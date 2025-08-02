# Complete Template: Adding New Backend APIs to Frontend

## Problem Solved
This template provides a comprehensive guide for adding new backend APIs to your multi-user frontend architecture. It covers all **24 layers** from backend to UI, ensuring proper user isolation and production readiness.

## Complete 24-Step Architecture Flow

**Updated with all missing infrastructure layers:**

```
BACKEND (Steps 1-3.5):
1. Auth/session validation     ← services/auth_service.py  
1.5. Rate limiting            ← @limiter.limit() decorators
2. Route handler              ← routes/api.py
2.5. Logging middleware       ← @log_performance, @log_error_handling
3. Backend domain logic       ← services/{domain}_service.py
3.5. Data validation          ← core/data_objects.py, core/result_objects.py

FRONTEND (Steps 4-21.5):
4. Frontend contract          ← apiRegistry.ts entry
5. Transport layer           ← APIService.request  
5.5. Request interceptors     ← Token injection, retry, deduplication (auto)
6. I/O wrapper              ← {Domain}Service.{method}()
7. ID→name mapping          ← PortfolioRepository.getName()
8. Provider wiring          ← SessionServicesProvider
9. ServiceContainer         ← Per-user IoC container
10. Zustand store           ← portfolioStore.byId[...]
10.5. Store middleware       ← Subscriptions, computed values, devtools
11. Cache layer             ← PortfolioCacheService.get{Feature}()
12. Manager                 ← PortfolioManager.{method}()
13. AdapterRegistry         ← Memoizes adapters per user
14. Adapter transform       ← {Feature}Adapter.transform()
15. React hook              ← use{Feature} (useQuery)
16. Query cache             ← QueryClientProvider
17. Query key helpers       ← {feature}Key(portfolioId)
18. View formatter          ← formatFor{Feature}View (optional)
19. Container component     ← {Feature}ViewContainer
19.5. Error boundaries       ← DashboardErrorBoundary (auto)
20. Presentational         ← {Feature}View
21. Instrumentation         ← frontendLogger
```

## Two-Phase Implementation Strategy

### Phase 1: Multi-User Safe Placeholders (Steps 4-24)  
*Build complete frontend architecture with mock data at service layer*

### Phase 2: Backend Integration (Steps 1-3 + Replace Step 6)
*Add real backend APIs and replace service mocks*

## Implementation Quick Reference

| Step | Layer | Type | Action Required |
|------|-------|------|----------------|
| 4 | API Registry | 🔧 Template | Copy/modify contract |
| 5 | Transport | ✅ Auto | No code needed |
| 6 | Service | 🔧 Template | Copy/modify service class |
| 7 | Repository | ✅ Auto | Usually no changes |
| 8 | Provider | ✅ Auto | Follow existing pattern |
| 9 | ServiceContainer | 🔧 Template | Add service getter |
| 10 | Zustand Store | 💭 Optional | Only if global state needed |
| 11 | Cache | 🔧 Template | Add cache methods |
| 12 | Manager | 🔧 Template | Add business logic |
| 13 | AdapterRegistry | ✅ Auto | No changes needed |
| 14 | Adapter | 🔧 Template | Create transformation logic |
| 15 | React Hook | 🔧 Template | Create useQuery hook |
| 16 | Query Cache | ✅ Auto | No changes needed |
| 17 | Query Keys | 🔧 Template | Add key helper |
| 18-21 | UI Components | 💭 Optional | Build when ready |

✅ **Auto** = Built-in infrastructure, no code needed  
🔧 **Template** = Copy/paste/modify provided templates  
💭 **Optional** = Implement based on feature requirements

---

## Phase 1: Multi-User Safe Placeholders

**⚠️ CRITICAL: In multi-user systems, you CANNOT skip any of steps 8-19.5. Skipping them = data leaks between users!**

### Step 4: Frontend Contract (API Registry)
**Location**: `frontend/src/apiRegistry.ts`

```typescript
export const apiRegistry = {
  // ... existing entries
  
  {featureName}: {
    path: '/api/{feature-name}',
    method: 'POST' as const,
    description: '{Feature} analysis for portfolio optimization',
    requestShape: {
      portfolio_id: 'string',
      options: 'object', // feature-specific options
    },
    responseShape: {
      success: 'boolean',
      portfolio_id: 'string',
      {featureName}_data: 'object',
      timestamp: 'string'
    }
  }
}
```

### Step 5: Transport Layer (Already Exists)
**Location**: `frontend/src/chassis/services/APIService.ts`
*No changes needed - APIService.request() handles auth, retry, etc.*

### Step 5.5: Request/Response Interceptors (Auto-Applied)
**Location**: `frontend/src/chassis/services/APIService.ts` (Built-in)
*Your APIService automatically provides these interceptors:*

```typescript
// Automatic token injection
if (this.getToken) {
  const token = this.getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
}

// Request deduplication (prevents duplicate simultaneous requests)
private pendingRequests: Map<string, Promise<any>> = new Map();
const requestKey = `${options.method || 'GET'}:${endpoint}:${Date.now()}`;

// Automatic retry with exponential backoff
const response = await this.fetchWithRetry(url, config, 3);

// CSRF protection
headers['X-Requested-With'] = 'XMLHttpRequest';

// Cookie credentials for cross-origin
credentials: 'include'
```

**🔑 Multi-User Safety**: All interceptors respect user context automatically.
**✅ No Code Needed**: These interceptors are built into APIService - your new API gets them automatically!

### Step 6: I/O Wrapper (Service Class)
**Location**: `frontend/src/chassis/services/{Feature}Service.ts`

```typescript
import { APIService } from './APIService';

/**
 * {Feature} service for portfolio {feature} operations
 * Handles API communication with proper user isolation
 */
export class {Feature}Service extends APIService {
  /**
   * Run {feature} analysis for a portfolio
   * PLACEHOLDER: Returns mock data but maintains service architecture
   */
  async analyze{Feature}(portfolioId: string, options = {}) {
    // TODO: Replace with real API call when backend ready
    // return this.request({
    //   url: apiRegistry.{featureName}.path,
    //   method: apiRegistry.{featureName}.method,
    //   data: { portfolio_id: portfolioId, options }
    // });
    
    // PLACEHOLDER: Simulate API delay and return structured mock data
    await new Promise(resolve => setTimeout(resolve, 1200));
    
    return {
      data: {
        success: true,
        portfolio_id: portfolioId,
        {featureName}_data: {
          // ... your feature-specific mock data
          analysis_id: `mock_${Date.now()}`,
          computed_at: new Date().toISOString(),
          // ... realistic structure matching expected backend response
        },
        timestamp: new Date().toISOString()
      }
    };
  }
}
```

### Step 7: ID→Name Mapping (Repository Integration)
**Location**: `frontend/src/repository/PortfolioRepository.ts`
*Usually no changes needed - existing getName() method handles mapping*

### Step 8: Provider Wiring (Multi-User Critical)
**Location**: `frontend/src/providers/SessionServicesProvider.tsx`
*Follow existing pattern to ensure your service gets proper user isolation*

### Step 9: ServiceContainer (Per-User IoC)
**Location**: `frontend/src/chassis/services/ServiceContainer.ts`

```typescript
// Add your service to the container
export class ServiceContainer {
  // ... existing services
  
  private _{featureName}Service?: {Feature}Service;
  
  get {featureName}Service(): {Feature}Service {
    if (!this._{featureName}Service) {
      this._{featureName}Service = new {Feature}Service(this.config);
    }
    return this._{featureName}Service;
  }
  
  // ... rest of container
}
```

### Step 10: Zustand Store Integration (User-Specific State)
**Location**: `frontend/src/stores/portfolioStore.ts`

```typescript
// If your feature needs global state, add to store
// Usually not needed for analysis features - React Query handles caching
interface PortfolioState {
  // ... existing state
  
  // Optional: Add feature-specific state if needed
  {featureName}Results?: Record<string, any>;
}

// Optional: Add actions if needed
const portfolioActions = {
  // ... existing actions
  
  set{Feature}Result: (portfolioId: string, result: any) => 
    set((state) => ({
      {featureName}Results: {
        ...state.{featureName}Results,
        [portfolioId]: result
      }
    }))
};
```

### Step 10.5: Store Subscriptions/Middleware (If Needed)
**Location**: `frontend/src/stores/portfolioStore.ts` (Pattern already in use)
*Your store already uses advanced patterns - add only if your feature needs them:*

```typescript
// EXISTING PATTERNS IN YOUR STORE:

// 1. Devtools middleware (already configured)
export const usePortfolioStore = createWithEqualityFn<PortfolioStoreState>()(
  devtools(
    (set, get) => ({
      // ... store implementation
    }),
    { name: 'portfolio-store' } // 🔑 Multi-user safe naming
  ),
  shallow
);

// 2. Computed/derived state (already implemented)
getCurrentPortfolio: () => {
  const state = get();
  return state.currentPortfolioId ? state.byId[state.currentPortfolioId] : null;
},

// 3. Cross-store subscriptions (if your feature needs them)
// Example: Listen to auth changes and clear feature data
import { useAuthStore } from './authStore';

const unsubscribe = useAuthStore.subscribe(
  (state) => state.user,
  (user, previousUser) => {
    if (!user && previousUser) {
      // User logged out - clear all {feature} data
      usePortfolioStore.setState((state) => ({
        {featureName}Results: {}
      }));
    }
  }
);

// 4. Content versioning (already implemented for cache invalidation)
contentVersion: holdingsChanged ? existing.contentVersion + 1 : existing.contentVersion,

// 5. Selective subscriptions in components
const portfolioResults = usePortfolioStore((state) => state.{featureName}Results);
```

**🔑 Multi-User Safety**: Store is automatically isolated per browser tab/user session.
**✅ Usually Skip This**: Most analysis features don't need additional store patterns.

### Step 11: Cache Layer (User Isolation Critical)
**Location**: `frontend/src/chassis/services/PortfolioCacheService.ts`

```typescript
export class PortfolioCacheService {
  // ... existing cache methods
  
  /**
   * {Feature} cache methods - user isolated
   */
  get{Feature}(portfolioId: string) {
    return this.cache.get(`{featureName}:${portfolioId}`);
  }
  
  set{Feature}(portfolioId: string, data: any) {
    this.cache.set(`{featureName}:${portfolioId}`, data, {
      ttl: 30 * 60 * 1000 // 30 minutes
    });
  }
  
  clear{Feature}(portfolioId?: string) {
    if (portfolioId) {
      this.cache.delete(`{featureName}:${portfolioId}`);
    } else {
      // Clear all {feature} cache for current user
      this.clearByPattern(`{featureName}:*`);
    }
  }
}
```

### Step 12: Manager (User-Scoped Business Logic)
**Location**: `frontend/src/chassis/managers/PortfolioManager.ts` (or create new manager)

```typescript
export class PortfolioManager {
  // ... existing methods
  
  /**
   * Run {feature} analysis with caching and error handling
   * PLACEHOLDER: Uses mock service but maintains proper isolation
   */
  async analyze{Feature}(portfolioId: string, options = {}) {
    try {
      // Check cache first (user-isolated)
      const cached = this.cache.get{Feature}(portfolioId);
      if (cached && !options.force) {
        frontendLogger.adapter.transformStart('PortfolioManager', `Using cached {feature} analysis for ${portfolioId}`);
        return { data: cached, fromCache: true };
      }
      
      // Get portfolio name (for backend API)
      const portfolioName = await this.repository.getName(portfolioId);
      
      // Call service (returns mock data for now)
      // If shared cached service (e.g. PortfolioCacheService) call that directly
      const result = await this.services.{featureName}Service.analyze{Feature}(portfolioName, options);
      
      if (result.data.success) {
        // Cache the result (user-isolated)
        this.cache.set{Feature}(portfolioId, result.data);
        
        // Optional: Update store if needed
        // this.store.set{Feature}Result(portfolioId, result.data);
        
        frontendLogger.adapter.transformSuccess('PortfolioManager', `{Feature} analysis completed for portfolio ${portfolioId}`);
        return { data: result.data, fromCache: false };
      } else {
        throw new Error(result.data.error || '{Feature} analysis failed');
      }
      
    } catch (error) {
      frontendLogger.error('{Feature} analysis error', 'PortfolioManager', error instanceof Error ? error : new Error(String(error)));
      
      // Clear potentially stale cache
      this.cache.clear{Feature}(portfolioId);
      
      return { 
        error: error instanceof Error ? error.message : 'Unknown error',
        data: null 
      };
    }
  }
}
```

### Step 13: AdapterRegistry (Memoization per User)
**Location**: `frontend/src/utils/AdapterRegistry.ts`
*No changes needed - existing registry handles user-scoped adapter memoization*

### Step 14: Adapter Transform (Data Transformation)
**Location**: `frontend/src/adapters/{Feature}Adapter.ts`

```typescript
import { frontendLogger } from '../services/frontendLogger';

/**
 * {Feature} adapter for transforming API data to UI format
 * Works with both mock and real backend data
 */
export class {Feature}Adapter {
  /**
   * Transform {feature} API response to UI-friendly format
   */
  transform(apiResponse: any) {
    frontendLogger.adapter.transformStart('{Feature}Adapter', {
      hasData: !!apiResponse,
      isPlaceholder: !!apiResponse?.analysis_id?.includes('mock_')
    });
    
    if (!apiResponse || !apiResponse.{featureName}_data) {
      return this.getDefaultData();
    }
    
    const data = apiResponse.{featureName}_data;
    
    // Transform to UI format
    const transformed = {
      portfolioId: apiResponse.portfolio_id,
      analysisId: data.analysis_id,
      computedAt: data.computed_at,
      
      // Feature-specific transformations
      // ... transform your mock/real data to UI format
      
      // Meta
      isPlaceholder: data.analysis_id?.includes('mock_'),
      timestamp: apiResponse.timestamp
    };
    
    frontendLogger.adapter.transformSuccess('{Feature}Adapter', {
      hasData: !!transformed,
      isPlaceholder: transformed.isPlaceholder
    });
    
    return transformed;
  }
  
  private getDefaultData() {
    return {
      portfolioId: '',
      analysisId: 'default',
      computedAt: new Date().toISOString(),
      // ... default values
      isPlaceholder: true,
      timestamp: new Date().toISOString()
    };
  }
}
```

### Step 15: React Hook (useQuery Integration)
**Location**: `frontend/src/features/{domain}/hooks/use{Feature}.ts`

```typescript
import { useQuery, useMutation } from '@tanstack/react-query';
import { useMemo } from 'react';
import { useSessionServices } from '../../../providers/SessionServicesProvider';
import { useCurrentPortfolio } from '../../../stores/portfolioStore';
import { {Feature}Adapter } from '../../../adapters/{Feature}Adapter';
import { AdapterRegistry } from '../../../utils/AdapterRegistry';
import { frontendLogger } from '../../../services/frontendLogger';
import { HOOK_QUERY_CONFIG } from '../../../config/queryConfig';
import { {featureName}Key } from '../../../queryKeys';

/**
 * {Feature} hook for portfolio {feature} analysis
 * Provides complete multi-user safe interface with caching and error handling
 */
export const use{Feature} = () => {
  const { manager } = useSessionServices(); // 🔑 User-scoped manager
  const currentPortfolio = useCurrentPortfolio(); // 🔑 User-specific portfolio
  
  // 🔑 User-scoped adapter (memoized per user)
  const adapter = useMemo(
    () => AdapterRegistry.getAdapter('{featureName}', 
      [currentPortfolio?.id || 'default'], 
      () => new {Feature}Adapter()
    ),
    [currentPortfolio?.id]
  );
  
  const {
    data,
    isLoading,
    error,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: {featureName}Key(currentPortfolio?.id), // 🔑 User-specific query key
    queryFn: async () => {
      if (!currentPortfolio) {
        frontendLogger.adapter.transformStart('use{Feature}', 'No portfolio');
        return null;
      }
      
      frontendLogger.adapter.transformStart('use{Feature}', { 
        portfolioId: currentPortfolio.id,
        userId: manager.userId // 🔑 Log which user
      });
      
      // 🔑 Use manager (handles caching, error handling, user isolation)
      const result = await manager.analyze{Feature}(currentPortfolio.id!);
      
      if (result.error) {
        throw new Error(result.error);
      }
      
      // 🔑 Transform using user-scoped adapter
      const transformedData = adapter.transform(result.data);
      
      frontendLogger.adapter.transformSuccess('use{Feature}', {
        hasData: !!transformedData,
        portfolioId: currentPortfolio.id,
        userId: manager.userId,
        fromCache: result.fromCache,
        isPlaceholder: transformedData.isPlaceholder
      });
      
      return transformedData;
    },
    enabled: !!currentPortfolio && !!manager,
    staleTime: HOOK_QUERY_CONFIG.useRiskScore.staleTime, // Reuse existing config
    retry: (failureCount, error: any) => {
      // Don't retry on validation errors
      if (error?.message?.includes('Portfolio validation')) {
        return false;
      }
      return failureCount < 2;
    },
  });
  
  // Mutation for running analysis with custom options
  const analyzeMutation = useMutation({
    mutationFn: async (options: any = {}) => {
      frontendLogger.user.action('run{Feature}Analysis', 'use{Feature}', {
        portfolioId: currentPortfolio?.id,
        options
      });
      
      if (!currentPortfolio) {
        throw new Error('No portfolio selected');
      }
      
      const result = await manager.analyze{Feature}(currentPortfolio.id!, { ...options, force: true });
      
      if (result.error) {
        throw new Error(result.error);
      }
      
      return result;
    },
    onSuccess: () => {
      // Invalidate cache to refetch with new results
      refetch();
    }
  });
  
  return useMemo(() => ({
    // Data
    data,
    
    // States
    isLoading,
    isRefetching,
    error: error?.message || null,
    
    // Actions
    refetch,
    runAnalysis: analyzeMutation.mutate,
    isAnalyzing: analyzeMutation.isPending,
    
    // Computed states
    hasData: !!data,
    hasError: !!error,
    hasPortfolio: !!currentPortfolio,
    
    // Debug/Meta info
    isPlaceholder: data?.isPlaceholder || false,
    currentUser: manager?.userId,
    currentPortfolio,
  }), [data, isLoading, isRefetching, error, refetch, analyzeMutation, currentPortfolio, manager]);
};
```

### Step 16: Query Cache (Already Configured)
**Location**: `frontend/src/providers/QueryProvider.tsx`
*No changes needed - QueryClientProvider already handles user-specific caching*

### Step 17: Query Key Helpers
**Location**: `frontend/src/queryKeys.ts`

```typescript
// Add your feature's query key helper
export const {featureName}Key = (portfolioId?: string) => 
  ['portfolio', portfolioId, '{featureName}'] as const;
```

### Steps 18-21: UI Layer (Optional for Phase 1)

**Step 18: View Formatter (Optional)**
```typescript
// frontend/src/features/{domain}/formatters/formatFor{Feature}View.ts
export const formatFor{Feature}View = (data) => {
  // Format data for specific UI components if needed
  return data;
};
```

**Step 19: Container Component (With Error Boundary)**
```typescript
// frontend/src/components/dashboard/views/{Feature}ViewContainer.tsx
import React from 'react';
import { use{Feature} } from '../../../features/{domain}';
import { {Feature}View } from './{Feature}View';
import { DashboardErrorBoundary } from '../shared/ErrorBoundary';
import { LoadingSpinner } from '../shared/ui/LoadingSpinner';

export const {Feature}ViewContainer: React.FC = () => {
  const { 
    data, 
    isLoading, 
    error, 
    isPlaceholder,
    runAnalysis,
    isAnalyzing 
  } = use{Feature}();

  if (isLoading) {
    return <LoadingSpinner message="Loading {feature} analysis..." />;
  }

  if (error) {
    return (
      <div className="text-center p-8 text-red-600">
        <p>Error loading {feature}: {error}</p>
        <button onClick={() => runAnalysis()} className="mt-2 btn-primary">
          Retry Analysis
        </button>
      </div>
    );
  }

  return (
    <DashboardErrorBoundary>
      <{Feature}View 
        data={data}
        isPlaceholder={isPlaceholder}
        onRunAnalysis={runAnalysis}
        isAnalyzing={isAnalyzing} 
      />
    </DashboardErrorBoundary>
  );
};
```

**Step 19.5: Error Boundaries (Multi-User Safe)**
**Location**: `frontend/src/components/dashboard/shared/ErrorBoundary.tsx` (Already exists)
*Your existing ErrorBoundary automatically provides:*

```typescript
// EXISTING ERROR BOUNDARY FEATURES:
class DashboardErrorBoundary extends React.Component {
  // 1. User-aware error logging
  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    frontendLogger.component.error('ErrorBoundary', error, errorInfo);
    // Logs include user context automatically via frontendLogger
  }

  // 2. Graceful error UI with recovery options
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center h-64">
          <div className="text-center p-8">
            <h2>Dashboard Error</h2>
            <p>Something went wrong loading this view.</p>
            <button onClick={() => window.location.reload()}>
              Reload Dashboard
            </button>
            <button onClick={() => this.setState({ hasError: false })}>
              Try Again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
```

**🔑 Multi-User Safety**: Error boundaries isolate crashes per user session.
**✅ Auto-Applied**: Wrap your container components in existing `<DashboardErrorBoundary>`!

**Step 20: Presentational Component**
```typescript
// Can build these against the hook immediately
const {Feature}View = ({ data, isPlaceholder, onRunAnalysis, isAnalyzing }) => {
  return (
    <div>
      {isPlaceholder && (
        <div className="bg-yellow-50 border border-yellow-200 rounded p-3 mb-4">
          🚧 Preview Mode - Using Mock Data
        </div>
      )}
      
      {data && (
        <div>
          {/* Render your feature data */}
        </div>
      )}
      
      <button 
        onClick={onRunAnalysis}
        disabled={isAnalyzing}
        className="btn-primary"
      >
        {isAnalyzing ? 'Analyzing...' : 'Run New Analysis'}
      </button>
    </div>
  );
};
```

**Step 21: Instrumentation (Already Included)**
*frontendLogger calls are integrated throughout the flow*

---

## Phase 2: Backend Integration (When Ready)

### Backend Steps (1-3)
1. **Auth/session validation** - Backend team implements
2. **Route handler** - Backend team adds to `routes/api.py`
3. **Backend service** - Backend team creates `services/{domain}_service.py`

### Frontend Integration (Replace Step 6)

**Simply replace the service implementation:**

```typescript
// In {Feature}Service.ts, replace this:
await new Promise(resolve => setTimeout(resolve, 1200));
return { data: { /* mock data */ } };

// With this:
return this.request({
  url: apiRegistry.{featureName}.path,
  method: apiRegistry.{featureName}.method,
  data: { portfolio_id: portfolioId, options }
});
```

**Everything else continues to work unchanged!**

---

## Export Pattern

```typescript
// frontend/src/features/{domain}/index.ts
export { use{Feature} } from './hooks/use{Feature}';

// frontend/src/features/index.ts
export * from './{domain}';
```

## Usage in Components

```typescript
import { use{Feature} } from '@/features/{domain}';
// or
import { use{Feature} } from '@/features';

const MyComponent = () => {
  const { 
    data, 
    isLoading, 
    runAnalysis, 
    isPlaceholder,
    currentUser 
  } = use{Feature}();
  
  return (
    <div>
      {isPlaceholder && (
        <Alert>🚧 Using mock data - Backend API not connected</Alert>
      )}
      
      {isLoading && <LoadingSpinner />}
      
      {data && (
        <div>
          <p>Analysis for user: {currentUser}</p>
          {/* Render your feature data */}
        </div>
      )}
      
      <button onClick={() => runAnalysis()}>
        Run New Analysis
      </button>
    </div>
  );
};
```

## ✅ Multi-User Safety Guaranteed

This template ensures:

- 🔒 **Complete user isolation** at all layers
- 🔄 **Full architecture testing** with realistic flows  
- 📦 **Easy backend migration** when APIs are ready
- 🧪 **Immediate UI development** with mock data
- 🛡️ **Production ready** multi-user safety

## 🔍 Audit Improvements Summary

**Critical Infrastructure Now Covered:**
- ✅ **Request/Response Interceptors** (auto-applied via APIService)
- ✅ **Rate Limiting & Logging** (backend middleware patterns)  
- ✅ **Store Middleware** (devtools, subscriptions, computed state)
- ✅ **Error Boundaries** (crash isolation per user session)
- ✅ **Data Validation** (backend input/output contracts)

**Enhanced Multi-User Safety:**
- 🔐 **User context logging** in all operations
- 🔐 **Cache key isolation** patterns enforced
- 🔐 **Service container** per-user scoping
- 🔐 **Query invalidation** user-specific patterns

**Developer Experience Improvements:**
- 📋 **Quick reference table** (auto vs template vs optional)
- 🎯 **Consistent naming** conventions for templates
- 📝 **Concrete code examples** for every layer
- 🚀 **Immediate UI development** capability

**No data leaks, no shortcuts, full architecture integrity!**

## FINAL CHECKLIST (POST IMPLEMENTATION)

Quick final checklist—things that sit **outside** the 24-step flow that you may still need to hook up when you drop a brand-new API/feature into the dashboard.

1. Dashboard layout / routing  
   • Add the `{Feature}ViewContainer` to whatever page, tab, or route renders the dashboard sections (e.g. `DashboardLayout.tsx` or `routes/dashboard.tsx`).  
   • Add a nav item / sidebar entry if the feature should be user-selectable.

2. Barrel exports  
   • `frontend/src/features/{domain}/index.ts` — export `use{Feature}` (already in template).  
   • `frontend/src/features/index.ts` — re-export the domain so callers can do `import { useFoo } from '@/features';`.

3. Global type declarations  
   • If you create new request/response TypeScript interfaces (or Zod schemas), export them in a `types.ts` so tests and Storybook stories can import them.

4. Query-config constants (staleTime, cacheTime)  
   • If the new data should live longer/shorter than the default, update `HOCK_QUERY_CONFIG` (template references it in the hook).

5. CSS / design tokens  
   • If the View uses new colour variables or utility classes, ensure they exist in your Tailwind config or CSS module.

6. Feature flags (optional)  
   • If you gate unfinished features behind a flag, register that flag in whatever configs or LaunchDarkly split you’re using.

7. Internationalisation (i18n)  
   • If you support multiple languages, add translation keys for headings, button labels, error texts in your locale JSON files.

8. Logging dashboards / metrics  
   • `frontendLogger` already logs adapter & user actions; create a Kibana / Datadog dashboard panel for the new event names if you monitor them in Ops.

9. Tests & stories  
   • Unit tests: adapter transform, hook happy-path & error-path.  
   • E2E smoke: mount the container, ensure “Run Analysis” returns 200.  
   • Storybook story: render `{Feature}View` with mock props.

10. Documentation touch-ups  
   • Update README or `docs/FEATURE_MATRIX.md` if you track feature availability per plan.  
   • Add an entry to any developer-onboarding doc that lists all query keys or cache helpers.

If you go through that list and the 24 template steps are already implemented, you’re fully wired—nothing else in the front-end should break or be missing.