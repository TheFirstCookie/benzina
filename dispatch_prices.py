"""Fetch ANRE from a reachable computer and dispatch the Telegram workflow."""
import argparse
import json
import logging
import os
from pathlib import Path
import subprocess

import requests

import bot


API = "https://api.github.com/repos/TheFirstCookie/benzina"


def github_headers():
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n", text=True,
        capture_output=True, check=True, timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if not fields.get("password"):
        raise RuntimeError("No saved GitHub credential; sign into Git first")
    return {"Authorization": "Bearer " + fields["password"],
            "Accept": "application/vnd.github+json"}


def dispatch(dry_run=False, prepare_only=False):
    now = bot.datetime.now(bot.TIMEZONE)
    if now.weekday() >= 5:
        logging.info("Weekend: no scheduled report")
        return
    headers = None
    if not prepare_only:
        headers = github_headers()
        if not dry_run:
            response = requests.get(API + "/actions/caches", headers=headers,
                                    params={"key": "sent-" + now.date().isoformat(),
                                            "ref": "refs/heads/main"}, timeout=30)
            response.raise_for_status()
            if response.json()["actions_caches"]:
                logging.info("Today's delivery is already recorded; skipping")
                return
    histories = [bot.get_table_rows(url) for url in bot.URLS.values()]
    payload = bot.history_payload(histories)
    (bot.DIAGNOSTICS_DIR / "relay-history.json").write_text(
        json.dumps(payload), encoding="utf-8")
    if prepare_only:
        logging.info("Validated fresh ANRE history; no workflow dispatched")
        return
    response = requests.post(
        API + "/actions/workflows/pret_carburanti.yml/dispatches", headers=headers,
        json={"ref": "main", "inputs": {"dry_run": dry_run,
              "automated": True, "history_json": json.dumps(payload)}}, timeout=30)
    response.raise_for_status()
    logging.info("GitHub accepted workflow dispatch: dry_run=%s publication=%s",
                 dry_run, payload["source"]["published_date"])


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    bot.DIAGNOSTICS_DIR = Path("diagnostics/relay")
    bot.setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Dispatch without Telegram delivery")
    parser.add_argument("--prepare-only", action="store_true", help="Validate locally without dispatching")
    args = parser.parse_args()
    try:
        dispatch(args.dry_run, args.prepare_only)
    except Exception:
        logging.exception("Local ANRE dispatch failed")
        raise SystemExit(1)
