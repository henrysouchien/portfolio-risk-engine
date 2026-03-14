# Performance Optimization — Phase 4 (Backend)
**Status:** DONE

## Context

Part of the cross-repo performance optimization effort. Master plan: `docs/planning/PERFORMANCE_OPTIMIZATION_PLAN.md`.

Progress: Phase 1 (frontend logger + market-intelligence fix, `4d8ca07e`), Phase 2 (frontend request reduction, `5429d81e`), Phase 3 planned in AI-excel-addin. Page load: 103 → 26 API requests. Gateway warm cache: ~4.2s.

Phase 4 targets the backend `analyze_portfolio()` path. Cold cache takes ~2-2.5s, warm cache ~50-100ms. The goal is to shave time off the cold-cache path by eliminating redundant data fetches and parallelizing sequential work.

## Current Call Chain (cold cache)

```
POST /api/analyze
  → PortfolioService.analyze_portfolio()     [service layer, L1/L2 cache check]
    → run_portfolio()                        [core/risk_orchestration.py — wrapper]
      → analyze_portfolio()                  [core/portfolio_analysis.py:58]
        → resolve_portfolio_config()          [~50ms, config loading + standardize_portfolio_input()]
          → standardize_portfolio_input()     [inside resolve_portfolio_config; may call latest_price() for share-based holdings]
        → resolve_risk_config()              [~5ms, risk limits loading]
      → build_portfolio_view()                [~1.5-2s, the heavy path]
        → get_returns_dataframe()             [~1-1.5s, ThreadPoolExecutor(8) → FMP]
        → compute_covariance_matrix()         [~50ms, numpy]
        → compute_risk_contributions()        [~50ms, numpy]
        → compute_factor_exposures()          [~200-400ms, ThreadPoolExecutor → FMP proxies]
        → compute_variance_attribution()      [~50ms, numpy, depends on factor_exposures]
      → calc_max_factor_betas()               [~200-400ms, SEQUENTIAL proxy fetches]
        → get_worst_monthly_factor_losses()   [fetches ~8 proxies SEQUENTIALLY]
        → compute_max_betas()                 [calls get_worst_monthly_factor_losses() AGAIN — LRU-cached]
      → evaluate_portfolio_risk_limits()      [~10ms, pure computation]
      → evaluate_portfolio_beta_limits()     [~5ms, pure computation]
```

**Date ranges**: `build_portfolio_view()` uses portfolio config `start_date`/`end_date`. `calc_max_factor_betas()` computes its own window: `today - lookback_years` to `today` (line 276-278 of `risk_helpers.py`). These are different date ranges — no straightforward data sharing between the two steps.

## Caching Layers

FMP data fetches go through multiple cache tiers:
1. **In-memory LRU**: `fmp/compat.py` wraps underlying fetch functions with `@lru_cache`. `_fetch_monthly_close_cached` (line 152) and `_fetch_monthly_total_return_cached` (line 357) both have `@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)`. Same `(ticker, start_date, end_date)` args → instant LRU hit.
2. **Disk cache**: `fmp/cache.py` stores responses on disk. The relevant price endpoints use `CacheRefresh.HASH_ONLY` — hash-based cache keying on request parameters, with no time-based refresh.
3. **FMP API**: Remote HTTP call, rate-limited.

This means the "double-fetch" in `calc_max_factor_betas()` (bottleneck #1) hits the in-memory LRU cache on the second call — microseconds, not disk reads. The real cold-cache cost is the **first** sequential traversal of ~8 proxies in `get_worst_monthly_factor_losses()`, which hits disk (Parquet) or FMP API.

## Bottlenecks Found

### 1. Redundant call in `calc_max_factor_betas()` (Low impact, code clarity)
`calc_max_factor_betas()` at line 281 calls `get_worst_monthly_factor_losses()` to fetch proxy data. Then at line 294, it calls `compute_max_betas()` which internally calls `get_worst_monthly_factor_losses()` AGAIN with identical `(proxies, start_str, end_str)`. Thanks to `@lru_cache` in `fmp/compat.py`, the second call hits the in-memory cache — so the actual latency impact is microseconds, not seconds. Still a redundant code path worth cleaning up.

The same pattern appears in `efficient_frontier.py:91-103` — calls `compute_max_betas()` first, then `get_worst_monthly_factor_losses()` separately.

### 2. Sequential proxy fetches in `get_worst_monthly_factor_losses()` (Main bottleneck)
`risk_helpers.py:63-85` iterates unique proxies in a sequential `for` loop. Each proxy calls `fetch_monthly_total_return_price()` (with fallback to `fetch_monthly_close()`). On cold cache (first call after process start), each proxy requires a disk Parquet read or FMP API call. For ~8 proxies, this serializes ~8 I/O operations. `get_returns_dataframe()` already uses `ThreadPoolExecutor` for the same pattern — `get_worst_monthly_factor_losses()` should too.

### 3. Sequential execution of independent steps (Medium impact)
`build_portfolio_view()` (Step 2, ~1.5-2s) and `calc_max_factor_betas()` (Step 3, ~200-400ms) run sequentially in `analyze_portfolio()` (lines 149, 175 of `portfolio_analysis.py`). They are fully independent — Step 3 doesn't consume Step 2's output, and they use different date ranges. Running them concurrently would save ~200-400ms (the shorter step overlaps with the longer one).

**Note**: Both steps call FMP fetch functions that share the same `@lru_cache`. Step 2 uses portfolio config dates, Step 3 uses a lookback window ending today — so they fetch different data and won't collide on cache keys. But concurrent FMP API calls could trigger rate limiting if many proxies are uncached. The FMP client has built-in rate limiting — verify it handles concurrent access from multiple ThreadPoolExecutors.

### 4. Makefile `--workers` + `--reload` conflict
`Makefile` runs `--workers $(UVICORN_WORKERS) --reload`. Uvicorn docs: `--workers` is "Not valid with `--reload`". When `--reload` is used, uvicorn always runs a single worker regardless of the `UVICORN_WORKERS` setting. So `make dev` has always been single-worker. The `app.py` `__main__` block (line 6001) also uses `reload=True` with no workers config. The `workers=4` example exists only in the `create_app()` docstring (line 882) as a production usage example.

## Items

### 4A. Eliminate redundant `get_worst_monthly_factor_losses()` call
**Impact**: Code clarity + eliminates redundant LRU lookups (~microseconds) | **Effort**: Small
**File**: `portfolio_risk_engine/risk_helpers.py`

`compute_max_betas()` (line 142) has the signature:
```python
def compute_max_betas(proxies, start_date, end_date, loss_limit_pct, fmp_ticker_map=None):
```

It has **7 external callers** that pass `(proxies, start_date, end_date, loss_limit_pct, fmp_ticker_map=...)`:
- `efficient_frontier.py:91`
- `portfolio_optimizer.py:141, 263, 538, 843, 1188, 1340`

**Change**: Add an optional `worst_losses` keyword arg that short-circuits the internal fetch when provided. Keep the existing positional signature fully backward-compatible — **no changes to any external caller**:

```python
# After (risk_helpers.py:142) — fmp_ticker_map stays positional (matching current signature):
def compute_max_betas(
    proxies: Dict[str, Dict[str, List[str] | str]],
    start_date: str,
    end_date:   str,
    loss_limit_pct: float,
    fmp_ticker_map: Dict[str, str] | None = None,
    worst_losses: Dict[str, float] | None = None,  # NEW: skip re-fetch when provided
) -> Dict[str, float]:
    if worst_losses is None:
        worst_losses = get_worst_monthly_factor_losses(
            proxies, start_date, end_date, fmp_ticker_map=fmp_ticker_map,
        )
    worst_by_type = aggregate_worst_losses_by_factor_type(proxies, worst_losses)
    return {
        ftype: float("inf") if worst >= 0 else loss_limit_pct / worst
        for ftype, (_, worst) in worst_by_type.items()
    }
```

Update `calc_max_factor_betas()` (line 294) to pass its already-computed data:
```python
max_betas = compute_max_betas(
    proxies, start_str, end_str, loss_limit,
    fmp_ticker_map=fmp_map,
    worst_losses=worst_per_proxy,  # skip redundant fetch
)
```

All 7 external callers continue to work unchanged — they don't pass `worst_losses`, so the internal fetch runs as before.

### 4B. Parallelize proxy fetches in `get_worst_monthly_factor_losses()`
**Impact**: ~8 sequential I/O ops → concurrent (biggest cold-cache win) | **Effort**: Small
**File**: `portfolio_risk_engine/risk_helpers.py`

**Change**: Replace the sequential `for` loop (line 63-85) with `ThreadPoolExecutor`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _fetch_single_proxy_worst(proxy, start_date, end_date, fmp_ticker_map):
    """Fetch worst monthly return for a single proxy."""
    try:
        try:
            prices = fetch_monthly_total_return_price(proxy, start_date, end_date, fmp_ticker_map=fmp_ticker_map)
        except Exception:
            prices = fetch_monthly_close(proxy, start_date, end_date, fmp_ticker_map=fmp_ticker_map)
        returns = calc_monthly_returns(prices)
        if not returns.empty:
            return proxy, float(returns.min())
    except Exception as e:
        print(f"⚠️ Failed for proxy {proxy}: {e}")
    return proxy, None

# In get_worst_monthly_factor_losses():
max_workers = min(8, len(unique_proxies)) or 1
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {
        executor.submit(_fetch_single_proxy_worst, proxy, start_date, end_date, fmp_ticker_map): proxy
        for proxy in sorted(unique_proxies)
    }
    for future in as_completed(futures):
        proxy, worst = future.result()
        if worst is not None:
            worst_losses[proxy] = worst
```

This mirrors the existing `get_returns_dataframe()` pattern (line 775-923 of `portfolio_risk_engine/portfolio_risk.py`) which already uses `ThreadPoolExecutor(max_workers=8)` for parallel FMP fetches. On cold cache, this turns ~8 sequential disk/API reads into concurrent I/O.

### 4C. Run `build_portfolio_view()` and `calc_max_factor_betas()` concurrently
**Impact**: Steps 2 and 3 overlap instead of sequential (~200-400ms saved) | **Effort**: Medium
**File**: `core/portfolio_analysis.py`

Currently `analyze_portfolio()` runs:
1. `build_portfolio_view()` (line 149) — ~1.5-2s, uses portfolio `config["start_date"]`/`config["end_date"]`
2. `calc_max_factor_betas()` (line 175) — ~200-400ms, uses `today - lookback_years` to `today`

These are independent — different date ranges, no data dependency between them. Run them concurrently:

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=2) as executor:
    future_view = executor.submit(build_portfolio_view, weights, config["start_date"], ...)
    future_betas = executor.submit(calc_max_factor_betas, lookback_years=lookback_years, ...)

    summary = future_view.result()
    max_betas, max_betas_by_proxy, historical_analysis = future_betas.result()
```

**Thread safety**: `build_portfolio_view` is `@lru_cache` wrapped (`lru_cache` is documented as thread-safe). `calc_max_factor_betas` does pure computation + I/O. The in-memory `@lru_cache` in `fmp/compat.py` is also thread-safe per Python docs. Both steps fetch different date ranges, so no cache key collision.

**Caution**: If both steps are on cold cache simultaneously, they create two `ThreadPoolExecutor` instances (one inside `get_returns_dataframe()`, one inside the parallelized `get_worst_monthly_factor_losses()` from 4B). This could spawn up to ~16 concurrent FMP fetch threads. Verify the FMP rate limiter (`fmp/client.py`) handles this correctly. If rate limiting becomes an issue, skip this item — 4A+4B already provide the main gains.

### 4D. Fix Makefile worker configuration
**Impact**: Correct dev/production worker setup | **Effort**: Trivial
**Files**: `Makefile`, `app.py`

**Problem**: `make dev` uses `--workers $(UVICORN_WORKERS) --reload`, but uvicorn's `--workers` flag is "Not valid with `--reload`". Dev has always been single-worker. The `app.py` `__main__` block (line 6015) also uses `reload=True` with no multi-worker support.

**Change**:
1. **`Makefile`**: Split into `dev` (reload, single worker) and `serve` (multi-worker, no reload). Update `.PHONY` and `help` to include the new `serve` target:
```makefile
.PHONY: help dev serve schema-samples test clean

help:
	@echo "  dev               - Start backend dev server (uvicorn, auto-reload, single worker)"
	@echo "  serve             - Start backend server with multiple workers (no reload)"
	...

# Dev server with auto-reload (always single worker — uvicorn constraint)
dev:
	python3 -m uvicorn app:app --host 0.0.0.0 --port $(UVICORN_PORT) --reload

# Production-like server with multiple workers (no reload)
UVICORN_WORKERS ?= 4
serve:
	python3 -m uvicorn app:app --host 0.0.0.0 --port $(UVICORN_PORT) --workers $(UVICORN_WORKERS)
```

2. **`app.py`**: Update `__main__` block (line 6001) to support both modes. Note: uvicorn requires an import string (not an app object) when `reload=True` or `workers > 1`:
```python
import os
workers = int(os.getenv("UVICORN_WORKERS", "1"))
if workers > 1:
    uvicorn.run("app:app", host="0.0.0.0", port=5001, workers=workers)
else:
    uvicorn.run("app:app", host="0.0.0.0", port=5001, reload=True)
```

3. **`app.py` docstrings**: Update `create_app()` usage examples (lines 876-883) to use import string `"app:app"` instead of `app` object. Also update module-level startup examples (lines 60-66) to reflect the `dev`/`serve` split.

## Files to Modify

| File | Changes |
|------|---------|
| `portfolio_risk_engine/risk_helpers.py` | 4A: add optional `worst_losses` kwarg to `compute_max_betas()`, pass from `calc_max_factor_betas()`; 4B: parallelize `get_worst_monthly_factor_losses()` |
| `core/portfolio_analysis.py` | 4C: run `build_portfolio_view` + `calc_max_factor_betas` concurrently |
| `app.py` | 4D: env-configurable worker count in `__main__` block + fix `create_app()` docstring examples to use import string |
| `Makefile` | 4D: split `dev` (reload, single worker) from `serve` (multi-worker) |

## Implementation Order

1. **4A** first (backward-compatible refactor — zero risk, clean up redundant code path)
2. **4B** next (parallelize proxy loop — biggest cold-cache latency win, same pattern as existing `get_returns_dataframe`)
3. **4D** (trivial Makefile/app.py fix)
4. **4C** last (concurrent steps — verify FMP rate limiter handles ~16 concurrent threads first)

## Verification

1. Run existing tests: `python -m pytest tests/core/test_portfolio_risk.py tests/core/test_temp_file_refactor.py tests/core/test_efficient_frontier.py -x -q`
1b. Add new unit tests for the modified functions: `get_worst_monthly_factor_losses()` (parallel behavior) and `compute_max_betas()` (short-circuit via `worst_losses` kwarg). Test both the happy path and the backward-compatible path (no `worst_losses` → internal fetch).
2. Add timing instrumentation to `get_worst_monthly_factor_losses()` and `calc_max_factor_betas()` — measure before/after 4B
3. Live test: `POST /api/analyze` on cold cache — measure total response time
4. Verify risk analysis output is identical (diff the JSON response before/after)
5. Check FMP rate limiter logs for any throttling during concurrent access (4C)
6. Verify `make dev` still works (single worker, reload) and `make serve` runs multi-worker
