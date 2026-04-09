# Plan: Fix Backtest "Changes from Current" Delta-Mode UX Bug (F5)

## Context

When the portfolio is not loaded (or positions are still fetching), `useScenarioState()` returns empty `initialPositions`, causing `buildWeightRecordFromPositions()` to produce `initialWeightRecord = {}`. The user can switch to delta mode ("Adjust from current holdings"), enter deltas, and attempt to run the backtest. `applyDeltas({}, deltaInputs)` silently drops all tickers (the `if (!(ticker in baseline))` guard skips every entry), resolving to empty weights.

### Corrected severity: UX bug, NOT a crash

The original TODO says "crashes component" but this is inaccurate. Code analysis shows:

1. **`applyDeltas({}, deltas)` returns `{}`** — it does not crash. It iterates entries, skips all of them (none are in the empty baseline), then calls `normalizeWeights({})` which returns `{}`. No exception thrown.
2. **`deltaIssueMessages` at line 616** fires immediately when `Object.keys(initialWeightRecord).length === 0`, producing `["Delta mode needs a current portfolio allocation to modify."]`.
3. **`canRunBacktest` at line 715** evaluates to `false` because `deltaIssueMessages.length > 0`.
4. **`handleRunBacktest` at line 686** has an early return for `deltaIssueMessages.length > 0`.
5. **`BacktestResults` component** (lines 209–786) is fully null-safe: it checks `data ?` at the top level (line 463) and renders a placeholder when data is undefined. No crash path there.

The actual problem is a **UX bug**: the user can enter delta mode (either by clicking the toggle or via cached UI state), see confusing behavior (all deltas silently ignored, warning banner), and be stuck in a dead-end state. This is bad UX but not a runtime error.

### Root cause: cached state bypass + mounted portfolio switch

There are **two distinct paths** that leave `inputMode` stuck as `"deltas"` when the portfolio has no positions:

**Path A — Cached state rehydration (mount-time)**. When a user previously used the backtest tool in delta mode, the UI store caches `inputMode: "deltas"`. If they reopen the tool after the portfolio unloads (e.g., session restart), `useState` initializes with:

```tsx
const [inputMode, setInputMode] = useState<BacktestInputMode>(validUiCache?.inputMode ?? "weights")
```

This restores `inputMode: "deltas"` immediately, bypassing the toggle button entirely. The disabled-toggle guard (Change 3 below) does NOT prevent this path — the user never clicks the toggle; the state is already "deltas" on mount.

**Path B — Mounted portfolio switch (post-mount)**. `ScenariosRouter.tsx:74` keeps `BacktestTool` mounted in the `fallbackByTool` record while the user switches portfolios. React does NOT re-run `useState` initializers on re-render — they fire only once at mount. So when `initialPositions` goes from `[AAPL, MSFT]` to `[]` because the new portfolio has no positions, `inputMode` stays `"deltas"`. The reseed effect (`useEffect` at line ~457) relies on `seedKey` changing, but if the new portfolio has no positions AND no context weights, `seedKey` resolves to `""`. If the *old* `lastSeedKeyRef.current` was already `""` (e.g., the previous portfolio was context-weight seeded), the reseed effect no-ops and never calls `setInputMode("weights")`. Even when `seedKey` *does* change, the reseed effect only fires its `setInputMode("weights")` call inside the `initialWeightRecord.length > 0` branch (line ~491) — when the new portfolio is empty, neither the context-weights nor the portfolio-weights branch executes, so `inputMode` is untouched.

**Cache contamination corollary**: The persistence effect at line ~524 writes the full state object (`rows`, `deltaRows`, `activeWeights`, `inputMode`, etc.) to `toolRunParams["backtest:ui"]` keyed by the current `portfolioId`. After the portfolio switch, `portfolioId` changes, so the persistence effect writes stale delta state (`inputMode: "deltas"`, old `deltaRows`, old `activeWeights`) under the *new* portfolio's cache key. If the user later navigates away and back, Change 1's mount-time clamp catches `inputMode` — but stale `deltaRows` and `activeWeights` would still leak. Change 2's `useEffect` is the proper fix: it resets all four values (`inputMode`, `deltaRows`, `rows`, `activeWeights`). Note that the persistence effect will still fire once with stale state on the transitional render (React effects run in declaration order within a render, but `setState` inside an effect does not take effect until the next render). Change 2's state reset triggers a re-render where the persistence effect fires again with corrected values, overwriting the stale entry.

**Severity**: Medium (UX bug). **Scope**: Small (~25 lines across 1 file + test additions).

---

## Change 1: Clamp cached `inputMode` at rehydration (mount-time guard)

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/BacktestTool.tsx`
**Location**: Line ~393 (the `inputMode` useState initializer)

This handles **Path A** — cached state rehydration at mount time.

**Current code** (line 393):
```tsx
const [inputMode, setInputMode] = useState<BacktestInputMode>(validUiCache?.inputMode ?? "weights")
```

**New code**:
```tsx
const cachedInputMode = validUiCache?.inputMode ?? "weights"
const [inputMode, setInputMode] = useState<BacktestInputMode>(
  cachedInputMode === "deltas" && initialPositions.length === 0 ? "weights" : cachedInputMode
)
```

**Why**: Prevents the tool from opening in delta mode when there is no portfolio to delta from, regardless of whether the user entered delta mode via the toggle or via cached state. `initialPositions` is the stable input (from `useScenarioState`) — we check it directly rather than the derived `initialWeightRecord` memo (which isn't computed yet at state initialization time).

**Edge case — portfolio loads after mount**: If `initialPositions` starts empty (loading) and then populates, the user will be in weights mode. They can manually switch to deltas once positions arrive. This is correct behavior — the tool should not auto-flip to deltas when data arrives asynchronously.

**Limitation**: This only fires at mount. If `initialPositions` changes *after* mount (Path B), `useState` does not re-run. Change 2 covers that case.

---

## Change 2: useEffect to clamp inputMode on post-mount portfolio switch

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/BacktestTool.tsx`
**Location**: After the reseed effect (~line 522, before the persistence effect at line ~524)

This handles **Path B** — the mounted portfolio switch path that the `useState` initializer cannot catch.

**New code** (insert as a new `useEffect`):
```tsx
useEffect(() => {
  if (inputMode === "deltas" && initialPositions.length === 0) {
    setInputMode("weights")
    setDeltaRows([])
    setRows([createWeightRow()])
    setActiveWeights({})
  }
}, [initialPositions, inputMode])
```

**`rows` reset value**: `[createWeightRow()]` rather than `[]`. The component's `useState` initializer (line 388) defaults to `[createWeightRow()]` — a single empty editable row. Resetting to `[]` would render the weight table with no editable row until the user clicks "Add ticker", which is inconsistent with the normal empty-state experience.

**Why**: When `ScenariosRouter` keeps `BacktestTool` mounted and the user switches to a portfolio with no positions, `initialPositions` transitions from populated to empty. The `useState` initializer does not re-run (React only runs it once at mount). The reseed effect (line ~457) does not reliably reset `inputMode` because:
1. When `seedKey` resolves to `""` (empty portfolio, no context weights) and `lastSeedKeyRef.current` is also `""`, the early return `!seedKey || lastSeedKeyRef.current === seedKey` bails out immediately.
2. Even when `seedKey` changes, neither the context-weights branch (line ~462) nor the portfolio-weights branch (line ~488) executes when the new portfolio has no positions — so `setInputMode("weights")` is never called.

This `useEffect` is a direct, minimal guard: whenever the combination of `inputMode === "deltas"` and `initialPositions.length === 0` is true — regardless of how it arose — force back to `"weights"`.

**Targeted state reset, not just `inputMode`**: The persistence effect at line ~524 writes the full state object (`rows`, `deltaRows`, `activeWeights`, `inputMode`, `selectedPreset`, `lastSeedKey`, `lastRunWeights`) keyed by the current `portfolioId`. If this effect only resets `inputMode`, the stale `deltaRows`, `rows`, and `activeWeights` from the old portfolio remain in React state and get written to the new (empty) portfolio's cache key by the persistence effect. Resetting `inputMode`, `deltaRows`, `rows`, and `activeWeights` prevents the delta-mode bug and its visible side effects.

**Fields NOT reset (stale-but-harmless)**: Three additional persisted fields are NOT reset by this effect: `selectedPreset`, `lastSeedKey` (ref), and `lastRunWeights` (ref). These are stale-but-harmless because none of them cause the delta-mode bug:
- `selectedPreset` is cosmetic — it controls which preset pill appears highlighted. A stale value from the old portfolio is visually wrong for one render but is overwritten as soon as the user interacts with presets or the reseed effect runs on the next portfolio load.
- `lastSeedKey` and `lastRunWeights` are used for **change detection**, not display. `lastSeedKey` gates whether the reseed effect re-fires; `lastRunWeights` gates whether the "Run" button shows a re-run indicator. Neither value causes incorrect weights to be sent to the backend or displayed to the user. When the new portfolio loads positions, the reseed effect updates both refs with fresh values.

The reseed effect handles the reverse transition (empty→populated) by seeding fresh values when `seedKey` changes, so these empty values are transient.

**Effect ordering and the persistence effect**: Source order does NOT prevent the persistence effect from running once with the stale render snapshot. React executes all effects from a single render in declaration order, and the `setInputMode("weights")` call inside this effect does not take effect until the *next* render. This means the persistence effect WILL fire once on the transitional render with the old `inputMode === "deltas"` (and old `deltaRows`/`rows`/`activeWeights`). However, this is acceptable because:
1. This effect batches all four state updates (`setInputMode`, `setDeltaRows`, `setRows`, `setActiveWeights`), triggering exactly one re-render.
2. On that re-render, the persistence effect fires again with the corrected state (`inputMode: "weights"`, empty `deltaRows`/`activeWeights`, `rows: [createWeightRow()]`), overwriting the stale cache entry for the new portfolio.
3. The net result is correct: the new portfolio's cache key ends up with clean state. The intermediate stale write is immediately overwritten.

**Placement**: Must appear *before* the persistence effect (line ~524) in source order to make the intent clear, though the critical correctness property is the re-render cycle described above, not declaration order.

---

## Change 3: Disable delta mode toggle when no portfolio baseline

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/BacktestTool.tsx`
**Location**: Line ~1627 (the "Adjust from current holdings" / "Switch to full allocation" toggle button)

**Current code** (line 1627–1634):
```tsx
<Button
  type="button"
  variant="ghost"
  onClick={() => handleInputModeChange(inputMode === "weights" ? "deltas" : "weights")}
  className="rounded-[4px] text-sm text-muted-foreground"
>
  {inputMode === "deltas" ? "Switch to full allocation" : "Adjust from current holdings"}
</Button>
```

**New code**:
```tsx
<Button
  type="button"
  variant="ghost"
  onClick={() => handleInputModeChange(inputMode === "weights" ? "deltas" : "weights")}
  disabled={inputMode === "weights" && Object.keys(initialWeightRecord).length === 0}
  className="rounded-[4px] text-sm text-muted-foreground"
>
  {inputMode === "deltas" ? "Switch to full allocation" : "Adjust from current holdings"}
</Button>
```

**Why**: Belt-and-suspenders. Changes 1 and 2 handle the cached-state and portfolio-switch paths; this handles the manual-click path. The button is only disabled when in weights mode and trying to switch TO deltas — switching back from deltas to weights is always allowed. This matches the pattern WhatIfTool should also adopt (separate issue).

---

## Changes NOT made (from original plan, removed as redundant)

### ~~Guard `applyDeltas` for empty baseline~~ (was original Change 1)

The original plan added `if (Object.keys(baseline).length === 0) return {}` at the top of `applyDeltas`. This is unnecessary — `applyDeltas({}, deltas)` already returns `{}` (the loop body skips every ticker, then `normalizeWeights({})` returns `{}`). The existing behavior is correct and the intent is clear from the `if (!(ticker in baseline))` guard on each entry. Adding a redundant early-return would be cosmetic clutter that doesn't change any behavior.

### ~~Explicit guard in `handleRunBacktest`~~ (was original Change 3)

The original plan added a second guard `if (inputMode === "deltas" && Object.keys(initialWeightRecord).length === 0) return` inside `handleRunBacktest`. This is redundant with the existing `deltaIssueMessages.length > 0` check on the same line (686). The `deltaIssueMessages` computation (line 610–646) already returns `["Delta mode needs a current portfolio allocation to modify."]` when `initialWeightRecord` is empty. Adding a parallel check that duplicates this logic creates maintenance burden (two guards to keep in sync) for zero behavioral benefit. If the invariant matters, enforce it once — and `deltaIssueMessages` is the canonical enforcement point.

### ~~Guard on persistence effect~~ (Codex R2 finding 2)

The persistence effect at line ~524 does not need its own guard. Change 2's `useEffect` now resets all four relevant state values (`inputMode`, `deltaRows`, `rows`, `activeWeights`) reactively whenever `initialPositions` becomes empty and `inputMode` is `"deltas"`. The persistence effect will fire once with stale values on the transitional render (React effects run synchronously in declaration order within a render; `setState` calls within an effect do not take effect until the next render). However, the state reset triggers a re-render, and the persistence effect fires again with the corrected values, overwriting the stale cache entry. The intermediate write is harmless. Adding a separate guard inside the persistence effect would duplicate the invariant for negligible benefit — the stale write is already self-correcting within the same event loop tick.

---

## Test Cases

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/__tests__/BacktestTool.test.tsx`

**Import addition**: Test 4 uses `waitFor`. Add it to the existing `@testing-library/react` import on line 1:
```tsx
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
```

Add the following tests to the existing `describe("BacktestTool", ...)` block.

### Test 1: Cached delta mode rehydrates as weights when portfolio is empty

This is the **primary test** — it covers Path A (cached state bypass at mount).

```tsx
it("rehydrates cached delta mode as weights mode when portfolio has no positions", () => {
  mockUseScenarioState.mockReturnValue({ initialPositions: [] } as never)
  toolRunParams = {
    "backtest:ui": {
      portfolioId: "pf-1",
      rows: [],
      deltaRows: [{ id: "d1", ticker: "AAPL", delta: "+5%" }],
      activeWeights: {},
      benchmark: "SPY",
      period: "3Y",
      inputMode: "deltas",
      lastSeedKey: "",
      lastRunWeights: {},
    },
  }
  mockUseBacktest.mockReturnValue(createBacktestState({ data: null, hasData: false }) as never)

  render(<BacktestTool context={{}} onNavigate={vi.fn()} />)

  // Should NOT show the delta warning — the tool should have fallen back to weights mode
  expect(screen.queryByText(/Delta mode needs a current portfolio allocation to modify/i)).not.toBeInTheDocument()

  // The toggle button should say "Adjust from current holdings" (weights mode label)
  const toggleButton = screen.getByRole("button", { name: /Adjust from current holdings/i })
  expect(toggleButton).toBeInTheDocument()
  // And it should be disabled since there are no positions to delta from
  expect(toggleButton).toBeDisabled()
})
```

### Test 2: Delta mode toggle disabled when portfolio has no positions

```tsx
it("disables the delta mode toggle when initialPositions is empty", () => {
  mockUseScenarioState.mockReturnValue({ initialPositions: [] } as never)
  toolRunParams = {}
  mockUseBacktest.mockReturnValue(createBacktestState({ data: null, hasData: false }) as never)

  render(<BacktestTool context={{}} onNavigate={vi.fn()} />)

  const toggleButton = screen.getByRole("button", { name: /Adjust from current holdings/i })
  expect(toggleButton).toBeDisabled()
})
```

### Test 3: Cached delta mode rehydrates correctly when portfolio IS loaded

Ensures the fix doesn't break the happy path — delta mode should restore normally when positions exist.

```tsx
it("preserves cached delta mode when portfolio has positions", () => {
  mockUseScenarioState.mockReturnValue({
    initialPositions: [
      { ticker: "AAPL", weight: 60 },
      { ticker: "MSFT", weight: 40 },
    ],
  } as never)
  toolRunParams = {
    "backtest:ui": {
      portfolioId: "pf-1",
      rows: [],
      deltaRows: [{ id: "d1", ticker: "AAPL", delta: "+5%" }],
      activeWeights: { AAPL: 0.65, MSFT: 0.35 },
      benchmark: "SPY",
      period: "3Y",
      inputMode: "deltas",
      lastSeedKey: "",
      lastRunWeights: {},
    },
  }
  mockUseBacktest.mockReturnValue(createBacktestState({ data: null, hasData: false }) as never)

  render(<BacktestTool context={{}} onNavigate={vi.fn()} />)

  // Should be in delta mode — the "Switch to full allocation" label indicates delta mode is active
  expect(screen.getByRole("button", { name: /Switch to full allocation/i })).toBeInTheDocument()
})
```

### Test 4: Mounted portfolio switch resets delta mode and prevents stale cache contamination

This covers **Path B** — the mounted-router path where `BacktestTool` stays mounted while `initialPositions` transitions from populated to empty (portfolio switch without unmount). The `useState` initializer does not re-run; only the `useEffect` from Change 2 can catch this. It also verifies that the new portfolio's persisted cache does not contain stale delta state from the old portfolio.

**Import note**: This test uses `waitFor` from `@testing-library/react`. The existing test file imports `cleanup, fireEvent, render, screen` from that package (line 1). Add `waitFor` to that import.

```tsx
it("resets to weights mode when initialPositions transitions from populated to empty without unmount", async () => {
  // Phase 1: mount with a populated portfolio in delta mode
  mockUseScenarioState.mockReturnValue({
    initialPositions: [
      { ticker: "AAPL", weight: 60 },
      { ticker: "MSFT", weight: 40 },
    ],
  } as never)
  toolRunParams = {
    "backtest:ui": {
      portfolioId: "pf-1",
      rows: [],
      deltaRows: [{ id: "d1", ticker: "AAPL", delta: "+5%" }],
      activeWeights: { AAPL: 0.65, MSFT: 0.35 },
      benchmark: "SPY",
      period: "3Y",
      inputMode: "deltas",
      lastSeedKey: "portfolio:pf-1",
      lastRunWeights: {},
    },
  }
  mockUseBacktest.mockReturnValue(createBacktestState({ data: null, hasData: false }) as never)

  const { rerender } = render(<BacktestTool context={{}} onNavigate={vi.fn()} />)

  // Confirm we are in delta mode
  expect(screen.getByRole("button", { name: /Switch to full allocation/i })).toBeInTheDocument()

  // Phase 2: simulate portfolio switch — positions become empty, portfolioId changes
  mockUseScenarioState.mockReturnValue({ initialPositions: [] } as never)
  mockUseBacktest.mockReturnValue(createBacktestState({
    currentPortfolio: { id: "pf-2" },
    data: null,
    hasData: false,
  }) as never)
  // Clear the UI cache so validUiCache becomes undefined (portfolioId mismatch)
  toolRunParams = {}

  rerender(<BacktestTool context={{}} onNavigate={vi.fn()} />)

  // Should have reset to weights mode — the useEffect catches the post-mount transition
  expect(screen.queryByText(/Delta mode needs a current portfolio allocation to modify/i)).not.toBeInTheDocument()
  const toggleButton = screen.getByRole("button", { name: /Adjust from current holdings/i })
  expect(toggleButton).toBeInTheDocument()
  expect(toggleButton).toBeDisabled()

  // Wait for effects to settle (Change 2 triggers re-render → persistence effect re-fires)
  await waitFor(() => {
    // Verify persistence: the last write for pf-2 must NOT contain stale delta state.
    // mockSetToolRunParams is wired into useUIStore via the beforeEach setup (line 222-228),
    // which passes it as `setToolRunParams` in the selector return value.
    const lastCall = mockSetToolRunParams.mock.calls
      .filter(([key]: [string]) => key === "backtest:ui")
      .at(-1)
    if (lastCall) {
      const persisted = lastCall[1]
      expect(persisted.portfolioId).toBe("pf-2")
      expect(persisted.inputMode).toBe("weights")
      expect(persisted.deltaRows).toEqual([])
      expect(persisted.activeWeights).toEqual({})
      // rows resets to [createWeightRow()] — one empty row, not []
      expect(persisted.rows).toHaveLength(1)
      expect(persisted.rows[0]).toMatchObject({ ticker: "", weight: "" })
    }
  })
})
```

**Why this test matters**: Tests 1-3 all verify mount-time behavior (Change 1). This test specifically exercises the post-mount code path (Change 2) that only the `useEffect` can fix. Without the `useEffect`, this test would fail — `inputMode` would remain `"deltas"` because `useState` initializers don't re-run on rerender, and the reseed effect would no-op (empty `seedKey`).

**Persistence assertion**: The `waitFor` block verifies that after effects settle, the persisted state for `pf-2` contains clean values (`inputMode: "weights"`, empty `deltaRows`/`activeWeights`, single empty weight row), not stale data from `pf-1`. This directly addresses the cache contamination concern: even though the persistence effect fires once with stale state on the transitional render, the re-render from Change 2's state reset must overwrite it with corrected values.

**Mock wiring**: The test uses `mockSetToolRunParams` which is already wired into the component via the `beforeEach` setup. The existing `mockUseUIStore` implementation (line 222-228 of the test file) passes `mockSetToolRunParams` as `setToolRunParams` through the Zustand selector pattern: `mockUseUIStore.mockImplementation((selector) => selector({ setToolRunParams: mockSetToolRunParams, toolRunParams }))`. No additional spy setup is needed.

---

## Risk Assessment

- **Regression risk**: Very low. Change 1 only affects state initialization when cached inputMode is "deltas" AND portfolio is empty — the existing behavior for all other cases is unchanged. Change 2's `useEffect` is a no-op whenever `inputMode` is already `"weights"` or `initialPositions` is non-empty. Change 3 only disables a button under a specific condition.
- **Async position loading**: If `initialPositions` is empty at mount but loads later, the tool starts in weights mode. The user can manually switch to deltas once positions arrive. This is better UX than starting in a broken delta mode and then somehow auto-fixing. Change 2 does NOT interfere with this — once positions arrive, `initialPositions.length > 0` and the effect is a no-op, so the user can freely switch to delta mode.
- **Cache contamination**: Change 2 resets four state values (`inputMode`, `deltaRows`, `rows`, `activeWeights`) when the baseline becomes empty. Three additional persisted fields (`selectedPreset`, `lastSeedKey`, `lastRunWeights`) are NOT reset — they are stale-but-harmless (cosmetic preset highlight and change-detection refs that don't affect display or backend calls; see the "Fields NOT reset" note in Change 2). The persistence effect will fire once with stale values on the transitional render, but the state reset triggers a re-render where the persistence effect fires again with clean values for the four reset fields, overwriting the stale cache entry. The intermediate write is harmless — it is immediately superseded. No separate guard needed on the persistence effect itself.
- **Cache invalidation**: The existing `validUiCache` check (`uiCache?.portfolioId === portfolioId`) already handles portfolio switching at mount time. Change 1 adds a complementary check for the "same portfolio, no positions yet" case. Change 2 handles the case where `validUiCache` becomes `undefined` after a portfolio switch (portfolioId mismatch) but `inputMode` state is already latched.
- **Effect ordering**: Both Change 2's effect and the persistence effect run on the same render cycle. Change 2's `setInputMode`/`setDeltaRows`/`setRows`/`setActiveWeights` calls are batched by React and do NOT take effect until the next render. The persistence effect therefore fires once with stale state on the transitional render, then again with corrected state on the re-render. The final persisted value is correct (though `selectedPreset`, `lastSeedKey`, and `lastRunWeights` remain stale-but-harmless — see Change 2 notes). There is no race condition — React processes effects synchronously within each render cycle, and the state updates from Change 2 trigger exactly one additional render that overwrites any stale cache.
- **Performance**: Negligible. `initialPositions.length` is a constant-time property access. The `useEffect` is a no-op on the fast path (weights mode or non-empty positions).

---

## TODO.md update

Change the F5 row description from "crashes component" to "enters broken delta mode":

```
| Backtest "Changes from current" — broken delta mode on empty portfolio (F5) | Medium | **INVESTIGATED** — cached `inputMode: "deltas"` rehydrates even when portfolio has no positions; mounted portfolio switch leaves stale delta state. Plan: `BACKTEST_DELTA_CRASH_FIX_PLAN.md` | E |
```
