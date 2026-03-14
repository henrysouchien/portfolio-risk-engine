# App Platform v2 — Auth Service & Gateway Proxy Extraction

**Status**: v2 Complete (Phases 5-7)
**Created**: 2026-03-08
**Prereq**: v1 complete (Phases 1-4, commit `868e2218`)

## Overview

Extract auth service (~450 lines) and gateway proxy (~344 lines) from `risk_module` into `app_platform/`. Follows same shim-based migration pattern as v1. PyPI distribution deferred until a second consumer exists.

---

## 1. Current State Analysis

### 1.1 Auth Service (`services/auth_service.py` — 453 lines)

**Module-level state**: `auth_service = AuthService()` singleton (line 453)

**Class**: `AuthService(use_database=None)`
- Constructor reads `USE_DATABASE`, `STRICT_DATABASE_MODE` env vars
- `session_duration` from `SESSION_DURATION_DAYS`, `cleanup_interval` from `SESSION_CLEANUP_INTERVAL_HOURS`
- In-memory dicts as DB fallback: `users_dict`, `user_sessions_dict`

**Public methods**:
| Method | Returns | Domain coupling |
|--------|---------|----------------|
| `verify_google_token(token)` | `(user_info_dict, error)` | Google-specific |
| `create_user_session(user_info)` | `session_id: str` | Generic |
| `get_user_by_session(session_id)` | `dict \| None` | Generic |
| `delete_session(session_id)` | `bool` | Generic |
| `cleanup_expired_sessions()` | `int` (count) | Generic |

**Session dict shape** (returned by `get_user_by_session()`):
```python
{'user_id': int, 'google_user_id': str, 'email': str, 'name': str, 'tier': str}
```

**Domain coupling**: `_ensure_default_risk_limits(user_id)` (lines 150-177) — imports `RiskLimitsManager`, creates default limits on first login. This is the only domain-specific method.

**Importers**: 17+ files (12 route modules + app.py + 2 test files + scripts like `scripts/get_api_json.py`, `tests/utils/show_api_output.py`). All use the `auth_service` singleton. Some tests also access constructor and state attributes directly (`use_database`, `last_cleanup`, `cleanup_interval`).

### 1.2 Gateway Proxy (`routes/gateway_proxy.py` — 344 lines)

**Module-level state**:
- `gateway_proxy_router = APIRouter(tags=["gateway-proxy"])`
- `_gateway_session_tokens: Dict[str, str]` — per-user token cache
- `_user_stream_locks: Dict[str, asyncio.Lock]` — per-user stream lock
- `_state_lock = asyncio.Lock()`

**Endpoints**:
- `POST /chat` — SSE streaming proxy to upstream gateway (per-user lock, token refresh on 401)
- `POST /tool-approval` — JSON proxy for tool approval

**Pydantic models**: `GatewayChatRequest`, `GatewayToolApprovalRequest`

**Domain coupling**: `_get_gateway_url()`, `_get_gateway_api_key()` read env vars. `get_current_user()` calls `auth_service.get_user_by_session()`. Everything else is generic.

**Importers**: Only `app.py` (router registration).

### 1.3 Database Client Session/User Methods (`inputs/database_client.py`)

Auth service calls `get_db_session()` directly with raw SQL — it does NOT go through `DatabaseClient` for session CRUD. The user management methods in `DatabaseClient` (`get_or_create_user_id`, `update_user_info`) are separate from auth session management.

---

## 2. Design — Protocol-Based Auth

### 2.1 Core Protocols

```python
# app_platform/auth/protocols.py
from typing import Protocol, Optional, Dict, Any

class SessionStore(Protocol):
    """Backend for session persistence."""
    def create_session(self, session_id: str, user_id: Any, expires_at: datetime) -> None: ...
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...
    def delete_session(self, session_id: str) -> bool: ...
    def cleanup_expired(self) -> int: ...
    def touch_session(self, session_id: str) -> None: ...

class UserStore(Protocol):
    """Backend for user persistence."""
    def get_or_create_user(self, provider_user_id: str, email: str, name: str) -> tuple[Any, Dict[str, Any]]: ...
        # Returns (user_id, user_dict). user_id is int for Postgres, str for InMemory.
        # user_dict has keys: email, name, tier (+ provider-specific fields).
    def get_user_by_id(self, user_id: Any) -> Optional[Dict[str, Any]]: ...

class TokenVerifier(Protocol):
    """OAuth/OIDC token verification."""
    def verify(self, token: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]: ...
```

### 2.2 Implementations

```python
# app_platform/auth/stores.py

class PostgresSessionStore:
    """SessionStore backed by psycopg2."""
    def __init__(self, get_session_fn):
        """get_session_fn: callable returning context manager (e.g., get_db_session)"""
        ...

class InMemorySessionStore:
    """SessionStore backed by dicts (dev/test mode)."""
    ...

class PostgresUserStore:
    """UserStore backed by psycopg2."""
    def __init__(self, get_session_fn):
        ...

class InMemoryUserStore:
    """UserStore backed by dicts."""
    ...
```

### 2.3 AuthService

```python
# app_platform/auth/service.py

class AuthServiceBase:
    """Generic auth service with pluggable stores and token verifier."""
    def __init__(
        self,
        session_store: SessionStore,
        user_store: UserStore,
        token_verifier: Optional[TokenVerifier] = None,
        session_duration: timedelta = timedelta(days=7),
        cleanup_interval: timedelta = timedelta(hours=1),
        strict_mode: bool = False,          # If True, no fallback to in-memory
        fallback_session_store: Optional[SessionStore] = None,  # In-memory fallback
        fallback_user_store: Optional[UserStore] = None,
    ):
        ...

    def verify_token(self, token: str) -> tuple[Optional[Dict], Optional[str]]: ...
    def create_user_session(self, user_info: Dict) -> str: ...
    def get_user_by_session(self, session_id: str) -> Optional[Dict]: ...
    def delete_session(self, session_id: str) -> bool: ...
    def cleanup_expired_sessions(self) -> int: ...

    # Hook called after user is created/updated in the PRIMARY store.
    # Receives the user_id from UserStore.get_or_create_user() return tuple.
    # Called on primary path only — NOT called when falling back to fallback store.
    def on_user_created(self, user_id: Any, user_info: Dict) -> None:
        """Post-creation hook. Default is no-op. Override in subclass.
        user_id: int (Postgres) or str (InMemory) from UserStore.get_or_create_user()[0].
        user_info: original user_info dict passed to create_user_session()."""
        pass
```

**Key design**: `AuthServiceBase` has NO domain methods. The `use_database: bool` flag is replaced by explicit store injection. DB-first + memory-fallback becomes primary store + fallback store. The `on_user_created()` hook replaces the need to override `create_user_session()` — it fires from inside `_create_or_update_user()` on the DB path only, with the resolved `user_id`.

**Fallback semantics (must match current `services/auth_service.py` behavior exactly)**:

The `strict_mode` flag (maps to current `STRICT_DATABASE_MODE`) controls whether to skip the memory fallback on primary store exceptions. Behavior varies by method:
- **`create_user_session`**: Outer catch re-raises as `AuthenticationError` → **CAN propagate to callers** in both strict and non-strict modes (if both DB and memory fail).
- **`get_user_by_session`** / **`delete_session`**: Outer catch returns safe default (`None` / `False`) → **never propagates to callers**. Strict mode only skips memory fallback before the outer catch swallows the error.
- **`cleanup_expired_sessions`**: Outer catch returns 0 → never propagates. Ignores strict_mode entirely.

| Method | Primary succeeds | Primary returns None/empty | Primary raises (strict=True) | Primary raises (strict=False) |
|--------|-----------------|---------------------------|-------|------|
| `create_user_session` | Return session_id | N/A | Inner raises `AuthenticationError` → outer catch returns error to caller | Fall through to fallback store |
| `get_user_by_session` | Return user dict | Return None (NO fallback) | Inner raises `AuthenticationError` → skips memory fallback → **outer catch returns None** | Log warning, fall through to memory → returns memory result (user dict or None). Outer catch returns None only if memory also raises. |
| `delete_session` | Return True (unconditionally, no row-count check) | N/A | Inner raises `AuthenticationError` → skips memory fallback → **outer catch returns False** | Log warning, fall through to memory (returns True if found, False if not). Outer catch returns False only if memory also raises. |
| `cleanup_expired` | Return count | N/A | Ignores strict_mode for cleanup | Same — always runs both stores. Outer catch: return 0 |

**Critical details from current code**:
- `delete_session()` DB path returns `True` unconditionally (line 375) — does NOT check rowcount. Only memory path returns `False` for not-found.
- `get_user_by_session()` outer `except` (line 345-347) catches ALL exceptions including re-raised `AuthenticationError` from strict mode, returns `None`. So strict mode effectively: raises from inner try → caught by outer try → returns None. This means **strict mode NEVER propagates to callers** for `get_user_by_session` — it just skips the memory fallback path.
- `delete_session()` same pattern: outer catch (line 392-394) returns `False` on any exception.
- `cleanup_expired_sessions()` does NOT check `STRICT_DATABASE_MODE` — always falls through to memory cleanup on DB error.

These semantics must be replicated exactly in `AuthServiceBase` and unit-tested with mock stores that raise on command vs return None.

### 2.4 Risk Module Subclass

```python
# services/auth_service.py (after extraction — thin subclass)

class AuthService(AuthServiceBase):
    """Risk-module auth with post-login risk limits initialization."""

    def __init__(self, use_database: bool = None):
        # Build stores based on use_database flag (backward compat)
        ...
        super().__init__(session_store=..., user_store=..., ...)

    def verify_google_token(self, token: str) -> tuple[Optional[Dict], Optional[str]]:
        """Preserve legacy method name — delegates to base verify_token()."""
        return self.verify_token(token)

    def on_user_created(self, user_id: Any, user_info: Dict) -> None:
        """Domain hook: create default risk limits for new DB users."""
        self._ensure_default_risk_limits(user_id)

    def _ensure_default_risk_limits(self, user_id: int):
        """Domain-specific: create default risk limits for new users.
        Takes user_id (int), NOT user_info — matches current code at line 150."""
        ...

auth_service = AuthService()  # Singleton preserved
```

**Backward-compat for `verify_google_token()`**: Routes (`routes/auth.py` lines 430, 719) call `auth_service.verify_google_token(token)`. The subclass preserves this name as a thin delegate to `verify_token()`. Base class uses the generic name.

**Risk-limits hook placement**: Current code calls `_ensure_default_risk_limits(user_id)` inside `_create_or_update_user_database()` (line 142) — on the DB path only, with the integer `user_id` from `get_or_create_user_id()`. The `on_user_created(user_id, user_info)` hook in `AuthServiceBase` fires from the same seam: after the primary `UserStore.get_or_create_user()` returns. It is NOT called in the memory fallback path. This matches current behavior exactly.

### 2.5 FastAPI Dependency

```python
# app_platform/auth/dependencies.py

def create_auth_dependency(auth_service: AuthServiceBase, cookie_name: str = "session_id"):
    """Factory for FastAPI get_current_user dependency."""
    def get_current_user(request: Request) -> dict:
        session_id = request.cookies.get(cookie_name)
        user = auth_service.get_user_by_session(session_id)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        return user
    return get_current_user
```

### 2.6 Google Token Verifier

```python
# app_platform/auth/google.py

class GoogleTokenVerifier:
    """TokenVerifier implementation for Google OAuth2."""
    def __init__(self, client_id: str, dev_mode: bool = False, dev_user: Optional[Dict] = None):
        ...
    def verify(self, token: str) -> tuple[Optional[Dict], Optional[str]]: ...
```

---

## 3. Design — Gateway Proxy

### 3.1 Module Structure

```python
# app_platform/gateway/
#     __init__.py
#     proxy.py        # Core proxy logic + router factory
#     models.py       # Pydantic request models
#     session.py      # Per-user session token cache + stream locks
```

### 3.2 Gateway Proxy Factory

```python
# app_platform/gateway/proxy.py

@dataclass
class GatewayConfig:
    """Gateway configuration. Fields accept str values OR callables for late-bound resolution.
    Callables are invoked at request time (not import time) to support env var monkeypatching in tests.
    """
    gateway_url: str | Callable[[], str] = ""          # Upstream gateway URL (or callable)
    api_key: str | Callable[[], str] = ""              # Gateway API key (or callable)
    ssl_verify: bool | str | Callable[[], bool | str] = True  # True, False, CA bundle path, or callable
    channel: str = "web"                               # Channel tag for context

    def resolve_url(self) -> str:
        return self.gateway_url() if callable(self.gateway_url) else self.gateway_url

    def resolve_api_key(self) -> str:
        return self.api_key() if callable(self.api_key) else self.api_key

    def resolve_ssl_verify(self) -> bool | str:
        return self.ssl_verify() if callable(self.ssl_verify) else self.ssl_verify

def create_gateway_router(
    config: GatewayConfig,
    get_current_user: Callable,          # FastAPI dependency (injected)
    http_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,  # Late-bound for test monkeypatching
    prefix: str = "",
) -> APIRouter:
    """Factory that creates a gateway proxy router with injected config.

    http_client_factory: If provided, called at request time to create httpx client.
    Default creates client from config.ssl_verify. Tests inject mock transports here.
    """
    ...
```

**Key design**: No module-level state. Config and auth dependency are injected. The router factory creates all state internally (token cache, stream locks).

**Gateway state invariants** (must be preserved):
1. `/tool-approval` MUST reuse the same per-user session token as `/chat` — they share a single `GatewaySessionManager` instance inside the router
2. `/tool-approval` does NOT acquire the per-user stream lock — it must succeed while `/chat` is actively streaming (the stream lock only gates concurrent `/chat` requests)
3. Token refresh on 401 is shared — if `/chat` refreshes, subsequent `/tool-approval` uses the new token
4. `_reset_proxy_state_for_tests()` must be exposed on the router or session manager for test isolation

### 3.3 SSL Verification

`ssl_verify` supports three modes (matching current `routes/gateway_proxy.py:86-98`):
- `True` — default, system CA verification
- `False` — disable SSL (local dev with self-signed certs)
- `str` — path to custom CA bundle file

```python
def _parse_ssl_verify(raw: str) -> bool | str:
    """Parse GATEWAY_SSL_VERIFY env var. Supports 'true', 'false', or CA bundle path."""
    stripped = raw.strip().lower()
    if stripped == "false":
        return False
    if stripped in ("", "true"):
        return True
    return raw.strip()  # CA bundle path — preserve original case
```

### 3.4 Risk Module Wiring

```python
# app.py (after extraction)
from app_platform.gateway import create_gateway_router, GatewayConfig

# Callables for late-bound env var resolution (request-time, not import-time).
# Matches current behavior where _get_gateway_url()/_get_gateway_api_key()
# read env vars on each call.
gateway_config = GatewayConfig(
    gateway_url=lambda: os.getenv("GATEWAY_URL", ""),
    api_key=lambda: os.getenv("GATEWAY_API_KEY", ""),
    ssl_verify=lambda: _parse_ssl_verify(os.getenv("GATEWAY_SSL_VERIFY", "")),
)
gateway_router = create_gateway_router(config=gateway_config, get_current_user=get_current_user)
app.include_router(gateway_router, prefix="/api/gateway")
```

---

## 4. Module Organization

```
app_platform/
    auth/
        __init__.py          # Core-only re-exports (NO google.py or dependencies.py imports)
        protocols.py         # SessionStore, UserStore, TokenVerifier protocols
        service.py           # AuthServiceBase
        stores.py            # PostgresSessionStore, InMemorySessionStore, PostgresUserStore, InMemoryUserStore
        google.py            # GoogleTokenVerifier (requires google-auth — NOT imported by __init__)
        dependencies.py      # create_auth_dependency() (requires FastAPI — NOT imported by __init__)
    gateway/
        __init__.py          # Re-exports: create_gateway_router, GatewayConfig
        proxy.py             # Router factory + SSE streaming logic
        models.py            # GatewayChatRequest, GatewayToolApprovalRequest
        session.py           # GatewaySessionManager (token cache + stream locks)
```

**10 new source files** across 2 subpackages.

**Import rules for `auth/__init__.py`** (core-only exports):
```python
# app_platform/auth/__init__.py — ONLY core/stdlib modules
from .protocols import SessionStore, UserStore, TokenVerifier
from .service import AuthServiceBase
from .stores import PostgresSessionStore, InMemorySessionStore, PostgresUserStore, InMemoryUserStore

# DO NOT import from .google (requires google-auth)
# DO NOT import from .dependencies (requires FastAPI)
# Consumers import those directly: from app_platform.auth.google import GoogleTokenVerifier
```

---

## 5. Extraction Phases

### Phase 5: Auth Service

**Steps**:
1. Create `app_platform/auth/protocols.py` — `SessionStore`, `UserStore`, `TokenVerifier` protocols
2. Create `app_platform/auth/stores.py` — `PostgresSessionStore`, `InMemorySessionStore`, `PostgresUserStore`, `InMemoryUserStore`
3. Create `app_platform/auth/google.py` — `GoogleTokenVerifier` (extract from `verify_google_token()`)
4. Create `app_platform/auth/service.py` — `AuthServiceBase` with store injection, dual-mode fallback, cleanup interval
5. Create `app_platform/auth/dependencies.py` — `create_auth_dependency()` factory
6. Create `app_platform/auth/__init__.py` with re-exports
7. Update `services/auth_service.py` → thin subclass of `AuthServiceBase`:
   - Constructor builds stores from `use_database` flag (backward compat)
   - Add `verify_google_token()` as alias for `verify_token()` (preserves `routes/auth.py` callers)
   - Override `on_user_created(user_id, user_info)` to call `_ensure_default_risk_limits(user_id)` — DB path only, with integer user_id
   - Keep `auth_service = AuthService()` singleton
   - Preserve instance attributes accessed by tests: `use_database`, `last_cleanup`, `cleanup_interval`, `session_duration`
   - All 17+ importers unchanged
8. Write tests for `app_platform.auth` in isolation (mock stores):
   - Protocol conformance for all 4 store implementations
   - AuthServiceBase: session CRUD, token verify delegation, fallback semantics (exception vs miss), cleanup
   - GoogleTokenVerifier: mock `google.oauth2.id_token`, dev mode bypass
   - Fallback edge cases: primary raises → fallback used; primary returns None → no fallback; strict_mode=True → no fallback
9. Write shim compatibility tests:
   - `from services.auth_service import auth_service` — singleton exists
   - `auth_service.verify_google_token` — method exists (legacy name)
   - `auth_service.get_user_by_session()` returns dict with 5 keys
   - `auth_service.use_database` — attribute accessible
   - `AuthService(use_database=False)` — constructor backward compat

**Risk**: Medium — 17+ importers, but shim + subclass preserves exact interface. `get_user_by_session()` return shape is the contract; it does not change.

**Key constraints**:
- `_ensure_default_risk_limits()` must NOT move to `app_platform`. It imports `RiskLimitsManager` from `core/`.
- `verify_google_token()` method name must be preserved on the subclass (called by `routes/auth.py` lines 430, 719).
- `on_user_created()` hook fires with `user_id: int` (from `UserStore.get_or_create_user()`) — NOT with `user_info` dict. This matches current `_ensure_default_risk_limits(user_id)` signature at line 150.

### Phase 6: Gateway Proxy

**Steps**:
1. Create `app_platform/gateway/models.py` — `GatewayChatRequest`, `GatewayToolApprovalRequest`
2. Create `app_platform/gateway/session.py` — `GatewaySessionManager` (token cache + stream locks + init/refresh)
3. Create `app_platform/gateway/proxy.py` — `create_gateway_router()` factory + `GatewayConfig`. Move all streaming/proxy logic here.
4. Create `app_platform/gateway/__init__.py` with re-exports
5. Update `routes/gateway_proxy.py` → thin shim:
   ```python
   """Backward-compatible shim."""
   from app_platform.gateway import create_gateway_router, GatewayConfig
   from app_platform.gateway.proxy import _parse_ssl_verify
   import os

   # Pass callables so config resolves at REQUEST time (not import time).
   # Current code reads env vars via _get_gateway_url()/_get_gateway_api_key()
   # at request time. Tests monkeypatch env vars after import.
   _config = GatewayConfig(
       gateway_url=lambda: os.getenv("GATEWAY_URL", ""),
       api_key=lambda: os.getenv("GATEWAY_API_KEY", ""),
       ssl_verify=lambda: _parse_ssl_verify(os.getenv("GATEWAY_SSL_VERIFY", "")),
   )
   from services.auth_service import auth_service
   from app_platform.auth.dependencies import create_auth_dependency
   _get_current_user = create_auth_dependency(auth_service)
   gateway_proxy_router = create_gateway_router(config=_config, get_current_user=_get_current_user)
   import sys as _sys

   # Late-bound http client factory — tests monkeypatch THIS module-level name.
   # The router's endpoint handlers dereference it at request time (not capture time).
   def _create_http_client():
       from app_platform.gateway.proxy import default_http_client_factory
       return default_http_client_factory(_config.resolve_ssl_verify())

   # Pass a lambda that defers to the module-level name, so monkeypatching works:
   gateway_proxy_router = create_gateway_router(
       config=_config,
       get_current_user=_get_current_user,
       http_client_factory=lambda: _sys.modules[__name__]._create_http_client(),
   )

   # Expose internal state for backward-compat test monkeypatching.
   _gateway_session_tokens = gateway_proxy_router._session_manager._tokens
   _user_stream_locks = gateway_proxy_router._session_manager._stream_locks
   _reset_proxy_state_for_tests = gateway_proxy_router._session_manager.reset
   # Also re-export auth_service for monkeypatching gateway_proxy.auth_service
   from services.auth_service import auth_service
   ```

**Gateway shim monkeypatch compatibility**: Current `tests/test_gateway_proxy.py` monkeypatches the shim module directly via `import routes.gateway_proxy as gateway_proxy`. It accesses:
- `gateway_proxy._create_http_client` — replaced with mock transport factory
- `gateway_proxy.auth_service` — `.get_user_by_session` patched
- `gateway_proxy._gateway_session_tokens` — dict mutated directly for pre-seeding tokens
- `gateway_proxy._user_stream_locks` — dict mutated directly for lock simulation
- `gateway_proxy._reset_proxy_state_for_tests()` — called in autouse fixture

**Late-binding for `_create_http_client`**: The `http_client_factory` parameter receives a lambda that defers lookup to the shim module's `_create_http_client` via `sys.modules[__name__]`. When tests `monkeypatch.setattr(gateway_proxy, "_create_http_client", ...)`, the lambda picks up the patched version at request time. This matches the current behavior where endpoint handlers call the module-level function directly.

**Dict identity for `_gateway_session_tokens` / `_user_stream_locks`**: The shim exposes references to the `GatewaySessionManager`'s internal dicts. Tests mutate these dicts directly (e.g., `gateway_proxy._gateway_session_tokens["101"] = "token-1"`). Since Python dict assignment mutates in-place, the session manager sees the change. `_reset_proxy_state_for_tests()` must `.clear()` these dicts (not replace them) to preserve identity.
6. Write tests for `app_platform.gateway` in isolation (mock httpx, mock auth)
7. Write shim compatibility test: `from routes.gateway_proxy import gateway_proxy_router` still works

**Risk**: Medium — single production importer (`app.py`), but `tests/test_gateway_proxy.py` has a broad monkeypatch surface against `routes.gateway_proxy` internals (`_create_http_client`, `_gateway_session_tokens`, `_user_stream_locks`, `auth_service`). Shim must re-export all these as module-level names.

**Dependency**: Phase 5 must be complete (gateway uses `create_auth_dependency`).

### Phase 7: Housekeeping

**Steps**:
1. Update `app_platform/pyproject.toml` — bump to 0.2.0, add `google-auth` to auth optional extra
2. Update plan status
3. Update CLAUDE.md if needed

---

## 6. Dependency Management (Updated)

```toml
[project.optional-dependencies]
fastapi = [
    "fastapi>=0.100",
    "starlette",
    "slowapi>=0.1.9",
]
auth-google = [
    "google-auth>=2.0",
]
gateway = [
    "httpx>=0.24",
    "fastapi>=0.100",
]
all = ["app-platform[fastapi,auth-google,gateway]"]
```

| Subpackage | Required extra | Notes |
|-----------|---------------|-------|
| `app_platform.db` | (core) | |
| `app_platform.logging` | (core) | |
| `app_platform.middleware` | `fastapi` | |
| `app_platform.auth` (base) | (core) | Protocols, stores, AuthServiceBase — stdlib only |
| `app_platform.auth.google` | `auth-google` | GoogleTokenVerifier |
| `app_platform.auth.dependencies` | `fastapi` | `create_auth_dependency()` uses FastAPI Request/HTTPException |
| `app_platform.gateway` | `gateway` | httpx + FastAPI |

**Import leakage prevention**: `app_platform/__init__.py` will NOT eagerly re-export `auth` or `gateway` subpackages. These are opt-in imports only (`from app_platform.auth import ...`, `from app_platform.gateway import ...`). The top-level `__init__.py` continues to re-export only v1 subpackages (db, logging, middleware) which are core/always-available.

**`google-auth-oauthlib` dropped**: Not needed — current code uses `google.oauth2.id_token.verify_oauth2_token()` which is in `google-auth` alone. `oauthlib` is for the full OAuth flow which we don't do server-side.

---

## 7. Testing

### Package-level tests
```
tests/app_platform/
    test_auth_protocols.py       # Protocol conformance for all 4 store implementations
    test_auth_stores_memory.py   # InMemorySessionStore, InMemoryUserStore (full lifecycle)
    test_auth_stores_postgres.py # PostgresSessionStore, PostgresUserStore (mock get_db_session)
    test_auth_service.py         # AuthServiceBase with mock stores:
                                 #   - session CRUD lifecycle
                                 #   - on_user_created hook fires on DB path only
                                 #   - fallback: primary exception → fallback used
                                 #   - fallback: primary returns None → NO fallback
                                 #   - strict_mode=True → skips memory fallback, outer catch returns None/False (never propagates to caller)
                                 #   - cleanup: always runs both stores
                                 #   - cleanup_interval respected (skip if too soon)
    test_auth_google.py          # GoogleTokenVerifier (mock google.oauth2.id_token)
                                 #   - valid token → user_info dict
                                 #   - invalid token → (None, error_message)
                                 #   - dev mode → mock user returned
    test_auth_dependencies.py    # create_auth_dependency:
                                 #   - valid session → user dict
                                 #   - missing cookie → 401
                                 #   - expired session → 401
    test_gateway_session.py      # GatewaySessionManager:
                                 #   - token cache per user_key
                                 #   - stream lock per user_key (concurrent /chat rejected)
                                 #   - /tool-approval does NOT need stream lock
                                 #   - token refresh on 401
                                 #   - reset() clears all state
    test_gateway_proxy.py        # create_gateway_router factory (1:1 with tests/test_gateway_proxy.py):
                                 #   - Session token caching: two /chat calls → one /api/chat/init
                                 #   - SSE streaming + passthrough ordering (text_delta, tool_approval, stream_complete)
                                 #   - SSE response headers (content-type, cache-control, x-accel-buffering) + no set-cookie
                                 #   - 401 retry with new token on /chat (init called twice, chat auth changes)
                                 #   - /tool-approval 401 passthrough WITHOUT refresh (returns error as-is)
                                 #   - /tool-approval shares per-user token with /chat (same Bearer header)
                                 #   - /tool-approval bypasses stream lock (succeeds while lock held)
                                 #   - concurrent /chat rejected (409) when lock held
                                 #   - channel forcing (always "web") + model stripping from upstream payload
                                 #   - tolerant session-token extraction (nested session.token, session.session_token)
                                 #   - ssl_verify: True, False, CA bundle path (via _create_http_client)
                                 #   - allow_tool_type forwarding in approval payload
                                 #   - unauthenticated request → 401 (no upstream call)
    test_gateway_models.py       # Pydantic model validation
```

### Shim compatibility tests
```
tests/app_platform/
    test_shim_auth.py            # from services.auth_service import auth_service
                                 #   - singleton exists, is AuthService
                                 #   - verify_google_token() method exists (legacy name)
                                 #   - get_user_by_session returns dict with 5 keys
                                 #   - use_database attribute accessible
                                 #   - AuthService(use_database=False) constructor works
                                 #   - last_cleanup, cleanup_interval, session_duration attributes
    test_shim_gateway.py         # from routes.gateway_proxy import gateway_proxy_router
                                 #   - is APIRouter with routes at /chat and /tool-approval
                                 #   - _reset_proxy_state_for_tests callable
                                 #   - _create_http_client callable and monkeypatchable
                                 #   - _gateway_session_tokens is a mutable dict
                                 #   - _user_stream_locks is a mutable dict
                                 #   - auth_service accessible for monkeypatching
                                 #   - GATEWAY_URL/GATEWAY_API_KEY/GATEWAY_SSL_VERIFY env vars all read at request time
                                 #     (test: monkeypatch env after import, verify values used in request)
```

### Key assertions
- `auth_service.get_user_by_session()` returns dict with keys: `user_id`, `google_user_id`, `email`, `name`, `tier`
- `auth_service.verify_google_token` is callable (legacy method name preserved)
- `auth_service.create_user_session()` returns `str`
- `gateway_proxy_router` is an `APIRouter` with routes at `/chat` and `/tool-approval`
- `_ensure_default_risk_limits()` is NOT in `app_platform` (grep guard)
- `grep -r "RiskLimitsManager" app_platform/` returns zero matches
- `grep -r "from app_platform.auth" app_platform/__init__.py` returns zero matches (no eager re-export)

---

## 8. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Session dict shape changes | Protocol defines return type. Shim test asserts all 5 keys. |
| `_ensure_default_risk_limits` leaks to platform | Stays in risk_module subclass via `on_user_created()` hook. Grep guard in tests. |
| `verify_google_token()` method name breakage | Subclass preserves method as alias for `verify_token()`. Shim test verifies. |
| Risk-limits hook wrong seam/signature | `on_user_created(user_id, user_info)` fires from DB user creation path only, with integer `user_id`. NOT from memory fallback. NOT from session creation. Matches current `_create_or_update_user_database()` line 142. |
| `use_database` flag backward compat | Subclass constructor maps `use_database=True` → Postgres stores, `False` → InMemory stores. Instance attribute preserved. |
| `STRICT_DATABASE_MODE` fallback semantics | Outer try/except catches ALL exceptions (including re-raised AuthenticationError from strict mode). `get_user_by_session` → returns None. `delete_session` → returns False. Strict mode effectively just skips memory fallback, never propagates to callers. `delete_session` DB path returns True unconditionally (no rowcount check). Cleanup ignores strict_mode. All documented in fallback semantics table. |
| Module-level singleton timing | `auth_service = AuthService()` stays at module level in `services/auth_service.py`. Same import-time behavior. |
| Test/script attribute access | Subclass preserves `use_database`, `last_cleanup`, `cleanup_interval`, `session_duration` as instance attributes. |
| Optional dependency import leakage | `app_platform/__init__.py` does NOT re-export auth/gateway. They are opt-in subpackage imports only. `auth.dependencies` requires `fastapi` extra. `auth.google` requires `auth-google` extra. |
| Gateway env vars frozen at import time | `GatewayConfig` fields accept callables (lambdas). Shim passes `lambda: os.getenv(...)`. `resolve_url()`/`resolve_api_key()`/`resolve_ssl_verify()` called at request time. Tests monkeypatch env vars after import — verified in shim tests. |
| `GATEWAY_SSL_VERIFY` path regression | `ssl_verify: bool \| str \| Callable`. `_parse_ssl_verify()` handles true/false/CA-bundle-path. Unit test for all 3 modes. |
| Gateway `/tool-approval` token sharing | Both endpoints share single `GatewaySessionManager`. `/tool-approval` does NOT acquire stream lock. Explicit test. |
| `google-auth` import at module level | `GoogleTokenVerifier` is in its own module (`auth/google.py`). Auth service base has no google imports. |
| `_reset_proxy_state_for_tests()` | Exposed via `GatewaySessionManager.reset()`. Shim re-exports for backward compat. |

---

## 9. PyPI Distribution (Deferred)

Still deferred. When ready:
- Name options: `web-app-platform`, `app-infra`, `fastapi-app-platform` (avoid Azure collision)
- Sync script pattern: `scripts/sync_app_platform.sh` (like `scripts/sync_fmp_mcp.sh`)
- Only publish when a second consumer repo exists

---

## 10. Success Criteria

1. `app_platform.auth` passes own tests with zero risk_module imports
2. `app_platform.gateway` passes own tests with zero risk_module imports
3. All 17+ auth_service importers work unchanged via shim/subclass
4. `verify_google_token()` method name preserved on subclass
5. Gateway proxy shim works unchanged for app.py
6. Full risk_module test suite passes (including `tests/test_gateway_proxy.py`)
7. `grep -r "RiskLimitsManager" app_platform/` returns zero matches
8. `grep -r "from app_platform.auth" app_platform/__init__.py` returns zero matches (no eager re-export)
9. Session dict shape preserved (5 keys: user_id, google_user_id, email, name, tier)
10. `GATEWAY_SSL_VERIFY` supports true/false/CA-bundle-path (no regression)
11. `/tool-approval` shares per-user token with `/chat` and bypasses stream lock
