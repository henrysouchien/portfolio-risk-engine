# Plan: Unified `list_connections` MCP Tool (v12)

## Context

There's no single tool to answer "what brokerage connections do I have and are they alive?" Today you'd need to call 3-4 separate endpoints (`/snaptrade/connections`, `/plaid/connections`, `/api/onboarding/ibkr-status`, plus `check_schwab_token.py`). The pieces exist — they just need to be unified into one MCP tool.

## What We're Building

A single MCP tool: `list_connections(check_health: bool = False)`

- `check_health=False` (default): Lists known connections. The depth of information varies by provider because each uses a different discovery mechanism:
  - **SnapTrade**: Remote API call to list accounts → knows connection exists and accounts are listed. Status: `"listed"`.
  - **Plaid**: AWS Secrets Manager read + optional DB lookup → knows item exists and reauth status. Status: `"ok"` or `"needs_reauth"`.
  - **Schwab**: Local token file check only. Status: `"token_present"` / `"token_missing"` / `"not_configured"`.
  - **IBKR**: Config/env check only. Status: `"configured"` / `"not_configured"`.
- `check_health=True`: All of the above, plus active health probing. Status labels are refined to health-verified values (`"connected"`, `"disabled"`, `"unreachable"`, `"degraded"`, etc.).

Uses **agent format** (snapshot + flags) because this is a diagnostic tool and flags are perfect for surfacing actionable issues.

---

## Status Label Vocabulary

Each provider's `status` field reflects what is actually known at the current `check_health` level. Labels are NOT uniform across providers — each reflects the provider's discovery mechanism.

### Default mode (`check_health=False`)

| Provider | Status values | What it means |
|----------|--------------|---------------|
| SnapTrade | `"listed"` | Account API returned this authorization. Connection exists but health unknown. |
| Plaid | `"ok"` / `"needs_reauth"` | Secret exists. `needs_reauth` from DB (or `"ok"` if no DB). |
| Schwab | `"token_present"` / `"token_missing"` / `"not_configured"` | File-system check only. |
| IBKR | `"configured"` / `"not_configured"` | Config/env check only. |

### Health mode (`check_health=True`) — status refined

| Provider | Status values | What it means |
|----------|--------------|---------------|
| SnapTrade | `"connected"` / `"disabled"` / `"data_failed"` | Authorization detail probed. `"connected"` = data_ok. `"data_failed"` = balance probe failed but not disabled. |
| Plaid | `"ok"` / `"needs_reauth"` | Same as default (Plaid has no deeper probe). |
| Schwab | `"connected"` / `"degraded"` / `"token_expired"` / `"token_missing"` / `"not_configured"` | `check_token_health()` inspected. `"degraded"` = warnings present but not expired. |
| IBKR | `"connected"` / `"unreachable"` / `"not_configured"` | Gateway probed. |

---

## Files to Create/Modify

### 1. NEW: `mcp_tools/connection_status.py` — Main tool module

Separate from existing `mcp_tools/connections.py` (which has action tools: initiate/complete). This is a diagnostic tool.

```python
@handle_mcp_errors
def list_connections(
    check_health: bool = False,
    user_email: Optional[str] = None,
) -> dict[str, Any]:
```

**User resolution guard:** Before any provider calls, resolve the user following the existing pattern from `mcp_tools/connections.py` (lines 64-70 and 328-330):
```python
resolved_email, user_id, context = _resolve_tool_user(user_email)
if resolved_email is None or user_id is None:
    return {"status": "error", "error": format_missing_user_error(context)}
```
Where `_resolve_tool_user()` calls `resolve_user_email()` → `resolve_user_id()`. `format_missing_user_error()` returns a `str`, so it must be wrapped in the standard `{"status": "error", "error": str}` dict (matching `connections.py:330`).

`resolved_email` is passed to SnapTrade/Plaid helpers. `user_id` is passed to the Plaid DB lookup. In no-DB mode, `resolve_user_id()` returns sentinel `0` (not None) — the Plaid helper treats `user_id=0` the same as any valid ID for the DB query attempt, which will gracefully fail if DB is unavailable.

**Per-provider logic:**

| Provider | check_health=False | check_health=True |
|----------|-------------------|-------------------|
| SnapTrade | `_list_user_accounts_with_retry()` + grouping (see §Grouping) | Same listing + authorization detail + balance probe (see §SnapTrade Health) |
| Plaid | `_list_plaid_items()` local helper (see §Plaid) | Same (reauth flag is the health signal) |
| Schwab | `is_provider_enabled("schwab")` + `os.path.exists(token_path)` | + `check_token_health()` for full inspection |
| IBKR | `is_provider_enabled("ibkr")` only (no network) | + `IBKRConnectionManager().probe_connection()` |

Each provider wrapped in its own try/except — one failing doesn't break the others. The per-provider try/except catches exceptions and records the error string in an `error` field on the provider dict, so the caller can distinguish "provider errored" from "no connections."

**SnapTrade building blocks:** The MCP tool does NOT call the high-level helpers directly. `check_snaptrade_connection_health()` swallows exceptions at the outer level and returns `[]` (see `connections.py:313-315`), making it impossible to distinguish errors from empty results. `list_snaptrade_connections()` does re-raise (lines 150-152), but we bypass both to get consistent error handling and avoid the double-wrapping.

Instead, import the underlying helpers that DO raise from their canonical locations:
- From `brokerage.snaptrade.client`: `_list_user_accounts_with_retry`, `_detail_brokerage_authorization_with_retry`, `_get_user_account_balance_with_retry`, `_symbol_search_user_account_with_retry`, `get_snaptrade_client`
- From `brokerage.snaptrade.users`: `get_snaptrade_user_id_from_email`
- From `brokerage.snaptrade.secrets`: `get_snaptrade_user_secret`

These retry helpers are defined in `brokerage/snaptrade/client.py` (lines 75+), not `connections.py` — `connections.py` only imports them. No `__all__` changes needed.

**SnapTrade "no secret" guard:** SnapTrade is enabled by default for all users (`is_provider_enabled("snaptrade")` returns True). But `get_snaptrade_user_secret()` returns `None` when the user has never linked a SnapTrade account (see `brokerage/snaptrade/secrets.py:142`). This is a normal empty state, NOT an error — matching existing behavior in `mcp_tools/connections.py:255`. The MCP tool must check for `None` secret before calling `_list_user_accounts_with_retry()`:
```python
user_secret = get_snaptrade_user_secret(resolved_email)
if not user_secret:
    # Normal: user has no SnapTrade connections. Return empty list, no error.
    snaptrade_connections = []
else:
    accounts_response = _list_user_accounts_with_retry(client, snaptrade_user_id, user_secret)
    # ... group and optionally probe
```

**SnapTrade grouping (§Grouping):** `_list_user_accounts_with_retry()` returns one row per *account*. The MCP tool groups by `authorization_id` to produce one row per *connection*. The grouping must use `_normalize_auth_id()` logic matching `check_snaptrade_connection_health()` (lines 162-168) — `brokerage_authorization` can be a dict `{id: "..."}` or a bare string:
```python
def _normalize_auth_id(auth_value: Any) -> str | None:
    if isinstance(auth_value, dict):
        auth_id = auth_value.get("id")
        return str(auth_id) if auth_id else None
    if auth_value:
        return str(auth_value)
    return None
```
Handle missing auth IDs the same way as `check_snaptrade_connection_health()` (line 203-205): if `_normalize_auth_id()` returns `None`, use fallback `f"unknown:{account_id}"` (or `"unknown"` if account_id is also missing). Then group: `grouped[auth_id] = {authorization_id, institution, status: "listed", account_ids: []}`. This prevents orphaned accounts from collapsing into a single `None` key.

**SnapTrade health probing (§SnapTrade Health):** When `check_health=True`, after grouping, iterate each authorization:
1. Call `_detail_brokerage_authorization_with_retry()` → extract `connection_type`, `disabled`, `disabled_date`
2. Call `_get_user_account_balance_with_retry()` on first account → `data_ok: True/False`
3. Optionally call `_symbol_search_user_account_with_retry("AAPL")` → `trading_ok`
4. Set `status`: `"disabled"` if `disabled=True`, else `"connected"` if `data_ok`, else `"data_failed"` (balance probe failed but connection exists and not disabled)

**Plaid listing (§Plaid):** The `needs_reauth` DB lookup stays in the MCP tool layer, NOT in `brokerage/plaid/connections.py` (which is pure API/secrets helpers). The MCP tool has a local `_list_plaid_items()` helper that:
1. Calls `list_user_tokens(user_email, region_name)` to find secrets in AWS Secrets Manager
2. Reads each secret to get `item_id`
3. Derives institution from DB lookup first (via `DatabaseClient.list_provider_items_for_user()`), falls back to secret-name slug (matching `routes/onboarding.py:100-113` behavior)
4. If DB available, checks `needs_reauth` via same DB query. If DB unavailable, defaults to `needs_reauth=False`.
5. Returns: `[{item_id, institution, status: "ok"|"needs_reauth", needs_reauth: bool}]`

**Schwab fields (§Schwab):** The Schwab snapshot always includes `status` and `token_file_exists` (available in both modes via local file check). When `check_health=True`, `check_token_health()` is called and its full return dict is merged in: `token_age_seconds`, `refresh_token_expires_at`, `refresh_token_days_remaining`, `near_refresh_expiry`, `warnings`.

Default path Schwab status derivation:
- `is_provider_enabled("schwab")` is False → `status: "not_configured"`, `token_file_exists: False`
- Enabled but token file missing → `status: "token_missing"`, `token_file_exists: False`
- Enabled and token file exists → `status: "token_present"`, `token_file_exists: True`

Health mode Schwab status derivation (after `check_token_health()`). Evaluated in strict priority order — first match wins:
1. `token_file_exists=False` → `status: "token_missing"`
2. `near_refresh_expiry=True` → `status: "token_expired"` (covers both date-based expiry where `refresh_token_days_remaining <= 0`, AND `invalid_grant` errors where `refresh_token_days_remaining` may be `None` but `near_refresh_expiry` is set to `True` by the exception handler at `client.py:366`)
3. `warnings` non-empty (but `near_refresh_expiry=False` and file exists) → `status: "degraded"` (e.g., corrupt JSON, non-grant client error)
4. No warnings and not expired → `status: "connected"`

**IBKR passive vs active (§IBKR):** For `check_health=False`, use only `is_provider_enabled("ibkr")` (pure config check, no network). Status is `"configured"` (enabled) or `"not_configured"`. For `check_health=True`, call `IBKRConnectionManager().probe_connection()` which returns `{reachable, managed_accounts, error}`. Status becomes `"connected"` (reachable) or `"unreachable"`.

**Snapshot shape:**
```python
{
    "providers": {
        "snaptrade": {
            "enabled": bool,
            "error": str | None,
            "connections": [            # one per authorization_id (grouped)
                {
                    "authorization_id": str,
                    "institution": str,
                    "status": str,      # see Status Label Vocabulary above
                    "account_ids": [str, ...],
                    # check_health=True only:
                    "connection_type": str,
                    "disabled": bool,
                    "disabled_date": str | None,
                    "data_ok": bool,
                    "trading_ok": bool | None,
                    "trading_error": str | None,
                }
            ]
        },
        "plaid": {
            "enabled": bool,
            "error": str | None,
            "connections": [
                {
                    "item_id": str,
                    "institution": str,
                    "status": "ok" | "needs_reauth",
                    "needs_reauth": bool,
                }
            ]
        },
        "schwab": {
            "enabled": bool,
            "error": str | None,
            "connection": {
                "status": str,          # see Status Label Vocabulary above
                "token_file_exists": bool,
                # check_health=True only:
                "token_age_seconds": float | None,
                "refresh_token_expires_at": str | None,
                "refresh_token_days_remaining": float | None,
                "near_refresh_expiry": bool,
                "warnings": [str, ...],
            }
        },
        "ibkr": {
            "enabled": bool,
            "error": str | None,
            "connection": {
                "status": str,          # see Status Label Vocabulary above
                # check_health=True only:
                "gateway_reachable": bool,
                "managed_accounts": [str, ...],
                "probe_error": str | None,
            }
        }
    },
    "summary": {
        "total_connections": int,
        "healthy": int,
        "needs_attention": int,
        "health_probed": bool,
    }
}
```

### Summary counting rules

**`total_connections`**: Count of actually-discovered connections (not just configured providers).
- SnapTrade: `len(connections)` (0 if `error` is set or provider disabled)
- Plaid: `len(connections)` (0 if `error` is set or provider disabled)
- Schwab: 1 if `status` not in `("not_configured", "token_missing")`, else 0. 0 if `error` set.
- IBKR: 1 if `enabled=True` and `status != "not_configured"`, else 0. 0 if `error` set. (Same rule in both modes — an unreachable gateway is still a connection that needs attention, not a missing connection.)

**`healthy`** (only meaningful when `health_probed=True`):
- SnapTrade: count of connections where `data_ok=True` and `disabled=False`
- Plaid: count of connections where `needs_reauth=False`
- Schwab: 1 if `status == "connected"`, else 0
- IBKR: 1 if `status == "connected"`, else 0

**`needs_attention`** = `total_connections` - `healthy` (clamped to >= 0)

When `health_probed=False`, `healthy` and `needs_attention` are both 0 (unknown).

**Returns agent format:** `{status, format: "agent", snapshot, flags}`

### 2. NEW: `core/connection_flags.py`

```python
def generate_connection_flags(snapshot: dict) -> list[dict]:
```

Follows the exact pattern of `core/risk_score_flags.py`. Reads the real field names from the snapshot.

| Flag | Severity | Condition | Requires health_probed |
|------|----------|-----------|----------------------|
| `schwab_token_missing` | error | `schwab.enabled=True` AND `schwab.connection.status == "token_missing"` | No |
| `schwab_token_expired` | error | `near_refresh_expiry=True` (covers both date-based expiry and `invalid_grant`) | Yes |
| `schwab_token_expiring` | warning | `near_refresh_expiry=False` and `refresh_token_days_remaining` is not None and `<= 2` | Yes |
| `schwab_degraded` | warning | `schwab.connection.status == "degraded"` (warnings present, not expired) | Yes |
| `plaid_needs_reauth` | error | any Plaid item has `needs_reauth=True`. Message includes institution. | No |
| `snaptrade_disabled` | error | any authorization has `disabled=True` | Yes |
| `snaptrade_data_probe_failed` | warning | `data_ok=False` on any non-disabled connection | Yes |
| `ibkr_gateway_unreachable` | error | `gateway_reachable=False` | Yes |
| `provider_error` | error | any provider has non-None `error` field. Includes provider name + error. | No |
| `no_connections` | warning | `total_connections == 0` and no provider errors | No |
| `all_healthy` | success | `health_probed=True` and no error/warning flags generated | Yes |

### 3. MODIFY: `mcp_server.py`

Import + register:
```python
from mcp_tools.connection_status import list_connections as _list_connections

@mcp.tool()
def list_connections(check_health: bool = False) -> dict:
    """List all brokerage connections with optional health probing."""
    return _list_connections(check_health=check_health, user_email=None)
```

---

## Existing Functions to Reuse (do NOT rewrite)

- `_list_user_accounts_with_retry()` — `brokerage/snaptrade/client.py:75` (raises on failure)
- `_detail_brokerage_authorization_with_retry()` — `brokerage/snaptrade/client.py:83` (raises on failure)
- `_get_user_account_balance_with_retry()` — `brokerage/snaptrade/client.py` (raises on failure)
- `_symbol_search_user_account_with_retry()` — `brokerage/snaptrade/client.py` (raises on failure)
- `get_snaptrade_user_id_from_email()` — `brokerage/snaptrade/users.py`
- `get_snaptrade_user_secret()` — `brokerage/snaptrade/secrets.py`
- `get_snaptrade_client()` — `brokerage/snaptrade/client.py`
- `check_token_health()` — `brokerage/schwab/client.py:325` (returns: `token_file_exists`, `token_age_seconds`, `refresh_token_expires_at`, `refresh_token_days_remaining`, `near_refresh_expiry`, `warnings`)
- `list_user_tokens()` — `brokerage/plaid/secrets.py`
- `is_provider_enabled()` — `providers/routing.py:279` (config-only, no network)
- `handle_mcp_errors` decorator — `mcp_tools/common.py`
- `resolve_user_email()` — `utils/user_context.py:89` (returns `(email, context)` tuple)
- `format_missing_user_error()` — import from `settings` (re-exported from `utils/user_context.py:105`). Returns a **string**, must be wrapped in `{"status": "error", "error": str}`
- `resolve_user_id()` — `utils/user_resolution.py` (no-DB-safe)
- `normalize_institution_slug()` — `providers/routing.py:81` (for Plaid institution derivation)
- `DatabaseClient.list_provider_items_for_user()` — for Plaid `needs_reauth` lookup

---

## No-DB Mode

- SnapTrade: works fully (SnapTrade API only)
- Plaid: listing works (AWS Secrets Manager). `needs_reauth` defaults to False without DB. Institution derived from secret-name slug as fallback.
- Schwab: works fully (token file check, no DB)
- IBKR: works fully (config check default; gateway probe on check_health=True)

---

## Implementation Order

1. `core/connection_flags.py`
2. `mcp_tools/connection_status.py` (includes `_list_plaid_items()` helper, SnapTrade grouping with `_normalize_auth_id()`, SnapTrade health probing using building blocks from `brokerage.snaptrade.client`)
3. `mcp_server.py` registration
4. Tests

Note: No changes to `brokerage/snaptrade/connections.py`, `brokerage/plaid/connections.py`, or `routes/onboarding.py`.

## Test Cases

Tests go in `tests/mcp_tools/test_connection_status.py`. All provider calls mocked.

| Test | What it verifies |
|------|-----------------|
| `test_list_connections_missing_user` | No user configured → returns `{"status": "error", "error": ...}`, no provider calls made |
| `test_list_connections_all_providers_enabled` | Happy path: all 4 providers enabled, correct snapshot shape |
| `test_list_connections_no_providers_enabled` | All disabled → `total_connections=0`, `no_connections` warning flag. No `schwab_token_missing`. |
| `test_list_connections_check_health_schwab_expiring` | Schwab `refresh_token_days_remaining=1.5` → `schwab_token_expiring` warning |
| `test_list_connections_check_health_schwab_expired_by_date` | Schwab `near_refresh_expiry=True`, `refresh_token_days_remaining<=0` → `schwab_token_expired` error, status `"token_expired"` |
| `test_list_connections_check_health_schwab_expired_invalid_grant` | Schwab `near_refresh_expiry=True`, `refresh_token_days_remaining=None` (invalid_grant path) → `schwab_token_expired` error, status `"token_expired"` |
| `test_list_connections_schwab_token_missing_default_mode` | Schwab enabled, token file missing → `schwab_token_missing` error, status `"token_missing"` |
| `test_list_connections_schwab_token_missing_health_mode` | check_health=True, `check_token_health()` returns `token_file_exists=False` + warning → status `"token_missing"` (NOT `"degraded"`), `schwab_token_missing` error |
| `test_list_connections_schwab_degraded` | check_health=True, warnings non-empty but not expired → status `"degraded"`, `schwab_degraded` warning |
| `test_list_connections_schwab_not_configured_no_flag` | Schwab disabled → status `"not_configured"`, no `schwab_token_missing` flag |
| `test_list_connections_plaid_needs_reauth` | Plaid item with `needs_reauth=True` → status `"needs_reauth"`, `plaid_needs_reauth` error flag |
| `test_list_connections_plaid_no_db` | No DB → Plaid items listed, status `"ok"`, institution from slug |
| `test_list_connections_snaptrade_no_secret` | SnapTrade enabled but `get_snaptrade_user_secret()` returns None → empty connections, no `error` field, no `provider_error` flag |
| `test_list_connections_snaptrade_grouping_default` | 3 accounts across 2 auth IDs → 2 connections, all `status: "listed"` |
| `test_list_connections_snaptrade_grouping_health` | Same 3 accounts → 2 connections with health fields, `status: "connected"` |
| `test_list_connections_snaptrade_dict_auth_id` | `brokerage_authorization={id: "abc"}` dict → normalized to `"abc"` in both modes |
| `test_list_connections_snaptrade_missing_auth_id` | Account with no `brokerage_authorization` → grouped under `"unknown:{account_id}"`, not collapsed with other orphans |
| `test_list_connections_snaptrade_disabled_health_only` | check_health=True, auth detail `disabled=True` → `snaptrade_disabled` error. Default mode → flag NOT emitted. |
| `test_list_connections_snaptrade_data_probe_failed` | check_health=True, balance fetch raises → `data_ok=False`, `snaptrade_data_probe_failed` warning |
| `test_list_connections_snaptrade_api_error_propagates` | `_list_user_accounts_with_retry` raises → `error` field, `provider_error` flag, `total_connections` excludes this provider |
| `test_list_connections_ibkr_passive_no_probe` | check_health=False → `is_provider_enabled()` called, NOT `probe_connection()`. Status `"configured"`. |
| `test_list_connections_ibkr_default_status_labels` | Default: enabled → `"configured"`, disabled → `"not_configured"` |
| `test_list_connections_ibkr_health_status_labels` | Health: reachable → `"connected"`, not reachable → `"unreachable"` |
| `test_list_connections_ibkr_gateway_unreachable` | check_health=True, `reachable=False` → `ibkr_gateway_unreachable` error |
| `test_list_connections_provider_exception_isolation` | SnapTrade raises, other providers still return data. SnapTrade `error` field set. |
| `test_list_connections_summary_counting_default` | 2 SnapTrade auths + 1 Plaid + Schwab token_present + IBKR configured → `total_connections=5`, `healthy=0`, `needs_attention=0` (not probed) |
| `test_list_connections_summary_counting_health` | Same setup, check_health=True, 1 SnapTrade disabled → `total_connections=5`, `healthy=4`, `needs_attention=1` |
| `test_list_connections_summary_error_excluded` | SnapTrade errors → `total_connections` does NOT count SnapTrade connections |
| `test_list_connections_all_healthy` | check_health=True, everything passes → `all_healthy` success flag |
| `test_list_connections_provider_error_flag` | Provider has non-None `error` → `provider_error` flag with provider name |
| `test_list_connections_no_connections_vs_error` | Empty + no error → `no_connections`. Empty + error → `provider_error` only (not `no_connections`). |

## Verification

1. Run `list_connections()` — SnapTrade `"listed"`, Plaid `"ok"`, IBKR `"configured"`, Schwab `"token_present"`. Summary has `total_connections` but `healthy`/`needs_attention` are 0 (not probed).
2. Run `list_connections(check_health=True)` — probes each, refined status labels. Summary has real healthy/needs_attention counts.
3. With Schwab token near expiry: `schwab_token_expiring` warning
4. With Schwab token missing (enabled): `schwab_token_missing` error
5. With Schwab disabled: no `schwab_token_missing` flag
6. With Schwab warnings but not expired: `schwab_degraded` warning
7. With IBKR Gateway down: `ibkr_gateway_unreachable` error
8. Kill SnapTrade API: `provider_error` flag fires (not silent empty)
9. Existing tests pass (`pytest tests/`)
10. New tests pass (`pytest tests/mcp_tools/test_connection_status.py`)
