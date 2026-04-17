# F20 Fix: Portfolio Loading Race Condition (v3 — Codex R2 findings addressed)

## Context

**Bug**: On page load, users intermittently see a flash of "No portfolio connected" (or blank/crash state) before the real portfolio data renders. Non-deterministic — depends on React render batching timing.

**Root cause**: `PortfolioInitializer.tsx:257` has a loading guard that is too narrow:

```typescript
const isLoading = !currentPortfolio && (portfolioListQuery.isLoading || bootstrapQuery.isLoading);
```

The guard only covers the two queries' `isLoading` states. Any render where `currentPortfolio` is still `null`, neither query reports `isLoading`, and no error exists will fall through to render children — flashing "No portfolio connected."

The primary scenario: when `bootstrapQuery.queryFn` resolves, it calls `PortfolioRepository.setCurrent()` (Zustand) and then the promise settles (React Query). If these two state-management systems (`useSyncExternalStore` for Zustand vs React Query's observer) don't batch into the same React render, there is a frame where React Query shows success (`isLoading=false`) but Zustand hasn't re-rendered yet (`currentPortfolio=null`). The current guard doesn't cover this gap.

TanStack Query v5 does return optimistic fetching results on the enabling render (via `getOptimisticResult`), so the list→bootstrap transition is likely covered. But the broader vulnerability remains: the guard is not exhaustive for all intermediate states.

---

## Fix

### File: `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx`

**Change** (lines 257-259): Reorder and simplify the loading gate to be definitive.

Before:
```typescript
const isLoading = !currentPortfolio && (portfolioListQuery.isLoading || bootstrapQuery.isLoading);
const error = portfolioListQuery.error ?? bootstrapQuery.error;
const isError = !currentPortfolio && !!error;
```

After:
```typescript
const error = portfolioListQuery.error ?? bootstrapQuery.error;
const isError = !currentPortfolio && !!error;
const isLoading = !currentPortfolio && !isError;
```

**Logic**: If there's no portfolio and no error, we're still loading. Covers all intermediate states by construction — no need to enumerate individual query phases.

**Safety** (under current mount invariants):

`PortfolioInitializer` renders in two places — `ModernDashboardApp.tsx:634` (dashboard) and `AnalystApp.tsx:145` (analyst mode). Both are reached only through `AppOrchestratorModern`, which gates on the same `isAuthenticated && user && servicesReady` condition (lines 143 and 107 respectively). `useServicesReady()` returns `!!(user && services)` (`SessionServicesProvider.tsx:567`), guaranteeing `useAPIService()` is non-null in both paths. Under these shared invariants:

- Bootstrap succeeds → `PortfolioRepository.setCurrent()` → `currentPortfolio` non-null → `isLoading=false`
- Bootstrap fails → `error` set → `isError=true` → `isLoading=false`
- Portfolio list fails → `error` set → same
- Empty list → bootstrap throws `createEmptyPortfolioError()` (status 404) → `isError=true`

If this component were ever rendered outside these auth/service gates (e.g., in a test harness without mocked auth), the new guard would show loading indefinitely rather than flashing children. This is acceptable — the old behavior (rendering children with null portfolio) was worse.

### File: `frontend/packages/connectors/src/providers/__tests__/PortfolioInitializer.test.tsx`

**Add regression test** in the `guard clause` describe block. This documents the invariant: children must never render when `currentPortfolio` is null and no error exists.

```typescript
it('never renders children while currentPortfolio is null and no error exists', () => {
  // Portfolio list loaded successfully
  mockPortfolioList.data = [makePortfolio()];
  mockPortfolioList.isLoading = false;
  mockPortfolioList.isError = false;
  mockPortfolioList.error = null;

  // currentPortfolio not yet set (Zustand hasn't re-rendered)
  mockUseCurrentId.mockReturnValue(null);

  mockGetPortfolio.mockResolvedValue({
    success: true,
    portfolio_data: { holdings: [] },
    portfolio_name: 'test_portfolio',
  });

  renderInitializer();

  // Invariant: loading shown, children never exposed while portfolio is null
  expect(screen.getByTestId('loading')).toBeInTheDocument();
  expect(screen.queryByTestId('children')).not.toBeInTheDocument();
  expect(screen.queryByTestId('error')).not.toBeInTheDocument();
});
```

**Test scope note**: TanStack Query v5 returns optimistic fetching results on the enabling render (`getOptimisticResult` in `queryObserver.ts:453`), so `bootstrapQuery.isLoading` is likely `true` during this initial render under both old and new guards. This means the test passes under both implementations and serves as a **regression guard** — documenting the invariant rather than proving the specific behavioral change. The race condition's fix is validated by the logical argument (the new guard is exhaustive by construction) and by manual testing (hard-refresh verification). Unit tests cannot reliably reproduce cross-state-manager batching timing.

---

## Files Modified

| File | Change |
|------|--------|
| `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx` | Reorder `isLoading`/`isError` to close race gap (3-line change) |
| `frontend/packages/connectors/src/providers/__tests__/PortfolioInitializer.test.tsx` | Add regression test for the gap state |

## Verification

1. **Unit tests**: `cd frontend && pnpm test -- --run packages/connectors/src/providers/__tests__/PortfolioInitializer.test.tsx`
2. **Full connectors test suite**: `cd frontend && pnpm test -- --run packages/connectors/`
3. **Type check**: `cd frontend && pnpm tsc --noEmit`
4. **Manual**: Start the app (`services-mcp` → `risk_module` + `risk_module_frontend`), open `localhost:3000`, hard-refresh several times — should never flash "No portfolio connected"
