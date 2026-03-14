# Plan: Performance Backend Gaps — P6 Final

**Date:** 2026-03-05
**Status:** ✅ COMPLETE — commits `58425197`, `4949842b`, `abaef8b9`
**Supersedes:** Previous "4 Fixes" plan (✅ COMPLETE 2026-03-04, commit `592256c9`)

## Context

Three remaining frontend-backend gaps from the cleanup audit (P6 tier). The `data_availability` gap was confirmed as not-a-real-gap (those fields are correctly `false` in realized mode — hypothetical-only concepts).

---

## 1. Realized Benchmark Key Mismatch (Bug Fix)

**Problem:** `to_api_response()` in `RealizedPerformanceResult` extracts `benchmark_monthly_returns` from `_postfilter`, but uses the **full unfiltered** key. Meanwhile `monthly_returns` in the response is the **selected/filtered** window. Date keys don't match → adapter lookup returns 0 for every month → flat benchmark line.

**Note:** Commit `a2cce363` partially fixed this (wired benchmark from `_postfilter` instead of nowhere) but still reads the wrong key at line 645.

**File:** `core/result_objects/realized_performance.py` — `to_api_response()` (line 645)

**Fix:** Change line 645 to use `selected_benchmark_monthly_returns`:

```python
benchmark_monthly = postfilter.get("selected_benchmark_monthly_returns") or postfilter.get("benchmark_monthly_returns") or {}
```

Fallback to unselected for backward compatibility with older cached results.

---

## 2. 1D/1W Period Returns (New Feature)

**Problem:** Performance engine only has monthly return series. No 1D/1W returns exist. Frontend period selector can't show these.

**Approach:** Standalone `compute_recent_returns()` function that fetches last ~14 days of daily prices for portfolio tickers + benchmark, computes weighted 1D and 1W returns. Called from service layer, merged into performance result. Keeps the monthly engine untouched.

### Step 2a. Backend: New `compute_recent_returns()` function

**File:** `portfolio_risk_engine/performance_metrics_engine.py` — add after `compute_performance_metrics()`

```python
def compute_recent_returns(
    weights: Dict[str, float],
    benchmark_ticker: str = "SPY",
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Optional[float]]:
```

- For each ticker, call `fetch_daily_close(ticker, start_date=today-14d)` (exists in `fmp/compat.py:323`)
- Compute daily returns, weight-average across portfolio
- 1D = last trading day's weighted return; 1W = compound of last 5 trading days
- Same for benchmark
- Return dict with `last_day_return`, `last_week_return`, `last_day_benchmark_return`, `last_week_benchmark_return` — all in percent (matching `last_month_return` convention)
- Return `None` for any value that can't be computed (weekend, missing data)

### Step 2b. Backend: Call from `calculate_portfolio_performance_metrics()`

**File:** `portfolio_risk_engine/portfolio_risk.py` — `calculate_portfolio_performance_metrics()` (line 1755)

This is where `compute_performance_metrics()` is called (line 1886) and the `performance_metrics` dict is assembled. After the existing `compute_performance_metrics()` call at line 1886, call `compute_recent_returns(weights, benchmark_ticker, fmp_ticker_map)` and merge into `performance_metrics["returns"]`:

```python
# After line 1894 (performance_metrics = compute_performance_metrics(...))
try:
    from portfolio_risk_engine.performance_metrics_engine import compute_recent_returns
    recent = compute_recent_returns(filtered_weights, benchmark_ticker, fmp_ticker_map)
    performance_metrics.setdefault("returns", {}).update(recent)
except Exception:
    pass  # Daily returns are best-effort
```

### Step 2c. Frontend: Adapter adds new period entries

**File:** `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` — `transformPerformanceSummary()` (line 789)

**Post-refactor state:** Commit `fa3ddc75` already removed the dead 1D/1W zero placeholders. The `periods` object now only has `"1M"` and `"1Y"` keys. Add `"1D"` and `"1W"` entries **conditionally** (only when backend provides data):

```typescript
const periods: Record<string, any> = {
  "1M": { ... },  // existing
  "1Y": { ... },  // existing
};

// Add 1D/1W only when backend provides daily return data
if (performance.returns.last_day_return != null) {
  periods["1D"] = {
    portfolioReturn: performance.returns.last_day_return,
    benchmarkReturn: performance.returns.last_day_benchmark_return ?? null,
    activeReturn: performance.returns.last_day_return - (performance.returns.last_day_benchmark_return ?? 0),
    volatility: performance.risk_metrics.volatility
  };
}
if (performance.returns.last_week_return != null) {
  periods["1W"] = {
    portfolioReturn: performance.returns.last_week_return,
    benchmarkReturn: performance.returns.last_week_benchmark_return ?? null,
    activeReturn: performance.returns.last_week_return - (performance.returns.last_week_benchmark_return ?? 0),
    volatility: performance.risk_metrics.volatility
  };
}
```

### Step 2d. Frontend: Container supports new period keys

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — line 507

**Post-refactor state:** `supportedKeys` is currently `['1M', '1Y', 'YTD']` (commit `fa3ddc75`). Change to `['1D', '1W', '1M', '1Y', 'YTD']`.

---

## 3. Hedging VaR/Cost/Beta → Backend (Architecture Fix)

**Problem:** `expectedCost`, `beforeVaR`, `afterVaR`, `portfolioBeta` are computed client-side in a `useMemo` in `RiskAnalysisModernContainer.tsx` (~lines 314-374). This creates a race condition: hedging data arrives before risk data → values stay at 0/N/A permanently. The adapter also hardcodes these to `0` / `'N/A'` (`HedgingAdapter.ts:151-161`).

**Key insight:** The hedging service (`recommend_portfolio_offsets()` in `services/factor_intelligence_service.py:1023`) already calls `build_portfolio_view()` at line 1113, which returns `portfolio_returns` (monthly return series), `variance_decomposition.portfolio_variance`, and `portfolio_factor_betas`. All inputs for VaR are already computed — just not surfaced. We compute VaR/cost/beta **entirely on the backend** using **empirical (historical) VaR** and return them as fields in the API response. No client-side math needed.

**Why empirical VaR:** Parametric VaR assumes normally distributed returns and underestimates tail risk. Empirical VaR uses the 5th percentile of actual portfolio returns — no distribution assumption, captures fat tails and correlation blow-ups. The portfolio return series is already available from `build_portfolio_view()` at no extra cost.

### Step 3a. Backend: Add `portfolio_value` to request model

**File:** `models/factor_intelligence_models.py` — `PortfolioOffsetRecommendationRequest`

Add: `portfolio_value: Optional[float] = None`

### Step 3b. Backend: Compute VaR/cost/beta in hedging service

**File:** `services/factor_intelligence_service.py` — `recommend_portfolio_offsets()` (line 1196)

After building `view` (line 1113) and `recs` (line 1194), compute the hedging metrics and add to `analysis_metadata`. `market_beta` is already extracted at lines 1150-1158 — reuse that variable:

```python
# --- Compute hedging risk metrics from portfolio view ---
import numpy as np

portfolio_value = data.portfolio_value  # from request model
port_ret = view.get("portfolio_returns")  # pd.Series of monthly returns (already computed)

# Empirical VaR: 5th percentile of actual monthly portfolio returns, scaled to daily
# Monthly → daily scaling: divide by sqrt(21 trading days)
before_var = None
monthly_var_pct = None
if port_ret is not None and len(port_ret) >= 6 and portfolio_value:
    monthly_var_pct = float(np.percentile(port_ret.dropna(), 5))  # e.g., -0.032 = -3.2%
    daily_var_pct = monthly_var_pct / np.sqrt(21)
    before_var = round(abs(daily_var_pct) * portfolio_value, 2)  # positive dollar amount

# Annual volatility for metadata (from factor model)
portfolio_variance = (view.get("variance_decomposition") or {}).get("portfolio_variance")
annual_vol = round(float(np.sqrt(portfolio_variance)) * 100, 2) if portfolio_variance else None

# Per-recommendation: expected cost, risk reduction, and after-VaR
for rec in recs:
    sw = rec.get("suggested_weight", 0)
    rec["expected_cost"] = round(portfolio_value * sw, 2) if portfolio_value else None
    # risk_reduction derived from |correlation| (same as frontend adapter line 137)
    corr = abs(float(rec.get("correlation", 0) or 0))
    rr = round(corr * 100)
    rec["risk_reduction"] = rr
    rec["before_var"] = before_var
    rec["after_var"] = round(before_var * (1 - rr / 100), 2) if before_var and rr else before_var

analysis_metadata = {
    "start_date": dates["start"],
    "end_date": dates["end"],
    "driver_count": len(drivers),
    "weights_count": len(data.weights),
    "portfolio_value": portfolio_value,
    "annual_volatility": annual_vol,
    "market_beta": round(market_beta, 3) if market_beta is not None else None,
    "before_var": before_var,
    "var_method": "empirical_5pct",
    "var_horizon": "daily",
    "var_observations": len(port_ret) if port_ret is not None else 0,
}
```

**Notes:**
- `port_ret` is `view["portfolio_returns"]` — the monthly return series already computed by `build_portfolio_view()` (line 1724 in `portfolio_risk.py`)
- Minimum 6 months required for meaningful empirical VaR
- Monthly→daily scaling via `sqrt(21)` (square-root-of-time rule) — standard for risk reporting
- `var_method` / `var_horizon` / `var_observations` in metadata for transparency

These flow through `PortfolioOffsetRecommendationResult.analysis_metadata` → `to_api_response()` automatically (already passes through as `Dict[str, Any]`).

### Step 3c. Frontend: Pass portfolioValue in hook

**File:** `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts`

Extend hook to accept `portfolioValue?: number` and include it in the API request body as `portfolio_value`.

### Step 3d. Frontend: Adapter reads pre-computed fields

**File:** `frontend/packages/connectors/src/adapters/HedgingAdapter.ts` (lines 148-163)

Replace the hardcoded values with reads from the backend response. Each recommendation now has `expected_cost`, `before_var`, `after_var`. `analysis_metadata.market_beta` provides portfolio beta:

```typescript
details: {
  description: `...`,
  riskReduction,
  expectedCost: bestRecommendation.expected_cost ?? 0,
  implementationSteps: [...],
  marketImpact: {
    beforeVaR: bestRecommendation.before_var != null ? `$${bestRecommendation.before_var.toLocaleString()}` : 'N/A',
    afterVaR: bestRecommendation.after_var != null ? `$${bestRecommendation.after_var.toLocaleString()}` : 'N/A',
    riskReduction: `${riskReduction}%`,
    portfolioBeta: analysisMetadata?.market_beta != null ? String(analysisMetadata.market_beta) : 'N/A',
  },
},
```

Note: `analysisMetadata` is read from the top-level API response `analysis_metadata` field and passed into the strategy mapping function.

### Step 3e. Frontend: Remove container enrichment useMemo

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx`

Delete the enrichment `useMemo` block (~lines 314-374, ~60 lines). The backend now provides all values.

---

## Files Modified

| # | File | Change |
|---|------|--------|
| 1 | `core/result_objects/realized_performance.py` | Fix benchmark key (~1 line) |
| 2 | `portfolio_risk_engine/performance_metrics_engine.py` | New `compute_recent_returns()` (~40 lines) |
| 3 | `portfolio_risk_engine/portfolio_risk.py` | Call `compute_recent_returns()` in `calculate_portfolio_performance_metrics()` (~5 lines) |
| 4 | `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` | Add 1D/1W periods (~12 lines) |
| 5 | `PerformanceViewContainer.tsx` | Extend `supportedKeys` (~1 line) |
| 6 | `models/factor_intelligence_models.py` | Add `portfolio_value` field (~1 line) |
| 7 | `services/factor_intelligence_service.py` | Compute VaR/cost/beta, add to `analysis_metadata` + per-rec fields (~20 lines) |
| 8 | `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts` | Pass portfolioValue (~3 lines) |
| 9 | `frontend/packages/connectors/src/adapters/HedgingAdapter.ts` | Read pre-computed fields instead of hardcoded values (~10 lines) |
| 10 | `RiskAnalysisModernContainer.tsx` | Remove enrichment useMemo (~-60 lines) |

## Verification

1. **Realized benchmark:** `get_performance(mode="realized")` via MCP — check `benchmark_monthly_returns` keys align with `monthly_returns` keys
2. **1D/1W returns:** `get_performance()` via MCP — check `returns.last_day_return` and `returns.last_week_return` are non-null floats
3. **Hedging VaR:** `get_factor_recommendations()` via MCP — check each recommendation has `expected_cost`, `before_var`, `after_var` as floats, and `analysis_metadata` has `market_beta` and `annual_volatility`
4. **Hedging UI:** Open Risk Analysis → Hedging tab in browser — verify real dollar amounts for VaR, real cost, real beta
5. `python -m pytest tests/ -k "performance or factor" --tb=short -q`
6. `pnpm typecheck`
