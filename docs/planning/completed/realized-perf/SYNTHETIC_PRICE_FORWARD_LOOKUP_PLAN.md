# Fix Synthetic Position Pricing for Incomplete Trades

**Date**: 2026-03-06
**Status**: Planned (revised after Codex review)
**Files**: `core/realized_performance/timeline.py`

## Problem

When the FIFO matcher finds an exit without a matching entry, the timeline builder creates a synthetic position at `inception_date - 1 second`. The `_create_synthetic_cash_events()` function then creates pseudo BUY/SHORT transactions for these entries. Its price resolution uses:

1. **Backward price lookup** from `price_cache` at the synthetic date (strict: `<= date`)
2. **Fallback to `price_hint`** (which is `sell_price` for incomplete trades, or broker cost basis for current positions)

For IBKR options, the price cache (from Flex PriorPeriodPosition marks) starts at inception, but the synthetic date is `inception - 1s` — so the backward lookup misses by one day. If `price_hint > 0`, the event still gets created. But when `price_hint == 0` (expired options like NMM_C70, NMM_C85), the event is **skipped entirely** — no pseudo-transaction, no TWR flow.

## Why the impact is narrow (Codex review finding)

The downstream TWR flow path (`_synthetic_events_to_flows()`) already uses `_value_at_or_before()` which **does forward lookup** (`_helpers.py:174-176`). So for options where `price_hint > 0` (PDD, NXT, PLTR), the pseudo-transaction gets created with the hint price, but the TWR flow is repriced with the correct `price_cache` mark anyway. The `price` stored in the pseudo-transaction only matters for:

1. **Whether the event exists at all** — if `price <= 0`, the entry is skipped (line 720-725)
2. **Diagnostics/audit trail** — the stored price shows in logs

This means the fix **only changes realized returns for currently-skipped entries**: NMM_C70_260116 and NMM_C85_260116 (both expired with `price_hint=0.0`). The other options (PDD, NXT, PLTR) are already correctly priced through the TWR flow repricing path.

## The Fix

Add a forward-lookup fallback in `_create_synthetic_cash_events()`, **scoped to `synthetic_incomplete_trade` entries only**. This prevents changing behavior for `synthetic_current_position` entries where `price_hint` is broker cost basis (more accurate than a market mark).

**File**: `core/realized_performance/timeline.py` — `_create_synthetic_cash_events()` (lines 692-725)

### Current flow:
```
1. backward lookup: series[series.index <= date]  ->  price
2. if price <= 0: use price_hint                  ->  skipped when hint=0
```

### New flow (incomplete trades only):
```
1. backward lookup: series[series.index <= date]   ->  price
2. if price <= 0 AND source == "synthetic_incomplete_trade":
      forward lookup: series[series.index > date].iloc[0]  ->  price
3. if price <= 0: use price_hint                   ->  last resort
```

### Exact edit in `_create_synthetic_cash_events()`:

After line 698 (`price = _helpers._as_float(prior.iloc[-1], 0.0)`), before line 700 (`if price <= 0:`), insert:

```python
        # Forward lookup fallback for incomplete trades only.
        # The synthetic date (inception - 1s) is arbitrary, so the nearest future
        # price (typically the first PriorPeriodPosition mark) is more accurate than
        # sell_price. NOT applied to current-position synthetics where price_hint
        # is broker cost basis (more accurate than a market mark).
        if price <= 0 and source == "synthetic_incomplete_trade" and not series.empty:
            forward = series[series.index > pd.Timestamp(date)]
            if not forward.empty:
                price = _helpers._as_float(forward.iloc[0], 0.0)
                if price > 0:
                    warnings.append(
                        f"Used forward price lookup for {ticker} ({direction}) on "
                        f"{date.date().isoformat()} "
                        f"(nearest available: {forward.index[0].date().isoformat()})."
                    )
```

Also update the comment on line 693 from "Strict backward-only lookup" to "Backward-first lookup".

## Expected Impact

**Directly fixes (skipped -> priced)**:

| Symbol | Current | After Fix | IBKR Actual |
|--------|---------|-----------|-------------|
| NMM_C70_260116 | Skipped (hint=$0) | Forward lookup → inception mark | -$210 realized |
| NMM_C85_260116 | Skipped (hint=$0) | Forward lookup → inception mark | -$85 realized |

**No change (already working via TWR flow repricing)**:

| Symbol | price_hint | TWR flow price source |
|--------|-----------|----------------------|
| PDD_C110_260116 | $1,519/$1,310 | Already repriced via `_value_at_or_before()` |
| PDD_P60_260116 | $430 | Already repriced via `_value_at_or_before()` |
| NXT_C30_250815 | $1,151/$1,003 | Already repriced via `_value_at_or_before()` |
| PLTR_P80_250417 | $335/$336 | Already repriced via `_value_at_or_before()` |
| PLTR_P90_250417 | $770 | Already repriced via `_value_at_or_before()` |

## Testing

### Existing tests that must NOT break

These tests assert strict backward-only behavior for `synthetic_current_position` entries. The source-gating ensures they pass unchanged:

- `test_synthetic_cash_events_skip_positions_without_prices` (line 4181) — `synthetic_current_position` with future-only data, no hint → still skipped
- `test_synthetic_cash_events_fallback_to_price_hint_when_history_missing` (line 4208) — `synthetic_current_position` with future-only data + hint → still uses hint
- `test_synthetic_cash_events_fte_prefers_price_cache_over_hint` (line 4238) — `synthetic_incomplete_trade` with cache hit → still uses cache; cache miss → still uses hint

### New tests
1. `test_synthetic_cash_events_incomplete_trade_forward_lookup` — `synthetic_incomplete_trade` with future-only data and `price_hint=0` → uses forward price, emits warning
2. `test_synthetic_ `synthetic_incomplete_trade` with future-only data and `price_hint > 0` → forward price preferred over sell_price hint
3. `test_synthetic_cash_events_current_position_no_forward_lookup` — `synthetic_current_position` with future-only data and `price_hint=0` → still skipped (forward lookup NOT applied)
4. `test_synthetic_cash_events_forward_lookup_zero_mark` — `synthetic_incomplete_trade` with future-only data where first mark is 0.0 → falls through to `price_hint`

### End-to-end verification
Run `get_performance(mode="realized", institution="ibkr", format="summary")` via MCP and check:
- "Used forward price lookup" warnings appear for NMM_C70 and NMM_C85
- NMM_C70/C85 no longer "Skipped" — they get priced via forward lookup
- Return impact is small (these are ~$295 combined realized loss, small vs portfolio)

## Not in Scope
- Backfill JSON population (complementary but separate)
- Fixing `price_hint = sell_price` default (still useful as last resort for non-option trades)
- MHI futures misclassification (separate issue)
- FIFO lot-level realized P&L for incomplete trades (requires backfill, not pricing)
- Larger return gap investigation (TWR flow repricing already handles most options correctly)

## Source Context
- Comparison doc: `docs/planning/performance-actual-2025/IBKR_REALIZED_PERF_COMPARISON.md`
- Engine output: `logs/performance/performance_realized_20260306_204350.json`
- Codex review: FAIL — overstated impact, scope too broad, test plan incomplete. All addressed in this revision.
