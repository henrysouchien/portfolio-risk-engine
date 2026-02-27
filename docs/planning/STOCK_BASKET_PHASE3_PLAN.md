# Stock Basket Phase 3: Basket as Custom Factor

**Date**: 2026-02-27
**Status**: Planned
**Depends on**: Phase 2 (returns analysis, complete)
**Codex review**: 4 rounds — PASS. R1: 4 HIGH (correlation buckets, perf re-fetch, cache fingerprint, portfolio recs threading). R2: 2 HIGH (recs path, perf schema), 2 MEDIUM (overlay sampling, cache threading). R3: 2 MEDIUM (Sharpe risk-free, returns date alignment), 1 LOW (overlay duplication). R4: PASS — 3 MEDIUM (returns date scope, label→column mapping for Sharpe lookup, fingerprint on failure), 2 LOW. All addressed below.
**Risk**: Medium — injects into existing factor panel + requires targeted changes to correlation overlay and performance computation to handle synthetic (non-ticker) columns

## Goal

Wire user baskets into the factor analysis system so they appear alongside standard factors (SPY, QQQ, sector ETFs) in correlation matrices, performance tables, and hedge recommendations — all transparently.

## Design Decision: Extra Returns Injection (Not Universe Extension)

Baskets are **weighted composites** (a single return series computed from multiple tickers), not individual ticker ETFs. The existing panel construction (`build_factor_returns_panel()`) fetches price data per-ticker from FMP. We can't add basket names to the universe because they aren't real tickers.

**Approach**: Inject pre-computed basket return series into the panel **after** the normal panel is built. The normal panel construction, LRU caching, and universe logic are untouched. However, two downstream consumers need targeted changes:
1. **Correlations** are computed within category buckets — a `user_baskets` category with 1-2 items would be skipped (`len < 2`). Fix: add a dedicated basket overlay matrix that correlates baskets against all factors (following the existing macro overlay pattern).
2. **Performance** re-fetches price data by ticker name via `calculate_portfolio_performance_metrics()` — basket names aren't real tickers. Fix: detect basket columns and compute metrics directly from the panel series.

## Data Flow

```
MCP tool: get_factor_analysis(include_baskets=True)
    ↓
_compute_basket_factor_series(user_email, start, end)
  → load all user baskets from DB via get_user_factor_groups(user_id)
  → for each: resolve weights → get_returns_dataframe → compute_portfolio_returns
  → return Dict[str, pd.Series]  (basket_name → monthly returns)
    ↓
service._panel(extra_returns=basket_series)
  → build normal panel (unchanged, LRU-cached)
  → clone panel, append basket columns
  → update attrs['categories'] with {basket_name: 'user_baskets'}
  → update attrs['labels'] with {basket_name: display_label}
    ↓
analyze_correlations: basket overlay matrix (baskets × all factors)
analyze_performance: direct metrics from panel series (bypass re-fetch)
recommend_offsets: baskets as hedge candidates
    ↓
Result objects → agent snapshot → flags → MCP response
  (baskets appear in correlation matrices, performance tables, recommendations)
```

## Implementation

### 1. New helper: `_compute_basket_factor_series()` in `mcp_tools/factor_intelligence.py`

```python
def _compute_basket_factor_series(
    user_email: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[Dict[str, pd.Series], str]:
    """Returns (basket_series_dict, cache_fingerprint)."""
```

**Steps:**
1. Resolve user via `resolve_user_email()` + DB user ID lookup (reuse pattern from `baskets.py:48`). If user resolution fails, return `({}, "")` — don't break factor analysis when `RISK_MODULE_USER_EMAIL` is missing.
2. Load all baskets: `db.get_user_factor_groups(user_id)` (returns list of dicts with `group_name`, `tickers`, `weights`, `weighting_method`, `updated_at`)
3. Build cache fingerprint from `(user_id, name, updated_at)` tuples — not just names. This ensures cache invalidates when basket content changes.
4. For each basket:
   - Parse tickers and weighting_method from DB row
   - Resolve weights using `_resolve_weights()` from `mcp_tools/baskets.py` (import it)
   - Call `get_returns_dataframe(resolved_weights, start, end)` — use the **same** start/end dates passed to the factor tool (which match the panel's resolved dates)
   - Filter to available tickers, re-normalize weights (same pattern as `analyze_basket`)
   - Call `compute_portfolio_returns(returns_df, adjusted_weights)` → pd.Series
   - Store in result dict: `{group_name: series}`
5. Skip baskets that fail (log warning, don't break the tool)
6. Return `({}, "")` if user has no baskets or all fail

**Date alignment**: The MCP tool passes the same `start_date`/`end_date` to both the factor service and the basket helper. The service internally uses `_resolve_dates()` to default to last-completed-month-end. To avoid subtle mismatches, the MCP tool should call `service._resolve_dates(start_date, end_date)` first and pass the resolved dates to the basket helper.

**Reuse**: Import `_resolve_weights`, `_normalize_tickers` from `mcp_tools.baskets`. Import `get_returns_dataframe`, `compute_portfolio_returns` from `portfolio_risk_engine.portfolio_risk`.

### 2. Modify `_panel()` in `services/factor_intelligence_service.py`

Add `extra_returns: Optional[Dict[str, pd.Series]] = None` parameter (line 225).

After the existing panel build + asset class filter, inject extra returns:
```python
if extra_returns:
    panel = self._inject_extra_returns(panel, extra_returns)
return panel
```

### 3. New method: `_inject_extra_returns()` in `services/factor_intelligence_service.py`

```python
def _inject_extra_returns(self, panel: pd.DataFrame, extra_returns: Dict[str, pd.Series]) -> pd.DataFrame:
```

**Steps:**
1. Clone the panel (`panel.copy()`) — don't mutate the LRU-cached version
2. Deep-copy `attrs` dicts (pandas 2.2.3 preserves attrs on `.copy()`, but category/label dicts are shared references — must deep-copy to avoid mutating cached metadata): `new_panel.attrs = {k: (dict(v) if isinstance(v, dict) else v) for k, v in panel.attrs.items()}`
3. For each `(name, series)` in `extra_returns`:
   - **Case-insensitive collision check**: if `name.upper()` matches any existing column (uppercased), skip and log warning. This prevents basket "SPY" from overwriting the real SPY column.
   - Align series to panel index via `series.reindex(panel.index)` (NaN for missing months)
   - Add as new column: `new_panel[name] = aligned_series`
4. Update `new_panel.attrs['categories']`: add `{name: 'user_baskets'}` for each injected series
5. Update `new_panel.attrs['labels']`: add `{name: f"Basket: {name}"}` for display
6. Return modified panel

### 4. Thread `extra_returns` through service analysis methods

Add `extra_returns: Optional[Dict[str, pd.Series]] = None` parameter to these methods and pass through to `_panel()`:

- `analyze_correlations()` (line 264)
- `analyze_performance()`
- `analyze_returns()`
- `recommend_offsets()` (line 735)
- `recommend_portfolio_offsets()` (line 927) — **critical**: this method does NOT call `_panel()` directly. It calls `recommend_offsets()` at line 1056. Thread `extra_returns` through to that inner call.

Each method that calls `self._panel(...)` adds `extra_returns=extra_returns` to the call. For `recommend_portfolio_offsets()`, pass `extra_returns` to its `self.recommend_offsets()` call instead.

### 5. Basket cross-correlation matrix (shared by correlations + recommendations)

**Problem**: Correlations are computed within category buckets (line 896 in `core/factor_intelligence.py`). A `user_baskets` category with 1-2 baskets gets skipped (`len(tickers) < 2`) or only correlates baskets against each other — not against standard factors. The same matrices feed `recommend_offsets()` (line 796), so baskets won't appear as hedge candidates either.

**Fix**: New helper function `_compute_basket_cross_correlations()` in `core/factor_intelligence.py`, called from BOTH `compute_per_category_correlation_matrices()` AND usable in `recommend_offsets()`.

**`_compute_basket_cross_correlations(panel: pd.DataFrame) -> Optional[pd.DataFrame]`:**

1. Identify basket columns from `panel.attrs['categories']` where value == `'user_baskets'`
2. If no basket columns, return None
3. Identify all non-basket columns (the standard factors)
4. For each basket, compute **pairwise** correlation against each factor: `panel[[basket, factor]].dropna().corr().iloc[0, 1]`. This avoids global `dropna()` which would collapse observations.
5. Build an N×M DataFrame: rows = all factors + baskets, columns = all factors + baskets, filling pairwise correlations. (Or simpler: a dict-of-dicts that becomes a DataFrame.)
6. Return as `basket_overlay` matrix

**Single integration point in `compute_per_category_correlation_matrices()`:**
- After the category loop (line 908), call `_compute_basket_cross_correlations(panel)`
- If result is not None, store as `matrices['basket_overlay']` with data quality entry

**Recommendation path inherits automatically:**
- `recommend_offsets()` at line 796 calls `compute_per_category_correlation_matrices(panel)` and gets back all matrices including `basket_overlay`
- The existing `scan_matrix` loop at line 887 (`for key, mat in matrices.items()`) automatically scans `basket_overlay`, finding basket-vs-factor correlations
- Baskets anti-correlated to the overexposed factor appear as hedge candidates
- Single compute path avoids divergence risk between correlation reporting and recommendations

### 6. Basket performance handling in `compute_factor_performance_profiles()`

**Problem**: `compute_factor_performance_profiles()` (line 1312 in `core/factor_intelligence.py`) loops through panel columns and calls `calculate_portfolio_performance_metrics(weights={ticker: 1.0}, ...)` per column. For basket names like "tech_leaders", this tries to fetch price data for a non-existent ticker.

**Fix**: In the loop at line 1328, check if the column is a basket (via `categories.get(t) == 'user_baskets'`). For baskets, compute metrics directly from the panel series and output using the **exact same schema** as `_perf_pick_fields()` (line 1292) — keys must be `annual_return`, `volatility`, `sharpe_ratio`, `max_drawdown`, `beta_to_market`:

```python
categories = returns_panel.attrs.get("categories", {})

for t in returns_panel.columns:
    if categories.get(t) == 'user_baskets':
        # Compute directly from panel series — no FMP re-fetch
        series = returns_panel[t].dropna()
        if len(series) < 3:
            errors[t] = "insufficient data for basket"
            continue
        total_return = float((1 + series).prod() - 1)
        n_months = len(series)
        ann_return = float((1 + total_return) ** (12 / n_months) - 1) if total_return > -1 else 0.0
        vol = float(series.std() * np.sqrt(12))
        # Max drawdown from cumulative returns
        cum = (1 + series).cumprod()
        running_max = cum.cummax()
        drawdown = ((cum - running_max) / running_max).min()
        # Use same risk-free rate as the canonical engine (fetched at top of function or passed in)
        rf = risk_free_rate  # annual decimal, e.g. 0.04
        profiles[t] = {
            "annual_return": round(ann_return * 100, 2),    # percent, matching _perf_pick_fields schema
            "volatility": round(vol * 100, 2),               # percent
            "sharpe_ratio": round((ann_return - rf) / vol, 3) if vol > 0 else None,  # risk-free adjusted
            "max_drawdown": round(float(drawdown) * 100, 2), # percent (negative)
            "beta_to_market": None,                           # not computed for baskets
        }
        continue
    # ... existing ticker-based fetch path unchanged
```

Key: output dict keys match `_perf_pick_fields()` exactly (`annual_return`, `volatility`, `sharpe_ratio`, `max_drawdown`, `beta_to_market`). Values in percent (matching `compute_performance_metrics` convention). No new helper functions needed — max drawdown computed inline from cumulative returns.

### 7. Update service-level cache keys

Service cache keys must include a basket fingerprint that reflects **content changes**, not just names. Use the fingerprint string returned by `_compute_basket_factor_series()`:

```python
# In MCP tool layer, pass fingerprint to service
basket_series, basket_fp = _compute_basket_factor_series(user_email, start, end)
```

Thread BOTH `extra_returns` AND `basket_fp` through all service methods. Add `basket_fp` to cache key tuples in:
- `analyze_correlations()` cache key (line 417)
- `analyze_performance()` cache key
- `analyze_returns()` cache key
- `recommend_offsets()` cache key (line 787)
- `recommend_portfolio_offsets()` — thread both to its inner `self.recommend_offsets()` call at line 1056

The fingerprint is built from `(user_id, name, updated_at)` tuples, so it invalidates when baskets are created/updated/deleted/renamed.

### 8. Update MCP tools in `mcp_tools/factor_intelligence.py`

**`get_factor_analysis()`** (line 155) — Add parameters:
- `include_baskets: bool = True`
- `user_email: Optional[str] = None` (needed for basket DB lookup)

Before calling service methods, resolve dates and compute basket series:
```python
basket_series = {}
basket_fp = ""
if include_baskets:
    resolved_dates = service._resolve_dates(start_date, end_date)
    basket_series, basket_fp = _compute_basket_factor_series(
        user_email, resolved_dates["start"], resolved_dates["end"]
    )
```

Pass to each service call: `extra_returns=basket_series or None, basket_fp=basket_fp`

**No-user fallback**: If `user_email` is None and `RISK_MODULE_USER_EMAIL` is not set, `_compute_basket_factor_series` returns `({}, "")` — factor analysis proceeds without baskets. No error raised.

**`get_factor_recommendations()`** (line 507) — Add parameter:
- `include_baskets: bool = True`

Same pattern — compute basket series and pass to service calls. (`user_email` already exists on this tool.)

### 9. Register updated tool signatures in `mcp_server.py`

Add `include_baskets: bool` parameter to both `get_factor_analysis()` and `get_factor_recommendations()` wrappers. For `get_factor_analysis()`, also add `user_email` (pass `None` like other tools — uses `RISK_MODULE_USER_EMAIL` from env). `get_factor_recommendations()` already has `user_email`.

## Key Implementation Notes

- **`build_factor_returns_panel()` unchanged** — LRU-cached panel builder is untouched
- **Two targeted changes to `core/factor_intelligence.py`**: (1) basket overlay in correlation computation, (2) basket branch in performance profile computation. Both are additive — existing logic untouched.
- **No changes to result objects or flag generation** — basket overlay matrix flows through existing `FactorCorrelationResult.matrices` dict; basket performance entries flow through existing `profiles` dict
- **Basket names as column names**: Use `group_name` (e.g., "tech_leaders") as the panel column. `labels` attr provides display: `"Basket: tech_leaders"`
- **Case-insensitive collision guard**: If `basket_name.upper()` matches any existing column, skip injection and log warning. Prevents basket "SPY" from overwriting the real SPY column.
- **Best-effort everywhere**: If user resolution fails, basket computation fails, or any basket errors — skip silently. Factor analysis should never fail because of a basket issue.
- **`include_baskets=True` by default**: Transparent inclusion. Set `False` for pure factor analysis. Missing user context → graceful fallback to no baskets.
- **Empty baskets**: No baskets → empty dict → no injection → behavior identical to today
- **Cache fingerprint**: Uses `(user_id, name, updated_at)` tuples for content-aware invalidation. Basket renames, ticker changes, and weight changes all produce different fingerprints.
- **Performance**: Each basket requires a `get_returns_dataframe()` call (FMP fetch, ~500ms each). With 2-3 baskets this adds ~1-2s. Acceptable for an analysis tool that already takes several seconds. Future optimization: union-fetch all basket tickers in one call.
- **Returns mode (`analysis_type="returns"`)**: `analyze_returns()` derives its own start date from trailing windows (e.g., "1y" = 12 months back from end). Basket series should be fetched with a wide enough window to cover the longest trailing window. Use the panel's `attrs['start_date']` after panel construction, or fetch 3 years (the default) and let downstream windowing trim as needed.
- **Label→column mapping for Sharpe enrichment**: Recommendation Sharpe lookup keys by display label. The basket_overlay matrix uses display labels (`"Basket: tech_leaders"`). The Sharpe enrichment step in `recommend_offsets()` looks up performance profiles by label — ensure the profile dict is keyed by the same display label used in the matrix, OR maintain a `label_to_column` reverse map for lookup.
- **Fingerprint on failure**: Return the DB-derived fingerprint even when all basket computations fail (empty series dict but valid fingerprint). This prevents transient failures from collapsing into the same cache key as "no baskets" users.

## Reference Files

- `services/factor_intelligence_service.py:225` — `_panel()` (injection point for extra_returns)
- `services/factor_intelligence_service.py:264` — `analyze_correlations()` (thread extra_returns, add basket overlay)
- `services/factor_intelligence_service.py:735` — `recommend_offsets()` (thread extra_returns)
- `services/factor_intelligence_service.py:927` — `recommend_portfolio_offsets()` (thread extra_returns to inner recommend_offsets call at line 1056)
- `services/factor_intelligence_service.py:77` — `_resolve_dates()` (use for date alignment)
- `core/factor_intelligence.py:790` — `compute_per_category_correlation_matrices()` (add basket overlay logic)
- `core/factor_intelligence.py:896` — generic category loop (context — baskets would be skipped here with < 2 items)
- `core/factor_intelligence.py:1312` — `compute_factor_performance_profiles()` (add basket branch at line 1328)
- `core/factor_intelligence.py:631` — `build_factor_returns_panel()` (context — not modified)
- `mcp_tools/factor_intelligence.py:155` — `get_factor_analysis()` (add include_baskets + user_email)
- `mcp_tools/factor_intelligence.py:507` — `get_factor_recommendations()` (add include_baskets)
- `mcp_tools/baskets.py:393` — `_resolve_weights()` (reuse for basket return computation)
- `mcp_tools/baskets.py:48` — `_resolve_user_and_id()` (reuse pattern for user resolution)
- `portfolio_risk_engine/portfolio_risk.py:459` — `get_returns_dataframe()` (compute basket component returns)
- `portfolio_risk_engine/portfolio_risk.py:101` — `compute_portfolio_returns()` (aggregate to basket series)
- `inputs/database_client.py:1868` — `get_user_factor_groups(user_id)` (load all user baskets, includes updated_at)
- `mcp_server.py` — tool registration wrappers (add include_baskets parameter)

## Verification

1. `python3 -c "from mcp_tools.factor_intelligence import get_factor_analysis"` — imports cleanly
2. Create a test basket with 4 tickers, run `get_factor_analysis(analysis_type="correlations", format="agent", include_baskets=True)` — basket appears in correlation matrix under `user_baskets` category
3. Run `get_factor_analysis(analysis_type="performance", format="agent", include_baskets=True)` — basket appears in performance table with return/Sharpe/drawdown
4. Run `get_factor_recommendations(mode="single", overexposed_factor="Technology", include_baskets=True)` — baskets appear as potential hedge candidates
5. Run with `include_baskets=False` — baskets do not appear (regression check)
6. Run with user who has no baskets — identical to current behavior
7. Verify basket columns appear in `attrs['categories']` as `'user_baskets'` and in correlation output under `basket_overlay` matrix key
8. Verify cache fingerprint: modify a basket (update tickers/weights), re-run — results should reflect the change (not stale cached)
