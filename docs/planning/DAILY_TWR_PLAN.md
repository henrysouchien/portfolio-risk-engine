# Daily TWR for Realized Performance

## Context

Our realized performance engine uses **Monthly Modified Dietz** returns — one return per calendar month. This approximates TWR but breaks down when large external flows arrive near month boundaries. Example: account 252 had a $65K deposit on Jan 31 into a $139 account. The deposit gets near-zero Dietz time-weight, producing a -3.94% January return that drags full-year TWR from ~10% down to 5.57% (broker reports +10.65% using daily TWR).

The fix: switch to daily price/NAV granularity and true sub-period TWR, which is the industry standard for performance reporting. FMP already returns daily prices — we currently resample to monthly and throw them away.

## Approach: Daily NAV + Sub-Period TWR, Aggregated to Monthly

1. Fetch daily close prices (stop resampling to monthly)
2. Compute NAV at daily granularity
3. At each external flow date, compute a sub-period return using true TWR formula
4. Chain sub-period returns within each calendar month to produce monthly TWR
5. Monthly returns feed into `compute_performance_metrics` unchanged (same shape, same frequency)

**Why aggregate to monthly?** The performance metrics engine (Sharpe, Sortino, CAPM) expects monthly frequency for meaningful annualization. Daily returns would need `sqrt(252)` and 252+ observations for CAPM — more fragile. Daily NAV gives accurate TWR; monthly aggregation gives stable risk metrics.

## Files to Modify

| File | Change |
|------|--------|
| `fmp/compat.py` | Add `fetch_daily_close()` (same FMP call, skip resample) |
| `fmp/fx.py` | Add `get_daily_fx_series()` (daily FX rates) |
| `providers/interfaces.py` | Add `fetch_daily_close()` to `PriceSeriesProvider` protocol |
| `providers/fmp_price.py` | Implement `fetch_daily_close()` on `FMPProvider` |
| `core/realized_performance_analysis.py` | Daily price/FX cache, daily NAV, sub-period TWR |

**No changes to:** `performance_metrics_engine.py`, result objects, frontend, API shape.

## Implementation

### Change 1: Daily price fetching (`fmp/compat.py`)

Add `fetch_daily_close()` that returns raw daily series **without** `resample("ME")["close"].last()`. Reuse same FMP endpoint and caching pattern as `fetch_monthly_close()`.

```python
@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def _fetch_daily_close_cached(ticker, fmp_symbol, start_date, end_date):
    # Same FMP API call as _fetch_monthly_close_cached
    # Same error handling, plan-blocked check, minor currency normalization
    # Skip: resample("ME")["close"].last()
    # Return: pd.Series(index=daily_dates, values=close_prices)

def fetch_daily_close(ticker, start_date=None, end_date=None, *, fmp_ticker=None, fmp_ticker_map=None):
    # Same signature pattern as fetch_monthly_close
```

### Change 2: Daily FX series (`fmp/fx.py`)

Add `get_daily_fx_series()` — same logic as `get_monthly_fx_series()` but calls `fetch_daily_close()`.

```python
def get_daily_fx_series(currency, start_date, end_date):
    """Return daily FX series (currency -> USD)."""
    # Same as get_monthly_fx_series but uses fetch_daily_close
```

### Change 3: Provider protocol + FMPProvider (`providers/interfaces.py`, `providers/fmp_price.py`)

Add `fetch_daily_close()` to `PriceSeriesProvider` protocol with default fallback to monthly:

```python
# interfaces.py
def fetch_daily_close(self, symbol, start_date, end_date, **kw) -> pd.Series:
    return self.fetch_monthly_close(symbol, start_date, end_date, **kw)

# fmp_price.py
def fetch_daily_close(self, symbol, start_date, end_date, **kw):
    return fetch_daily_close(symbol, start_date, end_date, fmp_ticker_map=kw.get("fmp_ticker_map"))
```

IBKR provider returns monthly by default — `_value_at_or_before()` still finds nearest prior price. No IBKR changes needed. **Note:** IBKR symbols priced from monthly data will have stale prices between month-ends (same value repeated for ~20 business days). This is acceptable — it matches current behavior and doesn't introduce new error. Daily TWR still improves flow-timing accuracy even with monthly price resolution.

### Change 4: Realized performance engine (`core/realized_performance_analysis.py`)

#### 4a: Switch price cache to daily

In `_fetch_price_from_chain()` (line 295), call `provider.fetch_daily_close()` instead of `provider.fetch_monthly_close()`. The `_value_at_or_before()` lookup (line 172) is already date-agnostic — with daily series it finds the nearest prior daily close instead of monthly close.

#### 4b: Switch FX cache to daily

In `_build_fx_cache()` (line 829), call `get_daily_fx_series()` instead of `get_monthly_fx_series()`. The `_event_fx_rate()` lookup uses `_value_at_or_before` — already date-agnostic.

#### 4c: Daily NAV computation

`compute_monthly_nav()` (line 1787) is already date-agnostic — it iterates over a date list and accumulates positions/cash. Generalize it:

- Rename `month_ends` parameter to `eval_dates` (or add a wrapper)
- Add `_business_day_range(start, end)` helper using `pd.bdate_range()`
- Compute daily NAV: `compute_monthly_nav(position_timeline, business_days, price_cache, fx_cache, cash_snapshots)`

#### 4d: Sub-period TWR computation

New function `compute_twr_monthly_returns()`:

```python
def compute_twr_monthly_returns(
    daily_nav: pd.Series,                        # NAV at each business day
    external_flows: List[Tuple[datetime, float]], # (date, amount) pairs
    month_ends: List[datetime],                   # for monthly aggregation
) -> Tuple[pd.Series, List[str]]:
    """True time-weighted monthly returns via daily sub-periods.

    Algorithm:
    1. Aggregate same-day flows: {date: sum(amounts)}
    2. Walk the daily NAV series day by day
    3. On non-flow days: no action (NAV tracks position value changes)
    4. On flow days: end the current sub-period, start a new one
       - pre_flow_nav = daily_nav[D] - sum(external flows on D)
       - Sub-period return = pre_flow_nav / sub_period_start_nav - 1
       - New sub-period start = daily_nav[D] (post-flow, since cash replay already applied the flow)
    5. At month-end: close the active sub-period
    6. Monthly TWR = product of (1 + R_sub) for all sub-periods in month - 1
    7. Return monthly return series
    """
```

**Pre-flow vs post-flow NAV (critical detail):**

Cash replay (`derive_cash_and_external_flows`, line 1648-1718) processes events chronologically and records `cash_snapshots` **after** each event. So when `compute_monthly_nav` evaluates at a flow date, the resulting daily NAV **includes** the flow's cash impact (post-flow NAV).

To get pre-flow NAV on flow day D:
- `pre_flow_nav = daily_nav[D] - sum(flows on day D)`
- This works because `daily_nav[D]` = positions_value(D) + cash_after_all_events(D)
- Subtracting the day's external flows gives positions_value(D) + cash_before_external_flows(D)

Then:
- Sub-period return = `pre_flow_nav / sub_period_start_nav - 1`
- Next sub-period start = `pre_flow_nav + sum(flows on day D)` = `daily_nav[D]`

**Edge cases:**

| Case | Handling |
|------|----------|
| Multiple flows same day | Aggregate into single net flow per day |
| Flow on inception day (V_start=0) | `R = (daily_nav[D] - flow) / flow` if flow > 0, else 0 |
| Weekend/holiday flows | Snap to next business day in daily_nav index (flows between bdays attributed to next bday) |
| Flow before first price | Use first available NAV; sub-period return = 0 for gap |
| Flow after last price | Use last available NAV (carry-forward) |
| Zero/negative denominator | Return 0 with warning (same as current Modified Dietz edge case) |

#### 4e: Wire into pipeline

In `_analyze_realized_performance_single_scope()`:

1. Build daily date list: `eval_dates = _business_day_range(inception_date, end_date)`
2. Compute daily NAV using existing `compute_monthly_nav` with daily dates
3. Compute TWR monthly returns: `compute_twr_monthly_returns(daily_nav, external_flows, month_ends)`
4. Keep existing `month_ends` for monthly NAV metadata (display, result object)
5. Monthly returns feed into `compute_performance_metrics` unchanged

Same for observed-only NAV track (both synthetic-enhanced and observed tracks get daily TWR).

### Account aggregation path

The aggregation path (`_sum_account_monthly_series` + `_build_aggregated_result`) must also use daily TWR for consistency. Changes:

1. Each per-account run now stores daily NAV + external flows in `realized_metadata._postfilter` (alongside existing monthly series)
2. `_sum_account_monthly_series` → `_sum_account_daily_series`: sum daily NAVs across accounts (same `reindex + ffill + sum` pattern, just daily index instead of monthly)
3. `_build_aggregated_result`: call `compute_twr_monthly_returns` on the combined daily NAV + combined external flows
4. Inception deferral (`min_inception_nav`) still applies — skip daily NAV points before the account crosses the threshold

This ensures the combined multi-account return uses the same daily TWR methodology as per-account runs. Without this, the aggregation path reintroduces Monthly Modified Dietz distortion on the combined series.

## Key Existing Functions (reusable as-is)

- `_value_at_or_before(series, when, default)` (line 172): Already date-agnostic — works with daily series
- `_event_fx_rate(currency, when, fx_cache)` (line 821): Uses `_value_at_or_before` — date-agnostic
- `compute_monthly_nav()` (line 1787): Loop is date-agnostic — just change the date list input
- `compute_performance_metrics()` (`performance_metrics_engine.py`): Unchanged — still receives monthly returns
- `_normalize_monthly_index()` (line 475): Still needed for aligning monthly outputs

## Performance Considerations

- Daily prices: ~20x more data points than monthly (252/year vs 12/year)
- Daily NAV loop: ~500 iterations for 2-year period vs 24 — still trivially fast
- FMP API: identical call (same endpoint), no extra requests — just skip resample
- LRU cache on `_fetch_daily_close_cached` prevents redundant fetches
- Memory: ~5KB per ticker for 2 years of daily data — negligible

## Verification

```bash
# 1. Existing tests must pass
python3 -m pytest tests/ -x -q -k "realized" 2>&1 | tail -20

# 2. Account 252: should improve from +5.57% toward broker +10.65%
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='charles_schwab', account='25524252', format='agent', use_cache=False)
print(f'Account 252: {r[\"snapshot\"][\"returns\"][\"total_return_pct\"]}%')
"

# 3. Account 165: must stay near broker -8.29%
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='charles_schwab', account='87656165', format='agent', use_cache=False)
print(f'Account 165: {r[\"snapshot\"][\"returns\"][\"total_return_pct\"]}%')
"

# 4. IBKR: must stay unchanged (-71.66%)
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='interactive_brokers', format='agent', use_cache=False)
print(f'IBKR: {r[\"snapshot\"][\"returns\"][\"total_return_pct\"]}%')
"

# 5. Schwab combined
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='charles_schwab', format='agent', use_cache=False)
print(f'Combined: {r[\"snapshot\"][\"returns\"][\"total_return_pct\"]}%')
"
```

## Acceptance Gates

- Account 252 2025: closer to broker +10.65% (currently +5.57%)
- Account 165: unchanged (~-7.97%, ±0.5pp acceptable)
- IBKR: unchanged (-71.66%)
- All existing tests pass
- No extra FMP API calls
