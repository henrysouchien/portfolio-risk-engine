#Date settings for portfolio analysis are in settings.py

# settings.py  
PORTFOLIO_DEFAULTS = {
    "start_date": "2019-01-31", # start date for portfolio analysis
    "end_date":   "2025-06-27", # end date for portfolio analysis
    "normalize_weights": False,  # Global default for portfolio weight normalization
    "worst_case_lookback_years": 10,  # Historical lookback period for worst-case scenario analysis
    "expected_returns_lookback_years": 10,  # Default years of historical data for expected returns estimation
    "expected_returns_fallback_default": 0.06,  # Default fallback return (6%) when calculation fails
    "cash_proxy_fallback_return": 0.02  # Conservative fallback return (2%) for cash proxies when Treasury rates unavailable
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

# SnapTrade Configuration
import os

SNAPTRADE_CLIENT_ID = os.getenv("SNAPTRADE_CLIENT_ID", "")
SNAPTRADE_CONSUMER_KEY = os.getenv("SNAPTRADE_CONSUMER_KEY", "")
SNAPTRADE_BASE_URL = os.getenv("SNAPTRADE_BASE_URL", "https://api.snaptrade.com/api/v1")
SNAPTRADE_ENVIRONMENT = os.getenv("SNAPTRADE_ENVIRONMENT", "production")  # or "sandbox"
ENABLE_SNAPTRADE = True  # Always enabled

# SnapTrade Rate Limits
SNAPTRADE_RATE_LIMIT = int(os.getenv("SNAPTRADE_RATE_LIMIT", "250"))  # requests per minute
SNAPTRADE_HOLDINGS_DAILY_LIMIT = int(os.getenv("SNAPTRADE_HOLDINGS_DAILY_LIMIT", "4"))  # per user per day

# SnapTrade Webhook Configuration
SNAPTRADE_WEBHOOK_SECRET = os.getenv("SNAPTRADE_WEBHOOK_SECRET", "")
SNAPTRADE_WEBHOOK_URL = os.getenv("SNAPTRADE_WEBHOOK_URL", "")

# Multi-Provider Configuration
PROVIDER_PRIORITY_CONFIG = {
    # Provider priority for metadata (quantities always summed)
    # Higher number = higher priority for cost_basis, account_id, etc.
    "snaptrade": int(os.getenv("SNAPTRADE_PRIORITY", "3")),  # Highest - real-time brokerage data
    "plaid": int(os.getenv("PLAID_PRIORITY", "2")),          # Medium - aggregated data  
    "manual": int(os.getenv("MANUAL_PRIORITY", "1")),        # Lowest - user input
}

# Provider Display Configuration
PROVIDER_DISPLAY_CONFIG = {
    "snaptrade": {
        "name": "SnapTrade",
        "description": "Direct brokerage connections (Fidelity, Schwab, etc.)",
        "icon": "snaptrade",
        "color": "#4F46E5",
        "features": ["real_time_data", "all_brokerages", "trading"]
    },
    "plaid": {
        "name": "Plaid",
        "description": "Bank and investment account aggregation",
        "icon": "plaid", 
        "color": "#00D4AA",
        "features": ["bank_accounts", "aggregation", "read_only"]
    },
    "manual": {
        "name": "Manual Entry",
        "description": "Manually entered positions and accounts",
        "icon": "manual",
        "color": "#6B7280",
        "features": ["custom_portfolios", "flexibility"]
    }
}

# Provider Routing Configuration
PROVIDER_ROUTING_CONFIG = {
    "enabled": True,
    "default_timeout": 30,  # seconds
    "max_fallback_time": 60,  # seconds
    "health_check_interval": 300,  # seconds
    "error_rate_threshold": 0.3,  # 30% error rate triggers degradation
}

# Institution Routing Mappings
# Maps institution slugs to supported providers
INSTITUTION_PROVIDER_MAPPING = {
    # Major brokerages - SnapTrade preferred
    "charles_schwab": ["snaptrade", "plaid"],
    "fidelity": ["snaptrade", "plaid"], 
    "td_ameritrade": ["snaptrade", "plaid"],
    "etrade": ["snaptrade", "plaid"],
    "interactive_brokers": ["snaptrade", "plaid"],
    "vanguard": ["snaptrade", "plaid"],
    "merrill_edge": ["snaptrade", "plaid"],
    
    # Banks - Plaid preferred
    "chase": ["plaid"],
    "bank_of_america": ["plaid"],
    "wells_fargo": ["plaid"],
    "citibank": ["plaid"],
    "us_bank": ["plaid"],
    
    # Investment platforms
    "robinhood": ["snaptrade", "plaid"],
    "webull": ["snaptrade"],
    "m1_finance": ["plaid"],
    "betterment": ["plaid"],
    "wealthfront": ["plaid"],
}

