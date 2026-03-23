from __future__ import annotations

import json
import os
import re
import settings
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
from providers.csv_transactions import CSVTransactionProvider
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

from . import _helpers, engine, holdings, mwr as _mwr, nav

def _prefetch_fifo_transactions(
    *,
    positions,
    user_email: str,
    source: str,
    institution: Optional[str],
    account: Optional[str] = None,
    account_filters: Optional[list[tuple[str, str, str | None]]] = None,
) -> List[Dict[str, Any]]:
    """Fetch and normalize FIFO transactions once for account discovery."""
    allow_stale_existing_transaction_store = True
    for position_row in list(getattr(getattr(positions, "data", None), "positions", []) or []):
        try:
            raw_value = float(position_row.get("value") or 0.0)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(raw_value):
            continue
        if raw_value != 0.0:
            allow_stale_existing_transaction_store = False
            break
    transaction_store_read = bool(_helpers._shim_attr("TRANSACTION_STORE_READ", TRANSACTION_STORE_READ))
    transaction_store_max_age_hours = _helpers._shim_attr(
        "TRANSACTION_STORE_MAX_AGE_HOURS",
        TRANSACTION_STORE_MAX_AGE_HOURS,
    )
    transaction_store_retry_cooldown_minutes = _helpers._shim_attr(
        "TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES",
        TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES,
    )
    fetch_transactions_for_source_fn = _helpers._shim_attr(
        "fetch_transactions_for_source",
        fetch_transactions_for_source,
    )
    get_schwab_security_lookup_fn = _helpers._shim_attr(
        "get_schwab_security_lookup",
        get_schwab_security_lookup,
    )
    trading_analyzer_cls = _helpers._shim_attr("TradingAnalyzer", TradingAnalyzer)

    csv_store = CSVTransactionProvider()
    if account_filters is None and csv_store.has_source(user_email, source):
        store_data = csv_store.load_transactions(user_email, source)
        fifo_transactions = list(store_data.get("fifo_transactions") or [])
        if settings.EXERCISE_COST_BASIS_ENABLED:
            from trading_analysis.exercise_linkage import link_option_exercises

            fifo_transactions = link_option_exercises(fifo_transactions)
    elif transaction_store_read:
        from inputs.transaction_store import (
            ensure_store_fresh,
            load_from_store,
            load_from_store_for_portfolio,
        )
        from utils.user_resolution import resolve_user_id

        user_id = resolve_user_id(user_email)
        ensure_store_fresh(
            user_id=user_id,
            user_email=user_email,
            provider=source,
            max_age_hours=transaction_store_max_age_hours,
            retry_cooldown_minutes=transaction_store_retry_cooldown_minutes,
            allow_stale_existing=allow_stale_existing_transaction_store,
        )
        if account_filters:
            store_data = load_from_store_for_portfolio(
                user_id=user_id,
                account_filters=account_filters,
                source=source,
            )
        else:
            store_data = load_from_store(
                user_id=user_id,
                source=source,
                institution=institution,
                account=account,
            )
        fifo_transactions = list(store_data.get("fifo_transactions") or [])
        if settings.EXERCISE_COST_BASIS_ENABLED:
            from trading_analysis.exercise_linkage import link_option_exercises
            fifo_transactions = link_option_exercises(fifo_transactions)
    else:
        if institution:
            fetch_result = fetch_transactions_for_source_fn(
                user_email=user_email,
                source=source,
                institution=institution,
                account=account,
            )
        else:
            fetch_result = fetch_transactions_for_source_fn(
                user_email=user_email,
                source=source,
                account=account,
            )

        payload = getattr(fetch_result, "payload", fetch_result) or {}
        if not isinstance(payload, dict):
            payload = {}

        schwab_security_lookup = get_schwab_security_lookup_fn(
            user_email=user_email,
            source=source,
            payload=payload,
        )
        analyzer = trading_analyzer_cls(
            plaid_securities=payload.get("plaid_securities", []),
            plaid_transactions=payload.get("plaid_transactions", []),
            snaptrade_activities=payload.get("snaptrade_activities", []),
            ibkr_flex_trades=payload.get("ibkr_flex_trades"),
            ibkr_flex_cash_rows=payload.get("ibkr_flex_cash_rows"),
            schwab_transactions=payload.get("schwab_transactions", []),
            schwab_security_lookup=schwab_security_lookup,
            use_fifo=True,
            account_filter=None,
        )
        fifo_transactions = list(analyzer.fifo_transactions)
    if institution:
        fifo_transactions = [
            txn
            for txn in fifo_transactions
            if match_institution(txn.get("_institution") or "", institution)
        ]
    fifo_transactions.sort(key=lambda row: _helpers._to_datetime(row.get("date")) or datetime.min)
    return fifo_transactions

def _looks_like_display_name(candidate: str, institution: str) -> bool:
    """Return True if candidate looks like a provider display name, not a real account ID.

    Display names like "Interactive Brokers (Henry Chien)" are generated by
    aggregators (SnapTrade) and can't be matched against transaction account_id
    fields from native data sources (e.g. IBKR Flex "U2471778").

    Real account IDs (IBKR U-numbers, Schwab masked numbers) are never treated
    as display names, so dormant accounts with real IDs are preserved.
    """
    normalized = candidate.strip().lower()
    if not normalized:
        return False
    # If it matches an IBKR account ID pattern (U1234567), it's a real ID
    if _helpers._IBKR_ACCOUNT_ID_RE.match(normalized.replace(" ", "")):
        return False
    # If it contains the institution keyword, it's a display name
    if match_institution(normalized, institution):
        return True
    # If it contains common display-name patterns (parentheses, long names)
    if "(" in candidate or len(candidate) > 30:
        return True
    return False

def _discover_account_ids(
    positions: "PositionResult",
    fifo_transactions: List[Dict[str, Any]],
    institution: str,
) -> List[str]:
    """Discover account IDs from positions and normalized transactions.

    Position-derived display names (e.g. "Interactive Brokers (Henry Chien)")
    that match zero transactions are removed when transaction-derived accounts
    exist.  Only display names are filtered - real account IDs (IBKR U-numbers,
    Schwab masked numbers) are always preserved even if dormant.
    """
    from_positions: set[str] = set()
    from_transactions: set[str] = set()
    linked_account_pairs: set[Tuple[str, str]] = set()

    for pos in list(getattr(getattr(positions, "data", None), "positions", []) or []):
        brokerage_name = str(pos.get("brokerage_name") or pos.get("institution") or "")
        if not match_institution(brokerage_name, institution):
            continue
        account_name = str(pos.get("account_name") or "").strip()
        if account_name:
            from_positions.add(account_name)
        account_id = str(pos.get("account_id") or "").strip()
        if account_id:
            from_positions.add(account_id)
            if account_name:
                linked_account_pairs.add((account_name, account_id))

    for txn in fifo_transactions or []:
        txn_institution = str(txn.get("_institution") or txn.get("institution") or "")
        if not match_institution(txn_institution, institution):
            continue
        account_name = str(txn.get("account_name") or "").strip()
        if account_name:
            from_transactions.add(account_name)
        account_id = str(txn.get("account_id") or "").strip()
        if account_id:
            from_transactions.add(account_id)
            if account_name:
                linked_account_pairs.add((account_name, account_id))

    all_accounts = from_positions | from_transactions
    if all_accounts:
        normalized_to_values: Dict[str, set[str]] = defaultdict(set)
        for value in all_accounts:
            normalized = str(value or "").strip().lower()
            if normalized:
                normalized_to_values[normalized].add(str(value).strip())

        normalized_accounts = set(normalized_to_values)
        linked_accounts: Dict[str, set[str]] = defaultdict(set)
        for left_raw, right_raw in linked_account_pairs:
            left = str(left_raw or "").strip().lower()
            right = str(right_raw or "").strip().lower()
            if not left or not right:
                continue
            linked_accounts[left].add(right)
            linked_accounts[right].add(left)
        canonical_by_normalized: Dict[str, str] = {}
        visited_norms: set[str] = set()

        for account_norm in sorted(normalized_accounts):
            if account_norm in visited_norms:
                continue

            component: set[str] = set()
            stack = [account_norm]
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.add(current)
                visited_norms.add(current)
                for alias in resolve_account_aliases(current):
                    if alias in normalized_accounts and alias not in component:
                        stack.append(alias)
                for linked in linked_accounts.get(current, set()):
                    if linked in normalized_accounts and linked not in component:
                        stack.append(linked)

            ibkr_norms = sorted(
                member
                for member in component
                if _helpers._IBKR_ACCOUNT_ID_RE.match(member.replace(" ", ""))
            )
            canonical_norm = ibkr_norms[0] if ibkr_norms else sorted(component)[0]
            for member in component:
                canonical_by_normalized[member] = canonical_norm

        def _canonical_value(raw_value: str) -> str:
            normalized = str(raw_value or "").strip().lower()
            if not normalized:
                return ""
            canonical_norm = canonical_by_normalized.get(normalized, normalized)
            display_candidates = sorted(normalized_to_values.get(canonical_norm, {canonical_norm}))
            if _helpers._IBKR_ACCOUNT_ID_RE.match(canonical_norm.replace(" ", "")):
                ibkr_display = [
                    candidate
                    for candidate in display_candidates
                    if _helpers._IBKR_ACCOUNT_ID_RE.match(candidate.strip().replace(" ", ""))
                ]
                if ibkr_display:
                    return ibkr_display[0]
            return display_candidates[0]

        from_positions = {_canonical_value(value) for value in from_positions if str(value).strip()}
        from_transactions = {_canonical_value(value) for value in from_transactions if str(value).strip()}

    seen = from_positions | from_transactions

    # Remove position-only DISPLAY NAMES with zero matching transactions.
    # Real account IDs (U2471778, etc.) are never removed - only names that
    # look like provider-generated display names are candidates.
    position_only = from_positions - from_transactions
    if position_only and from_transactions:
        institution_txns = [
            txn
            for txn in (fifo_transactions or [])
            if match_institution(
                str(txn.get("_institution") or txn.get("institution") or ""),
                institution,
            )
        ]
        for candidate in list(position_only):
            if not _looks_like_display_name(candidate, institution):
                continue  # Real account ID - keep even if dormant
            if not any(holdings._match_account(txn, candidate) for txn in institution_txns):
                seen.discard(candidate)

    return sorted(seen)

def _discover_schwab_account_ids(
    positions: "PositionResult",
    fifo_transactions: List[Dict[str, Any]],
    institution: Optional[str],
) -> List[str]:
    """Backward-compatible alias for callers/tests expecting Schwab defaults."""
    return _discover_account_ids(
        positions=positions,
        fifo_transactions=fifo_transactions,
        institution=(institution or "schwab"),
    )

def _snap_flow_date_to_nav(
    flow_date: datetime,
    nav_idx: pd.DatetimeIndex,
) -> Optional[pd.Timestamp]:
    """Snap a flow date to the nearest NAV index date (same logic as TWR).

    Uses searchsorted(side='left') to find the first NAV date >= flow_date.
    Returns None if the flow falls after all NAV dates.
    """
    if nav_idx.empty:
        return None
    flow_day = pd.Timestamp(flow_date).normalize()
    pos = int(nav_idx.searchsorted(flow_day, side="left"))
    if pos >= len(nav_idx):
        return None
    return nav_idx[pos]

def _merge_window(
    existing: Optional[Dict[str, Optional[str]]],
    incoming: Optional[Dict[str, Optional[str]]],
) -> Dict[str, Optional[str]]:
    start_candidates: List[datetime] = []
    end_candidates: List[datetime] = []

    for row in (existing or {}, incoming or {}):
        start = _helpers._to_datetime(row.get("start")) if isinstance(row, dict) else None
        end = _helpers._to_datetime(row.get("end")) if isinstance(row, dict) else None
        if start is not None:
            start_candidates.append(start)
        if end is not None:
            end_candidates.append(end)

    return {
        "start": min(start_candidates).isoformat() if start_candidates else None,
        "end": max(end_candidates).isoformat() if end_candidates else None,
    }

def _merge_numeric_dict(target: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in (incoming or {}).items():
        if isinstance(value, dict):
            existing = target.get(key)
            if not isinstance(existing, dict):
                target[key] = {}
                existing = target[key]
            _merge_numeric_dict(existing, value)
            continue
        if isinstance(value, list):
            existing_list = target.get(key)
            if not isinstance(existing_list, list):
                target[key] = list(value)
            else:
                for item in value:
                    if item not in existing_list:
                        existing_list.append(item)
            continue
        if isinstance(value, bool):
            target.setdefault(key, value)
            continue
        if isinstance(value, (int, float, np.number)):
            target[key] = _helpers._as_float(target.get(key), 0.0) + _helpers._as_float(value, 0.0)
            continue
        target.setdefault(key, value)
    return target

def _sum_account_daily_series(
    per_account: Dict[str, "RealizedPerformanceResult"],
    *,
    min_inception_nav: float = 500.0,
    nav_key: str = "daily_nav",
    fallback_nav_key: str = "monthly_nav",
    external_flow_key: str = "external_flows",
    fallback_external_flow_key: str = "net_flows",
) -> Tuple[pd.Series, List[Tuple[datetime, float]]]:
    all_navs: List[pd.Series] = []
    all_external_flows: List[List[Tuple[datetime, float]]] = []

    for result in per_account.values():
        pf = getattr(getattr(result, "realized_metadata", None), "_postfilter", None) or {}
        nav_s = _helpers._dict_to_series(pf.get(nav_key))
        if nav_s.empty:
            nav_s = _helpers._dict_to_series(pf.get(fallback_nav_key))
        external_flows = _helpers._dict_to_flow_list(pf.get(external_flow_key))
        if not external_flows:
            external_flows = _helpers._dict_to_flow_list(pf.get(fallback_external_flow_key))

        if not nav_s.empty and min_inception_nav > 0:
            mask = nav_s.abs() >= min_inception_nav
            if mask.any():
                first_viable = pd.Timestamp(mask.idxmax()).to_pydatetime().replace(tzinfo=None)
                full_nav_idx = pd.DatetimeIndex(nav_s.index).sort_values()
                nav_s = nav_s.loc[first_viable:]
                first_viable_ts = pd.Timestamp(first_viable)
                external_flows = [
                    (when, amount)
                    for when, amount in external_flows
                    if (snapped := _snap_flow_date_to_nav(when, full_nav_idx)) is not None
                    and snapped >= first_viable_ts
                ]

        all_navs.append(nav_s)
        all_external_flows.append(external_flows)

    non_empty_navs = [series for series in all_navs if not series.empty]
    if not non_empty_navs:
        return pd.Series(dtype=float), []

    union_idx = pd.DatetimeIndex(sorted(set().union(*(series.index for series in non_empty_navs))))
    combined_nav = sum(
        series.reindex(union_idx).ffill().fillna(0.0)
        for series in all_navs
    )
    combined_external_flows = sorted(
        [item for flows in all_external_flows for item in flows],
        key=lambda row: row[0],
    )
    return combined_nav.sort_index(), combined_external_flows

def _sum_account_monthly_series(
    per_account: Dict[str, "RealizedPerformanceResult"],
    *,
    min_inception_nav: float = 500.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    all_navs: List[pd.Series] = []
    all_nets: List[pd.Series] = []
    all_tws: List[pd.Series] = []

    for result in per_account.values():
        pf = getattr(getattr(result, "realized_metadata", None), "_postfilter", None) or {}
        nav_s = _helpers._dict_to_series(pf.get("monthly_nav"))
        net_s = _helpers._dict_to_series(pf.get("net_flows"))
        tw_s = _helpers._dict_to_series(pf.get("time_weighted_flows"))

        # Defer inception for tiny-base accounts: skip months before the
        # account first crosses ``min_inception_nav``.  This prevents
        # extreme Modified Dietz returns on near-zero starting balances
        # (e.g., credit-card cash-back rewards accumulating $27-$140)
        # from distorting the combined return.
        if not nav_s.empty and min_inception_nav > 0:
            mask = nav_s.abs() >= min_inception_nav
            if mask.any():
                first_viable = mask.idxmax()
                nav_s = nav_s.loc[first_viable:]
                net_s = net_s.reindex(nav_s.index).fillna(0.0)
                tw_s = tw_s.reindex(nav_s.index).fillna(0.0)

        all_navs.append(nav_s)
        all_nets.append(net_s)
        all_tws.append(tw_s)

    non_empty_navs = [series for series in all_navs if not series.empty]
    if not non_empty_navs:
        return pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float)

    union_idx = pd.DatetimeIndex(
        sorted(set().union(*(series.index for series in non_empty_navs)))
    )
    combined_nav = sum(
        series.reindex(union_idx).ffill().fillna(0.0)
        for series in all_navs
    )
    combined_net = sum(
        series.reindex(union_idx).fillna(0.0)
        for series in all_nets
    )
    combined_tw = sum(
        series.reindex(union_idx).fillna(0.0)
        for series in all_tws
    )
    return (
        _helpers._normalize_monthly_index(combined_nav),
        _helpers._normalize_monthly_index(combined_net),
        _helpers._normalize_monthly_index(combined_tw),
    )

def _build_aggregated_result(
    *,
    per_account: Dict[str, "RealizedPerformanceResult"],
    per_account_errors: Dict[str, str],
    benchmark_ticker: str,
    include_series: bool,
    price_registry: ProviderRegistry | None,
    fmp_ticker_map: Dict[str, str],
) -> Union["RealizedPerformanceResult", Dict[str, Any]]:
    del price_registry
    fetch_monthly_close_fn = _helpers._shim_attr("fetch_monthly_close", fetch_monthly_close)
    calc_monthly_returns_fn = _helpers._shim_attr("calc_monthly_returns", calc_monthly_returns)
    compute_performance_metrics_fn = _helpers._shim_attr(
        "compute_performance_metrics",
        compute_performance_metrics,
    )

    if not per_account:
        return {
            "status": "error",
            "message": "No successful account analyses available for aggregation.",
        }

    agg_daily_nav, agg_external_flows = _sum_account_daily_series(
        per_account,
        external_flow_key="investor_external_flows",
        fallback_external_flow_key="external_flows",
    )
    if agg_daily_nav.empty:
        return {
            "status": "error",
            "message": "No daily NAV data available for account aggregation.",
        }

    inception_candidates: List[datetime] = []
    inception_original_candidates: List[datetime] = []
    end_candidates: List[datetime] = [datetime.now(UTC).replace(tzinfo=None)]
    for result in per_account.values():
        inception_dt = _helpers._to_datetime(result.realized_metadata.inception_date)
        if inception_dt is not None:
            inception_candidates.append(inception_dt)
        inception_original_dt = _helpers._to_datetime(
            result.realized_metadata.inception_date_original or result.realized_metadata.inception_date
        )
        if inception_original_dt is not None:
            inception_original_candidates.append(inception_original_dt)
        analysis_end = _helpers._to_datetime((result.analysis_period or {}).get("end_date"))
        if analysis_end is not None:
            end_candidates.append(analysis_end)
    end_candidates.append(agg_daily_nav.index.max().to_pydatetime().replace(tzinfo=None))

    inception_date = min(inception_candidates) if inception_candidates else (end_candidates[0] - timedelta(days=365))
    inception_date_original = (
        min(inception_original_candidates)
        if any(result.realized_metadata.inception_date_original is not None for result in per_account.values())
        else None
    )
    end_date = max(end_candidates)
    month_ends = _helpers._month_end_range(inception_date, end_date)

    month_end_index = pd.DatetimeIndex(pd.to_datetime(month_ends)).sort_values()
    agg_nav = pd.Series(
        [_helpers._value_at_or_before(agg_daily_nav, ts, default=np.nan) for ts in month_end_index],
        index=month_end_index,
        dtype=float,
    )
    agg_nav = _helpers._normalize_monthly_index(agg_nav)
    if agg_nav.empty:
        return {
            "status": "error",
            "message": "No monthly NAV data available for account aggregation.",
        }

    agg_net, agg_tw = nav.compute_monthly_external_flows(
        external_flows=agg_external_flows,
        month_ends=month_ends,
    )
    agg_net = _helpers._normalize_monthly_index(agg_net)
    agg_tw = _helpers._normalize_monthly_index(agg_tw)

    has_daily_external_flows = False
    for result in per_account.values():
        pf = getattr(getattr(result, "realized_metadata", None), "_postfilter", None) or {}
        if pf.get("investor_external_flows") or pf.get("external_flows"):
            has_daily_external_flows = True
            break
    if not has_daily_external_flows:
        _, legacy_net, legacy_tw = _sum_account_monthly_series(per_account)
        if not legacy_net.empty:
            agg_net = legacy_net.reindex(agg_nav.index).fillna(0.0)
        if not legacy_tw.empty:
            agg_tw = legacy_tw.reindex(agg_nav.index).fillna(0.0)

    agg_monthly_returns, agg_return_warnings = nav.compute_twr_monthly_returns(
        daily_nav=agg_daily_nav,
        external_flows=agg_external_flows,
        month_ends=month_ends,
    )
    agg_monthly_returns = agg_monthly_returns.replace([np.inf, -np.inf], np.nan).dropna()
    if agg_monthly_returns.empty:
        return {
            "status": "error",
            "message": "No valid monthly returns after account aggregation.",
        }

    benchmark_start = (
        (pd.Timestamp(inception_date).to_period("M") - 1)
        .to_timestamp()
        .to_pydatetime()
        .replace(tzinfo=None)
    )
    benchmark_prices = fetch_monthly_close_fn(
        benchmark_ticker,
        start_date=benchmark_start,
        end_date=end_date,
        fmp_ticker_map=fmp_ticker_map or None,
    )
    benchmark_returns = calc_monthly_returns_fn(benchmark_prices)
    benchmark_returns = _helpers._series_from_cache(benchmark_returns)
    agg_monthly_returns = _helpers._normalize_monthly_index(agg_monthly_returns)
    benchmark_returns = _helpers._normalize_monthly_index(benchmark_returns)

    aligned = pd.DataFrame(
        {
            "portfolio": agg_monthly_returns,
            "benchmark": benchmark_returns,
        }
    ).dropna()
    if aligned.empty:
        return {
            "status": "error",
            "message": "No overlapping benchmark data for aggregated returns.",
        }

    risk_free_rate = nav._safe_treasury_rate(inception_date, end_date)
    aligned_start = aligned.index.min()
    aligned_end = aligned.index.max()
    start_iso = aligned_start.date().isoformat()
    end_iso = aligned_end.date().isoformat()
    min_capm = DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 24)
    performance_metrics = compute_performance_metrics_fn(
        portfolio_returns=aligned["portfolio"],
        benchmark_returns=aligned["benchmark"],
        risk_free_rate=risk_free_rate,
        benchmark_ticker=benchmark_ticker,
        start_date=start_iso,
        end_date=end_iso,
        min_capm_observations=min_capm,
    )

    account_items = sorted(per_account.items(), key=lambda row: row[0])
    meta_dicts = [result.realized_metadata.to_dict() for _, result in account_items]
    first_meta = meta_dicts[0] if meta_dicts else {}
    first_result = account_items[0][1]

    def _sum_field(name: str) -> float:
        return float(sum(_helpers._as_float(meta.get(name), 0.0) for meta in meta_dicts))

    def _sum_int_field(name: str) -> int:
        return int(round(sum(_helpers._as_float(meta.get(name), 0.0) for meta in meta_dicts)))

    source_breakdown_counter: Counter[str] = Counter()
    flow_source_breakdown_counter: Counter[str] = Counter()
    unpriceable_reason_counts: Counter[str] = Counter()
    income_overlap_by_provider: Counter[str] = Counter()
    fetch_errors: Dict[str, str] = {}
    provider_flow_coverage: Dict[str, Dict[str, Any]] = {}
    flow_fallback_reasons: List[str] = []
    reliability_reasons: List[str] = []
    reliability_reason_codes: List[str] = []
    source_holding_symbols_set: set[str] = set()
    cross_source_leakage_symbols_set: set[str] = set()
    synthetic_current_ticker_set: set[str] = set()
    synthetic_positions_seen: set[Tuple[str, str, str]] = set()
    synthetic_positions: List[Dict[str, str]] = []
    first_exit_details: List[Any] = []
    unpriceable_symbol_set: set[str] = set()
    unpriceable_suppressed_symbol_set: set[str] = set()
    unpriceable_reasons: Dict[str, str] = {}

    data_warnings_set: set[str] = set()
    data_quality_flags: List[Dict[str, Any]] = []
    seen_flag_codes: set[str] = set()
    dedup_diagnostics: Dict[str, Any] = {}

    income_total = 0.0
    income_dividends = 0.0
    income_interest = 0.0
    income_by_month: Dict[str, float] = defaultdict(float)
    income_by_symbol: Dict[str, float] = defaultdict(float)
    income_by_institution: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"dividends": 0.0, "interest": 0.0, "total": 0.0}
    )
    inferred_cost_basis = 0.0
    inferred_portfolio_value = 0.0

    data_coverage_weighted = 0.0
    data_coverage_weight = 0.0

    merged_inferred_flow: Dict[str, Any] = {
        "mode": (first_meta.get("inferred_flow_diagnostics") or {}).get("mode", "inference_only"),
        "fallback_slices_present": bool(
            (first_meta.get("inferred_flow_diagnostics") or {}).get("fallback_slices_present", False)
        ),
        "replayed_fallback_provider_activity": bool(
            (first_meta.get("inferred_flow_diagnostics") or {}).get("replayed_fallback_provider_activity", False)
        ),
        "total_inferred_event_count": 0,
        "total_inferred_net_usd": 0.0,
        "inferred_event_window": {"start": None, "end": None},
        "by_provider": {},
        "by_slice": {},
    }

    for _, result in account_items:
        meta = result.realized_metadata.to_dict()
        income = meta.get("income", {}) or {}
        inferred = meta.get("inferred_flow_diagnostics", {}) or {}

        txn_count = max(int(_helpers._as_float(meta.get("source_transaction_count"), 0.0)), 0)
        data_coverage_weight += txn_count
        data_coverage_weighted += _helpers._as_float(meta.get("data_coverage"), 0.0) * txn_count

        for key, value in (meta.get("source_breakdown", {}) or {}).items():
            source_breakdown_counter[str(key)] += int(_helpers._as_float(value, 0.0))
        for key, value in (meta.get("flow_source_breakdown", {}) or {}).items():
            flow_source_breakdown_counter[str(key)] += int(_helpers._as_float(value, 0.0))
        for key, value in (meta.get("unpriceable_reason_counts", {}) or {}).items():
            unpriceable_reason_counts[str(key)] += int(_helpers._as_float(value, 0.0))
        for key, value in (meta.get("income_flow_overlap_dropped_by_provider", {}) or {}).items():
            income_overlap_by_provider[str(key)] += int(_helpers._as_float(value, 0.0))

        for key, value in (meta.get("fetch_errors", {}) or {}).items():
            fetch_errors.setdefault(str(key), str(value))
        for key, value in (meta.get("provider_flow_coverage", {}) or {}).items():
            if str(key) not in provider_flow_coverage:
                provider_flow_coverage[str(key)] = dict(value) if isinstance(value, dict) else {"value": value}
        for reason in list(meta.get("flow_fallback_reasons", []) or []):
            if reason not in flow_fallback_reasons:
                flow_fallback_reasons.append(reason)
        for reason in list(meta.get("reliability_reasons", []) or []):
            if reason not in reliability_reasons:
                reliability_reasons.append(reason)
        for code in list(meta.get("reliability_reason_codes", []) or []):
            if code not in reliability_reason_codes:
                reliability_reason_codes.append(code)

        source_holding_symbols_set.update(
            str(symbol)
            for symbol in list(meta.get("source_holding_symbols", []) or [])
            if str(symbol).strip()
        )
        cross_source_leakage_symbols_set.update(
            str(symbol)
            for symbol in list(meta.get("cross_source_holding_leakage_symbols", []) or [])
            if str(symbol).strip()
        )
        synthetic_current_ticker_set.update(
            str(symbol)
            for symbol in list(meta.get("synthetic_current_position_tickers", []) or [])
            if str(symbol).strip()
        )

        for row in list(meta.get("synthetic_positions", []) or []):
            if not isinstance(row, dict):
                continue
            dedup_key = (
                str(row.get("ticker") or ""),
                str(row.get("currency") or ""),
                str(row.get("direction") or ""),
            )
            if dedup_key in synthetic_positions_seen:
                continue
            synthetic_positions_seen.add(dedup_key)
            synthetic_positions.append(
                {
                    "ticker": dedup_key[0],
                    "currency": dedup_key[1],
                    "direction": dedup_key[2],
                }
            )

        first_exit_details.extend(list(meta.get("first_transaction_exit_details", []) or []))
        unpriceable_symbol_set.update(
            str(symbol)
            for symbol in list(meta.get("unpriceable_symbols", []) or [])
            if str(symbol).strip()
        )
        unpriceable_suppressed_symbol_set.update(
            str(symbol).strip().upper()
            for symbol in list(meta.get("unpriceable_suppressed_symbols", []) or [])
            if str(symbol).strip()
        )
        for ticker, reason in (meta.get("unpriceable_reasons", {}) or {}).items():
            unpriceable_reasons.setdefault(str(ticker), str(reason))

        for warning in list(meta.get("data_warnings", []) or []):
            if warning:
                data_warnings_set.add(str(warning))

        for flag in list(meta.get("data_quality_flags", []) or []):
            if not isinstance(flag, dict):
                continue
            code = str(flag.get("code") or "").strip() or json.dumps(flag, sort_keys=True)
            if code in seen_flag_codes:
                continue
            seen_flag_codes.add(code)
            data_quality_flags.append(dict(flag))

        _merge_numeric_dict(dedup_diagnostics, meta.get("dedup_diagnostics", {}) or {})

        income_total += _helpers._as_float(income.get("total"), 0.0)
        income_dividends += _helpers._as_float(income.get("dividends"), 0.0)
        income_interest += _helpers._as_float(income.get("interest"), 0.0)
        for month, value in (income.get("by_month", {}) or {}).items():
            income_by_month[str(month)] += _helpers._as_float(value, 0.0)
        for symbol, value in (income.get("by_symbol", {}) or {}).items():
            income_by_symbol[str(symbol)] += _helpers._as_float(value, 0.0)
        for institution_key, row in (income.get("by_institution", {}) or {}).items():
            if not isinstance(row, dict):
                continue
            income_by_institution[str(institution_key)]["dividends"] += _helpers._as_float(row.get("dividends"), 0.0)
            income_by_institution[str(institution_key)]["interest"] += _helpers._as_float(row.get("interest"), 0.0)
            income_by_institution[str(institution_key)]["total"] += _helpers._as_float(row.get("total"), 0.0)

        projected_annual_local = _helpers._as_float(income.get("projected_annual"), 0.0)
        yield_on_cost_local = _helpers._as_float(income.get("yield_on_cost"), 0.0)
        yield_on_value_local = _helpers._as_float(income.get("yield_on_value"), 0.0)
        if projected_annual_local > 0 and yield_on_cost_local > 0:
            inferred_cost_basis += projected_annual_local / (yield_on_cost_local / 100.0)
        if projected_annual_local > 0 and yield_on_value_local > 0:
            inferred_portfolio_value += projected_annual_local / (yield_on_value_local / 100.0)

        merged_inferred_flow["total_inferred_event_count"] += int(
            _helpers._as_float(inferred.get("total_inferred_event_count"), 0.0)
        )
        merged_inferred_flow["total_inferred_net_usd"] += _helpers._as_float(
            inferred.get("total_inferred_net_usd"),
            0.0,
        )
        merged_inferred_flow["inferred_event_window"] = _merge_window(
            merged_inferred_flow.get("inferred_event_window"),
            inferred.get("inferred_event_window"),
        )
        merged_inferred_flow["out_of_window_provider_activity_count"] = int(
            _helpers._as_float(merged_inferred_flow.get("out_of_window_provider_activity_count"), 0.0)
            + _helpers._as_float(inferred.get("out_of_window_provider_activity_count"), 0.0)
        )
        merged_inferred_flow["out_of_window_provider_income_count"] = int(
            _helpers._as_float(merged_inferred_flow.get("out_of_window_provider_income_count"), 0.0)
            + _helpers._as_float(inferred.get("out_of_window_provider_income_count"), 0.0)
        )

        by_provider = inferred.get("by_provider", {}) or {}
        for provider_name, row in by_provider.items():
            provider_key = str(provider_name)
            existing = merged_inferred_flow["by_provider"].setdefault(
                provider_key,
                {
                    "slice_count": 0,
                    "transaction_count": 0,
                    "income_count": 0,
                    "inferred_event_count": 0,
                    "inferred_net_usd": 0.0,
                    "activity_window": {"start": None, "end": None},
                    "inferred_event_window": {"start": None, "end": None},
                },
            )
            existing["slice_count"] += int(_helpers._as_float((row or {}).get("slice_count"), 0.0))
            existing["transaction_count"] += int(_helpers._as_float((row or {}).get("transaction_count"), 0.0))
            existing["income_count"] += int(_helpers._as_float((row or {}).get("income_count"), 0.0))
            existing["inferred_event_count"] += int(_helpers._as_float((row or {}).get("inferred_event_count"), 0.0))
            existing["inferred_net_usd"] += _helpers._as_float((row or {}).get("inferred_net_usd"), 0.0)
            existing["activity_window"] = _merge_window(
                existing.get("activity_window"),
                (row or {}).get("activity_window"),
            )
            existing["inferred_event_window"] = _merge_window(
                existing.get("inferred_event_window"),
                (row or {}).get("inferred_event_window"),
            )

        for slice_key, row in (inferred.get("by_slice", {}) or {}).items():
            merged_inferred_flow["by_slice"][str(slice_key)] = dict(row) if isinstance(row, dict) else {"value": row}

        # Per-account observed-only tracks are aggregated from _postfilter
        # after metadata merging so we can apply the same inception gating
        # used for the synthetic-enhanced track.

    income_month_keys = sorted(income_by_month.keys())
    if len(income_month_keys) >= 3:
        current_monthly_rate = sum(income_by_month[key] for key in income_month_keys[-3:]) / 3.0
    else:
        current_monthly_rate = income_total / max(len(income_month_keys), 1)
    projected_annual = current_monthly_rate * 12.0

    income_yield_on_cost = (
        (projected_annual / inferred_cost_basis) * 100.0
        if inferred_cost_basis > 0
        else 0.0
    )
    income_yield_on_value = (
        (projected_annual / inferred_portfolio_value) * 100.0
        if inferred_portfolio_value > 0
        else 0.0
    )

    if data_coverage_weight > 0:
        data_coverage = data_coverage_weighted / data_coverage_weight
    else:
        data_coverage = (
            sum(_helpers._as_float(meta.get("data_coverage"), 0.0) for meta in meta_dicts) / max(len(meta_dicts), 1)
        )

    observed_daily_nav, observed_external_flows = _sum_account_daily_series(
        per_account,
        nav_key="observed_only_daily_nav",
        fallback_nav_key="observed_only_monthly_nav",
        external_flow_key="observed_only_external_flows",
        fallback_external_flow_key="observed_only_net_flows",
    )
    if observed_daily_nav.empty:
        observed_only_nav = pd.Series(0.0, index=agg_nav.index, dtype=float)
        observed_only_net = pd.Series(0.0, index=agg_nav.index, dtype=float)
    else:
        observed_only_nav = pd.Series(
            [_helpers._value_at_or_before(observed_daily_nav, ts, default=0.0) for ts in agg_nav.index],
            index=agg_nav.index,
            dtype=float,
        )
        observed_only_net, _ = nav.compute_monthly_external_flows(
            external_flows=observed_external_flows,
            month_ends=[ts.to_pydatetime().replace(tzinfo=None) for ts in agg_nav.index],
        )
        observed_only_net = _helpers._normalize_monthly_index(observed_only_net).reindex(agg_nav.index).fillna(0.0)

    extreme_abs_return_threshold = _helpers._as_float(
        DATA_QUALITY_THRESHOLDS.get("realized_extreme_monthly_return_abs", 3.0),
        3.0,
    )
    extreme_return_months: List[Dict[str, Any]] = []
    for ts, raw_value in agg_monthly_returns.items():
        raw = _helpers._as_float(raw_value, np.nan)
        if not np.isfinite(raw):
            continue
        if abs(raw) <= extreme_abs_return_threshold and raw >= -1.0:
            continue
        action = "warned"
        reason = "extreme return"
        if raw < -1.0:
            action = "clamped_to_-100pct"
            reason = "long-only safety clamp"
        extreme_return_months.append(
            {
                "month_end": ts.date().isoformat(),
                "raw_return_pct": round(raw * 100.0, 2),
                "action": action,
                "reason": reason,
                "monthly_nav": round(_helpers._as_float(agg_nav.get(ts), 0.0), 2),
                "monthly_net_flow": round(_helpers._as_float(agg_net.get(ts), 0.0), 2),
            }
        )

    data_warnings_set.update(str(warning) for warning in agg_return_warnings if warning)
    data_warnings_set.add(f"Account aggregation: combined {len(account_items)} Schwab account(s).")
    if per_account_errors:
        failed_preview = ", ".join(
            f"{acct}: {msg}" for acct, msg in sorted(per_account_errors.items())
        )
        data_warnings_set.add(
            "Account aggregation: skipped account(s) with errors - "
            f"{failed_preview}"
        )

    for provider_name, row in (merged_inferred_flow.get("by_provider", {}) or {}).items():
        row["inferred_net_usd"] = round(_helpers._as_float(row.get("inferred_net_usd"), 0.0), 2)
        merged_inferred_flow["by_provider"][provider_name] = row
    merged_inferred_flow["by_provider"] = dict(
        sorted((merged_inferred_flow.get("by_provider") or {}).items())
    )
    merged_inferred_flow["by_slice"] = dict(
        sorted((merged_inferred_flow.get("by_slice") or {}).items())
    )
    merged_inferred_flow["total_inferred_event_count"] = int(
        _helpers._as_float(merged_inferred_flow.get("total_inferred_event_count"), 0.0)
    )
    merged_inferred_flow["total_inferred_net_usd"] = round(
        _helpers._as_float(merged_inferred_flow.get("total_inferred_net_usd"), 0.0),
        2,
    )

    realized_metadata = dict(first_meta)
    realized_metadata.update(
        {
            "realized_pnl": round(_sum_field("realized_pnl"), 2),
            "unrealized_pnl": round(_sum_field("unrealized_pnl"), 2),
            "net_contributions": round(_sum_field("net_contributions"), 2),
            "external_net_flows_usd": round(_sum_field("external_net_flows_usd"), 2),
            "net_contributions_definition": first_meta.get("net_contributions_definition", "trade_cash_legs_legacy"),
            "nav_pnl_usd": round(_sum_field("nav_pnl_usd"), 2),
            "nav_pnl_synthetic_enhanced_usd": round(_sum_field("nav_pnl_synthetic_enhanced_usd"), 2),
            "nav_pnl_observed_only_usd": round(_sum_field("nav_pnl_observed_only_usd"), 2),
            "nav_pnl_synthetic_impact_usd": round(_sum_field("nav_pnl_synthetic_impact_usd"), 2),
            "lot_pnl_usd": round(_sum_field("lot_pnl_usd"), 2),
            "incomplete_pnl": round(_sum_field("incomplete_pnl"), 2),
            "reconciliation_gap_usd": round(_sum_field("reconciliation_gap_usd"), 2),
            "pnl_basis": first_meta.get("pnl_basis", {}),
            "nav_metrics_estimated": any(bool(meta.get("nav_metrics_estimated")) for meta in meta_dicts),
            "high_confidence_realized": all(bool(meta.get("high_confidence_realized")) for meta in meta_dicts),
            "income": {
                "total": round(income_total, 2),
                "dividends": round(income_dividends, 2),
                "interest": round(income_interest, 2),
                "by_month": dict(sorted((k, round(v, 2)) for k, v in income_by_month.items())),
                "by_symbol": dict(sorted((k, round(v, 2)) for k, v in income_by_symbol.items())),
                "by_institution": {
                    key: {
                        "dividends": round(_helpers._as_float(row.get("dividends"), 0.0), 2),
                        "interest": round(_helpers._as_float(row.get("interest"), 0.0), 2),
                        "total": round(_helpers._as_float(row.get("total"), 0.0), 2),
                    }
                    for key, row in sorted(income_by_institution.items())
                },
                "current_monthly_rate": round(current_monthly_rate, 2),
                "projected_annual": round(projected_annual, 2),
                "yield_on_cost": round(income_yield_on_cost, 4),
                "yield_on_value": round(income_yield_on_value, 4),
            },
            "data_coverage": round(data_coverage, 2),
            "inception_date": inception_date.date().isoformat(),
            "synthetic_positions": synthetic_positions,
            "synthetic_entry_count": _sum_int_field("synthetic_entry_count"),
            "synthetic_current_position_count": _sum_int_field("synthetic_current_position_count"),
            "synthetic_current_position_tickers": sorted(synthetic_current_ticker_set),
            "synthetic_current_market_value": round(_sum_field("synthetic_current_market_value"), 2),
            "synthetic_incomplete_trade_count": _sum_int_field("synthetic_incomplete_trade_count"),
            "first_transaction_exit_count": _sum_int_field("first_transaction_exit_count"),
            "first_transaction_exit_details": first_exit_details,
            "extreme_return_months": extreme_return_months,
            "data_quality_flags": data_quality_flags,
            "unpriceable_symbol_count": len(unpriceable_symbol_set),
            "unpriceable_symbols": sorted(unpriceable_symbol_set),
            "unpriceable_reason_counts": dict(sorted(unpriceable_reason_counts.items())),
            "unpriceable_reasons": dict(sorted(unpriceable_reasons.items())),
            "ibkr_pricing_coverage": first_meta.get("ibkr_pricing_coverage", {}),
            "source_breakdown": dict(sorted(source_breakdown_counter.items())),
            "reliable": all(bool(meta.get("reliable")) for meta in meta_dicts),
            "reliability_reasons": reliability_reasons,
            "holdings_scope": first_meta.get("holdings_scope", first_result.realized_metadata.holdings_scope),
            "source_holding_symbols": sorted(source_holding_symbols_set),
            "source_holding_count": len(source_holding_symbols_set),
            "source_transaction_count": _sum_int_field("source_transaction_count"),
            "cross_source_holding_leakage_symbols": sorted(cross_source_leakage_symbols_set),
            "reliability_reason_codes": reliability_reason_codes,
            "fetch_errors": fetch_errors,
            "flow_source_breakdown": dict(sorted(flow_source_breakdown_counter.items())),
            "inferred_flow_diagnostics": merged_inferred_flow,
            "provider_flow_coverage": dict(sorted(provider_flow_coverage.items())),
            "flow_fallback_reasons": flow_fallback_reasons,
            "dedup_diagnostics": dedup_diagnostics,
            "data_warnings": sorted(data_warnings_set),
            "futures_cash_policy": "fee_only",
            "futures_margin_anchor_applied": any(
                bool(meta.get("futures_margin_anchor_applied", False)) for meta in meta_dicts
            ),
            "futures_margin_anchor_usd": round(_sum_field("futures_margin_anchor_usd"), 2),
            "cash_anchor_source": (
                "futures_margin"
                if any(meta.get("cash_anchor_source") == "futures_margin" for meta in meta_dicts)
                else first_meta.get("cash_anchor_source", "none")
            ),
            "cash_anchor_applied_to_nav": any(
                bool(meta.get("cash_anchor_applied_to_nav", False)) for meta in meta_dicts
            ),
            "cash_anchor_available": any(
                bool(meta.get("cash_anchor_available", False)) for meta in meta_dicts
            ),
            "cash_anchor_offset_usd": round(_sum_field("cash_anchor_offset_usd"), 2),
            "observed_only_cash_anchor_offset_usd": round(
                _sum_field("observed_only_cash_anchor_offset_usd"), 2
            ),
            "cash_backsolve_start_usd": round(_sum_field("cash_backsolve_start_usd"), 2),
            "cash_backsolve_observed_end_usd": round(_sum_field("cash_backsolve_observed_end_usd"), 2),
            "cash_backsolve_replay_final_usd": round(_sum_field("cash_backsolve_replay_final_usd"), 2),
            "cash_backsolve_matched_rows": _sum_int_field("cash_backsolve_matched_rows"),
            "futures_txn_count_replayed": _sum_int_field("futures_txn_count_replayed"),
            "futures_notional_suppressed_usd": round(_sum_field("futures_notional_suppressed_usd"), 2),
            "unpriceable_suppressed_count": _sum_int_field("unpriceable_suppressed_count"),
            "unpriceable_suppressed_usd": round(_sum_field("unpriceable_suppressed_usd"), 2),
            "unpriceable_suppressed_symbols": sorted(unpriceable_suppressed_symbol_set),
            "futures_fee_cash_impact_usd": round(_sum_field("futures_fee_cash_impact_usd"), 2),
            "futures_unknown_action_count": _sum_int_field("futures_unknown_action_count"),
            "futures_missing_fx_count": _sum_int_field("futures_missing_fx_count"),
            "futures_mtm_event_count": _sum_int_field("futures_mtm_event_count"),
            "futures_mtm_cash_impact_usd": round(_sum_field("futures_mtm_cash_impact_usd"), 2),
            "income_flow_overlap_dropped_count": _sum_int_field("income_flow_overlap_dropped_count"),
            "income_flow_overlap_dropped_net_usd": round(_sum_field("income_flow_overlap_dropped_net_usd"), 2),
            "income_flow_overlap_dropped_by_provider": dict(sorted(income_overlap_by_provider.items())),
            "income_flow_overlap_candidate_count": _sum_int_field("income_flow_overlap_candidate_count"),
            "income_flow_overlap_alias_mismatch_count": _sum_int_field("income_flow_overlap_alias_mismatch_count"),
            "income_flow_overlap_alias_mismatch_samples": list(
                first_meta.get("income_flow_overlap_alias_mismatch_samples", []) or []
            ),
        }
    )
    if inception_date_original is not None:
        realized_metadata["inception_date_original"] = inception_date_original.date().isoformat()

    agg_nav_start = _helpers._value_at_or_before(agg_nav, aligned_start, default=np.nan)
    agg_nav_end = _helpers._value_at_or_before(agg_nav, aligned_end, default=np.nan)
    mwr_value, mwr_status = _mwr.compute_mwr(
        external_flows=agg_external_flows,
        nav_start=agg_nav_start,
        nav_end=agg_nav_end,
        start_date=aligned_start,
        end_date=aligned_end,
    )
    realized_metadata["money_weighted_return"] = round(mwr_value * 100.0, 2) if mwr_value is not None else None
    realized_metadata["mwr_status"] = mwr_status

    realized_metadata["_postfilter"] = {
        "portfolio_monthly_returns": {
            ts.date().isoformat(): float(value)
            for ts, value in aligned["portfolio"].to_dict().items()
        },
        "benchmark_monthly_returns": {
            ts.date().isoformat(): float(value)
            for ts, value in aligned["benchmark"].to_dict().items()
        },
        "selected_portfolio_monthly_returns": {
            ts.date().isoformat(): float(value)
            for ts, value in aligned["portfolio"].to_dict().items()
        },
        "selected_benchmark_monthly_returns": {
            ts.date().isoformat(): float(value)
            for ts, value in aligned["benchmark"].to_dict().items()
        },
        "monthly_nav": _helpers._series_to_dict(agg_nav),
        "daily_nav": {
            ts.date().isoformat(): float(_helpers._as_float(value, 0.0))
            for ts, value in agg_daily_nav.items()
        },
        "observed_only_monthly_nav": _helpers._series_to_dict(observed_only_nav),
        "observed_only_daily_nav": {
            ts.date().isoformat(): float(_helpers._as_float(value, 0.0))
            for ts, value in observed_daily_nav.items()
        },
        "net_flows": _helpers._series_to_dict(agg_net),
        "external_flows": _helpers._flows_to_dict(agg_external_flows),
        "observed_only_net_flows": _helpers._series_to_dict(observed_only_net),
        "observed_only_external_flows": _helpers._flows_to_dict(observed_external_flows),
        "time_weighted_flows": _helpers._series_to_dict(agg_tw),
        "risk_free_rate": float(risk_free_rate),
        "benchmark_ticker": benchmark_ticker,
    }

    # Preserve per-account raw debug audit streams under account ids.
    per_account_audit = {}
    for account_id, result in account_items:
        pf = getattr(getattr(result, "realized_metadata", None), "_postfilter", None) or {}
        if "audit_trail" in pf:
            per_account_audit[account_id] = pf["audit_trail"]
    if per_account_audit:
        realized_metadata["_postfilter"]["audit_trail_by_account"] = per_account_audit

    realized_metadata["account_aggregation"] = {
        "mode": "per_account_modified_dietz",
        "account_count": len(account_items),
        "accounts": {
            account_id: {
                "total_return_pct": result.returns.get("total_return"),
                "inception_date": str(result.realized_metadata.inception_date),
                "nav_pnl_usd": result.realized_metadata.nav_pnl_usd,
                "external_net_flows_usd": result.realized_metadata.external_net_flows_usd,
            }
            for account_id, result in account_items
        },
        "failed_accounts": dict(sorted(per_account_errors.items())),
    }

    if include_series:
        realized_metadata["monthly_nav"] = {
            ts.date().isoformat(): round(float(value), 2)
            for ts, value in agg_nav.items()
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
            ts.date().isoformat(): round(float(value), 4)
            for ts, value in cumulative.items()
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
    performance_metrics["money_weighted_return"] = realized_metadata["money_weighted_return"]
    performance_metrics["net_contributions_definition"] = realized_metadata["net_contributions_definition"]

    from core.result_objects import RealizedPerformanceResult

    return RealizedPerformanceResult.from_analysis_dict(performance_metrics)

def _analyze_realized_performance_account_aggregated(
    positions: "PositionResult",
    user_email: str,
    benchmark_ticker: str = "SPY",
    source: str = "all",
    institution: Optional[str] = None,
    segment: str = "all",
    include_series: bool = False,
    backfill_path: Optional[str] = None,
    price_registry: ProviderRegistry | None = None,
    inception_override: Optional[datetime] = None,
    account_filters: Optional[list[tuple[str, str, str | None]]] = None,
) -> Union["RealizedPerformanceResult", Dict[str, Any]]:
    import logging
    from core.result_objects import RealizedPerformanceResult
    perf_logger = logging.getLogger("performance")

    assert institution is not None

    account_ids: List[str] = []
    fmp_ticker_map: Dict[str, str] = {}

    warnings: List[str] = []
    if source != "all":
        scoped_holdings = holdings._build_source_scoped_holdings(
            positions,
            source,
            warnings,
            institution=institution,
            account=None,
        )
        fmp_ticker_map = dict(scoped_holdings.fmp_ticker_map)
    else:
        _, fmp_ticker_map, _ = holdings._build_current_positions(
            positions,
            institution=institution,
            account=None,
        )

    try:
        prefetch_fifo = _prefetch_fifo_transactions(
            positions=positions,
            user_email=user_email,
            source=source,
            institution=institution,
            account_filters=account_filters,
        )
        account_ids = _discover_account_ids(
            positions,
            prefetch_fifo,
            institution,
        )
    except Exception as exc:
        perf_logger.warning(
            "Account aggregation prefetch failed; falling back to single-scope path: %s",
            exc,
        )
        return engine._analyze_realized_performance_single_scope(
            positions=positions,
            user_email=user_email,
            benchmark_ticker=benchmark_ticker,
            source=source,
            institution=institution,
            account=None,
            segment=segment,
            include_series=include_series,
            backfill_path=backfill_path,
            price_registry=price_registry,
            inception_override=inception_override,
            account_filters=account_filters,
        )

    if len(account_ids) <= 1:
        single_account = account_ids[0] if account_ids else None
        return engine._analyze_realized_performance_single_scope(
            positions=positions,
            user_email=user_email,
            benchmark_ticker=benchmark_ticker,
            source=source,
            institution=institution,
            account=single_account,
            segment=segment,
            include_series=include_series,
            backfill_path=backfill_path,
            price_registry=price_registry,
            inception_override=inception_override,
            account_filters=account_filters,
        )

    per_account: Dict[str, RealizedPerformanceResult] = {}
    per_account_errors: Dict[str, str] = {}
    for account_id in account_ids:
        try:
            account_result = engine._analyze_realized_performance_single_scope(
                positions=positions,
                user_email=user_email,
                benchmark_ticker=benchmark_ticker,
                source=source,
                institution=institution,
                account=account_id,
                segment=segment,
                include_series=False,
                backfill_path=backfill_path,
                price_registry=price_registry,
                inception_override=inception_override,
                use_per_symbol_inception=bool(match_institution(institution, "schwab")),
                account_filters=account_filters,
            )
            if isinstance(account_result, dict):
                if account_result.get("status") == "error":
                    per_account_errors[account_id] = str(
                        account_result.get("message") or "unknown error"
                    )
                    continue
                account_result = RealizedPerformanceResult.from_analysis_dict(account_result)

            pf = getattr(getattr(account_result, "realized_metadata", None), "_postfilter", None) or {}
            missing_keys = [
                key
                for key in ("monthly_nav", "net_flows", "time_weighted_flows")
                if not pf.get(key)
            ]
            if missing_keys:
                per_account_errors[account_id] = f"missing _postfilter keys: {missing_keys}"
                continue
            per_account[account_id] = account_result
        except Exception as exc:
            per_account_errors[account_id] = str(exc)

    if not per_account:
        perf_logger.warning(
            "Account aggregation: all %d accounts failed, falling back to single-scope",
            len(account_ids),
        )
        fallback = engine._analyze_realized_performance_single_scope(
            positions=positions,
            user_email=user_email,
            benchmark_ticker=benchmark_ticker,
            source=source,
            institution=institution,
            account=None,
            segment=segment,
            include_series=include_series,
            backfill_path=backfill_path,
            price_registry=price_registry,
            inception_override=inception_override,
            account_filters=account_filters,
        )
        if isinstance(fallback, RealizedPerformanceResult):
            fallback_warnings = list(fallback.realized_metadata.data_warnings or [])
            fallback_warnings.append(
                f"Account aggregation fallback: all discovered {institution} accounts failed account-scoped analysis."
            )
            fallback.realized_metadata.data_warnings = sorted(set(fallback_warnings))
        return fallback

    return _build_aggregated_result(
        per_account=per_account,
        per_account_errors=per_account_errors,
        benchmark_ticker=benchmark_ticker,
        include_series=include_series,
        price_registry=price_registry,
        fmp_ticker_map=fmp_ticker_map,
    )

def analyze_realized_performance(
    positions: "PositionResult",
    user_email: str,
    benchmark_ticker: str = "SPY",
    source: str = "all",
    institution: Optional[str] = None,
    account: Optional[str] = None,
    segment: str = "all",
    include_series: bool = False,
    backfill_path: Optional[str] = None,
    price_registry: ProviderRegistry | None = None,
    inception_override: Optional[datetime] = None,
    account_filters: Optional[list[tuple[str, str, str | None]]] = None,
) -> Union["RealizedPerformanceResult", Dict[str, Any]]:
    source = (source or "all").lower().strip()
    institution = (institution or "").strip() or None
    account = (account or "").strip() or None
    _SOURCE_TO_INSTITUTION = {
        "schwab": "schwab",
        "schwab_csv": "schwab",
        "ibkr_flex": "ibkr",
        "ibkr_statement": "ibkr",
    }

    if institution is not None and source not in {"all"}:
        expected_inst = _SOURCE_TO_INSTITUTION.get(source)
        if expected_inst and not match_institution(institution, expected_inst):
            return {
                "status": "error",
                "message": f"source={source!r} conflicts with institution={institution!r}",
            }

    if institution is None and source not in {"all"}:
        institution = _SOURCE_TO_INSTITUTION.get(source)

    use_per_symbol_inception = bool(
        institution and match_institution(institution, "schwab")
    )

    if source not in {"all", "snaptrade", "plaid", "ibkr_flex", "ibkr_statement", "schwab", "schwab_csv"}:
        return engine._analyze_realized_performance_single_scope(
            positions=positions,
            user_email=user_email,
            benchmark_ticker=benchmark_ticker,
            source=source,
            institution=institution,
            account=account,
            segment=segment,
            include_series=include_series,
            backfill_path=backfill_path,
            price_registry=price_registry,
            inception_override=inception_override,
            use_per_symbol_inception=use_per_symbol_inception,
            account_filters=account_filters,
        )

    should_aggregate = not account and institution is not None and not account_filters

    if should_aggregate:
        return _analyze_realized_performance_account_aggregated(
            positions=positions,
            user_email=user_email,
            benchmark_ticker=benchmark_ticker,
            source=source,
            institution=institution,
            segment=segment,
            include_series=include_series,
            backfill_path=backfill_path,
            price_registry=price_registry,
            inception_override=inception_override,
            account_filters=account_filters,
        )

    return engine._analyze_realized_performance_single_scope(
        positions=positions,
        user_email=user_email,
        benchmark_ticker=benchmark_ticker,
        source=source,
        institution=institution,
        account=account,
        segment=segment,
        include_series=include_series,
        backfill_path=backfill_path,
        price_registry=price_registry,
        inception_override=inception_override,
        use_per_symbol_inception=use_per_symbol_inception,
        account_filters=account_filters,
    )

__all__ = [
    '_prefetch_fifo_transactions',
    '_looks_like_display_name',
    '_discover_account_ids',
    '_discover_schwab_account_ids',
    '_snap_flow_date_to_nav',
    '_merge_window',
    '_merge_numeric_dict',
    '_sum_account_daily_series',
    '_sum_account_monthly_series',
    '_build_aggregated_result',
    '_analyze_realized_performance_account_aggregated',
    'analyze_realized_performance',
]
