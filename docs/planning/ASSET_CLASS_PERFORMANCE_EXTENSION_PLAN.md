# Asset Class Performance Extension Plan

## Executive Summary

This document outlines the implementation plan for adding **real performance data** to the asset allocation display. Currently, the frontend shows placeholder values (`+0.0%`, `neutral`) for asset class performance changes. This extension will calculate and display actual performance metrics for each asset class over selectable time periods.

## Current State Analysis

### ✅ **Existing Infrastructure Available for Leverage**

#### **1. Centralized Constants System** (`core/constants.py`)
- ✅ `VALID_ASSET_CLASSES` - Canonical asset class definitions
- ✅ `ASSET_CLASS_DISPLAY_NAMES` - Human-readable names for UI
- ✅ `ASSET_CLASS_COLORS` - Consistent color scheme for charts
- ✅ Helper functions: `get_asset_class_display_name()`, `get_asset_class_color()`
- ✅ Validation functions: `is_valid_asset_class()`

#### **2. Market Data Infrastructure** (`data_loader.py`)
- ✅ `fetch_monthly_close()` - FMP API integration with multi-layer caching
- ✅ `cache_read()` - Generic disk+RAM caching framework
- ✅ LRU caching with configurable `DATA_LOADER_LRU_SIZE`
- ✅ Parquet-based disk cache with compression
- ✅ Rate limiting and error handling for FMP API
- ✅ Existing `/historical-price-eod/full` endpoint integration

#### **3. Service Architecture Patterns**
- ✅ `ServiceCacheMixin` - Standardized TTL+LRU caching with thread safety
- ✅ Service decorators: `@log_performance`, `@log_cache_operations`, `@log_error_handling`
- ✅ Standard service lifecycle methods: `clear_cache()`, `get_cache_stats()`, `health_check()`
  (Note: No new service will be added in this phase; logic lives in PortfolioService.)

#### **4. Asset Classification System**
- ✅ 5-tier intelligent asset class classification fully operational
- ✅ SecurityTypeService with asset class grouping logic
- ✅ Pre-calculated asset classes in `analysis_metadata`

#### **5. Frontend Components**
- ✅ AssetAllocationContainer and AssetAllocation components ready for real data
- ✅ API integration via `useRiskAnalysis` hook
- ✅ Color mapping and display name formatting already in place

### 🔄 **Current Limitations**
1. **Placeholder Performance Data**: Frontend shows hardcoded `+0.0%` and `neutral` change values
2. **No Time Series Calculation**: No system to calculate asset class performance over time periods
3. **Missing Performance Service**: No dedicated service leveraging existing infrastructure patterns

## Technical Architecture

### **Data Flow for Performance Calculation** (Following Clean Architecture)
```
User Request → Frontend Time Period Selection → API POST (with performance_period) →
PortfolioService.analyze_portfolio() → core/asset_class_performance.py → data_loader.fetch_monthly_close() →
Aggregate by Asset Class (monthly-only) → Add to analysis_metadata['asset_class_performance'] →
RiskAnalysisResult formatting (pure display) → Frontend AssetAllocation card
```

**Architecture Layers (this phase)**:
1. **Core Layer**: Pure business logic (`core/asset_class_performance.py`)
2. **Service Layer**: PortfolioService orchestrates performance calc (no new service)
3. **API Layer**: HTTP endpoints with parameter validation (`app.py`)
4. **Adapter Layer**: RiskAnalysisAdapter surfaces `asset_allocation` for UI
5. **Hooks Layer**: `useRiskAnalysis({ performancePeriod })` propagates period param
6. **Frontend Layer**: Container wraps the AssetAllocation display component

### **Core Components to Implement**

#### 1. **Core Asset Class Performance Module** (NEW)
**File**: `/core/asset_class_performance.py`

**Follows Existing Core Architecture**:
- ✅ Pure business logic (no caching, no logging, no service infrastructure)
- ✅ Follows pattern of existing `core/performance_analysis.py`
- ✅ Uses `data_loader.fetch_monthly_close()` for price data
- ✅ Uses existing `core.constants` for validation
- ✅ Leverages existing 5-tier asset classification results

**Core Functions**:
```python
# core/asset_class_performance.py
from typing import Dict, List
from data_loader import fetch_monthly_close
from core.constants import (
    VALID_ASSET_CLASSES,
    is_valid_asset_class,
    get_asset_class_color,
    get_asset_class_display_name,
)

def group_holdings_by_asset_class(
    portfolio_holdings: Dict[str, float],
    asset_class_mapping: Dict[str, str]
) -> Dict[str, Dict[str, float]]:
    """
    Group portfolio holdings by asset class using existing 5-tier classification.
    
    Args:
        portfolio_holdings: {ticker: weight}
        asset_class_mapping: {ticker: asset_class} from existing classification
    
    Returns:
        Dict[str, Dict[str, float]]: {asset_class: {ticker: weight}}
    """
    asset_class_holdings = {}
    
    for ticker, weight in portfolio_holdings.items():
        asset_class = asset_class_mapping.get(ticker, 'unknown')
        
        if asset_class not in asset_class_holdings:
            asset_class_holdings[asset_class] = {}
        
        asset_class_holdings[asset_class][ticker] = weight
    
    return asset_class_holdings

def calculate_asset_class_returns(
    asset_class_holdings: Dict[str, Dict[str, float]],
    time_period: str  # Supported: "1M", "3M", "6M", "1Y", "YTD"
) -> Dict[str, float]:
    """
    Calculate asset class performance using existing price data infrastructure.
    
    Args:
        asset_class_holdings: {asset_class: {ticker: weight}}
        time_period: "1M", "3M", "6M", "1Y", "YTD" (monthly granularity)
    
    Returns:
        Dict[str, float]: {asset_class: period_return}
    """
    asset_class_returns = {}
    
    for asset_class, holdings in asset_class_holdings.items():
        if not holdings:
            continue
            
        weighted_return = calculate_weighted_portfolio_return(holdings, time_period)
        asset_class_returns[asset_class] = weighted_return
    
    return asset_class_returns

def calculate_weighted_portfolio_return(
    holdings: Dict[str, float], 
    time_period: str
) -> float:
    """
    Calculate weighted return for a group of holdings.
    """
    total_return = 0.0
    total_weight = sum(holdings.values())
    
    if total_weight == 0:
        return 0.0
    
    start_date = get_period_start_date(time_period)
    for ticker, weight in holdings.items():
        # Use existing cached monthly price fetching; skip tickers with insufficient data
        price_series = fetch_monthly_close(ticker, start_date=start_date)
        if len(price_series) >= 2:
            period_return = (price_series.iloc[-1] / price_series.iloc[0]) - 1.0
            weighted_return = period_return * (weight / total_weight)
            total_return += weighted_return
    
    return total_return

def classify_performance_change(return_pct: float) -> str:
    """Classify return as positive, negative, or neutral."""
    if return_pct > 0.005:  # > 0.5%
        return "positive"
    elif return_pct < -0.005:  # < -0.5%
        return "negative"
    else:
        return "neutral"

def get_period_start_date(time_period: str) -> str:
    """Convert time period to start date for data fetching."""
    from datetime import datetime, timedelta
    
    now = datetime.now()
    
    if time_period == "1M":
        start_date = now - timedelta(days=30)
    elif time_period == "3M":
        start_date = now - timedelta(days=90)
    elif time_period == "6M":
        start_date = now - timedelta(days=180)
    elif time_period == "1Y":
        start_date = now - timedelta(days=365)
    elif time_period == "YTD":
        start_date = datetime(now.year, 1, 1)
    else:
        start_date = now - timedelta(days=30)  # Default to 1M
    
    return start_date.strftime("%Y-%m-%d")
```

#### 3. Future: AssetClassPerformanceService / FactorIntelligenceService (Not in this phase)
If/when we expand to cross-portfolio and factor-level analytics, introduce a dedicated service
(e.g., FactorIntelligenceService) and have PortfolioService delegate to it. For now, keep
all asset-class performance logic inside PortfolioService using the core functions.

#### 4. **Enhanced PortfolioService** (MODIFY)
**File**: `/services/portfolio_service.py`

**Orchestrates Performance Calculation**:
- ✅ Calls core performance analysis during portfolio analysis
- ✅ Adds performance data to `analysis_metadata` (existing pattern)
- ✅ Maintains separation of concerns (core logic vs service infrastructure)
- ✅ Uses existing service dependency injection patterns

**Integration Pattern**:
```python
# In PortfolioService.analyze_portfolio(..., performance_period: str = "1M")
# After result (RiskAnalysisResult) has analysis_metadata['asset_classes']
from services.security_type_service import SecurityTypeService
from core.asset_class_performance import (
    group_holdings_by_asset_class,
    calculate_asset_class_returns,
)

class_map = result.analysis_metadata.get('asset_classes', {}) or 
            SecurityTypeService.get_asset_classes(portfolio_data.get_tickers(), portfolio_data)
grouped = group_holdings_by_asset_class(portfolio_data.portfolio_input, class_map)
performance = calculate_asset_class_returns(grouped, performance_period)

result.analysis_metadata['asset_class_performance'] = {
    'performance_data': performance,
    'period': performance_period,
    'calculation_date': datetime.now(UTC).isoformat(),
    'data_quality': 'complete'
}
```

#### 5. **Enhanced RiskAnalysisResult** (MODIFY)
**File**: `/core/result_objects.py`

**Pure Formatting Logic** (No Business Logic):
- ✅ Uses pre-calculated performance data from `analysis_metadata`
- ✅ Maintains existing "pure formatting" architecture
- ✅ No service calls or business logic in result objects
- ✅ Uses existing centralized constants for display formatting

**Changes to `_build_asset_allocation_breakdown()`**:
```python
def _build_asset_allocation_breakdown(self) -> List[Dict[str, Any]]:
    """
    Enhanced to format pre-calculated performance data.
    Maintains pure formatting logic - no business calculations.
    """
    # Use existing asset class grouping logic
    asset_classes = getattr(self, 'analysis_metadata', {}).get('asset_classes', {})
    
    # Get pre-calculated performance data from analysis_metadata
    performance_metadata = self.analysis_metadata.get('asset_class_performance', {})
    performance_data = performance_metadata.get('performance_data', {})
    
    for asset_class, holdings in asset_groups.items():
        # Existing logic for percentage and value calculations...
        
        # Use pre-calculated performance data (no business logic)
        if performance_data and asset_class in performance_data:
            period_return = performance_data[asset_class]
            change = f"{period_return:+.1%}"
            change_type = classify_performance_change(period_return)
        else:
            # Fallback to existing placeholder values
            change = "+0.0%"
            change_type = "neutral"
        
        # Use centralized constants for color & display name
        color = get_asset_class_color(asset_class)
        label = get_asset_class_display_name(asset_class)
```

#### 6. **Frontend Time Period Selection** (NEW)
**File**: `/frontend/src/components/portfolio/AssetAllocation.tsx`

**Leverages Existing Infrastructure**:
- ✅ Extends existing AssetAllocation component structure
- ✅ Uses existing `useRiskAnalysis` hook for API integration
- ✅ Maintains existing loading/error states pattern
- ✅ Preserves existing color mapping and display name formatting

**Enhancements**:
```jsx
const AssetAllocation = ({ allocations }) => {
  const [performancePeriod, setPerformancePeriod] = useState("1M");
  
  // Leverage existing hook pattern with new parameter
  const { data, refetch } = useRiskAnalysis({ 
    performance_period: performancePeriod 
  });
  
  // Use existing loading/error state handling...
  
  return (
    <div>
      {/* NEW: Time period selector using existing UI patterns */}
      <select 
        value={performancePeriod} 
        onChange={(e) => setPerformancePeriod(e.target.value)}
        className="existing-dropdown-styles"
      >
        <option value="1M">1 Month</option>
        <option value="3M">3 Months</option>
        <option value="6M">6 Months</option>
        <option value="1Y">1 Year</option>
        <option value="YTD">YTD</option>
      </select>
      
      {/* Existing allocation display logic with real performance data */}
      {allocations.map(allocation => (
        // Uses existing color mapping and display names
        // Now shows real change values instead of placeholders
      ))}
    </div>
  );
};
```

#### 7. **Enhanced API Endpoints** (MODIFY)
**File**: `/app.py`

**Leverages Existing Infrastructure**:
- ✅ Extends existing portfolio analysis endpoints
- ✅ Uses existing service dependency injection patterns
- ✅ Maintains backward compatibility with existing API contracts
- ✅ Follows existing parameter validation patterns

**Changes to portfolio analysis endpoints**:
```python
class PortfolioAnalysisRequest(BaseModel):
    portfolio_name: str = "CURRENT_PORTFOLIO"
    performance_period: str | None = "1M"

@app.post("/api/portfolio-analysis")
async def portfolio_analysis(analysis_request: PortfolioAnalysisRequest, ...):
    period = (analysis_request.performance_period or "1M").upper()
    if period not in {"1M", "3M", "6M", "1Y", "YTD"}:
        period = "1M"
    result = portfolio_service.analyze_portfolio(portfolio_data, performance_period=period)
    # ... existing response serialization
```

<!-- No new service registration in this phase; PortfolioService performs the calculation. -->

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

#### **Enhanced API Response** (Leveraging Existing Structure)
```json
{
  "asset_allocation": [
    {
      "category": "equity",                    // Uses existing asset class from analysis_metadata
      "percentage": 45.2,                     // Existing calculation logic
      "value": "$1,281,281",                  // Existing formatting
      "change": "+2.3%",                      // NEW: Real data (not placeholder)
      "changeType": "positive",               // NEW: Calculated (not placeholder)
      "color": "bg-blue-500",                 // Uses core.constants.get_asset_class_color()
      "holdings": ["AAPL", "MSFT", "GOOGL"]  // Existing holdings list
    }
  ],
  "performance_metadata": {                   // NEW: Performance context
    "period": "1M",
    "calculation_date": "2025-01-15T10:30:00Z",
    "data_quality": "complete"               // Based on data availability
  }
}
```

## Implementation Plan

### **Phase 1: Core Module + PortfolioService Integration** (Week 1)
1. **Create core/asset_class_performance.py**
   - ✅ Implement grouping and monthly return aggregation functions
   - ✅ Support periods: {"1M","3M","6M","1Y","YTD"}
   - ✅ Unit-test pure functions in isolation

2. **Integrate in PortfolioService.analyze_portfolio**
   - ✅ Build class map via SecurityTypeService (already cached)
   - ✅ Group holdings and calculate performance via core functions
   - ✅ Attach results to analysis_metadata['asset_class_performance']

3. **Leverage Existing FMP Integration**
   - ✅ Use `data_loader.fetch_monthly_close()` (already has multi-layer caching)
   - ✅ No changes needed to FMP API integration (already optimized)
   - ✅ Leverage existing rate limiting and error handling
   - ✅ Use existing parquet-based disk cache for performance

4. **Unit Testing** (Following Existing Patterns)
   - ✅ Use existing fixtures; test PortfolioService integration in a focused path
   - ✅ Validate analysis_metadata payload contents and shape
   - ✅ Leverage existing error handling patterns

### **Phase 2: Backend Integration** (Week 2) - Using Existing Patterns
1. **Enhance RiskAnalysisResult** (Minimal Changes)
   - ✅ Extend existing `_build_asset_allocation_breakdown()` method
   - ✅ Use existing asset class data from `analysis_metadata`
   - ✅ Leverage `core.constants.get_asset_class_color()` for color mapping
   - ✅ Maintain existing API response structure

2. **Update API Endpoints** (Following Existing Patterns)
   - ✅ Add `performance_period` to POST request models (`/api/analyze`, `/api/portfolio-analysis`)
   - ✅ **Request Validation**: Explicitly validate `performance_period` against `{"1M","3M","6M","1Y","YTD"}` in both endpoints; default to "1M"
   - ✅ **Data Quality Rule**: Define "complete" as effective coverage ≥ 90% of total portfolio weight included in period computation; otherwise "partial"
   - ✅ **Backend Logging**: Add summary line logging per-class returns and data_quality after computation
   - ✅ Maintain backward compatibility with default values
   - ✅ Follow existing dependency injection patterns for services

3. **Service Layer Integration**
   - ✅ No new service this phase; keep logic in PortfolioService
   - ✅ Maintain PortfolioService cache key behavior
   - ✅ Reuse SecurityTypeService caches; avoid redundant layers

### **Phase 3: Frontend Enhancement** (Week 3) - Leveraging Existing UI Patterns
1. **Time Period Selection UI** (Using Existing Components)
   - ✅ Extend existing AssetAllocation component structure
   - ✅ Use existing dropdown styling and state management patterns
   - ✅ Leverage `useRiskAnalysis({ performancePeriod })` with new parameter
   - ✅ Follow existing loading state patterns from other components

2. **Enhanced Data Display** (Minimal Changes)
   - ✅ Remove placeholder values (simple deletion)
   - ✅ Use existing color mapping from `core.constants`
   - ✅ Leverage existing display name formatting
   - ✅ Maintain existing tooltip and UI styling patterns

3. **User Experience Improvements** (Following Existing Patterns)
   - ✅ Use existing default value patterns
   - ✅ Leverage existing React Query caching for smooth transitions
   - ✅ Follow existing loading/error state management
   - ✅ Use existing frontend caching and state management

### **Phase 4: Frontend Integration** (Week 3) - Specific Implementation

#### **1. Manager Chain Enhancement** (MODIFY)
**Frontend Service Layer Updates**

**A. PortfolioManager** (`/frontend/src/chassis/managers/PortfolioManager.ts`):
```typescript
// CURRENT:
public async analyzePortfolioRisk(portfolioId: string): Promise<{ analysis: any; error: string | null }>

// ENHANCED:
public async analyzePortfolioRisk(
  portfolioId: string, 
  options?: { performancePeriod?: string }
): Promise<{ analysis: any; error: string | null }> {
  try {
    const portfolio = usePortfolioStore.getState().byId[portfolioId]?.portfolio;
    if (!portfolio) throw new Error('Portfolio not found');

    // Forward performance period through service chain
    const requestBody = {
      portfolio_name: portfolio.portfolio_name || 'CURRENT_PORTFOLIO',
      ...(options?.performancePeriod && { performance_period: options.performancePeriod })
    };

    const result = await this.cacheService.post('/api/analyze', requestBody);
    
    return { analysis: result, error: null };
  } catch (error) {
    return { analysis: null, error: (error as Error).message };
  }
}
```

**B. Service Chain Updates** (Following Manager → Cache → API pattern):
- **RiskAnalysisService**: Update `analyzePortfolio(portfolioId, { performancePeriod }?)` signature
- **APIService**: Forward `{ performancePeriod }` to RiskAnalysisService
- **PortfolioCacheService**: Accept and forward `{ performancePeriod }` in `getRiskAnalysis(...)`
- **All services**: Maintain existing error handling and pass-through patterns

#### **2. useRiskAnalysis Hook Enhancement** (MODIFY)
**File**: `/frontend/src/features/analysis/hooks/useRiskAnalysis.ts`

**Current Signature**:
```typescript
export const useRiskAnalysis = () => {
```

**Enhanced Signature & Implementation**:
```typescript
interface UseRiskAnalysisOptions {
  performancePeriod?: string;
}

/**
 * useRiskAnalysis Hook - Enhanced with performance period support
 * 
 * USAGE: useRiskAnalysis({ performancePeriod: "1M" })
 * CACHING: Query key includes performancePeriod for proper cache isolation
 * MANAGER: Passes { performancePeriod } to manager.analyzePortfolioRisk
 */
export const useRiskAnalysis = (options?: UseRiskAnalysisOptions) => {
  // DEPENDENCIES: Core service and state providers (EXISTING)
  const { manager, unifiedAdapterCache } = useSessionServices();
  const currentPortfolio = useCurrentPortfolio();
  
  // EXTRACT: Performance period with default
  const performancePeriod = options?.performancePeriod || '1M';
  
  // ADAPTER REGISTRY: Portfolio-scoped RiskAnalysisAdapter (EXISTING)
  const factorAdapter = useMemo(
    () => AdapterRegistry.getAdapter('riskAnalysis', [currentPortfolio?.id || 'default'], 
      (cache) => new RiskAnalysisAdapter(cache, currentPortfolio?.id || undefined), unifiedAdapterCache),
    [currentPortfolio?.id, unifiedAdapterCache]
  );
  
  // TANSTACK QUERY: Enhanced with performance period in query key
  const {
    data,
    isLoading,
    error,
    refetch
  } = useQuery({
    queryKey: riskAnalysisKey(currentPortfolio?.id, performancePeriod), // ENHANCED: Include period
    queryFn: async (): Promise<any> => {
      if (!currentPortfolio?.id || !manager) {
        throw new Error('Portfolio or manager not available');
      }

      // ENHANCED: Pass performance period to manager
      const result = await manager.analyzePortfolioRisk(currentPortfolio.id, {
        performance_period: performancePeriod
      });
      
      if (result.error) {
        throw new Error(result.error);
      }
      
      return factorAdapter.transform(result.analysis);
    },
    enabled: !!currentPortfolio && !!manager,
    staleTime: HOOK_QUERY_CONFIG.useRiskAnalysis.staleTime,
    // Existing retry logic...
  });

  // EXISTING: Return structure with enhanced query key
  return {
    data: data || null,
    isLoading,
    error,
    refetch,
    hasData: !!data,
    hasPortfolio: !!currentPortfolio,
    currentPortfolio
  };
};
```

#### **3. Query Key Enhancement** (MODIFY)
**File**: `/frontend/src/queryKeys.ts`

**Enhanced riskAnalysisKey function**:
```typescript
// BEFORE:
export const riskAnalysisKey = (portfolioId?: string) => ['riskAnalysis', portfolioId].filter(Boolean);

// AFTER:
export const riskAnalysisKey = (portfolioId?: string, performancePeriod?: string) => 
  ['riskAnalysis', portfolioId, performancePeriod].filter(Boolean);
```

#### **4. UI Container + Component Enhancement** (MODIFY)

**A. AssetAllocation Component** (`/frontend/src/components/portfolio/AssetAllocation.tsx`):
```typescript
interface AssetAllocationProps {
  allocations?: AllocationItem[]; // NEW: Accept props instead of always using mock
  // ... existing props
}

const AssetAllocation: React.FC<AssetAllocationProps> = ({ 
  allocations, 
  ...props 
}) => {
  // Use props first, fallback to mock only when props are absent (for stories)
  const displayAllocations = allocations || getMockAllocations();
  
  return (
    <div>
      {displayAllocations.map(allocation => (
        // Existing allocation rendering logic
      ))}
    </div>
  );
};
```

**B. AssetAllocationContainer** (`/frontend/src/components/dashboard/views/modern/AssetAllocationContainer.tsx`):

**Enhanced Implementation with Real Data Integration**:
```typescript
// EXISTING IMPORTS + NEW STATE IMPORT
import React, { useState, useEffect } from 'react';
import { useRiskAnalysis } from '../../../../features/analysis/hooks/useRiskAnalysis';
// ... existing imports

const AssetAllocationContainer: React.FC<AssetAllocationContainerProps> = ({ 
  className,
  ...props 
}) => {
  // NEW: Performance period state management
  const [performancePeriod, setPerformancePeriod] = useState<string>("1M");
  
  // EXISTING: Event bus and session services
  const { eventBus } = useSessionServices();
  
  // ENHANCED: Hook call with performance period
  const { 
    data, 
    isLoading, 
    error, 
    hasData,
    hasPortfolio,
    refetch,
    currentPortfolio
  } = useRiskAnalysis({ performancePeriod }); // ENHANCED: Pass period
  
  // EXISTING: Event-driven updates (unchanged)
  useEffect(() => {
    // Existing event handling logic...
  }, [eventBus, currentPortfolio?.id, refetch]);

  // EXISTING: Lifecycle logging (unchanged)
  useEffect(() => {
    frontendLogger.user.action('viewRendered', 'AssetAllocationContainer', {
      hasData: !!data,
      isLoading,
      hasError: !!error,
      hasAssetAllocation: !!(data?.asset_allocation && data.asset_allocation.length > 0)
    });
  }, [data, isLoading, error]);

  // EXISTING: Loading, error, no portfolio states (unchanged)
  if (isLoading) { /* existing loading UI */ }
  if (error) { /* existing error UI */ }  
  if (!hasPortfolio) { /* existing no portfolio UI */ }

  // ENHANCED: Data transformation with performance period context
  const transformAssetAllocation = (backendData: any[]) => {
    if (!backendData || !Array.isArray(backendData)) {
      return [];
    }

    return backendData.map(item => ({
      category: formatAssetClassName(item.category || 'Unknown'),
      percentage: item.percentage || 0,
      value: item.value || '$0',
      
      // ENHANCED: Real performance data (no longer placeholders)
      change: item.change || '+0.0%',
      changeType: item.changeType || 'neutral',
      
      color: getAssetClassColor(item.category || 'unknown'),
      holdings: item.holdings || []
    }));
  };

  // EXISTING: Helper functions (unchanged)
  const formatAssetClassName = (assetClass: string): string => { /* existing */ };
  const getAssetClassColor = (assetClass: string): string => { /* existing */ };

  // ENHANCED: Asset allocation data extraction
  const assetAllocationData = data?.asset_allocation || [];
  const transformedAllocations = transformAssetAllocation(assetAllocationData);

  // EXISTING: No data state (unchanged)
  if (!hasData || transformedAllocations.length === 0) {
    /* existing no data UI */
  }

  // ENHANCED: Render with period selector
  return (
    <DashboardErrorBoundary>
      <div className={className} {...props}>
        {/* NEW: Time period selector */}
        <div className="mb-4 flex justify-between items-center">
          <h3 className="text-lg font-semibold">Asset Allocation</h3>
          <select 
            value={performancePeriod} 
            onChange={(e) => setPerformancePeriod(e.target.value)}
            className="px-3 py-1 border border-gray-300 rounded text-sm"
          >
            <option value="1M">1 Month</option>
            <option value="3M">3 Months</option>
            <option value="6M">6 Months</option>
            <option value="1Y">1 Year</option>
            <option value="YTD">YTD</option>
          </select>
        </div>
        
        {/* EXISTING: Asset allocation display */}
        <AssetAllocation allocations={transformedAllocations} />
        
        {/* EXISTING: Development indicator (enhanced) */}
        {process.env.NODE_ENV === 'development' && (
          <div className="fixed bottom-4 left-4 bg-blue-100 text-blue-800 px-3 py-1 rounded text-xs">
            Asset Allocation: {hasData && assetAllocationData.length > 0 ? 'Real Data' : 'Mock Data'} 
            | Period: {performancePeriod} | Source: useRiskAnalysis
          </div>
        )}
      </div>
    </DashboardErrorBoundary>
  );
};
```

#### **5. RiskAnalysisAdapter Enhancement** (MODIFY)
**File**: `/frontend/src/adapters/RiskAnalysisAdapter.ts`

**Current Implementation**: ✅ **Already supports asset_allocation**
- Lines 181-191: Interface already includes `asset_allocation` field
- Line 501: Adapter already passes through `asset_allocation` data

**Required Enhancements**:
```typescript
// A. Add resilient getter for nested response shapes
private extractAssetAllocation(data: any): any[] {
  // Handle multiple response structures: top-level, analysis, risk_results
  return data?.asset_allocation || 
         data?.analysis?.asset_allocation || 
         data?.risk_results?.asset_allocation || 
         [];
}

// B. Add camelCase alias in transform output
return {
  // ... existing fields
  asset_allocation: this.extractAssetAllocation(factorData),
  assetAllocation: this.extractAssetAllocation(factorData), // camelCase alias
  // ... rest of transform
};
```

**Adapter Guards**: Keep existing resilient guards until generated types are updated

#### **6. Types & Generated Interfaces** (UPDATE)
**Implementation Notes**:
- ✅ **Performance Period Validation**: Add validation in manager to ensure period is in `["1M", "3M", "6M", "1Y", "YTD"]`
- ✅ **Generated Types**: Update TS interfaces to include:
  - `asset_allocation` in API response types
  - Optional `analysis_metadata.asset_class_performance` structure
- ✅ **Adapter Resilience**: Keep adapter guards until generated types are refreshed
- ✅ **Query Key Typing**: Update query key type to include optional `performancePeriod`

**ModernDashboard Integration**:
- ✅ **Replace Mock Usage**: Explicitly replace `<AssetAllocation />` mock component with `<AssetAllocationContainer />` in ModernDashboard
- ✅ **Container Routing**: Ensure AssetAllocationContainer is properly exported from modern views index

#### **7. Testing Strategy**
1. **Manager Tests**: Test `analyzePortfolioRisk` with performance period parameter
2. **Hook Tests**: Test query key changes and cache behavior across periods  
3. **Container Tests**: Test period selection triggers refetch
4. **Integration Tests**: Test end-to-end flow from period selection to display

#### **8. Observability & Debugging**
```typescript
// In manager method
frontendLogger.logComponent('PortfolioManager', 'Analyzing portfolio with performance period', {
  portfolioId, 
  performance_period: options?.performance_period
});

// In hook
frontendLogger.logComponent('useRiskAnalysis', 'Query with performance period', {
  performancePeriod,
  queryKey: riskAnalysisKey(currentPortfolio?.id, performancePeriod)
});

// In adapter (existing logging enhanced)
log.logAdapter('RiskAnalysisAdapter', 'Transform completed with asset allocation', {
  hasAssetAllocation: !!(data?.asset_allocation?.length),
  assetAllocationCount: data?.asset_allocation?.length || 0
});
```

## Technical Specifications

### **Performance Calculation Logic**

#### **Asset Class Return Calculation** (Leveraging Existing Infrastructure):
```python
def calculate_asset_class_return(holdings: Dict[str, float], period: str) -> float:
    """
    Calculate weighted average return using existing data_loader infrastructure.
    
    Leverages:
    - data_loader.fetch_monthly_close() for price data with caching
    - Existing FMP API integration and rate limiting
    - Parquet-based disk cache for performance
    """
    from data_loader import fetch_monthly_close  # Use existing infrastructure
    
    total_return = 0.0
    total_weight = sum(holdings.values())
    
    for ticker, weight in holdings.items():
        # Use existing cached price fetching
        price_series = fetch_monthly_close(ticker, start_date=period_start, end_date=period_end)
        
        if len(price_series) >= 2:
            period_return = (price_series.iloc[-1] / price_series.iloc[0]) - 1.0
            weighted_return = period_return * (weight / total_weight)
            total_return += weighted_return
    
    return total_return
```

#### **Change Type Classification** (Using Existing Patterns):
```python
def classify_performance_change(return_pct: float) -> str:
    """
    Classify performance using consistent thresholds.
    Follows existing frontend changeType patterns.
    """
    if return_pct > 0.005:  # > 0.5%
        return "positive"
    elif return_pct < -0.005:  # < -0.5%
        return "negative"
    else:
        return "neutral"
```

### **Caching Strategy** (Leveraging Existing Infrastructure)

#### **Performance Cache Hierarchy** (Using Existing Patterns):
1. **ServiceCacheMixin TTL Cache**: Service-level caching (TTL from `utils.config.SERVICE_CACHE_TTL`)
2. **data_loader LRU Cache**: RAM cache for price data (`@lru_cache` with `DATA_LOADER_LRU_SIZE`)
3. **data_loader Disk Cache**: Parquet-based disk cache with compression (`cache_read()`)
4. **Service Manager Cache**: Integration with existing service cache lifecycle

#### **Cache Keys** (Following Existing Patterns):
```python
# Use existing ServiceCacheMixin patterns
class AssetClassPerformanceService(ServiceCacheMixin):
    def calculate_asset_class_performance(self, portfolio_data, time_period):
        # Follow existing cache key patterns from other services
        cache_key = f"asset_class_perf_{portfolio_data.get_cache_key()}_{time_period}"
        
        with self._lock:  # Use existing thread-safe caching from ServiceCacheMixin
            if self.cache_results and cache_key in self._cache:
                return self._cache[cache_key]
        
        # Use existing data_loader.fetch_monthly_close() which has its own caching
        # No need for additional performance cache layers
```

### **API Changes**

#### **New Body Parameters (POST)**:
```
POST /api/portfolio-analysis
{
  "portfolio_name": "CURRENT_PORTFOLIO",
  "performance_period": "1M"  // optional (defaults to 1M)
}

POST /api/analyze
{
  "portfolio_name": "CURRENT_PORTFOLIO",
  "performance_period": "3M"  // optional
}
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

This revised extension plan **maximally leverages existing infrastructure** to provide meaningful performance insights with minimal new code. By building on established patterns and centralized constants, this approach significantly reduces implementation complexity and risk.

### **Infrastructure Leverage Summary**:
- ✅ **ServiceCacheMixin**: Standardized caching without custom cache implementation
- ✅ **data_loader.fetch_monthly_close()**: Existing FMP integration with multi-layer caching
- ✅ **core.constants**: Centralized asset class definitions, colors, and validation
- ✅ **Existing Service Patterns**: Standard decorators, lifecycle methods, and registration
- ✅ **Frontend Infrastructure**: Existing hooks, state management, and UI patterns
- ✅ **API Patterns**: Existing parameter validation and dependency injection

### **Benefits of Leveraging Existing Infrastructure**:
1. **Reduced Code Duplication**: Uses centralized constants instead of hardcoded values
2. **Consistent Patterns**: Follows established service and component architectures  
3. **Proven Reliability**: Builds on tested caching and data loading infrastructure
4. **Faster Implementation**: Less custom code means faster development and testing
5. **Lower Maintenance**: Uses shared infrastructure that's already maintained

### **Revised Metrics**:
- **Total Implementation Time**: **2 weeks** (reduced from 3 weeks)
- **Implementation Complexity**: **Low** (reduced from Medium)  
- **Business Value**: **High** (unchanged)
- **Technical Risk**: **Very Low** (reduced from Low)
- **Code Reuse**: **>80%** (leverages existing infrastructure extensively)

## Acceptance Criteria

### **Backend Validation** ✅
- [ ] `/api/analyze` responds with `asset_allocation` containing real `change`/`changeType` values (not placeholders)
- [ ] `analysis_metadata.asset_class_performance` includes `period`, `calculation_date`, `data_quality`
- [ ] Request validation: `performance_period` validated against `{"1M","3M","6M","1Y","YTD"}` with "1M" default
- [ ] Data quality: "complete" when ≥90% portfolio weight included; "partial" otherwise
- [ ] Backend logging: Summary line with per-class returns and data_quality after computation

### **Frontend Integration** ✅
- [ ] **RiskAnalysisAdapter**: Exposes `assetAllocation` camelCase alias; handles nested response shapes
- [ ] **useRiskAnalysis Hook**: Accepts `{ performancePeriod }` argument; includes period in query key
- [ ] **Manager Chain**: All services forward `performancePeriod` through service chain to API
- [ ] **AssetAllocationContainer**: 
  - Pulls from `useRiskAnalysis({ performancePeriod })`
  - Manages local `performancePeriod` state 
  - Triggers refetch on period change
- [ ] **AssetAllocation Component**: Accepts `allocations?: AllocationItem[]` props; fallback to mock only when absent
- [ ] **ModernDashboard**: Mock component usage replaced with `<AssetAllocationContainer />`

### **Caching & Performance** ✅
- [ ] Query key includes `performancePeriod` for proper cache isolation across periods
- [ ] Hook passes `{ performancePeriod }` to `manager.analyzePortfolioRisk`
- [ ] Cache behavior: Different periods cache separately; period changes trigger refetch
- [ ] Performance: Period switching < 1 second with cached data

### **Data Quality & UX** ✅
- [ ] Real performance data displays instead of `+0.0%` placeholders
- [ ] Period selector shows 1M, 3M, 6M, 1Y, YTD options with "1M" default
- [ ] Loading states during period calculation
- [ ] Error handling for missing/partial performance data
- [ ] Development indicator shows "Real Data" vs "Mock Data" source
