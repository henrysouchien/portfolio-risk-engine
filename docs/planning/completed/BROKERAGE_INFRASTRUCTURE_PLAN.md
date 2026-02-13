# Brokerage Infrastructure Plan: SnapTrade Trading + IBKR Migration + Plaid Cost Reduction

**Created:** 2026-02-10
**Completed:** 2026-02-12
**Status:** ✅ Complete — All three phases implemented and verified

## Context

Three interconnected problems with brokerage connections:
1. **SnapTrade trading is blocked** — 403 code 1020 (app-level trading permissions). All code is implemented but can't execute.
2. **Plaid costs are too high** — IBKR is connected on both Plaid and SnapTrade. Removing the Plaid IBKR connection eliminates 2 API calls per refresh cycle.
3. **Remaining Plaid calls can be minimized** — after IBKR migration, only Merrill Lynch stays on Plaid. Extend cache, reduce polling, add per-provider refresh control.

**Current connections:**
- Plaid: Merrill Lynch + Interactive Brokers (2 institutions × 2 API calls = 4 calls per refresh)
- SnapTrade: IBKR + Schwab (no per-call cost)

**Post-migration target:**
- Plaid: Merrill Lynch only (1 institution × 2 calls = 2 calls per refresh, with longer cache)
- SnapTrade: IBKR + Schwab (all data + trading)

---

## Implementation Order

**Required sequence:** A.1 → B → C → A.2+

Phase A.1 (health check) **must run before** Phase B (IBKR migration) to confirm SnapTrade IBKR is healthy before removing the Plaid fallback. The remaining Phase A steps (trading error messages, support request) can proceed in parallel with C or after.

---

## Phase A: SnapTrade Trading Enablement

### A.1: Add connection health check function (MUST run before Phase B)

**File: `snaptrade_loader.py`** (add after `list_snaptrade_connections()` ~line 644)

Add `check_snaptrade_connection_health(user_email, client, probe_trading=False)` that:
1. Calls `_list_user_accounts_with_retry()` to get accounts
2. For each unique `brokerage_authorization`, normalize the authorization ID (can be dict or string — use pattern from `snaptrade_broker_adapter.py:284-290`: `_extract_authorization_id()`), then call new `_detail_brokerage_authorization_with_retry()` to get the full authorization object (type, disabled status)
3. For one account per authorization, tries `_get_user_account_balance_with_retry()` to test data connectivity
4. **Only if `probe_trading=True`**: For trade-type connections, tries `_symbol_search_user_account_with_retry()` with "AAPL" to test trading API access. Default is **passive only** (no trading probes) — Bug 10 showed that API calls during bad connection state can disable connections.
5. Returns list of dicts:
```python
{
    "authorization_id": str,
    "brokerage_name": str,
    "connection_type": str,  # "read" or "trade"
    "disabled": bool,
    "disabled_date": str | None,
    "account_ids": list[str],
    "data_ok": bool,
    "trading_ok": bool | None,  # None unless probe_trading=True
    "trading_error": str | None,
}
```

Also add `_detail_brokerage_authorization_with_retry()` wrapper using existing `@with_snaptrade_retry` decorator pattern. SDK endpoint: `client.connections.detail_brokerage_authorization(authorization_id=..., user_id=..., user_secret=...)`.

### A.2: Pre-trade 403/1020 error mapping

**File: `services/trade_execution_service.py`**

Add a helper `_map_snaptrade_trading_error(exception)` that detects 403/1020 errors and returns a clear message:
```
"SnapTrade trading permissions not enabled for {brokerage}.
Error code 1020 — contact SnapTrade support to enable app-level trading."
```

Apply this helper in two places where SnapTrade 403 can surface:
1. `_validate_pre_trade()` around `adapter.search_symbol()` (line 938) — symbol search can fail with 403
2. `preview_order()` around `adapter.preview_order()` — order impact can also fail with 403

This is lightweight error message improvement, not a new health check call per trade.

### A.3: Diagnostic run (inline, not a new file)

Run these one-time diagnostics during implementation:
1. `list_snaptrade_connections()` → verify Schwab + IBKR appear
2. `check_snaptrade_connection_health()` → verify disabled=False, data_ok=True for all
3. `check_snaptrade_connection_health(probe_trading=True)` → explicitly test trading APIs (only after confirming connections are healthy)
4. If trading still returns 403/1020 → use the support request template below

**SnapTrade support request template:**
```
Subject: Enable trading permissions for app
- Client ID: [SNAPTRADE_CLIENT_ID from env]
- Affected authorizations: [auth_ids from health check]
- Brokerages: Interactive Brokers, Charles Schwab
- Error: HTTP 403, code 1020 on get_order_impact / place_order endpoints
- Use case: Portfolio rebalancing via MCP tools
```

### A.4: End-to-end trading test (once permissions are live)

1. `search_snaptrade_symbol(user_email, account_id, "AAPL")` — verify symbol resolves
2. `preview_snaptrade_order(user_email, account_id, "AAPL", "BUY", 1, "Market")` — verify no 403
3. MCP tool: `preview_trade(ticker="AAPL", quantity=1, side="BUY", account_id=<schwab_acct>)`
4. DO NOT execute — just verify preview works

### Phase A files changed:
| File | Change |
|------|--------|
| `snaptrade_loader.py` | Add `check_snaptrade_connection_health()`, `_detail_brokerage_authorization_with_retry()` (~70 lines) |
| `services/trade_execution_service.py` | Add `_map_snaptrade_trading_error()` helper, apply in 2 places (~15 lines) |

---

## Phase B: IBKR Migration (Plaid → SnapTrade)

**Prerequisite:** Phase A.1 health check must confirm SnapTrade IBKR connection is `disabled=False` and `data_ok=True`. Do NOT proceed if IBKR data is unavailable on SnapTrade.

### B.1: Pre-migration diagnostics

**Identify Plaid IBKR token:** Call `list_user_tokens("hc@henrychien.com", "us-east-1")` — find the secret path containing "interactive-brokers". Must match exactly one secret (abort if zero or multiple matches).

**Compare normalized holdings:** Fetch from both providers and compare:
- Plaid: `fetch_plaid_holdings(ibkr_access_token, plaid_client)` → normalize via `normalize_plaid_holdings(holdings, securities)` → get tickers/quantities
- SnapTrade: `fetch_snaptrade_holdings(user_email, snaptrade_client)` → `normalize_snaptrade_holdings()` → filter to `brokerage_name` containing "Interactive Brokers"
- Compare: same tickers present (exclude cash rows), quantities within rounding tolerance
- Log any discrepancies for manual review before proceeding

### B.2: Add institution-scoped removal function

**File: `plaid_loader.py`** (add after `delete_plaid_user_tokens()` ~line 1460)

Add `remove_plaid_institution()`:
```python
def remove_plaid_institution(
    user_id: str,
    institution_slug: str,  # e.g., "interactive-brokers" (matches secret path naming)
    region_name: str,
    client: plaid_api.PlaidApi,
    dry_run: bool = True,
) -> dict:
```

Steps:
1. Call `list_user_tokens(user_id, region_name)` to find matching secret path
2. Match `institution_slug` against secret path — **require exactly one match** (error if zero or multiple)
3. Retrieve access token from the matched secret via `get_plaid_token()`
4. If `dry_run=False`:
   - Call `remove_plaid_connection(access_token, client)` to revoke with Plaid
   - Delete the AWS secret via `boto3.client('secretsmanager').delete_secret(SecretId=secret_name, RecoveryWindowInDays=7)` — **use recoverable deletion** (7-day recovery window) instead of `ForceDeleteWithoutRecovery`
5. Return `{"secret_name": ..., "plaid_removed": bool, "secret_deleted": bool, "dry_run": bool}`

**Note:** `list_user_tokens()` returns a list of secret name strings (not dicts). The existing `delete_plaid_user_tokens()` has a bug where it calls `.get('secret_name')` on these strings — we avoid that function entirely and handle deletion directly.

### B.3: DB cleanup via existing refresh mechanism

After removing the Plaid IBKR token, the existing `refresh_provider_positions("plaid")` will:
1. Fetch fresh from remaining Plaid institutions (Merrill Lynch only)
2. `_save_positions_to_db()` DELETEs all Plaid position rows, then INSERTs only Merrill Lynch rows

This is **safer than brokerage-scoped deletion** because it uses the existing tested provider replacement pattern (`services/position_service.py:738`). The old IBKR Plaid rows are automatically cleaned up.

**Edge case**: If `refresh_provider_positions("plaid")` raises because Merrill Lynch fetch fails (empty df → ValueError at line 762), the old IBKR Plaid rows remain in DB. **Fallback**: Use `delete_provider_positions("plaid")` (existing method at line 767) to force-clean all Plaid rows, then re-run refresh. This is safe because SnapTrade IBKR data is confirmed healthy (Phase A.1 gate).

### B.4: Migration execution procedure

```
1. GATE: check_snaptrade_connection_health() → IBKR shows disabled=False, data_ok=True
2. VERIFY: fetch_snaptrade_holdings() → IBKR positions match Plaid IBKR positions (B.1 comparison)
3. DRY RUN: remove_plaid_institution("hc@henrychien.com", "interactive-brokers", "us-east-1", client, dry_run=True)
4. CONFIRM: Review dry run output — exactly one secret matched
5. EXECUTE: remove_plaid_institution(..., dry_run=False)
6. RESYNC: service.refresh_provider_positions("plaid") → re-fetches Merrill Lynch only, cleans IBKR rows
7. VERIFY: get_positions(format="by_account") → IBKR only under SnapTrade, Merrill Lynch only under Plaid
8. VERIFY: list_user_tokens("hc@henrychien.com", "us-east-1") → returns 1 token (Merrill Lynch only)
9. VERIFY: Position totals match pre-migration totals
```

### Phase B files changed:
| File | Change |
|------|--------|
| `plaid_loader.py` | Add `remove_plaid_institution()` (~50 lines) |

*Note: B.3 uses existing `refresh_provider_positions()` — no new DB functions needed.*

---

## Phase C: Plaid Cost Reduction

### C.1: Per-provider cache TTL

**File: `settings.py`**

Add configuration:
```python
PROVIDER_CACHE_HOURS = {
    "plaid": int(os.getenv("PLAID_CACHE_HOURS", "72")),
    "snaptrade": int(os.getenv("SNAPTRADE_CACHE_HOURS", "24")),
}
```

**File: `services/position_service.py`**

Keep `CACHE_HOURS = 24` as the backward-compatible default (referenced by `routes/plaid.py:779` and `routes/snaptrade.py:613`). Add a `cache_hours_for_provider()` class method:

```python
from settings import PROVIDER_CACHE_HOURS

@classmethod
def cache_hours_for_provider(cls, provider: str) -> int:
    return PROVIDER_CACHE_HOURS.get(provider, cls.CACHE_HOURS)
```

Update `_check_cache_freshness()` (line 498) to use the new method:
```python
cache_hours = self.cache_hours_for_provider(provider)
return hours_ago < cache_hours, hours_ago
```

Update routes that reference `PositionService.CACHE_HOURS` to use `PositionService.cache_hours_for_provider("plaid")` and `cache_hours_for_provider("snaptrade")` respectively:
- `routes/plaid.py:779` — change to `PositionService.cache_hours_for_provider("plaid")`
- `routes/snaptrade.py:613` — change to `PositionService.cache_hours_for_provider("snaptrade")`

### C.2: Plaid Link polling optimization

**File: `plaid_loader.py`** (line 177)

Change default poll interval:
```python
# Before:
def wait_for_public_token(link_token, timeout=300, poll=4):

# After:
def wait_for_public_token(link_token, timeout=300, poll=10):
```

Reduces max polling calls from 75 to 30 during the Plaid Link flow. Only runs during one-time connection setup.

### C.3: Per-provider refresh on get_positions MCP tool

**File: `mcp_tools/positions.py`**

Add `refresh_provider` parameter:
```python
def get_positions(
    ...
    refresh_provider: Optional[str] = None,  # "plaid" or "snaptrade"
) -> dict:
```

When `refresh_provider` is set:
1. Force-refresh the specified provider: `service.refresh_provider_positions(refresh_provider)`
2. Then call `service.get_all_positions(use_cache=True)` which loads the refreshed provider from its now-fresh cache and the other provider from its existing cache
3. **Important**: Do NOT call `get_all_positions(force_refresh=True)` — the current `_get_positions_df()` auto-fetches stale/missing cache (line 219-239), so `use_cache=True` after a targeted refresh is sufficient. The other provider will only be re-fetched if its own cache has expired.
4. This lets the user say "refresh just Plaid" without burning SnapTrade API calls too

**File: `mcp_server.py`**

Update `get_positions` tool registration to include new parameter.

### C.4: Surface existing cache metadata in MCP responses

**Note:** `PositionService.get_all_positions()` already populates `result._cache_metadata` with per-provider `from_cache` and `cache_age_hours` (position_service.py:194-203). This just needs to be surfaced in the MCP tool response.

**File: `mcp_tools/positions.py`**

After calling `service.get_all_positions()`, extract `result._cache_metadata` and include in all response formats. **Null-guard `cache_age_hours`** — it is `None` when data was freshly fetched (not from cache):
```python
def _build_cache_info(result):
    info = {}
    for provider in ("plaid", "snaptrade"):
        meta = getattr(result, '_cache_metadata', {}).get(provider, {})
        age = meta.get("cache_age_hours")
        info[provider] = {
            "age_hours": round(age, 1) if age is not None else None,
            "ttl_hours": PositionService.cache_hours_for_provider(provider),
            "from_cache": meta.get("from_cache", False),
        }
    return info
```

No changes needed in `position_service.py` — the metadata already exists.

### Phase C files changed:
| File | Change |
|------|--------|
| `settings.py` | Add `PROVIDER_CACHE_HOURS` config (~5 lines) |
| `services/position_service.py` | Add `cache_hours_for_provider()`, update `_check_cache_freshness()` (~10 lines) |
| `routes/plaid.py` | Update CACHE_HOURS reference to provider-specific (1 line) |
| `routes/snaptrade.py` | Update CACHE_HOURS reference to provider-specific (1 line) |
| `plaid_loader.py` | Change `poll=4` → `poll=10` (1 line) |
| `mcp_tools/positions.py` | Add `refresh_provider` param, surface `cache_info` from existing metadata (~35 lines) |
| `mcp_server.py` | Update get_positions registration (~5 lines) |

---

## Verification

### Phase A
- Run `check_snaptrade_connection_health()` — all connections show `data_ok=True`, `disabled=False`
- Run `check_snaptrade_connection_health(probe_trading=True)` — check trading API access
- If trading permissions are live: `preview_trade` returns preview without 403
- If still blocked: error message clearly says "contact SnapTrade support, code 1020"

### Phase B
- **Pre-migration gate:** Health check confirms SnapTrade IBKR is healthy
- `get_positions(format="by_account")` — IBKR appears ONLY under SnapTrade
- `get_positions(format="by_account")` — Merrill Lynch appears ONLY under Plaid
- `list_user_tokens("hc@henrychien.com", "us-east-1")` — returns 1 token (Merrill Lynch only)
- Position totals match pre-migration totals (no missing holdings)

### Phase C
- `get_positions()` at 48 hours serves Plaid from cache (would have refreshed under old 24h TTL)
- `get_positions(refresh_provider="plaid")` triggers Plaid API calls; SnapTrade may also auto-fetch if its cache has expired (verify via logs)
- `get_positions()` response includes `cache_info` with per-provider ages and TTLs
- Plaid Link flow polls at 10s intervals (verify in logs)
- Route messages show correct per-provider TTL ("Data refreshes after 72h" for Plaid)

---

## Codex Review Findings Addressed

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | Phase sequencing not independent — IBKR could lose coverage | A.1 health check now gates Phase B; sequence is A.1 → B → C → A.2+ |
| 2 | HIGH | `CACHE_HOURS` replacement breaks routes | Keep `CACHE_HOURS` as default, add `cache_hours_for_provider()` method, update route references |
| 3 | HIGH | Health check trading probes can disable connection | `probe_trading=False` by default; active trading probes require explicit opt-in |
| 4 | HIGH | `ForceDeleteWithoutRecovery` + substring match dangerous | Require exact single match, use `RecoveryWindowInDays=7` for recoverable deletion |
| 5 | MED | A.2 targets wrong code location | Centralized `_map_snaptrade_trading_error()` helper applied at both symbol search and preview |
| 6 | MED | Holdings comparison needs normalization | Compare normalized holdings via `normalize_plaid_holdings()` / `normalize_snaptrade_holdings()` |
| 7 | MED | Brokerage-scoped delete unnecessary | Removed B.3 custom delete; use existing `refresh_provider_positions("plaid")` instead |
| 8 | MED | Cache metadata already exists in PositionService | C.4 now surfaces existing `_cache_metadata` instead of adding new plumbing |
| 9 | MED | `delete_plaid_user_tokens()` has str vs dict bug | Avoided entirely; `remove_plaid_institution()` handles deletion directly |
| 10 | LOW | Verification refresh is too broad | Phase B step 6 now uses `refresh_provider_positions("plaid")` specifically |

### Round 2 Findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 11 | HIGH | `cache_info` crashes on `round(None, 1)` for fresh fetches | Added null-guard: `round(age, 1) if age is not None else None` |
| 12 | MED | `refresh_provider` can still trigger other provider fetch | Documented: call `refresh_provider_positions()` first, then `get_all_positions(use_cache=True)` — other provider only auto-fetches if its own cache expired |
| 13 | MED | `refresh_provider_positions` raises on empty df | Added fallback: if Merrill Lynch fetch fails, use existing `delete_provider_positions("plaid")` to clean stale rows |
| 14 | LOW | Authorization ID can be dict or string | Added normalization step using existing `_extract_authorization_id()` pattern from snaptrade_broker_adapter.py:284-290 |

---

## Total files changed across all phases

| File | Phases | Lines added/changed |
|------|--------|---------------------|
| `snaptrade_loader.py` | A | ~70 lines (health check + retry wrapper) |
| `services/trade_execution_service.py` | A | ~15 lines (error mapping helper + 2 call sites) |
| `plaid_loader.py` | B, C | ~50 lines (institution removal) + 1 line (poll interval) |
| `services/position_service.py` | C | ~10 lines (cache_hours_for_provider + update check) |
| `settings.py` | C | ~5 lines (cache config) |
| `routes/plaid.py` | C | 1 line (cache hours reference) |
| `routes/snaptrade.py` | C | 1 line (cache hours reference) |
| `mcp_tools/positions.py` | C | ~35 lines (refresh_provider + cache_info) |
| `mcp_server.py` | C | ~5 lines (param update) |
