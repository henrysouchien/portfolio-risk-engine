# Agent-Guided Brokerage Connection — MCP Tools Plan

**Date:** 2026-03-21
**Status:** PLAN (v31 — cleanup pass after Codex reviews)
**Codex reviews:** v1 FAIL (6H 4M), v2 FAIL (3H 3M), v3-v30 FAIL (0-2H, decreasing). 104 findings resolved. All addressed below.

## Context

When an AI agent is helping a new user onboard ("I have Fidelity"), there's no MCP tool to initiate or monitor a brokerage connection. The CSV import path has a full 5-tool playbook (`normalizer_builder.py`), but API-based connections require the user to manually navigate the web UI. All the backend infrastructure exists — the gap is purely at the MCP layer.

**Goal:** 3 MCP tools that let an agent guide a user from "I have Fidelity" → connected portfolio with positions loaded.

**Agent workflow:**
```
User: "I have Fidelity"
  → Agent calls list_supported_brokerages() to confirm support
  → Agent calls initiate_brokerage_connection("fidelity")
  → Gets back SnapTrade connection URL + instructions
  → Tells user: "Open this link to connect your Fidelity account"
  → User completes OAuth in browser
  → Agent calls complete_brokerage_connection(provider="snaptrade", pre_auth_ids=<from initiate response>) to verify + bookkeep
  → Agent calls get_positions(force_refresh=True, refresh_provider="snaptrade", format="agent") to sync
  → Positions loaded + accounts auto-discovered in DB (via discover_accounts_from_positions)
  → Agent calls list_accounts() to confirm: "Your Fidelity account is connected — 2 accounts, 47 positions"
```

**Plaid variant** (two-step flow):
```
User: "I have Chase"
  → Agent calls initiate_brokerage_connection("chase")
  → Gets back Plaid hosted link URL + link_token
  → Tells user: "Open this link to connect your Chase account"
  → User completes Plaid Link in browser
  → Agent calls complete_brokerage_connection(provider="plaid", link_token="link-xxx")
  → Tool polls for public_token, exchanges it, stores access_token + provider_item
  → Agent calls get_positions(force_refresh=True, refresh_provider="plaid", format="agent") to sync
  → "Your Chase account is connected"
```

---

## Prerequisite: Slug Alias Fixes

Before implementing, fix alias gaps and conflicts in `INSTITUTION_SLUG_ALIASES` (`providers/routing_config.py:330`):

**1. Add missing institutions:**
```python
"m1 finance": "m1_finance",
"m1": "m1_finance",
"betterment": "betterment",
"wealthfront": "wealthfront",
"u.s. bank": "us_bank",    # display name is "U.S. Bank" but only "us bank" alias exists
"e trade": "etrade",       # catches "e-trade" after hyphen→space normalization in step 2b
```
These are in `INSTITUTION_PROVIDER_MAPPING` but have no alias entries (or missing variant aliases).

**2. Bank of America / Merrill — handled by exact-key-first resolution, NO global alias changes:**
The global `INSTITUTION_SLUG_ALIASES` maps `"bank of america"` → `"merrill"` and `"bofa"` → `"merrill"`. Do NOT change these — they're used by `match_brokerage()`, `trading_analysis/data_fetcher.py:46`, and tested in `tests/mcp_tools/test_brokerage_aliases.py:19`.

The exact-key-first approach in `initiate_brokerage_connection()` step 2a resolves this naturally:
- `"bank of america"` → normalizes to `"bank_of_america"` (spaces→underscores) → exact key match in `INSTITUTION_PROVIDER_MAPPING` → correct bank institution.
- `"bank_of_america"` → exact key match → correct.
- `"merrill"`, `"merrill edge"` → no exact key → slug resolver → `"merrill"` brokerage. Correct.
- `"bofa"` → no exact key → slug resolver → `"merrill"`. Accepted: existing behavior, changing would break tests.
- `"Bank of America Merrill Edge"` → normalizes to `"bank_of_america_merrill_edge"` → no exact key → slug resolver matches `"merrill"` first (alias order). Correct — this is a Merrill brokerage reference.
- `"bank of america checking"` → normalizes to `"bank_of_america_checking"` → no exact key → slug resolver matches `"bank of america"` substring → `"merrill"`. **Accepted limitation** — rare edge case, agent can clarify.

**File:** `providers/routing_config.py` (lines 330-354)

---

## Tool 1: `initiate_brokerage_connection()`

**Purpose:** Resolve institution → provider, generate connection URL, return it with instructions.

**Parameters:**
- `institution: str` — Institution slug or name ("fidelity", "charles_schwab", "chase")
- `user_email: str` — User identifier (optional, falls back to default)

**Implementation (in `mcp_tools/connections.py`):**

1. Resolve user via standard two-step MCP pattern (matching `mcp_tools/portfolio_management.py:29`): `resolved_email, _ctx = resolve_user_email(user_email)` — **returns `(str, dict)` tuple, must unpack** (`utils/user_context.py:89`). Falls back to `RISK_MODULE_USER_EMAIL` env var if None. Then `user_id = resolve_user_id(resolved_email)`. Use `format_missing_user_error()` if resolution fails. Decorated with `@handle_mcp_errors` + `@require_db`. Use `resolved_email` (not raw `user_email`) for all subsequent provider calls.
2. **Resolve institution in two steps — exact match FIRST, then slug resolution:**
   a. Normalize input: `institution.strip().rstrip(".,;:!?")` → `.lower()` → collapse internal whitespace via `" ".join(s.split())` → `.replace(" ", "_").replace("-", "_")` → try as exact key against `INSTITUTION_PROVIDER_MAPPING`. (Normalizes spaces, hyphens, trailing punctuation, and repeated whitespace — handles `bank-of-america`, `m1-finance`, `Bank of America.`, `Bank of America?`, `Bank   of   America`, etc.) If found, use directly. This handles pre-normalized slugs like `"charles_schwab"` and — critically — `"bank_of_america"` which would otherwise get swallowed by the `"bank of america" → merrill` alias in the substring resolver. It also correctly resolves `"bank of america"` → `"bank_of_america"` (after space→underscore normalization) directly to the bank institution.
   b. If no exact match, normalize for slug resolver: `slug_input = " ".join(institution.strip().rstrip(".,;:!?").lower().replace("-", " ").split())`. Then call `resolve_institution_slug(slug_input)` from `providers/routing.py:69` for fuzzy matching via `INSTITUTION_SLUG_ALIASES`. This handles most hyphenated inputs (e.g. `u.s.-bank` → `u.s. bank` → matches `"u.s. bank"` alias, `e-trade` → `e trade` → matches `"e trade"` alias added in prerequisite step).
   c. **BofA/Merrill:** No scoped override needed. Exact-key-first (step a) handles the common cases correctly — see prerequisite section §2 for full analysis. `"bank of america checking"` → merrill via substring resolver is an accepted edge case (rare, agent can clarify).
3. Look up provider chain via `INSTITUTION_PROVIDER_MAPPING[slug]` — this contains aggregator providers (snaptrade, plaid)
4. Check provider availability via shared `_check_provider_available(provider)` helper. This ALWAYS constructs the client — never short-circuits on env var checks alone:
   - First call `is_provider_enabled(provider)` from `providers/routing.py:279`. If False, provider is intentionally disabled via `ENABLED_PROVIDERS` — return `(False, None)` immediately.
   - If enabled, **always attempt client construction** as the definitive availability check. Do NOT use `is_provider_available()` at all — it only checks env vars and misses SDK failures, bad config values, and AWS credential paths:
     - **SnapTrade:** Try `get_snaptrade_client()`. Non-None means client constructed successfully (credentials loaded from env or AWS Secrets Manager).
     - **Plaid:** Try `create_client()` from `brokerage/plaid/client.py`. Non-None means SDK is installed and credentials are valid. Additionally try `import boto3` (needed for `store_plaid_token()` persistence at `brokerage/plaid/secrets.py:24`). If either fails, Plaid is genuinely unavailable.
     - **Accepted limitations:**
       - `create_client()` + `import boto3` proves SDK/credentials/dependency availability but not live AWS Secrets Manager connectivity. Failures caught at connection time by `complete_brokerage_connection()`'s try/except with cleanup.
       - **AWS-only SnapTrade conflict:** If SnapTrade credentials are only in AWS Secrets Manager (no env vars), `get_snaptrade_client()` succeeds (connection works), but the post-connect `get_positions(refresh_provider="snaptrade")` path in `PositionService` only registers SnapTrade when `is_provider_available("snaptrade")` passes env-var checks (`services/position_service.py:163`). `refresh_provider_positions()` will fail with "Unknown provider" for unregistered providers. This is a **pre-existing limitation** of the position service, not introduced by this plan. Workaround: ensure SnapTrade env vars (`SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`) are set even when AWS credentials are also configured. Future fix: align `PositionService` provider registration with the same client-construction check used here.
   - Return `(available: bool, client: Optional)`. The constructed client is cached and reused by `initiate_brokerage_connection()` — avoids double-construction and ensures the exact client that passed the availability check is the one used for the connection.
   - **Memoize per MCP call** via local dict — only 2 providers (snaptrade, plaid) are checked. Results cached for both `list_supported_brokerages()` (loops all institutions) and `initiate_brokerage_connection()` (loops provider chain with fallback).
5. **Loop through provider chain with fallback.** For each provider in `INSTITUTION_PROVIDER_MAPPING[slug]`:
   a. Check availability via `_check_provider_available(provider)`. Skip if unavailable.
   b. Attempt the full provider flow (snapshot + URL creation) inside try/except.
   c. If successful, return the result. If the provider fails (e.g. SnapTrade "user exists but no valid secret"), log warning and continue to next provider.
   d. If ALL providers fail, return error with **aggregated** failure details from all providers (matching the Error cases section format: `{"provider_errors": {"snaptrade": "...", "plaid": "..."}}`).
   This prevents a user-specific SnapTrade issue from blocking onboarding when Plaid is viable.
6. **Important:** `INSTITUTION_PROVIDER_MAPPING` already includes aggregator entries for Schwab and IBKR (`["snaptrade", "plaid"]`). These work — users CAN connect Schwab/IBKR via SnapTrade/Plaid. Direct providers (`POSITION_ROUTING`/`TRADE_ROUTING`) are separate concerns for position/trade routing after connection. This tool only handles the initial connection via aggregators.
7. **For each provider attempt**, generate connection URL:

   **SnapTrade path:**
   - Get SnapTrade client from `_check_provider_available("snaptrade")` result (already constructed in the provider loop, step 5). Reuse cached `(available, client)` tuple.
   - **Capture pre-auth snapshot:** Check `get_snaptrade_user_secret(resolved_email)`. If no secret (first-time user), `pre_auth_ids = []`. If secret exists, call `client.connections.list_brokerage_authorizations(user_id=snaptrade_user_id, user_secret=user_secret)` and extract `pre_auth_ids = [str(auth.get("id")) for auth in response.body]` (dict-like access, matching `adapter.py:324`).
   - Call `create_snaptrade_connection_url(resolved_email, client)` from `brokerage/snaptrade/connections.py:22`
   - Handle the "user exists but secret missing in AWS" failure path — catch the error and return actionable message
   - After URL creation, store provider_items mapping: replicate `_store_snaptrade_item_mapping()` logic from `routes/snaptrade.py:275`
   - Returns `connection_url` + `pre_auth_ids` as a JSON-encoded string (e.g. `'["auth_123","auth_456"]'`). Agent passes this opaque string back to `complete_brokerage_connection()` which parses it via `parse_json_list()`.

   **Plaid path:**
   - Get Plaid client from `_check_provider_available("plaid")` result (already constructed in the provider loop, step 5). Do NOT call `create_client()` again — reuse the cached `(available, client)` tuple.
   - Hash resolved email for Plaid user_id: `hashlib.sha256(resolved_email.encode()).hexdigest()[:16]` (same as `routes/plaid.py:736`)
   - Call `create_hosted_link_token(client, user_hash, redirect_uri=f"{FRONTEND_BASE_URL}/plaid/success", webhook_uri=f"{BACKEND_BASE_URL}/plaid/webhook")` from `brokerage/plaid/client.py:73` — must use `FRONTEND_BASE_URL` and `BACKEND_BASE_URL` from `settings.py`, matching `routes/plaid.py:742-743`. Do NOT use the placeholder defaults in the function signature.
   - Map `hosted_link_url` from the response into the unified `connection_url` field. Also return `link_token` separately — the agent needs it for the completion step.
   - **Critical:** Plaid is a two-step flow. This tool only starts it. `complete_brokerage_connection()` finishes it.

   **Note:** The `institution` parameter does NOT constrain the SnapTrade/Plaid connection to that specific brokerage. SnapTrade hardcodes `broker=None`, Plaid doesn't filter institutions. The institution only determines which *provider* to use.

8. Return response:
```python
{
    "status": "success",
    "institution": {"slug": "fidelity", "display_name": "Fidelity"},
    "provider": "snaptrade",
    "connection_url": "https://trade.snaptrade.com/connect?token=xxx",  # Unified field: SnapTrade redirectURI or Plaid hosted_link_url. Agent doesn't need to know which.
    "link_token": None,  # Only set for Plaid — needed for complete_brokerage_connection()
    "pre_auth_ids": "[\"auth_123\"]",  # SnapTrade only — JSON-encoded string. Pass back opaquely to complete_brokerage_connection().
    "flow_type": "hosted_ui",  # hosted_ui | hosted_link
    "instructions": [
        "Open the connection URL in your browser",
        "Log in to your Fidelity account",
        "Authorize the connection",
        "Return here when complete — I'll verify the connection"
    ],
    "next_step": "complete_brokerage_connection"  # tells agent what to call next
}
```

**Error cases:**
- Institution not found → return `list_supported_brokerages()` output inline
- No available provider for institution (all providers missing credentials) → error with setup guidance: for Plaid, mention `PLAID_CLIENT_ID`/`PLAID_SECRET` env vars; for SnapTrade, mention env vars OR AWS Secrets Manager configuration (`brokerage/snaptrade/secrets.py:53`)
- All providers in chain failed → error with **aggregated** failure details from ALL providers (not just the last one). Format: `{"status": "error", "message": "All providers failed for {institution}", "provider_errors": {"snaptrade": "User secret invalid — re-register", "plaid": "Not configured (PLAID_CLIENT_ID missing)"}}`. This ensures the most actionable root cause is visible, not hidden by the last-tried provider.
- Unexpected SDK error → wrapped error message via `@handle_mcp_errors`

**Existing code to reuse:**
- `providers/routing.py:resolve_institution_slug()` (line 69) — slug resolution
- `providers/routing.py:is_provider_enabled()` (line 279) — enablement gate (used by `_check_provider_available()`, NOT `is_provider_available()`)
- `providers/routing_config.py:INSTITUTION_PROVIDER_MAPPING` (line 171) — aggregator provider lookup
- `routes/provider_routing_api.py:_get_institution_display_name()` (line 630) — display names (backend, `@lru_cache`)
- `brokerage/snaptrade/connections.py:create_snaptrade_connection_url()` (line 22) — URL generation
- `brokerage/snaptrade/client.py:get_snaptrade_client()` — client factory (safe to call from MCP, builds fresh client per call)
- `brokerage/plaid/client.py:create_hosted_link_token()` (line 73) — Plaid link token
- `brokerage/plaid/client.py:create_client()` — client factory
- `routes/snaptrade.py:_store_snaptrade_item_mapping()` (line 275) — bookkeeping pattern (calls `db_client.store_provider_item`)
- `mcp_tools/common.py:@handle_mcp_errors` + `@require_db` — standard MCP decorators
- `utils/user_resolution.py:resolve_user_id()` — user lookup

---

## Tool 2: `complete_brokerage_connection()`

**Purpose:** Verify and finalize a brokerage connection after the user completes the OAuth/Link flow.

**Parameters:**
- `user_email: str` — User identifier (optional, falls back to default)
- `provider: str` — "snaptrade" or "plaid"
- `link_token: str` — Plaid only — returned by `initiate_brokerage_connection()`
- `pre_auth_ids: str` — **Required** for SnapTrade — JSON-encoded list of authorization IDs from before initiation. Parse via `parse_json_list()` from `mcp_tools/common.py`. If provider is "snaptrade" and `pre_auth_ids` is missing/None/empty-string, return error: "pre_auth_ids is required for SnapTrade — pass the value from initiate_brokerage_connection() response." Do NOT default to `[]` — that would make all existing authorizations appear "new."

**Implementation:**

**SnapTrade path:**
1. Resolve DB user: `resolved_email, _ctx = resolve_user_email(user_email)` (**tuple unpack**) → `user_id = resolve_user_id(resolved_email)`. Integer `user_id` for `AccountRegistry(user_id)` and `store_provider_item(user_id, ...)`. Use `resolved_email` for all provider calls.
2. Get SnapTrade client via `get_snaptrade_client()`. Guard for None.
3. Get user secret via `get_snaptrade_user_secret(resolved_email)`. If None → return error.
4. Get SnapTrade external ID via `get_snaptrade_user_id_from_email(resolved_email)`.
5. Call `client.connections.list_brokerage_authorizations(user_id=snaptrade_user_id, user_secret=user_secret)` — the real authorization source (`brokerage/snaptrade/adapter.py:324`). Returns dict-like authorization objects. Wrap in try/except:
   - 401/403 → `auth_required: True` via `_classify_auth_error()`
   - Other exceptions → `is_outage: True`
6. Extract current IDs: `current_auth_ids = {str(auth.get("id")) for auth in response.body}` (dict-like access, matching existing adapter pattern).
7. Diff: `new_auths = current_auth_ids - set(pre_auth_ids)`. Empty → return pending. Non-empty → confirmed.
8. **Scope ALL output and bookkeeping to `new_auths` only:**
   - `institution`: brokerage name — probe `auth.get("brokerage", {}).get("name")` first; if not present, fall back to `auth.get("name")` or `"unknown"`. The exact shape varies by SDK version; be defensive.
   - `account_count`: `auth.get("accounts")` DOES exist on the `list_brokerage_authorizations()` response (confirmed in `adapter.py:332`). Count accounts from new auths: `sum(len(auth.get("accounts") or []) for auth in auths if str(auth.get("id")) in new_auths)`.
   - **Minimal bookkeeping at completion time** (best-effort, non-fatal):
     - Store provider_items mapping: `with get_db_session() as conn: DatabaseClient(conn).store_provider_item(user_id, "snaptrade", snaptrade_user_id)` — matching `routes/snaptrade.py:275,596`.
     - `ensure_data_source()` only (no `link_accounts_to_data_source()` yet): `registry = AccountRegistry(user_id)` → `registry.ensure_data_source("snaptrade", provider_item_id=auth_id, institution_name=brokerage_name)`. This creates the data_source row but linking accounts is deferred — accounts don't exist in DB yet until positions are refreshed.
   - **Account discovery happens during position refresh.** The existing `PositionService` runs `AccountRegistry.discover_accounts_from_positions()` on refresh (`services/account_registry.py:54`), which creates account rows. Data-source auto-linking only succeeds when there is exactly one `(user_id, provider, institution_slug)` data source (`account_registry.py:620`). **Pre-existing limitation:** multiple SnapTrade authorizations at the same institution may leave accounts unlinked (SnapTrade positions don't carry `authorization_id` back through the payload — `snaptrade_loader.py:899`). This is not introduced by this plan; it's an existing account registry constraint.
   - **`refresh_provider` scoping note:** `get_positions(refresh_provider="snaptrade", format="agent")` refreshes only the specified provider's positions, but the returned result is still a combined multi-provider view (`get_all_positions()` at `position_service.py:519`). **Must use `format="agent"`** — the default `"full"` format doesn't include `provider_status`. Agent format exposes `auth_warnings` (auth issues from any provider, `positions.py:104`), `provider_status` (per-provider health, `positions.py:663`), and `cache_info` — NOT `provider_errors` (that's internal to `PositionService`). The agent should check `auth_warnings` and `provider_status` for the connected provider specifically, and ignore warnings from unrelated providers.
   - Zero accounts at completion time is expected — return success with `next_step` pointing to the position refresh.

**Do NOT use** `list_snaptrade_connections()` (account-derived, misses zero-account auths) or `_sync_snaptrade_data_sources()` (iterates all connections). Use `list_brokerage_authorizations()` scoped to `new_auths`.

**Plaid path:**
1. Resolve DB user: `resolved_email, _ctx = resolve_user_email(user_email)` (**tuple unpack**) → `user_id = resolve_user_id(resolved_email)`. Needed for `AccountRegistry(user_id)`, `store_provider_item(user_id, ...)`, and `store_plaid_token(resolved_email, ...)`.
2. Require `link_token`. Get Plaid client via `create_client()`. Guard for None.
3. Call `wait_for_public_token(link_token, timeout=5, poll=1, client=plaid_client)` from `brokerage/plaid/client.py:136`. Pass client explicitly.
4. TimeoutError → return `{"status": "pending", "message": "User hasn't completed Plaid Link yet."}`.
5. If public_token received → **two-tier error handling** (matching `routes/plaid.py:897-946`):

   **CRITICAL steps (full rollback on failure):**
   a. `ItemPublicTokenExchangeRequest(public_token=public_token)` → `plaid_client.item_public_token_exchange(request)` → `access_token` + `item_id`
   b. `get_institution_info(access_token=access_token, client=plaid_client)` → `(institution_name, institution_id)` (keyword-only args)
   c. **Duplicate guard:** `institution_slug = institution_name.lower().replace(' ', '-')`. Call `list_user_tokens(resolved_email, region_name=AWS_DEFAULT_REGION)` from `brokerage/plaid/secrets.py:104`. If any secret name ends with `/{institution_slug}` → clean up via `remove_plaid_connection(access_token, plaid_client)` → return error.
   d. `store_plaid_token(resolved_email, institution_name, access_token, item_id, region_name=AWS_DEFAULT_REGION)` from `brokerage/plaid/secrets.py:24`.
   e. **except** any failure in b-d: `remove_plaid_connection(access_token, plaid_client)`. If secret was stored, also `secrets_client.delete_secret(SecretId=f"plaid/access_token/{resolved_email}/{institution_slug}", ForceDeleteWithoutRecovery=True)` (matching `routes/plaid.py:1557`, no helper — boto3 direct). Return error.

   **NON-CRITICAL bookkeeping (best-effort, warning log on failure — matching `routes/plaid.py:927-946`):**
   f. `_store_plaid_item_mapping(user_id, item_id, institution_name)` pattern
   g. `AccountRegistry(user_id).ensure_data_source("plaid", provider_item_id=item_id, institution_name=institution_name)` — creates data_source row only. Do NOT call `link_accounts_to_data_source()` here — accounts don't exist in DB yet. Linking happens automatically during position refresh via `PositionService.discover_accounts_from_positions()` (`services/account_registry.py:54`).

**Return response:**
```python
# Success
{
    "status": "success",
    "provider": "snaptrade",
    "connected": True,
    "institution": "Fidelity",
    "account_count": 2,  # from auth.get("accounts") on new authorization objects
    "health": "healthy",
    "next_step": "get_positions(force_refresh=True, refresh_provider='snaptrade', format='agent')"
}

# Pending — Plaid (user hasn't completed Link)
{
    "status": "pending",
    "provider": "plaid",
    "connected": False,
    "message": "User hasn't completed Plaid Link yet. Try again in a few seconds."
}

# Pending — SnapTrade (no new authorization detected)
{
    "status": "pending",
    "provider": "snaptrade",
    "connected": False,
    "message": "No new brokerage authorization detected. User may not have completed the connection yet. Try again in a few seconds."
}

# Auth error (401/403)
{
    "status": "error",
    "provider": "snaptrade",
    "connected": False,
    "message": "SnapTrade authentication failed — user secret may be invalid",
    "auth_required": True,  # classified via _classify_auth_error()
    "is_outage": False
}

# Outage (other errors)
{
    "status": "error",
    "provider": "snaptrade",
    "connected": False,
    "message": "SnapTrade API error: <details>",
    "auth_required": False,
    "is_outage": True
}
```

**Error response note:** Tool 2's error responses use `message` field (not `error`) because they are returned explicitly from within the tool logic, NOT via `@handle_mcp_errors`. The decorator catches unexpected exceptions and returns `{"status": "error", "error": "..."}`. Tool 2's known error paths (pending, auth_required, is_outage, duplicate guard, missing pre_auth_ids) return structured responses directly with `message` for agent-friendly descriptions. Both patterns coexist — the decorator is the safety net, explicit returns are the primary path.

**Existing code to reuse:**
- `brokerage/snaptrade/adapter.py:list_brokerage_authorizations()` pattern (line 324) — real authorization source via SDK
- `brokerage/plaid/client.py:wait_for_public_token()` (line 136) — completion polling (also re-exported via `providers/plaid_loader.py`)
- `brokerage/plaid/client.py:get_institution_info()` (line 162) — institution lookup (**keyword-only**: `access_token=`, `client=`)
- `brokerage/plaid/secrets.py:store_plaid_token()` — AWS Secrets Manager storage
- `routes/plaid.py:_store_plaid_item_mapping()` (line 250) — provider_items bookkeeping pattern
- `routes/snaptrade.py:_store_snaptrade_item_mapping()` (line 275) — provider_items bookkeeping pattern
- `services/account_registry.py:AccountRegistry` — `ensure_data_source()` (completion only; `link_accounts_to_data_source()` runs automatically during position refresh)

---

## Tool 3: `list_supported_brokerages()`

**Purpose:** Return the list of supported institutions and which provider handles each.

**Parameters:**
- `category: str` — Filter by type ("brokerage", "bank", "digital_brokerage", "robo_advisor", "all"). Default: "all"

**Implementation:**
- **Cannot delegate to `get_supported_institutions()`** — it's an `async def` FastAPI route, and MCP tools are synchronous. Instead, reimplement the same logic synchronously (it's ~30 lines, no async I/O):
  1. Iterate `INSTITUTION_PROVIDER_MAPPING.items()`
  2. For each institution, determine provider availability via the shared `_check_provider_available(provider)` helper (defined in `mcp_tools/connections.py`). This checks `is_provider_enabled()` first, then ALWAYS constructs the client as definitive check — same helper and same logic as `initiate_brokerage_connection()` (see Tool 1 step 5). **Memoize per call:** cache `(available, client)` results in a local dict — only 2 providers exist (snaptrade, plaid), so at most 2 client constructions per MCP call. NOT module-level (availability can change between calls).
  3. Get display name via `_get_institution_display_name(slug)` from `routes/provider_routing_api.py:630` (`@lru_cache`, sync, safe to import)
  4. Get categories via `_get_institution_categories(slug, all_configured_providers)` from `routes/provider_routing_api.py:655` — pass ALL configured providers (not just available ones), because this helper adds `snaptrade_supported`/`plaid_supported` tags based on the provider list. Using only available providers would drop tags for temporarily-unconfigured providers.
  5. Get recommended provider via `_get_recommended_provider(slug, available_providers)` from `routes/provider_routing_api.py:598` — pass only AVAILABLE providers here, since recommendation must be actionable
- **Include ALL institutions** — not just those with available providers. Mark `available: False` for institutions where no provider has credentials. The async route skips unavailable ones (line 365), but the MCP tool should show them so the agent can explain what's missing.
- **Recommendation guard:** For unavailable institutions, set `recommended_provider: null` — do NOT call `_get_recommended_provider(slug, [])` which falsely returns `"plaid"` when given an empty provider list (line 609)
- Apply category filter if provided
- **No new name mapping** — reuse `_get_institution_display_name()` directly

**Return response** — MCP wrapper around `SupportedInstitution` fields, with `available` and `status` added (standard MCP response shape):
```python
{
    "status": "success",
    "institutions": [
        {
            "slug": "fidelity",
            "name": "Fidelity",
            "categories": ["brokerage", "investment"],
            "providers": ["snaptrade", "plaid"],  # only AVAILABLE providers (matching REST API semantics)
            "all_providers": ["snaptrade", "plaid"],  # all configured providers (may differ if credentials missing)
            "recommended_provider": "snaptrade",  # null if no providers available
            "available": True  # at least one provider has credentials
        },
        ...
    ],
    "available_count": 15,
    "total_count": 18
}
```
**Note:** This is intentionally a superset of `SupportedInstitution` — MCP tools wrap responses in `{status, ...}` and the `available` flag is needed for agent decision-making (the REST endpoint skips unavailable institutions entirely).

**Existing code to reuse (all sync, safe to import directly):**
- `providers/routing_config.py:INSTITUTION_PROVIDER_MAPPING` (line 171) — source of truth
- `providers/routing.py:is_provider_enabled()` (line 279) — enablement gate (used by shared `_check_provider_available()`)
- `brokerage/snaptrade/client.py:get_snaptrade_client()` + `brokerage/plaid/client.py:create_client()` — definitive availability via client construction
- `routes/provider_routing_api.py:_get_institution_display_name()` (line 630) — display names (`@lru_cache`)
- `routes/provider_routing_api.py:_get_institution_categories()` (line 655) — categories
- `routes/provider_routing_api.py:_get_recommended_provider()` (line 598) — provider recommendation

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `mcp_tools/connections.py` | **Create** | 3 tool implementations (~300-350 lines) |
| `mcp_server.py` | **Modify** | Register 3 new tools |
| `providers/routing_config.py` | **Modify** | Add missing slug aliases (m1_finance, betterment, wealthfront) |
| `tests/mcp_tools/test_connections.py` | **Create** | Unit tests (~20-25 tests) |

No new flags file needed — these are operational tools returning simple `{status, ...}` responses.

---

## What We're NOT Building

- **`disconnect_brokerage()`** — useful but not part of the onboarding flow. Phase 2.
- **`check_connection_status()`** — dropped per Codex review. `complete_brokerage_connection()` handles post-OAuth verification. After the agent runs `get_positions(force_refresh=True, refresh_provider=<provider>, format='agent')`, existing `list_accounts()` shows the new accounts (accounts are created during position refresh via `discover_accounts_from_positions()`, not at connection time).
- **Agent-format responses** — these are operational tools, not analytical. Simple `{status, ...}` responses like `list_accounts`.
- **Frontend changes** — the frontend connection flow already works. These tools let the agent guide users in CLI/chat context.
- **Direct provider connection flows** (Schwab OAuth CLI, IBKR Gateway probe) — these are separate setup paths. But Schwab/IBKR institutions connect fine via SnapTrade/Plaid aggregators — this tool handles that.
- **Connection state tracking** — no temp DB table or Redis. SnapTrade connections verified via `list_brokerage_authorizations()` before/after diff. Plaid connections verified via `link_token` polling.

---

## Codex Findings — Resolution

### v1 Findings (6H 4M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Plaid flow incomplete — plan threw away link_token | High | `initiate_brokerage_connection()` now returns `link_token`. `complete_brokerage_connection()` handles poll → exchange → store. |
| 2 | Direct-provider branch dead | High | **v3:** Removed entirely. Schwab/IBKR connect via aggregators (SnapTrade/Plaid) in `INSTITUTION_PROVIDER_MAPPING`. Direct providers are for position/trade routing post-connection, not initial linking. |
| 3 | Institution resolver in wrong file and weak | High | Fixed file ref to `providers/routing.py:69`. Prerequisite step adds missing aliases. |
| 4 | Institution parameter doesn't constrain connection | High | Documented explicitly: institution only selects provider, doesn't filter the OAuth/Link flow. |
| 5 | SnapTrade auto-register overstated | High | Added explicit error handling for "user exists, secret invalid" case. Returns actionable error. |
| 6 | MCP wrapper skips HTTP route behavior | High | **v3:** Tools use `@require_db` + `resolve_user_id()` (standard MCP pattern). Replicates: client init, provider_items storage, token exchange, data_source sync. |
| 7 | Plaid health signal bogus (provider_items.updated_at) | Medium | Dropped. Uses `wait_for_public_token()` for Plaid, `list_brokerage_authorizations()` for SnapTrade. |
| 8 | check_connection_status() duplicates list_accounts() | Medium | Dropped. Replaced with `complete_brokerage_connection()`. |
| 9 | check_snaptrade_connection_health() returns [] on errors | Medium | **v3→v18:** Final: uses `list_brokerage_authorizations()` (real auth source). Try/except with `_classify_auth_error()`. |
| 10 | list_supported_brokerages() creates third name source | Medium | Imports `_get_institution_display_name()` directly. No new mapping. |

### v2 Findings (3H 3M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 11 | Direct-provider fix blocks aggregator connections for Schwab/IBKR | High | **v3:** Removed `_get_direct_provider()` / `not_supported` branch entirely. All institutions connect via aggregators. |
| 12 | Plaid exchange API contract wrong | High | **v3:** Fixed to `ItemPublicTokenExchangeRequest(public_token=...)` wrapper. `get_institution_info` called with keyword-only args `(access_token=..., client=...)`. |
| 13 | list_supported_brokerages() can't delegate to async route | High | **v3:** Reimplements the logic synchronously (~30 lines). Imports the sync helper functions directly. Includes all institutions (marks unavailable ones). |
| 14 | check_snaptrade_connection_health() eats errors | Medium | **v3→v18:** Final: uses `list_brokerage_authorizations()` directly. |
| 15 | Missing @require_db and standard user resolution | Medium | **v3:** Tools use `@handle_mcp_errors` + `@require_db` decorators, `resolve_user_id()` for user context. |
| 16 | Response shape doesn't match SupportedInstitution model | Medium | **v3:** Response uses `name` (not `display_name`) to match `SupportedInstitution` model. |

### v3 Findings (0H 4M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 17 | User resolution uses wrong function | Medium | **v4:** Two-step pattern: `resolve_user_email(user_email)` → `resolve_user_id(resolved_email)` with `format_missing_user_error()`. Matches `portfolio_management.py:29`. |
| 18 | Response shape is superset of SupportedInstitution | Medium | **v4:** Documented as intentional. MCP tools wrap in `{status, ...}` and add `available` flag. REST endpoint skips unavailable institutions; MCP includes them. |
| 19 | Unavailable institutions get bogus plaid recommendation | Medium | **v4:** Skip `_get_recommended_provider()` for unavailable institutions, set to `null`. |
| 20 | Client factories can return None | Medium | **v4:** Explicit `None` guard after `get_snaptrade_client()` and `create_client()`. Return descriptive error with which env vars are missing. |

### v4 Findings (2H 2M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 21 | Plaid completion never creates/guards client | High | **v5:** Plaid path now explicitly creates client via `create_client()` with None guard, passes to all calls via `client=` kwarg. No module-level singleton reliance. |
| 22 | Env-var check misses AWS Secrets Manager credentials | High | **v5→v14:** Evolved through multiple revisions. Final: `_check_provider_available()` always constructs client as definitive check. `is_provider_enabled()` gate only. |
| 23 | `providers` field changed semantics (configured vs available) | Medium | **v5:** Split into `providers` (available only, matching REST semantics) and `all_providers` (all configured). No ambiguity. |
| 24 | SnapTrade 401 mislabeled as outage | Medium | **v5:** Error classification via `_classify_auth_error()` from `common.py:83`. 401/403 → `auth_required: True`, others → `is_outage: True`. |

### v5 Findings (1H 2M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 25 | list_supported_brokerages availability check insufficient | High | **v6→v14:** Shared `_check_provider_available()` helper with client construction, used by both tools. |
| 26 | Completion bookkeeping missing link_accounts_to_data_source() | Medium | **v6→v27:** `ensure_data_source()` at completion only. `link_accounts_to_data_source()` removed — accounts don't exist yet. Linking happens automatically during position refresh via `discover_accounts_from_positions()`. |
| 27 | SnapTrade empty list ambiguous (no secret vs no accounts) | Medium | **v6:** Pre-check `get_snaptrade_user_secret()` before listing. Disambiguates "not registered" from "no accounts." |

### v6 Findings (1H 2M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 28 | Fallback availability bypasses ENABLED_PROVIDERS | High | **v7:** `_check_provider_available()` checks `is_provider_enabled()` first. Only falls back to client factory if provider is enabled but env vars missing. Never resurrects disabled providers. |
| 29 | SnapTrade brokerage_authorization can be dict | Medium | **v7:** Normalize authorization_id with `str(...).strip()` matching `routes/snaptrade.py:307` pattern before using as provider_item_id. |
| 30 | BofA alias resolves to merrill instead of bank_of_america | Medium | **v7:** Prerequisite fixes `"bank of america"` → `"bank_of_america"` and `"bofa"` → `"bank_of_america"`. Merrill aliases unchanged. Dict ordering ensures longer match first. |

### v7 Findings (0H 2M 1L)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 31 | SnapTrade authorization_id normalization still wrong — str() stringifies dict | Medium | **v8:** Use shape-aware normalization from `connections.py:134` — check if value is dict, extract `id` key. Don't use raw `str()`. |
| 32 | `"u.s. bank"` alias missing — display name "U.S. Bank" won't resolve | Medium | **v8:** Added `"u.s. bank": "us_bank"` alias to prerequisite. |
| 33 | `hosted_oauth` doesn't match existing API vocabulary (`hosted_ui`) | Low | **v8:** Changed to `hosted_ui` everywhere, matching `routes/provider_routing_api.py:552`. |

### v8 Findings (0H 2M 1L)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 34 | Plaid has no AWS fallback — plan overstates | Medium | **v9:** AWS fallback only for SnapTrade. Plaid is env-var only (`brokerage/config.py:22`). Documented explicitly in `_check_provider_available()`. |
| 35 | Plaid redirect/webhook URIs unspecified — placeholder defaults | Medium | **v9:** Explicitly uses `FRONTEND_BASE_URL` + `BACKEND_BASE_URL` from `settings.py`, matching `routes/plaid.py:742-743`. |
| 36 | Categories helper leaks provider semantics | Low | **v9:** Pass `all_configured_providers` to `_get_institution_categories()` (for accurate tags), `available_providers` to `_get_recommended_provider()` (for actionable recommendation). |

### v9 Findings (0H 2M 1L)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 37 | SnapTrade completion can't prove NEW connection completed | Medium | **v10:** Before/after authorization snapshot. `initiate` captures `pre_auth_ids`, `complete` diffs against current to find new authorization. Empty diff → pending. |
| 38 | Plaid same-institution token overwrite | Medium | **v10:** Pre-check `provider_items` for existing Plaid connection to same institution. Reject with "disconnect first" error. Existing storage limitation documented. |
| 39 | `_check_provider_available()` not memoized — repeated AWS hits | Low | **v10:** Per-call memoization via local dict in `list_supported_brokerages()`. Not module-level (availability can change between calls). |

### v10 Findings (0H 2M 1L)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 40 | SnapTrade pre_auth_ids uses raw authorization_id (can be dict) | Medium | **v11:** Shared `_normalize_snaptrade_auth_id()` helper used in both initiate (capture) and complete (diff). Shape-aware: dict → extract `id` key, string → use directly. |
| 41 | Plaid overwrite guard on provider_items is unreliable | Medium | **v11:** Authoritative check against AWS secrets path via `list_user_tokens(resolved_email, region_name)`. `provider_items` is auxiliary only. |
| 42 | Plaid URL field name inconsistent (connection_url vs hosted_link_url) | Low | **v11:** Unified `connection_url` field in MCP response — agent doesn't need to know internal field names. Maps SnapTrade `redirectURI` and Plaid `hosted_link_url` to same field. |

### v11 Findings (0H 3M 1L)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 43 | Plaid overwrite guard runs after exchange — orphaned item | Medium | **v12:** If duplicate detected after exchange, clean up orphaned item via `item_remove()` / `remove_plaid_connection()` before returning error. |
| 44 | SnapTrade completion uses account-derived auth list (misses zero-account auths) | Medium | **v12:** Use `client.connections.list_brokerage_authorizations()` directly (real auth source, per `adapter.py:324`). Both initiate capture and complete diff use this. |
| 45 | pre_auth_ids MCP parsing unspecified | Medium | **v12:** Parse via `parse_json_list()` from `mcp_tools/common.py`. Documented in parameter description. |
| 46 | Plaid initiate still mentions hosted_link_url separately | Low | **v12:** Plaid `hosted_link_url` mapped into unified `connection_url` field. Only `link_token` returned separately. |

### v12 Findings (0H 4M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 47 | Availability too weak — env check doesn't catch SDK/config/AWS failures | Medium | **v13:** `_check_provider_available()` actually constructs the client as definitive check. Returns `(available, client)` tuple to avoid double-construction. Also checks boto3 for Plaid persistence. |
| 48 | First-time SnapTrade user has no secret for pre_auth capture | Medium | **v13:** Check `get_snaptrade_user_secret()` first. No secret → `pre_auth_ids=[]`. Secret exists → call `list_brokerage_authorizations()`. |
| 49 | Plaid orphan cleanup only covers duplicate case | Medium | **v13:** General try/except wrapping all post-exchange steps. ANY failure → `remove_plaid_connection(access_token, client)` cleanup before re-raising. |
| 50 | BofA alias change is global regression | Medium | **v13:** DO NOT change global aliases. Handle BofA/Merrill ambiguity as scoped disambiguation in `initiate_brokerage_connection()` only — detect "bank of america" in input, offer interactive choice. |

### v13 Findings (1H 2M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 51 | Availability still short-circuits on env vars | High | **v14:** `_check_provider_available()` ALWAYS constructs client. Enablement checked via `is_provider_enabled()` only. Client returned in tuple for reuse. |
| 52 | BofA disambiguation broken — slug resolver normalizes `bank_of_america` → merrill | Medium | **v14:** Exact key match against `INSTITUTION_PROVIDER_MAPPING` FIRST (before slug resolution). `bank_of_america` matches directly. If slug resolves to `merrill` but input contains "bank of america" or "bofa", return disambiguation response. |
| 53 | Plaid cleanup incomplete after `store_plaid_token()` | Medium | **v14:** Cleanup flag pattern: track `secret_stored` and `item_mapped` bools. Except block deletes AWS secret + provider_items row for steps that succeeded, matching `routes/plaid.py:1555` delete flow. |

### v14 Findings (2H 2M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 54 | `delete_plaid_token()` doesn't exist | High | **v15:** Use `boto3` `secrets_client.delete_secret(SecretId=secret_path, ForceDeleteWithoutRecovery=True)` directly, matching `routes/plaid.py:1557`. Build `secret_path = f"plaid/access_token/{resolved_email}/{institution_slug}"`. |
| 55 | Plaid rollback scope too broad — data-source sync is non-fatal in route | High | **v15:** Two-tier error handling. Critical steps (exchange, lookup, guard, secret storage) get full rollback. Non-critical (provider_items, AccountRegistry) are best-effort with warning log, matching `routes/plaid.py:943`. |
| 56 | `list_user_tokens()` requires `region_name` + secret key normalizes institution | Medium | **v15:** Pass `region_name=AWS_DEFAULT_REGION`. Normalize institution: `institution_slug = institution_name.lower().replace(' ', '-')`. Check secret names ending with `/{institution_slug}`. |
| 57 | Availability text still inconsistent — Tool 3 + reuse lists reference `is_provider_available()` | Medium | **v15:** Tool 3 text updated to reference `_check_provider_available()` with client construction. All `is_provider_available()` references removed from reuse lists, replaced with `is_provider_enabled()` + client factories. |

### v15 Findings (0H 3M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 58 | BofA disambiguation branch is dead code — exact-key-first resolves correctly | Medium | **v16:** Removed dead disambiguation branch. Documented why exact-key-first handles BofA correctly (space→underscore normalization → exact key match). "bofa" → merrill kept as accepted existing behavior. |
| 59 | Plaid availability overclaims — `create_client()` doesn't prove AWS connectivity | Medium | **v16:** Documented as accepted limitation. Full AWS connectivity check impractical (not done by REST routes either). Failures caught at connection time by `complete_brokerage_connection()` try/except with cleanup. |
| 60 | `is_provider_available()` still in revision-history tables | Medium | **v16:** All historical references updated to reflect final approach (`is_provider_enabled()` + client construction). |

### v16 Findings (0H 2M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 61 | BofA fix only works for exact input — phrases like "bank of america checking" still → merrill | Medium | **v17:** After slug resolution, if resolved to `merrill` AND original input contains `"bank of america"` substring, override to `bank_of_america`. Scoped to `initiate_brokerage_connection()` only. |
| 62 | SnapTrade completion doesn't scope to new_auths — inflates account_count with existing connections | Medium | **v17:** All output and bookkeeping scoped to `new_auths` set. Account count, institution name, and data-source sync filtered by new authorization IDs only. |

### v17 Findings (1H 2M)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 63 | SnapTrade completion contradicts itself — old list_snaptrade_connections text alongside new list_brokerage_authorizations | High | **v18:** Clean rewrite of Tool 2 SnapTrade section. Single flow: `list_brokerage_authorizations()` → diff `new_auths` → scope all output/bookkeeping. All references to `list_snaptrade_connections()` and `_sync_snaptrade_data_sources()` removed. |
| 64 | BofA override overbroad + prerequisite contradicts Tool 1 | Medium | **v18:** Removed override entirely. Documented exact-key-first resolution handles common cases. "bank of america checking" → merrill accepted as rare edge case. Prerequisite and Tool 1 now consistent. |
| 65 | pre_auth_ids extraction describes wrong payload shape | Medium | **v18:** Clean rewrite specifies `str(auth.id)` from authorization objects (top-level `id` field), not `brokerage_authorization` from account objects. |

**Tier gating note:** The HTTP routes use `_require_paid_user` (FastAPI dependency). MCP tools run in a trusted context (MCP server is behind auth). If tier enforcement is needed at the MCP layer, use the existing pattern from `mcp_server.py` credential gates (env var checks). This matches how other MCP tools handle access control.

---

## Implementation Order

1. **Prerequisite:** Add missing slug aliases to `routing_config.py`
2. `list_supported_brokerages()` — simplest, delegates to existing routing API logic
3. `initiate_brokerage_connection()` — core tool, two provider paths with bookkeeping
4. `complete_brokerage_connection()` — post-OAuth verification + Plaid token exchange
5. Register all 3 in `mcp_server.py`
6. Tests

**Estimated effort:** 2-3 days. More than v1 estimate due to Plaid two-step flow and bookkeeping replication.

---

## Verification

1. **Unit tests** — mock SnapTrade/Plaid clients, verify routing logic, error handling, provider_items bookkeeping
2. **Manual test (SnapTrade):** `list_supported_brokerages()` → `initiate_brokerage_connection("fidelity")` (save `pre_auth_ids` from response) → open URL → complete OAuth → `complete_brokerage_connection(provider="snaptrade", pre_auth_ids=<saved>)` → `get_positions(force_refresh=True, refresh_provider="snaptrade", format="agent")` → `list_accounts()` (accounts populated after refresh)
3. **Manual test (Plaid):** `initiate_brokerage_connection("chase")` → open URL → `complete_brokerage_connection(provider="plaid", link_token="link-xxx")` → verify token exchange + storage → `get_positions(force_refresh=True, refresh_provider="plaid", format="agent")` → `list_accounts()`
4. **Edge cases:** unknown institution, missing provider credentials, SnapTrade secret invalid, Plaid link_token expired, user hasn't completed Link yet (pending state), SnapTrade API outage vs no connections
