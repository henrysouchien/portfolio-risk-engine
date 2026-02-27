# SLV Momentum Exit Rule — Implementation Spec

**Created:** 2026-02-09
**Status:** Spec / needs implementation plan
**Purpose:** Hand off to another Claude instance to flesh out into a full implementation plan with trade execution

---

## The Exit Rules

### Rule 1: SLV Momentum Exit (PRIMARY — triggers trade execution)

From the Silver Undersupply Trade thesis (Notion: "Silver Undersupply Trade" idea page, Final Decision Output):

> "exit criteria is momentum based (silver monthly % return < 3-monthly average of monthly return)"

**In plain terms:** At the end of each month, compare SLV's return for that month against the average monthly return over the trailing 3 months. If the current month's return is lower, the exit signal fires.

**Formula:**
```
monthly_return = (close_this_month_end / close_prior_month_end) - 1
trailing_3m_avg = average(monthly_return[t-1], monthly_return[t-2], monthly_return[t-3])

IF monthly_return < trailing_3m_avg → EXIT signal
```

> **Clarification:** "start of month" means prior month-end close (they're the same price). This was verified using FMP `historical_price_adjusted` data in the Feb 9 thesis update.

### Rule 2: Portfolio Regime Check (SECONDARY — monitor + additional signal for orders)

From the Silver - Price / Risk Check journal entry (Notion, April 22, 2025):

> "Exit criteria: SLV monthly return is < its 3-month average of monthly returns AND portfolio 3-month rolling return <0 (indicates regime is not favorable for SLV, GLD, TLT combination)"

**In plain terms:** The original risk analysis also defined a portfolio-level check: the equal-weight SLV/GLD/TLT portfolio's 3-month rolling return is negative. This indicates the overall precious metals / defensive regime is unfavorable.

**Formula:**
```
portfolio_return = equal_weight_return(SLV, GLD, TLT, period=3_months)

IF portfolio_return < 0 → REGIME UNFAVORABLE signal
```

**How to use:**
- **Monitor alongside Rule 1** — report both signals each month
- **If both Rule 1 AND Rule 2 trigger** → stronger conviction to exit (regime + asset-specific momentum both negative)
- **If only Rule 1 triggers** (SLV fading but GLD/TLT carrying the portfolio) → still execute the exit per Rule 1, but flag that regime is still supportive — relevant for sizing the reduction and re-entry timing
- **If only Rule 2 triggers** (regime unfavorable but SLV still outperforming its own trend) → monitor closely, no trade action, but elevated alert

**Origin note:** Rule 1 was the version committed in the Final Decision Output on the idea page. Rule 2 was the fuller version from the risk analysis journal entry. Decision (Feb 9, 2026): Rule 1 is the primary trade trigger; Rule 2 is monitored and used as additional context for order sizing and re-entry decisions.

## Current Status (from thesis update research, Feb 9 2026)

- **January 2026:** Nearly triggered — 17.1% monthly return vs 15.4% trailing avg. Barely survived.
- **February 2026:** Likely to trigger unless SLV rallies to ~$90 by month end (currently $76).
- Full analysis in: `SLV_THESIS_UPDATE_RESULTS_20260209.md`

## Recommended Execution Plan (from thesis update)

When the exit rule triggers:
1. **Reduce position 50-75%** (not full exit — physical thesis still intact, just momentum fading)
2. **Hard stop at $65** (OI floor, 100% bounce rate in validation — see `slv_oi_analysis_20260207.md`)
3. **Watch March COMEX deliveries** as potential catalyst to re-enter or hold remainder

## Position Details

- **Ticker:** SLV
- **Shares:** 100
- **Entry price:** $31.79
- **Current price:** ~$76
- **Account:** Interactive Brokers (IBKR)
- **Brokerage for trading:** IBKR via `ib_async` + IB Gateway (NOT SnapTrade — Bug 10 is irrelevant here)

## Trading Infrastructure

The risk_module already has trade execution capability via IBKR:

### MCP Tools (available via portfolio-mcp)
- `preview_trade(ticker, quantity, side, order_type, ...)` — previews a trade, returns preview_id
- `execute_trade(preview_id)` — executes a previewed trade
- `get_orders()` — order history
- `cancel_order(order_id)` — cancel open order

### Supported Order Types
- **Market** — execute immediately at market price
- **Limit** — execute at specified price or better
- **Stop** — trigger when price hits stop level, then execute at market
- **StopLimit** — trigger at stop level, then execute as limit order
- **Time in force:** Day, GTC, FOK, IOC

### Key Files
- `risk_module/mcp_tools/trading.py` — MCP tool definitions (preview_trade, execute_trade)
- `risk_module/services/trade_execution_service.py` — trade execution service (broker-agnostic, routes to correct adapter)
- `risk_module/services/ibkr_broker_adapter.py` — IBKR broker adapter (uses `ib_async`)
- `risk_module/services/ibkr_connection_manager.py` — IBKR connection management
- `risk_module/settings.py` — TRADING_ENABLED, IBKR_ENABLED, IBKR_GATEWAY_PORT, IBKR_AUTHORIZED_ACCOUNTS

### Prerequisites
- `TRADING_ENABLED=true` in environment
- `IBKR_ENABLED=true` in environment
- `IBKR_READONLY=false` (default, already correct)
- `IBKR_AUTHORIZED_ACCOUNTS` set to the IBKR account ID holding SLV
- IB Gateway running (port 4001 for live, 4002 for paper)
- No Bug 10 blocker — IBKR adapter is independent of SnapTrade

## Architecture Note

The SLV momentum exit is the first use case, but the implementation should be lightly abstracted so it fits into the risk_module as reusable infrastructure. Don't over-engineer — but structure it so adding a new rule for a different position doesn't require rewriting the pipeline.

**Suggested structure:**
- **Signal functions** — each rule is a function that takes a ticker (or list of tickers) + price data and returns a standardized result: `{triggered: bool, severity: float, recommended_action: str, metadata: dict}`. The momentum exit and regime check are two signal functions. Others (trailing stop, profit target, time-based) could be added later with the same interface.
- **Execution pipeline** — takes a signal result + position info and runs the preview → confirm → execute flow. This already mostly exists in the trade execution service — just needs a thin orchestration layer that connects signals to trades.
- **Configuration** — keep it simple. Could be a dict/dataclass per position specifying: ticker, account, rules to evaluate, parameters per rule, sizing logic. No need for a database or UI — a Python config or YAML file is fine for now.

The goal is: when we want to add an exit rule for another position, we write a new signal function and add a config entry — we don't copy-paste the SLV pipeline.

## What Needs to Be Built

1. **Monthly return calculator** — pull price history from FMP, compute monthly returns and trailing averages. Should work for any ticker, not just SLV.
2. **Signal checker** — evaluate rules for a given position, output standardized results for each:
   - Rule 1 (momentum exit): monthly return vs trailing N-month avg — parameterized by ticker and lookback period
   - Rule 2 (regime check): equal-weight portfolio rolling return — parameterized by tickers and period
3. **Execution workflow** — sequential steps, each requires confirmation:
   - **Step 1: Evaluate signal** — run signal checker on month-end close
   - **Step 2: Determine sell quantity** based on signal severity:
     - Feb close > $90 → no action (rule not triggered)
     - Feb close $87-$90 (within 5% of trailing avg) → sell 50 shares (50%)
     - Feb close < $87 (>5% gap) → sell 75 shares (75%)
   - **Step 3: Execute partial sell** — `preview_trade(ticker="SLV", quantity=X, side="SELL", order_type="Market")` → present for confirmation → `execute_trade`
   - **Step 4: Place hard stop on remainder** — AFTER partial sell confirms, place stop on remaining shares: `preview_trade(ticker="SLV", quantity=Y, side="SELL", order_type="Stop", stop_price=65.0, time_in_force="GTC")` → confirm → execute
   - **Step 5: Update Notion** — reduce position size in portfolio entry, add exit note with date and rationale

   **Important:** No standing orders should be placed before the month-end evaluation. The stop order only goes on AFTER the partial sell, and only on the remaining shares. Placing a stop for 100 shares now would bypass the momentum rule.
4. **Scheduling** — run at end of each month (or on-demand check)

## Key References

- **Thesis page:** Notion "Silver Undersupply Trade" — has the original exit rule, price targets, position sizing
- **Thesis update:** `investment_tools/ibkr/notebooks/SLV_THESIS_UPDATE_RESULTS_20260209.md`
- **OI analysis:** `investment_tools/ibkr/output/slv_oi_analysis_20260207.md` — OI levels, validation, risk/reward
- **Price validation script:** `investment_tools/ibkr/notebooks/validate_oi_levels.py`
- **Portfolio position in Notion:** "Long SLV" in Portfolio database
- **Thesis update TODO:** `investment_tools/ibkr/notebooks/SLV_THESIS_UPDATE_TODO_20260209.md` — outstanding data work + flow data items
- **Workflow issues:** `investment_tools/ibkr/notebooks/SLV_THESIS_UPDATE_WORKFLOW_ISSUES_20260209.md` — research process improvements

## Review Notes (Feb 9 thesis update session)

- Formula clarified: uses prior month-end close, verified against FMP data
- Added sizing rule within the 50-75% range based on signal severity
- Corrected: position is in IBKR, not Schwab/SnapTrade. Bug 10 is NOT a blocker.
- Added Rule 2 (portfolio regime check: SLV/GLD/TLT 3-month rolling return) as monitoring signal alongside primary Rule 1
- Clarified execution sequencing: no standing orders before month-end evaluation. Stop order placed only after partial sell, only on remainder.
- **Timeline:** February exit signal likely triggers at month-end (~12 trading days). Signal checker + IBKR execution path need to be ready by ~Feb 25.
- **Priority:** This is the #1 implementation priority — the momentum exit is time-sensitive.
