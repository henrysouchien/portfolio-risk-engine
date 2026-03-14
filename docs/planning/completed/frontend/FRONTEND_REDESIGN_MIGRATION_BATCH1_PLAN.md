# Frontend Redesign — Batch 1: TabContentWrapper Migration

## Goal

Replace inline `TabsContent + ScrollArea + space-y-*` boilerplate with the `TabContentWrapper` block component (built in Phase 1c, `48fc07ca`). No visual changes — same CSS classes applied through the component abstraction.

## TabContentWrapper API

```tsx
<TabContentWrapper value="tab-id" height="h-[450px]" spacing="md">
  {children}
</TabContentWrapper>
```

| Prop | Default | Maps to |
|------|---------|---------|
| `value` | required | `TabsContent value=` |
| `children` | required | Content inside the spacing div |
| `height` | `"h-[450px]"` | `ScrollArea className=` |
| `spacing` | `"md"` | `sm` → `space-y-3`, `md` → `space-y-4`, `lg` → `space-y-6` |
| `className` | — | Extra classes on outer `TabsContent` |

The component outputs: `TabsContent(flex-1 min-h-0 overflow-hidden) > ScrollArea(height) > div(spacing)`.

---

## Migration Sites (13 unique sites across 13 files)

### Group A: Stock Lookup tabs (6 sites) — `h-[450px]` + `space-y-4` (exact defaults)

| # | File | value= | height | spacing | Props needed |
|---|------|--------|--------|---------|-------------|
| 1 | `stock-lookup/OverviewTab.tsx:17-112` | `overview` | `h-[450px]` | `space-y-4` | `value="overview"` |
| 2 | `stock-lookup/TechnicalsTab.tsx:17-128` | `technicals` | `h-[450px]` | `space-y-4` | `value="technicals"` |
| 3 | `stock-lookup/FundamentalsTab.tsx:78-207` | `fundamentals` | `h-[450px]` | `space-y-4` | `value="fundamentals"` |
| 4 | `stock-lookup/PortfolioFitTab.tsx:38-187` | `portfolio-fit` | `h-[450px]` | `space-y-4` | `value="portfolio-fit"` |
| 5 | `stock-lookup/PeerComparisonTab.tsx:77-168` | `peer-comparison` | `h-[450px]` | `space-y-4` | `value="peer-comparison"` |
| 6 | `StockLookup.tsx:302-343` | `risk-factors` | `h-[450px]` | `space-y-4` | `value="risk-factors"` |

All 6 use `className="flex-1 overflow-hidden"` on TabsContent (wrapper uses `flex-1 min-h-0 overflow-hidden` — adds `min-h-0`, safe). All match exact defaults so no extra props needed.

### Group B: Scenario tabs (4 sites) — `h-full` + `space-y-4` or `space-y-6`

| # | File | value= | height | spacing | Props needed |
|---|------|--------|--------|---------|-------------|
| 7 | `scenario/HistoricalTab.tsx:28-140` | `historical` | `h-full` | `space-y-4` | `height="h-full"` |
| 8 | `scenario/StressTestsTab.tsx:49-257` | `stress-tests` | `h-full` | `space-y-4` | `height="h-full"` |
| 9 | `scenario/OptimizationsTab.tsx:50-179` | `optimizations` | `h-full` | `space-y-6` | `height="h-full" spacing="lg"` |
| 10 | `scenario/MonteCarloTab.tsx:61-334` | `monte-carlo` | `h-full` | `space-y-6` | `height="h-full" spacing="lg"` |

All 4 use `className="flex-1 overflow-hidden min-h-0"` on TabsContent (wrapper produces same classes — `min-h-0` already included).

### Group C: Strategy tabs (2 sites) — `h-full` + `space-y-6`

| # | File | value= | height | spacing | Props needed |
|---|------|--------|--------|---------|-------------|
| 11 | `strategy/MarketplaceTab.tsx:27-130` | `marketplace` | `h-full` | `space-y-6` | `height="h-full" spacing="lg"` |
| 12 | `strategy/ActiveStrategiesTab.tsx:16-73` | `active` | `h-full` | `space-y-6` | `height="h-full" spacing="lg"` |

Same `flex-1 overflow-hidden min-h-0` pattern.

### Group D: FactorRiskModel (1 site) — `h-full` + `space-y-4`

| # | File | value= | height | spacing | Props needed |
|---|------|--------|--------|---------|-------------|
| 13 | `FactorRiskModel.tsx:349-396` | `fama-french` | `h-full` | `space-y-4` | `height="h-full"` |

Only the `fama-french` tab matches. The other two tabs don't fit: `risk-attribution` has ScrollArea nested inside a `div.space-y-4` (not wrapping the whole tab), `factor-performance` has no ScrollArea at all.

Note: `FactorRiskModel.tsx` uses `className="flex-1 overflow-hidden"` (no `min-h-0`), same as Group A. The wrapper adds `min-h-0` — safe, no visual change.

**Import note:** `FactorRiskModel.tsx` still uses `ScrollArea` in the `risk-attribution` tab (line 426) and `TabsContent` for the other two tabs — do NOT remove those imports.

---

## NOT Migrated (13 tab sites across 7 files)

### No ScrollArea — bare TabsContent wrapping child components
- `PerformanceView.tsx` (4 tabs) — `TabsContent` directly renders `<AttributionTab>` etc., no ScrollArea
- `RiskAnalysis.tsx` (3 tabs) — `TabsContent className="space-y-4 mt-6"` directly on TabsContent, no ScrollArea

### Non-matching layout
- `scenario/PortfolioBuilderTab.tsx` — TabsContent+ScrollArea wraps a grid layout, not `space-y-*` children
- `stock-lookup/PriceChartTab.tsx` — uses `div.overflow-auto`, not ScrollArea
- `strategy/PerformanceTab.tsx` — conditional branches, one without ScrollArea, one with extra `pr-2`
- `strategy/BuilderTab.tsx` — no ScrollArea, grid layout

### Partial match (ScrollArea nested inside, not at wrapper level)
- `FactorRiskModel.tsx` risk-attribution tab — ScrollArea at line 426 nested inside a `div.space-y-4`, not wrapping the whole tab
- `FactorRiskModel.tsx` factor-performance tab — no ScrollArea at all

---

## Transform Pattern

**Before:**
```tsx
import { ScrollArea } from "../../ui/scroll-area"
import { TabsContent } from "../../ui/tabs"

<TabsContent value="overview" className="flex-1 overflow-hidden">
  <ScrollArea className="h-[450px]">
    <div className="space-y-4">
      {/* content */}
    </div>
  </ScrollArea>
</TabsContent>
```

**After:**
```tsx
import { TabContentWrapper } from "../../blocks"

<TabContentWrapper value="overview">
  {/* content */}
</TabContentWrapper>
```

For non-default props:
```tsx
<TabContentWrapper value="historical" height="h-full">
<TabContentWrapper value="monte-carlo" height="h-full" spacing="lg">
```

### Import cleanup
- Remove `ScrollArea` import if TabContentWrapper is the only consumer (check for other ScrollArea usage in the file first)
- Remove `TabsContent` import if all TabsContent in the file are migrated (check for other TabsContent usage)
- Add `TabContentWrapper` import from `"../../blocks"` (or appropriate relative path)

---

## Verification

1. `pnpm typecheck` — no type errors
2. `pnpm lint` — no lint errors
3. `pnpm build` — succeeds
4. Visual inspection — stock-lookup tabs, scenario tabs, strategy tabs, factor model tab all render identically
