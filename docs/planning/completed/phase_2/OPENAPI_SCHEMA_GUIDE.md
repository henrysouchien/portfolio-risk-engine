# OpenAPI Schema Guide

*Last Updated: 2025-08-05 - Phase 1.5 Direct* Result Objects*

---

## Overview

This guide documents the OpenAPI schema mapping patterns used in the Risk Module API, particularly focusing on result object serialization and schema design patterns.

## Result Object Schema Mapping

### Direct* Result Objects

The Direct* result objects provide schema-compliant serialization for OpenAPI documentation and type safety. Each result object follows a consistent pattern:

| Result Object | Schema | Endpoint | Purpose |
|---------------|--------|----------|---------|
| `DirectPortfolioResult` | `DirectPortfolioResultSchema` | `/direct/portfolio` | Portfolio risk analysis |
| `DirectStockResult` | `DirectStockResultSchema` | `/direct/stock` | Individual stock analysis |
| `DirectOptimizationResult` | `DirectOptimizationResultSchema` | `/direct/optimize/*` | Portfolio optimization |
| `DirectPerformanceResult` | `DirectPerformanceResultSchema` | `/direct/performance` | Performance analytics |
| `DirectWhatIfResult` | `DirectWhatIfResultSchema` | `/direct/what-if` | Scenario analysis |
| `DirectInterpretResult` | `DirectInterpretResultSchema` | `/direct/interpret` | AI interpretation |

### Service Layer Result Objects (Phase 1.5 Addition)

The service layer result objects provide schema-compliant serialization for authenticated API endpoints:

| Result Object | Schema | Endpoint | Purpose | Status |
|---------------|--------|----------|---------|---------|
| `RiskAnalysisResult` | `RiskAnalysisResultSchema` | `/api/analyze`, `/api/portfolio-analysis` | Comprehensive portfolio risk analysis | ✅ **Completed** |
| `PerformanceResult` | `PerformanceResultSchema` | `/api/performance` | Portfolio performance analysis | 🔄 In Progress |
| `InterpretationResult` | `InterpretationResultSchema` | `/api/interpret` | AI-generated portfolio interpretation | 🔄 In Progress |
| `StockAnalysisResult` | `StockAnalysisResultSchema` | `/api/stock` (planned) | Individual stock risk analysis | ✅ **Completed** |
| `WhatIfResult` | `WhatIfResultSchema` | `/api/what-if` (planned) | Scenario analysis comparison | 🔄 Planned |

### Schema Design Pattern

All Direct* schemas follow this structure:

```python
from marshmallow import Schema, fields

class Direct[Type]ResultSchema(Schema):
    analysis_type = fields.String()           # Always present
    [specific_fields] = fields.Dict()         # Type-specific structured fields
    # Raw output fields are included via **kwargs expansion
```

### Service Layer Schema Pattern

Service layer schemas use structured field definitions:

```python
from marshmallow import Schema, fields

class [Type]ResultSchema(Schema):
    # Core analysis fields with specific types
    analysis_date = fields.DateTime()         # ISO datetime string
    portfolio_name = fields.String()
    formatted_report = fields.String()       # Human-readable report
    
    # Type-specific structured fields
    [specific_fields] = fields.Dict()         # Structured data objects
    [other_fields] = fields.Float()           # Primitive types
```

#### RiskAnalysisResult Schema Example (Phase 1.5 Complete)

```python
from marshmallow import Schema, fields

class RiskAnalysisResultSchema(Schema):
    # Volatility metrics
    volatility_annual        = fields.Float()
    volatility_monthly       = fields.Float()
    herfindahl               = fields.Float()
    
    # Complex structured data (Dict fields for Phase 1.5 speed)
    portfolio_factor_betas   = fields.Dict()
    variance_decomposition   = fields.Dict()
    risk_contributions       = fields.Dict()
    df_stock_betas           = fields.Dict()
    covariance_matrix        = fields.Dict()
    correlation_matrix       = fields.Dict()
    allocations              = fields.Dict()
    factor_vols              = fields.Dict()
    weighted_factor_var      = fields.Dict()
    asset_vol_summary        = fields.Dict()
    portfolio_returns        = fields.Dict()
    euler_variance_pct       = fields.Dict()
    industry_variance        = fields.Dict()
    suggested_limits         = fields.Dict()
    risk_checks              = fields.Dict()
    beta_checks              = fields.Dict()
    max_betas                = fields.Dict()
    max_betas_by_proxy       = fields.Dict()
    
    # Standard result object fields
    analysis_date            = fields.DateTime()
    portfolio_name           = fields.String()
    formatted_report         = fields.String()
```

**Migration Pattern for Phase 1.5:**
- Uses permissive `Dict` fields for complex data structures
- Maintains 1:1 mapping with existing `to_dict()` output
- Ready for Phase 1.6 schema curation (nested schemas, validation)

### API Method Pattern - Direct* Result Objects

Each Direct* result object implements this method pattern:

```python
@dataclass
class Direct[Type]Result:
    """Result object for direct [type] analysis endpoints.
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization for OpenAPI endpoints
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): High-level summary for logging and debugging
    
    Schema: Direct[Type]ResultSchema (schemas.direct_[type]_result)
    """
    
    def to_api_response(self) -> Dict[str, Any]:
        """Schema-compliant version for OpenAPI endpoints."""
        return {
            "analysis_type": self.analysis_type,
            # ... type-specific fields ...
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED - Use to_api_response() instead."""
        import warnings
        warnings.warn("Direct[Type]Result.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
```

### API Method Pattern - Service Layer Result Objects (Phase 1.5)

Service layer result objects (like `RiskAnalysisResult`) implement the Phase 1.5 migration pattern:

```python
class RiskAnalysisResult:
    """Result object for comprehensive portfolio risk analysis.
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization (Phase 1.5+)
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): Structured summary for logging and UI
        to_formatted_report(): Human-readable report for Claude
    
    Schema: RiskAnalysisResultSchema (schemas.risk_analysis_result)
    """
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
        return {
            "volatility_annual": self.volatility_annual,
            "volatility_monthly": self.volatility_monthly,
            "herfindahl": self.herfindahl,
            "portfolio_factor_betas": _convert_to_json_serializable(self.portfolio_factor_betas),
            "variance_decomposition": _convert_to_json_serializable(self.variance_decomposition),
            # ... all 24 fields identical to old to_dict() ...
            "analysis_date": self.analysis_date.isoformat(),
            "portfolio_name": self.portfolio_name,
            "formatted_report": self.to_formatted_report()
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("RiskAnalysisResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()  # Delegate to new method
```

### Service Layer Method Pattern

Service layer result objects follow this enhanced pattern:

```python
@dataclass
class [Type]Result:
    """Service layer result object for [type] analysis.
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization for OpenAPI endpoints
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): High-level summary for dashboard/logging
        get_[specific]_metrics(): Domain-specific data accessors
        to_formatted_report(): Human-readable text report
    
    Schema: [Type]ResultSchema (schemas.[type]_result)
    """
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert [Type]Result to OpenAPI-compliant dictionary for API responses.
        
        This method provides schema-compliant serialization for OpenAPI documentation
        and API responses, replacing the deprecated to_dict() method. The output structure
        matches the [Type]ResultSchema defined in schemas/[type]_result.py.
        
        Returns:
            Dict[str, Any]: Serialized analysis data with proper typing
        """
        return {
            # Core metadata
            "analysis_date": self.analysis_date.isoformat(),
            "portfolio_name": self.portfolio_name,
            "formatted_report": self.to_formatted_report(),
            
            # Type-specific data fields
            # ... structured data objects ...
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response()."""
        import warnings
        warnings.warn(
            "[Type]Result.to_dict() is deprecated; use to_api_response()",
            DeprecationWarning, stacklevel=2
        )
        return self.to_api_response()
```

## Endpoint Decorator Pattern

OpenAPI endpoints use this decorator pattern:

```python
@openapi_bp.route("/direct/[endpoint]", methods=["POST"])
@openapi_bp.response(200, Direct[Type]ResultSchema)
def api_direct_[endpoint]():
    # ... endpoint logic ...
    result = Direct[Type]Result(raw_output=raw_result)
    return jsonify({
        'success': True,
        'data': result.to_api_response(),  # ← Schema-compliant method
        'summary': result.get_summary(),
        'endpoint': 'direct/[endpoint]'
    })
```

## Schema Examples

### DirectPortfolioResultSchema

```python
class DirectPortfolioResultSchema(Schema):
    analysis_type = fields.String()
    volatility_annual = fields.Float(allow_none=True)
    portfolio_factor_betas = fields.Dict()
    risk_contributions = fields.Dict()
    df_stock_betas = fields.Dict()
    covariance_matrix = fields.Dict()
```

**Example Response:**
```json
{
  "analysis_type": "portfolio",
  "volatility_annual": 0.1547,
  "portfolio_factor_betas": {"market": 0.89, "momentum": 0.12},
  "risk_contributions": {"AAPL": 0.25, "GOOGL": 0.18},
  "df_stock_betas": {"AAPL": {"market": 1.2}},
  "covariance_matrix": {...}
}
```

### DirectOptimizationResultSchema

```python
class DirectOptimizationResultSchema(Schema):
    analysis_type = fields.String()
    optimal_weights = fields.Dict()
    optimization_metrics = fields.Dict()
```

**Example Response:**
```json
{
  "analysis_type": "optimization",
  "optimal_weights": {"AAPL": 0.30, "GOOGL": 0.25, "MSFT": 0.45},
  "optimization_metrics": {
    "expected_return": 0.12,
    "volatility": 0.15,
    "sharpe_ratio": 0.8
  }
}
```

### StockAnalysisResultSchema (Service Layer)

```python
class StockAnalysisResultSchema(Schema):
    ticker = fields.String()
    volatility_metrics = fields.Dict()
    regression_metrics = fields.Dict()
    factor_summary = fields.Dict()
    risk_metrics = fields.Dict()
    analysis_date = fields.String()
```

**Example Response:**
```json
{
  "ticker": "AAPL",
  "volatility_metrics": {
    "monthly_vol": 0.045,
    "annual_vol": 0.156
  },
  "regression_metrics": {
    "beta": 1.15,
    "alpha": 0.025,
    "r_squared": 0.78,
    "idio_vol_m": 0.032
  },
  "factor_summary": {
    "growth": 1.35,
    "value": -0.12,
    "momentum": 0.85
  },
  "risk_metrics": {
    "systematic_risk": 0.124,
    "idiosyncratic_risk": 0.032
  },
  "analysis_date": "2025-08-05T12:00:00"
}
```

### PerformanceResultSchema (Service Layer)

```python
class PerformanceResultSchema(Schema):
    analysis_period = fields.Dict()
    returns = fields.Dict()
    risk_metrics = fields.Dict()
    risk_adjusted_returns = fields.Dict()
    benchmark_analysis = fields.Dict()
    benchmark_comparison = fields.Dict()
    monthly_stats = fields.Dict()
    risk_free_rate = fields.Float()
    monthly_returns = fields.Dict()
    analysis_date = fields.String()
    portfolio_name = fields.String(allow_none=True)
    formatted_report = fields.String()
```

**Example Response:**
```json
{
  "analysis_period": {
    "start_date": "2023-01-01",
    "end_date": "2023-12-31",
    "years": 1.0
  },
  "returns": {
    "total_return": 0.155,
    "annualized_return": 0.124,
    "win_rate": 0.58
  },
  "risk_metrics": {
    "volatility": 0.185,
    "maximum_drawdown": -0.125,
    "downside_deviation": 0.092,
    "tracking_error": 0.045
  },
  "risk_adjusted_returns": {
    "sharpe_ratio": 1.25,
    "sortino_ratio": 1.68,
    "information_ratio": 0.56,
    "calmar_ratio": 0.99
  },
  "benchmark_analysis": {
    "alpha": 0.025,
    "beta": 1.02,
    "correlation": 0.89
  },
  "benchmark_comparison": {
    "excess_return": 0.025,
    "outperformance_months": 7
  },
  "monthly_stats": {
    "positive_months": 7,
    "negative_months": 5,
    "best_month": 0.089,
    "worst_month": -0.067
  },
  "risk_free_rate": 0.02,
  "monthly_returns": {
    "2023-01": 0.035,
    "2023-02": -0.012,
    "2023-03": 0.048
  },
  "analysis_date": "2025-08-05T12:00:00",
  "portfolio_name": "CURRENT_PORTFOLIO",
  "formatted_report": "Performance Analysis - CURRENT_PORTFOLIO\nAnnualized Return: 12.40%\nVolatility: 18.50%\nSharpe Ratio: 1.250\nMax Drawdown: -12.50%"
}
```

### DirectInterpretResultSchema

```python
class DirectInterpretResultSchema(Schema):
    analysis_type = fields.String()
    ai_interpretation = fields.String()
    full_diagnostics = fields.String()
    analysis_metadata = fields.Dict()
```

**Example Response:**
```json
{
  "analysis_type": "interpret",
  "ai_interpretation": "Your portfolio shows strong tech concentration...",
  "full_diagnostics": "Technical analysis:\n- Beta: 1.2\n- Alpha: 0.03",
  "analysis_metadata": {
    "model_version": "claude-3.5",
    "analysis_timestamp": "2025-08-05T13:00:00Z"
  }
}
```

## Migration Notes

### Phase 1.5 Changes (Current)

- ✅ Added `to_api_response()` methods to all Direct* result objects
- ✅ Created corresponding Marshmallow schemas for Direct* objects
- ✅ Updated all direct endpoints to use OpenAPI decorators
- ✅ Added `to_api_response()` method to `PerformanceResult` (service layer)
- ✅ Created `PerformanceResultSchema` for authenticated endpoints
- ✅ Updated `/api/performance` endpoint to use new schema pattern
- ✅ Added `to_api_response()` method to `StockAnalysisResult` (service layer)
- ✅ Created `StockAnalysisResultSchema` for stock analysis endpoints
- ⚠️ Service layer `/api/stock` endpoint not yet implemented (StockService exists but no endpoint)
- ✅ Deprecated `to_dict()` methods with proper warnings (will be removed in Phase 2)

### Upcoming Phase 2 Changes

- 🔄 Remove deprecated `to_dict()` methods
- 🔄 Add request body schemas for POST endpoints
- 🔄 Implement error response schemas
- 🔄 Add validation decorators

### Best Practices

1. **Always use `to_api_response()`** for new endpoints
2. **Schema-first design**: Create schema before implementing endpoint logic
3. **Consistent field naming**: Use snake_case for API fields
4. **Proper type hints**: Include return type annotations
5. **Documentation**: Update docstrings when adding new methods

## Swagger UI Access

Once the application is running, access the interactive API documentation at:
- **Development**: http://localhost:5000/docs/
- **Production**: https://[your-domain]/docs/

## File Locations

- **Result Objects**: `core/result_objects.py`
- **Schemas**: `schemas/direct_*.py`
- **Schema Registry**: `schemas/__init__.py`
- **API Routes**: `routes/api.py`

---

*For implementation details, see the [OpenAPI Migration Plan](OPENAPI_MIGRATION_PLAN.md).*