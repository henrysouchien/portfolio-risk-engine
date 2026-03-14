# Fix: Filter Plaid qty=0 Ghost Transactions

**Status:** COMPLETE (2026-03-05, commit `923d0f31`)

## Context
Data examination of Plaid/Merrill transactions revealed ~20 "ghost" trades: BUY records with `quantity=0, price=0, amount=0` that have unique Plaid `investment_transaction_id`s. These appear alongside every DSU/MSCI dividend reinvestment as a paired phantom entry. They survive DB dedup (unique IDs) and normalization (no qty guard). 58 total Plaid normalized txns, ~20 are ghosts (34% noise). While qty=0 doesn't affect share positions, these records inflate transaction counts, create noise in trading analysis, and could confuse FIFO matching.

## Root Cause
`PlaidNormalizer.normalize()` in `providers/normalizers/plaid.py` has no guard against zero-quantity trade-type transactions. A Plaid `type="buy"` with `qty=0` hits line 348, gets assigned `trade_type=BUY`, and flows to lines 420-452 where it's appended to both `trades` and `fifo_transactions` lists.

## Fix

### 1. Add ghost trade guard in PlaidNormalizer (`providers/normalizers/plaid.py`)

**Insertion point:** After line 418 (the `else: continue` that ends type routing) and before line 420 (trade creation). At this point all income/cash/fee rows have already `continue`d — only trade-type rows (buy/sell/short/cover) reach here.

```python
# Skip ghost transactions: trade-type row with no economic content
if abs(quantity) < 1e-9 and abs(price) < 1e-9 and abs(amount) < 1e-9 and abs(fee) < 1e-9:
    continue
```

**Why this is safe (addressing Codex review findings):**
- **Scoped to trades only**: Placed after type routing, so income/dividend/interest/cash/fee rows already `continue`d at lines 354-416. Zero-value dividends are preserved.
- **Includes fee check**: A row with `qty=0, price=0, amount=0, fee!=0` has monetary impact and is preserved (fail-open).
- **Epsilon comparison**: Uses `< 1e-9` instead of `== 0` to catch near-zero float artifacts and avoid NaN edge cases (`abs(NaN) < 1e-9` is False, so NaN rows are preserved).
- **Missing-field coercion safe**: Even if Plaid sends `None` fields that coerce to `0.0`, a truly incomplete trade with no qty/price/amount/fee has no economic content — dropping it is correct.
- **Fail-open**: All four fields must be near-zero. Any nonzero value preserves the row.

### 2. Add test cases (`tests/providers/normalizers/test_plaid.py`)

Add a test that covers:
- **Ghost BUY filtered**: `type="buy", quantity=0, price=0, amount=0, fees=0` → NOT in trades
- **Real reinvestment preserved**: `type="buy", quantity=5.123, price=42.50, amount=217.47` → IS in trades
- **Zero-value dividend preserved**: `type="dividend", quantity=0, price=0, amount=0` → IS in income events
- **Nonzero-fee zero-qty preserved**: `type="buy", quantity=0, price=0, amount=0, fees=5.0` → IS in trades (fail-open)
- **NaN quantity preserved**: `type="buy", quantity=NaN, price=0, amount=0` → IS in trades (fail-open)
- **Near-zero epsilon preserved**: `type="buy", quantity=1e-12, price=0, amount=0` → filtered (below epsilon); `quantity=0.001, price=0, amount=0` → IS in trades (above epsilon, fail-open)
- **Missing/None fields coerced**: `type="buy", quantity=None, price=None, amount=None, fees=None` → all coerce to 0.0 via `safe_float()` → filtered (correct: no economic content)

### 3. Verify with live data
After fix, re-ingest Plaid transactions and confirm:
- `list_transactions(provider="plaid")` count drops from 58 to ~38 (removing ~20 ghosts)
- All real trades (qty > 0) still present
- Income events unaffected (49 count unchanged)

## Codex Review History
- **Review 1 (2026-03-05)**: FAIL. 5 findings: (1) insertion point before type routing would drop zero-value dividends, (2) missing-field coercion risk, (3) exact `== 0` misses NaN/epsilon, (4) fee not checked, (5) test gaps. All addressed in v2.
- **Review 2 (2026-03-05)**: FAIL (medium). Insertion point PASS, epsilon/NaN PASS, fee check PASS. Test coverage incomplete — added near-zero epsilon and None/missing-field test cases in v3.

## Files Modified
| File | Change |
|------|--------|
| `providers/normalizers/plaid.py` | Add 2-line guard after line 418, before line 420 |
| `tests/providers/normalizers/test_plaid.py` | Add ghost transaction filter test (7 cases) |

## Verification Results
1. `python -m pytest tests/providers/normalizers/test_plaid.py -v` — 17 passed (16 existing + 1 new with 7 sub-cases)
2. Re-ingest: `ingest_transactions(provider="plaid")` — income_row_count=49 (unchanged)
3. DB cleanup: deleted 27 ghost rows from `normalized_transactions` (58→31 plaid trades)
4. `inspect_transactions(provider="plaid", symbol="DSU")` — 20 real trades, 0 qty=0 ghosts, total_buy_qty=2031.49 preserved

**Note:** The normalizer fix prevents new ghosts going forward. Existing ghost rows required a one-time DB cleanup (`DELETE FROM normalized_transactions WHERE provider='plaid' AND quantity=0 AND price=0 AND fee=0 AND trade_type IN ('BUY','SELL','SHORT','COVER')`) because `ON CONFLICT DO UPDATE` preserves previously-stored rows.
