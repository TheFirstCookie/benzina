import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from fuelbot import sources
from fuelbot.config import FETCH_RETRY_DELAY, HISTORY_MIRROR_URL, URLS
from tests.helpers import NOW, history, payload, response


class SourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    @patch("fuelbot.sources.requests.get")
    def test_parser_ignores_layout_headers_and_bad_prices_then_sorts_dates(self, get):
        get.return_value = response('''
            <table><tr><td>Menu</td><td>Help</td></tr></table>
            <table><tr><td>Date</td><td>PC</td></tr>
            <tr><td>23 octombrie 2026</td><td>32,45</td></tr>
            <tr><td>26 octombrie 2026</td><td>32,22</td></tr>
            <tr><td>22 octombrie 2026</td><td>unavailable</td></tr></table>
        ''')
        points = sources.fetch_anre_page(URLS["Benzina 95"], self.directory)
        self.assertEqual([point.price for point in points], [32.22, 32.45])
        self.assertGreater(points[0].date, points[1].date)
        self.assertEqual(len(list(self.directory.glob("*.html"))), 1)
        self.assertEqual(len(list(self.directory.glob("*.json"))), 1)

    @patch("fuelbot.sources.time.sleep")
    @patch("fuelbot.sources.fetch_anre_page")
    def test_network_timeout_retries_alternate_official_hostname(self, fetch, sleep):
        fetch.side_effect = [requests.ConnectTimeout("timeout"), history().petrol]
        self.assertEqual(sources.fetch_anre(URLS["Benzina 95"], self.directory), history().petrol)
        self.assertEqual(fetch.call_args.args[0], "https://www.anre.md/benzina-95-3-2")
        sleep.assert_called_once_with(FETCH_RETRY_DELAY)

    @patch("fuelbot.sources.log_dns")
    @patch("fuelbot.sources.time.sleep")
    @patch("fuelbot.sources.fetch_anre_page", side_effect=requests.ReadTimeout("timeout"))
    def test_exhausted_retries_report_failure_and_dns(self, fetch, sleep, dns):
        with self.assertRaisesRegex(sources.SourceUnavailable, "after 2 attempts: ReadTimeout"):
            sources.fetch_anre(URLS["Benzina 95"], self.directory)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(dns.call_count, 2)

    @patch("fuelbot.sources.requests.get")
    def test_maintenance_page_preserves_diagnostics_and_fails(self, get):
        get.return_value = response("<title>Maintenance</title><p>Try later</p>")
        with self.assertRaisesRegex(sources.SourceUnavailable, "Maintenance"):
            sources.fetch_anre_page(URLS["Benzina 95"], self.directory)
        self.assertEqual(len(list(self.directory.glob("*.html"))), 1)

    @patch("fuelbot.sources.time.sleep")
    @patch("fuelbot.sources.requests.get")
    def test_mirror_retries_transient_failure_and_normalizes_records(self, get, sleep):
        get.side_effect = [requests.ConnectTimeout("timeout"), response(json.dumps(payload()))]
        result = sources.fetch_mirror(NOW, self.directory)
        self.assertEqual(result.petrol, history().petrol)
        self.assertEqual(result.diesel, history().diesel)
        self.assertEqual(result.source, HISTORY_MIRROR_URL)
        sleep.assert_called_once_with(FETCH_RETRY_DELAY)

    @patch("fuelbot.sources.time.sleep")
    @patch("fuelbot.sources.requests.get")
    def test_stale_mirror_cannot_masquerade_as_success(self, get, sleep):
        data = payload()
        data["source"]["published_date"] = "2026-11-03"
        get.return_value = response(json.dumps(data))
        with self.assertRaises(sources.SourceUnavailable):
            sources.fetch_mirror(NOW, self.directory)
        self.assertEqual(get.call_count, 3)
