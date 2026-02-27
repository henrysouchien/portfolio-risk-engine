# Provider Normalization: Stop Redundant Plaid IBKR Transactions

## Context

Transactions are currently fetched from ALL providers blindly (`fetch_all_transactions()` calls all 3 sources). This means IBKR trades appear from both Plaid AND IBKR Flex, creating redundant data. The dedup in `TradingAnalyzer._deduplicate_transactions()` catches exact matches, but raw Plaid ticker variants (e.g., `AT.` vs `AT.L`) still leak through.

Now that positions have been migrated from Plaid to SnapTrade for all accounts except Merrill (which SnapTrade doesn't support), transactions should follow the same routing: **skip Plaid transactions for IBKR-connected accounts** since IBKR Flex provides better data (multipliers, asset categories, open/close indicators, futures support).

**Goal**: Filter Plaid IBKR transactions at fetch time so they never enter the pipeline. Also consolidate the duplicated `_fetch_transactions_for_source()` function.

## Files to Modify

1. `settings.py` — Add `TRANSACTION_ROUTING` config + `INSTITUTION_SLUG_ALIASES`
2. `trading_analysis/data_fetcher.py` — Add institution filtering + consolidate `_fetch_transactions_for_source()`
3. `core/realized_performance_analysis.py` — Remove duplicated `_fetch_transactions_for_source()`, import from data_fetcher, clean up unused imports
4. `mcp_tools/tax_harvest.py` — Remove duplicated `_fetch_transactions_for_source()`, import from data_fetcher, clean up unused imports
5. `run_trading_analysis.py` — Replace inline source-switch logic with `fetch_transactions_for_source()`
6. `tests/core/test_realized_performance_analysis.py` — Update monkeypatches from `_fetch_transactions_for_source` to `fetch_transactions_for_source`
7. `tests/trading_analysis/test_provider_routing.py` — New test file for routing logic

## Changes

### 1. Add routing config to `settings.py`

Add after `INSTITUTION_PROVIDER_MAPPING` (line ~561):

```python
# ═══════════════════════════════════════════════════════════════════════════════
# 📊 TRANSACTION PROVIDER ROUTING
# ═══════════════════════════════════════════════════════════════════════════════
#
# Controls which provider supplies TRANSACTIONS for each institution.
# Positions already route correctly (each provider only returns its own
# institutions' positions). Transactions need explicit routing because
# Plaid returns transactions for accounts that are also connected via
# other providers (IBKR Flex, SnapTrade).
#
# When an institution is listed here with a canonical transaction provider,
# Plaid transactions tagged with that institution's name are SKIPPED
# (filtered out at fetch time). This prevents:
# - Redundant duplicate data (Plaid IBKR + IBKR Flex)
# - Raw ticker variant leaks (Plaid AT. vs FMP AT.L)
# - Dedup overhead on known-redundant data
#
# Institutions NOT listed here: Plaid transactions pass through unchanged.

TRANSACTION_ROUTING = {
    # institution_slug → canonical transaction provider
    # When canonical != "plaid", Plaid transactions for this institution are skipped
    "interactive_brokers": "ibkr_flex",
}

# Maps various provider institution name strings to canonical slugs.
# Plaid institution names come from AWS secret path: split("/")[-1].replace("-"," ").title()
# Uses substring matching (case-insensitive): if any alias appears as a substring
# of the institution name, it maps to that slug. This mirrors the existing
# _IBKR_INSTITUTION_NAMES pattern in trading_analysis/analyzer.py:43.
INSTITUTION_SLUG_ALIASES = {
    "interactive brokers":   "interactive_brokers",
    "ibkr":                  "interactive_brokers",
}
```

### 2. Filter Plaid transactions + consolidate fetch helper in `data_fetcher.py`

**Change A** — Add `should_skip_plaid_institution()` helper function (after imports):

```python
def should_skip_plaid_institution(institution_name: str) -> bool:
    """Check if Plaid transactions for this institution should be skipped.

    Returns True when another provider (e.g., IBKR Flex) is the canonical
    transaction source for this institution.

    Uses substring matching to handle variants like "Interactive Brokers LLC",
    "Interactive Brokers - Individual", etc.
    """
    from settings import TRANSACTION_ROUTING, INSTITUTION_SLUG_ALIASES

    # Normalize: lowercase, strip, replace underscores with spaces
    # (AWS secret paths use hyphens→spaces, but guard against underscores too)
    name_lower = institution_name.lower().strip().replace("_", " ")
    if not name_lower:
        return False

    # Substring match — mirrors _IBKR_INSTITUTION_NAMES pattern in analyzer.py
    slug = None
    for alias, alias_slug in INSTITUTION_SLUG_ALIASES.items():
        if alias in name_lower:
            slug = alias_slug
            break

    if not slug:
        return False

    canonical = TRANSACTION_ROUTING.get(slug)
    return canonical is not None and canonical != "plaid"
```

**Change B** — Add filtering inside `fetch_plaid_transactions()`. Replace the current block at lines 169-171:

```python
# BEFORE (lines 169-171):
for tx in transactions:
    tx['_institution'] = institution
all_transactions.extend(transactions)

# AFTER:
for tx in transactions:
    tx['_institution'] = institution
    if should_skip_plaid_institution(institution):
        continue  # Skip — another provider is canonical for this institution
    all_transactions.append(tx)
```

Note: the `should_skip_plaid_institution()` check is inside the per-tx loop but the result is the same for all txns from one institution. This is fine — the function is a simple dict lookup with no I/O. Moving it outside the loop is a micro-optimization that doesn't matter for the small transaction counts involved.

**Change C** — Add `fetch_transactions_for_source()` as a public function at the bottom of `data_fetcher.py`:

```python
def fetch_transactions_for_source(user_email: str, source: str) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch provider transactions for requested source scope."""
    source = source.lower().strip()
    if source == "all":
        return fetch_all_transactions(user_email)
    if source == "snaptrade":
        return {"snaptrade_activities": fetch_snaptrade_activities(user_email=user_email),
                "plaid_transactions": [], "plaid_securities": [], "ibkr_flex_trades": []}
    if source == "plaid":
        plaid_payload = fetch_plaid_transactions(user_email=user_email)
        return {"snaptrade_activities": [],
                "plaid_transactions": plaid_payload.get("transactions", []),
                "plaid_securities": plaid_payload.get("securities", []),
                "ibkr_flex_trades": []}
    if source == "ibkr_flex":
        return {"snaptrade_activities": [], "plaid_transactions": [],
                "plaid_securities": [], "ibkr_flex_trades": fetch_ibkr_flex_trades()}
    raise ValueError("source must be one of: all, snaptrade, plaid, ibkr_flex")
```

### 3. Update `core/realized_performance_analysis.py`

**Delete** the duplicated `_fetch_transactions_for_source()` function (lines 566–603).

**Update imports** (lines 23–28) — replace individual fetch imports with consolidated helper:
```python
# BEFORE:
from trading_analysis.data_fetcher import (
    fetch_all_transactions,
    fetch_ibkr_flex_trades,
    fetch_plaid_transactions,
    fetch_snaptrade_activities,
)

# AFTER:
from trading_analysis.data_fetcher import fetch_transactions_for_source
```

**Update caller** — replace `_fetch_transactions_for_source(` with `fetch_transactions_for_source(`.

### 4. Update `mcp_tools/tax_harvest.py`

**Delete** the duplicated `_fetch_transactions_for_source()` function (lines 111–148).

**Update imports** — replace individual fetch imports with consolidated helper:
```python
# BEFORE:
from trading_analysis.data_fetcher import (
    fetch_all_transactions,
    fetch_ibkr_flex_trades,
    fetch_plaid_transactions,
    fetch_snaptrade_activities,
)

# AFTER:
from trading_analysis.data_fetcher import fetch_transactions_for_source
```

**Update caller** — `_load_fifo_data()` (line 151) calls `_fetch_transactions_for_source()` — change to `fetch_transactions_for_source()`.

### 5. Update `run_trading_analysis.py`

Replace the inline source-switch block (lines 482–506) with the consolidated helper:

```python
# BEFORE (lines 482-506): inline if/elif/else with 4 branches

# AFTER:
from trading_analysis.data_fetcher import fetch_transactions_for_source
data = fetch_transactions_for_source(user_email=user_email, source=args.source)
```

Also remove the now-unused individual fetch imports from lines 19–24.

### 6. Update test monkeypatches in `tests/core/test_realized_performance_analysis.py`

The existing tests monkeypatch `rpa._fetch_transactions_for_source` at 5 locations (lines 88, 409, 636, 755, 881). After the refactor, the function is imported into `rpa` as `fetch_transactions_for_source`. Update all patches:

```python
# BEFORE:
monkeypatch.setattr(rpa, "_fetch_transactions_for_source", ...)

# AFTER:
monkeypatch.setattr(rpa, "fetch_transactions_for_source", ...)
```

### 7. Tests

**New file**: `tests/trading_analysis/test_provider_routing.py`

```python
# Test should_skip_plaid_institution()
1. test_skip_ibkr_exact — "Interactive Brokers" → True
2. test_skip_ibkr_case_insensitive — "interactive brokers" → True
3. test_skip_ibkr_substring — "Interactive Brokers LLC" → True (substring match)
4. test_skip_ibkr_alias — "IBKR" → True
5. test_keep_merrill — "Merrill Lynch" → False (not in routing config)
6. test_keep_unknown — "Some New Broker" → False
7. test_keep_empty — "" → False

# Integration test: fetch_plaid_transactions filtering
8. test_plaid_ibkr_transactions_filtered — mock Plaid API, verify IBKR txns dropped, Merrill txns kept

# Consolidated helper branch tests
9. test_fetch_transactions_for_source_all — verify source="all" dispatches to fetch_all_transactions
10. test_fetch_transactions_for_source_snaptrade — verify source="snaptrade" returns only snaptrade data
11. test_fetch_transactions_for_source_plaid — verify source="plaid" returns only plaid data
12. test_fetch_transactions_for_source_ibkr_flex — verify source="ibkr_flex" returns only flex data
13. test_fetch_transactions_for_source_invalid — verify invalid source raises ValueError
```

## Verification

1. Run routing tests: `python3 -m pytest tests/trading_analysis/test_provider_routing.py -v`
2. Run existing dedup tests (should still pass): `python3 -m pytest tests/services/test_ibkr_flex_client.py -v`
3. Run realized performance tests: `python3 -m pytest tests/core/test_realized_performance_analysis.py -v`
4. Restart MCP server, call `get_performance(mode="realized", format="summary")`:
   - Verify `source_breakdown` no longer shows Plaid IBKR transactions
   - Verify `AT.` ticker warnings disappear (only `AT.L` remains from SnapTrade/consolidated positions)
   - Verify Merrill Lynch transactions still appear
5. Call `suggest_tax_loss_harvest()` — verify it still works (uses consolidated `fetch_transactions_for_source`)

## Edge Cases

- **Merrill Lynch**: NOT in `TRANSACTION_ROUTING` → Plaid transactions pass through unchanged. This is correct since Plaid is the only source for Merrill.
- **New institutions**: Any institution not matching `INSTITUTION_SLUG_ALIASES` substrings passes through unchanged. Safe default — only explicitly-routed institutions are filtered.
- **IBKR institution name variants**: Substring matching handles "Interactive Brokers LLC", "Interactive Brokers - Individual", etc. — any string containing "interactive brokers" or "ibkr" (case-insensitive) will match. This mirrors the existing `_IBKR_INSTITUTION_NAMES` pattern in `analyzer.py:43`.
- **No IBKR Flex credentials**: If IBKR Flex token/query_id not set, `fetch_ibkr_flex_trades()` returns `[]`. Plaid IBKR transactions are still filtered out (the routing config is about canonical provider, not availability). This is intentional — if IBKR Flex isn't configured, we'd rather have no IBKR transactions than incorrect Plaid ones with raw ticker variants.
- **Dedup still runs**: The existing `_deduplicate_transactions()` in `TradingAnalyzer` remains as a safety net. After this change it should be a no-op for IBKR (no Plaid IBKR transactions to dedup), but it still handles any other cross-provider overlaps.
