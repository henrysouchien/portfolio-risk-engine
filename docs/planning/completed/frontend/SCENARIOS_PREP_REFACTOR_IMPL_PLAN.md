# Scenarios Prep Refactors — Implementation Plan (v3)

> **v3 changes:** Prep C: removed fabricated `asOf` from TaxHarvestSourceData, added resolver registry test.
> **v2 changes:** Addressed all findings from Codex review round 1 (3× FAIL).
> **Codex review:** Round 3 — all 3 preps PASS.

## Context

`SCENARIOS_OVERHAUL_SPEC.md` (Phase 3) got a Codex FAIL — 5/7 findings trace to ScenarioAnalysisContainer (~840 lines) and StrategyBuilderContainer (~465 lines) owning state that downstream tool views can't access once extracted. These three prep refactors make each Phase 3 extraction trivial.

**Dependency map:**
```
Prep A: useScenarioState ──── unblocks ──→ What-If, Stress Test, Monte Carlo tool views
Prep B: useOptimizationWorkflow ── unblocks ──→ Optimize, Backtest tool views
Prep C: Tax Harvest plumbing ──── unblocks ──→ Tax Harvest tool view (independent of A/B)
```

A and B can run in parallel. C is fully independent.

---

## Prep A: Extract `useScenarioState()` Hook

**Goal:** Move ~300 lines of position-derived state, templates, optimization cache reads, and history tracking out of ScenarioAnalysisContainer into a reusable hook.

### New Files

| File | Purpose | ~Lines |
|------|---------|--------|
| `ui/src/components/portfolio/scenario/templates.ts` | Pure functions: `buildScenarioTemplates()` + 5 helpers | 210 |
| `ui/src/components/portfolio/scenario/useScenarioState.ts` | Hook: positions, templates, opt cache, history tracking | 140 |
| `ui/src/components/portfolio/scenario/__tests__/templates.test.ts` | Unit tests for pure template functions | 150 |
| `ui/src/components/portfolio/scenario/__tests__/useScenarioState.test.tsx` | Hook + integration tests with renderHook | 250 |

### Modified Files

| File | Change |
|------|--------|
| `ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` | Remove ~300 lines, consume `useScenarioState()` |
| `ui/src/components/portfolio/scenario/index.ts` | Add barrel exports for new files |

### Extraction Map (from ScenarioAnalysisContainer.tsx)

**To `templates.ts`** (pure functions, zero React imports):
- `toNormalizedWeights()` (L174-197), `isCashLikeType()` (L199-202), `isBondOrCashType()` (L204-207), `isCashHolding()` (L209-210), `toTemplateHoldings()` (L212-229)
- `buildScenarioTemplates()` (L231-362) — generates 5 templates from holdings
- `TemplateHolding` interface (L97-102)

**To `useScenarioState.ts`** (hook):
- `initialPositions` useMemo (L595-607) — maps `positionsData?.holdings`
- `scenarioTemplates` useMemo (L414-417) — calls `buildScenarioTemplates()`
- `optimizationData` useMemo (L418-440) — **FIX: use `buildDataSourceQueryKey('optimization', ...)` from `@risk/connectors/resolver/core` instead of legacy `portfolioOptimizationKey()`** (see Cache Key Fix below)
- 3 `pendingHistoryParamsRef` refs (L459-464) + 3 history `useEffect` blocks (L619-656)
- `handleRunStressTest` / `handleRunMonteCarlo` wrappers (L658-667)
- Internally calls: `usePositions()`, `useQueryClient()`, `useScenarioHistory()` (from `@risk/connectors`)

**Also:** Delete duplicate `dataFrameToRows()` (L152-170) from container — use `helpers.ts` version.

**Stays in container:** `handleRunScenario()`, `transformedData` useMemo, type converters (`toScenarioConfig` etc.), loading/error guards, render tree.

### Cache Key Fix (Codex finding: broken lookup)

The container currently reads optimization cache using `portfolioOptimizationKey()` from `@risk/chassis/queryKeys.ts`, which produces keys like `['portfolioOptimization', portfolioId, strategy]`. But `useDataSource('optimization', ...)` writes cache using `buildDataSourceQueryKey()` from `@risk/connectors/resolver/core.ts`, which produces keys like `['sdk', 'optimization', '{"portfolioId":"...","strategy":"..."}']`.

**These keys don't match — the cache read always returns null.**

Fix: Import `buildDataSourceQueryKey` from `@risk/connectors` and use it in the hook:
```typescript
import { buildDataSourceQueryKey } from '@risk/connectors';
// ...
const optimizationData = useMemo<CachedOptimizationData | null>(() => {
  for (const strategy of ['min_variance', 'max_return'] as const) {
    const queryKey = buildDataSourceQueryKey('optimization', { portfolioId, strategy });
    const cached = queryClient.getQueryData<unknown>(queryKey);
    if (cached) return { ...transformCached(cached), strategy };
  }
  return null;
}, [queryClient, portfolioId]);
```

### Hook Interface (revised — matches spec)

```typescript
function useScenarioState(deps: {
  whatIfData: unknown;
  stressTestData: unknown;
  monteCarloResult: unknown;
  runStressTest: (scenarioId: string) => void;
  runMonteCarlo: (params: Record<string, unknown>) => void;
  currentPortfolioId: string | undefined;
}): {
  // Position-derived
  initialPositions: PortfolioPosition[];

  // Templates
  scenarioTemplates: ScenarioTemplate[];

  // Optimization cache
  optimizationData: CachedOptimizationData | null;

  // History (spec-required: addRun, getRuns, clearHistory)
  addRun: (type: ScenarioRunType, params: unknown, results: unknown) => void;
  clearHistory: () => void;
  getRuns: () => ScenarioHistoryRun[];

  // Pending history tracking (spec-required: per-type trackers)
  pendingHistoryTracking: {
    trackWhatIf: (params: unknown) => void;
    trackStress: (params: unknown) => void;
    trackMonteCarlo: (params: unknown) => void;
  };

  // History-aware run wrappers
  handleRunStressTest: (scenarioId: string) => void;
  handleRunMonteCarlo: (params: MonteCarloParams) => void;
}
```

The `addRun` and `getRuns` are delegated from the `@risk/connectors` `useScenarioHistory()` hook. The `pendingHistoryTracking` setters write to refs synchronously; the 3 useEffect blocks inside the hook auto-commit to history when results arrive.

### Key Risks
- Two hooks named `useScenarioHistory` exist (`@risk/connectors` data-layer vs `@risk/ui` UI-layer). The new hook imports from `@risk/connectors`.
- Duplicate type definitions: container has local `ScenarioTemplate`, `CachedOptimizationData`, `OptimizationStrategy` that duplicate `types.ts`. Remove from container, import from `types.ts`.
- `buildDataSourceQueryKey` must be exported from `@risk/connectors` (currently internal to `resolver/core.ts` — add to barrel export if needed).

### Test Strategy (expanded per Codex feedback)
- **Unit tests** (`templates.test.ts`): Pure function tests for template generation
- **Hook tests** (`useScenarioState.test.tsx`): renderHook tests for positions, templates, cache read
- **Integration tests** (`useScenarioState.test.tsx`): History auto-recording when whatIf/stress/monteCarlo data changes with pending params set; optimization cache visibility using `buildDataSourceQueryKey` to seed cache and verify hook reads it

---

## Prep B: Extract `useOptimizationWorkflow()` + Deferred Execution

**Goal:** (1) Convert `usePortfolioOptimization` from auto-fetch to deferred execution, (2) extract optimize→backtest pipeline into a reusable workflow hook.

### New Files

| File | Purpose | ~Lines |
|------|---------|--------|
| `connectors/src/features/optimize/helpers.ts` | Parsing utilities extracted from container | 80 |
| `connectors/src/features/optimize/hooks/useOptimizationWorkflow.ts` | Workflow hook: optimize→backtest→export pipeline | 200 |
| `connectors/src/features/optimize/__tests__/useOptimizationWorkflow.test.tsx` | Hook tests | 200 |

### Modified Files

| File | Change |
|------|--------|
| `connectors/src/features/optimize/hooks/usePortfolioOptimization.ts` | Auto-fetch → deferred (add `runId`/`params`/`runPortfolioId` state, gated `resolverParams`) |
| `connectors/src/features/optimize/__tests__/usePortfolioOptimization.test.tsx` | Update tests for deferred behavior |
| `connectors/src/features/optimize/hooks/index.ts` | Add workflow hook export |
| `connectors/src/index.ts` | Add `useOptimizationWorkflow` export |
| `chassis/src/catalog/types.ts` | Add `_runId?: number` to `SDKSourceParamsMap['optimization']` |
| `ui/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx` | Replace 4 hook calls + handler logic with `useOptimizationWorkflow()` |

### Step 1: Update `SDKSourceParamsMap['optimization']` (Codex finding: missing type)

In `chassis/src/catalog/types.ts` line 568, add `_runId`:
```typescript
'optimization': { portfolioId?: string; strategy?: string; _runId?: number };
```

### Step 2: Convert `usePortfolioOptimization` to Deferred

Current (auto-fetches on mount):
```typescript
const resolved = useDataSource('optimization',
  currentPortfolio ? { portfolioId: currentPortfolio.id, strategy } : undefined,
  { enabled: !!currentPortfolio }  // ← fires immediately
);
```

Target (follows `useBacktest` deferred pattern):
```typescript
const [params, setParams] = useState<{ strategy: OptimizationStrategy } | null>(null);
const [runId, setRunId] = useState<number | null>(null);
const [runPortfolioId, setRunPortfolioId] = useState<string | undefined>(undefined);

const resolverParams = useMemo(() => {
  if (!params || !runPortfolioId || runPortfolioId !== portfolioId) return undefined;
  return { portfolioId, strategy: params.strategy, _runId: runId ?? undefined };
}, [params, runId, portfolioId, runPortfolioId]);

const resolved = useDataSource('optimization', resolverParams, {
  enabled: !!resolverParams  // ← only fires after runOptimization()
});
```

`optimizeMinVariance()` / `optimizeMaxReturn()` now delegate to `runOptimization(strategy)` which sets params + runId + runPortfolioId in one shot.

**No feature flag needed** — the auto-fetch was a wasted API call, and StrategyBuilderContainer is the only consumer.

### Step 3: Extract Helpers

Move from StrategyBuilderContainer (L80-155) to `optimize/helpers.ts`:
- `toRecord`, `toNumber`, `toString`, `toNumberRecord`, `toBacktestPeriod`
- `parseConstraint`, `parseStrategyConfig`
- `StrategyConstraint`, `StrategyConfig` interfaces

### Step 4: Create `useOptimizationWorkflow`

Composes 4 hooks internally:
- `usePortfolioOptimization()` (refactored, deferred)
- `useBacktest()` (already deferred)
- `useStrategyTemplates()` (auto-fetch, appropriate)
- `useWhatIfAnalysis()` (for export-to-scenario)

Moves from container:
- `handleOptimize()` (L246-291) — dual behavior: template deploy (weights→backtest) vs optimization (→optimizeMinVariance/MaxReturn)
- `handleBacktest()` (L294-329) — gates on `optimizationData?.weights`
- `handleExportToScenario()` (L351-388) — creates scenario template, calls `whatIf.runScenario()`
- `templatesProp` transformation (L183-192) + `hasTickerWeights` derivation (L193)

### What Stays in Container (Codex finding: package boundary)

Per Codex review, these **must stay in the container**, not move to `@risk/connectors`:

- **`transformedOptimizationData`** (L196-233) — typed against `StrategyBuilderProps['optimizationData']` from `@risk/ui` strategy types. `@risk/connectors` has no `@risk/ui` dependency and cannot import UI types.
- **`handleSaveStrategy()`** (L332-348) — stub/logging only, view-specific.

The container imports raw data from the workflow hook and transforms it locally:
```typescript
const workflow = useOptimizationWorkflow();
// Container still owns the UI-specific transformation:
const transformedOptimizationData = useMemo(() => {
  return transformForStrategyBuilder(workflow.optimizationData, workflow.templates);
}, [workflow.optimizationData, workflow.templates]);
```

Container shrinks from ~465 to ~180 lines (transform + lifecycle + render).

### Workflow Hook Return Type (Codex finding: underspecified)

```typescript
interface UseOptimizationWorkflowReturn {
  // Optimization state (all fields the container currently destructures)
  optimizationData: OptimizationData | null;
  isOptimizing: boolean;
  optimizationError: string | null;
  hasOptimizationData: boolean;
  hasPortfolio: boolean;
  strategy: OptimizationStrategy;
  refetchOptimization: () => void;
  clearOptimizationError: () => void;

  // Optimization actions
  optimizeMinVariance: () => void;
  optimizeMaxReturn: () => void;

  // Backtest state (gated on optimization)
  backtestData: BacktestData | undefined;
  isBacktesting: boolean;
  backtestError: string | null;
  canBacktest: boolean;  // derived: Object.keys(optimizationData?.weights || {}).length > 0

  // Templates (auto-fetched reference data)
  templates: TemplateRow[];

  // Orchestration actions
  handleOptimize: (constraints: unknown) => Promise<void>;
  handleBacktest: (strategyConfig: unknown) => Promise<void>;
  handleExportToScenario: (strategyConfig: unknown) => void;
}
```

### Known Bug: export-to-scenario payload (Codex finding)

`handleExportToScenario()` currently receives **asset-class allocation** (stocks/bonds/commodities/cash/alternatives percentages) from `BuilderTab.tsx`, NOT ticker weights. The `new_weights` in the scenario template are asset-class keys, not tickers.

**Decision:** Preserve this behavior as-is in the workflow hook extraction. This is a pre-existing bug outside this refactor's scope. Document with a `// TODO: export sends asset-class allocation, not ticker weights (pre-existing)` comment.

### Note: `dependsOn: ['positions']` (Codex finding)

The optimization descriptor has `dependsOn: ['positions']` at `descriptors.ts` L354. This means a standalone optimize tool view still requires positions to be cached first. This is acceptable for now — Phase 3 tool views will load in a context where positions are already fetched. No descriptor change needed for this prep.

### Key Risks
- `handleOptimize()` has dual behavior: template deployment routes to backtest, optimization routes to optimizer. Workflow hook must preserve this routing.
- `IntentRegistry.triggerIntent()` calls in handlers must be preserved (fire-and-forget side effects for cross-component communication).
- `useWhatIfAnalysis()` dependency for `exportToScenario` — the workflow hook takes a dependency on the what-if hook.

---

## Prep C: Tax Harvest Frontend Plumbing

**Goal:** Wire the existing backend `suggest_tax_loss_harvest()` MCP tool through all frontend layers so Phase 3d can consume real data.

### Backend Response Reality Check (Codex finding: spec stale)

The spec's `harvest_candidates` / `estimated_tax_savings` field names are **stale**. The actual backend (`mcp_tools/tax_harvest.py`) uses:

| Format | Key Fields |
|--------|-----------|
| `summary` | `total_harvestable_loss`, `short_term_loss`, `long_term_loss`, `candidate_count`, `candidates[]`, `wash_sale_warnings[]`, `data_coverage_pct`, `metadata{}`, `disclaimer` |
| `agent` | `snapshot{total_harvestable_loss, candidate_count, top_candidates[], wash_sale_tickers[]}`, `flags[]`, `file_path` |

**Critical:** Flags are only returned in `agent` format (L1101-1102 of tax_harvest.py). Summary format has no `flags` field.

**Decision:** Use `format="agent"` in the backend route to get flags. The adapter will extract both `snapshot` fields and `flags` from the agent response.

### Flags Passthrough (Codex finding: useDataSource ignores top-level flags)

`useDataSource()` only reads flags from `_metadata.warnings` (useDataSource.ts L27), not top-level `flags`. Two options:

**Option A (chosen):** The adapter's `transform()` output includes a `_metadata.warnings` array populated from the agent `flags`, so `useDataSource` picks them up automatically. The adapter also preserves the full typed `flags` array in the `TaxHarvestSourceData` output for richer UI consumption.

```typescript
// In TaxHarvestAdapter.transform():
return {
  ...transformedData,
  flags: agentFlags,  // Full typed flags for tool view
  _metadata: {
    warnings: agentFlags
      .filter(f => f.severity === 'warning' || f.severity === 'error')
      .map(f => f.message),
  },
};
```

### New Files

| File | Purpose | ~Lines |
|------|---------|--------|
| `routes/tax_harvest.py` | `POST /api/tax-harvest` REST endpoint | 40 |
| `tests/routes/test_tax_harvest_route.py` | Backend route test | 60 |
| `connectors/src/adapters/TaxHarvestAdapter.ts` | Transform agent response to domain types | 150 |
| `connectors/src/features/taxHarvest/hooks/useTaxHarvest.ts` | Deferred execution hook | 110 |
| `connectors/src/features/taxHarvest/hooks/index.ts` | Barrel export | 3 |
| `connectors/src/features/taxHarvest/index.ts` | Barrel export | 2 |
| `connectors/src/adapters/__tests__/TaxHarvestAdapter.test.ts` | Adapter tests | 100 |
| `connectors/src/features/taxHarvest/__tests__/useTaxHarvest.test.tsx` | Hook tests | 150 |
| `connectors/src/resolver/__tests__/taxHarvestResolver.test.ts` | Resolver registry integration test | 80 |

### Modified Files

| File | Change |
|------|--------|
| `app.py` | Register `tax_harvest_router` |
| `chassis/src/catalog/types.ts` | Rewrite `TaxHarvestSourceData` to match actual backend agent response; update `SDKSourceParamsMap['tax-harvest']` with `_runId` |
| `chassis/src/catalog/descriptors.ts` | Update descriptor fields from stale `opportunities`/`total_estimated_savings` to real field names |
| `chassis/src/services/APIService.ts` | Add `getTaxHarvest()` method |
| `connectors/src/resolver/registry.ts` | Replace stub (L761-774) with real API call + adapter |
| `connectors/src/index.ts` | Add `useTaxHarvest` export |

### Implementation Order

**1. Backend route** (`routes/tax_harvest.py`):
- Pattern: `routes/income.py` (37 lines)
- Auth via session cookie → `auth_service.get_user_by_session()`
- Call `suggest_tax_loss_harvest(user_email=..., format="agent", ...)` — **agent format, not summary** (gets flags)
- Register in `app.py`
- Add `tests/routes/test_tax_harvest_route.py` — mock `suggest_tax_loss_harvest`, verify auth + response passthrough

**2. Update types** (`chassis/src/catalog/types.ts`):

Rewrite `TaxHarvestSourceData` (L356-359) to match agent format:
```typescript
export interface TaxHarvestSourceData {
  // Summary metrics (from snapshot)
  totalHarvestableLoss: number;
  shortTermLoss: number;
  longTermLoss: number;
  candidateCount: number;
  dataCoveragePct: number;
  positionsAnalyzed: number;
  positionsWithLots: number;

  // Top candidates (from snapshot.top_candidates)
  topCandidates: Array<{
    ticker: string;
    totalLoss: number;
    lotCount: number;
    holdingPeriods: string[];
    washSaleRisk: boolean;
  }>;

  // Wash sale info (from snapshot)
  washSaleTickers: string[];
  washSaleTickerCount: number;

  // Flags (from agent response top-level flags)
  flags: Array<{
    flag: string;
    severity: 'error' | 'warning' | 'info' | 'success';
    message: string;
  }>;

  // Metadata
  verdict: string;

  // _metadata for useDataSource flag derivation
  _metadata?: { warnings: string[] };
}
```

Update `SDKSourceParamsMap['tax-harvest']`:
```typescript
'tax-harvest': {
  portfolioId?: string;
  source?: string;
  minLoss?: number;
  sortBy?: string;
  institution?: string;
  account?: string;
  _runId?: number;
};
```

**3. Update descriptor** (`chassis/src/catalog/descriptors.ts` L757-784):
- Replace `fields` from `[opportunities, total_estimated_savings]` to `[topCandidates, totalHarvestableLoss, shortTermLoss, longTermLoss, flags]`
- Keep `flagTypes: [{ name: 'wash_sale_warning', ... }]`
- Keep `dependsOn: ['positions']` — standalone hook requires positions in cache (acceptable for Phase 3 context)

**4. APIService method** (`chassis/src/services/APIService.ts`):
- `getTaxHarvest(params?: GetTaxHarvestParams): Promise<TaxHarvestAgentResponse>`
- `POST /api/tax-harvest` with JSON body

**5. Adapter** (`connectors/src/adapters/TaxHarvestAdapter.ts`):
- Pattern: `BacktestAdapter.ts` (constructor, transform, cache)
- Input: agent-format response with `snapshot` + `flags`
- Output: `TaxHarvestSourceData` with camelCase fields + `_metadata.warnings` for useDataSource flag derivation
- Content-hash caching, 900s TTL

**6. Resolver** (`connectors/src/resolver/registry.ts`):
- Replace stub with: `api.getTaxHarvest()` → `adapter.transform()` → return
- No `requirePortfolio()` — backend operates on user-level positions

**7. Hook** (`connectors/src/features/taxHarvest/hooks/useTaxHarvest.ts`):
- Pattern: `useBacktest.ts` deferred execution
- `runTaxHarvest(params?)` trigger, `_runId` cache busting, portfolio-change reset

### Hook Return Type (Codex finding: never specified)

```typescript
interface UseTaxHarvestReturn {
  data: TaxHarvestSourceData | undefined;
  loading: boolean;
  isLoading: boolean;
  isRefetching: boolean;
  error: string | null;
  hasData: boolean;
  hasError: boolean;
  hasPortfolio: boolean;
  flags: Flag[];  // From useDataSource flag derivation + direct data.flags
  runTaxHarvest: (params?: TaxHarvestParams) => void;
  refetch: () => void;
}
```

### Key Risks
- No `requirePortfolio()` in resolver — tax harvest operates on user-level positions, not a portfolio config
- Backend returns `status: "success"` even with zero candidates — adapter must not treat this as error
- `dependsOn: ['positions']` in descriptor means the hook won't fire without positions cached first — acceptable in Phase 3 context where positions are always loaded
- Backend tax-harvest flags can emit `severity: 'success'` but the shared resolver `Flag` type only covers `error | warning | info`. Adapter must normalize `success` → `info` when populating `_metadata.warnings` and `data.flags`

### Test Strategy (expanded per Codex feedback)
- **Backend route test** (`test_tax_harvest_route.py`): Mock `suggest_tax_loss_harvest`, verify auth gating, response format
- **Adapter tests** (`TaxHarvestAdapter.test.ts`): Transform agent response, empty candidates, flags passthrough to `_metadata.warnings`, error status handling
- **Resolver registry test** (`taxHarvestResolver.test.ts`): Mock APIService `getTaxHarvest()`, verify resolver calls adapter, returns transformed data with `_metadata.warnings`, replaces stub behavior
- **Hook tests** (`useTaxHarvest.test.tsx`): Deferred execution, portfolio gating, re-run cache busting, error surfacing

---

## Execution Order

```
Prep A (useScenarioState)    ───┐
                                ├──→ then Prep B (useOptimizationWorkflow)
Prep C (Tax Harvest plumbing) ──┘    (can overlap with A if different files)
```

Each prep: implement → test → Codex review → commit independently.

## Verification (all preps)

1. `cd frontend && npx tsc --noEmit` — zero TypeScript errors
2. `cd frontend && npx vitest run` — all existing + new tests pass
3. `pytest tests/routes/test_tax_harvest_route.py` — backend route test passes (Prep C)
4. Container behavior unchanged (visual spot-check)
5. New hooks importable from target locations
