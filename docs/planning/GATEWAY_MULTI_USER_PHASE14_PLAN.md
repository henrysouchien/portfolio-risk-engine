# Gateway Multi-User Migration — Phase 1.4 (Consumer-Side)

**Status:** APPROVED — Codex PASS round 4 (4 rounds, 10 findings addressed: 3 BLOCKER, 4 MAJOR, 3 MINOR)
**Date:** 2026-04-09
**Scope:** risk_module portfolio app, consumer-side only
**Depends on:** Phase 1.3 (finance_cli) landed ✅
**Upstream design doc:** `/Users/henrychien/Documents/Jupyter/AI-excel-addin/docs/design/gateway-multi-user-task.md` (§ "risk_module portfolio chat", lines 678–696)
**Task spec:** `docs/design/gateway-multi-user-migration-task.md` (note: spec overstates scope — see §1 below)

---

## 1. Scope correction vs. original task spec

The task spec at `docs/design/gateway-multi-user-migration-task.md` describes Phase 1.4 as a **two-place change**: (a) gateway-service side in `app.py`, (b) portfolio-app side in the proxy. This is wrong for risk_module. Verified:

- risk_module has **no `create_gateway_app()` instance**. No imports of it anywhere in the repo.
- `services.yaml` runs only `risk_module` (uvicorn `app:app`) and `risk_module_frontend` (vite). No gateway service.
- `GATEWAY_URL` env var points at an **external gateway** — in dev/prod this is finance_cli's gateway service (`python3 -m finance_cli.gateway`, port 8002). All resolver / usage ledger / BYOK work lives there per Phase 1.3.
- `users.anthropic_api_key_encrypted` columns referenced in the spec **do not exist** in `database/schema.sql`. Those columns live in finance_cli's DB, which finance_cli's resolver reads.
- `PostgresUsageLedger`, `routes/user_settings.py` BYOK CRUD, `utils/secrets.py` encryption helper all belong to the **gateway-service side** → out of scope.

**Phase 1.4 for risk_module is strictly consumer-side**: make the HTTP proxy speak the gateway's new multi-user contract so that when the gateway turns on strict mode (once a resolver is wired on the finance_cli gateway), risk_module doesn't break.

**If risk_module ever needs its own gateway service** (for isolated billing, different user base, etc.), that's a separate future task.

---

## 2. Current state

### 2.1 Session manager (`app_platform/gateway/session.py`)
- `GatewaySessionManager` keys the token store by `user_key` alone (string).
- `_get_user_key(user)` in `proxy.py` returns `str(user["user_id"])` (or google_user_id / email fallback) — so each authenticated risk_module end-user already gets their own gateway session token. ✓ Not pooled across users.
- `_initialize_session()` POSTs `{"api_key": api_key}` to `/chat/init` — **no `user_id` field sent**. Gateway's current behavior in non-strict mode: session is bound to `user_id="_default"`. Once the gateway flips strict mode, this will 400 with `strict_mode_default_user`.

### 2.2 Proxy (`app_platform/gateway/proxy.py`)
- `_build_gateway_chat_payload()` puts `user_id` inside `context["user_id"]` only — **no top-level field**. Gateway reads `ChatRequest.user_id` (top-level) first; missing → `None`. In strict mode: 400 `missing_user_id`.
- `request_id` is not sent at all. Gateway generates its own (uuid4) per request. No end-to-end trace from proxy → ledger.
- Existing 401 retry: on any 401 from `/api/chat`, force-refreshes the session token and retries once. Does **not** inspect error body — would unconditionally retry on structured 401s like `cross_user_reuse` if they ever happen (today they can't, but strict mode makes them possible). The existing code retries once (not infinitely), but the unconditional retry is still wrong for non-session-expired 401s.
- **No `auth_expired` handling.** Gateway's plan is to emit `{"error": "auth_expired", ...}` when Anthropic returns 401 on an expired OAuth token. Consumer must detect, re-init the session, and replay the request. Today risk_module would see this as a generic error and bubble it to the user.
- **Good news:** proxy is already a transparent forwarder for stream content. It does **not** scrape `usage` from `stream_complete` events. No billing double-count risk. ✓ No change needed on that axis.

### 2.3 Frontend (`GatewayClaudeService.ts`)
- Sends `{messages, context: {channel, ...}}` to `/api/gateway/chat`. No `user_id` — correct, because the proxy resolves it server-side from the authenticated session.
- **No frontend changes in Phase 1.4.** ✓

### 2.4 Shared package implication
- `app_platform/gateway/` is synced to the PyPI package `app-platform` (`scripts/sync_app_platform.sh`).
- `finance-web/server/routers/chat_router.py` also uses `app_platform.gateway`. So Phase 1.4 changes will affect finance-web too once published.
- Changes must be **additive and backward-compatible**: non-strict mode (no resolver on gateway) must continue to work. This is verified by keeping `context.user_id` intact, defaulting `user_id` kwargs to `None`, and only adding new top-level fields to outgoing payloads.

---

## 3. Acceptance gates

This plan is done when:

1. **Strict-mode init:** `POST /chat/init` sends `user_id` top-level. Verified by mock gateway asserting top-level presence.
2. **Strict-mode chat:** `POST /chat` upstream payload carries top-level `user_id` and `request_id`. Verified by mock gateway asserting top-level presence.
3. **Session pool isolation under key rotation:** If `GATEWAY_API_KEY` rotates, `get_token()` detects consumer-hash mismatch and forces a refresh (re-init with new key). Verified via unit test flipping the key.
4. **`auth_expired` retry (pre-stream only):** On pre-stream (non-200 HTTP response) `{"error": "auth_expired"}`, proxy invalidates the session token, re-inits the session, retries **once** (2 total `/chat` sends for pure auth_expired; 3 if mixed with session_expired). If the retry also fails with auth_expired, surfaces to client. Mid-stream SSE `auth_expired` detection is explicitly deferred (see §4.3 Change 4 — the frontend does NOT currently retry on mid-stream errors).
5. **Structured-401 no-infinite-loop:** On `{"error": "cross_user_reuse"}` (401) the proxy does NOT retry — surfaces error to client. Verified via mock.
5b. **Init-time credential errors surfaced:** On `credentials_unavailable`, `credentials_timeout`, or `strict_mode_default_user` from `/chat/init`, proxy surfaces the upstream status + structured body instead of collapsing to 502. Verified via mock.
6. **Backward compat:** All existing `tests/test_gateway_proxy.py` and `tests/app_platform/test_gateway_session.py` tests still pass (single-user / non-strict mode unchanged).
7. **No billing scraping:** Grep confirms `usage` / `stream_complete` event scraping is still absent. (Negative test: fail CI if a future change adds it.)
8. **End-to-end dev smoke:** With `GATEWAY_URL` pointed at finance_cli's gateway (strict mode, resolver configured, risk_module user provisioned in finance_cli's DB), the analyst chat stream lands successfully end-to-end. Documented as a manual gate, not automated.

---

## 4. File-by-file changes

All changes live in `app_platform/gateway/*` (plus tests). Nothing in `routes/`, `database/`, `frontend/`, or `app.py`.

### 4.1 `app_platform/gateway/session.py`

**Change 1 — Consumer-hash metadata for GATEWAY_API_KEY rotation detection.**

Rationale: guards against GATEWAY_API_KEY rotation leaving stale tokens in the pool. The store key stays as raw `user_key` (no composite) — this preserves backward compat for finance-web cleanup code (`settings_router.py:222`, `deletion_cleanup.py:144`) and all existing call sites that use `invalidate_token(user_key)` / `lookup_token(user_key)`.

**Codex R1 fix:** Composite-key storage was rejected because: (a) tool-approval `lookup_token()` would fail to find the in-flight session's token after a mid-stream key rotation; (b) finance-web callers that delete tokens by raw `user_key` would miss the composite entries.

Design:
- Add a `_consumer_key_hash(api_key: str) -> str` module-level helper returning `sha256(api_key).hexdigest()[:16]`.
- Add a second internal dict `_consumer_hashes: dict[str, str]` on `GatewaySessionManager`, keyed by `user_key`, storing the `consumer_hash` that was active when the token was issued.
- `get_token()`: compute `consumer_hash = _consumer_key_hash(api_key_fn())`. If stored hash for `user_key` doesn't match current hash → `force_refresh=True` (treat as stale). Store `(token, hash)` pair on success.
- `invalidate_token(user_key)` — **signature unchanged**. Deletes both the token and the consumer hash entry for `user_key`. All existing call sites (proxy disconnect, finance-web cleanup) work unchanged.
- `lookup_token(user_key)` — **signature unchanged**. Returns the cached token regardless of consumer hash (needed for mid-flight tool approvals). The staleness check only happens in `get_token()`.
- `reset()` — clears both `_token_store` and `_consumer_hashes`.

**Change 2 — Thread `user_id` into `_initialize_session()`.**

Rationale: gateway's `/chat/init` (strict mode) requires top-level `user_id`.

- `_initialize_session()` gains `user_id: str | None = None` kwarg.
- POST body becomes `{"api_key": api_key, "user_id": user_id}` when `user_id is not None`; falls back to `{"api_key": api_key}` when `None` (backward compat with current tests / non-strict mode / callers that haven't updated).
- `get_token()` threads `user_key` through as `user_id` to `_initialize_session()`.
- Rationale for using `user_key` as `user_id`: `_get_user_key(user)` in `proxy.py` already produces the authoritative end-user identifier (DB int id → google sub → email). That's what the gateway's resolver will key on.

**Change 3 — Structured error handling in `_initialize_session()` (Codex R1 BLOCKER fix).**

Rationale: strict-mode credential errors (`credentials_unavailable`, `credentials_timeout`, `strict_mode_default_user`) fire from `/chat/init`, not `/chat`. Current code collapses all non-200 init responses to a generic 502 — losing the upstream error code and preventing meaningful client error messages.

- On non-200 from `/chat/init`, attempt JSON parse of the body.
- If parseable and `body.get("error")` is a known gateway error code, raise an `HTTPException` with:
  - Status code = upstream status (401 for `credentials_unavailable`, 504 for `credentials_timeout`, 400 for `strict_mode_default_user`). Preserves the upstream code instead of collapsing to 502.
  - Detail = upstream body dict (passed through as structured JSON detail so the proxy caller / frontend can inspect `.error`, `.message`, etc.)
- If not parseable or unknown error code, fall back to current behavior: 502 with `f"Gateway session init failed ({status})"`.
- This means the proxy's `gateway_chat()` handler will naturally surface these errors — the HTTPException propagates up through the `try/except HTTPException: raise` path already at line 302.

### 4.2 `app_platform/gateway/models.py`

**No change to models.** `request_id` generation is handled inline in `proxy.py` (see §4.3 Change 2).

### 4.3 `app_platform/gateway/proxy.py`

**Change 1 — `_build_gateway_chat_payload()` sends top-level `user_id` and `request_id`.**

- Signature change: `_build_gateway_chat_payload(chat_request, channel, user_key, request_id)`.
- Emit:
  ```python
  {
      "messages": chat_request.messages,
      "context": upstream_context,   # context.user_id kept for backward compat with any enricher; harmless duplication
      "user_id": user_key,            # NEW top-level (strict-mode requirement)
      "request_id": request_id,       # NEW top-level (end-to-end trace)
  }
  ```
- Continue setting `upstream_context["user_id"] = user_key`. Reason: the existing context_enricher path echoes `user_id` into context; maintaining it avoids breaking any downstream consumer that reads from context. Harmless redundancy — gateway prefers top-level.

**Change 2 — `gateway_chat()` handler generates `request_id` per request (**Codex R1+R2 fix: format + reuse + ordering**).**

Ordering matters: `request_headers_factory` (if configured) may inject an `X-Request-ID` header. finance-web does this in `chat_router.py:22`. So we must resolve `extra_headers` BEFORE deriving `request_id`.

Implementation order inside `gateway_chat()`:
1. Compute `extra_headers` from `config.request_headers_factory(request)` (existing code, just move it earlier in the try block — before payload construction instead of after).
2. Derive canonical `request_id`: `(extra_headers or {}).get("X-Request-ID") or request.headers.get("X-Request-ID") or str(uuid.uuid4())`. Priority: factory-injected > incoming header > generated.
3. Pass `request_id` to `_build_gateway_chat_payload()` for top-level body field.
4. Ensure the same `request_id` appears in both the body AND the header (set `extra_headers["X-Request-ID"] = request_id` if not already present).

This guarantees a single canonical ID flows through header and body. Dashed UUID format (`str(uuid.uuid4())`) matches gateway's default (`server.py:556`).

Log `request_id` in any request-lifecycle log (correlates proxy logs with gateway ledger).

**Change 3 — Structured error inspection on non-200 responses.**

Replace the current blanket `if upstream_response.status_code == 401: force_refresh + retry` with a structured helper `_classify_upstream_error(response_body_bytes)` that returns one of:
- `"session_expired"` — retry with `force_refresh=True` (current behavior, now only for this case)
- `"auth_expired"` — invalidate session, re-init, retry once (NEW)
- `"cross_user_reuse"` — surface 401 to client immediately, no retry (NEW guard)
- `"missing_user_id"` — surface 400 to client immediately, no retry (indicates a bug in our payload construction)
- `"strict_mode_default_user"` — surface 400 to client, log as bug
- `"credentials_unavailable"` / `"credentials_timeout"` — surface 401/504 to client, friendly error message
- `"unknown"` — default fall-through, current behavior (pass upstream body + status through)

Implementation:
```python
async def _classify_upstream_error(response: httpx.Response) -> tuple[str, dict | None]:
    body_bytes = await response.aread()
    try:
        body = json.loads(body_bytes)
    except (ValueError, TypeError):
        body = None
    if isinstance(body, dict):
        error_code = body.get("error")
        if error_code in {
            "auth_expired",
            "cross_user_reuse",
            "missing_user_id",
            "strict_mode_default_user",
            "credentials_unavailable",
            "credentials_timeout",
        }:
            return error_code, body
    # Fallback: untyped 401 (current production behavior) = session expired
    if response.status_code == 401:
        return "session_expired", body
    return "unknown", body
```

Retry decision tree with per-error-type flags (**Codex R1+R2 fix**):

Per-error-type flags (**Codex R2 fix: single canonical model**):

State:
```python
session_expired_retried = False
auth_expired_retried = False
```

On non-200 from `/chat`:
1. Classify error via `_classify_upstream_error()`.
2. If `session_expired` AND NOT `session_expired_retried` → set flag, force_refresh token, retry.
3. If `auth_expired` AND NOT `auth_expired_retried` → set flag, invalidate token, get_token(force_refresh=True), retry.
4. Otherwise (non-retryable error, OR already retried for this type) → surface to client.

Sends:
- **Pure same-error:** initial → 1 retry → give up. **2 sends max.**
- **Mixed path:** initial → retry 1 (type A) → retry 2 (type B) → give up. **3 sends max.**
- **Non-retryable:** initial → give up. **1 send.**

Each retry must close the previous `upstream_response` before opening a new one.

**Change 4 — Stream-level `auth_expired` detection.**

The gateway may emit `auth_expired` either:
- Pre-stream: non-200 HTTP response with JSON body (handled by Change 3)
- Mid-stream: SSE data event `data: {"type":"error","error":"auth_expired",...}\n\n` (current speculation — finance_cli hasn't implemented the gateway side yet, so this is forward-compatible)

For mid-stream detection: this is harder because SSE chunks are forwarded as raw bytes. Options:
- (a) Parse SSE events in the proxy, detect `auth_expired`, emit a custom "retry" signal — **complex**, requires SSE parser, breaks transparent forwarding.
- (b) Let the client (frontend) detect mid-stream `auth_expired` events and retry via a fresh request — **simpler**, aligns with existing frontend error-event mapping in `GatewayClaudeService.ts`.
- **Decision: (b) for Phase 1.4.** Document mid-stream detection as "client-side" and defer any frontend work. In practice, the proxy's Change 3 handles the most common case (Anthropic 401 on first provider call → non-200 before the stream opens). Mid-stream 401s are rare and a degraded-but-functional failure is acceptable in Phase 1.4. If this becomes a problem in staging validation, add proxy-side SSE parsing in a follow-up.

**Change 5 — `gateway_tool_approval()` — no change needed.**

`lookup_token(user_key)` signature is unchanged (per BLOCKER 1 fix). Existing call works as-is.

**Change 6 — Disconnect-path invalidation — no change needed.**

`invalidate_token(user_key)` signature is unchanged (per BLOCKER 1 fix). Existing call works as-is.

### 4.4 `routes/gateway_proxy.py`

**No change.** This file is a thin shim that constructs `GatewayConfig` and calls `create_gateway_router`. All logic lives in `app_platform/gateway/proxy.py`.

### 4.5 `app_platform/gateway/__init__.py`

No change unless a new exportable symbol is introduced. None is.

---

## 5. Test plan

All tests live in `tests/app_platform/test_gateway_session.py` and `tests/test_gateway_proxy.py`. Existing tests (16 + 6 = 22) must pass unchanged; new tests are additive.

### 5.1 Session manager tests (`test_gateway_session.py`) — add

- **test_consumer_hash_mismatch_forces_refresh**: Create session for `user-1` with `api_key_fn → "key-A"`. Change `api_key_fn → "key-B"`. Call `get_token("user-1", ...)` again → triggers a NEW init call (hash mismatch detected). Assert: new token returned, stored hash updated.
- **test_consumer_hash_match_reuses_token**: Same key → no re-init. Assert: same token returned, 1 init call total.
- **test_initialize_session_sends_user_id_top_level**: Assert the POST body to `/api/chat/init` contains `{"api_key": ..., "user_id": "user-1"}`. Test both with `user_id=None` (omitted) and with value.
- **test_init_structured_error_credentials_unavailable**: Mock gateway returns 401 `{"error": "credentials_unavailable", "user_id": "u1"}` from `/chat/init`. Assert: HTTPException raised with status 401, detail contains upstream error body.
- **test_init_structured_error_credentials_timeout**: Mock gateway returns 504 `{"error": "credentials_timeout", "timeout_seconds": 5.0}` from `/chat/init`. Assert: HTTPException with 504.
- **test_init_structured_error_strict_mode**: Mock gateway returns 400 `{"error": "strict_mode_default_user"}` from `/chat/init`. Assert: HTTPException with 400.
- **test_init_unstructured_error_falls_back_502**: Mock gateway returns 500 with non-JSON body. Assert: HTTPException with 502 (current behavior preserved).

### 5.2 Proxy tests (`test_gateway_proxy.py`) — add

- **test_chat_payload_sends_user_id_top_level**: Captured upstream `/api/chat` request has `body["user_id"] == "101"` (from the mocked authenticated user) AND `body.get("context", {}).get("user_id") == "101"` (backward compat). And `body["request_id"]` is a UUID string with dashes (36 chars).
- **test_chat_request_id_reuses_factory_header**: Configure `request_headers_factory` that returns `{"X-Request-ID": "factory-123"}`. Assert: upstream body `request_id == "factory-123"` AND upstream header `X-Request-ID == "factory-123"`. Verifies factory-injected ID wins over generated UUID.
- **test_chat_request_id_reuses_incoming_header**: Send incoming request with `X-Request-ID: incoming-456`, no factory. Assert: upstream body `request_id == "incoming-456"` AND upstream header `X-Request-ID == "incoming-456"`.
- **test_chat_request_id_generates_when_absent**: No factory, no incoming header. Assert: upstream body `request_id` is a valid UUID with dashes AND upstream header `X-Request-ID` matches the same value.
- **test_chat_auth_expired_triggers_reinit_and_retry**: Mock gateway returns 401 with `{"error": "auth_expired", "user_id": "101"}` on first `/api/chat` call; returns 200 SSE on second. Assert: 2 `/api/chat/init` calls (original + re-init), 2 `/api/chat` calls, stream delivered cleanly.
- **test_chat_auth_expired_exhausts_retry_gives_up**: Gateway returns auth_expired on BOTH `/api/chat` attempts → proxy surfaces the 401 body to client after the 2nd send (per-type flag prevents further retry). No infinite loop.
- **test_chat_cross_user_reuse_does_not_retry**: Gateway returns 401 with `{"error": "cross_user_reuse", "session_user": "alice", "request_user": "bob"}`. Assert: one `/api/chat` call only (no retry), client receives 401 response with body passed through.
- **test_chat_strict_mode_default_user_surfaces**: Gateway returns 400 `{"error": "strict_mode_default_user"}`. Assert: no retry, client gets 400 pass-through.
- **test_chat_session_expired_still_retries**: Gateway returns 401 with `{}` (no error field, untyped 401). Assert: proxy treats as session_expired, forces refresh, retries. Preserves existing `test_proxy_chat_refreshes_token_on_401` behavior under the new dispatch.
- **test_chat_mixed_retry_session_then_auth_expired**: Gateway returns untyped 401 (session_expired) on first `/chat`, then `{"error": "auth_expired"}` on second `/chat`, then 200 SSE on third. Assert: 3 total `/chat` sends (1 initial + 1 session retry + 1 auth retry), stream delivered.
- **test_chat_same_error_twice_stops_after_one_retry**: Gateway returns session_expired on BOTH `/chat` attempts. Assert: exactly 2 `/chat` sends (per-type flag stops after 1 retry), client receives last error. No spin.
- **test_tool_approval_lookup_unchanged_signature**: Verify `lookup_token(user_key)` still works with raw user_key (no api_key_fn required). Tool approval finds the cached token for the correct user. Parallel to existing `test_proxy_approval_uses_same_session_token`.

### 5.3 Regression sweep — ALL gateway test files (**Codex R1 fix: full enumeration**)

Verify these tests STILL pass without modification (or minimal adjustment for new kwargs):

| File | Tests | Key concern |
|---|---|---|
| `tests/test_gateway_proxy.py` | 16 | Bulk of proxy integration tests. May need `user_id` kwarg on init mock. |
| `tests/app_platform/test_gateway_session.py` | 6 | Session manager unit tests. May need kwarg updates. |
| `tests/app_platform/test_gateway_proxy.py` | varies | App-platform-level proxy tests. Check payload assertions. |
| `tests/app_platform/test_gateway_models.py` | varies | Model tests — likely unaffected. |
| `tests/app_platform/test_shim_gateway.py` | varies | Shim assertions — check payload shape, env var handling. |
| `app_platform/gateway/tests/test_proxy.py` | 3 | In-package proxy tests. `test_disconnect_during_stalled_stream` uses `invalidate_token(user_key)` directly — must still work with unchanged signature. |
| `app_platform/gateway/tests/test_session.py` | 1 | `test_invalidate_token_removes_cached_token` — calls `invalidate_token("user-1")` and `lookup_token("user-1")` with raw user_key. Must pass unchanged (no signature change per BLOCKER 1 fix). |

Expected adjustments: any test that mocks `_initialize_session` directly must accept the new `user_id` kwarg. Signature of `invalidate_token`/`lookup_token` is UNCHANGED (per BLOCKER 1 fix), so those call sites need no update.

**Finance-web coordination note:** finance-web (`finance_cli/finance-web/`) also uses `app_platform.gateway` via PyPI. After publishing `app-platform` with these changes:
- `settings_router.py:222` and `deletion_cleanup.py:144` call `invalidate_token(user_key)` — unchanged signature, no breakage. ✓
- `test_web_chat_proxy.py:129` has exact payload assertions — verify `user_id` and `request_id` top-level fields don't cause assertion failures. If finance-web's mock gateway doesn't expect these new fields, tests may need updating in finance_cli. Document this as a downstream coordination item in the PR description.

### 5.4 Negative grep check

Add a one-line CI-grep (informal — can be a comment in the test file for now, Codex reviewer can elevate if desired):
> "If this grep starts matching, the proxy has started scraping billing events and must stop."
> `grep -rn "stream_complete" app_platform/gateway/proxy.py` → should return zero matches.

---

## 6. Implementation order

1. **Session manager changes** first (Changes 1–3 from §4.1 — consumer-hash metadata, user_id threading, init structured errors). Land + test in isolation.
2. **Proxy payload changes** next (Changes 1, 2 from §4.3 — user_id/request_id top-level plumbing). Land + test.
3. **Structured error inspection on /chat** (Change 3 from §4.3 — `_classify_upstream_error()` helper). Land + test.
4. **Retry logic** glued to the structured error classifier (per-error-type flags from §4.3). Land + test.
5. **Regression sweep** — re-run ALL gateway test files (7 suites per §5.3 table).

Each step is a separate commit. Commit messages follow the pattern: `gateway(multi-user): <scope>` for consistency with recent gateway commits.

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| `app_platform.gateway` is shared with finance-web via PyPI — breaking change cascades. | All changes are additive. Non-strict mode (current finance-web prod state) is unchanged. Publish as `app-platform` minor version bump post-merge. |
| Mid-stream `auth_expired` not handled → degraded UX if gateway starts emitting it. | Deferred to follow-up (per §4.3 Change 4 decision). Pre-stream case covered. Documented as known limitation. |
| Gateway `auth_expired` contract not yet implemented gateway-side. | We implement consumer-side forward-compatibly. Unit tests use mocked error bodies. When gateway lands it, risk_module is ready. No runtime dependency. |
| GATEWAY_API_KEY rotation during live request in flight. | Metadata-based detection: `get_token()` forces refresh on hash mismatch. In-flight request continues on old token until stream ends. No corruption. |
| Request ID format mismatch with gateway default. | Using `str(uuid.uuid4())` (dashed format), matching gateway's default. Reuse `X-Request-ID` header if present. |
| `_initialize_session()` test fixtures break on new `user_id` kwarg. | Kwarg is `user_id: str | None = None` — existing callers that don't pass it get `None` (backward compat). Adjust only tests that assert on the POST body shape. |
| Finance-web payload assertions break on new top-level fields. | Document as downstream coordination item in PR. `invalidate_token`/`lookup_token` signatures are unchanged — no runtime breakage. |

---

## 8. Out of scope (explicit)

- Gateway-service-side work (resolver, usage ledger, BYOK storage, etc.) — lives in finance_cli
- Frontend changes
- Database schema migrations
- New API endpoints (BYOK CRUD, etc.)
- Mid-stream `auth_expired` SSE parsing
- PyPI publish of `app-platform` (separate follow-up per `scripts/publish_app_platform.sh`)
- End-to-end staging validation against a live strict-mode gateway (documented manual gate, not automated)

---

## 9. Success criteria

- All tests in §5 pass (existing + new).
- `wc -l app_platform/gateway/session.py` + `app_platform/gateway/proxy.py` diff ≈ +150 lines net.
- Codex review PASS within ≤5 rounds.
- Manual smoke: with `GATEWAY_URL` pointed at a strict-mode gateway + resolver-provisioned user, analyst chat works end-to-end.
- No regression in finance-web when `app-platform` ships (verified by finance-web test suite post-publish).
