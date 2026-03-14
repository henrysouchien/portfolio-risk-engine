# Plan: Fix Flow-Date Snapping in Aggregate Inception Filter

## Context

Schwab aggregated return is +17.53% vs broker actual -8.29%. Root cause traced to `_sum_account_daily_series()` in `core/realized_performance_analysis.py` line 5643. The inception filter (`min_inception_nav=500`) compares **raw flow dates** against `first_viable` (a NAV index date, always a business day). But flows can land on weekends/holidays. `compute_twr_monthly_returns()` snaps flow dates to NAV dates via `searchsorted(side="left")`, but this snapping happens AFTER the filter has already dropped the flow.

**Concrete case**: Account 165's inception deposit of $18,342 is dated **Saturday Aug 24**. `first_viable = Monday Aug 26` (first NAV date >= $500). Filter drops the flow (`Aug 24 < Aug 26`). TWR would have snapped it to Aug 26. The aggregate sees $19K starting NAV with no matching inception flow — $18K of "free capital" inflates cumulative returns by ~14pp.

## Current Behavior (the bug)

In `_sum_account_daily_series()` lines 5638-5643:
```python
if not nav_s.empty and min_inception_nav > 0:
    mask = nav_s.abs() >= min_inception_nav
    if mask.any():
        first_viable = pd.Timestamp(mask.idxmax()).to_pydatetime().replace(tzinfo=None)
        nav_s = nav_s.loc[first_viable:]
        external_flows = [(when, amount) for when, amount in external_flows if when >= first_viable]
        # ^^^ BUG: compares raw flow date (could be weekend) against NAV date (business day)
```

In `compute_twr_monthly_returns()` lines 2154-2159, flow dates are snapped to NAV index:
```python
flow_day = pd.Timestamp(flow_date).normalize()
pos = int(nav_idx.searchsorted(flow_day, side="left"))
if pos >= len(nav_idx):
    snapped_day = nav_idx[-1]
else:
    snapped_day = nav_idx[pos]
```

The filter and the TWR engine use different date semantics. The filter compares raw calendar dates; the TWR engine snaps to the nearest NAV date. A Saturday flow gets dropped by the filter even though TWR would snap it to the following Monday.

## Changes

### 1. Add `_snap_flow_date_to_nav()` helper
**File**: `core/realized_performance_analysis.py` — near line 5550 (before `_dict_to_flow_list`)

Small helper replicating the `searchsorted(side="left")` logic from `compute_twr_monthly_returns()` line 2155. Returns the snapped `pd.Timestamp` or `None` if the flow is past all NAV dates.

```python
def _snap_flow_date_to_nav(
    flow_date: datetime,
    nav_idx: pd.DatetimeIndex,
) -> Optional[pd.Timestamp]:
    """Snap a flow date to the nearest NAV index date (same logic as TWR).

    Uses searchsorted(side='left') to find the first NAV date >= flow_date.
    Returns None if the flow falls after all NAV dates.
    """
    if nav_idx.empty:
        return None
    flow_day = pd.Timestamp(flow_date).normalize()
    pos = int(nav_idx.searchsorted(flow_day, side="left"))
    if pos >= len(nav_idx):
        return None
    return nav_idx[pos]
```

### 2. Fix the flow filter in `_sum_account_daily_series()`
**File**: `core/realized_performance_analysis.py` — lines 5638-5643

Change from:
```python
first_viable = pd.Timestamp(mask.idxmax()).to_pydatetime().replace(tzinfo=None)
nav_s = nav_s.loc[first_viable:]
external_flows = [(when, amount) for when, amount in external_flows if when >= first_viable]
```

To:
```python
first_viable = pd.Timestamp(mask.idxmax()).to_pydatetime().replace(tzinfo=None)
full_nav_idx = pd.DatetimeIndex(nav_s.index).sort_values()  # Before slicing
nav_s = nav_s.loc[first_viable:]
first_viable_ts = pd.Timestamp(first_viable)
external_flows = [
    (when, amount)
    for when, amount in external_flows
    if (snapped := _snap_flow_date_to_nav(when, full_nav_idx)) is not None
    and snapped >= first_viable_ts
]
```

Key: build `full_nav_idx` BEFORE slicing `nav_s`, so Saturday Aug 24 snaps to Monday Aug 26 (= `first_viable`) and is preserved. Flows well before `first_viable` still get dropped because their snapped date precedes `first_viable`.

### 3. No change to `_sum_account_monthly_series()`
The monthly function uses `net_s.reindex(nav_s.index).fillna(0.0)` — pandas month-end alignment, no raw date comparison. Not affected.

### 4. No change to `compute_twr_monthly_returns()`
Already has correct snapping logic. Keep the fix minimal — no refactor to use shared helper. The only difference: TWR snaps past-end flows to last NAV date; our helper returns `None` for those. Both behaviors are correct for their context.

### 5. Add tests
**File**: `tests/core/test_synthetic_twr_flows.py`

- **`test_snap_flow_date_to_nav_basic`**: weekday snaps to itself, Saturday snaps to Monday, past-end returns None
- **`test_sum_account_daily_series_weekend_inception_flow_preserved`**: Saturday inception deposit kept when `first_viable` is following Monday (core regression test)
- **`test_sum_account_daily_series_pre_inception_flow_still_dropped`**: flow well before `first_viable` still dropped even after snapping

## Codex Review Findings

### R1: `full_nav_idx` built before slice — PASS
Plan logic is correct: `full_nav_idx` is captured before slicing `nav_s`.

### R2: Walrus operator + None check — PASS
`(snapped := ...) is not None and snapped >= first_viable_ts` short-circuits safely. Project runtime is >=3.11 (`pyproject.toml`).

### R3: Explicit-key caller at line 6107 — ADDRESSED
Codex found line 6107 passes `external_flow_key="observed_only_external_flows"` explicitly. The fix applies to the same filter logic inside `_sum_account_daily_series` regardless of which key is used — the inception filter runs on whatever flows were loaded. Both call sites (line 5739 default, line 6107 observed-only) benefit from the fix.

### R4: Monthly series bug — PASS
No analogous raw-date bug. `_sum_account_monthly_series` uses `net_s.reindex(nav_s.index).fillna(0.0)` — pandas alignment, not raw date comparison.

### R5: Pre-inception flow leaking through — PASS (with caveat)
A pre-`first_viable` flow can only pass if no NAV date exists between the flow date and `first_viable`. This matches `searchsorted(side="left")` semantics and is consistent with TWR snapping behavior.

### R6: Past-end flow behavior — ADDRESSED
TWR snaps past-end flows to the last NAV date, but our helper returns `None` (drops them). This is intentionally different: in the filter context, a flow past all NAV dates in the filtered series cannot affect any TWR period, so dropping is correct. The existing `compute_twr_monthly_returns` is NOT modified — it keeps its own past-end snapping. Added a test case for past-end flows.

### Overall: PASS after addressing R3 and R6

## Risk Assessment

**Low risk**: Only changes the flow filter in `_sum_account_daily_series`. Does not alter TWR math, NAV computation, or Modified Dietz. Flows on business days pass identically through the new filter. Only weekend/holiday flows near `first_viable` are affected. Both call sites (default and observed-only at line 6107) benefit from the fix.

## Verification

1. **Unit tests**: `python3 -m pytest tests/core/test_synthetic_twr_flows.py tests/core/test_realized_performance_analysis.py -x -q`
2. **Schwab aggregate**: `get_performance(mode='realized', institution='schwab', format='agent')` — before: +17.53%, expect improvement toward -8.29%
3. **IBKR regression**: should stay near -8.04%
4. **Plaid regression**: should stay near -11.77%
