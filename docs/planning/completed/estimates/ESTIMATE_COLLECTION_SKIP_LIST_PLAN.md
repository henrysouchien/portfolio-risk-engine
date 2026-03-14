# Estimate Collection Universe Optimization

## Problem

The FMP company screener returns ~6,662 actively traded stocks, but many have no analyst estimate coverage. These tickers waste 3 API calls each (income_statement + 2 estimate periods) and always result in either:

1. **No income statement** — `_ReportedDateLookupFailed`, ticker is skipped entirely (fail-closed)
2. **No analyst estimates** — income statement lookup succeeds but `analyst_estimates` returns empty data for both periods, resulting in 0 rows inserted

### Observed from 100-ticker test run

- 97 succeeded, 3 failed
- Failed tickers: `AACOU`, `ADACU`, `ADACW` — all warrant/unit securities with no income statements AND no analyst estimates
- Many succeeded tickers also had 0 forward estimates (e.g. `AAB.TO`, `AACB`, `ABLV`, `ABTS`) — income statement exists but no analyst coverage

### Scale impact

At ~6,662 tickers, if ~30-40% have no estimates, that's ~2,000+ wasted API calls per run (income_statement lookups that lead nowhere). At 3 calls per ticker, that's ~6,000 wasted calls.

## Failure categories

| Category | Example | Income Statement? | Estimates? | Current behavior |
|---|---|---|---|---|
| Warrants/units | AACOU, ADACW | No | No | Fails with `_ReportedDateLookupFailed`, counted as failed |
| No analyst coverage | AAB.TO, ABLV | Yes | No | Succeeds with 0 rows inserted |
| Has coverage | AAPL, NVDA | Yes | Yes | Succeeds with rows inserted |

## Proposed approach: Bulk + screener intersection

Use FMP's `earnings-surprises-bulk` endpoint to get a definitive list of tickers with analyst coverage, then intersect with the screener to produce a filtered universe of only actively traded stocks that have coverage.

### `earnings-surprises-bulk`

- **Endpoint**: `earnings-surprises-bulk?year=YYYY` (v4, CSV response)
- **Returns**: All symbols that had earnings with analyst estimates for a given year
- **Fields (CSV columns)**: `date`, `symbol`, `actualEarningResult`, `estimatedEarning`
- **No `fiscalDateEnding`** — validated empirically. The `date` field is the earnings announcement date, not the fiscal period end date.
- **One call per year** — returns ~52K rows, ~17.9K distinct symbols (global, includes non-stocks)
- **Response format**: CSV (not JSON). `FMPClient.fetch_raw()` uses `resp.json()` internally, so this endpoint requires a dedicated CSV parsing path.

### Validated numbers

| Set | Count | Description |
|---|---|---|
| Screener | 6,662 | Actively traded, non-ETF/fund stocks (`company_screener`) |
| Bulk (2025) | 17,932 | All symbols with earnings surprises globally |
| **Intersection** | **4,911** | Actively traded stocks WITH analyst coverage |
| Screener only | 1,751 | Actively traded but no coverage (wasted API calls) |
| Bulk only | 13,021 | Global/delisted/non-stock symbols (noise) |

### Why intersection, not bulk-only

The bulk endpoint is global and noisy — it includes delisted tickers, foreign instruments, preferred shares, and other non-stock symbols. The screener enforces `isActivelyTrading=True`, `isEtf=False`, `isFund=False`. Using the intersection ensures we only collect actively traded stocks with confirmed analyst coverage.

### `income_statement` lookup: still required

The bulk endpoint does NOT contain `fiscalDateEnding`. Forward-only filtering (`_filter_forward_estimates`) requires the last reported fiscal date, which comes from the per-ticker `income_statement` call. This call is retained.

## Implementation plan

### 1. CSV parsing for bulk endpoint

`FMPClient.fetch_raw()` calls `resp.json()`, which will fail on CSV responses. Options:
- **Option A**: Add a `response_format="csv"` parameter to `fetch_raw()` that uses `csv.DictReader` instead of `resp.json()`
- **Option B**: Bypass `FMPClient` entirely — use `requests.get()` directly in the collection script with CSV parsing

Prefer **Option A** for consistency, but **Option B** is acceptable since this is a one-off call per run, not a general-purpose fetch pattern.

### 2. Register endpoint in `fmp/registry.py`

Register `earnings_surprises_bulk` with:
- `path`: `/earnings-surprises-bulk`
- `api_version`: `v4`
- `params`: `year` (required, INTEGER)
- `response_type`: `csv` (new type, or handled via special flag)
- `cache_refresh`: `MONTHLY` (coverage list doesn't change within a month)

### 3. Add `_fetch_covered_universe()` in `snapshot_estimates.py`

```python
def _fetch_covered_universe(client: FMPClient) -> tuple[list[str], str]:
    """Fetch actively traded tickers with analyst coverage.

    Intersects the company screener (actively traded stocks) with the
    earnings-surprises-bulk endpoint (symbols with analyst coverage)
    to produce the optimal collection universe.

    Returns (universe, universe_source) where universe_source is "bulk" or "screener".
    Falls back to screener-only if bulk endpoint fails entirely.
    """
    # 1. Fetch screener universe (existing _fetch_universe)
    screener_symbols = set(_fetch_universe(client))

    # 2. Fetch bulk coverage list (current + prior year)
    current_year = datetime.now(timezone.utc).year
    covered_symbols = set()
    for year in [current_year, current_year - 1]:
        try:
            bulk_symbols = _fetch_bulk_earnings_symbols(client, year)
            covered_symbols.update(bulk_symbols)
        except Exception:
            print(f"Bulk endpoint failed for year={year}, continuing", file=sys.stderr)

    # 3. If bulk failed entirely, fall back to screener-only
    if not covered_symbols:
        print("Bulk coverage unavailable, falling back to screener universe", file=sys.stderr)
        return sorted(screener_symbols), "screener"

    # 4. Intersect
    universe = screener_symbols & covered_symbols
    return sorted(universe), "bulk"
```

### 4. Symbol normalization

FMP may return different symbol formats between endpoints (e.g. `BRK.B` vs `BRK-B`). Before intersection:
- Normalize symbols: strip whitespace, uppercase
- If needed, canonicalize separators (`.` vs `-`) — validate whether this is actually an issue by checking a few known cases (BRK.B, BF.B) in both screener and bulk responses

### 5. CLI flags

- `--universe-source bulk|screener` (default: `bulk`) — `bulk` uses intersection, `screener` uses screener-only (legacy behavior)
- `--bulk-years N` (default: 2) — how many years of bulk data to union for coverage

### 6. Run metadata: `universe_source` column

Add `universe_source TEXT` column to `snapshot_runs` table to record which method produced the universe for a given run. Canonical values:
- `bulk` — intersection of screener + bulk endpoint (default)
- `screener` — screener-only (used via `--universe-source screener` or as fallback when bulk endpoint fails entirely)
- `explicit` — user-provided via `--tickers`

This makes resumed runs transparent — you can tell what method was used.

Schema change (idempotent — safe to re-run):
```sql
ALTER TABLE snapshot_runs ADD COLUMN IF NOT EXISTS universe_source TEXT;
```

### 7. Newly covered tickers (coverage gap)

The bulk endpoint only contains symbols that have already reported earnings with analyst estimates. Tickers where coverage was just initiated (analyst started covering but no earnings surprise yet) will be missed.

Mitigation: **Periodic screener recheck**. Every N runs (e.g. quarterly), do a full screener run (`--universe-source screener`) to discover newly covered tickers. This catches:
- Newly initiated coverage (analyst starts covering a stock)
- IPOs that gained coverage after listing
- Tickers that crossed from bulk-only to the intersection

This is acceptable because:
- Newly initiated coverage is rare (a few tickers per month)
- Missing one month of snapshots for a newly covered ticker is low-impact
- The quarterly full-screener run catches up

### 8. Fallback behavior

**Total bulk failure** (both years fail — network error, 402 plan-limited, endpoint removed):
- Log the failure
- Fall back to screener-only universe
- Record `universe_source = "screener"` in run metadata
- Do NOT fail the entire run

**Partial bulk failure** (one year succeeds, one fails):
- Use the symbols from the successful year for intersection
- Log a warning that coverage may be incomplete
- Record `universe_source = "bulk"` (still an intersection, just with partial bulk data)
- This is acceptable because the two years heavily overlap — the prior year is mainly a safety net for tickers that haven't reported in the current year yet

### 9. Tests

- CSV parsing: mock CSV response, verify symbol extraction
- Intersection: verify screener ∩ bulk produces correct set
- Symbol normalization: verify case/whitespace handling, test separator edge cases
- Fallback: verify graceful degradation when bulk fails
- Run metadata: verify `universe_source` is persisted correctly

## Files to modify

| File | Change |
|---|---|
| `fmp/registry.py` | Register `earnings_surprises_bulk` endpoint |
| `fmp/client.py` | Add CSV response handling (if Option A) |
| `fmp/scripts/snapshot_estimates.py` | Add `_fetch_covered_universe()`, `_fetch_bulk_earnings_symbols()`, `--universe-source` flag, `--bulk-years` flag |
| `fmp/scripts/create_fmp_data_schema.sql` | Add `universe_source TEXT` to `snapshot_runs` |
| `fmp/estimate_store.py` | Accept `universe_source` in `create_run()` and `update_run()` |
| `tests/fmp/test_snapshot_estimates_script.py` | Tests for new universe logic |

## Expected API savings

| Scenario | Universe size | Calls per run |
|---|---|---|
| Current (screener-only) | 6,662 | ~20,000 (3 per ticker) |
| Bulk intersection | 4,911 | ~14,700 (3 per ticker) |
| Savings | -1,751 tickers | ~5,250 fewer calls (~26% reduction) |

The `income_statement` call is retained (needed for forward filtering), so savings come purely from eliminating tickers with no coverage.
