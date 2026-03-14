# Frontend TypeScript Errors + Lint Warning Reduction Plan

**Date**: 2026-02-25
**Status**: Complete (Part 1 — TS errors). Part 2 (no-explicit-any reduction) deferred.
**Risk**: Low — type annotations, exports, and null checks. No logic changes.
**Prerequisite**: Frontend remaining cleanup (complete)

## Context

After the three-package split, cleanup, and gateway integration, the frontend has ~16 TypeScript errors and ~700 ESLint warnings (~597 of which are `no-explicit-any`). This plan fixes all TS errors and reduces the `any` warnings by roughly half.

## Part 1: TypeScript Errors (~16 total, 6 categories)

### Category 1: TS4023 — Exported variable cannot be named (6 errors)

Hooks return adapter types that aren't re-exported from the connectors barrel. With `composite: true` + `declarationDir`, `tsc -b` needs to name these types in `.d.ts` output but can't resolve them.

```
connectors/src/features/analysis/hooks/useAnalysisReport.ts(109,14): TS4023 ... 'AnalysisReportData'
connectors/src/features/analysis/hooks/usePerformance.ts(126,14): TS4023 ... 'PerformanceData'
connectors/src/features/analysis/hooks/useRiskAnalysis.ts(137,14): TS4023 ... 'RiskAnalysisTransformedData'
connectors/src/features/portfolio/hooks/usePortfolioSummary.ts(206,14): TS4023 ... 'PerformanceData', 'PortfolioSummaryData', 'RiskAnalysisTransformedData'
```

**Fix (2 steps — order matters):**

1. Add `export` to the type/interface declarations in each adapter source file (currently not exported):
   - `AnalysisReportData` in `connectors/src/adapters/AnalysisReportAdapter.ts:133`
   - `PerformanceData` in `connectors/src/adapters/PerformanceAdapter.ts:214`
   - `RiskAnalysisTransformedData` in `connectors/src/adapters/RiskAnalysisAdapter.ts:248`
   - `PortfolioSummaryData` in `connectors/src/adapters/PortfolioSummaryAdapter.ts:170`

2. Re-export them from `packages/connectors/src/index.ts`:
   ```ts
   export type { AnalysisReportData } from './adapters/AnalysisReportAdapter';
   export type { PerformanceData } from './adapters/PerformanceAdapter';
   export type { RiskAnalysisTransformedData } from './adapters/RiskAnalysisAdapter';
   export type { PortfolioSummaryData } from './adapters/PortfolioSummaryAdapter';
   ```

### Category 2: Import cleanup — Cross-package relative paths (not a current TS error, but a consistency fix)

The gateway integration imports `GatewayClaudeService` and `loadRuntimeConfig` via relative paths that cross from connectors into chassis source. These currently resolve via local proxy files (`export * from '@risk/chassis'`), so they don't cause TS2307 errors. However, they should use `@risk/chassis` directly for consistency with the package boundary convention.

```
connectors/src/features/external/hooks/usePortfolioChat.ts(65): import { GatewayClaudeService } from '../../../chassis/services/GatewayClaudeService';
connectors/src/features/external/hooks/usePortfolioChat.ts(66): import { loadRuntimeConfig } from '../../../chassis/utils/loadRuntimeConfig';
```

Both symbols are already exported from the chassis barrel (`GatewayClaudeService` via `services/index.ts:62`, `loadRuntimeConfig` via `chassis/src/index.ts:10`).

**Fix:** Update imports in `usePortfolioChat.ts` to use the package import:
```ts
// FROM:
import { GatewayClaudeService } from '../../../chassis/services/GatewayClaudeService';
import { loadRuntimeConfig } from '../../../chassis/utils/loadRuntimeConfig';
// TO:
import { GatewayClaudeService, loadRuntimeConfig } from '@risk/chassis';
```

Note: `getRuntimeConfig` does NOT exist — the correct export is `loadRuntimeConfig`.

### Category 3: TS2305/TS2724 — SnapTrade type barrel gap (6 errors)

`useSnapTrade.ts` imports 6 type interfaces from a proxy file (`connectors/src/chassis/services/SnapTradeService.ts`) which re-exports `* from '@risk/chassis'`. The types exist and are exported from `chassis/src/services/SnapTradeService.ts`, but the chassis services barrel (`chassis/src/services/index.ts:58`) only re-exports the `SnapTradeService` class — not the type interfaces.

```
connectors/src/features/external/hooks/useSnapTrade.ts(30-35): TS2305/TS2724:
  SnapTradeRegisterResponse, SnapTradeConnectionUrlResponse, SnapTradeConnection,
  SnapTradeConnectionsResponse, SnapTradeHoldingsResponse, SnapTradeDisconnectResponse
```

All 6 types are defined and exported in `chassis/src/services/SnapTradeService.ts` (lines 37-116).

**Fix:** Add the type re-exports to `packages/chassis/src/services/index.ts`:
```ts
export type {
  SnapTradeRegisterResponse,
  SnapTradeConnectionUrlResponse,
  SnapTradeConnection,
  SnapTradeConnectionsResponse,
  SnapTradeHoldingsResponse,
  SnapTradeDisconnectResponse,
} from './SnapTradeService';
```

This makes them flow through the existing `export * from '@risk/chassis'` proxy.

### Category 4: TS7006 — Implicit any on reduce params (2 errors)

```
ui/src/components/settings/AccountConnectionsContainer.tsx(526,69): TS7006: Parameter 'sum' implicitly has an 'any' type.
ui/src/components/settings/AccountConnectionsContainer.tsx(526,74): TS7006: Parameter 'holding' implicitly has an 'any' type.
```

**Fix:** Add type annotations to the `.reduce()` callback. Read line 526 to determine the correct types from context (likely `number` for `sum` and a holdings type for `holding`).

### Category 5: TS2742 — Radix menubar inferred type not portable (1 error)

```
ui/src/components/ui/menubar.tsx(9,7): TS2742: The inferred type of 'MenubarMenu' cannot be named without a reference to '@radix-ui/react-context'.
```

**Fix:** Add explicit type annotation:
```ts
const MenubarMenu: typeof MenubarPrimitive.Menu = MenubarPrimitive.Menu;
```

### Category 6: TS18049 — Possibly null/undefined (1 error)

```
connectors/src/features/riskMetrics/hooks/useRiskMetrics.ts(124,23): TS18049: 'riskAnalysisData' is possibly 'null' or 'undefined'.
```

**Fix:** Add optional chaining or null guard at line 124.

## Part 2: Reduce `no-explicit-any` Warnings (~597 → ~300)

### Strategy

Don't fix all ~597 in one pass — too large and risky. Focus on mechanical, safe conversions.

**Tier 1 — `any` → `unknown` (safest, ~200 fixes):**
- Function params typed as `any` where the body only passes them through (no property access)
- Return types of `any` that should be `unknown` (callers handle the casting)
- Generic containers: `any[]` → `unknown[]`, `Record<string, any>` → `Record<string, unknown>` where values aren't accessed with known keys
- Catch clauses: `catch (e: any)` → `catch (e: unknown)` with `instanceof Error` guards

**Important guardrail:** Do NOT introduce `as any` casts to work around `unknown`. If converting `any` → `unknown` requires adding casts downstream, leave it as `any` — the cure is worse than the disease.

**Tier 2 — Add real types (moderate, ~100 fixes):**
- Function params where the actual type is obvious from usage (e.g., `data: any` but body does `data.holdings` — clearly a portfolio response)
- React event handlers: `(e: any)` → `(e: React.ChangeEvent<HTMLInputElement>)` etc.
- API response types that match existing schemas in `connectors/src/schemas/api-schemas.ts`

**Not fixing (leave for later):**
- Deep adapter/transformer chains where fixing one `any` requires threading types through 5+ functions
- Third-party library interop where upstream types are `any`
- Complex generic types that would require significant refactoring

### Execution approach

Process by package (smallest to largest):
1. `packages/chassis/src/` — smallest surface, fix all
2. `packages/connectors/src/` — adapters and hooks, fix obvious types
3. `packages/ui/src/` — components, fix event handlers and props

## Execution Order

1. Fix TS errors — categories 1-6 (barrel exports first, then import fixes, then type annotations)
2. Run `pnpm typecheck` — verify 0 errors
3. Fix `no-explicit-any` warnings — tiers 1-2
4. Run `pnpm lint` — check warning count
5. Run `pnpm build` — verify nothing broke

## Verification

1. `pnpm build` — passes
2. `pnpm typecheck` — 0 errors
3. `pnpm lint` — 0 errors, ~300-400 warnings (down from ~700)
4. No runtime behavior changes — all fixes are type-level only
5. No new `as any` casts introduced
