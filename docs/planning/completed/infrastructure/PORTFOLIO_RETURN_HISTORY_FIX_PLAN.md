# Fix Short Portfolio Return History in Performance Pipeline

**Date**: 2026-02-28
**Status**: COMPLETE — Implemented and verified in Chrome 2026-03-01. Performance metrics now use full return history via partial-data reweighting.

## Context

During P2b factor attribution testing, we discovered that `port_ret` (portfolio returns) only spans 11 months (2025-03 to 2026-01) despite the portfolio having a 7-year date range (2019-01-31 to 2026-01-29). This truncated history caused factor attribution to fail initially (below the 12-month min observation threshold) and means all performance metrics (Sharpe, drawdown, alpha/beta, etc.) are computed on an artificially short window.

**Root cause**: `compute_portfolio_returns()` in `portfolio_risk.py` line 112 does:
```python
aligned = returns[list(w.keys())].dropna()
```

This `dropna()` drops ANY row where ANY ticker has NaN, truncating the entire portfolio return series to the **shortest common overlap** across all tickers. If one ticker IPO'd in early 2025, all 7 years of data for other tickers is thrown away.

**Impact**: Performance metrics (annualized return, volatility, Sharpe, drawdown, alpha/beta) are all computed on ~11 months instead of the full available history. This makes them statistically unreliable and misleading.

---

## Investigation Findings

### Call chain
1. `app.py:1495` → `portfolio_service.analyze_performance(portfolio_data, benchmark_ticker)`
2. `portfolio_service.py:565` → `run_portfolio_performance(temp_portfolio_file, ...)` — temp file includes `start_date`/`end_date` from `PortfolioData`
3. `run_risk.py:838` → `analyze_performance(filepath, benchmark_ticker)`
4. `performance_analysis.py:84` → `load_portfolio_config(filepath)` — reads dates from YAML correctly
5. `performance_analysis.py:113` → `calculate_portfolio_performance_metrics(weights, start_date, end_date, ...)`
6. `portfolio_risk.py:1694` → `get_returns_dataframe(filtered_weights, start_date, end_date, ...)` — fetches per-ticker returns with correct dates
7. `portfolio_risk.py:1703` → `compute_portfolio_returns(df_ret, filtered_weights)` — **`dropna()` truncates here**

### Key finding
- Dates ARE correctly threaded through the entire pipeline (temp YAML file has them, FMP API called with them)
- The truncation happens at `compute_portfolio_returns()` line 112 where `dropna()` drops all rows with ANY missing ticker
- This is a legitimate data alignment issue, not a bug per se — but the current approach is too aggressive for portfolios with mixed-vintage stocks

### Where `compute_portfolio_returns` is called
This function is used throughout the codebase (risk pipeline too), so changes must be backward-compatible.

---

## Codex Review (FAIL — 2026-02-28)

Codex confirmed root cause and pipeline separation are correct, but flagged issues with the implementation:

1. **Short/negative weight handling** — pure-short months get dropped (`weight_sum <= 0`), and long/short near-cancel months can create extreme effective leverage
2. **Statistical caveats** — time-varying composition changes interpretation of Sharpe/alpha/beta; metrics should be labeled as "partial data"
3. **Missing edge cases** — need minimum weight coverage threshold, short-only month handling, near-cancel guards
4. **Confirmed correct**: NOT modifying `compute_portfolio_returns()` — risk pipeline uses it at lines 1521-1524 for covariance/correlation

---

## Implementation Plan

### Step 1: Add partial-data portfolio return computation

**File**: `portfolio_risk_engine/portfolio_risk.py`

Add a new function `compute_portfolio_returns_partial()` that handles NaN tickers by reweighting:

```python
MIN_WEIGHT_COVERAGE = 0.5  # require at least 50% of portfolio weight to be available

def compute_portfolio_returns_partial(
    returns: pd.DataFrame,
    weights: Dict[str, float],
    min_weight_coverage: float = MIN_WEIGHT_COVERAGE,
) -> pd.Series:
    """Compute weighted portfolio returns, reweighting around missing tickers per month.

    Unlike compute_portfolio_returns() which drops any month with ANY missing ticker,
    this function rebalances weights for each month based on available tickers.

    Guards:
    - Months with < min_weight_coverage of total absolute weight are dropped
    - Uses absolute weight for coverage check (handles long/short portfolios)
    - Gross-exposure scaling preserves weight signs (no inversion for short positions)
    - Months requiring >5x gross scaling are skipped to prevent leverage blowups
    - When all tickers present, gross_scale = 1.0 → identical to compute_portfolio_returns()
    """
    w = normalize_weights(weights)
    tickers = list(w.keys())
    aligned = returns[tickers]
    base_weights = np.array([w[t] for t in tickers])
    total_abs_weight = np.abs(base_weights).sum()

    result = []
    skipped_coverage = 0
    skipped_cancel = 0
    for idx, row in aligned.iterrows():
        mask = ~row.isna()
        if not mask.any():
            continue  # skip months with zero data

        available_weights = base_weights[mask.values]

        # Coverage check: require sufficient absolute weight representation
        available_abs = np.abs(available_weights).sum()
        if total_abs_weight > 0 and (available_abs / total_abs_weight) < min_weight_coverage:
            skipped_coverage += 1
            continue  # insufficient representation

        # Scale up remaining weights to maintain original gross exposure level.
        # Multiply each available weight by (total_abs / available_abs).
        # This preserves sign (short weights stay negative) and scales proportionally.
        # Example: portfolio {A: 0.6, B: -0.4}, B missing → A scaled to 0.6 * (1.0/0.6) = 1.0
        # Example: long-only {A: 0.6, B: 0.4}, B missing → A scaled to 0.6 * (1.0/0.6) = 1.0
        if available_abs < 1e-10:
            skipped_cancel += 1
            continue

        gross_scale = total_abs_weight / available_abs
        # Guard against extreme leverage from gross scaling
        if gross_scale > 5.0:
            skipped_cancel += 1
            continue  # would create >5x effective leverage
        scaled_weights = available_weights * gross_scale
        month_return = row[mask].values.dot(scaled_weights)
        result.append((idx, month_return))

    if skipped_coverage or skipped_cancel:
        from portfolio_risk_engine._logging import portfolio_logger
        portfolio_logger.info(
            "compute_portfolio_returns_partial: %d months skipped (coverage < %.0f%%: %d, "
            "near-cancel: %d), %d months included",
            skipped_coverage + skipped_cancel, min_weight_coverage * 100,
            skipped_coverage, skipped_cancel, len(result),
        )

    if not result:
        return pd.Series(dtype=float, name="portfolio")

    dates, vals = zip(*result)
    return pd.Series(vals, index=pd.DatetimeIndex(dates), name="portfolio")
```

### Step 2: Use partial returns in performance pipeline only

**File**: `portfolio_risk_engine/portfolio_risk.py`

In `calculate_portfolio_performance_metrics()` at line ~1703, replace:
```python
portfolio_returns = compute_portfolio_returns(df_ret, filtered_weights)
```
with:
```python
portfolio_returns = compute_portfolio_returns_partial(df_ret, filtered_weights)
```

**Do NOT change** `compute_portfolio_returns()` itself or its callers in the risk pipeline (`build_portfolio_view`). Risk calculations (covariance matrix, VaR, etc.) legitimately need aligned time series. Risk pipeline callers confirmed at lines 1521-1524.

### Step 3: Add data quality note when partial data is used

In `calculate_portfolio_performance_metrics()`, after computing `portfolio_returns`, add a warning if partial data was used:

Place this **after** `combined_warnings` is initialized (line ~1751), not in the `warnings` list (which is ticker-exclusion-specific):

```python
# Check if partial data extended the return history
full_returns = compute_portfolio_returns(df_ret, filtered_weights)
if len(portfolio_returns) > len(full_returns):
    months_gained = len(portfolio_returns) - len(full_returns)
    combined_warnings.append(
        f"Extended return history by {months_gained} months using partial ticker data. "
        f"Months where not all tickers had data use reweighted available-ticker exposures — "
        f"performance metrics (Sharpe, drawdown, alpha/beta) reflect time-varying effective "
        f"weights, not the original static allocation."
    )
```

This ensures the warning is always included in the final `performance_metrics["warnings"]` regardless of whether any tickers were excluded.

---

## Files Modified

| File | Action |
|------|--------|
| `portfolio_risk_engine/portfolio_risk.py` | **Edit** — add `compute_portfolio_returns_partial()`, use it in `calculate_portfolio_performance_metrics()` |

No new files. Single-file change.

---

## Key Design Decisions

1. **New function, not modifying existing**: `compute_portfolio_returns()` is used in the risk pipeline (`build_portfolio_view` at line ~1494) where the returned portfolio series must be aligned with the `df_ret` DataFrame used for covariance/correlation (computed directly from `df_ret`). Changing the base function's `dropna()` behavior could introduce index misalignment between the portfolio series and the covariance matrix. A separate `compute_portfolio_returns_partial()` is safer.

2. **Performance pipeline only**: Risk calculations need complete aligned data. Performance metrics (returns, Sharpe, drawdown) work fine with reweighted partial data — this is standard practice in portfolio analytics.

3. **Per-month reweighting**: For each month, normalize weights to only available tickers. This means months early in the history may have slightly different effective weights, which is transparent and honest.

4. **Minimum weight coverage threshold (50%)**: A month is only included if at least 50% of total absolute portfolio weight is represented. Prevents unreliable returns from months with only marginal positions available. Uses absolute weight so long/short portfolios are handled correctly.

5. **Leverage guard**: Months where gross scaling would exceed 5x (i.e., available absolute weight < 20% of total) are skipped to prevent extreme effective leverage. This is a stricter practical guard than the 50% coverage threshold — it catches cases where a few small positions represent the month.

6. **Labeling**: When partial data extends the return history, a warning is added to `performance_metrics["warnings"]` so the frontend/consumer knows the history was extended with reweighted data.

---

## Verification

1. **Before/after comparison**: Run `calculate_portfolio_performance_metrics()` on a portfolio with mixed-vintage stocks, compare `len(port_ret)` before and after the change
2. **Sanity check**: Verify annualized return and Sharpe ratio are reasonable with the longer history
3. **Risk pipeline unaffected**: Verify `build_portfolio_view()` still uses `compute_portfolio_returns()` (no change)
4. **Factor attribution**: Verify factor attribution now has more data points and better regression quality
5. **Chrome visual test**: Reload Performance view, verify analysis period shows the full date range
6. **Edge cases to test**:
   - Portfolio where all tickers have full history → behavior identical to before
   - All-NaN month → skipped
   - Single available ticker month → included if weight coverage ≥ 50%
   - Short-only month → handled correctly (absolute weight coverage)
   - Long/short near-cancel month → skipped (leverage guard > 5x)
   - Short-only portfolio, one short missing → remaining shorts scaled up, signs preserved
