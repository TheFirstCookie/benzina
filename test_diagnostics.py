import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fuelbot.config import Settings
from fuelbot.diagnostics import Diagnostics, SafeFormatter, failure_kind
from fuelbot.storage import StorageError
from fuelbot.telegram import TelegramRejected, TelegramUncertain
from fuelbot.validation import InvalidHistory


class DiagnosticsTests(unittest.TestCase):
    def test_all_credentials_are_redacted_in_tracebacks_and_both_summaries(self):
        secrets = ("private-bot-token", "private-chat-id", "private-github-token")
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(bot_token=secrets[0], chat_id=secrets[1], github_token=secrets[2],
                                diagnostics_dir=Path(directory))
            diagnostics = Diagnostics(settings)
            diagnostics.set_stage("send Telegram photo")
            try:
                raise TelegramUncertain(" ".join(secrets))
            except TelegramUncertain as error:
                record = logging.LogRecord("bot", logging.ERROR, "", 0, "failed", (), __import__("sys").exc_info())
                rendered = SafeFormatter(secrets=secrets).format(record)
                with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(Path(directory) / "github.txt")}):
                    diagnostics.summary("FAILED", str(error), error)
            for path in Path(directory).iterdir():
                rendered += path.read_text(encoding="utf-8")
            for secret in secrets:
                self.assertNotIn(secret, rendered)
            summary = json.loads((Path(directory) / "summary.json").read_text())
            self.assertEqual(summary["failure_kind"], "telegram_uncertain")
            self.assertEqual(summary["events"][0]["stage"], "send Telegram photo")

    def test_failures_have_distinct_actionable_categories(self):
        for error, expected in ((TelegramRejected("403"), "telegram_rejected"),
                                (TelegramUncertain("timeout"), "telegram_uncertain"),
                                (InvalidHistory("stale"), "invalid_data"),
                                (StorageError("offline"), "delivery_storage"),
                                (ValueError("SEND_AT"), "configuration")):
            with self.subTest(error=error):
                self.assertEqual(failure_kind(error), expected)
