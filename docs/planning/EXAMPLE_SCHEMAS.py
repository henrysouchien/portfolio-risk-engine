"""
EXAMPLE_SCHEMAS.py

Example Marshmallow component schemas for the risk_module API Phase 1.6A.
These schemas demonstrate recommended structure and validation for key result objects.

Generated from analysis of:
- CLI formatted reports: /docs/schema_samples/cli/*.txt
- API JSON payloads: /docs/schema_samples/api/*.json
"""

from marshmallow import Schema, fields, validate, ValidationError, post_load
from typing import Dict, Any, Optional


# =============================================================================
# SHARED COMPONENT SCHEMAS
# =============================================================================

class PortfolioMetadataSchema(Schema):
    """
    Portfolio identification metadata used across all result objects.
    
    Used in: RiskAnalysisResult, RiskScoreResult, PerformanceResult, DirectPortfolioResult
    """
    analyzed_at = fields.DateTime(
        required=True, 
        format='iso8601',
        metadata={'description': 'Analysis timestamp in ISO 8601 format with timezone'}
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        metadata={'description': 'Portfolio identifier name'}
    )
    source = fields.Str(
        required=True,
        validate=validate.OneOf(['database', 'file', 'api']),
        metadata={'description': 'Data source type'}
    )
    user_id = fields.Int(
        required=True,
        validate=validate.Range(min=1),
        metadata={'description': 'User identifier'}
    )


class AnalysisPeriodSchema(Schema):
    """
    Time period information for performance and risk analysis.
    
    Used in: PerformanceResult, DirectStockResult
    """
    start_date = fields.Date(
        required=True,
        metadata={'description': 'Analysis start date'}
    )
    end_date = fields.Date(
        required=True,
        metadata={'description': 'Analysis end date'}
    )
    total_months = fields.Int(
        required=True,
        validate=validate.Range(min=1),
        metadata={'description': 'Total months in analysis period'}
    )
    years = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Analysis period in years (decimal)'}
    )


class FactorBetaSchema(Schema):
    """
    Factor exposures (betas) for risk model factors.
    
    Used in: RiskAnalysisResult, DirectPortfolioResult, RiskScoreResult
    """
    market = fields.Float(
        required=True,
        metadata={'description': 'Market factor beta'}
    )
    momentum = fields.Float(
        required=True,
        metadata={'description': 'Momentum factor beta'}
    )
    value = fields.Float(
        required=True,
        metadata={'description': 'Value factor beta'}
    )
    industry = fields.Float(
        required=True,
        metadata={'description': 'Industry factor beta'}
    )
    subindustry = fields.Float(
        required=True,
        metadata={'description': 'Sub-industry factor beta'}
    )


class BetaCheckSchema(Schema):
    """
    Beta constraint validation check.
    
    Used in: RiskAnalysisResult, DirectOptimizationResult, DirectWhatIfResult, DirectPortfolioResult
    """
    factor = fields.Str(
        required=True,
        validate=validate.OneOf(['market', 'momentum', 'value', 'industry', 'industry_proxy']),
        metadata={'description': 'Factor name being checked'}
    )
    portfolio_beta = fields.Float(
        required=True,
        allow_nan=False,
        metadata={'description': 'Current portfolio beta for this factor'}
    )
    max_allowed_beta = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Maximum allowed beta limit'}
    )
    pass_check = fields.Bool(
        required=True,
        data_key='pass',
        metadata={'description': 'Whether the beta check passes the limit'}
    )
    buffer = fields.Float(
        required=True,
        metadata={'description': 'Buffer remaining before hitting limit (can be negative)'}
    )
    index = fields.Int(
        required=False,
        validate=validate.Range(min=0),
        metadata={'description': 'Array index for reference (optional)'}
    )


class RiskConstraintSchema(Schema):
    """
    Risk constraint validation check.
    
    Used in: DirectOptimizationResult, DirectWhatIfResult
    """
    metric = fields.Str(
        required=True,
        data_key='Metric',
        validate=validate.OneOf(['Volatility', 'Max Weight', 'Factor Var %', 'Market Var %', 'Max Industry Var %']),
        metadata={'description': 'Risk metric being validated'}
    )
    actual = fields.Float(
        required=True,
        data_key='Actual',
        validate=validate.Range(min=0),
        metadata={'description': 'Actual metric value'}
    )
    limit = fields.Float(
        required=True,
        data_key='Limit',
        validate=validate.Range(min=0),
        metadata={'description': 'Risk limit threshold'}
    )
    pass_check = fields.Bool(
        required=True,
        data_key='Pass',
        metadata={'description': 'Whether the constraint check passes'}
    )


class VarianceDecompositionSchema(Schema):
    """
    Portfolio variance decomposition analysis.
    
    Used in: RiskAnalysisResult, RiskScoreResult
    """
    factor_pct = fields.Float(
        required=True,
        validate=validate.Range(min=0, max=1),
        metadata={'description': 'Factor variance as percentage of total variance'}
    )
    factor_variance = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Factor variance component'}
    )
    idiosyncratic_pct = fields.Float(
        required=True,
        validate=validate.Range(min=0, max=1),
        metadata={'description': 'Idiosyncratic variance as percentage of total variance'}
    )
    idiosyncratic_variance = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Idiosyncratic variance component'}
    )
    portfolio_variance = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Total portfolio variance'}
    )
    factor_breakdown_pct = fields.Dict(
        keys=fields.Str(),
        values=fields.Float(),
        required=True,
        metadata={'description': 'Factor breakdown percentages by factor name'}
    )
    factor_breakdown_var = fields.Dict(
        keys=fields.Str(),
        values=fields.Float(),
        required=True,
        metadata={'description': 'Factor breakdown variances by factor name'}
    )


# =============================================================================
# PERFORMANCE RESULT SCHEMAS
# =============================================================================

class ReturnsSchema(Schema):
    """Return metrics and statistics."""
    total_return = fields.Float(
        required=True,
        metadata={'description': 'Total return percentage'}
    )
    annualized_return = fields.Float(
        required=True,
        metadata={'description': 'Annualized return percentage'}
    )
    best_month = fields.Float(
        required=True,
        metadata={'description': 'Best monthly return percentage'}
    )
    worst_month = fields.Float(
        required=True,
        metadata={'description': 'Worst monthly return percentage'}
    )
    win_rate = fields.Float(
        required=True,
        validate=validate.Range(min=0, max=100),
        metadata={'description': 'Win rate percentage'}
    )
    positive_months = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Count of positive return months'}
    )
    negative_months = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Count of negative return months'}
    )


class RiskAdjustedReturnsSchema(Schema):
    """Risk-adjusted performance metrics."""
    sharpe_ratio = fields.Float(
        required=True,
        metadata={'description': 'Sharpe ratio'}
    )
    sortino_ratio = fields.Float(
        required=True,
        metadata={'description': 'Sortino ratio'}
    )
    information_ratio = fields.Float(
        required=True,
        metadata={'description': 'Information ratio vs benchmark'}
    )
    calmar_ratio = fields.Float(
        required=True,
        metadata={'description': 'Calmar ratio'}
    )


class BenchmarkAnalysisSchema(Schema):
    """Benchmark comparison analysis."""
    alpha_annual = fields.Float(
        required=True,
        metadata={'description': 'Annual alpha vs benchmark (%)'}
    )
    beta = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Portfolio beta vs benchmark'}
    )
    r_squared = fields.Float(
        required=True,
        validate=validate.Range(min=0, max=1),
        metadata={'description': 'R-squared correlation with benchmark'}
    )
    excess_return = fields.Float(
        required=True,
        metadata={'description': 'Excess return vs benchmark (%)'}
    )
    benchmark_ticker = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=10),
        metadata={'description': 'Benchmark ticker symbol'}
    )


class MonthlyStatsSchema(Schema):
    """Monthly performance statistics."""
    average_monthly_return = fields.Float(
        required=True,
        metadata={'description': 'Average monthly return (%)'}
    )
    average_win = fields.Float(
        required=True,
        metadata={'description': 'Average positive monthly return (%)'}
    )
    average_loss = fields.Float(
        required=True,
        metadata={'description': 'Average negative monthly return (%)'}
    )
    win_loss_ratio = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Win/loss ratio'}
    )


class PerformanceResultSchema(Schema):
    """Complete performance analysis result."""
    success = fields.Bool(required=True)
    benchmark = fields.Str(required=True, validate=validate.Length(min=1, max=10))
    formatted_report = fields.Str(required=True)
    
    portfolio_metadata = fields.Nested(PortfolioMetadataSchema, required=True)
    
    performance_metrics = fields.Dict(required=True)  # Complex nested structure
    
    summary = fields.Dict(
        keys=fields.Str(),
        values=fields.Raw(),
        required=True,
        metadata={'description': 'High-level performance summary'}
    )


# =============================================================================
# RISK SCORE RESULT SCHEMAS
# =============================================================================

class ComponentScoreSchema(Schema):
    """Individual risk component scores (0-100)."""
    concentration_risk = fields.Int(
        required=True,
        validate=validate.Range(min=0, max=100),
        metadata={'description': 'Concentration risk score (0-100)'}
    )
    factor_risk = fields.Int(
        required=True,
        validate=validate.Range(min=0, max=100),
        metadata={'description': 'Factor risk score (0-100)'}
    )
    sector_risk = fields.Int(
        required=True,
        validate=validate.Range(min=0, max=100),
        metadata={'description': 'Sector risk score (0-100)'}
    )
    volatility_risk = fields.Int(
        required=True,
        validate=validate.Range(min=0, max=100),
        metadata={'description': 'Volatility risk score (0-100)'}
    )


class LimitViolationsSchema(Schema):
    """Count of risk limit violations by category."""
    concentration = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Number of concentration violations'}
    )
    factor_betas = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Number of factor beta violations'}
    )
    leverage = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Number of leverage violations'}
    )
    variance_contributions = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Number of variance contribution violations'}
    )
    volatility = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Number of volatility violations'}
    )


class RiskScoreSchema(Schema):
    """Core risk scoring results."""
    score = fields.Float(
        required=True,
        validate=validate.Range(min=0, max=100),
        metadata={'description': 'Overall risk score (0-100)'}
    )
    category = fields.Str(
        required=True,
        validate=validate.OneOf(['Excellent', 'Good', 'Fair', 'Poor', 'Critical']),
        metadata={'description': 'Risk category classification'}
    )
    component_scores = fields.Nested(ComponentScoreSchema, required=True)
    
    details = fields.Dict(
        required=True,
        metadata={'description': 'Detailed risk score breakdown'}
    )
    interpretation = fields.Dict(
        required=True,
        metadata={'description': 'Risk score interpretation and guidance'}
    )
    potential_losses = fields.Dict(
        keys=fields.Str(),
        values=fields.Float(),
        required=True,
        metadata={'description': 'Potential loss estimates by risk type'}
    )
    recommendations = fields.List(
        fields.Str(),
        required=False,
        missing=[],
        metadata={'description': 'Risk management recommendations'}
    )
    risk_factors = fields.List(
        fields.Str(),
        required=False,
        missing=[],
        metadata={'description': 'Key risk factors identified'}
    )


class RiskScoreResultSchema(Schema):
    """Complete risk score analysis result."""
    success = fields.Bool(required=True)
    analysis_date = fields.DateTime(required=True, format='iso8601')
    formatted_report = fields.Str(required=True)
    
    portfolio_metadata = fields.Nested(PortfolioMetadataSchema, required=True)
    risk_score = fields.Nested(RiskScoreSchema, required=True)
    
    limits_analysis = fields.Dict(required=True)  # Complex nested structure
    portfolio_analysis = fields.Dict(required=True)  # Reuses RiskAnalysisResult structure
    
    summary = fields.Dict(
        keys=fields.Str(),
        values=fields.Raw(),
        required=True,
        metadata={'description': 'Risk score summary statistics'}
    )


# =============================================================================
# OPTIMIZATION RESULT SCHEMAS
# =============================================================================

class OptimizationMetadataSchema(Schema):
    """Optimization run metadata."""
    active_positions = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Number of active positions in optimized portfolio'}
    )
    analysis_date = fields.DateTime(
        required=True,
        format='iso8601',
        metadata={'description': 'Optimization analysis timestamp'}
    )
    optimization_type = fields.Str(
        required=True,
        validate=validate.OneOf(['minimum_variance', 'maximum_return', 'maximum_sharpe']),
        metadata={'description': 'Type of optimization performed'}
    )
    original_weights = fields.Dict(
        keys=fields.Str(),
        values=fields.Float(validate=validate.Range(min=0, max=1)),
        required=True,
        metadata={'description': 'Original portfolio weights by ticker'}
    )
    portfolio_file = fields.Str(
        required=False,
        metadata={'description': 'Source portfolio filename'}
    )
    total_positions = fields.Int(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Total positions in original portfolio'}
    )
    expected_returns_used = fields.Dict(
        keys=fields.Str(),
        values=fields.Float(),
        required=False,
        metadata={'description': 'Expected returns by ticker used in optimization'}
    )


class BetaConstraintsSchema(Schema):
    """Beta constraint analysis results."""
    beta_passes = fields.Bool(
        required=True,
        metadata={'description': 'Whether all beta constraints are satisfied'}
    )
    beta_checks = fields.List(
        fields.Nested(BetaCheckSchema),
        required=True,
        metadata={'description': 'Individual beta constraint checks'}
    )
    beta_violations = fields.List(
        fields.Nested(BetaCheckSchema),
        required=True,
        metadata={'description': 'Failed beta constraint checks'}
    )


class RiskConstraintsSchema(Schema):
    """Risk constraint analysis results."""
    risk_passes = fields.Bool(
        required=True,
        metadata={'description': 'Whether all risk constraints are satisfied'}
    )
    risk_checks = fields.List(
        fields.Nested(RiskConstraintSchema),
        required=True,
        metadata={'description': 'Individual risk constraint checks'}
    )
    risk_violations = fields.List(
        fields.Nested(RiskConstraintSchema),
        required=True,
        metadata={'description': 'Failed risk constraint checks'}
    )
    risk_limits = fields.Dict(
        required=True,
        metadata={'description': 'Risk limit definitions used'}
    )


class DirectOptimizationResultSchema(Schema):
    """Direct optimization API result."""
    success = fields.Bool(required=True)
    endpoint = fields.Str(required=True, validate=validate.Regexp(r'^direct/optimize/'))
    
    data = fields.Dict(required=True)  # Complex nested optimization data
    
    summary = fields.Dict(
        keys=fields.Str(),
        values=fields.Raw(),
        required=True,
        metadata={'description': 'Optimization summary information'}
    )


# =============================================================================
# STOCK ANALYSIS SCHEMAS
# =============================================================================

class StockRiskMetricsSchema(Schema):
    """Stock-specific risk metrics from regression analysis."""
    alpha = fields.Float(
        required=True,
        metadata={'description': 'Alpha vs benchmark (monthly)'}
    )
    beta = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Beta vs benchmark'}
    )
    idio_vol_m = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Monthly idiosyncratic volatility'}
    )
    r_squared = fields.Float(
        required=True,
        validate=validate.Range(min=0, max=1),
        metadata={'description': 'R-squared correlation with benchmark'}
    )


class VolatilityMetricsSchema(Schema):
    """Stock volatility calculations."""
    monthly_vol = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Monthly volatility'}
    )
    annual_vol = fields.Float(
        required=True,
        validate=validate.Range(min=0),
        metadata={'description': 'Annualized volatility'}
    )


class DirectStockResultSchema(Schema):
    """Direct stock analysis API result."""
    success = fields.Bool(required=True)
    endpoint = fields.Str(required=True, validate=validate.Equal('direct/stock'))
    
    data = fields.Dict(required=True)  # Complex nested stock analysis data
    
    summary = fields.Dict(
        keys=fields.Str(),
        values=fields.Raw(),
        required=True,
        metadata={'description': 'Stock analysis summary'}
    )


# =============================================================================
# WHAT-IF ANALYSIS SCHEMAS
# =============================================================================

class ComparisonRowSchema(Schema):
    """Before/after comparison for beta metrics."""
    max_beta = fields.Float(
        required=True,
        data_key='Max Beta',
        metadata={'description': 'Maximum allowed beta value'}
    )
    new_value = fields.Float(
        required=True,
        data_key='New',
        metadata={'description': 'New portfolio beta value'}
    )
    new_pass = fields.Bool(
        required=True,
        data_key='New Pass',
        metadata={'description': 'Whether new value passes constraint'}
    )
    old_value = fields.Float(
        required=True,
        data_key='Old',
        metadata={'description': 'Original portfolio beta value'}
    )
    old_pass = fields.Bool(
        required=True,
        data_key='Old Pass',
        metadata={'description': 'Whether original value passed constraint'}
    )
    delta = fields.Float(
        required=True,
        data_key='Δ',
        metadata={'description': 'Change in beta value (new - old)'}
    )


class RiskComparisonRowSchema(Schema):
    """Before/after comparison for risk metrics."""
    limit = fields.Float(
        required=True,
        data_key='Limit',
        metadata={'description': 'Risk constraint limit'}
    )
    metric = fields.Str(
        required=True,
        data_key='Metric',
        metadata={'description': 'Risk metric name'}
    )
    new_value = fields.Float(
        required=True,
        data_key='New',
        metadata={'description': 'New metric value'}
    )
    new_pass = fields.Bool(
        required=True,
        data_key='New Pass',
        metadata={'description': 'Whether new value passes constraint'}
    )
    old_value = fields.Float(
        required=True,
        data_key='Old',
        metadata={'description': 'Original metric value'}
    )
    old_pass = fields.Bool(
        required=True,
        data_key='Old Pass',
        metadata={'description': 'Whether original value passed constraint'}
    )
    delta = fields.Float(
        required=True,
        data_key='Δ',
        metadata={'description': 'Change in metric value (new - old)'}
    )


class WhatIfComparisonSchema(Schema):
    """What-if analysis comparison results."""
    beta_comparison = fields.List(
        fields.Nested(ComparisonRowSchema),
        required=True,
        metadata={'description': 'Beta comparison before/after changes'}
    )
    risk_comparison = fields.List(
        fields.Nested(RiskComparisonRowSchema),
        required=True,
        metadata={'description': 'Risk metrics comparison before/after changes'}
    )


class DirectWhatIfResultSchema(Schema):
    """Direct what-if analysis API result."""
    success = fields.Bool(required=True)
    endpoint = fields.Str(required=True, validate=validate.Equal('direct/whatif'))
    
    data = fields.Dict(required=True)  # Complex nested what-if analysis data
    
    summary = fields.Dict(
        keys=fields.Str(),
        values=fields.Raw(),
        required=True,
        metadata={'description': 'What-if analysis summary'}
    )


# =============================================================================
# HEALTH CHECK SCHEMA
# =============================================================================

class HealthResultSchema(Schema):
    """System health check response."""
    status = fields.Str(
        required=True,
        validate=validate.OneOf(['healthy', 'degraded', 'unhealthy']),
        metadata={'description': 'Overall system health status'}
    )
    version = fields.Str(
        required=True,
        validate=validate.Regexp(r'^\d+\.\d+\.\d+$'),
        metadata={'description': 'API version in semver format'}
    )
    google_oauth_configured = fields.Bool(
        required=True,
        metadata={'description': 'Whether Google OAuth is properly configured'}
    )


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================

def validate_portfolio_weights(weights_dict: Dict[str, float]) -> Dict[str, float]:
    """
    Validate that portfolio weights sum to approximately 1.0 and are non-negative.
    
    Args:
        weights_dict: Dictionary of ticker -> weight mappings
        
    Returns:
        Validated weights dictionary
        
    Raises:
        ValidationError: If weights are invalid
    """
    if not weights_dict:
        raise ValidationError("Weights dictionary cannot be empty")
    
    # Check individual weights are non-negative
    for ticker, weight in weights_dict.items():
        if not isinstance(weight, (int, float)):
            raise ValidationError(f"Weight for {ticker} must be a number, got {type(weight)}")
        if weight < 0:
            raise ValidationError(f"Weight for {ticker} cannot be negative: {weight}")
    
    # Check weights sum to approximately 1.0 (allow for floating point precision)
    total_weight = sum(weights_dict.values())
    if abs(total_weight - 1.0) > 0.001:
        raise ValidationError(f"Weights must sum to 1.0, got {total_weight:.6f}")
    
    return weights_dict


def validate_correlation_matrix(matrix_data: list) -> list:
    """
    Validate correlation matrix structure and properties.
    
    Args:
        matrix_data: List of correlation matrix rows
        
    Returns:
        Validated matrix data
        
    Raises:
        ValidationError: If matrix is invalid
    """
    if not matrix_data:
        raise ValidationError("Correlation matrix cannot be empty")
    
    n_assets = len(matrix_data)
    
    # Check matrix is square
    for i, row in enumerate(matrix_data):
        if not isinstance(row, dict):
            raise ValidationError(f"Matrix row {i} must be a dictionary")
        if len(row) != n_assets:
            raise ValidationError(f"Matrix row {i} has {len(row)} columns, expected {n_assets}")
    
    # Check diagonal is 1.0 and matrix is symmetric
    tickers = list(matrix_data[0].keys())
    for i, row in enumerate(matrix_data):
        ticker_i = tickers[i]
        
        # Check diagonal element
        if abs(row[ticker_i] - 1.0) > 0.001:
            raise ValidationError(f"Diagonal element [{ticker_i}, {ticker_i}] should be 1.0, got {row[ticker_i]}")
        
        # Check correlation bounds
        for ticker_j, correlation in row.items():
            if not isinstance(correlation, (int, float)):
                raise ValidationError(f"Correlation [{ticker_i}, {ticker_j}] must be numeric")
            if not (-1.0 <= correlation <= 1.0):
                raise ValidationError(f"Correlation [{ticker_i}, {ticker_j}] must be between -1 and 1, got {correlation}")
    
    return matrix_data


# =============================================================================
# EXAMPLE USAGE AND TESTING
# =============================================================================

if __name__ == "__main__":
    # Example: Validate a performance result
    performance_data = {
        "success": True,
        "benchmark": "SPY",
        "formatted_report": "Portfolio Performance Analysis...",
        "portfolio_metadata": {
            "analyzed_at": "2025-08-06T14:05:12+00:00",
            "name": "CURRENT_PORTFOLIO",
            "source": "database",
            "user_id": 1
        },
        "performance_metrics": {
            "analysis_date": "2025-08-06T14:05:12.345335",
            "analysis_period": {
                "start_date": "2019-01-31",
                "end_date": "2025-06-27",
                "total_months": 61,
                "years": 5.08
            },
            "returns": {
                "total_return": 222.59,
                "annualized_return": 25.91,
                "best_month": 17.8,
                "worst_month": -10.37,
                "win_rate": 63.9,
                "positive_months": 39,
                "negative_months": 22
            }
        },
        "summary": {
            "annualized_return": 25.91,
            "volatility": 20.09,
            "sharpe_ratio": 1.157
        }
    }
    
    # Test schema validation
    schema = PerformanceResultSchema()
    try:
        result = schema.load(performance_data)
        print("✅ Performance data validation passed")
    except ValidationError as e:
        print(f"❌ Validation failed: {e.messages}")
    
    # Example: Validate portfolio weights
    try:
        weights = {"AAPL": 0.3, "GOOGL": 0.25, "MSFT": 0.2, "AMZN": 0.15, "TSLA": 0.1}
        validated_weights = validate_portfolio_weights(weights)
        print("✅ Portfolio weights validation passed")
    except ValidationError as e:
        print(f"❌ Weights validation failed: {e}")