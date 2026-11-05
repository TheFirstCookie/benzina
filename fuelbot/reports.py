"""Pure chart and caption generation from validated publication records."""
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator
from .config import HISTORY_MIRROR_URL
from .models import Report
from .parsing import LUNI

def get_history(points, limit=15):
    selected = list(reversed(points[:limit]))
    return [point.date for point in selected], [point.price for point in selected]


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


def build_report(history, today):
    b_dates, b_prices = get_history(history.petrol)
    m_dates, m_prices = get_history(history.diesel)
    benzina = get_latest(history.petrol)
    motorina = get_latest(history.diesel)
    chart = make_chart(b_dates, b_prices, m_dates, m_prices)
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
    if history.source == HISTORY_MIRROR_URL:
        caption += "\n_Date ANRE preluate prin logos-pres.md_"

    detail = (f"Source: {history.source}\n"
              f"Benzina 95: {benzina['data']} / {benzina['pret']:.2f} lei\n"
              f"Motorina: {motorina['data']} / {motorina['pret']:.2f} lei")
    return Report(chart.getvalue(), caption, detail, history.petrol[0].date.date())
