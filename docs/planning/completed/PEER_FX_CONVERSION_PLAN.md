# Fix Foreign Currency Absolute Metrics in Peer Comparison

## Context

FMP returns absolute metrics (Revenue, EBITDA, Enterprise Value) in the company's **reported currency**. For SSNLF (Samsung), that's KRW, showing $333.6T revenue instead of ~$222B. Ratios (P/E, margins) are currency-neutral and unaffected.

## Approach

Convert absolute metrics to USD **at the end of `_fetch_ratios()`**, after all computations (including FCF Margin) are done on raw local-currency values. Use the existing `fmp.fx.get_spot_fx_rate()` which handles normalization, currency aliases (GBp→GBP), inversion, fallback, and has LRU caching.

## Changes — Backend Only

**`fmp/tools/peers.py` — `_fetch_ratios()`**

After the merge step (where all raw fields are assembled and `_computed_fcf_margin` is already computed), add a final conversion block:

```python
# === Final step: convert absolute metrics to USD ===
# Only after all computations (FCF margin uses raw values in same currency)
ABSOLUTE_METRICS = {"_annual_revenue", "_annual_ebitda", "enterpriseValueTTM", "freeCashFlowPerShareTTM"}

reported_currency = None
# Get currency from income_statement response (stored earlier)
if income_row is not None:
    reported_currency = income_row.get("reportedCurrency")

if reported_currency and reported_currency != "USD":
    from fmp.fx import get_spot_fx_rate
    fx_rate = get_spot_fx_rate(reported_currency)  # Returns currency→USD rate
    # get_spot_fx_rate returns 1.0 on failure (built-in fallback)

    if fx_rate != 1.0:
        for key in ABSOLUTE_METRICS:
            if key in merged and merged[key] is not None:
                try:
                    merged[key] = float(merged[key]) * fx_rate
                except (TypeError, ValueError):
                    pass

return (ticker, merged, None)
```

### Implementation detail: preserving the income_statement row

The current code extracts `_annual_revenue` and `_annual_ebitda` from the income_statement row into `income_dict`, then discards the row. To access `reportedCurrency` later, store the row reference:

```python
income_row = None  # Set at top of function
# ... in income_statement block:
income_row = row  # Keep reference for currency detection
```

### Key Design Decisions

- **Convert at the end**: FCF Margin is computed from `freeCashFlow / revenue` — both in local currency, so the ratio is correct. Converting Revenue first would break this.
- **Use existing `get_spot_fx_rate()`**: `fmp/fx.py:257` — handles `GBp`/`GBX` aliases, pair inversion, LRU caching (keyed by date), and returns 1.0 on failure. No need to reinvent.
- **`get_spot_fx_rate()` returns currency→USD multiplier**: multiply raw values by this rate (e.g., KRW value × 0.000664 = USD).
- **Include `freeCashFlowPerShareTTM`**: It's a monetary per-share value in local currency. Converting it keeps the Scale/Returns sections fully in USD. No mixed-units.
- **If `income_statement` fails**: No `reportedCurrency` available → no conversion attempted. EV stays in local currency. This is the correct behavior — we can't guess the currency.
- **If FX fetch fails**: `get_spot_fx_rate()` returns 1.0 → no conversion. Values stay in local currency. Frontend shows them with `$` prefix which is technically wrong, but better than hiding data. This is the existing fallback behavior in `fmp/fx.py`.

### What About EV?

`enterpriseValueTTM` is market-derived (market cap + debt - cash). FMP computes it from financial statements which are in reported currency. Verified: SSNLF's EV is 1304T (KRW), AAPL's is 3.7T (USD). The ratio is ~353x which matches USDKRW ~1505 × relative size difference. Converting with `reportedCurrency` from `income_statement` is correct because EV components (debt, cash) come from the same currency financial statements.

## Files to Modify

| File | Change |
|------|--------|
| `fmp/tools/peers.py` | Add FX conversion block at end of `_fetch_ratios()` |

## What Does NOT Change

- `fmp/fx.py` — unchanged, using existing `get_spot_fx_rate()`
- Frontend — unchanged
- Ratios/margins — unaffected (currency-neutral)
- `_computed_fcf_margin` — unaffected (computed before conversion from same-currency values)

## Tests

Add to `tests/mcp_tools/test_peers.py`:
- Non-USD ticker with `reportedCurrency: "KRW"` and mocked FX rate → absolute metrics multiplied by rate
- USD ticker → no conversion
- Missing `reportedCurrency` (income_statement failed) → no conversion
- `get_spot_fx_rate` returns 1.0 (FX failure) → no conversion
- `_computed_fcf_margin` unchanged regardless of currency (computed before conversion)
- `freeCashFlowPerShareTTM` converted alongside other absolute metrics

## Verification

1. `pytest tests/mcp_tools/test_peers.py -q` — passes including new FX tests
2. Browser: Research → AAPL → vs Peers → SSNLF Revenue ~$222B (not $333T)
3. SSNLF EBITDA ~$60B, EV ~$867B
4. AAPL and other USD peers unchanged
5. Margins/ratios for SSNLF unchanged
6. FCF Margin for SSNLF correct (computed from same-currency values before conversion)
