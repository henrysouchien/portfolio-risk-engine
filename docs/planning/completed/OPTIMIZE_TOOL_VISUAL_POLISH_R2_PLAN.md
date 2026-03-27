# Optimize Tool — Round 2 Visual Polish Plan

> **Codex review**: R1 FAIL (5). R2 FAIL (2). R3 FAIL (2). R4 FAIL (3). R5 FAIL (2). **R6 PASS.** Total: 6 rounds, 14 findings resolved.

## Context

Round 1 fixed structural UX issues (table truncation, constraint consolidation, loading skeletons). Round 2 addresses visual refinement feedback: font sizes too big, button orphaned, chart amateurish, cards generic, copy weak. The polished Monte Carlo, Backtest, and Stress Test tools are the reference standard.

**No backend changes.** Frontend-only CSS/layout/component changes.

---

## Phase 1 — High Impact

### Step 1.1: Add ScenarioInsightCard at top of results

**File:** `OptimizeTool.tsx`

Add `ScenarioInsightCard size="lg"` immediately after `workflow.optimizationData` check, before the frontier chart. Same pattern as MC (line 641) and BT (line 484).

**Verdict logic** (new `useMemo`):
- Count total violations from `compliance?.risk/factor/proxy`
- Compute Sharpe delta from `proposedMetrics.sharpe_ratio - currentMetrics.sharpe_ratio`
- Count trades from `weightChanges.length`

Decision tree (null-safe, strategy-aware — R1+R4 findings):

First check violations, then derive verdict from the **active strategy** (not just Sharpe):

1. **Violations > 0** (any strategy) → amber, `ShieldAlert`, "Optimization completed with constraint violations", body mentions violation count + trade count + goal label

2. **No violations, strategy-specific success check:**
   - `max_sharpe`: Check Sharpe delta (both non-null). Improved → emerald. Flat/declined → neutral.
   - `min_variance`: Check volatility delta. Decreased → emerald, "Risk reduced from {current}% to {proposed}%". Flat/increased → neutral.
   - `max_return`: Check return delta. Increased → emerald, "Expected return increased from {current}% to {proposed}%". Flat/decreased → neutral.
   - `target_volatility`: Check if proposed volatility is close to target (within 1pp). Hit → emerald, "Volatility landed at {proposed}% vs {target}% target". Missed → neutral.

3. **Metrics unavailable for comparison** (either null) → emerald, `ShieldCheck`, "Optimization complete", body: "The solver proposes {tradeCount} weight changes with no constraint violations."

**emerald** uses `ShieldCheck`, **neutral** uses `BarChart3`, **amber** uses `ShieldAlert`.

Body always includes trade count. `toGoalLabel(strategy)` is reused for the goal reference in copy.

Include `secondaryActionLabel="Ask AI about this"` with `onSecondaryAction={handleAskAI}`.

**Imports:** `ScenarioInsightCard` from `../shared/ScenarioInsightCard`, `ShieldAlert`, `ShieldCheck`, `BarChart3` from lucide-react.

**Pattern:** MC (line 641), BT (line 484), and WhatIf (line 756) all use `ScenarioInsightCard size="lg"`. Follow the same pattern.

### Step 1.2: Move Optimize button into GoalSelector header

**File:** `GoalSelector.tsx`

Move the button from orphaned `<div className="flex justify-end">` into a flex row in CardHeader alongside the title:

```tsx
<CardHeader className="space-y-3">
  <div className="flex flex-wrap items-start justify-between gap-4">
    <div className="space-y-2">
      <CardTitle className="text-2xl text-foreground">Optimize Portfolio</CardTitle>
      <CardDescription ...>Choose an objective, then run the optimizer against your current constraints.</CardDescription>
    </div>
    <Button variant="premium" ... className="h-11 rounded-full px-5">
      {isRunning ? "Optimizing..." : "Optimize"}
    </Button>
  </div>
</CardHeader>
```

Remove the old button `<div className="flex justify-end">` block (lines 150-161).

**Copy change:** "Goal Selector" → "Optimize Portfolio" (matches tool identity like "Monte Carlo", "Stress Test").

**Pattern:** Stress Test (button inline with Select in CardHeader).

### Step 1.3: Fix frontier chart

**File:** `EfficientFrontierTab.tsx`

In compact mode:

1. **Remove inner "Frontier Curve" title** — the `<div className="mb-3 flex items-center justify-between gap-3">` block (lines 244-250). Parent card already says "Efficient Frontier".

2. **Replace default Recharts `<Legend />`** with custom pill legend (MC pattern, lines 690-706):
   ```tsx
   <div className="mb-3 flex flex-wrap gap-2">
     {/* pill for each series with colored dot */}
   </div>
   ```
   Place above the `<ChartContainer>`. Remove `<Legend />` from the chart.

3. **Improve axis label sizing** — set fontSize to 11 on both axis labels (matching getAxisPreset default).

4. **Remove inner Card wrapper in compact mode** — change `<Card className="p-4 border-emerald-200/60">` to `<div>` for compact. The parent already provides card chrome.

**Guard:** All changes gated on `compact` prop except the pill legend which improves both modes.

---

## Phase 2 — Medium Impact

### Step 2.1: Replace Before/After DataTable with impact strip

**File:** `BeforeAfterComparison.tsx`

Replace DataTable with Stress Test horizontal strip pattern (`renderImpactSummary`, line 119-151).

**Preserve conditional metric rendering (R1 finding):** The current component conditionally renders Return (only when `proposedMetrics.return_pct != null`, line 144) and Sharpe (only when `proposedMetrics.sharpe_ratio != null`, line 155). The new strip MUST preserve this logic — build a `visibleMetrics` array dynamically, filtering out metrics where proposed is null. Always show Risk and Concentration; conditionally show Return and Sharpe.

**Preserve delta treatment (R1 finding):** The current `formatDelta()` (line 43) computes sign, color, and flat detection. The new strip must include a delta indicator per metric. Format: proposed value (bold) + "from {current}" (muted) + delta with semantic color (emerald for improvement, red for degradation, muted for flat). Use the existing `improvesWhen` direction logic to determine color.

**Mobile responsive (R1 finding):** The ST strip uses non-wrapping `flex` which works for 4 fixed metrics. With conditional metrics (2-4 visible), use a responsive grid that adapts to metric count. Pure Tailwind, no inline styles:

- 2 metrics: `grid-cols-2` (always 2 columns)
- 3 metrics: `grid-cols-2 sm:grid-cols-3` (2 on mobile, 3 on desktop)
- 4 metrics: `grid-cols-2 sm:grid-cols-4` (2 on mobile, 4 on desktop)

```tsx
const gridCols = visibleMetrics.length <= 2 ? "grid-cols-2" : visibleMetrics.length === 3 ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-2 sm:grid-cols-4"

<div className="overflow-hidden rounded-xl border border-border/60">
  <div className={cn("grid gap-px bg-border/50", gridCols)}>
    {visibleMetrics.map((metric) => (
      <div key={metric.id} className="bg-card px-4 py-2.5">
        <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">{metric.label}</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-base font-semibold tabular-nums">{metric.proposedFormatted}</span>
          <span className="text-xs tabular-nums text-muted-foreground">from {metric.currentFormatted}</span>
        </div>
        <div className={cn("text-xs tabular-nums font-medium", metric.deltaColor)}>{metric.deltaFormatted}</div>
      </div>
    ))}
  </div>
</div>
```

Add section header above: `<div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground mb-3">Portfolio Impact</div>`

Remove Card/CardHeader/CardContent wrapper — bare strip with section header.

**Pre-run empty state (R3+R4 findings):** `OptimizeTool.tsx` renders `BeforeAfterComparison`, `ConstraintStatus`, and `WeightChangesTable` unconditionally (lines 456-463). ALL three result sections should only render when `workflow.optimizationData` exists. Move all three inside the `workflow.optimizationData ? (` conditional block, after the insight card and frontier chart. Before optimization, only the GoalSelector and the empty frontier placeholder are visible (which already communicates "run first"). This eliminates the "Unavailable" constraint rows and empty trades card in the pre-run state.

**Copy:** "Return", "Risk", "Sharpe", "Concentration".

### Step 2.2: Downsize sub-section card titles

**Files + changes:**
- `OptimizeTool.tsx` Efficient Frontier card: `text-xl` → `text-lg font-semibold` + add `text-sm text-muted-foreground` subtitle: "Risk-return tradeoff with current and proposed portfolios."
- `ConstraintStatus.tsx`: `text-xl` → `text-base font-semibold`, title "Constraints" → "Constraint Check", remove CardDescription
- `WeightChangesTable.tsx`: `text-xl` → `text-base font-semibold`, title "Weight Changes" → "Proposed Trades", remove CardDescription

**Pattern:** MC chart titles use `text-lg font-semibold`. ST sub-cards use `text-base font-semibold`. BT section headers use `text-xs uppercase tracking`.

### Step 2.3: Improve copy

- GoalSelector description: → "Choose an objective, then run the optimizer against your current constraints."
- ConstraintStatus all-passing: "All constraints passing" → "All constraints satisfied", body → "No risk, factor, or proxy limits were violated."
- WeightChangesTable empty: → "Run an optimization to see proposed trades."
- Frontier empty state: → "Run an optimization to see how the proposed allocation compares on the risk-return frontier."

---

## Phase 3 — Low Impact

### Step 3.1: Differentiate card styling

- **Insight card:** Uses ScenarioInsightCard (has own gradient treatment — no wrapper needed)
- **Frontier card:** Change to `variant="glassTinted"` (matching BacktestResults line 475)
- **Impact strip:** No card wrapper (bare strip breaks monotony)
- **Constraint + Trades cards:** Remove `variant="glass"` prop entirely (which maps to `glass-premium` in card.tsx) and replace card className with `rounded-2xl border border-border/70 bg-card shadow-none` (flatter, matching ST sub-cards at line 535). Must remove the variant prop — just changing className while keeping `variant="glass"` won't work because the variant adds its own classes.

### Step 3.2: Skeleton refinement

Update `OptimizationResultsSkeleton` to match new layout:
- Insight placeholder: `h-16 rounded-xl`
- Chart placeholder: `h-80 rounded-2xl`
- Impact strip: `h-14 rounded-xl`
- Constraint card: `h-20 rounded-2xl`
- Trades table: `h-40 rounded-2xl`

---

## Files Modified

| File | Steps |
|------|-------|
| `tools/OptimizeTool.tsx` | 1.1, 2.2, 3.1, 3.2 |
| `optimize/GoalSelector.tsx` | 1.2, 2.3 |
| `scenario/EfficientFrontierTab.tsx` | 1.3 |
| `optimize/BeforeAfterComparison.tsx` | 2.1, 2.3 |
| `optimize/ConstraintStatus.tsx` | 2.2, 2.3 |
| `optimize/WeightChangesTable.tsx` | 2.2, 2.3 |

## Verification

1. Run optimization — verify insight card appears with correct verdict (emerald/amber/neutral)
2. Verify "Optimize" button is inline with title in GoalSelector header
3. Verify frontier chart: no inner "Frontier Curve" title, pill legend, readable axis labels, no double card nesting
4. Verify impact strip replaces old DataTable with horizontal layout
5. Verify downsized card titles (`text-lg`/`text-base` not `text-xl`)
6. Verify card differentiation (glassTinted frontier, flat constraint/trades cards, bare impact strip)
7. Navigate to standalone Efficient Frontier tab — verify non-compact mode still works
8. Run `cd frontend && npx vitest run`

**Tests to update (R1 finding):**
- `OptimizeComponents.test.tsx` — update Before/After tests (line 67+) for new strip format labels and delta strings. Update ConstraintStatus tests (line 159+) for "All constraints satisfied" copy.
- Add insight card verdict tests in `OptimizeTool.test.tsx` — test strategy-aware branches: violations (any strategy), max_sharpe improved/flat, min_variance decreased/flat, max_return increased/flat, target_volatility hit/miss, metrics-null fallback
- Add dynamic metric omission test in `BeforeAfterComparison` — verify Return/Sharpe hidden when proposed is null
- Verify `EfficientFrontierTab.test.tsx` compact vs standalone behavior (legend, title) still passes
