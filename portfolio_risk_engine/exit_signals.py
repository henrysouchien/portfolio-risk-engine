"""Exit signal evaluation engine.

Pure functions that evaluate exit rules on pre-computed return data.
Each signal function returns a SignalResult with triggered status,
severity, and recommended action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class SignalResult:
    """Standardized result from a signal evaluation.

    Attributes:
        rule_name: Identifier for the rule (e.g., "momentum_exit")
        triggered: Whether the signal fired
        severity: 0.0-1.0, how strongly the signal fired (0 = barely, 1 = extreme)
        recommended_action: Human-readable action (e.g., "SELL 75 shares")
        metadata: Rule-specific details (thresholds, values, etc.)
    """
    rule_name: str
    triggered: bool
    severity: float = 0.0
    recommended_action: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def momentum_exit_signal(
    returns: pd.Series,
    lookback: int = 3,
) -> SignalResult:
    """Evaluate momentum exit rule: current month return vs trailing N-month average.

    Rule: EXIT if monthly_return < avg(monthly_return[t-1], ..., monthly_return[t-lookback])

    Args:
        returns: Monthly return series (decimal), chronologically sorted,
                 index = month-end dates. Must have at least lookback+1 observations.
        lookback: Number of trailing months for the average (default 3).

    Returns:
        SignalResult with:
            triggered: True if current return < trailing average
            severity: Normalized gap (how far below the average)
            metadata: current_return, trailing_avg, gap, lookback,
                      monthly_returns (last lookback+1 values for display)
    """
    if len(returns) < lookback + 1:
        return SignalResult(
            rule_name="momentum_exit",
            triggered=False,
            recommended_action="Insufficient data",
            metadata={"error": f"Need {lookback + 1} months, have {len(returns)}"},
        )

    current_return = returns.iloc[-1]
    trailing_returns = returns.iloc[-(lookback + 1):-1]
    trailing_avg = trailing_returns.mean()
    gap = current_return - trailing_avg

    triggered = bool(current_return < trailing_avg)

    # Severity: how far below the average as a fraction of trailing volatility
    # 0.0 = at the threshold, 1.0 = very far below
    if triggered and float(trailing_returns.std()) > 0:
        severity = float(min(abs(gap) / trailing_returns.std(), 1.0))
    elif triggered:
        severity = 0.5  # Default if no spread in trailing returns
    else:
        severity = 0.0

    # Format monthly returns for display
    display_returns = {}
    for date, ret in returns.iloc[-(lookback + 1):].items():
        display_returns[date.strftime("%Y-%m")] = round(float(ret) * 100, 2)

    return SignalResult(
        rule_name="momentum_exit",
        triggered=triggered,
        severity=round(severity, 3),
        recommended_action="EXIT — momentum fading" if triggered else "HOLD — momentum intact",
        metadata={
            "current_month": returns.index[-1].strftime("%Y-%m"),
            "current_return_pct": round(float(current_return) * 100, 2),
            "trailing_avg_pct": round(float(trailing_avg) * 100, 2),
            "gap_pct": round(float(gap) * 100, 2),
            "lookback": lookback,
            "monthly_returns": display_returns,
        },
    )


def regime_check_signal(
    returns_panel: pd.DataFrame,
    period: int = 3,
) -> SignalResult:
    """Evaluate portfolio regime check: equal-weight rolling return over N months.

    Rule: UNFAVORABLE if equal-weight portfolio return over trailing N months < 0

    Method: Monthly-rebalanced equal-weight portfolio. Each month, compute
    the equal-weight average return across tickers, then compound those
    monthly portfolio returns over the period. This matches a monthly-
    rebalanced equal-weight portfolio construction.

    Args:
        returns_panel: DataFrame with columns = tickers (e.g., SLV, GLD, TLT),
                       index = month-end dates, values = monthly returns (decimal).
                       Must have at least `period` rows.
        period: Rolling window in months (default 3).

    Returns:
        SignalResult with:
            triggered: True if portfolio return < 0
            metadata: portfolio_return, per_ticker_returns, period
    """
    if len(returns_panel) < period:
        return SignalResult(
            rule_name="regime_check",
            triggered=False,
            recommended_action="Insufficient data",
            metadata={"error": f"Need {period} months, have {len(returns_panel)}"},
        )

    tail = returns_panel.iloc[-period:]

    # Monthly-rebalanced equal-weight: average return across tickers each month
    monthly_portfolio_returns = tail.mean(axis=1)  # Equal-weight each month

    # Compound monthly portfolio returns over the period
    portfolio_return = float((1 + monthly_portfolio_returns).prod() - 1)

    # Per-ticker total return for display
    per_ticker = {}
    for col in tail.columns:
        total = float((1 + tail[col]).prod() - 1)
        per_ticker[col] = round(total * 100, 2)

    triggered = bool(portfolio_return < 0)

    return SignalResult(
        rule_name="regime_check",
        triggered=triggered,
        severity=round(min(abs(portfolio_return) * 10, 1.0), 3) if triggered else 0.0,
        recommended_action=(
            "REGIME UNFAVORABLE — portfolio return negative"
            if triggered
            else "REGIME SUPPORTIVE — portfolio return positive"
        ),
        metadata={
            "portfolio_return_pct": round(portfolio_return * 100, 2),
            "per_ticker_returns_pct": per_ticker,
            "period_months": period,
            "start_month": tail.index[0].strftime("%Y-%m"),
            "end_month": tail.index[-1].strftime("%Y-%m"),
        },
    )


def determine_sell_quantity(
    signal: SignalResult,
    total_shares: int,
    min_pct: float = 0.50,
    max_pct: float = 0.75,
    gap_threshold_pct: float = 5.0,
) -> Dict[str, Any]:
    """Determine sell quantity based on gap between current return and trailing avg.

    Sizing logic from spec (SLV_MOMENTUM_EXIT_SPEC.md lines 126-128):
        - Gap <= gap_threshold_pct (within 5% of trailing avg) → sell min_pct
        - Gap > gap_threshold_pct (>5% gap) → sell max_pct

    The gap is read from signal.metadata["gap_pct"] (absolute value, in percentage
    points). The spec's "within 5% of trailing avg" refers to percentage-point
    difference in monthly returns (e.g., if current return = 5% and trailing avg
    = 10%, gap = 5pp). This matches the spec's price-level examples:
    $87-$90 range ≈ within 5pp of trailing monthly return average.

    Args:
        signal: The momentum exit signal result (must be triggered).
                Must have metadata["gap_pct"] set by momentum_exit_signal().
        total_shares: Current number of shares held
        min_pct: Minimum sell percentage (default 50%)
        max_pct: Maximum sell percentage (default 75%)
        gap_threshold_pct: Percentage-point gap cutoff (default 5.0)

    Returns:
        Dict with sell_quantity, remaining_shares, sell_pct, reasoning
    """
    if not signal.triggered:
        return {
            "sell_quantity": 0,
            "remaining_shares": total_shares,
            "sell_pct": 0.0,
            "reasoning": "Signal not triggered — no action",
        }

    gap_pct = abs(signal.metadata.get("gap_pct", 0.0))

    if gap_pct > gap_threshold_pct:
        sell_pct = max_pct
        reasoning = (
            f"Large gap ({gap_pct:.1f}pp > {gap_threshold_pct:.0f}pp threshold). "
            f"Selling {max_pct:.0%} of position."
        )
    else:
        sell_pct = min_pct
        reasoning = (
            f"Small gap ({gap_pct:.1f}pp <= {gap_threshold_pct:.0f}pp threshold). "
            f"Selling {min_pct:.0%} of position. Momentum fading but not extreme."
        )

    sell_quantity = max(1, int(total_shares * sell_pct))  # At least 1 share
    sell_quantity = min(sell_quantity, total_shares)  # Clamp to available
    remaining = total_shares - sell_quantity

    return {
        "sell_quantity": sell_quantity,
        "remaining_shares": remaining,
        "sell_pct": sell_pct,
        "reasoning": reasoning,
    }
