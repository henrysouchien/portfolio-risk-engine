# Composable App Framework — Phase 3: SDK Bridge

**Status:** Plan — Codex review round 11
**Date:** 2026-03-23
**Goal:** Data-source-aware component primitives + layout utilities — the last mile that lets an AI write a complete dashboard in ~40 lines of TSX.

## Context

Phases 0-2 are complete: DataCatalog (32 sources), useDataSource (universal hook + 27 resolvers), and interaction primitives (useSharedState, useEvent/useEmit, useFlow). What's missing is the component layer that connects `useDataSource` to the existing block components (MetricCard, DataTable, ChartContainer, InsightBanner) so that AI-generated code doesn't need to manually wire loading states, error handling, data extraction, or layout CSS.

The chat system already has a precedent: `data-table-adapter.tsx` auto-generates render functions from format specs, and `layout-renderer.tsx` renders grid/stack/row from JSON specs. This plan generalizes those patterns into reusable React components.

## Design Decisions

1. **Format: explicit in props, no catalog changes.** FieldDescriptor has `type` but not display format. Rather than extending 32 descriptors, the AI specifies format at the call site (matching existing DataTableColumnSpec pattern).
2. **Layout: extract from chat renderer, not wrap it.** Shared CSS constants (`gapClasses`, `gridColumnClasses`) AND `clampColumns` extracted to `sdk/layout/constants.ts`, consumed by both chat renderer and SDK layout components.
3. **Package location: `packages/ui/src/sdk/`.** `@risk/ui` already depends on both `@risk/chassis` (catalog) and `@risk/connectors` (useDataSource). Exported from `@risk/ui`.
4. **ChartPanel: cartesian only in v1.** Covers line/bar/area with auto-configured axes/tooltips via existing chart-theme presets + ChartTooltip block. Pie is a different API shape (`dataKey`/`nameKey` vs `xKey`/`yKeys`) — defer to v2 or the AI drops to DataBoundary + raw Recharts.
5. **Formatting: delegate to existing formatters with exact decimal options.** `sdk/format.ts` is a thin dispatcher for table/metric rendering: `formatCurrency(v, {decimals:2})`, `formatPercent(v, {decimals:1})`, `number.toLocaleString(undefined, {maximumFractionDigits:2})`, `formatCompact(v)` from `@risk/chassis`, `formatChartDate(v)` from `lib/chart-theme`. ChartPanel does NOT use `sdk/format.ts` for axis ticks — it uses chart-theme formatters directly (see ChartPanel section). Separate narrowed type aliases per consumer: `MetricFormatType` (excludes "badge"), `TooltipFormatType` (matches ChartTooltip's `"currency" | "percent" | "number"`).
6. **Flags: import from connectors, don't copy.** Flag normalization already lives in `connectors/src/utils/scenarioFlags.ts` — it handles `type`/`flag`/`name` shape differences and deduplicates via `mergeScenarioResolverFlags()`. FlagBanner imports directly from `@risk/connectors` (export added in Step 5). No `sdk/flags.ts` file — no new flag logic in `@risk/ui`.

## Codex Review History (rounds 1-8, 14 findings resolved)

All review history consolidated here. The **implementation sections below are authoritative** — this table is historical context only.

| Round | Key findings | Resolution (final) |
|-------|-------------|-------------------|
| R1 | SourceTable contract mismatch, DataBoundary missing idle state, Page wrapping SectionHeader, ChartPanel underspecified, flags/formatting reuse, clampColumns | All addressed in implementation sections below |
| R2 | seriesLabels wiring, flag shapes, FormatType too broad, import paths, placeholderData narrowing | All addressed in implementation sections below |
| R3 | mergeScenarioResolverFlags not exported, format decimal defaults | All addressed in implementation sections below |
| R4 | ColorScheme undefined, placeholderData function arity, format null handling | All addressed in implementation sections below |
| R5 | Axis formatters missing, title dead prop, stale export claim | All addressed in implementation sections below |
| R6 | FlagBanner data?.flags type-check, Y-axis percent sign mismatch | All addressed in implementation sections below |
| R7 | chart-theme has no formatNumber | All addressed in implementation sections below |
| R8 | Stale text in review tables contradicting final implementation | Review history collapsed into this summary table |

## Implementation Steps

### Step 1: Shared Utilities (~100 lines)

**`packages/ui/src/sdk/types.ts`** (~45 lines)
```ts
// Standalone — matches the 7 values in metricCardVariants/insightBannerVariants
type ColorScheme = "emerald" | "blue" | "purple" | "amber" | "red" | "indigo" | "neutral"

// Full union — used by SourceTable (cells can render ReactNode via PercentageBadge)
type FormatType = "text" | "number" | "currency" | "percent" | "badge" | "date" | "compact"

// Narrowed for MetricGrid — MetricCard.value is string-only, no ReactNode
type MetricFormatType = Exclude<FormatType, "badge">

// Narrowed for ChartPanel — matches ChartTooltip.TooltipValueFormat exactly
type TooltipFormatType = "currency" | "percent" | "number"

type GapSize = "sm" | "md" | "lg"
type GridColumns = 1 | 2 | 3 | 4
interface FieldConfig {
  key: string              // dot-path into source data
  label?: string           // display label
  format?: MetricFormatType  // narrowed: no "badge" (MetricCard.value is string)
  colorScheme?: ColorScheme
}
```

**`packages/ui/src/sdk/format.ts`** (~40 lines)
Pure dispatcher — delegates to existing formatters with options matching current `data-table-adapter.tsx` behavior.

**Null guard first**: All branches check `value == null` → return `"—"` (em-dash) before dispatching. This extends the adapter's pattern (where `toFiniteNumber(null)` returns `null` → `"—"` for numeric formats) to all format types.

Then by format type:
- `"currency"` → `formatCurrency(value, { decimals: 2 })` from `@risk/chassis` (matches adapter's 2-decimal output)
- `"percent"` → `formatPercent(value, { decimals: 1 })` from `@risk/chassis` (matches adapter's 1-decimal output)
- `"number"` → `value.toLocaleString(undefined, { maximumFractionDigits: 2 })` (matches adapter's exact behavior)
- `"compact"` → `formatCompact(value)` from `@risk/chassis`
- `"date"` → `formatChartDate(value)` from `lib/chart-theme`
- `"badge"` → `<PercentageBadge>` from `blocks/percentage-badge`
- `"text"` → `String(value)`

These options are **identical** to the current `data-table-adapter.tsx:39-67` implementation, ensuring zero visual regression when the adapter is refactored to import from here.

Two signatures:
- `formatValueToString(value, format: MetricFormatType): string` — always returns string (for MetricCard.value)
- `formatValue(value, format: FormatType): string | ReactNode` — may return ReactNode for "badge"

Also exports `toFiniteNumber()` (extracted from `data-table-adapter.tsx`). `data-table-adapter.tsx` refactored to import both from here.

**`packages/ui/src/sdk/get.ts`** (~20 lines)
Dot-path accessor: `get(obj, "returns.totalReturn")` → value. Split-on-dot + reduce.

No `sdk/flags.ts` — flag normalization already lives in `connectors/src/utils/scenarioFlags.ts` with `mergeScenarioResolverFlags()`. FlagBanner imports from `@risk/connectors` directly.

### Step 2: Layout Primitives (~180 lines)

All in `packages/ui/src/sdk/layout/`. Pure presentation, no data fetching.

| File | Lines | Description |
|------|-------|-------------|
| `constants.ts` | ~20 | Extract `gapClasses`, `gridColumnClasses`, `clampColumns` from chat `layout-renderer.tsx` |
| `Grid.tsx` | ~25 | `<Grid columns={3} gap="md">` → CSS grid with responsive breakpoints. Uses `clampColumns`. |
| `Stack.tsx` | ~20 | `<Stack gap="md">` → flex-col |
| `Split.tsx` | ~30 | `<Split ratio={[2,1]}>` → 2-pane grid with fr units, collapses on mobile |
| `Page.tsx` | ~35 | Own lightweight header (h2 + subtitle p + optional icon + actions slot) + Stack children. Does NOT wrap SectionHeader. |
| `Tabs.tsx` | ~40 | Compound component building on existing `Tabs`/`TabsList`/`TabsTrigger`/`TabsContent` from `components/ui/tabs.tsx`. Props: `defaultValue`, `value`, `onValueChange`. Each `Tabs.Tab` requires explicit `value` string. |
| `index.ts` | ~10 | Barrel export |

### Step 3: DataBoundary (~90 lines)

**`packages/ui/src/sdk/DataBoundary.tsx`**

The foundational data-aware wrapper. Generic on `DataSourceId`. Handles **4 states**: idle, loading, error, data.

```tsx
interface DataBoundaryProps<Id extends DataSourceId> {
  source: Id
  params?: Partial<SDKSourceParamsMap[Id]>
  options?: Pick<UseQueryOptions<SDKSourceOutputMap[Id]>, 'enabled' | 'placeholderData'>
  // Exact same Pick type as useDataSource's 3rd arg — full TanStack type, no narrowing
  fallback?: React.ReactNode               // loading state
  errorFallback?: React.ReactNode          // error state (no stale data)
  idleFallback?: React.ReactNode           // idle state (disabled or missing context)
  children: (
    data: SDKSourceOutputMap[Id],
    meta: {
      flags: Flag[]
      quality: DataQuality
      stale: boolean
      refetch: () => void
      lastUpdated: Date | null
      isFetching: boolean
      isPlaceholderData: boolean
    }
  ) => React.ReactNode
}
```

State resolution:
1. `loading === true` → render `fallback` or default skeleton
2. `error != null && data == null` → render `errorFallback` or default error display
3. `data == null && !loading && !error` → **idle** → render `idleFallback` or `null`
4. `data != null` → call `children(data, meta)`

`options.enabled` defaults to `true`. Portfolio-scoped sources that lack context will hit idle state (useDataSource returns `data=null, loading=false, error=null`). `options.placeholderData` uses TanStack's full `PlaceholderDataFunction` type (2-arg: `previousData, previousQuery`) via the `Pick` — no custom narrowing.

### Step 4: Data-Source-Aware Components (~460 lines)

**`packages/ui/src/sdk/MetricGrid.tsx`** (~120 lines)
```tsx
<MetricGrid source="risk-score" fields={["overall_risk_score", "risk_category"]} columns={2} />
<MetricGrid source="performance" fields={[
  { key: "returns.totalReturn", label: "Total Return", format: "percent" },
]} />
```
- Wraps DataBoundary → extracts values via `get()` → renders `<Grid>` of `<MetricCard>`
- Accepts string shorthand (field name) or FieldConfig (dot-path + label + format: `MetricFormatType` + colorScheme)
- Uses `formatValueToString()` (always returns string, matching MetricCard.value: string)

**`packages/ui/src/sdk/SourceTable.tsx`** (~140 lines)

Bridges the SDK column spec to the real `DataTableProps` contract:

```tsx
interface SourceTableColumn {
  key: string
  label: string
  format?: FormatType
  align?: "left" | "center" | "right"
  sortable?: boolean       // default true
  tooltip?: string         // forwarded to DataTableColumn.tooltip
}

interface SourceTableProps<Id extends DataSourceId> {
  source: Id
  params?: Partial<SDKSourceParamsMap[Id]>
  field: string                          // dot-path to array field
  columns: SourceTableColumn[]
  rowKey: string                         // field name for key extraction
  onRowClick?: (row: Record<string, unknown>) => void
  emptyMessage?: string
  className?: string
}
```

Implementation details:
- `rowKey` string → `keyExtractor: (row) => String(row[rowKey])` for DataTable
- **Owns sort state internally**: `useState<{ field: string; direction: 'asc' | 'desc' } | null>(null)`. Passes `sortField`/`sortDirection`/`onSort` to DataTable.
- **Comparator policy**: Sort callback extracts raw values from rows, then: numbers via `toFiniteNumber` comparison, dates via `Date.parse`, strings via `localeCompare`. Nulls/undefined sort last always. Toggle asc→desc→clear.
- **Row click**: wraps DataTable in a `<div>` with click handler that resolves the clicked row from event target → closest `<tr>` → row index. Applies `rowClassName` for `cursor-pointer` when `onRowClick` is provided.
- Converts `SourceTableColumn[]` → `DataTableColumn<Record<string, unknown>>[]` using `formatValue()` for cell rendering (same pattern as `DataTableBlock`).

**`packages/ui/src/sdk/FlagBanner.tsx`** (~60 lines)
```tsx
<FlagBanner source="risk-score" severityFilter={["warning", "error"]} />
```
- Wraps DataBoundary
- Uses `mergeScenarioResolverFlags(resolvedFlags, (data as Record<string, unknown>)?.flags)` from `@risk/connectors`. Cast to `Record<string, unknown>` is necessary because not all `SDKSourceOutputMap[Id]` types have a `flags` property (only scenario sources do). The helper's second arg is typed `unknown` and `toNormalizedEntries()` safely returns `[]` for non-array input. Export added to `connectors/src/index.ts` in Step 5.
- Filters by severity, limits by `maxItems`
- Maps severity → InsightBanner colorScheme: error→red, warning→amber, info→blue
- Maps severity → icon: `AlertTriangle` for error, `AlertCircle` for warning, `Info` for info
- Renders `<Stack gap="sm">` of `<InsightBanner>`

**`packages/ui/src/sdk/ChartPanel.tsx`** (~140 lines)

v1: **cartesian charts only** (line, bar, area). Pie deferred.

```tsx
type CartesianChartType = "line" | "bar" | "area"

interface ChartPanelProps<Id extends DataSourceId> {
  source: Id
  params?: Partial<SDKSourceParamsMap[Id]>
  field: string                          // dot-path to array data
  chartType?: CartesianChartType         // default "line"
  xKey: string
  yKeys: string[]
  seriesLabels?: Record<string, string>  // yKey → display name for legend + tooltip
  title?: string
  height?: number                        // default 300
  legend?: boolean                       // default true
  dateGranularity?: DateGranularity      // forwarded to ChartTooltip
  yFormat?: TooltipFormatType             // narrowed to ChartTooltip's accepted types
  className?: string
}
```

Implementation:
- Wraps DataBoundary → extracts data array via `get(data, field)`
- **Title**: renders `{title && <h3 className="mb-2 text-sm font-medium text-foreground">{title}</h3>}` above ChartContainer (ChartContainer has no title API; existing charts render titles outside, e.g. `PerformanceTrendChart.tsx:88`)
- Uses `ChartContainer` block for loading/empty/error chrome
- Renders appropriate Recharts component: `LineChart`/`BarChart`/`AreaChart` + `Line`/`Bar`/`Area` per yKey
- **Series `name` prop**: Each `<Line>`/`<Bar>`/`<Area>` gets `name={seriesLabels?.[yKey] ?? yKey}`. This is the existing codebase pattern (e.g. `PerformanceTrendChart.tsx:139` sets `name="Portfolio"`). ChartTooltip receives `entry.name` matching this display label.
- **Axis tick formatters**: `XAxis tickFormatter={(v) => formatChartDate(v, dateGranularity ?? 'daily')}` from `lib/chart-theme`. `YAxis tickFormatter` uses **chart-theme formatters** (not `sdk/format.ts`): `yFormat === 'percent' ? (v) => formatPercent(v) : yFormat === 'currency' ? (v) => formatCurrency(v) : (v) => v.toLocaleString("en-US")` where `formatPercent`/`formatCurrency` come from `lib/chart-theme`, and the number fallback uses inline `toLocaleString` matching ChartTooltip's exact number branch (`chart-tooltip.tsx:40`). No `formatNumber` from chart-theme (it doesn't exist there). This ensures axis and tooltip use the same formatter path.
- Uses `ChartTooltip` block as custom tooltip component, with:
  - `dateGranularity` forwarded
  - `valueFormatters` built as `Record<displayName, yFormat>` (keyed by the same display names set on series `name` props)
  - `defaultFormat` from `yFormat`
- Auto-configures via chart-theme presets: `getAxisPreset()` for XAxis/YAxis **styling** (font, tick size), `getGridPreset()` for CartesianGrid, `getChartColor(index)` for each series
- `legend && <Legend />` from Recharts — legend reads series `name` props automatically

### Step 5: Wiring (~20 lines)

- **`packages/ui/src/sdk/index.ts`** — barrel export for entire SDK
- **Update `packages/ui/src/index.ts`** — add `export * from './sdk'`
- **Refactor `src/components/chat/blocks/layout-renderer.tsx`** — import `gapClasses`, `gridColumnClasses`, `clampColumns` from `../../../sdk/layout/constants` (3 levels: `components/chat/blocks/` → `src/sdk/layout/`)
- **Refactor `src/components/chat/blocks/data-table-adapter.tsx`** — import `formatValue`/`toFiniteNumber` from `../../../sdk/format` (same depth)
- **Update `packages/connectors/src/index.ts`** — add `export { mergeScenarioResolverFlags } from './utils/scenarioFlags'` (FlagBanner needs this export)

### Step 6: Tests (~310 lines, 7 files)

All in `packages/ui/src/sdk/__tests__/`:

| Test file | ~Lines | Covers |
|-----------|--------|--------|
| `format.test.ts` | 50 | formatValue dispatches correctly for each FormatType, null/undefined → em-dash for ALL format types (including text/date), decimal options match adapter |
| `get.test.ts` | 30 | Simple, nested, missing, array-index paths |
| `DataBoundary.test.tsx` | 70 | **4 states**: idle (disabled/no context), loading, error, data. Custom fallbacks. Meta forwarding. |
| `MetricGrid.test.tsx` | 50 | String shorthand, FieldConfig, format application, grid columns |
| `SourceTable.test.tsx` | 50 | keyExtractor bridging, internal sort state + comparator policy (number/string/null), row click |
| `FlagBanner.test.tsx` | 30 | Flag merge from multiple sources, severity filter, maxItems |
| `ChartPanel.test.tsx` | 30 | Cartesian chart types, ChartTooltip integration, seriesLabels, legend toggle |

Mock `useDataSource` via `vi.mock('@risk/connectors')`. Mock Recharts for ChartPanel (jsdom doesn't render SVG).

## File Summary

| Category | Files | Lines |
|----------|-------|-------|
| Shared utilities | 3 | ~100 |
| Layout primitives | 7 | ~180 |
| DataBoundary | 1 | ~90 |
| Data-aware components | 4 | ~460 |
| Wiring/exports | 5 | ~25 |
| Tests | 7 | ~310 |
| **Total** | **27** | **~1165** |

## Sequencing

```
Step 1 (utils) ─────────┐
                         ├──→ Step 3 (DataBoundary) ──→ Step 4 (components) ──→ Step 5 (wiring)
Step 2 (layout) ────────┘                                                            ↓
                                                                                Step 6 (tests)
```

Steps 1+2 are independent (parallel). Step 3 depends on Step 1. Step 4 depends on 1+2+3. Steps 5+6 are cleanup/validation. Tests can be written incrementally with each step.

## Verification

1. **TypeScript**: `cd frontend && npx tsc --noEmit` — zero errors
2. **Tests**: `cd frontend && npx vitest run packages/ui/src/sdk/` — all pass
3. **Existing tests**: `cd frontend && npx vitest run` — no regressions (chat blocks, layout-renderer, scenarioSignals still work after refactor)
4. **Visual**: Write the 40-line dashboard example, render in browser, verify it fetches data and displays correctly
5. **Bundle**: `cd frontend && npx vite build` — SDK adds to `@risk/ui` chunk, no new chunks needed

## End-to-End Example: 40-Line Dashboard

After implementation, this should work:

```tsx
import { useSharedState } from '@risk/connectors'
import { Page, Grid, Split, Tabs, MetricGrid, SourceTable, ChartPanel, FlagBanner, DataBoundary } from '@risk/ui'

export function RiskDashboard() {
  const [selectedTicker, setSelectedTicker] = useSharedState<string | null>("selectedTicker", null)

  return (
    <Page title="Risk Dashboard" subtitle="Real-time portfolio monitoring">
      <FlagBanner source="risk-score" severityFilter={["warning", "error"]} />

      <MetricGrid source="risk-score" fields={[
        { key: "overall_risk_score", label: "Risk Score", format: "number" },
        { key: "risk_category", label: "Category" },
      ]} columns={2} />

      <Split ratio={[2, 1]}>
        <ChartPanel
          source="performance"
          field="performanceTimeSeries"
          chartType="line"
          xKey="date"
          yKeys={["portfolioCumReturn", "benchmarkCumReturn"]}
          seriesLabels={{ portfolioCumReturn: "Portfolio", benchmarkCumReturn: "Benchmark" }}
          dateGranularity="monthly"
          yFormat="percent"
          title="Cumulative Returns"
        />
        <MetricGrid source="performance" fields={[
          { key: "returns.totalReturn", label: "Total Return", format: "percent" },
          { key: "returns.annualizedReturn", label: "Annualized", format: "percent" },
          { key: "risk.volatility", label: "Volatility", format: "percent" },
          { key: "risk.maxDrawdown", label: "Max Drawdown", format: "percent" },
        ]} columns={1} />
      </Split>

      <Tabs defaultValue="holdings">
        <Tabs.Tab value="holdings" label="Holdings">
          <SourceTable
            source="positions-enriched"
            field="holdings"
            columns={[
              { key: "ticker", label: "Ticker" },
              { key: "name", label: "Name" },
              { key: "value", label: "Value", format: "currency", align: "right" },
              { key: "weight", label: "Weight", format: "percent", align: "right" },
            ]}
            rowKey="ticker"
            onRowClick={(row) => setSelectedTicker(String(row.ticker))}
          />
        </Tabs.Tab>
        <Tabs.Tab value="risk-factors" label="Risk Factors">
          <SourceTable
            source="risk-score"
            field="component_scores"
            columns={[
              { key: "name", label: "Component" },
              { key: "score", label: "Score", format: "number", align: "right" },
              { key: "maxScore", label: "Max", format: "number", align: "right" },
            ]}
            rowKey="name"
          />
        </Tabs.Tab>
      </Tabs>
    </Page>
  )
}
```

## Critical Files

- `packages/connectors/src/resolver/useDataSource.ts` — hook that DataBoundary wraps (has `enabled`/`placeholderData` options)
- `packages/connectors/src/resolver/types.ts` — `ResolvedData<T>`, `Flag`, `DataQuality`
- `packages/chassis/src/catalog/types.ts` — `DataSourceId`, `SDKSourceOutputMap`, `SDKSourceParamsMap`, `FieldDescriptor`
- `packages/chassis/src/utils/formatting.ts` — re-exports `formatCurrency`/`formatPercent`/`formatNumber`/`formatCompact` from `@risk/app-platform`
- `packages/ui/src/lib/chart-theme.ts` — `formatChartDate`, `getAxisPreset`, `getGridPreset`, `getTooltipStyle`, `getChartColor`, `DateGranularity`
- `packages/ui/src/components/blocks/metric-card.tsx` — MetricCard props for MetricGrid delegation
- `packages/ui/src/components/blocks/data-table.tsx` — DataTable + DataTableColumn + DataTableProps (keyExtractor, sortField/sortDirection/onSort, hoveredRow/onHoveredRowChange, rowClassName)
- `packages/ui/src/components/blocks/chart-container.tsx` — ChartContainer for ChartPanel delegation
- `packages/ui/src/components/blocks/chart-tooltip.tsx` — ChartTooltip with dateGranularity, valueFormatters, defaultFormat
- `packages/ui/src/components/blocks/insight-banner.tsx` — InsightBanner (requires icon, title; optional subtitle, colorScheme)
- `packages/ui/src/components/ui/tabs.tsx` — existing Tabs/TabsList/TabsTrigger/TabsContent (Radix wrappers)
- `packages/connectors/src/utils/scenarioFlags.ts` — `mergeScenarioResolverFlags()` (flag normalization + dedup). **NOT currently exported from `@risk/connectors` root** — Step 5 adds the export line to `connectors/src/index.ts`.
- `packages/ui/src/components/chat/blocks/data-table-adapter.tsx` — existing formatValue/toFiniteNumber to extract
- `packages/ui/src/components/chat/blocks/layout-renderer.tsx` — existing gapClasses/gridColumnClasses/clampColumns to extract
