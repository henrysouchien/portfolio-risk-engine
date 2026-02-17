# Provider Router Refactor

**Status**: COMPLETE (2026-02-16)

## Context

The current provider system uses a **filter pattern**: every enabled provider fetches all its data, then each non-canonical provider drops records belonging to other providers via `should_skip_for_provider()`. This means we fetch data we know we'll throw away, and the filter logic is scattered across 4 provider files plus `data_fetcher.py` (mid-fetch Plaid filter at line ~263).

We want a **router pattern**: config declares which provider handles each institution (for positions and transactions independently). The system only calls the providers it needs, and a central router partitions aggregator results (Plaid/SnapTrade serve multiple institutions) instead of each provider filtering itself.

**Important constraint**: Aggregator providers (Plaid, SnapTrade) fetch all institutions at once — they can't fetch per-institution. So the router still needs to partition their results after fetch. The key change is that this happens centrally in the router, not scattered across each provider.

## Config Changes (`settings.py`)

Add default provider settings. Existing routing tables stay the same shape:

```python
# Existing (unchanged)
POSITION_ROUTING = {"charles_schwab": "schwab"}
TRANSACTION_ROUTING = {"interactive_brokers": "ibkr_flex", "charles_schwab": "schwab"}

# New: fallback for institutions not in routing tables
# This is a LIST — all listed providers are called for unrouted institutions.
# This avoids data loss when institutions only exist in one aggregator.
_raw = os.getenv("DEFAULT_POSITION_PROVIDERS", "snaptrade,plaid")
DEFAULT_POSITION_PROVIDERS = [p.strip().lower() for p in _raw.split(",") if p.strip()]

_raw = os.getenv("DEFAULT_TRANSACTION_PROVIDERS", "snaptrade,plaid")
DEFAULT_TRANSACTION_PROVIDERS = [p.strip().lower() for p in _raw.split(",") if p.strip()]
```

**Rationale for list (not single)**: If default is only `snaptrade`, Plaid-only institutions disappear. Both aggregators must remain active for unrouted institutions to avoid silent data loss.

**Env parsing**: Strip whitespace and lowercase to handle `"snaptrade, plaid"` etc. Empty tokens filtered out.

## Edge Cases & Safety

### Empty/missing institution names
Records with empty or unresolvable institution names are **always kept** by the partition step — they pass through to whichever provider fetched them. This preserves the current fail-open behavior.

### Default provider validation
Validate inside `get_required_providers()` (not at startup — registries are lazily constructed):
- Position defaults must be in `ALL_PROVIDERS`, enabled, AND be a known position-capable provider (`plaid`, `snaptrade`, `schwab`)
- Transaction defaults must be in `ALL_PROVIDERS`, enabled, AND be a known transaction-capable provider (`plaid`, `snaptrade`, `ibkr_flex`, `schwab`)
- Log a warning (not error) for invalid defaults — fail-open by including all enabled providers of the correct type

### DI/custom registries
When `get_all_positions()` or `fetch_all_transactions()` receives a custom registry (tests, DI), **skip the `get_required_providers()` gate entirely** — call all registered providers. The routing gate only applies to the default registry path.

### Canonical providers for unconnected institutions
`get_required_providers()` includes all canonical providers from the routing table. If a user doesn't have an IBKR account, the IBKR provider simply returns empty data (already handled). No special case needed.

## Implementation

### Step 1: Add router functions to `providers/routing.py`

New functions (positive routing logic):

- **`get_required_providers(data_type)`** — Returns set of providers needed: all canonical providers from the routing table (that are available) + all default providers (that are available). Falls back to all enabled providers if no routing config exists.

- **`institution_belongs_to_provider(institution_name, provider, data_type)`** — Returns True if this institution's data should come from this provider. Logic:
  1. Empty/unresolvable institution → always True (keep the data)
  2. Resolve slug → lookup routing table
  3. If routed: return `canonical == provider`; unless canonical unavailable, then return `provider in defaults` (fail-open)
  4. If not routed: return `provider in defaults`

- **`partition_positions(df, provider)`** — Filters a positions DataFrame to only rows where `institution_belongs_to_provider()` is True. Uses `institution` or `brokerage_name` column. Returns filtered DataFrame (empty rows with missing institution are always kept).

- **`partition_transactions(records, provider, institution_field)`** — Filters a transaction list to only records belonging to this provider. Records with empty institution field are always kept.

Deprecate `should_skip_for_provider()` (keep as wrapper → `not institution_belongs_to_provider()`).
Deprecate `EmptyAfterRoutingError` (no longer raised).

### Step 2: Update `services/position_service.py` — `get_all_positions()`

Replace the current loop-all-and-catch pattern (lines 200-220):

```python
from providers.routing import get_required_providers, partition_positions

needed = get_required_providers("positions")
for provider_name in self._position_providers:
    if provider_name not in needed:
        continue
    df, from_cache, cache_age = self._get_positions_df(...)
    df = partition_positions(df, provider_name)
    provider_results[provider_name] = (df, from_cache, cache_age)
```

**DI safety**: If `self._position_providers` was injected with custom providers (not default), skip the `needed` gate — call all of them. Detect this by checking if the registry was built from defaults or injected.

**Provider-scoped paths**: `get_positions(provider=...)` and `refresh_provider_positions()` also need partition applied. These are single-provider fetches that currently rely on provider-internal filters. After filter removal, add `partition_positions()` call after fetch in these paths too. **Important**: partition must happen BEFORE any consolidation step (`_consolidate_cross_provider`) to preserve institution fidelity. Also check `routes/plaid.py` and `routes/snaptrade.py` for direct provider calls.

**CLI wrappers**: `run_positions.py` uses `fetch_plaid_positions()` / `fetch_snaptrade_positions()` / `fetch_schwab_positions()` which bypass `get_positions(provider=...)`. These need partition applied too, or should be routed through `get_positions(provider=...)` instead.

Remove `EmptyAfterRoutingError` import and catch block.

### Step 3: Update `trading_analysis/data_fetcher.py`

**`fetch_all_transactions()`** — Add partition step after each provider fetch:

```python
from providers.routing import get_required_providers, partition_transactions

needed = get_required_providers("transactions")
for name, provider in registry.get_transaction_providers().items():
    if registry_is_default and name not in needed:
        continue
    provider_payload = provider.fetch_transactions(user_email=user_email)
    _partition_provider_payload(provider_payload, name)  # new helper
    _merge_payloads(payload, provider_payload)
```

**DI safety**: When `registry` parameter is explicitly passed (not None), skip the `needed` gate — the caller controls which providers run.

Add `_partition_provider_payload()` helper that knows the institution field for each payload key:
- `plaid_transactions` → field `_institution`
- `snaptrade_activities` → field `_brokerage_name`
- `ibkr_flex_trades`, `schwab_transactions` → skip (canonical, no partition needed)
- Unknown keys → skip (don't partition, preserve data)

**`fetch_plaid_transactions()`** — Remove the `should_skip_plaid_institution()` filter at line ~263.

**`fetch_transactions_for_source()`** — No change needed. When user explicitly picks a source, they get everything from that provider (no partition).

### Step 4: Strip filter logic from 4 provider files

| File | Remove |
|------|--------|
| `providers/plaid_positions.py` | `should_skip_for_provider` block + `EmptyAfterRoutingError` (lines 24-35) |
| `providers/snaptrade_positions.py` | `should_skip_for_provider` block + `EmptyAfterRoutingError` (lines 30-46) |
| `providers/plaid_transactions.py` | `should_skip_for_provider` filter loop (line 24) |
| `providers/snaptrade_transactions.py` | `should_skip_for_provider` filter (lines 24-28) |

Each provider becomes a clean fetcher — fetch everything, return everything.

### Step 5: Tests

**Update `tests/providers/test_routing.py`:**
- Test `institution_belongs_to_provider()` — routed, unrouted, fail-open, empty institution
- Test `get_required_providers()` — returns correct set based on config, includes all defaults
- Test `partition_positions()` / `partition_transactions()` — correct filtering, empty institution preserved
- Test deprecated `should_skip_for_provider()` still works
- Test default provider validation — invalid defaults log warning, fall back to all enabled
- Test with no routing config at all — all enabled providers are required

**Update `tests/providers/test_transaction_providers.py`:**
- Verify providers no longer filter internally

**Update `tests/providers/test_provider_switching.py`:**
- Update assertions for new routing semantics

**Update `tests/trading_analysis/test_provider_routing.py`:**
- Update for centralized partition behavior

**Update `tests/services/test_position_service_provider_registry.py`:**
- Verify DI/custom registries bypass the `needed` gate

**New tests:**
- `source="all"` path through `fetch_transactions_for_source()` after central partitioning
- DI/custom registry with arbitrary provider names still works
- `get_positions(provider=..., consolidate=True/False)` — partition before consolidation
- `refresh_provider_positions()` — routing applied correctly
- CLI source-specific path via `run_positions.py` — no routed-away rows leak

## Files Modified

| File | Change |
|------|--------|
| `settings.py` | Add `DEFAULT_POSITION_PROVIDERS`, `DEFAULT_TRANSACTION_PROVIDERS` |
| `providers/routing.py` | Add router functions, deprecate filter functions |
| `services/position_service.py` | Router dispatch in `get_all_positions()` |
| `trading_analysis/data_fetcher.py` | Centralized partition in `fetch_all_transactions()`, remove mid-fetch filter |
| `providers/plaid_positions.py` | Remove filter (~12 lines) |
| `providers/snaptrade_positions.py` | Remove filter (~17 lines) |
| `providers/plaid_transactions.py` | Remove filter (~4 lines) |
| `providers/snaptrade_transactions.py` | Remove filter (~6 lines) |
| `tests/providers/test_routing.py` | New router tests + update existing |
| `tests/providers/test_transaction_providers.py` | Update for no internal filtering |
| `tests/providers/test_provider_switching.py` | Update for new routing semantics |
| `tests/trading_analysis/test_provider_routing.py` | Update for centralized partition |
| `tests/services/test_position_service_provider_registry.py` | Verify DI bypass |
| `trading_analysis/README.md` | Update routing narrative (remove `should_skip_plaid_institution` references) |
| `routes/plaid.py` | Add partition to provider-scoped position fetch/refresh paths |
| `routes/snaptrade.py` | Add partition to provider-scoped position fetch/refresh paths |
| `run_positions.py` | Route CLI wrappers through partitioned path |

## What Doesn't Change

- Provider interfaces (`providers/interfaces.py`)
- `ProviderRegistry` (`providers/registry.py`)
- Schwab/IBKR provider implementations (already canonical, no filters)
- `is_provider_enabled()` / `is_provider_available()` — unchanged
- `INSTITUTION_SLUG_ALIASES` — unchanged
- Cache logic in `position_service.py`
- `core/realized_performance_analysis.py` — calls `fetch_transactions_for_source()` which is unchanged
- `mcp_tools/trading_analysis.py` — calls `fetch_transactions_for_source()` which is unchanged

## Verification

1. Run routing tests: `python -m pytest tests/providers/test_routing.py -v`
2. Run all provider tests: `python -m pytest tests/providers/ -v`
3. Run position service tests: `python -m pytest tests/services/test_position_service_provider_registry.py -v`
4. Run trading analysis routing tests: `python -m pytest tests/trading_analysis/test_provider_routing.py -v`
5. Run full test suite: `python -m pytest tests/ -v`
6. Manual: With `SCHWAB_ENABLED=true`, verify `fetch_all_transactions()` calls schwab + ibkr_flex + default providers (not just one default)

## Codex Review

### Round 1 — Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Single default provider loses data for institutions only in one aggregator | Changed to `DEFAULT_*_PROVIDERS` (list), both aggregators active by default |
| 2 | HIGH | No validation that default provider is compatible with data type | Added validation section — log warning, fail-open to all enabled |
| 3 | HIGH | `get_required_providers()` gate breaks DI/custom registries in tests | Added DI safety — skip gate when registry is injected |
| 4 | MED | Empty/missing institution names could be dropped by partition | Partition always keeps records with empty institution |
| 5 | MED | Context section missed `data_fetcher.py:263` mid-fetch filter | Fixed in context description |
| 6 | MED | Still calls canonical providers for users without those institutions | Documented as acceptable — provider returns empty, already handled |
| 7 | MED | Missing test files from plan | Added all test files to modification table |
| 8 | MED | Test plan inadequate for new risk profile | Expanded with misconfig, empty institution, DI, source="all" tests |
| 9 | LOW | Manual verification step inaccurate | Fixed to include all canonical providers |
| 10 | LOW | Deprecation scope larger than listed | Covered by expanded test file list |

### Round 2 — Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | MED | Provider-scoped paths (`get_positions(provider=...)`, `refresh_provider_positions()`) bypass partitioning | Added partition call to provider-scoped paths in Step 2; added `routes/plaid.py` and `routes/snaptrade.py` to files list |
| 2 | MED | `routes/plaid.py` and `routes/snaptrade.py` not in plan | Added to files modified table |
| 3 | LOW | "Validate at startup" is underspecified — registries are lazily constructed | Moved validation into `get_required_providers()` |
| 4 | LOW | Env list parsing fragile — `.split(",")` doesn't strip whitespace/case | Fixed parsing to strip + lowercase + filter empty tokens |
| 5 | LOW | `trading_analysis/README.md` still references old routing narrative | Added to files modified table |

### Round 3 — Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | MED | Validation checks `ALL_PROVIDERS` but not data-type compatibility (e.g., `ibkr_flex` isn't a position provider) | Added data-type-aware validation: position defaults must be position-capable, transaction defaults must be transaction-capable |
| 2 | MED | Partition after consolidation loses institution fidelity | Explicitly require partition BEFORE consolidation in provider-scoped paths |
| 3 | LOW | `run_positions.py` CLI wrappers bypass `get_positions()` — routed-away rows could leak | Added `run_positions.py` to files list, noted CLI wrappers need partition or rerouting |
| 4 | LOW | Test plan missing provider-scoped and CLI path coverage | Added tests for `get_positions(provider=..., consolidate=True/False)`, `refresh_provider_positions()`, CLI paths |
