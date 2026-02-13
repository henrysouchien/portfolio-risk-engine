# Factor Intelligence MCP Tools - Implementation Plan

> **Status:** IN PROGRESS

## Overview

Expose the Factor Intelligence Engine via 2 MCP tools on the `portfolio-mcp` server, following existing tool patterns (`analyze_stock`, `get_risk_analysis`).

The backend is fully implemented: `FactorIntelligenceService` has 4 analysis methods, 4 result objects with `to_api_response()` and `to_cli_report()`, and FastAPI routes already prove the data flow.

## Tools

### Tool 1: `get_factor_analysis`

**Purpose:** Market-wide factor intelligence — correlation matrices, sensitivity overlays, and factor performance profiles.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `analysis_type` | `Literal["correlations", "performance"]` | `"correlations"` | Which analysis to run |
| `start_date` | `Optional[str]` | `None` | YYYY-MM-DD start date |
| `end_date` | `Optional[str]` | `None` | YYYY-MM-DD end date |
| `categories` | `Optional[list[str]]` | `None` | Factor categories to include (e.g., `["industry", "style"]`). Default: all |
| `include_rate_sensitivity` | `bool` | `True` | Include rate sensitivity overlay (correlations only) |
| `include_market_sensitivity` | `bool` | `True` | Include market sensitivity overlay (correlations only) |
| `include_macro_composite` | `bool` | `True` | Include macro composite matrix (correlations only) |
| `industry_granularity` | `Literal["group", "industry"]` | `"group"` | Industry grouping level |
| `benchmark_ticker` | `str` | `"SPY"` | Benchmark for performance analysis (performance only) |
| `format` | `Literal["full", "summary", "report"]` | `"summary"` | Output format |
| `use_cache` | `bool` | `True` | Use cached results |

**Flow:**
1. Redirect stdout to stderr
2. Instantiate `FactorIntelligenceService(cache_results=use_cache)`
3. Branch on `analysis_type`:
   - `"correlations"` → call `service.analyze_correlations(...)` → `FactorCorrelationResult`
   - `"performance"` → call `service.analyze_performance(...)` → `FactorPerformanceResult`
4. Format response:
   - `"summary"` → extract key metrics (see below)
   - `"full"` → `result.to_api_response()` + `status: "success"`
   - `"report"` → `result.to_cli_report()` + `status: "success"`
5. Catch exceptions → `{"status": "error", "error": str(e)}`

**Summary format for correlations:**
```python
{
    "status": "success",
    "analysis_type": "correlations",
    "categories_analyzed": ["industry", "style", "market", ...],
    "matrix_sizes": {"industry": [11, 11], "style": [4, 4], ...},
    "overlays_included": ["rate_sensitivity", "market_sensitivity", "macro_composite"],
    "data_quality": {<category>: {"coverage_pct": float, "excluded": [...]}},
    "analysis_period": {"start_date": "2019-01-01", "end_date": "2024-12-31"},
    "total_corr_ms": 1234
}
```

**Summary format for performance:**
```python
{
    "status": "success",
    "analysis_type": "performance",
    "top_factors_by_sharpe": [
        {"ticker": "XLK", "sharpe_ratio": 1.2, "annual_return": 0.18, "volatility": 0.15},
        ...  # top 5
    ],
    "macro_composites": {...},  # composites.macro sub-dict from API response
    "category_composites": {...},  # composites.categories sub-dict from API response
    "factors_analyzed": 25,
    "analysis_period": {"start_date": "2019-01-01", "end_date": "2024-12-31"},
    "factor_performance_ms": 567
}
```

### Tool 2: `get_factor_recommendations`

**Purpose:** Factor-based offset/hedge recommendations — either for a single overexposed factor or portfolio-aware.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | `Literal["single", "portfolio"]` | `"single"` | Recommendation mode |
| `overexposed_factor` | `Optional[str]` | `None` | Factor to hedge (required for single mode, e.g., "Real Estate", "Technology") |
| `start_date` | `Optional[str]` | `None` | YYYY-MM-DD start date |
| `end_date` | `Optional[str]` | `None` | YYYY-MM-DD end date |
| `correlation_threshold` | `float` | `-0.2` | Max correlation for hedge candidates |
| `max_recommendations` | `int` | `10` | Max recommendations to return |
| `industry_granularity` | `Literal["group", "industry"]` | `"group"` | Industry grouping level |
| `format` | `Literal["full", "summary", "report"]` | `"summary"` | Output format |
| `use_cache` | `bool` | `True` | Use cached results |

**Flow:**
1. Redirect stdout to stderr
2. Branch on `mode`:
   - `"single"`:
     - Validate `overexposed_factor` is provided
     - Instantiate `FactorIntelligenceService(cache_results=use_cache)`
     - Call `service.recommend_offsets(overexposed_label=overexposed_factor, ...)`
     - Returns `OffsetRecommendationResult`
   - `"portfolio"`:
     - Load positions via `PositionService` (same pattern as `_load_portfolio_for_analysis`)
     - Compute weights from position market values: `{ticker: value / total_value}`
     - Instantiate `FactorIntelligenceService(cache_results=use_cache)`
     - Call `service.recommend_portfolio_offsets(weights=weights, ...)`
     - Returns `PortfolioOffsetRecommendationResult`
3. Format response (summary/full/report)
4. Catch exceptions → error dict

**Summary format for single mode:**
```python
{
    "status": "success",
    "mode": "single",
    "overexposed_factor": "Real Estate",
    "recommendations": [
        {"ticker": "XLU", "correlation": -0.35, "sharpe_ratio": 0.7, "category": "industry"},
        ...  # top N (capped at max_recommendations)
    ],
    "recommendation_count": 8,
    "analysis_period": {"start_date": "2019-01-01", "end_date": "2024-12-31"}
}
```

**Summary format for portfolio mode:**
```python
{
    "status": "success",
    "mode": "portfolio",
    "risk_drivers": [
        {"label": "Technology", "weight_pct": 35.2},
        ...  # top drivers
    ],
    "recommendations": [
        {"ticker": "XLU", "category": "industry", "correlation": -0.3, "sharpe_ratio": 0.7, "suggested_weight": 0.05},
        ...  # top N (capped at max_recommendations total)
    ],
    "recommendation_count": 10,
    "analysis_period": {"start_date": "2019-01-01", "end_date": "2024-12-31"}
}
```

## Edge Cases

1. **Missing `overexposed_factor` in single mode**: Return `{"status": "error", "error": "overexposed_factor is required when mode='single'"}` immediately (pre-check before service call).

2. **Portfolio weight extraction**: Use `PositionService` to fetch live positions (each position has a `value` field with market value in USD). Compute weights as `value / total_value`. Filter out cash positions (`type == "cash"` or `ticker.startswith("CUR:")`). This avoids relying on `portfolio_data.get_weights()` which returns empty for brokerage data (shares/dollars format, no weight keys).

3. **Label not found in correlation matrix**: Service returns empty recommendations list — surface as `{"status": "success", ..., "recommendations": [], "recommendation_count": 0, "note": "No matching factor found for '<label>'. Try a different factor name or use industry_granularity='industry' for more granular matching."}`.

4. **Service exceptions**: All caught by outer try/except, returned as error dict.

5. **Correlation-only params passed to performance analysis_type**: Ignored silently (not passed to `analyze_performance()`).

## Files to Create/Modify

### New File
1. **`mcp_tools/factor_intelligence.py`** — Tool implementations (`get_factor_analysis`, `get_factor_recommendations`)

### Modified Files
2. **`mcp_server.py`** — Import + 2 `@mcp.tool()` registrations
3. **`mcp_tools/__init__.py`** — Import + export
4. **`mcp_tools/README.md`** — Document new tools, mark FactorIntelligenceService as done

## Implementation Details

### `mcp_tools/factor_intelligence.py`

```python
"""
MCP Tools: get_factor_analysis, get_factor_recommendations

Exposes factor intelligence (correlations, performance, offset recommendations)
as MCP tools for AI invocation.

Usage (from Claude):
    "Show me factor correlations" -> get_factor_analysis()
    "Factor performance analysis" -> get_factor_analysis(analysis_type="performance")
    "What hedges real estate exposure?" -> get_factor_recommendations(overexposed_factor="Real Estate")
    "Recommend portfolio hedges" -> get_factor_recommendations(mode="portfolio")
"""

import sys
from typing import Optional, Literal, Dict

from services.factor_intelligence_service import FactorIntelligenceService


def get_factor_analysis(
    analysis_type: Literal["correlations", "performance"] = "correlations",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    categories: Optional[list[str]] = None,
    include_rate_sensitivity: bool = True,
    include_market_sensitivity: bool = True,
    include_macro_composite: bool = True,
    industry_granularity: Literal["group", "industry"] = "group",
    benchmark_ticker: str = "SPY",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Analyze factor correlations and performance across asset classes.

    Args:
        analysis_type: "correlations" or "performance"
        start_date: Analysis start date (YYYY-MM-DD, optional)
        end_date: Analysis end date (YYYY-MM-DD, optional)
        categories: Factor categories to analyze (e.g., ["industry", "style"])
        include_rate_sensitivity: Include rate sensitivity overlay (correlations only)
        include_market_sensitivity: Include market sensitivity overlay (correlations only)
        include_macro_composite: Include macro composite matrix (correlations only)
        industry_granularity: "group" or "industry"
        benchmark_ticker: Benchmark for performance (performance only, default "SPY")
        format: "summary", "full", or "report"
        use_cache: Use cached results (default True)

    Returns:
        dict with status field ("success" or "error")
    """
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        service = FactorIntelligenceService(cache_results=use_cache)

        if analysis_type == "correlations":
            result = service.analyze_correlations(
                start_date=start_date,
                end_date=end_date,
                categories=categories,
                include_rate_sensitivity=include_rate_sensitivity,
                include_market_sensitivity=include_market_sensitivity,
                include_macro_composite=include_macro_composite,
                industry_granularity=industry_granularity,
            )

            if format == "summary":
                api = result.to_api_response()
                matrices = api.get("matrices", {})
                overlays = api.get("overlays", {})
                overlays_included = [k for k, v in overlays.items() if v]
                matrix_sizes = {}
                for cat, mat in matrices.items():
                    if isinstance(mat, dict):
                        keys = list(mat.keys())
                        matrix_sizes[cat] = [len(keys), len(keys)]

                metadata = api.get("analysis_metadata", {})
                return {
                    "status": "success",
                    "analysis_type": "correlations",
                    "categories_analyzed": list(matrices.keys()),
                    "matrix_sizes": matrix_sizes,
                    "overlays_included": overlays_included,
                    "data_quality": api.get("data_quality", {}),
                    "analysis_period": {
                        "start_date": metadata.get("start_date"),
                        "end_date": metadata.get("end_date"),
                    },
                    "total_corr_ms": api.get("performance", {}).get("total_corr_ms", 0),
                }
            elif format == "full":
                response = result.to_api_response()
                response["status"] = "success"
                return response
            else:  # report
                return {
                    "status": "success",
                    "analysis_type": "correlations",
                    "report": result.to_cli_report(),
                }

        else:  # performance
            result = service.analyze_performance(
                start_date=start_date,
                end_date=end_date,
                benchmark_ticker=benchmark_ticker,
                factor_categories=categories,
                industry_granularity=industry_granularity,
            )

            if format == "summary":
                api = result.to_api_response()
                per_factor = api.get("per_factor", {})
                composites = api.get("composites", {})

                # Top 5 by Sharpe
                factor_list = []
                for ticker, metrics in per_factor.items():
                    if isinstance(metrics, dict):
                        factor_list.append({
                            "ticker": ticker,
                            "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                            "annual_return": metrics.get("annual_return", 0),
                            "volatility": metrics.get("volatility", 0),
                        })
                factor_list.sort(key=lambda x: x.get("sharpe_ratio", 0), reverse=True)

                metadata = api.get("analysis_metadata", {})
                perf = api.get("performance", {})
                return {
                    "status": "success",
                    "analysis_type": "performance",
                    "top_factors_by_sharpe": factor_list[:5],
                    "macro_composites": composites.get("macro", {}),
                    "category_composites": composites.get("categories", {}),
                    "factors_analyzed": len(per_factor),
                    "analysis_period": {
                        "start_date": metadata.get("start_date"),
                        "end_date": metadata.get("end_date"),
                    },
                    "factor_performance_ms": perf.get("factor_performance_ms", 0),
                }
            elif format == "full":
                response = result.to_api_response()
                response["status"] = "success"
                return response
            else:  # report
                return {
                    "status": "success",
                    "analysis_type": "performance",
                    "report": result.to_cli_report(),
                }

    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved


def _load_portfolio_weights(user_email: Optional[str], use_cache: bool) -> Dict[str, float]:
    """
    Load portfolio weights from live brokerage positions.

    Fetches positions via PositionService and computes weights from market values.
    Excludes cash positions (CUR:* tickers and type=="cash").

    Returns:
        Dict[str, float]: {ticker: weight} where weights sum to ~1.0

    Raises:
        ValueError: If no user configured, no positions found, or all positions are cash.
    """
    from settings import get_default_user
    from services.position_service import PositionService

    user = user_email or get_default_user()
    if not user:
        raise ValueError("No user specified and RISK_MODULE_USER_EMAIL not configured")

    position_service = PositionService(user)
    position_result = position_service.get_all_positions(
        use_cache=use_cache,
        force_refresh=not use_cache,
        consolidate=True,
    )

    positions = position_result.data.positions
    if not positions:
        raise ValueError("No brokerage positions found. Connect a brokerage account first.")

    # Filter out cash positions and compute weights from market values
    equity_positions = [
        p for p in positions
        if p.get("type") != "cash" and not p["ticker"].startswith("CUR:")
    ]
    if not equity_positions:
        raise ValueError("No non-cash positions found for weight computation.")

    total_value = sum(abs(float(p["value"])) for p in equity_positions)
    if total_value <= 0:
        raise ValueError("Total position value is zero or negative.")

    weights = {}
    for p in equity_positions:
        val = float(p["value"])
        if val != 0:
            weights[p["ticker"]] = val / total_value

    return weights


def get_factor_recommendations(
    mode: Literal["single", "portfolio"] = "single",
    overexposed_factor: Optional[str] = None,
    user_email: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    correlation_threshold: float = -0.2,
    max_recommendations: int = 10,
    industry_granularity: Literal["group", "industry"] = "group",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Get factor-based hedge/offset recommendations.

    Args:
        mode: "single" (hedge one factor) or "portfolio" (portfolio-aware)
        overexposed_factor: Factor to hedge (required for single mode)
        user_email: User email (uses env var if not provided)
        start_date: Analysis start date (YYYY-MM-DD, optional)
        end_date: Analysis end date (YYYY-MM-DD, optional)
        correlation_threshold: Max correlation for hedge candidates (default -0.2)
        max_recommendations: Max recommendations to return (default 10)
        industry_granularity: "group" or "industry"
        format: "summary", "full", or "report"
        use_cache: Use cached results (default True)

    Returns:
        dict with status field ("success" or "error")
    """
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        service = FactorIntelligenceService(cache_results=use_cache)

        if mode == "single":
            if not overexposed_factor:
                return {
                    "status": "error",
                    "error": "overexposed_factor is required when mode='single'. "
                             "Provide the factor/industry to hedge (e.g., 'Real Estate', 'Technology')."
                }

            result = service.recommend_offsets(
                overexposed_label=overexposed_factor,
                start_date=start_date,
                end_date=end_date,
                correlation_threshold=correlation_threshold,
                max_recommendations=max_recommendations,
                industry_granularity=industry_granularity,
            )

            if format == "summary":
                api = result.to_api_response()
                recs = api.get("recommendations", [])
                metadata = api.get("analysis_metadata", {})
                summary = {
                    "status": "success",
                    "mode": "single",
                    "overexposed_factor": overexposed_factor,
                    "recommendations": recs[:max_recommendations],
                    "recommendation_count": len(recs),
                    "analysis_period": {
                        "start_date": metadata.get("start_date"),
                        "end_date": metadata.get("end_date"),
                    },
                }
                if not recs:
                    summary["note"] = (
                        f"No matching factor found for '{overexposed_factor}'. "
                        "Try a different factor name or use industry_granularity='industry' "
                        "for more granular matching."
                    )
                return summary
            elif format == "full":
                response = result.to_api_response()
                response["status"] = "success"
                return response
            else:  # report
                return {
                    "status": "success",
                    "mode": "single",
                    "report": result.to_cli_report(),
                }

        else:  # portfolio mode
            # Load weights directly from positions (not via _load_portfolio_for_analysis)
            weights = _load_portfolio_weights(user_email, use_cache)

            result = service.recommend_portfolio_offsets(
                weights=weights,
                start_date=start_date,
                end_date=end_date,
                correlation_threshold=correlation_threshold,
                max_recs_per_driver=max_recommendations,
                industry_granularity=industry_granularity,
            )

            if format == "summary":
                api = result.to_api_response()
                drivers = api.get("drivers", [])
                all_recs = api.get("recommendations", [])
                # Cap total recommendations (service returns max_recs_per_driver
                # which can exceed max_recommendations total)
                recs = all_recs[:max_recommendations]
                metadata = api.get("analysis_metadata", {})
                return {
                    "status": "success",
                    "mode": "portfolio",
                    "risk_drivers": drivers,
                    "recommendations": recs,
                    "recommendation_count": len(recs),
                    "analysis_period": {
                        "start_date": metadata.get("start_date"),
                        "end_date": metadata.get("end_date"),
                    },
                }
            elif format == "full":
                response = result.to_api_response()
                response["status"] = "success"
                return response
            else:  # report
                return {
                    "status": "success",
                    "mode": "portfolio",
                    "report": result.to_cli_report(),
                }

    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved
```

### `mcp_server.py` additions

```python
# Add imports (at top, within stdout redirect block)
from mcp_tools.factor_intelligence import get_factor_analysis as _get_factor_analysis
from mcp_tools.factor_intelligence import get_factor_recommendations as _get_factor_recommendations

# Add tool registrations (after run_whatif)

@mcp.tool()
def get_factor_analysis(
    analysis_type: Literal["correlations", "performance"] = "correlations",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    categories: Optional[list[str]] = None,
    include_rate_sensitivity: bool = True,
    include_market_sensitivity: bool = True,
    include_macro_composite: bool = True,
    industry_granularity: Literal["group", "industry"] = "group",
    benchmark_ticker: str = "SPY",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Analyze factor correlations and performance across asset classes.

    Provides market-wide factor intelligence: correlation matrices between
    factor proxies (industry ETFs, style factors, bonds, commodities),
    sensitivity overlays (rate and market betas), and factor performance
    profiles (Sharpe, volatility, returns).

    Args:
        analysis_type: Type of analysis:
            - "correlations": Factor-to-factor correlation matrices with
              rate/market sensitivity overlays and macro composite view
            - "performance": Factor risk/return profiles with Sharpe ratios,
              volatility, and composite performance across macro groups
        start_date: Analysis start date in YYYY-MM-DD format (optional).
        end_date: Analysis end date in YYYY-MM-DD format (optional).
        categories: Factor categories to analyze (e.g., ["industry", "style",
            "market", "bond", "commodity"]). Default: all available.
        include_rate_sensitivity: Include rate sensitivity overlay showing
            ETF correlations with yield changes (correlations only, default: True).
        include_market_sensitivity: Include market sensitivity overlay showing
            ETF betas to benchmarks (correlations only, default: True).
        include_macro_composite: Include macro composite matrix showing
            cross-asset-class correlations (correlations only, default: True).
        industry_granularity: Industry grouping level:
            - "group": Aggregate by sector group (defensive, cyclical, etc.)
            - "industry": Show individual industries
        benchmark_ticker: Benchmark for performance comparison (performance
            only, default: "SPY").
        format: Output format:
            - "summary": Key metrics (categories, matrix sizes, top factors)
            - "full": Complete analysis with all matrices and metrics
            - "report": Human-readable formatted report
        use_cache: Use cached results when available (default: True).

    Returns:
        Factor analysis data with status field ("success" or "error").

    Examples:
        "Show me factor correlations" -> get_factor_analysis()
        "How do industry factors correlate?" -> get_factor_analysis(categories=["industry"])
        "Factor performance analysis" -> get_factor_analysis(analysis_type="performance")
        "Which factors have the best Sharpe?" -> get_factor_analysis(analysis_type="performance")
        "Full correlation report" -> get_factor_analysis(format="report")
    """
    return _get_factor_analysis(
        analysis_type=analysis_type,
        start_date=start_date,
        end_date=end_date,
        categories=categories,
        include_rate_sensitivity=include_rate_sensitivity,
        include_market_sensitivity=include_market_sensitivity,
        include_macro_composite=include_macro_composite,
        industry_granularity=industry_granularity,
        benchmark_ticker=benchmark_ticker,
        format=format,
        use_cache=use_cache,
    )


@mcp.tool()
def get_factor_recommendations(
    mode: Literal["single", "portfolio"] = "single",
    overexposed_factor: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    correlation_threshold: float = -0.2,
    max_recommendations: int = 10,
    industry_granularity: Literal["group", "industry"] = "group",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Get factor-based hedge/offset recommendations.

    Recommends factors that offset (hedge) specific overexposures using
    correlation analysis and risk/return profiles. Two modes:

    - "single": Find hedges for a specific factor (e.g., "Real Estate is
      overexposed, what offsets it?")
    - "portfolio": Detect portfolio risk drivers and recommend hedges based
      on current brokerage positions

    Args:
        mode: Recommendation mode:
            - "single": Hedge a specific overexposed factor
            - "portfolio": Portfolio-aware recommendations based on positions
        overexposed_factor: The factor/industry to hedge (required for single
            mode). Examples: "Real Estate", "Technology", "Financials".
        start_date: Analysis start date in YYYY-MM-DD format (optional).
        end_date: Analysis end date in YYYY-MM-DD format (optional).
        correlation_threshold: Maximum correlation for hedge candidates.
            More negative = stronger hedge requirement (default: -0.2).
        max_recommendations: Maximum recommendations to return (default: 10).
        industry_granularity: Industry grouping level:
            - "group": Match by sector group (defensive, cyclical, etc.)
            - "industry": Match by individual industry
        format: Output format:
            - "summary": Top recommendations with correlation and Sharpe
            - "full": Complete analysis with all fields
            - "report": Human-readable formatted report
        use_cache: Use cached results when available (default: True).

    Returns:
        Offset recommendations with status field ("success" or "error").

    Examples:
        "What hedges real estate exposure?" -> get_factor_recommendations(overexposed_factor="Real Estate")
        "Find hedges for technology" -> get_factor_recommendations(overexposed_factor="Technology")
        "Recommend portfolio hedges" -> get_factor_recommendations(mode="portfolio")
        "What should I add to reduce risk?" -> get_factor_recommendations(mode="portfolio")
    """
    return _get_factor_recommendations(
        mode=mode,
        overexposed_factor=overexposed_factor,
        user_email=None,  # Uses RISK_MODULE_USER_EMAIL from env
        start_date=start_date,
        end_date=end_date,
        correlation_threshold=correlation_threshold,
        max_recommendations=max_recommendations,
        industry_granularity=industry_granularity,
        format=format,
        use_cache=use_cache,
    )
```

### `mcp_tools/__init__.py` additions

```python
# Add import
from mcp_tools.factor_intelligence import get_factor_analysis, get_factor_recommendations

# Add to __all__
"get_factor_analysis",
"get_factor_recommendations",
```

### `mcp_tools/README.md` updates

- Add `get_factor_analysis` and `get_factor_recommendations` to tool list with parameters, examples
- Update services table to mark `FactorIntelligenceService` as `✅ Done`
- Add `factor_intelligence.py` to file organization listing

## Verification Steps

1. **Import test**: `from mcp_tools.factor_intelligence import get_factor_analysis, get_factor_recommendations` — no import errors
2. **Correlations summary**: `get_factor_analysis(format="summary")` → status: success, categories listed
3. **Correlations full**: `get_factor_analysis(format="full")` → status: success, matrices present
4. **Correlations report**: `get_factor_analysis(format="report")` → status: success, report string
5. **Performance summary**: `get_factor_analysis(analysis_type="performance", format="summary")` → top factors listed
6. **Performance full/report**: same pattern
7. **Single recommendation**: `get_factor_recommendations(overexposed_factor="Real Estate")` → recommendations list
8. **Single recommendation missing param**: `get_factor_recommendations()` → status: error (overexposed_factor required)
9. **Portfolio recommendation**: `get_factor_recommendations(mode="portfolio")` → drivers + recommendations
10. **Error case**: `get_factor_analysis(start_date="invalid")` → status: error with message

## Patterns Followed

| Pattern | Implementation |
|---------|---------------|
| stdout redirection | `sys.stdout = sys.stderr` in try/finally |
| Error handling | `try/except → {"status": "error", "error": str(e)}` |
| Format switching | summary/full/report consistent structure |
| Tool registration | `@mcp.tool()` in `mcp_server.py` with full docstrings |
| Exports | `mcp_tools/__init__.py` imports + `__all__` |
| No user context for standalone | `get_factor_analysis` — like `analyze_stock`, no user needed |
| User context for portfolio | `get_factor_recommendations(mode="portfolio")` — `_load_portfolio_weights()` helper uses `PositionService` directly to get market values and compute weights |

---

*Created: 2026-02-07*
