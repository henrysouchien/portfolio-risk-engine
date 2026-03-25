"""Backtest interpretive flags for agent-oriented responses."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any) -> float | None:
    """Convert to finite float; return None when invalid."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def generate_backtest_flags(snapshot: dict) -> list[dict]:
    """Generate actionable flags from BacktestResult agent snapshot."""
    if not isinstance(snapshot, dict):
        return []

    flags: list[dict] = []
    period = snapshot.get("period", {}) or {}
    returns = snapshot.get("returns", {}) or {}
    risk = snapshot.get("risk", {}) or {}
    data_quality = snapshot.get("data_quality", {}) or {}
    benchmark = snapshot.get("benchmark", {}) or {}

    excluded_tickers = list(data_quality.get("excluded_tickers") or [])
    excluded_count = int(data_quality.get("excluded_count", len(excluded_tickers)))
    period_months = _to_float(period.get("months"))
    max_drawdown = _to_float(risk.get("max_drawdown_pct"))
    excess_return = _to_float(returns.get("excess_return_pct"))
    sharpe_ratio = _to_float(risk.get("sharpe_ratio"))
    volatility = _to_float(snapshot.get("volatility"))
    down_capture_ratio = _to_float(snapshot.get("down_capture_ratio"))
    annual_alpha_positive_count = _to_float(snapshot.get("annual_alpha_positive_count"))
    annual_alpha_total = _to_float(snapshot.get("annual_alpha_total"))
    benchmark_ticker = benchmark.get("ticker", "benchmark")

    if excluded_count > 0:
        preview = ", ".join(excluded_tickers[:5])
        suffix = "..." if excluded_count > 5 else ""
        flags.append(
            {
                "type": "excluded_tickers",
                "severity": "warning",
                "message": (
                    f"{excluded_count} ticker(s) excluded due to insufficient history"
                    + (f": {preview}{suffix}" if preview else "")
                ),
                "excluded_tickers": excluded_tickers,
            }
        )

    if period_months is not None and period_months < 12:
        flags.append(
            {
                "type": "short_backtest_window",
                "severity": "warning",
                "message": "Short backtest period (< 12 months) - metrics may be unreliable",
                "months": int(period_months),
            }
        )

    if max_drawdown is not None and max_drawdown <= -30.0:
        flags.append(
            {
                "type": "deep_drawdown",
                "severity": "warning",
                "message": f"Max drawdown exceeds -30% ({max_drawdown:.1f}%)",
                "max_drawdown_pct": round(max_drawdown, 2),
            }
        )

    if volatility is not None and volatility > 30.0:
        flags.append(
            {
                "type": "high_volatility",
                "severity": "warning",
                "message": f"Annualized volatility is elevated at {volatility:.1f}%",
                "volatility": round(volatility, 2),
            }
        )

    if down_capture_ratio is not None and down_capture_ratio > 1.1:
        flags.append(
            {
                "type": "strong_down_capture",
                "severity": "warning",
                "message": (
                    f"Down capture ratio of {down_capture_ratio:.2f} suggests the portfolio amplifies benchmark losses"
                ),
                "down_capture_ratio": round(down_capture_ratio, 3),
            }
        )

    if excess_return is not None:
        verb = "outperformed" if excess_return >= 0 else "underperformed"
        flags.append(
            {
                "type": "benchmark_relative",
                "severity": "info",
                "message": (
                    f"Portfolio {verb} {benchmark_ticker} by {abs(excess_return):.2f}% total return"
                ),
                "excess_return_pct": round(excess_return, 2),
            }
        )

    if (
        annual_alpha_positive_count is not None
        and annual_alpha_total is not None
        and annual_alpha_total > 0
        and annual_alpha_positive_count > (annual_alpha_total / 2.0)
    ):
        positive_years = int(annual_alpha_positive_count)
        total_years = int(annual_alpha_total)
        flags.append(
            {
                "type": "annual_consistency",
                "severity": "info",
                "message": f"Positive alpha in {positive_years} of {total_years} years",
                "annual_alpha_positive_count": positive_years,
                "annual_alpha_total": total_years,
            }
        )

    if sharpe_ratio is not None and sharpe_ratio > 1.0:
        flags.append(
            {
                "type": "positive_risk_adjusted_returns",
                "severity": "success",
                "message": f"Positive risk-adjusted returns (Sharpe {sharpe_ratio:.2f})",
                "sharpe_ratio": round(sharpe_ratio, 3),
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags
