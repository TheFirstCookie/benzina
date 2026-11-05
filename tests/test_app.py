from dataclasses import replace
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fuelbot import app
from fuelbot.config import HISTORY_MIRROR_URL, Settings
from fuelbot.diagnostics import Diagnostics
from fuelbot.sources import SourceUnavailable
from fuelbot.storage import SQLiteLedger
from fuelbot.telegram import TelegramUncertain
from fuelbot.validation import InvalidHistory
from tests.helpers import NOW, history, payload


class AppTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        directory = Path(self.directory.name)
        self.settings = Settings(bot_token="fake-token", chat_id="12345", diagnostics_dir=directory,
                                 state_path=directory / "deliveries.sqlite3", send_at="12:50")
        self.diagnostics = Diagnostics(self.settings)
        self.clock = lambda: NOW

    def run_report(self, **kwargs):
        return app.run(self.settings, self.diagnostics, clock=self.clock, **kwargs)

    def summary(self):
        return json.loads((self.settings.diagnostics_dir / "summary.json").read_text())

    @patch("fuelbot.app.make_ledger")
    @patch("fuelbot.telegram.send_photo")
    @patch("fuelbot.scheduler.wait_until_send_time")
    @patch("fuelbot.sources.fetch_anre")
    def test_dry_run_never_waits_sends_or_creates_delivery_state(self, fetch, wait, send, ledger):
        data = history()
        fetch.side_effect = [data.petrol, data.diesel]
        self.run_report(dry_run=True, scheduled=True)
        wait.assert_not_called()
        send.assert_not_called()
        ledger.assert_not_called()
        self.assertFalse(self.settings.state_path.exists())
        self.assertEqual(self.summary()["stage"], "dry run complete")
        self.assertTrue((self.settings.diagnostics_dir / "chart.png").read_bytes().startswith(b"\x89PNG"))

    @patch("fuelbot.sources.fetch_anre")
    @patch("fuelbot.sources.fetch_mirror")
    def test_outage_of_either_product_uses_one_complete_mirror_history(self, mirror, fetch):
        data = history(source=HISTORY_MIRROR_URL)
        mirror.return_value = data
        for failures in ([SourceUnavailable("petrol timeout")],
                         [data.petrol, SourceUnavailable("diesel timeout")]):
            with self.subTest(failures=failures):
                fetch.side_effect = failures
                self.run_report(dry_run=True)
                caption = (self.settings.diagnostics_dir / "caption.txt").read_text(encoding="utf-8")
                self.assertIn("32.45 lei/litru", caption)
                self.assertIn("35.88 lei/litru", caption)
                self.assertIn("logos-pres.md", caption)

    @patch("fuelbot.sources.fetch_anre")
    @patch("fuelbot.sources.fetch_mirror")
    def test_stale_direct_history_also_uses_the_validated_fallback(self, mirror, fetch):
        old = history(NOW - timedelta(days=1))
        fetch.side_effect = [old.petrol, old.diesel]
        mirror.return_value = history(source=HISTORY_MIRROR_URL)
        self.run_report(dry_run=True)
        mirror.assert_called_once()

    @patch("fuelbot.sources.fetch_anre")
    @patch("fuelbot.sources.fetch_mirror")
    def test_supplied_history_needs_no_source_network_requests(self, mirror, fetch):
        self.run_report(dry_run=True, history_json=json.dumps(payload()))
        mirror.assert_not_called()
        fetch.assert_not_called()
        self.assertIn("ANRE relay", self.summary()["detail"])
        caption = (self.settings.diagnostics_dir / "caption.txt").read_text(encoding="utf-8")
        self.assertNotIn("logos-pres.md", caption)

    @patch("fuelbot.telegram.send_photo")
    def test_malformed_or_stale_supplied_data_cannot_send(self, send):
        for data in ("{", "null", json.dumps(payload(NOW - timedelta(days=1)))):
            with self.subTest(data=data), self.assertRaises(InvalidHistory):
                self.run_report(dry_run=True, history_json=data)
        send.assert_not_called()

    @patch("fuelbot.telegram.send_photo", return_value=42)
    @patch("fuelbot.scheduler.wait_until_send_time")
    def test_scheduled_delivery_prepares_then_waits_and_records_confirmed_id(self, wait, send):
        events = []
        wait.side_effect = lambda *args, **kw: events.append("prepare wait" if kw else "send wait")
        send.side_effect = lambda *args: (events.append("send"), 42)[1]
        ledger = SQLiteLedger(self.settings.state_path)
        self.assertEqual(self.run_report(scheduled=True, ledger=ledger, history_json=json.dumps(payload())), 42)
        self.assertEqual(events, ["prepare wait", "send wait", "send"])
        self.assertEqual(ledger.get("2026-11-05")["message_id"], 42)
        self.assertEqual(self.summary()["stage"], "Telegram delivery confirmed")
        # A second invocation skips before scraping or preparing a report.
        with patch("fuelbot.app.prepare_report") as prepare:
            self.run_report(ledger=SQLiteLedger(self.settings.state_path))
        prepare.assert_not_called()
        send.assert_called_once()
        self.assertEqual(self.summary()["status"], "skipped")

    @patch("fuelbot.telegram.send_photo", side_effect=TelegramUncertain("timeout"))
    def test_ambiguous_timeout_is_not_a_success_and_blocks_later_runs(self, send):
        ledger = SQLiteLedger(self.settings.state_path)
        with self.assertRaises(TelegramUncertain):
            self.run_report(ledger=ledger, history_json=json.dumps(payload()))
        self.assertEqual(ledger.get("2026-11-05")["status"], "uncertain")
        self.run_report(ledger=ledger)
        send.assert_called_once()
        self.assertEqual(self.summary()["status"], "skipped")

    @patch("fuelbot.sources.fetch_anre")
    def test_missing_credentials_fail_before_any_network_request(self, fetch):
        with self.assertRaisesRegex(ValueError, "BOT_TOKEN.*CHAT_ID"):
            app.run(replace(self.settings, bot_token="", chat_id=""), clock=self.clock)
        fetch.assert_not_called()

    @patch("fuelbot.telegram.send_photo")
    def test_midnight_rollover_cannot_send_yesterdays_prepared_report(self, send):
        times = iter([NOW, NOW, NOW + timedelta(days=1)])
        with self.assertRaisesRegex(InvalidHistory, "became stale"):
            app.run(self.settings, self.diagnostics, clock=lambda: next(times),
                    ledger=SQLiteLedger(self.settings.state_path), history_json=json.dumps(payload()))
        send.assert_not_called()

    @patch("fuelbot.diagnostics.Diagnostics.setup_logging")
    @patch("fuelbot.app.Settings.from_env")
    @patch("fuelbot.sources.fetch_anre", side_effect=SourceUnavailable("ANRE down"))
    @patch("fuelbot.sources.fetch_mirror", side_effect=SourceUnavailable("mirror down"))
    def test_cli_failure_records_source_category_and_nonzero_exit(self, mirror, fetch, settings, logging):
        settings.return_value = replace(self.settings, send_at="")
        with patch("fuelbot.app.logging.exception"), patch.dict("os.environ", {"ANRE_HISTORY_JSON": ""}):
            self.assertEqual(app.cli(["--dry-run"]), 1)
        self.assertEqual(self.summary()["failure_kind"], "source_unavailable")
        self.assertEqual(self.summary()["stage"], "fetch mirrored ANRE publication history")

    @patch("fuelbot.diagnostics.Diagnostics.setup_logging")
    @patch("fuelbot.app.Settings.from_env")
    @patch("fuelbot.sources.fetch_anre")
    def test_status_command_inspects_existing_record_without_sending(self, fetch, settings, logging):
        settings.return_value = self.settings
        ledger = SQLiteLedger(self.settings.state_path)
        reservation = ledger.reserve("2026-11-05")
        ledger.finish(reservation, "sent", 42)
        with patch("sys.stdout", new_callable=io.StringIO) as output, patch("fuelbot.app.make_ledger", return_value=ledger):
            self.assertEqual(app.cli(["--delivery-status", "2026-11-05"]), 0)
        self.assertEqual(json.loads(output.getvalue())["message_id"], 42)
        fetch.assert_not_called()

    @patch("fuelbot.app.Settings.from_env", side_effect=ValueError("SEND_AT must use HH:MM"))
    def test_cli_reports_invalid_configuration_without_a_traceback(self, settings):
        with patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(app.cli(["--dry-run"]), 1)
        self.assertIn("Configuration error: SEND_AT", error.getvalue())
