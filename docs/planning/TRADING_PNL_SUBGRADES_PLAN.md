# Trading P&L Sub-Grades Readability Fix

## Context

The Trading P&L card shows sub-grades as cryptic abbreviations: "CONV C", "TIME N/A", "SIZE A", "AVGD F". A portfolio manager has no way to understand what these dimensions measure or what's driving the overall C grade.

## Current State

**File:** `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` (lines 48-53, 172-185)

Sub-grades are rendered as small pill badges in a flex-wrap row:
```tsx
const subGrades = [
  { label: 'Conv', value: '...' },
  { label: 'Time', value: '...' },
  { label: 'Size', value: '...' },
  { label: 'AvgD', value: '...' },
]
```

Rendered as: `<span className="... text-[10px] font-semibold uppercase">{label} {value}</span>`

## Problem

1. Abbreviations are unreadable — "CONV", "AVGD" mean nothing to an investor
2. No explanation of what each dimension measures
3. No way to understand why a grade is what it is

## Proposed Design

Replace the flex-wrap pill row (lines 172-185) with a 2x2 grid of labeled metrics inside the existing `rounded-xl bg-neutral-50/90 p-3` container, below the Overall Grade row.

### Layout

```
┌──────────────────────┬──────────────────────┐
│ Conviction        C  │ Timing          N/A  │
│ Bet sizing vs outcome│ Exit timing          │
├──────────────────────┼──────────────────────┤
│ Sizing            A  │ Averaging Down    F  │
│ Size consistency     │ Adding to losers     │
└──────────────────────┴──────────────────────┘
```

Each cell:
- Full label (not abbreviated): "Conviction", "Timing", "Sizing", "Averaging Down"
- Grade badge right-aligned (same color-coded pill as now)
- One-line description below in muted text
- Tooltip with fuller explanation on hover

### Styling (matching existing patterns)

- Grid: `grid grid-cols-2 gap-2`
- Per cell: `rounded-lg border border-neutral-200/40 px-3 py-2`
- Label: `text-xs font-medium text-neutral-700`
- Description: `text-[10px] text-neutral-400`
- Grade pill: same `gradeToneClasses` mapping, same sizing
- Tooltips: `TooltipContent className="border-neutral-700 bg-neutral-900 text-white"` (already imported)

### Sub-grade definitions (from `trading_analysis/interpretation_guide.md`)

| Label | Description (in cell) | Tooltip (on hover) |
|-------|----------------------|-------------------|
| Conviction | Bet sizing vs outcome | Do your bigger bets outperform your smaller ones? |
| Timing | Exit timing | How close your exits are to optimal sell points |
| Sizing | Size consistency | How consistent your position sizes are (CV%) |
| Averaging Down | Adding to losers | Whether buying more of losing positions works for you |

### Edge case — Averaging Down with no data

The backend defaults `averaging_down_success_rate` to 0 when there are no averaging-down events, producing an F grade even when there's no data. However, the frontend only receives grade strings — there's no count field to distinguish "F because bad decisions" from "F because no data."

**Decision:** Show the grade as-is without special-casing. The tooltip explains what the dimension measures; the user can interpret an F grade in context. Adding a count field to the API would be a separate backend change out of scope here.

## Changes

### `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

1. Update `subGrades` array to include `fullLabel`, `description`, and `tooltip` fields
2. Replace the flex-wrap pill rendering (lines 172-185) with the 2x2 grid layout
3. Wrap each cell in Tooltip (already imported)

No other files change. No data changes — same `grades` fields from the API.

## Verification

1. TypeScript check
2. Browser: Performance view → Trading P&L card, confirm sub-grades show full labels + descriptions
3. Hover tooltips work on each sub-grade cell
4. Grade colors match existing scheme (emerald A, blue B, amber C, red D/F)
5. N/A grades render correctly (neutral styling)
