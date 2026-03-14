# Fix: PostgreSQL Connection Leak — Root Cause
**Status:** DONE

## Problem

PostgreSQL connections accumulate until `max_connections=100` is hit ("FATAL: too many clients already"). The cascading failure fix (commit `2dca72fd`) prevents the crash loop, but the underlying leak persists.

## Root Cause Analysis

### Primary: Pool Size Exceeds max_connections

The pool math doesn't work. `DB_POOL_MAX=20` with multiple processes exceeds PostgreSQL's `max_connections=100`:

| Deployment | Processes | Pool Max Each | Total Possible |
|-----------|-----------|---------------|----------------|
| `make dev` (`--reload` → 1 worker) | 1 web + 1 MCP | 20 | **40** |
| `make dev` (no `--reload`, 2 workers) | 2 web + 1 MCP | 20 | **60** |
| Production (4 workers) | 4 web + 1 MCP | 20 | **100** (at limit) |
| Any deployment + lingering MCP | +1 per old MCP | 20 | **+20 each** |

The `DB_POOL_MIN=5` also means each process pre-allocates 5 connections on pool creation, consuming slots even before any requests.

### Contributing: No Pool Cleanup on Process Exit

Neither `app.py` nor `mcp_server.py` registers any shutdown handler:
- `app.py`: No `lifespan` context manager, no `on_event("shutdown")`, no `atexit`
- `mcp_server.py`: No cleanup before/after `mcp.run()`. When the stdio client closes stdin, the MCP protocol layer shuts down the process but the pool connections are never explicitly closed.
- `PoolManager.close()` exists (`app_platform/db/pool.py:71`) but is **dead code** — only called in tests via `_reset_for_tests()`.

Without explicit cleanup, connections persist until GC or TCP keepalive timeout, extending the window where old-process connections overlap with new-process connections.

### Contributing: Thread-Unsafe Pool

`SimpleConnectionPool` is documented as NOT thread-safe. The codebase uses multiple threads:
- `OrderWatcher` runs in a daemon thread (`services/order_watcher.py:25`) and calls `get_db_session()` (`order_watcher.py:73`)
- `ThreadPoolExecutor` used in `portfolio_risk_engine/portfolio_risk.py:859`, `services/portfolio_service.py:1141`

Concurrent `getconn()`/`putconn()` from different threads can corrupt the pool's internal tracking, causing the pool to lose track of connections (leaked) or hand out the same connection twice.

### Minor: `delete_factor_group` Use-After-Release

`routes/factor_intelligence.py:292-294` — connection returned to pool inside `with`, then used outside. Correctness bug (not a leak), but should be fixed.

```python
# CURRENT (buggy):
with get_db_session() as conn:
    db = DatabaseClient(conn)      # inside with
db.delete_factor_group(...)        # OUTSIDE — conn already returned!
```

## Changes

### Step 1: Reduce Pool Size

**Files:** `.env`, `app_platform/db/pool.py`

Change `DB_POOL_MAX=20` → `DB_POOL_MAX=10`, `DB_POOL_MIN=5` → `DB_POOL_MIN=2`.

Also change the **code defaults** in `app_platform/db/pool.py` so processes without `.env` (e.g. production, new deployments) get the safe values:
- `pool.py:38` — `os.getenv("DB_POOL_MIN", "5")` → `os.getenv("DB_POOL_MIN", "2")`
- `pool.py:45` — `os.getenv("DB_POOL_MAX", "20")` → `os.getenv("DB_POOL_MAX", "10")`

With 10 max per process:
- `make dev` (2 workers + 1 MCP) = 3 × 10 = 30 (safe)
- Production (4 workers + 1 MCP) = 5 × 10 = 50 (safe)
- Dev + 2 lingering MCPs = 5 × 10 = 50 (still safe)

This is the single highest-impact change — it prevents exhaustion even without cleanup fixes.

**Deployment note**: If production or other environments inject `DB_POOL_MIN`/`DB_POOL_MAX` via secrets or explicit env vars (e.g. AWS Secrets Manager), those override the code defaults. After deploying this change, verify the deployed environment uses `DB_POOL_MAX=10` and `DB_POOL_MIN=2`. Update references in `docs/deployment/AWS_SECRETS_MANAGER_MIGRATION_GUIDE.md` and `docs/reference/DATABASE_REFERENCE.md` to reflect the new recommended values.

### Step 1b: Switch to ThreadedConnectionPool

**File:** `app_platform/db/pool.py`

Replace `SimpleConnectionPool` with `ThreadedConnectionPool` (one-line import change). `ThreadedConnectionPool` has the same constructor signature and API but adds internal locking around `getconn()`/`putconn()`. This eliminates the thread-safety corruption path from `OrderWatcher` (daemon thread) and `ThreadPoolExecutor` usage.

```python
# Before:
from psycopg2.pool import SimpleConnectionPool

# After:
from psycopg2.pool import ThreadedConnectionPool
```

And change the constructor call:
```python
# Before (pool.py:63):
self._pool = SimpleConnectionPool(min_connections, max_connections, ...)

# After:
self._pool = ThreadedConnectionPool(min_connections, max_connections, ...)
```

`ThreadedConnectionPool` is a drop-in replacement — same constructor, same `getconn()`/`putconn()`/`closeall()` API. The only difference is internal thread safety.

### Step 2: Add MCP Server Pool Cleanup via FastMCP Lifespan

**File:** `mcp_server.py`

`atexit` does NOT reliably fire when stdio MCP processes are killed — the MCP client protocol closes stdin, waits briefly, then escalates to `SIGTERM`/`SIGKILL`. Use FastMCP's built-in `@lifespan` decorator instead, which runs teardown code during the stdio shutdown sequence (inside `run_stdio_async()`) before `mcp.run()` returns.

**Critical ordering**: The FastMCP lifespan teardown runs **before** `mcp.run()` returns. `OrderWatcher` is a daemon thread that calls `get_db_session()` during polls. If we close the pool in lifespan teardown while the watcher is still polling, it will error. Therefore, stop the OrderWatcher **first** in lifespan teardown, **then** close the pool.

First, promote `_order_watcher` to module scope. Currently it's only defined inside `if __name__ == "__main__"` (`mcp_server.py:2088`), making it invisible to the lifespan function. Add at module level (near the top, after imports):

```python
_order_watcher = None  # Set in __main__, used by lifespan teardown
```

Then define the lifespan and wire it into `FastMCP`:

```python
from fastmcp.server.lifespan import lifespan as mcp_lifespan

@mcp_lifespan
async def pool_cleanup(server):
    yield {}
    # Teardown — order matters:
    # 1. Stop OrderWatcher (it uses DB connections)
    if _order_watcher is not None:
        try:
            _order_watcher.stop()
        except Exception:
            pass
    # 2. Close DB pool
    from app_platform.db.pool import close_pool
    close_pool()

mcp = FastMCP(
    "portfolio-mcp",
    instructions="Portfolio analysis and position management tools for Claude Code",
    lifespan=pool_cleanup,
)
```

Also add `atexit` as belt-and-suspenders for normal interpreter exits (e.g. `Ctrl-C`, clean EOF). Must also stop OrderWatcher first to maintain the same ordering guarantee:

```python
import atexit

def _atexit_cleanup():
    if _order_watcher is not None:
        try:
            _order_watcher.stop()
        except Exception:
            pass
    from app_platform.db.pool import close_pool
    close_pool()

atexit.register(_atexit_cleanup)
```

### Step 3: Add Public `close_pool()` Function

**File:** `app_platform/db/pool.py`

Add a public runtime API instead of using private `_reset_for_tests()` or `_get_default_manager()`.

`close_pool()` holds `_default_lock` for the entire close-and-null sequence. `PoolManager.close()` remains non-terminal (can recreate) to preserve existing behavior tested in `test_close_shuts_down_pool_and_allows_recreation`.

```python
def close_pool() -> None:
    """Close the process-global connection pool, releasing all connections.

    Safe to call even if no pool has been created. After closing, the next
    ``get_pool()`` call will lazily create a fresh PoolManager and pool.
    """
    with PoolManager._default_lock:
        mgr = PoolManager._default_manager
        if mgr is not None:
            mgr.close()
            PoolManager._default_manager = None
```

**Race note**: `_get_default_manager()` has an unlocked fast path, so a concurrent caller could grab a reference to the old manager between `close()` and the null assignment. If that caller then calls `get_pool()`, it would recreate a pool on the stale manager. Additionally, after `close_pool()` nulls `_default_manager`, a late caller (e.g. OrderWatcher if `stop()` timed out) hitting `get_pool()` will create a brand new `PoolManager` and pool. Both cases are acceptable because: (a) `close_pool()` is only called during process shutdown, (b) the process exits moments later, and (c) the primary defense against exhaustion is pool size reduction (Step 1), not cleanup handlers. The cleanup is a best-effort optimization to release connections promptly, not a guarantee.

Export `close_pool` in `app_platform/db/pool.py`'s `__all__`. Callers (`mcp_server.py`, `app.py`) import directly via `from app_platform.db.pool import close_pool`. No need to re-export through `database/pool.py` shim or `database/__init__.py` — `close_pool()` is only used by entry-point shutdown handlers, not by general application code.

### Step 4: Add FastAPI Lifespan Handler

**File:** `app.py` (inside `create_app()`)

Add a `lifespan` async context manager to `create_app()` and pass it to the existing `FastAPI()` constructor:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    yield
    # Shutdown: close DB pool
    from app_platform.db.pool import close_pool
    close_pool()

# Inside create_app():
app = FastAPI(
    title="Risk Module API",
    version="2.0",
    description="Portfolio risk analysis and optimization API",
    lifespan=_lifespan,
)
```

### Step 5: Harden `putconn()` Against Pool-Closed Errors

**File:** `app_platform/db/session.py`

When `closeall()` is called during shutdown while a connection is still checked out (e.g. OrderWatcher mid-poll), psycopg2 closes the checked-out connection. When the `get_db_session()` context manager exits and calls `pool.putconn(conn)`, psycopg2 raises `PoolError` because the pool is already closed. This leaves `_METRICS["active"]` undecremented and produces noisy tracebacks during shutdown.

Fix: Wrap `putconn()` in a try/except in `SessionManager.get_db_session()`:

```python
# Before (session.py:70-75):
try:
    yield conn
finally:
    pool.putconn(conn)
    with _M_LOCK:
        _METRICS["active"] -= 1

# After:
try:
    yield conn
finally:
    try:
        pool.putconn(conn)
    except PoolError as exc:
        # Pool may be closed during shutdown — connection already freed by closeall().
        # Log at WARNING so non-shutdown PoolErrors (e.g. double-return bugs) are visible.
        logger.warning("putconn() failed (likely shutdown race): %s", exc)
    finally:
        with _M_LOCK:
            _METRICS["active"] -= 1
```

### Step 6: Fix `delete_factor_group` Use-After-Release

**File:** `routes/factor_intelligence.py`

Move `db.delete_factor_group()` inside the `with` block (indent 4 spaces):

```python
# Before (lines 292-294):
with get_db_session() as conn:
    db = DatabaseClient(conn)
db.delete_factor_group(user['user_id'], group_name)

# After:
with get_db_session() as conn:
    db = DatabaseClient(conn)
    db.delete_factor_group(user['user_id'], group_name)
```


## Files

| File | Change |
|------|--------|
| `.env` | `DB_POOL_MAX=10`, `DB_POOL_MIN=2` |
| `app_platform/db/pool.py` | Change defaults to `2`/`10`, `SimpleConnectionPool` → `ThreadedConnectionPool`, add public `close_pool()` |
| `mcp_server.py` | Promote `_order_watcher` to module scope, FastMCP `@lifespan` (watcher stop → pool close), `atexit` belt-and-suspenders |
| `app_platform/db/session.py` | Wrap `putconn()` in try/except `PoolError` for pool-closed errors |
| `app.py` | `lifespan` context manager on `FastAPI(lifespan=...)` inside `create_app()` |
| `routes/factor_intelligence.py` | Fix indentation on `delete_factor_group` |
| `docs/reference/DATABASE_REFERENCE.md` | Update pool class name (`ThreadedConnectionPool`), default values, file path |
| `docs/deployment/AWS_SECRETS_MANAGER_MIGRATION_GUIDE.md` | Update `DB_POOL_MIN`/`DB_POOL_MAX` recommended values to `2`/`10` |
| `docs/guides/usage_notes.md` | Update `DB_POOL_MIN`/`DB_POOL_MAX` values to `2`/`10` |
| `readme.md` | Update pool class reference (`SimpleConnectionPool` → `ThreadedConnectionPool`, correct file path) |
| `.env.example` | Replace obsolete `DB_POOL_SIZE=5` with `DB_POOL_MIN=2` / `DB_POOL_MAX=10` |
| `docs/reference/ENVIRONMENT_SETUP.md` | Update pool env var names and default values |
| `docs/guides/DEVELOPER_ONBOARDING.md` | Update pool config references |

## Tests

### Unit tests (`tests/app_platform/test_db_pool.py`)
1. **`close_pool()` — no pool exists**: Call `close_pool()` when no default manager exists → no error.
2. **`close_pool()` — closes and nulls**: Create pool via `get_pool()`, call `close_pool()`, verify `PoolManager._default_manager is None`. Next `get_pool()` creates fresh manager and pool (different instance).
3. **Existing `close()` behavior preserved**: `manager.close(); manager.get_pool()` still recreates (`test_close_shuts_down_pool_and_allows_recreation` must pass unchanged).
4. **Pool defaults**: Verify `PoolManager().min_connections == 2` and `PoolManager().max_connections == 10` when env vars are unset.
5. **ThreadedConnectionPool used**: Verify `pool.py` imports and constructs `ThreadedConnectionPool` (not `SimpleConnectionPool`).

### Session tests (`tests/app_platform/test_db_session.py`)
6. **`putconn()` tolerates pool-closed `PoolError`**: Mock pool where `putconn()` raises `PoolError`. Verify `get_db_session()` exits cleanly and `_METRICS["active"]` is still decremented. Verify non-`PoolError` exceptions from `putconn()` still propagate.

### Integration tests
7. **FastAPI lifespan calls `close_pool()`**: Mock `close_pool()`, enter/exit the lifespan context, verify `close_pool` was called during shutdown.
8. **MCP lifespan teardown ordering**: Import `pool_cleanup` from `mcp_server`, invoke it as an async context manager. Verify that after `yield`, `OrderWatcher.stop()` is called before `close_pool()`. Use mocks for both.

### Route tests
9. **`delete_factor_group` fix**: Mock `DatabaseClient.delete_factor_group` and `get_db_session`, call the endpoint, verify `delete_factor_group` is called while the session context manager is still open (not after exit).

## Verification

1. `python3 -m pytest tests/ -x -q` — full suite passes
2. Restart MCP server (Claude Code `/mcp` command) × 3 → query `pg_stat_activity` to confirm old connections close
3. Confirm MCP tools still work after changes
4. Verify deployed environments use `DB_POOL_MAX=10`, `DB_POOL_MIN=2`

## Known Limitations

- **ThreadedConnectionPool overhead**: Adds per-call locking overhead to `getconn()`/`putconn()`. Negligible compared to actual DB I/O.
- **No cross-process pool monitoring**: `_METRICS` in `session.py` only tracks per-process checkouts. For cross-process visibility, query `pg_stat_activity` directly. Adding pool metrics to `/api/health` is deferred (requires HealthResponse model + OpenAPI schema + generated types update).
- **OrderWatcher stop() timeout + pool recreation**: `stop()` joins for up to 5 seconds. If the watcher is mid-poll (DB + broker calls in `reconcile_open_orders()`), it may still be running when `close_pool()` executes. Since `PoolManager.close()` is non-terminal, a late DB call from the watcher could create a new pool. This is acceptable because: (a) the watcher is a daemon thread — killed when the process exits moments later, (b) any recreated pool lives for at most seconds, (c) with `DB_POOL_MAX=10` (Step 1), even a recreated pool can't exhaust `max_connections`.
- **EstimateStore secondary pool** (`fmp/estimate_store.py`): Separate pool (max=3) with proper `close()` + context manager. Not contributing to the leak.
