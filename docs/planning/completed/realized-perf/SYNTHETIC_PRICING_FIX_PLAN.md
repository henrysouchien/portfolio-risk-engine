# Fix 2c: Synthetic Position Pricing — Use Price Cache Instead of Sell Price

**Status:** PLANNED
**Priority:** High
**Added:** 2026-03-06
**Parent:** IBKR_NAV_GAP_FIX_PLAN.md (Fix 2c)

## Problem

The IBKR realized performance engine has a TWR of +8.53% vs IBKR statement
+0.29% (recon gap 38.29%). The root cause is bad synthetic pricing for
**FTE (First-Transaction-Exit) positions** — 19 positions where the first
observed FIFO transaction is a SELL/COVER, meaning the opening BUY happened
before the Flex data window (~12 months).

The engine creates "synthetic entries" (fake opening trades at inception) for
these positions, then uses `_create_synthetic_cash_events()` to generate
pseudo-BUY cash flows for TWR adjustment. **The bug**: for FTE positions
(source=`synthetic_incomplete_trade`), the code uses `price_hint` (= the SELL
price from the closing trade) instead of looking up the actual historical
market price from `price_cache`. This means the synthetic buy is priced at
the *exit* price, not the *entry* price — distorting TWR flows by thousands.

Example: CBL engine synthetic price = $22.87 (its sell price), IBKR statement
prior_price = $26.58. Across 19 FTE positions the mispricing compounds into
the $8,611 cash gap (back-solved start cash -$19,708 vs IBKR -$11,097).

## Root Cause (2 bugs in `core/realized_performance/timeline.py`)

### Bug 1: price_hint set to sell price (line 625)

```python
"price_hint": _helpers._as_float(getattr(incomplete, "sell_price", 0.0), 0.0),
```

For `synthetic_incomplete_trade` entries, `price_hint` is set to the SELL
price of the closing trade — not the opening price.

### Bug 2: `_create_synthetic_cash_events()` skips price_cache for FTE (lines 692-694)

```python
if source == "synthetic_incomplete_trade":
    price = _helpers._as_float(entry.get("price_hint"), 0.0)
else:
    series = _helpers._series_from_cache(price_cache.get(ticker))
    prior = series[series.index <= pd.Timestamp(date)]
    if not prior.empty:
        price = _helpers._as_float(prior.iloc[-1], 0.0)
```

The `synthetic_incomplete_trade` branch directly uses `price_hint` (sell
price) and never checks `price_cache`. The fallback at lines 702-705
(use `price_hint` when cache misses) is correct but never reached for FTE.

## Changes

### 1. Fix pricing in `_create_synthetic_cash_events()` — `timeline.py` ~line 692

**Before (broken):**
```python
price = 0.0
if source == "synthetic_incomplete_trade":
    price = _helpers._as_float(entry.get("price_hint"), 0.0)
else:
    series = _helpers._series_from_cache(price_cache.get(ticker))
    prior = series[series.index <= pd.Timestamp(date)]
    if not prior.empty:
        price = _helpers._as_float(prior.iloc[-1], 0.0)
```

**After (fixed):**
```python
price = 0.0
series = _helpers._series_from_cache(price_cache.get(ticker))
prior = series[series.index <= pd.Timestamp(date)]
if not prior.empty:
    price = _helpers._as_float(prior.iloc[-1], 0.0)
```

Remove the `if source == "synthetic_incomplete_trade"` special case. ALL
synthetic entries now use price_cache backward lookup. The existing fallback
at lines 702-705 still catches tickers with no cache data via `price_hint`.

### 2. price_hint source — NO CHANGE NEEDED

Codex review confirmed `IncompleteTrade` has no `cost_basis` field (only
`ClosedTrade` and `OpenLot` do). The `sell_price` fallback is acceptable
because Change 1 ensures `price_cache` is always tried first — `price_hint`
is only used when the cache has no data for that ticker/date, which is rare.

### 3. Update test — `tests/core/test_realized_performance_analysis.py`

**Test:** `test_create_synthetic_cash_events_generates_pseudo_buys` (~line 4117)

This test has a `synthetic_incomplete_trade` NVDA entry with
`price_hint=321.0` and `price_cache` containing NVDA at $300.0. After the
fix it should assert `price == 300.0` (cache wins over hint).

### 4. Add new test: FTE prefers price_cache, falls back to price_hint

New test `test_synthetic_cash_events_fte_prefers_price_cache_over_hint`:
- Entry with `price_hint=50` + `price_cache` at $45 → asserts price=45
- Entry with `price_hint=88` + empty cache → asserts price=88 (fallback)

## Files Modified

| File | Change |
|------|--------|
| `core/realized_performance/timeline.py` | Remove FTE special case (~line 692), improve price_hint source (~line 625) |
| `tests/core/test_realized_performance_analysis.py` | Update NVDA assertion 321→300, add cache-vs-hint test |

## Expected Impact

| Metric | Before | After (estimated) |
|--------|--------|-------------------|
| Synthetic pricing source | sell_price (wrong) | price_cache (correct) |
| FTE positions affected | 19 | 19 |
| Cash replay gap | ~$8,611 | Reduced |
| Recon gap | 38.29% | Significantly reduced |
| TWR | +8.53% | Closer to +0.29% |

## Verification

1. `python3 -m pytest tests/core/test_realized_performance_analysis.py -v -k synthetic_cash` — updated + new tests pass
2. `python3 -m pytest tests/core/ -x -q` — no regressions
3. MCP: `get_performance(mode="realized", source="ibkr_flex")` — check TWR closer to +0.29%
4. Check `recon_gap_pct` decreased from 38.29%
5. Update `IBKR_NAV_GAP_FIX_PLAN.md` and `BACKLOG.md` with results
