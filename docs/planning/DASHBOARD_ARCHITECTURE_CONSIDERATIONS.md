# Risk Analysis Dashboard - Architecture Considerations

This document outlines critical architectural decisions and implementation considerations that should be addressed before and during the dashboard implementation.

## 1. Portfolio Context Management

### Current State
- Each component independently fetches portfolio context
- Portfolio ID retrieved from cookies/metadata per request

### Challenge
- Dashboard loads data once but needs consistent portfolio context
- Users may have multiple portfolios in database
- Need to handle portfolio switching

### Proposed Solution
```typescript
interface DashboardContext {
  currentPortfolioId: string;
  portfolioSource: 'database' | 'plaid' | 'yaml';
  userId: string;
  portfolioList?: Portfolio[]; // Available portfolios
}

// Add portfolio selector to dashboard header
<PortfolioSelector 
  current={currentPortfolioId}
  portfolios={userPortfolios}
  onChange={handlePortfolioSwitch}
/>
```

### Implementation Notes
- Store selected portfolio in React Context
- Persist selection in localStorage
- Clear analysis cache on portfolio switch
- Show loading state during portfolio change

## 2. Real-time Price Updates Integration

### Current State
- Price refresh implemented in portfolio display
- Manual refresh button triggers update

### Integration Requirements
- Dashboard should have global price refresh
- All views should update when prices change
- Preserve cash position handling (SGOV = 1.0)

### Proposed Implementation
```typescript
interface DashboardState {
  analysisData: AnalysisData;
  pricesLastUpdated: Date;
  isPriceRefreshing: boolean;
}

// Global refresh that triggers re-analysis
const refreshDashboard = async () => {
  // 1. Refresh prices
  const updatedPrices = await apiService.refreshPortfolioPrices(holdings);
  
  // 2. Trigger new analysis with updated prices
  const newAnalysis = await loadAnalysisData(true); // force refresh
  
  // 3. Update all views
  setAnalysisData(newAnalysis);
};
```

## 3. Performance & Loading Strategy

### ⚠️ ARCHITECTURAL GAP: Cache Management & Memory Issues

**Current Plan Issue:**
```typescript
// PROBLEMATIC: Aggressive caching without management
const [analysisData, setAnalysisData] = useState<AnalysisData | null>(null);

// Load all analysis data once
const loadAnalysisData = async () => {
  if (analysisData) return; // Already loaded
  // ⚠️ ARCHITECTURAL CONCERN: Never refreshes, grows indefinitely
};

// PROBLEMS:
// 1. No cache invalidation strategy
// 2. No memory management for large datasets
// 3. No lazy loading for expensive computations
// 4. All data loaded even if user only uses one view
```

### Recommended Solution: Smart Caching with TTL and Selective Loading
```typescript
interface CacheStrategy {
  maxAge: number; // TTL in milliseconds
  maxSize: number; // Maximum entries to store
  lazyLoad: boolean; // Load data only when view is accessed
  refreshTriggers: string[]; // Events that invalidate cache
  memoryLimit: number; // Maximum memory usage
}

interface CacheEntry<T> {
  data: T;
  timestamp: number;
  accessCount: number;
  lastAccessed: number;
  size: number; // Estimated memory size
}

class SmartCache<T> {
  private cache = new Map<string, CacheEntry<T>>();
  private totalSize = 0;
  
  constructor(private strategy: CacheStrategy) {}
  
  get(key: string): T | null {
    const entry = this.cache.get(key);
    if (!entry) return null;
    
    // Check TTL
    if (Date.now() - entry.timestamp > this.strategy.maxAge) {
      this.delete(key);
      return null;
    }
    
    // Update access statistics
    entry.accessCount++;
    entry.lastAccessed = Date.now();
    return entry.data;
  }
  
  set(key: string, data: T): void {
    const size = this.estimateSize(data);
    
    // Evict entries if needed
    this.evictIfNeeded(size);
    
    const entry: CacheEntry<T> = {
      data,
      timestamp: Date.now(),
      accessCount: 1,
      lastAccessed: Date.now(),
      size
    };
    
    this.cache.set(key, entry);
    this.totalSize += size;
  }
  
  private evictIfNeeded(newEntrySize: number): void {
    // LRU eviction when approaching limits
    while (
      (this.cache.size >= this.strategy.maxSize) ||
      (this.totalSize + newEntrySize > this.strategy.memoryLimit)
    ) {
      const lruKey = this.findLRUKey();
      if (lruKey) this.delete(lruKey);
    }
  }
  
  private findLRUKey(): string | null {
    let oldestTime = Date.now();
    let lruKey: string | null = null;
    
    for (const [key, entry] of this.cache) {
      if (entry.lastAccessed < oldestTime) {
        oldestTime = entry.lastAccessed;
        lruKey = key;
      }
    }
    
    return lruKey;
  }
  
  invalidate(pattern: string | RegExp): void {
    for (const key of this.cache.keys()) {
      if (typeof pattern === 'string' ? key.includes(pattern) : pattern.test(key)) {
        this.delete(key);
      }
    }
  }
  
  private delete(key: string): void {
    const entry = this.cache.get(key);
    if (entry) {
      this.totalSize -= entry.size;
      this.cache.delete(key);
    }
  }
  
  private estimateSize(data: any): number {
    // Rough estimation - could be more sophisticated
    return JSON.stringify(data).length * 2; // 2 bytes per char
  }
}

// Usage with lazy loading
const useCachedData = <T>(
  key: string, 
  loader: () => Promise<T>, 
  strategy: CacheStrategy
) => {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  
  const cache = useMemo(() => new SmartCache<T>(strategy), [strategy]);
  
  const loadData = useCallback(async (forceRefresh = false) => {
    // Check cache first
    if (!forceRefresh) {
      const cached = cache.get(key);
      if (cached) {
        setData(cached);
        return cached;
      }
    }
    
    setIsLoading(true);
    setError(null);
    
    try {
      const result = await loader();
      cache.set(key, result);
      setData(result);
      return result;
    } catch (err) {
      setError(err as Error);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [key, loader, cache]);
  
  // Auto-load based on strategy
  useEffect(() => {
    if (!strategy.lazyLoad || !data) {
      loadData();
    }
  }, [loadData, strategy.lazyLoad, data]);
  
  return { data, isLoading, error, reload: loadData };
};
```

### Challenge
- Loading all analysis data upfront can be slow
- Some analyses are compute-intensive
- Users may only view certain tabs

### Enhanced Progressive Loading Strategy
```typescript
// Phase 1: Critical data (risk score + current view)
const loadCriticalData = async () => {
  const [riskScore, currentViewData] = await Promise.all([
    apiService.getRiskScore(),
    loadViewData(activeView)
  ]);
};

// Phase 2: Background load remaining data with priority
const loadRemainingData = async () => {
  // Load in priority order with delays to prevent overwhelming
  const loadWithDelay = async (loader: () => Promise<any>, delay: number) => {
    await new Promise(resolve => setTimeout(resolve, delay));
    return loader();
  };
  
  const remaining = await Promise.allSettled([
    loadWithDelay(() => apiService.getPortfolioAnalysis(), 100),
    loadWithDelay(() => apiService.getPerformance(), 300),
    loadWithDelay(() => apiService.getRiskSettings(), 500)
  ]);
};

// Phase 3: Preload charts/visualizations only when view is likely to be accessed
const preloadVisualizations = async (viewId: string) => {
  // Only preload if user has been on dashboard for >30 seconds
  // and hasn't switched views recently
  const shouldPreload = (
    getDashboardSessionTime() > 30000 &&
    getTimeSinceLastViewChange() > 10000
  );
  
  if (shouldPreload) {
    await loadVisualizationData(viewId);
  }
};
```

### Enhanced Caching Strategy
- **TTL Management**: Respect backend 30-minute TTL with refresh indicators
- **Memory limits**: Implement cache size limits with LRU eviction
- **Selective refresh**: Allow manual refresh of specific data types
- **Portfolio scoping**: Cache by portfolio ID with automatic invalidation on switch
- **Background refresh**: Update stale data in background while showing cached version

## 4. Error Handling & Partial Failures

### ⚠️ ARCHITECTURAL GAP: Error Recovery Strategy

**Current Plan Issue:**
```typescript
// PROBLEMATIC: All-or-nothing loading
const loadAnalysisData = async () => {
  try {
    const [portfolioAnalysis, riskScore] = await Promise.all([
      apiService.getPortfolioAnalysis(),
      apiService.getRiskScore()
    ]);
    // ⚠️ ARCHITECTURAL CONCERN: No partial failure handling
  } catch (error) {
    console.error('Failed to load analysis:', error);
    // ⚠️ All data fails if any endpoint fails
  }
};

// PROBLEMS:
// 1. Single endpoint failure breaks entire dashboard
// 2. No retry mechanisms or exponential backoff
// 3. No graceful degradation for partial data
// 4. No offline/cache fallback strategy
```

### Recommended Solution: Resilient Data Loading
```typescript
interface FailureRecoveryStrategy {
  maxRetries: number;
  retryDelay: number;
  exponentialBackoff: boolean;
  fallbackToCache: boolean;
  partialFailureThreshold: number; // e.g., 0.5 = 50% endpoints must succeed
}

const loadAnalysisDataResilient = async (strategy: FailureRecoveryStrategy) => {
  const endpointLoaders = [
    { key: 'portfolioAnalysis', loader: () => apiService.getPortfolioAnalysis(), priority: 'high' },
    { key: 'riskScore', loader: () => apiService.getRiskScore(), priority: 'high' },
    { key: 'riskSettings', loader: () => apiService.getRiskSettings(), priority: 'medium' },
    { key: 'performance', loader: () => apiService.getPerformanceAnalysis(), priority: 'low' }
  ];
  
  // Use Promise.allSettled for partial failure handling
  const results = await Promise.allSettled(
    endpointLoaders.map(endpoint => retryWithBackoff(endpoint.loader, strategy))
  );
  
  // Process partial results
  const partialData: Partial<AnalysisData> = {};
  const errors: Record<string, Error> = {};
  let highPriorityFailures = 0;
  
  results.forEach((result, index) => {
    const endpoint = endpointLoaders[index];
    
    if (result.status === 'fulfilled') {
      partialData[endpoint.key] = result.value;
    } else {
      errors[endpoint.key] = result.reason;
      if (endpoint.priority === 'high') highPriorityFailures++;
      
      // Try cache fallback
      if (strategy.fallbackToCache) {
        const cachedData = getCachedData(endpoint.key);
        if (cachedData && !isExpired(cachedData)) {
          partialData[endpoint.key] = cachedData.data;
          partialData[`${endpoint.key}_isStale`] = true;
        }
      }
    }
  });
  
  // Determine if we have enough data to proceed
  const successfulHighPriority = endpointLoaders.filter(e => e.priority === 'high').length - highPriorityFailures;
  const canProceed = successfulHighPriority >= Math.ceil(endpointLoaders.filter(e => e.priority === 'high').length * strategy.partialFailureThreshold);
  
  return {
    data: partialData,
    errors,
    canProceed,
    degradedMode: Object.keys(errors).length > 0
  };
};

// Retry with exponential backoff
const retryWithBackoff = async (fn: () => Promise<any>, strategy: FailureRecoveryStrategy) => {
  let attempt = 0;
  
  while (attempt < strategy.maxRetries) {
    try {
      return await fn();
    } catch (error) {
      attempt++;
      if (attempt >= strategy.maxRetries) throw error;
      
      const delay = strategy.exponentialBackoff 
        ? strategy.retryDelay * Math.pow(2, attempt - 1)
        : strategy.retryDelay;
        
      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }
};
```

### Current Limitation
- Plan has single global error state
- One failed endpoint blocks entire dashboard

### Enhanced Granular Error Handling
```typescript
interface ViewState {
  data: any;
  loading: boolean;
  error: Error | null;
  lastUpdated: Date;
  isStale: boolean;
  hasPartialData: boolean; // NEW: Indicates degraded but functional state
  retryCount: number; // NEW: Track retry attempts
  canRetry: boolean; // NEW: Whether retry is available
}

interface DashboardViewStates {
  score: ViewState;
  metrics: ViewState;
  factors: ViewState;
  report: ViewState;
  settings: ViewState;
}

// Enhanced error boundary with degraded mode support
<ViewContainer>
  {viewState.error && !viewState.hasPartialData ? (
    <ErrorBoundary 
      error={viewState.error}
      onRetry={() => reloadView(viewId)}
      canRetry={viewState.canRetry}
      retryCount={viewState.retryCount}
    />
  ) : (
    <>
      {viewState.hasPartialData && (
        <DegradedModeWarning 
          message="Some data unavailable - showing cached/partial results"
          onRefresh={() => reloadView(viewId)}
        />
      )}
      <ViewContent 
        data={viewState.data} 
        isStale={viewState.isStale}
      />
    </>
  )}
</ViewContainer>
```

## 5. Component Coupling & Data Access Architecture

### ⚠️ ARCHITECTURAL GAP: Component Coupling Risk

**Current Plan Issue:**
```typescript
// PROBLEMATIC: Tight coupling between views and data structure
const getViewData = () => {
  const view = analysisViews.find(v => v.id === activeView);
  return view.dataExtractor(analysisData); // ⚠️ COUPLING CONCERN
};

// Each view's dataExtractor directly accesses API structure
dataExtractor: (analysis) => ({
  data: analysis.analysis.volatility_annual,  // Tightly coupled to backend
  visuals: analysis.analysis.formatted_tables
})

// PROBLEMS:
// 1. Each view tightly coupled to specific data structure
// 2. Backend API changes could break multiple views
// 3. Hard to unit test views in isolation
// 4. Difficult to add new data sources or transform data
// 5. No abstraction layer for business logic
```

### Recommended Solution: Data Repository Pattern
```typescript
// Abstract data access layer
interface DataRepository {
  // High-level data access methods
  getPortfolioMetrics(): Promise<PortfolioMetrics>;
  getRiskScore(): Promise<RiskScore>;
  getFactorAnalysis(): Promise<FactorAnalysis>;
  getPerformanceData(): Promise<PerformanceData>;
  getRiskSettings(): Promise<RiskSettings>;
  
  // Data transformation methods
  transformForView(data: any, viewType: ViewType): ViewData;
  validateData(data: any): boolean;
  
  // Cache management
  invalidateCache(keys: string[]): void;
  refreshData(dataType: string): Promise<void>;
}

// Implementation that handles API details
class ApiDataRepository implements DataRepository {
  constructor(private apiService: ApiService, private cache: DataCache) {}
  
  async getPortfolioMetrics(): Promise<PortfolioMetrics> {
    const rawData = await this.apiService.getPortfolioAnalysis();
    
    // Transform API response to standardized format
    return {
      volatility: rawData.analysis.volatility_annual,
      sharpeRatio: rawData.analysis.sharpe_ratio,
      concentrationRisk: this.calculateConcentration(rawData.analysis.allocations),
      // Abstract away API structure details
    };
  }
  
  transformForView(data: any, viewType: ViewType): ViewData {
    // Centralized view transformation logic
    switch (viewType) {
      case 'metrics':
        return this.transformMetricsView(data);
      case 'factors':
        return this.transformFactorsView(data);
      default:
        return data;
    }
  }
  
  private transformMetricsView(data: any): MetricsViewData {
    // Complex transformation logic isolated here
    return {
      data: {
        // Standardized metrics regardless of API changes
        portfolioMetrics: this.extractMetrics(data),
        riskContributions: this.calculateRiskContributions(data)
      },
      visuals: {
        // Chart-ready data
        timeSeriesData: this.prepareTimeSeriesData(data),
        distributionData: this.prepareDistributionData(data)
      }
    };
  }
}

// Views now depend on repository interface, not raw API
const MetricsView = () => {
  const repository = useDataRepository();
  const { data, isLoading, error } = useAsyncData(() => 
    repository.getPortfolioMetrics()
  );
  
  // View is decoupled from API structure
  return <MetricsDisplay metrics={data} />;
};

// Dependency injection for testing
const DashboardProvider = ({ children, repository }: Props) => (
  <DataRepositoryContext.Provider value={repository}>
    {children}
  </DataRepositoryContext.Provider>
);

// Easy to mock for testing
const MockDataRepository: DataRepository = {
  getPortfolioMetrics: async () => mockMetrics,
  getRiskScore: async () => mockRiskScore,
  // ... other methods
};
```

### Benefits of This Architecture:
1. **Decoupling**: Views don't know about API structure changes
2. **Testability**: Easy to mock data layer for unit tests
3. **Maintainability**: Business logic centralized in repository
4. **Flexibility**: Easy to add caching, validation, transformation
5. **Consistency**: All data access goes through same patterns

## 6. Cash Position Display Consistency

### Requirements
- Maintain "Cash Proxy" indicators across all views
- Ensure price=1.0 for cash positions
- Preserve type information through data transformations

### Implementation Checklist
- [ ] Risk Score view shows cash positions correctly
- [ ] Metrics view preserves cash type in tables
- [ ] Factor analysis excludes cash from factor betas
- [ ] Reports clearly indicate cash positions

## 6. WebSocket Integration (Future)

### Use Cases
- Real-time chat-visual synchronization
- Live risk alerts
- Collaborative analysis sessions
- Streaming large analyses

### Architecture Preparation
```typescript
interface WebSocketMessage {
  type: 'view_change' | 'data_update' | 'alert' | 'chat_action';
  payload: any;
  timestamp: Date;
}

// Prepare for future WebSocket
class DashboardConnection {
  connect() { /* HTTP polling for now */ }
  upgrade() { /* WebSocket when available */ }
}
```

## 7. Mobile UX Considerations

### ⚠️ ARCHITECTURAL GAP: Mobile/Responsive Architecture

**Current Plan Issue:**
```typescript
// MENTIONED BUT NOT ARCHITECTURALLY PLANNED
// Mobile Design
// - Responsive breakpoints:
//   - Desktop: > 1024px (three-panel layout: sidebar | content | chat)
//   - Tablet: 768-1024px (collapsible sidebar + stacked content/chat)
//   - Mobile: < 768px (hamburger menu sidebar + single column content)

// ⚠️ ARCHITECTURAL CONCERN: 
// - Layout changes affect entire component tree
// - No responsive state management 
// - No mobile-specific optimizations
// - Charts/tables may not work well on small screens
```

### Recommended Solution: Mobile-First Responsive Architecture
```typescript
interface ResponsiveState {
  breakpoint: 'mobile' | 'tablet' | 'desktop';
  layout: 'single-column' | 'two-column' | 'three-column';
  components: {
    sidebar: 'hidden' | 'overlay' | 'inline';
    chat: 'hidden' | 'modal' | 'panel';
    charts: 'simplified' | 'full';
  };
  interactions: {
    navigation: 'swipe' | 'click';
    charts: 'touch' | 'hover';
  };
}

// Responsive state management
const useResponsiveState = () => {
  const [state, setState] = useState<ResponsiveState>(getInitialState());
  
  useEffect(() => {
    const updateBreakpoint = () => {
      const width = window.innerWidth;
      const newBreakpoint = width < 768 ? 'mobile' : width < 1024 ? 'tablet' : 'desktop';
      
      if (newBreakpoint !== state.breakpoint) {
        setState(prevState => ({
          ...prevState,
          breakpoint: newBreakpoint,
          layout: getLayoutForBreakpoint(newBreakpoint),
          components: getComponentsForBreakpoint(newBreakpoint),
          interactions: getInteractionsForBreakpoint(newBreakpoint)
        }));
      }
    };
    
    window.addEventListener('resize', updateBreakpoint);
    return () => window.removeEventListener('resize', updateBreakpoint);
  }, [state.breakpoint]);
  
  return state;
};

// Responsive component that adapts behavior
const ResponsiveDashboard = () => {
  const responsive = useResponsiveState();
  
  return (
    <div className={`dashboard-${responsive.breakpoint}`}>
      {responsive.layout === 'three-column' ? (
        <ThreePanelLayout responsive={responsive} />
      ) : responsive.layout === 'two-column' ? (
        <TwoPanelLayout responsive={responsive} />
      ) : (
        <SingleColumnLayout responsive={responsive} />
      )}
    </div>
  );
};

// Mobile-optimized chart component
const ResponsiveChart = ({ data, type, responsive }: Props) => {
  const chartConfig = useMemo(() => {
    if (responsive.breakpoint === 'mobile') {
      return {
        width: Math.min(300, window.innerWidth - 40),
        height: 200,
        simplified: true,
        fontSize: 12,
        showLegend: false
      };
    } else if (responsive.breakpoint === 'tablet') {
      return {
        width: 400,
        height: 250,
        simplified: false,
        fontSize: 14,
        showLegend: true
      };
    } else {
      return {
        width: 500,
        height: 300,
        simplified: false,
        fontSize: 16,
        showLegend: true
      };
    }
  }, [responsive.breakpoint]);
  
  return (
    <ChartContainer config={chartConfig}>
      {responsive.components.charts === 'simplified' ? (
        <SimplifiedChart data={data} config={chartConfig} />
      ) : (
        <FullChart data={data} config={chartConfig} />
      )}
    </ChartContainer>
  );
};
```

### Responsive Breakpoints
- Desktop: > 1024px (three panels)
- Tablet: 768-1024px (collapsible sidebar)
- Mobile: < 768px (stacked layout)

### Enhanced Mobile-Specific Features
```typescript
// Touch-optimized swipe navigation
const useSwipeNavigation = (views: ViewConfig[], activeView: string, onViewChange: (view: string) => void) => {
  const [touchStart, setTouchStart] = useState<number | null>(null);
  const [touchEnd, setTouchEnd] = useState<number | null>(null);
  
  const minSwipeDistance = 50;
  
  const onTouchStart = (e: TouchEvent) => {
    setTouchEnd(null);
    setTouchStart(e.targetTouches[0].clientX);
  };
  
  const onTouchMove = (e: TouchEvent) => {
    setTouchEnd(e.targetTouches[0].clientX);
  };
  
  const onTouchEnd = () => {
    if (!touchStart || !touchEnd) return;
    
    const distance = touchStart - touchEnd;
    const isLeftSwipe = distance > minSwipeDistance;
    const isRightSwipe = distance < -minSwipeDistance;
    
    if (isLeftSwipe || isRightSwipe) {
      const currentIndex = views.findIndex(v => v.id === activeView);
      const nextIndex = isLeftSwipe ? currentIndex + 1 : currentIndex - 1;
      
      if (views[nextIndex]) {
        onViewChange(views[nextIndex].id);
        
        // Haptic feedback if available
        if ('vibrate' in navigator) {
          navigator.vibrate(50);
        }
      }
    }
  };
  
  return { onTouchStart, onTouchMove, onTouchEnd };
};

// Progressive enhancement for mobile
const MobileEnhancedLayout = ({ children, responsive }: Props) => {
  const swipeHandlers = useSwipeNavigation(views, activeView, setActiveView);
  
  return (
    <div 
      className="mobile-layout"
      {...(responsive.breakpoint === 'mobile' ? swipeHandlers : {})}
    >
      {responsive.breakpoint === 'mobile' && (
        <MobileHeader>
          <HamburgerMenu />
          <ViewIndicator activeView={activeView} totalViews={views.length} />
          <QuickActions />
        </MobileHeader>
      )}
      
      <main className="mobile-content">
        {children}
      </main>
      
      {responsive.components.chat === 'modal' && (
        <ChatModal>
          <ChatPanel />
        </ChatModal>
      )}
      
      {responsive.breakpoint === 'mobile' && (
        <MobileNavigation>
          <SwipeIndicator />
          <ViewDots views={views} activeView={activeView} />
        </MobileNavigation>
      )}
    </div>
  );
};

// Performance optimization for mobile
const useMobileOptimizations = (responsive: ResponsiveState) => {
  useEffect(() => {
    if (responsive.breakpoint === 'mobile') {
      // Reduce animation complexity
      document.documentElement.style.setProperty('--animation-duration', '200ms');
      
      // Disable hover effects
      document.body.classList.add('touch-device');
      
      // Optimize scroll performance
      document.body.style.webkitOverflowScrolling = 'touch';
    } else {
      // Restore desktop optimizations
      document.documentElement.style.setProperty('--animation-duration', '300ms');
      document.body.classList.remove('touch-device');
    }
  }, [responsive.breakpoint]);
};
```

## 8. Performance Analytics View

### Missing from Current Plan
The `/api/performance` endpoint exists but no view defined

### Proposed View Structure
```typescript
{
  id: 'performance',
  label: 'Performance',
  icon: '📊',
  displayMode: 'split',
  dataExtractor: (analysis) => ({
    data: {
      returns: analysis.performance.returns,
      riskMetrics: analysis.performance.risk_metrics,
      sharpeRatio: analysis.performance.risk_adjusted_returns.sharpe_ratio,
      benchmarkComparison: analysis.performance.benchmark_comparison
    },
    visuals: {
      returnTimeline: analysis.performance.monthly_returns,
      drawdownChart: analysis.performance.risk_metrics.drawdown_periods,
      rollingMetrics: calculateRollingMetrics(analysis.performance)
    }
  })
}
```

## 9. Scenario Management Architecture

### Requirements
- Store multiple portfolio configurations
- Compare scenarios side-by-side
- Track scenario lineage

### Data Structure
```typescript
interface Scenario {
  id: string;
  name: string;
  baselineId?: string; // Parent scenario
  portfolioConfig: PortfolioConfiguration;
  analysisResults?: AnalysisData;
  metadata: {
    createdAt: Date;
    createdBy: 'user' | 'ai' | 'optimizer';
    description: string;
    changes: ChangeLog[];
  };
}

interface ScenarioManager {
  scenarios: Map<string, Scenario>;
  activeScenarioId: string;
  maxScenarios: number; // Limit for performance
  
  createScenario(name: string, config: PortfolioConfiguration): string;
  deleteScenario(id: string): void;
  compareScenarios(ids: string[]): ComparisonResult;
  exportScenario(id: string): ScenarioExport;
}
```

## 10. Export & Sharing Architecture

### Export Formats
- PDF: Full report with charts
- CSV: Raw data tables
- JSON: Complete analysis data
- Link: Shareable read-only view

### Implementation Strategy
```typescript
interface ExportManager {
  exportView(viewId: string, format: ExportFormat): Promise<Blob>;
  exportFullAnalysis(format: ExportFormat): Promise<Blob>;
  generateShareLink(options: ShareOptions): Promise<string>;
}

// Server-side considerations
// - Generate temporary share tokens
// - Store shared analysis snapshots
// - Implement read-only API endpoints
```

## 11. Audit Trail & Compliance

### Tracking Requirements
```typescript
interface AuditEvent {
  userId: string;
  action: AuditAction;
  resource: string;
  details: Record<string, any>;
  timestamp: Date;
  ip?: string;
  userAgent?: string;
}

enum AuditAction {
  VIEW_ANALYSIS = 'view_analysis',
  EXPORT_DATA = 'export_data',
  MODIFY_SETTINGS = 'modify_settings',
  CREATE_SCENARIO = 'create_scenario',
  SHARE_ANALYSIS = 'share_analysis'
}

// Log significant actions
auditLogger.log({
  userId: user.id,
  action: AuditAction.MODIFY_SETTINGS,
  resource: 'risk_limits',
  details: { 
    field: 'max_volatility',
    oldValue: 0.25,
    newValue: 0.30
  }
});
```

## 12. Integration Points

### Current System Integration
- Portfolio Management: Load/switch portfolios
- What-if Analysis: Create scenarios from dashboard
- Risk Settings: Modify limits from settings view

### Future Integration Considerations
- Trade Execution: Apply rebalancing suggestions
- Alert System: Real-time risk notifications
- Collaboration: Shared analysis sessions
- External Data: Market data feeds

## 13. State Management Architecture

### ⚠️ CRITICAL ARCHITECTURAL GAP: React Context Scalability Risk

**Current Plan Issue:**
```typescript
// PROBLEMATIC: Simple React Context approach
interface AnalysisContext {
  activeView: 'score' | 'metrics' | 'factors' | 'report' | 'interpretation';
  viewData: {
    [key: string]: any;  // ⚠️ PERFORMANCE CONCERN
  };
}

// PROBLEMS:
// 1. Any viewData change re-renders entire component tree
// 2. No selective subscriptions to specific data slices
// 3. Complex nested updates will cause performance issues
// 4. No optimistic updates or state normalization
```

### Recommended Solution: Zustand with State Normalization
```typescript
interface DashboardStore {
  // Normalized data entities
  entities: {
    portfolioAnalysis: PortfolioAnalysis | null;
    riskScore: RiskScore | null;
    riskLimits: RiskLimits | null;
    performanceData: PerformanceData | null;
  };
  
  // UI state (separate from data)
  ui: {
    activeView: ViewType;
    isLoading: Record<string, boolean>;
    errors: Record<string, Error | null>;
  };
  
  // Cache management
  cache: {
    lastUpdated: Record<string, number>;
    staleTime: number;
    invalidationTriggers: string[];
  };
  
  // Portfolio context
  currentPortfolioId: string;
  portfolioList: Portfolio[];
  
  // Selective update actions
  updateEntity: <T>(entityType: keyof entities, data: T) => void;
  setUIState: (key: string, value: any) => void;
  invalidateCache: (keys: string[]) => void;
  
  // Derived state selectors
  getViewData: (viewId: ViewType) => any;
  isViewLoading: (viewId: ViewType) => boolean;
  isDataStale: (entityType: string) => boolean;
}

// Component subscription example
const MetricsView = () => {
  // Only re-renders when metrics data changes
  const metricsData = useDashboardStore(state => state.getViewData('metrics'));
  const isLoading = useDashboardStore(state => state.isViewLoading('metrics'));
  
  // This component won't re-render when other views' data changes
};
```

### Performance Benefits of This Approach:
1. **Selective re-renders** - Components only update when their data changes
2. **State normalization** - Avoids deep object updates
3. **Optimistic updates** - UI can update immediately while API calls complete  
4. **Memory efficiency** - Can implement cleanup for unused data

## 14. Testing Strategy

### Critical Test Scenarios
1. Portfolio switching maintains correct context
2. Price refresh updates all views
3. Cash positions display correctly
4. Partial API failures show graceful degradation
5. Mobile layout responds correctly
6. Export functions produce valid outputs
7. Audit trail captures all actions

### Performance Benchmarks
- Initial load: < 3 seconds
- View switch: < 100ms
- Price refresh: < 2 seconds
- Export generation: < 5 seconds

## Implementation Priority

### Phase 1 (MVP)
1. Portfolio context management
2. Basic view switching
3. Error handling per view
4. Cash position consistency

### Phase 2 (Enhanced)
1. Progressive loading
2. Price refresh integration
3. Mobile optimization
4. Basic export (PDF/CSV)

### Phase 3 (Advanced)
1. Scenario management
2. WebSocket integration
3. Collaborative features
4. Advanced analytics

## ⚠️ CRITICAL ARCHITECTURAL GAPS REQUIRING RESOLUTION

### High Priority Gaps to Address Before Implementation:

1. **State Management Architecture** - React Context will cause performance issues at scale
   - **Decision Needed**: Use Zustand, Redux Toolkit, or enhanced Context with normalization?
   - **Impact**: Affects entire component re-render behavior and user experience

2. **Error Recovery Strategy** - Current all-or-nothing loading will break dashboard frequently  
   - **Decision Needed**: Implement partial failure handling with retry mechanisms?
   - **Impact**: Determines dashboard reliability and user frustration levels

3. **Performance & Caching** - No cache invalidation or memory management planned
   - **Decision Needed**: Implement smart caching with TTL and LRU eviction?
   - **Impact**: Affects dashboard responsiveness and memory usage over time

4. **Component Coupling** - Views tightly coupled to specific API data structures
   - **Decision Needed**: Implement data repository pattern for abstraction?
   - **Impact**: Affects maintainability and testing, API change resilience

5. **Mobile/Responsive Architecture** - Basic responsive design without mobile optimizations
   - **Decision Needed**: Implement mobile-first architecture with touch optimizations?
   - **Impact**: Determines mobile user experience quality

## Decision Points Requiring Team Input

### Architectural Decisions:
1. **State Management**: Zustand vs. Redux Toolkit vs. Enhanced Context?
2. **Error Strategy**: Graceful degradation vs. retry mechanisms vs. both?
3. **Cache Implementation**: Browser storage vs. memory only vs. hybrid?
4. **Data Abstraction**: Repository pattern vs. direct API coupling?
5. **Mobile Strategy**: Progressive enhancement vs. separate mobile views?

### UX/Feature Decisions:
6. **Portfolio Switching UX**: Dropdown vs. modal vs. separate page?
7. **Export Security**: Any restrictions on what users can export?
8. **Mobile Features**: Which features to exclude on mobile?
9. **Scenario Limits**: How many scenarios can users create?
10. **Share Links**: Temporary vs. permanent? Access controls?

---

This document should be reviewed and updated as implementation progresses and new requirements emerge.

🤔 Potential Minor Gaps (Non-Critical):
1. URL Routing/Deep Linking
Current: View state only in memory
Consider: ?view=factors URL parameters for bookmarking
Decision: Probably not needed for Phase 1, easy to add later
2. Session Persistence
Current: Dashboard state resets on page refresh
Consider: localStorage for active view
Decision: Phase 2+ enhancement, not critical for MVP
3. Keyboard Shortcuts
Current: Mouse/touch navigation only
Consider: 1-5 keys for view switching
Decision: Nice-to-have, not essential for analysts
4. Advanced Data Export
Current: Basic export mentioned
Consider: PDF reports, custom CSV formatting
Decision: Phase 3+ feature, Claude can help with data interpretation