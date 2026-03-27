# Hedge Tool Volatility Source Alignment

## Context

The hedge tool's portfolio volatility (6.7%) doesn't match the overview (7.5%). Two different methods:

- **Overview** (`build_portfolio_view`): `vol_a = vol_m * sqrt(12)` from covariance matrix — direct `w'Σw` computation on actual returns
- **Hedge tool**: `sqrt(portfolio_variance)` from variance decomposition — factor model approximation (`Σ(w²β²σ²) + Σ(w²σ²_idio)`)

The factor model is an approximation that misses residual cross-asset correlations not explained by shared factors, causing the ~0.8pp gap. The covariance-based value is more accurate and is what the user sees everywhere else.

## Fix

**File**: `services/factor_intelligence_service.py`, lines 1645-1650

Replace the current `sqrt(portfolio_variance)` derivation with a preference chain:

1. `view.get("volatility_annual")` — available when `build_portfolio_view()` was called (path 2, no `analysis_result`)
2. `getattr(analysis_result, "volatility_annual", None)` — available when `analysis_result` is passed from `get_risk_analysis` (path 1)
3. `sqrt(portfolio_variance)` — fallback for tests or edge cases where neither is available

**Current code** (lines 1645-1650):
```python
portfolio_variance = (view.get("variance_decomposition") or {}).get("portfolio_variance")
annual_vol = (
    round(float(np.sqrt(portfolio_variance)), 4)
    if portfolio_variance is not None and float(portfolio_variance) > 0
    else None
)
```

**New code**:
```python
# Prefer covariance-based vol (matches overview/risk analysis) over factor-model
# approximation from variance decomposition
annual_vol = None
_cov_vol = view.get("volatility_annual")
if _cov_vol is None and analysis_result is not None:
    _cov_vol = getattr(analysis_result, "volatility_annual", None)
if _cov_vol is not None:
    try:
        annual_vol = round(float(_cov_vol), 4)
    except (TypeError, ValueError):
        pass
if annual_vol is None:
    portfolio_variance = (view.get("variance_decomposition") or {}).get("portfolio_variance")
    if portfolio_variance is not None and float(portfolio_variance) > 0:
        annual_vol = round(float(np.sqrt(portfolio_variance)), 4)
```

Logging threshold stays at `> 2.0` (200% decimal).

## Test impact

- Existing test `test_recommend_portfolio_offsets_reuses_analysis_result_without_building_view`: its `analysis_result` SimpleNamespace has no `volatility_annual` → falls through to `sqrt(0.04) = 0.2` → no change in behavior
- Add a new test: `analysis_result` with `volatility_annual=0.075` → verify that value is used instead of sqrt(variance_decomposition)

## Files

| File | Change |
|------|--------|
| `services/factor_intelligence_service.py` | Lines 1645-1650: preference chain |
| `tests/services/test_factor_intelligence_service.py` | New test for volatility_annual preference |

## Verification

1. `pytest tests/services/test_factor_intelligence_service.py tests/core/test_factor_recs_agent_snapshot.py -x -q`
2. MCP: `get_factor_recommendations(mode="portfolio", format="full")` → check `annual_volatility` matches overview's value (~7.5%)
