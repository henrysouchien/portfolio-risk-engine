# Trading P&L Sub-Grades Readability Fix

## Context

The Trading P&L card shows sub-grades as cryptic abbreviations: "CONV C", "TIME N/A", "SIZE A", "AVGD F". A portfolio manager has no way to understand what these dimensions measure or what's driving the overall C grade.

## Current State

**File:** `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` (lines 48-53, 172-185)

Sub-grades are rendered as small pill badges in a flex-wrap row:
```tsx
const subGrades = [
  { label: 'Conv', value: '...' },   // Conviction — quality of entry/exit decisions
  { label: 'Time', value: '...' },   // Timing — entry/exit timing vs price movement
  { label: 'Size', value: '...' },   // Position Sizing — larger winners vs smaller losers
  { label: 'AvgD', value: '...' },   // Averaging Down — quality of adding to positions
]
```

Rendered as: `<span className="... text-[10px] font-semibold uppercase">{label} {value}</span>`

## Problem

1. Abbreviations are unreadable — "CONV", "AVGD" mean nothing to an investor
2. No explanation of what each dimension measures
3. No way to understand why a grade is what it is
4. The pills are all crammed together with no hierarchy

## Proposed Design

Replace the pill badges with a small 2x2 grid of labeled metrics, each with a tooltip explaining the dimension. Keep inside the existing `rounded-xl bg-neutral-50/90 p-3` container alongside the Overall Grade.

### Layout

Keep the existing Overall Grade row (left label + right circle badge). Below it, replace the flex-wrap pill row with:

```
┌──────────────────────┬──────────────────────┐
│ Conviction        C  │ Timing          N/A  │
│ Entry/exit quality   │ Trade timing         │
├──────────────────────┼──────────────────────┤
│ Sizing            A  │ Avg. Down         F  │
│ Position sizing      │ Adding to losers     │
└──────────────────────┴──────────────────────┘
```

Each cell:
- Full label (not abbreviated): "Conviction", "Timing", "Sizing", "Avg. Down"
- Grade badge right-aligned (same color-coded pill as now)
- One-line description below in muted text
- Tooltip with fuller explanation on hover

### Styling (matching existing patterns)

- Grid: `grid grid-cols-2 gap-2`
- Per cell: `rounded-lg border border-neutral-200/40 px-3 py-2` (subtle inner borders for separation)
- Label: `text-xs font-medium text-neutral-700`
- Description: `text-[10px] text-neutral-400`
- Grade pill: same `gradeToneClasses` mapping, same `text-[10px] font-semibold uppercase` styling
- Tooltips: same `TooltipContent className="border-neutral-700 bg-neutral-900 text-white"` as elsewhere

### Sub-grade definitions (for tooltips)

| Label | Description | Tooltip |
|-------|------------|---------|
| Conviction | Entry/exit quality | How well you committed to winners and cut losers |
| Timing | Trade timing | Quality of entry and exit points relative to price moves |
| Sizing | Position sizing | Whether you sized winners larger than losers |
| Avg. Down | Adding to losers | Whether you added to losing positions (lower is worse) |

## Changes

### `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

1. Update `subGrades` array to include `fullLabel` and `description` fields
2. Replace the flex-wrap pill rendering (lines 172-185) with the 2x2 grid layout
3. Add Tooltip wrapping on each cell (Tooltip/TooltipTrigger/TooltipContent already imported)

No other files change. No data changes — same `grades` fields from the API.

## Verification

1. TypeScript check
2. Browser: Performance view → Trading P&L card, confirm sub-grades show full labels + descriptions
3. Hover tooltips work on each sub-grade cell
4. Grade colors match existing scheme (emerald A, blue B, amber C, red D/F)
