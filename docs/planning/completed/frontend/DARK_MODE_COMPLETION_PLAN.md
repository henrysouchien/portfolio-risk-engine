# R19: Dark Mode CSS Completion Plan

**Status**: READY TO EXECUTE (v3 — revised after Codex review)
**Date**: 2026-03-16
**Source**: `docs/planning/REVIEW_FINDINGS.md` — R19

---

## Problem Summary

When `.dark` class is on `<html>`, the header/sidebar go dark (via glass-premium dark overrides) but the main content area stays light. Text in headings, company names, and filters becomes faded gray-on-white, nearly unreadable. Three root causes:

1. **41 CSS variables missing from the `.dark` block** in `index.css` (69 in `:root`, 28 in `.dark`). Missing: the entire neutral scale (10), accent color palettes (25), and shadow tokens (3). Additionally, `--destructive`, `--destructive-foreground`, and `--sidebar-*` are missing from BOTH `:root` and `.dark`.

2. **~1,727 hardcoded color class occurrences across ~120 component files.** Classes like `text-neutral-900`, `bg-white`, `border-neutral-200` use Tailwind's built-in neutral palette (fixed hex values), NOT the CSS variables defined in index.css. These cannot respond to theme changes.

3. **No dark mode toggle in the UI.** The uiStore has `setTheme()` and App.tsx syncs the `.dark` class, but there is no user-visible control. Theme is not persisted to localStorage.

## Architecture Decision

**Key insight (confirmed by Codex):** `tailwind.config.js` maps only **semantic** colors (`foreground`, `card`, `border`, `muted`, etc.) to CSS vars. It does NOT remap Tailwind's built-in `neutral-*` scale. There are **zero** `var(--neutral-*)` or `hsl(var(--neutral-*))` usages in any frontend component. Adding dark values for `--neutral-*` CSS vars alone fixes essentially nothing visible.

The semantic CSS variable classes (`text-foreground`, `bg-card`, `bg-muted`, etc.) **already work in dark mode** because their dark values are defined in the `.dark` block. The fix is migrating hardcoded Tailwind classes to these semantic classes.

**Consequence for phasing:** Component migration (Phases 3-6) does NOT depend on Phase 1. Semantic classes already resolve correctly in dark mode. Phase 1 only helps glass/gradient utilities and custom CSS that references vars directly.

---

## Phase 1: CSS Variable Completion + Gradient Dark Overrides

**File:** `frontend/packages/ui/src/index.css`
**Impact:** Fixes glass-based cards, gradient backgrounds, and custom CSS. Does NOT fix hardcoded Tailwind classes.

### 1a. Add dark overrides for missing variables

41 `:root` variables are absent from `.dark`. Of these, 38 are theme-dependent and need dark overrides. The remaining 3 (`--radius`, `--radius-lg`, `--radius-xl`) are geometry tokens — not theme-dependent, no dark override needed.

**Neutral scale** (inverted for dark mode):
```css
--neutral-50:  213 25% 9%;
--neutral-100: 213 23% 12%;
--neutral-200: 213 20% 18%;
--neutral-300: 213 18% 25%;
--neutral-400: 210 12% 40%;
--neutral-500: 210 9% 55%;
--neutral-600: 210 7% 65%;
--neutral-700: 210 9% 78%;
--neutral-800: 210 12% 88%;
--neutral-900: 210 17% 96%;
```

**Accent palettes** (bumped lightness for visibility on dark bg):
- **Emerald**: `--emerald-50: 160 30% 12%`, `--emerald-100: 158 35% 18%`, `--emerald-500: 160 74% 55%`, `--emerald-600: 158 74% 48%`, `--emerald-700: 158 80% 40%`
- **Blue**: `--blue-50: 217 30% 12%`, `--blue-100: 214 35% 18%`, `--blue-500: 217 81% 65%`, `--blue-600: 221 73% 58%`, `--blue-700: 224 76% 52%`
- **Amber**: `--amber-50: 48 30% 12%`, `--amber-100: 48 35% 18%`, `--amber-400: 45 86% 68%`, `--amber-500: 43 89% 65%`, `--amber-600: 41 96% 58%`
- **Red**: `--red-50: 0 30% 12%`, `--red-100: 0 35% 18%`, `--red-500: 0 74% 65%`, `--red-600: 0 72% 58%`, `--red-700: 0 74% 52%`
- **Purple**: `--purple-50: 270 30% 12%`, `--purple-100: 269 35% 18%`, `--purple-500: 262 73% 68%`, `--purple-600: 262 70% 60%`, `--purple-700: 262 76% 55%`

**Shadow tokens**:
```css
--shadow-soft:   213 15% 4%;
--shadow-medium: 213 20% 2%;
--shadow-strong: 213 25% 0%;
```

### 1b. Add `--destructive` and `--destructive-foreground` to BOTH `:root` and `.dark`

Light:
```css
--destructive: 0 72% 51%;
--destructive-foreground: 0 0% 98%;
```
Dark (must maintain ≥4.5:1 contrast per WCAG AA):
```css
--destructive: 0 62% 30%;           /* Darker red background */
--destructive-foreground: 0 0% 98%; /* Near-white text → ~9.8:1 contrast */
```

**Rationale**: `toast.tsx` uses `bg-destructive text-destructive-foreground`. The v1 plan proposed `0 74% 65%` with white text ≈ 3.13:1 (fails WCAG AA). Use a darker red bg to maintain accessible contrast.

### 1c. Add `--sidebar-*` variables to BOTH `:root` and `.dark`

**De-prioritized**: The live shell uses `AppSidebar.tsx`, while the generic `sidebar.tsx` component that references these vars appears unused in the current app. Add the vars for completeness but this is low ROI for the dark mode issue. Match existing `--card` / `--card-foreground` values.

### 1d. Add dark overrides for gradient utility classes

After the existing `.dark .glass-tinted` block, add dark overrides for light-only gradient/pseudo-element utilities:
- `.dark .bg-gradient-sophisticated` — dark neutral gradient (used by ModernDashboardApp main layout)
- `.dark .gradient-success` — dark emerald gradient
- `.dark .gradient-risk` — dark amber gradient
- `.dark .gradient-depth` — dark blue gradient
- `.dark .gradient-sophisticated` — dark neutral gradient (used by `BenchmarksTab.tsx`)
- `.dark .skeleton-premium` — dark gray gradient sweep
- `.dark .shimmer-loading` — dark shimmer
- `.dark .btn-premium::before` — dark button gradient pseudo-element
- `.dark .scroll-premium::-webkit-scrollbar-thumb` — dark scrollbar thumb

**Note:** Some utility classes may have additional pseudo-element or scrollbar styles with hardcoded light colors. Audit all `::before`, `::after`, and `::-webkit-scrollbar-*` rules in `index.css` for light-only gradients.

---

## Phase 2: Dark Mode Toggle + Theme Persistence

**Files:** `frontend/packages/connectors/src/stores/uiStore.ts`, `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx`, `frontend/packages/ui/src/App.tsx` (verify `.dark` class sync)
**Dependency:** NONE — works independently of Phase 1

### 2a. Add localStorage persistence for theme

In `frontend/packages/connectors/src/stores/uiStore.ts` (the canonical store — `frontend/packages/ui/src/stores/uiStore.ts` is only a re-export), add `getStoredTheme()` helper (matching existing `getStoredVisualStyle()` pattern). Update `setTheme` action to persist. Export `useTheme` selector. Add test coverage for storage and root `.dark` class sync in `App.tsx`.

### 2b. Add dark mode toggle to SettingsPanel

Add "Color Mode" toggle in the Appearance section (after Visual Style, before Navigation Layout). Use same ToggleGroup component and layout pattern. Follow the existing draft-then-commit pattern: current appearance settings use local draft state (initialized from store on open, committed on Save). The Color Mode toggle should follow the same pattern — draft on change, apply on Save — for consistency with Visual Style and Navigation Layout.

### 2c. Migrate SettingsPanel itself (47 hardcoded refs)

As proof-of-concept, replace hardcoded classes in SettingsPanel — the first thing users see when toggling dark mode. Use **contextual** semantic replacements:

| Hardcoded class | Semantic replacement | Context |
|---|---|---|
| `text-neutral-900` | `text-foreground` | Headings, labels |
| `text-neutral-700` | `text-foreground` | Primary text |
| `text-neutral-600` | `text-muted-foreground` | Descriptions |
| `text-neutral-500` | `text-muted-foreground` | Secondary text |
| `bg-white` | `bg-card` | Card/panel backgrounds |
| `bg-neutral-50` | `bg-muted` | Subtle backgrounds |
| `border-neutral-200` | `border-border` | Dividers, borders |
| `border-neutral-200/50` | `border-border/50` | Subtle borders |
| `data-[state=on]:bg-blue-50/60` | `data-[state=on]:bg-primary/10` | Toggle selected bg |
| `data-[state=on]:border-blue-500` | `data-[state=on]:border-primary` | Toggle selected border |
| `data-[state=on]:text-neutral-900` | `data-[state=on]:text-foreground` | Toggle selected text |
| `hover:bg-neutral-50` | `hover:bg-muted` | Toggle hover bg |
| `bg-neutral-300` (in layout preview divs) | `bg-muted-foreground/40` | Preview decoration |
| `border-neutral-200/50` | `border-border/50` | Subtle preview border |
| `bg-white/70` | `bg-card/70` | Preview glass bg |

**Note:** The SettingsPanel mapping table covers the most impactful classes. Additional hardcoded classes in preview/decoration elements (layout mock divs) should be migrated during implementation but may use context-specific replacements.

---

## Phase 3: Navigation Shell Migration

Always-visible chrome — fixes the entire shell.

**Files (3 files, ~35 refs):**
- `AppSidebar.tsx` (4 refs)
- `NavBar.tsx` (10 refs — includes `focus-visible:ring-neutral-400`)
- `ModernDashboardApp.tsx` (21 refs)

**Dependency:** NONE — semantic classes already have dark values

### Contextual Replacement Mapping

| Hardcoded class | Semantic replacement | Context |
|---|---|---|
| `bg-white`, `bg-white/90` | `bg-card`, `bg-card/90` | Panel/card backgrounds |
| `text-neutral-900` | `text-foreground` | Headings, primary labels |
| `text-neutral-700`, `text-neutral-800` | `text-foreground` | Primary text |
| `text-neutral-600`, `text-neutral-500` | `text-muted-foreground` | Secondary text |
| `text-neutral-400` | `text-muted-foreground` | Tertiary text |
| `bg-neutral-50` | `bg-muted` | Subtle backgrounds |
| `bg-neutral-100` | `bg-secondary` | Secondary backgrounds |
| `bg-neutral-300/40` | `bg-border/40` | Separators/dividers |
| `border-neutral-200` | `border-border` | Borders |
| `border-neutral-200/60` | `border-border/60` | Subtle borders |
| `hover:bg-neutral-100` | `hover:bg-secondary` | Hover states |
| `hover:text-neutral-900` | `hover:text-foreground` | Hover text |
| `hover:bg-white/60` | `hover:bg-card/60` | Hover card bg |
| `bg-neutral-900 text-white` | `bg-foreground text-background` | Active nav button |
| `focus-visible:ring-neutral-400` | `focus-visible:ring-ring` | Focus rings |
| `hover:bg-emerald-50 hover:text-emerald-700` | Keep as-is | Brand accent hovers (already visible on dark bg) |

---

## Phase 4: High-Impact Dashboard Components + Chart Theming

### Batch 4A — Overview page (6 files, ~50 refs)
- `PortfolioOverview.tsx`, `OverviewMetricCard.tsx`, `SmartAlertsPanel.tsx`, `AIRecommendationsPanel.tsx`, `MarketIntelligenceBanner.tsx`, `ViewControlsHeader.tsx`

### Batch 4B — Dashboard cards (4 files, ~19 refs)
- `DashboardHoldingsCard.tsx`, `DashboardIncomeCard.tsx`, `DashboardPerformanceStrip.tsx`, `DashboardAlertsPanel.tsx`

### Batch 4C — Holdings view (5 files, ~29 refs)
- `HoldingsTable.tsx`, `HoldingsTableHeader.tsx`, `HoldingsTableFooter.tsx`, `HoldingsSummaryCards.tsx`, `PortfolioHoldings.tsx`

### Batch 4D — Chart theming (NEW)

Newer charts use `chart-theme.ts` (dark-aware), but older chart code hardcodes light colors:
- `PerformanceBenchmarkChart.tsx` — hardcoded light grays/hex
- `chartConstants.ts` — hardcoded color palette
- Any other chart files using literal `#hex` or `rgb()` values instead of theme tokens

**Fix**: Migrate hardcoded chart colors to use `chart-theme.ts` helpers or CSS variables. Verify all Recharts/chart components respond to theme changes.

Same contextual replacement mapping as Phase 3 for non-chart components.

---

## Phase 5: Content View Components

### Batch 5A — Scenario tools (5 files, ~190 refs)
- `BacktestTool.tsx` (49), `OptimizeTool.tsx` (40), `MonteCarloTool.tsx` (40), `StressTestTool.tsx` (36), `WhatIfTool.tsx` (25)

### Batch 5B — Trading view (4 files, ~239 refs)
- `BasketsCard.tsx` (86), `QuickTradeCard.tsx` (67), `HedgeMonitorCard.tsx` (57), `OrdersCard.tsx` (29)

### Batch 5C — Performance + Research (8 files, ~95 refs)
- `PerformanceHeaderCard.tsx` (33), `PerformanceTab.tsx` (28), `PerformanceChart.tsx` (19), `StockLookup.tsx` (28), `AssetAllocation.tsx` (28), `RiskAnalysis.tsx` (31), `FactorRiskModel.tsx` (27), `HedgeWorkflowDialog.tsx` (28)

### Batch 5D — Remaining (chat, blocks, shared)
- `ChatCore.tsx` (18), `metric-card.tsx` (11), `PortfolioSelector.tsx` (14), `RiskSettingsViewModern.tsx` (32), remaining block/error components

**Note**: Each batch must handle context-specific replacements (tooltips, error surfaces, destructive states) — not just blanket neutral→semantic swaps.

---

## Phase 6: Block Components + Shared UI (move earlier if bandwidth allows)

Shared building blocks — fixing these propagates dark mode support to every consumer. Consider moving this before Phase 5 for higher leverage.

- `gradient-progress.tsx`, `section-header.tsx`, `percentage-badge.tsx`, `status-cell.tsx`, `insight-banner.tsx`, `metric-card.tsx`
- `notification-center.tsx`, `LoadingSpinner.tsx`, `ConditionalStates.tsx`, `ErrorBoundary.tsx`, `LiveClock.tsx`

---

## Execution Order and Dependencies

```
Phase 1 (CSS vars + gradients)  — INDEPENDENT, 1 file, helps glass/gradient areas
Phase 2 (toggle + persist)      — INDEPENDENT, 2 files, enables user testing
Phase 3 (nav shell)             — INDEPENDENT (semantic classes already have dark values)
Phase 4 (overview + charts)     — INDEPENDENT, Phase 1 helps gradient components
Phase 5 (content views)         — INDEPENDENT, can parallelize across batches
Phase 6 (blocks/shared)         — INDEPENDENT, consider running before Phase 5
```

**Correction from v1:** Phases 3-6 do NOT depend on Phase 1. Semantic classes (`text-foreground`, `bg-card`, `border-border`, etc.) already have correct dark values in the `.dark` block via `tailwind.config.js` → CSS var mapping. Phase 1 only helps glass/gradient utility classes and any future `hsl(var(--neutral-*))` usage.

**Recommended order:** 2 → 1 → 3 → 6 → 4 → 5 (toggle first so you can test, then shell, then shared blocks for leverage, then views)

---

## Testing Strategy

For each phase:
1. Toggle dark mode via devtools: `document.documentElement.classList.toggle('dark')`
2. After Phase 2: use the new UI toggle in Settings
3. Verify: all text readable (≥4.5:1 contrast), no white-on-white, no faded text
4. Verify: light mode unchanged (no regressions)
5. Verify: premium visual style works in both light and dark
6. Verify: chart colors/axes/labels are readable in dark mode (Phase 4D)
7. Verify: toast/destructive surfaces meet WCAG AA contrast (Phase 1b)
8. Run existing frontend test suite (`npm test`)

## Risk Mitigation

- **Near-identical light mode:** Semantic class values are close but not pixel-identical to the hardcoded classes they replace (e.g., `bg-neutral-50` ≈ `bg-muted`, `text-neutral-700` ≈ `text-foreground` — similar but different HSL values). Visual QA in light mode is required after each batch to catch any perceptible shifts.
- **Incremental:** Each phase/batch is independently committable and testable.
- **Parallel-safe:** All phases touch different files. Batches within phases touch different components.
- **Accessible contrast:** Dark destructive uses darker red bg (not bright red) to maintain ≥4.5:1 with light text.
- **Test coverage:** 443+ existing frontend tests catch regressions in component rendering.
