# GOLD Ticker Fix + Proxy/Peer Cache Management Tool

## Context

The ticker GOLD (NYSE) is **Gold.com, Inc.** (A-Mark Precious Metals, Financial Services). Codex incorrectly created a profile override mapping GOLD → "Barrick Gold" (which now trades as ABX.TO on TSX). This bad data propagates through:
- `config/profile_overrides.yaml` (untracked) — wrong company name
- `config/sector_overrides.yaml` (committed) — wrong sector
- DB `subindustry_peers` / `factor_proxies` tables — stale Barrick-era peers/proxies
- In-memory caches: LFU profile/peers, FMP TTL profile cache, lru_cache YAML loaders, workflow/result snapshot caches

Separately, there's no tooling to manage these DB caches — only manual SQL. This plan fixes GOLD and builds the cache management tool from the TODO.

---

## Step 1: Fix GOLD Config Data

### 1a. `config/profile_overrides.yaml` — remove GOLD entry
Keep the file with a comment header for future use, but no ticker entries.

### 1b. `config/sector_overrides.yaml` — remove GOLD line
Keep SLV and AT.L entries.

### 1c. Update tests
- `tests/providers/test_fmp_metadata.py:69-104` — replace GOLD/Barrick with generic `TESTCO` override to test override infrastructure
- `tests/services/test_factor_proxies.py:290-311` — replace `GOLD` with `TESTCO` in `has_profile_override` test
- **Add GOLD-specific regression test** in `test_fmp_metadata.py`: assert `has_profile_override("GOLD")` returns `False` after config change, and FMP data for GOLD passes through without override (company name stays "Gold.com, Inc.", sector stays "Financial Services")
- **Add GOLD test** in `test_portfolio_service.py`: assert GOLD is no longer in `_load_sector_overrides()` result

---

## Step 2: No LFU `evict_key()` needed

The original plan proposed targeted LFU key eviction, but FMP-resolved cache keys (e.g., `AT.L`) require user-scoped `fmp_ticker_map` to resolve, which an admin tool doesn't have. Instead, the `invalidate` action clears entire LFU caches via existing `clear_company_profile_cache()` and `clear_gpt_peers_cache()` functions (`proxy_builder.py:256-262`). These caches are bounded (1000/500 entries), process-global, and repopulate lazily on demand — a full clear is acceptable for a rare admin operation.

No new methods needed on `LFUCache`.

---

## Step 3: Add `clear_all_cached_profiles()` to FMPProfileProvider

**File**: `providers/fmp_metadata.py`

Add a method to clear the entire provider TTL profile cache:

```python
def clear_all_cached_profiles(self) -> None:
    """Clear all cached profiles. Used by admin cache invalidation."""
    with self._profile_cache_lock:
        self._profile_cache.clear()
```

This clears the entire `_profile_cache` (TTLCache, 300s TTL) which sits between FMP API calls and callers. A full clear is needed because cache keys use FMP-resolved symbols (e.g., `AT.L` not `AT`), and the admin tool lacks the `fmp_ticker_map` needed to resolve which keys to target. The cache is bounded (1024 entries) and TTL-scoped, so a full clear is cheap.

---

## Step 4: Add DB Methods

**File**: `inputs/database_client.py` (after `save_subindustry_peers` ~line 4592)

| Method | Purpose |
|--------|---------|
| `delete_subindustry_peers(ticker) -> bool` | DELETE from global peers table, return whether row existed |
| `delete_factor_proxies_for_ticker(ticker) -> int` | DELETE from ALL portfolios for a ticker, return row count |
| `list_subindustry_peers_summary(limit, min_age_days) -> list[dict]` | List entries with age info, optional age filter |
| `list_factor_proxies_for_ticker(ticker) -> list[dict]` | Show which portfolios cache proxies for ticker (JOIN `portfolios` on `id`) |

### Age/staleness query alignment

Use `COALESCE(updated_at, generated_at)` for staleness, matching the existing pattern in `admin/verify_proxies.py:144`:

```sql
WHERE COALESCE(updated_at, generated_at) < %s
```

Cutoff computed app-side: `datetime.utcnow() - timedelta(days=min_age_days)` passed as a parameterized `%s`.

### DB Schema Reference

```sql
-- subindustry_peers: ticker PK, peers JSONB, source, generated_at, updated_at
-- factor_proxies: portfolio_id + ticker UNIQUE, user_id, market/momentum/value/industry_proxy, subindustry_peers JSONB, created_at, updated_at
-- portfolios: id PK, user_id, name VARCHAR(255), start_date, end_date
```

### Existing DB Methods to Reuse
- `get_subindustry_peers(ticker)` — read single ticker peers
- `save_subindustry_peers(ticker, peers, source)` — upsert peers
- `get_factor_proxies(user_id, portfolio_name)` — read portfolio proxies
- `save_factor_proxies(user_id, portfolio_name, factor_proxies)` — upsert portfolio proxies

### Existing In-Memory Cache Functions
- `clear_company_profile_cache()` / `clear_gpt_peers_cache()` / `get_proxy_cache_stats()` in `core/proxy_builder.py`
- `_COMPANY_PROFILE_CACHE` (LFU, 1000 entries) — key format: `f"profile_{ticker.upper()}"`
- `_GPT_PEERS_CACHE` (LFU, 500 entries) — key format: MD5 hash of `{'ticker': T, 'start': S, 'end': E}`

---

## Step 5: Build MCP Tool

**New file**: `mcp_tools/proxy_cache.py`

Follow `manage_instrument_config` pattern: `@handle_mcp_errors` + `@require_db`, action-based dispatch.

```python
def manage_proxy_cache(action, ticker=None, min_age_days=None, limit=None) -> dict:
```

| Action | Params | Behavior |
|--------|--------|----------|
| `list` | `min_age_days`, `limit` | List cached `subindustry_peers` entries with age |
| `get` | `ticker` (required) | Show peers + factor_proxies for ticker |
| `invalidate` | `ticker` (required, comma-sep OK) | Delete from both DB tables + clear proxy/peer metadata caches (see below). Data auto-rebuilds on next portfolio analysis. |
| `audit` | `min_age_days` (default 90) | List stale entries using `COALESCE(updated_at, generated_at)` + recommendation |

**Why no `refresh` action**: Proxy rebuilding calls `build_proxy_for_ticker()` and `get_subindustry_peers_from_ticker()` which internally use `select_fmp_symbol(ticker, fmp_ticker_map=...)` (`proxy_builder.py:541`, `proxy_builder.py:827`). The resolver only honors aliases (e.g., `AT` → `AT.L`) when `fmp_ticker_map` is supplied (`ticker_resolver.py:119`). An admin tool has no user context to provide this map, so a `refresh` would generate data under the raw ticker.

**Pre-existing limitation**: The normal rebuild path (`ensure_factor_proxies()` at `factor_proxy_service.py:60`) also does NOT thread `fmp_ticker_map` — it only forwards `instrument_types` to the builders (`factor_proxy_service.py:154`). The two main callers (`workflow_cache.py:180`, `portfolio_manager.py:380`) also omit the alias map. This means alias-mapped tickers like `AT` already rebuild against the raw ticker in the current system. **This plan does not make that behavior worse** — `invalidate` restores exactly the same pre-invalidation state on the next rebuild. The alias resolution gap is a separate issue tracked independently.

For the GOLD ticker (the immediate fix), there is no FMP alias — `GOLD` resolves to `GOLD` on FMP — so this limitation does not apply.

### `invalidate` cache clearing — metadata layers

**FMP symbol resolution challenge**: Proxy builds resolve tickers through `select_fmp_symbol(ticker, fmp_ticker_map=...)` before profile lookup (e.g., `AT` → `AT.L`). Caches are keyed by the resolved symbol (`proxy_builder.py:541`, `fmp_metadata.py:89`). However, `select_fmp_symbol()` only resolves when `fmp_ticker_map` is provided — this map comes from user-scoped DB config (`user_ticker_config`), which an admin tool does not have access to.

**Solution**: Instead of attempting targeted key eviction (which requires user context), clear the **entire** LFU profile cache and **entire** FMP provider TTL cache on invalidation. This is the same approach already used for `_GPT_PEERS_CACHE` (cleared entirely because MD5-hashed keys can't be reversed). The caches are bounded (1000 LFU profiles, 1024 FMP TTL entries) and process-global, so a full clear is acceptable for a rare admin operation.

The `invalidate` action clears proxy/peer metadata caches. It does NOT clear PortfolioService instance-level result caches (`self._cache`, Redis L2) which hold full analysis outputs — these are TTL-bounded (`SERVICE_CACHE_TTL`, default 1800s / 30 min; `REDIS_CACHE_TTL` inherits the same default). Stale analysis results referencing old proxy data may persist for up to 30 minutes after invalidation. For immediate full purge, restart the service process (the existing `POST /admin/clear_cache` route at `routes/admin.py:789` clears a fresh `PortfolioService()` instance, not the live per-user singletons in `app.py:332-360`).

Metadata cache layers cleared by `invalidate`:

1. **DB tables**: `subindustry_peers` + `factor_proxies` (via new delete methods) — keyed by raw ticker
2. **LFU profile cache**: `clear_company_profile_cache()` — clears entire cache (can't target FMP-resolved keys without user context)
3. **LFU GPT peers cache**: `clear_gpt_peers_cache()` — clears entire cache (MD5-hashed keys)
4. **FMP provider TTL cache**: Clear entire `_profile_cache` via new `clear_all_cached_profiles()` method — can't target resolved keys without `fmp_ticker_map`
5. **YAML lru_caches**: `_load_profile_overrides.cache_clear()` + `_load_sector_overrides.cache_clear()` — forces re-read of edited YAMLs
6. **Workflow snapshot caches**: `clear_workflow_snapshot_caches()` — clears portfolio/factor_proxy/risk_limits snapshots
7. **Result snapshot caches**: `clear_result_snapshot_caches()` — clears analysis/risk_score/performance snapshots
8. **PortfolioService position profile cache + inflight**: Clear both `_position_profile_cache` AND `_position_profile_inflight` under `_shared_snapshot_lock`, matching the pattern in `PortfolioService.clear_cache()` (line 2187)

**Concurrency note**: If an analysis is already in-flight when `invalidate` runs, the running builder may write stale results back to caches after invalidation completes (the builders unconditionally write results in `portfolio_service.py:1661`, `workflow_cache.py:41`, `result_cache.py:98`). This is inherent to the cache architecture and acceptable for an admin tool — the stale data is TTL-bounded (5min profiles, 30s workflow snapshots) and will expire naturally. The tool response documents this: `"note": "If analysis is in-flight, stale data may briefly reappear until TTL expiry."`

```python
def _clear_all_ticker_caches(ticker: str) -> dict:
    from core.proxy_builder import clear_company_profile_cache, clear_gpt_peers_cache
    from utils.profile_overrides import _load_profile_overrides
    from services.portfolio_service import _load_sector_overrides, PortfolioService
    from services.portfolio.workflow_cache import clear_workflow_snapshot_caches
    from services.portfolio.result_cache import clear_result_snapshot_caches
    from providers.bootstrap import get_registry

    # Clear entire LFU caches — can't target FMP-resolved keys without user context
    clear_company_profile_cache()
    clear_gpt_peers_cache()

    # Clear entire FMP provider TTL profile cache
    fmp_cache_cleared = False
    try:
        provider = get_registry().get_profile_provider()
        if provider and hasattr(provider, 'clear_all_cached_profiles'):
            provider.clear_all_cached_profiles()
            fmp_cache_cleared = True
    except Exception:
        pass

    # Force YAML re-reads
    _load_profile_overrides.cache_clear()
    _load_sector_overrides.cache_clear()

    # Clear workflow + result snapshot caches
    clear_workflow_snapshot_caches()
    clear_result_snapshot_caches()

    # Clear position profile cache + inflight under shared lock
    # Must match PortfolioService.clear_cache() pattern (line 2191-2194)
    with PortfolioService._shared_snapshot_lock:
        PortfolioService._position_profile_cache.clear()
        PortfolioService._position_profile_inflight.clear()

    return {
        "profile_cache_cleared": True,
        "peers_cache_cleared": True,
        "fmp_cache_cleared": fmp_cache_cleared,
    }
```

### Latent bug note: `force_refresh` on `get_subindustry_peers_from_ticker`

`ensure_factor_proxies()` in `factor_proxy_service.py` passes `force_refresh=True` via `**peer_call_kwargs` (lines 210-212). However, the `cache_gpt_peers` decorator wrapper at `proxy_builder.py:222` has a fixed signature `def wrapper(ticker, start=None, end=None, fmp_ticker_map=None, instrument_types=None)` — no `**kwargs`. This means `force_refresh=True` would raise `TypeError` at the wrapper boundary. This code path only avoids crashing because `has_profile_override()` currently returns `False` for all tickers (empty YAML after Step 1), so `force_refresh` is never added to `peer_call_kwargs`. This is a pre-existing latent bug, not introduced by this plan.

### Pattern Reference
Follow `mcp_tools/instrument_config.py`:
- Decorator stacking: `@handle_mcp_errors` (outer) + `@require_db` (inner)
- DB access: `with get_db_session() as conn: db = DatabaseClient(conn)`
- Validation: normalize action to lowercase, check against `VALID_ACTIONS` tuple
- Response shape: `{"status": "success", "action": "...", ...data...}`
- Internal helpers: `_list_peers()`, `_get_ticker()`, `_invalidate()`, `_audit()`

### Edge Cases
- **Ticker not found in DB**: delete returns False/0, tool reports counts cleanly (no error)
- **Empty peer lists**: `get_subindustry_peers` returns None (missing) vs [] (empty) — surface via `found: true/false`
- **Comma-separated tickers**: `_parse_tickers()` splits and normalizes
- **Profile overrides intact**: infrastructure stays, YAML just has no entries. `has_profile_override()` returns False for all tickers.
- **Cache clear failures**: each cache clear is wrapped in try/except — partial success is OK for an admin tool

---

## Step 6: Register Tool

**File**: `mcp_server.py`

- Import `manage_proxy_cache` from `mcp_tools.proxy_cache`
- Add thin `@mcp.tool()` wrapper (after `manage_stress_scenarios` block ~line 1045)
- NOT added to `agent_registry` (admin tool, consistent with other `manage_*` tools)

---

## Step 7: Tests

### MCP tool tests — `tests/mcp_tools/test_proxy_cache.py` (~14 tests)
- list/get/invalidate/audit action flows
- comma-separated ticker parsing
- missing ticker validation
- ticker-not-found graceful handling
- invalid action raises ValueError
- `@require_db` behavior when DB unavailable
- invalidate calls all metadata cache-clear functions (mock and verify each of the 8 layers)
- invalidate clears entire LFU profile + peers caches (not targeted — FMP-resolved keys require user context)
- invalidate clears entire FMP provider TTL cache via `clear_all_cached_profiles()`
- invalidate clears both `_position_profile_cache` AND `_position_profile_inflight` under `_shared_snapshot_lock`

### GOLD regression tests
- `test_fmp_metadata.py`: `has_profile_override("GOLD")` returns `False`, FMP "Gold.com, Inc." passes through unmodified
- `test_portfolio_service.py` or `test_portfolio_service_asset_class_perf.py`: `_load_sector_overrides()` does not contain "GOLD"

### Override infrastructure tests (existing, updated)
- `test_fmp_metadata.py`: TESTCO override applies correctly (infrastructure still works)
- `test_factor_proxies.py`: TESTCO `has_profile_override` triggers force_refresh

### DB method tests (~6 tests)
- delete returns bool/count correctly
- list returns correct shape with age info using `COALESCE(updated_at, generated_at)`
- list_factor_proxies_for_ticker JOIN works

### No LFU `evict_key` tests needed
`evict_key()` is no longer part of the plan — invalidation uses full cache clears via existing `clear_company_profile_cache()` and `clear_gpt_peers_cache()`.

---

## Step 8: Invalidate GOLD from DB

After tool is built, use `manage_proxy_cache(action="invalidate", ticker="GOLD")` to clear stale Barrick proxy/peer metadata. Next analysis run (after PortfolioService result cache TTL expiry, ~30 min) rebuilds with correct Gold.com metadata.

---

## Known Residual Risk (Out of Scope)

`map_exchange_proxies("New York Stock Exchange", exchange_map)` does substring matching: `"nyse".lower() in "new york stock exchange".lower()`. Since "nyse" is NOT a contiguous substring of "new york stock exchange", GOLD falls through to DEFAULT (ACWX international) instead of NYSE (SPY domestic). This is a pre-existing exchange mapping issue, not introduced by this plan. It should be tracked as a separate TODO item for `core/proxy_builder.py:map_exchange_proxies()`.

---

## Files Changed

| File | Type | Description |
|------|------|-------------|
| `config/profile_overrides.yaml` | Edit | Remove GOLD entry, keep empty with comments |
| `config/sector_overrides.yaml` | Edit | Remove `GOLD: Basic Materials` |
| `providers/fmp_metadata.py` | Edit | Add `clear_all_cached_profiles()` method to `FMPProfileProvider` |
| `inputs/database_client.py` | Edit | 4 new methods for proxy/peer CRUD |
| `mcp_tools/proxy_cache.py` | **New** | `manage_proxy_cache()` MCP tool with full cache-layer clearing |
| `mcp_server.py` | Edit | Import + register tool |
| `tests/providers/test_fmp_metadata.py` | Edit | TESTCO override test + GOLD regression (no override) |
| `tests/services/test_factor_proxies.py` | Edit | Replace GOLD with TESTCO |
| `tests/mcp_tools/test_proxy_cache.py` | **New** | ~14 tests including cache-layer verification |

## Verification

1. Run `pytest tests/providers/test_fmp_metadata.py tests/services/test_factor_proxies.py` — updated tests pass
2. Run `pytest tests/mcp_tools/test_proxy_cache.py` — new tool tests pass
3. Use `manage_proxy_cache(action="get", ticker="GOLD")` to inspect current stale data
4. Use `manage_proxy_cache(action="invalidate", ticker="GOLD")` to clear proxy/peer metadata
5. Run portfolio analysis including GOLD — verify correct Gold.com metadata, Financial Services sector, no Barrick override
