# Optimize Tool — Visual Polish Plan

> **Codex review**: R1 FAIL (6). R2 FAIL (1). R3 FAIL (2). R4 FAIL (2 low). **R5 PASS.**

## Context

The Optimize tool was redesigned (commit `88b61eeb`) with a goal-oriented UX: GoalSelector, Efficient Frontier chart, Before/After comparison, Constraints, Weight Changes, and ActionBar. A live browser audit (7-dimension evaluation) found that the tool works well functionally but has several UX/polish issues — the biggest being an uncollapsed 25+ row weight table that buries the action bar 4 screens below the fold.

**No backend changes.** All changes are CSS/layout/component-level in the frontend.

**Audit findings** (7-dimension evaluation, live browser testing):
- UI/UX: B — Goal Selector excellent, but weight table (25+ rows, no truncation) dominates page and buries action bar
- Data Quality: B+ — All 4 Before/After metrics populated with correct directional coloring
- Cross-View: A- — 4 exit ramps (What-If, Backtest, Monte Carlo, Rebalance) + Ask AI
- Action Paths: B- — Exit ramps exist but buried below uncollapsed 25+ row table
- AI Integration: B+ — Full scenario chat with goal label, compliance flags, key metrics
- MCP Coverage: A- — 4 strategy types, agent format, efficient frontier auto-trigger
- State Persistence: B — Strategy selection + cached results persist via React Query cacheKey

---

## Phase 1 — High-Impact UX Fixes

### Step 1.1: Truncate Weight Changes table (show top 10, expand for all)

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/WeightChangesTable.tsx`

**Change:** Make `WeightChangesTable` a controlled component. Expansion state lives in `OptimizeTool.tsx` so the reset trigger can key off a per-run signal.

**WeightChangesTable.tsx changes:**
- Add `const INITIAL_VISIBLE = 10` at module scope
- Add props: `isExpanded: boolean`, `onToggleExpanded: () => void`
- Compute `displayedChanges = isExpanded ? changes : changes.slice(0, INITIAL_VISIBLE)`
- Pass `displayedChanges` to `<DataTable data={...}>`
- After `<DataTable>`, render toggle button when `changes.length > INITIAL_VISIBLE`
- Import `Button` from `../../../../ui/button`

**OptimizeTool.tsx changes (controlled state + reset):**
- Add `const [isWeightTableExpanded, setIsWeightTableExpanded] = useState(false)`
- Reset on new optimization run using the workflow's `runId` (from `usePortfolioOptimization.ts:73`), NOT `optimizationData` identity (cache hits return same object instance from UnifiedCache):

```tsx
const [isWeightTableExpanded, setIsWeightTableExpanded] = useState(false)
const lastRunIdRef = useRef(workflow.optimizationRunId)

useEffect(() => {
  if (workflow.optimizationRunId != null && workflow.optimizationRunId !== lastRunIdRef.current) {
    lastRunIdRef.current = workflow.optimizationRunId
    setIsWeightTableExpanded(false)
  }
}, [workflow.optimizationRunId])
```

If `optimizationRunId` is not currently exposed by `useOptimizationWorkflow`, thread it through from `usePortfolioOptimization` (which already has `_runId` via `useDataSource`).

**R4 finding — runId implementation detail:** The optimize hook currently generates `_runId` with `Date.now()` (`usePortfolioOptimization.ts:90`), not a true monotonic counter. For this reset use case, `Date.now()` is sufficient — same-millisecond reruns are practically impossible with human-initiated clicks. However, if preferred, the hook can be upgraded to use a counter pattern like `useWhatIfAnalysis.ts:9` (`let _runIdCounter = 0; ... ++_runIdCounter`). Either approach works for the table collapse reset.

**Hook threading:** If `_runId` is not already exposed by `useOptimizationWorkflow`, add it to the return value. This touches:
- `usePortfolioOptimization.ts` — expose `runId` in return object
- `useOptimizationWorkflow.ts` — passthrough as `optimizationRunId`

- Pass `isExpanded={isWeightTableExpanded}` and `onToggleExpanded={() => setIsWeightTableExpanded(prev => !prev)}` to `<WeightChangesTable>`

**Pattern:** StressTestTool `showAllPositions` pattern (line 185, 582-607)

### Step 1.2: Sticky action bar — DEMOTED to Phase 3

**Rationale (R1 finding):** After Step 1.1 truncates the table to 10 rows, the action bar is at most ~2 screens below the fold — much less severe. The original `-mx-6 px-6` margin hack also doesn't match the actual parent layout (the tool root `<div className="space-y-6">` has no `px-6` parent). If still desired after truncation, verify the actual parent padding in-browser and use matching negative margins. Move to Phase 3 as optional.

---

## Phase 2 — Medium Polish

### Step 2.1: Remove redundant Direction column

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/WeightChangesTable.tsx`

**Change:** Delete the last column entry (key `"direction"`, lines 58-75) from the `columns` array. Remove unused `ArrowDown`, `ArrowUp`, `Minus` imports. The Change column already has sign + color.

**Dead code cleanup (R1 finding):** Also remove the `direction` field from the `WeightChangeRow` interface (line 12) and remove the `direction` computation in `toWeightChanges()` in `OptimizeTool.tsx` (lines 136-141). The `WeightChangeRow` type and its construction should drop the field entirely.

### Step 2.2: Hide "N requested" badge in compact mode

**File:** `frontend/packages/ui/src/components/portfolio/scenario/EfficientFrontierTab.tsx`

**Change:** Line 246 — gate badge on `!compact`:

```tsx
{meta && !compact ? (
  <Badge variant="secondary" className="bg-emerald-100 text-emerald-800">
    {typeof meta.n_requested === "number" ? meta.n_requested : frontierPoints.length} requested
  </Badge>
) : null}
```

### Step 2.3: Consolidate all-passing constraints

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/ConstraintStatus.tsx`

**Change:** When all 3 sections pass, render a single consolidated row instead of 3 identical "All passing" rows:

```tsx
const allPassing = sections.every(s => s.state?.passes === true)
```

When `allPassing`: single row with green check + "All constraints passing" + subtitle "Risk limits, factor exposure, and proxy exposure are within bounds."

When NOT `allPassing`: existing 3-row collapsible layout.

### Step 2.4: Loading skeleton during optimization

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx`

**Change:** When `workflow.isOptimizing`, replace **all four result sections** (Frontier + BeforeAfterComparison + ConstraintStatus + WeightChangesTable) with skeleton placeholders.

- Import `Skeleton` from `../../../ui/skeleton`
- Wrap all four result sections in a conditional: `workflow.isOptimizing ? <SkeletonBlock /> : <ResultSections />`
- Skeleton block: Card with 4 skeleton groups representing frontier chart (h-80), before/after (h-32), constraints (h-24), and weight changes (h-40)

**R1 finding:** The frontier section is driven by `workflow.optimizationData`. During a re-run, `optimizationData` can become `null` (depending on `keepPreviousData` behavior in `useDataSource`), which causes the frontier to show "Run an optimization..." instead of a loading state. Skeletonizing all four sections together prevents this stale/empty state mismatch.

---

## Phase 3 — Low Cleanup

### Step 3.1: Trim verbose card subtitles

**Files + changes:**
- `BeforeAfterComparison.tsx` line 171: → "Current portfolio vs. proposed allocation."
- `WeightChangesTable.tsx` lines 82-84: → "Sorted by largest reallocation."
- `ConstraintStatus.tsx` lines 87-88: → "Portfolio, factor, and proxy guardrails."

### Step 3.2: Remove Tabs wrapper around frontier chart

**Files:**
- `OptimizeTool.tsx`: Remove `<Tabs value="efficient-frontier" className="w-full">` wrapper and `Tabs` import
- `EfficientFrontierTab.tsx`: When `compact`, render children in `<div className="space-y-6">` instead of `TabContentWrapper`

**R1 coupling warning:** These two edits MUST land together. `EfficientFrontierTab` always returns `TabContentWrapper`/`TabsContent`, which requires a `Tabs` ancestor to render. Removing the `Tabs` wrapper in `OptimizeTool.tsx` without also changing the compact path in `EfficientFrontierTab.tsx` will break compact rendering. Implement the `EfficientFrontierTab` change first, then remove the wrapper.

### Step 3.3: Sticky action bar (optional, browser-verify first)

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx`

**Change:** After Step 1.1 truncation, evaluate in-browser whether the action bar is still too far below fold. If so, wrap `<ActionBar>` in a sticky bottom container. The exact negative margin values must be determined from the actual parent layout — do NOT use the `-mx-6 px-6` pattern without verifying the parent container's padding first.

---

## Deferred

- **Arrow semantics in BeforeAfterComparison** (↗ for -5.3%) — design decision, separate review
- **Currency positions (CUR:USD etc.)** — data-level, not UI

## Files Modified (summary)

| File | Steps |
|------|-------|
| `optimize/WeightChangesTable.tsx` | 1.1, 2.1, 3.1 |
| `tools/OptimizeTool.tsx` | 1.1 (controlled state + reset), 2.1 (dead code), 2.4, 3.2, 3.3 |
| `connectors/.../optimize/hooks/usePortfolioOptimization.ts` | 1.1 (expose runId) |
| `connectors/.../optimize/hooks/useOptimizationWorkflow.ts` | 1.1 (passthrough optimizationRunId) |
| `optimize/ConstraintStatus.tsx` | 2.3, 3.1 |
| `scenario/EfficientFrontierTab.tsx` | 2.2, 3.2 |
| `optimize/BeforeAfterComparison.tsx` | 3.1 |

## Verification

**Browser testing:**
1. Run optimization with "Best risk-adjusted return" — verify:
   - Weight table shows 10 rows + "Show all N" button
   - Direction column gone, 4-column table
   - Constraints show single "All constraints passing" row
   - Frontier chart has no "15 requested" badge
   - Subtitles are concise
2. Click "Show all" — verify full table expands
3. Re-run optimization — verify table collapses back to 10 rows (reset-on-new-data)
4. Re-run optimization with prior results showing — verify skeleton appears for ALL sections (frontier + before/after + constraints + weight changes)
5. Navigate to standalone Efficient Frontier tab (non-compact) — verify badge still shows, tabs still work
6. Run optimization with violations — verify 3-row constraint layout still shows

**New tests to add:**
- `WeightChangesTable`: truncation (>10 rows shows button, <=10 does not), expand/collapse toggle via controlled props
- `OptimizeTool`: table collapses on new runId (reset behavior)
- `ConstraintStatus`: all-passing consolidation vs mixed/violation 3-row layout
- `EfficientFrontierTab`: compact mode hides badge
- `OptimizeTool`: skeleton shown during `isOptimizing` state

**Existing tests:**
- Run `cd frontend && npx vitest run` — verify no regressions in `OptimizeComponents.test.tsx` and other scenario tool tests
