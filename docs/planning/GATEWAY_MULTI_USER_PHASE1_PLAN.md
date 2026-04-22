---
name: Gateway Multi-User Phase 1 — Per-User Credential Resolution (Option D)
status: APPROVED v9 — Codex PASS at R9 (2026-04-16) after 8 rounds. R9 nits folded in (test split, internal helper for 3-state, `utils/gateway_context` module to avoid circular import). Ready for implementation.
tracks: TODO §Lane G → 6M (gateway credentials_resolver wiring) + 6N (portfolio-mcp user_id threading — requires real MCP identity propagation work) + 6O (credential redaction — bundled per Codex R1)
depends_on:
  - finance_cli Phase 1.3 (validated 2026-04)
  - risk_module gateway proxy Phase 1.4 (7b407b5d) — already handles auth_expired retry
  - AI-excel-addin gateway package Phase 1.1 + 1.2 (2323094)
---

## Context

Today the risk_module web chat proxies into AI-excel-addin's gateway (`:8000`) which is configured in single-operator mode: one env-var Anthropic credential (`ANTHROPIC_AUTH_TOKEN`) serves every user. Every web user's LLM usage bills to Henry's key with no attribution, no quotas, no BYOK option, and no per-user auth-expired recovery. The `GatewayServerConfig` at `AI-excel-addin/api/main.py:283` has no `credentials_resolver` configured, so the gateway runs in non-strict fallback mode (`user_id="_default"`) and the cross-user isolation features shipped in gateway Phase 1.1/1.2 are dormant.

This is the single remaining blocker before multi-user launch on the LLM billing / identity axis. 6N (portfolio-mcp user_id threading) collapses into this work because once the gateway is strict-mode and routing `user_id` per request, portfolio-mcp can read it from the tool call context instead of `RISK_MODULE_USER_EMAIL` env var.

### Architecture chosen: Option D — HTTP-callback resolver

The AI-excel-addin gateway is the agent host. The agent layer (`api/agent/`, `api/skills/`, `api/memory/`, `api/tool_registry.py`, prompts, hooks, channel registry, sub-agent wiring) lives in AI-excel-addin. Extracting it into a shared package to let risk_module stand up its own gateway is a multi-week refactor out of scope here. Instead:

- AI-excel-addin's gateway gains a `credentials_resolver` that dispatches by **the authenticated gateway API key** (`payload.api_key` on `ChatInitRequest`), NOT by client-supplied `context["channel"]`. Rationale (Codex R1 P1 #3): a client-advertised channel is trivially spoofable — a compromised consumer could label itself "excel" and grab operator creds. Binding dispatch to `payload.api_key` uses the gateway's existing consumer→gateway authentication surface (`valid_api_keys`) so the consumer class is authenticated, not advertised. `context["channel"]` stays as optional supplemental telemetry, never as an authorization signal.
- We register one gateway API key per consumer class:
  - `GATEWAY_API_KEY_EXCEL` → operator env-var credential
  - `GATEWAY_API_KEY_TELEGRAM` → operator env-var credential
  - `GATEWAY_API_KEY_WEB` → HTTP callback to risk_module
- Resolver derives consumer class from an in-memory `api_key_hash → channel` map built at gateway startup from those env vars. Unknown key hash → reject at `/chat/init` (gateway already rejects unknown keys; this adds the dispatch lookup).
- For web channel: resolver makes an HTTP callback to risk_module `/api/internal/resolve-credential`. Auth is HMAC-signed payload with timestamp (freshness-bounded, NOT replay-prevented — loopback/same-host deploy assumed; see §3 threat-model) plus private-network-only exposure.
- risk_module owns its user credential storage end-to-end. AI-excel-addin owns the agent brain.
- Gateway caches the resolved credential for the session lifetime (Phase 1.1 behavior), so the HTTP callback fires once per session-init, not per turn.

This keeps current deploy topology (one gateway, one agent brain) while making the credential plane per-user AND binding consumer identity to the authenticated API key surface.

### Reference implementations

- finance_cli resolver pattern: `finance_cli/gateway/server.py:266-348` (`_make_credentials_resolver`) — the DB+Secrets Manager lookup template this work mirrors for risk_module.
- AWS Secrets Manager helpers: `risk_module/brokerage/snaptrade/secrets.py:82-230` — the soft-delete-restore pattern mirrored for Anthropic key storage.
- Gateway design doc (source of truth): `AI-excel-addin/docs/design/gateway-multi-user-task.md` §2 (credentials_resolver callback), §"Strict mode", §"OAuth expiry".
- Consumer migration spec: `AI-excel-addin/docs/design/gateway-multi-user-task.md` Phase 1.4 acceptance gates.

---

## Goals

1. **Per-user Anthropic credential routing** for risk_module users. BYOK users supply their own key; users without a key get a structured `no_credential` error that the UI turns into "add your key" prompt. Metered/commercial tier fallback is Phase 2.
2. **Strict-mode enforcement**: gateway rejects `_default` user_id, enforces `user_id` on every `/chat`, enforces `(consumer_token, end_user_id)` session keying.
3. **No cross-repo coupling of user DBs**. AI-excel-addin gateway never reaches into risk_module's Postgres. Resolution is a signed HTTP callback.
4. **Zero-breakage on single-operator paths** (excel taskpane, Telegram bot). They continue to use the operator env-var credential after sending `channel` + `user_id` on init.
5. **Auth-expired recovery path works end-to-end** (design doc requirement for Phase 1.4 acceptance). Consumer sees structured `auth_expired` error, re-inits session, retries the user's last message.
6. **6N — portfolio-mcp per-user identity** (real work, NOT a side effect — see §7): extend gateway's MCP dispatcher to inject `user_id` via MCP protocol-level `meta` (FastMCP-compatible transport), and update portfolio-mcp's FastMCP middleware to read it + translate DB id → email into a ContextVar read by existing email-keyed internals. Without this, strict-mode credentials ship but every user still sees Henry's portfolio.
7. **6O — credential redaction** (bundled, NOT deferred — see §8): gateway `str(exc)` / `repr(exc)` paths get a redaction filter before emitting to client SSE streams or logs.

## Non-goals (explicit, defer to follow-up plans)

1. **Metered/commercial billing tier**. Phase 2 — usage ledger persistence, Stripe wiring, commercial API key pool. This plan only adds the `billing_mode` field to resolved credentials so the hook is in place.
2. **BYOK key validation at save time**. We don't call Anthropic to verify the key works when the user saves it. User sees the error on first chat turn. Phase 2 adds a test-call.
3. **Per-user memory** (AI-excel-addin memory store stays singleton — deferred per design doc T2).
4. **risk_module standing up its own gateway instance** (Option A — deferred indefinitely, explicitly rejected in favor of D).
5. **Agent-layer extraction into a shared package** (Option A' — deferred indefinitely).
6. **Rotating the shared resolver secret** automatically. Manual env-var rotation with coordinated restart is acceptable.
7. **PostgreSQL RLS** (separate security plan in `TODO §Security`).

---

## Design

### Topology after this plan

```
User → risk_module frontend (:3000)
     → risk_module backend (:5001)
         ├─ POST /api/gateway/chat → proxy (unchanged, already Phase 1.4) ─┐
         └─ POST /api/internal/resolve-credential ←── HMAC-signed ◄───┐    │
              (bound to private iface / loopback)                     │    │
                                                                      │    │
AI-excel-addin gateway (:8000)                                        │    │
  startup: build api_key_hash → channel map from env vars             │    │
  credentials_resolver(user_id, init_request):                        │    │
    channel = channel_for(hash(init_request.api_key))                 │    │
    if channel in {"excel", "telegram"}:                              │    │
      return AuthConfig.from_dict(operator_env_config) ───────────────┘    │
    elif channel == "web":                                                 │
      return await signed_http_call(risk_module_resolver_url, ...) ────────┘
    else:
      raise ValueError(f"unknown channel for api_key_hash")
```

**Key property** (per Codex R1): channel is server-derived from the authenticated API key. `context["channel"]` is ignored for authorization; it exists only as telemetry.

### 1. risk_module schema migration

Add three columns to `users` table:

```sql
ALTER TABLE users ADD COLUMN anthropic_api_key_secret_ref TEXT;
ALTER TABLE users ADD COLUMN anthropic_api_key_enc TEXT;
ALTER TABLE users ADD COLUMN anthropic_credential_source TEXT
  NOT NULL DEFAULT 'none'
  CHECK (anthropic_credential_source IN ('none', 'byok', 'metered'));
```

- `anthropic_api_key_secret_ref` — AWS Secrets Manager key path. Primary path for production (secrets in Secrets Manager, not DB).
- `anthropic_api_key_enc` — encrypted-at-rest blob (SESSION_SECRET symmetric encryption). Fallback for dev / environments without Secrets Manager access.
- `anthropic_credential_source` — cheap discriminator avoiding a Secrets-Manager call to check existence. `none` = no key, `byok` = user-provided, `metered` = placeholder for Phase 2 commercial tier.

Migration file: `database/migrations/NNNN_anthropic_credential_columns.sql`. Follows the existing migration pattern in `database/migrations/`.

### 2. Crypto + storage helpers (risk_module)

**Encryption-key provenance** (Codex R1 P1 #5):
- Production path: **AWS Secrets Manager is the only credential store.** DB-encrypted fallback is **disabled by env flag in prod** (`ALLOW_DB_CRED_FALLBACK=false`). If Secrets Manager write fails on `store`, the save operation fails and surfaces to the user — NOT silently degraded.
- Dev/test path: `ALLOW_DB_CRED_FALLBACK=true` enables the encrypted-DB fallback using a **dedicated** symmetric key, `ANTHROPIC_CRED_ENCRYPTION_KEY` (base64 Fernet key). This key has no other purpose — never reuse `FLASK_SECRET_KEY` (session cookies), never reuse `SESSION_SECRET` (doesn't exist in this app), never reuse `JWT_SECRET`. Separate keys means a compromise of one doesn't widen to the others.
- The dev key is generated once (`cryptography.fernet.Fernet.generate_key()`) and stored in `.env` for local dev. Rotation = manual re-encrypt migration (one-off script, not Phase 1 scope).

New module `services/anthropic_credential_store.py`:

```python
def store_user_anthropic_key(user_id: int, raw_key: str, db: DatabaseClient) -> None:
    """
    1. Attempt Secrets Manager write at `anthropic/api_key/{user_id}` (SnapTrade pattern).
    2. On Secrets Manager failure:
       - If ALLOW_DB_CRED_FALLBACK=true (dev): encrypt with ANTHROPIC_CRED_ENCRYPTION_KEY,
         write to users.anthropic_api_key_enc.
       - Else (prod): raise StorageError — do NOT silently degrade to DB.
    3. Update users row: set anthropic_api_key_secret_ref (or anthropic_api_key_enc),
       anthropic_credential_source='byok', anthropic_credential_updated_at=now.
    """

def get_user_anthropic_key(user_id: int, db: DatabaseClient) -> str | None:
    """
    1. Read users row.
    2. If secret_ref is set: fetch from Secrets Manager. On 503 / BotoCoreError, raise
       ResolverTransientError (distinct from "no key"). Do NOT fall back to DB here.
    3. Else if enc is set AND ALLOW_DB_CRED_FALLBACK=true: decrypt with
       ANTHROPIC_CRED_ENCRYPTION_KEY. On decrypt failure, log + return None (corruption
       is indistinguishable from "no key" from the caller's perspective, but we log).
    4. Else: return None.
    """

def delete_user_anthropic_key(user_id: int, db: DatabaseClient) -> None:
    """
    1. Soft-delete from Secrets Manager (recovery window per SnapTrade pattern).
    2. Null out users row columns, set source='none'. Idempotent — second call is a no-op.
    """
```

- Mirrors `brokerage/snaptrade/secrets.py` pattern exactly (`create_secret`→`put_secret_value`→`restore_secret` sequence).
- Crypto: `cryptography.fernet.Fernet` keyed by `ANTHROPIC_CRED_ENCRYPTION_KEY` env var. Module loads the key once at import and caches the Fernet instance.
- Prod deploy gate: assert `ALLOW_DB_CRED_FALLBACK=false` AND Secrets Manager reachable at startup. Fail-closed if Secrets Manager is unreachable on boot in prod.

### 3. Resolver endpoint (risk_module) — hardened per Codex R1 P1 #4

New route `routes/internal_resolver.py` mounted at `/api/internal/resolve-credential`.

**Network boundary** (required, not optional):
- Route binds to the internal interface only (`127.0.0.1` or a private VPC IP). Public-facing nginx/ALB does NOT proxy this path.
- Deploy config asserts this: ingress rules reject port-forwarded requests for `/api/internal/*` from public networks.
- In dev, binding to `127.0.0.1` is sufficient. In prod, VPC security group + ingress exclusion.

**Wire-level auth** (HMAC-signed, freshness-bounded):

Request headers:
```
X-Resolver-Timestamp: <unix_seconds>
X-Resolver-Signature: <hex(hmac_sha256(secret, f"{timestamp}\n{user_id}\n{consumer_key_hash}"))>
```

- Timestamp skew ±60s (rejected outside window — **freshness check, not replay prevention** per Codex R2 N #3).
- Signature uses a dedicated env var `GATEWAY_RESOLVER_HMAC_KEY` (distinct from JWT/session/encryption keys).
- Constant-time compare via `hmac.compare_digest`.
- Signed payload includes `consumer_key_hash` so a compromised secret on one consumer can't forge another's requests.

**Threat model + boundary requirements** (honest statement per Codex R2 N #3):

The HMAC + freshness check is sufficient when the resolver endpoint is **loopback-only** (gateway and risk_module backend on the same host). Same-host binding is the Phase 1 deployment target.

If this plan is ever deployed with gateway and risk_module on separate hosts:
- TLS (mutual or server-only with strong cert pinning) becomes mandatory.
- A replay nonce/dedupe store is required on the resolver side (e.g., Redis SET NX with 120s TTL keyed by signature hash). Without it, an attacker with wire capture can replay signed requests within the 60s window.
- Kubernetes NetworkPolicy / AWS security group rules enforce that only the gateway host can reach the endpoint.

Phase 1 deploys same-host → loopback-only binding is sufficient. Cross-host is a separate plan with its own review.

**Request shape** (Phase 1 scope — numeric DB id only per Codex R3/R4):
```python
class CredentialResolveRequest(BaseModel):
    user_id: str              # numeric DB users.id as a string (e.g., "42"). Non-numeric → 404.
    consumer_key_hash: str    # SHA256[:16] of the gateway API key that initiated (for audit)
    request_id: str           # trace ID from gateway, for log correlation
```

**Response shape** (matches gateway's `AuthConfig.from_dict()` contract):
```python
{
    "auth_config": {
        "provider": "anthropic",
        "billing_mode": "byok",
        "auth_mode": "oauth" | "api",   # set by _classify_credential
        "api_key": "..." | None,
        "auth_token": "..." | None,
        "model": "claude-sonnet-4-6",
        "max_tokens": 16000,
        "thinking": true,
    }
}
```

**Response outcomes** — distinct so the gateway can map to distinct error types (Codex R1 P1 #8):

| Outcome | Status | Body | Gateway maps to |
|---------|--------|------|-----------------|
| Key found | 200 | `{auth_config: {...}}` | `AuthConfig` returned |
| No key configured | 404 | `{error: "no_credential"}` | `NoCredentialError` (actionable "add your key") |
| Unknown user | 404 | `{error: "no_credential"}` | `NoCredentialError` — intentionally indistinguishable from "no key" (Codex R1 P1 #4, prevents user enumeration) |
| HMAC invalid / stale | 401 | `{error: "auth_failed"}` | `RuntimeError` (5xx to client, log + alert) |
| Secrets Manager down | 503 | `{error: "resolver_transient"}` | `RuntimeError` (5xx to client, distinguishable from NoCredentialError in logs — "resolver infrastructure down", NOT "add your key") |

**Normalized 404** is deliberate: unknown user and no-key-configured return identical bodies so the endpoint doesn't leak whether a user_id exists. Internal logs DO distinguish them for ops.

**User_id lookup strategy** (Codex R1 Open Q #5 → scope-cut per Codex R3 P1):

**Phase 1 scope cut — DB numeric id ONLY.** Accepting `google_user_id` too creates an ambiguity: Google's `sub` is often numeric (see `app_platform/auth/google.py:39`, `app_platform/auth/stores.py:127`), so `isdigit()`-based branching can't distinguish between "DB id 12345" and "Google sub 12345" reliably. Codex R3 P1 flagged this concretely.

**Resolver endpoint contract**: `user_id` MUST be the numeric DB `users.id`. Proxy's `_get_user_key()` priority already returns `str(user["user_id"])` (the DB id) first (`proxy.py:94-98`); non-id fallbacks (`google_user_id`, `email`) are defensive edge cases that only fire when the auth session is malformed.

**Proxy enforcement**: in the web channel (risk_module proxy), add an assertion at `_get_user_key()`: if `user["user_id"]` is None, raise 401 (invalid session) instead of falling through to google/email. This makes "DB id missing" a loud failure during session-init, not a silent resolver miss.

**Resolver endpoint query** (simple, deterministic):

```python
def resolve_user(user_id: str, cursor) -> dict | None:
    stripped = user_id.strip()
    if not stripped.isdigit():
        return None   # non-numeric → unknown (normalized 404)
    cursor.execute("SELECT * FROM users WHERE id = %s LIMIT 1", (int(stripped),))
    return cursor.fetchone()
```

One column, one type. No ambiguity.

**Follow-up scope** (Phase 2+): if there's ever a reviewed need to accept non-numeric user_ids, we add a typed user_id contract (e.g., prefixed strings `id:123`, `sub:abc`, `email:foo@bar.com`) with explicit type dispatch. Not Phase 1.

**Observability**:
- Log every resolution with: `request_id`, `user_id`, `consumer_key_hash[:8]`, outcome, latency_ms. NEVER log the resolved key.
- Metric: `resolver.outcomes{outcome, consumer}` counter.
- Metric: `resolver.latency_ms{consumer}` histogram.

### 4. Credential user-management endpoints (risk_module)

Public routes under `/api/user/anthropic-credential` (session-authed, same as other user routes):

- `GET  /api/user/anthropic-credential` → `{configured: bool, source: "none"|"byok", updated_at: iso8601}`
- `POST /api/user/anthropic-credential` → `{api_key: string}` (body), validates format, stores via `store_user_anthropic_key`
- `DELETE /api/user/anthropic-credential` → removes via `delete_user_anthropic_key`

Key format validation: starts with `sk-ant-` (either `sk-ant-api03-...` or `sk-ant-oat01-...`). Actual API validation deferred to Phase 2.

### 5. Frontend settings UI (risk_module)

New settings pane under existing settings view (likely `frontend/packages/ui/src/components/settings/` or peer — to confirm during implementation):

- "AI credential" section with single card
- States: "No key configured" (CTA "Add your key") / "Key configured ✓" (actions "Replace", "Remove")
- On save: POST endpoint, show success/error toast, never echo the key back
- Copy: short explanation that without a key, chat is unavailable until one is added
- Link out: "Get an Anthropic API key →" pointing to anthropic.com console

This is the first user-facing step — design needs a quick pass but copy + interaction are straightforward. Full BYOK onboarding flow (in-chat prompt when first hit) is Phase 2.

### 6. AI-excel-addin resolver + consumer threading

#### 6a. Resolver module

New file `api/credentials_resolver.py`:

```python
def make_credentials_resolver(
    operator_auth_config: dict,
    api_key_to_channel: dict[str, str],   # sha256_hash -> "excel"|"telegram"|"web"
    risk_module_resolver_url: str,
    resolver_hmac_key: str,
    http_timeout_seconds: float = 3.0,
) -> CredentialsResolver:
    """
    Build a resolver that dispatches by AUTHENTICATED API KEY (server-side, not client hint).
    - api_key hashes to operator channel (excel/telegram) -> return operator_auth_config.
    - api_key hashes to web channel -> HMAC-signed HTTP callback to risk_module.
    - unknown hash -> raise (gateway already rejects unknown keys, but defense-in-depth).
    """
```

**Dispatch flow** (Codex R1 P1 #3):

```python
async def _resolve(user_id: str, init_request: ChatInitRequest) -> AuthConfig:
    # Gateway validates init_request.api_key is in valid_api_keys before calling us.
    # We look up channel from the authenticated key hash — NOT from init_request.context.
    key_hash = hashlib.sha256(init_request.api_key.encode()).hexdigest()
    channel = api_key_to_channel.get(key_hash)
    if channel is None:
        # Defensive: should be unreachable because gateway rejected unknown keys first.
        raise RuntimeError("unknown consumer — no channel mapping")
    if channel in ("excel", "telegram"):
        return AuthConfig.from_dict({**operator_auth_config, "billing_mode": "byok"})
    if channel == "web":
        return await _resolve_web(user_id, key_hash, init_request.request_id or "")
    raise RuntimeError(f"unconfigured channel: {channel!r}")
```

**Web-path error mapping** (Codex R1 P1 #8 — distinguish "no key" from "resolver down"):

| HTTP response | Gateway maps to | User-facing UX |
|---------------|-----------------|----------------|
| 200 + auth_config | `AuthConfig` | chat proceeds |
| 404 `no_credential` | `NoCredentialError("configure an Anthropic key in settings")` | "add your key" card |
| 401 `auth_failed` | `RuntimeError` — logs HMAC mismatch, alerts ops | generic 5xx "chat temporarily unavailable" |
| 503 `resolver_transient` | `RuntimeError` — logs "risk_module resolver/secrets down" | generic 5xx "chat temporarily unavailable" |
| httpx timeout | `CredentialsTimeoutError` (gateway contract) | generic 5xx "chat temporarily unavailable" |
| other / 5xx | `RuntimeError` | generic 5xx |

Only `NoCredentialError` surfaces as actionable user UX. Infrastructure failures NEVER resolve as "add your key."

**Boundary hygiene** (Codex R1 P1 #9 — credential redaction bundled, 6O collapse):
- Web-path HTTP errors are caught with a redaction wrapper. The raw exception is logged (internal log only, severity ERROR) and a fixed sanitized error code is raised for the gateway. Gateway's `str(exc)` path at `server.py:337` only ever sees whitelisted sanitized messages.
- The resolver module never puts the resolved credential in exception messages. Log lines log `user_id`, `channel`, `outcome`, `latency_ms` only — never `api_key`, `auth_token`, or the raw response body.
- Add module-level `logging.Filter` that rejects any log record whose message matches patterns like `sk-ant-*`, `Bearer *`, or `"auth_token":` — defense-in-depth against accidental inclusion elsewhere. Gateway `runner.py:50` `_format_exc()` wrapped by the same filter (this is the 6O fix).

#### 6b. Wire into GatewayServerConfig

In `api/main.py:283`:

```python
# Build api_key → channel mapping from dedicated env vars.
# Keep both the raw keys (for gateway's valid_api_keys check at /chat/init)
# AND the hash→channel map (for resolver dispatch).
_dedicated_keys: dict[str, str] = {}           # raw_key -> channel
_api_key_hash_to_channel: dict[str, str] = {}  # sha256(raw_key) -> channel
for env, channel in [
    ("GATEWAY_API_KEY_EXCEL", "excel"),
    ("GATEWAY_API_KEY_TELEGRAM", "telegram"),
    ("GATEWAY_API_KEY_WEB", "web"),
]:
    key = os.getenv(env, "").strip()
    if key:
        _dedicated_keys[key] = channel
        _api_key_hash_to_channel[hashlib.sha256(key.encode()).hexdigest()] = channel

# Legacy single-key support for the dual-accept cutover window (see Phase 8).
# During cutover, gateway accepts BOTH the old shared key AND the new dedicated keys.
# The legacy key inherits the "web" channel by default (the consumer most sensitive to
# cross-user isolation — risk_module backend). Operators migrate Excel/Telegram to
# dedicated keys before enabling web strict mode.
_legacy_shared_key = os.getenv("GATEWAY_API_KEY_LEGACY", "").strip()
if _legacy_shared_key:
    _dedicated_keys.setdefault(_legacy_shared_key, os.getenv("GATEWAY_LEGACY_CHANNEL", "web"))
    _api_key_hash_to_channel.setdefault(
        hashlib.sha256(_legacy_shared_key.encode()).hexdigest(),
        os.getenv("GATEWAY_LEGACY_CHANNEL", "web"),
    )

_risk_module_resolver_url = os.getenv("RISK_MODULE_RESOLVER_URL", "").strip()
_resolver_hmac_key = os.getenv("GATEWAY_RESOLVER_HMAC_KEY", "").strip()

_credentials_resolver = None
if _api_key_hash_to_channel and _risk_module_resolver_url and _resolver_hmac_key:
    _credentials_resolver = make_credentials_resolver(
        operator_auth_config=get_provider_config(),
        api_key_to_channel=_api_key_hash_to_channel,
        risk_module_resolver_url=_risk_module_resolver_url,
        resolver_hmac_key=_resolver_hmac_key,
        http_timeout_seconds=float(os.getenv("RESOLVER_TIMEOUT", "3.0")),
    )

# valid_api_keys is ALWAYS the raw key set (what consumers actually send).
# When resolver is active, it's the union of dedicated keys + any legacy key.
# When resolver inactive, fall back to existing single-key behavior.
_valid_api_keys = (
    set(_dedicated_keys.keys())
    if _dedicated_keys
    else _existing_single_key_set   # preserved pre-plan behavior when keys unset
)

_gateway_config = GatewayServerConfig(
    ...existing kwargs...,
    valid_api_keys=_valid_api_keys,
    credentials_resolver=_credentials_resolver,
    resolver_timeout_seconds=5.0,
)
```

**Fix per Codex R2 P0 #1**: `valid_api_keys` is the set of raw keys consumers actually send, NOT the set of channel labels. Earlier draft conflated the two and would have rejected all real API keys at `/chat/init`. Corrected structure separates `_dedicated_keys` (raw → channel) from `_api_key_hash_to_channel` (hash → channel, used only by resolver dispatch).

**Critical fix per Codex R3 P0** — `valid_api_keys` on `GatewayServerConfig` is IGNORED when `auth_manager` is supplied (`packages/agent-gateway/agent_gateway/server.py:451`). AI-excel-addin supplies `auth_manager=_AUTH` at `api/main.py:283`, and `_AUTH` is built at `api/auth.py:17` with `valid_keys=_VALID_KEYS` where `_VALID_KEYS` comes from the `CHAT_VALID_KEYS` env var only. **The v3 config snippet alone doesn't actually change admission control.**

The real fix is TWO changes:

(a) Update `api/auth.py:10-17` to union the dedicated + legacy keys into `_VALID_KEYS`:

```python
# api/auth.py (updated)
_CHAT_VALID_KEYS = {
    key.strip()
    for key in os.getenv("CHAT_VALID_KEYS", "").strip().split(",")
    if key.strip()
}
# New: also include per-consumer dedicated keys and optional legacy key.
_DEDICATED_KEYS = {
    os.getenv(env, "").strip()
    for env in (
        "GATEWAY_API_KEY_EXCEL",
        "GATEWAY_API_KEY_TELEGRAM",
        "GATEWAY_API_KEY_WEB",
        "GATEWAY_API_KEY_LEGACY",
    )
}
_DEDICATED_KEYS.discard("")

_VALID_KEYS = _CHAT_VALID_KEYS | _DEDICATED_KEYS

SESSION_STORE = SessionStore(ttl=_SESSION_TTL)
_AUTH = AuthManager(secret=_JWT_SECRET, valid_keys=_VALID_KEYS, session_store=SESSION_STORE)
```

This is the authoritative admission change — `_AUTH.valid_keys` now contains the dedicated keys, so `/chat/init` accepts them.

(b) `api/main.py:283` passes the same hash-map into `GatewayServerConfig.credentials_resolver` so dispatch works as described above.

(c) `valid_api_keys=_valid_api_keys` in the `GatewayServerConfig` call is redundant (ignored when auth_manager is set), but left for OSS/documentation clarity — a consumer using `create_gateway_app` WITHOUT a custom `auth_manager` would rely on it. Add a comment noting this.

**Dual-accept cutover support per Codex R2 P1 #1**: Added `GATEWAY_API_KEY_LEGACY` env var. During Phase 8 cutover, gateway accepts BOTH old shared key (for any consumer mid-migration) AND the new dedicated keys. The legacy key maps to a configurable channel (default `web`). After all consumers have migrated to dedicated keys, operator unsets `GATEWAY_API_KEY_LEGACY` and the old key is rejected.

**Backward compat** (Codex R1 N #11): resolver activation requires ALL THREE env groups (any dedicated api key, resolver URL, HMAC key). If any unset → `_credentials_resolver = None` → gateway runs in existing single-operator mode unchanged. This branch is covered by an explicit regression test (see Testing §Backward-compat).

#### 6c. Excel taskpane — thread user_id on init AND /chat

**Init** (`src/taskpane/services/ChatService.ts:24-26`):
```typescript
async initSession(apiKey: string, userId: string): Promise<ChatInitResponse> {
    return this.client.postJson<ChatInitResponse>("/api/chat/init", {
        api_key: apiKey,
        user_id: userId,                          // REQUIRED in strict mode
        context: { channel: "excel" },            // supplemental telemetry, not authorization
    });
}
```

**Every /chat call** (`src/taskpane/services/ChatService.ts:33` + `taskpane.ts:635` request builder — per Codex R1 P1 #7):
```typescript
// ChatRequest body
{
    session_id: "...",
    messages: [...],
    user_id: userId,                              // REQUIRED in strict mode
    context: { channel: "excel" },
    request_id: crypto.randomUUID(),              // recommended (see design doc §"request_id derivation")
}
```

**Operator identity**: taskpane reads `userId` from a new config value `CHAT_OPERATOR_USER_ID` (defaults to `"operator"`). Single-operator mode — same id every session. `tool-result` / `tool-approval` requests inherit user_id from the session token (gateway-bound), no changes there.

**auth_expired retry**: extend the `streamChat()` error handler in `ChatService.ts:33` to detect `{error: "auth_expired"}` in the SSE stream, re-call `initSession()`, and re-invoke `streamChat()` with the new session token and the last user message (held in caller memory). Single retry; second auth_expired in the same turn surfaces as an error.

#### 6d. Telegram bot — thread user_id on init AND /chat

**Init** (`telegram_bot/backend_client.py:153`) — `ensure_session` sends `user_id` derived from `chat_id`:
```python
response = await self._client.post(
    f"{self._backend_url}/api/chat/init",
    json={
        "api_key": self._chat_api_key,
        "user_id": f"tg:{chat_id}",               # stable per Telegram user
        "context": {"channel": "telegram"},
    },
)
```

**Every /chat call** (`telegram_bot/backend_client.py:207` — `stream_chat` payload builder):
```python
payload = {
    "messages": messages,
    "context": {**(context or {}), "channel": "telegram"},
    "user_id": f"tg:{chat_id}",                   # REQUIRED in strict mode
    "request_id": str(uuid.uuid4()),
}
```

**auth_expired retry**: extend `stream_chat()` error parsing to detect `auth_expired` and re-invoke `ensure_session(force_refresh=True)` then replay the message. Same single-retry pattern as Excel.

#### 6e. risk_module proxy — verify channel + no-op

`risk_module/app_platform/gateway/proxy.py:107-126` — verify during implementation that `context["channel"] = "web"` is set on both init and every `/chat`. The Phase 1.4 proxy sets `user_id` at line 116/123 but the channel constant needs explicit verification:
- At `_build_gateway_chat_payload` (line 106): add `upstream_context["channel"] = "web"` unconditionally.
- At session-init path: ensure `context["channel"] = "web"` is sent.

auth_expired retry ALREADY implemented at `proxy.py:281` (Codex R1 N #10 — Phase 6 is now verification-only, not new work).

### 7. portfolio-mcp user_id threading (6N — real work, NOT a side effect)

**Correction per Codex R1 P0 #1**: the assumption that "gateway passes user_id into tool context automatically" is wrong. Today the gateway only injects `_session_id` into MCP calls (`packages/agent-gateway/agent_gateway/tool_dispatcher.py:399-402`):

```python
if server and server in self._mcp_session_inject_servers:
    tool_input = {**tool_input, "_session_id": self._session_id}
```

`_user_id` is not injected. `portfolio-mcp/mcp_server.py:285` still reads identity from `RISK_MODULE_USER_EMAIL` env var via `utils/user_context.py:54`. **Without the changes in this phase, strict-mode credentials ship but portfolio tools still return Henry's data for every user.** This is the launch-blocker.

**Correction per Codex R4 P0**: injecting `_user_id` into `tool_input` (alongside `_session_id`) breaks FastMCP. Portfolio-mcp uses `@mcp.tool()` decorators with explicit function signatures (`mcp_server.py:307`), and FastMCP's `function_tool.py:240` rejects unexpected kwargs with `ValidationError: Unexpected keyword argument`. Adding `_user_id` to 83 tool signatures is invasive, and even then the LLM would see it in the tool schema unless we mark it specially.

**FastMCP-compatible transport** (verified empirically):

The MCP protocol supports a `meta` field in `tools/call` requests (`mcp.ClientSession.call_tool(..., meta=...)` — verified in MCP Python SDK). FastMCP exposes this server-side via `Context.request_context` and via `FastMCP.add_middleware()` (verified — both APIs exist in installed `fastmcp`). We use protocol-level metadata, NOT tool args, so:
- Tool signatures stay unchanged (no per-tool edits to portfolio-mcp's 83 tools).
- LLM doesn't see `user_id` in any tool schema (FastMCP's `parameters` schema excludes `Context` params and protocol metadata — verified).
- FastMCP signature validation passes (metadata is not an unexpected kwarg).

**Gateway changes** (AI-excel-addin + gateway package):

1. **Gateway package** — `mcp_client.py:279` `call_tool` signature gains `meta: dict[str, Any] | None = None` and forwards to `server.session.call_tool(..., meta=meta)` (the underlying `mcp.ClientSession.call_tool` accepts it). Minor gateway-package version bump.

2. **tool_dispatcher.py:399-402** — REMOVE the `tool_input`-merging of `_session_id` for servers where we now use `meta` instead, OR keep it but add meta in parallel. Recommended: migrate both `_session_id` and `_user_id` onto `meta` for consistency, behind a per-server `_mcp_meta_inject_servers` allowlist:
   ```python
   if server and server in self._mcp_meta_inject_servers:
       meta = {"session_id": self._session_id, "user_id": self._user_id}
       result, error = await self._mcp.call_tool(tool_name, tool_input, meta=meta)
   elif server and server in self._mcp_session_inject_servers:
       # Legacy path — old servers still reading from tool_input
       tool_input = {**tool_input, "_session_id": self._session_id}
       result, error = await self._mcp.call_tool(tool_name, tool_input)
   else:
       result, error = await self._mcp.call_tool(tool_name, tool_input)
   ```
   This keeps backward compat for any existing server still reading `_session_id` from args, while `portfolio-mcp` (which is ours) migrates to meta immediately.

3. `ToolDispatcher` gains a `_user_id` constructor arg threaded from `Session.user_id`. **Correction per Codex R6 P1**: the live app's dispatcher is built in `AI-excel-addin/api/agent/interactive/runtime.py:179` (NOT gateway-package `runner.py` — that's the OSS path). Sub-agent dispatchers are created in `api/agent/shared/tool_handlers.py:845` and `api/agent/shared/tool_handlers.py:956`. Both sites must be updated to pass `user_id` through at construction. Implementation checklist:
   - `interactive/runtime.py:179` — `ToolDispatcher(..., user_id=session.user_id)` at the main dispatcher construction
   - `interactive/runtime.py:439` — `run_agent` wiring, thread `user_id` parameter
   - `shared/tool_handlers.py:845` — sub-agent dispatcher construction, inherit parent `user_id`
   - `shared/tool_handlers.py:956` — second sub-agent dispatcher site, same
   - Gateway-package `sub_agent.py` `make_run_agent_handler` — extend same wiring pattern if any codepath uses it (currently unreferenced in live app but kept for OSS parity)

4. Fan-out invariant: every tool call originating from a strict-mode session, whether from the top-level dispatcher or a sub-agent dispatcher, must carry `meta.user_id`. Missing `meta.user_id` in strict mode → fail closed. Acceptance test simulates sub-agent fan-out (parent chat → sub-agent → portfolio-mcp tool) and asserts `user_id` propagates to the leaf MCP call.

**portfolio-mcp changes** (risk_module):

5. **New FastMCP middleware + DB-id→email bridge** (Codex R5 P0) — portfolio-mcp internals are email-centric today (`utils/user_context.py:89` `resolve_user_email()` returns email, `actions/context.py:21` + `utils/user_resolution.py:6` convert email → DB id, tools like `mcp_tools/connections.py:64` and `mcp_tools/positions.py:558` expect email). The gateway sends numeric DB id in `meta.user_id` per §3 Phase 1 scope. The middleware MUST translate before stashing:

   ```python
   from fastmcp.server.middleware import Middleware, MiddlewareContext
   import contextvars

   # Stash EMAIL (not DB id) — that's what all existing portfolio-mcp internals consume.
   _USER_EMAIL_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar(
       "mcp_user_email", default=None
   )
   # Separate flag: True iff we're inside a gateway-originated MCP request.
   # This lets resolve_user_email() distinguish "standalone dev" (env fallback OK)
   # from "gateway request where user lookup failed" (must fail closed).
   # Per Codex R8 P0.
   _GATEWAY_REQUEST_ACTIVE: contextvars.ContextVar[bool] = contextvars.ContextVar(
       "mcp_gateway_request_active", default=False
   )

   class UserIdMiddleware(Middleware):
       async def on_call_tool(self, context: MiddlewareContext, call_next):
           # Per Codex R5 N: `fastmcp 3.2.4` places meta at context.message.meta.
           meta = getattr(context.message, "meta", None) or {}
           user_id_raw = meta.get("user_id")
           email: str | None = None
           # A gateway request is "active" whenever meta.user_id is present in
           # ANY form — even if lookup fails. That way resolve_user_email() knows
           # it's in gateway context and must NOT fall back to the env var.
           gateway_active = user_id_raw is not None
           if user_id_raw is not None and str(user_id_raw).isdigit():
               email = _resolve_email_for_user_id(int(user_id_raw))  # users.email WHERE id=%s
           email_token = _USER_EMAIL_CTX.set(email)
           active_token = _GATEWAY_REQUEST_ACTIVE.set(gateway_active)
           try:
               return await call_next(context)
           finally:
               _USER_EMAIL_CTX.reset(email_token)
               _GATEWAY_REQUEST_ACTIVE.reset(active_token)

   mcp.add_middleware(UserIdMiddleware())
   ```

   Per-request DB lookup overhead: a single indexed `SELECT email FROM users WHERE id = %s` plus an in-memory LRU (size ~1000, TTL 5min). Measure during implementation; if sub-millisecond, ship as-is. If not, precompute at gateway-session-init time and cache on the gateway side instead.

6. **`utils/user_context.py:89`** — `resolve_user_email()` uses three-state logic (Codex R8 P0 fail-closed guarantee):

   The contextvars live in a new module `utils/gateway_context.py` (Codex R9 nit — **do NOT import from `mcp_server`**, that creates a circular import since many `mcp_tools/*` files already import from `utils/user_context.py` which reads the contextvar). The middleware in `mcp_server.py` imports from `utils/gateway_context` and writes the vars.

   **Three-state logic as an internal helper** (Codex R9 nit — preserve today's `resolve_user_email(email=None, context=None)` signature):

   ```python
   # utils/user_context.py — preserve existing public signature
   def resolve_user_email(email: str | None = None, context: dict | None = None) -> str:
       if email:
           return email  # caller-provided override (existing behavior)
       return _resolve_from_gateway_or_env()

   # new internal helper — three-state branch
   def _resolve_from_gateway_or_env() -> str:
       from utils.gateway_context import _USER_EMAIL_CTX, _GATEWAY_REQUEST_ACTIVE
       ctx_email = _USER_EMAIL_CTX.get()
       if ctx_email:
           return ctx_email   # gateway request with successful lookup
       if _GATEWAY_REQUEST_ACTIVE.get():
           # Gateway request where user_id was missing/invalid/unresolvable.
           # Do NOT fall back to env — fail closed.
           raise UserContextError(
               "Gateway MCP request missing valid user_id. "
               "Check that the gateway is threading user_id into meta."
           )
       # Standalone/dev path — no gateway context active. Env fallback allowed.
       env_email = os.getenv("RISK_MODULE_USER_EMAIL", "").strip()
       if env_email:
           return env_email
       raise UserContextError("No user identity — run via gateway or set RISK_MODULE_USER_EMAIL")
   ```

   Existing callers of `resolve_user_email()` keep working because the public signature preserves the `email=None, context=None` shape; only the internal fallback path changes.

   This is the critical isolation guarantee: even if `RISK_MODULE_USER_EMAIL` is set in the gateway-hosted process (which it will be for backward compat during rollout), a gateway request with a missing or unresolvable user_id **errors out** rather than silently routing to Henry's data.

7. **Portfolio-side bypass audit** (Codex R6/R7 P0 — critical): not all MCP-reachable code paths use `resolve_user_email()`. The bypass surface is broader than `mcp_tools/` alone — shared service helpers called from MCP tools can have their own default-user logic. Partial list of known current hits (Codex verified, R7):

   **Direct `RISK_MODULE_USER_EMAIL` reads**:
   - `mcp_tools/import_portfolio.py:59`
   - `mcp_tools/import_transactions.py:38`

   **Direct `get_default_user()` / "or default" fallbacks**:
   - `mcp_tools/news_events.py:119` (multiple sites in same file)
   - `mcp_tools/factor_intelligence.py:313`
   - `mcp_tools/metric_insights.py:952` (Codex R8 N — mispath corrected from `utils/metric_insights.py`)
   - `services/performance_helpers.py:53` — called by `mcp_tools/performance.py:551` (exposed as `get_performance` tool)
   - `mcp_server.py:285` `get_mcp_context()` — diagnostic tool outside the main `mcp_tools/` tree; audit separately

   This list is **"known current hits, not exhaustive"** (R7 N). Any bypass left unaddressed → strict-mode credentials ship but that tool still routes to Henry's account.

   **Phase 7 sub-task — complete audit + fix**:
   - **Scope of audit**: all code reachable from the MCP tool surface, NOT only `mcp_tools/`. Includes `services/`, `utils/`, `actions/`, `core/` — any module callable from a `@mcp.tool()` function.
   - **What to flag**: (a) `os.getenv("RISK_MODULE_USER_EMAIL")` direct reads, (b) `get_default_user()` calls, (c) any `user_email or <fallback>` chain where fallback isn't the centralized `resolve_user_email()`.
   - **Fix pattern**: every flagged site routes through `resolve_user_email()` from `utils/user_context.py`. The contextvar-backed function returns the per-request user with env fallback only when contextvar is unset (standalone/dev).
   - **Allowlist**: if a tool genuinely needs an admin override (e.g., diagnostic tools), define one centralized `resolve_user_email_with_override()` helper — not ad-hoc env reads. Allowlist reviewed in code review.
   - **Boundary test (strengthened per Codex R7 N)**: pin direct env reads AND direct default-user reads across the MCP-reachable tree:
     ```
     grep -rE 'os\.getenv\("RISK_MODULE_USER_EMAIL"|get_default_user\(' \
         mcp_tools/ services/ utils/ actions/ core/ mcp_server.py \
         | grep -v utils/user_context.py         # centralized fallback allowed
         | grep -v actions/context.py            # if it has a documented exception — review
     ```
     (Codex R8 N: `mcp_server.py` included explicitly — `get_mcp_context()` at line 285 is outside `mcp_tools/` but still an exposed MCP surface.)
     returns zero results after the fix. Add this as a pre-commit hook or CI check to prevent regression.

8. All ~83 portfolio-mcp tools — **signature-level** no changes required. BUT every tool body must route user identity through `resolve_user_email()` / the centralized context path (Phase 7 sub-task covers the bypass fixes).

**Alternative considered + rejected**: change portfolio-mcp internals from email-centric to DB-id-centric. Rejected for Phase 1 — 83 tools + multiple helper layers + historical DB rows all use email keys. Too invasive. The translation bridge preserves the existing internal contract with one narrow insertion point (middleware) + the bypass audit + fix.

**Follow-up**: once Phase 1 is stable, a separate plan can migrate portfolio-mcp internals to DB-id-keyed if there's a reason (performance, cross-provider id stability). Not Phase 1.

**Gateway-side contract**:
- `meta["user_id"]` is a non-empty string when present; absent means the caller isn't a strict-mode gateway (e.g., standalone-dev).
- `meta` is opaque to the LLM — never exposed in tool schemas.
- Invariant test in gateway: in strict mode, no MCP tool call is dispatched without `user_id` populated in meta. Assertion in `tool_dispatcher.py` with fail-closed behavior.
- portfolio-mcp fail-closed: if `_USER_EMAIL_CTX.get()` is None AND `RISK_MODULE_USER_EMAIL` env is also unset AND the request isn't a standalone-dev request, raise a tool error. Don't silently default to any user.

**Acceptance tests for this phase** (must pass before launch):

- **Two-user concurrent**: U1 owns portfolio A, U2 owns portfolio B, concurrent chat sessions, both ask "show my positions." U1's response contains A tickers, U2's contains B. Repeat 10× to catch process-wide state / contextvar bleed.
- **MCP logs**: portfolio-mcp logs show `user_id = u1_id` for U1's tool calls, `user_id = u2_id` for U2's.
- **Tool schema inspection**: confirm `user_id` / `session_id` / `meta` do NOT appear in any FastMCP tool's `parameters`.
- **Fail-closed at portfolio-mcp — unknown/invalid user_id** (Codex R8 P0, test split per R9): set `RISK_MODULE_USER_EMAIL=henry@...` in the gateway process. Synthesize gateway MCP call with `meta.user_id = "99999999"` (nonexistent user). Tool call must ERROR with "Gateway MCP request missing valid user_id", NOT silently route to Henry. Repeat with `meta.user_id = "not-a-number"`. Both fail inside portfolio-mcp's middleware→`resolve_user_email()` chain.
- **Fail-closed at gateway — missing meta.user_id in strict mode**: when the gateway's `tool_dispatcher` is in strict mode and receives an MCP tool call with no `meta.user_id` set, the assertion fires BEFORE the MCP call is sent (no network roundtrip, fast fail). This is a separate test scoped to the gateway, not portfolio-mcp. Per R9: "missing meta entirely" fails at dispatcher; "invalid user_id value" fails at portfolio-mcp.
- **Standalone-dev path**: run portfolio-mcp directly (no gateway) with `RISK_MODULE_USER_EMAIL` set → env fallback works, tools resolve to the env email.

### 8. Credential redaction (6O — bundled per Codex R1 P1 #9)

**Why bundled, not deferred**: gateway `server.py:337` and `runner.py:50` return `str(exc)` or `repr(exc)` to clients via the SSE stream. If a resolver exception or provider auth error carries the raw credential in its message (which is easy to do accidentally — parsing errors, httpx error bodies, Anthropic SDK re-raises), the credential leaks into browser-visible JSON. This plan introduces a new credential path; shipping without redaction is a regression.

**Architectural principle** (Codex R3 P1): the PRIMARY defense is **"credentials never enter the exception pipeline in the first place."** Gateway core has many emit sites (`server.py:644`, `runner.py:1481/1536/1827`, `sdk_runner.py:762`, `event_log.append` copies events before `on_event`) that append raw exception text to SSE streams AND transcript files. Trying to scrub at those downstream sites is whack-a-mole. Instead, we guarantee credentials are sanitized **at the two boundaries where they enter the exception pipeline** — the resolver module and the Anthropic provider. Everything downstream only sees pre-sanitized exceptions.

**The two credential entry points**:

1. **Resolver module** (`api/credentials_resolver.py`) — handles raw keys when fetching from resolver endpoint. All exceptions from httpx/json parsing/signature checks wrap with `_sanitize_upstream_error()` before re-raise.
2. **Anthropic provider** — when Anthropic SDK raises (401, 429, schema errors), the exception may carry request headers (`Bearer <token>`) or response bodies containing our credential. We wrap `AnthropicProvider` at instantiation time to sanitize any exception before it propagates up into gateway core.

**Wrapped provider** — must cover the real `ModelProvider` surface (Codex R4 P1). The base provider API (`packages/agent-gateway/agent_gateway/providers/base.py:69`) exposes multiple methods used by `AgentRunner` (`runner.py:1232, 1250, 1403, 1817`):

- `create_client(auth_config)` — constructs the SDK client
- `get_model_info(...)`
- `normalize_messages(...)`
- `build_request_params(...)`
- `stream(...)` — the actual API call where auth errors surface
- (plus any other methods the base class declares — enumerate during implementation)

The wrapper MUST cover every method that either (a) constructs a client with credentials or (b) calls the SDK. A single `call()` wrap is insufficient.

```python
# AI-excel-addin api/credentials.py
from agent_gateway import AnthropicProvider

class SanitizingAnthropicProvider(AnthropicProvider):   # subclass concrete provider (Codex R7 P1)
    """Wrap AnthropicProvider to sanitize any exception from SDK internals
    before it enters gateway exception-rendering paths.

    Subclasses the CONCRETE AnthropicProvider (not generic ModelProvider) so that
    gateway branches like isinstance(provider, AnthropicProvider) at _provider_utils.py:193
    keep working. Phase 1 is gated to AGENT_PROVIDER=anthropic so this concrete
    subclass is always the right one.

    Every ModelProvider method used on the hot path is explicitly overridden:
    - create_client, has_active_credential (runner.py:1813)
    - get_model_info, normalize_messages, build_request_params (runner.py:1232/1250/1403)
    - stream (runner.py:1817)
    Plus any other public method on AnthropicProvider / ModelProvider base
    (enumerate from providers/base.py:69-<end> during implementation).

    No __getattr__ catch-all — explicit delegation only. New gateway-package
    methods require an explicit override added to this class on upgrade."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)   # preserve AnthropicProvider init semantics

    def create_client(self, auth_config):
        try:
            return super().create_client(auth_config)
        except Exception as exc:
            raise _sanitize_provider_exception(exc, stage="create_client") from None

    def has_active_credential(self, *args, **kwargs):   # runner.py:1813 hot path
        try:
            return super().has_active_credential(*args, **kwargs)
        except Exception as exc:
            raise _sanitize_provider_exception(exc, stage="has_active_credential") from None

    def get_model_info(self, *args, **kwargs):
        try:
            return super().get_model_info(*args, **kwargs)
        except Exception as exc:
            raise _sanitize_provider_exception(exc, stage="get_model_info") from None

    def normalize_messages(self, *args, **kwargs):
        try:
            return super().normalize_messages(*args, **kwargs)
        except Exception as exc:
            raise _sanitize_provider_exception(exc, stage="normalize_messages") from None

    def build_request_params(self, *args, **kwargs):
        try:
            return super().build_request_params(*args, **kwargs)
        except Exception as exc:
            raise _sanitize_provider_exception(exc, stage="build_request_params") from None

    async def stream(self, *args, **kwargs):
        try:
            async for chunk in super().stream(*args, **kwargs):
                yield chunk
        except Exception as exc:
            raise _sanitize_provider_exception(exc, stage="stream") from None

    # Enumerate remaining AnthropicProvider / ModelProvider methods during implementation.
    # Every public method must be explicitly overridden with sanitize-on-exception.

def _sanitize_provider_exception(exc: Exception, *, stage: str) -> Exception:
    """Strip any credential from exception messages + attached request/response."""
    # Map well-known SDK errors to credential-free equivalents.
    # Anthropic SDK: AuthenticationError, PermissionDeniedError, etc.
    # For unknown types: return RuntimeError(f"provider error at {stage}") with no message from exc.
    ...

def get_provider_instance(provider: str | None = None) -> "ModelProvider":
    # Phase 1 multi-user gate: AGENT_PROVIDER must be "anthropic".
    # SanitizingAnthropicProvider is a subclass of AnthropicProvider, so
    # isinstance(provider, AnthropicProvider) checks in gateway package still match.
    return SanitizingAnthropicProvider()
```

**Why AnthropicProvider subclass, not ModelProvider wrapper** (Codex R7 P1):
1. `isinstance(provider, AnthropicProvider)` branches at `_provider_utils.py:193` must match — a generic `ModelProvider` wrapper would fail these checks silently.
2. Phase 1 is gated to `AGENT_PROVIDER=anthropic` at startup. No reason to preserve other provider compat in the wrapper; concrete type is always AnthropicProvider.
3. `super().method()` delegation keeps `AnthropicProvider` init semantics intact (e.g., any connection pool setup in `__init__`).

**Future-proofing**: explicit delegation over the current interface only. No `__getattr__` catch-all (R5 finding: silently bypasses new methods on subclass). If the gateway package adds new AnthropicProvider/ModelProvider methods in a future version, this class must be updated with an explicit override per new method. Pin `ai-agent-gateway` version in `requirements.txt` and review the provider interface diff on every package bump.

**Implementation TODO** (flagged during Codex review for the implementer):
- Enumerate the full public method set of `AnthropicProvider` (inherits from `ModelProvider` base at `providers/base.py:69`) — confirm every method listed in the class skeleton above, add any missing ones. `has_active_credential()` was caught by R7 review; there may be others.
- Verify the stream method is actually `async` generator — if the base signature differs, mirror it exactly.

**agent-sdk path** (Codex R4 P1 — separately required): `api/agent/interactive/runtime.py:469` constructs a `claude_agent_sdk` runtime that bypasses `get_provider_instance()` entirely. Errors flow through `sdk_runner.py:759` which appends `str(exc)` to SSE events directly. Two options:

1. **Fix SDK runtime**: wrap the SDK client creation in `runtime.py:469` with `SanitizingProvider`-equivalent exception handling at every SDK call site. More invasive but correct.
2. **Scope cut**: explicitly declare that Phase 1 multi-user activation is NOT supported for `AGENT_PROVIDER=agent-sdk` deployments. Deploy `AGENT_PROVIDER=anthropic` only for multi-user. Flag with startup assertion in `main.py` that fails gateway init if `credentials_resolver` is configured AND `AGENT_PROVIDER=agent-sdk`.

**Phase 1 choice**: **option 2 scope cut**. agent-sdk is documented as experimental (design doc §"Non-goals" #3). Blocking multi-user activation when agent-sdk is the configured provider is a simple, safe gate. A follow-up plan can add agent-sdk parity when/if that provider matures to production.

```python
# api/main.py startup assertion
# Per Codex R5: widen gate beyond agent-sdk. This repo also supports
# `openai` and `codex` providers which have their own SDK error paths
# that are not covered by SanitizingProvider's Anthropic-specific mapping.
if _credentials_resolver is not None and get_agent_provider() != "anthropic":
    raise RuntimeError(
        f"Multi-user (resolver configured) is only supported with AGENT_PROVIDER=anthropic. "
        f"Current AGENT_PROVIDER={get_agent_provider()!r}. Unset the resolver env vars or "
        f"switch to AGENT_PROVIDER=anthropic."
    )
```

After this wrap + agent-sdk gate, gateway core's emit sites cannot leak credentials because the exception objects they render are either pre-sanitized (anthropic provider path) or impossible-to-reach (agent-sdk path blocked at startup).

**Defense-in-depth layers** (secondary, not relied upon as primary):

```python
# api/credentials_resolver.py (and any module touching raw keys)
def _sanitize_upstream_error(exc: Exception, *, stage: str) -> Exception:
    """Replace any exception from the provider/SDK/resolver chain with a
    credential-free equivalent BEFORE logging or re-raising."""
    if isinstance(exc, asyncio.TimeoutError):
        return CredentialsTimeoutError("resolver timeout")
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return NoCredentialError("configure an Anthropic key in settings")
    # Everything else: drop the original message + any attached response body.
    return RuntimeError(f"credential resolver unavailable (stage={stage})")

try:
    ...
except Exception as exc:
    sanitized = _sanitize_upstream_error(exc, stage="web")
    # Log with exc_info=False — do NOT render the original traceback.
    log.error("resolver error: %s", sanitized, extra={"stage": "web"})
    raise sanitized from None  # `from None` suppresses __cause__ chaining
```

Key rules:
- `from None` suppresses `__cause__` (otherwise Python renders the original exception in tracebacks).
- `exc_info=False` on log calls — never render the original traceback.
- Log records never carry the original exception object in structured fields.

**Layer 2 — Handler-boundary formatter** (`api/redaction.py`):

- Custom `logging.Formatter` subclass used by ALL gateway + proxy handlers. Overrides `formatException()` to run the scrub regex on rendered tracebacks AS WELL AS `format()` on the message.
- Regex patterns:
  - `sk-ant-api03-[A-Za-z0-9_-]+`
  - `sk-ant-oat01-[A-Za-z0-9_-]+`
  - `Bearer [A-Za-z0-9_.-]+`
  - `"auth_token"\s*:\s*"[^"]+"`
  - `"api_key"\s*:\s*"[^"]+"`
  Replacement: `[REDACTED_CREDENTIAL]`.
- Applied at the root logger's handler(s) so every log call — including ones from third-party SDKs — passes through it. Defense-in-depth; Layer 1 is the primary.

**Layer 3 — SSE/error envelope at the proxy boundary**:

- `risk_module/app_platform/gateway/proxy.py:392` `_format_exc` — apply the Layer 2 formatter's scrub function before returning the error string.
- Gateway-core emit sites (`server.py:644`, `runner.py:1481/1536/1827`, `sdk_runner.py:762`, `event_log.append`) are **NOT patched in Phase 1**. Codex R3 flagged that `on_event` rewrites arrive after `event_log.append` has already copied the event (`event_log.py:44`), so the rewrite hook is ineffective for transcripts. Our guarantee comes from Layer 1 (wrapped provider + sanitized resolver), which ensures these sites never see credential-carrying exceptions in the first place.
- **Follow-up**: once the gateway package accepts a PR that applies a pre-emit redaction callback in `event_log.append`, move Layer 3 earlier (upstream patch). Not Phase 1 scope.

**Layer 4 — Structured-field sanitization**:

- If we adopt structured logging (`.extra` dicts), sanitize any string field matching the same regex patterns before the record is dispatched. A `logging.Filter` with iteration over `record.__dict__` covers this.
- For `logging.LogRecord.args` (printf-style args) — iterate and scrub strings.

**Known gaps** (follow-up, explicitly out of scope):
- Anthropic SDK internals that log directly via its own logger before our code sees the exception. Mitigation: set `logging.getLogger("anthropic").addFilter(scrub_filter)` at startup — included in Phase 6 delivery.
- Third-party libraries that `print()` directly to stderr, bypassing logging. Not addressable by filter; acceptable residual risk.
- Deep structured logging refactor (making keys non-strings everywhere). Tracked separately.
- Gateway-core emit sites — mitigated by Layer 1 sanitize-at-boundary. A gateway-package PR to add pre-emit redaction at `event_log.append` is queued as follow-up work.

**Test coverage** (expanded):
- Synthetic exception with `sk-ant-api03-TESTKEY` in `.args[0]` → scrubbed.
- Exception with credential in `__cause__` → suppressed by `from None` wrap, not emitted.
- `exc_info=True` log call rendering traceback containing the credential → scrubbed by Layer 2 `formatException()` override.
- Structured `extra={"provider_response": "...sk-ant-..."}` → Layer 4 filter scrubs.
- Anthropic SDK synthetic exception path → `anthropic` logger filter scrubs.

### 9. auth_expired consumer retry — verification only

Phase 1.4 acceptance gate: when Anthropic returns 401, gateway returns structured `{error: "auth_expired", ...}`. Consumer must detect this, re-init the session (re-calling the resolver, which fetches a fresh credential), and replay the last user message.

**Status per Codex R1 N #10**: risk_module proxy ALREADY handles this at `proxy.py:281-323` (classifies error, invalidates cached token, re-inits, retries). This plan's scope is:
- **risk_module proxy**: verify existing retry path still works after Phase 1.4-style resolver is active (integration test). No code change expected.
- **Excel taskpane**: add retry path in `ChatService.streamChat()` (§6c above).
- **Telegram bot**: add retry path in `stream_chat()` (§6d above).

---

## Phases

**Re-ordered per Codex R1 P0 #2**: consumer contract changes MUST precede activation, because activation makes strict mode global — any consumer still sending legacy init/chat bodies breaks immediately. The old "flip env vars first" ordering would have broken all three consumers at activation time.

| Phase | Scope | Ship-independent? | Files touched |
|-------|-------|-------------------|---------------|
| 1 | Schema migration (users table cols) | Yes | risk_module |
| 2 | Crypto + Secrets Manager helpers + encryption key provisioning | Yes | risk_module |
| 3 | User-mgmt endpoints + settings UI (add/rotate/remove BYOK key) | Yes | risk_module |
| 4 | Internal resolver endpoint (HMAC + private-net bound) | Yes | risk_module |
| 5 | **Consumer contract prep** — Excel + Telegram + proxy all send `user_id` + `channel` on init AND every `/chat`; auth_expired retry in Excel + Telegram. **These changes are no-ops on the current non-strict gateway** — bodies just have extra fields the gateway ignores. | Yes | AI-excel-addin (Excel + Telegram) + risk_module (proxy verify) |
| 6 | Gateway resolver code + redaction filter + api_key-to-channel map + MCP `meta.user_id` injection (§7) + SanitizingProvider + non-anthropic-provider startup gate | Yes (code only, not activated) | AI-excel-addin gateway |
| 7 | portfolio-mcp `user_id` consumer — FastMCP middleware reads `meta.user_id`, translates DB id → email via `users.email` lookup, stashes into `ContextVar` read by `utils/user_context.py` | Yes (no-op until activated) | risk_module portfolio-mcp |
| 8 | **Activation with dual-accept window** (see Open Q #6 for full sequence): (a) publish `ai-agent-gateway` to PyPI + `pip install --upgrade` on the gateway host (Phase 6 edits live in `packages/agent-gateway/` which is source-of-truth; runtime loads from site-packages). (b) deploy gateway with dedicated keys + `GATEWAY_API_KEY_LEGACY` set, resolver URL/HMAC still empty → non-strict mode accepts both old+new keys. (c) migrate each consumer to its dedicated key. (d) flip resolver URL + HMAC → strict mode activates. (e) after 24-48h stable, unset `GATEWAY_API_KEY_LEGACY`. Restart required at each env-var state change (purges in-memory sessions). | Semi — requires PyPI publish + coordinated per-consumer deploy across dual-accept window | PyPI package bump + deploy config |
| 9 | E2E two-user acceptance tests (BYOK, auth_expired, cross-user isolation, MCP identity) | Blocks launch | Test scripts |

**Shipping order**:
1 → 2 → 3 (users can add keys, nothing uses them yet)
→ 4 (resolver endpoint works via curl against HMAC test)
→ 5 (consumers send extra fields — safe because gateway is still non-strict)
→ 6 + 7 (gateway code, MCP code — all code in place, not activated)
→ 8 (activation — flip env vars. Strict mode turns on. Consumer contract changes from Phase 5 are now required and present.)
→ 9 (acceptance tests)

**Critical**: DO NOT run Phase 8 before Phase 5 + 6 + 7 have landed and verified in prod. Doing so breaks all three consumers.

**Rollback plan for Phase 8**: revert the activation env vars to empty. Gateway resolver becomes `None` → non-strict mode → existing operator path resumes. Zero code rollback required. Kept as a fast safety valve.

---

## Testing strategy

### Unit tests

- `services/anthropic_credential_store.py`: store/get/delete paths; Secrets Manager success; Secrets Manager failure with `ALLOW_DB_CRED_FALLBACK=false` (raises); Secrets Manager failure with fallback=true (encrypts to DB); missing `ANTHROPIC_CRED_ENCRYPTION_KEY` (raises at import).
- `routes/internal_resolver.py`: valid HMAC (200); stale timestamp (401); wrong signature (401); user not found (404 normalized body); user with no key (404 normalized — identical to unknown user); Secrets Manager 503 (503 `resolver_transient`); user with BYOK API key (200, `auth_mode: "api"`); user with BYOK OAuth token (200, `auth_mode: "oauth"`).
- `api/credentials_resolver.py` (AI-excel-addin): each api_key → channel path; unknown api_key hash (raises); HTTP 200 → `AuthConfig`; 404 → `NoCredentialError`; 503 → `RuntimeError` (distinct from NoCredentialError); httpx timeout → `CredentialsTimeoutError`; 401 HMAC-side failure → `RuntimeError`; all exception paths verified to emit sanitized messages (no raw key leakage).
- Gateway redaction filter: record with `sk-ant-api03-TESTKEY123` in `.msg` / `.args` → output contains `[REDACTED_CREDENTIAL]`.
- `POST/GET/DELETE /api/user/anthropic-credential` routes: save (valid key); format validation (rejects non-sk-ant- prefix); rotate replaces key; idempotent delete; GET returns source without echoing key.

### Integration tests

- **Two-user E2E**: create two users in risk_module, configure different BYOK keys, send chat from each, verify gateway makes two separate sessions with two separate credentials. Inspect gateway logs for `api_key_hash` difference.
- **Cross-user-reuse rejection**: force-pool two users into one gateway session, verify gateway returns 401 `cross_user_reuse`.
- **Missing-user_id rejection**: send `/chat` body without `user_id` in strict mode, verify 400 `missing_user_id` (Codex R1 P1 #6).
- **Missing key path**: new user (no BYOK) hits chat, verify `no_credential` → UI shows "add your key" prompt.
- **Resolver transient 5xx**: mock Secrets Manager to 503, verify resolver returns 503 `resolver_transient`, gateway maps to 5xx (NOT "add your key") — Codex R1 P1 #8.
- **auth_expired retry (3 consumers)**: revoke Anthropic key mid-session for each of risk_module / Excel / Telegram, verify each consumer re-inits and replays.
- **Operator paths dispatched via api_key_hash**: Excel and Telegram still work with operator env-var credential, gateway logs show api_key_hash dispatched to correct channel.
- **Backward-compat regression**: with ALL resolver env vars unset, run full existing AI-excel-addin test suite + a pinned end-to-end test that exercises the `_default` operator path. Codex R1 N #11 — this is the guardrail that catches "strict mode leaks into single-user mode" bugs.
- **MCP per-user data**: two users concurrently ask "show my positions," verify each sees their own portfolio. Repeat 10× (Codex R1 P0 #1).
- **MCP missing `meta.user_id` fail-closed**: synthetic test dispatches an MCP call in strict mode with `meta` empty, verify gateway asserts and fails closed (tool call not sent).

### Security / redaction tests

- **Credential redaction at SSE boundary**: inject synthetic exception whose message contains `sk-ant-api03-TESTKEY` into the resolver path, verify the SSE stream emits `[REDACTED_CREDENTIAL]`, NOT the raw key (§8 invariant, Codex R1 P1 #9).
- **Credential redaction in logs**: same test asserts log records are also redacted.
- **HMAC stale-timestamp rejection**: send resolver request with `X-Resolver-Timestamp` 120s in the past, verify 401.
- **HMAC wrong-signature rejection**: send with mutated signature, verify 401.
- **User-enumeration resistance**: resolver endpoint response for unknown user vs known-but-no-key user are byte-identical (except request_id).

### Ops / deploy tests

- **Prod fail-closed on Secrets Manager down**: set `ALLOW_DB_CRED_FALLBACK=false`, force Secrets Manager error, verify `POST /api/user/anthropic-credential` returns 500 (not silently stored in DB).
- **Phase 8 rollback**: with resolver active, clear env vars, restart gateway, verify all existing consumers (web, excel, telegram) still work with their dedicated API keys via the non-strict path.

### Acceptance gates (per Phase 1.4 design doc + Codex R1)

Strict mode closes TWO bypasses (Codex R1 P1 #6): body-omission AND body-mismatch. Both must be tested.

- [ ] BYOK API key path works end-to-end (user with `sk-ant-api03-...` key)
- [ ] BYOK OAuth token path works end-to-end (user with `sk-ant-oat01-...` token)
- [ ] `auth_expired` retry verified for risk_module proxy (manual revoke test)
- [ ] `auth_expired` retry verified for Excel taskpane (manual revoke test)
- [ ] `auth_expired` retry verified for Telegram bot (manual revoke test)
- [ ] Strict mode rejects `_default` user_id at `/chat/init` (`strict_mode_default_user` error)
- [ ] **Strict mode rejects missing `user_id` on `/chat` body** (`missing_user_id` — bypass #1)
- [ ] **Strict mode rejects `user_id` body mismatching JWT-bound session user_id** (`cross_user_reuse` — bypass #2)
- [ ] Operator paths (excel, telegram) return operator credential (dispatched via api_key_hash)
- [ ] portfolio-mcp returns correct per-user data (two-user concurrent test, 10 iterations, no leakage)
- [ ] Regression: with resolver env vars unset, gateway behaves exactly as pre-plan (backward-compat test)
- [ ] Resolver endpoint rejects request with stale HMAC timestamp (>60s skew)
- [ ] Resolver endpoint rejects request with wrong HMAC signature
- [ ] Resolver endpoint returns identical 404 body for "no user" and "no key configured" (no enumeration)
- [ ] Credential redaction: synthetic exceptions containing `sk-ant-*` emit `[REDACTED_CREDENTIAL]` at every client-facing boundary (gateway SSE, proxy SSE, logs)
- [ ] Prod guard: when `ALLOW_DB_CRED_FALLBACK=false` and Secrets Manager write fails, `POST /api/user/anthropic-credential` returns 500 — does NOT silently degrade

---

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| HTTP callback latency adds noticeable delay to session-init | Medium | Session-lifetime cache (Phase 1.1 behavior) — callback fires once per session, not per turn. Typical session is 100s of turns. Target: <100ms callback overhead on session-init. |
| HMAC key leaks (env var, logs) | Low | Dedicated env var never logged. Covered by credential redaction filter (§8). Rotate via coordinated env-var update + restart of both services. |
| Secrets Manager write failure on save | Medium | Prod: fail-closed (user sees error, no silent DB degradation). Dev: optional DB fallback gated by `ALLOW_DB_CRED_FALLBACK`. Fail-closed is the safe default. |
| User adds invalid Anthropic key | High | Phase 1 surfaces error on first chat turn via provider-side 401 → gateway `auth_expired` → consumer shows "check your key" UX. Phase 2 adds save-time validation. |
| Consumer forgets to send `user_id` on /chat | Medium | Gateway strict mode rejects with `missing_user_id`. Acceptance test pins this. Phase 5 lands consumer changes BEFORE strict mode activates. |
| Compromised consumer advertises fake channel | Mitigated | Channel derived from `hash(api_key)` server-side, not from client payload. Compromised consumer only has its own channel's credential scope. |
| Gateway package upgrade breaks resolver signature | Low | `ai-agent-gateway` version pinned in `requirements.txt`. Upgrade tested against this contract. |
| Phase 8 activation breaks unready consumer | **High if ordering wrong** | Mitigated by phase ordering: Phase 5 (consumer contract) MUST precede Phase 8 (activation). Rollback = clear env vars, strict mode off, consumers resume on new dedicated API keys without changes. |
| Credential leaks via `repr(exc)` at SSE boundary | High without mitigation | §8 credential redaction filter + fixed sanitized error messages at resolver boundary. Acceptance test pins with synthetic keys. |
| MCP tool call dispatched without `meta.user_id` in strict mode | High | §7 gateway invariant: fail-closed assertion in `tool_dispatcher.py` on MCP dispatch. Portfolio-mcp middleware also fail-closes if `_USER_EMAIL_CTX` is unset AND env-var fallback is unset — no silent default-user route. |
| Portfolio-mcp tool bypasses centralized `resolve_user_email()` path and reads env directly | High | §7 Phase 7 sub-task: exhaustive audit + fix of `mcp_tools/*.py` for direct `RISK_MODULE_USER_EMAIL` reads. Pinned by boundary test (`grep -r` returns zero outside the centralized fallback). |
| `user_id` lookup ambiguity (multi-column collision) | Eliminated | Phase 1 scope cut — resolver accepts numeric DB `users.id` ONLY. Proxy asserts `user["user_id"]` is not None (fail-loud if missing), sending only the DB id. One column, one type, no collisions. |

### Explicit non-risks (verified during research)

- finance_cli resolver pattern is proven (validated 2026-04)
- risk_module gateway proxy already sends `user_id` per Phase 1.4 (`7b407b5d`)
- risk_module proxy already handles `auth_expired` retry at `proxy.py:281` (Phase 6 is verification-only)
- Gateway package supports all needed hooks (`credentials_resolver`, `resolver_timeout_seconds`, strict mode, `NoCredentialError`/`CredentialsTimeoutError`/`AuthExpiredError`)
- Gateway package `valid_api_keys` mechanism supports multiple keys (per-consumer keys are first-class — confirmed in `server.py:537`)
- AWS Secrets Manager pattern proven via SnapTrade (`brokerage/snaptrade/secrets.py`)
- `context["channel"]` being trustworthy is NOT assumed — dispatch binds to authenticated api_key_hash instead

---

## Out of scope (explicit)

- Metered/commercial billing tier (Phase 2)
- Usage ledger persistence (Phase 2)
- Stripe integration (Phase 2)
- BYOK key validation at save time via live Anthropic call (Phase 2)
- In-chat onboarding flow when user first hits chat without a key (Phase 2)
- PostgreSQL RLS (separate plan in TODO §Security)
- Agent-layer extraction / risk_module standing up its own gateway (rejected)
- Deep structured-logging refactor so credentials are never rendered as strings (follow-up after Phase 1 redaction filter proves the surface)
- Automated secret rotation (manual coordinated restart is acceptable for Phase 1 — see Open Q #7)

**Explicitly IN scope** (bundled per Codex R1, not deferred):
- Credential redaction in gateway error paths (6O) — see §8
- portfolio-mcp user_id threading (6N) — see §7 (real work, not a side effect)

---

## Open questions for review

Reprioritized per Codex R1 N #12 — these are the contracts that determine safety + rollout order, not cosmetic details.

1. **Server-derived consumer binding — is `hash(api_key) → channel` the right primitive?** Alternative considered: one gateway instance per consumer (single-consumer-per-process). Rejected because AI-excel-addin is already the shared agent host — spawning 3 gateway processes multiplies operational cost. Open: should we accept the api-key hash approach as final, or does the gateway package have a first-class "consumer registry" concept we should use instead?

2. **Exact MCP identity contract** — the proposed invariant is: "in strict mode, every MCP tool call carries `user_id` in the protocol-level `meta` field; portfolio-mcp fails closed if `meta.user_id` is absent while an active gateway session exists." Transport is `mcp.ClientSession.call_tool(..., meta=...)` (MCP protocol-level, NOT tool args) and FastMCP `Middleware.on_call_tool` reads it server-side via `context.message.meta` (Codex R6 verified against installed `fastmcp 3.2.4`). Does this contract hold for sub-agent dispatched MCP calls? Sub-agent dispatchers are created in `api/agent/shared/tool_handlers.py:845` and `:956`; Phase 7 Step 3 wires `user_id` into both sites. Acceptance test covers sub-agent fan-out.

3. **Prod fallback policy** — when AWS Secrets Manager is momentarily unavailable, should `POST /api/user/anthropic-credential` (save) fail, or should it queue and retry? Phase 1: fail with user-visible error. Phase 2: add idempotent retry queue if telemetry shows this is a real pain point.

4. **Resolver endpoint network boundary** — private interface binding (`127.0.0.1`) is sufficient when gateway and risk_module backend run on the same host. When they run on separate hosts (multi-node prod), we need VPC-only exposure via security groups. Decision required at deploy time; plan assumes single-host initially.

5. **`user_id` shape across the chain — Phase 1 scope**: numeric DB `users.id` string ONLY. Proxy's `_get_user_key()` asserts `user["user_id"]` is not None and returns `str(user["user_id"])`. Resolver endpoint rejects non-numeric input with normalized 404. portfolio-mcp receives numeric id only. Google sub / email multi-column lookup is explicitly out of Phase 1 scope per Codex R3/R4 — these paths are deferred until a typed user_id contract is designed. Confirm during implementation: every risk_module auth path populates `user["user_id"]` (the numeric DB id) — if any path creates sessions without it, that path must be fixed before Phase 8 activation.

6. **Operational rollout** — Phase 8 activation requires coordinated env-var push across gateway + risk_module backend + per-consumer deploy with a **dual-accept window** (Codex R2 P1 #1 + N #2).

   **Key property**: the gateway's `valid_api_keys` set ALWAYS drives what `/chat/init` accepts, regardless of resolver state. We keep the old and new keys valid simultaneously during cutover.

   **Ordered steps**:
   (a) Generate `GATEWAY_RESOLVER_HMAC_KEY`, `ANTHROPIC_CRED_ENCRYPTION_KEY`, and per-consumer keys `GATEWAY_API_KEY_EXCEL/TELEGRAM/WEB`. Store in prod secrets.
   (b) **Publish the gateway package to PyPI.** Phase 6 edits live in `AI-excel-addin/packages/agent-gateway/` but AI-excel-addin's gateway runtime loads from site-packages, not local source (by design — same local-first-then-publish pattern as `fmp/`→`fmp-mcp`). Without publish+reinstall, the new MCP `meta` transport + `_mcp_meta_inject_servers` allowlist + fail-closed assertion in `tool_dispatcher.py` are dormant. Steps:
   - Bump version in `packages/agent-gateway/pyproject.toml` (minor bump — Phase 6 is additive + backward-compat)
   - Run `scripts/publish_agent_gateway.sh` (per AI-excel-addin memory: sync+commit+push+version bump+build+twine check+PyPI upload one-shot)
   - `pip install --upgrade ai-agent-gateway` on the gateway host
   - Verify import: `python3 -c "from agent_gateway import AuthConfig; from agent_gateway.tool_dispatcher import ToolDispatcher; print('ok')"`
   (c) Deploy risk_module backend with resolver endpoint + its env vars (`GATEWAY_RESOLVER_HMAC_KEY`, `ANTHROPIC_CRED_ENCRYPTION_KEY`). Smoke-test HMAC endpoint via curl from gateway host.
   (d) Deploy gateway with resolver code + `GATEWAY_API_KEY_LEGACY=<old shared key>` + all three dedicated `GATEWAY_API_KEY_{EXCEL,TELEGRAM,WEB}` set + `GATEWAY_LEGACY_CHANNEL=web`. **Resolver URL + HMAC key STILL UNSET → `_credentials_resolver = None` → non-strict mode**. Now `valid_api_keys = {legacy, excel, telegram, web}` — old AND new keys all valid. Consumers can migrate one at a time without breaking.
   (e) Deploy each consumer (Excel, Telegram, risk_module backend) with its dedicated API key. Test each one. If a consumer fails with its new key, revert that single consumer (others unaffected).
   (f) Once all three consumers are on dedicated keys: smoke-test each one.
   (g) **Gateway cutover**: set `RISK_MODULE_RESOLVER_URL` + `GATEWAY_RESOLVER_HMAC_KEY` on the gateway → restart. Restart REQUIRED — Phase 1.1 `SessionStore` is in-memory, so any existing sessions are cleared automatically (Codex R2 N #2 addressed: `SessionStore` state does NOT persist across restarts per design doc §"Non-goals" #6). Strict mode activates, resolver fires, all consumers have dedicated keys already.
   (h) Verify acceptance gates live.
   (i) **Shrink window**: after 24-48h of stable operation, unset `GATEWAY_API_KEY_LEGACY` and restart. Legacy key is now rejected.
   (j) **If failure at step (g) or (h)**: unset `RISK_MODULE_RESOLVER_URL` + `GATEWAY_RESOLVER_HMAC_KEY`, restart. Strict mode off, resolver inactive, `GATEWAY_API_KEY_LEGACY` still accepted alongside dedicated keys — consumers keep working. Note: rolling back the package itself (via `pip install ai-agent-gateway==<prev-version>`) is a separate step if the package ships a genuinely broken change — the env-var revert alone keeps existing behavior working because all Phase 6 behavior is opt-in via the resolver being `None`.

   **Session purge invariant** (Codex R2 N #2): every resolver-config state transition (off→on, on→off) requires a gateway restart. This is enforced by design: `SessionStore` is in-memory, so restart naturally purges any session bound to a stale `(user_id, auth_config)` pair. Adding persistent `SessionStore` (deferred to Phase 2+ per design doc) would require explicit session-purge on transition — out of Phase 1 scope, but flagged in the ops runbook.

7. **Secret rotation ops runbook** — `GATEWAY_RESOLVER_HMAC_KEY` rotation requires coordinated restart of gateway + risk_module backend (both read the same env). Consumer API keys rotate independently per consumer via the same dual-accept pattern (add new key, migrate consumer, remove old key). Add a short ops doc (`docs/ops/GATEWAY_SECRET_ROTATION.md`) as part of Phase 4 deliverables.

8. **Metrics surfaces** — resolver outcome counter, resolver latency histogram, credential-redaction-filter hit counter (signal of a near-miss leak to investigate). Add a dashboard item in Phase 4. Propose dashboard location: wherever existing gateway metrics land today (verify during implementation).

---

## Implementation expectations

Per project workflow (CLAUDE.md):
- Plan → Codex review → Codex implements per phase
- Each phase lands as its own commit with tests + linter pass
- Phase boundaries are acceptance-testable independently
- Expected Codex review rounds: 4-8 on this plan (larger than average given cross-repo scope)
