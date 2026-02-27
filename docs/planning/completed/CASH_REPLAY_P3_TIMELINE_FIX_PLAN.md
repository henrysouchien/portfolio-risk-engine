# P3 Fix: Position Timeline Distortion — Global Inception + Futures Filter

## Sequencing Note (2026-02-25)

This document captures **Phase 3** of the cash replay hardening series.
Prior phases:
- **P1** (commit `efd8f1a6`): UNKNOWN/fx_artifact filtering + futures inference gating
- **P2** (commit `eb9fc423`): Synthetic cash events excluded from replay + sensitivity gate diagnostic-only
- **P2A reference**: `docs/planning/CASH_REPLAY_P2_SYNTHETIC_FIX_PLAN.md`

## Context

After P1+P2, the system reports **273% total return** vs actual broker returns of **-8% to -12%**. The cash replay is now clean, but the **position timeline** still injects phantom NAV via two mechanisms:

1. **Delayed synthetic placement** ($25K distortion): `synthetic_current_position` entries use per-symbol inception (`earliest_txn_by_symbol.get(ticker, inception_date)`) instead of global inception. Positions like GLBE and MSCI appear mid-month (Aug 2024), creating a sudden $25K NAV jump that Modified Dietz interprets as a +99% return.

2. **Futures incomplete trades** ($59K distortion): When FIFO sees a futures SELL with no prior BUY in the lookback window, it creates a `synthetic_incomplete_trade` entry. These use index price × quantity but miss the contract multiplier, creating phantom NAV (e.g., MES at $5,678 × 5 = $28K instead of real margin exposure ~$1K).

A third distortion (equity/options incomplete trades, ~$13K) is accepted as tolerable — these represent real positions with reasonable cost basis estimates.

## Changes

### File 1: `core/realized_performance_analysis.py`

#### Change 1: Always use global inception for `synthetic_current_position` — line 1196

**Before (lines 1193-1196):**
```python
            # Use per-symbol inception: earliest known txn for this symbol,
            # falling back to global inception for zero-history symbols.
            # Offset by -1s so synthetic entry sorts before any real txn at that timestamp.
            symbol_inception = earliest_txn_by_symbol.get(ticker, inception_date)
```

**After:**
```python
            # Use global inception for all synthetic positions so they appear
            # as pre-existing capital in V_start (avoids mid-period NAV jumps).
            # Offset by -1s so synthetic entry sorts before any real txn at that timestamp.
            symbol_inception = inception_date
```

**Why:** Per-symbol inception was designed to place synthetic entries closer to the first real transaction for that symbol. But this causes mid-period NAV jumps when positions appear months after inception. Using global inception means all synthetic positions appear in V_start from day one, treating them as pre-existing capital (same principle as the P2 fix).

#### Change 2: Filter futures from `synthetic_incomplete_trade` — after line 1253

Insert a new filter block after the existing `fx_artifact`/`unknown` filter (lines 1245-1253), before `_register_instrument_meta` at line 1255:

```python
        if instrument_type == "futures":
            warn_key = (key[0], key[1], key[2], "futures_incomplete")
            if warn_key not in filtered_warning_keys:
                warnings.append(
                    f"Filtered futures incomplete trade {symbol} ({currency}, {direction}) "
                    f"from position timeline: futures P&L captured via cash replay fees, "
                    f"not synthetic position value."
                )
                filtered_warning_keys.add(warn_key)
            filtered_keys.add(key)
            continue
```

**Why:** Futures positions are margined instruments. A synthetic BUY of MES at index price creates phantom notional value in the NAV. Futures P&L is already captured through fee-only cash replay (P1). No position value should appear in the timeline for unmatched futures trades.

### File 2: `tests/core/test_realized_performance_analysis.py`

#### Test Update 1: Fix `test_build_position_timeline_adds_synthetic_for_current_without_opening_history` (line 318)

This test expects per-symbol inception (`datetime(2024, 2, 9, 23, 59, 59)` — one second before the earliest AAPL txn). After the fix, all synthetics use global inception.

**Change:** Update `expected_syn_date` from `datetime(2024, 2, 9, 23, 59, 59)` to `datetime(2023, 12, 31, 23, 59, 59)` (global inception `2024-01-01` minus 1s). The rest of the test remains unchanged.

#### Test Update 2: Rewrite `test_per_symbol_inception_uses_earliest_txn_date` (line 5598)

This test validates the per-symbol inception behavior we're removing. Rewrite it to confirm global inception is always used:

```python
def test_synthetic_current_position_always_uses_global_inception():
    """Synthetic entry should always use global inception, not per-symbol earliest txn."""
    inception = datetime(2022, 8, 18)
    fifo_transactions = [
        {"symbol": "STWD", "type": "SELL", "date": datetime(2025, 1, 30),
         "quantity": 50, "price": 25.0, "fee": 0, "currency": "USD"},
        {"symbol": "AAPL", "type": "BUY", "date": datetime(2022, 8, 18),
         "quantity": 10, "price": 150.0, "fee": 0, "currency": "USD"},
    ]
    current_positions = {"STWD": {"shares": 100, "currency": "USD"}}

    _, _, synthetic_entries, _, _ = rpa.build_position_timeline(
        fifo_transactions=fifo_transactions,
        current_positions=current_positions,
        inception_date=inception,
        incomplete_trades=[],
    )

    assert len(synthetic_entries) == 1
    entry = synthetic_entries[0]
    assert entry["ticker"] == "STWD"
    # Should use GLOBAL inception - 1s, NOT STWD's earliest txn (2025-01-30)
    expected_date = datetime(2022, 8, 17, 23, 59, 59)
    assert entry["date"] == expected_date
```

#### Test Update 3: `test_zero_history_symbol_falls_back_to_global_inception` (line 5640)

This test already expects global inception behavior. It should **pass unchanged**.

#### New Test 1: Futures incomplete trades filtered from timeline

```python
def test_futures_incomplete_trade_filtered_from_position_timeline():
    """Futures incomplete trades should not create synthetic position entries."""
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

    # MES should be filtered — no synthetic entry for futures
    # (The raw SELL txn still adds MES to the timeline, but no synthetic opening is created)
    assert not any(e["ticker"] == "MES" for e in synthetic_entries)
    # Warning emitted
    assert any("Filtered futures incomplete trade MES" in w for w in warnings)
```

#### New Test 2: Non-futures incomplete trades still work

```python
def test_non_futures_incomplete_trade_preserved_in_timeline():
    """Equity incomplete trades should still create synthetic entries."""
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

    assert any(e["ticker"] == "GLBE" and e["source"] == "synthetic_incomplete_trade" for e in synthetic_entries)
    assert ("GLBE", "USD", "LONG") in timeline
```

## Why existing tests pass unchanged

- `test_zero_history_symbol_falls_back_to_global_inception` (line 5640): Already expects global inception for zero-history symbols — unchanged behavior.
- All `test_derive_cash_*` tests: Don't call `build_position_timeline`, unaffected.
- All P1/P2 tests: Test cash replay and sensitivity gate, not position timeline placement.
- `_create_synthetic_cash_events()` unit tests: Test the function in isolation.
- `test_build_position_timeline_filters_fx_artifact_and_unknown_from_incomplete`: Tests fx_artifact/unknown filtering, not futures. Unaffected.

## Verification

1. `pytest tests/core/test_realized_performance_analysis.py -v` — all existing + new tests pass
2. `pytest tests/ --ignore=tests/api -q` — full suite green
3. Manual: `python3 tests/utils/show_api_output.py "get_performance(mode='realized', format='agent')"` — confirm:
   - Aug 2024 monthly return drops from +99% (no more mid-month $25K NAV jump from GLBE/MSCI)
   - Mar/Apr 2025 monthly returns drop (no more $59K phantom futures NAV)
   - Total return moves materially closer to broker baseline range
4. Per-source check: `source="plaid"` should remain near -10% (was already close), `source="schwab"` and `source="ibkr_flex"` should improve

## Not in scope

- Equity/options incomplete trade distortion (~$13K) — accepted as tolerance
- Futures contract multiplier integration into position timeline (futures excluded entirely)
- Dead code cleanup for per-symbol inception computation (`earliest_txn_by_symbol` dict still built but unused for synthetic placement)
- Plaid security_id resolution (P4)
- `brokerage_name` population (P4)
