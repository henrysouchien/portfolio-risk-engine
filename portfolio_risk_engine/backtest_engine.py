"""Historical backtesting engine for strategy allocations."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS
from portfolio_risk_engine.data_loader import fetch_monthly_close
from portfolio_risk_engine.factor_utils import calc_monthly_returns
from portfolio_risk_engine.performance_metrics_engine import compute_performance_metrics
from portfolio_risk_engine.portfolio_risk import (
    _compute_factor_attribution,
    _compute_sector_attribution,
    _compute_security_attribution,
    _filter_tickers_by_data_availability,
    _get_risk_free_rate,
    compute_portfolio_returns,
    compute_portfolio_returns_partial,
    get_returns_dataframe,
)


def _series_to_month_dict(series: pd.Series) -> Dict[str, float]:
    """Convert monthly DatetimeIndex series to YYYY-MM keyed dict."""
    if series is None or series.empty:
        return {}
    return {
        idx.strftime("%Y-%m"): float(value)
        for idx, value in series.sort_index().items()
    }


def _build_annual_breakdown(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> list[dict[str, float | int]]:
    """Build per-calendar-year compounded return breakdown."""
    if portfolio_returns.empty or benchmark_returns.empty:
        return []

    aligned = pd.DataFrame(
        {"portfolio": portfolio_returns, "benchmark": benchmark_returns}
    ).dropna()
    if aligned.empty:
        return []

    annual_rows: list[dict[str, float | int]] = []
    for year, group in aligned.groupby(aligned.index.year):
        portfolio_total = float((1.0 + group["portfolio"]).prod() - 1.0)
        benchmark_total = float((1.0 + group["benchmark"]).prod() - 1.0)
        portfolio_pct = round(portfolio_total * 100.0, 2)
        benchmark_pct = round(benchmark_total * 100.0, 2)
        annual_rows.append(
            {
                "year": int(year),
                "portfolio_return": portfolio_pct,
                "benchmark_return": benchmark_pct,
                "alpha": round(portfolio_pct - benchmark_pct, 2),
            }
        )
    return annual_rows


def run_backtest(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    benchmark_ticker: str = "SPY",
    risk_free_rate: Optional[float] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    currency_map: Optional[Dict[str, str]] = None,
    instrument_types: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Run a historical backtest for a target allocation over a fixed date window.

    Mirrors ``calculate_portfolio_performance_metrics()`` and adds backtest-
    specific charting outputs (monthly/cumulative series + annual breakdown).
    """
    if not weights:
        return {"error": "Backtest requires non-empty weights"}

    # Window-aware observation gates (supports shorter windows like 1Y).
    default_min_obs = int(
        DATA_QUALITY_THRESHOLDS.get("min_observations_for_expected_returns", 11)
    )
    min_capm_obs = int(
        DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 12)
    )
    try:
        requested_month_points = len(pd.date_range(start=start_date, end=end_date, freq="ME"))
    except Exception:
        requested_month_points = 0
    requested_return_observations = max(1, requested_month_points - 1)
    min_obs = min(default_min_obs, requested_return_observations)

    filtered_weights, excluded_tickers, warnings = _filter_tickers_by_data_availability(
        weights=weights,
        start_date=start_date,
        end_date=end_date,
        min_months=min_obs,
        fmp_ticker_map=fmp_ticker_map,
        instrument_types=instrument_types,
    )

    if not filtered_weights:
        return {
            "error": "Insufficient data for backtest - all tickers excluded",
            "excluded_tickers": excluded_tickers,
            "warnings": warnings,
        }

    df_ret = get_returns_dataframe(
        weights=filtered_weights,
        start_date=start_date,
        end_date=end_date,
        fmp_ticker_map=fmp_ticker_map,
        currency_map=currency_map,
        min_observations=min_obs,
        instrument_types=instrument_types,
    )
    portfolio_returns = compute_portfolio_returns_partial(df_ret, filtered_weights)

    if portfolio_returns.empty or len(portfolio_returns) < min_obs:
        return {
            "error": "Insufficient data for backtest after filtering",
            "months_available": len(portfolio_returns),
            "excluded_tickers": excluded_tickers,
            "warnings": warnings,
        }

    try:
        benchmark_prices = fetch_monthly_close(
            benchmark_ticker,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        )
        benchmark_returns = calc_monthly_returns(benchmark_prices)
    except Exception as exc:
        return {"error": f"Could not fetch benchmark data for {benchmark_ticker}: {exc}"}

    aligned = pd.DataFrame(
        {"portfolio": portfolio_returns, "benchmark": benchmark_returns}
    ).dropna()
    if aligned.empty:
        return {"error": f"No overlapping data between portfolio and {benchmark_ticker}"}

    port_ret = aligned["portfolio"]
    bench_ret = aligned["benchmark"]

    resolved_risk_free_rate = _get_risk_free_rate(risk_free_rate, start_date, end_date)

    # Keep all required args explicit and pass CAPM gate override for short windows.
    performance_metrics = compute_performance_metrics(
        portfolio_returns=port_ret,
        benchmark_returns=bench_ret,
        risk_free_rate=resolved_risk_free_rate,
        benchmark_ticker=benchmark_ticker,
        start_date=start_date,
        end_date=end_date,
        min_capm_observations=min_capm_obs,
    )

    # Attribution analysis — same pattern as calculate_portfolio_performance_metrics()
    try:
        performance_metrics["security_attribution"] = _compute_security_attribution(
            df_ret=df_ret, weights=filtered_weights,
        )
    except Exception:
        performance_metrics["security_attribution"] = []

    try:
        performance_metrics["sector_attribution"] = _compute_sector_attribution(
            df_ret=df_ret, weights=filtered_weights, fmp_ticker_map=fmp_ticker_map,
        )
    except Exception:
        performance_metrics["sector_attribution"] = []

    try:
        performance_metrics["factor_attribution"] = _compute_factor_attribution(
            port_ret=port_ret, start_date=start_date, end_date=end_date,
            fmp_ticker_map=fmp_ticker_map,
        )
    except Exception:
        performance_metrics["factor_attribution"] = []

    combined_warnings = list(performance_metrics.get("warnings", []))
    full_returns = compute_portfolio_returns(df_ret, filtered_weights)
    if len(portfolio_returns) > len(full_returns):
        months_gained = len(portfolio_returns) - len(full_returns)
        combined_warnings.append(
            f"Extended return history by {months_gained} months using partial ticker data. "
            f"Months where not all tickers had data use reweighted available-ticker exposures."
        )
    combined_warnings.extend(warnings)

    cumulative_returns = (1.0 + port_ret).cumprod()
    benchmark_cumulative = (1.0 + bench_ret).cumprod()

    if excluded_tickers:
        performance_metrics["excluded_tickers"] = excluded_tickers
        performance_metrics[
            "analysis_notes"
        ] = f"Backtest completed with {len(excluded_tickers)} ticker(s) excluded due to insufficient data"
    if combined_warnings:
        performance_metrics["warnings"] = combined_warnings

    return {
        "performance_metrics": performance_metrics,
        "monthly_returns": _series_to_month_dict(port_ret),
        "benchmark_monthly_returns": _series_to_month_dict(bench_ret),
        "cumulative_returns": _series_to_month_dict(cumulative_returns),
        "benchmark_cumulative": _series_to_month_dict(benchmark_cumulative),
        "annual_breakdown": _build_annual_breakdown(port_ret, bench_ret),
        "weights": filtered_weights,
        "benchmark_ticker": benchmark_ticker,
        "excluded_tickers": excluded_tickers,
        "warnings": combined_warnings,
    }

