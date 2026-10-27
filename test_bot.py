import io
import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta
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

    def history_rows(self, prices):
        dates = ["23 octombrie 2026", "22 octombrie 2026", "21 octombrie 2026",
                 "20 octombrie 2026", "19 octombrie 2026", "16 octombrie 2026"]
        html = "<table>" + "".join(
            f"<tr><td>{date}</td><td>{price}</td></tr>"
            for date, price in zip(dates, prices)
        ) + "</table>"
        return bot.BeautifulSoup(html, "html.parser").find_all("tr")

    @patch("bot.send_photo_telegram")
    @patch("bot.wait_until_send_time")
    @patch("bot.get_table_rows")
    def test_original_friday_report_matches_telegram_caption(self, fetch, wait, send):
        fetch.side_effect = [self.history_rows([32.45, 32.72, 32.99, 33.21, 33.41, 33.53]),
                             self.history_rows([35.88, 35.90, 35.82, 35.57, 35.42, 35.22])]
        with patch("bot.datetime", wraps=datetime) as clock, \
                patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            clock.now.return_value = datetime(2026, 10, 23, 12, 50, tzinfo=bot.TIMEZONE)
            bot.main(dry_run=True)
        caption = (bot.DIAGNOSTICS_DIR / "caption.txt").read_text(encoding="utf-8")
        self.assertEqual(caption, "\n".join([
            "⛽ *Preturi Carburanti — ANRE Moldova*",
            "📅 23 octombrie 2026", "━━━━━━━━━━━━━━━━━━",
            "*Benzina 95*", "💰 Pret: `32.45 lei/litru`",
            "🔻 -0.27 lei fata de 22 octombrie 2026", "",
            "*Motorina*", "💰 Pret: `35.88 lei/litru`",
            "🔻 -0.02 lei fata de 22 octombrie 2026", "━━━━━━━━━━━━━━━━━━",
            "📊 *Rezumat saptamana:*", "Benzina 95: 🔻 -1.08 lei",
            "Motorina:   🔺 +0.66 lei", "_Sursa: anre.md/benzina-95-3-2_",
            "_Sursa: anre.md/motorina-3-3_",
        ]))
        self.assertTrue((bot.DIAGNOSTICS_DIR / "chart.png").read_bytes().startswith(b"\x89PNG"))
        wait.assert_not_called()
        send.assert_not_called()

    @patch("bot.fetch_mirrored_history", side_effect=RuntimeError("history unavailable"))
    @patch("bot.send_photo_telegram")
    @patch("bot.get_table_rows", side_effect=RuntimeError("history unavailable"))
    def test_history_failure_never_sends_a_different_report(self, fetch, send, mirror):
        with self.assertRaisesRegex(RuntimeError, "history unavailable"):
            bot.main(dry_run=True)
        send.assert_not_called()
        self.assertFalse((bot.DIAGNOSTICS_DIR / "summary.txt").exists())

    @patch("bot.fetch_mirrored_history", side_effect=RuntimeError("diesel timeout"))
    @patch("bot.send_photo_telegram")
    @patch("bot.get_table_rows")
    def test_diesel_failure_never_sends_partial_history(self, fetch, send, mirror):
        fetch.side_effect = [self.history_rows([32.45, 32.72]), RuntimeError("diesel timeout")]
        with self.assertRaisesRegex(RuntimeError, "diesel timeout"):
            bot.main(dry_run=True)
        send.assert_not_called()

    def mirrored_payload(self):
        today = datetime.now(bot.TIMEZONE).date()
        def product(prices):
            return {"current": prices[0], "change": round(prices[0] - prices[1], 2),
                    "history": [{"date": (today - timedelta(days=i)).isoformat(), "price": price}
                                for i, price in enumerate(prices)]}
        return {"source": {"name": "ANRE", "url": "https://anre.md/", "published_date": today.isoformat()},
                "products": {"gasoline_95": product([32.45, 32.72, 32.99, 33.21, 33.41, 33.53]),
                             "diesel": product([35.88, 35.90, 35.82, 35.57, 35.42, 35.22])}}

    @patch("bot.send_photo_telegram")
    @patch("bot.requests.get")
    @patch("bot.get_table_rows")
    def test_outage_of_either_fuel_restores_full_history_report_from_one_feed(self, fetch, get, send):
        for failure in ([RuntimeError("petrol timeout")],
                        [self.history_rows([1, 2]), RuntimeError("diesel timeout")]):
            with self.subTest(failure=failure), patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
                fetch.side_effect = failure
                get.return_value = self.response(json.dumps(self.mirrored_payload()))
                bot.main(dry_run=True)
                caption = (bot.DIAGNOSTICS_DIR / "caption.txt").read_text(encoding="utf-8")
                self.assertIn("Preturi Carburanti", caption)
                self.assertIn("32.45 lei/litru", caption)
                self.assertIn("35.88 lei/litru", caption)
                self.assertIn("-0.27 lei fata de", caption)
                self.assertIn("-0.02 lei fata de", caption)
                self.assertIn("logos-pres.md", caption)
                self.assertNotIn("Preturi in vigoare", caption)
                self.assertTrue((bot.DIAGNOSTICS_DIR / "chart.png").read_bytes().startswith(b"\x89PNG"))
        send.assert_not_called()

    @patch("bot.time.sleep")
    @patch("bot.requests.get")
    def test_mirror_retries_transient_network_errors(self, get, sleep):
        get.side_effect = [requests.ConnectTimeout("timeout"), self.response(json.dumps(self.mirrored_payload()))]
        rows = bot.fetch_mirrored_history()
        self.assertEqual(bot.get_latest(rows[0])["pret"], 32.45)
        self.assertEqual(get.call_args.args[0], bot.HISTORY_MIRROR_URL)
        sleep.assert_called_once_with(bot.FETCH_RETRY_DELAY)

    def test_mirror_rejects_stale_future_invalid_and_inconsistent_history(self):
        def set_nested(payload, keys, value):
            target = payload
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
        today = datetime.now(bot.TIMEZONE).date()
        invalid = [
            (("source", "name"), "Other"),
            (("source", "url"), "https://other.example/"),
            (("source", "published_date"), (today - timedelta(days=8)).isoformat()),
            (("source", "published_date"), (today + timedelta(days=1)).isoformat()),
            (("products", "gasoline_95", "current"), 99),
            (("products", "diesel", "change"), 99),
            (("products", "gasoline_95", "history", 0, "price"), float("nan")),
            (("products", "diesel", "history", 0, "price"), True),
            (("products", "diesel", "history", 0, "price"), -1),
            (("products", "diesel", "history", 0, "date"), (today + timedelta(days=1)).isoformat()),
            (("products", "diesel", "history", 1, "date"), today.isoformat()),
            (("products", "gasoline_95", "history"), []),
            (("products", "diesel", "history", 5, "date"), (today - timedelta(days=10)).isoformat()),
        ]
        for keys, value in invalid:
            with self.subTest(keys=keys, value=value):
                payload = self.mirrored_payload()
                set_nested(payload, keys, value)
                with self.assertRaises(ValueError):
                    bot.parse_mirrored_history(payload)

    @patch("bot.send_photo_telegram")
    @patch("bot.wait_until_send_time")
    @patch("bot.get_table_rows")
    def test_delivery_waits_after_preparation_and_sends_once(self, fetch, wait, send):
        fetch.side_effect = [self.history_rows([32.45, 32.72]), self.history_rows([35.88, 35.90])]
        events = []
        wait.side_effect = lambda **kw: events.append(("wait", kw))
        send.side_effect = lambda *args: events.append(("send", {}))
        with patch.object(bot, "BOT_TOKEN", "fake-token"), patch.object(bot, "CHAT_ID", "123"), \
                patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            bot.main()
        self.assertEqual(events, [("wait", {"lead_seconds": 300}), ("wait", {}), ("send", {})])
        send.assert_called_once()
        self.assertEqual(bot.STAGE, "Telegram delivery confirmed")

    @patch("bot.send_photo_telegram", side_effect=requests.ReadTimeout("ambiguous Telegram timeout"))
    @patch("bot.wait_until_send_time")
    @patch("bot.get_table_rows")
    def test_telegram_timeout_does_not_claim_success_or_retry(self, fetch, wait, send):
        fetch.side_effect = [self.history_rows([32.45, 32.72]), self.history_rows([35.88, 35.90])]
        with patch.object(bot, "BOT_TOKEN", "fake-token"), patch.object(bot, "CHAT_ID", "123"):
            with self.assertRaises(requests.ReadTimeout):
                bot.main()
        send.assert_called_once()
        self.assertFalse((bot.DIAGNOSTICS_DIR / "summary.txt").exists())

    @patch("bot.time.sleep")
    def test_1250_local_time_handles_winter_summer_and_late_starts(self, sleep):
        with patch.object(bot, "SEND_AT", "12:50"), patch("bot.datetime", wraps=datetime) as clock:
            for month in (1, 7):
                with self.subTest(month=month):
                    clock.now.return_value = datetime(2026, month, 15, 12, 40, tzinfo=bot.TIMEZONE)
                    bot.wait_until_send_time(lead_seconds=300)
                    sleep.assert_called_with(300)
                    clock.now.return_value = datetime(2026, month, 15, 12, 49, tzinfo=bot.TIMEZONE)
                    bot.wait_until_send_time()
                    sleep.assert_called_with(60)
                    sleep.reset_mock()
                    clock.now.return_value = datetime(2026, month, 15, 13, 0, tzinfo=bot.TIMEZONE)
                    bot.wait_until_send_time()
                    sleep.assert_not_called()

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
