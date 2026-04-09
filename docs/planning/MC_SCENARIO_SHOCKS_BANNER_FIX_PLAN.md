# MC Scenario Shocks Banner Fix Plan

**Bug**: When navigating from StressTestTool to MonteCarloTool via "Simulate recovery" exit ramp, the context banner does not show "Scenario-conditioned drift" even though the backend correctly applies scenario shocks.

**Status**: Draft v3 (re-scoped to diagnostic-first after v2 Codex review)  
**Files**: 2 changed, 0 new  
**Risk**: Low (UI-only, no backend changes)

---

## Codex Review v1 Findings (FAIL)

The v1 plan proposed two fixes: (1) `key={activeTool}` on Suspense, (2) blanket `useEffect([context])` sync. Codex rejected both:

1. **`key` prop is unnecessary**: `ScenariosRouter.tsx` renders `StressTestTool` and `MonteCarloTool` as distinct `React.lazy()` component types. React reconciliation already unmounts on cross-type switch. A `key` prop adds no value.
2. **Same-instance rerender is the real `useState` hazard**: The `useState(() => {...})` capture at `MonteCarloTool.tsx:280` only stales when the component receives new `context` props WITHOUT unmounting — not the cross-tool navigation case.
3. **Test plan insufficient**: The proposed router test passes with or without the `key` fix. Missing: MC rerender test that changes context without unmounting.
4. **`useEffect([context])` conflicts with `handleClearContext`**: User clicks "Clear context" → state cleared. Parent re-emits same `context` prop on next render → `useEffect` repopulates state, undoing the user's action.

---

## Codex Review v2 Findings (FAIL — 4 issues)

The v2 plan correctly identified the same-instance context hazard and proposed a `useEffect` + `contextDismissedRef` guard. However:

### Finding 1: Auto-run key uses stale `incoming*` values

The `contextKey` at `MonteCarloTool.tsx:642` mixes `incoming*` (frozen at mount via `useState(() => {...})` at line 280) and `context*` (live state):

```tsx
// contextKey — line 642-669
const contextKey = useMemo(() => {
  if (!incomingWeights && !incomingPortfolioValue && !incomingVolScale && !incomingDistribution && !contextScenarioShocks) {
    return ""
  }
  return JSON.stringify({
    w: sortedWeights,           // from incomingWeights (STALE)
    pv: incomingPortfolioValue, // STALE
    vs: incomingVolScale,       // STALE
    d: incomingDistribution,    // STALE
    ss: sortedScenarioShocks,   // from contextScenarioShocks (LIVE)
  })
}, [contextScenarioShocks, incomingDistribution, incomingPortfolioValue, incomingVolScale, incomingWeights, portfolioId])
```

The `incoming*` variables are destructured from `initialContext` (line 299-305), which is the frozen `useState` value. If the `useEffect` from Change 2 updates `contextWeights` etc., the banner shows correct values but `contextKey` still uses the stale `incoming*` references. This means:
- Auto-run gate (`autoRunCache === contextKey`) could use wrong key
- The "already ran with this context" dedup could fail

**Resolution**: Change 2's `useEffect` cannot fix `incoming*` because they're derived from `initialContext` (a `useState` value that never changes). The `contextKey` must be refactored to use `context*` state variables exclusively. See Change 2 below.

### Finding 2: Empty context contradicts store contract

The v2 plan said "preserve stale local context on `context={{}}` rerender", but `setActiveTool(tool)` in `uiStore.ts:332-334` explicitly clears `toolContext` to `{}`:

```tsx
setActiveTool: (activeTool, toolContext?) => set({
  activeTool,
  toolContext: toolContext ?? {},
})
```

**All same-tool `setActiveTool` calls send fresh context** — there's no legitimate case where context becomes `{}` while the user's previous context should be preserved. The two ways `toolContext` becomes `{}` are:
1. `setActiveTool("monte-carlo")` with no context arg — intentional, means "no context"
2. `resetToLanding()` — means "go home"

Both are intentional "clear context" signals. The v2 plan's no-op guard on empty context was wrong.

**Resolution**: The `useEffect` should treat empty context (`{}`) as "clear everything" — same as the user clicking "Clear context". This is consistent with the store contract. The `contextDismissedRef` only guards against same-object-reference re-renders from unrelated Zustand updates, NOT from `setActiveTool` calls. See Change 2 below.

**Test 3 updated**: The empty-context rerender test now asserts that context IS cleared.

### Finding 3: Change 1 depends on nonexistent field

The v2 plan's fallback `stressTest.data.factorShocks` does not exist. The actual data shape is:

- `StressTestData.factorContributions`: `Array<{ factor, shock, portfolioBeta, contributionPct }>` (from `StressTestAdapter.ts:21`)
- `StressTestApiResponse.factor_contributions`: `Array<{ factor, shock, portfolio_beta, contribution_pct }>` (from `api.ts:191`)

Neither has a `factorShocks: Record<string, number>` field. The shocks are embedded in `factorContributions[].shock` alongside portfolio betas.

**Resolution**: Change 1 is replaced with a reconstruction from `factorContributions`. See Change 1 below.

### Finding 4: `contextDismissedRef` never resets on new valid context

After "Clear context", `contextDismissedRef.current = true` persists for the component's lifetime. If `setActiveTool("monte-carlo", newContext)` is called while MC stays mounted, the new context is ignored because the ref is still `true`.

**Resolution**: Reset `contextDismissedRef` when context genuinely changes (new object reference with actual content). The `useEffect` checks for this. See Change 2 below.

---

## Strategy: Diagnostic-First, Then Fix

Given that:
1. The cross-tool navigation path (stress-test → monte-carlo) theoretically works correctly (React remounts, `useState` initializer captures fresh context)
2. The actual bug has never been reproduced with diagnostic instrumentation
3. The v2 plan's fixes introduced new correctness issues (stale `contextKey`, wrong empty-context semantics, nonexistent field)
4. The same-instance hazard is still theoretical (no existing code path triggers it)

**The plan is split into two phases:**

### Phase 1: Diagnostic instrumentation (implement now)

Add targeted `console.warn` logging at the three critical junctures to identify the real failure point in the next live reproduction. These are `console.warn` (not `console.log`) so they're visible in browser devtools even with info-level filtering.

### Phase 2: Defensive fix (implement after Phase 1 confirms root cause)

Apply the corrected Change 1 + Change 2 once we know WHERE the data is lost. If Phase 1 reveals a completely different root cause, this phase may be replaced.

---

## Phase 1: Diagnostic Instrumentation

### Diagnostic 1: StressTestTool shock capture

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx`  
**Location**: Inside the `useEffect` that sets `lastRunScenarioShocks` (line 170-184)

```tsx
useEffect(() => {
  if (!stressTest.data) {
    return
  }

  const pinnedScenarioId = stressTest.data.scenarioId ?? null
  const executedScenario = scenarioOptions.find((scenario) => scenario.id === stressTest.data?.scenarioId)
  const pinnedScenarioName = executedScenario?.name
    ?? stressTest.data.scenarioName
    ?? "Stress scenario"

  // DIAGNOSTIC: MC banner bug — verify shock capture
  if (!executedScenario) {
    console.warn("[StressTest→MC] executedScenario NOT FOUND", {
      scenarioId: stressTest.data.scenarioId,
      availableIds: scenarioOptions.map((s) => s.id),
      factorContributions: stressTest.data.factorContributions?.length ?? 0,
    })
  } else {
    console.warn("[StressTest→MC] executedScenario FOUND", {
      scenarioId: stressTest.data.scenarioId,
      shockKeys: Object.keys(executedScenario.shocks),
      shockCount: Object.keys(executedScenario.shocks).length,
    })
  }

  setLastRunScenarioId(pinnedScenarioId)
  setLastRunScenarioName(pinnedScenarioName)
  setLastRunScenarioShocks(executedScenario?.shocks ?? null)
}, [scenarioOptions, stressTest.data])
```

### Diagnostic 2: StressTestTool navigation handler

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx`  
**Location**: `handleMonteCarloNavigation` (line 541), before calling `onNavigate`

```tsx
const handleMonteCarloNavigation = () => {
  // DIAGNOSTIC: MC banner bug — verify shocks at navigation time
  console.warn("[StressTest→MC] handleMonteCarloNavigation", {
    hasData: !!stressTest.data,
    lastRunScenarioShocks: lastRunScenarioShocks
      ? `${Object.keys(lastRunScenarioShocks).length} factors`
      : "null",
    scenarioShocksPassedToMC: (lastRunScenarioShocks ?? undefined) ? "truthy" : "undefined",
  })

  if (!stressTest.data) {
    onNavigate("monte-carlo")
    return
  }
  // ... rest unchanged
```

### Diagnostic 3: MonteCarloTool context reception

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`  
**Location**: After `initialContext` state initialization (after line 305)

```tsx
const incomingLabel = initialContext.label

// DIAGNOSTIC: MC banner bug — verify context at MC mount
console.warn("[MC] mount context", {
  rawContextKeys: Object.keys(context),
  scenarioShocks: context.scenarioShocks ? "present" : "absent",
  normalizedScenarioShocks: incomingScenarioShocks
    ? `${Object.keys(incomingScenarioShocks).length} factors`
    : "undefined",
  source: incomingSource,
  label: incomingLabel,
})
```

### Expected diagnostic outcomes

| Scenario | Diagnostic 1 | Diagnostic 2 | Diagnostic 3 | Root cause |
|---|---|---|---|---|
| **Scenario A**: executedScenario not found | "NOT FOUND" | "null" | "absent" | scenarioId mismatch between API response and scenario options |
| **Scenario B**: shocks captured but lost at nav | "FOUND" | "null" | "absent" | State timing issue between `useEffect` and navigation handler |
| **Scenario C**: shocks passed but MC doesn't see | "FOUND" | "truthy" | "absent" | Store/router context propagation bug |
| **Scenario D**: MC sees shocks but banner fails | "FOUND" | "truthy" | "present" | `normalizeContextScenarioShocks` rejects data shape, or render logic bug |
| **Scenario E**: Everything works | "FOUND" | "truthy" | "present" + banner shows | Bug is intermittent / environment-specific |

---

## Phase 2: Defensive Fixes (post-diagnostic)

These fixes are correct regardless of which scenario Phase 1 reveals, but their priority depends on the root cause.

### Change 1: Reconstruct shocks from `factorContributions` as fallback

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx`  
**Lines**: 170-184

The `executedScenario?.shocks` lookup depends on finding the scenario in `scenarioOptions` by ID match. If the ID format differs between the API response (`stressTest.data.scenarioId`) and the scenario definitions (`stressScenarios.data` keys), this lookup fails and `lastRunScenarioShocks` is null.

The stress test response includes `factorContributions` which has the shock values per factor. We can reconstruct the `Record<string, number>` shape from this array.

**Before**:
```tsx
setLastRunScenarioShocks(executedScenario?.shocks ?? null)
```

**After**:
```tsx
const shocksFromContributions = stressTest.data.factorContributions.length > 0
  ? Object.fromEntries(
      stressTest.data.factorContributions.map((fc) => [fc.factor, fc.shock])
    )
  : null
setLastRunScenarioShocks(executedScenario?.shocks ?? shocksFromContributions)
```

**Why this is safe**: `factorContributions` comes from the same backend stress test run. The `shock` value on each contribution is the same factor shock used in the scenario — just embedded in a richer structure. The reconstructed `Record<string, number>` is shape-compatible with `scenarioShocks` as consumed by MonteCarloTool.

**Trade-off**: The `factorContributions` shocks might differ slightly from the `scenarioOptions` shocks if the backend modifies them (e.g., severity scaling). But having approximate shocks is better than having no shocks (which is the current failure mode).

### Change 2: Context sync with corrected semantics

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`  
**Insert after**: Line 330 (after `contextLabel` state declaration)

This addresses four issues simultaneously:
1. Same-instance context prop changes (the core vulnerability)
2. Empty context clears state (correct store contract semantics)
3. `contextDismissedRef` resets on genuinely new context
4. `contextKey` uses `context*` state instead of `incoming*` (fixes stale key)

**Add context sync effect after line 330**:
```tsx
const contextDismissedRef = useRef(false)
const prevContextRef = useRef(context)

useEffect(() => {
  // If context object reference changed, reset dismissed state
  // (new setActiveTool call = new intent, even after a prior Clear)
  if (context !== prevContextRef.current) {
    prevContextRef.current = context
    contextDismissedRef.current = false
  }

  // Don't repopulate if user explicitly dismissed context via Clear button
  if (contextDismissedRef.current) {
    return
  }

  const newScenarioShocks = normalizeContextScenarioShocks(context.scenarioShocks)
  const newSource = typeof context.source === "string" ? context.source : undefined
  const newLabel = typeof context.label === "string" ? context.label : undefined
  const newWeights = normalizeContextWeights(context.weights)
  const newPortfolioValue = normalizeContextNumber(context.portfolioValue)
  const newVolScale = normalizeContextNumber(context.volScale)
  const newDistribution = normalizeContextDistribution(context.distribution)

  // Check if we have any actual context to apply
  const hasContent = !!(newScenarioShocks || newSource || newWeights
    || newPortfolioValue !== undefined || newVolScale !== undefined)

  if (!hasContent) {
    // Empty context = explicit "no context" signal from store
    // Clear all context state to match store contract
    setContextWeights(undefined)
    setContextPortfolioValue(undefined)
    setContextVolScale(undefined)
    setContextScenarioShocks(undefined)
    setContextSource(undefined)
    setContextLabel(undefined)
    return
  }

  // Sync new context values
  setContextWeights(newWeights)
  setContextPortfolioValue(newPortfolioValue)
  setContextVolScale(newVolScale)
  setContextScenarioShocks(newScenarioShocks)
  setContextSource(newSource)
  setContextLabel(newLabel)

  if (newDistribution) {
    setDistribution(newDistribution)
  }
}, [context])
```

**Update `handleClearContext`** to set the dismissed ref:

```tsx
const handleClearContext = useCallback(() => {
  contextDismissedRef.current = true
  setContextWeights(undefined)
  setContextPortfolioValue(undefined)
  setContextVolScale(undefined)
  setContextScenarioShocks(undefined)
  setContextSource(undefined)
  setContextLabel(undefined)
}, [])
```

**Refactor `contextKey` to use `context*` state exclusively** (line 642-669):

```tsx
const contextKey = useMemo(() => {
  if (!contextWeights && !contextPortfolioValue && !contextVolScale && !contextScenarioShocks) {
    return ""
  }

  const sortedWeights = contextWeights
    ? Object.fromEntries(Object.entries(contextWeights).sort(([left], [right]) => left.localeCompare(right)))
    : undefined
  const sortedScenarioShocks = contextScenarioShocks
    ? Object.fromEntries(Object.entries(contextScenarioShocks).sort(([left], [right]) => left.localeCompare(right)))
    : undefined

  return JSON.stringify({
    pid: portfolioId,
    w: sortedWeights,
    pv: contextPortfolioValue,
    vs: contextVolScale,
    d: distribution,
    ss: sortedScenarioShocks,
  })
}, [
  contextScenarioShocks,
  contextPortfolioValue,
  contextVolScale,
  contextWeights,
  distribution,
  portfolioId,
])
```

**Why this is safe**: `contextKey` is used for two purposes: (1) auto-run dedup via `autoRunCache`, (2) triggering auto-run on mount with context. Both should react to the live `context*` state, not the frozen `incoming*` values. After this change:
- On fresh mount: `context*` state == `incoming*` values (both from same context prop), so behavior is identical.
- On same-instance prop change: `context*` state is updated by the `useEffect`, `contextKey` recomputes, auto-run fires correctly.
- After "Clear context": `context*` state is `undefined`, `contextKey` is `""`, auto-run gate returns early. Correct.

### Dropped: `key={activeTool}` on Suspense

Still not needed. React already remounts on cross-type component switch.

---

## Other Tools: Vulnerability Audit

| Tool | Context access pattern | Vulnerable? | Notes |
|---|---|---|---|
| **WhatIfTool** | `useMemo(() => ..., [context.weights])` | **No** | Reactive via `useMemo` deps. Context changes recompute immediately. |
| **BacktestTool** | `useMemo(() => normalizeWeights(context.weights), [context.weights])` | **No** | Same reactive `useMemo` pattern. |
| **OptimizeTool** | Direct reads: `context?.riskContext`, `context?.mcRunId` | **No** | Reads `context` props directly in render, no memoization. Always current. |
| **StressTestTool** | `_context` (destructured and unused) | **No** | Does not consume context at all. |
| **HedgeTool** | `context.label` (direct read) | **No** | Direct prop read, always current. |
| **RebalanceTool** | Passes through to child | **No** | Direct prop threading. |
| **TaxHarvestTool** | Does not consume context | **No** | N/A. |

**MonteCarloTool is the only tool** using the `useState(() => ...)` pattern for context capture.

---

## Test Cases

### Existing tests (no changes needed)

The existing test file `tools/__tests__/MonteCarloTool.test.tsx` already covers:
- Scenario shocks activate context banner (line 247-259)
- Scenario shocks appear in auto-context key (line 261-288)
- Scenario shocks threaded into run params (line 290-304)
- Clear context removes scenario shocks (line 306-330)
- Bootstrap distribution coerced to normal with shocks (line 332-354)

These tests all render fresh (no reuse), so they test the `useState` initializer path. They will continue to pass.

### New test 1: MC context sync on prop change without remount

```tsx
it("syncs context state when context prop changes without remount", () => {
  // Initial render with empty context
  const { rerender } = renderTool({})
  expect(screen.queryByText(/Scenario-conditioned drift/)).toBeNull()

  // Rerender with scenarioShocks context (simulating same-instance prop change)
  rerender(
    <MonteCarloTool
      context={{ scenarioShocks: { market: -0.15 }, source: "stress-test", label: "Post-crash recovery" }}
      onNavigate={vi.fn()}
    />
  )

  expect(screen.getByText(/Running with context from Post-crash recovery/)).toBeInTheDocument()
  expect(screen.getByText(/Scenario-conditioned drift/)).toBeInTheDocument()
})
```

This tests the `useEffect` defensive fix: component NOT unmounted, context prop changes. The effect syncs state.

### New test 2: Clear context is not overridden by parent re-emit

```tsx
it("does not repopulate context after user clicks Clear context", () => {
  const context = { scenarioShocks: { market: -0.15 }, source: "stress-test" }
  const { rerender } = renderTool(context)

  expect(screen.getByText(/Scenario-conditioned drift/)).toBeInTheDocument()

  // User clicks "Clear context"
  fireEvent.click(screen.getByText("Clear context"))
  expect(screen.queryByText(/Scenario-conditioned drift/)).toBeNull()

  // Parent re-renders with same context prop (e.g., unrelated Zustand update)
  rerender(
    <MonteCarloTool context={context} onNavigate={vi.fn()} />
  )

  // Context should stay cleared — user's action is respected
  // (same context object reference → dismissed ref still true)
  expect(screen.queryByText(/Scenario-conditioned drift/)).toBeNull()
})
```

This tests the `contextDismissedRef` guard: after "Clear context", the `useEffect` must NOT repopulate state even if the parent re-emits the same context object.

### New test 3: Empty context clears stale context state

```tsx
it("clears stale context when context prop becomes empty on rerender", () => {
  const { rerender } = renderTool({
    scenarioShocks: { market: -0.15 },
    source: "stress-test",
  })

  expect(screen.getByText(/Scenario-conditioned drift/)).toBeInTheDocument()

  // Parent sends empty context (e.g., setActiveTool("monte-carlo") with no context arg)
  rerender(<MonteCarloTool context={{}} onNavigate={vi.fn()} />)

  // Empty context = "no context" signal → banner should be cleared
  expect(screen.queryByText(/Scenario-conditioned drift/)).toBeNull()
})
```

This tests that empty context correctly clears state, matching the store's `setActiveTool` contract where omitting context means `toolContext: {}`.

### New test 4: New context after Clear resets dismissed state

```tsx
it("accepts new context after prior Clear if context object reference changes", () => {
  const originalContext = { scenarioShocks: { market: -0.15 }, source: "stress-test" }
  const { rerender } = renderTool(originalContext)

  expect(screen.getByText(/Scenario-conditioned drift/)).toBeInTheDocument()

  // User clicks "Clear context"
  fireEvent.click(screen.getByText("Clear context"))
  expect(screen.queryByText(/Scenario-conditioned drift/)).toBeNull()

  // New context arrives (different object reference = new setActiveTool call)
  const newContext = { scenarioShocks: { market: -0.25 }, source: "stress-test", label: "New scenario" }
  rerender(
    <MonteCarloTool context={newContext} onNavigate={vi.fn()} />
  )

  // New context should be accepted — dismissed ref was reset on new object reference
  expect(screen.getByText(/Scenario-conditioned drift/)).toBeInTheDocument()
  expect(screen.getByText(/Running with context from New scenario/)).toBeInTheDocument()
})
```

This tests Finding 4's fix: `contextDismissedRef` resets when a genuinely new context object arrives after a prior Clear.

---

## Banner Conditional Verification

After Phase 2, the banner logic at line 1002-1019 works correctly:

1. On cross-tool mount: `contextScenarioShocks` set via `useState` initializer from `context.scenarioShocks` (primary path). `useEffect` fires as belt-and-suspenders with same values (no-op).
2. On same-instance prop change: `contextScenarioShocks` set via `useEffect` sync (defensive path).
3. `hasActiveContext` (line 440) = `!!(contextWeights || contextPortfolioValue || contextVolScale || contextScenarioShocks)` -- truthy when shocks present.
4. `contextSource` set from `context.source` -- truthy ("stress-test").
5. `hasActiveContext && contextSource` -- truthy, banner renders.
6. `contextScenarioShocks ? " · Scenario-conditioned drift" : ""` -- truthy, text appears.

The auto-run `useEffect` (line 724-731) also benefits: `hasActiveContext` is now truthy, `contextKey` is computed from `context*` state (no stale `incoming*`), so the MC run triggers automatically with shocks applied.

---

## Implementation Sequence

### Phase 1 (now)
1. Add Diagnostic 1 to `StressTestTool.tsx` useEffect (~10 lines)
2. Add Diagnostic 2 to `StressTestTool.tsx` handleMonteCarloNavigation (~8 lines)
3. Add Diagnostic 3 to `MonteCarloTool.tsx` after initialContext (~8 lines)
4. Run `vitest` to verify no test regressions
5. Manual smoke test: StressTest → "Simulate recovery" → check console for `[StressTest→MC]` / `[MC]` logs
6. Record which scenario (A-E) matches the console output

### Phase 2 (after Phase 1 diagnosis)
1. Apply Change 1 (shock reconstruction fallback) — 5 lines in StressTestTool
2. Apply Change 2 (context sync effect + contextDismissedRef + contextKey refactor) — ~50 lines in MonteCarloTool
3. Update `handleClearContext` to set dismissed ref — 1 line
4. Remove Phase 1 diagnostics (or keep behind `__DEV__` guard)
5. Add 4 new tests
6. Run `vitest` to verify all existing + new tests pass
7. Manual smoke test: StressTest → "Simulate recovery" → verify banner shows "Scenario-conditioned drift"

---

## Open Questions Resolved

| Question | Answer |
|---|---|
| Does `stressTest.data.factorShocks` exist? | **No.** The field does not exist. `stressTest.data.factorContributions` is an `Array<{factor, shock, portfolioBeta, contributionPct}>`. Shocks must be reconstructed via `Object.fromEntries(fc.map(c => [c.factor, c.shock]))`. |
| Should empty context `{}` preserve stale state? | **No.** `setActiveTool(tool)` clears to `{}` intentionally. Empty context = "no context" = clear state. |
| Does `contextDismissedRef` need a reset mechanism? | **Yes.** Use `prevContextRef` to detect new object reference → reset dismissed flag. |
| Should `contextKey` use `incoming*` or `context*`? | **`context*` exclusively.** `incoming*` values are frozen at mount. `contextKey` must track live state for correct auto-run behavior. |
| Is the cross-tool navigation path the actual bug? | **Unknown — that's what Phase 1 diagnostics will determine.** Theory says it works (React remounts, `useState` captures fresh context). But the reported bug may involve `executedScenario` lookup failure (Scenario A), making `lastRunScenarioShocks` null at the source. |
