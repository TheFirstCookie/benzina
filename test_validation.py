from datetime import datetime, timedelta
import unittest

from fuelbot.models import FuelHistory, PricePoint
from fuelbot.validation import InvalidHistory, decode_history, encode_history, validate_history


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 5, 12, 50)
        self.points = tuple(PricePoint(datetime(2026, 11, 5) - timedelta(days=i), 30 + i / 10)
                            for i in range(6))

    def test_common_rules_reject_bad_prices_from_any_source(self):
        for value in (True, float("nan"), float("inf"), -1, 0, 1000, "30"):
            bad = (PricePoint(self.points[0].date, value), *self.points[1:])
            with self.subTest(value=value), self.assertRaises(InvalidHistory):
                validate_history(FuelHistory(bad, bad), self.now)

    def test_duplicate_unsorted_missing_and_mismatched_dates_are_rejected(self):
        variants = (self.points[:1], (self.points[0], *self.points), tuple(reversed(self.points)))
        for points in variants:
            with self.subTest(points=points), self.assertRaises(InvalidHistory):
                validate_history(FuelHistory(points, points), self.now)
        with self.assertRaisesRegex(InvalidHistory, "different publication"):
            validate_history(FuelHistory(self.points, self.points[:-1]), self.now)

    def test_json_round_trip_does_not_need_html(self):
        original = FuelHistory(self.points, self.points)
        restored = decode_history(encode_history(original, self.now), self.now)
        self.assertEqual(original.petrol, restored.petrol)
        self.assertEqual(original.diesel, restored.diesel)

    def test_malformed_payloads_fail_with_a_validation_error(self):
        for payload in (None, [], {}, {"source": None}, {"source": {"name": True}}):
            with self.subTest(payload=payload), self.assertRaises(InvalidHistory):
                decode_history(payload, self.now)
