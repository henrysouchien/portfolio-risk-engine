# Extract Broker Cost Basis from IBKR Flex Trades

**Date**: 2026-03-06
**Status**: Planned

## Context

Our realized performance engine has an $8,600 gap vs IBKR's actual P&L, primarily from 19 incomplete trades (exits without matching entries). When the FIFO matcher can't find an opening lot, it creates an `IncompleteTrade` with `sell_price` as the only price reference. The timeline builder then uses `sell_price` as `price_hint` for synthetic position pricing.

**Problem**: `sell_price` = exit price, not cost basis. A stock bought at $48 and sold at $30 gets a synthetic entry at $30, hiding the $18/share loss entirely.

**Discovery**: The IBKR Flex XML `Trade` rows have a `cost` field (total cost basis) and `fifoPnlRealized` field that we're NOT extracting. These give the exact IBKR cost basis for every closing trade — including the 19 incomplete trades.

**Fix**: Extract `cost` from Flex Trade rows in `ibkr/flex.py`, thread it as `broker_cost_basis` through the generic transaction pipeline, and use it as `price_hint` instead of `sell_price`. Each layer stays within its package boundary.

## The Change — 4 Layers

### Layer 1: `ibkr/flex.py` — Extraction (IBKR package)

**File**: `ibkr/flex.py`, `normalize_flex_trades()` (lines 355-391)

After fee extraction (line 362), before the normalized dict (line 373):

```python
# Broker cost basis for closing trades (IBKR Flex "cost" = total cost of lots closed).
# Extracted for SELL/COVER where openCloseIndicator is not explicitly "O" (open).
# Blank openCloseIndicator on a SELL is treated as a close — IBKR only omits this
# flag for simple long sells, which are indeed closes.
# Futures: skipped — futures incomplete trades are filtered in timeline.py:596
# and their cost conventions (notional vs point-based) are unverified.
broker_cost_basis = None
open_close = str(_get_attr(trade, "openCloseIndicator", "openClose", default="")).upper()
if trade_type in ("SELL", "COVER") and open_close != "O" and not is_futures:
    raw_cost = safe_float(_get_attr(trade, "cost"), 0.0)
    raw_qty = abs(safe_float(_get_attr(trade, "quantity", "qty"), 0.0))
    if abs(raw_cost) > 0 and raw_qty > 0:
        per_unit = abs(raw_cost) / raw_qty
        # For options: price = tradePrice * multiplier (per-contract).
        # Flex cost is also total, so cost/raw_qty = per-contract. Matches.
        # For stocks: cost/qty = per-share. Matches.
        broker_cost_basis = per_unit
```

Add to the normalized dict: `"broker_cost_basis": broker_cost_basis,`

**Key**: `raw_qty` uses the XML `quantity` directly (contracts for options, shares for stocks). NOT the adjusted `quantity` variable which has futures multiplier applied (line 349-350). The Flex `cost` is total, so dividing by raw contract/share count gives per-unit cost matching our `price` convention.

**Verified from Flex data**:
| Trade | cost | raw_qty | per_unit | price (our convention) |
|-------|------|---------|----------|----------------------|
| NMM stock SELL | -1928.10 | 40 | 48.20/share | 30.11/share |
| PDD C110 SELL | -3410.81 | 1 | 3410.81/contract | 1729/contract |
| NMM C70 expired | -210.04 | 1 | 210.04/contract | 0/contract |

### Layer 2: `providers/normalizers/ibkr_flex.py` — Pass-through

**File**: `providers/normalizers/ibkr_flex.py` (line 134-155)

Add to the fifo_transactions dict: `"broker_cost_basis": txn.get("broker_cost_basis"),`

Generic field name — any provider could populate this.

### Layer 3: `trading_analysis/fifo_matcher.py` — Thread to IncompleteTrade

**3a.** Add field to `IncompleteTrade` dataclass (after line 168):
```python
broker_cost_basis: Optional[float] = None
```

**3b.** Expand `txn_meta` (lines 406-409) to include:
```python
"broker_cost_basis": txn.get("broker_cost_basis"),
```

**3c.** In `_process_exit()` (line 804-818), add to IncompleteTrade construction:
```python
broker_cost_basis=meta.get("broker_cost_basis"),
```

**3d.** Same in `_create_incomplete_trade()` (line 886-900):
```python
broker_cost_basis=meta.get("broker_cost_basis"),
```

### Layer 4: `core/realized_performance/timeline.py` — Consumption

**Single-line change at line 625**:

```python
# Before:
"price_hint": _helpers._as_float(getattr(incomplete, "sell_price", 0.0), 0.0),

# After:
"price_hint": (
    _helpers._as_float(getattr(incomplete, "broker_cost_basis", None), 0.0)
    or _helpers._as_float(getattr(incomplete, "sell_price", 0.0), 0.0)
),
```

Prefers broker cost basis when available; falls back to sell_price for non-IBKR providers.

## Expected Impact

| Symbol | Current price_hint (sell_price) | After (broker_cost_basis) | IBKR Actual Cost | IBKR Realized P&L |
|--------|-------------------------------|--------------------------|-----------------|-------------------|
| CBL | $22.87/sh | $29.55/sh | $29.55/sh | -$670 |
| NMM stock | $30.11/sh | $48.20/sh | $48.20/sh | -$725 |
| SE | $105.21/sh | $127.36/sh | $127.36/sh | -$355 |
| MSCI | $509.54/sh | $575.43/sh | $575.43/sh | -$331 |
| VBNK | $10.19/sh | $13.94/sh | $13.94/sh | -$545 |
| PDD C110 | $1,519/ct | $3,411/ct | $3,411/ct | -$3,784 |
| NMM C70 | $0 (skipped) | $210/ct | $210/ct | -$210 |
| NMM C85 | $0 (skipped) | $85/ct | $85/ct | -$85 |
| PDD P60 | $430/ct | $166/ct | $166/ct | +$1,055 |
| NXT C30 | $1,077/ct | $1,063/ct | $1,063/ct | +$27 |

This gives the timeline builder the EXACT IBKR cost basis for every incomplete trade.

## Key Files
- `ibkr/flex.py:355-391` — Layer 1: extract `cost` field
- `providers/normalizers/ibkr_flex.py:134-155` — Layer 2: pass-through
- `trading_analysis/fifo_matcher.py:144-168, 406-409, 804-818, 886-900` — Layer 3: thread to IncompleteTrade
- `core/realized_performance/timeline.py:625` — Layer 4: consume as price_hint

## Testing

### Unit tests (new)
1. `tests/ibkr/test_flex.py` — `test_normalize_flex_trades_extracts_broker_cost_basis`: Closing stock trade (SELL, openClose=C) with `cost=-2955`, qty=100, assert `broker_cost_basis == 29.55`
2. `tests/ibkr/test_flex.py` — `test_normalize_flex_trades_option_broker_cost_basis`: Closing option trade with `cost=-3410.805`, qty=1, multiplier=100, assert `broker_cost_basis == 3410.805`
3. `tests/ibkr/test_flex.py` — `test_normalize_flex_trades_opening_trade_no_cost_basis`: Opening trade (openClose=O), assert `broker_cost_basis is None`
4. `tests/ibkr/test_flex.py` — `test_normalize_flex_trades_cost_basis_zero_cost`: Closing trade with `cost=0`, assert `broker_cost_basis is None`
5. `tests/ibkr/test_flex.py` — `test_normalize_flex_trades_cover_trade_cost_basis`: COVER (short close) trade with cost, assert `broker_cost_basis` extracted correctly
6. `tests/ibkr/test_flex.py` — `test_normalize_flex_trades_blank_open_close_sell`: SELL with blank openCloseIndicator and nonzero cost, assert `broker_cost_basis` extracted (blank = close)
7. `tests/ibkr/test_flex.py` — `test_normalize_flex_trades_futures_no_cost_basis`: Futures closing trade, assert `broker_cost_basis is None` (futures skipped)
8. `tests/trading_analysis/` — `test_fifo_incomplete_trade_carries_broker_cost_basis`: Full wiring test: create FIFO transactions with `broker_cost_basis=48.0` on a SELL with no prior BUY, process through FIFOMatcher, assert `result.incomplete_trades[0].broker_cost_basis == 48.0`
9. `tests/core/test_realized_performance_analysis.py` — `test_incomplete_trade_prefers_broker_cost_basis`: IncompleteTrade with both `sell_price=30.0` and `broker_cost_basis=48.0`, assert price_hint = 48.0
10. `tests/core/test_realized_performance_analysis.py` — `test_incomplete_trade_falls_back_to_sell_price`: IncompleteTrade with `broker_cost_basis=None`, assert price_hint = sell_price

### Existing tests that must NOT break
- `test_synthetic_cash_events_skip_positions_without_prices` (line 4181)
- `test_synthetic_cash_events_fallback_to_price_hint_when_history_missing` (line 4208)
- `test_synthetic_cash_events_fte_prefers_price_cache_over_hint` (line 4238)
- `test_synthetic_cash_events_incomplete_trade_forward_lookup` (line 4275)
- All existing `test_normalize_flex_trades_*` tests in `tests/ibkr/test_flex.py`

### End-to-end verification
Run `get_performance(mode="realized", institution="ibkr", format="summary")` via MCP and check:
- NAV return shifts closer to IBKR's actual +0.29%
- Incomplete trade synthetic entries use broker cost basis prices

## Codex Review Findings (addressed)

1. **Store persistence gap**: `broker_cost_basis` is NOT persisted in `transaction_store.py`. Realized perf uses live Flex fetch (not store reads), so this works for now. Phase 2 will add DB column + store persistence.
2. **Futures skipped**: Added `not is_futures` guard. Futures cost conventions (notional vs point-based) are unverified, and futures incomplete trades are already filtered at `timeline.py:596`.
3. **Blank openCloseIndicator**: Documented as assumption — blank SELL with nonzero cost is treated as a close (correct for IBKR long sells). Added test #6.
4. **Wiring test**: Added test #8 — full normalizer→FIFO→IncompleteTrade pipeline test.
5. **Edge case tests**: Added tests #4 (cost=0), #5 (COVER), #6 (blank flag), #7 (futures).

## Not in Scope
- Transaction store persistence of `broker_cost_basis` (Phase 2 — works without it since realized perf uses live Flex fetch path)
- `fifoPnlRealized` extraction (diagnostic only, not needed for pricing fix)
- Backfill JSON system changes (orthogonal)
- Futures cost basis (unverified conventions, already filtered downstream)
