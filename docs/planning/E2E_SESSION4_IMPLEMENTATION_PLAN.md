# E2E Fix Session 4: Performance & Auth Resilience — Implementation Plan

**Status**: READY FOR REVIEW (v5 — addresses all Codex findings through round 6)
**Session**: 4 of 4 (parallel fix sessions)
**Findings**: R3, R17, R18 from `docs/planning/REVIEW_FINDINGS.md`
**Date**: 2026-03-16

## Context

Three E2E findings need fixing: R3 (All Accounts portfolio switch times out at 30s), R17 (71 API requests on dashboard load), R18 (spurious session drops on navigation). These are infrastructure issues in the HTTP layer, auth layer, logging layer, and position fetching layer.

**Session boundaries (DO NOT TOUCH):**
- Session 1: CSS/UI + SettingsPanel.tsx
- Session 2: portfolio analysis/risk logic + `position_service.py:_consolidate_cross_provider()` (R8, line 624+)
- Session 3: recommendation logic/sector enrichment
- Session 4 (this): HTTP, auth, logging, query infra, position fetching (`get_all_positions` loop + `_get_positions_df` save lock)

---

## Step 1: Increase frontend timeout (R3)

**File:** `frontend/packages/chassis/src/catalog/descriptors.ts`

Change `DEFAULT_ERRORS.timeout` from `30000` to `60000` (line 13). Propagates to all descriptors using `...DEFAULT_ERRORS`. The 4 descriptors with explicit `timeout: 120000` (backtest, stress-test, monte-carlo, realized-performance) are unaffected. Also update `hedging-recommendations` which has its own `timeout: 30000` at ~line 551.

---

## Step 2: Fix log batching (R17)

**File:** `frontend/packages/app-platform/src/logging/Logger.ts`

1. **Line 41:** `QUEUE_FLUSH_DEBOUNCE_MS` from `200` to `1000`
2. **Line 929:** Batch size from `splice(0, 10)` to `splice(0, 50)`
3. **Startup grace period:** Add `_initTimestamp` field (set in `init()`). In `scheduleQueueFlush()`, use `Math.max(QUEUE_FLUSH_DEBOUNCE_MS, 2000 - elapsed)` as delay when within first 2s of init.

**Expected:** ~30 `/api/log-frontend` POSTs → 1-2.

---

## Step 3: Deduplicate data requests via query key normalization (R17)

**File:** `frontend/packages/connectors/src/resolver/useDataSource.ts`

**Problem:** Components that omit `portfolioId` generate different query keys from components that pass it explicitly, and from scheduler prefetches which always include it (`scheduler.ts:28-36`). React Query treats these as separate queries.

**Fix (fill-up):** When `portfolioId` is absent and a current portfolio exists, fill in the active portfolio ID so the key matches explicit-ID callers and scheduler prefetches.

```typescript
const normalizedParams = useMemo(() => {
  if (!currentPortfolio?.id) return params;
  const p = (params ?? {}) as Record<string, unknown>;
  if (!('portfolioId' in p) || p.portfolioId == null) {
    if (PORTFOLIO_SCOPED_SOURCES.has(sourceId)) {
      return { ...p, portfolioId: currentPortfolio.id } as Partial<SDKSourceParamsMap[Id]>;
    }
  }
  return params;
}, [params, currentPortfolio?.id, sourceId]);
```

`PORTFOLIO_SCOPED_SOURCES` mirrors `PREFETCH_PORTFOLIO_SCOPED_SOURCES` from `scheduler.ts:15-25` (positions, risk-score, risk-analysis, risk-profile, performance).

Pass `normalizedParams` to both `buildDataSourceQueryKey()` and `resolveWithCatalog()`.

**Why fill-up is safe:** On portfolio switch, `currentPortfolio.id` changes → all query keys change → React Query invalidates/refetches. No collision between different portfolios. `stripDefaults` in `core.ts:35-55` doesn't touch portfolioId.

**Known residual:** `portfolio-summary` is eager and its consumer (`usePortfolioSummary.ts:8`) passes an explicit ID, but the scheduler's `PREFETCH_PORTFOLIO_SCOPED_SOURCES` does not include `portfolio-summary`. This is a pre-existing mismatch unrelated to our change — our fill-up normalization doesn't affect it (it only fills when `portfolioId` is absent; `portfolio-summary` callers always pass it explicitly).

**Out of scope:** Resolver cascade in `registry.ts` (deeper architectural debt).

---

## Step 4: Add 401 retry with auth re-check (R18)

### Root cause

During navigation, lazy-loaded components trigger API calls. If the DB connection pool is under pressure, session lookup fails transiently. Current code: transient DB failure → `None` → 401 → `handleUnauthorizedSessionExpiry()` → `signOut()` → login redirect.

### 4a. Backend: Global exception handler for transient session lookup failures

**File:** `app_platform/db/exceptions.py`

Add `SessionLookupError(DatabaseError)` class. Distinct from existing `SessionNotFoundError` (session genuinely not found) — `SessionLookupError` means "couldn't check" (transient).

**File:** `app_platform/auth/service.py` (lines 110-141)

Rewrite `get_user_by_session()` to correctly distinguish "session not found" from "lookup failed":

```python
def get_user_by_session(self, session_id: str) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None

    try:
        try:
            session = self.session_store.get_session(session_id)
            if session is not None:
                return session
            return None  # genuinely not found in primary — 401 is correct

        except Exception as exc:
            logger.warning(
                "Primary session lookup failed for session_id=%s...: %s",
                session_id[:8], exc,
            )
            # Raise SessionLookupError immediately if no fallback or if
            # strict_mode (which skips fallback by design). The old
            # strict_mode path raised AuthenticationError, which was
            # swallowed by the outer catch → None → 401 → false logout.
            # That was the R18 root cause in production.
            if self.fallback_session_store is None or self.strict_mode:
                raise SessionLookupError(
                    f"Primary session store unavailable: {exc}",
                    original_error=exc,
                ) from exc

        # Primary failed (non-strict) — try fallback
        fallback_result = self.fallback_session_store.get_session(session_id)
        if fallback_result is not None:
            return fallback_result  # found in fallback, valid

        # Fallback returned None, but primary was DOWN, not "session not found".
        # Sessions are created in primary (service.py:79). If primary is down,
        # the session likely exists there but can't be read. Fallback (in-memory)
        # only has sessions created during degraded login (service.py:95-101).
        # Returning None here would be a false 401. Raise instead.
        raise SessionLookupError(
            f"Primary session store unavailable; cannot verify session {session_id[:8]}...",
        )

    except SessionLookupError:
        raise  # propagate to global handler → 503

    except Exception as exc:
        raise SessionLookupError(
            f"Session lookup failed: {exc}",
            original_error=exc,
        ) from exc
```

Key insights:
- In DB mode, `AuthService.__init__` (services/auth_service.py:95-98) sets `session_store=PostgresSessionStore` and `fallback_session_store=InMemorySessionStore`. Sessions are created in Postgres (service.py:79). When Postgres fails, the in-memory fallback returns `None` (session was never stored there). Previously this `None` became 401 — a false logout.
- **strict_mode is the R18 root cause in production.** `AuthService` passes `strict_mode=STRICT_DATABASE_MODE` (auth_service.py:111), and production sets `STRICT_DATABASE_MODE=true` (MULTI_USER_DEPLOYMENT_PLAN.md:220). In strict mode, the old code raised `AuthenticationError` which was caught by the outer except → `return None` → 401 → false logout. The fallback was never tried (test at test_auth_service.py:252-274 validates this: `fallback_session_store.get_calls == []`).
- The fix changes strict_mode behavior: `SessionLookupError` instead of `AuthenticationError`. **Test update required:** `test_get_user_by_session_returns_none_in_strict_mode_when_primary_raises` (test_auth_service.py:252) must be updated to expect `SessionLookupError` raised (not `user is None`).

**File:** `app.py` — Add global FastAPI exception handler

```python
from app_platform.db.exceptions import SessionLookupError

@app.exception_handler(SessionLookupError)
async def session_lookup_error_handler(request: Request, exc: SessionLookupError):
    return JSONResponse(
        status_code=503,
        content={"detail": "Session service temporarily unavailable"},
        headers={"Retry-After": "2"},
    )
```

This single handler covers **all routes** that call `get_user_by_session()` without their own broad `except Exception` — both the direct-call pattern (e.g., `routes/positions.py:359`) and the `Depends(get_current_user)` pattern (e.g., `routes/hedging.py:49`, `routes/portfolios.py:37`). When `get_user_by_session()` raises `SessionLookupError`, it propagates to FastAPI's exception handler → 503. Routes with broad catches (only in `routes/auth.py`) need explicit `except SessionLookupError: raise` — see below.

Existing global handlers for `PoolExhaustionError` and `ConnectionError` (app.py:942-943) already follow this same pattern.

**File:** `routes/auth.py` (~line 296) — `/auth/status` endpoint

The `/auth/status` endpoint has its own `try/except Exception` block (lines 321-328) that would catch `SessionLookupError` before the global handler. Add a specific catch that re-raises:

```python
except SessionLookupError:
    raise  # Let global handler return 503
except Exception as e:
    # existing handler unchanged
```

This ensures `verifySessionStillValid()` (step 4c) gets a 503 on transient DB failure, not `{authenticated: false}`.

**Other auth.py callers with broad catches:** Lines 365, 520, 825 (post-login `get_user_by_session`), 625/868 (pre-logout), and 768 (health check) are inside broad `try/except Exception` blocks. These are login/logout flows, not navigation data paths — not the R18 trigger. For completeness, add the same `except SessionLookupError: raise` one-liner before each broad catch.

**Why inline `get_current_user` in app.py:1038 and `create_auth_dependency()` don't need changes:** Both call `get_user_by_session()` which now raises `SessionLookupError`. Neither has a try/except around the call — the exception propagates to the route handler and then to the global handler naturally.

### 4b. Frontend: Add onAuthRetry callback to HttpClient

**File:** `frontend/packages/app-platform/src/http/HttpClient.ts`

Add `onAuthRetry?: () => Promise<boolean>` to `HttpClientConfig` (line 8-13). Store on class.

In `fetchWithRetry()` (line 70), add `let authRetried = false;` at the top of the method. Replace lines 83-86 with a **one-shot** auth retry:

```typescript
if (response.status === 401) {
  if (this.onAuthRetry && !authRetried) {
    authRetried = true;
    const stillValid = await this.onAuthRetry().catch(() => false);
    if (stillValid) continue;  // retry in next loop iteration
  }
  this.onUnauthorized?.();
  throw this.createHttpError(response, 'Session expired');
}
```

**One-shot flag behavior:**
- `authRetried` is local to the method call, reset per request
- First 401: calls `onAuthRetry()`. If `true`, `continue` retries (consumes 1 of 3+1 loop attempts). If `false`, calls `onUnauthorized()`.
- Second 401 (after retry): `authRetried` is already `true`, skips retry, calls `onUnauthorized()` immediately
- Note: The `continue` does consume one loop attempt. With `retries=3` (4 total iterations), this is acceptable — still leaves 2+ retry attempts for transient network errors.

**Keep lines 98-100 unchanged** (the `if 401 && onUnauthorized` re-throw in the catch block). This guard is still needed: after `onUnauthorized()` is called and the 401 error is thrown (line 85 equivalent), it enters the catch block. Without lines 98-100, the thrown 401 would fall through to the backoff delay (line 106) and retry the request after already deciding the session is invalid. Lines 98-100 ensure the 401 error is immediately re-thrown without backoff.

### 4c. Frontend: Define verifySessionStillValid

**File:** `frontend/packages/chassis/src/utils/authRetry.ts` (new file)

Define in chassis so all 3 APIService construction sites can import it. `authStore.ts` (chassis) uses a relative import; `SessionServicesProvider.tsx` and `useAuthFlow.ts` (connectors) import via `@risk/chassis`. Also export from `frontend/packages/chassis/src/index.ts`.

```typescript
// Relative import within chassis — do NOT use '@risk/chassis' barrel here
// to avoid self-import cycle (this file is exported from that barrel).
import { loadRuntimeConfig } from './loadRuntimeConfig';

export const verifySessionStillValid = async (): Promise<boolean> => {
  try {
    const { apiBaseUrl } = loadRuntimeConfig();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(`${apiBaseUrl}/auth/status`, {
        credentials: 'include',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        signal: controller.signal,
      });
      if (!response.ok) return false;  // 503 or other error = can't verify
      const data = await response.json();
      return data.authenticated === true;
    } finally {
      clearTimeout(timeoutId);
    }
  } catch {
    return false;
  }
};
```

Key design:
- **Raw fetch** — bypasses HttpClient 401 handling (avoids recursion)
- **Uses `loadRuntimeConfig().apiBaseUrl`** — respects configured API URL (not bare relative path)
- **5s AbortController timeout** — covers both headers AND body read (`clearTimeout` in `finally` after `response.json()`)
- **Returns `false` on any error** (network, timeout, 503) — conservative fallback

**File:** `frontend/packages/connectors/src/utils/sessionCleanup.ts`

Add diagnostic logging to `handleUnauthorizedSessionExpiry` (line 50):

```typescript
frontendLogger.logAdapter('sessionCleanup', 'handleUnauthorizedSessionExpiry called', {
  isAuthenticated: useAuthStore.getState().isAuthenticated,
  isHandling: isHandlingUnauthorizedExpiry,
});
```

### 4d. Frontend: Thread onAuthRetry through APIService to all 3 creation sites

**File:** `frontend/packages/chassis/src/services/APIService.ts`

Add `onAuthRetry?: () => Promise<boolean>` to `APIServiceConfig` (line 570-574). Pass through to `HttpClient` constructor (line 604-608).

There are 3 `APIService` construction sites. All 3 must wire `onAuthRetry`:

**Site 1 (critical — all data requests):** `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx` (~line 218)

```typescript
import { verifySessionStillValid } from '@risk/chassis';  // cross-package import

sessionServiceContainer.register('apiService', () => new APIService({
  onUnauthorized: handleUnauthorizedSessionExpiry,
  onAuthRetry: verifySessionStillValid,
}));
```

**Site 2 (auth flow):** `frontend/packages/connectors/src/features/auth/hooks/useAuthFlow.ts` (~line 73)

```typescript
import { verifySessionStillValid } from '@risk/chassis';  // cross-package import

const apiService = useMemo(() => new APIService({
  onUnauthorized: handleUnauthorizedSessionExpiry,
  onAuthRetry: verifySessionStillValid,
}), []);
```

**Site 3 (auth store bootstrap):** `frontend/packages/chassis/src/stores/authStore.ts` (~line 70)

```typescript
import { verifySessionStillValid } from '../utils/authRetry';  // same-package relative import

const authAPIService = new APIService({
  onUnauthorized: handleUnauthorizedSession,
  onAuthRetry: verifySessionStillValid,
});
```

**Required barrel export:** Add `export { verifySessionStillValid } from './utils/authRetry';` to `frontend/packages/chassis/src/index.ts` so connectors-package consumers can import via `@risk/chassis`.

### Defense summary (two layers)

**Layer 1 (backend, handles most cases):** `get_user_by_session()` raises `SessionLookupError` → global FastAPI handler returns 503 → `fetchWithRetry` auto-retries with exponential backoff → DB recovers → request succeeds. Covers all routes via global handler (plus explicit re-raises in `auth.py` broad catches).

**Layer 2 (frontend, handles edge cases):** If a genuine 401 gets through:
1. `HttpClient` receives 401 → calls `onAuthRetry()` (one-shot)
2. `verifySessionStillValid()` → raw `fetch(apiBaseUrl + '/auth/status')` with 5s timeout
3. `/auth/status` returns `{authenticated: true}` → retry original request once
4. `/auth/status` returns `{authenticated: false}` or 503 or error → `onUnauthorized()` fires → correct logout

**Bootstrap edge case:** During initial page load, `AuthService.ts:135` maps `/auth/status` failures to `{authenticated: false}`. If DB is down at bootstrap, user can't authenticate regardless. This is expected behavior and not an R18 regression (R18 is navigation drops, not bootstrap).

---

## Step 5: Parallelize multi-provider position fetching (R3 backend)

**File:** `services/position_service.py`

**Session 2 isolation (verified by code inspection):** Session 2's R8 fix targets `_consolidate_cross_provider()` (position_service.py, line 624+, specifically the cash dedup groupby at lines 664-688). Our changes touch two different locations: (1) `get_all_positions()` loop at lines 324-337, and (2) `_get_positions_df()` save lock at line 505. These are 120+ and 280+ lines away from Session 2's target. The call chain is: `get_all_positions()` → (parallel) `_get_positions_df()` → (later, sequential) `_consolidate_cross_provider()`. Our parallelization only affects the first two; Session 2's consolidation change only affects the last. The Session 2 plan doc references `get_all_positions()` at lines 121 and 424, but these are in "Files to read" (investigation) and "Key Files" (file-level listing) sections — the actual modification target (Step 5a, lines 696-713 of the plan doc) is `_consolidate_cross_provider()`.

### Parallel fetch with serialized save

**Problem:** `_get_positions_df()` has side effects via `_save_positions_to_db()` (line 505) which calls `AccountRegistry` methods that do read-modify-write on shared DB tables:
- `refresh_combined_portfolio()` (account_registry.py:271): replaces CURRENT_PORTFOLIO account links
- `ensure_single_account_portfolios()` (account_registry.py:298): reads account list written above

Running these concurrently causes race conditions.

**Solution:** `threading.Lock()` serializes `_save_positions_to_db()` calls. Fetches (the slow part: API calls + cache checks) remain parallel.

**Add to `__init__`:**
```python
import threading
self._save_lock = threading.Lock()
```

**Wrap save in `_get_positions_df()` (~line 505):**
```python
try:
    with self._save_lock:
        self._save_positions_to_db(df_for_save, provider)
except Exception as save_error:
    portfolio_logger.warning(...)
```

**Replace sequential loop in `get_all_positions()` (lines 324-337):**

```python
providers_to_fetch = [
    name for name in self._position_providers
    if name == "csv" or needed is None or name in needed
]

if len(providers_to_fetch) <= 1:
    for provider_name in providers_to_fetch:
        try:
            provider_results[provider_name] = self._get_positions_df(
                provider=provider_name, use_cache=use_cache,
                force_refresh=force_refresh, consolidate=False,
            )
        except Exception as exc:
            portfolio_logger.warning(f"Provider {provider_name} failed: {exc}")
            provider_results[provider_name] = (pd.DataFrame(), False, None)
            provider_errors[provider_name] = str(exc)
else:
    try:
        self._get_user_id()
    except Exception:
        pass

    with ThreadPoolExecutor(max_workers=len(providers_to_fetch)) as executor:
        futures = {
            executor.submit(
                self._get_positions_df, name, use_cache, force_refresh, False
            ): name
            for name in providers_to_fetch
        }
        for future in as_completed(futures):
            provider_name = futures[future]
            try:
                provider_results[provider_name] = future.result()
            except Exception as exc:
                portfolio_logger.warning(f"Provider {provider_name} failed: {exc}")
                provider_results[provider_name] = (pd.DataFrame(), False, None)
                provider_errors[provider_name] = str(exc)
```

**Thread safety analysis:**
- **Fetch phase (parallel):** Each thread calls `_fetch_fresh_positions(provider)` — independent API calls, no shared state
- **Transform phase (parallel):** DataFrame operations are local variables per thread
- **Save phase (serialized via `_save_lock`):** `_save_positions_to_db()` and all AccountRegistry calls serialized — no read-modify-write races
- **`_provider_metadata`:** Each thread writes distinct provider keys (lines 445, 495). Under CPython GIL, dict writes to distinct keys are safe
- **`_get_user_id()`:** Pre-called to cache `self.config.user_id` before threads start
- **Cache hit path:** When cached, `_save_positions_to_db` is not called (line 488 returns early). No lock contention.
- **All providers fail:** Each future's exception caught individually with `(pd.DataFrame(), False, None)` fallback. Downstream `pd.concat` (line 340-341) handles empty frames same as sequential

**Expected:** 3-4 providers at ~5s each → ~5s parallel fetch + <1s serial saves (was ~15-20s sequential).

---

## Commit Sequence

1. `fix: increase frontend timeout from 30s to 60s for analysis endpoints (R3)` — descriptors.ts
2. `fix: reduce log-frontend requests via larger batches and startup grace period (R17)` — Logger.ts
3. `fix: normalize portfolio ID in query keys to deduplicate data fetches (R17)` — useDataSource.ts
4. `fix: add 401 retry with auth re-check to prevent spurious logouts (R18)` — auth/service.py, exceptions.py, app.py, routes/auth.py (backend); HttpClient.ts, APIService.ts, sessionCleanup.ts, SessionServicesProvider.tsx, useAuthFlow.ts (frontend)
5. `perf: parallelize multi-provider position fetching with serialized saves (R3)` — position_service.py

---

## Verification

| Finding | Before | After | How to verify |
|---------|--------|-------|---------------|
| R3 timeout | "Data Loading Error" after 30s | Loading spinner, data appears | Switch to All Accounts |
| R3 backend | ~15-20s position fetch | ~5s (parallel) | Backend timing logs |
| R17 logs | ~30 log-frontend POSTs | 1-2 | DevTools Network filter |
| R17 dedup | ~10 duplicate data calls | fewer duplicates | DevTools Network count |
| R18 session | ~2/3 navigations drop session | 0 drops in 10 navigations | Click Dashboard→Strategy→Settings 10x |
| R18 503 | N/A | Transient DB errors → 503 → auto-retry | Kill DB briefly, observe retry |
| Regression | Single-account loads <5s | Still <5s | Switch to IBKR |

**Tests:**
- `npm test` in chassis, app-platform, connectors packages
- `pytest` for position_service, auth_service, app.py, auth routes
- New: HttpClient 401 one-shot retry tests, SessionLookupError global handler test, save_lock serialization test

---

## File Ownership Matrix

| File | Session | Change |
|------|---------|--------|
| `frontend/packages/chassis/src/catalog/descriptors.ts` | 4 | Timeout 30s→60s |
| `frontend/packages/app-platform/src/logging/Logger.ts` | 4 | Batch 10→50, debounce 200→1000, startup grace |
| `frontend/packages/connectors/src/resolver/useDataSource.ts` | 4 | Portfolio ID fill-up normalization |
| `frontend/packages/app-platform/src/http/HttpClient.ts` | 4 | onAuthRetry + one-shot 401 retry |
| `frontend/packages/chassis/src/services/APIService.ts` | 4 | Thread onAuthRetry config |
| `frontend/packages/chassis/src/utils/authRetry.ts` (new) | 4 | verifySessionStillValid function |
| `frontend/packages/chassis/src/index.ts` | 4 | Export verifySessionStillValid |
| `frontend/packages/connectors/src/utils/sessionCleanup.ts` | 4 | Diagnostic logging in handleUnauthorizedSessionExpiry |
| `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx` | 4 | Wire onAuthRetry |
| `frontend/packages/connectors/src/features/auth/hooks/useAuthFlow.ts` | 4 | Wire onAuthRetry |
| `frontend/packages/chassis/src/stores/authStore.ts` | 4 | Wire onAuthRetry |
| `app_platform/auth/service.py` | 4 | Raise SessionLookupError on transient failure |
| `app_platform/db/exceptions.py` | 4 | Add SessionLookupError class |
| `app.py` | 4 | Global SessionLookupError → 503 handler |
| `routes/auth.py` | 4 | Re-raise SessionLookupError before broad catches (7 sites) |
| `services/position_service.py` | 4 | ThreadPoolExecutor in `get_all_positions` + `_save_lock` in `_get_positions_df` |

**DO NOT TOUCH (other sessions):**

| File | Session |
|------|---------|
| `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx` | 1 |
| `frontend/packages/ui/src/index.css` | 1 |
| `core/portfolio_analysis.py` | 2 |
| `mcp_tools/risk.py` | 2 |
| `services/position_service.py:_consolidate_cross_provider()` (line 624+) | 2 |

---

## Changes from v3 (Codex v3 findings addressed)

1. **Critical: Fallback `None` → `SessionLookupError`:** Rewrote `get_user_by_session()` to handle the primary-fail + fallback-None case. Sessions are created in Postgres (primary). When Postgres fails, the in-memory fallback returns `None` (session was never stored there). Previously: `None` → 401 → false logout. Now: `SessionLookupError` → 503 → retry.
2. **High: Keep HttpClient catch block lines 98-100:** Reversed the v3 proposal to remove them. These lines prevent a thrown 401 from entering the backoff/retry path after `onUnauthorized()` has already been called.
3. **Medium: Auth.py broad catches:** Added `except SessionLookupError: raise` for all `get_user_by_session()` call sites in `routes/auth.py` that have broad `except Exception` blocks (lines 296, 365, 520, 625, 768, 825, 868).
4. **Medium: Session 2 isolation:** Cited code line numbers (324-337, 505, 624+) from direct inspection, not just plan doc references.
5. **strict_mode fix (v5):** `STRICT_DATABASE_MODE=true` in production means strict_mode IS active. The old strict_mode behavior (AuthenticationError → swallowed → None → 401) was the actual R18 root cause. Now raises `SessionLookupError` in both strict and non-strict mode. Test `test_auth_service.py:252` updated to expect `SessionLookupError`.
6. **v2 changelog inconsistency fixed:** Corrected the v2 changelog entry about lines 98-100 to match the v3/v4 decision to keep them.
7. **authStore.ts:70 wired:** Added as the 3rd APIService creation site. `verifySessionStillValid` defined in `@risk/chassis/src/utils/authRetry.ts` (new file), exported from `chassis/src/index.ts`. `authStore.ts` uses relative import; connectors-package sites import via `@risk/chassis`.
8. **Import paths consistent:** All code snippets use correct import paths. No more `../utils/sessionCleanup` for `verifySessionStillValid`.
9. **Defense summary fixed:** Uses `apiBaseUrl + '/auth/status'`, not bare `/auth/status`.
10. **File matrix complete:** Includes `chassis/src/index.ts` barrel export.

---

## Changes from v2 (Codex v2 findings addressed)

1. **Backend auth coverage — global handler:** Added `@app.exception_handler(SessionLookupError)` in `app.py`. Covers all routes without broad catches. Routes in `auth.py` that have their own `except Exception` blocks need explicit `except SessionLookupError: raise` one-liners. Follows existing pattern used by `PoolExhaustionError`/`ConnectionError` handlers.
2. **`dependencies.py` no longer needs changes:** `SessionLookupError` propagates through `create_auth_dependency()` and the inline `get_current_user()` to the global handler. No per-dependency modifications needed.
3. **`/auth/status` specific catch:** Added `except SessionLookupError: raise` before the generic `except Exception` to let the global handler return 503 instead of `{authenticated: false}`.
4. **Raw fetch URL fixed:** `verifySessionStillValid` now uses `loadRuntimeConfig().apiBaseUrl` instead of bare relative path.
5. **Timeout covers full operation:** `clearTimeout` moved to `finally` block after `response.json()`, so the 5s AbortController timeout covers both headers and body read.
6. **Session 2 conflict clarified:** Session 2's plan references `get_all_positions()` as a READ target for investigation. The actual modification is in `_consolidate_cross_provider()` (line 624+). Our change to the `get_all_positions()` loop (lines 324-337) and `_get_positions_df()` save lock (line 505) don't overlap.
7. **SettingsPanel references cleaned:** All references removed. Step 4 (old) dropped entirely.
8. **Attempt consumption documented:** The `continue` after auth retry consumes 1 of 3+1 loop iterations. Documented as acceptable.
9. **portfolio-summary residual documented:** Pre-existing mismatch between scheduler prefetch set and `portfolio-summary` eager descriptor. Our fill-up normalization doesn't affect it.
10. **AuthService bootstrap noted:** `AuthService.ts:135` maps failures to `{authenticated: false}` during bootstrap. This is expected — if DB is down at startup, user can't authenticate. Not an R18 regression.
11. **HttpClient catch block:** Lines 98-100 (401 re-throw guard in catch block) preserved — still needed to prevent thrown 401 from entering backoff path.
