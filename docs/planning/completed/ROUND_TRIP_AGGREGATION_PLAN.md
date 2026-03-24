# Step 1: FIFO Matcher Emits Round-Trip Boundaries

## Context

The trading scorecard redesign requires round-trip level observations (not individual FIFO lots). A round-trip is a complete position: enter, optionally scale in, exit fully. The FIFO matcher is the only place that knows when a position goes flat — it must emit this information during processing.

## Current State

`FIFOMatcher.process_transactions()` produces:
- `closed_trades: list[ClosedTrade]` — one per lot closure
- `open_lots: dict[(symbol, currency, direction), list[OpenLot]]` — final state only

The flat-position event (all lots consumed for a key) happens at `_process_exit()` line 758 when `self.open_lots[lot_key].pop(0)` removes the last lot. But this event is not recorded.

## Plan

### 1. Track round-trip boundaries during FIFO processing

**File:** `trading_analysis/fifo_matcher.py`

In `_process_exit()`, after line 758 (`self.open_lots[lot_key].pop(0)`), check if the key's lot list is now empty:

```python
# After popping the lot (line 758):
if not self.open_lots[lot_key]:
    # Position is flat — mark a round-trip boundary
    self._close_round_trip(lot_key)
```

Add tracking state to `FIFOMatcher.__init__()` AND `reset()` (line ~333 — reset() is called at the start of process_transactions, must clear new fields too):
```python
# In __init__ and reset():
self._current_round_trip_lots: dict[tuple, list[ClosedTrade]] = defaultdict(list)
self.round_trips: list[RoundTrip] = []
```

When a ClosedTrade is created (line 755), also accumulate it:
```python
self.closed_trades.append(closed_trade)
self._current_round_trip_lots[lot_key].append(closed_trade)
```

When position goes flat (`_close_round_trip`):
```python
def _close_round_trip(self, lot_key: tuple):
    lots = self._current_round_trip_lots.pop(lot_key, [])
    if not lots:
        return
    self.round_trips.append(RoundTrip.from_lots(lots))
```

### 2. RoundTrip dataclass

**File:** `trading_analysis/fifo_matcher.py` (co-located with ClosedTrade)

```python
@dataclass
class RoundTrip:
    symbol: str
    currency: str
    direction: str
    instrument_type: str

    entry_date: datetime
    exit_date: datetime
    days_in_trade: int
    num_lots: int

    cost_basis: float       # sum of lot cost_basis (local currency)
    proceeds: float         # sum of lot proceeds
    pnl_dollars: float      # sum of lot pnl_dollars (local currency)
    pnl_percent: float      # pnl_dollars / abs(sum of lot entry_value) * 100

    @property
    def is_winner(self) -> bool:
        return self.pnl_dollars > 0

    @classmethod
    def from_lots(cls, lots: list[ClosedTrade]) -> 'RoundTrip':
        assert lots, "Cannot create RoundTrip from empty lot list"
        first = lots[0]

        total_cost_basis = sum(lot.cost_basis for lot in lots)
        total_proceeds = sum(lot.proceeds for lot in lots)
        total_pnl = sum(lot.pnl_dollars for lot in lots)
        entry_date = min(lot.entry_date for lot in lots)
        exit_date = max(lot.exit_date for lot in lots)

        # Use abs(cost_basis) as denominator.
        # Note: long cost_basis includes entry fees, short cost_basis does not (matches ClosedTrade semantics).
        # This is consistent with how ClosedTrade.pnl_percent is already computed (uses entry_value = qty * price).
        pnl_percent = (total_pnl / abs(total_cost_basis) * 100) if abs(total_cost_basis) > 1e-10 else 0.0

        return cls(
            symbol=first.symbol,
            currency=first.currency,
            direction=first.direction,
            instrument_type=first.instrument_type,
            entry_date=entry_date,
            exit_date=exit_date,
            days_in_trade=(exit_date - entry_date).days,
            num_lots=len(lots),  # count of ClosedTrade fragments, not original lots
            cost_basis=total_cost_basis,
            proceeds=total_proceeds,
            pnl_dollars=total_pnl,
            pnl_percent=pnl_percent,
        )
```

### 3. Add to FIFOMatcherResult

**File:** `trading_analysis/fifo_matcher.py`

Add `round_trips` field:
```python
@dataclass
class FIFOMatcherResult:
    closed_trades: List[ClosedTrade] = field(default_factory=list)
    open_lots: Dict[...] = field(default_factory=dict)
    incomplete_trades: List[IncompleteTrade] = field(default_factory=list)
    inferred_shorts: Set[str] = field(default_factory=set)
    round_trips: List[RoundTrip] = field(default_factory=list)  # NEW
```

In `process_transactions()`, before building the result (line 652):
```python
# Handle any remaining accumulated lots for keys that went flat
# (already handled by _close_round_trip during processing)

result = FIFOMatcherResult(
    closed_trades=self.closed_trades,
    open_lots=dict(self.open_lots),
    incomplete_trades=self.incomplete_trades,
    inferred_shorts=self.inferred_shorts,
    round_trips=self.round_trips,  # NEW
)
```

Note: lots still accumulated in `_current_round_trip_lots` at end-of-processing are for positions still open — they are NOT emitted as round-trips. Only fully-flat positions get round-trips.

### Synthetic lot exclusion

The FIFO matcher is run twice in the codebase:
1. **Trading analyzer** (`trading_analysis/analyzer.py`) — real trades → round-trips are meaningful
2. **Realized performance engine** (`core/realized_performance/engine.py`) — includes synthetic "seed_back_solved" lots → round-trips are NOT meaningful

The scorecard consumes round-trips only from run #1 (trading analyzer). The analyzer already controls which matcher run feeds scoring, so no filtering needed inside the matcher itself.

Belt-and-suspenders: `RoundTrip.from_lots()` also checks `ClosedTrade.source` — if ANY lot has source containing "seed" or "synthetic", the round-trip is marked `synthetic=True` and excluded from scoring by the grading functions.

Add to RoundTrip dataclass:
```python
synthetic: bool = False  # True if any constituent lot is synthetic
```

In `from_lots()`:
```python
synthetic = any("seed" in (lot.source or "").lower() for lot in lots)
```

### Also update `load_and_merge_backfill()`

**File:** `trading_analysis/fifo_matcher.py` (~line 1078)

This function constructs a new `FIFOMatcherResult` that carries forward `closed_trades` from the original matcher run. It should also carry forward `round_trips` from the original result:

```python
# In load_and_merge_backfill, when building the merged result:
result = FIFOMatcherResult(
    closed_trades=merged_closed_trades,
    open_lots=...,
    incomplete_trades=...,
    inferred_shorts=...,
    round_trips=fifo_result.round_trips,  # carry forward from original run
)
```

### 4. Partial close handling

The existing `_process_exit()` has two paths (line 719-795):
- **Full lot close** (line 723): closes entire lot, pops from open_lots
- **Partial lot close** (line 760): splits lot, keeps remainder in open_lots

Both paths append to `self.closed_trades`. Both should also append to `self._current_round_trip_lots[lot_key]`.

The flat-position check only triggers when `not self.open_lots[lot_key]` after the full close path — partial closes never trigger it. This is correct: a partial close means the position is still open.

### 5. Edge case: same key re-opened after going flat

After `_close_round_trip(lot_key)` is called, the key is removed from `_current_round_trip_lots`. If the same key gets a new entry later (`_process_entry`), a fresh accumulation starts in `_current_round_trip_lots[lot_key]`. This naturally produces separate round-trips — no special handling needed.

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/fifo_matcher.py` | RoundTrip dataclass, tracking state, flat-position detection, FIFOMatcherResult.round_trips |

No other files change. The analyzer, models, and frontend are untouched. This is purely additive — existing behavior is preserved.

## Tests

**File:** `tests/trading_analysis/test_fifo_matcher.py` (or new test file)

Test cases:
1. **Single lot, single close** → 1 round-trip matching the single ClosedTrade
2. **Scaled-in position** (3 buys, 1 sell closing all) → 3 ClosedTrades but 1 RoundTrip
3. **Position goes flat, then re-enters** → 2 separate RoundTrips
4. **Partial close** (buy 100, sell 50, sell 50) → 2 ClosedTrades, 1 RoundTrip (flat after second sell). num_lots = 2 (fragments, not original lots).
5. **Still-open position** → ClosedTrades for partial exits, but NO RoundTrip emitted (position not flat)
6. **Multi-symbol** → independent round-trips per (symbol, currency, direction)
7. **Short position** → round-trip with direction='SHORT'
8. **Cross-currency same symbol** → separate round-trips for (AAPL, USD, LONG) vs (AAPL, GBP, LONG)
9. **Matcher reuse/reset** → process_transactions() called twice on same FIFOMatcher instance, second call has fresh round_trips (no leakage)
10. **Fee-bearing round-trip** → pnl_percent uses cost_basis (includes fees) as denominator, not entry_value
11. **Cross-through (short inference)** → BUY that covers short AND opens long triggers round-trip boundary for the short key
12. **Synthetic lots** → round-trip with any "seed_back_solved" source lot has `synthetic=True`
13. **Backfill carry-forward** → `load_and_merge_backfill()` preserves round_trips from original matcher run

Add tests to existing FIFO test files (e.g., `tests/trading_analysis/test_short_inference.py` or a new `tests/trading_analysis/test_round_trips.py`).

## Verification

1. `pytest tests/trading_analysis/ -v` — all new + existing tests pass
2. Existing ClosedTrade output is unchanged — no regressions in lot-level behavior
3. `len(result.round_trips)` ≤ `len(result.closed_trades)` always (round-trips aggregate lots)
