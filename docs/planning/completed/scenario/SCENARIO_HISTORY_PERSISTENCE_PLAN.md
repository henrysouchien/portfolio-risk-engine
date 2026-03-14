# Scenario History Persistence

## Context

Scenario analysis runs (what-if, stress test, Monte Carlo) are stored in `sessionStorage` via `useScenarioHistory` hook. Data is lost on page refresh or new tab. Users want history to persist across sessions so they can revisit and compare past runs.

**Goal:** Replace `sessionStorage` with database-backed persistence, reusing existing DB patterns (DatabaseClient, PortfolioRepository, migration conventions).

## Approach

Follow the same pattern as target allocations: migration → DatabaseClient methods → PortfolioRepository wrappers → REST endpoints in `app.py` → APIService methods → rewrite hook to TanStack Query. Keep the same hook interface so `ScenarioAnalysisContainer` (`frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` line 407) needs zero changes.

---

## Changes

### 1. Migration: `database/migrations/20260304_add_scenario_history.sql`

```sql
CREATE TABLE IF NOT EXISTS scenario_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_name VARCHAR(255) NOT NULL DEFAULT 'CURRENT_PORTFOLIO',
    run_id VARCHAR(100) NOT NULL,
    run_type VARCHAR(20) NOT NULL,  -- 'whatif' | 'stress' | 'monte-carlo'
    params JSONB NOT NULL DEFAULT '{}',
    results JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, portfolio_name, run_id)
);

CREATE INDEX IF NOT EXISTS idx_scenario_history_user_portfolio
    ON scenario_history(user_id, portfolio_name);
```

### 2. DatabaseClient: `inputs/database_client.py` (~60 lines)

Add 3 methods following the `get_target_allocations` / `set_target_allocations` pattern (lines 863-912):

**`save_scenario_run(user_id, portfolio_name, run)`** — INSERT with ON CONFLICT DO UPDATE (upsert). `run` dict has `{run_id, run_type, params, results}`. Call `_enforce_scenario_history_limit()` after insert. Truncate `results` JSONB to 500KB max before insert to guard against oversized Monte Carlo blobs.

**`get_scenario_history(user_id, portfolio_name, limit=50)`** — SELECT ordered by `created_at DESC`, LIMIT capped. Return `List[Dict]` with `{run_id, run_type, params, results, created_at}`.

**`delete_scenario_history(user_id, portfolio_name)`** — DELETE all rows for user+portfolio. Return count deleted.

**`_enforce_scenario_history_limit(user_id, portfolio_name, max_runs=50)`** — DELETE oldest rows beyond limit.

All methods use `@handle_database_error` decorator and graceful fallback: table-not-exists → return `[]` or `0`; DB connection errors → log + return empty (no crash).

### 3. PortfolioRepository: `inputs/portfolio_repository.py` (~15 lines)

Thin wrappers delegating to DatabaseClient:
- `save_scenario_run(user_id, portfolio_name, run_data)`
- `get_scenario_history(user_id, portfolio_name, limit=50)`
- `delete_scenario_history(user_id, portfolio_name)`

### 4. REST API: 3 endpoints in `app.py` (~80 lines)

Follow the target allocations endpoint pattern (`app.py` lines 2009-2084):

**`GET /api/scenarios/history?portfolio_name=CURRENT_PORTFOLIO`** — Returns `{ success, runs: [...], count }`. Auth via `get_current_user` + `_resolve_user_id`.

**`POST /api/scenarios/history`** — Body: `{ run_id, run_type, params, results, portfolio_name? }`. Saves one run. Returns `{ success, run_id }`.

**`DELETE /api/scenarios/history?portfolio_name=CURRENT_PORTFOLIO`** — Clears all history. Returns `{ success, deleted_count }`.

### 5. Frontend APIService: `frontend/packages/chassis/src/services/APIService.ts` (~20 lines)

Add 3 methods:
```typescript
async getScenarioHistory(portfolioName = 'CURRENT_PORTFOLIO'): Promise<ScenarioHistoryResponse>
async saveScenarioRun(run: { run_id: string; run_type: string; params: unknown; results: unknown; portfolio_name?: string }): Promise<{ success: boolean }>
async deleteScenarioHistory(portfolioName = 'CURRENT_PORTFOLIO'): Promise<{ success: boolean }>
```

Add `ScenarioHistoryResponse` type to `frontend/packages/chassis/src/types/api.ts`:
```typescript
export interface ScenarioHistoryResponse {
  success: boolean;
  runs: Array<{ run_id: string; run_type: string; params: unknown; results: unknown; created_at: string }>;
  count: number;
}
```

Add query key factory to `frontend/packages/chassis/src/queryKeys.ts` using existing `scoped()` convention:
```typescript
export const scenarioHistoryKey = (portfolioId?: string | null) => scoped('scenarioHistory', portfolioId);
```

### 6. Hook Rewrite: `frontend/packages/connectors/src/features/scenarioHistory/useScenarioHistory.ts`

Replace sessionStorage implementation with TanStack Query + mutations. **Same exported interface** (`{ runs, addRun, clearHistory, getRuns }`) and **same types** (`ScenarioHistoryRun`, `ScenarioRunType`).

**Field mapping** (API → hook contract): The API returns `{run_id, run_type, created_at}` but the existing `ScenarioHistoryRun` interface uses `{id, type, timestamp}`. The hook transforms API responses:
```typescript
// API → ScenarioHistoryRun
{ id: apiRun.run_id, type: apiRun.run_type, params: apiRun.params, results: apiRun.results, timestamp: new Date(apiRun.created_at).getTime() }
```

**Portfolio scoping**: Use `useCurrentPortfolio()` + `useSessionServices()` (same pattern as `useTargetAllocation.ts` lines 10-13) to derive `portfolioName` and `api` instance for API calls and query key.

**Data flow**:
- `useQuery` for `runs` (fetches from API via `api.getScenarioHistory(portfolioName)`, maps to `ScenarioHistoryRun[]`, `staleTime: 5 * 60_000`)
- `useMutation` for `addRun` — optimistic update via `queryClient.setQueryData` (append to cache), background POST via `api.saveScenarioRun()`. On mutation error: log warning but keep optimistic data (best-effort persistence; user still sees their run in the UI even if DB save fails).
- `useMutation` for `clearHistory` — optimistic clear via `queryClient.setQueryData([])`, background DELETE. On error: refetch to reconcile.
- `getRuns` stays as a client-side filter on the cached `runs` array by `type`
- Keep `ScenarioHistoryRun` and `ScenarioRunType` exports unchanged

No container changes needed — `ScenarioAnalysisContainer.tsx` line 407 destructures `{ addRun, clearHistory, getRuns }` which remain identical.

---

## Files

| File | Action |
|------|--------|
| `database/migrations/20260304_add_scenario_history.sql` | CREATE — new migration |
| `inputs/database_client.py` | MODIFY — add 4 methods (~60 lines) |
| `inputs/portfolio_repository.py` | MODIFY — add 3 thin wrappers (~15 lines) |
| `app.py` | MODIFY — add 3 REST endpoints (~80 lines) |
| `frontend/packages/chassis/src/services/APIService.ts` | MODIFY — add 3 API methods (~20 lines) |
| `frontend/packages/chassis/src/types/api.ts` | MODIFY — add `ScenarioHistoryResponse` type |
| `frontend/packages/chassis/src/queryKeys.ts` | MODIFY — add `scenarioHistoryKey` using `scoped()` |
| `frontend/packages/connectors/src/features/scenarioHistory/useScenarioHistory.ts` | REWRITE — sessionStorage → TanStack Query + mutations |

## Codex Review (R1)

**FAIL** — 6 findings, all addressed above:
1. **High** — API field names (`run_id`/`run_type`/`created_at`) don't match hook contract (`id`/`type`/`timestamp`). → Fixed: explicit field mapping transform documented in Section 6.
2. **High** — Optimistic strategy under-specified for failure/concurrency. → Fixed: `addRun` logs warning on error but keeps optimistic data; `clearHistory` refetches on error to reconcile.
3. **Medium** — Portfolio scoping not explicit in hook rewrite. → Fixed: use `useCurrentPortfolio()` + `useSessionServices()` (same as `useTargetAllocation.ts`).
4. **Medium** — Query key doesn't follow `scoped()` convention. → Fixed: use `scoped('scenarioHistory', portfolioId)`.
5. **Medium** — Large payload handling missing. → Fixed: 500KB cap on `results` JSONB before insert in DatabaseClient.
6. **Low** — Container file path ambiguous. → Fixed: full path specified.

## Verification

1. Run migration: `psql -f database/migrations/20260304_add_scenario_history.sql`
2. `make dev` — start backend
3. Test API directly:
   - `curl /api/scenarios/history` → `{ success: true, runs: [], count: 0 }`
   - POST a run → `{ success: true, run_id: "..." }`
   - GET again → run appears
   - DELETE → `{ success: true, deleted_count: 1 }`
4. `pnpm typecheck` — no TS errors
5. Open Scenario Analysis in browser, run a what-if or stress test
6. Check History tab — run appears
7. Refresh page — run persists (was lost before)
8. Clear history — runs disappear from both UI and DB
