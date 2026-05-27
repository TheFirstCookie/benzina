import requests
from bs4 import BeautifulSoup
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")

URLS = {
    "Benzina 95": "https://anre.md/benzina-95-3-2",
    "Motorina":   "https://anre.md/motorina-3-3",
}

def get_price(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, verify=False)
    soup = BeautifulSoup(r.text, "html.parser")

    table = soup.find("table")
    rows = [row for row in table.find_all("tr") if row.find("td")]

    azi  = rows[0].find_all("td")
    ieri = rows[1].find_all("td")

    pret_azi  = float(azi[-1].text.strip().replace(",", "."))
    pret_ieri = float(ieri[-1].text.strip().replace(",", "."))
    diferenta = round(pret_azi - pret_ieri, 2)

    return {
        "data":      azi[0].text.strip(),
        "pret":      pret_azi,
        "diferenta": diferenta,
    }

def format_block(nume, info):
    diff = info["diferenta"]
    if diff > 0:
        trend = f"🔺 +{diff:.2f} lei fata de ieri"
    elif diff < 0:
        trend = f"🔻 {diff:.2f} lei fata de ieri"
    else:
        trend = "➡️ Neschimbat fata de ieri"

    return (
        f"*{nume}*\n"
        f"💰 Pret: `{info['pret']:.2f} lei/litru`\n"
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
    import urllib3
    urllib3.disable_warnings()

    benzina  = get_price(URLS["Benzina 95"])
    motorina = get_price(URLS["Motorina"])

    mesaj = (
        f"⛽ *Preturi Carburanti — ANRE Moldova*\n"
        f"📅 {benzina['data']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{format_block('Benzina 95', benzina)}\n\n"
        f"{format_block('Motorina', motorina)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"_Sursa: anre.md_"
    )

    print(mesaj)
    send_to_telegram(mesaj)
    print("Mesaj trimis!")
