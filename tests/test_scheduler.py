from datetime import datetime
import unittest
from unittest.mock import Mock, patch

from fuelbot.config import Settings
from fuelbot import scheduler


class SchedulerTests(unittest.TestCase):
    @patch("fuelbot.scheduler.time.sleep")
    def test_local_time_handles_winter_summer_and_late_starts(self, sleep):
        settings = Settings(send_at="12:50")
        for month in (1, 7):
            with self.subTest(month=month):
                now = datetime(2026, month, 15, 12, 40, tzinfo=settings.timezone)
                scheduler.wait_until_send_time(settings, lead_seconds=300, now=now)
                sleep.assert_called_with(300)
                now = now.replace(minute=49)
                scheduler.wait_until_send_time(settings, now=now)
                sleep.assert_called_with(60)
                sleep.reset_mock()
                scheduler.wait_until_send_time(settings, now=now.replace(hour=13))
                sleep.assert_not_called()

    @patch("fuelbot.scheduler.wait_until_send_time")
    def test_dry_run_never_waits(self, wait):
        prepare, deliver = Mock(return_value="report"), Mock(return_value="result")
        self.assertEqual(scheduler.run(prepare, deliver, Settings(send_at="12:50"), dry_run=True), "result")
        wait.assert_not_called()
        deliver.assert_called_once_with("report")

    @patch("fuelbot.scheduler.time.sleep")
    def test_immediate_configuration_does_not_wait(self, sleep):
        scheduler.wait_until_send_time(Settings())
        sleep.assert_not_called()
