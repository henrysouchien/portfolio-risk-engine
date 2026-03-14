# Scenarios Prep Refactor Spec

> **Purpose**: Three isolated refactors that must land before Phase 3 (Scenarios Overhaul) can proceed.
> Each refactor extracts container-owned state into reusable hooks, unblocking the extraction of
> scenario tools into standalone views.
>
> **Context**: Codex reviewed `SCENARIOS_OVERHAUL_SPEC.md` and returned FAIL with 4 High / 3 Medium
> findings. The root cause of 5/7 findings is that ScenarioAnalysisContainer (~840 lines) and
> StrategyBuilderContainer (~465 lines) own state that downstream tool views need but can't access
> once extracted. These prep refactors make each extraction trivial.

---

## Dependency Map

```
Prep A: useScenarioState ──── unblocks ──→ What-If, Stress Test, Monte Carlo tool views
Prep B: useOptimizationWorkflow ── unblocks ──→ Optimize, Backtest tool views
Prep C: Tax Harvest plumbing ──── unblocks ──→ Tax Harvest tool view (independent of A/B)
```

Prep A and B can run in parallel. Prep C is fully independent.

---

## Prep A: Extract `useScenarioState()` Hook

### Problem

`ScenarioAnalysisContainer.tsx` (~840 lines) is the sole owner of:

1. **Positions-derived state** — `initialPositions` computed from `usePositions().holdings` (lines 595-607)
2. **Scenario templates** — `buildScenarioTemplates()` (lines 231-361) builds 5 templates from position holdings (equal weight, conservative 60/40, risk parity, concentrated growth, hedge overlay)
3. **Optimization cache read** — reads `portfolioOptimizationKey` from TanStack query cache to surface optimization results (lines 418-440)
4. **Scenario history tracking** — `useScenarioHistory()` + 3 `useEffect` blocks + 3 `pendingHistoryParamsRef` refs that record what-if/stress/monte-carlo runs into session history (lines 459-656)
5. **Transformed data assembly** — `transformedData` useMemo that assembles scenario results, templates, and strategy integration metadata (lines 528-593)
6. **Scenario execution orchestration** — `handleRunScenario()` (lines 674-729) that validates input, fires intents, and delegates to `runScenario()`

When Phase 3 extracts What-If, Stress Test, and Monte Carlo into standalone views, each view needs subsets of this state but cannot import it from a parent container.

### Source Files

| File | Lines | Package |
|------|-------|---------|
| `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` | ~840 | `@risk/ui` |
| `frontend/packages/ui/src/components/portfolio/scenario/useScenarioHistory.ts` | 246 | `@risk/ui` |
| `frontend/packages/ui/src/components/portfolio/scenario/useScenarioOrchestration.ts` | 273 | `@risk/ui` |
| `frontend/packages/ui/src/components/portfolio/scenario/types.ts` | 195 | `@risk/ui` |

### Target State

Create `useScenarioState()` in `@risk/connectors` (or `@risk/ui/scenario/`) that encapsulates:

```typescript
interface UseScenarioStateReturn {
  // Position-derived
  initialPositions: Array<{ ticker: string; name: string; weight: number; price: number; shares: number }>;

  // Templates
  scenarioTemplates: ScenarioTemplate[];

  // Optimization cache
  optimizationData: CachedOptimizationData | null;

  // History (delegates to useScenarioHistory)
  addRun: (type: string, params: unknown, results: unknown) => void;
  clearHistory: () => void;
  getRuns: () => ScenarioHistoryRun[];
  pendingHistoryTracking: {
    trackWhatIf: (params: unknown) => void;
    trackStress: (params: unknown) => void;
    trackMonteCarlo: (params: unknown) => void;
  };
}
```

### What Moves

| From Container | To Hook | Lines |
|---------------|---------|-------|
| `buildScenarioTemplates()` + helpers (`toNormalizedWeights`, `isCashLikeType`, etc.) | Module-level utility (already pure functions) | 152-361 |
| `initialPositions` useMemo | Inside hook | 595-607 |
| `optimizationData` useMemo + cache read | Inside hook | 418-440 |
| `useScenarioHistory()` + 3 tracking useEffects + 3 pending refs | Inside hook | 459-656 |
| `scenarioTemplates` useMemo | Inside hook | 414-417 |

### What Stays in Container (Temporarily)

- `handleRunScenario()` — orchestration of intent triggers and `runScenario()` delegation
- `transformedData` useMemo — assembles the specific shape expected by `<ScenarioAnalysis />`
- Loading/error/no-portfolio guard renders

### Constraints

- `useScenarioHistory` is currently in `@risk/ui` (not `@risk/connectors`). If the new hook lives in `@risk/connectors`, either (a) move `useScenarioHistory` to connectors, or (b) keep `useScenarioState` in `@risk/ui` and have tool views import from there.
- `portfolioOptimizationKey` is imported from `@risk/chassis`. The new hook needs this import.
- `buildScenarioTemplates()` and its helpers are pure functions (~210 lines). They should be extracted to a separate utility file, not inlined in the hook.

### Verification

- ScenarioAnalysisContainer renders identically before/after (no visual diff)
- All existing scenario tests pass
- Container shrinks by ~300 lines
- New hook is importable from tool view files

---

## Prep B: Extract `useOptimizationWorkflow()` Hook

### Problem

`StrategyBuilderContainer.tsx` (~465 lines) owns the optimize → backtest pipeline:

1. **Optimization hook consumption** — calls `usePortfolioOptimization()` and destructures all fields (lines 164-181)
2. **Backtest hook consumption** — calls `useBacktest()` and reads `backtest.data?.backtestResults` (lines 165, 183)
3. **Template loading** — calls `useStrategyTemplates()` and maps template data to component shape (lines 166, 184-192)
4. **Backtest gating** — `hasTickerWeights` check (line 193): backtest is disabled until optimization produces weights
5. **handleOptimize()** — parses constraints, fires intent, dispatches to `optimizeMinVariance()` or `optimizeMaxReturn()`, but also handles template deployment by routing to `backtest.runBacktest()` when weights are provided (lines 246-291)
6. **handleBacktest()** — gates on `optimizationData?.weights`, fires intent, calls `backtest.runBacktest()` with ticker weights from optimization (lines 294-329)
7. **handleExportToScenario()** — creates scenario template from strategy config and calls `whatIf.runScenario()` (lines 351-388)

Additionally, `usePortfolioOptimization()` hook (45 lines) **auto-fetches on mount** because it passes `enabled: !!currentPortfolio` with a default strategy. This means any component that calls it triggers an optimization API call immediately — incompatible with the "Run Optimization" button UX the Phase 3 spec envisions.

### Source Files

| File | Lines | Package |
|------|-------|---------|
| `frontend/packages/ui/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx` | ~465 | `@risk/ui` |
| `frontend/packages/connectors/src/features/optimize/hooks/usePortfolioOptimization.ts` | 45 | `@risk/connectors` |
| `frontend/packages/connectors/src/features/backtest/hooks/useBacktest.ts` | 126 | `@risk/connectors` |

### Target State

Create `useOptimizationWorkflow()` that wraps the optimize → backtest pipeline:

```typescript
interface UseOptimizationWorkflowReturn {
  // Optimization
  optimizationData: OptimizationData | null;
  isOptimizing: boolean;
  optimizationError: string | null;
  optimizeMinVariance: () => void;
  optimizeMaxReturn: () => void;

  // Backtest (gated on optimization)
  backtestData: BacktestData | undefined;
  isBacktesting: boolean;
  backtestError: string | null;
  runBacktest: (params: BacktestParams) => void;
  canBacktest: boolean;  // derived: Object.keys(optimizationData?.weights || {}).length > 0

  // Templates
  templates: TemplateRow[];

  // Cross-container export
  exportToScenario: (strategyConfig: unknown) => void;
}
```

### Critical Fix: Deferred Optimization Execution

`usePortfolioOptimization()` currently auto-fetches:

```typescript
// Current (line 10-16): auto-fetches when portfolio exists
const resolved = useDataSource(
  'optimization',
  currentPortfolio ? { portfolioId: currentPortfolio.id, strategy } : undefined,
  { enabled: !!currentPortfolio }  // ← fires immediately
);
```

Must change to deferred execution (same pattern as `useWhatIfAnalysis` and `useBacktest`):

```typescript
// Target: only fetches after explicit trigger
const [runId, setRunId] = useState<number | null>(null);
const resolverParams = useMemo(() => {
  if (!runId || !currentPortfolio) return undefined;
  return { portfolioId: currentPortfolio.id, strategy, _runId: runId };
}, [runId, currentPortfolio, strategy]);

const resolved = useDataSource('optimization', resolverParams, {
  enabled: !!resolverParams,  // ← only fires after setRunId
});
```

### What Moves

| From Container | To Hook | Lines |
|---------------|---------|-------|
| `usePortfolioOptimization()` + `useBacktest()` + `useStrategyTemplates()` calls | Internalized in workflow hook | 164-192 |
| `hasTickerWeights` derivation | `canBacktest` computed property | 193 |
| `handleOptimize()` logic (constraint parsing, intent, dispatch) | `optimize(constraints)` method | 246-291 |
| `handleBacktest()` logic (weight gating, intent, dispatch) | `runBacktest(config)` method | 294-329 |
| `handleExportToScenario()` logic | `exportToScenario(config)` method | 351-388 |
| Template data mapping (`templatesProp`) | Inside hook | 184-192 |

### What Stays in Container (Temporarily)

- `handleSaveStrategy()` — mock implementation, not needed for Phase 3
- Component render tree and loading/error guards
- `transformedOptimizationData` assembly

### Constraints

- The deferred execution change to `usePortfolioOptimization()` is a **behavioral change** — existing StrategyBuilderContainer currently shows optimization results on mount. After refactor, it should show a "Run Optimization" prompt instead. This is the desired Phase 3 UX but may need a feature flag if deployed before Phase 3.
- `handleOptimize()` has dual behavior: template deployment (routes to backtest) vs. optimization (routes to optimizer). The workflow hook must preserve this routing.
- `useWhatIfAnalysis()` is consumed for `exportToScenario` — the workflow hook takes a dependency on the what-if hook.

### Verification

- StrategyBuilderContainer renders identically before/after (with feature flag for auto-fetch behavior)
- Backtest is still gated on optimization weights
- Template deployment still routes correctly
- All existing strategy builder tests pass
- New hook is importable from OptimizeTool and BacktestTool

---

## Prep C: Tax Harvest Frontend Plumbing

### Problem

The backend `suggest_tax_loss_harvest()` MCP tool is complete (FIFO lots, wash sale rules, agent format with flags). But the frontend has **zero real integration**:

| Layer | Status |
|-------|--------|
| Catalog types (`TaxHarvestSourceData`) | Exists in `chassis/src/catalog/types.ts` (line 544) |
| Catalog descriptor (`taxHarvestDescriptor`) | Exists in `chassis/src/catalog/descriptors.ts` (line 757) |
| Resolver registry entry | **Stub only** — returns fake opportunities with `estimated_savings: 0` and a disclaimer (registry.ts lines 761-774) |
| APIService method | **Missing** — no `suggestTaxLossHarvest()` on APIService |
| Adapter | **Missing** — no `TaxHarvestAdapter` |
| Hook (`useTaxHarvest`) | **Missing** |

Phase 3d (Tax Harvest tool view) requires all layers to exist.

### Source Files

| File | Lines | What Needs Change |
|------|-------|-------------------|
| `frontend/packages/chassis/src/catalog/types.ts` | ~600 | Already has `TaxHarvestSourceData` type — may need refinement |
| `frontend/packages/chassis/src/catalog/descriptors.ts` | ~1270 | Already has `taxHarvestDescriptor` — may need refinement |
| `frontend/packages/chassis/src/services/APIService.ts` | (large) | Add `suggestTaxLossHarvest()` method |
| `frontend/packages/connectors/src/resolver/registry.ts` | ~900 | Replace stub resolver with real API call |
| `frontend/packages/connectors/src/adapters/` | (new file) | Create `TaxHarvestAdapter.ts` |
| `frontend/packages/connectors/src/features/` | (new dir) | Create `taxHarvest/hooks/useTaxHarvest.ts` |

### Backend API Reference

The MCP tool `suggest_tax_loss_harvest` returns agent format:

```python
{
    "status": "success",
    "format": "agent",
    "snapshot": {
        "harvest_candidates": [...],      # Ticker, unrealized P&L, lot details
        "wash_sale_warnings": [...],      # Tickers with wash sale risk
        "estimated_tax_savings": float,   # Total estimated savings
        "methodology": str,               # FIFO description
    },
    "flags": [...],                       # Interpretive flags (severity-sorted)
    "file_path": str | null,
}
```

The REST endpoint is `POST /api/tax-harvest` (or proxied through gateway as MCP call).

### Target State

#### 1. APIService Method

```typescript
// In APIService.ts
async suggestTaxLossHarvest(portfolioId: string): Promise<TaxHarvestResponse> {
  return this.post('/api/tax-harvest', { portfolio_name: portfolioId });
}
```

#### 2. Adapter

```typescript
// TaxHarvestAdapter.ts
export interface TaxHarvestData {
  harvest_candidates: Array<{
    ticker: string;
    unrealized_pnl: number;
    shares: number;
    cost_basis: number;
    current_price: number;
    holding_period: 'short' | 'long';
    wash_sale_risk: boolean;
  }>;
  wash_sale_warnings: string[];
  estimated_tax_savings: number;
  methodology: string;
  flags: Array<{ severity: string; message: string }>;
}

export class TaxHarvestAdapter {
  static transform(raw: unknown): TaxHarvestData { ... }
}
```

#### 3. Resolver

Replace the stub in `registry.ts` lines 761-774 with:

```typescript
'tax-harvest': async (params, context) => {
  const response = await context.api.suggestTaxLossHarvest(params.portfolioId);
  return TaxHarvestAdapter.transform(response);
},
```

#### 4. Hook

```typescript
// useTaxHarvest.ts — follows useBacktest pattern (deferred execution)
export const useTaxHarvest = () => {
  // Deferred: only fetches after explicit runHarvest() call
  // Returns: data, loading, error, runHarvest(), hasData, flags
};
```

### Pattern Reference

Follow the same pattern as `useBacktest.ts` (126 lines):
- Deferred execution via `runId` state
- `resolverParams` gated on `runId` existence
- `useDataSource('tax-harvest', resolverParams, { enabled: !!resolverParams })`
- Portfolio change resets state

### Constraints

- The backend MCP tool requires a portfolio to be loaded. The hook should gate on `currentPortfolio`.
- Wash sale warnings need special UI treatment (these are actionable flags, not just informational).
- The `TaxHarvestSourceData` type in catalog may need updating to match the actual backend response shape.

### Verification

- New `useTaxHarvest()` hook can be called from a test component
- Resolver makes real API call (not stub)
- Adapter correctly transforms backend response
- Existing tax-harvest catalog descriptor still works
- No regressions in other resolvers

---

## Implementation Order

```
Week 1: Prep A + Prep C (parallel — independent)
Week 2: Prep B (can overlap with Prep A if different files)
```

Each prep should be:
1. Planned as a standalone implementation doc
2. Implemented with tests
3. Verified that existing container behavior is unchanged
4. Committed independently

After all three land, `SCENARIOS_OVERHAUL_SPEC.md` should be revised to reference the new hooks, and Phase 3 extraction becomes straightforward.

---

## Reference Documents

- `docs/planning/SCENARIOS_OVERHAUL_SPEC.md` — Phase 3 spec (Codex FAIL findings drive these refactors)
- `docs/planning/FRONTEND_NAV_SYNTHESIS_PLAN.md` — Overall nav restructure plan
- `docs/planning/ADVISOR_WORKFLOW_RESULTS.md` — Experiment data informing tool groupings
