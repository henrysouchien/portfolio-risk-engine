# Optimization Endpoint Performance — Parallel Data Fetching

## Context

`POST /api/min-variance` and `POST /api/max-return` block for 60+ seconds on cold cache, making the Strategy Builder unusable. The QP solver itself is fast (1-3s via CVXPY). The bottleneck is **sequential per-ticker data fetching** in two functions:

- `get_returns_dataframe()` — fetches monthly prices for each ticker (20-30 serial calls)
- `compute_factor_exposures()` — fetches stock prices + all proxy prices per ticker (40-80 serial calls)

Additionally, the endpoints are declared `async` but run optimization **synchronously**, blocking the uvicorn event loop and queuing all other API calls behind the optimization.

**Goal:** Parallelize per-ticker data fetching within both functions, and offload optimization to a thread pool so it doesn't block the server. Expected speedup: **60s → 10-15s** on cold cache.

---

## Changes

### 1. Fix FMP thread safety: rate limiter + cache writes + plan-block map

**File:** `fmp/client.py`

The rate limiter's `acquire()` method (line 84-100) has a race condition: `len()` check and `append()` aren't atomic. Add `threading.Lock()`:

```python
import threading

class _RateLimiter:
    def __init__(self, max_calls_per_minute: int = 700) -> None:
        if max_calls_per_minute <= 0:
            raise ValueError("max_calls_per_minute must be positive")
        self._max = max_calls_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._timestamps and self._timestamps[0] <= now - 60:
                self._timestamps.popleft()

            if len(self._timestamps) >= self._max:
                sleep_until = self._timestamps[0] + 60
                sleep_for = sleep_until - now
                if sleep_for > 0:
                    time.sleep(sleep_for)

                now = time.monotonic()
                while self._timestamps and self._timestamps[0] <= now - 60:
                    self._timestamps.popleft()

            self._timestamps.append(time.monotonic())
```

Note: `time.sleep()` inside the lock is acceptable here — if we're at the rate limit, all threads should wait. The lock is only held briefly otherwise (deque operations).

**File:** `fmp/cache.py`

Cache writes at line 112 (`df.to_parquet(path, ...)`) are not atomic — concurrent threads writing the same cache key can corrupt the file. Fix: write to a temp file, then `os.replace()` (atomic on POSIX):

```python
import tempfile, os

# In read() method, line 112:
with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as tmp:
    df.to_parquet(tmp.name, engine="pyarrow", compression="zstd", index=True)
    os.replace(tmp.name, path)

# Same pattern in write() method, line 125
```

**File:** `fmp/compat.py`

The global `_plan_blocked_symbol_until` dict (line 35) is mutated by `_mark_plan_blocked_symbol()` and read by `_is_plan_blocked_symbol()` / `_prune_plan_blocked_symbols()`. With concurrent threads, iteration + mutation in `_prune_plan_blocked_symbols()` (line 44-46) can raise `RuntimeError: dictionary changed size during iteration`. Fix: add a module-level lock:

```python
_plan_blocked_lock = threading.Lock()

# Internal unlocked helper (caller must hold lock):
def _prune_plan_blocked_symbols_unlocked(now_ts=None):
    now = float(now_ts if now_ts is not None else time.time())
    for key, until in list(_plan_blocked_symbol_until.items()):
        if until <= now:
            _plan_blocked_symbol_until.pop(key, None)

# Public API — each acquires lock exactly once, calls unlocked helper:
def _prune_plan_blocked_symbols(now_ts=None):
    with _plan_blocked_lock:
        _prune_plan_blocked_symbols_unlocked(now_ts)

def _is_plan_blocked_symbol(symbol, now_ts=None):
    with _plan_blocked_lock:
        _prune_plan_blocked_symbols_unlocked(now_ts)
        key = _plan_blocked_key(symbol)
        return bool(key and key in _plan_blocked_symbol_until)

def _mark_plan_blocked_symbol(symbol, ttl_seconds=...):
    with _plan_blocked_lock:
        key = _plan_blocked_key(symbol)
        if key:
            _plan_blocked_symbol_until[key] = time.time() + max(1, int(ttl_seconds))
```

This avoids deadlock: `_is_plan_blocked_symbol` calls `_prune_unlocked` (no re-acquire), and all public functions acquire the lock exactly once.

### 2. Parallelize `get_returns_dataframe()` (~25 lines changed)

**File:** `portfolio_risk_engine/portfolio_risk.py`, lines 684-778

Extract the per-ticker body (lines 688-778) into a standalone function `_fetch_ticker_returns()` that takes all needed params and returns a result tuple. Then replace the sequential loop with `ThreadPoolExecutor`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _fetch_ticker_returns(
    ticker, start_date, end_date, fmp_ticker_map, currency_map,
    instrument_types, min_observations, do_fx_attribution,
):
    """Fetch and compute monthly returns for a single ticker. Thread-safe.

    Returns: (ticker, series_or_None, fx_dict_or_None, "ok"|"no_data"|"insufficient", error_msg_or_None)
    """
    try:
        # ... existing per-ticker body from lines 689-778 ...
        # Preserve exact exception handling semantics:
        # - fetch errors → ("no_data", str(e)[:50])
        # - insufficient observations → ("insufficient", count)
        # - success → ("ok", None)
    except Exception as e:
        return (ticker, None, None, "no_data", str(e)[:50])

rets = {}
excluded_no_data = []
excluded_insufficient = []
fx_attribution_local = {}

n_workers = min(8, len(weights)) or 1  # guard against 0
with ThreadPoolExecutor(max_workers=n_workers) as pool:
    futures = {
        pool.submit(
            _fetch_ticker_returns, t, start_date, end_date,
            fmp_ticker_map, currency_map, instrument_types,
            min_observations, fx_attribution_out is not None,
        ): t
        for t in weights
    }
    for fut in as_completed(futures):
        ticker, series, fx_data, status, err = fut.result()
        if status == "no_data":
            excluded_no_data.append((ticker, err or "fetch error"))
        elif status == "insufficient":
            excluded_insufficient.append((ticker, len(series) if series is not None else 0))
        else:
            rets[ticker] = series
            if fx_data:
                fx_attribution_local[ticker] = fx_data

if fx_attribution_out is not None:
    fx_attribution_out.update(fx_attribution_local)
```

The per-ticker work is fully independent — no shared mutable state. Each ticker fetches its own prices, computes its own returns, and optionally does its own FX adjustment.

**Contract preservation:** The function must still raise `ValueError` when ALL tickers are excluded (line 798). This check happens after the thread pool completes, same as before. FX attribution dict is merged into `fx_attribution_out` before the caller filters it at line 1565.

### 3. Parallelize `compute_factor_exposures()` (~25 lines changed)

**File:** `portfolio_risk_engine/portfolio_risk.py`, lines 993-1117

Extract the per-ticker body (lines 993-1116) into `_compute_single_ticker_factors()`:

```python
def _compute_single_ticker_factors(
    ticker, proxies, start_date, end_date, fmp_ticker_map, min_obs,
):
    """Compute factor betas and idiosyncratic variance for one ticker. Thread-safe.

    Returns: (ticker, betas_dict, idio_var) or (ticker, None, None) on skip.
    NOTE: Current code has no per-ticker exception handling — errors propagate
    and fail the entire function. We preserve this: do NOT add a blanket
    try/except. The only "skip" path is when factor_df is empty or has
    insufficient observations (line 1101-1102), which returns (ticker, None, None).
    """
    # ... existing per-ticker body from lines 998-1116 ...
    # If factor_df empty/insufficient → return (ticker, None, None)
    # Otherwise → return (ticker, betas_dict, idio_var)
```

Replace sequential loop:

```python
eligible = [(t, stock_factor_proxies[t]) for t in weights if t in stock_factor_proxies]
n_workers = min(6, len(eligible)) or 1  # guard against 0
with ThreadPoolExecutor(max_workers=n_workers) as pool:
    futures = {
        pool.submit(
            _compute_single_ticker_factors, ticker, proxies,
            start_date, end_date, fmp_ticker_map, min_obs,
        ): ticker
        for ticker, proxies in eligible
    }
    for fut in as_completed(futures):
        ticker, betas, idio_var = fut.result()
        if betas is not None:
            df_stock_betas.loc[ticker, betas.keys()] = pd.Series(betas)
            idio_var_dict[ticker] = idio_var
```

Note: `df_stock_betas` and `idio_var_dict` are only mutated on the main thread (in the `as_completed` loop), not inside the worker functions.

**Ordering:** `as_completed` returns results in arbitrary order. This is fine — `df_stock_betas` is a DataFrame indexed by ticker (order doesn't matter), `idio_var_dict` is a dict (order doesn't matter), `rets` in `get_returns_dataframe` is a dict (converted to DataFrame with column alignment). Log messages for excluded tickers may appear in different order, which is acceptable.

The post-loop interest rate section (lines 1118-1170) stays sequential — it's a single fetch + assignment, not per-ticker.

### 4. Offload entire sync workflow to thread pool in API routes

**File:** `app.py`, lines 2576-2902

Both `min_variance()` and `max_return()` are `async def` but do extensive blocking sync work: portfolio loading (line 2627), factor proxy ensure (line 2629), risk limits loading (line 2645), and finally the optimization call (line 2655). All of this blocks the uvicorn event loop.

Extract the entire blocking workflow into a sync helper and offload with Starlette's `run_in_threadpool` (the idiomatic FastAPI pattern):

```python
from starlette.concurrency import run_in_threadpool

# Extract sync workflow:
def _run_min_variance_sync(user_id, portfolio_name, optimization_service):
    """All blocking work for min-variance, suitable for run_in_threadpool."""
    pm = PortfolioManager(use_database=True, user_id=user_id)
    pd = pm.load_portfolio_data(portfolio_name)
    from services.factor_proxy_service import ensure_factor_proxies
    pd.stock_factor_proxies = ensure_factor_proxies(...)
    # ... risk limits loading ...
    result = optimization_service.optimize_minimum_variance(...)
    return result, risk_limits_name

# In async handler:
result, risk_limits_name = await run_in_threadpool(
    _run_min_variance_sync, user['user_id'], portfolio_name, optimization_service
)

# Same pattern for max_return()
```

Using `run_in_threadpool` instead of `asyncio.get_event_loop().run_in_executor()` because it's the standard Starlette/FastAPI utility and handles edge cases (loop lifecycle, etc.).

For `max_return`, the sync helper must also include the returns-coverage work (`ReturnsService.ensure_returns_coverage()` + `get_complete_returns()`, app.py:2768-2814), which is also blocking.

---

## Files to Modify

| File | Change | ~Lines |
|------|--------|--------|
| `fmp/client.py` | Add `threading.Lock()` to `_RateLimiter` | +3 |
| `fmp/cache.py` | Atomic cache writes via temp file + `os.replace()` | ~6 |
| `fmp/compat.py` | Lock around `_plan_blocked_symbol_until` dict mutations | +8 |
| `portfolio_risk_engine/portfolio_risk.py` | Extract `_fetch_ticker_returns()`, parallelize `get_returns_dataframe()` | ~30 |
| `portfolio_risk_engine/portfolio_risk.py` | Extract `_compute_single_ticker_factors()`, parallelize `compute_factor_exposures()` | ~30 |
| `app.py` | `run_in_threadpool()` for min-variance + max-return endpoints | ~20 |

---

## Thread Safety Notes

- **FMP disk cache** (`fmp/cache.py:99-113`): Currently NOT atomic — direct `to_parquet()` write. Fixed in step 1 with temp file + `os.replace()`. Concurrent reads of a partially written file would fail; `_safe_load()` (line 18) already handles this by returning `None` on corruption (triggers re-fetch).
- **FMP plan-block map** (`fmp/compat.py:35`): Global mutable dict iterated + mutated concurrently. Fixed in step 1 with module-level lock.
- **`requests.get()`**: Thread-safe (creates new connection per call).
- **`get_price_provider()` singleton**: Lazy-init, always returns same stateless adapter instance. Safe.
- **`calc_monthly_returns()`**: Pure function, no shared state.
- **`statsmodels.OLS`**: Creates new model per call. Safe.
- **`pandas` operations**: Safe for independent DataFrames.
- **FX provider**: Singleton, but `adjust_returns_for_fx()` is stateless.

## Max Workers Rationale

- `get_returns_dataframe()`: `min(8, len(weights))` — each ticker makes 1-2 FMP calls. With disk cache hits, many complete instantly. Cap to portfolio size avoids idle threads.
- `compute_factor_exposures()`: `min(6, len(eligible))` — each ticker makes 2-5 FMP calls. Slightly lower to avoid rate limit pressure.
- FMP rate limit: 700/min ≈ 11.7/sec. With 8 workers, worst case ~8 concurrent requests/sec — well under limit. Multiple concurrent optimization requests could fan out further, but rate limiter (now thread-safe) will block excess requests rather than fail.

## Existing Patterns

- **`enrich_positions_with_sectors()`** (`services/portfolio_service.py:1039-1064`): `ThreadPoolExecutor(max_workers=5)` with `pool.map()` for FMP profile lookups.
- **`build_factor_returns_panel()`** (`core/factor_intelligence.py:305-317`): `ThreadPoolExecutor` with `as_completed()` for returns loading.

Both use the same FMP client singleton without issues.

---

## Edge Cases

- **Empty portfolio**: No tickers → no threads spawned → existing error handling.
- **Single ticker**: Thread pool overhead ~1ms. Works correctly.
- **FMP rate limit hit**: Rate limiter blocks the thread that hit the limit. Other threads continue with cached data.
- **Exception in thread**: `fut.result()` re-raises. Current error handling catches and logs.
- **LRU cache on `build_portfolio_view()`**: Unchanged. Cache key is based on serialized inputs. Parallelization is invisible to cache layer.

---

## Verification

1. `python3 -m pytest tests/ -x -v` — no regressions
2. Start backend, open Strategy Builder, trigger min-variance optimization
3. Time the request — should complete in 10-15s on cold cache vs 60s+ before
4. Verify other API calls (holdings, risk) are responsive DURING optimization (run_in_executor test)
5. Check FMP rate limiter doesn't trigger 429s — monitor logs for rate limit warnings
6. Run optimization twice — second call should be fast (cache hit on `build_portfolio_view()`)
