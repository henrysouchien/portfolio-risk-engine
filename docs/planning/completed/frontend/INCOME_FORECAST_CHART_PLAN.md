# Income Forecast Chart Replacement Plan

**Status**: READY TO EXECUTE (v2 — Codex review fixes applied)
**Date**: 2026-03-16
**Scope**: Replace SparklineChart in Income Projection card with Recharts BarChart

---

## Problem

The "Monthly Forecast" chart in the Income Projection dashboard card uses the same hand-rolled SVG `SparklineChart` — a 36px tall wiggly line with no axes, no month labels, no values, no tooltip. For an income forecast where users need to see month-by-month amounts, a bar chart is far more appropriate than a line.

## Design Direction

**Component**: Recharts `BarChart` — vertical bars show monthly income amounts.
**Aesthetic**: Compact, fits within the existing card alongside headline metrics and top payers. NOT a full-page chart — this is a card-embedded mini chart.

**Key design choices**:
- Recharts `BarChart` with emerald bars (consistent with positive income = good)
- X-axis: month abbreviations ("Apr", "May", "Jun") — compact, no year unless spanning year boundary
- Y-axis: hidden (too cramped) — bar heights convey relative amounts, tooltip shows exact $
- No grid lines — too compact, bars speak for themselves
- Hover tooltip: month name + dollar amount via `<Tooltip content={<ChartTooltip ... />} />`
- Bars: rounded top corners (`radius={[3, 3, 0, 0]}`), emerald fill with slight opacity
- Height: 120px (minimum viable for ChartContainer — 80px is too small for empty state icon)
- No card wrapper — chart renders inside the existing `DashboardIncomeCard`

---

## Implementation

### Step 1: Create `IncomeBarChart` component

**New file**: `frontend/packages/ui/src/components/dashboard/cards/IncomeBarChart.tsx`

```tsx
import { Bar, BarChart, Tooltip, XAxis } from "recharts"
import { ChartContainer, ChartTooltip } from "../../blocks"
import {
  chartSemanticColors,
  getAxisPreset,
  formatChartDate,
} from "../../../lib/chart-theme"

export interface IncomeBarDataPoint {
  month: string    // "YYYY-MM-DD" format (normalized from backend "YYYY-MM")
  total: number    // monthly income in $
}

interface IncomeBarChartProps {
  data: IncomeBarDataPoint[]
}
```

**Component internals**:
- Bar color: `chartSemanticColors.positive()` (emerald)
- Bar: `<Bar dataKey="total" name="Income" radius={[3, 3, 0, 0]} fill={color} fillOpacity={0.8} />`
- X-axis: `tickFormatter` using `formatChartDate(value, "monthly")` — renders "Apr 2026". For compactness, could extract just month: strip year via regex or a custom formatter. Use `getAxisPreset()` for tick styling.
- Y-axis: omitted entirely (not just hidden — don't render `<YAxis>`)
- Grid: omitted (too compact)
- Tooltip: `<Tooltip content={<ChartTooltip defaultFormat="currency" dateGranularity="monthly" />} />` — wraps ChartTooltip inside Recharts Tooltip component (this is the pattern used throughout the codebase, NOT standalone)
- `<ChartContainer height={120} minHeight={100} isEmpty={!data?.length} emptyMessage="No income forecast">`
- Margin: `{ top: 4, right: 4, bottom: 0, left: 4 }` — tight for card embedding

**Date parsing**: The month key MUST be normalized to `YYYY-MM-DD` format using the `parseChartDate` regex in `chart-theme.ts:139` which matches `/^(\d{4})-(\d{2})-(\d{2})$/`. Use the local Date constructor (`new Date(year, month-1, day)`) to avoid timezone bugs. The data mapping in Step 2 appends `-01` to the `YYYY-MM` key.

### Step 2: Update `DashboardIncomeCard` to use new chart

**File**: `frontend/packages/ui/src/components/dashboard/cards/DashboardIncomeCard.tsx`

**Add import** at top of file:
```tsx
import { IncomeBarChart, type IncomeBarDataPoint } from "./IncomeBarChart"
```

**Current** (lines 51-57) — extracts flat number array:
```tsx
const monthlyIncomeCurve = useMemo<number[]>(() => {
  if (!income?.monthly_calendar) return [];
  return Object.entries(income.monthly_calendar as Record<string, { total: number }>)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, month]) => month.total)
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
}, [income?.monthly_calendar]);
```

**Change to** — preserve month keys, normalize date format:
```tsx
const monthlyIncomeData = useMemo<IncomeBarDataPoint[]>(() => {
  if (!income?.monthly_calendar) return [];
  return Object.entries(income.monthly_calendar as Record<string, { total: number }>)
    .sort(([a], [b]) => a.localeCompare(b))
    .filter(([, month]) => typeof month.total === 'number' && Number.isFinite(month.total))
    .map(([key, month]) => ({
      month: key.length === 7 ? key + '-01' : key,  // "2026-04" → "2026-04-01" for date parsing
      total: month.total,
    }));
}, [income?.monthly_calendar]);
```

**Current chart** (lines 120-130):
```tsx
<SparklineChart
  data={monthlyIncomeCurve}
  colorScheme="emerald"
  height={36}
  showFill
/>
```

**Replace with**:
```tsx
<IncomeBarChart data={monthlyIncomeData} />
```

Also update the "MONTHLY FORECAST" label above the chart to remove `text-[10px]` cramped sizing — make it `text-xs` to match other section labels.

Remove the `SparklineChart` import if no longer used in this file.

---

## Files Changed

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/dashboard/cards/IncomeBarChart.tsx` | **NEW** — Recharts BarChart component, exports `IncomeBarDataPoint` type |
| `frontend/packages/ui/src/components/dashboard/cards/DashboardIncomeCard.tsx` | Import IncomeBarChart, replace SparklineChart, preserve month keys in data |

## DO NOT Touch

- `sparkline-chart.tsx` — still used elsewhere
- Backend income projection logic
- Performance Trend chart (just committed separately)
- Any adapter files

## Testing

1. Visual: Income card shows bar chart with monthly bars instead of wiggly line
2. Bars: emerald/teal with rounded tops
3. X-axis: month abbreviations visible (timezone-correct — "Apr" not "Mar")
4. Tooltip: hover shows month + dollar amount (via `<Tooltip content={<ChartTooltip>}`)
5. Empty state: "No income forecast" via ChartContainer when no data
6. All-zero months: bars render at zero height (acceptable — no special handling needed)
7. Responsive: bars resize with card width
8. TypeScript: zero errors

## Data Shape Reference

The `income.monthly_calendar` from the API:
```json
{
  "2026-04": { "confirmed": 500, "estimated": 353, "total": 853 },
  "2026-05": { "confirmed": 200, "estimated": 600, "total": 800 },
  ...
}
```

Keys are `YYYY-MM`, sorted chronologically. Each month has `confirmed`, `estimated`, and `total`.

**Future enhancement**: Could split bars into confirmed (solid) vs estimated (striped/lighter opacity) stacked segments using the `confirmed` and `estimated` fields. Not in scope for this plan but the data supports it.

## Codex Review Fixes (v2)

Issues fixed from Codex round 1:
1. **Tooltip wiring**: Use `<Tooltip content={<ChartTooltip ... />} />` pattern (not standalone), matching all other charts in codebase
2. **Missing imports**: Added explicit `import { IncomeBarChart, type IncomeBarDataPoint }` to DashboardIncomeCard
3. **Timezone-safe date parsing**: Normalize month keys to `YYYY-MM-DD` via `key + '-01'` in data mapping. Removed `new Date(v + '-01')` formatter — use `formatChartDate(value, "monthly")` which uses the safe local-constructor path in `chart-theme.ts:139-143`
4. **Height**: Increased from 80px to 120px (minimum viable for ChartContainer empty state icon)
5. **Edge cases**: Empty → ChartContainer handles it. All-zero → bars render at zero height (acceptable). Negative totals possible from short positions but rare for income — no special handling.
