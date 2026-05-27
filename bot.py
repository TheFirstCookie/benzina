import requests
from bs4 import BeautifulSoup
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "TOKEN_TĂU_AICI")
CHAT_ID   = os.environ.get("CHAT_ID",   "CHAT_ID_TĂU_AICI")

URLS = {
    "Benzină 95": "https://anre.md/benzina-95-3-2",
    "Motorină":   "https://anre.md/motorina-3-3",
}

def get_price(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    table = soup.find("table")
    rows = table.find_all("tr")

    # rows[1] = azi, rows[2] = ieri
    azi   = rows[1].find_all("td")
    ieri  = rows[2].find_all("td")

    pret_azi  = float(azi[8].text.strip().replace(",", "."))
    pret_ieri = float(ieri[8].text.strip().replace(",", "."))
    diferenta = round(pret_azi - pret_ieri, 2)

    return {
        "data":      azi[0].text.strip(),
        "pret":      pret_azi,
        "diferenta": diferenta,
    }

def format_block(nume, info):
    diff = info["diferenta"]
    if diff > 0:
        trend = f"🔺 +{diff:.2f} lei față de ieri"
    elif diff < 0:
        trend = f"🔻 {diff:.2f} lei față de ieri"
    else:
        trend = "➡️ Neschimbat față de ieri"

    return (
        f"*{nume}*\n"
        f"💰 Preț: `{info['pret']:.2f} lei/litru`\n"
        f"{trend}"
    )

def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id":    CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown"
    })

if __name__ == "__main__":
    benzina = get_price(URLS["Benzină 95"])
    motorina = get_price(URLS["Motorină"])

    mesaj = (
        f"⛽ *Prețuri Carburanți — ANRE Moldova*\n"
        f"📅 {benzina['data']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{format_block('Benzină 95', benzina)}\n\n"
        f"{format_block('Motorină', motorina)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"_Sursa: anre.md_"
    )

    send_to_telegram(mesaj)
    print("Mesaj trimis cu succes!")
    print(mesaj)
