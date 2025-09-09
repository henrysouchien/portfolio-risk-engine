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
- ✅ **Asset class classifications**: `equity`, `bond`, `reit`, `commodity`, `cash`
- ✅ **3-tier classification strategy**: Provider → FMP → AI
- ✅ **Foundation for fixed income analytics**

## **🏗️ 3-Tier Asset Class Classification Strategy**

### **Tier 1: Provider Data (Plaid/SnapTrade) - AUTHORITATIVE**
**Priority**: Highest - Trust provider expertise where available
**Performance**: Immediate (already cached)
**Coverage**: Limited but highly accurate

```python
def get_asset_class_from_provider(ticker: str, portfolio_data: PortfolioData) -> Optional[str]:
    """
    Extract asset class hints from provider data
    
    Provider Intelligence Sources:
    - security_name: "REIT", "BOND", "TREASURY" keywords
    - type: "cash" → "cash" asset class
    - Provider-specific classifications
    
    Examples:
    - "Vanguard Real Estate ETF" → "reit"
    - "Treasury Bill" → "bond" 
    - type="cash" → "cash"
    """
```

**Implementation Strategy**:
- Extend existing provider data preservation logic
- Add keyword detection in security names
- Respect provider type classifications
- Cache results in existing database structure

### **Tier 2: FMP Industry Classification - INTELLIGENT**
**Priority**: Medium - Leverage existing FMP profile data
**Performance**: Fast (uses existing LFU cache via fetch_profile)
**Coverage**: Comprehensive for most securities

```python
def get_asset_class_from_fmp(ticker: str, profile: dict) -> Optional[str]:
    """
    Use FMP industry/sector data for asset class detection
    
    FMP Profile Intelligence:
    - industry: "Real Estate", "Fixed Income", "Commodities"
    - sector: "Real Estate", "Utilities"
    - isEtf + industry analysis for ETF classification
    
    Classification Rules:
    - industry contains "reit" or "real estate" → "reit"
    - industry contains "bond" or "treasury" → "bond"  
    - industry contains commodity keywords → "commodity"
    - sector = "Real Estate" → "reit"
    - Default → "equity"
    """
```

**Implementation Strategy**:
- Use existing `fetch_profile(ticker)` function (LFU cached)
- Add industry/sector keyword mapping
- Create classification rule engine
- Store results in existing database cache

### **Tier 3: AI Classification (GPT) - FALLBACK**
**Priority**: Lowest - Only when other methods fail
**Performance**: Slow (~2-3 seconds) but cached
**Coverage**: Universal fallback for edge cases

```python
def get_asset_class_from_ai(ticker: str) -> Optional[str]:
    """
    Use GPT for intelligent asset class detection
    
    Similar to existing sub-industry proxy generation:
    - Uses existing Claude integration
    - Respects gpt_enabled() configuration
    - Caches results in database
    - Handles rate limiting automatically
    
    Prompt Strategy:
    - Clear classification categories
    - Examples for each asset class
    - Single-word response format
    - Validation of response
    """
```

**Implementation Strategy**:
- Reuse existing GPT integration patterns from `factor_proxy_service.py`
- Use existing `gpt_enabled()` configuration
- Follow existing Claude rate limiting patterns
- Cache AI results in database for performance

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

```sql
-- Extend existing security_types table
ALTER TABLE security_types ADD COLUMN IF NOT EXISTS asset_class VARCHAR(20);
ALTER TABLE security_types ADD COLUMN IF NOT EXISTS asset_class_source VARCHAR(20); -- 'provider', 'fmp', 'ai'
ALTER TABLE security_types ADD COLUMN IF NOT EXISTS asset_class_updated TIMESTAMP;

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_security_types_asset_class ON security_types(asset_class);
```

## **📊 Asset Class Categories**

### **Complete Asset Class Taxonomy** (6 Categories)

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

6. **`mixed`** - Multi-asset funds, target-date funds, balanced funds
   - **Examples**: Target-date funds (VTTSX), balanced funds (VBIAX), lifecycle funds
   - **Risk Model**: Blended approach based on underlying asset allocation
   - **Provider Hints**: Security names with "target"/"balanced"/"lifecycle", FMP fund analysis

### **Classification Priority Matrix**

| Ticker Type | Tier 1 (Provider) | Tier 2 (FMP) | Tier 3 (AI) | Fallback |
|-------------|-------------------|---------------|--------------|----------|
| Individual Stocks | Limited | ✅ Industry/Sector | ✅ GPT | equity |
| ETFs | Security Name | ✅ Industry Analysis | ✅ GPT | equity |
| Mutual Funds | Security Name | ✅ Industry Analysis | ✅ GPT | equity |
| Cash/MMF | ✅ Provider Type | Limited | ✅ GPT | cash |
| Bonds | Security Name | ✅ Industry | ✅ GPT | bond |

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

## **📈 Performance Considerations**

### **Caching Strategy**
- **Tier 1**: Immediate (provider data already loaded)
- **Tier 2**: ~10ms (existing LFU cache via fetch_profile)
- **Tier 3**: ~2-3s first time, then cached (database + LFU)
- **Overall**: 95% of requests served from cache

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
    "cash": ["SGOV", "SHY"]  # Note: SHY could be bond or cash depending on context
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
