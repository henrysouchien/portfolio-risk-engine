# Frontend Redesign — Phase 1b: Recharts Theme Layer

**Date:** 2026-03-05
**Status:** PLANNING
**Source:** `FRONTEND_REDESIGN_PLAN.md` Phase 1b
**Codex Review:** R1 FAIL (F1-F3 fixed): DateGranularity exported, formatChartDate accepts number, negative index guard added.

---

## Context

Recharts v2.8.0 is installed in `packages/ui` but completely unused. All current charts are custom:
- `PerformanceChart.tsx` (417 lines) — Custom HTML/Tailwind bar chart with mock data
- `SparklineChart.tsx` (174 lines) — Pure SVG sparkline in MetricCard (stays as-is)

CSS already defines 5 chart color variables (`--chart-1` through `--chart-5`) in both light/dark themes (`index.css` lines 214-219, 259-264), plus Tailwind `chart-1` through `chart-5` in `tailwind.config.js`. No shadcn chart wrapper exists.

Phase 1b builds the Recharts theme infrastructure so chart sub-components extracted in Phases 2-4 have a polished, consistent foundation. Infrastructure only — no existing charts are migrated yet.

---

## Step 1: Create `lib/chart-theme.ts`

**New file:** `frontend/packages/ui/src/lib/chart-theme.ts` (~120 lines)

### 1a. Color palette from CSS variables

Recharts uses inline styles (`stroke`, `fill` as hex/rgb), not CSS classes. We need runtime CSS variable reading.

```typescript
/**
 * Read a CSS variable's HSL components and return an hsl() string.
 * CSS vars store bare HSL: "160 74% 42%", we wrap as "hsl(160 74% 42%)".
 * Guard for SSR/test: typeof document === 'undefined' → fallback.
 */
function getCSSColor(variable: string): string {
  if (typeof document === 'undefined') return '#888888'
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(variable)
    .trim()
  return value ? `hsl(${value})` : '#888888'
}

const CHART_COLOR_COUNT = 5

/** Get chart color by 0-based index. Wraps mod 5. Reads --chart-N CSS vars. Negative indices clamped to 0. */
export function getChartColor(index: number): string {
  const cssIndex = (((index % CHART_COLOR_COUNT) + CHART_COLOR_COUNT) % CHART_COLOR_COUNT) + 1
  return getCSSColor(`--chart-${cssIndex}`)
}

/** Get full palette as string[]. Call inside render for current theme. */
export function getChartColors(): string[] {
  return Array.from({ length: CHART_COLOR_COUNT }, (_, i) => getChartColor(i))
}

/** Semantic color accessors for financial chart meanings */
export const chartSemanticColors = {
  positive: () => getCSSColor('--chart-1'),   // emerald - gains
  neutral: () => getCSSColor('--chart-2'),    // blue - benchmark/info
  tertiary: () => getCSSColor('--chart-3'),   // purple - additional series
  warning: () => getCSSColor('--chart-4'),    // amber - caution
  negative: () => getCSSColor('--chart-5'),   // red - losses
} as const
```

### 1b. Axis/grid presets

```typescript
export interface AxisPreset {
  tick: { fontSize: number; fill: string; fontFamily: string }
  axisLine: { stroke: string; strokeWidth: number } | false
  tickLine: { stroke: string; strokeWidth: number } | false
}

/** Call inside render (reads CSS vars for current theme). */
export function getAxisPreset(): AxisPreset {
  return {
    tick: { fontSize: 11, fill: getCSSColor('--muted-foreground'), fontFamily: "'Inter', sans-serif" },
    axisLine: { stroke: getCSSColor('--border'), strokeWidth: 1 },
    tickLine: false,
  }
}

export function getGridPreset() {
  return {
    strokeDasharray: '3 3',
    stroke: getCSSColor('--border'),
    strokeOpacity: 0.5,
    vertical: false as const,
  }
}

export function getReferenceLinePreset() {
  return {
    stroke: getCSSColor('--muted-foreground'),
    strokeDasharray: '4 4',
    strokeWidth: 1,
    strokeOpacity: 0.6,
  }
}
```

### 1c. Financial data formatters

```typescript
/** Format as currency: $1,234.56 or $1.2M/$1.2K in compact mode */
export function formatCurrency(
  value: number,
  opts?: { decimals?: number; compact?: boolean }
): string {
  const { decimals = 2, compact = false } = opts ?? {}
  if (compact && Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (compact && Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD',
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(value)
}

/** Format as percent: +12.8%. Value already in percent (NOT decimal). */
export function formatPercent(
  value: number,
  opts?: { decimals?: number; sign?: boolean }
): string {
  const { decimals = 1, sign = true } = opts ?? {}
  const prefix = sign && value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(decimals)}%`
}

/** Format as basis points: +44 bps */
export function formatBasisPoints(value: number): string {
  const bps = Math.round(value * 100)
  const prefix = bps > 0 ? '+' : ''
  return `${prefix}${bps} bps`
}

export type DateGranularity = 'intraday' | 'daily' | 'monthly' | 'yearly'

/** Format date for chart axis/tooltip. Accepts string, Date, or epoch number (Recharts label type). */
export function formatChartDate(
  date: string | number | Date,
  granularity: DateGranularity = 'daily'
): string {
  const d = date instanceof Date ? date : new Date(date)
  switch (granularity) {
    case 'intraday': return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
    case 'daily': return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    case 'monthly': return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    case 'yearly': return d.getFullYear().toString()
  }
}
```

### 1d. Tooltip style helper

```typescript
/** Inline style for Recharts <Tooltip contentStyle={...}> */
export function getTooltipStyle(): React.CSSProperties {
  return {
    backgroundColor: getCSSColor('--card'),
    borderColor: getCSSColor('--border'),
    borderWidth: 1,
    borderRadius: 12,
    padding: '12px 16px',
    color: getCSSColor('--card-foreground'),
    fontFamily: "'Inter', sans-serif",
    fontSize: 12,
    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.12), 0 4px 16px rgba(0, 0, 0, 0.08)',
    backdropFilter: 'blur(16px)',
  }
}
```

---

## Step 2: Create `components/blocks/chart-tooltip.tsx`

**New file:** `frontend/packages/ui/src/components/blocks/chart-tooltip.tsx` (~80 lines)

Custom Recharts tooltip with glass styling:

```typescript
import { cn } from '@risk/chassis'
import { formatCurrency, formatPercent, formatChartDate, type DateGranularity } from '../../lib/chart-theme'

export type TooltipValueFormat = 'currency' | 'percent' | 'number'

export interface ChartTooltipProps {
  active?: boolean
  payload?: Array<{
    name: string; value: number
    color?: string; stroke?: string; fill?: string
    dataKey?: string; payload?: Record<string, unknown>
  }>
  label?: string | number
  className?: string
  dateGranularity?: DateGranularity
  labelFormatter?: (label: string | number) => string
  valueFormatters?: Record<string, TooltipValueFormat>
  defaultFormat?: TooltipValueFormat
}
```

- Container: `bg-card/95 backdrop-blur-xl border-border/50 rounded-xl shadow-lg`
- Header: formatted date via `formatChartDate(label, dateGranularity)` — `label` is `string | number` from Recharts, both accepted by `formatChartDate`
- Body: colored dot (`h-2.5 w-2.5 rounded-full`) + series name + formatted value
- Values use `tabular-nums` for alignment
- `formatValue()` internal helper dispatches to `formatCurrency`/`formatPercent`/`toLocaleString`
- Dark mode automatic via Tailwind classes

---

## Step 3: Create `components/blocks/chart-container.tsx`

**New file:** `frontend/packages/ui/src/components/blocks/chart-container.tsx` (~100 lines)

Responsive wrapper using Recharts `ResponsiveContainer`:

```typescript
import { ResponsiveContainer } from 'recharts'
import { cn } from '@risk/chassis'

export interface ChartContainerProps {
  children: React.ReactElement
  className?: string
  height?: number       // default 320
  minHeight?: number    // default 200
  isLoading?: boolean
  isEmpty?: boolean
  emptyMessage?: string // default "No data available"
  error?: string | null
}
```

States:
- **Loading**: 12 animated bars with staggered `animationDelay`, sine-wave heights, `animate-pulse` + `bg-muted/60`
- **Empty**: Minimal inline SVG chart icon + message text
- **Error**: Error circle SVG icon + red message
- **Normal**: `<ResponsiveContainer width="100%" height={resolvedHeight}>{children}</ResponsiveContainer>`

`children` typed as `React.ReactElement` (Recharts `ResponsiveContainer` requirement).

---

## Step 4: Update barrel exports

**`frontend/packages/ui/src/components/blocks/index.ts`** — add:
```typescript
export { ChartTooltip, type ChartTooltipProps, type TooltipValueFormat } from "./chart-tooltip"
export { ChartContainer, type ChartContainerProps } from "./chart-container"
```

**`frontend/packages/ui/src/index.ts`** — add:
```typescript
export {
  getChartColor, getChartColors, chartSemanticColors,
  getAxisPreset, getGridPreset, getReferenceLinePreset, getTooltipStyle,
  formatCurrency, formatPercent, formatBasisPoints, formatChartDate,
} from './lib/chart-theme'
```

Blocks already flow through `components/index.ts` → package `index.ts` via `export *`.

---

## Files Modified

| File | Changes |
|------|---------|
| `lib/chart-theme.ts` | **NEW** — color palette, axis presets, formatters, tooltip style (~120 lines) |
| `blocks/chart-tooltip.tsx` | **NEW** — styled Recharts tooltip (~80 lines) |
| `blocks/chart-container.tsx` | **NEW** — responsive wrapper with loading/empty/error (~100 lines) |
| `blocks/index.ts` | Add 2 export lines |
| `src/index.ts` | Add chart-theme exports |

**NOT modified:** PerformanceChart.tsx, SparklineChart.tsx, theme/colors.ts, index.css, tailwind.config.js

---

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. `cd frontend && pnpm build` — must pass (confirms Recharts tree-shaking)
3. No visual changes expected (infrastructure only, no consumers yet)
4. Verify stale grep — no other files should import from `chart-theme.ts` yet (only barrel exports)
