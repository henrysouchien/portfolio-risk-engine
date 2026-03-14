# Frontend Visual Audit — P1 Fixes (7 Issues)

**Date:** 2026-03-05
**Status:** COMPLETE — Implemented (`7a7d326c`), Chrome-verified all 7 fixes

## Context

The `completed/FRONTEND_VISUAL_AUDIT.md` cataloged 32 visual issues across all 7 views. This plan covers the 7 P1 (broken/clipped) issues — things that are visibly broken or unreadable in the current UI.

---

## V1. StockLookup: Search dropdown clipped

**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

**Problem:** Search dropdown (line 476, `absolute z-20`) is inside `CardHeader` → `SectionHeader` actions slot. It extends downward past `CardHeader` into the zone occupied by `CardContent` (line 517, `overflow-hidden`). The dropdown is NOT a child of `CardContent`, but the parent `Card` (line 439, `h-[800px]`) or `CardHeader` may clip it.

**Fix:** ShadCN `Card` base component has `overflow-hidden` at `card.tsx:12`. The dropdown is absolutely positioned from inside `CardHeader` but extends past the Card boundary, so it gets clipped by the Card's own `overflow-hidden`.

Override on the StockLookup Card instance (line 439): add `overflow-visible` to the Card's className. Keep `overflow-hidden` on `CardContent` (line 517, needed for tab scrolling). The dropdown at `z-20` will layer correctly over content below.

---

## V2. Overview: Metric cards cramped in compact mode

**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

**Problem:** Compact mode grid at line 1022: `grid-cols-2 md:grid-cols-3 xl:grid-cols-6`. Six cards in a row at xl width makes ALL CAPS labels wrap to 2-3 lines, unreadable.

**Fix:** Line 1022 — change `xl:grid-cols-6` → `xl:grid-cols-4`. Each card gets ~25% width instead of ~16%.

---

## V3. StockLookup: Broken dynamic Tailwind classes on risk card

**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

**Problem:** Line 709 uses chained `.replace()` on `getRiskColor()` output to build gradient classes. The chain produces invalid classes (`border-` with no color, conflicting `bg-` classes).

`getRiskColor("Low")` returns `"bg-emerald-100 text-emerald-700 border-emerald-200"`. After `.replace()` chain: `"bg-gradient-to-br from-emerald-50 to-white border- bg-emerald-700 border-emerald-200"` — broken.

**Fix:** Replace line 709's `.replace()` chain with a direct lookup map:
```tsx
const riskCardStyles: Record<string, string> = {
  Low: "bg-gradient-to-br from-emerald-50 to-white border border-emerald-200",
  Medium: "bg-gradient-to-br from-amber-50 to-white border border-amber-200",
  High: "bg-gradient-to-br from-orange-50 to-white border border-orange-200",
  Extreme: "bg-gradient-to-br from-red-50 to-white border border-red-200",
};
```
Line 709: `<Card className={\`p-4 ${riskCardStyles[selectedStock.riskRating] ?? "bg-gradient-to-br from-neutral-50 to-white border border-neutral-200"}\`}>`

---

## V4. StrategyBuilder: ScrollArea height chain broken

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`

**Problem:** Card `h-[700px]` → CardContent `flex-1` → Tabs `h-full flex flex-col` → TabsContent `flex-1 overflow-hidden` → ScrollArea `h-full`. The `TabsContent` elements lack `min-h-0`, so flex doesn't constrain content height, breaking scroll.

**Fix:** Add `min-h-0` to all 4 TabsContent elements:
- Line 494: `className="flex-1 overflow-hidden"` → `"flex-1 overflow-hidden min-h-0"`
- Line 686: same
- Line 792: same
- Line 846: same

---

## V5. StrategyBuilder: NaN values in Marketplace + Active tabs

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`

**Problem:** Safe wrappers exist (lines 89-93: `formatOptionalPercent`, `formatOptionalNumber`) but 9 call sites use raw `formatPercent`/`formatNumber`, rendering "NaN" when values are NaN/undefined.

**Fix:** Use inline ternary guards instead of `formatOptionalPercent`/`formatOptionalNumber`, since those wrappers don't support the `sign: true` option needed for YTD returns. Pattern: `value != null && Number.isFinite(value) ? formatPercent(value, opts) : "--"`

| Line | Current | Replacement |
|------|---------|-------------|
| 704 | `formatPercent(primaryStrategy.performance.ytd,{ decimals: 1,sign: true })` | `Number.isFinite(primaryStrategy.performance?.ytd) ? formatPercent(primaryStrategy.performance.ytd,{ decimals: 1,sign: true }) : "--"` |
| 709 | `formatNumber(primaryStrategy.sharpeRatio,{ decimals: 2 })` | `formatOptionalNumber(primaryStrategy.sharpeRatio, 2)` |
| 713 | `formatNumber(primaryStrategy.riskLevel,{ decimals: 1 })` | Guard the whole expression: `Number.isFinite(primaryStrategy.riskLevel) ? \`${formatNumber(primaryStrategy.riskLevel,{ decimals: 1 })}/10\` : "--"` (move `/10` inside the guard to avoid `"--/10"`) |
| 746 | `formatPercent(strategy.performance.ytd,{ decimals: 1,sign: true })` | `Number.isFinite(strategy.performance?.ytd) ? formatPercent(strategy.performance.ytd,{ decimals: 1,sign: true }) : "--"` |
| 752 | `formatNumber(strategy.sharpeRatio,{ decimals: 2 })` | `formatOptionalNumber(strategy.sharpeRatio, 2)` |
| 814 | `formatPercent(strategy.performance.ytd,{ decimals: 1,sign: true })` | Same pattern as 746 |
| 819 | `formatNumber(strategy.sharpeRatio,{ decimals: 2 })` | `formatOptionalNumber(strategy.sharpeRatio, 2)` |
| 823 | `formatPercent(strategy.volatility,{ decimals: 1 })` | `formatOptionalPercent(strategy.volatility, 1)` |
| 827 | `formatPercent(strategy.maxDrawdown,{ decimals: 1 })` | `formatOptionalPercent(strategy.maxDrawdown, 1)` |

---

## V6. ScenarioAnalysis: Fixed `h-[700px]` clips content

**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`

**Problem:** Main card at line 1255 is `h-[700px]`. After CardHeader (~120-150px) and TabsList (~48px), only ~510px remains for content. Historical tab's `ScrollArea h-[680px]` (line 1711) exceeds this.

**Fix:**
1. Line 1255: `h-[700px]` → `h-[calc(100vh-12rem)]` — card fills available viewport height (no min/max conflict). The `12rem` accounts for navbar + page padding.
2. Line 1711: Handled by V7 — the inner `h-[680px]` ScrollArea is removed entirely when Historical tab gets restructured with a top-level `<ScrollArea className="h-full">`.

---

## V7. ScenarioAnalysis: Historical tab missing top-level ScrollArea

**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`

**Problem:** 4 of 5 tabs wrap content in `<ScrollArea className="h-full">` (Portfolio Builder line 1357, Optimization line 1556, Stress Tests line 1798, Monte Carlo line 2005). Historical tab (lines 1686-1792) does NOT — uses bare `<div>` with a nested `<ScrollArea h-[680px]>` for just the scenario cards.

**Fix:** Restructure Historical tab to match the other 4 tabs:
- Wrap all content in `<ScrollArea className="h-full">`
- Remove the inner `h-[680px]` ScrollArea — the top-level one handles scrolling
- Add `min-h-0` to ALL TabsContent elements for flex constraint consistency

---

## Files Modified

| File | Changes |
|------|---------|
| `StockLookup.tsx` | V1: overflow fix, V3: risk card class lookup map |
| `PortfolioOverview.tsx` | V2: compact grid 6→4 cols |
| `StrategyBuilder.tsx` | V4: `min-h-0` on 4 TabsContent, V5: 9 unsafe format calls |
| `ScenarioAnalysis.tsx` | V6: flexible card height, V7: Historical tab ScrollArea + `min-h-0` |

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. Chrome: Stock Research → type ticker → dropdown visible, not clipped
3. Chrome: Stock Research → select stock → Risk Assessment card shows proper gradient
4. Chrome: Overview (compact mode) → metric cards readable, no label wrapping
5. Chrome: Strategy Builder → Marketplace → shows "--" not "NaN" for missing metrics
6. Chrome: Strategy Builder → all tabs scroll properly
7. Chrome: Scenario Analysis → Historical tab scrolls all content
8. Chrome: Scenario Analysis → card adapts to viewport height
