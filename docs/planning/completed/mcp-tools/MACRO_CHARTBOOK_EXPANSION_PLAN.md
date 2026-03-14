# Macro Chart Book Expansion — 5 New Market Sections

## Context

The base chart book (`3066c774`) has 6 sections (market snapshot, economic dashboard, sectors, technicals, movers, events). We tested FMP data availability and confirmed 5 additional market-view sections are feasible. Market breadth is not available from FMP — deferred.

## New Sections

### 7. Yield Curve
- **Data**: `FMPClient().fetch("treasury_rates", from=..., to=...)` — returns columns: month1, month2, month3, month6, year1, year2, ..., year30
- **Charts**:
  - Current yield curve: scatter+line of today's rates across maturities (x=maturity, y=rate)
  - Historical overlay: today vs 1 month ago vs 3 months ago vs 1 year ago (4 lines)
- **File**: `scripts/chartbook/charts_yield_curve.py`

### 8. Volatility
- **Data**: `FMPClient().fetch("historical_price_adjusted", symbol="^VIX", from=...)` — adjClose column
- **Charts**:
  - VIX line chart (1 year history)
  - Horizontal bands at 12 (low), 20 (moderate), 30 (high) for context
- **File**: `scripts/chartbook/charts_volatility.py`

### 9. Factor Performance
- **Data**: `historical_price_adjusted` for proxy ETFs: IWF (growth), IWD (value), MTUM (momentum), QUAL (quality), IWM (size), SPY (benchmark)
- **Charts**:
  - YTD cumulative return lines (all 5 factors + SPY benchmark, rebased to 0%)
  - Bar chart: MTD or 1M return comparison across factors
- **File**: `scripts/chartbook/charts_factors.py`

### 10. Currency & Commodities
- **Data**: `historical_price_adjusted` for DX-Y.NYB (DXY), GCUSD (gold), CLUSD (oil), BTCUSD (bitcoin)
- **Charts**:
  - 2×2 subplot grid: each asset gets a 6-month price line chart
  - Or single overlay chart with normalized returns (rebased to 100)
- **File**: `scripts/chartbook/charts_commodities.py`

### 11. Intermarket Analysis
- **Data**: `historical_price_adjusted` for SPY, TLT, GLD, USO
- **Charts**:
  - Normalized performance lines (rebased to 100) over 6 months — shows relative rotation
  - Correlation heatmap or relative strength bars (optional, if simple to compute)
- **File**: `scripts/chartbook/charts_intermarket.py`

## Data Fetcher Changes (`data_fetcher.py`)

Add new `_safe_fetch_df()` wrapper alongside existing `_safe_call()`. The existing `_safe_call()` expects dict responses (from FMP tool functions). New sections use `FMPClient().fetch()` which returns DataFrame — different contract.

```python
def _safe_fetch_df(endpoint: str, **kwargs) -> Optional[pd.DataFrame]:
    """Fetch from FMPClient, return DataFrame or None on failure."""
    try:
        df = FMPClient().fetch(endpoint, **kwargs)
        if df is None or df.empty:
            return None
        return df.sort_values("date").reset_index(drop=True)
    except Exception as exc:
        print(f"[chartbook] {endpoint} fetch failed: {exc}", file=sys.stderr)
        return None
```

**FMP keyword param**: `from` is a Python keyword — use `**{"from": date_str, "to": today_str}` syntax.

**Always pass `to=today`**: Prevents stale cached data from HASH_ONLY endpoints.

**Price column fallback**: Use `adjClose` with fallback to `close` if missing.

Add to `fetch_chartbook_data()`:

```
New data keys:
  "treasury_rates"  — _safe_fetch_df("treasury_rates", **{"from": 1yr_ago, "to": today})
  "vix"             — _safe_fetch_df("historical_price_adjusted", symbol="^VIX", **{"from": 1yr_ago, "to": today})
  "price_histories" — {symbol: df} for all unique symbols (SPY, IWF, IWD, MTUM, QUAL, IWM, TLT, GLD, USO, DX-Y.NYB, GCUSD, CLUSD, BTCUSD)
```

**SPY dedup + window**: Fetch ALL price histories with the superset window (YTD or 1 year, whichever is longer). Chart builders slice to their needed range. This avoids fetching SPY twice and handles the YTD-vs-6M mismatch.

**Parallelization**: New fetches are pure HTTP→DataFrame (no internal fan-out). Use a separate `ThreadPoolExecutor` block for the ~13 price history calls + 1 treasury + 1 VIX = 15 parallel calls. `max_workers=6` to stay under FMP rate limits.

Chart builders receive pre-sliced dicts:
```python
bundle["factor_etfs"] = {sym: bundle["price_histories"][sym] for sym in FACTOR_SYMBOLS}
bundle["commodities"] = {sym: bundle["price_histories"][sym] for sym in COMMODITY_SYMBOLS}
bundle["intermarket"] = {sym: bundle["price_histories"][sym] for sym in INTERMARKET_SYMBOLS}
```

## Entry Point Changes (`macro_chartbook.py`)

Add 5 new sections to the `sections` list:

```python
("Yield Curve", build_yield_curve_section(data.get("treasury_rates"))),
("Volatility", build_volatility_section(data.get("vix"))),
("Factor Performance", build_factors_section(data.get("factor_etfs"))),
("Currency & Commodities", build_commodities_section(data.get("commodities"))),
("Intermarket Analysis", build_intermarket_section(data.get("intermarket"))),
```

## Files to Create/Modify

| File | Action |
|------|--------|
| `scripts/chartbook/charts_yield_curve.py` | NEW — yield curve line charts |
| `scripts/chartbook/charts_volatility.py` | NEW — VIX line chart |
| `scripts/chartbook/charts_factors.py` | NEW — factor ETF performance |
| `scripts/chartbook/charts_commodities.py` | NEW — DXY/gold/oil/BTC |
| `scripts/chartbook/charts_intermarket.py` | NEW — relative performance |
| `scripts/chartbook/data_fetcher.py` | EDIT — add 5 new data fetches |
| `scripts/macro_chartbook.py` | EDIT — add 5 new sections + imports |

## Key Implementation Notes

- **FMPClient direct**: New sections use `FMPClient().fetch()` directly (returns DataFrame), not the higher-level tool functions. This is simpler for raw price data.
- **New `_safe_fetch_df()` wrapper**: Separate from `_safe_call()` which expects dict. Returns `DataFrame | None`, sorts by date, logs failures to stderr.
- **Date ranges**: Treasury/VIX = 1 year. Factors = YTD. Commodities/intermarket = 6 months. All price histories fetched with superset window; chart builders slice.
- **Price column**: Use `adjClose` with fallback to `close` column. Coerce to numeric.
- **Return computation**: `(price / price_first - 1) * 100` for cumulative %. Sort by date ascending before rebasing.
- **Same chart patterns**: `_warning()`, `_to_float()`, `plotly_dark` template, `pio.to_html(fig, full_html=False, include_plotlyjs=False)`
- **Error handling**: `_safe_fetch_df()` for DataFrame fetches. Each chart builder handles `None`/empty data gracefully with placeholder HTML.
- **Yield curve**: Tolerate missing maturities (some rows may have null for month2 etc.).
- **Weekend handling**: BTC trades 7 days/week; equity/commodity symbols are weekday-only. Intermarket section should align on common dates via inner join.

## Verification

1. `python3 scripts/macro_chartbook.py` — all 11 sections render
2. Open HTML, verify new sections have interactive charts
3. Check yield curve shape makes sense (short < long rates normally)
4. Check factor lines are rebased to 0% at start
5. Check VIX has context bands at 12/20/30

## Status: COMPLETE (2026-03-06)

All 5 new sections implemented and verified in browser. Additional fixes applied:
- Responsive charts: `config={"responsive": True}` on all `pio.to_html()` calls
- Layout fix: Yield curve and factor performance sections use stacked layout (not side-by-side grid) to prevent horizontal scrolling with many x-axis categories
- CSS: `overflow-x: hidden` on subsections, `min(380px, 100%)` grid minimum, forced `width: 100%` on plotly divs
