from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import brentq, newton

from . import _helpers

_LOG = logging.getLogger(__name__)

_BRACKETS: Tuple[Tuple[float, float], ...] = (
    (-0.5, 2.0),
    (-0.75, 5.0),
    (-0.9, 10.0),
    (-0.95, 25.0),
    (-0.99, 100.0),
)


def _xnpv(rate: float, dates: Sequence[datetime], amounts: Sequence[float]) -> float:
    if rate <= -1.0:
        return np.inf
    base = 1.0 + rate
    start = dates[0]
    total = 0.0
    for when, amount in zip(dates, amounts):
        years = max((when - start).total_seconds(), 0.0) / (365.25 * 86400.0)
        try:
            total += float(amount) / (base ** years)
        except (OverflowError, ZeroDivisionError):
            return np.inf
    return float(total)


def xirr(dates: Sequence[datetime], amounts: Sequence[float], guess: float = 0.1) -> Optional[float]:
    if len(dates) != len(amounts) or len(dates) < 2:
        return None

    cleaned: List[Tuple[datetime, float]] = []
    for raw_dt, raw_amt in zip(dates, amounts):
        dt = _helpers._to_datetime(raw_dt)
        if dt is None:
            continue
        cleaned.append((dt, _helpers._as_float(raw_amt, 0.0)))
    if len(cleaned) < 2:
        return None

    cleaned.sort(key=lambda row: row[0])
    ordered_dates = [row[0] for row in cleaned]
    ordered_amounts = [row[1] for row in cleaned]
    has_positive = any(val > 0.0 for val in ordered_amounts)
    has_negative = any(val < 0.0 for val in ordered_amounts)
    if not (has_positive and has_negative):
        return None

    def _f(rate: float) -> float:
        return _xnpv(rate, ordered_dates, ordered_amounts)

    for low, high in _BRACKETS:
        f_low = _f(low)
        f_high = _f(high)
        if not np.isfinite(f_low) or not np.isfinite(f_high):
            continue
        if abs(f_low) < 1e-10:
            return low
        if abs(f_high) < 1e-10:
            return high
        if f_low * f_high < 0.0:
            try:
                root = brentq(_f, low, high, maxiter=1000)
                if np.isfinite(root) and root > -1.0:
                    return float(root)
            except Exception:
                continue

    _LOG.warning("XIRR bracket search found no sign change in [%s, %s].", _BRACKETS[0], _BRACKETS[-1])

    try:
        root = newton(_f, x0=guess, maxiter=100)
        if np.isfinite(root) and root > -1.0 and abs(_f(root)) < 1e-6:
            return float(root)
    except Exception:
        pass
    return None


def compute_mwr(
    external_flows: List[Tuple[datetime, float]],
    nav_start: float,
    nav_end: float,
    start_date: datetime,
    end_date: datetime,
) -> Tuple[Optional[float], str]:
    start = _helpers._to_datetime(start_date)
    end = _helpers._to_datetime(end_date)
    if start is None or end is None or end <= start:
        return None, "no_data"

    days = max((end - start).total_seconds() / 86400.0, 0.0)
    if days < 30.0:
        return None, "no_data"

    nav_start_value = _helpers._as_float(nav_start, np.nan)
    nav_end_value = _helpers._as_float(nav_end, np.nan)
    if not np.isfinite(nav_start_value) or not np.isfinite(nav_end_value) or abs(nav_start_value) <= 1e-9:
        return None, "no_data"

    flows_in_window: List[Tuple[datetime, float]] = []
    for raw_when, raw_amount in list(external_flows or []):
        when = _helpers._to_datetime(raw_when)
        if when is None or when < start or when > end:
            continue
        amount = _helpers._as_float(raw_amount, 0.0)
        if abs(amount) <= 1e-12:
            continue
        flows_in_window.append((when, amount))
    flows_in_window.sort(key=lambda row: row[0])

    if not flows_in_window:
        ratio = nav_end_value / nav_start_value
        if ratio < 0.0:
            return None, "failed"
        try:
            annualized = (ratio ** (365.25 / days)) - 1.0
        except (OverflowError, ValueError, ZeroDivisionError):
            return None, "failed"
        if not np.isfinite(annualized):
            return None, "failed"
        return float(annualized), "success"

    # XIRR investor convention: cash out from investor is negative, cash in is positive.
    cash_dates: List[datetime] = [start]
    cash_amounts: List[float] = [-float(nav_start_value)]
    cash_dates.extend(when for when, _ in flows_in_window)
    cash_amounts.extend(-float(amount) for _, amount in flows_in_window)
    cash_dates.append(end)
    cash_amounts.append(float(nav_end_value))

    irr = xirr(cash_dates, cash_amounts)
    if irr is None:
        return None, "failed"
    return float(irr), "success"


__all__ = [
    "xirr",
    "compute_mwr",
]
