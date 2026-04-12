# E14 Dead Code Cleanup — Legacy Scenario System

## Context

The scenario system was decomposed from a monolithic `ScenarioAnalysis.tsx` orchestrator (with 5 inline tabs) into a tool-based `ScenariosRouter` with lazy-loaded per-tool components (`WhatIfTool`, `StressTestTool`, `MonteCarloTool`, `OptimizeTool`, `BacktestTool`, `HedgeTool`, `RebalanceTool`, `TaxHarvestTool`). The old files were never deleted.

`ModernDashboardApp.tsx` routes `'scenarios'` to `<ScenariosRouter />`, not to the legacy `ScenarioAnalysisContainer`. The old tabs, their container, the monolithic orchestrator, and the legacy `RecentRunsPanel` are all unreachable in the live app.

## Codex Review History

- **Round 1**: Expanded scope from 3 files to 10 (old tabs + `RecentRunsPanel` also dead).
- **Round 2**: FAIL — found barrel export issues, dead `scenario/index.ts`, imprecise keep list. All addressed below.
- **Round 3 (re-verification 2026-04-12)**: Confirmed all 11 original files dead. Found 12th file (`ScenarioHeader.test.tsx`). Confirmed `modern/index.ts` barrel already clean. Confirmed zero stale references in surviving source/doc files.

## Live Routing (what stays)

```
ModernDashboardApp.tsx
  └─ case 'scenarios': <ScenariosRouter />
       ├─ ScenariosLanding → ScenarioRunComparisonPanel (no rerun)
       └─ tools: WhatIfTool, StressTestTool, MonteCarloTool, OptimizeTool,
                 BacktestTool, HedgeTool, RebalanceTool, TaxHarvestTool
```

Live tools import directly from source files (e.g., `from "../../scenario/helpers"`), NOT through the `scenario/index.ts` barrel.

## Files to Delete (12 files)

### Layer 1: Orchestrator + Container

| # | File | Why dead |
|---|------|----------|
| 1 | `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` | Monolithic orchestrator, replaced by `ScenariosRouter`. No live importers. |
| 2 | `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` | Wrapper for #1. NOT exported from `modern/index.ts` barrel (already removed). No live importers. |
| 3 | `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.test.tsx` | Orphaned test for #2. |

### Layer 2: Old Tab Components (only imported by #1)

| # | File | Why dead |
|---|------|----------|
| 4 | `frontend/packages/ui/src/components/portfolio/scenario/PortfolioBuilderTab.tsx` | Only imported by dead `ScenarioAnalysis.tsx`. Replaced by `WhatIfTool`. |
| 5 | `frontend/packages/ui/src/components/portfolio/scenario/MonteCarloTab.tsx` | Only imported by dead `ScenarioAnalysis.tsx`. Replaced by `MonteCarloTool`. |
| 6 | `frontend/packages/ui/src/components/portfolio/scenario/StressTestsTab.tsx` | Only imported by dead `ScenarioAnalysis.tsx`. Replaced by `StressTestTool`. |
| 7 | `frontend/packages/ui/src/components/portfolio/scenario/OptimizationsTab.tsx` | Only imported by dead `ScenarioAnalysis.tsx`. Replaced by `OptimizeTool`. |
| 8 | `frontend/packages/ui/src/components/portfolio/scenario/HistoricalTab.tsx` | No live importer found anywhere. |

### Layer 3: Components only used by dead tabs

| # | File | Why dead |
|---|------|----------|
| 9 | `frontend/packages/ui/src/components/portfolio/scenario/RecentRunsPanel.tsx` | Only rendered by dead tabs (#4-#8). Live app uses `ScenarioRunComparisonPanel` instead. |
| 10 | `frontend/packages/ui/src/components/portfolio/scenario/ScenarioHeader.tsx` | Only imported by dead `ScenarioAnalysis.tsx`. |

### Layer 4: Dead barrel + orphaned test

| # | File | Why dead |
|---|------|----------|
| 11 | `frontend/packages/ui/src/components/portfolio/scenario/index.ts` | Zero live consumers. All live tools import directly from source files. Only importers were `ScenarioAnalysis.tsx` and `ScenarioAnalysisContainer.tsx` — both being deleted. |
| 12 | `frontend/packages/ui/src/components/portfolio/scenario/__tests__/ScenarioHeader.test.tsx` | Tests the dead `ScenarioHeader` component (#10). Added in Round 3 re-verification. |

## Barrel Export Edit

### `modern/index.ts` — Already clean

The `ScenarioAnalysisContainer` export was already removed from `modern/index.ts` in a prior refactor. No edit needed. Verified 2026-04-12.

## Stale Reference Cleanup

Re-verification on 2026-04-12 found **zero stale references in surviving source or doc files** besides `docs/TODO.md` (updated in Step 6). The original plan's expected stale refs (`ModernDashboardApp.tsx`, `ErrorBoundary.tsx`, `frontend/README.md`, `WhatIfAnalysisAdapter.ts`, architecture docs) were all cleaned up in prior work.

Verification command:
```
rg -l "ScenarioAnalysis|ScenarioAnalysisContainer|PortfolioBuilderTab|RecentRunsPanel|ScenarioHeader|MonteCarloTab|StressTestsTab|OptimizationsTab|HistoricalTab" frontend/ docs/ \
  --glob '!**/node_modules/**' --glob '!**/dist/**' --glob '!docs/planning/completed/**' \
  --glob '!docs/planning/DEAD_CODE_CLEANUP_E14_PLAN.md' --glob '!docs/_archive/**' \
  --glob '!docs/planning/_legacy/**' --glob '!frontend/archive/**'
```

All matches are files being deleted + `docs/TODO.md` (the sole surviving hit — updated in Step 6).

## What is NOT Deleted

These files in `scenario/` are **live** (imported by new tool components or `ScenariosLanding`):

| File | Live consumer(s) | Import path |
|------|------------------|-------------|
| `useScenarioHistory.ts` | `ScenariosLanding.tsx`, `ScenarioRunComparisonPanel.test.tsx` | Direct: `from '../scenario/useScenarioHistory'` |
| `useScenarioState.ts` | `WhatIfTool`, `MonteCarloTool`, `StressTestTool`, `HedgeTool`, `BacktestTool` | Direct: `from '../../scenario/useScenarioState'` |
| `useScenarioOrchestration.ts` | `WhatIfTool` (only `deriveOptimizedPositions`) | Direct: `from '../../scenario/useScenarioOrchestration'` |
| `EfficientFrontierTab.tsx` | `OptimizeTool` | Direct: `from '../../scenario/EfficientFrontierTab'` |
| `helpers.ts` | `WhatIfTool`, `StressTestTool`, `MonteCarloTool`, `BacktestTool` | Direct: `from '../../scenario/helpers'` |
| `types.ts` | `ScenarioRunComparisonPanel`, hooks, tools | Direct: `from '../../scenario/types'` |
| `templates.ts` | `useScenarioState.ts` | Direct: `from './templates'` |

Test files kept (Vitest entrypoints that test live code — not imported, discovered by test runner):
- `__tests__/useScenarioHistory.test.tsx`
- `__tests__/useScenarioState.test.tsx`
- `__tests__/templates.test.ts`
- `__tests__/EfficientFrontierTab.test.tsx`

## Steps

1. Delete 12 files (Layers 1-4 above)
2. No stale reference cleanup needed in source or doc files (already clean). `docs/TODO.md` is the sole surviving hit — updated in Step 6.
3. Run `npm run typecheck` in `frontend/` — full `tsc -b` workspace check
4. Run `npm run build` in `frontend/` — Vite build confirms no import breakage
5. Run `npx vitest run` in `frontend/` — one-shot test run, no regressions
6. Update `docs/TODO.md` E14 entry: mark DONE, update description to reflect file-level cleanup is complete. The deferred follow-up (dead rerun branch inside `useScenarioHistory.ts`) is a separate minor task — not part of E14's scope.

## Verification

1. `npm run typecheck` passes — workspace `tsc -b` checks all files
2. `npm run build` passes — Vite build confirms bundled app compiles
3. `npx vitest run` passes — no test regressions from deleted files

## Follow-Up (out of scope)

**Dead rerun branch in `useScenarioHistory.ts`**: The hook is live, but `ScenariosLanding` passes `undefined` for all three rerun callbacks. The `rerunHistoryEntry()` and `canReRunHistoryEntry()` functions are dead code within the live file. Pruning this is a separate, smaller task.
