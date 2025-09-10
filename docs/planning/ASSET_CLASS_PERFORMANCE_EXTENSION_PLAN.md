# Asset Class Performance Extension Plan

## Executive Summary

This document outlines the implementation plan for adding **real performance data** to the asset allocation display. Currently, the frontend shows placeholder values (`+0.0%`, `neutral`) for asset class performance changes. This extension will calculate and display actual performance metrics for each asset class over selectable time periods.

## Current State Analysis

### ✅ **Existing Infrastructure**
1. **Asset Classification System**: 5-tier intelligent asset class classification fully operational
2. **Frontend Components**: AssetAllocationContainer and AssetAllocation components ready for real data
3. **API Integration**: Backend serves `asset_allocation` field with asset class breakdowns
4. **Market Data Infrastructure**: FMP API integration for historical price data via `data_loader.py`
5. **Caching System**: Multi-layer caching (memory, database, service-level)

### 🔄 **Current Limitations**
1. **Placeholder Performance Data**: Frontend shows hardcoded `+0.0%` and `neutral` change values
2. **No Time Series Calculation**: No system to calculate asset class performance over time periods
3. **Missing Performance Service**: No dedicated service for performance metric calculations

## Technical Architecture

### **Data Flow for Performance Calculation**
```
User Request → Frontend Time Period Selection → API Request → 
PortfolioService → AssetClassPerformanceService → FMP Historical Data → 
Asset Class Aggregation → Performance Calculation → Frontend Display
```

### **Core Components to Implement**

#### 1. **AssetClassPerformanceService** (NEW)
**File**: `/services/asset_class_performance_service.py`

**Responsibilities**:
- Calculate performance metrics for each asset class over time periods
- Aggregate individual security performance into asset class performance  
- Cache performance calculations for efficiency
- Support multiple time periods (1D, 1W, 1M, 3M, 6M, 1Y, YTD)

**Key Methods**:
```python
class AssetClassPerformanceService:
    def calculate_asset_class_performance(
        portfolio_data: PortfolioData, 
        time_period: str = "1M"
    ) -> Dict[str, AssetClassPerformance]
    
    def calculate_weighted_returns(
        asset_class_holdings: Dict[str, float],
        time_period: str
    ) -> float
    
    def get_performance_comparison(
        asset_classes: List[str],
        time_period: str  
    ) -> Dict[str, float]
```

#### 2. **Enhanced RiskAnalysisResult** (MODIFY)
**File**: `/core/result_objects.py`

**Changes to `_build_asset_allocation_breakdown()`**:
- Add performance calculation calls to AssetClassPerformanceService
- Include real `change` and `changeType` values in asset allocation response
- Support time period parameter for performance calculations

#### 3. **Frontend Time Period Selection** (NEW)
**File**: `/frontend/src/components/portfolio/AssetAllocation.tsx`

**Enhancements**:
- Add time period selector dropdown (1D, 1W, 1M, 3M, 6M, 1Y, YTD)
- Update API calls to include time period parameter
- Handle loading states during performance calculation
- Display performance period context in UI

#### 4. **Enhanced API Endpoints** (MODIFY)
**File**: `/app.py`

**Changes to portfolio analysis endpoints**:
- Add optional `performance_period` query parameter
- Pass performance period to PortfolioService for calculation
- Maintain backward compatibility (default to 1M)

### **Data Models**

#### **AssetClassPerformance** (NEW)
```python
@dataclass
class AssetClassPerformance:
    asset_class: str            # "equity", "bond", etc.
    period_return: float        # 0.023 (2.3%)
    period_volatility: float    # 0.157 (15.7%)
    period_sharpe: float        # 0.47
    start_date: datetime        
    end_date: datetime
    benchmark_return: float     # Optional market comparison
    relative_performance: float # vs benchmark
```

#### **Enhanced API Response** (MODIFY)
```json
{
  "asset_allocation": [
    {
      "category": "equity",
      "percentage": 45.2,
      "value": "$1,281,281",
      "change": "+2.3%",           // REAL DATA (not placeholder)
      "changeType": "positive",     // CALCULATED (not placeholder)
      "period": "1M",              // NEW: Time period context
      "volatility": "15.7%",       // NEW: Risk context
      "holdings": ["AAPL", "MSFT", "GOOGL"]
    }
  ]
}
```

## Implementation Plan

### **Phase 1: Core Performance Service** (Week 1)
1. **Create AssetClassPerformanceService**
   - Implement basic performance calculation logic
   - Add caching for repeated calculations
   - Support major time periods (1D, 1W, 1M, 3M, 6M, 1Y, YTD)

2. **Integrate with FMP Historical Data**
   - Extend `data_loader.py` for bulk historical price fetching
   - Add performance calculation utilities
   - Implement weighted return calculations for asset classes

3. **Unit Testing**
   - Test performance calculations with known benchmarks
   - Validate caching behavior
   - Test edge cases (weekends, holidays, missing data)

### **Phase 2: Backend Integration** (Week 2)
1. **Enhance RiskAnalysisResult**
   - Modify `_build_asset_allocation_breakdown()` to include real performance
   - Add performance service integration
   - Maintain backward compatibility

2. **Update API Endpoints**
   - Add `performance_period` parameter to portfolio analysis endpoints
   - Update API documentation
   - Add performance period validation

3. **Service Layer Integration**
   - Integrate AssetClassPerformanceService with PortfolioService
   - Add performance caching to service-level cache
   - Update cache invalidation logic

### **Phase 3: Frontend Enhancement** (Week 3)
1. **Time Period Selection UI**
   - Add time period dropdown to AssetAllocation component
   - Implement period selection state management
   - Add loading states for performance calculations

2. **Enhanced Data Display**
   - Remove placeholder performance values
   - Add period context display ("Last 1 Month Performance")
   - Enhance tooltips with volatility and Sharpe ratio information

3. **User Experience Improvements**
   - Add default period selection (1M)
   - Implement smooth transitions between periods
   - Add performance trend indicators (arrows, colors)

## Technical Specifications

### **Performance Calculation Logic**

#### **Asset Class Return Calculation**:
```python
def calculate_asset_class_return(holdings: Dict[str, float], period: str) -> float:
    """
    Calculate weighted average return for an asset class.
    
    Args:
        holdings: {ticker: weight} mapping for asset class
        period: "1D", "1W", "1M", "3M", "6M", "1Y", "YTD"
    
    Returns:
        float: Weighted return for the period
    """
    total_return = 0.0
    total_weight = sum(holdings.values())
    
    for ticker, weight in holdings.items():
        ticker_return = get_ticker_period_return(ticker, period)
        weighted_return = ticker_return * (weight / total_weight)
        total_return += weighted_return
    
    return total_return
```

#### **Change Type Classification**:
```python
def classify_performance_change(return_pct: float) -> str:
    """Classify performance as positive, negative, or neutral."""
    if return_pct > 0.5:  # > 0.5%
        return "positive"
    elif return_pct < -0.5:  # < -0.5%
        return "negative"
    else:
        return "neutral"
```

### **Caching Strategy**

#### **Performance Cache Hierarchy**:
1. **Memory Cache**: Recent calculations (TTL: 15 minutes)
2. **Database Cache**: Historical performance data (TTL: 24 hours)
3. **Service Cache**: Portfolio-specific performance results (TTL: 1 hour)

#### **Cache Keys**:
```python
# Performance calculation cache
performance_cache_key = f"asset_class_perf_{asset_class}_{period}_{end_date}"

# Portfolio performance cache  
portfolio_perf_key = f"portfolio_asset_perf_{portfolio_id}_{period}_{timestamp}"
```

### **API Changes**

#### **New Query Parameters**:
```
GET /api/portfolio-analysis?performance_period=1M
GET /api/analyze?performance_period=3M
```

#### **Enhanced Response Format**:
```json
{
  "asset_allocation": [...],
  "performance_metadata": {
    "period": "1M",
    "calculation_date": "2025-01-15T10:30:00Z",
    "data_quality": "complete",  // complete, partial, estimated
    "benchmark_context": {
      "market_return": "+1.8%",
      "market_period": "1M"
    }
  }
}
```

## Risk Mitigation

### **Data Quality Concerns**
- **Missing Price Data**: Implement fallback to longest available period
- **Market Closures**: Handle weekends and holidays gracefully  
- **Partial Data**: Provide data quality indicators in response

### **Performance Concerns**
- **Complex Calculations**: Implement aggressive caching at multiple levels
- **API Rate Limits**: Batch FMP API calls and respect rate limits
- **Memory Usage**: Use efficient data structures for historical data

### **User Experience Risks**
- **Slow Loading**: Show loading indicators and cached data while calculating
- **Confusing Metrics**: Provide clear period context and tooltips
- **Data Freshness**: Display calculation timestamps

## Success Metrics

### **Technical Metrics**
- Performance calculation time: < 2 seconds for complex portfolios
- Cache hit rate: > 80% for repeated calculations  
- API response time: < 500ms for cached results

### **User Experience Metrics**
- Real performance data displayed instead of placeholders
- Smooth time period transitions (< 1 second)
- Clear performance context and data quality indicators

### **Business Metrics**
- Accurate asset class performance tracking
- Enhanced portfolio analysis capabilities
- Reduced user confusion from placeholder data

## Future Enhancements

### **Advanced Performance Features**
- **Risk-Adjusted Returns**: Sharpe ratio, Sortino ratio for each asset class
- **Benchmark Comparison**: Asset class vs. market benchmark performance
- **Performance Attribution**: Factor vs. security selection contribution

### **Interactive Features**
- **Performance Charts**: Historical performance visualization
- **Drill-Down Analysis**: Asset class → individual security performance
- **Custom Time Ranges**: User-defined performance periods

### **Analytics Integration**
- **Performance Alerts**: Notifications for significant asset class moves
- **Trend Analysis**: Performance momentum and trend indicators
- **Correlation Analysis**: Asset class performance correlation matrix

---

## Conclusion

This extension builds on the solid foundation of the existing asset classification system to provide meaningful performance insights. The modular design ensures minimal risk to existing functionality while adding significant value through real performance data display.

The implementation leverages existing infrastructure (FMP API, caching systems, frontend components) and follows established patterns in the codebase. The phased approach allows for iterative development and testing while maintaining system stability.

**Total Implementation Time**: 3 weeks  
**Implementation Complexity**: Medium  
**Business Value**: High  
**Technical Risk**: Low