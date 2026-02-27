# Frontend Refactor Phase 3: Architectural Stability Plan

## Executive Summary

This document outlines the comprehensive plan for Phase 3 refactoring of the React TypeScript frontend, focusing on eliminating architectural fragility and establishing stable, maintainable patterns. The analysis has identified critical risks that pose immediate threats to system stability, performance, and security.

**Status:** CRITICAL - Multiple architectural risks require immediate attention  
**Estimated Effort:** 3-4 weeks engineering time  
**Priority:** Emergency fixes required before production deployment

🔁 Flow Regression Guardrails

Ensure no regression to the following flows:
	•	Google sign-in → portfolio load → component analysis (user-driven)
	•	Plaid link → refresh portfolio → component analysis (user-driven)
	•	Manual portfolio upload → component analysis (user-driven)
Add snapshots or flow tests to guard these.

---

## 🚨 CRITICAL ARCHITECTURAL RISKS IDENTIFIED

### **1. Service Instance Recreation Anti-Pattern**
**Severity:** CRITICAL  
**Files Affected:**
- `hooks/useRiskAnalysis.ts:10` 
- `hooks/useFactorAnalysis.ts:10`
- `hooks/useRiskScore.ts:10`
- `hooks/usePerformance.ts:10`
- `hooks/usePortfolioAnalysis.ts:10`
- `providers/SessionServicesProvider.tsx:37-40`

**Current Problem:**
```typescript
// ❌ PROBLEMATIC: New adapter instances on every render
export const useRiskAnalysis = () => {
  const adapter = new RiskAnalysisAdapter(); // Created every render
  // ... rest of hook
};
```

**Impact:** Memory leaks, cache invalidation, degraded performance  
**Fix Required:** Implement stable adapter registry keyed with proper memoization

### **2. Polling Without Cleanup**
**Severity:** CRITICAL  
**Files Affected:**
- `auth/GoogleSignInButton.tsx:47-52`
- `plaid/PlaidLinkButton.tsx:68,75,83`

**Current Problem:**
```typescript
// ❌ PROBLEMATIC: Polling continues after component unmount
setTimeout(() => {
  setPollCount(prev => prev + 1);
  // No cleanup mechanism
}, 500);
```

**Impact:** Memory leaks, resource exhaustion, background processing  
**Fix Required:** Implement cancellable polling with AbortController

### **3. Security Vulnerability - Hardcoded Secrets**
**Severity:** CRITICAL  
**Files Affected:**
- `chassis/services/APIService.ts:20-25`
- `services/frontendLogger.ts:67`

**Current Problem:** API endpoints and configuration exposed in frontend code  
**Impact:** Security breach through exposed configuration  
**Fix Required:** Environment-based configuration loading

---

## 🔴 HIGH SEVERITY RISKS

### **4. Shared Mutable State Without Protection**
**Files Affected:**
- `chassis/managers/PortfolioManager.ts:17`
- `stores/authStore.ts:138`

**Problem:** Multiple components sharing mutable state without synchronization  
**Impact:** State corruption, race conditions, UI inconsistency
**Fix Required:** Replace shared mutable objects (e.g. PortfolioManager, store-bound service instances) with Zustand-based state containers or adapter injection via AdapterRegistry. Where shared state must exist, enforce strict mutation boundaries using immer or zod schema-validated updates.

### **5. Tight Routing-State Coupling**
**Files Affected:**
- `dashboard/DashboardRouter.tsx:94-185`
- `dashboard/DashboardContainer.tsx:115-122`

**Problem:** Business logic tightly coupled to routing decisions  
**Impact:** Navigation failures corrupt application state
**Fix Required:** Refactor routing code to trigger intents rather than contain logic directly. Wrap with error boundaries to isolate failures.

### **6. Missing Cleanup in Event Listeners**
**Files Affected:**
- `stores/authStore.ts:138`
- `stores/uiStore.ts:69-71`

**Problem:** Event listeners and timers never cleaned up  
**Impact:** Memory leaks in long-running applications
**Fix Required:** Refactor all listener-attaching useEffect calls to return a cleanup function. Where persistent subscriptions are needed (e.g. auth changes), centralize listener registration in a singleton EventBus or at the top level of the app lifecycle (App.tsx or RootStore).

### **7. Unstable Hook Return Objects**
**Files Affected:** All custom hooks in `hooks/` directory

**Problem:** New objects returned on every call bypass React optimizations  
**Impact:** Cascading re-renders, performance degradation
**Fix Required:** Memoize all hook return values using useMemo, useCallback, or stable return wrappers. 

---

## 🟡 MEDIUM-HIGH SEVERITY RISKS

### **8. Circular Dependencies**
**Location:** Service layer throughout `chassis/` directory  
**Problem:** Service interdependencies create initialization order issues
**Fix Required:** Perform a madge audit. Refactor services into thin interfaces + injected implementations.

### **9. Data Inconsistency Across Layers**
**Problem:** Multiple sources of truth for portfolio data (store vs cache)
**Fix Required:** Define a single source of truth per data domain. Source = Zustand store. Convert caches to reactive selectors or usePortfolioData() hook that always pulls from the normalized store.

### **10. Route-Dependent Race Conditions**
**Files:** `hooks/usePortfolioSummary.ts:30-34`  
**Problem:** Concurrent API calls without cancellation tokens
**Fix Required:** All useEffect hooks that trigger API calls should use: AbortController for cancellation, defensive guards for sale state, shared useCancelableRequest() wrapper.

---

## PHASE 3 REFACTOR PLAN

### **WEEK 1: EMERGENCY FIXES (Critical Severity)**

#### **Day 1-2: Fix Service Instance Recreation**
- [ ] Create `AdapterRegistry` singleton for stable adapter instances
- [ ] Refactor all hooks to use parameter-aware memoized adapters
- [ ] Implement proper adapter lifecycle management (per user/session/portfolio context)
- [ ] Introduce lightweight `ServiceContainer` (see Dependency-Injection pattern) to expose per-user + portfolio singletons for `PortfolioManager`, `PortfolioCacheService`, and `APIService`, eliminating duplicate instances and enabling shared cache hits.

**Target Files:**
```
hooks/useRiskAnalysis.ts
hooks/useFactorAnalysis.ts  
hooks/useRiskScore.ts
hooks/usePerformance.ts
hooks/usePortfolioAnalysis.ts
```

**Implementation Pattern:**
```typescript
// ✅ CORRECT: Stable, parameterized adapter instances
/**
 * Registry for managing singleton adapter instances to prevent memory leaks and unnecessary recreation.
 * Provides parameterized caching based on adapter type and context arguments.
 */
class AdapterRegistry {
  private static instances = new Map<string, any>();

  /**
   * Retrieves or creates a cached adapter instance based on type and args.
   * @param type Unique type key (e.g. 'risk', 'performance', 'portfolio')
   * @param args Array of args used to differentiate instances (e.g. [userId, portfolioId])
   * @param factory Function that returns a new adapter instance
   * @returns Cached or newly created adapter instance
   */
  static getAdapter<T>(type: string, args: any[], factory: () => T): T {
    const key = `${type}::${JSON.stringify(args)}`;
    if (!this.instances.has(key)) {
      this.instances.set(key, factory());
    }
    return this.instances.get(key);
  }

  /**
   * Clears all cached adapter instances. Use during logout or session reset.
   */
  static clear(): void {
    this.instances.clear();
  }

  /**
   * Removes a specific adapter instance from cache.
   * @param type Adapter type key
   * @param args Context arguments used for the instance
   */
  static delete(type: string, args: any[]): void {
    const key = `${type}::${JSON.stringify(args)}`;
    this.instances.delete(key);
  }
}

/**
 * Hook for accessing risk analysis functionality with stable adapter instances.
 * @returns Memoized risk analysis adapter instance and query state
 */
export const useRiskAnalysis = () => {
  const { manager, cache } = useSessionServices();
  const currentPortfolio = useCurrentPortfolio();
  
  const riskAdapter = useMemo(
    () => AdapterRegistry.getAdapter('risk', [currentPortfolio?.id || 'default'], () => new RiskAnalysisAdapter()),
    [currentPortfolio?.id]
  );

  // Use cache service for risk analysis data
  const queryFn = useCallback(async () => {
    if (!currentPortfolio) return null;
    const result = await cache.getRiskAnalysis(currentPortfolio);
    return riskAdapter.transform(result);
  }, [cache, currentPortfolio, riskAdapter]);

  // ... rest of useQuery logic
};
```

#### **Day 3: Fix Polling and Cleanup Issues**
- [ ] Implement cancellable polling in GoogleSignInButton
- [ ] Add AbortController support to PlaidLinkButton
- [ ] Create reusable polling hook with cleanup
- [ ] Migrate legacy Pattern B components (`TabbedPortfolioAnalysis.tsx`, `RiskAnalysisChat.tsx`) to the standard Hook → Manager → Cache → APIService flow or remove them entirely.

**Implementation Pattern:**
```typescript
// ✅ CORRECT: Cancellable polling
/**
 * Hook for implementing cancellable polling operations with proper cleanup.
 * Automatically aborts polling when component unmounts or dependencies change.
 * @param pollFn Function that returns true when polling should stop
 * @param interval Polling interval in milliseconds
 */
const useCancellablePolling = (pollFn: () => boolean, interval: number) => {
  useEffect(() => {
    const abortController = new AbortController();
    
    /**
     * Recursive polling function that respects abort signals
     */
    const poll = async () => {
      if (abortController.signal.aborted) return;
      if (pollFn()) return;
      setTimeout(poll, interval);
    };
    
    poll();
    return () => abortController.abort();
  }, [pollFn, interval]);
};
```

#### **Day 4-5: Security Fixes**
- [ ] Remove hardcoded configuration from frontend
- [ ] Implement environment-based config loading
- [ ] Add proper secret management

### **WEEK 2: HIGH PRIORITY FIXES**

#### **Day 1-2: Stabilize Hook Returns**
- [ ] Add memoization to all custom hook return values
- [ ] Implement stable callback patterns
- [ ] Fix unnecessary re-renders
- [ ] Introduce `ErrorAdapter` (or a Zod-based parser) so all hooks consume a standardized `{ success, error_code, ... }` envelope.
- [ ] Add typed runtime configuration loader (`loadRuntimeConfig()` using Zod) to validate environment variables and eliminate secret-misplacement bugs.

**Implementation Pattern:**
```typescript
// ✅ CORRECT: Memoized hook returns
/**
 * Hook for accessing portfolio data with stable return values to prevent unnecessary re-renders.
 * Provides memoized data, loading states, and action callbacks matching existing hook patterns.
 * @returns Stable object containing portfolio data, loading state, error state, and actions
 */
export const usePortfolioSummary = () => {
  // ... hook logic
  
  return useMemo(() => ({
    data,
    summary: data, // Legacy alias
    loading,
    isLoading,
    error,
    refetch: useCallback(() => refetch(), [refetch]),
    refreshSummary: useCallback(() => refetch(), [refetch]),
    hasData: !!data,
    hasError: !!error,
    currentPortfolio
  }), [data, loading, isLoading, error, refetch, currentPortfolio]);
};
```

#### **Day 3-4: Fix Shared State Issues**
- [ ] Implement protective state boundaries
- [ ] Add state validation and error handling
- [ ] Create immutable update patterns
- [ ] Implement backend-driven `cacheVersion` field and frontend invalidation logic (`AdapterRegistry.clear()` and `PortfolioCacheService.clear()` when the version changes).
- [ ] Consolidate cancellation logic into a single `useCancellableRequest()` wrapper around `APIService` that shares AbortController handling across hooks.

#### **Day 5: Add Missing Cleanup**
- [ ] Audit all event listeners for cleanup
- [ ] Add cleanup to timer-based operations
- [ ] Implement proper component unmount handling

### **WEEK 3: ROUTING AND ARCHITECTURE**

#### **Day 1-3: Decouple Routing from State**
- [ ] Create route lifecycle managers
- [ ] Implement atomic navigation patterns
- [ ] Add route validation and error handling

**Implementation Pattern:**
```typescript
// ✅ CORRECT: Atomic navigation
/**
 * Manages atomic navigation operations with rollback capability to prevent partial state corruption.
 * Ensures navigation consistency by treating multiple navigation actions as a single transaction.
 */
class NavigationTransaction {
  /**
   * Executes a series of navigation actions atomically with rollback on failure.
   * @param actions Array of navigation actions to execute in sequence
   * @returns Promise resolving to navigation result with success status and optional error
   */
  async execute(actions: NavigationAction[]): Promise<NavigationResult> {
    const snapshot = this.captureState();
    try {
      for (const action of actions) {
        await this.executeAtomically(action);
      }
      return { success: true };
    } catch (error) {
      await this.rollback(snapshot);
      return { success: false, error };
    }
  }
}
```

#### **Day 4-5: Fix Service Dependencies**
- [ ] Implement proper dependency injection
- [ ] Resolve circular dependencies
- [ ] Create service lifecycle management

### **WEEK 4: DATA CONSISTENCY AND OPTIMIZATION**

#### **Day 1-2: Establish Single Source of Truth**
- [ ] Consolidate portfolio data management
- [ ] Implement consistent cache strategy
- [ ] Add data synchronization patterns

#### **Day 3-4: Add Cancellation Support**
- [ ] Implement AbortController for all async operations
- [ ] Add request cancellation to data fetching
- [ ] Create cancellable operation patterns

#### **Day 5: Testing and Validation**
- [ ] Add architectural tests
- [ ] Validate memory leak fixes
- [ ] Performance testing and optimization
- [ ] Add snapshot tests that mount each custom hook under a mock Provider to verify: (a) singleton instance counts remain 1, (b) no extra renders after state updates, and (c) all errors conform to the standardized envelope.
- [ ] Implement ESLint `no-await-in-loop` rule (with autofix hints) to enforce parallelized requests
- [ ] Implement custom ESLint rule `no-user-id-in-body` (AST check) to prevent leaking user identifiers in request payloads

---

## ARCHITECTURAL PATTERNS TO IMPLEMENT

### **1. Stable Service Pattern**
```typescript
/**
 * Singleton registry for managing adapter instances across the application.
 * Prevents memory leaks and ensures consistent adapter lifecycle management.
 */
class AdapterRegistry {
  private static instances = new Map();
  
  /**
   * Retrieves or creates a singleton adapter instance for the given type.
   * @param type Unique identifier for the adapter type
   * @param factory Factory function to create new adapter instances
   * @returns Singleton adapter instance
   */
  static getAdapter<T>(type: string, factory: () => T): T {
    if (!this.instances.has(type)) {
      this.instances.set(type, factory());
    }
    return this.instances.get(type);
  }
  
  /**
   * Clears all cached adapter instances. Use during logout or application reset.
   */
  static clear(): void {
    this.instances.clear();
  }
}

/**
 * Hook for accessing stable adapter instances with automatic memoization.
 * @param adapterType Unique type identifier for the adapter
 * @param adapterFactory Factory function to create the adapter
 * @returns Memoized adapter instance
 */
const useStableAdapter = <T>(adapterType: string, adapterFactory: () => T) => {
  return useMemo(() => AdapterRegistry.getAdapter(adapterType, adapterFactory), [adapterType]);
};
```

### **2. Cleanup Pattern**
```typescript
/**
 * Hook that ensures proper cleanup for all side effects to prevent memory leaks.
 * @param effect Function that may return a cleanup function
 * @param dependencies Dependency array for the effect
 */
const useCleanupEffect = (effect: () => (() => void) | void, dependencies: any[]) => {
  useEffect(() => {
    const cleanupFunction = effect();
    return cleanupFunction || (() => {}); // Always return cleanup function
  }, dependencies);
};

/**
 * Hook for managing cancellable operations with automatic cleanup on unmount.
 * @returns Function to execute cancellable operations
 */
const useCancellableOperation = () => {
  const abortControllerRef = useRef(new AbortController());
  
  useEffect(() => {
    return () => abortControllerRef.current.abort();
  }, []);
  
  /**
   * Executes an operation with cancellation support.
   * @param operation Async operation that accepts an AbortSignal
   * @returns Promise that resolves to operation result or null if cancelled
   */
  const executeOperation = useCallback(async (operation: (signal: AbortSignal) => Promise<any>) => {
    try {
      return await operation(abortControllerRef.current.signal);
    } catch (error) {
      if (error.name === 'AbortError') return null;
      throw error;
    }
  }, []);
  
  return executeOperation;
};
```

### **3. Immutable State Pattern**
```typescript
/**
 * Hook for managing state with validation boundaries to prevent corruption.
 * @param initialState Initial state value
 * @param stateValidator Function to validate state updates
 * @returns Tuple of current state and protected update function
 */
const useProtectedState = <T>(initialState: T, stateValidator: (state: T) => boolean) => {
  const [state, setState] = useState(initialState);
  
  /**
   * Updates state with validation to prevent invalid mutations.
   * @param stateUpdate Partial state object or update function
   */
  const updateProtectedState = useCallback((stateUpdate: Partial<T> | ((prev: T) => T)) => {
    setState(previousState => {
      const newState = typeof stateUpdate === 'function' 
        ? stateUpdate(previousState) 
        : { ...previousState, ...stateUpdate };
      
      if (!stateValidator(newState)) {
        console.error('Invalid state update attempted:', stateUpdate);
        return previousState;
      }
      return newState;
    });
  }, [stateValidator]);
  
  return [state, updateProtectedState] as const;
};
```

### **4. Dependency Injection Pattern**
```typescript
/**
 * Service container for dependency injection and singleton service management.
 * Provides lazy initialization and prevents circular dependency issues.
 */
class ServiceContainer {
  private services = new Map();
  private serviceFactories = new Map();
  
  /**
   * Registers a service factory with the container.
   * @param serviceKey Unique identifier for the service
   * @param serviceFactory Factory function to create the service instance
   */
  register<T>(serviceKey: string, serviceFactory: () => T): void {
    this.serviceFactories.set(serviceKey, serviceFactory);
  }
  
  /**
   * Retrieves or creates a singleton service instance.
   * @param serviceKey Unique identifier for the service
   * @returns Singleton service instance
   * @throws Error if service is not registered
   */
  get<T>(serviceKey: string): T {
    if (!this.services.has(serviceKey)) {
      const factory = this.serviceFactories.get(serviceKey);
      if (!factory) throw new Error(`Service ${serviceKey} not registered`);
      this.services.set(serviceKey, factory());
    }
    return this.services.get(serviceKey);
  }
  
  /**
   * Clears all cached service instances. Use during application reset.
   */
  clear(): void {
    this.services.clear();
  }
}

/**
 * Global service container instance for application-wide dependency injection.
 */
export const serviceContainer = new ServiceContainer();

// Service registration
serviceContainer.register('apiService', () => new APIService());

// Register per-user + portfolio scoped singletons
serviceContainer.register('portfolioCacheService', () =>
  new PortfolioCacheService(serviceContainer.get('apiService'))
);

serviceContainer.register('portfolioManager', () =>
  new PortfolioManager(
    serviceContainer.get('apiService'),
    serviceContainer.get('portfolioCacheService')
  )
);

/**
 * Hook for accessing injected services with automatic memoization.
 * @param serviceKey Unique identifier for the service
 * @returns Memoized service instance
 */
const useService = <T>(serviceKey: string): T => {
  return useMemo(() => serviceContainer.get<T>(serviceKey), [serviceKey]);
};
```

---

## SUCCESS METRICS

### **Performance Metrics**
- [ ] Memory usage reduced by 40%
- [ ] Component re-render count reduced by 60%
- [ ] Initial load time improved by 25%
- [ ] Cache hit rate improved to >85%

### **Stability Metrics**
- [ ] Zero memory leaks in 24-hour stress test
- [ ] Zero uncaught promise rejections
- [ ] Error boundary activation reduced by 90%
- [ ] Navigation consistency at 100%

### **Code Quality Metrics**
- [ ] Circular dependency count: 0
- [ ] Service instance recreation: 0
- [ ] Missing cleanup functions: 0
- [ ] Architectural violations: 0

---

## **Architectural Testing Strategy**

The following layers of testing will be used to validate architectural integrity and performance post-refactor:

#### ✅ Architectural Compliance
- Singleton instance tests (registry, services)
- Memoization/stable hook returns
- Cleanup validation (event listeners, polling, timers)

#### 🔄 Regression Verification
- Core flow behavior parity
- Snapshot diffs for critical flows

#### 🔬 Resource Lifecycle Validation
- Cancellable operations
- Memory leak detection via stress tests

#### 📏 Pattern Enforcement
- Lint rules for anti-patterns (e.g. new in render, unwrapped effects)
- CI assertions for architecture contract violations

## 🔒 Pattern Enforcement Tools
- ESLint + `react-hooks/exhaustive-deps`, `no-new-in-render` rule
- Madge for cycle detection (CI-enforced)
- Profiler snapshots for render storm detection
- `why-did-you-render` for re-render smoke tests (dev only)
- ESLint `no-await-in-loop` rule (with autofix hints) to enforce parallelized requests
- Custom ESLint rule `no-user-id-in-body`

#### 🧪 Standard Coverage (already in place)
- Unit tests for hook logic and services
- Integration tests for routing and state coordination
- Performance benchmarks on render, load, and memory


## COMPLETION TESTING STRATEGY

### **Unit Tests**
- [ ] Service lifecycle tests
- [ ] Hook stability tests
- [ ] Cleanup verification tests
- [ ] State consistency tests

### **Integration Tests**
- [ ] Navigation flow tests
- [ ] Cross-component communication tests
- [ ] Error boundary tests
- [ ] Memory leak detection tests

### **Performance Tests**
- [ ] Memory usage profiling
- [ ] Render performance benchmarks
- [ ] Cache efficiency tests
- [ ] Load testing scenarios

---

## RISK MITIGATION

### **Rollback Plan**
- [ ] Incremental deployment strategy
- [ ] Performance monitoring alerts
- [ ] Automated rollback triggers

### **Monitoring**
- [ ] Memory usage alerts
- [ ] Error rate monitoring
- [ ] Performance degradation detection
- [ ] User experience tracking

---

## POST-REFACTOR MAINTENANCE

### **Documentation**
- [ ] Architectural decision records
- [ ] Pattern usage guidelines
- [ ] Common pitfall documentation
- [ ] New developer onboarding guide

### **Ongoing Practices**
- [ ] Regular architectural reviews
- [ ] Performance monitoring
- [ ] Automated pattern enforcement
- [ ] Technical debt tracking

---

## CONCLUSION

Phase 3 refactoring addresses fundamental architectural issues that pose immediate risks to system stability and security. The planned improvements will establish a solid foundation for long-term maintainability and performance.

**Next Steps:**
1. Begin emergency fixes immediately
2. Assign dedicated team for 4-week focused effort
3. Implement monitoring and validation systems
4. Plan for ongoing architectural governance

**Expected Outcome:** A stable, performant, and maintainable React frontend architecture that can scale with business requirements while maintaining high code quality standards.