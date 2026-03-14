# Futures Transaction MTM Fix Plan

**Status:** PLANNED
**Priority:** High
**Added:** 2026-03-06
**Parent:** IBKR_NAV_GAP_FIX_PLAN.md (Fix 2 — Cash Replay Discrepancy)

## Problem

The realized performance engine's cash replay is missing **$1,654** in futures
cash flows. This accounts for the bulk of the remaining ~$3,104 cash replay
gap identified in Fix 2.

### Root Cause

IBKR's Cash Report "Cash Settling MTM" line includes **two** components:

| Component | Description | Engine captures? |
|-----------|-------------|-----------------|
| **Position MTM** | Daily variation margin (settlement_today - settlement_yesterday) | Yes (81 events) |
| **Transaction MTM** | Trade execution P&L (trade_price vs settlement_price on trade day) | **No** |

The normalizer `normalize_flex_futures_mtm()` in `ibkr/flex.py:827-830`
filters for `"POSITION MTM" in description` and explicitly drops rows starting
with `"BUY"` or `"SELL"`. These Buy/Sell rows in the StmtFunds section ARE the
Transaction MTM — they represent the cash impact of executing a trade at a
price different from that day's settlement.

Additionally, the engine (`nav.py:273-276`) suppresses futures trade notional
for FIFO events, so the Transaction MTM is not captured through any path.

### Verified Data

**Flex StmtFunds FUT rows (raw):** 182 total
- Position MTM: 162 rows (81 unique after dedup)
- Buy/Sell trade execution: 20 rows (10 unique USD after dedup)
- No "Transaction MTM" named rows exist — IBKR embeds them as Buy/Sell rows

**April+ comparison (statement period: April 1, 2025 - March 3, 2026):**

| Component | Engine | IBKR Statement | Gap |
|-----------|--------|---------------|-----|
| Position MTM | -$5,249.90 | — | — |
| Transaction MTM | $0 (missing) | — | — |
| Combined | -$5,249.90 | -$3,588.60 | $1,661.30 |
| With Txn MTM fix | -$3,595.79 | -$3,588.60 | **$7.19** (= futures commission) |

**Transaction MTM by symbol (April+):**

| Date | Symbol | Description | USD Amount |
|------|--------|-------------|-----------|
| 2025-04-01 | MGCM5 | Buy 1 MGC 26JUN25 | -$52.87 |
| 2025-04-04 | MGCM5 | Sell -1 MGC 26JUN25 | +$57.13 |
| 2025-04-07 | MHIJ5 | Sell -1 MHI 29APR25 | +$1,094.68 |
| 2025-04-09 | ZFM5 | Sell -1 ZF 30JUN25 | +$521.92 |
| 2025-04-14 | MGCM5 | Buy 1 MGC 26JUN25 | +$3.13 |
| 2025-05-28 | MGCM5 | Sell -1 MGC 26JUN25 | +$30.13 |
| | | **Total** | **+$1,654.12** |

**Overlap verification:** On trade dates, Position MTM and Buy/Sell rows
coexist for the same symbol. They are **additive** — different components of
that day's total cash flow. Example on April 7 MHIJ5:
- Position MTM: -$3,885.37 (daily variation)
- Sell -1 MHI: +$1,094.68 (trade execution P&L)
- Combined: -$2,790.69 (total cash impact that day)

### No Double-Counting Risk

The engine handles futures trades specially (`nav.py:273-276`):
```python
if is_futures:
    if event_type in {"BUY", "SELL", "SHORT", "COVER"}:
        futures_notional_suppressed_usd += abs(event["price"] * event["quantity"] * fx)
        fee_cash_impact = -(event["fee"] * fx)
```
Futures trade notional is **suppressed** — only the fee is applied. The FIFO
matcher does not compute realized P&L for futures. So Transaction MTM events
from StmtFunds would be the ONLY path for this cash flow — no double-counting.

## Changes

### 1. Normalizer: allowlist Position MTM + trade execution — `ibkr/flex.py`

**Location:** `normalize_flex_futures_mtm()` (~line 825-830)

**Current filter:**
```python
description = str(row.get("activityDescription") or row.get("description") or "").strip()
description_upper = description.upper()
if "POSITION MTM" not in description_upper:
    continue
if description_upper.startswith("BUY") or description_upper.startswith("SELL"):
    continue
```

**New filter:**
```python
description = str(row.get("activityDescription") or row.get("description") or "").strip()
description_upper = description.upper()
is_position_mtm = "POSITION MTM" in description_upper
is_trade_execution = description_upper.startswith("BUY ") or description_upper.startswith("SELL ")
if not is_position_mtm and not is_trade_execution:
    continue
```

This is an explicit allowlist:
- `"POSITION MTM"` → daily variation margin (existing behavior)
- `"BUY "` / `"SELL "` with trailing space → trade execution rows like
  `"Buy 1 MGC 26JUN25"`, `"Sell -1 MES 21MAR25"`

The trailing space prevents matching non-settlement descriptions like
hypothetical `"BuyBack"` or `"SellOff"` patterns. Commission adjustments
(e.g. `"Buy commission adjustment"`) ARE matched — but these would only
appear as FUT StmtFunds rows if they represent actual cash settlements,
and their amounts would be small ($2-5). In practice, IBKR commission
adjustments appear in the CashTransaction section, not StmtFunds.

Non-settlement FUT rows (if any existed) are still filtered out.

**Docstring:** Update from "Position MTM rows" to "cash-settlement rows"
(Position MTM + trade execution).

### 2. Dual-currency dedup — `ibkr/flex.py`

The existing dual-currency dedup logic (lines 889-915) groups by
`(account_id, date, raw_symbol)` and keeps only base-currency rows when both
USD and HKD exist.

**Edge case reviewed:** On a trade date, the group `(acct, date, MHIJ5)` now
contains both Position MTM rows (USD + HKD) AND trade execution rows
(USD + HKD). The dedup drops ALL non-base-currency rows in the group — so
both HKD Position MTM and HKD trade execution are dropped, keeping both USD
rows. This is correct: Position MTM USD + trade execution USD = total
base-currency cash impact for that day.

**Theoretical edge case:** If a trade execution row existed only in HKD (no
USD twin) but the group contained USD Position MTM rows, the HKD trade row
would be incorrectly dropped. However, IBKR always reports StmtFunds in both
settlement currency AND base currency for cross-currency instruments — verified
across all MHI rows in our data. Every HKD row has a corresponding USD row.

**No changes needed** — existing logic handles mixed row types correctly for
IBKR's actual output format.

### 3. Store dedup key — `inputs/transaction_store.py`

The `_dedup_key()` for `ibkr_flex_mtm` uses content-based key:
`mtm:{acct}:{dt}:{sym}:{amt}:{ccy}`. Position MTM and Transaction MTM events
have different amounts for the same date/symbol, so they naturally get
different keys.

**Collision risk:** If a Position MTM and trade execution row had the exact
same amount on the same date/symbol/currency, the keys would collide and one
would be lost. In practice this is extremely unlikely — Position MTM is a
daily settlement delta while Transaction MTM is a trade-vs-settlement delta,
computed from different price pairs. Verified against our data: no collisions
exist across all 91 events. Add `description[:20]` to dedup keys in **all
three** dedup layers:

**Layer 1 — Normalizer in-memory** (`ibkr/flex.py` `seen` set, ~line 854):
```python
dedup_key = (
    account_id or "",
    event_dt.date().isoformat(),
    raw_symbol,
    round(amount, 8),
    currency,
    description[:20],
)
```

**Layer 2 — Store insert** (`_dedup_key()` for `ibkr_flex_mtm`, ~line 1820):
```python
desc = (self._text_or_none(row.get("description")) or "")[:20]
return f"mtm:{acct}:{dt}:{sym}:{amt}:{ccy}:{desc}"
```

**Layer 3 — Store load** (`load_futures_mtm()` read-side dedup, ~line 1537):
```python
dedup_key = (
    str(payload.get("account_id") or ""),
    str(payload.get("date") or ""),
    str(payload.get("symbol") or ""),
    round(float(payload.get("amount") or 0), 8),
    str(payload.get("currency") or "USD"),
    str(payload.get("description") or "")[:20],
)
```

This distinguishes `"Position MTM..."` from `"Buy 1 MGC..."` even if amounts
match. The `[:20]` truncation keeps keys compact. All three layers must be
updated to prevent same-amount rows from colliding at normalize, write, or
read time.

### 4. Update tests — `tests/ibkr/test_flex_futures_mtm.py`

**Update** `test_normalize_flex_futures_mtm_skips_non_mtm_and_buy_sell_rows`:
- Rename to `test_normalize_flex_futures_mtm_filters_non_settlement_rows`
- Keep the STK row → still filtered (asset_category != FUT)
- Replace "Buy commission adjustment" with a non-settlement FUT description
  (e.g. `"Futures interest accrual"`) → still filtered by allowlist
- Add a "Buy 1 MESM5" FUT trade row → now included
- Assert 2 results (Position MTM + trade execution)

**Add** `test_normalize_flex_futures_mtm_includes_trade_execution_rows`:
- Input: Position MTM + "Buy 1 ZFM5" + "Sell -1 ZFM5" rows on same date
- Assert all 3 are included with correct amounts
- Verify they coexist (additive, not duplicates)

**Add** `test_normalize_flex_futures_mtm_rejects_non_settlement_fut_rows`:
- Input: FUT rows with descriptions like `"Futures interest accrual"`,
  `"Commission adjustment"`, `"Transfer"` — none matching Position MTM or
  `BUY `/`SELL ` prefix
- Assert 0 results — confirms the allowlist filters non-settlement rows

**Add** `test_normalize_flex_futures_mtm_cross_currency_mixed_types`:
- Input: Position MTM (USD + HKD) + trade execution (USD + HKD) on same
  date/symbol
- Assert 2 results (Position MTM USD + trade execution USD)
- Verify both HKD rows dropped by dual-currency dedup

**Add** `test_normalize_flex_futures_mtm_same_amount_different_types`:
- Input: Position MTM row AND "Buy 1 ZFM5" row with identical
  (account, date, symbol, amount, currency) but different descriptions
- Assert 2 results — description in dedup key prevents collision at
  normalizer level

**Add** `test_load_futures_mtm_preserves_same_amount_different_types`:
- Store two MTM rows with identical (acct, date, symbol, amount, currency) but
  different descriptions ("Position MTM" vs "Buy 1 ZFM5")
- Load via `load_futures_mtm()` and assert both survive (description in
  load-side dedup key)

### 5. DB cleanup + re-ingest

After code change:
1. Delete existing `ibkr_flex_mtm` rows: `DELETE FROM raw_transactions WHERE provider = 'ibkr_flex_mtm' AND user_id = 'henrychien@gmail.com'`
2. `/mcp` reconnect to pick up code changes
3. Re-ingest via `refresh_transactions` or `ensure_store_fresh()`
4. Verify: 91 rows (81 pos_mtm + 10 txn_mtm) vs previous 81

## Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py` | Replace description filter with allowlist, add `description[:20]` to in-memory dedup key, update docstring |
| `inputs/transaction_store.py` | Add `description[:20]` to `ibkr_flex_mtm` insert-time dedup key AND load-time dedup key |
| `tests/ibkr/test_flex_futures_mtm.py` | Update filter test, add trade execution / negative / collision / cross-currency tests |

## Expected Impact

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| MTM events (DB) | 81 | 91 | +10 |
| Engine futures MTM total | -$5,411 | -$3,955 | +$1,456 |
| April+ engine MTM | -$5,250 | -$3,596 | +$1,654 |
| Cash replay gap vs IBKR | ~$3,104 | ~$1,450 | -$1,654 |

The remaining ~$1,450 gap after this fix is from other cash replay drivers:
- FX translation ($54)
- Internal segment transfers ($1,408 securities <-> futures)
- Futures commission accounting differences ($7)

## Verification

1. `python3 -m pytest tests/ibkr/test_flex_futures_mtm.py -v` — updated tests pass
2. `python3 -m pytest tests/ -k flex -x -q` — no regressions
3. DB: `SELECT count(*) FROM raw_transactions WHERE provider = 'ibkr_flex_mtm'` → 91
4. MCP: `get_performance(mode="realized", source="ibkr_flex")` — check `futures_mtm_cash_impact_usd` closer to -$3,596 vs previous -$5,250
