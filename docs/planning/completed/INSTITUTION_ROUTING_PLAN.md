# Plan: Unified Institution-Level Provider Routing

**Status:** COMPLETE
**Date:** 2026-02-16
**Tests:** 24 in `tests/providers/test_routing.py`

## Context
Multiple providers (Plaid, SnapTrade, Schwab direct, IBKR Flex) can connect to the same institution. When two providers pull data for the same institution, you get duplicate positions and transactions. Currently only Plaid transactions are filtered via `should_skip_plaid_institution()` — Plaid positions, SnapTrade positions, and SnapTrade transactions have NO filtering.

Goal: generalize the existing Plaid transaction filter into a unified, config-driven routing mechanism that works for ALL providers and BOTH positions and transactions. Centralize institution metadata resolution with canonical naming via existing `INSTITUTION_SLUG_ALIASES`.

## Approach
- Create `providers/routing.py` with generalized `should_skip_for_provider(institution_name, my_provider, data_type)` that is **context-aware**:
  - Checks if canonical provider is actually enabled/available before skipping
  - Distinguishes `data_type="transactions"` vs `data_type="positions"` — each has its own routing map so they can be configured independently
- Separate routing configs: `TRANSACTION_ROUTING` (existing, unchanged) + new `POSITION_ROUTING` for position-specific routing. Both are pure config — add/remove institutions as providers become available
- Inject routing checks into 4 unfiltered provider paths
- Keep `should_skip_plaid_institution()` as thin wrapper for backward compat

## Step 1: Create `providers/routing.py`

New file (~60 lines) with core routing logic:

- `resolve_institution_slug(institution_name) -> str | None` — normalize name, substring match against `INSTITUTION_SLUG_ALIASES`, return canonical slug
- `get_canonical_provider(institution_name, data_type="transactions") -> str | None` — resolve slug, look up the appropriate routing map (`TRANSACTION_ROUTING` for transactions, `POSITION_ROUTING` for positions)
- `should_skip_for_provider(institution_name, my_provider, data_type="transactions") -> bool` — returns True when:
  1. A canonical provider exists for this institution + data_type, AND
  2. The canonical provider is not `my_provider`, AND
  3. The canonical provider is actually enabled (check `SCHWAB_ENABLED`, `IBKR_FLEX_TOKEN`, etc.)

**Custom exception** for routing-specific empty:
```python
class EmptyAfterRoutingError(Exception):
    """All data for a provider was filtered out by institution routing."""
    pass
```

**Provider availability checks** (fail-open — prevents data loss when canonical provider is disabled):
```python
def _is_provider_available(provider: str) -> bool:
    """Check if a canonical provider is actually configured and usable.
    Reads env vars at call time (not import time) to avoid stale config."""
    import os
    if provider == "schwab":
        return os.getenv("SCHWAB_ENABLED", "false").lower() == "true"
    if provider == "ibkr_flex":
        return bool(os.getenv("IBKR_FLEX_TOKEN", "") and os.getenv("IBKR_FLEX_QUERY_ID", ""))
    return True  # Unknown providers assumed available
```

Reads env vars at call time (same pattern as `fetch_ibkr_flex_trades` at `data_fetcher.py:103`). If the canonical provider is NOT available, `should_skip_for_provider()` returns `False` (fail-open — keep the fallback data).

Reuses existing config: `INSTITUTION_SLUG_ALIASES` for alias resolution, routing maps for canonical provider lookup. Same substring matching logic as current `should_skip_plaid_institution()`.

## Step 2: Add `POSITION_ROUTING` to `settings.py` (after line 595)

Keep `TRANSACTION_ROUTING` unchanged. Add a new `POSITION_ROUTING` map:

```python
TRANSACTION_ROUTING = {
    "interactive_brokers": "ibkr_flex",
    "charles_schwab": "schwab",
}

# Position routing — add institutions here as direct position providers become available.
# Currently only Schwab has a direct position provider. IBKR can be added here once
# an IBKR position provider is wired up (e.g., via IBKRClient.fetch_positions()).
POSITION_ROUTING = {
    "charles_schwab": "schwab",
}
```

Routing is purely config-driven: an institution only gets filtered for a given data type if it appears in the corresponding map. Adding `"interactive_brokers": "ibkr"` to `POSITION_ROUTING` later requires zero code changes.

## Step 3: Delegate `should_skip_plaid_institution()` in `data_fetcher.py` (lines 16-44)

Replace body with one-line delegation:
```python
def should_skip_plaid_institution(institution_name: str) -> bool:
    from providers.routing import should_skip_for_provider
    return should_skip_for_provider(institution_name, "plaid", data_type="transactions")
```

All existing callers unchanged. Docstring kept for discoverability.

## Step 4: Update `providers/plaid_transactions.py`

Switch from `should_skip_plaid_institution` to `should_skip_for_provider(institution, "plaid", data_type="transactions")` directly. Minor import change.

## Step 5: Inject routing into `providers/snaptrade_positions.py`

After `fetch_snaptrade_holdings()` returns raw holdings list, filter by `brokerage_name` field (available on every holding dict from `snaptrade_loader.py:905`):
```python
filtered = [h for h in raw if not should_skip_for_provider(h.get("brokerage_name", ""), "snaptrade", data_type="positions")]
```
Warn once per skipped institution (collect unique names, warn after loop). Pass `filtered` to `normalize_snaptrade_holdings()`. If all rows filtered by routing, raise `EmptyAfterRoutingError("All SnapTrade positions filtered by routing")` — NOT ValueError (which means missing data/credentials).

## Step 6: Inject routing into `providers/snaptrade_transactions.py`

After `fetch_snaptrade_activities()` returns activities list, filter by `_brokerage_name` field (set at `data_fetcher.py:194`):
```python
filtered = [a for a in activities if not should_skip_for_provider(a.get("_brokerage_name", ""), "snaptrade", data_type="transactions")]
```

## Step 7: Inject routing into `providers/plaid_positions.py`

After `load_all_user_holdings()` returns DataFrame, guard for empty/missing columns, then filter by `institution` column (set at `plaid_loader.py:981`):
```python
if df is not None and not df.empty and "institution" in df.columns:
    pre_count = len(df)
    mask = df["institution"].apply(lambda inst: not should_skip_for_provider(str(inst), "plaid", data_type="positions"))
    df = df[mask].reset_index(drop=True)
    if df.empty and pre_count > 0:
        raise EmptyAfterRoutingError("All Plaid positions filtered by routing")
```
The `pre_count > 0` check distinguishes "had data but all routed away" from "genuinely no data" (which should still raise ValueError downstream).

## Step 8: Handle empty-after-filter in `services/position_service.py` (line 206)

Wrap the per-provider fetch in `get_all_positions()` (line 206-212) with try/except for `EmptyAfterRoutingError` only:
```python
from providers.routing import EmptyAfterRoutingError

for provider_name in self._position_providers:
    try:
        provider_results[provider_name] = self._get_positions_df(
            provider=provider_name,
            use_cache=use_cache,
            force_refresh=force_refresh,
            consolidate=False,
        )
    except EmptyAfterRoutingError as e:
        portfolio_logger.warning(f"⚠️ {provider_name} positions routed to another provider: {e}")
        provider_results[provider_name] = (pd.DataFrame(), False, None)
```

**Only catches `EmptyAfterRoutingError`** — a custom exception raised by provider position modules (Steps 5, 7) when routing filters all rows. Real errors are untouched:
- `ValueError` from `_normalize_columns` (schema issues) → propagates
- `ValueError` from `_fetch_fresh_positions` (genuinely empty) → propagates
- `ValueError` from SnapTrade (missing credentials) → propagates
- Auth failures, network errors, RuntimeError → propagates

**All-providers-empty behavior**: If every provider is routed away AND no provider has data, `pd.concat` produces empty DataFrame, `PositionResult.from_dataframe()` raises — same as current behavior.

**Single-provider fetch** (`get_positions(provider="snaptrade")`): No try/except — `EmptyAfterRoutingError` propagates directly (correct: explicit single-provider request that's empty is an error).

## Step 9: Update `tests/providers/test_transaction_providers.py`

Update monkeypatch target for Plaid skip: patch `providers.plaid_transactions.should_skip_for_provider` (the symbol as imported in the module under test, not at the source).

## Step 10: Update `tests/trading_analysis/test_provider_routing.py`

Existing tests call `should_skip_plaid_institution()` which now delegates to `should_skip_for_provider()`. The availability check reads env vars, so tests need to ensure `SCHWAB_ENABLED=true` and `IBKR_FLEX_TOKEN`/`IBKR_FLEX_QUERY_ID` are set in the test environment (via `monkeypatch.setenv`). Add a fixture or setup that sets these env vars so existing assertions remain stable.

## Step 11: Update `settings.py` comments

Update the block comment at line 577 ("Positions already route correctly") to reflect that `POSITION_ROUTING` now handles position-level routing.

## Step 12: Tests — `tests/providers/test_routing.py`

~24 tests:
- Core routing: each provider/institution combo (skip, don't skip, unrouted, empty, case-insensitive)
- `resolve_institution_slug()` and `get_canonical_provider()` directly
- **Data type routing**: IBKR skipped for transactions but NOT for positions
- **Provider availability**: Schwab disabled → SnapTrade NOT skipped for Schwab
- **Provider availability**: IBKR Flex unconfigured → Plaid NOT skipped for IBKR
- Backward compat: `should_skip_plaid_institution()` still works via delegation
- Provider integration: mock SnapTrade/Plaid fetchers, verify filtering works
- Empty DataFrame handling: Plaid positions filter with no `institution` column
- **PositionService resilience**: `EmptyAfterRoutingError` caught in `get_all_positions`, doesn't crash multi-provider fetch
- **Error discrimination regression**: `ValueError` from missing credentials / schema issues is NOT caught (propagates through `get_all_positions`)
- **Source-specific fetch**: `get_positions(provider="snaptrade")` when all positions routed → `EmptyAfterRoutingError` propagates

## Files to create
| File | Purpose | Lines (est) |
|------|---------|-------------|
| `providers/routing.py` | Core routing logic + provider availability checks | ~60 |
| `tests/providers/test_routing.py` | Routing + integration tests | ~200 |

## Files to modify
| File | Change |
|------|--------|
| `settings.py` | Add `POSITION_ROUTING` dict + update routing comments (line 577, 595) |
| `trading_analysis/data_fetcher.py` | Thin wrapper delegation (lines 16-44) |
| `providers/plaid_transactions.py` | Switch to `should_skip_for_provider` |
| `providers/snaptrade_positions.py` | Add routing filter on raw holdings (`data_type="positions"`) |
| `providers/snaptrade_transactions.py` | Add routing filter on activities (`data_type="transactions"`) |
| `providers/plaid_positions.py` | Add routing filter on DataFrame (`data_type="positions"`) |
| `services/position_service.py` | Wrap per-provider fetch in `get_all_positions` with `EmptyAfterRoutingError` catch (line 206) |
| `tests/providers/test_transaction_providers.py` | Update monkeypatch target for Plaid skip |
| `tests/trading_analysis/test_provider_routing.py` | Add env var setup for availability checks |

## Known Limitations (acceptable for v1)

1. **Cache bypass**: Routing filters only run on fresh fetches, not cached DB rows. This means duplicates persist until cache expires or `force_refresh=True`. Acceptable because:
   - Cache TTL is configurable (default 72h Plaid, 24h SnapTrade/Schwab)
   - Routing config changes (enabling Schwab) are rare, one-time events
   - User can force refresh via CLI/API to apply routing immediately
   - Fixing this would require filtering at the DB read layer, adding complexity for a rare edge case

2. **Stale DB rows for routed-away providers**: When `EmptyAfterRoutingError` is raised, `_save_positions_to_db()` is skipped, so old rows from the routed-away provider linger in DB. They can still be returned via the cached path until cache expires or `force_refresh=True`, after which routing filters take effect on the fresh fetch. A future cleanup could purge on routing change, but not needed for v1.

## Verification
1. `python3 -m pytest tests/providers/test_routing.py -v` — new routing tests
2. `python3 -m pytest tests/trading_analysis/test_provider_routing.py -v` — existing tests still pass
3. `python3 -m pytest tests/providers/test_transaction_providers.py -v` — monkeypatch still works
4. `python3 -m pytest tests/ -x -q` — full suite
5. With `SCHWAB_ENABLED=false`: verify SnapTrade does NOT skip Schwab (fallback preserved)
6. With `SCHWAB_ENABLED=true`: verify SnapTrade skips Schwab positions + transactions
