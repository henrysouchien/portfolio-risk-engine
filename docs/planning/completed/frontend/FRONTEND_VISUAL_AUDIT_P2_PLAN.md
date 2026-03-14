# Frontend Visual Audit — P2 Layout & Spacing Fixes (V8-V16)

## Context

The `completed/FRONTEND_VISUAL_AUDIT.md` cataloged 32 visual issues. P1 (7 broken/clipped items) has a plan doc but is not yet implemented. This plan covers P2: 9 layout/spacing issues. All are CSS/Tailwind changes — no data flow changes. V10 is already resolved by a prior refactor, leaving 8 items.

## Items

### V8. Overview: Metric card labels — remove ALL CAPS
**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`
**Line 1119:** Remove `tracking-wide uppercase` from label className.
```
OLD: font-medium text-neutral-600 tracking-wide uppercase flex items-center space-x-2
NEW: font-medium text-neutral-600 flex items-center space-x-2
```
The "Updated" footer (line 1145) only shows on hover — acceptable, no change needed.

---

### V9. Overview: Move Market Intelligence below metrics
**File:** Same as V8
**Change:** Reorder three sibling sections from:
1. Market Intelligence (lines 918–982)
2. Smart Alerts (lines 984–1015)
3. Key Metrics Grid (lines 1017+)

To:
1. Smart Alerts (urgent, keep above fold)
2. Key Metrics Grid (portfolio metrics as hero)
3. Market Intelligence (supplementary, below fold)

Pure block move of the Market Intelligence `{externalMarketEvents.length > 0 && (...)}` block.

---

### V10. Factor Analysis: Left panel empty space — SKIP
Layout has been refactored to a tabbed interface since the audit. No 60/40 column split exists. Mark as resolved.

---

### V11. Scenario Analysis: N/A cards → placeholder
**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`
**Lines 1524–1543:** Wrap the 4 metric cards in `{analysisResults && showResults ? (...cards...) : (...placeholder...)}`. Placeholder shows an icon + "Run an analysis to see impact metrics" message.
> **Codex note:** Must check both `analysisResults` AND `showResults` — `analysisResults` can remain stale while `showResults` is false during a rerun (line 1128).

---

### V12. Stock Research: Fixed heights → min-heights
**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`
- **Line 439:** `h-[800px]` → `min-h-[800px]`
- **Line 610:** `h-[480px]` → `min-h-[480px]`

---

### V13. Stock Research: Dropdown overflow
**File:** Same as V12
**Line 476:** Change `min-w-[22rem]` to `min-w-0 w-full max-w-[22rem]` on the dropdown's className so it shrinks on narrow viewports instead of forcing overflow.
> **Codex note:** `max-w-full` alone doesn't fix overflow because `min-w-[22rem]` still forces the element wider than its container on small screens.

---

### V14. Strategy Builder: Responsive breakpoints
**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`
- **Line ~700:** Featured Strategy metrics: `grid grid-cols-3` → `grid grid-cols-1 sm:grid-cols-3`
- **Line ~811:** Active Strategy metrics: `grid grid-cols-4` → `grid grid-cols-2 md:grid-cols-4`

---

### V15. Strategy Builder: Empty Active Strategies state
**File:** Same as V14
**Lines ~793–840:** Wrap `activeStrategies.map(...)` in `{activeStrategies.length === 0 ? <EmptyState /> : <existing map>}`. Empty state shows icon + "No Active Strategies" heading + descriptive text.

---

### V16. Scenario Analysis: 5-tab bar responsive
**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`
**Line 1345:** Change `grid w-full grid-cols-5` → `flex w-full justify-start overflow-x-auto`. Add `flex-shrink-0 flex-1` to each TabsTrigger. Tabs use `text-xs` to fit better.
> **Codex note:** `TabsList` base style (`tabs.tsx:15`) includes `justify-center`. Must override to `justify-start` for `overflow-x-auto` to scroll correctly on narrow viewports.

---

## Files Modified

| File | Items | Changes |
|------|-------|---------|
| `PortfolioOverview.tsx` | V8, V9 | Remove uppercase, reorder sections |
| `ScenarioAnalysis.tsx` | V11, V16 | N/A placeholder, flex tab bar |
| `StockLookup.tsx` | V12, V13 | min-h heights, dropdown max-w |
| `StrategyBuilder.tsx` | V14, V15 | Responsive grids, empty state |

## Verification

1. `cd frontend && pnpm typecheck`
2. Chrome: Overview — metric labels sentence-case, portfolio metrics above fold
3. Chrome: Scenario Analysis → Portfolio Builder — placeholder instead of N/A cards
4. Chrome: Scenario Analysis — tab bar doesn't truncate on narrow viewport
5. Chrome: Stock Research — card grows with content, dropdown constrained
6. Chrome: Strategy Builder → Active — shows empty state message
