# Dashboard Design Overhaul Plan

## Context

A gstack `/design-review` audit scored PortfolioRisk Pro **C+** (Design) / **B** (AI Slop) with 12 findings. Both Codex (GPT-5.4) and a Claude subagent independently triggered **hard rejection #7**: "App UI made of stacked cards instead of layout." The overview dashboard is a card quilt — 6 equal-weight metric cards + performance strip + 4 partner cards in stacked grids. No visual hierarchy, no focal point, no workspace feel.

A previous unimplemented plan (`OVERVIEW_LAYOUT_RESTRUCTURE_PLAN.md`) proposed reducing from 6 to 3 metric cards. This plan builds on that idea and adds the CSS quick wins from the audit.

**Goal:** Transform the dashboard from a card mosaic into a layout-driven workspace with clear visual hierarchy. Fix all CSS-safe audit findings in the same pass. Target: **B+** design score.

---

## Phase 1: CSS Clean Sweep (low risk, no structural changes)

### 1.1 Remove unused Crimson Text font import
**File:** `frontend/packages/ui/src/index.css` ~line 114
Remove `&family=Crimson+Text:wght@400;600` from the Google Fonts import URL. Saves ~20KB.

### 1.2 Remove DEV debug overlays
Remove the fixed-position debug badges from ~10 container files. All are guarded by `import.meta.env.DEV &&` but clutter the dev experience and leaked into the audit screenshots. Files:
- `dashboard/views/modern/PortfolioOverviewContainer.tsx`
- `dashboard/views/modern/containers/PerformanceViewContainer.tsx`
- `dashboard/views/modern/containers/HoldingsViewModernContainer.tsx`
- Plus ~7 more containers with the same pattern

Search: `import.meta.env.DEV &&` in `frontend/packages/ui/src/components/dashboard/`

### 1.3 Add tabular-nums to data-table cells
**File:** `frontend/packages/ui/src/components/blocks/data-table.tsx`
Add `tabular-nums` to the `<td>` className. Summary cards already have it, table cells don't. Numbers in the holdings table shift width on data change.

### 1.4 Add text-wrap: balance to CardTitle
**File:** `frontend/packages/ui/src/components/ui/card.tsx`
Add `text-balance-optimal` (existing utility in index.css) to the `CardTitle` base className. Multi-line headings currently break unevenly on narrow viewports.

### 1.5 Bump minimum text size
**File:** `frontend/packages/ui/src/components/dashboard/cards/PortfolioEarningsCard.tsx`
Change `text-[10px]` to `text-xs` (12px) in the `sectionHeadingClassName` constant. 10px is below readable minimum. Grep for other `text-[10px]` occurrences and bump to `text-xs`.

### 1.6 Reduce mobile content padding
**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` ~line 683
Change `px-8` to `px-4 md:px-8` on the main content container. On 375px screens, 32px padding each side wastes 64px.

### 1.7 Touch target minimum on nav buttons
**File:** `frontend/packages/ui/src/components/dashboard/NavBar.tsx`
Add `min-h-[44px]` to nav button className to meet WCAG AA SC 2.5.8.

---

## Phase 2: Overview Layout Transformation (medium risk)

### 2.1 Reduce metric cards from 6 to 3

**File:** `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts`

Keep only the 3 hero metrics from the returned array:
1. **Total Portfolio Value** (index 0) — "what am I worth"
2. **YTD Return** (index 1) — "am I making money"
3. **Risk Score** (index 3) — "how safe am I"

Remove: Max Drawdown (index 2), Sharpe Ratio (index 4), Alpha Generation (index 5). These move to the performance strip.

The grid in `MetricCardsSection.tsx` (`grid-cols-2 md:grid-cols-3`) naturally renders 3 items as a single row on desktop.

### 2.2 De-emphasize metric card decoration

**File:** `frontend/packages/ui/src/components/portfolio/overview/OverviewMetricCard.tsx`

Make data, not chrome, the focal point:
- Remove the decorative corner gradient (absolute positioned bg element at line 78)
- Remove hover scale effects (`scale-[1.02]`, `hover:scale-[1.005]`)
- Reduce the icon bubble — from `rounded-2xl p-3` to `rounded-lg p-2`, smaller and less prominent
- Increase value text from `text-3xl` to `text-4xl` for stronger hierarchy
- Simplify the change badge — from `<Badge>` with shadow to plain text

Keep: the card wrapper itself (for border, padding), the AI insight panel (on focus), click behavior.

### 2.3 Expand DashboardPerformanceStrip

**File:** `frontend/packages/ui/src/components/dashboard/cards/DashboardPerformanceStrip.tsx`

Add the 3 demoted metrics to the strip. The strip already receives `sharedState` with both `usePortfolioSummary()` and `usePerformance()` data. Add:
- **Max Drawdown** — from `summary.maxDrawdown`
- **Sharpe Ratio** — from `summary.sharpeRatio`
- **Alpha** — from `summary.alphaAnnual`

Update grid from `grid-cols-2 md:grid-cols-4` to `grid-cols-3 md:grid-cols-4 xl:grid-cols-7`.

### 2.4 Update section headings

- `DashboardHoldingsCard.tsx`: "Portfolio Holdings" heading stays (it's accurate)
- `DashboardAlertsPanel.tsx`: Review heading — keep if already descriptive

---

## Phase 3: Navigation Labels (medium risk)

### 3.1 Expand sidebar with text labels

**File:** `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx`

Current: `w-16` (64px) with icon-only `h-11 w-11` buttons.

Change to: `w-48` (192px) on `lg:` breakpoint, `w-16` (icon-only) below `lg:`. Each button becomes:
```
icon (h-5 w-5 shrink-0) + label (text-sm font-medium)
```

On screens below `lg:` (1024px), the sidebar collapses to icon-only mode (current behavior). On `lg:+`, labels are visible.

This is the standard "collapsible rail" pattern — Figma, Linear, and Notion all use it.

### 3.2 Normalize border-radius
- `OverviewMetricCard.tsx`: Change `rounded-2xl` to `rounded-xl` to match card base
- Audit other `rounded-3xl` usages and reduce to `rounded-2xl`

---

## Phase 4: Test Updates

### 4.1 Update useOverviewMetrics tests
**File:** `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.test.tsx`
Update assertions for 3-metric array (remove Sharpe, Alpha, Max Drawdown expectations).

### 4.2 Update DashboardPerformanceStrip tests
**File:** `frontend/packages/ui/src/components/dashboard/cards/DashboardPerformanceStrip.test.tsx`
Add assertions for the 3 new strip metrics (Drawdown, Sharpe, Alpha).

### 4.3 Run full test suite
```bash
cd frontend && npx vitest run
```

---

## Critical Files

| File | Change |
|------|--------|
| `index.css` | Remove Crimson Text import |
| `useOverviewMetrics.ts` | Reduce from 6 to 3 metrics |
| `OverviewMetricCard.tsx` | De-emphasize card decoration |
| `DashboardPerformanceStrip.tsx` | Add 3 metrics to strip |
| `data-table.tsx` | Add tabular-nums |
| `card.tsx` | Add text-balance-optimal |
| `AppSidebar.tsx` | Expand with text labels on lg: |
| `NavBar.tsx` | Touch target minimum |
| `ModernDashboardApp.tsx` | Mobile padding |
| `PortfolioEarningsCard.tsx` | text-[10px] → text-xs |
| ~10 container files | Remove DEV debug overlays |

## Out of Scope (deferred)

- Chart color audit (FINDING-006) — needs per-chart-component tracing
- Mobile bottom navigation — needs new component
- CSS variables for artifact panel widths — cross-component coordination
- Holdings row click-through (FINDING-009) — needs DataTable prop addition + navigation logic

## Verification

1. `cd frontend && npx tsc --noEmit` — no type errors
2. `cd frontend && npx vitest run` — all tests pass
3. Start dev server, visually confirm:
   - Overview shows 3 headline metrics, not 6 cards
   - Performance strip shows 7 metrics
   - No DEV debug badges
   - Sidebar shows labels on desktop
   - Table numbers are column-aligned
   - Card titles use balanced wrapping
4. Responsive check: 375px mobile, 768px tablet, 1280px desktop
5. Network tab: no Crimson Text font request

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Design Review | `/design-review` | Live site visual audit | 1 | **C+ / B** | 12 findings (5 high, 5 medium, 2 polish) |
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 0 | — | — |
| Design Plan Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |

**VERDICT:** Design audit complete. Plan ready for review pipeline — run `/autoplan` for full review, or individual reviews above.
