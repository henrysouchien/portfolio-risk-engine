# Plan: Align Realized Performance Inception with Start Date

**Priority:** High
**Added:** 2026-03-07

## Context

The realized performance engine always derives `inception_date` from the earliest flex transaction (March 6, 2025), but the IBKR statement period starts April 1, 2025. This causes a $7,653 cash gap:

- March 6-31 contains first-exit sells (GLBE, VBNK, PLTR options) without matching buys
- These inflate the cash replay, making back-solved starting cash -$18,750 instead of -$11,097
- Position values already match IBKR within $87 — the entire NAV gap is cash
- **When replay periods align, the back-solve naturally produces the correct starting cash** (proven analytically: April+ flows ≈ IBKR's +$2,370, back-solve ≈ -$11,097)

No need to import IBKR's starting cash — just align the replay window so the back-solve works.

## Approach

Thread `start_date` from the MCP tool through to the engine as `inception_override`. When set, use it as `inception_date` and filter cash replay inputs to >= that date. FIFO matching still processes ALL transactions (needed for correct lot matching).

## Changes (7 files)

### 1. Engine — add `inception_override` param + filter events

**File:** `core/realized_performance/engine.py`

**a) Signature (line 152):** Add `inception_override: Optional[datetime] = None` as keyword-only arg.

**b) Override inception (after line 784):** When `inception_override > inception_date`, replace inception_date:
```python
original_inception_date = inception_date
if inception_override is not None and inception_override > inception_date:
    inception_date = inception_override
```

**c) Filter cash replay inputs (after line 1208):** Filter `transactions_for_cash` to >= inception_date:
```python
if inception_override is not None and inception_override > original_inception_date:
    transactions_for_cash = [
        txn for txn in fifo_transactions
        if (_helpers._to_datetime(txn.get("date")) or original_inception_date) >= inception_date
    ]
```

**d) Filter income, futures MTM, provider flows for cash replay ONLY:** Create **replay-only filtered copies** — do NOT mutate the canonical lists. The originals are consumed by non-cash-replay consumers (e.g. `_summarize_income_usd()` at line ~2417 uses `income_with_currency` for total income reporting, `_has_usable_mtm()` at line ~941 uses `futures_mtm_events` for futures routing decisions).
```python
if inception_override is not None and inception_override > original_inception_date:
    income_for_replay = [
        inc for inc in income_with_currency
        if (_helpers._to_datetime(inc.get("date")) or original_inception_date) >= inception_date
    ]
    mtm_for_replay = [
        e for e in futures_mtm_events
        if (_helpers._to_datetime(e.get("date")) or original_inception_date) >= inception_date
    ]
    flows_for_replay = [
        f for f in provider_flow_events
        if (_helpers._to_datetime(f.get("date")) or original_inception_date) >= inception_date
    ]
else:
    income_for_replay = income_with_currency
    mtm_for_replay = futures_mtm_events
    flows_for_replay = provider_flow_events
```
Pass `income_for_replay`, `mtm_for_replay`, and `flows_for_replay` to the cash replay path instead of the originals.

**e) Observed-only branch:** The observed-only cash replay path (around line 2093+) also uses `fifo_transactions` — apply the same filtered copies there for consistency.

**f) Diagnostics (line ~2694):** Add `inception_date_original` field when override is active.

### 2. Aggregation — thread param + aggregate `inception_date_original`

**File:** `core/realized_performance/aggregation.py`

- `analyze_realized_performance()` (line 1352): Add `inception_override: Optional[datetime] = None` param
- Pass to `engine._analyze_realized_performance_single_scope()` at lines 1388-1400 and 1417-1429
- `_analyze_realized_performance_account_aggregated()` (line 1199): Add param, pass through to each engine call
- **Multi-account aggregation (line ~1001):** When building `realized_metadata` from multiple accounts, compute `inception_date_original` as the `min()` of each account's `inception_date_original` (falling back to `inception_date` if not present). This mirrors how `inception_date` itself is already aggregated as the earliest across accounts.

### 3. Service layer — convert start_date string to datetime

**File:** `services/portfolio_service.py`

- `analyze_realized_performance()` (line 634): Add `start_date: Optional[str] = None` param
- Convert: `inception_override = pd.Timestamp(start_date).to_pydatetime().replace(tzinfo=None) if start_date else None`
- Pass `inception_override` to `_analyze_realized_performance()` at line 703
- Add `start_date` to cache key at line 689-693

### 4. MCP tool — thread start_date to service

**File:** `mcp_tools/performance.py`

- `_run_realized_with_service()` (line 132): Add `start_date: Optional[str] = None` param
- Pass to `PortfolioService.analyze_realized_performance()` at line 152
- Call site (line 592): Pass `normalized_start` to `_run_realized_with_service()`

### 5. REST endpoint — thread start_date

**File:** `routes/realized_performance.py`

- Pass `start_date` to `PortfolioService.analyze_realized_performance()` if the endpoint receives it

### 6. Shim re-export

**File:** `core/realized_performance_analysis.py`

- Ensure the shim passes through the new `inception_override` kwarg to `aggregation.analyze_realized_performance()`

### 7. Result object — add `inception_date_original` field

**File:** `core/result_objects/realized_performance.py`

- Add `inception_date_original: Optional[str] = None` field to `RealizedMetadata` (after `inception_date` at line 110)
- Add `inception_date_original` to `to_dict()` (line ~182+) — only include when not None
- Ensure `from_dict()` round-trips the field if present

## What does NOT change

- **FIFO matching** — still processes ALL transactions for correct lot matching
- **`_detect_first_exit_without_opening()`** — still runs on all transactions for diagnostics
- **Position timeline** — `build_position_timeline()` already receives `inception_date` as a param and places synthetic entries there; when inception is overridden, synthetics naturally anchor at the new date
- **Statement cash metadata** — still used for `observed_end_cash` in the back-solve; no change needed
- **`apply_date_window()`** — still runs post-analysis for end_date windowing and metric recomputation

## Verification

### Manual verification
1. Run `get_performance(mode="realized", source="ibkr_flex", start_date="2025-04-01", format="full", debug_inference=True, output="file", use_cache=False)`
2. Check `cash_backsolve_start_usd` ≈ -$11,097 (matching IBKR statement starting cash)
3. Check `inception_date` = "2025-04-01" and `inception_date_original` = "2025-03-06"
4. Check NAV at April 30 matches more closely with IBKR
5. Compare monthly returns against IBKR's TWR (0.29%)
6. Run without start_date — verify behavior unchanged (backward compatible)
7. Run existing tests: `python3 -m pytest tests/core/test_realized_performance_analysis.py -x`

### Automated tests (add to existing test file)
8. **Inception override filtering**: Unit test that `inception_override` filters `transactions_for_cash` but NOT `fifo_transactions` (FIFO still sees all txns)
9. **Replay-only copies**: Verify `income_with_currency` and `futures_mtm_events` canonical lists are NOT mutated when override is active (non-cash consumers still see full data)
10. **Observed-only branch**: Verify observed-only cash replay also respects the inception override filter
11. **Service cache key**: Verify different `start_date` values produce different cache keys
12. **Result object serialization**: Verify `inception_date_original` round-trips through `RealizedMetadata.to_dict()` / `from_dict()`
13. **Backward compatibility**: Verify `inception_override=None` produces identical results to current behavior
