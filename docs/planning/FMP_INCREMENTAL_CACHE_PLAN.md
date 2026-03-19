# FMP Incremental Price Cache — Plan

**Status**: PLAN v7 — addressing Codex v6 review feedback
**Severity**: Medium (performance)
**Scope**: `fmp/cache.py`, `fmp/compat.py`, `services/cache_adapters.py`
**Prerequisite**: Companion to `HARDCODED_DATE_AUDIT_PLAN.md` — dynamic dates make the current per-date-range cache strategy wasteful

---

## Background

The FMP price cache keys on `(endpoint, ticker, from_date, to_date, ...)`. Every unique date range produces a separate Parquet file on disk and a separate LRU entry in memory. Today there are 6,337 cache files at 142MB — many are the same ticker with different date range hashes (e.g., 20+ `^HSI_*.parquet` files).

With hardcoded dates this worked fine (stable keys → high hit rate). Moving to dynamic dates (`date.today()`) means:
- Every server restart shifts `end_date` by a day → full cache miss → re-download entire history for every ticker
- Old files accumulate on disk as orphans

Historical price data is **append-only** — once a day's close is recorded, it doesn't change (adjusted prices are the exception, handled separately). The cache should exploit this property.

---

## Design: Canonical Daily Store with Derived Monthly

### Core idea

Store **daily** data as the canonical source per `(ticker, series_kind)`. Derive monthly resampling on read. This avoids the partial-month problem where a mid-month fetch gets a future month-end label and appears "complete."

**Canonical key**: `(ticker, series_kind)` where `series_kind` is one of:
- `close` — unadjusted close prices (from `historical_price_eod`)
- `adjusted` — dividend-adjusted close (from `historical_price_adjusted`)
- `total_return` — total return prices (from `historical_price_adjusted`, `adjClose` column)

This prevents the collision between monthly close and monthly total-return — they're different series kinds stored in separate files.

When a request arrives:

1. Load the cached daily file for this `(ticker, series_kind)`
2. Check date coverage (min/max of the stored DatetimeIndex)
3. If the requested range is fully within stored range → slice (and resample to monthly if needed) → return (**cache hit, zero API calls**)
4. If the requested range extends beyond stored max → fetch only the delta from FMP (`stored_max + 1 day` → `requested_end`), append, save (**incremental extend**)
5. If the requested range starts before stored min → fetch the missing prefix (`requested_start` → `stored_min - 1 day`), prepend, save (**rare — only on lookback extension**)
6. If no cached file → full fetch, store

### What changes

**Layer 1: `fmp/cache.py` — new `TimeSeriesStore`**

New class alongside existing `FMPCache` (which stays for non-timeseries endpoints).

```python
class TimeSeriesStore:
    """Append-only daily time series cache. One Parquet file per (ticker, series_kind)."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._locks: dict[str, threading.Lock] = {}  # per-file thread locks
        self._lock_guard = threading.Lock()           # protects _locks dict

    def read(
        self,
        ticker: str,
        series_kind: str,     # "close" | "adjusted" | "total_return"
        start: str | None,
        end: str | None,
        loader: Callable[[str | None, str | None], pd.Series],
        *,
        resample: str | None = None,  # "ME" for monthly, None for daily
        max_age_days: int | None = None,  # force full refresh if file older than N days
    ) -> pd.Series:
        """
        Return cached daily series sliced to [start, end], extending via loader if needed.
        If resample is set, resample the daily data before returning.
        """
        ...
```

Key details:
- **File naming**: `cache/timeseries/{ticker}_{series_kind}.parquet` (e.g., `AAPL_close.parquet`, `AAPL_adjusted.parquet`)
- **Separate directory**: `cache/timeseries/` — not `cache/prices/`. Old per-date-range files in `cache/prices/` remain untouched and are still used by `FMPClient.fetch()` for direct callers.
- **Date coverage**: Read from the Parquet DatetimeIndex min/max — no separate metadata file
- **Append logic**: `pd.concat([existing, delta]).sort_index().loc[~.index.duplicated(keep='last')]`
- **Monthly derivation**: When `resample="ME"` is passed, apply `.resample("ME").last()` on the daily data before returning. Note: pandas `resample("ME")` will still label a partial March bucket as `2026-03-31` — this is standard pandas behavior and matches the current code (`compat.py:280,486`). The key improvement is that **coverage checks happen on daily data** (stored_max = actual last daily date, e.g., March 17), not on monthly labels. So the extend decision is always correct. The monthly label is cosmetic and all existing consumers already handle it.
- **Atomic writes**: Reuse existing `_atomic_write_parquet()` pattern
- **Thread safety**: Per-file `threading.Lock` (keyed by canonical file path). This is sufficient for single-process deployment (our case). Multi-process would need `fcntl.flock()` — noted as a future enhancement if needed.

**Layer 2: `fmp/compat.py` — rewire cached fetch functions**

Current (3 functions with `@lru_cache`):
```python
@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def _fetch_monthly_close_cached(ticker, fmp_symbol, start_date, end_date) -> pd.Series:
    ...

@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def _fetch_daily_close_cached(ticker, fmp_symbol, start_date, end_date) -> pd.Series:
    ...

@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def _fetch_monthly_total_return_cached(ticker, fmp_symbol, start_date, end_date) -> pd.Series:
    ...
```

After:
```python
def _fetch_monthly_close_cached(ticker, fmp_symbol, start_date, end_date) -> pd.Series:
    if _is_plan_blocked_symbol(fmp_symbol):
        return pd.Series(dtype=float, name=ticker)
    store = get_timeseries_store()
    series = store.read(
        ticker=fmp_symbol,
        series_kind="close",
        start=start_date,
        end=end_date,
        loader=lambda s, e: _fetch_daily_close_raw(ticker, fmp_symbol, s, e),
        resample="ME",
    )
    series.name = ticker  # Rename from fmp_symbol to caller's display ticker
    return series

def _fetch_daily_close_cached(ticker, fmp_symbol, start_date, end_date) -> pd.Series:
    if _is_plan_blocked_symbol(fmp_symbol):
        return pd.Series(dtype=float, name=ticker)
    store = get_timeseries_store()
    series = store.read(
        ticker=fmp_symbol,
        series_kind="close",
        start=start_date,
        end=end_date,
        loader=lambda s, e: _fetch_daily_close_raw(ticker, fmp_symbol, s, e),
    )
    series.name = ticker  # Rename from fmp_symbol to caller's display ticker
    return series

def _fetch_monthly_total_return_cached(ticker, fmp_symbol, start_date, end_date) -> pd.Series:
    # Preserve existing fallback behavior: try adjusted endpoint,
    # fall back to close-only with _price_only suffix on failure.
    # IMPORTANT: Do NOT cache fallback (close-only) data in the total_return
    # canonical file — it would poison the cache with wrong series kind.
    if _is_plan_blocked_symbol(fmp_symbol):
        return pd.Series(dtype=float, name=f"{ticker}_price_only")
    try:
        store = get_timeseries_store()
        series = store.read(
            ticker=fmp_symbol,
            series_kind="total_return",
            start=start_date,
            end=end_date,
            loader=lambda s, e: _fetch_total_return_raw(ticker, fmp_symbol, s, e),
            resample="ME",
            max_age_days=30,
        )
        series.name = f"{ticker}_total_return"
        return series
    except Exception:
        # Fallback to close-only — fetch via store but as "close" kind
        # (does NOT write to total_return cache file)
        series = store.read(
            ticker=fmp_symbol,
            series_kind="close",
            start=start_date,
            end=end_date,
            loader=lambda s, e: _fetch_daily_close_raw(ticker, fmp_symbol, s, e),
            resample="ME",
        )
        series.name = f"{ticker}_price_only"
        return series
```

- **`@lru_cache` removed** from these 3 functions. The `TimeSeriesStore` replaces them.
- **Extracted `_raw` helpers**: `_fetch_daily_close_raw()`, `_fetch_total_return_raw()` — FMP API calls via `client.fetch(..., use_cache=False)`, no caching. All 4 compat sites that call `client.fetch()` switch to `use_cache=False`: lines 245, 307, 457, 498. **These helpers preserve the existing 402-blocking lifecycle**: on HTTP 402, call `_mark_plan_blocked_symbol(fmp_symbol)` and log via `log_critical_alert()`, matching current behavior at `compat.py:244,500`. The wrappers check `_is_plan_blocked_symbol()` upfront; the raw helpers handle first-encounter marking.
- **Monthly close and daily close share the same canonical file** (`{ticker}_close.parquet`). Monthly just adds `resample="ME"`. This means fetching monthly first populates the daily cache too.
- **`_is_plan_blocked_symbol()` preserved**: All 3 functions check `_is_plan_blocked_symbol()` before hitting the store, matching current behavior (compat.py:234, 296). Returns empty Series with correct name on blocked symbols.
- **`series.name` rename-on-read**: The store caches by `fmp_symbol` (e.g., `AT.L`), but callers expect `series.name` to be the display ticker (e.g., `AT`). Each wrapper sets `series.name = ticker` after reading from the store. This matches current behavior (compat.py:282, 343, 489, 544) and avoids the AT/AT.L alias collision documented in `FMP_TICKER_POSITION_KEY_FIX.md`.
- **Total return fallback**: On adjusted-endpoint failure, falls back to `close` series kind (not `total_return`), with `_price_only` name suffix. This prevents poisoning the `total_return` cache with close-only data. Matches existing behavior (compat.py:492-544) and test assertions (test_fmp_migration.py:269).
- **`@lru_cache` removal propagation**: Multiple sites call `.cache_clear()` / `.cache_info()` on the 3 cached functions:
  - `services/cache_adapters.py:263` — `FMPCacheAdapter` manages these functions
  - `fmp/compat.py:89` — `_clear_historical_fetch_cache_for_tests()` calls `.cache_clear()` on all 3
  - Test files: `test_fmp_client.py:465,491`, `test_fmp_migration.py:115`, `test_cache_control.py:370`

  All must be updated. Approach: **Make `FMPCacheAdapter` store-aware** — replace the per-function `.cache_clear()` / `.cache_info()` pattern with a single `TimeSeriesStore` reference. The adapter calls `store.clear(series_kind=...)` for targeted clearing and `store.stats(series_kind=...)` for per-kind stats (file count, total size, date coverage). This avoids double-counting across functions that share the same store. For backward compat in test files, add `cache_clear()` as an attribute on the 3 functions that delegates to the store:
  - `_fetch_monthly_close_cached.cache_clear` → `store.clear(series_kind="close")`
  - `_fetch_daily_close_cached.cache_clear` → `store.clear(series_kind="close")`
  - `_fetch_monthly_total_return_cached.cache_clear` → `store.clear(series_kind="total_return")` **AND** `store.clear(series_kind="close")` — because fallback writes to `close` kind, and old `@lru_cache` evicted everything this function produced regardless of which endpoint succeeded.

  This preserves test isolation — existing tests at `test_fmp_client.py:466,491` and `compat.py:89` rely on these calls to evict cached data between test cases. `_clear_historical_fetch_cache_for_tests()` calls `get_timeseries_store().clear()` directly.

**Layer 3: Inflight dedup — keep dates in dedup key**

The existing `_run_historical_fetch_once()` pattern (compat.py:134-157) stays **unchanged**. The dedup key keeps `(type, ticker, fmp_symbol, start_str, end_str)` as-is. Rationale: the Future stores the already-sliced returned Series, so removing dates from the key would cause concurrent requests for different date ranges to get the wrong slice. The `TimeSeriesStore` handles the incremental extend logic internally — dedup only prevents duplicate HTTP requests for the same exact (ticker, range) pair in flight.

**Layer 4: `fmp/client.py` — no change**

`FMPClient.fetch()` stays as-is. Compat layer passes `use_cache=False` for price fetches (verified: `client.py:460` skips disk cache when `use_cache=False`).

### Adjusted prices (stock splits, dividends)

Dividend-adjusted prices (`historical_price_adjusted`) can retroactively change historical values after a split or dividend ex-date. The endpoint is currently `CacheRefresh.HASH_ONLY` (not MONTHLY — registry.py:238).

Strategy:
- **`close` (unadjusted)**: Truly append-only. `max_age_days=None` — never full-refresh.
- **`total_return` / `adjusted`**: `max_age_days=30`. If the cached file's mtime is >30 days old, trigger a full refresh. **Refresh scope**: re-fetch using the existing canonical file's min date as start and today as end (i.e., cover at least the same range). This prevents a narrow request from shrinking the canonical file. The store reads the existing file's date range before deleting and re-fetching. Corporate actions are rare (a few per ticker per year), so 30-day refresh is sufficient. This is a policy tradeoff: up to 30 days of stale adjusted prices after a split.

---

## Migration

### Cache file coexistence

- New canonical files go in `cache/timeseries/` (separate from `cache/prices/`)
- Old per-date-range files in `cache/prices/` are **NOT orphaned** — they continue to be used by `FMPClient.fetch()` for direct callers (e.g., `scripts/chartbook/data_fetcher.py:70`, `fmp/tools/market.py:1238`, `fmp/tools/fmp_core.py:140`). These callers go through `FMPClient.fetch()` which still uses `FMPCache` with the old key strategy. Only the compat-layer price wrappers (`fetch_monthly_close`, `fetch_daily_close`, `fetch_monthly_total_return_price`) use the new `TimeSeriesStore`.
- Over time, direct `client.fetch()` callers for price endpoints could be migrated to compat wrappers, but this is not required for the initial change.

### Backward compatibility

- Public API of `fetch_monthly_close()`, `fetch_daily_close()`, `fetch_monthly_total_return_price()` is unchanged (same args, same return type)
- Callers don't know or care about the cache strategy change
- `FMPClient.fetch()` is unchanged for all endpoints

---

## What NOT to change

| Component | Why |
|-----------|-----|
| `FMPClient.fetch()` cache strategy | Generic endpoint cache — works fine for profiles, financials, estimates. Direct price callers still use it. |
| `FMPCache` class | Still used for non-timeseries endpoints and direct client callers |
| `cache/prices/` directory | Still active for FMPClient.fetch() callers — do not clean up |
| Treasury rate cache | Small dataset, monthly refresh is fine |
| FX spot cache | Keyed by `(currency, date)` — correct as-is |
| IBKR cache (`ibkr/cache.py`) | Separate provider, own cache strategy |
| `_run_historical_fetch_once()` dedup keys | Must keep dates to avoid wrong-slice on concurrent requests |

---

## Tests

1. **Incremental extend**: Seed cache with daily data through March 17, request through March 18 → only 1-day delta fetched from API, file now covers full range
2. **Full coverage hit**: Request range within cached range → zero API calls
3. **Prefix extend**: Seed cache starting Jan 2020, request from Jan 2019 → prefix fetched, file now starts earlier
4. **Empty cache**: First request → full fetch → file created
5. **Monthly derivation**: Seed daily cache, request monthly → returns proper month-end resampled series
6. **Partial month coverage**: Seed daily data through March 17, request monthly → last entry has March 17 close value (labeled `2026-03-31` per pandas convention). Crucially, the **daily** stored_max is March 17, so requesting through March 18 correctly triggers a 1-day delta fetch (not a false coverage hit)
7. **Adjusted price refresh**: Seed cache >30 days old, request → full re-fetch (not incremental)
8. **Concurrent requests**: Two threads request same ticker+range simultaneously → only one API call (inflight dedup preserved)
9. **Different ranges concurrent**: Two threads request same ticker, different ranges → both get correct slices
10. **Slice correctness**: Cached data is 2019-2026, request is 2023-2025 → returned series is exactly [2023, 2025]
11. **Series kind isolation**: `close` and `total_return` for same ticker → separate files, no collision
12. **Cache adapter compat**: `FMPCacheAdapter.clear_cache()` works after @lru_cache removal
13. **Plan-blocked symbol**: Blocked symbol → returns empty Series immediately, no store hit
14. **Series.name aliasing**: Fetch with fmp_symbol=`AT.L`, display ticker=`AT` → returned series.name is `AT`
15. **Total return fallback**: Adjusted endpoint fails → fallback returns `_price_only` series from `close` cache, `total_return` cache file NOT created/poisoned

---

## Expected impact

- **Cache files**: ~6,337 (prices/) unchanged + ~150 new (timeseries/). Over time, timeseries/ serves most requests.
- **Disk usage**: ~50MB incremental for timeseries/ (one daily file per ticker, zstd compressed)
- **Cold start after restart**: Incremental (fetch 1 day of delta) instead of full re-download
- **FMP API calls on date shift**: ~0 for most tickers (already cached), 1 call per ticker for the 1-day delta

---

## Codex review history

- **v1 FAIL**: (1) `(ticker, frequency)` key collision — monthly close and monthly total-return both "monthly". (2) Removing dates from inflight dedup key → wrong-slice on concurrent requests. (3) Stored monthly data has partial-month edge case — month-end labels mask incomplete data. (4) threading.Lock not process-safe. (5) Adjusted endpoint is HASH_ONLY, not MONTHLY — stale claim. (6) Direct FMPClient.fetch() callers still use old cache files — can't clean up. (7) Removing @lru_cache breaks cache_adapters.py.
- **v2 FAIL**: (1) `resample("ME").last()` still labels partial months as month-end — plan claimed otherwise. (2) Total return fallback can poison cache with close-only data. (3) Store keyed by fmp_symbol but series.name must be display ticker — AT/AT.L alias issue. (4) `_is_plan_blocked_symbol()` check dropped from rewritten functions.
- **v3 FAIL**: (1) `_mark_plan_blocked_symbol()` 402-marking logic not specified in `_raw` helpers. (2) `@lru_cache` removal not fully propagated — `_clear_historical_fetch_cache_for_tests()` and 4 test files call `.cache_clear()`. (3) Adjusted price refresh scope undefined — narrow request could shrink canonical file.
- **v4 FAIL**: cache_clear()/cache_info() shims delegating to shared store → FMPCacheAdapter double-counts stats across functions sharing the same store.
- **v5 FAIL**: `cache_clear()` no-op on compat functions breaks test isolation — tests rely on evicting cached data between cases.
- **v6 FAIL**: `_fetch_monthly_total_return_cached` fallback writes to `close` kind, so clearing only `total_return` doesn't evict fallback data → test isolation broken.
- **v7**: Total return `cache_clear()` clears BOTH `total_return` AND `close` kinds, matching old `@lru_cache` evict-everything semantics.
