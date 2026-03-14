# Plan: Add MWR/IRR (Money-Weighted Return) Metric

## Context

Our realized performance engine computes TWR (time-weighted return) via Modified Dietz and True TWR paths. TWR isolates investment performance from cash flow timing — ideal for comparing manager skill. However, **Schwab reports MWR** (-8.29%), and our TWR (+21.94%) creates a confusing gap. MWR (= XIRR = dollar-weighted return) captures the actual investor experience including contribution/withdrawal timing. Adding MWR as a complementary metric lets users see both perspectives.

**Key insight**: All required inputs already exist in the engine — `external_flows` as `List[Tuple[datetime, float]]` (real investor cash flows), `daily_nav`/`monthly_nav` series, and NAV endpoints. This is primarily a threading exercise.

## Dependency: scipy

scipy is **not** in requirements.txt. We need `scipy.optimize.brentq` for the XIRR root-finding. scipy is the standard choice — already an indirect dependency via statsmodels/cvxpy. Add `scipy>=1.10.0`.

## Implementation

### Step 1: New module `core/realized_performance/mwr.py` (~60 lines)

XIRR solver + convenience wrapper.

**`xirr(dates, amounts, guess=0.1)`**: Core solver.
- XNPV(r) = Σ amount_i / (1+r)^((d_i - d_0)/365.25)
- Find r where XNPV(r) = 0 using `scipy.optimize.brentq`
- Bracket search: start with [-0.5, 2.0], widen progressively up to [-0.99, 100.0] if no sign change
- Fallback to `scipy.optimize.newton` if bracket search fails entirely
- Returns `Optional[float]` (annualized IRR as decimal, e.g., 0.08 = 8%)

**`compute_mwr(external_flows, nav_start, nav_end, start_date, end_date)`**: Convenience wrapper.
- Constructs XIRR cash flow vector: `[(-nav_start, start), (-flow_i, date_i), ..., (+nav_end, end)]`
- External flows sign convention: in our system, contributions are positive and withdrawals are negative. For XIRR, we **invert** — contributions become negative (investor puts money in), withdrawals become positive (investor takes money out).
- Returns `(Optional[float], status_str)` where status is "success" | "failed" | "no_data"

**Edge cases**:
- No external flows → simple: (nav_end / nav_start)^(365.25/days) - 1
- nav_start ≈ 0 → return (None, "no_data")
- Period < 30 days → return (None, "no_data") — too short for meaningful annualization
- No sign change in XNPV across bracket → return (None, "failed") with warning
- Multiple IRR patterns (non-conventional cash flows) → brentq returns the first root in bracket, which is the financially meaningful one for standard investment flows
- Solver fails → return (None, "failed")
- Pre-window flows → `compute_mwr` filters `external_flows` to `[start_date, end_date]` range to avoid counting flows before the aligned window starts (alignment may start after inception)

### Step 2: Integrate in `engine.py` (~15 lines)

**File**: `core/realized_performance/engine.py`

**Location**: After `performance_metrics = compute_performance_metrics_fn(...)` (line ~2115) and before `realized_metadata` dict (line ~2175). All inputs already in scope:
- `external_flows` (line ~1513) — `List[Tuple[datetime, float]]` — **real investor flows only** (NOT `twr_external_flows` which includes synthetic TWR-only flows)
- `official_nav_start` / `official_nav_end` (lines ~1917-1918) — tied to `aligned_start`/`aligned_end`
- `aligned_start` / `aligned_end` — use these as date anchors (consistent with NAV endpoints)

```python
from . import mwr as _mwr
mwr_value, mwr_status = _mwr.compute_mwr(
    external_flows=external_flows,      # real investor flows, NOT twr_external_flows
    nav_start=official_nav_start,
    nav_end=official_nav_end,
    start_date=aligned_start,           # consistent with NAV endpoint dates
    end_date=aligned_end,
)
```

**Why `external_flows` not `twr_external_flows`**: `twr_external_flows` includes synthetic flows added for TWR correctness (e.g., inferred position entries). MWR measures the actual investor's dollar-weighted experience, so it should only include real cash movements (deposits, withdrawals, trade cash legs).

Add to `realized_metadata` dict (after `external_net_flows_usd`, line ~2173):
```python
"money_weighted_return": round(mwr_value * 100, 2) if mwr_value is not None else None,
"mwr_status": mwr_status,
```

Note: `money_weighted_return` is in **percent** (like all TWR fields from `compute_performance_metrics` — e.g., 8.47 = 8.47%).

Promote to top-level `performance_metrics` (after line ~2397):
```python
performance_metrics["money_weighted_return"] = realized_metadata["money_weighted_return"]
```

### Step 3: Add fields to `RealizedMetadata` dataclass

**File**: `core/result_objects/realized_performance.py`

Add 2 fields to `RealizedMetadata` (after `external_net_flows_usd`, line ~145):
```python
money_weighted_return: Optional[float] = None   # percent (8.47 = 8.47%), like TWR fields
mwr_status: str = "not_computed"                # "success" | "failed" | "no_data" | "not_computed"
```

Add to `to_dict()` (after `external_net_flows_usd`, line ~219):
```python
"money_weighted_return": self.money_weighted_return,
"mwr_status": self.mwr_status,
```

Add to `from_dict()` (after `external_net_flows_usd`, line ~305):
```python
money_weighted_return=d.get("money_weighted_return"),
mwr_status=d.get("mwr_status", "not_computed"),
```

Add to `RealizedPerformanceResult.to_dict()` (after `external_net_flows_usd`, line ~422):
```python
"money_weighted_return": self.realized_metadata.money_weighted_return,
```

### Step 4: Aggregation — per-account + consolidated MWR

**File**: `core/realized_performance/aggregation.py`

**Per-account MWR** comes for free — Step 2 puts the computation inside `_analyze_realized_performance_single_scope` which runs once per account.

**Consolidated MWR** requires separate computation because MWR doesn't aggregate linearly across accounts. After the `realized_metadata` dict assembly (~line 1046):

1. Use `agg_external_flows` (already computed at line ~512 via `_sum_account_daily_series()`) — these are the real investor flows aggregated across accounts
2. Get aggregated NAV endpoints from `agg_nav` (the merged daily NAV series, already in scope)
3. Call `mwr.compute_mwr()` on the combined data
4. Set `realized_metadata["money_weighted_return"]` and `mwr_status`

**Important**: `_postfilter["external_flows"]` currently stores `twr_external_flows` (includes synthetic). We need to also persist the real investor flows. In engine.py, add to `_postfilter`:
```python
"investor_external_flows": _helpers._flows_to_dict(external_flows),  # real flows only
```

Then in aggregation, call `_sum_account_daily_series()` with `external_flow_key="investor_external_flows"` to get combined real investor flows for the consolidated MWR computation.

~20 lines of new code across engine.py and aggregation.py.

### Step 5: Add scipy to requirements.txt

**File**: `requirements.txt`

Add after `cvxpy>=1.6.0` (line 59):
```
scipy>=1.10.0  # XIRR solver for money-weighted return (core/realized_performance/mwr.py)
```

### Step 6: Update `__init__.py`

**File**: `core/realized_performance/__init__.py`

Follow existing pattern in full:
1. Add `mwr` to the module import on line 3: `from . import _helpers, aggregation, ..., mwr, ...`
2. Add `from .mwr import *` (like other submodules, lines 4-13)
3. Add `mwr.__all__` to the `__all__` extension loop (lines 91-102)
4. Add `"mwr"` to the top-level `__all__` list (lines 52-89)

## Files Modified

| File | Change |
|------|--------|
| `core/realized_performance/mwr.py` | **NEW** — XIRR solver + `compute_mwr()` |
| `core/realized_performance/__init__.py` | Import `mwr` module |
| `core/realized_performance/engine.py` | Call `compute_mwr()`, add fields to `realized_metadata` |
| `core/realized_performance/aggregation.py` | Consolidated MWR from combined flows |
| `core/result_objects/realized_performance.py` | 2 new fields on `RealizedMetadata` + serialization |
| `requirements.txt` | Add `scipy>=1.10.0` |

## What We Defer

- **Frontend display**: Backend fields auto-flow through `to_api_response()`. Frontend adapter + UI changes deferred to a follow-up.
- **Performance flags**: MWR-specific flags (e.g., "MWR significantly differs from TWR") deferred until we validate the numbers against real data.

## Tests

New file: `tests/core/test_realized_mwr.py`

1. **`test_xirr_simple_growth`** — $100 → $110 in 1 year → IRR ≈ 10%
2. **`test_xirr_with_contribution`** — $100 invested, $50 added at 6mo, ends $165
3. **`test_xirr_with_withdrawal`** — $100 invested, $20 withdrawn at 6mo
4. **`test_compute_mwr_no_flows`** — No external flows → simple annualized return
5. **`test_compute_mwr_short_period`** — < 30 days → None + "no_data"
6. **`test_compute_mwr_zero_nav`** — nav_start ≈ 0 → None + "no_data"
7. **`test_compute_mwr_solver_failure`** — Adversarial flows → None + "failed"
8. **`test_mwr_in_engine_output`** — Full engine integration via existing test harness
9. **`test_mwr_aggregation`** — Multi-account: consolidated MWR from combined flows

## Verification

```bash
# Unit tests for MWR module
pytest tests/core/test_realized_mwr.py -x -v

# Existing realized performance tests still pass
pytest tests/core/test_realized_performance_analysis.py -x -q
pytest tests/core/test_realized_cash_anchor.py -x -q
pytest tests/mcp_tools/test_performance.py -x -q

# Backward compat
python3 -c "from core.realized_performance.mwr import compute_mwr; print('OK')"

# Live: get_performance(mode="realized") → check realized_metadata.money_weighted_return
```
