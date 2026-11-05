import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import fuelbot.app as bot
import dispatch_prices


class DispatchTests(unittest.TestCase):
    def setUp(self):
        clock = patch("fuelbot.app.datetime", wraps=datetime)
        self.clock = clock.start()
        self.clock.now.return_value = datetime(2026, 11, 5, 12, 43, tzinfo=bot.TIMEZONE)
        self.addCleanup(clock.stop)

    @patch("dispatch_prices.github_headers", return_value={"Authorization": "Bearer fake"})
    @patch("dispatch_prices.requests.get")
    @patch("fuelbot.app.get_table_rows")
    @patch("dispatch_prices.requests.post")
    def test_delivery_marker_skips_fetch_and_dispatch(self, post, fetch, get, headers):
        get.return_value.json.return_value = {"actions_caches": [{"key": "sent-2026-11-05"}]}
        dispatch_prices.dispatch()
        fetch.assert_not_called()
        post.assert_not_called()
        self.assertEqual(get.call_args.kwargs["params"]["ref"], "refs/heads/main")

    @patch("dispatch_prices.github_headers")
    @patch("dispatch_prices.requests.get")
    @patch("dispatch_prices.requests.post")
    def test_weekend_does_not_dispatch(self, post, get, headers):
        self.clock.now.return_value = datetime(2026, 11, 7, 12, 43, tzinfo=bot.TIMEZONE)
        dispatch_prices.dispatch()
        headers.assert_not_called()
        get.assert_not_called()
        post.assert_not_called()

    @patch("dispatch_prices.github_headers", return_value={"Authorization": "Bearer fake"})
    @patch("fuelbot.app.history_payload", return_value={"source": {"published_date": "2026-11-05"}})
    @patch("fuelbot.app.get_table_rows", return_value=["rows"])
    @patch("dispatch_prices.requests.post")
    @patch("dispatch_prices.requests.get")
    def test_dry_run_uses_fresh_history_and_cannot_mark_real_delivery(self, get, post, fetch, payload, headers):
        with patch.object(bot, "DIAGNOSTICS_DIR") as directory:
            directory.__truediv__.return_value = Mock()
            dispatch_prices.dispatch(dry_run=True)
        get.assert_not_called()
        inputs = post.call_args.kwargs["json"]["inputs"]
        self.assertTrue(inputs["dry_run"])
        self.assertTrue(inputs["automated"])
        self.assertEqual(json.loads(inputs["history_json"]), payload.return_value)
        self.assertEqual(fetch.call_count, 2)

    @patch("dispatch_prices.subprocess.run")
    def test_credentials_stay_out_of_command_line_and_require_no_prompt(self, run):
        run.return_value.stdout = "username=TheFirstCookie\npassword=fake-secret\n"
        headers = dispatch_prices.github_headers()
        self.assertEqual(headers["Authorization"], "Bearer fake-secret")
        self.assertNotIn("fake-secret", str(run.call_args))
        self.assertEqual(run.call_args.kwargs["env"]["GCM_INTERACTIVE"], "never")


if __name__ == "__main__":
    unittest.main()
