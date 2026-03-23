# Add Forward Valuation Metrics to get_stock_fundamentals

## Context

The `get_stock_fundamentals` MCP tool (fmp-mcp) already computes forward P/E but uses TTM for PEG and EV/EBITDA, and doesn't have EV/Sales. All required data is already fetched — analyst_estimates, key_metrics_ttm, ratios_ttm. Just needs wiring to the existing helper functions.

**Scope**: `fmp/tools/stock_fundamentals.py` only. Peer comparison (`fmp/tools/peers.py`) and `analyze_stock` (`mcp_tools/stock.py`) are unaffected.

## Changes

### 1. `fmp/tools/stock_fundamentals.py` — compute forward metrics

**At line ~758** where `forward_pe_result` is computed, also compute forward EV/EBITDA and EV/Sales:

```python
# After forward_pe_result computation (line 762-766):
forward_ev_ebitda = None
forward_ev_sales = None
if "valuation" in requested_sections:
    # Source EV from ratios first (required fetch), fall back to key_metrics (best-effort)
    ratios_row = _first_record(raw_results.get("ratios"))
    key_metrics_row = _first_record(raw_results.get("key_metrics"))
    ev = parse_fmp_float(_pick_value(ratios_row, "enterpriseValueTTM")) if ratios_row else None
    if ev is None and key_metrics_row:
        ev = parse_fmp_float(_pick_value(key_metrics_row, "enterpriseValueTTM"))

    last_reported = raw_results.get("last_reported_fiscal_date")
    forward_ev_ebitda = compute_forward_ev_ebitda(ev, estimates, last_reported)
    forward_ev_sales = compute_forward_ev_sales(ev, estimates, last_reported)
```

`estimates` and `last_reported_fiscal_date` are already in scope from the forward P/E block (line 761, 765). EV sourced from `ratios_ttm` first (required fetch, line 678), `key_metrics_ttm` fallback (best-effort) — matches the existing TTM EV/EBITDA sourcing pattern in `_build_valuation()`.

**Pass to `_build_valuation()`** — add `forward_ev_ebitda` and `forward_ev_sales` as parameters:

```python
section_data, builder_warnings = _build_valuation(
    raw_results.get("ratios"),
    raw_results.get("key_metrics"),
    forward_pe_result,
    sector_pe,
    forward_ev_ebitda,   # NEW
    forward_ev_sales,    # NEW
)
```

**Import**: Add `compute_forward_ev_ebitda`, `compute_forward_ev_sales` to the import from `utils.fmp_helpers`.

### 2. `fmp/tools/stock_fundamentals.py` — update `_build_valuation()`

**Signature**: Add `forward_ev_ebitda: float | None = None` and `forward_ev_sales: float | None = None` parameters.

**Forward EV/EBITDA** — replace TTM with forward, keep TTM as fallback:

```python
# Replace lines 301-313:
if forward_ev_ebitda is not None:
    section["ev_ebitda"] = forward_ev_ebitda
    section["ev_ebitda_source"] = "FY1"
else:
    ev_ebitda_ttm = _parse_metric(ratios_row, "enterpriseValueMultipleTTM", "evToEbitdaTTM")
    if ev_ebitda_ttm is None and key_metrics_row:
        ev_ebitda_ttm = _parse_metric(key_metrics_row, "enterpriseValueMultipleTTM", "evToEbitdaTTM")
    if ev_ebitda_ttm is not None:
        section["ev_ebitda"] = ev_ebitda_ttm
        section["ev_ebitda_source"] = "ttm"
```

**Forward EV/Sales** — new field with TTM fallback (`priceToSalesRatioTTM` available in ratios_ttm):

```python
if forward_ev_sales is not None:
    section["ev_sales"] = forward_ev_sales
    section["ev_sales_source"] = "FY1"
else:
    ev_sales_ttm = _parse_metric(ratios_row, "priceToSalesRatioTTM")
    if ev_sales_ttm is not None:
        section["ev_sales"] = ev_sales_ttm
        section["ev_sales_source"] = "ttm"
```

Note: TTM fallback uses `priceToSalesRatioTTM` (P/S, not EV/Sales) since FMP doesn't provide a TTM EV/Sales field. This is an acceptable approximation — the `_source` field makes it transparent.

**Forward PEG** — swap to forward field, keep TTM fallback:

```python
# Replace lines 285-299:
forward_peg = _parse_metric(ratios_row, "forwardPriceToEarningsGrowthRatioTTM")
if forward_peg is None and key_metrics_row:
    forward_peg = _parse_metric(key_metrics_row, "forwardPriceToEarningsGrowthRatioTTM")
if forward_peg is not None:
    section["peg_ratio"] = forward_peg
    section["peg_source"] = "FY1"
else:
    ttm_peg = _parse_metric(ratios_row, "priceToEarningsGrowthRatioTTM", "pegRatioTTM", "pegRatio")
    if ttm_peg is None and key_metrics_row:
        ttm_peg = _parse_metric(key_metrics_row, "priceToEarningsGrowthRatioTTM", "pegRatioTTM", "pegRatio")
    if ttm_peg is not None:
        section["peg_ratio"] = ttm_peg
        section["peg_source"] = "ttm"
```

### 3. Tests

**In `tests/mcp_tools/test_stock_fundamentals.py`**:
- Add `enterpriseValueTTM` to ratios/key_metrics mock fixtures
- Add `ebitdaAvg`, `revenueAvg` to analyst_estimates mock fixtures
- Add `forwardPriceToEarningsGrowthRatioTTM` to ratios mock fixtures
- Verify valuation section includes `ev_ebitda` with forward value + `ev_ebitda_source: "FY1"`
- Verify `ev_sales` present with forward value + `ev_sales_source: "FY1"`
- Verify `peg_ratio` uses forward field + `peg_source: "FY1"`
- Verify TTM fallback when estimates missing (source fields show "ttm")
- Verify `*_source` fields reflect correct source

**In `tests/utils/test_forward_pe.py`**:
- No new tests needed — `compute_forward_ev_ebitda` and `compute_forward_ev_sales` already tested

## Edge Cases

- No analyst estimates → forward EV/EBITDA, EV/Sales, PEG all fall back to TTM (or None if TTM also unavailable)
- key_metrics_ttm failed → `enterpriseValueTTM` unavailable → forward EV/EBITDA and EV/Sales are None, fall back to TTM EV/EBITDA
- Forward PEG unavailable in ratios_ttm → falls back to TTM PEG
- `include` doesn't include "valuation" → none of this runs (existing gate at line 668/758)

## What Does NOT Change

- Forward P/E — unchanged (already forward)
- P/B ratio, P/FCF, dividend yield — stay TTM
- Profile, quote, profitability, balance_sheet, quality, technicals, chart sections — unchanged
- Peer comparison tool — unchanged (has its own forward metrics path)
- `analyze_stock` MCP tool — unchanged

## Files to Modify

| File | Change |
|------|--------|
| `fmp/tools/stock_fundamentals.py` | Compute forward metrics, update `_build_valuation()` signature + body |
| Tests for stock_fundamentals | Verify forward metrics in valuation output |

## Verification

1. Existing tests pass
2. MCP tool: `get_stock_fundamentals(symbol="AAPL", include=["valuation"])` → `ev_ebitda` has FY1 value, `ev_sales` present, `peg_ratio` uses forward
3. MCP tool: stock without analyst coverage → TTM fallbacks work
