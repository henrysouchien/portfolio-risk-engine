# Fix: PostgreSQL Connection Pool Exhaustion Cascading Failures
**Status:** DONE

## Context

PostgreSQL connections leak until the pool is fully exhausted ("too many clients already"). The MCP server cached `is_db_available()=True` at startup and keeps trying the DB path for every operation, causing cascading failures like "No provider could price SPY". Only fix is `sudo pg_ctl restart`.

**Root causes:**
1. `is_db_available()` caches `True` forever — no TTL, no invalidation on errors
2. `get_db_session()` has no error handling on `pool.getconn()` — raw `psycopg2.pool.PoolError` propagates
3. No mechanism to fall back gracefully when pool exhaustion hits mid-session
4. PostgreSQL `max_connections=100`, pool max=20/process. 2 dev workers × 20 + MCP × 20 = 60 (tight but OK). Production 4 workers would be 100 (zero headroom).

**Cascade failure chain:**
1. Connections leak or accumulate → pool exhausted → `pool.getconn()` raises `psycopg2.pool.PoolError`
2. `is_db_available()` cached `True` forever → never falls back to YAML
3. Every tool call tries DB path → fails → misleading pricing errors
4. `PoolError` inherits from `psycopg2.Error`, NOT `OperationalError` — existing `OperationalError` catches don't help

## Current Architecture

### Pool Layer (`app_platform/db/pool.py`)
- `PoolManager` wraps `psycopg2.pool.SimpleConnectionPool`
- Default: `DB_POOL_MIN=5`, `DB_POOL_MAX=20` (env-configurable)
- Process-global singleton via `_get_default_manager()`

### Session Layer (`app_platform/db/session.py`)
```python
@contextmanager
def get_db_session(self):
    pool = self._get_pool()
    conn = pool.getconn()          # ← NO error handling
    with _M_LOCK:
        _METRICS["active"] += 1
        _METRICS["total"] += 1
    try:
        yield conn
    finally:
        pool.putconn(conn)
        with _M_LOCK:
            _METRICS["active"] -= 1
```

### Availability Cache (`database/__init__.py`)
```python
_db_available: bool | None = None  # Positive-only cache — True forever

def is_db_available() -> bool:
    global _db_available
    if _db_available is True:
        return True              # ← Never re-checks once True
    # ... probe with SELECT 1 ...
    _db_available = True
    return True
```

### Error Infrastructure (exists but unused)
- `app_platform/db/exceptions.py` defines `PoolExhaustionError` — never raised
- `is_recoverable_error()` classifies `PoolExhaustionError` as recoverable — never called
- `inputs/exceptions.py` re-exports with `ErrorCodes.POOL_EXHAUSTED = "DB_002"` — never used

### Shim Layer (`database/session.py`)
Pure re-export:
```python
from app_platform.db.session import SessionManager, _METRICS, get_db_session
```

### MCP Error Handling (`mcp_tools/common.py`)
- `@handle_mcp_errors` catches `Exception` → `{"status": "error", "error": str(e)}`
- `@require_db` checks `is_db_available()` per call — but once cached True, always True

## Changes

### Fix 1: `database/__init__.py` — TTL + `mark_db_unavailable()`

Add a 5-minute TTL to the positive `is_db_available()` cache using `time.monotonic()`. Add `mark_db_unavailable()` that sets a **cooldown period** (30s) during which `is_db_available()` returns `False` without re-probing. This prevents the probe from immediately re-caching `True` on a transient free slot while the pool is still under pressure.

```python
import time
import psycopg2

_db_available: bool | None = None
_db_available_at: float = 0.0
_db_unavailable_until: float = 0.0   # cooldown: don't re-probe until this time
_db_lock = threading.Lock()
_DB_TTL = 300           # 5 minutes — positive cache lifetime
_DB_COOLDOWN = 30       # 30 seconds — suppress re-probe after invalidation

def is_db_available() -> bool:
    global _db_available, _db_available_at, _db_unavailable_until

    # Cooldown: recently marked unavailable → return False without probing
    if _db_unavailable_until > 0 and time.monotonic() < _db_unavailable_until:
        return False

    # Fast path: cached True within TTL (no lock)
    if _db_available is True:
        if (time.monotonic() - _db_available_at) < _DB_TTL:
            return True
        # TTL expired — fall through to locked re-check (do NOT write
        # _db_available = None here; that would clobber a concurrent
        # thread's fresh probe result)

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return False

    with _db_lock:
        # Double-check cooldown and TTL inside lock
        if _db_unavailable_until > 0 and time.monotonic() < _db_unavailable_until:
            return False
        if _db_available is True and (time.monotonic() - _db_available_at) < _DB_TTL:
            return True
        try:
            from app_platform.db.session import get_db_session as _platform_get_db_session
            from app_platform.db.exceptions import PoolExhaustionError, ConnectionError
            with _platform_get_db_session() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT 1")
                finally:
                    close_cursor = getattr(cursor, "close", None)
                    if callable(close_cursor):
                        close_cursor()
            _db_available = True
            _db_available_at = time.monotonic()
            return True
        except (
            PoolExhaustionError,
            ConnectionError,
            psycopg2.OperationalError,
        ):
            # Connection/pool error — arm cooldown. Catches both:
            # - Wrapped exceptions from Fix 2 (getconn failures)
            # - Raw psycopg2.OperationalError from cursor.execute
            #   (connection dropped after successful getconn)
            _db_available = None
            _db_unavailable_until = time.monotonic() + _DB_COOLDOWN
            return False
        except Exception:
            # Config, import, or unexpected error — don't arm cooldown
            # (may be permanent, re-probe immediately on next call)
            _db_available = None
            return False


def mark_db_unavailable() -> None:
    """Force is_db_available() to return False for _DB_COOLDOWN seconds.

    Called when pool exhaustion or connection errors are detected.
    The cooldown prevents re-probing from immediately re-caching True
    on a transient free slot while the pool is still under pressure.
    After cooldown expires, the next call re-probes with SELECT 1.
    """
    global _db_available, _db_unavailable_until
    with _db_lock:
        _db_available = None
        _db_unavailable_until = time.monotonic() + _DB_COOLDOWN


__all__ = ["get_db_session", "get_pool", "is_db_available", "mark_db_unavailable", "is_db_in_cooldown"]
```

Key design points:
- `time.monotonic()` is immune to clock adjustments
- **Cooldown period** (30s): after `mark_db_unavailable()`, returns `False` without probing — stops the cascade
- After cooldown expires, re-probes with `SELECT 1` — allows recovery when pool is healthy again
- Fast path (cached True within TTL, no cooldown) has zero locking overhead
- `is_db_available()` probe uses `app_platform.db.session.get_db_session` directly (not the shim) to avoid triggering the callback during probing

**Self-healing property**: Two paths re-arm the cooldown:
1. **Probe fails with connection error**: If cooldown expires and the probe fails with `PoolExhaustionError`, `ConnectionError` (wrapped by Fix 2 on getconn), or raw `psycopg2.OperationalError` (from cursor.execute after successful getconn), cooldown is re-armed — no requests even attempt the DB path. Other exceptions (config errors, import errors) do NOT arm cooldown — they set `_db_available = None` without cooldown so the next call re-probes immediately.
2. **Probe succeeds but pool still saturated**: The next `get_db_session()` call that fails will hit `PoolError` or `OperationalError` → `on_pool_error` callback fires → `mark_db_unavailable()` restarts the cooldown. During each 30s window, `@require_db`-decorated MCP tools return the "Database temporarily unavailable" error dict (see Fix 5), and other callers that check `is_db_available()` skip the DB path. **Note**: callers that go directly to `get_db_session()` without checking `is_db_available()` (e.g. routes, services) are NOT gated by cooldown — they will still attempt DB operations and get `PoolExhaustionError`/`ConnectionError`. Fix 4 (503 handler) catches those for unhandled REST paths (routes that don't catch `Exception` broadly). Routes with broad `except Exception` blocks (e.g. plaid, positions) will log the error but won't hit the 503 handler — Fix 2's callback still fires on those failures to re-arm cooldown. There may be a brief burst of failures between re-probe success and the next connection error, but the burst is bounded and the cooldown restarts immediately on the first failure.

**Lock-free fast path race**: The cooldown and TTL checks outside the lock are deliberately unsynchronized for zero-contention hot path. The outside-lock code only reads globals (never writes — the expired-TTL path falls through without setting `_db_available = None`, avoiding clobber of concurrent fresh probes). Worst case: a few threads read "no cooldown + cached True" just as another thread calls `mark_db_unavailable()`. Those threads proceed to `get_db_session()`, get connection errors, and the callback re-fires `mark_db_unavailable()`. The race window is brief and self-corrects on the first failure.

### Fix 2: `app_platform/db/session.py` — Catch `PoolError` + callback

Wrap connection acquisition to catch **both** `psycopg2.pool.PoolError` (local pool exhaustion: all slots in use) and `psycopg2.OperationalError` (server-side rejection: "too many clients already"). The try/except covers both `_get_pool()` and `pool.getconn()` because `SimpleConnectionPool.__init__()` opens `minconn` connections immediately — if PostgreSQL is at `max_connections`, the `OperationalError` fires during pool creation, not `getconn()`.

```python
import logging
import psycopg2
from psycopg2.pool import PoolError
from .exceptions import ConnectionError, PoolExhaustionError

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, pool_manager=None, pool_getter=None, on_pool_error=None):
        if pool_manager is not None and pool_getter is not None:
            raise ValueError("Provide either pool_manager or pool_getter, not both")
        self._pool_manager = pool_manager
        self._pool_getter = pool_getter
        self._on_pool_error = on_pool_error  # NEW

    @contextmanager
    def get_db_session(self):
        try:
            pool = self._get_pool()
            conn = pool.getconn()
        except PoolError as exc:
            # All local pool slots in use
            logger.error("Connection pool exhausted: %s", exc)
            self._fire_pool_error(exc)
            raise PoolExhaustionError(
                "Connection pool exhausted — all connections in use",
                original_error=exc,
            ) from exc
        except psycopg2.OperationalError as exc:
            # Server rejected connection (too many clients, auth, network)
            logger.error("Connection acquisition failed: %s", exc)
            self._fire_pool_error(exc)
            raise ConnectionError(
                f"Cannot acquire database connection: {exc}",
                original_error=exc,
            ) from exc
        with _M_LOCK:
            _METRICS["active"] += 1
            _METRICS["total"] += 1
        try:
            yield conn
        finally:
            pool.putconn(conn)
            with _M_LOCK:
                _METRICS["active"] -= 1

    def _fire_pool_error(self, exc):
        if self._on_pool_error is not None:
            try:
                self._on_pool_error(exc)
            except Exception:
                pass  # callback must not break the raise
```

Two failure modes caught with **distinct exception types**:
- `PoolError` → `PoolExhaustionError`: local pool has `maxconn` connections checked out
- `psycopg2.OperationalError` → `ConnectionError` (from `app_platform.db.exceptions`): server rejected connection (too many clients, auth failure, network error)

Both fire the `on_pool_error` callback (extracted to `_fire_pool_error()` helper). Both trigger cooldown via the callback. Both `_get_pool()` and `getconn()` are inside the try/except because `SimpleConnectionPool(minconn=5)` opens connections in its constructor — an `OperationalError` during pool init is the same class of failure as one during `getconn()`.

**Pool retry**: `PoolManager.get_pool()` still leaves `self._pool = None` on failure, so subsequent calls retry pool creation automatically. The only change is that the `OperationalError` from failed pool creation is now caught, wrapped as `ConnectionError`, and fires the callback.

`app_platform` stays independent — it imports only from psycopg2 and its own exceptions module.

### Fix 3: `database/session.py` — Wire callback

Promote from pure re-export to thin wrapper that creates a `SessionManager` with `on_pool_error=mark_db_unavailable` wired. Lazy singleton with lock.

```python
"""Backward-compatible shim with pool-error callback wired."""

import threading
from app_platform.db.session import SessionManager, _METRICS

_session_manager = None
_session_lock = threading.Lock()


def _get_manager():
    global _session_manager
    if _session_manager is None:
        with _session_lock:
            if _session_manager is None:
                from database import mark_db_unavailable
                _session_manager = SessionManager(
                    on_pool_error=lambda exc: mark_db_unavailable()
                )
    return _session_manager


def get_db_session():
    """Return a context manager for the process-global default DB session."""
    return _get_manager().get_db_session()


__all__ = ["SessionManager", "get_db_session", "_METRICS"]
```

All `from database import get_db_session` callers get the callback-wired version. Direct `from app_platform.db.session import get_db_session` (used only by `is_db_available()` for probing) stays un-wired.

### Fix 4: `app.py` — 503 handler for connection errors (best-effort)

Register exception handlers inside `create_app()`. **Note**: This is best-effort — many route handlers catch `Exception` broadly (e.g. plaid, positions) before FastAPI dispatches to global handlers, so this only covers unhandled REST paths.

Scoped to `PoolExhaustionError` and `ConnectionError` only — NOT the base `DatabaseError`.

Define the handler in **`app_platform/db/handlers.py`** (new, side-effect-free — importable without triggering `app.py` startup):

```python
# app_platform/db/handlers.py
import logging
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

async def db_connection_error_handler(request: Request, exc: Exception):
    logger.error(
        "Database connection error on %s %s: %s", request.method, request.url.path, exc
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": "Service temporarily unavailable",
            "message": "Database connection unavailable. Please retry shortly.",
            "type": "database_error",
        },
    )
```

Register in `app.py` `create_app()`:

```python
# Inside create_app():
from app_platform.db.exceptions import PoolExhaustionError, ConnectionError
from app_platform.db.handlers import db_connection_error_handler

app.add_exception_handler(PoolExhaustionError, db_connection_error_handler)
app.add_exception_handler(ConnectionError, db_connection_error_handler)
```

Does NOT catch generic `DatabaseError` to avoid false 503s on validation/permission/not-found errors.

### Fix 5: `mcp_tools/common.py` — Defense-in-depth + distinct `@require_db` message

**`@handle_mcp_errors`**: After catching any Exception, check if it's a `PoolExhaustionError` or `ConnectionError` → call `mark_db_unavailable()`. Belt-and-suspenders for code that imports `get_db_session` directly from `app_platform` (bypassing the shim). Scoped to the two concrete connection-error types — NOT the base `DatabaseError`, which includes `ValidationError`, `DatabasePermissionError`, etc.

```python
def handle_mcp_errors(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        _saved = sys.stdout
        sys.stdout = sys.stderr
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            portfolio_logger.error(f"{fn.__name__} failed: {e}")
            # Defense-in-depth: invalidate DB cache on pool/connection errors
            try:
                from app_platform.db.exceptions import PoolExhaustionError, ConnectionError
                if isinstance(e, (PoolExhaustionError, ConnectionError)):
                    from database import mark_db_unavailable
                    mark_db_unavailable()
            except Exception:
                pass
            return {"status": "error", "error": str(e)}
        finally:
            sys.stdout = _saved
    return wrapper
```

**`@require_db`**: Distinguish "not configured" from "temporarily unavailable". Check `DATABASE_URL` first (config absence always means "not configured", regardless of cooldown state). Then `is_db_available()`. Then cooldown for the "temporarily unavailable" message. The cooldown message is generic ("Database temporarily unavailable") — not "pool recovering" — because `ConnectionError` covers auth, network, and pool failures.

```python
def require_db(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        import os
        from database import is_db_available, is_db_in_cooldown

        # Config absence takes precedence — always "not configured"
        if not os.getenv("DATABASE_URL", "").strip():
            return {
                "status": "error",
                "error": (
                    "This feature requires a PostgreSQL database. "
                    "Set DATABASE_URL in your .env file to enable it."
                ),
            }
        if not is_db_available():
            if is_db_in_cooldown():
                return {
                    "status": "error",
                    "error": "Database temporarily unavailable. Please retry shortly.",
                }
            # DATABASE_URL is set, no cooldown — probe failed with a non-connection
            # error (import error, config parse error, etc.). Connection errors
            # arm cooldown and hit the branch above.
            return {
                "status": "error",
                "error": "Database unavailable. Check configuration and logs.",
            }
        return fn(*args, **kwargs)
    return wrapper
```

**`database/__init__.py`**: Add `is_db_in_cooldown()`:
```python
def is_db_in_cooldown() -> bool:
    """Return True if DB was recently marked unavailable and cooldown is active."""
    return _db_unavailable_until > 0 and time.monotonic() < _db_unavailable_until
```

Export in `__all__`.

## Files

| File | Change |
|------|--------|
| `database/__init__.py` | TTL on `is_db_available()`, add `mark_db_unavailable()` |
| `app_platform/db/session.py` | Catch `PoolError` → `PoolExhaustionError`, `on_pool_error` callback |
| `database/session.py` | Promote from re-export to callback-wired wrapper |
| `app_platform/db/handlers.py` (new) | `db_connection_error_handler` (side-effect-free, importable for tests) |
| `app.py` | Register 503 handlers in `create_app()` via `app.add_exception_handler()` |
| `mcp_tools/common.py` | Defense-in-depth `PoolExhaustionError`/`ConnectionError` catch + distinct `@require_db` message |
| `tests/database/test_pool_exhaustion.py` (new) | TTL, cooldown, invalidation, callback, recovery tests |
| `tests/app_platform/test_db_session.py` | Add PoolError catch + callback tests |
| `tests/app_platform/test_shim_db.py` | Update `get_db_session` identity test → behavioral test |

## Tests

### `tests/database/test_pool_exhaustion.py` (new)

**Shared fixture**: `@pytest.fixture(autouse=True)` that:
- Saves and restores `database._db_available`, `database._db_available_at`, `database._db_unavailable_until`, and `database.session._session_manager` after each test
- Sets `DATABASE_URL` to a dummy value via `monkeypatch.setenv` so probe-path tests actually reach the probe logic (without `DATABASE_URL`, `is_db_available()` returns False before probing)
Prevents test order dependencies across all tests in this module.

1. **test_is_db_available_ttl_expires** — Set `_db_available=True`, `_db_available_at` to 400s ago. Mock DB probe to fail → returns `False`. (The no-write-outside-lock invariant is enforced by code comment and code review; `threading.Lock.acquire` is not patchable for interleaving tests.)
2. **test_is_db_available_within_ttl_returns_cached** — Set `_db_available=True`, `_db_available_at` to 10s ago → returns `True` without probing.
3. **test_mark_db_unavailable_invalidates_cache** — Set `_db_available=True`. Call `mark_db_unavailable()`. Verify `_db_available is None` and cooldown is set.
4. **test_mark_db_unavailable_cooldown_suppresses_reprobe** — After `mark_db_unavailable()`, `is_db_available()` returns `False` immediately without probing (even if DB is healthy). Verify no `SELECT 1` call during cooldown.
5. **test_mark_db_unavailable_cooldown_expires_then_recovery** — After `mark_db_unavailable()`, advance time past cooldown, mock DB probe to succeed → `is_db_available()` returns `True`.
5b. **test_cooldown_expires_probe_fails_connection_error_rearms_cooldown** — After cooldown expires, monkeypatch `app_platform.db.session.get_db_session` to raise `ConnectionError` → `is_db_available()` returns `False` AND cooldown is re-armed.
5b2. **test_cooldown_expires_probe_fails_pool_exhaustion_rearms_cooldown** — Same as 5b but raise `PoolExhaustionError` → cooldown is also re-armed.
5b3. **test_probe_cursor_execute_failure_arms_cooldown** — Monkeypatch `app_platform.db.session.get_db_session` to return a context manager that yields a mock connection whose `cursor().execute()` raises raw `psycopg2.OperationalError`. Verify `is_db_available()` returns `False` AND cooldown is re-armed.
5c. **test_probe_config_error_does_not_arm_cooldown** — Mock DB probe to raise `ValueError` (simulating bad config). Verify `is_db_available()` returns `False` but cooldown is NOT armed (`_db_unavailable_until` unchanged). Next call re-probes immediately.
6. **test_require_db_during_cooldown_returns_temporary_message** — With `DATABASE_URL` set, after `mark_db_unavailable()`, `@require_db` returns "Database temporarily unavailable" error dict (not the "Set DATABASE_URL" message).
6b. **test_require_db_no_database_url_returns_config_message** — With `DATABASE_URL` unset/empty AND cooldown active, `@require_db` returns "Set DATABASE_URL" message. Also patch `database.is_db_available` to `assert_not_called()` to prove the short-circuit happens before `is_db_available()` is invoked.
6c. **test_require_db_probe_failure_arms_cooldown_then_returns_temporary** — With `DATABASE_URL` set, no pre-existing cooldown, mock DB probe to fail with `ConnectionError`. `is_db_available()` returns False and arms cooldown during the call. Verify `@require_db` returns "temporarily unavailable" (not "Set DATABASE_URL") — proves cooldown detection works even when cooldown is armed during `is_db_available()` itself.
6d. **test_require_db_config_error_returns_generic_unavailable** — With `DATABASE_URL` set, mock DB probe to raise `ValueError` (no cooldown armed). Verify `@require_db` returns "Database unavailable. Check configuration and logs." (not "Set DATABASE_URL" or "temporarily unavailable").
7. **test_shim_get_db_session_fires_mark_db_unavailable_on_pool_error** — Reset `database.session._session_manager = None` (the memoized singleton) before the test so `_get_manager()` re-initializes with a fresh callback binding. Then use `database.get_db_session` (the shim), mock pool to raise `PoolError` → verify `mark_db_unavailable()` was called (integration test for the wired callback). Use a fixture to restore the singleton after test.
8. **test_handle_mcp_errors_invalidates_on_connection_errors** — Decorate a function that raises `PoolExhaustionError`. Verify it returns error dict AND calls `mark_db_unavailable()`. Repeat with `ConnectionError` to confirm both types trigger invalidation.
8b. **test_handle_mcp_errors_does_not_invalidate_on_generic_database_error** — Decorate a function that raises a generic `DatabaseError` (e.g. `ValidationError`). Verify it returns error dict but does NOT call `mark_db_unavailable()` — only connection-acquisition errors should trigger cooldown.

### `tests/app_platform/test_db_session.py` (additions)

9. **test_get_db_session_catches_pool_error_and_raises_exhaustion** — Mock pool.getconn() to raise `PoolError` → `PoolExhaustionError` raised.
10. **test_get_db_session_catches_operational_error_and_raises_connection_error** — Mock pool.getconn() to raise `psycopg2.OperationalError` → `ConnectionError` raised AND `on_pool_error` callback fired (verifies the common "pool exists, server rejects" path triggers cooldown).
10b. **test_get_db_session_catches_pool_creation_operational_error** — Mock `_get_pool()` to raise `psycopg2.OperationalError` (simulating `SimpleConnectionPool.__init__` failure at max_connections) → `ConnectionError` raised AND callback fired. Then mock `_get_pool()` to succeed → verify recovery (session yields a connection).
11. **test_get_db_session_pool_error_fires_callback** — Mock pool.getconn() to raise `PoolError`, verify `on_pool_error` callback was called with the exception.
12. **test_get_db_session_callback_failure_does_not_suppress_error** — Callback raises → `PoolExhaustionError` still raised.

### `tests/app_platform/test_shim_db.py` (update)

13. **Update `test_legacy_database_imports_resolve_to_platform_exports`** — The `get_db_session` identity check (`assert get_db_session is platform_get_db_session`) must change to a behavioral test since the shim now wraps rather than re-exports. Replace with: verify `database.get_db_session` returns a context manager that yields a connection (same as `app_platform` version). The `get_pool` identity check is unchanged.
13b. **test_database_session_direct_module_import** — Verify `from database.session import get_db_session` still works (used by `tests/api/test_auth_system.py`). The shim's `get_db_session` is a module-level function, so direct imports resolve correctly.

### `tests/database/test_pool_exhaustion.py` (Fix 4 verification)

14. **test_503_on_pool_exhaustion_error** — Import `db_connection_error_handler` from `app_platform.db.handlers` (side-effect-free, no `app.py` startup). Register on a minimal test FastAPI app with a test route that raises `PoolExhaustionError`. Use `TestClient` to verify 503 with `{"type": "database_error"}`.
15. **test_503_on_connection_error** — Same test app with real handler, route raises `ConnectionError` from `app_platform.db.exceptions`. Verify 503.
16. **test_no_503_on_generic_database_error** — Same test app with real handler, route raises generic `DatabaseError`. Use `TestClient(app, raise_server_exceptions=False)`. Verify response is 500 (not 503). Proves the handler is scoped to the two concrete types.
17. **test_create_app_has_503_handlers_registered** — Requires `DATABASE_URL` env var (set via `monkeypatch.setenv` before import or rely on `.env`). Import `create_app` from `app` (triggers module-scope side effects — acceptable for this integration test). Call `create_app()`. Assert `PoolExhaustionError` and `ConnectionError` are keys in `app.exception_handlers`. Proves wiring inside the factory. Note: tests 14-16 avoid `app.py` side effects by importing only from `app_platform.db.handlers`; this test is the only one that imports `app.py`.

## Known Limitations

1. **Direct `get_db_session()` callers are NOT gated by cooldown.** Routes, services, and other code that calls `get_db_session()` directly (auth_service, plaid routes, portfolio_repository, etc.) will still attempt pool creation/acquisition during cooldown. Each failure fires the `on_pool_error` callback (re-arming cooldown) and raises `PoolExhaustionError`/`ConnectionError`. Fix 4's 503 handler catches unhandled REST paths; routes with broad `except Exception` blocks catch internally but still fire the callback. The cascade is partially stopped (MCP tools via `@require_db` skip DB entirely), not fully stopped for all callers. Full protection would require a shim-level cooldown short-circuit, which is a larger change.

2. **`psycopg2.OperationalError` conflates transient and permanent failures.** Pool exhaustion ("too many clients"), network issues, and auth/DNS errors all raise `OperationalError`. The cooldown treats all as transient (30s retry). Permanent misconfigurations will cycle through repeated 30s cooldowns. psycopg2 does not provide subclasses to distinguish these; doing so would require error message parsing, which is fragile. The 30s cooldown is short enough that permanent failures surface quickly through repeated "temporarily unavailable" responses.

## Out of Scope

- Connection leak root cause identification (separate investigation)
- Connection pool size auto-tuning
- `estimate_store.py` separate pool (low-priority, local-fallback-only)
- Redis-backed session pooling for production
- PostgreSQL `max_connections` tuning (document recommendation: set `DB_POOL_MAX=10` when running multiple workers)
- **Manual `is_db_available()` callers** — Many MCP tools and services use `is_db_available()` directly (not `@require_db`) for conditional DB access. During the ≤30s cooldown window, these keep their current no-DB behavior, which is the same as when DB is not configured. Effects include but are not limited to: YAML/default risk limits instead of DB-backed, hard "requires PostgreSQL" errors, misleading "not configured" messages, skipped transaction-store reads with extra upstream API calls, and disabled position caching. The primary mitigation is the short cooldown window. Only `@require_db`-decorated MCP tools and unhandled REST paths (via Fix 4's 503 handler) get improved temporary-unavailability responses. Migrating manual callers to cooldown-aware behavior is a separate follow-up.

## Verification

1. `python3 -m pytest tests/database/test_pool_exhaustion.py tests/app_platform/test_db_session.py tests/app_platform/test_shim_db.py -x -q` (includes 503 handler tests)
2. `python3 -m pytest tests/ -x -q` — full suite passes
3. Manual: restart risk_module, verify MCP tools work normally (no regression)
