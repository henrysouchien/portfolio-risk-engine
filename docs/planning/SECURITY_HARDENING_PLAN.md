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
| CSRF protection | NOT DONE |
| Security headers middleware | NOT DONE |
| Production CORS origin lockdown | NOT DONE (reads `CORS_ALLOWED_ORIGINS` env, defaults to localhost) |
| OpenAPI docs disabled in prod | NOT DONE (`FastAPI()` has no `docs_url` gating) |
| Error message sanitization | PARTIALLY DONE (auth routes only, per remediation Step 6) |
| Plaid webhook JWT verification | NOT DONE (uses forward-auth shared secret only) |
| Pre-commit secrets scanning | NOT DONE (no `.pre-commit-config.yaml` exists) |
| Dependency vulnerability scan | PARTIALLY DONE (audit identified 47 Python + 8 Node CVEs; some upgraded) |
| PII audit of logs | NOT DONE |
| MCP tool duplicate audit | NOT DONE |

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
No CSRF protection. Session cookies use `SameSite=lax` and `httponly=True`, which mitigates simple CSRF but does not prevent all vectors (e.g., top-level cross-site POST via form submission in older browsers).

### Files to Modify
- `requirements.txt` — add `fastapi-csrf-protect>=0.3.0`
- `app.py` — add CSRF middleware configuration in `create_app()` (~line 973)
- `app.py` — add CSRF dependency to state-changing route handlers
- `routes/auth.py` — exempt OAuth callback (cross-origin by design)
- `routes/plaid.py` — exempt webhook endpoint (machine-to-machine)
- `routes/snaptrade.py` — exempt webhook endpoint
- `frontend/packages/chassis/src/services/HttpClient.ts` (or `app-platform` `HttpClient.ts`) — send `X-CSRF-Token` header on mutating requests

### Implementation

```python
# app.py — inside create_app()
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError

@CsrfProtect.load_config
def get_csrf_config():
    return {
        "secret_key": resolve_session_secret(
            environment="production" if _is_production else "development"
        ),
        "cookie_samesite": "lax",
        "cookie_secure": _is_production,
        "token_location": "header",
        "header_name": "X-CSRF-Token",
    }

# Add endpoint to serve CSRF token
@app.get("/api/csrf-token")
async def get_csrf_token(csrf_protect: CsrfProtect = Depends()):
    token, signed = csrf_protect.generate_csrf_tokens()
    response = JSONResponse({"csrf_token": token})
    csrf_protect.set_csrf_cookie(signed, response)
    return response
```

State-changing endpoints that need CSRF validation (add `csrf_protect: CsrfProtect = Depends()` + `await csrf_protect.validate_csrf(request)`):
- `POST /api/portfolios` (create)
- `PUT /api/portfolios/{name}` (update)
- `PATCH /api/portfolios/{name}` (partial update)
- `DELETE /api/portfolios/{name}` (delete)
- `POST /api/risk-settings` (update risk settings)
- `POST /auth/logout` (logout)
- `POST /api/expected-returns` (update expected returns)
- All `/api/trading/*` endpoints (trade execution)

Endpoints to EXEMPT from CSRF:
- `POST /auth/google` — OAuth flow, no prior session
- `POST /plaid/webhook` — machine-to-machine
- `POST /snaptrade/webhook` — machine-to-machine
- `POST /api/frontend/log` — fire-and-forget logging

### Testing
- Unit: Mock CSRF token flow — verify 403 when missing, 200 when valid
- Manual: Use browser devtools to confirm `X-CSRF-Token` header sent on POST/PUT/DELETE
- Negative: Submit POST from a different origin without token — expect 403

### Rollback
Remove middleware addition from `create_app()`. No database changes. Fully reversible.

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
No `.pre-commit-config.yaml` exists. `.env` is in `.gitignore` (confirmed), but there is no automated scanning for accidentally committed secrets in Python/config files.

### Files to Create/Modify
- `.pre-commit-config.yaml` — NEW file
- `requirements.txt` — add `pre-commit>=3.7.0` to dev dependencies (or separate `requirements-dev.txt`)
- `.secrets.baseline` — NEW file (detect-secrets baseline)

### Implementation

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
        exclude: >
          (?x)^(
            .*\.lock|
            .*-lock\.json|
            frontend/openapi-schema\.json|
            .*\.min\.js
          )$

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-added-large-files
        args: ['--maxkb=500']
      - id: check-merge-conflict
      - id: detect-private-key
```

Setup commands:
```bash
pip install pre-commit detect-secrets
detect-secrets scan --exclude-files '\.lock|lock\.json|openapi-schema\.json' > .secrets.baseline
# Review baseline — verify no real secrets; only false positives
pre-commit install
```

### Testing
- Manual: Stage a file containing `AKIA...` (fake AWS key) — `pre-commit` should block commit
- Manual: Stage a normal Python file — should pass cleanly
- CI: `pre-commit run --all-files` in CI pipeline

### Rollback
Delete `.pre-commit-config.yaml` and `.secrets.baseline`. Run `pre-commit uninstall`. Fully reversible.

---

## Item 8: Dependency Vulnerability Scan + Pin Secure Versions

### Current State
Security audit (2026-03-12) identified 47 Python CVEs across 23 packages and 8 Node.js vulnerabilities. `requirements.txt` uses `>=` minimum version pins. Some packages may have been upgraded since the audit, but no systematic scan has been re-run.

Key vulnerable packages from audit:
- **Web stack**: werkzeug (3 CVEs), flask (2 CVEs), jinja2 (1 CVE)
- **Auth/crypto**: cryptography (2 CVEs), authlib (1 CVE)
- **HTTP**: aiohttp (9 CVEs), urllib3 (3 CVEs), h11 (1 CVE)
- **FastAPI**: python-multipart (1 CVE)

### Files to Modify
- `requirements.txt` — bump minimum version pins for vulnerable packages
- `frontend/package.json` — bump `happy-dom` (critical RCE in <20.0.0)

### Implementation

**Step 1: Python audit + upgrade**
```bash
pip install pip-audit
pip-audit --format=json > /tmp/pip-audit-results.json
# Review results, then upgrade:
pip install --upgrade werkzeug flask jinja2 cryptography authlib \
    python-multipart aiohttp h11 urllib3 pypdf protobuf pyasn1
pip-audit  # Verify reduction
pytest     # Regression check
```

**Step 2: Update `requirements.txt` minimum pins** to at least the fixed versions:
```
# Bump these to fixed versions (exact values from pip-audit):
# cryptography>=46.0.5 (was >=43.0.3)
# Add: python-multipart>=0.0.22
```

**Step 3: Node audit + upgrade**
```bash
cd frontend
pnpm audit
# Edit package.json: "happy-dom": "^20.0.0" (was 17.6.1)
pnpm install
pnpm test  # Regression check
```

**Step 4: Add CI check** (recommended but out-of-scope for this plan)

### Testing
- `pip-audit` — expect 0 critical/high vulnerabilities
- `pnpm audit` — expect 0 critical vulnerabilities
- `pytest` — full test suite passes
- `cd frontend && pnpm test` — frontend tests pass

### Rollback
Pin back to previous versions in `requirements.txt`. `pip install -r requirements.txt` to downgrade.

---

## Item 9: PII Audit of Log Statements + Redaction

### Current State
Grep analysis reveals the following PII exposure patterns:

1. **`routes/auth.py`** (lines 522, 638, 831, 883): `log_auth_event()` receives `user_email` param and passes it to structured log output. Emails are logged in auth success events.

2. **`app.py`** (lines 874, 877): Kartra webhook push logs raw `email` in print statements:
   ```python
   print(f"Delayed Kartra push for {email}")
   print(f"Error in Kartra push for {email}: {str(e)}")
   ```

3. **`utils/logging.py`** (line 467): `log_auth_event()` accepts `user_email` parameter and includes it in log payload.

4. **`routes/plaid.py`**: Logs `item_id` values (lines 369, 380, 384, etc.) which are opaque Plaid identifiers (not directly PII, but could be used for correlation).

5. **`scripts/*.py`**: Various print statements with user emails (diagnostic scripts, not production code paths).

### Files to Modify
- `utils/logging.py` — add email redaction helper, apply in `log_auth_event()`
- `routes/auth.py` — redact email before passing to `log_auth_event()`
- `app.py` — replace Kartra print statements with redacted logger calls

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
- Grep verification: After changes, `grep -rn 'email' routes/auth.py | grep log` shows only redacted emails
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
- Import: 2 (import_portfolio, import_transactions)
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
- Rebalance: 1 (generate_rebalance_trades)
- Trading: 5 (preview_trade, get_quote, execute_trade, get_orders, cancel_order)
- Futures roll: 2 (preview_futures_roll, execute_futures_roll)
- Multi-leg options: 2 (preview_option_trade, execute_option_trade)
- Signals: 1 (check_exit_signals)
- Hedge: 1 (monitor_hedge_positions)
- Normalizer: 5 (sample_csv, stage, test, activate, list)
- Context: 1 (get_mcp_context)
- **Total: 75 tools**

### Approach
Write a script to verify no duplicate tool names exist, then codify as a test.

### Files to Modify/Create
- `tests/test_mcp_tool_registry.py` — NEW test file

### Implementation

```python
# tests/test_mcp_tool_registry.py
"""Verify MCP tool registration integrity."""

import ast
import re
from pathlib import Path


def test_no_duplicate_mcp_tool_names():
    """Ensure no two @mcp.tool() functions share the same name."""
    mcp_server_path = Path(__file__).resolve().parents[1] / "mcp_server.py"
    source = mcp_server_path.read_text()
    tree = ast.parse(source)

    tool_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check if decorated with @mcp.tool()
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "tool"):
                    tool_names.append(node.name)

    duplicates = [name for name in tool_names if tool_names.count(name) > 1]
    assert not duplicates, f"Duplicate MCP tool names: {set(duplicates)}"
    # Sanity check: we expect 75 tools
    assert len(tool_names) >= 70, f"Expected ~75 tools, found {len(tool_names)}"


def test_all_tool_functions_delegate():
    """Verify each tool function delegates to an imported implementation."""
    mcp_server_path = Path(__file__).resolve().parents[1] / "mcp_server.py"
    source = mcp_server_path.read_text()

    # Find all import aliases (pattern: from mcp_tools.X import Y as _Y)
    import_pattern = re.compile(r"from mcp_tools\.\w+ import \w+ as (_\w+)")
    imported_impls = set(import_pattern.findall(source))

    # Each tool function body should reference one of these
    assert len(imported_impls) > 60, (
        f"Expected 60+ imported implementations, found {len(imported_impls)}"
    )
```

### Testing
- `pytest tests/test_mcp_tool_registry.py -v` — both tests pass
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
| 1 | CSRF protection | `curl -X POST /api/portfolios -H "Cookie: session=..." -d '{}' ` returns 403 (no CSRF token) |
| 2 | Security headers | `curl -I /api/health` shows X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy |
| 3 | CORS lockdown | `ENVIRONMENT=production CORS_ALLOWED_ORIGINS=* python -c "import app"` crashes with RuntimeError |
| 4 | OpenAPI disabled | `ENVIRONMENT=production`; `curl /docs` returns 404 |
| 5 | Error sanitization | Trigger 500 in prod mode; response body has no traceback or exception class name |
| 6 | Plaid webhook JWT | Send unsigned POST to `/plaid/webhook` with `PLAID_VERIFY_WEBHOOKS=true` — returns 401 |
| 7 | Pre-commit secrets | `echo "AKIA1234567890" > test.txt && git add test.txt && git commit` — blocked by detect-secrets |
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
