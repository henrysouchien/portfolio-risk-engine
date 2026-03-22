# Overview Layout — 3 Hero Cards + Enhanced Strip

## Context
The Overview has 6 metric cards + a 4-metric performance strip. Four of the six cards are performance variants (YTD Return, Sharpe, Alpha, + Value). The strip shows different-but-related metrics (Annualized Return, Alpha, Sharpe, Volatility). Concentration sits orphaned in the cards. The result: too many numbers competing for attention, no clear hierarchy, and metrics split across two locations.

**New approach: 3 headlines + 5 supporting metrics.**

## Plan

### Change 1: Reduce metric cards from 6 to 3

**File:** `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts`

Keep only the 3 hero metrics:
1. **Total Portfolio Value** (index 0) — "how much am I worth"
2. **YTD Return** (index 1) — "am I making money"
3. **Risk Score** (index 2) — "how safe am I"

Remove from the array: Sharpe Ratio (index 3), Alpha Generation (index 4), Concentration (index 5). These move to the strip.

The grid (`grid-cols-2 md:grid-cols-3`) renders 3 items as one clean row on desktop, 2+1 on mobile.

### Change 2: Enhance Performance Strip to 5 metrics

**File:** `frontend/packages/ui/src/components/dashboard/cards/DashboardPerformanceStrip.tsx`

Add Concentration to the strip (requires `usePortfolioSummary()` as a second data source — already cached/shared). The strip becomes:

1. **Annualized Return** (existing — from `usePerformance()`)
2. **Alpha** (existing — from `usePerformance()`)
3. **Sharpe Ratio** (existing — from `usePerformance()`)
4. **Volatility** (existing — from `usePerformance()`)
5. **Concentration** (new — from `usePortfolioSummary()`)

Grid changes from `grid-cols-2 md:grid-cols-4` to `grid-cols-2 md:grid-cols-5` (or `grid-cols-3 md:grid-cols-5` for better mobile).

**Implementation:**
- Add `import { usePortfolioSummary } from '@risk/connectors'`
- Destructure: `const { data: summaryData } = usePortfolioSummary()`
- Add concentration to the `metrics` useMemo
- Add a 5th `StatPair` for Concentration with label "Concentration", value as score/100, color based on threshold (>=70 positive, >=40 warning, else negative)

### Change 3: Move strip position in layout

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Move `<DashboardPerformanceStrip />` from between the two grids to directly after `<PortfolioOverviewContainer />`. This puts the supporting metrics right below the hero cards, before holdings/alerts.

**New layout order:**
```tsx
<div className="space-organic animate-stagger-fade-in">
  {/* Section 1: Headlines + supporting metrics */}
  <div className="hover-lift-premium">
    <PortfolioOverviewContainer />
  </div>
  <DashboardPerformanceStrip />

  {/* Section 2: What needs attention + what I own */}
  <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
    <DashboardHoldingsCard />
    <DashboardAlertsPanel
      smartAlerts={alertData}
      alertsLoading={alertsLoading}
      alertsError={alertError}
    />
  </div>

  {/* Section 3: Details */}
  <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
    <div className="hover-lift-premium animate-magnetic-hover">
      <AssetAllocationContainer />
    </div>
    <DashboardIncomeCard />
  </div>
</div>
```

Note: PortfolioOverviewContainer internally renders metric cards → performance trend chart → market intelligence → AI recommendations. The strip slots right after that container, before Holdings/Alerts.

## Files Modified
1. `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` — remove 3 metrics from array (Sharpe, Alpha, Concentration)
2. `frontend/packages/ui/src/components/dashboard/cards/DashboardPerformanceStrip.tsx` — add Concentration metric + `usePortfolioSummary()`, update grid to 5-col
3. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` — move strip position (after PortfolioOverviewContainer, before Holdings grid)

## Verification
1. `cd frontend && npx tsc --noEmit` — no type errors
2. Visual: 3 hero cards in one row (Value | YTD Return | Risk Score)
3. Strip below with 5 metrics (Annualized Return | Alpha | Sharpe | Volatility | Concentration)
4. Strip is clickable → navigates to Performance view
5. Holdings/Alerts grid directly below strip
6. Mobile: cards stack 2+1, strip stacks 2-col
7. No duplicate metrics anywhere on the page
