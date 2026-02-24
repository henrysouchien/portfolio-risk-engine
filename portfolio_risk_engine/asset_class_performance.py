"""
Asset Class Performance - Core Business Logic (monthly-only periods)

Pure functions to compute portfolio asset-class performance over a selected
monthly period window using cached price data. No logging, no services here.
"""
from __future__ import annotations

from typing import Dict
from datetime import datetime, timedelta

from portfolio_risk_engine.data_loader import fetch_monthly_close


SUPPORTED_PERIODS = {"1M", "3M", "6M", "1Y", "YTD"}


def get_period_start_date(time_period: str) -> str:
    """Return ISO date string for the start of the given monthly period.

    Supported periods: 1M, 3M, 6M, 1Y, YTD
    Defaults to 1M if unknown.
    """
    now = datetime.now()
    period = (time_period or "1M").upper()
    if period == "3M":
        start = now - timedelta(days=90)
    elif period == "6M":
        start = now - timedelta(days=180)
    elif period == "1Y":
        start = now - timedelta(days=365)
    elif period == "YTD":
        start = datetime(now.year, 1, 1)
    else:
        # Default 1M
        start = now - timedelta(days=30)
    return start.strftime("%Y-%m-%d")


def group_holdings_by_asset_class(
    portfolio_weights: Dict[str, float],
    asset_class_mapping: Dict[str, str]
) -> Dict[str, Dict[str, float]]:
    """Group weights by asset class using a ticker→asset_class mapping."""
    grouped: Dict[str, Dict[str, float]] = {}
    for ticker, weight in (portfolio_weights or {}).items():
        asset_class = asset_class_mapping.get(ticker, "unknown")
        bucket = grouped.setdefault(asset_class, {})
        bucket[ticker] = weight
    return grouped


def calculate_weighted_portfolio_return(
    holdings: Dict[str, float],
    time_period: str,
    fmp_ticker_map: Dict[str, str] | None = None,
) -> float:
    """Compute weighted period return for a set of holdings using monthly closes."""
    total_weight = sum(holdings.values()) or 0.0
    if total_weight == 0:
        return 0.0

    start_date = get_period_start_date(time_period)
    total_return = 0.0
    for ticker, weight in holdings.items():
        series = fetch_monthly_close(
            ticker,
            start_date=start_date,
            fmp_ticker_map=fmp_ticker_map,
        )
        if len(series) >= 2:
            period_ret = (series.iloc[-1] / series.iloc[0]) - 1.0
            total_return += period_ret * (weight / total_weight)
    return total_return


def calculate_asset_class_returns(
    asset_class_holdings: Dict[str, Dict[str, float]],
    time_period: str,
    fmp_ticker_map: Dict[str, str] | None = None,
) -> Dict[str, float]:
    """Calculate weighted returns per asset class for the selected period."""
    results: Dict[str, float] = {}
    for asset_class, class_holdings in (asset_class_holdings or {}).items():
        if not class_holdings:
            continue
        results[asset_class] = calculate_weighted_portfolio_return(
            class_holdings,
            time_period,
            fmp_ticker_map=fmp_ticker_map,
        )
    return results


def classify_performance_change(return_pct: float) -> str:
    """Classify change as positive/negative/neutral using ±0.5% thresholds."""
    if return_pct is None:
        return "neutral"
    if return_pct > 0.005:
        return "positive"
    if return_pct < -0.005:
        return "negative"
    return "neutral"
