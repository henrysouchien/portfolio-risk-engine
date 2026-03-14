from __future__ import annotations

import json
import os
import re
import sys
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
    fetch_ibkr_fx_monthly_close,
    fetch_ibkr_monthly_close,
    fetch_ibkr_option_monthly_mark,
    get_ibkr_futures_fmp_map,
)
from portfolio_risk_engine.providers import get_fx_provider
from providers.flows.common import build_slice_key
from providers.flows.extractor import extract_provider_flow_events
from providers.fmp_price import FMPPriceProvider
from providers.ibkr_price import IBKRPriceProvider
from providers.interfaces import PriceSeriesProvider
from providers.normalizers.schwab import get_schwab_security_lookup
from providers.registry import ProviderRegistry
from providers.routing import get_canonical_provider, resolve_provider_token
from providers.routing_config import resolve_account_aliases
from settings import (
    BACKFILL_FILE_PATH,
    DATA_QUALITY_THRESHOLDS,
    REALIZED_COVERAGE_TARGET,
    REALIZED_MAX_INCOMPLETE_TRADES,
    REALIZED_MAX_RECONCILIATION_GAP_PCT,
    REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE,
    REALIZED_PROVIDER_FLOW_SOURCES,
    REALIZED_USE_PROVIDER_FLOWS,
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

def _event_fx_rate(currency: str, when: datetime, fx_cache: Dict[str, pd.Series]) -> float:
    """Get FX currency->USD rate for event timestamp."""
    ccy = (currency or "USD").upper()
    if ccy == "USD":
        return 1.0
    return _helpers._value_at_or_before(fx_cache.get(ccy), when, default=1.0)

def get_monthly_fx_series(currency: str, start_date=None, end_date=None) -> pd.Series:
    """Compatibility wrapper routed through the configured FX provider."""
    return get_fx_provider().get_monthly_fx_series(currency, start_date, end_date)

def get_daily_fx_series(currency: str, start_date=None, end_date=None) -> pd.Series:
    """Compatibility wrapper for daily FX series with monthly fallback."""
    # Preserve monkeypatched test behavior by honoring overridden monthly helper.
    if get_monthly_fx_series is not _helpers._ORIGINAL_GET_MONTHLY_FX_SERIES:
        return get_monthly_fx_series(currency, start_date, end_date)
    rpa_mod = sys.modules.get("core.realized_performance_analysis")
    if rpa_mod is not None:
        fn = getattr(rpa_mod, "get_monthly_fx_series", None)
        if fn is not None and fn is not _helpers._ORIGINAL_GET_MONTHLY_FX_SERIES:
            return fn(currency, start_date, end_date)

    provider = get_fx_provider()
    getter = getattr(provider, "get_daily_fx_series", None)
    if callable(getter):
        return getter(currency, start_date, end_date)
    return provider.get_monthly_fx_series(currency, start_date, end_date)

def _build_fx_cache(
    *,
    currencies: Iterable[str],
    inception_date: datetime,
    end_date: datetime,
    warnings: List[str],
) -> Dict[str, pd.Series]:
    """Fetch and normalize daily FX series for requested currencies."""
    fx_cache: Dict[str, pd.Series] = {}
    for ccy in sorted({str(c or "USD").upper() for c in currencies}):
        try:
            fx_cache[ccy] = _helpers._series_from_cache(
                get_daily_fx_series(ccy, inception_date, end_date)
            )
        except Exception as exc:
            warnings.append(f"FX series fetch failed for {ccy}: {exc}; using 1.0 fallback.")
            fx_cache[ccy] = pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp(inception_date)]))
    return fx_cache

__all__ = [
    '_event_fx_rate',
    'get_monthly_fx_series',
    'get_daily_fx_series',
    '_build_fx_cache',
]
