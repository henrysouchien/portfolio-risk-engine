# Fix: Combined Portfolio Value Cache Bug (v3)

## Context

The combined portfolio total value intermittently shows incorrect values when switching between scoped and combined views.

## Investigation Findings

### Backend caches: NOT the cause
- Position snapshot cache (`position_snapshot_cache.py`): Key differentiates by `consolidate` flag. Different portfolios intentionally share the raw snapshot and filter downstream. Working as designed.
- Holdings result cache (`result_cache.py`): Already includes `portfolio_name` in key. Correct.

### Frontend main path: Query key IS portfolio-scoped
- `usePortfolioSummary` passes `{ portfolioId: currentPortfolio.id }` explicitly (line 10)
- Query key becomes `['sdk', 'portfolio-summary', '{"portfolioId":"..."}']` — includes portfolio
- Switching portfolios changes the key → different cache entries

### Remaining vulnerability: `PORTFOLIO_SCOPED_SOURCES` fallback
- `portfolio-summary`, `positions-enriched`, `realized-performance` are NOT in `PORTFOLIO_SCOPED_SOURCES`
- The main hooks pass `portfolioId` explicitly, so this doesn't affect the primary path
- But any caller that omits `portfolioId` would get a cache key without it — a defensive gap

### Possible actual causes (unconfirmed)
1. **Race condition during portfolio switch**: React Query invalidation + refetch may briefly show stale data from the previous portfolio before the new data arrives
2. **Nested source cache seeding**: The `portfolio-summary` resolver seeds nested queries (`performance`, `risk-analysis`) under generic keys that may not include portfolio ID
3. **Server-side position freshness**: Provider cache returning stale positions during a specific TTL window

## Recommended Fix

### Defensive: Add missing sources to `PORTFOLIO_SCOPED_SOURCES`

**File:** `frontend/packages/connectors/src/resolver/useDataSource.ts` (line 137)

```ts
const PORTFOLIO_SCOPED_SOURCES = new Set<DataSourceId>([
  'positions',
  'positions-enriched',
  'risk-score',
  'risk-analysis',
  'risk-profile',
  'performance',
  'realized-performance',
  'portfolio-summary',
]);
```

This is a low-risk hardening — ensures that even if a caller forgets to pass `portfolioId`, the auto-injection will add it to the cache key. Won't fix the bug if the main path is already correct, but prevents a class of cache key collisions.

## Status

**Root cause not confirmed.** The main code path appears to handle portfolio scoping correctly. The bug may require live reproduction with network timing analysis to identify the exact stale data source. The `PORTFOLIO_SCOPED_SOURCES` hardening is worth applying regardless.

## Files Modified

| File | Change |
|------|--------|
| `frontend/packages/connectors/src/resolver/useDataSource.ts` | Add `portfolio-summary`, `positions-enriched`, `realized-performance` to `PORTFOLIO_SCOPED_SOURCES` |
