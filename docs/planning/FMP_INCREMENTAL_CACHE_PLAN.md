# FMP Incremental Price Cache — Plan

**Status**: PLAN v1 — awaiting Codex review
**Severity**: Medium (performance)
**Scope**: `fmp/cache.py`, `fmp/compat.py`, minor touch to `fmp/client.py`
**Prerequisite**: Companion to `HARDCODED_DATE_AUDIT_PLAN.md` — dynamic dates make the current per-date-range cache strategy wasteful

---

## Background

The FMP price cache keys on `(endpoint, ticker, from_date, to_date, ...)`. Every unique date range produces a separate Parquet file on disk and a separate LRU entry in memory. Today there are 6,337 cache files at 142MB — many are the same ticker with different date range hashes (e.g., 20+ `^HSI_*.parquet` files).

With hardcoded dates this worked fine (stable keys → high hit rate). Moving to dynamic dates (`date.today()`) means:
- Every server restart shifts `end_date` by a day → full cache miss → re-download entire history for every ticker
- Old files accumulate on disk as orphans

Historical price data is **append-only** — once a day's close is recorded, it doesn't change (adjusted prices are the exception, handled separately). The cache should exploit this property.

---

## Design: Canonical Ticker Cache with Incremental Extension

### Core idea

One Parquet file per `(ticker, frequency)` on disk, growing over time. When a request arrives:

1. Load the cached file for this ticker+frequency
2. Check date coverage (min/max of the stored DatetimeIndex)
3. If the requested range is fully within stored range → slice and return (**cache hit, zero API calls**)
4. If the requested range extends beyond stored max → fetch only the delta from FMP (stored_max+1 → requested_end), append, save (**incremental extend**)
5. If the requested range starts before stored min → fetch the missing prefix (requested_start → stored_min-1), prepend, save (**rare — only on lookback extension**)
6. If no cached file → full fetch, store

### What changes

**Layer 1: `fmp/cache.py` — new `TimeSeriesStore`**

New class alongside existing `FMPCache` (which stays for non-timeseries endpoints like profiles, financials).

```python
class TimeSeriesStore:
    """Append-only time series cache. One Parquet file per (ticker, frequency)."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def read(
        self,
        ticker: str,
        frequency: str,  # "daily" | "monthly"
        start: str | None,
        end: str | None,
        loader: Callable[[str | None, str | None], pd.Series],
    ) -> pd.Series:
        """
        Return cached series sliced to [start, end], extending via loader if needed.
        """
        ...
```

Key details:
- **File naming**: `cache/prices/{ticker}_{frequency}.parquet` (e.g., `AAPL_daily.parquet`)
- **Date coverage**: Read from the Parquet DatetimeIndex min/max — no separate metadata file needed
- **Append logic**: `pd.concat([existing, delta]).sort_index().loc[~.index.duplicated(keep='last')]`
- **Atomic writes**: Reuse existing `_atomic_write_parquet()` pattern
- **Thread safety**: File-level lock per ticker (same pattern as `_HISTORICAL_FETCH_LOCK` in compat.py)

**Layer 2: `fmp/compat.py` — rewire `@lru_cache` wrappers**

Current:
```python
@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def _fetch_monthly_close_cached(ticker, fmp_symbol, start_date, end_date) -> pd.Series:
    # Fetch from FMP with from/to params
    ...
```

After:
```python
def _fetch_monthly_close_cached(ticker, fmp_symbol, start_date, end_date) -> pd.Series:
    store = get_timeseries_store()
    return store.read(
        ticker=fmp_symbol,
        frequency="monthly",
        start=start_date,
        end=end_date,
        loader=lambda s, e: _fetch_monthly_close_raw(ticker, fmp_symbol, s, e),
    )
```

- Remove `@lru_cache` from the 3 cached fetch functions — the `TimeSeriesStore` replaces it
- Add a thin in-memory LRU on `TimeSeriesStore.read()` keyed by `(ticker, frequency)` for hot-path performance (holds the full series, sliced on return)
- Extract the FMP API call into `_fetch_*_raw()` helpers (no caching, just HTTP + normalize)

**Layer 3: `fmp/client.py` — no change to `fetch()`**

`FMPClient.fetch()` stays as-is. It still handles the generic disk cache for non-timeseries endpoints (profiles, financials, estimates). The compat layer bypasses the client's cache for price fetches by calling `client.fetch(..., use_cache=False)` and managing caching itself via `TimeSeriesStore`.

### Adjusted prices (stock splits, dividends)

Dividend-adjusted prices (`historical_price_adjusted`) can retroactively change historical values after a split or dividend ex-date. Strategy:

- **Daily/monthly close** (unadjusted): Truly append-only. No staleness concern.
- **Total return / adjusted**: Add a `max_age_days` param to `TimeSeriesStore.read()`. If the cached file is older than N days (default: 30), re-fetch the full range and replace. This is a monthly refresh, matching the existing `CacheRefresh.MONTHLY` strategy.
- Corporate actions are rare (a few per ticker per year), so monthly refresh is sufficient.

### Dedup fetch / inflight coordination

The existing `_run_historical_fetch_once()` pattern (compat.py:134-157) with `_HISTORICAL_FETCH_LOCK` and `_HISTORICAL_FETCH_INFLIGHT` stays. It prevents duplicate in-flight requests for the same ticker. The only change: the key no longer includes dates (just `(type, ticker, fmp_symbol)`), since the store handles date range logic internally.

---

## Migration

### Cache file cleanup

Old per-date-range files (6,337 files, 142MB) become orphans. Options:
1. **Lazy**: Leave them. New canonical files go alongside. Old files never get hit again. Clean up manually or via a one-time script later.
2. **One-time migration**: Script reads each old Parquet, groups by ticker, merges into canonical files, deletes originals.

**Recommendation**: Option 1 (lazy). Old files are harmless. A manual `rm cache/prices/*_????????.parquet` clears them after the change is verified.

### Backward compatibility

- Public API of `fetch_monthly_close()`, `fetch_daily_close()`, `fetch_monthly_total_return_price()` is unchanged (same args, same return type)
- Callers don't know or care about the cache strategy change
- `FMPClient.fetch()` is unchanged for non-price endpoints

---

## What NOT to change

| Component | Why |
|-----------|-----|
| `FMPClient.fetch()` cache strategy | Generic endpoint cache — works fine for profiles, financials, estimates |
| `FMPCache` class | Still used for non-timeseries endpoints |
| Treasury rate cache | Small dataset, monthly refresh is fine |
| FX spot cache | Keyed by `(currency, date)` — correct as-is |
| IBKR cache (`ibkr/cache.py`) | Separate provider, own cache strategy |

---

## Tests

1. **Incremental extend**: Seed cache with data through March 17, request through March 18 → only 1-day delta fetched from API, file now covers full range
2. **Full coverage hit**: Request range within cached range → zero API calls
3. **Prefix extend**: Seed cache starting Jan 2020, request from Jan 2019 → prefix fetched, file now starts earlier
4. **Empty cache**: First request → full fetch → file created
5. **Adjusted price refresh**: Seed cache >30 days old, request → full re-fetch (not incremental)
6. **Concurrent requests**: Two threads request same ticker simultaneously → only one API call (inflight dedup)
7. **Slice correctness**: Cached data is 2019-2026, request is 2023-2025 → returned series is exactly [2023, 2025]

---

## Expected impact

- **Cache files**: ~6,337 → ~200 (one per ticker × frequency, not per date range)
- **Disk usage**: 142MB → ~50MB (no duplication, zstd compression)
- **Cold start after restart**: Incremental (fetch 1 day of delta) instead of full re-download
- **FMP API calls on date shift**: ~0 for most tickers (already cached), 1 call per ticker for the 1-day delta
