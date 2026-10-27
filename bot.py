import argparse
import json
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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")
TIMEZONE  = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Chisinau"))
# Ora locala (HH:MM) la care se trimite mesajul; gol = trimite imediat
SEND_AT   = os.environ.get("SEND_AT", "").strip()
REQUEST_TIMEOUT = 30
CONNECT_TIMEOUT = 10
FETCH_ATTEMPTS = 4
FETCH_RETRY_DELAY = 5
DIAGNOSTICS_DIR = Path(os.environ.get("DIAGNOSTICS_DIR", "diagnostics"))
STAGE = "startup"


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


def log_dns(url):
    host = urlsplit(url).hostname
    try:
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(
            host, 443, type=socket.SOCK_STREAM)})
        logging.info("DNS %s: %s", host, addresses)
    except OSError as error:
        logging.error("DNS %s failed: %s", host, error)

URLS = {
    "Benzina 95": "https://anre.md/benzina-95-3-2",
    "Motorina":   "https://anre.md/motorina-3-3",
}

LUNI = {
    "ianuarie": "01",
    "februarie": "02",
    "martie": "03",
    "aprilie": "04",
    "mai": "05",
    "iunie": "06",
    "iulie": "07",
    "august": "08",
    "septembrie": "09",
    "octombrie": "10",
    "noiembrie": "11",
    "decembrie": "12"
}


def parse_date(s):
    s = s.strip().lower()

    for luna_ro, luna_nr in LUNI.items():
        if luna_ro in s:
            s = s.replace(luna_ro, luna_nr)
            break

    try:
        return datetime.strptime(s, "%d %m %Y")
    except ValueError:
        return None


def parse_price(s):
    clean = s.strip().replace("\xa0", "").replace(" ", "")

    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")

    return float(clean)


def get_table_rows(url):
    # anre.md uneori raspunde cu o pagina fara tabel sau nu raspunde deloc
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        parts = urlsplit(url)
        host = "www.anre.md" if attempt % 2 == 0 else parts.netloc
        # ANRE also serves the original tables on port 80. Some runner networks
        # cannot reach its HTTPS port; keep the same data and report in that case.
        scheme = parts.scheme if attempt <= 2 else "http"
        candidate = urlunsplit(parts._replace(netloc=host, scheme=scheme))
        started = time.monotonic()
        logging.info("ANRE attempt %d/%d: %s", attempt, FETCH_ATTEMPTS, candidate)
        try:
            return fetch_table_rows(candidate)
        except (requests.RequestException, RuntimeError) as e:
            logging.warning("ANRE %s after %.1fs: %s", type(e).__name__,
                            time.monotonic() - started, e)
            if attempt == FETCH_ATTEMPTS:
                log_dns(url)
                log_dns(candidate)
                raise RuntimeError(
                    f"ANRE fetch failed after {FETCH_ATTEMPTS} attempts: "
                    f"{type(e).__name__}: {e}"
                ) from e
            logging.warning(
                "Incercarea %d/%d a esuat pentru %s: %s",
                attempt, FETCH_ATTEMPTS, candidate, e
            )
            time.sleep(FETCH_RETRY_DELAY)


def fetch_table_rows(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ANREPriceBot/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ro,en;q=0.8",
    }

    started = time.monotonic()
    r = requests.get(
        url,
        headers=headers,
        timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT)
    )
    logging.info("ANRE response: status=%s url=%s elapsed=%.2fs bytes=%d type=%s",
                 r.status_code, r.url, time.monotonic() - started,
                 len(r.content), r.headers.get("Content-Type", "unknown"))
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{urlsplit(url).netloc}-{urlsplit(url).path.strip('/')}"
    (DIAGNOSTICS_DIR / f"{filename}.html").write_text(r.text, encoding="utf-8")
    (DIAGNOSTICS_DIR / f"{filename}.json").write_text(json.dumps({
        "url": r.url, "status": r.status_code,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "bytes": len(r.content), "content_type": r.headers.get("Content-Type"),
        "server": r.headers.get("Server"),
        "retry_after": r.headers.get("Retry-After"),
    }, indent=2), encoding="utf-8")
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    logging.debug("ANRE page title=%r table_count=%d",
                  soup.title.get_text(strip=True) if soup.title else None,
                  len(soup.find_all("table")))
    # Ignore layout tables and header rows that use td instead of th.
    for table in soup.find_all("table"):
        rows = []
        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 2 or parse_date(cols[0].get_text(" ", strip=True)) is None:
                continue
            try:
                price = parse_price(cols[-1].get_text(strip=True))
                if not 0 < price < 1000:
                    continue
            except ValueError:
                logging.debug("Skipping invalid ANRE price on date %r",
                              cols[0].get_text(strip=True))
                continue
            rows.append(row)
        if len(rows) >= 2:
            rows.sort(key=lambda row: parse_date(row.find("td").get_text(" ", strip=True)),
                      reverse=True)
            logging.info("ANRE parsed %d prices; latest date=%s price=%s", len(rows),
                         rows[0].find("td").get_text(strip=True),
                         rows[0].find_all("td")[-1].get_text(strip=True))
            return rows
    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    raise RuntimeError(f"ANRE page has fewer than two valid price rows: {url}; "
                       f"title={title!r}; tables={len(soup.find_all('table'))}; "
                       "see diagnostics HTML")


def get_history(rows, limit=15):
    dates = []
    prices = []

    for row in rows[:limit]:
        cols = row.find_all("td")

        d = parse_date(cols[0].text)
        p = parse_price(cols[-1].text)

        if d:
            dates.append(d)
            prices.append(p)

    return list(reversed(dates)), list(reversed(prices))


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


def get_latest(rows):
    azi =rows[0].find_all("td")
    ultima_data = rows[1].find_all("td")

    pret_azi = parse_price(azi[-1].text)
    pret_ultima_data = parse_price(ultima_data[-1].text)

    return {
        "data": azi[0].text.strip(),
        "pret": pret_azi,
        "diferenta": round(pret_azi - pret_ultima_data, 2),
        "data_comparatie": ultima_data[0].text.strip(),
    }


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

    set_stage("fetch Benzina 95")
    b_rows = get_table_rows(URLS["Benzina 95"])
    set_stage("fetch Motorina")
    m_rows = get_table_rows(URLS["Motorina"])

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

    complete_report(chart, caption,
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
