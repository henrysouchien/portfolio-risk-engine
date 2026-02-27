# P2 Fix: Remove Synthetic Cash Events from Cash Replay

## Context

After the P1 fix (commit `efd8f1a6` — UNKNOWN/fx_artifact filtering + futures inference gating), the system still reports **+83.91%** when actual broker returns are **-8% to -12%**. The remaining distortion comes from synthetic positions: brokerage holdings with no opening BUY trade in transaction history.

**How the bug works:**
1. `build_position_timeline()` (line 1160-1215) detects positions where `missing_openings > 1e-6` → creates synthetic entry at `inception - 1s`
2. `_create_synthetic_cash_events()` (line 1285-1360) converts those into pseudo BUY transactions with `source="synthetic_cash_event"`
3. Line 3074: `transactions_for_cash = fifo_transactions + synthetic_cash_events` — synthetic BUYs enter the cash replay
4. Cash replay: synthetic BUY of e.g. NVDA 25 @ $115 → `cash -= $2,883` → cash goes negative → inference injects fake contribution of +$2,883
5. 10 synthetic positions × avg ~$6.7K each = **~$67K fake contributions** in Modified Dietz denominator
6. `SYNTHETIC_PNL_SENSITIVITY` gate fires → switches to observed-only track, but that track has edge cases with V_start ≈ 0

**The fix:** Remove synthetic cash events from `transactions_for_cash`. Synthetic positions remain in the position timeline (they're real holdings), but their cost doesn't inflate the cash replay denominator. Their value appears in V_start naturally via `compute_monthly_nav()`, treating them as pre-existing capital.

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

This is the entire core fix. Synthetic positions still appear in `position_timeline` (valued correctly at month-end via `compute_monthly_nav` line 1580-1595). They just don't create fake cash outflows that trigger the inference engine.

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

### File 2: `tests/core/test_realized_performance_analysis.py`

#### C. Update existing test — line 2982

`test_synthetic_positions_with_cash_produce_correct_nav_and_returns` currently passes `synth_cash` into `derive_cash_and_external_flows()`. Update to pass empty list (reflecting the fix):

```python
cash_snapshots, external_flows = rpa.derive_cash_and_external_flows(
    fifo_transactions=[],  # P2 fix: synthetic cash events no longer enter cash replay
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

#### D. Add P2 integration regression test

The regression test must exercise the `transactions_for_cash` composition path inside `analyze_realized_performance()` (not just call `derive_cash_and_external_flows` directly, which would pass even before the fix). Use `monkeypatch` to control inputs and verify that `_create_synthetic_cash_events` output does NOT appear in the cash replay:

```python
def test_synthetic_cash_events_excluded_from_cash_replay_integration(monkeypatch):
    """P2 regression: synthetic cash events must NOT enter transactions_for_cash.

    This is an integration test that exercises the composition at line 3074.
    We monkeypatch _create_synthetic_cash_events to return a known synthetic BUY,
    then verify that the resulting external_flows do NOT include its cash impact.
    """
    # Create a synthetic cash event for NVDA ($2500 notional)
    fake_synthetic = [{
        "type": "BUY", "symbol": "NVDA",
        "date": datetime(2024, 1, 30, 23, 59, 59),
        "quantity": 5.0, "price": 500.0, "fee": 0.0,
        "currency": "USD", "source": "synthetic_cash_event",
    }]
    original_create = rpa._create_synthetic_cash_events

    def patched_create(*args, **kwargs):
        result, warnings = original_create(*args, **kwargs)
        return result + fake_synthetic, warnings

    monkeypatch.setattr(rpa, "_create_synthetic_cash_events", patched_create)

    # Run analyze_realized_performance with minimal inputs
    # (mock the heavy dependencies: price fetching, benchmark, etc.)
    # ...
    # After the fix, transactions_for_cash = fifo_transactions (no synthetic),
    # so the $2500 NVDA synthetic BUY should NOT appear in external_flows.
    #
    # Specific assertion approach: check that the inferred_flow_diagnostics
    # total_inferred_net_usd does NOT include the $2500 synthetic notional.
```

**Alternative simpler approach:** Instead of a full integration test with heavy mocking, verify the composition directly by checking that `transactions_for_cash` (which becomes an internal variable) does not contain any `source="synthetic_cash_event"` entries. This can be done by monkeypatching `_compose_cash_and_external_flows` to capture its input:

```python
def test_synthetic_cash_events_excluded_from_transactions_for_cash(monkeypatch):
    """P2 regression: transactions_for_cash must not contain synthetic_cash_event entries."""
    captured_txns = []
    original_compose = None  # will be set in monkeypatch

    # We'll capture what gets passed to _compose_cash_and_external_flows
    # at line 3515 (the synthetic-enhanced track call)
    # and verify no synthetic_cash_event source is present.
    # Implementation details in the actual test code.
```

**Recommended:** Keep the unit-level test (calling `derive_cash_and_external_flows` directly with real vs synthetic inputs) as a simple sanity check, AND add a comment in the test docstring explaining that the real guard is the one-line change at line 3074. The composition is simple enough that a unit test plus code review is sufficient — we don't need a full integration test with heavy mocking for a one-line deletion.

## Why existing tests pass unchanged

- The 5 existing `test_derive_cash_*` tests pass `fifo_transactions` directly — they never include synthetic cash events
- `test_analyze_realized_performance_provider_mode_synthetic_cash_events_do_not_inflate_fallback_inference` monkeypatches `_create_synthetic_cash_events` — its output never enters `transactions_for_cash` anyway after the fix, so assertions pass more cleanly
- All P1 tests (UNKNOWN/fx_artifact filtering, futures gating) are unaffected — they test `derive_cash_and_external_flows` directly
- `_create_synthetic_cash_events()` unit tests test the function in isolation, not its integration with `transactions_for_cash`

## Effect on SYNTHETIC_PNL_SENSITIVITY gate

After this fix, the synthetic-enhanced and observed-only NAV tracks converge because:
- **Before:** Enhanced track has $67K fake contributions in denominator; observed track has none → large gap → gate fires
- **After:** Enhanced track has real cash only; observed track also has real cash only → gap is just synthetic position value difference → much smaller → gate may stop firing

This is correct: if the gate stops firing, it means the synthetic-enhanced track is now trustworthy and should be used (it has better position coverage since it includes real brokerage holdings).

## Verification

1. `pytest tests/core/test_realized_performance_analysis.py -v` — all existing + new tests pass
2. `pytest tests/ --ignore=tests/api -q` — full suite green
3. Manual: `python3 tests/utils/show_api_output.py "get_performance(mode='realized', format='agent')"` — confirm returns move toward -8% to -12% range
4. Check `synthetic_policy_impact_usd` is much smaller (was ~$67K, should be near position value difference only)
5. Verify `SYNTHETIC_PNL_SENSITIVITY` flag behavior — may stop firing (correct)

## Not in scope

- Dead code cleanup for `synthetic_cash_event` routing in `_compose_cash_and_external_flows` (lines 3237-3239, 3327-3328) — harmless no-ops, can clean up later
- Plaid security_id resolution (P3)
- `brokerage_name` population (P3)
