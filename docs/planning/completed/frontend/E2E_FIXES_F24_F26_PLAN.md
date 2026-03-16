# E2E Fixes — F24 + F26

## Context

Final two enhancements from the 2026-03-13 E2E audit. F24 enriches the sparse Income Projection card. F26 adds real factor t-statistics (currently hardcoded to 0).

---

## Fix 1: F24 — Enrich Income Projection card (Frontend only)

**Problem**: Dashboard Income Projection shows just 3 numbers (Annual Income, Monthly Rate, Est. Yield) with whitespace. The backend already returns much richer data that's being ignored.

**Data already available from resolver** (`income-projection` in `registry.ts`):
- `top_contributors[]` — ticker, annual_income, yield (top dividend payers)
- `income_by_frequency` — breakdown by Monthly/Quarterly/Annual payers
- `positions_with_dividends` / `positions_without_dividends` — coverage counts

**Approach**: Add a compact sub-section below the 3-stat row showing top 3 contributors. Minimal change, fills the whitespace meaningfully.

**Codex review corrections:**
- `income.top_contributors` does NOT exist — actual field is `income.positions[]` (array of `{ticker, annual_income, yield}`)
- `positions` is unsorted — must sort by `annual_income` descending, then slice top 3
- `yield` is already in percentage points (e.g., 3.1 = 3.1%) — do NOT multiply by 100
- Synthetic fallback doesn't have `positions` — guard with `?.length > 0`
- `income.metadata.positions_with_dividends` is valid on live data, absent in synthetic fallback

### File: `frontend/packages/ui/src/components/dashboard/cards/DashboardIncomeCard.tsx`

After the existing 3-column grid (line 60), add top contributors list:

```tsx
{/* After the grid-cols-3 div, before isEstimate check */}
{!resolved.loading && income?.positions?.length > 0 && (
  <div className="mt-4 space-y-2">
    <p className="text-xs font-medium uppercase tracking-wider text-neutral-500">Top Contributors</p>
    {[...income.positions]
      .filter((p: { annual_income?: number }) => (p.annual_income ?? 0) > 0)
      .sort((a: { annual_income: number }, b: { annual_income: number }) => b.annual_income - a.annual_income)
      .slice(0, 3)
      .map((c: { ticker: string; annual_income: number; yield?: number }) => (
        <div key={c.ticker} className="flex items-center justify-between text-sm">
          <span className="font-medium text-neutral-700">{c.ticker}</span>
          <div className="flex items-center gap-3">
            <span className="text-neutral-900">{formatCurrency(c.annual_income)}/yr</span>
            {c.yield != null && c.yield > 0 && (
              <span className="text-xs text-neutral-500">{c.yield.toFixed(1)}%</span>
            )}
          </div>
        </div>
      ))}
  </div>
)}
```

Also add dividend coverage indicator:
```tsx
{!resolved.loading && income?.metadata?.positions_with_dividends != null && (
  <p className="mt-2 text-xs text-neutral-400">
    {income.metadata.positions_with_dividends} of {(income.metadata.positions_with_dividends ?? 0) + (income.metadata.positions_without_dividends ?? 0)} holdings pay dividends
  </p>
)}
```

**No new imports needed** — all data comes from the existing `income` object via `useDataSource('income-projection')`.

---

## Fix 2: F26 — Factor t-statistics (Backend + Frontend)

**Problem**: Research page shows t-stat: 0.00 for every factor. `FactorRiskModelContainer.tsx` hardcodes `tStat: 0` (line 208).

**Root cause**: `compute_factor_exposures()` in `portfolio_risk.py` computes portfolio-level betas by weighted-averaging stock-level betas (line 1580), but never runs a portfolio-level regression. T-stats require regression diagnostics.

**Key insight**: `compute_multifactor_betas()` in `factor_utils.py` (lines 536-618) already runs full OLS with HAC covariance and returns `{'t': {factor: float}, 'p': {...}, ...}`. It's already used for rate factors (line 1390). We just need to also run it for the main factors at portfolio level.

**Codex review corrections:**
- `factor_df` is NOT available at line 1580 — it's a temporary loop local, gone by then
- `df_ret` IS available (function parameter) — holds per-ticker returns
- Must accumulate `factor_df` during the per-ticker loop or reconstruct it from `df_stock_betas` columns
- Frontend needs adapter plumbing: `RiskAnalysisAdapter.ts` must preserve `portfolio_factor_tstats`
- Significance badge should use t-stat thresholds (|t| > 2.0 = significant), not just beta magnitude
- `RiskAnalysisResult.from_core_analysis()` must also populate the new field (not just `to_api_response()`)

### Backend Changes

**File: `portfolio_risk_engine/portfolio_risk.py`** — `compute_factor_exposures()` (around line 1580)

1. **Accumulate factor data** during the per-ticker factor loop. The function iterates over tickers and builds `df_stock_betas`. During this loop, `factor_df` is computed per-ticker as a temporary. We need to save a union of all factor columns into a persistent `all_factors_df` that survives the loop.

2. After computing `portfolio_factor_betas` (line 1580), run portfolio-level OLS:

```python
# Build portfolio return series
port_ret = df_ret.mul(w_series, axis=1).sum(axis=1)

# Run multivariate OLS against accumulated factors
portfolio_factor_tstats = pd.Series(dtype=float)
try:
    if not port_ret.empty and all_factors_df is not None and not all_factors_df.empty:
        aligned_port = port_ret.reindex(all_factors_df.index).dropna()
        aligned_factors = all_factors_df.reindex(aligned_port.index).dropna()
        if len(aligned_port) >= 12:  # Minimum observations for meaningful regression
            ols_result = compute_multifactor_betas(aligned_port, aligned_factors, hac_lags=3)
            portfolio_factor_tstats = pd.Series(ols_result.get('t', {}), dtype=float)
except Exception:
    pass  # Graceful fallback
```

3. Add to return dict:
```python
"portfolio_factor_tstats": portfolio_factor_tstats,
```

**File: `core/result_objects/risk.py`** — `RiskAnalysisResult`

- Add `portfolio_factor_tstats: Optional[Dict[str, float]]` dataclass field
- Include in `to_api_response()` (serialize alongside `portfolio_factor_betas`)
- Include in `from_core_analysis()` (read from `portfolio_summary`)
- Include in `get_agent_snapshot()`

### Frontend Changes

**File: `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts`**

Preserve `portfolio_factor_tstats` in the transform output (same pattern as `portfolio_factor_betas` at line ~603).

**File: `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx`**

Line 208: Replace hardcoded 0:
```typescript
// Before
tStat: 0,
// After
tStat: riskData?.portfolio_factor_tstats?.[canonical] ?? 0,
```

Lines 106-111: Update `significanceFromBeta` to use t-stats when available:
```typescript
const significanceFromTStat = (tStat: number): string => {
  const abs = Math.abs(tStat);
  if (abs > 2.58) return 'High';    // 99% significance
  if (abs > 1.96) return 'Medium';  // 95% significance
  return 'Low';
};
```

---

## Verification

1. **F24**: Dashboard Income card shows top 3 contributors below the 3-stat row. Shows dividend coverage count. Synthetic fallback shows no contributors (graceful).
2. **F26**: Research → Factor Risk Model → t-stat column shows real values (not all 0.00). Significance badges reflect statistical significance (|t| > 1.96 = Medium, > 2.58 = High).
3. Backend: `python3 -m pytest tests/ -x -q -k "factor or portfolio_risk"`
4. Frontend: `cd frontend && npx vitest run`

## Files Modified

| File | Fix |
|------|-----|
| `frontend/.../cards/DashboardIncomeCard.tsx` | F24: Add top contributors + coverage |
| `portfolio_risk_engine/portfolio_risk.py` | F26: Accumulate factor_df, portfolio-level OLS |
| `core/result_objects/risk.py` | F26: Add portfolio_factor_tstats field |
| `frontend/.../adapters/RiskAnalysisAdapter.ts` | F26: Preserve portfolio_factor_tstats |
| `frontend/.../views/modern/FactorRiskModelContainer.tsx` | F26: Read t-stats, update significance |
