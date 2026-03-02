# Plan: Refactor Portfolio Views to Use Block Components

## Context

Phase 1 block components are built and committed (`b7988154`): PercentageBadge, GradientProgress, SparklineChart, SectionHeader, MetricCard. They're available via `import { ... } from '@risk/ui'` but no views use them yet. This plan refactors portfolio views one-by-one to replace inline patterns with block components, catching regressions at each step.

## Prerequisite: Add `children` Slot to MetricCard

Before refactoring complex views, MetricCard needs to actually **render** its `children` (already inherited via `React.HTMLAttributes` but not rendered in the JSX). Views pass in their view-specific content (AI insights, drill-down details, etc.) while the block handles the common structure.

**File**: `frontend/packages/ui/src/components/blocks/metric-card.tsx`
**Change**: Destructure `children` from props, render after the value/change section inside the `z-10` content div (only when `!isLoading`).

## Refactoring Order (view-by-view, easiest first)

### Wave 1: Easy Wins (2 views) — ✅ COMPLETE (`9506643d`)

Detailed plan: `docs/planning/FRONTEND_BLOCK_REFACTOR_WAVE1.md`

#### 1. AssetAllocation.tsx — ✅ Done
- **PercentageBadge**: Replaced TrendingUp/TrendingDown + colored span → `<PercentageBadge value={parseFloat(change)} showIcon variant="inline" size="xs" />`
- **GradientProgress**: Replaced `<Progress>` → `<GradientProgress>` with `colorSchemeFromBg()` helper mapping Tailwind `bg-*` classes to colorScheme keys
- Removed: `Progress`, `TrendingUp`, `TrendingDown` imports

#### 2. FactorRiskModel.tsx — ✅ Done
- **GradientProgress** (factor contribution): `colorScheme="purple"` — matches Factor Exposure tab theming
- **GradientProgress** (risk attribution): `colorScheme="indigo"` — visually distinct from factor tab
- Removed: `Progress` import

**Deferred from Wave 1**: PerformanceChart.tsx — performance badges are pre-formatted strings, poor PercentageBadge fit. No Progress bars. Skipped.

**Wave 1 gate**: ✅ `pnpm typecheck && pnpm build` passed. Visually verified in Chrome (gradient bars, percentage badges rendering correctly with real data).

### Wave 2: Medium (3 views) — ✅ COMPLETE (`93e5ed9e`)

Detailed plan: `docs/planning/FRONTEND_BLOCK_REFACTOR_WAVE2.md`

#### 4. RiskMetrics.tsx — ✅ Done
- **GradientProgress**: Replaced Progress+gradient overlay hack with `<GradientProgress>` using `statusToColorScheme()` helper (high→red, medium→amber, low→emerald). NOT autoColor — risk semantics are inverted.
- Removed: `Progress` import, `progressColor` from `getStatusConfig()`
- **Kept inline**: Header (pulse indicator, hover rotation — too customized for SectionHeader), status badge (text not numeric — not PercentageBadge)

#### 5. StockLookup.tsx — ✅ Done
- **SectionHeader**: Replaced manual header (icon+title+subtitle+search input) with `<SectionHeader icon={Search} colorScheme="blue" actions={...} />`
- **GradientProgress**: Replaced 8 Progress bars across 4 sections: Risk Factors (blue), RSI (blue), Valuation (indigo), Financial Health (neutral)
- Removed: `Progress`, `CardTitle` imports
- **Kept inline**: Metric cards (structural layout mismatch with MetricCard block — icon position, colored text)

#### 6. StrategyBuilder.tsx — ✅ Done
- **SectionHeader**: Replaced manual header (icon+title+subtitle+badge+button) with `<SectionHeader icon={Target} colorScheme="emerald" actions={...} />`
- Removed: `CardTitle` import
- **Kept inline**: Strategy preview cards and performance metric grids (MetricCard poor structural fit)

**Wave 2 gate**: ✅ `pnpm typecheck && pnpm build` passed. Visually verified in Chrome (GradientProgress risk colors, SectionHeader icons/actions all rendering correctly with real data).

### Wave 3: Medium-Hard (4 views) — ✅ COMPLETE (`750dea25`)

Detailed plan: `docs/planning/FRONTEND_BLOCK_REFACTOR_WAVE3.md`

MetricCard `children` slot was NOT needed — HoldingsView cards mapped cleanly to existing props.

#### 7. RiskAnalysis.tsx — ✅ Done
- **GradientProgress**: Replaced risk score Progress bar (`colorScheme="red"`)
- Removed: `Progress` import
- **Kept inline**: Header (plain CardTitle, no gradient icon), expandable risk factor cards

#### 8. ScenarioAnalysis.tsx — ✅ Done
- **SectionHeader**: Replaced header (red AlertTriangle + badge + Run Analysis button in actions)
- **GradientProgress**: Replaced 7 Progress bars — analysis overlay, stress test impact, 5 Monte Carlo percentile bars (red/amber/emerald color coding)
- Removed: `Progress`, `CardTitle` imports

#### 9. HoldingsView.tsx — ✅ Done
- **MetricCard**: Replaced 4 summary cards (Total Holdings/emerald, Total Return/blue, Avg Risk Score/amber, Active Alerts/red)
- Non-percentage changes ("Medium Risk", "High Priority") correctly use MetricCard's plain text fallback path
- **Kept inline**: Holdings table header (no gradient icon), table rows, search/filter controls

#### 10. PerformanceView.tsx — ✅ Done
- **SectionHeader**: Replaced 5 sub-section headers (Sector Attribution/blue, Factor Attribution/indigo, Benchmarks/purple, Risk & Drawdown/red with "Predictive" badge, Monthly Breakdown/blue with "Market Context" badge) — all `size="sm"`
- **GradientProgress**: Replaced sector attribution Progress bar (`colorScheme="blue"`)
- Removed: `Progress` import. Kept `CardTitle` (still used in Contributors/Detractors inline headers)
- **Kept inline**: Main header (too customized — AI indicator, view toggles, export menu), Contributors/Detractors headers (w-6 icons smaller than SectionHeader sm), benchmark boxes, drawdown/volatility detail boxes

**Wave 3 gate**: ✅ `pnpm typecheck && pnpm build` passed. Visually verified in Chrome (MetricCards, SectionHeaders, GradientProgress all rendering correctly with real data).

### Wave 4: Skipped — No Clean Block Fits

#### 11. PortfolioOverview.tsx (2,480 lines) — N/A

Investigated but no block adoptions warranted:
- **No Progress bars** — uses custom SVG sparklines, not scalar progress bars
- **Content headers** (Market Intelligence, AI Recommendations) use light tinted icon backgrounds (`bg-blue-100 text-blue-600`) not gradients — SectionHeader would change visual style from subtle to bold
- **Settings panel headers** are plain inline icons (`text-neutral-600`) — SectionHeader would add unwanted gradient visual weight
- **Smart Alerts header** uses `w-6 h-6` icon — smaller than SectionHeader's smallest size
- **Metric cards** are view-mode-dependent (compact/detailed/professional/institutional) with AI insights, institutional correlations, custom sparkline overlays — far exceeds MetricCard's prop-based API
- **Custom sparklines** use sophisticated SVG rendering with institutional-mode enhancements — more complex than SparklineChart block

This view is intentionally a self-contained "super component" where the patterns are deliberate, not boilerplate. Forcing blocks would either change visual style or make the code harder to read.

### Skipped (no extractable patterns)
- ConnectedRiskAnalysis.tsx (193 lines) — template only
- PortfolioHoldings.tsx (173 lines) — legacy component

## Refactoring Complete

Waves 1-3 adopted block components across 9 views. Wave 4 investigated and correctly skipped. Total: **5 blocks adopted** (SectionHeader, GradientProgress, MetricCard, PercentageBadge, colorSchemeFromBg helper) across **9 files**, replacing ~40 inline patterns with consistent block usage.

## Implementation Rules

1. **One view at a time** — finish and verify one view before starting the next
2. **No behavior changes** — refactoring only, rendered output must be identical
3. **Block handles common structure, view owns specifics** — AI insights, animated values, view-mode logic stay in the view and get passed as `children` or composed around the block
4. **Keep inline code if block doesn't fit** — don't force a block replacement if it makes the code harder to read
5. **Each wave gets its own commit** — so regressions are bisectable

## Files Modified

- `frontend/packages/ui/src/components/blocks/metric-card.tsx` — render `children` slot in card content
- `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx`
- `frontend/packages/ui/src/components/portfolio/PerformanceChart.tsx`
- `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx`
- `frontend/packages/ui/src/components/portfolio/RiskMetrics.tsx`
- `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`
- `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`
- `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`
- `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`
- `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`
- `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

## Verification (per wave)

1. `cd frontend && pnpm typecheck` — no TypeScript errors
2. `cd frontend && pnpm build` — Vite build succeeds
3. Spot-check: verify block imports are used, no dead inline code left behind
