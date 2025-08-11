#Date settings for portfolio analysis are in settings.py

# settings.py  
PORTFOLIO_DEFAULTS = {
    "start_date": "2019-01-31", # start date for portfolio analysis
    "end_date":   "2025-06-27", # end date for portfolio analysis
    "normalize_weights": False,  # Global default for portfolio weight normalization
    "worst_case_lookback_years": 10  # Historical lookback period for worst-case scenario analysis
}

# Risk Analysis Thresholds
# These constants define the hardcoded limits and thresholds used throughout the risk analysis system
RISK_ANALYSIS_THRESHOLDS = {
    # Leverage Analysis
    "leverage_warning_threshold": 1.1,  # Leverage ratio above which warnings are triggered
    
    # Risk Score Calculation (excess ratio thresholds)
    "risk_score_safe_threshold": 0.8,      # Below this ratio = 100 points (safe)
    "risk_score_caution_threshold": 1.0,   # At limit = 75 points (caution) 
    "risk_score_danger_threshold": 1.5,    # 50% over limit = 50 points (danger)
    
    # Beta Exposure Analysis
    "beta_warning_ratio": 0.75,  # Flag beta exposures above 75% of limit
    "beta_violation_ratio": 1.0, # Beta exposures above 100% of limit
    
    # Diversification Analysis  
    "herfindahl_warning_threshold": 0.15,  # HHI above this indicates low diversification
    "concentration_warning_ratio": 0.8,    # Position size above 80% of limit triggers warning
    
    # Volatility Analysis
    "volatility_warning_ratio": 0.8,  # Portfolio volatility above 80% of limit
    
    # Variance Contribution Analysis
    "factor_variance_warning_ratio": 0.8,        # Factor variance above 80% of limit
    "market_variance_warning_ratio": 0.8,        # Market variance above 80% of limit  
    "variance_contribution_threshold": 0.05,     # 5% - minimum contribution to recommend reduction
    "industry_concentration_warning_ratio": 0.5, # Industry concentration above 50% of limit
    
    # Leverage Display Thresholds
    "leverage_display_threshold": 1.01,  # Show leverage adjustments above this ratio
}

# Worst-Case Scenario Definitions
# These scenarios define the stress tests used for risk calculations and limit suggestions
WORST_CASE_SCENARIOS = {
    # Market crash scenario - based on major historical crashes
    # 2008: -37%, 2000-2002: -49%, 2020: -34%, 1987: -22%
    "market_crash": 0.35,
    
    # Factor-specific scenarios - for momentum/value tilts
    # These use individual factor loss limits since they're specific bets
    "momentum_crash": 0.50,  # Momentum factor reversal
    "value_crash": 0.40,     # Value factor underperformance
    
    # Concentration scenarios
    "single_stock_crash": 0.80,  # Individual stock failure
    "sector_crash": 0.50,        # Sector-wide crisis
    
    # Volatility scenarios
    "max_reasonable_volatility": 0.40,  # Maximum reasonable portfolio volatility
}

# Maximum Single Factor Loss Limits
# Default loss limits for individual factor exposures in worst-case scenarios
MAX_SINGLE_FACTOR_LOSS = {
    "default": -0.10,    # Default maximum single factor loss (10%)
    "sector": -0.08,     # Sector-specific factor loss limit (8%)
    "portfolio": -0.08,  # Portfolio-level factor loss limit (8%)
}

