# Backtest Attribution — Wire Existing Backend to Frontend

## Context

The Strategy Builder's Performance tab (StrategyBuilder.tsx:1091-1175) is a stub that shows hardcoded strategy metrics from mock `prebuiltStrategies`. Meanwhile, the backtest backend already computes comprehensive data (performance metrics, annual breakdown, monthly returns, cumulative returns, benchmark comparison) — and three attribution functions already exist in `portfolio_risk.py` but aren't called from the backtest engine:

- `_compute_security_attribution()` (line 2118) — per-ticker contribution
- `_compute_sector_attribution()` (line 2030) — sector-level via FMP profiles
- `_compute_factor_attribution()` (line 2141) — market/momentum/value OLS regression

**Goal:** Add attribution to the backtest engine output and rebuild the Performance tab to show real backtest data with attribution breakdown.

---

## Changes

### 1. Add attribution calls to backtest engine (~15 lines)

**File:** `portfolio_risk_engine/backtest_engine.py`, after line 162 (after `compute_performance_metrics()`)

Call the three existing attribution functions on the data already available in scope:

```python
from portfolio_risk_engine.portfolio_risk import (
    _compute_security_attribution,
    _compute_sector_attribution,
    _compute_factor_attribution,
)

# After performance_metrics = compute_performance_metrics(...) at line 162:
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
```

Variables already in scope: `df_ret` (line 112), `filtered_weights` (line 105), `port_ret` (line 148), `start_date`/`end_date` (function params), `fmp_ticker_map` (function params).

Exact same pattern used in `calculate_portfolio_performance_metrics()` at lines 1936-1961.

**No schema changes needed** — `performance_metrics` is a dict that flows through `BacktestResult.to_api_response()` untouched.

### 2. Add attribution types to frontend adapter (~30 lines)

**File:** `frontend/packages/connectors/src/adapters/BacktestAdapter.ts`

Add attribution interfaces and extract them in the adapter:

```typescript
export interface AttributionRow {
  name: string;
  allocation?: number;   // weight %
  return: number;         // period return %
  contribution: number;   // weighted contribution %
  beta?: number;          // factor beta (factor attribution only)
}

// Add to BacktestData interface:
export interface BacktestData {
  // ... existing fields ...
  securityAttribution: AttributionRow[];
  sectorAttribution: AttributionRow[];
  factorAttribution: AttributionRow[];
}
```

In `performTransformation()`, extract from `performanceMetrics`:

```typescript
securityAttribution: this.parseAttribution(performanceMetrics.security_attribution),
sectorAttribution: this.parseAttribution(performanceMetrics.sector_attribution),
factorAttribution: this.parseAttribution(performanceMetrics.factor_attribution),
```

Helper method:
```typescript
private parseAttribution(value: unknown): AttributionRow[] {
  if (!Array.isArray(value)) return [];
  return value.map(entry => {
    const row = toRecord(entry);
    return {
      name: typeof row.name === 'string' ? row.name : 'Unknown',
      allocation: typeof row.allocation === 'number' ? row.allocation : undefined,
      return: toNumber(row.return, 0),
      contribution: toNumber(row.contribution, 0),
      beta: typeof row.beta === 'number' ? row.beta : undefined,
    };
  });
}
```

### 3. Rebuild Performance tab with real backtest data (~200 lines)

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`, lines 1094-1175

Replace the current stub with sections that render real backtest data:

**A. Summary Metrics Card** (replaces current hardcoded card)
Read from `backtestData?.performanceMetrics` instead of mock `primaryStrategy`:
- Total Return, Annualized Return, Sharpe Ratio, Max Drawdown
- Benchmark comparison (portfolio vs SPY side-by-side)
- Alpha, Beta, R², Information Ratio

**B. Annual Breakdown Table**
Render `backtestData?.annualBreakdown` as a table:
- Columns: Year | Portfolio | Benchmark | Alpha
- Color-coded: green for positive alpha, red for negative

**C. Attribution Panels** (3 sections, each a sorted bar/table)

1. **Security Attribution** — `backtestData?.securityAttribution`
   - Table: Ticker | Weight | Return | Contribution
   - Sorted by |contribution| descending (already sorted by backend)
   - Top 5 shown, expandable

2. **Sector Attribution** — `backtestData?.sectorAttribution`
   - Table: Sector | Weight | Return | Contribution
   - Horizontal bar chart showing contribution per sector

3. **Factor Attribution** — `backtestData?.factorAttribution`
   - Table: Factor | Beta | Return | Contribution
   - Shows Market, Momentum, Value + Selection & Other residual

**D. Empty State**
When no backtest has been run yet, show a prompt: "Run a backtest to see performance attribution" with a CTA button.

### 4. Wire backtest data from container to view

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx`

The container already passes `backtest.data` via `backtestRows` (line 178), but the view only uses `optimizationData?.backtestResults`. Need to also pass the full `backtest.data` object so the Performance tab can access attribution and metrics:

```typescript
// Add to StrategyBuilder props:
backtestData={backtest.data}
```

Update StrategyBuilder props interface to accept `backtestData?: BacktestData`.

---

### 5. Export `BacktestData` type from `@risk/connectors`

**File:** `frontend/packages/connectors/src/index.ts`

Add to the "Adapter types" section (after line 51):

```typescript
export type { BacktestData, AttributionRow } from './adapters/BacktestAdapter';
```

Without this, `StrategyBuilder.tsx` cannot import `BacktestData` for its props interface.

### 6. Wrap backtest endpoint with `run_in_threadpool`

**File:** `app.py`, around line 2508

The backtest endpoint calls `run_backtest_engine()` synchronously, blocking the uvicorn event loop. Wrap with `run_in_threadpool` for consistency with optimization endpoints:

```python
from starlette.concurrency import run_in_threadpool

engine_result = await run_in_threadpool(
    run_backtest_engine,
    weights=normalized_weights,
    start_date=start_iso,
    end_date=end_iso,
    benchmark_ticker=str(backtest_request.benchmark or "SPY").upper(),
    risk_free_rate=None,
    fmp_ticker_map=portfolio_data.fmp_ticker_map,
    currency_map=portfolio_data.currency_map,
    instrument_types=portfolio_data.instrument_types,
)
```

This is especially important now that attribution calls add I/O (FMP sector lookups, factor data fetches).

---

## Thread Safety Note

`_compute_sector_attribution()` creates its own `ThreadPoolExecutor` internally (for parallel FMP profile fetches, see `portfolio_risk.py:2070`). When the backtest endpoint runs via `run_in_threadpool` (Step 6), this creates a nested thread pool scenario: outer `run_in_threadpool` thread → inner `ThreadPoolExecutor` inside `_compute_sector_attribution()`.

This is **not a blocker** — Python's `ThreadPoolExecutor` handles nesting correctly; the inner executor simply creates its own threads independent of the outer pool. The same `_compute_sector_attribution()` function is already called in production from `calculate_portfolio_performance_metrics()` at `portfolio_risk.py:1937` (via `/api/performance` → `performance_analysis.py:113`). No changes needed.

---

## Files to Modify

| File | Change | ~Lines |
|------|--------|--------|
| `portfolio_risk_engine/backtest_engine.py` | Add 3 attribution calls after performance_metrics | +15 |
| `frontend/packages/connectors/src/adapters/BacktestAdapter.ts` | Add AttributionRow type + parse attribution arrays | +30 |
| `frontend/packages/connectors/src/index.ts` | Export `BacktestData` + `AttributionRow` types | +1 |
| `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` | Rebuild Performance tab with real data + attribution panels | ~200 |
| `frontend/packages/ui/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx` | Pass full `backtestData` prop | +3 |
| `app.py` | Wrap `run_backtest_engine()` with `run_in_threadpool` | ~3 |

---

## Attribution Data Format (backend → frontend)

Each attribution row:
```json
{
  "name": "AAPL" | "Technology" | "Market",
  "allocation": 30.0,        // weight % (security/sector only)
  "return": 12.5,            // period return %
  "contribution": 3.75,      // weight × return %
  "beta": 0.95               // factor beta (factor attribution only)
}
```

Security: sorted by |contribution| desc. Sector: grouped by FMP profile sector. Factor: Market (SPY), Momentum (MTUM excess), Value (IWD excess), Selection & Other (residual).

---

## Existing Patterns

- **Attribution in `calculate_portfolio_performance_metrics()`** (`portfolio_risk.py:1936-1961`): Exact same 3 calls with try/except → `[]` fallback. Same variables passed.
- **Performance tab in PerformanceView** (`PerformanceView.tsx`): Already renders sector + security attribution from the `/api/analyze` endpoint. Same data format.
- **BacktestAdapter** (`BacktestAdapter.ts`): Already parses `performanceMetrics` as `UnknownRecord`. Attribution will flow through without schema changes on the API side.

---

## Verification

1. `python3 -m pytest tests/ -x -v` — no regressions
2. Run backtest via Python to verify attribution in response:
   ```python
   from portfolio_risk_engine.backtest_engine import run_backtest
   result = run_backtest(weights={...}, ...)
   assert "security_attribution" in result["performance_metrics"]
   assert "sector_attribution" in result["performance_metrics"]
   assert "factor_attribution" in result["performance_metrics"]
   ```
3. `pnpm typecheck` — frontend types pass
4. Start backend + frontend, navigate to Strategy Builder → run optimization → click "Backtest" → Performance tab shows real metrics + attribution tables
