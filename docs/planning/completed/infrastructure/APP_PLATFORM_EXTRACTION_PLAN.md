# App Platform Extraction Plan

**Status**: v1 Complete (Phases 1-4)
**Created**: 2026-03-08
**Review**: R3 PASS — all Codex findings resolved across 4 review rounds

## Overview

Refactor ~1,000 lines of generic web application infrastructure from `risk_module` into an `app_platform/` package within the same monorepo. The v1 scope covers **database, structured logging, and middleware** only. Auth, gateway proxy, and PyPI distribution are deferred to v2.

## 1. Package Design Decisions

### 1.1 Name

- **Python package name**: `app_platform`
- **PyPI/distribution name**: TBD — `app-platform` may collide with Azure's `azure-mgmt-appplatform`. Will finalize before PyPI publication (v2). In-repo usage is unaffected.
- **Import**: `from app_platform import ...`

### 1.2 Distribution: Local-First Monorepo Subfolder

Follow the proven `fmp/` pattern:

| Authoritative location | Deployment repo | Sync script |
|------------------------|----------------|-------------|
| `app_platform/` (this repo) | TBD (v2) | TBD (v2) |

- Changes are made and tested in the monorepo
- `risk_module` imports directly from the local path (no `pip install`)
- PyPI distribution deferred until in-repo extraction is stable (v2)

### 1.3 Design Principles

1. **Zero domain knowledge** — never import/reference risk, portfolio, trading, or finance concepts
2. **Manager objects over global singletons** — `PoolManager`, `LoggingManager` are the primary API; module-level convenience functions (`get_pool()`, `get_logger()`) delegate to managers and exist only for backward-compat shims
3. **Opt-in modules** — consumers pick what they need; DB-only users don't need `slowapi`
4. **psycopg2-native** — no SQLAlchemy; keep the lightweight approach
5. **Stdlib-only base classes** — `DatabaseClientBase` uses only stdlib `logging` + `time`, no dependency on `app_platform.logging`. This keeps Phase 1 self-contained.

### 1.4 Scope

**v1 (this plan)**: Database layer + structured logging + middleware assembly
**v2 (future)**: Auth service, gateway proxy, PyPI publication, sync script

---

## 2. Module Organization (v1)

```
app_platform/
    __init__.py              # Public API re-exports
    db/
        __init__.py          # Re-exports: PoolManager, get_pool, get_db_session
        pool.py              # PoolManager + get_pool() convenience (from database/pool.py)
        session.py           # SessionManager + get_db_session() convenience (from database/session.py)
        migration.py         # SQL migration runner (from admin/run_migration.py)
        exceptions.py        # Generic DB exception hierarchy (from inputs/exceptions.py)
        client_base.py       # Base CRUD helper class — stdlib only (from database_client.py)
    logging/
        __init__.py          # Re-exports
        core.py              # LoggingManager + structured JSON engine (from utils/logging.py)
        decorators.py        # @log_errors, @log_timing, @log_operation
    middleware/
        __init__.py          # Re-exports: configure_middleware()
        cors.py              # CORS configuration factory
        sessions.py          # Session middleware configuration
        rate_limiter.py      # ApiKeyRegistry + create_limiter() (from utils/rate_limiter.py)
        error_handlers.py    # Validation + rate limit exception handlers
    py.typed                 # PEP 561 marker
```

**12 source files** across 3 subpackages.

---

## 3. Interface Design (Public API)

### 3.1 Database — PoolManager

```python
from app_platform.db import PoolManager, get_pool, get_db_session

# Primary API: manager object (explicit, testable)
pool_mgr = PoolManager(
    database_url="postgresql://...",   # or reads DATABASE_URL env var
    min_connections=5,                 # or reads DB_POOL_MIN env var
    max_connections=20,                # or reads DB_POOL_MAX env var
)
pool = pool_mgr.get_pool()
pool_mgr.close()                      # Explicit shutdown (new — addresses pool lifecycle gap)

# Convenience API: module-level singleton (for shim compatibility)
# Delegates to a default PoolManager under the hood
pool = get_pool()

with get_db_session() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
```

Key changes from current code:
- `PoolManager` is the primary object; `get_pool()` is a convenience wrapper
- `close()` method for explicit pool shutdown (currently absent)
- `_reset_for_tests()` clears the singleton for test isolation
- No import of `utils.config` — reads env vars directly with defaults

### 3.2 Database Exceptions

```python
from app_platform.db.exceptions import (
    DatabaseError,              # Base
    ConnectionError,
    PoolExhaustionError,
    TimeoutError,
    TransactionError,
    ValidationError,
    MigrationError,
    SchemaError,
    DataConsistencyError,
    DatabasePermissionError,    # Renamed from PermissionError to avoid shadowing builtin
    AuthenticationError,
    SessionNotFoundError,
    NotFoundError,              # New generic base for domain NotFound subclasses
    handle_database_error,      # Decorator
    is_recoverable_error,       # Utility
    log_database_error,         # Utility
)
```

**Stays in `risk_module`** (domain-specific, subclass `NotFoundError`):
- `UserNotFoundError(NotFoundError)`
- `PortfolioNotFoundError(NotFoundError)`
- `ScenarioNotFoundError(NotFoundError)`
- `RiskLimitsNotFoundError(NotFoundError)`
- `CashMappingError(DatabaseError)`
- `DualModeError(Exception)` — not a DB error, stays as-is
- `ErrorCodes` — domain-specific codes stay in risk_module

### 3.3 Database Client Base (stdlib-only)

```python
from app_platform.db.client_base import DatabaseClientBase

class DatabaseClientBase:
    """Thin CRUD base with connection injection + timing. Stdlib-only — no app_platform.logging dependency."""
    def __init__(self, conn): ...
    def get_connection(self): ...              # @contextmanager, yields self.conn
    def is_connection_healthy(self, conn): ... # SELECT 1 health check
    def execute_with_timing(self, cursor, query, params=None, context=None, slow_ms=200): ...
    _execute_with_timing = execute_with_timing  # Alias — current callers use the private name
```

**Key design decision**: `DatabaseClientBase` uses only stdlib `logging` and `time`. It does NOT depend on `app_platform.logging` decorators. This means:
- Phase 1 (DB) is fully self-contained — no dependency on Phase 2 (logging)
- The current `@log_errors("critical")` decorator on `get_connection()` and `_execute_with_timing()` stays in risk_module's `DatabaseClient` subclass
- `DatabaseClientBase.execute_with_timing()` uses `logging.getLogger(__name__).warning()` for slow queries
- `_execute_with_timing` is preserved as an alias for `execute_with_timing` since existing callers (e.g., `database_client.py:703`) use the underscore-prefixed name

Risk module's `DatabaseClient` subclasses this and adds all 40+ domain methods + structured logging decorators.

### 3.4 Migration Runner

```python
from app_platform.db.migration import run_migration, run_migrations_dir

# Run a single SQL file
run_migration("database/migrations/001_init.sql")

# Run all .sql files in directory, sorted by filename
run_migrations_dir("database/migrations/")
```

Generalized from `admin/run_migration.py` — no hardcoded table verification. Consumers supply their own verification logic.

### 3.5 Structured Logging — LoggingManager

```python
from app_platform.logging import (
    # Primary API: manager
    LoggingManager,

    # Convenience API (delegates to default manager)
    get_logger, configure_logging,
    log_event, log_error, log_alert, log_slow_operation,
    log_errors, log_timing, log_operation,  # Decorators
    set_log_context, clear_log_context,
)

# Primary: explicit manager
mgr = LoggingManager(app_name="risk_module", log_dir="./logs", environment="production")
logger = mgr.get_logger("mymodule")

# Convenience: module-level (for shim compatibility)
configure_logging(app_name="risk_module")
logger = get_logger("mymodule")
```

Key changes:
- `LoggingManager` is the primary object; convenience functions delegate to a default instance
- Logger hierarchy prefix is configurable (currently hardcoded `"risk_module."`)
- `_configure_root_logger()` becomes `LoggingManager.__init__()` with lazy auto-configure: if `get_logger()` is called before `configure_logging()`, auto-configures with defaults and logs a warning
- Domain-specific aliases (`portfolio_logger`, `log_usage`, etc.) stay in `utils/logging.py` as thin wrappers
- `ContextVar` name is configurable (currently hardcoded `"risk_module_log_context"`)

### 3.6 Rate Limiting — ApiKeyRegistry

```python
from app_platform.middleware.rate_limiter import ApiKeyRegistry, create_limiter, RateLimitConfig

# Key registry (replaces bare VALID_KEYS/TIER_MAP/DEFAULT_KEYS dicts)
registry = ApiKeyRegistry()
registry.add_key("public_key_123", tier="public")
registry.add_key("registered_key_456", tier="registered")

# Or bulk-init from dict
registry = ApiKeyRegistry.from_dict({
    "public": "public_key_123",
    "registered": "registered_key_456",
    "paid": "paid_key_789",
})

# Properties (preserves current export surface)
registry.valid_keys      # set — equivalent to current VALID_KEYS
registry.tier_map        # dict — equivalent to current TIER_MAP
registry.public_key      # str — equivalent to current PUBLIC_KEY
registry.default_keys    # dict — equivalent to current DEFAULT_KEYS

# Create limiter
config = RateLimitConfig(
    dev_mode=True,              # Disables rate limiting (IS_DEV)
    key_registry=registry,
)
limiter = create_limiter(config)
```

**Shim compatibility**: `utils/rate_limiter.py` will re-export `limiter`, `VALID_KEYS`, `TIER_MAP`, `PUBLIC_KEY`, `DEFAULT_KEYS`, `IS_DEV` as module-level names backed by the registry. This preserves the exact import surface used by `app.py` and `routes/factor_intelligence.py`.

### 3.7 Middleware Assembly

```python
from app_platform.middleware import configure_middleware, MiddlewareConfig

config = MiddlewareConfig(
    cors_origins=["http://localhost:3000"],
    cors_credentials=True,
    session_secret="...",             # Falls back to FLASK_SECRET_KEY env (matches current app.py:956)
    rate_limiter=limiter,
    validation_error_logging=True,
)
configure_middleware(app, config)
```

Replaces the ~50 lines in `create_app()` that wire CORS, SessionMiddleware, and exception handlers.

---

## 4. Extraction Phases

### Phase 1: Database Layer (Lowest Risk)

**Scope**: `app_platform/db/` — pool, session, exceptions, migration, client_base (stdlib-only)

**Steps**:
1. Create `app_platform/` directory structure with `__init__.py` and `py.typed`
2. Create `app_platform/db/pool.py` — `PoolManager` class with `get_pool()`, `close()`, `_reset_for_tests()`. Replace `from utils.config import DB_POOL_MIN, DB_POOL_MAX` with env var reads + constructor args
3. Create `app_platform/db/session.py` — `SessionManager` + `get_db_session()` context manager. Import pool from `.pool`
4. Create `app_platform/db/exceptions.py` — generic exceptions only: `DatabaseError`, `ConnectionError`, `PoolExhaustionError`, `TimeoutError`, `TransactionError`, `ValidationError`, `MigrationError`, `SchemaError`, `DataConsistencyError`, `DatabasePermissionError`, `AuthenticationError`, `SessionNotFoundError`, `NotFoundError`. Plus `handle_database_error`, `is_recoverable_error`, `log_database_error` utilities
5. Create `app_platform/db/migration.py` — generalize `admin/run_migration.py` (remove hardcoded verify, accept session as arg)
6. Create `app_platform/db/client_base.py` — `DatabaseClientBase` with stdlib-only logging (no `app_platform.logging` dependency). Methods: `__init__(conn)`, `get_connection()`, `is_connection_healthy()`, `execute_with_timing()`
7. Update `database/pool.py` → thin shim: re-export from `app_platform.db.pool`, pass legacy default URL
8. Update `database/session.py` → thin shim: re-export from `app_platform.db.session`
9. Update `inputs/exceptions.py` → domain exceptions (`UserNotFoundError`, etc.) subclass `app_platform.db.exceptions.NotFoundError`. Import generic base from platform. Keep `DualModeError`, `ErrorCodes`, `CashMappingError` unchanged. Add `PermissionError = DatabasePermissionError` alias for backward compatibility (current code exports `PermissionError` at `inputs/exceptions.py:172`)
10. Update `inputs/database_client.py` → `class DatabaseClient(DatabaseClientBase)`. Keep all `@log_errors`/`@log_operation` decorators on the subclass methods (they depend on `utils.logging`, not `app_platform.logging`)
11. Write tests for `app_platform.db` in isolation
12. Write shim compatibility tests (see Testing section)

**Risk**: Low — pool/session have zero domain coupling. `client_base` is stdlib-only.

**Dependency**: None — Phase 1 is fully self-contained.

### Phase 2: Structured Logging

**Scope**: `app_platform/logging/` — `LoggingManager`, core engine, decorators

**Steps**:
1. Create `app_platform/logging/core.py` — extract from `utils/logging.py`:
   - All private helpers (`_json_default`, `_safe_dict`, `_compact_json`, `_now_iso`, `_has_file_handler`, `_build_json_logger`, `_emit_json`, `_format_details_for_text`, `_check_dedup`, `_normalize_exc`, `_normalize_details`, `_extract_correlation_id`)
   - `LoggingManager` class wrapping `_configure_root_logger()` as `__init__`
   - Core event functions: `get_logger`, `log_event`, `log_error`, `log_alert`, `log_slow_operation`, `log_service_status`
   - Context management: `set_log_context`, `clear_log_context` (with configurable `ContextVar` name)
   - Lazy auto-configure: if `get_logger()` called before `configure_logging()`, create default `LoggingManager` + warn
2. Create `app_platform/logging/decorators.py` — extract `log_errors`, `log_timing`, `log_operation`
3. Create `app_platform/logging/__init__.py` with re-exports + `configure_logging()` convenience function
4. Update `utils/logging.py` to:
   - Import core engine from `app_platform.logging`
   - Call `configure_logging(app_name="risk_module")` at module level (preserves import-time behavior)
   - Keep all domain-specific aliases (`portfolio_logger`, `trading_logger`, `database_logger`, `api_logger`, `log_usage`, `log_frontend_event`, `log_portfolio_operation`, `log_claude_integration`, `log_sql_query`, `log_schema_validation`, `log_rate_limit_hit`, `log_auth_event`, `log_resource_usage`, `log_critical_alert`) as thin wrappers
   - Keep backward-compatible `__all__` unchanged
5. Write tests for `app_platform.logging` in isolation
6. Write shim compatibility tests

**Risk**: Medium — 70 files import from `utils.logging`. Shim preserves all existing names.

**Subtlety**: Module-level `_configure_root_logger()` call at import time. Shim must call `configure_logging(app_name="risk_module")` immediately to preserve this behavior.

**Dependency**: Phase 1 must be complete (but Phase 2 does not depend on Phase 1 code — they are independent subpackages).

### Phase 3: Rate Limiter + Middleware Assembly

**Scope**: `app_platform/middleware/`

**Steps**:
1. Create `app_platform/middleware/rate_limiter.py` — `ApiKeyRegistry` class + `create_limiter()` + `RateLimitConfig`. The registry provides `valid_keys`, `tier_map`, `public_key`, `default_keys` as properties
2. Create `app_platform/middleware/cors.py` — `configure_cors()` factory
3. Create `app_platform/middleware/sessions.py` — `configure_sessions()` factory
4. Create `app_platform/middleware/error_handlers.py` — extract `RequestValidationError` and `RateLimitExceeded` handlers from `app.py`
5. Create `app_platform/middleware/__init__.py` with `configure_middleware()` convenience function
6. Update `utils/rate_limiter.py` → shim that:
   - Creates an `ApiKeyRegistry` with current default keys
   - Re-exports `limiter`, `VALID_KEYS`, `TIER_MAP`, `PUBLIC_KEY`, `DEFAULT_KEYS`, `IS_DEV` as module-level names (preserves exact import surface for `app.py` line 241 and `routes/factor_intelligence.py` line 37)
7. Update `app.py` `create_app()` to use `configure_middleware()` (optional — can keep current wiring via shim)
8. Write tests
9. Write shim compatibility tests

**Risk**: Low — thin configuration layer.

**Dependency**: Phase 2 must be complete (error handlers may use structured logging).

### Phase 4: Package Build (v1 finalization)

**Steps**:
1. Create `app_platform/pyproject.toml` (for future sync/PyPI, not needed for in-repo use)
2. Final cleanup and documentation
3. Update `CLAUDE.md` local-first table with `app_platform/`

---

## 5. Deferred to v2

The following are explicitly **out of scope** for v1:

### Auth Service
Codex correctly identified that `AuthServiceBase` is underspecified. The current code has overlapping session CRUD between `auth_service.py` and `database_client.py`, and the `use_database: bool` flag is not a clean abstraction boundary. v2 will:
- Define `SessionStore` and `UserStore` protocols (callback interfaces)
- Provide `PostgresSessionStore` and `InMemorySessionStore` implementations
- `AuthServiceBase` accepts a `SessionStore` via constructor injection
- `risk_module.AuthService` provides Google-specific verification + risk-limits creation

### Gateway Proxy
Per-user session caching and SSE streaming are valuable but have only 1 consumer. Deferring reduces v1 blast radius.

### PyPI Distribution
Package naming (`app-platform` may collide) and sync script are deferred until in-repo extraction is stable and a second consumer exists.

---

## 6. Migration Strategy

Uses the **shim pattern** proven by `core/realized_performance_analysis.py` and `core/data_objects.py`.

**Principle**: Zero consumer changes on day one. All existing import paths continue via thin shims.

```python
# database/pool.py (after Phase 1)
"""Backward-compatible shim."""
from app_platform.db.pool import PoolManager, get_pool
# Preserve legacy default URL for existing callers
import os as _os
if not _os.getenv("DATABASE_URL"):
    _os.environ.setdefault("DATABASE_URL", "postgresql://postgres@localhost:5432/risk_module_db")
__all__ = ['get_pool']

# database/session.py (after Phase 1)
"""Backward-compatible shim."""
from app_platform.db.session import get_db_session
__all__ = ['get_db_session']

# utils/rate_limiter.py (after Phase 3)
"""Backward-compatible shim."""
import os as _os
from app_platform.middleware.rate_limiter import ApiKeyRegistry, create_limiter, RateLimitConfig

_registry = ApiKeyRegistry.from_dict({"public": "public_key_123", "registered": "registered_key_456", "paid": "paid_key_789"})
VALID_KEYS = _registry.valid_keys
TIER_MAP = _registry.tier_map
PUBLIC_KEY = _registry.public_key
DEFAULT_KEYS = _registry.default_keys
IS_DEV = _os.getenv("IS_DEV", "false").lower() == "true"  # reads IS_DEV env var directly
limiter = create_limiter(RateLimitConfig(dev_mode=IS_DEV, key_registry=_registry))
```

**Backward-compat requirements** (from Codex review — must preserve):
- `auth_service` module-level singleton in `services/auth_service.py` (v2)
- `limiter` module-level instance in `utils/rate_limiter.py`
- `VALID_KEYS`, `TIER_MAP`, `PUBLIC_KEY`, `DEFAULT_KEYS`, `IS_DEV` module-level names
- `gateway_proxy_router` in `routes/gateway_proxy.py` (v2)
- `FLASK_SECRET_KEY` fallback in `app.py` session middleware
- User payload shape from `get_user_by_session()` (v2)

**Order per phase**:
1. Create new `app_platform/` module with tests passing in isolation
2. Update existing module to thin shim delegating to `app_platform`
3. Run shim compatibility tests (verify old imports still work)
4. Run full test suite — zero regressions
5. Commit

---

## 7. Testing

### Package-level tests (isolation)

```
tests/app_platform/
    test_db_pool.py          # PoolManager init, get_pool, close, thread safety, _reset_for_tests
    test_db_session.py       # SessionManager context manager, metrics, connection return
    test_db_exceptions.py    # Exception hierarchy, handle_database_error, is_recoverable_error
    test_db_migration.py     # SQL file execution, directory scanning
    test_db_client_base.py   # Base CRUD timing, health check (stdlib logging only)
    test_logging_core.py     # LoggingManager config, JSON emission, dedup, lazy auto-configure
    test_logging_decorators.py  # @log_errors, @log_timing, @log_operation
    test_rate_limiter.py     # ApiKeyRegistry, create_limiter, dev mode bypass, tier-based keys
    test_middleware.py       # CORS/session/error handler wiring on test FastAPI app
```

### Shim compatibility tests (regression)

These verify that existing import paths work identically after shimming. Run after each phase:

```
tests/app_platform/
    test_shim_db.py          # Phase 1: import database.pool, database.session, inputs.exceptions
    test_shim_logging.py     # Phase 2: import utils.logging (all 70+ names)
    test_shim_rate_limiter.py  # Phase 3: import utils.rate_limiter (limiter, VALID_KEYS, etc.)
```

Each shim test:
- Imports from the **old** path (e.g., `from database import get_db_session`)
- Verifies the imported object is the same as `from app_platform.db import get_db_session`
- Verifies module-level names exist with expected types
- For rate limiter: verifies `VALID_KEYS` is a `set`, `TIER_MAP` is a `dict`, `limiter` is a `Limiter`
- For logging: verifies `portfolio_logger` and other domain aliases still resolve
- For exceptions: verifies `PermissionError` alias exists and is `DatabasePermissionError`

### Import-chain smoke tests (decorator / side-effect paths)

These verify that modules applying decorators at import time still load without error after shimming. This is the highest-risk path — decorators from `utils.logging` are applied at class definition time in `database_client.py`, `auth_service.py`, and route modules.

```
tests/app_platform/
    test_import_chains.py
```

Tests (run after each phase):
- `import database` — pool shim loads
- `from inputs.database_client import DatabaseClient` — class loads with `@log_errors`/`@log_operation` decorators applied
- `from inputs.exceptions import PermissionError` — alias resolves to `DatabasePermissionError`
- `from services.auth_service import auth_service` — singleton creates, decorators applied
- `from utils.rate_limiter import limiter, VALID_KEYS, TIER_MAP, PUBLIC_KEY, DEFAULT_KEYS, IS_DEV` — all names resolve with correct types
- `from routes.factor_intelligence import factor_intelligence_router` — route module loads with `limiter` import
- `import app` — full app module loads (exercises all middleware, auth, and decorator wiring)

Each test is a simple assertion that the import succeeds and the imported name has the expected type. No DB connection or HTTP server needed.

### Integration safety net

The existing risk_module test suite (~600+ tests) runs after each phase as the final gate. If any test breaks, the shim is wrong.

### DB test strategy

- `PoolManager` tests: mock `SimpleConnectionPool` (no real DB needed)
- `SessionManager` tests: mock pool to return mock connections
- `DatabaseClientBase` tests: mock cursor for `execute_with_timing`
- `migration.py` tests: mock DB session, verify SQL execution calls

---

## 8. Dependency Management

### Core (always required)
```toml
[project]
dependencies = [
    "psycopg2-binary>=2.9",
]
```

### Optional extras
```toml
[project.optional-dependencies]
fastapi = [
    "fastapi>=0.100",
    "starlette",
    "slowapi>=0.1.9",
]
all = ["app-platform[fastapi]"]
```

| Subpackage | Required extra |
|-----------|---------------|
| `app_platform.db` | (core) |
| `app_platform.logging` | (core) |
| `app_platform.middleware` | `fastapi` |

**Note**: `google-auth` is NOT a dependency of `app_platform`. Google OAuth verification stays in `risk_module` (v2 auth extraction will revisit this — the platform auth layer will be provider-agnostic).

---

## 9. Configuration Pattern

Each subpackage uses manager objects with dataclass configs:

```python
@dataclass
class PoolConfig:
    database_url: str = ""           # Falls back to DATABASE_URL env
    min_connections: int = 5         # Falls back to DB_POOL_MIN env
    max_connections: int = 20        # Falls back to DB_POOL_MAX env

@dataclass
class LoggingConfig:
    app_name: str = "app"
    log_dir: str = ""                # Falls back to LOG_DIR env, then ./logs
    environment: str = ""            # Falls back to ENVIRONMENT env
    slow_threshold_s: float = 1.0
    very_slow_threshold_s: float = 5.0

@dataclass
class MiddlewareConfig:
    cors_origins: list[str] = field(default_factory=list)
    cors_credentials: bool = True
    session_secret: str = ""         # Falls back to FLASK_SECRET_KEY env (matches current app.py)
    rate_limiter: Limiter = None

@dataclass
class RateLimitConfig:
    dev_mode: bool = False           # Falls back to IS_DEV env
    key_registry: ApiKeyRegistry = None
```

**Fallback chain**: Constructor argument → environment variable → hardcoded default.

**Global state policy**: Manager objects (`PoolManager`, `LoggingManager`, `ApiKeyRegistry`) are the primary API. Module-level convenience functions (`get_pool()`, `get_logger()`, `limiter`) delegate to a default manager singleton. The singleton is set on first use and can be reset via `_reset_for_tests()`. This keeps the injection model clean while supporting backward-compat shims.

**Single process-global instance** is acceptable for v1. Multi-app support is out of scope.

---

## 10. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| `client_base` depends on `utils.logging` decorators | `DatabaseClientBase` is stdlib-only. Decorators stay on risk_module's `DatabaseClient` subclass. Phase 1 has no logging dependency. |
| Logging module-level side effects | Lazy auto-configure: `get_logger()` before `configure_logging()` creates default manager + warns. Shim calls `configure_logging("risk_module")` immediately. |
| `utils.logging` has 70 importers | Shim keeps canonical import path + all existing names. Zero import changes. |
| Exception hierarchy split breaks `except` clauses | Domain exceptions subclass platform `DatabaseError` → `NotFoundError`, so `except DatabaseError` still catches everything. |
| `database/pool.py` default URL has `risk_module_db` | Shim sets env var default. Extracted `PoolManager` reads `DATABASE_URL` with no hardcoded default. |
| Rate limiter exports missing | Shim explicitly re-exports `limiter`, `VALID_KEYS`, `TIER_MAP`, `PUBLIC_KEY`, `DEFAULT_KEYS`, `IS_DEV` as module-level names backed by `ApiKeyRegistry`. |
| `PermissionError` shadows builtin | Renamed to `DatabasePermissionError` in platform. `inputs/exceptions.py` shim adds `PermissionError = DatabasePermissionError` alias. Shim test verifies `from inputs.exceptions import PermissionError` still works. |
| Global singletons vs injection | Manager objects are primary API. Globals only in shims. `_reset_for_tests()` on each manager. |
| Import-time decorator application | Shim compatibility tests verify that importing `app.py`, `services.auth_service`, and route modules works after each phase. |

---

## 11. Line Count Estimates (v1 only)

| Source file | Total | Extract | Stay |
|------------|-------|---------|------|
| `database/pool.py` | 72 | 72 | ~10 (shim) |
| `database/session.py` | 65 | 65 | ~5 (shim) |
| `inputs/exceptions.py` | 290 | ~180 | ~110 (domain) |
| `admin/run_migration.py` | 126 | ~80 | 0 (replaced) |
| `inputs/database_client.py` | 3,836 | ~50 | ~3,786 |
| `utils/logging.py` | 857 | ~350 | ~507 (domain) |
| `utils/rate_limiter.py` | 54 | ~60 | ~15 (shim) |
| `app.py` middleware | ~100 | ~80 | ~20 |
| **Total** | **~5,400** | **~940** | **~4,453** |

v1 package: ~940 lines of generic infrastructure + ~120 lines of `__init__.py` re-exports.

---

## 12. Success Criteria

1. `app_platform/` passes its own test suite with zero dependency on risk_module code
2. All shim compatibility tests pass — old import paths work identically
3. Full risk_module test suite passes with zero failures after shim conversion
4. No circular imports between `app_platform` and `risk_module`
5. `app_platform.db.client_base` has zero imports from `app_platform.logging` (stdlib-only)

---

## 13. Open Questions (Resolved)

| Question | Resolution |
|----------|-----------|
| Zero-touch backward compat mandatory? | Yes — shims preserve all existing import paths. `app.py` and admin callers do NOT change in v1. |
| Multi-app support? | No — single process-global instance is fine for v1. |
| PyPI distribution in v1? | No — deferred to v2 when extraction is stable and a second consumer exists. |
| Request-id / log-context middleware? | Out of scope for v1 overview claim. Removed "everything a new project needs" phrasing. |
