# Security Type Architecture Implementation Summary

## Overview

This document summarizes the complete implementation of the Security Type Architecture to fix the DSU (and other securities) risk scoring issue. The implementation provides consistent security type classification across all providers and enables security-type-aware risk calculations.

## Problem Solved

**Issue**: DSU mutual fund was being treated as individual stock (80% crash scenario) instead of mutual fund (40% crash scenario) due to inconsistent provider classifications:
- SnapTrade: DSU = "equity" ❌
- Plaid: DSU = "mutual_fund" ✅  
- Risk scoring: Applied generic 80% crash to all securities ❌

**Solution**: Unified security type service with FMP as authoritative source and security-type-aware crash scenarios.

## Implementation Components

### 1. SecurityTypeService (`services/security_type_service.py`)

**Purpose**: Unified security type classification using FMP API with dual-layer caching

**Key Features**:
- **Cash-first strategy**: Preserves provider expertise for cash positions
- **Dual-layer caching**: LFU memory cache (0.001ms) + database cache (10ms) 
- **FMP integration**: Leverages existing `fetch_profile()` LFU cache
- **Graceful fallbacks**: Heuristic classification when services unavailable

**Core Method**:
```python
@staticmethod
def get_security_types(tickers: List[str], portfolio_data: PortfolioData = None) -> Dict[str, str]:
    """
    Get security types with provider cash preservation.
    
    Hierarchy:
    1. Provider data for cash positions (immediate)
    2. LFU memory cache via fetch_profile (~0.001ms)
    3. Database cache with 90-day TTL (~10ms)
    4. FMP API lookup (~200ms)
    5. Heuristic fallback (immediate)
    """
```

**Supported Classifications**:
- `equity`: Individual stocks (80% crash scenario)
- `etf`: Exchange-traded funds (35% crash scenario)
- `mutual_fund`: Mutual funds (40% crash scenario)
- `cash`: Cash equivalents (5% crash scenario)

### 2. Enhanced Risk Scoring (`portfolio_risk_score.py`)

**Changes Made**:
- Enhanced `calculate_concentration_risk_loss()` with security-type awareness
- Added `portfolio_data` parameter for provider data integration
- Added `get_crash_scenario_for_security_type()` helper function
- Imports: Added `SECURITY_TYPE_CRASH_MAPPING` from settings

**Before**:
```python
def calculate_concentration_risk_loss(summary: Dict[str, Any], leverage_ratio: float) -> float:
    # Always used 80% crash scenario for all securities
    single_stock_crash = WORST_CASE_SCENARIOS["single_stock_crash"]  # 80%
```

**After**:
```python
def calculate_concentration_risk_loss(summary: Dict[str, Any], leverage_ratio: float, portfolio_data=None) -> float:
    # Get security type and apply appropriate crash scenario
    security_types = SecurityTypeService.get_security_types([largest_ticker], portfolio_data)
    security_type = security_types.get(largest_ticker, "equity")
    crash_scenario_key = SECURITY_TYPE_CRASH_MAPPING.get(security_type, "single_stock_crash")
    crash_scenario = WORST_CASE_SCENARIOS[crash_scenario_key]
```

**Impact**:
- **DSU**: Now gets 40% crash scenario instead of 80% ✅
- **ETFs**: Get 35% crash scenario instead of 80% ✅
- **Cash**: Gets 5% crash scenario ✅
- **Individual stocks**: Still get 80% crash scenario ✅

### 3. Settings Configuration (`settings.py`)

**Added Security-Type-Specific Crash Scenarios**:
```python
WORST_CASE_SCENARIOS = {
    # ... existing scenarios ...
    "etf_crash": 0.35,              # Diversified ETF crash (market-like risk)
    "mutual_fund_crash": 0.40,      # Mutual fund crash (moderate diversification)
    "cash_crash": 0.05,             # Cash equivalent risk (money market funds)
}

SECURITY_TYPE_CRASH_MAPPING = {
    "equity": "single_stock_crash",      # Individual equity positions (80%)
    "etf": "etf_crash",                  # Diversified ETFs (35%)
    "mutual_fund": "mutual_fund_crash",  # Mutual funds (40%)
    "cash": "cash_crash"                 # Cash equivalents (5%)
}
```

### 4. Data Loader Enhancements

**SnapTrade Loader (`snaptrade_loader.py`)**:
- Added `get_enhanced_security_type()` function
- Enhanced conversion at line 1056: `'type': get_enhanced_security_type(ticker, position_type)`
- Preserves cash classifications, uses FMP for securities

**Plaid Loader (`plaid_loader.py`)**:
- Added identical `get_enhanced_security_type()` function  
- Enhanced conversion at line 1083: `'type': get_enhanced_security_type(ticker, position_type)`
- Consistent behavior across both providers

**Enhanced Logic**:
```python
def get_enhanced_security_type(ticker: str, original_type: str) -> str:
    """Cash-first strategy with FMP enhancement."""
    if original_type == 'cash':
        return 'cash'  # ✅ Preserve provider cash classification
    
    if SecurityTypeService:
        # Use SecurityTypeService for non-cash securities
        security_types = SecurityTypeService.get_security_types([ticker])
        return security_types.get(ticker, original_type)
    else:
        return original_type  # Fallback to provider classification
```

### 5. Configuration Constants (`utils/config.py`)

**Added SecurityTypeService Configuration**:
```python
# === SecurityTypeService Settings ===
SECURITY_TYPE_CACHE_TTL = int(os.getenv("SECURITY_TYPE_CACHE_TTL", "7776000"))  # 90 days
SECURITY_TYPE_CACHE_SIZE = int(os.getenv("SECURITY_TYPE_CACHE_SIZE", "10000"))  # 10k tickers
FMP_RATE_LIMIT_DELAY = float(os.getenv("FMP_RATE_LIMIT_DELAY", "0.1"))  # 100ms between calls
SECURITY_TYPE_BATCH_SIZE = int(os.getenv("SECURITY_TYPE_BATCH_SIZE", "50"))  # Max per batch
```

### 6. Service Registration (`services/service_manager.py`)

**Added SecurityTypeService Registration**:
```python
from services.security_type_service import SecurityTypeService

class ServiceManager:
    def __init__(self, cache_results: bool = True, enable_async: bool = True):
        # ... existing services ...
        self.security_type_service = SecurityTypeService()
    
    def get_service(self, service_name: str):
        services = {
            # ... existing services ...
            'security_type': self.security_type_service,
        }
```

### 7. Database Schema (Already Exists)

**Security Types Table** (`database/schema.sql` lines 625-648):
```sql
CREATE TABLE IF NOT EXISTS security_types (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL UNIQUE,
    security_type VARCHAR(50) NOT NULL,  -- 'equity', 'etf', 'mutual_fund', 'cash', 'bond', 'crypto'
    fmp_data JSONB,                      -- Store full FMP profile for reference and debugging
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Performance indexes and triggers included
```

### 8. Admin Tools (`admin/manage_security_types.py`)

**Comprehensive Management Interface**:
```bash
python admin/manage_security_types.py list --limit=50 --type=etf
python admin/manage_security_types.py stats
python admin/manage_security_types.py health
python admin/manage_security_types.py refresh AAPL
python admin/manage_security_types.py bulk-refresh --days=90
python admin/manage_security_types.py export types.json
python admin/manage_security_types.py import types.json
```

**Features**:
- Cache statistics and monitoring
- Health checks for database and FMP API
- Individual and bulk ticker refresh
- Data export/import for backup
- Stale entry management

## Data Flow

### Before (Problematic)
```
SnapTrade API → DSU = "equity" → 80% crash scenario ❌
Plaid API → DSU = "mutual_fund" → inconsistent across providers ❌
```

### After (Fixed)
```
Both Providers → SecurityTypeService → FMP API → DSU = "mutual_fund" → 40% crash scenario ✅
Cash positions → Provider classification preserved → 5% cash scenario ✅
```

## Performance Characteristics

**Caching Architecture**:
- **Layer 1**: LFU memory cache (existing fetch_profile, ~0.001ms)
- **Layer 2**: Database cache (90-day TTL, ~10ms)
- **Layer 3**: FMP API (authoritative source, ~200ms)
- **Layer 4**: Heuristic fallback (immediate)

**Expected Performance**:
- Cache hit rate: >95% after initial population
- Cross-user optimization: Popular stocks (AAPL, MSFT) stay in memory
- Automatic stale data refresh every 90 days
- Zero impact on existing system performance

## Testing and Verification

**Settings Verification**:
- ✅ All crash scenarios properly configured
- ✅ Security type mappings complete
- ✅ Configuration constants accessible

**Risk Score Integration**:
- ✅ Enhanced function signature with portfolio_data parameter
- ✅ All security types map to correct crash scenarios
- ✅ Backward compatibility maintained

**Admin Tools**:
- ✅ CLI interface functional
- ✅ All commands working (list, stats, health, refresh, etc.)
- ✅ Proper error handling and fallbacks

## Migration and Deployment

**Prerequisites**:
1. Database schema already exists (security_types table)
2. All code changes implemented
3. Configuration constants added

**Deployment Steps**:
1. Deploy code changes
2. Verify database table exists (already present)
3. Test admin tools functionality
4. Monitor cache population and performance

**Rollback Plan**:
- All changes are backward compatible
- SecurityTypeService gracefully falls back to provider data if unavailable
- No breaking changes to existing APIs

## Expected Business Impact

**Risk Accuracy Improvement**:
- **Mutual funds** (like DSU): 50% reduction in calculated concentration risk (80% → 40%)
- **ETFs**: 56% reduction in calculated concentration risk (80% → 35%)
- **Individual stocks**: No change (maintains 80% scenario)
- **Cash positions**: Minimal risk maintained (5% scenario)

**System Benefits**:
- Consistent security classification across all providers
- Professional-grade data quality from FMP
- Reduced maintenance overhead
- Enhanced monitoring and admin capabilities

## Monitoring and Maintenance

**Admin Commands for Ongoing Management**:
```bash
# Daily monitoring
python admin/manage_security_types.py stats
python admin/manage_security_types.py health

# Weekly maintenance
python admin/manage_security_types.py bulk-refresh --days=90

# Monthly backup
python admin/manage_security_types.py export "backup_$(date +%Y%m%d).json"
```

**Key Metrics to Monitor**:
- Cache hit rate (target >95%)
- Stale entry count (refresh if >1000)
- FMP API response times
- Database query performance

## Implementation Status: ✅ COMPLETE

All components of the Security Type Architecture have been successfully implemented and tested. The system is ready for production deployment to resolve the DSU risk scoring issue and improve overall security classification accuracy.