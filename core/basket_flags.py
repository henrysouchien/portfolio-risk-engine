"""Basket-level interpretive flags for agent-oriented responses."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any) -> float | None:
    """Convert to finite float; return None for missing/invalid values."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def generate_basket_flags(snapshot: dict) -> list[dict]:
    """Generate actionable flags from a basket analysis snapshot."""
    flags: list[dict] = []
    performance = snapshot.get("performance", {}) if isinstance(snapshot, dict) else {}
    components = snapshot.get("components", {}) if isinstance(snapshot, dict) else {}
    portfolio = snapshot.get("portfolio", {}) if isinstance(snapshot, dict) else {}
    data_coverage = snapshot.get("data_coverage", {}) if isinstance(snapshot, dict) else {}

    annualized_return = _to_float(performance.get("annualized_return_pct"))
    sharpe_ratio = _to_float(performance.get("sharpe_ratio"))
    max_drawdown = _to_float(performance.get("max_drawdown_pct"))
    volatility = _to_float(performance.get("volatility_pct"))
    max_weight_pct = _to_float(components.get("max_weight_pct"))
    correlation = _to_float(portfolio.get("correlation"))

    excluded = data_coverage.get("excluded_tickers")
    excluded_tickers = list(excluded) if isinstance(excluded, list) else []

    if max_weight_pct is not None and max_weight_pct > 40:
        flags.append(
            {
                "type": "high_concentration",
                "severity": "warning",
                "message": f"Largest component weight is {max_weight_pct:.1f}% (>40%)",
                "max_weight_pct": round(max_weight_pct, 2),
            }
        )

    if annualized_return is not None and annualized_return < 0:
        flags.append(
            {
                "type": "negative_annualized_return",
                "severity": "warning",
                "message": f"Basket annualized return is negative ({annualized_return:.1f}%)",
                "annualized_return_pct": round(annualized_return, 2),
            }
        )

    if sharpe_ratio is not None and sharpe_ratio > 1.5:
        flags.append(
            {
                "type": "strong_sharpe",
                "severity": "success",
                "message": f"Sharpe ratio is {sharpe_ratio:.2f} (excellent risk-adjusted returns)",
                "sharpe_ratio": round(sharpe_ratio, 3),
            }
        )
    elif sharpe_ratio is not None and sharpe_ratio < 0:
        flags.append(
            {
                "type": "negative_sharpe",
                "severity": "warning",
                "message": f"Sharpe ratio is {sharpe_ratio:.2f} (negative risk-adjusted returns)",
                "sharpe_ratio": round(sharpe_ratio, 3),
            }
        )

    if max_drawdown is not None and abs(max_drawdown) > 20:
        flags.append(
            {
                "type": "large_drawdown",
                "severity": "warning",
                "message": f"Basket experienced a {abs(max_drawdown):.1f}% maximum drawdown",
                "max_drawdown_pct": round(max_drawdown, 2),
            }
        )

    if excluded_tickers:
        flags.append(
            {
                "type": "data_coverage_gap",
                "severity": "warning",
                "message": f"{len(excluded_tickers)} ticker(s) excluded: {', '.join(excluded_tickers)}",
                "excluded_tickers": excluded_tickers,
            }
        )

    if correlation is not None and correlation > 0.9:
        flags.append(
            {
                "type": "high_portfolio_correlation",
                "severity": "info",
                "message": f"Correlation to current portfolio is {correlation:.2f} (limited diversification)",
                "correlation": round(correlation, 3),
            }
        )
    elif correlation is not None and correlation < 0.3:
        flags.append(
            {
                "type": "diversifying",
                "severity": "success",
                "message": f"Correlation to current portfolio is {correlation:.2f} (good diversification)",
                "correlation": round(correlation, 3),
            }
        )

    if volatility is not None and volatility > 30:
        flags.append(
            {
                "type": "high_volatility",
                "severity": "warning",
                "message": f"Basket volatility is {volatility:.1f}% (>30%)",
                "volatility_pct": round(volatility, 2),
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags
