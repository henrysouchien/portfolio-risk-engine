# Asset Class Extension Plan

**Status**: Planning document - Extends existing SecurityTypeService for intelligent asset class detection

## **🎯 Overview**

This document outlines the extension of the existing **SecurityTypeService** to add intelligent asset class detection capabilities. Rather than rebuilding the architecture, we leverage the proven 3-tier caching system and add asset class intelligence on top.

### **Current State**
- ✅ **SecurityTypeService exists** with multi-tier caching (LFU + database + FMP API)
- ✅ **Provider integration** working (Plaid, SnapTrade)
- ✅ **Current classifications**: `equity`, `etf`, `mutual_fund`, `cash`
- ❌ **Missing**: Asset class intelligence for fixed income analytics

### **Target State**
- ✅ **Extended SecurityTypeService** with asset class detection
- ✅ **Asset class classifications**: `equity`, `bond`, `reit`, `commodity`, `crypto`, `cash`, `mixed`
- ✅ **3-tier classification strategy**: Provider → FMP → AI
- ✅ **Foundation for fixed income analytics**

## **🏗️ 3-Tier Asset Class Classification Strategy**

### **Tier 1: Provider Data (Plaid/SnapTrade) - AUTHORITATIVE**
**Priority**: Highest - Trust provider expertise where available
**Performance**: Immediate (already cached)
**Coverage**: Limited but highly accurate for specific asset classes

```python
def get_asset_class_from_provider(ticker: str, portfolio_data: PortfolioData) -> Optional[str]:
    """
    Use direct provider classifications from security_type_mappings.yaml
    
    SNAPTRADE DIRECT MAPPINGS (HUGE ADVANTAGE):
    - bnd: bond           # Bond - Direct classification!
    - cash: cash          # Cash Balance - Direct classification!
    - cs/ps/ad: equity    # Common/Preferred Stock, ADR
    - crypto: crypto      # Cryptocurrency - Direct classification!
    - et/oef/cef: mixed   # ETFs/Funds - need deeper analysis
    
    PLAID DIRECT MAPPINGS (EXCELLENT COVERAGE):
    - cash: cash                    # Cash, money market funds
    - "fixed income": bond          # Bonds and CDs - DIRECT!
    - equity: equity                # Domestic and foreign equities  
    - cryptocurrency: crypto        # Digital currencies
    - etf/"mutual fund": mixed      # Multi-asset funds - need analysis
    - loan: bond                    # Loans - treat as fixed income
    
    CLASSIFICATION STRATEGY:
    1. Check provider type against asset_class_mappings in YAML
    2. Direct mapping where provider has clear classification
    3. Return None for ambiguous types (et, oef, cef, etf, mutual fund) → Tier 2
    
    EXAMPLES:
    - SnapTrade "bnd" → bond (authoritative!)
    - Plaid "fixed income" → bond (authoritative!)
    - SnapTrade "crypto" → crypto (authoritative!)
    - Plaid "etf" → None (needs FMP analysis)
    """
```

**Implementation Strategy**:
- **Use existing asset_class_mappings** from security_type_mappings.yaml
- **Leverage provider expertise** for clear classifications (bonds, cash, crypto)
- **Skip ambiguous types** (ETFs, mutual funds) → pass to Tier 2 FMP analysis
- **Extend existing provider data flows** in plaid_loader.py and snaptrade_loader.py
- **Cache results** in existing database structure

**Utility Function Extensions (utils/security_type_mappings.py)**:
```python
def get_asset_class_mapping() -> Dict[str, Dict[str, str]]:
    """Get provider-specific asset class mappings from YAML"""
    mappings = get_security_type_mappings()
    return mappings.get('asset_class_mappings', {})

def map_provider_to_asset_class(provider: str, provider_type: str) -> Optional[str]:
    """Map provider type to asset class using centralized YAML mappings"""
    asset_mappings = get_asset_class_mapping()
    provider_mappings = asset_mappings.get(provider, {})
    return provider_mappings.get(provider_type.lower())
```

### **Tier 2: FMP Industry Classification via Extended industry_to_etf.yaml - INTELLIGENT**
**Priority**: Medium - Leverage existing FMP profile data + industry mappings
**Performance**: Fast (uses existing LFU cache via fetch_profile)
**Coverage**: Comprehensive for most securities with existing industry mappings

```python
def get_asset_class_from_fmp(ticker: str, profile: dict) -> Optional[str]:
    """
    Use FMP industry data with extended industry_to_etf.yaml for asset class detection
    
    ARCHITECTURE:
    1. FMP provides industry: profile.get("industry") → "Gold", "Oil & Gas E&P", "Real Estate - Services"
    2. Extended industry_to_etf.yaml maps: industry → {etf: "GDX", asset_class: "commodity"}
    3. Direct lookup: industry → asset_class (clean, single source of truth)
    
    EXTENDED YAML STRUCTURE:
    Gold:
      etf: GDX
      asset_class: commodity
    "Oil & Gas E&P":
      etf: XOP  
      asset_class: commodity
    "Real Estate - Services":
      etf: IYR
      asset_class: reit
    "Consumer Electronics":
      etf: XLK
      asset_class: equity
    
    BENEFITS:
    - Single source of truth for both ETF and asset class mappings
    - Automatic sync when industry mappings change
    - Leverages existing, proven industry classification system
    - No double indirection (industry → ETF → asset class)
    """
```

**Implementation Strategy**:
- **Extend industry_to_etf.yaml** with asset_class field for each industry
- **Update load_industry_etf_map()** to handle new structure
- **Use existing fetch_profile(ticker)** function (LFU cached)
- **Direct industry lookup** in extended mapping file
- **Store results** in existing database cache

**Code Changes Required**:
- Update `proxy_builder.py` functions to handle new YAML structure
- Modify `map_industry_etf()` to access `.etf` field
- Add `get_asset_class_from_industry()` function for asset class lookup

**Proxy Builder Function Extensions (proxy_builder.py)**:
```python
def load_industry_etf_map() -> dict:
    """
    Load extended YAML with both etf and asset_class fields
    UPDATED: Handle new structure {industry: {etf: "XLK", asset_class: "equity"}}
    """

def map_industry_etf(industry: str, etf_map: dict) -> str:
    """
    UPDATED: Access .etf field from extended structure
    OLD: etf_map.get(industry)
    NEW: etf_map.get(industry, {}).get('etf')
    """

def map_industry_asset_class(industry: str, industry_map: dict) -> Optional[str]:
    """
    NEW: Map FMP industry to asset class via extended YAML
    Returns: industry_map.get(industry, {}).get('asset_class')
    """
```

### **Tier 3: AI Classification (GPT) - FALLBACK**
**Priority**: Lowest - Only when other methods fail
**Performance**: Slow (~2-3 seconds) but cached
**Coverage**: Universal fallback for edge cases and complex securities

```python
def get_asset_class_from_ai(ticker: str, profile: dict) -> Optional[tuple[str, float]]:
    """
    Use GPT for semantic asset class detection via FMP profile description
    
    FOLLOWS EXISTING SUBINDUSTRY PEERS PATTERN:
    - Database-first caching (check asset_class_cache table)
    - Uses existing GPT integration from gpt_helpers.py
    - Respects gpt_enabled() configuration  
    - Caches results with source tracking
    - Error handling with fallback to "mixed"
    
    INPUT DATA (from FMP profile):
    - symbol: ticker for context
    - companyName: "BlackRock Debt Strategies Fund, Inc."
    - description: Full semantic description with business details
    
    GPT PROMPT STRATEGY:
    - Clear 7-category classification: equity, bond, reit, commodity, crypto, cash, mixed
    - Structured output format: "asset_class,confidence_score"
    - Examples for each category
    - Confidence scoring (0.0-1.0 scale)
    
    EXAMPLE FLOW:
    Input: DSU profile with "fixed income", "debt instruments", "corporate loans"
    GPT Response: "bond,0.95"
    Parsed: ("bond", 0.95)
    Cached: database with source='gpt'
    
    RESPONSE PARSING:
    - Split on comma: asset_class, confidence = response.split(',')
    - Validate asset_class in allowed categories
    - Validate confidence is float 0.0-1.0
    - Return ("mixed", 0.5) if parsing fails
    """
```

**Implementation Strategy**:
- **Follow subindustry peers pattern** from `proxy_builder.py`
- **Reuse GPT infrastructure** from `gpt_helpers.py` 
- **Database-first caching** in new `asset_class_cache` table
- **Structured prompt** with clear format requirements
- **Response validation** and error handling
- **Confidence scoring** for quality assessment (threshold TBD)

**GPT Function Specification (gpt_helpers.py)**:
```python
def generate_asset_class_classification(ticker: str, company_name: str, description: str) -> str:
    """
    GPT function for asset class classification (follows generate_subindustry_peers pattern)
    
    Args:
        ticker: Stock symbol (e.g., "DSU")
        company_name: Company name from FMP (e.g., "BlackRock Debt Strategies Fund, Inc.")
        description: Company description from FMP profile
        
    Returns:
        String in format "asset_class,confidence_score" (e.g., "bond,0.95")
        
    Prompt Strategy:
        - Clear 7-category classification (equity, bond, reit, commodity, crypto, cash, mixed)
        - Focus on investment exposure, not legal structure
        - Return format: "asset_class,confidence_score"
        - Confidence range: 0.00-1.00
    """
```

## **🔧 SecurityTypeService Extension Architecture**

### **New Methods to Add**

```python
class SecurityTypeService:
    # ... all existing methods unchanged ...
    
    @staticmethod
    @log_performance(0.5)
    @log_cache_operations("asset_class_service")
    def get_asset_classes(tickers: List[str], portfolio_data: PortfolioData = None) -> Dict[str, str]:
        """
        NEW: Get asset classes using 3-tier strategy
        
        Returns:
            Dict mapping tickers to asset classes:
            {"SPY": "equity", "TLT": "bond", "VNQ": "reit", "GLD": "commodity", "SGOV": "cash"}
        """
    
    @staticmethod
    def get_asset_class(ticker: str, portfolio_data: PortfolioData = None) -> str:
        """
        NEW: Get single asset class (convenience method)
        """
        return SecurityTypeService.get_asset_classes([ticker], portfolio_data).get(ticker, 'equity')
    
    @staticmethod
    def get_full_classification(tickers: List[str], portfolio_data: PortfolioData = None) -> Dict[str, Dict]:
        """
        NEW: Get both security type and asset class efficiently in single call
        
        Returns:
            Dict mapping tickers to both classifications:
            {
                "AAPL": {"security_type": "equity", "asset_class": "equity"},
                "TLT": {"security_type": "etf", "asset_class": "bond"},
                "VNQ": {"security_type": "etf", "asset_class": "reit"}
            }
        """
    
    @staticmethod
    def _classify_asset_class_tier1(ticker: str, portfolio_data: PortfolioData) -> Optional[str]:
        """
        NEW: Tier 1 - Provider data classification
        """
    
    @staticmethod
    def _classify_asset_class_tier2(ticker: str) -> Optional[str]:
        """
        NEW: Tier 2 - FMP industry classification
        """
    
    @staticmethod
    def _classify_asset_class_tier3(ticker: str) -> Optional[str]:
        """
        NEW: Tier 3 - AI classification
        """
    
    @staticmethod
    def _update_asset_class_cache(ticker: str, asset_class: str, source: str) -> None:
        """
        NEW: Cache asset class results in database
        """
```

### **Database Schema Extension**

**Migration File**: `database/migrations/20250101_add_asset_class_columns.sql`

```sql
-- ============================================================================
-- ASSET CLASS EXTENSION MIGRATION
-- ============================================================================
-- Migration: 20250101_add_asset_class_columns.sql
-- Purpose: Extend security_types table with asset class classification columns
-- 
-- Background:
-- - Adds asset class intelligence to existing SecurityTypeService
-- - Follows established patterns from subindustry_peers table
-- - Enables 3-tier classification strategy (provider -> FMP -> AI)
-- ============================================================================

-- Extend existing security_types table
ALTER TABLE security_types ADD COLUMN IF NOT EXISTS asset_class VARCHAR(20);
ALTER TABLE security_types ADD COLUMN IF NOT EXISTS asset_class_source VARCHAR(20); -- 'provider', 'fmp', 'ai'
ALTER TABLE security_types ADD COLUMN IF NOT EXISTS asset_class_confidence DECIMAL(3,2); -- 0.00-1.00 for AI
ALTER TABLE security_types ADD COLUMN IF NOT EXISTS asset_class_updated TIMESTAMP;

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_security_types_asset_class ON security_types(asset_class);
CREATE INDEX IF NOT EXISTS idx_security_types_asset_class_source ON security_types(asset_class_source);
```

## **📊 Asset Class Categories**

### **Complete Asset Class Taxonomy** (7 Categories)

1. **`equity`** - Stocks, equity funds, equity ETFs
   - **Examples**: AAPL, MSFT, SPY, VTI, VXUS
   - **Risk Model**: Existing equity factor models (market, value, momentum)
   - **Provider Hints**: Plaid `"equity"`, SnapTrade `"cs"` (common stock)

2. **`bond`** - Government/corporate bonds, bond ETFs/funds  
   - **Examples**: TLT, AGG, BND, SHY, IEF, LQD, HYG, individual bonds
   - **Risk Model**: Duration-based fixed income analytics ← **Primary goal**
   - **Provider Hints**: SnapTrade `"bnd"` (direct!), Plaid security names with "bond"/"treasury"

3. **`reit`** - Real estate investment trusts, real estate ETFs/funds
   - **Examples**: VNQ, SCHH, RWR, IYR, individual REITs (like AMT, PLD)
   - **Risk Model**: Hybrid equity/real estate factors, interest rate sensitivity
   - **Provider Hints**: Security names with "real estate"/"REIT", FMP industry "Real Estate"

4. **`commodity`** - Commodity ETFs, precious metals, energy
   - **Examples**: GLD, SLV, DJP, USO, PDBC, IAU
   - **Risk Model**: Commodity-specific factors, inflation hedging
   - **Provider Hints**: Security names with "gold"/"silver"/"oil"/"commodity"

5. **`cash`** - Cash equivalents, money market funds, short-term treasury bills
   - **Examples**: SGOV, SHY (ultra-short), money market funds, actual cash positions
   - **Risk Model**: Minimal risk, very short duration
   - **Provider Hints**: Plaid `"cash"`, SnapTrade `"cash"`, CUR: prefixes

6. **`crypto`** - Cryptocurrency and digital assets
   - **Examples**: Bitcoin, Ethereum, crypto ETFs, digital asset funds
   - **Risk Model**: High volatility, alternative asset class
   - **Provider Hints**: Plaid `"cryptocurrency"`, SnapTrade `"crypto"`, security names with "Bitcoin"/"Ethereum"/"Crypto"

7. **`mixed`** - Multi-asset funds, target-date funds, balanced funds
   - **Examples**: Target-date funds (VTTSX), balanced funds (VBIAX), lifecycle funds
   - **Risk Model**: Blended approach based on underlying asset allocation
   - **Provider Hints**: Security names with "target"/"balanced"/"lifecycle", FMP fund analysis

### **Classification Priority Matrix**

| Ticker Type | Tier 1 (Provider) | Tier 2 (FMP) | Tier 3 (AI) |
|-------------|-------------------|---------------|--------------|
| Individual Stocks | Limited | ✅ Industry/Sector | ✅ GPT |
| ETFs | Security Name | ✅ Industry Analysis | ✅ GPT |
| Mutual Funds | Security Name | ✅ Industry Analysis | ✅ GPT |
| Cash/MMF | ✅ Provider Type | Limited | ✅ GPT |
| Bonds | ✅ Provider Type | ✅ Industry | ✅ GPT |
| Crypto | ✅ Provider Type | Limited | ✅ GPT |

## **🚀 Implementation Phases**

### **Phase 1: Core Extension (2-3 hours)**
- [ ] Add asset class methods to SecurityTypeService
- [ ] Implement Tier 1 (provider data) classification
- [ ] Implement Tier 2 (FMP industry) classification
- [ ] Add database schema extension
- [ ] Add caching for asset class results

### **Phase 2: AI Integration (1-2 hours)**
- [ ] Implement Tier 3 (GPT) classification
- [ ] Integrate with existing Claude service
- [ ] Add rate limiting and error handling
- [ ] Test AI classification accuracy

### **Phase 3: Testing & Validation (1 hour)**
- [ ] Test with common tickers (SPY, TLT, VNQ, GLD, SGOV)
- [ ] Validate classification accuracy
- [ ] Performance testing with existing cache
- [ ] Integration testing with portfolio analysis

### **Phase 4: Integration Points (1 hour)**
- [ ] Update portfolio analysis to use asset classes
- [ ] Prepare foundation for fixed income analytics
- [ ] Add asset class reporting to CLI/API
- [ ] Documentation updates

## **🔗 Integration Points**

### **Existing Services That Will Use Asset Classes**
1. **Fixed Income Analytics** (next phase)
   - Duration/convexity calculations for bonds
   - REIT-specific risk models
   - Yield vs capital return separation

2. **Portfolio Analysis Services**
   - Asset allocation reporting
   - Risk model selection based on asset class
   - Performance attribution by asset class

3. **AI/Claude Integration**
   - Contextual recommendations based on asset classes
   - Asset class-specific insights
   - Portfolio construction suggestions

### **API Endpoints to Enhance**
- `/api/analyze` - Add asset class breakdown
- `/api/portfolio-analysis` - Include asset allocation
- `/api/risk-score` - Asset class-specific risk factors

## **🔧 Admin Management Extensions**

### **Required Admin Script Updates**

The existing admin infrastructure needs to be extended to support asset class management:

**1. migrate_reference_data.py Extensions**:
```python
def migrate_asset_class_mappings(db_client):
    """Migrate asset class mappings from security_type_mappings.yaml to database"""
    # NEW: Add asset_class_mappings section migration
    # Populate asset class provider mappings (snaptrade, plaid)
    # Handle extended industry_to_etf.yaml structure with asset_class field

def migrate_extended_industry_mappings(db_client):
    """Migrate extended industry mappings with asset_class field"""
    # UPDATED: Handle new YAML structure {industry: {etf: "XLK", asset_class: "equity"}}
    # Populate both industry_mappings and new asset_class data
```

**2. manage_reference_data.py Extensions**:
```bash
# NEW COMMANDS TO ADD:
python admin/manage_reference_data.py asset-class list
python admin/manage_reference_data.py asset-class add snaptrade bnd bond
python admin/manage_reference_data.py asset-class add plaid "fixed income" bond
python admin/manage_reference_data.py asset-class clear-cache
python admin/manage_reference_data.py asset-class stats
python admin/manage_reference_data.py asset-class validate AAPL
```

**3. manage_security_types.py Extensions**:
```python
def asset_class_stats(db_client):
    """Show asset class classification statistics"""
    # NEW: Asset class distribution by source (provider/fmp/ai)
    # Classification accuracy metrics
    # Cache hit rates for asset class lookups

def validate_asset_class(db_client, ticker: str):
    """Validate asset class classification for specific ticker"""
    # NEW: Show classification path (tier 1/2/3)
    # Display confidence scores and sources
    # Compare against manual classification if available

def bulk_refresh_asset_classes(db_client):
    """Refresh stale asset class entries"""
    # NEW: Find entries older than threshold
    # Re-run 3-tier classification
    # Update database with new results
```

### **Database Schema Management**

**Migration Integration**:
- Extend existing migration system to handle asset class schema changes
- Add asset class columns to security_types table via migration script
- Update database triggers to handle asset class cache invalidation

**Cache Management**:
- Extend existing cache invalidation triggers for asset class changes
- Add asset class-specific cache statistics and monitoring
- Integrate with existing SecurityTypeService cache management

### **YAML Structure Management**

**Extended industry_to_etf.yaml Management**:
```python
def update_industry_asset_class(industry: str, etf: str, asset_class: str):
    """Update industry mapping with both ETF and asset class"""
    # Handle new structure: {industry: {etf: "XLK", asset_class: "equity"}}
    # Validate asset class against 7-category taxonomy
    # Update both database and YAML file

def validate_yaml_structure():
    """Validate extended YAML structure consistency"""
    # Ensure all industries have both etf and asset_class fields
    # Validate asset class values against taxonomy
    # Check for missing or malformed entries
```

### **Operational Commands**

**Daily Operations**:
```bash
# Monitor asset class classification health
python admin/manage_security_types.py asset-class-stats

# Validate specific classifications
python admin/manage_reference_data.py asset-class validate DSU TLT VNQ

# Refresh stale classifications
python admin/manage_security_types.py bulk-refresh-asset-classes
```

**Migration Operations**:
```bash
# Initial setup - migrate existing data
python admin/migrate_reference_data.py --include-asset-classes

# Update industry mappings with asset classes
python admin/manage_reference_data.py industry update-asset-classes

# Validate migration completeness
python admin/manage_reference_data.py asset-class validate-migration
```

## **📈 Performance Considerations**

### **Caching Strategy**
**FOLLOWS EXISTING PATTERNS**: Same database-first approach as security_types, subindustry_peers

**Performance Tiers:**
- **Tier 1**: Immediate (provider data already loaded)
- **Tier 2**: ~10ms (existing LFU cache via fetch_profile)
- **Tier 3**: ~2-3s first time, then cached (database + LFU)
- **Overall**: 95% of requests served from cache

**Database Schema (see Database Schema Extension section above for details)**

**DatabaseClient Extensions (inputs/database_client.py):**
```python
def get_asset_class(self, ticker: str) -> Optional[Dict[str, Any]]:
    """Get asset class for ticker from security_types table (follows subindustry_peers pattern)"""
    
def save_asset_class(self, ticker: str, asset_class: str, 
                    source: str = 'unknown', confidence: float = None) -> None:
    """Save asset class to security_types table (follows existing update patterns)"""
    
def get_asset_class_stats(self) -> Dict[str, int]:
    """Get asset class statistics by source (follows existing stats patterns)"""
```

**Database Flow (follows subindustry_peers pattern):**
1. **Check security_types table first** - `get_asset_class(ticker)`
2. **If found**: Return immediately with source tracking
3. **If not found**: Run 3-tier classification
4. **Save result**: `save_asset_class(ticker, result, source, confidence)`
5. **Error handling**: Continue even if database operations fail

### **Fallback Performance**
- Provider data: 100% reliable when available
- FMP data: 95% reliable (existing infrastructure)
- AI classification: 90% reliable (with rate limiting)
- Default fallback: 100% reliable (equity classification)

## **🧪 Testing Strategy**

### **Test Cases**
```python
# Common test tickers by asset class
TEST_CASES = {
    "equity": ["AAPL", "MSFT", "GOOGL", "SPY", "VTI"],
    "bond": ["TLT", "AGG", "BND", "SHY", "IEF", "LQD", "HYG"],
    "reit": ["VNQ", "SCHH", "RWR", "IYR"],
    "commodity": ["GLD", "SLV", "DJP", "USO"],
    "crypto": ["BITO", "ETHE", "GBTC"],  # Crypto ETFs and funds
    "cash": ["SGOV", "SHY"],  # Note: SHY could be bond or cash depending on context
    "mixed": ["VTTSX", "VBIAX"]  # Target-date and balanced funds
}
```

### **Validation Metrics**
- Classification accuracy: >90% for common tickers
- Performance: <100ms for cached results
- Coverage: 100% (with fallback to equity)
- Cache hit rate: >95% after warm-up

## **🔄 Migration Strategy**

### **Backward Compatibility**
- All existing SecurityTypeService methods unchanged
- New asset class methods are additive
- Existing security type classifications preserved
- No breaking changes to current functionality

### **Gradual Rollout**
1. **Phase 1**: Add asset class methods (no consumers yet)
2. **Phase 2**: Update new features to use asset classes
3. **Phase 3**: Migrate existing features gradually
4. **Phase 4**: Deprecate old patterns (future)

## **📊 Success Metrics**

### **Technical Metrics**
- [ ] Asset class classification accuracy >90%
- [ ] Performance <100ms for cached results
- [ ] Cache hit rate >95%
- [ ] Zero breaking changes to existing functionality

### **Business Metrics**
- [ ] Foundation ready for fixed income analytics
- [ ] Asset allocation reporting available
- [ ] AI recommendations become asset class-aware
- [ ] Platform supports 80% of retail portfolios (stocks + bonds + REITs)

## **🎯 Next Steps**

1. **Review and approve** this extension plan
2. **Implement Phase 1** (core extension) - 2-3 hours
3. **Test with common tickers** - validate accuracy
4. **Implement AI integration** - 1-2 hours  
5. **Build fixed income analytics** on this foundation

**Total Implementation Time**: 4-6 hours for complete asset class intelligence

This extension provides the **foundation for intelligent portfolio analysis** that can properly handle bonds, REITs, and other asset classes - transforming your platform from equity-focused to comprehensive portfolio intelligence.
