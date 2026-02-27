# Security Type Mapping Implementation Plan

## Overview

This document outlines the implementation plan for centralizing security type mappings using the established 3-tier architecture pattern (Database → YAML → Hardcoded fallback) that is already used for industry, cash, and exchange mappings.

## The 3-Tier Architecture Pattern

The risk module uses a consistent 3-tier pattern for all reference data mappings that provides optimal performance, reliability, and maintainability:

### **Tier 1: Database (Primary Source)**
- **Purpose**: High-performance caching and centralized management
- **Performance**: ~10ms query time
- **Benefits**: Consistent across users, admin manageable, audit trail

### **Tier 2: YAML Configuration (Reliable Fallback)**
- **Purpose**: Fallback when database unavailable
- **Performance**: ~1ms file read
- **Benefits**: Version controlled, human readable, deployment independent

### **Tier 3: Hardcoded Dictionary (Ultimate Fallback)**
- **Purpose**: Guarantee system availability
- **Performance**: ~0.001ms memory access
- **Benefits**: No external dependencies, always available

## Existing 3-Tier Implementations

### **Industry Mappings** (`utils/etf_mappings.py`)
```python
def get_etf_to_industry_map() -> Dict[str, str]:
    try:
        # Tier 1: Database first
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            industry_to_etf = db_client.get_industry_mappings()
            return {etf: industry for industry, etf in industry_to_etf.items()}
    except:
        try:
            # Tier 2: YAML fallback
            with open('industry_to_etf.yaml', 'r') as f:
                industry_to_etf = yaml.safe_load(f)
            return {etf: industry for industry, etf in industry_to_etf.items()}
        except:
            # Tier 3: Hardcoded fallback
            return {
                "XLK": "Technology",
                "XLF": "Financial Services",
                "XLV": "Healthcare",
                # ... more mappings
            }
```

### **Cash Mappings** (`run_portfolio_risk.py`)
```python
def get_cash_positions():
    try:
        # Tier 1: Database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            cash_map = db_client.get_cash_mappings()
            return set(cash_map.get("proxy_by_currency", {}).values())
    except Exception as e:
        try:
            # Tier 2: YAML fallback
            with open("cash_map.yaml", "r") as f:
                cash_map = yaml.safe_load(f)
                return set(cash_map.get("proxy_by_currency", {}).values())
        except FileNotFoundError:
            # Tier 3: Hardcoded fallback
            return {"SGOV", "ESTR", "IB01", "CASH", "USD"}
```

### **Exchange Mappings** (`proxy_builder.py`)
```python
def load_exchange_proxy_map(path: str = "exchange_etf_proxies.yaml") -> dict:
    try:
        # Tier 1: Database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            return db_client.get_exchange_mappings()
    except Exception as e:
        # Tier 2: YAML fallback
        database_logger.warning(f"Database unavailable ({e}), using {path} fallback")
        with open(path, "r") as f:
            return yaml.safe_load(f)
        # Tier 3: Hardcoded fallback handled by caller
```

## Supporting Infrastructure

### **Database Schema** (`database/schema.sql`)
```sql
-- Industry mappings
CREATE TABLE industry_proxies (
    industry VARCHAR(100) PRIMARY KEY,
    proxy_etf VARCHAR(10) NOT NULL
);

-- Cash mappings
CREATE TABLE cash_proxies (
    currency VARCHAR(3) PRIMARY KEY,
    proxy_etf VARCHAR(10) NOT NULL
);

-- Exchange mappings
CREATE TABLE exchange_proxies (
    exchange VARCHAR(10) NOT NULL,
    factor_type VARCHAR(20) NOT NULL,
    proxy_etf VARCHAR(10) NOT NULL,
    PRIMARY KEY (exchange, factor_type)
);
```

### **YAML Configuration Files**
- `industry_to_etf.yaml` - Industry to ETF mappings
- `cash_map.yaml` - Currency and cash alias mappings
- `exchange_etf_proxies.yaml` - Exchange to factor ETF mappings

### **DatabaseClient Methods** (`inputs/database_client.py`)
- `get_industry_mappings()` - Retrieve industry mappings
- `get_cash_mappings()` - Retrieve cash proxy mappings
- `get_exchange_mappings()` - Retrieve exchange mappings

### **Admin Management** (`admin/migrate_reference_data.py`)
- `migrate_industry_mappings()` - YAML to database migration
- `migrate_cash_mappings()` - YAML to database migration
- `migrate_exchange_mappings()` - YAML to database migration

## Security Type Mappings: The Missing Piece

Currently, security type mappings are the **only mapping type** that doesn't follow this pattern:

### **Current Scattered State**
- **SnapTrade**: Hardcoded dict in `snaptrade_loader.py`
- **FMP**: Hardcoded logic in `security_type_service.py`
- **Risk Scoring**: Hardcoded dict in `settings.py`

### **Target State: Consistent 3-Tier Pattern**
```python
# New security type mapping (following established pattern)
def get_security_type_mappings() -> Dict[str, Dict[str, str]]:
    try:
        # Tier 1: Database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            return db_client.get_security_type_mappings()
    except Exception as e:
        try:
            # Tier 2: YAML fallback
            with open('security_type_mappings.yaml', 'r') as f:
                config = yaml.safe_load(f)
                return config.get('provider_mappings', {})
        except:
            # Tier 3: Hardcoded fallback
            return {
                "snaptrade": {'oef': 'mutual_fund', 'cef': 'mutual_fund'},
                "fmp": {'isEtf': 'etf', 'isFund': 'mutual_fund'}
            }
```

This implementation will achieve **perfect architectural consistency** across all mapping types in the risk module.

## Current State Analysis

### Existing Mapping Architecture
All other mapping types follow a consistent 3-tier pattern:

1. **Industry Mappings**: ✅ Database → YAML → Hardcoded (FULLY IMPLEMENTED)
2. **Cash Mappings**: ✅ Database → YAML → Hardcoded (FULLY IMPLEMENTED)  
3. **Exchange Mappings**: ✅ Database → YAML → Hardcoded (FULLY IMPLEMENTED)
4. **Security Type Mappings**: ❌ Hardcoded only (NEEDS IMPLEMENTATION)

### Current Security Type Mapping Issues
Security type mappings are currently scattered across multiple files:

- **SnapTrade Loader** (`snaptrade_loader.py` line 624): Hardcoded dict
- **FMP/SecurityTypeService** (`security_type_service.py` line 281): Hardcoded logic
- **Risk Scoring** (`settings.py`): Hardcoded dict
- **Plaid Loader** (`plaid_loader.py`): Strategy-based (preserve non-equity types)

## Implementation Plan

### 1. Database Schema Changes

Add to `database/schema.sql`:

```sql
-- ============================================================================
-- SECURITY TYPE MAPPING TABLES
-- ============================================================================

-- Security type provider mappings
-- Maps provider-specific codes to canonical internal types
CREATE TABLE security_type_mappings (
    provider VARCHAR(20) NOT NULL,           -- 'snaptrade', 'fmp', 'plaid'
    provider_code VARCHAR(50) NOT NULL,      -- 'oef', 'isEtf', etc.
    canonical_type VARCHAR(20) NOT NULL,     -- 'mutual_fund', 'etf', 'equity', etc.
    description TEXT,                        -- Human-readable description
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (provider, provider_code)
);

-- Security type crash scenario mappings
-- Maps canonical security types to their risk scenarios
CREATE TABLE security_type_scenarios (
    security_type VARCHAR(20) PRIMARY KEY,   -- 'equity', 'etf', 'mutual_fund', etc.
    crash_scenario VARCHAR(50) NOT NULL,     -- 'single_stock_crash', 'etf_crash', etc.
    crash_percentage DECIMAL(5,3) NOT NULL,  -- 0.80, 0.35, 0.40, etc.
    description TEXT,                        -- Human-readable description
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- SECURITY TYPE MAPPING INDEXES
-- ============================================================================

CREATE INDEX idx_security_type_mappings_provider ON security_type_mappings(provider);
CREATE INDEX idx_security_type_mappings_canonical ON security_type_mappings(canonical_type);

-- ============================================================================
-- DEFAULT SECURITY TYPE MAPPING DATA
-- ============================================================================

-- SnapTrade provider mappings
INSERT INTO security_type_mappings (provider, provider_code, canonical_type, description) VALUES
    ('snaptrade', 'oef', 'mutual_fund', 'Open Ended Fund'),
    ('snaptrade', 'cef', 'mutual_fund', 'Closed End Fund'),
    ('snaptrade', 'et', 'etf', 'Exchange Traded Fund'),
    ('snaptrade', 'cs', 'equity', 'Common Stock'),
    ('snaptrade', 'ps', 'equity', 'Preferred Stock'),
    ('snaptrade', 'ad', 'equity', 'American Depositary Receipt'),
    ('snaptrade', 'ut', 'equity', 'Unit Trust'),
    ('snaptrade', 'wi', 'equity', 'When Issued'),
    ('snaptrade', 'bnd', 'bond', 'Bond'),
    ('snaptrade', 'crypto', 'crypto', 'Cryptocurrency'),
    ('snaptrade', 'rt', 'warrant', 'Rights'),
    ('snaptrade', 'wt', 'warrant', 'Warrants'),
    ('snaptrade', 'struct', 'derivative', 'Structured Product'),
    ('snaptrade', 'cash', 'cash', 'Cash Balance')
ON CONFLICT (provider, provider_code) DO NOTHING;

-- FMP provider mappings
INSERT INTO security_type_mappings (provider, provider_code, canonical_type, description) VALUES
    ('fmp', 'isEtf', 'etf', 'FMP ETF Flag'),
    ('fmp', 'isFund', 'mutual_fund', 'FMP Fund Flag'),
    ('fmp', 'CUR:', 'cash', 'FMP Currency Prefix')
ON CONFLICT (provider, provider_code) DO NOTHING;

-- Risk scenario mappings
INSERT INTO security_type_scenarios (security_type, crash_scenario, crash_percentage, description) VALUES
    ('equity', 'single_stock_crash', 0.80, 'Individual stock failure (Enron, Lehman Brothers)'),
    ('etf', 'etf_crash', 0.35, 'Diversified ETF crash (market-like risk)'),
    ('mutual_fund', 'mutual_fund_crash', 0.40, 'Mutual fund crash (moderate diversification)'),
    ('cash', 'cash_crash', 0.05, 'Cash equivalent risk (money market funds)'),
    ('bond', 'bond_crash', 0.30, 'Bond market crash'),
    ('crypto', 'crypto_crash', 0.90, 'Cryptocurrency crash'),
    ('derivative', 'derivative_crash', 0.95, 'Derivative instrument failure'),
    ('warrant', 'warrant_crash', 0.85, 'Warrant expiration/failure')
ON CONFLICT (security_type) DO NOTHING;
```

### 2. YAML Configuration File

Create `security_type_mappings.yaml`:

```yaml
# Security Type Mapping Configuration
# Fallback configuration when database is unavailable

# Provider-specific mappings to canonical types
provider_mappings:
  snaptrade:
    oef: mutual_fund    # Open Ended Fund
    cef: mutual_fund    # Closed End Fund
    et: etf             # Exchange Traded Fund
    cs: equity          # Common Stock
    ps: equity          # Preferred Stock
    ad: equity          # American Depositary Receipt
    ut: equity          # Unit Trust
    wi: equity          # When Issued
    bnd: bond           # Bond
    crypto: crypto      # Cryptocurrency
    rt: warrant         # Rights
    wt: warrant         # Warrants
    struct: derivative  # Structured Product
    cash: cash          # Cash Balance
  
  fmp:
    isEtf: etf          # FMP ETF flag
    isFund: mutual_fund # FMP Fund flag
    "CUR:": cash        # FMP Currency prefix
  
  plaid:
    # Plaid uses pass-through strategy
    # Preserve all non-equity types, enhance only equity types
    preserve_non_equity: true

# Risk scenario mappings
crash_scenarios:
  # Currently used crash scenarios (match settings.py)
  equity: single_stock_crash      # 80% - Individual stock failure
  etf: etf_crash                  # 35% - Diversified ETF crash
  mutual_fund: mutual_fund_crash  # 40% - Mutual fund crash
  cash: cash_crash                # 5% - Cash equivalent risk
  
  # Proposed future crash scenarios (not currently used)
  bond: bond_crash                # 30% - Bond market crash
  crypto: crypto_crash            # 90% - Cryptocurrency crash
  derivative: derivative_crash    # 95% - Derivative failure
  warrant: warrant_crash          # 85% - Warrant failure

# Canonical security types (for validation)
canonical_types:
  # Currently used types
  - equity
  - etf
  - mutual_fund
  - cash
  # Proposed future types (not currently used)
  - bond
  - crypto
  - derivative
  - warrant

# Provider strategies
provider_strategies:
  snaptrade: direct_mapping       # Use mapping table directly
  fmp: profile_analysis          # Analyze FMP profile fields
  plaid: selective_enhancement   # Preserve non-equity, enhance equity only
```

### 3. DatabaseClient Methods

Add to `inputs/database_client.py`:

```python
@log_error_handling("medium")
@handle_database_error
def get_security_type_mappings(self) -> Dict[str, Dict[str, str]]:
    """
    Get security type mappings from database.
    
    Returns:
        Dict mapping provider to {provider_code: canonical_type}
        Example: {"snaptrade": {"oef": "mutual_fund", "et": "etf"}}
    """
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT provider, provider_code, canonical_type 
            FROM security_type_mappings 
            ORDER BY provider, provider_code
        """)
        
        mappings = {}
        for row in cursor.fetchall():
            provider = row['provider']
            if provider not in mappings:
                mappings[provider] = {}
            mappings[provider][row['provider_code']] = row['canonical_type']
        
        return mappings

@log_error_handling("medium")
@handle_database_error
def get_security_type_scenarios(self) -> Dict[str, str]:
    """
    Get security type crash scenarios from database.
    
    Returns:
        Dict mapping security_type to crash_scenario
        Example: {"equity": "single_stock_crash", "etf": "etf_crash"}
    """
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT security_type, crash_scenario 
            FROM security_type_scenarios 
            ORDER BY security_type
        """)
        
        return {row['security_type']: row['crash_scenario'] for row in cursor.fetchall()}

@log_error_handling("medium")
@handle_database_error
def get_security_type_crash_percentages(self) -> Dict[str, float]:
    """
    Get security type crash percentages from database.
    
    Returns:
        Dict mapping security_type to crash_percentage
        Example: {"equity": 0.80, "etf": 0.35}
    """
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT security_type, crash_percentage 
            FROM security_type_scenarios 
            ORDER BY security_type
        """)
        
        return {row['security_type']: float(row['crash_percentage']) for row in cursor.fetchall()}

@log_error_handling("medium")
@handle_database_error
def update_security_type_mapping(self, provider: str, provider_code: str, canonical_type: str, description: str = None):
    """Update or insert security type mapping"""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO security_type_mappings (provider, provider_code, canonical_type, description, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (provider, provider_code) DO UPDATE SET
                canonical_type = EXCLUDED.canonical_type,
                description = EXCLUDED.description,
                updated_at = CURRENT_TIMESTAMP
        """, (provider, provider_code, canonical_type, description))
        conn.commit()

@log_error_handling("medium")
@handle_database_error
def update_security_type_scenario(self, security_type: str, crash_scenario: str, crash_percentage: float, description: str = None):
    """Update or insert security type crash scenario"""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO security_type_scenarios (security_type, crash_scenario, crash_percentage, description, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (security_type) DO UPDATE SET
                crash_scenario = EXCLUDED.crash_scenario,
                crash_percentage = EXCLUDED.crash_percentage,
                description = EXCLUDED.description,
                updated_at = CURRENT_TIMESTAMP
        """, (security_type, crash_scenario, crash_percentage, description))
        conn.commit()
```

### 4. Utility Module

Create `utils/security_type_mappings.py`:

```python
"""
Security Type Mapping Utilities

Provides centralized access to security type mappings using the established 3-tier pattern:
1. Database first (performance + consistency)
2. YAML fallback (reliability)
3. Hardcoded fallback (availability)

This follows the same pattern as industry_mappings, cash_mappings, and exchange_mappings.
"""

import yaml
from typing import Dict, Optional
from pathlib import Path

# Import existing logging infrastructure
from utils.logging import (
    log_error_handling,
    log_performance_tracking,
    database_logger,
    portfolio_logger
)

def get_security_type_mappings() -> Dict[str, Dict[str, str]]:
    """
    Get security type mappings using 3-tier pattern.
    
    Returns:
        Dict mapping provider to {provider_code: canonical_type}
        Example: {"snaptrade": {"oef": "mutual_fund", "et": "etf"}}
    """
    try:
        # 1. Database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            mappings = db_client.get_security_type_mappings()
            database_logger.info(f"✅ Security type mappings loaded from database: {len(mappings)} providers")
            return mappings
    except Exception as e:
        database_logger.warning(f"⚠️ Database unavailable for security type mappings: {e}")
        portfolio_logger.info("🔄 Falling back to YAML configuration for security type mappings")
        
        try:
            # 2. YAML fallback
            yaml_path = Path("security_type_mappings.yaml")
            if yaml_path.exists():
                with open(yaml_path, 'r') as f:
                    config = yaml.safe_load(f)
                    mappings = config.get('provider_mappings', {})
                    portfolio_logger.info(f"✅ Security type mappings loaded from YAML: {len(mappings)} providers")
                    return mappings
            else:
                portfolio_logger.warning(f"⚠️ YAML file not found: {yaml_path}")
        except Exception as yaml_error:
            portfolio_logger.warning(f"⚠️ YAML fallback failed: {yaml_error}")
        
        # 3. Hardcoded fallback
        hardcoded_mappings = {
            "snaptrade": {
                'oef': 'mutual_fund',  # Open Ended Fund
                'cef': 'mutual_fund',  # Closed End Fund
                'et': 'etf',           # ETF
                'cs': 'equity',        # Common Stock
                'ps': 'equity',        # Preferred Stock
                'ad': 'equity',        # ADR
                'ut': 'equity',        # Unit
                'wi': 'equity',        # When Issued
                'bnd': 'bond',         # Bond
                'crypto': 'crypto',    # Cryptocurrency
                'rt': 'warrant',       # Right
                'wt': 'warrant',       # Warrant
                'struct': 'derivative', # Structured Product
                'cash': 'cash',        # Cash Balance
            },
            "fmp": {
                'isEtf': 'etf',
                'isFund': 'mutual_fund',
                'CUR:': 'cash'
            }
        }
        portfolio_logger.info(f"🔧 Using hardcoded security type mappings: {len(hardcoded_mappings)} providers")
        return hardcoded_mappings

def get_crash_scenario_mappings() -> Dict[str, str]:
    """
    Get crash scenario mappings using 3-tier pattern.
    
    Returns:
        Dict mapping security_type to crash_scenario
        Example: {"equity": "single_stock_crash", "etf": "etf_crash"}
    """
    try:
        # 1. Database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            scenarios = db_client.get_security_type_scenarios()
            logger.debug(f"Retrieved crash scenarios from database: {len(scenarios)} types")
            return scenarios
    except Exception as e:
        logger.warning(f"Database unavailable for crash scenarios ({e}), using YAML fallback")
        
        try:
            # 2. YAML fallback
            yaml_path = Path("security_type_mappings.yaml")
            if yaml_path.exists():
                with open(yaml_path, 'r') as f:
                    config = yaml.safe_load(f)
                    scenarios = config.get('crash_scenarios', {})
                    logger.debug(f"Retrieved crash scenarios from YAML: {len(scenarios)} types")
                    return scenarios
            else:
                logger.warning(f"YAML file not found: {yaml_path}")
        except Exception as yaml_error:
            logger.warning(f"YAML fallback failed ({yaml_error}), using hardcoded fallback")
        
        # 3. Hardcoded fallback
        hardcoded_scenarios = {
            # Currently used crash scenarios (match settings.py)
            "equity": "single_stock_crash",      # 80%
            "etf": "etf_crash",                  # 35%
            "mutual_fund": "mutual_fund_crash",  # 40%
            "cash": "cash_crash",                # 5%
            
            # Proposed future crash scenarios (not currently used)
            "bond": "bond_crash",                # 30%
            "crypto": "crypto_crash",            # 90%
            "derivative": "derivative_crash",    # 95%
            "warrant": "warrant_crash"           # 85%
        }
        logger.info(f"Using hardcoded crash scenarios: {len(hardcoded_scenarios)} types")
        return hardcoded_scenarios

def get_snaptrade_mapping() -> Dict[str, str]:
    """Get SnapTrade-specific security type mapping"""
    mappings = get_security_type_mappings()
    return mappings.get('snaptrade', {})

def get_fmp_mapping() -> Dict[str, str]:
    """Get FMP-specific security type mapping"""
    mappings = get_security_type_mappings()
    return mappings.get('fmp', {})

@log_performance_tracking("snaptrade_mapping")
def map_snaptrade_code(snaptrade_code: str) -> Optional[str]:
    """
    Map SnapTrade code to canonical security type.
    
    Args:
        snaptrade_code: SnapTrade security type code (e.g., 'oef', 'et')
        
    Returns:
        Canonical security type or None if not found
    """
    portfolio_logger.debug(f"🔍 Mapping SnapTrade code: {snaptrade_code}")
    
    mapping = get_snaptrade_mapping()
    result = mapping.get(snaptrade_code.lower())
    
    if result:
        portfolio_logger.info(f"✅ SnapTrade mapping: {snaptrade_code} → {result}")
    else:
        portfolio_logger.warning(f"⚠️ Unknown SnapTrade code: {snaptrade_code}")
    
    return result

@log_performance_tracking("fmp_mapping")
def map_fmp_profile(profile: dict) -> Optional[str]:
    """
    Map FMP profile to canonical security type.
    
    Args:
        profile: FMP profile dictionary
        
    Returns:
        Canonical security type or None if not determined
    """
    if not profile:
        portfolio_logger.debug("🔍 FMP profile is empty, returning None")
        return None
    
    ticker = profile.get('symbol', profile.get('ticker', 'UNKNOWN'))
    portfolio_logger.debug(f"🔍 Mapping FMP profile for {ticker}")
        
    mapping = get_fmp_mapping()
    
    # Check FMP flags with detailed logging
    if profile.get("isEtf", False):
        result = mapping.get('isEtf', 'etf')
        portfolio_logger.info(f"✅ FMP mapping: {ticker} [isEtf=True] → {result}")
        return result
    elif profile.get("isFund", False):
        result = mapping.get('isFund', 'mutual_fund')
        portfolio_logger.info(f"✅ FMP mapping: {ticker} [isFund=True] → {result}")
        return result
    elif profile.get("ticker", "").startswith("CUR:"):
        result = mapping.get('CUR:', 'cash')
        portfolio_logger.info(f"✅ FMP mapping: {ticker} [ticker pattern] → {result}")
        return result
    
    portfolio_logger.debug(f"🔍 No FMP mapping found for {ticker}, returning None")
    return None

def get_crash_scenario(security_type: str) -> Optional[str]:
    """
    Get crash scenario for security type.
    
    Args:
        security_type: Canonical security type
        
    Returns:
        Crash scenario name or None if not found
    """
    scenarios = get_crash_scenario_mappings()
    return scenarios.get(security_type)

def validate_canonical_type(security_type: str) -> bool:
    """
    Validate that a security type is a recognized canonical type.
    
    Args:
        security_type: Security type to validate
        
    Returns:
        True if valid canonical type
    """
    try:
        # Try YAML first for canonical types list
        yaml_path = Path("security_type_mappings.yaml")
        if yaml_path.exists():
            with open(yaml_path, 'r') as f:
                config = yaml.safe_load(f)
                canonical_types = config.get('canonical_types', [])
                return security_type in canonical_types
    except:
        pass
    
    # Hardcoded fallback
    canonical_types = {'equity', 'etf', 'mutual_fund', 'cash', 'bond', 'crypto', 'derivative', 'warrant'}
    return security_type in canonical_types
```

### 5. Migration Script

Add to `admin/migrate_reference_data.py`:

```python
def migrate_security_type_mappings(db_client):
    """Migrate security type mappings from YAML to database"""
    print("\n🔐 Migrating security type mappings...")
    
    # Load security type mappings from YAML
    config = load_yaml_file("../security_type_mappings.yaml")
    
    if not config:
        print("⚠️  No security type mapping data found in security_type_mappings.yaml")
        return
    
    # Migrate provider mappings
    provider_mappings = config.get('provider_mappings', {})
    mapping_count = 0
    
    for provider, mappings in provider_mappings.items():
        if provider == 'plaid':
            continue  # Skip Plaid - it uses strategy-based approach
            
        print(f"  Processing provider: {provider}")
        
        for provider_code, canonical_type in mappings.items():
            try:
                db_client.update_security_type_mapping(provider, provider_code, canonical_type)
                print(f"    ✅ {provider}/{provider_code} → {canonical_type}")
                mapping_count += 1
            except Exception as e:
                print(f"    ❌ Failed to migrate {provider}/{provider_code}: {e}")
    
    # Migrate crash scenarios
    crash_scenarios = config.get('crash_scenarios', {})
    scenario_count = 0
    
    print(f"  Processing crash scenarios...")
    for security_type, crash_scenario in crash_scenarios.items():
        try:
            # Get crash percentage from settings (would need to be enhanced)
            # Crash percentages for all security types (current + proposed)
            crash_percentage = {
                # Currently used (match settings.py)
                'equity': 0.80,
                'etf': 0.35,
                'mutual_fund': 0.40,
                'cash': 0.05,
                # Proposed future scenarios
                'bond': 0.30,
                'crypto': 0.90,
                'derivative': 0.95,
                'warrant': 0.85
            }.get(security_type, 0.50)
            
            db_client.update_security_type_scenario(security_type, crash_scenario, crash_percentage)
            print(f"    ✅ {security_type} → {crash_scenario} ({crash_percentage:.0%})")
            scenario_count += 1
        except Exception as e:
            print(f"    ❌ Failed to migrate {security_type}: {e}")
    
    print(f"🔐 Successfully migrated {mapping_count} security type mappings and {scenario_count} crash scenarios")

# Update main migration function
def main():
    """Run all reference data migrations"""
    print("🚀 Starting reference data migration...")
    
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            
            # Run all migrations
            migrate_cash_mappings(db_client)
            migrate_exchange_mappings(db_client)
            migrate_industry_mappings(db_client)
            migrate_security_type_mappings(db_client)  # Add this line
            
            verify_migration(db_client)
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False
    
    print("✅ Reference data migration completed successfully!")
    return True
```

### 6. Admin Management Script

Add to `admin/manage_reference_data.py`:

```python
def manage_security_types(action, *args):
    """Manage security type mappings"""
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            
            if action == "list":
                mappings = db_client.get_security_type_mappings()
                scenarios = db_client.get_security_type_scenarios()
                
                print("\n📋 Security Type Mappings:")
                for provider, provider_mappings in mappings.items():
                    print(f"\n  {provider.upper()}:")
                    for code, canonical_type in provider_mappings.items():
                        print(f"    {code} → {canonical_type}")
                
                print("\n💥 Crash Scenarios:")
                for security_type, scenario in scenarios.items():
                    print(f"    {security_type} → {scenario}")
                    
            elif action == "add-mapping":
                if len(args) < 3:
                    print("Usage: security-type add-mapping <provider> <provider_code> <canonical_type> [description]")
                    return
                
                provider, provider_code, canonical_type = args[0], args[1], args[2]
                description = args[3] if len(args) > 3 else None
                
                db_client.update_security_type_mapping(provider, provider_code, canonical_type, description)
                print(f"✅ Added mapping: {provider}/{provider_code} → {canonical_type}")
                
            elif action == "add-scenario":
                if len(args) < 3:
                    print("Usage: security-type add-scenario <security_type> <crash_scenario> <crash_percentage> [description]")
                    return
                
                security_type, crash_scenario = args[0], args[1]
                crash_percentage = float(args[2])
                description = args[3] if len(args) > 3 else None
                
                db_client.update_security_type_scenario(security_type, crash_scenario, crash_percentage, description)
                print(f"✅ Added scenario: {security_type} → {crash_scenario} ({crash_percentage:.0%})")
                
            else:
                print("Available actions: list, add-mapping, add-scenario")
                
    except Exception as e:
        print(f"❌ Error managing security types: {e}")

# Update main function to include security-type command
def main():
    if len(sys.argv) < 2:
        print("Usage: python manage_reference_data.py <type> <action> [args...]")
        print("Types: cash, exchange, industry, security-type")
        return
    
    data_type = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else "list"
    args = sys.argv[3:]
    
    if data_type == "security-type":
        manage_security_types(action, *args)
    # ... existing handlers for cash, exchange, industry
```

## Integration Points

### Files to Update

1. **SnapTrade Loader** (`snaptrade_loader.py`):
   - Replace hardcoded `code_mapping` dict with `get_snaptrade_mapping()`
   - Update `_map_snaptrade_code_to_internal()` function

2. **SecurityTypeService** (`services/security_type_service.py`):
   - Replace hardcoded FMP logic with `map_fmp_profile()`
   - Update `normalize_fmp_profile()` method

3. **Settings** (`settings.py`):
   - Replace `SECURITY_TYPE_CRASH_MAPPING` with `get_crash_scenario_mappings()`
   - Update risk scoring functions to use centralized mappings

4. **Portfolio Risk Score** (`portfolio_risk_score.py`):
   - Update crash scenario lookups to use `get_crash_scenario()`

## Benefits

1. **Perfect Consistency**: Same 3-tier pattern as all other mappings
2. **Centralized Management**: Single source of truth for all security type logic
3. **Admin Tools**: Reuse existing admin infrastructure and patterns
4. **Reliability**: Database → YAML → Hardcoded fallback ensures availability
5. **Performance**: Database caching like other mapping types
6. **Maintainability**: Easy to add new providers or security types
7. **Auditability**: Database tracks all changes with timestamps

## Refactoring Analysis

### Components Requiring Refactoring

Based on codebase analysis, the following components have hardcoded security type mappings that need to be centralized:

#### 1. **SnapTrade Loader** (`snaptrade_loader.py`)
- **Function**: `_map_snaptrade_code_to_internal()` (line 587)
- **Current State**: Hardcoded dictionary mapping SnapTrade codes to internal types
- **Usage**: Called by `fetch_snaptrade_holdings()` - core data ingestion pipeline
- **Risk Level**: **LOW** - Self-contained function with clear interface
- **Dependencies**: None - standalone mapping function

```python
# Current implementation (line 620-634)
code_mapping = {
    'cs': 'equity',        # Common Stock
    'ps': 'equity',        # Preferred Stock  
    'ad': 'equity',        # ADR
    'et': 'etf',           # ETF
    'oef': 'mutual_fund',  # Open Ended Fund ← NEEDS CENTRALIZATION
    'cef': 'mutual_fund',  # Closed End Fund ← NEEDS CENTRALIZATION
    # ... more mappings
}
```

#### 2. **SecurityTypeService** (`services/security_type_service.py`)
- **Method**: `normalize_fmp_profile()` (line 271)
- **Current State**: Hardcoded FMP profile analysis logic
- **Usage**: Called by both SnapTrade and Plaid loaders for security type enhancement
- **Risk Level**: **MEDIUM** - Used across multiple loaders
- **Dependencies**: Used by `_fetch_and_cache_from_fmp()` and `force_refresh()`

```python
# Current implementation (line 278-286)
if profile.get("isEtf", False):
    return "etf"
elif profile.get("isFund", False):
    return "mutual_fund"  ← NEEDS CENTRALIZATION
elif profile.get("ticker", "").startswith("CUR:"):
    return "cash"
```

#### 3. **Settings** (`settings.py`)
- **Variable**: `SECURITY_TYPE_CRASH_MAPPING`
- **Current State**: Hardcoded dictionary mapping security types to crash scenarios
- **Usage**: Used throughout risk scoring calculations
- **Risk Level**: **HIGH** - Core risk calculation dependency
- **Dependencies**: Used by portfolio risk scoring functions

```python
# Current implementation in settings.py
SECURITY_TYPE_CRASH_MAPPING = {
    "equity": "single_stock_crash",
    "etf": "etf_crash", 
    "mutual_fund": "mutual_fund_crash",  ← NEEDS CENTRALIZATION
    "cash": "cash_crash"
}
```

#### 4. **Plaid Loader** (`plaid_loader.py`)
- **Function**: `get_enhanced_security_type()` (line 998)
- **Current State**: Strategy-based approach calling SecurityTypeService
- **Usage**: Selective enhancement of Plaid security types
- **Risk Level**: **LOW** - Only calls SecurityTypeService, no direct mappings
- **Dependencies**: Depends on SecurityTypeService refactor

### Dependency Mapping

```
SnapTrade Loader
├── _map_snaptrade_code_to_internal() [REFACTOR NEEDED]
└── get_enhanced_security_type() → SecurityTypeService [INDIRECT]

SecurityTypeService [REFACTOR NEEDED]
├── normalize_fmp_profile() [DIRECT REFACTOR]
├── _fetch_and_cache_from_fmp() [CALLS normalize_fmp_profile]
└── force_refresh() [CALLS normalize_fmp_profile]

Plaid Loader
└── get_enhanced_security_type() → SecurityTypeService [INDIRECT]

Settings [REFACTOR NEEDED]
└── SECURITY_TYPE_CRASH_MAPPING [DIRECT REFACTOR]

Risk Scoring Functions
└── Uses SECURITY_TYPE_CRASH_MAPPING [INDIRECT]
```

## Phased Refactoring Strategy

### **Phase 1: Foundation Setup** (Low Risk)
**Goal**: Create infrastructure without breaking existing functionality

**Tasks**:
1. Add database schema to `database/schema.sql`
2. Create `security_type_mappings.yaml` configuration file
3. Add DatabaseClient methods for security type operations
4. Create `utils/security_type_mappings.py` utility module
5. Add migration script to `admin/migrate_reference_data.py`

**Validation**: 
- Database schema applies cleanly
- YAML config loads without errors
- Utility functions work with hardcoded fallbacks
- No existing functionality affected

### **Phase 2: SnapTrade Loader Refactor** (Low Risk)
**Goal**: Replace SnapTrade hardcoded mapping with centralized system

**Tasks**:
1. Replace `_map_snaptrade_code_to_internal()` with centralized mapping call
2. Remove hardcoded `code_mapping` dictionary entirely
3. Update function to use `map_snaptrade_code()` from utils

**Implementation**:
```python
# New implementation in snaptrade_loader.py
def _map_snaptrade_code_to_internal(snaptrade_code: str) -> str:
    """Map SnapTrade's standardized type codes using centralized mappings."""
    from utils.security_type_mappings import map_snaptrade_code
    
    mapped_type = map_snaptrade_code(snaptrade_code)
    if mapped_type:
        return mapped_type
    
    # Log unknown codes for debugging
    portfolio_logger.warning(f"Unknown SnapTrade code '{snaptrade_code}', using as-is")
    return snaptrade_code.lower()
```

**Validation**:
- All existing SnapTrade mappings produce identical results
- 3-tier fallback system works (Database → YAML → Hardcoded)
- Unknown codes handled gracefully

### **Phase 3: SecurityTypeService Refactor** (Medium Risk)
**Goal**: Replace FMP hardcoded logic with centralized system

**Tasks**:
1. Replace `normalize_fmp_profile()` hardcoded logic with `map_fmp_profile()`
2. Remove hardcoded if/elif logic entirely
3. Update method to use centralized mapping

**Implementation**:
```python
# New implementation in security_type_service.py
@staticmethod
@log_performance_tracking("normalize_fmp_profile")
def normalize_fmp_profile(profile: dict, ticker: str = None, original_type: str = None) -> str:
    """Convert FMP profile to standardized security type using centralized mappings."""
    if not profile:
        portfolio_logger.debug(f"🔍 Empty FMP profile for {ticker}, returning original: {original_type}")
        return original_type
        
    from utils.security_type_mappings import map_fmp_profile
    
    # Log the decision process for debugging
    portfolio_logger.debug(f"🔍 Normalizing FMP profile for {ticker}: {profile}")
    
    mapped_type = map_fmp_profile(profile)
    if mapped_type:
        portfolio_logger.info(f"✅ FMP normalization: {ticker} → {mapped_type}")
        return mapped_type
    
    # Fallback to original provider type if no mapping found
    portfolio_logger.debug(f"🔄 No FMP mapping for {ticker}, using original: {original_type}")
    return original_type
```

**Validation**:
- All existing FMP classifications produce identical results
- DSU still maps to "mutual_fund" correctly
- Cash positions still work correctly
- 3-tier fallback system works (Database → YAML → Hardcoded)

### **Phase 4: Settings Refactor** (High Risk)
**Goal**: Replace hardcoded crash scenario mapping with centralized system

**Tasks**:
1. Replace `SECURITY_TYPE_CRASH_MAPPING` static dict with centralized call
2. Remove hardcoded mapping dictionary entirely
3. Update to use `get_crash_scenario_mappings()` from utils

**Implementation**:
```python
# New implementation in settings.py
from utils.security_type_mappings import get_crash_scenario_mappings
from utils.logging import portfolio_logger

# Replace static variable with centralized mapping
def _load_crash_scenario_mappings():
    """Load crash scenario mappings with logging."""
    portfolio_logger.info("🔄 Loading security type crash scenario mappings")
    mappings = get_crash_scenario_mappings()
    portfolio_logger.info(f"✅ Loaded {len(mappings)} crash scenario mappings")
    return mappings

SECURITY_TYPE_CRASH_MAPPING = _load_crash_scenario_mappings()
```

**Validation**:
- All risk calculations produce identical results
- DSU still gets 40% crash scenario (mutual_fund → mutual_fund_crash)
- All security types maintain correct crash percentages
- 3-tier fallback system works (Database → YAML → Hardcoded)

### **Phase 5: Integration Testing** (Critical)
**Goal**: Ensure end-to-end functionality works correctly

**Tasks**:
1. Run full integration tests across all data providers
2. Verify DSU classification works correctly end-to-end
3. Test database failover scenarios
4. Test YAML failover scenarios
5. Performance testing with database caching

**Test Cases**:
- SnapTrade DSU import → "mutual_fund" → 40% crash scenario
- FMP API lookup → correct security type classification
- Database unavailable → YAML fallback works
- YAML unavailable → hardcoded fallback works
- Admin tools work correctly
- Migration scripts work correctly

### **Phase 6: Admin Tools & Management** (Low Risk)
**Goal**: Complete the implementation with management tools

**Tasks**:
1. Add admin management commands
2. Clean up any temporary code or comments
3. Add monitoring and alerting
4. Verify all functionality working correctly

### **Phase 7: Documentation Updates** (Critical for Maintenance)
**Goal**: Update all documentation to reflect the new centralized architecture

**Tasks**:

#### **1. Module-Level Documentation Updates**
- **`utils/security_type_mappings.py`**: Add comprehensive module docstring explaining 3-tier architecture
- **`services/security_type_service.py`**: Update module docstring to reference centralized mappings
- **`snaptrade_loader.py`**: Update security type mapping section documentation
- **`plaid_loader.py`**: Update comments about SecurityTypeService integration
- **`settings.py`**: Update crash scenario mapping documentation

#### **2. Function/Method Docstring Updates**
```python
# Update SecurityTypeService.normalize_fmp_profile()
def normalize_fmp_profile(profile: dict, ticker: str = None, original_type: str = None) -> str:
    """
    Convert FMP profile to standardized security type using centralized mappings.
    
    Uses the centralized security type mapping system (Database → YAML → Hardcoded)
    to ensure consistent classification across all data providers.
    
    Args:
        profile: FMP profile dictionary with isEtf, isFund, ticker fields
        ticker: Security ticker symbol for logging purposes
        original_type: Fallback type from original provider
        
    Returns:
        Standardized security type: 'equity', 'etf', 'mutual_fund', 'cash'
        
    Architecture:
        Calls utils.security_type_mappings.map_fmp_profile() which uses:
        1. Database: security_type_mappings table (primary)
        2. YAML: security_type_mappings.yaml (fallback)  
        3. Hardcoded: Built-in mapping dictionary (ultimate fallback)
    """

# Update _map_snaptrade_code_to_internal()
def _map_snaptrade_code_to_internal(snaptrade_code: str) -> str:
    """
    Map SnapTrade's standardized type codes using centralized mappings.
    
    Uses the centralized security type mapping system for consistent
    classification across all portfolio data sources.
    
    Args:
        snaptrade_code: SnapTrade security type code (e.g., 'oef', 'et', 'cs')
        
    Returns:
        Internal security type classification
        
    Architecture:
        Calls utils.security_type_mappings.map_snaptrade_code() which uses:
        1. Database: security_type_mappings table (primary)
        2. YAML: security_type_mappings.yaml (fallback)
        3. Hardcoded: Built-in mapping dictionary (ultimate fallback)
        
    Mappings:
        'oef'/'cef' → 'mutual_fund'  # Open/Closed End Funds
        'et' → 'etf'                 # Exchange Traded Funds  
        'cs'/'ps' → 'equity'         # Common/Preferred Stock
        'cash' → 'cash'              # Cash positions
    """
```

#### **3. Inline Code Comments Updates**
- **Remove hardcoded mapping comments**: Update comments that reference hardcoded dictionaries
- **Add centralized mapping references**: Point to centralized system in key decision points
- **Update fallback explanations**: Explain 3-tier fallback strategy in error handling blocks
- **Add performance notes**: Document caching and performance characteristics

#### **4. Architecture Documentation Updates**
- **`architecture.md`**: Add security type mapping centralization section
- **`DATABASE_REFERENCE.md`**: Document new security type tables and relationships
- **`complete_codebase_map.md`**: Update security type flow diagrams
- **API documentation**: Update any references to security type handling

#### **5. Code Examples and Comments**
```python
# Update settings.py comments
# Replace:
# Hardcoded security type crash scenario mapping
SECURITY_TYPE_CRASH_MAPPING = get_crash_scenario_mappings()

# With:
# Centralized security type crash scenario mapping
# Uses 3-tier system: Database → YAML → Hardcoded fallback
# Managed via utils.security_type_mappings.get_crash_scenario_mappings()
SECURITY_TYPE_CRASH_MAPPING = get_crash_scenario_mappings()
```

#### **6. Migration Documentation**
- **Create migration guide**: Document the architectural change for future developers
- **Update troubleshooting docs**: Add common issues and solutions for centralized mappings
- **Add admin documentation**: Document how to manage mappings via admin tools

**Validation**:
- [ ] All docstrings accurately reflect new architecture
- [ ] No references to old hardcoded mapping approach
- [ ] Architecture diagrams updated
- [ ] Code examples work correctly
- [ ] Documentation builds without errors

## Risk Mitigation Strategies

### **3-Tier Fallback System**
- **Database first**: Primary source for performance and consistency
- **YAML fallback**: Reliable when database unavailable
- **Hardcoded fallback**: Ultimate reliability guarantee
- **Comprehensive logging**: Track which tier is being used

### **Rollback Plan**
1. **Phase-by-phase rollback**: Each phase can be independently rolled back
2. **Database rollback**: Schema changes can be reverted
3. **Code rollback**: Git revert for any problematic changes
4. **YAML config rollback**: Revert configuration changes

### **Testing Strategy**
- **Unit tests**: Each mapping function tested in isolation
- **Integration tests**: End-to-end data flow testing
- **Regression tests**: Ensure no existing functionality breaks
- **Performance tests**: Database caching performance validation
- **Failover tests**: Test all fallback scenarios

### **Monitoring**
- **Mapping success rates**: Track centralized vs fallback usage
- **Performance metrics**: Database query performance
- **Error rates**: Failed mapping attempts
- **Data consistency**: Verify mapping results match expectations

## Implementation Timeline

### **Week 1: Foundation** (Phase 1)
- Database schema design and implementation
- YAML configuration creation
- Utility module development
- Migration script creation

### **Week 2: SnapTrade Integration** (Phase 2)
- SnapTrade loader refactoring
- Feature flag implementation
- Unit testing and validation

### **Week 3: SecurityTypeService Integration** (Phase 3)
- SecurityTypeService refactoring
- Integration testing
- Performance validation

### **Week 4: Settings Integration** (Phase 4)
- Settings refactoring
- Risk scoring validation
- End-to-end testing

### **Week 5: Final Integration** (Phase 5-6)
- Full system testing
- Admin tools implementation
- Documentation updates
- Production deployment

## Success Criteria

1. **Functional**: All existing security type classifications work identically
2. **Performance**: No degradation in data loading or risk calculation performance
3. **Reliability**: 3-tier fallback system works correctly in all scenarios
4. **Maintainability**: New security types and providers can be added easily
5. **Consistency**: Perfect alignment with existing mapping architecture patterns

## Testing Strategy

1. **Unit Tests**: Test utility functions with mocked database
2. **Integration Tests**: Test 3-tier fallback behavior
3. **Migration Tests**: Verify data migration accuracy
4. **Regression Tests**: Ensure existing functionality unchanged
5. **Performance Tests**: Verify database caching performance

## Rollback Plan

If issues arise during implementation:
1. Keep existing hardcoded mappings as fallback
2. Add feature flag to enable/disable centralized mappings
3. Gradual rollout per provider (SnapTrade → FMP → Settings)
4. Database rollback scripts for schema changes

---

This implementation plan provides complete centralization of security type mappings while maintaining perfect consistency with the established architecture patterns used throughout the risk module.

---

## 🔍 **ARCHITECTURAL REVIEW & GAPS ANALYSIS**

### **✅ COVERED COMPONENTS**
- **SnapTrade Loader**: `_map_snaptrade_code_to_internal()` function
- **SecurityTypeService**: `normalize_fmp_profile()` method  
- **Settings**: `SECURITY_TYPE_CRASH_MAPPING` variable
- **Plaid Loader**: Indirect dependency (calls SecurityTypeService)

### **⚠️ TESTING STRATEGY GAP**

#### **Critical Integration Testing Required**
**Risk Level**: HIGH - **Essential for DSU validation**

The plan lacks specific integration tests to ensure the refactor doesn't break existing functionality, particularly the critical DSU → 40% crash scenario flow.

**Proposed Test Suite**:

```python
# tests/integration/test_security_type_mappings.py

import mock
from utils.logging import portfolio_logger
from services.security_type_service import SecurityTypeService
from utils.security_type_mappings import map_snaptrade_code, get_crash_scenario_mappings
from settings import CRASH_SCENARIOS

class TestSecurityTypeMappingIntegration:
    """Integration tests for centralized security type mappings."""
    
    def test_dsu_crash_scenario_end_to_end(self):
        """Verify DSU gets 40% crash scenario through complete pipeline."""
        # Test FMP profile → mutual_fund → 40% crash
        fmp_profile = {"isFund": True, "symbol": "DSU"}
        
        # Test SecurityTypeService mapping
        security_type = SecurityTypeService.normalize_fmp_profile(fmp_profile)
        assert security_type == "mutual_fund"
        
        # Test crash scenario mapping
        crash_scenario = get_security_type_crash_mapping()[security_type]
        assert crash_scenario == "mutual_fund_crash"
        
        # Test crash percentage
        crash_percentage = CRASH_SCENARIOS[crash_scenario]
        assert crash_percentage == 0.40  # 40% crash for DSU
    
    def test_snaptrade_mapping_consistency(self):
        """Verify SnapTrade mappings remain identical."""
        test_cases = [
            ("oef", "mutual_fund"),  # Open Ended Fund
            ("cef", "mutual_fund"),  # Closed End Fund
            ("et", "etf"),           # ETF
            ("cs", "equity"),        # Common Stock
        ]
        
        for snaptrade_code, expected_type in test_cases:
            result = _map_snaptrade_code_to_internal(snaptrade_code)
            assert result == expected_type
    
    def test_fmp_mapping_consistency(self):
        """Verify FMP mappings remain identical."""
        test_cases = [
            ({"isEtf": True}, "etf"),
            ({"isFund": True}, "mutual_fund"),
            ({"symbol": "CUR:USD"}, "cash"),
        ]
        
        for profile, expected_type in test_cases:
            result = SecurityTypeService.normalize_fmp_profile(profile)
            assert result == expected_type
    
    def test_three_tier_fallback_system(self):
        """Verify 3-tier fallback works correctly."""
        # Test database failure → YAML fallback
        with mock.patch('database.get_db_session', side_effect=Exception):
            result = map_snaptrade_code("oef")
            assert result == "mutual_fund"  # Should use YAML fallback
        
        # Test YAML failure → hardcoded fallback
        with mock.patch('builtins.open', side_effect=FileNotFoundError):
            result = map_snaptrade_code("oef")
            assert result == "mutual_fund"  # Should use hardcoded fallback
```

**Test Execution Strategy**:
1. **Pre-refactor baseline**: Run tests against current hardcoded implementation
2. **Post-refactor validation**: Run identical tests against centralized implementation
3. **Performance regression**: Ensure mapping performance remains acceptable
4. **End-to-end validation**: Test complete DSU portfolio risk calculation

## 📋 **LOGGING STRATEGY**

### **Decision Point Logging**
The implementation includes comprehensive logging at every key decision point to ensure complete visibility into the mapping process:

#### **🔍 Debug Level** (Development Only)
- **Input validation**: Log all incoming parameters and profiles
- **Mapping attempts**: Log each mapping lookup attempt
- **Fallback triggers**: Log when falling back between tiers

#### **ℹ️ Info Level** (Production + Development)  
- **Successful mappings**: Log all successful security type mappings
- **Tier usage**: Log which tier (Database/YAML/Hardcoded) is being used
- **System initialization**: Log when mappings are loaded

#### **⚠️ Warning Level** (Always)
- **Unknown codes**: Log unrecognized security type codes
- **Fallback usage**: Log when database/YAML unavailable
- **Missing mappings**: Log when no mapping found

#### **❌ Error Level** (Always)
- **System failures**: Log critical mapping system failures
- **Data inconsistencies**: Log mapping conflicts or corruption

### **Logging Infrastructure Integration**
- **Uses existing loggers**: `database_logger`, `portfolio_logger`
- **Performance tracking**: `@log_performance_tracking` decorators
- **Error handling**: `@log_error_handling` decorators
- **Structured logging**: Consistent emoji prefixes for easy filtering

### **Debugging Benefits**
With this logging strategy, any mapping issues can be quickly traced:
1. **DSU Classification**: Clear trail from SnapTrade → FMP → Risk Scoring
2. **Fallback Behavior**: Visibility into which tier is being used
3. **Performance Impact**: Track mapping performance across system
4. **Data Flow**: Complete audit trail for security type decisions

---

This implementation plan provides complete centralization of security type mappings while maintaining perfect consistency with the established architecture patterns used throughout the risk module. The critical testing strategy and comprehensive logging ensure that the refactor maintains all existing functionality, particularly the essential DSU → 40% crash scenario flow.

## 📋 **CURRENT VS PROPOSED MAPPINGS**

### **Currently Used** (Matches existing settings.py)
- **Security Types**: `equity`, `etf`, `mutual_fund`, `cash`
- **Crash Scenarios**: 4 mappings (80%, 35%, 40%, 5%)
- **SnapTrade Codes**: 13 mappings (oef, cef, et, cs, etc.)
- **FMP Profiles**: 3 mappings (isEtf, isFund, CUR:)

### **Proposed Future Expansion** (Not currently used)
- **Additional Types**: `bond`, `crypto`, `derivative`, `warrant`
- **Additional Scenarios**: 4 new crash scenarios (30%, 90%, 95%, 85%)
- **Database Ready**: Schema supports future expansion without migration

The implementation includes both current and proposed mappings to enable future expansion while maintaining 100% backward compatibility with existing functionality.

## 📚 **DOCUMENTATION MAINTENANCE**

### **Phase 7: Comprehensive Documentation Updates**
After successful testing and deployment, all documentation must be updated to reflect the new centralized architecture:

- **Module Documentation**: Update all affected modules with new architecture explanations
- **Function Docstrings**: Revise docstrings to reference centralized mappings instead of hardcoded logic
- **Inline Comments**: Update code comments to explain 3-tier fallback system
- **Architecture Docs**: Update system architecture documentation and diagrams
- **Migration Guide**: Create documentation for future developers about the architectural change

This ensures the codebase remains maintainable and new developers can understand the centralized mapping system.
