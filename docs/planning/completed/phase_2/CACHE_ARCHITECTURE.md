# Cache Architecture Patterns

This document explains the caching architecture evolution and patterns used in the frontend application.

## Overview

The application uses a multi-layered caching strategy with TanStack Query at the frontend level and various backend cache services. However, there are **two distinct patterns** for how data is cached, which can cause conflicts if not properly managed.

## The Two Caching Patterns

### 🔴 Legacy Pattern: Cache Raw API Responses

**Used by older hooks like usePortfolioSummary**

```typescript
// ❌ LEGACY PATTERN
const { data } = useQuery({
  queryKey: ['some-data', portfolioId],
  queryFn: async () => {
    const result = await manager.getSomeData(portfolioId);
    return result.raw_data; // Cache raw API response
  }
});

// Transform data in component/view
const transformedData = SomeAdapter.transform(data);
```

**Characteristics:**
- Caches raw API responses directly
- Data transformation happens in components/views
- Data structure: `{success: true, some_field: {...}, other_field: [...]}`
- Prone to inconsistent data structures across components

### ✅ Modern Pattern: Cache Transformed Data

**Used by newer hooks like usePerformance, useRiskAnalysis**

```typescript
// ✅ MODERN PATTERN  
const { data } = useQuery({
  queryKey: ['some-data', portfolioId],
  queryFn: async () => {
    const result = await manager.getSomeData(portfolioId);
    const transformedData = someAdapter.transform(result.raw_data);
    return transformedData; // Cache UI-ready data
  }
});

// Data is already transformed and ready for UI consumption
```

**Characteristics:**
- Caches transformed, UI-ready data structures
- Data transformation happens in hooks via adapters
- Data structure: `{field1: value, field2: {...}, field3: [...]}`
- Consistent, typed data structures across all components

## Cache Conflict Problems

### The Intermittency Issue

When **both patterns use the same TanStack Query cache key**, they create cache pollution:

```typescript
// 🚨 CONFLICT: Both hooks use same cache key but cache different data formats

// Legacy hook
useQuery({
  queryKey: ['performance', portfolioId], // Same key
  queryFn: () => manager.getPerformance().then(r => r.raw_data) // Raw data
});

// Modern hook  
useQuery({
  queryKey: ['performance', portfolioId], // Same key
  queryFn: () => manager.getPerformance().then(r => adapter.transform(r.raw_data)) // Transformed data
});
```

**Result:** Intermittent behavior based on which hook loads first:
- If legacy loads first → Modern hook gets raw data, causes "N/A" display issues
- If modern loads first → Legacy hook gets transformed data, causes structure mismatch errors

### Real Examples: Cache Conflicts We Fixed

**EXAMPLE 1: Performance Data Conflict**

**Problem:**
```typescript
// usePortfolioSummary (Legacy)
queryKey: performanceKey(portfolioId), // 'performance', portfolioId  
return result.performance; // Raw: {success: true, performance_metrics: {...}}

// usePerformance (Modern)
queryKey: performanceKey(portfolioId), // Same key!
return adapter.transform(result.performance); // Transformed: {risk: {...}, returns: {...}}
```

**Solution:**
```typescript
// usePortfolioSummary (Legacy) - Separate cache key
queryKey: ['performance-raw', portfolioId], // Different key
return result.performance; // Raw data, separate cache

// usePerformance (Modern) 
queryKey: ['performance', portfolioId], // Original key
return adapter.transform(result.performance); // Transformed data, separate cache
```

**EXAMPLE 2: Risk Analysis Data Conflict**

**Problem:**
```typescript
// usePortfolioSummary (Legacy)
queryKey: riskAnalysisKey(portfolioId), // 'risk-analysis', portfolioId
return result.analysis; // Raw: {portfolio_factor_betas: {...}, variance_decomposition: {...}}

// useRiskAnalysis (Modern)
queryKey: riskAnalysisKey(portfolioId), // Same key!  
return adapter.transform(result.analysis); // Transformed: {portfolio_summary: {...}, risk_metrics: {...}}
```

**Solution:**
```typescript
// usePortfolioSummary (Legacy) - Separate cache key
queryKey: ['risk-analysis-raw', portfolioId], // Different key
return result.analysis; // Raw data, separate cache

// useRiskAnalysis (Modern)
queryKey: ['risk-analysis', portfolioId], // Original key
return adapter.transform(result.analysis); // Transformed data, separate cache
```

## Best Practices

### 1. Use Separate Cache Keys for Different Data Formats

```typescript
// ✅ GOOD: Separate cache keys for different data formats
const rawDataKey = ['performance-raw', portfolioId];
const transformedDataKey = ['performance', portfolioId];
```

### 2. Prefer Modern Pattern for New Code

```typescript
// ✅ PREFERRED: Cache transformed data
const { data } = useQuery({
  queryKey: transformedDataKey,
  queryFn: async () => {
    const result = await manager.getData(portfolioId);
    return adapter.transform(result.data);
  }
});
```

### 3. Migrate Legacy Code Gradually

When migrating from legacy to modern pattern:

1. **First**: Change cache key to avoid conflicts
2. **Then**: Gradually migrate to adapter-based transformation
3. **Finally**: Update all consumers to expect transformed data

### 4. Document Cache Key Usage

Always document what data format a cache key contains:

```typescript
// Cache key documentation
const CACHE_KEYS = {
  // Raw API responses (legacy pattern)
  PERFORMANCE_RAW: ['performance-raw', portfolioId],
  RISK_ANALYSIS_RAW: ['risk-analysis-raw', portfolioId],
  
  // Transformed data (modern pattern)  
  PERFORMANCE: ['performance', portfolioId],
  RISK_ANALYSIS: ['risk-analysis', portfolioId],
};
```

## Migration Strategy

### For Existing Legacy Hooks

1. **Identify** hooks using legacy pattern (cache raw data)
2. **Separate** cache keys to avoid conflicts with modern hooks
3. **Plan** gradual migration to modern pattern
4. **Update** documentation to reflect cache separation

### For New Development

1. **Always** use modern pattern (cache transformed data)
2. **Use** adapters for data transformation
3. **Choose** descriptive cache keys that indicate data format
4. **Document** expected data structures

## Debugging Cache Issues

### Signs of Cache Conflicts

- Intermittent "N/A" or undefined values
- Data structure errors (accessing properties that don't exist)
- Inconsistent data formats between page loads
- TypeScript errors about missing properties

### Investigation Steps

1. Check if multiple hooks use the same cache key
2. Verify data formats cached by each hook
3. Look for raw vs transformed data mismatches
4. Add logging to see what data structure is being cached/retrieved

### Common Solutions

1. **Separate cache keys** for different data formats
2. **Ensure consistent transformation** across all consumers
3. **Migrate to modern pattern** for new development
4. **Document cache key ownership** and data formats