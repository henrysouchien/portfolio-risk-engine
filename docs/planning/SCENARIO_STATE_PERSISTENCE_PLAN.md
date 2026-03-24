# A0: Scenario State Persistence

**Status**: TODO
**Created**: 2026-03-24
**Reviewed**: Codex R1 FAIL (4), R2 FAIL (4), R3 FAIL (3), R4 FAIL (2), all addressed in v5 below

## Context

Navigating away from any scenario tool and returning forces a re-run. Root cause: `uiStore.setActiveView()` resets `activeTool` to `'landing'` and clears `toolContext`. This unmounts the tool component, destroying hook `useState` → `resolverParams` undefined → `useDataSource` disabled → data gone.

**Fix: persist run params, not results.** Hooks rehydrate from cached params on remount → `resolverParams` reconstitutes → React Query cache hit → instant data.

## R3 Findings and Fixes

1. **`useOptimizationWorkflow.ts` not in file list** → Added to file list (#7). Thread `cacheKey` option to inner `usePortfolioOptimization()` call.
2. **BacktestTool `lastSeedKeyRef` not hydrated** → Persist `lastSeedKey` in `:ui` cache (same pattern as WhatIf). Prevents mount-time reseeding from overwriting restored state.
3. **`:ui` cache entries not portfolio-scoped** → Include `portfolioId` in all `:ui` cache shapes. Validate with `validUiCache = uiCache?.portfolioId === portfolioId ? uiCache : undefined` before restoring.

## R2 Findings and Fixes

1. **Portfolio-switch clearing in unmounted ScenariosRouter** → Move clearing to the hooks themselves: each hook compares cached `runPortfolioId` against current `portfolioId` on mount and skips rehydration if they differ.
2. **WhatIf `runPortfolioIdRef` not hydrated + mount-time reseeding** → Hydrate the ref from cache. Persist `lastSeedKey` so the seeding guard (`lastSeedKeyRef.current === seedKey`) prevents re-seeding.
3. **Tool component UI state not cached** → Include tool component files. Each tool reads/writes component-level state (selectedScenarioId, numSimulations, etc.) to the cache alongside hook params.
4. **Shared hooks bleed across surfaces** → Scope caching with an optional `cacheKey` param. Only scenario tool call sites pass a key; other callers (StockLookup, HedgeTool, OptimizationWorkflow) don't participate.

## Files to modify

### Store layer
1. `frontend/packages/connectors/src/stores/uiStore.ts` — stop reset, add `toolRunParams`, update `resetToLanding`
1b. `frontend/packages/connectors/src/index.ts` — re-export `useToolRunParams`

### Hook layer (add optional `cacheKey` param, persist/restore)
2. `frontend/packages/connectors/src/features/stressTest/hooks/useStressTest.ts`
3. `frontend/packages/connectors/src/features/monteCarlo/hooks/useMonteCarlo.ts`
4. `frontend/packages/connectors/src/features/whatIf/hooks/useWhatIfAnalysis.ts`
5. `frontend/packages/connectors/src/features/backtest/hooks/useBacktest.ts`
6. `frontend/packages/connectors/src/features/optimize/hooks/usePortfolioOptimization.ts`
7. `frontend/packages/connectors/src/features/optimize/hooks/useOptimizationWorkflow.ts` — thread `cacheKey` to inner `usePortfolioOptimization()` call

### Tool components (pass cacheKey, cache/restore UI state)
7. `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx`
8. `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`
9. `frontend/packages/ui/src/components/portfolio/scenarios/tools/WhatIfTool.tsx`
10. `frontend/packages/ui/src/components/portfolio/scenarios/tools/BacktestTool.tsx`
11. `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx`

## Changes

### Step 1: Stop resetting activeTool on nav away (uiStore.ts, lines 327-337)

```tsx
// Before:
setActiveView: (activeView: ViewId) => {
  try { window.localStorage.setItem('activeView', activeView); } catch {}
  set((state) => ({
    activeView,
    ...(isScenariosSectionView(activeView)
      ? {}
      : {
          activeTool: state.activeTool === 'landing' ? state.activeTool : 'landing',
          toolContext: {},
        }),
  }));
},

// After:
setActiveView: (activeView: ViewId) => {
  try { window.localStorage.setItem('activeView', activeView); } catch {}
  set({ activeView });
},
```

### Step 2: Add toolRunParams to UIState (uiStore.ts)

```tsx
// In UIState interface:
toolRunParams: Record<string, unknown>;
setToolRunParams: (key: string, params: unknown) => void;
clearToolRunParams: (key?: string) => void;

// Implementation:
toolRunParams: {},
setToolRunParams: (key, params) => set((state) => ({
  toolRunParams: { ...state.toolRunParams, [key]: params },
})),
clearToolRunParams: (key) => set((state) => ({
  toolRunParams: key
    ? Object.fromEntries(Object.entries(state.toolRunParams).filter(([k]) => k !== key))
    : {},
})),

// Update resetToLanding (fixes R1 finding #3):
resetToLanding: () => set({
  activeTool: 'landing',
  toolContext: {},
  toolRunParams: {},
}),
```

### Step 3: Export selector (uiStore.ts)

```tsx
export const useToolRunParams = () => useUIStore((s) => ({
  setToolRunParams: s.setToolRunParams,
  clearToolRunParams: s.clearToolRunParams,
  toolRunParams: s.toolRunParams,
}));
```

Re-export from `@risk/connectors` index.

### Step 4: Hook integration pattern — scoped caching

Each hook gets an optional `cacheKey` param. When provided, the hook persists/restores its run params. When omitted (StockLookup, HedgeTool, OptimizationWorkflow internal usage), no caching occurs.

**Example: `useStressTest(options?: { cacheKey?: string })`**

```tsx
export const useStressTest = (options?: { cacheKey?: string }) => {
  const { setToolRunParams, toolRunParams } = useToolRunParams();
  const cacheKey = options?.cacheKey;
  const cached = cacheKey ? toolRunParams[cacheKey] as {
    scenarioId: string; runId: number; runPortfolioId: string;
  } | undefined : undefined;

  const currentPortfolio = useCurrentPortfolio();
  const portfolioId = currentPortfolio?.id;

  // Skip rehydration if portfolio changed (fixes R2 finding #1)
  const validCache = cached && cached.runPortfolioId === portfolioId ? cached : undefined;

  const [scenarioId, setScenarioId] = useState<string | null>(validCache?.scenarioId ?? null);
  const [runId, setRunId] = useState<number | null>(validCache?.runId ?? null);
  const [runPortfolioId, setRunPortfolioId] = useState<string | undefined>(validCache?.runPortfolioId);
  // ... rest of hook unchanged ...

  const runStressTest = useCallback((nextScenarioId: string) => {
    if (!currentPortfolio) return;
    const newRunId = Date.now();
    setRunPortfolioId(currentPortfolio.id);
    setScenarioId(nextScenarioId);
    setRunId(newRunId);
    if (cacheKey) {
      setToolRunParams(cacheKey, {
        scenarioId: nextScenarioId, runId: newRunId, runPortfolioId: currentPortfolio.id,
      });
    }
  }, [currentPortfolio, cacheKey, setToolRunParams]);
```

**WhatIf special handling** (fixes R2 finding #2):

`useWhatIfAnalysis` uses `runPortfolioIdRef` (ref, not state). Hydrate it from cache:
```tsx
const runPortfolioIdRef = useRef<string | undefined>(validCache?.runPortfolioId);
```

Also cache `lastSeedKey` so the WhatIfTool seeding guard prevents re-seeding on remount:
```tsx
// WhatIf cache shape includes:
{ scenarioParams, runId, runPortfolioId, inputMode, weightInputs, deltaInputs, lastSeedKey }
```

### Per-hook cache shapes:

| Hook | Cache shape |
|------|------------|
| `useStressTest` | `{ scenarioId, runId, runPortfolioId }` |
| `useMonteCarlo` | `{ params, runId, runPortfolioId }` |
| `useWhatIfAnalysis` | `{ scenarioParams, runId, runPortfolioId, inputMode, weightInputs, deltaInputs, lastSeedKey }` |
| `useBacktest` | `{ params, runId, runPortfolioId }` |
| `usePortfolioOptimization` | `{ strategy, params, runId, runPortfolioId }` |

### Step 5: Tool components — pass cacheKey + cache/restore UI state

Each tool component:
1. Passes `{ cacheKey: 'stress-test' }` to its hook
2. Reads/writes component-level UI state to a separate cache entry (e.g., `'stress-test:ui'`)

**StressTestTool** (fixes R2 finding #3, R3 finding #3 — portfolioId in `:ui` cache):
```tsx
const stressTest = useStressTest({ cacheKey: 'stress-test' });
const { setToolRunParams, toolRunParams } = useToolRunParams();
const portfolioId = stressTest.currentPortfolio?.id;
const uiCache = toolRunParams['stress-test:ui'] as {
  portfolioId: string; selectedScenarioId: string;
  lastRunScenarioId: string | null; lastRunScenarioName: string | null;
} | undefined;
const validUiCache = uiCache?.portfolioId === portfolioId ? uiCache : undefined;

const [selectedScenarioId, setSelectedScenarioId] = useState(validUiCache?.selectedScenarioId ?? "");
const [lastRunScenarioId, setLastRunScenarioId] = useState(validUiCache?.lastRunScenarioId ?? null);
const [lastRunScenarioName, setLastRunScenarioName] = useState(validUiCache?.lastRunScenarioName ?? null);

// Save UI state after run (include portfolioId for scoping):
useEffect(() => {
  if (lastRunScenarioId && portfolioId) {
    setToolRunParams('stress-test:ui', {
      portfolioId, selectedScenarioId, lastRunScenarioId, lastRunScenarioName,
    });
  }
}, [selectedScenarioId, lastRunScenarioId, lastRunScenarioName, portfolioId, setToolRunParams]);
```

**MonteCarloTool** (R3 finding #3 — portfolioId in `:ui` cache):
```tsx
const monteCarlo = useMonteCarlo({ cacheKey: 'monte-carlo' });
const uiCache = toolRunParams['monte-carlo:ui'] as {
  portfolioId: string; numSimulations: number; timeHorizonMonths: number;
} | undefined;
const validUiCache = uiCache?.portfolioId === portfolioId ? uiCache : undefined;
const [numSimulations, setNumSimulations] = useState(validUiCache?.numSimulations ?? 1000);
const [timeHorizonMonths, setTimeHorizonMonths] = useState(validUiCache?.timeHorizonMonths ?? 12);
```

**WhatIfTool** (fixes R2 finding #2 mount-time reseeding, R4 finding #1 — portfolioId in `:ui`):
```tsx
const whatIfAnalysis = useWhatIfAnalysis({ cacheKey: 'what-if' });
const portfolioId = whatIfAnalysis.currentPortfolio?.id;
// Persist lastSeedKey ref so the seeding guard (lastSeedKeyRef.current === seedKey) prevents re-seeding
const uiCache = toolRunParams['what-if:ui'] as { portfolioId: string; lastSeedKey: string } | undefined;
const validUiCache = uiCache?.portfolioId === portfolioId ? uiCache : undefined;
const lastSeedKeyRef = useRef(validUiCache?.lastSeedKey ?? "");
```

**BacktestTool** (+ lastSeedKeyRef hydration to prevent mount-time reseeding — same pattern as WhatIf, fixes R3 finding #2):
```tsx
const backtest = useBacktest({ cacheKey: 'backtest' });
const uiCache = toolRunParams['backtest:ui'] as {
  portfolioId: string; rows: WeightRow[]; activeWeights: Record<string, number>;
  benchmark: string; period: string; lastSeedKey: string;
} | undefined;
const validUiCache = uiCache?.portfolioId === portfolioId ? uiCache : undefined;
const [rows, setRows] = useState<WeightRow[]>(validUiCache?.rows ?? [createWeightRow()]);
const [activeWeights, setActiveWeights] = useState<Record<string, number>>(validUiCache?.activeWeights ?? {});
const [benchmark, setBenchmark] = useState(validUiCache?.benchmark ?? "SPY");
const [period, setPeriod] = useState(validUiCache?.period ?? "3Y");
const lastSeedKeyRef = useRef(validUiCache?.lastSeedKey ?? "");
// Seeding guard (lastSeedKeyRef.current === seedKey) prevents re-seeding
```

**OptimizeTool** (R3 finding #1 — thread cacheKey through workflow, R3 finding #3 — portfolioId):
```tsx
// OptimizeTool passes cacheKey to useOptimizationWorkflow:
const workflow = useOptimizationWorkflow({ cacheKey: 'optimize' });
// useOptimizationWorkflow threads it: usePortfolioOptimization({ cacheKey: options?.cacheKey })

const uiCache = toolRunParams['optimize:ui'] as {
  portfolioId: string; strategy: OptimizationStrategy; selectedTemplateId: string | null;
  activeWeights: Record<string, number>; activeWeightSource: string; nPoints: number;
} | undefined;
const validUiCache = uiCache?.portfolioId === portfolioId ? uiCache : undefined;
const [strategy, setStrategy] = useState<OptimizationStrategy>(validUiCache?.strategy ?? workflow.strategy);
const [selectedTemplateId, setSelectedTemplateId] = useState(validUiCache?.selectedTemplateId ?? NO_TEMPLATE);
const [nPoints, setNPoints] = useState(validUiCache?.nPoints ?? 20);
```

### Step 6: Scoped caching prevents cross-surface bleed (fixes R2 finding #4)

Non-scenario callers don't pass `cacheKey`:
- `StockLookupContainer` → `useWhatIfAnalysis()` (no cacheKey → no caching)
- `HedgeTool` → `useStressTest()` (no cacheKey → no caching)
- `useOptimizationWorkflow` → `useBacktest()`, `useWhatIfAnalysis()` (no cacheKey → no caching)

Only the dedicated tool components pass cacheKey:
- `StressTestTool` → `useStressTest({ cacheKey: 'stress-test' })`
- `MonteCarloTool` → `useMonteCarlo({ cacheKey: 'monte-carlo' })`
- etc.

### Step 7: Portfolio-switch clearing (fixes R2 finding #1)

Instead of clearing in ScenariosRouter (which is unmounted), each hook handles it:

The `validCache` check at mount time already handles this:
```tsx
const validCache = cached && cached.runPortfolioId === portfolioId ? cached : undefined;
```

If the portfolio changed while the user was on another view, the cached `runPortfolioId` won't match `portfolioId` → `validCache` is `undefined` → hook initializes with null params → no stale data.

The existing per-hook portfolio-change effect (e.g., `useStressTest` lines 30-39) clears local state when portfolio changes while mounted. On unmount+remount with new portfolio, the `validCache` guard handles it.

Also clear stale cache entries proactively: when any hook detects a portfolio mismatch, clear its own cache key:
```tsx
useEffect(() => {
  if (cacheKey && cached && cached.runPortfolioId !== portfolioId) {
    setToolRunParams(cacheKey, undefined);
  }
}, [cacheKey, cached, portfolioId, setToolRunParams]);
```

## What changes behaviorally

- Navigate away → back: same tool, same results (React Query cache hit)
- Switch portfolios: cached params invalidated (runPortfolioId mismatch), tools show fresh state
- "Back to Scenarios" / workflow abandon: `resetToLanding()` clears all params
- Non-scenario surfaces using same hooks: unaffected (no cacheKey)
- Data-layer invalidation: React Query handles it; params are still valid

## Verification

1. `cd frontend && npx tsc --noEmit` — no type errors
2. Run stress test → Holdings → back → stress test results + selected scenario visible
3. Run Monte Carlo → Risk → back → results visible, numSimulations/timeHorizon preserved
4. Run What-If with delta mode → Performance → back → delta inputs restored, no re-seeding
5. Switch portfolio while on Holdings → return to Scenarios → tool selected but no stale data
6. Open Stock Lookup → run what-if there → return to Scenarios What-If → scenario tool has its own state
7. Click "Back to Scenarios" breadcrumb → landing, all cached params cleared
8. Frontend tests pass
