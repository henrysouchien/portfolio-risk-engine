# Wave 2.6: Stock Research — Wire Real Risk Data

**Status**: COMPLETE — Commit `03f010ea`
**Parent doc**: `completed/FRONTEND_PHASE2_WORKING_DOC.md` → "Stock Research Residual Gaps"
**Date**: 2026-03-03

## Context

The Stock Research view (`StockLookup.tsx`) has multiple data gaps despite the backend already computing the needed values. The `/api/direct/stock` endpoint calls `to_api_response()` → `enrich_stock_data()`, returning `volatility_metrics` (with `sharpe_ratio`), `regression_metrics` (with `r_squared`), and `factor_summary` (per-factor betas/r_squared). However:

1. **Risk Factors tab is 100% hardcoded** — 6 fake factors instead of real `factor_summary` data
2. **Sharpe ratio** — backend has real value in `volatility_metrics.sharpe_ratio` but container looks in wrong place (`stockRecord.sharpe_ratio`), falls back to `1.2`
3. **Max drawdown** — backend does NOT include it in `vol_metrics` (computed but not added to dict). Container uses synthetic `vol * -2`
4. **Correlation to S&P 500** — BUG: uses `r_squared` directly instead of `sqrt(r_squared)` with sign from beta
5. **VaR 95%/99%** — no backend field, container uses parametric `vol * z-score` which is mathematically valid but uses annual vol instead of daily vol
6. **Volatility display scale** — `annual_vol` is decimal (0.25 = 25%) but displayed raw with `%` suffix → shows "0.2%" instead of "25.0%"
7. **Adapter** — `StockRiskDisplayData.volatility_metrics` only types `monthly_vol` and `annual_vol`, dropping `sharpe_ratio`/`sortino_ratio` that flow from backend

## Scope

| Item | Layer | Effort |
|------|-------|--------|
| Add `max_drawdown` to `vol_metrics` dict | Backend | Trivial (1 line) |
| Extend adapter `volatility_metrics` type | Frontend adapter | Low |
| Pass `factor_summary` through to view | Frontend container + props | Medium |
| Fix sharpe/maxDrawdown/correlation/vol scale mappings | Frontend container | Low |
| Replace hardcoded Risk Factors tab | Frontend view | Medium |
| Fix VaR computation (daily vol, not annual) | Frontend container | Trivial |

---

## Step 1: Backend — Add `max_drawdown` to `vol_metrics` (both analysis paths)

**File**: `portfolio_risk_engine/risk_summary.py`

### 1a. Simple market regression path — `get_stock_risk_profile()` (line 75-77)

Currently computes `sharpe_ratio` and `sortino_ratio` from `compute_stock_performance_metrics()` and adds them to `vol_metrics`, but `max_drawdown` (also in the DataFrame) is not added. The local variable is `stock_perf` (NOT `perf_metrics`), and the index is `"stock"` (NOT the ticker symbol):

```python
# After existing lines 76-77 that add sharpe_ratio and sortino_ratio:
if "stock" in stock_perf.index:
    vol_metrics["sharpe_ratio"] = float(stock_perf.loc["stock", "Sharpe"])
    vol_metrics["sortino_ratio"] = float(stock_perf.loc["stock", "Sortino"])
    vol_metrics["max_drawdown"] = float(stock_perf.loc["stock", "Max Drawdown"])  # ADD THIS LINE
```

### 1b. Multi-factor path — `get_detailed_stock_factor_profile()` (line 190)

This function only calls `compute_volatility()` which returns just `{monthly_vol, annual_vol}`. It does NOT call `compute_stock_performance_metrics()`, so `sharpe_ratio`/`sortino_ratio`/`max_drawdown` are all missing in the multi-factor path.

Add performance metrics computation after line 190:

```python
# Line 190 existing:
"vol_metrics": compute_volatility(df_reg["stock"]),

# Replace with:
vol_metrics = compute_volatility(df_reg["stock"])
# Add performance metrics (sharpe, sortino, max_drawdown) — same pattern as get_stock_risk_profile()
try:
    stock_perf = compute_stock_performance_metrics(
        pd.DataFrame({"stock": df_reg["stock"]}),  # use df_reg to match volatility/regression window
        risk_free_rate=0.04,
        start_date=str(start_date),
        end_date=str(end_date),
    )
    if "stock" in stock_perf.index:
        vol_metrics["sharpe_ratio"] = float(stock_perf.loc["stock", "Sharpe"])
        vol_metrics["sortino_ratio"] = float(stock_perf.loc["stock", "Sortino"])
        vol_metrics["max_drawdown"] = float(stock_perf.loc["stock", "Max Drawdown"])
except Exception:
    pass  # graceful — these are enrichment fields, not critical

# Then use vol_metrics in the return dict:
return {
    "vol_metrics": vol_metrics,
    ...
}
```

This ensures both analysis paths (simple regression + multi-factor) include sharpe/sortino/max_drawdown. The `get_agent_snapshot()` method already tries `vol.get("max_drawdown")` at line 145 — this fix makes it return real data in both paths.

## Step 2: Frontend — Extend `StockRiskDisplayData` in adapter

**File**: `frontend/packages/connectors/src/adapters/StockAnalysisAdapter.ts`

Extend the `volatility_metrics` type in `StockRiskDisplayData` interface (line 74-77):

```typescript
volatility_metrics: {
  monthly_vol: number;
  annual_vol: number;
  sharpe_ratio?: number;    // ADD
  sortino_ratio?: number;   // ADD
  max_drawdown?: number;    // ADD
};
```

Extend the `factor_summary` type (line 84-88) to include `r_squared` and `idio_vol_m`:

```typescript
factor_summary?: {
  beta?: Record<string, number>;
  r_squared?: Record<string, number>;      // ADD
  idio_vol_m?: Record<string, number>;     // ADD
};
```

Update `performTransformation()` (line 197-201) to preserve the new `factor_summary` sub-keys:

```typescript
factor_summary: Object.keys(factorSummary).length > 0 ? {
  beta: Object.fromEntries(
    Object.entries(factorBeta).filter(([, value]) => typeof value === 'number')
  ) as Record<string, number>,
  r_squared: Object.fromEntries(
    Object.entries(this.toRecord(factorSummary.r_squared)).filter(([, value]) => typeof value === 'number')
  ) as Record<string, number>,
  idio_vol_m: Object.fromEntries(
    Object.entries(this.toRecord(factorSummary.idio_vol_m)).filter(([, value]) => typeof value === 'number')
  ) as Record<string, number>,
} : undefined,
```

Also extend the `volatility_metrics` extraction (lines 187-190) to pass through the new keys. Add a private helper that returns `number | undefined` (existing `extractNumericValue` always returns `number` with a required fallback, so we need a variant that handles both string-encoded numbers AND missing values):

```typescript
private extractOptionalNumericValue(obj: Record<string, unknown>, key: string): number | undefined {
  const value = obj?.[key];
  if (typeof value === 'number' && !isNaN(value)) return value;
  if (typeof value === 'string') {
    const parsed = parseFloat(value);
    if (!isNaN(parsed)) return parsed;
  }
  return undefined;
}
```

Then use it:
```typescript
volatility_metrics: {
  monthly_vol: this.extractNumericValue(volatilityMetrics, 'monthly_vol', 0),
  annual_vol: this.extractNumericValue(volatilityMetrics, 'annual_vol', 0),
  sharpe_ratio: this.extractOptionalNumericValue(volatilityMetrics, 'sharpe_ratio'),
  sortino_ratio: this.extractOptionalNumericValue(volatilityMetrics, 'sortino_ratio'),
  max_drawdown: this.extractOptionalNumericValue(volatilityMetrics, 'max_drawdown'),
},
```

## Step 3: Frontend — Fix container data mappings

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx`

### 3a. Fix volatility scale (line 249, 292, 303)
`annual_vol` from backend is decimal (0.25 = 25%). Container stores raw decimal, view appends `%` → shows "0.2%" instead of "25.0%". Fix by converting to percentage at the extraction point:
```typescript
// BEFORE:
const annualVolatility = toNumber(stockData.volatility_metrics?.annual_vol, 0);
// AFTER:
const annualVolatility = toNumber(stockData.volatility_metrics?.annual_vol, 0) * 100;
```
This fixes both the volatility display and the VaR computation downstream (which uses `annualVolatility`).

### 3b. Fix sharpe ratio (line 293)
```typescript
// BEFORE:
sharpeRatio: toNumber(stockRecord.sharpe_ratio, toNumber(analysisRecord.sharpe_ratio, 1.2)),
// AFTER:
sharpeRatio: toNumber(stockData.volatility_metrics?.sharpe_ratio, 0),
```
Fallback `0` not `1.2` — if no data, show 0 (honest) not a fake positive number.

### 3c. Fix max drawdown (line 294)
```typescript
// BEFORE:
maxDrawdown: toNumber(stockRecord.max_drawdown, Math.abs(annualVolatility || 15) * -2),
// AFTER:
maxDrawdown: toNumber(stockData.volatility_metrics?.max_drawdown, 0) * 100,
```
Backend stores `max_drawdown` as decimal (e.g., -0.25 for -25%). Multiply by 100 for display percentage. Fallback `0`.

### 3d. Fix correlation to S&P 500 — BUG FIX (line 295)
```typescript
// BEFORE (BUG: r_squared is not correlation):
correlationToSP500: toNumber(stockData.regression_metrics?.r_squared, beta || 0.7),
// AFTER (correct: correlation = sign(beta) * sqrt(r_squared)):
correlationToSP500: (() => {
  const rSq = stockData.regression_metrics?.r_squared;
  if (typeof rSq === 'number' && rSq > 0) {
    return Math.sign(beta) * Math.sqrt(rSq);
  }
  return 0;
})(),
```

### 3e. Fix VaR computation (lines 289-290)
After fix 3a, `annualVolatility` is in percentage form (e.g., 25.0 for 25%). Daily VaR = annualVol / sqrt(252) * z-score:
```typescript
// BEFORE:
var95: toNumber(stockRecord.var_95, Math.abs(annualVolatility || 15) * 1.65),
var99: toNumber(stockRecord.var_99, Math.abs(annualVolatility || 20) * 2.33),
// AFTER (parametric daily VaR):
var95: (annualVolatility / Math.sqrt(252)) * 1.645,
var99: (annualVolatility / Math.sqrt(252)) * 2.326,
```
Result is already in percentage terms since `annualVolatility` is in %. For a 25% annual vol stock: daily VaR95 = 25/15.87 * 1.645 ≈ 2.6%.

### 3f. Pass factor_summary through to view
Add `factorSummary` to the returned object:
```typescript
factorSummary: stockData.factor_summary ?? undefined,
```

## Step 4: Frontend — Extend `StockLookup` props and types

**File**: `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

### 4a. Add `factorSummary` to the `StockLookupSelectedStock` type (or wherever the selectedStock type is defined)
```typescript
factorSummary?: {
  beta?: Record<string, number>;
  r_squared?: Record<string, number>;
  idio_vol_m?: Record<string, number>;
};
```

### 4b. Replace hardcoded `riskFactors` array (lines 319-326)

Replace the static array with a computed one from `selectedStock.factorSummary`:

```typescript
const riskFactors: RiskFactor[] = selectedStock?.factorSummary?.beta
  ? Object.entries(selectedStock.factorSummary.beta).map(([name, betaValue]) => {
      const rSquared = selectedStock.factorSummary?.r_squared?.[name] ?? 0;
      const displayName = name.charAt(0).toUpperCase() + name.slice(1);
      return {
        name: displayName,
        exposure: Math.round(Math.min(Math.abs(betaValue) / 2, 1) * 100),  // beta → 0-100 scale (2.0 beta = 100%)
        risk: Math.round(rSquared * 100),                                   // r_squared → percentage (already 0-1)
        description: `${displayName} factor: β=${betaValue.toFixed(2)}, R²=${(rSquared * 100).toFixed(1)}%`,
      };
    })
  : [];
```

If `factorSummary` is empty/undefined, render a "No factor data" message instead of the factor bars.

## Step 5: Frontend — Handle edge cases in rendering

### 5a. VaR/MaxDrawdown null display
In the Overview tab where these are rendered (lines 564-621), the current code already uses `?.toFixed(1) ?? 'N/A'` which handles null gracefully. Verify `0` displays as `0.0%` not `N/A`.

### 5b. Empty factor summary
When `riskFactors` array is empty, show a placeholder message in the Risk Factors tab:
```tsx
{riskFactors.length === 0 ? (
  <div className="text-sm text-neutral-500 text-center py-8">
    Factor analysis not available for this stock
  </div>
) : (
  // existing factor rendering
)}
```

### 5c. Sharpe ratio zero
Sharpe of 0 should display as `0.00` (valid value), not be hidden. Current rendering already handles this.

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `portfolio_risk_engine/risk_summary.py` | Add `max_drawdown` to `vol_metrics` in both analysis paths (simple + multi-factor) |
| `frontend/packages/connectors/src/adapters/StockAnalysisAdapter.ts` | Extend `StockRiskDisplayData` volatility_metrics + factor_summary types |
| `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` | Fix sharpe/maxDrawdown/correlation/VaR/vol scale mappings, pass factorSummary |
| `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` | Add factorSummary to type, replace hardcoded Risk Factors with real data |

## Verification

1. **Backend**: After adding `max_drawdown`, run `pytest tests/` to verify no regressions. Check `curl /api/direct/stock?ticker=AAPL` returns `volatility_metrics` with `sharpe_ratio`, `sortino_ratio`, and `max_drawdown` keys.
2. **Frontend build**: `cd frontend && pnpm typecheck && pnpm lint && pnpm build` — 0 errors
3. **Visual checks**:
   - Overview tab: Volatility shows correct percentage (e.g., "25.0%" not "0.2%")
   - VaR 95/99% shows reasonable daily values (typically 1-3% for most stocks), not inflated annual numbers
   - Sharpe ratio shows real value (not 1.2 fallback)
   - Max drawdown shows real historical value (not synthetic vol*2)
   - Correlation shows ~0.5-0.9 range for typical stocks (not raw R² which is 0.25-0.81)
   - Risk Factors tab shows real factor names (market, momentum, value, industry, subindustry) with real beta/R² values
4. **Edge cases**: Stock with no factor analysis (simple_market_regression only) — Risk Factors tab shows "not available" message
5. **Existing tests**: All passing
