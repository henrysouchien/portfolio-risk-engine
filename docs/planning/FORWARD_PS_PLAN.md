# Replace TTM P/S with Forward EV/Sales in Peer Comparison

## Context

The peer comparison table's P/S ratio (`priceToSalesRatioTTM`) is backward-looking and equity-only. EV/Sales is a better comp metric — capital-structure neutral, accounts for debt and cash. We already use forward EV/EBITDA (FY1), so forward EV/Sales follows the same pattern.

FMP provides `revenueAvg` in `analyst_estimates` (already fetched). `enterpriseValueTTM` is already in the merged dict from ratios_ttm/key_metrics_ttm. No new API calls needed.

## Formula

```
Forward EV/Sales = enterpriseValueTTM / FY1 revenueAvg
```

Where FY1 is the first analyst estimate period after `last_reported_date`, using existing `_pick_fy1_estimate()` helper. Same computation pattern as `compute_forward_ev_ebitda()`.

**Currency safety**: Computed BEFORE FX conversion in `_fetch_ratios_and_estimates()`. Both `enterpriseValueTTM` and `revenueAvg` are in reporting currency at that point — ratio is currency-neutral.

## Changes

### 1. Backend: `utils/fmp_helpers.py` — new function

Add `compute_forward_ev_sales()` using `_pick_fy1_estimate()`:

```python
def compute_forward_ev_sales(
    enterprise_value: Any,
    estimates: Any,
    last_reported_fiscal_date: str | None = None,
) -> float | None:
    """Compute FY1 forward EV/Sales from analyst revenue estimates."""
    ev = parse_fmp_float(enterprise_value)
    if ev is None or ev <= 0:
        return None

    fy1 = _pick_fy1_estimate(estimates, last_reported_fiscal_date)
    if fy1 is None:
        return None

    revenue_avg = parse_fmp_float(fy1.get("revenueAvg"))
    if revenue_avg is None or revenue_avg <= 0:
        return None

    return round(ev / revenue_avg, 2)
```

Returns float|None (same pattern as `compute_forward_ev_ebitda()`).

### 2. Backend: `fmp/tools/peers.py`

**Compute forward EV/Sales** after the `_computed_forward_ev_ebitda` line, before FX conversion:

```python
merged["_computed_forward_ev_sales"] = compute_forward_ev_sales(
    merged.get("enterpriseValueTTM"),
    estimates,
    last_reported_date,
)
```

Uses same `enterpriseValueTTM` from merged dict as forward EV/EBITDA.

**In `DEFAULT_PEER_METRICS`:**
```python
# Change:
"priceToSalesRatioTTM",
# To:
"_computed_forward_ev_sales",
```

**In `METRIC_LABELS`:**
```python
# Change:
"priceToSalesRatioTTM": "P/S Ratio",
# To:
"_computed_forward_ev_sales": "EV/Sales (FY1)",
```

**Import**: Add `compute_forward_ev_sales` to the import from `utils.fmp_helpers`.

### 3. Frontend: `helpers.ts`

In `LOWER_IS_BETTER_METRICS`:
- Remove `priceToSalesRatioTTM`
- Add `_computed_forward_ev_sales`

In `NON_POSITIVE_EXCLUDES_RANKING`:
- Remove `priceToSalesRatioTTM`
- Add `_computed_forward_ev_sales`

### 4. Frontend: `PeerComparisonTab.tsx`

In `METRIC_GROUP`:
- Remove `priceToSalesRatioTTM: "Valuation"`
- Add `_computed_forward_ev_sales: "Valuation"`

### 5. Tests: `tests/utils/test_forward_pe.py`

Add tests for `compute_forward_ev_sales()`:
- Happy path: valid EV + valid revenueAvg → correct ratio
- No estimates → None
- Negative revenue estimate → None
- EV is None or ≤ 0 → None
- All estimates before cutoff → None

### 6. Tests: `tests/mcp_tools/test_peers.py`

- Add `revenueAvg` to SAMPLE_ANALYST_ESTIMATES mock data for each ticker
- Add `_computed_forward_ev_sales` assertion in `test_default_metrics_not_empty`
- Remove `priceToSalesRatioTTM` assertion from `test_default_metrics_not_empty`
- Add `"EV/Sales (FY1)"` to `test_summary_metric_labels` assertions (no existing `"P/S Ratio"` assertion to replace — just add the new one)
- Add integration test: verify `_computed_forward_ev_sales` row has expected values
- Add full-format assertion for both raw `priceToSalesRatioTTM` and `_computed_forward_ev_sales`
- Add `_computed_forward_ev_sales` assertions to existing degradation tests:
  - **key_metrics failure**: forward EV/Sales should still be present (EV comes from ratios_ttm which is required, not key_metrics_ttm)
  - **income_statement failure**: forward EV/Sales may still compute if estimates and EV are available (income_statement failure only drops revenue/ebitda actuals and last_reported_date — without last_reported_date, `_pick_fy1_estimate` falls back to `date.today()` as cutoff, so estimates with future dates still work)
  - **analyst_estimates failure**: forward EV/Sales should be `None` (no estimates → no FY1 revenue)
- Use fixed future dates (e.g., "2030-12-31") in test estimate fixtures to avoid clock-sensitivity from `_pick_fy1_estimate()`'s `date.today()` fallback
- Add FX-path assertion: verify `_computed_forward_ev_sales` is NOT converted by FX (it's a ratio, not in ABSOLUTE_METRICS). Add to `test_non_usd_absolute_metrics_are_converted_at_end_and_fcf_margin_is_unchanged` — assert computed EV/Sales value is unchanged after FX conversion

### 7. Frontend test: `helpers.test.ts`

- Assert `_computed_forward_ev_sales` IN `LOWER_IS_BETTER_METRICS`
- Assert `_computed_forward_ev_sales` IN `NON_POSITIVE_EXCLUDES_RANKING`
- Assert `priceToSalesRatioTTM` NOT IN either set

## Edge Cases

- No analyst estimates → None → shows "—"
- Negative or zero revenue estimate → None → shows "—"
- EV unavailable or ≤ 0 → None → shows "—"
- All estimate dates before cutoff → None → shows "—"
- `format="full"` output: raw `priceToSalesRatioTTM` still present plus `_computed_forward_ev_sales`

## What Does NOT Change

- Forward P/E — unchanged
- Forward PEG — unchanged
- Forward EV/EBITDA — unchanged
- FCF Margin — unchanged
- P/FCF (stays TTM)
- FX conversion — ratio is currency-neutral

## Files to Modify

| File | Change |
|------|--------|
| `utils/fmp_helpers.py` | Add `compute_forward_ev_sales()` |
| `fmp/tools/peers.py` | Call new function, swap in DEFAULT_PEER_METRICS + METRIC_LABELS |
| `frontend/.../helpers.ts` | Swap metric key in LOWER_IS_BETTER + NON_POSITIVE sets |
| `frontend/.../PeerComparisonTab.tsx` | Swap metric key in METRIC_GROUP |
| `tests/utils/test_forward_pe.py` | Unit tests for `compute_forward_ev_sales()` |
| `tests/mcp_tools/test_peers.py` | Update mock data + assertions + integration tests |
| `frontend/.../helpers.test.ts` | Forward EV/Sales in metric sets |

## Verification

1. `pytest tests/utils/test_forward_pe.py -q` — all tests pass
2. `pytest tests/mcp_tools/test_peers.py -q` — all tests pass
3. Frontend tests pass
4. Browser: AAPL → vs Peers → "EV/Sales (FY1)" in Valuation section
5. Ranking correct (lower = better, non-positive excluded)
