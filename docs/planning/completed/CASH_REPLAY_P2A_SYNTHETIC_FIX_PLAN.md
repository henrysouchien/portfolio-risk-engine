# P2A Fix: Remove Synthetic Cash Events from Cash Replay + Diagnostic-Only Sensitivity Gate

## Sequencing Note (2026-02-25)

This document captures the first Phase 2 slice (**P2A**) and has already been implemented.
Follow-on work is tracked separately as **P2B** in:
- `docs/planning/CASH_REPLAY_P2_FIX_PLAN.md`

## Context

After the P1 fix (commit `efd8f1a6` — UNKNOWN/fx_artifact filtering + futures inference gating), the system still reports **+83.91%** when actual broker returns are **-8% to -12%**. The remaining distortion comes from synthetic positions: brokerage holdings with no opening BUY trade in transaction history.

**How the bug works:**
1. `build_position_timeline()` (line 1160-1215) detects positions where `missing_openings > 1e-6` → creates synthetic entry at `inception - 1s`
2. `_create_synthetic_cash_events()` (line 1285-1360) converts those into pseudo BUY transactions with `source="synthetic_cash_event"`
3. Line 3074: `transactions_for_cash = fifo_transactions + synthetic_cash_events` — synthetic BUYs enter the cash replay
4. Cash replay: synthetic BUY of e.g. NVDA 25 @ $115 → `cash -= $2,883` → cash goes negative → inference injects fake contribution of +$2,883
5. 10 synthetic positions × avg ~$6.7K each = **~$67K fake contributions** in Modified Dietz denominator
6. `SYNTHETIC_PNL_SENSITIVITY` gate fires → switches to observed-only track, but that track has V_start=0 edge cases and its own extreme return spikes

**Secondary problem:** The `SYNTHETIC_PNL_SENSITIVITY` gate (lines 3985-4026) was designed to catch fake contributions from synthetic cash events. After removing those, the $28K gap between enhanced and observed tracks is now just real position value (NVDA, V, etc. unrealized gains). The gate still fires ($28K > $5K threshold) and forces the **worse** observed-only track:

| Track | Total Return | Worst Months |
|---|---|---|
| Enhanced (after P2A) | 273% | Aug 2024: +99% |
| Observed-only | 391% | Sept 2024: +151%, Mar/Apr: +34/33% |

The observed-only track is strictly worse because V_start=0 for the first 5 months (no real positions exist yet).

## Changes

### File 1: `core/realized_performance_analysis.py`

#### A. Core fix — line 3074

Change:
```python
transactions_for_cash = fifo_transactions + synthetic_cash_events
```
to:
```python
transactions_for_cash = fifo_transactions
```

This is the core fix. Synthetic positions still appear in `position_timeline` (valued correctly at month-end via `compute_monthly_nav` line 1580-1595). They just don't create fake cash outflows that trigger the inference engine.

**Why this works for Modified Dietz:**
- V_start at inception = position_value (synthetic + real) + cash (real only) — synthetic positions appear as pre-existing capital
- `flow_net` and `flow_weighted` only include real external flows — no fake contributions
- `r = (V_end - V_start - flow_net) / (V_start + flow_weighted)` gives correct return on real + pre-existing capital

#### B. Update warning message — lines 3070-3073

Change the warning from "Created N synthetic cash event(s) for cash-flow reconstruction" to reflect that synthetic events are now diagnostic-only:

```python
if synthetic_cash_events:
    warnings.append(
        f"Detected {len(synthetic_cash_events)} synthetic position(s) with estimated cash impact. "
        "Synthetic positions are valued in NAV but excluded from cash replay to avoid "
        "inflating the Modified Dietz denominator."
    )
```

#### C. Make SYNTHETIC_PNL_SENSITIVITY gate diagnostic-only — lines 3985-4026

The gate at line 3985 (`if has_high_synthetic_sensitivity:`) currently switches `selected_aligned` from the synthetic-enhanced track to the observed-only track. After the P2A fix, the enhanced track is more trustworthy (it has real starting capital from synthetic positions), while the observed-only track suffers from V_start=0 edge cases.

**Change:** Keep all diagnostic computation (the `SYNTHETIC_PNL_SENSITIVITY` flag, the `synthetic_policy_impact_usd` value, the warning message) but **remove the track switch**. Specifically, remove or skip the block that:
1. Computes `observed_monthly_returns` from the observed-only track
2. Applies clamping and extreme-return filtering to observed returns
3. Builds `observed_aligned` DataFrame
4. Overwrites `selected_aligned = observed_aligned`

The flag still fires. The warning still appears. The agent still sees `SYNTHETIC_PNL_SENSITIVITY: high` in data quality flags. But the headline return metrics now come from the synthetic-enhanced track, which has better starting capital and fewer V_start=0 edge cases.

**Before (lines 3985-4026):**
```python
if has_high_synthetic_sensitivity:
    observed_monthly_returns, _observed_return_warnings = compute_monthly_returns(
        monthly_nav=observed_monthly_nav,
        net_flows=observed_net_flows,
        time_weighted_flows=observed_tw_flows,
    )
    # ... clamping, filtering, building observed_aligned ...
    if not observed_aligned.empty:
        selected_aligned = observed_aligned  # ← THIS IS THE PROBLEM
        warnings.append("Return metrics are computed from observed-only NAV ...")
    else:
        warnings.append("Observed-only return series was unavailable; falling back ...")
```

**After:** Remove the entire `if has_high_synthetic_sensitivity:` block that switches `selected_aligned`. The observed-only NAV and flows are still computed (lines 3534-3558) for the P&L sensitivity diagnostic, and the `SYNTHETIC_PNL_SENSITIVITY` flag is still emitted (lines 3869-3883). Only the track-switch logic is removed.

### File 2: `tests/core/test_realized_performance_analysis.py`

#### D. Update existing test — line 2982

`test_synthetic_positions_with_cash_produce_correct_nav_and_returns` currently passes `synth_cash` into `derive_cash_and_external_flows()`. Update to pass empty list (reflecting the fix):

```python
cash_snapshots, external_flows = rpa.derive_cash_and_external_flows(
    fifo_transactions=[],  # P2A fix: synthetic cash events no longer enter cash replay
    income_with_currency=[],
    fx_cache=fx_cache,
)
```

**Important:** Also update the `return_warnings` assertion. With `fifo_transactions=[]`, the first month has V_start=0 and no inflows → `compute_monthly_returns()` emits a warning ("V_start=0 with no detected inflows; return set to 0."). Change:

```python
# Before:
assert return_warnings == []
# After:
assert len(return_warnings) == 1  # V_start=0 warning for inception month
assert "V_start=0" in return_warnings[0]
```

Return value assertions unchanged: inception return = 0.0, month 2 return = 0.1.

#### E. Add P2 regression test

New test that verifies synthetic positions don't inflate external flows:

```python
def test_synthetic_cash_events_excluded_from_cash_replay_no_denominator_inflation():
    """P2 regression: synthetic cash events should NOT enter cash replay."""
    inception = datetime(2024, 1, 31)
    fifo_transactions = [
        {"symbol": "AAPL", "type": "BUY", "date": datetime(2024, 2, 5),
         "quantity": 10.0, "price": 100.0, "fee": 0.0, "currency": "USD"},
    ]
    current_positions = {
        "AAPL": {"shares": 10.0, "currency": "USD"},
        "NVDA": {"shares": 5.0, "currency": "USD", "value": 2500.0},
    }
    timeline, _, synthetic_entries, _, _ = rpa.build_position_timeline(
        fifo_transactions=fifo_transactions,
        current_positions=current_positions,
        inception_date=inception,
        incomplete_trades=[],
    )
    # Synthetic entry exists for NVDA (no opening BUY in fifo_transactions)
    assert any(e["ticker"] == "NVDA" for e in synthetic_entries)

    fx_cache = {"USD": _constant_fx(start="2024-01-31", periods=4, value=1.0)}

    # Cash replay uses ONLY fifo_transactions — NOT fifo_transactions + synthetic_cash_events
    cash_snapshots, external_flows = rpa.derive_cash_and_external_flows(
        fifo_transactions=fifo_transactions,
        income_with_currency=[],
        fx_cache=fx_cache,
    )
    total_external = sum(amt for _, amt in external_flows)
    # Only the real AAPL BUY ($1000) should drive inference — NOT the $2500 synthetic NVDA
    assert total_external == pytest.approx(1000.0)
    assert total_external < 1500.0  # guard: no synthetic inflation
```

#### F. Update any test that asserts observed-only track is selected

If any existing test asserts that `selected_aligned` or return metrics come from the observed-only track when `SYNTHETIC_PNL_SENSITIVITY` fires, update it to reflect that the enhanced track is now always used. Search for tests referencing "observed-only NAV" or "Return metrics are computed from observed-only" and update assertions accordingly.

## Why existing tests pass unchanged

- The 5 existing `test_derive_cash_*` tests pass `fifo_transactions` directly — they never include synthetic cash events
- `test_analyze_realized_performance_provider_mode_synthetic_cash_events_do_not_inflate_fallback_inference` monkeypatches `_create_synthetic_cash_events` — its output never enters `transactions_for_cash` anyway after the fix
- All P1 tests (UNKNOWN/fx_artifact filtering, futures gating) are unaffected
- `_create_synthetic_cash_events()` unit tests test the function in isolation

## Verification

1. `pytest tests/core/test_realized_performance_analysis.py -v` — all existing + new tests pass
2. `pytest tests/ --ignore=tests/api -q` — full suite green
3. Manual: `python3 tests/utils/show_api_output.py "get_performance(mode='realized', format='agent')"` — confirm returns are from enhanced track (should show ~273% before extreme-return filtering, much lower after filtering)
4. Verify enhanced track monthly returns are smoother than observed-only (no +151% Sept spike)
5. `SYNTHETIC_PNL_SENSITIVITY` flag should still appear in data quality flags (diagnostic-only, no track switch)

## Not in scope

- Dead code cleanup for `synthetic_cash_event` routing in `_compose_cash_and_external_flows`
- Further Modified Dietz V_start=0 edge case handling (separate investigation)
- Plaid security_id resolution (P3)
- `brokerage_name` population (P3)
