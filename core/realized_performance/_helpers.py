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

_ORIGINAL_FETCH_MONTHLY_CLOSE = fetch_monthly_close

TYPE_ORDER = {
    "SELL": 0,
    "SHORT": 1,
    "INCOME": 2,
    "PROVIDER_FLOW": 2,
    "BUY": 3,
    "COVER": 4,
    # After BUY/COVER so same-day futures opens adjust position state before MTM settles.
    "FUTURES_MTM": 5,
}

_FX_PAIR_SYMBOL_RE = re.compile(r"^[A-Z]{3}\.[A-Z]{3}$")

_IBKR_ACCOUNT_ID_RE = re.compile(r"^u\d+$", re.IGNORECASE)

_PSEUDO_SYMBOL_EXACT = frozenset({
    "MARGIN_INTEREST",
    "INTEREST",
    "UNRESOLVED_DIVIDEND",
    "DEPOSIT",
    "USD",
})

REALIZED_PROVIDER_ALIAS_MAP = {
    "IBKR_FLEX": "IBKR",
    "INTERACTIVE_BROKERS": "IBKR",
}

def _is_fx_artifact_symbol(symbol: str) -> bool:
    return bool(_FX_PAIR_SYMBOL_RE.match(str(symbol or "").strip().upper()))

def _infer_instrument_type_from_transaction(txn: Dict[str, Any]) -> str:
    """Infer instrument_type for legacy transactions that lack explicit tags."""
    explicit = txn.get("instrument_type")
    if explicit:
        return coerce_instrument_type(explicit, default="equity")

    trade_type = str(txn.get("type") or "").strip().upper()
    if trade_type in ("DIVIDEND", "INTEREST"):
        return "income"

    symbol = str(txn.get("symbol") or "").strip().upper()
    if symbol.startswith("UNKNOWN"):
        return "unknown"
    if _is_fx_artifact_symbol(symbol):
        return "fx_artifact"
    if bool(txn.get("is_option")):
        return "option"
    if bool(txn.get("is_futures")):
        return "futures"
    return "equity"


def _is_pseudo_symbol(symbol: str) -> bool:
    """Return True for synthetic/placeholder symbols that should not hit STS."""
    s = str(symbol or "").strip().upper()
    if not s:
        return True
    if s in _PSEUDO_SYMBOL_EXACT:
        return True
    if s.startswith("UNKNOWN"):
        return True
    if s.startswith("CUR:"):
        return True
    if s.endswith("IBKR MANAGED SECURITIES"):
        return True
    return False

def _infer_position_instrument_type(position: Dict[str, Any]) -> str:
    """Infer instrument_type from current-position row fields."""
    explicit = position.get("instrument_type")
    if explicit:
        return coerce_instrument_type(explicit, default="equity")

    ticker = str(position.get("ticker") or "").strip().upper()
    if ticker.startswith("UNKNOWN"):
        return "unknown"
    if _is_fx_artifact_symbol(ticker):
        return "fx_artifact"

    snaptrade_code = str(position.get("snaptrade_type_code") or "").strip().lower()
    if snaptrade_code in {"op", "opt"}:
        return "option"
    if snaptrade_code in {"fut", "future"}:
        return "futures"
    if snaptrade_code in {"bnd", "bond"}:
        return "bond"
    if snaptrade_code in {"cash", "fx", "forex"}:
        return "fx_artifact"
    if snaptrade_code == "oef":
        return "mutual_fund"
    # SnapTrade uses security_type="mutual_fund" for CEFs too; keep them exchange-traded here.
    if snaptrade_code == "cef":
        return "equity"

    type_tokens = [
        str(position.get("type") or "").strip().lower(),
        str(position.get("security_type") or "").strip().lower(),
    ]
    joined = " ".join(tok for tok in type_tokens if tok)
    if "option" in joined or "derivative" in joined:
        return "option"
    if "future" in joined:
        return "futures"
    if "bond" in joined or "fixed income" in joined or "treasury" in joined:
        return "bond"
    if "cash" in joined or "currency" in joined or "fx" in joined:
        return "fx_artifact"
    if "mutual" in joined:
        return "mutual_fund"
    if "open" in joined and "fund" in joined:
        return "mutual_fund"

    return "equity"

def _to_datetime(value: Any) -> Optional[datetime]:
    """Convert value to naive datetime where possible."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return pd.Timestamp(value).to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None

def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float with safe fallback."""
    try:
        out = float(value)
        if np.isnan(out) or not np.isfinite(out):
            return default
        return out
    except Exception:
        return default

def _value_at_or_before(series: Optional[pd.Series], when: Any, default: float = 0.0) -> float:
    """Get latest series value <= when, with nearest fallback."""
    if series is None or len(series) == 0:
        return default

    ts = pd.Timestamp(when)
    s = series.dropna()
    if s.empty:
        return default

    s = s.sort_index()
    prior = s[s.index <= ts]
    if not prior.empty:
        return _as_float(prior.iloc[-1], default)

    future = s[s.index > ts]
    if not future.empty:
        return _as_float(future.iloc[0], default)

    return default

def _series_from_cache(series: Optional[pd.Series]) -> pd.Series:
    """Normalize cached series to sorted datetime-indexed float series."""
    if series is None:
        return pd.Series(dtype=float)
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index)
    return series.sort_index().astype(float)

def _option_fifo_terminal_series(
    symbol: str,
    fifo_transactions: List[Dict[str, Any]],
    end_date: Any,
) -> pd.Series:
    """Build a 1-point option terminal price series from FIFO close transactions."""
    sym = str(symbol or "").strip().upper()
    end_ts = pd.Timestamp(end_date)
    terminal_event: tuple[datetime, float] | None = None
    for txn in fifo_transactions:
        txn_symbol = str(txn.get("symbol") or "").strip().upper()
        txn_type = str(txn.get("type") or "").upper()
        if txn_symbol != sym or txn_type not in {"SELL", "COVER"}:
            continue
        close_date = _to_datetime(txn.get("date"))
        close_price = _as_float(txn.get("price"), default=np.nan)
        if close_date is None or not np.isfinite(close_price):
            continue
        if close_date > end_ts.to_pydatetime().replace(tzinfo=None):
            continue
        if terminal_event is None or close_date > terminal_event[0]:
            terminal_event = (close_date, close_price)

    if terminal_event is None:
        return pd.Series(dtype=float)

    ts, price = terminal_event
    series = pd.Series([float(price)], index=pd.DatetimeIndex([pd.Timestamp(ts)]), name=sym)
    return series.sort_index()

def _option_fifo_terminal_source(
    symbol: str,
    fifo_transactions: list,
    end_date: str | datetime,
) -> str | None:
    """Return the source of the terminal SELL/COVER event for this option.

    Mirrors _option_fifo_terminal_series() selection logic: same symbol,
    SELL/COVER type, valid price, date <= end_date, latest date wins.
    """
    sym = str(symbol or "").strip().upper()
    end_ts = pd.Timestamp(end_date).to_pydatetime().replace(tzinfo=None)
    best_date: datetime | None = None
    best_source: str | None = None
    for txn in fifo_transactions:
        txn_symbol = str(txn.get("symbol") or "").strip().upper()
        txn_type = str(txn.get("type") or "").upper()
        if txn_symbol != sym or txn_type not in {"SELL", "COVER"}:
            continue
        close_date = _to_datetime(txn.get("date"))
        close_price = _as_float(txn.get("price"), default=np.nan)
        if close_date is None or not np.isfinite(close_price):
            continue
        if close_date > end_ts:
            continue
        if best_date is None or close_date > best_date:
            best_date = close_date
            best_source = str(txn.get("source") or "").strip().lower()
    return best_source

def _option_expiry_datetime(
    symbol: str,
    contract_identity: dict[str, Any] | None,
) -> Optional[datetime]:
    expiry_token: Any = None
    if isinstance(contract_identity, dict):
        expiry_token = contract_identity.get("expiry")

    if expiry_token in (None, ""):
        parsed = parse_option_contract_identity_from_symbol(symbol)
        if isinstance(parsed, dict):
            expiry_token = parsed.get("expiry")

    if expiry_token in (None, ""):
        return None

    if isinstance(expiry_token, datetime):
        return expiry_token.replace(tzinfo=None)

    token = str(expiry_token).strip()
    if not token:
        return None

    for fmt in ("%Y%m%d", "%y%m%d"):
        if token.isdigit() and len(token) == len(datetime.now().strftime(fmt)):
            try:
                return datetime.strptime(token, fmt)
            except ValueError:
                continue

    try:
        return pd.Timestamp(token).to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None

def _build_option_price_cache(
    option_price_rows: List[Dict[str, Any]],
) -> Dict[str, pd.Series]:
    """Convert flat option price rows into {ticker: pd.Series} for price_cache."""
    grouped: Dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in option_price_rows:
        ticker = str(row.get("ticker", "")).strip()
        date_str = str(row.get("date", "")).strip()
        price = row.get("price")
        if not ticker or not date_str or price is None:
            continue
        try:
            price_float = float(price)
        except (ValueError, TypeError):
            continue
        grouped[ticker].append((date_str, price_float))

    result: Dict[str, pd.Series] = {}
    for ticker, entries in grouped.items():
        dates = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in entries])
        values = [p for _, p in entries]
        series = pd.Series(values, index=dates, dtype=float, name=ticker)
        series = series.sort_index()
        series = series[~series.index.duplicated(keep="last")]
        result[ticker] = series
    return result

def _month_end_range(start: datetime, end: datetime) -> List[datetime]:
    """Build month-end date list for [start, end]."""
    # Normalize to calendar dates so month-end anchors do not inherit
    # provider event time-of-day (which can break benchmark alignment).
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    month_ends = [
        dt.to_pydatetime().replace(tzinfo=None)
        for dt in pd.date_range(start_ts, end_ts, freq="ME")
    ]
    if month_ends:
        return month_ends
    return [start_ts.to_period("M").to_timestamp("M").to_pydatetime().replace(tzinfo=None)]

def _business_day_range(start: datetime, end: datetime) -> List[datetime]:
    """Build business-day date list for [start, end]."""
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    business_days = [
        dt.to_pydatetime().replace(tzinfo=None)
        for dt in pd.bdate_range(start_ts, end_ts)
    ]
    if business_days:
        return business_days
    return [start_ts.to_pydatetime().replace(tzinfo=None)]

def _normalize_monthly_index(series: Optional[pd.Series]) -> pd.Series:
    """Normalize a monthly series index to canonical month-end midnight timestamps."""
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)

    out = series.copy()
    idx = pd.DatetimeIndex(pd.to_datetime(out.index))
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    normalized_idx = idx.to_period("M").to_timestamp("M")
    out.index = pd.DatetimeIndex(normalized_idx)
    out = out[~out.index.duplicated(keep="last")]
    return out.sort_index()

def _dict_to_series(values: Optional[Dict[str, Any]]) -> pd.Series:
    """Convert {date_str: value} payloads into sorted float series."""
    if not values:
        return pd.Series(dtype=float)

    if not isinstance(values, dict):
        return pd.Series(dtype=float)

    index_tokens: List[pd.Timestamp] = []
    output_values: List[float] = []
    for raw_key, raw_value in values.items():
        dt = pd.to_datetime(raw_key, errors="coerce")
        if pd.isna(dt):
            continue
        index_tokens.append(pd.Timestamp(dt))
        output_values.append(_as_float(raw_value, 0.0))

    if not index_tokens:
        return pd.Series(dtype=float)

    series = pd.Series(output_values, index=pd.DatetimeIndex(index_tokens), dtype=float)
    series = series.sort_index()
    return series[~series.index.duplicated(keep="last")]

def _series_to_dict(series: pd.Series) -> Dict[str, float]:
    normalized = _normalize_monthly_index(series)
    return {
        ts.date().isoformat(): float(_as_float(value, 0.0))
        for ts, value in normalized.items()
    }

def _flows_to_dict(flows: List[Tuple[datetime, float]]) -> Dict[str, float]:
    aggregated: Dict[str, float] = defaultdict(float)
    for when, amount in flows:
        dt = pd.to_datetime(when, errors="coerce")
        if pd.isna(dt):
            continue
        key = pd.Timestamp(dt).normalize().date().isoformat()
        aggregated[key] += _as_float(amount, 0.0)
    return dict(sorted((k, float(v)) for k, v in aggregated.items()))

def _dict_to_flow_list(values: Optional[Dict[str, Any]]) -> List[Tuple[datetime, float]]:
    if not values or not isinstance(values, dict):
        return []

    out: List[Tuple[datetime, float]] = []
    for raw_key, raw_value in values.items():
        dt = _to_datetime(raw_key)
        if dt is None:
            continue
        out.append((dt, _as_float(raw_value, 0.0)))
    out.sort(key=lambda row: row[0])
    return out

def _month_end_cash_series(
    cash_snapshots: List[Tuple[datetime, float]],
    month_end_index: pd.DatetimeIndex,
) -> pd.Series:
    """Project cash snapshots onto month-end timestamps using <= lookup."""
    idx = pd.DatetimeIndex(pd.to_datetime(month_end_index)).sort_values()
    if idx.empty:
        return pd.Series(dtype=float)
    if not cash_snapshots:
        return pd.Series(0.0, index=idx, dtype=float)

    cash_series = pd.Series(
        [_as_float(amount, 0.0) for _, amount in cash_snapshots],
        index=pd.DatetimeIndex([pd.Timestamp(ts) for ts, _ in cash_snapshots]),
        dtype=float,
    ).sort_index()

    return pd.Series(
        [_value_at_or_before(cash_series, ts, default=0.0) for ts in idx],
        index=idx,
        dtype=float,
    )



# Captured at package-import time via _capture_original_sentinels().
_ORIGINAL_GET_MONTHLY_FX_SERIES = None
_ORIGINAL_COMPUTE_MONTHLY_RETURNS = None


def _capture_original_sentinels(
    monthly_fx_series_fn,
    compute_monthly_returns_fn,
) -> None:
    """Capture function sentinels used to detect monkeypatched test overrides."""
    global _ORIGINAL_GET_MONTHLY_FX_SERIES
    global _ORIGINAL_COMPUTE_MONTHLY_RETURNS
    if _ORIGINAL_GET_MONTHLY_FX_SERIES is None:
        _ORIGINAL_GET_MONTHLY_FX_SERIES = monthly_fx_series_fn
    if _ORIGINAL_COMPUTE_MONTHLY_RETURNS is None:
        _ORIGINAL_COMPUTE_MONTHLY_RETURNS = compute_monthly_returns_fn


def _shim_attr(name: str, default: Any = None) -> Any:
    """Read a runtime override from core.realized_performance package if present."""
    rpa_mod = sys.modules.get("core.realized_performance")
    if rpa_mod is None:
        return default
    return getattr(rpa_mod, name, default)

__all__ = [
    '_ORIGINAL_FETCH_MONTHLY_CLOSE',
    '_ORIGINAL_GET_MONTHLY_FX_SERIES',
    '_ORIGINAL_COMPUTE_MONTHLY_RETURNS',
    'TYPE_ORDER',
    '_FX_PAIR_SYMBOL_RE',
    '_IBKR_ACCOUNT_ID_RE',
    'REALIZED_PROVIDER_ALIAS_MAP',
    '_is_fx_artifact_symbol',
    '_infer_instrument_type_from_transaction',
    '_infer_position_instrument_type',
    '_to_datetime',
    '_as_float',
    '_value_at_or_before',
    '_series_from_cache',
    '_option_fifo_terminal_series',
    '_option_expiry_datetime',
    '_build_option_price_cache',
    '_month_end_range',
    '_business_day_range',
    '_normalize_monthly_index',
    '_dict_to_series',
    '_series_to_dict',
    '_flows_to_dict',
    '_dict_to_flow_list',
    '_month_end_cash_series',
    '_capture_original_sentinels',
    '_shim_attr',
]
