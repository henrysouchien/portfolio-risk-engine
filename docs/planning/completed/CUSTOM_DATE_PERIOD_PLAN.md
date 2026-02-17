# Custom Date Period for Performance Analysis

**Status:** COMPLETE

## Context

`get_performance()` currently has no date parameters — hypothetical mode uses portfolio YAML defaults (typically 5yr lookback), and realized mode always runs from inception (earliest transaction) to now. The user wants to be able to specify a custom time period for both modes (e.g. "how did I do in 2024?" or "last 12 months").

## Approach

**Hypothetical mode**: Passthrough — thread `start_date`/`end_date` into `PortfolioData`. The downstream pipeline (`get_returns_dataframe()` → `compute_performance_metrics()`) already supports date params at every layer. No new logic needed.

**Realized mode**: Post-filter — run the full pipeline (inception to now) unchanged, then slice the monthly returns series to the requested window and recompute metrics from the subset. This is correct because Modified Dietz monthly returns are self-contained — each month's return is independent.

**Why post-filter, not bounded recompute**: Overriding `inception_date`/`end_date` before pipeline execution would change FX cache construction, NAV state, and synthetic position placement. Pre-window events would use wrong FX fallbacks, and opening NAV state would be incorrect. Post-filter avoids all of this — the full pipeline runs exactly as it does today, and we only filter the output.

---

## Changes

### 1. MCP tool signature — `mcp_tools/performance.py`

Add two optional params to `get_performance()`:

```python
def get_performance(
    ...
    start_date: Optional[str] = None,   # NEW — YYYY-MM-DD
    end_date: Optional[str] = None,     # NEW — YYYY-MM-DD
) -> dict:
```

**Input validation** (before any pipeline call):
- Parse both dates with `pd.Timestamp()`, return error on invalid format
- If both provided, enforce `start_date <= end_date`
- Normalize to ISO format (`YYYY-MM-DD`) for consistent downstream handling

Update docstring with examples:
- `"How did I do in 2024?" -> get_performance(start_date="2024-01-01", end_date="2024-12-31")`
- `"Last 12 months?" -> get_performance(start_date="2025-02-01")`

### 2. Hypothetical mode path — `mcp_tools/performance.py`

Add `start_date`/`end_date` params to `_load_portfolio_for_performance()`:

```python
def _load_portfolio_for_performance(user_email, portfolio_name, use_cache=True,
                                     start_date=None, end_date=None):
    ...
    portfolio_data = position_result.data.to_portfolio_data(
        portfolio_name=portfolio_name,
        start_date=start_date,
        end_date=end_date,
    )
```

`to_portfolio_data()` already accepts `start_date`/`end_date` (`position_service.py:423`). When `None`, it falls back to `PORTFOLIO_DEFAULTS` — existing behavior preserved.

The rest of the hypothetical pipeline (`PortfolioService.analyze_performance()` → temp file → `run_portfolio_performance()`) already uses whatever dates are in `PortfolioData`. No deeper changes needed.

### 3. Expose post-filter data from realized pipeline — `core/realized_performance_analysis.py`

The post-filter needs data that's currently computed internally but not returned. Add these to `realized_metadata` (always, not gated by `include_series`):

```python
# In realized_metadata dict (~line 1806):
"_postfilter": {
    "portfolio_monthly_returns": {
        ts.date().isoformat(): float(v)
        for ts, v in aligned["portfolio"].to_dict().items()
    },
    "benchmark_monthly_returns": {
        ts.date().isoformat(): float(v)
        for ts, v in aligned["benchmark"].to_dict().items()
    },
    "monthly_nav": {
        ts.date().isoformat(): float(val)
        for ts, val in monthly_nav.items()
    },
    "net_flows": {
        ts.date().isoformat(): float(val)
        for ts, val in net_flows.items()
    },
    "risk_free_rate": float(risk_free_rate),  # raw decimal (e.g. 0.047)
    "benchmark_ticker": benchmark_ticker,
},
```

**Precision**: Values are stored as raw floats (no rounding) to preserve accuracy for recomputation. Rounding happens only in user-facing output fields.

**Why a `_postfilter` sub-dict**: Keeps internal plumbing data separate from user-facing fields. The leading underscore signals it's implementation detail. The MCP layer reads it for recomputation then strips it unconditionally before any output path (summary, full, or report).

**Note**: `monthly_nav` was already conditionally included under `include_series`. Keep that existing behavior for the user-facing `monthly_nav` key (rounded). The `_postfilter` copy is always present with full precision for internal use.

### 4. Realized mode post-filter — `mcp_tools/performance.py`

After getting the full realized result, apply date filtering then strip internal data:

```python
# Check for pipeline error before windowing
if realized_result.get("status") == "error":
    return { "status": "error", "error": realized_result.get("message", "...") }

if start_date or end_date:
    realized_result = _apply_date_window(realized_result, start_date, end_date)
    # _apply_date_window returns error dict on failure — check again
    if realized_result.get("status") == "error":
        return realized_result

# Strip _postfilter unconditionally (before any format branch)
realized_result.get("realized_metadata", {}).pop("_postfilter", None)
```

New helper `_apply_date_window(result, start_date, end_date)`:

1. Extract `monthly_returns` dict from result (keyed by `YYYY-MM-DD` strings)
2. Convert to `pd.Series` with `DatetimeIndex`
3. **Snap dates to month-ends**:
    - `start_date`: If it falls on the 1st of a month, include that month (first month-end = end of that month). Otherwise, skip to the next full month (first month-end = end of the following month). Examples: `start_date=2024-01-01` → includes Jan (first month-end = `2024-01-31`). `start_date=2024-01-15` → excludes Jan, first included is Feb (first month-end = `2024-02-29`). This ensures only full months are included.
    - `end_date` → last month-end <= end_date.
4. Slice to `[snapped_start, snapped_end]` window
5. If sliced series is empty → return error dict: `{"status": "error", "error": "No data available for the requested period (available: {first} to {last})"}`
6. If 1 month only → skip `compute_performance_metrics()` and build a result with the **same dict structure** as normal output but with null/zero risk metrics. Specifically:
    - `returns`: populate `total_return`, `best_month`, `worst_month` from the single month. **Unit convention**: match `compute_performance_metrics()` output — all return fields in percent-points (e.g. raw `0.023` → `2.30`), rounded to 2dp. Set `annualized_return` to `None` (meaningless for 1 month), `positive_months`/`negative_months`/`win_rate` from the single value
    - `risk_metrics`: all `None` (`volatility`, `maximum_drawdown`, `downside_deviation`, `tracking_error`)
    - `risk_adjusted_returns`: all `None` (`sharpe_ratio`, `sortino_ratio`, `information_ratio`, `calmar_ratio`)
    - `benchmark_analysis`: `alpha_annual`/`beta`/`r_squared` = `None`; `benchmark_ticker` preserved; `excess_return` = `(portfolio_return - benchmark_return) * 100` (percent-points, matching existing convention)
    - `benchmark_comparison`: populate total returns for both; set vol/Sharpe to `None`
    - `monthly_stats`: populate from single month; `win_loss_ratio` = `None`
    - `analysis_period`: `total_months` = 1, `years` = 0.08
    - This preserves the dict schema so all formatters (summary at line 355, report at line 141) can safely access keys without KeyError. Null-valued fields are displayed as "N/A" in report format.
7. If 2 months → add warning to `realized_metadata.data_warnings`: "Custom window has only 2 months; risk metrics have limited statistical significance"
8. Extract matching benchmark returns from `_postfilter.benchmark_monthly_returns` (same date slice)
9. **Window-specific risk-free rate**: Call `_safe_treasury_rate(snapped_start, snapped_end)` for the window. Import this from the core module. This ensures Sharpe/Sortino use period-appropriate rates.
10. Use raw portfolio returns from `_postfilter.portfolio_monthly_returns` (not the rounded `monthly_returns` dict) to preserve full precision for recomputation.
11. Call `compute_performance_metrics()` with sliced raw portfolio + benchmark returns → new metrics
12. **Recalculate `official_pnl_usd`** for the window:
    - Get `monthly_nav` series from `_postfilter.monthly_nav`
    - Get `net_flows` series from `_postfilter.net_flows`
    - **NAV boundary**: `nav_start` = NAV at the month-end **before** `snapped_start` (the opening balance before the first return month). Look up the prior month in the `monthly_nav` series. If `snapped_start` is the first month in the series (no prior month available), set `official_pnl_usd = None` and add warning: "Cannot determine opening NAV for custom window starting at portfolio inception; official P&L unavailable for this window." Do NOT attempt to back-derive NAV from returns — Modified Dietz returns are flow-adjusted, so `NAV / (1 + r)` does not recover the opening NAV when external flows exist.
    - `nav_end = monthly_nav[snapped_end]`
    - `window_net_flows = sum(net_flows[snapped_start : snapped_end])` (inclusive of both endpoints)
    - `official_pnl_usd = nav_end - nav_start - window_net_flows`
13. Replace in result: `analysis_period`, `returns`, `risk_metrics`, `risk_adjusted_returns`, `benchmark_analysis`, `benchmark_comparison`, `monthly_stats`, `monthly_returns`, `risk_free_rate`
14. Update `realized_metadata.official_pnl_usd` with windowed value
15. **Set `reconciliation_gap_usd` to `None`** in windowed output — comparing windowed official P&L vs all-time lot P&L is not a valid reconciliation. Add explanatory note in `custom_window`.
16. Keep lot-based fields unchanged: `realized_pnl`, `unrealized_pnl`, `income` (all-time FIFO, clearly labeled)
17. Add `"custom_window"` to result:
    ```python
    "custom_window": {
        "start_date": snapped_start_iso,
        "end_date": snapped_end_iso,
        "full_inception": original_inception_date,
        "note": "Return/risk metrics and official P&L are for the custom window. "
                "Lot-based P&L (realized/unrealized/income) reflects all-time FIFO. "
                "Reconciliation gap is not applicable for custom windows."
    }
    ```
18. Update both top-level aliases AND nested `realized_metadata` fields for consistency (summary mode reads nested metadata at `mcp_tools/performance.py:360`)

**Edge cases**:
- `start_date` after all available months → error dict with available date range
- `end_date` before inception → error dict with inception date
- `start_date > end_date` → caught in input validation (step 1)
- Window = 1 month → simplified output, risk metrics = `null`, skip `compute_performance_metrics()`
- Window = 2 months → compute normally, add warning to `realized_metadata.data_warnings`
- Window starts at first available month (no prior NAV) → `official_pnl_usd = None` with warning (no back-derivation attempted)

### 5. Report format — `_format_realized_report()`

When `custom_window` is present in result:
- Add header line: `"📅 Custom window: {start} to {end} (full history from {inception})"`
- **Guard all numeric formatters** against `None` values. Multiple paths in `_format_realized_report()`, `_categorize_performance_from_metrics()` (line 65), and `_generate_key_insights_from_metrics()` (line 92) do numeric comparisons or `:,.2f` formatting that will `TypeError` on `None`. Add a helper `_fmt(value, fmt=":,.2f", default="N/A")` that returns the formatted string or the default when value is `None`. Apply this in:
  - Report formatter: reconciliation gap, volatility, Sharpe, alpha, beta, all risk metrics
  - `_categorize_performance_from_metrics()`: guard `sharpe` and `annual_return` against `None` before comparison
  - `_generate_key_insights_from_metrics()`: guard all numeric fields before comparison
  - Summary format: numeric fields that are forwarded to the client should remain `None` (not "N/A") — JSON clients handle null natively. Only the report format needs string guards.

### 6. MCP server registration — `mcp_server.py`

The MCP server (`mcp_server.py:199`) wraps `_get_performance()` with its own signature for MCP clients. Add `start_date`/`end_date` params to the wrapper and thread them through:

```python
@mcp.tool()
def get_performance(
    ...
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    return _get_performance(
        ...
        start_date=start_date,
        end_date=end_date,
    )
```

Update the docstring with date param descriptions and examples.

### 7. No changes to `services/portfolio_service.py` for realized

Since realized post-filter happens in the MCP layer after the service call, the service layer doesn't need date params for realized mode. The cache continues to cache the full result; filtering is applied on top.

For hypothetical mode, dates flow through `PortfolioData` which already affects the cache key via `portfolio_data.get_cache_key()`.

---

## Files to modify

1. **`mcp_server.py`** — add `start_date`/`end_date` params to `get_performance()` wrapper, thread to `_get_performance()`
2. **`mcp_tools/performance.py`** — add `start_date`/`end_date` params, input validation, `_load_portfolio_for_performance()` threading, `_apply_date_window()` helper, `_postfilter` stripping (unconditional, before all format branches), report format update
3. **`core/realized_performance_analysis.py`** — add `_postfilter` sub-dict to `realized_metadata` (portfolio + benchmark returns, monthly_nav, net_flows, risk_free_rate — all raw precision)
4. **`tests/mcp_tools/test_performance.py`** — new tests for date window filtering
5. **`tests/core/test_realized_performance_analysis.py`** — test that `_postfilter` is present in output

## Files NOT modified

- `services/portfolio_service.py` — realized cache unaffected; hypothetical dates flow through PortfolioData
- `core/performance_metrics_engine.py` — already date-agnostic

---

## Verification

1. **Unit tests**:
   - `_apply_date_window` slices monthly returns correctly and snaps to month-ends
   - `_apply_date_window` uses prior-month NAV as opening balance for windowed P&L
   - `_apply_date_window` sets `official_pnl_usd = None` when no prior-month NAV exists (window starts at inception)
   - `_apply_date_window` calls window-specific treasury rate, not full-period rate
   - `_apply_date_window` returns error dict on empty window (checked by caller)
   - `reconciliation_gap_usd` is `None` in windowed output
   - N=1 month window returns simplified output with null risk metrics (no `compute_performance_metrics` call)
   - N=2 month window computes normally with warning in `data_warnings`
   - Report format handles `reconciliation_gap_usd = None` without TypeError
   - Edge cases: start after data, end before inception, reversed dates, empty window
   - `None` dates preserve existing behavior (no regression)
   - Hypothetical mode threads dates to PortfolioData
   - `_postfilter` is stripped unconditionally from all output paths (summary, full, report)
   - Both nested `realized_metadata` and top-level aliases are updated consistently
   - `_postfilter` stores raw floats (portfolio returns, benchmark returns, NAV, flows — not rounded)
   - `start_date` on month-start (`YYYY-MM-01`) confirms that month IS included (not skipped)
   - 1-month report formatting renders all `None` metrics without `TypeError`
   - `mcp_server.py` wrapper passes `start_date`/`end_date` through to `_get_performance()`

2. **MCP live tests**:
   - `get_performance(mode="realized", start_date="2025-01-01")` — ~13 months, recent performance only
   - `get_performance(mode="realized", start_date="2024-01-01", end_date="2024-12-31")` — 2024 only
   - `get_performance(mode="hypothetical", start_date="2024-01-01")` — hypothetical from 2024
   - `get_performance(mode="realized")` — unchanged (no regression)
   - `get_performance(mode="realized", start_date="2030-01-01")` — error: no data
