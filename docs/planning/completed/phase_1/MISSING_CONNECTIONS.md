
Perfect! Let me analyze all the errors we encountered and create a comprehensive list of **broken data connections** that were exposed by removing mock data:

## 📋 **Broken Data Connections Discovered**

### **🔍 Error Analysis Summary:**

From the TypeScript errors and surgical mock removal, here are the **broken data connections** we found:

## **1. FactorAnalysisView - Missing Portfolio Data Flow**
- **Error**: `Property 'portfolioData' is missing in type` in FactorAnalysisViewContainer
- **Issue**: `FactorAnalysisViewContainer` doesn't pass `portfolioData` to `FactorAnalysisView`
- **Connection Broken**: Portfolio holdings data → Factor Analysis component
- **Current Workaround**: We set `portfolioData={null}` temporarily

## **2. SummaryBar - Missing Portfolio Data Interface**  
- **Error**: `Binding element 'portfolioData' implicitly has an 'any' type`
- **Issue**: Component expects portfolio data but has no type interface
- **Connection Broken**: Portfolio summary data → SummaryBar component
- **Current Workaround**: Added basic TypeScript interface

## **3. FactorAnalysisView - Extensive Hardcoded Mock Data**
- **Error**: Multiple `implicitly has an 'any' type` errors
- **Issue**: Component has extensive hardcoded default data instead of real data flows
- **Connections Broken**: 
  - Beta exposure data (mainFactors, industryProxies)
  - Correlation matrix data 
  - Risk metrics data
  - Portfolio holdings mapping
- **Current Workaround**: Added TypeScript annotations, but still using hardcoded defaults

## **4. HoldingsViewContainer - Graceful Degradation**
- **Status**: ✅ **Working correctly!**
- **Behavior**: Now returns `null` when no real portfolio data, shows broken connection clearly
- **This is exactly what we wanted** - clear diagnostic

## **5. DashboardContainer - Graceful Degradation**
- **Status**: ✅ **Working correctly!** 
- **Behavior**: Now returns `null` for portfolio data, `'Unknown'` for timestamps
- **This is exactly what we wanted** - clear diagnostic

## **6. Performance Analytics - Missing Data Flow**
- **Issue**: `PerformanceAnalyticsView` was using `mockPerformanceData` fallback
- **Connection Broken**: Performance metrics data → Performance view
- **Current Status**: Now gets `undefined` when no real performance data

---

## 🎯 **Priority List - Broken Data Connections to Fix:**

### **🔴 High Priority:**
1. **Factor Analysis Portfolio Data** - `FactorAnalysisViewContainer` needs to pass real portfolio data
2. **Factor Analysis Real Data Flow** - Replace hardcoded defaults with real factor analysis data
3. **Performance Analytics Data Flow** - Connect real performance data instead of mock fallbacks

### **🟡 Medium Priority:**  
4. **SummaryBar Data Flow** - Connect real portfolio summary data
5. **Correlation Matrix Data** - Real correlation data instead of hardcoded matrix

### **🟢 Low Priority (Already Working):**
6. **Holdings Data Flow** - ✅ Already working correctly with graceful degradation
7. **Dashboard Portfolio Summary** - ✅ Already working correctly with graceful degradation

---

## 📊 **What This Tells Us:**

**Good News:** 
- ✅ **Holdings data flow** is working (minimal errors)
- ✅ **Dashboard container** handles missing data gracefully  
- ✅ **Basic portfolio loading** is functional

**Areas Needing Work:**
- ❌ **Factor Analysis** is mostly hardcoded mock data
- ❌ **Performance Analytics** needs real data hookup  
- ❌ **Summary components** need proper data interfaces

This gives us a **clear roadmap** of what needs to be connected! 🗺️

Great question! Let's find unused code and modules. There are several ways to detect unused code in our project:
```bash
cd frontend && npx depcheck
```
```bash
cd frontend && npx ts-prune
```
Let me fix that - I'm already in the frontend directory:
```bash
npx depcheck
```
```bash
npx ts-prune
```
Excellent! This gives us great insights. Let me also check for unused files and run a more targeted analysis:
```bash
find src -name "*.tsx" -o -name "*.ts" -o -name "*.jsx" -o -name "*.js" | head -20
```
Ran tool
Great! Now let me create a comprehensive summary of what we found and suggest cleanup actions:

## 🧹 **Unused Code Analysis Results**

### **✅ Good News - Old DashboardApp Cleaned Up**
No references found to the old `components/dashboard/DashboardApp` path - you successfully removed that!

### **📦 Unused Dependencies (Safe to Remove)**
```bash
npm uninstall @testing-library/dom @testing-library/react @testing-library/user-event react-plaid-link
```

### **🛠️ Unused DevDependencies (Testing/Build Tools)**
```bash
npm uninstall -D @babel/core @babel/plugin-transform-runtime @babel/preset-env @babel/preset-react @babel/preset-typescript autoprefixer babel-jest cypress identity-obj-proxy jest-environment-jsdom msw postcss
```

### **🔍 Potentially Unused Code Files**

Based on `ts-prune` results, these exports appear unused and **could be candidates for removal**:

**High Priority (Likely Safe to Remove):**
- `src/pages/InstantTryPage.tsx` - InstantTryPage
- `src/hooks/usePlaid.ts` - usePlaid (we're using the intent system instead)
- `src/hooks/usePortfolioData.ts` - useAllPortfolios, useCurrentPortfolioData
- `src/chassis/managers/ChatManager.ts` - ChatManager
- `src/chassis/managers/PlaidManager.ts` - PlaidManager

**Medium Priority (Review Before Removing):**
- `src/components/RequireAuth.tsx` - RequireAuth component
- `src/router/AppRouter.tsx` - AppRouter (vs AppOrchestrator)
- Multiple index.ts exports that may be for future use

### **🎯 Recommended Cleanup Steps**
Ran tool
Want me to start with any of these cleanup tasks? I'd recommend starting with:

1. **Remove unused dependencies** (quickest win)
2. **Check specific files** like `InstantTryPage` and `usePlaid` 
3. **Review unused managers** like `ChatManager`

This will help declutter your codebase and make it easier to navigate! Which would you like to tackle first?