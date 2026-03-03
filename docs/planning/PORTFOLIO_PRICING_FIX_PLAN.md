# Fix: `transform_portfolio_for_display()` Returns Zero Market Values

**Date**: 2026-03-02
**Status**: COMPLETE

## Context

`GET /api/portfolios/{portfolio_name}` calls `transform_portfolio_for_display()` (app.py line ~2290) which hardcodes `market_value: 0` for every holding. The frontend tries to fix this with a separate `POST /api/portfolio/refresh-prices` call in `PortfolioInitializer.tsx`, but that's a fragile second round-trip that can silently fail.

The pricing logic already exists in `PortfolioService.refresh_portfolio_prices()` (portfolio_service.py line ~929) — it calls `latest_price()`, handles cash positions, futures instrument types, etc. We just need the `get_portfolio` endpoint to use it.

---

## Implementation Plan

### Step 1: Add `portfolio_service` dependency to `get_portfolio` endpoint

**File**: `app.py` line ~2371

Add `portfolio_service` as a FastAPI dependency (same pattern already used by `refresh_prices` on line 2329):

```python
# Before:
@app.get("/api/portfolios/{portfolio_name}", response_model=get_response_model(CurrentPortfolioResponse))
async def get_portfolio(
    portfolio_name: str,
    request: Request,
    user: dict = Depends(get_current_user)
):

# After:
@app.get("/api/portfolios/{portfolio_name}", response_model=get_response_model(CurrentPortfolioResponse))
async def get_portfolio(
    portfolio_name: str,
    request: Request,
    user: dict = Depends(get_current_user),
    portfolio_service: PortfolioService = Depends(
        lambda user=Depends(get_current_user): get_user_portfolio_service(user)
    )
):
```

### Step 2: Rewrite `transform_portfolio_for_display()` to accept and use `portfolio_service`

**File**: `app.py` line ~2290

Change signature to accept `portfolio_service` (optional for backward compat). Build the stub holdings list from `standardized_input` as before, including `fmp_ticker` from `portfolio_data.fmp_ticker_map`. Then delegate to `portfolio_service.refresh_portfolio_prices()` to fill in real prices:

```python
def transform_portfolio_for_display(portfolio_data, portfolio_service=None):
    """Transform PortfolioData to frontend display format with live prices.

    Builds a holdings list from standardized_input, then delegates to
    PortfolioService.refresh_portfolio_prices() to fill in market_value
    via latest_price(). If no service is provided or pricing fails,
    market_value stays 0 (the frontend adapter has a time-series fallback).
    """
    holdings_list = []
    for ticker, holding in portfolio_data.standardized_input.items():
        quantity = holding.get("shares", 0) or holding.get("dollars", 0)
        holdings_list.append({
            "ticker": ticker,
            "shares": quantity,
            "market_value": 0,
            "security_name": "",
            "type": holding.get("type"),
            "fmp_ticker": (portfolio_data.fmp_ticker_map or {}).get(ticker),
        })

    # Price via PortfolioService if available
    if portfolio_service is not None:
        try:
            result = portfolio_service.refresh_portfolio_prices(holdings_list)
            holdings_list = result.get("holdings", holdings_list)
            total_value = result.get("total_portfolio_value", 0)
        except Exception as e:
            api_logger.warning(f"transform_portfolio_for_display: pricing failed: {e}")
            total_value = 0
    else:
        total_value = sum(h.get("market_value", 0) for h in holdings_list)

    # Enrich holdings with display metadata
    holdings_list = enrich_holdings_with_metadata(holdings_list)

    return {
        "holdings": holdings_list,
        "total_portfolio_value": total_value,
        "statement_date": portfolio_data._last_updated.isoformat() if portfolio_data._last_updated else datetime.now(UTC).isoformat(),
        "account_type": "Database Portfolio"
    }
```

### Step 3: Pass `portfolio_service` from endpoint

**File**: `app.py` line ~2394

```python
# Before:
transformed_data = transform_portfolio_for_display(portfolio_data)

# After:
transformed_data = transform_portfolio_for_display(portfolio_data, portfolio_service)
```

### Step 4: Remove debug prints

Remove the `print(f"[TRANSFORM DEBUG]...")` and `print(f"[ENRICH DEBUG]...")` lines from both `transform_portfolio_for_display()` and `enrich_holdings_with_metadata()`.

---

## Files Modified

| File | Change |
|------|--------|
| `app.py` | Add `portfolio_service` dep to `get_portfolio`, rewrite `transform_portfolio_for_display()`, pass service, remove debug prints |

## What This Does NOT Change

- `refresh-prices` endpoint unchanged — still works as a manual refresh
- Frontend `PortfolioInitializer.tsx` unchanged — its refresh call becomes redundant but harmless
- No adapter or frontend changes needed
- `PortfolioService.refresh_portfolio_prices()` unchanged

## Verification

1. Restart backend: `python app.py`
2. Load dashboard — Total Portfolio Value should show real value on first load (no flaky refresh needed)
3. The `refresh-prices` frontend call should still work as before (idempotent)
