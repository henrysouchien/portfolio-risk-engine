# Fix: Spontaneous Session Logout Cascade (R18)

**Status**: PLANNED (post-Codex review v2)
**Priority**: Critical — blocks all testing
**Date**: 2026-03-16
**Findings**: `docs/planning/REVIEW_FINDINGS.md` → R18

---

## Context

The app drops sessions during normal browsing — clicking notifications, switching pages, general use. Root cause is a multi-layer cascade:

1. **Backend `get_session()` does a DB WRITE inside the READ path** — UPDATEs `last_accessed` (throttled to every 5min per session, but still a write in a read method). Under concurrent requests, this can cause DB lock contention or connection pool pressure, triggering exceptions.
2. **DB errors surface as 503** — `SessionLookupError` is already mapped to 503 by the app-level exception handler (`app.py:954`). This is correct — the backend does NOT return 401 for DB errors.
3. **Frontend `verifySessionStillValid()` treats 503/network errors as "session dead"** — any non-200 or fetch failure returns `false`, which confirms logout. This is the key frontend bug.
4. **Frontend has TWO independent logout handlers, both with weak guards**:
   - `authStore.ts:47` — `handleUnauthorizedSession()` (for `authAPIService` calls only)
   - `sessionCleanup.ts:50` — `handleUnauthorizedSessionExpiry()` (for normal API traffic via `SessionServicesProvider`)
   Both use boolean guards that reset in `finally`, allowing concurrent 401s to race through.
5. **Cross-tab broadcast** — `signOut()` broadcasts via both `localStorage` AND `BroadcastChannel`, potentially double-firing.

**Codex review corrections applied**: Backend already returns 503 (not 401) for DB errors. HttpClient already retries 503 without calling `onUnauthorized`. The critical missing file was `sessionCleanup.ts`, not just `authStore.ts`.

---

## Steps

### Step 1: Backend — Make `get_session()` read-only

**File:** `app_platform/auth/stores.py:34-75`

Remove the `last_accessed` UPDATE (lines 52-67) from `PostgresSessionStore.get_session()`. The method becomes a pure SELECT — no `conn.commit()` needed. This eliminates the DB write that can cause contention during concurrent requests.

`touch_session()` already exists on both stores and the protocol (`stores.py:98-109`, `protocols.py:25`), so no new method needed.

Also remove the inline `last_accessed` mutation from `InMemorySessionStore.get_session()` for consistency.

### Step 2: Backend — Add debounced touch to `AuthServiceBase`

**File:** `app_platform/auth/service.py`

Add `_maybe_touch_session(store, session_id)` to `AuthServiceBase`. Takes the **resolved store** (whichever store the session was found in) so that primary-store hits touch the primary store and fallback-store hits touch the fallback store. Uses an in-memory dict + threading lock to ensure at most one `touch_session()` DB call per session per 5 minutes. Swallows all exceptions — a failed touch must never cause a 401/503.

Call sites in `get_user_by_session()`:
- After primary success (line 117-118): `self._maybe_touch_session(self.session_store, session_id)`
- After fallback success (line 133-134): `self._maybe_touch_session(self.fallback_session_store, session_id)`

```python
def _maybe_touch_session(self, store: SessionStore, session_id: str) -> None:
    now = datetime.now(UTC)
    with self._touch_lock:
        last = self._touch_cache.get(session_id)
        if last and (now - last) < timedelta(minutes=5):
            return
        self._touch_cache[session_id] = now
    try:
        store.touch_session(session_id)
    except Exception:
        pass
```

**Cache cleanup**: Prune entries older than 30min on each call (bounded cleanup inside the lock). Also clear session from cache on `delete_session()`.

### Step 3: Frontend — Return `true` on 503/network errors in `verifySessionStillValid`

**File:** `frontend/packages/chassis/src/utils/authRetry.ts`

This is the key frontend fix. Change the retry logic:
- Return `false` ONLY on explicit 401 or `authenticated: false` from a 200 response
- Return `true` on 503, 5xx, network errors, and timeouts — if we can't reach the backend, don't assume the session is dead

```typescript
// 503 / 5xx = backend temporarily unavailable, assume session still valid
if (response.status >= 500) return true;
// 401 = session genuinely expired
if (response.status === 401) return false;
```

Also change the catch block: network errors return `true` (not `false`).

### Step 4: Frontend — Debounce BOTH logout handlers

**File 1:** `frontend/packages/connectors/src/utils/sessionCleanup.ts:50-68`

This is the primary logout path for normal API traffic. Replace the `isHandlingUnauthorizedExpiry` boolean guard with a Promise-based lock + 100ms settle delay. Same pattern as below.

**File 2:** `frontend/packages/chassis/src/stores/authStore.ts:45-69`

Replace the `isHandlingUnauthorizedSession` boolean guard with the same Promise-based lock pattern.

```typescript
let logoutPromise: Promise<void> | null = null;

export const handleUnauthorizedSessionExpiry = () => {
  const authStore = useAuthStore.getState();
  if (!authStore.isAuthenticated || logoutPromise) return;

  logoutPromise = (async () => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    const currentState = useAuthStore.getState();
    if (!currentState.isAuthenticated) return;
    onLogout();
  })().finally(() => {
    setTimeout(() => { logoutPromise = null; }, 2000);
  });
};
```

Apply the same pattern to `handleUnauthorizedSession` in `authStore.ts`.

---

## File Summary

| File | Change |
|------|--------|
| `app_platform/auth/stores.py` | Remove UPDATE from `get_session()` — root cause fix |
| `app_platform/auth/service.py` | Add `_maybe_touch_session()` debounced helper with cache cleanup |
| `frontend/packages/chassis/src/utils/authRetry.ts` | Return `true` on 503/5xx/network errors (key frontend fix) |
| `frontend/packages/connectors/src/utils/sessionCleanup.ts` | Debounce `handleUnauthorizedSessionExpiry` with Promise lock |
| `frontend/packages/chassis/src/stores/authStore.ts` | Debounce `handleUnauthorizedSession` with Promise lock |

Note: HttpClient 503 handling (original Step 3) is **not needed** — HttpClient already retries 503 via generic retry logic without calling `onUnauthorized`.

## Tests

| Test File | Changes |
|-----------|---------|
| `tests/app_platform/test_session_bug_fix.py` | Adjust `FakeCursor` expectations (no UPDATE in `get_session`) |
| `tests/app_platform/test_auth_protocols.py` | Update assertion expecting commit + 2 statements from `get_session` |
| `tests/app_platform/test_auth_service.py` | Add: debounced touch (30 calls → 1), touch failure isolation, cache cleanup, fallback-store hit touches fallback (not primary) |
| `tests/app_platform/test_auth_stores_memory.py` | Verify `get_session` no longer mutates `last_accessed` |
| `frontend/packages/chassis/src/utils/__tests__/authRetry.test.ts` | Update 503 → `true`, add 401 → `false`, 200/`authenticated:false` → `false`, network error → `true` |
| `frontend/packages/chassis/src/stores/__tests__/authStore.test.ts` | Add: concurrent `handleUnauthorizedSession` calls → 1 signOut, post-delay re-check skips if already signed out |
| `frontend/packages/connectors/src/utils/__tests__/sessionCleanup.test.ts` | Add: 30 concurrent calls → 1 `onLogout`, debounce window holds |

## Verification

1. `pytest tests/app_platform/ -x`
2. `cd frontend && npx vitest run`
3. Start the app, open multiple tabs at localhost:3000
4. Click around rapidly — notifications, page switches, portfolio selector
5. Confirm no spontaneous logouts over 5+ minutes of active use

## Backwards Compatibility

- `app_platform`: Behavioral change — `get_session()` no longer updates `last_accessed` inline. The `SessionStore` protocol already has `touch_session()` for this purpose. Update `docs/reference/DATABASE_REFERENCE.md` to reflect that `last_accessed` is updated via `touch_session()` at the service layer, not in `get_session()`.
- Frontend: Additive (503 handling in authRetry) and behavioral fixes (debounce) with no API surface change.
- Sync scripts (`scripts/sync_app_platform.sh`, `scripts/sync_frontend_app_platform.sh`) needed before publishing.
