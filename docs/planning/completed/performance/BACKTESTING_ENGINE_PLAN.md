# Strategy Builder Backtesting Engine (Wave 3g)

**Date**: 2026-03-03
**Status**: Revision 7 — addressing Codex review round 6 findings
**Wave**: 3g (from `completed/FRONTEND_PHASE2_WORKING_DOC.md`)

## Context

The Strategy Builder has a "Run Backtest" button that currently routes to what-if analysis (forward-looking risk projection) with mock results. We need a **real historical backtesting engine** that replays target weights over historical price data to show what-would-have-happened performance.

The building blocks already exist:
- `calculate_portfolio_performance_metrics()` in `portfolio_risk.py` (lines 1682-1821) does 90% of what we need: filter tickers → fetch returns → compute portfolio returns → fetch benchmark → call `compute_performance_metrics()`
- The backtest engine is a thin wrapper that adds: cumulative return series (for charting), annual breakdown (per-year performance), and proper result object packaging

**Single new file for the engine** (`portfolio_risk_engine/backtest_engine.py`), plus result object, API endpoint, MCP tool, and frontend wiring.

---

## Data Flow

```
Frontend: StrategyBuilder → "Run Backtest" button
  → handleBacktest() in StrategyBuilderContainer
    → POST /api/backtest { weights, benchmark, period } via SessionManager
      → backtest_engine.run_backtest()
        → compute min_obs from DATA_QUALITY_THRESHOLDS + requested window
        → _filter_tickers_by_data_availability(min_months=min_obs)
        → get_returns_dataframe(weights, start, end, min_observations=min_obs)
        → compute_portfolio_returns_partial(df_ret, weights)
            (dynamic reweighting: skips months with < min_weight_coverage,
             caps gross_scale at 5.0 to avoid near-cancel blow-up)
        → fetch_monthly_close(benchmark) → calc_monthly_returns()
            (calc_monthly_returns from factor_utils.py, NOT data_loader.py)
        → compute_performance_metrics(port_ret, bench_ret, risk_free_rate, benchmark_ticker, start_date, end_date, min_capm_observations=min_capm_obs)
        → Build cumulative series + annual breakdown
      → BacktestResult.to_api_response()
    → BacktestAdapter.transform()
  → StrategyBuilder renders real results in backtestResults[] shape
```

---

## Phase 1: Core Engine

**New file: `portfolio_risk_engine/backtest_engine.py`**

```python
def run_backtest(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    benchmark_ticker: str = "SPY",
    risk_free_rate: Optional[float] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    currency_map: Optional[Dict[str, str]] = None,
    instrument_types: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]
```

Implementation mirrors `calculate_portfolio_performance_metrics()` (lines 1734-1821):

**Step 0 — Dynamic observation gating** (lines 1734-1744):
```python
from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS
default_min_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_expected_returns"]
min_capm_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_capm_regression"]
requested_month_points = len(pd.date_range(start=start_date, end=end_date, freq="ME"))
requested_return_observations = max(1, requested_month_points - 1)
min_obs = min(default_min_obs, requested_return_observations)
```
This allows short-window backtests (e.g. 1Y = 11 observations) to proceed even when `default_min_obs` is higher. `min_capm_obs` gates CAPM regression inside `compute_performance_metrics()`.

1. `_filter_tickers_by_data_availability(weights, start, end, min_months=min_obs, ...)` → prune tickers with insufficient history, rebalance weights
2. `get_returns_dataframe(filtered_weights, ..., min_observations=min_obs)` → monthly returns DataFrame
3. `compute_portfolio_returns_partial(df_ret, filtered_weights)` → weighted monthly returns with **dynamic reweighting**: for each month, only available tickers contribute; weights are rescaled by `total_abs_weight / available_abs`; months where available weight coverage < `min_weight_coverage` (default 0.5) are skipped; months where `gross_scale > 5.0` (near-cancellation) are skipped
4. `fetch_monthly_close(benchmark_ticker, ...)` → benchmark prices → `calc_monthly_returns()` (**imported from `factor_utils.py`**, not `data_loader.py`)
5. Align portfolio + benchmark returns via `pd.DataFrame({...}).dropna()`
6. `_get_risk_free_rate()` if not provided
7. `compute_performance_metrics(portfolio_returns=port_ret, benchmark_returns=bench_ret, risk_free_rate=risk_free_rate, benchmark_ticker=benchmark_ticker, start_date=start_date, end_date=end_date, min_capm_observations=min_capm_obs)` → full metrics dict (returns None for alpha/beta/r_squared when observations < `min_capm_obs`). All 7 positional args are required — see `performance_metrics_engine.py:19-27`.

**Additional backtest-specific output:**
8. **Cumulative returns**: `(1 + port_ret).cumprod()` and same for benchmark — for charting
9. **Annual breakdown**: Group monthly returns by calendar year, compound within each year, compute per-year alpha vs benchmark
10. **Monthly return series**: Dict of `{YYYY-MM: return}` for portfolio + benchmark

Return dict shape:
```python
{
    "performance_metrics": { ... },  # Full output from compute_performance_metrics()
    "monthly_returns": { "2024-01": 0.023, ... },
    "benchmark_monthly_returns": { "2024-01": 0.018, ... },
    "cumulative_returns": { "2024-01": 1.023, ... },
    "benchmark_cumulative": { "2024-01": 1.018, ... },
    "annual_breakdown": [
        { "year": 2024, "portfolio_return": 18.5, "benchmark_return": 15.2, "alpha": 3.3 }
    ],
    "weights": { ... },
    "benchmark_ticker": "SPY",
    "excluded_tickers": [],
    "warnings": []
}
```

Key reuse points (all from `portfolio_risk_engine/`):
- `_filter_tickers_by_data_availability()` at `portfolio_risk.py:1747`
- `get_returns_dataframe()` at `portfolio_risk.py:277`
- `compute_portfolio_returns_partial()` at `portfolio_risk.py:120` (dynamic reweighting, coverage guards)
- `fetch_monthly_close()` at `data_loader.py`
- `calc_monthly_returns()` at **`factor_utils.py`** (NOT `data_loader.py` — imported at `portfolio_risk.py:55`)
- `_get_risk_free_rate()` at `portfolio_risk.py`
- `compute_performance_metrics()` at `performance_metrics_engine.py`
- `DATA_QUALITY_THRESHOLDS` at `config.py` (for `min_observations_for_expected_returns`, `min_observations_for_capm_regression`)

---

## Phase 2: Result Object + Flags

**New file: `core/result_objects/backtest.py`**

`BacktestResult` dataclass following `PerformanceResult` pattern (`core/result_objects/performance.py`):
- `to_api_response()` → JSON-serializable dict
- `get_summary()` → compact metrics
- `get_agent_snapshot()` → agent format snapshot

Register in `core/result_objects/__init__.py`.

**New file: `core/backtest_flags.py`**

Interpretive flags following standard pattern (`core/*_flags.py`):
- **warning**: "N tickers excluded due to insufficient history" (with list)
- **warning**: "Short backtest period (< 12 months) — metrics may be unreliable"
- **warning**: "Max drawdown exceeds -30%"
- **info**: "Outperformed/underperformed benchmark by X%"
- **success**: "Positive risk-adjusted returns (Sharpe > 1.0)"

---

## Phase 3: API Endpoint

**Modify: `app.py`** — add `POST /api/backtest`

Request:
```json
{
    "weights": {"AAPL": 0.3, "MSFT": 0.3, "SGOV": 0.4},
    "benchmark": "SPY",
    "period": "5Y",
    "start_date": null,
    "end_date": null
}
```

`period` options: `"1Y"`, `"3Y"`, `"5Y"`, `"10Y"`, `"MAX"`. Resolved server-side: end = today, start = today - N years. `start_date`/`end_date` override `period` when provided.

Logic:
1. Resolve `period` to start_date/end_date
2. Load portfolio config for `fmp_ticker_map`, `currency_map`, `instrument_types` (via `load_portfolio_config()` or `PortfolioManager`)
3. Call `backtest_engine.run_backtest()`
4. Wrap in `BacktestResult`, return with `success: True` wrapper (matching existing API response pattern, e.g. `/api/performance` at `app.py:1459`):
```python
{
    "success": True,
    "backtest_results": result.to_api_response(),
    "summary": result.get_summary(),
    "portfolio_metadata": { "name": ..., "user_id": ..., "source": "api", "analyzed_at": ... }
}
```

---

## Phase 4: MCP Tool

**New file: `mcp_tools/backtest.py`**

```python
@handle_mcp_errors
def run_backtest(
    user_email: Optional[str] = None,
    weights: Optional[dict] = None,       # {"AAPL": 0.3, "MSFT": 0.7} — typed dict, NOT str
    benchmark: str = "SPY",
    period: str = "5Y",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "agent"] = "agent",
    output: Literal["inline", "file"] = "inline",
    use_cache: bool = True,
) -> dict
```

Follows `run_whatif()` pattern in `mcp_tools/whatif.py` (lines 67-76):
- `weights` is `Optional[dict]` (typed dict param matching `target_weights` pattern — NOT `str` + `json.loads()`)
- `output` and `use_cache` params match whatif pattern
- `user_email` is first param (convention)
- Load portfolio context via `_load_portfolio_for_analysis()` from `mcp_tools/risk.py`
- Call `backtest_engine.run_backtest()`
- Build `BacktestResult`
- If `format == "agent"`: return snapshot + flags
- If `output == "file"`: write full payload to disk, return `file_path`
- Register in `mcp_server.py`

---

## Phase 5: Frontend Wiring

**5a. New hook: `frontend/packages/connectors/src/features/backtest/hooks/useBacktest.ts`**

Follow the `useWhatIfAnalysis` pattern: TanStack Query with `SessionManager` for API calls. The hook exposes a `runBacktest()` function (similar to `whatIf.runScenario()`) that POSTs to `/api/backtest` and stores results in query state.

```typescript
// Frontend interface (camelCase)
interface BacktestParams {
  weights: Record<string, number>;
  benchmark?: string;
  period?: '1Y' | '3Y' | '5Y' | '10Y' | 'MAX';
  startDate?: string;   // Serialized to snake_case (start_date) by APIService
  endDate?: string;      // Serialized to snake_case (end_date) by APIService
}

interface UseBacktestReturn {
  data: BacktestData | null;
  isLoading: boolean;
  error: string | null;
  runBacktest: (params: BacktestParams) => void;
}
```

Export from `@risk/connectors` index.

**Frontend plumbing** (following `useWhatIfAnalysis` pattern through the service chain):
- **`PortfolioManager.ts`**: Add `analyzeBacktest(params)` method that calls `this.cacheService.getBacktest(params)`
- **`PortfolioCacheService.ts`**: Add `getBacktest(params)` method that calls `this.apiService.postBacktest(params)` with cache TTL. Cache key must use a deep deterministic hash of all params — `JSON.stringify()` the full params object (including the nested `weights` dict with sorted keys) to produce a unique cache key. Do NOT use the existing shallow key pattern which only stringifies top-level keys and would collide on different ticker weight sets
- **`APIService.ts`**: Add `postBacktest(params)` method → `POST /api/backtest` with snake_case body (`start_date`, `end_date`)
- **`api.ts` types**: Add `BacktestApiResponse` interface alongside existing type aliases (e.g. `PerformanceApiResponse` at line 45). Define the response shape to match the `{success, backtest_results, summary, portfolio_metadata}` wrapper. Note: existing generated types in `api-generated.ts` are from a one-time generation — new endpoints add manual types here.
- **`models/response_models.py`**: Add `BacktestResponse(BaseModel)` following the non-direct endpoint pattern (e.g. `PerformanceResponse` at line 28, used by `/api/performance`). Fields: `success: bool`, `backtest_results: Dict[str, Any]`, `summary: Dict[str, Any]`, `portfolio_metadata: Dict[str, Any]`. Use as `response_model` in the `app.py` route decorator via `get_response_model(BacktestResponse)`.
- **`models/__init__.py`**: Add `from .response_models import BacktestResponse` export (following existing pattern at lines 1-20).
- The hook calls `manager.analyzeBacktest(params)` → adapter transforms → query cache

**5b. New adapter: `frontend/packages/connectors/src/adapters/BacktestAdapter.ts`**

snake_case → camelCase transform. **Critical**: The adapter must map the API response to the existing `backtestResults` UI contract expected by `StrategyBuilder.tsx` (lines 227-233):

```typescript
// StrategyBuilder expects this shape:
backtestResults: Array<{
  period: string;     // e.g. "2019-2024"
  return: number;     // total portfolio return (%)
  benchmark: number;  // total benchmark return (%)
  alpha: number;      // portfolio - benchmark (%)
  sharpe: number;     // Sharpe ratio
}>
```

The adapter transforms the API's `performance_metrics` + `annual_breakdown` into this shape using the **actual nested keys** from `compute_performance_metrics()` output (see `performance_metrics_engine.py:175-224`):
- **Summary row**: `period` = "{start_year}-{end_year}", `return` = `performance_metrics.returns.total_return`, `benchmark` = `performance_metrics.benchmark_comparison.benchmark_total_return`, `alpha` = `performance_metrics.benchmark_comparison.portfolio_total_return - benchmark_total_return` (simple excess return, NOT CAPM alpha — avoids `alpha_annual` being `None` on short windows), `sharpe` = `performance_metrics.risk_adjusted_returns.sharpe_ratio`
- **Annual rows** (from `annual_breakdown[]`): `period` = year string, `return`/`benchmark`/`alpha` from each entry, `sharpe` = 0
- **Null safety**: All numeric fields default to 0 when source is `None` (e.g. short-window backtests where CAPM regression can't run)

The adapter also passes through the full response (cumulative series, monthly returns, risk_metrics) as extended fields for richer rendering when the UI is ready for it.

**5c. Update `StrategyBuilderContainer.tsx`:**
- Replace mock `backtestResults` array (currently lines 197-205) with real data from `useBacktest()` hook
- Replace `handleBacktest` function (currently lines 273-321, routes to `whatIf.runScenario()`) — call `backtest.runBacktest()` with **ticker weights from `optimizationData.weights`** (e.g. `{AAPL: 0.3, MSFT: 0.4}`), NOT the asset-class allocation sliders (`{stocks: 60, bonds: 30}`). The StrategyBuilder's `allocation` state is asset-class percentages — these are NOT valid backtest inputs. The backtest engine requires real ticker weights, which come from the optimization result.
- If no optimization has been run yet (no ticker weights available), disable the backtest button or show a message ("Run optimization first")
- Wire `backtest.isLoading` into component loading state

**5d. Update `StrategyBuilder.tsx`:**
- The existing `backtestResults` type (lines 227-233) is preserved — no type changes needed
- Render real backtest results using the same table format, now with real data instead of mock
- Add period selector (1Y/3Y/5Y/10Y/MAX) that re-triggers backtest
- Wire `isBacktesting` state from hook loading
- Remove mock `backtestResults` fallback comment (line 254)

---

## Edge Cases

1. **Tickers without full history**: Handled by `_filter_tickers_by_data_availability()`. Report excluded tickers + warnings in response. If ALL excluded, return error.
2. **Short periods**: 1Y backtest gives ~11 monthly return observations. Dynamic observation gating (`min_obs = min(default_min_obs, requested_return_observations)`) allows short windows to proceed. `compute_performance_metrics()` returns None for alpha/beta/r_squared when observations < `min_capm_obs`. Surface in flags.
3. **FX / futures / international**: Fully handled by passing `currency_map`, `instrument_types`, `fmp_ticker_map` through to `get_returns_dataframe()`.
4. **Performance**: `get_returns_dataframe()` uses disk + LRU caching for price data. A 5Y backtest with 20 tickers should complete in 2-5 seconds. Cached runs sub-second.
5. **Units consistency**: `compute_performance_metrics()` returns values already in percent (15.5 not 0.155). Do NOT multiply by 100 again.

---

## Critical Files

| File | Purpose |
|------|---------|
| `portfolio_risk_engine/portfolio_risk.py` | Reference: `calculate_portfolio_performance_metrics()` (lines 1682-1821), `get_returns_dataframe()`, `compute_portfolio_returns_partial()`, `_filter_tickers_by_data_availability()`, `_get_risk_free_rate()` |
| `portfolio_risk_engine/performance_metrics_engine.py` | `compute_performance_metrics()` — called by engine |
| `portfolio_risk_engine/data_loader.py` | `fetch_monthly_close()` |
| `portfolio_risk_engine/factor_utils.py` | `calc_monthly_returns()` (imported at `portfolio_risk.py:55`) |
| `portfolio_risk_engine/config.py` | `DATA_QUALITY_THRESHOLDS` (observation gating) |
| `core/result_objects/performance.py` | Pattern for `BacktestResult` |
| `mcp_tools/whatif.py` | Pattern for MCP tool structure |
| `portfolio_risk_engine/backtest_engine.py` | **NEW** — core engine |
| `core/result_objects/backtest.py` | **NEW** — result object |
| `core/backtest_flags.py` | **NEW** — interpretive flags |
| `mcp_tools/backtest.py` | **NEW** — MCP tool |
| `models/response_models.py` | **MODIFY** — add `BacktestResponse` |
| `models/__init__.py` | **MODIFY** — export `BacktestResponse` |
| `app.py` | **MODIFY** — add `/api/backtest` endpoint + import `BacktestResponse` from `models` (add to existing import list at line 132) |
| `mcp_server.py` | **MODIFY** — register backtest tool |
| `frontend/.../StrategyBuilderContainer.tsx` | **MODIFY** — wire real backtest (use `optimizationData.weights` as ticker weights) |
| `frontend/.../StrategyBuilder.tsx` | **MODIFY** — render real results |
| `frontend/.../useBacktest.ts` | **NEW** — TanStack Query hook |
| `frontend/.../BacktestAdapter.ts` | **NEW** — response adapter |
| `frontend/.../PortfolioManager.ts` | **MODIFY** — add `analyzeBacktest()` method |
| `frontend/.../PortfolioCacheService.ts` | **MODIFY** — add `getBacktest()` method |
| `frontend/.../APIService.ts` | **MODIFY** — add `postBacktest()` method |
| `frontend/.../api.ts` | **MODIFY** — add `BacktestApiResponse` type |

---

## Verification

1. **Unit test**: `tests/test_backtest_engine.py` — mock `get_returns_dataframe`, verify metrics computation, ticker exclusion, annual breakdown
2. **MCP test**: Call `run_backtest` tool with real portfolio weights
3. **API test**: `POST /api/backtest` with sample weights
4. **pnpm typecheck** + **pnpm build** — no frontend errors
5. **Chrome verification**: Strategy Builder → Run Backtest → see real historical performance with cumulative chart
