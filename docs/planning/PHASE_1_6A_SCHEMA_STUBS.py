"""
Phase 1.6A Schema Stubs - Risk Module OpenAPI 3 Migration
Generated from comprehensive analysis of CLI reports and API JSON payloads

These stubs represent recommended Marshmallow schema structures based on:
- /docs/schema_samples/cli/*.txt (human-readable reports)
- /docs/schema_samples/api/*.json (machine-readable payloads)

Priority: PerformanceResult, RiskScoreResult, RiskAnalysisResult
"""

from marshmallow import Schema, fields, validate
from typing import Dict, List, Optional


# =============================================================================
# TIER 1 COMPONENT SCHEMAS (High Priority - Immediate Implementation)
# =============================================================================

class AnalysisPeriodSchema(Schema):
    """
    Used in: PerformanceResult, StockAnalysisResult, RiskAnalysisResult
    Represents date range and duration of analysis
    """
    start_date = fields.Date(required=True, description="Analysis start date (YYYY-MM-DD)")
    end_date = fields.Date(required=True, description="Analysis end date (YYYY-MM-DD)")
    total_months = fields.Integer(required=True, validate=validate.Range(min=1, max=1200))
    years = fields.Float(required=True, validate=validate.Range(min=0.01, max=100.0))


class FactorBetasSchema(Schema):
    """
    Used in: RiskScoreResult, RiskAnalysisResult, OptimizationResult
    Factor exposure measurements
    """
    market = fields.Float(required=True, validate=validate.Range(min=-5.0, max=5.0))
    momentum = fields.Float(required=True, validate=validate.Range(min=-5.0, max=5.0))
    value = fields.Float(required=True, validate=validate.Range(min=-5.0, max=5.0))
    industry = fields.Float(required=True, validate=validate.Range(min=-5.0, max=5.0))
    subindustry = fields.Float(required=True, validate=validate.Range(min=-5.0, max=5.0))


class RiskCheckSchema(Schema):
    """
    Used in: OptimizationResult, RiskScoreResult
    Individual risk constraint validation
    """
    metric = fields.String(required=True, validate=validate.Length(min=1))
    actual = fields.Float(required=True)
    limit = fields.Float(required=True)
    pass_check = fields.Boolean(required=True, data_key="pass")
    buffer = fields.Float(allow_none=True, description="Distance to limit")


class PortfolioMetadataSchema(Schema):
    """
    Used in: PerformanceResult, RiskScoreResult, RiskAnalysisResult
    Standard portfolio identification information
    """
    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    source = fields.String(required=True, validate=validate.OneOf(["database", "file", "upload"]))
    user_id = fields.Integer(required=True, validate=validate.Range(min=1))
    analyzed_at = fields.DateTime(required=True, description="Analysis timestamp (ISO 8601)")


# =============================================================================
# TIER 2 COMPONENT SCHEMAS (Secondary Priority)
# =============================================================================

class ReturnsSchema(Schema):
    """
    Used in: PerformanceResult
    Return performance metrics
    """
    total_return = fields.Float(required=True, description="Total cumulative return (decimal)")
    annualized_return = fields.Float(required=True, description="Annualized return (decimal)")
    best_month = fields.Float(required=True, description="Best monthly return (decimal)")
    worst_month = fields.Float(required=True, description="Worst monthly return (decimal)")
    win_rate = fields.Float(required=True, validate=validate.Range(min=0.0, max=100.0))
    positive_months = fields.Integer(required=True, validate=validate.Range(min=0))
    negative_months = fields.Integer(required=True, validate=validate.Range(min=0))


class RiskMetricsSchema(Schema):
    """
    Used in: PerformanceResult, StockAnalysisResult
    Risk measurement standardization
    """
    volatility = fields.Float(required=True, validate=validate.Range(min=0.0, max=10.0),
                             description="Annualized volatility (decimal)")
    maximum_drawdown = fields.Float(required=True, validate=validate.Range(min=-1.0, max=0.0),
                                   description="Maximum drawdown (decimal)")
    downside_deviation = fields.Float(required=True, validate=validate.Range(min=0.0, max=10.0))
    tracking_error = fields.Float(required=True, validate=validate.Range(min=0.0, max=10.0))


class BenchmarkAnalysisSchema(Schema):
    """
    Used in: PerformanceResult
    Benchmark comparison metrics
    """
    alpha_annual = fields.Float(required=True, description="Annual alpha vs benchmark (decimal)")
    benchmark_ticker = fields.String(required=True, validate=validate.Length(min=1, max=10))
    beta = fields.Float(required=True, validate=validate.Range(min=-5.0, max=5.0))
    excess_return = fields.Float(required=True, description="Excess return vs benchmark (decimal)")
    r_squared = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))


class MonthlyStatsSchema(Schema):
    """
    Used in: PerformanceResult
    Monthly performance statistics
    """
    average_monthly_return = fields.Float(required=True, description="Average monthly return (decimal)")
    average_win = fields.Float(required=True, description="Average winning month (decimal)")
    average_loss = fields.Float(required=True, description="Average losing month (decimal)")
    win_loss_ratio = fields.Float(required=True, validate=validate.Range(min=0.0))


class RiskAdjustedReturnsSchema(Schema):
    """
    Used in: PerformanceResult
    Risk-adjusted performance metrics
    """
    sharpe_ratio = fields.Float(required=True, validate=validate.Range(min=-10.0, max=10.0))
    sortino_ratio = fields.Float(required=True, validate=validate.Range(min=-10.0, max=10.0))
    information_ratio = fields.Float(required=True, validate=validate.Range(min=-10.0, max=10.0))
    calmar_ratio = fields.Float(required=True, validate=validate.Range(min=-10.0, max=10.0))


# =============================================================================
# MAIN RESULT SCHEMAS
# =============================================================================

class PerformanceResultSchema(Schema):
    """
    Main performance analysis result schema
    Priority: HIGH - Core functionality, high complexity
    """
    # Standard response fields
    success = fields.Boolean(required=True)
    
    # Portfolio identification
    portfolio_metadata = fields.Nested(PortfolioMetadataSchema, required=True)
    
    # Main performance data
    benchmark = fields.String(required=True, validate=validate.Length(min=1, max=10))
    analysis_date = fields.DateTime(required=True, description="Analysis timestamp (ISO 8601)")
    analysis_period = fields.Nested(AnalysisPeriodSchema, required=True)
    
    # Core metrics
    returns = fields.Nested(ReturnsSchema, required=True)
    risk_metrics = fields.Nested(RiskMetricsSchema, required=True)
    risk_adjusted_returns = fields.Nested(RiskAdjustedReturnsSchema, required=True)
    benchmark_analysis = fields.Nested(BenchmarkAnalysisSchema, required=True)
    monthly_stats = fields.Nested(MonthlyStatsSchema, required=True)
    
    # Time series data
    monthly_returns = fields.Dict(keys=fields.Date(), values=fields.Float(), required=True,
                                 description="Monthly returns time series (date -> decimal return)")
    
    # Metadata
    risk_free_rate = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))
    performance_category = fields.String(required=True, 
                                       validate=validate.OneOf(["excellent", "good", "fair", "poor"]))
    portfolio_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    position_count = fields.Integer(required=True, validate=validate.Range(min=0))
    
    # Insights and formatting
    key_insights = fields.List(fields.String(), required=True)
    enhanced_key_insights = fields.List(fields.String(), allow_none=True)
    formatted_report = fields.String(required=True, description="CLI formatted output")
    
    # Summary for quick access
    summary = fields.Dict(required=True, description="Key metrics summary")


class RiskScoreComponentSchema(Schema):
    """
    Individual risk component scores
    """
    factor_risk = fields.Integer(required=True, validate=validate.Range(min=0, max=100))
    concentration_risk = fields.Integer(required=True, validate=validate.Range(min=0, max=100))
    volatility_risk = fields.Integer(required=True, validate=validate.Range(min=0, max=100))
    sector_risk = fields.Integer(required=True, validate=validate.Range(min=0, max=100))


class PotentialLossesSchema(Schema):
    """
    Potential loss estimates by risk category
    """
    max_loss_limit = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))
    factor_risk = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))
    concentration_risk = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))
    volatility_risk = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))
    sector_risk = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))


class RiskScoreDetailsSchema(Schema):
    """
    Additional risk scoring details
    """
    leverage_ratio = fields.Float(required=True, validate=validate.Range(min=0.0, max=10.0))
    max_loss_limit = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))
    excess_ratios = fields.Dict(required=True, description="Risk excess ratios")


class RiskScoreInterpretationSchema(Schema):
    """
    Human-readable risk interpretation
    """
    summary = fields.String(required=True, validate=validate.Length(min=1, max=500))
    details = fields.List(fields.String(), required=True)


class RiskScoreSchema(Schema):
    """
    Main risk score container
    """
    score = fields.Float(required=True, validate=validate.Range(min=0.0, max=100.0))
    category = fields.String(required=True, validate=validate.OneOf(["Excellent", "Good", "Fair", "Poor"]))
    component_scores = fields.Nested(RiskScoreComponentSchema, required=True)
    potential_losses = fields.Nested(PotentialLossesSchema, required=True)
    details = fields.Nested(RiskScoreDetailsSchema, required=True)
    interpretation = fields.Nested(RiskScoreInterpretationSchema, required=True)
    recommendations = fields.List(fields.String(), required=True)
    risk_factors = fields.List(fields.String(), required=True)


class AllocationSchema(Schema):
    """
    Position allocation data
    """
    portfolio_weight = fields.Float(required=True, validate=validate.Range(min=-1.0, max=1.0),
                                   data_key="Portfolio Weight")
    equal_weight = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0),
                               data_key="Equal Weight")
    eq_diff = fields.Float(required=True, validate=validate.Range(min=-1.0, max=1.0),
                          data_key="Eq Diff")


class VarianceDecompositionSchema(Schema):
    """
    Portfolio risk decomposition
    """
    portfolio_variance = fields.Float(required=True, validate=validate.Range(min=0.0))
    factor_variance = fields.Float(required=True, validate=validate.Range(min=0.0))
    idiosyncratic_variance = fields.Float(required=True, validate=validate.Range(min=0.0))
    factor_pct = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))
    idiosyncratic_pct = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))


class LimitViolationsSchema(Schema):
    """
    Risk limit violation counts
    """
    total = fields.Integer(required=True, validate=validate.Range(min=0))
    factor_betas = fields.Integer(required=True, validate=validate.Range(min=0))
    concentration = fields.Integer(required=True, validate=validate.Range(min=0))
    volatility = fields.Integer(required=True, validate=validate.Range(min=0))
    variance_contributions = fields.Integer(required=True, validate=validate.Range(min=0))
    leverage = fields.Integer(required=True, validate=validate.Range(min=0))


class LimitsAnalysisSchema(Schema):
    """
    Risk limits analysis container
    """
    limit_violations = fields.Nested(LimitViolationsSchema, required=True)
    risk_factors = fields.List(fields.String(), required=True)
    recommendations = fields.List(fields.String(), required=True)


class RiskScoreResultSchema(Schema):
    """
    Main risk score result schema
    Priority: HIGH - Critical business logic, complex nested structures
    """
    # Standard response fields
    success = fields.Boolean(required=True)
    
    # Portfolio identification
    portfolio_metadata = fields.Nested(PortfolioMetadataSchema, required=True)
    
    # Core risk scoring
    analysis_date = fields.DateTime(required=True, description="Analysis timestamp (ISO 8601)")
    portfolio_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    risk_score = fields.Nested(RiskScoreSchema, required=True)
    
    # Detailed analysis
    limits_analysis = fields.Nested(LimitsAnalysisSchema, required=True)
    portfolio_analysis = fields.Dict(required=True, description="Detailed portfolio analysis")
    
    # Risk limits metadata
    risk_limits_metadata = fields.Dict(allow_none=True, description="Risk limits configuration")
    risk_limits_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    
    # Priority actions and risk factors
    priority_actions = fields.List(fields.String(), required=True)
    risk_factors_with_priority = fields.List(fields.Dict(), required=True)
    
    # Violation details
    violation_details = fields.Dict(required=True, description="Detailed violation breakdown")
    violations_summary = fields.Dict(required=True, description="Violation summary statistics")
    suggested_limits = fields.Dict(required=True, description="Recommended limit adjustments")
    
    # Output formatting
    formatted_report = fields.String(required=True, description="CLI formatted output")
    
    # Summary
    summary = fields.Dict(required=True, description="Risk score summary")


class BetaCheckSchema(Schema):
    """
    Factor beta limit validation
    """
    factor = fields.String(required=True, validate=validate.Length(min=1, max=50))
    portfolio_beta = fields.Float(required=True, validate=validate.Range(min=-10.0, max=10.0))
    max_allowed_beta = fields.Float(required=True, validate=validate.Range(min=0.0, max=10.0))
    buffer = fields.Float(required=True, description="Distance to limit (can be negative)")
    pass_check = fields.Boolean(required=True, data_key="pass")


class RiskAnalysisResultSchema(Schema):
    """
    Comprehensive risk analysis result schema
    Priority: HIGH - Complex analytics, multiple data matrices
    """
    # Standard response fields
    success = fields.Boolean(required=True)
    
    # Portfolio identification
    portfolio_metadata = fields.Nested(PortfolioMetadataSchema, required=True)
    
    # Main risk analysis container
    risk_results = fields.Dict(required=True, description="Complete risk analysis data")
    
    # Core components that should be extracted to structured fields
    analysis_date = fields.DateTime(required=True, description="Analysis timestamp (ISO 8601)")
    allocations = fields.Dict(required=True, description="Portfolio allocation breakdown")
    portfolio_factor_betas = fields.Nested(FactorBetasSchema, required=True)
    
    # Risk analysis
    beta_checks = fields.List(fields.Nested(BetaCheckSchema), required=True)
    variance_decomposition = fields.Nested(VarianceDecompositionSchema, required=True)
    
    # Portfolio metrics
    herfindahl = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0),
                             description="Concentration measure")
    volatility_annual = fields.Float(required=True, validate=validate.Range(min=0.0, max=10.0))
    volatility_monthly = fields.Float(required=True, validate=validate.Range(min=0.0, max=10.0))
    
    # Large data structures (candidates for lazy loading)
    correlation_matrix = fields.Dict(allow_none=True, description="Asset correlation matrix")
    covariance_matrix = fields.Dict(allow_none=True, description="Asset covariance matrix")
    risk_contributions = fields.Dict(required=True, description="Risk contribution by asset")
    
    # Factor analysis
    factor_proxies = fields.Dict(required=True, description="Factor proxy mappings")
    df_stock_betas = fields.Dict(required=True, description="Individual stock factor betas")
    
    # Additional analysis
    expected_returns = fields.Dict(allow_none=True, description="Expected returns (optional)")


# =============================================================================
# EXAMPLE USAGE AND VALIDATION
# =============================================================================

def validate_performance_result(data: Dict) -> Dict:
    """
    Example validation function for PerformanceResult
    """
    schema = PerformanceResultSchema()
    try:
        result = schema.load(data)
        return {"valid": True, "data": result, "errors": None}
    except Exception as e:
        return {"valid": False, "data": None, "errors": str(e)}


def create_performance_result_stub() -> Dict:
    """
    Create a minimal valid PerformanceResult for testing
    """
    return {
        "success": True,
        "portfolio_metadata": {
            "name": "TEST_PORTFOLIO",
            "source": "database",
            "user_id": 1,
            "analyzed_at": "2025-08-09T17:11:11.374719"
        },
        "benchmark": "SPY",
        "analysis_date": "2025-08-09T17:11:11.374719",
        "analysis_period": {
            "start_date": "2019-01-31",
            "end_date": "2025-06-27",
            "total_months": 61,
            "years": 5.08
        },
        "returns": {
            "total_return": 2.2207,
            "annualized_return": 0.2587,
            "best_month": 0.1775,
            "worst_month": -0.1033,
            "win_rate": 63.9,
            "positive_months": 39,
            "negative_months": 22
        },
        "risk_metrics": {
            "volatility": 0.2004,
            "maximum_drawdown": -0.2262,
            "downside_deviation": 0.1759,
            "tracking_error": 0.0866
        },
        "risk_adjusted_returns": {
            "sharpe_ratio": 1.158,
            "sortino_ratio": 1.32,
            "information_ratio": 1.273,
            "calmar_ratio": 1.144
        },
        "benchmark_analysis": {
            "alpha_annual": 0.0848,
            "benchmark_ticker": "SPY",
            "beta": 1.118,
            "excess_return": 0.1103,
            "r_squared": 0.822
        },
        "monthly_stats": {
            "average_monthly_return": 0.021,
            "average_win": 0.056,
            "average_loss": -0.041,
            "win_loss_ratio": 1.36
        },
        "monthly_returns": {
            "2020-06-30": 0.025,
            "2020-07-31": 0.0881
        },
        "risk_free_rate": 0.0265,
        "performance_category": "good",
        "portfolio_name": "TEST_PORTFOLIO",
        "position_count": 14,
        "key_insights": [
            "Strong alpha generation (+8.5% vs benchmark)",
            "High volatility (20.0% vs 16.3% benchmark)"
        ],
        "formatted_report": "Performance Analysis - TEST_PORTFOLIO",
        "summary": {
            "analysis_years": 5.08,
            "annualized_return": 0.2587,
            "max_drawdown": -0.2262,
            "sharpe_ratio": 1.158
        }
    }


if __name__ == "__main__":
    # Example validation test
    stub_data = create_performance_result_stub()
    result = validate_performance_result(stub_data)
    print(f"Validation result: {result['valid']}")
    if not result['valid']:
        print(f"Errors: {result['errors']}")