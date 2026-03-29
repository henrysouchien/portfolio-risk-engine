"""Canonical security identity primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


InstrumentCategory = Literal[
    "equity",
    "etf",
    "futures",
    "option",
    "cash",
    "bond",
    "fx",
    "crypto",
    "warrant",
    "derivative",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class SecurityIdentity:
    """Canonicalized identity for a portfolio security."""

    security_key: str
    source_symbol: str
    portfolio_symbol: str
    data_symbol: str
    instrument_category: InstrumentCategory
    exchange_mic: str | None
    currency: str | None
    cusip: str | None
    isin: str | None
    figi: str | None
    resolution_method: str

    def __str__(self) -> str:
        return self.security_key

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
