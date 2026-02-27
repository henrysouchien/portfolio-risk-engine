"""Realized portfolio performance analysis pipeline.

Called by:
- ``services.portfolio_service.PortfolioService.analyze_realized_performance``.
- MCP/API wrappers that need realized-performance payloads.

Calls into:
- Transaction fetch/routing in ``trading_analysis.data_fetcher``.
- Provider-flow extraction in ``providers/flows``.
- FIFO normalization/matching in ``trading_analysis``.
- Shared metrics engine in ``core.performance_metrics_engine``.

Primary flow:
1. Build current holdings context and fetch source-scoped transactions.
2. Normalize transactions to FIFO + income events.
3. Reconcile provider-authoritative flows vs inferred fallback flows.
4. Build monthly NAV/return series and compute performance metrics.
5. Return ``RealizedPerformanceResult``-compatible payload.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from core.performance_metrics_engine import compute_performance_metrics
from factor_utils import calc_monthly_returns
from data_loader import fetch_monthly_close, fetch_monthly_treasury_rates
from fmp.fx import get_monthly_fx_series
from ibkr.compat import (
    fetch_ibkr_bond_monthly_close,
    fetch_ibkr_fx_monthly_close,
    fetch_ibkr_monthly_close,
    fetch_ibkr_option_monthly_mark,
    get_ibkr_futures_fmp_map,
)
from providers.fmp_price import FMPPriceProvider
from providers.flows.common import build_slice_key
from providers.flows.extractor import extract_provider_flow_events
from providers.ibkr_price import IBKRPriceProvider
from providers.interfaces import PriceSeriesProvider
from providers.normalizers.schwab import get_schwab_security_lookup
from providers.routing import get_canonical_provider, resolve_provider_token
from providers.registry import ProviderRegistry
from settings import (
    BACKFILL_FILE_PATH,
    DATA_QUALITY_THRESHOLDS,
    REALIZED_COVERAGE_TARGET,
    REALIZED_MAX_INCOMPLETE_TRADES,
    REALIZED_MAX_RECONCILIATION_GAP_PCT,
    REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE,
    REALIZED_PROVIDER_FLOW_SOURCES,
    REALIZED_USE_PROVIDER_FLOWS,
)
from trading_analysis.analyzer import TradingAnalyzer
from trading_analysis.data_fetcher import fetch_transactions_for_source, match_institution
from trading_analysis.fifo_matcher import FIFOMatcher, IncompleteTrade, OpenLot
from trading_analysis.instrument_meta import InstrumentMeta, coerce_instrument_type
from trading_analysis.symbol_utils import parse_option_contract_identity_from_symbol


TYPE_ORDER = {
    "SELL": 0,
    "SHORT": 1,
    "INCOME": 2,
    "PROVIDER_FLOW": 2,
    "BUY": 3,
    "COVER": 4,
}
_FX_PAIR_SYMBOL_RE = re.compile(r"^[A-Z]{3}\.[A-Z]{3}$")
_IBKR_ACCOUNT_ID_RE = re.compile(r"^u\d+$", re.IGNORECASE)
# Provider alias normalization used only by realized cash replay overlap dedupe.
# Keep synchronized with docs/planning/CASH_REPLAY_P2_FIX_PLAN.md.
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
        return coerce_instrument_type(explicit)

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


def _infer_position_instrument_type(position: Dict[str, Any]) -> str:
    """Infer instrument_type from current-position row fields."""
    explicit = position.get("instrument_type")
    if explicit:
        return coerce_instrument_type(explicit)

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


@dataclass
class PriceResult:
    series: pd.Series
    success_provider: str | None = None
    attempts: list[tuple[str, str, Exception | None]] = field(default_factory=list)


def _build_default_price_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register_price_provider(
        FMPPriceProvider(fetcher=fetch_monthly_close),
        priority=10,
    )
    registry.register_price_provider(
        IBKRPriceProvider(
            futures_fetcher=fetch_ibkr_monthly_close,
            fx_fetcher=fetch_ibkr_fx_monthly_close,
            bond_fetcher=fetch_ibkr_bond_monthly_close,
            option_fetcher=fetch_ibkr_option_monthly_mark,
        ),
        priority=20,
    )
    return registry


def _fetch_price_from_chain(
    providers: list[PriceSeriesProvider],
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    *,
    instrument_type: str,
    contract_identity: dict[str, Any] | None,
    fmp_ticker_map: dict[str, str] | None,
) -> PriceResult:
    result = PriceResult(series=pd.Series(dtype=float))
    for provider in providers:
        if (
            instrument_type == "option"
            and provider.provider_name == "ibkr"
            and not (isinstance(contract_identity, dict) and contract_identity)
        ):
            result.attempts.append((provider.provider_name, "skipped_missing_contract_identity", None))
            continue

        try:
            series = provider.fetch_monthly_close(
                symbol,
                start_date,
                end_date,
                instrument_type=instrument_type,
                contract_identity=contract_identity,
                fmp_ticker_map=fmp_ticker_map,
            )
            if not isinstance(series, pd.Series):
                series = pd.Series(dtype=float)
            normalized = _series_from_cache(series)
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


def _build_current_positions(
    positions: "PositionResult",
    institution: Optional[str] = None,
    account: Optional[str] = None,
    rows_override: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], List[str]]:
    """Build ticker->position map and fmp_ticker map from PositionResult."""
    current_positions: Dict[str, Dict[str, Any]] = {}
    fmp_ticker_map: Dict[str, str] = {}
    warnings: List[str] = []
    filtered_positions = 0
    missing_brokerage_name = 0
    account_filtered_positions = 0

    rows = rows_override if rows_override is not None else list(getattr(positions.data, "positions", []) or [])
    for pos in rows:
        if institution:
            brokerage_name = str(pos.get("brokerage_name") or "")
            if not match_institution(brokerage_name, institution):
                filtered_positions += 1
                if not brokerage_name.strip():
                    missing_brokerage_name += 1
                continue
        if account and not _match_account(pos, account):
            account_filtered_positions += 1
            continue

        ticker = pos.get("ticker")
        if not ticker or not isinstance(ticker, str):
            continue
        if pos.get("type") == "cash" or ticker.startswith("CUR:"):
            continue

        quantity = _as_float(pos.get("quantity"), 0.0)
        if abs(quantity) < 1e-9:
            continue

        currency = pos.get("original_currency") or pos.get("currency") or "USD"
        has_cost_basis_usd = pos.get("cost_basis_usd") is not None
        cost_basis = pos.get("cost_basis_usd")
        if cost_basis is None:
            cost_basis = pos.get("cost_basis")
        cost_basis_is_usd = has_cost_basis_usd or str(currency).upper() == "USD"
        instrument_type = _infer_position_instrument_type(pos)

        if ticker in current_positions:
            existing_currency = current_positions[ticker].get("currency")
            if existing_currency != currency:
                warnings.append(
                    f"Mixed currencies in current positions for {ticker} ({existing_currency} vs {currency}); using first currency."
                )
                continue
            current_positions[ticker]["shares"] += quantity
            current_positions[ticker]["value"] += _as_float(pos.get("value"), 0.0)
            if cost_basis is not None:
                current_positions[ticker]["cost_basis"] = _as_float(
                    current_positions[ticker].get("cost_basis"), 0.0
                ) + _as_float(cost_basis, 0.0)
            if current_positions[ticker].get("cost_basis_is_usd") != cost_basis_is_usd:
                warnings.append(
                    f"Mixed cost_basis provenance in current positions for {ticker}; using first provenance."
                )
            if current_positions[ticker].get("instrument_type") != instrument_type:
                warnings.append(
                    f"Mixed instrument_type in current positions for {ticker} "
                    f"({current_positions[ticker].get('instrument_type')} vs {instrument_type}); "
                    "using first instrument_type."
                )
        else:
            current_positions[ticker] = {
                "shares": quantity,
                "currency": str(currency),
                "cost_basis": None if cost_basis is None else _as_float(cost_basis, 0.0),
                "cost_basis_is_usd": cost_basis_is_usd,
                "value": _as_float(pos.get("value"), 0.0),
                "instrument_type": instrument_type,
            }

        fmp_ticker = pos.get("fmp_ticker")
        if isinstance(fmp_ticker, str) and fmp_ticker.strip() and ticker not in fmp_ticker_map:
            fmp_ticker_map[ticker] = fmp_ticker.strip()

    if institution and filtered_positions:
        warnings.append(
            f"Institution filter '{institution}': excluded {filtered_positions} position row(s)"
            f" ({missing_brokerage_name} missing brokerage_name)."
        )
    if account and account_filtered_positions:
        warnings.append(
            f"Account filter '{account}': excluded {account_filtered_positions} position row(s)."
        )

    return current_positions, fmp_ticker_map, warnings


@dataclass
class SourceScopedHoldings:
    current_positions: Dict[str, Dict[str, Any]]
    fmp_ticker_map: Dict[str, str]
    source_holding_symbols: List[str]
    source_holding_count: int
    cross_source_holding_leakage_symbols: List[str]
    holdings_scope: str = "source_scoped"


def _normalize_source_token(value: Any) -> Optional[str]:
    return resolve_provider_token(str(value or ""))


def _match_account(row: Dict[str, Any], account_filter: Optional[str]) -> bool:
    """Match account filter against account_id or account_name (exact, case-insensitive)."""
    normalized_filter = str(account_filter or "").strip().lower()
    if not normalized_filter:
        return True
    account_id = str(row.get("account_id") or "").strip().lower()
    account_name = str(row.get("account_name") or "").strip().lower()
    return normalized_filter in {account_id, account_name}


def _is_ibkr_identity_field(field_name: str, normalized_value: str) -> bool:
    if "interactive brokers" in normalized_value or "ibkr" in normalized_value:
        return True
    if field_name == "account_id" and bool(_IBKR_ACCOUNT_ID_RE.match(normalized_value.replace(" ", ""))):
        return True
    return False


def _provider_matches_from_position_row(
    pos: Dict[str, Any],
) -> Tuple[set[str], str]:
    primary_matches: set[str] = set()
    secondary_matches: set[str] = set()
    tertiary_matches: set[str] = set()

    for field_name in ("account_id", "account_name", "brokerage_name", "institution"):
        value = str(pos.get(field_name) or "").strip()
        if not value:
            continue
        normalized = " ".join(value.lower().replace("_", " ").replace("-", " ").split())

        mapped = _normalize_source_token(normalized)
        if mapped:
            primary_matches.add(mapped)

        canonical = get_canonical_provider(value, data_type="transactions")
        canonical_mapped = _normalize_source_token(canonical)
        if canonical_mapped:
            primary_matches.add(canonical_mapped)

        if _is_ibkr_identity_field(field_name, normalized):
            primary_matches.add("ibkr_flex")

    raw_source = str(pos.get("position_source") or "").strip().lower()
    if raw_source:
        for token in [tok.strip() for tok in raw_source.split(",") if tok.strip()]:
            mapped = _normalize_source_token(token)
            if mapped:
                secondary_matches.add(mapped)

    brokerage_candidates = [
        str(pos.get("brokerage_name") or "").strip(),
        str(pos.get("institution") or "").strip(),
    ]
    for brokerage_name in brokerage_candidates:
        if not brokerage_name:
            continue
        if match_institution(brokerage_name, "ibkr"):
            tertiary_matches.add("ibkr_flex")
        if match_institution(brokerage_name, "schwab"):
            tertiary_matches.add("schwab")

    if primary_matches:
        return primary_matches, "primary"
    if secondary_matches:
        # Prefer native broker APIs over aggregator mirrors when both appear.
        native_sources = {"schwab", "ibkr_flex"}
        aggregator_sources = {"plaid", "snaptrade"}
        native_in = secondary_matches & native_sources
        aggregator_in = secondary_matches & aggregator_sources
        if native_in and aggregator_in:
            secondary_matches = native_in
        return secondary_matches, "secondary"
    if tertiary_matches:
        return tertiary_matches, "tertiary"
    return set(), "none"


def _build_source_scoped_holdings(
    positions: "PositionResult",
    source: str,
    warnings: List[str],
    institution: Optional[str] = None,
    account: Optional[str] = None,
) -> SourceScopedHoldings:
    """Build source-scoped holdings with deterministic attribution and leakage diagnostics."""
    if source == "all":
        return SourceScopedHoldings(
            current_positions={},
            fmp_ticker_map={},
            source_holding_symbols=[],
            source_holding_count=0,
            cross_source_holding_leakage_symbols=[],
            holdings_scope="consolidated",
        )

    candidate_rows: List[Dict[str, Any]] = []
    symbol_to_sources: Dict[str, set[str]] = defaultdict(set)
    row_level_ambiguous_symbols: set[str] = set()
    institution_filtered_rows = 0
    institution_missing_brokerage_name = 0
    account_filtered_rows = 0

    for pos in list(getattr(getattr(positions, "data", None), "positions", []) or []):
        if institution:
            brokerage_name = str(pos.get("brokerage_name") or pos.get("institution") or "")
            if not match_institution(brokerage_name, institution):
                institution_filtered_rows += 1
                if not brokerage_name.strip():
                    institution_missing_brokerage_name += 1
                continue
        if account and not _match_account(pos, account):
            account_filtered_rows += 1
            continue

        ticker = pos.get("ticker")
        if not ticker or not isinstance(ticker, str):
            continue
        if pos.get("type") == "cash" or ticker.startswith("CUR:"):
            continue

        quantity = _as_float(pos.get("quantity"), 0.0)
        if abs(quantity) < 1e-9:
            continue

        matches, _match_basis = _provider_matches_from_position_row(pos)
        symbol = ticker.strip()
        sources_for_symbol = set(matches)
        raw_source = str(pos.get("position_source") or "").strip().lower()
        if raw_source:
            for token in [tok.strip() for tok in raw_source.split(",") if tok.strip()]:
                mapped = _normalize_source_token(token)
                if mapped:
                    sources_for_symbol.add(mapped)
                else:
                    collapsed = " ".join(token.replace("_", " ").replace("-", " ").split())
                    if collapsed:
                        sources_for_symbol.add(collapsed)
        if not sources_for_symbol:
            continue
        symbol_to_sources[symbol].update(sources_for_symbol)
        if len(matches) > 1 and source in matches:
            row_level_ambiguous_symbols.add(symbol)

        if source in matches:
            candidate_rows.append(pos)

    _NATIVE_SOURCES = {"schwab", "ibkr_flex"}
    _AGGREGATOR_SOURCES = {"plaid", "snaptrade"}

    symbol_level_leakage = set()
    for symbol, sources in symbol_to_sources.items():
        if source not in sources or len(sources) <= 1:
            continue
        native_in = sources & _NATIVE_SOURCES
        aggregator_in = sources & _AGGREGATOR_SOURCES
        unknown_sources = sources - _NATIVE_SOURCES - _AGGREGATOR_SOURCES
        if (
            native_in
            and aggregator_in
            and len(native_in) == 1
            and not unknown_sources
            and source in native_in
        ):
            continue
        symbol_level_leakage.add(symbol)
    cross_source_leakage_symbols = sorted(symbol_level_leakage | row_level_ambiguous_symbols)

    if cross_source_leakage_symbols:
        preview = ", ".join(cross_source_leakage_symbols[:5])
        if len(cross_source_leakage_symbols) > 5:
            preview = f"{preview}, ..."
        warnings.append(
            f"Excluded {len(cross_source_leakage_symbols)} cross-source holding symbol(s) from {source} "
            f"strict holdings scope ({preview}); attribution remained ambiguous after precedence checks."
        )
    if institution and institution_filtered_rows:
        warnings.append(
            f"Institution filter '{institution}': excluded {institution_filtered_rows} source-scoped position row(s)"
            f" ({institution_missing_brokerage_name} missing brokerage/institution)."
        )
    if account and account_filtered_rows:
        warnings.append(
            f"Account filter '{account}': excluded {account_filtered_rows} source-scoped position row(s)."
        )

    strict_rows = [
        row for row in candidate_rows
        if str(row.get("ticker") or "").strip() not in set(cross_source_leakage_symbols)
    ]
    scoped_positions, scoped_fmp_map, scoped_warnings = _build_current_positions(
        positions,
        institution=None,
        rows_override=strict_rows,
    )
    warnings.extend(scoped_warnings)
    symbols = sorted(scoped_positions.keys())
    return SourceScopedHoldings(
        current_positions=scoped_positions,
        fmp_ticker_map=scoped_fmp_map,
        source_holding_symbols=symbols,
        source_holding_count=len(symbols),
        cross_source_holding_leakage_symbols=cross_source_leakage_symbols,
        holdings_scope="source_scoped",
    )


def _event_fx_rate(currency: str, when: datetime, fx_cache: Dict[str, pd.Series]) -> float:
    """Get FX currency->USD rate for event timestamp."""
    ccy = (currency or "USD").upper()
    if ccy == "USD":
        return 1.0
    return _value_at_or_before(fx_cache.get(ccy), when, default=1.0)


def _build_fx_cache(
    *,
    currencies: Iterable[str],
    inception_date: datetime,
    end_date: datetime,
    warnings: List[str],
) -> Dict[str, pd.Series]:
    """Fetch and normalize monthly FX series for requested currencies."""
    fx_cache: Dict[str, pd.Series] = {}
    for ccy in sorted({str(c or "USD").upper() for c in currencies}):
        try:
            fx_cache[ccy] = _series_from_cache(
                get_monthly_fx_series(ccy, inception_date, end_date)
            )
        except Exception as exc:
            warnings.append(f"FX series fetch failed for {ccy}: {exc}; using 1.0 fallback.")
            fx_cache[ccy] = pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp(inception_date)]))
    return fx_cache


def _synthetic_price_hint_from_position(
    *,
    shares: float,
    currency: str,
    position_row: Dict[str, Any],
) -> float:
    """Infer a fallback local-currency price hint for synthetic cash events.

    Prefer broker cost basis per share for USD positions. If unavailable, use
    current market value per share for USD positions. For non-USD positions we
    avoid deriving hints from potentially USD-denominated fields.
    """
    qty = abs(_as_float(shares, 0.0))
    if qty <= 1e-9:
        return 0.0

    ccy = str(currency or "USD").upper()
    cost_basis = _as_float(position_row.get("cost_basis"), 0.0)
    cost_basis_is_usd = bool(position_row.get("cost_basis_is_usd", ccy == "USD"))
    if ccy == "USD" and cost_basis > 0 and cost_basis_is_usd:
        return cost_basis / qty

    value = _as_float(position_row.get("value"), 0.0)
    if ccy == "USD" and value > 0:
        return value / qty

    return 0.0


def _detect_first_exit_without_opening(
    fifo_transactions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Detect symbols whose first transaction date contains exits but no openings."""
    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    opening_type_by_direction = {
        "LONG": {"BUY"},
        "SHORT": {"SHORT"},
    }
    exit_type_by_direction = {
        "LONG": {"SELL"},
        "SHORT": {"COVER"},
    }

    for txn in fifo_transactions:
        symbol = str(txn.get("symbol") or "").strip()
        if not symbol:
            continue
        date = _to_datetime(txn.get("date"))
        if date is None:
            continue
        txn_type = str(txn.get("type") or "").upper()
        if txn_type in {"BUY", "SELL"}:
            direction = "LONG"
        elif txn_type in {"SHORT", "COVER"}:
            direction = "SHORT"
        else:
            continue

        currency = str(txn.get("currency") or "USD").upper()
        grouped[(symbol, currency, direction)].append(
            {
                "date": date,
                "type": txn_type,
                "source": str(txn.get("source") or "unknown"),
                "quantity": abs(_as_float(txn.get("quantity"), 0.0)),
            }
        )

    flags: List[Dict[str, Any]] = []
    for (symbol, currency, direction), events in grouped.items():
        earliest_date = min(e["date"] for e in events).date()
        earliest_events = [e for e in events if e["date"].date() == earliest_date]
        has_opening = any(
            str(e.get("type") or "").upper() in opening_type_by_direction[direction]
            for e in earliest_events
        )
        has_exit = any(
            str(e.get("type") or "").upper() in exit_type_by_direction[direction]
            for e in earliest_events
        )
        if not has_exit or has_opening:
            continue

        first_exit = next(
            e for e in sorted(earliest_events, key=lambda item: TYPE_ORDER.get(str(item.get("type") or ""), 99))
            if str(e.get("type") or "").upper() in exit_type_by_direction[direction]
        )
        flags.append(
            {
                "symbol": symbol,
                "currency": currency,
                "direction": direction,
                "first_date": earliest_date.isoformat(),
                "first_type": str(first_exit.get("type") or "").upper(),
                "source": str(first_exit.get("source") or "unknown"),
                "quantity": float(_as_float(first_exit.get("quantity"), 0.0)),
            }
        )

    flags.sort(key=lambda item: (item["symbol"], item["currency"], item["direction"]))
    return flags


def _build_seed_open_lots(
    fifo_transactions: List[Dict[str, Any]],
    current_positions: Dict[str, Dict[str, Any]],
    observed_open_lots: Dict[Tuple[str, str, str], List[OpenLot]],
    inception_date: datetime,
    fx_cache: Optional[Dict[str, pd.Series]] = None,
) -> Tuple[Dict[Tuple[str, str, str], List[OpenLot]], List[str]]:
    """Compute pre-seeded open lots from broker cost basis for two-pass FIFO.

    For each current LONG position with missing buy history, back-solve the
    cost per share for the pre-window portion using:
        seed_price = (broker_cost - observed_lot_cost) / pre_window_shares

    Args:
        fifo_transactions: All normalized FIFO transactions.
        current_positions: ticker -> {shares, currency, cost_basis, cost_basis_is_usd, ...}
        observed_open_lots: Open lots from pass-1 FIFO (keyed by (sym, ccy, dir)).
        inception_date: Global inception date (fallback for zero-history symbols).
        fx_cache: FX rate series for currency alignment.

    Returns:
        (seeded_lots_dict, warnings) where seeded_lots_dict is keyed by
        (symbol, currency, "LONG") and each value is a list containing one OpenLot.
    """
    import logging
    logger = logging.getLogger("performance")

    seeded: Dict[Tuple[str, str, str], List[OpenLot]] = {}
    seed_warnings: List[str] = []

    # Build per-symbol earliest txn date (same logic as build_position_timeline)
    earliest_txn_by_symbol: Dict[str, datetime] = {}
    for txn in fifo_transactions:
        sym = str(txn.get("symbol", "")).strip()
        dt = _to_datetime(txn.get("date"))
        if sym and dt:
            if sym not in earliest_txn_by_symbol or dt < earliest_txn_by_symbol[sym]:
                earliest_txn_by_symbol[sym] = dt

    # Pre-compute in-window openings and exits per (symbol, currency, LONG)
    in_window_openings: Dict[str, float] = defaultdict(float)
    in_window_exits: Dict[str, float] = defaultdict(float)
    for txn in fifo_transactions:
        sym = str(txn.get("symbol", "")).strip()
        txn_type = str(txn.get("type", "")).upper()
        qty = abs(_as_float(txn.get("quantity"), 0.0))
        if txn_type == "BUY":
            in_window_openings[sym] += qty
        elif txn_type == "SELL":
            in_window_exits[sym] += qty

    for ticker, pos in current_positions.items():
        shares = _as_float(pos.get("shares"), 0.0)
        if shares <= 0:
            # Only seed LONG positions (per plan: scope to LONG only)
            continue

        broker_cost = _as_float(pos.get("cost_basis"), 0.0)
        if broker_cost <= 0:
            # No usable broker cost basis — skip seeding, will use FMP fallback for NAV
            continue

        currency = str(pos.get("currency") or "USD").upper()
        cost_is_usd = pos.get("cost_basis_is_usd", currency == "USD")
        lot_key = (ticker, currency, "LONG")

        # Observed open lots from pass 1
        obs_lots = observed_open_lots.get(lot_key, [])
        obs_shares = sum(lot.remaining_quantity for lot in obs_lots)
        obs_cost = sum(
            lot.remaining_quantity * lot.entry_price + lot.remaining_entry_fee
            for lot in obs_lots
        )

        # If cost_basis is in USD but lots are in local currency, convert lot cost to USD
        if cost_is_usd and currency != "USD" and fx_cache:
            # Use latest available FX rate for conversion
            fx_rate = _value_at_or_before(
                fx_cache.get(currency),
                datetime.now().replace(tzinfo=None),
                default=1.0,
            )
            obs_cost_usd = obs_cost * fx_rate
        else:
            obs_cost_usd = obs_cost

        # Seed only the gap between current holdings and observed pass-1 open lots.
        # This avoids over-seeding in sell-then-rebuy patterns where pre-window
        # shares were already fully closed within the observed window.
        pre_window_shares_by_gap = max(0.0, shares - obs_shares)
        pre_window_shares_by_delta = shares + in_window_exits.get(ticker, 0.0) - in_window_openings.get(ticker, 0.0)

        if pre_window_shares_by_gap <= 0.01:
            if pre_window_shares_by_delta > 0.01:
                seed_warnings.append(
                    f"Seed skip {ticker}: observed open lots already cover current shares "
                    f"(current={shares:.4f}, observed_open={obs_shares:.4f}, delta_pre_window={pre_window_shares_by_delta:.4f}). "
                    "Likely sell-then-rebuy pattern; treating earlier sells as incomplete history."
                )
            # All shares explained by in-window buys — no seeding needed
            continue

        pre_window_cost = broker_cost - obs_cost_usd
        if pre_window_cost <= 0:
            seed_warnings.append(
                f"Seed skip {ticker}: broker cost ${broker_cost:.2f} < observed lot cost ${obs_cost_usd:.2f}; "
                "data inconsistency."
            )
            continue

        seed_price = pre_window_cost / pre_window_shares_by_gap

        # If seed price is in USD but we need local-currency lot price, convert back
        if cost_is_usd and currency != "USD" and fx_cache:
            fx_rate = _value_at_or_before(
                fx_cache.get(currency),
                datetime.now().replace(tzinfo=None),
                default=1.0,
            )
            if fx_rate > 0:
                seed_price = seed_price / fx_rate

        # Place seeded lot at symbol's earliest txn - 1s (or global inception - 1s)
        symbol_inception = earliest_txn_by_symbol.get(ticker, inception_date)
        seed_date = symbol_inception - timedelta(seconds=1)

        seed_lot = OpenLot(
            symbol=ticker,
            entry_date=seed_date,
            entry_price=seed_price,
            original_quantity=pre_window_shares_by_gap,
            remaining_quantity=pre_window_shares_by_gap,
            entry_fee=0.0,
            source="seed_back_solved",
            currency=currency,
            direction="LONG",
        )

        seeded[lot_key] = [seed_lot]
        logger.debug(
            "Seeded %s: %.2f shares @ $%.4f (broker_cost=$%.2f, obs_cost=$%.2f)",
            ticker, pre_window_shares_by_gap, seed_price, broker_cost, obs_cost_usd,
        )

    return seeded, seed_warnings


def build_position_timeline(
    fifo_transactions: List[Dict[str, Any]],
    current_positions: Dict[str, Dict[str, Any]],
    inception_date: datetime,
    incomplete_trades: List[IncompleteTrade],
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[Tuple[str, str, str], List[Tuple[datetime, float]]],
    List[Dict[str, str]],
    List[Dict[str, Any]],
    Dict[Tuple[str, str, str], InstrumentMeta],
    List[str],
]:
    """Walk transactions forward to reconstruct quantities by (ticker, currency, direction)."""
    del fmp_ticker_map  # Reserved for future use.

    position_events: Dict[Tuple[str, str, str], List[Tuple[datetime, float]]] = defaultdict(list)
    synthetic_positions: List[Dict[str, str]] = []
    synthetic_entries: List[Dict[str, Any]] = []
    instrument_meta: Dict[Tuple[str, str, str], InstrumentMeta] = {}
    warnings: List[str] = []

    opening_qty: Dict[Tuple[str, str, str], float] = defaultdict(float)
    exit_qty: Dict[Tuple[str, str, str], float] = defaultdict(float)
    filtered_keys: set[Tuple[str, str, str]] = set()
    filtered_warning_keys: set[Tuple[str, str, str, str]] = set()
    conflict_warning_keys: set[Tuple[Tuple[str, str, str], str, str]] = set()

    def _register_instrument_meta(
        key: Tuple[str, str, str],
        raw_instrument_type: Any,
        raw_contract_identity: Any,
    ) -> None:
        normalized_instrument_type = coerce_instrument_type(raw_instrument_type)
        contract_identity = raw_contract_identity if isinstance(raw_contract_identity, dict) else None
        existing = instrument_meta.get(key)
        if existing is None:
            instrument_meta[key] = {
                "instrument_type": normalized_instrument_type,
                "contract_identity": contract_identity,
            }
            return

        existing_type = coerce_instrument_type(existing.get("instrument_type"))
        if existing_type != normalized_instrument_type:
            warn_key = (key, existing_type, normalized_instrument_type)
            if warn_key not in conflict_warning_keys:
                warnings.append(
                    "Instrument type conflict for "
                    f"{key[0]} ({key[1]}, {key[2]}): "
                    f"kept {existing_type}, ignored {normalized_instrument_type}."
                )
                conflict_warning_keys.add(warn_key)
            return

        if existing.get("contract_identity") is None and contract_identity is not None:
            existing["contract_identity"] = contract_identity

    for txn in fifo_transactions:
        date = _to_datetime(txn.get("date"))
        if date is None:
            continue

        symbol = str(txn.get("symbol", "")).strip()
        if not symbol:
            continue
        currency = str(txn.get("currency") or "USD").upper()
        txn_type = str(txn.get("type", "")).upper()
        qty = abs(_as_float(txn.get("quantity"), 0.0))
        if qty <= 0:
            continue
        instrument_type = _infer_instrument_type_from_transaction(txn)
        contract_identity = txn.get("contract_identity")

        if txn_type == "BUY":
            key = (symbol, currency, "LONG")
        elif txn_type == "SELL":
            key = (symbol, currency, "LONG")
        elif txn_type == "SHORT":
            key = (symbol, currency, "SHORT")
        elif txn_type == "COVER":
            key = (symbol, currency, "SHORT")
        else:
            continue

        if instrument_type in {"fx_artifact", "unknown"}:
            filtered_keys.add(key)
            warn_key = (key[0], key[1], key[2], instrument_type)
            if warn_key not in filtered_warning_keys:
                warnings.append(
                    f"Filtered {symbol} ({currency}, {key[2]}) from timeline: instrument_type={instrument_type}."
                )
                filtered_warning_keys.add(warn_key)
            continue

        _register_instrument_meta(key, instrument_type, contract_identity)

        if txn_type in {"BUY", "SHORT"}:
            position_events[key].append((date, qty))
            opening_qty[key] += qty
        else:
            position_events[key].append((date, -qty))
            exit_qty[key] += qty

    # Per-symbol earliest transaction date for more accurate synthetic placement.
    # Keyed by symbol (not symbol+direction) — conservative: uses earliest across
    # all directions for the rare case of long+short on same symbol.
    earliest_txn_by_symbol: Dict[str, datetime] = {}
    for txn in fifo_transactions:
        sym = str(txn.get("symbol", "")).strip()
        dt = _to_datetime(txn.get("date"))
        if sym and dt:
            if sym not in earliest_txn_by_symbol or dt < earliest_txn_by_symbol[sym]:
                earliest_txn_by_symbol[sym] = dt

    synthetic_keys: set[Tuple[str, str, str]] = set()
    synthetic_qty_by_key: Dict[Tuple[str, str, str], float] = defaultdict(float)
    current_position_synthetic_keys: set[Tuple[str, str, str]] = set()
    filtered_futures_incomplete_keys: set[Tuple[str, str, str]] = set()

    # Synthetic starts for current positions with missing or partial opening history.
    for ticker, pos in current_positions.items():
        shares = _as_float(pos.get("shares"), 0.0)
        if abs(shares) < 1e-9:
            continue

        currency = str(pos.get("currency") or "USD").upper()
        direction = "SHORT" if shares < 0 else "LONG"
        key = (ticker, currency, direction)
        instrument_type = coerce_instrument_type(pos.get("instrument_type"), default="equity")

        if instrument_type in {"fx_artifact", "unknown"}:
            warn_key = (key[0], key[1], key[2], instrument_type)
            if warn_key not in filtered_warning_keys:
                warnings.append(
                    f"Filtered {ticker} ({currency}, {direction}) from timeline: instrument_type={instrument_type}."
                )
                filtered_warning_keys.add(warn_key)
            filtered_keys.add(key)
            continue

        _register_instrument_meta(key, instrument_type, None)

        required_entry_qty = abs(shares) + exit_qty.get(key, 0.0)
        known_openings = opening_qty.get(key, 0.0)
        missing_openings = required_entry_qty - known_openings

        if missing_openings > 1e-6:
            # Use global inception for all synthetic positions so they appear
            # as pre-existing capital in V_start (avoids mid-period NAV jumps).
            # Offset by -1s so synthetic entry sorts before any real txn at that timestamp.
            symbol_inception = inception_date
            synthetic_date = symbol_inception - timedelta(seconds=1)
            price_hint = _synthetic_price_hint_from_position(
                shares=shares,
                currency=currency,
                position_row=pos,
            )
            estimated_current_value_usd = abs(_as_float(pos.get("value"), 0.0))

            position_events[key].append((synthetic_date, missing_openings))
            synthetic_keys.add(key)
            synthetic_qty_by_key[key] += missing_openings
            current_position_synthetic_keys.add(key)
            synthetic_entries.append(
                {
                    "ticker": ticker,
                    "currency": currency,
                    "direction": direction,
                    "date": synthetic_date,
                    "quantity": missing_openings,
                    "source": "synthetic_current_position",
                    "price_hint": price_hint if price_hint > 0 else None,
                    "estimated_current_value_usd": estimated_current_value_usd,
                    "instrument_type": instrument_type,
                }
            )

    # Synthetic starts for FIFO incomplete exits just before trade date.
    for incomplete in incomplete_trades:
        symbol = str(incomplete.symbol)
        currency = str(incomplete.currency or "USD").upper()
        direction = str(incomplete.direction or "LONG").upper()
        qty = abs(_as_float(incomplete.quantity, 0.0))
        sell_date = _to_datetime(incomplete.sell_date)

        if not symbol or qty <= 0 or sell_date is None:
            warnings.append("Skipped malformed incomplete trade during synthetic reconstruction.")
            continue

        # Place incomplete-trade synthetic at global inception (not sell_date - 1s)
        # so the position has month-end value from day one.  When the SELL lands,
        # it converts position value → cash; Modified Dietz sees a roughly neutral
        # transfer instead of phantom cash appearing from nowhere.
        synthetic_date = inception_date - timedelta(seconds=1)
        key = (symbol, currency, direction)
        if key in filtered_keys:
            continue

        meta = instrument_meta.get(key)
        instrument_type = coerce_instrument_type(
            (meta or {}).get("instrument_type"),
            default="equity",
        )
        if instrument_type in {"fx_artifact", "unknown"}:
            warn_key = (key[0], key[1], key[2], instrument_type)
            if warn_key not in filtered_warning_keys:
                warnings.append(
                    f"Filtered {symbol} ({currency}, {direction}) from timeline: instrument_type={instrument_type}."
                )
                filtered_warning_keys.add(warn_key)
            filtered_keys.add(key)
            continue

        if instrument_type == "futures":
            warn_key = (key[0], key[1], key[2], "futures_incomplete")
            if warn_key not in filtered_warning_keys:
                warnings.append(
                    f"Filtered futures incomplete trade {symbol} ({currency}, {direction}) "
                    f"from position timeline: futures P&L captured via cash replay fees, "
                    f"not synthetic position value."
                )
                filtered_warning_keys.add(warn_key)
            filtered_keys.add(key)
            filtered_futures_incomplete_keys.add(key)
            continue

        _register_instrument_meta(key, instrument_type, (meta or {}).get("contract_identity"))

        if key in current_position_synthetic_keys and synthetic_qty_by_key.get(key, 0.0) > 1e-9:
            continue

        position_events[key].append((synthetic_date, qty))
        synthetic_keys.add(key)
        synthetic_qty_by_key[key] += qty
        synthetic_entries.append(
            {
                "ticker": symbol,
                "currency": currency,
                "direction": direction,
                "date": synthetic_date,
                "quantity": qty,
                "source": "synthetic_incomplete_trade",
                "price_hint": _as_float(getattr(incomplete, "sell_price", 0.0), 0.0),
                "instrument_type": instrument_type,
            }
        )

    # For filtered futures incomplete trades, add compensating position events
    # to balance the unmatched SELL/COVER that's already in position_events.
    for _inc in incomplete_trades:
        _inc_sym = str(getattr(_inc, "symbol", "")).strip()
        _inc_ccy = str(getattr(_inc, "currency", "USD")).upper()
        _inc_dir = str(getattr(_inc, "direction", "LONG")).upper()
        _inc_key = (_inc_sym, _inc_ccy, _inc_dir)

        if _inc_key not in filtered_futures_incomplete_keys:
            continue
        if _inc_key in current_position_synthetic_keys:
            continue
        if _inc_key not in position_events:
            continue

        _inc_qty = abs(_as_float(getattr(_inc, "quantity", 0), 0.0))
        _inc_sell_date = _to_datetime(getattr(_inc, "sell_date", None))
        if _inc_qty <= 0 or _inc_sell_date is None:
            continue

        _compensating_date = _inc_sell_date - timedelta(seconds=1)
        position_events[_inc_key].append((_compensating_date, _inc_qty))

    for key, events in position_events.items():
        events.sort(key=lambda x: x[0])

    for ticker, currency, direction in sorted(synthetic_keys):
        synthetic_positions.append(
            {
                "ticker": ticker,
                "currency": currency,
                "direction": direction,
            }
        )

    return dict(position_events), synthetic_positions, synthetic_entries, instrument_meta, warnings


def _create_synthetic_cash_events(
    synthetic_entries: List[Dict[str, Any]],
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
    min_notional_usd: float = 1.0,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Create pseudo BUY/SHORT transactions so synthetic positions also fund cash."""
    del fx_cache  # Reserved for future currency-specific refinements.

    pseudo_transactions: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for entry in synthetic_entries:
        ticker = str(entry.get("ticker") or "").strip()
        currency = str(entry.get("currency") or "USD").upper()
        direction = str(entry.get("direction") or "LONG").upper()
        source = str(entry.get("source") or "")
        date = _to_datetime(entry.get("date"))
        quantity = abs(_as_float(entry.get("quantity"), 0.0))
        estimated_current_value_usd = abs(_as_float(entry.get("estimated_current_value_usd"), 0.0))

        if not ticker or date is None or quantity <= 0:
            warnings.append("Skipped malformed synthetic entry while creating synthetic cash events.")
            continue

        price = 0.0
        if source == "synthetic_incomplete_trade":
            price = _as_float(entry.get("price_hint"), 0.0)
        else:
            # Strict backward-only lookup: only allow prices on or before entry date.
            series = _series_from_cache(price_cache.get(ticker))
            prior = series[series.index <= pd.Timestamp(date)]
            if not prior.empty:
                price = _as_float(prior.iloc[-1], 0.0)

        if price <= 0:
            fallback_price_hint = _as_float(entry.get("price_hint"), 0.0)
            if fallback_price_hint > 0:
                price = fallback_price_hint
                warnings.append(
                    f"Used synthetic price hint for {ticker} ({direction}) on {date.date().isoformat()} "
                    f"because no historical price was available."
                )
            elif (
                source == "synthetic_current_position"
                and estimated_current_value_usd > 0
                and estimated_current_value_usd <= max(min_notional_usd, 0.0)
            ):
                warnings.append(
                    f"Skipped low-notional synthetic cash event for {ticker} ({direction}) on "
                    f"{date.date().isoformat()} (estimated value ${estimated_current_value_usd:.2f} <= "
                    f"${max(min_notional_usd, 0.0):.2f})."
                )
                continue

        if price <= 0:
            warnings.append(
                f"Skipped synthetic cash event for {ticker} ({direction}) on {date.date().isoformat()}: "
                "no valid non-zero price found."
            )
            continue

        pseudo_transactions.append(
            {
                "type": "SHORT" if direction == "SHORT" else "BUY",
                "symbol": ticker,
                "date": date,
                "quantity": quantity,
                "price": price,
                "fee": 0.0,
                "currency": currency,
                "source": "synthetic_cash_event",
            }
        )

    return pseudo_transactions, warnings


def derive_cash_and_external_flows(
    fifo_transactions: List[Dict[str, Any]],
    income_with_currency: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
    provider_flow_events: Optional[List[Dict[str, Any]]] = None,
    *,
    disable_inference_when_provider_mode: bool = True,
    force_disable_inference: bool = False,
    warnings: Optional[List[str]] = None,
    replay_diagnostics: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Tuple[datetime, float]], List[Tuple[datetime, float]]]:
    """Replay trades+income stream to derive cash and net external capital flows.

    Positive external flows represent inferred capital contributions when cash
    would otherwise go negative. Negative external flows represent subsequent
    withdrawals (repayment) when later events replenish cash above outstanding
    inferred contributions.
    """
    if replay_diagnostics is not None:
        replay_diagnostics.setdefault("futures_txn_count_replayed", 0)
        replay_diagnostics.setdefault("futures_notional_suppressed_usd", 0.0)
        replay_diagnostics.setdefault("futures_fee_cash_impact_usd", 0.0)
        replay_diagnostics.setdefault("futures_unknown_action_count", 0)
        replay_diagnostics.setdefault("futures_missing_fx_count", 0)
        replay_diagnostics.setdefault("income_flow_overlap_dropped_count", 0)
        replay_diagnostics.setdefault("income_flow_overlap_dropped_net_usd", 0.0)
        replay_diagnostics.setdefault("income_flow_overlap_dropped_by_provider", {})
        replay_diagnostics.setdefault("income_flow_overlap_candidate_count", 0)
        replay_diagnostics.setdefault("income_flow_overlap_alias_mismatch_count", 0)
        replay_diagnostics.setdefault("income_flow_overlap_alias_mismatch_samples", [])

    def _fx_with_futures_default(currency: str, when: datetime) -> Tuple[float, bool]:
        ccy = str(currency or "USD").upper()
        if ccy == "USD":
            return 1.0, False

        fx_series = fx_cache.get(ccy)
        if fx_series is None or len(fx_series) == 0:
            return 1.0, True

        fx_value = _value_at_or_before(fx_series, when, default=np.nan)
        if not np.isfinite(_as_float(fx_value, default=np.nan)) or _as_float(fx_value, default=np.nan) <= 0:
            return 1.0, True

        return float(_as_float(fx_value, default=1.0)), False

    provider_flow_events_for_replay = list(provider_flow_events or [])
    overlap_diagnostics: Dict[str, Any] = {
        "dropped_count": 0,
        "dropped_net_usd": 0.0,
        "dropped_by_provider": {},
        "candidate_count": 0,
        "alias_normalization_mismatch_count": 0,
        "alias_normalization_mismatch_samples": [],
    }
    if provider_flow_events_for_replay:
        provider_flow_events_for_replay, overlap_diagnostics = _dedupe_income_provider_internal_flow_overlap(
            income_with_currency=income_with_currency,
            provider_flow_events=provider_flow_events_for_replay,
        )

    events: List[Dict[str, Any]] = []
    _skipped_unknown = 0
    _skipped_fx = 0
    _futures_count = 0

    for txn in fifo_transactions:
        date = _to_datetime(txn.get("date"))
        if date is None:
            continue

        instrument_type = _infer_instrument_type_from_transaction(txn)
        if instrument_type == "unknown":
            _skipped_unknown += 1
            continue
        if instrument_type == "fx_artifact":
            _skipped_fx += 1
            continue

        symbol = str(txn.get("symbol") or "").strip()
        if "symbol" in txn and not symbol:
            _skipped_unknown += 1
            continue

        is_futures = instrument_type == "futures"
        if is_futures:
            _futures_count += 1

        events.append(
            {
                "date": date,
                "event_type": str(txn.get("type", "")).upper(),
                "price": _as_float(txn.get("price"), 0.0),
                "quantity": abs(_as_float(txn.get("quantity"), 0.0)),
                "fee": abs(_as_float(txn.get("fee"), 0.0)),
                "currency": str(txn.get("currency") or "USD").upper(),
                "is_futures": is_futures,
                "symbol": symbol,
            }
        )

    if warnings is not None and _skipped_unknown > 0:
        warnings.append(
            f"Cash replay: skipped {_skipped_unknown} unknown/empty-symbol transaction(s)."
        )
    if warnings is not None and _skipped_fx > 0:
        warnings.append(
            f"Cash replay: skipped {_skipped_fx} fx-artifact transaction(s)."
        )
    if warnings is not None and _futures_count > 0:
        warnings.append(
            f"Cash replay: replaying {_futures_count} futures transaction(s); "
            "inference is suppressed while futures exposure is open."
        )

    for inc in income_with_currency:
        date = _to_datetime(inc.get("date"))
        if date is None:
            continue
        events.append(
            {
                "date": date,
                "event_type": "INCOME",
                "amount": _as_float(inc.get("amount"), 0.0),
                "currency": str(inc.get("currency") or "USD").upper(),
            }
        )

    for provider_flow in provider_flow_events_for_replay:
        date = _to_datetime(provider_flow.get("timestamp") or provider_flow.get("date"))
        if date is None:
            continue
        amount = _as_float(provider_flow.get("amount"), 0.0)
        if amount == 0:
            continue
        events.append(
            {
                "date": date,
                "event_type": "PROVIDER_FLOW",
                "amount": amount,
                "currency": str(provider_flow.get("currency") or "USD").upper(),
                "is_external_flow": bool(provider_flow.get("is_external_flow")),
            }
        )

    events.sort(key=lambda e: (e["date"], TYPE_ORDER.get(e["event_type"], 99)))

    cash = 0.0
    outstanding_injections = 0.0
    cash_snapshots: List[Tuple[datetime, float]] = []
    external_flows: List[Tuple[datetime, float]] = []
    provider_mode = bool(provider_flow_events)
    inference_enabled = ((not provider_mode) or (not disable_inference_when_provider_mode)) and not force_disable_inference
    _futures_positions: Dict[str, float] = {}
    futures_notional_suppressed_usd = 0.0
    futures_fee_cash_impact_usd = 0.0
    futures_unknown_action_count = 0
    futures_missing_fx_count = 0

    for event in events:
        event_type = event["event_type"]
        is_futures = bool(event.get("is_futures", False))
        if is_futures:
            fx, missing_fx = _fx_with_futures_default(event.get("currency", "USD"), event["date"])
            if missing_fx:
                futures_missing_fx_count += 1
        else:
            fx = _event_fx_rate(event.get("currency", "USD"), event["date"], fx_cache)

        if is_futures:
            if event_type in {"BUY", "SELL", "SHORT", "COVER"}:
                futures_notional_suppressed_usd += abs(event["price"] * event["quantity"] * fx)
                fee_cash_impact = -(event["fee"] * fx)
                cash += fee_cash_impact
                futures_fee_cash_impact_usd += fee_cash_impact
            else:
                futures_unknown_action_count += 1
                if event["fee"] > 0:
                    fee_cash_impact = -(event["fee"] * fx)
                    cash += fee_cash_impact
                    futures_fee_cash_impact_usd += fee_cash_impact
        else:
            if event_type == "BUY":
                cash -= (event["price"] * event["quantity"] + event["fee"]) * fx
            elif event_type == "SELL":
                cash += (event["price"] * event["quantity"] - event["fee"]) * fx
            elif event_type == "SHORT":
                cash += (event["price"] * event["quantity"] - event["fee"]) * fx
            elif event_type == "COVER":
                cash -= (event["price"] * event["quantity"] + event["fee"]) * fx
            elif event_type == "INCOME":
                cash += event.get("amount", 0.0) * fx
            elif event_type == "PROVIDER_FLOW":
                signed_amount = event.get("amount", 0.0) * fx
                cash += signed_amount
                if bool(event.get("is_external_flow")):
                    external_flows.append((event["date"], signed_amount))

        if is_futures:
            symbol = str(event.get("symbol") or "").strip().upper()
            quantity = event["quantity"]
            if event_type in ("BUY", "COVER"):
                _futures_positions[symbol] = _futures_positions.get(symbol, 0.0) + quantity
            elif event_type in ("SELL", "SHORT"):
                _futures_positions[symbol] = _futures_positions.get(symbol, 0.0) - quantity

            if symbol in _futures_positions and abs(_futures_positions[symbol]) < 1e-9:
                del _futures_positions[symbol]

        # When provider flows are supplied for this replay, treat them as the
        # authoritative capital-flow source for the branch and disable inferred
        # contribution/withdrawal generation entirely.
        apply_inferred_adjustments = inference_enabled
        has_open_futures = bool(_futures_positions)

        if apply_inferred_adjustments and not has_open_futures and cash < 0:
            injection = abs(cash)
            external_flows.append((event["date"], injection))
            outstanding_injections += injection
            cash = 0.0

        # Repay previously inferred contributions before carrying excess cash.
        if apply_inferred_adjustments and not has_open_futures and cash > 0 and outstanding_injections > 0:
            withdrawal = min(cash, outstanding_injections)
            if withdrawal > 0:
                external_flows.append((event["date"], -withdrawal))
                cash -= withdrawal
                outstanding_injections -= withdrawal

        cash_snapshots.append((event["date"], cash))

    if warnings is not None and _futures_positions:
        open_symbols = ", ".join(symbol or "<UNKNOWN>" for symbol in sorted(_futures_positions.keys()))
        warnings.append(
            f"Cash replay: {len(_futures_positions)} open futures position(s) at end of "
            f"replay ({open_symbols}). Inference was suppressed during open period."
        )
    if warnings is not None and futures_unknown_action_count > 0:
        warnings.append(
            f"Cash replay: {futures_unknown_action_count} futures transaction(s) used fee-only fallback for unknown action types."
        )
    if warnings is not None and futures_missing_fx_count > 0:
        warnings.append(
            f"Cash replay: {futures_missing_fx_count} futures transaction(s) used FX=1.0 fallback due to missing/invalid FX."
        )
    if warnings is not None and int(_as_float(overlap_diagnostics.get("dropped_count"), 0.0)) > 0:
        warnings.append(
            "Cash replay: dropped "
            f"{int(_as_float(overlap_diagnostics.get('dropped_count'), 0.0))} overlapping non-external "
            "provider-flow event(s) in favor of INCOME rows."
        )

    if replay_diagnostics is not None:
        replay_diagnostics["futures_txn_count_replayed"] = int(
            _as_float(replay_diagnostics.get("futures_txn_count_replayed"), 0.0)
        ) + _futures_count
        replay_diagnostics["futures_notional_suppressed_usd"] = _as_float(
            replay_diagnostics.get("futures_notional_suppressed_usd"),
            0.0,
        ) + futures_notional_suppressed_usd
        replay_diagnostics["futures_fee_cash_impact_usd"] = _as_float(
            replay_diagnostics.get("futures_fee_cash_impact_usd"),
            0.0,
        ) + futures_fee_cash_impact_usd
        replay_diagnostics["futures_unknown_action_count"] = int(
            _as_float(replay_diagnostics.get("futures_unknown_action_count"), 0.0)
        ) + futures_unknown_action_count
        replay_diagnostics["futures_missing_fx_count"] = int(
            _as_float(replay_diagnostics.get("futures_missing_fx_count"), 0.0)
        ) + futures_missing_fx_count
        replay_diagnostics["income_flow_overlap_dropped_count"] = int(
            _as_float(replay_diagnostics.get("income_flow_overlap_dropped_count"), 0.0)
        ) + int(_as_float(overlap_diagnostics.get("dropped_count"), 0.0))
        replay_diagnostics["income_flow_overlap_dropped_net_usd"] = _as_float(
            replay_diagnostics.get("income_flow_overlap_dropped_net_usd"),
            0.0,
        ) + _as_float(overlap_diagnostics.get("dropped_net_usd"), 0.0)
        replay_diagnostics["income_flow_overlap_candidate_count"] = int(
            _as_float(replay_diagnostics.get("income_flow_overlap_candidate_count"), 0.0)
        ) + int(_as_float(overlap_diagnostics.get("candidate_count"), 0.0))
        replay_diagnostics["income_flow_overlap_alias_mismatch_count"] = int(
            _as_float(replay_diagnostics.get("income_flow_overlap_alias_mismatch_count"), 0.0)
        ) + int(_as_float(overlap_diagnostics.get("alias_normalization_mismatch_count"), 0.0))

        dropped_by_provider = replay_diagnostics.setdefault("income_flow_overlap_dropped_by_provider", {})
        for provider, count in dict(overlap_diagnostics.get("dropped_by_provider") or {}).items():
            dropped_by_provider[provider] = int(_as_float(dropped_by_provider.get(provider), 0.0)) + int(
                _as_float(count, 0.0)
            )

        sample_pairs = replay_diagnostics.setdefault("income_flow_overlap_alias_mismatch_samples", [])
        for pair in list(overlap_diagnostics.get("alias_normalization_mismatch_samples") or []):
            if pair not in sample_pairs and len(sample_pairs) < 5:
                sample_pairs.append(pair)

    return cash_snapshots, external_flows


def compute_monthly_nav(
    position_timeline: Dict[Tuple[str, str, str], List[Tuple[datetime, float]]],
    month_ends: List[datetime],
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
    cash_snapshots: List[Tuple[datetime, float]],
) -> pd.Series:
    """Compute month-end NAV = valued positions + derived cash."""
    if not month_ends:
        return pd.Series(dtype=float)

    month_end_index = pd.DatetimeIndex(pd.to_datetime(month_ends)).sort_values()

    events_by_key: Dict[Tuple[str, str, str], List[Tuple[datetime, float]]] = {}
    ptrs: Dict[Tuple[str, str, str], int] = {}
    quantities: Dict[Tuple[str, str, str], float] = {}

    for key, events in position_timeline.items():
        normalized = [(pd.Timestamp(d).to_pydatetime().replace(tzinfo=None), _as_float(q, 0.0)) for d, q in events]
        normalized.sort(key=lambda x: x[0])
        events_by_key[key] = normalized
        ptrs[key] = 0
        quantities[key] = 0.0

    cash_snapshots_sorted = sorted(
        [(pd.Timestamp(d).to_pydatetime().replace(tzinfo=None), _as_float(v, 0.0)) for d, v in cash_snapshots],
        key=lambda x: x[0],
    )
    cash_ptr = 0
    cash_value = 0.0

    nav_values: List[float] = []

    for month_end in month_end_index:
        me = month_end.to_pydatetime().replace(tzinfo=None)

        while cash_ptr < len(cash_snapshots_sorted) and cash_snapshots_sorted[cash_ptr][0] <= me:
            cash_value = cash_snapshots_sorted[cash_ptr][1]
            cash_ptr += 1

        position_value = 0.0

        for key, events in events_by_key.items():
            ptr = ptrs[key]
            while ptr < len(events) and events[ptr][0] <= me:
                quantities[key] += events[ptr][1]
                ptr += 1
            ptrs[key] = ptr

            qty = quantities[key]
            if abs(qty) < 1e-9:
                continue

            ticker, currency, direction = key
            price = _value_at_or_before(price_cache.get(ticker), me, default=0.0)
            fx = _event_fx_rate(currency, me, fx_cache)
            sign = -1.0 if direction == "SHORT" else 1.0
            position_value += sign * qty * price * fx

        nav_values.append(position_value + cash_value)

    return pd.Series(nav_values, index=month_end_index, dtype=float)


def compute_monthly_external_flows(
    external_flows: List[Tuple[datetime, float]],
    month_ends: List[datetime],
) -> Tuple[pd.Series, pd.Series]:
    """Aggregate external inflows by month (net and Modified-Dietz weighted)."""
    index = pd.DatetimeIndex(pd.to_datetime(month_ends)).sort_values()
    net_flows = pd.Series(0.0, index=index)
    weighted_flows = pd.Series(0.0, index=index)

    for flow_date, amount in external_flows:
        flow_ts = pd.Timestamp(flow_date)
        month_end = flow_ts.to_period("M").to_timestamp("M")
        if month_end not in net_flows.index:
            continue

        month_start = month_end.to_period("M").to_timestamp("M") + pd.offsets.MonthBegin(-1)
        # Convert to true month start (YYYY-MM-01)
        month_start = pd.Timestamp(year=month_end.year, month=month_end.month, day=1)

        days_in_month = int(month_end.day)
        day_of_month = int((flow_ts.normalize() - month_start).days)
        day_of_month = max(0, min(day_of_month, days_in_month - 1))
        weight = (days_in_month - day_of_month) / days_in_month

        net_flows.loc[month_end] += _as_float(amount, 0.0)
        weighted_flows.loc[month_end] += _as_float(amount, 0.0) * weight

    return net_flows, weighted_flows


def compute_monthly_returns(
    monthly_nav: pd.Series,
    net_flows: pd.Series,
    time_weighted_flows: pd.Series,
) -> Tuple[pd.Series, List[str]]:
    """Compute Modified Dietz monthly returns using cash-inclusive NAV."""
    warnings: List[str] = []

    if monthly_nav is None or monthly_nav.empty:
        return pd.Series(dtype=float), ["Monthly NAV series is empty; cannot compute returns."]

    nav = monthly_nav.sort_index().astype(float)
    net = net_flows.reindex(nav.index).fillna(0.0).astype(float)
    tw = time_weighted_flows.reindex(nav.index).fillna(0.0).astype(float)

    returns = pd.Series(index=nav.index, dtype=float)

    prev_nav = 0.0
    for i, ts in enumerate(nav.index):
        v_end = _as_float(nav.iloc[i], 0.0)
        v_start = prev_nav if i > 0 else 0.0
        flow_net = _as_float(net.loc[ts], 0.0)
        flow_weighted = _as_float(tw.loc[ts], 0.0)

        if abs(v_start) < 1e-12:
            denom = flow_net
            if denom <= 0:
                returns.loc[ts] = 0.0
                warnings.append(
                    f"{ts.date().isoformat()}: V_start=0 with no detected inflows; return set to 0."
                )
            else:
                returns.loc[ts] = (v_end - flow_net) / denom
        else:
            v_adjusted = v_start + flow_weighted
            if v_adjusted <= 0:
                returns.loc[ts] = 0.0
                warnings.append(
                    f"{ts.date().isoformat()}: V_adjusted<=0 ({v_adjusted:.6f}); return set to 0."
                )
            else:
                returns.loc[ts] = (v_end - v_start - flow_net) / v_adjusted

        prev_nav = v_end

    return returns, warnings


def _safe_treasury_rate(start_date: datetime, end_date: datetime) -> float:
    """Fetch mean 3M treasury yield and return annual decimal rate."""
    try:
        rates = fetch_monthly_treasury_rates("month3", start_date, end_date)
        rates = _series_from_cache(rates)
        if rates.empty:
            return 0.04
        return _as_float(rates.mean(), 4.0) / 100.0
    except Exception:
        return 0.04


def _compute_unrealized_pnl_usd(
    fifo_result,
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
    as_of: datetime,
) -> float:
    """Compute unrealized P&L from FIFO open lots converted to USD."""
    total = 0.0
    for (symbol, currency, direction), lots in fifo_result.open_lots.items():
        current_price = _value_at_or_before(price_cache.get(symbol), as_of, default=0.0)
        fx = _event_fx_rate(currency, as_of, fx_cache)
        for lot in lots:
            qty = _as_float(getattr(lot, "remaining_quantity", 0.0), 0.0)
            entry = _as_float(getattr(lot, "entry_price", 0.0), 0.0)
            if direction == "SHORT":
                pnl = (entry - current_price) * qty
            else:
                pnl = (current_price - entry) * qty
            total += pnl * fx
    return total


def _compute_net_contributions_usd(
    fifo_transactions: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
) -> float:
    """Compute net contributed capital (buys/covers minus sells/shorts) in USD."""
    total = 0.0
    for txn in fifo_transactions:
        date = _to_datetime(txn.get("date"))
        if date is None:
            continue
        txn_type = str(txn.get("type", "")).upper()
        amount = _as_float(txn.get("price"), 0.0) * abs(_as_float(txn.get("quantity"), 0.0))
        fee = abs(_as_float(txn.get("fee"), 0.0))
        fx = _event_fx_rate(str(txn.get("currency") or "USD"), date, fx_cache)

        if txn_type in {"BUY", "COVER"}:
            total += (amount + fee) * fx
        elif txn_type in {"SELL", "SHORT"}:
            total -= (amount - fee) * fx

    return total


def _income_with_currency(
    analyzer: TradingAnalyzer,
    fifo_transactions: List[Dict[str, Any]],
    current_positions: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach inferred currency to normalized income events."""
    symbol_currency_map: Dict[str, str] = {}

    for txn in fifo_transactions:
        symbol = str(txn.get("symbol") or "").strip()
        if not symbol:
            continue
        symbol_currency_map.setdefault(symbol, str(txn.get("currency") or "USD").upper())

    for symbol, pos in current_positions.items():
        symbol_currency_map.setdefault(symbol, str(pos.get("currency") or "USD").upper())

    rows: List[Dict[str, Any]] = []
    for inc in analyzer.income_events:
        direct_currency = str(getattr(inc, "currency", "") or "").strip().upper()
        rows.append(
            {
                "symbol": inc.symbol,
                "date": inc.date,
                "amount": _as_float(inc.amount, 0.0),
                "income_type": inc.income_type,
                "currency": direct_currency or symbol_currency_map.get(inc.symbol, "USD"),
                "source": inc.source,
                "institution": getattr(inc, "institution", "") or "",
                "account_id": _normalize_optional_identifier(getattr(inc, "account_id", None)),
                "account_name": _normalize_optional_identifier(getattr(inc, "account_name", None)),
            }
        )
    return rows


def _normalize_optional_identifier(value: Any) -> str | None:
    """Return stripped identifier string or ``None`` when empty."""

    text = str(value or "").strip()
    return text or None


def _normalize_replay_identifier(value: Any, *, default: str) -> str:
    token = str(value or "").strip()
    if not token:
        return default
    token = re.sub(r"[\s\-]+", "_", token.upper())
    token = re.sub(r"_+", "_", token).strip("_")
    return token or default


def _normalize_realized_replay_provider(
    value: Any,
    *,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> str:
    raw = str(value or "").strip()
    normalized = _normalize_replay_identifier(raw, default="UNKNOWN")
    normalized = REALIZED_PROVIDER_ALIAS_MAP.get(normalized, normalized)

    if diagnostics is not None and raw:
        raw_upper = raw.upper()
        if normalized != raw_upper:
            diagnostics["alias_normalization_mismatch_count"] = int(
                _as_float(diagnostics.get("alias_normalization_mismatch_count"), 0.0)
            ) + 1
            pair = {
                "raw_provider": raw,
                "normalized_provider": normalized,
            }
            samples = diagnostics.setdefault("alias_normalization_mismatch_samples", [])
            if pair not in samples and len(samples) < 5:
                samples.append(pair)

    return normalized


def _replay_account_identity(row: Dict[str, Any]) -> str:
    account_id = _normalize_optional_identifier(row.get("account_id"))
    if account_id:
        return f"ACCOUNT_ID:{_normalize_replay_identifier(account_id, default='UNKNOWN')}"

    account_number = _normalize_optional_identifier(row.get("account_number"))
    if account_number:
        return f"ACCOUNT_NUMBER:{_normalize_replay_identifier(account_number, default='UNKNOWN')}"

    institution = _normalize_replay_identifier(
        _normalize_optional_identifier(row.get("institution")),
        default="UNKNOWN_INSTITUTION",
    )
    masked_account = _normalize_optional_identifier(row.get("masked_account"))
    if not masked_account:
        masked_account = _normalize_optional_identifier(row.get("account_name"))
    if not masked_account:
        masked_account = _normalize_optional_identifier(row.get("provider_account_ref"))
    masked_component = _normalize_replay_identifier(
        masked_account,
        default="UNKNOWN_ACCOUNT",
    )
    return f"FALLBACK:{institution}|{masked_component}"


def _dedupe_income_provider_internal_flow_overlap(
    *,
    income_with_currency: List[Dict[str, Any]],
    provider_flow_events: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    diagnostics: Dict[str, Any] = {
        "dropped_count": 0,
        "dropped_net_usd": 0.0,
        "dropped_by_provider": {},
        "candidate_count": 0,
        "alias_normalization_mismatch_count": 0,
        "alias_normalization_mismatch_samples": [],
    }
    if not provider_flow_events or not income_with_currency:
        return list(provider_flow_events), diagnostics

    income_lookup: Dict[Tuple[str, str, datetime, int], List[Dict[str, Any]]] = defaultdict(list)
    for inc in income_with_currency:
        inc_date = _to_datetime(inc.get("date"))
        if inc_date is None:
            continue
        provider_key = _normalize_realized_replay_provider(
            inc.get("source"),
            diagnostics=diagnostics,
        )
        account_identity = _replay_account_identity(inc)
        amount = _as_float(inc.get("amount"), 0.0)
        amount_cents = int(round(amount * 100.0))
        income_lookup[(provider_key, account_identity, inc_date.date(), amount_cents)].append(
            {"amount": amount, "matched": False}
        )

    dropped_by_provider: Dict[str, int] = defaultdict(int)
    filtered_events: List[Dict[str, Any]] = []

    for provider_flow in provider_flow_events:
        if bool(provider_flow.get("is_external_flow")):
            filtered_events.append(provider_flow)
            continue

        flow_date = _to_datetime(provider_flow.get("timestamp") or provider_flow.get("date"))
        if flow_date is None:
            filtered_events.append(provider_flow)
            continue

        provider_key = _normalize_realized_replay_provider(
            provider_flow.get("provider") or provider_flow.get("source"),
            diagnostics=diagnostics,
        )
        account_identity = _replay_account_identity(provider_flow)
        amount = _as_float(provider_flow.get("amount"), 0.0)
        amount_cents = int(round(amount * 100.0))

        candidate_groups: List[List[Dict[str, Any]]] = []
        for cents in (amount_cents - 1, amount_cents, amount_cents + 1):
            bucket = income_lookup.get((provider_key, account_identity, flow_date.date(), cents))
            if bucket:
                candidate_groups.append(bucket)

        if candidate_groups:
            diagnostics["candidate_count"] = int(_as_float(diagnostics.get("candidate_count"), 0.0)) + 1

        matched = False
        for group in candidate_groups:
            for candidate in group:
                if candidate.get("matched"):
                    continue
                if abs(_as_float(candidate.get("amount"), 0.0) - amount) <= 0.01:
                    candidate["matched"] = True
                    matched = True
                    break
            if matched:
                break

        if matched:
            dropped_by_provider[provider_key] += 1
            diagnostics["dropped_count"] = int(_as_float(diagnostics.get("dropped_count"), 0.0)) + 1
            diagnostics["dropped_net_usd"] = _as_float(diagnostics.get("dropped_net_usd"), 0.0) + amount
            continue

        filtered_events.append(provider_flow)

    diagnostics["dropped_net_usd"] = round(_as_float(diagnostics.get("dropped_net_usd"), 0.0), 2)
    diagnostics["dropped_by_provider"] = dict(sorted(dropped_by_provider.items()))
    return filtered_events, diagnostics


def _flow_slice_key(
    *,
    provider: Any,
    institution: Any,
    account_id: Any,
    provider_account_ref: Any,
    account_name: Any,
) -> str:
    """Build canonical provider/institution/account key for flow authority slices."""

    return build_slice_key(
        provider=str(provider or "unknown").strip().lower() or "unknown",
        institution=_normalize_optional_identifier(institution),
        account_id=_normalize_optional_identifier(account_id),
        provider_account_ref=_normalize_optional_identifier(provider_account_ref),
        account_name=_normalize_optional_identifier(account_name),
    )


def _provider_flow_event_sort_key(event: Dict[str, Any]) -> Tuple[str, datetime, str, str, str]:
    """Stable sort key for deterministic provider-flow event deduplication."""

    provider = str(event.get("provider") or "unknown").strip().lower()
    timestamp = _to_datetime(event.get("timestamp") or event.get("date")) or datetime.min
    transaction_id = str(event.get("transaction_id") or "")
    account_id = str(event.get("account_id") or "")
    fingerprint = str(event.get("provider_row_fingerprint") or "")
    return provider, timestamp, transaction_id, account_id, fingerprint


def _deduplicate_provider_flow_events(
    events: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Deduplicate provider flow events and return diagnostics.

    Dedup semantics:
    - Prefer transaction-id keys when available.
    - Fall back to provider/account/date/amount/type fingerprint when needed.
    - Fail-open for rows lacking safe identity fields (kept, not dropped).
    """

    seen: set[Tuple[Any, ...]] = set()
    deduped: List[Dict[str, Any]] = []
    dropped_by_provider: Dict[str, int] = defaultdict(int)
    dropped_by_slice: Dict[str, int] = defaultdict(int)

    for event in sorted(events, key=_provider_flow_event_sort_key):
        provider = str(event.get("provider") or "unknown").strip().lower()
        slice_key = _flow_slice_key(
            provider=provider,
            institution=event.get("institution"),
            account_id=event.get("account_id"),
            provider_account_ref=event.get("provider_account_ref"),
            account_name=event.get("account_name"),
        )
        canonical_identity = slice_key.split("|")[-1]
        transaction_id = str(event.get("transaction_id") or "").strip()

        dedup_key: Tuple[Any, ...] | None
        if transaction_id:
            dedup_key = ("txn_id", provider, canonical_identity, transaction_id)
        else:
            timestamp = _to_datetime(event.get("timestamp") or event.get("date"))
            raw_description = str(event.get("raw_description") or "").strip()
            fingerprint = str(event.get("provider_row_fingerprint") or "").strip()
            if not raw_description and not fingerprint:
                # Fail-open: insufficient identity for safe dedup.
                dedup_key = None
            else:
                dedup_key = (
                    "fallback",
                    provider,
                    canonical_identity,
                    timestamp.isoformat() if timestamp else "",
                    round(_as_float(event.get("amount"), 0.0), 8),
                    str(event.get("currency") or "USD").upper(),
                    str(event.get("raw_type") or ""),
                    str(event.get("raw_subtype") or ""),
                    raw_description,
                    fingerprint,
                )

        if dedup_key is not None and dedup_key in seen:
            dropped_by_provider[provider] += 1
            dropped_by_slice[slice_key] += 1
            continue

        if dedup_key is not None:
            seen.add(dedup_key)
        deduped.append(event)

    diagnostics = {
        "input_count": len(events),
        "output_count": len(deduped),
        "duplicates_dropped_by_provider": dict(sorted(dropped_by_provider.items())),
        "duplicates_dropped_by_slice": dict(sorted(dropped_by_slice.items())),
    }
    return deduped, diagnostics


def _build_provider_flow_authority(
    events: List[Dict[str, Any]],
    fetch_metadata: List[Dict[str, Any]],
    *,
    require_coverage: bool,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Build slice-level authority map for provider-reported flow usage.

    Decision semantics:
    - Slice is authoritative when it has provider events.
    - Slice may also be authoritative with deterministic no-flow metadata
      (clean metadata indicates no events for that window).
    - ``require_coverage`` is retained for interface compatibility but does not
      gate authority in current direct-first mode.
    """

    # Gate-free mode: provider-reported events are authoritative when present.
    # ``require_coverage`` is retained for interface compatibility, but authority
    # no longer fails closed on metadata quality flags.
    _ = require_coverage
    authority: Dict[str, Dict[str, Any]] = {}
    fallback_reasons: List[str] = []
    event_count_by_slice: Dict[str, int] = defaultdict(int)

    for event in events:
        key = _flow_slice_key(
            provider=event.get("provider"),
            institution=event.get("institution"),
            account_id=event.get("account_id"),
            provider_account_ref=event.get("provider_account_ref"),
            account_name=event.get("account_name"),
        )
        event_count_by_slice[key] += 1

    metadata_by_slice: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in fetch_metadata:
        key = _flow_slice_key(
            provider=row.get("provider"),
            institution=row.get("institution"),
            account_id=row.get("account_id"),
            provider_account_ref=row.get("provider_account_ref"),
            account_name=row.get("account_name"),
        )
        metadata_by_slice[key].append(row)

    all_slices = set(event_count_by_slice.keys()) | set(metadata_by_slice.keys())
    for key in sorted(all_slices):
        slice_metadata = metadata_by_slice.get(key, [])
        event_count = int(event_count_by_slice.get(key, 0))
        has_metadata = len(slice_metadata) > 0
        has_error = any(str(row.get("fetch_error") or "").strip() for row in slice_metadata)
        has_partial = any(
            bool(row.get("partial_data")) or row.get("pagination_exhausted") is False
            for row in slice_metadata
        )
        unmapped_row_count = int(sum(_as_float(row.get("unmapped_row_count"), 0.0) for row in slice_metadata))
        has_unmapped = unmapped_row_count > 0
        has_snaptrade_sync_gap = any(_is_snaptrade_sync_gap_metadata_row(row) for row in slice_metadata)

        coverage_starts = [
            _to_datetime(row.get("payload_coverage_start") or row.get("fetch_window_start"))
            for row in slice_metadata
        ]
        coverage_ends = [
            _to_datetime(row.get("payload_coverage_end") or row.get("fetch_window_end"))
            for row in slice_metadata
        ]
        coverage_start = min((dt for dt in coverage_starts if dt is not None), default=None)
        coverage_end = max((dt for dt in coverage_ends if dt is not None), default=None)

        deterministic_no_flow = (
            has_metadata
            and event_count == 0
            and (
                (not has_error and not has_partial and not has_unmapped)
                or (has_snaptrade_sync_gap and not has_error and not has_unmapped)
            )
        )
        authoritative = event_count > 0 or deterministic_no_flow

        reason = ""
        if not authoritative:
            if event_count == 0 and has_metadata and not has_error and not has_partial and not has_unmapped:
                reason = "no_provider_events_with_clean_metadata"
            elif event_count == 0 and not has_metadata:
                reason = "missing_fetch_metadata"
            else:
                reason = "no_provider_events"
            fallback_reasons.append(f"{key}:{reason}")

        authority[key] = {
            "authoritative": authoritative,
            "has_metadata": has_metadata,
            "event_count": event_count,
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "has_error": has_error,
            "has_partial": has_partial,
            "deterministic_no_flow": deterministic_no_flow,
            "unmapped_row_count": unmapped_row_count,
        }

    return authority, sorted(set(fallback_reasons))


def _is_snaptrade_sync_gap_metadata_row(row: Dict[str, Any]) -> bool:
    """Detect SnapTrade metadata rows indicating transactions-sync initialization gap."""

    provider = str(row.get("provider") or "").strip().lower()
    if provider != "snaptrade":
        return False
    diagnostic_code = str(row.get("diagnostic_code") or "").strip().lower()
    transactions_sync_initialized = row.get("transactions_sync_initialized")
    row_count = int(_as_float(row.get("row_count"), 0.0))
    return (
        diagnostic_code == "snaptrade_transactions_sync_uninitialized"
        or (transactions_sync_initialized is False and row_count == 0)
    )


def _build_fetch_metadata_warnings(
    fetch_metadata: List[Dict[str, Any]],
    *,
    source: str,
    institution: Optional[str],
) -> List[str]:
    """Build user-facing warnings from provider fetch-metadata diagnostics."""

    warnings: List[str] = []
    seen: set[str] = set()
    source_filter = str(source or "all").strip().lower()

    for row in fetch_metadata:
        provider = str(row.get("provider") or "").strip().lower()
        if source_filter != "all" and provider != source_filter:
            continue

        row_institution = str(row.get("institution") or "")
        if institution and row_institution and not match_institution(row_institution, institution):
            continue

        is_snaptrade_sync_gap = _is_snaptrade_sync_gap_metadata_row(row)
        if not is_snaptrade_sync_gap:
            continue

        institution_label = row_institution.strip() or "unknown institution"
        account_label = (
            str(row.get("account_name") or "").strip()
            or str(row.get("account_id") or "").strip()
            or "unknown account"
        )

        warning = (
            f"SnapTrade transaction reporting is unavailable for {institution_label} ({account_label}); "
            "account activities returned zero rows. Use provider-native transaction feeds "
            "(for example, IBKR Flex for Interactive Brokers) for realized-performance history."
        )
        if warning in seen:
            continue
        seen.add(warning)
        warnings.append(warning)

    return warnings


def _is_authoritative_slice(
    authority: Dict[str, Dict[str, Any]],
    *,
    provider: Any,
    institution: Any,
    account_id: Any,
    provider_account_ref: Any,
    account_name: Any,
    event_date: datetime,
) -> bool:
    return _authoritative_slice_status(
        authority,
        provider=provider,
        institution=institution,
        account_id=account_id,
        provider_account_ref=provider_account_ref,
        account_name=account_name,
        event_date=event_date,
    ) == "authoritative_in_window"


def _authoritative_slice_status(
    authority: Dict[str, Dict[str, Any]],
    *,
    provider: Any,
    institution: Any,
    account_id: Any,
    provider_account_ref: Any,
    account_name: Any,
    event_date: datetime,
) -> str:
    key = _flow_slice_key(
        provider=provider,
        institution=institution,
        account_id=account_id,
        provider_account_ref=provider_account_ref,
        account_name=account_name,
    )
    row = authority.get(key)
    if not row or not bool(row.get("authoritative")):
        return "non_authoritative"

    start = _to_datetime(row.get("coverage_start"))
    end = _to_datetime(row.get("coverage_end"))
    if start is not None and event_date < start:
        return "authoritative_out_of_window"
    if end is not None and event_date > end:
        return "authoritative_out_of_window"
    return "authoritative_in_window"


def _combine_cash_snapshots(
    inference_snapshots: List[Tuple[datetime, float]],
    provider_cash_deltas: List[Tuple[datetime, float]],
) -> List[Tuple[datetime, float]]:
    inference_deltas: List[Tuple[datetime, float]] = []
    prev_cash = 0.0
    for when, cash_value in sorted(inference_snapshots, key=lambda row: row[0]):
        delta = _as_float(cash_value, 0.0) - prev_cash
        prev_cash = _as_float(cash_value, 0.0)
        inference_deltas.append((when, delta))

    combined_events: List[Tuple[datetime, int, float]] = []
    combined_events.extend((when, 0, _as_float(delta, 0.0)) for when, delta in inference_deltas)
    combined_events.extend((when, 1, _as_float(delta, 0.0)) for when, delta in provider_cash_deltas)
    combined_events.sort(key=lambda row: (row[0], row[1]))

    cash = 0.0
    snapshots: List[Tuple[datetime, float]] = []
    for when, _order, delta in combined_events:
        cash += delta
        snapshots.append((when, cash))
    return snapshots


def _normalize_source_name(value: Any) -> str:
    source = str(value or "unknown").strip().lower()
    return source or "unknown"


def _sanitize_backfill_id_component(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "unknown"
    return "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in raw)


def _build_backfill_transaction_id(
    entry: Dict[str, Any],
    seq_by_fallback_key: Dict[Tuple[str, str, str, str, str, str], int],
) -> str:
    source = _sanitize_backfill_id_component(_normalize_source_name(entry.get("source")))
    exit_transaction_id = str(entry.get("transaction_id") or "").strip()
    if exit_transaction_id:
        return f"backfill_{source}_entry_for_{_sanitize_backfill_id_component(exit_transaction_id)}"

    symbol = _sanitize_backfill_id_component(entry.get("symbol"))
    entry_date = _to_datetime(entry.get("manual_entry_date"))
    date_component = entry_date.date().isoformat() if entry_date else "unknown_date"
    direction = _sanitize_backfill_id_component(str(entry.get("direction") or "LONG").upper())
    qty_component = _sanitize_backfill_id_component(f"{abs(_as_float(entry.get('quantity'), 0.0)):.10g}")
    price_component = _sanitize_backfill_id_component(f"{_as_float(entry.get('manual_entry_price'), 0.0):.10g}")
    fallback_key = (source, symbol, date_component, direction, qty_component, price_component)
    seq = seq_by_fallback_key[fallback_key]
    seq_by_fallback_key[fallback_key] += 1
    return f"backfill_{source}_{symbol}_{date_component}_{direction}_{qty_component}_{price_component}_{seq}"


def _build_backfill_entry_transactions(
    backfill_path: Optional[str],
    source_filter: str,
    existing_transaction_ids: set[str],
    explicit_path: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], List[str]]:
    """Load manual backfill file and convert rows into synthetic entry transactions."""
    warnings: List[str] = []
    path = str(backfill_path or "").strip()
    if not path:
        return [], {}, warnings

    if not os.path.exists(path):
        if explicit_path:
            warnings.append(f"Backfill file not found at {path}; skipping backfill injection.")
        return [], {}, warnings

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:
        warnings.append(f"Failed to load backfill file {path}: {exc}; skipping backfill injection.")
        return [], {}, warnings

    if not isinstance(raw, list):
        warnings.append(f"Backfill file {path} is not a JSON array; skipping backfill injection.")
        return [], {}, warnings

    seq_by_fallback_key: Dict[Tuple[str, str, str, str, str, str], int] = defaultdict(int)
    injected_transactions: List[Dict[str, Any]] = []
    metadata_by_txn_id: Dict[str, Dict[str, Any]] = {}

    for row in raw:
        if not isinstance(row, dict):
            continue
        if row.get("manual_entry_price") is None:
            continue

        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue

        row_source = _normalize_source_name(row.get("source"))
        if source_filter != "all" and row_source != source_filter:
            continue

        entry_date = _to_datetime(row.get("manual_entry_date"))
        quantity = abs(_as_float(row.get("quantity"), 0.0))
        entry_price = _as_float(row.get("manual_entry_price"), 0.0)
        if entry_date is None or quantity <= 0 or entry_price <= 0:
            continue

        direction = str(row.get("direction") or "LONG").upper()
        txn_type = "SHORT" if direction == "SHORT" else "BUY"
        transaction_id = _build_backfill_transaction_id(row, seq_by_fallback_key)
        if transaction_id in existing_transaction_ids:
            continue

        fee = _as_float(row.get("manual_entry_fee"), 0.0)
        currency = str(row.get("currency") or "USD").upper()
        instrument_type = coerce_instrument_type(row.get("instrument_type"), default="equity")
        existing_transaction_ids.add(transaction_id)

        injected_transactions.append(
            {
                "type": txn_type,
                "symbol": symbol,
                "date": entry_date,
                "quantity": quantity,
                "price": entry_price,
                "fee": fee,
                "currency": currency,
                "source": row_source,
                "transaction_id": transaction_id,
                "instrument_type": instrument_type,
            }
        )
        metadata_by_txn_id[transaction_id] = {
            "symbol": symbol,
            "direction": "SHORT" if txn_type == "SHORT" else "LONG",
            "entry_date": entry_date,
            "quantity": quantity,
            "price": entry_price,
        }

    return injected_transactions, metadata_by_txn_id, warnings


def _emit_backfill_diagnostics(
    fifo_result: Any,
    fifo_transactions: List[Dict[str, Any]],
    backfill_metadata: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Emit stale/redundant duplicate diagnostics for manually backfilled entries."""
    if not backfill_metadata:
        return []

    warnings: List[str] = []
    warned_stale: set[str] = set()
    warned_redundant: set[str] = set()
    warned_wide: set[str] = set()

    provider_entry_transactions: List[Dict[str, Any]] = []
    for txn in fifo_transactions:
        txn_type = str(txn.get("type") or "").upper()
        if txn_type not in {"BUY", "SHORT"}:
            continue
        txn_id = str(txn.get("transaction_id") or "")
        if txn_id.startswith("backfill_"):
            continue
        direction = "SHORT" if txn_type == "SHORT" else "LONG"
        provider_entry_transactions.append(
            {
                "symbol": str(txn.get("symbol") or "").strip(),
                "direction": direction,
                "date": _to_datetime(txn.get("date")),
                "quantity": abs(_as_float(txn.get("quantity"), 0.0)),
                "price": _as_float(txn.get("price"), 0.0),
            }
        )

    for lots in getattr(fifo_result, "open_lots", {}).values():
        for lot in lots:
            txn_id = str(getattr(lot, "transaction_id", "") or "")
            if not txn_id.startswith("backfill_") or txn_id in warned_stale:
                continue
            symbol = str(getattr(lot, "symbol", "") or backfill_metadata.get(txn_id, {}).get("symbol") or "UNKNOWN")
            warnings.append(
                f"Backfill entry for {symbol} is unmatched open lot - provider may have supplied the original entry. "
                "Remove from backfill file."
            )
            warned_stale.add(txn_id)

    for closed_trade in getattr(fifo_result, "closed_trades", []):
        entry_id = str(getattr(closed_trade, "entry_transaction_id", "") or "")
        if not entry_id.startswith("backfill_") or entry_id not in backfill_metadata:
            continue
        meta = backfill_metadata[entry_id]
        entry_date = meta.get("entry_date")
        if entry_date is None:
            continue
        symbol = str(meta.get("symbol") or "")
        direction = str(meta.get("direction") or "LONG").upper()

        for lot_key, lots in getattr(fifo_result, "open_lots", {}).items():
            lot_symbol, _, lot_direction = lot_key
            if lot_symbol != symbol or lot_direction != direction:
                continue
            for lot in lots:
                lot_txn_id = str(getattr(lot, "transaction_id", "") or "")
                if lot_txn_id.startswith("backfill_"):
                    continue
                lot_entry_date = _to_datetime(getattr(lot, "entry_date", None))
                if lot_entry_date is None:
                    continue
                if abs((lot_entry_date.date() - entry_date.date()).days) <= 3 and entry_id not in warned_redundant:
                    warnings.append(
                        f"Backfill entry for {symbol} on {entry_date.date().isoformat()} may be redundant: "
                        "provider open lot exists within +/-3 days. Verify and remove backfill if redundant."
                    )
                    warned_redundant.add(entry_id)
                if entry_id in warned_redundant:
                    break
            if entry_id in warned_redundant:
                break

    for entry_id, meta in backfill_metadata.items():
        entry_date = meta.get("entry_date")
        symbol = str(meta.get("symbol") or "")
        direction = str(meta.get("direction") or "LONG").upper()
        quantity = _as_float(meta.get("quantity"), 0.0)
        price = _as_float(meta.get("price"), 0.0)
        if entry_date is None or quantity <= 0 or price <= 0:
            continue

        for provider_entry in provider_entry_transactions:
            if provider_entry.get("symbol") != symbol or provider_entry.get("direction") != direction:
                continue
            provider_date = provider_entry.get("date")
            provider_qty = _as_float(provider_entry.get("quantity"), 0.0)
            provider_price = _as_float(provider_entry.get("price"), 0.0)
            if provider_date is None or provider_qty <= 0 or provider_price <= 0:
                continue

            day_delta = abs((provider_date.date() - entry_date.date()).days)
            qty_match = abs(provider_qty - quantity) <= quantity * 0.05
            price_match = abs(provider_price - price) <= price * 0.10
            if day_delta <= 14 and qty_match and price_match and entry_id not in warned_wide:
                warnings.append(
                    f"INFO: Possible duplicate: backfill {symbol} matches provider entry on "
                    f"{provider_date.date().isoformat()}. Verify and remove backfill if redundant."
                )
                warned_wide.add(entry_id)
                break

    return warnings


def _compute_realized_pnl_usd(
    closed_trades: Iterable[Any],
    fx_cache: Dict[str, pd.Series],
) -> float:
    """Compute closed-trade realized P&L in USD using per-leg FX rates."""
    total = 0.0
    for trade in closed_trades:
        has_leg_fields = all(
            hasattr(trade, attr)
            for attr in ("entry_date", "exit_date", "entry_price", "exit_price", "quantity", "entry_fee", "exit_fee")
        )
        if not has_leg_fields:
            total += _as_float(getattr(trade, "pnl_dollars", 0.0), 0.0)
            continue

        direction = str(getattr(trade, "direction", "LONG") or "LONG").upper()
        currency = str(getattr(trade, "currency", "USD") or "USD").upper()
        entry_date = _to_datetime(getattr(trade, "entry_date", None))
        exit_date = _to_datetime(getattr(trade, "exit_date", None))
        if entry_date is None or exit_date is None:
            total += _as_float(getattr(trade, "pnl_dollars", 0.0), 0.0)
            continue

        qty = abs(_as_float(getattr(trade, "quantity", 0.0), 0.0))
        entry_price = _as_float(getattr(trade, "entry_price", 0.0), 0.0)
        exit_price = _as_float(getattr(trade, "exit_price", 0.0), 0.0)
        entry_fee = _as_float(getattr(trade, "entry_fee", 0.0), 0.0)
        exit_fee = _as_float(getattr(trade, "exit_fee", 0.0), 0.0)
        entry_fx = _event_fx_rate(currency, entry_date, fx_cache)
        exit_fx = _event_fx_rate(currency, exit_date, fx_cache)

        entry_fee_usd = entry_fee * entry_fx
        exit_fee_usd = exit_fee * exit_fx

        if direction == "SHORT":
            entry_proceeds_usd = entry_price * qty * entry_fx
            exit_cost_usd = exit_price * qty * exit_fx
            total += entry_proceeds_usd - exit_cost_usd - entry_fee_usd - exit_fee_usd
        else:
            entry_cost_usd = entry_price * qty * entry_fx
            exit_proceeds_usd = exit_price * qty * exit_fx
            total += exit_proceeds_usd - entry_cost_usd - entry_fee_usd - exit_fee_usd

    return float(total)


def _summarize_income_usd(
    income_with_currency: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
) -> Dict[str, float]:
    """Aggregate income fields in USD using event-date FX normalization."""
    by_month_usd: Dict[str, float] = defaultdict(float)
    by_institution: Dict[str, Dict[str, float]] = defaultdict(lambda: {"dividends": 0.0, "interest": 0.0, "total": 0.0})
    total_dividends_usd = 0.0
    total_interest_usd = 0.0

    for event in income_with_currency:
        when = _to_datetime(event.get("date"))
        if when is None:
            continue
        amount = _as_float(event.get("amount"), 0.0)
        currency = str(event.get("currency") or "USD").upper()
        amount_usd = amount * _event_fx_rate(currency, when, fx_cache)
        month_key = when.strftime("%Y-%m")
        by_month_usd[month_key] += amount_usd

        income_type = str(event.get("income_type") or "").lower()
        inst_key = str(event.get("institution") or "unknown").strip() or "unknown"
        if income_type == "dividend":
            total_dividends_usd += amount_usd
            by_institution[inst_key]["dividends"] += amount_usd
        else:
            total_interest_usd += amount_usd
            by_institution[inst_key]["interest"] += amount_usd
        by_institution[inst_key]["total"] += amount_usd

    total_income_usd = total_dividends_usd + total_interest_usd
    months = sorted(by_month_usd.keys())
    if len(months) >= 3:
        current_monthly_usd = sum(by_month_usd[m] for m in months[-3:]) / 3.0
    else:
        current_monthly_usd = total_income_usd / max(len(months), 1)

    # Round by_institution values for clean output
    by_institution_rounded = {
        k: {sub_k: round(sub_v, 2) for sub_k, sub_v in v.items()}
        for k, v in sorted(by_institution.items())
    }

    return {
        "total": float(total_income_usd),
        "dividends": float(total_dividends_usd),
        "interest": float(total_interest_usd),
        "by_institution": by_institution_rounded,
        "current_monthly_rate": float(current_monthly_usd),
        "projected_annual": float(current_monthly_usd * 12.0),
    }


def analyze_realized_performance(
    positions: "PositionResult",
    user_email: str,
    benchmark_ticker: str = "SPY",
    source: str = "all",
    institution: Optional[str] = None,
    account: Optional[str] = None,
    include_series: bool = False,
    backfill_path: Optional[str] = None,
    price_registry: ProviderRegistry | None = None,
) -> Union["RealizedPerformanceResult", Dict[str, Any]]:
    """Compute realized performance metrics and realized metadata from transactions.

    Called by:
    - Service/API orchestration paths that return realized performance payloads.

    Calls into:
    - ``fetch_transactions_for_source`` for transaction retrieval.
    - ``extract_provider_flow_events`` for provider-authoritative cash flows.
    - ``TradingAnalyzer`` for normalization/FIFO preprocessing.
    - ``compute_performance_metrics`` for shared metric computation.

    Source and authority semantics:
    - ``source=all`` allows orchestrated multi-provider fetch and provider-flow
      coverage checks.
    - Non-``all`` source constrains transaction fetch path and uses source-scoped
      holdings attribution for coverage/synthetic diagnostics.
    - Provider flow events are used directly when configured and sufficiently
      covered; otherwise the path falls back to inferred cash-flow reconstruction.

    Debug pointer:
    - If realized returns look wrong, inspect ``warnings`` and
      ``realized_metadata.provider_flow_coverage`` first.
    """
    warnings: List[str] = []

    try:
        source = source.lower().strip()
        price_registry = price_registry or _build_default_price_registry()
        institution = (institution or "").strip() or None
        account = (account or "").strip() or None
        if source not in {"all", "snaptrade", "plaid", "ibkr_flex", "schwab"}:
            return {
                "status": "error",
                "message": "source must be one of: all, snaptrade, plaid, ibkr_flex, schwab",
            }

        if source != "all":
            warnings.append(
                "source filter applies to transactions and holdings are source-scoped when attribution is available."
            )
            scoped_holdings = _build_source_scoped_holdings(
                positions,
                source,
                warnings,
                institution=institution,
                account=account,
            )
            current_positions = scoped_holdings.current_positions
            fmp_ticker_map = dict(scoped_holdings.fmp_ticker_map)
            source_holding_symbols = scoped_holdings.source_holding_symbols
            cross_source_holding_leakage_symbols = scoped_holdings.cross_source_holding_leakage_symbols
            holdings_scope = scoped_holdings.holdings_scope
        else:
            current_positions, fmp_ticker_map, build_warnings = _build_current_positions(
                positions,
                institution=institution,
                account=account,
            )
            warnings.extend(build_warnings)
            source_holding_symbols = sorted(current_positions.keys())
            cross_source_holding_leakage_symbols: List[str] = []
            holdings_scope = "institution_scoped" if institution else "consolidated"

        if institution:
            fetch_result = fetch_transactions_for_source(
                user_email=user_email,
                source=source,
                institution=institution,
            )
        else:
            fetch_result = fetch_transactions_for_source(user_email=user_email, source=source)
        payload = getattr(fetch_result, "payload", fetch_result)
        fetch_metadata_rows = list(getattr(fetch_result, "fetch_metadata", []) or [])
        warnings.extend(
            _build_fetch_metadata_warnings(
                fetch_metadata_rows,
                source=source,
                institution=institution,
            )
        )
        fetch_errors: Dict[str, str] = {}
        for row in fetch_metadata_rows:
            err = row.get("fetch_error")
            if err:
                provider = row.get("provider", "unknown")
                if provider not in fetch_errors:
                    fetch_errors[provider] = str(err)
        schwab_security_lookup = get_schwab_security_lookup(
            user_email=user_email,
            source=source,
            payload=payload,
        )
        provider_first_mode = bool(REALIZED_USE_PROVIDER_FLOWS)
        enabled_provider_flow_sources = {
            str(token or "").strip().lower()
            for token in REALIZED_PROVIDER_FLOW_SOURCES
            if str(token or "").strip()
        }
        provider_flow_events_raw: List[Dict[str, Any]] = []
        provider_fetch_metadata: List[Dict[str, Any]] = []
        dedup_diagnostics: Dict[str, Any] = {}
        provider_flow_coverage: Dict[str, Dict[str, Any]] = {}
        flow_fallback_reasons: List[str] = []
        flow_source_breakdown = {
            "provider_authoritative_applied": 0,
            "provider_authoritative_available": 0,
            "provider_diagnostics_only": 0,
            "inferred": 0,
        }

        if provider_first_mode:
            try:
                provider_flow_events_raw, provider_fetch_metadata = extract_provider_flow_events(fetch_result)
            except Exception as exc:
                warnings.append(
                    f"Provider-flow extraction unavailable; using inference-only cash flow reconstruction: {exc}"
                )
                provider_first_mode = False

        analyzer = TradingAnalyzer(
            plaid_securities=payload.get("plaid_securities", []),
            plaid_transactions=payload.get("plaid_transactions", []),
            snaptrade_activities=payload.get("snaptrade_activities", []),
            ibkr_flex_trades=payload.get("ibkr_flex_trades"),
            ibkr_flex_cash_rows=payload.get("ibkr_flex_cash_rows"),
            schwab_transactions=payload.get("schwab_transactions", []),
            schwab_security_lookup=schwab_security_lookup,
            use_fifo=True,
            account_filter=account,
        )

        fifo_transactions = list(analyzer.fifo_transactions)
        backfill_metadata: Dict[str, Dict[str, Any]] = {}
        effective_backfill_path = backfill_path if backfill_path is not None else BACKFILL_FILE_PATH
        existing_transaction_ids = {
            str(txn.get("transaction_id")).strip()
            for txn in fifo_transactions
            if str(txn.get("transaction_id") or "").strip()
        }
        backfill_transactions, backfill_metadata, backfill_warnings = _build_backfill_entry_transactions(
            backfill_path=effective_backfill_path,
            source_filter=source,
            existing_transaction_ids=existing_transaction_ids,
            explicit_path=backfill_path is not None,
        )
        warnings.extend(backfill_warnings)
        if backfill_transactions:
            fifo_transactions = backfill_transactions + fifo_transactions
            warnings.append(
                f"Injected {len(backfill_transactions)} backfill entry transaction(s) from {effective_backfill_path}."
            )
        if institution:
            pre_count = len(fifo_transactions)
            fifo_transactions = [
                txn
                for txn in fifo_transactions
                if match_institution(txn.get("_institution") or "", institution)
            ]
            warnings.append(
                f"Institution filter '{institution}': {len(fifo_transactions)}/{pre_count} transactions matched."
            )
        if account:
            pre_count = len(fifo_transactions)
            fifo_transactions = [
                txn for txn in fifo_transactions
                if _match_account(txn, account)
            ]
            warnings.append(
                f"Account filter '{account}': {len(fifo_transactions)}/{pre_count} transactions matched."
            )
        fifo_transactions.sort(key=lambda t: _to_datetime(t.get("date")) or datetime.min)

        futures_map = get_ibkr_futures_fmp_map()
        equity_symbols = {
            str(txn.get("symbol") or "").strip().upper()
            for txn in fifo_transactions
            if _infer_instrument_type_from_transaction(txn) == "equity" and txn.get("symbol")
        }
        mapped_futures_for_fmp: set[str] = set()
        for txn in fifo_transactions:
            sym = str(txn.get("symbol") or "").strip().upper()
            if (
                _infer_instrument_type_from_transaction(txn) == "futures"
                and sym in futures_map
                and sym not in mapped_futures_for_fmp
            ):
                mapped_futures_for_fmp.add(sym)
                if sym in fmp_ticker_map or sym in equity_symbols:
                    warnings.append(
                        f"Futures symbol {sym} collides with equity ticker; "
                        "futures pricing skipped (equity mapping preserved)."
                    )
                else:
                    fmp_ticker_map[sym] = futures_map[sym]

        if not fifo_transactions and not current_positions:
            return {
                "status": "error",
                "message": "No transaction history and no current positions available for realized performance analysis.",
            }

        now = datetime.now(UTC).replace(tzinfo=None)
        if fifo_transactions:
            inception_from_transactions = min(
                _to_datetime(t.get("date"))
                for t in fifo_transactions
                if _to_datetime(t.get("date")) is not None
            )
            inception_from_transactions = inception_from_transactions or (now - timedelta(days=365))
        else:
            inception_from_transactions = now - timedelta(days=365)
            warnings.append(
                "No transaction history found; using 12-month synthetic inception for current holdings."
            )

        income_with_currency = _income_with_currency(analyzer, fifo_transactions, current_positions)
        if institution:
            income_with_currency = [
                inc
                for inc in income_with_currency
                if match_institution(inc.get("institution") or "", institution)
            ]
        if account:
            income_with_currency = [
                inc
                for inc in income_with_currency
                if _match_account(inc, account)
            ]

        provider_flow_events: List[Dict[str, Any]] = []
        first_authoritative_provider_flow_date: datetime | None = None
        if provider_first_mode:
            provider_flow_events = [
                row
                for row in provider_flow_events_raw
                if str(row.get("provider") or "").strip().lower() in enabled_provider_flow_sources
            ]
            provider_fetch_metadata = [
                row
                for row in provider_fetch_metadata
                if str(row.get("provider") or "").strip().lower() in enabled_provider_flow_sources
            ]

            if institution:
                provider_flow_events = [
                    row
                    for row in provider_flow_events
                    if match_institution(str(row.get("institution") or ""), institution)
                ]
                provider_fetch_metadata = [
                    row
                    for row in provider_fetch_metadata
                    if match_institution(str(row.get("institution") or ""), institution)
                ]
            if account:
                provider_flow_events = [
                    row
                    for row in provider_flow_events
                    if _match_account(row, account)
                ]
                provider_fetch_metadata = [
                    row
                    for row in provider_fetch_metadata
                    if _match_account(row, account)
                ]

            provider_flow_events, dedup_diagnostics = _deduplicate_provider_flow_events(provider_flow_events)
            provider_flow_coverage, flow_fallback_reasons = _build_provider_flow_authority(
                provider_flow_events,
                provider_fetch_metadata,
                require_coverage=bool(REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE),
            )

            for event in provider_flow_events:
                when = _to_datetime(event.get("timestamp") or event.get("date"))
                if when is None:
                    continue
                is_authoritative = _is_authoritative_slice(
                    provider_flow_coverage,
                    provider=event.get("provider"),
                    institution=event.get("institution"),
                    account_id=event.get("account_id"),
                    provider_account_ref=event.get("provider_account_ref"),
                    account_name=event.get("account_name"),
                    event_date=when,
                )
                if not is_authoritative:
                    continue
                if first_authoritative_provider_flow_date is None or when < first_authoritative_provider_flow_date:
                    first_authoritative_provider_flow_date = when

        inception_candidates = [inception_from_transactions]
        first_income_date = min(
            (
                _to_datetime(row.get("date"))
                for row in income_with_currency
                if _to_datetime(row.get("date")) is not None
            ),
            default=None,
        )
        if first_income_date is not None:
            inception_candidates.append(first_income_date)
        if provider_first_mode and first_authoritative_provider_flow_date is not None:
            inception_candidates.append(first_authoritative_provider_flow_date)

        inception_date = min(inception_candidates)

        latest_event_date = inception_date
        for txn in fifo_transactions:
            dt = _to_datetime(txn.get("date"))
            if dt and dt > latest_event_date:
                latest_event_date = dt
        for inc in income_with_currency:
            dt = _to_datetime(inc.get("date"))
            if dt and dt > latest_event_date:
                latest_event_date = dt
        for event in provider_flow_events:
            dt = _to_datetime(event.get("timestamp") or event.get("date"))
            if dt and dt > latest_event_date:
                latest_event_date = dt
        end_date = max(now, latest_event_date)

        currencies = {"USD"}
        for pos in current_positions.values():
            currencies.add(str(pos.get("currency") or "USD").upper())
        for txn in fifo_transactions:
            currencies.add(str(txn.get("currency") or "USD").upper())
        for inc in income_with_currency:
            currencies.add(str(inc.get("currency") or "USD").upper())
        for event in provider_flow_events:
            currencies.add(str(event.get("currency") or "USD").upper())
        fx_cache = _build_fx_cache(
            currencies=currencies,
            inception_date=inception_date,
            end_date=end_date,
            warnings=warnings,
        )

        # Delta-gap analysis: identify symbols where short inference should be
        # suppressed because there are missing buys from before the txn window.
        visible_delta: Dict[str, float] = defaultdict(float)
        for txn in fifo_transactions:
            sym = str(txn.get("symbol", "")).strip()
            qty = abs(_as_float(txn.get("quantity"), 0.0))
            txn_type = str(txn.get("type", "")).upper()
            if txn_type in ("BUY", "COVER"):
                visible_delta[sym] += qty
            elif txn_type in ("SELL", "SHORT"):
                visible_delta[sym] -= qty

        no_infer_symbols: set[str] = set()
        for sym, delta in visible_delta.items():
            holdings = _as_float(current_positions.get(sym, {}).get("shares"), 0.0)
            gap = holdings - delta
            if gap > 0.01:  # missing buys → don't infer shorts
                no_infer_symbols.add(sym)

        first_exit_without_opening = _detect_first_exit_without_opening(fifo_transactions)
        if first_exit_without_opening:
            preview = ", ".join(item["symbol"] for item in first_exit_without_opening[:5])
            if len(first_exit_without_opening) > 5:
                preview = f"{preview}, ..."
            warnings.append(
                f"Detected {len(first_exit_without_opening)} symbol(s) where the first observed transaction "
                f"is an exit without an opening ({preview}). Entry history is likely truncated; backfill recommended."
            )

        # Two-pass FIFO for back-solved cost basis:
        # Pass 1: get observed open lots (no seeded lots).
        probe_result = FIFOMatcher(
            no_infer_symbols=no_infer_symbols,
        ).process_transactions(fifo_transactions)

        # Compute seeded lots from broker cost basis (FX-aware for non-USD symbols).
        seeded_lots, seed_warnings = _build_seed_open_lots(
            fifo_transactions=fifo_transactions,
            current_positions=current_positions,
            observed_open_lots=probe_result.open_lots,
            inception_date=inception_date,
            fx_cache=fx_cache,
        )
        warnings.extend(seed_warnings)

        # Pass 2: re-run with seeded lots (or reuse pass 1 if nothing to seed).
        if seeded_lots:
            fifo_result = FIFOMatcher(
                no_infer_symbols=no_infer_symbols,
            ).process_transactions(fifo_transactions, initial_open_lots=seeded_lots)
        else:
            fifo_result = probe_result

        warnings.extend(
            _emit_backfill_diagnostics(
                fifo_result=fifo_result,
                fifo_transactions=fifo_transactions,
                backfill_metadata=backfill_metadata,
            )
        )
        inferred_shorts = sorted(
            str(sym).strip()
            for sym in getattr(fifo_result, "inferred_shorts", set())
            if str(sym).strip()
        )

        position_timeline, synthetic_positions, synthetic_entries, instrument_meta, timeline_warnings = build_position_timeline(
            fifo_transactions=fifo_transactions,
            current_positions=current_positions,
            inception_date=inception_date,
            incomplete_trades=fifo_result.incomplete_trades,
            fmp_ticker_map=fmp_ticker_map or None,
        )
        warnings.extend(timeline_warnings)

        month_ends = _month_end_range(inception_date, end_date)

        tickers = sorted({key[0] for key in position_timeline.keys()})
        ticker_instrument_types: Dict[str, set[str]] = defaultdict(set)
        ticker_contract_identities: Dict[str, Dict[str, Any]] = {}
        contract_identity_conflicts: set[str] = set()
        for key in position_timeline.keys():
            meta = instrument_meta.get(key) or {}
            raw_instrument_type = str(meta.get("instrument_type") or "").strip().lower()
            if raw_instrument_type in {"fx", "forex"}:
                ticker_instrument_types[key[0]].add("fx")
            else:
                ticker_instrument_types[key[0]].add(
                    coerce_instrument_type(meta.get("instrument_type"), default="equity")
                )
            contract_identity = meta.get("contract_identity")
            if isinstance(contract_identity, dict) and contract_identity:
                existing = ticker_contract_identities.get(key[0])
                if existing is None:
                    ticker_contract_identities[key[0]] = dict(contract_identity)
                elif existing != contract_identity and key[0] not in contract_identity_conflicts:
                    warnings.append(
                        f"Contract identity conflict for {key[0]}; using first identity for IBKR pricing."
                    )
                    contract_identity_conflicts.add(key[0])

        routing_priority = {
            "futures": 0,
            "fx": 1,
            "bond": 2,
            "option": 3,
            "equity": 4,
            "fx_artifact": 5,
            "unknown": 6,
        }

        # Fetch prices starting 2 months before inception so that the strict
        # backward-only price lookup in _create_synthetic_cash_events has
        # at least one prior month-end price available at the inception date.
        price_fetch_start = inception_date - timedelta(days=62)
        price_cache: Dict[str, pd.Series] = {}
        unpriceable_symbols: set[str] = set()
        ibkr_priced_symbols: Dict[str, set[str]] = defaultdict(set)
        unpriceable_reason_counts: Counter[str] = Counter()
        unpriceable_reasons: Dict[str, str] = {}
        for ticker in tickers:
            raw_types = ticker_instrument_types.get(ticker, {"equity"})
            instrument_type = min(raw_types, key=lambda t: routing_priority.get(t, 99))
            contract_identity = ticker_contract_identities.get(ticker)
            if len(raw_types) > 1:
                warnings.append(
                    f"Mixed instrument types for {ticker}: {sorted(raw_types)}; using {instrument_type} for pricing."
                )

            norm = pd.Series(dtype=float)
            unpriceable_reason = "no_price_data"
            if instrument_type in {"fx_artifact", "unknown"}:
                warnings.append(
                    f"Skipping pricing for {ticker}: instrument_type={instrument_type} should have been filtered upstream."
                )
                unpriceable_reason = f"filtered_{instrument_type}"
            elif instrument_type == "option":
                # Check if option still has open lots — if so, prefer IBKR fallback
                # over stale FIFO terminal price. Timeline events are deltas
                # (BUY=+qty, SELL=-qty), so we must sum to get cumulative position.
                option_still_open = False
                for tl_key, tl_events in position_timeline.items():
                    if tl_key[0] == ticker and tl_events:
                        cumulative_qty = sum(float(ev[1]) for ev in tl_events)
                        if abs(cumulative_qty) > 1e-9:
                            option_still_open = True
                            break

                fifo_terminal = _option_fifo_terminal_series(ticker, fifo_transactions, end_date)
                has_fifo_terminal = not fifo_terminal.empty and not fifo_terminal.dropna().empty
                option_expiry = _option_expiry_datetime(ticker, contract_identity)
                end_ts = pd.Timestamp(end_date).to_pydatetime().replace(tzinfo=None)
                option_expired = option_expiry is not None and option_expiry <= end_ts
                current_shares = _as_float((current_positions.get(ticker) or {}).get("shares"), 0.0)
                flat_current_holdings = abs(current_shares) <= 1e-9

                if has_fifo_terminal and (
                    (not option_still_open)
                    or (option_expired and flat_current_holdings)
                ):
                    norm = _series_from_cache(fifo_terminal)
                    if option_still_open and option_expired and flat_current_holdings and option_expiry is not None:
                        warnings.append(
                            f"Priced expired option {ticker} using FIFO close-price terminal heuristic "
                            f"(expiry {option_expiry.date().isoformat()}, current holdings flat)."
                        )
                    else:
                        warnings.append(
                            f"Priced option {ticker} using FIFO close-price terminal heuristic."
                        )
                else:
                    price_result = _fetch_price_from_chain(
                        price_registry.get_price_chain("option"),
                        ticker,
                        price_fetch_start,
                        end_date,
                        instrument_type="option",
                        contract_identity=contract_identity,
                        fmp_ticker_map=fmp_ticker_map or None,
                    )
                    norm = _series_from_cache(price_result.series)
                    chain_reason = _emit_pricing_diagnostics(
                        ticker=ticker,
                        instrument_type="option",
                        contract_identity=contract_identity,
                        result=price_result,
                        warnings=warnings,
                        ibkr_priced_symbols=ibkr_priced_symbols,
                    )
                    if norm.empty or norm.dropna().empty:
                        unpriceable_reason = chain_reason
            else:
                chain = price_registry.get_price_chain(instrument_type)
                if instrument_type == "bond":
                    has_ibkr = any(provider.provider_name == "ibkr" for provider in chain)
                    con_id = None
                    if isinstance(contract_identity, dict):
                        con_id = contract_identity.get("con_id")
                    if has_ibkr and con_id in (None, ""):
                        warnings.append(
                            f"No contract_identity.con_id for bond {ticker}; skipping IBKR bond pricing."
                        )
                        unpriceable_reason = "bond_missing_con_id"
                    else:
                        price_result = _fetch_price_from_chain(
                            chain,
                            ticker,
                            price_fetch_start,
                            end_date,
                            instrument_type=instrument_type,
                            contract_identity=contract_identity,
                            fmp_ticker_map=fmp_ticker_map or None,
                        )
                        norm = _series_from_cache(price_result.series)
                        chain_reason = _emit_pricing_diagnostics(
                            ticker=ticker,
                            instrument_type=instrument_type,
                            contract_identity=contract_identity,
                            result=price_result,
                            warnings=warnings,
                            ibkr_priced_symbols=ibkr_priced_symbols,
                        )
                        if norm.empty or norm.dropna().empty:
                            unpriceable_reason = chain_reason
                else:
                    price_result = _fetch_price_from_chain(
                        chain,
                        ticker,
                        price_fetch_start,
                        end_date,
                        instrument_type=instrument_type,
                        contract_identity=contract_identity,
                        fmp_ticker_map=fmp_ticker_map or None,
                    )
                    norm = _series_from_cache(price_result.series)
                    chain_reason = _emit_pricing_diagnostics(
                        ticker=ticker,
                        instrument_type=instrument_type,
                        contract_identity=contract_identity,
                        result=price_result,
                        warnings=warnings,
                        ibkr_priced_symbols=ibkr_priced_symbols,
                    )
                    if norm.empty or norm.dropna().empty:
                        unpriceable_reason = chain_reason
                        if instrument_type == "equity":
                            unpriceable_reason = "equity_no_data"

            if norm.empty or norm.dropna().empty:
                warnings.append(f"No monthly prices found for {ticker}; valuing as 0 when unavailable.")
                unpriceable_symbols.add(ticker)
                unpriceable_reasons[ticker] = unpriceable_reason
                unpriceable_reason_counts[unpriceable_reason] += 1
            price_cache[ticker] = norm

        unpriceable_symbols_sorted = sorted(unpriceable_symbols)
        data_quality_flags: List[Dict[str, Any]] = []
        if unpriceable_symbols_sorted:
            preview = ", ".join(unpriceable_symbols_sorted[:5])
            if len(unpriceable_symbols_sorted) > 5:
                preview = f"{preview}, ..."
            warnings.append(
                f"HIGH DATA QUALITY FLAG: {len(unpriceable_symbols_sorted)} symbol(s) could not be priced "
                f"({preview}). These symbols are valued at 0 in NAV and unrealized P&L."
            )
            data_quality_flags.append(
                {
                    "code": "UNPRICEABLE_SYMBOLS",
                    "severity": "high",
                    "count": len(unpriceable_symbols_sorted),
                    "symbols": unpriceable_symbols_sorted,
                }
            )

        if first_exit_without_opening:
            data_quality_flags.append(
                {
                    "code": "FIRST_TRANSACTION_EXIT",
                    "severity": "medium",
                    "count": len(first_exit_without_opening),
                    "details": first_exit_without_opening,
                }
            )

        timeline_currencies = {
            str(ccy or "USD").upper()
            for _, ccy, _ in position_timeline.keys()
        }
        missing_fx = sorted(ccy for ccy in timeline_currencies if ccy not in fx_cache)
        if missing_fx:
            fx_cache.update(
                _build_fx_cache(
                    currencies=missing_fx,
                    inception_date=inception_date,
                    end_date=end_date,
                    warnings=warnings,
                )
            )

        synthetic_cash_events, synth_cash_warnings = _create_synthetic_cash_events(
            synthetic_entries=synthetic_entries,
            price_cache=price_cache,
            fx_cache=fx_cache,
            min_notional_usd=_as_float(
                DATA_QUALITY_THRESHOLDS.get("synthetic_cash_min_notional_usd", 1.0),
                1.0,
            ),
        )
        warnings.extend(synth_cash_warnings)
        if synthetic_cash_events:
            warnings.append(
                f"Detected {len(synthetic_cash_events)} synthetic position(s) with estimated cash impact. "
                "Synthetic positions are valued in NAV but excluded from cash replay to avoid "
                "inflating the Modified Dietz denominator."
            )
        transactions_for_cash = fifo_transactions

        def _compose_cash_and_external_flows(
            branch_transactions: List[Dict[str, Any]],
        ) -> Tuple[
            List[Tuple[datetime, float]],
            List[Tuple[datetime, float]],
            Dict[str, int],
            Dict[str, Any],
            Dict[str, Any],
        ]:
            def _window(dates: List[datetime]) -> Dict[str, Optional[str]]:
                valid_dates = sorted(dt for dt in dates if dt is not None)
                if not valid_dates:
                    return {"start": None, "end": None}
                return {
                    "start": valid_dates[0].isoformat(),
                    "end": valid_dates[-1].isoformat(),
                }

            def _snapshots_to_deltas(snapshots: List[Tuple[datetime, float]]) -> List[Tuple[datetime, float]]:
                deltas: List[Tuple[datetime, float]] = []
                prior_cash = 0.0
                for when, cash_value in sorted(snapshots, key=lambda row: row[0]):
                    cash_numeric = _as_float(cash_value, 0.0)
                    deltas.append((when, cash_numeric - prior_cash))
                    prior_cash = cash_numeric
                return deltas

            replay_diag: Dict[str, Any] = {
                "futures_txn_count_replayed": 0,
                "futures_notional_suppressed_usd": 0.0,
                "futures_fee_cash_impact_usd": 0.0,
                "futures_unknown_action_count": 0,
                "futures_missing_fx_count": 0,
                "income_flow_overlap_dropped_count": 0,
                "income_flow_overlap_dropped_net_usd": 0.0,
                "income_flow_overlap_dropped_by_provider": {},
                "income_flow_overlap_candidate_count": 0,
                "income_flow_overlap_alias_mismatch_count": 0,
                "income_flow_overlap_alias_mismatch_samples": [],
            }

            def _finalize_replay_diag() -> Dict[str, Any]:
                return {
                    "futures_txn_count_replayed": int(_as_float(replay_diag.get("futures_txn_count_replayed"), 0.0)),
                    "futures_notional_suppressed_usd": round(
                        _as_float(replay_diag.get("futures_notional_suppressed_usd"), 0.0),
                        2,
                    ),
                    "futures_fee_cash_impact_usd": round(
                        _as_float(replay_diag.get("futures_fee_cash_impact_usd"), 0.0),
                        2,
                    ),
                    "futures_unknown_action_count": int(_as_float(replay_diag.get("futures_unknown_action_count"), 0.0)),
                    "futures_missing_fx_count": int(_as_float(replay_diag.get("futures_missing_fx_count"), 0.0)),
                    "income_flow_overlap_dropped_count": int(
                        _as_float(replay_diag.get("income_flow_overlap_dropped_count"), 0.0)
                    ),
                    "income_flow_overlap_dropped_net_usd": round(
                        _as_float(replay_diag.get("income_flow_overlap_dropped_net_usd"), 0.0),
                        2,
                    ),
                    "income_flow_overlap_dropped_by_provider": dict(
                        sorted((replay_diag.get("income_flow_overlap_dropped_by_provider") or {}).items())
                    ),
                    "income_flow_overlap_candidate_count": int(
                        _as_float(replay_diag.get("income_flow_overlap_candidate_count"), 0.0)
                    ),
                    "income_flow_overlap_alias_mismatch_count": int(
                        _as_float(replay_diag.get("income_flow_overlap_alias_mismatch_count"), 0.0)
                    ),
                    "income_flow_overlap_alias_mismatch_samples": list(
                        replay_diag.get("income_flow_overlap_alias_mismatch_samples") or []
                    ),
                }

            if not provider_first_mode:
                cash_snapshots_local, external_flows_local = derive_cash_and_external_flows(
                    fifo_transactions=branch_transactions,
                    income_with_currency=income_with_currency,
                    fx_cache=fx_cache,
                    warnings=warnings,
                    replay_diagnostics=replay_diag,
                )
                inferred_dates = [when for when, _ in external_flows_local]
                inferred_net_usd = float(sum(_as_float(amount, 0.0) for _, amount in external_flows_local))
                return cash_snapshots_local, external_flows_local, {
                    "provider_authoritative_applied": 0,
                    "provider_authoritative_available": 0,
                    "provider_diagnostics_only": 0,
                    "inferred": len(external_flows_local),
                    }, {
                        "mode": "inference_only",
                        "fallback_slices_present": False,
                        "replayed_fallback_provider_activity": False,
                        "total_inferred_event_count": len(external_flows_local),
                        "total_inferred_net_usd": round(inferred_net_usd, 2),
                        "inferred_event_window": _window(inferred_dates),
                        "by_provider": {},
                        "by_slice": {},
                }, _finalize_replay_diag()

            authoritative_events: List[Dict[str, Any]] = []
            authoritative_available_count = 0
            diagnostics_only_count = 0

            for event in provider_flow_events:
                provider = _normalize_source_name(event.get("provider"))
                if provider not in enabled_provider_flow_sources:
                    continue

                event_date = _to_datetime(event.get("timestamp") or event.get("date"))
                if event_date is None:
                    continue

                is_authoritative = _is_authoritative_slice(
                    provider_flow_coverage,
                    provider=provider,
                    institution=event.get("institution"),
                    account_id=event.get("account_id"),
                    provider_account_ref=event.get("provider_account_ref"),
                    account_name=event.get("account_name"),
                    event_date=event_date,
                )
                if not is_authoritative:
                    diagnostics_only_count += 1
                    continue

                authoritative_available_count += 1
                amount = _as_float(event.get("amount"), 0.0)
                if amount == 0:
                    # Keep zero-amount authoritative events visible in diagnostics.
                    diagnostics_only_count += 1
                    continue

                authoritative_events.append(event)

            if not authoritative_events:
                has_deterministic_no_flow_authority = any(
                    bool(row.get("authoritative")) and bool(row.get("deterministic_no_flow"))
                    for row in provider_flow_coverage.values()
                )
                if has_deterministic_no_flow_authority and not flow_fallback_reasons:
                    cash_no_inference, external_no_inference = derive_cash_and_external_flows(
                        fifo_transactions=branch_transactions,
                        income_with_currency=income_with_currency,
                        fx_cache=fx_cache,
                        force_disable_inference=True,
                        warnings=warnings,
                        replay_diagnostics=replay_diag,
                    )
                    return cash_no_inference, external_no_inference, {
                        "provider_authoritative_applied": 0,
                        "provider_authoritative_available": authoritative_available_count,
                        "provider_diagnostics_only": diagnostics_only_count,
                        "inferred": 0,
                    }, {
                        "mode": "provider_authoritative_deterministic_no_flow_no_events",
                        "fallback_slices_present": False,
                        "replayed_fallback_provider_activity": False,
                        "total_inferred_event_count": 0,
                        "total_inferred_net_usd": 0.0,
                        "inferred_event_window": {"start": None, "end": None},
                        "by_provider": {},
                        "by_slice": {},
                    }, _finalize_replay_diag()

                fallback_cash, fallback_external = derive_cash_and_external_flows(
                    fifo_transactions=branch_transactions,
                    income_with_currency=income_with_currency,
                    fx_cache=fx_cache,
                    warnings=warnings,
                    replay_diagnostics=replay_diag,
                )
                inferred_dates = [when for when, _ in fallback_external]
                inferred_net_usd = float(sum(_as_float(amount, 0.0) for _, amount in fallback_external))
                return fallback_cash, fallback_external, {
                    "provider_authoritative_applied": 0,
                    "provider_authoritative_available": authoritative_available_count,
                    "provider_diagnostics_only": diagnostics_only_count,
                    "inferred": len(fallback_external),
                }, {
                    "mode": "provider_no_authoritative_events",
                    "fallback_slices_present": bool(flow_fallback_reasons),
                    "replayed_fallback_provider_activity": False,
                    "total_inferred_event_count": len(fallback_external),
                    "total_inferred_net_usd": round(inferred_net_usd, 2),
                    "inferred_event_window": _window(inferred_dates),
                    "by_provider": {},
                    "by_slice": {},
                }, _finalize_replay_diag()

            has_fallback_slices = bool(flow_fallback_reasons)
            if not has_fallback_slices:
                composed_cash, composed_external = derive_cash_and_external_flows(
                    fifo_transactions=branch_transactions,
                    income_with_currency=income_with_currency,
                    fx_cache=fx_cache,
                    provider_flow_events=authoritative_events,
                    warnings=warnings,
                    replay_diagnostics=replay_diag,
                )
                inferred_count = 0
                inferred_flow_diagnostics = {
                    "mode": "provider_authoritative_only",
                    "fallback_slices_present": False,
                    "replayed_fallback_provider_activity": False,
                    "total_inferred_event_count": 0,
                    "total_inferred_net_usd": 0.0,
                    "inferred_event_window": {"start": None, "end": None},
                    "by_provider": {},
                    "by_slice": {},
                }
            else:
                authoritative_branch_transactions: List[Dict[str, Any]] = []
                out_of_window_branch_transactions: List[Dict[str, Any]] = []
                fallback_branch_transactions: List[Dict[str, Any]] = []
                fallback_provider_activity_count = 0
                out_of_window_provider_activity_count = 0
                for txn in branch_transactions:
                    if str(txn.get("source") or "").strip().lower() == "synthetic_cash_event":
                        authoritative_branch_transactions.append(txn)
                        continue

                    event_date = _to_datetime(txn.get("date"))
                    if event_date is None:
                        fallback_branch_transactions.append(txn)
                        continue

                    provider = _normalize_source_name(txn.get("source"))
                    if provider not in enabled_provider_flow_sources:
                        fallback_branch_transactions.append(txn)
                        continue

                    authority_status = _authoritative_slice_status(
                        provider_flow_coverage,
                        provider=provider,
                        institution=txn.get("_institution") or txn.get("institution"),
                        account_id=txn.get("account_id"),
                        provider_account_ref=txn.get("provider_account_ref"),
                        account_name=txn.get("account_name"),
                        event_date=event_date,
                    )
                    if authority_status == "authoritative_in_window":
                        authoritative_branch_transactions.append(txn)
                    elif authority_status == "authoritative_out_of_window":
                        out_of_window_branch_transactions.append(txn)
                        out_of_window_provider_activity_count += 1
                    else:
                        fallback_branch_transactions.append(txn)
                        fallback_provider_activity_count += 1

                authoritative_branch_income: List[Dict[str, Any]] = []
                out_of_window_branch_income: List[Dict[str, Any]] = []
                fallback_branch_income: List[Dict[str, Any]] = []
                fallback_provider_income_count = 0
                out_of_window_provider_income_count = 0
                for inc in income_with_currency:
                    event_date = _to_datetime(inc.get("date"))
                    if event_date is None:
                        fallback_branch_income.append(inc)
                        continue

                    provider = _normalize_source_name(inc.get("source"))
                    if provider not in enabled_provider_flow_sources:
                        fallback_branch_income.append(inc)
                        continue

                    authority_status = _authoritative_slice_status(
                        provider_flow_coverage,
                        provider=provider,
                        institution=inc.get("institution"),
                        account_id=inc.get("account_id"),
                        provider_account_ref=None,
                        account_name=inc.get("account_name"),
                        event_date=event_date,
                    )
                    if authority_status == "authoritative_in_window":
                        authoritative_branch_income.append(inc)
                    elif authority_status == "authoritative_out_of_window":
                        out_of_window_branch_income.append(inc)
                        out_of_window_provider_income_count += 1
                    else:
                        fallback_branch_income.append(inc)
                        fallback_provider_income_count += 1

                if fallback_provider_activity_count == 0 and fallback_provider_income_count == 0:
                    composed_cash, composed_external = derive_cash_and_external_flows(
                        fifo_transactions=branch_transactions,
                        income_with_currency=income_with_currency,
                        fx_cache=fx_cache,
                        provider_flow_events=authoritative_events,
                        warnings=warnings,
                        replay_diagnostics=replay_diag,
                    )
                    inferred_count = 0
                    inferred_flow_diagnostics = {
                        "mode": "provider_authoritative_only_no_fallback_activity",
                        "fallback_slices_present": True,
                        "replayed_fallback_provider_activity": False,
                        "total_inferred_event_count": 0,
                        "total_inferred_net_usd": 0.0,
                        "inferred_event_window": {"start": None, "end": None},
                        "by_provider": {},
                        "by_slice": {},
                    }
                else:
                    fallback_partitions: Dict[str, Dict[str, Any]] = {}

                    def _partition_key_for_transaction(txn: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
                        source = str(txn.get("source") or "").strip().lower()
                        if source == "synthetic_cash_event":
                            return "non_provider|synthetic_cash_event", "synthetic_cash_event", None

                        provider = _normalize_source_name(txn.get("source"))
                        if provider in enabled_provider_flow_sources:
                            slice_key = _flow_slice_key(
                                provider=provider,
                                institution=txn.get("_institution") or txn.get("institution"),
                                account_id=txn.get("account_id"),
                                provider_account_ref=txn.get("provider_account_ref"),
                                account_name=txn.get("account_name"),
                            )
                            return f"slice|{slice_key}", provider, slice_key

                        return f"non_provider|{provider}", provider, None

                    def _partition_key_for_income(inc: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
                        provider = _normalize_source_name(inc.get("source"))
                        if provider in enabled_provider_flow_sources:
                            slice_key = _flow_slice_key(
                                provider=provider,
                                institution=inc.get("institution"),
                                account_id=inc.get("account_id"),
                                provider_account_ref=None,
                                account_name=inc.get("account_name"),
                            )
                            return f"slice|{slice_key}", provider, slice_key
                        return f"non_provider|{provider}", provider, None

                    for txn in fallback_branch_transactions:
                        part_key, provider_name, slice_key = _partition_key_for_transaction(txn)
                        row = fallback_partitions.setdefault(
                            part_key,
                            {
                                "provider": provider_name,
                                "slice_key": slice_key,
                                "transactions": [],
                                "income": [],
                            },
                        )
                        row["transactions"].append(txn)

                    for inc in fallback_branch_income:
                        part_key, provider_name, slice_key = _partition_key_for_income(inc)
                        row = fallback_partitions.setdefault(
                            part_key,
                            {
                                "provider": provider_name,
                                "slice_key": slice_key,
                                "transactions": [],
                                "income": [],
                            },
                        )
                        row["income"].append(inc)

                    authoritative_cash, authoritative_external = derive_cash_and_external_flows(
                        fifo_transactions=authoritative_branch_transactions,
                        income_with_currency=authoritative_branch_income,
                        fx_cache=fx_cache,
                        provider_flow_events=authoritative_events,
                        warnings=warnings,
                        replay_diagnostics=replay_diag,
                    )
                    out_of_window_cash, out_of_window_external = derive_cash_and_external_flows(
                        fifo_transactions=out_of_window_branch_transactions,
                        income_with_currency=out_of_window_branch_income,
                        fx_cache=fx_cache,
                        force_disable_inference=True,
                        warnings=warnings,
                        replay_diagnostics=replay_diag,
                    )

                    fallback_deltas: List[Tuple[datetime, float]] = []
                    fallback_external: List[Tuple[datetime, float]] = []
                    by_slice: Dict[str, Dict[str, Any]] = {}
                    by_provider_acc: Dict[str, Dict[str, Any]] = {}

                    for row in fallback_partitions.values():
                        partition_transactions = list(row.get("transactions") or [])
                        partition_income = list(row.get("income") or [])
                        partition_cash, partition_external = derive_cash_and_external_flows(
                            fifo_transactions=partition_transactions,
                            income_with_currency=partition_income,
                            fx_cache=fx_cache,
                            warnings=warnings,
                            replay_diagnostics=replay_diag,
                        )
                        fallback_deltas.extend(_snapshots_to_deltas(partition_cash))
                        fallback_external.extend(partition_external)

                        provider_name = str(row.get("provider") or "unknown")
                        slice_key = row.get("slice_key")
                        activity_dates = [
                            _to_datetime(txn.get("date"))
                            for txn in partition_transactions
                            if _to_datetime(txn.get("date")) is not None
                        ]
                        activity_dates.extend(
                            _to_datetime(inc.get("date"))
                            for inc in partition_income
                            if _to_datetime(inc.get("date")) is not None
                        )
                        inferred_dates = [when for when, _ in partition_external]
                        inferred_net_usd = float(sum(_as_float(amount, 0.0) for _, amount in partition_external))

                        provider_row = by_provider_acc.setdefault(
                            provider_name,
                            {
                                "provider": provider_name,
                                "slice_count": 0,
                                "transaction_count": 0,
                                "income_count": 0,
                                "inferred_event_count": 0,
                                "inferred_net_usd": 0.0,
                                "_activity_dates": [],
                                "_inferred_dates": [],
                            },
                        )
                        provider_row["slice_count"] += 1
                        provider_row["transaction_count"] += len(partition_transactions)
                        provider_row["income_count"] += len(partition_income)
                        provider_row["inferred_event_count"] += len(partition_external)
                        provider_row["inferred_net_usd"] += inferred_net_usd
                        provider_row["_activity_dates"].extend(activity_dates)
                        provider_row["_inferred_dates"].extend(inferred_dates)

                        if slice_key:
                            by_slice[slice_key] = {
                                "provider": provider_name,
                                "transaction_count": len(partition_transactions),
                                "income_count": len(partition_income),
                                "inferred_event_count": len(partition_external),
                                "inferred_net_usd": round(inferred_net_usd, 2),
                                "activity_window": _window(activity_dates),
                                "inferred_event_window": _window(inferred_dates),
                            }

                    authoritative_deltas = _snapshots_to_deltas(authoritative_cash)
                    out_of_window_deltas = _snapshots_to_deltas(out_of_window_cash)
                    fallback_cash = _combine_cash_snapshots([], fallback_deltas) if fallback_deltas else []

                    composed_cash = _combine_cash_snapshots(
                        fallback_cash,
                        authoritative_deltas + out_of_window_deltas,
                    )
                    composed_external = sorted(
                        authoritative_external + out_of_window_external + fallback_external,
                        key=lambda row: row[0],
                    )
                    inferred_count = len(fallback_external)
                    total_inferred_net_usd = float(sum(_as_float(amount, 0.0) for _, amount in fallback_external))
                    inferred_dates = [when for when, _ in fallback_external]

                    by_provider: Dict[str, Dict[str, Any]] = {}
                    for provider_name, row in by_provider_acc.items():
                        by_provider[provider_name] = {
                            "slice_count": int(_as_float(row.get("slice_count"), 0.0)),
                            "transaction_count": int(_as_float(row.get("transaction_count"), 0.0)),
                            "income_count": int(_as_float(row.get("income_count"), 0.0)),
                            "inferred_event_count": int(_as_float(row.get("inferred_event_count"), 0.0)),
                            "inferred_net_usd": round(_as_float(row.get("inferred_net_usd"), 0.0), 2),
                            "activity_window": _window(list(row.get("_activity_dates") or [])),
                            "inferred_event_window": _window(list(row.get("_inferred_dates") or [])),
                        }

                    inferred_flow_diagnostics = {
                        "mode": "provider_mixed_authority_partitioned_fallback",
                        "fallback_slices_present": True,
                        "replayed_fallback_provider_activity": True,
                        "total_inferred_event_count": inferred_count,
                        "total_inferred_net_usd": round(total_inferred_net_usd, 2),
                        "inferred_event_window": _window(inferred_dates),
                        "out_of_window_provider_activity_count": int(out_of_window_provider_activity_count),
                        "out_of_window_provider_income_count": int(out_of_window_provider_income_count),
                        "by_provider": dict(sorted(by_provider.items())),
                        "by_slice": dict(sorted(by_slice.items())),
                    }

            external_authoritative_applied = sum(
                1
                for event in authoritative_events
                if bool(event.get("is_external_flow")) and abs(_as_float(event.get("amount"), 0.0)) > 0.0
            )

            return composed_cash, composed_external, {
                "provider_authoritative_applied": len(authoritative_events),
                "provider_authoritative_available": authoritative_available_count,
                "provider_diagnostics_only": diagnostics_only_count,
                "inferred": inferred_count if has_fallback_slices else max(0, len(composed_external) - external_authoritative_applied),
            }, inferred_flow_diagnostics, _finalize_replay_diag()

        (
            cash_snapshots,
            external_flows,
            flow_source_breakdown,
            inferred_flow_diagnostics,
            cash_replay_diagnostics,
        ) = _compose_cash_and_external_flows(transactions_for_cash)
        alias_mismatch_count = int(_as_float(cash_replay_diagnostics.get("income_flow_overlap_alias_mismatch_count"), 0.0))
        if alias_mismatch_count > 0:
            mismatch_samples = list(cash_replay_diagnostics.get("income_flow_overlap_alias_mismatch_samples") or [])
            sample_preview = ", ".join(
                f"{row.get('raw_provider')}->{row.get('normalized_provider')}"
                for row in mismatch_samples[:3]
            )
            if sample_preview:
                warnings.append(
                    "Cash replay: provider alias normalization adjusted "
                    f"{alias_mismatch_count} source token(s) ({sample_preview})."
                )
            else:
                warnings.append(
                    "Cash replay: provider alias normalization adjusted "
                    f"{alias_mismatch_count} source token(s)."
                )

        monthly_nav = compute_monthly_nav(
            position_timeline=position_timeline,
            month_ends=month_ends,
            price_cache=price_cache,
            fx_cache=fx_cache,
            cash_snapshots=cash_snapshots,
        )

        net_flows, tw_flows = compute_monthly_external_flows(
            external_flows=external_flows,
            month_ends=month_ends,
        )

        observed_position_timeline, _, _, _, _ = build_position_timeline(
            fifo_transactions=fifo_transactions,
            current_positions={},
            inception_date=inception_date,
            incomplete_trades=fifo_result.incomplete_trades,
            fmp_ticker_map=fmp_ticker_map or None,
        )
        # Observed-only branch must exclude provider-authoritative flow events so
        # synthetic impact reflects the delta between provider-driven and
        # transaction-only replay traces.
        observed_cash_snapshots, observed_external_flows = derive_cash_and_external_flows(
            fifo_transactions=fifo_transactions,
            income_with_currency=income_with_currency,
            fx_cache=fx_cache,
            warnings=warnings,
        )
        observed_monthly_nav = compute_monthly_nav(
            position_timeline=observed_position_timeline,
            month_ends=month_ends,
            price_cache=price_cache,
            fx_cache=fx_cache,
            cash_snapshots=observed_cash_snapshots,
        )
        observed_net_flows, observed_tw_flows = compute_monthly_external_flows(
            external_flows=observed_external_flows,
            month_ends=month_ends,
        )

        if provider_first_mode and flow_fallback_reasons:
            warnings.append(
                f"Provider-flow fallback applied on {len(flow_fallback_reasons)} slice(s); "
                "inference used for non-authoritative partitions."
            )

        monthly_returns, return_warnings = compute_monthly_returns(
            monthly_nav=monthly_nav,
            net_flows=net_flows,
            time_weighted_flows=tw_flows,
        )
        warnings.extend(return_warnings)

        total_cost_basis_usd = 0.0
        current_portfolio_value = 0.0
        current_position_keys: set[Tuple[str, str, str]] = set()
        for ticker, pos in current_positions.items():
            shares = _as_float(pos.get("shares"), 0.0)
            if abs(shares) < 1e-9:
                continue
            direction = "SHORT" if shares < 0 else "LONG"
            currency = str(pos.get("currency") or "USD").upper()
            current_position_keys.add((ticker, currency, direction))
            current_portfolio_value += _as_float(pos.get("value"), 0.0)

            cb = pos.get("cost_basis")
            if cb is not None:
                cost_basis_value = _as_float(cb, 0.0)
                if not bool(pos.get("cost_basis_is_usd", False)):
                    cost_basis_value *= _event_fx_rate(currency, end_date, fx_cache)
                total_cost_basis_usd += cost_basis_value
        if source == "all":
            source_holding_symbols = sorted(current_positions.keys())
        source_holding_count = len(source_holding_symbols)

        opening_keys: set[Tuple[str, str, str]] = set()
        for txn in fifo_transactions:
            txn_type = str(txn.get("type") or "").upper()
            symbol = str(txn.get("symbol") or "")
            currency = str(txn.get("currency") or "USD").upper()
            if txn_type == "BUY":
                opening_keys.add((symbol, currency, "LONG"))
            elif txn_type == "SHORT":
                opening_keys.add((symbol, currency, "SHORT"))

        if current_position_keys:
            positions_with_full_history = sum(1 for key in current_position_keys if key in opening_keys)
            data_coverage = 100.0 * positions_with_full_history / len(current_position_keys)
        else:
            data_coverage = 100.0
        if not fifo_transactions and current_positions:
            data_coverage = 0.0

        if source != "all" and cross_source_holding_leakage_symbols:
            data_quality_flags.append(
                {
                    "code": "CROSS_SOURCE_HOLDING_LEAKAGE",
                    "severity": "medium",
                    "count": len(cross_source_holding_leakage_symbols),
                    "symbols": cross_source_holding_leakage_symbols,
                }
            )

        low_coverage_threshold = _as_float(
            DATA_QUALITY_THRESHOLDS.get("realized_inferred_short_low_coverage_pct", 80.0),
            80.0,
        )
        synthetic_current_tickers = sorted(
            {
                str(entry.get("ticker") or "").strip()
                for entry in synthetic_entries
                if str(entry.get("source") or "") == "synthetic_current_position"
                and str(entry.get("ticker") or "").strip()
            }
        )
        synthetic_current_market_value = float(
            sum(
                abs(_as_float((current_positions.get(ticker) or {}).get("value"), 0.0))
                for ticker in synthetic_current_tickers
            )
        )
        synthetic_incomplete_trade_count = sum(
            1
            for entry in synthetic_entries
            if str(entry.get("source") or "") == "synthetic_incomplete_trade"
        )
        if synthetic_current_tickers:
            preview = ", ".join(synthetic_current_tickers[:5])
            if len(synthetic_current_tickers) > 5:
                preview = f"{preview}, ..."
            severity = "high" if data_coverage < low_coverage_threshold else "medium"
            warnings.append(
                f"HIGH DATA QUALITY FLAG: Synthetic opening positions inferred for "
                f"{len(synthetic_current_tickers)} symbol(s) ({preview}). "
                "NAV/return metrics include these synthetic lots, but realized/unrealized "
                "P&L only includes observed transaction lots, so the metrics can diverge."
            )
            data_quality_flags.append(
                {
                    "code": "SYNTHETIC_OPENING_POSITIONS",
                    "severity": severity,
                    "count": len(synthetic_current_tickers),
                    "symbols": synthetic_current_tickers,
                    "estimated_current_market_value": round(synthetic_current_market_value, 2),
                }
            )

        if inferred_shorts and data_coverage < low_coverage_threshold:
            preview = ", ".join(inferred_shorts[:5])
            if len(inferred_shorts) > 5:
                preview = f"{preview}, ..."
            warnings.append(
                f"Inferred short entries detected for {len(inferred_shorts)} symbol(s)"
                f" ({preview}) with low transaction coverage "
                f"({data_coverage:.2f}% < {low_coverage_threshold:.0f}%). "
                "Realized/unrealized P&L may diverge from NAV-based returns; "
                "review transaction completeness or short-inference overrides."
            )

        # Check current holdings direction — historical closed shorts shouldn't
        # disable the safety clamp for a currently long-only portfolio.
        is_long_only = all(direction != "SHORT" for _, _, direction in current_position_keys)
        extreme_abs_return_threshold = _as_float(
            DATA_QUALITY_THRESHOLDS.get("realized_extreme_monthly_return_abs", 3.0),
            3.0,
        )
        extreme_month_filter_active = bool(
            data_coverage < low_coverage_threshold
            or synthetic_current_tickers
            or unpriceable_symbols_sorted
        )
        extreme_return_months: List[Dict[str, Any]] = []
        for ts in monthly_returns.index:
            raw = _as_float(monthly_returns.loc[ts], default=np.nan)
            if not np.isfinite(raw):
                continue

            action = "none"
            reason = ""
            if data_coverage < 100.0 and is_long_only and raw < -1.0:
                warnings.append(
                    f"{ts.date().isoformat()}: Clamping return from {raw:.2%} to -100.0%. "
                    "Likely caused by incomplete transaction history."
                )
                monthly_returns.loc[ts] = -1.0
                action = "clamped_to_-100pct"
                reason = "long-only safety clamp"
            elif abs(raw) > extreme_abs_return_threshold and extreme_month_filter_active:
                warnings.append(
                    f"{ts.date().isoformat()}: Excluding extreme return from chain-link metrics "
                    f"({raw:.2%}, |r|>{extreme_abs_return_threshold:.2f}) due to low-confidence data coverage."
                )
                monthly_returns.loc[ts] = np.nan
                action = "excluded_from_chain_linking"
                reason = "extreme-return low-confidence filter"
            elif abs(raw) > extreme_abs_return_threshold:
                warnings.append(
                    f"{ts.date().isoformat()}: Extreme return detected ({raw:.2%}). "
                    "This may indicate missing transaction history."
                )
                action = "warned"
                reason = "extreme return"

            if abs(raw) > extreme_abs_return_threshold or raw < -1.0:
                extreme_return_months.append(
                    {
                        "month_end": ts.date().isoformat(),
                        "raw_return_pct": round(raw * 100.0, 2),
                        "action": action,
                        "reason": reason,
                        "monthly_nav": round(_as_float(monthly_nav.get(ts), 0.0), 2),
                        "monthly_net_flow": round(_as_float(net_flows.get(ts), 0.0), 2),
                    }
                )

        monthly_returns = monthly_returns.replace([np.inf, -np.inf], np.nan).dropna()
        if monthly_returns.empty:
            return {
                "status": "error",
                "message": "No valid monthly return observations available after NAV/flow reconstruction.",
                "data_warnings": sorted(set(warnings)),
            }

        excluded_extreme_months = [
            row for row in extreme_return_months
            if str(row.get("action")) == "excluded_from_chain_linking"
        ]
        if excluded_extreme_months:
            data_quality_flags.append(
                {
                    "code": "EXTREME_MONTHLY_RETURNS_EXCLUDED",
                    "severity": "high" if data_coverage < low_coverage_threshold else "medium",
                    "count": len(excluded_extreme_months),
                    "threshold_abs_return": round(extreme_abs_return_threshold, 4),
                    "months": excluded_extreme_months,
                }
            )

        benchmark_prices = fetch_monthly_close(
            benchmark_ticker,
            start_date=inception_date,
            end_date=end_date,
            fmp_ticker_map=fmp_ticker_map or None,
        )
        benchmark_returns = calc_monthly_returns(benchmark_prices)
        benchmark_returns = _series_from_cache(benchmark_returns)
        monthly_returns = _normalize_monthly_index(monthly_returns)
        benchmark_returns = _normalize_monthly_index(benchmark_returns)

        aligned = pd.DataFrame(
            {
                "portfolio": monthly_returns,
                "benchmark": benchmark_returns,
            }
        ).dropna()

        if aligned.empty:
            return {
                "status": "error",
                "message": f"No overlapping monthly returns between portfolio and benchmark {benchmark_ticker}.",
                "data_warnings": sorted(set(warnings)),
            }

        source_breakdown = dict(Counter(str(t.get("source") or "unknown") for t in fifo_transactions))
        source_transaction_count = len(fifo_transactions)
        realized_pnl = float(_compute_realized_pnl_usd(fifo_result.closed_trades, fx_cache))
        unrealized_pnl = float(
            _compute_unrealized_pnl_usd(
                fifo_result=fifo_result,
                price_cache=price_cache,
                fx_cache=fx_cache,
                as_of=end_date,
            )
        )
        net_contributions = float(_compute_net_contributions_usd(fifo_transactions, fx_cache))
        aligned_start = aligned.index.min()
        aligned_end = aligned.index.max()
        official_nav_start = _value_at_or_before(monthly_nav, aligned_start, default=np.nan)
        official_nav_end = _value_at_or_before(monthly_nav, aligned_end, default=np.nan)
        cumulative_net_external_flows = float(
            net_flows.reindex(aligned.index).fillna(0.0).sum()
        )
        observed_nav_start = _value_at_or_before(observed_monthly_nav, aligned_start, default=np.nan)
        observed_nav_end = _value_at_or_before(observed_monthly_nav, aligned_end, default=np.nan)
        observed_cumulative_net_external_flows = float(
            observed_net_flows.reindex(aligned.index).fillna(0.0).sum()
        )
        # ── Two independent P&L measurement tracks ──────────────────────
        #
        # nav_pnl_usd  (NAV-flow, top-down)
        #   Total gain = NAV_end - NAV_start - net_external_flows.
        #   Derived from monthly Modified Dietz returns × market values.
        #   Captures everything (realized + unrealized + income) in one
        #   number but does NOT split them out.
        #
        # lot_pnl_usd  (FIFO lot-based, bottom-up)
        #   = realized_pnl (closed FIFO trades)
        #   + unrealized_pnl (open lots marked to market)
        #   + income (dividends + interest)
        #   Provides the realized/unrealized breakdown but may under-count
        #   when trade history is incomplete or symbols are unpriceable.
        #
        # reconciliation_gap_usd = nav - lot.  Some gap is expected
        # due to unpriceable symbols, incomplete trades, and timing diffs.
        # ────────────────────────────────────────────────────────────────
        if not np.isfinite(official_nav_start) or not np.isfinite(official_nav_end):
            warnings.append(
                "Unable to compute NAV P&L due to missing NAV endpoints; defaulting to 0.0."
            )
            nav_pnl_usd = 0.0
        else:
            nav_pnl_usd = float(
                official_nav_end - official_nav_start - cumulative_net_external_flows
            )
        if not np.isfinite(observed_nav_start) or not np.isfinite(observed_nav_end):
            observed_nav_pnl_usd = 0.0
        else:
            observed_nav_pnl_usd = float(
                observed_nav_end - observed_nav_start - observed_cumulative_net_external_flows
            )
        synthetic_policy_impact_usd = float(nav_pnl_usd - observed_nav_pnl_usd)

        income_analysis = analyzer.analyze_income()
        income_summary_usd = _summarize_income_usd(income_with_currency, fx_cache)
        income_total = _as_float(income_summary_usd.get("total"), 0.0)
        lot_pnl_usd = float(realized_pnl + unrealized_pnl + income_total)
        reconciliation_gap_usd = float(nav_pnl_usd - lot_pnl_usd)

        income_yield_on_cost = (
            (_as_float(income_summary_usd.get("projected_annual"), 0.0) / total_cost_basis_usd) * 100.0
            if total_cost_basis_usd > 0
            else 0.0
        )
        income_yield_on_value = (
            (_as_float(income_summary_usd.get("projected_annual"), 0.0) / current_portfolio_value) * 100.0
            if current_portfolio_value > 0
            else 0.0
        )
        nav_metrics_estimated = bool(
            synthetic_current_tickers
            or data_coverage < low_coverage_threshold
            or len(unpriceable_symbols_sorted) > 0
        )
        synthetic_sensitivity_threshold_usd = _as_float(
            DATA_QUALITY_THRESHOLDS.get("realized_synthetic_pnl_sensitivity_usd", 5000.0),
            5000.0,
        )
        if abs(synthetic_policy_impact_usd) >= synthetic_sensitivity_threshold_usd:
            warnings.append(
                "HIGH DATA QUALITY FLAG: NAV P&L is highly sensitive to synthetic "
                f"reconstruction (synthetic impact ${synthetic_policy_impact_usd:,.2f})."
            )
            data_quality_flags.append(
                {
                    "code": "SYNTHETIC_PNL_SENSITIVITY",
                    "severity": "high",
                    "impact_usd": round(synthetic_policy_impact_usd, 2),
                    "threshold_usd": round(synthetic_sensitivity_threshold_usd, 2),
                    "nav_pnl_synthetic_enhanced_usd": round(nav_pnl_usd, 2),
                    "nav_pnl_observed_only_usd": round(observed_nav_pnl_usd, 2),
                }
            )

        incomplete_trade_count = len(getattr(fifo_result, "incomplete_trades", []))
        reconciliation_gap_pct = (
            abs(reconciliation_gap_usd) / max(abs(_as_float(official_nav_end, 0.0)), 1000.0) * 100.0  # uses synthetic-enhanced NAV end
        )
        has_high_severity_unpriceable = any(
            str(flag.get("code")) == "UNPRICEABLE_SYMBOLS"
            and str(flag.get("severity", "")).lower() == "high"
            for flag in data_quality_flags
        )
        has_high_synthetic_sensitivity = any(
            str(flag.get("code")) == "SYNTHETIC_PNL_SENSITIVITY"
            and str(flag.get("severity", "")).lower() == "high"
            for flag in data_quality_flags
        )

        confidence_failures: List[str] = []
        if data_coverage < REALIZED_COVERAGE_TARGET:
            confidence_failures.append(
                f"HIGH CONFIDENCE GATE FAILED: data coverage {data_coverage:.2f}% "
                f"is below target {REALIZED_COVERAGE_TARGET:.2f}%."
            )
        if incomplete_trade_count > REALIZED_MAX_INCOMPLETE_TRADES:
            confidence_failures.append(
                f"HIGH CONFIDENCE GATE FAILED: incomplete trades ({incomplete_trade_count}) "
                f"exceed max allowed ({REALIZED_MAX_INCOMPLETE_TRADES})."
            )
        if reconciliation_gap_pct > REALIZED_MAX_RECONCILIATION_GAP_PCT:
            confidence_failures.append(
                f"HIGH CONFIDENCE GATE FAILED: reconciliation gap {reconciliation_gap_pct:.2f}% "
                f"exceeds max {REALIZED_MAX_RECONCILIATION_GAP_PCT:.2f}%."
            )
        if nav_metrics_estimated:
            confidence_failures.append(
                "HIGH CONFIDENCE GATE FAILED: NAV metrics include estimated inputs "
                "(synthetic positions, low coverage, or unpriceable symbols)."
            )
        if has_high_severity_unpriceable:
            confidence_failures.append(
                "HIGH CONFIDENCE GATE FAILED: high-severity unpriceable symbols are present."
            )
        if has_high_synthetic_sensitivity:
            confidence_failures.append(
                "HIGH CONFIDENCE GATE FAILED: NAV P&L is highly sensitive to synthetic reconstruction."
            )
        if confidence_failures:
            warnings.extend(confidence_failures)
        high_confidence_realized = len(confidence_failures) == 0

        reliability_reason_codes: List[str] = []
        reliability_reasons: List[str] = []

        def _add_reliability_reason(code: str, message: str) -> None:
            if code not in reliability_reason_codes:
                reliability_reason_codes.append(code)
            if message not in reliability_reasons:
                reliability_reasons.append(message)

        if data_coverage < REALIZED_COVERAGE_TARGET:
            _add_reliability_reason(
                "LOW_DATA_COVERAGE",
                f"Data coverage {data_coverage:.2f}% is below target {REALIZED_COVERAGE_TARGET:.2f}%.",
            )
        if incomplete_trade_count > REALIZED_MAX_INCOMPLETE_TRADES:
            _add_reliability_reason(
                "INCOMPLETE_TRADES_EXCEED_LIMIT",
                f"Incomplete trades ({incomplete_trade_count}) exceed max allowed ({REALIZED_MAX_INCOMPLETE_TRADES}).",
            )
        if reconciliation_gap_pct > REALIZED_MAX_RECONCILIATION_GAP_PCT:
            _add_reliability_reason(
                "RECONCILIATION_GAP_EXCEED_LIMIT",
                f"Reconciliation gap {reconciliation_gap_pct:.2f}% exceeds max {REALIZED_MAX_RECONCILIATION_GAP_PCT:.2f}%.",
            )
        if nav_metrics_estimated:
            _add_reliability_reason(
                "NAV_METRICS_ESTIMATED",
                "NAV metrics include estimated inputs (synthetic positions, low coverage, or unpriceable symbols).",
            )
        if has_high_severity_unpriceable:
            _add_reliability_reason(
                "HIGH_SEVERITY_UNPRICEABLE",
                "High-severity unpriceable symbols are present.",
            )
        if has_high_synthetic_sensitivity:
            _add_reliability_reason(
                "SYNTHETIC_PNL_SENSITIVITY",
                "NAV P&L is highly sensitive to synthetic reconstruction.",
            )
        if source_transaction_count == 0:
            _add_reliability_reason(
                "ZERO_SOURCE_TRANSACTIONS",
                "No source transactions were available for the selected source.",
            )
        if cross_source_holding_leakage_symbols:
            _add_reliability_reason(
                "CROSS_SOURCE_HOLDING_LEAKAGE",
                f"{len(cross_source_holding_leakage_symbols)} holding symbol(s) had cross-source attribution leakage.",
            )

        reliable = bool(
            high_confidence_realized
            and source_transaction_count > 0
            and not has_high_synthetic_sensitivity
            and not cross_source_holding_leakage_symbols
        )

        risk_free_rate = _safe_treasury_rate(inception_date, end_date)
        min_capm = DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 24)
        selected_aligned = aligned

        start_iso = selected_aligned.index.min().date().isoformat()
        end_iso = selected_aligned.index.max().date().isoformat()

        performance_metrics = compute_performance_metrics(
            portfolio_returns=selected_aligned["portfolio"],
            benchmark_returns=selected_aligned["benchmark"],
            risk_free_rate=risk_free_rate,
            benchmark_ticker=benchmark_ticker,
            start_date=start_iso,
            end_date=end_iso,
            min_capm_observations=min_capm,
        )

        ibkr_pricing_by_type = {
            instrument: len(ibkr_priced_symbols.get(instrument, set()))
            for instrument in ("futures", "fx", "bond", "option")
        }
        ibkr_pricing_total = int(sum(ibkr_pricing_by_type.values()))

        provider_flow_coverage_serialized: Dict[str, Dict[str, Any]] = {}
        for key, row in provider_flow_coverage.items():
            provider_flow_coverage_serialized[key] = {
                "authoritative": bool(row.get("authoritative")),
                "has_metadata": bool(row.get("has_metadata")),
                "event_count": int(_as_float(row.get("event_count"), 0.0)),
                "coverage_start": (
                    _to_datetime(row.get("coverage_start")).isoformat()
                    if _to_datetime(row.get("coverage_start")) is not None
                    else None
                ),
                "coverage_end": (
                    _to_datetime(row.get("coverage_end")).isoformat()
                    if _to_datetime(row.get("coverage_end")) is not None
                    else None
                ),
                "has_error": bool(row.get("has_error")),
                "has_partial": bool(row.get("has_partial")),
                "deterministic_no_flow": bool(row.get("deterministic_no_flow")),
                "unmapped_row_count": int(_as_float(row.get("unmapped_row_count"), 0.0)),
            }

        realized_metadata = {
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "net_contributions": round(net_contributions, 2),
            "external_net_flows_usd": round(cumulative_net_external_flows, 2),
            "net_contributions_definition": "trade_cash_legs_legacy",
            "nav_pnl_usd": round(nav_pnl_usd, 2),
            "nav_pnl_synthetic_enhanced_usd": round(nav_pnl_usd, 2),
            "nav_pnl_observed_only_usd": round(observed_nav_pnl_usd, 2),
            "nav_pnl_synthetic_impact_usd": round(synthetic_policy_impact_usd, 2),
            "lot_pnl_usd": round(lot_pnl_usd, 2),
            "reconciliation_gap_usd": round(reconciliation_gap_usd, 2),
            "pnl_basis": {  # methodology labels for each P&L track (see comment block above)
                "nav": "nav_flow_synthetic_enhanced",  # top-down: NAV_end - NAV_start - flows
                "nav_observed_only": "nav_flow_observed_only",
                "lot": "fifo_observed_lots",   # bottom-up: realized + unrealized + income
            },
            "nav_metrics_estimated": nav_metrics_estimated,
            "high_confidence_realized": high_confidence_realized,
            "reliable": reliable,
            "reliability_reasons": reliability_reasons,
            "reliability_reason_codes": reliability_reason_codes,
            "holdings_scope": holdings_scope,
            "source_holding_symbols": source_holding_symbols,
            "source_holding_count": source_holding_count,
            "source_transaction_count": source_transaction_count,
            "cross_source_holding_leakage_symbols": cross_source_holding_leakage_symbols,
            "income": {
                "total": round(income_total, 2),
                "dividends": round(_as_float(income_summary_usd.get("dividends"), 0.0), 2),
                "interest": round(_as_float(income_summary_usd.get("interest"), 0.0), 2),
                "by_month": income_analysis.by_month,
                "by_symbol": income_analysis.by_symbol,
                "by_institution": income_summary_usd.get("by_institution", {}),
                "current_monthly_rate": round(_as_float(income_summary_usd.get("current_monthly_rate"), 0.0), 2),
                "projected_annual": round(_as_float(income_summary_usd.get("projected_annual"), 0.0), 2),
                "yield_on_cost": round(income_yield_on_cost, 4),
                "yield_on_value": round(income_yield_on_value, 4),
            },
            "data_coverage": round(data_coverage, 2),
            "inception_date": inception_date.date().isoformat(),
            "synthetic_positions": synthetic_positions,
            "synthetic_entry_count": len(synthetic_entries),
            "synthetic_current_position_count": len(synthetic_current_tickers),
            "synthetic_current_position_tickers": synthetic_current_tickers,
            "synthetic_current_market_value": round(synthetic_current_market_value, 2),
            "synthetic_incomplete_trade_count": synthetic_incomplete_trade_count,
            "first_transaction_exit_count": len(first_exit_without_opening),
            "first_transaction_exit_details": first_exit_without_opening,
            "extreme_return_months": extreme_return_months,
            "data_quality_flags": data_quality_flags,
            "unpriceable_symbol_count": len(unpriceable_symbols_sorted),
            "unpriceable_symbols": unpriceable_symbols_sorted,
            "unpriceable_reason_counts": dict(sorted(unpriceable_reason_counts.items())),
            "unpriceable_reasons": dict(sorted(unpriceable_reasons.items())),
            "ibkr_pricing_coverage": {
                "total_symbols_priced_via_ibkr": ibkr_pricing_total,
                "by_instrument_type": ibkr_pricing_by_type,
            },
            "source_breakdown": source_breakdown,
            "fetch_errors": fetch_errors,
            "flow_source_breakdown": flow_source_breakdown,
            "inferred_flow_diagnostics": inferred_flow_diagnostics,
            "futures_cash_policy": "fee_only",
            "futures_txn_count_replayed": int(_as_float(cash_replay_diagnostics.get("futures_txn_count_replayed"), 0.0)),
            "futures_notional_suppressed_usd": round(
                _as_float(cash_replay_diagnostics.get("futures_notional_suppressed_usd"), 0.0),
                2,
            ),
            "futures_fee_cash_impact_usd": round(
                _as_float(cash_replay_diagnostics.get("futures_fee_cash_impact_usd"), 0.0),
                2,
            ),
            "futures_unknown_action_count": int(
                _as_float(cash_replay_diagnostics.get("futures_unknown_action_count"), 0.0)
            ),
            "futures_missing_fx_count": int(
                _as_float(cash_replay_diagnostics.get("futures_missing_fx_count"), 0.0)
            ),
            "income_flow_overlap_dropped_count": int(
                _as_float(cash_replay_diagnostics.get("income_flow_overlap_dropped_count"), 0.0)
            ),
            "income_flow_overlap_dropped_net_usd": round(
                _as_float(cash_replay_diagnostics.get("income_flow_overlap_dropped_net_usd"), 0.0),
                2,
            ),
            "income_flow_overlap_dropped_by_provider": dict(
                sorted((cash_replay_diagnostics.get("income_flow_overlap_dropped_by_provider") or {}).items())
            ),
            "income_flow_overlap_candidate_count": int(
                _as_float(cash_replay_diagnostics.get("income_flow_overlap_candidate_count"), 0.0)
            ),
            "income_flow_overlap_alias_mismatch_count": alias_mismatch_count,
            "income_flow_overlap_alias_mismatch_samples": list(
                cash_replay_diagnostics.get("income_flow_overlap_alias_mismatch_samples") or []
            ),
            "provider_flow_coverage": provider_flow_coverage_serialized,
            "flow_fallback_reasons": flow_fallback_reasons,
            "dedup_diagnostics": dedup_diagnostics,
            "data_warnings": sorted(set(warnings)),
            "_postfilter": {
                "portfolio_monthly_returns": {
                    ts.date().isoformat(): float(v)
                    for ts, v in aligned["portfolio"].to_dict().items()
                },
                "benchmark_monthly_returns": {
                    ts.date().isoformat(): float(v)
                    for ts, v in aligned["benchmark"].to_dict().items()
                },
                "selected_portfolio_monthly_returns": {
                    ts.date().isoformat(): float(v)
                    for ts, v in selected_aligned["portfolio"].to_dict().items()
                },
                "selected_benchmark_monthly_returns": {
                    ts.date().isoformat(): float(v)
                    for ts, v in selected_aligned["benchmark"].to_dict().items()
                },
                "monthly_nav": {
                    ts.date().isoformat(): float(val)
                    for ts, val in monthly_nav.items()
                },
                "observed_only_monthly_nav": {
                    ts.date().isoformat(): float(val)
                    for ts, val in observed_monthly_nav.items()
                },
                "net_flows": {
                    ts.date().isoformat(): float(val)
                    for ts, val in net_flows.items()
                },
                "observed_only_net_flows": {
                    ts.date().isoformat(): float(val)
                    for ts, val in observed_net_flows.items()
                },
                "risk_free_rate": float(risk_free_rate),
                "benchmark_ticker": benchmark_ticker,
            },
        }

        if include_series:
            realized_metadata["monthly_nav"] = {
                ts.date().isoformat(): round(float(val), 2)
                for ts, val in monthly_nav.items()
            }
            reported_monthly_returns = pd.Series(
                performance_metrics.get("monthly_returns", {}),
                dtype=float,
            )
            if not reported_monthly_returns.empty:
                reported_monthly_returns.index = pd.to_datetime(
                    reported_monthly_returns.index,
                    errors="coerce",
                )
                reported_monthly_returns = reported_monthly_returns[
                    ~reported_monthly_returns.index.isna()
                ].sort_index()
            cumulative = (1.0 + reported_monthly_returns).cumprod()
            realized_metadata["growth_of_dollar"] = {
                ts.date().isoformat(): round(float(val), 4)
                for ts, val in cumulative.items()
            }

        performance_metrics["realized_metadata"] = realized_metadata
        performance_metrics["realized_pnl"] = realized_metadata["realized_pnl"]
        performance_metrics["unrealized_pnl"] = realized_metadata["unrealized_pnl"]
        performance_metrics["income_total"] = realized_metadata["income"]["total"]
        performance_metrics["income_yield_on_cost"] = realized_metadata["income"]["yield_on_cost"]
        performance_metrics["income_yield_on_value"] = realized_metadata["income"]["yield_on_value"]
        performance_metrics["data_coverage"] = realized_metadata["data_coverage"]
        performance_metrics["inception_date"] = realized_metadata["inception_date"]
        performance_metrics["nav_pnl_usd"] = realized_metadata["nav_pnl_usd"]
        performance_metrics["nav_pnl_observed_only_usd"] = realized_metadata["nav_pnl_observed_only_usd"]
        performance_metrics["nav_pnl_synthetic_impact_usd"] = realized_metadata["nav_pnl_synthetic_impact_usd"]
        performance_metrics["lot_pnl_usd"] = realized_metadata["lot_pnl_usd"]
        performance_metrics["reconciliation_gap_usd"] = realized_metadata["reconciliation_gap_usd"]
        performance_metrics["nav_metrics_estimated"] = realized_metadata["nav_metrics_estimated"]
        performance_metrics["high_confidence_realized"] = realized_metadata["high_confidence_realized"]
        performance_metrics["reliable"] = realized_metadata["reliable"]
        performance_metrics["reliability_reason_codes"] = realized_metadata["reliability_reason_codes"]
        performance_metrics["pnl_basis"] = realized_metadata["pnl_basis"]
        performance_metrics["external_net_flows_usd"] = realized_metadata["external_net_flows_usd"]
        performance_metrics["net_contributions_definition"] = realized_metadata["net_contributions_definition"]

        from core.result_objects import RealizedPerformanceResult
        return RealizedPerformanceResult.from_analysis_dict(performance_metrics)

    except Exception as exc:
        return {
            "status": "error",
            "message": f"Realized performance analysis failed: {exc}",
            "data_warnings": sorted(set(warnings)) if warnings else [],
        }


__all__ = [
    "REALIZED_PROVIDER_ALIAS_MAP",
    "build_position_timeline",
    "derive_cash_and_external_flows",
    "compute_monthly_nav",
    "compute_monthly_external_flows",
    "compute_monthly_returns",
    "analyze_realized_performance",
]
