# Agent-Guided Brokerage Connection — MCP Tools Plan

**Date:** 2026-03-22
**Status:** PLAN (v37 — clean rewrite after bug fixes landed)
**History:** v1-v31 FAIL (104 findings). Bugs 1-3 fixed in `955d4c81`. v32 FAIL (0H 6M). v33 FAIL (1C 2H 3M 1L). v34 FAIL (0H 2M 1L). All addressed below.

## Context

When an AI agent helps a new user onboard ("I have Fidelity"), there's no MCP tool to initiate or monitor a brokerage connection. The CSV import path has a full 5-tool playbook (`normalizer_builder.py`), but API-based connections require the web UI. All backend infrastructure exists — the gap is purely at the MCP layer.

**Goal:** 3 MCP tools: `initiate_brokerage_connection`, `complete_brokerage_connection`, `list_supported_brokerages`.

**Agent workflow (SnapTrade):**
```
User: "I have Fidelity"
  → Agent calls initiate_brokerage_connection("fidelity")
  → Gets back SnapTrade connection URL + pre_auth_ids
  → Tells user: "Open this link to connect your Fidelity account"
  → User completes OAuth in browser
  → Agent calls complete_brokerage_connection(provider="snaptrade", pre_auth_ids=<from initiate>)
  → Agent calls get_positions(force_refresh=True, refresh_provider="snaptrade", format="agent")
  → Agent calls list_accounts() to confirm
```

**Plaid variant:**
```
User: "I have Chase"
  → Agent calls initiate_brokerage_connection("chase")
  → Gets back Plaid hosted link URL + link_token
  → User completes Plaid Link in browser
  → Agent calls complete_brokerage_connection(provider="plaid", link_token="link-xxx")
  → Agent calls get_positions(force_refresh=True, refresh_provider="plaid", format="agent")
```

---

## Prerequisites (DONE — committed in `955d4c81`)

The following bugs were fixed before this plan can be implemented:
- `resolve_institution_slug()` now normalizes hyphens (`.replace("-", " ")`)
- Missing aliases added: `e trade`, `m1 finance`, `betterment`, `wealthfront`, `u.s. bank`
- `is_provider_available("snaptrade")` now falls back to AWS Secrets Manager via `providers.snaptrade_loader.get_snaptrade_client()`
- `wait_for_public_token()` guards partial sessions (no more IndexError)

---

## Tool 1: `initiate_brokerage_connection()`

**Purpose:** Resolve institution → provider, generate connection URL.

**Parameters:**
- `institution: str` — Institution slug or name ("fidelity", "charles_schwab", "chase")
- `user_email: str` — Optional, falls back to `RISK_MODULE_USER_EMAIL`

**Implementation (in `mcp_tools/connections.py`):**

1. **Resolve user:** `resolved_email, _ctx = resolve_user_email(user_email)` (returns tuple, must unpack). If `resolved_email` is None, return `{"status": "error", "error": format_missing_user_error(_ctx)}`. Then `user_id = resolve_user_id(resolved_email)`. Decorated with `@handle_mcp_errors` + `@require_db`.

2. **Resolve institution — exact key first, then slug resolver:**
   a. Normalize: `institution.strip().rstrip(".,;:!?").lower()` → collapse whitespace via `" ".join(s.split())` → `.replace(" ", "_").replace("-", "_")` → try as exact key in `INSTITUTION_PROVIDER_MAPPING`.
   b. If no exact match, call `resolve_institution_slug(institution)` from `providers/routing.py:69`. Hyphen normalization is built in (fixed in `955d4c81`).
   c. If BOTH exact match and slug resolver return None/no match → return error with supported institution list from `list_supported_brokerages()`.
   d. BofA/Merrill: exact-key-first resolves `"bank of america"` → `bank_of_america` correctly. `"bofa"` → `merrill` is accepted existing behavior.

3. **Look up provider chain** via `INSTITUTION_PROVIDER_MAPPING[slug]`.

4. **Loop through providers with fallback.** For each provider:
   a. Check `is_provider_enabled(provider)`. Skip if disabled.
   b. Check `is_provider_available(provider)`. Skip if unavailable. (SnapTrade AWS fallback built in — `955d4c81`.) **Plaid note:** `is_provider_available("plaid")` only checks env vars. The fallback loop's Plaid path (step 6) guards `create_client()` for None (SDK missing). Additionally, `complete_brokerage_connection()` depends on `boto3` for token storage — if boto3 is missing, completion fails with cleanup. Tool 3 (`list_supported_brokerages`) checks all three (env vars + SDK + boto3) before marking Plaid available.
   c. Attempt connection URL creation inside try/except. On failure, log warning and continue to next provider.
   d. If ALL fail, return MCP-standard error with aggregated details: `{"status": "error", "error": "All providers failed for {institution}", "provider_errors": {"snaptrade": "disabled", "plaid": "SDK not installed"}}`. Include ALL providers from the chain — record skipped providers too. This ensures the error dict is never empty.

5. **SnapTrade path:**
   - Get client via `get_snaptrade_client()` from `brokerage/snaptrade/client.py`. Guard for None.
   - **Pre-auth snapshot:** Get SnapTrade external user_id via `snaptrade_user_id = get_snaptrade_user_id_from_email(resolved_email)` from `brokerage/snaptrade/users.py:20` — this is the SnapTrade-side identifier, NOT the DB integer `user_id`. Check `get_snaptrade_user_secret(resolved_email)`. No secret → `pre_auth_ids = []`. Secret exists → call `client.connections.list_brokerage_authorizations(user_id=snaptrade_user_id, user_secret=user_secret)` → extract `pre_auth_ids = [str(auth.get("id")) for auth in response.body]`.
   - Call `create_snaptrade_connection_url(resolved_email, client)`.
   - Store provider_items: replicate `_store_snaptrade_item_mapping()` from `routes/snaptrade.py:275`.
   - Return `connection_url` + `pre_auth_ids` (JSON-encoded string).

6. **Plaid path:**
   - **Three-part availability gate (same as Tool 3):** verify `create_client()` returns non-None (SDK) AND `import boto3` succeeds (required for `store_plaid_token()`/`list_user_tokens()` via `_require_boto3()`). If either fails, skip Plaid and continue to next provider in fallback loop. This prevents starting Link when completion cannot persist tokens.
   - Hash email: `hashlib.sha256(resolved_email.encode()).hexdigest()[:16]`.
   - Call `create_hosted_link_token(client, user_hash, redirect_uri=f"{FRONTEND_BASE_URL}/plaid/success", webhook_uri=f"{BACKEND_BASE_URL}/plaid/webhook")`.
   - Return unified `connection_url` (from `hosted_link_url`) + `link_token`.

7. **Return response:**
```python
{
    "status": "success",
    "institution": {"slug": "fidelity", "display_name": "Fidelity"},
    "provider": "snaptrade",
    "connection_url": "https://trade.snaptrade.com/connect?token=xxx",
    "link_token": None,       # Plaid only
    "pre_auth_ids": "[...]",  # SnapTrade only, JSON-encoded
    "flow_type": "hosted_ui", # hosted_ui | hosted_link
    "instructions": ["Open the connection URL in your browser", "..."],
    "next_step": "complete_brokerage_connection"
}
```

**Existing code to reuse:**
- `providers/routing.py:resolve_institution_slug()` (line 69), `is_provider_enabled()` (line 279), `is_provider_available()` (line 300)
- `providers/routing_config.py:INSTITUTION_PROVIDER_MAPPING` (line 171)
- `routes/provider_routing_api.py:_get_institution_display_name()` (line 630)
- `brokerage/snaptrade/connections.py:create_snaptrade_connection_url()` (line 22)
- `brokerage/plaid/client.py:create_hosted_link_token()` (line 73), `create_client()`
- `routes/snaptrade.py:_store_snaptrade_item_mapping()` (line 275)
- `mcp_tools/common.py:@handle_mcp_errors`, `@require_db`, `parse_json_list()`
- `utils/user_context.py:resolve_user_email()` (line 89, returns tuple)
- `utils/user_resolution.py:resolve_user_id()`

---

## Tool 2: `complete_brokerage_connection()`

**Purpose:** Verify and finalize a brokerage connection after OAuth/Link flow.

**Parameters:**
- `user_email: str` — Optional
- `provider: str` — "snaptrade" or "plaid"
- `link_token: str` — Plaid only
- `pre_auth_ids: str` — **Required** for SnapTrade. JSON-encoded list. Error if missing (prevents false positives from empty default).

**SnapTrade path:**
1. `resolved_email, _ctx = resolve_user_email(user_email)`. If `resolved_email` is None, return `{"status": "error", "error": format_missing_user_error(_ctx)}`. Then `user_id = resolve_user_id(resolved_email)`.
2. Get client via `get_snaptrade_client()`. Guard for None.
3. Get secret via `get_snaptrade_user_secret(resolved_email)`. None → error.
4. Get external ID via `get_snaptrade_user_id_from_email(resolved_email)`.
5. Call `client.connections.list_brokerage_authorizations(user_id=snaptrade_user_id, user_secret=user_secret)`. Wrap in try/except:
   - 401/403 → `auth_required: True` via `_classify_auth_error()`
   - Other → `is_outage: True`
6. Extract: `current_auth_ids = {str(auth.get("id")) for auth in response.body}`.
7. Parse `pre_auth_ids` via `parse_json_list(pre_auth_ids)` from `mcp_tools/common.py` → `list[str]`. Then diff: `new_auths = current_auth_ids - set(parsed_pre_auth_ids)`. Empty → pending. Non-empty → confirmed. (Do NOT do `set(pre_auth_ids)` on the raw JSON string — that produces a set of characters.)
8. **Scope to `new_auths` only:**
   - `institution`: probe `auth.get("brokerage", {}).get("name")`, fallback to `auth.get("name")` or `"unknown"`.
   - `account_count`: `sum(len(auth.get("accounts") or []) for auth in auths if str(auth.get("id")) in new_auths)`.
   - Bookkeeping (best-effort, wrapped in try/except with warning log):
     - `with get_db_session() as conn: DatabaseClient(conn).store_provider_item(user_id, "snaptrade", snaptrade_user_id)` — `store_provider_item` is a `DatabaseClient` method, not standalone.
     - For each new auth ID: `AccountRegistry(user_id).ensure_data_source("snaptrade", provider_item_id=auth_id, institution_name=brokerage_name)` — must pass `institution_name` per authorization (account discovery matches on `provider + institution_slug`).
     - No `link_accounts_to_data_source()` — deferred to position refresh via `discover_accounts_from_positions()`.
   - Account discovery happens during `get_positions(refresh_provider=..., format="agent")` via `discover_accounts_from_positions()`. **Note:** if the newly connected account has no holdings (empty or cash-only), position service may return empty/raise (`position_service.py:1877`). The agent should treat this as normal for new connections — advise user to wait and retry, or check `list_accounts()` which may still be empty until holdings appear. This is a pre-existing limitation (cash-only accounts documented in Known Limitations).

**Do NOT use** `list_snaptrade_connections()` or `_sync_snaptrade_data_sources()`.

**Plaid path:**
1. `resolved_email, _ctx = resolve_user_email(user_email)`. If `resolved_email` is None, return `{"status": "error", "error": format_missing_user_error(_ctx)}`. Then `user_id = resolve_user_id(resolved_email)`.
2. Require `link_token`. Get client via `create_client()`. Guard for None.
3. Call `wait_for_public_token(link_token, timeout=5, poll=1, client=plaid_client)`. Partial sessions are safe (guarded in `955d4c81`).
4. TimeoutError → pending.
5. If public_token → **two-tier error handling:**

   **Critical (rollback on failure):**
   a. `ItemPublicTokenExchangeRequest(public_token=...)` → `plaid_client.item_public_token_exchange(request)` → `access_token` + `item_id`.
   b. `get_institution_info(access_token=access_token, client=plaid_client)` → `(institution_name, institution_id)` (keyword-only args).
   c. **Duplicate guard:** `institution_slug = institution_name.lower().replace(' ', '-')`. Call `list_user_tokens(resolved_email, region_name=AWS_DEFAULT_REGION)` → returns list of secret names (e.g. `plaid/access_token/user@email/chase-bank`). Check if any name ends with `/{institution_slug}` — institution-specific match, NOT "any token exists." If match found → `remove_plaid_connection(access_token, plaid_client)` → return error "Already connected to {institution} via Plaid."
   d. `store_plaid_token(resolved_email, institution_name, access_token, item_id, region_name=AWS_DEFAULT_REGION)`.
   e. **except** b-d: `remove_plaid_connection(access_token, plaid_client)`. If secret stored, also `secrets_client.delete_secret(SecretId=..., ForceDeleteWithoutRecovery=True)`.

   **Non-critical (best-effort):**
   f. `_store_plaid_item_mapping(user_id, item_id, institution_name)`.
   g. `AccountRegistry(user_id).ensure_data_source("plaid", provider_item_id=item_id, institution_name=institution_name)`.

**Error response note:** All error responses use the MCP standard `{"status": "error", "error": "..."}` shape, matching `@handle_mcp_errors` and `mcp_tools/README.md`. Known error paths (pending, auth_required, is_outage, duplicate guard, missing pre_auth_ids) return explicitly with additional fields (`auth_required`, `is_outage`, `provider_errors`) alongside the standard `error` field.

---

## Tool 3: `list_supported_brokerages()`

**Purpose:** Return supported institutions with provider availability.

**Parameters:**
- `category: str` — "brokerage", "bank", "digital_brokerage", "robo_advisor", "all". Default: "all"

**Implementation:**
- Iterate `INSTITUTION_PROVIDER_MAPPING.items()`.
- Check availability: call `is_provider_available(p)` first (SnapTrade AWS fallback built in). For Plaid, additionally verify: (1) `create_client()` returns non-None (SDK installed + credentials valid), AND (2) `import boto3` succeeds (required by `store_plaid_token()` and `list_user_tokens()` in `brokerage/plaid/secrets.py` which call `_require_boto3()`). Both must pass or Plaid is marked unavailable — prevents advertising a provider where users can start Link but never complete. Cache per-call.
- Display names via `_get_institution_display_name(slug)` (sync, `@lru_cache`).
- Categories via `_get_institution_categories(slug, all_configured_providers)` — pass ALL configured providers.
- Recommendation: if `available_providers` is non-empty, call `_get_recommended_provider(slug, available_providers)`. If empty, set `recommended_provider = None` — do NOT call the helper, which falsely returns `"plaid"` for empty lists (`provider_routing_api.py:600`).
- Include ALL institutions (mark `available: False` for unconfigured ones).
- Apply category filter if provided.
- Memoize availability per-call via local dict (only 2 providers checked).

**Response:**
```python
{
    "status": "success",
    "institutions": [
        {
            "slug": "fidelity",
            "name": "Fidelity",
            "categories": ["brokerage", "investment"],
            "providers": ["snaptrade", "plaid"],
            "all_providers": ["snaptrade", "plaid"],
            "recommended_provider": "snaptrade",
            "available": True
        }, ...
    ],
    "available_count": 12,  # example — depends on configured credentials
    "total_count": 16       # matches current INSTITUTION_PROVIDER_MAPPING size
}
```

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `mcp_tools/connections.py` | **Create** | 3 tool implementations (~300 lines) |
| `mcp_server.py` | **Modify** | Register 3 new tools |
| `tests/mcp_tools/test_connections.py` | **Create** | Unit tests (~20-25 tests) |

---

## Known Limitations (pre-existing, not introduced by this plan)

- **Multiple same-institution SnapTrade auths:** accounts may stay unlinked (`account_registry.py:620` requires unique data source match).
- **Plaid same-institution token overwrite:** `store_plaid_token()` keys by institution, not item_id.
- **Cash-only Plaid accounts:** invisible to `list_accounts()` (account discovery is position-driven).
- **`refresh_provider` scope:** refreshes one provider but returns combined multi-provider view. Agent should use `format="agent"` and check `provider_status`/`auth_warnings` for the connected provider.
- **`routes/provider_routing_api.py:_is_provider_available()`** is a separate function — not affected by `providers/routing.py` fix.

---

## Verification

1. `python3 -m pytest tests/mcp_tools/test_connections.py -v`
2. Manual (SnapTrade): `initiate_brokerage_connection("fidelity")` → open URL → `complete_brokerage_connection(provider="snaptrade", pre_auth_ids=<saved>)` → `get_positions(force_refresh=True, refresh_provider="snaptrade", format="agent")` → `list_accounts()`
3. Manual (Plaid): `initiate_brokerage_connection("chase")` → open URL → `complete_brokerage_connection(provider="plaid", link_token="link-xxx")` → `get_positions(force_refresh=True, refresh_provider="plaid", format="agent")` → `list_accounts()`
