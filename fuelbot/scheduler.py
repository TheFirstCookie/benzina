"""Scheduling is independent of fetching, rendering and Telegram transport."""
from datetime import datetime, timedelta
import logging
import time


def wait_until_send_time(settings, lead_seconds=0, now=None):
    if not settings.send_at:
        return
    hour, minute = map(int, settings.send_at.split(":"))
    now = now or datetime.now(settings.timezone)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(seconds=lead_seconds)
    seconds = (target - now).total_seconds()
    if seconds > 0:
        logging.info("Scheduler waiting until %s (%d seconds)", target, seconds)
        time.sleep(seconds)
    else:
        logging.info("Scheduled time has passed; continuing immediately")


def run(prepare, deliver, settings, dry_run=False):
    if not dry_run:
        wait_until_send_time(settings, lead_seconds=300)
    report = prepare()
    if not dry_run:
        wait_until_send_time(settings)
    return deliver(report)
