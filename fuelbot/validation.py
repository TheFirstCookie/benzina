"""The same integrity rules apply to ANRE, mirrors and supplied relay data."""
from datetime import datetime, timedelta
import math

from .models import FuelHistory, PricePoint


class InvalidHistory(ValueError):
    pass


def expected_publication_date(now):
    day = now.date()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def valid_number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def validate_history(history, now, minimum=2):
    expected = expected_publication_date(now)
    for name, points in (("petrol", history.petrol), ("diesel", history.diesel)):
        if len(points) < minimum:
            raise InvalidHistory(f"Incomplete {name} history: need at least {minimum} publications")
        for point in points:
            if not isinstance(point.date, datetime) or point.date.tzinfo is not None:
                raise InvalidHistory("Publication dates must be dates without time zones")
            if point.date.time() != datetime.min.time():
                raise InvalidHistory("Publication dates cannot contain a time")
            if not valid_number(point.price) or not 0 < point.price < 1000:
                raise InvalidHistory(f"Invalid ANRE price for {name}")
        dates = [point.date for point in points]
        if dates[0].date() != expected:
            raise InvalidHistory(f"ANRE publication date {dates[0].date()} is stale or future; expected {expected}")
        if any(left <= right for left, right in zip(dates, dates[1:])):
            raise InvalidHistory("Publication dates must be unique and ordered newest first")
    if [point.date for point in history.petrol] != [point.date for point in history.diesel]:
        raise InvalidHistory("Fuel histories have different publication dates")
    return history


def iso_date(value):
    if not isinstance(value, str):
        raise InvalidHistory("Publication date must use YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise InvalidHistory("Publication date must use YYYY-MM-DD") from None
    if parsed.strftime("%Y-%m-%d") != value:
        raise InvalidHistory("Publication date must use YYYY-MM-DD")
    return parsed


def decode_history(payload, now, source="ANRE relay"):
    try:
        origin = payload["source"]
        if origin["name"] != "ANRE" or origin["url"] not in ("https://anre.md", "https://anre.md/"):
            raise InvalidHistory("History feed does not identify the official ANRE source")
        published = iso_date(origin["published_date"])
        histories = []
        for key in ("gasoline_95", "diesel"):
            product = payload["products"][key]
            points = tuple(sorted((PricePoint(iso_date(item["date"]), item["price"])
                                   for item in product["history"]), key=lambda point: point.date, reverse=True))
            # Validate every point before taking the ten points used by the chart.
            validate_history(FuelHistory(points, points), now, minimum=6)
            if points[0].date != published:
                raise InvalidHistory("Advertised publication date disagrees with history")
            if (not valid_number(product["current"]) or not valid_number(product["change"])
                    or points[0].price != product["current"]
                    or round(points[0].price - points[1].price, 2) != product["change"]):
                raise InvalidHistory("Advertised current price or daily change disagrees with history")
            histories.append(points)
        full = validate_history(FuelHistory(*histories, source=source), now, minimum=6)
        return FuelHistory(full.petrol[:10], full.diesel[:10], source)
    except (KeyError, TypeError, AttributeError) as error:
        raise InvalidHistory("Malformed ANRE publication history") from error


def encode_history(history, now):
    validate_history(history, now, minimum=6)
    products = {}
    for key, points in (("gasoline_95", history.petrol), ("diesel", history.diesel)):
        products[key] = {"current": points[0].price,
                         "change": round(points[0].price - points[1].price, 2),
                         "history": [{"date": point.date.strftime("%Y-%m-%d"), "price": point.price}
                                     for point in points[:10]]}
    return {"source": {"name": "ANRE", "url": "https://anre.md/",
                       "published_date": history.petrol[0].date.strftime("%Y-%m-%d")},
            "products": products}
