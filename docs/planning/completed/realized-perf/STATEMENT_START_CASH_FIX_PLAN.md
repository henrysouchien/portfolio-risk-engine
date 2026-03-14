# Fix 2d: Mid-Period Cash Anchor from IBKR Statement Starting Cash

**Status:** SUPERSEDED by `DUAL_CASH_ANCHOR_PLAN.md` (Fix 3, Steps 1-3)
**Priority:** High
**Added:** 2026-03-06
**Parent:** IBKR_NAV_GAP_FIX_PLAN.md (Fix 2d)

## Problem

The engine back-solves inception cash from ending cash minus full replay:
```
start_cash = ending_cash - replay_change = -$8,727 - $10,980 = -$19,708
```
IBKR's actual April 1 cash was -$11,097. Gap: $8,611. This makes
inception NAV too low and produces a -39.68% April return (should be milder).

The back-solve error comes from accumulated replay drift (futures MTM
timing, FX, segment transfers) over 12 months of transactions.

## Key Insight

The IBKR statement provides cash at **both** endpoints:
- Starting Cash at **April 1**: -$11,097 (extracted, stored, **unused**)
- Ending Cash at **March 3**: -$8,727 (extracted, stored, used for anchor)

Currently the anchor is calibrated at the END (12 months from inception).
The drift accumulates over 12 months → $8,611 error at inception.

**Fix: Calibrate the anchor at the statement START date (April 1) instead.**
This is only ~1 month from inception, so drift is minimal. April 1 cash
is exact, and all monthly NAVs from April onward are much more accurate.

## How the Anchor Works

The anchor is a constant offset applied to ALL cash snapshots:
```
actual_cash(date) = replay_cash(date) + anchor
```

Currently: `anchor = end_cash - replay_end = -$8,727 - $10,980 = -$19,708`
→ End cash is exact, inception cash is off by $8,611.

New: `anchor = start_cash - replay_at_april1 = -$11,097 - replay_at_april1`
→ April 1 cash is exact, inception cash is off by ~1 month of drift (small).

End cash will be slightly off (~$4K drift vs current $0), but this trade-off
is much better: inception NAV will be accurate, and the massive -39.68%
April return will be corrected.

## Changes

### 1. Extract statement start date from DB path — `ibkr/flex.py`

Add `period_start` to the `extract_statement_cash()` return dict by parsing
the DB filename convention `U{acct}_{YYYYMMDD}_{YYYYMMDD}`:

```python
import re
m = re.search(r'_(\d{8})_\d{8}', str(statement_db_path))
if m:
    result["period_start"] = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
```

### 2. Return starting cash + period_start from metadata — `engine.py`

Modify `_statement_cash_from_metadata()` to return a dict:

```python
def _statement_cash_from_metadata() -> dict[str, Any] | None:
    for row in provider_fetch_metadata:
        if str(row.get("provider") or "").strip().lower() != "ibkr_flex":
            continue
        sc = row.get("statement_cash")
        if isinstance(sc, dict) and sc.get("ending_cash_usd") is not None:
            return sc
    return None
```

### 3. Calibrate anchor at statement start date — `engine.py` ~line 1785

After computing `cash_snapshots` (line 1645), find the replay value at the
statement start date and calibrate the anchor there:

```python
stmt = _statement_cash_from_metadata() if source == "ibkr_flex" else None

if stmt:
    observed_end_cash = float(stmt["ending_cash_usd"])
    cash_anchor_source = "ibkr_statement"
    _cash_anchor_matched_rows = 1

    # Prefer mid-period anchor at statement start date
    stmt_start_cash = stmt.get("starting_cash_usd")
    stmt_start_date = stmt.get("period_start")  # "YYYY-MM-DD" or None
    if stmt_start_cash is not None and stmt_start_date:
        stmt_start_dt = pd.Timestamp(stmt_start_date)
        # Find replay cash closest to statement start date
        replay_at_stmt_start = 0.0
        for snap_dt, snap_cash in cash_snapshots:
            if snap_dt <= stmt_start_dt:
                replay_at_stmt_start = snap_cash
            else:
                break
        back_solved_start_cash = float(stmt_start_cash) - replay_at_stmt_start
    else:
        # Fall back to end-anchor
        replay_final_cash = cash_snapshots[-1][1] if cash_snapshots else 0.0
        back_solved_start_cash = observed_end_cash - replay_final_cash
else:
    observed_end_cash, _cash_anchor_matched_rows = _cash_anchor_offset_from_positions()
    cash_anchor_source = "snaptrade_cur"
    replay_final_cash = cash_snapshots[-1][1] if cash_snapshots else 0.0
    back_solved_start_cash = observed_end_cash - replay_final_cash
```

### 4. Also fix observed-only anchor — `engine.py` ~line 1870-1890

The observed-only cash anchor branch does a similar back-solve. Apply the
same mid-period anchor logic there for consistency.

### 5. Add diagnostic warning

```python
if stmt_start_cash is not None:
    end_anchor_would_be = observed_end_cash - replay_final_cash
    divergence = abs(back_solved_start_cash - end_anchor_would_be)
    if divergence > 100:
        warnings.append(
            f"Cash anchor calibrated at statement start ({stmt_start_date}): "
            f"offset ${back_solved_start_cash:,.2f} vs end-anchor ${end_anchor_would_be:,.2f} "
            f"(${divergence:,.2f} drift over replay period)."
        )
```

## Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py` | Add `period_start` to `extract_statement_cash()` return |
| `core/realized_performance/engine.py` | Return full dict from metadata helper; calibrate anchor at statement start date |

## Expected Impact

| Metric | Before | After (estimated) |
|--------|--------|-------------------|
| Anchor calibration point | End (March 2026) | Statement start (April 1, 2025) |
| Anchor drift | $8,611 (12 months) | ~$0 at April 1, small at inception |
| Inception cash | -$19,708 | ~-$15,000 (April 1 - March replay) |
| March 31 NAV | $17,344 | ~$22,371 (matches IBKR) |
| April return | -39.68% | Much milder |
| TWR | +5.91% | Significantly closer to +0.29% |

## Verification

1. `python3 -m pytest tests/core/ -x -q` — no regressions
2. MCP: `get_performance(mode="realized", source="ibkr_flex")` — check:
   - `cash_anchor_offset_usd` changed from -$19,708
   - April return no longer -39.68%
   - TWR closer to +0.29%
3. Check monthly NAV at March 31 ≈ $22,371 (matches IBKR April 1 NAV)
