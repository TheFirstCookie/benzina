"""Source-independent publication records; HTML stops at the source boundary."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PricePoint:
    date: datetime
    price: float


@dataclass(frozen=True)
class FuelHistory:
    petrol: tuple[PricePoint, ...]
    diesel: tuple[PricePoint, ...]
    source: str = "ANRE direct"


@dataclass(frozen=True)
class Report:
    chart: bytes
    caption: str
    detail: str
