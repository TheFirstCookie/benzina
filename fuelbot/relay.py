"""Fetch fresh ANRE data locally and dispatch the GitHub reporting workflow."""
import argparse
from dataclasses import replace
from datetime import datetime
import json
import logging
import os
import subprocess
import sys
from zoneinfo import ZoneInfoNotFoundError

import requests

from .config import Settings, URLS
from .diagnostics import Diagnostics
from .models import FuelHistory
from .sources import fetch_anre
from .storage import GitHubLedger, is_blocked
from .validation import encode_history


def github_headers():
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n", text=True,
        capture_output=True, check=True, timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if not fields.get("password"):
        raise RuntimeError("No saved GitHub credential; sign into Git first")
    return {"Authorization": "Bearer " + fields["password"], "Accept": "application/vnd.github+json"}


def dispatch(settings, diagnostics=None, *, dry_run=False, prepare_only=False, clock=None):
    diagnostics = diagnostics or Diagnostics(settings)
    now = clock() if clock else datetime.now(settings.timezone)
    if now.weekday() >= 5:
        diagnostics.set_stage("weekend skipped")
        diagnostics.summary("skipped", "Weekend: no scheduled report")
        return
    headers = None
    if not prepare_only:
        diagnostics.set_stage("GitHub authentication")
        headers = github_headers()
        if not dry_run:
            diagnostics.set_stage("check durable delivery record")
            ledger = GitHubLedger(settings.github_repository, headers["Authorization"].removeprefix("Bearer "),
                                  settings.delivery_branch)
            record = ledger.get(now.date().isoformat())
            if is_blocked(record):
                diagnostics.set_stage("delivery skipped")
                diagnostics.summary("skipped", f"Today's delivery status is {record['status']}")
                return
    histories = []
    for name, url in URLS.items():
        diagnostics.set_stage("fetch " + name)
        histories.append(tuple(fetch_anre(url, settings.diagnostics_dir)))
    diagnostics.set_stage("validate official publication history")
    payload = encode_history(FuelHistory(*histories), now)
    settings.diagnostics_dir.mkdir(parents=True, exist_ok=True)
    (settings.diagnostics_dir / "relay-history.json").write_text(json.dumps(payload), encoding="utf-8")
    if prepare_only:
        diagnostics.set_stage("relay validation complete")
        diagnostics.summary("success", "Fresh official ANRE history validated; no workflow dispatched")
        return
    diagnostics.set_stage("dispatch GitHub workflow")
    response = requests.post(
        f"https://api.github.com/repos/{settings.github_repository}/actions/workflows/pret_carburanti.yml/dispatches",
        headers=headers, json={"ref": "main", "inputs": {"dry_run": dry_run, "automated": True,
                                                         "history_json": json.dumps(payload)}}, timeout=(10, 30))
    response.raise_for_status()
    diagnostics.set_stage("GitHub dispatch accepted")
    diagnostics.summary("success", f"GitHub accepted dispatch; Telegram delivery is not yet confirmed. Dry run: {dry_run}")


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Dispatch a workflow without Telegram delivery")
    parser.add_argument("--prepare-only", action="store_true", help="Validate locally without dispatching")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except (ValueError, ZoneInfoNotFoundError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1
    settings = replace(settings, diagnostics_dir=settings.diagnostics_dir / "relay")
    diagnostics = Diagnostics(settings)
    diagnostics.setup_logging()
    try:
        dispatch(settings, diagnostics, dry_run=args.dry_run, prepare_only=args.prepare_only)
        return 0
    except Exception as error:
        logging.exception("Local ANRE dispatch failed at stage: %s", diagnostics.stage)
        diagnostics.summary("FAILED", f"{type(error).__name__}: {error}", error)
        return 1
