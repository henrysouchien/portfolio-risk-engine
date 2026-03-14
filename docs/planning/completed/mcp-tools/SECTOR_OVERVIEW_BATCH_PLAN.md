# Plan: `get_sector_overview` Batch Mode — Per-Symbol P/E Comparison

**Status:** REVISED — Codex review findings addressed (8/8)

---

## Goal

Add an optional `symbols` parameter to `get_sector_overview()` that accepts a list of stock symbols. For each symbol, fetch its trailing P/E ratio and sector/industry classification, then compare each stock's P/E against the corresponding sector or industry average P/E from the existing snapshot data.

## Current State

`get_sector_overview()` in `mcp_tools/market.py` currently:
- Fetches sector/industry performance snapshots (`sector_performance_snapshot` / `industry_performance_snapshot`)
- Fetches sector/industry P/E snapshots (`sector_pe_snapshot` / `industry_pe_snapshot`)
- Merges them into a unified heatmap by sector/industry name
- Returns `change_pct` and `pe_ratio` per sector/industry

## Design

When `symbols` is provided, the tool enters **batch comparison mode**:

1. Validate input: reject if `sector` is also provided (explicit error); deduplicate and normalize symbols
2. Fetch the sector/industry P/E snapshot as before (for benchmark averages)
3. For each symbol, fetch its `profile` (to get `sector` and `industry`) and `ratios_ttm` (to get the stock's own trailing P/E)
4. Join each stock's P/E against its sector/industry average P/E
5. Return a per-symbol comparison table in deterministic input order

### Data Flow

```
symbols=["AAPL", "MSFT", "XOM"]
           |
           v
    +-------------------+         +---------------------+
    | FMP profile       |         | sector_pe_snapshot   |
    | (sector, industry)|         | or industry_pe_snap  |
    +-------------------+         +---------------------+
    | via client.fetch() |         |
    | (cached, TTL=168h) |         v
    +-------------------+   pe_lookup (by sector/industry name)
           |
           v
    +------------------------+
    | FMP ratios_ttm         |
    | (priceToEarningsRatio  |
    |  TTM)                  |
    | via client.fetch()     |
    | (cached, TTL=24h)      |
    +------------------------+
           |
           v
    per-symbol output:
      symbol, sector, industry, stock_pe, benchmark_pe, premium_pct
```

### FMP Endpoints Used

- **`profile`** (existing, v3, cached TTL=168h): Returns `sector`, `industry`, `companyName`. Already registered.
- **`ratios_ttm`** (existing, stable, cached TTL=24h): Returns `priceToEarningsRatioTTM` (trailing P/E). Already registered.
- **`sector_pe_snapshot`** / **`industry_pe_snapshot`** (existing, cached TTL=6h): Returns aggregate P/E by sector/industry. Already used by `get_sector_overview`.

No new FMP endpoints need to be registered.

### Caching Strategy (HIGH #1 fix)

**Use `client.fetch()` (cached), NOT `fetch_raw()` (uncached).**

`fetch_raw()` at `fmp/client.py:369` explicitly bypasses caching — every call hits the FMP API directly. With 10 symbols, that would be 20 uncached API calls per invocation, creating real rate-limit risk especially on free-tier FMP plans.

Instead, use `client.fetch()` which leverages the Parquet+zstd disk cache:
- `profile`: TTL = 168 hours (1 week) — sector/industry classification rarely changes
- `ratios_ttm`: TTL = 24 hours — P/E updates daily

The per-symbol fetcher extracts the first row from the returned DataFrame:
```python
def _fetch_symbol_data(client: FMPClient, symbol: str, use_cache: bool) -> ...:
    profile_df = client.fetch("profile", symbol=symbol, use_cache=use_cache)
    ratios_df = client.fetch("ratios_ttm", symbol=symbol, use_cache=use_cache)
    profile = profile_df.iloc[0].to_dict() if not profile_df.empty else None
    ratios = ratios_df.iloc[0].to_dict() if not ratios_df.empty else None
    ...
```

Additional safeguard: cap at **10 symbols** (not 20) to limit worst-case uncached calls to 20 API hits. The `use_cache` parameter is passed through so users can force-refresh when needed.

## Output Structure

When `symbols` is provided (summary format):

```python
{
    "status": "success",
    "date": "2026-02-15",
    "level": "industry",
    "benchmark_level": "industry",   # explicit label for benchmark source
    "mode": "comparison",
    "comparisons": [                 # deterministic: preserves input symbol order
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "stock_pe": 32.5,
            "benchmark_pe": 28.1,           # level-neutral key
            "benchmark_name": "Consumer Electronics",
            "premium_pct": 15.66,
            "verdict": "above",             # level-neutral
        },
        {
            "symbol": "XOM",
            "name": "Exxon Mobil Corporation",
            "sector": "Energy",
            "industry": "Oil & Gas Integrated",
            "stock_pe": 12.3,
            "benchmark_pe": 14.8,
            "benchmark_name": "Oil & Gas Integrated",
            "premium_pct": -16.89,
            "verdict": "below",
        },
        {
            "symbol": "BYND",
            "name": "Beyond Meat, Inc.",
            "sector": "Consumer Defensive",
            "industry": "Packaged Foods",
            "stock_pe": null,
            "benchmark_pe": 22.1,
            "benchmark_name": "Packaged Foods",
            "premium_pct": null,
            "verdict": "negative_earnings",
        },
        {
            "symbol": "NEWCO",
            "name": "NewCo Inc.",
            "sector": "Technology",
            "industry": "Obscure Niche",
            "stock_pe": 18.0,
            "benchmark_pe": null,
            "benchmark_name": null,
            "premium_pct": null,
            "verdict": "no_benchmark",
        },
    ],
    "summary": {
        "above_count": 1,
        "below_count": 1,
        "at_par_count": 0,
        "no_benchmark_count": 1,
        "negative_earnings_count": 1,
        "avg_premium_pct": -0.62,
    },
    "failed_symbols": [],
    "count": 4,
}
```

When `format="full"`, each comparison includes `"profile_raw"` and `"ratios_raw"` dicts.

## File Changes

### 1. `mcp_tools/market.py`

**a. Update `get_sector_overview()` signature:**

Add `symbols: Optional[list[str]] = None`. Add `import math`. Add validation:
```python
if symbols is not None:
    if sector:
        return {
            "status": "error",
            "error": "Cannot combine 'symbols' and 'sector' parameters. "
                     "Use 'symbols' for per-stock P/E comparison, or "
                     "'sector' for sector-level overview, but not both.",
        }
    return _fetch_symbol_pe_comparison(symbols, date, level, format, use_cache)
return _fetch_sector_overview(date, sector, level, format, use_cache)
```

Note: `if symbols is not None:` (not `if symbols:`) ensures `symbols=[]` enters the batch branch and hits the empty-list validation inside `_fetch_symbol_pe_comparison()`, rather than falling through to sector overview mode.

**b. Add `_fetch_symbol_pe_comparison()` helper:**

```python
MAX_COMPARISON_SYMBOLS = 10

def _fetch_symbol_pe_comparison(symbols, snapshot_date, level, format, use_cache):
```

Steps:
1. Strip whitespace, uppercase, deduplicate preserving input order (`dict.fromkeys()`)
2. Reject empty list; cap at 10 with `truncated_warning` if exceeded
3. Fetch benchmark P/E snapshot via `_safe_fetch()`
4. Build case-insensitive P/E lookup dict
5. Parallel fetch per-symbol data via `ThreadPoolExecutor` (max 5 workers) using `client.fetch()` (cached)
6. Build comparisons in input order; handle all-failed case
7. Build summary stats; return

**c. Add `_fetch_symbol_data()` helper:**

Per-symbol fetcher using cached `client.fetch()`, returns `(symbol, profile_dict, ratios_dict, error_or_None)`.

**d. Add `_compute_pe_premium()` helper (HIGH #2 fix):**

```python
def _compute_pe_premium(stock_pe, benchmark_pe):
    if stock_pe is None or benchmark_pe is None:
        return None
    try:
        stock_pe_f, benchmark_pe_f = float(stock_pe), float(benchmark_pe)
    except (ValueError, TypeError):
        return None
    if benchmark_pe_f == 0 or not math.isfinite(benchmark_pe_f) or not math.isfinite(stock_pe_f):
        return None
    return round((stock_pe_f - benchmark_pe_f) / benchmark_pe_f * 100, 2)
```

**e. Add `_classify_verdict()` helper:**

Returns `"above"`, `"below"`, `"at_par"`, `"negative_earnings"`, `"no_benchmark"`, or `"no_data"`. Level-neutral verdicts.

### 2. `fmp_mcp_server.py`

Add `symbols: Optional[list[str]] = None` to wrapper, update docstring with comparison examples.

### 3. `tests/mcp_tools/test_market.py`

Add `TestGetSectorOverviewSymbols` class — **18 tests** (all mock `client.fetch()`, return DataFrames):

1. `test_symbols_basic_comparison` — 2 symbols, verify structure + premium calc
2. `test_symbols_industry_level` — `level="industry"`, verify industry matching
3. `test_symbols_missing_pe` — negative P/E → `verdict: "negative_earnings"`
4. `test_symbols_no_benchmark_match` — industry not in snapshot → `verdict: "no_benchmark"`
5. `test_symbols_failed_fetch` — one fails, others succeed; `failed_symbols` populated
6. `test_symbols_empty_list` — `symbols=[]` → error
7. `test_symbols_full_format` — includes `profile_raw` and `ratios_raw`
8. `test_symbols_verdict_thresholds` — +6% → above, -6% → below, +3% → at_par
9. `test_symbols_cap_enforcement` — 15 symbols → only 10 processed, `truncated_warning`
10. `test_symbols_dedupe_and_normalization` — `["aapl", "AAPL", " msft "]` → `["AAPL", "MSFT"]`
11. `test_symbols_output_order_deterministic` — preserves input order
12. `test_symbols_plus_sector_conflict` — explicit validation error
13. `test_symbols_zero_benchmark_pe` — `premium_pct: None`, no divide-by-zero
14. `test_symbols_all_failed` — `status: "error"`
15. `test_symbols_date_and_use_cache_passthrough` — verify params reach fetch calls
16. `test_symbols_empty_snapshot_valid_symbols` — all get `verdict: "no_benchmark"`
17. `test_symbols_missing_sector_in_profile` — empty sector/industry → `verdict: "no_benchmark"`
18. `test_symbols_duplicate_preserved_first` — dedup preserves first occurrence

## Design Decisions

1. **Reuse existing P/E snapshot** rather than computing from constituents — canonical source
2. **Parallel fetching** via `ThreadPoolExecutor` (max 5 workers), matching `compare_peers` pattern
3. **Max 10 symbols** cap (reduced from 20) — limits worst-case to 20 API calls when cache cold (HIGH #1)
4. **Use `client.fetch()` (cached)** not `fetch_raw()` (uncached) — profile cached 168h, ratios cached 24h (HIGH #1)
5. **P/E field**: `priceToEarningsRatioTTM` from `ratios_ttm` — actual FMP field name, consistent with `mcp_tools/peers.py:31,47` (MED #3, LOW #8)
6. **Level-neutral output keys**: `benchmark_pe`, `benchmark_level`, verdicts are `"above"`/`"below"`/`"at_par"` (MED #4)
7. **`symbols` + `sector` → explicit validation error** (MED #5)
8. **Verdict thresholds**: 5% for above/below
9. **Negative P/E**: `stock_pe: None`, `verdict: "negative_earnings"`
10. **Deterministic output order**: preserves input symbol order after dedup (MED #6)
11. **Divide-by-zero guard**: `_compute_pe_premium()` returns None for benchmark_pe=0 (HIGH #2)

## Edge Cases

| Case | Handling |
|------|----------|
| `symbols=[]` | `status: "error"` |
| `symbols` + `sector` both provided | `status: "error"` — explicit conflict (MED #5) |
| All symbols fail to fetch | `status: "error"` with `failed_symbols` |
| One symbol fails, others succeed | Partial success, failed in `failed_symbols` |
| Negative earnings (P/E <= 0, numeric) | `stock_pe: None`, `verdict: "negative_earnings"` |
| Missing/unparseable P/E (None) | `stock_pe: None`, `verdict: "no_data"` |
| Industry/sector not in snapshot | `benchmark_pe: None`, `verdict: "no_benchmark"` |
| Benchmark P/E is 0.0 | `premium_pct: None`, `verdict: "no_data"` (HIGH #2) |
| Benchmark P/E non-numeric / NaN | `premium_pct: None`, `verdict: "no_data"` |
| Profile missing sector/industry | `benchmark_pe: None`, `verdict: "no_benchmark"` |
| P/E snapshot empty (API issue) | All get `verdict: "no_benchmark"` |
| Duplicate symbols | Deduped preserving first-occurrence order |
| Mixed case / whitespace | Normalized to uppercase, stripped |
| >10 symbols | Truncated to first 10 with `truncated_warning` |
| `use_cache=False` | Passed through to all `client.fetch()` calls |
| `date` param with symbols | Passed through to P/E snapshot fetch |

## Traps to Avoid During Implementation (LOW #8)

- **P/E field name**: `ratios_ttm` returns `priceToEarningsRatioTTM`. `profile` returns a different `peRatio`. Always use the former.
- **Test fixtures**: Some existing tests use `peRatioTTM` in mocks — incorrect for `ratios_ttm` data. Always use `priceToEarningsRatioTTM`.
- **`fetch()` vs `fetch_raw()`**: `fetch()` returns `pd.DataFrame` (cached), `fetch_raw()` returns raw JSON (uncached). Use `df.iloc[0].to_dict()`.
- **`profile` response**: Single-row DataFrame. Check `not df.empty` before `.iloc[0]`.
