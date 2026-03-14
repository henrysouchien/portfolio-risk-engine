# Fix: Server-Side userId Override in Frontend Logging
**Status:** PLANNING

## Context

`routes/frontend_logging.py` has a low-severity userId spoofing vulnerability. In production, `frontend_logging_auth_check()` (line 154) resolves the user from the session cookie via `auth_service.get_user_by_session()`, but discards the identity — returning `True` instead of the user dict. At line 397, the `userId` in the structured log event is taken directly from the client-supplied payload (`log_entry.userId`), allowing an authenticated user to write log entries attributed to any userId.

Similarly, `session` at line 396 falls back to the client-supplied `log_entry.session`, which could also be spoofed.

**Impact**: Low severity (log attribution only, no data access). But for multi-user deployment, log integrity matters for debugging and analytics.

**Fix**: Return the server-resolved user from the auth check and override `userId`/`session` in the structured event with server-authoritative values in production.

## Implementation Steps

### Step 1: Return user dict from auth check

**File:** `routes/frontend_logging.py` — `frontend_logging_auth_check()` (line 154)

Current:
```python
def frontend_logging_auth_check(request: Request):
    if os.getenv('ENVIRONMENT', 'development') == 'development':
        return True
    session_id = request.cookies.get('session_id')
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return True  # <-- discards user identity
```

Change `return True` → `return user`:
```python
def frontend_logging_auth_check(request: Request) -> Union[Dict[str, Any], bool]:
    """Auth check for log ingestion; returns user dict in production, True in dev."""
    if os.getenv('ENVIRONMENT', 'development') == 'development':
        return True
    session_id = request.cookies.get('session_id')
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user  # Dict[str, Any] — keys: user_id (int|str), email, name, tier, google_user_id
```

**Note on `user_id` type**: `get_user_by_session()` returns `Optional[Dict[str, Any]]`. The `user_id` value is `int` from `PostgresSessionStore` but could be `str` from `InMemorySessionStore`. Always convert with `str()`.

### Step 2: Thread auth result through to log processing

**File:** `routes/frontend_logging.py` — `log_frontend()` (line 174)

Change the `Depends` type annotation:

```python
@frontend_logging_router.post('/api/log-frontend', response_model=LogResponse)
async def log_frontend(
    request: Request,
    auth_result: Union[Dict[str, Any], bool] = Depends(frontend_logging_auth_check)
):
```

Pass `auth_result` to both call sites of `process_individual_log()`:
- Line 271: `await process_individual_log(individual_log, request, log_data.get('sessionId', ''), auth_result)`
- Line 275: `await process_individual_log(individual_log, request, log_data.get('session', ''), auth_result)`

### Step 3: Override userId AND session with server-resolved identity

**File:** `routes/frontend_logging.py` — `process_individual_log()` (line 323)

Add `auth_result` parameter:

```python
async def process_individual_log(
    log_entry: LogEntry,
    request: Request,
    session_id: str = '',
    auth_result: Union[Dict[str, Any], bool] = True,
):
```

At lines 396-397, replace client-supplied values with server-resolved ones when available:

```python
    # Server-authoritative identity: override client-supplied userId/session in production.
    # auth_result is a user dict in production, True in dev.
    # IMPORTANT: session_id comes from the request BODY (log_data['sessionId'] or log_data['session']),
    # NOT from the cookie — so it is also client-supplied and must be overridden in production.
    if isinstance(auth_result, dict):
        resolved_user_id = str(auth_result.get('user_id', ''))
        resolved_session = request.cookies.get('session_id', '')  # Use cookie, not body
    else:
        resolved_user_id = log_entry.userId or ''
        resolved_session = session_id or log_entry.session or ''

    structured_event = {
        "timestamp": timestamp,
        "level": level,
        "category": category,
        "component": component,
        "message": message,
        "url": url,
        "data": log_entry.data or {},
        "session": resolved_session,
        "userId": resolved_user_id,
    }
```

**Key fix from review**: The `session_id` parameter passed to `process_individual_log()` comes from the request body (`log_data.get('sessionId', '')`) — NOT from the auth cookie. So in production, we must read the cookie directly from `request.cookies.get('session_id', '')` to get the server-validated session.

### Step 4: Update existing test helper

**File:** `tests/routes/test_frontend_logging_auth.py`

The existing `_noop_process_individual_log` (line 20) accepts 3 args but `log_frontend()` will now pass 4 (adding `auth_result`). Update the signature:

```python
async def _noop_process_individual_log(log_entry, request, session_id="", auth_result=True):
    return None
```

### Step 5: Add new tests

**File:** `tests/routes/test_frontend_logging_auth.py`

Add three tests:

1. **`test_production_overrides_client_userid`** — In production, send a log with `userId: "spoofed_123"`, mock `log_frontend_event` to capture the structured event, verify it has `userId: "88"` (from server-resolved user dict `{"user_id": 88}`), not the client-supplied value.

2. **`test_production_overrides_client_session`** — In production, send a batch with `sessionId: "spoofed_sess"`, verify the structured event `session` field equals the cookie value (`"frontend-session"`), not the body value.

3. **`test_dev_uses_client_userid`** — In development, send a log with `userId: "client_456"`, verify the structured event keeps the client-supplied value (dev mode returns `True`, no server user to resolve).

Mock `log_frontend_event` at its **import site** — monkeypatch `routes.frontend_logging.log_frontend_event` (i.e. `frontend_logging_routes.log_frontend_event`), NOT `utils.logging.log_frontend_event`, because the route module imports the function directly at line 46. Do NOT monkeypatch `process_individual_log` in these tests — let the real function run so we can assert the structured event content.

## Files Changed (2)

| File | Change | ~Lines |
|------|--------|--------|
| `routes/frontend_logging.py` | Return user dict from auth, thread through, override userId + session | ~15 net |
| `tests/routes/test_frontend_logging_auth.py` | Fix `_noop` signature + add 3 new tests | ~40 |

## Verification

1. `cd /Users/henrychien/Documents/Jupyter/risk_module && python -m pytest tests/routes/test_frontend_logging_auth.py -v` — all tests pass (existing 4 + new 3)
2. `cd /Users/henrychien/Documents/Jupyter/risk_module && python -m pytest tests/ -x --timeout=60 -q` — no regressions
