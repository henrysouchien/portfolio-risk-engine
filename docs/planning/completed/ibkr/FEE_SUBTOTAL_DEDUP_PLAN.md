# Fee Subtotal Dedup Plan (v4)

## Problem

IBKR Flex CashTransaction section includes both per-account detail rows (`levelOfDetail=DETAIL`) and consolidated summary rows (`levelOfDetail=SUMMARY`). The normalizer ingests both, causing double-counted fees (-$145), and potentially double-counted income if the segment dedup (Pass 1) doesn't catch all non-DETAIL rows.

**Pattern observed in live Flex data** (159 CashTransaction rows: 86 DETAIL, 73 SUMMARY):
```
2025-06-03  -$10.00  acct=U2471778  lod=DETAIL   SNAPSHOTVALUENONPRO   (detail)
2025-06-03   -$4.50  acct=U2471778  lod=DETAIL   ABCOPRANP              (detail)
2025-06-03  -$14.50  acct=-         lod=SUMMARY  ABCOPRANP              (subtotal)
```

All 73 SUMMARY rows have `accountId="-"`. They are consolidated duplicates of the per-account DETAIL rows.

**Impact**: 10 fee SUMMARY rows x -$14.50 = -$145.00 of double-counted fees (store total -$319 vs IBKR statement ~-$164). Income SUMMARY rows are currently caught by Pass 1 segment dedup (same amount, different accountId), but filtering them early is cleaner and more robust.

## Root Cause

`_normalize_cash_transaction_row()` (ibkr/flex.py:989) does not check the `levelOfDetail` attribute. All rows are normalized and enter the dedup pipeline. Pass 1 segment dedup catches same-amount SUMMARY rows (income/MTM), but fee SUMMARY rows have different amounts (they're subtotals, not duplicates) and survive all dedup passes.

## Approach

Filter non-DETAIL rows early using the `levelOfDetail` XML attribute. Use `!= "DETAIL"` (not `== "SUMMARY"`) to also catch any other aggregate values IBKR may emit (e.g., `CURRENCY_SUMMARY`).

**Confirmed available**: `levelOfDetail` is present on every CashTransaction row in the live Flex XML. ib_async's `FlexReport.extract()` preserves all XML attributes via `node.attrib` (ib_async/flexreport.py:67). Current data has only `DETAIL` (86) and `SUMMARY` (73).

**Safe fallback**: If `levelOfDetail` is missing or empty, the row is kept (no data loss). If no DETAIL rows exist in the batch (summary-only report), filtering is disabled entirely. A warning is logged for `accountId="-"` rows missing `levelOfDetail` to detect format changes.

**Why batch-level guard is sufficient**: IBKR's `levelOfDetail` is a binary classification in the Flex schema — DETAIL rows are per-account events, SUMMARY rows are consolidated rollups. In our live data, all 73 SUMMARY rows have `accountId="-"` (consolidated) and all 86 DETAIL rows have real account IDs. There is no scenario in the Flex schema where a SUMMARY row contains unique event data not present in DETAIL rows — rollups are by definition derived from the detail rows.

## Implementation

### Helper: `_should_filter_non_detail()`

Batch-level check: only filter non-DETAIL rows when at least one DETAIL row exists. If a report has only SUMMARY rows (abnormal), keep everything to avoid data loss.

```python
def _should_filter_non_detail(raw_rows: Iterable[dict[str, Any]]) -> bool:
    """Return True if we should filter non-DETAIL levelOfDetail rows.

    Only filters when at least one DETAIL row exists — if ALL rows are
    SUMMARY (abnormal Flex config), keep everything to avoid data loss.
    """
    for row in raw_rows:
        lod = str(row.get("levelOfDetail") or "").strip().upper()
        if lod == "DETAIL":
            return True
    return False
```

### File: `ibkr/flex.py` — `_normalize_cash_transaction_row()`

Add a `filter_non_detail` parameter (default `False`). The caller (`normalize_flex_cash_rows()`) pre-computes the flag via `_should_filter_non_detail()`.

**Location**: After line 1000 (`account_id` assignment), before `account_name`.

```python
def _normalize_cash_transaction_row(
    raw_row: dict[str, Any], row_index: int, *, filter_non_detail: bool = False,
) -> dict[str, Any]:
    ...
    account_id = _normalize_identifier(raw_row.get("accountId") or raw_row.get("accountID"))
    # Skip non-detail rows (SUMMARY, CURRENCY_SUMMARY, etc.) — these are
    # consolidated duplicates of per-account DETAIL rows.
    lod = str(raw_row.get("levelOfDetail") or "").strip().upper()
    if filter_non_detail and lod and lod != "DETAIL":
        return {}
    # Warn if accountId="-" but no levelOfDetail — possible format change
    if not lod and account_id == "-":
        logger.warning(
            "CashTransaction row with accountId='-' missing levelOfDetail; "
            "keeping row but may be a summary duplicate: date=%s type=%s amount=%s",
            raw_row.get("dateTime") or raw_row.get("date"),
            raw_row.get("type"),
            raw_row.get("amount"),
        )
    account_name = ...  # rest unchanged
```

**Caller update** in `normalize_flex_cash_rows()` (line 1098):

```python
def normalize_flex_cash_rows(
    cash_rows: Iterable[dict[str, Any]],
    transfer_rows: Iterable[dict[str, Any]],
    base_currency: str = "USD",
) -> list[dict[str, Any]]:
    # Materialize to allow two-pass iteration
    cash_rows_list = list(cash_rows)
    _filter_lod = _should_filter_non_detail(cash_rows_list)

    normalized: list[dict[str, Any]] = []
    ...
    for index, row in enumerate(cash_rows_list):
        normalized_row = _normalize_cash_transaction_row(row, index, filter_non_detail=_filter_lod)
        ...
```

### File: `ibkr/flex.py` — `normalize_flex_cash_income_trades()`

**Location**: Before the main loop (line ~716). Same pattern: pre-compute, then filter per-row.

```python
def normalize_flex_cash_income_trades(
    raw_cash_rows: Iterable[dict[str, Any]],
    ...
) -> list[dict[str, Any]]:
    raw_cash_rows_list = list(raw_cash_rows)
    _filter_lod = _should_filter_non_detail(raw_cash_rows_list)
    ...
    for row in raw_cash_rows_list:
        trade_type = _income_trade_type_for_cash_type(str(row.get("type") or "").strip().upper())
        if not trade_type:
            continue

        # Skip non-detail rows when DETAIL rows exist in the batch
        lod = str(row.get("levelOfDetail") or "").strip().upper()
        if _filter_lod and lod and lod != "DETAIL":
            continue
        # Warn if accountId="-" but no levelOfDetail — possible format change
        account_id = _normalize_identifier(row.get("accountId") or row.get("accountID"))
        if not lod and account_id == "-":
            logger.warning(
                "CashTransaction income row with accountId='-' missing levelOfDetail; "
                "keeping row but may be a summary duplicate: date=%s type=%s amount=%s",
                row.get("dateTime") or row.get("date"),
                row.get("type"),
                row.get("amount"),
            )
```

**Note**: Both `normalize_flex_cash_rows()` and `normalize_flex_cash_income_trades()` receive the same `raw_cash_rows` from `fetch_flex_data()` (line 1389/1394). Since we materialize to a list in each function, the `Iterable` is consumed correctly.

### What about the existing segment dedup (Pass 1)?

No changes needed. With non-DETAIL rows filtered early, Pass 1 no longer sees them. The segment dedup still handles any same-amount cross-account duplicates that might exist among DETAIL rows (defensive).

### What about `normalize_flex_futures_mtm()` (line 838)?

Already has `account_id == "-"` filter at line 874. The StatementOfFundsLine section may not have `levelOfDetail`. The existing guard is sufficient.

## Edge Cases

| Scenario | Result |
|---|---|
| Fee SUMMARY row (lod=SUMMARY) | Filtered early — never enters dedup pipeline |
| Fee DETAIL row (lod=DETAIL) | Kept |
| Dividend SUMMARY row | Filtered early — no longer relies on Pass 1 |
| Unknown lod value (e.g., CURRENCY_SUMMARY) | Filtered (`lod != "DETAIL"`) |
| Missing levelOfDetail (attribute absent) | Row kept (safe fallback), warning logged if acct="-" |
| Empty levelOfDetail (lod="") | Row kept (safe fallback) |

## Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py` | Add `levelOfDetail` filter in `_normalize_cash_transaction_row()` and `normalize_flex_cash_income_trades()` |
| `tests/ibkr/test_flex.py` | Add 9 tests |

## Tests

**File: `tests/ibkr/test_flex.py`**

### Test 1: `test_normalize_flex_cash_rows_filters_summary_fee_rows`

```python
cash_rows = [
    {"transactionID": "1001", "dateTime": "2025-06-03", "accountId": "U2471778",
     "currency": "USD", "amount": "-10.00", "type": "Other Fees",
     "description": "SNAPSHOTVALUENONPRO FOR JUN 2025", "levelOfDetail": "DETAIL"},
    {"transactionID": "1002", "dateTime": "2025-06-03", "accountId": "U2471778",
     "currency": "USD", "amount": "-4.50", "type": "Other Fees",
     "description": "ABCOPRANP FOR JUN 2025", "levelOfDetail": "DETAIL"},
    {"dateTime": "2025-06-03", "accountId": "-",
     "currency": "USD", "amount": "-14.50", "type": "Other Fees",
     "description": "ABCOPRANP FOR JUN 2025", "levelOfDetail": "SUMMARY"},
]
```

- Assert: `len(normalized) == 2`
- Assert: no row has `account_id == "-"`
- Assert: `sum(r["amount"] for r in normalized) == pytest.approx(-14.50)`

### Test 2: `test_normalize_flex_cash_income_trades_filters_summary_rows`

Test the income path specifically with a SUMMARY-only row that has no DETAIL counterpart:

```python
cash_rows = [
    {"transactionID": "2001", "dateTime": "2025-06-15", "accountId": "U2471778",
     "currency": "USD", "amount": "50.00", "type": "Dividends",
     "description": "AAPL(US0378331005) CASH DIVIDEND", "symbol": "AAPL",
     "levelOfDetail": "DETAIL"},
    # SUMMARY-only row — no matching DETAIL for this amount
    {"dateTime": "2025-06-15", "accountId": "-",
     "currency": "USD", "amount": "30.00", "type": "Dividends",
     "description": "MSFT CASH DIVIDEND", "symbol": "MSFT",
     "levelOfDetail": "SUMMARY"},
]
```

- Call `flex_client.normalize_flex_cash_income_trades(cash_rows)`
- Assert: only 1 income trade row returned (the DETAIL AAPL row)
- Assert: MSFT SUMMARY row is absent (proves the filter, not Pass 1 dedup)

### Test 3: `test_normalize_flex_cash_rows_keeps_detail_only`

```python
cash_rows = [
    {"transactionID": "3001", "dateTime": "2025-05-02", "accountId": "U2471778",
     "currency": "USD", "amount": "-10.00", "type": "Other Fees",
     "description": "SNAPSHOTVALUENONPRO", "levelOfDetail": "DETAIL"},
    {"transactionID": "3002", "dateTime": "2025-05-02", "accountId": "U2471778",
     "currency": "USD", "amount": "-4.50", "type": "Other Fees",
     "description": "ABCOPRANP", "levelOfDetail": "DETAIL"},
]
```

- Assert: `len(normalized) == 2`

### Test 4: `test_normalize_flex_cash_rows_missing_level_of_detail_kept`

Same as Test 1 but all rows have no `levelOfDetail` key (simulates format change).

- Assert: `len(normalized) == 3` (all kept — missing attribute defaults to keeping the row)

### Test 5: `test_normalize_flex_cash_rows_filters_non_detail_values`

A row with an unknown non-DETAIL value should be filtered:

```python
cash_rows = [
    {"transactionID": "5001", "dateTime": "2025-06-03", "accountId": "U2471778",
     "currency": "USD", "amount": "-10.00", "type": "Other Fees",
     "description": "SNAPSHOTVALUENONPRO", "levelOfDetail": "DETAIL"},
    {"dateTime": "2025-06-03", "accountId": "-",
     "currency": "USD", "amount": "-10.00", "type": "Other Fees",
     "description": "CONSOLIDATED", "levelOfDetail": "CURRENCY_SUMMARY"},
]
```

- Assert: `len(normalized) == 1` (CURRENCY_SUMMARY filtered)
- Assert: kept row has `transaction_id == "5001"`

### Test 6: `test_normalize_flex_cash_rows_summary_only_report_keeps_all`

A report with only SUMMARY rows (no DETAIL) should keep everything — `_should_filter_non_detail()` returns False:

```python
cash_rows = [
    {"dateTime": "2025-06-03", "accountId": "-",
     "currency": "USD", "amount": "-14.50", "type": "Other Fees",
     "description": "ABCOPRANP FOR JUN 2025", "levelOfDetail": "SUMMARY"},
    {"dateTime": "2025-06-15", "accountId": "-",
     "currency": "USD", "amount": "-10.00", "type": "Other Fees",
     "description": "SNAPSHOTVALUENONPRO", "levelOfDetail": "SUMMARY"},
]
```

- Assert: `len(normalized) == 2` (all kept — no DETAIL rows in batch, so filter is disabled)

### Test 7: `test_normalize_flex_cash_rows_warns_on_dash_account_missing_lod`

A row with `accountId="-"` and no `levelOfDetail` should be kept but emit a warning:

```python
cash_rows = [
    {"transactionID": "6001", "dateTime": "2025-06-03", "accountId": "U2471778",
     "currency": "USD", "amount": "-10.00", "type": "Other Fees",
     "description": "SNAPSHOTVALUENONPRO"},
    {"dateTime": "2025-06-03", "accountId": "-",
     "currency": "USD", "amount": "-14.50", "type": "Other Fees",
     "description": "ABCOPRANP"},
]
```

- Use `caplog` fixture with `logging.WARNING` level for `ibkr` logger (the ibkr package logger)
- Assert: `len(normalized) == 2` (both kept — no levelOfDetail)
- Assert: warning logged containing "missing levelOfDetail"

### Test 8: `test_normalize_flex_cash_income_trades_filters_summary_and_warns`

Verify the income path filters SUMMARY and warns on missing lod:

```python
cash_rows_summary = [
    {"transactionID": "7001", "dateTime": "2025-06-15", "accountId": "U2471778",
     "currency": "USD", "amount": "50.00", "type": "Dividends",
     "description": "AAPL DIVIDEND", "symbol": "AAPL", "levelOfDetail": "DETAIL"},
    {"dateTime": "2025-06-15", "accountId": "-",
     "currency": "USD", "amount": "50.00", "type": "Dividends",
     "description": "AAPL DIVIDEND", "symbol": "AAPL", "levelOfDetail": "SUMMARY"},
]
cash_rows_no_lod = [
    {"transactionID": "7003", "dateTime": "2025-06-15", "accountId": "U2471778",
     "currency": "USD", "amount": "50.00", "type": "Dividends",
     "description": "AAPL DIVIDEND", "symbol": "AAPL"},
    {"dateTime": "2025-06-15", "accountId": "-",
     "currency": "USD", "amount": "50.00", "type": "Dividends",
     "description": "AAPL DIVIDEND", "symbol": "AAPL"},
]
```

- Call `flex_client.normalize_flex_cash_income_trades(cash_rows_summary)`
- Assert: 1 row returned (SUMMARY filtered)
- Call `flex_client.normalize_flex_cash_income_trades(cash_rows_no_lod)` with `caplog` (logger `ibkr`)
- Assert: 1 row returned (both kept by lod filter, then existing income dedup at line 774 collapses same-amount cross-account rows to 1)
- Assert: warning logged containing "missing levelOfDetail"

### Test 9: `test_normalize_flex_cash_income_trades_summary_only_keeps_all`

Income-path equivalent of Test 6 — summary-only batch:

```python
cash_rows = [
    {"dateTime": "2025-06-15", "accountId": "-",
     "currency": "USD", "amount": "50.00", "type": "Dividends",
     "description": "AAPL DIVIDEND", "symbol": "AAPL", "levelOfDetail": "SUMMARY"},
    {"dateTime": "2025-06-15", "accountId": "-",
     "currency": "USD", "amount": "30.00", "type": "Dividends",
     "description": "MSFT DIVIDEND", "symbol": "MSFT", "levelOfDetail": "SUMMARY"},
]
```

- Call `flex_client.normalize_flex_cash_income_trades(cash_rows)`
- Assert: 2 rows returned (all kept — no DETAIL rows in batch, filter disabled)

## Verification

```bash
# Unit tests
pytest tests/ibkr/test_flex.py -x -v

# Regression
pytest tests/ibkr/ -x -q
pytest tests/core/test_realized*.py -x -q

# Live: re-ingest IBKR flex, then check:
# list_flow_events(provider="ibkr_flex") → fee total should drop from -$319 to ~-$174
#   (wider date range than IBKR statement explains gap vs statement's -$164)
# list_income_events(provider="ibkr_flex") → income count may stay flat (SUMMARY income
#   rows were already caught by existing dedup), but verify no regressions in totals
# Fee totals should match or be closer to IBKR statement values
```
