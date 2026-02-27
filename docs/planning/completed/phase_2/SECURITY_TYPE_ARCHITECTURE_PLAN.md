# Security Type Architecture Plan

## 🎯 **Problem Statement**

**Current Issue:** DSU (and potentially other securities) are being treated as individual stocks (80% crash scenario) instead of mutual funds (40% crash scenario) in risk scoring calculations.

**Root Cause:** Inconsistent security type classification across data providers:
- **Plaid**: DSU = `"mutual fund"` ✅ (Correct)
- **SnapTrade**: DSU = `"equity"` ❌ (Incorrect)
- **Risk Scoring**: Uses 80% single stock crash scenario for DSU (incorrect)

## 🏗️ **Proposed Solution: Unified Security Type Service**

Replace provider-specific security type data with a **single source of truth** using FMP API with database caching, while **preserving provider expertise for cash positions**.

### **Cash-First Strategy:**
- **Cash positions**: Trust Plaid/SnapTrade (domain expertise for currencies/cash equivalents)
- **Securities**: Trust FMP (authoritative for stocks/ETFs/mutual funds)  
- **Result**: Optimal classification accuracy across all position types

**Example:**
```python
# Input from Plaid/SnapTrade:
portfolio_input = {
    "USD": {"shares": 1000, "type": "cash"},        # ✅ Keep provider data
    "SGOV": {"shares": 100, "type": "cash"},        # ✅ Keep provider data  
    "DSU": {"shares": 50, "type": "equity"}         # ❌ Override with FMP
}

# After SecurityTypeService processing:
security_types = {
    "USD": "cash",          # ✅ Preserved from provider
    "SGOV": "cash",         # ✅ Preserved from provider
    "DSU": "mutual_fund"    # ✅ Corrected by FMP
}
```

### **Architecture Overview**

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Portfolio     │    │  SecurityType    │    │   FMP API       │
│   Analysis      │───▶│    Service       │───▶│   (Source of    │
│                 │    │                  │    │    Truth)       │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   Database       │
                       │   Cache          │
                       │ (security_types) │
                       └──────────────────┘
```

## 🔗 **Integration Points**

Based on the data flow analysis, the `SecurityTypeService` needs to be integrated at **two critical points**:

### **Integration Point 1: Provider Data Loading** 

#### **SnapTrade Integration**
**Location:** `snaptrade_loader.py`
**Function:** `convert_snaptrade_holdings_to_portfolio_data()`
**Current Logic (line 1020):**
```python
# Current SnapTrade:
holdings_dict[ticker] = {
    'shares': float(quantity),
    'currency': row.get('currency', 'USD'),
    'type': position_type  # ❌ Uses provider classification
}
```

#### **Plaid Integration**
**Location:** `plaid_loader.py`
**Function:** `convert_plaid_holdings_to_portfolio_data()`
**Current Logic (line 1047):**
```python
# Current Plaid:
portfolio_input[ticker] = {
    'shares': float(quantity),
    'currency': currency,
    'type': position_type,  # ❌ Uses provider classification
    'cost_basis': cost_basis,
    'account_id': account_id
}
```

#### **Enhanced Logic (Both Providers):**
```python
# Enhanced with SecurityTypeService:
def get_enhanced_security_type(ticker: str, original_type: str) -> str:
    """Get security type with cash preservation"""
    if original_type == 'cash':
        return 'cash'  # ✅ Preserve provider cash classification
    else:
        return SecurityTypeService.get_security_type_from_fmp(ticker)  # ✅ Use FMP for securities

# SnapTrade (line 1020):
holdings_dict[ticker] = {
    'shares': float(quantity),
    'currency': row.get('currency', 'USD'),
    'type': get_enhanced_security_type(ticker, position_type)
}

# Plaid (line 1047):
portfolio_input[ticker] = {
    'shares': float(quantity),
    'currency': currency,
    'type': get_enhanced_security_type(ticker, position_type),
    'cost_basis': cost_basis,
    'account_id': account_id
}
```

### **Integration Point 2: Risk Score Calculation**
**Location:** `portfolio_risk_score.py`
**Function:** `calculate_concentration_risk_loss()`
**Current Logic:**
```python
# Current (line ~1400):
def calculate_concentration_risk_loss(summary: Dict[str, Any], leverage_ratio: float) -> float:
    single_stock_crash = WORST_CASE_SCENARIOS["single_stock_crash"]  # ❌ Generic 80%
    concentration_loss = max_position * single_stock_crash * leverage_ratio
```

**Enhanced Logic:**
```python
# Enhanced with SecurityTypeService:
def calculate_concentration_risk_loss(summary: Dict[str, Any], leverage_ratio: float, portfolio_data: PortfolioData = None) -> float:
    tickers = list(weights.index)
    security_types = SecurityTypeService.get_security_types(tickers, portfolio_data)
    crash_scenario = get_crash_scenario_for_security_type(security_types[largest_ticker])
    concentration_loss = max_position * crash_scenario * leverage_ratio
```

## 🔄 **Data Flow Overview**

### **Current Flow (Problematic):**
```
Provider APIs:
├─ SnapTrade API → DSU classified as "equity" 
├─ Plaid API → DSU classified as "mutual_fund" (correct but inconsistent)
└─ Result: Same security, different classifications across providers ❌

Data Processing:
1. snaptrade_loader.py → holdings_dict[DSU]['type'] = "equity" (wrong)
2. plaid_loader.py → portfolio_input[DSU]['type'] = "mutual_fund" (right)
3. DatabaseClient.save_portfolio() → stores inconsistent types per provider
4. portfolio_risk_score.py → applies 80% crash to SnapTrade DSU ❌
```

### **Enhanced Flow (Fixed):**
```
Provider APIs:
├─ SnapTrade API → DSU classified as "equity" (ignored for non-cash)
├─ Plaid API → DSU classified as "mutual_fund" (ignored for non-cash)
└─ Result: Provider classifications ignored, FMP becomes single source ✅

Data Processing:
1. Both loaders → get_enhanced_security_type("DSU", original_type)
   ├─ Cash positions: Preserve provider classification
   ├─ Non-cash: Query FMP API → DSU = "mutual_fund" ✅
   └─ Consistent classification across all providers
2. holdings_dict[DSU]['type'] = "mutual_fund" (both providers)
3. DatabaseClient.save_portfolio() → stores consistent "mutual_fund"
4. portfolio_risk_score.py → applies 40% crash scenario to DSU ✅
```

## 🏗️ **Architectural Review & Compliance**

### **✅ Alignment with Existing Patterns**

Based on codebase analysis, the `SecurityTypeService` aligns well with existing architectural patterns:

#### **1. Service Layer Patterns**
- **✅ Follows ServiceCacheMixin pattern** (like PortfolioService, StockService)
- **✅ Uses logging decorators** (`@log_error_handling`, `@log_performance`, `@log_cache_operations`)
- **✅ Implements proper error handling** with `ServiceError` exceptions
- **✅ Supports caching with TTL** (follows `SERVICE_CACHE_MAXSIZE`, `SERVICE_CACHE_TTL`)

#### **2. Database Access Patterns**
- **✅ Uses `get_db_session()` context manager** (like AuthService)
- **✅ Follows DatabaseClient pattern** for database operations
- **✅ Implements proper transaction management** with rollback support
- **✅ Uses parameterized queries** to prevent SQL injection

#### **3. External API Integration Patterns**
- **✅ Leverages existing LFU cache** (`@cache_company_profile` decorator)
- **✅ Uses existing FMP integration** (`fetch_profile` function)
- **✅ Follows timeout and error handling** patterns from proxy_builder.py
- **✅ Implements rate limiting awareness** (existing FMP patterns)

#### **4. Configuration Management**
- **✅ Uses environment variables** for configuration (like utils/config.py)
- **✅ Supports development/production modes** 
- **✅ Follows centralized settings pattern** (settings.py)

### **🔧 Missing Architectural Considerations**

#### **1. Service Registration & Discovery**
**Gap:** SecurityTypeService needs to be registered in ServiceManager
```python
# services/service_manager.py - ADD:
from services.security_type_service import SecurityTypeService

class ServiceManager:
    def __init__(self, cache_results: bool = True, enable_async: bool = True):
        # ... existing services ...
        self.security_type_service = SecurityTypeService(cache_results=cache_results)
    
    def get_service(self, service_name: str):
        services = {
            # ... existing services ...
            'security_type': self.security_type_service,
        }
```

#### **2. Configuration Constants**
**Gap:** Need to add SecurityTypeService configuration to utils/config.py
```python
# utils/config.py - ADD:
SECURITY_TYPE_CACHE_TTL = int(os.getenv("SECURITY_TYPE_CACHE_TTL", "7776000"))  # 90 days
SECURITY_TYPE_CACHE_SIZE = int(os.getenv("SECURITY_TYPE_CACHE_SIZE", "10000"))  # 10k tickers
FMP_RATE_LIMIT_DELAY = float(os.getenv("FMP_RATE_LIMIT_DELAY", "0.1"))  # 100ms between calls
```

#### **3. Monitoring & Observability**
**Gap:** Need to add cache statistics and health checks
```python
# SecurityTypeService - ADD:
def get_cache_stats(self) -> Dict[str, Any]:
    """Get cache statistics for monitoring"""
    return {
        'database_cache_size': self._get_db_cache_size(),
        'lfu_cache_stats': _COMPANY_PROFILE_CACHE.stats(),
        'cache_hit_rate': self._calculate_hit_rate(),
        'stale_entries_count': self._count_stale_entries()
    }

def health_check(self) -> Dict[str, Any]:
    """Health check for service monitoring"""
    return {
        'database_connection': self._test_db_connection(),
        'fmp_api_status': self._test_fmp_api(),
        'cache_status': 'healthy' if len(self.cache) > 0 else 'empty'
    }
```

#### **4. Async Support**
**Gap:** Consider async variant for high-throughput scenarios
```python
# services/async_security_type_service.py - FUTURE:
class AsyncSecurityTypeService:
    """Async variant for batch security type lookups"""
    
    async def get_security_types_batch(self, tickers: List[str]) -> Dict[str, str]:
        """Async batch lookup with concurrent FMP calls"""
        # Implementation for high-throughput scenarios
```

#### **5. CLI Integration**
**Gap:** CLI commands need SecurityTypeService access without user context
```python
# SecurityTypeService - MODIFY:
@staticmethod
def get_security_types(tickers: List[str], portfolio_data: PortfolioData = None) -> Dict[str, str]:
    """Static method for CLI compatibility (no user context required)"""
    # Implementation that works both in API and CLI contexts
```

#### **6. Testing Infrastructure**
**Gap:** Comprehensive test coverage following existing patterns
```python
# tests/test_security_type_service.py - ADD:
class TestSecurityTypeService:
    """Test suite following existing service test patterns"""
    
    def test_cash_preservation(self):
        """Test that cash types are preserved from providers"""
        
    def test_fmp_integration(self):
        """Test FMP API integration with mocking"""
        
    def test_database_caching(self):
        """Test database cache with TTL and stale detection"""
        
    def test_lfu_cache_integration(self):
        """Test LFU cache integration with existing fetch_profile"""
        
    def test_error_handling(self):
        """Test graceful degradation and fallback scenarios"""
```

#### **7. Database Migration & Schema**
**✅ COMPLETED:** Added to production schema in `database/schema.sql`
```sql
-- ✅ ADDED TO database/schema.sql (lines 625-648)
-- Global security type classification cache table
-- Stores authoritative security types from Financial Modeling Prep (FMP) API
-- Provides consistent classification across all providers (Plaid, SnapTrade, etc.)
CREATE TABLE IF NOT EXISTS security_types (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL UNIQUE,
    security_type VARCHAR(50) NOT NULL,  -- 'equity', 'etf', 'mutual_fund', 'cash', 'bond', 'crypto'
    fmp_data JSONB,                      -- Store full FMP profile for reference and debugging
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Performance indexes and triggers included ✅
```

**Migration Script:** For existing deployments, create `database/migrations/20250101_add_security_types.sql`

#### **8. Admin Tools & Management**
**Gap:** Admin interface for security type management
```python
# admin/manage_security_types.py - ADD:
def list_security_types(db_client, limit=50):
    """List security types with pagination"""
    
def force_refresh_ticker(db_client, ticker):
    """Force refresh specific ticker from FMP"""
    
def bulk_refresh_stale(db_client, days=90):
    """Bulk refresh stale entries older than N days"""
    
def export_security_types(db_client, output_file):
    """Export security types for backup/analysis"""
```

#### **9. Backup & Recovery Strategy**
**Gap:** Data protection and disaster recovery
```python
# SecurityTypeService - ADD:
@staticmethod
def export_cache_to_yaml(output_path: str):
    """Export database cache to YAML for backup"""
    
@staticmethod  
def import_cache_from_yaml(yaml_path: str):
    """Import security types from YAML backup"""
    
def get_cache_health_report(self) -> Dict[str, Any]:
    """Generate health report for monitoring"""
```

## 📋 **Implementation Plan**

### **Phase 1: Database Schema Enhancement**

**New Table: `security_types`**
```sql
CREATE TABLE security_types (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL UNIQUE,
    security_type VARCHAR(50) NOT NULL,  -- 'equity', 'etf', 'mutual_fund', 'cash'
    fmp_data JSONB,                      -- Store full FMP profile for reference
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_security_types_ticker (ticker),
    INDEX idx_security_types_updated (last_updated)
);
```

**Initial Data Population:**
- Populate with known securities from existing portfolios
- Use FMP API to fetch and normalize security types
- Set TTL for cache refresh (30 days recommended)

### **Phase 2: SecurityType Service Implementation**

**Core Service Class:**
```python
# File: services/security_type_service.py

from proxy_builder import fetch_profile  # Leverages existing LFU cache
from inputs.database_client import DatabaseClient
from database.db_session import get_db_session
import json

class SecurityTypeService:
    """
    Unified security type classification service using FMP API with dual-layer caching.
    
    Provides consistent security type classification across all system components,
    replacing inconsistent provider-specific classifications.
    
    Caching Architecture:
    - Layer 1: LFU in-memory cache (existing fetch_profile cache, 1000 items) - FASTEST
    - Layer 2: Database cache (90-day TTL, persistent across restarts) - PERSISTENT  
    - Layer 3: FMP API (authoritative source) - AUTHORITATIVE
    """
    
    @staticmethod
    def get_security_types(tickers: List[str], portfolio_data: PortfolioData = None) -> Dict[str, str]:
        """
        Get normalized security types for list of tickers with provider cash preservation.
        
        Hierarchy:
        1. Provider data for cash positions (Plaid/SnapTrade expertise) - immediate
        2. LFU memory cache (via fetch_profile, cross-user) - ~0.001ms
        3. Database cache (persistent, 90-day TTL) - ~10ms
        4. FMP API lookup (authoritative for securities) - ~200ms
        5. Heuristic fallback (safe) - immediate
        """
        security_types = {}
        
        # 1. FIRST: Preserve cash types from original provider data
        # Providers (Plaid/SnapTrade) are authoritative for cash/currency positions
        if portfolio_data:
            for ticker in tickers:
                original_type = portfolio_data.standardized_input.get(ticker, {}).get('type')
                if original_type == "cash":
                    security_types[ticker] = "cash"  # ✅ Trust provider for cash
        
        # 2. For non-cash tickers, use FMP-based classification
        non_cash_tickers = [t for t in tickers if t not in security_types]
        
        if non_cash_tickers:
            # Check database for non-cash tickers (includes stale detection)
            db_results = SecurityTypeService._get_from_database_cache(non_cash_tickers)
            fresh_tickers = db_results['fresh']
            stale_tickers = db_results['stale'] 
            missing_tickers = db_results['missing']
            
            # Add fresh database results
            security_types.update(fresh_tickers)
            
            # For stale + missing tickers, use fetch_profile (LFU cache + FMP)
            refresh_tickers = list(stale_tickers.keys()) + missing_tickers
            if refresh_tickers:
                fresh_types = SecurityTypeService._fetch_and_cache_from_fmp(refresh_tickers)
                security_types.update(fresh_types)
        
        return security_types
    
    @staticmethod
    def _get_from_database_cache(tickers: List[str]) -> Dict[str, Any]:
        """Get security types from database with stale detection"""
        fresh_types = {}
        stale_types = {}
        
        with get_db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ticker, security_type,
                       CASE WHEN last_updated < NOW() - INTERVAL '90 days' 
                            THEN true ELSE false END as is_stale
                FROM security_types 
                WHERE ticker = ANY(%s)
            """, (tickers,))
            
            found_tickers = set()
            for ticker, sec_type, is_stale in cursor.fetchall():
                found_tickers.add(ticker)
                if is_stale:
                    stale_types[ticker] = sec_type
                else:
                    fresh_types[ticker] = sec_type
        
        missing_tickers = [t for t in tickers if t not in found_tickers]
        
        return {
            'fresh': fresh_types,
            'stale': stale_types, 
            'missing': missing_tickers
        }
    
    @staticmethod
    def _fetch_and_cache_from_fmp(tickers: List[str]) -> Dict[str, str]:
        """Fetch from FMP using existing LFU cache and update database"""
        fresh_types = {}
        
        for ticker in tickers:
            try:
                # Uses existing @cache_company_profile decorator
                profile = fetch_profile(ticker)  # ← Leverages LFU cache!
                security_type = SecurityTypeService.normalize_fmp_profile(profile)
                fresh_types[ticker] = security_type
                
                # Update database cache
                SecurityTypeService._update_database_cache(ticker, security_type, profile)
                
            except Exception as e:
                # Fallback to heuristic
                fresh_types[ticker] = SecurityTypeService._detect_security_type_heuristic(ticker)
        
        return fresh_types
    
    @staticmethod
    def normalize_fmp_profile(profile: dict) -> str:
        """Convert FMP profile to standardized security type"""
        if profile.get("isEtf", False):
            return "etf"
        elif profile.get("isFund", False):
            return "mutual_fund"
        elif profile.get("ticker", "").startswith("CUR:"):
            return "cash"
        else:
            return "equity"
    
    @staticmethod
    def _update_database_cache(ticker: str, security_type: str, fmp_profile: dict) -> None:
        """Update database cache with fresh security type data"""
        with get_db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO security_types (ticker, security_type, fmp_data, last_updated)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (ticker) DO UPDATE SET
                    security_type = EXCLUDED.security_type,
                    fmp_data = EXCLUDED.fmp_data,
                    last_updated = CURRENT_TIMESTAMP
            """, (ticker, security_type, json.dumps(fmp_profile)))
    
    @staticmethod
    def _detect_security_type_heuristic(ticker: str) -> str:
        """Heuristic fallback for security type detection"""
        ticker_upper = ticker.upper()
        
        # Cash position detection
        if ticker_upper.startswith("CUR:") or ticker_upper in {"CASH", "USD", "SGOV"}:
            return "cash"
        
        # Common ETF patterns
        if any(pattern in ticker_upper for pattern in ["ETF", "SPY", "QQQ", "IWM", "SHY"]):
            return "etf"
        
        # Default to equity (conservative approach)
        return "equity"
    
    @staticmethod
    def force_refresh(ticker: str) -> str:
        """Admin function to force refresh specific ticker"""
        profile = fetch_profile(ticker)  # Uses LFU cache
        security_type = SecurityTypeService.normalize_fmp_profile(profile)
        SecurityTypeService._update_database_cache(ticker, security_type, profile)
        return security_type
```

**Normalization Logic:**
```python
def normalize_fmp_profile(profile: dict) -> str:
    """Convert FMP boolean flags to our security type format"""
    if profile.get("isEtf", False):
        return "etf"
    elif profile.get("isFund", False):
        return "mutual_fund"
    elif profile.get("ticker", "").startswith("CUR:"):
        return "cash"
    else:
        return "equity"
```

### **Phase 3: Risk Scoring Integration**

**Enhanced Crash Scenarios:**
```python
# File: settings.py

WORST_CASE_SCENARIOS = {
    "single_stock_crash": 0.80,     # Individual equity positions
    "etf_crash": 0.35,              # Diversified ETFs (market-like risk)
    "mutual_fund_crash": 0.40,      # Mutual funds (moderate diversification)
    "cash_crash": 0.05,             # Cash equivalents (minimal risk)
}

SECURITY_TYPE_CRASH_MAPPING = {
    "equity": "single_stock_crash",
    "etf": "etf_crash", 
    "mutual_fund": "mutual_fund_crash",
    "cash": "cash_crash"
}
```

**Updated Risk Calculation:**
```python
# File: portfolio_risk_score.py

def calculate_concentration_risk_loss(
    summary: Dict[str, Any], 
    leverage_ratio: float,
    security_types: Optional[Dict[str, str]] = None
) -> float:
    """Enhanced concentration risk with security-type-aware crash scenarios"""
    
    # Get security types if not provided
    if not security_types:
        tickers = list(summary["allocations"]["Portfolio Weight"].index)
        security_types = SecurityTypeService.get_security_types(tickers)
    
    # Find largest position
    weights = summary["allocations"]["Portfolio Weight"]
    max_position = weights.abs().max()
    largest_ticker = weights.abs().idxmax()
    
    # Apply appropriate crash scenario based on security type
    security_type = security_types.get(largest_ticker, "equity")
    crash_scenario_key = SECURITY_TYPE_CRASH_MAPPING.get(security_type, "single_stock_crash")
    crash_scenario = WORST_CASE_SCENARIOS[crash_scenario_key]
    
    return max_position * crash_scenario * leverage_ratio
```

### **Phase 4: Data Migration Strategy**

**Migration Steps:**
1. **Create security_types table** with proper indexes
2. **Populate initial data** from existing portfolio tickers
3. **Update data ingestion** to ignore provider security types
4. **Modify risk scoring** to use SecurityTypeService
5. **Add background refresh** job for cache maintenance

**Data Sources Priority:**
```python
# Remove dependency on provider security types
# OLD: Use Plaid/SnapTrade security_type fields
# NEW: Use FMP API as single source of truth

# Provider data still used for:
# - Position quantities, values, currencies
# - Account information, cost basis
# - NOT security type classification
```

## 🔄 **Integration Points**

### **Portfolio Risk Scoring Integration**

**Primary Integration: `calculate_concentration_risk_loss()` Function**

```python
# File: portfolio_risk_score.py
# Function: calculate_concentration_risk_loss()

# BEFORE (Current Implementation):
def calculate_concentration_risk_loss(summary: Dict[str, Any], leverage_ratio: float) -> float:
    """Calculate concentration risk using generic single stock crash scenario"""
    weights = summary["allocations"]["Portfolio Weight"]
    max_position = weights.abs().max()
    
    # ❌ PROBLEM: Uses same 80% crash scenario for all securities
    single_stock_crash = WORST_CASE_SCENARIOS["single_stock_crash"]  # 80%
    concentration_loss = max_position * single_stock_crash * leverage_ratio
    
    return concentration_loss

# AFTER (Enhanced Implementation):
def calculate_concentration_risk_loss(summary: Dict[str, Any], leverage_ratio: float, portfolio_data: PortfolioData = None) -> float:
    """Calculate concentration risk using security-type-aware crash scenarios"""
    weights = summary["allocations"]["Portfolio Weight"]
    max_position = weights.abs().max()
    largest_ticker = weights.abs().idxmax()
    
    # ✅ SOLUTION: Get security types with provider cash preservation
    tickers = list(weights.index)
    security_types = SecurityTypeService.get_security_types(tickers, portfolio_data)
    
    # Apply security-type-specific crash scenario
    security_type = security_types.get(largest_ticker, "equity")
    crash_scenario = get_crash_scenario_for_security_type(security_type)
    
    concentration_loss = max_position * crash_scenario * leverage_ratio
    return concentration_loss

def get_crash_scenario_for_security_type(security_type: str) -> float:
    """Map security type to appropriate crash scenario"""
    scenario_mapping = {
        "equity": WORST_CASE_SCENARIOS["single_stock_crash"],      # 80%
        "etf": WORST_CASE_SCENARIOS["etf_crash"],                  # 35%
        "mutual_fund": WORST_CASE_SCENARIOS["mutual_fund_crash"],  # 40%
        "cash": WORST_CASE_SCENARIOS["cash_crash"],                # 5%
    }
    return scenario_mapping.get(security_type, WORST_CASE_SCENARIOS["single_stock_crash"])
```

**Enhanced Settings Configuration:**

```python
# File: settings.py
# Add new crash scenarios for different security types

WORST_CASE_SCENARIOS = {
    # Existing scenarios
    "single_stock_crash": 0.80,     # Individual equity failure (Enron, Lehman)
    "momentum_crash": 0.50,         # Momentum factor crash (2000 tech bubble)
    "value_crash": 0.40,            # Value factor crash (2008 financial crisis)
    "sector_crash": 0.50,           # Sector-wide collapse (2008 financials)
    
    # NEW: Security-type-specific scenarios
    "etf_crash": 0.35,              # Diversified ETF crash (market-like risk)
    "mutual_fund_crash": 0.40,      # Mutual fund crash (moderate diversification)
    "cash_crash": 0.05,             # Cash equivalent risk (money market funds)
}

# NEW: Security type to crash scenario mapping
SECURITY_TYPE_CRASH_MAPPING = {
    "equity": "single_stock_crash",
    "etf": "etf_crash", 
    "mutual_fund": "mutual_fund_crash",
    "cash": "cash_crash"
}
```

**Import Statement Addition:**

```python
# File: portfolio_risk_score.py
# Add import at the top of the file

from services.security_type_service import SecurityTypeService
```

**Function Call Integration:**

```python
# File: portfolio_risk_score.py
# Function: calculate_portfolio_risk_score() - Line ~1610

def calculate_portfolio_risk_score(
    summary: Dict[str, Any],
    portfolio_limits: Dict[str, float],
    concentration_limits: Dict[str, float],
    variance_limits: Dict[str, float],
    max_betas: Dict[str, float],
    max_proxy_betas: Optional[Dict[str, float]] = None,
    leverage_ratio: float = 1.0,
    max_single_factor_loss: float = None
) -> Dict[str, Any]:
    """
    Calculate comprehensive portfolio risk score with security-type awareness.
    
    Enhanced to use SecurityTypeService for accurate security classification,
    ensuring appropriate crash scenarios for different asset types.
    """
    
    # ... existing code ...
    
    # ENHANCED: Concentration risk calculation with security type awareness
    concentration_loss = calculate_concentration_risk_loss(summary, leverage_ratio)
    
    # ... rest of existing code remains unchanged ...
```

**Expected Impact Examples:**

```python
# DSU (Mutual Fund) Example:
# BEFORE: DSU treated as equity → 80% crash scenario → High concentration risk
# AFTER:  DSU identified as mutual_fund → 40% crash scenario → Appropriate risk

# SPY (ETF) Example:  
# BEFORE: SPY treated as equity → 80% crash scenario → Overestimated risk
# AFTER:  SPY identified as etf → 35% crash scenario → Market-appropriate risk

# AAPL (Individual Stock) Example:
# BEFORE: AAPL treated as equity → 80% crash scenario → Correct
# AFTER:  AAPL identified as equity → 80% crash scenario → Still correct
```

### **Risk Score Component Impact**

The enhanced concentration risk calculation will affect the overall risk score:

```python
# In calculate_portfolio_risk_score() - Component scoring section
component_scores = {
    "factor_risk": score_excess_ratio(factor_loss, user_max_loss),
    "concentration_risk": score_excess_ratio(concentration_loss, user_max_loss),  # ← Enhanced
    "volatility_risk": score_excess_ratio(volatility_loss, user_max_loss),
    "sector_risk": score_excess_ratio(sector_loss, user_max_loss)
}

# DSU Impact: Lower concentration_risk score → Better overall portfolio risk score
```

### **CLI Compatibility** 
- YAML-based workflows automatically get FMP security types
- No breaking changes to existing CLI commands
- Consistent behavior between CLI and API

### **API Enhancement**
- Database portfolios get enhanced security type accuracy
- Real-time FMP lookups for new securities
- Cached responses for performance

### **Data Ingestion**
- Plaid/SnapTrade loaders ignore provider security types
- Focus on position data (shares, values, currencies)
- SecurityTypeService handles all classification

## 📊 **Performance Considerations**

### **Dual-Layer Caching Strategy (Optimized Order)**
- **Layer 1 - LFU memory cache**: Existing `@cache_company_profile` system (1000 items) - FASTEST
- **Layer 2 - Database cache**: Persistent storage with 90-day TTL and stale data refresh
- **Performance**: LFU cache ~0.001ms, Database ~10ms, FMP API ~200ms
- **Cross-user optimization**: Popular stocks (AAPL, MSFT) stay in LFU cache
- **Automatic eviction**: LFU keeps most accessed securities in memory
- **Persistence**: Database cache survives server restarts and provides fallback

### **API Rate Limits**
- FMP allows 250 calls/day on free tier, 10,000+ on paid
- Cache hit rate should be >95% after initial population
- Batch unknown securities during off-peak hours

### **Stale Data Refresh Logic**
```python
def get_security_types(tickers: List[str]) -> Dict[str, str]:
    """Database cache with automatic stale data refresh"""
    security_types = {}
    stale_tickers = []
    
    # 1. Database lookup with TTL check
    with get_db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ticker, security_type, 
                   CASE WHEN last_updated < NOW() - INTERVAL '90 days' 
                        THEN true ELSE false END as is_stale
            FROM security_types 
            WHERE ticker = ANY(%s)
        """, (tickers,))
        
        for ticker, sec_type, is_stale in cursor.fetchall():
            security_types[ticker] = sec_type
            if is_stale:
                stale_tickers.append(ticker)
    
    # 2. Identify completely missing tickers
    missing_tickers = [t for t in tickers if t not in security_types]
    
    # 3. Refresh stale + missing tickers from FMP
    refresh_tickers = stale_tickers + missing_tickers
    if refresh_tickers:
        fresh_types = fetch_and_update_from_fmp(refresh_tickers)
        security_types.update(fresh_types)
    
    return security_types

def fetch_and_update_from_fmp(tickers: List[str]) -> Dict[str, str]:
    """Fetch from FMP and update database with fresh data"""
    fresh_types = {}
    
    for ticker in tickers:
        try:
            profile = fetch_profile(ticker)
            security_type = normalize_fmp_profile(profile)
            fresh_types[ticker] = security_type
            
            # Update database with fresh data
            update_security_type_cache(ticker, security_type, profile)
            
        except Exception as e:
            # Fallback to heuristic if FMP fails
            fresh_types[ticker] = detect_security_type_heuristic(ticker)
    
    return fresh_types
```

### **Manual Refresh Interface**
```python
class SecurityTypeService:
    @staticmethod
    def force_refresh(ticker: str) -> str:
        """Admin function to force refresh specific ticker"""
        profile = fetch_profile(ticker)
        security_type = normalize_fmp_profile(profile)
        update_security_type_cache(ticker, security_type, profile)
        return security_type
    
    @staticmethod
    def bulk_refresh(tickers: List[str]) -> Dict[str, str]:
        """Admin function to refresh multiple tickers"""
        return fetch_and_update_from_fmp(tickers)
```

## 🧪 **Testing Strategy**

### **Unit Tests**
- SecurityTypeService methods
- FMP profile normalization
- Cache hit/miss scenarios
- Fallback behavior

### **Integration Tests**
- End-to-end risk scoring with DSU
- CLI vs API consistency
- Database migration validation

### **Performance Tests**
- Cache performance under load
- FMP API response times
- Batch processing efficiency

## 🚀 **Expected Outcomes**

### **Immediate Benefits**
- **DSU gets correct 40% crash scenario** instead of 80%
- **Consistent security classification** across all system components
- **No provider conflicts** - single source of truth
- **Leverages existing architecture** - integrates with current LFU cache system

### **Performance Benefits (Dual-Layer Caching)**
- **Ultra-fast lookups**: Popular securities cached in memory (~0.001ms)
- **Cross-user optimization**: AAPL cached for all users after first lookup
- **Persistent storage**: Database cache survives server restarts
- **Minimal API costs**: LFU cache dramatically reduces FMP API calls

### **Long-term Benefits**
- **Scalable architecture** for new security types
- **Professional-grade data quality** from FMP
- **Reduced maintenance** - no provider reconciliation needed
- **Enhanced risk accuracy** for all security types
- **Consistent with codebase patterns** - uses existing proxy_builder infrastructure

## 📅 **Implementation Timeline**

**Week 1: Foundation**
- Create database schema
- Implement SecurityTypeService core methods
- Add FMP profile normalization

**Week 2: Integration** 
- Update portfolio_risk_score.py
- Modify data ingestion to ignore provider types
- Add caching layer

**Week 3: Testing & Migration**
- Populate security_types table
- Run comprehensive tests
- Deploy with feature flag

**Week 4: Monitoring & Optimization**
- Monitor cache hit rates
- Optimize batch processing
- Performance tuning

## 🔍 **Success Metrics**

- **DSU risk score accuracy**: Verify 40% crash scenario applied
- **Cache hit rate**: Target >95% after initial population  
- **API response time**: <100ms for cached lookups
- **Data consistency**: Zero security type conflicts
- **System reliability**: 99.9% uptime for security type lookups

---

## 📝 **Next Steps**

1. **Review and approve** this architecture plan
2. **Create database migration** scripts
3. **Implement SecurityTypeService** core functionality
4. **Update risk scoring** integration points
5. **Test with DSU** to validate fix

**Priority**: High - Fixes critical risk scoring accuracy issue for mutual funds and ETFs.
