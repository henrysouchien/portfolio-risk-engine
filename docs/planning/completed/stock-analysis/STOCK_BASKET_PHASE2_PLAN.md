# Stock Basket Phase 2: Returns Analysis

**Date**: 2026-02-27
**Status**: Complete (commit `240f00ea`)
**Depends on**: Phase 1 (CRUD tools, complete)
**Codex review**: 2 rounds — PASS. Addressed portfolio correlation source, alignment guards, benchmark fetching, risk-free rate, component attribution
**Risk**: Low-Medium — reuses existing returns computation and performance metrics engine

## Goal

New MCP tool `analyze_basket` that computes weighted returns for a saved basket and reports full performance metrics (return, Sharpe, drawdown, alpha/beta vs benchmark) plus per-component analysis and portfolio correlation.

## Data Flow

```
get_basket(name) → resolved basket_weights
    ↓
get_returns_dataframe(basket_weights, start, end)     → per-ticker returns DataFrame
compute_portfolio_returns(df, basket_weights)          → basket return pd.Series
    ↓
compute_performance_metrics(basket_series, benchmark)  → full metrics dict
df.corr()                                              → N×N component correlation matrix
per-component: compounded returns + weight × contribution → individual ticker stats
    ↓
BasketAnalysisResult → get_agent_snapshot() → flags → MCP response
```

## Implementation

### 1. New result object: `core/result_objects/basket.py`

New `BasketAnalysisResult` dataclass following the existing pattern (see `performance.py`, `optimization.py`).

**Fields:**
- `basket_name: str`
- `description: Optional[str]`
- `tickers: List[str]`
- `resolved_weights: Dict[str, float]`
- `weighting_method: str`
- `performance: Dict[str, Any]` — the full dict from `compute_performance_metrics()`
- `component_returns: Dict[str, Dict[str, float]]` — per-ticker `{total_return, annualized_return, volatility, weight, contribution}`
- `correlation_matrix: Dict[str, Dict[str, float]]` — N×N ticker correlation as nested dict
- `basket_to_portfolio_corr: Optional[float]` — scalar correlation to user's portfolio (None if no portfolio)
- `data_coverage: Dict[str, Any]` — `{available_tickers: [...], excluded_tickers: [...], coverage_pct: float}`
- `analysis_period: Dict[str, Any]` — start_date, end_date, total_months
- `analysis_date: datetime`
- `warnings: List[str]`

**Methods:**
- `get_agent_snapshot() -> Dict` — returns key metrics for agent consumption: basket name, weighting, ticker count, total return, annualized return, volatility, Sharpe, max drawdown, alpha, beta, top/bottom component, portfolio correlation, data coverage, warnings
- `get_summary() -> Dict` — condensed version
- `to_api_response() -> Dict` — full serializable payload

Re-export from `core/result_objects/__init__.py`.

### 2. New flags module: `core/basket_flags.py`

Following the existing flag pattern (see `core/performance_flags.py`).

**`generate_basket_flags(snapshot: Dict) -> List[Dict]`**

Flag logic:
- **Concentration**: If any single component weight > 40%, warning about concentration risk
- **Performance**: If annualized return < 0, warning. If Sharpe > 1.5, success. If Sharpe < 0, warning.
- **Drawdown**: If max drawdown > 20%, warning
- **Data coverage**: If excluded tickers > 0, warning listing what was dropped
- **Correlation**: If basket-to-portfolio correlation > 0.9, info that basket adds little diversification. If < 0.3, success that basket provides diversification.
- **Volatility**: If basket volatility > 30%, warning about high vol

Severity order: error → warning → info → success (same as all other flag modules).

### 3. New MCP tool: `analyze_basket` in `mcp_tools/baskets.py`

**Signature:**
```python
@handle_mcp_errors
def analyze_basket(
    name: str,
    benchmark_ticker: str = "SPY",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_portfolio_correlation: bool = True,
    format: Literal["full", "agent"] = "full",
    user_email: Optional[str] = None,
) -> dict:
```

**Implementation steps:**

1. Resolve user and load basket via existing `get_factor_group()`
2. Resolve weights using existing `_resolve_weights()` helper
3. Handle missing start_date/end_date: default to 3 years back from today
4. Call `get_returns_dataframe(resolved_weights, start_date, end_date)` to get per-ticker returns
5. Filter to available tickers, re-normalize weights, track excluded tickers (the data_coverage handling from the plan)
6. Call `compute_portfolio_returns(returns_df, adjusted_weights)` to get basket return series
7. Fetch benchmark returns using the direct path: `fetch_monthly_close(benchmark_ticker, start, end)` → `calc_monthly_returns()` (same approach as `portfolio_risk.py:1604`). This avoids the 11-observation filter that `get_returns_dataframe()` applies.
8. Align basket and benchmark series on common dates via `pd.concat([basket, benchmark], axis=1).dropna()`. **Guard**: if aligned length < 3, return an error response ("insufficient overlapping data for analysis") instead of proceeding to metrics computation.
9. Fetch risk-free rate using the same treasury-based pattern as the existing performance path: 3-month Treasury mean with 4% (0.04) fallback. See `portfolio_risk.py:1489` for the hypothetical path and `mcp_tools/performance.py:283` for `_safe_treasury_rate`. Prefer the simpler fallback approach.
10. Call `compute_performance_metrics(basket_series, benchmark_series, risk_free_rate, benchmark_ticker, start_date, end_date)`
11. Compute per-component stats using compounded returns: `total_return = (1 + df[ticker]).prod() - 1`, `annualized_return`, `volatility = df[ticker].std() * sqrt(12)`, `contribution = weight × total_return`. This is mathematically correct for multiplicative returns.
12. Compute component correlation matrix: `returns_df.corr()`
13. If `include_portfolio_correlation` and user has a portfolio: load portfolio positions via `PositionService.get_all_positions(user_id)` (same user-scoped pattern as `mcp_tools/factor_intelligence.py:454`), extract ticker weights, compute portfolio return series via `get_returns_dataframe()` + `compute_portfolio_returns()`, then `basket_series.corr(portfolio_series)`.
14. Build `BasketAnalysisResult`
15. If `format="agent"`: call `get_agent_snapshot()` → `generate_basket_flags()` → return agent response

**Portfolio correlation (step 13)**: Use `PositionService.get_all_positions(user_id)` to get user-scoped live holdings (NOT `load_portfolio_config()` which reads local YAML and has no user context). Extract ticker weights from positions DataFrame. If the user has no portfolio or positions fail to load, set `basket_to_portfolio_corr = None` and add an info warning. This is best-effort — don't fail the tool if portfolio can't be loaded.

**Risk-free rate**: Use 3-month Treasury mean with 0.04 fallback, matching the existing performance path in `portfolio_risk.py:1489`. Do NOT reference `settings.RISK_FREE_RATE` — that constant doesn't exist.

### 4. Register tool in `mcp_server.py`

Follow existing pattern — import from `mcp_tools.baskets`, register with `@mcp.tool()`.

### 5. Update `mcp_tools/__init__.py`

Add `analyze_basket` to exports.

## Key Implementation Notes

- **`compute_performance_metrics()` returns values already in percent** — do NOT multiply by 100 again in the snapshot
- **`get_returns_dataframe()` uses inner join** (`.dropna()`) — only months where ALL tickers have data survive. This is why we must re-normalize weights for excluded tickers.
- **Minimum observations**: `get_returns_dataframe()` defaults to 11 months minimum per ticker. Baskets with very new IPOs may have components excluded.
- **FMP ticker map**: Not needed for standard US equities. Pass `fmp_ticker_map=None`.
- **Use `make_json_safe()`** from `utils/serialization.py` on any dict going to JSON (handles NaN → None).
- **Alignment guard**: After aligning basket and benchmark series, check length ≥ 3 before calling `compute_performance_metrics()`. If too short, return a structured error instead of letting assertions crash.
- **All-excluded edge case**: If all basket tickers are excluded by the min-observations filter, `get_returns_dataframe()` raises `ValueError`. Catch this and return a user-friendly error ("no basket components have sufficient price history").
- **Component attribution math**: Use compounded returns `(1 + r).prod() - 1`, not `sum()`. The sum of monthly returns is not the total return.

## Reference Files

- `portfolio_risk_engine/portfolio_risk.py:459` — `get_returns_dataframe()`
- `portfolio_risk_engine/portfolio_risk.py:101` — `compute_portfolio_returns()`
- `portfolio_risk_engine/performance_metrics_engine.py:19` — `compute_performance_metrics()`
- `core/result_objects/performance.py` — `PerformanceResult` pattern
- `core/performance_flags.py` — flag generation pattern
- `mcp_tools/performance.py` — existing performance MCP tool (agent format, risk-free rate)
- `mcp_tools/baskets.py` — Phase 1 helpers to reuse
- `mcp_tools/common.py` — `@handle_mcp_errors`
- `utils/serialization.py` — `make_json_safe()`
- `portfolio_risk_engine/portfolio_risk.py:1604` — direct benchmark fetch pattern (`fetch_monthly_close` + `calc_monthly_returns`)
- `portfolio_risk_engine/portfolio_risk.py:1489` — risk-free rate treasury pattern with 0.04 fallback
- `mcp_tools/factor_intelligence.py:454` — user-scoped portfolio position loading pattern via `PositionService`
- `services/portfolio/position_service.py` — `PositionService.get_all_positions()`

## Verification

1. `python3 -c "from mcp_tools.baskets import analyze_basket"` — imports cleanly
2. Create a test basket with 5 tickers, call `analyze_basket("test", format="agent")` — returns full metrics
3. Verify Sharpe ratio, total return, and max drawdown are plausible for the chosen tickers
4. Verify per-component contributions sum to approximately the basket total return
5. Verify data_coverage reports any excluded tickers
6. Verify flags fire correctly (e.g., high concentration, low Sharpe)
7. Verify portfolio correlation is computed when user has a portfolio, and None when not
