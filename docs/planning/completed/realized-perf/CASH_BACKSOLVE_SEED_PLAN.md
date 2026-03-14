# Fix: Back-Solve Starting Cash into Realized Performance Engine

## Context

The realized performance engine reports **-8.50%** for the IBKR account vs the
official statement return of **+0.29%**. Root cause: the cash replay in
`derive_cash_and_external_flows()` starts from `cash = 0.0` (nav.py:236),
so the NAV denominator is wrong from day one.

We validated a back-solve methodology in `scripts/ibkr_cash_backsolve.py`:
```
start_cash = observed_end_cash - sum(in_period_replay_impacts)
```
For IBKR: `start_cash = -8,727 - (+2,370) = -11,097`, matching the IBKR
statement within ~$1,852 (FX methodology — validated and accepted).

The engine already has anchor infrastructure at engine.py:1547-1596
(`_apply_cash_anchor`, `REALIZED_CASH_ANCHOR_NAV` flag), but it currently
injects the **end** observed cash at inception — conceptually wrong. We need
the **back-solved start cash** instead.

### How cash snapshots work

`derive_cash_and_external_flows()` returns `cash_snapshots: List[(datetime, float)]`
where each entry is a cumulative running total starting from 0. The final
snapshot = total cash change. `compute_monthly_nav()` reads these as absolute
values (nav.py:480). Shifting all snapshots by `start_cash` correctly adjusts
NAV: `NAV = position_value + (cash_from_zero + start_cash)`.

## Changes

### 1. Replace anchor value with back-solve computation — `engine.py`

**File**: `core/realized_performance/engine.py`

**Current** (engine.py:1579-1592):
```python
cash_anchor_requested = bool(_helpers._shim_attr("REALIZED_CASH_ANCHOR_NAV", False))
raw_observed_cash_anchor_offset = _cash_anchor_offset_from_positions()
```
Uses end cash directly as anchor offset.

**New** (same location):
```python
cash_anchor_requested = bool(_helpers._shim_attr("REALIZED_CASH_ANCHOR_NAV", True))
observed_end_cash = _cash_anchor_offset_from_positions()
replay_final_cash = cash_snapshots[-1][1] if cash_snapshots else 0.0
back_solved_start_cash = observed_end_cash - replay_final_cash
raw_observed_cash_anchor_offset = back_solved_start_cash
```

**Why this works**: The replay has already run (lines 992-1500 produce
`cash_snapshots`) before the anchor code at line 1579. The final snapshot
value is the total cash change from 0. Subtracting from observed end cash
gives the start cash. The rest of the anchor machinery (`_apply_cash_anchor`,
`anchor_snapshot = [(inception_date, offset)]`) works unchanged.

**Observed-only branch** (engine.py:1649-1658): The observed-only replay
excludes provider-flow events and may produce different cash totals than
the main branch. After `observed_cash_snapshots` is computed (line 1649),
build a separate anchor snapshot and apply it:

```python
# After line 1656 (observed replay done), before line 1657:
observed_replay_final = observed_cash_snapshots[-1][1] if observed_cash_snapshots else 0.0
observed_back_solved_start = observed_end_cash - observed_replay_final
observed_only_cash_anchor_offset_usd = observed_back_solved_start

# Replace existing line 1657-1658:
if cash_anchor_applied_to_nav:
    observed_anchor_snapshot = [(inception_date, observed_back_solved_start)]
    observed_cash_snapshots = _apply_cash_anchor(observed_cash_snapshots, observed_anchor_snapshot)
```

This ensures the observed-only NAV uses its own back-solved start cash
rather than reusing the main branch's anchor snapshot (which may include
provider-flow effects).

### 2. Enable anchor by default

Two changes required:

1. `core/realized_performance/__init__.py:43` — change module-level constant:
   ```python
   # Before:
   REALIZED_CASH_ANCHOR_NAV = False
   # After:
   REALIZED_CASH_ANCHOR_NAV = True
   ```

2. `core/realized_performance/engine.py:1579` — change `_shim_attr` default:
   ```python
   # Before:
   cash_anchor_requested = bool(_helpers._shim_attr("REALIZED_CASH_ANCHOR_NAV", False))
   # After:
   cash_anchor_requested = bool(_helpers._shim_attr("REALIZED_CASH_ANCHOR_NAV", True))
   ```

Both are needed because `_shim_attr` reads from `core.realized_performance_analysis`
module (which re-exports from `__init__.py`). If the module is loaded, it reads
the module-level value; if not, it falls back to the default arg. Both must be
`True` for consistent behavior.

### 3. Add diagnostic metadata — `engine.py`

Add alongside existing `cash_anchor_offset_usd` in realized_metadata:
```python
"cash_backsolve_observed_end_usd": round(observed_end_cash, 2),
"cash_backsolve_replay_final_usd": round(replay_final_cash, 2),
"cash_backsolve_start_usd": round(back_solved_start_cash, 2),
```

### 4. Tests — `tests/core/test_realized_cash_anchor.py`

Existing tests use empty transactions -> `replay_final_cash = 0` ->
`back_solved_start = -500 - 0 = -500`. Tests should pass unchanged since the
formula reduces to the same value when there are no replay events.

Run to confirm; adjust if any edge case breaks.

## Files Modified

| File | Change |
|------|--------|
| `core/realized_performance/engine.py` | Back-solve computation, observed-only anchor, metadata |
| `core/realized_performance/__init__.py` | Flip `REALIZED_CASH_ANCHOR_NAV` default to `True` |
| `tests/core/test_realized_cash_anchor.py` | Verify pass (likely no changes) |

No changes to `nav.py` — offset applied after replay via existing
`_apply_cash_anchor()`.

## Codex Review

- Round 1: **FAIL** (2 issues)
  1. `_shim_attr` default alone won't flip runtime default — must also change
     `__init__.py:43` module-level constant. **Fixed.**
  2. Observed-only branch reused main anchor snapshot — needs its own
     back-solved anchor. **Fixed.**
- Round 2: **PASS**

## Verification

1. `python3 -m pytest tests/core/test_realized_cash_anchor.py -v` — all 4 pass
2. `python3 -m pytest tests/ -x --timeout=60` — no regressions
3. MCP: `get_performance(mode="realized", source="ibkr_flex")` — return shifts from ~-8.5% toward ~+0.3%
4. `realized_metadata.cash_backsolve_*` fields show computation
5. `realized_metadata.cash_anchor_applied_to_nav` is `true`
