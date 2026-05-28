import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator
from datetime import datetime
import os
import io
import urllib3

urllib3.disable_warnings()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")

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
    except:
        return None


def get_history(url, limit=15):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(url, headers=headers, verify=False)
    soup = BeautifulSoup(r.text, "html.parser")

    table = soup.find("table")
    rows = [row for row in table.find_all("tr") if row.find("td")]

    dates = []
    prices = []

    for row in rows[:limit]:
        cols = row.find_all("td")

        d = parse_date(cols[0].text)
        p = float(cols[-1].text.strip().replace(",", "."))

        if d:
            dates.append(d)
            prices.append(p)

    return list(reversed(dates)), list(reversed(prices))


def get_latest(url):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(url, headers=headers, verify=False)
    soup = BeautifulSoup(r.text, "html.parser")

    table = soup.find("table")
    rows = [row for row in table.find_all("tr") if row.find("td")]

    azi = rows[0].find_all("td")
    ultima_data = rows[1].find_all("td")

    pret_azi = float(azi[-1].text.strip().replace(",", "."))
    pret_ultima_data = float(ultima_data[-1].text.strip().replace(",", "."))

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

    y_min = current_min - 1
    y_max = current_max + 1

    ax.set_ylim(y_min, y_max)

    # Incrementare cu 0.5
    ax.yaxis.set_major_locator(MultipleLocator(0.5))

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

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "caption": caption,
            "parse_mode": "Markdown"
        },
        files={
            "photo": ("chart.png", image_buf, "image/png")
        }
    )


if __name__ == "__main__":

    b_dates, b_prices = get_history(URLS["Benzina 95"])
    m_dates, m_prices = get_history(URLS["Motorina"])

    benzina = get_latest(URLS["Benzina 95"])
    motorina = get_latest(URLS["Motorina"])

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

    today = datetime.now()

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

    send_photo_telegram(chart, caption)
