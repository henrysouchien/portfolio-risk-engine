# Realized Performance — Starting Cash Anchor + Non-Trade Item Fixes

**Status:** SUPERSEDED by `DUAL_CASH_ANCHOR_PLAN.md`
**Goal:** Close the 4.2pp TWR gap vs IBKR statement (engine +4.53% vs IBKR +0.29%)
**Depends on:** Fix 1 (statement cash anchor) COMPLETE, Fix 2a (MTM metadata) COMPLETE, Fix 2b (AT. pricing) COMPLETE
**Backlog ref:** `BACKLOG.md` → "IBKR Realized Performance — Fix 3"

## Root Cause Analysis

### What we confirmed works

The realized performance engine **already captures** non-trade cash items:

| Item | Store Events | IBKR Statement | Match? |
|------|-------------|----------------|--------|
| Dividends | +$182.41 (Apr+) | +$182.41 | **Exact** |
| USD Interest | -$276.17 | -$252.40 | Close (timing) |
| Fees | -$319.03 | -$164.00 | **Bug: -$155 double-count** |

Dividends, interest, and fees all flow through the cash replay via:
- Income events → `_income_with_currency()` → `derive_cash_and_external_flows()`
- Provider flows → `provider_flow_events` → same cash replay

### The actual gap driver

The **entire** 4.2pp TWR gap is from the starting cash back-solve error:

```
start_cash = end_cash - replay_net
           = -8,727   - (-10,023)
           = -18,750   ← WRONG (should be -11,097)
```

The replay net is inflated by one-sided sells from 19 first-exit positions
(sell proceeds with no matching buy outflows). This makes the back-solved
start cash $7,653 too negative, which depresses inception NAV by $4,013
(partially offset by synthetic position values).

With a starting cash anchor from the IBKR statement:
- Corrected inception NAV: $22,371 (was $18,358)
- IBKR inception NAV: $22,284
- Gap: **$87** (from synthetic position value differences)

### Secondary issues found

1. **Fee double-counting** (-$155): Flex CashTransaction subtotal rows
   ingested as separate fee entries alongside individual line items
2. **HKD interest missing** (-$9.44): Non-USD interest charges not captured
3. **UK Stamp Tax missing** (-$11.04): Transaction fees outside CashTransaction

---

## Plan

### Part 1: Starting Cash Anchor (closes 95% of gap)

Use the IBKR statement's known starting cash balance as an anchor instead
of back-solving it from the incomplete transaction replay.

#### 1a. Extract statement starting cash from Flex metadata

The engine already extracts ending cash from the IBKR statement via
`extract_statement_cash()` in `ibkr/flex.py` (commit `c07f341b`). Extend
this to also extract **starting** cash from the same source.

**File:** `ibkr/flex.py` — `extract_statement_cash()`

The Flex CashReport section contains both Starting Cash and Ending Cash.
Currently only ending cash is extracted. Add starting cash extraction:

```python
# In extract_statement_cash(), add:
"statement_start_cash_usd": starting_cash_value,
```

Store in `fetch_metadata` alongside the existing `statement_end_cash_usd`.

#### 1b. Use statement start cash in the back-solve

**File:** `core/realized_performance/engine.py` — cash back-solve section (~line 1979)

Currently:
```python
back_solved_start_cash = observed_end_cash - replay_final_cash
```

Add anchor logic:
```python
# Prefer statement starting cash when available
statement_start_cash = _extract_statement_start_cash(fetch_metadata_rows)
if statement_start_cash is not None:
    back_solved_start_cash = statement_start_cash
    cash_anchor_source = "ibkr_statement_start"
else:
    back_solved_start_cash = observed_end_cash - replay_final_cash
    cash_anchor_source = "back_solve"
```

**Important:** The statement start cash corresponds to a specific date
(the statement period start). The anchor should only apply when the
engine's inception date is close to or after the statement start date.
If inception is significantly before the statement period, the anchor
may not be appropriate.

#### 1c. Adjust inception NAV computation

When the starting cash is anchored (not back-solved), the inception NAV
should use the anchored value:

```python
inception_nav = inception_positions_value + back_solved_start_cash
```

This already works — `back_solved_start_cash` feeds into the NAV computation.
The fix in 1b changes its value, which propagates automatically.

#### 1d. Add metadata fields

**File:** `core/result_objects/realized_performance.py`

Add to `RealizedMetadata`:
```python
cash_anchor_start_source: str = "back_solve"  # or "ibkr_statement_start"
statement_start_cash_usd: Optional[float] = None
```

#### 1e. Flex query: ensure CashReport section is requested

Verify the Flex query template includes the CashReport section with
Starting Cash. The current query requests CashTransaction (for trades)
but CashReport (for balance summaries) may be separate.

**Check:** Does `extract_statement_cash()` already handle this? If yes,
no change needed. If the starting cash comes from a different Flex section
(e.g., StatementOfFundsLine or CashReport), ensure it's requested.

#### Tests

1. `test_statement_start_cash_anchor` — when statement start cash available,
   back-solve uses it instead of replay-based computation
2. `test_statement_start_cash_missing_falls_back` — when not available,
   falls back to existing back-solve
3. `test_anchored_inception_nav` — inception NAV with anchored start cash
   matches expected value (positions + anchored cash)

---

### Part 2: Fee Double-Count Fix

#### Problem

The Flex CashTransaction section contains both individual fee line items
AND subtotal rows. The normalizer ingests both, double-counting fees.

Pattern observed:
```
2025-06-03  -$10.00  SNAPSHOTVALUENONPRO FOR JUN 2025
2025-06-03   -$4.50  ABCOPRANP FOR JUN 2025
2025-06-03  -$14.50  ABCOPRANP FOR JUN 2025  ← SUBTOTAL (= -10 + -4.50)
```

Impact: -$155 in extra fee charges (engine -$319 vs IBKR -$164).

#### Fix

**File:** `ibkr/flex.py` — `normalize_flex_cash_rows()`

Filter out subtotal/aggregate rows from CashTransaction. IBKR subtotal
rows can be identified by:
- Amount equals sum of preceding same-date individual items
- Or: `levelOfDetail` field = "SUMMARY" (if present in Flex XML)
- Or: deduplicate by checking if a row's amount equals the sum of
  other same-date, same-description-prefix rows

**Simpler approach:** In `providers/flows/ibkr_flex.py`, deduplicate
fee events that appear to be subtotals. For each date, if a fee amount
equals the sum of other fees on the same date, exclude it.

#### Tests

1. `test_flex_fee_subtotal_excluded` — subtotal row filtered out
2. `test_flex_fee_individual_items_kept` — individual items preserved
3. `test_flex_fee_no_false_positive` — non-subtotal fees not excluded

---

### Part 3: Minor Missing Items

#### 3a. HKD margin interest (-$9.44)

**Investigation needed:** Check if the Flex CashTransaction includes HKD
interest rows. If yes, the normalizer may be filtering non-USD currencies.
If no, these charges may only appear in the Activity Statement.

**File:** `ibkr/flex.py` — `normalize_flex_cash_income_trades()`

Check currency handling. The normalizer should preserve the original
currency and let the cash replay handle FX conversion.

#### 3b. UK Stamp Tax (-$11.04)

Transaction fees (regulatory taxes) are in a separate IBKR report section
(`TransactionTaxes` or similar) not currently extracted. These are small
but real costs.

**Options:**
- Extract from Flex TransactionTax section (if available)
- Or accept as a known gap (~$11/year for LSE trades)

#### 3c. Cross-provider audit

Verify non-trade item capture across all providers:

| Item | IBKR Flex | Schwab | Plaid | SnapTrade |
|------|-----------|--------|-------|-----------|
| Dividends | ✓ (33 events) | ✓ (251 events) | ✓ (33 events) | ✓ |
| Interest | ✓ USD only | ✓ (73 events) | ✓ (16 events) | ✓ |
| Fees | ✓ (bug: double-count) | ✓ | Partial | Partial |
| Stamp Tax | ✗ | N/A | N/A | N/A |

Run `get_performance(mode="realized", source=X)` for each provider and
check `income_summary_usd` in the output to verify income flows through.

---

## Expected Impact

### Part 1 (Starting Cash Anchor)
- Inception NAV: $18,358 → $22,371 (within $87 of IBKR's $22,284)
- TWR gap: 4.2pp → ~0.3pp (residual from FMP vs IBKR pricing + timing)
- `high_confidence_realized`: should flip to `true` (recon gap < 5%)

### Part 2 (Fee Double-Count Fix)
- Fee impact: -$319 → ~-$164 (matches IBKR statement)
- NAV impact: +$155 over the period (fees were over-deducted)
- TWR impact: ~0.7pp improvement

### Part 3 (Minor Items)
- HKD interest: -$9.44 additional deduction
- Stamp tax: -$11.04 additional deduction
- Combined TWR impact: ~0.1pp

---

## Files Modified

| File | Change | Part |
|------|--------|------|
| `ibkr/flex.py` | Extract statement starting cash | 1a |
| `core/realized_performance/engine.py` | Anchor start cash from statement | 1b |
| `core/result_objects/realized_performance.py` | Add anchor metadata fields | 1d |
| `ibkr/flex.py` or `providers/flows/ibkr_flex.py` | Filter fee subtotal rows | 2 |
| `ibkr/flex.py` | HKD interest handling (if needed) | 3a |

## Priority

Part 1 first (closes 95% of gap). Part 2 next (fee accuracy). Part 3 as follow-up.

## Data Points (Current State)

| Metric | Engine | IBKR Statement | Gap |
|--------|--------|---------------|-----|
| End cash | -$8,727 | -$8,727 | $0 |
| Start cash (back-solved) | -$18,750 | -$11,097 | $7,653 |
| Inception NAV | $18,358 | $22,284 | $3,926 |
| TWR | +5.52% | +0.29% | 5.2pp |
| Dividends (Apr+) | +$182.41 | +$182.41 | $0 |
| Interest | -$276 | -$262 | -$14 |
| Fees | -$319 | -$164 | -$155 (bug) |
| Data coverage | 50% | — | — |
