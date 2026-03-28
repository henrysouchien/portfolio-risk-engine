from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd

from portfolio_risk_engine.performance_metrics_engine import compute_performance_metrics
from portfolio_risk_engine.data_loader import fetch_monthly_close, fetch_monthly_treasury_rates
from portfolio_risk_engine.factor_utils import calc_monthly_returns
from ibkr.compat import (
    fetch_ibkr_bond_monthly_close,
    fetch_ibkr_daily_close_bond,
    fetch_ibkr_daily_close_fx,
    fetch_ibkr_daily_close_futures,
    fetch_ibkr_fx_monthly_close,
    fetch_ibkr_monthly_close,
    fetch_ibkr_option_monthly_mark,
    get_ibkr_futures_fmp_map,
)
from portfolio_risk_engine.providers import get_fx_provider
from providers.flows.common import build_slice_key
from providers.flows.extractor import extract_provider_flow_events
from providers.bs_option_price import OptionBSPriceProvider
from providers.fmp_price import FMPPriceProvider
from providers.ibkr_price import IBKRPriceProvider
from providers.interfaces import PriceSeriesProvider
from providers.normalizers.schwab import get_schwab_security_lookup
from providers.registry import ProviderRegistry
from providers.routing import get_canonical_provider, resolve_provider_token
from providers.routing_config import resolve_account_aliases
from providers.ticker_resolver import AliasMapResolver, TickerResolver
from settings import (
    BACKFILL_FILE_PATH,
    DATA_QUALITY_THRESHOLDS,
    REALIZED_COVERAGE_TARGET,
    REALIZED_MAX_INCOMPLETE_TRADES,
    REALIZED_MAX_RECONCILIATION_GAP_PCT,
    REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE,
    REALIZED_PROVIDER_FLOW_SOURCES,
    REALIZED_USE_PROVIDER_FLOWS,
    OPTION_BS_FALLBACK_ENABLED,
    TRANSACTION_STORE_MAX_AGE_HOURS,
    TRANSACTION_STORE_READ,
    TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES,
)
from trading_analysis.analyzer import TradingAnalyzer
from trading_analysis.data_fetcher import fetch_transactions_for_source, match_institution
from trading_analysis.fifo_matcher import FIFOMatcher, IncompleteTrade, OpenLot
from trading_analysis.instrument_meta import InstrumentMeta, coerce_instrument_type
from trading_analysis.symbol_utils import parse_option_contract_identity_from_symbol

from . import _helpers

_ORIGINAL_FETCH_IBKR_MONTHLY_CLOSE = fetch_ibkr_monthly_close
_ORIGINAL_FETCH_IBKR_FX_MONTHLY_CLOSE = fetch_ibkr_fx_monthly_close
_ORIGINAL_FETCH_IBKR_BOND_MONTHLY_CLOSE = fetch_ibkr_bond_monthly_close
_ORIGINAL_FETCH_IBKR_DAILY_CLOSE_FUTURES = fetch_ibkr_daily_close_futures
_ORIGINAL_FETCH_IBKR_DAILY_CLOSE_FX = fetch_ibkr_daily_close_fx
_ORIGINAL_FETCH_IBKR_DAILY_CLOSE_BOND = fetch_ibkr_daily_close_bond

@dataclass
class PriceResult:
    series: pd.Series
    success_provider: str | None = None
    attempts: list[tuple[str, str, Exception | None]] = field(default_factory=list)

def _build_default_price_registry() -> ProviderRegistry:
    from providers.bootstrap import build_default_registry

    monthly_close_fetcher = fetch_monthly_close
    ibkr_futures_fetcher = _helpers._shim_attr("fetch_ibkr_monthly_close", fetch_ibkr_monthly_close)
    ibkr_fx_fetcher = _helpers._shim_attr("fetch_ibkr_fx_monthly_close", fetch_ibkr_fx_monthly_close)
    ibkr_bond_fetcher = _helpers._shim_attr("fetch_ibkr_bond_monthly_close", fetch_ibkr_bond_monthly_close)
    ibkr_option_fetcher = _helpers._shim_attr("fetch_ibkr_option_monthly_mark", fetch_ibkr_option_monthly_mark)
    ibkr_futures_daily_fetcher = _helpers._shim_attr("fetch_ibkr_daily_close_futures", fetch_ibkr_daily_close_futures)
    ibkr_fx_daily_fetcher = _helpers._shim_attr("fetch_ibkr_daily_close_fx", fetch_ibkr_daily_close_fx)
    ibkr_bond_daily_fetcher = _helpers._shim_attr("fetch_ibkr_daily_close_bond", fetch_ibkr_daily_close_bond)

    def _fetch_daily_close_for_registry(*args: Any, **kwargs: Any) -> pd.Series:
        # Preserve monkeypatched test behavior: if this module's
        # `fetch_monthly_close` has been overridden, route daily fetches through
        # that override instead of the FMP daily helper.
        if monthly_close_fetcher is not _helpers._ORIGINAL_FETCH_MONTHLY_CLOSE:
            return monthly_close_fetcher(*args, **kwargs)
        from fmp.compat import fetch_daily_close as _fetch_daily_close

        return _fetch_daily_close(*args, **kwargs)

    if (
        ibkr_futures_daily_fetcher is _ORIGINAL_FETCH_IBKR_DAILY_CLOSE_FUTURES
        and ibkr_futures_fetcher is not _ORIGINAL_FETCH_IBKR_MONTHLY_CLOSE
    ):
        ibkr_futures_daily_fetcher = ibkr_futures_fetcher

    if (
        ibkr_fx_daily_fetcher is _ORIGINAL_FETCH_IBKR_DAILY_CLOSE_FX
        and ibkr_fx_fetcher is not _ORIGINAL_FETCH_IBKR_FX_MONTHLY_CLOSE
    ):
        ibkr_fx_daily_fetcher = ibkr_fx_fetcher

    if (
        ibkr_bond_daily_fetcher is _ORIGINAL_FETCH_IBKR_DAILY_CLOSE_BOND
        and ibkr_bond_fetcher is not _ORIGINAL_FETCH_IBKR_BOND_MONTHLY_CLOSE
    ):
        ibkr_bond_daily_fetcher = ibkr_bond_fetcher

    return build_default_registry(
        fmp_fetcher=monthly_close_fetcher,
        fmp_daily_fetcher=_fetch_daily_close_for_registry,
        ibkr_futures_fetcher=ibkr_futures_fetcher,
        ibkr_fx_fetcher=ibkr_fx_fetcher,
        ibkr_bond_fetcher=ibkr_bond_fetcher,
        ibkr_option_fetcher=ibkr_option_fetcher,
        ibkr_futures_daily_fetcher=ibkr_futures_daily_fetcher,
        ibkr_fx_daily_fetcher=ibkr_fx_daily_fetcher,
        ibkr_bond_daily_fetcher=ibkr_bond_daily_fetcher,
    )

def _fetch_price_from_chain(
    providers: list[PriceSeriesProvider],
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    *,
    instrument_type: str,
    contract_identity: dict[str, Any] | None,
    ticker_alias_map: dict[str, str] | None,
    ticker_resolver: TickerResolver | None = None,
) -> PriceResult:
    result = PriceResult(series=pd.Series(dtype=float))
    if ticker_resolver is None:
        ticker_resolver = AliasMapResolver(ticker_alias_map)
    for provider in providers:
        if (
            instrument_type == "option"
            and provider.provider_name == "ibkr"
            and not (isinstance(contract_identity, dict) and contract_identity)
        ):
            result.attempts.append((provider.provider_name, "skipped_missing_contract_identity", None))
            continue

        try:
            fetch_daily = getattr(provider, "fetch_daily_close", None)
            if callable(fetch_daily):
                series = fetch_daily(
                    symbol,
                    start_date,
                    end_date,
                    instrument_type=instrument_type,
                    contract_identity=contract_identity,
                    ticker_resolver=ticker_resolver,
                )
            else:
                series = provider.fetch_monthly_close(
                    symbol,
                    start_date,
                    end_date,
                    instrument_type=instrument_type,
                    contract_identity=contract_identity,
                    ticker_resolver=ticker_resolver,
                )
            if not isinstance(series, pd.Series):
                series = pd.Series(dtype=float)
            normalized = _helpers._series_from_cache(series)
            if not normalized.empty and not normalized.dropna().empty:
                result.series = normalized
                result.success_provider = provider.provider_name
                result.attempts.append((provider.provider_name, "success", None))
                return result
            result.attempts.append((provider.provider_name, "empty", None))
        except Exception as exc:
            result.attempts.append((provider.provider_name, "error", exc))
    return result

def _emit_pricing_diagnostics(
    *,
    ticker: str,
    instrument_type: str,
    contract_identity: dict[str, Any] | None,
    result: PriceResult,
    warnings: list[str],
    ibkr_priced_symbols: dict[str, set[str]],
) -> str:
    unpriceable_reason = "no_price_data"

    def _status_code(exc: Exception) -> int | None:
        raw = getattr(exc, "status_code", None)
        try:
            return int(raw)
        except Exception:
            return None

    def _fmp_error_message(exc: Exception) -> str:
        status_code = _status_code(exc)
        if status_code == 402:
            if instrument_type == "futures":
                return (
                    f"FMP plan does not include futures symbol {ticker} (HTTP 402); "
                    "using IBKR fallback."
                )
            if instrument_type == "fx":
                return f"FMP plan does not include FX symbol {ticker} (HTTP 402); trying IBKR fallback."
            if instrument_type == "bond":
                return f"FMP plan does not include bond symbol {ticker} (HTTP 402); trying IBKR fallback."
            if instrument_type == "option":
                return f"FMP plan does not include option symbol {ticker} (HTTP 402); trying IBKR fallback."
            return f"FMP plan does not include symbol {ticker} (HTTP 402)."

        if instrument_type == "futures":
            return f"FMP price fetch failed for futures {ticker}: {exc}; trying IBKR fallback."
        if instrument_type == "fx":
            return f"FMP price fetch failed for FX {ticker}: {exc}; trying IBKR fallback."
        if instrument_type == "bond":
            return f"FMP price fetch failed for bond {ticker}: {exc}; trying IBKR fallback."
        return f"Price fetch failed for {ticker}: {exc}"

    for provider_name, outcome, exc in result.attempts:
        if provider_name == "fmp" and outcome == "error" and exc is not None:
            warnings.append(_fmp_error_message(exc))
            if _status_code(exc) == 402:
                unpriceable_reason = f"{instrument_type}_fmp_plan_blocked"
            else:
                unpriceable_reason = f"{instrument_type}_fmp_error"

    if result.success_provider == "ibkr":
        if instrument_type == "futures":
            warnings.append(
                f"Priced futures {ticker} via IBKR Gateway fallback ({len(result.series)} monthly bars)."
            )
        elif instrument_type == "fx":
            warnings.append(
                f"Priced FX {ticker} via IBKR Gateway fallback ({len(result.series)} monthly bars)."
            )
        elif instrument_type == "bond":
            warnings.append(
                f"Priced bond {ticker} via IBKR Gateway fallback ({len(result.series)} monthly bars)."
            )
        elif instrument_type == "option":
            warnings.append(
                f"Priced option {ticker} via IBKR Gateway fallback ({len(result.series)} monthly bars)."
            )
        ibkr_priced_symbols[instrument_type].add(ticker)
        return unpriceable_reason

    if result.success_provider == "bs_option":
        warnings.append(
            f"Priced option {ticker} via Black-Scholes theoretical fallback "
            f"({len(result.series)} monthly bars). Prices are theoretical."
        )
        return unpriceable_reason

    ibkr_attempt = next((a for a in result.attempts if a[0] == "ibkr"), None)
    if ibkr_attempt:
        _, outcome, exc = ibkr_attempt
        if outcome == "skipped_missing_contract_identity":
            if instrument_type == "option":
                warnings.append(
                    f"Skipped IBKR fallback for option {ticker}: missing contract_identity "
                    "(requires con_id or expiry/strike/right)."
                )
                unpriceable_reason = "option_missing_contract_identity"
        elif outcome == "empty":
            if instrument_type == "futures":
                warnings.append(
                    f"IBKR fallback returned no data for futures {ticker} (Gateway may not be running)."
                )
                unpriceable_reason = "futures_ibkr_no_data"
            elif instrument_type == "fx":
                warnings.append(
                    f"IBKR fallback returned no data for FX {ticker} (Gateway may not be running)."
                )
                unpriceable_reason = "fx_ibkr_no_data"
            elif instrument_type == "bond":
                warnings.append(
                    f"IBKR fallback returned no data for bond {ticker} (Gateway/entitlements may be unavailable)."
                )
                unpriceable_reason = "bond_ibkr_no_data"
            elif instrument_type == "option":
                if not contract_identity:
                    warnings.append(
                        f"No contract_identity available for option {ticker}; IBKR option pricing may fail."
                    )
                warnings.append(
                    f"IBKR fallback returned no data for option {ticker} (entitlements or contract details may be unavailable)."
                )
                unpriceable_reason = "option_no_fifo_or_ibkr_data"
        elif outcome == "error" and exc is not None:
            if instrument_type == "futures":
                warnings.append(f"IBKR fallback also failed for futures {ticker}: {exc}")
                unpriceable_reason = "futures_ibkr_error"
            elif instrument_type == "fx":
                warnings.append(f"IBKR fallback also failed for FX {ticker}: {exc}")
                unpriceable_reason = "fx_ibkr_error"
            elif instrument_type == "bond":
                warnings.append(f"IBKR fallback also failed for bond {ticker}: {exc}")
                unpriceable_reason = "bond_ibkr_error"
            elif instrument_type == "option":
                warnings.append(f"IBKR fallback also failed for option {ticker}: {exc}")
                unpriceable_reason = "option_ibkr_error"

    return unpriceable_reason

__all__ = [
    'PriceResult',
    '_build_default_price_registry',
    '_fetch_price_from_chain',
    '_emit_pricing_diagnostics',
]
