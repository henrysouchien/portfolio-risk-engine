# Income Projection MCP Tool - Implementation Plan

> **Status:** PLANNED
> **Complexity:** Moderate (Tier 2 — combines multiple data sources)

## Overview

Expose portfolio income projection via a new `get_income_projection` MCP tool on the `portfolio-mcp` server. Combines current brokerage positions (shares + tickers) with FMP dividend history and a **new** forward dividend calendar endpoint to produce confirmed and estimated income projections.

No new service layer is needed. The core projection logic lives in a new `core/income_projection.py` module (pure computation, no I/O) with the MCP tool in `mcp_tools/income.py` handling data loading and formatting.

## Use Cases & Example Queries

This tool answers questions about portfolio dividend income, yield, and upcoming payment schedules. Example natural language queries:

- **"How much dividend income will my portfolio generate this year?"** -- `get_income_projection()` returns the total projected annual income with a breakdown of confirmed vs estimated payments
- **"When is my next dividend payment?"** -- `get_income_projection(format="calendar")` shows the month-by-month payment schedule with specific ex-dates and payment dates
- **"Which holdings contribute the most to my income?"** -- `get_income_projection()` includes the top 5 income contributors sorted by projected annual income
- **"What's my portfolio yield?"** -- `get_income_projection()` returns both yield-on-value and yield-on-cost for the entire portfolio
- **"Show me a full income breakdown per position"** -- `get_income_projection(format="full")` provides per-position detail including dividend frequency, type, and next ex-date

### Tool Chaining Example

A strategic question like **"How is my portfolio positioned for a recession?"** would chain multiple tools to assess defensiveness:

1. `get_income_projection()` -- check whether the portfolio generates reliable defensive income (high-yield, regular-frequency dividends)
2. `get_economic_data(indicator_name="smoothedUSRecessionProbabilities")` -- assess current recession probability from macro indicators
3. `get_risk_analysis(include=["risk_metrics", "factor_analysis"])` -- evaluate portfolio volatility, beta, and defensive factor exposures
4. `get_sector_overview(include_portfolio=True)` -- check exposure to defensive sectors (Utilities, Healthcare, Consumer Staples) vs cyclical sectors

The agent combines income stability, macro conditions, risk metrics, and sector positioning to give a comprehensive recession-readiness assessment.

## FMP Endpoint Registrations

### Existing (no change)
- `dividends` — `/stable/dividends?symbol=X` — per-stock dividend history (already registered in `fmp/registry.py`)

### New Registration
- `dividends_calendar` — `/stable/dividends-calendar?from=...&to=...` — forward dividend schedule across all stocks

```python
# In fmp/registry.py — add after the existing "dividends" registration

register_endpoint(
    FMPEndpoint(
        name="dividends_calendar",
        path="/dividends-calendar",
        description="Forward dividend calendar with ex-dates and payment dates",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#stock-dividend",
        category="dividends",
        api_version="stable",
        params=[
            EndpointParam("from", ParamType.DATE, required=True, description="Start date (YYYY-MM-DD)"),
            EndpointParam("to", ParamType.DATE, required=True, description="End date (YYYY-MM-DD)"),
        ],
        cache_dir="cache/dividends",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=12,  # Calendar changes as new declarations come in
    )
)
```

**Design note:** The calendar endpoint returns all stocks with upcoming ex-dates in the date range, not filtered by symbol. We fetch once and filter to portfolio holdings client-side (1 API call vs N per-ticker calls).

## MCP Tool Function Signature

```python
def get_income_projection(
    user_email: Optional[str] = None,
    projection_months: int = 12,
    format: Literal["full", "summary", "calendar"] = "summary",
    use_cache: bool = True,
) -> dict:
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `user_email` | `Optional[str]` | `None` | User email (uses `RISK_MODULE_USER_EMAIL` if not provided) |
| `projection_months` | `int` | `12` | Forward projection window (1-24 months) |
| `format` | `Literal["full", "summary", "calendar"]` | `"summary"` | Output format |
| `use_cache` | `bool` | `True` | Use cached position/dividend data |

### Format Options

- **`summary`**: Total projected annual income, portfolio yield, next 3 months breakdown, top 5 income contributors
- **`full`**: Per-position income detail (ticker, shares, annual dividend, yield, frequency, next ex-date, projected annual income)
- **`calendar`**: Month-by-month expected payment schedule with confirmed vs estimated breakdown

## Data Flow

```
┌──────────────────┐
│  PositionService  │  Step 1: Load current positions (ticker, shares, value, currency)
│  get_all_positions│  Filter out cash (CUR:*, type=="cash")
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  FMP dividends    │  Step 2: For each holding, fetch dividend history
│  (per-ticker)     │  Returns: adjDividend, frequency, ex-dates
│  Already cached   │  Uses existing fetch_dividend_history() via fmp/compat.py
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  FMP dividends-   │  Step 3: Fetch forward calendar (single call)
│  calendar         │  Date range: today → today + 90 days
│  (NEW endpoint)   │  Filter to portfolio tickers
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  core/income_     │  Step 4: Projection engine (pure computation)
│  projection.py    │  - Match calendar entries to positions → confirmed income
│                   │  - Extrapolate from history → estimated income for months
│                   │    beyond calendar coverage
│                   │  - Aggregate by month/quarter
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  mcp_tools/       │  Step 5: Format response (summary/full/calendar)
│  income.py        │
└──────────────────┘
```

## Core Module: `core/income_projection.py`

Pure computation module with no I/O. Takes pre-fetched data and produces projections.

### Key Functions

```python
def classify_dividend_type(history_df: pd.DataFrame) -> str:
    """
    Classify a stock's dividend behavior from history.

    Returns:
        "regular" — consistent payments at predictable frequency
        "variable" — payments vary significantly (>30% coefficient of variation)
        "recently_initiated" — fewer than 4 payments in history
        "none" — no dividend history
    """

def estimate_annual_dividend(history_df: pd.DataFrame) -> dict:
    """
    Estimate annual dividend from history using TTM methodology.

    Returns:
        {
            "annual_dividend_per_share": float,
            "frequency": str,  # "Quarterly", "Monthly", "Annual", "Semi-Annual"
            "dividend_type": str,  # from classify_dividend_type()
            "ttm_payments": int,
            "latest_payment_amount": float,
            "latest_ex_date": str,
        }
    """

def build_income_projection(
    positions: list[dict],
    dividend_estimates: dict[str, dict],
    calendar_entries: list[dict],
    projection_months: int = 12,
) -> dict:
    """
    Build complete income projection combining confirmed and estimated data.

    Args:
        positions: List of position dicts with ticker, shares, value, currency
        dividend_estimates: {ticker: estimate_dict} from estimate_annual_dividend()
        calendar_entries: Forward calendar entries filtered to portfolio holdings
        projection_months: Forward projection window

    Returns:
        {
            "total_projected_annual_income": float,
            "portfolio_yield_on_value": float,
            "portfolio_yield_on_cost": float,
            "positions": [per-position detail],
            "monthly_calendar": {YYYY-MM: {confirmed: float, estimated: float, total: float, payments: [...]}},
            "quarterly_summary": {Q1-Q4: {total: float, payments: int}},
            "income_by_frequency": {"Quarterly": float, "Monthly": float, ...},
            "metadata": {
                "projection_months": int,
                "positions_with_dividends": int,
                "positions_without_dividends": int,
                "confirmed_income_months": int,  # months with calendar data
                "special_dividends_excluded": [...]
            }
        }
    """
```

### Projection Logic

1. **Confirmed income** (from forward calendar, typically 0-3 months):
   - Match `dividends_calendar` entries to portfolio tickers by symbol
   - Income = `adjDividend * shares` for each matched entry
   - Mark payment month from `paymentDate` (or `date` if `paymentDate` missing)

2. **Estimated income** (from history extrapolation, months beyond calendar coverage):
   - Use `estimate_annual_dividend()` to get per-share annual dividend and frequency
   - Distribute evenly across payment months based on frequency:
     - Quarterly: every 3 months, anchored to most recent payment month
     - Monthly: every month
     - Annual: single month, anchored to most recent payment month
     - Semi-Annual: every 6 months, anchored to most recent payment months
   - For variable dividends: use TTM average but flag as estimated

3. **Special dividends**: Detected when a single payment is >2x the median regular payment. Flagged in metadata but NOT projected forward (non-recurring).

4. **Month overlap**: When a month has both confirmed (calendar) and estimated payments for the same ticker, prefer the confirmed amount.

## MCP Tool: `mcp_tools/income.py`

### Architecture

Follows the same pattern as `mcp_tools/performance.py`:
- Import `_resolve_user_id` from `mcp_tools.risk` (shared utility)
- Load positions via `PositionService` (same as `_load_portfolio_for_performance`)
- Redirect stdout to stderr
- Try/except at tool boundary

### Implementation Sketch

```python
"""
MCP Tools: get_income_projection

Exposes portfolio income projection as an MCP tool for AI invocation.

Usage (from Claude):
    "What's my projected dividend income?"
    "Show me upcoming dividend payments"
    "How much income will my portfolio generate?"

Architecture note:
- Uses live brokerage positions + FMP dividend data
- No factor proxies, risk limits, or PortfolioData needed
- Combines confirmed (calendar) and estimated (history) projections
- stdout is redirected to stderr to protect MCP JSON-RPC channel
"""

import sys
from datetime import date, timedelta
from typing import Optional, Literal

from services.position_service import PositionService
from settings import get_default_user
from mcp_tools.risk import _resolve_user_id


def _load_positions_for_income(user_email, use_cache=True):
    """
    Load positions for income projection. Returns non-cash equity positions
    with shares, value, cost_basis, and ticker info.

    Raises on error (callers catch at tool boundary).
    """
    user = user_email or get_default_user()
    if not user:
        raise ValueError("No user specified and RISK_MODULE_USER_EMAIL not configured")

    position_service = PositionService(user)
    position_result = position_service.get_all_positions(
        use_cache=use_cache,
        force_refresh=not use_cache,
        consolidate=True,
    )

    if not position_result.data.positions:
        raise ValueError("No brokerage positions found. Connect a brokerage account first.")

    # Filter to non-cash equity positions
    positions = [
        p for p in position_result.data.positions
        if p.get("type") != "cash" and not p["ticker"].startswith("CUR:")
    ]
    if not positions:
        raise ValueError("No equity positions found for income projection.")

    return positions


def _fetch_dividend_data(positions, use_cache=True):
    """
    Fetch dividend history for all positions and forward calendar.

    Returns:
        (dividend_estimates, calendar_entries) tuple
    """
    from data_loader import fetch_dividend_history
    from fmp.client import get_client
    from core.income_projection import estimate_annual_dividend

    tickers = [p["ticker"] for p in positions]
    ticker_set = set(tickers)

    # 1. Fetch dividend history per ticker
    dividend_estimates = {}
    for p in positions:
        ticker = p["ticker"]
        fmp_ticker = p.get("fmp_ticker") or ticker
        try:
            history_df = fetch_dividend_history(
                ticker,
                fmp_ticker=fmp_ticker,
            )
            dividend_estimates[ticker] = estimate_annual_dividend(history_df)
        except Exception:
            # Non-dividend payer or API error — skip
            dividend_estimates[ticker] = estimate_annual_dividend(None)

    # 2. Fetch forward calendar (single call, 90 days)
    today = date.today()
    end_date = today + timedelta(days=90)

    try:
        client = get_client()
        calendar_df = client.fetch(
            "dividends_calendar",
            **{"from": today.isoformat(), "to": end_date.isoformat()},
            use_cache=use_cache,
        )
        # Filter to portfolio holdings
        if not calendar_df.empty and "symbol" in calendar_df.columns:
            calendar_df = calendar_df[calendar_df["symbol"].isin(ticker_set)]
            calendar_entries = calendar_df.to_dict("records")
        else:
            calendar_entries = []
    except Exception:
        # Calendar unavailable — fall back to history-only projection
        calendar_entries = []

    return dividend_estimates, calendar_entries


def get_income_projection(
    user_email: Optional[str] = None,
    projection_months: int = 12,
    format: Literal["full", "summary", "calendar"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Project portfolio dividend income from current holdings.

    Combines current positions with dividend history and forward
    dividend calendar to produce confirmed and estimated income projections.

    Args:
        user_email: User to analyze. If not provided, uses default user.
        projection_months: Forward projection window in months (default: 12, max: 24).
        format: Output format:
            - "summary": Annual income, yield, next 3 months, top contributors
            - "full": Per-position income detail with dividend metadata
            - "calendar": Month-by-month payment schedule
        use_cache: Use cached position/dividend data (default: True).

    Returns:
        dict: Income projection data with status field ("success" or "error")

    Examples:
        "What's my projected dividend income?" -> get_income_projection()
        "Show me upcoming dividends" -> get_income_projection(format="calendar")
        "Full income detail per position" -> get_income_projection(format="full")
        "6-month income forecast" -> get_income_projection(projection_months=6)
    """
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # Validate projection_months
        projection_months = max(1, min(24, projection_months))

        # 1. Load positions
        positions = _load_positions_for_income(user_email, use_cache=use_cache)

        # 2. Fetch dividend data
        dividend_estimates, calendar_entries = _fetch_dividend_data(
            positions, use_cache=use_cache
        )

        # 3. Build projection
        from core.income_projection import build_income_projection

        projection = build_income_projection(
            positions=positions,
            dividend_estimates=dividend_estimates,
            calendar_entries=calendar_entries,
            projection_months=projection_months,
        )

        # 4. Format response
        if format == "summary":
            return _format_summary(projection)
        elif format == "full":
            return _format_full(projection)
        else:  # calendar
            return _format_calendar(projection)

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }
    finally:
        sys.stdout = _saved


def _format_summary(projection: dict) -> dict:
    """Format summary response: key metrics + top contributors."""
    positions = projection.get("positions", [])
    monthly = projection.get("monthly_calendar", {})
    metadata = projection.get("metadata", {})

    # Top 5 income contributors by projected annual income
    income_positions = [
        p for p in positions if p.get("projected_annual_income", 0) > 0
    ]
    income_positions.sort(
        key=lambda p: p.get("projected_annual_income", 0), reverse=True
    )
    top_contributors = [
        {
            "ticker": p["ticker"],
            "shares": p["shares"],
            "annual_dividend_per_share": p.get("annual_dividend_per_share", 0),
            "projected_annual_income": p.get("projected_annual_income", 0),
            "yield_on_cost": p.get("yield_on_cost", 0),
            "frequency": p.get("frequency", "Unknown"),
        }
        for p in income_positions[:5]
    ]

    # Next 3 months breakdown
    sorted_months = sorted(monthly.keys())[:3]
    next_3_months = {
        m: {
            "total": monthly[m]["total"],
            "confirmed": monthly[m]["confirmed"],
            "estimated": monthly[m]["estimated"],
            "payment_count": len(monthly[m].get("payments", [])),
        }
        for m in sorted_months
    }

    return {
        "status": "success",
        "total_projected_annual_income": projection.get("total_projected_annual_income", 0),
        "portfolio_yield_on_value": projection.get("portfolio_yield_on_value", 0),
        "portfolio_yield_on_cost": projection.get("portfolio_yield_on_cost", 0),
        "next_3_months": next_3_months,
        "top_5_contributors": top_contributors,
        "positions_with_dividends": metadata.get("positions_with_dividends", 0),
        "positions_without_dividends": metadata.get("positions_without_dividends", 0),
        "projection_months": metadata.get("projection_months", 12),
    }


def _format_full(projection: dict) -> dict:
    """Format full response: per-position detail."""
    return {
        "status": "success",
        **projection,
    }


def _format_calendar(projection: dict) -> dict:
    """Format calendar response: month-by-month schedule."""
    monthly = projection.get("monthly_calendar", {})
    metadata = projection.get("metadata", {})

    return {
        "status": "success",
        "monthly_calendar": monthly,
        "quarterly_summary": projection.get("quarterly_summary", {}),
        "total_projected_annual_income": projection.get("total_projected_annual_income", 0),
        "income_by_frequency": projection.get("income_by_frequency", {}),
        "metadata": metadata,
    }
```

## Output Structures

### Summary Format
```python
{
    "status": "success",
    "total_projected_annual_income": 15234.50,
    "portfolio_yield_on_value": 4.82,       # percentage
    "portfolio_yield_on_cost": 5.31,         # percentage
    "next_3_months": {
        "2026-02": {"total": 1250.00, "confirmed": 1100.00, "estimated": 150.00, "payment_count": 5},
        "2026-03": {"total": 980.00, "confirmed": 980.00, "estimated": 0.00, "payment_count": 3},
        "2026-04": {"total": 1420.00, "confirmed": 0.00, "estimated": 1420.00, "payment_count": 7},
    },
    "top_5_contributors": [
        {
            "ticker": "STWD",
            "shares": 2964,
            "annual_dividend_per_share": 1.92,
            "projected_annual_income": 5690.88,
            "yield_on_cost": 9.47,
            "frequency": "Quarterly"
        },
        ...
    ],
    "positions_with_dividends": 18,
    "positions_without_dividends": 3,
    "projection_months": 12
}
```

### Full Format
```python
{
    "status": "success",
    "total_projected_annual_income": 15234.50,
    "portfolio_yield_on_value": 4.82,
    "portfolio_yield_on_cost": 5.31,
    "positions": [
        {
            "ticker": "STWD",
            "shares": 2964,
            "market_value": 60082.20,
            "cost_basis": 31867.00,
            "annual_dividend_per_share": 1.92,
            "projected_annual_income": 5690.88,
            "yield_on_value": 9.47,
            "yield_on_cost": 17.86,
            "frequency": "Quarterly",
            "dividend_type": "regular",     # regular | variable | recently_initiated | none
            "next_ex_date": "2026-03-15",   # from calendar, or null
            "next_payment_date": "2026-04-01",
            "ttm_payments": 4,
            "latest_payment_amount": 0.48,
            "currency": "USD"
        },
        {
            "ticker": "AAPL",
            "shares": 100,
            "market_value": 23750.00,
            "cost_basis": 15000.00,
            "annual_dividend_per_share": 1.00,
            "projected_annual_income": 100.00,
            "yield_on_value": 0.42,
            "yield_on_cost": 0.67,
            "frequency": "Quarterly",
            "dividend_type": "regular",
            "next_ex_date": "2026-02-10",
            "next_payment_date": "2026-02-15",
            "ttm_payments": 4,
            "latest_payment_amount": 0.25,
            "currency": "USD"
        },
        {
            "ticker": "TSLA",
            "shares": 50,
            "market_value": 18500.00,
            "cost_basis": 12000.00,
            "annual_dividend_per_share": 0.0,
            "projected_annual_income": 0.0,
            "yield_on_value": 0.0,
            "yield_on_cost": 0.0,
            "frequency": "None",
            "dividend_type": "none",
            "next_ex_date": null,
            "next_payment_date": null,
            "ttm_payments": 0,
            "latest_payment_amount": 0.0,
            "currency": "USD"
        }
    ],
    "monthly_calendar": { ... },    # same as calendar format
    "quarterly_summary": { ... },
    "income_by_frequency": {"Quarterly": 12000.00, "Monthly": 3000.00, "Annual": 234.50},
    "metadata": {
        "projection_months": 12,
        "positions_with_dividends": 18,
        "positions_without_dividends": 3,
        "confirmed_income_months": 3,
        "special_dividends_excluded": [
            {"ticker": "MSFT", "date": "2025-11-15", "amount": 5.00, "reason": "special"}
        ]
    }
}
```

### Calendar Format
```python
{
    "status": "success",
    "monthly_calendar": {
        "2026-02": {
            "total": 1250.00,
            "confirmed": 1100.00,
            "estimated": 150.00,
            "payments": [
                {
                    "ticker": "STWD",
                    "amount": 480.00,          # shares * dividend per share
                    "dividend_per_share": 0.48,
                    "ex_date": "2026-02-14",
                    "payment_date": "2026-02-28",
                    "source": "confirmed"       # "confirmed" | "estimated"
                },
                {
                    "ticker": "DSU",
                    "amount": 150.00,
                    "dividend_per_share": 0.05,
                    "ex_date": null,
                    "payment_date": null,
                    "source": "estimated"
                },
                ...
            ]
        },
        "2026-03": { ... },
        ...
    },
    "quarterly_summary": {
        "Q1_2026": {"total": 3650.00, "payments": 15},
        "Q2_2026": {"total": 3800.00, "payments": 16},
        "Q3_2026": {"total": 3900.00, "payments": 15},
        "Q4_2026": {"total": 3884.50, "payments": 14}
    },
    "total_projected_annual_income": 15234.50,
    "income_by_frequency": {"Quarterly": 12000.00, "Monthly": 3000.00, "Annual": 234.50},
    "metadata": { ... }
}
```

## Edge Cases

### 1. No dividend history (non-payers)
- `estimate_annual_dividend(None)` or empty DataFrame returns `dividend_type: "none"`, all amounts 0
- Position appears in full format with `projected_annual_income: 0` — NOT omitted
- Summary skips these in `top_5_contributors` (they have zero income)
- `positions_without_dividends` count in metadata

### 2. Variable dividends (e.g., REITs with fluctuating payouts)
- Detected when coefficient of variation of adjDividend > 0.30
- `dividend_type: "variable"` — uses TTM sum as annual estimate
- Not excluded from projections, but flagged for transparency
- Calendar entries still use confirmed amounts when available

### 3. Recently initiated dividends (< 4 payments)
- `dividend_type: "recently_initiated"`
- Annualize from available data: if 2 quarterly payments, annual = sum * 2
- Flag as lower confidence in metadata

### 4. Special dividends
- A payment is "special" when it exceeds 2x the median regular payment for that stock
- Special dividends are excluded from forward projection (non-recurring)
- Listed in `metadata.special_dividends_excluded` for transparency
- FMP's `frequency` field or `label` may also indicate "Special" — check both

### 5. Calendar endpoint returns no data
- Graceful fallback: all months become "estimated" (no confirmed entries)
- Warning logged but not surfaced as error
- `confirmed_income_months: 0` in metadata

### 6. FMP dividend history fetch fails for a ticker
- Individual ticker failure does not fail the entire projection
- That ticker gets `dividend_type: "none"` and zero income
- Warning logged via `portfolio_logger`

### 7. Foreign currency positions
- Dividend amounts from FMP are in local currency
- Position `value` is already USD-converted (by PositionService)
- For yield calculations: use USD market value (from position)
- For income projection: use local dividend * shares, then flag currency
- If position has `currency` != "USD", note in per-position output

### 8. Short positions (negative shares)
- Shorts pay dividends out (negative income)
- Include in projection with negative `projected_annual_income`
- Income = shares (negative) * dividend_per_share

### 9. ETFs and funds
- ETFs pay dividends — treated same as stocks
- Use same `fetch_dividend_history()` path
- ETF dividend frequency may be irregular — handle via date-spacing estimation

### 10. Projection months validation
- Clamp to [1, 24] range
- Values < 1 set to 1, values > 24 set to 24

## Files to Create

### 1. `core/income_projection.py` (NEW)
Pure computation module. Functions:
- `classify_dividend_type(history_df)` — categorize payer behavior
- `estimate_annual_dividend(history_df)` — TTM-based annual estimate
- `build_income_projection(positions, dividend_estimates, calendar_entries, projection_months)` — main engine
- `_detect_special_dividends(history_df)` — identify non-recurring payments
- `_project_payment_months(frequency, anchor_month, projection_months)` — schedule generator
- `_assign_calendar_quarter(month_str)` — "2026-03" -> "Q1_2026"

### 2. `mcp_tools/income.py` (NEW)
MCP tool implementation. Functions:
- `_load_positions_for_income(user_email, use_cache)` — position loading (lightweight, no PortfolioData)
- `_fetch_dividend_data(positions, use_cache)` — FMP data fetching
- `get_income_projection(...)` — main tool entry point
- `_format_summary(projection)` — summary formatter
- `_format_full(projection)` — full formatter
- `_format_calendar(projection)` — calendar formatter

## Files to Modify

### 3. `fmp/registry.py`
- Add `dividends_calendar` endpoint registration (after existing `dividends` registration)

### 4. `mcp_server.py`
- Add import: `from mcp_tools.income import get_income_projection as _get_income_projection`
- Add `@mcp.tool()` registration for `get_income_projection`

### 5. `mcp_tools/__init__.py`
- Add import: `from mcp_tools.income import get_income_projection`
- Add `"get_income_projection"` to `__all__`
- Update docstring tool list

### 6. `mcp_tools/README.md`
- Add `get_income_projection` tool documentation

## mcp_server.py Registration

```python
@mcp.tool()
def get_income_projection(
    projection_months: int = 12,
    format: Literal["full", "summary", "calendar"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Project portfolio dividend income from current holdings.

    Combines current positions with dividend history and forward
    dividend calendar to produce confirmed and estimated income
    projections by month.

    Args:
        projection_months: Forward projection window in months (default: 12, max: 24).
        format: Output format:
            - "summary": Annual income, yield, next 3 months, top contributors
            - "full": Per-position income detail with dividend metadata
            - "calendar": Month-by-month payment schedule (confirmed vs estimated)
        use_cache: Use cached position/dividend data (default: True).

    Returns:
        Income projection data with status field ("success" or "error").

    Examples:
        "What's my projected dividend income?" -> get_income_projection()
        "Show me upcoming dividend payments" -> get_income_projection(format="calendar")
        "Full income breakdown per position" -> get_income_projection(format="full")
        "6-month income forecast" -> get_income_projection(projection_months=6)
    """
    return _get_income_projection(
        user_email=None,  # Uses RISK_MODULE_USER_EMAIL from env
        projection_months=projection_months,
        format=format,
        use_cache=use_cache,
    )
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No user configured | `{"status": "error", "error": "No user specified and RISK_MODULE_USER_EMAIL not configured"}` |
| No positions found | `{"status": "error", "error": "No brokerage positions found..."}` |
| All positions are cash | `{"status": "error", "error": "No equity positions found for income projection."}` |
| FMP API failure (calendar) | Graceful fallback — all months estimated, warning logged |
| FMP API failure (single ticker dividends) | That ticker gets `dividend_type: "none"`, warning logged |
| FMP API failure (all tickers) | Still succeeds with all positions showing zero income |
| Invalid projection_months | Clamped to [1, 24] — no error |

## Patterns Followed

| Pattern | Implementation |
|---------|---------------|
| stdout redirection | `sys.stdout = sys.stderr` in try/finally |
| Error handling | `try/except -> {"status": "error", "error": str(e)}` |
| Format switching | summary/full/calendar consistent structure |
| Tool registration | `@mcp.tool()` in `mcp_server.py` with full docstrings |
| Exports | `mcp_tools/__init__.py` imports + `__all__` |
| Position loading | Via `PositionService` (matches `_load_portfolio_weights` pattern) |
| No PortfolioData needed | Like `get_factor_analysis` — lightweight, no factor proxies/risk limits |
| FMP client usage | `get_client().fetch()` for new endpoint, `fetch_dividend_history()` for existing |
| Pure core module | `core/income_projection.py` — no I/O, testable in isolation |
| `user_email` hidden at server | MCP server passes `user_email=None`, tool reads from env |

## Testing Plan

### Unit Tests: `tests/core/test_income_projection.py`

1. **classify_dividend_type** — regular, variable, recently_initiated, none (empty/None)
2. **estimate_annual_dividend** — quarterly payer, monthly payer, annual payer, empty
3. **_detect_special_dividends** — normal payments (none detected), one outlier detected
4. **_project_payment_months** — quarterly from anchor, monthly, annual
5. **build_income_projection** — full integration with mock data:
   - Mixed portfolio (payers + non-payers)
   - Confirmed + estimated mix
   - Special dividend exclusion
   - Short position (negative income)
   - Variable dividend flagging
6. **Edge: empty positions list** — returns zero totals, empty calendar
7. **Edge: no calendar entries** — all estimated, zero confirmed

### Integration Tests (manual verification)

1. `get_income_projection(format="summary")` — status: success, yields > 0
2. `get_income_projection(format="full")` — all positions present, non-payers show zero
3. `get_income_projection(format="calendar")` — 12 months of data, quarterly summary
4. `get_income_projection(projection_months=6)` — only 6 months in calendar
5. `get_income_projection(projection_months=0)` — clamped to 1, no error

## Estimated Complexity

- **Core module** (`core/income_projection.py`): ~200 lines — frequency detection, TTM estimation, calendar merging, month projection
- **MCP tool** (`mcp_tools/income.py`): ~180 lines — position loading, FMP fetching, 3 formatters
- **FMP registration** (`fmp/registry.py`): ~15 lines — single endpoint
- **Server/init updates**: ~40 lines — boilerplate registration
- **Tests**: ~250 lines — unit tests for core module

**Total: ~685 lines across 6 files**

**Estimated implementation time:** 4-6 hours

**API calls per invocation:**
- 1 call to `dividends-calendar` (single bulk call for next 90 days)
- N calls to `dividends` (per ticker, but cached monthly — warm cache means zero API calls after first run)
- Typical portfolio of 20 positions: 1 + 20 = 21 FMP calls on first run, 1 on subsequent (cached)

---

*Created: 2026-02-07*
