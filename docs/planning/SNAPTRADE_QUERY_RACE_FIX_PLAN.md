# Plan: Fix useSnapTrade (and usePlaid) Query Paused-on-Load — v7

## Status: NEEDS REPRODUCTION — Backend + Frontend Dual Fix After R5 Review

v1 proposed removing `!!api &&` from `enabled`. Codex R1 FAIL (4 findings). v2 listed hypotheses but missed a critical code path. v3 found the `SnapTradeService` error-swallowing pattern. Codex R2 FAIL (6 findings). v4 tightens hypothesis dismissals, fixes factual errors, removes redundant retry proposal, and adds a decisive repro strategy. Codex R3 FAIL (4 findings): backend route also swallows errors, repro plan doesn't check response body, test QueryClient disables retries, Option B only helps on remount. v5 addresses all 4 findings and splits Plaid vs SnapTrade per Codex recommendation. Codex R4 (2 findings): Hypothesis B had no offline repro or fix path, Hypothesis A writeup buried the dominant failure path. v6 adds an explicit offline repro step + fix path for B, and rewrites Hypothesis A to lead with the backend swallow as the primary mechanism. Codex R5 (2 findings): bad consumer key repro variant is non-deterministic (401 hits auth-error branch via `is_snaptrade_secret_error`, not the generic swallow), auth error retry story incomplete (`SnapTradeAuthError` lacks `.status` so global retry predicate doesn't skip it). v7 removes the bad consumer key repro variant and adds explicit auth error retry analysis.

### v1 Findings That Were Wrong

1. **`!!api` is always true** -- `useSessionServices()` throws if services context is null (SessionServicesProvider.tsx:564-569). The hook only runs inside the services-ready gate (`AppOrchestratorModern` renders dashboard only when `servicesReady === true`). Removing `!!api` from `enabled` is a no-op.

2. **`isEnabled` is always true** -- `config.enableSnapTrade` is hardcoded to `true` in `environment.ts` line 40. Not a feature flag that can be toggled.

3. **Cache-deadlock theory unsupported** -- `invalidateQueries` on a nonexistent key leaves the cache empty, not deadlocked. No code path seeds an empty cache entry for these keys.

4. **Tests don't validate the actual bug** -- Tests hard-code truthy `api`, so the proposed test would pass both before and after the fix.

---

## Context

The `useSnapTrade` React Query reportedly enters `paused` state on page load and never fires until manually invalidated. Holdings loading cascades downstream: the holdings query gates on `(connections?.length ?? 0) > 0`, so if connections are paused, holdings never load.

**Logged in TODO** as pre-existing bug during SnapTrade Secret Recovery work (`4e633086`).

## Architecture: How Components Reach useSnapTrade

```
<App>
  <React.StrictMode>                      -- dev-mode double mount/unmount (index.tsx:21)
    <QueryProvider>                        -- creates QueryClient
      <AuthProvider>
        <SessionServicesProvider>           -- useMemo creates services keyed on [user?.id, user?.tier, queryClient]
          <AppOrchestratorModern>           -- gates on useServicesReady() before rendering dashboard
            <ModernDashboardApp>            -- only renders when servicesReady === true
              <PortfolioInitializer>        -- blocks children until portfolio bootstrapped
                <SettingsView>              -- rendered by renderMainContent() case 'settings'
                  <AccountConnectionsContainer>
                    useSnapTrade()          -- called here
```

### Proof That `enabled` Is Always True

| Condition | Value at hook call time | Evidence |
|-----------|------------------------|----------|
| `user` | Always truthy | `AppOrchestratorModern` gates on `isAuthenticated && user && servicesReady` (line 143) |
| `api` | Always truthy | `useSessionServices()` throws if null (SessionServicesProvider.tsx:564-569) |
| `isEnabled` | Always `true` | Hardcoded: `enableSnapTrade: true` in `chassis/src/config/environment.ts:40` |
| `!!api && !!user && isEnabled` | Always `true` | All three terms are provably true by the time the hook runs |

There is no "race" where `enabled` starts `false` and transitions to `true`. The `enabled` expression is equivalent to `true` at every render.

## What We Know For Sure

1. The bug was observed (logged in TODO during SnapTrade Secret Recovery work).
2. The `enabled` condition is always `true` by the time the hook mounts (proven above).
3. The query options suppress ALL automatic recovery: `staleTime: Infinity`, `gcTime: Infinity`, `refetchOnMount: false`, `refetchOnWindowFocus: false`, `refetchOnReconnect: false`.
4. Installed TanStack Query version: `5.90.21` (resolved in `pnpm-lock.yaml`; v3 incorrectly said `5.85.5`, v1 said `5.83.0`).
5. React StrictMode is enabled (`index.tsx:21`) -- dev-mode double mount/unmount.

## Critical Finding: Error Swallowing at TWO Layers (SnapTrade-Specific)

**This is the key finding missed in v1-v2, and v3-v4 only caught the frontend half.**

### Layer 1 (Backend): `routes/snaptrade.py` Returns 200 on Failures

The SnapTrade backend route (`routes/snaptrade.py:706-720`) catches generic exceptions and returns `200 + {success: true, connections: []}`:

```python
except Exception as e:
    log_error("snaptrade_connections", "get_connections", e)
    if is_snaptrade_secret_error(e):
        return ConnectionsResponse(
            success=False, connections=[],
            message="SnapTrade authentication failed - connection needs repair",
            auth_error=True,
        )
    # BUG: Generic failures return 200 + success: true
    return ConnectionsResponse(
        success=True, connections=[],
        message="Unable to retrieve connections"
    )
```

This means the frontend never sees a 500 — it sees a normal 200 response with `success: true` and an empty connections array. Even if the frontend service layer correctly propagated errors, there would be no HTTP error to propagate.

**Contrast with Plaid:** The Plaid backend route (`routes/plaid.py:668-670`) does the right thing — it raises `HTTPException(status_code=500)` for generic failures. So the backend error-swallowing is a SnapTrade-specific problem.

### Layer 2 (Frontend): `SnapTradeService.getConnections()` Catch-All

`SnapTradeService.getConnections()` (chassis/src/services/SnapTradeService.ts:152-170) has a catch-all that converts every error into a fake-successful empty response:

```ts
async getConnections(): Promise<SnapTradeConnectionsResponse> {
  try {
    const response = await this.request<SnapTradeConnectionsResponse>(
      '/api/snaptrade/connections', { method: 'GET' }
    );
    return response;
  } catch (error) {
    // BUG: Swallows ALL errors — React Query never sees them
    return { success: false, connections: [], message: 'Failed to fetch connections', auth_error: false };
  }
}
```

**Double-swallowing for SnapTrade:** Even when the backend DOES return a real error (e.g., network timeout, DNS failure), the frontend catch-all converts it to `{ success: false, connections: [] }`. But the more common path is: the backend already returned `200 + {success: true}`, so the frontend catch block isn't even reached — the error is silently downgraded to success before the HTTP response leaves the server.

### Combined Consequence

**The common path:** Backend swallows the error at `routes/snaptrade.py:716` and returns `200 + {success: true, connections: [], message: "Unable to retrieve connections"}`. The frontend never sees an error — `SnapTradeService.getConnections()` returns the response normally, the queryFn returns `[]`, React Query marks it `status: 'success'`, and `staleTime: Infinity` locks in the empty state for the session. The frontend catch-all at `SnapTradeService.ts:166` is irrelevant in this path because the backend already returned HTTP 200.

**The less common path:** A network-level failure (DNS, TCP timeout) prevents the backend response from arriving. `SnapTradeService.getConnections()` catch-all converts the error to `{success: false, connections: [], auth_error: false}`. The queryFn still doesn't throw (neither `auth_error` nor `message === 'SnapTrade service unavailable'` matches), so the same permanent-empty outcome occurs.

**Either way:**
1. Returns `[]` to React Query → `status: 'success'`, `data: []`
2. `staleTime: Infinity` + `refetchOnMount: false` = permanent empty state for the session
3. Holdings query disabled because `connections.length === 0`
4. User sees nothing; no retry ever fires

**This is not "paused" — it's "silently succeeded with empty data and no recovery path."** The original observation of "paused" was likely a misinterpretation: the connections query shows `status: 'success'` with `data: []`, the holdings query is correctly disabled (since `connections.length === 0`), and from the user's perspective nothing loads.

### getHoldings Does NOT Have This Problem

`SnapTradeService.getHoldings()` (chassis/src/services/SnapTradeService.ts:176-195) already rethrows errors (`throw error` at line 193). Only `getConnections()` swallows errors. This means holdings failures would correctly surface to React Query's retry mechanism — but since the holdings query is gated on `connections.length > 0`, the swallowed-connections bug prevents it from ever firing.

### PlaidService.getConnections() Has Only the Frontend Bug

`PlaidService.getConnections()` (chassis/src/services/PlaidService.ts:97-100) has an identical frontend catch-all returning `{ success: false, connections: [], message: 'Failed to fetch connections' }`. However, the Plaid backend route (`routes/plaid.py:668-670`) correctly raises `HTTPException(status_code=500)` for generic failures. So Plaid only has a one-layer problem (frontend catch-all), while SnapTrade has a two-layer problem (backend + frontend).

This means the fix must be split by service — SnapTrade needs both backend and frontend fixes, while Plaid only needs the frontend fix.

## Hypotheses — Ranked by Likelihood

### Hypothesis A (MOST LIKELY): Backend Swallows Error → Permanent Empty State

**The dominant failure path is in the backend, not the frontend.** When `list_snaptrade_connections()` raises any non-auth exception, the except handler at `routes/snaptrade.py:706-720` catches it and returns `ConnectionsResponse(success=True, connections=[], message="Unable to retrieve connections")` — a 200 response that looks identical to "user has no connections" except for the message field. The frontend `SnapTradeService.getConnections()` catch-all (line 166-168) is a secondary issue: it would swallow network-level errors (DNS failure, timeout before HTTP response), but in the common case the backend has already returned a successful HTTP 200 before the frontend catch is reached.

**Mechanism (primary — backend swallow at `routes/snaptrade.py:716`):**
1. Backend `GET /api/snaptrade/connections` hits any error in `list_snaptrade_connections()` (SnapTrade API timeout, rate limit, corrupted secret that isn't detected by `is_snaptrade_secret_error`, network error to SnapTrade API)
2. The except handler at line 706 catches it, logs the error, but returns HTTP 200 with `{success: true, connections: [], message: "Unable to retrieve connections"}`
3. Frontend `SnapTradeService.getConnections()` receives a normal 200 response — the catch block at line 166 is never reached
4. `useSnapTrade` queryFn receives `{success: true, connections: []}` — `auth_error` is falsy, `message` is not `'SnapTrade service unavailable'`, so neither guard triggers
5. Returns `[]` to React Query, which marks it `status: 'success'`, `data: []`
6. Global retry policy (`QueryProvider.tsx` lines 30-36) never fires because no error was thrown
7. `staleTime: Infinity` + `refetchOnMount: false` = this empty result persists for the entire session
8. Holdings query is disabled because `connections.length === 0`
9. User sees empty connections, empty holdings — "nothing loads"
10. Only `invalidateQueries` or `refetch()` can recover — but no code path triggers this automatically

**Mechanism (secondary — frontend swallow at `SnapTradeService.ts:166`):**
If the error is at the network level (DNS failure, TCP timeout before any HTTP response), the backend never responds and `this.request()` throws. The catch-all at line 166 converts this to `{success: false, connections: [], message: 'Failed to fetch connections', auth_error: false}`. The queryFn still doesn't throw (it checks `auth_error` and `message === 'SnapTrade service unavailable'`, neither matches), so the same permanent-empty-state outcome occurs.

**Why this matches the observation:**
- "Query enters paused state" — likely misidentified. The holdings query is disabled (`fetchStatus: 'idle'`), which looks similar to "paused" in DevTools
- "Never fires until manually invalidated" — exactly what happens with a swallowed error + session-long cache
- Intermittent — only occurs when the backend has a transient error at the specific moment of first page load

**Why the fix works:** The backend fix (replacing the generic except with `raise HTTPException(status_code=502)`) is the primary fix — it makes genuine failures visible as HTTP errors. The frontend fix (removing the `SnapTradeService` catch-all) is the secondary fix — it ensures network-level errors also propagate. Together they let errors reach React Query's global retry policy (up to 3 retries, skip 4xx). Transient failures recover automatically. Persistent failures surface as `status: 'error'` in the UI instead of silent empty data.

### Hypothesis B: Network Mode Paused (NOT DISMISSED — but lower likelihood than A)

**Theory:** TanStack Query v5 with default `networkMode: 'online'` checks `navigator.onLine` *before* calling `queryFn`. If the browser reports offline at the moment the query mounts, TanStack sets `fetchStatus: 'paused'` and never invokes `queryFn` at all. The `SnapTradeService` catch-all is irrelevant in this scenario because execution never reaches it. **Critically, with `refetchOnReconnect: false` (line 138 of `useSnapTrade.ts`), the query stays paused permanently** — even after the browser comes back online, TanStack will not automatically retry because the hook explicitly opts out of reconnect-triggered refetches.

**Why lower likelihood than A (but still possible):**
1. The user's machine is almost always online, so the window for this is small.
2. Hypothesis A has a clearer trigger (any backend transient error) and broader exposure.
3. However, Hypothesis B cannot be dismissed by the SnapTradeService catch-all alone — TanStack's offline check runs *before* the catch-all has any opportunity to swallow the error.
4. If B is the real cause, Option A (stop swallowing errors) won't help at all because `queryFn` is never reached.

**How to distinguish from A in repro:** If DevTools shows `status: 'pending'` + `fetchStatus: 'paused'` (not `status: 'success'` + `data: []`), it's Hypothesis B. Hypothesis A produces `status: 'success'`.

**Offline repro steps (to confirm or rule out B):**
1. Start the backend + frontend normally
2. Open Chrome DevTools > Network tab
3. Toggle **Offline** mode ON (DevTools > Network > "No throttling" dropdown > "Offline")
4. Log in and navigate to Settings > Integrations (or refresh while already there)
5. Open React Query DevTools, inspect the `snaptradeConnections` query
6. **Hypothesis B confirmed:** `status: 'pending'`, `fetchStatus: 'paused'` — TanStack paused before `queryFn` ran
7. Toggle Offline mode OFF — if the query stays paused (does not automatically retry), `refetchOnReconnect: false` is the culprit
8. **Hypothesis B disproved:** `status: 'success'` or `status: 'error'` — TanStack did not enter paused state

**Fix path for B (if confirmed):** Change `refetchOnReconnect: false` to `refetchOnReconnect: true` (or remove it entirely — `true` is the default). This allows TanStack to automatically retry paused queries when the browser comes back online. Alternatively, set `networkMode: 'always'` on the query options, which tells TanStack to always invoke `queryFn` regardless of `navigator.onLine` state (the `queryFn` would then fail with a network error, which React Query can retry). The `refetchOnReconnect: true` approach is simpler and more aligned with the existing query option pattern. The same change should be applied to the holdings query (line 176) and the equivalent Plaid hooks.

### Hypothesis C: invalidateQueries Pre-Seeding (DISPROVEN)

**Disproven by Codex finding #2:** `invalidateQueries` on a nonexistent cache key is a no-op in TanStack Query v5. It does not create a cache entry. This hypothesis has no valid mechanism.

### Hypothesis D: Stale user?.id in Query Key (DISPROVEN)

**Disproven by architecture analysis:** The services-ready gate in `AppOrchestratorModern` means `user` is always non-null by the time `useSnapTrade` renders. `SessionServicesProvider.useMemo` depends on `user?.id`, so `services = null` when `user = null`, which means `servicesReady = false` and the dashboard doesn't render.

## Recommended Fix

### Option A (Recommended): Stop Swallowing Errors at Both Layers

**Problem:** SnapTrade has two layers of error swallowing. The backend route (`routes/snaptrade.py:716`) returns `200 + {success: true, connections: []}` for generic failures. The frontend service (`SnapTradeService.getConnections()`) has a catch-all that converts exceptions to fake success responses. Both must be fixed for errors to reach React Query's retry mechanism.

**Fix Part 1 — Backend: `routes/snaptrade.py` — Return error status for genuine failures**

The generic except clause (line 706-720) currently returns `success: true` with an empty array. Change it to return an error that the frontend can distinguish from "user legitimately has no connections":

```python
except Exception as e:
    log_error("snaptrade_connections", "get_connections", e)
    if is_snaptrade_secret_error(e):
        return ConnectionsResponse(
            success=False, connections=[],
            message="SnapTrade authentication failed - connection needs repair",
            auth_error=True,
        )
    # Return error status — don't masquerade as empty success
    raise HTTPException(
        status_code=502,
        detail="Unable to retrieve connections from SnapTrade"
    )
```

Use 502 (Bad Gateway) rather than 500 because the error originates from the upstream SnapTrade API, not from our server itself. This matches the Plaid backend pattern (`routes/plaid.py:668-670` raises `HTTPException(status_code=500)`).

**Fix Part 2 — Frontend: `SnapTradeService.ts` — Remove catch-all in `getConnections()`**

```ts
async getConnections(): Promise<SnapTradeConnectionsResponse> {
  const response = await this.request<SnapTradeConnectionsResponse>(
    '/api/snaptrade/connections', { method: 'GET' }
  );

  // Log success normally
  frontendLogger.logAdapter('SnapTradeService', 'SnapTrade connections fetched', {
    count: response.connections?.length || 0,
    success: response.success
  });

  return response;
}
```

Remove the catch-all entirely. Let errors propagate to the `queryFn`, where:
- `SnapTradeAuthError` is still thrown by the queryFn for `auth_error: true` responses (line 104-106)
- `'SnapTrade service unavailable'` is still handled gracefully by the queryFn (line 109-118, returns `[]`)
- HTTP errors (now including the 502 from Part 1) propagate to React Query's global retry mechanism (up to 3 retries, 4xx excluded)

**Fix Part 3 — Frontend: `PlaidService.ts` — Remove catch-all in `getConnections()`**

Same pattern as SnapTrade. Remove the catch-all at `PlaidService.ts:97-100`. The Plaid backend already returns proper HTTP errors (500), so only the frontend catch-all needs removal.

**Alternative for the queryFn (SnapTrade only):** Instead of (or in addition to) fixing the backend, the `useSnapTrade` queryFn could treat `message === "Unable to retrieve connections"` as an error:

```ts
// After existing auth_error and service-unavailable checks:
if (data.message === 'Unable to retrieve connections') {
  throw new Error('SnapTrade backend failed to retrieve connections');
}
```

This is a belt-and-suspenders approach — useful if the backend fix is deferred, but the backend fix (Part 1) is the proper solution.

**No per-hook `retry` needed.** The app already has global query retry configured in `QueryProvider.tsx` (lines 30-36). Adding `retry: 2` to individual hooks is redundant. The real issue is that the swallowed error prevents the global retry from ever seeing the failure.

**Auth error retry behavior (explicit).** When the backend returns `auth_error: true`, the `useSnapTrade` queryFn throws `SnapTradeAuthError` (line 105). The global retry predicate at `QueryProvider.tsx:30-35` only skips retries for errors where `typeof error.status === 'number' && error.status >= 400 && error.status < 500`. `SnapTradeAuthError` is a plain `Error` subclass with no `.status` property, so it falls through to `return failureCount < 3` — **auth errors will be retried up to 3 times.** Note that the `routes/snaptrade.py:686` early return for missing or `needs_reconnection_`-prefixed secrets sends `auth_error: true` without invoking any auto-rotation — in that path, all 3 retries are duplicate failures hitting the same early return. However, this is still acceptable: auth retries are harmless (no side effects, fast-fail), and in the separate code path where `is_snaptrade_secret_error()` catches a 401 from the SnapTrade API, the secret recovery mechanism may rotate the secret between retries, giving auto-recovery a chance to succeed. If all 3 retries fail, React Query marks the query as `status: 'error'` and the UI surfaces the auth error (which triggers the "Fix Connection" flow). No change needed.

### Option B: Defensive refetchOnMount (Less Invasive)

Keep the catch-all but make `refetchOnMount` smart — only suppress refetch when there's real data:

```ts
refetchOnMount: (query) => {
  const data = query.state.data;
  // Only skip refetch when we have actual connections; retry on empty/error
  return Array.isArray(data) && data.length > 0 ? false : 'always';
},
```

This preserves session-long caching for the success case but retries on empty/error results.

**Limitation (R3 finding #4):** `refetchOnMount` only triggers when the component unmounts and remounts. While the Settings > Integrations page stays mounted, this function never re-evaluates. If the initial fetch silently returns empty (via the backend swallowing pattern), recovery only happens if the user navigates away from Settings and comes back. This means Option B alone is insufficient for SnapTrade — it doesn't recover while the page is mounted. An interval-based mechanism (e.g., `refetchInterval` returning a value only when data is empty) could address this, but adds complexity and polling overhead for a problem better solved at the source (Option A).

### Option C: No Code Changes (If Cannot Reproduce)

If the bug cannot be reproduced after 3 attempts:
1. Update TODO to CANNOT_REPRODUCE with investigation notes
2. Document the error-swallowing patterns for future reference (even if not triggering now, the code is fragile)

## Files Changed

### Option A (Recommended)

| File | Change |
|------|--------|
| `routes/snaptrade.py` | Replace generic `except` handler (lines 716-720) with `raise HTTPException(status_code=502)` — stop returning `200 + {success: true, connections: []}` for genuine failures |
| `frontend/packages/chassis/src/services/SnapTradeService.ts` | Remove catch-all in `getConnections()` only (`getHoldings()` already rethrows at line 193) |
| `frontend/packages/chassis/src/services/PlaidService.ts` | Remove catch-all in `getConnections()` (lines 97-100; same swallowing pattern as SnapTrade; all other Plaid methods already rethrow). Plaid backend already raises `HTTPException(500)` — only the frontend catch-all needs removal. |

No changes to `useSnapTrade.ts` or `usePlaid.ts` hooks for Option A alone — the global retry policy in `QueryProvider.tsx` (lines 30-36: up to 3 retries, skip 4xx) handles transient failures once the service layer stops swallowing them.

**If Hypothesis B is confirmed during repro** (query enters `fetchStatus: 'paused'` with offline toggle), additionally change `refetchOnReconnect: false` to `refetchOnReconnect: true` on the connections and holdings queries in both `useSnapTrade.ts` (lines 138, 176) and the equivalent `usePlaid.ts` hooks. This is orthogonal to Option A and should be applied regardless of whether Option A is also applied — the two fixes address different failure modes (A: backend/frontend error swallowing; B: permanent pause on transient offline state).

### Option C (No Code Changes)

No file changes. Update `docs/TODO.md` only to record CANNOT_REPRODUCE status with investigation notes.

## Pre-Implementation Step: Reproduce the Bug

**Live reproduction is needed before implementation.** The hypothesis is strong (dual error-swallowing pattern is visible in the code), but the original bug report was during Secret Recovery work and may have been a transient condition that no longer applies. Implementing without reproduction risks changing behavior based on an untested assumption.

**Why the old repro was not decisive:** `status: 'success'` + `data: []` is also the legitimate "user has no connections" case. Observing it doesn't prove an error was swallowed. There is no persisted query cache (`@tanstack/react-query-persist-client` is not installed), so clearing browser storage is irrelevant — the cache is in-memory only and resets on every page refresh.

**Why DevTools status alone isn't enough for SnapTrade (R3 finding #2):** Because the backend route returns `200 + {success: true}` for genuine failures, forced failures (bad creds, raised exceptions) flow through the route's try/except and still produce a 200 response. DevTools showing `status: 200` or React Query showing `status: 'success'` wouldn't tell you whether the backend encountered an error or the user genuinely has no connections. You MUST check the response body.

**Decisive forced-failure repro (two scenarios):**

**Scenario 1 — Hypothesis A (backend error swallowing):**

1. **Force a generic backend error** (NOT an auth error — see note below) — one of:
   a. Add a temporary `raise Exception("test")` in `brokerage/snaptrade/connections.py` before the return
   b. Block the SnapTrade API host in `/etc/hosts` (manual environment modification — causes network timeout, must be reverted after testing)
   
   **Do NOT use a bad `SNAPTRADE_CONSUMER_KEY`.** A garbage consumer key produces a 401 from the SnapTrade API. `is_snaptrade_secret_error()` (`_shared.py:95-97`) classifies any `ApiException` with `status == 401` as an auth error, so the except handler at `routes/snaptrade.py:708` takes the `auth_error: true` branch — NOT the generic swallow at line 716. This makes it a non-deterministic repro for the generic-failure path. Variant (a) above — injecting `raise Exception("test")` — is deterministic: it raises a plain `Exception` that bypasses the auth-error check and hits the generic swallow. Variant (b) — blocking the host in `/etc/hosts` — is a manual environment modification that achieves the same effect (network error → generic `Exception`) but depends on external state and must be manually reverted.
2. Start the backend + frontend (`services-mcp` → `risk_module` + `risk_module_frontend`)
3. Log in, navigate to Settings > Integrations
4. **Check the actual HTTP response body** (not just the status code):
   - Open DevTools > Network tab, find the `GET /api/snaptrade/connections` request
   - Inspect the response body: look for `"message": "Unable to retrieve connections"` — this is the backend's error-swallowing signature
   - Compare: a legitimate empty state would have `"message": "Found 0 connections"` (line 703 of `routes/snaptrade.py`)
5. **Check React Query DevTools** and inspect the `snaptradeConnections` query:
   - **Hypothesis A confirmed (EXPECTED):** `status: 'success'`, `fetchStatus: 'idle'`, `data: []`, AND the Network tab shows `"message": "Unable to retrieve connections"` in the response body — error was swallowed at the backend, React Query thinks it succeeded
   - **Neither:** `status: 'error'` — error propagated correctly (bug doesn't reproduce with current code)
6. **Backend log correlation:** Check the risk_module service logs (`service_logs risk_module`) for the forced error. If the error appears in logs but the HTTP response is `200 + {success: true}`, the backend swallowing is proven independently of the frontend.
7. **Restore the backend** to normal config, refresh the page, verify connections load correctly.

**Scenario 2 — Hypothesis B (browser offline → permanent pause):**

1. Start the backend + frontend normally (no forced errors)
2. Log in, navigate to Settings > Integrations, verify connections load normally
3. Open Chrome DevTools > Network tab
4. **Toggle Offline mode ON** (DevTools > Network > "No throttling" dropdown > "Offline")
5. Hard-refresh the page (Cmd+Shift+R) so the query re-mounts while the browser thinks it's offline
6. **Check React Query DevTools** and inspect the `snaptradeConnections` query:
   - **Hypothesis B confirmed:** `status: 'pending'`, `fetchStatus: 'paused'` — TanStack paused before `queryFn` ran. No `GET /api/snaptrade/connections` request appears in the Network tab at all (the `queryFn` was never called).
   - **Not B:** `status: 'success'` or `status: 'error'` — TanStack did not enter paused state
7. **Toggle Offline mode OFF** and observe:
   - If the query **stays paused** (does not automatically retry): `refetchOnReconnect: false` is the culprit — TanStack respects the hook's opt-out and never retries, even though the network is back. This confirms the fix is to change `refetchOnReconnect` to `true`.
   - If the query **automatically retries**: `refetchOnReconnect: false` is not being respected (unlikely), or TanStack v5 has a different code path. Hypothesis B is disproved as a permanent-pause cause.

**Key distinction from the "no connections" case:** Scenario 1's forced backend error guarantees there IS an error to observe. Checking the response body `message` field distinguishes "Unable to retrieve connections" (error was swallowed) from "Found N connections" (legitimate response). Scenario 2's offline toggle simulates a condition that Scenario 1 cannot reach — `queryFn` is never called, so neither the backend nor the frontend error-swallowing paths are relevant.

## What NOT to Do

- Do NOT remove `!!api` from `enabled` as a "fix" -- it's a no-op that doesn't address any root cause.
- Do NOT change `refetchOnMount` to `true` globally -- it would break session-long caching (every view navigation re-fetches).
- Do NOT add a `useEffect` that calls `refetch()` on mount -- band-aid over an unknown root cause.

## Test Plan

### Test Harness Note (R3 finding #3)

The shared test QueryClient at `connectors/src/resolver/__tests__/renderWithProviders.tsx:11-18` sets `retry: false` by default. This is correct for most tests (deterministic, no flaky waits), but tests that need to verify retry behavior (tests 1, 5 below) MUST create a custom QueryClient with retries enabled:

```ts
const retryQueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,           // Match production retry count or use a small number
      retryDelay: 0,      // No delay in tests
      gcTime: Infinity,
    },
  },
});

// Pass to renderHookWithQuery:
const { result } = renderHookWithQuery(() => useSnapTrade(), {
  queryClient: retryQueryClient,
});
```

The `renderHookWithQuery` helper already accepts a `queryClient` option (line 23-30 of `renderWithProviders.tsx`), so no harness changes are needed — just pass the overridden client. Tests that do NOT test retry behavior should use the default QueryClient (which disables retries) for determinism.

### For Option A — useSnapTrade tests (`useSnapTrade.test.tsx`)

1. **Error recovery test**: Mock `SnapTradeService.getConnections()` to throw on first 2 calls, succeed on 3rd. **Must use a custom QueryClient with `retry: 2`** (see harness note above). Verify React Query retries and eventually shows connections.
2. **Backend down test**: Mock to always throw. Verify query enters `status: 'error'` (not silently empty with `status: 'success'`). Verify `AccountConnectionsContainer` renders error UI. Can use default QueryClient (retry: false) since we're testing the error state, not retry behavior.
3. **Session-long cache preservation test**: After successful fetch, verify no refetch on mount/focus/reconnect.
4. **Holdings cascade test**: After connections load with data, verify holdings query fires. After connections error, verify holdings stays disabled (gated on `connections.length > 0`).

### For Option A — Backend tests (`test_snaptrade_connections_route`)

9. **502 on generic failure**: Mock `list_snaptrade_connections()` to raise a generic `Exception`. Verify route returns HTTP 502 (not 200 with empty connections).
10. **Auth error still returns 200 + auth_error**: Mock `is_snaptrade_secret_error()` to return True. Verify route returns `{success: false, auth_error: true}` (this path should NOT change).
11. **Success path unchanged**: Verify normal flow still returns `{success: true, connections: [...]}`.

### For Option A — usePlaid tests (`usePlaid.test.tsx`) — NEW (was missing from R1)

5. **Plaid error recovery test**: Mock `PlaidService.getConnections()` to throw on first call, succeed on retry. **Must use a custom QueryClient with `retry: 1`** (see harness note above). Verify recovery.
6. **Plaid backend down test**: Mock to always throw. Verify `status: 'error'`, not silent empty. Can use default QueryClient.
7. **Plaid session-long cache preservation**: After successful fetch, verify no refetch on mount/focus/reconnect (same invariant as SnapTrade).
8. **Plaid holdings cascade test**: Verify holdings query stays disabled when connections error, fires when connections have data.

### For Option C

1. All existing tests pass (no behavioral change).

## Acceptance Criteria

1. Root cause is identified via forced-failure repro (Scenario 1 for Hypothesis A, Scenario 2 for Hypothesis B) with backend response body inspection and backend log correlation.
2. Fix addresses the actual root cause — error swallowing at BOTH layers for SnapTrade (backend route + frontend service) and the frontend layer for Plaid.
3. Session-long caching behavior is preserved for the success path.
4. Transient backend errors recover via React Query's global retry policy (if Option A).
5. Persistent backend errors surface in UI as `status: 'error'` (not silent empty `status: 'success'`).
6. SnapTrade backend route returns HTTP 502 (not `200 + {success: true}`) for generic failures.
7. Both `SnapTradeService.getConnections()` and `PlaidService.getConnections()` frontend catch-alls are removed.
8. If Hypothesis B is confirmed: `refetchOnReconnect: false` changed to `refetchOnReconnect: true` on connections and holdings queries in both `useSnapTrade.ts` and `usePlaid.ts`.
9. Existing 20+ useSnapTrade tests pass unchanged.
10. New regression tests added for useSnapTrade (tests 1-4), usePlaid (tests 5-8), AND backend route (tests 9-11).
11. Retry tests use a custom QueryClient with retries enabled (not the default `retry: false` test harness).
