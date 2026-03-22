# Fix Risk Drivers: Replace Bivariate Correlation² with Multi-Factor Variance Attribution

## Context
The Risk Drivers card currently shows bivariate `correlation²` (from `compute_factor_metrics`) as "risk influence." This is misleading — it's not variance decomposition, the values overlap (sum to >100%), and correlation isn't causation. The codebase already has `compute_multifactor_betas()` in `factor_utils.py` which runs a proper joint OLS regression, but it's not called in the stock analysis path.

## Approach
1. Call `compute_multifactor_betas()` alongside `compute_factor_metrics()` in the stock analysis path
2. Compute per-factor variance contribution using exact additive decomposition from the multi-factor OLS
3. Thread the new data through to the frontend
4. The Risk Drivers card shows approximate risk share (clamped + renormalized to 100%)

## Variance Decomposition Method

Use **exact additive decomposition** from the multi-factor OLS:
```
y_hat = sum(beta_i × factor_i) + alpha     # fitted values from joint regression
contribution_i = beta_i × Cov(factor_i, y_hat) / Var(y)
```

This properly accounts for cross-factor correlations. The raw signed contributions sum with idiosyncratic to exactly 100%. However, some factor contributions can be negative (hedging/diversification effect).

**Backend stores raw signed values.** Frontend handles display:
- Clamp negative factor contributions to 0 (hedging factors aren't "risk drivers")
- Renormalize all displayed values (clamped factors + idiosyncratic) to sum to ~100% (rounding may produce 99-101%)
- Label as "approximate share of risk" — not "exact variance decomposition"

All computations must use the **same aligned sample** that the OLS used (complete-case intersection across all factors).

## Implementation

### Step 1: Add multi-factor call + variance decomposition to stock analysis
**File:** `portfolio_risk_engine/risk_summary.py` — `get_detailed_stock_factor_profile()` (~line 212)

The function currently returns a literal dict (line 209). Add variance attribution computation before the return:

```python
from portfolio_risk_engine.factor_utils import compute_multifactor_betas

# Actual signature: compute_multifactor_betas(stock_returns: pd.Series, factor_df: pd.DataFrame)
factor_df = pd.DataFrame(factor_dict)
multifactor_stats = compute_multifactor_betas(stock_returns, factor_df)

variance_attribution = None
if multifactor_stats.get("betas") and not multifactor_stats["resid"].empty:
    # Use the same aligned sample the regression used
    aligned = pd.concat([stock_returns, factor_df], axis=1).dropna()
    y = aligned.iloc[:, 0]
    fitted = y - multifactor_stats["resid"]
    stock_var = y.var()

    if stock_var > 0:
        factor_var_contrib = {}
        for factor_name in factor_df.columns:
            beta_mf = multifactor_stats["betas"].get(factor_name, 0)
            # Exact: beta_i × Cov(factor_i, fitted_values) / Var(y)
            cov_with_fitted = aligned[factor_name].cov(fitted)
            contrib = (beta_mf * cov_with_fitted) / stock_var
            factor_var_contrib[factor_name] = float(contrib)  # raw signed value — frontend handles clamping/renormalization

        # Idiosyncratic = residual variance / stock variance
        resid_var = multifactor_stats["resid"].var()
        factor_var_contrib["idiosyncratic"] = float(resid_var / stock_var)

        variance_attribution = factor_var_contrib

# Add to the return dict
return {
    "vol_metrics": vol_metrics,
    "regression_metrics": compute_regression_metrics(df_reg),
    "factor_summary": compute_factor_metrics(stock_returns, factor_dict),
    "variance_attribution": variance_attribution,  # None if regression failed
    "model_r2": multifactor_stats.get("r2", 0),
}
```

**Key points:**
- `compute_multifactor_betas(stock_returns, factor_df)` — two args: Series + DataFrame (not a single DataFrame)
- The function handles its own minimum-observation threshold internally (from `DATA_QUALITY_THRESHOLDS`)
- Backend stores raw signed contributions (may be negative for hedging factors) — frontend handles clamping + renormalization for display
- Idiosyncratic = `resid.var() / stock.var()` directly from OLS residuals
- If regression fails or has insufficient data, `variance_attribution` is None → frontend falls back to bivariate
- Top-3 display + idiosyncratic won't visually sum to ~100% (rounding may produce 99-101%) when there are 4-5 factors. Add an "Other" bucket: `other = sum(remaining factors beyond top 3)`. The card shows: Top 3 + Other + Company-Specific = ~100%

### Step 2: Thread through StockAnalysisResult
**File:** `core/result_objects/stock_analysis.py`

Add `variance_attribution` field to `StockAnalysisResult`:
- Store the dict from Step 1 (optional field, None/missing when unavailable)
- Expose in `to_api_response()` as `variance_attribution` — **only include the key when non-None** (omit entirely when unavailable, do not serialize as JSON null)
- Do NOT add to `get_agent_snapshot()` to avoid breaking existing exact-key test in `test_stock_agent_snapshot.py`

**File:** `portfolio_risk_engine/stock_analysis.py`

Pass `variance_attribution` from the profile to `StockAnalysisResult` (only when present in profile).

### Step 3: Update frontend data flow
**File:** `services/stock_service.py` — `enrich_stock_data()`

The `variance_attribution` will flow through the existing stock analysis API response via `to_api_response()`. The adapter already spreads `...data`, so no adapter changes needed.

**File:** `frontend/.../StockLookupContainer.tsx`

Map `variance_attribution` from the stock data into `selectedStock`:
```typescript
varianceAttribution: (stockRecord.variance_attribution && typeof stockRecord.variance_attribution === 'object')
  ? stockRecord.variance_attribution as Record<string, number>
  : undefined,  // guard against null/missing — do NOT pass null to children
```

**File:** `frontend/.../types.ts`

Add to selectedStock type:
```typescript
varianceAttribution?: Record<string, number>
```

### Step 4: Update the Risk Drivers card
**File:** `frontend/.../StockLookup.tsx`

Update `riskFactors` computation to use `varianceAttribution` when available.

**Frontend renormalization logic** (in StockLookup.tsx or RisksSignalsTab.tsx):
```typescript
if (!varianceAttribution) return fallbackBivariate  // guard null/undefined

// 1. Separate factors from idiosyncratic
const entries = Object.entries(varianceAttribution)
const idioRaw = varianceAttribution.idiosyncratic ?? 0
const factorEntries = entries.filter(([k]) => k !== "idiosyncratic")

// 2. Clamp negative factors to 0
const clamped = factorEntries.map(([name, val]) => [name, Math.max(0, val)])

// 3. Renormalize: clamped factors + idiosyncratic sum to ~100% (rounding may produce 99-101%)
const total = clamped.reduce((s, [, v]) => s + v, 0) + idioRaw
const normalize = (v: number) => total > 0 ? v / total : 0

// 4. Build riskFactors from normalized values
const riskFactors = clamped.map(([name, val]) => ({
  name: capitalize(name),
  risk: Math.round(normalize(val) * 100),
  ...
}))
const idiosyncraticPct = Math.round(normalize(idioRaw) * 100)
```

Pass both `riskFactors` and `idiosyncraticPct` to `RisksSignalsTab`.

**File:** `frontend/.../RisksSignalsTab.tsx`

Update the card subtitle from "Top factors driving this stock's risk" to "Approximate share of return variance" (honest about the approximation).

Add `idiosyncraticPct` prop. Render below the top-3 factor bars:
- If factors beyond top 3 exist: "Other Factors" row (sum of remaining, muted blue bar)
- "Company-Specific" row (idiosyncratic, neutral/gray bar, always last)
- Together: Top 3 + Other + Company-Specific ≈ 100%

Backend stores raw signed values. Frontend clamps negative factors to 0 then renormalizes so Top 3 + Other + Company-Specific = 100%. This is approximate risk share, not exact variance decomposition.

### Step 5: Update MCP tool
**File:** `mcp_tools/stock.py`

Add `variance_attribution` to the summary format:
```python
if hasattr(result, 'variance_attribution') and result.variance_attribution:
    summary["variance_attribution"] = result.variance_attribution
```

## Files Changed

| File | Changes |
|------|---------|
| `portfolio_risk_engine/risk_summary.py` | Add multi-factor regression call + exact variance decomposition |
| `core/result_objects/stock_analysis.py` | Add `variance_attribution` optional field, expose in `to_api_response()` |
| `portfolio_risk_engine/stock_analysis.py` | Pass variance_attribution to StockAnalysisResult |
| `frontend/.../types.ts` | Add `varianceAttribution` field |
| `frontend/.../StockLookupContainer.tsx` | Map `variance_attribution` |
| `frontend/.../StockLookup.tsx` | Use varianceAttribution for riskFactors + extract idiosyncratic |
| `frontend/.../RisksSignalsTab.tsx` | Add idiosyncraticPct prop, render Company-Specific row |
| `mcp_tools/stock.py` | Add variance_attribution to summary |

## Verification
1. `python3 -c "from mcp_tools.stock import analyze_stock; r = analyze_stock('AAPL', format='summary'); import json; va = r.get('variance_attribution', {}); print(json.dumps(va, indent=2)); print(f'Raw sum: {sum(va.values()):.4f}')"` — raw signed values should sum to ~1.0 (exact decomposition). Some factors may be negative.
2. Frontend: Risk Drivers shows top 3 factor bars + Other (if applicable) + "Company-Specific" row. After clamping + renormalization, displayed percentages sum to ~100% (rounding may produce 99-101%).
3. Compare: ordering may differ from bivariate correlation² — multi-factor attribution controls for factor overlap
4. Run existing tests: `pytest tests/core/test_stock_agent_snapshot.py tests/mcp_tools/test_stock_agent_format.py -q`
5. Add synthetic unit test: verify raw variance_attribution values sum to ~1.0 given known factor returns + stock returns
6. Add test in test_stock_agent_format.py: verify `variance_attribution` present in `format="summary"` output
7. Add test on `StockAnalysisResult.to_api_response()`: (a) verify `variance_attribution` key present when set, (b) verify key is OMITTED (not null) when unset/None
8. Extract frontend clamp/renormalize/top-3+Other logic into a testable helper function. Add unit tests for: negative contributions, fewer-than-3 factors, Other bucketing, fallback when varianceAttribution is undefined or null
9. Manual verification: run AAPL analysis and confirm raw sum ~1.0
