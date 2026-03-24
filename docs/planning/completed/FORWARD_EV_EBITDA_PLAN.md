# Replace TTM EV/EBITDA with Forward EV/EBITDA in Peer Comparison

## Context

The peer comparison table's EV/EBITDA (`enterpriseValueMultipleTTM`) is backward-looking. We already use forward P/E (FY1) and forward PEG (FY1). EV/EBITDA should follow the same pattern: Enterprise Value / FY1 consensus EBITDA estimate.

FMP provides `ebitdaAvg` in `analyst_estimates` (already fetched in `_fetch_ratios_and_estimates`). Enterprise value is in `ratios_ttm` (primary) and `key_metrics_ttm` (best-effort), both already fetched. No new API calls needed.

**Note**: FMP does NOT provide forward FCF estimates, so P/FCF stays TTM.

**No TTM fallback**: Same approach as forward PEG — if FY1 EBITDA estimate is unavailable, the cell shows "—". This is acceptable for peer comparison (large/mid-cap stocks with analyst coverage).

## Formula

```
Forward EV/EBITDA = enterpriseValueTTM / FY1 ebitdaAvg
```

Where FY1 is the first analyst estimate period after `last_reported_date`, same cutoff logic as `compute_forward_pe()`.

**Currency safety**: Computation happens BEFORE FX conversion in `_fetch_ratios_and_estimates()` (line ~206). At that point, both `enterpriseValueTTM` (from ratios_ttm) and `ebitdaAvg` (from analyst_estimates) are in the stock's reporting currency, so the ratio is currency-neutral.

## Changes

### 1. Backend: `utils/fmp_helpers.py` — extract shared helper + new function

**Extract** `_pick_fy1_estimate()` from `compute_forward_pe()` to eliminate duplication:

```python
def _pick_fy1_estimate(
    estimates: Any,
    last_reported_fiscal_date: str | None = None,
) -> dict | None:
    """Pick the first analyst estimate row after the last reported fiscal date.

    Returns the raw estimate dict for the FY1 period, or None.
    Shared by compute_forward_pe() and compute_forward_ev_ebitda().
    """
    # Parse cutoff (same logic as current compute_forward_pe lines 77-84)
    parsed_cutoff: date
    if last_reported_fiscal_date:
        try:
            parsed_cutoff = date.fromisoformat(str(last_reported_fiscal_date)[:10])
        except ValueError:
            parsed_cutoff = date.today()
    else:
        parsed_cutoff = date.today()

    # Normalize estimates: dict → [dict], list → filter dicts, else → []
    if isinstance(estimates, dict):
        estimate_rows = [estimates]
    elif isinstance(estimates, list):
        estimate_rows = [row for row in estimates if isinstance(row, dict)]
    else:
        estimate_rows = []

    # Parse dates and sort
    dated_rows = []
    for row in estimate_rows:
        raw_date = row.get("date")
        if not raw_date:
            continue
        try:
            fiscal_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        dated_rows.append((fiscal_date, row))

    # Return first future row
    for fiscal_date, row in sorted(dated_rows, key=lambda item: item[0]):
        if fiscal_date <= parsed_cutoff:
            continue
        return row

    return None
```

**Refactor** `compute_forward_pe()` to use `_pick_fy1_estimate()`:

```python
def compute_forward_pe(current_price, estimates, last_reported_fiscal_date=None):
    result = {"forward_pe": None, "ntm_eps": None, "pe_source": "unavailable", ...}

    price = parse_fmp_float(current_price)
    if price is None or price <= 0:
        return result

    fy1 = _pick_fy1_estimate(estimates, last_reported_fiscal_date)
    if fy1 is None:
        return result

    eps_avg = parse_fmp_float(fy1.get("epsAvg"))
    if eps_avg is None or eps_avg <= 0:
        return {**result, "pe_source": "negative_forward_earnings"}

    return {
        "forward_pe": round(price / eps_avg, 2),
        "ntm_eps": eps_avg,
        "pe_source": "forward",
        "analyst_count": fy1.get("numAnalystsEps"),
        "fiscal_period": str(fy1.get("date"))[:10],
    }
```

**Add** `compute_forward_ev_ebitda()`:

```python
def compute_forward_ev_ebitda(
    enterprise_value: Any,
    estimates: Any,
    last_reported_fiscal_date: str | None = None,
) -> float | None:
    """Compute FY1 forward EV/EBITDA. Returns float or None."""
    ev = parse_fmp_float(enterprise_value)
    if ev is None or ev <= 0:
        return None

    fy1 = _pick_fy1_estimate(estimates, last_reported_fiscal_date)
    if fy1 is None:
        return None

    ebitda_avg = parse_fmp_float(fy1.get("ebitdaAvg"))
    if ebitda_avg is None or ebitda_avg <= 0:
        return None

    return round(ev / ebitda_avg, 2)
```

**Why float|None instead of dict**: Only `peers.py` uses this, and it only needs the number. Unlike forward P/E (which serves stock_fundamentals too and needs source/analyst_count), EV/EBITDA is peer-comparison only.

### 2. Backend: `fmp/tools/peers.py`

**After line 200** where `merged["forwardPE"]` is set (BEFORE FX conversion at line ~206):

```python
merged["_computed_forward_ev_ebitda"] = compute_forward_ev_ebitda(
    merged.get("enterpriseValueTTM"),
    estimates,
    last_reported_date,
)
```

`enterpriseValueTTM` primarily comes from `ratios_ttm` (required fetch, line 107). Since `merged` is `{**metrics_dict, **income_dict, **ratios_dict}`, `ratios_dict` takes precedence. If `ratios_ttm` omits the field, it can fall back to `key_metrics_ttm` (best-effort) — this is acceptable since either source provides the same value.

**In `DEFAULT_PEER_METRICS`:**
```python
# Change:
"enterpriseValueMultipleTTM",
# To:
"_computed_forward_ev_ebitda",
```

**In `METRIC_LABELS`:**
```python
# Change:
"enterpriseValueMultipleTTM": "EV/EBITDA",
# To:
"_computed_forward_ev_ebitda": "EV/EBITDA (FY1)",
```

**Import**: Add `compute_forward_ev_ebitda` to the import from `utils.fmp_helpers`.

### 3. Frontend: `helpers.ts`

In `LOWER_IS_BETTER_METRICS`:
- Remove `enterpriseValueMultipleTTM`
- Add `_computed_forward_ev_ebitda`

In `NON_POSITIVE_EXCLUDES_RANKING`:
- Remove `enterpriseValueMultipleTTM`
- Add `_computed_forward_ev_ebitda`

### 4. Frontend: `PeerComparisonTab.tsx`

In `METRIC_GROUP`:
- Remove `enterpriseValueMultipleTTM: "Valuation"`
- Add `_computed_forward_ev_ebitda: "Valuation"`

### 5. Tests: `tests/utils/test_forward_pe.py`

Add tests for `compute_forward_ev_ebitda()` AND verify `compute_forward_pe()` refactor doesn't regress:

- `test_forward_ev_ebitda_happy_path`: valid EV + valid ebitdaAvg → correct ratio
- `test_forward_ev_ebitda_no_estimates`: None input → None
- `test_forward_ev_ebitda_negative_ebitda`: ebitdaAvg <= 0 → None
- `test_forward_ev_ebitda_negative_ev`: EV <= 0 → None
- `test_forward_ev_ebitda_all_before_cutoff`: all estimates before last_reported_date → None
- `test_forward_ev_ebitda_missing_ebitda_field`: FY1 row exists but no ebitdaAvg key → None
- Verify ALL existing `compute_forward_pe` tests still pass after refactor to `_pick_fy1_estimate`

### 6. Tests: `tests/mcp_tools/test_peers.py`

- Add `_computed_forward_ev_ebitda` assertion in `test_default_metrics_not_empty`
- Remove `enterpriseValueMultipleTTM` assertion from `test_default_metrics_not_empty`
- Update `test_summary_metric_labels`: `"EV/EBITDA"` → `"EV/EBITDA (FY1)"`
- Add `ebitdaAvg` to SAMPLE_ANALYST_ESTIMATES mock data for each ticker
- Add integration test: `test_forward_ev_ebitda_present_in_comparison` — verify `_computed_forward_ev_ebitda` row has expected values
- Add integration test: `test_forward_ev_ebitda_missing_estimates` — verify `None` in comparison row when analyst estimates fail (rendering "—" is frontend-side in `formatPeerMetricValue`)

### 7. Frontend test: `helpers.test.ts`

- Assert `_computed_forward_ev_ebitda` IN `LOWER_IS_BETTER_METRICS`
- Assert `_computed_forward_ev_ebitda` IN `NON_POSITIVE_EXCLUDES_RANKING`
- Assert `enterpriseValueMultipleTTM` NOT IN either set

## Edge Cases

- No analyst estimates → `None` → shows "—"
- Negative or zero EBITDA estimate → `None` → shows "—"
- Negative or zero EV → `None` → shows "—"
- EV unavailable (ratios_ttm failed → whole ticker fails, not just this metric)
- All estimate dates before cutoff → `None` → shows "—"
- FY1 row exists but `ebitdaAvg` key missing → `None` → shows "—"
- `format="full"` output: raw `enterpriseValueMultipleTTM` from ratios_ttm still present (it's in the raw data), plus `_computed_forward_ev_ebitda` — both visible. This is fine for full-format inspection. Add assertion in existing `test_full_format` to verify both keys present.

## What Does NOT Change

- Forward P/E — refactored to use `_pick_fy1_estimate()` but same behavior
- Forward PEG — unchanged
- FCF Margin — unchanged
- P/FCF (stays TTM — no FMP forward FCF data)
- FX conversion — ratio computed pre-conversion, currency-neutral

## Files to Modify

| File | Change |
|------|--------|
| `utils/fmp_helpers.py` | Extract `_pick_fy1_estimate()`, refactor `compute_forward_pe()`, add `compute_forward_ev_ebitda()` |
| `fmp/tools/peers.py` | Call new function, swap in DEFAULT_PEER_METRICS + METRIC_LABELS |
| `frontend/.../helpers.ts` | Swap metric key in LOWER_IS_BETTER + NON_POSITIVE sets |
| `frontend/.../PeerComparisonTab.tsx` | Swap metric key in METRIC_GROUP |
| `tests/utils/test_forward_pe.py` | Unit tests for `compute_forward_ev_ebitda()` + verify PE refactor |
| `tests/mcp_tools/test_peers.py` | Update mock data + assertions + integration tests |
| `frontend/.../helpers.test.ts` | Forward EV/EBITDA in metric sets |

## Verification

1. `pytest tests/utils/test_forward_pe.py -q` — all tests pass (existing + new)
2. `pytest tests/mcp_tools/test_peers.py -q` — all tests pass
3. Frontend tests pass
4. Browser: AAPL → vs Peers → "EV/EBITDA (FY1)" in Valuation section with forward values
5. Ranking correct (lower = better, non-positive excluded)
