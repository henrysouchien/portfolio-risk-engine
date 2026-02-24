"""Minimal ticker/currency resolver helpers for standalone mode."""

from __future__ import annotations

from typing import Optional


def normalize_currency(currency: Optional[str]) -> Optional[str]:
    if not currency:
        return None
    ccy = str(currency).upper()
    aliases = {
        "GBX": "GBP",
        "GBP": "GBP",
    }
    return aliases.get(ccy, ccy)


def select_fmp_symbol(
    ticker: str,
    *,
    fmp_ticker: Optional[str] = None,
    fmp_ticker_map: Optional[dict[str, str]] = None,
) -> str:
    if fmp_ticker:
        return fmp_ticker
    if fmp_ticker_map and ticker in fmp_ticker_map:
        mapped = fmp_ticker_map.get(ticker)
        if mapped:
            return mapped
    return ticker


def normalize_fmp_price(price: Optional[float], currency: Optional[str]) -> tuple[Optional[float], str]:
    if price is None:
        return None, (currency or "USD")
    ccy = normalize_currency(currency) or "USD"
    minor = {
        "GBX": ("GBP", 100.0),
    }
    if ccy in minor:
        base_ccy, divisor = minor[ccy]
        return (float(price) / divisor), base_ccy
    return float(price), ccy


def fetch_fmp_quote_with_currency(symbol: str) -> tuple[Optional[float], Optional[str]]:
    if not symbol:
        return None, None
    try:  # pragma: no cover - best effort live fetch
        from fmp.client import FMPClient  # type: ignore

        data = FMPClient().fetch_raw("profile", symbol=symbol)
        if isinstance(data, list) and data:
            row = data[0] or {}
            return row.get("price"), row.get("currency")
    except Exception:
        pass
    return None, None
