# Stale-Cache Position Repricing Fix

**Status:** DRAFT — Codex round 2
**Updated:** 2026-03-23
**Related:** `docs/planning/PERFORMANCE_REGRESSION_AUDIT_PLAN.md`

## Context

The March 22-23 performance regression audit introduced stale-tolerant position loading so startup-facing routes (`holdings`, `income`, `alerts`, `market-intelligence`, `realized-performance`) could return DB-cached positions immediately via `allow_stale_cache=True`. This was a major startup latency win (cold overview from 31s back to ~2s).

However, a repricing gap was introduced: positions loaded from stale DB cache return with `current_price: 0.0` and `value: 0.0`. This causes:
- Single-account `POST /api/analyze` → 500 error on cold path ("No valid return data, All 0 tickers excluded")
- All holdings show `current_price: 0.0` and `gross_exposure: 0.0` on the stale startup path
- Warm analyze/risk-score remain slow for single-account scope

## Root Cause

Two bugs in `services/position_service.py`:

### Bug 1: Metadata key mismatch in `_should_reprice_cached_provider()` (line 771)

The method only checks `metadata.get("stale_fallback")` (set on provider fetch failure, line 995). But the two startup-facing stale paths set different keys:
- `stale_forced_fallback` (line 950) — `allow_stale_cache=True` path
- `stale_grace_fallback` (line 934) — grace-window stale reads

Neither triggers repricing in the parent `get_all_positions()` merge path.

### Bug 2: Zero-value fallback guard only checks NaN (line 701)

The fallback at lines 695-705 checks `combined["value"].isna()`, but DB-cached positions have `value=0.0` (set by `_ensure_cached_columns` line 1870 when no price/value columns exist). `0.0` is not NaN, so the guard never fires.

## Fix

### Change 1: `_should_reprice_cached_provider()` — check all three stale metadata keys

**File:** `services/position_service.py`, line 771

```python
# Before:
if metadata.get("stale_fallback"):
    return True

# After:
if metadata.get("stale_fallback") or metadata.get("stale_forced_fallback") or metadata.get("stale_grace_fallback"):
    return True
```

### Change 2: Fallback guard catches zero-value cached positions with non-zero quantity

**File:** `services/position_service.py`, lines 695-705

The fallback block exists specifically for cached providers skipped by `_should_reprice_cached_provider`. Per Codex review feedback, the mask must be **scoped to cached-provider rows** not already handled by Fix 1 — otherwise it could reprice fresh provider rows or legitimate zero-value instruments (options/derivatives).

```python
# Before:
if reprice_cached_positions and not combined.empty:
    if "value" not in combined.columns:
        missing_mask = pd.Series(True, index=combined.index)
    else:
        missing_mask = combined["value"].isna()
    if missing_mask.any():
        repriced = self._calculate_market_values(combined.loc[missing_mask])
        for column in repriced.columns:
            combined.loc[missing_mask, column] = repriced[column]

# After:
if reprice_cached_positions and not combined.empty:
    if "value" not in combined.columns:
        missing_mask = pd.Series(True, index=combined.index)
    else:
        # Scope to cached-provider rows NOT already repriced by the provider-level pass above.
        # This catches DB-cached rows where value=0.0 (not NaN) due to _ensure_cached_columns
        # defaulting missing value/price columns to 0.0.
        all_cached_providers = {
            str(name).strip().lower()
            for name, (_, cached, _) in provider_results.items()
            if cached
        }
        already_repriced = cached_provider_names  # from the provider-level pass above
        unhandled_cached = all_cached_providers - already_repriced
        quantity_col = pd.to_numeric(combined.get("quantity"), errors="coerce").fillna(0.0)
        value_col = pd.to_numeric(combined["value"], errors="coerce").fillna(0.0)
        is_cached_row = (
            combined["position_source"].fillna("").astype(str).str.strip().str.lower().isin(unhandled_cached)
            if "position_source" in combined.columns and unhandled_cached
            else pd.Series(False, index=combined.index)
        )
        missing_mask = combined["value"].isna() | (is_cached_row & (value_col == 0.0) & (quantity_col.abs() > 0))
    if missing_mask.any():
        repriced = self._calculate_market_values(combined.loc[missing_mask])
        for column in repriced.columns:
            combined.loc[missing_mask, column] = repriced[column]
```

This catches:
- `value=NaN` on any row (original behavior)
- `value=0.0` with non-zero quantity on **cached-provider rows not already repriced** (the stale-cache bug)

It correctly skips:
- Fresh provider rows with legitimate zero values (options/derivatives)
- `quantity=0, value=0` (closed positions)
- Cached rows already repriced by the provider-level pass (Fix 1)

### Change 3: Tests

**File:** `tests/services/test_position_service_batch_pricing.py`

**Test A** — `test_should_reprice_cached_provider_triggers_on_all_stale_metadata_keys`:
Unit test: verify `_should_reprice_cached_provider()` returns `True` for each of `stale_fallback`, `stale_forced_fallback`, `stale_grace_fallback` with young cache (< 6h), confirming metadata alone triggers repricing.

**File:** `tests/services/test_position_service_provider_registry.py`

**Test B** — `test_get_all_positions_reprices_stale_forced_fallback_db_shaped_rows`:
Integration test through `get_all_positions()`. Setup: single provider, `_get_cache_freshness` returns stale (2h), `allow_stale_cache=True`. Mock `_load_cached_positions` to return DB-shaped DataFrame (ticker, quantity, currency, type — NO price/value/local_price/local_value columns, matching the real DB schema from `database_client.py:3637`). Mock `_calculate_market_values` to set price/value. Assert:
- `stale_forced_fallback` metadata is set
- `_calculate_market_values` was called (deferred repricing fired)
- Returned positions have non-zero value

**Test C** — `test_get_all_positions_reprices_stale_grace_fallback_db_shaped_rows`:
Same as Test B but using the grace-window path (stale_fallback_hours > hours_ago).

**Test D** — `test_fallback_guard_does_not_reprice_fresh_zero_value_rows`:
Regression test: two-provider setup — one fresh (from_cache=False) with a legitimate zero-value option row (qty=10, value=0.0), one stale cached. Assert that `_calculate_market_values` is NOT called for the fresh provider's rows.

**Test E** — `test_fallback_guard_catches_unhandled_cached_zero_value_rows`:
Edge case: single provider with recent cache (< 6h, no stale metadata), DB-shaped columns. Fix 1's provider-level pass skips this provider (not stale). Fix 2's scoped fallback should still catch the zero-value rows because the provider is cached but unhandled.

## Files Modified

| File | Change |
|------|--------|
| `services/position_service.py:771` | Add `stale_forced_fallback` and `stale_grace_fallback` checks |
| `services/position_service.py:695-705` | Scope zero-value fallback to cached-provider rows not already repriced |
| `tests/services/test_position_service_batch_pricing.py` | Add Test A |
| `tests/services/test_position_service_provider_registry.py` | Add Tests B, C, D, E |

## Performance Impact

None. Fix 1 adds two dict lookups (constant time). Fix 2's scoped fallback adds a set-difference and position_source isin check on an already-in-memory DataFrame, only when the provider-level pass didn't already handle the rows. After Fix 1, stale providers are repriced at the provider level (lines 687-693), so the fallback typically finds nothing to do.

## Codex Review History

### Round 1 — FAIL
- Fix 1: APPROVED
- Fix 2: REJECTED — fallback guard was global, could reprice fresh rows and legitimate zero-value instruments
- Tests: INSUFFICIENT — needed integration-style `get_all_positions()` tests with DB-shaped columns, regression test for fresh zero-value rows

### Round 2 — changes made
- Fix 2: Scoped to `unhandled_cached` provider rows (cached minus already-repriced)
- Tests: Added 4 integration tests (B-E) covering stale-forced, stale-grace, fresh zero-value regression, and unhandled-cached fallback

## Verification

1. `python3 -m pytest tests/services/test_position_service_batch_pricing.py tests/services/test_position_service_provider_registry.py -q` — all new + existing tests pass
2. Restart backend, clear cache, run the measurement script: `python3 scripts/perf_measurement.py`
   - Single-account analyze should return 200 with ~60KB (not 500/0.3KB)
   - Holdings should show non-zero `current_price` and `gross_exposure`
3. Confirm warm path latency is not regressed vs the numbers we just measured
