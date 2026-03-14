# Frontend Phase 5 Polish: StockLookup + Risk Analysis Batch

## Context
Continuing Phase 5 Visual Polish. Previous batches applied `glassTinted` Card variants, `hover-lift-subtle` micro-interactions, and `animate-stagger-fade-in` to Overview, Holdings, Performance, Scenario, and Strategy views. This batch applies the same patterns to StockLookup and RiskAnalysis.

Classic mode neutralization is handled globally by `[data-visual-style="classic"]` in `index.css`.

All files under `frontend/packages/ui/src/components/portfolio/`.

## Changes

### 1. glassTinted on plain white content Cards
Replace `bg-white/80 border-neutral-200/60` or `bg-white border-neutral-200/60` with `variant="glassTinted"`.

**StockLookup tabs:**
- `stock-lookup/OverviewTab.tsx` — "Additional Risk Metrics" Card (line 55): `bg-white/80 border-neutral-200/60` → `variant="glassTinted"`
- `stock-lookup/TechnicalsTab.tsx` — "Support & Resistance" Card (line 50): `bg-white/80 border-neutral-200/60` → `variant="glassTinted"`
- `stock-lookup/FundamentalsTab.tsx` — "Valuation Metrics" Card (line 131): `bg-white/80 border-neutral-200/60` → `variant="glassTinted"`
- `stock-lookup/PortfolioFitTab.tsx` — what-if result Card (line 81): `border-neutral-200/60 bg-white/90` → `variant="glassTinted"`
- `stock-lookup/PortfolioFitTab.tsx` — risk checks Card (line 109): `border-neutral-200/60 bg-white/90` → `variant="glassTinted"`
- `stock-lookup/PeerComparisonTab.tsx` — loading Card (line 88): `border-neutral-200/60` → `variant="glassTinted"`
- `stock-lookup/PeerComparisonTab.tsx` — empty state Card (line 103): `border-neutral-200/60` → `variant="glassTinted"`
- `stock-lookup/PeerComparisonTab.tsx` — peer table Card (line 109): `border-neutral-200/60` → `variant="glassTinted"` with `p-0 overflow-hidden`
- `stock-lookup/PortfolioFitTab.tsx` — empty state Card (line 154): `border-neutral-200/60` → `variant="glassTinted"`

**StockLookup root:**
- `StockLookup.tsx` — risk factor cards inline (line 308): `bg-white/80 border-neutral-200/60` → `variant="glassTinted"`

**RiskAnalysis:**
- `RiskAnalysis.tsx` — main Card (line 135): `border-neutral-200/60 shadow-sm` → `variant="glassTinted"`

### 2. hover-lift-subtle on metric cards and interactive cards

**StockLookup tabs:**
- `stock-lookup/OverviewTab.tsx` — 4 StatusCell tiles (lines 21, 29, 37, 45): add `className="hover-lift-subtle"` (StatusCell accepts className and merges via `cn()`)
- `stock-lookup/FundamentalsTab.tsx` — 4 gradient metric Cards (lines 83, 98, 107, 122): add `hover-lift-subtle`
- `stock-lookup/TechnicalsTab.tsx` — RSI Card (line 22) and MACD Card (line 33): add `hover-lift-subtle`
- `stock-lookup/TechnicalsTab.tsx` — Bollinger Bands Card (line 104): add `hover-lift-subtle`

**StockLookup root:**
- `StockLookup.tsx` — risk factor cards (line 308): add `hover-lift-subtle` (already has `hover:shadow-md`)

**RiskAnalysis:**
- `RiskAnalysis.tsx` — risk factor Cards (line 181): add `hover-lift-subtle` (already has `hover:shadow-md`)
- `RiskAnalysis.tsx` — stress test Cards (line 243): add `hover-lift-subtle`
- `RiskAnalysis.tsx` — hedging strategy Cards (line 286): add `hover-lift-subtle` (already has `hover:shadow-sm`)

### 3. Stagger animations on card lists

**RiskAnalysis:**
- `RiskAnalysis.tsx` — risk factor cards list (line 178): wrap each card in stagger div
- `RiskAnalysis.tsx` — stress test cards list (line 242): wrap each card in stagger div
- `RiskAnalysis.tsx` — hedging strategy cards list (line 285): wrap each card in stagger div

**StockLookup:**
- `StockLookup.tsx` — risk factor cards (line 307): wrap each card in stagger div

Pattern: `<div key={...} className="animate-stagger-fade-in" style={{ animationDelay: \`${index * 0.08}s\` }}>`. Move existing `key` to wrapper div.

**Layout safety:** All stagger targets have wrapper-tolerant parents: RiskAnalysis risk factors (space-y-4 in TabsContent), stress tests (grid gap-4), hedging (grid gap-4), StockLookup risk factors (TabContentWrapper space-y). No stagger wrappers around table rows or search result buttons.

## Dropped
- No changes to StockLookup.tsx root container Card (line 108, already has gradient bg + shadow-lg + hover:shadow-xl)
- OverviewTab StatusCell tiles: hover-lift-subtle added via `className` prop at usage site (StatusCell merges className via `cn()` at status-cell.tsx:111), no component definition changes needed
- No changes to PriceChartTab (chart-only, uses `bg-card` theme token)
- No changes to stock header section in StockLookup.tsx (already has gradient background)
- No changes to PortfolioFitTab position sizing Card (already has gradient background)
- No changes to PeerComparisonTab header Card (already has gradient background)
- No changes to search result buttons in StockLookup.tsx (stagger wrappers would break `last:border-b-0`)
- No changes to peer comparison table rows (stagger wrappers invalid inside `<tbody>`)
- No chart styling changes
