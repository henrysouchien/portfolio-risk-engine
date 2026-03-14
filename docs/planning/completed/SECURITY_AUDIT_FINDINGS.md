# Security Audit Findings

**Date**: 2026-03-12
**Scope**: Phase 3H of PUBLISH_PLAN.md — 14-item checklist from MULTI_USER_DEPLOYMENT_PLAN.md
**Status**: Read-only investigation. No fixes applied.

---

## Executive Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 3 |
| HIGH     | 4 |
| MEDIUM   | 7 |
| LOW      | 4 |

**Top risks**: Hardcoded default session secret, overly permissive CORS methods/headers, conditional admin auth on `/auth/cleanup`, no rate limiting on auth endpoints, and 47 Python + 8 Node dependency vulnerabilities.

---

## A. Security Checklist (MULTI_USER_DEPLOYMENT_PLAN.md)

### 1. `FLASK_SECRET_KEY` is cryptographically random (not the default)

**Status**: FAIL (CRITICAL)

`app_platform/middleware/sessions.py:9` defines:
```python
DEFAULT_SESSION_SECRET = "dev-secret-key-change-in-production"
```

`app.py:996` uses:
```python
secret_key=os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")
```

If `FLASK_SECRET_KEY` is not set, the app runs with a publicly known secret. Session cookies can be forged.

**Action**: Require `FLASK_SECRET_KEY` at startup (crash if missing in production).

---

### 2. `.env` file is `chmod 600` (owner-read only)

**Status**: PASS (local)

`.env` is in `.gitignore` and not tracked by git. Permissions are a deployment concern.

---

### 3. RDS security group: inbound 5432 only from EC2 security group

**Status**: NOT AUDITABLE (AWS config, outside codebase)

---

### 4. EC2 security group: inbound 80/443 only (no 5001 exposed)

**Status**: NOT AUDITABLE (AWS config, outside codebase)

---

### 5. `ADMIN_TOKEN` is set and strong

**Status**: PARTIAL

`routes/admin.py:231-272` — `require_admin_token` dependency reads `X-Admin-Token` header and compares to env var. Good: moved from query-param to header-based auth. Bad: no rate limiting (see finding B.3).

---

### 6. Google OAuth authorized JavaScript origins are exact-match (no wildcards)

**Status**: NOT AUDITABLE (Google Cloud Console config, outside codebase)

Code correctly reads `GOOGLE_CLIENT_ID` from env. `app_platform/auth/google.py` delegates to `google.oauth2.id_token.verify_oauth2_token()` which validates issuer and audience.

---

### 7. `ENVIRONMENT=production` (enables secure cookies, disables dev features)

**Status**: PASS (code-level)

`routes/auth.py:448-455`:
```python
secure=os.getenv("ENVIRONMENT", "development") == "production"
```
Cookie `httponly=True`, `samesite='lax'`, `secure` gated on production. See finding B.5 for SameSite discussion.

---

### 8. No `.env` file in git

**Status**: PASS

`.env` is in `.gitignore` line 8. `git ls-files --error-unmatch .env` confirms not tracked. However, `.env` exists locally with real credentials — see finding C.1 for hardcoded-secrets context.

---

### 9. SSH key-only access to EC2 (no password auth)

**Status**: NOT AUDITABLE (server config, outside codebase)

---

### 10. AWS credentials: Use EC2 instance profile instead of IAM keys in `.env`

**Status**: DEPLOYMENT CONCERN

Local `.env` has `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. For production EC2, use instance profiles instead. No code changes needed — just don't set these env vars in production.

---

### 11. FMP data DB: Use read-only user not `estimateadmin`

**Status**: NOT AUDITABLE (DB user config, outside codebase)

Code uses `DATABASE_URL` env var — user is configured there.

---

### 12. Admin endpoints: query-param auth leaks tokens in logs

**Status**: FIXED

`routes/admin.py` now uses `X-Admin-Token` header via `require_admin_token` FastAPI dependency. No query-param fallback on admin routes.

**Exception**: `routes/auth.py:633-638` — `/auth/cleanup` still accepts both header AND query param:
```python
provided = request.headers.get("X-Admin-Token") or request.query_params.get("admin_token")
```
This endpoint also has conditional auth — see finding B.2.

---

### 13. Unauthenticated endpoints: `/generate_key` and `/auth/cleanup`

**Status**: PARTIAL FIX

- `/generate_key` (`routes/admin.py:274`): Now has `Depends(require_admin_token)`. FIXED.
- `/auth/cleanup` (`routes/auth.py:562`): Auth is **conditional** — if `ADMIN_TOKEN` env var is not set, endpoint is completely open. STILL VULNERABLE.

---

### 14. Session cookie `secure=True`

**Status**: PASS (in production)

Set when `ENVIRONMENT=production`. See checklist item 7.

---

## B. Application Security Findings

### B.1. Overly Permissive CORS (HIGH)

**File**: `app.py:986-990`

```python
allow_methods=["*"],
allow_headers=["*"],
```

Default origins are `localhost:3000,localhost:8000` (safe), but methods/headers should be restricted to actual usage: `["GET", "POST", "PUT", "DELETE", "OPTIONS"]` for methods, and an explicit header whitelist.

**Risk**: Allows TRACE/CONNECT methods; combined with `allow_credentials=True` widens CSRF surface.

---

### B.2. Conditional Admin Auth on `/auth/cleanup` (HIGH)

**File**: `routes/auth.py:633-638`

```python
admin_token = os.getenv("ADMIN_TOKEN")
if admin_token:
    provided = request.headers.get("X-Admin-Token") or request.query_params.get("admin_token")
    if provided != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
```

If `ADMIN_TOKEN` is unset, no auth check runs. This is a "fail-open" pattern.

**Risk**: Unauthorized session cleanup; potential DoS via repeated cleanup triggers.

---

### B.3. No Rate Limiting on Auth/Admin Endpoints (HIGH)

**Files**: `routes/admin.py`, `routes/auth.py`

No rate limiting on:
- `POST /auth/google` (login)
- `POST /auth/refresh` (token refresh)
- `POST /generate_key` (API key generation)
- `POST /auth/cleanup` (session cleanup)
- All `/admin/*` endpoints

**Risk**: Brute-force attacks on admin token, credential stuffing on login.

---

### B.4. API Keys in Query Parameters (MEDIUM)

**File**: `app.py:1087-1090`

```python
def get_api_key(request: Request) -> str:
    return request.query_params.get("key", PUBLIC_KEY)
```

Query params appear in server access logs, proxy logs, referer headers, browser history.

**Action**: Accept via `Authorization` or `X-API-Key` header instead.

---

### B.5. SameSite=lax on Session Cookies (MEDIUM)

**Files**: `app.py:997`, `routes/auth.py:454`

`samesite='lax'` allows cookies on cross-site top-level GET navigations. `strict` would be more secure but may break OAuth redirect flows. Consider adding CSRF tokens if keeping `lax`.

---

### B.6. Error Messages Expose Exception Details (MEDIUM)

**File**: `routes/auth.py:435,471,560,650`

```python
raise HTTPException(status_code=401, detail=f"Token verification failed: {error}")
```

Internal exception messages returned to client. Use generic messages in production.

---

### B.7. Admin Docs Conflict with Implementation (LOW)

**File**: `routes/admin.py:287-288`

`/generate_key` docstring says "No authentication required (webhook endpoint)" but code requires admin token. Misleading for maintainers.

---

## C. Hardcoded Secrets & Paths

### C.1. Local `.env` Contains Real Credentials (INFO — not in git)

`.env` is gitignored and not tracked. Contains real keys for: OpenAI, FMP, Plaid (production), AWS IAM, Google OAuth, Anthropic, IBKR Flex, Schwab, SnapTrade, EDGAR.

**Not a code vulnerability** since file is not committed, but:
- No `.env.example` template exists for safe onboarding
- If repo were ever made public or `.gitignore` removed, all credentials would leak
- Consider a pre-commit hook (e.g., `detect-secrets`) as a guardrail

---

### C.2. Hardcoded User Paths (LOW)

Several files contain `/Users/henrychien/...` paths:
- `mcp_server.py:9` — docstring comment
- `fmp/server.py:9` — docstring comment
- `fmp/examples/fcf_analysis.py:12` — `sys.path.insert()`
- `fmp/examples/treasury_yield_analysis.py:11` — `sys.path.insert()`
- `scripts/explore_transactions.py:272` — hardcoded output dir

Not exploitable but breaks portability.

---

## D. Dependency Vulnerabilities

### D.1. Python — pip audit (47 vulnerabilities, 23 packages)

| Package | Version | Vulns | Fix Available |
|---------|---------|-------|---------------|
| **aiohttp** | 3.12.13 | 9 CVEs | 3.12.14, 3.13.3 |
| **authlib** | 1.6.6 | 1 CVE | 1.6.7 |
| **cryptography** | 43.0.3 | 2 CVEs | 44.0.1, 46.0.5 |
| **diskcache** | 5.6.3 | 1 CVE | No fix yet |
| **flask** | 3.1.0 | 2 CVEs | 3.1.1, 3.1.3 |
| **fonttools** | 4.56.0 | 1 CVE | 4.60.2 |
| **h11** | 0.14.0 | 1 CVE | 0.16.0 |
| **jinja2** | 3.1.5 | 1 CVE | 3.1.6 |
| **jupyter-core** | 5.7.2 | 1 CVE | 5.8.1 |
| **marshmallow** | 4.0.0 | 1 CVE | 3.26.2, 4.1.2 |
| **nbconvert** | 7.16.6 | 1 CVE | 7.17.0 |
| **pdfminer-six** | 20250327 | 2 CVEs | 20251107, 20251230 |
| **pillow** | 11.1.0 | 1 CVE | 12.1.1 |
| **pip** | 25.1.1 | 2 CVEs | 25.3, 26.0 |
| **protobuf** | 6.30.2 | 2 CVEs | 6.31.1, 6.33.5 |
| **pyasn1** | 0.6.1 | 1 CVE | 0.6.2 |
| **pypdf** | 6.7.0 | 7 CVEs | 6.7.1–6.7.5 |
| **python-multipart** | 0.0.20 | 1 CVE | 0.0.22 |
| **setuptools** | 75.8.0 | 1 PYSEC | 78.1.1 |
| **tornado** | 6.4.2 | 1 CVE | 6.5 |
| **urllib3** | 2.5.0 | 3 CVEs | 2.6.0, 2.6.3 |
| **werkzeug** | 3.1.3 | 3 CVEs | 3.1.4–3.1.6 |
| **yt-dlp** | 2025.5.22 | 1 CVE | 2026.2.21 |

**Priority upgrades**: werkzeug, flask, jinja2 (web stack), cryptography, authlib (auth stack), python-multipart (FastAPI uploads), aiohttp (async HTTP).

### D.2. Node.js — pnpm audit (8 vulnerabilities)

| Severity | Package | Issue | Fix |
|----------|---------|-------|-----|
| **CRITICAL** | happy-dom <20.0.0 | VM Context Escape (RCE) | >=20.0.0 |
| **HIGH** | minimatch (multiple) | ReDoS (4 advisories) | >=5.1.8, >=10.2.3 |
| **HIGH** | minimatch <3.1.4 | ReDoS | >=3.1.4 |
| **MODERATE** | js-yaml >=4.0.0 <4.1.1 | Prototype pollution | >=4.1.1 |

All are **dev dependencies** (test runner, linting, codegen). No production runtime exposure. happy-dom RCE is most urgent since it's the test runner (vitest).

---

## E. Checklist Summary

| # | Item | Status |
|---|------|--------|
| 1 | FLASK_SECRET_KEY random | FAIL — hardcoded default |
| 2 | .env chmod 600 | PASS (local) |
| 3 | RDS security group | N/A (AWS config) |
| 4 | EC2 security group | N/A (AWS config) |
| 5 | ADMIN_TOKEN set and strong | PARTIAL — no rate limiting |
| 6 | Google OAuth origins exact-match | N/A (Google Console) |
| 7 | ENVIRONMENT=production | PASS |
| 8 | No .env in git | PASS |
| 9 | SSH key-only | N/A (server config) |
| 10 | AWS instance profile | DEPLOYMENT |
| 11 | FMP read-only DB user | N/A (DB config) |
| 12 | Admin endpoints: no query-param auth | FIXED (except /auth/cleanup) |
| 13 | Unauthenticated endpoints | PARTIAL — /auth/cleanup fail-open |
| 14 | Session cookie secure=True | PASS |

---

## F. Recommended Fix Priority

### Immediate (before any public deployment)
1. **Require** `FLASK_SECRET_KEY` at startup — crash if missing when `ENVIRONMENT=production`
2. **Fix** `/auth/cleanup` fail-open auth — use `require_admin_token` dependency
3. **Restrict** CORS methods/headers to explicit whitelist
4. **Upgrade** werkzeug, flask, jinja2, cryptography, authlib, python-multipart

### High (before multi-user)
5. **Add rate limiting** on auth + admin endpoints (e.g., `slowapi`)
6. **Move** API key acceptance from query param to header
7. **Remove** query-param fallback from `/auth/cleanup`
8. **Upgrade** happy-dom (dev dep, but RCE in test env)

### Medium (hardening)
9. Add CSRF tokens or switch to `SameSite=strict`
10. Genericize error messages in production
11. Create `.env.example` template
12. Add `detect-secrets` pre-commit hook
13. Upgrade remaining pip-audit findings (aiohttp, pypdf, urllib3, etc.)

### Low (cleanup)
14. Fix admin docstring for `/generate_key`
15. Remove hardcoded user paths from examples
16. Upgrade minimatch/js-yaml dev deps
