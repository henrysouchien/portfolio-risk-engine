# Scenario Analysis: Full Overhaul (5 Phases)

**Status**: COMPLETE — all 5 phases implemented
**Date**: 2026-03-03

## Context

The Scenario Analysis view has 5 tabs. Portfolio Builder works with real what-if data. Stress Tests tab is now wired to real backend APIs (Phase 1 complete). Historical tab is still disabled/placeholder. Monte Carlo is a placeholder. Optimizations tab shows what-if-derived suggestions but no real optimization data. No Monte Carlo engine exists.

**Goal:** Make all 5 tabs functional with real data, add scenario session history, and enable preset templates.

---

## Phase 1: Stress Test + Historical Frontend Wiring — ✅ COMPLETE

Implemented in commit `6644b810` (2026-03-03, "feat: wire stress test frontend — Phase 3 complete (Wave 3h)"). 776 insertions across 13 files.

- Query keys: `stressTestKey()`, `stressScenarioKey()` in `queryKeys.ts`
- API methods: `postStressTest()`, `getStressScenarios()`, `postStressTestRunAll()` in `APIService.ts`
- Cache: `getStressTest()` in `PortfolioCacheService.ts`
- Manager: `analyzeStressTest()` in `PortfolioManager.ts`
- Hooks: `useStressTest()` + `useStressScenarios()` with `StressTestAdapter`
- Container + component wired with real API data

---

## Phase 2: What-If Preset Templates (frontend only)

Replace 5 hardcoded inert templates with actionable presets derived from current portfolio.

### 2a. Template definitions

**`ScenarioAnalysisContainer.tsx`** — replace hardcoded templates with computed presets. **Important:** `initialPositions` (line ~374) strips `type` and `volatility` fields. Use upstream positions data from `usePositions()` (which includes `holding.type` and `holding.volatility` via `PositionsAdapter`) to compute templates:
- **Equal Weight**: all current non-cash positions get `1/N` weight (decimal, e.g. `0.05`). Cash positions excluded.
- **Conservative (60/40)**: classify via `holding.type` from positions data — bond/cash types get 60% total, equity types get 40% total. Weights within each class proportional to current weights. Normalize to sum=1.0.
- **Risk Parity**: weight = `(1/vol_i) / Σ(1/vol_j)`. Use `holding.volatility` from positions data (already enriched in Wave 2.5, available via `PositionsAdapter`). If vol missing, fall back to equal weight for that position.
- **Concentrated Growth**: top 5 positions by current weight, equally weighted at 20% each.
- **Hedge Overlay**: current weights unchanged + delta `{SPY: "-5%"}` (reduces equity beta).

All templates produce `new_weights` dict (decimal values, e.g. `{AAPL: 0.25}`). The what-if API accepts `scenario.new_weights` with decimal values. Templates call `runScenario()` from `useWhatIfAnalysis`.

**Note:** The current "Quick Actions" section in `ScenarioAnalysis.tsx` (line ~293, ~849, ~1138) uses mock/random behavior. Replace these with the real computed templates above.

### 2b. UI changes

**`ScenarioAnalysis.tsx`** — Portfolio Builder tab:
- Add "Quick Templates" card section above the manual input area
- Each template: name, description, "Apply & Run" button
- On click: populate inputs + auto-run scenario
- Results display in the existing what-if results panel

---

## Phase 3: Monte Carlo Engine (backend + frontend)

### 3a. Backend computation

**New `portfolio_risk_engine/monte_carlo.py`**:

```python
def run_monte_carlo(
    risk_result: RiskAnalysisResult,
    num_simulations: int = 1000,
    time_horizon_months: int = 12,
    portfolio_value: float | None = None,
) -> dict
```

**Math:**
1. Extract `weights` (Series), `covariance_matrix` (DataFrame), `expected_returns` (dict, optional) from `RiskAnalysisResult`
2. **Covariance is already monthly** — `compute_covariance_matrix()` calls `returns.cov()` on monthly returns in `portfolio_risk.py:195`. Do NOT divide by 12.
3. If no `expected_returns`, compute from `risk_result.portfolio_returns` mean (already monthly) or fall back to zero drift (conservative assumption).
4. Monthly drift per asset: `mu_monthly[i] = expected_returns[i] / 12` if annual, or direct if monthly.
5. Cholesky decomposition: `L = cholesky(cov_matrix)`. **Edge cases:**
   - If covariance matrix is not PSD (tiny negative eigenvalues from numerical noise), use `nearest_psd()` fix: eigendecompose, clamp negative eigenvalues to small epsilon, reconstruct.
   - If matrix is singular (e.g., single asset), fall back to diagonal variance simulation.
6. For each of N simulations: generate T months of correlated normal shocks via `L @ z`, compound portfolio returns. **Floor individual monthly returns at -99%** to prevent negative portfolio values.
7. Return percentile paths (5th, 25th, 50th, 75th, 95th), VaR/CVaR at terminal, probability of loss, expected terminal value.
8. **VaR/CVaR sign convention:** VaR and CVaR are positive loss amounts. `var_95 = initial_value - p5_terminal_value` (e.g., 117400 - 98000 = 19400). CVaR = mean of `initial_value - terminal_value` for simulations below the 5th percentile.

**Returns:**
```python
{
    "num_simulations": 1000,
    "time_horizon_months": 12,
    "initial_value": 117400,
    "percentile_paths": {
        "p5": [117400, 115200, ...],   # monthly values at 5th percentile
        "p25": [...],
        "p50": [...],
        "p75": [...],
        "p95": [...]
    },
    "terminal_distribution": {
        "mean": 125000,
        "median": 124200,
        "p5": 98000,
        "p95": 155000,
        "var_95": 19400,       # positive = loss amount (initial - p5 terminal)
        "cvar_95": 24100,      # mean loss below 5th percentile (positive)
        "probability_of_loss": 0.23,
        "max_gain_pct": 42.1,
        "max_loss_pct": -28.3,
    }
}
```

### 3b. API endpoint

**`app.py`** — Add `POST /api/monte-carlo`:
- Request: `{ portfolio_name, num_simulations?, time_horizon_months? }`
- Flow: load portfolio → `analyze_portfolio()` (cached) → `run_monte_carlo(risk_result)` → return
- Add `MonteCarloRequest`/`MonteCarloResponse` to `models/response_models.py`

**`services/scenario_service.py`** — Add `run_monte_carlo_simulation()` method.

### 3c. Frontend wiring

**Chassis:**
- `queryKeys.ts`: add `monteCarloKey(portfolioId)` (portfolio-id-scoped, matching existing patterns like `stressTestKey(portfolioId, ...)`)
- `APIService.ts`: add `runMonteCarlo(portfolioName, params)` → `POST /api/monte-carlo`
- `PortfolioCacheService.ts`: add `getMonteCarlo()` cache method

**Connectors:**
- `PortfolioManager.ts`: add `analyzeMonteCarlo(params)` → delegates to cache service
- New `features/monteCarlo/hooks/useMonteCarlo.ts` — manager-driven, on-demand refetch (same pattern as `useBacktest`)
- Returns: `{ result, isRunning, runMonteCarlo, error }`
- Barrel exports: `features/monteCarlo/hooks/index.ts` → `features/monteCarlo/index.ts` → `features/index.ts` → `connectors/src/index.ts`

**UI — `ScenarioAnalysis.tsx`** Monte Carlo tab:
- Remove placeholder card
- Add parameter controls: simulations (500/1000/5000 radio), horizon (6/12/24/36 months radio)
- "Run Simulation" button → `onRunMonteCarlo(params)`
- Results display:
  - Summary stats: expected value, probability of loss, VaR 95%, CVaR 95%
  - Percentile table: each month × percentiles (simple table, not chart)
  - Terminal distribution summary: min/max/mean/median

**Container** — wire `useMonteCarlo()`, pass to ScenarioAnalysis.

### 3d. Tests

**`tests/test_monte_carlo.py`** — unit tests with mock `RiskAnalysisResult`:
- Verify output shape
- Verify percentile ordering (p5 < p25 < p50 < p75 < p95)
- Verify terminal stats consistency
- Edge cases: single asset, zero vol

---

## Phase 4: Scenario Session History (frontend only)

Client-side session storage of scenario runs for comparison.

### 4a. Hook

**New `frontend/packages/connectors/src/features/scenarioHistory/useScenarioHistory.ts`**:
- Uses `sessionStorage` (clears on tab close)
- Stores: `Array<{ id, type: 'whatif'|'stress'|'monte-carlo', params, results, timestamp }>`
- Methods: `addRun(type, params, results)`, `clearHistory()`, `getRuns(type?)`
- Max 20 entries, FIFO eviction
- Auto-called after each successful scenario run in the container

### 4b. Container + UI

**`ScenarioAnalysisContainer.tsx`** — detect success via `useEffect` on hook return data changes (NOT `onSuccess` callback, which is deprecated in TanStack Query v5). Each hook's `data` going from null → non-null (or reference changing) signals a successful run. Use a ref to track previous data and compare.

**`ScenarioAnalysis.tsx`** — add collapsible "Recent Runs" panel at bottom of each tab:
- List: timestamp, type, scenario name, key metric (impact % or expected value)
- "Re-run" button re-executes with same params
- "Compare" mode: select 2 runs → side-by-side metrics table

---

## Phase 5: Optimizations Tab Cleanup (frontend only)

### 5a. Wire real optimization data

**`ScenarioAnalysisContainer.tsx`**:
- Do NOT import `usePortfolioOptimization()` — it auto-fetches and takes 60+ seconds. Instead, read cached optimization data directly via `queryClient.getQueryData(portfolioOptimizationKey(portfolioId, strategy))` from `useQueryClient()`. The key factory is `portfolioOptimizationKey` in `queryKeys.ts`, and the optimization hook caches under `portfolioOptimizationKey(currentPortfolio?.id || 'none', strategy)`. **Caveat:** must match the exact `portfolioId` (may be `'none'`) and `strategy` (check both `'min_variance'` and `'max_return'`, or whichever was last run). This is read-only access to data already fetched by Strategy Builder.
- If cached data exists, pass to ScenarioAnalysis. If not, pass `null`.
- Pass optimization results to ScenarioAnalysis

**`ScenarioAnalysis.tsx`** — Optimizations tab:
- **Current state:** Tab shows what-if-derived suggestions (lines ~739, ~1175), not real optimization data. Replace with optimization payload props.
- If optimization data exists (cached from Strategy Builder): show optimized weights vs current, risk improvement metrics
- "Apply as What-If" button → runs what-if with optimized weights (cross-links to Portfolio Builder tab)
- If no optimization data: show prompt "Run an optimization in Strategy Builder (⌘5) to see results here"

---

## Phase Dependencies

```
Phase 1 (Stress/Historical) ──── ✅ COMPLETE
Phase 2 (What-If Templates)   ── independent
Phase 3 (Monte Carlo) ────────── independent
Phase 4 (Session History) ─────── can start after Phase 1 (MC results additive)
Phase 5 (Optimizations) ──────── independent
```

Phase 1 is done. Phases 2, 3, 5 are independent of each other. Phase 4 can start after Phase 1 (what-if + stress test results available to store) — Monte Carlo results are additive but not required. All remaining phases touch `ScenarioAnalysis.tsx` and `ScenarioAnalysisContainer.tsx` — execute sequentially, not in parallel.

---

## Files Summary

| Phase | File | Action |
|-------|------|--------|
| 1 | *(all files)* | ✅ COMPLETE — commit `6644b810` |
| 2 | `ui/.../ScenarioAnalysisContainer.tsx` | Computed template presets |
| 2 | `ui/.../ScenarioAnalysis.tsx` | Quick Templates UI in Portfolio Builder tab |
| 3 | `portfolio_risk_engine/monte_carlo.py` | **New** — simulation engine |
| 3 | `models/response_models.py` | Add request/response models |
| 3 | `services/scenario_service.py` | Add monte carlo method |
| 3 | `app.py` | Add POST /api/monte-carlo |
| 3 | `tests/test_monte_carlo.py` | **New** — unit tests |
| 3 | `chassis/src/queryKeys.ts` | Add monte carlo key |
| 3 | `chassis/src/services/APIService.ts` | Add method |
| 3 | `connectors/src/features/monteCarlo/hooks/useMonteCarlo.ts` | **New** |
| 3 | `ui/.../ScenarioAnalysis.tsx` | Replace Monte Carlo placeholder |
| 4 | `connectors/src/features/scenarioHistory/useScenarioHistory.ts` | **New** |
| 4 | `ui/.../ScenarioAnalysisContainer.tsx` | Wire history |
| 4 | `ui/.../ScenarioAnalysis.tsx` | Recent Runs panel |
| 5 | `ui/.../ScenarioAnalysisContainer.tsx` | Wire optimization data |
| 5 | `ui/.../ScenarioAnalysis.tsx` | Optimizations tab real data |

---

## Verification

**Phase 1:** ✅ COMPLETE (commit `6644b810`)

**Phase 2:** Chrome: Portfolio Builder tab → Quick Templates section → click "Equal Weight" → inputs populate + scenario auto-runs → results display.

**Phase 3:** `python3 -m pytest tests/test_monte_carlo.py -v` passes. `curl -X POST localhost:8000/api/monte-carlo -d '{"portfolio_name":"CURRENT_PORTFOLIO"}'` returns percentile paths. Chrome: Monte Carlo tab → select params → Run → summary stats + percentile table.

**Phase 4:** Chrome: Run a stress test → "Recent Runs" panel shows entry → click Re-run → same scenario executes → select 2 runs → comparison table.

**Phase 5:** Chrome: Run optimization in Strategy Builder → switch to Scenario Analysis → Optimizations tab shows real optimized weights. Click "Apply as What-If" → Portfolio Builder tab activates with optimized weights.
