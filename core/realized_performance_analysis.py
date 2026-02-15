"""Realized portfolio performance analysis pipeline.

Builds monthly, cash-inclusive portfolio returns from transaction history and
current holdings, then computes risk/performance metrics via the shared
performance metrics engine.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from core.performance_metrics_engine import compute_performance_metrics
from factor_utils import calc_monthly_returns
from data_loader import fetch_monthly_close, fetch_monthly_treasury_rates
from fmp.fx import get_monthly_fx_series
from settings import (
    BACKFILL_FILE_PATH,
    DATA_QUALITY_THRESHOLDS,
    REALIZED_COVERAGE_TARGET,
    REALIZED_MAX_INCOMPLETE_TRADES,
    REALIZED_MAX_RECONCILIATION_GAP_PCT,
)
from trading_analysis.analyzer import TradingAnalyzer
from trading_analysis.data_fetcher import fetch_transactions_for_source
from trading_analysis.fifo_matcher import FIFOMatcher, IncompleteTrade, OpenLot
from trading_analysis.instrument_meta import InstrumentMeta, coerce_instrument_type
from utils.ticker_resolver import load_exchange_mappings


TYPE_ORDER = {
    "SELL": 0,
    "SHORT": 1,
    "INCOME": 2,
    "BUY": 3,
    "COVER": 4,
}
_FX_PAIR_SYMBOL_RE = re.compile(r"^[A-Z]{3}\.[A-Z]{3}$")


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


def _month_end_range(start: datetime, end: datetime) -> List[datetime]:
    """Build month-end date list for [start, end]."""
    month_ends = [
        dt.to_pydatetime().replace(tzinfo=None)
        for dt in pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="ME")
    ]
    if month_ends:
        return month_ends
    return [pd.Timestamp(start).to_period("M").to_timestamp("M").to_pydatetime().replace(tzinfo=None)]


def _build_current_positions(positions: "PositionResult") -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], List[str]]:
    """Build ticker->position map and fmp_ticker map from PositionResult."""
    current_positions: Dict[str, Dict[str, Any]] = {}
    fmp_ticker_map: Dict[str, str] = {}
    warnings: List[str] = []

    for pos in positions.data.positions:
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

    return current_positions, fmp_ticker_map, warnings


def _build_source_aligned_holdings(
    positions: "PositionResult",
    source: str,
    warnings: List[str],
) -> Dict[str, float]:
    """Build ticker->shares for a single provider from raw position rows.

    This is used only for source-filtered short-inference gap logic. Mixed-source
    consolidated rows (e.g., "plaid,snaptrade") are excluded because attribution
    to a single provider is ambiguous.
    """
    if source == "all":
        return {}

    aligned: Dict[str, float] = defaultdict(float)
    mixed_symbols: set[str] = set()

    for pos in getattr(getattr(positions, "data", None), "positions", []):
        ticker = pos.get("ticker")
        if not ticker or not isinstance(ticker, str):
            continue
        if pos.get("type") == "cash" or ticker.startswith("CUR:"):
            continue

        quantity = _as_float(pos.get("quantity"), 0.0)
        if abs(quantity) < 1e-9:
            continue

        raw_source = str(pos.get("position_source") or "").strip().lower()
        if not raw_source:
            continue

        sources = [s.strip() for s in raw_source.split(",") if s.strip()]
        if len(sources) == 1:
            if sources[0] == source:
                aligned[ticker.strip()] += quantity
            continue

        if source in sources:
            mixed_symbols.add(ticker.strip())

    if mixed_symbols:
        preview = ", ".join(sorted(mixed_symbols)[:5])
        if len(mixed_symbols) > 5:
            preview = f"{preview}, ..."
        warnings.append(
            f"Excluded {len(mixed_symbols)} mixed-source position symbol(s) from {source} holdings alignment "
            f"for short-inference gap logic ({preview}); provider attribution is ambiguous in consolidated rows."
        )

    return dict(aligned)


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
            # Use per-symbol inception: earliest known txn for this symbol,
            # falling back to global inception for zero-history symbols.
            # Offset by -1s so synthetic entry sorts before any real txn at that timestamp.
            symbol_inception = earliest_txn_by_symbol.get(ticker, inception_date)
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

        synthetic_date = sell_date - timedelta(seconds=1)
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
) -> Tuple[List[Tuple[datetime, float]], List[Tuple[datetime, float]]]:
    """Replay trades+income stream to derive cash and net external capital flows.

    Positive external flows represent inferred capital contributions when cash
    would otherwise go negative. Negative external flows represent subsequent
    withdrawals (repayment) when later events replenish cash above outstanding
    inferred contributions.
    """
    events: List[Dict[str, Any]] = []

    for txn in fifo_transactions:
        date = _to_datetime(txn.get("date"))
        if date is None:
            continue
        events.append(
            {
                "date": date,
                "event_type": str(txn.get("type", "")).upper(),
                "price": _as_float(txn.get("price"), 0.0),
                "quantity": abs(_as_float(txn.get("quantity"), 0.0)),
                "fee": abs(_as_float(txn.get("fee"), 0.0)),
                "currency": str(txn.get("currency") or "USD").upper(),
            }
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

    events.sort(key=lambda e: (e["date"], TYPE_ORDER.get(e["event_type"], 99)))

    cash = 0.0
    outstanding_injections = 0.0
    cash_snapshots: List[Tuple[datetime, float]] = []
    external_flows: List[Tuple[datetime, float]] = []

    for event in events:
        fx = _event_fx_rate(event.get("currency", "USD"), event["date"], fx_cache)
        event_type = event["event_type"]

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

        if cash < 0:
            injection = abs(cash)
            external_flows.append((event["date"], injection))
            outstanding_injections += injection
            cash = 0.0

        # Repay previously inferred contributions before carrying excess cash.
        if cash > 0 and outstanding_injections > 0:
            withdrawal = min(cash, outstanding_injections)
            if withdrawal > 0:
                external_flows.append((event["date"], -withdrawal))
                cash -= withdrawal
                outstanding_injections -= withdrawal

        cash_snapshots.append((event["date"], cash))

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

    return [
        {
            "symbol": inc.symbol,
            "date": inc.date,
            "amount": _as_float(inc.amount, 0.0),
            "income_type": inc.income_type,
            "currency": symbol_currency_map.get(inc.symbol, "USD"),
            "source": inc.source,
        }
        for inc in analyzer.income_events
    ]


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
        if income_type == "dividend":
            total_dividends_usd += amount_usd
        else:
            total_interest_usd += amount_usd

    total_income_usd = total_dividends_usd + total_interest_usd
    months = sorted(by_month_usd.keys())
    if len(months) >= 3:
        current_monthly_usd = sum(by_month_usd[m] for m in months[-3:]) / 3.0
    else:
        current_monthly_usd = total_income_usd / max(len(months), 1)

    return {
        "total": float(total_income_usd),
        "dividends": float(total_dividends_usd),
        "interest": float(total_interest_usd),
        "current_monthly_rate": float(current_monthly_usd),
        "projected_annual": float(current_monthly_usd * 12.0),
    }


def analyze_realized_performance(
    positions: "PositionResult",
    user_email: str,
    benchmark_ticker: str = "SPY",
    source: str = "all",
    include_series: bool = False,
    backfill_path: Optional[str] = None,
) -> Union["RealizedPerformanceResult", Dict[str, Any]]:
    """Compute realized performance metrics and realized metadata from transactions."""
    warnings: List[str] = []

    try:
        source = source.lower().strip()
        if source not in {"all", "snaptrade", "plaid", "ibkr_flex"}:
            return {"status": "error", "message": "source must be one of: all, snaptrade, plaid, ibkr_flex"}

        current_positions, fmp_ticker_map, build_warnings = _build_current_positions(positions)
        warnings.extend(build_warnings)

        if source != "all":
            warnings.append(
                "source filter applies to transactions; current positions remain consolidated for NAV and valuation. "
                "Short-inference gap logic uses source-aligned holdings when attributable."
            )

        payload = fetch_transactions_for_source(user_email=user_email, source=source)

        analyzer = TradingAnalyzer(
            plaid_securities=payload.get("plaid_securities", []),
            plaid_transactions=payload.get("plaid_transactions", []),
            snaptrade_activities=payload.get("snaptrade_activities", []),
            ibkr_flex_trades=payload.get("ibkr_flex_trades"),
            use_fifo=True,
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
        fifo_transactions.sort(key=lambda t: _to_datetime(t.get("date")) or datetime.min)

        futures_map = load_exchange_mappings().get("ibkr_futures_to_fmp", {})
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
            inception_date = min(_to_datetime(t.get("date")) for t in fifo_transactions if _to_datetime(t.get("date")) is not None)
            inception_date = inception_date or (now - timedelta(days=365))
        else:
            inception_date = now - timedelta(days=365)
            warnings.append(
                "No transaction history found; using 12-month synthetic inception for current holdings."
            )

        income_with_currency = _income_with_currency(analyzer, fifo_transactions, current_positions)

        latest_event_date = inception_date
        for txn in fifo_transactions:
            dt = _to_datetime(txn.get("date"))
            if dt and dt > latest_event_date:
                latest_event_date = dt
        for inc in income_with_currency:
            dt = _to_datetime(inc.get("date"))
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

        source_holdings = _build_source_aligned_holdings(positions, source, warnings)

        no_infer_symbols: set[str] = set()
        for sym, delta in visible_delta.items():
            if source == "all":
                holdings = _as_float(current_positions.get(sym, {}).get("shares"), 0.0)
            else:
                holdings = _as_float(source_holdings.get(sym), 0.0)
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
                if not option_still_open and not fifo_terminal.empty and not fifo_terminal.dropna().empty:
                    norm = _series_from_cache(fifo_terminal)
                    warnings.append(
                        f"Priced option {ticker} using FIFO close-price terminal heuristic."
                    )
                else:
                    try:
                        from services.ibkr_data.compat import fetch_ibkr_option_monthly_mark

                        ibkr_series = fetch_ibkr_option_monthly_mark(
                            ticker,
                            start_date=price_fetch_start,
                            end_date=end_date,
                            contract_identity=contract_identity,
                        )
                        norm = _series_from_cache(ibkr_series)
                        if not norm.empty and not norm.dropna().empty:
                            warnings.append(
                                f"Priced option {ticker} via IBKR Gateway fallback ({len(norm)} monthly bars)."
                            )
                            ibkr_priced_symbols["option"].add(ticker)
                        else:
                            if not contract_identity:
                                warnings.append(
                                    f"No contract_identity available for option {ticker}; IBKR option pricing may fail."
                                )
                            warnings.append(
                                f"IBKR fallback returned no data for option {ticker} (entitlements or contract details may be unavailable)."
                            )
                            unpriceable_reason = "option_no_fifo_or_ibkr_data"
                    except Exception as ibkr_exc:
                        warnings.append(f"IBKR fallback also failed for option {ticker}: {ibkr_exc}")
                        unpriceable_reason = "option_ibkr_error"
            else:
                try:
                    series = fetch_monthly_close(
                        ticker,
                        start_date=price_fetch_start,
                        end_date=end_date,
                        fmp_ticker_map=fmp_ticker_map or None,
                    )
                    norm = _series_from_cache(series)
                except Exception as exc:
                    norm = pd.Series(dtype=float)
                    if instrument_type == "futures":
                        warnings.append(
                            f"FMP price fetch failed for futures {ticker}: {exc}; trying IBKR fallback."
                        )
                    elif instrument_type == "fx":
                        warnings.append(
                            f"FMP price fetch failed for FX {ticker}: {exc}; trying IBKR fallback."
                        )
                    elif instrument_type == "bond":
                        warnings.append(
                            f"FMP price fetch failed for bond {ticker}: {exc}; trying IBKR fallback."
                        )
                    else:
                        warnings.append(f"Price fetch failed for {ticker}: {exc}")
                    unpriceable_reason = f"{instrument_type}_fmp_error"

            if norm.empty or norm.dropna().empty:
                if instrument_type == "futures":
                    try:
                        from services.ibkr_data.compat import fetch_ibkr_monthly_close

                        ibkr_series = fetch_ibkr_monthly_close(
                            ticker,
                            start_date=price_fetch_start,
                            end_date=end_date,
                        )
                        norm = _series_from_cache(ibkr_series)
                        if not norm.empty and not norm.dropna().empty:
                            warnings.append(
                                f"Priced futures {ticker} via IBKR Gateway fallback ({len(norm)} monthly bars)."
                            )
                            ibkr_priced_symbols["futures"].add(ticker)
                        else:
                            warnings.append(
                                f"IBKR fallback returned no data for futures {ticker} (Gateway may not be running)."
                            )
                            unpriceable_reason = "futures_ibkr_no_data"
                    except Exception as ibkr_exc:
                        warnings.append(f"IBKR fallback also failed for futures {ticker}: {ibkr_exc}")
                        unpriceable_reason = "futures_ibkr_error"
                elif instrument_type == "fx":
                    try:
                        from services.ibkr_data.compat import fetch_ibkr_fx_monthly_close

                        ibkr_series = fetch_ibkr_fx_monthly_close(
                            ticker,
                            start_date=price_fetch_start,
                            end_date=end_date,
                        )
                        norm = _series_from_cache(ibkr_series)
                        if not norm.empty and not norm.dropna().empty:
                            warnings.append(
                                f"Priced FX {ticker} via IBKR Gateway fallback ({len(norm)} monthly bars)."
                            )
                            ibkr_priced_symbols["fx"].add(ticker)
                        else:
                            warnings.append(
                                f"IBKR fallback returned no data for FX {ticker} (Gateway may not be running)."
                            )
                            unpriceable_reason = "fx_ibkr_no_data"
                    except Exception as ibkr_exc:
                        warnings.append(f"IBKR fallback also failed for FX {ticker}: {ibkr_exc}")
                        unpriceable_reason = "fx_ibkr_error"
                elif instrument_type == "bond":
                    con_id = None
                    if isinstance(contract_identity, dict):
                        con_id = contract_identity.get("con_id")
                    if con_id in (None, ""):
                        warnings.append(
                            f"No contract_identity.con_id for bond {ticker}; skipping IBKR bond pricing."
                        )
                        unpriceable_reason = "bond_missing_con_id"
                    else:
                        try:
                            from services.ibkr_data.compat import fetch_ibkr_bond_monthly_close

                            ibkr_series = fetch_ibkr_bond_monthly_close(
                                ticker,
                                start_date=price_fetch_start,
                                end_date=end_date,
                                contract_identity=contract_identity,
                            )
                            norm = _series_from_cache(ibkr_series)
                            if not norm.empty and not norm.dropna().empty:
                                warnings.append(
                                    f"Priced bond {ticker} via IBKR Gateway fallback ({len(norm)} monthly bars)."
                                )
                                ibkr_priced_symbols["bond"].add(ticker)
                            else:
                                warnings.append(
                                    f"IBKR fallback returned no data for bond {ticker} (Gateway/entitlements may be unavailable)."
                                )
                                unpriceable_reason = "bond_ibkr_no_data"
                        except Exception as ibkr_exc:
                            warnings.append(f"IBKR fallback also failed for bond {ticker}: {ibkr_exc}")
                            unpriceable_reason = "bond_ibkr_error"
                elif instrument_type == "equity":
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
                f"Created {len(synthetic_cash_events)} synthetic cash event(s) for cash-flow reconstruction."
            )
        transactions_for_cash = fifo_transactions + synthetic_cash_events

        cash_snapshots, external_flows = derive_cash_and_external_flows(
            fifo_transactions=transactions_for_cash,
            income_with_currency=income_with_currency,
            fx_cache=fx_cache,
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
            incomplete_trades=[],
            fmp_ticker_map=fmp_ticker_map or None,
        )
        observed_cash_snapshots, observed_external_flows = derive_cash_and_external_flows(
            fifo_transactions=fifo_transactions,
            income_with_currency=income_with_currency,
            fx_cache=fx_cache,
        )
        observed_monthly_nav = compute_monthly_nav(
            position_timeline=observed_position_timeline,
            month_ends=month_ends,
            price_cache=price_cache,
            fx_cache=fx_cache,
            cash_snapshots=observed_cash_snapshots,
        )
        observed_net_flows, _ = compute_monthly_external_flows(
            external_flows=observed_external_flows,
            month_ends=month_ends,
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

        start_iso = aligned.index.min().date().isoformat()
        end_iso = aligned.index.max().date().isoformat()

        risk_free_rate = _safe_treasury_rate(inception_date, end_date)
        min_capm = DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 24)

        performance_metrics = compute_performance_metrics(
            portfolio_returns=aligned["portfolio"],
            benchmark_returns=aligned["benchmark"],
            risk_free_rate=risk_free_rate,
            benchmark_ticker=benchmark_ticker,
            start_date=start_iso,
            end_date=end_iso,
            min_capm_observations=min_capm,
        )

        source_breakdown = dict(Counter(str(t.get("source") or "unknown") for t in fifo_transactions))
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

        ibkr_pricing_by_type = {
            instrument: len(ibkr_priced_symbols.get(instrument, set()))
            for instrument in ("futures", "fx", "bond", "option")
        }
        ibkr_pricing_total = int(sum(ibkr_pricing_by_type.values()))

        realized_metadata = {
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "net_contributions": round(net_contributions, 2),
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
            "income": {
                "total": round(income_total, 2),
                "dividends": round(_as_float(income_summary_usd.get("dividends"), 0.0), 2),
                "interest": round(_as_float(income_summary_usd.get("interest"), 0.0), 2),
                "by_month": income_analysis.by_month,
                "by_symbol": income_analysis.by_symbol,
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
            cumulative = (1.0 + monthly_returns).cumprod()
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
        performance_metrics["pnl_basis"] = realized_metadata["pnl_basis"]

        from core.result_objects import RealizedPerformanceResult
        return RealizedPerformanceResult.from_analysis_dict(performance_metrics)

    except Exception as exc:
        return {
            "status": "error",
            "message": f"Realized performance analysis failed: {exc}",
            "data_warnings": sorted(set(warnings)) if warnings else [],
        }


__all__ = [
    "build_position_timeline",
    "derive_cash_and_external_flows",
    "compute_monthly_nav",
    "compute_monthly_external_flows",
    "compute_monthly_returns",
    "analyze_realized_performance",
]
