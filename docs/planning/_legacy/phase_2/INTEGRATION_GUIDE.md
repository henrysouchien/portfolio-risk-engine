# Portfolio UI Integration Guide

## 📊 Component Status & Overview

**Current State:**
- ✅ **17 modern UI components** with beautiful styling and comprehensive functionality
- ✅ **Excellent documentation** in each component header with integration guidance  
- ✅ **One working example**: `ConnectedRiskAnalysis.tsx` shows the integration pattern
- ❌ **Missing**: Container components for most views following classic UI pattern
- ❌ **Mock data**: Components use static/mocked data instead of live hooks

**Purpose:**
- These `components/portfolio/*` files are the modern, presentational UI for the portfolio dashboard.
- They do not fetch data themselves. Integrate them using the same container pattern used by the classic UI (`components/dashboard/views/*`).

Core Pattern (Container → View)
- View components here are “dumb”/presentational and focus on layout and styling.
- Create a matching Container that:
  - Calls the appropriate React Query hook(s) from `src/features/*`.
  - Handles Loading, Error, and No‑Data states using shared UI components.
  - Passes adapter‑shaped data down as props, or lets the view read via hooks if truly safe.
  - Wires refresh actions to the Intent system, then refetches queries.

Building Blocks
- Hooks (React Query + adapters):
  - Portfolio summary: `features/portfolio/usePortfolioSummary`
  - Factor risk: `features/analysis/useRiskAnalysis`
  - Performance: `features/analysis/usePerformance`
  - Risk score: `features/riskScore/useRiskScore`
  - What‑If/Scenarios: `features/whatIf/useWhatIfAnalysis`
  - Optimization: `features/optimize/usePortfolioOptimization`
  - Stocks: `features/stockAnalysis/useStockAnalysis`
- Shared UI (for containers): `components/dashboard/shared/ui/*`
  - `LoadingSpinner`, `ErrorMessage`, `NoDataMessage`, `StatusIndicator`
  - Boundary: `components/dashboard/shared/ErrorBoundary`
- Intents (for long‑running operations): `utils/NavigationIntents`
  - Example: `await IntentRegistry.triggerIntent('refresh-holdings')`
  - Note: If you reference new intents (e.g., `refresh-performance`, `run-scenario`, `optimize-portfolio`), add them to the IntentRegistry and back them with the appropriate manager/service calls, or fall back to plain `refetch()` where applicable.
- Stores (use in containers, not in views):
  - `stores/portfolioStore`: `useCurrentPortfolio()` etc.
  - `stores/uiStore`: `setActiveView`, `setViewLoading`, `setViewError`
- Logging: `services/frontendLogger`

Query & Cache Notes
- Hooks are backed by TanStack Query and adapters; do not call APIs directly from views.
- Keys/staleTime come from `HOOK_QUERY_CONFIG` in hook modules.
- Some hooks share keys (e.g., risk score/analysis with portfolio summary) to benefit from warm caches.
- Always refetch after an intent that changes backend state:
  1) `await IntentRegistry.triggerIntent('refresh-holdings')`
  2) `await summary.refetch()` (or the relevant hook’s `refetch`)

Styling & Theme
- `index.css` defines HSL tokens; Tailwind maps them to semantic classes in `tailwind.config.js`.
- Use `bg-background`, `text-foreground`, `bg-card`, `border-border`, `text-chart-1..5`, etc.
- Custom utilities available: `glass-premium`, `hover-lift-premium`, `skeleton-premium`, `text-gradient-premium`.
- Dark mode is controlled by `.dark` on `<html>`, toggled in `App.tsx` via `uiStore`.

Container Skeleton (Generic)
```tsx
import React, { useEffect } from 'react';
import { DashboardErrorBoundary, ErrorMessage, LoadingSpinner, NoDataMessage } from '../../dashboard/shared';
import { frontendLogger } from '../../../services/frontendLogger';

// 1) Choose the correct hook for your view
import { useRiskAnalysis } from '../../../features/analysis';

// 2) Import the presentational component from portfolio/
import RiskAnalysis from '../../portfolio/RiskAnalysis';

export const RiskAnalysisModernViewContainer: React.FC = () => {
  const { data, isLoading, error, refetch } = useRiskAnalysis();

  useEffect(() => {
    frontendLogger.user.action('viewRendered', 'RiskAnalysisModern', {
      hasData: !!data,
      isLoading,
      hasError: !!error,
    });
  }, [data, isLoading, error]);

  if (isLoading) return <LoadingSpinner message="Analyzing risk factors..." />;
  if (error) return <ErrorMessage error={String(error)} onRetry={refetch} />;
  if (!data) return <NoDataMessage message="No analysis available. Upload a portfolio." />;

  return (
    <DashboardErrorBoundary>
      <RiskAnalysis /* pass props if needed */ />
    </DashboardErrorBoundary>
  );
};
```

Examples per Component
- PortfolioOverview
  - Hook: `usePortfolioSummary()`
  - Refresh: `IntentRegistry.triggerIntent('refresh-holdings')` then `summary.refetch()`
  - Props: can remain self‑contained, or pass summary totals/lastUpdated explicitly.

```tsx
import { usePortfolioSummary } from '../../../features/portfolio';
import PortfolioOverview from '../../portfolio/PortfolioOverview';

export const PortfolioOverviewContainer = () => {
  const summary = usePortfolioSummary();
  if (summary.isLoading) return <LoadingSpinner message="Loading overview..." />;
  if (summary.error) return <ErrorMessage error={String(summary.error)} onRetry={summary.refetch} />;
  if (!summary.data) return <NoDataMessage message="No portfolio loaded." />;
  return <PortfolioOverview />; // or pass summary.data props
};
```

- HoldingsView
  - Hook: `usePortfolioSummary()` (adapter provides normalized holdings)
  - Refresh button: trigger intent then `summary.refetch()`

```tsx
import HoldingsView from '../../portfolio/HoldingsView';
import { IntentRegistry } from '../../../utils/NavigationIntents';

export const HoldingsViewContainer = () => {
  const summary = usePortfolioSummary();
  const onRefresh = async () => {
    const res = await IntentRegistry.triggerIntent('refresh-holdings');
    if (res.success) await summary.refetch();
  };
  // Handle load/error/no-data...
  return <HoldingsView /* optional props, onRefresh={onRefresh} */ />;
};
```

- PerformanceView / PerformanceChart
  - Hook: `usePerformance()`
  - Pass time‑series and benchmark to the chart; keep chart purely presentational.

```tsx
import { usePerformance } from '../../../features/analysis';
import PerformanceView from '../../portfolio/PerformanceView';

export const PerformanceViewContainer = () => {
  const perf = usePerformance();
  if (perf.isLoading) return <LoadingSpinner message="Loading performance..." />;
  if (perf.error) return <ErrorMessage error={String(perf.error)} onRetry={perf.refetch} />;
  if (!perf.data) return <NoDataMessage message="No performance data." />;
  return <PerformanceView />; // or pass perf.data to internal chart
};
```

- RiskAnalysis / FactorRiskModel / RiskMetrics
  - Hook: `useRiskAnalysis()`; adapter exposes factor exposures, variance, correlations, etc.
  - Use existing `ConnectedRiskAnalysis` as a ready‑made example wrapper.

- ScenarioAnalysis
  - Hook: `useWhatIfAnalysis()`; container runs scenarios, passes results and controls.

```tsx
import { useWhatIfAnalysis } from '../../../features/whatIf';
import ScenarioAnalysis from '../../portfolio/ScenarioAnalysis';

export const ScenarioAnalysisContainer = () => {
  const { data, runScenario, isLoading, error } = useWhatIfAnalysis();
  // Handle states...
  return <ScenarioAnalysis /* props from data + handlers */ />;
};
```

- StrategyBuilder
  - Hooks: `usePortfolioOptimization()` and/or `useWhatIfAnalysis()`
  - Container coordinates optimization → scenario → refetch summaries.

- StockLookup
  - Hook: `useStockAnalysis()` with debounce in container; Intent to navigate to research view.

Do’s and Don’ts
- Do: Keep portfolio components presentational. Put data fetching, effects, and store interactions in containers.
- Do: Reuse shared UI for loading/error/no‑data to keep UX consistent.
- Do: Use Intents for actions that mutate backend state; then refetch affected queries.
- Don’t: Call APIs directly from views.
- Don’t: Couple views to Zustand stores; read store in container if absolutely necessary.

Logging
- Log mount/actions from containers:
```ts
frontendLogger.user.action('viewRendered', 'ComponentName', { hasData, isLoading, hasError });
```

Where to Place Containers
- To match the classic pattern, place containers under `components/dashboard/views/` and import the modern portfolio views from `components/portfolio/`.
- Example filename convention: `RiskAnalysisModernViewContainer.tsx`, `PortfolioOverviewContainer.tsx`.

## 🏗️ Required Container Components

Following the **Container/View pattern** from your classic UI, you need to create these containers in `src/components/dashboard/views/`:

### **Phase 1: Core Views (High Priority)**

#### 1. **`PortfolioOverviewContainer.tsx`** ⭐ START HERE
```tsx
/**
 * PortfolioOverviewContainer - Container for modern PortfolioOverview
 * Highest impact - main dashboard landing view
 */
import React, { useEffect } from 'react';
import { usePortfolioSummary } from '../../../features/portfolio';
import { DashboardErrorBoundary, ErrorMessage, LoadingSpinner, NoDataMessage } from '../shared';
import { frontendLogger } from '../../../services/frontendLogger';
import PortfolioOverview from '../../portfolio/PortfolioOverview';
import { IntentRegistry } from '../../../utils/NavigationIntents';

const PortfolioOverviewContainer = ({ ...props }) => {
  const { data, loading, error, hasData, hasPortfolio, refetch, clearError } = usePortfolioSummary();
  
  useEffect(() => {
    frontendLogger.user.action('viewRendered', 'PortfolioOverview', {
      hasData: !!data, isLoading: loading, hasError: !!error
    });
  }, [data, loading, error]);

  const handleRefresh = async () => {
    const result = await IntentRegistry.triggerIntent('refresh-holdings');
    if (result.success) await refetch();
  };

  if (loading) return <LoadingSpinner message="Loading portfolio overview..." />;
  if (error) return <ErrorMessage error={error} onRetry={() => { clearError(); refetch(); }} />;
  if (!hasPortfolio) return <NoDataMessage message="No portfolio loaded." />;

  return (
    <DashboardErrorBoundary>
      <PortfolioOverview 
        data={data}
        onRefresh={handleRefresh}
        {...props}
      />
      {process.env.NODE_ENV === 'development' && (
        <div className="fixed bottom-4 right-4 bg-green-100 text-green-800 px-3 py-1 rounded text-xs">
          Overview: {hasData ? 'Real' : 'Mock'}
        </div>
      )}
    </DashboardErrorBoundary>
  );
};

export default React.memo(PortfolioOverviewContainer);
```

**Integration Steps:**
- **Hook**: `usePortfolioSummary()` - same cache as other views
- **Intent**: `'refresh-holdings'` for portfolio refresh  
- **Props needed**: Modify `PortfolioOverview.tsx` to accept `data` prop instead of mock data
- **Data fields**: `totalValue, dayChange, riskScore, sharpeRatio, lastUpdated`

#### 2. **`HoldingsViewModernContainer.tsx`**
```tsx
/**
 * HoldingsViewModernContainer - Modern holdings table with enhanced features
 * Reuses logic from existing HoldingsViewContainer but with modern UI
 */
import React, { useEffect } from 'react';
import { usePortfolioSummary } from '../../../features/portfolio';
import { usePlaid } from '../../../features/external';
import { DashboardErrorBoundary, ErrorMessage, LoadingSpinner, NoDataMessage } from '../shared';
import { frontendLogger } from '../../../services/frontendLogger';
import HoldingsView from '../../portfolio/HoldingsView'; // Modern component
import { IntentRegistry } from '../../../utils/NavigationIntents';

const HoldingsViewModernContainer = ({ onRefresh, onAnalyzeRisk, ...props }) => {
  const { data, loading, error, hasData, hasPortfolio, refetch, clearError } = usePortfolioSummary();
  const { connections, loading: plaidLoading } = usePlaid();
  
  useEffect(() => {
    frontendLogger.user.action('viewRendered', 'HoldingsViewModern', {
      hasData: !!data, isLoading: loading, hasError: !!error,
      holdingsCount: data?.holdings?.length || 0
    });
  }, [data, loading, error]);

  const handleRefresh = async () => {
    if (onRefresh) await onRefresh();
    await refetch();
  };

  // Same state handling as classic container
  if (loading && !hasData) return <LoadingSpinner message="Loading holdings..." />;
  if (error) return <ErrorMessage error={error} onRetry={() => { clearError(); refetch(); }} />;
  if (!hasPortfolio) return <NoDataMessage message="No portfolio loaded." />;

  // Transform data for modern component
  const holdingsData = hasPortfolio && data ? {
    summary: {
      totalValue: data.summary?.totalValue || 0,
      lastUpdated: data.summary?.lastUpdated || 'Unknown'
    },
    holdings: (data.holdings || []).map(holding => ({
      // Enhanced fields for modern UI
      ...holding,
      riskScore: holding.riskScore || Math.random() * 10, // TODO: Add from adapter
      aiScore: holding.aiScore || Math.random() * 100,   // TODO: Add from adapter  
      alerts: holding.alerts || 0,                       // TODO: Add from adapter
      trend: holding.trend || []                         // TODO: Add from adapter
    }))
  } : null;

  return (
    <DashboardErrorBoundary>
      <HoldingsView 
        portfolioData={holdingsData}
        connectedAccounts={connections?.map(conn => ({
          name: conn.institution,
          lastSynced: conn.last_updated ? new Date(conn.last_updated).toLocaleString() : 'Never',
          status: conn.status === 'active' ? 'Active' : 'Inactive'
        })) || []}
        onRefresh={handleRefresh}
        onAnalyzeRisk={onAnalyzeRisk}
        isRefreshing={loading || plaidLoading}
        {...props}
      />
      {process.env.NODE_ENV === 'development' && (
        <div className="fixed bottom-4 right-4 bg-blue-100 text-blue-800 px-3 py-1 rounded text-xs">
          Holdings: {hasData ? 'Real' : 'Mock'} | Count: {data?.holdings?.length || 0}
        </div>
      )}
    </DashboardErrorBoundary>
  );
};

export default React.memo(HoldingsViewModernContainer);
```

**Integration Steps:**
- **Hook**: `usePortfolioSummary()` for holdings data
- **Intent**: `'refresh-holdings'` for Plaid sync
- **Props needed**: Modify `HoldingsView.tsx` to accept `portfolioData` prop
- **Enhanced data**: Add `riskScore, aiScore, alerts, trend[]` to adapter

#### 3. **`PerformanceViewContainer.tsx`**
```tsx
/**
 * PerformanceViewContainer - Modern performance analytics with charts
 * New container for enhanced performance visualization
 */
import React, { useEffect } from 'react';
import { usePerformance } from '../../../features/analysis';
import { DashboardErrorBoundary, ErrorMessage, LoadingSpinner, NoDataMessage } from '../shared';
import { frontendLogger } from '../../../services/frontendLogger';
import PerformanceView from '../../portfolio/PerformanceView';
import { IntentRegistry } from '../../../utils/NavigationIntents';

const PerformanceViewContainer = ({ ...props }) => {
  const { data, loading, error, hasData, hasPortfolio, refetch, clearError } = usePerformance();
  
  useEffect(() => {
    frontendLogger.user.action('viewRendered', 'PerformanceView', {
      hasData: !!data, isLoading: loading, hasError: !!error
    });
  }, [data, loading, error]);

  const handleRefreshPerformance = async () => {
    const result = await IntentRegistry.triggerIntent('refresh-performance');
    if (result.success) await refetch();
  };

  if (loading) return <LoadingSpinner message="Loading performance data..." />;
  if (error) return <ErrorMessage error={error} onRetry={() => { clearError(); refetch(); }} />;
  if (!hasPortfolio) return <NoDataMessage message="No portfolio loaded." />;

  return (
    <DashboardErrorBoundary>
      <PerformanceView 
        data={data}
        onRefresh={handleRefreshPerformance}
        {...props}
      />
      {process.env.NODE_ENV === 'development' && (
        <div className="fixed bottom-4 right-4 bg-purple-100 text-purple-800 px-3 py-1 rounded text-xs">
          Performance: {hasData ? 'Real' : 'Mock'}
        </div>
      )}
    </DashboardErrorBoundary>
  );
};

export default React.memo(PerformanceViewContainer);
```

**Integration Steps:**
- **Hook**: `usePerformance()` - may need enhancement for time series data
- **Intent**: `'refresh-performance'` (new intent likely needed; otherwise call `refetch()` directly)
- **Props needed**: Modify `PerformanceView.tsx` to accept `data` prop  
- **New adapter**: `PerformanceAdapter` for time series, benchmarks, attribution

### **Phase 2: Analysis Views (Medium Priority)**

#### 4. **`RiskAnalysisModernContainer.tsx`** 
```tsx
/**
 * RiskAnalysisModernContainer - Use ConnectedRiskAnalysis as template
 * Copy the working ConnectedRiskAnalysis.tsx pattern
 */
// Use existing ConnectedRiskAnalysis.tsx as your template!
// It already demonstrates the correct integration pattern
```

**Integration Steps:**
- **Template**: Use existing `ConnectedRiskAnalysis.tsx` - it's already correct!
- **Hook**: `useRiskAnalysis()` - already integrated
- **Props**: Update `RiskAnalysis.tsx` to accept transformed data
- **Data**: Use existing adapter output, enhance for UI components

### **Phase 3: Advanced Features (Lower Priority)**

#### 5. **`ScenarioAnalysisContainer.tsx`**
```tsx
/**
 * ScenarioAnalysisContainer - What-if analysis and stress testing
 * Requires useWhatIfAnalysis hook development
 */
import React, { useEffect } from 'react';
import { useWhatIfAnalysis } from '../../../features/whatIf'; // ⚠️ Needs implementation
import ScenarioAnalysis from '../../portfolio/ScenarioAnalysis';
// ... standard container pattern
```

**Integration Steps:**
- **Hook**: `useWhatIfAnalysis()` - needs implementation in `features/whatIf/hooks/`
- **Intent**: `'run-scenario'` (new intent needed)
- **Backend**: What-if analysis API endpoints

#### 6. **`StrategyBuilderContainer.tsx`**
```tsx
/**
 * StrategyBuilderContainer - Portfolio optimization and rebalancing
 * Requires usePortfolioOptimization hook development  
 */
import React, { useEffect } from 'react';
import { usePortfolioOptimization } from '../../../features/optimize'; // ⚠️ Needs implementation
import StrategyBuilder from '../../portfolio/StrategyBuilder';
// ... standard container pattern
```

**Integration Steps:**
- **Hooks**: `usePortfolioOptimization()` + `useWhatIfAnalysis()`
- **Intent**: `'optimize-portfolio'` (new intent needed)
- **Backend**: Portfolio optimization API endpoints

#### 7. **`StockLookupContainer.tsx`**
```tsx
/**
 * StockLookupContainer - Enhanced stock search and analysis
 * Extends existing useStockAnalysis with debouncing
 */
import React, { useState, useEffect, useMemo } from 'react';
import { useStockAnalysis } from '../../../features/stockAnalysis';
import StockLookup from '../../portfolio/StockLookup';
import { IntentRegistry } from '../../../utils/NavigationIntents';

const StockLookupContainer = ({ ...props }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedTerm, setDebouncedTerm] = useState('');
  
  // Debounce search term
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedTerm(searchTerm), 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const { data, loading, error, refetch } = useStockAnalysis(debouncedTerm);

  const handleNavigateToResearch = async (symbol: string) => {
    const result = await IntentRegistry.triggerIntent('navigate-to-research', { symbol });
    if (result.success) {
      // Navigate to StockResearchViewContainer
    }
  };

  return <StockLookup 
    searchTerm={searchTerm}
    onSearchChange={setSearchTerm}
    searchResults={data}
    isSearching={loading}
    onSelectStock={handleNavigateToResearch}
    {...props}
  />;
};
```

**Integration Steps:**
- **Hook**: `useStockAnalysis()` with debounced search
- **Intent**: `'navigate-to-research'` for deep stock analysis
- **Enhancement**: May need additional stock data fields

## 🔌 Hook Integration Requirements

### **✅ Ready to Use (Existing Hooks):**
```typescript
usePortfolioSummary()    // PortfolioOverview, HoldingsView - READY
useRiskScore()           // Risk metrics display - READY  
useRiskAnalysis()        // RiskAnalysis, FactorRiskModel - READY
usePerformance()         // PerformanceView - may need enhancement
useAnalysisReport()      // Comprehensive reporting - READY
useStockAnalysis()       // StockLookup - may need enhancement
```

### **⚠️ Need Development/Enhancement:**
```typescript
useWhatIfAnalysis()      // ScenarioAnalysis - placeholder exists, needs implementation
usePortfolioOptimization() // StrategyBuilder - placeholder exists, needs implementation  
usePerformance()         // Enhancement needed for time series data
useStockAnalysis()       // Enhancement needed for enhanced UI data
```

## 🔄 Data Transformation & Adapter Updates

### **1. PortfolioSummaryAdapter Enhancement**
```typescript
// Add fields for PortfolioOverview component
interface PortfolioSummaryOutput {
  summary: {
    totalValue: number;
    dayChange: number;           // ← ADD
    dayChangePercent: number;    // ← ADD  
    ytdReturn: number;          // ← ADD
    sharpeRatio: number;        // ← ADD
    maxDrawdown: number;        // ← ADD
    volatilityAnnual: number;   // ← EXISTS
    riskScore: number;          // ← EXISTS
    lastUpdated: string;        // ← EXISTS
  };
  holdings: Array<{
    // Enhanced fields for modern HoldingsView
    ticker: string;
    name: string; 
    value: number;
    shares: number;
    riskScore: number;          // ← ADD
    aiScore: number;            // ← ADD
    alerts: number;             // ← ADD
    trend: number[];            // ← ADD (price history for sparklines)
    beta: number;               // ← ADD
    volatility: number;         // ← ADD
    isProxy: boolean;           // ← EXISTS
  }>;
}
```

### **2. New PerformanceAdapter** 
```typescript
// Create new adapter for PerformanceView component
interface PerformanceOutput {
  timeSeries: Array<{
    date: string;
    portfolioValue: number;
    benchmarkValue: number;
    portfolioReturn: number;
    benchmarkReturn: number;
  }>;
  periods: {
    '1D': { return: number; benchmark: number; alpha: number };
    '1W': { return: number; benchmark: number; alpha: number };
    '1M': { return: number; benchmark: number; alpha: number };
    '3M': { return: number; benchmark: number; alpha: number };
    '1Y': { return: number; benchmark: number; alpha: number };
    'YTD': { return: number; benchmark: number; alpha: number };
  };
  attribution: {
    sectors: Array<{ name: string; contribution: number }>;
    factors: Array<{ name: string; contribution: number }>;
    security: Array<{ name: string; contribution: number }>;
  };
  benchmarks: Array<{ symbol: string; name: string }>;
}
```

### **3. Enhanced RiskAnalysisAdapter**
```typescript
// Enhance existing adapter for modern RiskAnalysis UI
interface RiskAnalysisOutput {
  // ... existing fields
  riskFactors: Array<{
    id: string;
    name: string;
    level: 'Low' | 'Medium' | 'High' | 'Extreme';
    score: number;
    impact: string;              // ← ADD (dollar impact)
    description: string;         // ← ADD
    mitigation: string;          // ← ADD
    timeline: string;            // ← ADD
  }>;
  hedgingStrategies: Array<{     // ← ADD
    strategy: string;
    cost: string;
    protection: string;
    efficiency: 'High' | 'Medium' | 'Low';
  }>;
}
```

## 🎯 Navigation Intent System Integration

### **New Intents Needed:**
```typescript
// Add to NavigationIntent type in utils/NavigationIntents.ts
type NavigationIntent = 
  | 'refresh-holdings'          // ← EXISTS
  | 'analyze-risk'              // ← EXISTS  
  | 'refresh-performance'       // ← ADD
  | 'export-pdf'               // ← ADD
  | 'export-csv'               // ← ADD  
  | 'optimize-portfolio'       // ← ADD
  | 'run-scenario'             // ← ADD
  | 'lookup-stock'             // ← ADD
  | 'navigate-to-research';    // ← ADD
```

### **Intent Handler Registration:**
```typescript
// In SessionServicesProvider, register new handlers:
IntentRegistry.registerHandler('refresh-performance', async () => {
  const result = await manager.refreshPerformanceData(currentPortfolio.id);
  if (result.success) {
    queryClient.invalidateQueries(['performance']);
  }
});

IntentRegistry.registerHandler('optimize-portfolio', async (payload) => {
  const result = await manager.optimizePortfolio(currentPortfolio.id, payload);
  if (result.success) {
    queryClient.invalidateQueries(['portfolio', 'performance']);
  }
});

IntentRegistry.registerHandler('run-scenario', async (payload) => {
  const result = await manager.runScenario(currentPortfolio.id, payload.scenario);
  return result;
});
```

## 📁 Integration File Structure

```
src/components/
├── dashboard/views/           # Containers (match classic pattern)
│   ├── [EXISTING] Classic containers
│   │   ├── RiskScoreViewContainer.tsx
│   │   ├── HoldingsViewContainer.tsx  
│   │   └── PerformanceAnalyticsViewContainer.tsx
│   │
│   └── [NEW] Modern containers
│       ├── PortfolioOverviewContainer.tsx      # ⭐ Phase 1
│       ├── HoldingsViewModernContainer.tsx     # ⭐ Phase 1
│       ├── PerformanceViewContainer.tsx        # ⭐ Phase 1
│       ├── RiskAnalysisModernContainer.tsx     # Phase 2
│       ├── ScenarioAnalysisContainer.tsx       # Phase 3
│       ├── StrategyBuilderContainer.tsx        # Phase 3
│       └── StockLookupContainer.tsx            # Phase 3
│
├── portfolio/                 # Views (update for props)
│   ├── [MODIFY] Accept props instead of mock data
│   │   ├── PortfolioOverview.tsx       # Add data prop interface
│   │   ├── HoldingsView.tsx            # Add portfolioData prop interface
│   │   ├── PerformanceView.tsx         # Add data prop interface
│   │   ├── RiskAnalysis.tsx            # Add transformed data props
│   │   ├── ScenarioAnalysis.tsx        # Add scenario data props
│   │   ├── StrategyBuilder.tsx         # Add optimization data props
│   │   └── StockLookup.tsx             # Add search results props
│   │
│   └── [READY] Template example
│       └── ConnectedRiskAnalysis.tsx   # Use as template ✅
```

## 📋 Implementation Roadmap

### **Week 1: Core Views Foundation**
1. **Day 1-2**: Create `PortfolioOverviewContainer.tsx` 
   - Modify `PortfolioOverview.tsx` to accept `data` prop
   - Test with real data from `usePortfolioSummary()`
   
2. **Day 3-4**: Create `HoldingsViewModernContainer.tsx`
   - Enhance `PortfolioSummaryAdapter` for additional fields
   - Modify `HoldingsView.tsx` prop interface
   
3. **Day 5**: Create `PerformanceViewContainer.tsx`
   - Create `PerformanceAdapter` for time series data
   - Add `'refresh-performance'` intent

### **Week 2: Analysis Enhancement** 
1. **Day 1-2**: Copy `ConnectedRiskAnalysis.tsx` pattern to `RiskAnalysisModernContainer.tsx`
   - Enhance `RiskAnalysisAdapter` for modern UI data
   - Update `RiskAnalysis.tsx` prop interface
   
2. **Day 3-5**: Test integration with existing dashboard routing
   - Update `ViewRenderer.tsx` to include modern containers
   - Ensure cache sharing works correctly

### **Week 3: Advanced Features**
1. **Day 1-3**: Implement `useWhatIfAnalysis()` hook
   - Create `ScenarioAnalysisContainer.tsx`
   - Add `'run-scenario'` intent
   
2. **Day 4-5**: Implement `usePortfolioOptimization()` hook  
   - Create `StrategyBuilderContainer.tsx`
   - Add `'optimize-portfolio'` intent

## 🎯 Success Metrics

**Integration Complete When:**
- ✅ All 7 container components created following classic pattern
- ✅ All portfolio views accept props instead of using mock data
- ✅ New intents registered and working
- ✅ Adapters enhanced with required data fields
- ✅ Cache sharing working between classic and modern views
- ✅ Error/loading/no-data states handled consistently
- ✅ Development indicators showing "Real" data

**Quality Gates:**
- ✅ Same logging pattern as classic containers
- ✅ Same error boundary usage as classic containers  
- ✅ Same intent system integration as classic containers
- ✅ Same cache invalidation strategy as classic containers
- ✅ No direct API calls from views
- ✅ No Zustand store access from views

This systematic approach ensures your beautiful new UI components integrate seamlessly with your existing, battle-tested architecture while maintaining all the performance, caching, and error handling benefits of your current system.
