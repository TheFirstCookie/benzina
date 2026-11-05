import argparse
import json
import math
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import io
import time
import logging

from fuelbot.config import (
    Settings, URLS, HISTORY_MIRROR_URL, REQUEST_TIMEOUT, CONNECT_TIMEOUT,
    FETCH_ATTEMPTS, FETCH_RETRY_DELAY, MIRROR_ATTEMPTS,
)

_settings = Settings.from_env()
BOT_TOKEN = _settings.bot_token
CHAT_ID = _settings.chat_id
TIMEZONE = _settings.timezone
SEND_AT = _settings.send_at
DIAGNOSTICS_DIR = _settings.diagnostics_dir
STAGE = "startup"


from fuelbot import sources, reports, telegram, scheduler
from fuelbot.reports import get_history, get_latest, format_date, get_weekly_change, make_chart, format_block, format_weekly
from fuelbot.models import PricePoint, FuelHistory
from fuelbot.parsing import LUNI, parse_date, parse_price


def log_dns(url):
    return sources.log_dns(url)


def fetch_table_rows(url):
    return sources.fetch_table_rows(url, DIAGNOSTICS_DIR)


def get_table_rows(url):
    return sources.get_table_rows(url, DIAGNOSTICS_DIR, fetch=fetch_table_rows)


def fetch_mirrored_history():
    return sources.fetch_mirrored_history(parse_mirrored_history, DIAGNOSTICS_DIR)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        # requests exceptions include the Telegram URL, which contains the token.
        message = super().format(record)
        for secret in (BOT_TOKEN, CHAT_ID):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        return message


def setup_logging(debug=False):
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    formatter = SafeFormatter("%(asctime)s %(levelname)s %(message)s")
    handlers = [logging.StreamHandler(), logging.FileHandler(
        DIAGNOSTICS_DIR / "bot.log", encoding="utf-8")]
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        handlers=handlers, force=True)
    # Avoid verbose library HTTP logs, especially Telegram URLs with credentials.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def set_stage(stage):
    global STAGE
    STAGE = stage
    logging.info("Stage: %s", stage)


def write_summary(status, detail):
    text = f"Bot: {status}\nStage: {STAGE}\n{detail}\n"
    for secret in (BOT_TOKEN, CHAT_ID):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    (DIAGNOSTICS_DIR / "summary.txt").write_text(text, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write("\n```text\n" + text + "```\n")


from fuelbot import validation


def expected_publication_date():
    return validation.expected_publication_date(datetime.now(TIMEZONE))


def parse_mirrored_history(payload):
    history = validation.decode_history(payload, datetime.now(TIMEZONE))
    return history.petrol, history.diesel


def validate_histories(histories):
    return validation.validate_history(FuelHistory(tuple(histories[0]), tuple(histories[1])), datetime.now(TIMEZONE))


def history_payload(histories):
    history = FuelHistory(tuple(histories[0]), tuple(histories[1]))
    return validation.encode_history(history, datetime.now(TIMEZONE))


def complete_report(chart, caption, detail, dry_run):
    (DIAGNOSTICS_DIR / "chart.png").write_bytes(chart.getvalue())
    (DIAGNOSTICS_DIR / "caption.txt").write_text(caption, encoding="utf-8")
    if dry_run:
        set_stage("dry run complete")
    else:
        set_stage("send Telegram photo")
        send_photo_telegram(chart, caption)
        set_stage("Telegram delivery confirmed")
    write_summary("success", f"{detail}\nDry run: {dry_run}")


def send_photo_telegram(image_buf, caption):
    return telegram.send_photo(Settings(bot_token=BOT_TOKEN, chat_id=CHAT_ID), image_buf.getvalue(), caption)


def wait_until_send_time(lead_seconds=0):
    return scheduler.wait_until_send_time(
        Settings(send_at=SEND_AT, timezone=TIMEZONE), lead_seconds, now=datetime.now(TIMEZONE))


def main(dry_run=False, scheduled=False):
    set_stage("configuration")
    if not dry_run:
        missing = [name for name, value in (("BOT_TOKEN", BOT_TOKEN), ("CHAT_ID", CHAT_ID))
                   if not value.strip()]
        if missing:
            raise RuntimeError("Missing GitHub Actions secrets: " + ", ".join(missing))
    logging.info("Python=%s timezone=%s send_at=%s dry_run=%s event=%s run_id=%s",
                 sys.version.split()[0], TIMEZONE, SEND_AT or "immediate", dry_run,
                 os.environ.get("GITHUB_EVENT_NAME", "local"),
                 os.environ.get("GITHUB_RUN_ID", "local"))
    def deliver(report):
        return complete_report(io.BytesIO(report.chart), report.caption, report.detail, dry_run)
    if scheduled:
        return scheduler.run(prepare_report, deliver,
                             Settings(send_at=SEND_AT, timezone=TIMEZONE), dry_run=dry_run)
    return deliver(prepare_report())


def prepare_report():
    today = datetime.now(TIMEZONE)
    logging.info("Rulez botul pentru data locala: %s", today.date())

    mirrored = False
    supplied_history = os.environ.get("ANRE_HISTORY_JSON", "").strip()
    if supplied_history:
        set_stage("validate supplied ANRE publication history")
        b_rows, m_rows = parse_mirrored_history(json.loads(supplied_history))
    else:
        try:
            set_stage("fetch Benzina 95")
            b_rows = get_table_rows(URLS["Benzina 95"])
            set_stage("fetch Motorina")
            m_rows = get_table_rows(URLS["Motorina"])
            validate_histories((b_rows, m_rows))
        except (requests.RequestException, RuntimeError, ValueError) as error:
            logging.warning("Direct ANRE history unavailable; trying publication-history mirror: %s", error)
            set_stage("fetch mirrored ANRE publication history")
            b_rows, m_rows = fetch_mirrored_history()
            mirrored = True

    set_stage("generate chart and caption")
    history = FuelHistory(tuple(b_rows), tuple(m_rows), HISTORY_MIRROR_URL if mirrored else "ANRE direct")
    report = reports.build_report(history, today)
    return report


def cli():
    parser = argparse.ArgumentParser(description="ANRE fuel prices to Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and chart without sending to Telegram")
    parser.add_argument("--debug", action="store_true", help="Enable application debug logging")
    parser.add_argument("--scheduled", action="store_true", help="Wait until SEND_AT outside the reporting worker")
    args = parser.parse_args()
    setup_logging(args.debug)
    try:
        main(dry_run=args.dry_run, scheduled=args.scheduled or bool(SEND_AT))
    except Exception as error:
        logging.exception("Bot failed at stage: %s", STAGE)
        write_summary("FAILED", f"{type(error).__name__}: {error}")
        sys.exit(1)
