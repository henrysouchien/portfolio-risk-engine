# Startup Dependency Probes — pgbouncer + redis guard

## Context

After E22, `DATABASE_URL` points to pgbouncer (port 6432). If pgbouncer isn't running when the app starts, every DB call fails with "connection refused" — but the app itself starts fine and accepts traffic, returning cryptic errors. Same for redis when Celery is enabled.

The fix: probe dependencies in the FastAPI lifespan before `yield` (before accepting traffic). Fail fast with a clear message instead of silently accepting requests that will all fail.

## Current state

**File:** `app.py` lines 1048-1075

```python
@asynccontextmanager
async def _lifespan(app):
    if os.getenv("CELERY_ENABLED", ...):
        try:
            redis.Redis.from_url(broker_url, ...).ping()
            portfolio_logger.info("Celery broker reachable at %s", broker_url)
        except Exception as exc:
            portfolio_logger.warning("Celery broker unavailable at startup: %s", exc)
    yield
    # shutdown: close celery, close pool
```

Problems:
1. No DB/pgbouncer probe at all
2. Redis failure only logs a warning — app starts and Celery tasks silently fail
3. No clear message about what to start first

## Changes

### Change 1: Rewrite `_lifespan()` with probes gated by env var

**File:** `app.py`, replace the existing `_lifespan()` body (lines 1049-1066)

```python
@asynccontextmanager
async def _lifespan(app):
    if os.getenv("STARTUP_PROBES", "true").lower() in {"1", "true", "yes", "on"}:
        from database import is_db_available, reset_db_availability
        from utils.logging import portfolio_logger

        # --- DB probe (hard failure) ---
        reset_db_availability()
        if not is_db_available():
            portfolio_logger.critical(
                "Database unreachable at startup. Possible causes: "
                "pgbouncer not running (port 6432), PostgreSQL down, "
                "DATABASE_URL misconfigured, or pool error. "
                "Check pgbouncer and PostgreSQL, then restart."
            )
            raise RuntimeError("Database unreachable at startup")
        portfolio_logger.info("Database reachable")

        # --- Redis/Celery broker probe (hard failure when enabled) ---
        if os.getenv("CELERY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
            try:
                import redis
                broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
                redis.Redis.from_url(
                    broker_url, socket_connect_timeout=2, socket_timeout=2
                ).ping()
                portfolio_logger.info("Celery broker reachable")
            except Exception as exc:
                portfolio_logger.critical(
                    "Celery broker unreachable — is redis running? "
                    "Start redis before risk_module. Error: %s",
                    exc,
                )
                raise RuntimeError("Celery broker unreachable at startup")

    yield
    # ... existing shutdown code (close celery, close pool) unchanged ...
```

**Why env var gating (`STARTUP_PROBES`)?**

The lifespan runs for every `TestClient(...)` use in the test suite (~163 callsites). Alternative approaches (monkeypatching wrapper functions, patching the database module) all have edge cases:
- Patching `database.is_db_available` globally breaks the 12+ database unit tests in `test_pool_exhaustion.py` that test real TTL/cooldown/reset behavior
- Patching app-level wrappers requires `import app` during conftest setup, which triggers import-time side effects (`sys.exit(1)` if `DATABASE_URL` unset)
- Module reloads (`importlib.reload`) in `test_debug_timing.py` discard monkeypatches

A simple `STARTUP_PROBES=false` env var avoids all of these:
- `monkeypatch.setenv` works before any module import (no import-time side effects)
- `os.getenv` is checked each time `_lifespan()` runs (survives module reloads)
- The `database` module is never patched (database unit tests unaffected)
- Defaults to `true` — probes run in dev and production unless explicitly disabled
- Useful in CI where services aren't running but unit tests should pass

`reset_db_availability()` (`database/__init__.py:104`) clears the tri-state cache so the probe always performs a fresh `SELECT 1` — no stale cache from prior state or cooldown.

`raise RuntimeError(...)` inside a lifespan context manager causes uvicorn to refuse startup.

**Note:** No credentials are logged. The error message lists multiple possible causes.

### Change 2: Autouse conftest fixture

**File:** `tests/conftest.py`

```python
@pytest.fixture(autouse=True)
def _disable_startup_probes(monkeypatch):
    """Disable startup dependency probes in tests."""
    monkeypatch.setenv("STARTUP_PROBES", "false")
```

One line. No function patching, no module imports, no edge cases. Follows the existing pattern at `tests/conftest.py:5` (`_disable_transaction_store_read`).

### Change 3: Update .env.example

**File:** `.env.example`

Add after the database config section:

```bash
# Startup dependency probes (check pgbouncer + redis before accepting traffic)
STARTUP_PROBES=true
```

### Change 4: New tests

**File:** `tests/test_startup_probes.py` (new, small)

All tests use a module-level `pytestmark` or fixture to ensure `DATABASE_URL` and `FMP_API_KEY` are set before `app` is imported (following the pattern in `tests/app_platform/test_app_lifecycle.py:12-13`). Each test sets `STARTUP_PROBES=true` to override the conftest fixture, and pins `CELERY_ENABLED=false` unless explicitly testing the redis path.

```python
@pytest.fixture(autouse=True)
def _probe_env(monkeypatch):
    """Ensure app can import + probes are enabled for this test module."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/db")
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setenv("STARTUP_PROBES", "true")
    monkeypatch.setenv("CELERY_ENABLED", "false")
```

Tests:

1. **`test_lifespan_exits_when_db_unreachable`**: Monkeypatch `database.is_db_available` → `False`, `database.reset_db_availability` → no-op. Assert entering the lifespan raises `RuntimeError`.

2. **`test_lifespan_exits_when_redis_unreachable`**: Set `CELERY_ENABLED=true`, monkeypatch `database.is_db_available` → `True`, `database.reset_db_availability` → no-op, `redis.Redis.from_url` → raise `ConnectionError`. Assert `RuntimeError`.

3. **`test_lifespan_succeeds_when_deps_available`**: Monkeypatch `database.is_db_available` → `True`, `database.reset_db_availability` → no-op. Assert lifespan enters and yields.

4. **`test_lifespan_succeeds_with_celery_enabled`**: Set `CELERY_ENABLED=true`, monkeypatch `database.is_db_available` → `True`, `database.reset_db_availability` → no-op, `redis.Redis.from_url` → mock with `.ping()` succeeding. Assert lifespan enters and yields.

5. **`test_lifespan_resets_db_availability_before_probe`**: Record call order by monkeypatching both `database.reset_db_availability` and `database.is_db_available` to append to a shared list. Assert `reset_db_availability` is called before `is_db_available`.

6. **`test_lifespan_skips_probes_when_disabled`**: Set `STARTUP_PROBES=false`. Monkeypatch `database.is_db_available` to record calls. Assert lifespan enters and yields without calling `is_db_available`.

**Note:** These tests monkeypatch `database.is_db_available` locally (within each test). This is safe because the conftest's `STARTUP_PROBES=false` prevents the lifespan from reaching the `database` imports in all other tests — the local patches only take effect when `STARTUP_PROBES=true` is explicitly set.

---

## Files touched

| File | Change |
|------|--------|
| `app.py` | Rewrite `_lifespan()` with DB + redis probes gated by `STARTUP_PROBES` env var (~25 lines) |
| `tests/conftest.py` | Add autouse `_disable_startup_probes` fixture (1 line: `monkeypatch.setenv`) |
| `.env.example` | Add `STARTUP_PROBES=true` |
| `tests/test_startup_probes.py` | **New** — 6 tests for startup guard behavior |

## What this does NOT change

- `database/__init__.py` — `is_db_available()` and `reset_db_availability()` reused as-is
- `/api/health` endpoint — stays lightweight (health endpoint enhancement is a separate concern)
- Celery worker startup — workers have their own probe via `on_worker_ready` signal
- Any existing test — the conftest fixture disables probes for all existing tests

## Verification

1. **pgbouncer down**: Stop pgbouncer, start risk_module → should exit immediately with `Database unreachable at startup. Possible causes: pgbouncer not running (port 6432), PostgreSQL down, DATABASE_URL misconfigured, or pool error.`
2. **redis down**: Stop redis, set `CELERY_ENABLED=true`, start risk_module → should exit with `Celery broker unreachable`
3. **all up**: Start pgbouncer + redis + risk_module → starts normally, logs "Database reachable" and "Celery broker reachable"
4. **probes disabled**: Set `STARTUP_PROBES=false`, start risk_module without pgbouncer → starts normally (probes skipped)
5. **new tests**: `pytest tests/test_startup_probes.py -v`
6. **full suite**: `pytest tests/ -x` — conftest fixture disables probes for all 163 TestClient callsites
