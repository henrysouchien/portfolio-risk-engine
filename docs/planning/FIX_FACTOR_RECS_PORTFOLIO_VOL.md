# Fix: `portfolio_volatility` and `annual_volatility` null in `get_factor_recommendations`

## Context

The `get_factor_recommendations` MCP tool returns `portfolio_volatility: null` and `annual_volatility: null` in its diagnosis and analysis_metadata, even though portfolio variance IS computed correctly (0.004472). The vol fields exist in the response but are never populated.

Codex recently landed a commit (HEAD) that added `portfolio_name` support and `load_portfolio_recommendation_context()` to wire the `analysis_result` path. That change is good but doesn't fix the root cause — the view dict omission.

## Root Cause

**File:** `services/factor_intelligence_service.py`, `recommend_portfolio_offsets()` method

When `analysis_result` is non-None, the code builds a `view` dict (line ~1466-1472) that omits `volatility_annual`:

```python
if analysis_result is not None:
    view = {
        "industry_variance": analysis_result.industry_variance or {},
        "portfolio_factor_betas": analysis_result.portfolio_factor_betas,
        "portfolio_returns": analysis_result.portfolio_returns,
        "variance_decomposition": analysis_result.variance_decomposition or {},
        # volatility_annual is MISSING
    }
```

Later (line ~1712), `view.get("volatility_annual")` returns `None`. There is a `getattr` fallback at line ~1714 that reads from `analysis_result` directly — this works but is fragile and wasn't working before Codex's change because `analysis_result` was always `None` in the MCP path.

The else branch (when `analysis_result` is None) calls `build_portfolio_view()` which correctly includes `volatility_annual`. So Path B works; Path A has the gap.

## Two code paths

| Path | When | `volatility_annual` in view? | Vol populated? |
|------|------|------------------------------|----------------|
| A: `analysis_result` non-None | User resolves, context loads | NO (missing from view dict) | Only via getattr fallback |
| B: `analysis_result` is None | No user or context fails | YES (from `build_portfolio_view()`) | Yes |

## Fix

**File:** `services/factor_intelligence_service.py`

Add `volatility_annual` to the view dict when `analysis_result` is provided. Use direct attribute access — `volatility_annual` is a non-optional `float` field on `RiskAnalysisResult` (defined in `core/result_objects/risk.py` line 110). If it's missing, we want a clear `AttributeError`, not a silent `None`.

```python
if analysis_result is not None:
    view = {
        "industry_variance": analysis_result.industry_variance or {},
        "portfolio_factor_betas": analysis_result.portfolio_factor_betas,
        "portfolio_returns": analysis_result.portfolio_returns,
        "variance_decomposition": analysis_result.variance_decomposition or {},
        "volatility_annual": analysis_result.volatility_annual,  # <-- ADD
    }
```

This is the only code change needed. Path B already works correctly.

## Key references

- `services/factor_intelligence_service.py` — `recommend_portfolio_offsets()`, view dict at ~1466, vol lookup at ~1710
- `core/result_objects/risk.py:110` — `volatility_annual: float` (non-optional dataclass field)
- `portfolio_risk_engine/portfolio_risk.py:2023` — `build_portfolio_view()` returns `volatility_annual`
- `core/result_objects/factor_intelligence.py:1078` — `PortfolioOffsetRecommendationResult` carries `diagnosis.portfolio_volatility` and `analysis_metadata.annual_volatility`

## Verification

1. Restart the portfolio-mcp service (not just MCP reconnect — the Python process must restart to load new code)
2. Call `get_factor_recommendations` with `mode="portfolio"`, `format="full"`
3. Confirm `diagnosis.portfolio_volatility` and `analysis_metadata.annual_volatility` are non-null floats
4. Expected vol: ~23% annualized (sqrt(0.004472) * sqrt(12) ≈ 0.232)
