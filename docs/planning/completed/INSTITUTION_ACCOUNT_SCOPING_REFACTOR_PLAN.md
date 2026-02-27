# Institution/Account Scoping Refactor

## Context

The system conflates "provider" (data pipe — Plaid, SnapTrade, Schwab API, IBKR Flex) with "institution" (brokerage — Charles Schwab, Interactive Brokers, Merrill) throughout the codebase. The `source` parameter on MCP tools accepts provider names (`"schwab"`, `"plaid"`) but users think in terms of institutions and accounts. This causes:

1. **Ambiguous `source` parameter** — `source="schwab"` is a provider name used as an institution filter
2. **Routing/partition tied to provider** — filtering logic is driven by provider name instead of institution
3. **Hard-coded dedup patches** — `_deduplicate_transactions()` in the analyzer and `_REALIZED_SOURCE_TOKEN_MAP` exist because the provider-centric model can't cleanly handle cross-provider institution overlap
4. **No account-level scoping** — users can't analyze individual accounts (e.g., retirement vs individual brokerage)

**Goal**: Separate provider from institution/account at the API layer. Add `institution` and `account` params to MCP tools. Keep internal provider tokens as-is. Drive routing by institution, not provider.

## Three Concepts

| Concept | Meaning | Examples | Parameter |
|---------|---------|----------|-----------|
| **Source** (provider) | Data pipe / API connection | `plaid`, `snaptrade`, `schwab`, `ibkr_flex` | `source=` (existing, keep as-is) |
| **Institution** | Brokerage where account lives | `charles_schwab`, `interactive_brokers`, `merrill` | `institution=` (new) |
| **Account** | Specific account at institution | `25524252`, `51388013` | `account=` (new) |

These are orthogonal filters:
- `institution="charles_schwab"` — all Schwab accounts, regardless of which provider fetched them
- `source="plaid"` — data from the Plaid provider, with routing applied (only institutions routed to Plaid)
- `institution="charles_schwab", account="25524252"` — one specific account

## Current State

### Provider-Institution Mapping

```
Provider (source)    Institution              Accounts
─────────────────    ───────────────────       ────────────────────────────
plaid                Merrill                   CMA-Edge (DSU, IT, MSCI, STWD)
schwab               Charles Schwab            25524252, 51388013, 87656165
snaptrade            Interactive Brokers       (Henry Chien) — 11 symbols
ibkr_flex            Interactive Brokers       U2471778
```

### Where Provider/Institution Are Conflated

1. **MCP `source` param** — `source="schwab"` is a provider name used as institution filter
2. **`_REALIZED_SOURCE_TOKEN_MAP`** (`core/realized_performance_analysis.py:80-93`) — hard-coded map from institution names ("charles schwab") to provider tokens ("schwab")
3. **`_IBKR_INSTITUTION_NAMES`** (`trading_analysis/analyzer.py:43`) — hard-coded set for dedup
4. **`_deduplicate_transactions()`** (`trading_analysis/analyzer.py:470-510`) — hard-coded Plaid↔IBKR dedup that predates routing infrastructure
5. **`_build_source_scoped_holdings()`** (`core/realized_performance_analysis.py:679-796`) — reverse-engineers provider from position metadata to scope holdings

### Routing Infrastructure (Already Clean)

The routing tables in `providers/routing_config.py` correctly model institution → provider:
```python
TRANSACTION_ROUTING = {"interactive_brokers": "ibkr_flex", "charles_schwab": "schwab"}
POSITION_ROUTING = {"charles_schwab": "schwab"}
INSTITUTION_SLUG_ALIASES = {"interactive brokers": "interactive_brokers", "ibkr": "interactive_brokers", "charles schwab": "charles_schwab", "schwab": "charles_schwab"}
```

The routing functions in `providers/routing.py` (`resolve_institution_slug()`, `partition_transactions()`, `partition_positions()`) are well-designed. The problem is that downstream code doesn't fully use them.

### Account ID Semantics

Schwab stores account data as:
- `account_id` = opaque hash from Schwab API (e.g., `"hash-abc123"`)
- `account_name` = display account number (e.g., `"25524252"`)

The `account` parameter must match flexibly against **both** `account_id` and `account_name` since users will provide display numbers, not internal hashes.

### `get_positions` Tool Note

`get_positions` (`mcp_tools/positions.py`) does **not** currently have a `source` parameter. It has:
- `brokerage` — institution-level filter (already institution-scoped!)
- `refresh_provider` — which provider to refresh from

This tool only needs the new `account` parameter (it already has institution filtering via `brokerage`).

## Design Decision: No Provider Token Rename

**Original plan**: Rename `"schwab"` → `"schwab_api"` to disambiguate provider from institution.

**Decision**: Do NOT rename internal provider tokens. The rename touches 30+ files, requires DB migration (`position_source` is part of a unique constraint), breaks `trade_execution_service.py` provider detection, and ripples through settings, CLIs, flow extractors, and normalizers. The blast radius is disproportionate to the value.

Instead, disambiguation comes from the **parameter names themselves**: `source=` is clearly the provider pipe, `institution=` is the brokerage. Internal code continues using `"schwab"` as the provider token. Documentation and docstrings clarify the distinction.

## Phased Commits (Single PR)

### Phase 1: Institution Provider Resolver

Add `resolve_providers_for_institution()` to `providers/routing.py` — the missing piece that maps an institution to the provider(s) that should be queried.

```python
def resolve_providers_for_institution(
    institution: str,
    data_type: str = "transactions",  # "transactions" or "positions"
) -> list[str]:
    """Return ordered list of providers to query for an institution.

    Checks canonical provider first (from TRANSACTION_ROUTING/POSITION_ROUTING),
    falls back to default providers if canonical is unavailable.
    """
    slug = resolve_institution_slug(institution)
    if not slug:
        # Unknown institution — fall back to all enabled default providers.
        # Institution filter will be applied post-fetch to narrow results.
        defaults = DEFAULT_TRANSACTION_PROVIDERS if data_type == "transactions" else DEFAULT_POSITION_PROVIDERS
        return [p for p in defaults if is_provider_available(p)]
    routing = TRANSACTION_ROUTING if data_type == "transactions" else POSITION_ROUTING
    canonical = routing.get(slug)
    if canonical and is_provider_available(canonical):
        return [canonical]
    # Fallback: which default providers could serve this institution?
    defaults = DEFAULT_TRANSACTION_PROVIDERS if data_type == "transactions" else DEFAULT_POSITION_PROVIDERS
    return [p for p in defaults if is_provider_available(p)]
```

Also add `resolve_provider_token()` for consolidating `_REALIZED_SOURCE_TOKEN_MAP`:

```python
_PROVIDER_NAME_ALIASES = {"ibkr": "ibkr_flex", "ibkr flex": "ibkr_flex", "snap trade": "snaptrade"}
_CANONICAL_PROVIDERS = {"snaptrade", "plaid", "ibkr_flex", "schwab"}

def resolve_provider_token(value: str) -> str | None:
    """Resolve free-text provider or institution name to canonical provider token."""
    collapsed = " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())
    if not collapsed:
        return None
    if collapsed in _CANONICAL_PROVIDERS:
        return collapsed
    if collapsed in _PROVIDER_NAME_ALIASES:
        return _PROVIDER_NAME_ALIASES[collapsed]
    slug = resolve_institution_slug(collapsed)
    if slug:
        return TRANSACTION_ROUTING.get(slug)
    return None
```

**Files:**
- `providers/routing.py` — add both functions
- `tests/providers/test_routing.py` — test cases for both

### Phase 2: Add `institution` and `account` parameters to MCP tools

Add new optional params alongside existing `source`. The `source` parameter keeps its existing values and semantics. Note: Phase 3 item 1 (explicit-source partition) changes `source="plaid"`/`"snaptrade"` to apply routing partition — this should land before Phase 2 so the behavior matrix is correct from the start.

```python
def get_performance(
    source: Literal["all", "snaptrade", "plaid", "ibkr_flex", "schwab"] = "all",
    institution: Optional[str] = None,   # NEW — "charles_schwab", "merrill", etc.
    account: Optional[str] = None,       # NEW — account number or account ID
    ...
)
```

**Tools to update** (3 tools that currently accept `source`):
- `mcp_tools/performance.py` — `get_performance()`: add `institution`, `account`
- `mcp_tools/trading_analysis.py` — `get_trading_analysis()`: add `institution`, `account`
- `mcp_tools/tax_harvest.py` — `suggest_tax_loss_harvest()`: add `institution`, `account`

**Tool with existing institution filtering** (1 tool):
- `mcp_tools/positions.py` — `get_positions()`: already has `brokerage` (= institution filter). Add `account` only. Also add `institution` as an alias for `brokerage` for API consistency — if both are provided, `institution` takes precedence. The `brokerage` param is kept for backwards compatibility but `institution` is the preferred name going forward.

**`mcp_server.py`**: Update tool registration signatures for new params.

**Account matching logic** — case-insensitive exact match against both `account_id` AND `account_name`:
```python
def _match_account(row: dict, account_filter: str) -> bool:
    """Match account filter against account_id or account_name.

    Uses case-insensitive exact equality (not substring) to avoid false positives.
    For example, account "2552" should NOT match account_name "25524252".
    Case-insensitive to handle IBKR-style IDs that users may vary in case (e.g., "u2471778" vs "U2471778").
    """
    normalized_filter = account_filter.strip().lower()
    account_id = str(row.get("account_id") or "").strip().lower()
    account_name = str(row.get("account_name") or "").strip().lower()
    return normalized_filter in (account_id, account_name)
```

**Position consolidation**: When `institution` or `account` is provided, force `consolidate=False` to preserve per-account rows. Cross-provider consolidation (`position_service.py:417,510`) drops `brokerage_name`/`account_id`/`account_name` metadata during grouping, making post-fetch institution/account filtering unreliable on consolidated rows. This rule applies everywhere: MCP tool code, tax harvest, realized performance.

**Filter resolution rules** (applied in order):

1. **Source resolution**: Determines which provider(s) to fetch from.
   - `source="all"` (default): fetch from all enabled providers, apply routing partition to aggregator data
   - `source="plaid"` / `"snaptrade"` / etc.: fetch from that specific provider, apply routing partition (aggregator data filtered by institution routing)
   - When `institution` is set and `source="all"`: fetch from all providers, apply routing partition, then filter by institution. (The `resolve_providers_for_institution()` resolver is used internally as an optimization to skip providers that can't serve the requested institution, but the result is the same.)

2. **Institution filter** (post-fetch): When `institution` is set, filter positions and transactions to rows matching that institution's `brokerage_name` via `match_institution()`.

3. **Account filter** (post-fetch): When `account` is set, filter positions and transactions to rows where `account_id` or `account_name` matches. Applied after institution filter. Forces `consolidate=False`.

4. **Incompatible filters**: When `source` + `institution` point to incompatible data (e.g., `source="ibkr_flex", institution="charles_schwab"`), the result is empty — no error, just no matching data.

5. **Availability fallback**: Routing partition only drops aggregator rows when the canonical provider is available. If `ibkr_flex` is unavailable, `institution_belongs_to_provider("interactive brokers", "plaid")` returns `True` (fallback to defaults) — so Plaid/SnapTrade IBKR rows survive. Matrix rows marked "empty" for aggregator+IBKR assume `ibkr_flex` is available; when unavailable, those rows would return data instead.

**Behavior matrix** (representative examples):

| `source` | `institution` | `account` | Fetch from | Filter | Expected result |
|----------|--------------|-----------|------------|--------|-----------------|
| `"all"` | None | None | All providers | Routing partition | All data (current default) |
| `"all"` | `"charles_schwab"` | None | All providers | Institution=Schwab | All Schwab accounts |
| `"all"` | `"charles_schwab"` | `"25524252"` | All providers | Institution+Account | One Schwab account |
| `"all"` | `"interactive_brokers"` | None | All providers | Institution=IBKR | All IBKR accounts |
| `"all"` | `"merrill"` | None | All providers | Institution=Merrill | Merrill account only |
| `"all"` | None | `"25524252"` | All providers | Account only | Account across all institutions |
| `"schwab"` | None | None | Schwab API | None | Schwab API data |
| `"schwab"` | None | `"25524252"` | Schwab API | Account | One Schwab account |
| `"schwab"` | `"charles_schwab"` | `"25524252"` | Schwab API | Institution+Account | One Schwab account |
| `"schwab"` | `"interactive_brokers"` | None | Schwab API | Institution=IBKR | Empty (incompatible) |
| `"plaid"` | None | None | Plaid | Routing partition | Plaid-routed institutions (Merrill) |
| `"plaid"` | `"merrill"` | None | Plaid | Institution=Merrill | Merrill via Plaid |
| `"plaid"` | `"interactive_brokers"` | None | Plaid | Institution=IBKR | Empty when ibkr_flex available (IBKR routed away); data when ibkr_flex unavailable (fallback) |
| `"snaptrade"` | None | None | SnapTrade | Routing partition | SnapTrade-routed institutions |
| `"snaptrade"` | `"interactive_brokers"` | None | SnapTrade | Routing+Institution=IBKR | Empty when ibkr_flex available (IBKR routed away); data when ibkr_flex unavailable (fallback) |
| `"snaptrade"` | None | `"U2471778"` | SnapTrade | Account | Empty when ibkr_flex available (IBKR routed away from SnapTrade); data when ibkr_flex unavailable (fallback) |
| `"ibkr_flex"` | None | None | IBKR Flex | None | IBKR Flex data (direct provider, no partition needed) |
| `"ibkr_flex"` | None | `"U2471778"` | IBKR Flex | Account | One IBKR account |
| `"ibkr_flex"` | `"charles_schwab"` | None | IBKR Flex | Institution=Schwab | Empty (incompatible) |

**For the realized performance path — holdings:**
- `analyze_realized_performance()` already has an `institution` parameter — thread it from the MCP `institution` param
- Add `account` parameter to `analyze_realized_performance()` and thread to `_build_source_scoped_holdings()`
- In `_build_source_scoped_holdings()`: when `institution` is provided, filter by `brokerage_name` directly (using existing `match_institution()`). When `account` is provided, filter by `_match_account()`.

**For the trading analysis path — NormalizedTrade model update:**
- `NormalizedTrade` (`trading_analysis/models.py:212`) already has `institution` but lacks `account_id`/`account_name` fields. Add optional `account_id: Optional[str] = None` and `account_name: Optional[str] = None` fields to `NormalizedTrade`.
- Update normalizers that produce `NormalizedTrade` to propagate account metadata from raw transactions. The normalizers live in `providers/normalizers/` (not `trading_analysis/normalizers/`) and are wired from `TradingAnalyzer._normalize_transactions()` (`trading_analysis/analyzer.py:143`). Specifically: `providers/normalizers/plaid.py`, `providers/normalizers/snaptrade.py`, `providers/normalizers/ibkr_flex.py`, `providers/normalizers/schwab.py`.
- `NormalizedIncome` (`models.py:230`) already has `account_id` and `account_name` — no changes needed.
- Account filtering on `trades` (list of `NormalizedTrade`) uses `_match_account()` against `trade.account_id` / `trade.account_name`.

**For the realized performance path — transactions:**
- Thread `account` through to transaction filtering in the analyzer. After FIFO normalization, filter `fifo_transactions` and `trades` by account:
  - Each normalized transaction carries `account_id` and `account_name` (attached during normalization per above)
  - Apply `_match_account()` to filter transactions to the target account
  - Also filter `income_events` (carry `account_id`, `account_name` fields already)
  - Provider-flow events (`provider_flows`) carry account metadata — filter both events and fetch metadata by account before coverage/authority logic
- **Account-aware dedup**: The current dedup key in `_deduplicate_transactions()` (`analyzer.py:460`) does not include account identity. When `account` is set, add `account_id` to the dedup key to prevent matching transactions across different accounts that share the same (symbol, type, date, qty, price) signature. This change goes in `trading_analysis/analyzer.py` as part of Phase 2 (not Phase 3 dedup deprecation).
- This ensures holdings AND transactions are scoped to the same account, producing correct per-account returns.

**Tax harvest account/institution scoping:**
- Position loading (`tax_harvest.py:814`): `get_all_positions()` only accepts `use_cache`, `force_refresh`, `consolidate` — it has no institution/account params. Instead, apply institution/account filtering **post-fetch** in the tool code: load all positions with `consolidate=False` (when `institution` or `account` is set — consolidation drops brokerage/account metadata), then filter the resulting position list by institution (`match_institution()` on `brokerage_name`) and/or account (`_match_account()`).
- Transaction/FIFO loading: Thread `institution`/`account` to `_load_fifo_data()` which calls through to the analyzer.
- **Wash sale scope**: Wash sale checks intentionally widen to `source="all"` (`tax_harvest.py:909`) to catch cross-account wash sales. This is **correct IRS behavior** — wash sales apply across all accounts. When `account` or `institution` is set, the candidate universe narrows but the wash sale scan still uses all-source transactions. Add a comment documenting this intentional widening.

**For the transaction fetch path:**
- When only `institution` is set (no `source`): use `resolve_providers_for_institution()` to determine which providers to call, then filter results by institution
- When only `source` is set: fetch from that provider, apply routing partition (consistent with `source="all"` behavior)
- When both are set: fetch from `source` provider, apply routing partition, then filter by `institution`
- `account` filtering is applied post-fetch (after normalization), not at the fetch level, because providers don't support account-level fetch granularity

### Phase 3: Consolidate hard-coded maps + dedup cleanup

> **Ordering note**: Item 1 (explicit-source partition) should be implemented **before or alongside Phase 2**, not after. The Phase 2 behavior matrix assumes routing partition is applied for all `source` values — that assumption only holds once this item lands. In practice, commit this as the first commit in Phase 3, or as the last commit of Phase 1.

1. **Apply routing partition for explicit source fetches** in `fetch_transactions_for_source()` (`trading_analysis/data_fetcher.py:819-831`):
   - Add `_partition_provider_payload()` call between fetch and merge for explicit sources
   - This makes `source="plaid"` drop IBKR-institution rows via routing (consistent with `source="all"` behavior)
   - Update docstring to remove "bypass" language
   - **Behavior change**: `source="plaid"` previously returned ALL Plaid data including IBKR-institution rows. After this change, it only returns Plaid data for institutions routed to Plaid (e.g., Merrill). This is the intended behavior — `source="plaid"` means "institutions served by Plaid," not "raw Plaid API dump." Add regression tests for the new behavior.

2. **Replace `_REALIZED_SOURCE_TOKEN_MAP`** (`core/realized_performance_analysis.py:80-93`):
   - Replace `_normalize_source_token()` with delegation to `resolve_provider_token()` from Phase 1
   - Delete the hard-coded map
   - Keep `REALIZED_PROVIDER_ALIAS_MAP` (lines 96-99) — different concern (cash replay display names)

3. **Deprecate `_deduplicate_transactions()`** (`trading_analysis/analyzer.py:470-510`):
   - Add a feature flag `DEDUP_LEGACY_ENABLED` (default `True`) guarding the dedup
   - Log when dedup actually removes rows (visibility for transition)
   - Plan to remove entirely once institution-driven fetching is proven via regression tests
   - Do NOT remove immediately — keep as safety net until alias coverage is verified

### Phase 4: Tests

**`tests/providers/test_routing.py`:**
- `test_resolve_providers_for_institution_canonical_available` — schwab → `["schwab"]`
- `test_resolve_providers_for_institution_canonical_unavailable` — falls back to defaults
- `test_resolve_providers_for_institution_unknown` — unrecognized institution → falls back to all enabled default providers
- `test_resolve_provider_token_provider_name` — `"plaid"` → `"plaid"`
- `test_resolve_provider_token_institution_name` — `"charles schwab"` → `"schwab"`
- `test_resolve_provider_token_alias` — `"ibkr"` → `"ibkr_flex"`

**`tests/trading_analysis/test_provider_routing.py`:**
- Update `test_fetch_transactions_for_source_snaptrade_bypasses_partition` → assert partition applied (IBKR rows dropped)
- Update `test_fetch_transactions_for_source_plaid_bypasses_partition` → assert partition applied
- Add `test_fetch_transactions_for_source_plaid_keeps_merrill` — Merrill rows survive partition

**`tests/core/test_realized_performance_analysis.py`:**
- `test_account_scoping_filters_holdings_by_account_id` — positions filtered to matching account
- `test_account_scoping_filters_holdings_by_account_name` — display number match
- `test_account_scoping_filters_transactions_by_account` — FIFO txns filtered to account
- `test_account_scoping_filters_income_by_account` — income events filtered to account
- `test_institution_scoping_filters_holdings` — positions filtered by institution
- `test_institution_and_account_combined` — both filters applied

**`tests/mcp_tools/test_performance.py`** (or equivalent):
- `test_get_performance_realized_with_institution` — institution param threaded
- `test_get_performance_realized_with_account` — account param threaded

**`tests/services/test_portfolio_service.py`:**
- `test_analyze_realized_performance_with_account` — account param threaded to core
- `test_analyze_realized_performance_cache_key_includes_account` — different account → different cache key

**`tests/mcp_tools/test_trading_analysis.py`:**
- `test_get_trading_analysis_with_institution` — institution param threaded
- `test_get_trading_analysis_with_account` — account param threaded

**`tests/mcp_tools/test_tax_harvest.py`** (or equivalent):
- `test_suggest_tax_loss_harvest_with_institution` — institution param threaded
- `test_suggest_tax_loss_harvest_with_account` — account param threaded

**`tests/providers/normalizers/test_*_normalizer.py`** (per-provider):
- `test_plaid_normalizer_propagates_account_metadata` — `NormalizedTrade` has `account_id`/`account_name` from Plaid raw transaction
- `test_snaptrade_normalizer_propagates_account_metadata` — same for SnapTrade
- `test_ibkr_flex_normalizer_propagates_account_metadata` — same for IBKR Flex
- `test_schwab_normalizer_propagates_account_metadata` — same for Schwab

**`tests/trading_analysis/test_analyzer.py`** (or equivalent):
- `test_dedup_includes_account_id_when_account_filter_active` — same (symbol, type, date, qty, price) in different accounts are NOT deduped
- `test_dedup_without_account_filter_unchanged` — dedup behavior unchanged when no account filter

**`tests/mcp_tools/test_positions_agent_format.py`:**
- `test_get_positions_with_account` — account filter applied to position rows
- `test_get_positions_institution_alias_precedence` — when both `institution` and `brokerage` are provided, `institution` takes precedence
- `test_get_positions_brokerage_backwards_compat` — `brokerage` param still works when `institution` is not provided

**`tests/trading_analysis/test_provider_routing.py`** (availability fallback):
- `test_plaid_ibkr_institution_returns_data_when_ibkr_flex_unavailable` — `source="plaid", institution="interactive_brokers"` returns Plaid IBKR rows when `ibkr_flex` provider is unavailable (fallback behavior)
- `test_plaid_ibkr_institution_empty_when_ibkr_flex_available` — same params return empty when `ibkr_flex` is available (routing partitions IBKR away from Plaid)
- `test_snaptrade_ibkr_institution_fallback_behavior` — same pattern for SnapTrade + IBKR

**`tests/unit/test_mcp_server_contracts.py`:**
- Update tool signature tests for new `institution`/`account` params

**Full suite**: `pytest tests/ --timeout=120`

### Live Regression Tests

Capture baselines **before** implementation, then verify after each phase. These protect the realized performance returns we've carefully tuned through P3.2.

**Determinism controls**: All live test calls that support `use_cache` use `use_cache=False` to ensure fresh data. Tools without a `use_cache` param (e.g., `get_trading_analysis`) are inherently fresh per call. Baselines and re-runs should be done in the same session or close together to minimize data drift (new transactions, price changes). Comparison is on **domain metrics** (return metrics for performance, trade count + symbol set for trading analysis, candidate count + ticker set for tax harvest, position count + symbol set for positions), not on timestamps, cache metadata, or timing fields. Provider availability must be consistent across runs — if `ibkr_flex` was available during baseline capture, it must be available during re-run (check via provider status in response).

**Pre-implementation baseline capture** (run once, save outputs):
```bash
# Realized performance — all sources combined (the headline number)
# Expected: Combined +34.66%, IBKR +10.45%, Schwab +33.13%, Plaid -7.96%
get_performance(mode="realized", source="all", format="full", use_cache=False)

# Per-source realized performance
get_performance(mode="realized", source="schwab", format="full", use_cache=False)
get_performance(mode="realized", source="ibkr_flex", format="full", use_cache=False)
get_performance(mode="realized", source="plaid", format="full", use_cache=False)
get_performance(mode="realized", source="snaptrade", format="full", use_cache=False)

# Trading analysis — all sources + per-source (no use_cache param)
get_trading_analysis(source="all", format="full")
get_trading_analysis(source="plaid", format="full")
get_trading_analysis(source="snaptrade", format="full")

# Tax harvest — baseline
suggest_tax_loss_harvest(source="all", format="full", use_cache=False)

# Positions — all
get_positions(format="full", use_cache=False)
```

Save full JSON outputs to `docs/planning/performance-actual-2025/live_test/` with `pre_refactor_` prefix.

**After Phase 1** (resolver only — no behavior change expected):
- Re-run all baseline calls. Domain metrics must **match** baseline — Phase 1 is purely additive.

**After Phase 3 item 1** (explicit-source partition — behavior change):
- `source="all"`: domain metrics must match baseline (routing already applied for `source="all"`)
- `source="schwab"`, `source="ibkr_flex"`: domain metrics must match baseline (direct providers, no partition change)
- `source="plaid"`: **expected to change** — IBKR-institution rows now dropped by routing partition. Structural checks: verify Merrill rows survive (count > 0), IBKR-institution rows removed (count = 0). Note: if `ibkr_flex` is unavailable during the test, Plaid IBKR rows survive as fallback — verify provider status matches baseline.
- `source="snaptrade"`: **expected to change** — IBKR-institution rows now dropped if `ibkr_flex` available (same fallback caveat as Plaid).
- `get_trading_analysis(source="all")`: trade count and symbol set must match baseline (routing already applied for `source="all"`)
- `get_trading_analysis(source="plaid")` and `get_trading_analysis(source="snaptrade")`: same expected changes as realized perf — verify IBKR-institution trades removed, other institution trades retained (Merrill trades present in Plaid output).

**After Phase 2** (new params — existing behavior unchanged, new paths work):
- All `source=` calls from baseline: domain metrics must match post-Phase-3-item-1 outputs
- New calls to verify:
  ```bash
  get_performance(mode="realized", institution="charles_schwab", format="full", use_cache=False)
  # Return metrics should match source="schwab" baseline

  get_performance(mode="realized", institution="interactive_brokers", format="full", use_cache=False)
  # Return metrics should match source="ibkr_flex" baseline

  get_performance(mode="realized", institution="charles_schwab", account="25524252", format="full", use_cache=False)
  # Symbols in monthly_returns must be a subset of institution="charles_schwab" symbols.
  # total_return_pct may differ (single account vs all accounts). Verify it is a valid number, not NaN/null.

  get_trading_analysis(institution="interactive_brokers", format="full")
  # Trade count + symbol set should match source="ibkr_flex" trading analysis (if baselined) or ibkr_flex performance symbol set

  get_positions(institution="Charles Schwab", account="25524252", format="full", use_cache=False)

  suggest_tax_loss_harvest(institution="charles_schwab", format="full", use_cache=False)
  # Candidates should be subset of source="all" baseline candidates
  ```

**After Phase 3 remainder** (map consolidation + dedup deprecation):
- Re-run all calls. Domain metrics must match Phase 2 outputs — consolidation is internal refactoring only.
- Verify `DEDUP_LEGACY_ENABLED=True` (default) produces same results as before.
- Verify dedup logging fires when duplicates are detected.

**Failure criteria**:
- **Realized performance return metrics**: Any change in `total_return_pct` or `monthly_returns` for existing `source=` calls (outside of Phase 3 item 1 expected changes) is a regression and blocks the phase.
- **Trading analysis stability**: `get_trading_analysis(source="all")` trade count and symbol set must match baseline across all phases. Per-source calls follow same Phase 3 item 1 expected-change rules as realized perf.
- **Tax harvest stability**: `suggest_tax_loss_harvest(source="all")` candidate count and ticker set must match baseline across phases. Institution-scoped calls (`institution="charles_schwab"`) must produce a strict subset of the `source="all"` candidate tickers.
- **Positions stability**: `get_positions()` position count and symbol set must match baseline. Institution/account-scoped calls must produce a strict subset of baseline positions.
- **Institution-scoped equivalence** (Phase 2): For performance, `institution="charles_schwab"` return metrics must match `source="schwab"` baseline. `institution="interactive_brokers"` must match `source="ibkr_flex"` baseline. For trading analysis, `institution="interactive_brokers"` trade symbols must be a subset of `source="all"` IBKR-institution trades. For all tools, `institution=X, account=Y` must produce a subset of `institution=X` by symbol/ticker set. Return metrics for account-scoped calls may differ from institution-scoped (different account mix) but must be valid numbers (not NaN/null).
- **Structural invariants for Phase 3 item 1**: `source="plaid"` must have 0 IBKR-institution rows and >0 Merrill rows. `source="snaptrade"` must have 0 IBKR-institution rows (when ibkr_flex available). Machine-check via institution field on returned rows/transactions.
- **Provider availability**: If provider availability differs between baseline and re-run, results are not comparable — re-capture baseline first.

## Files to Modify

| Phase | File | Change |
|-------|------|--------|
| 1 | `providers/routing.py` | Add `resolve_providers_for_institution()`, `resolve_provider_token()` |
| 1 | `tests/providers/test_routing.py` | Test both new functions |
| 2 | `mcp_tools/performance.py` | Add `institution`, `account` params; thread to realized perf |
| 2 | `mcp_tools/trading_analysis.py` | Add `institution`, `account` params |
| 2 | `mcp_tools/tax_harvest.py` | Add `institution`, `account` params |
| 2 | `mcp_tools/positions.py` | Add `account` param + `institution` alias for `brokerage` |
| 2 | `mcp_server.py` | Update tool registration signatures |
| 2 | `core/realized_performance_analysis.py` | Add `account` param to `analyze_realized_performance()`, thread to `_build_source_scoped_holdings()` |
| 2 | `services/portfolio_service.py` | Add `account` param to `analyze_realized_performance()`, include in cache key |
| 2 | `services/position_service.py` | Support `account` filter in position loading (for `consolidate=False` path) |
| 2 | `trading_analysis/data_fetcher.py` | Add institution-driven fetch path |
| 2 | `trading_analysis/models.py` | Add `account_id`, `account_name` fields to `NormalizedTrade` |
| 2 | `providers/normalizers/{plaid,snaptrade,ibkr_flex,schwab}.py` | Propagate account metadata to `NormalizedTrade` |
| 2 | `trading_analysis/analyzer.py` | Add `account_id` to dedup key when account filtering active |
| 3 | `trading_analysis/data_fetcher.py` | Apply routing partition for explicit source fetches (**land before Phase 2**) |
| 3 | `core/realized_performance_analysis.py` | Replace `_REALIZED_SOURCE_TOKEN_MAP` with `resolve_provider_token()` delegation |
| 3 | `trading_analysis/analyzer.py` | Gate `_deduplicate_transactions` behind feature flag + add logging |
| 3 | `tests/trading_analysis/test_provider_routing.py` | Update bypass tests → partition tests |
| 4 | Various test files | New tests for institution/account filtering |

## Verification

```bash
# After each phase
pytest tests/ -x --timeout=120

# Phase 1 — resolver tests
pytest tests/providers/test_routing.py -v -k "resolve_provider"

# Phase 2 — new param integration
pytest tests/mcp_tools/ -v
# MCP tool calls:
get_performance(mode="realized", institution="charles_schwab")
get_performance(mode="realized", institution="charles_schwab", account="25524252")
get_trading_analysis(institution="interactive_brokers")
get_positions(brokerage="Schwab", account="25524252")

# Phase 3 — dedup + routing consolidation
pytest tests/trading_analysis/test_provider_routing.py -v
pytest tests/core/test_realized_performance_analysis.py -v -k "source_scoped"

# Full suite
pytest tests/ --timeout=120
```

## Review Response Log

### Review 1 (Codex) — FAIL, 5 HIGH / 3 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Institution→provider resolver underspecified | Added `resolve_providers_for_institution()` in Phase 1 with explicit fallback logic |
| 2 | HIGH | Phase 1 rename blast radius larger than listed | **Dropped the rename entirely.** Disambiguation comes from parameter names (`source=` vs `institution=`), not token renaming. Avoids 30+ file changes, DB migration, trade execution breakage. |
| 3 | HIGH | DB `position_source` rename risk underplayed | N/A — rename dropped |
| 4 | HIGH | Trade execution service breaks with renamed token | N/A — rename dropped |
| 5 | HIGH | Account semantics incorrect (hash vs display number) | Added `_match_account()` that matches against both `account_id` AND `account_name`. Forced `consolidate=False` when `account` is provided. |
| 6 | MEDIUM | Dedup removal not safely justified | Changed to feature-flag deprecation (`DEDUP_LEGACY_ENABLED=True`), keep as safety net, log when triggered, remove after regression proof |
| 7 | MEDIUM | `get_positions` doesn't have `source` param | Corrected: only add `account` to `get_positions` (it already has `brokerage` for institution filtering) |
| 8 | MEDIUM | No backward compatibility plan | N/A — no rename means no breaking changes. `source` param unchanged. New `institution`/`account` are purely additive. |

### Review 2 (Codex) — FAIL, 1 HIGH / 2 MEDIUM / 1 LOW

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Account scoping not plumbed end-to-end — `portfolio_service.py` missing `account` param | Added `services/portfolio_service.py` and `services/position_service.py` to Phase 2 file list. `portfolio_service.py` already has `institution`, needs `account` added to signature + cache key. |
| 2 | MEDIUM | Behavior matrix incomplete — missing `source="all" + account only` and `source + account` without institution | Added 3 missing rows to behavior matrix: `all+account`, `schwab+account`, `plaid+account` |
| 3 | MEDIUM | File list/test plan gaps — service boundary and position service not listed | Added `portfolio_service.py` and `position_service.py` to Phase 2 file list |
| 4 | LOW | Explicit-source partition is a behavior change for diagnostics | Added documentation note in Phase 3 about behavior change + regression test requirement |

### Review 3 (Codex) — FAIL, 1 HIGH / 3 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Account scoping not plumbed on transaction side | Added explicit transaction-side account filtering: `_match_account()` applied to `fifo_transactions`, `trades`, `income_events`, and `provider_flows` after normalization. Account filtering is post-fetch (providers don't support account-level fetch granularity). |
| 2 | MEDIUM | Behavior matrix missing snaptrade/ibkr_flex permutations | Added 7 rows covering `snaptrade` and `ibkr_flex` with institution/account combinations, including empty-result cases for incompatible filters |
| 3 | MEDIUM | Explicit-source partition behavior internally inconsistent | Resolved wording: `source="plaid"` means "institutions served by Plaid" — partition always applies. Removed contradictory "raw Plaid data before partition" language. |
| 4 | MEDIUM | Test scope too generic | Replaced generic bullet points with specific test names organized by test file: 6 routing tests, 3 provider routing tests, 6 realized perf tests, 1 service test, contract test updates |

### Review 4 (Codex) — FAIL, 2 HIGH / 3 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Explicit-source semantics still inconsistent — "raw pipe" wording contradicts partition behavior | Removed all "raw pipe" references. Replaced with consistent wording: explicit `source` always has routing partition applied. Updated Three Concepts section and behavior matrix. |
| 2 | HIGH | Behavior matrix still incomplete | Replaced matrix with explicit filter resolution rules (4 numbered rules) + comprehensive 21-row decision table covering all source/institution/account permutations including incompatible filters and institution-only (no source) cases |
| 3 | MEDIUM | Unknown institution resolver returns `[]` — can drop valid data | Changed fallback: unknown institution now returns all enabled default providers. Institution filter applied post-fetch to narrow results. |
| 4 | MEDIUM | Transaction dedup not account-aware | Added account-aware dedup: apply account filter BEFORE dedup runs, or add `_account_id` to dedup key when account filtering is active. Also filter provider flow metadata by account before coverage/authority logic. |
| 5 | MEDIUM | Tests missing for trading_analysis, tax_harvest, positions, cache key | Added specific test names for all 4 MCP tools + cache key variance test in portfolio_service |

### Review 5 (Codex) — FAIL, 2 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | MEDIUM | "Raw pipe" wording still in transaction fetch path description | Replaced "raw pipe" with "apply routing partition" in fetch path rules |
| 2 | MEDIUM | Unknown institution test expects `[]` but resolver now returns defaults | Updated test expectation to match resolver behavior: falls back to all enabled default providers |

### Review 6 (Codex) — FAIL, 2 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | MEDIUM | `source` defaults to `"all"` so `source=None` branch is unreachable | Removed `source=None` rows from matrix. Institution-only optimization via resolver happens inside `source="all"` path, not a separate branch. Updated filter rule 1 wording. |
| 2 | MEDIUM | SnapTrade+IBKR matrix row says "if routing allows" — ambiguous | Clarified: IBKR is routed to ibkr_flex, so routing partition drops IBKR rows from SnapTrade → result is empty. Same logic as Plaid+IBKR. |

### Review 7 (Codex) — FAIL, 1 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | MEDIUM | Availability fallback inconsistent with "always empty" matrix claims | Added Rule 5 (availability fallback) explaining that aggregator rows survive when canonical provider is unavailable. Updated matrix rows for plaid+IBKR and snaptrade+IBKR to note conditional behavior. |

### Review 8 (Codex) — PASS

No issues found. Plan approved.

### Review 9 (Self) — PASS, 3 LOW

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | LOW | Phase ordering: Phase 3 item 3 (explicit-source partition) must land before Phase 2 for behavior matrix to hold | Reordered Phase 3 items — partition is now item 1 with ordering note to commit before/alongside Phase 2 |
| 2 | LOW | `_match_account` exact match semantics undocumented | Added docstring clarifying exact equality, not substring matching |
| 3 | LOW | `brokerage` vs `institution` param naming discrepancy on `get_positions` | Added `institution` as alias for `brokerage` on `get_positions` for API consistency. `brokerage` kept for backwards compat. |

### Review 10 (Codex) — FAIL, 2 HIGH / 3 MEDIUM / 1 LOW

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | `NormalizedTrade` lacks `account_id`/`account_name` fields — account scoping on trades not implementable | Added `account_id`, `account_name` optional fields to `NormalizedTrade` model. Added `trading_analysis/models.py` and `trading_analysis/normalizers/*.py` to Phase 2 file list. Normalizers propagate account metadata from raw transactions. |
| 2 | HIGH | Tax harvest account/institution scoping underspecified — position loading, FIFO scoping, wash sale widening | Added detailed tax harvest scoping section: position loading narrows by institution/account, FIFO loading threads filters, wash sale scan intentionally stays all-source (correct IRS behavior). |
| 3 | MEDIUM | Phase 2 says source works "exactly as before" but Phase 3 changes explicit-source behavior | Reworded Phase 2 intro to reference the Phase 3 partition change and note it should land first. |
| 4 | MEDIUM | Ordering note references "Item 3" but partition is now Item 1 | Fixed reference to "Item 1". |
| 5 | MEDIUM | Test plan missing `get_performance` with account/institution coverage | Added `tests/mcp_tools/test_performance.py` section with institution and account tests. |
| 6 | LOW | `_match_account` uses case-sensitive comparison — IBKR IDs vary in case | Changed to case-insensitive exact match with `.lower()` normalization. |

### Review 11 (Codex) — FAIL, 1 HIGH / 2 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Normalizers live in `providers/normalizers/`, not `trading_analysis/normalizers/` — file list had wrong path | Fixed path to `providers/normalizers/{plaid,snaptrade,ibkr_flex,schwab}.py`. Updated description to reference actual analyzer wiring (`analyzer.py:143`). |
| 2 | MEDIUM | `get_all_positions()` has no `brokerage` param — plan said to pass institution to it | Changed to post-fetch filtering in tool code. `get_all_positions()` called with `consolidate=False`, then `match_institution()` and `_match_account()` applied to the result list. |
| 3 | MEDIUM | Test plan missing per-normalizer account metadata propagation tests | Added 4 per-normalizer tests in `tests/providers/normalizers/` validating `NormalizedTrade` carries `account_id`/`account_name`. |

### Review 12 (Codex) — FAIL, 2 HIGH

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Tax harvest says `consolidate=False` only "when `account` is set" but consolidation also drops `brokerage_name` needed for institution filtering | Made consolidation rule consistent everywhere: `consolidate=False` when `institution` OR `account` is set. Updated both the general rule and the tax harvest section to match. |
| 2 | HIGH | Account-aware dedup not in Phase 2 file list or test plan — dedup key (`analyzer.py:460`) lacks account identity | Added `trading_analysis/analyzer.py` to Phase 2 file list for dedup key change. Added 2 cross-account dedup regression tests to test plan. |

### Review 13 (Codex) — PASS, 2 LOW

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | LOW | No test for `institution` vs `brokerage` precedence on `get_positions` | Added `test_get_positions_institution_alias_precedence` and `test_get_positions_brokerage_backwards_compat` to test plan. |
| 2 | LOW | No end-to-end test for availability fallback (plaid/snaptrade + IBKR when ibkr_flex unavailable) | Added 3 availability fallback tests in `tests/trading_analysis/test_provider_routing.py` covering plaid+IBKR and snaptrade+IBKR with ibkr_flex available vs unavailable. |

### Review 14 (Codex) — PASS, 1 LOW

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | LOW | Ambiguous snaptrade+account matrix row ("if routing keeps it") | Clarified: empty when ibkr_flex available (IBKR routed away), data when unavailable (fallback). |

### Review 15 (Codex) — FAIL, 1 HIGH / 3 MEDIUM / 1 LOW

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Live baseline not deterministic — no cache control, no provider availability check, raw JSON comparison fragile | Added determinism controls: `use_cache=False` on all calls, compare return metrics only (not timestamps/metadata), require provider availability match between baseline and re-run. |
| 2 | MEDIUM | Live tests missing tax harvest baseline + scoped call | Added `suggest_tax_loss_harvest(source="all")` to baseline and `suggest_tax_loss_harvest(institution="charles_schwab")` to Phase 2 verification. |
| 3 | MEDIUM | Phase 3 item 1 Plaid expected-change rule missing availability fallback caveat | Added note: if ibkr_flex unavailable, Plaid IBKR rows survive as fallback — verify provider status matches baseline. |
| 4 | MEDIUM | Trading analysis live tests only cover source="all", not per-source partition impact | Added `get_trading_analysis(source="plaid")` and `get_trading_analysis(source="snaptrade")` to baseline + Phase 3 item 1 verification. |
| 5 | LOW | Failure criteria only check return metrics, not structural invariants for expected changes | Added structural checks: Phase 3 item 1 must show 0 IBKR-institution rows and >0 Merrill rows for source="plaid". Machine-checkable via institution field. |

### Review 16 (Codex) — FAIL, 1 HIGH / 2 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | `use_cache=False` missing on tax harvest and positions baseline calls despite determinism rule | Added `use_cache=False` to all baseline calls consistently. |
| 2 | MEDIUM | Failure criteria not machine-checkable for tax harvest subset and trading analysis stability | Expanded failure criteria: trading analysis checks trade count + symbol set; tax harvest checks candidate count + ticker set + strict subset for institution-scoped calls. |
| 3 | MEDIUM | Phase 3 item 1 doesn't explicitly assert `get_trading_analysis(source="all")` stability | Added `source="all"` trading analysis to Phase 3 item 1 verification list. |

### Review 17 (Codex) — FAIL, 2 MEDIUM / 1 LOW

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | MEDIUM | `use_cache=False` rule claimed universal but `get_trading_analysis` has no such param | Reworded: "tools that support `use_cache`" + noted tools without it are inherently fresh. |
| 2 | MEDIUM | Failure criteria missing positions and institution-scoped equivalence checks | Added positions stability (count + symbol set), institution-scoped equivalence (institution=X matches source=X baseline), and subset checks for account-scoped calls. |
| 3 | LOW | Phase-level checks used "return metrics" for non-return-metric tools (trading analysis) | Replaced with "domain metrics" throughout, defined per tool type in determinism controls. |

### Review 18 (Codex) — FAIL, 1 HIGH / 2 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Baseline calls use default format which doesn't expose required comparison fields (monthly_returns, symbol sets) | Added `format="full"` to all baseline and verification calls. |
| 2 | MEDIUM | Phase 2 new calls missing `use_cache=False` on tools that support it | Added `use_cache=False` to all Phase 2 verification calls for performance, positions, tax harvest. |
| 3 | MEDIUM | `get_trading_analysis(institution="interactive_brokers")` has no pass/fail criterion | Added to institution-scoped equivalence: trading analysis institution-scoped trades must be subset of source="all" IBKR-institution trades. |

### Review 19 (Codex) — FAIL, 1 MEDIUM

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | MEDIUM | Account-scoped performance "subset" undefined for return metrics | Clarified: symbol/ticker set must be subset; return metrics may differ (different account mix) but must be valid numbers (not NaN/null). |
