# Fix: Suppress Unpriceable Symbol Cash Impact in Daily TWR

**Date**: 2026-03-02
**Status**: COMPLETE (implemented in commit `8829bb2f`)

## Context

Plaid/Merrill realized performance regressed from -12.93% (0.4pp from actual -12.49%) to +1.51% after Fix H/I switched from monthly Modified Dietz to daily TWR. The entire delta traces to **one month: October 2024** (+16.41% vs -0.06% under Dietz).

**Root cause**: The US Treasury Note 4.25% is unpriceable (B-005, valued at $0 in `price_cache`). Its BUY/SELL transactions still affect the cash replay:
- Oct 8: BUY 100 shares @ $100.06 → cash -$10,006
- Oct 9: BUY 100 shares @ $100.04 → cash -$10,004
- Oct 15: SELL 200 shares @ $100.02 → cash +$20,004

Since the position is valued at $0 in NAV, these cash moves appear as phantom NAV changes. Under monthly Dietz, buy and maturity in the same month cancelled out. Under daily TWR, geometric compounding amplifies the intra-month distortion: the +71.5% daily return on Oct 15 is not offset by the drops on Oct 8-9.

### Daily TWR trace for October 2024

```
Oct 7:  NAV  10,185 → 60,095  (+$50K deposit, correct external flow)
Oct 8:  NAV  60,095 → 50,178  (-16.50% — Treasury BUY drains $10K cash, position worth $0)
Oct 9:  NAV  50,178 → 27,264  (-19.76% — Treasury BUY + DSU DRIPs + $13K withdrawal)
Oct 14: NAV  27,416
Oct 15: NAV  27,416 → 47,745  (+71.49% — Treasury SELL returns $20K cash, position was $0)
```

The +71.5% on Oct 15 compounds with prior drops to produce +16.41% for the month instead of ~0%.

## Fix

Suppress BUY/SELL/SHORT/COVER cash impact for unpriceable symbols in `derive_cash_and_external_flows()`, following the existing futures-notional-suppression pattern. Only fees hit cash.

### File: `core/realized_performance_analysis.py`

**Step 1. Add `suppress_symbols` parameter to `derive_cash_and_external_flows`** (line 1547)

```python
def derive_cash_and_external_flows(
    fifo_transactions: ...,
    ...
    suppress_symbols: Optional[Set[str]] = None,   # NEW
    ...
)
```

**Step 2. Add suppression logic after the `is_futures` branch** (after line 1756, before line 1757's `else`)

In the event loop, when `not is_futures` and the event's `symbol` is in `suppress_symbols`, suppress the notional cash impact (BUY/SELL/SHORT/COVER) but allow fees through. Track suppression in `replay_diagnostics`. Pattern mirrors the futures suppression at lines 1745-1756.

```python
# After the is_futures block, before the normal BUY/SELL logic:
symbol = str(event.get("symbol") or "").strip()
if not is_futures and symbol in _suppress and event_type in {"BUY", "SELL", "SHORT", "COVER"}:
    notional = event["price"] * event["quantity"] * fx
    unpriceable_suppressed_usd += abs(notional)
    unpriceable_suppressed_count += 1
    fee_impact = -(event["fee"] * fx)
    cash += fee_impact
    # skip normal BUY/SELL cash logic
else:
    # existing BUY/SELL/SHORT/COVER/INCOME/PROVIDER_FLOW logic
```

**Step 3. Add diagnostics fields to `replay_diagnostics`** and `_finalize_replay_diag()`

New fields in the `replay_diagnostics` dict (accumulated in `derive_cash_and_external_flows`, finalized in `_finalize_replay_diag()`):
- `unpriceable_suppressed_count`: number of suppressed events
- `unpriceable_suppressed_usd`: total notional suppressed
- `unpriceable_suppressed_symbols`: list of affected symbols

These get flattened into `realized_metadata` at the same level as existing `futures_notional_suppressed_usd` (lines 4980-4988), following the same pattern:
```python
"unpriceable_suppressed_count": int(cash_replay_diagnostics.get("unpriceable_suppressed_count", 0)),
"unpriceable_suppressed_usd": round(cash_replay_diagnostics.get("unpriceable_suppressed_usd", 0.0), 2),
"unpriceable_suppressed_symbols": list(cash_replay_diagnostics.get("unpriceable_suppressed_symbols", [])),
```

The same flattening must also be added in the per-account aggregation path (`_analyze_realized_performance_account_aggregated`, line ~5963).

**Step 4. Wire `unpriceable_symbols` through all call sites**

`unpriceable_symbols` is already in scope of the `_compose_cash_and_external_flows` closure (built at line 3556, closure defined at line 3768). Pass it to all `derive_cash_and_external_flows` calls:

- 8 calls inside `_compose_cash_and_external_flows` (lines 3851, 3918, 3943, 3971, 4103, 4212, 4221, **4240**)
- 1 direct call for the observed-only branch (line 4430)

All 9 get `suppress_symbols=unpriceable_symbols`. The line 4240 call is the mixed-authority fallback partition path — missing it would leak phantom cash effects through that code path.

**Step 5. Add a warning when suppression fires**

After the cash replay, if `unpriceable_suppressed_count > 0`, append a warning like:
```
"Cash replay: suppressed $X notional from N unpriceable-symbol transaction(s) (SYMBOLS)."
```

### Blanket suppression is correct

`unpriceable_symbols` can include symbols beyond just the Treasury (options, FX artifacts, bonds without CUSIP, etc.). Blanket suppression is correct for all of them: if a symbol's position value is $0 in NAV (because it's unpriceable), its trade cash impact creates the same phantom NAV inconsistency regardless of the reason. The alternative — maintaining a whitelist of "acceptable" unpriceable reasons — adds complexity with no correctness benefit.

Note: suppressing unpriceable cash impact will also prevent some inferred injections/withdrawals (since cash won't go as negative). This is intentional — those injections were themselves phantom artifacts of the unpriceable cash drain.

### What NOT to change

- **INCOME events**: Not symbol-tagged in the event dict (line 1666-1677), so they can't be filtered by symbol. The Treasury interest ($425 on Oct 15) is a real provider flow marked `is_external_flow=True` — it correctly enters the TWR denominator. No change needed.
- **PROVIDER_FLOW events**: These are real deposits/withdrawals ($50K, $13K, etc.). They are correct and must remain.
- **position_timeline**: The Treasury still appears in the timeline (needed for data_coverage tracking), but its $0 price means it contributes nothing to NAV. No change needed.
- **DSU transactions**: DSU is priceable — it has valid prices in `price_cache`. Only symbols in `unpriceable_symbols` are suppressed.

## Expected Result

| Month | Before Fix | After Fix | Actual |
|-------|-----------|-----------|--------|
| Oct 2024 | +16.41% | ~-0.06% (matching Dietz) | — |
| Chain total | +1.51% | ~-7.96% | -12.49% |

The fix should restore Plaid to approximately the pre-Fix-H result (-7.96%), eliminating the +16.5pp October distortion. The remaining ~4.5pp gap to actual (-12.49%) is a separate issue (likely the observed-only track not being wired, per B-014).

## Verification

1. Run `get_performance(source='plaid', mode='realized', format='agent', output='file')` and check:
   - October 2024 monthly return should be close to -0.06% (not +16.41%)
   - Chain-linked total should be roughly -8% to -10% (not +1.51%)
   - `cash_replay_diagnostics.unpriceable_suppressed_count` > 0
   - `cash_replay_diagnostics.unpriceable_suppressed_usd` ≈ $40K (two buys + one sell)

2. Run existing tests: `python -m pytest tests/test_realized_performance*.py -x`

3. Verify IBKR and Schwab are unaffected (they have no unpriceable symbols in their BUY/SELL transactions):
   - `get_performance(source='ibkr_flex', mode='realized')` → should still be -11.37%
   - `get_performance(source='schwab', mode='realized')` → should still be +23.13%
