# Debugging Complex Data Flows

## The Challenge
Modern web apps with multiple data sources, caching layers, and state management can be overwhelming to debug. Here's a systematic approach for tackling complex flow issues.

## Mental Models That Help

### 1. Map the Flow Visually
```
User Action → Frontend State → API Call → Backend Processing → Response → State Update → UI Re-render
     ↓              ↓           ↓              ↓             ↓           ↓           ↓
  (specific)    (which store)  (which API)   (DB changes)  (what data) (merge logic) (what changes)
```

### 2. Define Ownership Boundaries
- **External APIs**: Raw data only (Plaid holdings, market data)
- **Backend**: Business logic, persistence, validation
- **Frontend State**: UI concerns, identity mapping, caching
- **Repository Layer**: Data integrity, business rules enforcement

### 3. Use Logs as Breadcrumbs
- **Performance logs**: Show expensive operations and timing
- **Error logs**: Reveal where assumptions break down
- **Frontend logs**: Trace user actions and state changes
- **Backend logs**: Follow data transformations and saves

## Debugging Strategy

### Step 1: Isolate the Failing Component
- Don't try to understand the entire flow at once
- Focus on the specific error or unexpected behavior
- Trust that other components work until proven otherwise

### Step 2: Trace Backwards from the Error
- Start with the error message/symptom
- Work backwards through the logs to find the root cause
- Look for missing data, wrong assumptions, or identity mismatches

### Step 3: Verify Assumptions About Data Shape
- Check what each layer expects vs. what it receives
- Look for missing required fields (like `portfolio_name` in our case)
- Verify identity mappings between systems

## Common Patterns in Our System

### Portfolio Identity Management
- **Backend expects**: `portfolio_name` as identifier
- **Frontend uses**: `id` for UI state management
- **External APIs**: Don't know about our identity system
- **Fix pattern**: Always preserve both when updating

### Update vs Create Operations
- **Updates**: Should preserve existing identity and merge new data
- **Creates**: Can generate new identity
- **Refreshes**: Are updates, not creates (preserve all metadata)

### Cache Invalidation
- **React Query**: Needs explicit invalidation after updates
- **Frontend State**: Repository handles merge logic
- **Backend Cache**: Factor proxies, analysis results need careful handling

## When Complexity Is Normal

This level of complexity is expected for:
- Financial applications (multiple data sources, strict consistency)
- Real-time dashboards (live data + expensive computations)
- Multi-tenant systems (user-specific + shared reference data)
- Apps with external APIs + local optimizations

## Tools That Help

1. **Structured Logging**: Time-stamped, categorized log entries
2. **Repository Pattern**: Single entry point for data operations
3. **Type Safety**: Catch data shape mismatches at compile time
4. **Integration Tests**: Verify end-to-end flows work as expected

## Example: Portfolio Refresh Bug

**Symptom**: "PortfolioRepository: portfolio missing id and/or portfolio_name"
**Root Cause**: Plaid API returns `Portfolio` object without `portfolio_name` field
**Fix**: Preserve existing portfolio identity during refresh operations
**Lesson**: Update operations must explicitly maintain entity identity across system boundaries

---

*Remember: Complex systems are complex for good reasons. Don't feel bad about needing to think through the interactions carefully - that's part of building robust software.*