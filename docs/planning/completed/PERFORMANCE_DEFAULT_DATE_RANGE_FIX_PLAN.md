# Fix: `/api/performance` Default Date Range → "Insufficient Data" 500

## Context

`POST /api/performance` returns 500 with "Insufficient data for performance calculation after filtering" when called without explicit date params (which is the only way the frontend can call it, since `PerformanceRequest` has no date fields).

The MCP `get_performance(start_date="2025-01-01")` works fine because agents always pass explicit dates.

## Root Cause

The REST path loads portfolio metadata from the DB, which stores `start_date="2019-01-31"` and `end_date="2026-01-29"` (from `PORTFOLIO_DEFAULTS` in `settings.py`). These dates were inherited from the old YAML-file era and represent a 7-year analysis window. Many portfolio tickers don't have 7 years of FMP price history, causing cascading failures → "Insufficient data" → 500.

### Data flow (REST)

```
PerformanceRequest(portfolio_name, benchmark_ticker)  # no dates
→ _run_performance_workflow()
→ pm.load_portfolio_data(portfolio_name)
→ _load_portfolio_from_database()
→ get_portfolio_metadata()  # returns DB-stored dates: 2019-01-31 to 2026-01-29
→ assembler.build_portfolio_data(metadata=portfolio_metadata)
→ PortfolioData(start_date="2019-01-31", end_date="2026-01-29")
→ portfolio_service.analyze_performance()
→ create_temp_file() → run_portfolio_performance()
→ get_returns_dataframe() tries to fetch 7 years of monthly closes
→ many tickers fail → "Insufficient data" → 500
```

### Data flow (MCP — works)

```
get_performance(start_date="2025-01-01")
→ load_portfolio_for_performance(start_date="2025-01-01")
→ position_result.data.to_portfolio_data(start_date="2025-01-01")
→ PortfolioData(start_date="2025-01-01")
→ 1-year window → all tickers have data → success
```

## Fix

### 1. Add `start_date`/`end_date` to `PerformanceRequest`

**File**: `app.py` (~line 400-443)

Add optional date fields so the frontend can eventually pass custom ranges:

```python
class PerformanceRequest(BaseModel):
    portfolio_name: str = "CURRENT_PORTFOLIO"
    benchmark_ticker: str = "SPY"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
```

### 2. Apply 1-year lookback default in `_run_performance_workflow()`

**File**: `app.py` (~line 1550-1561)

When no dates are provided, default to a 1-year lookback from today. When dates are provided, override the DB-stored dates on the portfolio_data object:

```python
def _run_performance_workflow(
    benchmark_ticker: str,
    portfolio_name: str,
    user: dict,
    portfolio_service: PortfolioService,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    pm = PortfolioManager(use_database=True, user_id=user['user_id'])
    portfolio_data = pm.load_portfolio_data(portfolio_name)

    # Override DB-stored dates with request dates or sensible default
    from datetime import date
    from dateutil.relativedelta import relativedelta

    effective_end = end_date or date.today().isoformat()
    effective_start = start_date or (date.today() - relativedelta(years=1)).isoformat()
    portfolio_data.start_date = effective_start
    portfolio_data.end_date = effective_end

    result = portfolio_service.analyze_performance(portfolio_data, benchmark_ticker)
    ...
```

### 3. Wire dates through the REST endpoint handler

**File**: `app.py` (the `POST /api/performance` handler)

Pass `request.start_date` and `request.end_date` through to `_run_performance_workflow()`.

## Files

| File | Change |
|------|--------|
| `app.py` | Add `start_date`/`end_date` to `PerformanceRequest` (~line 400) |
| `app.py` | Add date params to `_run_performance_workflow()` signature (~line 1550) |
| `app.py` | Apply 1-year lookback default when no dates provided (~line 1557) |
| `app.py` | Pass request dates through at call site |

## Verification

1. `python3 -m pytest tests/ -x -q` — existing tests pass
2. Restart risk_module, load overview page in Chrome — performance section renders (no 500)
3. MCP: `get_performance(format="summary")` still works with explicit dates
4. Test with explicit dates: `curl -X POST /api/performance -d '{"start_date":"2024-01-01"}'` → custom range
5. Test without dates: `curl -X POST /api/performance` → 1-year lookback, no 500

## Notes

- `PORTFOLIO_DEFAULTS` is NOT changed — it's used in many places and changing it is too broad
- The DB-stored dates remain as-is — they're only meaningful for YAML-era workflows
- The `to_portfolio_data()` path (used by MCP) also falls back to `PORTFOLIO_DEFAULTS` when `start_date=None`, but MCP callers always pass dates explicitly. If that ever changes, the same 1-year default should be applied there too.
- The `dateutil.relativedelta` is already a dependency (used elsewhere in the codebase)
