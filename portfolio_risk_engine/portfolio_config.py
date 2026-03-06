#!/usr/bin/env python3
# coding: utf-8

"""Portfolio configuration and normalization utilities for core analysis flows.

Called by:
- Core analysis entrypoints in ``core/portfolio_analysis.py``,
  ``core/performance_analysis.py``, and ``core/optimization.py``.
- Config adapter helpers in ``core/config_adapters.py``.

Contract notes:
- ``load_portfolio_config`` resolves canonical config payloads from YAML.
- ``standardize_portfolio_input`` is the single source of truth for
  weights/exposure normalization.
- ``latest_price`` is the core-layer price accessor used by standardization.
"""

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union, Iterator

import numpy as np
import pandas as pd
import yaml
from settings import OPTION_PRICING_PORTFOLIO_ENABLED

from portfolio_risk_engine.data_loader import fetch_monthly_close
from portfolio_risk_engine.portfolio_risk import normalize_weights
from portfolio_risk_engine._logging import (
    log_critical_alert,
    log_errors,
    log_timing,
    log_operation,
    log_service_health,
)
from portfolio_risk_engine.providers import get_currency_resolver, get_fx_provider
from portfolio_risk_engine._ticker import (
    select_fmp_symbol,
    normalize_fmp_price,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# Auto-detect cash positions from database (with YAML fallback)
@log_errors("medium")
@log_operation("cash_positions_detection")
@log_timing(1.0)
def get_cash_positions():
    """
    Discover the set of tickers that should be treated as cash proxies.

    Resolution order:
        1) Database: query `cash_mappings` via `DatabaseClient.get_cash_mappings()`
           and use `proxy_by_currency` values.
        2) YAML fallback: load `cash_map.yaml` from the project root and use
           `proxy_by_currency` values.
        3) Hard-coded defaults: a minimal set {"SGOV", "ESTR", "IB01", "CASH", "USD"}.

    Returns:
        set[str]: Unique tickers recognized as cash or cash-equivalent proxies.

    Notes:
        - Exposure filtering: Used to exclude positive cash positions when computing
          risky exposures and leverage, while still including negative cash balances
          (margin debt) as risk.
        - Display labeling: Also used by CLI/report formatting to label tickers via
          `format_ticker_with_label(...)`, so cash-like tickers render appropriately
          (e.g., grouping or special casing in displays).
        - The function is decorated with logging and performance instrumentation
          and will emit health signals when the database is unreachable.
    """
    # LOGGING: Add cash position detection logging with data source and timing
    # LOGGING: Add resource usage monitoring for cache initialization here
    # LOGGING: Add critical alert for database connection failures here
    import time
    start_time = time.time()

    try:
        # Try database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            cash_map = db_client.get_cash_mappings()

            return set(cash_map.get("proxy_by_currency", {}).values())
    except Exception as e:
        # LOGGING: Add critical alert for database connection failures
        response_time = time.time() - start_time
        log_critical_alert("database_connection_failure", "high", f"Database connection failed for cash positions", "Check database connectivity and credentials", details={"error": str(e), "operation": "get_cash_mappings"})
        log_service_health("PostgreSQL", "down", response_time, {"error": str(e)})

        # Fallback to YAML
        print(f"⚠️ Database unavailable ({e}), using cash_map.yaml fallback")
        try:
            with open("cash_map.yaml", "r") as f:
                cash_map = yaml.safe_load(f)
                return set(cash_map.get("proxy_by_currency", {}).values())
        except FileNotFoundError:
            # Fallback to common cash proxies
            print("⚠️ cash_map.yaml not found, using default cash proxies")
            return {"SGOV", "ESTR", "IB01", "CASH", "USD"}


_cash_positions_cache: set[str] | None = None


def _get_cash_positions_cached() -> set[str]:
    global _cash_positions_cache
    if _cash_positions_cache is None:
        _cash_positions_cache = set(get_cash_positions())
    return _cash_positions_cache


class _LazyCashPositions:
    """Set-like proxy that loads cash proxies only on first access."""

    def __contains__(self, item: object) -> bool:
        return item in _get_cash_positions_cached()

    def __iter__(self) -> Iterator[str]:
        return iter(_get_cash_positions_cached())

    def __len__(self) -> int:
        return len(_get_cash_positions_cached())


cash_positions = _LazyCashPositions()


@log_errors("high")
@log_operation("portfolio_standardization")
@log_timing(2.0)
def standardize_portfolio_input(
    raw_input: Dict[str, Dict[str, Union[float, int]]],
    price_fetcher: Callable[[str], float],
    *,
    currency_map: Optional[Dict[str, str]] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    instrument_types: Optional[Dict[str, str]] = None,
    contract_identities: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Union[Dict[str, float], float]]:
    """
    Normalize portfolio input into weights using shares, dollar value, or direct weight.

    Args:
        raw_input (dict): Dict of ticker → {"shares": int}, {"dollars": float}, or {"weight": float}
        price_fetcher (callable): Function to fetch latest price for a given ticker
        currency_map (dict, optional): Mapping of ticker -> ISO currency code (non-USD only)
        fmp_ticker_map (dict, optional): Mapping of display ticker -> FMP ticker
        instrument_types (dict, optional): Mapping of ticker -> instrument type.

    Returns:
        dict: {
            "weights": Dict[ticker, normalized weight],
            "dollar_exposure": Dict[ticker, dollar amount],
            "total_value": float,
            "net_exposure": float,
            "gross_exposure": float,
            "leverage": float,
            "notional_leverage": float,
        }
    """
    # LOGGING: Add portfolio standardization start logging with input size and format
    # LOGGING: Add workflow state logging for portfolio standardization workflow here
    # LOGGING: Add resource usage monitoring for portfolio processing here

    # LOGGING: Add portfolio processing logging with ticker count and validation
    # LOGGING: Add workflow state logging for portfolio processing completion here
    dollar_exposure = {}
    margin_exposure = {}  # Track margin-based values for NAV and leverage ratio.
    dollars_entry_tickers = set()  # track tickers using raw "dollars" (not price_fetcher)
    cash_positions = _get_cash_positions_cached()
    get_contract_spec = None
    if instrument_types:
        from brokerage.futures import get_contract_spec as _get_contract_spec

        get_contract_spec = _get_contract_spec

    # LOGGING: Add portfolio processing logging with ticker count and validation
    for ticker, entry in raw_input.items():
        if "weight" in entry:
            # Will normalize weights separately
            continue
        elif "dollars" in entry:
            raw_dollars = float(entry["dollars"])
            ccy = currency_map.get(ticker) if currency_map else None
            if ccy and ccy.upper() != "USD":
                try:
                    fx = get_fx_provider()
                    if fx is not None:
                        raw_dollars = raw_dollars * float(fx.get_fx_rate(ccy))
                except Exception:
                    pass
            dollar_exposure[ticker] = raw_dollars
            margin_exposure[ticker] = raw_dollars
            dollars_entry_tickers.add(ticker)
        elif "shares" in entry:
            price = price_fetcher(ticker)
            base_value = float(entry["shares"]) * price
            margin_exposure[ticker] = base_value

            normalized_ticker = str(ticker or "").strip().upper()
            instrument_type = str(
                (instrument_types or {}).get(normalized_ticker)
                or (instrument_types or {}).get(str(ticker or "").strip())
                or ""
            ).strip().lower()
            if instrument_type == "futures" and get_contract_spec is not None:
                spec = get_contract_spec(normalized_ticker)
                if spec:
                    dollar_exposure[ticker] = base_value * float(spec.multiplier)
                else:
                    dollar_exposure[ticker] = base_value
            elif instrument_type == "option" and OPTION_PRICING_PORTFOLIO_ENABLED:
                ci = (contract_identities or {}).get(normalized_ticker) or {}
                mult = float(ci.get("multiplier", 100))
                dollar_exposure[ticker] = base_value * mult
            else:
                dollar_exposure[ticker] = base_value
        else:
            raise ValueError(f"Invalid input for {ticker}: must provide 'shares', 'dollars', or 'weight'.")

    # Warn only for "dollars" entries — "shares" entries go through price_fetcher
    # which already handles FX via latest_price() FMP profile fallback.
    if not currency_map and fmp_ticker_map and dollars_entry_tickers:
        from portfolio_risk_engine._logging import portfolio_logger
        for ticker in dollars_entry_tickers:
            fmp_sym = fmp_ticker_map.get(ticker, "")
            if any(fmp_sym.endswith(s) for s in (".L", ".TO", ".PA", ".DE", ".HK")):
                portfolio_logger.warning(
                    f"{ticker} appears foreign (FMP: {fmp_sym}) but no currency_map provided - "
                    "treating dollars entry as USD"
                )

    # If any weights were specified, override dollar_exposure logic
    if all("weight" in entry for entry in raw_input.values()):
        weights = {t: float(v["weight"]) for t, v in raw_input.items()}
        normalized_weights = normalize_weights(weights)

        # Calculate exposure excluding only POSITIVE cash positions
        # Negative cash positions (margin debt) should be included
        risky_weights = {
            t: w for t, w in weights.items()
            if t not in cash_positions or w < 0  # Include negative cash positions (margin debt)
        }
        net_exposure = sum(risky_weights.values())
        gross_exposure = sum(abs(w) for w in risky_weights.values())

        leverage = gross_exposure / net_exposure if net_exposure != 0 else np.inf

        return {
            "weights": normalized_weights,
            "dollar_exposure": None,
            "total_value": None,
            "net_exposure": net_exposure,
            "gross_exposure": gross_exposure,
            "leverage": leverage,
            "notional_leverage": 1.0,
        }

    total_notional = sum(dollar_exposure.values())
    weights = {t: v / total_notional for t, v in dollar_exposure.items()}

    # Calculate exposure excluding only POSITIVE cash positions
    # Negative cash positions (margin debt) should be included
    risky_weights = {
        t: w for t, w in weights.items()
        if t not in cash_positions or w < 0  # Include negative cash positions (margin debt)
    }
    net_exposure = sum(risky_weights.values())
    gross_exposure = sum(abs(w) for w in risky_weights.values())

    leverage = gross_exposure / net_exposure if net_exposure else np.inf
    margin_total = sum(margin_exposure.values()) if margin_exposure else total_notional
    notional_leverage = total_notional / margin_total if margin_total > 0 else 1.0

    return {
        "weights": weights,
        "dollar_exposure": dollar_exposure,
        "total_value": margin_total,
        "net_exposure": net_exposure,
        "gross_exposure": gross_exposure,
        "leverage": leverage,
        "notional_leverage": notional_leverage,
    }


@log_errors("high")
def latest_price(
    ticker: str,
    *,
    fmp_ticker: str | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
    currency: str | None = None,
    instrument_types: dict[str, str] | None = None,
    contract_identity: dict[str, Any] | None = None,
) -> float:
    """
    Fetches the latest available month-end closing price for a given ticker,
    converted to USD.

    FX conversion follows three paths:
    1. Explicit currency provided → convert using month-end FX rate
    2. Foreign FMP mapping exists (fmp_ticker/fmp_ticker_map) → infer currency
       from FMP profile via fetch_fmp_quote_with_currency(), then convert
    3. No currency info, no foreign mapping → assume domestic USD, return raw price

    Args:
        ticker (str): Ticker symbol of the stock or ETF.
        fmp_ticker (str, optional): FMP-compatible symbol override.
        fmp_ticker_map (dict, optional): Mapping of ticker -> fmp_ticker.
        currency (str, optional): Explicit currency code for FX conversion.
        instrument_types (dict, optional): Mapping of ticker -> instrument type.

    Returns:
        float: Most recent non-NaN month-end closing price in USD.
    """
    normalized_ticker = str(ticker or "").strip().upper()
    instrument_type = str(
        (instrument_types or {}).get(normalized_ticker)
        or (instrument_types or {}).get(str(ticker or "").strip())
        or ""
    ).strip().lower()
    if instrument_type == "futures":
        return _latest_futures_price(
            ticker,
            currency=currency,
            fmp_ticker=fmp_ticker,
            fmp_ticker_map=fmp_ticker_map,
        )
    if instrument_type == "option" and OPTION_PRICING_PORTFOLIO_ENABLED:
        return _latest_option_price(ticker, contract_identity=contract_identity)

    prices = fetch_monthly_close(
        ticker,
        fmp_ticker=fmp_ticker,
        fmp_ticker_map=fmp_ticker_map,
    )
    raw_price = prices.dropna().iloc[-1]

    if currency and currency.upper() == "USD":
        return raw_price

    # No currency info and no foreign ticker mapping — assume domestic (USD).
    # Foreign stocks require fmp_ticker_map (e.g. AT→AT.L) for correct exchange
    # resolution, so absence implies US-listed. Avoids extra FMP profile API call.
    if not currency and not fmp_ticker and not (fmp_ticker_map and ticker in fmp_ticker_map):
        return raw_price

    fmp_symbol = select_fmp_symbol(
        ticker,
        fmp_ticker=fmp_ticker,
        fmp_ticker_map=fmp_ticker_map,
    )
    resolver = get_currency_resolver()
    fmp_currency = resolver.infer_currency(fmp_symbol)
    normalized_price, base_currency = normalize_fmp_price(raw_price, fmp_currency)

    effective_currency = currency or base_currency
    if effective_currency and effective_currency.upper() != "USD":
        try:
            fx = get_fx_provider()
            if fx is not None:
                fx_rate = float(fx.get_fx_rate(effective_currency))
                if normalized_price is not None:
                    normalized_price = normalized_price * fx_rate
        except Exception:
            pass

    return normalized_price if normalized_price is not None else raw_price


def _latest_option_price(
    ticker: str,
    *,
    contract_identity: dict[str, Any] | None = None,
) -> float:
    """Fetch latest option price through ProviderRegistry chain."""
    from providers.bootstrap import get_registry

    registry = get_registry()
    chain = registry.get_price_chain("option")

    # Providers need concrete date windows — use trailing 24 months.
    end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
    start_date = (pd.Timestamp.now() - pd.DateOffset(months=24)).strftime("%Y-%m-%d")

    for provider in chain:
        if (
            provider.provider_name == "ibkr"
            and not (isinstance(contract_identity, dict) and contract_identity)
        ):
            continue
        try:
            series = provider.fetch_monthly_close(
                ticker,
                start_date,
                end_date,
                instrument_type="option",
                contract_identity=contract_identity,
            )
            if isinstance(series, pd.Series) and not series.dropna().empty:
                return float(series.dropna().iloc[-1])
        except Exception:
            continue

    # All providers failed — return 0.0 so standardize_portfolio_input()
    # treats this as a zero-value position (excluded from weights).
    # Raising would abort the entire analysis for one unpriceable option.
    from portfolio_risk_engine._logging import portfolio_logger

    portfolio_logger.warning(f"Cannot price option {ticker}: all providers failed, excluding from analysis")
    return 0.0


def _latest_futures_price(
    ticker: str,
    *,
    currency: str | None = None,
    fmp_ticker: str | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
) -> float:
    """Fetch latest futures price through the futures pricing chain."""
    from brokerage.futures import get_contract_spec
    from brokerage.futures.pricing import get_default_pricing_chain

    normalized_ticker = str(ticker or "").strip().upper()
    spec = get_contract_spec(normalized_ticker)

    explicit_map_symbol = (fmp_ticker_map or {}).get(ticker)
    if explicit_map_symbol is None and normalized_ticker != str(ticker or "").strip():
        explicit_map_symbol = (fmp_ticker_map or {}).get(normalized_ticker)
    has_explicit_override = bool(fmp_ticker) or bool(explicit_map_symbol)
    if has_explicit_override:
        resolved_fmp = str(fmp_ticker or explicit_map_symbol or "").strip() or None
    else:
        resolved_fmp = spec.fmp_symbol if spec else None

    chain = get_default_pricing_chain()
    raw_price = float(chain.fetch_latest_price(normalized_ticker, alt_symbol=resolved_fmp))

    effective_currency = currency or (spec.currency if spec else None)
    if effective_currency and effective_currency.upper() != "USD":
        try:
            fx = get_fx_provider()
            if fx is not None:
                raw_price = raw_price * float(fx.get_fx_rate(effective_currency))
        except Exception:
            pass

    return raw_price


@log_errors("high")
@log_operation("config_loading")
@log_timing(0.5)
def load_portfolio_config(
    filepath: str = "portfolio.yaml",
    price_fetcher: Callable[[str], float] | None = None,
) -> Dict[str, Any]:
    """
    Load the YAML and return a dict with parsed + normalised fields.
    No printing, no side effects.
    """
    resolved_path = Path(filepath)
    if not resolved_path.is_absolute() and not resolved_path.exists():
        candidate = _PROJECT_ROOT / resolved_path
        if candidate.exists():
            resolved_path = candidate

    with open(resolved_path, "r") as f:
        cfg_raw = yaml.safe_load(f)

    # • Keep the original keys for downstream code
    cfg: Dict[str, Any] = dict(cfg_raw)          # shallow copy

    fmp_ticker_map = cfg.get("fmp_ticker_map")
    currency_map = cfg.get("currency_map")
    instrument_types = cfg.get("instrument_types")
    if price_fetcher is None:
        if fmp_ticker_map:
            price_fetcher = lambda t: latest_price(
                t,
                fmp_ticker_map=fmp_ticker_map,
                currency=currency_map.get(t) if currency_map else None,
                instrument_types=instrument_types,
            )
        else:
            price_fetcher = lambda t: latest_price(
                t,
                currency=currency_map.get(t) if currency_map else None,
                instrument_types=instrument_types,
            )
    parsed = standardize_portfolio_input(
        cfg["portfolio_input"],
        price_fetcher,
        currency_map=currency_map,
        fmp_ticker_map=fmp_ticker_map,
        instrument_types=instrument_types,
    )

    cfg.update(
        weights=parsed["weights"],
        dollar_exposure=parsed["dollar_exposure"],
        total_value=parsed["total_value"],
        net_exposure=parsed["net_exposure"],
        gross_exposure=parsed["gross_exposure"],
        leverage=parsed["leverage"],
        notional_leverage=parsed.get("notional_leverage", 1.0),
    )
    return cfg
