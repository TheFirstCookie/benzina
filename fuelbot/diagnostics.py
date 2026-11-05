"""Redacted logs and machine-readable summaries for each run."""
from datetime import datetime, timezone
import json
import logging
import os
import sqlite3
import time

import requests

from .storage import StorageError
from .telegram import TelegramRejected, TelegramUncertain
from .validation import InvalidHistory


def redact(text, secrets):
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


class SafeFormatter(logging.Formatter):
    converter = time.gmtime

    def __init__(self, fmt=None, secrets=()):
        super().__init__(fmt)
        self.secrets = secrets

    def format(self, record):
        return redact(super().format(record), self.secrets)


def failure_kind(error):
    # More specific errors must precede their ValueError/RuntimeError bases.
    if isinstance(error, TelegramRejected):
        return "telegram_rejected"
    if isinstance(error, TelegramUncertain):
        return "telegram_uncertain"
    if isinstance(error, (StorageError, sqlite3.Error)):
        return "delivery_storage"
    if isinstance(error, InvalidHistory):
        return "invalid_data"
    from .sources import SourceUnavailable
    if isinstance(error, SourceUnavailable):
        return "source_unavailable"
    if isinstance(error, requests.RequestException):
        return "network"
    if isinstance(error, ValueError):
        return "configuration"
    return "internal"


class Diagnostics:
    def __init__(self, settings):
        self.settings = settings
        self.stage = "startup"
        self.events = []

    @property
    def secrets(self):
        return (self.settings.bot_token, self.settings.chat_id, self.settings.github_token)

    def setup_logging(self, debug=False):
        directory = self.settings.diagnostics_dir
        directory.mkdir(parents=True, exist_ok=True)
        formatter = SafeFormatter("%(asctime)sZ %(levelname)s %(message)s", self.secrets)
        handlers = [logging.StreamHandler(), logging.FileHandler(directory / "bot.log", encoding="utf-8")]
        for handler in handlers:
            handler.setFormatter(formatter)
        logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers, force=True)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("matplotlib").setLevel(logging.WARNING)

    def set_stage(self, stage):
        self.stage = stage
        self.events.append({"stage": stage, "at": datetime.now(timezone.utc).isoformat()})
        logging.info("Stage: %s", stage)

    def save_report(self, report):
        directory = self.settings.diagnostics_dir
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "chart.png").write_bytes(report.chart)
        (directory / "caption.txt").write_text(report.caption, encoding="utf-8")

    def summary(self, status, detail, error=None):
        directory = self.settings.diagnostics_dir
        directory.mkdir(parents=True, exist_ok=True)
        kind = failure_kind(error) if error else None
        text = redact(f"Bot: {status}\nStage: {self.stage}\nFailure kind: {kind or 'none'}\n{detail}\n", self.secrets)
        structured = {"status": status, "stage": self.stage, "failure_kind": kind,
                      "detail": detail, "events": self.events}
        (directory / "summary.txt").write_text(text, encoding="utf-8")
        (directory / "summary.json").write_text(redact(json.dumps(structured, indent=2), self.secrets), encoding="utf-8")
        destination = os.environ.get("GITHUB_STEP_SUMMARY")
        if destination:
            with open(destination, "a", encoding="utf-8") as output:
                output.write("\n```text\n" + text + "```\n")
