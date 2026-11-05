from datetime import datetime, timedelta

import requests

from fuelbot.config import Settings
from fuelbot.models import FuelHistory, PricePoint
from fuelbot.validation import encode_history


NOW = datetime(2026, 11, 5, 12, 50, tzinfo=Settings().timezone)
PETROL = [32.45, 32.72, 32.99, 33.21, 33.41, 33.53]
DIESEL = [35.88, 35.90, 35.82, 35.57, 35.42, 35.22]


def points(prices, published=None):
    day = published or NOW.date()
    result = []
    for price in prices:
        result.append(PricePoint(datetime.combine(day, datetime.min.time()), price))
        day -= timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
    return tuple(result)


def history(now=NOW, source="ANRE direct"):
    return FuelHistory(points(PETROL, now.date()), points(DIESEL, now.date()), source)


def payload(now=NOW):
    return encode_history(history(now), now)


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result.url = "https://anre.md/benzina-95-3-2"
    result.encoding = "utf-8"
    result._content = body.encode("utf-8")
    result.headers["Content-Type"] = "text/html"
    return result
