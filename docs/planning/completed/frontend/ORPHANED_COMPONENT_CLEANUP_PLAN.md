# Orphaned Component Cleanup

## Context

~30 frontend files are never rendered in the running app. They add to bundle size, lint warnings, and cognitive overhead. Inventory completed 2026-02-26 in `completed/FRONTEND_ORPHANED_COMPONENTS.md`, verified still orphaned 2026-03-04. Pure deletion — no behavioral changes.

All paths below are full paths from `frontend/packages/ui/src/`.

---

## Deletions by Category

### Cat 6: Debug Artifact (1 file)
- `components/dashboard/shared/recovery/risk-analysis-dashboard.tsx`
- Delete `components/dashboard/shared/recovery/` directory.

### Cat 4: Orphaned Shared UI (5 files — delete entire directory)
- `components/dashboard/shared/ui/MetricsCard.tsx`
- `components/dashboard/shared/ui/StatusIndicator.tsx`
- `components/dashboard/shared/ui/LoadingView.tsx`
- `components/dashboard/shared/ui/index.js` (duplicate of index.ts)
- `components/dashboard/shared/ui/index.ts`
- Delete entire `components/dashboard/shared/ui/` directory.
- **Barrel**: Remove `export * from './ui'` from `components/dashboard/shared/index.ts` (line 2)

### Cat 2: Superseded Infrastructure (4 files)
- `router/AppOrchestrator.tsx` (superseded by AppOrchestratorModern)
- `components/layouts/DashboardLayout.tsx`
- `components/layouts/index.ts`
- `components/portfolio/ConnectedRiskAnalysis.tsx` (reference template, never rendered — exported from `components/dashboard/views/modern/index.ts` line 41 via `../../../portfolio/ConnectedRiskAnalysis`)
- **Barrel**: Remove line 41 from `components/dashboard/views/modern/index.ts` (`export { default as ConnectedRiskAnalysis }`)
- Delete `components/layouts/` directory.

### Cat 1: Dead Page + Dependencies (4 files)
- `pages/InstantTryPage.tsx`
- `components/AnalysisSection.tsx`
- `components/FileUploadSection.tsx`
- `components/portfolio/PortfolioHoldings.tsx`
- **Barrel**: Remove `export { default as PortfolioHoldings }` from `components/portfolio/index.ts` (line 48)

### Cat 5: Legacy Provider Components (6 files — delete both directories)
- `components/plaid/PlaidLinkButton.tsx`
- `components/plaid/ConnectedAccounts.tsx`
- `components/plaid/index.ts`
- `components/snaptrade/SnapTradeLaunchButton.tsx`
- `components/snaptrade/ConnectedSnapTradeAccounts.tsx`
- `components/snaptrade/index.ts`
- **Barrel**: Remove `export * from './plaid'` from `components/index.ts` (line 34)
- Delete `components/plaid/` and `components/snaptrade/` directories.

### Cat 3: Orphaned Chart Subsystem (22 files — delete entire directory)
Delete entire `components/dashboard/shared/charts/` directory:
- 6 chart components (RiskRadarChart, VarianceBarChart, PerformanceLineChart, RiskContributionChart, RiskContributionParetoChart, PerformanceBenchmarkChart)
- 8 slot components + `slots/index.ts`
- 2 example files (ChartExamples, ViewIntegrationExample)
- 1 adapter (chartDataAdapters.ts)
- 1 constants file (chartConstants.ts)
- 2 markdown docs (README.md, INTEGRATION_GUIDE.md)
- `charts/index.ts`
- **Barrel**: Remove `export * from './charts'` from `components/dashboard/shared/index.ts` (line 3)

---

## Barrel Export Changes Summary

| File (from `frontend/packages/ui/src/`) | Change |
|------|--------|
| `components/dashboard/views/modern/index.ts` | Remove line 41 (ConnectedRiskAnalysis export) |
| `components/portfolio/index.ts` | Remove line 48 (PortfolioHoldings export) |
| `components/index.ts` | Remove line 34 (`export * from './plaid'`) |
| `components/dashboard/shared/index.ts` | Remove lines 2-3 (`export * from './ui'` and `export * from './charts'`) |

---

## Files Summary

**Delete**: 42 files across 6 directories:
- `components/dashboard/shared/recovery/` (1 file)
- `components/dashboard/shared/ui/` (5 files)
- `components/dashboard/shared/charts/` (22 files)
- `components/layouts/` (2 files)
- `components/plaid/` (3 files)
- `components/snaptrade/` (3 files)
- Plus 6 standalone files: `router/AppOrchestrator.tsx`, `pages/InstantTryPage.tsx`, `components/AnalysisSection.tsx`, `components/FileUploadSection.tsx`, `components/portfolio/PortfolioHoldings.tsx`, `components/portfolio/ConnectedRiskAnalysis.tsx`

**Modify**: 4 barrel export files

## Codex Review (R1)

**FAIL** — 3 findings:
1. **Medium** — `ConnectedRiskAnalysis.tsx` path was wrong → Fixed: `components/portfolio/ConnectedRiskAnalysis.tsx`.
2. **Medium** — Barrel summary incomplete for `ui/` → Fixed: delete entire directory.
3. **Low** — Path prefixes inconsistent, file counts off → Fixed: all paths now full from `frontend/packages/ui/src/`, counts enumerated.

## Codex Review (R2)

**FAIL** — cosmetic only:
1. Dashboard paths still used short form (`dashboard/...` instead of `components/dashboard/...`) → Fixed: all paths now fully qualified.
2. Category file counts inconsistent with listed items → Fixed: counts match enumerated files.

## Verification

1. `cd frontend && pnpm typecheck` — 0 TS errors
2. `cd frontend && pnpm build` — clean build (confirms no runtime imports broken)
3. Visual check: app renders normally (Overview, Holdings, Performance, Analytics views)
