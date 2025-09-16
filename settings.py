#Date settings for portfolio analysis are in settings.py
import os

# URL Configuration
FRONTEND_BASE_URL = os.getenv('FRONTEND_BASE_URL', 'http://localhost:3000')
BACKEND_BASE_URL = os.getenv('BACKEND_BASE_URL', 'http://localhost:5001')

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
    
    # Subindustry peer filtering
    "min_valid_peers_for_median": 1,             # Minimum peers needed to calculate subindustry median
    "max_peer_drop_rate": 0.8,                   # Warning if >80% of peers dropped due to data issues
    
    # Expected returns calculation
    "min_observations_for_expected_returns": 12,  # Minimum months of data for reliable expected return calculation
    
    # CAPM regression calculation
    "min_observations_for_capm_regression": 24,   # Minimum months for reliable alpha/beta calculation (2 years)
    
    # Data quality warning thresholds
    "min_r2_for_rate_factors": 0.3,              # Minimum R² for rate factor regressions before warning
    "max_reasonable_interest_rate_beta": 25,     # Maximum reasonable interest rate beta before warning
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

# ═══════════════════════════════════════════════════════════════════════════════
# 🛠️ PROVIDER CAPABILITIES CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Provider Capabilities Configuration for Backend Routing Logic
# Defines the technical capabilities and features of each financial data provider
# Used by backend routing and provider health monitoring systems
#
# 🎯 PURPOSE:
# ===========
# This configuration provides capability metadata for provider routing decisions:
# • Backend provider routing and selection logic
# • Health monitoring and availability checks
# • API response metadata for routing explanations
# • Provider comparison for optimal routing decisions
#
# 🔗 INTEGRATION POINTS:
# =====================
# • **provider_routing_api.py**: Uses capabilities for routing decisions and API metadata
# • **Provider Health Monitoring**: Tracks capabilities for availability assessments
# • **Routing Logic**: Determines provider suitability based on required capabilities
# • **Analytics**: Capability tracking for provider performance metrics
#
# 🏗️ ARCHITECTURE NOTE:
# =====================
# UI/Visual configuration (colors, icons, descriptions) has been moved to:
# frontend/src/config/providers.ts - This ensures proper separation of concerns
# where frontend owns UI metadata and backend owns business logic.

PROVIDER_CAPABILITIES = {
    # ═══════════════════════════════════════════════════════════════════════════════
    # 📈 SNAPTRADE - Real-time Brokerage Specialist
    # ═══════════════════════════════════════════════════════════════════════════════
    "snaptrade": [
        "real_time_data",      # Live position updates and pricing
        "all_brokerages",      # Comprehensive brokerage institution support
        "trading",             # Trading capabilities and order management
        "options_trading",     # Options and advanced trading features
        "crypto_support"       # Cryptocurrency trading support
    ],
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 🏦 PLAID - Universal Financial Data Aggregator
    # ═══════════════════════════════════════════════════════════════════════════════
    "plaid": [
        "bank_accounts",       # Traditional banking (checking, savings, credit)
        "aggregation",         # Multi-institution data consolidation
        "read_only",          # Read-only access (no trading capabilities)
        "transaction_data",    # Detailed transaction history
        "credit_monitoring"    # Credit score and monitoring features
    ],
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # ✏️ MANUAL ENTRY - User-controlled Portfolio Management
    # ═══════════════════════════════════════════════════════════════════════════════
    "manual": [
        "custom_portfolios",   # User-defined portfolio structures
        "flexibility",         # Maximum customization and control
        "privacy",            # No external connections required
        "offline_mode"        # Works without internet connectivity
    ]
}

# 🏷️ CAPABILITY DEFINITIONS:
# ===========================
# Standard capability tags used for provider routing and feature comparison:
#
# **Data Quality & Timing:**
# • "real_time_data" - Live updates and current pricing
# • "aggregation" - Multi-source data consolidation
# • "transaction_data" - Detailed transaction history and categorization
# • "historical_data" - Historical price and transaction data
#
# **Institution Support:**
# • "all_brokerages" - Comprehensive brokerage coverage
# • "bank_accounts" - Traditional banking institution support
# • "crypto_exchanges" - Cryptocurrency platform integration
#
# **Trading & Management:**
# • "trading" - Active trading and order management
# • "options_trading" - Options and advanced trading strategies
# • "crypto_support" - Cryptocurrency trading and wallet management
# • "read_only" - View-only access without trading capabilities
#
# **Privacy & Control:**
# • "custom_portfolios" - User-defined portfolio structures
# • "flexibility" - Maximum customization and manual control
# • "privacy" - No external connections or data sharing required
# • "offline_mode" - Functionality available without internet connectivity
#
# **Additional Services:**
# • "credit_monitoring" - Credit score tracking and monitoring alerts
#
# 🔄 ADDING NEW PROVIDERS:
# ========================
# 1. Add new provider entry to PROVIDER_CAPABILITIES with appropriate capability tags
# 2. Update provider_routing_api.py routing logic if needed
# 3. Add institution mappings to INSTITUTION_PROVIDER_MAPPING below
# 4. Test routing decisions with new provider configuration
# 5. Update frontend provider display config in frontend/src/config/providers.ts

# Provider Routing Configuration
PROVIDER_ROUTING_CONFIG = {
    "enabled": True,
    "default_timeout": 30,  # seconds
    "max_fallback_time": 60,  # seconds
    "health_check_interval": 300,  # seconds
    "error_rate_threshold": 0.3,  # 30% error rate triggers degradation
}

# ═══════════════════════════════════════════════════════════════════════════════
# 🏦 INSTITUTION PROVIDER ROUTING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Institution Routing Mappings
# Maps institution slugs to supported providers with intelligent routing priority
# 
# 🎯 ROUTING STRATEGY:
# ===================
# 1. **Array Order = Priority**: First provider in array is preferred
# 2. **Brokerage Priority**: SnapTrade preferred for investment accounts (better data quality)
# 3. **Bank Priority**: Plaid preferred/only for traditional banking (specialized support)
# 4. **Fallback Logic**: If primary provider fails, system automatically tries secondary
# 5. **Health Monitoring**: Unhealthy providers are automatically skipped
#
# 🔗 INTEGRATION POINTS:
# =====================
# • Frontend: ProviderRoutingService.routeConnection() uses this mapping
# • Backend: /api/provider-routing/institution-support/{slug} endpoint
# • Routing API: provider_routing_api.py for real-time routing decisions
# • Health Checks: provider_routing.py monitors provider availability
#
# 📊 PROVIDER CAPABILITIES:
# ========================
# • **SnapTrade**: Specialized for brokerages (Schwab, Fidelity, TD, etc.)
#   - Real-time brokerage data, better investment account support
#   - Supports: Stock positions, options, crypto, retirement accounts
#   - Limitations: Limited traditional banking features
#
# • **Plaid**: Universal financial data provider
#   - Excellent banking support, broad institution coverage
#   - Supports: Checking/savings, credit cards, loans, some investments
#   - Limitations: Less detailed investment data for some brokerages
#
# 🛠️ CONFIGURATION EXAMPLES:
# ==========================
# ["snaptrade", "plaid"] = SnapTrade preferred, Plaid fallback
# ["plaid"]              = Plaid only (no alternatives)
# ["snaptrade"]          = SnapTrade only (rare, specific use cases)
#
# 🔄 DYNAMIC ROUTING FLOW:
# ========================
# 1. User selects institution (e.g., "charles_schwab")
# 2. ProviderRoutingService.routeConnection("charles_schwab") called
# 3. Backend checks INSTITUTION_PROVIDER_MAPPING["charles_schwab"] = ["snaptrade", "plaid"]
# 4. System attempts SnapTrade first (preferred for brokerages)
# 5. If SnapTrade unavailable/unhealthy, falls back to Plaid
# 6. Connection attempt routed to selected provider's API flow

INSTITUTION_PROVIDER_MAPPING = {
    # ═══════════════════════════════════════════════════════════════════════════════
    # 🏢 MAJOR TRADITIONAL BROKERAGES
    # ═══════════════════════════════════════════════════════════════════════════════
    # SnapTrade preferred for investment-focused institutions with better data quality
    # and real-time position tracking. Plaid as reliable fallback option.
    
    "charles_schwab": ["snaptrade", "plaid"],        # Large brokerage, excellent SnapTrade support
    "fidelity": ["snaptrade", "plaid"],             # Investment giant, strong both providers
    "td_ameritrade": ["snaptrade", "plaid"],        # Now part of Schwab, good SnapTrade integration
    "etrade": ["snaptrade", "plaid"],               # Popular online brokerage
    "interactive_brokers": ["snaptrade", "plaid"],  # Professional platform, international
    "vanguard": ["snaptrade", "plaid"],             # Low-cost index funds and ETFs
    "merrill_edge": ["snaptrade", "plaid"],         # Bank of America brokerage arm
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 🏦 TRADITIONAL BANKS
    # ═══════════════════════════════════════════════════════════════════════════════
    # Plaid specialized for banking services - checking, savings, credit cards, loans
    # SnapTrade not supported as these are primarily banking institutions
    
    "chase": ["plaid"],                             # JPMorgan Chase - largest US bank
    "bank_of_america": ["plaid"],                   # Major retail banking
    "wells_fargo": ["plaid"],                       # Large regional bank
    "citibank": ["plaid"],                          # Global banking institution
    "us_bank": ["plaid"],                           # Fifth largest bank in US
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 📱 MODERN DIGITAL INVESTMENT PLATFORMS
    # ═══════════════════════════════════════════════════════════════════════════════
    # Mix of SnapTrade and Plaid based on platform capabilities and data availability
    
    "robinhood": ["snaptrade", "plaid"],            # Popular mobile-first brokerage
    "webull": ["snaptrade"],                        # Commission-free trading, SnapTrade specialized
    "m1_finance": ["plaid"],                        # Automated investing, better Plaid integration
    "betterment": ["plaid"],                        # Robo-advisor, primarily Plaid supported
    "wealthfront": ["plaid"],                       # Automated investment management
}

# 📋 INSTITUTION SLUG NAMING CONVENTION:
# =====================================
# • lowercase_with_underscores format
# • No spaces, special characters, or numbers
# • Recognizable abbreviations for long names (td_ameritrade vs td_ameritrade_inc)
# • Consistent with both SnapTrade and Plaid institution identifiers where possible
#
# 🔄 ADDING NEW INSTITUTIONS:
# ===========================
# 1. Add entry to INSTITUTION_PROVIDER_MAPPING with appropriate provider priority
# 2. Test routing via /api/provider-routing/institution-support/{new_slug}
# 3. Update frontend institution selection UI if needed
# 4. Add display name mapping in provider_routing_api.py _get_institution_display_name()
# 5. Consider adding institution logo and categories for UI enhancement
