from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fuelbot.config import Settings
from fuelbot import relay
from tests.helpers import NOW, history


class RelayTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""})
        environment.start()
        self.addCleanup(environment.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(diagnostics_dir=Path(directory.name))

    def dispatch(self, **kwargs):
        return relay.dispatch(self.settings, clock=lambda: NOW.replace(hour=12, minute=43), **kwargs)

    @patch("fuelbot.relay.github_headers", return_value={"Authorization": "Bearer fake"})
    @patch("fuelbot.relay.GitHubLedger")
    @patch("fuelbot.relay.fetch_anre")
    @patch("fuelbot.relay.requests.post")
    def test_durable_marker_skips_fetch_and_dispatch(self, post, fetch, ledger, headers):
        ledger.return_value.get.return_value = {"status": "sent", "message_id": 42}
        self.dispatch()
        fetch.assert_not_called()
        post.assert_not_called()
        ledger.return_value.get.assert_called_once_with("2026-11-05")

    @patch("fuelbot.relay.github_headers")
    @patch("fuelbot.relay.requests.post")
    def test_weekend_does_not_dispatch(self, post, headers):
        relay.dispatch(self.settings, clock=lambda: NOW + timedelta(days=2))
        headers.assert_not_called()
        post.assert_not_called()

    @patch("fuelbot.relay.github_headers", return_value={"Authorization": "Bearer fake"})
    @patch("fuelbot.relay.GitHubLedger")
    @patch("fuelbot.relay.fetch_anre")
    @patch("fuelbot.relay.requests.post")
    def test_dry_run_dispatches_fresh_official_data_without_delivery_state(self, post, fetch, ledger, headers):
        data = history()
        fetch.side_effect = [data.petrol, data.diesel]
        self.dispatch(dry_run=True)
        ledger.assert_not_called()
        inputs = post.call_args.kwargs["json"]["inputs"]
        self.assertTrue(inputs["dry_run"])
        self.assertTrue(inputs["automated"])
        self.assertEqual(json.loads(inputs["history_json"])["source"]["published_date"], "2026-11-05")
        self.assertEqual(fetch.call_count, 2)

    @patch("fuelbot.relay.github_headers")
    @patch("fuelbot.relay.fetch_anre")
    @patch("fuelbot.relay.requests.post")
    def test_prepare_only_needs_neither_credentials_nor_dispatch(self, post, fetch, headers):
        data = history()
        fetch.side_effect = [data.petrol, data.diesel]
        self.dispatch(prepare_only=True)
        headers.assert_not_called()
        post.assert_not_called()
        self.assertTrue((self.settings.diagnostics_dir / "relay-history.json").exists())

    @patch("fuelbot.relay.subprocess.run")
    def test_credentials_stay_out_of_command_line_and_require_no_prompt(self, run):
        run.return_value.stdout = "username=TheFirstCookie\npassword=fake-secret\n"
        headers = relay.github_headers()
        self.assertEqual(headers["Authorization"], "Bearer fake-secret")
        self.assertNotIn("fake-secret", str(run.call_args))
        self.assertEqual(run.call_args.kwargs["env"]["GCM_INTERACTIVE"], "never")
