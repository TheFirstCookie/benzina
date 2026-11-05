import argparse
import json
import math
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import io
import time
import logging

from fuelbot.config import (
    Settings, URLS, HISTORY_MIRROR_URL, REQUEST_TIMEOUT, CONNECT_TIMEOUT,
    FETCH_ATTEMPTS, FETCH_RETRY_DELAY, MIRROR_ATTEMPTS,
)

_settings = Settings.from_env()
BOT_TOKEN = _settings.bot_token
CHAT_ID = _settings.chat_id
TIMEZONE = _settings.timezone
SEND_AT = _settings.send_at
DIAGNOSTICS_DIR = _settings.diagnostics_dir
STAGE = "startup"


from fuelbot import sources
from fuelbot.models import PricePoint, FuelHistory
from fuelbot.parsing import LUNI, parse_date, parse_price


def log_dns(url):
    return sources.log_dns(url)


def fetch_table_rows(url):
    return sources.fetch_table_rows(url, DIAGNOSTICS_DIR)


def get_table_rows(url):
    return sources.get_table_rows(url, DIAGNOSTICS_DIR, fetch=fetch_table_rows)


def fetch_mirrored_history():
    return sources.fetch_mirrored_history(parse_mirrored_history, DIAGNOSTICS_DIR)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        # requests exceptions include the Telegram URL, which contains the token.
        message = super().format(record)
        for secret in (BOT_TOKEN, CHAT_ID):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        return message


def setup_logging(debug=False):
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    formatter = SafeFormatter("%(asctime)s %(levelname)s %(message)s")
    handlers = [logging.StreamHandler(), logging.FileHandler(
        DIAGNOSTICS_DIR / "bot.log", encoding="utf-8")]
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        handlers=handlers, force=True)
    # Avoid verbose library HTTP logs, especially Telegram URLs with credentials.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def set_stage(stage):
    global STAGE
    STAGE = stage
    logging.info("Stage: %s", stage)


def write_summary(status, detail):
    text = f"Bot: {status}\nStage: {STAGE}\n{detail}\n"
    for secret in (BOT_TOKEN, CHAT_ID):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    (DIAGNOSTICS_DIR / "summary.txt").write_text(text, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write("\n```text\n" + text + "```\n")













def get_history(points, limit=15):
    selected = list(reversed(points[:limit]))
    return [point.date for point in selected], [point.price for point in selected]












from fuelbot import validation


def expected_publication_date():
    return validation.expected_publication_date(datetime.now(TIMEZONE))


def parse_mirrored_history(payload):
    history = validation.decode_history(payload, datetime.now(TIMEZONE))
    return history.petrol, history.diesel


def validate_histories(histories):
    return validation.validate_history(FuelHistory(tuple(histories[0]), tuple(histories[1])), datetime.now(TIMEZONE))


def history_payload(histories):
    history = FuelHistory(tuple(histories[0]), tuple(histories[1]))
    return validation.encode_history(history, datetime.now(TIMEZONE))


def complete_report(chart, caption, detail, dry_run):
    (DIAGNOSTICS_DIR / "chart.png").write_bytes(chart.getvalue())
    (DIAGNOSTICS_DIR / "caption.txt").write_text(caption, encoding="utf-8")
    if dry_run:
        set_stage("dry run complete")
    else:
        set_stage("wait for send time")
        wait_until_send_time()
        set_stage("send Telegram photo")
        send_photo_telegram(chart, caption)
        set_stage("Telegram delivery confirmed")
    write_summary("success", f"{detail}\nDry run: {dry_run}")


def get_latest(points):
    current, previous = points[:2]
    return {
        "data": format_date(current.date),
        "pret": current.price,
        "diferenta": round(current.price - previous.price, 2),
        "data_comparatie": format_date(previous.date),
    }


def format_date(date):
    return f"{date.day} {list(LUNI)[date.month - 1]} {date.year}"


def get_weekly_change(dates, prices):
    if len(prices) >= 6:
        return round(prices[-1] - prices[-6], 2)

    elif len(prices) >= 2:
        return round(prices[-1] - prices[0], 2)

    return 0.0


def make_chart(b_dates, b_prices, m_dates, m_prices):

    fig, ax = plt.subplots(figsize=(10, 5))

    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    # Benzina
    ax.plot(
        b_dates,
        b_prices,
        color="#4fc3f7",
        linewidth=2.5,
        marker="o",
        markersize=4,
        label="Benzina 95"
    )

    ax.fill_between(
        b_dates,
        b_prices,
        alpha=0.15,
        color="#4fc3f7"
    )

    # Motorina
    ax.plot(
        m_dates,
        m_prices,
        color="#81c784",
        linewidth=2.5,
        marker="o",
        markersize=4,
        label="Motorina"
    )

    ax.fill_between(
        m_dates,
        m_prices,
        alpha=0.15,
        color="#81c784"
    )

    ax.set_title(
        "Graficul Pretului Carburantilor — ANRE Moldova",
        color="white",
        fontsize=13,
        pad=12
    )

    ax.set_ylabel(
        "Pret (lei/litru)",
        color="#aaaaaa"
    )

    # Y axis dinamic
    all_prices = b_prices + m_prices

    current_min = min(all_prices)
    current_max = max(all_prices)

    y_min = current_min - 0.5
    y_max = current_max + 0.5

    ax.set_ylim(y_min, y_max)

    # Incrementare cu 0.5
    ax.yaxis.set_major_locator(MultipleLocator(0.25))

    ax.tick_params(colors="#aaaaaa")

    ax.xaxis.set_major_formatter(
        mdates.DateFormatter("%d %b")
    )

    ax.xaxis.set_major_locator(
        mdates.DayLocator(interval=2)
    )

    plt.xticks(rotation=35)

    for spine in ax.spines.values():
        spine.set_edgecolor("#333355")

    ax.legend(
        facecolor="#1a1a2e",
        labelcolor="white",
        framealpha=0.8
    )

    ax.grid(
        axis="y",
        color="#333355",
        linestyle="--",
        alpha=0.5
    )

    buf = io.BytesIO()

    plt.tight_layout()

    plt.savefig(
        buf,
        format="png",
        dpi=130,
        facecolor=fig.get_facecolor()
    )

    buf.seek(0)

    plt.close()

    return buf


def format_block(nume, info):

    diff = info["diferenta"]
    data_comparatie = info["data_comparatie"]

    if diff > 0:
        trend = f"🔺 +{diff:.2f} lei fata de {data_comparatie}"

    elif diff < 0:
        trend = f"🔻 {diff:.2f} lei fata de {data_comparatie}"

    else:
        trend = f"➡️ Neschimbat fata de {data_comparatie}"

    return (
        f"*{nume}*\n"
        f"💰 Pret: `{info['pret']:.2f} lei/litru`\n"
        f"{trend}"
    )


def format_weekly(b_diff, m_diff):

    def arrow(d):
        if d > 0:
            return f"🔺 +{d:.2f} lei"

        elif d < 0:
            return f"🔻 {d:.2f} lei"

        else:
            return "➡️ neschimbat"

    return (
        f"\n📊 *Rezumat saptamana:*\n"
        f"Benzina 95: {arrow(b_diff)}\n"
        f"Motorina:   {arrow(m_diff)}"
    )


def send_photo_telegram(image_buf, caption):
    if not BOT_TOKEN:
        raise RuntimeError("Lipseste secretul BOT_TOKEN")

    if not CHAT_ID:
        raise RuntimeError("Lipseste secretul CHAT_ID")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    logging.info("Sending Telegram photo: bytes=%d caption_characters=%d",
                 image_buf.getbuffer().nbytes, len(caption))
    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "caption": caption,
            "parse_mode": "Markdown"
        },
        files={
            "photo": ("chart.png", image_buf, "image/png")
        },
        timeout=REQUEST_TIMEOUT
    )

    try:
        payload = response.json()
    except ValueError:
        payload = {"description": response.text[:500]}

    if not response.ok or not payload.get("ok", False):
        description = payload.get("description", payload)
        raise RuntimeError(
            f"Telegram sendPhoto a esuat ({response.status_code}): {description}"
        )

    message = payload.get("result", {})
    logging.info(
        "Telegram a acceptat mesajul: message_id=%s",
        message.get("message_id")
    )


def wait_until_send_time(lead_seconds=0):
    # GitHub porneste cron-ul cu ore de intarziere, asa ca workflow-ul porneste
    # devreme si botul asteapta aici pana la ora exacta (ora Moldovei, cu DST)
    if not SEND_AT:
        return

    hour, minute = map(int, SEND_AT.split(":"))
    now = datetime.now(TIMEZONE)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(seconds=lead_seconds)
    seconds = (target - now).total_seconds()

    if seconds <= 0:
        logging.info("Ora %s a trecut deja, trimit imediat", SEND_AT)
        return

    logging.info("Astept pana la %s (%d minute)", target, seconds // 60)
    time.sleep(seconds)


def main(dry_run=False):
    set_stage("configuration")
    if not dry_run:
        missing = [name for name, value in (("BOT_TOKEN", BOT_TOKEN), ("CHAT_ID", CHAT_ID))
                   if not value.strip()]
        if missing:
            raise RuntimeError("Missing GitHub Actions secrets: " + ", ".join(missing))
    logging.info("Python=%s timezone=%s send_at=%s dry_run=%s event=%s run_id=%s",
                 sys.version.split()[0], TIMEZONE, SEND_AT or "immediate", dry_run,
                 os.environ.get("GITHUB_EVENT_NAME", "local"),
                 os.environ.get("GITHUB_RUN_ID", "local"))
    if not dry_run:
        set_stage("wait for price preparation time")
        wait_until_send_time(lead_seconds=300)

    today = datetime.now(TIMEZONE)
    logging.info("Rulez botul pentru data locala: %s", today.date())

    mirrored = False
    supplied_history = os.environ.get("ANRE_HISTORY_JSON", "").strip()
    if supplied_history:
        set_stage("validate supplied ANRE publication history")
        b_rows, m_rows = parse_mirrored_history(json.loads(supplied_history))
    else:
        try:
            set_stage("fetch Benzina 95")
            b_rows = get_table_rows(URLS["Benzina 95"])
            set_stage("fetch Motorina")
            m_rows = get_table_rows(URLS["Motorina"])
            validate_histories((b_rows, m_rows))
        except (requests.RequestException, RuntimeError, ValueError) as error:
            logging.warning("Direct ANRE history unavailable; trying publication-history mirror: %s", error)
            set_stage("fetch mirrored ANRE publication history")
            b_rows, m_rows = fetch_mirrored_history()
            mirrored = True

    set_stage("parse prices")
    b_dates, b_prices = get_history(b_rows)
    m_dates, m_prices = get_history(m_rows)

    benzina = get_latest(b_rows)
    motorina = get_latest(m_rows)

    set_stage("generate chart")
    chart = make_chart(
        b_dates,
        b_prices,
        m_dates,
        m_prices
    )

    caption = (
        f"⛽ *Preturi Carburanti — ANRE Moldova*\n"
        f"📅 {benzina['data']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{format_block('Benzina 95', benzina)}\n\n"
        f"{format_block('Motorina', motorina)}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    # Vineri
    if today.weekday() == 4:

        b_weekly = get_weekly_change(
            b_dates,
            b_prices
        )

        m_weekly = get_weekly_change(
            m_dates,
            m_prices
        )

        caption += format_weekly(
            b_weekly,
            m_weekly
        )

    caption += "\n_Sursa: anre.md/benzina-95-3-2_"
    caption += "\n_Sursa: anre.md/motorina-3-3_"
    if mirrored:
        caption += "\n_Date ANRE preluate prin logos-pres.md_"

    complete_report(chart, caption,
                    f"Source: {HISTORY_MIRROR_URL if mirrored else 'ANRE direct'}\n"
                    f"Benzina 95: {benzina['data']} / {benzina['pret']:.2f} lei\n"
                    f"Motorina: {motorina['data']} / {motorina['pret']:.2f} lei", dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ANRE fuel prices to Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and chart without sending to Telegram")
    parser.add_argument("--debug", action="store_true", help="Enable application debug logging")
    args = parser.parse_args()
    setup_logging(args.debug)
    try:
        main(dry_run=args.dry_run)
    except Exception as error:
        logging.exception("Bot failed at stage: %s", STAGE)
        write_summary("FAILED", f"{type(error).__name__}: {error}")
        sys.exit(1)
