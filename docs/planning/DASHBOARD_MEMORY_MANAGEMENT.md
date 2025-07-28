# Dashboard Memory Management Guide

## Overview

This document provides comprehensive memory management patterns for the Risk Analysis Dashboard to prevent memory leaks during long analyst sessions. Analysts may use the dashboard for hours, switching between portfolios, views, and analysis types. Without proper cleanup, memory usage grows indefinitely leading to browser slowdowns and crashes.

## Backend Foundation

The backend already has robust LRU/LFU caching with bounded memory:
- **Price cache**: 256 items (LRU)
- **Portfolio analysis**: 100 items (LRU) 
- **Company profiles**: 1000 items (LFU)
- **GPT peer analysis**: 500 items (LFU)

The frontend needs equivalent discipline to prevent indefinite memory growth.

## Memory Leak Prevention Patterns

### 1. Chart Library Cleanup

**Problem:** Chart libraries (Plotly, D3, Chart.js) create DOM elements, event listeners, and WebGL contexts that must be explicitly cleaned up.

**Solution:**

```typescript
// hooks/useChartCleanup.ts - Automatic chart cleanup
import { useEffect, useRef } from 'react';

export const useChartCleanup = () => {
  const chartInstances = useRef<any[]>([]);
  
  const registerChart = (chartInstance: any, cleanupMethod = 'destroy') => {
    chartInstances.current.push({ instance: chartInstance, cleanup: cleanupMethod });
  };
  
  const cleanupCharts = () => {
    chartInstances.current.forEach(({ instance, cleanup }) => {
      try {
        if (instance && instance[cleanup]) {
          instance[cleanup]();
        }
        // Plotly-specific cleanup
        if (instance && instance.purge) instance.purge();
        // D3-specific cleanup  
        if (instance && instance.remove) instance.remove();
      } catch (error) {
        console.warn('Chart cleanup failed:', error);
      }
    });
    chartInstances.current = [];
  };
  
  useEffect(() => {
    return cleanupCharts; // Cleanup when component unmounts
  }, []);
  
  return { registerChart, cleanupCharts };
};

// Usage in chart components:
const PortfolioChart: React.FC<{ data: ChartData }> = ({ data }) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const { registerChart } = useChartCleanup();
  
  useEffect(() => {
    if (chartRef.current && data) {
      const chart = Plotly.newPlot(chartRef.current, data.traces, data.layout);
      registerChart(chartRef.current, 'purge'); // Register for cleanup
    }
  }, [data, registerChart]);
  
  return <div ref={chartRef} className="chart-container" />;
};
```

### 2. Bounded Data Retention

**Problem:** Analysis datasets can be 50MB+ for detailed factor analysis. Without bounds, data accumulates indefinitely.

**Solution:**

```typescript
// store/dashboardStore.ts - Memory-bounded Zustand store
import { create } from 'zustand';

interface DashboardStore {
  analysisResults: Map<string, AnalysisData>;
  chartDataCache: Map<string, ChartData>;
  recentPortfolios: PortfolioData[];
  
  // Actions with automatic bounds enforcement
  addAnalysisResult: (key: string, data: AnalysisData) => void;
  addChartData: (key: string, data: ChartData) => void;
  addRecentPortfolio: (portfolio: PortfolioData) => void;
  forceMemoryCleanup: () => void;
}

// Memory limits based on typical analysis sizes
const MAX_ANALYSIS_RESULTS = 10;    // ~500MB max (50MB per analysis)
const MAX_CHART_DATA = 20;          // ~200MB max (10MB per chart dataset)
const MAX_RECENT_PORTFOLIOS = 15;   // ~15MB max (1MB per portfolio)

export const useDashboardStore = create<DashboardStore>((set, get) => ({
  analysisResults: new Map(),
  chartDataCache: new Map(),
  recentPortfolios: [],
  
  addAnalysisResult: (key: string, data: AnalysisData) => {
    set(state => {
      const results = new Map(state.analysisResults);
      results.set(key, data);
      
      // Remove oldest entries if over limit
      if (results.size > MAX_ANALYSIS_RESULTS) {
        const oldestKey = results.keys().next().value;
        results.delete(oldestKey);
      }
      
      return { analysisResults: results };
    });
  },
  
  addChartData: (key: string, data: ChartData) => {
    set(state => {
      const cache = new Map(state.chartDataCache);
      cache.set(key, data);
      
      // LRU eviction for chart data
      if (cache.size > MAX_CHART_DATA) {
        const oldestKey = cache.keys().next().value;
        cache.delete(oldestKey);
      }
      
      return { chartDataCache: cache };
    });
  },
  
  addRecentPortfolio: (portfolio: PortfolioData) => {
    set(state => {
      const recent = [...state.recentPortfolios, portfolio];
      // Keep only most recent portfolios
      return { recentPortfolios: recent.slice(-MAX_RECENT_PORTFOLIOS) };
    });
  },
  
  forceMemoryCleanup: () => {
    set({
      analysisResults: new Map(),
      chartDataCache: new Map(),
      recentPortfolios: []
    });
    
    // Suggest garbage collection (browser-dependent)
    if (typeof window !== 'undefined' && (window as any).gc) {
      (window as any).gc();
    }
  }
}));
```

### 3. Event Listener Management

**Problem:** Event listeners accumulate during view switches without cleanup.

**Solution:**

```typescript
// hooks/useEventCleanup.ts - Automatic event listener cleanup
import { useEffect, useRef } from 'react';

type EventListener = {
  target: EventTarget;
  event: string;
  handler: EventListener;
  options?: boolean | AddEventListenerOptions;
};

export const useEventCleanup = () => {
  const listeners = useRef<EventListener[]>([]);
  
  const addListener = (
    target: EventTarget,
    event: string,
    handler: EventListener,
    options?: boolean | AddEventListenerOptions
  ) => {
    target.addEventListener(event, handler, options);
    listeners.current.push({ target, event, handler, options });
  };
  
  const removeAllListeners = () => {
    listeners.current.forEach(({ target, event, handler, options }) => {
      target.removeEventListener(event, handler, options);
    });
    listeners.current = [];
  };
  
  useEffect(() => {
    return removeAllListeners; // Cleanup on unmount
  }, []);
  
  return { addListener, removeAllListeners };
};

// Usage in dashboard components:
const DashboardView: React.FC = () => {
  const { addListener } = useEventCleanup();
  
  useEffect(() => {
    const handleResize = () => { /* resize charts */ };
    const handleKeyboard = (e: KeyboardEvent) => { /* keyboard shortcuts */ };
    const handleVisibilityChange = () => { /* pause/resume updates */ };
    
    // All listeners automatically cleaned up on unmount
    addListener(window, 'resize', handleResize);
    addListener(document, 'keydown', handleKeyboard);
    addListener(document, 'visibilitychange', handleVisibilityChange);
  }, [addListener]);
  
  return <div>Dashboard content...</div>;
};
```

### 4. Heavy Dataset Reference Management

**Problem:** Large analysis datasets held in closures prevent garbage collection.

**Solution:**

```typescript
// hooks/useDatasetCleanup.ts - Explicit reference cleanup
import { useCallback, useRef } from 'react';

export const useDatasetCleanup = () => {
  const datasetRefs = useRef<WeakSet<any>>(new WeakSet());
  
  const processLargeDataset = useCallback(<T, R>(
    dataset: T,
    processor: (data: T) => R,
    onComplete?: (result: R) => void
  ): R => {
    try {
      // Process the dataset
      const result = processor(dataset);
      
      // Track dataset for potential cleanup
      datasetRefs.current.add(dataset);
      
      if (onComplete) {
        onComplete(result);
      }
      
      return result;
    } finally {
      // Explicit reference cleanup (helps garbage collection)
      (dataset as any) = null;
    }
  }, []);
  
  const forceCleanup = useCallback(() => {
    // Clear weak references and suggest GC
    datasetRefs.current = new WeakSet();
    
    if (typeof window !== 'undefined' && (window as any).gc) {
      (window as any).gc();
    }
  }, []);
  
  return { processLargeDataset, forceCleanup };
};

// Usage in analysis components:
const FactorAnalysisView: React.FC = () => {
  const { processLargeDataset } = useDatasetCleanup();
  const [chartData, setChartData] = useState<ChartData | null>(null);
  
  const analyzeFactorData = useCallback(async (rawData: RawAnalysisData) => {
    const processed = processLargeDataset(
      rawData,
      (data) => computeFactorAnalysis(data), // Heavy computation
      (result) => setChartData(result.chartData)
    );
    
    // rawData reference automatically cleaned up
    return processed;
  }, [processLargeDataset]);
  
  // Clear chart data when switching views
  useEffect(() => {
    return () => setChartData(null);
  }, []);
  
  return <div>{chartData && <FactorChart data={chartData} />}</div>;
};
```

### 5. Component Memory Lifecycle

**Master cleanup hook that coordinates all memory management:**

```typescript
// hooks/useMemoryLifecycle.ts - Master memory management
import { useEffect, useRef } from 'react';
import { useChartCleanup } from './useChartCleanup';
import { useEventCleanup } from './useEventCleanup';
import { useDatasetCleanup } from './useDatasetCleanup';

export const useMemoryLifecycle = (componentName: string) => {
  const { cleanupCharts } = useChartCleanup();
  const { removeAllListeners } = useEventCleanup();
  const { forceCleanup: cleanupDatasets } = useDatasetCleanup();
  
  const startTime = useRef(Date.now());
  
  useEffect(() => {
    // Component mounted
    console.log(`📊 ${componentName} mounted`);
    
    return () => {
      // Component unmounting - comprehensive cleanup
      const sessionTime = Date.now() - startTime.current;
      console.log(`🧹 ${componentName} cleanup after ${sessionTime}ms`);
      
      // Cleanup in order of importance
      cleanupCharts();        // Charts (heaviest memory usage)
      removeAllListeners();   // Event listeners
      cleanupDatasets();      // Large dataset references
      
      // Optional: Force garbage collection hint
      if (sessionTime > 300000) { // After 5+ minute sessions
        setTimeout(() => {
          if (typeof window !== 'undefined' && (window as any).gc) {
            (window as any).gc();
          }
        }, 100);
      }
    };
  }, [componentName, cleanupCharts, removeAllListeners, cleanupDatasets]);
};

// Usage in major dashboard components:
const DashboardContainer: React.FC = () => {
  useMemoryLifecycle('DashboardContainer');
  
  return (
    <DashboardProvider>
      {/* Dashboard content */}
    </DashboardProvider>
  );
};
```

## Memory Monitoring (Development)

### Development-Only Memory Monitoring

**Catch leaks early with real-time monitoring:**

```typescript
// hooks/useMemoryMonitoring.ts (dev mode only)
import { useEffect } from 'react';

export const useMemoryMonitoring = (componentName: string) => {
  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    
    const monitorMemory = () => {
      if ('memory' in performance) {
        const memory = (performance as any).memory;
        const used = Math.round(memory.usedJSHeapSize / 1024 / 1024);
        const total = Math.round(memory.totalJSHeapSize / 1024 / 1024);
        
        console.log(`🧠 ${componentName} Memory: ${used}MB / ${total}MB`);
        
        // Warn on high memory usage
        if (used > 512) { // > 512MB
          console.warn(`⚠️ High memory usage in ${componentName}: ${used}MB`);
        }
      }
    };
    
    // Monitor memory every 30 seconds
    const interval = setInterval(monitorMemory, 30000);
    monitorMemory(); // Initial reading
    
    return () => clearInterval(interval);
  }, [componentName]);
};

// Usage:
const DashboardView: React.FC = () => {
  useMemoryMonitoring('DashboardView');
  
  return <div>/* Dashboard content */</div>;
};
```

### Memory Usage Visualization (Optional)

**Real-time memory usage display for development:**

```typescript
// components/MemoryMonitor.tsx (dev mode only)
import { useState, useEffect } from 'react';

interface MemoryStats {
  used: number;
  total: number;
  percentage: number;
}

export const MemoryMonitor: React.FC = () => {
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  
  // Only render in development mode
  if (process.env.NODE_ENV === 'production') return null;
  
  useEffect(() => {
    const updateMemoryStats = () => {
      if ('memory' in performance) {
        const memory = (performance as any).memory;
        const used = Math.round(memory.usedJSHeapSize / 1024 / 1024);
        const total = Math.round(memory.totalJSHeapSize / 1024 / 1024);
        const percentage = Math.round((used / total) * 100);
        
        setMemoryStats({ used, total, percentage });
      }
    };
    
    updateMemoryStats();
    const interval = setInterval(updateMemoryStats, 5000); // Update every 5 seconds
    
    return () => clearInterval(interval);
  }, []);
  
  if (!memoryStats) return null;
  
  const getStatusColor = (percentage: number) => {
    if (percentage > 80) return 'text-red-600 bg-red-100';
    if (percentage > 60) return 'text-yellow-600 bg-yellow-100';
    return 'text-green-600 bg-green-100';
  };
  
  return (
    <div className="fixed bottom-4 right-4 p-3 rounded-lg shadow-lg bg-white border">
      <div className="text-sm font-medium text-gray-700">Memory Usage</div>
      <div className={`text-lg font-bold ${getStatusColor(memoryStats.percentage)}`}>
        {memoryStats.used}MB / {memoryStats.total}MB ({memoryStats.percentage}%)
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
        <div 
          className={`h-2 rounded-full transition-all duration-300 ${
            memoryStats.percentage > 80 ? 'bg-red-500' : 
            memoryStats.percentage > 60 ? 'bg-yellow-500' : 'bg-green-500'
          }`}
          style={{ width: `${Math.min(memoryStats.percentage, 100)}%` }}
        />
      </div>
    </div>
  );
};
```

## Memory Management Principles

### Automated Cleanup
- **All cleanup hooks automatically run** on component unmount
- **No manual cleanup calls** required in component code
- **Fail-safe operation**: cleanup continues even if individual cleanups fail

### Bounded Collections
- **Analysis results**: Max 10 items (~500MB total)
- **Chart data cache**: Max 20 items (~200MB total)  
- **Recent portfolios**: Max 15 items (~15MB total)
- **Total frontend memory target**: <1GB for long sessions

### Performance Monitoring
- **Development-mode memory monitoring** warns at 512MB usage
- **Optional garbage collection hints** after long sessions (5+ minutes)
- **Chart cleanup prioritized** (heaviest memory impact)

### Graceful Degradation
- **Memory limits enforced** with LRU eviction
- **Failed cleanups logged** but don't break functionality
- **WeakSet references** allow natural garbage collection

## Implementation Checklist

### Core Memory Hooks
- [ ] `useChartCleanup` - Chart library cleanup
- [ ] `useEventCleanup` - Event listener management
- [ ] `useDatasetCleanup` - Heavy dataset reference cleanup
- [ ] `useMemoryLifecycle` - Master cleanup coordinator

### Store Configuration
- [ ] Memory-bounded Zustand store with Map collections
- [ ] LRU eviction for analysis results and chart data
- [ ] Force cleanup methods for manual memory management

### Development Tools
- [ ] `useMemoryMonitoring` - Real-time memory tracking
- [ ] `MemoryMonitor` component - Visual memory usage display
- [ ] Console logging for component lifecycle tracking

### Integration Points
- [ ] Chart components use `useChartCleanup`
- [ ] Dashboard views use `useEventCleanup`
- [ ] Analysis components use `useDatasetCleanup`
- [ ] Main dashboard uses `useMemoryLifecycle`

## Production Benefits

- **Prevents browser crashes** during long analyst sessions
- **Maintains responsive performance** after hours of use
- **Automatic cleanup** requires no analyst intervention
- **Memory usage stays bounded** regardless of analysis complexity
- **Graceful performance degradation** instead of hard crashes
- **Development visibility** into memory usage patterns

## Memory Leak Testing

### Manual Testing
1. **Open dashboard** in Chrome DevTools with Memory tab
2. **Switch between views** repeatedly (50+ times)
3. **Take heap snapshots** before/after view switching
4. **Check for growing object counts** (DOM nodes, event listeners, data objects)

### Automated Testing (Optional)
```typescript
// tests/memoryLeaks.test.ts
import { render, cleanup } from '@testing-library/react';
import { DashboardContainer } from '../components/DashboardContainer';

describe('Memory Leak Prevention', () => {
  afterEach(() => {
    cleanup();
    // Force garbage collection in test environment
    if (global.gc) global.gc();
  });
  
  test('should not leak memory after multiple mount/unmount cycles', () => {
    const initialMemory = process.memoryUsage().heapUsed;
    
    // Mount/unmount dashboard 100 times
    for (let i = 0; i < 100; i++) {
      const { unmount } = render(<DashboardContainer />);
      unmount();
    }
    
    // Allow garbage collection
    if (global.gc) global.gc();
    
    const finalMemory = process.memoryUsage().heapUsed;
    const memoryGrowth = finalMemory - initialMemory;
    
    // Memory growth should be minimal (< 10MB for 100 cycles)
    expect(memoryGrowth).toBeLessThan(10 * 1024 * 1024);
  });
});
```

This comprehensive memory management system ensures the dashboard remains performant during extended analyst sessions while providing clear visibility into memory usage patterns during development. 