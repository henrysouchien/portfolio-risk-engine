# Multi-User Isolation Audit Fix Plan
**Status:** DONE

**Priority:** High | **Added:** 2026-03-09

## Context

Full multi-user readiness audit found 3 gaps. The database schema is multi-user (all tables have `user_id` FK), auth is enforced on all routes, and caching is user-scoped. But 2 `DatabaseClient` methods and 1 route auth check have isolation gaps.

## Findings

| # | Severity | File | Method/Function | Issue |
|---|----------|------|-----------------|-------|
| 1 | Critical | `inputs/database_client.py` | `delete_provider_item(provider, item_id)` | WHERE clause lacks `user_id` filter. Any caller could delete another user's provider item mapping. |
| 2 | Critical | `inputs/database_client.py` | `set_provider_item_reauth(provider, item_id, needs_reauth)` | WHERE clause lacks `user_id` filter. Any caller could flip another user's reauth flag. |
| 3 | Low | `routes/frontend_logging.py` | `frontend_logging_auth_check()` | Returns `True` unconditionally in dev mode. Production path has a TODO for session validation. |

## Changes

### Fix 1 — `delete_provider_item()` (Critical)

**File:** `inputs/database_client.py`

Add `user_id: int` parameter. Add `AND user_id = %s` to WHERE clause.

Before:
```python
def delete_provider_item(self, provider: str, item_id: str) -> None:
    ...
    cursor.execute(
        "DELETE FROM provider_items WHERE provider = %s AND item_id = %s",
        (str(provider or "").strip().lower(), item_id),
    )
```

After:
```python
def delete_provider_item(self, user_id: int, provider: str, item_id: str) -> None:
    ...
    cursor.execute(
        "DELETE FROM provider_items WHERE provider = %s AND item_id = %s AND user_id = %s",
        (str(provider or "").strip().lower(), item_id, user_id),
    )
```

**Callers to update:**
- `routes/plaid.py` line ~1502 — `disconnect_plaid()` route handler. Has `user['user_id']` in scope from session auth. Pass it through.

### Fix 2 — `set_provider_item_reauth()` (Critical)

**File:** `inputs/database_client.py`

Add `user_id: int` parameter. Add `AND user_id = %s` to WHERE clause.

Before:
```python
def set_provider_item_reauth(self, provider: str, item_id: str, needs_reauth: bool) -> None:
    ...
    cursor.execute(
        """
        UPDATE provider_items
        SET needs_reauth = %s, updated_at = NOW()
        WHERE provider = %s AND item_id = %s
        """,
        (bool(needs_reauth), str(provider or "").strip().lower(), item_id),
    )
```

After:
```python
def set_provider_item_reauth(self, user_id: int, provider: str, item_id: str, needs_reauth: bool) -> None:
    ...
    cursor.execute(
        """
        UPDATE provider_items
        SET needs_reauth = %s, updated_at = NOW()
        WHERE provider = %s AND item_id = %s AND user_id = %s
        """,
        (bool(needs_reauth), str(provider or "").strip().lower(), item_id, user_id),
    )
```

**Callers to update:**
- `routes/plaid.py` — `_set_provider_item_reauth()` wrapper (line ~266). Currently takes `(item_id, needs_reauth)`. Add `user_id` param.
- `scripts/plaid_reauth.py` — `_clear_reauth_flag()` (line ~108). CLI script that operates on a specific user's item. Resolve `user_id` from the user_email param already available in caller scope.

**Webhook caller detail — ITEM webhook path needs user resolution for mutating operations:**

The ITEM webhook branch (lines ~1363-1397 in `routes/plaid.py`) currently calls `_set_provider_item_reauth(item_id, needs_reauth)` directly — it does NOT resolve the owning user first. Only the INVESTMENTS branch calls `_set_plaid_pending_updates_for_item()` which does its own user lookup.

Fix: Resolve the owner only for the 3 mutating codes (`ITEM_LOGIN_REQUIRED`, `PENDING_EXPIRATION`, `LOGIN_REPAIRED`). Non-mutating codes (`USER_PERMISSION_REVOKED`, `WEBHOOK_UPDATE_ACKNOWLEDGED`, other `ERROR` codes) continue to log without needing ownership. This preserves existing logging behavior for informational events even when the item mapping is missing.

```python
elif webhook_type == "ITEM":
    if webhook_code == "ERROR":
        error_data = webhook_data.error or {}
        error_code = error_data.get("error_code", "")
        if error_code == "ITEM_LOGIN_REQUIRED":
            # Mutating: resolve owner
            item_owner = _resolve_item_owner(item_id)
            if item_owner:
                _set_provider_item_reauth(item_owner["user_id"], item_id, True)
        else:
            portfolio_logger.error(...)  # Non-mutating, no owner needed
    elif webhook_code == "PENDING_EXPIRATION":
        item_owner = _resolve_item_owner(item_id)
        if item_owner:
            _set_provider_item_reauth(item_owner["user_id"], item_id, True)
    elif webhook_code == "LOGIN_REPAIRED":
        item_owner = _resolve_item_owner(item_id)
        if item_owner:
            _set_provider_item_reauth(item_owner["user_id"], item_id, False)
    elif webhook_code == "USER_PERMISSION_REVOKED":
        portfolio_logger.warning(...)  # Non-mutating, no owner needed
    ...
```

Add a small helper to keep the resolution DRY:
```python
def _resolve_item_owner(item_id: str) -> Optional[dict]:
    """Resolve owning user for a Plaid item_id. Returns None if mapping missing."""
    if not item_id:
        return None
    try:
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            return db_client.get_user_by_provider_item("plaid", item_id)
    except Exception as e:
        portfolio_logger.warning(f"⚠️ Failed to resolve owner for item_id={item_id}: {e}")
        return None
```

When `_resolve_item_owner()` returns `None`, log a warning and skip the reauth update — do not fail the webhook (return 200 to Plaid to prevent retries).

Update `_set_provider_item_reauth()` wrapper signature to `(user_id: int, item_id: str, needs_reauth: bool)`.

### Fix 3 — `frontend_logging_auth_check()` (Low)

**File:** `routes/frontend_logging.py`

Two endpoints use this dependency:
- `POST /api/log-frontend` — log ingestion (should require auth in production)
- `GET /api/log-frontend/health` — health check (should remain public for load balancers/monitors)

**Change:** Split the health endpoint to bypass auth. Apply session validation only to the POST endpoint.

Before:
```python
def frontend_logging_auth_check(request: Request):
    if os.getenv('ENVIRONMENT', 'development') == 'development':
        return True
    # TODO: In production, implement user session validation here
    client_ip = request.client.host if request.client else "unknown"
    frontend_logger.info(f"[FRONTEND-LOGGING] Request from {client_ip}")
    return True
```

After:
```python
def frontend_logging_auth_check(request: Request):
    """Auth check for log ingestion — requires session in production."""
    if os.getenv('ENVIRONMENT', 'development') == 'development':
        return True
    session_id = request.cookies.get('session_id')
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return True
```

Remove `Depends(frontend_logging_auth_check)` from the health endpoint so it stays public:
```python
@frontend_logging_router.get('/api/log-frontend/health', response_model=LogResponse)
async def frontend_logging_health(request: Request):
    # No auth required — public health check for load balancers
    ...
```

Add import for `auth_service` at top of file if not already present. `HTTPException` is already imported from FastAPI.

### Noted: `store_provider_item()` ownership transfer risk

**Not fixing in this PR** but worth noting: `store_provider_item()` uses `ON CONFLICT (provider, item_id) DO UPDATE SET user_id = ...`, meaning a write with a different `user_id` silently reassigns ownership. This is by design for legitimate re-linking scenarios (user disconnects and reconnects Plaid).

Exploitability is limited today because all call sites are trusted server-side/admin write paths:
- `routes/plaid.py` — called after OAuth token exchange, `user['user_id']` from session auth
- `routes/snaptrade.py` — called during authenticated connection setup, `user_id` from session

Note: SnapTrade's `item_id` is a deterministic hash of email (in `providers/snaptrade_loader.py:340`), not an opaque token like Plaid's. Both are safe today because writes only happen in authenticated server-side contexts, but this helper should be revisited if any unauthenticated write path is ever added.

## Files Changed

| File | Change |
|------|--------|
| `inputs/database_client.py` | Add `user_id` param to `delete_provider_item()` and `set_provider_item_reauth()` |
| `routes/plaid.py` | Add user resolution at top of ITEM webhook branch. Thread `user_id` to both wrapper functions. Update `_set_provider_item_reauth()` wrapper signature. |
| `scripts/plaid_reauth.py` | Thread `user_id` to `_clear_reauth_flag()` |
| `routes/frontend_logging.py` | Implement production session auth for POST. Remove auth dependency from health endpoint. |
| `tests/api/test_plaid_webhook.py` | Update monkeypatched `_set_provider_item_reauth` signatures to include `user_id`. Add monkeypatch for `_resolve_item_owner` (or patch `get_db_session` + `DatabaseClient.get_user_by_provider_item`) to control owner resolution. Add test for missing/stale mapping → webhook returns 200 with no reauth update. |
| `tests/multi_user/test_provider_item_isolation.py` (new) | Verify user A cannot modify user B's provider items |
| `tests/routes/test_frontend_logging_auth.py` (new) | Verify production auth enforcement + health endpoint stays public |

## Tests

1. **Provider item delete isolation**: Create items for user A and user B. User A's delete call should not affect user B's item.
2. **Provider item reauth isolation**: User A's reauth flag change should not affect user B's item.
3. **Webhook user resolution + threading**: Stub `get_user_by_provider_item` to return a user dict. Verify ITEM webhook calls `_set_provider_item_reauth` with the resolved `user_id`.
4. **Webhook missing mapping**: Stub `get_user_by_provider_item` to return `None`. Verify ITEM webhook returns 200 and does NOT call `_set_provider_item_reauth`.
5. **Frontend logging production auth**: With `ENVIRONMENT=production`, unauthenticated POST requests get 401. Authenticated POST requests succeed.
6. **Frontend logging health stays public**: With `ENVIRONMENT=production`, health endpoint returns 200 without session cookie.
7. **Frontend logging dev bypass**: With `ENVIRONMENT=development`, all requests succeed without session.

## Verification

1. `python3 -m pytest tests/multi_user/ -x -q`
2. `python3 -m pytest tests/api/test_plaid_webhook.py -x -q`
3. `python3 -m pytest tests/routes/test_frontend_logging_auth.py -x -q`
4. `python3 -m pytest tests/ -x -q` — full suite passes
