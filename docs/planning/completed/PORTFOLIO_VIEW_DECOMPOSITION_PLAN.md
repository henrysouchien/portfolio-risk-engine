# Decompose `build_portfolio_view()` + Add Per-Stock Sharpe/Sortino

**Status:** COMPLETE
**Date:** 2026-02-16
**Key functions:** `compute_stock_performance_metrics()`, `compute_factor_exposures()`, `compute_variance_attribution()`, `compute_asset_vol_summary()` in `portfolio_risk.py`

## Context

`_build_portfolio_view_computation()` is a ~500-line monolith in `portfolio_risk.py` (lines 699-1268). It computes returns, factor regressions, variance decomposition, and per-stock stats all in one pass. This coupling means you can't get per-stock risk-adjusted metrics (Sharpe/Sortino) without running the entire portfolio pipeline — blocking use cases like standalone stock analysis or an ETF leaderboard.

The function already has clear stage boundaries marked with section comments. We'll extract these into composable functions that `build_portfolio_view()` calls internally, while making the per-stock metrics stage independently callable.

## Stage Boundaries (current code)

| Stage | Lines | What it does | Dependencies |
|-------|-------|-------------|--------------|
| 0. Returns setup | 765-818 | `df_ret`, weights re-norm, cov/corr, vol, RC, HHI | weights, dates |
| 1. Equity factor betas | 821-941 | `df_stock_betas`, `idio_var_dict` | weights, factor proxies, dates |
| 1b. Rate factors | 942-1032 | Interest rate beta injection | asset_classes, df_stock_betas |
| 2a. Factor vols | 1034-1156 | `df_factor_vols`, `weighted_factor_var` | factor proxies, df_stock_betas |
| 2b. Euler variance | 1158-1164 | `euler_var_pct` | weights, cov_mat |
| 3. Industry aggregation | 1166-1189 | `industry_var_dict`, `industry_groups` | factor proxies, weighted_factor_var |
| 3a. Portfolio factor betas | 1191-1205 | `portfolio_factor_betas` = df_stock_betas × weights | df_stock_betas, weights |
| 4. Per-asset summary | 1207-1231 | `df_asset` (vol summary) | df_ret, idio_var_dict, weights |
| 5. Assembly | 1245-1268 | Return dict | all above |

## Existing Helper Functions (reused, not rewritten)

These standalone functions already exist and are called within the monolith:

- `compute_performance_metrics()` — `core/performance_metrics_engine.py` (portfolio-level Sharpe/Sortino/Calmar)
- `compute_covariance_matrix()`, `compute_correlation_matrix()` — `portfolio_risk.py`
- `compute_risk_contributions()` — `portfolio_risk.py`
- `compute_euler_variance_percent()` — `portfolio_risk.py`
- `compute_stock_factor_betas()`, `compute_multifactor_betas()` — `factor_utils.py`
- `calc_weighted_factor_variance()` — `portfolio_risk.py`
- `compute_portfolio_variance_breakdown()` — `portfolio_risk.py`
- `calc_monthly_returns()`, `compute_volatility()` — `factor_utils.py`
- `get_returns_dataframe()` — `portfolio_risk.py`

The ~500 lines of glue code (fetching proxy returns, aligning indices, looping per ticker for regressions, handling edge cases) is what gets organized into composable stages.

## Decomposition Plan

### New functions to extract (all in `portfolio_risk.py`):

**1. `compute_stock_performance_metrics(df_ret, risk_free_rate=0.04, start_date=None, end_date=None) → DataFrame`**
- **Standalone** — only needs a returns DataFrame (no weights, no factor proxies)
- `risk_free_rate` defaults to 0.04 (static) — never fetches treasury rates internally. Callers that want live rates fetch externally and pass explicitly.
- If `start_date`/`end_date` not provided, infer from `df_ret.index`
- Full performance suite mirroring `compute_performance_metrics()` but vectorized across all stocks:
  - `Annual Return` — CAGR
  - `Vol A` — annualized volatility
  - `Sharpe` — (annual return - rf) / vol
  - `Sortino` — (annual return - rf) / downside deviation
  - `Max Drawdown` — peak-to-trough
  - `Calmar` — annual return / |max drawdown|
  - `Downside Dev` — annualized downside deviation
  - `Win Rate` — % positive months
  - `Best Month` / `Worst Month`
- Returns a DataFrame indexed by ticker
- This is the reusable piece — works for portfolio stocks, standalone tickers, ETF screening, etc.
- **Risk-free rate**: Defaults to static 0.04 — no treasury API call. `_get_risk_free_rate()` helper extracted for callers that want live rates (used by `calculate_portfolio_performance_metrics()` only).

**Edge-case conventions** (match `compute_performance_metrics()` exactly):
- **Units**: All values in decimals (e.g., 0.25 = 25% vol), matching existing `Vol A` convention
- **Downside threshold**: Monthly returns below `rf_monthly` (= `risk_free_rate / 12`), matching `performance_metrics_engine.py:68`
- Zero vol → Sharpe = 0 (line 59)
- Zero downside deviation → Sortino = 0 (line 75)
- Max drawdown > -0.1% → Calmar = 0 (line 118)
- Replace any inf/-inf with 0.0, fillna(0.0) — **only for new performance columns**
- Stocks with < 3 months of data → all metrics = 0 (guard, with warning)

**2. `compute_factor_exposures(weights, df_ret, stock_factor_proxies, asset_classes, start_date, end_date, fmp_ticker_map) → dict`**
- Wraps current stages 1 + 1b + 2a (lines 821-1156)
- Also computes `portfolio_factor_betas` (line 1205: `df_stock_betas.mul(w_series, axis=0).sum()`)
- Returns: `{"df_stock_betas", "df_stock_betas_raw", "idio_var_dict", "df_factor_vols", "weighted_factor_var", "interest_rate_vol", "portfolio_factor_betas"}`
- **NaN ordering**: Industry aggregation (stage 3, inside `compute_variance_attribution`) reads raw `df_stock_betas` BEFORE fill. `compute_factor_exposures` returns `df_stock_betas` in TWO forms:
  - `"df_stock_betas_raw"` — with NaNs, passed to `compute_variance_attribution` for industry aggregation
  - `"df_stock_betas"` — after `.fillna(0.0)`, for the final return dict and `portfolio_factor_betas` computation (matching current line 1194-1196 → 1205 → 1254)
- This is the heaviest stage — all the factor regression work

**3. `compute_variance_attribution(weights, cov_mat, stock_factor_proxies, weighted_factor_var, idio_var_dict, vol_m, df_stock_betas) → dict`**
- Wraps current stages 2b + 3 (Euler + industry aggregation + variance decomposition)
- Returns: `{"euler_variance_pct", "industry_variance", "variance_decomposition"}`

**4. `compute_asset_vol_summary(df_ret, weights, idio_var_dict, stock_perf_metrics) → DataFrame`**
- Wraps current stage 4 (lines 1207-1231)
- `Vol A` comes from `stock_perf_metrics` (computed once in function 1) — NOT recomputed here. Avoids column collision.
- Adds portfolio-weighted columns: `Weighted Vol A`, `Idio Vol A`, `Weighted Idio Vol A`, `Weighted Idio Var`
- **NaN parity for idio columns**: Idio values stay NaN when no factor estimate exists (stocks without proxies). Only new performance columns (Sharpe, Sortino, etc.) use fillna(0.0). This preserves exact parity with current `df_asset` behavior.
- Joins remaining performance columns from `stock_perf_metrics` (Sharpe, Sortino, etc.)
- Returns the enriched `df_asset` DataFrame

### Rewritten `_build_portfolio_view_computation()`:

```python
def _build_portfolio_view_computation(...):
    # Stage 0: Returns setup (stays inline — short and foundational)
    df_ret = get_returns_dataframe(...)
    # ... weight re-normalization ...
    port_ret = compute_portfolio_returns(df_ret, weights)
    cov_mat = compute_covariance_matrix(df_ret)
    corr_mat = compute_correlation_matrix(df_ret)
    vol_m = compute_portfolio_volatility(weights, cov_mat)
    vol_a = vol_m * np.sqrt(12)
    rc = compute_risk_contributions(weights, cov_mat)
    hhi = compute_herfindahl(weights)
    df_alloc = compute_target_allocations(weights, expected_returns)

    # Stage 1-2a: Factor analysis (betas, idio var, factor vols, portfolio_factor_betas)
    # Returns df_stock_betas (filled) + df_stock_betas_raw (with NaNs) + portfolio_factor_betas
    factor_result = compute_factor_exposures(...)

    # Stage 2b-3: Variance attribution (Euler, industry, decomposition)
    # Uses df_stock_betas_raw for industry aggregation (NaN-aware, matching current behavior)
    var_result = compute_variance_attribution(
        ...,
        df_stock_betas=factor_result["df_stock_betas_raw"],
        ...
    )

    # Stage 4: Per-stock metrics (standalone + portfolio context)
    # Static 0.04 default — no treasury API call in risk path
    stock_perf = compute_stock_performance_metrics(df_ret, risk_free_rate=0.04, start_date=start_date, end_date=end_date)
    df_asset = compute_asset_vol_summary(df_ret, weights, factor_result["idio_var_dict"], stock_perf)

    # Assembly — same return dict shape as before
    # Note: df_stock_betas is the FILLED version (matching current output contract)
    return {
        "allocations": df_alloc,
        "covariance_matrix": cov_mat,
        "correlation_matrix": corr_mat,
        "volatility_monthly": vol_m,
        "volatility_annual": vol_a,
        "risk_contributions": rc,
        "herfindahl": hhi,
        "df_stock_betas": factor_result["df_stock_betas"],       # filled (0.0)
        "portfolio_factor_betas": factor_result["portfolio_factor_betas"],
        "factor_vols": factor_result["df_factor_vols"],
        "weighted_factor_var": factor_result["weighted_factor_var"],
        "euler_variance_pct": var_result["euler_variance_pct"],
        "asset_vol_summary": df_asset,
        "portfolio_returns": port_ret,
        "variance_decomposition": var_result["variance_decomposition"],
        "industry_variance": var_result["industry_variance"],
    }
```

## All Callers of `build_portfolio_view()`

These callers are **unchanged** — the return dict shape is identical (just `df_asset` gains new columns):

- `core/portfolio_analysis.py` — `analyze_portfolio()` (main entry point)
- `mcp_tools/risk.py` — `get_risk_analysis()` (MCP tool, via `portfolio_analysis.py`)
- `run_portfolio_risk.py` — `display_portfolio_summary()` (CLI)
- `core/scenario_analysis.py` — what-if scenarios
- `services/factor_intelligence_service.py` — factor performance profiles
- `portfolio_risk_score.py` — risk scoring
- `portfolio_optimizer.py` — optimization (uses `df_stock_betas`, `portfolio_factor_betas` for constraints)

## Files Modified

- **`portfolio_risk.py`** — Extract 4 functions + `_get_risk_free_rate()` helper, rewrite `_build_portfolio_view_computation()` as orchestrator, bump cache version to `"rbeta_v2"` at both touchpoints (lines 690 and 299)
- **`risk_summary.py`** — Update `get_stock_risk_profile()` to use `compute_stock_performance_metrics()` for Sharpe/Sortino
- **`tests/test_portfolio_risk.py`** (new file) — Tests for each extracted function + per-stock Sharpe/Sortino + edge cases

## What stays the same

- Return dict shape from `build_portfolio_view()` — identical 16 keys
- `df_asset` gains new columns but all existing columns preserved with same names/dtypes
- All 7 callers unchanged
- Cache key structure unchanged (just version bump at both touchpoints)
- MCP API response unchanged (new columns auto-flow through `asset_vol_summary`)

## Verification

### Parity test (critical)
Snapshot current `build_portfolio_view()` output with a known portfolio, run refactored version, assert all existing keys/values match exactly (only `df_asset` has additional columns). This should cover:
- Standard portfolio path (with factor proxies)
- No-proxy path (weights only, no `stock_factor_proxies`)
- Bond/rate-factor path (with `asset_classes` containing bonds)

### Unit tests for extracted functions
1. `compute_stock_performance_metrics()` — deterministic returns DataFrame, verify all 10 columns, edge cases:
   - Zero-vol stock (constant returns) → Sharpe = 0, Sortino = 0
   - All-positive-return stock → Sortino uses rf threshold, not 0
   - Stock with < 3 months data → all metrics = 0, warning logged
   - Known Sharpe/Sortino from hand-calculated example
2. `compute_factor_exposures()` — returns both raw and filled `df_stock_betas`, `portfolio_factor_betas` matches manual weighted sum
3. `compute_variance_attribution()` — Euler sums to ~1.0, industry dict non-empty when proxies provided
4. `compute_asset_vol_summary()` — no duplicate `Vol A` column, weighted columns computed correctly

### Integration/caller tests
5. `pytest tests/test_portfolio_risk.py -v` — all existing + new tests pass
6. `python run_portfolio_risk.py` — confirm `asset_vol_summary` shows new performance columns in CLI output
7. MCP `get_risk_analysis` with `include=["variance"]` — confirm new columns appear
8. Standalone: `compute_stock_performance_metrics(df_ret)` works without portfolio context
