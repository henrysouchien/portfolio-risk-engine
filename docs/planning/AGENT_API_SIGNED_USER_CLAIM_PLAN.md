# Agent API Multi-User — Gateway-Signed User Claim

**Status**: ✅ **Codex R5 PASS** (2026-04-22) — plan is implementable. 5 review rounds (R1 FAIL → R2 FAIL → R3 FAIL → R4 FAIL → R5 PASS). v5 + R5 cleanups applied. See §11 change log.
**Date**: 2026-04-22
**Predecessor**: `docs/planning/completed/AGENT_CODE_EXECUTION_REGISTRY_PLAN.md` Phase 1 (shipped). Phase 3 (DB-backed keys) was the original multi-user proposal — superseded by this plan per `feedback_capability_not_workflow_gate.md`-aligned reasoning: the gateway already has HMAC-signed user identity infrastructure; reuse it instead of building parallel DB-backed key management.

---

## 1. Goal

Replace the single static `AGENT_API_KEY` bearer auth on `/api/agent/call` with a **gateway-signed user claim** carried through the sandbox environment. After this ships, each sandbox spawn carries proof of which user it's acting for, verified cryptographically at the agent API.

**Multi-user unification**: the gateway already knows `session.user_id` (multi-user shipped 2026-04-17). This plan carries that identity through the sandbox → risk_module HTTP boundary using the same HMAC-SHA256 pattern the gateway's existing internal resolver uses (`routes/internal_resolver.py`).

---

## 2. Non-goals

- **No gateway rearchitecture.** The gateway's Claude-API traffic path is untouched. This plan adds a *sandbox-bound signed claim* to the existing gateway responsibilities.
- **No DB table for keys.** The original Phase 3 plan proposed `agent_api_keys` with per-user hashed tokens. This plan doesn't create one — signed claims + HMAC rotation handle revocation.
- **No new runtime dependency.** Uses stdlib `hmac` + `hashlib` + `secrets` like the existing resolver. No JWT library.
- **No changes to the 33 allowlisted registry functions.** Registry surface is unchanged; only the auth layer changes.
- **No frontend / Excel-addin UI changes.** User doesn't interact with this.

---

## 3. Current state (verified via research 2026-04-22)

### 3.1 Agent API auth (risk_module)
- `routes/agent_api.py:35-51` — `get_agent_user(request)`: reads `settings.AGENT_API_KEY` (line 37), returns 503 if unset, requires `Authorization: Bearer <token>`, uses `secrets.compare_digest(token, settings.AGENT_API_KEY)` at line 48.
- `routes/agent_api.py:54-60` — `_resolve_agent_user()`: delegates to `utils/user_context.py:resolve_user_email()`, which reads `RISK_MODULE_USER_EMAIL` env var. **Single-user per process** — no way to resolve per-request user identity today.
- `routes/agent_api.py:90` — when `entry.has_user_email`, force-injects `user_email` into params (caller cannot override). This stays.
- `routes/agent_api.py:63,106` — `get_agent_user` guards BOTH `POST /call` and `GET /registry`. Auth changes affect both endpoints, not just `/call` (Codex R1 nit).

### 3.2 Gateway HMAC infrastructure (risk_module — already shipped)
- `routes/internal_resolver.py` implements HMAC-SHA256 verification for the internal resolver flow.
- `routes/internal_resolver.py:48` — reads `GATEWAY_RESOLVER_HMAC_KEY` env var.
- `routes/internal_resolver.py:155-160` — canonical payload: `f"{timestamp}\n{user_id}\n{consumer_key_hash}"`, `hmac.new(key, canonical, hashlib.sha256).digest()`.
- `routes/internal_resolver.py:31` — `_TIMESTAMP_SKEW_SECONDS = 60` (replay window).
- Headers: `X-Resolver-Timestamp`, `X-Resolver-Signature`. **This is the pattern we mirror.**

### 3.3 Sandbox spawn path (AI-excel-addin)
- `api/agent/interactive/runtime.py:125-139` — `_prepare_env_with_host_paths()` only injects `RISK_CLIENT_PATH` + `PORTFOLIO_MATH_PATH` into PYTHONPATH. **No auth / user identity injection.**
- **Critical env-copy site** (Codex R1 blocker #4): `packages/agent-gateway/agent_gateway/code_execution/_helpers.py:65` — `_build_subprocess_env()` does `os.environ.copy()`. This is where **any env var on the parent process, including the HMAC key, leaks into the sandbox**. The §8.3 mitigation (HMAC key must never reach sandbox) implements here, NOT in `_prepare_env_with_host_paths`.
- `packages/agent-gateway/agent_gateway/code_execution/_subprocess.py:114` — `env=process_env` passes the full copied env straight to the subprocess backend.
- `api/agent/interactive/runtime.py:211,467,516,552` — `session.user_id` is threaded through `ToolDispatcher` + `run_agent_handler` + `UserScopedRunner`, but **never reaches the sandbox env**.
- `api/agent/interactive/runtime.py:391` — `prepare_env` closure in `CodeExecutionConfig` is the right injection point for gateway-to-sandbox claim env vars. **No refactor needed** (Codex R1 nit).

### 3.4 Gateway session identity shape (Codex R1 blocker #1)
- `app_platform/gateway/proxy.py:97,103` — the gateway session subject is `str(user.get("user_id"))`, NOT an email. User id is a generic key (strings like `"alice"`, `"1"`, `"42"` in tests).
- `app_platform/gateway/session.py:149` — session threading confirms user_id shape.
- **Implication**: plan cannot sign `user_email` assuming session holds it. Must sign `user_id` and either (a) resolve email on the verifier side, or (b) thread both `user_id` and `user_email` into the signed claim at gateway-side (gateway DOES know email at resolve time, just not carried in session).
- **v2 choice**: sign BOTH `user_id` and `user_email` in the canonical payload. Gateway has both at claim-signing time (user record resolved during auth). Verifier trusts signed email. Zero new DB dependency on the verifier. See §4.1.

### 3.5 Key-name wiring mismatch
- Server validates `AGENT_API_KEY` (risk_module `settings.py` / `routes/agent_api.py`).
- risk_client reads `RISK_API_KEY` at `risk_client/__init__.py:52,55-56` — **raises `ValueError` on missing key** (not just 401 at call time). Operator-aliased to the same secret today.
- The new design makes this moot, BUT (Codex R1 blocker #3) `RiskClient.__init__` must be refactored: it currently REQUIRES the env var at construction time, which means after Step 4 cutover, `_risk = RiskClient()` will crash before headers attach. See §5.2.

### 3.6 Pre-existing JWT dep (Codex R1 nit)
- Earlier draft claimed no JWT in either repo. **Wrong**: AI-excel-addin imports `jwt` at `packages/agent-gateway/agent_gateway/session.py:11` and declares `PyJWT` in `packages/agent-gateway/pyproject.toml:12`. Does NOT force using JWT here — stdlib HMAC is the simpler fit and matches `routes/internal_resolver.py`. Premise corrected for honesty.

### 3.7 Code-execution timeout ceiling (Codex R1 recommend)
- `packages/agent-gateway/agent_gateway/code_execution/_config.py:37` — `max_timeout_ms: int = 120_000`. Code_execute calls are capped at 120s. Plan's 15min expiry is wildly too long for this. v2 derives expiry from ceiling: 300s (120s ceiling + 180s buffer for pre/post overhead).

### 3.8 Docker backend is subprocess-only-today for host paths (Codex R1 recommend)
- `packages/agent-gateway/agent_gateway/code_execution/_backends/_docker.py:147,317` — docker backend spawns with `--network none` and only passes PYTHONPATH; host paths are not volume-mounted. risk_client today works only via subprocess backend.
- **Plan v2 scope**: signed claims are subprocess-only in v1. Docker parity is a follow-up bundled with PM1B.

### 3.9 No existing code-execution env allowlist/denylist (Codex R1 recommend)
- Grep across AI-excel-addin: the only env allowlist is for MCP subprocesses at `packages/agent-gateway/agent_gateway/mcp_client.py:29`. Code execution inherits full `os.environ` unfiltered.
- `run_bash` (`api/local_tools.py:386`) also copies full `os.environ`. Bounds the threat model: the HMAC key strip in §8.3 applies to code_execute AND run_bash if the key ever lives in the parent process.
- v2 adds a minimal denylist mechanism (see §5.3).

---

## 4. Design

### 4.1 Signed claim shape (v2 — revised per Codex R1 blockers #1, #2)

Canonical payload signed by the gateway at sandbox spawn — **six signed values**:

```
f"{audience}\n{issued_at}\n{expiry}\n{user_id}\n{user_email}\n{nonce}"
```

- `audience`: fixed literal `"agent_api_v1"`. Scopes the signature to this auth contract — prevents claim reuse across other HMAC-protected surfaces.
- `issued_at`: integer Unix seconds when signed. Informational.
- `expiry`: integer Unix seconds — hard validity cap. Gateway sets `expiry = issued_at + AGENT_API_CLAIM_TTL_SECONDS` (default **300s** per §3.7).
- `user_id`: gateway session user_id (string). Authoritative identity.
- `user_email`: authoritative email from the gateway's user record at auth time. Signing this avoids a DB lookup on the verifier side.
- `nonce`: 16-byte hex string (32 chars). Primarily for claim uniqueness / observability; replay within TTL is acknowledged in §8 risk #4.

Signature: `hmac.new(hmac_key, canonical.encode(), hashlib.sha256).digest()`, hex-encoded. Six-value canonical → **7-field transport** (6 values + signature header — see §4.3).

### 4.2 Key material

**New env var**: `AGENT_API_USER_CLAIM_HMAC_KEY` (separate from `GATEWAY_RESOLVER_HMAC_KEY` — different concerns, different rotation cadence).

- Set in BOTH AI-excel-addin server (signer) and risk_module server (verifier). Pre-shared ops secret.
- Rotation workflow: shared-secret rotation with a brief dual-key window (verifier accepts old-or-new for the rotation window, then old key is retired). Scope of dual-key support: 5 min skew → support not urgent; scope for v1 plan as single-key, add dual-key mechanism in follow-up if ops needs it.
- Fail-closed: if either side has the env var unset, strict mode rejects all sandbox → agent_api traffic with 503.

### 4.3 Transport (v2 — 7 headers: 6 signed values + signature, per Codex R1 blocker #2)

**Headers** (preferred over bearer — bearer is legacy). `X-Agent-Claim-*` prefix (Codex R1 recommend — clearer than `X-Agent-*`):
- `X-Agent-Claim-Audience: agent_api_v1`
- `X-Agent-Claim-Issued-At: <unix_seconds>`
- `X-Agent-Claim-Expiry: <unix_seconds>`
- `X-Agent-Claim-User-Id: <user_id>`
- `X-Agent-Claim-User-Email: <email>`
- `X-Agent-Claim-Nonce: <16-byte hex>`
- `X-Agent-Claim-Signature: <hex-encoded HMAC-SHA256>`

Bearer auth stays as a **deprecated fallback** during rollout (see §4.5). After cutover, bearer path returns 401.

### 4.4 Verification logic (risk_module)

`routes/agent_api.py:get_agent_user()` updated to prefer signed claim, fall back to bearer. **Feature-flag control flow lives in `get_agent_user()`, not in `_verify_signed_claim()`** (Codex R5 recommend — removes ambiguity):

```python
def get_agent_user(request: Request) -> dict[str, str]:
    """Resolve user from signed claim (preferred) or legacy bearer (fallback)."""
    # Signed-claim path: both flag enabled AND headers present
    if settings.AGENT_API_SIGNED_CLAIM_ENABLED and _has_signed_claim_headers(request):
        return _verify_signed_claim(request)  # succeeds or raises HTTPException

    # Legacy bearer path (deprecated, gated by AGENT_API_LEGACY_BEARER_ENABLED)
    if not settings.AGENT_API_LEGACY_BEARER_ENABLED:
        raise HTTPException(status_code=401, detail="Signed user claim required")
    return _legacy_bearer_auth(request)
```

Control-flow semantics:
- `AGENT_API_SIGNED_CLAIM_ENABLED=false` + headers present → headers IGNORED, bearer path attempted.
- `AGENT_API_SIGNED_CLAIM_ENABLED=true` + headers present → signed-claim verification runs (fails fast on any defect; does NOT silently fall back to bearer per Codex R1 recommend).
- No signed headers → bearer path attempted regardless of flag.
- Both flags false → all requests rejected.

`_verify_signed_claim(request)` is called ONLY when the flag is enabled and headers are present. It performs the 9 checks below and either returns the resolved user dict or raises `HTTPException`. No sentinel, no fall-through.

Steps (v2 — 7 headers, expiry-based validity):
1. Extract the 7 claim headers. Missing any → 401.
2. Audience literal: reject if not `"agent_api_v1"` → 401.
3. Parse `issued_at` and `expiry` as ints. Reject if `issued_at > now + _CLOCK_SKEW` (60s forward tolerance) or `now > expiry` → 401.
4. Sanity: reject if `expiry - issued_at > AGENT_API_CLAIM_MAX_TTL_SECONDS` (default 600s ceiling) — defends against a compromised signer issuing long-lived claims → 401.
5. Parse nonce hex. Reject if not 32 chars or invalid hex → 401.
6. Read `AGENT_API_USER_CLAIM_HMAC_KEY`. Missing → 503.
7. Recompute canonical payload, HMAC-SHA256, hex.
8. `secrets.compare_digest(computed_hex, supplied_hex)` — 401 on mismatch.
9. Return `{"email": user_email_from_claim, "user_id": user_id_from_claim, "source": "signed_claim"}`.

`_resolve_agent_user()` retires — both email and user_id come from the verified claim, not env-var lookup. The `entry.has_user_email` injection at `routes/agent_api.py:90` still uses the resolved email (unchanged call site).

### 4.5 Rollout sequencing

Two env-var flags to allow staged cutover:

- `AGENT_API_SIGNED_CLAIM_ENABLED=true` (default) — enables the signed-claim verification path. When false, only bearer works (e.g., local dev setup without HMAC key provisioned).
- `AGENT_API_LEGACY_BEARER_ENABLED=true` → flip to `false` after all deploys upgraded. When false, bearer-only requests are rejected.

**Rollout phases:**

1. Ship the verifier in risk_module with signed-claim support ON and legacy-bearer also ON. No behavior change (nothing signs yet, all traffic uses bearer).
2. Ship the signer in AI-excel-addin. At sandbox spawn, if `AGENT_API_USER_CLAIM_HMAC_KEY` is set, compute the 6 signed values + signature and inject the 7 `AGENT_API_CLAIM_*` env vars; `risk_client` attaches the 7 `X-Agent-Claim-*` headers on every call. Bearer still attached for legacy servers. Dual-auth-enabled.
3. Confirm prod traffic is 100% signed-claim. Flip risk_module `AGENT_API_LEGACY_BEARER_ENABLED=false`. Revoke static `AGENT_API_KEY`.

### 4.6 What `risk_client` does (v2 — refactor `__init__` per Codex R1 blocker #3)

Current state: `risk_client/__init__.py:50-59` `RiskClient.__init__` **raises `ValueError` if `RISK_API_KEY` is absent**, and installs `Authorization: Bearer` on `self._session` eagerly. After Step 4 cutover, this crashes before headers can attach.

v2 refactor — `__init__` accepts either mode:
1. If `RISK_API_KEY` set → legacy bearer mode (current behavior). Install `Authorization: Bearer`.
2. Else if the 7 signed-claim env vars are present (`AGENT_API_CLAIM_*`) → signed-claim mode. Do NOT install bearer; remember claim env vars for per-`call()` header attachment.
3. Else → raise `ValueError("RISK_API_KEY or signed-claim env vars required")`. Fail-fast matches today's strictness.

On every `call()`:
- In signed-claim mode: re-read the 7 env vars, attach as `X-Agent-Claim-*` headers on THIS request (fresh read allows gateway to rotate the claim mid-sandbox if it ever becomes necessary — out of v1 scope, but the shape supports it).
- In legacy bearer mode: bearer already on session, no per-request work.
- In dual-auth rollout: if both present, attach BOTH (headers + bearer). Verifier accepts either.

**TTL ceiling**: the sandbox reuses one claim across many HTTP calls within its lifetime. Given code_execute max timeout is 120s (`_config.py:37`), the 300s default TTL covers normal sandbox lifetimes with buffer. Long-running plot/MC still well within 300s. Verifier caps TTL at 600s (see §4.4 step 4) so even if a future signer picks a longer TTL, verification rejects anything >10min.

**No HMAC key in sandbox.** Per §8 risk #3, the HMAC key stays in the parent (gateway/runtime) process. The sandbox gets only the already-signed claim values. See §5.3 for the implementation site of the HMAC-key denylist.

### 4.7 Backwards compat & migration

Before ship:
- ✅ risk_module verifier supports signed-claim + legacy-bearer.
- ✅ AI-excel-addin signer injects headers at sandbox spawn.
- ✅ risk_client attaches headers if present, else bearer.

Cutover:
- Flip `AGENT_API_LEGACY_BEARER_ENABLED=false` on risk_module.
- Revoke static `AGENT_API_KEY`.
- All sandbox → agent_api traffic is now signed-claim-only.

No DB migration. No user-facing impact. Rollback is one env-var flip.

---

## 5. Scope — exact file changes (v2)

### 5.1 risk_module — verifier

**Modified**:
- `routes/agent_api.py` — rewrite `get_agent_user()` to prefer signed-claim; add `_verify_signed_claim()` helper mirroring `routes/internal_resolver.py` pattern; keep bearer fallback gated by `AGENT_API_LEGACY_BEARER_ENABLED`. Applies to BOTH `/call` and `/registry` (Codex R1 nit).
- `settings.py` — add `AGENT_API_USER_CLAIM_HMAC_KEY`, `AGENT_API_SIGNED_CLAIM_ENABLED` (default `True`), `AGENT_API_LEGACY_BEARER_ENABLED` (default `True`), `AGENT_API_CLAIM_MAX_TTL_SECONDS` (default `600` — ceiling; signer picks its TTL up to this).
- `tests/routes/test_agent_api.py` — add signed-claim positive/negative cases: valid signature, expired (now > expiry), future-skewed issued_at, TTL > ceiling, wrong signature, wrong audience, missing any of 7 headers, invalid nonce format, HMAC key unset → 503, legacy bearer disabled + signed OK, legacy bearer disabled + bearer only → 401.

**New**:
- `utils/agent_claim.py` — canonical-payload builder + verify helpers. Reusable by both verifier and tests. Exports `build_canonical(...)`, `sign(hmac_key, ...) -> str`, `verify(hmac_key, headers, ttl_ceiling) -> dict | None`.

### 5.2 risk_module — risk_client (Codex R1 blocker #3 expansion)

**Modified**:
- `risk_client/__init__.py` — refactor `__init__` to accept EITHER `RISK_API_KEY` OR the 7 `AGENT_API_CLAIM_*` env vars. Raise `ValueError` only if both absent. Per-`call()` path attaches `X-Agent-Claim-*` headers (fresh read) in signed-claim mode; bearer session header retained only in legacy mode. Dual-auth during rollout: if both present, attach both.
- **`scripts/generate_risk_client.py`** (Codex R1 recommend) — the generator emits `risk_client/__init__.py`; the __init__ template at line 382 mirrors the current bearer-required shape. Generator template must produce the dual-mode `__init__`.
- `tests/test_risk_client_contract.py` — signed-claim-mode case (headers present). Legacy bearer case preserved.
- **`tests/test_risk_client.py`** (Codex R1 recommend) — the existing constructor tests at line 73 assume bearer-required; update to cover dual-mode and the "neither present" failure path.

### 5.3 AI-excel-addin — signer + HMAC-key strip (Codex R1 blocker #4 site correction)

**Prerequisite — thread user_email end-to-end through `/chat/init`** (Codex R2 blocker #1, R3 blocker expansion):
- Email must flow across the full init path on BOTH repos. Current state (all 5 sites lack email):

  Risk_module side (proxy + init payload):
  - `app_platform/gateway/proxy.py:191` — has authenticated `user` dict with email (entry point).
  - `app_platform/gateway/proxy.py:114,123` — forwards only user_id today.
  - `app_platform/gateway/session.py:96,139,149` — **builds the `/chat/init` request payload** to the gateway. Sends `user_id`/`channel` only today.

  AI-excel-addin gateway side (server + session type):
  - `packages/agent-gateway/agent_gateway/server.py:490` — `chat_init` handler reads the init payload.
  - `packages/agent-gateway/agent_gateway/server.py:536` — creates + stores `GatewaySession`; currently only persists `user_id`.
  - `packages/agent-gateway/agent_gateway/session.py:21` — `GatewaySession` dataclass. Add `user_email: str | None`.
  - `packages/agent-gateway/agent_gateway/session.py:157` — session token persistence path. Carry `user_email`.

- **Scope addition (5 files)**:
  1. `app_platform/gateway/proxy.py:114,123,191` — extract `user["email"]` and pass to the session builder.
  2. `app_platform/gateway/session.py:96,139,149` — include `user_email` in the `/chat/init` request body.
  3. `packages/agent-gateway/agent_gateway/server.py:490,536` — read `user_email` from init payload, pass into `GatewaySession` creation.
  4. `packages/agent-gateway/agent_gateway/session.py:21,157` — add `user_email: str | None` to the dataclass + token persistence.
  5. Tests (Codex R3 recommend):
     - `app_platform/gateway/tests/test_session.py:19` — payload-shape test asserts `user_email` now in init body.
     - `packages/agent-gateway/tests/test_server_multi_user.py:103,133` — extend multi-user fixtures to populate `user_email`, assert the gateway persists it on the session.

- Keep `user_email` optional on session for backwards compat during rollout. Signer requires it in signed-claim mode; absent → skip claim injection, fall back to bearer for that request.

**Modified (signer site)**:
- `api/agent/interactive/runtime.py` — build `_prepare_env_with_signed_claim` wrapper that calls `_prepare_env_with_host_paths`, then injects the 7 `AGENT_API_CLAIM_*` env vars computed from `session.user_id` + `session.user_email` (now present after prerequisite) + `AGENT_API_USER_CLAIM_HMAC_KEY`. Threaded via `CodeExecutionConfig(prepare_env=...)` closure at `runtime.py:391` — no refactor needed (Codex R1 nit).
- `settings.py` (AI-excel-addin) — add `AGENT_API_USER_CLAIM_HMAC_KEY` and `AGENT_API_CLAIM_TTL_SECONDS` (default `300`, signer-configurable up to verifier's 600s ceiling) as explicit env-var config (Codex R2 recommend).
- **`packages/agent-gateway/agent_gateway/code_execution/_helpers.py`** (Codex R1 blocker #4 — this is the actual HMAC-key strip site) — extend `_build_subprocess_env()` at line 65 to apply a **sandbox env denylist** that strips `AGENT_API_USER_CLAIM_HMAC_KEY` (and any similarly-sensitive server secrets) from the env dict BEFORE sandbox spawn. This is the critical mitigation for §8 risk #3.
- **Denylist mechanism is new** (Codex R1 recommend — no existing code-exec allowlist). Simple shape: a module-level `_SANDBOX_ENV_DENYLIST: frozenset[str]` containing `AGENT_API_USER_CLAIM_HMAC_KEY`, `GATEWAY_RESOLVER_HMAC_KEY`, and any pre-existing secret env vars we know shouldn't reach the sandbox. Applied after `os.environ.copy()` in `_build_subprocess_env`. Extend via config if ops need per-deploy additions.

**New**:
- `api/agent/interactive/_agent_claim.py` — `sign_user_claim(hmac_key, user_id, user_email, ttl_seconds) -> dict[str, str]` returns the 7 `AGENT_API_CLAIM_*` env-var values. Uses stdlib `hmac`/`hashlib`/`secrets.token_hex(16)` (no PyJWT despite its presence at `session.py:11` — matches `internal_resolver.py` pattern for consistency).

**Tests**:
- `tests/test_code_execute.py` — new test alongside PM1A + Phase 3D smoke tests:
  - Spawn sandbox with `user_id`/`user_email` in session, verify the 7 `AGENT_API_CLAIM_*` env vars are present in sandbox env.
  - **Explicit assertion that `AGENT_API_USER_CLAIM_HMAC_KEY` is NOT in sandbox env** (validates §8 risk #3 mitigation).
  - Integration mode (if risk_module runs locally): full round-trip with signed-claim headers, expect 200.

### 5.4 AI-excel-addin — registry catalog fetcher (Codex R1 recommend)

**Modified**:
- `api/agent/shared/system_prompt.py:646` — `_fetch_risk_function_catalog` currently uses direct `requests` + bearer auth. After cutover, this fails silently and the agent loses the dynamic catalog. **v2 chosen path**: inline — same direct `requests` call, but add signed-claim headers minted at fetch time via a small helper that calls `sign_user_claim()` (§5.3) with a synthetic server-admin identity (`user_id="system:registry_fetcher"`, `user_email="system+registry@hank.local"`). Short-lived (300s TTL), audience `agent_api_v1`. No `risk_client` introduced at this site — `risk_client` is sandbox-side; the fetcher is server-side and hits the same endpoint independently.

### 5.5 Docker backend is subprocess-only in v1 (Codex R1 recommend)

- `packages/agent-gateway/agent_gateway/code_execution/_backends/_docker.py:147,317` — docker is `--network none` + PYTHONPATH-only. risk_client calls already can't work in docker today.
- v1 signed-claim scope: **subprocess backend ONLY**. Docker parity is deferred to a PM1B-bundled follow-up.
- System prompt bullet (AI-excel-addin `system_prompt.py:697`) already notes `host="subprocess"` required for `portfolio_math` / `_risk`. v2 plan doesn't need to extend that constraint.

### 5.6 Config & ops

- `.env.example` in both repos — document `AGENT_API_USER_CLAIM_HMAC_KEY`, the two feature flags (`AGENT_API_SIGNED_CLAIM_ENABLED`, `AGENT_API_LEGACY_BEARER_ENABLED`), and TTL config (`AGENT_API_CLAIM_TTL_SECONDS` signer-side, `AGENT_API_CLAIM_MAX_TTL_SECONDS` verifier ceiling). Mirror the `GATEWAY_RESOLVER_HMAC_KEY` pattern.
- New doc `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` — rollout phases from §4.5, HMAC-key provisioning instructions, cutover verification steps.
- `docs/ops/GATEWAY_MULTI_USER_ACTIVATION.md` — cross-link to the new activation doc.

### 5.7 Threat model bound (Codex R1 recommend)

- `run_bash` (`api/local_tools.py:386`) also copies full `os.environ`. The `_SANDBOX_ENV_DENYLIST` mechanism added in §5.3 should either (a) be shared across `code_execute` and `run_bash`, or (b) be applied separately in `run_bash`'s env construction. **v1 choice**: shared denylist module so both surfaces get the same protection. Scope bump of ~20 lines.

---

## 6. Step-by-step implementation

### Step 1 — risk_module verifier (risk_module only, no behavior change)

- Add `AGENT_API_USER_CLAIM_HMAC_KEY`, `AGENT_API_SIGNED_CLAIM_ENABLED` (default `True`), `AGENT_API_LEGACY_BEARER_ENABLED` (default `True`), `AGENT_API_CLAIM_MAX_TTL_SECONDS` (default `600`) to `settings.py`.
- Add `utils/agent_claim.py` — canonical-payload builder + HMAC verify + TTL/audience/skew checks. Test-reusable.
- Rewrite `routes/agent_api.py:get_agent_user()` for the §4.4 nine-step verification. Keep bearer as gated fallback. Applies to BOTH `/call` (line 63) and `/registry` (line 106).
- Add `tests/routes/test_agent_api.py` cases: valid, expired, future-skewed issued_at, TTL > ceiling, wrong signature, wrong audience, missing each of 7 headers, bad nonce, HMAC key unset → 503, legacy bearer disabled, dual-auth present.
- With `AGENT_API_SIGNED_CLAIM_ENABLED=false` or no signed headers in requests, behavior is byte-identical — all existing bearer tests pass unchanged.
- Commit: `feat(agent_api): gateway-signed user claim verifier (Phase 3 Step 1)`.

### Step 2 — risk_client dual-mode init (Codex R1 blocker #3)

- Refactor `risk_client/__init__.py:RiskClient.__init__` to accept either `RISK_API_KEY` or the 7 `AGENT_API_CLAIM_*` env vars. Raise only if neither present.
- Update `risk_client/__init__.py:call()` — attach `X-Agent-Claim-*` headers in signed-claim mode (fresh env read per call); bearer on session in legacy mode; both in dual-auth rollout mode.
- Update `scripts/generate_risk_client.py` template at line 382 — generator output must match the dual-mode `__init__` (otherwise next regen will clobber the refactor).
- Update `tests/test_risk_client.py` constructor tests (line 73) for dual-mode.
- Update `tests/test_risk_client_contract.py` with signed-claim-mode round-trip against the Step 1 verifier.
- Commit: `feat(risk_client): dual-mode bearer/signed-claim auth (Phase 3 Step 2)`.

### Step 3 — Thread `user_email` end-to-end through `/chat/init` (Codex R3 blocker, R4 blocker — prerequisite for Step 4)

**This step must ship BEFORE Step 4.** Without it, the signer at `session.user_email` has nothing to read. Spans both repos; single conceptual change.

**Payload shape decision** (Codex R4 recommend): `user_email` lives **at top level** in the `/chat/init` request body (not nested under `context`). Reason: mirrors `user_id` which is already top-level at `app_platform/gateway/session.py:149` and `ChatInitRequest` at `packages/agent-gateway/agent_gateway/server.py:46`. Nesting under `context` is for per-request metadata; identity belongs top-level.

**risk_module changes**:
- `app_platform/gateway/proxy.py:114,123,191` — extract `user["email"]` (already in authenticated `user` dict at line 191), pass to session builder.
- `app_platform/gateway/session.py:96,139,149` — include `user_email` in the `/chat/init` request body at top level.
- `app_platform/gateway/tests/test_session.py:19` — payload-shape test asserts top-level `user_email` present.

**AI-excel-addin changes**:
- `packages/agent-gateway/agent_gateway/server.py:46` — add `user_email: str | None = None` to `ChatInitRequest` model.
- `packages/agent-gateway/agent_gateway/server.py:490,536` — read `user_email` from init payload, pass into `GatewaySession` creation.
- `packages/agent-gateway/agent_gateway/session.py:21,157` — add `user_email: str | None` to `GatewaySession` dataclass + token persistence.
- `packages/agent-gateway/tests/test_server_multi_user.py:103,133` — extend multi-user fixtures to populate `user_email`; assert gateway persists it on the session.

**Backwards compat**: `user_email` is OPTIONAL on the session throughout rollout — old risk_module deploys that haven't shipped Step 3 yet will send init without `user_email`, and the gateway session will have `user_email=None`. Signer-side (Step 4) handles this by falling back to bearer when `session.user_email is None`.

Commits (one per repo):
- risk_module: `feat(gateway): thread user_email through /chat/init (Phase 3 Step 3a)`
- AI-excel-addin: `feat(gateway): accept user_email in /chat/init payload + session (Phase 3 Step 3b)`

### Step 4 — AI-excel-addin signer + HMAC-key sandbox strip (Codex R1 blocker #4)

**Depends on Step 3.**

- Add `AGENT_API_USER_CLAIM_HMAC_KEY` + `AGENT_API_CLAIM_TTL_SECONDS` (default 300) to AI-excel-addin env/settings.
- New file `api/agent/interactive/_agent_claim.py` — `sign_user_claim(hmac_key, user_id, user_email, ttl_seconds, audience="agent_api_v1") -> dict[str, str]` via stdlib `hmac`/`hashlib`/`secrets.token_hex(16)`.
- Refactor `api/agent/interactive/runtime.py` — build `_prepare_env_with_signed_claim` wrapper; thread via `CodeExecutionConfig(prepare_env=...)` closure at line 391. **Fallback**: if `session.user_email is None` OR `AGENT_API_USER_CLAIM_HMAC_KEY` unset, skip signed-claim injection (sandbox falls back to bearer via risk_client).
- **Critical**: `packages/agent-gateway/agent_gateway/code_execution/_helpers.py:65` — add `_SANDBOX_ENV_DENYLIST` (frozenset) applied after `os.environ.copy()`. Include `AGENT_API_USER_CLAIM_HMAC_KEY`, `GATEWAY_RESOLVER_HMAC_KEY`, plus pre-existing server-secret vars. Mirror into `api/local_tools.py:386` `run_bash`.
- Docker backend unchanged — subprocess-only in v1 per §5.5.
- `tests/test_code_execute.py` — new tests:
  - Happy path: `session.user_email` set + HMAC key set → 7 `AGENT_API_CLAIM_*` env vars present in sandbox.
  - **`AGENT_API_USER_CLAIM_HMAC_KEY` NOT in sandbox env** (validates §8 risk #3).
  - **Rollout-compat test (Codex R4 recommend)**: `session.user_email is None` → no claim env vars injected; sandbox falls back to bearer; agent_api accepts because legacy-bearer still enabled.
  - Round-trip if risk_module verifier available locally.
- Commit in AI-excel-addin: `feat(sandbox): inject gateway-signed user claim + env denylist (Phase 3 Step 4)`.

### Step 5 — AI-excel-addin registry catalog fetcher (Codex R1 recommend)

- `api/agent/shared/system_prompt.py:646` — `_fetch_risk_function_catalog` uses direct `requests` + bearer today. Keep the same shape but mint signed headers inline via `sign_user_claim()` with a synthetic server-admin identity (`user_id="system:registry_fetcher"`, `user_email="system+registry@hank.local"`, 300s TTL, audience `agent_api_v1`). No `risk_client` introduced here — `risk_client` is sandbox-side; this is a server-side fetcher. Matches §5.4 choice. Otherwise after Step 6 cutover, the dynamic catalog silently stops loading.
- Extend `tests/test_system_prompt.py` with a fetcher regression test asserting the dynamic catalog still populates post-cutover.
- Commit in AI-excel-addin: `fix(prompt): migrate registry fetcher to signed-claim auth (Phase 3 Step 5)`.

### Step 6 — Rollout + cutover

- Deploy Steps 1-5 to staging. Verify signed-claim traffic, legacy bearer optional.
- Ops: provision `AGENT_API_USER_CLAIM_HMAC_KEY` in both repos' deploy envs. Document in new `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md`.
- After confirming 100% signed-claim traffic in staging then prod: flip risk_module `AGENT_API_LEGACY_BEARER_ENABLED=false`. Revoke `AGENT_API_KEY`.
- Commit: `chore(agent_api): retire legacy bearer path (Phase 3 Step 6)` — removes bearer branches, retires settings, docs cleanup.

### Step 7 — Docs + ship log

- Update `docs/planning/AGENT_SURFACE_AUDIT.md` — add Phase 3 multi-user row → SHIPPED.
- Update `docs/TODO.md` 6D entry → DONE, superseded from DB-backed-keys design.
- Update `docs/planning/completed/AGENT_CODE_EXECUTION_REGISTRY_PLAN.md` Phase 3 section — mark superseded with pointer.
- Append ship log with commit SHAs across both repos to this plan's §10.
- Commit: `docs(planning): mark agent_api multi-user SHIPPED`.

---

## 7. Test plan

New tests at each step. Coverage targets:

**risk_module `tests/routes/test_agent_api.py`** (Step 1):
- Signed claim: valid → 200. Missing any of 7 headers → 401. Expired (`now > expiry`) → 401. Future-skewed `issued_at` → 401. TTL > ceiling → 401. Wrong signature → 401. Wrong audience → 401. Non-hex nonce / not 32 chars → 401. HMAC key unset → 503. Legacy-bearer disabled + signed OK → 200. Legacy-bearer disabled + bearer only → 401.
- Feature-flag gate (Codex R4 recommend): `AGENT_API_SIGNED_CLAIM_ENABLED=false` + valid signed headers present + bearer also present → bearer path used (signed claim ignored when disabled). `AGENT_API_SIGNED_CLAIM_ENABLED=false` + signed headers only → 401.
- Preserve all existing bearer-auth tests under `AGENT_API_LEGACY_BEARER_ENABLED=true` (default during rollout).
- Applies to BOTH `/call` and `/registry` endpoints.

**risk_client contract tests** (Step 2):
- Signed-claim mode: 7 env vars set → `X-Agent-Claim-*` headers present, no bearer.
- Legacy mode: `RISK_API_KEY` set → bearer attached, no claim headers.
- Dual-auth mode: both set → both attached.
- Neither present → `ValueError` at `__init__` time.
- Round-trip against Step 1 verifier (either live or mock).
- `tests/test_risk_client.py` constructor tests updated.

**AI-excel-addin `/chat/init` handoff** (Step 3):
- risk_module side (`app_platform/gateway/tests/test_session.py:19`): init request payload includes top-level `user_email` field.
- AI-excel-addin side (`packages/agent-gateway/tests/test_server_multi_user.py:103,133`): init handler reads top-level `user_email`, `GatewaySession.user_email` persists through token round-trip.

**AI-excel-addin code_execute** (Step 4):
- Mocked mode: spawn sandbox for a `(user_id, user_email)` pair, assert `sign_user_claim` was called with both. Assert all 7 `AGENT_API_CLAIM_*` env vars are present in the sandbox env via the PM1A pattern.
- Critical: assert `AGENT_API_USER_CLAIM_HMAC_KEY` is NOT in the sandbox env (§8 risk #3 validation).
- Rollout-compat: `session.user_email is None` → no claim env vars → sandbox falls back to bearer → agent_api accepts under legacy bearer.
- Integration mode (requires live risk_module verifier): full round-trip — sandbox → signed-claim headers → 200 response from agent_api.

**Tests that must pass unchanged**:
- Everything in `tests/routes/test_agent_api.py` under default (legacy bearer enabled).
- All tests in AI-excel-addin `tests/test_code_execute.py` — PM1A smoke and Phase 3D smoke — must still pass with signer enabled.

---

## 7a. Follow-up (out of scope for this plan)

**Identity model refactor: `user_email` → `user_id` as canonical downstream identity**

The signed claim in this plan carries both `user_id` (authoritative) and `user_email` (convenience to avoid verifier-side lookup). The email is preserved because risk_module's internal code — 409 occurrences across 124 files — keys user-scoped data by email today (registry functions, actions, services, providers, MCP tools, DB queries, tests). Converting to user_id is a weeks-long refactor orthogonal to multi-user auth.

When that refactor ships, this plan's signed claim can drop `user_email` as a one-line canonical change (update signer + verifier + risk_client env-var set — ~10 lines net). The design is forward-compatible.

**Not blocking multi-user.** Tracked separately in `docs/TODO.md` (see "Identity Model Refactor" entry). File a dedicated plan when sequenced.

---

## 8. Risks & mitigations (v2)

| # | Risk | Mitigation |
|---|------|------------|
| 1 | **Clock skew between signer and verifier** | 60s forward-skew on `issued_at`. 300s TTL default. NTP assumption documented in ops guide. |
| 2 | **HMAC key leak from AI-excel-addin server disk** | Same threat model as `GATEWAY_RESOLVER_HMAC_KEY` today. Secrets Manager for prod, env-var for dev. |
| 3 | **Sandbox steals key from env and mints claims** (Codex R1 blocker #4 — site corrected) | The HMAC key NEVER enters the sandbox env. Strip site: `_build_subprocess_env()` in `code_execution/_helpers.py:65` — `_SANDBOX_ENV_DENYLIST` applied after `os.environ.copy()`. **Step 4 test explicitly asserts the key is not in sandbox env.** Same denylist applied at `api/local_tools.py:386` `run_bash`. |
| 4 | **Replay inside TTL window** (Codex R1 recommend — honest framing) | Nonce alone does not prevent replay without server-side nonce storage. A stolen header set IS replayable until `expiry`. Mitigation: (a) TLS in transit, (b) 300s TTL caps blast radius, (c) verifier TTL-ceiling rejects tampered expiry. Add per-nonce caching if operational evidence requires. |
| 5 | **Dual-auth rollout leaves a seam** | Explicit feature flags + rollout playbook in §4.5. Cutover is a single env-var flip. Invalid signed headers do NOT downgrade to bearer — they fail (Codex R1 recommend). |
| 6 | **Long-running sandbox exceeds claim expiry** | Code_execute hard cap is 120s (`_config.py:37`). 300s TTL has ~180s buffer for overhead. `AGENT_API_CLAIM_MAX_TTL_SECONDS=600` is the verifier ceiling (signer can pick anything ≤ ceiling). If long-sandbox patterns emerge, bump ceiling or add refresh endpoint. |
| 7 | **Docker backend** | Subprocess-only in v1 (Codex R1 recommend). Docker backend is `--network none` + PYTHONPATH-only — risk_client doesn't work there today. Deferred to PM1B bundle. |
| 8 | **`run_bash` leaks HMAC key too** (Codex R1 recommend) | Same `_SANDBOX_ENV_DENYLIST` applied at `api/local_tools.py:386` env construction. Both surfaces protected by one shared module. |
| 9 | **Registry fetcher silently breaks at cutover** (Codex R1 recommend) | `api/agent/shared/system_prompt.py:646` dynamic catalog fetch migrates to signed-claim auth in Step 5. Test regression added in Step 5. |

---

## 9. Codex review resolutions

> **Note**: step numbers referenced in R1-R3 resolutions reflect the step numbering at each round's plan version. After v5's R4 restructure, steps were renumbered (prereq became Step 3, everything after shifted +1). Resolution bullets below preserve their original round-context numbering; for current step numbers, see §6.



### R4 resolutions (2026-04-22, v4 → v5)

- **R4 Blocker (prereq not in executable step sequence)** → §6 restructured: new **Step 3** dedicated to `user_email` end-to-end threading (own commits in both repos), Step 4 now AI-excel-addin signer + depends explicitly on Step 3. Step 4/5/6 renumbered throughout.
- **R4 Recommend (pin where user_email lives in /chat/init)** → Step 3 decision: **top-level `user_email` field** (not nested under `context`). Mirrors `user_id`. `ChatInitRequest` model change added to scope at `server.py:46`.
- **R4 Recommend (AGENT_API_SIGNED_CLAIM_ENABLED missing from §4.4 and tests)** → Added as step 0 of the verifier pseudocode (feature-flag gate). §7 test list extended with "signed headers present while verification disabled" case.
- **R4 Recommend (rollout-compat test for session.user_email is None)** → Added to Step 4 test list — sandbox falls back to bearer when email is absent; agent_api accepts because legacy bearer still enabled during rollout.
- **R4 Nit (change log said canonical = 7 values)** → Corrected: canonical is 6 values, signature is transport. 7-field transport = 6 values + signature header.

### R3 resolutions (2026-04-22, v3 → v4)

- **R3 Blocker #1 (user_email prereq didn't cover all 5 init sites)** → §5.3 prerequisite now enumerates 5 files across both repos: proxy.py:114,123,191 + session.py:96,139,149 in risk_module, server.py:490,536 + session.py:21,157 in AI-excel-addin. End-to-end coverage on `/chat/init` path.
- **R3 Blocker #2 (Step 4 text still mentioned risk_client)** → §6 Step 4 aligned with §5.4 — inline `requests` + `sign_user_claim()` only, risk_client reference removed.
- **R3 Recommend (tests for user_email handoff)** → Prerequisite scope now includes `test_session.py:19` payload-shape test and `test_server_multi_user.py:103,133` persistence tests.
- **R3 Nit (§5.6 "three feature flags")** → Corrected to "two feature flags + TTL config" with explicit enumeration.

### R2 resolutions (2026-04-22, v2 → v3)

- **R2 Blocker #1 (no path to `user_email` in session)** → §5.3 new "Prerequisite" subsection explicitly scopes threading email through `GatewaySession` and the proxy forward. `app_platform/gateway/proxy.py:114,123,191` + `packages/agent-gateway/agent_gateway/session.py:21,157` added to scope. Gateway test fixture extension noted.
- **R2 Blocker #2 (residual inconsistencies on header/field count)** → Three spots fixed: §4.1 line 94 "6-value canonical → 7-field transport"; §4.3 heading corrected to "7 headers: 6 signed values + signature"; §4.5 rollout Step 2 now says "7 AGENT_API_CLAIM_* env vars"; §7 Step 3 test assertion now "7 env vars" plus explicit HMAC-key-not-in-sandbox assertion.
- **R2 Recommend #1 (pick one registry-fetcher path)** → §5.4 chose: inline `requests` + signed headers minted via `sign_user_claim()` with synthetic server-admin identity. risk_client not introduced there — it's a sandbox-side client, the fetcher is server-side.
- **R2 Recommend #2 (TTL config source)** → `AGENT_API_CLAIM_TTL_SECONDS` (default `300`) explicit in AI-excel-addin `settings.py` (added to §5.3). Verifier ceiling stays at `AGENT_API_CLAIM_MAX_TTL_SECONDS=600` in risk_module.
- **R2 Nit (§4.3 labeled 6 headers)** → Fixed to "7 headers: 6 signed values + signature".

### R1 resolutions (2026-04-22, v1 → v2)

All R1 findings resolved in v2:

1. **Blocker #1 (claim subject is user_id, not email)** → §4.1 canonical payload now signs BOTH `user_id` and `user_email`. Gateway has both at signing time; verifier trusts both from the signed claim. §3.4 documents session identity shape.
2. **Blocker #2 (plan internally inconsistent on 4 vs 5 headers)** → v2 uses 7 headers throughout (audience + issued_at + expiry + user_id + user_email + nonce + signature). All sections (§4.3, §4.4, §5.2, §6 Steps 1-3) propagated consistently.
3. **Blocker #3 (risk_client `__init__` crashes on missing RISK_API_KEY)** → §5.2 rewrites `RiskClient.__init__` as dual-mode (bearer OR claim env vars). `scripts/generate_risk_client.py` and `tests/test_risk_client.py` added to scope.
4. **Blocker #4 (HMAC key strip site wrong)** → §5.3 corrected to `packages/agent-gateway/agent_gateway/code_execution/_helpers.py:65` `_build_subprocess_env()`. Denylist mechanism added (new — doesn't exist today) and reused by `run_bash` in `api/local_tools.py:386`.
5. **Recommend (expiry too long)** → Default TTL 300s (was 900s). Verifier ceiling 600s. Derived from code_execute 120s max timeout + ~180s buffer.
6. **Recommend (nonce ≠ replay protection)** → §8 risk #4 reframed honestly. Mitigation is TLS + short TTL + ceiling; verifier-side nonce caching deferred unless ops evidence.
7. **Recommend (audience/scope string)** → Added `audience = "agent_api_v1"` as first canonical field. Prevents cross-surface claim reuse.
8. **Recommend (`X-Agent-Claim-*` header prefix)** → Applied throughout §4.3.
9. **Recommend (docker backend out of scope)** → §3.8 / §5.5 explicit. Deferred to PM1B bundle.
10. **Recommend (scope missed generator + tests + system_prompt)** → §5.2 adds `scripts/generate_risk_client.py` and `tests/test_risk_client.py`. §5.4 adds `api/agent/shared/system_prompt.py:646` registry fetcher migration as a new Step 4.
11. **Recommend (no existing code-exec env allowlist)** → §5.3 adds `_SANDBOX_ENV_DENYLIST` as a new shared mechanism applied in both code_execute and run_bash env construction.
12. **Nit (PyJWT already in AI-excel-addin)** → §3.6 corrected. Doesn't force using JWT; stdlib HMAC is still the fit.
13. **Nit (auth protects /call AND /registry)** → §3.1 and §5.1 updated. Both endpoints covered by the same `get_agent_user` rewrite.
14. **Nit (threading `session.user_id` into prepare_env needs no refactor)** → §3.3 bullet added.

---

## 10. Ship log

Shipped 2026-04-22. This log records the implementation commits that landed across both repos.

- Step 1 — `risk_module` `2fe96075` — verifier + signed-claim tests (`43` pass)
- Step 2 — `risk_module` `6e9cc689` — dual-mode `risk_client` auth (`72` pass)
- Step 3a — `risk_module` `6d2a131f` — `/chat/init` top-level `user_email` threading (`3` pass)
- Step 3b — `AI-excel-addin` `5099f18` — `/chat/init` accept/persist `user_email` (`10` pass)
- Step 4 — `AI-excel-addin` `b16e8e2` — signer + sandbox env denylist (`25` pass)
- Step 5 — `AI-excel-addin` `985d30a` — registry fetcher signed-claim migration (`3` pass)

Rollout activation remains manual and is documented in `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md`.

### Live verification (2026-04-23 session)

| Check | Method | Result |
|---|---|---|
| Verifier accepts valid signed claim (all 6 canonical fields + HMAC) | `curl` with real HMAC-SHA256 | ✅ 200, `X-Agent-Claim-User-Id` resolved |
| Verifier rejects bad signature | `curl` with zeroed signature | ✅ 401 "Invalid signed user claim" |
| Verifier rejects expired claim (`now > expiry`) | `curl` with past expiry | ✅ 401 |
| Verifier rejects wrong audience | `curl` with `"agent_api_v999"` | ✅ 401 |
| Verifier rejects missing header | `curl` without `X-Agent-Claim-Nonce` | ✅ 401 |
| Legacy bearer still works under dual-auth | `curl` with `Authorization: Bearer $AGENT_API_KEY` | ✅ 200 |
| Step 5 registry fetcher uses signed-claim live | Gateway restart → `_fetch_risk_function_catalog` hits `/api/agent/registry?tier=...` | ✅ 200 from gateway's signed-claim path |
| `/chat/init` accepts + persists `user_email` | backend POST with `user_email=hc@henrychien.com` | ✅ session created |
| Signer reaches `code_execute` tool call with `host='subprocess'` | gateway log: `Tool call: code_execute` | ✅ invoked via `web` channel |

**Not covered live** (covered by Step 4 unit tests):
- Sandbox env vars actually injected at spawn.
- `AGENT_API_USER_CLAIM_HMAC_KEY` confirmed absent from sandbox env.
- End-to-end: sandbox `risk_client` → `/api/agent/call` with `X-Agent-Claim-*` → risk_module logs `source: signed_claim`.

Blocker that prevented full E2E verification: Hank frontend requests `claude-opus-4-7` but ai-excel-addin's `ALLOWED_MODELS` at `tool_catalog.py:54` only lists `claude-sonnet-4-6` + `claude-opus-4-6`. Gateway rejects with 400 before code_execute is dispatched. This is package-version drift (stale published ai-agent-gateway vs current source), unrelated to Phase 3 but blocking the live test. Filed separately in TODO as an architectural package-publish issue.

**Cutover readiness**: verifier side is production-safe (all reject paths tested with real HMAC + signed-claim path live via Step 5 fetcher). Rollout activation (flip `AGENT_API_LEGACY_BEARER_ENABLED=false`) not yet executed. Dual-auth mode remains active; cutover reversible via single env-var flip.

---

## 11. Change log

**v5 (2026-04-22)**: Codex R4 FAIL (step-sequence + spec-step drift). Fixed:
- Blocker: `/chat/init` prereq promoted from §5 prose into §6 as its own **Step 3** (cross-repo, own commits). Later steps renumbered 4→5→6→7.
- Recommend: top-level `user_email` in `ChatInitRequest` payload shape locked (not under `context`).
- Recommend: `AGENT_API_SIGNED_CLAIM_ENABLED` gate explicit at verifier step 0; §7 test list covers "headers present + verification disabled".
- Recommend: rollout-compat test for `session.user_email is None` → bearer fallback.
- Nit: change log "canonical = 7 values" → corrected to "canonical = 6 values, signature is transport; 7-field transport".

**v4 (2026-04-22)**: Codex R3 FAIL (plan-shape gaps). Fixed:
- Blocker: `user_email` prereq now enumerates **all 5 sites** on the `/chat/init` path, not just 2. Added `risk_module/app_platform/gateway/session.py:96,139,149` (init request builder) and `AI-excel-addin/packages/agent-gateway/agent_gateway/server.py:490,536` (init handler + session creation).
- Blocker: §6 Step 4 now specifies inline `requests` + `sign_user_claim()` (matches §5.4 choice). Previously said "via reused risk_client" — contradiction removed.
- Recommend: added `/chat/init` payload-shape + session-persistence tests to §5.3 prerequisite (`risk_module/app_platform/gateway/tests/test_session.py:19` and `AI-excel-addin/packages/agent-gateway/tests/test_server_multi_user.py:103,133`).
- Nit: §5.6 "three feature flags" → corrected to "two feature flags + TTL config" (enumerated).

**v3 (2026-04-22)**: Codex R2 FAIL (plan-shape, not design). Fixed:
- Blocker: added explicit scope for threading `user_email` through `GatewaySession` + proxy (prerequisite in §5.3). Core issue: session only carries `user_id` today; signer has no path to email without this prereq.
- Blocker: propagated 7-header consistency through remaining §4.1, §4.3, §4.5, §7 Step 3.
- Recommend: picked registry-fetcher path (inline signed-header requests with synthetic server-admin identity) — dropped the alternative.
- Recommend: added `AGENT_API_CLAIM_TTL_SECONDS` (default 300) explicit signer config.

**v2 (2026-04-22)**: Codex R1 FAIL → rewritten. 4 blockers + 7 recommends + 3 nits all integrated. See §9 resolutions.

Key v2 shape changes:
- Canonical payload: 6 signed values (audience + issued_at + expiry + user_id + user_email + nonce). Signature is transport, not part of canonical. 7-field transport = 6 values + signature header. Previously inconsistent across sections.
- Claim subject: `user_id` + `user_email` (both signed). Previously incorrectly assumed session carried email.
- TTL: 300s default / 600s ceiling. Previously 900s which exceeded code_execute's 120s max.
- risk_client: `__init__` refactor mandatory — previously missed the hard-raise on missing `RISK_API_KEY`.
- HMAC-key strip site: `packages/agent-gateway/agent_gateway/code_execution/_helpers.py:65` (not runtime). Denylist is new, applies to code_execute and run_bash.
- Scope additions: generator template, `tests/test_risk_client.py`, `api/agent/shared/system_prompt.py:646` registry fetcher.
- Docker backend explicitly out-of-scope for v1 — risk_client doesn't work in docker today anyway.
- Step count: 5 → 6 (added registry fetcher migration as own step).

**v1 (2026-04-22)**: Initial draft. FAIL at Codex R1.
