# UI Component Creation Template

## Overview
This template provides a step-by-step guide for creating new UI features in the dashboard application. It covers the complete process from navigation integration to component implementation, following the patterns established in the Stock Research feature.

**Clean Architecture**: This template reflects the current clean, modern component architecture. Legacy components have been archived, ensuring a single source of truth for navigation and component patterns.

## Prerequisites
- Understand the app's clean ViewRenderer architecture (single source navigation)
- Familiar with TypeScript, React, and TailwindCSS  
- Know the data structure you're building UI for

**Current Architecture**: The app uses a clean, modern architecture where:
- **Navigation**: `Sidebar.tsx` (single tab renderer)
- **Routing**: `ViewRenderer.tsx` (view switching)  
- **Config**: `/layout/dashboardConfig.ts` (tab definitions)

**Tab Rendering Flow**:
```
/layout/dashboardConfig.ts → Sidebar.tsx → Your Tabs
```

---

## Phase 1: Planning & Architecture

### Step 1: Define Your Feature
**Define these before coding:**

```typescript
// Feature Definition
Feature Name: "Stock Research"
Tab ID: "research" 
Tab Icon: "🔍"
Tab Label: "Stock Research"
Route: "/research" (if using URL routing)

// Data Structure (from backend or mock)
interface FeatureData {
  // Example: StockAnalysisResult structure
  ticker: string;
  volatility_metrics: {
    monthly_vol: number;
    annual_vol: number;
  };
  regression_metrics: {
    beta: number;
    alpha: number;
    r_squared: number;
    idio_vol_m: number;
  };
  // ... etc
}

// Component Hierarchy Planning
FeatureViewContainer (state management, API calls)
├── FeatureSearchInput (user input)
├── FeatureDataDisplay (main results)
│   ├── MetricsCardA (first data section)
│   ├── MetricsCardB (second data section)
│   └── MetricsCardC (third data section)
├── LoadingSpinner (from shared)
└── ErrorMessage (from shared)
```

---

## Phase 2: Navigation Integration

### Step 2: Add Tab to Sidebar Navigation
**File**: `frontend/src/components/dashboard/layout/dashboardConfig.ts`

```typescript
export const DASHBOARD_VIEWS: DashboardView[] = [
  { id: 'score', label: 'Risk Score', icon: '📊' },
  { id: 'factors', label: 'Factor Analysis', icon: '🎯' },
  { id: 'performance', label: 'Performance Analytics', icon: '📈' },
  { id: 'research', label: 'Stock Research', icon: '🔍' }, // ← Add your feature
  { id: 'report', label: 'Analysis Report', icon: '📋' },
  { id: 'settings', label: 'Risk Limits', icon: '⚙️' },
  { id: 'holdings', label: 'Portfolio Holdings', icon: '💼' }
];
```

**Key Pattern**: 
- `id` must be unique and match routing
- `icon` should be descriptive emoji
- `label` appears in sidebar

**Navigation Architecture**: Tabs are rendered by `Sidebar.tsx` component using this configuration. The system uses a clean, single-source architecture with no legacy tab renderers.

### Step 3: Update ViewId Type Definition
**File**: `frontend/src/stores/uiStore.ts`

```typescript
// Add your feature ID to the ViewId type
type ViewId = 'score' | 'factors' | 'performance' | 'holdings' | 'research' | 'report' | 'settings';
//                                                                    ^^^^^^^^^^^
```

### Step 4: Update ViewRenderer (Critical!)
**File**: `frontend/src/components/dashboard/ViewRenderer.tsx`

**4a. Update ViewId Type:**
```typescript
export type ViewId = 'score' | 'holdings' | 'factors' | 'performance' | 'research' | 'report' | 'settings';
//                                                                     ^^^^^^^^^^^
```

**4b. Add Lazy Loading:**
```typescript
const lazyViews = {
  factors: lazy(() => import('./views/FactorAnalysisViewContainer')),
  performance: lazy(() => import('./views/PerformanceAnalyticsViewContainer')),
  research: lazy(() => import('./views/StockResearchViewContainer')), // ← Add your container
  report: lazy(() => import('./views/AnalysisReportView')),
  settings: lazy(() => import('./views/RiskSettingsView'))
};
```

**4c. Add Switch Case:**
```typescript
// Inside the switch statement around line 97
case 'research': {
  const StockResearchViewContainer = lazyViews.research;
  return <StockResearchViewContainer />;
}
```

---

## Phase 3: Container Component

### Step 5: Create Main Container Component
**File**: `frontend/src/components/dashboard/views/{Feature}ViewContainer.tsx`

**Container Responsibilities:**
- State management (search, loading, error, data)
- API calls (mock or real)
- Error handling
- Loading states
- Orchestrate child components

**Template Structure:**
```typescript
import React, { useState, useEffect } from 'react';
import { DashboardErrorBoundary, LoadingSpinner, ErrorMessage } from '../shared';
import { frontendLogger } from '../../../services/frontendLogger';
import FeatureSearchInput from './FeatureSearchInput';
import FeatureDataDisplay from './FeatureDataDisplay';

interface FeatureViewContainerProps {
  [key: string]: any; // Flexible props for future integration
}

// Mock data matching your backend structure
const mockFeatureData = {
  // ... structure matching your backend API
};

const FeatureViewContainer: React.FC<FeatureViewContainerProps> = ({ ...props }) => {
  // State management
  const [inputValue, setInputValue] = useState<string>('');
  const [featureData, setFeatureData] = useState<any>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState<boolean>(false);

  // Component lifecycle logging
  useEffect(() => {
    frontendLogger.user.action('viewRendered', 'FeatureView', {
      hasData: !!featureData,
      isLoading,
      hasError: !!error,
      inputValue
    });
  }, [featureData, isLoading, error, inputValue]);

  // Mock API call (replace with real hook later)
  const handleSearch = async (searchTerm: string) => {
    if (!searchTerm.trim()) {
      setError('Please enter a valid search term');
      return;
    }

    setIsLoading(true);
    setError(null);
    setHasSearched(true);
    
    frontendLogger.user.action('feature-search-initiated', 'FeatureViewContainer', { 
      searchTerm: searchTerm 
    });

    try {
      // Simulate API delay
      await new Promise(resolve => setTimeout(resolve, 1200));
      
      // Mock response with variations based on input
      const mockResponse = {
        ...mockFeatureData,
        searchTerm,
        // Add variations for demo
      };

      setFeatureData(mockResponse);
      setInputValue(searchTerm);

      frontendLogger.user.action('feature-search-success', 'FeatureViewContainer', {
        searchTerm,
        hasData: !!mockResponse
      });

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch data';
      setError(errorMessage);
      
      frontendLogger.error('Feature search failed', 'FeatureViewContainer', 
        err instanceof Error ? err : new Error(String(err)));
    } finally {
      setIsLoading(false);
    }
  };

  const handleClear = () => {
    setFeatureData(null);
    setInputValue('');
    setError(null);
    setHasSearched(false);
    frontendLogger.user.action('feature-search-cleared', 'FeatureViewContainer');
  };

  return (
    <DashboardErrorBoundary>
      <div className="h-full flex flex-col bg-gray-50">
        {/* Header with Search */}
        <div className="bg-white border-b border-gray-200 p-6">
          <div className="max-w-4xl mx-auto">
            <h1 className="text-2xl font-bold text-gray-900 mb-4">Feature Title</h1>
            <p className="text-gray-600 mb-6">
              Feature description and instructions.
            </p>
            
            <FeatureSearchInput
              onSearch={handleSearch}
              onClear={handleClear}
              isLoading={isLoading}
              selectedValue={inputValue}
            />
          </div>
        </div>

        {/* Main Content Area */}
        <div className="flex-1 p-6">
          <div className="max-w-4xl mx-auto">
            {/* Loading State */}
            {isLoading && (
              <div className="flex items-center justify-center py-12">
                <LoadingSpinner message={`Loading ${inputValue}...`} />
              </div>
            )}

            {/* Error State */}
            {error && !isLoading && (
              <ErrorMessage 
                error={error}
                onRetry={() => {
                  setError(null);
                  if (inputValue) {
                    handleSearch(inputValue);
                  }
                }}
              />
            )}

            {/* Results Display */}
            {featureData && !isLoading && !error && (
              <div>
                {/* Mock Mode Indicator */}
                <div className="mb-6">
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <div className="flex items-center">
                      <div className="text-blue-800 text-sm">
                        🚧 <strong>Preview Mode</strong> - Using mock data for UI development
                      </div>
                    </div>
                  </div>
                </div>

                <FeatureDataDisplay featureData={featureData} />
              </div>
            )}

            {/* Empty State (no results) */}
            {!featureData && !isLoading && !error && hasSearched && (
              <div className="text-center py-12">
                <div className="text-gray-500 mb-4">
                  <svg className="w-16 h-16 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    {/* No data icon */}
                  </svg>
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">No data available</h3>
                <p className="text-gray-600">
                  Please try a different search term.
                </p>
              </div>
            )}

            {/* Initial State (no search yet) */}
            {!hasSearched && !isLoading && (
              <div className="text-center py-12">
                <div className="text-gray-400 mb-4">
                  <svg className="w-16 h-16 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    {/* Search icon */}
                  </svg>
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Search for Data</h3>
                <p className="text-gray-600 mb-6">
                  Enter a search term above to get started.
                </p>
                {/* Quick examples if applicable */}
              </div>
            )}
          </div>
        </div>
      </div>
    </DashboardErrorBoundary>
  );
};

export default React.memo(FeatureViewContainer);
```

---

## Phase 4: Input Component

### Step 6: Create Search/Input Component
**File**: `frontend/src/components/dashboard/views/{Feature}SearchInput.tsx`

**Input Component Responsibilities:**
- User input handling
- Validation
- Quick actions/shortcuts
- Clear/reset functionality

**Template Structure:**
```typescript
import React, { useState, useRef } from 'react';
import { frontendLogger } from '../../../services/frontendLogger';

interface FeatureSearchInputProps {
  onSearch: (searchTerm: string) => void;
  onClear: () => void;
  isLoading: boolean;
  selectedValue?: string;
}

const FeatureSearchInput: React.FC<FeatureSearchInputProps> = ({
  onSearch,
  onClear,
  isLoading,
  selectedValue = ''
}) => {
  const [inputValue, setInputValue] = useState<string>('');
  const [validationError, setValidationError] = useState<string>('');
  const inputRef = useRef<HTMLInputElement>(null);

  // Validation function
  const validateInput = (value: string): string | null => {
    const cleanValue = value.trim();
    
    if (!cleanValue) {
      return 'Search term is required';
    }
    
    // Add specific validation rules
    if (cleanValue.length < 1 || cleanValue.length > 20) {
      return 'Search term must be 1-20 characters';
    }
    
    return null;
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setInputValue(value);
    
    if (validationError) {
      setValidationError('');
    }

    frontendLogger.user.action('input-change', 'FeatureSearchInput', {
      inputLength: value.length,
      hasContent: value.length > 0
    });
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSearch();
    }
  };

  const handleSearch = () => {
    const cleanValue = inputValue.trim();
    const validation = validateInput(cleanValue);
    
    if (validation) {
      setValidationError(validation);
      return;
    }

    setValidationError('');
    onSearch(cleanValue);
  };

  const handleClear = () => {
    setInputValue('');
    setValidationError('');
    onClear();
    
    setTimeout(() => {
      inputRef.current?.focus();
    }, 100);
  };

  return (
    <div className="space-y-4">
      {/* Main Input */}
      <div className="flex items-center space-x-3">
        <div className="flex-1 relative">
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={handleInputChange}
            onKeyPress={handleKeyPress}
            placeholder="Enter search term..."
            disabled={isLoading}
            className={`w-full px-4 py-3 text-lg border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100 ${
              validationError 
                ? 'border-red-300 focus:ring-red-500' 
                : 'border-gray-300'
            }`}
          />
          
          {/* Validation Error */}
          {validationError && (
            <p className="mt-1 text-sm text-red-600">{validationError}</p>
          )}
        </div>
        
        {/* Search Button */}
        <button
          onClick={handleSearch}
          disabled={isLoading || !inputValue.trim()}
          className="px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:bg-gray-300 transition-colors"
        >
          {isLoading ? 'Searching...' : 'Search'}
        </button>
        
        {/* Clear Button */}
        {selectedValue && !isLoading && (
          <button
            onClick={handleClear}
            className="px-4 py-3 text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Clear
          </button>
        )}
      </div>

      {/* Quick Actions (if applicable) */}
      {!selectedValue && !isLoading && (
        <div className="flex items-center space-x-2">
          <span className="text-sm text-gray-500">Quick search:</span>
          {['Example1', 'Example2', 'Example3'].map(example => (
            <button
              key={example}
              onClick={() => onSearch(example)}
              className="px-3 py-1 text-sm text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded-md"
            >
              {example}
            </button>
          ))}
        </div>
      )}

      {/* Current Selection Display */}
      {selectedValue && !isLoading && (
        <div className="flex items-center justify-between p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <span className="text-blue-800 font-medium">
            Current: <strong>{selectedValue}</strong>
          </span>
          <button
            onClick={handleClear}
            className="text-blue-600 hover:text-blue-800 text-sm underline"
          >
            Search different term
          </button>
        </div>
      )}
    </div>
  );
};

export default FeatureSearchInput;
```

---

## Phase 5: Data Display Components

### Step 7: Create Main Data Display Component
**File**: `frontend/src/components/dashboard/views/{Feature}DataDisplay.tsx`

```typescript
import React from 'react';
import MetricsCardA from './MetricsCardA';
import MetricsCardB from './MetricsCardB';
import MetricsCardC from './MetricsCardC';

interface FeatureDataDisplayProps {
  featureData: {
    // Your data structure
    searchTerm: string;
    section_a: any;
    section_b: any;
    section_c: any;
    metadata: any;
  };
}

const FeatureDataDisplay: React.FC<FeatureDataDisplayProps> = ({ featureData }) => {
  const { searchTerm, section_a, section_b, section_c } = featureData;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">{searchTerm}</h2>
            <p className="text-gray-600 mt-1">Feature Analysis Results</p>
          </div>
          <div className="text-right">
            <div className="text-sm text-gray-500">Analysis Date</div>
            <div className="text-lg font-medium text-gray-900">
              {new Date().toLocaleDateString()}
            </div>
          </div>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <MetricsCardA data={section_a} searchTerm={searchTerm} />
        <MetricsCardB data={section_b} searchTerm={searchTerm} />
      </div>

      {/* Full-width component if needed */}
      {section_c && (
        <MetricsCardC data={section_c} searchTerm={searchTerm} />
      )}

      {/* Summary Section */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200 p-6">
        <h3 className="text-lg font-semibold text-blue-900 mb-3">Summary</h3>
        {/* Summary content */}
      </div>
    </div>
  );
};

export default FeatureDataDisplay;
```

### Step 8: Create Individual Metrics Cards
**File**: `frontend/src/components/dashboard/views/MetricsCard{A,B,C}.tsx`

**Card Component Pattern:**
```typescript
import React from 'react';

interface MetricsCardAProps {
  data: {
    // Specific data structure for this card
    metric1: number;
    metric2: number;
  };
  searchTerm: string;
}

const MetricsCardA: React.FC<MetricsCardAProps> = ({ data, searchTerm }) => {
  const { metric1, metric2 } = data;

  // Helper functions for interpretation
  const getMetricLevel = (value: number) => {
    if (value > 0.8) return { level: 'High', color: 'red' };
    if (value > 0.5) return { level: 'Medium', color: 'yellow' };
    return { level: 'Low', color: 'green' };
  };

  const metric1Level = getMetricLevel(metric1);

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      {/* Card Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">Section A Metrics</h3>
        <div className={`px-2.5 py-0.5 rounded-full text-xs font-medium bg-${metric1Level.color}-50 text-${metric1Level.color}-800`}>
          {metric1Level.level}
        </div>
      </div>

      {/* Metric Values */}
      <div className="space-y-4">
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Metric 1</span>
            <span className="text-lg font-bold text-gray-900">
              {(metric1 * 100).toFixed(2)}%
            </span>
          </div>
          {/* Visual indicator */}
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div 
              className={`bg-${metric1Level.color}-600 h-2 rounded-full transition-all duration-300`}
              style={{ width: `${metric1 * 100}%` }}
            />
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Metric 2</span>
            <span className="text-lg font-bold text-gray-900">
              {metric2.toFixed(3)}
            </span>
          </div>
        </div>
      </div>

      {/* Interpretation */}
      <div className="mt-4 p-3 bg-gray-50 rounded-lg">
        <h4 className="text-sm font-medium text-gray-900 mb-2">Interpretation</h4>
        <div className="text-sm text-gray-700 space-y-1">
          <div>• {searchTerm} shows {metric1Level.level.toLowerCase()} metric1 levels</div>
          <div>• Metric2 value indicates specific characteristic</div>
        </div>
      </div>
    </div>
  );
};

export default MetricsCardA;
```

---

## Phase 6: Integration & Testing

### Step 9: Import Path Updates
**Update imports in parent components if needed:**

```typescript
// In ViewRenderer.tsx - already handled in Step 4
case 'research': {
  const StockResearchViewContainer = lazyViews.research;
  return <StockResearchViewContainer />;
}
```

### Step 10: Test Navigation Flow
**Testing checklist:**

1. ✅ **Tab appears** in sidebar with correct icon/label
2. ✅ **Tab click** changes active view (highlight state)
3. ✅ **Component loads** without TypeScript errors
4. ✅ **Search functionality** works with validation
5. ✅ **Loading states** display correctly
6. ✅ **Error handling** works for invalid inputs
7. ✅ **Mock data** displays in cards
8. ✅ **Responsive design** works on mobile/tablet

### Step 11: Handle TypeScript Errors
**Common issues and fixes:**

```typescript
// Issue: Import path extensions
❌ import Component from './Component.tsx';
✅ import Component from './Component';

// Issue: JSX character escaping
❌ <span>Beta > 1: High exposure</span>
✅ <span>Beta &gt; 1: High exposure</span>

// Issue: ViewId type mismatches
❌ Missing 'research' in ViewId type definitions
✅ Add to both uiStore.ts AND ViewRenderer.tsx
```

---

## Phase 7: Backend Integration (Future)

### Step 12: Replace Mock Data with Real API
**When backend is ready:**

1. **Create service class** following `ADD_NEW_API_TEMPLATE.md`
2. **Create React hook** with useQuery
3. **Replace mock search function** in container
4. **Remove mock mode indicator**
5. **Add real error handling**

**Quick replacement pattern:**
```typescript
// In FeatureViewContainer.tsx

// Replace this:
const handleSearch = async (searchTerm: string) => {
  // Mock implementation
};

// With this:
const { data, isLoading, error, refetch } = useFeatureSearch();
```

---

## Component File Structure Summary

```
frontend/src/components/dashboard/views/
├── FeatureViewContainer.tsx          ← Main container (state + orchestration)
├── FeatureSearchInput.tsx            ← Search/input interface  
├── FeatureDataDisplay.tsx            ← Main results display
├── MetricsCardA.tsx                  ← First data section
├── MetricsCardB.tsx                  ← Second data section
└── MetricsCardC.tsx                  ← Third data section

frontend/src/components/dashboard/layout/
└── dashboardConfig.ts                ← Add tab configuration

frontend/src/stores/
└── uiStore.ts                        ← Add ViewId type

frontend/src/components/dashboard/
└── ViewRenderer.tsx                  ← Add routing logic
```

---

## Key Patterns & Best Practices

### State Management
- ✅ **Container owns state** (search term, data, loading, error)
- ✅ **Props flow down** to child components
- ✅ **Callbacks flow up** for user actions
- ✅ **useEffect for logging** component lifecycle

### Error Handling
- ✅ **Validation at input level** (immediate feedback)
- ✅ **Try/catch in API calls** (network/server errors)
- ✅ **Error state management** (clear error on new search)
- ✅ **Graceful error UI** (retry buttons, helpful messages)

### Loading States
- ✅ **Loading spinner** with contextual message
- ✅ **Disabled inputs** during loading
- ✅ **Loading button states** ("Searching..." text)

### Responsive Design
- ✅ **Mobile-first approach** (grid-cols-1 md:grid-cols-2)
- ✅ **Flexible layouts** (max-w-4xl containers)
- ✅ **Touch-friendly** (adequate button sizes)

### Accessibility
- ✅ **Proper ARIA labels** for buttons
- ✅ **Keyboard navigation** (Enter to search)
- ✅ **Focus management** (auto-focus on clear)
- ✅ **Color contrast** (error states, indicators)

### Performance
- ✅ **Lazy loading** for secondary views
- ✅ **React.memo** for expensive components
- ✅ **Debounced inputs** (if real-time search)
- ✅ **Efficient re-renders** (useMemo, useCallback)

---

## Template Usage Instructions

1. **Copy this template** for each new UI feature
2. **Replace all instances** of "Feature" with your feature name
3. **Update data structures** to match your backend API
4. **Customize validation rules** for your input requirements
5. **Design metrics cards** based on your data sections
6. **Test thoroughly** before backend integration
7. **Follow naming conventions** consistently

This template provides a complete foundation for building rich, interactive dashboard components that integrate seamlessly with the clean, modern architecture. 

**Architecture Benefits**:
- ✅ **Single source of truth** for navigation (no duplicate tab renderers)
- ✅ **Clean component hierarchy** (legacy components archived)
- ✅ **Modern patterns** (TypeScript, lazy loading, proper state management)
- ✅ **Maintainable codebase** (clear separation of concerns)