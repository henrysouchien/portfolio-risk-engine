"""Realized portfolio performance analysis pipeline.

Builds monthly, cash-inclusive portfolio returns from transaction history and
current holdings, then computes risk/performance metrics via the shared
performance metrics engine.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.performance_metrics_engine import compute_performance_metrics
from factor_utils import calc_monthly_returns
from data_loader import fetch_monthly_close, fetch_monthly_treasury_rates
from fmp.fx import get_monthly_fx_series
from settings import DATA_QUALITY_THRESHOLDS
from trading_analysis.analyzer import TradingAnalyzer
from trading_analysis.data_fetcher import fetch_transactions_for_source
from trading_analysis.fifo_matcher import FIFOMatcher, IncompleteTrade
from utils.ticker_resolver import load_exchange_mappings


TYPE_ORDER = {
    "SELL": 0,
    "SHORT": 1,
    "INCOME": 2,
    "BUY": 3,
    "COVER": 4,
}


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
        cost_basis = pos.get("cost_basis_usd")
        if cost_basis is None:
            cost_basis = pos.get("cost_basis")

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
        else:
            current_positions[ticker] = {
                "shares": quantity,
                "currency": str(currency),
                "cost_basis": None if cost_basis is None else _as_float(cost_basis, 0.0),
                "value": _as_float(pos.get("value"), 0.0),
            }

        fmp_ticker = pos.get("fmp_ticker")
        if isinstance(fmp_ticker, str) and fmp_ticker.strip() and ticker not in fmp_ticker_map:
            fmp_ticker_map[ticker] = fmp_ticker.strip()

    return current_positions, fmp_ticker_map, warnings


def _event_fx_rate(currency: str, when: datetime, fx_cache: Dict[str, pd.Series]) -> float:
    """Get FX currency->USD rate for event timestamp."""
    ccy = (currency or "USD").upper()
    if ccy == "USD":
        return 1.0
    return _value_at_or_before(fx_cache.get(ccy), when, default=1.0)


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
    List[str],
]:
    """Walk transactions forward to reconstruct quantities by (ticker, currency, direction)."""
    del fmp_ticker_map  # Reserved for future use.

    position_events: Dict[Tuple[str, str, str], List[Tuple[datetime, float]]] = defaultdict(list)
    synthetic_positions: List[Dict[str, str]] = []
    synthetic_entries: List[Dict[str, Any]] = []
    warnings: List[str] = []

    opening_qty: Dict[Tuple[str, str, str], float] = defaultdict(float)
    exit_qty: Dict[Tuple[str, str, str], float] = defaultdict(float)

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

        if txn_type == "BUY":
            key = (symbol, currency, "LONG")
            position_events[key].append((date, qty))
            opening_qty[key] += qty
        elif txn_type == "SELL":
            key = (symbol, currency, "LONG")
            position_events[key].append((date, -qty))
            exit_qty[key] += qty
        elif txn_type == "SHORT":
            key = (symbol, currency, "SHORT")
            position_events[key].append((date, qty))
            opening_qty[key] += qty
        elif txn_type == "COVER":
            key = (symbol, currency, "SHORT")
            position_events[key].append((date, -qty))
            exit_qty[key] += qty

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

        required_entry_qty = abs(shares) + exit_qty.get(key, 0.0)
        known_openings = opening_qty.get(key, 0.0)
        missing_openings = required_entry_qty - known_openings

        if missing_openings > 1e-6:
            position_events[key].append((inception_date, missing_openings))
            synthetic_keys.add(key)
            synthetic_qty_by_key[key] += missing_openings
            current_position_synthetic_keys.add(key)
            synthetic_entries.append(
                {
                    "ticker": ticker,
                    "currency": currency,
                    "direction": direction,
                    "date": inception_date,
                    "quantity": missing_openings,
                    "source": "synthetic_current_position",
                    "price_hint": None,
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

    return dict(position_events), synthetic_positions, synthetic_entries, warnings


def _create_synthetic_cash_events(
    synthetic_entries: List[Dict[str, Any]],
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
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
    """Replay trades+income stream to derive cash and external capital injections."""
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
            cash = 0.0

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
            denom = flow_weighted if flow_weighted > 0 else flow_net
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


def analyze_realized_performance(
    positions: "PositionResult",
    user_email: str,
    benchmark_ticker: str = "SPY",
    source: str = "all",
    include_series: bool = False,
) -> Dict[str, Any]:
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
                "source filter applies to transactions only; current positions remain consolidated across providers."
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
        fifo_transactions.sort(key=lambda t: _to_datetime(t.get("date")) or datetime.min)

        futures_map = load_exchange_mappings().get("ibkr_futures_to_fmp", {})
        equity_symbols = {
            str(txn.get("symbol") or "").strip().upper()
            for txn in fifo_transactions
            if not txn.get("is_futures") and not txn.get("is_option") and txn.get("symbol")
        }
        futures_mapped: set[str] = set()
        for txn in fifo_transactions:
            sym = str(txn.get("symbol") or "").strip().upper()
            if txn.get("is_futures") and sym in futures_map and sym not in futures_mapped:
                futures_mapped.add(sym)
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

        fifo_result = FIFOMatcher().process_transactions(fifo_transactions)

        position_timeline, synthetic_positions, synthetic_entries, timeline_warnings = build_position_timeline(
            fifo_transactions=fifo_transactions,
            current_positions=current_positions,
            inception_date=inception_date,
            incomplete_trades=fifo_result.incomplete_trades,
            fmp_ticker_map=fmp_ticker_map or None,
        )
        warnings.extend(timeline_warnings)

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

        month_ends = _month_end_range(inception_date, end_date)

        tickers = sorted({key[0] for key in position_timeline.keys()})
        # Fetch prices starting 2 months before inception so that the strict
        # backward-only price lookup in _create_synthetic_cash_events has
        # at least one prior month-end price available at the inception date.
        price_fetch_start = inception_date - timedelta(days=62)
        price_cache: Dict[str, pd.Series] = {}
        for ticker in tickers:
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
                if ticker in futures_mapped:
                    warnings.append(
                        f"FMP price fetch failed for futures {ticker}: {exc}; trying IBKR fallback."
                    )
                else:
                    warnings.append(f"Price fetch failed for {ticker}: {exc}")

            if (norm.empty or norm.dropna().empty) and ticker in futures_mapped:
                try:
                    from services.ibkr_historical_data import fetch_ibkr_monthly_close

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
                    else:
                        warnings.append(
                            f"IBKR fallback returned no data for futures {ticker} (Gateway may not be running)."
                        )
                except Exception as ibkr_exc:
                    warnings.append(f"IBKR fallback also failed for futures {ticker}: {ibkr_exc}")

            if norm.empty or norm.dropna().empty:
                warnings.append(f"No monthly prices found for {ticker}; valuing as 0 when unavailable.")
            price_cache[ticker] = norm

        currencies = {"USD"}
        for _, ccy, _ in position_timeline.keys():
            currencies.add((ccy or "USD").upper())
        for txn in fifo_transactions:
            currencies.add(str(txn.get("currency") or "USD").upper())
        for inc in income_with_currency:
            currencies.add(str(inc.get("currency") or "USD").upper())

        fx_cache: Dict[str, pd.Series] = {}
        for ccy in sorted(currencies):
            try:
                fx_cache[ccy] = _series_from_cache(
                    get_monthly_fx_series(ccy, inception_date, end_date)
                )
            except Exception as exc:
                warnings.append(f"FX series fetch failed for {ccy}: {exc}; using 1.0 fallback.")
                fx_cache[ccy] = pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp(inception_date)]))

        synthetic_cash_events, synth_cash_warnings = _create_synthetic_cash_events(
            synthetic_entries=synthetic_entries,
            price_cache=price_cache,
            fx_cache=fx_cache,
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

        monthly_returns, return_warnings = compute_monthly_returns(
            monthly_nav=monthly_nav,
            net_flows=net_flows,
            time_weighted_flows=tw_flows,
        )
        warnings.extend(return_warnings)

        total_cost_basis = 0.0
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
                total_cost_basis += _as_float(cb, 0.0)

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

        # Check current holdings direction — historical closed shorts shouldn't
        # disable the safety clamp for a currently long-only portfolio.
        is_long_only = all(direction != "SHORT" for _, _, direction in current_position_keys)
        if data_coverage < 100.0 and is_long_only:
            for ts in monthly_returns.index:
                raw = _as_float(monthly_returns.loc[ts], default=np.nan)
                if not np.isfinite(raw):
                    continue
                if raw < -1.0:
                    warnings.append(
                        f"{ts.date().isoformat()}: Clamping return from {raw:.2%} to -100.0%. "
                        "Likely caused by incomplete transaction history."
                    )
                    monthly_returns.loc[ts] = -1.0
                elif abs(raw) > 3.0:
                    warnings.append(
                        f"{ts.date().isoformat()}: Extreme return detected ({raw:.2%}). "
                        "This may indicate missing transaction history."
                    )

        monthly_returns = monthly_returns.replace([np.inf, -np.inf], np.nan).dropna()
        if monthly_returns.empty:
            return {
                "status": "error",
                "message": "No valid monthly return observations available after NAV/flow reconstruction.",
                "data_warnings": sorted(set(warnings)),
            }

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
        realized_pnl = float(sum(_as_float(ct.pnl_dollars, 0.0) for ct in fifo_result.closed_trades))
        unrealized_pnl = float(
            _compute_unrealized_pnl_usd(
                fifo_result=fifo_result,
                price_cache=price_cache,
                fx_cache=fx_cache,
                as_of=end_date,
            )
        )
        net_contributions = float(_compute_net_contributions_usd(fifo_transactions, fx_cache))

        income_analysis = analyzer.analyze_income()

        income_yield_on_cost = (
            (income_analysis.projected_annual / total_cost_basis) * 100.0 if total_cost_basis > 0 else 0.0
        )
        income_yield_on_value = (
            (income_analysis.projected_annual / current_portfolio_value) * 100.0
            if current_portfolio_value > 0
            else 0.0
        )

        realized_metadata = {
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "net_contributions": round(net_contributions, 2),
            "income": {
                "total": round(_as_float(income_analysis.total_income, 0.0), 2),
                "dividends": round(_as_float(income_analysis.total_dividends, 0.0), 2),
                "interest": round(_as_float(income_analysis.total_interest, 0.0), 2),
                "by_month": income_analysis.by_month,
                "by_symbol": income_analysis.by_symbol,
                "current_monthly_rate": round(_as_float(income_analysis.current_monthly_rate, 0.0), 2),
                "projected_annual": round(_as_float(income_analysis.projected_annual, 0.0), 2),
                "yield_on_cost": round(income_yield_on_cost, 4),
                "yield_on_value": round(income_yield_on_value, 4),
            },
            "data_coverage": round(data_coverage, 2),
            "inception_date": inception_date.date().isoformat(),
            "synthetic_positions": synthetic_positions,
            "source_breakdown": source_breakdown,
            "data_warnings": sorted(set(warnings)),
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

        return performance_metrics

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
