# Plan: Fix TWR Inception Month Return

**Priority:** High
**Added:** 2026-03-07

## Context

The realized performance TWR (time-weighted return) drops the inception month entirely, producing wildly incorrect results. With `start_date="2025-04-01"`:
- Engine TWR: **53.9%** (chains from May, skips April)
- IBKR TWR: **0.29%**
- Engine simple return: **-2.4%** (correct ballpark)

**Root cause chain** (two bugs):

1. **Benchmark alignment drops inception month.** `calc_monthly_returns()` (`factor_utils.py:53`) uses `pct_change().dropna()` — the first month is always NaN. When aligned with portfolio returns at `engine.py:2393-2398` AND `aggregation.py:605-609`, `.dropna()` kills the inception row.

2. **Synthetic TWR flows distort inception month return.** `twr_external_flows` (`engine.py:1906`) includes `synthetic_twr_flows` — a $39,677 inflow at inception representing all 22 synthetic positions. In `compute_twr_monthly_returns()` (`nav.py:735-744`), the `idx==0` special case computes `day_nav / net_flow` = $22,289 / $39,677 = 0.562 as the inception "growth factor." This makes April's return **-64.4%** instead of the correct **-36.6%**.

**These compound**: Bug 2 produces a garbage -64.4% April return, then Bug 1 drops it entirely, masking the problem. The TWR then chains from May's $14K base, inflating all subsequent returns.

## Changes (3 files)

### 1. Benchmark — fetch from first of prior month

**Files:** `core/realized_performance/engine.py` (line ~2382) AND `core/realized_performance/aggregation.py` (line ~594)

Both locations fetch benchmark prices starting at `inception_date`. Shift the start to the first day of the prior month so `pct_change()` has a prior month-end close to compute the inception month return:

```python
benchmark_start = (pd.Timestamp(inception_date).to_period("M") - 1).to_timestamp().to_pydatetime().replace(tzinfo=None)
benchmark_prices = fetch_monthly_close_fn(
    benchmark_ticker,
    start_date=benchmark_start,  # was: inception_date
    end_date=end_date,
    ...
)
```

Using first-of-prior-month (not `MonthEnd(1)` back) ensures `fetch_monthly_close` captures the full prior month of daily prices for resampling, avoiding weekend/holiday edge cases.

**Mid-month inception note:** For month-start inceptions (e.g. April 1), the portfolio and benchmark month returns align perfectly. For mid-month inceptions, the portfolio return is a partial month while the benchmark return is a full calendar month — this is an inherent mismatch in monthly TWR alignment. This plan targets the month-start case (our IBKR use case). Mid-month alignment is a separate enhancement if needed.

**Limitation:** If the benchmark ticker has no price history before inception (e.g., a newly-listed ETF), `calc_monthly_returns().dropna()` will still drop the inception month. This is an edge case — standard benchmarks (SPY, VTI) always have history.

### 2. TWR inception day — skip return, set baseline

**File:** `core/realized_performance/nav.py` (lines 735-744)

The `idx==0` special case currently computes `day_nav / net_flow` when there are inflows. This "cost basis multiple" approach is wrong when the inflow is a synthetic position contribution — it produces a fractional growth factor that distorts the entire month.

Replace the inception day logic: inception day contributes 0% return (no prior NAV to measure against). Set `prev_nav` so day 2+ chains correctly. Flows that land on inception day are absorbed into the baseline — they will be correctly flow-adjusted from day 2 onward via the GIPS formula.

```python
if idx == 0:
    # No prior NAV exists on inception day — no return to compute.
    # Any flows snapped to this day are absorbed into the baseline.
    # Day 2+ will flow-adjust correctly via the GIPS formula using
    # prev_nav and cf_in/cf_out.
    prev_nav = day_nav
    continue
```

With no external flows (our case), April chains daily returns from April 2 onward: `month_growth = nav_apr30 / nav_apr1 = 14128/22289 = 0.634` -> **-36.6%** return. Correct.

With a real deposit on inception day, the deposit is reflected in `day_nav` (NAV includes the cash). From day 2, the GIPS formula uses `prev_nav` (which includes the deposit) as the denominator. Any same-day P&L between deposit and close is small and unmeasurable without intraday data — treating it as 0% is standard GIPS practice for the first observation.

### 3. Legacy path — pass inception NAV (defensive)

**File:** `core/realized_performance/nav.py` (line 642, `compute_monthly_returns`)

Add optional `inception_nav: Optional[float] = None` parameter. When provided, use it as `v_start` for the first month instead of 0.0:

```python
v_start = inception_nav if (i == 0 and inception_nav is not None) else (prev_nav if i > 0 else 0.0)
```

**Caller** (`engine.py` line ~2212): Inside the `if legacy_monthly_return_path:` branch (line 2116), compute inception NAV and pass it. In the legacy branch, `daily_nav = monthly_nav.copy()` (line 2125), so `daily_nav.iloc[0]` is the first month-end NAV, NOT inception NAV. Instead, compute it explicitly inside the legacy branch:

```python
if legacy_monthly_return_path:
    inception_nav_value = float(nav.compute_monthly_nav(
        position_timeline=position_timeline,
        month_ends=[inception_date],
        price_cache=price_cache,
        fx_cache=fx_cache,
        cash_snapshots=cash_snapshots,
        futures_keys=futures_keys,
    ).iloc[0])
    # ... existing monthly_nav computation ...
    monthly_returns, return_warnings = nav.compute_monthly_returns(
        monthly_nav=monthly_nav,
        net_flows=net_flows,
        time_weighted_flows=tw_flows,
        inception_nav=inception_nav_value,
    )
```

**Important:** This inception NAV computation and the `inception_nav=` kwarg must be INSIDE the `if legacy_monthly_return_path:` branch only. Do NOT add the extra `compute_monthly_nav()` call on the normal TWR path — it's unnecessary there and would break call-count assertions in tests.

This fix is defensive — the legacy path is currently inactive but could be activated by test monkey-patches.

**Test updates required:** All legacy-path test stubs that mock `compute_monthly_returns` with a fixed-arity signature will fail with `TypeError` once the engine passes `inception_nav`. Add `**kwargs` to ALL fakes. Exhaustive list (run `grep -n "compute_monthly_returns" tests/` to verify none are missed):
- `tests/core/test_realized_mwr.py:222`
- `tests/core/test_realized_performance_analysis.py` — lines 137, 276, 433, 1747, 2508, 4707, 4825, 4943, 5263, 5449, 5580, 5727, 5830, 6251, 7917, 8078, 8310, 8459
- `tests/core/test_realized_performance_segment.py:363, 1123, 1251`
- `tests/core/test_realized_performance_bond_pricing.py:148`

**Call ordering note:** The extra `compute_monthly_nav()` call for inception NAV is INSIDE the `if legacy_monthly_return_path:` branch, before the existing `monthly_nav` computation. Tests with stateful NAV fakes or exact-call-count assertions may need adjustment because this adds one more call to the fake:
- `test_realized_performance_analysis.py:5823` (stateful `_fake_nav` by call count)
- `test_realized_performance_analysis.py:1700, 1783` (exact call count assertions)

## What does NOT change

- `compute_monthly_external_flows()` — unchanged
- `derive_cash_and_external_flows()` — unchanged
- Synthetic TWR flow generation (`_synthetic_events_to_flows`) — still generated, still in `twr_external_flows`. The fix is in how the TWR function handles them on inception day, not in suppressing them.
- Cash replay / back-solve — unchanged
- All other months' returns — unchanged (only inception day logic changes)

## Verification

### Manual
1. Run `get_performance(mode="realized", source="ibkr_flex", start_date="2025-04-01", format="full", debug_inference=True, output="file", use_cache=False)`
2. Check April is now in `monthly_returns` (was missing)
3. Check April return ~ -36.6% (not -64.4% or 0%)
4. Check benchmark April return exists (was NaN/missing)
5. Check TWR is much closer to IBKR's 0.29% (should be in the low single digits, not 53.9%)
6. Run without start_date — verify behavior unchanged (backward compatible)

### Automated
7. Run existing tests: `python3 -m pytest tests/core/test_realized_performance_analysis.py -x`
8. Run MWR tests: `python3 -m pytest tests/core/test_realized_mwr.py -x`
9. Run synthetic TWR tests: `python3 -m pytest tests/core/test_synthetic_twr_flows.py -x`
10. Run segment tests: `python3 -m pytest tests/core/test_realized_performance_segment.py -x`
11. Run bond pricing tests: `python3 -m pytest tests/core/test_realized_performance_bond_pricing.py -x`
12. Run cash anchor tests: `python3 -m pytest tests/core/test_realized_cash_anchor.py -x`
13. Verify `test_compute_monthly_returns_*` tests still pass (legacy path tests)

### New regression tests
14. **TWR inception flow test — positive flow:** Unit test for `compute_twr_monthly_returns` with a positive inflow snapped onto the first NAV day. Verify inception day contributes 0% and subsequent daily returns chain correctly from the inception NAV baseline.
15. **TWR inception flow test — negative flow:** Same as above but with a negative flow (withdrawal) on inception day. Verify inception day still contributes 0%.
16. **TWR inception flow test — mixed flows:** Positive inflow + negative outflow on inception day. Verify inception day still contributes 0%.
17. **TWR inception flow test — pre-inception weekend snap:** Flow dated on a weekend before inception that gets snapped to inception day via `searchsorted`. Verify it is absorbed into the baseline correctly.
18. **Benchmark alignment test:** Exercise real `calc_monthly_returns` (not stubbed) with benchmark prices fetched from the prior month. Assert that `fetch_monthly_close_fn` is called with the prior-month start date (not `inception_date`). Verify the inception month survives `.dropna()` alignment in both the engine and aggregation paths.
19. **Legacy path inception_nav test:** Activate the legacy path via monkey-patch and verify that `compute_monthly_returns` receives `inception_nav` kwarg and uses it as `v_start` for the first month instead of 0.0. Assert the first month return is computed against the inception NAV, not against zero.
