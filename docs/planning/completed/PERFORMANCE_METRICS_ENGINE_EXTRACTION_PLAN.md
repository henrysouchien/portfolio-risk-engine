# Performance Metrics Engine Extraction Plan

**Status:** COMPLETE
**Prerequisite for:** `REALIZED_PERFORMANCE_MCP_PLAN.md`
**Implements:** `PERFORMANCE_METRICS_ENGINE_PREIMPLEMENTATION_PLAN.md`

---

## Context

Before adding `get_realized_performance` (which computes actual performance from transaction history), we need to extract the pure metric math out of `portfolio_risk.calculate_portfolio_performance_metrics()` into a reusable engine. Currently that function mixes I/O (FMP data fetching, benchmark alignment, treasury rates) with pure math (returns, volatility, Sharpe, drawdown, CAPM). This refactor isolates the math so both hypothetical and realized pipelines can share it, with strict parity guarantees.

---

## File Changes

| File | Action | What |
|------|--------|------|
| `core/performance_metrics_engine.py` | **CREATE** | Pure function `compute_performance_metrics()` |
| `portfolio_risk.py` | **MODIFY** | Replace math block (lines ~1395-1522) with engine call |
| `tests/core/test_performance_metrics_engine.py` | **CREATE** | Characterization tests + engine unit tests |

No changes to `core/performance_analysis.py`, `services/portfolio_service.py`, `mcp_tools/performance.py`, or `core/result_objects.py` — the adapter output dict is identical so all downstream consumers are unaffected.

---

## Engine Function Signature

```python
# core/performance_metrics_engine.py

def compute_performance_metrics(
    portfolio_returns: pd.Series,     # aligned monthly returns (no NaN)
    benchmark_returns: pd.Series,     # aligned monthly returns (same index)
    risk_free_rate: float,            # annual decimal (e.g. 0.04)
    benchmark_ticker: str,            # label for output dict
    start_date: str,                  # ISO date for metadata
    end_date: str,                    # ISO date for metadata
    min_capm_observations: int = 24,  # CAPM regression minimum
) -> Dict[str, Any]:
```

**Imports**: Only `pandas`, `numpy`, `statsmodels.api` — no FMP, no data_loader, no settings.

**Input preconditions** (enforced with ValueError):
- `portfolio_returns` and `benchmark_returns` must have the same length and index
- Neither series may contain NaN values
- Index must be DatetimeIndex (engine uses `.date().isoformat()` for monthly_returns keys)

**Unit convention for `risk_free_rate`**: Input is annual decimal (e.g. `0.04` for 4%). Engine converts to monthly (`/ 12`) internally. Output `risk_free_rate` key is percentage (`round(val * 100, 2)` → `4.0`).

**Output**: Same nested dict structure as current lines 1471-1522 with identical keys and rounding:

```python
{
    "analysis_period": {"start_date", "end_date", "total_months", "years"},
    "returns": {"total_return", "annualized_return", "best_month", "worst_month",
                "positive_months", "negative_months", "win_rate"},
    "risk_metrics": {"volatility", "maximum_drawdown", "downside_deviation", "tracking_error"},
    "risk_adjusted_returns": {"sharpe_ratio", "sortino_ratio", "information_ratio", "calmar_ratio"},
    "benchmark_analysis": {"benchmark_ticker", "alpha_annual", "beta", "r_squared", "excess_return"},
    "benchmark_comparison": {"portfolio_return", "benchmark_return", "portfolio_volatility",
                             "benchmark_volatility", "portfolio_sharpe", "benchmark_sharpe"},
    "monthly_stats": {"average_monthly_return", "average_win", "average_loss", "win_loss_ratio"},
    "risk_free_rate": float,
    "monthly_returns": {date_iso: float}
}
```

**Rounding conventions** (preserved exactly):
- Percentages: `round(val * 100, 2)`
- Win rate: `round(val * 100, 1)`
- Ratios (sharpe, sortino, info, calmar, beta, r²): `round(val, 3)`
- Monthly returns: `.round(4)`
- Years: `round(val, 2)`
- Win/loss ratio: `round(val, 2)`

---

## Adapter Changes (portfolio_risk.py)

`calculate_portfolio_performance_metrics()` keeps all I/O:
- `_filter_tickers_by_data_availability()` — ticker filtering
- `get_returns_dataframe()` — FMP price fetching
- `compute_portfolio_returns()` — weighted sum
- `fetch_monthly_close()` — benchmark prices
- `calc_monthly_returns()` — benchmark returns
- `pd.DataFrame(...).dropna()` — alignment
- `fetch_monthly_treasury_rates()` — risk-free rate
- All early-return error dicts
- `excluded_tickers`, `warnings`, `analysis_notes` post-processing
- `calculate_portfolio_dividend_yield()` — dividend metrics

The math block (lines ~1395-1522) gets replaced with:
```python
from core.performance_metrics_engine import compute_performance_metrics
performance_metrics = compute_performance_metrics(
    portfolio_returns=port_ret,
    benchmark_returns=bench_ret,
    risk_free_rate=risk_free_rate,
    benchmark_ticker=benchmark_ticker,
    start_date=start_date,
    end_date=end_date,
    min_capm_observations=DATA_QUALITY_THRESHOLDS["min_observations_for_capm_regression"],
)
```

---

## Implementation Sequence

### Step 1: Characterization Tests (Lock Current Behavior)
Write `tests/core/test_performance_metrics_engine.py` with deterministic fixtures (seeded `np.random` Series). Mock all I/O in `calculate_portfolio_performance_metrics` to inject known data. Snapshot the exact output dict — every key, every value.

**Math test cases:**
- Normal case (36 months, standard data)
- Insufficient CAPM observations (fallback: alpha=0, beta=1, r²=0)
- CAPM regression exception (e.g. singular matrix — same fallback: alpha=0, beta=1, r²=0)
- Zero volatility (all ratios → 0)
- All negative months (win_rate=0)
- Rounding verification (2dp percentages, 1dp win_rate, 3dp ratios, 4dp monthly returns)
- Input precondition violations (mismatched length, NaN, non-DatetimeIndex → ValueError)

**Adapter test cases** (post-engine, adapter-owned behavior):
- `excluded_tickers` / `warnings` / `analysis_notes` present when tickers filtered
- `dividend_metrics` success path structure
- `dividend_metrics` exception fallback structure
- Error dicts for: all tickers excluded, insufficient data after filtering, benchmark fetch failure, no overlap

**Gate:** Tests pass before any code changes.

### Step 2: Create Engine
Create `core/performance_metrics_engine.py` — direct lift of lines 1395-1522 with variable renames (`port_ret` → `portfolio_returns`, etc.). Add engine-only unit tests that call `compute_performance_metrics()` directly with the same fixtures. Verify output matches characterization snapshots.

**Gate:** Engine unit tests pass.

### Step 3: Wire Adapter
Modify `portfolio_risk.py` — replace math block with engine call. Add import. Run characterization tests.

**Gate:** Identical output to Step 1 snapshots.

### Step 4: Regression Pass
Run end-to-end paths to confirm no observable change:
```bash
python3 tests/utils/show_api_output.py performance
python3 tests/utils/show_api_output.py direct/performance
```

---

## Verification

1. **Characterization tests**: deterministic fixtures → exact output match before and after
2. **Engine unit tests**: edge cases (zero vol, insufficient CAPM, no wins) all produce expected fallback values
3. **End-to-end**: `show_api_output.py performance` produces same structure and formatting
4. **MCP**: `get_performance` with summary/full/report formats unchanged

---

## Compatibility Contract

For all `get_performance` paths:
1. Field names unchanged
2. Units unchanged (% fields remain percent values, not decimals)
3. Rounding unchanged
4. Data quality thresholds unchanged
5. Error messages/keys unchanged
6. Benchmark alignment behavior unchanged
7. Risk-free fallback behavior unchanged

---

## Call Chain (unchanged)

```
mcp_tools/performance.py:get_performance()
  → PortfolioService.analyze_performance()
    → run_risk.py:run_portfolio_performance()
      → core/performance_analysis.py:analyze_performance()
        → portfolio_risk.py:calculate_portfolio_performance_metrics()  [adapter - I/O]
          → core/performance_metrics_engine.py:compute_performance_metrics()  [NEW - pure math]
```
