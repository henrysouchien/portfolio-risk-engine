# Backend Enhancement TODOs

This document contains all the backend enhancements needed to support the complete modern UI integration. These are currently using fallback/mock data in the containers.

## StockAnalysisAdapter Enhancements

### Basic Stock Search & Metadata
- [ ] Add **real stock search functionality** to replace mock search in `StockLookupContainer.tsx:110`
- [ ] Add **company metadata API** for real company names instead of `"${symbol} Inc."` defaults
- [ ] Add **exchange information** from stock metadata API
- [ ] Add **search loading state** when stock search API is implemented

### Market Data Integration
- [ ] Add **real-time price feeds** from market data API (`current_price`, `StockLookupContainer.tsx:185`)
- [ ] Add **daily price change calculation** (`price_change`, `StockLookupContainer.tsx:186`)
- [ ] Add **daily percentage change calculation** (`price_change_percent`, `StockLookupContainer.tsx:187`)
- [ ] Add **market capitalization** from fundamental data (`market_cap`, `StockLookupContainer.tsx:188`)
- [ ] Add **trading volume** from market data API (`volume`, `StockLookupContainer.tsx:189`)

### Risk Calculations
- [ ] Add `var_95` and `var_99` calculations (Value at Risk) - `StockLookupContainer.tsx:198-200`
- [ ] Add `sharpe_ratio` calculation - `StockLookupContainer.tsx:204-205`
- [ ] Add `max_drawdown` calculation - `StockLookupContainer.tsx:206-207`
- [ ] Add `sp500_correlation` calculation - `StockLookupContainer.tsx:208-209`
- [ ] Add **comprehensive risk score calculation** based on multiple factors - `StockLookupContainer.tsx:192`

### Fundamental Data
- [ ] Add comprehensive `fundamentals` object with:
  - [ ] `revenue`, `profit_margin`, `debt_to_equity`
  - [ ] `current_ratio`, `roe`, `book_value`
  - [ ] `pe_ratio`, `pb_ratio` - `StockLookupContainer.tsx:220-222`

### Technical Analysis  
- [ ] Add `technical_indicators` object with:
  - [ ] `rsi` (Relative Strength Index) - `StockLookupContainer.tsx:241-242`
  - [ ] `macd` (Moving Average Convergence Divergence) - `StockLookupContainer.tsx:243-244`
  - [ ] `bollinger_position` (Upper/Lower/Middle band position) - `StockLookupContainer.tsx:249-250`
- [ ] Add `technical_levels` object with:
  - [ ] `resistance` levels - `StockLookupContainer.tsx:245-246`
  - [ ] `support` levels - `StockLookupContainer.tsx:247-248`

### Market Data
- [ ] Add `sector` classification - `StockLookupContainer.tsx:210-211`
- [ ] Enhance existing technical analysis calculations

## PortfolioSummaryAdapter Enhancements

### Holdings Enhancement (from HoldingsViewModernContainer.tsx)
- [ ] Add `sector` classification for each holding - `HoldingsViewModernContainer.tsx:210`
- [ ] Add `assetClass` categorization - `HoldingsViewModernContainer.tsx:211`
- [ ] Add `avgCost` (average cost basis calculation) - `HoldingsViewModernContainer.tsx:212`
- [ ] Add `currentPrice` from real-time market data API - `HoldingsViewModernContainer.tsx:213`
- [ ] Add `totalReturn` and `totalReturnPercent` calculations - `HoldingsViewModernContainer.tsx:214-215`
- [ ] Add `dayChange` and `dayChangePercent` from market data API - `HoldingsViewModernContainer.tsx:216-217`
- [ ] Add `weight` (portfolio weight calculation) - `HoldingsViewModernContainer.tsx:218`

### Risk Analytics per Holding (from HoldingsViewModernContainer.tsx)
- [ ] Add `riskScore` calculation based on volatility, beta, sector exposure - `HoldingsViewModernContainer.tsx:221`
- [ ] Add `beta` calculation from regression analysis vs market index (market factor beta available)
- [ ] Add `volatility` calculation from historical price data - `HoldingsViewModernContainer.tsx:223`
- [ ] Add `aiScore` from machine learning models - `HoldingsViewModernContainer.tsx:224`
- [ ] Add `alerts` count from risk monitoring system - `HoldingsViewModernContainer.tsx:225`
- [ ] Add `trend` data (15-day price history for sparkline charts) - `HoldingsViewModernContainer.tsx:226`

## PerformanceAdapter Enhancements

### ✅ FULLY IMPLEMENTED FEATURES
- ✅ **Comprehensive time series generation** from monthly returns with cumulative calculations
- ✅ **Complete benchmark analysis** with alpha, beta, R², excess return calculations
- ✅ **Full risk metrics transformation** with percentage conversion (volatility, max drawdown, downside deviation, tracking error)
- ✅ **Performance summary** with period breakdowns (1D, 1W, 1M, 1Y) and risk-adjusted returns
- ✅ **Monthly statistics** with win/loss ratios, positive/negative month counts
- ✅ **Validation system** with error/warning collection for robust data handling
- ✅ **30-minute caching system** for performance optimization
- ✅ **Backend integration** with FastAPI endpoint `/api/performance` and Pydantic validation

### MINOR ENHANCEMENTS NEEDED
- [ ] Add dynamic benchmark selection UI (currently defaults to SPY)
- [ ] Add configurable benchmark metadata from market data API

### BACKEND FEATURE GAPS (Not Adapter Issues)
- [ ] Add sector attribution analysis to backend performance endpoint
- [ ] Add factor attribution analysis (value, growth, momentum, etc.) to backend
- [ ] Add security-level attribution analysis to backend

## OptimizationAdapter Enhancements

### Risk Metrics (from StrategyBuilderContainer.tsx)
- [ ] Add `maxDrawdown` calculation for strategies - `StrategyBuilderContainer.tsx:113`
- [ ] Add benchmark performance data for comparison - `StrategyBuilderContainer.tsx:131`
- [ ] Add `alpha` calculation vs benchmark - `StrategyBuilderContainer.tsx:132`

### Strategy Comparison (from StrategyBuilderContainer.tsx)
- [ ] Add comparison vs current portfolio metrics:
  - [ ] `returnImprovement` calculation - `StrategyBuilderContainer.tsx:122`
  - [ ] `riskReduction` calculation - `StrategyBuilderContainer.tsx:123`
  - [ ] `sharpeImprovement` calculation - `StrategyBuilderContainer.tsx:124`

### Strategy Templates & Management (from StrategyBuilderContainer.tsx)
- [ ] Add **dynamic strategy templates** to replace hardcoded ones - `StrategyBuilderContainer.tsx:136`
- [ ] Add **dynamic allocation from backend strategy templates** - `StrategyBuilderContainer.tsx:143, 150`
- [ ] Add `saveStrategy` method and backend endpoints - `StrategyBuilderContainer.tsx:254-255`
- [ ] Add strategy persistence and retrieval

## WhatIfAnalysisAdapter Enhancements

### Scenario Results Enhancement (from ScenarioAnalysisContainer.tsx)
- [ ] Add **comprehensive scenario results** to WhatIfAnalysisAdapter - `ScenarioAnalysisContainer.tsx:102`
- [ ] Add **scenario portfolio valuation** - `ScenarioAnalysisContainer.tsx:110`
- [ ] Add **proper total return calculation for scenarios** - `ScenarioAnalysisContainer.tsx:111`
- [ ] Add **comprehensive risk metrics for scenario results** - `ScenarioAnalysisContainer.tsx:112`

### Scenario Templates & Configuration (from ScenarioAnalysisContainer.tsx)
- [ ] Add **dynamic scenario templates** to replace hardcoded ones - `ScenarioAnalysisContainer.tsx:116`
- [ ] Add **dynamic strategy allocation from backend** - `StrategyBuilderContainer.tsx:126, 136`
- [ ] Add **configurable stress test parameters** - `ScenarioAnalysisContainer.tsx:154`
- [ ] Add **dynamic sector rotation scenarios** - `ScenarioAnalysisContainer.tsx:160`

### Strategy Integration Metadata (from ScenarioAnalysisContainer.tsx)
- [ ] Add **strategy template availability check** - `ScenarioAnalysisContainer.tsx:165`
- [ ] Add **StrategyBuilder integration status** - `ScenarioAnalysisContainer.tsx:166`
- [ ] Add **dynamic strategy types from backend** - `ScenarioAnalysisContainer.tsx:167`

## UI Component Integration (from ModernDashboardApp.tsx)

### Mock Data Components Requiring Adapter Integration
- [ ] **AssetAllocation**: Connect to PortfolioSummaryAdapter for real allocation percentages - `ModernDashboardApp.tsx:114`
- [ ] **FactorRiskModel**: Integrate with RiskAnalysisAdapter for real risk factor data - `ModernDashboardApp.tsx:115, 435`
- [ ] **RiskMetrics**: Integrate with RiskAnalysisAdapter for real risk metrics - `ModernDashboardApp.tsx:116, 438`
- [ ] **PerformanceChart**: Integrate with PerformanceAdapter for real performance data - `ModernDashboardApp.tsx:117`

### System Integration
- [ ] **Real-time market data API** for market status indicator - `ModernDashboardApp.tsx:150`
- [ ] **Real notification service** to replace mock notification system - `ModernDashboardApp.tsx:155`

## Priority Order

### High Priority (Core Functionality)
1. **PortfolioSummaryAdapter holdings enhancement** (sector, prices, returns, risk analytics) - `HoldingsViewModernContainer.tsx`
2. **StockAnalysisAdapter basic risk calculations** (VaR, Sharpe, max drawdown) - `StockLookupContainer.tsx`
3. **Market data API integration** (real-time prices, daily changes, volume) - `StockLookupContainer.tsx` & `HoldingsViewModernContainer.tsx`
4. ✅ **PerformanceAdapter - COMPLETE** (comprehensive implementation with caching, validation, and full backend integration)

### Medium Priority (Enhanced Analytics)
1. **StockAnalysisAdapter technical analysis** (RSI, MACD, Bollinger bands, support/resistance) - `StockLookupContainer.tsx`
2. **OptimizationAdapter strategy comparison metrics** (return improvement, risk reduction, Sharpe improvement) - `StrategyBuilderContainer.tsx`
3. **WhatIfAnalysisAdapter scenario enhancements** (comprehensive results, proper valuation) - `ScenarioAnalysisContainer.tsx`
4. **Backend attribution analysis features** (sector/factor/security-level) - `PerformanceViewContainer.tsx`

### Lower Priority (Advanced Features)
1. **StockAnalysisAdapter fundamental data** (comprehensive financials) - `StockLookupContainer.tsx`
2. **OptimizationAdapter strategy management** (save/load strategies, dynamic templates) - `StrategyBuilderContainer.tsx`
3. **Real-time market status & notifications** - `ModernDashboardApp.tsx`
4. **UI component adapter integration** (AssetAllocation, FactorRiskModel, RiskMetrics, PerformanceChart) - `ModernDashboardApp.tsx`

## Implementation Notes

- Most containers currently use approximations or placeholder data for missing fields
- All fallback data is clearly marked with TODO comments in the container files
- Real backend data takes precedence - fallbacks only used when backend data unavailable
- Containers are production-ready and will automatically use real data once backend provides it
- **NEW**: Added comprehensive file references with line numbers for each TODO item

## Summary of TODO Audit Results

### Files Audited
- ✅ `StockLookupContainer.tsx` - **33 TODOs** (most comprehensive stock analysis enhancements needed)
- ✅ `HoldingsViewModernContainer.tsx` - **11 TODOs** (holdings enhancement and risk analytics per holding)
- ✅ `PerformanceViewContainer.tsx` - **6 TODOs** (mostly backend attribution analysis features)
- ✅ `StrategyBuilderContainer.tsx` - **8 TODOs** (optimization metrics and strategy templates)
- ✅ `ScenarioAnalysisContainer.tsx` - **11 TODOs** (scenario results and template enhancements)
- ✅ `ModernDashboardApp.tsx` - **6 TODOs** (UI component integration and system features)
- ✅ `PortfolioOverviewContainer.tsx` - **0 TODOs** (fully integrated)
- ✅ `RiskAnalysisModernContainer.tsx` - **0 TODOs** (fully integrated)
- ✅ `RiskSettingsViewModern.tsx` - **0 TODOs** (fully integrated)

### Total Enhancement Items
**75 backend enhancement items** identified across 6 adapter categories:
- **StockAnalysisAdapter**: 25 enhancements (stock search, market data, risk calculations, fundamentals, technical analysis)
- **PortfolioSummaryAdapter**: 11 enhancements (holdings enhancement, risk analytics per holding)
- **OptimizationAdapter**: 8 enhancements (risk metrics, strategy comparison, templates & management)
- **WhatIfAnalysisAdapter**: 11 enhancements (scenario results, templates & configuration, strategy integration)
- **UI Component Integration**: 6 enhancements (mock data components, system integration)
- **PerformanceAdapter**: 4 minor enhancements (attribution analysis - backend features, not adapter issues)

### New Categories Added
- **WhatIfAnalysisAdapter Enhancements** (new category)
- **UI Component Integration** (new category)
- **Basic Stock Search & Metadata** (new subcategory under StockAnalysisAdapter)
- **Market Data Integration** (enhanced subcategory under StockAnalysisAdapter)