from datetime import datetime
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image

from fuelbot.config import HISTORY_MIRROR_URL
from fuelbot.reports import build_report, format_block
from tests.helpers import NOW, history


class ReportTests(unittest.TestCase):
    @patch("requests.get", side_effect=AssertionError("Rendering must not fetch data"))
    @patch("requests.post", side_effect=AssertionError("Rendering must not send messages"))
    def test_original_friday_caption_and_chart_are_preserved(self, post, get):
        friday = datetime(2026, 10, 23, 12, 50, tzinfo=NOW.tzinfo)
        report = build_report(history(friday), friday)
        expected = (Path(__file__).parent / "fixtures/friday_caption.txt").read_text(encoding="utf-8").rstrip("\n")
        self.assertEqual(report.caption, expected)
        self.assertEqual(report.published_date, friday.date())
        with Image.open(io.BytesIO(report.chart)) as chart:
            self.assertEqual(chart.size, (1300, 650))
            self.assertEqual(chart.format, "PNG")

    def test_mirror_is_identified_without_changing_the_original_report(self):
        report = build_report(history(source=HISTORY_MIRROR_URL), NOW)
        self.assertIn("Date ANRE preluate prin logos-pres.md", report.caption)
        self.assertIn("Sursa: anre.md/benzina-95-3-2", report.caption)
        self.assertNotIn("Preturi in vigoare", report.caption)

    def test_increase_decrease_and_unchanged_caption_formats(self):
        for difference, expected in ((0.12, "🔺 +0.12"), (-0.12, "🔻 -0.12"), (0, "➡️ Neschimbat")):
            info = {"diferenta": difference, "data_comparatie": "4 noiembrie 2026", "pret": 30.80}
            with self.subTest(difference=difference):
                self.assertIn(expected, format_block("Benzina 95", info))
