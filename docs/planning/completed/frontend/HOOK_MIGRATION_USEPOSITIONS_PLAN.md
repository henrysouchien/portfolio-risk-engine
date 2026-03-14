# Hook Migration: usePositions → useDataSource
**Status:** DONE

## Context

16/18 data-fetch hooks have been migrated to the `useDataSource` pattern (Batches A-D). `usePositions` was deferred because its resolver reads raw portfolio data from the Zustand store, while the hook calls `api.getPositionsHoldings()` + `PositionsAdapter.transform()` to get enriched data (day changes, risk metrics, sparklines, etc.).

**Problem**: The existing `positions` resolver (`registry.ts:128`) reads from `context.currentPortfolio` — raw store data with fields like `market_value`, `holdings[]` as plain arrays. The hook needs enriched `PositionsData` from the API + adapter (fields like `dayChange`, `beta`, `riskScore`, `weight`, `trend`). These are different shapes.

**Why not rewrite the existing resolver**: 5 downstream resolvers (`trading-analysis`, `income-projection`, `tax-harvest`, `portfolio-news`, `events-calendar`) depend on the raw `positions` resolver and read fields like `holding.market_value` that don't exist on the enriched shape (it uses `holding.value` instead). Changing the shape would break them.

**Solution**: Add a new `positions-enriched` data source that calls the API + adapter. Migrate `usePositions` to `useDataSource('positions-enriched')`. Leave the raw `positions` resolver untouched.

## Implementation Steps

### Step 1: Add `positions-enriched` to type system

**File:** `frontend/packages/chassis/src/catalog/types.ts`

1. Add `| 'positions-enriched'` to the `DataSourceId` union (after `'positions'` at line 20)
2. Add to `SDKSourceOutputMap`: `'positions-enriched': PositionsEnrichedSourceData`
3. Add to `SDKSourceParamsMap`: `'positions-enriched': Record<string, never>` (no params — `api.getPositionsHoldings()` takes no arguments)

Define `PositionsEnrichedSourceData` in types.ts to match `PositionsData` from the adapter:
```typescript
export interface PositionsEnrichedSourceData {
  summary: {
    totalValue: number;
    lastUpdated: string;
  };
  holdings: Array<{
    id: string;
    ticker: string;
    name: string;
    value: number;
    shares: number;
    weight: number;
    avgCost?: number;
    currentPrice?: number;
    totalReturn?: number;
    totalReturnPercent?: number;
    type?: string;
    sector?: string;
    assetClass?: string;
    isProxy: boolean;
    dayChange?: number;
    dayChangePercent?: number;
    trend?: number[];
    volatility?: number;
    alerts?: number;
    alertDetails?: Array<{ severity: string; message: string }>;
    riskScore?: number;
    beta?: number;
    riskPct?: number;
    maxDrawdown?: number;
  }>;
}
```

### Step 2: Add descriptor + register in all 3 places

**File:** `frontend/packages/chassis/src/catalog/descriptors.ts`

Add `positionsEnrichedDescriptor` (modeled on existing `positionsDescriptor` at line 19):

```typescript
const positionsEnrichedDescriptor = defineDescriptor({
  id: 'positions-enriched',
  label: 'Enriched Portfolio Positions',
  category: 'portfolio',
  params: [],
  fields: [
    { name: 'summary', type: 'object', description: 'Portfolio summary with total value and last updated timestamp.' },
    { name: 'holdings', type: 'array', description: 'Enriched portfolio holdings with risk metrics, day changes, and trends.' },
  ],
  flagTypes: [{ name: 'stale_positions', description: 'Positions may be outdated.', severity: 'warning' }],
  refresh: {
    defaultTTL: 300,
    staleWhileRevalidate: true,
    invalidatedBy: ['portfolio-data-invalidated', 'all-data-invalidated'],
  },
  loading: {
    strategy: 'lazy',
    priority: 5,
  },
  errors: {
    ...DEFAULT_ERRORS,
    fallbackToStale: true,
  },
});
```

**Three registration sites** (all in descriptors.ts):
1. Add to `descriptorList` array (~line 1114)
2. Add to `sdkDescriptorMap` object (~line 1148): `'positions-enriched': positionsEnrichedDescriptor,`
3. Add to `ensureFieldConformance()` object (~line 1205): `'positions-enriched': true,`

**Note on loading strategy**: Use `strategy: 'lazy'` (not `'eager'`). The scheduler prefetches all eager descriptors on mount (`scheduler.ts:94`). Since `positions-enriched` hits the API, we don't want it prefetched on every page load — only when the positions view mounts. This avoids the stale-cache risk where `CacheCoordinator` invalidates the old `positionsHoldingsKey()` but not the new SDK key.

### Step 3: Update descriptor test count

**File:** `frontend/packages/chassis/src/catalog/__tests__/descriptors.test.ts`

Update the count assertion from 31 → 32:
```typescript
expect(dataCatalog.list()).toHaveLength(32);
expect(sdkDescriptors).toHaveLength(32);
```

### Step 4: Add resolver

**File:** `frontend/packages/connectors/src/resolver/registry.ts`

Add new resolver entry after the existing `positions` resolver (after line 150):

```typescript
'positions-enriched': async (_params, context) => {
  const { api } = context.services;
  const payload = await api.getPositionsHoldings();
  return PositionsAdapter.transform(payload);
},
```

Import `PositionsAdapter` from `../adapters/PositionsAdapter` at the top of the file.

### Step 5: Migrate the hook

**File:** `frontend/packages/connectors/src/features/positions/hooks/usePositions.ts`

Replace the 57-line implementation with a thin `useDataSource` wrapper. Follow the `useSmartAlerts` pattern (auto-fetch, no mutation):

```typescript
import { useMemo } from 'react';
import { useCurrentPortfolio } from '@risk/chassis';
import type { PositionsData } from '../../../adapters/PositionsAdapter';
import { useDataSource } from '../../../resolver/useDataSource';

export const usePositions = () => {
  const currentPortfolio = useCurrentPortfolio();
  const resolved = useDataSource('positions-enriched');

  return useMemo(
    () => ({
      data: (resolved.data ?? undefined) as PositionsData | undefined,
      loading: resolved.loading,
      isLoading: resolved.loading,
      isRefetching: resolved.isRefetching,
      error: resolved.error?.userMessage ?? null,
      refetch: resolved.refetch,
      hasData: !!resolved.data,
      hasError: !!resolved.error,
      hasPortfolio: !!currentPortfolio,
      currentPortfolio,
      clearError: () => {},
    }),
    [resolved, currentPortfolio]
  );
};
```

Key points:
- Return shape is **identical** to current hook — no consumer changes needed
- `data` uses `resolved.data ?? undefined` (not `null`) to match current behavior where `data` is `undefined` before resolution
- `useDataSource` handles TanStack Query, caching, stale-while-revalidate
- `clearError` stays as no-op (errors clear on successful refetch, same as before)

**`refetch()` and `await` (pre-existing pattern)**: `useDataSource.refetch` returns `void` (not `Promise`), while `HoldingsViewModernContainer.tsx:232` does `await refetch()`. This is a pre-existing pattern across ALL migrated hooks — `useSmartAlerts`, `useHedgingRecommendations`, `useStressTest`, `useMetricInsights`, `useMarketIntelligence`, and their tests all `await` the void refetch. It works because `await undefined` resolves immediately, and React Query's state update triggers a re-render with fresh data. This is not a regression from this migration — it's consistent with all 16 already-migrated hooks. If we want to fix this globally, `useDataSource` should return `query.refetch()` instead of `void query.refetch()`, but that's a separate cleanup.

**Retry behavior change (accepted)**: Current hook suppresses retries for "validation"/"contract" errors via custom retry function. `useDataSource` uses numeric retry from descriptor (`DEFAULT_ERRORS`). This is an intentional simplification consistent with all other migrated hooks. `classifyError` already marks validation errors as non-retryable. Contract errors are rare and the TTL prevents excessive retries.

**Error message format change (accepted)**: Current hook exposes raw `error.message`. Migrated hook exposes `error?.userMessage` from `DataSourceError`. The user-facing message may differ slightly (e.g., "Received an unexpected data format from the server." instead of raw backend text). This is consistent with all other migrated hooks and is the intended behavior — user-friendly messages instead of raw errors.

### Step 6: Update tests

**File:** `frontend/packages/connectors/src/features/positions/__tests__/usePositions.test.tsx`

The resolver calls `context.services.api.getPositionsHoldings()`, so mocking `useSessionServices` to return `{ api: mockApi }` still intercepts the call. Changes:

1. **Remove** direct `PositionsAdapter.transform` mock — the resolver imports and calls the real adapter. Mock the API return to include proper raw data so the real adapter can transform it.
2. **Adjust error assertions** — errors are now `DataSourceError` objects with `.userMessage`, not plain strings. The hook maps `resolved.error?.userMessage ?? null`, so `result.current.error` is still a string or null.
3. **Keep** all 6 existing test cases with adjusted mock wiring.
4. **Add** a test for `data` being `undefined` (not `null`) before query resolves — ensures the `?? undefined` mapping works.

## Consumers

Two UI components consume `usePositions`:
1. **`HoldingsViewModernContainer.tsx`** — reads `data`, `loading`, `error`, `refetch`, `hasData`, `hasPortfolio`, `currentPortfolio`. Awaits `refetch()` (pre-existing void-await pattern).
2. **`ScenarioAnalysisContainer.tsx:393`** — reads `data` only (destructured as `positionsData`).

Both work unchanged with the migrated hook.

## Backward Compatibility

- Hook return shape is unchanged — all consumers work without modification
- `refetch()` follows the same void-return pattern as all 16 other migrated hooks
- `data` is `undefined` (not `null`) before resolution, matching current behavior
- Error messages use `DataSourceError.userMessage` (user-friendly) instead of raw `error.message` — consistent with all other migrated hooks
- Raw `positions` resolver untouched — all 5 downstream resolvers unaffected
- `PositionsAdapter` untouched — just called from a different site (resolver instead of hook)

## Files Changed (5)

| File | Change | ~Lines |
|------|--------|--------|
| `frontend/packages/chassis/src/catalog/types.ts` | Add `positions-enriched` to DataSourceId, output map, params map | +25 |
| `frontend/packages/chassis/src/catalog/descriptors.ts` | Add descriptor + register in descriptorList, sdkDescriptorMap, ensureFieldConformance | +35 |
| `frontend/packages/chassis/src/catalog/__tests__/descriptors.test.ts` | Update count 31→32 | +1 |
| `frontend/packages/connectors/src/resolver/registry.ts` | Add `positions-enriched` resolver (4 lines) + import | +5 |
| `frontend/packages/connectors/src/features/positions/hooks/usePositions.ts` | Replace with thin `useDataSource` wrapper | 57→28 (-29) |

**Test update**: `usePositions.test.tsx` — mock adjustments + new assertion

**Unchanged**: All downstream resolvers, `PositionsAdapter.ts`, `CacheCoordinator.ts`, backend

## Existing Code Reused

- `useDataSource` hook (`resolver/useDataSource.ts`) — standard data-fetch wrapper
- `PositionsAdapter.transform()` (`adapters/PositionsAdapter.ts`) — moved from hook to resolver
- `api.getPositionsHoldings()` — existing API method, unchanged
- `positionsDescriptor` pattern (`descriptors.ts:19`) — template for new descriptor
- `useSmartAlerts` pattern (`hooks/useSmartAlerts.ts`) — template for thin wrapper

## Verification

1. `cd frontend && npx tsc --noEmit` — TypeScript compiles with 0 errors in both chassis and connectors
2. `cd frontend && npx vitest run packages/chassis/src/catalog` — descriptor test passes (count=32)
3. `cd frontend && npx vitest run packages/connectors/src/features/positions` — all usePositions tests pass
4. `cd frontend && npx vitest run packages/connectors/src/resolver` — resolver tests pass
5. Verify no other files import from the old usePositions internals (no `useQuery`/`HOOK_QUERY_CONFIG` direct usage)
