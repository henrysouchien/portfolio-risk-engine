"""
Schema Stubs - Risk Module API Phase 1.6A
==========================================

Example Marshmallow component schemas based on comprehensive field analysis.
These stubs demonstrate recommended structure and reusable components.

Usage:
    from schemas.components import PerformanceResultSchema
    
    # Deserialize API response
    schema = PerformanceResultSchema()
    result = schema.load(api_response_json)
    
    # Serialize for API response  
    response_data = schema.dump(performance_analysis_object)
"""

from marshmallow import Schema, fields, validates_schema, ValidationError, INCLUDE
from typing import Dict, Any


# ============================================================================
# COMPONENT SCHEMAS (Reusable across multiple result objects)
# ============================================================================

class PortfolioMetadataSchema(Schema):
    """Portfolio identification metadata - reused across all result objects."""
    analyzed_at = fields.DateTime(required=True, format='iso8601')
    name = fields.String(required=True, validate=validate.Length(min=1))
    source = fields.String(required=True, validate=validate.OneOf(['database', 'file', 'api']))
    user_id = fields.Integer(required=True, validate=validate.Range(min=1))


class AnalysisPeriodSchema(Schema):
    """Date range and duration information for time-series analyses."""
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    total_months = fields.Integer(required=True, validate=validate.Range(min=1))
    years = fields.Float(required=True, validate=validate.Range(min=0))


class FactorBetaSchema(Schema):
    """Factor exposure coefficients - common across risk analyses."""
    market = fields.Float(required=True)
    momentum = fields.Float(required=True)
    value = fields.Float(required=True)
    industry = fields.Float(required=True)
    subindustry = fields.Float(required=True)


class BetaCheckSchema(Schema):
    """Factor beta limit validation results."""
    factor = fields.String(required=True)
    portfolio_beta = fields.Float(required=True)
    max_allowed_beta = fields.Float(required=True)
    pass_ = fields.Boolean(data_key='pass', required=True)
    buffer = fields.Float(required=True)
    index = fields.Integer(required=False)  # Implementation detail - consider removing


class SummaryMetricsSchema(Schema):
    """High-level portfolio metrics summary."""
    analysis_years = fields.Float(required=False, allow_none=True)
    annualized_return = fields.Float(required=True)
    volatility = fields.Float(required=True, validate=validate.Range(min=0))
    max_drawdown = fields.Float(required=True, validate=validate.Range(max=0))
    sharpe_ratio = fields.Float(required=True)
    total_return = fields.Float(required=True)
    win_rate = fields.Float(required=False, validate=validate.Range(min=0, max=100))


# ============================================================================
# PERFORMANCE RESULT SCHEMAS
# ============================================================================

class BenchmarkAnalysisSchema(Schema):
    """Benchmark comparison metrics (alpha, beta, R-squared)."""
    alpha_annual = fields.Float(required=True)
    benchmark_ticker = fields.String(required=True, validate=validate.Length(min=1))
    beta = fields.Float(required=True)
    excess_return = fields.Float(required=True)
    r_squared = fields.Float(required=True, validate=validate.Range(min=0, max=1))


class BenchmarkComparisonSchema(Schema):
    """Side-by-side portfolio vs benchmark metrics."""
    portfolio_return = fields.Float(required=True)
    portfolio_volatility = fields.Float(required=True, validate=validate.Range(min=0))
    portfolio_sharpe = fields.Float(required=True)
    benchmark_return = fields.Float(required=True)
    benchmark_volatility = fields.Float(required=True, validate=validate.Range(min=0))
    benchmark_sharpe = fields.Float(required=True)


class ReturnsSchema(Schema):
    """Return metrics and statistics."""
    annualized_return = fields.Float(required=True)
    total_return = fields.Float(required=True)
    best_month = fields.Float(required=True)
    worst_month = fields.Float(required=True)
    win_rate = fields.Float(required=True, validate=validate.Range(min=0, max=100))
    positive_months = fields.Integer(required=True, validate=validate.Range(min=0))
    negative_months = fields.Integer(required=True, validate=validate.Range(min=0))


class RiskMetricsSchema(Schema):
    """Risk and volatility measurements."""
    volatility = fields.Float(required=True, validate=validate.Range(min=0))
    maximum_drawdown = fields.Float(required=True, validate=validate.Range(max=0))
    downside_deviation = fields.Float(required=True, validate=validate.Range(min=0))
    tracking_error = fields.Float(required=True, validate=validate.Range(min=0))


class RiskAdjustedReturnsSchema(Schema):
    """Risk-adjusted performance ratios."""
    sharpe_ratio = fields.Float(required=True)
    sortino_ratio = fields.Float(required=True)
    information_ratio = fields.Float(required=True)
    calmar_ratio = fields.Float(required=True)


class MonthlyStatsSchema(Schema):
    """Monthly return statistics."""
    average_monthly_return = fields.Float(required=True)
    average_win = fields.Float(required=True)
    average_loss = fields.Float(required=True)
    win_loss_ratio = fields.Float(required=True, validate=validate.Range(min=0))


class PerformanceMetricsSchema(Schema):
    """Core performance analysis data structure."""
    analysis_date = fields.DateTime(required=True, format='iso8601')
    analysis_period = fields.Nested(AnalysisPeriodSchema, required=True)
    portfolio_name = fields.String(required=True)
    
    # Performance metrics groups
    returns = fields.Nested(ReturnsSchema, required=True)
    risk_metrics = fields.Nested(RiskMetricsSchema, required=True)
    risk_adjusted_returns = fields.Nested(RiskAdjustedReturnsSchema, required=True)
    monthly_stats = fields.Nested(MonthlyStatsSchema, required=True)
    
    # Benchmark analysis
    benchmark_analysis = fields.Nested(BenchmarkAnalysisSchema, required=True)
    benchmark_comparison = fields.Nested(BenchmarkComparisonSchema, required=True)
    
    # Historical data
    monthly_returns = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    
    # Market data
    risk_free_rate = fields.Float(required=True, validate=validate.Range(min=0))
    
    # TODO: Remove in Phase 1.6C - redundant with structured data
    formatted_report = fields.String(required=False)


class PerformanceResultSchema(Schema):
    """Complete PerformanceResult API response schema."""
    success = fields.Boolean(required=True)
    benchmark = fields.String(required=True, validate=validate.Length(min=1))
    
    performance_metrics = fields.Nested(PerformanceMetricsSchema, required=True)
    portfolio_metadata = fields.Nested(PortfolioMetadataSchema, required=True)
    summary = fields.Nested(SummaryMetricsSchema, required=True)
    
    # TODO: Remove in Phase 1.6C - redundant with structured data  
    formatted_report = fields.String(required=False)


# ============================================================================
# RISK SCORE RESULT SCHEMAS
# ============================================================================

class ComponentScoresSchema(Schema):
    """Individual risk component scoring."""
    factor_risk = fields.Integer(required=True, validate=validate.Range(min=0, max=100))
    concentration_risk = fields.Integer(required=True, validate=validate.Range(min=0, max=100))
    volatility_risk = fields.Integer(required=True, validate=validate.Range(min=0, max=100))
    sector_risk = fields.Integer(required=True, validate=validate.Range(min=0, max=100))


class RiskScoreDetailsSchema(Schema):
    """Detailed risk score calculations."""
    max_loss_limit = fields.Float(required=True, validate=validate.Range(min=0, max=1))
    leverage_ratio = fields.Float(required=True, validate=validate.Range(min=0))
    excess_ratios = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)


class RiskScoreInterpretationSchema(Schema):
    """Human-readable risk score interpretation."""
    summary = fields.String(required=True)
    details = fields.List(fields.String(), required=True)


class PotentialLossesSchema(Schema):
    """Potential loss calculations by risk type."""
    max_loss_limit = fields.Float(required=True, validate=validate.Range(min=0, max=1))
    factor_risk = fields.Float(required=True, validate=validate.Range(min=0))
    concentration_risk = fields.Float(required=True, validate=validate.Range(min=0))
    volatility_risk = fields.Float(required=True, validate=validate.Range(min=0))
    sector_risk = fields.Float(required=True, validate=validate.Range(min=0))


class RiskScoreSchema(Schema):
    """Risk scoring results and interpretation."""
    score = fields.Float(required=True, validate=validate.Range(min=0, max=100))
    category = fields.String(required=True, validate=validate.OneOf(['Excellent', 'Good', 'Fair', 'Poor']))
    
    component_scores = fields.Nested(ComponentScoresSchema, required=True)
    details = fields.Nested(RiskScoreDetailsSchema, required=True)
    interpretation = fields.Nested(RiskScoreInterpretationSchema, required=True)
    potential_losses = fields.Nested(PotentialLossesSchema, required=True)
    
    recommendations = fields.List(fields.String(), required=True)
    risk_factors = fields.List(fields.String(), required=True)


class LimitViolationsSchema(Schema):
    """Risk limit violation counts by category."""
    factor_betas = fields.Integer(required=True, validate=validate.Range(min=0))
    concentration = fields.Integer(required=True, validate=validate.Range(min=0))
    volatility = fields.Integer(required=True, validate=validate.Range(min=0))
    variance_contributions = fields.Integer(required=True, validate=validate.Range(min=0))
    leverage = fields.Integer(required=True, validate=validate.Range(min=0))


class LimitsAnalysisSchema(Schema):
    """Risk limit analysis and recommendations."""
    limit_violations = fields.Nested(LimitViolationsSchema, required=True)
    recommendations = fields.List(fields.String(), required=True)
    risk_factors = fields.List(fields.String(), required=True)


class RiskScoreResultSchema(Schema):
    """Complete RiskScoreResult API response schema."""
    success = fields.Boolean(required=True)
    analysis_date = fields.DateTime(required=True, format='iso8601')
    
    risk_score = fields.Nested(RiskScoreSchema, required=True)
    limits_analysis = fields.Nested(LimitsAnalysisSchema, required=True)
    portfolio_metadata = fields.Nested(PortfolioMetadataSchema, required=True)
    
    # High-level summary
    summary = fields.Dict(keys=fields.String(), values=fields.Raw(), required=True)
    
    # TODO: Add portfolio_analysis nested structure (very large - consider separate schema)
    portfolio_analysis = fields.Dict(required=False)  # Placeholder for complex structure
    
    # TODO: Remove in Phase 1.6C - redundant with structured data
    formatted_report = fields.String(required=False)


# ============================================================================
# RISK ANALYSIS RESULT SCHEMAS  
# ============================================================================

class AllocationsSchema(Schema):
    """Portfolio weight analysis (Equal Weight, Portfolio Weight, differences)."""
    # Dynamic structure - asset names as keys
    # Consider using fields.Dict for flexibility or explicit asset list
    portfolio_weight = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    equal_weight = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    eq_diff = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)


class AssetVolatilitySummarySchema(Schema):
    """Per-asset volatility and variance metrics."""
    vol_a = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    idio_vol_a = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    weighted_vol_a = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    weighted_idio_vol_a = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    weighted_idio_var = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)


class AssetWeightsSchema(Schema):
    """Dynamic asset weight mappings."""
    
    class Meta:
        unknown = INCLUDE  # Allow dynamic ticker fields
    
    @validates_schema
    def validate_weights(self, data: Dict[str, Any], **kwargs):
        """Validate that all weight values are floats within reasonable range."""
        for ticker, weight in data.items():
            if not isinstance(weight, (int, float)):
                raise ValidationError(f"Weight for {ticker} must be a number, got {type(weight)}")
            if not -1.0 <= weight <= 1.0:
                raise ValidationError(f"Weight for {ticker} must be between -1.0 and 1.0, got {weight}")


class RiskCheckSchema(Schema):
    """Risk constraint validation."""
    metric = fields.String(required=True)
    actual = fields.Float(required=True)  # Standardized as number instead of "29.8%"
    limit = fields.Float(required=True)   # Standardized as number instead of "40.0%"
    pass_ = fields.Boolean(data_key='pass', required=True)  # Standardized as boolean


class VarianceDecompositionSchema(Schema):
    """Portfolio variance decomposition into factors and idiosyncratic components."""
    portfolio_variance = fields.Float(required=True, validate=validate.Range(min=0))
    factor_variance = fields.Float(required=True, validate=validate.Range(min=0))
    idiosyncratic_variance = fields.Float(required=True, validate=validate.Range(min=0))
    factor_pct = fields.Float(required=True, validate=validate.Range(min=0, max=1))
    idiosyncratic_pct = fields.Float(required=True, validate=validate.Range(min=0, max=1))
    
    # Factor breakdown
    factor_breakdown_var = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    factor_breakdown_pct = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)


class IndustryVarianceSchema(Schema):
    """Industry variance analysis and concentration."""
    absolute = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    percent_of_portfolio = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    per_industry_group_beta = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)


class RiskResultsSchema(Schema):
    """Complex risk analysis results structure."""
    analysis_date = fields.DateTime(required=True, format='iso8601')
    
    # Portfolio composition and weights
    allocations = fields.Nested(AllocationsSchema, required=True)
    
    # Volatility and risk metrics
    volatility_annual = fields.Float(required=True, validate=validate.Range(min=0))
    volatility_monthly = fields.Float(required=True, validate=validate.Range(min=0))
    herfindahl = fields.Float(required=True, validate=validate.Range(min=0, max=1))
    
    # Asset-level analysis
    asset_vol_summary = fields.Nested(AssetVolatilitySummarySchema, required=True)
    
    # Factor analysis
    portfolio_factor_betas = fields.Nested(FactorBetaSchema, required=True)
    df_stock_betas = fields.List(fields.Nested(FactorBetaSchema), required=True)
    beta_checks = fields.List(fields.Nested(BetaCheckSchema), required=True)
    
    # Risk decomposition
    variance_decomposition = fields.Nested(VarianceDecompositionSchema, required=True)
    industry_variance = fields.Nested(IndustryVarianceSchema, required=True)
    risk_contributions = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    euler_variance_pct = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    
    # Historical returns
    portfolio_returns = fields.Dict(keys=fields.String(), values=fields.Float(), required=True)
    
    # Matrix data (may be large - consider pagination)
    correlation_matrix = fields.List(fields.Dict(), required=False)
    covariance_matrix = fields.List(fields.Dict(), required=False)
    
    # Factor volatilities and weighted variances
    factor_vols = fields.List(fields.Dict(), required=True)
    weighted_factor_var = fields.List(fields.Dict(), required=True)


class RiskAnalysisResultSchema(Schema):
    """Complete RiskAnalysisResult API response schema."""
    portfolio_metadata = fields.Nested(PortfolioMetadataSchema, required=True)
    risk_results = fields.Nested(RiskResultsSchema, required=True)


# ============================================================================
# MISSING SCHEMAS (TODO: Implement in Phase 1.6B)
# ============================================================================

# =============================================================================
# MISSING SCHEMAS (TODO: Implement in Phase 1.6B)
# =============================================================================

class OptimizationMetadataSchema(Schema):
    """Optimization run metadata."""
    active_positions = fields.Integer(required=True)
    analysis_date = fields.DateTime(required=True, format='iso8601')
    expected_returns_used = fields.Dict(values=fields.Float(), required=True)
    optimization_type = fields.String(required=True)
    original_weights = fields.Dict(values=fields.Float(), required=True)
    portfolio_file = fields.String(required=True)
    total_positions = fields.Integer(required=True)


class OptimizationBetaAnalysisSchema(Schema):
    """Beta analysis for optimization results."""
    factor_beta_checks = fields.List(fields.Nested(BetaCheckSchema), required=True)
    factor_beta_passes = fields.Boolean(required=True)
    factor_beta_violations = fields.List(fields.Dict(), required=True)
    proxy_beta_checks = fields.List(fields.Dict(), required=True)
    proxy_beta_passes = fields.Boolean(required=True)
    proxy_beta_violations = fields.List(fields.Dict(), required=True)


class DirectOptimizationResultSchema(Schema):
    """Direct optimization API result."""
    data = fields.Dict(required=True)  # Contains analysis_type, beta_analysis, etc.
    endpoint = fields.String(required=True)
    success = fields.Boolean(required=True)
    summary = fields.Dict(required=True)
    error = fields.Nested('ErrorResponseSchema', required=False, allow_none=True)


class ComparisonRowSchema(Schema):
    """Before/after comparison row for what-if analysis."""
    max_beta = fields.Float(data_key='Max Beta', required=True)
    new = fields.Float(data_key='New', required=True)
    new_pass = fields.String(data_key='New Pass', required=True)  # TODO: Standardize to boolean
    old = fields.Float(data_key='Old', required=True)
    old_pass = fields.String(data_key='Old Pass', required=True)  # TODO: Standardize to boolean
    delta = fields.Float(data_key='Δ', required=True)


class DeltaChangeSchema(Schema):
    """Change metrics for what-if analysis."""
    base_volatility = fields.Float(required=True)
    scenario_volatility = fields.Float(required=True)
    volatility_delta = fields.Float(required=True)


class DirectWhatIfResultSchema(Schema):
    """Direct what-if API result."""
    data = fields.Dict(required=True)  # Contains analysis_type, comparison_analysis, etc.
    endpoint = fields.String(required=True)
    success = fields.Boolean(required=True)
    summary = fields.Dict(required=True)


# =============================================================================
# DIRECT API RESULT SCHEMAS
# =============================================================================

class StockRiskMetricsSchema(Schema):
    """Stock-specific risk metrics."""
    alpha = fields.Float(required=True)
    beta = fields.Float(required=True)
    idio_vol_m = fields.Float(required=True)  # Idiosyncratic volatility monthly
    r_squared = fields.Float(required=True)


class StockVolatilityMetricsSchema(Schema):
    """Stock volatility measurements."""
    annual_vol = fields.Float(required=True)
    monthly_vol = fields.Float(required=True)


class DirectStockDataSchema(Schema):
    """Direct stock analysis data container."""
    analysis_metadata = fields.Dict(required=True)
    analysis_period = fields.Nested(AnalysisPeriodSchema, required=True)
    analysis_type = fields.String(required=True)
    benchmark = fields.String(required=True)
    formatted_report = fields.String(required=True)
    risk_metrics = fields.Nested(StockRiskMetricsSchema, required=True)
    ticker = fields.String(required=True)
    volatility_metrics = fields.Nested(StockVolatilityMetricsSchema, required=True)
    raw_data = fields.Dict(required=True)


class DirectStockResultSchema(Schema):
    """Direct stock analysis API result."""
    data = fields.Nested(DirectStockDataSchema, required=True)
    endpoint = fields.String(required=True)
    success = fields.Boolean(required=True)
    summary = fields.Dict(required=True)


class DirectPortfolioDataSchema(Schema):
    """Direct portfolio analysis data container."""
    analysis_metadata = fields.Dict(required=True)
    analysis_type = fields.String(required=True)
    beta_analysis = fields.Dict(required=True)
    correlation_matrix = fields.Dict(required=True)
    covariance_matrix = fields.Dict(required=True)
    risk_analysis = fields.Dict(required=True)


class DirectPortfolioResultSchema(Schema):
    """Direct portfolio analysis API result."""
    data = fields.Nested(DirectPortfolioDataSchema, required=True)
    endpoint = fields.String(required=True)
    success = fields.Boolean(required=True)
    summary = fields.Dict(required=True)


# =============================================================================
# ERROR HANDLING SCHEMAS
# =============================================================================

class ErrorDetailsSchema(Schema):
    """Error detail information."""
    error_type = fields.String(required=True)


class ErrorResponseSchema(Schema):
    """Standardized error response."""
    code = fields.String(required=True)
    details = fields.Nested(ErrorDetailsSchema, required=True)
    message = fields.String(required=True)
    timestamp = fields.DateTime(required=True, format='iso8601')


class FailedApiResponseSchema(Schema):
    """Failed API response structure."""
    endpoint = fields.String(required=True)
    error = fields.Nested(ErrorResponseSchema, required=True)
    success = fields.Boolean(required=True, validate=lambda x: x is False)


# =============================================================================
# HEALTH CHECK SCHEMAS
# =============================================================================

class HealthCheckSchema(Schema):
    """System health check response."""
    google_oauth_configured = fields.Boolean(required=True)
    status = fields.String(required=True, validate=validate.OneOf(['healthy', 'unhealthy']))
    version = fields.String(required=True)


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def validate_percentage(value: float) -> bool:
    """Validate percentage values (can be negative for some metrics)."""
    return -100 <= value <= 1000  # Allow for leveraged portfolios


def validate_correlation(value: float) -> bool:
    """Validate correlation values."""
    return -1 <= value <= 1


def validate_beta(value: float) -> bool:
    """Validate beta values (can be negative)."""
    return -10 <= value <= 10  # Reasonable beta range


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

# =============================================================================
# EXAMPLE USAGE
# =============================================================================

def example_usage():
    """Demonstrate schema usage patterns."""
    
    # Example 1: Deserialize PerformanceResult from API
    performance_schema = PerformanceResultSchema()
    api_response = {
        "benchmark": "SPY",
        "formatted_report": "📊 PORTFOLIO PERFORMANCE...",
        "performance_metrics": {
            "analysis_date": "2025-08-05T21:12:35",
            "analysis_period": {
                "start_date": "2019-01-31",
                "end_date": "2025-06-27", 
                "total_months": 61,
                "years": 5.08
            },
            "returns": {
                "total_return": 221.76,
                "annualized_return": 25.85,
                "best_month": 17.76,
                "worst_month": -10.34,
                "win_rate": 63.9,
                "positive_months": 39,
                "negative_months": 22
            },
            # ... other required fields
        },
        # ... other required fields
    }
    
    try:
        result = performance_schema.load(api_response)
        print("✅ Performance result loaded successfully")
    except ValidationError as err:
        print(f"❌ Validation errors: {err.messages}")
    
    # Example 2: Component schema reuse
    metadata_schema = PortfolioMetadataSchema()
    metadata = {
        "analyzed_at": "2025-08-06T01:12:35+00:00",
        "name": "CURRENT_PORTFOLIO",
        "source": "database",
        "user_id": 1
    }
    
    try:
        validated_metadata = metadata_schema.load(metadata)
        print("✅ Portfolio metadata validated successfully")
    except ValidationError as err:
        print(f"❌ Metadata validation errors: {err.messages}")


if __name__ == "__main__":
    example_usage()
    
    print("\nSchema stubs loaded successfully!")
    print("Available schemas:")
    print("- PerformanceResultSchema")
    print("- RiskScoreResultSchema") 
    print("- RiskAnalysisResultSchema")
    print("- DirectStockResultSchema")
    print("- DirectPortfolioResultSchema")
    print("- Component schemas: PortfolioMetadataSchema, FactorBetaSchema, etc.")
    print("\nTODO: Complete DirectOptimizationResultSchema and DirectWhatIfResultSchema")


# =============================================================================
# MIGRATION NOTES
# =============================================================================

"""
Migration from Phase 1.5 to 1.6A:

1. BREAKING CHANGES:
   - Boolean fields: "PASS"/"FAIL" strings → true/false booleans
   - Percentage fields: "29.8%" strings → 29.8 numbers
   - DateTime fields: Multiple formats → consistent ISO 8601 with timezone

2. NEW COMPONENT SCHEMAS:
   - PortfolioMetadataSchema: Reuse across all result objects
   - AnalysisPeriodSchema: Reuse for time-series analysis
   - BetaCheckSchema: Reuse for factor constraint validation
   - RiskCheckSchema: Reuse for risk constraint validation

3. VALIDATION IMPROVEMENTS:
   - Asset weights validated within [-1.0, 1.0] range
   - Risk scores validated within [0, 100] range  
   - Required vs optional fields explicitly defined
   - Null handling for optional nested objects

4. RECOMMENDED USAGE:
   ```python
   # Import component schemas
   from schemas.components import (
       PerformanceResultSchema,
       RiskScoreResultSchema, 
       PortfolioMetadataSchema
   )
   
   # Use in API route handlers
   @app.route('/api/performance')
   def get_performance():
       result = analyze_performance(portfolio)
       schema = PerformanceResultSchema()
       return schema.dump(result)
   ```

5. TESTING STRATEGY:
   - Unit test each component schema independently
   - Integration test with actual API response samples
   - Validate round-trip serialization (object → JSON → object)
   - Test edge cases (null values, empty arrays, large numbers)
"""