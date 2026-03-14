# Caching Infrastructure Audit & Normalization Plan

## Executive Summary

This document captures critical caching infrastructure issues revealed during the investigation of a cache invalidation bug in the risk settings → risk analysis flow. The issues stem from the UI migration where legacy caching patterns coexist with modern patterns, creating inconsistencies and cache invalidation failures.

## 🚨 Critical Issues Discovered

### Issue #1: Service Instance Proliferation
**Problem**: Multiple instances of the same service class being created independently
**Root Cause**: Legacy direct instantiation patterns coexisting with modern dependency injection
**Impact**: Cache clearing operations fail because they target different instances than those serving data

**Specific Example**:
- `PortfolioManager` creates its own `PortfolioCacheService` instance (line 111)
- `SessionServicesProvider` creates a separate `PortfolioCacheService` instance (lines 160-162)
- `useRiskSettings` clears cache in Instance A, but API calls use Instance B
- Result: Cache invalidation appears to work but has no effect

### Issue #2: Inconsistent Cache Key Strategies
**Problem**: Cache keys not properly reflecting the actual data being cached
**Root Cause**: Adapters not updated when underlying data structures change
**Impact**: Cache keys remain the same even when underlying data changes, causing stale data to be served

**Specific Example**:
- `PortfolioSummaryAdapter` cache key used `riskScore?.score` (undefined)
- Should use `riskScore?.overall_risk_score` (the actual field)
- Result: Same cache key generated for different risk scores, serving stale summary data

### Issue #3: Mixed Caching Architecture Patterns
**Problem**: Three different caching approaches operating independently
**Root Cause**: Evolution from legacy to modern patterns without consolidation
**Impact**: Complex debugging, inconsistent behavior, potential race conditions

**Current Caching Layers**:
1. **TanStack Query** - Query-level caching with invalidation
2. **AdapterRegistry** - Adapter instance caching with 30-minute TTL
3. **PortfolioCacheService** - Service-level caching with version-based keys

## 🔍 Audit Results

### Caching Architecture Audit

#### Current Caching Layers Identified

**1. TanStack Query (React Query) - Query-Level Caching**
- **Location**: `frontend/src/providers/QueryProvider.tsx`
- **Strategy**: Unified TTL via `REACT_APP_PORTFOLIO_CACHE_TTL` environment variable
- **Configuration**: `frontend/src/config/queryConfig.ts` with multiplier-based TTL
- **Scope**: Global query caching with user-scoped keys
- **TTL Management**: Environment-controlled with multipliers (0.2x to 288x base TTL)
- **Invalidation**: Manual via `queryClient.invalidateQueries()`

**2. AdapterRegistry - Adapter Instance Caching**
- **Location**: `frontend/src/utils/AdapterRegistry.ts`
- **Strategy**: Singleton adapter instances with parameterized cache keys
- **Scope**: Prevents duplicate adapter creation, user-scoped via context args
- **TTL Management**: No automatic expiration, manual cleanup via `clear()` or `delete()`
- **Invalidation**: Manual via `AdapterRegistry.delete()` or `clear()`

**3. PortfolioCacheService - Service-Level Caching**
- **Location**: `frontend/src/chassis/services/PortfolioCacheService.ts`
- **Strategy**: Version-based cache keys with content-aware invalidation
- **Scope**: Portfolio-specific caching with version tracking
- **TTL Management**: No automatic expiration mentioned
- **Invalidation**: Manual via `clearPortfolio()` method

**4. Adapter Internal Caches - Component-Level Caching**
- **Strategy**: 30-minute TTL within individual adapter instances
- **Examples**: `RiskScoreAdapter`, `RiskAnalysisAdapter`, `PortfolioSummaryAdapter`
- **TTL Management**: Unified via `getCacheTTL()` utility
- **Invalidation**: Manual via adapter's `clearCache()` method

**5. Legacy Service Singletons - Global Instance Caching**
- **Location**: `frontend/src/chassis/services/index.ts`
- **Strategy**: Global singleton instances (legacy pattern)
- **Examples**: `apiService`, `claudeService`, `stockCacheService`, `portfolioManager`
- **Issue**: Coexists with modern SessionServicesProvider pattern

## 🔍 COMPREHENSIVE DEEP AUDIT - ALL CACHING LAYERS

### 1. React Component-Level Caching & Memoization

#### 1.1 React.memo() Usage (Component Memoization)
**Purpose**: Prevent unnecessary component re-renders
**Locations Found**:
- `PortfolioOverviewContainer.tsx` (line 148)
- `RiskAnalysisModernContainer.tsx` (line 353)
- `StockResearchViewContainer.tsx` (line 205) - Legacy
- `RiskScoreViewContainer.tsx` (line 128) - Legacy
- `RiskAnalysisViewContainer.tsx` (line 143) - Legacy
- `PortfolioOptimizationViewContainer.tsx` (line 161) - Legacy
- `PerformanceAnalyticsViewContainer.tsx` (line 146) - Legacy
- `AnalysisReportViewContainer.tsx` (line 159) - Legacy
- `WhatIfAnalysisViewContainer.tsx` (line 161) - Legacy
- `RiskSettingsViewContainer.tsx` (line 186) - Legacy

**Conflict Risk**: HIGH - Can prevent updates when props don't change reference but content changes

#### 1.2 useMemo() Usage (Value Memoization)
**Purpose**: Expensive computation caching within components
**Critical Locations**:
- `SessionServicesProvider.tsx` (line 132) - Service container creation
- `PortfolioOverview.tsx` (line 454) - Metrics calculation with `[data, data?.summary?.riskScore]`
- `RiskSettingsViewContainer.tsx` (line 115) - Enhanced risk data aggregation
- `DashboardContainer.tsx` (line 169) - Portfolio summary object
- All feature hooks using `AdapterRegistry.getAdapter()` pattern

**Conflict Risk**: MEDIUM - Can cache stale computations if dependencies not properly managed

#### 1.3 useCallback() Usage (Function Memoization)
**Purpose**: Function reference stability to prevent child re-renders
**Extensive Usage**: Found in 50+ components for event handlers and API calls
**Conflict Risk**: LOW - Generally safe but can mask dependency issues

### 2. Browser Storage Mechanisms

#### 2.1 SessionStorage (Secure Storage)
**Location**: `services/SecureStorage.ts`
**Purpose**: Portfolio metadata storage with versioning
**Strategy**: Session-scoped, versioned data with expiration
**Scope**: Single browser tab, cleared on tab close
**Conflict Risk**: LOW - Session-scoped, no cross-tab conflicts

#### 2.2 LocalStorage (User Preferences)
**Locations**:
- `PortfolioOverview.tsx` (lines 938, 2506) - View mode preferences, portfolio settings
- `PerformanceView.tsx` (lines 322, 358) - Performance preferences with debouncing
- `authStore.ts` (lines 425-426) - Cross-tab auth token sync
**Purpose**: Persistent user preferences across sessions
**Conflict Risk**: MEDIUM - Can persist stale preferences, cross-tab sync issues

#### 2.3 Cross-Tab Synchronization
**Location**: `authStore.ts` (lines 372-408)
**Mechanisms**: localStorage events + BroadcastChannel API
**Purpose**: Authentication state sync across browser tabs
**Conflict Risk**: MEDIUM - Race conditions during concurrent tab operations

### 3. In-Memory Caching Structures

#### 3.1 JavaScript Map/Set Collections
**Adapter Internal Caches**:
- `PortfolioSummaryAdapter.ts` (line 221) - `Map<string, { data: any; timestamp: number }>`
- `RiskScoreAdapter.ts` (line 241) - `Map<string, { data: any; timestamp: number }>`
- `PerformanceAdapter.ts` (line 340) - `Map<string, { data: any; timestamp: number }>`
- `PortfolioOptimizationAdapter.ts` (line 104) - `Map<string, { data: OptimizationData; timestamp: number }>`
- `AnalysisReportAdapter.ts` (line 191) - `Map<string, { data: any; timestamp: number }>`
- `RiskAnalysisAdapter.ts` (line 289) - `Map<string, { data: any; timestamp: number }>`

**Service-Level Caches**:
- `PortfolioCacheService.ts` (lines 75-76) - `Map<string, CacheEntry>` + `Map<string, Promise<any>>`
- `APIService.ts` (line 64) - `Map<string, Promise<any>>` for request deduplication
- `AdapterRegistry.ts` (line 191) - `Map<string, any>` for adapter instances

**Component-Level Collections**:
- `usePlaidPolling.ts` (line 73) - `Set<string>` for active polling tokens
- `HoldingsView.tsx` (line 654) - `Set` for unique sectors

**Conflict Risk**: HIGH - Multiple Map instances can hold conflicting data

#### 3.2 WeakMap/WeakSet Usage
**Location**: `AdapterRegistry.ts` (lines 15, 112)
**Purpose**: Circular reference detection during serialization
**Conflict Risk**: LOW - Used for validation only

### 4. State Management Caching

#### 4.1 Zustand Store Caching
**Locations**:
- `authStore.ts` - Authentication state with cross-tab sync
- `portfolioStore.ts` - Portfolio state management
- `uiStore.ts` - UI preferences and state

**Caching Behavior**: Persistent in-memory state with selective subscriptions
**Conflict Risk**: MEDIUM - State can become stale if not properly invalidated

#### 4.2 TanStack Query (React Query) Caching
**Location**: `providers/QueryProvider.tsx`
**Strategy**: Multi-layered query caching with TTL management
**Configuration**: Environment-controlled TTL with multipliers (0.2x to 288x)
**Scope**: User-scoped query keys for multi-user isolation
**Conflict Risk**: MEDIUM - Complex invalidation patterns, user isolation critical

### 5. Network-Level Caching

#### 5.1 HTTP Request Deduplication
**Location**: `APIService.ts` (line 64)
**Purpose**: Prevent duplicate concurrent requests
**Strategy**: `Map<string, Promise<any>>` keyed by request signature
**Conflict Risk**: LOW - Short-lived, request-scoped

#### 5.2 Service Worker Caching (If Present)
**Status**: Not detected in current audit
**Potential Risk**: Would add another caching layer if implemented

### 6. Adapter-Level Caching Patterns

#### 6.1 AdapterRegistry Instance Caching
**Location**: `utils/AdapterRegistry.ts`
**Purpose**: Prevent duplicate adapter instantiation
**Strategy**: Singleton pattern with parameterized keys
**Scope**: Application-wide, user-scoped via context arguments
**Conflict Risk**: HIGH - Instance proliferation if not properly managed

#### 6.2 Individual Adapter Internal Caches
**Pattern**: Each adapter has its own 30-minute TTL cache
**Strategy**: Content-based cache keys with timestamp validation
**Scope**: Adapter instance-specific
**Conflict Risk**: HIGH - Multiple cache layers for same data

### 7. Development & Debugging Caches

#### 7.1 React DevTools Caching
**Purpose**: Component state inspection and time-travel debugging
**Conflict Risk**: LOW - Development-only

#### 7.2 TanStack Query DevTools
**Purpose**: Query cache visualization and debugging
**Conflict Risk**: LOW - Development-only

### 8. Environment-Specific Caching

#### 8.1 Development Environment Caching
**Strategy**: 0.2x TTL multiplier for faster feedback
**All cache layers scaled down proportionally
**Conflict Risk**: LOW - Consistent scaling

#### 8.2 Test Environment Caching
**Strategy**: 0ms TTL for predictable behavior
**All caching disabled for test isolation
**Conflict Risk**: NONE - No caching in tests

#### 8.3 Production Environment Caching
**Strategy**: Full TTL multipliers for optimal performance
**All cache layers operating at designed capacity
**Conflict Risk**: HIGH - Full complexity of all cache interactions

## 🚨 CRITICAL CACHING CONFLICT ZONES

### Zone 1: Multi-Instance Service Caches
**Components**: PortfolioCacheService, APIService, PortfolioManager
**Risk**: Different instances caching different versions of same data
**Impact**: Cache invalidation failures, stale data serving

### Zone 2: React Memoization vs Data Updates
**Components**: React.memo + useMemo with complex dependencies
**Risk**: UI not updating when underlying data changes
**Impact**: Users see stale information despite fresh API data

### Zone 3: Cross-Layer Cache Coordination
**Components**: TanStack Query + PortfolioCacheService + Adapter Internal Caches
**Risk**: Invalidating one layer while others serve stale data
**Impact**: Inconsistent data across UI components

### Zone 4: Browser Storage vs In-Memory State
**Components**: localStorage preferences + Zustand state + component state
**Risk**: Conflicting sources of truth for user preferences
**Impact**: UI state inconsistencies, preference loss

### Zone 5: Adapter Cache Key Conflicts
**Components**: Multiple adapters using similar cache key generation
**Risk**: Cache key collisions or inconsistent field usage
**Impact**: Wrong data returned for cache hits

## 📊 CACHING LAYER INTERACTION MATRIX

| Layer | TanStack Query | AdapterRegistry | Adapter Internal | PortfolioCacheService | React Memo | Browser Storage |
|-------|---------------|-----------------|------------------|----------------------|------------|-----------------|
| **TanStack Query** | ✅ Self | 🔄 Invalidates | 🔄 Triggers | 🔄 Calls | ⚠️ May conflict | 🔄 May read |
| **AdapterRegistry** | 🔄 Used by | ✅ Self | 🔄 Manages | ❌ Independent | ❌ Independent | ❌ Independent |
| **Adapter Internal** | 🔄 Serves | 🔄 Managed by | ✅ Self | ❌ Independent | ⚠️ May conflict | ❌ Independent |
| **PortfolioCacheService** | 🔄 Serves | ❌ Independent | ❌ Independent | ✅ Self | ⚠️ May conflict | ❌ Independent |
| **React Memo** | ⚠️ May conflict | ❌ Independent | ⚠️ May conflict | ⚠️ May conflict | ✅ Self | ⚠️ May conflict |
| **Browser Storage** | 🔄 May write | ❌ Independent | ❌ Independent | ❌ Independent | ⚠️ May conflict | ✅ Self |

**Legend**: ✅ Self-contained | 🔄 Coordinated interaction | ⚠️ Potential conflict | ❌ Independent operation

#### Cache Configuration Architecture

**Unified TTL Management**:
- **Base Configuration**: `frontend/src/utils/cacheConfig.ts`
- **Environment Variable**: `REACT_APP_PORTFOLIO_CACHE_TTL` (default: 5 minutes)
- **Multiplier System**: Different data types use proportional multipliers
  - Real-time data: 0.2x base (minimum 1 minute)
  - Portfolio data: 1.0x base
  - User preferences: 3.0x base
  - Reference data: 12.0x base
  - Static data: 288.0x base (24 hours at 5min base)

### Service Instance Proliferation Audit

#### Critical Instance Proliferation Issues

**1. PortfolioCacheService - CONFIRMED ISSUE**
- **SessionServicesProvider Instance**: Lines 160-162 in `SessionServicesProvider.tsx`
- **PortfolioManager Instance**: Line 111 in `PortfolioManager.ts` (FIXED)
- **Legacy Singleton Instance**: Line 56 in `chassis/services/index.ts`
- **Impact**: Cache clearing operations target different instances than data serving

**2. APIService - MULTIPLE INSTANCES DETECTED**
- **SessionServicesProvider Instance**: Line 148 in `SessionServicesProvider.tsx`
- **AuthStore Instance**: Line 246 in `stores/authStore.ts`
- **useAuthFlow Instance**: Line 67 in `features/auth/hooks/useAuthFlow.ts`
- **Legacy Singleton Instance**: Line 36 in `chassis/services/index.ts`
- **Impact**: Potential authentication state inconsistencies

**3. PortfolioManager - MULTIPLE INSTANCES DETECTED**
- **SessionServicesProvider Instance**: Lines 163-168 in `SessionServicesProvider.tsx`
- **Legacy Singleton Instance**: Line 61 in `chassis/services/index.ts`
- **Impact**: Different manager instances may have different state

**4. ClaudeService - MULTIPLE INSTANCES DETECTED**
- **SessionServicesProvider Instance**: Lines 151-158 in `SessionServicesProvider.tsx`
- **Legacy Singleton Instance**: Line 41 in `chassis/services/index.ts`
- **Impact**: AI service state inconsistencies

**5. AuthManager - POTENTIAL ISSUE**
- **useAuthFlow Instance**: Line 68 in `features/auth/hooks/useAuthFlow.ts`
- **Pattern**: Direct instantiation in hook, not using SessionServicesProvider
- **Impact**: Authentication state management inconsistencies

#### Services Following Correct Patterns

**✅ Properly Using SessionServicesProvider**:
- All modern hooks in `features/` directory use `useSessionServices()`
- RiskSettingsManager, StockManager properly registered in SessionServicesProvider
- PlaidPollingService properly registered and dependency-injected

**✅ Adapter Pattern Compliance**:
- All adapters use `AdapterRegistry.getAdapter()` pattern correctly
- Proper cache key generation with portfolio/user context
- Consistent factory function pattern

#### Legacy vs Modern Pattern Coexistence Issues

**Legacy Pattern (Problematic)**:
```typescript
// Direct singleton import and usage
import { portfolioManager } from '../chassis/services/index';
const manager = new PortfolioManager(apiService, claudeService); // Direct instantiation
```

**Modern Pattern (Correct)**:
```typescript
// Dependency injection via SessionServicesProvider
const { manager } = useSessionServices();
```

**Files Still Using Legacy Patterns**:
- `stores/authStore.ts` - Direct APIService instantiation
- `features/auth/hooks/useAuthFlow.ts` - Direct service instantiation
- `chassis/services/index.ts` - Global singleton exports (legacy compatibility)

## 📋 Identified Issues Summary

### 🚨 Critical Issues (Immediate Action Required)

**1. Service Instance Proliferation**
- **Severity**: HIGH
- **Impact**: Cache invalidation failures, state inconsistencies
- **Affected Services**: PortfolioCacheService (FIXED), APIService, PortfolioManager, ClaudeService, AuthManager
- **Root Cause**: Legacy singleton pattern coexisting with modern dependency injection

**2. Inconsistent Cache Key Generation**
- **Severity**: MEDIUM
- **Impact**: Stale data served even when underlying data changes
- **Example**: PortfolioSummaryAdapter using wrong risk score field (FIXED)
- **Root Cause**: Adapters not updated when data structures evolve

**3. Manual Cache Invalidation Complexity**
- **Severity**: MEDIUM
- **Impact**: Error-prone cache clearing, missed invalidations
- **Layers Affected**: TanStack Query, AdapterRegistry, PortfolioCacheService, Adapter Internal Caches
- **Root Cause**: No unified cache invalidation strategy

### ⚠️ Architectural Issues (Design Debt)

**4. Mixed Caching Architecture Patterns**
- **Severity**: MEDIUM
- **Impact**: Complex debugging, inconsistent behavior, maintenance overhead
- **Patterns**: 5 different caching layers with different strategies
- **Root Cause**: Evolution from legacy to modern without consolidation

**5. Legacy Service Pattern Persistence**
- **Severity**: LOW-MEDIUM
- **Impact**: Confusion, potential future bugs, maintenance complexity
- **Files**: `chassis/services/index.ts`, `stores/authStore.ts`, `features/auth/hooks/useAuthFlow.ts`
- **Root Cause**: Incomplete migration to SessionServicesProvider pattern

**6. Cache TTL Configuration Fragmentation**
- **Severity**: LOW
- **Impact**: Inconsistent cache behavior across components
- **Issue**: Some components use custom TTL multipliers outside standard config
- **Examples**: `usePlaid.ts` (Infinity), `useChat.ts` (2.0x), custom multipliers in various hooks

### 🔧 Technical Debt Issues

**7. Adapter Cache Key Inconsistencies**
- **Severity**: LOW-MEDIUM
- **Impact**: Potential cache misses or incorrect cache hits
- **Issue**: Different adapters may use different field names for same data
- **Example**: Risk score field variations across adapters

**8. Missing Cache Invalidation Automation**
- **Severity**: LOW
- **Impact**: Manual cache management burden, potential for human error
- **Issue**: No automatic cache invalidation on data mutations
- **Opportunity**: Could implement reactive cache invalidation

**9. Cache Layer Coordination Issues**
- **Severity**: LOW
- **Impact**: Race conditions, timing-dependent bugs
- **Issue**: Multiple cache layers operating independently
- **Example**: TanStack Query invalidation triggering before adapter cache clearing

### 📊 Performance Issues

**10. Potential Memory Leaks**
- **Severity**: LOW-MEDIUM
- **Impact**: Memory usage growth over time
- **Issue**: AdapterRegistry and some caches lack automatic cleanup
- **Risk**: Long-running sessions may accumulate stale cache entries

**11. Cache Redundancy**
- **Severity**: LOW
- **Impact**: Unnecessary memory usage, complex invalidation
- **Issue**: Multiple cache layers caching similar data
- **Example**: TanStack Query + PortfolioCacheService + Adapter Internal Cache

### 🎯 Migration-Specific Issues

**12. UI Migration Incomplete Service Adoption**
- **Severity**: MEDIUM
- **Impact**: Inconsistent service usage between UI generations
- **Issue**: Modern UI uses SessionServicesProvider, legacy patterns still exist
- **Risk**: Future bugs as legacy patterns are gradually removed

**13. Cache Strategy Evolution Debt**
- **Severity**: LOW-MEDIUM
- **Impact**: Maintenance complexity, potential for configuration drift
- **Issue**: Cache configuration spread across multiple files and patterns
- **Opportunity**: Consolidate into unified cache strategy

## 🎯 Normalization Recommendations

### Phase 1: Critical Fixes (Immediate - 1-2 weeks)

**1.1 Eliminate Service Instance Proliferation**
- Audit and fix all remaining multiple service instances
- Migrate `authStore.ts` and `useAuthFlow.ts` to use SessionServicesProvider
- Remove or deprecate legacy singleton exports in `chassis/services/index.ts`
- Add runtime validation to detect multiple instances in development

**1.2 Standardize Cache Key Generation**
- Create unified cache key generation utilities
- Audit all adapters for consistent field usage
- Implement cache key validation in development mode
- Document cache key standards and patterns

**1.3 Implement Unified Cache Invalidation**
- Create centralized cache invalidation service
- Implement automatic invalidation on data mutations
- Add cache invalidation debugging tools
- Standardize invalidation patterns across all hooks

### Phase 2: Architecture Consolidation (Medium-term - 1-2 months)

**2.1 Cache Layer Consolidation**
- Evaluate necessity of each caching layer
- Consolidate overlapping cache functionality
- Implement hierarchical cache strategy
- Reduce cache layer complexity from 5 to 2-3 layers

**2.2 Legacy Pattern Migration**
- Complete migration from legacy singleton pattern
- Remove legacy service exports
- Update all remaining direct service instantiations
- Implement migration validation tools

**2.3 Cache Configuration Unification**
- Consolidate all cache TTL configurations
- Implement unified cache policy management
- Standardize cache multiplier usage
- Create cache configuration validation

### Phase 3: Performance & Automation (Long-term - 2-3 months)

**3.1 Automatic Cache Management**
- Implement reactive cache invalidation
- Add automatic cache cleanup and garbage collection
- Implement cache warming strategies
- Add cache performance monitoring

**3.2 Developer Experience Improvements**
- Create cache debugging tools and visualizations
- Implement cache testing utilities
- Add cache performance profiling
- Create cache architecture documentation

**3.3 Advanced Cache Strategies**
- Implement intelligent cache prefetching
- Add cache compression for large datasets
- Implement cache persistence across sessions
- Add cache analytics and optimization

### Success Metrics

**Immediate (Phase 1)**:
- Zero service instance proliferation issues
- 100% consistent cache key generation
- Unified cache invalidation across all components
- Elimination of cache-related bugs

**Medium-term (Phase 2)**:
- Reduced cache layer complexity (5→3 layers)
- Complete legacy pattern elimination
- Unified cache configuration management
- Improved cache debugging capabilities

**Long-term (Phase 3)**:
- Automatic cache management with minimal manual intervention
- Advanced cache performance optimization
- Comprehensive cache monitoring and analytics
- Developer-friendly cache tooling and documentation

---

**Document Status**: In Progress - Conducting Audits
**Last Updated**: $(date)
**Next Steps**: Complete caching architecture audit, then service proliferation audit
