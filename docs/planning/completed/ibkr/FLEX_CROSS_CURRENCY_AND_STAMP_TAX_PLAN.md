# Plan: Flex Cross-Currency Dedup Fix + UK Stamp Tax Verification

**Priority:** Low (data correctness, ~$20 combined impact)
**Added:** 2026-03-07
**Extracted from:** `DUAL_CASH_ANCHOR_PLAN.md` Fix 5a/5b

## Fix A: Cross-Currency Dedup Drops Distinct HKD Interest (-$9.44)

### Problem

The Flex normalizer has a cross-currency dedup (Pass 2) in both `normalize_flex_cash_income_trades()` (line ~821) and `normalize_flex_cash_rows()` (line ~1176). It groups rows by `(date, symbol, type)` — ignoring currency — then keeps only base-currency (USD) rows when duplicates exist.

This correctly handles IBKR's pattern of reporting the same event in both local and base currency (e.g., HKD -30,000 and USD -$3,885 for the same margin interest charge). But it also incorrectly drops **distinct** charges that happen to share the same `(date, symbol, type)` key.

Example: If USD margin interest is -$50 and HKD margin interest is -$9.44 (a separate charge on HKD margin balance), the HKD row gets dropped because it shares the key `(2025-06-03, MARGIN_INTEREST, INTEREST)` with the USD row.

### Root Cause

The dedup has no way to distinguish "same event in two currencies" from "two distinct events in different currencies". It blindly keeps base-currency rows and drops everything else.

### Fix

Use `fxRateToBase` from the Flex CashTransaction XML to compute **signed** base-currency equivalents. Cluster rows by signed base amount — rows within tolerance are true duplicates (keep only the base-currency representative); rows that don't match any cluster are distinct charges (keep all).

**Signed amounts are critical:** A +$5 interest credit and a -$5 interest charge with the same absolute value must NOT be collapsed. Using signed base amounts prevents opposite-sign collapse.

`fxRateToBase` is a standard IBKR Flex attribute on CashTransaction rows. ib_async preserves all XML attributes via `node.attrib`, so it's accessible as `row.get("fxRateToBase")`.

### Implementation

**File: `ibkr/flex.py`**

**a) Store `fxRateToBase` on normalized rows:**

Income path — add to normalized dict in `normalize_flex_cash_income_trades()` (line ~780, after `"_institution": "ibkr"`):
```python
"fx_rate_to_base": safe_float(row.get("fxRateToBase"), 0.0),
```

Flow/fee path — add to `_normalize_cash_transaction_row()` return dict (line ~1112, after `"section": ...`):
```python
"fx_rate_to_base": safe_float(raw_row.get("fxRateToBase"), 0.0),
```

Note: Uses `safe_float(value, 0.0)` (from `ibkr/_vendor.py`), NOT `_parse_cash_amount(..., default=None)` which doesn't support None default. Zero means "no FX data available".

**b) Extract shared helper:**

```python
def _cross_currency_dedup(
    grouped_rows: list[dict[str, Any]],
    normalized_base_currency: str,
) -> list[dict[str, Any]]:
    """Deduplicate cross-currency rows, keeping distinct charges.

    True duplicates (same event in local + base currency) are collapsed
    to the base-currency row. Distinct charges (different base-currency
    amounts) are all kept.

    Uses pairwise clustering by SIGNED base-currency equivalent. Only
    activates when ALL rows have usable fxRateToBase; otherwise falls
    back to legacy behavior (keep base-currency rows).

    Signed amounts prevent opposite-sign collapse (e.g., +$5 credit and
    -$5 charge with the same absolute value are distinct events).
    """
    if len(grouped_rows) <= 1:
        return list(grouped_rows)

    currencies = {_normalize_flex_currency(row.get("currency")) for row in grouped_rows}
    if len(currencies) <= 1:
        return list(grouped_rows)

    base_currency_rows = [
        row for row in grouped_rows
        if _normalize_flex_currency(row.get("currency")) == normalized_base_currency
    ]

    # Compute SIGNED base-currency equivalent for each row.
    # fx_rate_to_base was stored during normalization via safe_float(, 0.0).
    base_equivalents: list[tuple[int, float]] = []  # (index, signed_base_amount)
    all_have_fx = True
    for i, row in enumerate(grouped_rows):
        fx = safe_float(row.get("fx_rate_to_base"), 0.0)
        if fx == 0.0:
            all_have_fx = False
            break
        raw_amount = _parse_cash_amount(row.get("amount"), default=0.0)
        base_equivalents.append((i, raw_amount * fx))  # SIGNED, not abs()

    if not all_have_fx:
        # Partial or missing FX data — fall back to legacy behavior.
        # Keep base-currency rows if available, else keep all.
        if base_currency_rows:
            return base_currency_rows
        return list(grouped_rows)

    # Sort base_equivalents by signed amount for deterministic clustering
    # regardless of input row order.
    base_equivalents.sort(key=lambda x: x[1])

    # Cluster rows by signed base-currency equivalent.
    # Fixed $0.10 tolerance — no relative component.
    # IBKR FX rounding errors are empirically < $0.10 (verified against
    # live Flex data: USD -$3885.37 vs HKD base equivalent -$3885.30,
    # difference $0.07). A relative term would create a $19+ window on
    # large amounts, collapsing legitimately distinct charges.
    TOLERANCE = 0.10

    clusters: list[list[int]] = []  # list of (original index) lists
    cluster_amounts: list[float] = []  # representative amount per cluster
    for idx, base_amt in base_equivalents:
        matched = False
        for ci, cluster in enumerate(clusters):
            ref_amt = cluster_amounts[ci]
            if abs(base_amt - ref_amt) < TOLERANCE:
                cluster.append(idx)
                matched = True
                break
        if not matched:
            clusters.append([idx])
            cluster_amounts.append(base_amt)

    if len(clusters) == 1:
        # All rows are true duplicates — keep base-currency rows (existing behavior)
        if base_currency_rows:
            return base_currency_rows
        return list(grouped_rows)

    # Multiple clusters = distinct charges exist.
    # For each cluster: keep ALL base-currency rows in that cluster.
    # If no base-currency row exists in a cluster, keep ALL non-base rows.
    #
    # Why keep all base-currency rows (not just one)?
    # Pass 1 (segment dedup) already collapsed same-currency same-amount
    # duplicates. If two base-currency rows survive Pass 1 into the same
    # cluster, they represent genuinely different events (e.g., two separate
    # USD charges with slightly different amounts that cluster together).
    # Dropping one would lose a real event.
    result: list[dict[str, Any]] = []
    for cluster in clusters:
        cluster_rows = [grouped_rows[i] for i in cluster]
        base_in_cluster = [
            row for row in cluster_rows
            if _normalize_flex_currency(row.get("currency")) == normalized_base_currency
        ]
        if base_in_cluster:
            result.extend(base_in_cluster)
        else:
            # No base-currency row — keep all non-base rows in cluster
            result.extend(cluster_rows)
    return result
```

**c) Replace inline dedup blocks with helper call:**

Income path — replace lines 833-853 in `normalize_flex_cash_income_trades()`:
```python
normalized = []
for grouped_rows in cross_currency_grouped.values():
    normalized.extend(
        _cross_currency_dedup(grouped_rows, normalized_base_currency)
    )
```

Flow/fee path — replace lines 1188-1208 in `normalize_flex_cash_rows()`:
```python
normalized = []
for grouped_rows in cross_currency_grouped.values():
    normalized.extend(
        _cross_currency_dedup(grouped_rows, normalized_base_currency)
    )
```

### Edge Cases

1. **`fxRateToBase` missing/zero on ANY row:** `all_have_fx = False` → falls back to legacy behavior (keep base-currency rows). No regression with existing tests.
2. **Base-currency row has `fxRateToBase=1.0`:** Correctly computes `amount * 1.0 = amount`. Works.
3. **Multiple non-base currencies (HKD + GBP, no USD):** If FX data shows distinct amounts, all kept via separate clusters. If no FX data, existing behavior (keep all when no base-currency match).
4. **Same base-equivalent amounts from different currencies:** Single cluster → collapsed to base-currency row (correct — true duplicate).
5. **3-row mixed group (USD -$50, HKD -$73.75 @ 0.128 = -$9.44, HKD -$30000 @ 0.00167 = -$50.10):** Sorted by signed amount: [(-$50.10, HKD-30000), (-$50, USD), (-$9.44, HKD-73.75)]. Two clusters: {HKD-30000, USD} and {HKD-73.75}. First cluster keeps USD -$50 (base winner), second keeps HKD -$73.75 (only member). Result: 2 rows (correct).
6. **Opposite-sign amounts:** USD +$5 (fx=1.0) and HKD -$39 (fx=0.128, base=-$5). Signed: +5 vs -5 → difference = 10 > tolerance → two clusters → both kept. Correct.
7. **Order independence:** `base_equivalents.sort()` ensures deterministic clustering regardless of input row order.
8. **Multiple base-currency rows in one cluster:** Pass 1 (segment dedup) already removes same-currency same-amount duplicates. If two USD rows with slightly different amounts cluster together, both are kept — they're distinct events. The helper does NOT call `_select_dedup_winner()` (which requires `synthetic_prefixes` kwarg and is designed for Pass 1 semantics, not cross-currency clustering).
9. **Interaction with `levelOfDetail` filtering (commit `80184915`):** `levelOfDetail` filtering runs BEFORE cross-currency dedup (at row normalization time, lines 736-738 and 1033-1036). SUMMARY rows are already removed before dedup sees them. No interaction — independent pipeline stages.
10. **Tolerance uses strict `<` (not `<=`):** Boundary values at exactly the threshold are treated as distinct, avoiding ambiguous edge cases.

## Fix B: UK Stamp Tax (-$11.04) — Already Handled

### Investigation Result

`normalize_flex_trades()` at `flex.py:358-368` already extracts `taxes` from Flex Trade rows and adds it to the `fee` field:

```python
fee = abs(safe_float(_get_attr(trade, "ibCommission", "commission", "commissionAmount"), 0.0))
    + abs(safe_float(_get_attr(trade, "taxes"), 0.0))
```

UK stamp duty (SDRT) is reported in the Flex `taxes` attribute on Trade rows. This is already included in the trade cost basis and flows through the cash replay via the TRADE event outflow. **No code change needed.**

Existing test coverage: `tests/ibkr/test_flex.py:149` already exercises the `taxes` + `ibCommission` → `fee` path. Add one explicit stamp tax test for clarity.

## Tests

**File: `tests/ibkr/test_flex.py`**

### Fix A tests (cross-currency dedup):

1. **`test_income_cross_currency_dedup_keeps_distinct_amounts`** — USD interest -$50 (fxRateToBase=1.0) + HKD interest -$73.75 (fxRateToBase=0.128 → base -$9.44) on same date. Two clusters → both kept.

2. **`test_income_cross_currency_dedup_drops_true_duplicate_with_fx`** — USD interest -$3885.37 (fxRateToBase=1.0) + HKD interest -$30000 (fxRateToBase=0.12951 → base -$3885.30) on same date. One cluster, within tolerance → HKD dropped, USD kept.

3. **`test_income_cross_currency_dedup_no_fx_data_falls_back`** — USD + HKD rows WITHOUT fxRateToBase (fx_rate_to_base=0.0) → `all_have_fx = False` → falls back to existing behavior (keep USD). No regression.

4. **`test_income_cross_currency_dedup_partial_fx_falls_back`** — USD row has fxRateToBase=1.0, HKD row has no fxRateToBase → `all_have_fx = False` on second row → falls back to legacy. Ensures partial data doesn't cause misclassification.

5. **`test_income_cross_currency_dedup_3row_mixed_group`** — USD -$50 (fx=1.0) + HKD -$73.75 (fx=0.128, base=-$9.44) + HKD -$30000 (fx=0.00167, base=-$50.10). Three rows → two clusters: {USD, HKD-30000} and {HKD-73.75}. Result: 2 rows.

6. **`test_income_cross_currency_dedup_opposite_sign`** — USD +$5 interest credit (fx=1.0) + HKD -$39 interest charge (fx=0.128, base=-$5) on same date/symbol/type. Signed amounts: +5 vs -5 → separate clusters → both kept. Verifies opposite-sign events are never collapsed.

7. **`test_income_cross_currency_dedup_reorder_stable`** — Same rows as test 2 but in reversed order (HKD first, USD second). Verify same result (USD kept). Tests `base_equivalents.sort()` determinism.

8. **`test_income_cross_currency_dedup_small_amount_boundary`** — Two sub-tests:
   - USD -$0.30 (fx=1.0) + HKD -$2.34 (fx=0.128, base=-$0.2995). Difference $0.0005 < $0.10 tolerance → one cluster → collapsed to USD.
   - USD -$0.30 (fx=1.0) + HKD -$3.28 (fx=0.128, base=-$0.42). Difference $0.12 >= $0.10 tolerance → two clusters → both kept.

9. **`test_income_cross_currency_dedup_two_base_rows_in_same_cluster`** — USD -$50.00 (fx=1.0) + USD -$50.05 (fx=1.0) + HKD -$387 (fx=0.12929, base=-$50.04). All three base equivalents within $0.10 → single cluster. Cluster has two base-currency rows (USD -$50.00 and USD -$50.05). Result: both USD rows kept, HKD dropped. Proves the helper keeps ALL base rows per cluster (not just one via `_select_dedup_winner`). A broken implementation picking only one winner would return 1 row instead of 2.

10. **`test_income_cross_currency_dedup_large_amount_distinct`** — USD -$3885.37 (fx=1.0) + HKD -$30100 (fx=0.12951, base=-$3898.25). Difference $12.88 > $0.10 tolerance → two clusters → both kept. Verifies that the flat $0.10 tolerance doesn't collapse large amounts that happen to be near each other.

11. **`test_flow_cross_currency_dedup_keeps_distinct_amounts`** — Same as test 1 but via `normalize_flex_cash_rows()` flow path.

12. **`test_flow_cross_currency_dedup_drops_true_duplicate_with_fx`** — Same as test 2 but via flow path.

13. **`test_cross_currency_dedup_zero_fx_rate`** — Row with explicit `fxRateToBase="0"` → treated as no FX data → legacy fallback.

### Fix B test (stamp tax — verification only):

14. **`test_trade_taxes_included_in_fee`** — Trade with `ibCommission=-2.50` and `taxes=-11.04` → `fee == 13.54`. Uses `_flex_trade()` helper.

### Existing test compatibility:

The existing tests (`test_income_cross_currency_dedup_keeps_usd`, `test_income_cross_currency_dedup_order_independent`, `test_flow_cross_currency_dedup_keeps_usd`, etc.) do NOT include `fxRateToBase` in their test data. With the fix, `fx_rate_to_base = safe_float(None, 0.0) = 0.0` → `all_have_fx = False` → legacy fallback path. **All existing tests pass unchanged.**

## Verification

```bash
# New + existing cross-currency tests
pytest tests/ibkr/test_flex.py -x -v -k "cross_currency or taxes"

# Full flex test suite regression
pytest tests/ibkr/test_flex.py -x -q

# Full realized perf regression
pytest tests/core/test_realized_performance_analysis.py -x -q
```

## DB Cleanup

After deploying, re-ingest IBKR Flex data to pick up the previously-dropped HKD interest rows. The new rows will have different transaction_ids (content-hash based) and will insert cleanly.

No manual DB purge needed — this fix only adds rows that were previously dropped.
