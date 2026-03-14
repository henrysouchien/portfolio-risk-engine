# Frontend Redesign — Phase 2: PortfolioOverview Decomposition

**Date:** 2026-03-05
**Status:** DONE (`810c6140`)
**Source:** `FRONTEND_REDESIGN_PLAN.md` Phase 2

---

## Context

`PortfolioOverview.tsx` is 2,076 lines — the largest monolith in the frontend. It contains types, state, metrics building, color helpers, an advanced sparkline renderer, and 6 major JSX sections all in one file. Decomposing it into focused sub-components makes each piece testable, reviewable, and maintainable.

The container (`PortfolioOverviewContainer.tsx`, 246 lines) is already separated and passes: `data`, `smartAlerts`, `marketEvents`, `aiRecommendations`, `metricInsights`, `onRefresh`, `loading`, `className`. Container is NOT modified.

**Goal:** 2,076-line monolith → ~180-line orchestrator + 10 focused files in `components/portfolio/overview/`.

---

## New directory: `components/portfolio/overview/`

### 1. `types.ts` (~130 lines)
**Replaces:** lines 206-327
- `ViewMode` type alias (`"compact" | "detailed" | "professional" | "institutional"`)
- `MetricData`, `MarketEvent`, `AIRecommendation`, `SmartAlert` interfaces
- `PortfolioOverviewProps` interface
- Color system types

### 2. `helpers.ts` (~80 lines)
**Replaces:** lines 403-408 (`getChangeType`, inside metrics useMemo) + lines 587-652 (color/visual helpers)
- `getChangeType(value)` — maps number → "positive"|"negative"|"warning"|"neutral" (extracted from metrics useMemo at line 403)
- `getMetricColorSystem(changeType, viewMode)` — bg/border/text/icon/accent/glow classes
- `getChangeIcon(changeType)` — returns Lucide icon component
- `getPriorityGlow(priority)` — shadow class for priority levels

### 3. `useOverviewMetrics.ts` (~140 lines)
**Replaces:** lines 398-550
- Hook: `useOverviewMetrics(data, metricInsights)` → `MetricData[]`
- Builds 6 metric objects (Total Value, Daily P&L, Risk Score, Sharpe, Alpha, Concentration)
- Contains the `useMemo` and all metric construction logic

### 4. `InstitutionalSparkline.tsx` (~120 lines)
**Replaces:** lines 658-804
- SVG sparkline with animated gradients, volatility filters, live streaming effects, correlation indicators
- Props: `{ trend, changeType, isActive, volatility, isLive?, correlations?, viewMode }`
- Only used by OverviewMetricCard, but 146 lines warrants its own file

### 5. `OverviewMetricCard.tsx` (~300 lines)
**Replaces:** lines 806-826 (`formatValue` + `getAlertBadge`) + lines 961-1375 (the per-metric card inside the grid `.map()`)
- `formatValue(value, rawValue, precision)` — currency/number formatting for display (line 806)
- `getAlertBadge(alertLevel)` — renders urgent/caution/watch Badge (line 815)
- Single metric card with all 4 view-mode conditionals
- Hover/focus effects, glow, scale animations
- Inline AI insight panel (expandable on hover)
- Institutional correlations/technical signals
- Tooltip with metric details
- Footer with trend dots
- Props: `{ metric, index, viewMode, isHovered, isFocused, showAIInsights, onMouseEnter, onMouseLeave, onClick }`

**Why not reuse existing MetricCard block?** The overview cards have substantial additional behavior (view-mode sizing, hover AI panel, institutional badges, custom tooltips) that doesn't fit the simpler MetricCard. MetricCard stays for HoldingsView summary cards etc.

### 6. `ViewControlsHeader.tsx` (~80 lines)
**Replaces:** lines 840-916
- View mode toggle buttons (Compact/Detailed/Pro/Institutional) + AI Insights toggle + Refresh + Settings gear
- Props: `{ viewMode, onViewModeChange, showAIInsights, onToggleAIInsights, onRefresh, onOpenSettings, loading }`

### 7. `SmartAlertsPanel.tsx` (~45 lines)
**Replaces:** lines 922-949
- Severity-coded alert items (up to 3 shown)
- Props: `{ alerts }`

### 8. `MarketIntelligenceBanner.tsx` (~70 lines)
**Replaces:** lines 1382-1442
- Market events with impact badges and relevance scores
- Props: `{ events }`

### 9. `AIRecommendationsPanel.tsx` (~90 lines)
**Replaces:** lines 1448-1526
- Recommendation cards with priority, risk level, impact, confidence
- Props: `{ recommendations, visible }`

### 10. `SettingsPanel.tsx` (~290 lines)
**Replaces:** lines 358-393 (5 settings state objects) + lines 1533-2071 (Sheet + all sections + footer)
- Self-contained: owns all 5 settings state objects (display, refresh, alerts, charts, export)
- Note: lines 344-357 are orchestrator state (`hoveredMetric`, `viewMode`, `showAIInsights`, `focusedMetric`, `settingsPanelOpen`) and stay in the orchestrator
- Sheet wrapper with header, 5 sections with Switch/Input/Select controls, footer (reset/save)
- Props: `{ open, onOpenChange }`

### 11. `index.ts` (~10 lines)
- Barrel re-exports sub-components, types, helpers, and hook for internal use within `overview/`
- Does NOT re-export PortfolioOverview (orchestrator lives outside at `components/portfolio/PortfolioOverview.tsx`)
- Example: `export { OverviewMetricCard } from './OverviewMetricCard'`, `export type { ViewMode, MetricData } from './types'`, etc.

---

## Orchestrator: `PortfolioOverview.tsx` (~180 lines)

After extraction:

**State** (~10 lines): `hoveredMetric`, `viewMode`, `showAIInsights`, `focusedMetric`, `settingsPanelOpen`

**Hook** (~2 lines): `const metrics = useOverviewMetrics(data, metricInsights)`

**Handlers** (~15 lines): `handleDataRefresh`, `handleMetricFocus`, `handleViewModeChange`

**JSX** (~130 lines):
```tsx
<TooltipProvider>
  <div className="space-y-8">
    <ViewControlsHeader ... />
    {alerts.length > 0 && <SmartAlertsPanel alerts={alerts} />}
    <div className={gridClass}>
      {metrics.map((metric, i) => (
        <OverviewMetricCard key={i} metric={metric} viewMode={viewMode} ... />
      ))}
    </div>
    {events.length > 0 && <MarketIntelligenceBanner events={events} />}
    <AIRecommendationsPanel recommendations={recs} visible={showAIInsights} />
    <SettingsPanel open={settingsPanelOpen} onOpenChange={setSettingsPanelOpen} />
  </div>
</TooltipProvider>
```

---

## Import path strategy

The container imports from `../../../portfolio/PortfolioOverview`. To avoid breaking the container:

**Keep `PortfolioOverview.tsx` at its current path** (`components/portfolio/PortfolioOverview.tsx`). The file becomes the ~180-line orchestrator that imports sub-components from `./overview/`. The container import path is unchanged. Zero container modifications.

The `overview/index.ts` barrel is for internal use — sub-components import types/helpers from siblings within the `overview/` directory.

---

## Implementation sequence

1. Create `overview/types.ts` — no deps
2. Create `overview/helpers.ts` — depends on types
3. Create `overview/useOverviewMetrics.ts` — depends on types
4. Create `overview/InstitutionalSparkline.tsx` — depends on types + lib/colors
5. Create `overview/OverviewMetricCard.tsx` — depends on types + helpers + InstitutionalSparkline
6. Create `overview/ViewControlsHeader.tsx` — depends on types
7. Create `overview/SmartAlertsPanel.tsx` — depends on types
8. Create `overview/MarketIntelligenceBanner.tsx` — depends on types
9. Create `overview/AIRecommendationsPanel.tsx` — depends on types
10. Create `overview/SettingsPanel.tsx` — self-contained + UI primitives
11. Create `overview/index.ts` — barrel
12. Rewrite `PortfolioOverview.tsx` as orchestrator importing from `./overview`

Steps 6-10 are independent and can be parallelized.

---

## Files modified

| File | Changes |
|------|---------|
| `overview/types.ts` | **NEW** ~130 lines |
| `overview/helpers.ts` | **NEW** ~80 lines |
| `overview/useOverviewMetrics.ts` | **NEW** ~140 lines |
| `overview/InstitutionalSparkline.tsx` | **NEW** ~120 lines |
| `overview/OverviewMetricCard.tsx` | **NEW** ~300 lines |
| `overview/ViewControlsHeader.tsx` | **NEW** ~80 lines |
| `overview/SmartAlertsPanel.tsx` | **NEW** ~45 lines |
| `overview/MarketIntelligenceBanner.tsx` | **NEW** ~70 lines |
| `overview/AIRecommendationsPanel.tsx` | **NEW** ~90 lines |
| `overview/SettingsPanel.tsx` | **NEW** ~290 lines |
| `overview/index.ts` | **NEW** ~10 lines |
| `PortfolioOverview.tsx` | **REWRITE** 2,076 → ~180 lines |

**NOT modified:** PortfolioOverviewContainer.tsx, any other view component, blocks/, lib/colors.ts

**Total:** ~1,508 lines across 12 files (was 2,076 in 1 file). Net reduction from removing verbose comment blocks.

---

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. `cd frontend && pnpm build` — must pass
3. Visual verification in Chrome — all 4 view modes (Compact/Detailed/Pro/Institutional)
4. Smart Alerts, Market Intelligence, AI Recommendations all render
5. Settings panel opens, all 5 sections present, Save/Reset work
6. Metric card hover effects, AI insights panel, tooltips all work
7. Verify container import still resolves (no import path breakage)
