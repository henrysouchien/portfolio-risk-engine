# Monte Carlo Cross-View Context Passing

> **v7** — revised after Codex review rounds 1-6.

## Context

The Monte Carlo backend supports scenario conditioning (`resolved_weights`, `portfolio_value`, `vol_scale`) for cross-tool chaining, but the frontend has no way to trigger it. The `ScenariosRouter` already passes `toolContext` to all tools and `setActiveTool` accepts an optional context object — but Monte Carlo ignores it (`void context`), and no source tool passes context when navigating to Monte Carlo.

This plan wires three cross-tool flows:
1. **Stress Test → Monte Carlo**: "Simulate recovery" with shocked portfolio value + elevated vol
2. **Optimization → Monte Carlo**: "Simulate outcomes" with optimized weights
3. **What-If → Monte Carlo**: "Simulate forward" with scenario weights

---

## Step 1: Monte Carlo consumes context

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`

### 1a. Remove `void context`, read incoming context

Replace `void context` (line ~131) with context extraction:

```tsx
const incomingWeights = context?.weights as Record<string, number> | undefined
const incomingPortfolioValue = context?.portfolioValue as number | undefined
const incomingVolScale = context?.volScale as number | undefined
const incomingDistribution = context?.distribution as MonteCarloDistribution | undefined
const incomingSource = context?.source as string | undefined
const incomingLabel = context?.label as string | undefined
const hasIncomingContext = !!(incomingWeights || incomingPortfolioValue || incomingVolScale)
```

### 1b. Persist context in local state + seed form + auto-run

Context params must persist in local state so they're included in **every run** (not just the initial auto-run). The normal "Run Monte Carlo" button must also send `resolvedWeights`/`portfolioValue`/`volScale` when they came from upstream context.

**New state for conditioned params** (initialized from context):
```tsx
const [contextWeights, setContextWeights] = useState<Record<string, number> | undefined>(incomingWeights)
const [contextPortfolioValue, setContextPortfolioValue] = useState<number | undefined>(incomingPortfolioValue)
const [contextVolScale, setContextVolScale] = useState<number | undefined>(incomingVolScale)
```

**Seed distribution from context** — also update the dropdown to match so the UI doesn't lie:
```tsx
const [distribution, setDistribution] = useState<MonteCarloDistribution>(() => {
  if (incomingDistribution) return incomingDistribution
  // Force compatible distribution when context provides weights/vol_scale and cached is bootstrap
  const cached = validUiCache?.distribution ?? validRunCache?.params.distribution ?? "normal"
  if (cached === "bootstrap" && (incomingWeights || (incomingVolScale && incomingVolScale !== 1))) {
    return "normal"
  }
  return cached
})
```

**Update `handleRun`** to include context params:
```tsx
const handleRun = () => {
  const params: MonteCarloParams = {
    numSimulations,
    timeHorizonMonths,
    distribution,
    driftModel,
    ...(distribution === 't' ? { df } : {}),
    ...(contextWeights ? { resolvedWeights: contextWeights } : {}),
    ...(contextPortfolioValue ? { portfolioValue: contextPortfolioValue } : {}),
    ...(contextVolScale ? { volScale: contextVolScale } : {}),
  }
  pendingHistoryTracking.trackMonteCarlo(params)
  handleRunMonteCarlo(params)
}
```

**Auto-run via `toolRunParams` persistence** (survives unmount/remount):

Use the existing `toolRunParams` mechanism (already used for MC run cache) to track whether we've auto-run for this specific context. This prevents re-auto-run on remount (since `toolRunParams` persist across tool switches) and respects the "Clear context" action (since clearing local state makes `hasActiveContext` false).

```tsx
// Compute a stable, portfolio-scoped context key from incoming params (empty string if no context).
// Include portfolioId so cross-portfolio switches don't suppress auto-run.
// Sort weight keys for canonical ordering so logically identical sets produce the same key.
const contextKey = useMemo(() => {
  if (!incomingWeights && !incomingPortfolioValue && !incomingVolScale && !incomingDistribution) return ""
  const sortedWeights = incomingWeights ? Object.fromEntries(Object.entries(incomingWeights).sort()) : undefined
  return JSON.stringify({ pid: portfolioId, w: sortedWeights, pv: incomingPortfolioValue, vs: incomingVolScale, d: incomingDistribution })
}, [portfolioId, incomingWeights, incomingPortfolioValue, incomingVolScale, incomingDistribution])

const autoRunCache = toolRunParams["monte-carlo:auto-context"] as string | undefined

useEffect(() => {
  // Skip if: no active context, already ran for this context key, or portfolio not ready
  if (!hasActiveContext || !contextKey || autoRunCache === contextKey || !monteCarlo.hasPortfolio) {
    return
  }
  // Mark as auto-run for this context (persists across unmount/remount)
  setToolRunParams("monte-carlo:auto-context", contextKey)
  handleRun()
}, [hasActiveContext, contextKey, autoRunCache, monteCarlo.hasPortfolio])
```

When the user clears context, `hasActiveContext` becomes false, so the effect won't fire. If they navigate away and back with the same router context on the same portfolio, `autoRunCache === contextKey` prevents re-auto-run. If new context arrives (different weights/value/portfolio), the key changes and it auto-runs again.

**Design note**: `toolRunParams["monte-carlo:auto-context"]` stores a single key (not per-portfolio). This means switching portfolios A→B→A with identical context will re-auto-run on the A return. This is acceptable — the user is explicitly returning to a conditioned scenario, and a fresh run with the same params is cheap. True per-portfolio dedup would require a map, adding complexity for a near-impossible user flow.

Clear context button is in the context banner (see Step 1c).

### 1c. Show context banner (driven by local state, not router context)

Also persist `source` and `label` in local state so the banner and clear action are self-contained:

```tsx
const [contextSource, setContextSource] = useState<string | undefined>(incomingSource)
const [contextLabel, setContextLabel] = useState<string | undefined>(incomingLabel)
const hasActiveContext = !!(contextWeights || contextPortfolioValue || contextVolScale)
```

Banner (render before results, after form):
```tsx
{hasActiveContext && contextSource ? (
  <div className="flex items-center justify-between rounded-2xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
    <span>
      Running with context from {contextLabel ?? contextSource}
      {contextPortfolioValue ? ` · Starting value: ${formatCurrency(contextPortfolioValue)}` : ''}
      {contextVolScale && contextVolScale !== 1 ? ` · Vol scale: ${contextVolScale}x` : ''}
      {contextWeights ? ' · Custom weights applied' : ''}
    </span>
    <button
      type="button"
      className="ml-3 text-xs font-medium text-blue-700 underline hover:text-blue-900"
      onClick={() => {
        setContextWeights(undefined)
        setContextPortfolioValue(undefined)
        setContextVolScale(undefined)
        setContextSource(undefined)
        setContextLabel(undefined)
      }}
    >
      Clear context
    </button>
  </div>
) : null}
```

This is fully local — clearing context resets all local state. The router-level `toolContext` is not modified (it's read-once at mount via `incomingX` variables). On remount, `toolRunParams["monte-carlo:auto-context"]` persists and prevents re-auto-running for the same context key.

### 1d. Thread new params through the hook + API

**File**: `frontend/packages/connectors/src/features/monteCarlo/hooks/useMonteCarlo.ts`

Add to `MonteCarloParams`:
```typescript
resolvedWeights?: Record<string, number>;
portfolioValue?: number;
volScale?: number;
```

**File**: `frontend/packages/connectors/src/resolver/registry.ts`

Thread `resolvedWeights`, `portfolioValue`, `volScale` in the 'monte-carlo' resolver to manager call.

**File**: `frontend/packages/connectors/src/managers/PortfolioManager.ts`

Thread to cache service.

**File**: `frontend/packages/chassis/src/services/PortfolioCacheService.ts`

Thread to API service.

**File**: `frontend/packages/chassis/src/services/APIService.ts`

Add to request body (camelCase → snake_case):
```typescript
resolved_weights: params?.resolvedWeights,
portfolio_value: params?.portfolioValue,
vol_scale: params?.volScale,
```

**File**: `frontend/packages/chassis/src/catalog/types.ts`

Add `resolvedWeights`, `portfolioValue`, `volScale` to `SDKSourceParamsMap['monte-carlo']`.

**File**: `frontend/packages/chassis/src/types/api.ts`

Add to `MonteCarloApiResponse` the fields the engine already returns:
```typescript
vol_scale?: number;
weights_overridden?: boolean;
resolved_weights?: Record<string, number> | null;
```

Note: `portfolio_value` is a **request** param, not a response field. The response has `initial_value` which reflects the effective starting value (whether overridden or not).

---

## Step 2: Stress Test → Monte Carlo

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx`

Line 626 currently: `onClick={() => onNavigate("monte-carlo")}`

**Gate the button on having stress test results** — only show "Simulate recovery" when `stressTest.data` exists. When no results, keep the current "Run Monte Carlo" label with no context:

```tsx
<ExitRampButton
  label={stressTest.data ? "Simulate recovery" : "Run Monte Carlo"}
  onClick={() => {
    if (!stressTest.data) {
      onNavigate("monte-carlo")
      return
    }
    const impactPct = stressTest.data.estimatedImpactPct
    const impactDollar = stressTest.data.estimatedImpactDollar
    // Derive current portfolio value from dollar impact and pct
    const currentValue = impactDollar != null && Math.abs(impactPct) > 0.01
      ? Math.abs(impactDollar / (impactPct / 100))
      : undefined
    const stressedValue = currentValue != null && impactDollar != null
      ? currentValue + impactDollar
      : undefined

    onNavigate("monte-carlo", {
      ...(stressedValue != null ? { portfolioValue: stressedValue } : {}),
      volScale: 1.5,
      distribution: "t",
      source: "stress-test",
      label: `Post-${pinnedScenarioName} recovery`,
    })
  }}
/>
```

---

## Step 3: Optimization → Monte Carlo

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx`

Add a new ExitRampButton alongside the existing ones (~line 691):

```tsx
<ExitRampButton
  label="Simulate outcomes"
  onClick={() => onNavigate("monte-carlo", {
    weights: activeWeights,
    source: "optimize",
    label: "Optimized allocation",
  })}
  disabled={!canUseExitRamps}
  tooltip={!canUseExitRamps ? "Run an optimization to resolve weights first." : undefined}
/>
```

---

## Step 4: What-If → Monte Carlo

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/WhatIfTool.tsx`

Add a new ExitRampButton alongside the existing ones (~line 684):

```tsx
<ExitRampButton
  label="Simulate forward"
  onClick={() => onNavigate("monte-carlo", {
    weights: resolvedWeights,
    source: "what-if",
    label: importedLabel ?? "What-If scenario",
  })}
  disabled={!canUseExitRamps}
  tooltip={!canUseExitRamps ? "Run a scenario to resolve weights first." : undefined}
/>
```

---

## Step 5: REST endpoint + backend threading

These params are currently **MCP-only** — NOT on the REST endpoint. Must add them.

**File**: `models/response_models.py`

Add to `MonteCarloRequest`:
```python
resolved_weights: Optional[Dict[str, float]] = None
portfolio_value: Optional[float] = None
vol_scale: Optional[float] = 1.0

@validator("vol_scale", always=True)
def validate_vol_scale(cls, v, values):
    if v is not None and v <= 0:
        raise ValueError("vol_scale must be > 0")
    if values.get("distribution") == "bootstrap" and v is not None and not math.isclose(v, 1.0):
        raise ValueError("vol_scale must be 1.0 when distribution is 'bootstrap'")
    return v

@validator("portfolio_value")
def validate_portfolio_value(cls, v):
    if v is not None and v <= 0:
        raise ValueError("portfolio_value must be > 0")
    return v

@validator("resolved_weights")
def validate_resolved_weights_bootstrap(cls, v, values):
    if v is not None and values.get("distribution") == "bootstrap":
        raise ValueError("resolved_weights is not supported with bootstrap distribution")
    return v
```

Add to `MonteCarloResponse`:
```python
vol_scale: Optional[float] = None
weights_overridden: Optional[bool] = None
resolved_weights: Optional[Dict[str, float]] = None
```

**File**: `app.py`

Thread `resolved_weights`, `portfolio_value`, `vol_scale` through `_run_monte_carlo_workflow()` → `scenario_service.run_monte_carlo_simulation()` → engine. **No manual validation here** — all validation is on `MonteCarloRequest` via Pydantic validators (422). `app.py` is threading-only.

**File**: `services/scenario_service.py`

Add `resolved_weights`, `portfolio_value`, `vol_scale` params to `run_monte_carlo_simulation()`, pass to engine.

---

## Files Summary

**Monte Carlo context consumption (8 files)**:
1. `MonteCarloTool.tsx` — read context, toolRunParams-guarded auto-run, context banner, seed form state
2. `useMonteCarlo.ts` — extend MonteCarloParams with resolvedWeights/portfolioValue/volScale
3. `registry.ts` — thread new params
4. `PortfolioManager.ts` — thread
5. `PortfolioCacheService.ts` — thread
6. `APIService.ts` — add to request body
7. `catalog/types.ts` — add to SDKSourceParamsMap
8. `api.ts` — add vol_scale/weights_overridden/resolved_weights to MonteCarloApiResponse

**Source tools (3 files)**:
9. `StressTestTool.tsx` — "Simulate recovery" with guard + stressed value context
10. `OptimizeTool.tsx` — "Simulate outcomes" button with weights
11. `WhatIfTool.tsx` — "Simulate forward" button with weights

**Backend REST threading (4 files)**:
12. `models/response_models.py` — add to MonteCarloRequest + MonteCarloResponse
13. `app.py` — thread + validate through workflow
14. `services/scenario_service.py` — thread to engine
15. `tests/api/test_monte_carlo_api.py` — update existing monkeypatched signatures to accept new kwargs + add tests for: resolved_weights/portfolio_value/vol_scale threading, vol_scale <= 0 → 422, portfolio_value <= 0 → 422, bootstrap + resolved_weights → 422, bootstrap + vol_scale != 1 → 422 (all via Pydantic validators on MonteCarloRequest)

Note: `frontend/openapi-schema.json` is intentionally left stale — it's regenerated on demand, not auto-synced on every model change.

---

## Verification

1. **Stress Test → MC**: Run stress test → click "Simulate recovery" → MC auto-runs with shocked value, vol 1.5x, Student-t, context banner shows source and starting value
2. **Stress Test (no result) → MC**: Click "Run Monte Carlo" before running stress test → MC opens normally without context
3. **Optimize → MC**: Run optimization → click "Simulate outcomes" → MC auto-runs with optimized weights, context banner shows "Optimized allocation · Custom weights applied"
4. **What-If → MC**: Run what-if → click "Simulate forward" → MC auto-runs with scenario weights, context banner
5. **Direct MC**: Open MC directly → no context banner, no auto-run, runs normally with defaults
6. **TypeScript**: `tsc --noEmit` clean
7. **Backend tests**: `python3 -m pytest tests/test_monte_carlo.py tests/api/test_monte_carlo_api.py -x -v` (verify existing + new API tests pass)
