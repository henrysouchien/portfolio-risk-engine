"""
Income Projection Engine

Pure computation module for dividend income projection. No I/O — takes
pre-fetched data (positions, dividend history, forward calendar) and produces
confirmed + estimated income projections by month.

Key functions:
- classify_dividend_type(): categorize payer behavior (regular, variable, etc.)
- estimate_annual_dividend(): TTM-based annual dividend estimate per share
- build_income_projection(): main engine combining confirmed + estimated income
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


def classify_dividend_type(history_df: Optional[pd.DataFrame]) -> str:
    """
    Classify a stock's dividend behavior from history.

    Returns:
        "regular" — consistent payments at predictable frequency
        "variable" — payments vary significantly (>30% coefficient of variation)
        "recently_initiated" — fewer than 4 payments in history
        "none" — no dividend history
    """
    if history_df is None or history_df.empty:
        return "none"

    amounts = pd.to_numeric(
        history_df.get("adjDividend", pd.Series(dtype=float)), errors="coerce"
    ).dropna()

    if amounts.empty:
        return "none"

    if len(amounts) < 4:
        return "recently_initiated"

    # Coefficient of variation
    mean_val = amounts.mean()
    if mean_val == 0:
        return "none"

    cv = amounts.std() / mean_val
    if cv > 0.30:
        return "variable"

    return "regular"


def _detect_special_dividends(history_df: pd.DataFrame) -> list[dict]:
    """
    Identify non-recurring (special) dividend payments.

    A payment is "special" when:
    - It exceeds 2x the median regular payment, OR
    - The frequency/label field contains "special" (case-insensitive)

    Returns list of special dividend records with ticker, date, amount, reason.
    """
    if history_df is None or history_df.empty:
        return []

    amounts = pd.to_numeric(
        history_df.get("adjDividend", pd.Series(dtype=float)), errors="coerce"
    ).fillna(0)

    if amounts.empty or len(amounts) < 2:
        return []

    median_val = amounts.median()
    specials = []

    for idx_date, row in history_df.iterrows():
        amount = float(pd.to_numeric(row.get("adjDividend", 0), errors="coerce") or 0)
        freq = str(row.get("frequency", "")).lower() if row.get("frequency") else ""
        label = str(row.get("label", "")).lower() if row.get("label") else ""

        reason = None
        if "special" in freq or "special" in label:
            reason = "special"
        elif median_val > 0 and amount > 2.0 * median_val:
            reason = f"outlier (>{2 * median_val:.4f}, 2x median)"

        if reason:
            date_str = str(idx_date)[:10] if idx_date is not None else None
            specials.append({
                "date": date_str,
                "amount": amount,
                "reason": reason,
            })

    return specials


def _infer_frequency(history_df: pd.DataFrame) -> str:
    """Infer dividend frequency from history data."""
    if history_df is None or history_df.empty:
        return "None"

    # Try the frequency column first
    freq_col = history_df.get("frequency")
    if freq_col is not None and not freq_col.isna().all():
        recent_freq = freq_col.iloc[-1] if not freq_col.empty else None
        if recent_freq and not pd.isna(recent_freq):
            freq_lower = str(recent_freq).lower()
            if "monthly" in freq_lower or "month" in freq_lower:
                return "Monthly"
            elif "quarterly" in freq_lower or "quarter" in freq_lower:
                return "Quarterly"
            elif "semi" in freq_lower:
                return "Semi-Annual"
            elif "annual" in freq_lower or "year" in freq_lower:
                return "Annual"

    # Estimate from date spacing
    if hasattr(history_df.index, 'to_series'):
        dates = history_df.index.to_series()
    else:
        dates = pd.Series(history_df.index)

    dates = pd.to_datetime(dates, errors="coerce").dropna().sort_values()
    if len(dates) >= 2:
        diffs = dates.diff().dropna()
        avg_days = diffs.dt.days.mean()
        if avg_days < 40:
            return "Monthly"
        elif avg_days < 120:
            return "Quarterly"
        elif avg_days < 250:
            return "Semi-Annual"
        else:
            return "Annual"

    return "Unknown"


def estimate_annual_dividend(history_df: Optional[pd.DataFrame]) -> dict:
    """
    Estimate annual dividend from history using TTM methodology.

    Returns:
        {
            "annual_dividend_per_share": float,
            "frequency": str,
            "dividend_type": str,
            "ttm_payments": int,
            "latest_payment_amount": float,
            "latest_ex_date": str or None,
        }
    """
    dividend_type = classify_dividend_type(history_df)

    if dividend_type == "none" or history_df is None or history_df.empty:
        return {
            "annual_dividend_per_share": 0.0,
            "frequency": "None",
            "dividend_type": "none",
            "ttm_payments": 0,
            "latest_payment_amount": 0.0,
            "latest_ex_date": None,
        }

    # Filter out special dividends from projection
    specials = _detect_special_dividends(history_df)
    special_dates = {s["date"] for s in specials}

    amounts = []
    for idx_date, row in history_df.iterrows():
        date_str = str(idx_date)[:10]
        if date_str in special_dates:
            continue
        amt = float(pd.to_numeric(row.get("adjDividend", 0), errors="coerce") or 0)
        if amt > 0:
            amounts.append(amt)

    frequency = _infer_frequency(history_df)

    # Get latest ex-date
    dates = pd.to_datetime(history_df.index, errors="coerce").dropna()
    latest_ex_date = str(dates.max())[:10] if len(dates) > 0 else None

    # Latest payment amount (non-special)
    latest_payment = amounts[-1] if amounts else 0.0

    # TTM sum from the filtered history (data_loader already does TTM for us,
    # but we need to handle the case where we got full history)
    ttm_payments = len(amounts)
    ttm_sum = sum(amounts)

    # Annualize based on frequency
    if frequency == "Quarterly":
        if ttm_payments >= 4:
            annual_dividend = sum(amounts[-4:])
        elif ttm_payments > 0:
            annual_dividend = (ttm_sum / ttm_payments) * 4
        else:
            annual_dividend = 0.0
    elif frequency == "Monthly":
        if ttm_payments >= 12:
            annual_dividend = sum(amounts[-12:])
        elif ttm_payments > 0:
            annual_dividend = (ttm_sum / ttm_payments) * 12
        else:
            annual_dividend = 0.0
    elif frequency == "Semi-Annual":
        if ttm_payments >= 2:
            annual_dividend = sum(amounts[-2:])
        elif ttm_payments > 0:
            annual_dividend = ttm_sum * 2
        else:
            annual_dividend = 0.0
    elif frequency == "Annual":
        annual_dividend = amounts[-1] if amounts else 0.0
    else:
        # Unknown frequency — use TTM sum
        annual_dividend = ttm_sum

    return {
        "annual_dividend_per_share": round(annual_dividend, 6),
        "frequency": frequency,
        "dividend_type": dividend_type,
        "ttm_payments": ttm_payments,
        "latest_payment_amount": round(latest_payment, 6),
        "latest_ex_date": latest_ex_date,
    }


def _project_payment_months(
    frequency: str,
    anchor_month: Optional[str],
    projection_months: int,
    start_month: str,
) -> list[str]:
    """
    Generate projected payment months based on frequency and anchor.

    Args:
        frequency: "Quarterly", "Monthly", "Semi-Annual", "Annual"
        anchor_month: YYYY-MM of most recent payment (anchor for schedule)
        projection_months: how many months to project forward
        start_month: YYYY-MM of projection start

    Returns:
        List of YYYY-MM strings for projected payment months
    """
    if frequency == "None" or not anchor_month:
        return []

    start = pd.Timestamp(start_month + "-01")
    end = start + pd.DateOffset(months=projection_months)

    if frequency == "Monthly":
        interval = 1
    elif frequency == "Quarterly":
        interval = 3
    elif frequency == "Semi-Annual":
        interval = 6
    elif frequency == "Annual":
        interval = 12
    else:
        interval = 3  # default to quarterly

    anchor = pd.Timestamp(anchor_month + "-01")
    months = []

    # Walk forward from anchor by interval until past end
    current = anchor
    while current < end:
        if current >= start:
            months.append(current.strftime("%Y-%m"))
        current = current + pd.DateOffset(months=interval)

    # Also walk backward from anchor to fill earlier projected months
    current = anchor - pd.DateOffset(months=interval)
    while current >= start:
        months.append(current.strftime("%Y-%m"))
        current = current - pd.DateOffset(months=interval)

    months = sorted(set(months))
    return [m for m in months if pd.Timestamp(m + "-01") < end]


def _assign_calendar_quarter(month_str: str) -> str:
    """Convert YYYY-MM to quarter label like Q1_2026."""
    try:
        ts = pd.Timestamp(month_str + "-01")
        quarter = (ts.month - 1) // 3 + 1
        return f"Q{quarter}_{ts.year}"
    except Exception:
        return "Unknown"


def build_income_projection(
    positions: list[dict],
    dividend_estimates: dict[str, dict],
    calendar_entries: list[dict],
    projection_months: int = 12,
) -> dict:
    """
    Build complete income projection combining confirmed and estimated data.

    Args:
        positions: List of position dicts with ticker, shares, value, currency, cost_basis
        dividend_estimates: {ticker: estimate_dict} from estimate_annual_dividend()
        calendar_entries: Forward calendar entries filtered to portfolio holdings
        projection_months: Forward projection window

    Returns:
        Full projection dict with totals, per-position detail, monthly calendar,
        quarterly summary, and metadata.
    """
    today = date.today()
    start_month = today.strftime("%Y-%m")

    # Build calendar lookup: {(ticker, YYYY-MM): [entries]}
    confirmed_by_ticker_month: dict[tuple[str, str], list[dict]] = {}
    for entry in calendar_entries:
        symbol = entry.get("symbol", "")
        # Use payment date if available, otherwise ex-date
        pay_date_str = entry.get("paymentDate") or entry.get("date") or entry.get("recordDate")
        if not pay_date_str or not symbol:
            continue
        try:
            pay_date = pd.Timestamp(pay_date_str)
            month_key = pay_date.strftime("%Y-%m")
        except Exception:
            continue

        key = (symbol, month_key)
        if key not in confirmed_by_ticker_month:
            confirmed_by_ticker_month[key] = []
        confirmed_by_ticker_month[key].append(entry)

    # Pre-compute ticker→ex_date from calendar for "next_ex_date"
    next_ex_dates: dict[str, str] = {}
    next_payment_dates: dict[str, str] = {}
    for entry in sorted(calendar_entries, key=lambda e: e.get("date", "")):
        symbol = entry.get("symbol", "")
        ex_date = entry.get("date")
        pay_date = entry.get("paymentDate")
        if symbol and ex_date and symbol not in next_ex_dates:
            next_ex_dates[symbol] = ex_date
        if symbol and pay_date and symbol not in next_payment_dates:
            next_payment_dates[symbol] = pay_date

    # Monthly calendar: {YYYY-MM: {confirmed, estimated, total, payments}}
    monthly_calendar: dict[str, dict] = {}

    # Initialize months
    for i in range(projection_months):
        m = (pd.Timestamp(start_month + "-01") + pd.DateOffset(months=i)).strftime("%Y-%m")
        monthly_calendar[m] = {
            "confirmed": 0.0,
            "estimated": 0.0,
            "total": 0.0,
            "payments": [],
        }

    position_details = []
    total_portfolio_value = 0.0
    total_portfolio_cost = 0.0
    total_projected_income = 0.0
    positions_with_divs = 0
    positions_without_divs = 0
    all_special_dividends = []
    income_by_frequency: dict[str, float] = {}

    for pos in positions:
        ticker = pos.get("ticker", "")
        shares = float(pos.get("quantity") or pos.get("shares") or 0)
        market_value = float(pos.get("value") or 0)
        cost_basis = float(pos.get("cost_basis_usd") or pos.get("cost_basis") or 0)
        currency = pos.get("currency", "USD")

        total_portfolio_value += market_value
        total_portfolio_cost += cost_basis

        estimate = dividend_estimates.get(ticker, {})
        annual_div_ps = estimate.get("annual_dividend_per_share", 0)
        frequency = estimate.get("frequency", "None")
        dividend_type = estimate.get("dividend_type", "none")
        ttm_payments = estimate.get("ttm_payments", 0)
        latest_payment = estimate.get("latest_payment_amount", 0)
        latest_ex_date = estimate.get("latest_ex_date")

        projected_annual_income = annual_div_ps * shares

        # Yield calculations
        yield_on_value = (projected_annual_income / market_value * 100) if market_value > 0 else 0
        yield_on_cost = (projected_annual_income / cost_basis * 100) if cost_basis > 0 else 0

        if annual_div_ps > 0:
            positions_with_divs += 1
        else:
            positions_without_divs += 1

        total_projected_income += projected_annual_income

        # Track income by frequency
        if frequency != "None" and projected_annual_income != 0:
            income_by_frequency[frequency] = income_by_frequency.get(frequency, 0) + projected_annual_income

        # Per-position detail
        pos_detail = {
            "ticker": ticker,
            "shares": shares,
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "annual_dividend_per_share": round(annual_div_ps, 4),
            "projected_annual_income": round(projected_annual_income, 2),
            "yield_on_value": round(yield_on_value, 2),
            "yield_on_cost": round(yield_on_cost, 2),
            "frequency": frequency,
            "dividend_type": dividend_type,
            "next_ex_date": next_ex_dates.get(ticker),
            "next_payment_date": next_payment_dates.get(ticker),
            "ttm_payments": ttm_payments,
            "latest_payment_amount": round(latest_payment, 4),
            "currency": currency,
        }
        position_details.append(pos_detail)

        # Populate monthly calendar
        if annual_div_ps <= 0 and shares >= 0:
            continue  # Non-payer (or zero) and not short — nothing to project

        # 1. Add confirmed entries from calendar
        confirmed_months_for_ticker = set()
        for month_key in list(monthly_calendar.keys()):
            cal_key = (ticker, month_key)
            if cal_key in confirmed_by_ticker_month:
                for entry in confirmed_by_ticker_month[cal_key]:
                    div_amount = float(entry.get("adjDividend") or entry.get("dividend") or 0)
                    if div_amount <= 0:
                        continue
                    income = div_amount * shares
                    monthly_calendar[month_key]["confirmed"] += income
                    monthly_calendar[month_key]["total"] += income
                    monthly_calendar[month_key]["payments"].append({
                        "ticker": ticker,
                        "amount": round(income, 2),
                        "dividend_per_share": round(div_amount, 4),
                        "ex_date": entry.get("date"),
                        "payment_date": entry.get("paymentDate"),
                        "source": "confirmed",
                    })
                    confirmed_months_for_ticker.add(month_key)

        # 2. Add estimated entries for months without confirmed data
        if annual_div_ps > 0 or (shares < 0 and annual_div_ps != 0):
            anchor_month = latest_ex_date[:7] if latest_ex_date else start_month
            projected_months = _project_payment_months(
                frequency, anchor_month, projection_months, start_month
            )

            # Per-payment amount
            if frequency == "Monthly":
                per_payment = annual_div_ps / 12
            elif frequency == "Quarterly":
                per_payment = annual_div_ps / 4
            elif frequency == "Semi-Annual":
                per_payment = annual_div_ps / 2
            elif frequency == "Annual":
                per_payment = annual_div_ps
            else:
                per_payment = annual_div_ps / 4  # default quarterly

            for m in projected_months:
                if m in monthly_calendar and m not in confirmed_months_for_ticker:
                    income = per_payment * shares
                    monthly_calendar[m]["estimated"] += income
                    monthly_calendar[m]["total"] += income
                    monthly_calendar[m]["payments"].append({
                        "ticker": ticker,
                        "amount": round(income, 2),
                        "dividend_per_share": round(per_payment, 4),
                        "ex_date": None,
                        "payment_date": None,
                        "source": "estimated",
                    })

    # Round monthly totals
    for m in monthly_calendar:
        monthly_calendar[m]["confirmed"] = round(monthly_calendar[m]["confirmed"], 2)
        monthly_calendar[m]["estimated"] = round(monthly_calendar[m]["estimated"], 2)
        monthly_calendar[m]["total"] = round(monthly_calendar[m]["total"], 2)

    # Round income_by_frequency
    income_by_frequency = {k: round(v, 2) for k, v in income_by_frequency.items()}

    # Quarterly summary
    quarterly_summary: dict[str, dict] = {}
    for m, data in monthly_calendar.items():
        q = _assign_calendar_quarter(m)
        if q not in quarterly_summary:
            quarterly_summary[q] = {"total": 0.0, "payments": 0}
        quarterly_summary[q]["total"] = round(quarterly_summary[q]["total"] + data["total"], 2)
        quarterly_summary[q]["payments"] += len(data["payments"])

    # Portfolio yields
    portfolio_yield_on_value = (
        (total_projected_income / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
    )
    portfolio_yield_on_cost = (
        (total_projected_income / total_portfolio_cost * 100) if total_portfolio_cost > 0 else 0
    )

    # Confirmed income months
    confirmed_months = sum(1 for m in monthly_calendar.values() if m["confirmed"] > 0)

    return {
        "total_projected_annual_income": round(total_projected_income, 2),
        "portfolio_yield_on_value": round(portfolio_yield_on_value, 2),
        "portfolio_yield_on_cost": round(portfolio_yield_on_cost, 2),
        "positions": position_details,
        "monthly_calendar": monthly_calendar,
        "quarterly_summary": quarterly_summary,
        "income_by_frequency": income_by_frequency,
        "metadata": {
            "projection_months": projection_months,
            "positions_with_dividends": positions_with_divs,
            "positions_without_dividends": positions_without_divs,
            "confirmed_income_months": confirmed_months,
            "special_dividends_excluded": all_special_dividends,
        },
    }
