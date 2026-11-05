"""ANRE Romanian date and numeric parsing."""
from datetime import datetime

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
