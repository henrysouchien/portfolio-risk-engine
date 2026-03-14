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

from . import _helpers, fx as fx_module, provider_flows

def _sanitize_backfill_id_component(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "unknown"
    return "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in raw)

def _build_backfill_transaction_id(
    entry: Dict[str, Any],
    seq_by_fallback_key: Dict[Tuple[str, str, str, str, str, str], int],
) -> str:
    source = _sanitize_backfill_id_component(provider_flows._normalize_source_name(entry.get("source")))
    exit_transaction_id = str(entry.get("transaction_id") or "").strip()
    if exit_transaction_id:
        return f"backfill_{source}_entry_for_{_sanitize_backfill_id_component(exit_transaction_id)}"

    symbol = _sanitize_backfill_id_component(entry.get("symbol"))
    entry_date = _helpers._to_datetime(entry.get("manual_entry_date"))
    date_component = entry_date.date().isoformat() if entry_date else "unknown_date"
    direction = _sanitize_backfill_id_component(str(entry.get("direction") or "LONG").upper())
    qty_component = _sanitize_backfill_id_component(f"{abs(_helpers._as_float(entry.get('quantity'), 0.0)):.10g}")
    price_component = _sanitize_backfill_id_component(f"{_helpers._as_float(entry.get('manual_entry_price'), 0.0):.10g}")
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

        row_source = provider_flows._normalize_source_name(row.get("source"))
        if source_filter != "all" and row_source != source_filter:
            continue

        entry_date = _helpers._to_datetime(row.get("manual_entry_date"))
        quantity = abs(_helpers._as_float(row.get("quantity"), 0.0))
        entry_price = _helpers._as_float(row.get("manual_entry_price"), 0.0)
        if entry_date is None or quantity <= 0 or entry_price <= 0:
            continue

        direction = str(row.get("direction") or "LONG").upper()
        txn_type = "SHORT" if direction == "SHORT" else "BUY"
        transaction_id = _build_backfill_transaction_id(row, seq_by_fallback_key)
        if transaction_id in existing_transaction_ids:
            continue

        fee = _helpers._as_float(row.get("manual_entry_fee"), 0.0)
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
                "date": _helpers._to_datetime(txn.get("date")),
                "quantity": abs(_helpers._as_float(txn.get("quantity"), 0.0)),
                "price": _helpers._as_float(txn.get("price"), 0.0),
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
                lot_entry_date = _helpers._to_datetime(getattr(lot, "entry_date", None))
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
        quantity = _helpers._as_float(meta.get("quantity"), 0.0)
        price = _helpers._as_float(meta.get("price"), 0.0)
        if entry_date is None or quantity <= 0 or price <= 0:
            continue

        for provider_entry in provider_entry_transactions:
            if provider_entry.get("symbol") != symbol or provider_entry.get("direction") != direction:
                continue
            provider_date = provider_entry.get("date")
            provider_qty = _helpers._as_float(provider_entry.get("quantity"), 0.0)
            provider_price = _helpers._as_float(provider_entry.get("price"), 0.0)
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
            total += _helpers._as_float(getattr(trade, "pnl_dollars", 0.0), 0.0)
            continue

        direction = str(getattr(trade, "direction", "LONG") or "LONG").upper()
        currency = str(getattr(trade, "currency", "USD") or "USD").upper()
        entry_date = _helpers._to_datetime(getattr(trade, "entry_date", None))
        exit_date = _helpers._to_datetime(getattr(trade, "exit_date", None))
        if entry_date is None or exit_date is None:
            total += _helpers._as_float(getattr(trade, "pnl_dollars", 0.0), 0.0)
            continue

        qty = abs(_helpers._as_float(getattr(trade, "quantity", 0.0), 0.0))
        entry_price = _helpers._as_float(getattr(trade, "entry_price", 0.0), 0.0)
        exit_price = _helpers._as_float(getattr(trade, "exit_price", 0.0), 0.0)
        entry_fee = _helpers._as_float(getattr(trade, "entry_fee", 0.0), 0.0)
        exit_fee = _helpers._as_float(getattr(trade, "exit_fee", 0.0), 0.0)
        entry_fx = fx_module._event_fx_rate(currency, entry_date, fx_cache)
        exit_fx = fx_module._event_fx_rate(currency, exit_date, fx_cache)

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

def _compute_incomplete_trade_pnl_usd(
    incomplete_trades: Iterable[Any],
    fx_cache: Dict[str, pd.Series],
) -> float:
    """Sum broker-reported P&L for incomplete trades in USD."""
    total = 0.0
    for trade in incomplete_trades:
        pnl = getattr(trade, "broker_pnl", None)
        if pnl is None:
            continue

        instrument_type = str(getattr(trade, "instrument_type", "equity") or "equity").lower()
        if instrument_type == "futures":
            continue

        currency = str(getattr(trade, "currency", "USD") or "USD").upper()
        trade_date = _helpers._to_datetime(getattr(trade, "sell_date", None))
        if trade_date is None:
            total += float(pnl)
            continue

        fx_rate = fx_module._event_fx_rate(currency, trade_date, fx_cache)
        total += float(pnl) * fx_rate

    return float(total)

def _summarize_income_usd(
    income_with_currency: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
) -> Dict[str, float]:
    """Aggregate income fields in USD using event-date FX normalization."""
    by_month_usd: Dict[str, float] = defaultdict(float)
    by_symbol_usd: Dict[str, float] = defaultdict(float)
    by_institution: Dict[str, Dict[str, float]] = defaultdict(lambda: {"dividends": 0.0, "interest": 0.0, "total": 0.0})
    total_dividends_usd = 0.0
    total_interest_usd = 0.0

    for event in income_with_currency:
        when = _helpers._to_datetime(event.get("date"))
        if when is None:
            continue
        amount = _helpers._as_float(event.get("amount"), 0.0)
        currency = str(event.get("currency") or "USD").upper()
        amount_usd = amount * fx_module._event_fx_rate(currency, when, fx_cache)
        month_key = when.strftime("%Y-%m")
        symbol = str(event.get("symbol") or "").strip() or "UNKNOWN"
        by_month_usd[month_key] += amount_usd
        by_symbol_usd[symbol] += amount_usd

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
        "by_month": {k: round(v, 2) for k, v in sorted(by_month_usd.items())},
        "by_symbol": {k: round(v, 2) for k, v in sorted(by_symbol_usd.items())},
        "by_institution": by_institution_rounded,
        "current_monthly_rate": float(current_monthly_usd),
        "projected_annual": float(current_monthly_usd * 12.0),
    }

__all__ = [
    '_sanitize_backfill_id_component',
    '_build_backfill_transaction_id',
    '_build_backfill_entry_transactions',
    '_emit_backfill_diagnostics',
    '_compute_realized_pnl_usd',
    '_compute_incomplete_trade_pnl_usd',
    '_summarize_income_usd',
]
