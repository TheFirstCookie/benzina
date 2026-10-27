import io
import json
import logging
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import requests

import bot


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.diag = patch.object(bot, "DIAGNOSTICS_DIR", Path(self.temp.name))
        self.diag.start()
        self.addCleanup(self.diag.stop)

    def response(self, html, status=200):
        response = requests.Response()
        response.status_code = status
        response.url = bot.URLS["Benzina 95"]
        response._content = html.encode("utf-8")
        response.encoding = "utf-8"
        response.headers["Content-Type"] = "text/html"
        return response

    def current_prices(self):
        return {"date": bot.datetime.now(bot.TIMEZONE).strftime("%Y-%m-%d"),
                "b_pc": 32.22, "m_pc": 36.0}

    @patch("bot.requests.get")
    @patch("bot.get_table_rows", side_effect=RuntimeError("history connection timed out"))
    @patch("bot.wait_until_send_time")
    @patch("bot.send_photo_telegram")
    def test_history_outage_uses_official_caps_without_invented_comparisons(self, send, wait, fetch, get):
        prices = self.current_prices()
        get.return_value = self.response(json.dumps(prices))
        with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            bot.main(dry_run=True)
        self.assertEqual(get.call_args.args[0], bot.CURRENT_PRICES_URL)
        self.assertTrue((bot.DIAGNOSTICS_DIR / "chart.png").read_bytes().startswith(b"\x89PNG"))
        caption = (bot.DIAGNOSTICS_DIR / "caption.txt").read_text(encoding="utf-8")
        self.assertIn("Preturi in vigoare", caption)
        self.assertIn("32.22", caption)
        self.assertIn("36.00", caption)
        self.assertIn("ecarburanti.anre.md", caption)
        self.assertNotIn("fata de", caption)
        self.assertNotIn("Rezumat saptamana", caption)
        summary = (bot.DIAGNOSTICS_DIR / "summary.txt").read_text()
        self.assertIn("Bot: success", summary)
        self.assertIn("not publication history", summary)
        wait.assert_not_called()
        send.assert_not_called()

    @patch("bot.requests.get")
    @patch("bot.get_table_rows", side_effect=[["petrol history"], RuntimeError("diesel timeout")])
    def test_diesel_history_outage_uses_both_caps_from_same_api_snapshot(self, fetch, get):
        get.return_value = self.response(json.dumps(self.current_prices()))
        with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            bot.main(dry_run=True)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("32.22", (bot.DIAGNOSTICS_DIR / "caption.txt").read_text(encoding="utf-8"))

    @patch("bot.time.sleep")
    @patch("bot.requests.get")
    def test_current_api_retries_a_transient_connection_failure(self, get, sleep):
        prices = self.current_prices()
        get.side_effect = [requests.ConnectTimeout("timeout"), self.response(json.dumps(prices))]
        self.assertEqual(bot.fetch_current_prices(), prices)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(bot.FETCH_RETRY_DELAY)

    @patch("bot.requests.get")
    def test_current_api_rejects_stale_future_missing_or_invalid_prices(self, get):
        today = bot.datetime.now(bot.TIMEZONE).date()
        invalid = [
            {**self.current_prices(), "date": (today - timedelta(days=8)).isoformat()},
            {**self.current_prices(), "date": (today + timedelta(days=1)).isoformat()},
            {**self.current_prices(), "date": "not-a-date"},
            {**self.current_prices(), "b_pc": 0},
            {**self.current_prices(), "m_pc": -1},
            {**self.current_prices(), "b_pc": True},
            {**self.current_prices(), "b_pc": "32.22"},
            {**self.current_prices(), "m_pc": float("nan")},
            {**self.current_prices(), "m_pc": float("inf")},
            {"date": today.isoformat(), "b_pc": 32.22},
            [],
        ]
        with patch.object(bot, "CURRENT_PRICE_ATTEMPTS", 1):
            for payload in invalid:
                with self.subTest(payload=payload):
                    get.return_value = self.response(json.dumps(payload))
                    with self.assertRaisesRegex(RuntimeError, "fallback failed"):
                        bot.fetch_current_prices()
            get.return_value = self.response("<html>Maintenance</html>")
            with self.assertRaisesRegex(RuntimeError, "fallback failed"):
                bot.fetch_current_prices()

    @patch("bot.send_photo_telegram")
    @patch("bot.requests.get")
    @patch("bot.get_table_rows", side_effect=RuntimeError("history timeout"))
    def test_both_official_sources_failing_never_report_success(self, fetch, get, send):
        get.return_value = self.response("Service unavailable", 503)
        with patch.object(bot, "CURRENT_PRICE_ATTEMPTS", 1):
            with self.assertRaisesRegex(RuntimeError, "fallback failed"):
                bot.main(dry_run=True)
        send.assert_not_called()
        self.assertFalse((bot.DIAGNOSTICS_DIR / "summary.txt").exists())

    @patch("bot.send_photo_telegram")
    @patch("bot.wait_until_send_time")
    @patch("bot.requests.get")
    @patch("bot.get_table_rows", side_effect=RuntimeError("history timeout"))
    def test_fallback_delivery_is_confirmed_once_and_telegram_failures_propagate(self, fetch, get, wait, send):
        get.return_value = self.response(json.dumps(self.current_prices()))
        with patch.object(bot, "BOT_TOKEN", "fake-token"), patch.object(bot, "CHAT_ID", "123"), \
                patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            bot.main()
            send.assert_called_once()
            self.assertEqual(bot.STAGE, "Telegram delivery confirmed")
            (bot.DIAGNOSTICS_DIR / "summary.txt").unlink()
            send.reset_mock()
            send.side_effect = requests.ReadTimeout("ambiguous Telegram timeout")
            with self.assertRaises(requests.ReadTimeout):
                bot.main()
            send.assert_called_once()
            self.assertFalse((bot.DIAGNOSTICS_DIR / "summary.txt").exists())

    @patch("bot.requests.get")
    def test_parser_ignores_layout_and_headers_and_sorts_dates(self, get):
        get.return_value = self.response("""
            <table><tr><td>Menu</td><td>Help</td></tr></table>
            <table><tr><td>Date</td><td>PC</td></tr>
            <tr><td>23 octombrie 2026</td><td>32,45</td></tr>
            <tr><td>26 octombrie 2026</td><td>32,22</td></tr>
            <tr><td>22 octombrie 2026</td><td>unavailable</td></tr></table>
        """)
        rows = bot.fetch_table_rows(bot.URLS["Benzina 95"])
        latest = bot.get_latest(rows)
        self.assertEqual(latest["pret"], 32.22)
        self.assertEqual(latest["diferenta"], -0.23)
        dates, prices = bot.get_history(rows)
        self.assertLess(dates[0], dates[1])
        self.assertEqual(prices, [32.45, 32.22])

    @patch("bot.time.sleep")
    @patch("bot.fetch_table_rows")
    def test_connect_timeout_recovers_using_alternate_official_hostname(self, fetch, sleep):
        fetch.side_effect = [requests.ConnectTimeout("connection timed out"), ["rows"]]
        self.assertEqual(bot.get_table_rows(bot.URLS["Benzina 95"]), ["rows"])
        self.assertEqual(fetch.call_args_list[1].args[0], "https://www.anre.md/benzina-95-3-2")
        sleep.assert_called_once_with(bot.FETCH_RETRY_DELAY)

    @patch("bot.log_dns")
    @patch("bot.time.sleep")
    @patch("bot.fetch_table_rows", side_effect=requests.ReadTimeout("read timed out"))
    def test_exhausted_retries_report_failure_and_dns(self, fetch, sleep, dns):
        with patch.object(bot, "FETCH_ATTEMPTS", 2):
            with self.assertRaisesRegex(RuntimeError, "after 2 attempts: ReadTimeout"):
                bot.get_table_rows(bot.URLS["Benzina 95"])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(dns.call_count, 2)

    @patch("bot.requests.get")
    def test_missing_table_saves_response_for_debugging(self, get):
        get.return_value = self.response("<title>Maintenance</title><p>Try later</p>")
        with self.assertRaisesRegex(RuntimeError, "Maintenance"):
            bot.fetch_table_rows(bot.URLS["Benzina 95"])
        self.assertEqual(len(list(bot.DIAGNOSTICS_DIR.glob("*.html"))), 1)
        self.assertEqual(len(list(bot.DIAGNOSTICS_DIR.glob("*.json"))), 1)

    @patch("bot.requests.post")
    def test_telegram_rejection_is_not_success(self, post):
        post.return_value = self.response('{"ok":false,"description":"Forbidden"}', 403)
        with patch.object(bot, "BOT_TOKEN", "fake-token"), patch.object(bot, "CHAT_ID", "123"):
            with self.assertRaisesRegex(RuntimeError, "403.*Forbidden"):
                bot.send_photo_telegram(io.BytesIO(b"image"), "caption")

    def test_formatter_redacts_token_in_exception_traceback(self):
        with patch.object(bot, "BOT_TOKEN", "fake-secret"):
            try:
                raise requests.ConnectionError("https://api.telegram.org/botfake-secret/sendPhoto")
            except requests.ConnectionError:
                record = logging.LogRecord("bot", logging.ERROR, "", 0, "failed", (), __import__("sys").exc_info())
            rendered = bot.SafeFormatter().format(record)
        self.assertNotIn("fake-secret", rendered)
        self.assertIn("[REDACTED]", rendered)

    @patch("bot.get_table_rows")
    def test_missing_secrets_fail_before_network(self, fetch):
        with patch.object(bot, "BOT_TOKEN", ""), patch.object(bot, "CHAT_ID", ""):
            with self.assertRaisesRegex(RuntimeError, "Missing GitHub Actions secrets"):
                bot.main()
        fetch.assert_not_called()

    @patch("bot.send_photo_telegram")
    @patch("bot.wait_until_send_time")
    @patch("bot.get_table_rows")
    def test_dry_run_builds_chart_without_wait_or_telegram(self, fetch, wait, send):
        soup = bot.BeautifulSoup("""<table>
            <tr><td>26 octombrie 2026</td><td>32,22</td></tr>
            <tr><td>23 octombrie 2026</td><td>32,45</td></tr>
            </table>""", "html.parser")
        fetch.return_value = soup.find_all("tr")
        with patch.object(bot, "BOT_TOKEN", ""), patch.object(bot, "CHAT_ID", ""), \
                patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            bot.main(dry_run=True)
        wait.assert_not_called()
        send.assert_not_called()
        self.assertTrue((bot.DIAGNOSTICS_DIR / "chart.png").read_bytes().startswith(b"\x89PNG"))
        self.assertIn("Dry run: True", (bot.DIAGNOSTICS_DIR / "summary.txt").read_text())


if __name__ == "__main__":
    unittest.main()
