# Frontend Orphaned Components — Cleanup Task

**Date**: 2026-02-26
**Status**: Inventory complete — cleanup not started
**Priority**: Low — none of these affect the running app

### Related Docs
| Doc | Purpose |
|-----|---------|
| `FRONTEND_COMPONENT_VISUAL_MAP.md` | Visual map of all components that ARE rendered |
| `FRONTEND_PHASE2_WORKING_DOC.md` | Phase 2 master doc — this cleanup is a separate workstream |

---

## Summary

~30 files exist in the frontend that are never rendered in the running app. They fall into 6 categories: a dead page with its dependencies, superseded infrastructure, an entire orphaned chart subsystem, unused shared UI primitives, legacy provider components, and a debug artifact.

None of these affect functionality. They add to bundle size, lint warning count, and cognitive overhead when navigating the codebase.

---

## Category 1: Dead Page + Dependencies (4 files)

`InstantTryPage.tsx` was built as a "try without signing up" flow. The `LandingPage` fires `window.location.href = '/try'` on click, but `AppOrchestratorModern` has no `/try` route handler — only `/plaid/success` and `/snaptrade/success` are routed. The page is completely unreachable.

| File | Role | Only Used By |
|------|------|-------------|
| `pages/InstantTryPage.tsx` | Dead page — no route in AppOrchestratorModern | (entry point) |
| `components/AnalysisSection.tsx` | Sub-component | InstantTryPage only |
| `components/FileUploadSection.tsx` | Sub-component | InstantTryPage only |
| `components/portfolio/PortfolioHoldings.tsx` | Sub-component | InstantTryPage only |

**Action**: Delete all 4 files. Remove the `/try` navigation from `LandingPage` if it still exists.

---

## Category 2: Superseded Infrastructure (3 files)

| File | What It Was | Why It's Dead |
|------|------------|--------------|
| `router/AppOrchestrator.tsx` | Original router | Replaced by `AppOrchestratorModern`. `App.tsx` imports Modern exclusively. |
| `components/layouts/DashboardLayout.tsx` | Layout wrapper | Export commented out in `components/index.ts`. No importers. |
| `components/dashboard/views/modern/ConnectedRiskAnalysis.tsx` | Reference implementation | Used as a template to build `RiskAnalysisModernContainer`. Exported from barrel but never rendered. |

**Action**: Delete all 3 files. Remove `ConnectedRiskAnalysis` from the `modern/index.ts` barrel export.

---

## Category 3: Orphaned Chart Subsystem (~16 files)

The entire `dashboard/shared/charts/` directory is a self-contained island. No production container imports anything from it. It appears to have been built as a reusable chart infrastructure but was never wired into the actual dashboard views.

**Raw chart components** (6 files):
- `RiskRadarChart.tsx`
- `VarianceBarChart.tsx`
- `PerformanceLineChart.tsx`
- `RiskContributionChart.tsx`
- `RiskContributionParetoChart.tsx`
- `PerformanceBenchmarkChart.tsx`

**Slot components** (8 files in `charts/slots/`):
- All 8 slot components — only used within `examples/ChartExamples.tsx` and `examples/ViewIntegrationExample.tsx`

**Example/demo files** (2 files):
- `examples/ChartExamples.tsx`
- `examples/ViewIntegrationExample.tsx`

**Adapter** (1 file):
- `chartDataAdapters.ts`

**Action**: Evaluate whether any of these chart components are worth keeping for Phase 3 (Composable App Framework SDK — `ChartPanel` primitive). If not, delete the entire `dashboard/shared/charts/` directory.

---

## Category 4: Orphaned Shared UI Components (3 files)

| File | What It Was | Importers |
|------|------------|-----------|
| `dashboard/shared/ui/MetricsCard.tsx` | Generic metric card | None |
| `dashboard/shared/ui/StatusIndicator.tsx` | Status dot/badge | None |
| `dashboard/shared/ui/LoadingView.tsx` | Loading skeleton | None |

These appear to have been built as reusable primitives but the production containers use their own inline implementations instead.

**Action**: Delete. If Phase 3 SDK needs these patterns, they'll be rebuilt as proper SDK primitives (`MetricGrid`, etc.).

---

## Category 5: Legacy Provider Components (4 files)

The actual account connections UI goes through `AccountConnectionsContainer` (settings/) → `AccountConnections` (settings/). These older component-level wrappers around Plaid/SnapTrade are completely bypassed.

| File | What It Was | Current Status |
|------|------------|---------------|
| `components/plaid/PlaidLinkButton.tsx` | Direct Plaid Link button | Bypassed — only referenced in `archive/legacy/` |
| `components/plaid/ConnectedAccounts.tsx` | Plaid accounts list | Bypassed — same |
| `components/snaptrade/SnapTradeLaunchButton.tsx` | Direct SnapTrade launch | Only in archived legacy example |
| `components/snaptrade/ConnectedSnapTradeAccounts.tsx` | SnapTrade accounts list | Same |

**Action**: Delete all 4 files and their parent directories if empty after deletion.

---

## Category 6: Debug Artifact (1 file)

| File | What It Was |
|------|------------|
| `dashboard/shared/recovery/risk-analysis-dashboard.tsx` | Recovery/debug artifact — no importers anywhere |

**Action**: Delete.

---

## Execution Plan

1. **Verify** each file has zero production importers (grep for import statements)
2. **Delete** files by category (smallest risk first: categories 6, 4, 2, 1, 3)
3. **Clean up** barrel exports (`modern/index.ts`, `components/index.ts`, any other barrels)
4. **Typecheck**: `cd frontend && pnpm typecheck` — 0 errors
5. **Lint**: `cd frontend && pnpm lint` — warning count should decrease
6. **Commit** with descriptive message

Estimated impact: ~30 fewer files, reduced bundle size, lower lint warning count.
