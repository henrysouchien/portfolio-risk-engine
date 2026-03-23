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

from . import _helpers, fx as fx_module

def _synthetic_events_to_flows(
    synthetic_cash_events: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
    price_cache: Optional[Dict[str, pd.Series]] = None,
) -> List[Tuple[datetime, float]]:
    """Convert synthetic cash events to external flow tuples for TWR.

    Synthetic positions appear in NAV but their cash events are excluded
    from the cash replay (to avoid inflating the Modified Dietz denominator).
    For TWR, we need matching flows so the GIPS formula treats position
    appearances as contributions rather than returns.

    When price_cache is provided, use NAV-aligned market prices to keep
    synthetic flow valuation consistent with NAV valuation.

    Sign convention (matches TWR flow semantics):
    - BUY  -> positive inflow  (NAV increases by long position value)
    - SHORT -> negative outflow (NAV decreases by short position liability)
    """
    flows: List[Tuple[datetime, float]] = []
    for evt in synthetic_cash_events:
        evt_date = _helpers._to_datetime(evt.get("date"))
        if evt_date is None:
            continue

        ticker = str(evt.get("symbol") or "").strip()
        nav_price = None
        if price_cache and ticker:
            nav_price = _helpers._value_at_or_before(
                price_cache.get(ticker),
                evt_date,
                default=0.0,
            )
            if nav_price is not None and nav_price <= 0:
                nav_price = None

        price = nav_price if nav_price is not None else _helpers._as_float(evt.get("price"), 0.0)
        qty = _helpers._as_float(evt.get("quantity"), 0.0)
        if price <= 0 or qty <= 0:
            continue

        currency = str(evt.get("currency") or "USD").upper()
        fx = fx_module._event_fx_rate(currency, evt_date, fx_cache)
        notional_usd = price * qty * fx

        # BUY = positive inflow, SHORT = negative outflow.
        evt_type = str(evt.get("type") or "BUY").upper()
        signed_amount = notional_usd if evt_type != "SHORT" else -notional_usd
        if abs(signed_amount) > 1e-6:
            flows.append((evt_date, signed_amount))

    return flows

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
    qty = abs(_helpers._as_float(shares, 0.0))
    if qty <= 1e-9:
        return 0.0

    ccy = str(currency or "USD").upper()
    cost_basis = _helpers._as_float(position_row.get("cost_basis"), 0.0)
    cost_basis_is_usd = bool(position_row.get("cost_basis_is_usd", ccy == "USD"))
    if ccy == "USD" and cost_basis > 0 and cost_basis_is_usd:
        return cost_basis / qty

    value = _helpers._as_float(position_row.get("value"), 0.0)
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
        date = _helpers._to_datetime(txn.get("date"))
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
                "quantity": abs(_helpers._as_float(txn.get("quantity"), 0.0)),
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
            e for e in sorted(earliest_events, key=lambda item: _helpers.TYPE_ORDER.get(str(item.get("type") or ""), 99))
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
                "quantity": float(_helpers._as_float(first_exit.get("quantity"), 0.0)),
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
        dt = _helpers._to_datetime(txn.get("date"))
        if sym and dt:
            if sym not in earliest_txn_by_symbol or dt < earliest_txn_by_symbol[sym]:
                earliest_txn_by_symbol[sym] = dt

    # Pre-compute in-window openings and exits per (symbol, currency, LONG)
    in_window_openings: Dict[str, float] = defaultdict(float)
    in_window_exits: Dict[str, float] = defaultdict(float)
    for txn in fifo_transactions:
        sym = str(txn.get("symbol", "")).strip()
        txn_type = str(txn.get("type", "")).upper()
        qty = abs(_helpers._as_float(txn.get("quantity"), 0.0))
        if txn_type == "BUY":
            in_window_openings[sym] += qty
        elif txn_type == "SELL":
            in_window_exits[sym] += qty

    for ticker, pos in current_positions.items():
        shares = _helpers._as_float(pos.get("shares"), 0.0)
        if shares <= 0:
            # Only seed LONG positions (per plan: scope to LONG only)
            continue

        broker_cost = _helpers._as_float(pos.get("cost_basis"), 0.0)
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
            fx_rate = _helpers._value_at_or_before(
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
            fx_rate = _helpers._value_at_or_before(
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
    *,
    use_per_symbol_inception: bool = False,
) -> Tuple[
    Dict[Tuple[str, str, str], List[Tuple[datetime, float]]],
    List[Dict[str, str]],
    List[Dict[str, Any]],
    Dict[Tuple[str, str, str], InstrumentMeta],
    List[str],
]:
    """Walk transactions forward to reconstruct quantities by (ticker, currency, direction).

    When ``use_per_symbol_inception`` is True, synthetic positions are placed at
    each symbol's earliest transaction date rather than the global inception.
    This prevents backdating positions to months before they were actually held,
    but requires complete transaction history (safe for Schwab; unsafe for IBKR
    whose Flex query window may be limited).
    """
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
        normalized_instrument_type = coerce_instrument_type(raw_instrument_type, default="equity")
        contract_identity = raw_contract_identity if isinstance(raw_contract_identity, dict) else None
        existing = instrument_meta.get(key)
        if existing is None:
            instrument_meta[key] = {
                "instrument_type": normalized_instrument_type,
                "contract_identity": contract_identity,
            }
            return

        existing_type = coerce_instrument_type(existing.get("instrument_type"), default="equity")
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
        date = _helpers._to_datetime(txn.get("date"))
        if date is None:
            continue

        symbol = str(txn.get("symbol", "")).strip()
        if not symbol:
            continue
        currency = str(txn.get("currency") or "USD").upper()
        txn_type = str(txn.get("type", "")).upper()
        qty = abs(_helpers._as_float(txn.get("quantity"), 0.0))
        if qty <= 0:
            continue
        instrument_type = _helpers._infer_instrument_type_from_transaction(txn)
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
        dt = _helpers._to_datetime(txn.get("date"))
        if sym and dt:
            if sym not in earliest_txn_by_symbol or dt < earliest_txn_by_symbol[sym]:
                earliest_txn_by_symbol[sym] = dt

    synthetic_keys: set[Tuple[str, str, str]] = set()
    synthetic_qty_by_key: Dict[Tuple[str, str, str], float] = defaultdict(float)
    current_position_synthetic_keys: set[Tuple[str, str, str]] = set()
    filtered_futures_incomplete_keys: set[Tuple[str, str, str]] = set()

    # Synthetic starts for current positions with missing or partial opening history.
    for ticker, pos in current_positions.items():
        shares = _helpers._as_float(pos.get("shares"), 0.0)
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
            # When per-symbol inception is enabled (complete txn history,
            # e.g. Schwab), place synthetic at the symbol's earliest txn date
            # so positions aren't backdated before they were actually held.
            # Falls back to global inception for symbols with NO transaction
            # history — these may be legitimately held from inception without
            # matching buy records (e.g. pre-existing positions).
            # Without per-symbol inception (e.g. IBKR Flex with limited
            # history), always use global inception.
            if use_per_symbol_inception:
                symbol_inception = earliest_txn_by_symbol.get(ticker, inception_date)
            else:
                symbol_inception = inception_date
            synthetic_date = symbol_inception - timedelta(seconds=1)
            price_hint = _synthetic_price_hint_from_position(
                shares=shares,
                currency=currency,
                position_row=pos,
            )
            estimated_current_value_usd = abs(_helpers._as_float(pos.get("value"), 0.0))

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
        qty = abs(_helpers._as_float(incomplete.quantity, 0.0))
        sell_date = _helpers._to_datetime(incomplete.sell_date)

        if not symbol or qty <= 0 or sell_date is None:
            warnings.append("Skipped malformed incomplete trade during synthetic reconstruction.")
            continue

        # Place incomplete-trade synthetic at global inception (not sell_date - 1s)
        # so the position has month-end value from day one.  When the SELL lands,
        # it converts position value → cash; Modified Dietz sees a roughly neutral
        # transfer instead of phantom cash appearing from nowhere.
        # When per-symbol inception is enabled, anchor to symbol's earliest txn
        # (or sell_date if no prior txn) to avoid backdating beyond actual holding.
        if use_per_symbol_inception:
            symbol_anchor = earliest_txn_by_symbol.get(symbol)
            if symbol_anchor is not None:
                synthetic_date = min(symbol_anchor, sell_date) - timedelta(seconds=1)
            else:
                synthetic_date = sell_date - timedelta(seconds=1)
        else:
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
                "price_hint": (
                    _helpers._as_float(getattr(incomplete, "broker_cost_basis", None), 0.0)
                    or _helpers._as_float(getattr(incomplete, "sell_price", 0.0), 0.0)
                ),
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

        _inc_qty = abs(_helpers._as_float(getattr(_inc, "quantity", 0), 0.0))
        _inc_sell_date = _helpers._to_datetime(getattr(_inc, "sell_date", None))
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
        date = _helpers._to_datetime(entry.get("date"))
        quantity = abs(_helpers._as_float(entry.get("quantity"), 0.0))
        estimated_current_value_usd = abs(_helpers._as_float(entry.get("estimated_current_value_usd"), 0.0))

        if not ticker or date is None or quantity <= 0:
            warnings.append("Skipped malformed synthetic entry while creating synthetic cash events.")
            continue

        price = 0.0
        # Backward-first lookup: prefer prices on or before entry date.
        series = _helpers._series_from_cache(price_cache.get(ticker))
        series.index = pd.to_datetime(series.index)
        prior = series[series.index <= pd.Timestamp(date)]
        if not prior.empty:
            price = _helpers._as_float(prior.iloc[-1], 0.0)

        if price <= 0 and source == "synthetic_incomplete_trade" and not series.empty:
            forward = series[series.index > pd.Timestamp(date)]
            if not forward.empty:
                price = _helpers._as_float(forward.iloc[0], 0.0)
                if price > 0:
                    warnings.append(
                        f"Used forward price lookup for {ticker} ({direction}) on "
                        f"{date.date().isoformat()} "
                        f"(nearest available: {forward.index[0].date().isoformat()})."
                    )

        if price <= 0:
            fallback_price_hint = _helpers._as_float(entry.get("price_hint"), 0.0)
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

__all__ = [
    '_synthetic_events_to_flows',
    '_synthetic_price_hint_from_position',
    '_detect_first_exit_without_opening',
    '_build_seed_open_lots',
    'build_position_timeline',
    '_create_synthetic_cash_events',
]
