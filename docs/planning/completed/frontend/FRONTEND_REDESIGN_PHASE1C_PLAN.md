# Frontend Redesign — Phase 1c: Expand Block Component Library

**Date:** 2026-03-06
**Status:** PLANNING
**Source:** `FRONTEND_REDESIGN_PLAN.md` Phase 1c
**Depends on:** Phase 1a (colors.ts) DONE, Phase 1b (chart-theme) DONE
**Codex Review:** R1-R5 FAIL. R6: narrowed "all new blocks follow colorScheme" to only InsightBanner + StatusCell; StatPair/TabContentWrapper/DataTable don't use colorScheme.

---

## Context

7 blocks exist in `components/blocks/`:
- **5 original** (metric-card, percentage-badge, gradient-progress, section-header, sparkline-chart) — CVA variants with 7 `colorScheme` options (emerald, blue, purple, amber, red, indigo, neutral), fixed Tailwind palette classes, `cn()` from `@risk/chassis`
- **2 from Phase 1b** (chart-tooltip, chart-container) — no `colorScheme` CVA; use semantic token classes (`bg-muted/60`, `text-muted-foreground`) for automatic dark mode

New blocks in this phase: `InsightBanner` and `StatusCell` follow the original 5's CVA + `colorScheme` pattern. `StatPair` uses CVA for size only (no colorScheme — uses a simpler `valueColor` prop). `TabContentWrapper` and `DataTable` are structural wrappers with no color scheme variants.

A codebase audit found 5 high-frequency patterns that lack shared components:
- 40+ label-value pairs with inconsistent styling
- 12+ alert/insight banner cards with duplicated structure
- 8+ colored metric cells in grids
- 7+ TabsContent+ScrollArea wrappers (identical boilerplate)
- 1 sortable table (HoldingsTable) plus several static/unstyled tables (AttributionTab, etc.) with repeated header/hover patterns but no user-driven sort

This phase adds 5 new blocks. Infrastructure only — no existing consumers migrated (same approach as Phase 1b).

---

## Block 1: `StatPair` (~60 lines)

**File:** `frontend/packages/ui/src/components/blocks/stat-pair.tsx`

Horizontal label + value row. Replaces 40+ instances of:
```tsx
<div className="flex justify-between text-sm">
  <span className="text-neutral-600">Label</span>
  <span className="font-semibold text-red-600">Value</span>
</div>
```

### Props

```typescript
import { cva, type VariantProps } from "class-variance-authority"

const statPairVariants = cva("flex items-center justify-between gap-2", {
  variants: {
    size: {
      sm: "text-xs",
      md: "text-sm",
      lg: "text-base",
    },
  },
  defaultVariants: { size: "md" },
})

export interface StatPairProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof statPairVariants> {
  label: string
  value: React.ReactNode
  valueColor?: "positive" | "negative" | "warning" | "neutral" | "muted"
  bold?: boolean          // default true — bold value text
  icon?: React.ReactNode  // optional leading icon on value side
}
```

### Rendering

- Label: `text-muted-foreground` (always)
- Value: `font-semibold` (when `bold`) + color from `valueColor` map:
  - `positive` → `text-emerald-600`
  - `negative` → `text-red-600`
  - `warning` → `text-amber-600`
  - `neutral` → `text-foreground`
  - `muted` → `text-muted-foreground`
  - Default (no valueColor) → `text-foreground`
- Value accepts ReactNode for flexible content (badges, formatted numbers, etc.)
- Icon rendered inline before value with `gap-1.5`

### Consumer examples (future migration)

```tsx
// Before (OverviewTab.tsx line 75-79)
<div className="flex justify-between">
  <span className="text-neutral-600">VaR 99%:</span>
  <span className="font-semibold text-red-600">3.6%</span>
</div>

// After
<StatPair label="VaR 99%" value="3.6%" valueColor="negative" />
```

---

## Block 2: `InsightBanner` (~90 lines)

**File:** `frontend/packages/ui/src/components/blocks/insight-banner.tsx`

Alert/insight/AI card with icon header, content area, optional action. Replaces 12+ instances across SmartAlertsPanel, AIRecommendationsPanel, MarketIntelligenceBanner, ScenarioHeader, PerformanceHeaderCard.

### Props

```typescript
const insightBannerVariants = cva(
  "rounded-xl border p-4 animate-fade-in-gentle",
  {
    variants: {
      colorScheme: {
        emerald: "border-emerald-200/50 bg-gradient-to-br from-emerald-50/70 to-white",
        blue: "border-blue-200/50 bg-gradient-to-br from-blue-50/70 to-white",
        purple: "border-purple-200/50 bg-gradient-to-br from-purple-50/70 to-white",
        amber: "border-amber-200/50 bg-gradient-to-br from-amber-50/70 to-white",
        red: "border-red-200/50 bg-gradient-to-br from-red-50/70 to-white",
        indigo: "border-indigo-200/50 bg-gradient-to-br from-indigo-50/70 to-white",
        neutral: "border-neutral-200/60 bg-gradient-to-br from-neutral-50/80 to-white",
      },
      variant: {
        default: "",
        glass: "glass-tinted",
      },
    },
    defaultVariants: { colorScheme: "neutral", variant: "default" },
  }
)

export interface InsightBannerProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof insightBannerVariants> {
  icon: React.ComponentType<{ className?: string }>
  title: string
  subtitle?: string
  badge?: React.ReactNode
  action?: React.ReactNode   // right-aligned button/link
  children?: React.ReactNode // content area below header
}
```

### Rendering

- Header row: icon in pastel circle (matching the SmartAlertsPanel/MarketIntelligenceBanner pattern, NOT the SectionHeader gradient pattern) + title + subtitle + optional badge + optional action (right-aligned)
- Icon circle: `w-7 h-7 rounded-lg bg-{color}-100 flex items-center justify-center` + `Icon className="w-3.5 h-3.5 text-{color}-600"` (pastel background, not gradient — matches actual consumer pattern in SmartAlertsPanel.tsx:16)
- Title: `text-sm font-semibold text-{color}-900`
- Subtitle: `text-xs text-{color}-700 mt-0.5`
- Children rendered below header with `mt-3` gap
- Color scheme drives all internal color classes via a lookup map (not CVA for inner elements — just a `colorClasses` record)

### Consumer examples (future migration)

```tsx
// Before (SmartAlertsPanel.tsx)
<Card className="p-4 glass-tinted border-purple-200/40 animate-fade-in-gentle">
  <div className="flex items-center space-x-3 mb-4">
    <div className="w-6 h-6 bg-purple-100 rounded-lg flex items-center justify-center">
      <AlertTriangle className="w-3 h-3 text-purple-600" />
    </div>
    <span className="font-semibold text-purple-900 text-sm">Smart Alerts</span>
    <Badge>...</Badge>
  </div>
  {/* content */}
</Card>

// After
<InsightBanner
  icon={AlertTriangle}
  title="Smart Alerts"
  colorScheme="purple"
  variant="glass"
  badge={<Badge>...</Badge>}
>
  {/* content */}
</InsightBanner>
```

---

## Block 3: `StatusCell` (~70 lines)

**File:** `frontend/packages/ui/src/components/blocks/status-cell.tsx`

Colored metric cell for dashboard grids. Replaces 8+ instances in OverviewTab (VaR/Beta/Volatility/Sharpe grid), ScenarioHeader (3-col results grid), ActiveStrategiesTab (4-col performance grid).

### Props

```typescript
const statusCellVariants = cva(
  "rounded-xl border p-4 transition-all duration-200",
  {
    variants: {
      colorScheme: {
        emerald: "border-emerald-200/60 bg-gradient-to-br from-emerald-50 to-emerald-100/50",
        blue: "border-blue-200/60 bg-gradient-to-br from-blue-50 to-blue-100/50",
        purple: "border-purple-200/60 bg-gradient-to-br from-purple-50 to-purple-100/50",
        amber: "border-amber-200/60 bg-gradient-to-br from-amber-50 to-amber-100/50",
        red: "border-red-200/60 bg-gradient-to-br from-red-50 to-red-100/50",
        indigo: "border-indigo-200/60 bg-gradient-to-br from-indigo-50 to-indigo-100/50",
        neutral: "border-neutral-200/60 bg-gradient-to-br from-neutral-50 to-neutral-100/50",
      },
      align: {
        left: "text-left",
        center: "text-center",
      },
    },
    defaultVariants: { colorScheme: "neutral", align: "left" },
  }
)

export interface StatusCellProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof statusCellVariants> {
  label: string
  value: string
  description?: string
  icon?: React.ComponentType<{ className?: string }>
}
```

### Rendering

- When icon present: header row with `flex items-center justify-between mb-2` — label left, icon right
- Label: `text-sm font-semibold text-{color}-900`
- Value: `text-2xl font-bold text-{color}-600`
- Description: `text-xs text-{color}-700 mt-1`
- Color classes from lookup map keyed by colorScheme

### Consumer examples (future migration)

```tsx
// Before (OverviewTab.tsx lines 26-35)
<Card className="p-4 bg-gradient-to-br from-red-50 to-red-100/50 border-red-200/60">
  <div className="flex items-center justify-between mb-2">
    <span className="text-sm font-semibold text-red-900">Value at Risk (95%)</span>
    <AlertTriangle className="w-4 h-4 text-red-600" />
  </div>
  <div className="text-2xl font-bold text-red-600">2.5%</div>
  <p className="text-xs text-red-700 mt-1">Daily potential loss</p>
</Card>

// After
<StatusCell
  colorScheme="red"
  icon={AlertTriangle}
  label="Value at Risk (95%)"
  value="2.5%"
  description="Daily potential loss"
/>
```

---

## Block 4: `TabContentWrapper` (~40 lines)

**File:** `frontend/packages/ui/src/components/blocks/tab-content-wrapper.tsx`

TabsContent + ScrollArea with consistent spacing. Replaces 7+ identical wrappers across stock-lookup tabs, scenario tabs, strategy tabs.

### Props

```typescript
export interface TabContentWrapperProps {
  value: string              // TabsContent value
  children: React.ReactNode
  className?: string
  height?: string            // default "h-[450px]", accepts any Tailwind height
  spacing?: "sm" | "md" | "lg"  // gap between children: 3/4/6. Default "md"
}
```

### Rendering

```tsx
<TabsContent value={value} className={cn("flex-1 min-h-0 overflow-hidden", className)}>
  <ScrollArea className={height}>
    <div className={cn("space-y-{spacing}")}>
      {children}
    </div>
  </ScrollArea>
</TabsContent>
```

- Spacing map: sm → `space-y-3`, md → `space-y-4`, lg → `space-y-6`
- `min-h-0` always applied (flex constraint for proper scroll)
- Imports `TabsContent` from `../ui/tabs` and `ScrollArea` from `../ui/scroll-area`

### Consumer examples (future migration)

```tsx
// Before (OverviewTab.tsx lines 17-19 + 110-112)
<TabsContent value="overview" className="flex-1 overflow-hidden">
  <ScrollArea className="h-[450px]">
    <div className="space-y-4">
      {/* content */}
    </div>
  </ScrollArea>
</TabsContent>

// After
<TabContentWrapper value="overview">
  {/* content */}
</TabContentWrapper>
```

---

## Block 5: `DataTable` (~130 lines)

**File:** `frontend/packages/ui/src/components/blocks/data-table.tsx`

Styled table with optional sorting, hover rows, empty state. Generic typed component. Primary target: HoldingsTable (270 lines, user-sortable). Secondary targets: AttributionTab and other static tables that share the same header/hover styling but have no user-driven sort.

### Props

```typescript
export interface DataTableColumn<T, K extends string = string> {
  key: K
  label: string
  width?: string             // Tailwind width class (e.g. "w-32")
  align?: "left" | "center" | "right"
  sortable?: boolean         // default true
  render: (row: T, index: number) => React.ReactNode
}

export interface DataTableProps<T, K extends string = string> {
  columns: DataTableColumn<T, K>[]
  data: T[]
  keyExtractor: (row: T) => string
  sortField?: K
  sortDirection?: "asc" | "desc"  // enables aria-sort on active column
  onSort?: (field: K) => void
  emptyMessage?: string      // default "No data available"
  className?: string
  hoveredRow?: string | null
  onHoveredRowChange?: (rowKey: string | null) => void
  rowClassName?: (row: T, index: number) => string
}
```

Sort key is generic `K extends string` so consumers can pass typed unions (e.g. `HoldingsSortField`) and get type-safe `onSort` callbacks. Defaults to `string` for simple cases.

### Rendering

- **Container**: `overflow-x-auto` div
- **Header**: `<thead>` with `border-b border-border/60 bg-gradient-to-r from-muted/50 to-background`
  - Each sortable column: ghost Button with label + ArrowUpDown icon (shown when active)
  - Text: `text-xs font-medium uppercase tracking-wide text-muted-foreground`
  - Alignment via `text-left` / `text-center` / `text-right`
- **Body**: `<tbody>` with `divide-y divide-border/40`
  - Row hover: `transition-all duration-200 hover:bg-muted/30`
  - Active hover (when `hoveredRow` matches): `bg-muted/20 shadow-sm`
  - Cursor: `cursor-pointer` when `onHoveredRowChange` is provided (matching existing HoldingsTable hover behavior). `onRowClick` is deferred — adding clickable rows requires keyboard/focus accessibility (tabIndex, Enter/Space handlers, role="button") which is out of scope for Phase 1c infrastructure.
  - Stagger animation delay: `animationDelay: ${index * 0.03}s`
- **Empty state**: Full-width `<td colSpan={columns.length}>` with centered message, `text-sm text-muted-foreground py-12`
- **Accessibility**:
  - Sortable `<th>`: `aria-sort="ascending"` when `sortField === column.key && sortDirection === "asc"`, `"descending"` when desc. Only applied to the currently sorted column — non-active sortable headers get no `aria-sort` attribute (per WAI-ARIA sortable table pattern). Requires `sortDirection` prop (optional — when omitted, no `aria-sort` emitted on any column).
  - `ArrowUpDown` icon: `aria-hidden="true"` (decorative)
  - Empty state uses proper `colSpan` for full-width cell
- Generic `<T, K extends string>` — fully typed columns, data, and sort keys
- Uses raw `<table>` elements (NOT shadcn Table primitives) — matches the primary target consumer (HoldingsTable) and secondary targets (AttributionTab, etc.) which all use raw `<table>`. Note: shadcn `Table` at `../ui/table.tsx` IS used elsewhere (e.g. HedgeWorkflowDialog), but the table consumers this block targets all use raw elements. Staying raw avoids a migration within a migration; consumers using shadcn Table can continue as-is.
- Import `ArrowUpDown` from lucide-react, `Button` from `../ui/button`

### Consumer examples (future migration)

```tsx
// After (HoldingsTable — simplified, typed sort key)
const columns: DataTableColumn<Holding, HoldingsSortField>[] = [
  { key: "symbol", label: "Symbol", width: "w-48",
    render: (h) => <SymbolCell holding={h} /> },
  { key: "marketValue", label: "Market Value", width: "w-32",
    render: (h) => <span>{formatCurrency(h.marketValue)}</span> },
  // ...
]

<DataTable<Holding, HoldingsSortField>
  columns={columns}
  data={holdings}
  keyExtractor={(h) => h.id}
  sortField={sortField}
  onSort={onSort}
  hoveredRow={hoveredRow}
  onHoveredRowChange={onHoveredRowChange}
/>
```

---

## Step 6: Update barrel exports

**`frontend/packages/ui/src/components/blocks/index.ts`** — append:
```typescript
export { StatPair, type StatPairProps } from "./stat-pair"
export { InsightBanner, type InsightBannerProps } from "./insight-banner"
export { StatusCell, type StatusCellProps } from "./status-cell"
export { TabContentWrapper, type TabContentWrapperProps } from "./tab-content-wrapper"
export { DataTable, type DataTableProps, type DataTableColumn } from "./data-table"
```

No changes needed to `src/index.ts` — blocks flow through `export * from './components'` already.

---

## Files Summary

| File | Changes | Lines |
|------|---------|-------|
| `blocks/stat-pair.tsx` | **NEW** | ~60 |
| `blocks/insight-banner.tsx` | **NEW** | ~90 |
| `blocks/status-cell.tsx` | **NEW** | ~70 |
| `blocks/tab-content-wrapper.tsx` | **NEW** | ~40 |
| `blocks/data-table.tsx` | **NEW** | ~130 |
| `blocks/index.ts` | Append 5 export lines | +5 |

**NOT modified:** Any existing blocks, any view components, any CSS/theme files.

---

## Execution

Can be built in a single Codex call (all 5 blocks + barrel export update) or split into 2 batches:
- Batch 1: StatPair + InsightBanner + StatusCell (simpler, ~220 lines)
- Batch 2: TabContentWrapper + DataTable (DataTable is most complex, ~170 lines)

---

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. `cd frontend && pnpm build` — must pass
3. No visual changes expected (infrastructure only, no consumers yet)
4. Verify stale grep — no files should import from new blocks yet (only barrel exports)
