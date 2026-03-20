from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as _date_type
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
from brokerage.futures import get_contract_spec
from portfolio_risk_engine.providers import get_fx_provider
from providers.flows.common import build_slice_key
from providers.flows.extractor import extract_provider_flow_events
from providers.fmp_price import FMPPriceProvider
from providers.ibkr_price import IBKRPriceProvider
from providers.interfaces import PriceSeriesProvider
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
from trading_analysis.instrument_meta import InstrumentMeta, coerce_instrument_type
from trading_analysis.symbol_utils import parse_option_contract_identity_from_symbol

from . import _helpers, fx as fx_module, provider_flows

def derive_cash_and_external_flows(
    fifo_transactions: List[Dict[str, Any]],
    income_with_currency: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
    provider_flow_events: Optional[List[Dict[str, Any]]] = None,
    futures_mtm_events: Optional[List[Dict[str, Any]]] = None,
    *,
    disable_inference_when_provider_mode: bool = True,
    force_disable_inference: bool = False,
    warnings: Optional[List[str]] = None,
    replay_diagnostics: Optional[Dict[str, Any]] = None,
    suppress_symbols: Optional[Set[str]] = None,
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
        replay_diagnostics.setdefault("futures_mtm_event_count", 0)
        replay_diagnostics.setdefault("futures_mtm_cash_impact_usd", 0.0)
        replay_diagnostics.setdefault("unpriceable_suppressed_count", 0)
        replay_diagnostics.setdefault("unpriceable_suppressed_usd", 0.0)
        replay_diagnostics.setdefault("unpriceable_suppressed_symbols", [])
        replay_diagnostics.setdefault("income_flow_overlap_dropped_count", 0)
        replay_diagnostics.setdefault("income_flow_overlap_dropped_net_usd", 0.0)
        replay_diagnostics.setdefault("income_flow_overlap_dropped_by_provider", {})
        replay_diagnostics.setdefault("income_flow_overlap_candidate_count", 0)
        replay_diagnostics.setdefault("income_flow_overlap_alias_mismatch_count", 0)
        replay_diagnostics.setdefault("income_flow_overlap_alias_mismatch_samples", [])
        replay_diagnostics.setdefault("futures_inception_margin_usd", 0.0)
        replay_diagnostics.setdefault("futures_inception_trade_date", None)
    _suppress_symbols = {
        str(symbol).strip().upper()
        for symbol in (suppress_symbols or set())
        if str(symbol).strip()
    }

    def _fx_with_futures_default(currency: str, when: datetime) -> Tuple[float, bool]:
        ccy = str(currency or "USD").upper()
        if ccy == "USD":
            return 1.0, False

        fx_series = fx_cache.get(ccy)
        if fx_series is None or len(fx_series) == 0:
            return 1.0, True

        fx_value = _helpers._value_at_or_before(fx_series, when, default=np.nan)
        if not np.isfinite(_helpers._as_float(fx_value, default=np.nan)) or _helpers._as_float(fx_value, default=np.nan) <= 0:
            return 1.0, True

        return float(_helpers._as_float(fx_value, default=1.0)), False

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
        provider_flow_events_for_replay, overlap_diagnostics = provider_flows._dedupe_income_provider_internal_flow_overlap(
            income_with_currency=income_with_currency,
            provider_flow_events=provider_flow_events_for_replay,
        )

    events: List[Dict[str, Any]] = []
    _skipped_unknown = 0
    _skipped_non_trade = 0
    _futures_count = 0
    _futures_mtm_count = 0

    for txn in fifo_transactions:
        date = _helpers._to_datetime(txn.get("date"))
        if date is None:
            continue

        instrument_type = _helpers._infer_instrument_type_from_transaction(txn)
        if instrument_type == "unknown":
            _skipped_unknown += 1
            continue
        if instrument_type in ("fx_artifact", "income"):
            _skipped_non_trade += 1
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
                "price": _helpers._as_float(txn.get("price"), 0.0),
                "quantity": abs(_helpers._as_float(txn.get("quantity"), 0.0)),
                "fee": abs(_helpers._as_float(txn.get("fee"), 0.0)),
                "currency": str(txn.get("currency") or "USD").upper(),
                "is_futures": is_futures,
                "symbol": symbol,
                "instrument_type": instrument_type,
                "source": str(txn.get("source") or "").strip().lower(),
                "multiplier": _helpers._as_float(
                    (txn.get("contract_identity") or {}).get("multiplier"), 1.0
                ),
                "expiry": str((txn.get("contract_identity") or {}).get("expiry") or ""),
                "con_id": str((txn.get("contract_identity") or {}).get("con_id") or ""),
            }
        )

    if warnings is not None and _skipped_unknown > 0:
        warnings.append(
            f"Cash replay: skipped {_skipped_unknown} unknown/empty-symbol transaction(s)."
        )
    if warnings is not None and _skipped_non_trade > 0:
        warnings.append(
            f"Cash replay: skipped {_skipped_non_trade} non-trade transaction(s) (fx_artifact/income)."
        )
    if warnings is not None and _futures_count > 0:
        warnings.append(
            f"Cash replay: replaying {_futures_count} futures transaction(s); "
            "inference is suppressed while futures exposure is open."
        )

    for inc in income_with_currency:
        date = _helpers._to_datetime(inc.get("date"))
        if date is None:
            continue
        events.append(
            {
                "date": date,
                "event_type": "INCOME",
                "amount": _helpers._as_float(inc.get("amount"), 0.0),
                "currency": str(inc.get("currency") or "USD").upper(),
            }
        )

    for provider_flow in provider_flow_events_for_replay:
        date = _helpers._to_datetime(provider_flow.get("timestamp") or provider_flow.get("date"))
        if date is None:
            continue
        amount = _helpers._as_float(provider_flow.get("amount"), 0.0)
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

    for mtm in (futures_mtm_events or []):
        date = _helpers._to_datetime(mtm.get("date"))
        if date is None:
            continue
        amount = _helpers._as_float(mtm.get("amount"), 0.0)
        if amount == 0:
            continue
        _futures_mtm_count += 1
        events.append(
            {
                "date": date,
                "event_type": "FUTURES_MTM",
                "amount": amount,
                "currency": str(mtm.get("currency") or "USD").upper(),
                "symbol": str(mtm.get("symbol") or "").strip().upper(),
                # MTM settlement is a cash event, not a futures trade event.
                "is_futures": False,
            }
        )

    events.sort(key=lambda e: (e["date"], _helpers.TYPE_ORDER.get(e["event_type"], 99)))

    cash = 0.0
    outstanding_injections = 0.0
    cash_snapshots: List[Tuple[datetime, float]] = []
    external_flows: List[Tuple[datetime, float]] = []
    provider_mode = bool(provider_flow_events)
    inference_enabled = ((not provider_mode) or (not disable_inference_when_provider_mode)) and not force_disable_inference
    _DEFAULT_MARGIN_RATE = 0.10
    _futures_positions: Dict[Tuple[str, str], float] = {}
    _futures_contract_price: Dict[Tuple[str, str], float] = {}
    _futures_contract_fx: Dict[Tuple[str, str], float] = {}
    _futures_contract_margin_rate: Dict[Tuple[str, str], float] = {}
    _futures_contract_multiplier: Dict[Tuple[str, str], float] = {}
    _futures_inception_margin_captured = False
    futures_inception_margin_usd = 0.0
    _futures_inception_date: Optional[_date_type] = None
    futures_notional_suppressed_usd = 0.0
    futures_fee_cash_impact_usd = 0.0
    futures_unknown_action_count = 0
    futures_missing_fx_count = 0
    futures_mtm_cash_impact_usd = 0.0
    unpriceable_suppressed_count = 0
    unpriceable_suppressed_usd = 0.0
    unpriceable_suppressed_symbols: set[str] = set()

    for event in events:
        event_type = event["event_type"]
        is_futures = bool(event.get("is_futures", False))
        normalized_symbol = str(event.get("symbol") or "").strip().upper()
        if is_futures:
            fx, missing_fx = _fx_with_futures_default(event.get("currency", "USD"), event["date"])
            if missing_fx:
                futures_missing_fx_count += 1
        elif event_type == "FUTURES_MTM":
            fx, missing_fx = _fx_with_futures_default(event.get("currency", "USD"), event["date"])
            if missing_fx:
                futures_missing_fx_count += 1
        else:
            fx = fx_module._event_fx_rate(event.get("currency", "USD"), event["date"], fx_cache)

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
        elif normalized_symbol in _suppress_symbols and event_type in {"BUY", "SELL", "SHORT", "COVER"}:
            unpriceable_suppressed_count += 1
            _sup_pq = event["price"] * event["quantity"]
            if (
                OPTION_MULTIPLIER_NAV_ENABLED
                and event.get("instrument_type") == "option"
                and event.get("source") not in IBKR_TRANSACTION_SOURCES
            ):
                _sup_mult = _helpers._as_float(event.get("multiplier"), 1.0)
                if np.isfinite(_sup_mult) and _sup_mult > 1:
                    _sup_pq = _sup_pq * _sup_mult
            unpriceable_suppressed_usd += abs(_sup_pq * fx)
            if normalized_symbol:
                unpriceable_suppressed_symbols.add(normalized_symbol)
            fee_cash_impact = -(event["fee"] * fx)
            cash += fee_cash_impact
        else:
            if event_type in ("BUY", "SELL", "SHORT", "COVER"):
                pq = event["price"] * event["quantity"]
                if (
                    OPTION_MULTIPLIER_NAV_ENABLED
                    and event.get("instrument_type") == "option"
                    and event.get("source") not in IBKR_TRANSACTION_SOURCES
                ):
                    mult = _helpers._as_float(event.get("multiplier"), 1.0)
                    if np.isfinite(mult) and mult > 1:
                        pq = pq * mult

                if event_type == "BUY":
                    cash -= (pq + event["fee"]) * fx
                elif event_type == "SELL":
                    cash += (pq - event["fee"]) * fx
                elif event_type == "SHORT":
                    cash += (pq - event["fee"]) * fx
                elif event_type == "COVER":
                    cash -= (pq + event["fee"]) * fx
            elif event_type == "INCOME":
                cash += event.get("amount", 0.0) * fx
            elif event_type == "PROVIDER_FLOW":
                signed_amount = event.get("amount", 0.0) * fx
                cash += signed_amount
                if bool(event.get("is_external_flow")):
                    external_flows.append((event["date"], signed_amount))
            elif event_type == "FUTURES_MTM":
                mtm_cash_impact = event.get("amount", 0.0) * fx
                cash += mtm_cash_impact
                futures_mtm_cash_impact_usd += mtm_cash_impact

        if is_futures and event_type in ("BUY", "SELL", "SHORT", "COVER"):
            event_cal_date = event["date"].date()

            # Detect transition past inception date → snapshot inception margin
            if (
                _futures_inception_date is not None
                and not _futures_inception_margin_captured
                and event_cal_date != _futures_inception_date
            ):
                _futures_inception_margin_captured = True
                futures_inception_margin_usd = sum(
                    abs(cqty)
                    * _futures_contract_price.get(ck, 0.0)
                    * _futures_contract_multiplier.get(ck, 1.0)
                    * _futures_contract_margin_rate.get(ck, _DEFAULT_MARGIN_RATE)
                    * _futures_contract_fx.get(ck, 1.0)
                    for ck, cqty in _futures_positions.items()
                )

            # Update positions — use normalized_symbol (already assigned at line 267)
            contract_key_suffix = str(event.get("expiry") or "") or str(event.get("con_id") or "")
            contract_key = (normalized_symbol, contract_key_suffix)
            quantity = event["quantity"]
            if event_type in ("BUY", "COVER"):
                _futures_positions[contract_key] = _futures_positions.get(contract_key, 0.0) + quantity
            elif event_type in ("SELL", "SHORT"):
                _futures_positions[contract_key] = _futures_positions.get(contract_key, 0.0) - quantity

            if contract_key in _futures_positions and abs(_futures_positions[contract_key]) < 1e-9:
                del _futures_positions[contract_key]
                _futures_contract_price.pop(contract_key, None)
                _futures_contract_fx.pop(contract_key, None)
                _futures_contract_margin_rate.pop(contract_key, None)
                _futures_contract_multiplier.pop(contract_key, None)
            else:
                _futures_contract_price[contract_key] = event["price"]
                _futures_contract_fx[contract_key] = fx
                if contract_key not in _futures_contract_margin_rate:
                    spec = get_contract_spec(normalized_symbol)
                    _futures_contract_margin_rate[contract_key] = (
                        spec.margin_rate if spec else _DEFAULT_MARGIN_RATE
                    )
                    _futures_contract_multiplier[contract_key] = (
                        spec.multiplier if spec else 1.0
                    )

            # Track inception date (only set on actual position-changing trades)
            if _futures_inception_date is None:
                _futures_inception_date = event_cal_date

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

    # Post-loop: if all futures trades were on one date, snapshot inception margin now
    if _futures_inception_date is not None and not _futures_inception_margin_captured:
        _futures_inception_margin_captured = True
        futures_inception_margin_usd = sum(
            abs(cqty)
            * _futures_contract_price.get(ck, 0.0)
            * _futures_contract_multiplier.get(ck, 1.0)
            * _futures_contract_margin_rate.get(ck, _DEFAULT_MARGIN_RATE)
            * _futures_contract_fx.get(ck, 1.0)
            for ck, cqty in _futures_positions.items()
        )

    if warnings is not None and _futures_positions:
        open_contracts = ", ".join(
            f"{sym}({exp})" if exp else sym
            for sym, exp in sorted(_futures_positions.keys())
        )
        warnings.append(
            f"Cash replay: {len(_futures_positions)} open futures position(s) at end of "
            f"replay ({open_contracts}). Inference was suppressed during open period."
        )
    if warnings is not None and futures_unknown_action_count > 0:
        warnings.append(
            f"Cash replay: {futures_unknown_action_count} futures transaction(s) used fee-only fallback for unknown action types."
        )
    if warnings is not None and futures_missing_fx_count > 0:
        warnings.append(
            f"Cash replay: {futures_missing_fx_count} futures transaction(s) used FX=1.0 fallback due to missing/invalid FX."
        )
    if warnings is not None and unpriceable_suppressed_count > 0:
        suppressed_symbols_sorted = sorted(unpriceable_suppressed_symbols)
        preview = ", ".join(suppressed_symbols_sorted[:5])
        if len(suppressed_symbols_sorted) > 5:
            preview = f"{preview}, ..."
        warnings.append(
            f"Cash replay: suppressed ${unpriceable_suppressed_usd:,.2f} notional from "
            f"{unpriceable_suppressed_count} unpriceable-symbol transaction(s) ({preview}). "
            "Notional was excluded; fees were retained."
        )
    if warnings is not None and int(_helpers._as_float(overlap_diagnostics.get("dropped_count"), 0.0)) > 0:
        warnings.append(
            "Cash replay: dropped "
            f"{int(_helpers._as_float(overlap_diagnostics.get('dropped_count'), 0.0))} overlapping non-external "
            "provider-flow event(s) in favor of INCOME rows."
        )

    if replay_diagnostics is not None:
        replay_diagnostics["futures_txn_count_replayed"] = int(
            _helpers._as_float(replay_diagnostics.get("futures_txn_count_replayed"), 0.0)
        ) + _futures_count
        replay_diagnostics["futures_notional_suppressed_usd"] = _helpers._as_float(
            replay_diagnostics.get("futures_notional_suppressed_usd"),
            0.0,
        ) + futures_notional_suppressed_usd
        replay_diagnostics["futures_fee_cash_impact_usd"] = _helpers._as_float(
            replay_diagnostics.get("futures_fee_cash_impact_usd"),
            0.0,
        ) + futures_fee_cash_impact_usd
        replay_diagnostics["futures_unknown_action_count"] = int(
            _helpers._as_float(replay_diagnostics.get("futures_unknown_action_count"), 0.0)
        ) + futures_unknown_action_count
        replay_diagnostics["futures_missing_fx_count"] = int(
            _helpers._as_float(replay_diagnostics.get("futures_missing_fx_count"), 0.0)
        ) + futures_missing_fx_count
        replay_diagnostics["futures_mtm_event_count"] = int(
            _helpers._as_float(replay_diagnostics.get("futures_mtm_event_count"), 0.0)
        ) + _futures_mtm_count
        replay_diagnostics["futures_mtm_cash_impact_usd"] = _helpers._as_float(
            replay_diagnostics.get("futures_mtm_cash_impact_usd"),
            0.0,
        ) + futures_mtm_cash_impact_usd
        replay_diagnostics["unpriceable_suppressed_count"] = int(
            _helpers._as_float(replay_diagnostics.get("unpriceable_suppressed_count"), 0.0)
        ) + unpriceable_suppressed_count
        replay_diagnostics["unpriceable_suppressed_usd"] = _helpers._as_float(
            replay_diagnostics.get("unpriceable_suppressed_usd"),
            0.0,
        ) + unpriceable_suppressed_usd
        replay_suppressed_symbols = {
            str(symbol).strip().upper()
            for symbol in list(replay_diagnostics.get("unpriceable_suppressed_symbols", []) or [])
            if str(symbol).strip()
        }
        replay_suppressed_symbols.update(unpriceable_suppressed_symbols)
        replay_diagnostics["unpriceable_suppressed_symbols"] = sorted(replay_suppressed_symbols)
        replay_diagnostics["income_flow_overlap_dropped_count"] = int(
            _helpers._as_float(replay_diagnostics.get("income_flow_overlap_dropped_count"), 0.0)
        ) + int(_helpers._as_float(overlap_diagnostics.get("dropped_count"), 0.0))
        replay_diagnostics["income_flow_overlap_dropped_net_usd"] = _helpers._as_float(
            replay_diagnostics.get("income_flow_overlap_dropped_net_usd"),
            0.0,
        ) + _helpers._as_float(overlap_diagnostics.get("dropped_net_usd"), 0.0)
        replay_diagnostics["income_flow_overlap_candidate_count"] = int(
            _helpers._as_float(replay_diagnostics.get("income_flow_overlap_candidate_count"), 0.0)
        ) + int(_helpers._as_float(overlap_diagnostics.get("candidate_count"), 0.0))
        replay_diagnostics["income_flow_overlap_alias_mismatch_count"] = int(
            _helpers._as_float(replay_diagnostics.get("income_flow_overlap_alias_mismatch_count"), 0.0)
        ) + int(_helpers._as_float(overlap_diagnostics.get("alias_normalization_mismatch_count"), 0.0))

        dropped_by_provider = replay_diagnostics.setdefault("income_flow_overlap_dropped_by_provider", {})
        for provider, count in dict(overlap_diagnostics.get("dropped_by_provider") or {}).items():
            dropped_by_provider[provider] = int(_helpers._as_float(dropped_by_provider.get(provider), 0.0)) + int(
                _helpers._as_float(count, 0.0)
            )

        sample_pairs = replay_diagnostics.setdefault("income_flow_overlap_alias_mismatch_samples", [])
        for pair in list(overlap_diagnostics.get("alias_normalization_mismatch_samples") or []):
            if pair not in sample_pairs and len(sample_pairs) < 5:
                sample_pairs.append(pair)

        replay_diagnostics["futures_inception_margin_usd"] = max(
            _helpers._as_float(replay_diagnostics.get("futures_inception_margin_usd"), 0.0),
            futures_inception_margin_usd,
        )
        if _futures_inception_date is not None:
            existing_date = replay_diagnostics.get("futures_inception_trade_date")
            if existing_date is None:
                replay_diagnostics["futures_inception_trade_date"] = _futures_inception_date
            else:
                replay_diagnostics["futures_inception_trade_date"] = min(existing_date, _futures_inception_date)

    return cash_snapshots, external_flows

def compute_monthly_nav(
    position_timeline: Dict[Tuple[str, str, str], List[Tuple[datetime, float]]],
    month_ends: List[datetime],
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
    cash_snapshots: List[Tuple[datetime, float]],
    futures_keys: Optional[Set[Tuple[str, str, str]]] = None,
) -> pd.Series:
    """Compute month-end NAV = valued positions + derived cash.

    Futures positions are excluded from position valuation because their P&L
    is already captured in cash via FUTURES_MTM daily settlement events.
    Including notional value would double-count and massively inflate NAV.
    """
    if not month_ends:
        return pd.Series(dtype=float)

    def _prepare_lookup(series: pd.Series | None) -> tuple[np.ndarray, np.ndarray] | None:
        if series is None or len(series) == 0:
            return None
        prepared = series.dropna()
        if prepared.empty:
            return None
        if not isinstance(prepared.index, pd.DatetimeIndex):
            prepared.index = pd.to_datetime(prepared.index)
        prepared = prepared.sort_index()
        index_ns = prepared.index.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
        return index_ns, prepared.to_numpy(dtype=float, copy=False)

    def _lookup_prepared(
        prepared: tuple[np.ndarray, np.ndarray] | None,
        when_ns: int,
        *,
        default: float,
    ) -> float:
        if prepared is None:
            return default
        index_ns, values = prepared
        if len(index_ns) == 0:
            return default

        prior_pos = int(np.searchsorted(index_ns, when_ns, side="right")) - 1
        if prior_pos >= 0:
            return _helpers._as_float(values[prior_pos], default)

        future_pos = int(np.searchsorted(index_ns, when_ns, side="left"))
        if future_pos < len(values):
            return _helpers._as_float(values[future_pos], default)

        return default

    month_end_index = pd.DatetimeIndex(pd.to_datetime(month_ends)).sort_values()
    prepared_price_cache = {
        ticker: _prepare_lookup(series)
        for ticker, series in price_cache.items()
    }
    prepared_fx_cache = {
        currency.upper(): _prepare_lookup(series)
        for currency, series in fx_cache.items()
    }

    events_by_key: Dict[Tuple[str, str, str], List[Tuple[datetime, float]]] = {}
    ptrs: Dict[Tuple[str, str, str], int] = {}
    quantities: Dict[Tuple[str, str, str], float] = {}

    for key, events in position_timeline.items():
        normalized = [(pd.Timestamp(d).to_pydatetime().replace(tzinfo=None), _helpers._as_float(q, 0.0)) for d, q in events]
        normalized.sort(key=lambda x: x[0])
        events_by_key[key] = normalized
        ptrs[key] = 0
        quantities[key] = 0.0

    cash_snapshots_sorted = sorted(
        [(pd.Timestamp(d).to_pydatetime().replace(tzinfo=None), _helpers._as_float(v, 0.0)) for d, v in cash_snapshots],
        key=lambda x: x[0],
    )
    cash_ptr = 0
    cash_value = 0.0

    nav_values: List[float] = []

    for month_end in month_end_index:
        me = month_end.to_pydatetime().replace(tzinfo=None)
        me_ns = month_end.value

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
            if futures_keys and key in futures_keys:
                continue
            price = _lookup_prepared(prepared_price_cache.get(ticker), me_ns, default=0.0)
            fx = (
                1.0
                if str(currency or "USD").upper() == "USD"
                else _lookup_prepared(
                    prepared_fx_cache.get(str(currency or "USD").upper()),
                    me_ns,
                    default=1.0,
                )
            )
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

        net_flows.loc[month_end] += _helpers._as_float(amount, 0.0)
        weighted_flows.loc[month_end] += _helpers._as_float(amount, 0.0) * weight

    return net_flows, weighted_flows

def compute_monthly_returns(
    monthly_nav: pd.Series,
    net_flows: pd.Series,
    time_weighted_flows: pd.Series,
    inception_nav: Optional[float] = None,
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
        v_end = _helpers._as_float(nav.iloc[i], 0.0)
        v_start = inception_nav if (i == 0 and inception_nav is not None) else (prev_nav if i > 0 else 0.0)
        flow_net = _helpers._as_float(net.loc[ts], 0.0)
        flow_weighted = _helpers._as_float(tw.loc[ts], 0.0)

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

def compute_twr_monthly_returns(
    daily_nav: pd.Series,
    external_flows: List[Tuple[datetime, float]],
    month_ends: List[datetime],
) -> Tuple[pd.Series, List[str]]:
    """Compute monthly TWR by chaining daily GIPS flow-adjusted returns."""
    warnings: List[str] = []
    if daily_nav is None or daily_nav.empty:
        return pd.Series(dtype=float), ["Daily NAV series is empty; cannot compute TWR returns."]

    nav = _helpers._series_from_cache(daily_nav).dropna()
    if nav.empty:
        return pd.Series(dtype=float), ["Daily NAV series has no valid values; cannot compute TWR returns."]

    nav_idx = pd.DatetimeIndex(pd.to_datetime(nav.index)).sort_values()
    nav = nav.reindex(nav_idx)

    # Store inflows/outflows separately for mixed-flow days.
    # Value shape: [total_inflows, total_outflows], where outflows stay negative.
    flows_by_day: Dict[pd.Timestamp, List[float]] = defaultdict(lambda: [0.0, 0.0])
    for flow_date, amount in external_flows:
        amt = _helpers._as_float(amount, 0.0)
        if not np.isfinite(amt) or abs(amt) < 1e-12:
            continue
        flow_day = pd.Timestamp(flow_date).normalize()
        pos = int(nav_idx.searchsorted(flow_day, side="left"))
        if pos >= len(nav_idx):
            snapped_day = nav_idx[-1]
        else:
            snapped_day = nav_idx[pos]
        if amt > 0:
            flows_by_day[snapped_day][0] += amt
        else:
            flows_by_day[snapped_day][1] += amt

    month_growth: Dict[pd.Period, float] = defaultdict(lambda: 1.0)
    month_has_data: Dict[pd.Period, bool] = defaultdict(bool)

    prev_nav = 0.0
    for idx, day in enumerate(nav_idx):
        day_nav = _helpers._as_float(nav.loc[day], 0.0)
        month = day.to_period("M")
        month_has_data[month] = True

        cf_in, cf_out = flows_by_day.get(day, (0.0, 0.0))

        if idx == 0:
            # No prior NAV exists on inception day — no return to compute.
            # Any flows snapped to this day are absorbed into the baseline.
            # Day 2+ will flow-adjust correctly via the GIPS formula using
            # prev_nav and cf_in/cf_out.
            prev_nav = day_nav
            continue

        # GIPS mixed-flow daily return:
        #   R = (V_D + |CF_out|) / (V_{D-1} + CF_in) - 1
        # cf_out is negative, so V_D + |CF_out| == V_D - cf_out.
        numer = day_nav - cf_out
        denom = prev_nav + cf_in

        if denom > 1e-12:
            r_day = (numer / denom) - 1.0
        elif abs(day_nav) < 1e-12:
            r_day = 0.0
        else:
            r_day = 0.0
            warnings.append(f"{day.date().isoformat()}: denominator ~0, return set to 0")

        month_growth[month] *= (1.0 + r_day)
        prev_nav = day_nav

    month_end_index = pd.DatetimeIndex(pd.to_datetime(month_ends)).sort_values()
    month_end_index = pd.DatetimeIndex(month_end_index.to_period("M").to_timestamp("M"))
    month_end_index = month_end_index[~month_end_index.duplicated(keep="last")]
    if month_end_index.empty:
        month_end_index = pd.DatetimeIndex(
            sorted({pd.Timestamp(ts).to_period("M").to_timestamp("M") for ts in nav_idx})
        )

    monthly_returns = pd.Series(index=month_end_index, dtype=float)
    for month_end in month_end_index:
        month = month_end.to_period("M")
        if not month_has_data.get(month, False):
            continue
        monthly_returns.loc[month_end] = month_growth[month] - 1.0

    return monthly_returns.dropna().sort_index(), warnings

def _safe_treasury_rate(start_date: datetime, end_date: datetime) -> float:
    """Fetch mean 3M treasury yield and return annual decimal rate."""
    treasury_fetcher = fetch_monthly_treasury_rates
    try:
        rates = treasury_fetcher("month3", start_date, end_date)
        rates = _helpers._series_from_cache(rates)
        if rates.empty:
            return 0.04
        return _helpers._as_float(rates.mean(), 4.0) / 100.0
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
        current_price = _helpers._value_at_or_before(price_cache.get(symbol), as_of, default=0.0)
        fx = fx_module._event_fx_rate(currency, as_of, fx_cache)
        for lot in lots:
            qty = _helpers._as_float(getattr(lot, "remaining_quantity", 0.0), 0.0)
            entry = _helpers._as_float(getattr(lot, "entry_price", 0.0), 0.0)
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
        date = _helpers._to_datetime(txn.get("date"))
        if date is None:
            continue
        txn_type = str(txn.get("type", "")).upper()
        amount = _helpers._as_float(txn.get("price"), 0.0) * abs(_helpers._as_float(txn.get("quantity"), 0.0))
        fee = abs(_helpers._as_float(txn.get("fee"), 0.0))
        fx = fx_module._event_fx_rate(str(txn.get("currency") or "USD"), date, fx_cache)

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
                "amount": _helpers._as_float(inc.amount, 0.0),
                "income_type": inc.income_type,
                "currency": direct_currency or symbol_currency_map.get(inc.symbol, "USD"),
                "source": inc.source,
                "institution": getattr(inc, "institution", "") or "",
                "account_id": provider_flows._normalize_optional_identifier(getattr(inc, "account_id", None)),
                "account_name": provider_flows._normalize_optional_identifier(getattr(inc, "account_name", None)),
            }
        )
    return rows

__all__ = [
    'derive_cash_and_external_flows',
    'compute_monthly_nav',
    'compute_monthly_external_flows',
    'compute_monthly_returns',
    'compute_twr_monthly_returns',
    '_safe_treasury_rate',
    '_compute_unrealized_pnl_usd',
    '_compute_net_contributions_usd',
    '_income_with_currency',
]
