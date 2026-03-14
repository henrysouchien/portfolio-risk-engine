# Frontend Redesign — Batch 3: StatusCell + DataTable Migration

## Overview

Two sub-batches:
- **3a: StatusCell** — 6 colored metric cards across 2 files replaced with the `<StatusCell>` block
- **3b: DataTable** — 8 inline `<table>` elements across 2 files replaced with the `<DataTable>` block

3a is DRY cleanup with minor visual consistency improvements (icon position standardization). 3b is DRY cleanup with intentional visual upgrades (gradient header, row hover, fade-in animation).

---

## Batch 3a: StatusCell Migration

### StatusCell API

```tsx
<StatusCell
  label="Value at Risk (95%)"
  value="2.5%"
  description="Daily potential loss"
  icon={AlertTriangle}
  colorScheme="red"
/>
```

| Prop | Default | Options |
|------|---------|---------|
| `label` | required | Label text (text-sm font-semibold) |
| `value` | required | Display value (text-2xl font-bold) |
| `description` | — | Optional subtitle (text-xs) |
| `icon` | — | Optional `ComponentType<{ className?: string }>` — rendered top-right |
| `colorScheme` | `"neutral"` | `emerald`, `blue`, `purple`, `amber`, `red`, `indigo`, `neutral` |
| `align` | `"left"` | `left`, `center` |

**Layout:** Colored gradient card (`from-{color}-50 to-{color}-100/50 border-{color}-200/60`). When icon provided: `flex items-center justify-between` with label left, icon right. Value below in text-2xl. Description below value in text-xs.

**Color classes:** Label uses `text-{color}-900`, value uses `text-{color}-600` (except `neutral` which uses `text-neutral-700`), description uses `text-{color}-700`, icon uses `text-{color}-600`.

### Site 1: `stock-lookup/OverviewTab.tsx` — 4 StatusCells (lines 22-61)

The key risk metrics grid has 4 inline colored cards that are exact StatusCell matches.

| Card | Label | Value Expression | Description | Icon | colorScheme |
|------|-------|-----------------|-------------|------|-------------|
| VaR 95% | `"Value at Risk (95%)"` | `{selectedStock.var95?.toFixed(1) ?? 'N/A'}%` | `"Daily potential loss"` | `AlertTriangle` | `red` |
| Beta | `"Beta"` | `{selectedStock.beta.toFixed(2)}` | `"Market sensitivity"` | `Target` | `purple` |
| Volatility | `"Volatility"` | `{selectedStock.volatility.toFixed(1)}%` | `"Annualized"` | `BarChart3` | `amber` |
| Sharpe Ratio | `"Sharpe Ratio"` | `{selectedStock.sharpeRatio.toFixed(2)}` | `"Risk-adjusted return"` | `Target` | `emerald` |

**Current structure (each card):**
```tsx
<Card className="p-4 bg-gradient-to-br from-red-50 to-red-100/50 border-red-200/60">
  <div className="flex items-center justify-between mb-2">
    <span className="text-sm font-semibold text-red-900">Value at Risk (95%)</span>
    <AlertTriangle className="w-4 h-4 text-red-600" />
  </div>
  <div className="text-2xl font-bold text-red-600">
    {selectedStock.var95?.toFixed(1) ?? 'N/A'}%
  </div>
  <p className="text-xs text-red-700 mt-1">Daily potential loss</p>
</Card>
```

**After:**
```tsx
<StatusCell
  label="Value at Risk (95%)"
  value={`${selectedStock.var95?.toFixed(1) ?? 'N/A'}%`}
  description="Daily potential loss"
  icon={AlertTriangle}
  colorScheme="red"
/>
```

**Visual differences:**
- StatusCell uses `rounded-xl` (matches Card default). `p-4` matches. `mb-2` / `mt-1` spacing matches.
- **Shadow loss:** Current cards use `<Card>` which has `shadow` in default variant. StatusCell is a plain `div` with no shadow. This is a minor visual change — the gradient background and border are the dominant visual, shadow is subtle.
- Value colors: Current uses `text-{color}-600`. StatusCell also uses `text-{color}-600`. Exact match.

### Site 2: `FactorRiskModel.tsx` — 2 StatusCells (lines 403-418)

The risk attribution tab's summary metrics grid has 2 cards.

| Card | Label | Value Expression | Description | Icon | colorScheme |
|------|-------|-----------------|-------------|------|-------------|
| Total Risk | `"Total Risk"` | `{formatPercent(resolvedTotalRisk, { decimals: 1 })}` | `"Annualized Volatility"` | `Target` | `purple` |
| Active Risk | `"Active Risk"` | `{formatPercent(activeRisk, { decimals: 1 })}` | `"Tracking Error"` | `Activity` | `emerald` |

**Current structure:**
```tsx
<Card className="p-4 bg-gradient-to-br from-purple-50 to-purple-100/50 border-purple-200/60">
  <div className="flex items-center space-x-2 mb-2">
    <Target className="w-4 h-4 text-purple-600" />
    <span className="text-sm font-semibold text-purple-900">Total Risk</span>
  </div>
  <div className="text-2xl font-bold text-purple-900">{formatPercent(...)}</div>
  <div className="text-xs text-purple-700">Annualized Volatility</div>
</Card>
```

**After:**
```tsx
<StatusCell
  label="Total Risk"
  value={formatPercent(resolvedTotalRisk, { decimals: 1 })}
  description="Annualized Volatility"
  icon={Target}
  colorScheme="purple"
/>
```

**Visual differences:**
1. **Icon position change:** Current has icon LEFT of label (`flex items-center space-x-2`). StatusCell puts icon RIGHT of label (`flex items-center justify-between`). This is a minor layout change that matches OverviewTab's pattern. Accept for consistency.
2. **Value color:** Current uses `text-purple-900`. StatusCell uses `text-purple-600`. This is a minor color change — value becomes slightly lighter. Accept.
3. **Shadow loss:** Same as OverviewTab — current `<Card>` has shadow, StatusCell does not. Minor.

### NOT Migrated

| File | What | Why |
|------|------|-----|
| `FactorRiskModel.tsx:459-471` | 3 performance tab cards (Factor Alpha, Info Ratio, R-Squared) | Value-above-label order (inverted from StatusCell). text-lg not text-2xl. text-center. Would need StatusCell API change to support inverted order. |
| `stock-lookup/TechnicalsTab.tsx:22-43` | 2 indicator cards (RSI, MACD) | text-xl not text-2xl. RSI has embedded GradientProgress child. MACD uses `green` color not in StatusCell variants. StatusCell doesn't support children. |
| `stock-lookup/FundamentalsTab.tsx:83-128` | 4 financial metric cards (P/E, ROE, Debt/Equity, Profit Margin) | text-xl not text-2xl. Colors `teal`, `orange`, `rose` not in StatusCell's 7 color variants. No icon. |
| `performance/PerformanceHeaderCard.tsx:188-248` | 4 header metric cards | Different gradient (`from-{color}-300/30 to-transparent`), `animate-magnetic-hover`, `hover-lift-subtle`, relative overflow-hidden. Highly custom layout. |
| `RiskMetrics.tsx:287-358` | Dynamic risk metric cards | Different gradient pattern (`from-{color}-100 to-{color}-200/80` not `from-{color}-50 to-{color}-100/50`), status-dependent coloring, progress bars, trend indicators. Complex dynamic rendering. |
| `performance/BenchmarksTab.tsx:36-68` | 3 return comparison cards | Custom CSS classes (`gradient-sophisticated`, `gradient-depth`, `gradient-success`). Badges inline with header. Not gradient-50 pattern. |
| `scenario/MonteCarloTab.tsx:142-167` | 4 summary stat cards | text-lg font-semibold (not text-2xl font-bold). Label text-xs (not text-sm font-semibold). No gradient background. Different structure. |
| `scenario/OptimizationsTab.tsx:99-130` | 5 risk check cards | text-center text-lg, bg-white not gradient. Different card structure entirely. |
| `strategy/MarketplaceTab.tsx:38-57` | 3 featured strategy metric cards | text-center text-xl, bg-white border not gradient. Nested inside larger banner card. |
| `stock-lookup/TechnicalsTab.tsx:104-125` | Bollinger Bands card | Contains Badge + conditional text, not label/value/description pattern. |
| `RiskAnalysis.tsx:178-233` | Risk factor cards | Expandable sections, progress bars, mitigation strategies. Complex interactive cards. |

### Import Changes

**OverviewTab.tsx:**
- Add: `StatusCell` to existing blocks import (already imports `GradientProgress, StatPair, TabContentWrapper`)
- Keep: `AlertTriangle, BarChart3, Target` from lucide-react (used by StatusCell icon prop)
- Keep: `Card` from ui/card (still used at lines 65 and 95 for Additional Risk Metrics and Risk Assessment cards)

**FactorRiskModel.tsx:**
- Add: `StatusCell` to blocks import (if not already imported)
- Keep: `Target`, `Activity` from lucide-react
- Keep: `Card` import (used extensively elsewhere in file)

---

## Batch 3b: DataTable Migration

### DataTable API

```tsx
<DataTable
  columns={columns}
  data={rows}
  keyExtractor={(row) => row.name}
  emptyMessage="No data available"
/>
```

| Prop | Required | Description |
|------|----------|-------------|
| `columns` | Yes | `DataTableColumn<T>[]` — key, label, width?, align?, sortable?, render |
| `data` | Yes | `T[]` — row data array |
| `keyExtractor` | Yes | `(row: T) => string` — unique row key |
| `sortField` | No | Current sort field key |
| `sortDirection` | No | `"asc"` or `"desc"` |
| `onSort` | No | `(field: K) => void` — sort callback |
| `emptyMessage` | No | Empty state text (default: "No data available") |
| `hoveredRow` | No | Currently hovered row key |
| `onHoveredRowChange` | No | `(key: string \| null) => void` |
| `rowClassName` | No | `(row: T, index: number) => string` |
| `className` | No | Wrapper className |

**Visual features vs current inline tables:**
- **Header:** `bg-gradient-to-r from-muted/50 to-background` gradient + `border-b border-border/60` (current tables have plain `border-b border-neutral-200` or similar)
- **Header text:** `text-xs font-medium uppercase tracking-wide text-muted-foreground` (current: `text-xs uppercase tracking-wide text-neutral-500` — nearly identical)
- **Body rows:** `divide-y divide-border/40` + `animate-fade-in-gentle` + `hover:bg-muted/30` transition (current: `border-b border-neutral-100`, no hover, no animation)
- **Cell padding:** `px-6 py-4` (current: `py-3 pr-4` / `px-4 py-3` — DataTable is slightly more spacious)

These differences are intentional visual upgrades: gradient header, row hover, staggered fade-in animation.

### Site 1: `performance/AttributionTab.tsx` — 4 Tables

All 4 tables share the same 4-column pattern (Name, Weight/Beta, Return, Contribution) with color-coded contribution column.

#### Table 1: Sector Attribution (lines 38-69)

**Columns:**

| Key | Label | Align | Render |
|-----|-------|-------|--------|
| `name` | Sector | left | `row.name` (font-medium text-neutral-900) |
| `allocation` | Weight | right | `formatOptionalPercent(row.allocation, 2)` |
| `return` | Return | right | `formatPercent(row.return, { decimals: 2, sign: true })` |
| `contribution` | Contribution | right | `formatPercent(row.contribution, ...)` with `getChangeColor()` + font-medium |

**Data:** `sortedSectorRows` | **Key:** `row.name` | **Empty:** "No sector attribution data available."

#### Table 2: Factor Attribution (lines 76-104)

Same structure as Sector but with Beta column instead of Weight.

| Key | Label | Align | Render |
|-----|-------|-------|--------|
| `name` | Factor | left | `row.name` |
| `beta` | Beta | right | `formatOptionalNumber(row.beta, 3)` |
| `return` | Return | right | `formatPercent(...)` |
| `contribution` | Contribution | right | Color-coded |

**Data:** `sortedFactorRows` | **Key:** `row.name` | **Empty:** "Factor attribution requires ≥12 months of data."

**Note:** Conditional rendering — entire table section only renders when `sortedFactorRows.length > 0`. The DataTable's emptyMessage won't be reached. Keep the outer conditional check as-is, with DataTable inside.

#### Table 3: Top Contributors (lines 111-149)

Same 4-column pattern (Ticker, Weight, Return, Contribution).

**Data:** `sortedContributorRows.slice(0, showAllContributors ? undefined : 5)` | **Key:** `` `${row.symbol}-${row.name}` `` | **Empty:** "No security contributors available."

**Note:** "Show all" button is OUTSIDE the table (lines 143-149). DataTable receives the already-sliced data array. Button stays in the parent JSX after the DataTable. No conflict.

#### Table 4: Top Detractors (lines 156-195)

Identical to Contributors. Same "Show all" button pattern.

**Data:** `sortedDetractorRows.slice(0, showAllDetractors ? undefined : 5)` | **Key:** `` `${row.symbol}-${row.name}` ``

#### Column Definition Pattern (shared)

All 4 tables can share column definition factories or inline definitions. The contribution column render is identical across all 4:

```tsx
{
  key: "contribution",
  label: "Contribution",
  align: "right" as const,
  sortable: false,
  render: (row) => (
    <span className={`font-medium ${getChangeColor(row.contribution, true)}`}>
      {formatPercent(row.contribution, { decimals: 2, sign: true })}
    </span>
  ),
}
```

#### Import Changes

- Add: `DataTable` and `DataTableColumn` to blocks import
- Remove: (no imports to remove — table elements are JSX intrinsics)

### Site 2: `strategy/PerformanceTab.tsx` — 4 Tables (lines 199-331)

All 4 tables follow the same pattern as AttributionTab. They render backtest results.

#### Table 1: Annual Breakdown (lines 199-228)

| Key | Label | Align | Render |
|-----|-------|-------|--------|
| `year` | Year | left | `row.year` (font-medium text-neutral-900) |
| `portfolioReturn` | Portfolio | right | `formatPercent(row.portfolioReturn, { decimals: 2, sign: true })` |
| `benchmarkReturn` | {benchmarkTicker \|\| "SPY"} | right | `formatPercent(row.benchmarkReturn, ...)` |
| `alpha` | Alpha | right | Color-coded with `getChangeColor()` + font-medium |

**Data:** `annualBreakdownRows` | **Key:** `String(row.year)` | **Empty:** "No annual breakdown data available."

**Note:** Column 3 header is dynamic (`backtestData.benchmarkTicker || "SPY"`). DataTable supports this — the `label` prop is a string, set at column definition time.

#### Table 2: Security Attribution (lines 232-263)

| Key | Label | Align | Render |
|-----|-------|-------|--------|
| `name` | Security | left | `row.name` |
| `allocation` | Weight | right | `formatOptionalPercent(row.allocation, 2)` |
| `return` | Return | right | `formatPercent(...)` |
| `contribution` | Contribution | right | Color-coded |

**Data:** `backtestData.securityAttribution` | **Key:** `row.name`

#### Table 3: Sector Attribution (lines 265-297)

Identical column structure to Security Attribution but with "Sector" label.

**Data:** `backtestData.sectorAttribution` | **Key:** `row.name`

#### Table 4: Factor Attribution (lines 299-331)

Same as AttributionTab's Factor table (Factor, Beta, Return, Contribution).

**Data:** `backtestData.factorAttribution` | **Key:** `row.name`

#### Import Changes

- Add: `DataTable` and `DataTableColumn` to blocks import (or just from `"../../blocks"`)
- Keep: all existing imports

### NOT Migrated

| File | Table | Why |
|------|-------|-----|
| `holdings/HoldingsTable.tsx` | Main holdings table (7 cols, sorting, hover) | Very complex cell rendering (sector icons, sparklines, tooltips, alert overlays, badges). While DataTable API can technically handle it via render functions, the effort is high and risk of visual regression is significant. Already well-structured. Defer to separate batch. |
| `stock-lookup/PeerComparisonTab.tsx:111-152` | Peer comparison table | Dynamic column count (varies by peer count). Complex ranking badge cells with best/worst/ranked conditional styling. Low DRY benefit for a one-off dynamic table. |
| `scenario/StressTestsTab.tsx:161-185` | Position impacts table | Compact `text-xs` with `py-1` padding. Nested inside stress test result card. DataTable's `px-6 py-4` padding would be far too spacious. |
| `scenario/OptimizationsTab.tsx:143-167` | Optimized weights table | Compact `text-xs` with `py-2` padding. Same padding mismatch as stress tests. |
| `scenario/MonteCarloTab.tsx:262-287` | Percentile paths table | Compact `text-xs` with `py-2 pr-3`. Per-cell semantic colors (red P5, blue P50, green P95). DataTable padding too spacious. |
| `scenario/RecentRunsPanel.tsx:134-152` | Run comparison table | Small 3-column table nested inside collapsible panel. Conditional rendering. Low DRY benefit. |

---

## Execution Order

1. **Batch 3a first** (StatusCell) — 2 files, 6 cards, straightforward pattern replacement
2. **Batch 3b second** (DataTable) — 2 files, 8 tables, higher complexity but repetitive pattern

## Verification

1. `pnpm typecheck` — no type errors
2. `pnpm lint` — no lint errors
3. `pnpm build` — succeeds
4. Chrome verify: Stock Research OverviewTab (4 StatusCells), Factor Risk Model risk-attribution tab (2 StatusCells), Performance AttributionTab (4 tables), Strategy Builder PerformanceTab (4 tables)
