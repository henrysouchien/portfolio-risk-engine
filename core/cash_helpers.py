from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

from config import resolve_config_path

_cash_map_cache: dict[str, Any] | None = None
_proxy_by_currency_cache: dict[str, str] | None = None
_proxy_tickers_cache: set[str] | None = None
_proxy_ticker_to_currency_cache: dict[str, str] | None = None
_alias_to_currency_cache: dict[str, str] | None = None


def _normalize_mapping_section(
    cash_map: Mapping[str, Any],
    section: str,
    *,
    uppercase_values: bool = False,
    uppercase_keys: bool = False,
) -> dict[str, str]:
    raw = cash_map.get(section)
    if not isinstance(raw, Mapping) or not raw:
        raise RuntimeError(f"cash_map.yaml missing non-empty `{section}` mapping")

    normalized: dict[str, str] = {}
    for raw_key, raw_value in raw.items():
        if raw_key is None or raw_value is None:
            raise RuntimeError(f"cash_map.yaml has blank key/value in `{section}`")
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if not key or not value:
            raise RuntimeError(f"cash_map.yaml has blank key/value in `{section}`")
        if uppercase_keys:
            key = key.upper()
        if uppercase_values:
            value = value.upper()
        normalized[key] = value
    return normalized


def _load_cash_map() -> dict[str, Any]:
    yaml_path = resolve_config_path("cash_map.yaml")
    with open(yaml_path, "r", encoding="utf-8") as handle:
        cash_map = yaml.safe_load(handle) or {}

    if not isinstance(cash_map, Mapping):
        raise RuntimeError(f"cash_map.yaml top-level value must be a mapping: {yaml_path}")

    proxy_by_currency = _normalize_mapping_section(
        cash_map,
        "proxy_by_currency",
        uppercase_keys=True,
    )
    alias_to_currency = _normalize_mapping_section(
        cash_map,
        "alias_to_currency",
        uppercase_values=True,
    )
    cash_equivalent_tickers = cash_map.get("cash_equivalent_tickers", []) or []
    if not isinstance(cash_equivalent_tickers, list):
        raise RuntimeError("cash_map.yaml `cash_equivalent_tickers` must be a list when present")

    return {
        "proxy_by_currency": proxy_by_currency,
        "alias_to_currency": alias_to_currency,
        "cash_equivalent_tickers": [
            str(ticker).strip()
            for ticker in cash_equivalent_tickers
            if str(ticker).strip()
        ],
    }


def _get_cash_map_cached() -> dict[str, Any]:
    global _cash_map_cache
    if _cash_map_cache is None:
        _cash_map_cache = _load_cash_map()
    return _cash_map_cache


def _get_proxy_by_currency_cached() -> dict[str, str]:
    global _proxy_by_currency_cache
    if _proxy_by_currency_cache is None:
        _proxy_by_currency_cache = dict(_get_cash_map_cached()["proxy_by_currency"])
    return _proxy_by_currency_cache


def _get_proxy_tickers_cached() -> set[str]:
    global _proxy_tickers_cache
    if _proxy_tickers_cache is None:
        _proxy_tickers_cache = set(_get_proxy_by_currency_cached().values())
    return _proxy_tickers_cache


def _get_proxy_ticker_to_currency_cached() -> dict[str, str]:
    global _proxy_ticker_to_currency_cache
    if _proxy_ticker_to_currency_cache is None:
        _proxy_ticker_to_currency_cache = {
            proxy: currency
            for currency, proxy in _get_proxy_by_currency_cached().items()
        }
    return _proxy_ticker_to_currency_cache


def _get_alias_to_currency_cached() -> dict[str, str]:
    global _alias_to_currency_cache
    if _alias_to_currency_cache is None:
        _alias_to_currency_cache = dict(_get_cash_map_cached()["alias_to_currency"])
    return _alias_to_currency_cache


def get_cash_map() -> dict[str, Any]:
    """Return a copy of the validated canonical cash mapping."""
    cash_map = _get_cash_map_cached()
    return {
        "proxy_by_currency": dict(cash_map["proxy_by_currency"]),
        "alias_to_currency": dict(cash_map["alias_to_currency"]),
        "cash_equivalent_tickers": list(cash_map["cash_equivalent_tickers"]),
    }


def get_cash_proxy_map() -> tuple[dict[str, str], dict[str, str]]:
    """Return currency proxy and broker-alias maps from the canonical cash map."""
    return (
        dict(_get_proxy_by_currency_cached()),
        dict(_get_alias_to_currency_cached()),
    )


def get_proxy_by_currency() -> dict[str, str]:
    """Return {ISO currency: proxy ticker} from the canonical cash map."""
    return dict(_get_proxy_by_currency_cached())


def get_alias_to_currency() -> dict[str, str]:
    """Return {broker cash alias: ISO currency} from the canonical cash map."""
    return dict(_get_alias_to_currency_cached())


def get_cash_equivalent_tickers() -> list[str]:
    """Return configured cash-equivalent tickers from the canonical cash map."""
    return list(_get_cash_map_cached()["cash_equivalent_tickers"])


def get_cash_proxy_tickers() -> set[str]:
    """Return the set of proxy ETF tickers configured by currency."""
    return set(_get_proxy_tickers_cached())


def clear_cash_map_cache() -> None:
    """Clear cached cash-map data after config updates or in tests."""
    global _cash_map_cache
    global _proxy_by_currency_cache
    global _proxy_tickers_cache
    global _proxy_ticker_to_currency_cache
    global _alias_to_currency_cache

    _cash_map_cache = None
    _proxy_by_currency_cache = None
    _proxy_tickers_cache = None
    _proxy_ticker_to_currency_cache = None
    _alias_to_currency_cache = None


def is_cur_ticker(ticker: str) -> bool:
    """True if the ticker is a CUR:* synthetic currency ticker (case-insensitive).

    NARROW: matches only the CUR:USD-style prefix format. Does NOT match
    proxy ETFs (SGOV, ERNS.L, IBGE.L) or broker-format aliases (CASH, USD:CASH).

    Use this for raw-format detection at providers, inputs, symbol resolution,
    and anywhere you want to distinguish "is this a synthetic currency ticker"
    from "is this any kind of cash representation".
    """
    return isinstance(ticker, str) and ticker.upper().startswith("CUR:")


def is_cash_proxy_ticker(ticker: str) -> bool:
    """True if the ticker is a CUR:* OR a currency proxy ETF (SGOV, ERNS.L, IBGE.L).

    MEDIUM: matches CUR:* prefix AND the values of cash_map.yaml's
    `proxy_by_currency` map. Does NOT match broker-format aliases like CASH.

    Use this in the returns-generation pipeline where we want to synthesize
    cash-like returns for both raw CUR:* positions and the ETFs that proxy
    them. Preserves the exact semantics of the old `_is_cash_proxy` helper.
    """
    if is_cur_ticker(ticker):
        return True
    if not isinstance(ticker, str):
        return False
    return ticker in _get_proxy_tickers_cached()


def is_cash_ticker(ticker: str) -> bool:
    """True if the ticker represents any form of cash/cash-equivalent.

    BROAD: matches CUR:* prefix (case-insensitive), proxy ETFs from
    `proxy_by_currency`, AND broker-format aliases from `alias_to_currency`
    (CASH, USD:CASH, etc.). This is the widest of the three ticker predicates.

    Use this for display labeling, ingestion-time detection, and any callsite
    that needs to recognize cash-like symbols regardless of format.
    """
    if is_cur_ticker(ticker):
        return True
    if not isinstance(ticker, str):
        return False
    return ticker in _get_proxy_tickers_cached() or ticker in _get_alias_to_currency_cached()


def is_cash_position(position: Mapping[str, Any]) -> bool:
    """True if a position dict represents a cash holding.

    Checks (in order): position['type'] == 'cash', is_cur_ticker(ticker).

    **Two-way check** (type + CUR:*), NOT three-way. Does NOT check the
    `is_cash_equivalent` field. This preserves the semantics of the 3 old
    majority callsites (routes/hedging.py:55, mcp_tools/rebalance.py:36,
    mcp_tools/positions.py:201) which were all 2-way.

    The one old callsite that WAS 3-way (portfolio_risk_engine/data_objects.py:85)
    migrates to `is_cash_position(p) or p.get("is_cash_equivalent") is True` -
    an explicit extra check at that one site only. Uses strict `is True`
    (NOT `bool(...)`) to match the old `data_objects.py:91` behavior exactly.
    Truthy non-bool values like `"false"`, `"yes"`, or `1` must NOT be treated
    as cash. This avoids a behavior expansion at the 3 majority sites (where
    proxies marked `is_cash_equivalent=True` at routes/positions.py:572 would
    newly be classified as cash).

    Uses is_cur_ticker (narrow) NOT is_cash_ticker (broad) - same rationale:
    broadening would newly match SGOV/CASH at migrated paths.

    Use this at position-level callsites (MCP tools, routes, rebalance,
    hedging). For ticker-only callsites, use the appropriate ticker predicate
    above (is_cur_ticker / is_cash_proxy_ticker / is_cash_ticker).
    """
    return position.get("type") == "cash" or is_cur_ticker(position.get("ticker", ""))


def cash_proxy_for_currency(currency: str) -> str | None:
    """Return the proxy ETF ticker for a given ISO currency (USD -> SGOV,
    GBP -> ERNS.L, EUR -> IBGE.L), or None if not mapped. YAML-backed."""
    if not isinstance(currency, str):
        return None
    return _get_proxy_by_currency_cached().get(currency.upper())


def currency_for_ticker(ticker: str) -> str | None:
    """Return the ISO currency code for a cash ticker, or None if not cash.

    Resolves CUR:* prefix (CUR:USD -> USD), proxy ETFs from
    proxy_by_currency (ERNS.L -> GBP, SGOV -> USD), and broker-format
    aliases from alias_to_currency (CASH -> USD). YAML-backed.
    """
    if not isinstance(ticker, str):
        return None
    if is_cur_ticker(ticker):
        currency = ticker.split(":", 1)[1].strip().upper()
        return currency or None
    # Reverse lookup: proxy ETF -> currency (ERNS.L -> GBP)
    proxy_currency = _get_proxy_ticker_to_currency_cached().get(ticker)
    if proxy_currency is not None:
        return proxy_currency
    return _get_alias_to_currency_cached().get(ticker)


__all__ = [
    "cash_proxy_for_currency",
    "clear_cash_map_cache",
    "currency_for_ticker",
    "get_alias_to_currency",
    "get_cash_equivalent_tickers",
    "get_cash_map",
    "get_cash_proxy_map",
    "get_cash_proxy_tickers",
    "get_proxy_by_currency",
    "is_cash_position",
    "is_cash_proxy_ticker",
    "is_cash_ticker",
    "is_cur_ticker",
]
