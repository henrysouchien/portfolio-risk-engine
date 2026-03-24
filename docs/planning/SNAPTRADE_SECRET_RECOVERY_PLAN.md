# SnapTrade User Secret Recovery Plan

## Context

SnapTrade holdings fetch returns 500 because the upstream SnapTrade API returns 401 "Invalid userID or userSecret". The secret in AWS Secrets Manager exists but SnapTrade rejects it. Re-registration doesn't help — the "already exist" path in `register_snaptrade_user()` just returns the same stale secret from AWS. There is no recovery path.

The SnapTrade SDK has `reset_snap_trade_user_secret` — a secret rotation endpoint that generates a new secret **without deleting the user or their brokerage connections**. This codebase doesn't use it.

## Design

Two-tier recovery with clear separation: **auto-recovery** (Tier 1, transparent) vs **user-initiated reconnect** (Tier 2, destructive).

- **Tier 1 — Secret Rotation**: Call `reset_snap_trade_user_secret(user_id, user_secret)`. Generates a new secret preserving all brokerage connections. Includes a **post-rotation probe** (`list_user_accounts`) to verify the new secret works.
- **Tier 2 — Delete + Re-register**: If rotation also fails with 401 (secret fully invalidated), the user must delete and re-register. This loses brokerage connections — **never automatic**, always user-initiated via explicit UI confirmation. Includes position purging and AWS force-delete.

Auto-recovery (on 401 during holdings/connections fetch) only attempts Tier 1. Tier 2 is only reachable via the manual endpoint with `tier="full"` + frontend button with explicit user consent.

### Concurrency Safety

Locking is managed at the **caller site** (auto-recovery wrappers), NOT inside `rotate_snaptrade_user_secret()`. This avoids deadlock with non-reentrant locks.

```python
# Module-level in recovery.py
_rotation_locks: Dict[str, threading.Lock] = {}
_rotation_locks_guard = threading.Lock()

def _get_rotation_lock(user_email: str) -> threading.Lock:
    with _rotation_locks_guard:
        if user_email not in _rotation_locks:
            _rotation_locks[user_email] = threading.Lock()
        return _rotation_locks[user_email]
```

Auto-recovery pattern (used in Steps 4 and 5):
1. Catch 401 from SDK call, capture the `failed_secret` that was used
2. Acquire per-user lock
3. Inside lock: re-read `current_secret` from AWS
4. If `current_secret != failed_secret` → another caller already rotated → skip rotation, just retry with new secret
5. Else call `rotate_snaptrade_user_secret()` (lock-free function)
6. Release lock
7. Retry the original operation once

`rotate_snaptrade_user_secret()` is a pure function — no lock, no "already rotated" check. Callers are responsible for concurrency control.

**Multi-worker safety**: `threading.Lock` is process-local. The app can run with multiple uvicorn workers (`UVICORN_WORKERS=4`).

**Tier 1 (rotation)**: Cross-worker races are safe. The `failed_secret != current_secret` AWS re-read guard prevents redundant rotations. If two workers both rotate, the second overwrites the first — but both probe afterward, so the final secret is verified working.

**Tier 2 (destructive)**: Concurrent Tier 2 from different workers could interleave: worker A stores a new secret, worker B's later force-delete removes it. To handle this, Tier 2 adds a **post-store probe** (same as Tier 1): after storing the new secret, call `_list_user_accounts_with_retry(client, user_id, new_secret)`. If the probe fails (another worker interfered), re-read the latest secret from AWS and probe that. If the re-read secret works, return it. If not, re-raise. This makes Tier 2 converge to a valid state regardless of interleaving. The key insight: the last writer wins, and the probe verifies the winner's secret works.

### AWS Store Resilience

The SDK docs warn: "if you call this endpoint and fail to save the new secret, you'll no longer be able to access any data for this user". To mitigate:

1. `store_snaptrade_user_secret()` is retried up to 2 times (1s delay between) before giving up
2. If all store retries fail, write the new secret to a local recovery file (`~/.snaptrade_recovery/{user_hash}.secret`) with `0600` permissions. Do NOT log the secret via `log_error()` or `portfolio_logger` — those write to `errors.jsonl` and `app.log` without redaction, which would be a credential leak. Log only a message like "CRITICAL: new secret written to recovery file" with the file path.
3. Error propagates — Tier 2 is NOT attempted (the rotated-but-unsaved secret would be lost)

### AWS Soft-Delete Handling for Tier 2

`delete_snaptrade_user_secret()` currently uses `RecoveryWindowInDays=7` (soft delete). Tier 2 needs to immediately re-register and store a new secret under the same name. AWS rejects `create_secret` for secrets in "pending deletion".

Fix: Add `force: bool = False` parameter to `delete_snaptrade_user_secret()`. When `force=True`, use `ForceDeleteWithoutRecovery=True`.

**Critical**: `delete_snaptrade_user()` in `users.py` internally calls `delete_snaptrade_user_secret()` without `force` (lines 75, 80). Tier 2 does NOT call `delete_snaptrade_user()`. Instead, it calls the individual steps directly:
1. `_delete_snap_trade_user_with_retry(client, snaptrade_user_id)` — API-only delete
2. `delete_snaptrade_user_secret(user_email, force=True)` — AWS force-delete

This avoids touching the existing `delete_snaptrade_user()` helper.

### Frontend Error Surfacing

The current chain swallows auth errors:
- `routes/snaptrade.py` `GET /connections` catches all exceptions → returns `success=True, connections=[]` (line 684)
- `useSnapTrade()` queryFn returns `data.connections ?? []` without checking `success` (line 111)

Fix in two places:
1. **Backend** (Step 6): Connections endpoint returns `success=False, auth_error=True` on auth errors
2. **Frontend** (Step 11): The `useSnapTrade()` queryFn checks `data.auth_error === true` and throws a typed error. This makes react-query treat it as a query error, which flows into `connectionsError` → the hook's `error` field → the container's `error` prop → the `AccountConnections` error card.

### Tier 1→2 Frontend Contract

The `POST /reset-secret` endpoint always returns HTTP 200 with a JSON body. On Tier 1 failure (rotation 401), it returns `{ success: false, recovery_method: null, message: "...", connections_preserved: true, tier2_available: true }`. The frontend `.then()` checks `result.success` — if false and `tier2_available`, prompts for Tier 2 confirmation. This avoids the HTTP client throwing on non-2xx.

On truly unrecoverable errors (AWS failure, unexpected exception), the endpoint returns 500 which the HTTP client throws.

## Implementation

### Step 1: SDK wrapper — `brokerage/snaptrade/client.py`

Add retry-wrapped SDK call:

```python
@with_snaptrade_retry("reset_snap_trade_user_secret")
def _reset_snap_trade_user_secret_with_retry(client, user_id, user_secret):
    return client.authentication.reset_snap_trade_user_secret(
        user_id=user_id, user_secret=user_secret,
    )
```

Add to `__all__`.

### Step 2: Auth error classifier — `brokerage/snaptrade/_shared.py`

Add helper:

```python
def is_snaptrade_secret_error(e: Exception) -> bool:
    """Check if exception is a SnapTrade 401 invalid-secret error.

    Only 401 (invalid credentials) triggers recovery. 403 (permission denied)
    is a different class of error — the secret may be valid but the user lacks
    access. Rotating the secret would not help.
    """
    return isinstance(e, ApiException) and getattr(e, "status", None) == 401
```

Add to `__all__`.

### Step 3: Core recovery module — NEW `brokerage/snaptrade/recovery.py`

**`rotate_snaptrade_user_secret(user_email, client) -> str`**
Pure function — no locking. Callers manage concurrency.
1. Resolve `user_id` via `get_snaptrade_user_id_from_email(user_email)`
2. Fetch current `user_secret` from AWS via `get_snaptrade_user_secret(user_email)`
3. Call `_reset_snap_trade_user_secret_with_retry(client, user_id, user_secret)`
4. Extract `new_secret` from `response.body["userSecret"]`
5. **Store with retry**: Call `store_snaptrade_user_secret(user_email, new_secret)` with up to 2 retries (1s delay). On final failure, write secret to recovery file (see AWS Store Resilience section), then re-raise.
6. **Post-rotation probe**: Call `_list_user_accounts_with_retry(client, user_id, new_secret)`. If this 401s, log ERROR "rotated secret rejected by probe" and raise `RuntimeError`.
7. Return `new_secret`

**`recover_snaptrade_auth(user_email, client, user_id: int) -> tuple[str, str]`**
Two-tier orchestrator. Returns `(new_secret, method)`. Takes `user_id` (local DB integer) for position cleanup.
- Tier 1: Try `rotate_snaptrade_user_secret()`. On success → return `(new_secret, "rotation")`. On `ApiException` with 401 → fall through to Tier 2.
- On AWS store failure or probe failure → re-raise immediately, do NOT fall through to Tier 2.
- Tier 2 (direct SDK/AWS calls, NOT via `delete_snaptrade_user()` wrapper):
  1. Try `_delete_snap_trade_user_with_retry(client, snaptrade_user_id)`. If `ApiException` with "not found" → log info, continue (user already gone on SnapTrade side — same behavior as `delete_snaptrade_user()` line 79). Other exceptions propagate.
  2. `delete_snaptrade_user_secret(user_email, force=True)` — AWS force-delete (no 7-day window)
  3. `PositionService(user_email=user_email, user_id=user_id).delete_provider_positions('snaptrade')` — purge local positions
  4. `time.sleep(1)` — brief delay for SnapTrade eventual consistency
  5. Call `_register_snap_trade_user_with_retry(client, snaptrade_user_id)` directly (raw SDK call, NOT `register_snaptrade_user()` wrapper which has "already exist" handling that would raise RuntimeError after force-delete)
  6. Extract `new_secret` from `response.body["userSecret"]`
  7. **Store with retry** (same hardening as Tier 1): `store_snaptrade_user_secret(user_email, new_secret)` with up to 2 retries (1s delay). On final failure, write to recovery file, re-raise.
  8. If step 5 raises "already exist" `ApiException`, `time.sleep(2)` then retry step 5 once (eventual consistency)
  9. **Post-store probe** (multi-worker safety): Call `_list_user_accounts_with_retry(client, snaptrade_user_id, new_secret)`. If probe fails, re-read latest secret from AWS, probe that. If re-read secret works, use it. If not, re-raise.
  10. **AccountRegistry refresh** (matching DELETE /user at `routes/snaptrade.py` line 1104): `AccountRegistry(user_id).refresh_combined_portfolio()` + `AccountRegistry(user_id).ensure_single_account_portfolios()`. Wrap in try/except — non-fatal if it fails.
  11. Return `(new_secret, "delete_recreate")`

Also exports: `_get_rotation_lock()` for auto-recovery callers.

### Step 4: Auto-recovery in holdings fetch — `providers/snaptrade_loader.py`

Wrap the try block in `fetch_snaptrade_holdings()` (line 881). On `ApiException` where `is_snaptrade_secret_error(e)`:
1. Capture `failed_secret` = the user_secret that was used for the failed call (line 885)
2. Acquire per-user lock via `_get_rotation_lock(user_email)`
3. Inside lock: re-read `current_secret` from AWS
4. If `current_secret != failed_secret` → log info "secret already rotated by another caller", release lock, retry fetch
5. Else: call `rotate_snaptrade_user_secret(user_email, client)`, release lock
6. If rotation fails, let error propagate (no Tier 2)
7. Retry `fetch_snaptrade_holdings()` once with the new secret

### Step 5: Auto-recovery in connections list — `brokerage/snaptrade/connections.py`

Same lock-then-check-then-rotate pattern as Step 4 for `list_snaptrade_connections()` — the `_list_user_accounts_with_retry()` call at line 99 can also 401.

### Step 5b: Auto-recovery in broker adapter — `brokerage/snaptrade/adapter.py`

`SnapTradeBrokerAdapter._get_identity()` (line 367) reads the secret and is called by 4 methods: `get_account_balance()` (line 241), `refresh_after_trade()` (line 260), `_fetch_accounts()` (line 303), `_resolve_authorization_id()` (line 323). These cover trading flows (preview, execute, cancel) which are NOT covered by Steps 4-5.

Add auto-recovery to all 4 adapter methods using the `_try_rotate_secret` + re-read pattern. Example for `_fetch_accounts()`:

```python
def _fetch_accounts(self, force_refresh=False):
    # ... existing cache check ...
    client = self._get_client()
    user_id, user_secret = self._get_identity()
    try:
        response = _list_user_accounts_with_retry(client, user_id, user_secret)
    except ApiException as e:
        if not is_snaptrade_secret_error(e):
            raise
        failed_secret = user_secret
        lock = _get_rotation_lock(self._user_email)
        with lock:
            current_secret = get_snaptrade_user_secret(self._user_email)
            if current_secret == failed_secret:
                rotate_snaptrade_user_secret(self._user_email, client)
        user_id, user_secret = self._get_identity()  # re-read after rotation
        response = _list_user_accounts_with_retry(client, user_id, user_secret)
    # ... rest unchanged ...
```

### Step 5c: Auto-recovery in trading module — `brokerage/snaptrade/trading.py`

All 5 trading functions (`search_snaptrade_symbol` line 23, `preview_snaptrade_order` line 99, `place_snaptrade_checked_order` line 193, `get_snaptrade_orders` line 220, `cancel_snaptrade_order` line 250) follow the same pattern: `_get_snaptrade_identity(user_email)` → SDK call. These are called directly by `TradeExecutionService`, bypassing the adapter's `_fetch_accounts()`.

Add a shared recovery helper in `brokerage/snaptrade/recovery.py`:

The caller pattern is the same everywhere — wrap in try/except, call `_try_rotate_secret`, re-read identity, retry once:

**Trading functions** (all 5 in `trading.py`):
```python
def search_snaptrade_symbol(user_email, account_id, ticker, client=None):
    ...
    user_id, user_secret = _get_snaptrade_identity(user_email)
    ...
    try:
        response = _symbol_search_user_account_with_retry(
            client, user_id, user_secret, account_id, ticker_upper)
    except ApiException as e:
        if not is_snaptrade_secret_error(e):
            raise
        _try_rotate_secret(user_email, client, user_secret)
        user_id, user_secret = _get_snaptrade_identity(user_email)
        response = _symbol_search_user_account_with_retry(
            client, user_id, user_secret, account_id, ticker_upper)
```

**Adapter methods** (all 4 in `adapter.py`): Same pattern. The raw bound SDK calls in `_resolve_authorization_id()` and `refresh_after_trade()` use `user_secret` as a kwarg — the re-read handles this naturally since `_get_identity()` returns a fresh secret.

**Shared rotation helper** `_try_rotate_secret(user_email, client, failed_secret)` in `recovery.py`:
```python
def _try_rotate_secret(user_email: str, client, failed_secret: str) -> None:
    """Attempt Tier 1 rotation if the secret hasn't already been rotated."""
    lock = _get_rotation_lock(user_email)
    with lock:
        current = get_snaptrade_user_secret(user_email)
        if current == failed_secret:
            rotate_snaptrade_user_secret(user_email, client)
```

This is signature-agnostic — works for retry wrappers (positional user_secret at index 2), raw bound SDK methods (kwarg user_secret), or any other call pattern. The caller always re-reads identity after `_try_rotate_secret`.

### Step 6: Fix error swallowing + auth error surfacing — `routes/snaptrade.py`

Modify the `GET /connections` exception handler (lines 681-688). Split into two cases:

```python
except Exception as e:
    log_error("snaptrade_connections", "get_connections", e)
    if is_snaptrade_secret_error(e):
        return ConnectionsResponse(
            success=False,
            connections=[],
            message="SnapTrade authentication failed — connection needs repair",
            auth_error=True,
        )
    # Non-auth errors: graceful degradation (existing behavior)
    return ConnectionsResponse(
        success=True,
        connections=[],
        message="Unable to retrieve connections",
    )
```

Add `auth_error: bool = False` field to `ConnectionsResponse` model.

### Step 7: Manual endpoint — `routes/snaptrade.py`

**`POST /api/snaptrade/reset-secret`** (authenticated)
- Query param `tier` (default `"rotation"`): `"rotation"` (Tier 1 only) or `"full"` (Tier 1 → Tier 2 fallback). Default is the safe non-destructive option.
- `tier="rotation"`: calls `rotate_snaptrade_user_secret()` only
- `tier="full"`: calls `recover_snaptrade_auth(user_email, client, user_id)` (Tier 1 → Tier 2 fallback)
- **Always returns HTTP 200** with JSON body. On rotation 401 failure (recoverable → Tier 2 available), returns `{ success: false, tier2_available: true }`. On unrecoverable errors (AWS failure, probe failure), returns 500.
- Response model:

```python
class ResetSecretResponse(BaseModel):
    success: bool
    recovery_method: Optional[str] = None  # "rotation" or "delete_recreate"
    message: str
    connections_preserved: bool = True  # False when delete_recreate
    tier2_available: bool = False       # True when rotation failed but full recovery possible
```

Endpoint logic:
```python
lock = _get_rotation_lock(user_email)
with lock:
    try:
        if tier == "full":
            new_secret, method = recover_snaptrade_auth(user_email, client, user_id)
            return ResetSecretResponse(success=True, recovery_method=method,
                connections_preserved=(method == "rotation"), ...)
        else:
            rotate_snaptrade_user_secret(user_email, client)
            return ResetSecretResponse(success=True, recovery_method="rotation",
                connections_preserved=True, ...)
    except ApiException as e:
        if is_snaptrade_secret_error(e) and tier == "rotation":
            return ResetSecretResponse(success=False, tier2_available=True,
                message="Secret rotation failed — full recovery available", ...)
        raise HTTPException(500, detail=str(e))
```

The manual endpoint acquires the per-user lock to prevent racing with auto-recovery callers.

### Step 8: AWS force-delete parameter — `brokerage/snaptrade/secrets.py`

Add `force: bool = False` parameter to `delete_snaptrade_user_secret()`:

```python
def delete_snaptrade_user_secret(user_email: str, region_name: str = "us-east-1", force: bool = False) -> None:
    ...
    if force:
        secrets_client.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
    else:
        secrets_client.delete_secret(SecretId=secret_name, RecoveryWindowInDays=7)
```

Existing callers are unaffected — they don't pass `force`.

### Step 9: Frontend service — `frontend/packages/chassis/src/services/SnapTradeService.ts`

Add interfaces + method:

```typescript
export interface SnapTradeResetSecretResponse {
  success: boolean;
  recovery_method?: 'rotation' | 'delete_recreate';
  message: string;
  connections_preserved: boolean;
  tier2_available: boolean;
}

async resetSecret(tier: 'rotation' | 'full' = 'rotation'): Promise<SnapTradeResetSecretResponse> {
  return this.request<SnapTradeResetSecretResponse>(
    `/api/snaptrade/reset-secret?tier=${tier}`, { method: 'POST' }
  );
}
```

Update `SnapTradeConnectionsResponse` to add `auth_error?: boolean`.

### Step 10: API service delegation — `frontend/packages/chassis/src/services/APIService.ts`

Add pass-through method matching existing pattern:

```typescript
async resetSnapTradeSecret(tier?: 'rotation' | 'full'): Promise<SnapTradeResetSecretResponse> {
  return this.snaptradeService.resetSecret(tier);
}
```

### Step 11: Hook wiring — `frontend/packages/connectors/src/features/external/hooks/useSnapTrade.ts`

Two changes:

**A) Auth error detection in connections queryFn** (around line 91-111):
After `const data = await api.getSnapTradeConnections()`, add:
```typescript
if (data.auth_error) {
  throw new Error('SnapTrade authentication failed — use Fix Connection to repair');
}
```
This makes react-query treat it as a query error → flows into `connectionsError` → the hook's `error` field at line 370. No extra `authError` prop needed — the existing error pipeline handles it.

Additionally expose `authError` boolean. Since react-query can retain stale `connections` data even after a refetch error (session-long cache), `connections === undefined` is unreliable. Instead, derive from the error directly:
```typescript
// Typed error class for auth failures
class SnapTradeAuthError extends Error {
  constructor(message: string) { super(message); this.name = 'SnapTradeAuthError'; }
}

// In queryFn: throw new SnapTradeAuthError(...) instead of generic Error

// In hook return:
authError: connectionsError instanceof SnapTradeAuthError,
```
This works regardless of whether stale data exists in the cache.

**B) Reset mutation**:
- Add `resetSecretMutation` using the existing mutation pattern
- Action: calls `api.resetSnapTradeSecret(tier)`
- On ANY success (`result.success === true`): invalidate connections, holdings, AND `['accounts', 'list']` queries. The `['accounts', 'list']` invalidation is critical for Tier 2 — `AccountConnectionsContainer` merges DB-backed account rows via `useAccounts()` (line 439, 706), and existing destructive flows already invalidate this key (line 990, 1015). Without it, stale SnapTrade account rows remain visible after delete_recreate.
- Return new fields: `resetSecret(tier)`, `isResettingSecret`
- Errors fold into existing `error` aggregation at line 370

### Step 12: Frontend UI — `frontend/packages/ui/src/components/settings/AccountConnections.tsx`

This is the **actual rendered component** (confirmed via `SettingsView.tsx` → `AccountConnectionsContainer.tsx` → `AccountConnections`).

Add new props to `AccountConnectionsProps`:
```typescript
onFixConnection?: () => void;
isFixingConnection?: boolean;
showFixConnection?: boolean;
```

Modify the error card (lines 78-90). When `showFixConnection` is true, add a "Fix Connection" button next to the dismiss button:
```tsx
{showFixConnection && (
  <Button
    variant="outline"
    size="sm"
    onClick={onFixConnection}
    disabled={isFixingConnection}
    className="text-amber-800 border-amber-300 hover:bg-amber-100"
  >
    {isFixingConnection ? <RefreshCw className="w-3 h-3 animate-spin mr-1" /> : null}
    Fix Connection
  </Button>
)}
```

### Step 13: Container wiring — `frontend/packages/ui/src/components/settings/AccountConnectionsContainer.tsx`

- Destructure `resetSecret`, `isResettingSecret` from `useSnapTrade()` hook
- Derive `showFixConnection` from the hook's `authError` or error message check
- Pass to `<AccountConnections>`:
  - `showFixConnection={showFixConnection}`
  - `isFixingConnection={isResettingSecret}`
  - `onFixConnection` handler:
    1. Call `resetSecret("rotation")` (returns promise resolving to response body, since endpoint returns 200)
    2. `.then(result => { if (!result.success && result.tier2_available) { /* confirm dialog for tier=full */ } })`
    3. On Tier 2 confirm: `resetSecret("full")`

### Step 14: Package exports — `brokerage/snaptrade/__init__.py`

Add imports and `__all__` entries:
- `rotate_snaptrade_user_secret` from `brokerage.snaptrade.recovery`
- `recover_snaptrade_auth` from `brokerage.snaptrade.recovery`

### Step 15: Tests — NEW `tests/snaptrade/test_snaptrade_recovery.py`

~31 tests (27 backend + 4 frontend):

**Core rotation:**
1. `test_rotate_secret_success` — mock SDK reset + AWS store + probe, verify new secret returned
2. `test_rotate_secret_401` — mock SDK 401 on reset, verify ApiException propagates
3. `test_rotate_secret_aws_store_failure_with_retry` — store fails 3x, verify recovery file written, error propagates
4. `test_rotate_secret_aws_store_retry_succeeds` — store fails once, succeeds on retry, verify success
5. `test_rotate_secret_probe_fails` — reset succeeds + store succeeds + probe 401, verify RuntimeError
6. `test_rotate_is_lock_free` — verify rotate does NOT acquire any lock

**Two-tier orchestrator:**
7. `test_recover_tier1_success` — rotation succeeds, delete NOT called
8. `test_recover_tier2_calls_raw_sdk` — rotation 401 → verify `_delete_snap_trade_user_with_retry` called (NOT `delete_snaptrade_user`), `delete_snaptrade_user_secret(force=True)` called, `_register_snap_trade_user_with_retry` called (NOT `register_snaptrade_user`), position purge called
9. `test_recover_storage_failure_no_tier2` — store fails → error propagates, Tier 2 NOT attempted
10. `test_recover_probe_failure_no_tier2` — probe fails → error propagates, Tier 2 NOT attempted
11. `test_recover_tier2_eventual_consistency` — raw register raises "already exist", succeeds after 2s retry
12. `test_recover_user_id_passed_to_position_service` — verify `user_id` param is used for `PositionService`

**Concurrency:**
13. `test_concurrent_auto_recovery_single_rotation` — two threads hit 401, first rotates, second sees changed secret and skips
14. `test_auto_recovery_skip_if_secret_changed` — failed_secret != current_secret → no rotation, just retry

**Auto-recovery:**
15. `test_auto_recovery_holdings_fetch` — 401 on first call → lock → rotate → retry succeeds
16. `test_auto_recovery_not_on_429` — 429 does NOT trigger recovery

**Endpoint + error surfacing:**
17. `test_reset_secret_endpoint_default_tier` — POST with no `tier` param uses `"rotation"` (not destructive)
18. `test_reset_secret_endpoint_rotation_401_returns_200` — rotation fails with 401, endpoint returns 200 with `success=false, tier2_available=true` (not 500)
19. `test_tier2_api_delete_not_found_continues` — `_delete_snap_trade_user_with_retry` raises "not found" → Tier 2 continues to force-delete + register (doesn't abort)
20. `test_tier2_store_retry_on_failure` — Tier 2's store call retried 2x, writes recovery file on final failure (not logged)
21. `test_tier2_refreshes_account_registry` — verify `AccountRegistry.refresh_combined_portfolio()` and `ensure_single_account_portfolios()` called after Tier 2
22. `test_adapter_fetch_accounts_auto_recovery` — mock 401 on `_list_user_accounts_with_retry` in adapter `_fetch_accounts()` → rotation → retry succeeds
23. `test_secret_not_logged_on_store_failure` — verify the full secret is NOT passed to `log_error()` or `portfolio_logger`, only written to recovery file
24. `test_try_rotate_secret_helper` — mock 401, verify `_try_rotate_secret` acquires lock + rotates when secrets match, skips when they differ
25. `test_trading_search_symbol_auto_recovery` — mock `_symbol_search_user_account_with_retry` 401 → `_try_rotate_secret` rotates → re-read identity → retry succeeds
26. `test_adapter_resolve_authorization_id_recovery` — mock raw `list_brokerage_authorizations` 401 (kwarg user_secret) → `_try_rotate_secret` → re-read → retry
27. `test_adapter_refresh_after_trade_recovery` — mock raw `refresh_brokerage_authorization` 401 (kwarg user_secret) → `_try_rotate_secret` → re-read → retry

**Frontend tests** (in `frontend/packages/connectors/src/features/external/__tests__/useSnapTrade.test.tsx`):
28. `test_auth_error_response_throws_SnapTradeAuthError` — mock API returning `{ success: false, auth_error: true }` → queryFn throws `SnapTradeAuthError` → `connectionsError` is set → hook's `authError` is true
29. `test_auth_error_with_stale_cache_still_shows_authError` — prior successful load cached connections, then refetch returns auth_error → `authError` is true (not suppressed by stale data)
30. `test_resetSecret_mutation_invalidates_all_three_queries` — mock successful reset → verify `snaptradeConnectionsKey`, `snaptradeHoldingsKey`, AND `['accounts', 'list']` queries all invalidated
31. `test_resetSecret_tier2_available_on_rotation_failure` — mock `resetSecret("rotation")` returning `{ success: false, tier2_available: true }` → verify promise resolves (not rejects) with the response body

## Files Changed

| File | Type | Description |
|------|------|-------------|
| `brokerage/snaptrade/client.py` | Modify | Add `_reset_snap_trade_user_secret_with_retry` |
| `brokerage/snaptrade/_shared.py` | Modify | Add `is_snaptrade_secret_error()` |
| `brokerage/snaptrade/recovery.py` | **New** | `rotate_snaptrade_user_secret()`, `recover_snaptrade_auth()`, per-user lock helpers |
| `brokerage/snaptrade/secrets.py` | Modify | Add `force` param to `delete_snaptrade_user_secret()` |
| `brokerage/snaptrade/__init__.py` | Modify | Export recovery functions |
| `providers/snaptrade_loader.py` | Modify | Auto-recovery wrapper in `fetch_snaptrade_holdings()` |
| `brokerage/snaptrade/connections.py` | Modify | Auto-recovery wrapper in `list_snaptrade_connections()` |
| `brokerage/snaptrade/adapter.py` | Modify | Auto-recovery via `_try_rotate_secret()` + re-read in `_fetch_accounts()`, `get_account_balance()`, `refresh_after_trade()`, `_resolve_authorization_id()` |
| `brokerage/snaptrade/trading.py` | Modify | Auto-recovery via `_try_rotate_secret()` + re-read in all 5 trading functions |
| `routes/snaptrade.py` | Modify | Auth error surfacing in `GET /connections` + `POST /api/snaptrade/reset-secret` + `ConnectionsResponse.auth_error` |
| `frontend/.../SnapTradeService.ts` | Modify | `resetSecret()` + response types + `auth_error` on connections |
| `frontend/.../APIService.ts` | Modify | `resetSnapTradeSecret()` delegation |
| `frontend/.../useSnapTrade.ts` | Modify | Auth error throw in queryFn + `resetSecret` mutation + `isResettingSecret` |
| `frontend/.../AccountConnections.tsx` | Modify | "Fix Connection" button in error card |
| `frontend/.../AccountConnectionsContainer.tsx` | Modify | Pass fix-connection props + Tier 2 confirmation |
| `tests/snaptrade/test_snaptrade_recovery.py` | **New** | ~27 backend unit tests |

## Key Functions to Reuse

- `get_snaptrade_user_id_from_email()` — `brokerage/snaptrade/users.py:20`
- `get_snaptrade_user_secret()` — `brokerage/snaptrade/secrets.py:126`
- `store_snaptrade_user_secret()` — `brokerage/snaptrade/secrets.py:82`
- `delete_snaptrade_user_secret()` — `brokerage/snaptrade/secrets.py:153` (adding `force` param)
- `_delete_snap_trade_user_with_retry()` — `brokerage/snaptrade/client.py:139` (API-only delete, for Tier 2)
- `_register_snap_trade_user_with_retry()` — `brokerage/snaptrade/client.py:46` (raw register, for Tier 2)
- `_list_user_accounts_with_retry()` — `brokerage/snaptrade/client.py:76` (post-rotation probe)
- `with_snaptrade_retry()` — `brokerage/snaptrade/_shared.py:95`
- `ApiException` — `brokerage/snaptrade/_shared.py:12`
- `PositionService.delete_provider_positions()` — used in `routes/snaptrade.py:1092` (Tier 2 cleanup)

## Error Handling Matrix

| Scenario | Behavior |
|----------|----------|
| Reset succeeds + store succeeds + probe succeeds | Return new secret, connections preserved |
| Reset succeeds + store fails (after retries) | Write secret to recovery file, re-raise, NO Tier 2 |
| Reset succeeds + store succeeds + probe 401 | RuntimeError "rotated secret rejected", NO Tier 2 |
| Reset fails 401 (auto-recovery) | Let error propagate to frontend |
| Reset fails 401 (manual `tier=rotation`) | Returns 200 `{ success: false, tier2_available: true }` |
| Reset fails 401 (manual `tier=full`) | Tier 2: raw API delete + force AWS delete + purge positions + raw register |
| Reset fails 429/5xx | Retry via decorator, propagate if exhausted |
| Non-auth error (400, 404) | No recovery attempted |
| Concurrent 401s (same user) | First caller rotates under lock; others see changed secret, skip rotation, retry |
| Tier 2 register "already exist" | Retry once after 2s delay (eventual consistency) |
| Default POST /reset-secret | Uses `tier="rotation"` (non-destructive) |
| GET /connections 401 | Returns `success=False, auth_error=True` → queryFn throws → error card |

## Verification

1. `pytest tests/snaptrade/test_snaptrade_recovery.py` — all 27 backend tests pass
2. `pytest tests/snaptrade/` — all existing tests still pass
3. Manual: `POST /api/snaptrade/reset-secret` → verify 200 response, `recovery_method="rotation"`
4. Manual: `POST /api/snaptrade/reset-secret?tier=full` → verify Tier 2, `connections_preserved=false`
5. Manual: `POST /api/snaptrade/reset-secret` with stale secret → verify 200 `{ success: false, tier2_available: true }` (not 500)
6. Manual: `GET /api/snaptrade/connections` with stale secret → verify `success=false, auth_error=true`
7. Frontend: Error card shows "Fix Connection" button, Tier 1 on click, Tier 2 confirmation dialog on failure
8. `cd frontend && npx vitest run packages/connectors/src/features/external/__tests__/useSnapTrade.test.tsx` — all 4 new frontend tests pass

## Codex Review History

### Round 1 — 5 findings

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Concurrency race | Per-user locks at caller site |
| 2 | No post-rotation probe | list_user_accounts probe |
| 3 | Tier 2 cleanup gaps | Position purge + eventual consistency |
| 4 | Default tier destructive | Default → "rotation" |
| 5 | Frontend surface incomplete | Full wiring added |

### Round 2 — 5 findings

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Deadlock: rotate acquires lock + caller acquires lock | rotate is now lock-free |
| 2 | AWS soft-delete 7-day window blocks re-create | `force` param + `ForceDeleteWithoutRecovery` |
| 3 | Frontend error swallowed | Split auth vs non-auth in endpoint + throw in queryFn |
| 4 | Missing user_id in Tier 2 | Added `user_id: int` to signature |
| 5 | Truncated secret not recoverable | Recovery file (`~/.snaptrade_recovery/`) instead of logging |

### Round 3 — 4 findings

| # | Finding | Resolution |
|---|---------|------------|
| 1 | AWS soft-delete still open: `delete_snaptrade_user()` calls non-force delete internally | Tier 2 now calls `_delete_snap_trade_user_with_retry()` + `delete_snaptrade_user_secret(force=True)` directly, NOT the wrapper |
| 2 | Frontend auth error not flowing to `error` prop | queryFn throws on `data.auth_error === true` → react-query treats as error → flows through existing pipeline |
| 3 | Tier 1→2 frontend contract: HTTP client throws on non-2xx | Endpoint always returns 200 on rotation 401 with `{ success: false, tier2_available: true }`. 500 only for unrecoverable. |
| 4 | register_snaptrade_user "already exist" raises RuntimeError | Tier 2 calls `_register_snap_trade_user_with_retry()` directly (raw SDK), NOT the wrapper |

### Round 4 — 4 findings

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Tier 2 drops "not found" cleanup when bypassing wrapper | Tier 2 step 1 now catches "not found" ApiException and continues (matches `delete_snaptrade_user()` line 79 behavior) |
| 2 | Manual endpoint calls rotate without lock | Endpoint now acquires per-user lock via `_get_rotation_lock()` before calling rotate/recover |
| 3 | Tier 2 success doesn't invalidate stale session cache | Hook now invalidates BOTH connections AND holdings on ANY successful reset (not just when `connections_preserved`) |
| 4 | Tier 2 store has no retry hardening | Tier 2 step 7 now uses same retry + recovery file pattern as Tier 1 step 5 |

### Round 5 — 2 findings

| # | Finding | Resolution |
|---|---------|------------|
| 1 | `authError` heuristic (`connections === undefined`) fails with stale session cache | Typed `SnapTradeAuthError` class thrown from queryFn; `authError` derived from `connectionsError instanceof SnapTradeAuthError` (not data presence) |
| 2 | No frontend test coverage for auth error flow + reset mutation | 4 frontend tests added to `useSnapTrade.test.tsx`: auth error throw, stale cache resilience, query invalidation, tier2_available contract |

### Round 6 — PASS (first reviewer)

### Round 6b (fresh reviewer) — 5 findings

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Full secret logged via `log_error()` → credential leak in `errors.jsonl`/`app.log` | Secret written to `~/.snaptrade_recovery/{user_hash}.secret` file (0600 perms) instead. Never passed to `log_error()` or `portfolio_logger`. |
| 2 | Process-local lock insufficient for multi-worker deployment | Replaced "acceptable risk" framing with idempotency argument: all recovery paths (Tier 1 rotation, Tier 2 delete+register, AWS force-delete+create) are idempotent and converge to valid state even under concurrent execution. |
| 3 | Tier 2 doesn't clear DB-backed account rows — stale UI in `AccountConnectionsContainer` | Hook now also invalidates `['accounts', 'list']` query. Tier 2 calls `AccountRegistry.refresh_combined_portfolio()` + `ensure_single_account_portfolios()` (matching DELETE /user at line 1104). |
| 4 | Adapter trading flows (`_fetch_accounts`, `_resolve_authorization_id`) not covered by auto-recovery | Added Step 5b: auto-recovery wrapper in `SnapTradeBrokerAdapter._fetch_accounts()` with same lock-then-check-then-rotate pattern. Direct trading calls read fresh from AWS after rotation. |
| 5 | `is_snaptrade_auth_error` includes 403 but bug is 401 only | Renamed to `is_snaptrade_secret_error()`, narrowed to 401 only. 403 (permission denied) is a different error class where rotation would not help. |

### Round 7 — 2 findings

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Stale references to "CRITICAL log with full secret" in tests and history | Cleaned all references: test 3 → "verify recovery file written", round 2 #5 → "recovery file", round 4 #4 → "recovery file pattern" |
| 2 | Multi-worker Tier 2 race: worker B's force-delete can remove worker A's fresh secret | Tier 2 now has post-store probe (step 9). If probe fails (another worker interfered), re-reads latest secret from AWS and probes that. Last writer wins, probe verifies convergence. |

### Round 8 — 1 finding

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Trading module (`trading.py`) has 5 functions calling SDK with user_secret directly, bypassing adapter. `_fetch_accounts()` doesn't gate trading — `TradeExecutionService` calls trading functions directly. | Added Step 5c: `_try_rotate_secret()` helper + try/except/re-read pattern applied to all 5 trading functions + 4 adapter methods. |

### Round 9 — 1 finding

| # | Finding | Resolution |
|---|---------|------------|
| 1 | `with_secret_recovery` assumes user_secret at positional arg index 2, but adapter raw SDK calls have different signatures | Replaced with signature-agnostic pattern: `_try_rotate_secret(user_email, client, failed_secret)` helper only does lock+check+rotate. Callers use try/except and re-read identity themselves after rotation. Works for retry wrappers (positional) and raw bound SDK methods (kwarg) alike. |

### Round 10 — 1 finding (stale text)

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Old `with_secret_recovery()` still referenced in tests, files table, and Step 5c | Cleaned all active references to `_try_rotate_secret()` pattern |

### Round 11 — 3 findings

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Frontend test only verifies 2 query invalidations, not 3 (missing `['accounts','list']`) | Test renamed to `test_resetSecret_mutation_invalidates_all_three_queries`, verifies all 3 keys |
| 2 | No test for adapter raw-bound SDK methods (`_resolve_authorization_id`, `refresh_after_trade`) | Added tests 26-27: verify kwarg-style SDK calls also trigger `_try_rotate_secret` → re-read → retry |
| 3 | Stale sentence: "_fetch_accounts gates all trading operations" contradicts Step 5c | Corrected to "Add auto-recovery to all 4 adapter methods" |
