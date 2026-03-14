# Frontend Phase 5 Polish: Scenario + Strategy Batch

## Context
Continuing Phase 5 Visual Polish. Previous batches applied `glassTinted` Card variants, `hover-lift-subtle` micro-interactions, and `animate-stagger-fade-in` to Overview, Holdings, and Performance views. This batch applies the same patterns to the Scenario Analysis and Strategy Builder views.

Classic mode neutralization is handled globally by `[data-visual-style="classic"]` in `index.css` — no per-component gating needed.

## Changes

### 1. hover-lift-subtle on metric display cards
Add `hover-lift-subtle` to all inline metric `div` elements (the `p-3 bg-[color]-50 rounded-lg border` pattern) and small metric Cards.

**Files & locations:**
- `scenario/MonteCarloTab.tsx` — 4 result Cards (lines 143-166), 6 terminal distribution divs (lines 293-320)
- `scenario/OptimizationsTab.tsx` — 5 metric divs (lines 100-129)
- `scenario/ScenarioHeader.tsx` — 3 metric divs (lines 81-98)
- `scenario/PortfolioBuilderTab.tsx` — 4 impact metric divs (lines 224-242)
- `strategy/BuilderTab.tsx` — 4 strategy preview divs (lines 195-218)
- `strategy/ActiveStrategiesTab.tsx` — 4 metric divs per strategy (lines 39-58)
- `strategy/MarketplaceTab.tsx` — 3 featured strategy divs (lines 39-57)
- `strategy/PerformanceTab.tsx` — 8 backtest summary divs (lines 242-289)

### 2. glassTinted on plain white content Cards
Replace `bg-white border-neutral-200/60` with `variant="glassTinted"` on data-display Cards.

**Files & locations:**
- `scenario/OptimizationsTab.tsx` — empty state Card (line 51) + comparison table Card (line 133): `bg-white border-neutral-200/60` → `variant="glassTinted"`
- `scenario/HistoricalTab.tsx` — empty state Card (line 47): `border-neutral-200/60 bg-white` → `variant="glassTinted"`
- `scenario/StressTestsTab.tsx` — empty state Card (line 50): `border-neutral-200/60 bg-white` → `variant="glassTinted"`
- `strategy/PerformanceTab.tsx` — 4 attribution Cards (lines 342, 353, 364, 375): `bg-white border-neutral-200/60` → `variant="glassTinted"`
- `strategy/ActiveStrategiesTab.tsx` — strategy Cards (line 24): `bg-white border-neutral-200/60` → `variant="glassTinted"`
- `strategy/MarketplaceTab.tsx` — strategy cards (line 65): `bg-white border-neutral-200/60` → `variant="glassTinted"`
- `scenario/RecentRunsPanel.tsx` — panel Card (line 30): `border-neutral-200/60 bg-white` → `variant="glassTinted"`

### 3. hover-lift-subtle on interactive cards
Add `hover-lift-subtle` class to clickable/hoverable cards.

**Files & locations:**
- `strategy/MarketplaceTab.tsx` — strategy cards (line 65, already has `hover:shadow-md`)
- `scenario/HistoricalTab.tsx` — scenario cards (line 61)
- `scenario/StressTestsTab.tsx` — stress test cards (line 62)

### 4. Stagger animations on card lists
Wrap list items in `animate-stagger-fade-in` div with `animationDelay`.

**Files & locations:**
- `scenario/StressTestsTab.tsx` — stress test factor cards (wrap each card in stagger div)
- `strategy/MarketplaceTab.tsx` — strategy grid cards (wrap each card in stagger div)
- `scenario/HistoricalTab.tsx` — historical scenario cards (wrap each card in stagger div)

Pattern: Move `key` to wrapper div, add `className="animate-stagger-fade-in"` and `style={{ animationDelay: \`${index * 0.08}s\` }}`. Animation fill mode `both` ensures items start hidden during delay.

**Grid layout note:** For MarketplaceTab (parent is `grid grid-cols-2`), the stagger wrapper div must include `className="h-full"` so the inner Card stretches to equal height with siblings. HistoricalTab and StressTestsTab use `space-y-*` layouts and don't need this.

## Dropped
- No changes to ScenarioAnalysis.tsx or StrategyBuilder.tsx root containers (already have gradient bg + shadow-lg)
- No changes to PortfolioBuilderTab position rows (line 135) — these are editable form rows (weight sliders + remove buttons), not data-display cards. hover-lift-subtle is for "click to view detail" affordance, not form inputs.
- No chart styling changes
- No changes to ScenarioHeader configuration card (already has gradient background)
