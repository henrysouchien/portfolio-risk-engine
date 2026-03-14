# Frontend Visual Audit — P3 Visual Polish Fixes (V17-V28)

## Context

P1 (7 broken/clipped) and P2 (9 layout/spacing) are done. P3 has 12 items — 7 are quick CSS/component fixes batched here. V18 (debug badges) kept as-is for dev use. V19 (tooltip overlap), V23 (price chart), V25 (performance charts), V26 (Monte Carlo visualization) are deferred as separate backlog items requiring chart library integration.

## Items

### V17. Risk score bars always red → color by risk level
**File:** `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`
**Line 210:** `colorScheme="red"` hardcoded on `GradientProgress`.
**Fix:** Derive from `risk.level`:
```tsx
colorScheme={risk.level === 'Low' ? 'emerald' : risk.level === 'Medium' ? 'amber' : 'red'}
```
Do NOT use `autoColor` — its thresholds are inverted for risk semantics.

---

### V18. Debug badges — SKIP (keeping for dev use)

---

### V20. Top Contributors/Detractors too long → default top 5
**File:** `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`
**Lines 1071, 1105:** `sortedContributorRows.map(...)` and `sortedDetractorRows.map(...)` render all rows.
**Fix:** Add `.slice(0, showAll ? undefined : 5)` with separate `useState` toggles for each table (`showAllContributors`, `showAllDetractors`) and a "Show all N" / "Show top 5" button below each table.

---

### V21. AI Recommendations uneven card heights → flex stretch
**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`
**Line ~1470:** Card className is `p-4 hover-lift-subtle border-neutral-200/40`.
**Fix:** Add `flex flex-col h-full` to the Card. Add `flex-1` to the description `<p>` so the body stretches and action items align at the bottom.

---

### V22. Portfolio Fit missing column headers → add header row
**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`
**Line ~1179:** `portfolioFitAnalysis.metrics.map(...)` renders 4-col grid rows without headers.
**Fix:** Add a header row before the `.map()`:
```tsx
<div className="grid grid-cols-4 gap-2 text-xs text-neutral-500 font-medium border-b border-neutral-200 pb-1 mb-1">
  <span>Metric</span><span>Current</span><span>With Position</span><span>Impact</span>
</div>
```

---

### V24. Duplicate "Run Backtest" buttons → remove header button
**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`
**Line 446–466:** "Run Backtest" button in `CardHeader` `SectionHeader` actions prop.
**Fix:** Remove the Run Backtest button from the header actions (lines 446–466). Keep the "Backtest Strategy" button in the Builder tab (line 664–675) and the "Run a backtest" CTA in the Performance empty state (line 1073–1083). The header already has the AI Enhanced toggle and period selector.

---

### V27. Inconsistent empty states → standardize pattern
**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`
Standardize to match Tab 2 (AI Optimization) pattern: card + icon + heading + description.

> **Codex note:** `Clock` and `Activity` are NOT currently imported. Add them to the existing lucide-react import (line 12). `BarChart3` is already imported.

**Tab 3 — Historical (line ~1715):** Replace amber banner with empty-state card: Clock icon + "Historical Scenarios" heading + "Historical stress testing is not yet available. This feature is coming soon."

**Tab 4 — Stress Tests (line ~1807):** Replace bare `<div>` with empty-state card: Activity icon + "No Stress Scenarios" heading + "No stress scenarios are available yet. Configure factors above to get started."

**Tab 5 — Monte Carlo (line ~2190):** Enhance existing dashed card: Add BarChart3 icon + "Monte Carlo Simulation" heading above the existing description text.

---

### V28. Optimization metrics grid overflow → responsive breakpoints
**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`
**Line 1614:** `grid grid-cols-2 lg:grid-cols-5`
**Fix:** Change to `grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5` and add `min-w-0` to each metric cell div to prevent text overflow.

---

## Files Modified

| File | Items | Changes |
|------|-------|---------|
| `RiskAnalysis.tsx` | V17 | Color-code progress bars by risk level |
| `PerformanceView.tsx` | V20 | Slice to top 5 + show-all toggle |
| `PortfolioOverview.tsx` | V21 | Flex stretch on recommendation cards |
| `StockLookup.tsx` | V22 | Add column headers to Portfolio Fit |
| `StrategyBuilder.tsx` | V24 | Remove header Run Backtest button |
| `ScenarioAnalysis.tsx` | V27, V28 | Standardize empty states, responsive grid |

## Verification

1. `cd frontend && pnpm typecheck`
2. Chrome: Overview → Risk Analysis section — bars green/amber/red matching risk level
3. Chrome: Performance → Contributors/Detractors — shows top 5 with "Show all" button
4. Chrome: Overview → AI Recommendations — cards same height in each row
5. Chrome: Stock Research → Portfolio Fit tab — column headers visible
6. Chrome: Strategy Builder — single backtest button in Builder tab, not in header
7. Chrome: Scenario Analysis → Historical/Stress/Monte Carlo — consistent empty state cards
8. Chrome: Scenario Analysis → AI Optimization → run optimization — metrics grid doesn't overflow
