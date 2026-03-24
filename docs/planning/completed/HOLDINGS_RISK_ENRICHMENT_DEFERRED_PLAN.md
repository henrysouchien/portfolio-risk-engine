# Holdings Risk Enrichment — Non-Blocking Exact-Key Cache Hit

**Status:** DRAFT — Codex round 4
**Updated:** 2026-03-23
**Related:** `docs/planning/PERFORMANCE_REGRESSION_AUDIT_PLAN.md`

## Context

Cold `GET /api/positions/holdings` takes **5-10s** because `enrich_positions_with_risk` blocks on `risk_future.result()` which joins the prewarm's shared analysis computation. The cost is **waiting**, not duplicate work.

Risk enrichment fields (`risk_score`, `beta`, `risk_pct`, `max_drawdown`) are supplementary but should appear when the analysis result is available.

## Blockers Identified by Codex (Rounds 1-3)

1. `with ThreadPoolExecutor(...)` blocks on `__exit__` — timeout on `.result()` doesn't help
2. `enrich_positions_with_risk()` re-blocks when `prefetched_risk_result=None` — falls back to sync `get_positions_risk_result()`
3. Prefix-matching cache peek is unsafe — multiple entries can match
4. Permanently skipping `enrich_positions_with_risk` means risk fields never appear, even after prewarm completes
5. Holdings payload shape changes if `enrich_positions_with_risk` is never called (`risk_score`/`beta`/`risk_pct`/`max_drawdown` keys missing entirely vs present-but-null)

**Codex guidance**: "The holdings path needs a non-blocking exact-cache-hit risk merge path, not permanent removal."

## Fix: Non-Blocking Exact-Key Risk Enrichment

Keep `enrich_positions_with_risk` in the holdings path. Remove the `ThreadPoolExecutor` and `risk_future`. Instead, do an exact-key synchronous cache check (no `.result()` wait, no futures) via `get_positions_risk_result` refactored to support a `non_blocking` mode.

### Change 1: `services/portfolio_service.py` — Add `non_blocking` parameter to `get_positions_risk_result`

```python
def get_positions_risk_result(
    self,
    result: PositionResult | None,
    portfolio_name: str,
    user_id: int,
    *,
    requested_portfolio_name: Optional[str] = None,
    allow_gpt: bool = False,
    non_blocking: bool = False,
) -> Any:
```

When `non_blocking=True`:
- Build the same exact cache key as the normal path (same `get_portfolio_snapshot`, `get_factor_proxies_snapshot`, `get_risk_limits_snapshot`, same `refresh_cache_key`)
- Instead of calling `get_analysis_result_snapshot()` (which blocks via `_get_or_build`), call a new `peek_analysis_result_snapshot()` that only checks the TTL cache (no builder, no in-flight join)
- Return `None` if the cache doesn't have the result yet

The key is **exact-key** — same key derivation as the blocking path, just a cache-only lookup.

### Change 2: `services/portfolio/result_cache.py` — Add `peek_analysis_result_snapshot()`

```python
def peek_analysis_result_snapshot(
    *,
    user_id: int,
    portfolio_name: str,
    portfolio_data: Any,
    risk_limits_data: Any,
    performance_period: str,
) -> Any | None:
    """Return the cached analysis result if available, else None. Never blocks."""
    cache_key = (
        f"{user_id}:{portfolio_name}:{str(performance_period).upper()}:"
        f"{_cache_key_for(portfolio_data, fallback='portfolio')}:"
        f"{_cache_key_for(risk_limits_data, fallback='risk-limits')}"
    )
    with _cache_lock:
        value = _analysis_cache.get(cache_key)
        if value is not None:
            return _clone(value)
    return None
```

This is exact-key, no prefix matching, no futures, no timeout. It returns the cached result if the prewarm has already finished and populated the cache, or `None` if not.

### Change 3: `routes/positions.py` — Replace ThreadPoolExecutor with non-blocking call

**Current** (lines 412-489):
```python
with ThreadPoolExecutor(max_workers=1) as executor:
    risk_future = executor.submit(portfolio_svc.get_positions_risk_result, ...)
    # ... position loading, enrichment ...
    prefetched_risk_result = risk_future.result()  # BLOCKS
    portfolio_svc.enrich_positions_with_risk(..., prefetched_risk_result=prefetched_risk_result)
```

**After**:
```python
# No ThreadPoolExecutor, no risk_future
# ... position loading, enrichment (same as before) ...

with timing.step("enrich_positions_with_risk"):
    try:
        prefetched_risk_result = portfolio_svc.get_positions_risk_result(
            None,
            scope.config_portfolio_name,
            int(user["user_id"]),
            requested_portfolio_name=normalized_requested_portfolio_name,
            allow_gpt=allow_gpt,
            non_blocking=True,  # NEW: returns None if not cached
        )
        portfolio_svc.enrich_positions_with_risk(
            result,
            payload,
            scope.config_portfolio_name,
            user["user_id"],
            requested_portfolio_name=portfolio_name,
            prefetched_risk_result=prefetched_risk_result,
            allow_gpt=allow_gpt,
        )
    except Exception:
        pass
```

When `prefetched_risk_result` is not `None` (analysis cached): full risk enrichment, all fields populated.
When `prefetched_risk_result` is `None` (analysis not ready): `enrich_positions_with_risk` initializes `risk_score`/`beta`/`risk_pct`/`max_drawdown` to `None` at line 1304-1308, then returns early at line 1319-1320 (`if risk_result is None: return`). Response shape preserved (keys present but null).

**CRITICAL**: We must also prevent `enrich_positions_with_risk` from re-blocking when `prefetched_risk_result=None`. Currently line 1310-1318 falls back to sync `get_positions_risk_result()`. Fix: add a `skip_fallback: bool = False` parameter to `enrich_positions_with_risk`. When `True`, skip the fallback and just return after initializing fields to `None`.

### Change 4: `services/portfolio_service.py` — Add `skip_fallback` to `enrich_positions_with_risk`

```python
def enrich_positions_with_risk(
    self,
    result: PositionResult,
    payload: Dict[str, Any],
    portfolio_name: str,
    user_id: int,
    *,
    requested_portfolio_name: Optional[str] = None,
    prefetched_risk_result: Any = None,
    allow_gpt: bool = False,
    skip_fallback: bool = False,
) -> None:
```

At line 1310-1318, change:
```python
risk_result = prefetched_risk_result
if risk_result is None:
    risk_result = self.get_positions_risk_result(...)  # BLOCKING FALLBACK
```
To:
```python
risk_result = prefetched_risk_result
if risk_result is None and not skip_fallback:
    risk_result = self.get_positions_risk_result(...)
```

Holdings route passes `skip_fallback=True`. Export route continues with default `skip_fallback=False`.

### Change 5: `_holdings_cache` invalidation when analysis arrives

Same as rounds 2-3:
```python
# In _run_prewarm_build, after cache[key] = value:
if cache is _analysis_cache:
    _holdings_cache.clear()

# In _get_or_build, after cache[key] = value:
if cache is _analysis_cache:
    _holdings_cache.clear()
```

When prewarm finishes → `_analysis_cache` populated → `_holdings_cache` cleared → next holdings request rebuilds → `peek_analysis_result_snapshot()` now finds the cached result → `enrich_positions_with_risk` gets real data → risk fields populated.

This closes the round 3 gap: risk fields DO appear on the next holdings request because the rebuild path calls `enrich_positions_with_risk` every time (just non-blocking).

## Files Modified

| File | Change |
|------|--------|
| `routes/positions.py:412-489` | Remove ThreadPoolExecutor/risk_future, use non-blocking `get_positions_risk_result(non_blocking=True)` + `enrich_positions_with_risk(skip_fallback=True)` |
| `routes/positions.py:563-575` | No change (builder calls `_load_enriched_positions` as before) |
| `services/portfolio_service.py:1419` | Add `non_blocking` param to `get_positions_risk_result` |
| `services/portfolio_service.py:1252` | Add `skip_fallback` param to `enrich_positions_with_risk` |
| `services/portfolio/result_cache.py` | Add `peek_analysis_result_snapshot()`, add `_holdings_cache` invalidation |
| `tests/routes/test_positions_lazy_service.py` | Update tests for non-blocking behavior |
| `tests/services/test_portfolio_result_cache.py` | Add peek + invalidation tests |

## What This Does NOT Change

- The prewarm path — still runs, still populates `_analysis_cache`
- The `/api/analyze` endpoint — still runs full analysis
- `/api/positions/export` — still gets blocking risk enrichment (default `skip_fallback=False`, `non_blocking=False`)
- Response shape — `risk_score`/`beta`/`risk_pct`/`max_drawdown` keys always present (null when not ready, populated when cached)

## Performance Impact

- **Cold holdings (analysis not cached)**: 5-10s → ~1-2s (risk fields null, rest populated)
- **Cold holdings (analysis cached from prewarm)**: instant risk enrichment from cache hit
- **After prewarm completes**: `_holdings_cache` invalidated → next request rebuilds with risk
- **Warm holdings**: ~5ms (no change)
- **Export**: unchanged (blocking enrichment)

## Codex Review History

### Round 1 — FAIL: Prefix-matching unsafe, holdings cached 30s, export not mentioned, tests would break
### Round 2 — FAIL: ThreadPoolExecutor blocks on exit, enrich re-blocks on None, stale-write race
### Round 3 — FAIL: Skipping enrich entirely means risk never appears, response shape changes, tests insufficient
### Round 4 — changes made:
- Non-blocking exact-key cache check via `peek_analysis_result_snapshot()` (same key derivation as blocking path)
- `get_positions_risk_result(non_blocking=True)` returns None if not cached
- `enrich_positions_with_risk(skip_fallback=True)` prevents re-blocking
- Always calls `enrich_positions_with_risk` → response shape preserved (keys present, null when not ready)
- `_holdings_cache` invalidation → risk appears on next request after prewarm completes

## Verification

1. `python3 -m pytest tests/routes/test_positions_lazy_service.py tests/services/test_portfolio_result_cache.py -x -q` — all tests pass
2. Restart backend, clear cache, time cold holdings: should be < 2s (was 5-10s)
3. Risk fields null on first cold hit, present on next request after prewarm
4. Export CSV still includes risk columns
5. Run full measurement script
