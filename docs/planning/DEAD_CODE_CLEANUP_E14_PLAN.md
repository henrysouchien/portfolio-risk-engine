# E14 Dead Code Cleanup — Legacy Scenario System

## Context

The scenario system was decomposed from a monolithic `ScenarioAnalysis.tsx` orchestrator (with 5 inline tabs) into a tool-based `ScenariosRouter` with lazy-loaded per-tool components (`WhatIfTool`, `StressTestTool`, `MonteCarloTool`, `OptimizeTool`, `BacktestTool`, `HedgeTool`, `RebalanceTool`, `TaxHarvestTool`). The old files were never deleted.

`ModernDashboardApp.tsx` routes `'scenarios'` to `<ScenariosRouter />`, not to the legacy `ScenarioAnalysisContainer`. The old tabs, their container, the monolithic orchestrator, and the legacy `RecentRunsPanel` are all unreachable in the live app.

## Codex Review Findings (Round 1 + Round 2)

**Round 1** expanded scope from 3 files to 10: old tabs and `RecentRunsPanel` are also dead.

**Round 2** (via MCP) returned FAIL with these findings:
1. **Static reachability**: `modern/index.ts:32` re-exports `ScenarioAnalysisContainer`, and `ModernDashboardApp.tsx:84` imports from that barrel. However, `ModernDashboardApp.tsx` only destructures `PerformanceViewContainer` and `PortfolioOverviewContainer` — `ScenarioAnalysisContainer` is never used. The barrel export must be removed as part of this cleanup.
2. **`scenario/index.ts` keep list was imprecise**: Several barrel exports are dead (`useScenarioOrchestration` hook, `deriveMetricsFromComparison`, `deriveRecommendations`, `computeHhi`, `HISTORICAL_SCENARIOS`, `ScenarioTab`, `ScenarioAnalysisProps`). Live tools import directly from source files, not through the barrel.
3. **`HistoricalTab.tsx` reason was wrong**: `ScenarioAnalysis.tsx` does not import `HistoricalTab`. It has no live importer at all.
4. **`templates.ts` exports**: Barrel exports of template functions are dead (no external consumer), but the file itself is live (`useScenarioState.ts:9` imports `buildScenarioTemplates` directly).

## Live Routing (what stays)

```
ModernDashboardApp.tsx
  └─ case 'scenarios': <ScenariosRouter />
       ├─ ScenariosLanding → ScenarioRunComparisonPanel (no rerun)
       └─ tools: WhatIfTool, StressTestTool, MonteCarloTool, OptimizeTool,
                 BacktestTool, HedgeTool, RebalanceTool, TaxHarvestTool
```

Live tools import directly from source files (e.g., `from "../../scenario/helpers"`), NOT through the `scenario/index.ts` barrel.

## Files to Delete (11 files)

### Layer 1: Orchestrator + Container

| # | File | Why dead |
|---|------|----------|
| 1 | `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` | Monolithic orchestrator, replaced by `ScenariosRouter`. Only imported by dead container (#2). |
| 2 | `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` | Wrapper for #1. Re-exported from `modern/index.ts` barrel but never destructured by any live import. |
| 3 | `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.test.tsx` | Orphaned test for #2. |

### Layer 2: Old Tab Components (only imported by #1)

| # | File | Why dead |
|---|------|----------|
| 4 | `frontend/packages/ui/src/components/portfolio/scenario/PortfolioBuilderTab.tsx` | Only imported by dead `ScenarioAnalysis.tsx:15`. Replaced by `WhatIfTool`. |
| 5 | `frontend/packages/ui/src/components/portfolio/scenario/MonteCarloTab.tsx` | Only imported by dead `ScenarioAnalysis.tsx:18`. Replaced by `MonteCarloTool`. |
| 6 | `frontend/packages/ui/src/components/portfolio/scenario/StressTestsTab.tsx` | Only imported by dead `ScenarioAnalysis.tsx:17`. Replaced by `StressTestTool`. |
| 7 | `frontend/packages/ui/src/components/portfolio/scenario/OptimizationsTab.tsx` | Only imported by dead `ScenarioAnalysis.tsx:16`. Replaced by `OptimizeTool`. |
| 8 | `frontend/packages/ui/src/components/portfolio/scenario/HistoricalTab.tsx` | No live importer found. Not imported by `ScenarioAnalysis.tsx` or any new tool. |

### Layer 3: Components only used by dead tabs

| # | File | Why dead |
|---|------|----------|
| 9 | `frontend/packages/ui/src/components/portfolio/scenario/RecentRunsPanel.tsx` | Only rendered by dead tabs (#4-#8). Live app uses `ScenarioRunComparisonPanel` instead. |
| 10 | `frontend/packages/ui/src/components/portfolio/scenario/ScenarioHeader.tsx` | Only imported by dead `ScenarioAnalysis.tsx:14`. |

## Barrel Export Edits

### `scenario/index.ts` — Delete entirely

The barrel has **zero live consumers**. All live code imports directly from source files:
- `ScenariosLanding.tsx:19` → `from '../scenario/useScenarioHistory'`
- `WhatIfTool.tsx:6` → `from '../../scenario/useScenarioOrchestration'`
- `WhatIfTool.tsx:7` → `from '../../scenario/helpers'`
- `WhatIfTool.tsx:8` → `from '../../scenario/useScenarioState'`
- `OptimizeTool.tsx:13` → `from '../../scenario/EfficientFrontierTab'`
- `ScenarioRunComparisonPanel.tsx:3` → `from '../../scenario/types'`
- etc.

The only barrel importers are `ScenarioAnalysis.tsx` and `ScenarioAnalysisContainer.tsx` — both being deleted. (`ScenarioAnalysisContainer.test.tsx` imports the container directly, not the barrel.) So `scenario/index.ts` is itself dead code and should be deleted (bringing total to **11 files**).

### `modern/index.ts` — Remove dead container export

Remove line 32: `export { default as ScenarioAnalysisContainer } from './ScenarioAnalysisContainer';`

## What is NOT Deleted

These files in `scenario/` are **live** (imported by new tool components or `ScenariosLanding`):

| File | Live consumer | Import path |
|------|---------------|-------------|
| `useScenarioHistory.ts` | `ScenariosLanding.tsx:19` (presentation only; rerun branch is dead — see follow-up below) | Direct: `from '../scenario/useScenarioHistory'` |
| `useScenarioState.ts` | `WhatIfTool`, `MonteCarloTool`, `StressTestTool`, `HedgeTool`, `BacktestTool` | Direct: `from '../../scenario/useScenarioState'` |
| `useScenarioOrchestration.ts` | `WhatIfTool.tsx:6` (only `deriveOptimizedPositions`) | Direct: `from '../../scenario/useScenarioOrchestration'` |
| `EfficientFrontierTab.tsx` | `OptimizeTool.tsx:13` | Direct: `from '../../scenario/EfficientFrontierTab'` |
| `helpers.ts` | `WhatIfTool`, `StressTestTool`, `MonteCarloTool`, `BacktestTool` | Direct: `from '../../scenario/helpers'` |
| `types.ts` | `ScenarioRunComparisonPanel`, hooks, tools | Direct: `from '../../scenario/types'` |
| `templates.ts` | `useScenarioState.ts:9` | Direct: `from './templates'` |

Test files in `scenario/__tests__/` are **kept** (they test live hooks/templates/components):
- `useScenarioHistory.test.tsx` — tests live hook
- `useScenarioState.test.tsx` — tests live hook
- `templates.test.ts` — tests live templates
- `EfficientFrontierTab.test.tsx` — tests live tab (used by `OptimizeTool`)

## Follow-Up (out of scope for this plan)

**Dead rerun branch in `useScenarioHistory.ts`**: The hook is live (used by `ScenariosLanding`), but `ScenariosLanding` passes `undefined` for all three rerun callbacks (`onRunScenario`, `onRunStressTest`, `onRunMonteCarlo`). This means the `rerunHistoryEntry()` and `canReRunHistoryEntry()` functions (lines 162-202) are dead code within the live file — they were only callable from the now-deleted `RecentRunsPanel`. The corresponding test cases in `useScenarioHistory.test.tsx` (lines 22-65) test this dead branch. Pruning this dead code within live files is a separate, smaller task.

## Steps

1. Edit `modern/index.ts` — remove `ScenarioAnalysisContainer` export (line 32)
2. Delete 11 files (#1-#10 + `frontend/packages/ui/src/components/portfolio/scenario/index.ts`)
3. Search-and-clean stale references to deleted files. Run:
   ```
   rg -l "ScenarioAnalysis|ScenarioAnalysisContainer|PortfolioBuilderTab|RecentRunsPanel|ScenarioHeader|MonteCarloTab|StressTestsTab|OptimizationsTab|HistoricalTab" frontend/ docs/ --glob '!**/node_modules/**' --glob '!**/dist/**' --glob '!docs/planning/completed/**' --glob '!docs/planning/DEAD_CODE_CLEANUP_E14_PLAN.md' --glob '!docs/_archive/**' --glob '!docs/planning/_legacy/**' --glob '!frontend/archive/**'
   ```
   For each hit in a surviving file: remove or update the stale reference (comment, doc listing, or architecture description). Archive/legacy docs are excluded — they are historical and not worth updating. Known files with stale references include:
   - `ModernDashboardApp.tsx`, `ErrorBoundary.tsx`, `frontend/README.md`
   - `WhatIfAnalysisAdapter.ts`, `frontend/packages/ui/src/ARCHITECTURE.md`
   - `docs/architecture.md`, `docs/architecture/FRONTEND_ARCHITECTURE.md`
   - `frontend/packages/ui/src/components/portfolio/index.ts` (stale comment)
4. Run `npm run typecheck` in `frontend/` — full `tsc -b` workspace check
5. Run `npm run build` in `frontend/` — verify no import breakage
6. Run `npx vitest run` in `frontend/` — verify no test regressions (one-shot, not watch mode)
7. Update `docs/TODO.md` E14 entry to PARTIAL — file-level cleanup done, rerun branch pruning deferred

## Verification

1. `npm run typecheck` passes in `frontend/` — full workspace `tsc -b` checks all files, not just the bundled app graph
2. `npm run build` passes in `frontend/` — Vite build confirms the bundled app compiles
3. `npx vitest run` passes in `frontend/` — one-shot test run, no regressions from deleted files
