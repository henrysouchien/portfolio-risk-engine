# Modern UI Integration Plan

## 📋 **IMPLEMENTATION STATUS UPDATE** (Current as of audit)

### ✅ **COMPLETED: Core Modern UI Architecture**
- **Modern UI Foundation** ✅ - ModernDashboardApp.tsx (941 lines) fully implemented
- **Container Architecture** ✅ - All 8 modern containers implemented and wired
- **Navigation System** ✅ - Keyboard shortcuts (⌘1-⌘8), view switching, command palette
- **Data Integration** ✅ - React Query + Adapter pattern + Zustand stores
- **Error Handling** ✅ - Loading states, error boundaries, retry mechanisms
- **Authentication** ✅ - Google OAuth integration, session management
- **Responsive Design** ✅ - Mobile-first, glass morphism, Tailwind CSS
- **AI Integration** ✅ - Chat interface, full-screen and modal modes

### ❌ **STILL NEEDS IMPLEMENTATION: Feature Completeness**

#### **🔴 HIGH PRIORITY - Intent System (5 TODOs)**
**Location**: `frontend/src/providers/SessionServicesProvider.tsx:329-352`
- **export-pdf** ❌ - Currently placeholder logging only
- **export-csv** ❌ - Currently placeholder logging only  
- **optimize-portfolio** ❌ - Currently placeholder logging only
- **run-scenario** ❌ - Currently placeholder logging only
- **backtest-strategy** ❌ - Currently placeholder logging only

#### **🔴 HIGH PRIORITY - Holdings Data Enhancement (8 TODOs)**
**Location**: `frontend/src/adapters/PortfolioSummaryAdapter.ts:389-394`
- **sector** ❌ - Currently null (need sector classification per holding)
- **assetClass** ❌ - Currently null (need asset class per holding)
- **avgCost** ❌ - Currently null (need average cost basis per holding)
- **currentPrice** ❌ - Currently null (need current price per holding)
- **volatility** ❌ - Currently null (need per-holding volatility)
- **aiScore** ❌ - Currently null (need AI score per holding)
- **alerts** ❌ - Currently 0 (need alert count per holding)
- **trend** ❌ - Currently empty array (need sparkline data per holding)

#### **🔴 HIGH PRIORITY - Mock Component Integration (4 TODOs)**
**Location**: `frontend/src/components/apps/ModernDashboardApp.tsx:58-61`
- **AssetAllocation** ❌ - Currently mock data (need real adapter integration)
- **FactorRiskModel** ❌ - Currently mock data (need real adapter integration)
- **RiskMetrics** ❌ - Currently mock data (need real adapter integration)
- **PerformanceChart** ❌ - Currently mock data (need real adapter integration)

#### **🔴 MEDIUM PRIORITY - Advanced Features (15+ TODOs)**
**Locations**: Various container files
- **Strategy Saving** ❌ - `StrategyBuilderContainer.tsx:254-261` (backend API needed)
- **Backtesting Engine** ❌ - `StrategyBuilderContainer.tsx` (historical analysis)
- **Short-term Performance** ❌ - `PerformanceAdapter.ts:556-567` (1D, 1W data missing)
- **Stock Analysis** ❌ - `StockLookupContainer.tsx` (33+ enhancements needed)
- **Scenario Templates** ❌ - `ScenarioAnalysisContainer.tsx` (11+ enhancements)

### 🎯 **IMPLEMENTATION ROADMAP**:
**Phase 1**: Intent system implementation (export, optimization, backtesting)
**Phase 2**: Holdings data enhancement (sector, prices, volatility, AI scores)
**Phase 3**: Mock component integration (real adapters for AssetAllocation, etc.)
**Phase 4**: Advanced features (strategy saving, comprehensive backtesting)

---

## Purpose
- Capture the end-to-end plan to complete and verify the integration of the new modern UI with the existing frontend infrastructure (stores, hooks, adapters, intents).
- Provide a single, actionable reference for remaining work and QA.

## Current Status (Completed - Core Architecture)
- Modern containers wired in ModernDashboardApp: Overview, Holdings, Performance, Risk Analysis, Scenarios, Strategies.
- Keyboard shortcuts: ⌘1..⌘5, ⌘8 (Scenarios).
- uiStore updated with `scenarios` view.
- Notification popover layering fixed (header z-index to 50; popover absolute within header).
- PortfolioSummaryAdapter extended:
  - Summary metrics (with performance-derived fallbacks): dayChange, dayChangePercent, ytdReturn, sharpeRatio, maxDrawdown.
  - Per-holding analytics: weight (%), factorBetas (from stock betas), riskContributionPct (from euler variance).
- usePortfolioSummary fetches in parallel: riskScore, riskAnalysis, performance → adapter.transform.
- PerformanceViewContainer mapping added; PerformanceView loading/controls integrated (isBusy).
- HoldingsView uses adapter values (no random placeholders); still has TODOs for sector/assetClass/price/returns.
- RiskAnalysis modern container wired; RiskAnalysis view accepts props and uses data when present.
- StockLookup presentational view uses props only; ModernDashboard uses StockLookupContainer.
- Intents registered: refresh-holdings, connect-account, analyze-risk, refresh-performance, refresh-risk-analysis, navigate-to-(research|scenarios|strategies), export-(pdf|csv) [TODO], optimize-portfolio [TODO], run-scenario [TODO], backtest-strategy [TODO].

## ❌ **REMAINING WORK (High Value) - DETAILED IMPLEMENTATION TASKS**

### **🔴 CRITICAL: Intent System Implementation**
**File**: `frontend/src/providers/SessionServicesProvider.tsx`
**Lines**: 329-352
**Status**: ❌ **ALL PLACEHOLDER IMPLEMENTATIONS**

```typescript
// CURRENT STATE: All intents only log to console
const exportPdfHandler = async (payload?: any) => {
  // TODO: Implement actual export via backend or client-side generator
};
const exportCsvHandler = async (payload?: any) => {
  // TODO: Implement actual export via backend or client-side generator  
};
const optimizePortfolioHandler = async (payload?: any) => {
  // TODO: Call manager.optimizePortfolio when backend is available
};
const runScenarioHandler = async (payload?: any) => {
  // TODO: Call manager.analyzeWhatIfScenario when backend is available
};
const backtestStrategyHandler = async (payload?: any) => {
  // TODO: Call backtest service/endpoint when available
};
```

**IMPLEMENTATION NEEDED**:
- ❌ **export-pdf**: Implement PDF generation (client-side or backend endpoint)
- ❌ **export-csv**: Implement CSV export functionality  
- ❌ **optimize-portfolio**: Wire to real backend optimization services
- ❌ **run-scenario**: Connect to scenario analysis backend
- ❌ **backtest-strategy**: Implement backtesting service integration

### **🔴 CRITICAL: PortfolioSummaryAdapter Holdings Enhancement**
**File**: `frontend/src/adapters/PortfolioSummaryAdapter.ts`
**Lines**: 389-394
**Status**: ❌ **8 MAJOR DATA GAPS**

```typescript
// CURRENT STATE: All enhanced holding fields are null/empty
return {
  // ... existing fields work correctly
  beta: factorBetas['market'] ?? null, // TODO: Confirm market factor key naming
  volatility: null,     // TODO: Provide per-holding volatility when available
  aiScore: null,        // TODO: Provide AI score per holding
  alerts: 0,           // TODO: Provide alert count per holding  
  trend: [] as number[], // TODO: Provide sparkline data per holding
  // MISSING FIELDS NEED TO BE ADDED:
  sector: null,         // TODO: Add sector classification per holding
  assetClass: null,     // TODO: Add asset class per holding
  avgCost: null,        // TODO: Add average cost basis per holding
  currentPrice: null,   // TODO: Add current price per holding
};
```

**IMPLEMENTATION NEEDED**:
- ❌ **sector**: Add sector classification per holding (backend data source needed)
- ❌ **assetClass**: Add asset class per holding (backend data source needed)
- ❌ **avgCost**: Add average cost basis per holding (backend data source needed)
- ❌ **currentPrice**: Add current price per holding (backend data source needed)
- ❌ **volatility**: Provide per-holding volatility (from factor model or backend)
- ❌ **aiScore**: Provide AI score per holding (backend AI analysis needed)
- ❌ **alerts**: Provide alert count per holding (backend alert system needed)
- ❌ **trend**: Provide sparkline data per holding (recent price series needed)

### **🔴 CRITICAL: Mock Component Integration**
**File**: `frontend/src/components/apps/ModernDashboardApp.tsx`
**Lines**: 58-61
**Status**: ❌ **4 COMPONENTS USING MOCK DATA**

```typescript
// CURRENT STATE: Components imported but using static mock data
import AssetAllocation from '../portfolio/AssetAllocation';      // ❌ Mock data
import FactorRiskModel from '../portfolio/FactorRiskModel';      // ❌ Mock data
import RiskMetrics from '../portfolio/RiskMetrics';              // ❌ Mock data
import PerformanceChart from '../portfolio/PerformanceChart';    // ❌ Mock data
```

**IMPLEMENTATION NEEDED**:
- ❌ **AssetAllocation**: Connect to real PortfolioSummaryAdapter allocation data
- ❌ **FactorRiskModel**: Connect to real RiskAnalysisAdapter factor exposure data
- ❌ **RiskMetrics**: Connect to real RiskAnalysisAdapter risk metrics data
- ❌ **PerformanceChart**: Connect to real PerformanceAdapter time series data

### **🔴 HIGH PRIORITY: Performance Integration Gaps**
**File**: `frontend/src/adapters/PerformanceAdapter.ts`
**Lines**: 556-567
**Status**: ❌ **SHORT-TERM DATA MISSING**

```typescript
// CURRENT STATE: 1D and 1W data hardcoded to 0
const periods = {
  "1D": {
    portfolioReturn: 0,  // ❌ Missing data - need 1D return calculation
    benchmarkReturn: 0,  // ❌ Missing data - need 1D benchmark data
  },
  "1W": {
    portfolioReturn: 0,  // ❌ Missing data - need 1W return calculation  
    benchmarkReturn: 0,  // ❌ Missing data - need 1W benchmark data
  },
  // 1M and 1Y work correctly with real data
};
```

**IMPLEMENTATION NEEDED**:
- ❌ **1D Performance**: Implement daily return calculations (backend needed)
- ❌ **1W Performance**: Implement weekly return calculations (backend needed)
- ❌ **Benchmark Integration**: Surface performance benchmarks in adapter summary

Nice-to-Have (Polish)
- Add portal-based popovers for other header menus (if overlap issues recur), keeping current absolute approach for now.
- Add an Overview Classic router mapping (optional) to show modern Overview in classic ViewRenderer.
- Replace placeholder AI scores/alerts with real sources when available.

Adapter Details (Reference)
- PortfolioSummaryAdapter.transform(riskAnalysis, riskScore, portfolioHoldings, performance?)
  - Summary
    - totalValue: sum holdings market_value
    - riskScore: riskScore.overall_risk_score || risk_score.score || null
    - volatilityAnnual: analysis.volatility_annual || risk_results.volatility_annual || risk_metrics.annual_volatility || null
    - dayChange/dayChangePercent: from last two points in performance time series (0 fallback)
    - ytdReturn: from performanceSummary.periods.YTD (0 fallback)
    - sharpeRatio: from performanceSummary.riskMetrics (0 fallback)
    - maxDrawdown: from performance.risk.maxDrawdown (0 fallback)
  - Holdings
    - weight = value / totalValue × 100 (0 if totalValue=0)
    - factorBetas: from stock_betas (ticker-first) or transposed df_stock_betas (factor-first)
    - riskContributionPct: from euler_variance_pct (normalize to % if fractional)
    - beta: factorBetas.market (TODO confirm factor key)
    - volatility/aiScore/alerts/trend: TODO placeholders for now

Containers (Reference)
- PortfolioOverviewContainer: usePortfolioSummary, onRefresh → refresh-holdings + refetch
- HoldingsViewModernContainer: uses adapter holdings; removed random placeholders, TODOs for missing fields
- PerformanceViewContainer: maps usePerformance to view props; onRefresh → refresh-performance + refetch
- RiskAnalysisModernContainer: passes adapter data to props; refresh via refetch
- ScenarioAnalysisContainer / StrategyBuilderContainer: ready; wire endpoints for scenario/optimize/backtest

Intent Registry (Registered)
- refresh-holdings, connect-account, analyze-risk
- refresh-performance, refresh-risk-analysis
- navigate-to-research, navigate-to-scenario-analysis, navigate-to-strategy-builder
- export-pdf (TODO), export-csv (TODO)
- optimize-portfolio (TODO), run-scenario (TODO), backtest-strategy (TODO)

QA Smoke Test (Manual)
- Authenticated start → ModernDashboardApp loads; header visible with bell popover.
- Overview (⌘1): summary populated; Refresh triggers intent + refetch.
- Holdings (⌘2): table renders with weight, factorBetas, riskContributionPct; sector filter works.
- Factors (⌘3): risk analysis renders slots; refresh works; no errors.
- Performance (⌘4): chart + benchmarks; period selector; loading disables controls; refresh works.
- Strategies (⌘5): container renders; placeholder actions log; no crashes.
- Scenarios (⌘8): container renders; placeholder actions log; no crashes.
- Research: StockLookup via container; search and selection handler logs; no prop errors.
- Notifications: Popover opens above content; not clipped.

## ⚠️ **RISKS / TODO PLACEHOLDERS - PRODUCTION READINESS CONCERNS**

### **🚨 CRITICAL RISKS**
- **Intent System**: ❌ **5 major intents are placeholder-only** (export-pdf, export-csv, optimize-portfolio, run-scenario, backtest-strategy)
  - **Risk**: Users can trigger these actions but nothing happens except logging
  - **Impact**: Poor user experience, broken workflows in production
  - **Mitigation**: Disable UI buttons or show "Coming Soon" until implemented

- **Holdings Data**: ❌ **8 critical holding fields are null/missing** (sector, assetClass, avgCost, currentPrice, volatility, aiScore, alerts, trend)
  - **Risk**: Holdings table shows incomplete data, missing key portfolio insights
  - **Impact**: Reduced analytical value, user confusion about missing data
  - **Mitigation**: Backend data sources needed or graceful "Data not available" messaging

- **Mock Components**: ❌ **4 major components using static mock data** (AssetAllocation, FactorRiskModel, RiskMetrics, PerformanceChart)
  - **Risk**: Charts and analysis show fake data instead of real portfolio insights
  - **Impact**: Misleading information, loss of user trust
  - **Mitigation**: Connect to real adapters or hide components until ready

### **⚠️ MEDIUM RISKS**
- **Performance Data**: Short-term performance (1D, 1W) hardcoded to 0
- **Advanced Features**: Strategy saving, backtesting engine not implemented
- **Export Functionality**: Users expect working export but only get logging

## 🎯 **NEXT ACTIONS - PRIORITIZED IMPLEMENTATION PLAN**

### **🔴 PHASE 1: Critical Intent System (Estimated: 2-3 weeks)**
**Goal**: Replace placeholder intent handlers with real functionality

1. **Export System Implementation**
   - **export-pdf**: Implement PDF generation (recommend client-side with jsPDF + html2canvas)
   - **export-csv**: Implement CSV export (client-side data serialization)
   - **Files to modify**: `SessionServicesProvider.tsx:329-337`

2. **Optimization Integration**  
   - **optimize-portfolio**: Wire to existing backend optimization endpoints
   - **run-scenario**: Connect to existing what-if analysis backend
   - **backtest-strategy**: Implement backtesting service integration
   - **Files to modify**: `SessionServicesProvider.tsx:339-352`

### **🔴 PHASE 2: Holdings Data Enhancement (Estimated: 3-4 weeks)**
**Goal**: Complete PortfolioSummaryAdapter with all holding fields

1. **Backend Data Sources** (Backend work required)
   - Add sector classification API endpoint
   - Add asset class categorization
   - Add cost basis tracking
   - Add real-time price feeds

2. **Adapter Integration** (Frontend work)
   - **File**: `PortfolioSummaryAdapter.ts:389-394`
   - Wire new backend data sources to adapter
   - Add graceful fallbacks for missing data
   - Update TypeScript interfaces

### **🔴 PHASE 3: Mock Component Integration (Estimated: 1-2 weeks)**
**Goal**: Connect mock components to real adapters

1. **Component Wiring**
   - **AssetAllocation** → PortfolioSummaryAdapter allocation data
   - **FactorRiskModel** → RiskAnalysisAdapter factor exposure data  
   - **RiskMetrics** → RiskAnalysisAdapter risk metrics data
   - **PerformanceChart** → PerformanceAdapter time series data
   - **Files to modify**: `ModernDashboardApp.tsx:58-61` + individual component files

### **🔴 PHASE 4: Performance Data Completion (Estimated: 2-3 weeks)**
**Goal**: Add missing short-term performance data

1. **Backend Enhancement** (Backend work required)
   - Implement 1D return calculations
   - Implement 1W return calculations  
   - Add benchmark data for short-term periods

2. **Adapter Updates** (Frontend work)
   - **File**: `PerformanceAdapter.ts:556-567`
   - Wire new backend data to adapter
   - Update period calculations

### **📋 IMMEDIATE ACTIONS (This Week)**
1. **Risk Mitigation**: Add "Coming Soon" messaging for placeholder intents
2. **Data Validation**: Add "Data not available" messaging for null holding fields
3. **Component Safety**: Hide or disable mock components showing fake data
4. **Documentation**: Update component documentation to reflect current limitations

Additional Gaps and Issues (Review)
- Mock components to wire: AssetAllocation, FactorRiskModel, RiskMetrics, PerformanceChart — replace TODOs with real adapters or mapped data sources.
- Risk Settings view: RiskSettingsViewModern is “ready for integration”; wire to RiskManagerService
  - GET `/api/risk-settings?portfolio_name=...` (fetch) and PUT `/api/risk-settings` (update) paths
  - Ensure UI state, optimistic updates, and cache invalidation on save (query key: `riskSettingsKey`).
- Endpoint contract validation (envelopes and fields):
  - POST `/api/analyze` → `{ success: boolean, data: {...} }` (adapters unwrap `data`)
  - POST `/api/risk-score` → `{ success: boolean, risk_score: {...} }`
  - POST `/api/performance` → `{ success: boolean, ... }` (PerformanceAdapter relies on stable field names)
  - POST `/api/what-if` → request `{ portfolio_name, scenario }` (Frontend sends `scenario` directly)
  - POST `/api/min-variance` and `/api/max-return` → `{ success: boolean, ... }`
  - GET `/api/portfolio?name=...` (or equivalent) → `{ success, portfolio_data, portfolio_name }` used by PortfolioInitializer
  - GET `/api/portfolio/refresh-prices` (currently POST in code) → ensure implemented as POST `/api/portfolio/refresh-prices` with `{ holdings }` and returns `{ success, portfolio_data }`.
- Authentication and CORS:
  - All requests use `credentials: 'include'` (cookie-based auth). Backend must allow credentials and CRA origin, and set session cookies.
  - `X-Requested-With: XMLHttpRequest` header is sent; confirm backend CSRF policy accepts this header.
- Plaid integration checks:
  - Endpoints required: `/plaid/connections`, `/plaid/holdings`, `/plaid/create_link_token`, `/plaid/exchange_public_token`.
  - `create_link_token` response supports optional `hosted_link_url`; connect flow uses popup with that URL if present.
  - Cache strategy: session-long (Infinity). Verify this matches product expectations; add manual refresh paths as needed.
- Cache and invalidation:
  - `PortfolioCacheService` uses content-versioned keys via `PortfolioRepository.getPortfolioContent(...)`. Verify content version increments on holdings changes (uploads, Plaid refresh) to avoid stale analysis/performance/risk-score.
  - Ensure `REACT_APP_PORTFOLIO_CACHE_TTL` is set appropriately per environment; production should use longer TTLs.
- Adapter data expectations and fallbacks:
  - `PortfolioSummaryAdapter` volatility fallbacks: analysis.volatility_annual → risk_results.volatility_annual → risk_metrics.annual_volatility. Ensure backend provides at least one path.
  - Per-holding fields still placeholders (sector, assetClass, prices, returns, volatility, aiScore, alerts, trend) — plan data sources and map.
- Intents still placeholders to implement: `export-pdf`, `export-csv`, `optimize-portfolio`, `run-scenario`, `backtest-strategy` (only logging now). Define endpoints or client-side flows and wire.
- Debug logging:
  - `APIService.getWhatIfAnalysis` logs request to console. Remove or guard under dev flag for production.
- Portfolio bootstrap route:
  - `RiskAnalysisService.getPortfolio(portfolioId→portfolio_name)` is used by `PortfolioInitializer`. Confirm actual backend route and response shape align with `CurrentPortfolioResponse` used by types.
- Testing gaps:
  - Add Playwright smoke tests for Modern views (Overview/Holdings/Risk/Performance/Plaid flow) using MSW or a dev backend.
  - Add contract tests for endpoint envelopes (analyze, risk-score, performance, what-if) to catch schema drift.

**File/Code References**
- Modern UI entry and toggle:
  - `frontend/src/router/AppOrchestratorModern.tsx` (modern/classic switch, services-ready gating)
  - `frontend/src/components/apps/ModernDashboardApp.tsx` (modern containers wiring)

- Mock components to wire with real data:
  - `frontend/src/components/portfolio/AssetAllocation.tsx`
  - `frontend/src/components/portfolio/FactorRiskModel.tsx`
  - `frontend/src/components/portfolio/RiskMetrics.tsx`
  - `frontend/src/components/portfolio/PerformanceChart.tsx`

- Risk settings integration:
  - View: `frontend/src/components/dashboard/views/modern/RiskSettingsViewModern.tsx`
  - Service: `frontend/src/chassis/services/RiskManagerService.ts` → `getRiskSettings`, `updateRiskSettings`
  - Query key: `frontend/src/queryKeys.ts` → `riskSettingsKey`
  - Cache service: `frontend/src/chassis/services/PortfolioCacheService.ts` → `getRiskSettings`

- Portfolio bootstrap and price refresh:
  - `frontend/src/providers/PortfolioInitializer.tsx` → calls `api.getPortfolio(DEFAULT_PORTFOLIO_NAME)` and `api.refreshPortfolioPrices(holdings)`
  - `frontend/src/chassis/services/RiskAnalysisService.ts` → `refreshPortfolioPrices` (POST `/api/portfolio/refresh-prices`)

- Endpoint contracts (backend must match):
  - Analyze: `frontend/src/chassis/services/RiskAnalysisService.ts` → `analyzePortfolio` (POST `/api/analyze` expects `{ success, data }`)
  - Risk score: `frontend/src/chassis/services/RiskAnalysisService.ts` → `getRiskScore` (POST `/api/risk-score` expects `{ success, risk_score }`)
  - Performance: `frontend/src/chassis/services/RiskAnalysisService.ts` → `getPerformanceAnalysis` (POST `/api/performance` envelope)
  - Portfolio fetch by name: `frontend/src/chassis/services/RiskAnalysisService.ts` → `getPortfolio` (used via `APIService.getPortfolio`)
  - What-if: `frontend/src/chassis/services/APIService.ts` → `getWhatIfAnalysis` (POST `/api/what-if` body `{ portfolio_name, scenario }`)
  - Optimization: `frontend/src/chassis/services/APIService.ts` → `getMinVarianceOptimization`, `getMaxReturnOptimization`

- Plaid integration:
  - Hook: `frontend/src/features/external/hooks/usePlaid.ts` (session-long cache; connections/holdings)
  - Service: `frontend/src/chassis/services/PlaidService.ts` → `getConnections`, `getPlaidHoldings`, `createLinkToken`, `exchangePublicToken`

- Auth/CORS behavior:
  - `frontend/src/chassis/services/APIService.ts` → `request` and `requestStream` include `credentials: 'include'` and header `X-Requested-With: XMLHttpRequest`
  - Auth endpoints: `frontend/src/chassis/services/AuthService.ts` → `checkAuthStatus` (GET `/auth/status`), `googleAuth`

- Cache/invalidation (content-versioned keys):
  - `frontend/src/chassis/services/PortfolioCacheService.ts` → `generateCacheKey`, `getOrFetch`, `clearPortfolio`
  - Uses `PortfolioRepository.getPortfolioContent(portfolioId)` to derive `version`

- Adapters and fallback logic:
  - Summary: `frontend/src/adapters/PortfolioSummaryAdapter.ts` (volatility/risk score extraction fallbacks; holdings mapping TODOs)
  - Risk analysis: `frontend/src/adapters/RiskAnalysisAdapter.ts` (factor betas, variance decomposition, correlation matrix)
  - Performance: `frontend/src/adapters/PerformanceAdapter.ts` (confirm field names consulted by modern containers)

- Intents registration (placeholders to implement marked):
  - `frontend/src/providers/SessionServicesProvider.tsx` → `IntentRegistry.registerHandler(...)` for
    `export-pdf`, `export-csv`, `optimize-portfolio`, `run-scenario`, `backtest-strategy`, plus refresh/navigate intents

- Debug logging to guard/remove for production:
  - `frontend/src/chassis/services/APIService.ts` → `getWhatIfAnalysis` contains `console.log('🔍 What-If API Request:', ...)`

- Query keys and timing config:
  - Keys: `frontend/src/queryKeys.ts`
  - Timing: `frontend/src/config/queryConfig.ts` and `frontend/src/utils/cacheConfig.ts` (base TTL from `REACT_APP_PORTFOLIO_CACHE_TTL`)

Phased Implementation Plan
- Phase 0: Baseline Alignment
  - Environment: Confirm `REACT_APP_API_BASE_URL`, CORS with credentials, and cookies work end-to-end.
  - Types: Run `npm run generate-types` and resolve adapter/service type conflicts.
  - Acceptance: Auth via `/auth/status` works; Modern Dashboard loads post-bootstrap with no console errors.

- Phase 1: Contract Verification
  - Validate endpoint envelopes/fields match services/adapters:
    - Analyze `/api/analyze` → `{ success, data }`
    - Risk Score `/api/risk-score` → `{ success, risk_score }`
    - Performance `/api/performance` → success envelope
    - What-If `/api/what-if` → body `{ portfolio_name, scenario }`
    - Optimization `/api/min-variance`, `/api/max-return` → success envelope
    - Portfolio fetch/refresh-prices align with `PortfolioInitializer.tsx` and `RiskAnalysisService.ts`
  - Tests: Add small Jest tests around `RiskAnalysisService`/`APIService` parsing; MSW handlers for dev.
  - Acceptance: All calls return expected shapes; adapters yield non-null core fields (risk score, volatility).

- Phase 2: Risk Settings Integration
  - Wire `RiskSettingsViewModern.tsx` to `RiskManagerService` with `riskSettingsKey` and mutations.
  - Implement optimistic update and invalidate queries on save.
  - Acceptance: GET/PUT flows function; edits reflect instantly; errors display properly.

- Phase 3: Wire Mock Components
  - Components: `AssetAllocation`, `FactorRiskModel`, `RiskMetrics`, `PerformanceChart`.
  - Adapters: Extend to provide allocation breakdown, factor exposures, risk metrics, performance series/benchmarks.
  - Acceptance: Components render real data; placeholders removed.

- Phase 4: Intents With Real Actions
  - Implement `export-pdf`, `export-csv`, `optimize-portfolio`, `run-scenario`, `backtest-strategy` endpoints or client-side flows.
  - Integrate in `SessionServicesProvider.tsx` handlers with UI feedback and error handling.
  - Acceptance: Actions perform real work; UI shows progress/errors; refetch when appropriate.

- Phase 5: Cache & Invalidation
  - Verify content version increments on holdings changes (`PortfolioRepository.getPortfolioContent(...).version`).
  - Set `REACT_APP_PORTFOLIO_CACHE_TTL` per environment; validate `queryConfig.ts` scaling.
  - Acceptance: Risk/performance/score refresh after holdings changes; no stale cross-view data.

- Phase 6: Plaid Flow
  - Ensure `/plaid/*` endpoints work and handle `hosted_link_url` in connect flow.
  - Provide manual refresh for connections/holdings while keeping session-long caching.
  - Acceptance: Link completes; connections/holdings load once per session; manual refresh updates immediately.

- Phase 7: Cleanup & Guards
  - Guard/remove debug logs (e.g., `console.log` in `APIService.getWhatIfAnalysis`).
  - Keep Modern UI behind a flag with keyboard toggle for safe rollback.
  - Acceptance: No noisy logs in production; easy rollback remains.

- Phase 8: Testing & CI
  - Playwright: Smoke tests for Modern Overview/Holdings/Risk/Performance + Plaid link stub.
  - Jest: Adapter transformation tests for fallbacks and error surfacing.
  - CI: Add `npm run generate-types:check` to catch schema drift.
  - Acceptance: Tests pass locally/CI; type drift blocked.

- Phase 9: Rollout
  - Gradual enablement; monitor logs/metrics via `frontendLogger`.
  - Track API error rates and adapter transform failures.
  - Acceptance: Stable metrics; low error rate; promote Modern UI default.
