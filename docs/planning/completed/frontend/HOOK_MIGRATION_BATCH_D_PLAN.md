# Hook Migration Batch D — useWhatIfAnalysis
**Status:** DONE

## Context

Batch D of the `useDataSource` hook migration. Batches A (7), B (4), C (4) are done — 15/18 hooks migrated. This batch migrates the last complex hook: `useWhatIfAnalysis` (499 lines → ~180 lines). After this, only `useScenarioHistory` (CRUD/mutation pattern, doesn't fit `useDataSource`) and `usePositions` (needs resolver rewrite) remain — both deferred.

## Scope

| Hook | Lines | Pattern | Infrastructure |
|------|-------|---------|---------------|
| useWhatIfAnalysis | 499 → ~180 | Manual trigger + local input state | Reuses existing `what-if` resolver + descriptor (updates needed) |

**useScenarioHistory is NOT included** — it's 90% mutations (save run, clear history) + 10% query. Only 3 fields used by its single consumer. The `useDataSource` pattern doesn't fit mutations. Defer.

## Key Design Decisions

1. **Update existing `what-if` resolver** to route through `WhatIfAnalysisAdapter` (same Batch C pattern as stock-analysis/optimization)
2. **`_runId` manual trigger** replaces `setTimeout(() => refetch(), 0)` hack
3. **Input management stays local** — 5 useState hooks + 9 callbacks (~120 lines) remain in the hook
4. **Remove `dependsOn: ['positions']`** from descriptor — what-if uses `portfolio.id` not positions data, the dependency would unnecessarily block execution
5. **`DataSourceError` in resolver** — bypasses classifyError rewriting (Batch C pattern)
6. **No new DataSourceId** — `what-if` already exists
7. **Descriptor `retryable: false`** — `useDataSource` reads retry config from descriptor (`descriptor.errors.retryable`), NOT from `DataSourceError.retryable`. The current hook's custom retry logic (no-retry for "Portfolio validation"/"scenario failed") is lost. Fix: set `errors: { ...DEFAULT_ERRORS, retryable: false, maxRetries: 0 }` in the what-if descriptor. What-if is a manual-trigger hook — retrying automatically after failure makes no sense.
8. **`guardedRefetch`** — Expose `guardedRefetch` (not raw `refetch`) so callers can't fire the resolver with undefined params. Same pattern as `useBacktest`/`useStressTest`.
9. **No `_runId` in descriptor params** — `_runId` is an internal cache-busting trigger, not a user-facing param. Other manual-trigger descriptors (backtest, stress-test, monte-carlo) don't list it in descriptor params. Only add it to `SDKSourceParamsMap` in `types.ts`.

## Implementation Steps

### Step 1: Update `WhatIfSourceData` type

**File:** `frontend/packages/chassis/src/catalog/types.ts`

Current (lines 194-198):
```typescript
export interface WhatIfSourceData {
  scenario: Record<string, unknown>;
  summary?: string;
  formatted_report?: string;
}
```

New — match `WhatIfAnalysisData` from adapter:
```typescript
export interface WhatIfSourceData {
  success?: boolean;
  scenario_results: Record<string, unknown>;
  summary: Record<string, unknown>;
  portfolio_metadata: Record<string, unknown>;
  risk_limits_metadata: Record<string, unknown>;
}
```

Add `_runId` to `SDKSourceParamsMap['what-if']` (line 530):
```typescript
'what-if': { portfolioId?: string; scenario?: Record<string, unknown>; _runId?: number };
```

### Step 2: Update descriptor

**File:** `frontend/packages/chassis/src/catalog/descriptors.ts` (lines 339-373)

Changes:
- **fields**: Change from `scenario/summary/formatted_report` to `scenario_results/summary/portfolio_metadata/risk_limits_metadata` (all `type: 'object'`)
- **loading.dependsOn**: Remove `['positions']` → `[]`
- **errors**: Change from `DEFAULT_ERRORS` to `{ ...DEFAULT_ERRORS, retryable: false, maxRetries: 0 }` — what-if is manual-trigger, automatic retry after failure makes no sense
- **Do NOT add `_runId` to descriptor params** — it's an internal cache-busting trigger (backtest/stress-test/monte-carlo descriptors don't list it either)

### Step 3: Update `what-if` resolver

**File:** `frontend/packages/connectors/src/resolver/registry.ts` (lines 430-449)

Route through `WhatIfAnalysisAdapter` + throw `DataSourceError`:

```typescript
'what-if': async (params, context) => {
  const portfolio = requirePortfolio('what-if', getPortfolio(params?.portfolioId, context.currentPortfolio));
  const scenario = params?.scenario ?? {};
  const { manager, unifiedAdapterCache } = context.services;

  const result = await manager.analyzeWhatIfScenario(portfolio.id!, { scenario });
  if (result.error || !result.whatIfAnalysis) {
    throw new DataSourceError({
      category: 'unknown',
      sourceId: 'what-if',
      retryable: false,
      userMessage: result.error ?? 'What-if analysis returned no data',
    });
  }

  const adapter = AdapterRegistry.getAdapter(
    'whatIfAnalysis',
    [portfolio.id ?? 'default'],
    (cache) => new WhatIfAnalysisAdapter(cache, portfolio.id ?? undefined),
    unifiedAdapterCache
  );

  return adapter.transform(
    result.whatIfAnalysis as Parameters<typeof adapter.transform>[0]
  ) as SDKSourceOutputMap['what-if'];
},
```

New import: `import { WhatIfAnalysisAdapter } from '../adapters/WhatIfAnalysisAdapter';`

### Step 4: Rewrite hook

**File:** `frontend/packages/connectors/src/features/whatIf/hooks/useWhatIfAnalysis.ts`

Structure (499 → ~180 lines):
- **Data-fetching**: `useDataSource('what-if', resolverParams, { enabled })` replaces `useQuery` + adapter + manager calls
- **Manual trigger**: `runScenario()` → sets `scenarioParams` + `runPortfolioId` + `_runId` → `resolverParams` changes → `useDataSource` auto-fetches
- **Input management**: All 5 useState + 9 callbacks preserved unchanged
- **Portfolio change reset**: New `useEffect` clears scenario state when portfolioId changes
- **`runPortfolioId` guard**: Captures portfolio at trigger time, prevents stale-portfolio fetches (established in Batch B)
- **`guardedRefetch`**: Wrap `resolved.refetch` in a guard that checks `resolverParams` is non-null before calling. Expose as `refetch` and `refreshWhatIfAnalysis`. Same pattern as `useBacktest`/`useStressTest`.
- Returns all 23 existing fields with same names/types:
  `data`, `loading`, `isLoading`, `isRefetching`, `error`, `refetch`, `refreshWhatIfAnalysis`, `hasData`, `hasError`, `hasPortfolio`, `currentPortfolio`, `clearError`, `scenarioId`, `runScenario`, `inputMode`, `setInputMode`, `weightInputs`, `deltaInputs`, `addAssetInput`, `removeAssetInput`, `updateAssetName`, `updateAssetValue`, `runScenarioFromInputs`

### Step 5: Update tests

**File:** `frontend/packages/connectors/src/features/whatIf/__tests__/useWhatIfAnalysis.test.tsx`

- Remove mocks for `AdapterRegistry`, `useSessionServices`, `manager.analyzeWhatIfScenario`
- Add mock for `useDataSource` from `'../../../resolver'`
- Keep pure input management tests unchanged (local state, no useDataSource): `addAssetInput`, `removeAssetInput`, `updateAssetName`, `updateAssetValue`, `setInputMode`, `runScenarioFromInputs` empty-input alert test
- Rewrite data-fetching tests to verify `useDataSource` params (mock `useDataSource` from `'../../../resolver'`)
- Rewrite `runScenarioFromInputs` positive-path test — currently asserts `manager.analyzeWhatIfScenario` was called; after migration, assert `useDataSource` was called with correct scenario params (this test crosses the local→data-fetch boundary)
- Add new tests: `_runId` in params, portfolio-change reset, `enabled: false` before first trigger, `guardedRefetch` no-op when params null
- **Note on resolver coverage**: `core.test.ts` mocks the registry, so resolver functions have no direct unit test. This is the same pattern as all prior batches (A/B/C) — resolver correctness is verified via Chrome live testing + typecheck, not unit tests. Acceptable tradeoff for this migration.

## Behavioral Changes

| BC | Description | Impact |
|----|-------------|--------|
| BC-1 | `setTimeout(() => refetch(), 0)` → `_runId` state trigger | More reliable, no race condition. Same UX. |
| BC-2 | Adapter transform moves from hook to resolver; `WhatIfSourceData` type + descriptor fields change from old shape (`scenario/summary/formatted_report`) to adapter output shape (`scenario_results/summary/portfolio_metadata/risk_limits_metadata`) | Source-schema change at the catalog layer. Consumers using `useWhatIfAnalysis` see identical data (adapter output was already the hook's return shape). But any code reading the catalog descriptor fields will see different field names. |
| BC-3 | Cache key: `whatIfAnalysisKey(portfolioId, scenarioId)` → `['sdk', 'what-if', serialized(params)]` | Old cached data orphaned. Negligible — manual trigger hook. |
| BC-4 | `dependsOn: ['positions']` removed from descriptor | What-if no longer waits for positions to load. Improvement — was unnecessary. |
| BC-5 | Custom per-error retry logic lost (no-retry for "Portfolio validation"/"scenario failed") | `useDataSource` reads retry from descriptor, NOT from `DataSourceError.retryable`. Fix: descriptor sets `retryable: false, maxRetries: 0`. This is stricter than before (old hook retried network errors 2×) but appropriate for a manual-trigger hook — user can re-run manually. |
| BC-6 | Portfolio change now clears scenario state | Improvement — prevents stale scenario after portfolio switch. |
| BC-7 | Error goes through `classifyError` | Mitigated: resolver throws `DataSourceError` directly, bypasses rewriting. |
| BC-8 | `scenarioId` derived from `_runId` state instead of independent useState | Same format, different source. No consumer impact. |
| BC-9 | `refetch`/`refreshWhatIfAnalysis` guarded — no-op when params null | Improvement. Prevents accidental resolver call with undefined params before first run or after portfolio reset. |

## Files Changed (Expected: ~5)

1. `chassis/src/catalog/types.ts` — Update `WhatIfSourceData` + add `_runId` to params
2. `chassis/src/catalog/descriptors.ts` — Update fields, params, remove `dependsOn`
3. `connectors/src/resolver/registry.ts` — Update resolver + add adapter import
4. `connectors/src/features/whatIf/hooks/useWhatIfAnalysis.ts` — Rewrite (499 → ~180)
5. `connectors/src/features/whatIf/__tests__/useWhatIfAnalysis.test.tsx` — Rewrite test mocks

## Verification

1. `cd frontend && pnpm typecheck` — zero TS errors
2. `cd frontend && pnpm test -- useWhatIfAnalysis.test` — all tests pass
3. `cd frontend && pnpm test -- descriptors.test` — descriptor count unchanged (31)
4. `cd frontend && pnpm build` — build succeeds
5. Chrome verify:
   - Scenario Analysis → What-If tab → add assets → Run → verify results render
   - Stock Lookup → "Portfolio Fit" what-if → verify data renders
   - Switch portfolio → verify scenario state resets
