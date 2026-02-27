# Coordinated Caching Architecture Design

## Executive Summary

This document defines the target architecture for transforming our current multi-layer caching system from isolated silos into coordinated layers that communicate effectively while preserving the performance benefits that make our UI fast and responsive.

## 🎯 Design Goals

### Primary Objectives
- **Preserve UI Speed**: Maintain the fast, responsive user experience through multi-layer caching
- **Eliminate Cache Conflicts**: Prevent stale data and inconsistencies through coordinated invalidation
- **Maintain Multi-User Safety**: Ensure complete user isolation with per-user service instances
- **Reduce Complexity**: Simplify cache management through centralized coordination points
- **Enable Scalability**: Create patterns that prevent conflicts as new features are added

### Success Metrics
- **Zero cache invalidation failures** - All layers update consistently
- **Maintained UI performance** - No regression in response times
- **Simplified developer experience** - Single API for cache operations
- **Complete user isolation** - No cross-user data leakage
- **Predictable behavior** - Consistent cache state across all components

## 🏗️ Architectural Overview

### Four-Layer Coordinated Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  UI REACTIVITY LAYER                    │
│  Smart Memoization • Component Optimization • Rendering │
└─────────────────┬───────────────────────────────────────┘
                  ↕ (Event-Driven Communication)
┌─────────────────┴───────────────────────────────────────┐
│               APPLICATION STATE LAYER                   │
│  TanStack Query • Zustand Stores • Cache Coordinator   │
└─────────────────┬───────────────────────────────────────┘
                  ↕ (Coordinated Invalidation)
┌─────────────────┴───────────────────────────────────────┐
│             DATA TRANSFORMATION LAYER                   │
│  Unified Adapter Cache • AdapterRegistry • Transforms  │
└─────────────────┬───────────────────────────────────────┘
                  ↕ (Service Integration)
┌─────────────────┴───────────────────────────────────────┐
│                API/NETWORK LAYER                        │
│  Single Service Instances • Request Deduplication      │
└─────────────────────────────────────────────────────────┘
```

## 📋 Layer Specifications

### Layer 1: UI Reactivity Layer

**Purpose**: Optimize React rendering and prevent unnecessary component updates

**Components**:
- **Smart React.memo()**: Custom comparison functions based on actual data changes
- **Precise useMemo()**: Dependencies that accurately reflect data relationships
- **Stable useCallback()**: Function reference stability for child component optimization
- **Event Listeners**: React to cache invalidation events for coordinated updates

**Key Patterns**:
```typescript
// Smart memoization with data-aware comparison
const SmartMemoComponent = React.memo(Component, (prevProps, nextProps) => {
  return prevProps.data?.riskScore === nextProps.data?.riskScore &&
         prevProps.data?.lastUpdated === nextProps.data?.lastUpdated;
});

// Precise useMemo dependencies
const processedData = useMemo(() => {
  return expensiveTransformation(rawData);
}, [rawData.id, rawData.version, rawData.lastModified]);
```

**Responsibilities**:
- Prevent unnecessary re-renders when data hasn't actually changed
- Listen for cache invalidation events and trigger appropriate updates
- Provide smooth, responsive UI interactions
- Maintain component performance optimization

### Layer 2: Application State Layer

**Purpose**: Centralized state management with intelligent cache coordination

**Components**:
- **TanStack Query**: Server state management with user-scoped cache keys
- **Zustand Stores**: Client state (authentication, UI preferences, navigation)
- **Cache Coordinator**: Central orchestration of all cache invalidation operations
- **Event Bus**: Communication channel between layers and components

**Key Patterns**:
```typescript
// User-scoped query keys for multi-user isolation
const queryKey = ['portfolio', userId, portfolioId, 'riskAnalysis'];

// Coordinated cache invalidation
class CacheCoordinator {
  async invalidateRiskData(portfolioId: string) {
    // 1. Invalidate TanStack Query cache
    await this.queryClient.invalidateQueries(['risk', this.userId, portfolioId]);
    
    // 2. Clear adapter transformation caches
    this.adapterCache.clearByType('risk', portfolioId);
    
    // 3. Clear service-level caches
    this.serviceCache.clearPortfolio(portfolioId);
    
    // 4. Notify UI components
    this.eventBus.emit('risk-data-updated', { portfolioId, userId: this.userId });
  }
}
```

**Responsibilities**:
- Manage server state with automatic background synchronization
- Coordinate cache invalidation across all layers
- Provide event-driven communication between components
- Maintain user-scoped state isolation

### Layer 3: Data Transformation Layer

**Purpose**: Transform API responses into UI-ready formats with coordinated caching

**Components**:
- **Unified Adapter Cache**: Single cache instance shared across all adapters
- **AdapterRegistry**: Manages adapter instances with per-user scoping
- **Transformation Pipeline**: Consistent data formatting and validation
- **Cache Key Management**: Intelligent cache key generation and collision prevention

**Key Patterns**:
```typescript
// Unified cache shared by all adapters
class UnifiedAdapterCache {
  private cache = new Map<string, CacheEntry>();
  
  get<T>(key: string, transform: () => T, ttl: number): T {
    // Unified caching logic with coordinated invalidation
  }
  
  clearByType(dataType: 'risk' | 'portfolio' | 'performance', portfolioId: string) {
    // Clear all related transformations atomically
    const keysToDelete = Array.from(this.cache.keys())
      .filter(key => key.includes(dataType) && key.includes(portfolioId));
    keysToDelete.forEach(key => this.cache.delete(key));
  }
}

// Coordinated adapter pattern
class RiskScoreAdapter {
  constructor(private unifiedCache: UnifiedAdapterCache) {}
  
  transform(data: any): RiskScoreData {
    const cacheKey = this.generateCacheKey(data);
    return this.unifiedCache.get(cacheKey, () => this.transformInternal(data), this.TTL);
  }
}
```

**Responsibilities**:
- Transform raw API data into consistent UI formats
- Provide coordinated caching across all data transformations
- Generate intelligent cache keys that prevent collisions
- Enable atomic clearing of related transformation caches

### Layer 4: API/Network Layer

**Purpose**: Handle API requests with deduplication and response caching

**Components**:
- **Single Service Instances**: One APIService, PortfolioCacheService per user
- **Request Deduplication**: Prevent concurrent duplicate API calls
- **Response Caching**: Service-level caching with version-based keys
- **Network Optimization**: Intelligent request batching and prioritization

**Key Patterns**:
```typescript
// Enforced singleton pattern per user session
class APIService {
  private static instances = new Map<string, APIService>();
  
  static getInstance(userId: string): APIService {
    if (!this.instances.has(userId)) {
      this.instances.set(userId, new APIService(userId));
    }
    return this.instances.get(userId)!;
  }
  
  // Request deduplication
  private pendingRequests = new Map<string, Promise<any>>();
  
  async request(endpoint: string, options: RequestOptions): Promise<any> {
    const requestKey = this.generateRequestKey(endpoint, options);
    
    if (this.pendingRequests.has(requestKey)) {
      return this.pendingRequests.get(requestKey);
    }
    
    const requestPromise = this.executeRequest(endpoint, options);
    this.pendingRequests.set(requestKey, requestPromise);
    
    try {
      const result = await requestPromise;
      return result;
    } finally {
      this.pendingRequests.delete(requestKey);
    }
  }
}
```

**Responsibilities**:
- Provide single service instances per user to prevent proliferation
- Deduplicate concurrent requests to the same endpoints
- Cache API responses with intelligent versioning
- Optimize network usage through batching and prioritization

## 🔄 Data Flow Architecture

### Request Flow (Bottom-Up)
```
1. Component requests data
   ↓
2. UI Layer checks memoization cache
   ↓
3. State Layer checks TanStack Query cache
   ↓
4. Transformation Layer checks adapter cache
   ↓
5. Service Layer checks API response cache
   ↓
6. Network request (if all caches miss)
   ↓
7. Response flows back up through all layers
   ↓
8. Each layer caches appropriate data
   ↓
9. Component receives optimized data
```

### Invalidation Flow (Top-Down)
```
1. User action triggers mutation
   ↓
2. Cache Coordinator orchestrates invalidation
   ↓
3. State Layer: Clear TanStack Query cache
   ↓
4. Transformation Layer: Clear adapter caches
   ↓
5. Service Layer: Clear API response caches
   ↓
6. Event Bus: Notify all interested components
   ↓
7. UI Layer: Components check for updates
   ↓
8. Fresh data flows through all layers
```

## 🔐 Multi-User Architecture

### Per-User Service Isolation

Each authenticated user receives a complete, isolated set of coordinated layers:

```
User A Session:
├── UI Reactivity Layer A (User A's components)
├── Application State Layer A (User A's queries & stores)
├── Data Transformation Layer A (User A's adapters)
└── API/Network Layer A (User A's services)

User B Session:
├── UI Reactivity Layer B (User B's components)
├── Application State Layer B (User B's queries & stores)
├── Data Transformation Layer B (User B's adapters)
└── API/Network Layer B (User B's services)
```

### User Isolation Guarantees

- **Complete Data Separation**: No cross-user data access possible
- **Independent Cache Management**: User A's invalidation doesn't affect User B
- **Scoped Service Instances**: Each user gets their own service container
- **User-Scoped Cache Keys**: All cache keys include user identification
- **Session-Based Lifecycle**: Services created on login, destroyed on logout

## 🎯 Coordination Mechanisms

### Cache Coordinator

**Central orchestration service for coordinated cache invalidation**

```typescript
interface CacheCoordinator {
  // Data type invalidation
  invalidateRiskData(portfolioId: string): Promise<void>;
  invalidatePortfolioData(portfolioId: string): Promise<void>;
  invalidatePerformanceData(portfolioId: string): Promise<void>;
  
  // Bulk operations
  invalidateAllPortfolioData(portfolioId: string): Promise<void>;
  invalidateUserData(): Promise<void>;
  
  // Selective invalidation
  invalidateByPattern(pattern: string, scope: string): Promise<void>;
}
```

### Event Bus

**Communication channel enabling loose coupling between layers**

```typescript
interface EventBus {
  // Data update events
  emit('risk-data-updated', { portfolioId: string, userId: string }): void;
  emit('portfolio-changed', { portfolioId: string, userId: string }): void;
  emit('cache-invalidated', { dataType: string, portfolioId: string }): void;
  
  // Component lifecycle events
  emit('component-mounted', { componentId: string, dataRequirements: string[] }): void;
  emit('component-unmounted', { componentId: string }): void;
  
  // Performance monitoring events
  emit('cache-hit', { layer: string, key: string, responseTime: number }): void;
  emit('cache-miss', { layer: string, key: string, fetchTime: number }): void;
}
```

### Unified Adapter Cache

**Shared caching infrastructure preventing adapter-level conflicts**

```typescript
interface UnifiedAdapterCache {
  // Coordinated caching operations
  get<T>(key: string, factory: () => T, ttl: number): T;
  set<T>(key: string, value: T, ttl: number): void;
  delete(key: string): boolean;
  
  // Bulk operations
  clearByType(dataType: string, portfolioId?: string): number;
  clearByPattern(pattern: RegExp): number;
  clearAll(): void;
  
  // Monitoring and debugging
  getStats(): CacheStats;
  getKeys(): string[];
  inspect(key: string): CacheEntry | null;
}
```

## 🚀 Performance Characteristics

### Speed Preservation

- **Multi-Layer Caching**: Each layer provides performance benefits
- **Request Deduplication**: Eliminates redundant network calls
- **Smart Memoization**: Prevents unnecessary React re-renders
- **Background Synchronization**: Keeps data fresh without blocking UI
- **Coordinated Cache Hits**: Better cache efficiency through coordination

### Memory Optimization

- **Shared Cache Instances**: Reduces memory footprint
- **Intelligent TTL Management**: Automatic cleanup of stale data
- **User-Scoped Lifecycle**: Complete cleanup on user logout
- **Coordinated Eviction**: Removes related data atomically

### Network Efficiency

- **Request Deduplication**: Prevents duplicate concurrent requests
- **Intelligent Batching**: Combines related API calls
- **Background Prefetching**: Anticipates data needs
- **Conditional Requests**: Uses ETags and cache headers effectively

## 🔧 Implementation Strategy

### Phase 1: Foundation (1-2 weeks)
- Create CacheCoordinator service
- Implement EventBus communication system
- Create UnifiedAdapterCache infrastructure
- Add runtime validation for service instances

### Phase 2: Layer Coordination (2-3 weeks)
- Replace React.memo with smart comparison functions
- Implement coordinated invalidation patterns
- Migrate adapters to unified cache system
- Update service instantiation to enforce singletons

### Phase 3: Integration & Optimization (1-2 weeks)
- Connect all layers through coordination mechanisms
- Add performance monitoring and debugging tools
- Implement cache warming and prefetching strategies
- Add comprehensive testing for coordination patterns

## 📊 Success Metrics

### Performance Metrics
- **UI Response Time**: Maintain < 100ms for cached data access
- **Cache Hit Ratio**: Achieve > 80% cache hits across all layers
- **Memory Usage**: Reduce cache memory footprint by 30%
- **Network Requests**: Reduce redundant API calls by 90%

### Reliability Metrics
- **Cache Consistency**: Zero instances of stale data display
- **Invalidation Success**: 100% successful coordinated invalidation
- **User Isolation**: Zero cross-user data leakage incidents
- **Error Recovery**: Graceful degradation when cache layers fail

### Developer Experience Metrics
- **API Simplicity**: Single method call for cache invalidation
- **Debugging Clarity**: Clear visibility into cache state and operations
- **Development Speed**: Faster feature development through predictable patterns
- **Bug Reduction**: Fewer cache-related bugs through coordination

## 🎯 Migration Considerations

### Backward Compatibility
- Maintain existing API contracts during transition
- Provide gradual migration path for existing components
- Preserve current performance characteristics
- Support both old and new patterns during transition period

### Risk Mitigation
- Implement feature flags for coordinated caching rollout
- Provide fallback mechanisms for cache coordination failures
- Monitor performance metrics during migration
- Maintain rollback capability for each implementation phase

### Testing Strategy
- Unit tests for individual coordination components
- Integration tests for cross-layer communication
- Performance tests to validate speed preservation
- Multi-user tests to verify isolation guarantees

## 📋 COMPREHENSIVE IMPLEMENTATION PLAN

### Current Frontend Architecture Analysis

#### ✅ EXISTING FOUNDATION (80% Complete)

**Provider Hierarchy (Perfect Foundation)**:
```
App.tsx
├── QueryProvider (TanStack Query) ✅
├── AuthProvider (Zustand authStore) ✅  
├── SessionServicesProvider (Per-user services) ✅
└── AppOrchestrator (State machine) ✅
```

**State Management (Excellent Foundation)**:
- **TanStack Query**: Server state with user-scoped keys ✅
- **Zustand Stores**: `authStore`, `portfolioStore`, `uiStore` ✅
- **Cross-tab sync**: Authentication state synchronization ✅
- **Multi-user isolation**: Complete per-user service containers ✅

**Service Layer (Good Foundation, Needs Normalization)**:
- **SessionServicesProvider**: Creates per-user service instances ✅
- **ServiceContainer**: Dependency injection pattern ✅
- **Single instances per user**: Mostly implemented (fixed PortfolioManager) ✅
- **Request deduplication**: APIService has Map-based deduplication ✅

**Hook Patterns (Excellent Foundation)**:
- **Consistent patterns**: All hooks follow same TanStack Query + Adapter pattern ✅
- **User-scoped queries**: Query keys include user context ✅
- **AdapterRegistry usage**: All hooks use `AdapterRegistry.getAdapter()` ✅
- **Error handling**: Consistent error patterns across hooks ✅

#### 🔄 COMPONENTS REQUIRING REFACTORING

**React Memoization (8 modern containers to update)**:
```
Current: React.memo(Component) // Generic memoization
Target:  React.memo(Component, smartComparison) // Data-aware memoization
```
- `PortfolioOverviewContainer.tsx`
- `RiskAnalysisModernContainer.tsx`
- `PerformanceViewContainer.tsx`
- `HoldingsViewModernContainer.tsx`
- `RiskSettingsContainer.tsx`
- `ScenarioAnalysisContainer.tsx`
- `StockLookupContainer.tsx`
- `StrategyBuilderContainer.tsx`

*Note: Legacy containers will be moved to legacy folder and excluded from refactoring*

**Adapter Caches (6 adapters to refactor)**:
```
Current: Each adapter has private Map<string, CacheEntry>
Target:  All adapters use shared UnifiedAdapterCache
```
- `RiskScoreAdapter`, `RiskAnalysisAdapter`, `PortfolioSummaryAdapter`
- `PerformanceAdapter`, `AnalysisReportAdapter`, `PortfolioOptimizationAdapter`

**Manual Cache Invalidation (1 hook to refactor)**:
```
Current: useRiskSettings manually clears each cache layer
Target:  CacheCoordinator.invalidateRiskData() handles all layers
```
- `useRiskSettings.ts` - Replace manual clearing with coordinated invalidation

#### 🆕 NEW COMPONENTS TO CREATE

**Coordination Services (3 new services)**:
1. **CacheCoordinator** - Orchestrates invalidation across all layers
2. **EventBus** - Enables communication between layers and components  
3. **UnifiedAdapterCache** - Shared cache instance for all adapters

### Phase-by-Phase Implementation Plan

#### Phase 1: Foundation Components (Week 1-2)

**1.1 Create EventBus Service**
```typescript
// Location: frontend/src/services/EventBus.ts
// Purpose: Communication channel between layers
// Effort: LOW (2-3 hours)
// Dependencies: None

interface EventBus {
  emit(event: string, data: any): void;
  on(event: string, handler: (data: any) => void): () => void;
  off(event: string, handler: (data: any) => void): void;
}
```

**1.2 Create UnifiedAdapterCache Service**
```typescript
// Location: frontend/src/services/UnifiedAdapterCache.ts  
// Purpose: Shared cache for all adapters
// Effort: MEDIUM (4-6 hours)
// Dependencies: EventBus

class UnifiedAdapterCache {
  private cache = new Map<string, CacheEntry>();
  constructor(private eventBus: EventBus) {}
  
  get<T>(key: string, factory: () => T, ttl: number): T;
  clearByType(dataType: string, portfolioId?: string): number;
  clearByPattern(pattern: RegExp): number;
}
```

**1.3 Create CacheCoordinator Service**
```typescript
// Location: frontend/src/services/CacheCoordinator.ts
// Purpose: Orchestrate invalidation across all layers
// Effort: MEDIUM (6-8 hours)  
// Dependencies: EventBus, UnifiedAdapterCache, QueryClient, PortfolioCacheService

class CacheCoordinator {
  async invalidateRiskData(portfolioId: string): Promise<void>;
  async invalidatePortfolioData(portfolioId: string): Promise<void>;
  async invalidateAllData(portfolioId: string): Promise<void>;
}
```

**1.4 Register Services in SessionServicesProvider**
```typescript
// Location: frontend/src/providers/SessionServicesProvider.tsx
// Purpose: Add new services to dependency injection
// Effort: LOW (1-2 hours)
// Dependencies: All Phase 1 services

sessionServiceContainer.register('eventBus', () => new EventBus());
sessionServiceContainer.register('unifiedAdapterCache', () => 
  new UnifiedAdapterCache(sessionServiceContainer.get('eventBus'))
);
sessionServiceContainer.register('cacheCoordinator', () => 
  new CacheCoordinator(/* all dependencies */)
);
```

**Phase 1 Deliverables**:
- ✅ EventBus service with pub/sub functionality
- ✅ UnifiedAdapterCache with coordinated clearing
- ✅ CacheCoordinator with invalidation orchestration
- ✅ Services registered in SessionServicesProvider
- ✅ Runtime validation for service instances

#### Phase 2: Layer Coordination (Week 3-4)

**2.1 Refactor Adapter Internal Caches**
```typescript
// Target: 6 adapter files
// Pattern: Replace private Map with UnifiedAdapterCache injection
// Effort: MEDIUM (8-12 hours total, ~2 hours per adapter)

// Before:
class RiskScoreAdapter {
  private cache: Map<string, CacheEntry> = new Map();
}

// After:  
class RiskScoreAdapter {
  constructor(private unifiedCache: UnifiedAdapterCache) {}
  
  transform(data: any) {
    return this.unifiedCache.get(cacheKey, () => this.transformInternal(data), this.TTL);
  }
}
```

**Files to Update**:
- `adapters/RiskScoreAdapter.ts`
- `adapters/RiskAnalysisAdapter.ts`  
- `adapters/PortfolioSummaryAdapter.ts`
- `adapters/PerformanceAdapter.ts`
- `adapters/AnalysisReportAdapter.ts`
- `adapters/PortfolioOptimizationAdapter.ts`

**2.2 Update AdapterRegistry to Use UnifiedCache**
```typescript
// Location: frontend/src/utils/AdapterRegistry.ts
// Purpose: Pass UnifiedAdapterCache to all adapter factories
// Effort: LOW (2-3 hours)

// Before:
AdapterRegistry.getAdapter('riskScore', [portfolioId], () => new RiskScoreAdapter());

// After:
AdapterRegistry.getAdapter('riskScore', [portfolioId], (unifiedCache) => 
  new RiskScoreAdapter(unifiedCache)
);
```

**2.3 Replace Manual Cache Invalidation**
```typescript
// Location: frontend/src/features/riskSettings/hooks/useRiskSettings.ts
// Purpose: Replace manual clearing with coordinated invalidation
// Effort: MEDIUM (4-6 hours)

// Before: Manual clearing of each layer
AdapterRegistry.delete('riskScore', [portfolioId]);
cache.clearPortfolio(portfolioId);
queryClient.invalidateQueries(['risk', userId, portfolioId]);

// After: Coordinated invalidation
const { cacheCoordinator } = useSessionServices();
await cacheCoordinator.invalidateRiskData(portfolioId);
```

**2.4 Implement Smart React Memoization**
```typescript
// Target: 8 modern container components (legacy containers excluded)
// Pattern: Replace generic React.memo with data-aware comparison
// Effort: MEDIUM (5-6 hours total)

// Before:
export default React.memo(PortfolioOverviewContainer);

// After:
const smartComparison = (prevProps: Props, nextProps: Props) => {
  return prevProps.data?.summary?.riskScore === nextProps.data?.summary?.riskScore &&
         prevProps.data?.summary?.lastUpdated === nextProps.data?.summary?.lastUpdated;
};
export default React.memo(PortfolioOverviewContainer, smartComparison);
```

**Phase 2 Deliverables**:
- ✅ All adapters using UnifiedAdapterCache
- ✅ AdapterRegistry coordinating cache injection
- ✅ useRiskSettings using coordinated invalidation
- ✅ Smart React.memo comparison functions
- ✅ Event-driven component updates

#### Phase 3: Integration & Optimization (Week 5-6)

**3.1 Add Event-Driven Component Updates**
```typescript
// Target: Key components that display cached data
// Pattern: Listen for cache invalidation events
// Effort: MEDIUM (6-8 hours)

const PortfolioOverviewContainer = () => {
  const { eventBus } = useSessionServices();
  
  useEffect(() => {
    const unsubscribe = eventBus.on('risk-data-updated', ({ portfolioId }) => {
      if (portfolioId === currentPortfolio?.id) {
        // Trigger re-render or refetch
      }
    });
    return unsubscribe;
  }, [eventBus, currentPortfolio?.id]);
};
```

**3.2 Implement Cache Performance Monitoring**
```typescript
// Location: frontend/src/services/CacheMonitor.ts
// Purpose: Track cache performance and debugging
// Effort: LOW (3-4 hours)

class CacheMonitor {
  trackCacheHit(layer: string, key: string, responseTime: number): void;
  trackCacheMiss(layer: string, key: string, fetchTime: number): void;
  generateReport(): CachePerformanceReport;
}
```

**3.3 Add Cache Warming Strategies**
```typescript
// Location: frontend/src/services/CacheWarmer.ts
// Purpose: Preload critical data for better UX
// Effort: MEDIUM (4-6 hours)

class CacheWarmer {
  async warmPortfolioData(portfolioId: string): Promise<void>;
  async warmRiskData(portfolioId: string): Promise<void>;
}
```

**3.4 Create Developer Debugging Tools**
```typescript
// Location: frontend/src/utils/CacheDebugger.ts
// Purpose: Visualize cache state and operations
// Effort: LOW (2-3 hours)

class CacheDebugger {
  inspectCacheState(): CacheStateReport;
  visualizeInvalidationFlow(dataType: string): InvalidationFlowDiagram;
}
```

**Phase 3 Deliverables**:
- ✅ Event-driven component updates
- ✅ Cache performance monitoring
- ✅ Cache warming for critical data
- ✅ Developer debugging tools
- ✅ Comprehensive testing suite

### Implementation Effort Summary

| Phase | Component | Effort Level | Time Estimate |
|-------|-----------|--------------|---------------|
| **Phase 1** | EventBus | LOW | 2-3 hours |
| | UnifiedAdapterCache | MEDIUM | 4-6 hours |
| | CacheCoordinator | MEDIUM | 6-8 hours |
| | Service Registration | LOW | 1-2 hours |
| **Phase 2** | Adapter Refactoring (6 files) | MEDIUM | 8-12 hours |
| | AdapterRegistry Updates | LOW | 2-3 hours |
| | useRiskSettings Refactor | MEDIUM | 4-6 hours |
| | Smart React.memo (8 modern files) | MEDIUM | 5-6 hours |
| **Phase 3** | Event-Driven Updates | MEDIUM | 6-8 hours |
| | Performance Monitoring | LOW | 3-4 hours |
| | Cache Warming | MEDIUM | 4-6 hours |
| | Debugging Tools | LOW | 2-3 hours |

**Total Estimated Effort**: 48-67 hours (6-8 days of focused development)

### Legacy Container Conflict Analysis & Mitigation

#### 🔍 **CONFLICT ASSESSMENT**

**✅ GOOD NEWS: Minimal Conflicts Detected**

**Shared Infrastructure (Potential Conflicts)**:
- ✅ **SessionServicesProvider**: Both modern and legacy containers use the SAME user-scoped services
- ✅ **AdapterRegistry**: Both use the SAME adapter instances (shared cache state)
- ✅ **TanStack Query**: Both use the SAME query client and cache
- ✅ **Hook Layer**: Both use identical hooks (`useRiskScore`, `useRiskAnalysis`, etc.)

**Current Isolation**:
- ✅ **UI Switching**: `AppOrchestratorModern` conditionally renders either `DashboardApp` (legacy) OR `ModernDashboardApp` (modern)
- ✅ **No Simultaneous Usage**: Only one UI active at a time per user session
- ✅ **Same Data Sources**: Both UIs consume identical transformed data from same adapters

#### 🛡️ **CONFLICT MITIGATION STRATEGY**

**Phase 1: Coordination Services (No Conflicts)**
```typescript
// NEW services are additive - legacy containers won't use them
sessionServiceContainer.register('eventBus', () => new EventBus());
sessionServiceContainer.register('unifiedAdapterCache', () => new UnifiedAdapterCache());
sessionServiceContainer.register('cacheCoordinator', () => new CacheCoordinator());

// Legacy containers continue using existing patterns:
// - Direct adapter calls (no coordination)
// - Manual TanStack Query invalidation
// - Individual adapter internal caches
```

**Phase 2: Adapter Refactoring (Backward Compatible)**
```typescript
// BEFORE: Legacy and modern both use individual adapter caches
class RiskScoreAdapter {
  private cache: Map<string, CacheEntry> = new Map(); // ✅ Works for both
}

// AFTER: Adapters accept optional UnifiedAdapterCache
class RiskScoreAdapter {
  constructor(private unifiedCache?: UnifiedAdapterCache) {}
  
  transform(data: any) {
    // ✅ Backward compatible: Falls back to internal cache if no unified cache
    if (this.unifiedCache) {
      return this.unifiedCache.get(key, () => this.transformInternal(data), TTL);
    } else {
      // Legacy path: Use internal Map cache
      return this.getFromInternalCache(key, () => this.transformInternal(data));
    }
  }
}
```

**Phase 3: Selective Coordination**
```typescript
// Modern containers: Use coordinated invalidation
const { cacheCoordinator } = useSessionServices();
await cacheCoordinator.invalidateRiskData(portfolioId);

// Legacy containers: Continue manual invalidation (unchanged)
queryClient.invalidateQueries(['risk', userId, portfolioId]);
```

#### 🔧 **IMPLEMENTATION SAFETY MEASURES**

**1. Gradual Adapter Migration**
```typescript
// AdapterRegistry factory function becomes backward compatible
AdapterRegistry.getAdapter('riskScore', [portfolioId], (unifiedCache?) => {
  // Modern containers pass unifiedCache, legacy containers pass undefined
  return new RiskScoreAdapter(unifiedCache);
});
```

**2. Always-On Coordination Services**
```typescript
// In SessionServicesProvider - Always register coordination services
sessionServiceContainer.register('eventBus', () => new EventBus());
sessionServiceContainer.register('unifiedAdapterCache', () => 
  new UnifiedAdapterCache(sessionServiceContainer.get('eventBus'))
);
sessionServiceContainer.register('cacheCoordinator', () => new CacheCoordinator(
  sessionServiceContainer.get('queryClient'),
  sessionServiceContainer.get('portfolioCacheService'),
  sessionServiceContainer.get('unifiedAdapterCache'),
  sessionServiceContainer.get('eventBus')
));
```

**3. Runtime Detection**
```typescript
// Adapters can detect if they're in coordinated mode
class RiskScoreAdapter {
  get isCoordinated() {
    return !!this.unifiedCache;
  }
  
  clearCache() {
    if (this.isCoordinated) {
      // Modern path: Coordinated clearing
      this.unifiedCache.clearByType('riskScore', this.portfolioId);
    } else {
      // Legacy path: Internal cache clearing
      this.internalCache.clear();
    }
  }
}
```

#### 🎯 **ZERO-CONFLICT GUARANTEE**

**Why This Approach is Safe**:
- ✅ **Additive Changes**: New services don't replace existing ones
- ✅ **Optional Coordination**: Adapters work with or without UnifiedAdapterCache
- ✅ **UI Isolation**: Only one UI active at a time (no simultaneous conflicts)
- ✅ **Backward Compatibility**: Legacy containers continue working unchanged
- ✅ **Gradual Migration**: Can enable coordination per-container basis

**Rollback Strategy**:
- ✅ **Phase 1**: Simply don't register new services
- ✅ **Phase 2**: Adapters fall back to internal caches automatically  
- ✅ **Phase 3**: Modern containers fall back to manual invalidation

### Risk Mitigation Strategy

**Low-Risk Implementation**:
- ✅ **Incremental rollout** - Each phase can be deployed independently
- ✅ **Backward compatibility** - Legacy containers continue working unchanged
- ✅ **Always-on coordination** - New services available to all containers immediately
- ✅ **Rollback capability** - Each phase can be reverted if issues arise
- ✅ **Zero legacy conflicts** - Legacy containers remain completely unaffected
- ✅ **Future archival ready** - Legacy code can be moved to archives anytime

**Testing Strategy**:
- **Unit tests** for each new service (EventBus, UnifiedAdapterCache, CacheCoordinator)
- **Integration tests** for cross-layer coordination
- **Performance tests** to validate speed preservation
- **Multi-user tests** to verify isolation guarantees

**Monitoring & Validation**:
- **Cache hit ratio monitoring** - Ensure performance is maintained
- **Invalidation success tracking** - Verify coordinated clearing works
- **User isolation validation** - Confirm no cross-user data leakage
- **Performance regression testing** - Maintain UI responsiveness

### Success Criteria

**Phase 1 Success**:
- ✅ All new services created and registered
- ✅ Services accessible via `useSessionServices()`
- ✅ Runtime validation prevents service instance proliferation
- ✅ No performance regression

**Phase 2 Success**:
- ✅ All adapters using unified cache
- ✅ Coordinated invalidation working in useRiskSettings
- ✅ Smart React.memo preventing unnecessary re-renders
- ✅ Zero cache invalidation failures

**Phase 3 Success**:
- ✅ Event-driven updates working across components
- ✅ Cache performance monitoring operational
- ✅ Developer debugging tools functional
- ✅ Complete coordinated caching architecture operational

## 📝 DETAILED IMPLEMENTATION SPECIFICATION

### Phase 1: New Service Components

#### 1.1 EventBus Service

**File**: `frontend/src/chassis/services/EventBus.ts`

**Purpose**: Cross-layer communication service for coordinated caching

```typescript
import { frontendLogger } from '../../services/frontendLogger';

export interface CacheEvent {
  type: 'cache-invalidated' | 'cache-cleared' | 'data-updated' | 'adapter-cleared';
  source: 'coordinator' | 'adapter' | 'service' | 'component';
  portfolioId?: string;
  dataType?: string;
  timestamp: number;
  metadata?: Record<string, any>;
}

export type EventHandler<T = any> = (data: T) => void;

export class EventBus {
  private listeners = new Map<string, Set<EventHandler>>();
  
  /**
   * Subscribe to events of a specific type
   * @param event Event type to listen for
   * @param handler Function to call when event occurs
   * @returns Unsubscribe function
   */
  on<T = any>(event: string, handler: EventHandler<T>): () => void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    
    this.listeners.get(event)!.add(handler);
    
    // Return unsubscribe function
    return () => {
      const handlers = this.listeners.get(event);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.listeners.delete(event);
        }
      }
    };
  }
  
  /**
   * Emit an event to all subscribers
   * @param event Event type to emit
   * @param data Data to send with the event
   */
  emit<T = any>(event: string, data: T): void {
    const handlers = this.listeners.get(event);
    if (handlers) {
      handlers.forEach(handler => {
        try {
          handler(data);
          frontendLogger.adapter.transformSuccess('EventBus', `Event emitted: ${event}`);
        } catch (error) {
          frontendLogger.adapter.transformError('EventBus', error as Error, { event, data });
          // Don't re-throw - continue with other handlers
        }
      });
    }
  }
  
  /**
   * Remove a specific handler for an event
   */
  off<T = any>(event: string, handler: EventHandler<T>): void {
    const handlers = this.listeners.get(event);
    if (handlers) {
      handlers.delete(handler);
      if (handlers.size === 0) {
        this.listeners.delete(event);
      }
    }
  }
  
  /**
   * Remove all handlers for an event, or all handlers if no event specified
   */
  clear(event?: string): void {
    if (event) {
      this.listeners.delete(event);
    } else {
      this.listeners.clear();
    }
  }
  
  /**
   * Get current listener count for debugging
   */
  getListenerCount(event?: string): number {
    if (event) {
      return this.listeners.get(event)?.size || 0;
    }
    return Array.from(this.listeners.values()).reduce((total, handlers) => total + handlers.size, 0);
  }
  
  // MEMORY LEAK DETECTION (for debugging)
  getActiveListenerCount(): number {
    return Array.from(this.listeners.values()).reduce((total, handlers) => total + handlers.size, 0);
  }
  
  getListenersByEvent(): Record<string, number> {
    const result: Record<string, number> = {};
    for (const [event, handlers] of this.listeners.entries()) {
      result[event] = handlers.size;
    }
    return result;
  }
}
```

#### 1.2 UnifiedAdapterCache Service

**File**: `frontend/src/chassis/services/UnifiedAdapterCache.ts`

**Purpose**: Shared cache service replacing individual adapter Map-based caches

```typescript
import { EventBus, CacheEvent } from './EventBus';
import { frontendLogger } from '../../services/frontendLogger';

export interface CacheEntry<T = any> {
  value: T;
  timestamp: number;
  ttl: number;
  portfolioId?: string;
  dataType?: string;
}

export interface CacheStats {
  totalEntries: number;
  hitCount: number;
  missCount: number;
  hitRatio: number;
  entriesByType: Record<string, number>;
  entriesByPortfolio: Record<string, number>;
}

export interface CachePerformanceMetrics {
  hitRatio: number;
  avgResponseTime: number;
  totalRequests: number;
  errorRate: number;
  entriesByType: Record<string, { hits: number; misses: number; errors: number }>;
  recentOperations: Array<{
    timestamp: number;
    operation: 'hit' | 'miss' | 'clear' | 'error';
    key: string;
    responseTime?: number;
    dataType?: string;
  }>;
}

export class UnifiedAdapterCache {
  private cache = new Map<string, CacheEntry>();
  private performanceMetrics = {
    totalRequests: 0,
    totalHits: 0,
    totalMisses: 0,
    totalErrors: 0,
    responseTimes: [] as number[],
    operationLog: [] as any[],
    typeMetrics: new Map<string, { hits: number; misses: number; errors: number }>()
  };
  
  constructor(private eventBus: EventBus) {}
  
  /**
   * Get value from cache or create it using factory function
   */
  get<T>(
    key: string, 
    factory: () => T, 
    ttl: number, 
    metadata?: { portfolioId?: string; dataType?: string }
  ): T {
    const startTime = performance.now();
    this.performanceMetrics.totalRequests++;
    
    try {
      const entry = this.cache.get(key);
      const now = Date.now();
      
      // Check if entry exists and is not expired
      if (entry && (now - entry.timestamp) < entry.ttl) {
        const responseTime = performance.now() - startTime;
        this.recordOperation('hit', key, responseTime, metadata?.dataType);
        frontendLogger.adapter.transformSuccess('UnifiedAdapterCache', `Cache hit: ${key}`);
        return entry.value as T;
      }
      
      // Cache miss or expired - create new value
      frontendLogger.adapter.transformStart('UnifiedAdapterCache', `Cache miss: ${key}`);
      const value = factory();
      const responseTime = performance.now() - startTime;
      this.recordOperation('miss', key, responseTime, metadata?.dataType);
      
      const cacheEntry: CacheEntry<T> = {
        value,
        timestamp: now,
        ttl,
        portfolioId: metadata?.portfolioId,
        dataType: metadata?.dataType
      };
      
      this.cache.set(key, cacheEntry);
      
      // Emit cache update event
      this.eventBus.emit<CacheEvent>('cache-updated', {
        type: 'data-updated',
        source: 'adapter',
        portfolioId: metadata?.portfolioId,
        dataType: metadata?.dataType,
        timestamp: now,
        metadata: { key, ttl }
      });
      
      frontendLogger.adapter.transformSuccess('UnifiedAdapterCache', `Cached: ${key}`);
      return value;
      
    } catch (error) {
      const responseTime = performance.now() - startTime;
      this.recordOperation('error', key, responseTime, metadata?.dataType);
      frontendLogger.adapter.transformError('UnifiedAdapterCache', error as Error, { key, metadata });
      throw error;
    }
  }
  
  /**
   * Clear cache entries by data type and optionally portfolio
   */
  clearByType(dataType: string, portfolioId?: string): number {
    let clearedCount = 0;
    const keysToDelete: string[] = [];
    
    for (const [key, entry] of this.cache.entries()) {
      const matchesType = entry.dataType === dataType;
      const matchesPortfolio = !portfolioId || entry.portfolioId === portfolioId;
      
      if (matchesType && matchesPortfolio) {
        keysToDelete.push(key);
        clearedCount++;
      }
    }
    
    keysToDelete.forEach(key => this.cache.delete(key));
    
    if (clearedCount > 0) {
      frontendLogger.adapter.transformSuccess('UnifiedAdapterCache', 
        `Cleared ${clearedCount} entries for type: ${dataType}${portfolioId ? `, portfolio: ${portfolioId}` : ''}`
      );
      
      // Emit cache cleared event
      this.eventBus.emit<CacheEvent>('cache-cleared', {
        type: 'cache-cleared',
        source: 'adapter',
        portfolioId,
        dataType,
        timestamp: Date.now(),
        metadata: { clearedCount }
      });
    }
    
    return clearedCount;
  }
  
  /**
   * Clear cache entries matching a pattern
   */
  clearByPattern(pattern: RegExp): number {
    let clearedCount = 0;
    const keysToDelete: string[] = [];
    
    for (const key of this.cache.keys()) {
      if (pattern.test(key)) {
        keysToDelete.push(key);
        clearedCount++;
      }
    }
    
    keysToDelete.forEach(key => this.cache.delete(key));
    
    if (clearedCount > 0) {
      frontendLogger.adapter.transformSuccess('UnifiedAdapterCache', 
        `Cleared ${clearedCount} entries matching pattern: ${pattern}`
      );
    }
    
    return clearedCount;
  }
  
  /**
   * Clear all cache entries for a portfolio
   */
  clearPortfolio(portfolioId: string): number {
    let clearedCount = 0;
    const keysToDelete: string[] = [];
    
    for (const [key, entry] of this.cache.entries()) {
      if (entry.portfolioId === portfolioId) {
        keysToDelete.push(key);
        clearedCount++;
      }
    }
    
    keysToDelete.forEach(key => this.cache.delete(key));
    
    if (clearedCount > 0) {
      frontendLogger.adapter.transformSuccess('UnifiedAdapterCache', 
        `Cleared ${clearedCount} entries for portfolio: ${portfolioId}`
      );
    }
    
    return clearedCount;
  }
  
  private recordOperation(
    operation: 'hit' | 'miss' | 'clear' | 'error',
    key: string,
    responseTime: number,
    dataType?: string
  ): void {
    // Update counters
    if (operation === 'hit') this.performanceMetrics.totalHits++;
    if (operation === 'miss') this.performanceMetrics.totalMisses++;
    if (operation === 'error') this.performanceMetrics.totalErrors++;
    
    // Track response times
    this.performanceMetrics.responseTimes.push(responseTime);
    if (this.performanceMetrics.responseTimes.length > 1000) {
      this.performanceMetrics.responseTimes.shift(); // Keep last 1000
    }
    
    // Track by type
    if (dataType) {
      if (!this.performanceMetrics.typeMetrics.has(dataType)) {
        this.performanceMetrics.typeMetrics.set(dataType, { hits: 0, misses: 0, errors: 0 });
      }
      const typeStats = this.performanceMetrics.typeMetrics.get(dataType)!;
      typeStats[operation === 'hit' ? 'hits' : operation === 'miss' ? 'misses' : 'errors']++;
    }
    
    // Log recent operations
    this.performanceMetrics.operationLog.push({
      timestamp: Date.now(),
      operation,
      key,
      responseTime,
      dataType
    });
    
    // Keep only last 100 operations
    if (this.performanceMetrics.operationLog.length > 100) {
      this.performanceMetrics.operationLog.shift();
    }
  }
  
  /**
   * Get cache statistics for monitoring
   */
  getStats(): CacheStats {
    const entriesByType: Record<string, number> = {};
    const entriesByPortfolio: Record<string, number> = {};
    
    for (const entry of this.cache.values()) {
      if (entry.dataType) {
        entriesByType[entry.dataType] = (entriesByType[entry.dataType] || 0) + 1;
      }
      if (entry.portfolioId) {
        entriesByPortfolio[entry.portfolioId] = (entriesByPortfolio[entry.portfolioId] || 0) + 1;
      }
    }
    
    const totalRequests = this.performanceMetrics.totalHits + this.performanceMetrics.totalMisses;
    
    return {
      totalEntries: this.cache.size,
      hitCount: this.performanceMetrics.totalHits,
      missCount: this.performanceMetrics.totalMisses,
      hitRatio: totalRequests > 0 ? this.performanceMetrics.totalHits / totalRequests : 0,
      entriesByType,
      entriesByPortfolio
    };
  }
  
  /**
   * Get performance metrics for monitoring
   */
  getPerformanceMetrics(): CachePerformanceMetrics {
    const totalRequests = this.performanceMetrics.totalRequests;
    const avgResponseTime = this.performanceMetrics.responseTimes.length > 0 ?
      this.performanceMetrics.responseTimes.reduce((a, b) => a + b, 0) / this.performanceMetrics.responseTimes.length : 0;
    
    return {
      hitRatio: totalRequests > 0 ? this.performanceMetrics.totalHits / totalRequests : 0,
      avgResponseTime,
      totalRequests,
      errorRate: totalRequests > 0 ? this.performanceMetrics.totalErrors / totalRequests : 0,
      entriesByType: Object.fromEntries(this.performanceMetrics.typeMetrics),
      recentOperations: [...this.performanceMetrics.operationLog]
    };
  }
  
  /**
   * Clear all cache entries
   */
  clear(): void {
    const clearedCount = this.cache.size;
    this.cache.clear();
    
    frontendLogger.adapter.transformSuccess('UnifiedAdapterCache', 
      `Cleared all cache entries (${clearedCount} total)`
    );
  }
}
```

#### 1.3 CacheCoordinator Service

**File**: `frontend/src/chassis/services/CacheCoordinator.ts`

**Purpose**: Orchestrates cache invalidation across all layers

```typescript
import { QueryClient } from '@tanstack/react-query';
import { PortfolioCacheService } from './PortfolioCacheService';
import { UnifiedAdapterCache } from './UnifiedAdapterCache';
import { EventBus, CacheEvent } from './EventBus';
import { AdapterRegistry } from '../../utils/AdapterRegistry';
import { frontendLogger } from '../../services/frontendLogger';
import { 
  riskScoreKey, 
  riskAnalysisKey, 
  performanceKey, 
  portfolioSummaryKey,
  riskSettingsKey 
} from '../../queryKeys';

export interface InvalidationResult {
  success: boolean;
  layersCleared: string[];
  entriesCleared: number;
  errors: string[];
  timestamp: number;
}

export class CacheCoordinator {
  constructor(
    private queryClient: QueryClient,
    private portfolioCacheService: PortfolioCacheService,
    private unifiedAdapterCache: UnifiedAdapterCache,
    private eventBus: EventBus
  ) {}
  
  /**
   * Invalidate all risk-related data for a portfolio
   * Clears: risk score, risk analysis, risk settings
   */
  async invalidateRiskData(portfolioId: string): Promise<InvalidationResult> {
    const layersCleared: string[] = [];
    const errors: string[] = [];
    let totalEntriesCleared = 0;
    let partialSuccess = false;
    
    frontendLogger.user.action('invalidateRiskData', 'CacheCoordinator', { portfolioId });
    
    try {
      // Layer 1: Clear adapter internal caches and remove from registry
      const adapterTypes = ['riskScore', 'riskAnalysis', 'factor'];
      
      for (const adapterType of adapterTypes) {
        try {
          // Clear from unified cache
          const cleared = this.unifiedAdapterCache.clearByType(adapterType, portfolioId);
          totalEntriesCleared += cleared;
          layersCleared.push(`UnifiedAdapterCache:${adapterType}(${cleared})`);
          partialSuccess = true;
          
          // Remove adapter instances from registry
          AdapterRegistry.delete(adapterType, [portfolioId]);
          layersCleared.push(`AdapterRegistry:${adapterType}`);
          
        } catch (error) {
          errors.push(`Failed to clear ${adapterType}: ${error.message}`);
        }
      }
      
      // Layer 2: Clear PortfolioCacheService
      try {
        this.portfolioCacheService.clearPortfolio(portfolioId);
        layersCleared.push('PortfolioCacheService');
        partialSuccess = true;
      } catch (error) {
        errors.push(`PortfolioCacheService failed: ${error.message}`);
      }
      
      // Layer 3: Invalidate TanStack Query cache
      try {
        await Promise.all([
          this.queryClient.invalidateQueries({ queryKey: riskScoreKey(portfolioId) }),
          this.queryClient.invalidateQueries({ queryKey: riskAnalysisKey(portfolioId) }),
          this.queryClient.invalidateQueries({ queryKey: riskSettingsKey(portfolioId) })
        ]);
        layersCleared.push('TanStackQuery:risk');
        partialSuccess = true;
      } catch (error) {
        errors.push(`TanStack Query failed: ${error.message}`);
      }
      
      // Layer 4: Emit coordination event
      try {
        this.eventBus.emit<CacheEvent>('risk-data-invalidated', {
          type: 'cache-invalidated',
          source: 'coordinator',
          portfolioId,
          dataType: 'risk',
          timestamp: Date.now(),
          metadata: { layersCleared, entriesCleared: totalEntriesCleared }
        });
      } catch (error) {
        errors.push(`EventBus failed: ${error.message}`);
      }
      
      const result: InvalidationResult = {
        success: partialSuccess && errors.length === 0,
        layersCleared,
        entriesCleared: totalEntriesCleared,
        errors,
        timestamp: Date.now()
      };
      
      frontendLogger.user.action('invalidateRiskDataComplete', 'CacheCoordinator', result);
      return result;
      
    } catch (error) {
      const result: InvalidationResult = {
        success: false,
        layersCleared,
        entriesCleared: totalEntriesCleared,
        errors: [`Critical error: ${error.message}`],
        timestamp: Date.now()
      };
      
      frontendLogger.adapter.transformError('CacheCoordinator', error as Error, { portfolioId });
      return result;
    }
  }
  
  /**
   * Invalidate all portfolio-related data
   * Clears: portfolio summary, performance, holdings
   */
  async invalidatePortfolioData(portfolioId: string): Promise<InvalidationResult> {
    const layersCleared: string[] = [];
    const errors: string[] = [];
    let totalEntriesCleared = 0;
    let partialSuccess = false;
    
    frontendLogger.user.action('invalidatePortfolioData', 'CacheCoordinator', { portfolioId });
    
    try {
      // Clear adapter caches
      const adapterTypes = ['portfolioSummary', 'performance'];
      
      for (const adapterType of adapterTypes) {
        try {
          const cleared = this.unifiedAdapterCache.clearByType(adapterType, portfolioId);
          totalEntriesCleared += cleared;
          AdapterRegistry.delete(adapterType, [portfolioId]);
          layersCleared.push(`UnifiedAdapterCache:${adapterType}(${cleared})`);
          partialSuccess = true;
        } catch (error) {
          errors.push(`Failed to clear ${adapterType}: ${error.message}`);
        }
      }
      
      // Clear service cache
      try {
        this.portfolioCacheService.clearPortfolio(portfolioId);
        layersCleared.push('PortfolioCacheService');
        partialSuccess = true;
      } catch (error) {
        errors.push(`PortfolioCacheService failed: ${error.message}`);
      }
      
      // Invalidate queries
      try {
        await Promise.all([
          this.queryClient.invalidateQueries({ queryKey: portfolioSummaryKey(portfolioId) }),
          this.queryClient.invalidateQueries({ queryKey: performanceKey(portfolioId) })
        ]);
        layersCleared.push('TanStackQuery:portfolio');
        partialSuccess = true;
      } catch (error) {
        errors.push(`TanStack Query failed: ${error.message}`);
      }
      
      return {
        success: partialSuccess && errors.length === 0,
        layersCleared,
        entriesCleared: totalEntriesCleared,
        errors,
        timestamp: Date.now()
      };
      
    } catch (error) {
      return {
        success: false,
        layersCleared,
        entriesCleared: totalEntriesCleared,
        errors: [`Critical error: ${error.message}`],
        timestamp: Date.now()
      };
    }
  }
  
  /**
   * Invalidate ALL data for a portfolio (nuclear option)
   */
  async invalidateAllData(portfolioId: string): Promise<InvalidationResult> {
    frontendLogger.user.action('invalidateAllData', 'CacheCoordinator', { portfolioId });
    
    const riskResult = await this.invalidateRiskData(portfolioId);
    const portfolioResult = await this.invalidatePortfolioData(portfolioId);
    
    return {
      success: riskResult.success && portfolioResult.success,
      layersCleared: [...riskResult.layersCleared, ...portfolioResult.layersCleared],
      entriesCleared: riskResult.entriesCleared + portfolioResult.entriesCleared,
      errors: [...riskResult.errors, ...portfolioResult.errors],
      timestamp: Date.now()
    };
  }
}
```

#### 1.4 Cache Types Definition

**File**: `frontend/src/types/cache.ts` (NEW FILE)

**Purpose**: Standardized cache key metadata and utility functions

```typescript
export interface CacheKeyMetadata {
  portfolioId: string;
  dataType: 'riskScore' | 'riskAnalysis' | 'performance' | 'portfolioSummary' | 'analysisReport' | 'optimization';
  version?: string;
  userId?: string;
  timestamp?: number;
}

export interface StandardCacheKey {
  key: string;
  metadata: CacheKeyMetadata;
}

/**
 * Utility function for generating standardized cache keys
 * @param baseKey The base cache key (usually a content hash)
 * @param metadata Cache metadata for standardization
 * @returns Standardized cache key with metadata
 */
export function generateStandardCacheKey(
  baseKey: string, 
  metadata: CacheKeyMetadata
): StandardCacheKey {
  const keyParts = [
    metadata.dataType,
    metadata.portfolioId,
    baseKey,
    metadata.version || 'v1'
  ].filter(Boolean);
  
  return {
    key: keyParts.join('_'),
    metadata: {
      ...metadata,
      timestamp: Date.now()
    }
  };
}

/**
 * Parse a standardized cache key back into components
 * @param key The standardized cache key
 * @returns Parsed components or null if invalid format
 */
export function parseStandardCacheKey(key: string): { dataType: string; portfolioId: string; baseKey: string; version: string } | null {
  const parts = key.split('_');
  if (parts.length < 4) return null;
  
  return {
    dataType: parts[0],
    portfolioId: parts[1],
    baseKey: parts.slice(2, -1).join('_'),
    version: parts[parts.length - 1]
  };
}
```

### Phase 1: Service Registration Changes

#### 1.5 SessionServicesProvider Updates

**File**: `frontend/src/providers/SessionServicesProvider.tsx`

**Key Changes Required**:

1. **Add imports**:
```typescript
import { EventBus } from '../chassis/services/EventBus';
import { UnifiedAdapterCache } from '../chassis/services/UnifiedAdapterCache';
import { CacheCoordinator } from '../chassis/services/CacheCoordinator';
import { useQueryClient } from '@tanstack/react-query';
```

2. **Update Services interface** - Add coordination services:
```typescript
interface Services {
  // ... existing services
  eventBus: EventBus;
  unifiedAdapterCache: UnifiedAdapterCache;
  cacheCoordinator: CacheCoordinator;
}
```

3. **Register coordination services** in service container:
```typescript
sessionServiceContainer.register('eventBus', () => new EventBus());
sessionServiceContainer.register('unifiedAdapterCache', () => 
  new UnifiedAdapterCache(sessionServiceContainer.get('eventBus'))
);
sessionServiceContainer.register('cacheCoordinator', () => 
  new CacheCoordinator(
    queryClient,
    sessionServiceContainer.get('portfolioCacheService'),
    sessionServiceContainer.get('unifiedAdapterCache'),
    sessionServiceContainer.get('eventBus')
  )
);
```

### Phase 2: Adapter Refactoring Specifications

#### 2.1 Adapter Pattern Changes

**Files**: 6 adapter files need updates
- `RiskScoreAdapter.ts`
- `RiskAnalysisAdapter.ts` 
- `PortfolioSummaryAdapter.ts`
- `PerformanceAdapter.ts`
- `AnalysisReportAdapter.ts`
- `PortfolioOptimizationAdapter.ts`

**Pattern for each adapter**:

1. **Constructor update** - Accept optional UnifiedAdapterCache:
```typescript
constructor(private unifiedCache?: UnifiedAdapterCache) {}
```

2. **Transform method update** - Use unified cache if available:
```typescript
transform(apiResponse: any): TransformedData {
  const cacheKey = this.generateCacheKey(apiResponse);
  
  if (this.unifiedCache) {
    return this.unifiedCache.get(
      cacheKey,
      () => this.transformInternal(apiResponse),
      this.TTL,
      { portfolioId: this.extractPortfolioId(apiResponse), dataType: 'adapterType' }
    );
  } else {
    // Fallback to internal cache for backward compatibility
    return this.getFromInternalCache(cacheKey, () => this.transformInternal(apiResponse));
  }
}
```

3. **clearCache method update**:
```typescript
clearCache(): void {
  if (this.unifiedCache) {
    this.unifiedCache.clearByType('adapterType');
  } else {
    this.internalCache.clear();
  }
}
```

#### 2.2 AdapterRegistry Updates

**File**: `frontend/src/utils/AdapterRegistry.ts`

**CLEAN BREAKING CHANGE** - Update getAdapter method to require UnifiedAdapterCache:
```typescript
static getAdapter<T>(
  type: string, 
  dependencies: unknown[], 
  factory: (unifiedCache: UnifiedAdapterCache) => T,  // Required parameter
  unifiedCache: UnifiedAdapterCache                   // Required parameter
): T {
  const key = `${type}_${hashArgs(dependencies)}`;
  
  if (AdapterRegistry.adapters.has(key)) {
    return AdapterRegistry.adapters.get(key) as T;
  }
  
  // CLEAN: Single signature, no complexity
  const adapter = factory(unifiedCache);
  AdapterRegistry.adapters.set(key, adapter);
  return adapter;
}
```

**RATIONALE**: Clean breaking change is simpler than backward compatibility since we're already updating all usage sites for coordinated caching.

#### 2.3 Hook Updates for Coordination

**File**: `frontend/src/features/riskSettings/hooks/useRiskSettings.ts`

**Replace manual cache clearing** with coordinated invalidation:

```typescript
// BEFORE: Manual clearing (50+ lines of code)
const adapterTypes = ['riskScore', 'riskAnalysis', 'factor', 'performance', 'portfolioSummary'];
adapterTypes.forEach(adapterType => {
  // Manual adapter clearing...
});
cache.clearPortfolio(portfolioId);
await Promise.all([
  queryClient.invalidateQueries(...),
  // More manual invalidations...
]);

// AFTER: Single coordinated call (3 lines of code)
const { cacheCoordinator } = useSessionServices();
const result = await cacheCoordinator.invalidateRiskData(currentPortfolio.id);
```

### Phase 3: Component Integration Specifications

#### 3.1 Smart React.memo Implementation

**Files**: 8 modern container components

**Pattern for each container**:
```typescript
// BEFORE: Generic memoization
export default React.memo(ComponentName);

// AFTER: Smart comparison
const smartComparison = (prevProps: Props, nextProps: Props) => {
  return (
    prevProps.data?.key === nextProps.data?.key &&
    prevProps.isLoading === nextProps.isLoading &&
    prevProps.error === nextProps.error
  );
};
export default React.memo(ComponentName, smartComparison);
```

#### 3.2 Event-Driven Component Updates

**Pattern for components that display cached data**:
```typescript
const Component = () => {
  const { eventBus } = useSessionServices();
  const currentPortfolio = useCurrentPortfolio();
  const { refetch } = useDataHook();
  
  useEffect(() => {
    const unsubscribe = eventBus.on('risk-data-invalidated', ({ portfolioId }) => {
      if (portfolioId === currentPortfolio?.id) {
        refetch();
      }
    });
    return unsubscribe;
  }, [eventBus, currentPortfolio?.id, refetch]);
};
```

### Implementation Effort Summary

| Component | File Changes | Effort | Key Changes |
|-----------|--------------|--------|-------------|
| **EventBus** | 1 new file | 2-3 hours | Complete new service |
| **UnifiedAdapterCache** | 1 new file | 4-6 hours | Complete new service |
| **CacheCoordinator** | 1 new file | 6-8 hours | Complete new service |
| **SessionServicesProvider** | 1 file update | 1-2 hours | Add service registration |
| **6 Adapters** | 6 file updates | 8-12 hours | Constructor + transform method |
| **AdapterRegistry** | 1 file update | 2-3 hours | Update getAdapter signature |
| **useRiskSettings** | 1 file update | 4-6 hours | Replace manual clearing |
| **8 Containers** | 8 file updates | 5-6 hours | Smart React.memo + events |

**Total**: 16 files changed, 48-67 hours estimated

## 🔍 COMPREHENSIVE IMPLEMENTATION REVIEW

### Critical Gaps & Considerations Identified

#### 🚨 **1. TypeScript Integration Concerns**

**Issue**: Our new services need proper TypeScript integration
```typescript
// MISSING: Proper type exports in service index files
// frontend/src/chassis/services/index.ts needs updates

// CURRENT: Only exports singleton instances
export { stockManager } from './StockManager';

// NEEDED: Export classes for our new services
export { EventBus } from './EventBus';
export { UnifiedAdapterCache } from './UnifiedAdapterCache';
export { CacheCoordinator } from './CacheCoordinator';
```

**Fix Required**: Update `frontend/src/chassis/services/index.ts` to export new service classes

**SOLUTION**:
```typescript
// frontend/src/chassis/services/index.ts - ADD THESE EXPORTS
export { EventBus } from './EventBus';
export { UnifiedAdapterCache } from './UnifiedAdapterCache';
export { CacheCoordinator } from './CacheCoordinator';

// Keep existing exports
export { stockManager } from './StockManager';
export { APIService } from './APIService';
export { ClaudeService } from './ClaudeService';
// ... other existing exports
```

#### 🚨 **2. Error Handling Pattern Consistency**

**Issue**: Our services must follow existing error handling patterns
```typescript
// EXISTING PATTERN (from APIService, adapters):
try {
  // operation
  frontendLogger.adapter.transformSuccess('ServiceName', 'Operation completed');
} catch (error) {
  frontendLogger.adapter.transformError('ServiceName', error, { context });
  throw error; // Re-throw for upstream handling
}
```

**Fix Required**: Ensure all new services use `frontendLogger` consistently

**SOLUTION**: Update all service implementations with proper error handling:

```typescript
// EventBus.ts - ADD ERROR HANDLING
import { frontendLogger } from '../../services/frontendLogger';

export class EventBus {
  emit<T>(event: string, data: T): void {
    const handlers = this.listeners.get(event);
    if (handlers) {
      handlers.forEach(handler => {
        try {
          handler(data);
          frontendLogger.adapter.transformSuccess('EventBus', `Event emitted: ${event}`);
        } catch (error) {
          frontendLogger.adapter.transformError('EventBus', error as Error, { event, data });
          // Don't re-throw - continue with other handlers
        }
      });
    }
  }
}

// UnifiedAdapterCache.ts - ADD ERROR HANDLING  
import { frontendLogger } from '../../services/frontendLogger';

export class UnifiedAdapterCache {
  get<T>(key: string, factory: () => T, ttl: number, metadata?: any): T {
    try {
      // ... cache logic
      frontendLogger.adapter.transformSuccess('UnifiedAdapterCache', `Cache operation: ${key}`);
      return value;
    } catch (error) {
      frontendLogger.adapter.transformError('UnifiedAdapterCache', error as Error, { key, metadata });
      throw error; // Re-throw for upstream handling
    }
  }
}

// CacheCoordinator.ts - ADD ERROR HANDLING
import { frontendLogger } from '../../services/frontendLogger';

export class CacheCoordinator {
  async invalidateRiskData(portfolioId: string): Promise<InvalidationResult> {
    try {
      frontendLogger.user.action('invalidateRiskData', 'CacheCoordinator', { portfolioId });
      // ... coordination logic
      frontendLogger.user.action('invalidateRiskDataComplete', 'CacheCoordinator', result);
      return result;
    } catch (error) {
      frontendLogger.adapter.transformError('CacheCoordinator', error as Error, { portfolioId });
      return { success: false, errors: [error.message], /* ... */ };
    }
  }
}
```

#### 🚨 **3. Testing Strategy Gap**

**Issue**: No testing plan for new coordination services
- **EventBus**: Needs pub/sub functionality tests
- **UnifiedAdapterCache**: Needs TTL, clearing, and stats tests  
- **CacheCoordinator**: Needs integration tests across all layers

**Fix Required**: Add testing specifications to implementation plan

**SOLUTION**: Create comprehensive test files for all new services:

```typescript
// tests/frontend/services/EventBus.test.js
describe('EventBus', () => {
  test('should emit and receive events', () => {
    const eventBus = new EventBus();
    const handler = jest.fn();
    
    eventBus.on('test-event', handler);
    eventBus.emit('test-event', { data: 'test' });
    
    expect(handler).toHaveBeenCalledWith({ data: 'test' });
  });
  
  test('should handle unsubscribe correctly', () => {
    const eventBus = new EventBus();
    const handler = jest.fn();
    
    const unsubscribe = eventBus.on('test-event', handler);
    unsubscribe();
    eventBus.emit('test-event', { data: 'test' });
    
    expect(handler).not.toHaveBeenCalled();
  });
  
  test('should handle handler errors gracefully', () => {
    const eventBus = new EventBus();
    const errorHandler = jest.fn(() => { throw new Error('Handler error'); });
    const goodHandler = jest.fn();
    
    eventBus.on('test-event', errorHandler);
    eventBus.on('test-event', goodHandler);
    eventBus.emit('test-event', { data: 'test' });
    
    expect(goodHandler).toHaveBeenCalled(); // Should still execute
  });
});

// tests/frontend/services/UnifiedAdapterCache.test.js
describe('UnifiedAdapterCache', () => {
  test('should cache and retrieve values', () => {
    const eventBus = new EventBus();
    const cache = new UnifiedAdapterCache(eventBus);
    const factory = jest.fn(() => 'cached-value');
    
    const result1 = cache.get('test-key', factory, 30000);
    const result2 = cache.get('test-key', factory, 30000);
    
    expect(result1).toBe('cached-value');
    expect(result2).toBe('cached-value');
    expect(factory).toHaveBeenCalledTimes(1); // Only called once
  });
  
  test('should respect TTL expiration', async () => {
    const eventBus = new EventBus();
    const cache = new UnifiedAdapterCache(eventBus);
    const factory = jest.fn(() => 'cached-value');
    
    cache.get('test-key', factory, 100); // 100ms TTL
    await new Promise(resolve => setTimeout(resolve, 150));
    cache.get('test-key', factory, 100);
    
    expect(factory).toHaveBeenCalledTimes(2); // Called twice due to expiration
  });
  
  test('should clear by type correctly', () => {
    const eventBus = new EventBus();
    const cache = new UnifiedAdapterCache(eventBus);
    
    cache.get('key1', () => 'value1', 30000, { dataType: 'riskScore', portfolioId: 'p1' });
    cache.get('key2', () => 'value2', 30000, { dataType: 'riskAnalysis', portfolioId: 'p1' });
    
    const cleared = cache.clearByType('riskScore', 'p1');
    
    expect(cleared).toBe(1);
  });
});

// tests/frontend/services/CacheCoordinator.test.js
describe('CacheCoordinator', () => {
  test('should coordinate invalidation across all layers', async () => {
    const mockQueryClient = { invalidateQueries: jest.fn(() => Promise.resolve()) };
    const mockPortfolioCacheService = { clearPortfolio: jest.fn() };
    const mockUnifiedAdapterCache = { clearByType: jest.fn(() => 2) };
    const mockEventBus = { emit: jest.fn() };
    
    const coordinator = new CacheCoordinator(
      mockQueryClient, mockPortfolioCacheService, mockUnifiedAdapterCache, mockEventBus
    );
    
    const result = await coordinator.invalidateRiskData('test-portfolio');
    
    expect(result.success).toBe(true);
    expect(mockQueryClient.invalidateQueries).toHaveBeenCalled();
    expect(mockPortfolioCacheService.clearPortfolio).toHaveBeenCalledWith('test-portfolio');
    expect(mockUnifiedAdapterCache.clearByType).toHaveBeenCalledWith('riskScore', 'test-portfolio');
    expect(mockEventBus.emit).toHaveBeenCalledWith('risk-data-invalidated', expect.any(Object));
  });
});

// tests/integration/cache-coordination.test.js - INTEGRATION TEST
describe('Cache Coordination Integration', () => {
  test('should coordinate cache clearing across all layers in real scenario', async () => {
    // Test with real SessionServicesProvider setup
    // Verify that changing risk settings triggers coordinated cache clearing
    // Validate that UI components receive updated data
  });
});
```

#### ✅ **4. Adapter Factory Function Signature - CLEAN BREAKING CHANGE**

**Decision**: **Clean breaking change** - update all usage sites during cache architecture overhaul

**CURRENT USAGE** (throughout codebase):
```typescript
AdapterRegistry.getAdapter('riskScore', [portfolioId], () => new RiskScoreAdapter());
```

**NEW SIGNATURE** (clean, no backward compatibility):
```typescript
AdapterRegistry.getAdapter('riskScore', [portfolioId], 
  (unifiedCache) => new RiskScoreAdapter(unifiedCache), 
  unifiedCache
);
```

**RATIONALE**: 
- ✅ **Already updating everything** - 15+ hooks need changes anyway for coordinated caching
- ✅ **Cleaner architecture** - no complex fallback logic or optional parameters
- ✅ **Better developer experience** - single, clear pattern to follow
- ✅ **Prevents future confusion** - no legacy vs modern patterns to remember

**SOLUTION**: Clean AdapterRegistry implementation:

```typescript
// frontend/src/utils/AdapterRegistry.ts - CLEAN BREAKING CHANGE
static getAdapter<T>(
  type: string, 
  dependencies: unknown[], 
  factory: (unifiedCache: UnifiedAdapterCache) => T,
  unifiedCache: UnifiedAdapterCache
): T {
  const key = `${type}_${hashArgs(dependencies)}`;
  
  if (AdapterRegistry.adapters.has(key)) {
    return AdapterRegistry.adapters.get(key) as T;
  }
  
  // CLEAN: Single signature, no complexity
  const adapter = factory(unifiedCache);
  AdapterRegistry.adapters.set(key, adapter);
  return adapter;
}

// ALTERNATIVE APPROACH: Method overloading
static getAdapter<T>(type: string, dependencies: unknown[], factory: () => T): T;
static getAdapter<T>(
  type: string, 
  dependencies: unknown[], 
  factory: (unifiedCache?: UnifiedAdapterCache) => T,
  unifiedCache: UnifiedAdapterCache
): T;
static getAdapter<T>(
  type: string, 
  dependencies: unknown[], 
  factory: ((unifiedCache?: UnifiedAdapterCache) => T) | (() => T),
  unifiedCache?: UnifiedAdapterCache
): T {
  // Implementation handles both cases
  const key = `${type}_${hashArgs(dependencies)}`;
  
  if (AdapterRegistry.adapters.has(key)) {
    return AdapterRegistry.adapters.get(key) as T;
  }
  
  const adapter = unifiedCache ? 
    (factory as (unifiedCache: UnifiedAdapterCache) => T)(unifiedCache) :
    (factory as () => T)();
    
  AdapterRegistry.adapters.set(key, adapter);
  return adapter;
}
```

#### 🚨 **5. Hook Integration Missing Details**

**Issue**: Hooks need to pass UnifiedAdapterCache to adapters
```typescript
// CURRENT (in all hooks):
const adapter = useMemo(
  () => AdapterRegistry.getAdapter('riskScore', [portfolioId], () => new RiskScoreAdapter()),
  [portfolioId]
);

// NEEDED (in all hooks):
const { unifiedAdapterCache } = useSessionServices();
const adapter = useMemo(
  () => AdapterRegistry.getAdapter('riskScore', [portfolioId], 
    (cache) => new RiskScoreAdapter(cache), unifiedAdapterCache),
  [portfolioId, unifiedAdapterCache]
);
```

**Fix Required**: Update ALL hooks that use adapters (15+ files)

**SOLUTION**: Standardized hook pattern for adapter integration:

```typescript
// PATTERN FOR ALL HOOKS - Example: useRiskScore.ts
import { useSessionServices } from '../../../providers/SessionServicesProvider';

export const useRiskScore = () => {
  const { manager, unifiedAdapterCache } = useSessionServices(); // GET UNIFIED CACHE
  const currentPortfolio = useCurrentPortfolio();
  
  // UPDATED: Pass unifiedAdapterCache to adapter factory
  const riskScoreAdapter = useMemo(
    () => AdapterRegistry.getAdapter(
      'riskScore', 
      [currentPortfolio?.id || 'default'], 
      (unifiedCache) => new RiskScoreAdapter(unifiedCache), // NEW SIGNATURE
      unifiedAdapterCache // PASS UNIFIED CACHE
    ),
    [currentPortfolio?.id, unifiedAdapterCache] // ADD TO DEPENDENCIES
  );
  
  // Rest of hook unchanged...
};

// FILES TO UPDATE (15+ hooks):
// frontend/src/features/riskScore/hooks/useRiskScore.ts
// frontend/src/features/analysis/hooks/useRiskAnalysis.ts
// frontend/src/features/analysis/hooks/usePerformance.ts
// frontend/src/features/portfolio/hooks/usePortfolioSummary.ts
// frontend/src/features/analysis/hooks/useAnalysisReport.ts
// frontend/src/features/optimize/hooks/usePortfolioOptimization.ts
// frontend/src/features/whatIf/hooks/useWhatIfAnalysis.ts
// frontend/src/features/stockAnalysis/hooks/useStockAnalysis.ts
// frontend/src/features/portfolio/hooks/useInstantAnalysis.ts
// ... and all other hooks that use AdapterRegistry.getAdapter()

// BATCH UPDATE SCRIPT (for efficiency):
// find frontend/src/features -name "*.ts" -exec grep -l "AdapterRegistry.getAdapter" {} \;
// Then apply the pattern above to each file
```

#### 🚨 **6. Memory Leak Prevention**

**Issue**: EventBus listeners need proper cleanup
```typescript
// POTENTIAL MEMORY LEAK:
useEffect(() => {
  eventBus.on('event', handler);
  // Missing cleanup!
}, []);

// REQUIRED PATTERN:
useEffect(() => {
  const unsubscribe = eventBus.on('event', handler);
  return unsubscribe; // Cleanup on unmount
}, []);
```

**Fix Required**: Ensure all event listeners have proper cleanup

**SOLUTION**: Standardized event listener cleanup pattern:

```typescript
// SAFE EVENT LISTENER PATTERN - For all components using EventBus
const ComponentWithEventListener = () => {
  const { eventBus } = useSessionServices();
  const currentPortfolio = useCurrentPortfolio();
  const { refetch } = useDataHook();
  
  // CORRECT: Proper cleanup with useEffect
  useEffect(() => {
    if (!eventBus || !currentPortfolio?.id) return;
    
    const handleRiskDataInvalidated = ({ portfolioId }: { portfolioId: string }) => {
      if (portfolioId === currentPortfolio.id) {
        refetch();
      }
    };
    
    // Subscribe and get unsubscribe function
    const unsubscribe = eventBus.on('risk-data-invalidated', handleRiskDataInvalidated);
    
    // CRITICAL: Return cleanup function
    return () => {
      unsubscribe();
    };
  }, [eventBus, currentPortfolio?.id, refetch]);
  
  // Component render...
};

// COMPONENTS TO UPDATE (8 modern containers):
// frontend/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx
// frontend/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx
// frontend/src/components/dashboard/views/modern/PerformanceViewContainer.tsx
// frontend/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx
// frontend/src/components/dashboard/views/modern/RiskSettingsContainer.tsx
// frontend/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx
// frontend/src/components/dashboard/views/modern/StockLookupContainer.tsx
// frontend/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx

// MEMORY LEAK DETECTION (for testing):
// Add to EventBus class for debugging
export class EventBus {
  getActiveListenerCount(): number {
    return Array.from(this.listeners.values()).reduce((total, handlers) => total + handlers.size, 0);
  }
  
  getListenersByEvent(): Record<string, number> {
    const result: Record<string, number> = {};
    for (const [event, handlers] of this.listeners.entries()) {
      result[event] = handlers.size;
    }
    return result;
  }
}
```

#### 🚨 **7. Service Container Registration Order**

**Issue**: Dependencies must be registered in correct order
```typescript
// WRONG ORDER (will fail):
sessionServiceContainer.register('cacheCoordinator', () => 
  new CacheCoordinator(queryClient, portfolioCacheService, unifiedAdapterCache, eventBus)
);
sessionServiceContainer.register('eventBus', () => new EventBus());

// CORRECT ORDER:
sessionServiceContainer.register('eventBus', () => new EventBus());
sessionServiceContainer.register('unifiedAdapterCache', () => 
  new UnifiedAdapterCache(sessionServiceContainer.get('eventBus'))
);
sessionServiceContainer.register('cacheCoordinator', () => 
  new CacheCoordinator(/* all dependencies */)
);
```

**Fix Required**: Specify exact registration order in implementation

**SOLUTION**: Exact service registration order in SessionServicesProvider:

```typescript
// frontend/src/providers/SessionServicesProvider.tsx - EXACT ORDER REQUIRED
const services = useMemo<Services | null>(() => {
  if (!user) return null;
  
  const sessionServiceContainer = new ServiceContainer();
  
  // PHASE 1: FOUNDATION SERVICES (no dependencies)
  sessionServiceContainer.register('apiService', () => new APIService());
  
  // PHASE 2: SERVICES WITH SINGLE DEPENDENCIES
  sessionServiceContainer.register('claudeService', () => {
    const apiSvc = sessionServiceContainer.get<APIService>('apiService');
    return new ClaudeService({
      request: (apiSvc as any).request.bind(apiSvc),
      requestStream: (apiSvc as any).requestStream.bind(apiSvc),
    });
  });
  
  sessionServiceContainer.register('portfolioCacheService', () => 
    new PortfolioCacheService(sessionServiceContainer.get('apiService'))
  );
  
  // PHASE 3: COORDINATION SERVICES (specific order required)
  sessionServiceContainer.register('eventBus', () => new EventBus());
  
  sessionServiceContainer.register('unifiedAdapterCache', () => 
    new UnifiedAdapterCache(sessionServiceContainer.get('eventBus'))
  );
  
  // PHASE 4: COMPLEX SERVICES (multiple dependencies)
  sessionServiceContainer.register('portfolioManager', () =>
    new PortfolioManager(
      sessionServiceContainer.get('apiService'),
      sessionServiceContainer.get('claudeService'),
      sessionServiceContainer.get('portfolioCacheService') // Shared instance
    )
  );
  
  sessionServiceContainer.register('riskSettingsManager', () =>
    new RiskSettingsManager(
      sessionServiceContainer.get('portfolioCacheService'),
      sessionServiceContainer.get('apiService')
    )
  );
  
  // PHASE 5: COORDINATION ORCHESTRATOR (depends on all coordination services)
  sessionServiceContainer.register('cacheCoordinator', () => 
    new CacheCoordinator(
      queryClient, // From useQueryClient()
      sessionServiceContainer.get('portfolioCacheService'),
      sessionServiceContainer.get('unifiedAdapterCache'),
      sessionServiceContainer.get('eventBus')
    )
  );
  
  // PHASE 6: REMAINING SERVICES
  sessionServiceContainer.register('stockManager', () => {
    const { stockManager } = require('../chassis/services');
    return stockManager;
  });
  
  sessionServiceContainer.register('plaidPollingService', () => {
    const apiSvc = sessionServiceContainer.get<APIService>('apiService');
    return new PlaidPollingService({
      baseURL: (apiSvc as any).baseURL,
      request: (apiSvc as any).request.bind(apiSvc)
    });
  });
  
  // CRITICAL: Dependencies must be registered BEFORE they are used
  // Order matters for: eventBus → unifiedAdapterCache → cacheCoordinator
  
  // Get all services...
  return { /* all services */ };
}, [user?.id, queryClient]);
```

### 🔧 **Additional Implementation Requirements**

#### **8. Cache Key Standardization**

**SOLUTION**: Standardized cache key metadata interface and implementation:

```typescript
// frontend/src/types/cache.ts - NEW FILE
export interface CacheKeyMetadata {
  portfolioId: string;
  dataType: 'riskScore' | 'riskAnalysis' | 'performance' | 'portfolioSummary' | 'analysisReport' | 'optimization';
  version?: string;
  userId?: string;
  timestamp?: number;
}

export interface StandardCacheKey {
  key: string;
  metadata: CacheKeyMetadata;
}

// Utility function for generating standardized cache keys
export function generateStandardCacheKey(
  baseKey: string, 
  metadata: CacheKeyMetadata
): StandardCacheKey {
  const keyParts = [
    metadata.dataType,
    metadata.portfolioId,
    baseKey,
    metadata.version || 'v1'
  ].filter(Boolean);
  
  return {
    key: keyParts.join('_'),
    metadata: {
      ...metadata,
      timestamp: Date.now()
    }
  };
}

// UPDATE ALL ADAPTERS to use standardized keys:
// Example in RiskScoreAdapter:
private generateCacheKey(apiResponse: any): string {
  const baseKey = this.hashContent(apiResponse);
  const standardKey = generateStandardCacheKey(baseKey, {
    portfolioId: this.extractPortfolioId(apiResponse),
    dataType: 'riskScore',
    version: 'v1'
  });
  return standardKey.key;
}
```

#### **9. Performance Monitoring Integration**

**SOLUTION**: Comprehensive performance tracking in UnifiedAdapterCache:

```typescript
// Add to UnifiedAdapterCache class:
export interface CachePerformanceMetrics {
  hitRatio: number;
  avgResponseTime: number;
  totalRequests: number;
  errorRate: number;
  entriesByType: Record<string, { hits: number; misses: number; errors: number }>;
  recentOperations: Array<{
    timestamp: number;
    operation: 'hit' | 'miss' | 'clear' | 'error';
    key: string;
    responseTime?: number;
    dataType?: string;
  }>;
}

export class UnifiedAdapterCache {
  private performanceMetrics = {
    totalRequests: 0,
    totalHits: 0,
    totalMisses: 0,
    totalErrors: 0,
    responseTimes: [] as number[],
    operationLog: [] as any[],
    typeMetrics: new Map<string, { hits: number; misses: number; errors: number }>()
  };
  
  get<T>(key: string, factory: () => T, ttl: number, metadata?: any): T {
    const startTime = performance.now();
    this.performanceMetrics.totalRequests++;
    
    try {
      const entry = this.cache.get(key);
      const now = Date.now();
      
      if (entry && (now - entry.timestamp) < entry.ttl) {
        // Cache hit
        const responseTime = performance.now() - startTime;
        this.recordOperation('hit', key, responseTime, metadata?.dataType);
        return entry.value as T;
      }
      
      // Cache miss
      const value = factory();
      const responseTime = performance.now() - startTime;
      this.recordOperation('miss', key, responseTime, metadata?.dataType);
      
      // Cache the result
      this.cache.set(key, { value, timestamp: now, ttl, ...metadata });
      return value;
      
    } catch (error) {
      const responseTime = performance.now() - startTime;
      this.recordOperation('error', key, responseTime, metadata?.dataType);
      throw error;
    }
  }
  
  private recordOperation(
    operation: 'hit' | 'miss' | 'clear' | 'error',
    key: string,
    responseTime: number,
    dataType?: string
  ): void {
    // Update counters
    if (operation === 'hit') this.performanceMetrics.totalHits++;
    if (operation === 'miss') this.performanceMetrics.totalMisses++;
    if (operation === 'error') this.performanceMetrics.totalErrors++;
    
    // Track response times
    this.performanceMetrics.responseTimes.push(responseTime);
    if (this.performanceMetrics.responseTimes.length > 1000) {
      this.performanceMetrics.responseTimes.shift(); // Keep last 1000
    }
    
    // Track by type
    if (dataType) {
      if (!this.performanceMetrics.typeMetrics.has(dataType)) {
        this.performanceMetrics.typeMetrics.set(dataType, { hits: 0, misses: 0, errors: 0 });
      }
      const typeStats = this.performanceMetrics.typeMetrics.get(dataType)!;
      typeStats[operation === 'hit' ? 'hits' : operation === 'miss' ? 'misses' : 'errors']++;
    }
    
    // Log recent operations
    this.performanceMetrics.operationLog.push({
      timestamp: Date.now(),
      operation,
      key,
      responseTime,
      dataType
    });
    
    // Keep only last 100 operations
    if (this.performanceMetrics.operationLog.length > 100) {
      this.performanceMetrics.operationLog.shift();
    }
  }
  
  getPerformanceMetrics(): CachePerformanceMetrics {
    const totalRequests = this.performanceMetrics.totalRequests;
    const avgResponseTime = this.performanceMetrics.responseTimes.length > 0 ?
      this.performanceMetrics.responseTimes.reduce((a, b) => a + b, 0) / this.performanceMetrics.responseTimes.length : 0;
    
    return {
      hitRatio: totalRequests > 0 ? this.performanceMetrics.totalHits / totalRequests : 0,
      avgResponseTime,
      totalRequests,
      errorRate: totalRequests > 0 ? this.performanceMetrics.totalErrors / totalRequests : 0,
      entriesByType: Object.fromEntries(this.performanceMetrics.typeMetrics),
      recentOperations: [...this.performanceMetrics.operationLog]
    };
  }
}
```

#### **10. Graceful Degradation Strategy**

**SOLUTION**: Comprehensive fallback patterns for all coordination services:

```typescript
// PATTERN 1: Adapter Graceful Degradation
class RiskScoreAdapter {
  constructor(private unifiedCache?: UnifiedAdapterCache) {}
  
  transform(data: any): RiskScoreData {
    const cacheKey = this.generateCacheKey(data);
    
    // Try coordinated caching first
    if (this.unifiedCache) {
      try {
        return this.unifiedCache.get(
          cacheKey,
          () => this.transformInternal(data),
          this.TTL,
          { portfolioId: this.extractPortfolioId(data), dataType: 'riskScore' }
        );
      } catch (error) {
        frontendLogger.adapter.transformError('RiskScoreAdapter', error as Error, { 
          fallback: 'internal-cache',
          cacheKey 
        });
        // Fall through to internal cache
      }
    }
    
    // Fallback to internal cache
    return this.getFromInternalCache(cacheKey, () => this.transformInternal(data));
  }
  
  clearCache(): void {
    if (this.unifiedCache) {
      try {
        const cleared = this.unifiedCache.clearByType('riskScore');
        frontendLogger.adapter.transformSuccess('RiskScoreAdapter', `Unified cache cleared: ${cleared} entries`);
        return;
      } catch (error) {
        frontendLogger.adapter.transformError('RiskScoreAdapter', error as Error, { 
          fallback: 'internal-cache-clear' 
        });
      }
    }
    
    // Fallback to internal cache clearing
    this.internalCache.clear();
    frontendLogger.adapter.transformSuccess('RiskScoreAdapter', 'Internal cache cleared (fallback)');
  }
}

// PATTERN 2: Hook Graceful Degradation
export const useRiskScore = () => {
  const sessionServices = useSessionServices();
  const currentPortfolio = useCurrentPortfolio();
  
  const riskScoreAdapter = useMemo(() => {
    try {
      // Try coordinated approach
      if (sessionServices?.unifiedAdapterCache) {
        return AdapterRegistry.getAdapter(
          'riskScore',
          [currentPortfolio?.id || 'default'],
          (unifiedCache) => new RiskScoreAdapter(unifiedCache),
          sessionServices.unifiedAdapterCache
        );
      }
    } catch (error) {
      frontendLogger.adapter.transformError('useRiskScore', error as Error, { 
        fallback: 'legacy-adapter' 
      });
    }
    
    // Fallback to legacy approach
    return AdapterRegistry.getAdapter(
      'riskScore',
      [currentPortfolio?.id || 'default'],
      () => new RiskScoreAdapter() // No unified cache
    );
  }, [currentPortfolio?.id, sessionServices?.unifiedAdapterCache]);
  
  // Rest of hook unchanged...
};

// PATTERN 3: CacheCoordinator Graceful Degradation
export class CacheCoordinator {
  async invalidateRiskData(portfolioId: string): Promise<InvalidationResult> {
    const layersCleared: string[] = [];
    const errors: string[] = [];
    let partialSuccess = false;
    
    // Try each layer independently - don't fail if one fails
    
    // Layer 1: UnifiedAdapterCache
    try {
      const cleared = this.unifiedAdapterCache.clearByType('riskScore', portfolioId);
      layersCleared.push(`UnifiedAdapterCache:riskScore(${cleared})`);
      partialSuccess = true;
    } catch (error) {
      errors.push(`UnifiedAdapterCache failed: ${error.message}`);
    }
    
    // Layer 2: PortfolioCacheService  
    try {
      this.portfolioCacheService.clearPortfolio(portfolioId);
      layersCleared.push('PortfolioCacheService');
      partialSuccess = true;
    } catch (error) {
      errors.push(`PortfolioCacheService failed: ${error.message}`);
    }
    
    // Layer 3: TanStack Query
    try {
      await this.queryClient.invalidateQueries({ queryKey: riskScoreKey(portfolioId) });
      layersCleared.push('TanStackQuery');
      partialSuccess = true;
    } catch (error) {
      errors.push(`TanStack Query failed: ${error.message}`);
    }
    
    // Layer 4: AdapterRegistry (fallback clearing)
    try {
      AdapterRegistry.delete('riskScore', [portfolioId]);
      layersCleared.push('AdapterRegistry');
      partialSuccess = true;
    } catch (error) {
      errors.push(`AdapterRegistry failed: ${error.message}`);
    }
    
    return {
      success: partialSuccess && errors.length === 0,
      layersCleared,
      entriesCleared: layersCleared.length,
      errors,
      timestamp: Date.now()
    };
  }
}
```

### 📋 **Updated Implementation Checklist**

#### **Phase 1 Additions**:
- [ ] Update `frontend/src/chassis/services/index.ts` exports
- [ ] Add comprehensive error handling with `frontendLogger`
- [ ] Implement graceful degradation patterns
- [ ] Add performance monitoring interfaces
- [ ] Create unit tests for all 3 new services

#### **Phase 2 Additions**:
- [ ] Update ALL 15+ hooks to pass UnifiedAdapterCache
- [ ] Implement clean AdapterRegistry breaking change (simpler than backward compatibility)
- [ ] Add memory leak prevention for event listeners
- [ ] Standardize cache key formats across adapters
- [ ] Add integration tests for cross-layer coordination

#### **Phase 3 Additions**:
- [ ] Add cache performance monitoring dashboard
- [ ] Implement cache warming strategies
- [ ] Add developer debugging tools
- [ ] Create comprehensive E2E tests

### 🎯 **Revised Effort Estimate**

| Phase | Original Estimate | Additional Work | New Estimate |
|-------|------------------|-----------------|--------------|
| **Phase 1** | 13-19 hours | +8 hours (testing, error handling) | 21-27 hours |
| **Phase 2** | 20-29 hours | +12 hours (hook updates, compatibility) | 32-41 hours |
| **Phase 3** | 15-21 hours | +6 hours (monitoring, E2E tests) | 21-27 hours |

**New Total**: 74-95 hours (9-12 days of focused development)

### ✅ **Implementation Readiness Assessment**

**Ready to Proceed**: ✅ YES, with the identified additions
**Risk Level**: 🟡 MEDIUM (manageable with proper planning)
**Confidence**: 🟢 HIGH (comprehensive review completed)

---

**Document Status**: Complete Implementation Plan with All Gaps Addressed and Solutions Provided  
**Next Steps**: Begin Phase 1 implementation with confidence - all critical issues resolved
