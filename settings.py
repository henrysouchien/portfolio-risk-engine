#Date settings for portfolio analysis are in settings.py
import os
from functools import lru_cache
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


# ═══════════════════════════════════════════════════════════════════════════════
# 🤖 MCP / CLI Default User Configuration
# ═══════════════════════════════════════════════════════════════════════════════

RISK_MODULE_USER_EMAIL_ENV = "RISK_MODULE_USER_EMAIL"


def _default_dotenv_path() -> Path:
    return Path(__file__).resolve().parent / ".env"


def _normalize_email_value(value: str | None) -> str | None:
    """Normalize env/file values and strip optional wrapping quotes."""
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
        normalized = normalized[1:-1].strip()
    return normalized or None


@lru_cache(maxsize=16)
def _read_key_from_env_file(file_path: str, key: str) -> str | None:
    """Read a key from a dotenv-style file without requiring dotenv import."""
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                current_key, raw_value = line.split("=", 1)
                if current_key.strip() != key:
                    continue
                value = raw_value.split("#", 1)[0].strip()
                return _normalize_email_value(value)
    except OSError:
        return None
    return None


def _read_env_or_dotenv(key: str, default: str | None = None) -> str | None:
    """Read a setting from runtime env first, then project .env fallback."""
    env_value = _normalize_email_value(os.getenv(key))
    if env_value is not None:
        return env_value

    dotenv_value = _read_key_from_env_file(str(_default_dotenv_path()), key)
    if dotenv_value is not None:
        return dotenv_value

    return default


def resolve_default_user() -> tuple[str | None, str]:
    """
    Resolve default user email for MCP/CLI flows.

    Resolution order:
    1) Runtime environment variable (`RISK_MODULE_USER_EMAIL`)
    2) Project `.env` file fallback
    """
    env_user = _normalize_email_value(os.getenv(RISK_MODULE_USER_EMAIL_ENV))
    if env_user:
        return env_user, "env"

    dotenv_user = _read_key_from_env_file(
        str(_default_dotenv_path()),
        RISK_MODULE_USER_EMAIL_ENV,
    )
    if dotenv_user:
        return dotenv_user, "dotenv"

    return None, "none"


def get_default_user_context() -> dict[str, object]:
    """Return user-resolution debug context for MCP diagnostics."""
    user, source = resolve_default_user()
    dotenv_path = _default_dotenv_path()
    return {
        "user_email": user,
        "source": source,
        "env_var": RISK_MODULE_USER_EMAIL_ENV,
        "dotenv_path": str(dotenv_path),
        "dotenv_exists": dotenv_path.exists(),
    }


def resolve_user_email(user_email: str | None = None) -> tuple[str | None, dict[str, object]]:
    """
    Resolve tool user_email with explicit argument taking precedence.
    Returns `(resolved_email, debug_context)`.
    """
    explicit_user = _normalize_email_value(user_email)
    context = get_default_user_context()

    if explicit_user:
        context["user_email"] = explicit_user
        context["source"] = "argument"
        return explicit_user, context

    return context["user_email"], context


def format_missing_user_error(context: dict[str, object] | None = None) -> str:
    """Build a consistent actionable error for missing user context."""
    ctx = context or get_default_user_context()
    dotenv_location = str(ctx.get("dotenv_path", _default_dotenv_path()))
    if not bool(ctx.get("dotenv_exists", False)):
        dotenv_location = f"{dotenv_location} (not found)"

    return (
        "No user specified and RISK_MODULE_USER_EMAIL not configured. "
        f"Checked user_email argument, env var {ctx.get('env_var', RISK_MODULE_USER_EMAIL_ENV)}, "
        f"and .env fallback at {dotenv_location}. "
        "Set RISK_MODULE_USER_EMAIL in MCP server config or pass user_email explicitly."
    )


def get_default_user() -> str | None:
    """
    Get the default user email for MCP tools and CLI commands.

    Reads from `RISK_MODULE_USER_EMAIL` env var first, then project `.env` fallback.
    """
    user, _source = resolve_default_user()
    return user

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
        "correlation_threshold": -0.2,
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

# ═══════════════════════════════════════════════════════════════════════════════
# 📊 TRANSACTION PROVIDER ROUTING
# ═══════════════════════════════════════════════════════════════════════════════
#
# Controls which provider supplies TRANSACTIONS for each institution.
# Position routing is configured separately in POSITION_ROUTING below.
# Transactions need explicit routing because Plaid may return activity for
# institutions that are also connected via direct providers (IBKR Flex,
# Schwab direct, SnapTrade).
#
# When an institution is listed here with a canonical transaction provider,
# Plaid transactions tagged with that institution's name are SKIPPED
# (filtered out at fetch time). This prevents:
# - Redundant duplicate data (Plaid IBKR + IBKR Flex)
# - Raw ticker variant leaks (Plaid AT. vs FMP AT.L)
# - Dedup overhead on known-redundant data
#
# Institutions NOT listed here: Plaid transactions pass through unchanged.

TRANSACTION_ROUTING = {
    # institution_slug → canonical transaction provider
    # When canonical != "plaid", Plaid transactions for this institution are skipped
    "interactive_brokers": "ibkr_flex",
    "charles_schwab": "schwab",
}

# Controls which provider supplies POSITIONS for each institution.
# Add institutions here as direct position providers become available.
# IBKR can be added once an IBKR position provider is wired up.
POSITION_ROUTING = {
    # institution_slug → canonical position provider
    "charles_schwab": "schwab",
}

# Default providers for institutions not explicitly routed.
# Keep both aggregators by default to avoid dropping data for single-aggregator institutions.
_default_position_providers_raw = os.getenv("DEFAULT_POSITION_PROVIDERS", "snaptrade,plaid")
DEFAULT_POSITION_PROVIDERS = [
    provider.strip().lower()
    for provider in _default_position_providers_raw.split(",")
    if provider.strip()
]

_default_transaction_providers_raw = os.getenv("DEFAULT_TRANSACTION_PROVIDERS", "snaptrade,plaid")
DEFAULT_TRANSACTION_PROVIDERS = [
    provider.strip().lower()
    for provider in _default_transaction_providers_raw.split(",")
    if provider.strip()
]

# Transaction fetch policy for source="all":
# - balanced: fetch all enabled/required providers, then partition by routing.
# - direct_first: prefer direct providers (ibkr_flex/schwab), and call aggregators
#   only for institutions without a healthy direct provider.
_transaction_fetch_policy_raw = os.getenv(
    "TRANSACTION_FETCH_POLICY",
    "direct_first",
).strip().lower()
if _transaction_fetch_policy_raw not in {"balanced", "direct_first"}:
    _transaction_fetch_policy_raw = "balanced"
TRANSACTION_FETCH_POLICY = _transaction_fetch_policy_raw

# Maps various provider institution name strings to canonical slugs.
# Plaid institution names come from AWS secret path: split("/")[-1].replace("-"," ").title()
# Uses substring matching (case-insensitive): if any alias appears as a substring
# of the institution name, it maps to that slug. This mirrors the existing
# _IBKR_INSTITUTION_NAMES pattern in trading_analysis/analyzer.py:43.
INSTITUTION_SLUG_ALIASES = {
    "interactive brokers": "interactive_brokers",
    "ibkr": "interactive_brokers",
    "charles schwab": "charles_schwab",
    "schwab": "charles_schwab",
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
IBKR_GATEWAY_HOST = os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1")
IBKR_GATEWAY_PORT = int(os.getenv("IBKR_GATEWAY_PORT", "7496"))  # 7496=TWS live, 7497=TWS paper, 4001=Gateway live, 4002=Gateway paper
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))
IBKR_TIMEOUT = int(os.getenv("IBKR_TIMEOUT", "10"))
IBKR_READONLY = os.getenv("IBKR_READONLY", "false").lower() == "true"
IBKR_AUTHORIZED_ACCOUNTS = [
    a.strip() for a in os.getenv("IBKR_AUTHORIZED_ACCOUNTS", "").split(",") if a.strip()
]
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
SCHWAB_APP_KEY = _read_env_or_dotenv("SCHWAB_APP_KEY", "") or ""
SCHWAB_APP_SECRET = _read_env_or_dotenv("SCHWAB_APP_SECRET", "") or ""
SCHWAB_CALLBACK_URL = _read_env_or_dotenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182") or "https://127.0.0.1:8182"
SCHWAB_TOKEN_PATH = os.path.expanduser(
    _read_env_or_dotenv("SCHWAB_TOKEN_PATH", "~/.schwab_token.json") or "~/.schwab_token.json"
)
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
