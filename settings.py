#Date settings for portfolio analysis are in settings.py
import os
from pathlib import Path

# Ensure local ".env" is loaded even for direct Python invocations
# (e.g., scripts/tools that bypass mcp_server.py bootstrapping).
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except Exception:
    # Fail open: settings still support explicit process env and file fallback.
    pass

# URL Configuration
FRONTEND_BASE_URL = os.getenv('FRONTEND_BASE_URL', 'http://localhost:3000')
BACKEND_BASE_URL = os.getenv('BACKEND_BASE_URL', 'http://localhost:5001')


from utils.user_context import (
    RISK_MODULE_USER_EMAIL_ENV,
    _default_dotenv_path,
    _normalize_email_value,
    _read_env_or_dotenv,
    _read_key_from_env_file,
    format_missing_user_error,
    get_default_user,
    get_default_user_context,
    resolve_default_user,
    resolve_user_email,
)

# settings.py  
PORTFOLIO_DEFAULTS = {
    "start_date": "2019-01-31", # start date for portfolio analysis
    "end_date":   "2026-01-29", # end date for portfolio analysis (updated 2026-01-29)
    "normalize_weights": False,  # Global default for portfolio weight normalization
    "worst_case_lookback_years": 10,  # Historical lookback period for worst-case scenario analysis
    "expected_returns_lookback_years": 10,  # Default years of historical data for expected returns estimation
    "expected_returns_fallback_default": 0.06,  # Default fallback return (6%) when calculation fails
    "cash_proxy_fallback_return": 0.02  # Conservative fallback return (2%) for cash proxies when Treasury rates unavailable
}

# Dividend calculation settings - CURRENT YIELD METHOD ONLY (V1)
DIVIDEND_DEFAULTS = {
    "lookback_months": 12,
    "min_dividend_data_coverage": 0.7,
    "include_zero_yield_positions": True,
}

# Rate factor configuration (centralized)
# Controls maturities, mapping to provider fields, and defaults for rate beta analysis.
#
# Notes:
# - default_maturities define the key‑rate vector used in regressions.
# - treasury_mapping maps internal keys to provider field names used by the
#   data_loader/factor_utils aggregators.
# - scale='pp' indicates input levels are percentages and will be converted to
#   decimal internally (0.01 per 1%).
RATE_FACTOR_CONFIG = {
    "default_maturities": ["UST2Y", "UST5Y", "UST10Y", "UST30Y"],
    # Mapping from internal factor key → FMP treasury maturity column name
    "treasury_mapping": {
        "UST2Y": "year2",
        "UST5Y": "year5",
        "UST10Y": "year10",
        "UST30Y": "year30",
    },
    # Minimum number of maturities required to proceed (warn below this)
    "min_required_maturities": 2,
    # Internal scaling for Δy preparation ('pp' → percentage points to decimal)
    "scale": "pp",
    # Default frequency identifier for monthly data
    "frequency": "M",
    # Asset classes eligible for interest rate factor injection
    "eligible_asset_classes": ["bond", "real_estate"],
}

# Optional profiles for future flexibility (not strictly required by core integration)
RATE_FACTOR_PROFILES = {
    "standard": ["UST2Y", "UST5Y", "UST10Y", "UST30Y"],
    "short_term": ["UST2Y", "UST5Y"],
    "long_term": ["UST10Y", "UST30Y"],
    "minimal": ["UST10Y"],
}

# Data Quality Thresholds
# Minimum observation requirements for various factor calculations and data validation
DATA_QUALITY_THRESHOLDS = {
    # Factor beta calculation minimum observations
    "min_observations_for_factor_betas": 2,     # Minimum monthly observations for reliable beta calculation
    "min_observations_for_interest_rate_beta": 6,  # Minimum observations for interest rate beta calculation
    
    # Peer validation thresholds
    "min_observations_for_peer_validation": 3,   # Minimum observations for peer ticker validation
    "min_peer_overlap_observations": 1,          # Minimum observations a peer must have in analysis window
    
    # General data quality checks
    "min_observations_for_returns_calculation": 2,  # Minimum observations needed to calculate returns
    "min_observations_for_regression": 3,        # Minimum observations for any regression analysis
    "min_observations_for_factor_attribution": 6,  # Minimum monthly observations for portfolio factor attribution

    # Subindustry peer filtering
    "min_valid_peers_for_median": 1,             # Minimum peers needed to calculate subindustry median
    "max_peer_drop_rate": 0.8,                   # Warning if >80% of peers dropped due to data issues
    
    # Expected returns calculation
    # 11 monthly returns ~= 12 months of price history.
    "min_observations_for_expected_returns": 11,  # Minimum monthly return observations for reliable expected return calculation
    
    # CAPM regression calculation
    "min_observations_for_capm_regression": 12,   # Minimum months for alpha/beta calculation (1 year)
    
    # Data quality warning thresholds
    "min_r2_for_rate_factors": 0.3,              # Minimum R² for rate factor regressions before warning
    "max_reasonable_interest_rate_beta": 25,     # Maximum reasonable interest rate beta before warning
}

# Realized-performance acceptance thresholds
BACKFILL_FILE_PATH = os.getenv(
    "BACKFILL_FILE_PATH",
    os.path.join(os.path.dirname(__file__), "user_data", "incomplete_trades_backfill.json"),
)
REALIZED_COVERAGE_TARGET = float(os.getenv("REALIZED_COVERAGE_TARGET", "95.0"))
REALIZED_MAX_INCOMPLETE_TRADES = int(os.getenv("REALIZED_MAX_INCOMPLETE_TRADES", "0"))
REALIZED_MAX_RECONCILIATION_GAP_PCT = float(os.getenv("REALIZED_MAX_RECONCILIATION_GAP_PCT", "2.0"))

# Provider-native flow controls for realized performance.
# Rollback: set REALIZED_USE_PROVIDER_FLOWS=false (subordinate flags are ignored).
REALIZED_USE_PROVIDER_FLOWS = os.getenv("REALIZED_USE_PROVIDER_FLOWS", "true").lower() == "true"
REALIZED_PROVIDER_FLOW_SOURCES = [
    token.strip().lower()
    for token in os.getenv("REALIZED_PROVIDER_FLOW_SOURCES", "schwab,plaid,snaptrade,ibkr_flex").split(",")
    if token.strip()
]
REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE = (
    os.getenv("REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE", "true").lower() == "true"
)

# Risk Analysis Thresholds
# These constants define the hardcoded limits and thresholds used throughout the risk analysis system
RISK_ANALYSIS_THRESHOLDS = {
    # Leverage Analysis
    "leverage_warning_threshold": 1.1,  # Leverage ratio above which warnings are triggered
    
    # Risk Score Calculation (excess ratio thresholds)
    "risk_score_safe_threshold": 0.8,      # Below this ratio = 100 points (safe)
    "risk_score_caution_threshold": 1.0,   # At limit = 75 points (caution) 
    "risk_score_danger_threshold": 1.5,    # 50% over limit = 50 points (danger)
    "risk_score_critical_threshold": 2.0,  # 100% over limit = 0 points (critical)
    
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

# ===========================
# Factor Intelligence Defaults
# ===========================

# Default granularity for industry correlations. Options: 'group' | 'industry'
DEFAULT_INDUSTRY_GRANULARITY = 'group'

# Macro matrix controls used by compute_macro_etf_matrix
MACRO_DEFAULTS = {
    'macro_max_per_group': 3,
    'macro_deduplicate_threshold': 0.95,
    'macro_min_group_coverage_pct': 0.6,
}

# Core defaults used by Factor Intelligence analyses.
FACTOR_INTELLIGENCE_DEFAULTS = {
    # Analysis time window - default start date for factor analysis
    "start_date": "2010-01-31",

    # Core sector ETFs: 11 high-level SPDR sector ETFs used for portfolio-level sector analysis
    # These represent the major S&P 500 sector breakdowns and are used for:
    # - Individual ETF rate/market sensitivity calculations
    # - Sector preference resolution and display ordering
    # - High-level sector correlation matrices
    "core_sector_tickers": [
        "XLK", "XLV", "XLF", "XLY", "XLP", "XLE",  # Technology, Healthcare, Financial Services, Consumer Discretionary, Consumer Staples, Energy
        "XLI", "XLB", "XLRE", "XLU", "XLC",       # Industrials, Materials, Real Estate, Utilities, Communication Services
    ],

    # Display labels for core sector ETFs - used in CLI output and API responses
    # Maps 1:1 with core_sector_tickers above for consistent labeling across all factor intelligence features
    "core_sector_labels": [
        "Technology",               # XLK
        "Healthcare",               # XLV
        "Financial Services",       # XLF
        "Consumer Discretionary",   # XLY
        "Consumer Staples",         # XLP
        "Energy",                   # XLE
        "Industrials",              # XLI
        "Materials",                # XLB
        "Real Estate",              # XLRE
        "Utilities",                # XLU
        "Communication Services",   # XLC
    ],

    # Default asset categories for different types of factor analysis
    # These control which ETF categories get included when no explicit categories are specified
    "default_categories": {
        # Rate sensitivity analysis: How assets respond to interest rate changes (Δy)
        # - bond: Treasury ETFs, corporate bonds, TIPS (primary rate-sensitive assets)
        # - industry: Sector ETFs (secondary rate sensitivity via duration/growth profiles)
        # - market: Broad market ETFs (market-wide rate sensitivity)
        "rate_sensitivity": ["bond", "industry", "market"],

        # Market sensitivity analysis: How assets respond to equity market movements (beta)
        # - industry: Sector ETFs (primary market sensitivity analysis)
        # - style: Value/Growth/Momentum ETFs (style factor market sensitivity)
        "market_sensitivity": ["industry", "style"],

        # Correlation matrix analysis: Comprehensive cross-asset correlations
        # - All major asset classes for complete factor correlation picture
        "correlations": ["bond", "commodity", "crypto", "industry", "market", "style", "cash"],
    },

    # Correlation analysis configuration - controls behavior of factor correlation matrices
    "correlations": {
        # Matrix sizing and filtering
        "max_factors": 15,                    # Maximum number of factors to include per correlation matrix
        "min_observations": 24,               # Minimum monthly observations required for correlation calculation (2 years)
        "correlation_threshold": 0.05,       # Minimum correlation magnitude to include in analysis
        "top_n_per_matrix": 15,              # Top N correlations to highlight in each matrix

        # Analysis scope and granularity
        "industry_granularity": "industry",  # Level of industry analysis: "industry" (detailed) vs "group" (high-level)
        "format": "json",                    # Output format for API responses

        # Overlay analysis toggles - additional matrices beyond core correlations
        "include_rate_sensitivity": True,    # Calculate ETF sensitivity to interest rate changes (rate betas)
        "include_market_sensitivity": True,  # Calculate ETF sensitivity to market movements (market betas)
        "include_macro_composite": True,     # Generate macro-level asset class correlation matrix
        "include_macro_etf": False,          # Generate ETF-level macro correlation matrix (resource intensive)
        "include_rolling_summaries": False,  # Include time-series rolling correlation summaries

        # Benchmark and grouping configuration
        "market_benchmarks": ["SPY"],                                              # Market benchmarks for beta calculations
        "macro_groups": ["equity", "bond", "cash", "commodity", "crypto"],       # Asset classes for macro composite analysis
    },
    "performance": {
        "benchmark_ticker": "SPY",
        "min_observations": 24,
        "industry_granularity": DEFAULT_INDUSTRY_GRANULARITY,
        "include_macro": True,
        "include_factor_categories": True,
        "composite_weighting_method": "equal",
        "composite_max_per_group": None,
    },
    "returns": {
        "default_windows": ["1m", "3m", "6m", "1y"],
        "top_n": 10,
        "industry_granularity": DEFAULT_INDUSTRY_GRANULARITY,
    },
    "offsets": {
        "correlation_threshold": -0.2,
        "max_recommendations": 10,
        "industry_granularity": "industry",
    },
    "portfolio_offsets": {
        "correlation_threshold": 0.3,    # positive: "least correlated" diversifiers (equity sectors rarely have negative correlations)
        "max_recs_per_driver": 5,
        "industry_granularity": DEFAULT_INDUSTRY_GRANULARITY,
        "driver_budget": 0.06,
    },
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
    
    # Security-type-specific crash scenarios (NEW - FIXES DSU ISSUE!)
    # These replace the generic single_stock_crash for different security types
    # Based on historical diversification and risk profiles:
    "etf_crash": 0.35,              # Diversified ETF crash (tracks market-wide events)
    "fund_crash": 0.40,             # Fund crash (moderate diversification) ← DSU FIX!
    "mutual_fund_crash": 0.40,      # Mutual fund crash (backward compatibility) ← DSU FIX!
    "cash_crash": 0.05,             # Cash equivalent risk (money market funds, very low)
    
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

# Security Type to Crash Scenario Mapping (NEW - ENABLES SECURITY-TYPE-AWARE RISK SCORING!)
# Maps security types from SecurityTypeService to their appropriate crash scenarios.
# Used by portfolio_risk_score.calculate_concentration_risk_loss() to apply different
# crash scenarios based on the actual security type rather than treating all as equity.
#
# BEFORE: All securities used single_stock_crash (80%) - DSU got 80% ❌
# AFTER: Each security type gets appropriate scenario - DSU gets 40% ✅
#
# Historical Context:
# - equity (80%): Individual stock failures (Enron, Lehman Brothers, WorldCom)
# - etf (35%): Diversified ETF crashes track market events (2008, 2020)
# - mutual_fund (40%): Mutual fund crashes have moderate diversification protection
# - cash (5%): Money market/cash equivalents have very low crash risk
#
# CENTRALIZED MAPPING SYSTEM:
# Uses the established 3-tier architecture pattern (Database → YAML → Hardcoded)
# that is consistent with all other mapping systems in the risk module.
def _load_crash_scenario_mappings():
    """
    Load crash scenario mappings using centralized system.
    
    ARCHITECTURE:
    Calls utils.security_type_mappings.get_crash_scenario_mappings() which uses:
    1. Database: security_type_scenarios table (primary)
    2. YAML: security_type_mappings.yaml (fallback)
    3. Hardcoded: Built-in mapping dictionary (ultimate fallback)
    
    Returns:
        Dict mapping security types to crash scenario keys
    """
    try:
        from utils.security_type_mappings import get_crash_scenario_mappings
        return get_crash_scenario_mappings()
    except Exception:
        # Ultimate fallback - preserve original hardcoded mapping
        return {
            "equity": "single_stock_crash",      # Individual equity positions (80%)
            "etf": "etf_crash",                  # Diversified ETFs (35%) - 56% risk reduction
            "fund": "fund_crash",                # Funds (40%) - 50% risk reduction ← DSU FIX!
            "mutual_fund": "mutual_fund_crash",  # Mutual funds (40%) - backward compatibility ← DSU FIX!
            "cash": "cash_crash"                 # Cash equivalents (5%) - 94% risk reduction
        }

# Load crash scenario mappings using centralized system
SECURITY_TYPE_CRASH_MAPPING = _load_crash_scenario_mappings()

# SnapTrade Configuration
ENABLE_SNAPTRADE = True  # Always enabled

from providers.routing_config import (
    DEFAULT_POSITION_PROVIDERS,
    DEFAULT_TRANSACTION_PROVIDERS,
    INSTITUTION_PROVIDER_MAPPING,
    INSTITUTION_SLUG_ALIASES,
    POSITION_ROUTING,
    PROVIDER_CAPABILITIES,
    PROVIDER_PRIORITY_CONFIG,
    PROVIDER_ROUTING_CONFIG,
    TRANSACTION_FETCH_POLICY,
    TRANSACTION_ROUTING,
)

# Trading Execution Configuration
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "false").lower() == "true"

TRADING_DEFAULTS = {
    "max_order_value": float(os.getenv("MAX_ORDER_VALUE", "100000")),
    "max_single_stock_weight_post_trade": 0.25,
    "preview_expiry_seconds": 300,  # 5 min
    "default_time_in_force": "Day",
    "default_order_type": "Market",
    "log_all_previews": True,
    "log_all_executions": True,
}

# IBKR (Interactive Brokers) Configuration
IBKR_ENABLED = os.getenv("IBKR_ENABLED", "false").lower() == "true"
from ibkr.config import (
    IBKR_AUTHORIZED_ACCOUNTS,
    IBKR_CLIENT_ID,
    IBKR_GATEWAY_HOST,
    IBKR_GATEWAY_PORT,
    IBKR_READONLY,
    IBKR_TIMEOUT,
)

IBKR_FLEX_TOKEN = os.getenv("IBKR_FLEX_TOKEN", "")
IBKR_FLEX_QUERY_ID = os.getenv("IBKR_FLEX_QUERY_ID", "")

# Provider credential requirements (used by providers.routing)
PROVIDER_CREDENTIALS: dict[str, list[str]] = {
    "plaid": [],
    "snaptrade": [],
    "ibkr": [],
    "ibkr_flex": ["IBKR_FLEX_TOKEN", "IBKR_FLEX_QUERY_ID"],
    "schwab": ["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET"],
}

# Schwab (Direct API) Configuration
SCHWAB_ENABLED = (_read_env_or_dotenv("SCHWAB_ENABLED", "false") or "false").lower() == "true"
SCHWAB_HISTORY_DAYS = int(_read_env_or_dotenv("SCHWAB_HISTORY_DAYS", "365") or "365")
SCHWAB_TRANSACTIONS_CACHE_PATH = os.path.expanduser(
    _read_env_or_dotenv(
        "SCHWAB_TRANSACTIONS_CACHE_PATH",
        os.path.join(os.path.dirname(__file__), "cache", "schwab_transactions.json"),
    ) or os.path.join(os.path.dirname(__file__), "cache", "schwab_transactions.json")
)

# Provider-specific cache TTL (hours)
PROVIDER_CACHE_HOURS = {
    "plaid": int(os.getenv("PLAID_CACHE_HOURS", "72")),
    "snaptrade": int(os.getenv("SNAPTRADE_CACHE_HOURS", "24")),
    "schwab": int(os.getenv("SCHWAB_CACHE_HOURS", "24")),
}
