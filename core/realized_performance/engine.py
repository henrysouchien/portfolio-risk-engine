from __future__ import annotations

import json
import os
import re
import settings
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as _date_type
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd

from app_platform.logging.workflow_timing import WorkflowTimer
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
from providers.routing import (
    IBKR_TRANSACTION_SOURCES,
    get_canonical_provider,
    resolve_provider_token,
)
from providers.routing_config import resolve_account_aliases
from settings import (
    BACKFILL_FILE_PATH,
    DATA_QUALITY_THRESHOLDS,
    OPTION_MULTIPLIER_NAV_ENABLED,
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
from trading_analysis.instrument_meta import (
    SEGMENT_ASSET_CLASS_MAP,
    SEGMENT_INSTRUMENT_TYPES,
    _ASSET_CLASS_SEGMENTS,
    _EXCLUDED_ASSET_CLASSES,
    _EXCLUDED_INSTRUMENT_TYPES,
    InstrumentMeta,
    coerce_instrument_type,
)
from trading_analysis.symbol_utils import parse_option_contract_identity_from_symbol
from utils.logging import portfolio_logger
from services.security_type_service import SecurityTypeService

from . import _helpers, backfill, fx, holdings, mwr as _mwr, nav, pricing, provider_flows, timeline


_REALIZED_PRICE_FETCH_WORKERS = max(1, int(os.getenv("REALIZED_PRICE_FETCH_WORKERS", "8")))


def _serialize_audit_trail(
    synthetic_entries: Optional[List[Dict[str, Any]]],
    position_timeline: Optional[Dict[Tuple[str, str, str], List[Tuple[Any, Any]]]],
    cash_snapshots: Optional[List[Tuple[Any, Any]]],
    observed_cash_snapshots: Optional[List[Tuple[Any, Any]]],
    fifo_transactions: Optional[List[Dict[str, Any]]],
    futures_mtm_events: Optional[List[Dict[str, Any]]],
    synthetic_twr_flows: Optional[List[Tuple[Any, Any]]],
    cash_replay_diagnostics: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Serialize raw audit variables into JSON-safe structures for debug output."""

    def _safe_val(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return {str(k): _safe_val(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_safe_val(v) for v in value]
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, (float, np.floating)) and np.isnan(float(value)):
            return None
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        return value

    def _safe_dict(entry: Optional[Dict[str, Any]], exclude_keys: Set[str] = frozenset()) -> Dict[str, Any]:
        return {
            str(key): _safe_val(val)
            for key, val in dict(entry or {}).items()
            if key not in exclude_keys
        }

    return {
        "synthetic_entries": [
            {
                **_safe_dict(entry),
                "date": _safe_val((entry or {}).get("date")),
            }
            for entry in (synthetic_entries or [])
        ],
        "position_timeline": {
            f"{ticker}|{ccy}|{direction}": [
                {
                    "date": _safe_val(dt),
                    "quantity": float(_helpers._as_float(qty, 0.0)),
                }
                for dt, qty in (events or [])
            ]
            for (ticker, ccy, direction), events in dict(position_timeline or {}).items()
        },
        "cash_snapshots": [
            {
                "date": _safe_val(dt),
                "cumulative_usd": round(float(_helpers._as_float(val, 0.0)), 2),
            }
            for dt, val in (cash_snapshots or [])
        ],
        "observed_cash_snapshots": [
            {
                "date": _safe_val(dt),
                "cumulative_usd": round(float(_helpers._as_float(val, 0.0)), 2),
            }
            for dt, val in (observed_cash_snapshots or [])
        ],
        "fifo_transactions": [
            _safe_dict(txn, exclude_keys={"_raw"})
            for txn in (fifo_transactions or [])
        ],
        "futures_mtm_events": [
            _safe_dict(evt)
            for evt in (futures_mtm_events or [])
        ],
        "synthetic_twr_flows": _helpers._flows_to_dict(synthetic_twr_flows or []),
        "cash_replay_diagnostics_full": {
            str(key): _safe_val(value)
            for key, value in dict(cash_replay_diagnostics or {}).items()
        },
    }


def _truncate_replay_at_date(
    cash_snapshots: List[Tuple[datetime, float]],
    cutoff_date: _date_type,
    full_replay: float,
) -> float:
    """Return the cumulative replay cash value at or before cutoff_date."""
    _ = full_replay
    if not cash_snapshots:
        return 0.0
    result = 0.0
    for snap_dt, snap_val in cash_snapshots:
        if snap_dt.date() <= cutoff_date:
            result = float(_helpers._as_float(snap_val, 0.0))
        else:
            break
    return result


def _analyze_realized_performance_single_scope(
    positions: "PositionResult",
    user_email: str,
    benchmark_ticker: str = "SPY",
    source: str = "all",
    institution: Optional[str] = None,
    account: Optional[str] = None,
    disable_statement_cash: bool = False,
    segment: str = "all",
    include_series: bool = False,
    backfill_path: Optional[str] = None,
    price_registry: ProviderRegistry | None = None,
    account_filters: Optional[list[tuple[str, str, str | None]]] = None,
    *,
    inception_override: Optional[datetime] = None,
    use_per_symbol_inception: bool = False,
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
    inception_override = _helpers._to_datetime(inception_override)
    position_rows_for_stale_checks = list(getattr(getattr(positions, "data", None), "positions", []) or [])
    allow_stale_existing_transaction_store = True
    for position_row in position_rows_for_stale_checks:
        try:
            raw_value = float(position_row.get("value") or 0.0)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(raw_value):
            continue
        if raw_value != 0.0:
            allow_stale_existing_transaction_store = False
            break
    fetch_transactions_for_source_fn = _helpers._shim_attr(
        "fetch_transactions_for_source",
        fetch_transactions_for_source,
    )
    get_schwab_security_lookup_fn = _helpers._shim_attr(
        "get_schwab_security_lookup",
        get_schwab_security_lookup,
    )
    trading_analyzer_cls = _helpers._shim_attr("TradingAnalyzer", TradingAnalyzer)
    fifo_matcher_cls = _helpers._shim_attr("FIFOMatcher", FIFOMatcher)
    get_ibkr_futures_fmp_map_fn = _helpers._shim_attr("get_ibkr_futures_fmp_map", get_ibkr_futures_fmp_map)
    fetch_monthly_close_fn = _helpers._shim_attr("fetch_monthly_close", fetch_monthly_close)
    calc_monthly_returns_fn = _helpers._shim_attr("calc_monthly_returns", calc_monthly_returns)
    extract_provider_flow_events_fn = _helpers._shim_attr(
        "extract_provider_flow_events",
        extract_provider_flow_events,
    )
    compute_performance_metrics_fn = _helpers._shim_attr(
        "compute_performance_metrics",
        compute_performance_metrics,
    )
    transaction_store_read = bool(_helpers._shim_attr("TRANSACTION_STORE_READ", TRANSACTION_STORE_READ))
    transaction_store_max_age_hours = _helpers._shim_attr(
        "TRANSACTION_STORE_MAX_AGE_HOURS",
        TRANSACTION_STORE_MAX_AGE_HOURS,
    )
    transaction_store_retry_cooldown_minutes = _helpers._shim_attr(
        "TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES",
        TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES,
    )
    realized_provider_flow_sources = _helpers._shim_attr(
        "REALIZED_PROVIDER_FLOW_SOURCES",
        REALIZED_PROVIDER_FLOW_SOURCES,
    )
    realized_use_provider_flows = bool(_helpers._shim_attr("REALIZED_USE_PROVIDER_FLOWS", REALIZED_USE_PROVIDER_FLOWS))
    realized_provider_flows_require_coverage = bool(
        _helpers._shim_attr(
            "REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE",
            REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE,
        )
    )
    backfill_file_path = _helpers._shim_attr("BACKFILL_FILE_PATH", BACKFILL_FILE_PATH)
    timing = WorkflowTimer(
        "realized_aggregation",
        requested_source=source,
        requested_segment=segment,
        institution_scoped=bool(institution),
        account_scoped=bool(account),
        include_series=bool(include_series),
        use_per_symbol_inception=bool(use_per_symbol_inception),
    )

    def _normalize_symbol(value: Any) -> str:
        return str(value or "").strip().upper()

    def _assign_canonical_segment(
        symbol: str,
        instrument_type: str,
        asset_classes: Dict[str, str],
    ) -> str | None:
        instrument_type = (instrument_type or "").strip().lower()
        if instrument_type in _EXCLUDED_INSTRUMENT_TYPES:
            if instrument_type == "unknown":
                portfolio_logger.warning(
                    "Excluding %s: unknown instrument_type — position excluded from realized performance",
                    symbol,
                )
            return None
        if instrument_type == "option":
            return "options"
        if instrument_type == "futures":
            return "futures"
        if instrument_type == "bond":
            return "bonds"
        asset_class = str(asset_classes.get(symbol, "unknown")).strip().lower()
        if asset_class in _EXCLUDED_ASSET_CLASSES:
            return None
        for canonical_segment, allowed_classes in SEGMENT_ASSET_CLASS_MAP.items():
            if asset_class in allowed_classes:
                return canonical_segment
        return "equities"

    try:
        source = source.lower().strip()
        segment = (segment or "all").strip().lower() or "all"
        if segment not in {
            "all",
            "equities",
            "options",
            "futures",
            "bonds",
            "real_estate",
            "commodities",
            "crypto",
        }:
            segment = "all"
        price_registry = price_registry or pricing._build_default_price_registry()
        institution = (institution or "").strip() or None
        account = (account or "").strip() or None
        if source not in {"all", "snaptrade", "plaid", "ibkr_flex", "ibkr_statement", "schwab", "schwab_csv"}:
            timing.finish(status="error", error="invalid_source")
            return {
                "status": "error",
                "message": (
                    "source must be one of: all, snaptrade, plaid, ibkr_flex, "
                    "ibkr_statement, schwab, schwab_csv"
                ),
            }

        if source != "all":
            warnings.append(
                "source filter applies to transactions and holdings are source-scoped when attribution is available."
            )
            with timing.step("build_source_scoped_holdings"):
                scoped_holdings = holdings._build_source_scoped_holdings(
                    positions,
                    source,
                    warnings,
                    institution=institution,
                    account=account,
                )
            current_positions = scoped_holdings.current_positions
            ticker_alias_map = dict(scoped_holdings.ticker_alias_map)
            source_holding_symbols = scoped_holdings.source_holding_symbols
            cross_source_holding_leakage_symbols = scoped_holdings.cross_source_holding_leakage_symbols
            holdings_scope = scoped_holdings.holdings_scope
        else:
            with timing.step("build_current_positions"):
                current_positions, ticker_alias_map, build_warnings = holdings._build_current_positions(
                    positions,
                    institution=institution,
                    account=account,
                )
            warnings.extend(build_warnings)
            source_holding_symbols = sorted(current_positions.keys())
            cross_source_holding_leakage_symbols: List[str] = []
            holdings_scope = "institution_scoped" if institution else "consolidated"

        enabled_provider_flow_sources = {
            str(token or "").strip().lower()
            for token in realized_provider_flow_sources
            if str(token or "").strip()
        }
        provider_flow_events_raw: List[Dict[str, Any]] = []
        provider_fetch_metadata: List[Dict[str, Any]] = []
        dedup_diagnostics: Dict[str, Any] = {}
        provider_flow_coverage: Dict[str, Dict[str, Any]] = {}
        flow_fallback_reasons: List[str] = []
        flex_option_price_rows: List[Dict[str, Any]] = []
        flow_source_breakdown = {
            "provider_authoritative_applied": 0,
            "provider_authoritative_available": 0,
            "provider_diagnostics_only": 0,
            "inferred": 0,
        }

        csv_store = CSVTransactionProvider()
        if account_filters is None and csv_store.has_source(user_email, source):
            with timing.step("load_csv_transactions"):
                store_data = csv_store.load_transactions(user_email, source)
            fifo_transactions = list(store_data.get("fifo_transactions") or [])
            if settings.EXERCISE_COST_BASIS_ENABLED:
                from trading_analysis.exercise_linkage import link_option_exercises

                fifo_transactions = link_option_exercises(fifo_transactions)
            futures_mtm_events = list(store_data.get("futures_mtm_events") or [])
            flex_option_price_rows = list(store_data.get("flex_option_price_rows") or [])
            provider_flow_events_raw = list(store_data.get("provider_flow_events") or [])
            fetch_metadata_rows = list(store_data.get("fetch_metadata") or [])
            analyzer = store_data["income_provider"]

            warnings.extend(
                provider_flows._build_fetch_metadata_warnings(
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

            provider_first_mode = True
            provider_fetch_metadata = list(fetch_metadata_rows)
        elif transaction_store_read:
            from inputs.transaction_store import (
                ensure_store_fresh,
                load_from_store,
                load_from_store_for_portfolio,
            )
            from utils.user_resolution import resolve_user_id

            user_id = resolve_user_id(user_email)
            with timing.step("load_transaction_store"):
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
            futures_mtm_events = list(store_data.get("futures_mtm_events") or [])
            flex_option_price_rows = list(store_data.get("flex_option_price_rows") or [])
            provider_flow_events_raw = list(store_data.get("provider_flow_events") or [])
            fetch_metadata_rows = list(store_data.get("fetch_metadata") or [])
            analyzer = store_data["income_provider"]

            warnings.extend(
                provider_flows._build_fetch_metadata_warnings(
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

            provider_first_mode = True
            provider_fetch_metadata = list(fetch_metadata_rows)
        else:
            with timing.step("fetch_transactions"):
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
            payload = getattr(fetch_result, "payload", fetch_result)
            fetch_metadata_rows = list(getattr(fetch_result, "fetch_metadata", []) or [])
            warnings.extend(
                provider_flows._build_fetch_metadata_warnings(
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
            with timing.step("build_schwab_security_lookup"):
                schwab_security_lookup = get_schwab_security_lookup_fn(
                    user_email=user_email,
                    source=source,
                    payload=payload,
                )
            provider_first_mode = realized_use_provider_flows

            if provider_first_mode:
                try:
                    with timing.step("extract_provider_flow_events"):
                        provider_flow_events_raw, provider_fetch_metadata = extract_provider_flow_events_fn(fetch_result)
                except Exception as exc:
                    warnings.append(
                        f"Provider-flow extraction unavailable; using inference-only cash flow reconstruction: {exc}"
                    )
                    provider_first_mode = False

            with timing.step("build_trading_analyzer"):
                analyzer = trading_analyzer_cls(
                    plaid_securities=payload.get("plaid_securities", []),
                    plaid_transactions=payload.get("plaid_transactions", []),
                    snaptrade_activities=payload.get("snaptrade_activities", []),
                    ibkr_flex_trades=payload.get("ibkr_flex_trades"),
                    ibkr_flex_cash_rows=payload.get("ibkr_flex_cash_rows"),
                    ibkr_flex_futures_mtm=payload.get("ibkr_flex_futures_mtm"),
                    schwab_transactions=payload.get("schwab_transactions", []),
                    schwab_security_lookup=schwab_security_lookup,
                    use_fifo=True,
                    account_filter=account,
                )

            fifo_transactions = list(analyzer.fifo_transactions)
            futures_mtm_events = list(payload.get("ibkr_flex_futures_mtm") or [])
            flex_option_price_rows = list(payload.get("ibkr_flex_option_prices") or [])
        backfill_metadata: Dict[str, Dict[str, Any]] = {}
        effective_backfill_path = backfill_path if backfill_path is not None else backfill_file_path
        existing_transaction_ids = {
            str(txn.get("transaction_id")).strip()
            for txn in fifo_transactions
            if str(txn.get("transaction_id") or "").strip()
        }
        with timing.step("build_backfill_entries"):
            backfill_transactions, backfill_metadata, backfill_warnings = backfill._build_backfill_entry_transactions(
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
            futures_mtm_events = [
                event
                for event in futures_mtm_events
                if match_institution(str(event.get("_institution") or event.get("institution") or ""), institution)
            ]
        if account:
            pre_count = len(fifo_transactions)
            fifo_transactions = [
                txn for txn in fifo_transactions
                if holdings._match_account(txn, account)
            ]
            warnings.append(
                f"Account filter '{account}': {len(fifo_transactions)}/{pre_count} transactions matched."
            )
            futures_mtm_events = [
                event for event in futures_mtm_events
                if holdings._match_account(event, account)
            ]
        # --- Reconcile position keys against transaction symbols via ticker_alias_map ---
        # Position snapshots use raw tickers (e.g. "AT") while Flex transactions use
        # FMP-resolved symbols (e.g. "AT.L").  ticker_alias_map has {raw: fmp} entries.
        # Remap position keys to match transaction symbols when the alias confirms.
        #
        # Evidence is net trade delta keyed by (symbol, currency), not mere symbol presence.
        # Only position-affecting trade types (BUY/SELL/SHORT/COVER) count.
        # Income rows (DIVIDEND, INTEREST, etc.) may carry a different symbol variant
        # and must not serve as evidence.
        # A remap fires only when ALL conditions hold:
        #   1. The FMP candidate has net-open same-currency trade volume (abs(delta) > 0.01)
        #   2. The raw position key does NOT have net-open same-currency trade volume
        #   3. Direction alignment: position shares sign matches candidate delta sign
        # This prevents: false positives from old closed trades, cross-direction remaps
        # (SHORT onto BUY evidence), and cross-currency remaps (GBP position onto USD trades).
        _TRADE_TYPES = {"BUY", "SELL", "SHORT", "COVER"}
        if ticker_alias_map and current_positions and fifo_transactions:
            # Compute net trade delta per symbol from position-affecting trades only.
            # Positive = net long buys, negative = net short sells.
            # Only symbols with abs(delta) > 0.01 have open-position evidence.
            # Key by (symbol, currency) so evidence is currency-specific.
            # Timeline keys are (symbol, currency, direction) - same-symbol trades in a
            # different currency are NOT evidence for a position in another currency.
            _trade_delta: Dict[Tuple[str, str], float] = defaultdict(float)
            for _t in fifo_transactions:
                _sym = str(_t.get("symbol", "")).strip()
                _ttype = str(_t.get("type", "")).upper()
                if not _sym or _ttype not in _TRADE_TYPES:
                    continue
                _tccy = str(_t.get("currency", "USD")).upper()
                _qty = abs(_helpers._as_float(_t.get("quantity"), 0.0))
                _key = (_sym, _tccy)
                if _ttype in ("BUY", "COVER"):
                    _trade_delta[_key] += _qty
                elif _ttype in ("SELL", "SHORT"):
                    _trade_delta[_key] -= _qty

            # Phase 1: Collect candidate remaps and detect multi-source collisions.
            # A "collision" is when two or more raw keys would remap to the same FMP target.
            # We count sources per target upfront so the result is iteration-order-independent.
            _candidates: Dict[str, str] = {}       # {pos_key: candidate}
            _target_sources: Dict[str, list] = {}   # {candidate: [pos_key, ...]}
            for _pos_key in list(current_positions.keys()):
                _candidate = ticker_alias_map.get(_pos_key)
                if not _candidate or _candidate == _pos_key:
                    continue
                _pos_data = current_positions[_pos_key]
                _pos_shares = _helpers._as_float(_pos_data.get("shares"), 0.0)
                _pos_ccy = str(_pos_data.get("currency", "USD")).upper()
                _cand_delta = _trade_delta.get((_candidate, _pos_ccy), 0.0)
                _raw_delta = _trade_delta.get((_pos_key, _pos_ccy), 0.0)
                if (abs(_cand_delta) > 0.01                              # candidate has same-ccy open trades
                    and abs(_raw_delta) < 0.01                           # raw key: closed/no same-ccy trades
                    and _pos_shares * _cand_delta > 0                    # direction alignment
                    and _candidate not in current_positions):
                    _candidates[_pos_key] = _candidate
                    _target_sources.setdefault(_candidate, []).append(_pos_key)

            # Phase 2: Build final remap, skipping ALL sources that collide on the same target.
            _remapped: Dict[str, str] = {}
            for _pos_key, _candidate in _candidates.items():
                if len(_target_sources[_candidate]) > 1:
                    continue  # Multiple raw keys -> same target: skip all, don't pick a winner
                _remapped[_pos_key] = _candidate

            if _remapped:
                for _old_key, _new_key in _remapped.items():
                    current_positions[_new_key] = current_positions.pop(_old_key)
                source_holding_symbols = sorted(current_positions.keys())
                warnings.append(
                    f"Reconciled {len(_remapped)} position key(s) to match transaction symbols: "
                    + ", ".join(f"{k} → {v}" for k, v in sorted(_remapped.items()))
                )
        segment_keep_symbols: set[str] = set()
        excluded_symbols_set: set[str] = set()
        if segment != "all":
            non_income_transactions = [
                txn
                for txn in fifo_transactions
                if _helpers._infer_instrument_type_from_transaction(txn) != "income"
            ]
            symbol_instrument_types: Dict[str, str] = {}
            for txn in non_income_transactions:
                symbol = _normalize_symbol(txn.get("symbol"))
                if not symbol:
                    continue
                symbol_instrument_types[symbol] = _helpers._infer_instrument_type_from_transaction(txn)
            if segment in _ASSET_CLASS_SEGMENTS:
                asset_class_symbols = sorted(
                    symbol
                    for symbol, instrument_type in symbol_instrument_types.items()
                    if instrument_type in (SEGMENT_INSTRUMENT_TYPES["equities"] | SEGMENT_INSTRUMENT_TYPES["bonds"])
                )
                segment_asset_classes = SecurityTypeService.get_asset_classes(
                    asset_class_symbols
                ) if asset_class_symbols else {}
            else:
                segment_asset_classes = {}
            for symbol, instrument_type in symbol_instrument_types.items():
                canonical = _assign_canonical_segment(
                    symbol,
                    instrument_type,
                    segment_asset_classes,
                )
                if canonical == segment:
                    segment_keep_symbols.add(symbol)
                else:
                    excluded_symbols_set.add(symbol)
            # Classify income-only symbols that paid dividends/interest but had
            # no trades within the analysis window.
            _income_only_symbols: set[str] = set()
            for inc in getattr(analyzer, "income_events", []):
                sym = _normalize_symbol(getattr(inc, "symbol", ""))
                if sym and sym not in symbol_instrument_types:
                    _income_only_symbols.add(sym)

            if _income_only_symbols:
                # Build a normalized-key lookup for current_positions instrument_type.
                _pos_itype_map: Dict[str, str] = {}
                for pos_key, pos_val in current_positions.items():
                    norm_key = _normalize_symbol(pos_key)
                    if norm_key:
                        itype = str((pos_val or {}).get("instrument_type", "")).strip().lower()
                        if itype and itype not in {"", "unknown"}:
                            _pos_itype_map[norm_key] = itype

                _income_instrument_types: Dict[str, str] = {}
                _pseudo_income_symbols: set[str] = set()
                for sym in _income_only_symbols:
                    # Position metadata always wins over pseudo classification.
                    if sym in _pos_itype_map:
                        _income_instrument_types[sym] = _pos_itype_map[sym]
                        continue
                    if _helpers._is_pseudo_symbol(sym):
                        _pseudo_income_symbols.add(sym)
                        continue
                    _income_instrument_types[sym] = "equity"

                if segment == "equities":
                    segment_keep_symbols.update(_pseudo_income_symbols)
                else:
                    excluded_symbols_set.update(_pseudo_income_symbols)

                _real_income_equity_syms = sorted(
                    s
                    for s, t in _income_instrument_types.items()
                    if t in (SEGMENT_INSTRUMENT_TYPES["equities"] | SEGMENT_INSTRUMENT_TYPES["bonds"])
                )
                if _real_income_equity_syms and segment in _ASSET_CLASS_SEGMENTS:
                    _income_asset_classes = SecurityTypeService.get_asset_classes(
                        _real_income_equity_syms
                    )
                    segment_asset_classes.update(_income_asset_classes)

                for sym, itype in _income_instrument_types.items():
                    canonical = _assign_canonical_segment(sym, itype, segment_asset_classes)
                    if canonical == segment:
                        segment_keep_symbols.add(sym)
                    elif canonical is not None:
                        excluded_symbols_set.add(sym)

            # Exclude income-only FIFO symbols not already classified.
            for txn in fifo_transactions:
                symbol = _normalize_symbol(txn.get("symbol"))
                if not symbol:
                    continue
                if (
                    _helpers._infer_instrument_type_from_transaction(txn) == "income"
                    and symbol not in symbol_instrument_types
                    and symbol not in segment_keep_symbols
                ):
                    excluded_symbols_set.add(symbol)
            pre_count = len(fifo_transactions)
            fifo_transactions = [
                txn
                for txn in fifo_transactions
                if _normalize_symbol(txn.get("symbol")) in segment_keep_symbols
            ]
            if segment_keep_symbols:
                current_positions = {
                    symbol: details
                    for symbol, details in current_positions.items()
                    if _normalize_symbol(symbol) in segment_keep_symbols
                }
                source_holding_symbols = sorted(current_positions.keys())
                source_holding_count = len(current_positions)
            else:
                current_positions = {}
                source_holding_symbols = []
                source_holding_count = 0
            if segment == "futures":
                futures_mtm_events = [
                    event
                    for event in futures_mtm_events
                    if _normalize_symbol(
                        event.get("symbol")
                        or event.get("ticker")
                        or event.get("contract_symbol")
                        or event.get("underlying")
                    ) in segment_keep_symbols
                ]
            else:
                futures_mtm_events = []
            provider_first_mode = False
            provider_flow_events_raw = []
            provider_fetch_metadata = []
            warnings.append(
                f"Segment filter '{segment}': {len(fifo_transactions)}/{pre_count} transactions matched."
            )
        fifo_transactions.sort(key=lambda t: _helpers._to_datetime(t.get("date")) or datetime.min)
        futures_mtm_events.sort(key=lambda row: _helpers._to_datetime(row.get("date")) or datetime.min)

        ibkr_stmtfunds_present_values = [
            row.get("stmtfunds_section_present")
            for row in fetch_metadata_rows
            if str(row.get("provider") or "").strip().lower() in IBKR_TRANSACTION_SOURCES
            and row.get("stmtfunds_section_present") is not None
        ]
        stmtfunds_section_present: bool | None = None
        if ibkr_stmtfunds_present_values:
            stmtfunds_section_present = any(bool(v) for v in ibkr_stmtfunds_present_values)
        has_futures_transactions = any(
            _helpers._infer_instrument_type_from_transaction(txn) == "futures"
            for txn in fifo_transactions
        )
        if stmtfunds_section_present is False and has_futures_transactions:
            warnings.append(
                "IBKR Flex StmtFunds section is missing while futures trades are present; "
                "daily futures MTM settlement is unavailable and realized performance can be materially distorted."
            )

        futures_map = get_ibkr_futures_fmp_map_fn()
        equity_symbols = {
            str(txn.get("symbol") or "").strip().upper()
            for txn in fifo_transactions
            if _helpers._infer_instrument_type_from_transaction(txn) == "equity" and txn.get("symbol")
        }
        mapped_futures_for_fmp: set[str] = set()
        for txn in fifo_transactions:
            sym = str(txn.get("symbol") or "").strip().upper()
            if (
                _helpers._infer_instrument_type_from_transaction(txn) == "futures"
                and sym in futures_map
                and sym not in mapped_futures_for_fmp
            ):
                mapped_futures_for_fmp.add(sym)
                if sym in ticker_alias_map or sym in equity_symbols:
                    warnings.append(
                        f"Futures symbol {sym} collides with equity ticker; "
                        "futures pricing skipped (equity mapping preserved)."
                    )
                else:
                    ticker_alias_map[sym] = futures_map[sym]

        if not fifo_transactions and not current_positions:
            timing.finish(status="error", error="no_transactions_or_positions")
            return {
                "status": "error",
                "message": "No transaction history and no current positions available for realized performance analysis.",
            }

        now = datetime.now(UTC).replace(tzinfo=None)
        if fifo_transactions:
            inception_from_transactions = min(
                _helpers._to_datetime(t.get("date"))
                for t in fifo_transactions
                if _helpers._to_datetime(t.get("date")) is not None
            )
            inception_from_transactions = inception_from_transactions or (now - timedelta(days=365))
        else:
            inception_from_transactions = now - timedelta(days=365)
            warnings.append(
                "No transaction history found; using 12-month synthetic inception for current holdings."
            )

        with timing.step("build_income_rows"):
            income_with_currency = nav._income_with_currency(analyzer, fifo_transactions, current_positions)
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
                if holdings._match_account(inc, account)
            ]
        if segment != "all":
            income_with_currency = [
                inc
                for inc in income_with_currency
                if _normalize_symbol(inc.get("symbol")) in segment_keep_symbols
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
                    if holdings._match_account(row, account)
                ]
                provider_fetch_metadata = [
                    row
                    for row in provider_fetch_metadata
                    if holdings._match_account(row, account)
                ]

            with timing.step("build_provider_flow_authority"):
                provider_flow_events, dedup_diagnostics = provider_flows._deduplicate_provider_flow_events(provider_flow_events)
                provider_flow_coverage, flow_fallback_reasons = provider_flows._build_provider_flow_authority(
                    provider_flow_events,
                    provider_fetch_metadata,
                    require_coverage=realized_provider_flows_require_coverage,
                )

            for event in provider_flow_events:
                when = _helpers._to_datetime(event.get("timestamp") or event.get("date"))
                if when is None:
                    continue
                is_authoritative = provider_flows._is_authoritative_slice(
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
                _helpers._to_datetime(row.get("date"))
                for row in income_with_currency
                if _helpers._to_datetime(row.get("date")) is not None
            ),
            default=None,
        )
        if first_income_date is not None:
            inception_candidates.append(first_income_date)
        first_futures_mtm_date = min(
            (
                _helpers._to_datetime(row.get("date"))
                for row in futures_mtm_events
                if _helpers._to_datetime(row.get("date")) is not None
            ),
            default=None,
        )
        if first_futures_mtm_date is not None:
            inception_candidates.append(first_futures_mtm_date)
        if provider_first_mode and first_authoritative_provider_flow_date is not None:
            inception_candidates.append(first_authoritative_provider_flow_date)

        inception_date = min(inception_candidates)
        original_inception_date = inception_date
        replay_filter_active = bool(
            inception_override is not None and inception_override > original_inception_date
        )
        if replay_filter_active:
            inception_date = inception_override

        latest_event_date = inception_date
        for txn in fifo_transactions:
            dt = _helpers._to_datetime(txn.get("date"))
            if dt and dt > latest_event_date:
                latest_event_date = dt
        for inc in income_with_currency:
            dt = _helpers._to_datetime(inc.get("date"))
            if dt and dt > latest_event_date:
                latest_event_date = dt
        for event in provider_flow_events:
            dt = _helpers._to_datetime(event.get("timestamp") or event.get("date"))
            if dt and dt > latest_event_date:
                latest_event_date = dt
        for mtm in futures_mtm_events:
            dt = _helpers._to_datetime(mtm.get("date"))
            if dt and dt > latest_event_date:
                latest_event_date = dt
        end_date = max(now, latest_event_date)

        fx_cache_start = original_inception_date if replay_filter_active else inception_date
        currencies = {"USD"}
        for pos in current_positions.values():
            currencies.add(str(pos.get("currency") or "USD").upper())
        for txn in fifo_transactions:
            currencies.add(str(txn.get("currency") or "USD").upper())
        for inc in income_with_currency:
            currencies.add(str(inc.get("currency") or "USD").upper())
        for event in provider_flow_events:
            currencies.add(str(event.get("currency") or "USD").upper())
        for mtm in futures_mtm_events:
            ccy = str(mtm.get("currency") or "USD").upper()
            if ccy != "USD":
                currencies.add(ccy)
        with timing.step("build_fx_cache"):
            fx_cache = fx._build_fx_cache(
                currencies=currencies,
                inception_date=fx_cache_start,
                end_date=end_date,
                warnings=warnings,
            )

        # Delta-gap analysis: identify symbols where short inference should be
        # suppressed because there are missing buys from before the txn window.
        visible_delta: Dict[str, float] = defaultdict(float)
        for txn in fifo_transactions:
            sym = str(txn.get("symbol", "")).strip()
            qty = abs(_helpers._as_float(txn.get("quantity"), 0.0))
            txn_type = str(txn.get("type", "")).upper()
            if txn_type in ("BUY", "COVER"):
                visible_delta[sym] += qty
            elif txn_type in ("SELL", "SHORT"):
                visible_delta[sym] -= qty

        no_infer_symbols: set[str] = set()
        for sym, delta in visible_delta.items():
            holding_shares = _helpers._as_float(current_positions.get(sym, {}).get("shares"), 0.0)
            gap = holding_shares - delta
            if gap > 0.01:  # missing buys → don't infer shorts
                no_infer_symbols.add(sym)

        first_exit_without_opening = timeline._detect_first_exit_without_opening(fifo_transactions)
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
        with timing.step("fifo_probe"):
            probe_result = fifo_matcher_cls(
                no_infer_symbols=no_infer_symbols,
            ).process_transactions(fifo_transactions)

        # Compute seeded lots from broker cost basis (FX-aware for non-USD symbols).
        with timing.step("build_seed_open_lots"):
            seeded_lots, seed_warnings = timeline._build_seed_open_lots(
                fifo_transactions=fifo_transactions,
                current_positions=current_positions,
                observed_open_lots=probe_result.open_lots,
                inception_date=inception_date,
                fx_cache=fx_cache,
            )
        warnings.extend(seed_warnings)

        # Pass 2: re-run with seeded lots (or reuse pass 1 if nothing to seed).
        if seeded_lots:
            with timing.step("fifo_seeded_pass"):
                fifo_result = fifo_matcher_cls(
                    no_infer_symbols=no_infer_symbols,
                ).process_transactions(fifo_transactions, initial_open_lots=seeded_lots)
        else:
            fifo_result = probe_result

        warnings.extend(
            backfill._emit_backfill_diagnostics(
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

        with timing.step("build_position_timeline"):
            position_timeline, synthetic_positions, synthetic_entries, instrument_meta, timeline_warnings = timeline.build_position_timeline(
                fifo_transactions=fifo_transactions,
                current_positions=current_positions,
                inception_date=inception_date,
                incomplete_trades=fifo_result.incomplete_trades,
                ticker_alias_map=ticker_alias_map or None,
                use_per_symbol_inception=use_per_symbol_inception,
            )
        warnings.extend(timeline_warnings)

        month_ends = _helpers._month_end_range(inception_date, end_date)

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

        futures_keys: set[tuple[str, str, str]] = {
            key for key, meta in instrument_meta.items()
            if coerce_instrument_type(meta.get("instrument_type"), default="equity") == "futures"
        }

        def _has_usable_mtm(events: list) -> bool:
            for e in events:
                d = _helpers._to_datetime(e.get("date"))
                if d is None:
                    continue
                if abs(_helpers._as_float(e.get("amount"), 0.0)) > 0:
                    return True
            return False

        if not futures_mtm_events or not _has_usable_mtm(futures_mtm_events):
            futures_keys = set()

        routing_priority = {
            "futures": 0,
            "fx": 1,
            "bond": 2,
            "option": 3,
            "equity": 4,
            "income": 5,
            "fx_artifact": 5,
            "unknown": 6,
        }

        # Fetch prices starting 2 months before inception so that the strict
        # backward-only price lookup in _create_synthetic_cash_events has
        # at least one prior month-end price available at the inception date.
        price_fetch_start = inception_date - timedelta(days=62)
        price_cache: Dict[str, pd.Series] = {}
        flex_option_cache = _helpers._build_option_price_cache(flex_option_price_rows)
        if flex_option_cache:
            warnings.append(
                f"Loaded {len(flex_option_cache)} option price series from IBKR Flex "
                f"PriorPeriodPosition."
            )
        unpriceable_symbols: set[str] = set()
        ibkr_priced_symbols: Dict[str, set[str]] = defaultdict(set)
        unpriceable_reason_counts: Counter[str] = Counter()
        unpriceable_reasons: Dict[str, str] = {}
        def _resolve_price_for_ticker(ticker: str) -> Dict[str, Any]:
            raw_types = ticker_instrument_types.get(ticker, {"equity"})
            instrument_type = min(raw_types, key=lambda t: routing_priority.get(t, 99))
            contract_identity = ticker_contract_identities.get(ticker)
            ticker_warnings: List[str] = []
            if len(raw_types) > 1:
                ticker_warnings.append(
                    f"Mixed instrument types for {ticker}: {sorted(raw_types)}; using {instrument_type} for pricing."
                )

            norm = pd.Series(dtype=float)
            unpriceable_reason = "no_price_data"
            ibkr_instrument_type: str | None = None
            if instrument_type in {"fx_artifact", "unknown"}:
                ticker_warnings.append(
                    f"Skipping pricing for {ticker}: instrument_type={instrument_type} should have been filtered upstream."
                )
                unpriceable_reason = f"filtered_{instrument_type}"
            elif instrument_type == "option":
                flex_series = flex_option_cache.get(ticker)
                if flex_series is not None and not flex_series.empty:
                    norm = _helpers._series_from_cache(flex_series)
                    ticker_warnings.append(
                        f"Priced option {ticker} using IBKR Flex PriorPeriodPosition daily marks "
                        f"({len(norm)} data points)."
                    )
                else:
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

                    fifo_terminal = _helpers._option_fifo_terminal_series(ticker, fifo_transactions, end_date)
                    has_fifo_terminal = not fifo_terminal.empty and not fifo_terminal.dropna().empty
                    option_expiry = _helpers._option_expiry_datetime(ticker, contract_identity)
                    end_ts = pd.Timestamp(end_date).to_pydatetime().replace(tzinfo=None)
                    option_expired = option_expiry is not None and option_expiry <= end_ts
                    current_shares = _helpers._as_float((current_positions.get(ticker) or {}).get("shares"), 0.0)
                    flat_current_holdings = abs(current_shares) <= 1e-9

                    if has_fifo_terminal and (
                        (not option_still_open)
                        or (option_expired and flat_current_holdings)
                    ):
                        norm = _helpers._series_from_cache(fifo_terminal)
                        if not norm.empty and OPTION_MULTIPLIER_NAV_ENABLED:
                            fifo_source = _helpers._option_fifo_terminal_source(
                                ticker, fifo_transactions, end_date
                            )
                            if fifo_source not in IBKR_TRANSACTION_SOURCES:
                                mult = _helpers._as_float(
                                    (contract_identity or {}).get("multiplier"), 1.0
                                )
                                if np.isfinite(mult) and mult > 1:
                                    norm = norm * mult
                                    ticker_warnings.append(
                                        f"Applied {mult:.0f}x contract multiplier to {ticker} "
                                        f"FIFO terminal price (non-Flex per-share → per-contract)."
                                    )
                        if option_still_open and option_expired and flat_current_holdings and option_expiry is not None:
                            ticker_warnings.append(
                                f"Priced expired option {ticker} using FIFO close-price terminal heuristic "
                                f"(expiry {option_expiry.date().isoformat()}, current holdings flat)."
                            )
                        else:
                            ticker_warnings.append(
                                f"Priced option {ticker} using FIFO close-price terminal heuristic."
                            )
                    else:
                        price_result = pricing._fetch_price_from_chain(
                            price_registry.get_price_chain("option"),
                            ticker,
                            price_fetch_start,
                            end_date,
                            instrument_type="option",
                            contract_identity=contract_identity,
                            ticker_alias_map=ticker_alias_map or None,
                        )
                        norm = _helpers._series_from_cache(price_result.series)
                        if not norm.empty and OPTION_MULTIPLIER_NAV_ENABLED:
                            mult = _helpers._as_float(
                                (contract_identity or {}).get("multiplier"), 1.0
                            )
                            if np.isfinite(mult) and mult > 1:
                                norm = norm * mult
                                ticker_warnings.append(
                                    f"Applied {mult:.0f}x contract multiplier to {ticker} "
                                    f"price chain prices (per-share → per-contract)."
                                )
                        local_ibkr_priced_symbols: Dict[str, set[str]] = defaultdict(set)
                        chain_reason = pricing._emit_pricing_diagnostics(
                            ticker=ticker,
                            instrument_type="option",
                            contract_identity=contract_identity,
                            result=price_result,
                            warnings=ticker_warnings,
                            ibkr_priced_symbols=local_ibkr_priced_symbols,
                        )
                        if local_ibkr_priced_symbols.get("option"):
                            ibkr_instrument_type = "option"
                        if norm.empty or norm.dropna().empty:
                            unpriceable_reason = chain_reason
            else:
                chain = price_registry.get_price_chain(instrument_type)
                if instrument_type == "bond":
                    has_ibkr = any(provider.provider_name == "ibkr" for provider in chain)
                    con_id = None
                    if isinstance(contract_identity, dict):
                        con_id = contract_identity.get("con_id")

                    existing_cusip = (
                        isinstance(contract_identity, dict) and contract_identity.get("cusip")
                    )
                    existing_isin = (
                        isinstance(contract_identity, dict) and contract_identity.get("isin")
                    )
                    sec_ids = (current_positions.get(ticker) or {}).get("security_identifiers")
                    if sec_ids and not existing_cusip:
                        enriched = dict(contract_identity) if isinstance(contract_identity, dict) else {}
                        enriched.update(sec_ids)
                        contract_identity = enriched

                    has_cusip = isinstance(contract_identity, dict) and contract_identity.get("cusip")
                    has_isin = isinstance(contract_identity, dict) and contract_identity.get("isin")
                    if has_ibkr and con_id in (None, "") and not (has_cusip or has_isin):
                        ticker_warnings.append(
                            f"No con_id, CUSIP, or ISIN for bond {ticker}; skipping IBKR bond pricing."
                        )
                        unpriceable_reason = "bond_missing_identifiers"
                    else:
                        price_result = pricing._fetch_price_from_chain(
                            chain,
                            ticker,
                            price_fetch_start,
                            end_date,
                            instrument_type=instrument_type,
                            contract_identity=contract_identity,
                            ticker_alias_map=ticker_alias_map or None,
                        )
                        norm = _helpers._series_from_cache(price_result.series)
                        local_ibkr_priced_symbols: Dict[str, set[str]] = defaultdict(set)
                        chain_reason = pricing._emit_pricing_diagnostics(
                            ticker=ticker,
                            instrument_type=instrument_type,
                            contract_identity=contract_identity,
                            result=price_result,
                            warnings=ticker_warnings,
                            ibkr_priced_symbols=local_ibkr_priced_symbols,
                        )
                        if local_ibkr_priced_symbols.get(instrument_type):
                            ibkr_instrument_type = instrument_type
                        if norm.empty or norm.dropna().empty:
                            unpriceable_reason = chain_reason
                else:
                    price_result = pricing._fetch_price_from_chain(
                        chain,
                        ticker,
                        price_fetch_start,
                        end_date,
                        instrument_type=instrument_type,
                        contract_identity=contract_identity,
                        ticker_alias_map=ticker_alias_map or None,
                    )
                    norm = _helpers._series_from_cache(price_result.series)
                    local_ibkr_priced_symbols: Dict[str, set[str]] = defaultdict(set)
                    chain_reason = pricing._emit_pricing_diagnostics(
                        ticker=ticker,
                        instrument_type=instrument_type,
                        contract_identity=contract_identity,
                        result=price_result,
                        warnings=ticker_warnings,
                        ibkr_priced_symbols=local_ibkr_priced_symbols,
                    )
                    if local_ibkr_priced_symbols.get(instrument_type):
                        ibkr_instrument_type = instrument_type
                    if norm.empty or norm.dropna().empty:
                        unpriceable_reason = chain_reason
                        if instrument_type == "equity":
                            unpriceable_reason = "equity_no_data"

            return {
                "ticker": ticker,
                "series": norm,
                "warnings": ticker_warnings,
                "unpriceable_reason": unpriceable_reason,
                "ibkr_instrument_type": ibkr_instrument_type,
            }

        price_results_by_ticker: Dict[str, Dict[str, Any]] = {}
        max_price_workers = min(len(tickers), _REALIZED_PRICE_FETCH_WORKERS)
        with timing.step("build_price_cache"):
            if max_price_workers <= 1:
                for ticker in tickers:
                    price_results_by_ticker[ticker] = _resolve_price_for_ticker(ticker)
            else:
                with ThreadPoolExecutor(max_workers=max_price_workers) as executor:
                    future_to_ticker = {
                        executor.submit(_resolve_price_for_ticker, ticker): ticker for ticker in tickers
                    }
                    for future in as_completed(future_to_ticker):
                        ticker = future_to_ticker[future]
                        try:
                            price_results_by_ticker[ticker] = future.result()
                        except Exception as exc:
                            price_results_by_ticker[ticker] = {
                                "ticker": ticker,
                                "series": pd.Series(dtype=float),
                                "warnings": [f"Price fetch failed for {ticker}: {exc}"],
                                "unpriceable_reason": "price_fetch_exception",
                                "ibkr_instrument_type": None,
                            }

        for ticker in tickers:
            ticker_result = price_results_by_ticker[ticker]
            warnings.extend(ticker_result["warnings"])
            ibkr_instrument_type = ticker_result.get("ibkr_instrument_type")
            if ibkr_instrument_type:
                ibkr_priced_symbols[ibkr_instrument_type].add(ticker)

            norm = ticker_result["series"]
            if norm.empty or norm.dropna().empty:
                warnings.append(f"No monthly prices found for {ticker}; valuing as 0 when unavailable.")
                unpriceable_symbols.add(ticker)
                unpriceable_reason = ticker_result["unpriceable_reason"]
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
            with timing.step("build_missing_timeline_fx_cache"):
                fx_cache.update(
                    fx._build_fx_cache(
                        currencies=missing_fx,
                        inception_date=inception_date,
                        end_date=end_date,
                        warnings=warnings,
                    )
                )

        synthetic_cash_events, synth_cash_warnings = timeline._create_synthetic_cash_events(
            synthetic_entries=synthetic_entries,
            price_cache=price_cache,
            fx_cache=fx_cache,
            min_notional_usd=_helpers._as_float(
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

        def _event_in_replay_window(value: Any) -> bool:
            if not replay_filter_active:
                return True
            event_dt = _helpers._to_datetime(value)
            return (event_dt or original_inception_date) >= inception_date

        if replay_filter_active:
            transactions_for_cash = [
                txn
                for txn in fifo_transactions
                if _event_in_replay_window(txn.get("date"))
            ]
            income_for_replay = [
                inc
                for inc in income_with_currency
                if _event_in_replay_window(inc.get("date"))
            ]
            mtm_for_replay = [
                event
                for event in futures_mtm_events
                if _event_in_replay_window(event.get("date"))
            ]
            flows_for_replay = [
                event
                for event in provider_flow_events
                if _event_in_replay_window(event.get("timestamp") or event.get("date"))
            ]
        else:
            transactions_for_cash = fifo_transactions
            income_for_replay = income_with_currency
            mtm_for_replay = futures_mtm_events
            flows_for_replay = provider_flow_events

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
                    cash_numeric = _helpers._as_float(cash_value, 0.0)
                    deltas.append((when, cash_numeric - prior_cash))
                    prior_cash = cash_numeric
                return deltas

            replay_diag: Dict[str, Any] = {
                "futures_txn_count_replayed": 0,
                "futures_notional_suppressed_usd": 0.0,
                "futures_fee_cash_impact_usd": 0.0,
                "futures_unknown_action_count": 0,
                "futures_missing_fx_count": 0,
                "futures_mtm_event_count": 0,
                "futures_mtm_cash_impact_usd": 0.0,
                "unpriceable_suppressed_count": 0,
                "unpriceable_suppressed_usd": 0.0,
                "unpriceable_suppressed_symbols": [],
                "income_flow_overlap_dropped_count": 0,
                "income_flow_overlap_dropped_net_usd": 0.0,
                "income_flow_overlap_dropped_by_provider": {},
                "income_flow_overlap_candidate_count": 0,
                "income_flow_overlap_alias_mismatch_count": 0,
                "income_flow_overlap_alias_mismatch_samples": [],
                "futures_inception_margin_usd": 0.0,
                "futures_inception_trade_date": None,
            }

            def _finalize_replay_diag() -> Dict[str, Any]:
                return {
                    "futures_txn_count_replayed": int(_helpers._as_float(replay_diag.get("futures_txn_count_replayed"), 0.0)),
                    "futures_notional_suppressed_usd": round(
                        _helpers._as_float(replay_diag.get("futures_notional_suppressed_usd"), 0.0),
                        2,
                    ),
                    "futures_fee_cash_impact_usd": round(
                        _helpers._as_float(replay_diag.get("futures_fee_cash_impact_usd"), 0.0),
                        2,
                    ),
                    "futures_unknown_action_count": int(_helpers._as_float(replay_diag.get("futures_unknown_action_count"), 0.0)),
                    "futures_missing_fx_count": int(_helpers._as_float(replay_diag.get("futures_missing_fx_count"), 0.0)),
                    "futures_mtm_event_count": int(_helpers._as_float(replay_diag.get("futures_mtm_event_count"), 0.0)),
                    "futures_mtm_cash_impact_usd": round(
                        _helpers._as_float(replay_diag.get("futures_mtm_cash_impact_usd"), 0.0),
                        2,
                    ),
                    "unpriceable_suppressed_count": int(
                        _helpers._as_float(replay_diag.get("unpriceable_suppressed_count"), 0.0)
                    ),
                    "unpriceable_suppressed_usd": round(
                        _helpers._as_float(replay_diag.get("unpriceable_suppressed_usd"), 0.0),
                        2,
                    ),
                    "unpriceable_suppressed_symbols": sorted(
                        {
                            str(symbol).strip().upper()
                            for symbol in list(replay_diag.get("unpriceable_suppressed_symbols", []) or [])
                            if str(symbol).strip()
                        }
                    ),
                    "income_flow_overlap_dropped_count": int(
                        _helpers._as_float(replay_diag.get("income_flow_overlap_dropped_count"), 0.0)
                    ),
                    "income_flow_overlap_dropped_net_usd": round(
                        _helpers._as_float(replay_diag.get("income_flow_overlap_dropped_net_usd"), 0.0),
                        2,
                    ),
                    "income_flow_overlap_dropped_by_provider": dict(
                        sorted((replay_diag.get("income_flow_overlap_dropped_by_provider") or {}).items())
                    ),
                    "income_flow_overlap_candidate_count": int(
                        _helpers._as_float(replay_diag.get("income_flow_overlap_candidate_count"), 0.0)
                    ),
                    "income_flow_overlap_alias_mismatch_count": int(
                        _helpers._as_float(replay_diag.get("income_flow_overlap_alias_mismatch_count"), 0.0)
                    ),
                    "income_flow_overlap_alias_mismatch_samples": list(
                        replay_diag.get("income_flow_overlap_alias_mismatch_samples") or []
                    ),
                    "futures_inception_margin_usd": round(
                        _helpers._as_float(replay_diag.get("futures_inception_margin_usd"), 0.0),
                        2,
                    ),
                    "futures_inception_trade_date": replay_diag.get("futures_inception_trade_date"),
                }

            if not provider_first_mode:
                cash_snapshots_local, external_flows_local = nav.derive_cash_and_external_flows(
                    fifo_transactions=branch_transactions,
                    income_with_currency=income_for_replay,
                    fx_cache=fx_cache,
                    futures_mtm_events=mtm_for_replay,
                    warnings=warnings,
                    replay_diagnostics=replay_diag,
                    suppress_symbols=unpriceable_symbols,
                )
                inferred_dates = [when for when, _ in external_flows_local]
                inferred_net_usd = float(sum(_helpers._as_float(amount, 0.0) for _, amount in external_flows_local))
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

            for event in flows_for_replay:
                provider = provider_flows._normalize_source_name(event.get("provider"))
                if provider not in enabled_provider_flow_sources:
                    continue

                event_date = _helpers._to_datetime(event.get("timestamp") or event.get("date"))
                if event_date is None:
                    continue

                is_authoritative = provider_flows._is_authoritative_slice(
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
                amount = _helpers._as_float(event.get("amount"), 0.0)
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
                    cash_no_inference, external_no_inference = nav.derive_cash_and_external_flows(
                        fifo_transactions=branch_transactions,
                        income_with_currency=income_for_replay,
                        fx_cache=fx_cache,
                        futures_mtm_events=mtm_for_replay,
                        force_disable_inference=True,
                        warnings=warnings,
                        replay_diagnostics=replay_diag,
                        suppress_symbols=unpriceable_symbols,
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

                fallback_cash, fallback_external = nav.derive_cash_and_external_flows(
                    fifo_transactions=branch_transactions,
                    income_with_currency=income_for_replay,
                    fx_cache=fx_cache,
                    futures_mtm_events=mtm_for_replay,
                    warnings=warnings,
                    replay_diagnostics=replay_diag,
                    suppress_symbols=unpriceable_symbols,
                )
                inferred_dates = [when for when, _ in fallback_external]
                inferred_net_usd = float(sum(_helpers._as_float(amount, 0.0) for _, amount in fallback_external))
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
                composed_cash, composed_external = nav.derive_cash_and_external_flows(
                    fifo_transactions=branch_transactions,
                    income_with_currency=income_for_replay,
                    fx_cache=fx_cache,
                    provider_flow_events=authoritative_events,
                    futures_mtm_events=mtm_for_replay,
                    warnings=warnings,
                    replay_diagnostics=replay_diag,
                    suppress_symbols=unpriceable_symbols,
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

                    event_date = _helpers._to_datetime(txn.get("date"))
                    if event_date is None:
                        fallback_branch_transactions.append(txn)
                        continue

                    provider = provider_flows._normalize_source_name(txn.get("source"))
                    if provider not in enabled_provider_flow_sources:
                        fallback_branch_transactions.append(txn)
                        continue

                    authority_status = provider_flows._authoritative_slice_status(
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
                for inc in income_for_replay:
                    event_date = _helpers._to_datetime(inc.get("date"))
                    if event_date is None:
                        fallback_branch_income.append(inc)
                        continue

                    provider = provider_flows._normalize_source_name(inc.get("source"))
                    if provider not in enabled_provider_flow_sources:
                        fallback_branch_income.append(inc)
                        continue

                    authority_status = provider_flows._authoritative_slice_status(
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

                authoritative_branch_mtm: List[Dict[str, Any]] = []
                out_of_window_branch_mtm: List[Dict[str, Any]] = []
                fallback_branch_mtm: List[Dict[str, Any]] = []
                fallback_provider_mtm_count = 0
                out_of_window_provider_mtm_count = 0
                for mtm in mtm_for_replay:
                    event_date = _helpers._to_datetime(mtm.get("date"))
                    if event_date is None:
                        fallback_branch_mtm.append(mtm)
                        continue

                    provider = provider_flows._normalize_source_name(mtm.get("provider"))
                    if provider not in enabled_provider_flow_sources:
                        fallback_branch_mtm.append(mtm)
                        continue

                    authority_status = provider_flows._authoritative_slice_status(
                        provider_flow_coverage,
                        provider=provider,
                        institution=mtm.get("institution"),
                        account_id=mtm.get("account_id"),
                        provider_account_ref=mtm.get("provider_account_ref"),
                        account_name=mtm.get("account_name"),
                        event_date=event_date,
                    )
                    if authority_status == "authoritative_in_window":
                        authoritative_branch_mtm.append(mtm)
                    elif authority_status == "authoritative_out_of_window":
                        out_of_window_branch_mtm.append(mtm)
                        out_of_window_provider_mtm_count += 1
                    else:
                        fallback_branch_mtm.append(mtm)
                        fallback_provider_mtm_count += 1

                if (
                    fallback_provider_activity_count == 0
                    and fallback_provider_income_count == 0
                    and fallback_provider_mtm_count == 0
                ):
                    composed_cash, composed_external = nav.derive_cash_and_external_flows(
                        fifo_transactions=branch_transactions,
                        income_with_currency=income_for_replay,
                        fx_cache=fx_cache,
                        provider_flow_events=authoritative_events,
                        futures_mtm_events=mtm_for_replay,
                        warnings=warnings,
                        replay_diagnostics=replay_diag,
                        suppress_symbols=unpriceable_symbols,
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

                        provider = provider_flows._normalize_source_name(txn.get("source"))
                        if provider in enabled_provider_flow_sources:
                            slice_key = provider_flows._flow_slice_key(
                                provider=provider,
                                institution=txn.get("_institution") or txn.get("institution"),
                                account_id=txn.get("account_id"),
                                provider_account_ref=txn.get("provider_account_ref"),
                                account_name=txn.get("account_name"),
                            )
                            return f"slice|{slice_key}", provider, slice_key

                        return f"non_provider|{provider}", provider, None

                    def _partition_key_for_income(inc: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
                        provider = provider_flows._normalize_source_name(inc.get("source"))
                        if provider in enabled_provider_flow_sources:
                            slice_key = provider_flows._flow_slice_key(
                                provider=provider,
                                institution=inc.get("institution"),
                                account_id=inc.get("account_id"),
                                provider_account_ref=None,
                                account_name=inc.get("account_name"),
                            )
                            return f"slice|{slice_key}", provider, slice_key
                        return f"non_provider|{provider}", provider, None

                    def _partition_key_for_mtm(mtm: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
                        provider = provider_flows._normalize_source_name(mtm.get("provider"))
                        if provider in enabled_provider_flow_sources:
                            slice_key = provider_flows._flow_slice_key(
                                provider=provider,
                                institution=mtm.get("institution"),
                                account_id=mtm.get("account_id"),
                                provider_account_ref=mtm.get("provider_account_ref"),
                                account_name=mtm.get("account_name"),
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
                                "mtm": [],
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
                                "mtm": [],
                            },
                        )
                        row["income"].append(inc)

                    for mtm in fallback_branch_mtm:
                        part_key, provider_name, slice_key = _partition_key_for_mtm(mtm)
                        row = fallback_partitions.setdefault(
                            part_key,
                            {
                                "provider": provider_name,
                                "slice_key": slice_key,
                                "transactions": [],
                                "income": [],
                                "mtm": [],
                            },
                        )
                        row["mtm"].append(mtm)

                    authoritative_cash, authoritative_external = nav.derive_cash_and_external_flows(
                        fifo_transactions=authoritative_branch_transactions,
                        income_with_currency=authoritative_branch_income,
                        fx_cache=fx_cache,
                        provider_flow_events=authoritative_events,
                        futures_mtm_events=authoritative_branch_mtm,
                        warnings=warnings,
                        replay_diagnostics=replay_diag,
                        suppress_symbols=unpriceable_symbols,
                    )
                    out_of_window_cash, out_of_window_external = nav.derive_cash_and_external_flows(
                        fifo_transactions=out_of_window_branch_transactions,
                        income_with_currency=out_of_window_branch_income,
                        fx_cache=fx_cache,
                        futures_mtm_events=out_of_window_branch_mtm,
                        force_disable_inference=True,
                        warnings=warnings,
                        replay_diagnostics=replay_diag,
                        suppress_symbols=unpriceable_symbols,
                    )

                    fallback_deltas: List[Tuple[datetime, float]] = []
                    fallback_external: List[Tuple[datetime, float]] = []
                    by_slice: Dict[str, Dict[str, Any]] = {}
                    by_provider_acc: Dict[str, Dict[str, Any]] = {}

                    for row in fallback_partitions.values():
                        partition_transactions = list(row.get("transactions") or [])
                        partition_income = list(row.get("income") or [])
                        partition_mtm = list(row.get("mtm") or [])
                        partition_cash, partition_external = nav.derive_cash_and_external_flows(
                            fifo_transactions=partition_transactions,
                            income_with_currency=partition_income,
                            fx_cache=fx_cache,
                            futures_mtm_events=partition_mtm,
                            warnings=warnings,
                            replay_diagnostics=replay_diag,
                            suppress_symbols=unpriceable_symbols,
                        )
                        fallback_deltas.extend(_snapshots_to_deltas(partition_cash))
                        fallback_external.extend(partition_external)

                        provider_name = str(row.get("provider") or "unknown")
                        slice_key = row.get("slice_key")
                        activity_dates = [
                            _helpers._to_datetime(txn.get("date"))
                            for txn in partition_transactions
                            if _helpers._to_datetime(txn.get("date")) is not None
                        ]
                        activity_dates.extend(
                            _helpers._to_datetime(inc.get("date"))
                            for inc in partition_income
                            if _helpers._to_datetime(inc.get("date")) is not None
                        )
                        activity_dates.extend(
                            _helpers._to_datetime(mtm.get("date"))
                            for mtm in partition_mtm
                            if _helpers._to_datetime(mtm.get("date")) is not None
                        )
                        inferred_dates = [when for when, _ in partition_external]
                        inferred_net_usd = float(sum(_helpers._as_float(amount, 0.0) for _, amount in partition_external))

                        provider_row = by_provider_acc.setdefault(
                            provider_name,
                            {
                                "provider": provider_name,
                                "slice_count": 0,
                                "transaction_count": 0,
                                "income_count": 0,
                                "mtm_count": 0,
                                "inferred_event_count": 0,
                                "inferred_net_usd": 0.0,
                                "_activity_dates": [],
                                "_inferred_dates": [],
                            },
                        )
                        provider_row["slice_count"] += 1
                        provider_row["transaction_count"] += len(partition_transactions)
                        provider_row["income_count"] += len(partition_income)
                        provider_row["mtm_count"] += len(partition_mtm)
                        provider_row["inferred_event_count"] += len(partition_external)
                        provider_row["inferred_net_usd"] += inferred_net_usd
                        provider_row["_activity_dates"].extend(activity_dates)
                        provider_row["_inferred_dates"].extend(inferred_dates)

                        if slice_key:
                            by_slice[slice_key] = {
                                "provider": provider_name,
                                "transaction_count": len(partition_transactions),
                                "income_count": len(partition_income),
                                "mtm_count": len(partition_mtm),
                                "inferred_event_count": len(partition_external),
                                "inferred_net_usd": round(inferred_net_usd, 2),
                                "activity_window": _window(activity_dates),
                                "inferred_event_window": _window(inferred_dates),
                            }

                    authoritative_deltas = _snapshots_to_deltas(authoritative_cash)
                    out_of_window_deltas = _snapshots_to_deltas(out_of_window_cash)
                    fallback_cash = provider_flows._combine_cash_snapshots([], fallback_deltas) if fallback_deltas else []

                    composed_cash = provider_flows._combine_cash_snapshots(
                        fallback_cash,
                        authoritative_deltas + out_of_window_deltas,
                    )
                    composed_external = sorted(
                        authoritative_external + out_of_window_external + fallback_external,
                        key=lambda row: row[0],
                    )
                    inferred_count = len(fallback_external)
                    total_inferred_net_usd = float(sum(_helpers._as_float(amount, 0.0) for _, amount in fallback_external))
                    inferred_dates = [when for when, _ in fallback_external]

                    by_provider: Dict[str, Dict[str, Any]] = {}
                    for provider_name, row in by_provider_acc.items():
                        by_provider[provider_name] = {
                            "slice_count": int(_helpers._as_float(row.get("slice_count"), 0.0)),
                            "transaction_count": int(_helpers._as_float(row.get("transaction_count"), 0.0)),
                            "income_count": int(_helpers._as_float(row.get("income_count"), 0.0)),
                            "mtm_count": int(_helpers._as_float(row.get("mtm_count"), 0.0)),
                            "inferred_event_count": int(_helpers._as_float(row.get("inferred_event_count"), 0.0)),
                            "inferred_net_usd": round(_helpers._as_float(row.get("inferred_net_usd"), 0.0), 2),
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
                        "out_of_window_provider_mtm_count": int(out_of_window_provider_mtm_count),
                        "by_provider": dict(sorted(by_provider.items())),
                        "by_slice": dict(sorted(by_slice.items())),
                    }

            external_authoritative_applied = sum(
                1
                for event in authoritative_events
                if bool(event.get("is_external_flow")) and abs(_helpers._as_float(event.get("amount"), 0.0)) > 0.0
            )

            return composed_cash, composed_external, {
                "provider_authoritative_applied": len(authoritative_events),
                "provider_authoritative_available": authoritative_available_count,
                "provider_diagnostics_only": diagnostics_only_count,
                "inferred": inferred_count if has_fallback_slices else max(0, len(composed_external) - external_authoritative_applied),
            }, inferred_flow_diagnostics, _finalize_replay_diag()

        with timing.step("compose_cash_and_external_flows"):
            (
                cash_snapshots,
                external_flows,
                flow_source_breakdown,
                inferred_flow_diagnostics,
                cash_replay_diagnostics,
            ) = _compose_cash_and_external_flows(transactions_for_cash)
        if replay_filter_active:
            cash_replay_diagnostics = dict(cash_replay_diagnostics)
            cash_replay_diagnostics.update(
                {
                    "inception_date_original": original_inception_date.date().isoformat(),
                    "inception_date_effective": inception_date.date().isoformat(),
                    "transactions_for_replay_count": len(transactions_for_cash),
                    "income_for_replay_count": len(income_for_replay),
                    "futures_mtm_for_replay_count": len(mtm_for_replay),
                    "provider_flows_for_replay_count": len(flows_for_replay),
                }
            )
        # Synthetic cash events as TWR flows - synthetic positions appear in
        # NAV, so TWR needs matching flows to treat them as contributions
        # rather than returns. BUY -> positive inflow, SHORT -> negative outflow.
        # Modified Dietz path (net_flows/tw_flows) is unaffected - the exclusion
        # from cash replay is correct for that formula.
        synthetic_twr_flows = timeline._synthetic_events_to_flows(
            synthetic_cash_events,
            fx_cache,
            price_cache=price_cache,
        )
        twr_external_flows = external_flows + synthetic_twr_flows
        alias_mismatch_count = int(_helpers._as_float(cash_replay_diagnostics.get("income_flow_overlap_alias_mismatch_count"), 0.0))
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

        _txn_account_aliases: set[str] = set()
        if source != "all":
            for txn in fifo_transactions:
                aid = str(txn.get("account_id") or "").strip().lower()
                if aid:
                    for alias in resolve_account_aliases(aid):
                        _txn_account_aliases.add(alias)

        def _cash_anchor_offset_from_positions() -> Tuple[float, int]:
            rows = list(getattr(getattr(positions, "data", None), "positions", []) or [])

            def _scan_cash(use_aliases: bool) -> Tuple[float, int]:
                cash = 0.0
                count = 0
                seen_cash_keys: set[Tuple[frozenset[str], str]] = set()
                for row in rows:
                    row_account = str(row.get("account_id") or "").strip().lower()

                    if use_aliases:
                        if not row_account or row_account not in _txn_account_aliases:
                            continue
                    elif institution:
                        brokerage_name = str(row.get("brokerage_name") or "")
                        if not match_institution(brokerage_name, institution):
                            continue
                    elif source != "all":
                        matches, _ = holdings._provider_matches_from_position_row(row)
                        if source not in matches:
                            continue

                    if account and not holdings._match_account(row, account):
                        continue

                    ticker = str(row.get("ticker") or "").strip().upper()
                    kind = str(row.get("type") or "").strip().lower()
                    if ticker.startswith("CUR:") or kind in {"cash", "currency", "fx", "forex"}:
                        if use_aliases:
                            # Deduplicate by (alias_group, ticker) to prevent
                            # double-counting from unconsolidated multi-provider rows.
                            alias_group = resolve_account_aliases(row_account)
                            dedup_key = (alias_group, ticker)
                            if dedup_key in seen_cash_keys:
                                continue
                            seen_cash_keys.add(dedup_key)
                        cash += _helpers._as_float(row.get("value"), 0.0)
                        count += 1
                return float(cash), count

            # Primary: try alias-based matching (cross-provider safe)
            if _txn_account_aliases:
                result = _scan_cash(use_aliases=True)
                if result[1] > 0:
                    return result
                # Alias matching found no cash — fall back to source/institution
                warnings.append(
                    "Cash anchor: alias matching found no cash rows; "
                    "falling back to source/institution matching."
                )
            return _scan_cash(use_aliases=False)

        def _snapshots_to_deltas_local(snapshots: List[Tuple[datetime, float]]) -> List[Tuple[datetime, float]]:
            if not snapshots:
                return []
            deltas: List[Tuple[datetime, float]] = []
            prior = 0.0
            for when, value in sorted(snapshots, key=lambda row: row[0]):
                current = _helpers._as_float(value, 0.0)
                deltas.append((when, current - prior))
                prior = current
            return deltas

        def _apply_cash_anchor(
            snapshots: List[Tuple[datetime, float]],
            anchor_snapshot: List[Tuple[datetime, float]],
        ) -> List[Tuple[datetime, float]]:
            if not anchor_snapshot:
                return snapshots
            return provider_flows._combine_cash_snapshots(
                anchor_snapshot,
                _snapshots_to_deltas_local(snapshots),
            )

        def _statement_cash_from_metadata() -> dict[str, Any] | None:
            """Extract IBKR statement cash metadata from fetch_metadata.

            Only used for IBKR transaction sources (guarded at call site).
            Returns the statement_cash dict from the first IBKR metadata row
            that carries ending_cash_usd.

            Multi-account note: IBKRFlexTransactionProvider._build_metadata()
            emits one metadata row per account slice (grouped by account_id).
            But statement_cash is set identically on ALL slices because it comes
            from one IBKR_STATEMENT_DB_PATH setting. So first-match returns the
            same value regardless of which slice is hit.

            If we ever support multiple IBKR accounts with different statements,
            this would need account-level scoping. For now, single-account is
            the only supported case.

            Returns None if no statement cash is available, falling back to the
            SnapTrade CUR:* anchor.
            """
            for row in provider_fetch_metadata:
                if str(row.get("provider") or "").strip().lower() not in IBKR_TRANSACTION_SOURCES:
                    continue
                sc = row.get("statement_cash")
                if isinstance(sc, dict) and sc.get("ending_cash_usd") is not None:
                    return sc
            return None

        cash_anchor_requested = bool(_helpers._shim_attr("REALIZED_CASH_ANCHOR_NAV", True))
        if segment != "all" and segment != "futures":
            cash_anchor_requested = False

        # Initialize all anchor locals unconditionally
        observed_end_cash = 0.0
        back_solved_start_cash = 0.0
        raw_observed_cash_anchor_offset = 0.0
        _cash_anchor_matched_rows = 0
        cash_anchor_source = "none"
        cash_anchor_available = False
        cash_anchor_applied_to_nav = False
        cash_anchor_offset_usd = 0.0
        observed_only_cash_anchor_offset_usd = 0.0
        replay_final_cash = cash_snapshots[-1][1] if cash_snapshots else 0.0
        anchor_snapshot: List[Tuple[datetime, float]] = []
        _futures_margin_available = False
        _futures_margin_anchor_usd = 0.0
        _futures_margin_anchor_date: Optional[datetime] = None
        futures_margin_anchor_applied = False
        _period_end_str: Optional[str] = None
        _stmt_end_date: Optional[_date_type] = None

        # --- Compute availability first (independent of flag) ---
        if segment == "futures":
            _inception_margin = _helpers._as_float(
                cash_replay_diagnostics.get("futures_inception_margin_usd"), 0.0
            )
            _inception_trade_date = cash_replay_diagnostics.get("futures_inception_trade_date")
            if _inception_margin > 0 and _inception_trade_date is not None:
                if isinstance(_inception_trade_date, _date_type) and not isinstance(_inception_trade_date, datetime):
                    _futures_margin_anchor_date = datetime.combine(_inception_trade_date, datetime.min.time())
                else:
                    _futures_margin_anchor_date = _inception_trade_date
                _futures_margin_available = True
                _futures_margin_anchor_usd = _inception_margin
                raw_observed_cash_anchor_offset = _inception_margin
                back_solved_start_cash = _inception_margin
                cash_anchor_source = "futures_margin"
                cash_anchor_available = True
        else:
            # Legacy observed-cash anchor path (non-futures only)
            statement_info = (
                _statement_cash_from_metadata()
                if source in IBKR_TRANSACTION_SOURCES and not disable_statement_cash
                else None
            )
            if statement_info is not None:
                observed_end_cash = float(statement_info["ending_cash_usd"])
                _cash_anchor_matched_rows = 1
                cash_anchor_source = "ibkr_statement"
                _period_end_str = statement_info.get("period_end")
                if _period_end_str:
                    try:
                        _stmt_end_date = pd.Timestamp(_period_end_str).date()
                    except Exception:
                        _stmt_end_date = None
                if _stmt_end_date and cash_snapshots:
                    replay_final_cash = _truncate_replay_at_date(
                        cash_snapshots,
                        _stmt_end_date,
                        replay_final_cash,
                    )
            else:
                observed_end_cash, _cash_anchor_matched_rows = _cash_anchor_offset_from_positions()
                cash_anchor_source = "snaptrade_cur"
            if statement_info is not None or _cash_anchor_matched_rows > 0:
                back_solved_start_cash = observed_end_cash - replay_final_cash
                raw_observed_cash_anchor_offset = back_solved_start_cash
                cash_anchor_available = abs(raw_observed_cash_anchor_offset) > 1e-9

        # --- Apply anchor (shared path, gated on flag + availability) ---
        _anchor_date = _futures_margin_anchor_date if _futures_margin_available else inception_date
        if cash_anchor_requested and cash_anchor_available:
            anchor_snapshot = [(_anchor_date, raw_observed_cash_anchor_offset)]
            cash_snapshots = _apply_cash_anchor(cash_snapshots, anchor_snapshot)
            cash_anchor_applied_to_nav = True
            cash_anchor_offset_usd = raw_observed_cash_anchor_offset
            observed_only_cash_anchor_offset_usd = raw_observed_cash_anchor_offset
            if _futures_margin_available:
                futures_margin_anchor_applied = True
        elif cash_anchor_requested and not cash_anchor_available and segment != "futures":
            warnings.append(
                "REALIZED_CASH_ANCHOR_NAV enabled but no observed cash snapshot is available; continuing without anchor."
            )

        eval_dates = _helpers._business_day_range(inception_date, end_date)
        legacy_monthly_return_path = nav.compute_monthly_returns is not _helpers._ORIGINAL_COMPUTE_MONTHLY_RETURNS
        month_end_index = pd.DatetimeIndex(pd.to_datetime(month_ends)).sort_values()

        with timing.step("build_primary_nav_series"):
            if legacy_monthly_return_path:
                inception_nav_value = float(
                    nav.compute_monthly_nav(
                        position_timeline=position_timeline,
                        month_ends=[inception_date],
                        price_cache=price_cache,
                        fx_cache=fx_cache,
                        cash_snapshots=cash_snapshots,
                        futures_keys=futures_keys,
                    ).iloc[0]
                )
                monthly_nav = nav.compute_monthly_nav(
                    position_timeline=position_timeline,
                    month_ends=month_ends,
                    price_cache=price_cache,
                    fx_cache=fx_cache,
                    cash_snapshots=cash_snapshots,
                    futures_keys=futures_keys,
                )
                daily_nav = monthly_nav.copy()
            else:
                daily_nav = nav.compute_monthly_nav(
                    position_timeline=position_timeline,
                    month_ends=eval_dates,
                    price_cache=price_cache,
                    fx_cache=fx_cache,
                    cash_snapshots=cash_snapshots,
                    futures_keys=futures_keys,
                )
                monthly_nav = pd.Series(
                    [_helpers._value_at_or_before(daily_nav, ts, default=np.nan) for ts in month_end_index],
                    index=month_end_index,
                    dtype=float,
                ).dropna()

        net_flows, tw_flows = nav.compute_monthly_external_flows(
            external_flows=external_flows,
            month_ends=month_ends,
        )

        observed_position_timeline, _, _, _, _ = timeline.build_position_timeline(
            fifo_transactions=fifo_transactions,
            current_positions={},
            inception_date=inception_date,
            incomplete_trades=fifo_result.incomplete_trades,
            ticker_alias_map=ticker_alias_map or None,
            use_per_symbol_inception=use_per_symbol_inception,
        )
        # Observed-only branch must exclude provider-authoritative flow events so
        # synthetic impact reflects the delta between provider-driven and
        # transaction-only replay traces.
        observed_cash_snapshots, observed_external_flows = nav.derive_cash_and_external_flows(
            fifo_transactions=transactions_for_cash,
            income_with_currency=income_for_replay,
            fx_cache=fx_cache,
            futures_mtm_events=mtm_for_replay,
            warnings=warnings,
            suppress_symbols=unpriceable_symbols,
        )
        if cash_anchor_applied_to_nav:
            if futures_margin_anchor_applied:
                observed_only_cash_anchor_offset_usd = _futures_margin_anchor_usd
                observed_anchor_snapshot = [(_futures_margin_anchor_date, _futures_margin_anchor_usd)]
                observed_cash_snapshots = _apply_cash_anchor(observed_cash_snapshots, observed_anchor_snapshot)
            else:
                observed_replay_final = observed_cash_snapshots[-1][1] if observed_cash_snapshots else 0.0
                if _stmt_end_date and observed_cash_snapshots:
                    observed_replay_final = _truncate_replay_at_date(
                        observed_cash_snapshots,
                        _stmt_end_date,
                        observed_replay_final,
                    )
                observed_back_solved_start = observed_end_cash - observed_replay_final
                observed_only_cash_anchor_offset_usd = observed_back_solved_start
                observed_anchor_snapshot = [(inception_date, observed_back_solved_start)]
                observed_cash_snapshots = _apply_cash_anchor(observed_cash_snapshots, observed_anchor_snapshot)
        with timing.step("build_observed_nav_series"):
            if legacy_monthly_return_path:
                observed_monthly_nav = nav.compute_monthly_nav(
                    position_timeline=observed_position_timeline,
                    month_ends=month_ends,
                    price_cache=price_cache,
                    fx_cache=fx_cache,
                    cash_snapshots=observed_cash_snapshots,
                    futures_keys=futures_keys,
                )
                observed_daily_nav = observed_monthly_nav.copy()
            else:
                observed_daily_nav = nav.compute_monthly_nav(
                    position_timeline=observed_position_timeline,
                    month_ends=eval_dates,
                    price_cache=price_cache,
                    fx_cache=fx_cache,
                    cash_snapshots=observed_cash_snapshots,
                    futures_keys=futures_keys,
                )
                observed_monthly_nav = pd.Series(
                    [_helpers._value_at_or_before(observed_daily_nav, ts, default=np.nan) for ts in month_end_index],
                    index=month_end_index,
                    dtype=float,
                ).dropna()
        observed_net_flows, observed_tw_flows = nav.compute_monthly_external_flows(
            external_flows=observed_external_flows,
            month_ends=month_ends,
        )

        if provider_first_mode and flow_fallback_reasons:
            warnings.append(
                f"Provider-flow fallback applied on {len(flow_fallback_reasons)} slice(s); "
                "inference used for non-authoritative partitions."
            )

        with timing.step("build_monthly_returns"):
            if legacy_monthly_return_path:
                monthly_returns, return_warnings = nav.compute_monthly_returns(
                    monthly_nav=monthly_nav,
                    net_flows=net_flows,
                    time_weighted_flows=tw_flows,
                    inception_nav=inception_nav_value,
                )
            else:
                monthly_returns, return_warnings = nav.compute_twr_monthly_returns(
                    daily_nav=daily_nav,
                    external_flows=twr_external_flows,
                    month_ends=month_ends,
                )
        warnings.extend(return_warnings)

        total_cost_basis_usd = 0.0
        current_portfolio_value = 0.0
        current_position_keys: set[Tuple[str, str, str]] = set()
        for ticker, pos in current_positions.items():
            shares = _helpers._as_float(pos.get("shares"), 0.0)
            if abs(shares) < 1e-9:
                continue
            direction = "SHORT" if shares < 0 else "LONG"
            currency = str(pos.get("currency") or "USD").upper()
            current_position_keys.add((ticker, currency, direction))
            current_portfolio_value += _helpers._as_float(pos.get("value"), 0.0)

            cb = pos.get("cost_basis")
            if cb is not None:
                cost_basis_value = _helpers._as_float(cb, 0.0)
                if not bool(pos.get("cost_basis_is_usd", False)):
                    cost_basis_value *= fx._event_fx_rate(currency, end_date, fx_cache)
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

        low_coverage_threshold = _helpers._as_float(
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
                abs(_helpers._as_float((current_positions.get(ticker) or {}).get("value"), 0.0))
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
        extreme_abs_return_threshold = _helpers._as_float(
            DATA_QUALITY_THRESHOLDS.get("realized_extreme_monthly_return_abs", 3.0),
            3.0,
        )
        extreme_return_months: List[Dict[str, Any]] = []
        for ts in monthly_returns.index:
            raw = _helpers._as_float(monthly_returns.loc[ts], default=np.nan)
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
                        "monthly_nav": round(_helpers._as_float(monthly_nav.get(ts), 0.0), 2),
                        "monthly_net_flow": round(_helpers._as_float(net_flows.get(ts), 0.0), 2),
                    }
                )

        monthly_returns = monthly_returns.replace([np.inf, -np.inf], np.nan).dropna()
        if monthly_returns.empty:
            timing.finish(status="error", error="no_valid_monthly_returns")
            return {
                "status": "error",
                "message": "No valid monthly return observations available after NAV/flow reconstruction.",
                "data_warnings": sorted(set(warnings)),
            }

        benchmark_start = (
            (pd.Timestamp(inception_date).to_period("M") - 1)
            .to_timestamp()
            .to_pydatetime()
            .replace(tzinfo=None)
        )
        with timing.step("build_benchmark_returns"):
            benchmark_prices = fetch_monthly_close_fn(
                benchmark_ticker,
                start_date=benchmark_start,
                end_date=end_date,
                ticker_alias_map=ticker_alias_map or None,
            )
            benchmark_returns = calc_monthly_returns_fn(benchmark_prices)
        benchmark_returns = _helpers._series_from_cache(benchmark_returns)
        monthly_returns = _helpers._normalize_monthly_index(monthly_returns)
        benchmark_returns = _helpers._normalize_monthly_index(benchmark_returns)

        aligned = pd.DataFrame(
            {
                "portfolio": monthly_returns,
                "benchmark": benchmark_returns,
            }
        ).dropna()

        if aligned.empty:
            timing.finish(status="error", error="no_benchmark_overlap")
            return {
                "status": "error",
                "message": f"No overlapping monthly returns between portfolio and benchmark {benchmark_ticker}.",
                "data_warnings": sorted(set(warnings)),
            }

        source_breakdown = dict(Counter(str(t.get("source") or "unknown") for t in fifo_transactions))
        source_transaction_count = len(fifo_transactions)
        realized_pnl = float(backfill._compute_realized_pnl_usd(fifo_result.closed_trades, fx_cache))
        incomplete_pnl = float(
            backfill._compute_incomplete_trade_pnl_usd(fifo_result.incomplete_trades, fx_cache)
        )
        realized_pnl += incomplete_pnl
        unrealized_pnl = float(
            nav._compute_unrealized_pnl_usd(
                fifo_result=fifo_result,
                price_cache=price_cache,
                fx_cache=fx_cache,
                as_of=end_date,
            )
        )
        net_contributions = float(nav._compute_net_contributions_usd(fifo_transactions, fx_cache))
        aligned_start = aligned.index.min()
        aligned_end = aligned.index.max()
        official_nav_start = _helpers._value_at_or_before(monthly_nav, aligned_start, default=np.nan)
        official_nav_end = _helpers._value_at_or_before(monthly_nav, aligned_end, default=np.nan)
        cumulative_net_external_flows = float(
            net_flows.reindex(aligned.index).fillna(0.0).sum()
        )
        observed_nav_start = _helpers._value_at_or_before(observed_monthly_nav, aligned_start, default=np.nan)
        observed_nav_end = _helpers._value_at_or_before(observed_monthly_nav, aligned_end, default=np.nan)
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

        income_summary_usd = backfill._summarize_income_usd(income_with_currency, fx_cache)
        income_total = _helpers._as_float(income_summary_usd.get("total"), 0.0)
        lot_pnl_usd = float(realized_pnl + unrealized_pnl + income_total)
        reconciliation_gap_usd = float(nav_pnl_usd - lot_pnl_usd)

        income_yield_on_cost = (
            (_helpers._as_float(income_summary_usd.get("projected_annual"), 0.0) / total_cost_basis_usd) * 100.0
            if total_cost_basis_usd > 0
            else 0.0
        )
        income_yield_on_value = (
            (_helpers._as_float(income_summary_usd.get("projected_annual"), 0.0) / current_portfolio_value) * 100.0
            if current_portfolio_value > 0
            else 0.0
        )
        nav_metrics_estimated = bool(
            synthetic_current_tickers
            or data_coverage < low_coverage_threshold
            or len(unpriceable_symbols_sorted) > 0
        )
        synthetic_sensitivity_threshold_usd = _helpers._as_float(
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
            abs(reconciliation_gap_usd) / max(abs(_helpers._as_float(official_nav_end, 0.0)), 1000.0) * 100.0  # uses synthetic-enhanced NAV end
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

        risk_free_rate = nav._safe_treasury_rate(inception_date, end_date)
        min_capm = DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 24)
        selected_aligned = aligned

        start_iso = selected_aligned.index.min().date().isoformat()
        end_iso = selected_aligned.index.max().date().isoformat()

        with timing.step("compute_performance_metrics"):
            performance_metrics = compute_performance_metrics_fn(
                portfolio_returns=selected_aligned["portfolio"],
                benchmark_returns=selected_aligned["benchmark"],
                risk_free_rate=risk_free_rate,
                benchmark_ticker=benchmark_ticker,
                start_date=start_iso,
                end_date=end_iso,
                min_capm_observations=min_capm,
            )

        mwr_value, mwr_status = _mwr.compute_mwr(
            external_flows=external_flows,
            nav_start=official_nav_start,
            nav_end=official_nav_end,
            start_date=aligned_start,
            end_date=aligned_end,
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
                "event_count": int(_helpers._as_float(row.get("event_count"), 0.0)),
                "coverage_start": (
                    _helpers._to_datetime(row.get("coverage_start")).isoformat()
                    if _helpers._to_datetime(row.get("coverage_start")) is not None
                    else None
                ),
                "coverage_end": (
                    _helpers._to_datetime(row.get("coverage_end")).isoformat()
                    if _helpers._to_datetime(row.get("coverage_end")) is not None
                    else None
                ),
                "has_error": bool(row.get("has_error")),
                "has_partial": bool(row.get("has_partial")),
                "deterministic_no_flow": bool(row.get("deterministic_no_flow")),
                "unmapped_row_count": int(_helpers._as_float(row.get("unmapped_row_count"), 0.0)),
            }

        def _build_nav_components(
            nav_series: pd.Series,
            cash_points: List[Tuple[datetime, float]],
        ) -> Dict[str, Dict[str, float]]:
            if nav_series is None or len(nav_series) == 0:
                return {}
            nav_idx = pd.DatetimeIndex(pd.to_datetime(nav_series.index)).sort_values()
            cash_series = _helpers._month_end_cash_series(cash_points, nav_idx)
            out: Dict[str, Dict[str, float]] = {}
            for ts in nav_idx:
                nav_usd = _helpers._as_float(nav_series.get(ts), 0.0)
                cash_usd = _helpers._as_float(cash_series.get(ts), 0.0)
                out[ts.date().isoformat()] = {
                    "nav_usd": float(nav_usd),
                    "cash_value_usd": float(cash_usd),
                    "positions_value_usd": float(nav_usd - cash_usd),
                }
            return out

        monthly_nav_components = _build_nav_components(monthly_nav, cash_snapshots)
        observed_only_monthly_nav_components = _build_nav_components(observed_monthly_nav, observed_cash_snapshots)

        realized_metadata = {
            "realized_pnl": round(realized_pnl, 2),
            "incomplete_pnl": round(incomplete_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "net_contributions": round(net_contributions, 2),
            "external_net_flows_usd": round(cumulative_net_external_flows, 2),
            "money_weighted_return": round(mwr_value * 100.0, 2) if mwr_value is not None else None,
            "mwr_status": mwr_status,
            "cash_anchor_available": bool(cash_anchor_available),
            "cash_anchor_applied_to_nav": bool(cash_anchor_applied_to_nav),
            "cash_anchor_offset_usd": round(_helpers._as_float(cash_anchor_offset_usd, 0.0), 2),
            "cash_backsolve_observed_end_usd": round(_helpers._as_float(observed_end_cash, 0.0), 2),
            "cash_backsolve_replay_final_usd": round(_helpers._as_float(replay_final_cash, 0.0), 2),
            "cash_backsolve_start_usd": round(_helpers._as_float(back_solved_start_cash, 0.0), 2),
            "cash_backsolve_matched_rows": _cash_anchor_matched_rows,
            "cash_anchor_source": cash_anchor_source,
            "cash_anchor_statement_period_end": (
                _period_end_str if cash_anchor_source == "ibkr_statement" else None
            ),
            "observed_only_cash_anchor_offset_usd": round(
                _helpers._as_float(observed_only_cash_anchor_offset_usd, 0.0),
                2,
            ),
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
            "segment": segment,
            "excluded_symbols": sorted(excluded_symbols_set),
            "cross_source_holding_leakage_symbols": cross_source_holding_leakage_symbols,
            "income": {
                "total": round(income_total, 2),
                "dividends": round(_helpers._as_float(income_summary_usd.get("dividends"), 0.0), 2),
                "interest": round(_helpers._as_float(income_summary_usd.get("interest"), 0.0), 2),
                "by_month": income_summary_usd.get("by_month", {}),
                "by_symbol": income_summary_usd.get("by_symbol", {}),
                "by_institution": income_summary_usd.get("by_institution", {}),
                "current_monthly_rate": round(_helpers._as_float(income_summary_usd.get("current_monthly_rate"), 0.0), 2),
                "projected_annual": round(_helpers._as_float(income_summary_usd.get("projected_annual"), 0.0), 2),
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
            "futures_cash_policy": (
                "fee_and_mtm"
                if int(_helpers._as_float(cash_replay_diagnostics.get("futures_mtm_event_count"), 0.0)) > 0
                else "fee_only"
            ),
            "futures_margin_anchor_applied": bool(futures_margin_anchor_applied),
            "futures_margin_anchor_usd": round(_futures_margin_anchor_usd if futures_margin_anchor_applied else 0.0, 2),
            "futures_txn_count_replayed": int(_helpers._as_float(cash_replay_diagnostics.get("futures_txn_count_replayed"), 0.0)),
            "futures_notional_suppressed_usd": round(
                _helpers._as_float(cash_replay_diagnostics.get("futures_notional_suppressed_usd"), 0.0),
                2,
            ),
            "unpriceable_suppressed_count": int(
                _helpers._as_float(cash_replay_diagnostics.get("unpriceable_suppressed_count"), 0.0)
            ),
            "unpriceable_suppressed_usd": round(
                _helpers._as_float(cash_replay_diagnostics.get("unpriceable_suppressed_usd"), 0.0),
                2,
            ),
            "unpriceable_suppressed_symbols": sorted(
                {
                    str(symbol).strip().upper()
                    for symbol in list(cash_replay_diagnostics.get("unpriceable_suppressed_symbols", []) or [])
                    if str(symbol).strip()
                }
            ),
            "futures_fee_cash_impact_usd": round(
                _helpers._as_float(cash_replay_diagnostics.get("futures_fee_cash_impact_usd"), 0.0),
                2,
            ),
            "futures_unknown_action_count": int(
                _helpers._as_float(cash_replay_diagnostics.get("futures_unknown_action_count"), 0.0)
            ),
            "futures_missing_fx_count": int(
                _helpers._as_float(cash_replay_diagnostics.get("futures_missing_fx_count"), 0.0)
            ),
            "futures_mtm_event_count": int(
                _helpers._as_float(cash_replay_diagnostics.get("futures_mtm_event_count"), 0.0)
            ),
            "futures_mtm_cash_impact_usd": round(
                _helpers._as_float(cash_replay_diagnostics.get("futures_mtm_cash_impact_usd"), 0.0),
                2,
            ),
            "income_flow_overlap_dropped_count": int(
                _helpers._as_float(cash_replay_diagnostics.get("income_flow_overlap_dropped_count"), 0.0)
            ),
            "income_flow_overlap_dropped_net_usd": round(
                _helpers._as_float(cash_replay_diagnostics.get("income_flow_overlap_dropped_net_usd"), 0.0),
                2,
            ),
            "income_flow_overlap_dropped_by_provider": dict(
                sorted((cash_replay_diagnostics.get("income_flow_overlap_dropped_by_provider") or {}).items())
            ),
            "income_flow_overlap_candidate_count": int(
                _helpers._as_float(cash_replay_diagnostics.get("income_flow_overlap_candidate_count"), 0.0)
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
                "daily_nav": {
                    ts.date().isoformat(): float(val)
                    for ts, val in daily_nav.items()
                },
                "observed_only_monthly_nav": {
                    ts.date().isoformat(): float(val)
                    for ts, val in observed_monthly_nav.items()
                },
                "observed_only_daily_nav": {
                    ts.date().isoformat(): float(val)
                    for ts, val in observed_daily_nav.items()
                },
                "monthly_nav_components": monthly_nav_components,
                "monthly_nav_components_cash_anchored": monthly_nav_components,
                "observed_only_monthly_nav_components": observed_only_monthly_nav_components,
                "observed_only_monthly_nav_components_cash_anchored": observed_only_monthly_nav_components,
                "net_flows": {
                    ts.date().isoformat(): float(val)
                    for ts, val in net_flows.items()
                },
                "external_flows": _helpers._flows_to_dict(twr_external_flows),
                "investor_external_flows": _helpers._flows_to_dict(external_flows),
                "observed_only_net_flows": {
                    ts.date().isoformat(): float(val)
                    for ts, val in observed_net_flows.items()
                },
                "observed_only_external_flows": _helpers._flows_to_dict(observed_external_flows),
                "time_weighted_flows": {
                    ts.date().isoformat(): float(val)
                    for ts, val in tw_flows.items()
                },
                "risk_free_rate": float(risk_free_rate),
                "benchmark_ticker": benchmark_ticker,
                "audit_trail": _serialize_audit_trail(
                    synthetic_entries,
                    position_timeline,
                    cash_snapshots,
                    observed_cash_snapshots,
                    fifo_transactions,
                    futures_mtm_events,
                    synthetic_twr_flows,
                    cash_replay_diagnostics,
                ),
            },
        }
        if replay_filter_active:
            realized_metadata["inception_date_original"] = original_inception_date.date().isoformat()

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
        performance_metrics["money_weighted_return"] = realized_metadata["money_weighted_return"]
        performance_metrics["net_contributions_definition"] = realized_metadata["net_contributions_definition"]

        timing.finish(
            status="success",
            transaction_count=len(fifo_transactions),
            holding_count=len(current_positions),
            ticker_count=len(tickers),
            month_count=len(month_ends),
            provider_first_mode=provider_first_mode,
            fallback_slice_count=len(flow_fallback_reasons),
        )
        from core.result_objects import RealizedPerformanceResult
        return RealizedPerformanceResult.from_analysis_dict(performance_metrics)

    except Exception as exc:
        timing.finish(status="exception", error_type=type(exc).__name__)
        return {
            "status": "error",
            "message": f"Realized performance analysis failed: {exc}",
            "data_warnings": sorted(set(warnings)) if warnings else [],
        }

__all__ = [
    '_analyze_realized_performance_single_scope',
]
