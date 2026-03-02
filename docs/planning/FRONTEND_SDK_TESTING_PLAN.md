# Frontend SDK Testing

**Date**: 2026-03-01
**Status**: Complete (Phase 1 committed `5d490407`, Phase 2 committed `6c59f7e7`)

## Context

The frontend SDK has Vitest configured but only 1 test file (`formatting.test.ts`). The TODO calls for coverage of: classifyError, DataCatalog, conformance, useDataSource, and feature hooks. Pure function tests need zero new deps; hook tests need React testing infrastructure.

**Prerequisite**: Vite 7 requires Node 20.19+. Verify `node -v` before running tests.

## Codex R1 Findings (addressed below)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | HIGH | DataCatalog "cycle" test unreachable — `register()` rejects unregistered deps before cycle check runs | Replace with self-dependency test; add `makeDescriptor()` test helper |
| 2 | HIGH | Conformance test says "no duplicates across any descriptor" but conformance checks per-descriptor uniqueness | Fix test description to per-descriptor uniqueness |
| 3 | HIGH | `SessionServicesContext` not exported — `renderWithProviders` can't inject mock services | Use `vi.mock` for `useSessionServices` instead of context injection |
| 4 | MEDIUM | `resolveWithCatalog()` in core.ts has timeout/abort/classification logic — not covered | Add ~4 tests for resolveWithCatalog (mock resolveDataSource) |
| 5 | MEDIUM | useDataSource missing branches: `'minimal'` quality, `_metadata.missingFields`, stale-during-refetch | Add tests for these paths |
| 6 | MEDIUM | `pnpm test` may fail on startup if Node version too old (Vite 7 requires 20.19+) | Document prerequisite |
| 7 | LOW | DataCatalog test descriptors need all required fields (params/fields/flagTypes/refresh/loading/errors) | Add `makeDescriptor()` factory helper |

## Codex R2 Findings (addressed below)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | MEDIUM | `resolveWithCatalog` missing abort-after-start branch (event listener path) | Added 5th test for mid-flight abort |
| 2 | MEDIUM | `useDataSource` plan doesn't cover DataSourceError pass-through branch | Added explicit pass-through test |
| 3 | LOW | Self-dependency should pin to "unregistered source" error, not cycle error | Pinned to exact error semantics |

## Phase 1: Pure Function Tests (no new deps, no config changes)

Same pattern as `formatting.test.ts`. Prerequisite: Node 20.19+.

### Test Helper: `makeDescriptor()`

Create a `makeDescriptor(id, overrides)` factory that returns a valid descriptor with all required fields (params, fields, flagTypes, refresh, loading, errors) defaulted. Use real `DataSourceId` values from the union type. Used by DataCatalog tests.

### 1.1 `chassis/src/errors/__tests__/classifyError.test.ts` (~15 tests)

Test all 12 classification paths in `classifyError.ts`:
- Pass-through: `DataSourceError` instance returned as-is
- HTTP status: 401/403→auth, 404→not_found, 429→rate_limit, 500+→server, 206→partial, 408/504→timeout
- Error codes: ETIMEDOUT/ECONNABORTED→timeout, ENOTFOUND/ECONNRESET/EAI_AGAIN→network
- Error names: AbortError→timeout, TypeError→network, ValidationError→validation
- Message regex: /validation/i, /invalid/i → validation
- Category field: `category='partial'`→partial, `category='validation'`→validation
- Default fallback: unknown category, `retryableDefault` param honored
- Edge cases: string error, null error, plain object

### 1.2 `chassis/src/catalog/__tests__/DataCatalog.test.ts` (~12 tests)

Create fresh `DataCatalog` instances with `makeDescriptor()` helper:
- `register()` + `list()`: registers and lists
- `register()` duplicate → throws
- `register()` missing dependency → throws "depends on unregistered source"
- `register()` self-dependency → throws "depends on unregistered source" (R1 fix: self-ref hits unregistered-dep check before cycle check; R2 fix: pinned to exact error semantics)
- `describe()` known → returns descriptor
- `describe()` unknown → throws
- `has()` → true/false
- `listByCategory()` → filters
- `search()` matches across id, label, category, param name, field name, flag name
- `search('')` → returns all
- `search()` case insensitive

### 1.3 `chassis/src/catalog/__tests__/descriptors.test.ts` (~5 tests)

Structural validation of the real 18 production descriptors:
- All 18 registered without error (import `dataCatalog`)
- `getDefaultParams()` returns defaults when no overrides
- `getDefaultParams()` merges overrides
- Every descriptor has non-empty `fields` array
- Every descriptor has valid `category`

### 1.4 `chassis/src/catalog/__tests__/conformance.test.ts` (~2 tests)

- `assertCatalogConformance()` returns true for production catalog
- No duplicate field names **within each descriptor** (per-descriptor uniqueness, R1 fix)

### 1.5 `connectors/src/resolver/__tests__/core.test.ts` (~9 tests)

Pure function tests for `serializeParams`, `buildDataSourceQueryKey`, and `resolveWithCatalog` in `core.ts`:

**serializeParams + buildDataSourceQueryKey** (~5 tests):
- `serializeParams` sorts keys deterministically
- `serializeParams` handles undefined/null → `'{}'`
- `serializeParams` handles nested objects (recursive sort)
- `buildDataSourceQueryKey` returns `['sdk', sourceId, serialized]`
- Same params → same key (stability)

**resolveWithCatalog** (~5 tests, R1 fix — mock `resolveDataSource` via `vi.mock`):
- Resolves successfully when resolver returns data
- Throws classified timeout error when descriptor timeout expires
- Throws classified error when signal is pre-aborted
- Throws classified error when signal aborts mid-flight (abort event listener path, `core.ts:60-67`) (R2 fix)
- Throws classified error when resolver rejects (error classification pass-through)

**Phase 1 total: ~44 tests, 5 files, 0 new deps.**

## Phase 2: Hook Tests (needs deps + config)

**Status**: Planning (R1 reviewed, fixes applied)

### Codex R1 Findings (addressed below)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | HIGH | Missing dependency-gating test — `useDataSource` gates on `dependsOn` (line 82-85) but no test covers it | Added test 12: use `risk-score` (depends on `positions`), assert resolveWithCatalog not called until positions seeded |
| 2 | MEDIUM | Missing stale-quality branch coverage — hook has explicit stale logic (line 119) | Added tests 9-10: isFetching+data→stale, error+fallbackToStale+data→stale |
| 3 | HIGH | useRiskScore missing call args assertion — only validates returned fields | Added tests 6-7: assert `useDataSource` called with correct sourceId and portfolioId |
| 4 | LOW | `gcTime: 0` causes brittle cache-dependent tests | Changed to `gcTime: Infinity` |
| 5 | LOW | `environmentMatchGlobs` deprecated | Keeping with note — `test.projects` doesn't inherit `resolve.dedupe` |

### Lessons from First Attempt

These issues were discovered during a coding attempt without a reviewed plan:

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | `useQueryClient()` throws "No QueryClient set" in tests | pnpm monorepo: test helper at `frontend/test/` and source at `packages/connectors/src/` resolve `@tanstack/react-query` to different module instances | Add `resolve.dedupe: ['react', 'react-dom', '@tanstack/react-query']` to vite.config.ts |
| 2 | `test.projects` breaks dedupe | Vitest 3.x `test.projects` entries do NOT inherit `resolve.dedupe` from parent config | Use `environmentMatchGlobs` instead (deprecated but functional) |
| 3 | Error tests timeout at 1s | Positions descriptor has `maxRetries: 2` which overrides test QueryClient's `retry: false` | Set `retryDelay: 0` in test QueryClient — retries happen instantly |
| 4 | useRiskScore mock path wrong | `vi.mock('../../../../providers/SessionServicesProvider')` from `riskScore/__tests__/` resolves outside `src/` | Mock `useDataSource` directly via `vi.mock('../../../resolver')` instead of mocking the full chain |
| 5 | `@risk/chassis` barrel mock duplication concern | Mocking barrel with `importOriginal` + spread is safe — preserves real class refs for `instanceof` | Use `vi.mock('@risk/chassis', importOriginal)`, spread actual, replace only `useCurrentPortfolio` |

### 2.1 Install dependencies

```bash
cd frontend && pnpm add -D @testing-library/react @testing-library/jest-dom jsdom
```

### 2.2 Configure vitest

Add to `frontend/vite.config.ts`:

1. **`resolve.dedupe`** at top level (CRITICAL — prevents duplicate module instances):
```typescript
resolve: {
  dedupe: ['react', 'react-dom', '@tanstack/react-query'],
},
```

2. **`test` block**:
```typescript
test: {
  include: ['packages/*/src/**/*.test.{ts,tsx}'],
  setupFiles: ['./test/setup.ts'],
  environmentMatchGlobs: [
    ['packages/*/src/**/*.test.tsx', 'jsdom'],
  ],
},
```

### 2.3 Create test infrastructure

**`frontend/test/setup.ts`** — Extends vitest expect with jest-dom matchers:
```typescript
import '@testing-library/jest-dom/vitest';
```

**`frontend/test/helpers/renderWithProviders.tsx`** — QueryClient wrapper for hook tests. Does NOT provide `SessionServicesContext` (context is not exported from SessionServicesProvider.tsx line 174).

- `createTestQueryClient()`: `retry: false`, `retryDelay: 0` (instant retries when per-query retry overrides), `gcTime: Infinity` (R1 fix: `gcTime: 0` causes brittle cache-dependent tests)
- `renderHookWithQuery()`: wraps `renderHook` with `QueryClientProvider`, returns `{ ...result, queryClient }`

### 2.4 `connectors/src/resolver/__tests__/useDataSource.test.tsx` (11 tests)

**Mocking strategy** (3 modules, all `vi.mock` paths relative to test file at `resolver/__tests__/`):

| Module | Mock path | Strategy |
|--------|-----------|----------|
| SessionServicesProvider | `../../providers/SessionServicesProvider` | Full mock → `{ useSessionServices: vi.fn() }` returning fake Services with spy eventBus |
| @risk/chassis | `@risk/chassis` | `importOriginal` + spread, replace only `useCurrentPortfolio` with `vi.fn()` |
| resolver core | `../core` | `importOriginal` + spread, replace only `resolveWithCatalog` with `vi.fn()` |

**Tests**:
1. Returns loading=true initially (never-resolving promise)
2. Returns data after resolver resolves (quality='complete', error=null)
3. Returns classified error on rejection (`new Error()` → `DataSourceError`)
4. Passes through existing DataSourceError as-is (same instance, category preserved)
5. Derives flags from `_metadata.warnings` (2 warnings → 2 Flag objects)
6. Quality is 'partial' when `data_availability.data_quality='partial'`
7. Quality is 'partial' when `data_availability.data_quality='minimal'`
8. Quality is 'partial' when `_metadata.missingFields` is non-empty
9. Quality is 'stale' during refetch when data exists (`isFetching && data`) (R1 fix)
10. Quality is 'stale' when error + fallbackToStale + existing data (R1 fix)
11. Quality is 'error' when error + no fallback data
12. Disabled when dependencies not in cache — use `risk-score` (depends on `positions`), assert `resolveWithCatalog` not called until positions data seeded in QueryClient cache (R1 fix)
13. Subscribes to invalidation events (eventBus.on called with `'portfolio-data-invalidated'` and `'all-data-invalidated'`)
14. Refetch is callable (no throw)

### 2.5 `connectors/src/features/riskScore/__tests__/useRiskScore.test.tsx` (5 tests)

**Mocking strategy** (2 modules, paths relative to `riskScore/__tests__/`):

| Module | Mock path | Strategy |
|--------|-----------|----------|
| @risk/chassis | `@risk/chassis` | `importOriginal` + spread, replace only `useCurrentPortfolio` |
| resolver barrel | `../../../resolver` | Full mock → `{ useDataSource: vi.fn() }` |

Uses plain `renderHook` (no QueryClientProvider — `useDataSource` is fully mocked).
Uses `createResolvedData(overrides)` factory returning valid `ResolvedData<unknown>` with all fields defaulted.

**Tests**:
1. `hasPortfolio=false` when no portfolio (`useCurrentPortfolio` returns null)
2. `hasData=true` when data resolves
3. Maps `error.userMessage` to error string field
4. `refreshRiskScore` calls refetch (spy called)
5. Passes through loading and isRefetching
6. Calls `useDataSource('risk-score', { portfolioId })` with correct args when portfolio present (R1 fix)
7. Calls `useDataSource('risk-score', { portfolioId: undefined })` when no portfolio (R1 fix)

**Phase 2 total: 21 tests, 2 test files + 2 infrastructure files + 2 config changes.**

## Files to Create

| File | Phase | Env |
|------|-------|-----|
| `chassis/src/errors/__tests__/classifyError.test.ts` | 1 (done) | node |
| `chassis/src/catalog/__tests__/DataCatalog.test.ts` | 1 (done) | node |
| `chassis/src/catalog/__tests__/descriptors.test.ts` | 1 (done) | node |
| `chassis/src/catalog/__tests__/conformance.test.ts` | 1 (done) | node |
| `connectors/src/resolver/__tests__/core.test.ts` | 1 (done) | node |
| `frontend/test/setup.ts` | 2 (done) | — |
| `frontend/test/helpers/renderWithProviders.tsx` | 2 (done) | — |
| `connectors/src/resolver/__tests__/useDataSource.test.tsx` | 2 (done) | jsdom |
| `connectors/src/features/riskScore/__tests__/useRiskScore.test.tsx` | 2 (done) | jsdom |

## Files to Modify

| File | Change |
|------|--------|
| `frontend/package.json` | Add 3 devDependencies (Phase 2) |
| `frontend/vite.config.ts` | Add `resolve.dedupe` + `test` block (Phase 2) |

## Key Source Files

- `chassis/src/errors/classifyError.ts` — 12 classification paths, pure function
- `chassis/src/errors/DataSourceError.ts` — Error class used by classifyError
- `chassis/src/catalog/DataCatalog.ts` — Registry class with cycle detection
- `chassis/src/catalog/descriptors.ts` — 18 descriptors, `getDefaultParams()`, `dataCatalog` singleton; positions descriptor: `maxRetries: 2`, `invalidatedBy: ['portfolio-data-invalidated', 'all-data-invalidated']`
- `chassis/src/catalog/conformance.ts` — `assertCatalogConformance()` per-descriptor field uniqueness check
- `connectors/src/resolver/core.ts` — `serializeParams()`, `buildDataSourceQueryKey()`, `resolveWithCatalog()`
- `connectors/src/resolver/useDataSource.ts` — Foundation hook with dependency resolution, quality, flags
- `connectors/src/resolver/index.ts` — Barrel exports `useDataSource` (mocked in useRiskScore tests)
- `connectors/src/features/riskScore/hooks/useRiskScore.ts` — Representative feature hook (thin wrapper)
- `connectors/src/providers/SessionServicesProvider.tsx` — Services interface (line 138), context NOT exported (line 174)
- `chassis/src/utils/__tests__/formatting.test.ts` — Existing test (pattern reference)

## Verification

1. Prerequisite: `node -v` → 20.19+ (Vite 7 requirement)
2. After Phase 1: `cd frontend && pnpm test` — 54 tests pass, no new deps (done, committed `5d490407`)
3. After Phase 2: `cd frontend && pnpm install && pnpm test` — 75 total tests pass (54 Phase 1 + 14 useDataSource + 7 useRiskScore) (done, committed `6c59f7e7`)
4. `cd frontend && pnpm build` — still builds cleanly (verified)
