"""
Core Constants Module

Centralized definitions for asset classes, security types, and other system constants.
This prevents hardcoded values scattered throughout the codebase and ensures consistency.
"""

# Asset Class Constants
# =====================
# These are the canonical asset classes supported by the system.
# Used for validation, UI display, and business logic throughout the application.

VALID_ASSET_CLASSES = {
    'equity',       # Stocks, equities
    'bond',         # Fixed income securities
    'real_estate',  # REITs, real estate investments
    'commodity',    # Gold, oil, agricultural products
    'crypto',       # Cryptocurrencies (BTC, ETH, etc.)
    'cash',         # Cash equivalents, money market
    'mixed',        # Multi-asset funds, balanced funds
    'unknown'       # Fallback for unclassifiable securities
}

# Asset Class Display Names
# ========================
# Human-readable names for frontend display

ASSET_CLASS_DISPLAY_NAMES = {
    'equity': 'Equity',
    'bond': 'Fixed Income', 
    'real_estate': 'Real Estate',
    'commodity': 'Commodities',
    'crypto': 'Cryptocurrency',
    'cash': 'Cash',
    'mixed': 'Mixed Assets',
    'unknown': 'Other'
}

# Asset Class Colors (for UI)
# ===========================
# Consistent color scheme for charts and displays

ASSET_CLASS_COLORS = {
    'equity': 'bg-blue-500',
    'bond': 'bg-emerald-500',
    'real_estate': 'bg-amber-500', 
    'commodity': 'bg-orange-500',
    'crypto': 'bg-purple-500',
    'cash': 'bg-gray-500',
    'mixed': 'bg-neutral-500',
    'unknown': 'bg-neutral-400'
}

# Security Type Constants  
# =======================
# Canonical security types used by SecurityTypeService

VALID_SECURITY_TYPES = {
    'equity',       # Regular stocks
    'etf',          # Exchange-traded funds
    'mutual_fund',  # Mutual funds
    'bond',         # Bonds and fixed income
    'cash',         # Cash and cash equivalents
    'crypto',       # Cryptocurrencies
    'commodity',    # Commodity investments
    'derivative',   # Options, futures, etc.
    'warrant',      # Warrants
    'fund'          # Generic fund type
}

# Diversified Security Types
# =========================
# Security types that represent diversified baskets rather than single issuers.
# These are exempt from single-company concentration checks.

DIVERSIFIED_SECURITY_TYPES = {
    'etf',
    'fund',
    'mutual_fund',
}

# Cache Configuration
# ==================
# TTL and cache settings used across the system

CACHE_TTL_DAYS = 90  # Database cache TTL for security types and asset classes
STALE_THRESHOLD_DAYS = 90  # When to consider cached data stale

# Security Type to Asset Class Mappings
# ====================================
# Business logic for mapping security types to asset classes

SECURITY_TYPE_TO_ASSET_CLASS = {
    'equity': 'equity',           # Fallback for regular stocks after FMP Industry analysis
    'cash': 'cash',               # Cash positions and money market
    'bond': 'bond',               # Bonds and fixed income
    'crypto': 'crypto',           # Cryptocurrency
    'commodity': 'commodity',     # Commodity funds
    'etf': 'mixed',              # ETFs need deeper analysis
    'fund': 'mixed',             # Mutual funds need deeper analysis
    'mutual_fund': 'mixed',      # Plaid mutual funds need deeper analysis
    'warrant': 'derivative',     # Warrants are derivative instruments
    'derivative': 'derivative',   # Derivatives - separate category (not asset class)
}

# Validation Functions
# ===================

def is_valid_asset_class(asset_class: str) -> bool:
    """Check if an asset class is valid."""
    return asset_class in VALID_ASSET_CLASSES

def is_valid_security_type(security_type: str) -> bool:
    """Check if a security type is valid."""
    return security_type in VALID_SECURITY_TYPES

def get_asset_class_display_name(asset_class: str) -> str:
    """Get human-readable display name for asset class."""
    return ASSET_CLASS_DISPLAY_NAMES.get(asset_class, asset_class.title())

def get_asset_class_color(asset_class: str) -> str:
    """Get UI color class for asset class."""
    return ASSET_CLASS_COLORS.get(asset_class, 'bg-neutral-500')

def map_security_type_to_asset_class(security_type: str) -> str:
    """Map security type to asset class using centralized business logic."""
    return SECURITY_TYPE_TO_ASSET_CLASS.get(security_type)
