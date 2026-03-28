# Optimization Tool Redesign — Goal-Oriented UX

## Context

The current optimization tool is an academic-feeling calculator: pick "Min Variance" or "Max Return" from a dropdown, see a weights table, maybe export. But users don't think in optimization types — they think in goals: "improve my risk-adjusted return", "reduce my risk", "target a specific volatility."

The backend already supports 4 optimization types (`min_variance`, `max_return`, `max_sharpe`, `target_volatility`) via the MCP tool, but the frontend only exposes 2 via REST endpoints. The efficient frontier exists as a separate, disconnected chart. There's no before/after comparison. Compliance data (risk violations, factor violations) is computed but never surfaced in the UI.

This redesign transforms the optimization tool into a goal-first experience with inline frontier context, before/after comparison, and constraint visibility — while keeping it a single-purpose tool (not a workflow).

## Decisions Made

- **Backend in scope**: Add REST endpoints for `max_sharpe` and `target_volatility` (engine functions already exist)
- **Templates removed from OptimizeTool only**: Template selector doesn't fit goal-oriented narrative. Remove template UI/state from `OptimizeTool.tsx`. Do NOT remove template logic from `useOptimizationWorkflow` — it's shared with `StrategyBuilderContainer.tsx` which depends on `workflow.templates`. The hook IS modified to route 4 strategies, but template features are preserved.
- **Frontier timing**: Auto-trigger after optimization completes (no upfront load)
- **No trade execution**: Action paths hand off to existing tools (What-If, Backtest, Rebalance, Chat). "Set Target" navigates to the rebalance tool with optimized weights as context (existing behavior), not the `set_target_allocation` API.
- **State persistence**: Out of scope (A0 workstream)

## Layout

```
┌─────────────────────────────────────────────────────┐
│ Goal Selector                                        │
│ ○ Best risk-adjusted return (max_sharpe) ← default   │
│ ○ Reduce portfolio risk (min_variance)               │
│ ○ Maximize return (max_return)                       │
│ ○ Target volatility (target_volatility)              │
│   └─ [____%] input field (shown when selected)       │
│                                        [Optimize →]  │
├─────────────────────────────────────────────────────┤
│ Efficient Frontier (inline, auto-loaded after run)   │
│   ● You are here (current)                           │
│   ◆ Proposed (optimized)                             │
│   ── frontier curve                                  │
├─────────────────────────────────────────────────────┤
│ Before / After                                       │
│ ┌──────────┬──────────┬──────────┬─────────┐        │
│ │ Metric   │ Current  │ Proposed │ Change  │        │
│ ├──────────┼──────────┼──────────┼─────────┤        │
│ │ Return*  │ 8.2%     │ 9.1%    │ +0.9%  ↑│        │
│ │ Risk     │ 14.3%    │ 12.1%   │ -2.2%  ↓│        │
│ │ Sharpe*  │ 0.57     │ 0.75    │ +0.18  ↑│        │
│ │ HHI      │ 0.18     │ 0.12    │ -0.06  ↓│        │
│ │ * shown when expected returns available  │        │
│ └──────────┴──────────┴──────────┴─────────┘        │
├─────────────────────────────────────────────────────┤
│ Constraints                                          │
│ ✓ Risk limits: all passing                           │
│ ✗ Factor exposure: 2 violations (market beta 1.3 > 1.2)│
│ ✓ Proxy (industry exposure): within limits            │
├─────────────────────────────────────────────────────┤
│ Weight Changes (sorted by |delta|)                   │
│ AAPL  25.3% → 18.1%  (-720bp) ↓                    │
│ SGOV   5.2% → 12.8%  (+760bp) ↑                    │
│ MSFT  18.7% → 16.2%  (-250bp) ↓                    │
│ ...                                                  │
├─────────────────────────────────────────────────────┤
│ [Apply as What-If] [Backtest This] [Set Target]      │
│                              [Ask AI about this]     │
└─────────────────────────────────────────────────────┘
```

## Implementation Plan

### Phase 0: Backend — REST endpoints for max_sharpe and target_volatility

The MCP tool already calls `optimize_max_sharpe()` and `optimize_target_volatility()` from `portfolio_risk_engine.optimization`. The REST endpoints need the same routing.

**Step 0.1**: Add service methods to `OptimizationService`

File: `services/optimization_service.py`
- Add `optimize_maximum_sharpe(portfolio_data, risk_limits_data)` — follows `optimize_maximum_return` pattern, calls engine's `optimize_max_sharpe()`
- Add `optimize_target_volatility_portfolio(portfolio_data, risk_limits_data, target_volatility)` — calls engine's `optimize_target_volatility()`
- Both return `OptimizationResult` (same as existing methods)
- Import `optimize_max_sharpe, optimize_target_volatility` from `portfolio_risk_engine.optimization`

**Step 0.2**: Add response models

File: `models/response_models.py`
- Add `MaxSharpeResponse(BaseModel)` — same schema as `MinVarianceResponse` (reuse fields: `success`, `optimization_results`, `summary`, `portfolio_metadata`, `risk_limits_metadata`)
- Add `TargetVolatilityResponse(BaseModel)` — same schema

File: `models/__init__.py`
- Export `MaxSharpeResponse`, `TargetVolatilityResponse`

**Step 0.3**: Add REST endpoints to `app.py`

File: `app.py`
- Add `TargetVolatilityRequest(OptimizationRequest)` Pydantic model with `target_volatility: float` field (snake_case — backend convention)
- Add `_run_max_sharpe_workflow()` — mirrors `_run_max_return_workflow()` (needs expected returns, same gating logic)
- Add `_run_target_volatility_workflow()` — mirrors max_return + passes target_volatility param
- Add `POST /api/max-sharpe` endpoint — uses `MaxSharpeResponse`
- Add `POST /api/target-volatility` endpoint — uses `TargetVolatilityRequest` + `TargetVolatilityResponse`
- Both use `get_user_optimization_service` dependency (per-user caching)
- Response shape: identical `{success, optimization_results, summary, portfolio_metadata, risk_limits_metadata}`
- **Error handling**: Do NOT follow `_run_max_return_workflow()`'s pattern. That workflow catches generic `Exception` and converts to 500, swallowing expected-returns failures. Instead, follow the efficient frontier pattern: raise `HTTPException(status_code=422, detail="...")` explicitly for missing expected returns. New workflow helpers should validate expected returns upfront and return a clear 422 if absent. **At the endpoint level**, the new route handlers must re-raise `HTTPException` before the generic `except Exception` catch — add an explicit `except HTTPException: raise` clause so 422s propagate correctly (the existing optimization endpoints catch all exceptions and convert to 500 otherwise).

**Step 0.4**: Enrich `evaluate_optimized_weights()` with expected return and Sharpe

File: `portfolio_risk_engine/portfolio_optimizer.py` (function `evaluate_optimized_weights`, line ~569)
- Currently calls `build_portfolio_view()` which returns `volatility_annual` and `herfindahl` but NOT expected return or Sharpe
- When `expected_returns` dict is available (passed through from `portfolio_data.expected_returns`), compute:
  - `expected_return = sum(w_i * μ_i)` — dot product of optimized weights and expected returns
  - `sharpe_ratio = (expected_return - risk_free_rate) / volatility_annual` — use treasury rate or 0.04 default
- Add these to `portfolio_summary` dict returned by `evaluate_optimized_weights()`
- The enrichment runs **when expected_returns are present in `portfolio_data`** — regardless of optimization type. When expected_returns are absent, these fields are simply omitted from the response.
- **Important**: `optimize_min_variance()` in `portfolio_risk_engine/optimization.py` does NOT call `evaluate_optimized_weights()` — it calls `run_min_var()` directly and returns `OptimizationResult` without `portfolio_summary`. The other 3 types (`optimize_max_return`, `optimize_max_sharpe`, `optimize_target_volatility`) DO call `evaluate_optimized_weights()`. To get proposed metrics for min_variance, add an `evaluate_optimized_weights()` call to `optimize_min_variance()` (or compute the metrics inline). This is a small addition (~5 lines) following the pattern at line ~294.
- **max_drawdown is NOT computable** without a backtest — excluded from the before/after comparison

**Key files**: `services/optimization_service.py`, `models/response_models.py`, `models/__init__.py`, `app.py`, `portfolio_risk_engine/portfolio_optimizer.py`
**Reuse**: `OptimizationRequest` model, `get_user_optimization_service` dependency
**Note on existing max_return workflow**: `_run_max_return_workflow()` has a known issue where it swallows expected-returns failures in a broad `except Exception` and proceeds with incomplete data. The new max-sharpe and target-volatility workflows must NOT replicate this — use `HTTPException(422)` for missing expected returns. Fixing the existing max_return workflow's error handling is out of scope for this plan but should be addressed separately.

### Phase 1: Type expansion — chassis + services + adapter

Expand the TypeScript type system from 2 to 4 optimization strategies.

**Step 1.1**: Expand chassis types

File: `frontend/packages/chassis/src/catalog/types.ts`
- `OptimizationSourceData.strategy`: `'min_variance' | 'max_return'` → add `'max_sharpe' | 'target_volatility'`
- `SDKSourceParamsMap['optimization']`: add `targetVolatility?: number` (camelCase — matching existing SDK param conventions in this file)

**Naming convention**: Backend uses `snake_case` (`target_volatility`), frontend uses `camelCase` (`targetVolatility`). Conversion boundary is at the API service layer — `APIService.getTargetVolatilityOptimization()` receives camelCase from hooks and sends snake_case to the REST endpoint.

File: `frontend/packages/chassis/src/types/api.ts`
- Add `MaxSharpeApiResponse` and `TargetVolatilityApiResponse` type aliases (same schema as `MinVarianceApiResponse`)

File: `frontend/packages/chassis/src/types/api-generated.ts`
- **Update manually** — add `MaxSharpeResponse` and `TargetVolatilityResponse` schema types matching the existing `MinVarianceResponse`/`MaxReturnResponse` pattern (same fields). The generated file at line ~4778 has the existing types. No automated `generate-types` script exists in this repo; types are maintained manually in this file.

File: `frontend/packages/chassis/src/catalog/descriptors.ts`
- Update `optimizationDescriptor`:
  - **Fields**: add `compliance` and `optimized_weights` to the field list
  - **Params**: expand strategy values from `min_variance|max_return` to include `max_sharpe|target_volatility`, add `targetVolatility` as an optional numeric param (camelCase in descriptor, matching SDK convention)

**Step 1.2**: Add API service methods

File: `frontend/packages/chassis/src/services/APIService.ts`
- Add `getMaxSharpeOptimization(portfolioName)` → `POST /api/max-sharpe`
- Add `getTargetVolatilityOptimization(portfolioName, targetVolatility)` → `POST /api/target-volatility`

File: `frontend/packages/chassis/src/services/PortfolioCacheService.ts`
- Add `getMaxSharpeOptimization(portfolioId, portfolio)` — follows existing cache pattern
- Add `getTargetVolatilityOptimization(portfolioId, portfolio, targetVolatility)` — same pattern
- **Cache key for targetVolatility must include the target value** to prevent collisions between different target vols. Use operation key `targetVolatility_${targetVol}` (e.g., `portfolio1.targetVolatility_0.12.v0`). Current cache key format: `${portfolioId}.${operation}.v${version}`

**Step 1.3**: Expand adapter

File: `frontend/packages/connectors/src/adapters/PortfolioOptimizationAdapter.ts`
- Expand `OptimizationStrategy` type to 4 values
- Extract compliance data from `optimization_results.risk_analysis` and `optimization_results.beta_analysis`:
  ```ts
  compliance: {
    risk: { passes: boolean | null; violationCount: number; details: Array<{metric, actual, limit}> }
    factor: { passes: boolean | null; violationCount: number; details: Array<{factor, beta, limit}> }
    proxy: { passes: boolean | null; violationCount: number; details: Array<Record<string, unknown>> }
  }
  ```
- Extract proposed metrics from `optimization_results.portfolio_summary`:
  - `volatility_annual` (decimal) — convert to percent at adapter layer
  - `herfindahl` — available directly
  - `expected_return` — **only available when expected_returns are present in portfolio data** (see Step 0.4). Present for any strategy when expected returns are stored in DB; absent when they're not.
  - `sharpe_ratio` — computed as `(expected_return - risk_free_rate) / volatility_annual` when expected_return is present (matches Step 0.4 formula)
  - `max_drawdown` — **NOT available** for proposed portfolio (would require backtesting). Excluded from comparison.
- Expose `optimized_weights` as a top-level field (currently buried in `optimization_results_raw`)

**Step 1.4**: Expand resolver + manager

File: `frontend/packages/connectors/src/resolver/registry.ts` (lines ~691-717)
- Expand strategy routing from 2-way to 4-way switch

File: `frontend/packages/connectors/src/managers/PortfolioManager.ts`
- Add `optimizeMaxSharpe(portfolioId)` and `optimizeTargetVolatility(portfolioId, targetVolatility)` methods

**Step 1.5**: Expand scenario state types

File: `frontend/packages/ui/src/components/portfolio/scenario/types.ts`
- Expand `OptimizationStrategy` union from `"min_variance" | "max_return"` → add `"max_sharpe" | "target_volatility"`

File: `frontend/packages/ui/src/components/portfolio/scenario/useScenarioState.ts`
- Expand `OPTIMIZATION_STRATEGIES` array to include all 4 values
- Update `toOptimizationStrategy()` helper (line ~68) to recognize `max_sharpe` and `target_volatility` — currently only recognizes 2 values and coerces unknown inputs to fallback

File: `frontend/packages/ui/src/components/portfolio/scenario/__tests__/useScenarioState.test.tsx`
- Update tests to cover new strategy values

### Phase 2: Hook expansion

**Step 2.1**: Expand usePortfolioOptimization

File: `frontend/packages/connectors/src/features/optimize/hooks/usePortfolioOptimization.ts`
- Expand strategy type to 4 values
- **Change default strategy from `min_variance` to `max_sharpe`** — matches the goal-first UX where "Best risk-adjusted return" is the default selection. Update the initial state value (currently `'min_variance'` at line ~22).
- Add `targetVolatility` to resolver params (when strategy is `target_volatility`)
- **Include `targetVolatility` in hook params and cache state** — different target vols must trigger different fetches
- Add convenience methods: `optimizeMaxSharpe()`, `optimizeTargetVolatility(vol: number)`
- Update `runOptimization()` to accept `{ strategy, targetVolatility? }`

Also update the default in `descriptors.ts` optimization descriptor params (line ~348) to match `max_sharpe` as default.

**Step 2.2**: Update useOptimizationWorkflow (minimal change)

File: `frontend/packages/connectors/src/features/optimize/hooks/useOptimizationWorkflow.ts`
- **Do NOT remove template logic** — this hook is shared with `StrategyBuilderContainer.tsx` which depends on `workflow.templates`
- Update `handleOptimize` to route all 4 strategies
- Pass through compliance data from optimization data

### Phase 3: UI redesign — OptimizeTool component

**Step 3.1**: Create sub-component directory

Create `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/` with:

- **`GoalSelector.tsx`** — Radio-card group with 4 goal-oriented choices. Each card: icon + label + description. `targetVolatility` shows a numeric input (percent) when selected — **convert to decimal before sending to backend** (e.g., user enters `12` → API receives `0.12`). Validate: must be positive, reasonable range (1-50%). Run button at bottom. Props: `{ strategy, onStrategyChange, targetVolatility, onTargetVolatilityChange, onRun, isRunning }`

- **`BeforeAfterComparison.tsx`** — Table/grid showing current vs proposed metrics. 4 rows: Expected Return (when available), Expected Risk (volatility), Sharpe Ratio (when available), Concentration (HHI). Max drawdown excluded (not computable for proposed without backtesting). Each row shows current value, proposed value, delta with color (green = improvement, red = worse). Return/Sharpe rows shown **based on metric presence in the data**, not by strategy name (min_variance CAN have expected returns if they're stored in the DB — `PortfolioManager.load_portfolio_data()` loads them when available). **Per-metric formatting**: Return and Risk displayed as percentages (adapter converts backend decimals to percent), Sharpe and HHI displayed as raw decimal values (not percentages). Props: `{ currentMetrics, proposedMetrics }`. Uses existing MetricCard or table patterns.

- **`ConstraintStatus.tsx`** — Three rows for risk/factor/proxy compliance. Each shows pass/fail icon + violation count + expandable details. Uses compliance data from adapter. Props: `{ compliance }`.

- **`WeightChangesTable.tsx`** — Extracted from existing inline table. Sorted by `|change_bps|` descending. Columns: Ticker, Current %, Proposed %, Change (bps), direction arrow. Uses DataTable block component. Props: `{ changes }`.

- **`ActionBar.tsx`** — Four buttons: Apply as What-If, Backtest This, Set as Target (navigates to rebalance tool with optimized weights as context via `onNavigate("rebalance", { weights, label, source })`), Ask AI about this. Props: callbacks for each action.

- **`index.ts`** — Barrel export.

**Step 3.2**: Rewrite OptimizeTool

File: `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx`
- Replace monolithic 706-line component with orchestrator that composes sub-components
- Remove template selector entirely
- Wire GoalSelector → usePortfolioOptimization → results flow
- Auto-trigger efficient frontier after optimization completes
- Add proposed portfolio point to EfficientFrontierTab (new prop)
- Compute before/after metrics from adapter's extracted data
- Wire constraint status from adapter's compliance data
- Keep existing action handlers (What-If, Backtest, Set Target, Chat)

**Step 3.3**: Update EfficientFrontierTab

File: `frontend/packages/ui/src/components/portfolio/scenario/EfficientFrontierTab.tsx`
- Add `proposedPoint?: { volatility_pct: number; expected_return_pct: number }` prop
- Render third Scatter series for proposed position (distinct color/shape from current)
- Add `compact?: boolean` prop — when true, hide the detail table and "Run Frontier" card (just show the chart)
- Keep full mode available for standalone use

### Phase 4: Integration wiring

**Step 4.1**: Auto-trigger frontier

In OptimizeTool, after optimization completes — **only if the optimization response indicates expected returns were available**. The efficient frontier backend requires expected returns and hard-fails (422) without them. Gate on data presence, not strategy name, since min_variance CAN have expected returns if they're stored and max_return CAN fail to load them:
```ts
useEffect(() => {
  // Frontier requires expected returns — check if the optimization result has them
  // Adapter normalizes to _pct fields, so check expected_return_pct
  const hasExpectedReturns = optimizationData?.proposedMetrics?.expected_return_pct != null;
  if (optimizationData && hasExpectedReturns && !frontierResult && !isFrontierRunning) {
    runEfficientFrontier();
  }
}, [optimizationData]);
```
When expected returns are absent, the frontier section shows an informational message: "Configure expected returns to see the efficient frontier." No run button — clicking it would just produce a 422 error.

**Step 4.2**: Compute proposed point for frontier

From the adapter's normalized optimization data, extract volatility and expected return (already converted to percent at adapter layer). Pass as `proposedPoint` to EfficientFrontierTab:
```ts
proposedPoint = {
  volatility_pct: optimizationData.proposedMetrics.volatility_pct,  // percent, e.g. 12.1
  expected_return_pct: optimizationData.proposedMetrics.expected_return_pct,  // percent, e.g. 9.1
}
```
**Unit contract**: `EfficientFrontierTab` expects `_pct` fields (percent, not decimal). Backend `portfolio_summary` returns `volatility_annual` as decimal (e.g., `0.121`). The adapter (Step 1.3) handles the `×100` conversion. Do NOT pass raw `portfolio_summary` values directly to the frontier chart.

**Step 4.3**: Before/after metric extraction

**Proposed** metrics come from `optimization_results.portfolio_summary` after backend enrichment (Step 0.4): `expected_return`, `volatility_annual`, `sharpe_ratio`, `herfindahl`. Note: `max_drawdown` is NOT available for proposed portfolio (would require backtesting) — excluded from comparison.

**Current** metrics are NOT fully available from `usePositions()` — positions provides holdings and weights (as 0-100 percentages) but NOT portfolio-level return, Sharpe, volatility, or HHI. HHI must be computed client-side from position weights (see below).

**Decision**: Add `usePerformance()` to `OptimizeTool` for current portfolio metrics. `usePerformance()` exposes annualized return, Sharpe ratio, volatility, and max drawdown via `PerformanceAdapter`. Only return, Sharpe, and volatility are used in the comparison (max drawdown excluded since proposed side doesn't have it).

**HHI (concentration)**: `usePositions()` does NOT expose HHI directly — it provides holdings with weights as 0-100 percentages. Current HHI must be computed client-side from position weights: `HHI = Σ(w_i²)` where `w_i` is in 0-1 decimal form. The `BeforeAfterComparison` component should normalize position weights from percentage (0-100) to decimal (0-1) before computing HHI. Proposed HHI comes from `optimization_results.portfolio_summary.herfindahl` (already 0-1 decimal). Same normalization applies to weight change bps calculations.

**Unit normalization required**: Backend optimization `portfolio_summary.expected_return` is decimal (e.g., `0.095` = 9.5%), while `PerformanceAdapter` output is percentage-based (e.g., `9.5`). The `BeforeAfterComparison` component must normalize both sides to the same unit before computing deltas. Convention: display as percentage, normalize backend decimals to percentage at the adapter extraction step (Step 1.3).

File to update: `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx` — add `usePerformance()` import and usage.

## Files Changed

| File | Action | Phase |
|------|--------|-------|
| `services/optimization_service.py` | Modify — add 2 service methods | 0 |
| `models/response_models.py` | Modify — add MaxSharpeResponse, TargetVolatilityResponse | 0 |
| `models/__init__.py` | Modify — export new response models | 0 |
| `portfolio_risk_engine/portfolio_optimizer.py` | Modify — enrich evaluate_optimized_weights with expected_return + Sharpe | 0 |
| `portfolio_risk_engine/optimization.py` | Modify — add evaluate_optimized_weights() call to optimize_min_variance() | 0 |
| `app.py` | Modify — add 2 REST endpoints + workflow helpers + request model | 0 |
| `frontend/packages/chassis/src/catalog/types.ts` | Modify — expand strategy type, add compliance | 1 |
| `frontend/packages/chassis/src/catalog/descriptors.ts` | Modify — update optimization descriptor fields + params | 1 |
| `frontend/packages/chassis/src/types/api.ts` | Modify — add response type aliases | 1 |
| `frontend/packages/chassis/src/types/api-generated.ts` | Modify — add MaxSharpe/TargetVolatility schema types | 1 |
| `frontend/packages/chassis/src/services/APIService.ts` | Modify — add 2 API methods | 1 |
| `frontend/packages/chassis/src/services/PortfolioCacheService.ts` | Modify — add 2 cache methods (targetVol in cache key) | 1 |
| `frontend/packages/connectors/src/adapters/PortfolioOptimizationAdapter.ts` | Modify — expand strategy, extract compliance/metrics | 1 |
| `frontend/packages/connectors/src/resolver/registry.ts` | Modify — 4-way strategy routing | 1 |
| `frontend/packages/connectors/src/managers/PortfolioManager.ts` | Modify — add 2 manager methods | 1 |
| `frontend/packages/ui/src/components/portfolio/scenario/types.ts` | Modify — expand OptimizationStrategy union | 1 |
| `frontend/packages/ui/src/components/portfolio/scenario/useScenarioState.ts` | Modify — expand OPTIMIZATION_STRATEGIES + toOptimizationStrategy() | 1 |
| `frontend/packages/ui/src/components/portfolio/scenario/__tests__/useScenarioState.test.tsx` | Modify — add tests for new strategies | 1 |
| `frontend/packages/connectors/src/features/optimize/hooks/usePortfolioOptimization.ts` | Modify — support 4 strategies, targetVol in params, default→max_sharpe | 2 |
| `frontend/packages/connectors/src/features/optimize/hooks/useOptimizationWorkflow.ts` | Modify — route 4 strategies (keep templates) | 2 |
| `frontend/packages/ui/src/components/portfolio/scenario/EfficientFrontierTab.tsx` | Modify — proposedPoint + compact mode | 3 |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx` | Rewrite — goal-first orchestrator + usePerformance | 3 |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/GoalSelector.tsx` | Create | 3 |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/BeforeAfterComparison.tsx` | Create | 3 |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/ConstraintStatus.tsx` | Create | 3 |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/WeightChangesTable.tsx` | Create | 3 |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/ActionBar.tsx` | Create | 3 |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/index.ts` | Create | 3 |

**22 files modified, 6 files created**

## Verification

1. **Backend**: Run existing optimization tests (`pytest tests/ -k optimization`). Add tests for new REST endpoints (max-sharpe, target-volatility) verifying response shape matches existing endpoints.
2. **Frontend types**: `cd frontend && npm run typecheck` across all 3 packages — verify no type errors from strategy expansion.
3. **Frontend build**: `cd frontend && npm run build` — verify no build errors.
4. **Manual test**: Open Scenarios → Optimize in browser. Verify:
   - All 4 goals selectable
   - Target volatility input appears/hides correctly
   - Optimization runs and returns results
   - Efficient frontier auto-loads after optimization with both markers
   - Before/after comparison shows correct delta values
   - Constraint status reflects compliance data
   - Weight changes sorted by magnitude
   - All 4 action buttons work (What-If, Backtest, Set Target, Chat)
5. **Frontend tests**: Run existing frontend tests (`cd frontend && npm test`). Add tests for new sub-components (GoalSelector, BeforeAfterComparison, ConstraintStatus).

## Risks

- **Expected returns requirement**: `max_sharpe` and `target_volatility` both require stored expected returns. If a user hasn't configured these, the optimization will return an error. The GoalSelector should show a helpful message when this happens (the backend already returns a clear error message).
- **Frontier + optimization coupling**: Auto-triggering the frontier after optimization creates a sequential 3-10s wait. Mitigate by showing the optimization results immediately with a "Loading frontier..." placeholder for the chart.
- **Type cascade**: Expanding `OptimizationStrategy` from 2→4 touches types in 3 packages. Must update all in lockstep. This is a well-trodden pattern in this codebase.
