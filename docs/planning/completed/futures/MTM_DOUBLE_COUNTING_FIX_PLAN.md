# Fix: IBKR Flex MTM Currency Double-Counting

## Context

The IBKR Flex `StatementOfFundsLine` section reports each futures Position MTM
settlement event in **both** the native trading currency (e.g. HKD for MHI Hang
Seng futures) and the account base currency (USD). These are the same cash
settlement expressed in two currencies, not two independent cash impacts.

Our normalizer `normalize_flex_futures_mtm()` deduplicates by
`(account_id, date, raw_symbol, amount, currency)` — since both `amount` and
`currency` differ between the two rows, both pass through. This doubles the
MTM cash impact for every non-USD futures contract.

**Measured impact**: For the IBKR reconciliation dataset (Apr 2025 - Mar 2026),
MHI MTM is double-counted: ~$4,353 appears in both HKD (native) and USD
(converted). Fixing this alone brings the cash back-solve starting balance from
$3,997 error to $356 error vs the official IBKR statement (-$11,097 ground truth).

### Evidence

From live DB data (101 MTM events total, 32 are MHI):
- 16 MHI events in HKD (native currency)
- 16 MHI events in USD (base currency conversion)
- Paired by date with exact FX ratios (e.g. Apr 7: HKD -30,180 / USD -3,885.37 = 0.1287 HKD/USD)

Statement ground truth vs engine:
- Statement Cash Settling MTM (base currency): -$3,588.60
- Engine MTM (naive sum, double-counted): -$9,602.53
- Engine MTM (deduped, USD-only): -$5,249.90

### Data Validation (from live DB)

Confirmed via direct DB query:
- Exactly ONE MTM row per `(account, date, contract, currency)` — no same-currency duplicates exist
- 16 events have both HKD+USD (MHI) — these are the cross-currency duplicates
- 69 events have only USD (MES, MGC, ZF) — all single-currency events are USD
- The `(account_id, date, raw_symbol)` key is safe: IBKR emits exactly one MTM per contract per day per currency

## Codex Review Feedback (Round 1: FAIL)

1. **HIGH — USD hardcode**: "prefer USD" isn't base-currency-safe for non-USD base accounts (e.g. EUR base + HKD native would keep wrong row).
   - **Resolution**: Accept `base_currency` as parameter (default `"USD"`), documented as account base currency. All current users have USD base. If a non-USD-base account is added, caller can pass the correct value.

2. **HIGH — Dedup key too coarse**: `(account_id, date, raw_symbol)` could collapse legitimate same-currency multi-row events.
   - **Resolution**: DB query confirms IBKR sends exactly one row per (account, date, contract, currency). The key is safe. But to be defensive: only collapse when multiple currencies exist for the same key. If all entries share the same currency, keep all of them.

3. **MEDIUM — Test gaps**: Need row-order independence and same-currency/different-amount preservation.
   - **Resolution**: Add these tests.

4. **MEDIUM — Cleanup SQL hardcoded user_id=1**.
   - **Resolution**: Remove user_id filter (clean all users), or parameterize.

## Changes

### 1. Fix normalizer dedup - `ibkr/flex.py`

**Function**: `normalize_flex_futures_mtm()` (line 653)

**Current**: Single-pass with dedup key `(account_id, date, raw_symbol, amount, currency)`.

**New**: Two-pass approach with `base_currency` parameter (default `"USD"`):
1. First pass: collect all valid MTM candidates with exact-duplicate dedup
   using `(account_id, date, raw_symbol, amount, currency)` — same as today.
   This preserves the existing behavior of collapsing identical segment copies
   (tested by `test_normalize_flex_futures_mtm_dedup_uses_raw_contract_symbol`).
2. Second pass (NEW): group surviving events by `(account_id, date, raw_symbol)`.
   For groups with **multiple currencies**, keep only the `base_currency` entry.
   If no `base_currency` entry exists, keep all entries in the group (no data loss;
   downstream FX handles any currency).

This preserves correct behavior for:
- USD-only futures (MES, ZF, MGC) — unchanged, single row per event
- Non-USD futures with both rows (MHI HKD+USD) — keeps USD, drops HKD duplicate
- Non-USD futures with only native row — keeps it (no data loss)
- Different contract months same day (ZFM5 vs ZFN5) — still separate events (raw_symbol differs)
- Exact same-currency duplicates (segment copies) — collapsed as before
- Hypothetical same-currency/different-amount rows — preserved (not collapsed)

### 2. Update tests - `tests/ibkr/test_flex_futures_mtm.py`

- **Keep** `test_normalize_flex_futures_mtm_keeps_hkd_and_eur_currencies`:
  Uses MHI and MGC on DIFFERENT dates — distinct events, both kept. No change needed.

- **Add** `test_normalize_flex_futures_mtm_dedup_cross_currency_same_event`:
  Two rows for the same (account, date, contract) in HKD and USD -> only 1 output (USD preferred).

- **Add** `test_normalize_flex_futures_mtm_keeps_native_when_no_base_currency`:
  A non-USD event with no USD counterpart -> kept as-is.

- **Add** `test_normalize_flex_futures_mtm_cross_currency_dedup_order_independent`:
  Same as cross-currency test but with USD row BEFORE HKD row — same result.

- **Add** `test_normalize_flex_futures_mtm_same_currency_different_amounts_preserved`:
  Two USD rows for same (account, date, contract) with different amounts -> both kept
  (exact-duplicate dedup only collapses when amount AND currency match).

- **Add** `test_normalize_flex_futures_mtm_non_usd_base_currency_override`:
  Pass `base_currency="EUR"`, provide EUR+HKD rows for same event -> EUR kept.

- **Add** `test_normalize_flex_futures_mtm_no_base_match_keeps_all`:
  Multi-currency group where neither matches `base_currency` -> all kept
  (downstream FX handles conversion).

### 3. Clean up stored data - one-time DB fix

The transaction store has 101 MTM events (16 HKD duplicates for MHI). After the
normalizer fix, new ingestions will be correct, but existing stored data has the
duplicates.

**Approach**: Delete existing MTM rows and re-ingest:
```sql
DELETE FROM raw_transactions WHERE provider = 'ibkr_flex_mtm';
```
Then trigger re-ingest via `refresh_transactions` or direct Flex fetch.

### 4. Verify with back-solve diagnostic - `scripts/ibkr_cash_backsolve.py`

Re-run the back-solve script after fix + re-ingest to confirm the gap drops
from ~$4,000 to ~$356.

## Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py` | Fix `normalize_flex_futures_mtm()` dedup logic, add `base_currency` param |
| `tests/ibkr/test_flex_futures_mtm.py` | Add 4 new tests for cross-currency dedup |

## Current Code Reference

### Normalizer (`ibkr/flex.py:653-732`)

Current dedup key (line 691-700):
```python
dedup_key = (
    account_id or "",
    event_dt.date().isoformat(),
    raw_symbol,
    round(amount, 8),
    currency,
)
if dedup_key in seen:
    continue
seen.add(dedup_key)
```

### Existing test that validates HKD/EUR (`tests/ibkr/test_flex_futures_mtm.py:113-141`)

```python
def test_normalize_flex_futures_mtm_keeps_hkd_and_eur_currencies() -> None:
    rows = [
        {
            "assetCategory": "FUT",
            "activityDescription": "Position MTM",
            "reportDate": "20250407",
            "accountId": "DU123",
            "symbol": "MHIJ5",
            "amount": "-30000",
            "currency": "HKD",
        },
        {
            "assetCategory": "FUT",
            "activityDescription": "Position MTM",
            "reportDate": "20250408",
            "accountId": "DU123",
            "symbol": "MGCM5",
            "amount": "320.25",
            "currency": "eur",
        },
    ]
    normalized = flex_client.normalize_flex_futures_mtm(rows)
    assert len(normalized) == 2
    assert normalized[0]["currency"] == "HKD"
    assert normalized[1]["currency"] == "EUR"
```

Note: MHI and MGC are on DIFFERENT dates — this does NOT exercise the
cross-currency-same-event dedup scenario.

### Downstream consumer (`core/realized_performance_analysis.py`)

The cash replay in `derive_cash_and_external_flows()` handles FX conversion for
non-USD MTM via `_fx_with_futures_default()`. Keeping USD rows means IBKR's own
FX rate is used (more accurate than our approximation). If only a native-currency
row exists, the downstream FX conversion handles it.

## Design Decisions (Resolved)

1. **Base currency**: Parameterized as `base_currency="USD"` default. All current
   users have USD base accounts. Caller can override for non-USD-base accounts.
2. **Dedup safety**: Only collapse cross-currency groups. Same-currency groups
   preserved as-is. DB query confirms IBKR sends one row per (account, date,
   contract, currency), so the `(account_id, date, raw_symbol)` key is safe.

## Verification

1. `python3 -m py_compile ibkr/flex.py` — syntax check
2. `pytest -xvs tests/ibkr/test_flex_futures_mtm.py` — all tests pass
3. Re-ingest IBKR Flex data (delete old MTM rows + re-fetch)
4. `python3 scripts/ibkr_cash_backsolve.py` — confirm back-solve gap ~ $356
5. `get_performance(mode="realized", source="ibkr_flex", format="full", output="file")` —
   verify `futures_mtm_cash_impact_usd` is roughly halved vs prior run
