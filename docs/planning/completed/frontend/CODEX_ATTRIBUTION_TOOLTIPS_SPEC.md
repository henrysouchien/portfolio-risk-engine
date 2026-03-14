# Codex Spec: Attribution Column Header Tooltips (T2 #26)

**Goal:** Add tooltip explanations to ambiguous column headers in the attribution tables.

**Pattern:** Radix Tooltip already exists. Example usage in `RiskAnalysisTab.tsx` lines 31-44.

**Constraint:** `TooltipProvider` is already rendered at `PerformanceView.tsx:113` wrapping all tabs including AttributionTab. Do NOT add another provider.

---

## Step 1: Extend DataTableColumn interface

**File:** `frontend/packages/ui/src/components/blocks/data-table.tsx`

The current interface (lines 23-30):
```typescript
export interface DataTableColumn<T, K extends string = string> {
  key: K
  label: string
  width?: string
  align?: DataTableAlign
  sortable?: boolean
  render: (row: T, index: number) => React.ReactNode
}
```

Add an optional `tooltip` field:
```typescript
export interface DataTableColumn<T, K extends string = string> {
  key: K
  label: string
  tooltip?: string          // <-- add this
  width?: string
  align?: DataTableAlign
  sortable?: boolean
  render: (row: T, index: number) => React.ReactNode
}
```

### Header rendering change

The header currently builds a `headerLabel` fragment (lines 80-85) and branches between a sortable `<Button>` path (line 94) and a non-sortable `<div>` path (line 107). Both paths render `{headerLabel}` as their children.

**Change only the `headerLabel` construction** (lines 80-85) so both paths automatically get the tooltip. Add the tooltip import at the top of the file alongside the existing `Button` import:

```tsx
import { Info } from "lucide-react"

import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip"
```

Then replace the `headerLabel` block:

**Before (lines 80-85):**
```tsx
const headerLabel = (
  <>
    <span>{column.label}</span>
    {isSorted ? <ArrowUpDown aria-hidden="true" className="h-3 w-3" /> : null}
  </>
)
```

**After:**
```tsx
const headerLabel = (
  <>
    {column.tooltip ? (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex cursor-help items-center gap-1">
            {column.label}
            <Info aria-hidden="true" className="h-3 w-3 text-muted-foreground/60" />
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <span className="max-w-xs text-sm">{column.tooltip}</span>
        </TooltipContent>
      </Tooltip>
    ) : (
      <span>{column.label}</span>
    )}
    {isSorted ? <ArrowUpDown aria-hidden="true" className="h-3 w-3" /> : null}
  </>
)
```

This preserves both the sortable `<Button>` and non-sortable `<div>` code paths unchanged -- only the shared `headerLabel` content is modified. No `TooltipProvider` is added here; the caller is responsible for providing one (PerformanceView already does).

## Step 2: Add tooltips to Sector Attribution columns

**File:** `frontend/packages/ui/src/components/portfolio/performance/AttributionTab.tsx`

Update `sectorColumns` (lines 12-45). All four columns have `sortable: false`. Add `tooltip` to the ambiguous ones:

```typescript
const sectorColumns: DataTableColumn<PerformanceAttributionSector>[] = [
  {
    key: "name",
    label: "Sector",
    align: "left",
    sortable: false,
    tooltip: "GICS sector classification of holdings",
    render: (row) => <span className="font-medium text-neutral-900">{row.name}</span>,
  },
  {
    key: "allocation",
    label: "Weight",
    align: "right",
    sortable: false,
    tooltip: "Portfolio weight allocated to this sector at period end",
    render: (row) => formatOptionalPercent(row.allocation, 2),
  },
  {
    key: "return",
    label: "Return",
    align: "right",
    sortable: false,
    tooltip: "Total return of this sector's holdings during the period",
    render: (row) => formatPercent(row.return, { decimals: 2, sign: true }),
  },
  {
    key: "contribution",
    label: "Contribution",
    align: "right",
    sortable: false,
    tooltip: "Impact on total portfolio return (weight x sector return)",
    render: (row) => (
      <span className={`font-medium ${getChangeColor(row.contribution, true)}`}>
        {formatPercent(row.contribution, { decimals: 2, sign: true })}
      </span>
    ),
  },
]
```

## Step 3: Add tooltips to Factor Attribution columns

Same file, `factorColumns` (lines 47-80):

```typescript
const factorColumns: DataTableColumn<PerformanceAttributionFactor>[] = [
  {
    key: "name",
    label: "Factor",
    align: "left",
    sortable: false,
    tooltip: "Risk factor from the portfolio's factor model",
    render: (row) => <span className="font-medium text-neutral-900">{row.name}</span>,
  },
  {
    key: "beta",
    label: "Beta",
    align: "right",
    sortable: false,
    tooltip: "Portfolio sensitivity to this factor (near 0 = neutral exposure)",
    render: (row) => formatOptionalNumber(row.beta, 3),
  },
  {
    key: "return",
    label: "Return",
    align: "right",
    sortable: false,
    tooltip: "Return attributable to this factor during the period",
    render: (row) => formatPercent(row.return, { decimals: 2, sign: true }),
  },
  {
    key: "contribution",
    label: "Contribution",
    align: "right",
    sortable: false,
    tooltip: "Impact on total portfolio return from this factor exposure",
    render: (row) => (
      <span className={`font-medium ${getChangeColor(row.contribution, true)}`}>
        {formatPercent(row.contribution, { decimals: 2, sign: true })}
      </span>
    ),
  },
]
```

## Step 4: Add tooltips to Stock Attribution columns

Same file, `stockColumns` (lines 82-115). Column key is `symbol` (not `ticker`):

```typescript
const stockColumns: DataTableColumn<PerformanceAttributionStock>[] = [
  {
    key: "symbol",
    label: "Ticker",
    align: "left",
    sortable: false,
    render: (row) => <span className="font-medium text-neutral-900">{row.symbol}</span>,
    // No tooltip — self-explanatory
  },
  {
    key: "weight",
    label: "Weight",
    align: "right",
    sortable: false,
    tooltip: "Average portfolio weight of this position during the period",
    render: (row) => formatOptionalPercent(row.weight, 2),
  },
  {
    key: "return",
    label: "Return",
    align: "right",
    sortable: false,
    tooltip: "Total return of this position during the period",
    render: (row) => formatPercent(row.return, { decimals: 2, sign: true }),
  },
  {
    key: "contribution",
    label: "Contribution",
    align: "right",
    sortable: false,
    tooltip: "Position's contribution to total portfolio return (weight x return)",
    render: (row) => (
      <span className={`font-medium ${getChangeColor(row.contribution, true)}`}>
        {formatPercent(row.contribution, { decimals: 2, sign: true })}
      </span>
    ),
  },
]
```

## Verification

```bash
cd frontend && npx tsc --noEmit
```

Visually confirm: hover a "Weight" or "Contribution" header in any attribution table and verify the tooltip renders with the expected copy.

## Summary

| Correction from v1 | What changed |
|---|---|
| Interface shape | `DataTableColumn<T, K extends string = string>` with `width?: string`, `render: (row: T, index: number)` (not optional, takes index) |
| Import path | Relative `../ui/tooltip` (not `@risk/ui/components/ui/tooltip`) |
| Column key | `symbol` (not `ticker`) in stock attribution |
| Beta tooltip copy | "near 0 = neutral exposure" (not "1.0 = market-neutral") |
| Header branch | Tooltip injected into shared `headerLabel` fragment, preserving both sortable `<Button>` and non-sortable `<div>` paths |
| TooltipProvider | Already at `PerformanceView.tsx:113` -- no extra provider needed |

2 files changed: `data-table.tsx` (interface + headerLabel) and `AttributionTab.tsx` (11 tooltip strings across 3 tables). Reusable pattern -- any DataTable column can now have tooltips.
