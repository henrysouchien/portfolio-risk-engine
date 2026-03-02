# P2b: Factor Performance Attribution — Portfolio-Level Factor Return Decomposition

**Date**: 2026-02-28
**Status**: COMPLETE — Verified end-to-end in Chrome 2026-02-28. Min observations lowered 12→6 for shorter-lived portfolios.
**Parent**: TODO.md P2b, `FRONTEND_DATA_WIRING_AUDIT.md`

## Context

P2 (sector + security attribution) is complete and verified in Chrome. The `PerformanceView` attribution section has three tabs: sectors (working), factors (empty `[]`), security (working). This plan fills in the factor attribution gap.

The risk pipeline already computes per-stock factor betas via `compute_factor_exposures()` (per-stock OLS regressions against market/momentum/value/industry/commodity proxies). Rather than duplicating that expensive per-stock work in the performance pipeline, we'll run a single **portfolio-level multivariate OLS regression** of portfolio returns against standard factor returns. This is cheaper, self-contained, and gives the standard Fama-French style decomposition.

**Goal**: Decompose portfolio returns into factor contributions (market, momentum, value) and thread through to the frontend.

---

## What Already Exists

### Backend — Factor Infrastructure
- `compute_factor_exposures()` in `portfolio_risk.py` (line 872) — per-stock factor regressions. Returns `portfolio_factor_betas`, `df_stock_betas`, etc. Runs in risk pipeline only.
- **`compute_multifactor_betas(stock_returns, factor_df)`** in `factor_utils.py` (line 540) — multivariate OLS with HAC standard errors, VIF diagnostics, condition number. Returns `{betas, alpha, r2, r2_adj, t, p, std_err, resid, vif, cond_number}`. **Reuse this** instead of raw `sm.OLS`.
- `fetch_excess_return(etf, market, ...)` in `factor_utils.py` (line 226) — computes ETF - market excess returns. Used for momentum (MTUM) and value (IWD).
- `fetch_monthly_total_return_price(ticker, ...)` in `data_loader.py` (line 180) — total-return price series with fallback to close.
- `calc_monthly_returns(prices)` — standard monthly return calculation.
- Standard factor proxies used across all portfolios: `SPY` (market), `MTUM` (momentum), `IWD` (value).

### Backend — Performance Pipeline
- `calculate_portfolio_performance_metrics()` in `portfolio_risk.py` (line 1584) already has:
  - `df_ret`: per-ticker monthly returns DataFrame
  - `filtered_weights`: portfolio weights by ticker
  - `port_ret` / `bench_ret`: aligned portfolio and benchmark return series
  - `start_date`, `end_date`, `fmp_ticker_map` in scope
- `PerformanceResult` in `core/result_objects/performance.py` — already has `sector_attribution` and `security_attribution` fields. No `factor_attribution` yet.

### Frontend
- `PerformanceAdapter.ts` line ~805: `factors: []` — hardcoded empty array
- `PerformanceViewContainer.tsx` line ~305: passes `attribution.factors` through (gets `[]`)
- `PerformanceView.tsx` line ~223: type `factors?: Array<{ name: string; contribution: number }>` — defined but no rendering code
- No UI rendering for factors exists yet — only sectors and security have card rendering

---

## Implementation Plan

### Step 1: Add `_compute_factor_attribution()` to `portfolio_risk.py`

**File**: `portfolio_risk_engine/portfolio_risk.py`

New helper function near the existing `_compute_sector_attribution()`:

```python
def _compute_factor_attribution(
    port_ret: pd.Series,
    start_date: str,
    end_date: str,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Portfolio-level factor return attribution via multivariate OLS.

    Regresses portfolio returns against standard factor returns (market, momentum, value)
    to decompose total return into factor contributions.

    Monthly contribution_t = beta_i × factor_return_i,t
    Period contribution = sum of monthly contributions (arithmetic)
    Selection & Other = total_return - sum(factor_contributions) - intercept_contribution
    """
    # 1. Fetch factor return series independently (keep available subset on failure):
    #    - Market: calc_monthly_returns(fetch_monthly_total_return_price("SPY", ...))
    #    - Momentum: fetch_excess_return("MTUM", "SPY", ...)
    #    - Value: fetch_excess_return("IWD", "SPY", ...)
    #    Wrap each in try/except — if one fails, continue with remaining factors.

    # 2. Align all series to port_ret index, build factor DataFrame
    #    Require at least 1 factor and min_observations_for_factor_attribution (12) months.

    # 3. Run multivariate OLS using compute_multifactor_betas() from factor_utils.py
    #    This handles HAC standard errors, VIF diagnostics, condition number.
    #    Returns: {betas, alpha (intercept), r2, r2_adj, resid, vif, cond_number}

    # 4. Compute monthly factor contributions: beta_i × factor_return_i,t for each month
    #    Sum monthly contributions to get period contribution per factor (arithmetic sum).
    #    This avoids geometric-linking issues with excess-return factors.

    # 5. Intercept contribution = alpha (monthly intercept) × n_months
    #    Factor return (for display) = cumulative factor return over period × 100

    # 6. Selection & Other = total_portfolio_return - sum(factor_contributions) - intercept
    #    Label as "Selection & Other" (captures stock selection + unmodeled factors + linking error)

    # 7. Return list sorted by |contribution| descending:
    #    [{"name": "Market", "beta": 0.85, "return": 18.5, "contribution": 15.7}, ...]
    #    Include selection as: {"name": "Selection & Other", "beta": null, ...}
```

**Factor definitions** (hardcoded defaults — same proxies used throughout codebase):

| Factor | Display Name | Proxy | Return Type |
|--------|-------------|-------|-------------|
| market | Market | SPY | Total return |
| momentum | Momentum | MTUM | Excess (MTUM - SPY) |
| value | Value | IWD | Excess (IWD - SPY) |
| selection | Selection & Other | — | Residual (total - factor contributions - intercept) |

**Why only 3 factors + selection**: Market/momentum/value are the universal factors applied to all stocks. Industry and commodity are stock-specific (industry ETF varies per ticker) — they don't have a single portfolio-level proxy. Interest rate is bond-only. These 3 cover the standard Fama-French decomposition.

**Min observations**: Add `min_observations_for_factor_attribution: 12` to `DATA_QUALITY_THRESHOLDS` in `config.py`. The existing `min_observations_for_regression` is only 3 (too low for meaningful factor attribution). 12 months gives a reasonable minimum for OLS with 3 factors. If insufficient data, return empty list (frontend handles gracefully).

**Partial factor failure**: Fetch each factor independently in its own try/except. If one factor (e.g., MTUM) fails, continue with available factors. Require at least 1 factor to proceed.

Call in `calculate_portfolio_performance_metrics()` after sector/security attribution (~line 1770):
```python
try:
    performance_metrics["factor_attribution"] = _compute_factor_attribution(
        port_ret=port_ret,
        start_date=start_date,
        end_date=end_date,
        fmp_ticker_map=fmp_ticker_map,
    )
except Exception:
    performance_metrics["factor_attribution"] = []
```

### Step 2: Thread through `PerformanceResult`

**File**: `core/result_objects/performance.py`

Add field after `security_attribution` (~line 122):
```python
factor_attribution: Optional[List[Dict[str, Any]]] = None
```

Update `to_api_response()` to include:
```python
"factor_attribution": self.factor_attribution,
```

Update `from_core_analysis()` to extract:
```python
factor_attribution=data.get("factor_attribution"),
```

### Step 3: Map in `PerformanceAdapter.ts`

**File**: `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts`

**Step 3a**: Add `factor_attribution` to the `PerformanceResult` input interface (~line 218):
```typescript
factor_attribution?: Array<{
  name: string;
  beta: number | null;
  return: number;
  contribution: number;
}>;
```

**Step 3b**: Update `PerformanceData.performanceSummary.attribution.factors` output type (~line 331) from `{name, contribution}` to:
```typescript
factors: Array<{ name: string; beta: number | null; return: number; contribution: number }>;
```

**Step 3c**: Replace `factors: []` in `transformPerformanceSummary()` (~line 805):
```typescript
factors: (performance.factor_attribution || []).map(f => ({
  name: f.name,
  beta: f.beta ?? null,
  return: f.return ?? 0,
  contribution: f.contribution ?? 0,
})),
```

### Step 4: Widen factor type in container + view

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`

Update factors type in `PerformanceDataLike` and `MappedPerformanceViewData` (~lines 107, 136):
```typescript
factors?: Array<{ name: string; beta: number | null; return: number; contribution: number }>;
```

**File**: `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

Update factors type in attribution interface (~line 223):
```typescript
factors?: Array<{ name: string; beta: number | null; return: number; contribution: number }>;
```

### Step 5: Add factor attribution rendering in `PerformanceView.tsx`

**File**: `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

Add a factor attribution section within the Attribution tab content (after sector cards, ~line 1300). Pattern: similar to sector cards but simpler — show factor name, beta, factor return, and contribution.

```tsx
{/* Factor Attribution Section */}
{data?.attribution?.factors && data.attribution.factors.length > 0 && (
  <div className="mt-6">
    <h4 className="text-sm font-semibold mb-3">Factor Attribution</h4>
    <div className="space-y-2">
      {data.attribution.factors.map((factor) => (
        <div key={factor.name} className="flex items-center justify-between p-3 rounded-lg bg-gray-50">
          <div>
            <span className="font-medium">{factor.name}</span>
            {factor.beta != null && (
              <span className="text-xs text-gray-500 ml-2">β {factor.beta.toFixed(2)}</span>
            )}
          </div>
          <div className="text-right">
            <span className={`font-semibold ${factor.contribution >= 0 ? 'text-green-600' : 'text-red-500'}`}>
              {factor.contribution >= 0 ? '+' : ''}{factor.contribution.toFixed(2)}%
            </span>
            <span className="text-xs text-gray-500 ml-1">contribution</span>
          </div>
        </div>
      ))}
    </div>
  </div>
)}
```

No fallback mock data needed — if empty, section simply doesn't render.

---

## Files Modified

| File | Action |
|------|--------|
| `portfolio_risk_engine/portfolio_risk.py` | **Edit** — add `_compute_factor_attribution()`, call in `calculate_portfolio_performance_metrics()` |
| `portfolio_risk_engine/config.py` | **Edit** — add `min_observations_for_factor_attribution: 12` to `DATA_QUALITY_THRESHOLDS` |
| `core/result_objects/performance.py` | **Edit** — add `factor_attribution` field + `to_api_response()` + `from_core_analysis()` |
| `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` | **Edit** — add `factor_attribution` to input interface, update output type, map in `transformPerformanceSummary()` |
| `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` | **Edit** — widen factor type, add factor rendering section |
| `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` | **Edit** — widen factor type in interfaces |
| `tests/core/test_portfolio_risk.py` | **Edit** — add tests for `_compute_factor_attribution()` |

No new files.

---

## Key Design Decisions

1. **Portfolio-level regression, not per-stock**: One multivariate OLS on `port_ret` vs 3 factor series. Much cheaper than running `compute_factor_exposures()` (which does per-stock regressions). Standard Fama-French approach.

2. **Reuse `compute_multifactor_betas()`**: Existing utility in `factor_utils.py` (line 540) handles HAC standard errors, VIF diagnostics, and condition number. No raw `sm.OLS` needed.

3. **Monthly contribution aggregation**: Compute `beta_i × factor_return_i,t` per month, then sum across months. This avoids geometric-linking issues when using excess-return factors (MTUM-SPY, IWD-SPY). More accurate than `beta × cumulative_factor_return`.

4. **Hardcoded factor proxies (SPY/MTUM/IWD)**: Same proxies used across all portfolios in `stock_factor_proxies`. No need to pass proxy config — keeps performance pipeline independent from risk pipeline.

5. **"Selection & Other" not "Alpha"**: The residual captures stock selection skill + unmodeled factors + linking error + intercept. Labeling it "Alpha" would overstate precision. "Selection & Other" is more honest.

6. **Graceful partial failure**: Each factor fetched independently. If MTUM fails but SPY and IWD succeed, regression runs with 2 factors. Only fail entirely if zero factors available or insufficient observations.

7. **Dedicated observation threshold**: New `min_observations_for_factor_attribution: 12` in config. The existing `min_observations_for_regression` is 3 (too low for 3-factor OLS).

8. **No industry/commodity/interest_rate factors**: These are stock-specific or asset-class specific — no single portfolio-level proxy. Market/momentum/value are the universal factors.

9. **No fallback mock data**: Unlike sectors, factors have no pre-existing hardcoded mock. If regression fails, return empty array — section doesn't render.

10. **Enriched factor type shape**: `{name, beta, return, contribution}` — richer than the existing minimal `{name, contribution}` type. Beta and factor return provide valuable context for users.

---

## Verification

1. **Python unit test** (`tests/core/test_portfolio_risk.py`):
   - `test_compute_factor_attribution_returns_betas_and_contributions()`: Mock factor fetchers, verify output shape `{name, beta, return, contribution}`, verify contributions sum to ~total return (within "Selection & Other" residual)
   - `test_compute_factor_attribution_partial_factor_failure()`: Mock one factor fetch to raise, verify remaining factors still returned
   - `test_compute_factor_attribution_insufficient_data()`: Portfolio with < 12 months → verify empty list returned
2. **Integration test**: Call `calculate_portfolio_performance_metrics()`, verify `factor_attribution` key in output
3. **TypeScript**: `npx tsc --noEmit` passes for all three packages
4. **Chrome visual test**: Navigate to Performance view → Attribution tab, verify factor cards display with real betas and contributions
5. **Sanity check**: Sum of all factor contributions + "Selection & Other" should approximately equal total portfolio return
