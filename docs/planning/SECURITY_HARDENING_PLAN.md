# Security Hardening Plan — Pre-Deploy Checklist

**Date**: 2026-03-19
**Status**: Plan — ready for implementation
**Prerequisite docs**:
- `docs/planning/completed/SECURITY_AUDIT_FINDINGS.md` (2026-03-12 audit, 3 critical / 4 high / 7 medium / 4 low)
- `docs/planning/completed/SECURITY_REMEDIATION_PLAN.md` (11-step remediation, partially implemented)
- `docs/deployment/SECURITY_IMPLEMENTATION_PLAN.md` (original deployment checklist)

## Context

The remediation plan addressed critical/high findings (session secret enforcement, `/auth/cleanup` fail-open, CORS restriction, rate limiting on auth/admin). This plan covers the 10 remaining hardening items that were either out-of-scope in that plan or explicitly deferred. These are all code-level changes needed before multi-user production deployment.

### Current State Summary

| Area | Status |
|------|--------|
| Session secret enforcement | DONE (`resolve_session_secret()` crashes in prod if unset) |
| `/auth/cleanup` fail-open | DONE (requires `X-Admin-Token` header) |
| CORS methods/headers | DONE (explicit whitelist, no wildcards) |
| Auth/admin rate limiting | DONE (IP-based via `get_remote_address`) |
| API key header preference | DONE (header-first, query-param fallback) |
| CSRF protection | DONE (signed double-submit token middleware + frontend `X-CSRF-Token` support) |
| Security headers middleware | DONE (`SecurityHeadersMiddleware` on backend + nginx static headers for Hank) |
| Production CORS origin lockdown | DONE (production rejects empty, wildcard, localhost/loopback, non-HTTPS, and path-bearing origins) |
| OpenAPI docs disabled in prod | DONE (`FastAPI()` docs/OpenAPI/Redoc routes disabled in production) |
| Error message sanitization | DONE for production 5xx `HTTPException` responses (global handler preserves 4xx/user errors and dev diagnostics) |
| Plaid webhook JWT verification | NOT DONE (uses forward-auth shared secret only) |
| Pre-commit secrets scanning | DONE (local pre-commit hook scans staged files for common credential formats) |
| Dependency vulnerability scan | DONE (`pip-audit` and `pnpm audit` return 0 vulnerabilities after pin/lock refresh) |
| PII audit of logs | DONE for production auth/Kartra email logs (`redact_email()` masks addresses before logging) |
| MCP tool duplicate audit | DONE (AST test prevents duplicate tool names per MCP server) |

---

## Priority Ordering

Items are sequenced by risk-to-effort ratio. Higher-risk items that block production go first; lower-risk polish items go last.

| Priority | Item | Risk | Effort |
|----------|------|------|--------|
| P0 | 5. Error message sanitization | HIGH — `str(e)` in ~45 HTTP responses leaks internals | 2h |
| P0 | 4. Disable OpenAPI docs in production | HIGH — full API schema exposed, trivial fix | 15min |
| P0 | 3. Production CORS lockdown | HIGH — must enforce exact origins in prod | 30min |
| P1 | 2. Security headers middleware | HIGH — missing HSTS/CSP/X-Frame enables XSS/clickjack | 1h |
| P1 | 1. CSRF protection middleware | MEDIUM — SameSite=lax + httponly cookies provide partial defense | 2h |
| P1 | 8. Dependency vulnerability scan + pin | HIGH — 47 Python CVEs identified in audit | 2h |
| P2 | 6. Plaid webhook JWT signature verification | MEDIUM — forward-auth exists but not Plaid-native JWT | 2h |
| P2 | 9. PII audit of log statements + redaction | MEDIUM — user emails logged in auth events and Kartra push | 1.5h |
| P3 | 7. Pre-commit secrets scanning hook | LOW — `.env` is gitignored; this is defense-in-depth | 30min |
| P3 | 10. Duplicate MCP tool registration audit | LOW — no runtime risk, but tooling hygiene | 1h |

**Total estimated effort**: ~13 hours

---

## Item 1: CSRF Protection Middleware

### Current State
Completed. Session cookies use `SameSite=lax` and `httponly=True`; unsafe cookie-authenticated requests now also require a signed CSRF token echoed in `X-CSRF-Token`.

Implementation details:
- `GET /api/csrf-token` issues a JSON `csrf_token` and an HttpOnly signed `csrf_token` cookie.
- The signed cookie is bound to the current `session_id` value and expires after 12 hours.
- Unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) are rejected with `403` and `error: csrf_failed` when a `session_id` cookie is present but the token is missing, expired, mismatched, or bound to a different session.
- Requests without a `session_id` cookie are left alone so public/API-key flows are not broken.
- OAuth/dev-login bootstrap, Plaid webhook, SnapTrade webhook, and frontend log ingestion are exempt.

### Files to Modify
- `app_platform/middleware/csrf.py` — signed token helpers and ASGI middleware
- `app_platform/middleware/__init__.py` — middleware exports
- `app.py` — `GET /api/csrf-token`, CORS `X-CSRF-Token`, and middleware wiring
- `frontend/packages/app-platform/src/http/HttpClient.ts` — fetch/cache/send CSRF token for mutating requests, refresh once on `csrf_failed`
- `tests/app_platform/test_csrf_middleware.py` — backend coverage
- `frontend/packages/app-platform/src/http/HttpClient.test.ts` — frontend coverage

### Implementation

```python
# app.py — inside create_app()
@app.get("/api/csrf-token")
async def get_csrf_token(request: Request):
    return create_csrf_token_response(
        request,
        secret_key=session_secret,
        secure_cookie=_is_production,
    )

app.add_middleware(CsrfProtectionMiddleware, secret_key=session_secret)
```

The frontend `HttpClient` now fetches `/api/csrf-token` before mutating requests, attaches `X-CSRF-Token`, and refreshes/retries once if the backend returns `error: csrf_failed`.

### Testing
- `pytest tests/app_platform/test_csrf_middleware.py tests/app_platform/test_middleware.py tests/routes/test_openapi_docs.py -q`
- `cd frontend && pnpm vitest run packages/app-platform/src/http/HttpClient.test.ts`
- `python3 -m py_compile app_platform/middleware/csrf.py app.py`
- `python3 -m flake8 app_platform/middleware/csrf.py tests/app_platform/test_csrf_middleware.py --max-line-length=120 --ignore=E501,W503`

### Rollback
Remove the `/api/csrf-token` route, `CsrfProtectionMiddleware` wiring, frontend token attach logic, and tests. No database changes. Fully reversible.

---

## Item 2: Security Headers Middleware

### Current State
No security headers middleware. Responses lack HSTS, X-Frame-Options, X-Content-Type-Options, CSP, and Referrer-Policy.

### Files to Modify
- `app_platform/middleware/security_headers.py` — NEW file
- `app_platform/middleware/__init__.py` — re-export
- `app.py` — add middleware in `create_app()` (after CORS, before session)

### Implementation

```python
# app_platform/middleware/security_headers.py
"""Security response headers middleware."""

from __future__ import annotations

import os

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, is_production: bool = False, csp_connect_src: str = ""):
        super().__init__(app)
        self.is_production = is_production
        self.csp_connect_src = csp_connect_src

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"  # Modern: disable legacy XSS auditor
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )

        if self.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # CSP: allow self + known external APIs
        connect_sources = "'self'"
        if self.csp_connect_src:
            connect_sources += f" {self.csp_connect_src}"

        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "  # React CSS-in-JS needs unsafe-inline
            "img-src 'self' data: https:; "
            f"connect-src {connect_sources}; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )

        return response


__all__ = ["SecurityHeadersMiddleware"]
```

```python
# app.py — inside create_app(), after CORS middleware
app.add_middleware(
    SecurityHeadersMiddleware,
    is_production=_is_production,
    csp_connect_src=(
        "https://api.anthropic.com "
        "https://production.plaid.com "
        "https://sandbox.plaid.com "
        "https://financialmodelingprep.com"
    ),
)
```

### Testing
- Unit: Test middleware class directly — verify each header present on response
- Manual: `curl -I https://localhost:5001/api/health` and inspect headers
- CSP: Load frontend in browser, check console for CSP violations (expect none for normal flows)

### Rollback
Remove `app.add_middleware(SecurityHeadersMiddleware, ...)` line. No data changes.

---

## Item 3: Production CORS Lockdown

### Current State
`app.py:309-314` reads `CORS_ALLOWED_ORIGINS` env var, defaulting to `http://localhost:3000,https://localhost:8000`. Methods and headers are already restricted (remediation Step 3 fixed wildcards). The remaining gap: no enforcement that production deploys MUST set this env var to exact domain(s).

### Files to Modify
- `app.py` (~line 309) — add production validation
- `app_platform/middleware/cors.py` — add `validate_cors_origins()` helper

### Implementation

```python
# app.py — replace _CORS_ORIGINS block (~line 309)
_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,https://localhost:8000"
    ).split(",")
    if origin.strip()
]

if _is_production:
    # Block wildcard origins in production
    if "*" in _CORS_ORIGINS:
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS must not contain '*' in production. "
            "Set to your exact domain(s), e.g., CORS_ALLOWED_ORIGINS=https://app.yourdomain.com"
        )
    # Block localhost origins in production
    localhost_origins = [o for o in _CORS_ORIGINS if "localhost" in o or "127.0.0.1" in o]
    if localhost_origins:
        raise RuntimeError(
            f"CORS_ALLOWED_ORIGINS contains localhost origins in production: {localhost_origins}. "
            "Set to your exact production domain(s)."
        )
```

### Testing
- Unit: Set `ENVIRONMENT=production` + `CORS_ALLOWED_ORIGINS=*` — expect `RuntimeError`
- Unit: Set `ENVIRONMENT=production` + `CORS_ALLOWED_ORIGINS=http://localhost:3000` — expect `RuntimeError`
- Unit: Set `ENVIRONMENT=production` + `CORS_ALLOWED_ORIGINS=https://app.example.com` — expect success
- Manual: `curl -H "Origin: https://evil.com" -X OPTIONS /api/health` — verify no `Access-Control-Allow-Origin` in response

### Rollback
Remove the production validation block. Fully reversible; no data changes.

---

## Item 4: Disable OpenAPI Docs in Production

### Current State
`app.py:973-978` creates `FastAPI()` without `docs_url`/`redoc_url`/`openapi_url` gating. Interactive docs are exposed at `/docs` and `/redoc` in all environments.

### Files to Modify
- `app.py` (~line 973) — add conditional URL params to `FastAPI()` constructor

### Implementation

```python
# app.py — replace FastAPI() construction (~line 973)
app = FastAPI(
    title="Risk Module API",
    version="2.0",
    description="Portfolio risk analysis and optimization API",
    lifespan=_lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)
```

### Testing
- Manual (dev): Visit `http://localhost:5001/docs` — should load Swagger UI
- Manual (prod): Set `ENVIRONMENT=production`, visit `/docs` — should return 404
- Unit: Create app with `ENVIRONMENT=production`, assert `app.docs_url is None`

### Rollback
Remove the conditional expressions (revert to no `docs_url`/`redoc_url`/`openapi_url` args). Fully reversible.

---

## Item 5: Error Message Sanitization

### Current State
The security remediation plan (Step 6) addressed auth routes (`routes/auth.py`). However, the problem is far more widespread:

- **`app.py`**: ~27 occurrences of `"message": str(e)` in HTTP error responses (lines 1425, 1571, 1733, 1890, 1984, 2165, 3759, 3821, etc.)
- **`routes/plaid.py`**: 8 occurrences of `detail=str(e)` in `HTTPException`
- **`routes/snaptrade.py`**: 6 occurrences of `detail=str(e)`
- **`routes/admin.py`**: 2 occurrences of `detail=str(e)`
- **`app.py:2145`**: `traceback.format_exc()` logged and full exception type exposed in response at line 2155

Total: ~45 sites where raw exception text reaches the client, potentially exposing file paths, SQL fragments, API keys in error messages, or internal library versions.

### Files to Modify
- `app_platform/middleware/error_handlers.py` — add `sanitize_error_for_client()` utility
- `app.py` — global exception handler that catches unhandled exceptions
- `routes/plaid.py` — replace 8 `detail=str(e)` sites
- `routes/snaptrade.py` — replace 6 `detail=str(e)` sites
- `routes/admin.py` — replace 2 `detail=str(e)` sites
- `routes/auth.py` — verify remediation Step 6 was applied

### Implementation

**Strategy**: Rather than patching 45 individual sites, add a global unhandled-exception handler that sanitizes all 500 responses in production, then progressively fix individual sites.

```python
# app_platform/middleware/error_handlers.py — add function

def sanitize_error_for_client(
    error: Exception,
    *,
    is_production: bool = False,
    generic_message: str = "An internal error occurred. Please try again.",
) -> str:
    """Return error message safe for client consumption."""
    if is_production:
        return generic_message
    return str(error)
```

```python
# app.py — add global exception handler inside create_app()

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log full details server-side
    api_logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    # Return sanitized message to client
    if _is_production:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "message": "An unexpected error occurred. Please try again.",
            },
        )
    # Dev mode: return full details for debugging
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc),
        },
    )
```

For the 18 `detail=str(e)` sites in `routes/`, replace with:
```python
from app_platform.middleware.error_handlers import sanitize_error_for_client

# Before:
raise HTTPException(status_code=500, detail=str(e))

# After:
raise HTTPException(
    status_code=500,
    detail=sanitize_error_for_client(e, is_production=_is_production),
)
```

### Testing
- Unit: Call `sanitize_error_for_client(ValueError("secret SQL"), is_production=True)` — returns generic message
- Unit: Same with `is_production=False` — returns `"secret SQL"`
- Integration: Trigger a 500 error in production mode — verify response body has no stack trace
- Regression: Run `pytest` — existing error-path tests should still pass (dev mode returns details)

### Rollback
Remove global exception handler. Revert `routes/*.py` changes. Fully reversible.

---

## Item 6: Plaid Webhook JWT Signature Verification

### Current State
`routes/plaid.py` has `_validate_plaid_webhook_forward_auth()` (line 192) which checks a shared secret in the `X-Plaid-Forward-Secret` header. This is a custom forwarding-proxy authentication mechanism but does NOT implement Plaid's native JWT webhook verification.

Plaid signs webhooks with a JWT in the `Plaid-Verification` header. The verification key is fetched from Plaid's JWKS endpoint. Without this, any attacker who discovers the webhook URL can forge webhook payloads (the forwarding secret only protects against accidental exposure, not a determined attacker).

Relevant docstring at line 1370-1384 explicitly says: "Should implement Plaid webhook signature verification" and "Should implement signature verification in production."

### Files to Modify
- `routes/plaid.py` — add JWT verification to `plaid_webhook()` handler
- `requirements.txt` — add `pyjwt>=2.8.0` and `jwcrypto>=1.5.0` (or use `plaid-python`'s built-in verification if available)

### Implementation

```python
# routes/plaid.py — add Plaid JWT verification

import jwt
import time
import hashlib
import httpx

_PLAID_JWKS_CACHE: dict = {}
_PLAID_JWKS_CACHE_TTL = 3600  # 1 hour

async def _get_plaid_verification_key(key_id: str) -> dict:
    """Fetch Plaid's JWKS and cache. Plaid rotates keys periodically."""
    now = time.time()
    if _PLAID_JWKS_CACHE.get("keys") and now - _PLAID_JWKS_CACHE.get("fetched_at", 0) < _PLAID_JWKS_CACHE_TTL:
        for key in _PLAID_JWKS_CACHE["keys"]:
            if key.get("kid") == key_id:
                return key

    # Fetch fresh keys
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://production.plaid.com/webhook_verification_key/get",
            json={"client_id": PLAID_CLIENT_ID, "secret": PLAID_SECRET, "key_id": key_id})
        resp.raise_for_status()
        key_data = resp.json().get("key", {})
        if "keys" not in _PLAID_JWKS_CACHE:
            _PLAID_JWKS_CACHE["keys"] = []
        _PLAID_JWKS_CACHE["keys"].append(key_data)
        _PLAID_JWKS_CACHE["fetched_at"] = now
        return key_data


def _verify_plaid_webhook_jwt(body: bytes, plaid_verification_header: str) -> bool:
    """Verify Plaid webhook JWT signature per Plaid docs."""
    if not plaid_verification_header:
        return False

    # Decode header without verification to get key_id
    unverified = jwt.get_unverified_header(plaid_verification_header)
    key_id = unverified.get("kid")
    if not key_id:
        return False

    # Fetch the verification key
    # Note: This is sync for simplicity; consider async in the actual handler
    key_data = ...  # fetched from cache or Plaid API

    # Verify the JWT
    claims = jwt.decode(
        plaid_verification_header,
        key_data,
        algorithms=["ES256"],
        options={"verify_iat": True},
    )

    # Verify the body hash matches
    body_hash = hashlib.sha256(body).hexdigest()
    if claims.get("request_body_sha256") != body_hash:
        return False

    # Verify iat is within 5 minutes
    if abs(time.time() - claims.get("iat", 0)) > 300:
        return False

    return True
```

Modify `plaid_webhook()` handler:
```python
@plaid_router.post("/webhook")
async def plaid_webhook(request: Request):
    body = await request.body()
    plaid_verification = request.headers.get("Plaid-Verification", "")

    # Plaid-native JWT verification (production)
    if _is_production or os.getenv("PLAID_VERIFY_WEBHOOKS", "false").lower() == "true":
        if not await _verify_plaid_webhook_jwt(body, plaid_verification):
            portfolio_logger.warning("Rejecting Plaid webhook: JWT verification failed")
            raise HTTPException(status_code=401, detail="Webhook verification failed")

    # Existing forward-auth check (development/staging proxy)
    _validate_plaid_webhook_forward_auth(request)

    webhook_data = WebhookRequest.model_validate_json(body)
    # ... rest of handler
```

### Testing
- Unit: Mock JWKS response, verify valid JWT passes
- Unit: Verify expired JWT (iat > 5 min) is rejected
- Unit: Verify body hash mismatch is rejected
- Unit: Verify missing `Plaid-Verification` header is rejected in production mode
- Integration: Feature-flag `PLAID_VERIFY_WEBHOOKS=true` in staging, send test webhook from Plaid sandbox

### Rollback
Feature-flagged via `PLAID_VERIFY_WEBHOOKS` env var. Set to `false` to disable. Fully reversible.

---

## Item 7: Pre-Commit Secrets Scanning Hook

### Current State
Implemented via a repo-local pre-commit hook. `.env` is in `.gitignore`, and staged Python/config/text files are now scanned before commit for common credential formats.

### Files to Create/Modify
- `.pre-commit-config.yaml` — NEW file
- `scripts/check_secrets.py` — NEW local scanner used by the hook
- `tests/scripts/test_check_secrets.py` — NEW unit tests for scanner detection, allowlisting, binary skips, and output redaction
- `requirements-dev.txt` — add `pre-commit>=3.7.0`

### Implementation

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: risk-module-secret-scan
        name: Risk module secret scan
        entry: python3 scripts/check_secrets.py
        language: system
        stages: [pre-commit]
```

Setup commands:
```bash
pip install -r requirements-dev.txt
pre-commit install
```

Implementation note: the original detect-secrets baseline approach was avoided because full-tree baseline generation is slow/noisy in this repo and can make routine commits depend on a large allowlist. The local hook has no network install step, no baseline, redacts secret values in output, skips binary/generated artifacts, supports `pre-commit run --all-files`, and supports explicit `allowlist secret` markers for intentional fixtures.

### Testing
- Unit: `pytest tests/scripts/test_check_secrets.py -q`
- Manual: Stage a file containing a realistic fake AWS key — `pre-commit run risk-module-secret-scan` should block commit
- Manual: Stage a normal Python file — `pre-commit run risk-module-secret-scan` should pass cleanly
- CI: `pre-commit run --all-files` can run the local hook without external hook downloads

### Rollback
Delete `.pre-commit-config.yaml`, `scripts/check_secrets.py`, and `tests/scripts/test_check_secrets.py`. Run `pre-commit uninstall`. Fully reversible.

---

## Item 8: Dependency Vulnerability Scan + Pin Secure Versions

### Current State
Completed. A fresh audit on 2026-05-05 found the current Python exposure was limited to `cryptography==46.0.5`:
- CVE-2026-34073, fixed by `cryptography==46.0.6`
- CVE-2026-39892, fixed by `cryptography==46.0.7`

The frontend audit found vulnerable transitive/direct packages in the Vite test/build toolchain:
- `happy-dom==20.8.3`
- `vite==7.3.1`
- `postcss==8.5.6`
- `brace-expansion==5.0.3`
- `picomatch==2.3.1` and `picomatch==4.0.3`
- `lodash==4.17.23`

After the pin and lock refresh, both audits return 0 known vulnerabilities.

### Files to Modify
- `requirements.txt` — pin `cryptography==46.0.7`
- `requirements.lock` — regenerate Python lock hashes for `cryptography==46.0.7`
- `frontend/package.json` — bump direct vulnerable toolchain packages and add transitive overrides
- `frontend/pnpm-lock.yaml` — refresh frontend lockfile

### Implementation

**Python dependency fix**
```bash
pip-audit -r requirements.txt --format=json
uv pip compile requirements.txt --generate-hashes \
  --upgrade-package cryptography \
  --output-file requirements.lock
```

`requirements.txt` now pins `cryptography==46.0.7`, the smallest available patch release that fixes both audit findings without a broader major-version jump.

**Frontend dependency fix**
```bash
cd frontend
pnpm audit --json
pnpm install --lockfile-only
```

`frontend/package.json` now bumps `happy-dom`, `vite`, `postcss`, `tailwindcss`, and `@typescript-eslint/*`. It also adds `pnpm.overrides` for vulnerable transitive `brace-expansion`, `picomatch@2`, `picomatch@4`, and `lodash`.

### Testing
- `pip-audit -r requirements.txt --format=json` — returns no known vulnerabilities
- `cd frontend && pnpm audit --json` — returns 0 vulnerabilities
- `python3 -m pip install --dry-run -r requirements.txt` — dependency set resolves
- `cd frontend && pnpm test -- --run` — frontend tests pass
- `pre-commit run risk-module-secret-scan --all-files` — no newly introduced secrets

### Rollback
Pin `cryptography` back to the previous version in `requirements.txt`, regenerate `requirements.lock`, revert the frontend package pins/overrides, and run `pnpm install --lockfile-only`.

---

## Item 9: PII Audit of Log Statements + Redaction

### Current State
Production auth/Kartra email log exposure is remediated. Grep analysis originally found the following PII exposure patterns:

1. **`routes/auth.py`** (lines 522, 638, 831, 883): `log_auth_event()` receives `user_email` param and passes it to structured log output. **Fixed at the wrapper:** `log_auth_event()` now redacts `user_email` centrally, so the auth routes can continue passing the original request context without emitting raw addresses.

2. **`app.py`** (lines 874, 877): Kartra webhook push logs raw `email` in print statements:
   ```python
   print(f"Delayed Kartra push for {email}")
   print(f"Error in Kartra push for {email}: {str(e)}")
   ```

3. **`utils/logging.py`** (line 467): `log_auth_event()` accepts `user_email` parameter and includes it in log payload. **Fixed:** `redact_email()` masks addresses before structured logging.

4. **`routes/plaid.py`**: Logs `item_id` values (lines 369, 380, 384, etc.) which are opaque Plaid identifiers (not directly PII, but could be used for correlation). Left unchanged in this slice because provider webhook files were under active concurrent edits; this is lower-risk than raw email logging.

5. **`scripts/*.py`**: Various print statements with user emails (diagnostic scripts, not production code paths).

### Files to Modify
- `utils/logging.py` — add email redaction helper, apply in `log_auth_event()`
- `app.py` — replace Kartra print statements with redacted logger calls
- `tests/api/test_logging.py` — cover email redaction and auth-event payloads

### Implementation

```python
# utils/logging.py — add redaction utility

def redact_email(email: str | None) -> str:
    """Redact email for logging: 'user@example.com' -> 'us***@e***.com'"""
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    redacted_local = local[:2] + "***" if len(local) > 2 else "***"
    domain_parts = domain.split(".")
    redacted_domain = domain_parts[0][:1] + "***" if domain_parts else "***"
    tld = "." + domain_parts[-1] if len(domain_parts) > 1 else ""
    return f"{redacted_local}@{redacted_domain}{tld}"
```

Apply to `log_auth_event()`:
```python
def log_auth_event(
    user_id: int,
    event_type: str,
    provider: str | None = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    return log_event(
        "auth_event",
        event_type,
        user_id=user_id,
        provider=provider,
        success=success,
        user_email=redact_email(user_email),  # Redact before logging
        details=details or {},
    )
```

Fix Kartra print statements in `app.py`:
```python
# Before:
print(f"Delayed Kartra push for {email}")
# After:
api_logger.info("Delayed Kartra push for user_id=%s", user.get("user_id"))
```

### Testing
- Unit: `redact_email("alice@example.com")` -> `"al***@e***.com"`
- Unit: `redact_email(None)` -> `"***"`
- Unit: `log_auth_event(..., user_email="alice@example.com")` returns a payload with only the redacted address
- Manual: Trigger login, inspect server logs — no raw emails visible

### Rollback
Revert `utils/logging.py` changes. Fully reversible; no data migration.

---

## Item 10: Duplicate MCP Tool Registration Audit

### Current State
`mcp_server.py` registers 75 `@mcp.tool()` decorated functions. Each function is a thin wrapper that delegates to an imported implementation from `mcp_tools/*.py`. The tool names are derived from function names.

Current tool count by module:
- Portfolio management: 7 (list_accounts, list_portfolios, create_portfolio, update_portfolio_accounts, delete_portfolio, account_deactivate, account_activate)
- Positions: 2 (get_positions, export_holdings)
- Import: 2 (import_portfolio, import_transaction_file)
- Risk: 5 (get_risk_score, get_risk_analysis, get_leverage_capacity, set_risk_profile, get_risk_profile)
- Allocation: 2 (set_target_allocation, get_target_allocation)
- Audit: 3 (record_workflow_action, update_action_status, get_action_history)
- Config: 2 (manage_instrument_config, manage_ticker_config)
- Performance: 1 (get_performance)
- Trading analysis: 1 (get_trading_analysis)
- Transactions: 8 (ingest, list, batches, inspect, flows, income, refresh, coverage)
- Options: 2 (analyze_option_strategy, analyze_option_chain)
- Futures: 1 (get_futures_curve)
- Stock: 1 (analyze_stock)
- Optimization: 2 (run_optimization, get_efficient_frontier)
- What-if: 1 (run_whatif)
- Backtest: 1 (run_backtest)
- Compare: 1 (compare_scenarios)
- Factors: 2 (get_factor_analysis, get_factor_recommendations)
- Income: 1 (get_income_projection)
- News/events: 2 (get_portfolio_news, get_portfolio_events_calendar)
- Tax: 1 (suggest_tax_loss_harvest)
- Baskets: 9 (create, list, get, analyze, update, delete, create_from_etf, preview_trade, execute_trade)
- Rebalance: 1 (preview_rebalance_trades)
- Trading: 5 (preview_trade, get_quote, execute_trade, get_orders, cancel_order)
- Futures roll: 2 (preview_futures_roll, execute_futures_roll)
- Multi-leg options: 2 (preview_option_trade, execute_option_trade)
- Signals: 1 (check_exit_signals)
- Hedge: 1 (monitor_hedge_positions)
- Normalizer: 5 (sample_csv, stage, test, activate, list)
- Context: 1 (get_mcp_context)
- **Total: 75 tools**

### Approach
Implemented an AST-based test that verifies each MCP server has unique tool names, including both decorator-style registrations in `mcp_server.py` and direct callable registrations in `mcp_server_research.py`.

### Files to Modify/Create
- `tests/test_mcp_tool_registry.py` — NEW test file

### Implementation

```python
def test_mcp_tool_registrations_have_unique_names_per_server() -> None:
    ...


def test_mcp_tool_registration_counts_stay_in_expected_ranges() -> None:
    ...
```

### Testing
- `pytest tests/test_mcp_tool_registry.py -q` — both tests pass
- If a duplicate is found, the test output names the offending function

### Rollback
Delete the test file. No production code changes.

---

## Parallelization Map

```
                    ┌─────────────────────────────────┐
                    │  P0: Can run in parallel         │
                    ├─────────────────────────────────┤
                    │ Item 4: OpenAPI docs (15min)     │
Commit 1 ──────────│ Item 5: Error sanitization (2h)  │
                    │ Item 3: CORS lockdown (30min)    │
                    └─────────────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────────┐
                    │  P1: Can run in parallel         │
                    ├─────────────────────────────────┤
Commit 2 ──────────│ Item 2: Security headers (1h)    │
                    │ Item 1: CSRF middleware (2h)     │
                    │ Item 8: Dep scan + pin (2h)      │
                    └─────────────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────────┐
                    │  P2: Can run in parallel         │
                    ├─────────────────────────────────┤
Commit 3 ──────────│ Item 6: Plaid JWT verify (2h)    │
                    │ Item 9: PII log redaction (1.5h) │
                    └─────────────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────────┐
                    │  P3: Can run in parallel         │
                    ├─────────────────────────────────┤
Commit 4 ──────────│ Item 7: Pre-commit hook (30min)  │
                    │ Item 10: MCP tool audit (1h)     │
                    └─────────────────────────────────┘
```

Items within the same commit/priority tier touch different files and can be developed in parallel. Items across tiers should be committed sequentially because:
- P0 fixes the highest-risk exposure; validate before adding middleware layers
- P1 middleware additions may interact (CSRF + security headers + new deps)
- P2 items are independent but should land after core hardening is stable
- P3 items are tooling/hygiene and have zero production runtime impact

---

## Verification Checklist

| # | Item | Verification Command / Check |
|---|------|------------------------------|
| 1 | CSRF protection | `pytest tests/app_platform/test_csrf_middleware.py` passes; `curl -X POST /api/portfolios -H "Cookie: session_id=..." -d '{}'` returns 403 without `X-CSRF-Token` |
| 2 | Security headers | `curl -I /api/health` shows X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy |
| 3 | CORS lockdown | `ENVIRONMENT=production CORS_ALLOWED_ORIGINS=* python -c "import app"` crashes with RuntimeError |
| 4 | OpenAPI disabled | `ENVIRONMENT=production`; `curl /docs` returns 404 |
| 5 | Error sanitization | Trigger 500 in prod mode; response body has no traceback or exception class name |
| 6 | Plaid webhook JWT | Send unsigned POST to `/plaid/webhook` with `PLAID_VERIFY_WEBHOOKS=true` — returns 401 |
| 7 | Pre-commit secrets | Stage a file with `AKIA` + 16 uppercase/digit characters; `pre-commit run risk-module-secret-scan` blocks it |
| 8 | Dep scan clean | `pip-audit` returns 0 critical/high; `pnpm audit` returns 0 critical |
| 9 | PII redacted | Login, check server logs — email appears as `al***@e***.com`, not `alice@example.com` |
| 10 | No duplicate tools | `pytest tests/test_mcp_tool_registry.py` passes |

---

## Rollback Safety Summary

| Item | Reversible? | Data Changes? | Notes |
|------|-------------|---------------|-------|
| 1. CSRF | Yes | None | Remove middleware line |
| 2. Security headers | Yes | None | Remove middleware line |
| 3. CORS lockdown | Yes | None | Remove validation block |
| 4. OpenAPI docs | Yes | None | Remove conditional args |
| 5. Error sanitization | Yes | None | Remove global handler + revert route changes |
| 6. Plaid JWT | Yes | None | Feature-flagged; set `PLAID_VERIFY_WEBHOOKS=false` |
| 7. Pre-commit hook | Yes | None | Delete config + `pre-commit uninstall` |
| 8. Dep versions | Yes | None | Pin back to old versions |
| 9. PII redaction | Yes | None | Revert `utils/logging.py` |
| 10. MCP audit | Yes | None | Delete test file (test-only change) |

All 10 items are fully reversible with no database migrations or data changes.
