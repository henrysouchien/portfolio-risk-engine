# GIPS-Compliant TWR: BOD Flow Method + CASH_RECEIPT Date Fix

## Context

Our daily TWR implementation (commit `4adb8176`) computes sub-period returns using `pre_flow_nav = day_nav - flow_amt`. This breaks when deposits and position purchases happen on the same day — the EOD NAV includes intraday P&L on newly-bought positions funded by the deposit, so subtracting just the flow gives a phantom pre-flow value.

**Account 252 example (Jan 2025):** $65K deposit on Jan 30 (`time`), positions bought same day. EOD NAV = $65,191. `pre_flow = 65,191 - 65,000 = $191`, but actual pre-deposit portfolio was ~$163. Result: January return = -63% (with flow dated Jan 31 via `tradeDate`) or +37% (with flow on Jan 30 but using `day_nav - flow`). Both wrong.

**Fix:** Two changes following CFA GIPS standards:
1. **BOD method**: Use `V_{D-1}` (previous day's close) instead of `day_nav - flow` for the pre-flow sub-period end
2. **CASH_RECEIPT date**: Use `time` (actual receipt) instead of `tradeDate` (T+1 settlement) for Schwab bank transfers

## GIPS Standard Reference

The industry-standard daily TWR formula (BOD-for-inflows convention):

| Day Type | Formula |
|----------|---------|
| No flows | `R = V_D / V_{D-1} - 1` |
| Inflow CF on day D | `R = V_D / (V_{D-1} + CF) - 1` |
| Outflow W on day D | `R = (V_D + W) / V_{D-1} - 1` |
| Mixed | `R = (V_D + CF_out) / (V_{D-1} + CF_in) - 1` |

Key insight: no need for `pre_flow_nav` derivation. The formula uses `V_{D-1}` (observable) directly.

## Files to Modify

| File | Change |
|------|--------|
| `core/realized_performance_analysis.py` | Rewrite `compute_twr_monthly_returns()` inner loop to use GIPS BOD formula |
| `providers/flows/schwab.py` | Use `time` for CASH_RECEIPT rows in `_flow_event()` |
| `tests/core/test_realized_performance_analysis.py` | Update TWR test assertions for BOD semantics |

## Change 1: TWR formula (`core/realized_performance_analysis.py`)

### Current (lines 2044-2072)

```python
subperiod_start_nav = _as_float(nav.iloc[0], 0.0)
for idx, day in enumerate(nav_idx):
    day_nav = _as_float(nav.loc[day], 0.0)
    ...
    flow_amt = _as_float(flows_by_day.get(day, 0.0), 0.0)
    if abs(flow_amt) > 0.0:
        pre_flow_nav = day_nav - flow_amt          # ← wrong
        ...
        subperiod_start_nav = day_nav
    is_month_boundary = ...
    if is_month_boundary:
        r_month_close = ... end_nav=day_nav / start_nav=subperiod_start_nav
        subperiod_start_nav = day_nav
```

### New: GIPS BOD formula

Replace the inner loop with the standard daily chain-link approach. No need for separate "flow sub-period" and "month-close sub-period" — each day gets exactly one return.

**Flow aggregation change:** Replace `flows_by_day: Dict[Timestamp, float]` (net) with `flows_by_day: Dict[Timestamp, Tuple[float, float]]` storing `(total_inflows, total_outflows)` separately. This preserves GIPS mixed-flow correctness when inflows and outflows occur on the same day.

```python
# Build flows_by_day with separate inflow/outflow tracking
flows_by_day: Dict[pd.Timestamp, List[float, float]] = defaultdict(lambda: [0.0, 0.0])
for flow_date, amount in external_flows:
    amt = _as_float(amount, 0.0)
    if not np.isfinite(amt) or abs(amt) < 1e-12:
        continue
    flow_day = pd.Timestamp(flow_date).normalize()
    pos = int(nav_idx.searchsorted(flow_day, side="left"))
    snapped_day = nav_idx[min(pos, len(nav_idx) - 1)]
    if amt > 0:
        flows_by_day[snapped_day][0] += amt   # inflow
    else:
        flows_by_day[snapped_day][1] += amt   # outflow (negative)

prev_nav = _as_float(nav.iloc[0], 0.0)
for idx, day in enumerate(nav_idx):
    day_nav = _as_float(nav.loc[day], 0.0)
    month = day.to_period("M")
    month_has_data[month] = True

    # Separate inflows and outflows for GIPS mixed-flow formula.
    # flows_by_day stores (total_inflows, total_outflows) per day.
    cf_in, cf_out = flows_by_day.get(day, (0.0, 0.0))

    if idx == 0:
        # First day: if there's a net flow, treat as inception
        net_flow = cf_in + cf_out  # cf_out is negative
        if abs(net_flow) > 1e-12:
            if net_flow > 0:
                r = (day_nav / net_flow) - 1.0
            else:
                r = 0.0
            month_growth[month] *= (1.0 + r)
        prev_nav = day_nav
        continue

    # GIPS mixed-flow formula (BOD for inflows, EOD for outflows):
    #   R = (V_D + |CF_out|) / (V_{D-1} + CF_in) - 1
    # cf_out is stored as negative, so V_D + |CF_out| = V_D - cf_out
    numer = day_nav - cf_out      # day_nav + |outflows|
    denom = prev_nav + cf_in      # prev_nav + inflows

    if denom > 1e-12:
        r = (numer / denom) - 1.0
    elif abs(day_nav) < 1e-12:
        r = 0.0
    else:
        r = 0.0
        warnings.append(f"{day.date().isoformat()}: denominator ~0, return set to 0")

    month_growth[month] *= (1.0 + r)
    prev_nav = day_nav
```

**Key simplification:** Each day produces exactly one return. No splitting into "flow sub-period" + "month-close sub-period". The `_subperiod_return` helper function can be removed or simplified.

### Month boundary handling

The current code has explicit month-boundary logic to close out the month. With the day-by-day chain, this is no longer needed — the month's growth is the product of all daily returns within that month. The existing `month_growth[month] *= (1.0 + r)` accumulation already handles this.

Remove the `is_month_boundary` block entirely — the `subperiod_start_nav` tracking becomes `prev_nav` which updates every day regardless.

## Change 2: CASH_RECEIPT date (`providers/flows/schwab.py`)

### Current (lines 201-212)

```python
timestamp = normalize_event_time(
    row.get("date")
    or row.get("transactionDate")
    or row.get("tradeDate")
    or row.get("settlementDate")
    or row.get("time")
)
```

### New

```python
# CASH_RECEIPT (bank transfers): `tradeDate` is T+1 settlement, but
# cash is available on the `time` date and may fund same-day trades.
# Using `tradeDate` creates a 1-day gap where positions bought with
# the deposit appear in NAV before the flow is recorded.
row_type = row.get("type", "")
if row_type == "CASH_RECEIPT" and row.get("time"):
    timestamp = normalize_event_time(row["time"])
else:
    timestamp = normalize_event_time(
        row.get("date")
        or row.get("transactionDate")
        or row.get("tradeDate")
        or row.get("settlementDate")
        or row.get("time")
    )
```

All 10 CASH_RECEIPT rows with time/tradeDate discrepancy shift by exactly 1 day (verified in investigation). Midnight truncation still applies after `normalize_event_time()`.

**Timezone note:** `normalize_event_time()` in `providers/flows/common.py` (line 159) strips timezone info via `pd.Timestamp().to_pydatetime()`. The `time` values are UTC (e.g., `2025-01-30T19:45:24+0000`), which is 2:45 PM ET — safely the same business day. The subsequent `timestamp.replace(hour=0, ...)` at line 215 truncates to midnight. All 10 observed `time` values are between 15:00-20:00 UTC (morning-afternoon US Eastern), so no risk of landing on the wrong business day.

## Change 3: Tests (`tests/core/test_realized_performance_analysis.py`)

### Test 1: `test_compute_twr_monthly_returns_handles_flow_timing_split`

```
NAV: Jan 30=100, Jan 31=160, Feb 1=161, Feb 29=170
Flow: +50 on Jan 31
```

Current assertion: Jan return = 10% (uses `pre_flow = 160 - 50 = 110`)

BOD method:
- Jan 30→31: `R = 160 / (100 + 50) - 1 = 6.67%`
- Feb 1→29: `R_chain = (161/160) × (170/161) - 1 = 6.25%`

Update assertion: Jan = `160/150 - 1 ≈ 0.0667`, Feb = `170/160 - 1 = 0.0625`

### Test 2: `test_compute_twr_monthly_returns_snaps_weekend_flows_to_next_business_day`

```
NAV: Jan 5=100, Jan 8=200, Jan 31=210
Flow: +100 on Jan 6 (snaps to Jan 8)
```

Current assertion: Jan return = 5%

BOD method:
- Jan 5→8: `R = 200 / (100 + 100) - 1 = 0%`
- Jan 8→31: `R = 210 / 200 - 1 = 5%`
- Total: `(1.0)(1.05) - 1 = 5%`

**Same result.** No test change needed.

## New Tests to Add

### Test 3: Outflow (withdrawal)

```
NAV: Jan 2=1000, Jan 3=800, Jan 31=810
Outflow: -200 on Jan 3
```
EOD-for-outflows: `R_jan3 = (800 + 200) / 1000 - 1 = 0%`, `R_rest = 810/800 - 1 = 1.25%`
Total Jan = `(1.0)(1.0125) - 1 = 1.25%`

### Test 4: Mixed same-day inflow + outflow

```
NAV: Jan 2=1000, Jan 3=1050, Jan 31=1060
Inflow: +500, Outflow: -200 on Jan 3
```
Mixed formula: `R = (1050 + 200) / (1000 + 500) - 1 = 1250/1500 - 1 = -16.67%`
Then `R_rest = 1060/1050 - 1 = 0.95%`
Total Jan = `(0.8333)(1.0095) - 1 = -15.88%`

### Test 5: Zero-denominator warning

```
NAV: Jan 2=0, Jan 3=100
No flows.
```
Should produce warning and `r = 0` for Jan 2→3, then no further returns.

### Test 6: CASH_RECEIPT `time` precedence

Unit test for `_flow_event()`: verify that a row with `type="CASH_RECEIPT"`, `time="2025-01-30T19:45:00+0000"`, `tradeDate="2025-01-31T05:00:00+0000"` produces a flow event dated `2025-01-30`.

## Edge Cases

| Case | Current | BOD method |
|------|---------|------------|
| Flow on first day (idx=0) | `V_end / flow - 1` | Same — inception flow |
| Flow on last day of month | Sub-period split + 0% close | Single day return: `V_D / (V_{D-1} + CF) - 1` |
| Mixed same-day in+out | Net aggregated (loses directionality) | Separate `(cf_in, cf_out)` in mixed formula |
| Outflow (withdrawal) | `pre_flow = day_nav - (neg_flow)` — adds to NAV | `numer = V_D + |outflow|`, `denom = V_{D-1}` — correct EOD-for-outflows |
| Zero previous NAV | Warning, return=0 | Same |

## Verification

```bash
# 1. Existing tests (update assertions first)
python3 -m pytest tests/core/test_realized_performance_analysis.py -x -q -k "twr" 2>&1 | tail -10

# 2. Full test suite
python3 -m pytest tests/ -x -q -k "realized" 2>&1 | tail -20

# 3. Account 252 (2025 isolated): should approach broker +10.65%
python3 -c "
from mcp_tools.performance import _load_portfolio_for_performance
from core.realized_performance_analysis import analyze_realized_performance
user, uid, pd_, pr = _load_portfolio_for_performance(None, 'CURRENT_PORTFOLIO', use_cache=False, institution='charles_schwab', account='25524252', mode='realized')
r = analyze_realized_performance(pr, str(user), institution='charles_schwab', account='25524252')
twr = 1.0
for dt, v in sorted(r.monthly_returns.items()):
    if '2025' in str(dt): twr *= (1+v)
print(f'252 2025: {(twr-1)*100:+.2f}% (broker: +10.65%)')
"

# 4. Account 165: must stay near -8.29%
# 5. Account 013 (2025): should stay near -15% (close to broker -14.69%)
# 6. IBKR: must stay unchanged
```

## IBKR / Non-Schwab Impact

The TWR formula change is in the shared `compute_twr_monthly_returns()` function — it affects **all providers**, not just Schwab. However:

- IBKR prices are monthly (daily fallback returns monthly series). Daily NAV has fewer data points, so daily returns are computed over multi-day gaps. The BOD formula `V_D / (V_{D-1} + CF) - 1` still works correctly — `V_{D-1}` is the last available NAV, which may be weeks prior.
- IBKR flows are extracted from Flex queries with their own date fields (not affected by the CASH_RECEIPT change, which is Schwab-only).
- The CASH_RECEIPT date fix in `providers/flows/schwab.py` is gated by `row.get("type") == "CASH_RECEIPT"` — no effect on other providers.

IBKR must be explicitly verified (not just "unchanged" — actively run and compare).

## Acceptance Gates

- Account 252 January return: no longer -63% (should be near 0% or small positive)
- Account 165 (2025): unchanged within ±0.5pp of -8.30%
- Account 013 (2025): stays near -15% (within ±1pp)
- IBKR: actively verified, within ±0.5pp of current baseline (+15.69%)
- All existing tests pass (with updated assertions)
- New tests pass: outflow, mixed flow, zero-denom, CASH_RECEIPT date
