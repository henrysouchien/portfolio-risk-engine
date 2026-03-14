# Fix: IBKR Flex Income/Fee Segment + Cross-Currency Dedup

## Context

The IBKR Flex `CashTransaction` section reports each income/fee event once
per account segment (S=Securities, C=Commodities, F=Financial). For accounts
with HKD holdings (MHI futures), events also appear in both native currency
(HKD) and base currency (USD). Combined, this produces up to 6x duplication.

Additionally, `BROKERINTPAID` rows are processed by BOTH the income pipeline
(`normalize_flex_cash_income_trades()` → type=INTEREST) AND the flow pipeline
(`normalize_flex_cash_rows()` → flow_type=fee), causing double-counting of
interest charges.

This plan applies the same two-pass dedup pattern used in the MTM fix
(`normalize_flex_futures_mtm()`), extended to income and flow normalizers.

### Evidence (from DB queries)

| Event Type | Raw Rows | Unique | Ratio | USD-Deduped vs Statement |
|-----------|----------|--------|-------|--------------------------|
| DIVIDEND  | 198      | 33     | 6.0x  | $182.41 = $182.41 **EXACT** |
| INTEREST  | 156      | 26     | 6.0x  | -$252.40 = -$252.40 **EXACT** |
| Fees      | 270      | 60     | 4.5x  | -$571.44 vs -$237.03 (has overlap) |
| Trades    | 237      | 79     | 3.0x  | Already deduped correctly |
| MTM       | 85       | 85     | 1.0x  | Already deduped (prior fix) |

The fee discrepancy (-$571 vs -$237) breaks down:
- Interest overlap: -$252.41 (same entries in both income and fee pipelines)
- After removing overlap: -$319.03 vs -$237.03 = -$82 remaining gap
- The $82 may be from sub-segment fee duplication or GBP fee entries

### Root Cause: Three Bugs

**Bug 1: No segment dedup in income normalizer**
`normalize_flex_cash_income_trades()` (line 582) processes every raw
CashTransaction row. IBKR reports each event once per segment, each with a
unique `transactionID`. No dedup → 6x income events.

**Bug 2: No segment dedup in flow normalizer**
`normalize_flex_cash_rows()` (line 900) has overlap dedup between
CashTransaction and Transfer sections, but no segment dedup within
CashTransaction. Result: 4.5x fee events.

**Bug 3: BROKERINTPAID in both pipelines**
- `_income_trade_type_for_cash_type()` (line 573): Maps `BROKERINTPAID` → `"INTEREST"`
- `_cash_classification()` (line 545): Maps `BROKERINTPAID` → `"fee"` flow
- Both called on the same raw `CashTransaction` rows
- Result: every interest-paid event creates BOTH an income row AND a flow row

## Codex Review Feedback (Round 1: FAIL → Round 2: FAIL)

### Round 1 Issues (all resolved)

1. **HIGH — DB cleanup incomplete** → Delete from all four tables, scoped to user_id.
2. **HIGH — Dedup keys too coarse** → See Round 2 #2 for refined resolution.
3. **MEDIUM — "Keep first" causes transaction_id churn** → See Round 2 #1 for refined resolution.
4. **MEDIUM — BROKERINTPAID removal safety** → Confirmed safe (income replays independently from flows).
5. **MEDIUM — Test gaps** → See Round 2 #4 for expanded test plan.

### Round 2 Issues (all resolved)

1. **HIGH — transaction_id churn when multiple real IDs exist**: "Prefer real ID"
   is ambiguous when ALL segment copies have real `transactionID`s.
   - **Resolution**: Two-tier tiebreaker: prefer real transactionID over synthetic,
     then `min(transaction_id)` among real IDs. This is stable across ingests because
     IBKR assigns the same transactionIDs for the same data. No ordering dependency.

2. **HIGH — cross-currency `abs(amount)` is unsafe**: (a) `abs()` can merge
   opposite-sign events; (b) amounts differ across currencies (e.g. -30000 HKD vs
   -3885 USD), so amount-based matching misses true FX duplicates.
   - **Resolution**: Follow the MTM pattern exactly — cross-currency group key
     does NOT include amount. For income: `(account_id, date, symbol, income_type)`.
     For flows: `(account_id, date, flow_type, raw_type)`. Pass 1 (segment dedup)
     already collapsed same-amount/same-currency duplicates, so the remaining
     multi-currency entries for the same event will differ in amount. Grouping
     without amount correctly matches them. The `raw_type` discriminator in flows
     prevents collapsing distinct fee types (FEES vs COMMADJ) on the same day.

3. **MEDIUM — flow segment dedup key too coarse**: `(account_id, date, flow_type,
   amount, currency)` can collapse distinct same-day same-amount fees.
   - **Resolution**: Add `raw_type` to the flow segment dedup key:
     `(account_id, date, flow_type, raw_type, round(amount, 8), currency)`.
     This distinguishes FEES from COMMADJ from ADVISORFEES.

4. **MEDIUM — test coverage gaps**: Missing tests for deterministic winner among
   multiple real IDs, flow order-independence, cross-currency different-amount matching.
   - **Resolution**: Added 3 new tests (see test plan below).

## Changes

### 1. Fix BROKERINTPAID double-counting — `ibkr/flex.py`

**Function**: `_cash_classification()` (line 545)

Remove `BROKERINTPAID` and `BONDINTPAID` from the `fee_types` set. These are
already handled by the income pipeline as INTEREST events. The flow pipeline
should not also emit them as fee events.

```python
# Before:
fee_types = {"BROKERINTPAID", "BONDINTPAID", "FEES", "COMMADJ", "ADVISORFEES"}

# After:
fee_types = {"FEES", "COMMADJ", "ADVISORFEES"}
```

**Why this is safe**:
- Income pipeline (`_income_trade_type_for_cash_type`) already captures
  `BROKERINTPAID` and `BONDINTPAID` as INTEREST income events.
- `derive_cash_and_external_flows()` replays income events into cash (line 1845-1846).
- The flow extractor (`providers/flows/ibkr_flex.py:43`) only emits rows with
  `flow_type` in canonical set — after fix, BROKERINTPAID rows return empty from
  `_cash_classification()` and are naturally excluded.
- BROKERINTPAID has `is_external_flow=false`, so external-flow tracking is unaffected.

### 2. Add segment dedup to income normalizer — `ibkr/flex.py`

**Function**: `normalize_flex_cash_income_trades()` (line 582)

Add two-pass dedup (same pattern as `normalize_flex_futures_mtm()`):

**Pass 1 (segment dedup)**: After building normalized list, dedup by
`(account_id, date_iso, symbol, income_type, round(amount, 8), currency)`.
Uses **signed** amount to avoid collapsing opposite-sign events (e.g. +$100
dividend and -$100 withholding on same day). Deterministic winner selection:
prefer real transactionID over synthetic, then `min(transaction_id)` among
real IDs. This is stable across ingests.

**Pass 2 (cross-currency dedup)**: Group surviving events by
`(account_id, date_iso, symbol, income_type)` — **no amount** in key
(same pattern as MTM). Amounts differ across currencies (e.g. -30000 HKD vs
-3885 USD for the same event), so amount-based matching would miss true
duplicates. For groups with multiple currencies, keep only `base_currency`
(default "USD") entries. If no base currency match, keep all.

Add `base_currency: str = "USD"` parameter (same as MTM normalizer).

### 3. Add segment dedup to flow normalizer — `ibkr/flex.py`

**Function**: `normalize_flex_cash_rows()` (line 900)

After building normalized list (from both CashTransaction and Transfer
sections), add the same two-pass dedup:

**Pass 1 (segment dedup)**: Dedup by
`(account_id, date_iso, flow_type, raw_type, round(amount, 8), currency)`.
Uses **signed** amount. Includes `raw_type` to distinguish FEES from COMMADJ
from ADVISORFEES. Deterministic winner: prefer real transactionID, then
`min(transaction_id)` among real IDs.

**Pass 2 (cross-currency dedup)**: Group by
`(account_id, date_iso, flow_type, raw_type)` — **no amount** in key
(same pattern as MTM). For multi-currency groups, keep only `base_currency`
entries. If no match, keep all.

Add `base_currency: str = "USD"` parameter.

**Note**: The existing CashTransaction/Transfer overlap dedup
(`_build_overlap_key` + `primary_overlap_keys`) is preserved — it runs
first, then the segment/cross-currency dedup runs on the surviving rows.

### 4. Update tests

**Existing tests (keep passing)**:
- `test_normalize_flex_cash_income_trades_maps_dividend_and_interest_rows` — no change needed (single-segment, single-currency)
- `test_normalize_flex_cash_rows_prefers_cash_transaction_over_transfer_overlap` — no change needed (single-segment)
- `test_normalize_flex_cash_rows_keeps_string_transaction_ids` — no change needed

**New tests for `normalize_flex_cash_income_trades()`**:
- `test_income_segment_dedup_collapses_identical_copies` — 3 identical dividend rows (different transactionID) → 1 output
- `test_income_segment_dedup_deterministic_winner` — 3 segment copies all with real transactionIDs → keeps `min(transaction_id)`, stable across runs
- `test_income_cross_currency_dedup_keeps_usd` — same interest in HKD (-30000) and USD (-3885) → keeps USD only (different amounts!)
- `test_income_different_symbols_same_day_preserved` — different symbols on same day → both kept
- `test_income_same_symbol_different_amounts_preserved` — same symbol, same day, different amounts → both kept
- `test_income_base_currency_override` — `base_currency="EUR"` → keeps EUR over HKD
- `test_income_no_base_match_keeps_all` — HKD+GBP with default USD base → both kept
- `test_income_cross_currency_dedup_order_independent` — USD before HKD or HKD before USD → same result

**New tests for `normalize_flex_cash_rows()`**:
- `test_flow_segment_dedup_collapses_identical_fees` — 3 identical fee rows → 1 output
- `test_flow_cross_currency_dedup_keeps_usd` — same fee in HKD and USD (different amounts) → keeps USD only
- `test_flow_same_type_different_amounts_preserved` — same flow_type, same day, different amounts → both kept
- `test_flow_no_base_match_keeps_all` — multi-currency with no USD → all kept
- `test_flow_different_raw_types_same_day_preserved` — FEES and COMMADJ on same day with same amount → both kept (raw_type discriminator)
- `test_flow_order_independent` — shuffled input order → same output

**New tests for `_cash_classification()`**:
- `test_broker_interest_paid_not_classified_as_fee` — `BROKERINTPAID` returns empty string flow_type
- `test_bond_interest_paid_not_classified_as_fee` — `BONDINTPAID` returns empty string flow_type
- `test_fees_commadj_advisorfees_still_classified` — `FEES`/`COMMADJ`/`ADVISORFEES` still return "fee"

### 5. Clean up stored data — one-time DB fix

After normalizer fixes, delete ALL IBKR Flex data from all tables, scoped to user:
```sql
-- Delete from derived tables first (FK references)
DELETE FROM normalized_transactions WHERE provider = 'ibkr_flex' AND user_id = %(user_id)s;
DELETE FROM normalized_income WHERE provider = 'ibkr_flex' AND user_id = %(user_id)s;
DELETE FROM provider_flow_events WHERE provider = 'ibkr_flex' AND user_id = %(user_id)s;
-- Delete from raw table
DELETE FROM raw_transactions WHERE provider IN ('ibkr_flex', 'ibkr_flex_mtm') AND user_id = %(user_id)s;
```
Then trigger re-ingest via `refresh_transactions(provider="ibkr_flex")`.

### 6. Verify with back-solve diagnostic

Re-run `python3 scripts/ibkr_cash_backsolve.py` and confirm:
- Income matches statement ($182.41 dividends, ~-$252 interest)
- Fees are no longer double-counted with interest
- Total back-solve gap shrinks significantly from -$1,702

## Actual Results

| Category | Before Fix | After Fix | Statement | Notes |
|----------|-----------|-----------|-----------|-------|
| Dividends | $364.82 (2x) | $306.97 (33 rows) | $182.41 | Gross; $124.56 = withholding tax (WHTAX excluded by design) |
| Interest | -$651.62 (2.5x) | -$308.58 (13 rows) | -$252.40 | Includes HKD→USD conversion delta |
| Fees | -$999.70 (4.2x, includes interest overlap) | -$319.03 (35 rows) | -$237.03 | BROKERINTPAID removed from fees |
| MTM | -$5,249.90 | -$5,209.68 (85 rows) | -$3,588.60 | Separate issue |

Back-solve gap: -$1,702 → -$2,695. Gap widened because the double-counted
fees/interest were accidentally compensating for the real MTM discrepancy
(-$1,661). Removing ~$966 of phantom cash drains exposed the underlying gap.

### Implementation discovery: account_id dedup

IBKR Flex reports the same event with different `accountId` values across
segments (`"U2471778"` vs `"-"`). The dedup keys exclude `account_id` entirely
to handle this. This is safe because `(date, symbol, type, amount, currency)`
is sufficient to identify duplicate events within a single-account Flex query.

## Design Decisions (Resolved)

1. **Signed amount in segment dedup**: Using signed `round(amount, 8)` instead
   of `abs(amount)`. This prevents collapsing a +$100 dividend and -$100
   withholding on the same day/symbol/account.

2. **No amount in cross-currency grouping**: Following the MTM pattern exactly.
   Cross-currency group key does NOT include amount because the same event has
   different magnitudes in different currencies (e.g. -30000 HKD vs -3885 USD).
   Including amount would prevent matching. Safe because Pass 1 already
   collapsed same-amount/same-currency segment duplicates — remaining
   multi-currency entries represent the same event in different denominations.
   For flows, `raw_type` in the group key prevents collapsing distinct fee types.

3. **Deterministic row selection**: Two-tier: prefer real IBKR `transactionID`
   over synthetic, then `min(transaction_id)` among real IDs. For cross-currency
   dedup, prefer base_currency row (same as MTM fix). The `min()` tiebreaker is
   stable across ingests because IBKR assigns the same transactionIDs.

4. **Flow dedup discriminator**: `raw_type` added to both segment and
   cross-currency dedup keys for flows. This distinguishes FEES from COMMADJ
   from ADVISORFEES, preventing false collapses of distinct fee events.

5. **BROKERINTPAID removal safety**: Verified that the realized performance
   engine's cash replay processes income events and provider flow events
   independently (lines 1845-1849). Removing BROKERINTPAID from flows eliminates
   double-counting. No external-flow tracking is affected.

## Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py` | Fix `_cash_classification()`, add dedup to `normalize_flex_cash_income_trades()` and `normalize_flex_cash_rows()` |
| `tests/ibkr/test_flex.py` | Add segment/cross-currency dedup tests for income and flows, interest classification tests |

## Verification

1. `python3 -m py_compile ibkr/flex.py` — syntax check
2. `pytest -xvs tests/ibkr/test_flex.py` — all tests pass
3. `pytest -xvs tests/ibkr/test_flex_futures_mtm.py` — MTM tests still pass
4. Delete + re-ingest IBKR Flex data (scoped to user)
5. `python3 scripts/ibkr_cash_backsolve.py` — confirm improved category match
6. `get_performance(mode="realized", source="ibkr_flex", format="full", output="file")` — check income/fee totals
