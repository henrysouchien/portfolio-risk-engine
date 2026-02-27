# SLV Momentum Exit — Implementation Plan

**Created:** 2026-02-10
**Status:** COMPLETE — implemented and tested (19/19 tests passing)
**Spec:** `docs/planning/SLV_MOMENTUM_EXIT_SPEC.md`
**Workflow:** `docs/planning/AUTONOMOUS_WORKFLOW.md`

---

## Overview

Build a reusable exit-signal system in the risk_module, with the SLV momentum exit as the first use case. The system has three layers:

1. **Signal engine** (`core/exit_signals.py`) — pure functions that evaluate exit rules
2. **MCP tool** (`mcp_tools/signals.py`) — `check_exit_signals` tool that fetches data, runs signals, and returns actionable results
3. **Orchestration by Claude** — Claude reads signal results, then uses existing `preview_trade` → `execute_trade` tools to act

Trade execution infrastructure already exists and does not need modification.

---

## Architecture

```
Claude invokes check_exit_signals(ticker="SLV")
    ↓
mcp_tools/signals.py
    ├─ Fetch monthly prices via data_loader.fetch_monthly_total_return_price()
    ├─ Compute monthly returns via factor_utils.calc_monthly_returns()
    ├─ Load rule config for ticker
    ├─ Evaluate each rule via core/exit_signals.py
    └─ Return SignalCheckResult (all signals + position context + recommended actions)
    ↓
Claude reads result, decides action:
    ├─ No signal → report status, no action
    ├─ Signal triggered → preview_trade(ticker="SLV", quantity=X, side="SELL", ...)
    ├─ User confirms → execute_trade(preview_id)
    ├─ Place stop on remainder → preview_trade(ticker="SLV", ..., order_type="Stop", stop_price=65.0, time_in_force="GTC")
    └─ Update Notion position
```

**Why Claude is the orchestration layer:** Each execution step requires user confirmation. Claude already mediates between MCP tools and the user. Building a separate orchestration service would duplicate this and remove the human-in-the-loop. Claude calls `check_exit_signals`, presents results, then chains `preview_trade` → `execute_trade` as needed.

---

## Files to Create

### 1. `core/exit_signals.py` — Signal Engine (~150 lines)

Pure functions that evaluate exit rules. No I/O, no FMP calls — takes pre-computed data as input.

```python
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

    triggered = current_return < trailing_avg

    # Severity: how far below the average as a fraction of trailing volatility
    # 0.0 = at the threshold, 1.0 = very far below
    if triggered and trailing_returns.std() > 0:
        severity = min(abs(gap) / trailing_returns.std(), 1.0)
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

    triggered = portfolio_return < 0

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
```

**Key design decisions:**
- `SignalResult` is a simple dataclass, not in `result_objects.py` — it's lightweight and specific to exit signals. Keeps `result_objects.py` focused on portfolio analysis results.
- `momentum_exit_signal()` and `regime_check_signal()` are pure functions: given returns data, return a result. No FMP calls, no I/O.
- `determine_sell_quantity()` is also pure: given a signal + position size, return sell quantity. Parameterized for reuse.
- Severity is normalized 0-1 using trailing volatility as denominator (for momentum) or absolute magnitude (for regime).

### 2. `mcp_tools/signals.py` — MCP Tool (~250 lines)

MCP tool that orchestrates data fetching + signal evaluation.

```python
"""Exit signal evaluation MCP tool.

Fetches price data, evaluates configured exit rules, and returns
actionable results with position context and trade recommendations.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import pandas as pd

from core.exit_signals import (
    SignalResult,
    determine_sell_quantity,
    momentum_exit_signal,
    regime_check_signal,
)
from data_loader import fetch_monthly_total_return_price
from factor_utils import calc_monthly_returns
from services.position_service import PositionService
from settings import get_default_user
from utils.date_utils import last_month_end
from utils.logging import portfolio_logger


# ── Exit rule configurations ──────────────────────────────────────
# Per-ticker rule configurations. Each entry specifies which rules
# to evaluate and their parameters. This is the "config entry" from
# the spec's architecture note.
#
# To add a new position's exit rules:
# 1. Write a new signal function in core/exit_signals.py (if needed)
# 2. Add a dispatch case in _evaluate_rule()
# 3. Add a config entry below

EXIT_RULE_CONFIGS = {
    "SLV": {
        "rules": [
            {
                "name": "momentum_exit",
                "params": {"lookback": 3},
                "is_primary": True,
            },
            {
                "name": "regime_check",
                "params": {"tickers": ["SLV", "GLD", "TLT"], "period": 3},
                "is_primary": False,
            },
        ],
        "sizing": {
            "min_pct": 0.50,
            "max_pct": 0.75,
            "gap_threshold_pct": 5.0,
        },
        "stop_loss": {
            "price": 65.0,
            "time_in_force": "GTC",
        },
    },
}


def _fetch_returns(ticker: str, months_needed: int) -> pd.Series:
    """Fetch monthly returns for a ticker with sufficient history.

    Uses last_month_end() to anchor evaluation to completed months only.
    This prevents partial-month returns from triggering false exits.

    Args:
        ticker: Stock ticker
        months_needed: Minimum months of return data required

    Returns:
        pd.Series of monthly returns (decimal), chronologically sorted,
        ending at last completed month-end.
    """
    from dateutil.relativedelta import relativedelta

    # Anchor to last completed month-end (prevents partial-month false triggers)
    end_date = last_month_end()

    # Go back months_needed + buffer for month-end alignment + pct_change drop
    buffer_months = 3
    total_months = months_needed + buffer_months
    start_dt = datetime.strptime(end_date, "%Y-%m-%d") - relativedelta(months=total_months + 1)
    start_date = start_dt.strftime("%Y-%m-%d")

    prices = fetch_monthly_total_return_price(ticker, start_date=start_date, end_date=end_date)
    returns = calc_monthly_returns(prices)
    return returns


def _fetch_returns_panel(tickers: List[str], months_needed: int) -> pd.DataFrame:
    """Fetch aligned monthly returns panel for multiple tickers.

    All tickers must be fetched successfully. If any ticker fails, raises
    ValueError with the list of missing tickers (regime check requires
    the full basket — partial data would change signal semantics).

    Returns:
        pd.DataFrame with columns = tickers, index = month-end dates

    Raises:
        ValueError: If any ticker fails to fetch
    """
    all_returns = {}
    failed_tickers = []
    for t in tickers:
        try:
            all_returns[t] = _fetch_returns(t, months_needed)
        except Exception as e:
            portfolio_logger.warning(f"Failed to fetch returns for {t}: {e}")
            failed_tickers.append(t)

    if failed_tickers:
        raise ValueError(
            f"Regime check requires all tickers. Missing: {failed_tickers}"
        )

    panel = pd.DataFrame(all_returns)
    panel = panel.dropna()  # Align to common dates
    return panel


def _get_position_context(
    ticker: str,
    user_email: Optional[str] = None,
    shares_override: Optional[int] = None,
    account_id_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Get current position info for a ticker.

    Attempts lookup via PositionService (covers Plaid + SnapTrade providers).
    If the position is in IBKR (not covered by PositionService), the caller
    should pass shares_override and account_id_override.

    Returns dict with shares, current_price, cost_basis, value, etc.
    """
    # If overrides provided, use them directly (IBKR positions)
    if shares_override is not None:
        return {
            "ticker": ticker,
            "shares": shares_override,
            "account_id": account_id_override,
            "position_source": "user_provided",
        }

    try:
        email = user_email or get_default_user()
        if not email:
            return {"ticker": ticker, "shares": 0, "error": "No user email configured"}

        svc = PositionService(user_email=email)
        result = svc.get_all_positions(use_cache=True, consolidate=False)

        # Collect all matching positions (may span multiple accounts)
        matches = [
            pos for pos in result.data.positions
            if pos.get("ticker") == ticker or pos.get("symbol") == ticker
        ]

        if not matches:
            return {
                "ticker": ticker,
                "shares": 0,
                "error": "Position not found in Plaid/SnapTrade. Use shares param for IBKR positions.",
            }

        if len(matches) == 1:
            pos = matches[0]
            return {
                "ticker": ticker,
                "shares": abs(pos.get("quantity", 0)),
                "current_price": pos.get("price", 0),
                "cost_basis": pos.get("cost_basis", 0),
                "value": pos.get("value", 0),
                "currency": pos.get("currency", "USD"),
                "account_id": pos.get("account_id"),
                "account_name": pos.get("account_name"),
                "position_source": pos.get("position_source"),
            }

        # Multiple accounts hold this ticker — require explicit account_id
        accounts = [
            {"account_id": p.get("account_id"), "shares": abs(p.get("quantity", 0)),
             "position_source": p.get("position_source")}
            for p in matches
        ]
        return {
            "ticker": ticker,
            "shares": 0,
            "error": f"Multiple accounts hold {ticker}. Pass account_id to disambiguate.",
            "accounts": accounts,
        }
    except Exception as e:
        portfolio_logger.warning(f"Failed to get position for {ticker}: {e}")
        return {"ticker": ticker, "shares": 0, "error": str(e)}


def _evaluate_rule(
    rule_config: Dict[str, Any],
    ticker: str,
) -> SignalResult:
    """Evaluate a single rule for a ticker.

    Dispatches to the appropriate signal function based on rule name.
    To add a new rule: add a new elif branch here + signal function in
    core/exit_signals.py + config entry in EXIT_RULE_CONFIGS.
    """
    name = rule_config["name"]
    params = rule_config.get("params", {})

    if name == "momentum_exit":
        lookback = params.get("lookback", 3)
        returns = _fetch_returns(ticker, months_needed=lookback + 1)
        return momentum_exit_signal(returns, lookback=lookback)

    elif name == "regime_check":
        tickers = params.get("tickers", [ticker, "GLD", "TLT"])
        period = params.get("period", 3)
        panel = _fetch_returns_panel(tickers, months_needed=period)
        return regime_check_signal(panel, period=period)

    else:
        return SignalResult(
            rule_name=name,
            triggered=False,
            recommended_action=f"Unknown rule: {name}",
            metadata={"error": f"Rule '{name}' not found"},
        )


def check_exit_signals(
    ticker: str,
    shares: Optional[int] = None,
    account_id: Optional[str] = None,
    user_email: Optional[str] = None,
    format: Literal["summary", "full"] = "summary",
) -> dict:
    """Evaluate exit signals for a position.

    Checks all configured exit rules for the given ticker and returns
    signal results with position context and trade recommendations.

    Args:
        ticker: Stock ticker to evaluate (e.g., "SLV")
        shares: Override share count (use for IBKR positions not in PositionService)
        account_id: Override account ID (use for IBKR positions)
        user_email: Optional user email for position lookup
        format: "summary" (default) or "full" (includes rule config)

    Returns:
        Dict with status, signals, position, and recommended_actions.

    Examples:
        # Check SLV exit signals (IBKR position — pass shares explicitly)
        check_exit_signals(ticker="SLV", shares=100)

        # Response includes:
        # - Each signal's triggered/severity status
        # - Current position details (shares, cost basis, P&L)
        # - Recommended sell quantity if signal triggered
        # - Stop loss parameters for remaining shares
    """
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        return _check_exit_signals_impl(ticker, shares, account_id, user_email, format)
    except Exception as e:
        portfolio_logger.error(f"check_exit_signals failed for {ticker}: {e}")
        return {"status": "error", "error": str(e), "ticker": ticker}
    finally:
        sys.stdout = _saved


def _check_exit_signals_impl(
    ticker: str,
    shares: Optional[int],
    account_id: Optional[str],
    user_email: Optional[str],
    format: str,
) -> dict:
    """Implementation of check_exit_signals."""
    ticker = ticker.upper()

    # Load config for this ticker
    config = EXIT_RULE_CONFIGS.get(ticker)
    if not config:
        return {
            "status": "error",
            "error": f"No exit rules configured for {ticker}",
            "available_tickers": list(EXIT_RULE_CONFIGS.keys()),
        }

    # Get position context (with overrides for IBKR)
    position = _get_position_context(
        ticker, user_email,
        shares_override=shares,
        account_id_override=account_id,
    )

    # Evaluate each rule
    signals = []
    primary_signal = None
    primary_errored = False
    for rule_config in config["rules"]:
        try:
            result = _evaluate_rule(rule_config, ticker)
            signal_dict = {
                "rule_name": result.rule_name,
                "triggered": result.triggered,
                "severity": result.severity,
                "recommended_action": result.recommended_action,
                "is_primary": rule_config.get("is_primary", False),
                "status": "ok",
                "metadata": result.metadata,
            }
            signals.append(signal_dict)
            if rule_config.get("is_primary") and result.triggered:
                primary_signal = result
        except Exception as e:
            portfolio_logger.error(f"Error evaluating rule {rule_config['name']}: {e}")
            is_primary = rule_config.get("is_primary", False)
            if is_primary:
                primary_errored = True
            signals.append({
                "rule_name": rule_config["name"],
                "triggered": False,
                "severity": 0.0,
                "recommended_action": f"Error: {e}",
                "is_primary": is_primary,
                "status": "error",
                "metadata": {"error": str(e)},
            })

    # Determine recommended actions
    recommended_actions = []
    sizing = None

    if primary_signal and primary_signal.triggered:
        pos_shares = position.get("shares", 0)
        pos_account = position.get("account_id")
        if pos_shares > 0:
            sizing_config = config.get("sizing", {})
            sizing = determine_sell_quantity(
                primary_signal,
                total_shares=int(pos_shares),
                min_pct=sizing_config.get("min_pct", 0.50),
                max_pct=sizing_config.get("max_pct", 0.75),
                gap_threshold_pct=sizing_config.get("gap_threshold_pct", 5.0),
            )
            sell_action = {
                "step": 1,
                "action": "SELL",
                "ticker": ticker,
                "quantity": sizing["sell_quantity"],
                "order_type": "Market",
                "reasoning": sizing["reasoning"],
            }
            if pos_account:
                sell_action["account_id"] = pos_account
            recommended_actions.append(sell_action)

            # Stop loss on remainder
            stop_config = config.get("stop_loss", {})
            if stop_config and sizing["remaining_shares"] > 0:
                stop_action = {
                    "step": 2,
                    "action": "PLACE_STOP",
                    "ticker": ticker,
                    "quantity": sizing["remaining_shares"],
                    "order_type": "Stop",
                    "stop_price": stop_config.get("price"),
                    "time_in_force": stop_config.get("time_in_force", "GTC"),
                    "reasoning": f"Hard stop at ${stop_config.get('price')} on remaining {sizing['remaining_shares']} shares",
                }
                if pos_account:
                    stop_action["account_id"] = pos_account
                recommended_actions.append(stop_action)

    # Composite assessment — account for rule errors
    ok_signals = [s for s in signals if s["status"] == "ok"]
    errored_signals = [s for s in signals if s["status"] == "error"]
    any_triggered = any(s["triggered"] for s in ok_signals)
    all_ok_triggered = ok_signals and all(s["triggered"] for s in ok_signals)

    if primary_errored:
        overall = "ERROR — primary rule failed, cannot determine exit status"
    elif all_ok_triggered and not errored_signals:
        overall = "STRONG EXIT — both momentum and regime signals triggered"
    elif primary_signal and primary_signal.triggered:
        if errored_signals:
            secondary_names = [s["rule_name"] for s in errored_signals]
            overall = f"EXIT — primary momentum signal triggered ({', '.join(secondary_names)} errored, status unknown)"
        else:
            overall = "EXIT — primary momentum signal triggered (regime still supportive)"
    elif any_triggered:
        overall = "MONITOR — secondary signal triggered, primary holds"
    else:
        overall = "HOLD — no signals triggered"

    # Month completeness check
    eval_month_end = last_month_end()

    # trade_eligible only if primary rule evaluated successfully
    trade_eligible = not primary_errored and primary_signal is not None

    result = {
        "status": "success",
        "ticker": ticker,
        "overall_assessment": overall,
        "signals": signals,
        "position": position,
        "recommended_actions": recommended_actions,
        "evaluated_at": datetime.now().isoformat(),
        "evaluation_month_end": eval_month_end,
        "trade_eligible": trade_eligible,
    }

    if sizing:
        result["sizing"] = sizing

    if format == "full":
        result["config"] = {
            "rules": config["rules"],
            "sizing": config.get("sizing"),
            "stop_loss": config.get("stop_loss"),
        }

    return result
```

**Key design decisions:**
- `EXIT_RULE_CONFIGS` is a Python dict, not YAML — simple, version-controlled, no file I/O. Can be moved to YAML/DB later if needed.
- Rule dispatch is in `_evaluate_rule()` — each rule name maps to a signal function + its data fetching. Adding a new rule means: write signal function in `core/exit_signals.py`, add dispatch case in `_evaluate_rule()`, add config entry.
- **IBKR position support:** `shares` and `account_id` are optional params. SLV is in IBKR which isn't covered by PositionService (Plaid/SnapTrade only). User passes `shares=100` explicitly.
- **Partial-month gating:** `_fetch_returns()` uses `last_month_end()` as end_date, so returns always end at the last completed month. No partial-month false triggers.
- **Regime ticker strictness:** `_fetch_returns_panel()` raises if any configured ticker fails (partial basket would change signal semantics).
- **Error handling:** Outer `check_exit_signals()` wraps impl in try/except, always returns `{"status": "error"}` on failure.
- `recommended_actions` includes `account_id` when available.

### 3. `mcp_server.py` — Registration (add ~15 lines)

Add the new tool to the portfolio-mcp server:

```python
# In the tool registration section of mcp_server.py:

from mcp_tools.signals import check_exit_signals as _check_exit_signals_impl

@mcp.tool()
def check_exit_signals(
    ticker: str,
    shares: Optional[int] = None,
    account_id: Optional[str] = None,
    format: Literal["summary", "full"] = "summary",
) -> dict:
    """Evaluate exit signals for a position.

    Checks configured exit rules (momentum, regime) and returns signal status,
    position context, and recommended trade actions.

    Args:
        ticker: Stock ticker to evaluate (e.g., "SLV")
        shares: Override share count (use for IBKR positions not auto-detected)
        account_id: Override account ID (use for IBKR positions)
        format: "summary" (default) or "full" (includes rule config)

    Returns:
        Signal results with overall assessment, per-rule details,
        position info, and recommended sell quantities.

    Examples:
        check_exit_signals(ticker="SLV", shares=100)
        check_exit_signals(ticker="SLV", shares=100, format="full")
    """
    return _check_exit_signals_impl(
        ticker=ticker, shares=shares, account_id=account_id, format=format
    )
```

### 4. Tests — `tests/core/test_exit_signals.py` (~150 lines)

Unit tests for the pure signal functions.

```python
"""Tests for core/exit_signals.py signal evaluation functions."""

import pandas as pd
import numpy as np
import pytest
from core.exit_signals import (
    SignalResult,
    momentum_exit_signal,
    regime_check_signal,
    determine_sell_quantity,
)


class TestMomentumExitSignal:
    """Tests for momentum_exit_signal()."""

    def _make_returns(self, values: list) -> pd.Series:
        """Helper: create monthly return series from values."""
        dates = pd.date_range("2025-09-30", periods=len(values), freq="ME")
        return pd.Series(values, index=dates)

    def test_triggered_when_current_below_trailing_avg(self):
        # trailing avg of [0.10, 0.08, 0.12] = 0.10
        # current = 0.05 < 0.10 → triggered
        returns = self._make_returns([0.10, 0.08, 0.12, 0.05])
        result = momentum_exit_signal(returns, lookback=3)
        assert result.triggered is True
        assert result.rule_name == "momentum_exit"
        assert result.severity > 0

    def test_not_triggered_when_current_above_trailing_avg(self):
        # trailing avg of [0.05, 0.06, 0.04] = 0.05
        # current = 0.10 > 0.05 → not triggered
        returns = self._make_returns([0.05, 0.06, 0.04, 0.10])
        result = momentum_exit_signal(returns, lookback=3)
        assert result.triggered is False
        assert result.severity == 0.0

    def test_not_triggered_when_current_equals_trailing_avg(self):
        # Edge: exact match → not triggered (< is strict)
        returns = self._make_returns([0.05, 0.05, 0.05, 0.05])
        result = momentum_exit_signal(returns, lookback=3)
        assert result.triggered is False

    def test_insufficient_data(self):
        returns = self._make_returns([0.05, 0.10])
        result = momentum_exit_signal(returns, lookback=3)
        assert result.triggered is False
        assert "error" in result.metadata

    def test_negative_returns(self):
        # All negative but current is worse → triggered
        returns = self._make_returns([-0.02, -0.01, -0.03, -0.10])
        result = momentum_exit_signal(returns, lookback=3)
        assert result.triggered is True

    def test_metadata_contains_expected_fields(self):
        returns = self._make_returns([0.10, 0.08, 0.12, 0.05])
        result = momentum_exit_signal(returns, lookback=3)
        assert "current_return_pct" in result.metadata
        assert "trailing_avg_pct" in result.metadata
        assert "gap_pct" in result.metadata
        assert "monthly_returns" in result.metadata

    def test_severity_bounded_zero_to_one(self):
        # Extreme case: huge gap
        returns = self._make_returns([0.10, 0.10, 0.10, -0.50])
        result = momentum_exit_signal(returns, lookback=3)
        assert 0.0 <= result.severity <= 1.0

    def test_custom_lookback(self):
        returns = self._make_returns([0.05, 0.06, 0.04, 0.08, 0.10, 0.02])
        result = momentum_exit_signal(returns, lookback=5)
        assert result.metadata["lookback"] == 5


class TestRegimeCheckSignal:
    """Tests for regime_check_signal()."""

    def _make_panel(self, data: dict, n_months: int) -> pd.DataFrame:
        """Helper: create returns panel."""
        dates = pd.date_range("2025-09-30", periods=n_months, freq="ME")
        return pd.DataFrame(data, index=dates)

    def test_triggered_when_portfolio_negative(self):
        panel = self._make_panel({
            "SLV": [-0.05, -0.10, -0.03],
            "GLD": [-0.02, -0.04, -0.01],
            "TLT": [-0.03, -0.05, -0.02],
        }, 3)
        result = regime_check_signal(panel, period=3)
        assert result.triggered is True

    def test_not_triggered_when_portfolio_positive(self):
        panel = self._make_panel({
            "SLV": [0.05, 0.10, 0.08],
            "GLD": [0.02, 0.04, 0.03],
            "TLT": [0.01, 0.02, 0.01],
        }, 3)
        result = regime_check_signal(panel, period=3)
        assert result.triggered is False

    def test_mixed_tickers_but_overall_negative(self):
        # SLV positive, but GLD and TLT negative enough to drag portfolio down
        panel = self._make_panel({
            "SLV": [0.05, 0.10, 0.08],
            "GLD": [-0.15, -0.20, -0.10],
            "TLT": [-0.10, -0.15, -0.08],
        }, 3)
        result = regime_check_signal(panel, period=3)
        assert result.triggered is True

    def test_insufficient_data(self):
        panel = self._make_panel({"SLV": [0.05], "GLD": [0.02]}, 1)
        result = regime_check_signal(panel, period=3)
        assert result.triggered is False
        assert "error" in result.metadata

    def test_metadata_contains_per_ticker_returns(self):
        panel = self._make_panel({
            "SLV": [0.05, 0.10, 0.08],
            "GLD": [0.02, 0.04, 0.03],
            "TLT": [0.01, 0.02, 0.01],
        }, 3)
        result = regime_check_signal(panel, period=3)
        assert "per_ticker_returns_pct" in result.metadata
        assert "SLV" in result.metadata["per_ticker_returns_pct"]


class TestDetermineSellQuantity:
    """Tests for determine_sell_quantity()."""

    def test_small_gap_sells_min_pct(self):
        # gap_pct = 3.0 <= 5.0 threshold → min_pct (50%)
        signal = SignalResult(
            "momentum_exit", triggered=True, severity=0.3,
            metadata={"gap_pct": -3.0},
        )
        result = determine_sell_quantity(signal, total_shares=100)
        assert result["sell_quantity"] == 50
        assert result["remaining_shares"] == 50

    def test_large_gap_sells_max_pct(self):
        # gap_pct = 8.0 > 5.0 threshold → max_pct (75%)
        signal = SignalResult(
            "momentum_exit", triggered=True, severity=0.8,
            metadata={"gap_pct": -8.0},
        )
        result = determine_sell_quantity(signal, total_shares=100)
        assert result["sell_quantity"] == 75
        assert result["remaining_shares"] == 25

    def test_not_triggered_sells_nothing(self):
        signal = SignalResult("momentum_exit", triggered=False, severity=0.0)
        result = determine_sell_quantity(signal, total_shares=100)
        assert result["sell_quantity"] == 0
        assert result["remaining_shares"] == 100

    def test_custom_sizing_params(self):
        signal = SignalResult(
            "momentum_exit", triggered=True, severity=0.8,
            metadata={"gap_pct": -10.0},
        )
        result = determine_sell_quantity(
            signal, total_shares=200, min_pct=0.30, max_pct=0.60
        )
        assert result["sell_quantity"] == 120  # 200 * 0.60
        assert result["remaining_shares"] == 80

    def test_exact_gap_threshold(self):
        # gap_pct = 5.0 exactly at threshold → min_pct (<=)
        signal = SignalResult(
            "momentum_exit", triggered=True, severity=0.5,
            metadata={"gap_pct": -5.0},
        )
        result = determine_sell_quantity(signal, total_shares=100, gap_threshold_pct=5.0)
        assert result["sell_quantity"] == 50  # <= threshold → min_pct

    def test_minimum_one_share(self):
        # Very small holding: 1 share × 50% = 0.5 → floors to 0, but enforce min 1
        signal = SignalResult(
            "momentum_exit", triggered=True, severity=0.3,
            metadata={"gap_pct": -2.0},
        )
        result = determine_sell_quantity(signal, total_shares=1)
        assert result["sell_quantity"] == 1
        assert result["remaining_shares"] == 0
```

---

## Files Modified

### `mcp_server.py`
- Add import: `from mcp_tools.signals import check_exit_signals as _check_exit_signals_impl`
- Add `@mcp.tool()` registration for `check_exit_signals` (same pattern as other tools)

### `mcp_tools/__init__.py`
- Add `"signals"` to the module list (if it maintains one)

---

## Files NOT Modified

- **`mcp_tools/trading.py`** — No changes. Existing `preview_trade`, `execute_trade` are used as-is.
- **`services/trade_execution_service.py`** — No changes.
- **`core/result_objects.py`** — `SignalResult` lives in `core/exit_signals.py` (lightweight, domain-specific).
- **`data_loader.py`**, **`factor_utils.py`** — Used as-is for price fetching and return computation.

---

## Edge Cases & Constraints

1. **Month-end gating (partial-month prevention):** `_fetch_returns()` uses `last_month_end()` as the end_date, so returns always end at the last completed month-end. This prevents partial-month returns from producing false exit signals. The response includes `evaluation_month_end` showing which month was evaluated and `trade_eligible` (true only when primary rule evaluated successfully and triggered).

2. **Insufficient price history:** If a ticker has < lookback+1 months of data, the signal returns `triggered=False` with an error in metadata. This is safe (no false positives from bad data).

3. **FMP data gaps:** If FMP is down or returns empty data, `fetch_monthly_total_return_price()` will raise. The MCP tool catches this per-rule and reports the error without crashing.

4. **IBKR positions not in PositionService:** SLV is held in IBKR, which PositionService doesn't cover (Plaid/SnapTrade only). The `shares` and `account_id` params allow explicit position info. If neither passed nor auto-detected, signals still evaluate but `recommended_actions` will have 0 shares.

5. **Month-end alignment:** FMP prices are resampled to month-end (`ME` frequency). `calc_monthly_returns()` uses `pct_change()` on these month-end prices, which is correct.

6. **Regime check ticker strictness:** `_fetch_returns_panel()` requires ALL configured tickers (e.g., SLV, GLD, TLT). If any ticker fails to fetch, the rule returns an error rather than computing on a partial basket (which would change the signal's semantics).

7. **Scheduling:** The tool is designed for on-demand invocation by Claude, not automated scheduling. The intended cadence is: invoke on the first US business day after each month-end close. The `evaluation_month_end` field makes it clear which month was evaluated, preventing accidental double-evaluation. If automated scheduling is needed later, a cron + MCP invocation wrapper can be added.

---

## Verification Plan

1. **Core unit tests:** Run `pytest tests/core/test_exit_signals.py -v` — all signal functions are pure, fully testable without mocking.

2. **MCP tool tests:** Create `tests/mcp_tools/test_signals.py` with mocks for:
   - `fetch_monthly_total_return_price` — return synthetic price series
   - `PositionService` — return mock position data or simulate "not found"
   - Test cases:
     - Ticker with no config → error response
     - Successful evaluation with triggered signal → recommended_actions populated
     - Successful evaluation with no trigger → HOLD assessment
     - Position not found + no shares override → signals evaluate, 0 shares in sizing
     - shares override provided → uses override, no PositionService call
     - FMP failure on one regime ticker → regime check returns error, momentum still works
     - Format "full" includes config section

3. **Integration test (manual):** Run the MCP tool against live data:
   ```
   check_exit_signals(ticker="SLV", shares=100)
   ```
   Verify:
   - Returns last completed month's signal status
   - `evaluation_month_end` matches last month-end
   - Recommended actions match expected sizing logic
   - Monthly returns in metadata match FMP data

4. **Regression:** Existing tests should be unaffected — we're only adding new files and a new MCP tool registration.

---

## Implementation Notes for Codex

### Import paths (relative to project root `/Users/henrychien/Documents/Jupyter/risk_module/`)
- `from data_loader import fetch_monthly_total_return_price` — top-level module
- `from factor_utils import calc_monthly_returns` — top-level module
- `from core.exit_signals import ...` — new module
- `from services.position_service import PositionService` — `PositionService(user_email=email)` constructor
- `from settings import get_default_user` — **NOT** `utils.user` (does not exist)
- `from utils.date_utils import last_month_end` — returns last completed month-end as `"YYYY-MM-DD"`
- `from utils.logging import portfolio_logger` — existing logging

### PositionService usage
```python
svc = PositionService(user_email=email)
result = svc.get_all_positions(use_cache=True, consolidate=False)
# result.data.positions is a list of dicts (unconsolidated — preserves per-account detail)
# Fields: ticker, quantity (NOT shares), price, value, cost_basis, currency,
#         account_id, position_source (NOT provider)
```

### MCP tool pattern
- Redirect stdout: `_saved = sys.stdout; sys.stdout = sys.stderr` in outer function, restore in `finally`
- Return dict with `"status"` field
- User resolution: `user_email or get_default_user()` (from `settings`)
- Wrap impl in try/except in the OUTER function, return `{"status": "error", "error": str(e)}` on failure
- Use `Literal["summary", "full"]` for format param, not bare `str`

### Testing pattern
- Core tests in `tests/core/test_exit_signals.py` — pure data, no mocking needed
- MCP tests in `tests/mcp_tools/test_signals.py` — mock FMP + PositionService
- Follow existing test style: class-based grouping, descriptive method names

---

## Sequence of Implementation

1. Create `core/exit_signals.py` — pure signal functions + SignalResult dataclass
2. Create `tests/core/test_exit_signals.py` — unit tests for signal functions
3. Create `mcp_tools/signals.py` — MCP tool implementation
4. Create `tests/mcp_tools/test_signals.py` — MCP tool tests with mocks
5. Modify `mcp_server.py` — register the new tool
6. Run tests: `pytest tests/core/test_exit_signals.py tests/mcp_tools/test_signals.py -v`
7. Manual integration test: invoke `check_exit_signals(ticker="SLV", shares=100)` via MCP

---

## Codex Review — Round 1

14 items found, all addressed:

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | HIGH | `utils.user.get_default_user` doesn't exist | Changed to `from settings import get_default_user` |
| 2 | HIGH | PositionService doesn't cover IBKR | Added `shares`/`account_id` override params |
| 3 | HIGH | Sizing uses vol-normalized severity, spec uses 5% gap | Changed to `gap_threshold_pct` using `metadata["gap_pct"]` |
| 4 | HIGH | Partial month can trigger false exits | `_fetch_returns()` now uses `last_month_end()` as end_date |
| 5 | HIGH | Silently drops failed regime tickers | `_fetch_returns_panel()` now raises on any missing ticker |
| 6 | HIGH | Missing try/except in outer MCP function | Added try/except wrapping `_check_exit_signals_impl()` |
| 7 | MED | Regime check math: buy-and-hold vs rebalanced | Clarified as monthly-rebalanced equal-weight (mean per month, then compound) |
| 8 | MED | Field names wrong (shares vs quantity, provider vs position_source) | Fixed to `quantity` and `position_source` |
| 9 | MED | Missing account_id in recommended_actions | Added `account_id` to sell/stop actions when available |
| 10 | MED | `int()` floors to 0 for small holdings | Added `max(1, ...)` minimum + `min(sell_quantity, total_shares)` clamp |
| 11 | MED | RULE_REGISTRY defined but unused | Removed; dispatch is direct in `_evaluate_rule()` |
| 12 | MED | No MCP-level tests | Added `tests/mcp_tools/test_signals.py` to verification plan |
| 13 | LOW | format should be Literal type | Changed to `Literal["summary", "full"]` |
| 14 | LOW | Scheduling not concrete | Added scheduling clarification to edge cases |

## Codex Review — Round 2

5 items found, all addressed:

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | HIGH | consolidate=True can merge multi-account positions | Changed to `consolidate=False`, handle multi-account with disambiguation |
| 2 | MED | Override branch uses `source` not `position_source` | Changed to `position_source` consistently |
| 3 | MED | Errored regime rule shows "regime still supportive" | Track `status: ok/error` per signal, distinct assessment for errored rules |
| 4 | MED | Gap threshold: spec says "5% of trailing avg" (relative vs absolute) | Clarified as percentage-point gap, documented spec alignment |
| 5 | MED | `trade_eligible` always True even on errors | Now `False` when primary rule errors or doesn't trigger |
| - | LOW | Unused imports (`date`, `_resolve_user_id`) | Removed from snippet |
