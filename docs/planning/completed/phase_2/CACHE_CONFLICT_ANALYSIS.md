# Cache Conflict Analysis - Complete Audit

## Summary

**CONFLICTS FOUND: 3 Total - ALL RESOLVED! ✅**
- ✅ **FIXED**: Performance data conflict (usePerformance vs usePortfolioSummary)
- ✅ **FIXED**: Risk analysis data conflict (useRiskAnalysis vs usePortfolioSummary)  
- ✅ **FIXED**: Risk score data conflict (useRiskScore vs usePortfolioSummary)

## Complete Cache Key Usage Map

| Query Key | Hook 1 | Data Format 1 | Hook 2 | Data Format 2 | Status |
|-----------|---------|---------------|---------|---------------|--------|
| `performanceKey(id)` | usePerformance | TRANSFORMED | ~~usePortfolioSummary~~ | ~~RAW~~ | ✅ **FIXED** |
| `riskAnalysisKey(id)` | useRiskAnalysis | TRANSFORMED | ~~usePortfolioSummary~~ | ~~RAW~~ | ✅ **FIXED** |
| `riskScoreKey(id)` | useRiskScore | TRANSFORMED | ~~usePortfolioSummary~~ | ~~RAW~~ | ✅ **FIXED** |
| `analysisReportKey(id)` | useAnalysisReport | TRANSFORMED | - | - | ✅ Safe |
| `portfolioOptimizationKey(id, strategy)` | usePortfolioOptimization | TRANSFORMED | - | - | ✅ Safe |
| `whatIfAnalysisKey(id, scenario)` | useWhatIfAnalysis | TRANSFORMED | - | - | ✅ Safe |
| `riskSettingsKey(id)` | useRiskSettings | TRANSFORMED | - | - | ✅ Safe |
| `stockAnalysisKey(ticker)` | useStockAnalysis | TRANSFORMED | - | - | ✅ Safe |
| `plaidConnectionsKey(userId)` | usePlaid | TRANSFORMED | - | - | ✅ Safe |
| `plaidHoldingsKey(userId)` | usePlaid | TRANSFORMED | - | - | ✅ Safe |
| `snaptradeConnectionsKey(userId)` | useSnapTrade | TRANSFORMED | - | - | ✅ Safe |
| `snaptradeHoldingsKey(userId)` | useSnapTrade | TRANSFORMED | - | - | ✅ Safe |
| `chatContextKey(id)` | useChat, usePortfolioChat | SAME FORMAT | - | - | ✅ Safe |
| `initialPortfolioKey` | PortfolioInitializer | RAW | - | - | ✅ Safe |

## Detailed Conflict Analysis

### ✅ FIXED CONFLICT: Risk Score Data (RESOLVED)

**Before:**
```typescript
useRiskScore:          ['riskScore', portfolioId] → TRANSFORMED
usePortfolioSummary:   ['riskScore', portfolioId] → RAW
```

**After:**
```typescript
useRiskScore:          ['riskScore', portfolioId] → TRANSFORMED  
usePortfolioSummary:   ['risk-score-raw', portfolioId] → RAW
```

### ✅ FIXED CONFLICTS

#### 1. Performance Data (RESOLVED)
**Before:**
```typescript
usePerformance:        ['performance', portfolioId] → TRANSFORMED
usePortfolioSummary:   ['performance', portfolioId] → RAW
```

**After:**
```typescript
usePerformance:        ['performance', portfolioId] → TRANSFORMED  
usePortfolioSummary:   ['performance-raw', portfolioId] → RAW
```

#### 2. Risk Analysis Data (RESOLVED)  
**Before:**
```typescript
useRiskAnalysis:       ['riskAnalysis', portfolioId] → TRANSFORMED
usePortfolioSummary:   ['riskAnalysis', portfolioId] → RAW
```

**After:**
```typescript
useRiskAnalysis:       ['riskAnalysis', portfolioId] → TRANSFORMED
usePortfolioSummary:   ['risk-analysis-raw', portfolioId] → RAW
```

## Root Cause Analysis

### The usePortfolioSummary Problem

The `usePortfolioSummary` hook is a **legacy aggregation pattern** that:

1. **Uses multiple useQueries** to fetch data from different sources
2. **Caches RAW API responses** (legacy pattern)
3. **Shares cache keys** with modern hooks that cache transformed data
4. **Creates race conditions** based on load order

### Why This Architecture Exists

`usePortfolioSummary` was designed to:
- Aggregate data from multiple APIs for summary display
- Share cache keys with individual hooks for performance
- Provide instant loading when individual views populate cache

**But it breaks the modern adapter pattern!**

## Recommended Fixes

### Option 1: Cache Key Separation (QUICK FIX)
Separate cache keys like we did for performance and risk analysis:

```typescript
// usePortfolioSummary.ts - Change risk score key
queryKey: ['risk-score-raw', currentPortfolio?.id],  // Different key
return result.riskScore; // Keep raw data for legacy compatibility
```

### Option 2: Unified Transformation (ARCHITECTURAL FIX)
Migrate usePortfolioSummary to use transformed data:

```typescript
// usePortfolioSummary.ts - Use same key, transform data
queryKey: riskScoreKey(currentPortfolio?.id),        // Same key as useRiskScore
queryFn: async () => {
  const result = await manager.calculateRiskScore(currentPortfolio.id!);
  return riskScoreAdapter.transform(result.riskScore); // Transform like useRiskScore
}
```

### Option 3: Shared Hook Strategy (FUTURE)
Create a shared hook that both can use:

```typescript
// New: useSharedRiskScore.ts
export const useSharedRiskScore = () => {
  const { data } = useQuery({
    queryKey: riskScoreKey(portfolioId),
    queryFn: () => manager.calculateRiskScore().then(r => adapter.transform(r.riskScore))
  });
  return { data };
};

// useRiskScore.ts and usePortfolioSummary.ts both use useSharedRiskScore
```

## Prevention Strategy

### 1. Naming Convention
Use different cache key patterns for different data formats:

```typescript
// Raw data keys
const rawDataKey = (type: string, id: string) => [`${type}-raw`, id];

// Transformed data keys  
const transformedDataKey = (type: string, id: string) => [type, id];
```

### 2. Documentation Requirements
Every hook using TanStack Query must document:
- **Cache key used**
- **Data format cached** (raw vs transformed)
- **Dependencies on other hooks**

### 3. Centralized Cache Key Registry
Maintain a registry tracking:
- Which hooks use which keys
- What data format each key contains
- Dependencies between hooks

### 4. Automated Conflict Detection
Create a script/test to:
- Scan all `useQuery` calls
- Extract cache keys and data formats
- Flag potential conflicts
- Run in CI/CD pipeline

## Next Steps

1. **IMMEDIATE**: Fix the risk score cache conflict
2. **SHORT-TERM**: Audit all remaining shared data flows
3. **LONG-TERM**: Migrate usePortfolioSummary to modern pattern
4. **PREVENTION**: Implement conflict detection tooling