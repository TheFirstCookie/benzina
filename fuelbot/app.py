"""Application orchestration with explicit configuration and service boundaries."""
import argparse
from datetime import datetime
import json
import logging
import os
import sys
from zoneinfo import ZoneInfoNotFoundError

import requests

from . import reports, scheduler, sources, telegram
from .config import Settings, URLS
from .delivery import deliver_once
from .diagnostics import Diagnostics, redact
from .models import FuelHistory
from .storage import is_blocked, make_ledger
from .validation import InvalidHistory, decode_history, expected_publication_date, iso_date, validate_history


def fetch_history(settings, diagnostics, now, history_json=None):
    if history_json:
        diagnostics.set_stage("validate supplied ANRE publication history")
        try:
            payload = json.loads(history_json)
        except (ValueError, TypeError) as error:
            raise InvalidHistory("Supplied ANRE history is not valid JSON") from error
        return decode_history(payload, now)
    try:
        diagnostics.set_stage("fetch Benzina 95")
        petrol = sources.fetch_anre(URLS["Benzina 95"], settings.diagnostics_dir)
        diagnostics.set_stage("fetch Motorina")
        diesel = sources.fetch_anre(URLS["Motorina"], settings.diagnostics_dir)
        return validate_history(FuelHistory(tuple(petrol), tuple(diesel)), now)
    except (sources.SourceUnavailable, requests.RequestException, InvalidHistory) as error:
        logging.warning("Direct ANRE history unavailable; trying publication-history mirror: %s", error)
        diagnostics.set_stage("fetch mirrored ANRE publication history")
        return sources.fetch_mirror(now, settings.diagnostics_dir)


def prepare_report(settings, diagnostics, now, history_json=None):
    history = fetch_history(settings, diagnostics, now, history_json)
    diagnostics.set_stage("generate chart and caption")
    report = reports.build_report(history, now)
    diagnostics.save_report(report)
    return report


def deliver_report(report, settings, diagnostics, now, dry_run=False, force=False, ledger=None):
    if report.published_date != expected_publication_date(now):
        raise InvalidHistory("Prepared report became stale before delivery")
    if dry_run:
        diagnostics.set_stage("dry run complete")
        diagnostics.summary("success", report.detail + "\nDry run: True")
        return None
    settings.require_telegram()
    ledger = ledger if ledger is not None else make_ledger(settings)
    diagnostics.set_stage("reserve delivery")

    def send():
        diagnostics.set_stage("send Telegram photo")
        return telegram.send_photo(settings, report.chart, report.caption)

    message_id = deliver_once(ledger, now.date().isoformat(), send, force=force)
    if message_id is None:
        diagnostics.set_stage("delivery skipped")
        diagnostics.summary("skipped", "Existing delivery reservation prevents a duplicate")
    else:
        diagnostics.set_stage("Telegram delivery confirmed")
        diagnostics.summary("success", f"{report.detail}\nMessage ID: {message_id}\nDry run: False")
    return message_id


def run(settings, diagnostics=None, *, dry_run=False, scheduled=False, force=False,
        history_json=None, ledger=None, clock=None):
    diagnostics = diagnostics or Diagnostics(settings)
    clock = clock or (lambda: datetime.now(settings.timezone))
    diagnostics.set_stage("configuration")
    if not dry_run:
        settings.require_telegram()
        ledger = ledger if ledger is not None else make_ledger(settings)
        if not force:
            record = ledger.get(clock().date().isoformat())
            if is_blocked(record):
                diagnostics.set_stage("delivery skipped")
                diagnostics.summary("skipped", f"Existing durable delivery status: {record['status']}")
                return None
    logging.info("Python=%s timezone=%s send_at=%s dry_run=%s event=%s run_id=%s",
                 sys.version.split()[0], settings.timezone, settings.send_at or "immediate", dry_run,
                 os.environ.get("GITHUB_EVENT_NAME", "local"), os.environ.get("GITHUB_RUN_ID", "local"))

    def prepare():
        return prepare_report(settings, diagnostics, clock(), history_json)

    def deliver(report):
        return deliver_report(report, settings, diagnostics, clock(), dry_run, force, ledger)

    if scheduled:
        return scheduler.run(prepare, deliver, settings, dry_run=dry_run)
    return deliver(prepare())


def cli(argv=None):
    parser = argparse.ArgumentParser(description="ANRE fuel prices to Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and chart without sending or recording delivery")
    parser.add_argument("--debug", action="store_true", help="Enable detailed application logging")
    parser.add_argument("--scheduled", action="store_true", help="Let the scheduler wait until SEND_AT")
    parser.add_argument("--force", action="store_true", help="Explicitly resend despite a delivery record")
    parser.add_argument("--delivery-status", metavar="YYYY-MM-DD", help="Inspect a durable delivery record without sending")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except (ValueError, ZoneInfoNotFoundError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1
    diagnostics = Diagnostics(settings)
    diagnostics.setup_logging(args.debug)
    try:
        if args.delivery_status:
            key = iso_date(args.delivery_status).date().isoformat()
            diagnostics.set_stage("inspect delivery status")
            record = make_ledger(settings).get(key)
            print(redact(json.dumps(record, indent=2), diagnostics.secrets))
            diagnostics.summary("success", f"Inspected delivery status for {key}; no Telegram request made")
        else:
            run(settings, diagnostics, dry_run=args.dry_run, scheduled=args.scheduled or bool(settings.send_at),
                force=args.force, history_json=os.environ.get("ANRE_HISTORY_JSON", "").strip())
        return 0
    except Exception as error:
        logging.exception("Bot failed at stage: %s", diagnostics.stage)
        diagnostics.summary("FAILED", f"{type(error).__name__}: {error}", error)
        return 1
