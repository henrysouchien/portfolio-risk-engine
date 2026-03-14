# Security Audit Remediation Plan

**Date**: 2026-03-12
**Audit**: `docs/planning/SECURITY_AUDIT_FINDINGS.md`
**Codex Review**: Incorporated (2026-03-12)
**Status**: Plan — ready for implementation

## Context

Security audit (2026-03-12) found 3 critical, 4 high, 7 medium, and 4 low findings across auth, CORS, rate limiting, error handling, and dependencies. This plan addresses all code-level findings. AWS/infra items (RDS SG, EC2 SG, SSH config, DB users, instance profiles) are deployment concerns and out of scope.

## Codex Review Corrections Applied

- Step 1: Keep `DEFAULT_SESSION_SECRET` in re-exports (`middleware/__init__.py`, `app_platform/__init__.py`) but deprecate it — avoids import breakage
- Step 2: `require_admin_token` is nested in `admin.py` factory and not importable — inline the check in `auth.py` instead
- Step 3: Added `PATCH` to CORS methods (used by `PATCH /api/portfolios/{name}`). Also update `app_platform/middleware/cors.py` defaults
- Step 4: Existing limiter key func is tier-based (reads `?key=`), not IP-based — use `key_func=get_remote_address` override for auth/admin routes
- Step 5: Also update `_build_key_func()` in `app_platform/middleware/rate_limiter.py:95` and 429 logging in `app.py:1055` to check header
- Step 7: Expanded scope — stale query-param references in admin docstrings at lines 395, 507, 692 and `docs/interfaces/api.md:53`
- Step 9: `.env.example` already exists — this is an edit, not create
- Step 10: Most packages are transitive deps not pinned in `requirements.txt` — use `pip install --upgrade` then freeze
- Step 11: `happy-dom` is exact-pinned at 17.6.1 — must edit `package.json` version, not just `pnpm update`
- Audit correction: `POST /auth/refresh` does not exist — removed from rate limiting list

## Steps

### Step 1: Session Secret — Require in Production (CRITICAL)

**Files**: `app.py:993-999`, `app_platform/middleware/sessions.py`, `app_platform/middleware/__init__.py`, `app_platform/__init__.py`

- In `app_platform/middleware/sessions.py`: Update `resolve_session_secret()` to accept `environment` kwarg and raise `RuntimeError` if `FLASK_SECRET_KEY` is unset AND `environment == "production"`
- Keep `DEFAULT_SESSION_SECRET` constant but set it to empty string `""` — preserves re-exports in `middleware/__init__.py:12` and `app_platform/__init__.py:54` without exposing a usable default
- In `app.py:993-999`: Pass `environment=_is_production` context to the resolver. Keep the dev fallback for local dev, crash hard in production

```python
# app_platform/middleware/sessions.py
DEFAULT_SESSION_SECRET = ""  # empty — callers must provide via env var

def resolve_session_secret(secret_key: str = "", *, environment: str = "") -> str:
    if secret_key:
        return secret_key
    env_key = os.getenv("FLASK_SECRET_KEY", "")
    if not env_key and environment == "production":
        raise RuntimeError(
            "FLASK_SECRET_KEY must be set in production. "
            "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return env_key or "dev-only-not-for-production"
```

```python
# app.py:993-999
secret_key=resolve_session_secret(environment="production" if _is_production else "development"),
```

---

### Step 2: Fix `/auth/cleanup` Fail-Open Auth (CRITICAL)

**File**: `routes/auth.py:562-650`

Inline the admin token check (can't import `require_admin_token` — it's nested inside `admin.py`'s `create_admin_router()` factory). Use `Header(...)` to make the token required at the FastAPI validation level.

- Add `x_admin_token: str = Header(..., alias="X-Admin-Token")` as function parameter
- Remove the manual `os.getenv("ADMIN_TOKEN")` conditional block (lines 634-638)
- Remove the query-param fallback
- Keep `request: Request` param (needed for rate limiting in Step 4)
- Update the docstring (currently says "No authentication required")

```python
@auth_router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_sessions(
    request: Request,
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
):
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # ... rest of cleanup logic
```

---

### Step 3: Restrict CORS Methods/Headers (HIGH)

**Files**: `app.py:984-991`, `app_platform/middleware/cors.py`

Replace wildcards with explicit whitelist. Include `PATCH` (used by `PATCH /api/portfolios/{name}` at app.py:4116).

```python
# app.py:984-991
allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
allow_headers=[
    "Content-Type", "Authorization", "X-API-Key", "X-Admin-Token",
    "X-Requested-With", "Accept", "Origin",
],
```

Also update `app_platform/middleware/cors.py` defaults to match:
```python
DEFAULT_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
DEFAULT_HEADERS = ["Content-Type", "Authorization", "X-API-Key", "X-Admin-Token",
                   "X-Requested-With", "Accept", "Origin"]
```

---

### Step 4: Rate Limiting on Auth/Admin Endpoints (HIGH)

**Files**: `routes/auth.py`, `routes/admin.py`

SlowAPI infra exists but uses a tier-based key func (`_build_key_func` reads `?key=`). For auth/admin endpoints, override with IP-based limiting using `key_func=get_remote_address`:

```python
from slowapi.util import get_remote_address
from utils.rate_limiter import limiter

@auth_router.post("/google")
@limiter.limit("10/minute", key_func=get_remote_address)
async def google_auth(request: Request, ...):
```

Endpoints and limits:
- `POST /auth/google` — `10/minute` (login)
- `POST /auth/logout` — `20/minute` (logout)
- `POST /auth/cleanup` — `5/minute` (admin)
- `POST /generate_key` — `5/minute` (admin)
- `GET /admin/usage_summary` — `10/minute` (admin)
- `GET /admin/cache_status` — `10/minute` (admin)
- `POST /admin/clear_cache` — `5/minute` (admin)

Ensure `request: Request` is the first parameter on each endpoint (SlowAPI requirement). Decorator goes after `@router.method()`, before `@log_operation()`.

---

### Step 5: API Key from Header Instead of Query Param (MEDIUM)

**Files**: `app.py:1087-1090`, `app_platform/middleware/rate_limiter.py:95`, `app.py:1055`

Change `get_api_key()` to read from header first, fall back to query param for backwards compat:

```python
# app.py:1087-1090
def get_api_key(request: Request) -> str:
    """FastAPI dependency to get API key from header (preferred) or query params."""
    return (
        request.headers.get("X-API-Key")
        or request.query_params.get("key")
        or PUBLIC_KEY
    )
```

Also update the rate limiter key func to match (`app_platform/middleware/rate_limiter.py:95`):
```python
user_key = request.headers.get("X-API-Key") or request.query_params.get("key", public_key)
```

And the 429 logging in `app.py:1055`:
```python
user_key = request.headers.get("X-API-Key") or request.query_params.get("key", PUBLIC_KEY)
```

---

### Step 6: Genericize Auth Error Messages in Production (MEDIUM)

**File**: `routes/auth.py:435, 471, 560, 650`

Replace exception-detail-in-response with generic messages when in production:

```python
_is_production = os.getenv("ENVIRONMENT", "development") == "production"

# Line 435 (google_auth token verification):
detail = "Authentication failed" if _is_production else f"Token verification failed: {error}"
raise HTTPException(status_code=401, detail=detail)

# Line 471 (google_auth catch-all):
detail = "Authentication failed" if _is_production else str(e)
raise HTTPException(status_code=500, detail=detail)

# Line 560 (logout catch-all):
detail = "An error occurred" if _is_production else str(e)
raise HTTPException(status_code=500, detail=detail)

# Line 650 (cleanup catch-all):
detail = "An error occurred" if _is_production else str(e)
raise HTTPException(status_code=500, detail=detail)
```

---

### Step 7: Fix Stale Docstrings (LOW)

**Files**:
- `routes/admin.py:288` — Remove "No authentication required" from `/generate_key` docstring
- `routes/admin.py:234-260` — Update `require_admin_token` docstring (still references "query parameter")
- `routes/admin.py:395,507,692` — Update usage_summary, cache_status, clear_cache docstrings (may reference query-param auth)
- `routes/auth.py:576` — Update `/cleanup` docstring to say "Requires X-Admin-Token header"
- `docs/interfaces/api.md:53` — Update admin auth docs from query-param to header

---

### Step 8: Remove Hardcoded User Paths (LOW)

**Files**:
- `mcp_server.py:9` — Replace with relative path or `__file__`-based
- `fmp/server.py:9` — Same
- `fmp/examples/fcf_analysis.py:12` — Use `Path(__file__).resolve().parents[2]`
- `fmp/examples/treasury_yield_analysis.py:11` — Same
- `scripts/explore_transactions.py:272` — Use `Path(__file__).parent / "transaction_samples"`

---

### Step 9: Add `FLASK_SECRET_KEY` to `.env.example` (LOW)

**File**: `.env.example` (edit — file already exists)

Add after the `ENVIRONMENT=development` line:
```
# Session Security (REQUIRED in production - generate with: python -c "import secrets; print(secrets.token_hex(32))")
FLASK_SECRET_KEY=
```

---

### Step 10: Dependency Upgrades — Python (HIGH)

Most flagged packages are transitive deps not directly pinned in `requirements.txt`. Strategy:

1. Upgrade priority packages (web + auth stack): `pip install --upgrade werkzeug flask jinja2 cryptography authlib python-multipart aiohttp h11 urllib3`
2. Upgrade secondary packages: `pip install --upgrade pypdf pdfminer-six pillow protobuf pyasn1 marshmallow tornado setuptools`
3. Re-run `pip audit` to verify reduction
4. Run `pytest` to catch breakage
5. Pin any directly-imported packages that are in `requirements.txt`

Skip: `diskcache` (no fix available), `yt-dlp` (not used in prod), `fonttools`/`jupyter-core`/`nbconvert` (dev tooling only).

---

### Step 11: Dependency Upgrades — Node (MEDIUM)

**File**: `frontend/package.json`

`happy-dom` is exact-pinned at `17.6.1` — `pnpm update` alone won't cross major versions.

1. Edit `frontend/package.json`: change `"happy-dom": "17.6.1"` → `"happy-dom": "^20.0.0"`
2. Run `pnpm install` to update lockfile
3. Run `pnpm test` to verify vitest compatibility
4. For minimatch/js-yaml: check if upgrading `@redocly/openapi-core` and `eslint` resolves transitive deps. If not, add `pnpm.overrides` in `package.json`

---

## Out of Scope (deployment/infra items — no code changes)

- RDS security group (checklist item 3)
- EC2 security group (checklist item 4)
- Google OAuth Console origins (checklist item 6)
- SSH key-only (checklist item 9)
- AWS instance profiles vs IAM keys (checklist item 10)
- FMP read-only DB user (checklist item 11)
- SameSite=strict (keeping lax — required for OAuth redirect flow; CSRF risk is low with httponly + auth-token model)
- `detect-secrets` pre-commit hook (nice-to-have, not a code fix)
- API key tier self-selection (Codex flagged: callers can pick a higher-tier key from `TIER_MAP` defaults — existing design issue, not introduced by this plan)

## Verification

1. **Unit tests**: Run `pytest` — no regressions from steps 1-9
2. **Manual startup test**: Set `ENVIRONMENT=production` without `FLASK_SECRET_KEY` → app should crash with clear `RuntimeError`
3. **Manual auth test**: `curl -X POST /auth/cleanup` without `X-Admin-Token` → 422 (missing required header)
4. **Manual CORS test**: `curl -X TRACE` against the API → should be rejected
5. **Rate limit test**: Hit `/auth/google` 11 times in 1 minute → 429 on 11th
6. **Import test**: `python -c "from app_platform.middleware import DEFAULT_SESSION_SECRET"` → should import (empty string, no crash)
7. **pip audit**: Re-run after step 10, confirm vuln count reduction
8. **pnpm audit**: Re-run after step 11, confirm happy-dom resolved
9. **Frontend tests**: `cd frontend && pnpm test` — no regressions from happy-dom upgrade

## Execution Order

1. **Commit 1** (Critical/High — Steps 1-4): Session secret enforcement, cleanup auth fix, CORS restriction, rate limiting
2. **Commit 2** (Medium/Low — Steps 5-9): API key header, error messages, docstrings, hardcoded paths, .env.example
3. **Commit 3** (Python deps — Step 10): Upgrade + test + pin
4. **Commit 4** (Node deps — Step 11): happy-dom major version bump + test
