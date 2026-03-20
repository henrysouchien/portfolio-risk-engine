# Fix Stress Test Impact — Per-Stock Weighted Factor Stress

## Context

The Stress Tests tab shows raw worst-month proxy returns as portfolio impacts (e.g., Industry: -53.4%). This is the raw worst monthly return of one industry proxy (SLV), not a portfolio-level impact. SLV is a small position — the portfolio would barely feel a silver crash.

## Formula

```
factor_stress_impact[ftype] = leverage × Σ (weight_i × beta_i[ftype] × worst_loss_of_proxy_i[ftype])
```

Where for each stock i:
- `weight_i` = normalized portfolio weight (from allocations, sums to ~1.0)
- `beta_i[ftype]` = stock's factor beta estimated against its own proxy (from `df_stock_betas`)
- `worst_loss_of_proxy_i[ftype]` = worst monthly return of THAT STOCK's proxy (from `worst_per_proxy`)
- `leverage` = portfolio leverage ratio (from `summary["leverage"]`)

For market/momentum/value (shared proxy), this reduces to `leverage × portfolio_beta × worst_loss`.
For industry (per-stock proxies), each stock contributes its own proxy's worst loss weighted by its own beta and position size.

**Known limitation — momentum/value betas**: These betas are estimated on excess-return factor series (ETF - market), but shocks use raw ETF worst months. This mismatch is pre-existing in the codebase and out of scope for this change.

**List-valued proxies (peer groups)**: Only `subindustry` uses list proxies in production configs. Industry proxies are always scalar strings. The function will skip list-valued proxies (contribute 0) rather than incorrectly pair a peer-median beta with an individual constituent's worst loss. This is documented in the code.

## Date Display

With per-stock weighted impacts, there is no single "worst month" — each stock's proxy may have crashed in a different month. The current `worst_factor_dates` (single proxy's worst month) becomes misleading.

**Fix**: Replace `Worst month: Mar 2020` with the lookback window: `10Y lookback`. This honestly communicates that the stress test uses worst monthly returns from within the lookback period without claiming a specific date.

For the High Volatility Scenario (synthetic, no historical data): continue showing `Synthetic scenario`.

## Missing Data Handling

Missing proxy loss, missing beta, or missing proxy config should NOT silently reduce stress to 0. Instead:
- The function returns both `impact` and `coverage` (fraction of portfolio weight with valid data)
- Frontend can display a warning if coverage is low (e.g., < 80%)
- Return shape: `{factor_type: {"impact": float, "coverage": float}}`

## Changes

### 1. Backend: `portfolio_risk_engine/risk_helpers.py`

**Add new function** `compute_factor_stress_impacts()`:

```python
def compute_factor_stress_impacts(
    stock_factor_proxies: Dict[str, Dict[str, Union[str, List[str]]]],
    worst_per_proxy: Dict[str, float],
    df_stock_betas: pd.DataFrame,
    portfolio_weights: Dict[str, float],
    leverage: float = 1.0,
) -> Dict[str, Dict[str, float]]:
    """
    Compute position-weighted stress impact per factor type.

    Returns: {factor_type: {"impact": decimal, "coverage": 0.0-1.0}}
    """
```

Logic per factor_type:
- Derive factor types dynamically from `stock_factor_proxies` values (not hardcoded)
- For each ticker in portfolio_weights:
  - Get proxy from `stock_factor_proxies[ticker][ftype]`
  - If proxy is a list → skip (beta was estimated on peer-median, no matching shock available)
  - If proxy is a string → `proxy_worst = worst_per_proxy.get(proxy)`
  - If proxy_worst is None → ticker is "uncovered", add weight to uncovered total
  - Get beta from `df_stock_betas.loc[ticker, ftype]` (NaN → 0.0)
  - Accumulate `weight × beta × proxy_worst`
- Multiply total impact by `leverage`
- `coverage = covered_weight / total_weight`

### 2. Backend: `core/portfolio_analysis.py`

After line 242 where `result` is constructed (so `historical_analysis` is mutable on it):

```python
from portfolio_risk_engine.risk_helpers import compute_factor_stress_impacts

factor_stress_impacts = compute_factor_stress_impacts(
    stock_factor_proxies=config.get("stock_factor_proxies", {}),
    worst_per_proxy=historical_analysis.get("worst_per_proxy", {}),
    df_stock_betas=summary.get("df_stock_betas", pd.DataFrame()),
    portfolio_weights={
        str(t): float(row["Portfolio Weight"])
        for t, row in summary.get("allocations", pd.DataFrame()).iterrows()
        if "Portfolio Weight" in summary.get("allocations", pd.DataFrame()).columns
    },
    leverage=summary.get("leverage", 1.0),
)
result.historical_analysis["factor_stress_impacts"] = factor_stress_impacts
```

### 3. Frontend: `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts`

Add optional type in BOTH `historical_analysis` declarations (~lines 173 and 255):
```typescript
factor_stress_impacts?: Record<string, { impact: number; coverage: number }>;
```

### 4. Frontend: `frontend/packages/chassis/src/catalog/types.ts`

Add to the `historical_analysis` type (~line 130):
```typescript
factor_stress_impacts?: Record<string, { impact: number; coverage: number }>;
```

### 5. Frontend: `RiskAnalysisModernContainer.tsx`

**All-or-nothing fallback**: if `factor_stress_impacts` exists and has entries, use it for ALL factors. If missing or empty, fall back to raw proxy losses for ALL. Never mix.

```typescript
const histAnalysis = data?.historical_analysis as {
  worst_by_factor?: Record<string, [string, number]>;
  worst_factor_dates?: Record<string, string>;
  factor_stress_impacts?: Record<string, { impact: number; coverage: number }>;
} | undefined;

const stressImpacts = histAnalysis?.factor_stress_impacts;
const useWeightedImpacts = stressImpacts && Object.keys(stressImpacts).length > 0;
const worstDates = histAnalysis?.worst_factor_dates;
const analysisYears = histAnalysis?.analysis_period?.years;

// Inside the loop:
const impact = useWeightedImpacts
  ? (stressImpacts[factor]?.impact ?? 0)
  : loss;

tests.push({
  scenario: `${factor} Stress Test`,
  impact: impact * 100,
  probability: loss < -0.15 ? 0.1 : 0.05,
  worstDate: useWeightedImpacts
    ? undefined   // No single worst month for weighted composite
    : worstDates?.[factor],
  lookbackYears: useWeightedImpacts ? (analysisYears ?? 10) : undefined,
});
```

### 6. Frontend: `RiskAnalysis.tsx`

Update the stress test type and display:

```typescript
// Type
stressTests: Array<{
  scenario: string;
  impact: number;
  probability?: number;
  worstDate?: string;
  lookbackYears?: number;  // NEW
}>;

// Display
<p className="mt-1 text-xs text-muted-foreground">
  {test.worstDate
    ? `Worst month: ${formatYearMonth(test.worstDate)}`
    : test.lookbackYears
      ? `${test.lookbackYears}Y lookback`
      : 'Synthetic scenario'}
</p>
```

### 7. Frontend: `useRiskMetrics.ts`

Check if this hook derives stress data from `historical_analysis.worst_by_factor`. If so, update to also check `factor_stress_impacts`. If it only uses the data for a different purpose (risk score display), no change needed.

## What Does NOT Change

- `_fetch_single_proxy_worst()`, `get_worst_monthly_factor_losses()`, `aggregate_worst_losses_by_factor_type()`, `compute_max_betas()`, `calc_max_factor_betas()` — all unchanged
- `run_stress_test()` / `stress_testing.py` — unchanged
- `RiskAnalysisResult` dataclass fields — unchanged (`historical_analysis` is `Dict[str, Any]`)
- Formatters — unchanged (ignore unknown keys)
- `worst_by_factor`, `worst_per_proxy`, `worst_factor_dates` — all unchanged and still returned

## Files to Modify

| File | Change | Blast radius |
|------|--------|-------------|
| `portfolio_risk_engine/risk_helpers.py` | Add `compute_factor_stress_impacts()` | **Zero** — new function |
| `core/portfolio_analysis.py` | Call it after line 242, add to `historical_analysis` | **Low** — additive |
| `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts` | Add type in both declarations | **Zero** — additive |
| `frontend/packages/chassis/src/catalog/types.ts` | Add type | **Zero** — additive |
| `frontend/packages/ui/.../RiskAnalysisModernContainer.tsx` | Use weighted impacts (all-or-nothing) | **Low** |
| `frontend/packages/ui/.../RiskAnalysis.tsx` | Add `lookbackYears`, update display | **Low** |
| `frontend/packages/connectors/src/features/riskMetrics/hooks/useRiskMetrics.ts` | Check and update if needed | **Low** |

## Tests

1. **Backend** (`tests/core/test_portfolio_risk.py`):
   - `compute_factor_stress_impacts()` with known inputs → verify weighted sum
   - Single-proxy factor (market) → result = leverage × portfolio_beta × worst_loss
   - Per-stock proxy factor (industry) → each stock uses its own proxy
   - Missing proxy in `worst_per_proxy` → coverage < 1.0, impact excludes that stock
   - List-valued proxy → skipped, coverage reflects it
   - Leverage applied correctly

2. **Frontend** (`RiskAnalysis.test.tsx`):
   - `lookbackYears` present → displays "10Y lookback"
   - `worstDate` present → displays "Worst month: Mar 2020"
   - Neither → displays "Synthetic scenario"

## Verification

1. `pytest tests/core/test_portfolio_risk.py -k "factor_stress" --no-header -q` — new tests pass
2. `pytest tests/core/test_portfolio_risk.py --no-header -q` — no regressions
3. `npx tsc --noEmit --project packages/ui/tsconfig.json` — clean
4. `npx eslint packages/connectors/src/adapters/RiskAnalysisAdapter.ts packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx packages/ui/src/components/portfolio/RiskAnalysis.tsx` — lint clean
5. Browser: Factors → Stress Tests — Industry should be ~5% instead of 53%, shows "10Y lookback"
6. Backward compat: without backend restart, frontend shows raw proxy losses with dates (existing behavior)
