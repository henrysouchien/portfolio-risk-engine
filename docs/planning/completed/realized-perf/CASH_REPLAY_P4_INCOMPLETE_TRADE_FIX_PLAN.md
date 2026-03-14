# P3.1 Fix: Balance Futures Position Events When Synthetic Opening Filtered

## Sequencing Note (2026-02-26)

This document supersedes the original P4 plan (incomplete trade cash suppression), which was based on a flawed analysis. The actual root cause is a **P3 regression** where futures incomplete trade transactions were left in the position timeline after their synthetic openings were removed.

Prior phases:
- **P1** (`efd8f1a6`): UNKNOWN/fx_artifact filtering + futures inference gating
- **P2A** (`eb9fc423`): Synthetic cash events excluded from replay + sensitivity gate diagnostic-only
- **P2B** (`1d943108`): Futures fee-only cash replay + income/provider overlap dedup
- **P3** (`0e533cb7`): Global inception for synthetics + futures incomplete trade filter

## Problem

After P3, IBKR returns **regressed** from -68.88% to -100.00% (actual: -9.35%). The root cause is a **position timeline asymmetry for futures transactions**.

P3 correctly filtered `synthetic_incomplete_trade` entries for futures (line 1255-1265), preventing futures from appearing as priced synthetic positions. However, it did NOT account for the **real transaction events** for those same futures already in `position_events`. The fifo_transactions loop (lines 1104-1148) processes SELL/COVER events for futures and adds them to `position_events` BEFORE the futures filter runs in the incomplete trade loop.

### Concrete example: MES in March 2025

1. **fifo_transactions loop** (line 1104): MES SELL 5 @ $5,653 is processed. `position_events[("MES", "USD", "LONG")]` gets `(March 10, -5)`.
2. **Incomplete trade loop** (line 1220): IncompleteTrade for MES (qty=5, direction=LONG). P3 filter at line 1255 fires → synthetic opening `(March 9 23:59:59, +5)` is NOT created. `filtered_keys.add(("MES", "USD", "LONG"))`.
3. **Result**: position_events for MES has only the SELL (-5), no opening (+5). At March 31: cumulative qty = -5. Position value = -1 × (-5) × $5,653 = **-$28,266** (SHORT-signed LONG with negative qty).

This -$28K phantom negative position value is the primary reason March NAV goes negative (-$10,178 vs February's +$13,667), which triggers V_adjusted <= 0 and cascades into a -100% total return.

### Monthly NAV trace (current P3 state)

| Month | Position Value | Cash | NAV | Notes |
|-------|---------------|------|-----|-------|
| Feb 2025 | +$14,671 | -$1,004 | **+$13,667** | 9 positions, MES not yet sold |
| Mar 2025 | -$13,109 | +$2,930 | **-$10,178** | MES -$28K dominates |
| Apr 2025 | -$9,713 | +$16,628 | **+$6,915** | Recovers (more SELLs add cash) |

Without the MES phantom negative, March positions would be: -$13,109 + $28,266 = +$15,157. March NAV = +$15,157 + $2,930 = **+$18,087**. Positive, and the -100% cascade would not occur.

### Why the original P4 analysis was wrong

The original P4 plan proposed suppressing SELL cash for incomplete trades. This was based on the assumption that incomplete trade SELLs add "phantom positive cash" without matching position value. In reality:

1. **Non-futures incomplete trades**: Their `synthetic_incomplete_trade` entries ARE in the position timeline (+qty at sell_date - 1s). The SELL subtracts the same qty. The position nets to 0 at month-end. The SELL cash IS balanced — it converts position value to cash, not phantom cash.

2. **Futures incomplete trades**: Their `synthetic_incomplete_trade` entries are FILTERED by P3. But their SELL transactions are fee-only (P2B), contributing negligible cash. The problem is the position timeline, not the cash replay.

## Fix

**Approach**: For each filtered futures IncompleteTrade **that does NOT already have a current-position synthetic covering the exit**, add a **compensating positive event** to `position_events` that balances the unmatched SELL quantity. The compensating event is placed at `sell_date - 1s` (same timing as the filtered synthetic would have used). Since both the compensating opening and the real SELL occur within the same day, the position nets to 0 at every month-end. No phantom positive or negative NAV is created.

**Why skip keys with current-position synthetics**: When a futures symbol is BOTH a current holding AND has an incomplete trade, the current-position synthetic at line 1188 already computes `required_entry_qty = abs(shares) + exit_qty.get(key, 0.0)`. The `exit_qty` includes the SELL from the incomplete trade, so the synthetic current position already accounts for the exit. Adding a compensating event would double-count: e.g., shares=3, SELL=2 → current synthetic +5, compensating +2, SELL -2 = net 5 (should be 3).

This fix is surgical: it only adds the exact incomplete quantity for filtered futures keys that lack current-position coverage. It does NOT delete any existing events.

**Additional change**: Move ALL incomplete trade synthetic placement from `sell_date - 1s` to `inception_date - 1s`. This ensures the position has month-end value from inception → SELL converts position to cash (roughly neutral for Modified Dietz) instead of SELL cash appearing as phantom return. Without this, non-futures incomplete trade SELLs inflate returns because the position exists for only 1 second (same day as SELL), contributing no month-end value.

### File: `core/realized_performance_analysis.py`

#### Change 1: Track filtered futures incomplete keys separately — at line 1264

Currently the P3 futures filter adds keys to the generic `filtered_keys` set (line 1264). We need a dedicated set to avoid conflating with fx_artifact/unknown filtered keys.

**Add** before the incomplete trade loop (before line ~1220):
```python
        filtered_futures_incomplete_keys: Set[Tuple[str, str, str]] = set()
```

**Modify** line 1264 to also add to the dedicated set:
```python
            filtered_keys.add(key)
            filtered_futures_incomplete_keys.add(key)
            continue
```

The existing `filtered_keys.add(key)` stays — it's still needed for the generic filtering logic. We just ALSO track it in the dedicated set.

#### Change 2: Add compensating events for filtered futures incomplete trades — after line 1286

After the incomplete trade processing loop ends (line 1286), before the events sort at line 1288:

**Insert:**
```python
        # For filtered futures incomplete trades, add compensating position events
        # to balance the unmatched SELL/COVER that's already in position_events
        # from the fifo_transactions loop above.
        #
        # P3 correctly filters the synthetic_incomplete_trade entry for futures
        # (no priced synthetic should appear in synthetic_entries). But the real
        # SELL/COVER from fifo_transactions is already in position_events, creating
        # an unbalanced negative quantity (e.g., MES SELL -5 with no +5 opening).
        #
        # The compensating event opens the position at sell_date - 1s, so the
        # position nets to 0 at month-end. Since both events (opening and close)
        # occur within the same day, no month-end valuation picks up a non-zero
        # futures position. This prevents phantom negative NAV without creating
        # phantom positive NAV.
        #
        # SKIP keys that also have a current-position synthetic
        # (current_position_synthetic_keys): the synthetic_current_position at
        # line 1188 already computes required_entry_qty = abs(shares) + exit_qty,
        # which includes the incomplete trade's SELL. Adding a compensating event
        # would double-count.
        for _inc in incomplete_trades:
            _inc_sym = str(getattr(_inc, "symbol", "")).strip()
            _inc_ccy = str(getattr(_inc, "currency", "USD")).upper()
            _inc_dir = str(getattr(_inc, "direction", "LONG")).upper()
            _inc_key = (_inc_sym, _inc_ccy, _inc_dir)

            if _inc_key not in filtered_futures_incomplete_keys:
                continue
            if _inc_key in current_position_synthetic_keys:
                continue
            if _inc_key not in position_events:
                continue

            _inc_qty = abs(_as_float(getattr(_inc, "quantity", 0), 0.0))
            _inc_sell_date = _to_datetime(getattr(_inc, "sell_date", None))
            if _inc_qty <= 0 or _inc_sell_date is None:
                continue

            _compensating_date = _inc_sell_date - timedelta(seconds=1)
            position_events[_inc_key].append((_compensating_date, _inc_qty))
```

**Why this is correct:**
- Uses `filtered_futures_incomplete_keys` (not the generic `filtered_keys`), so only futures incomplete trades are affected. fx_artifact/unknown keys are never compensated.
- Skips keys in `current_position_synthetic_keys` — those already have `required_entry_qty = abs(shares) + exit_qty` covering the SELL. No double-counting.
- Only adds quantity matching the IncompleteTrade (the exact unmatched portion from FIFO). Partial matches are handled correctly because `IncompleteTrade.quantity` is already just the unmatched remainder.
- Does NOT modify `synthetic_entries` — the position won't be counted as a synthetic entry or affect synthetic_count diagnostics.
- Does NOT delete any existing events — matched BUY lots, current positions, and other transactions are preserved.

### File: `tests/core/test_realized_performance_analysis.py`

#### Update existing test: `test_futures_incomplete_trade_filtered_from_position_timeline` (line ~5673)

The current test (lines 5673-5721) asserts:
```python
assert not any(e["ticker"] == "MES" for e in synthetic_entries)
assert any("Filtered futures incomplete trade MES" in w for w in warnings)
```

It does NOT currently assert `("MES", "USD", "LONG") not in timeline`. We need to ADD assertions that MES events are balanced:

**Replace the assertion block with:**
```python
    # MES should NOT have synthetic entries (filtered by P3)
    assert not any(e["ticker"] == "MES" for e in synthetic_entries)
    # But MES SHOULD still be in timeline with balanced events (compensating + SELL = 0)
    assert ("MES", "USD", "LONG") in timeline
    mes_events = timeline[("MES", "USD", "LONG")]
    assert abs(sum(q for _, q in mes_events)) < 1e-9  # net qty = 0
    # Warning still emitted for filtering
    assert any("Filtered futures incomplete trade MES" in w for w in warnings)
```

Note: The function signature needs to capture `timeline` too — change from `_, _, synthetic_entries, _, warnings` to `timeline, _, synthetic_entries, _, warnings`.

#### New Test 1: Futures incomplete trade SELL balanced by compensating event

```python
def test_futures_incomplete_trade_sell_balanced_by_compensating_event():
    """P3.1: Filtered futures incomplete trade should have a compensating event
    that balances the SELL, so the position nets to 0 at month-end."""
    from trading_analysis.fifo_matcher import IncompleteTrade

    inception = datetime(2025, 1, 1)
    fifo_transactions = [
        {"symbol": "MES", "type": "SELL", "date": datetime(2025, 3, 10),
         "quantity": 5, "price": 5678.0, "fee": 2.5, "currency": "USD",
         "instrument_type": "futures"},
        {"symbol": "AAPL", "type": "BUY", "date": datetime(2025, 2, 1),
         "quantity": 10, "price": 200.0, "fee": 0, "currency": "USD"},
    ]
    incomplete_trades = [
        IncompleteTrade(
            symbol="MES", currency="USD", direction="LONG",
            quantity=5, sell_date=datetime(2025, 3, 10), sell_price=5678.0,
        ),
    ]

    timeline, _, synthetic_entries, _, warnings = rpa.build_position_timeline(
        fifo_transactions=fifo_transactions,
        current_positions={},
        inception_date=inception,
        incomplete_trades=incomplete_trades,
    )

    # MES should be in timeline with balanced events
    assert ("MES", "USD", "LONG") in timeline
    mes_events = timeline[("MES", "USD", "LONG")]
    # Should have exactly 2 events: compensating +5, SELL -5
    assert len(mes_events) == 2
    assert abs(sum(q for _, q in mes_events)) < 1e-9  # net = 0

    # No synthetic entry for MES (P3 filter still active)
    assert not any(e["ticker"] == "MES" for e in synthetic_entries)

    # AAPL unaffected
    assert ("AAPL", "USD", "LONG") in timeline

    # Warning emitted
    assert any("Filtered futures incomplete trade MES" in w for w in warnings)
```

#### New Test 2: Non-futures incomplete trade position events preserved

```python
def test_non_futures_incomplete_trade_position_events_preserved():
    """P3.1: Non-futures incomplete trades should keep both synthetic and real events."""
    from trading_analysis.fifo_matcher import IncompleteTrade

    inception = datetime(2025, 1, 1)
    fifo_transactions = [
        {"symbol": "GLBE", "type": "SELL", "date": datetime(2025, 3, 5),
         "quantity": 50, "price": 60.0, "fee": 0, "currency": "USD"},
    ]
    incomplete_trades = [
        IncompleteTrade(
            symbol="GLBE", currency="USD", direction="LONG",
            quantity=50, sell_date=datetime(2025, 3, 5), sell_price=60.0,
        ),
    ]

    timeline, _, synthetic_entries, _, _ = rpa.build_position_timeline(
        fifo_transactions=fifo_transactions,
        current_positions={},
        inception_date=inception,
        incomplete_trades=incomplete_trades,
    )

    # GLBE should be in timeline — both synthetic opening and real SELL
    assert ("GLBE", "USD", "LONG") in timeline
    assert any(e["ticker"] == "GLBE" and e["source"] == "synthetic_incomplete_trade" for e in synthetic_entries)
    # The position should net to 0 (synthetic +50, SELL -50)
    events = timeline[("GLBE", "USD", "LONG")]
    net_qty = sum(q for _, q in events)
    assert abs(net_qty) < 1e-9
```

#### New Test 3: Futures incomplete trade with overlapping current position — NO compensating event

```python
def test_futures_incomplete_trade_with_current_position_no_compensation():
    """P3.1: If a futures symbol is BOTH a current holding and has a filtered
    incomplete trade, NO compensating event should be added because the
    current-position synthetic already covers the exit via
    required_entry_qty = abs(shares) + exit_qty."""
    from trading_analysis.fifo_matcher import IncompleteTrade

    inception = datetime(2025, 1, 1)
    fifo_transactions = [
        {"symbol": "MES", "type": "SELL", "date": datetime(2025, 3, 10),
         "quantity": 2, "price": 5678.0, "fee": 2.5, "currency": "USD",
         "instrument_type": "futures"},
    ]
    current_positions = {"MES": {"shares": 3, "currency": "USD", "instrument_type": "futures"}}
    incomplete_trades = [
        IncompleteTrade(
            symbol="MES", currency="USD", direction="LONG",
            quantity=2, sell_date=datetime(2025, 3, 10), sell_price=5678.0,
        ),
    ]

    timeline, _, synthetic_entries, _, warnings = rpa.build_position_timeline(
        fifo_transactions=fifo_transactions,
        current_positions=current_positions,
        inception_date=inception,
        incomplete_trades=incomplete_trades,
    )

    # MES should be in timeline (current position)
    assert ("MES", "USD", "LONG") in timeline
    # Current position synthetic entry should exist
    assert any(
        e["ticker"] == "MES" and e["source"] == "synthetic_current_position"
        for e in synthetic_entries
    )
    # Incomplete trade synthetic entry should NOT exist (filtered by P3)
    assert not any(
        e["ticker"] == "MES" and e["source"] == "synthetic_incomplete_trade"
        for e in synthetic_entries
    )
    # Timeline should have: synthetic current +5 (shares=3 + exit_qty=2), SELL -2
    # Net = 5 - 2 = 3 (the current holding remains)
    # NO compensating event — current-position synthetic already covers the exit
    mes_events = timeline[("MES", "USD", "LONG")]
    net_qty = sum(q for _, q in mes_events)
    assert net_qty == pytest.approx(3.0)
    # Should only have 2 events: synthetic current +5, SELL -2
    assert len(mes_events) == 2
```

#### New Test 4: SHORT/COVER futures incomplete trade balanced

```python
def test_futures_short_cover_incomplete_trade_balanced():
    """P3.1: SHORT direction futures incomplete trade should also be balanced."""
    from trading_analysis.fifo_matcher import IncompleteTrade

    inception = datetime(2025, 1, 1)
    fifo_transactions = [
        {"symbol": "MES", "type": "COVER", "date": datetime(2025, 3, 10),
         "quantity": 3, "price": 5678.0, "fee": 2.5, "currency": "USD",
         "instrument_type": "futures"},
    ]
    incomplete_trades = [
        IncompleteTrade(
            symbol="MES", currency="USD", direction="SHORT",
            quantity=3, sell_date=datetime(2025, 3, 10), sell_price=5678.0,
        ),
    ]

    timeline, _, synthetic_entries, _, warnings = rpa.build_position_timeline(
        fifo_transactions=fifo_transactions,
        current_positions={},
        inception_date=inception,
        incomplete_trades=incomplete_trades,
    )

    # MES SHORT should be in timeline with balanced events
    assert ("MES", "USD", "SHORT") in timeline
    mes_events = timeline[("MES", "USD", "SHORT")]
    assert abs(sum(q for _, q in mes_events)) < 1e-9  # net = 0
    assert not any(e["ticker"] == "MES" for e in synthetic_entries)
```

## Why existing tests pass unchanged

- `test_futures_incomplete_trade_filtered_from_position_timeline` (line ~5673): **NEEDS UPDATE** — add `timeline` capture and balanced-event assertions. The existing assertions (`not any synthetic_entries`, warning check) remain valid.
- `test_non_futures_incomplete_trade_preserved_in_timeline` (line ~5724): Unaffected — non-futures keys aren't in `filtered_futures_incomplete_keys`.
- All `test_derive_cash_*` tests: Don't call `build_position_timeline`, unaffected.
- All P1/P2 tests: Unaffected.

## Expected Impact

| Source | Post-P3 (current) | Expected Post-P3.1 | Broker Actual |
|--------|-------------------|---------------------|---------------|
| **IBKR** | -100.00% | Significantly improved (no -$28K phantom) | -9.35% |
| **Schwab** | +49.76% | Unchanged (no futures) | -8.29% |
| **Plaid** | -7.96% | Unchanged (no futures) | -12.49% |
| **Combined** | -23.84% | Improved (IBKR no longer -100%) | -8 to -12% |

## Verification

1. `pytest tests/core/test_realized_performance_analysis.py -v` — all existing + new tests pass
2. `pytest tests/ --ignore=tests/api -q` — full suite green
3. Manual per-source check:
   ```
   python3 -c "
   from mcp_tools.performance import get_performance
   for source in ['all', 'plaid', 'schwab', 'ibkr_flex']:
       r = get_performance(mode='realized', source=source, format='agent', use_cache=False)
       ret = r['snapshot']['returns']
       print(f'{source}: {ret[\"total_return_pct\"]}%')
   "
   ```
4. IBKR March 2025 monthly NAV should be positive (no -$28K MES phantom)
5. IBKR should no longer show V_adjusted <= 0 cascading failure
6. Update `RETURN_PROGRESSION_BY_FIX.md` with post-P3.1 measurements

## Not in scope

- Schwab +49.76% distortion (4 synthetic positions with appreciation — separate investigation)
- Plaid security_id resolution
- Backfill of missing BUY entries for incomplete trades
