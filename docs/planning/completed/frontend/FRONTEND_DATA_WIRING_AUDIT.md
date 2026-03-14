# Frontend Data Wiring Audit

**Date:** 2026-03-04 (last updated, re-verified)
**Status:** 9/9 views wired to real APIs. All functional wiring gaps resolved. No mock data in any view. Remaining items are hardcoded fallback values and dead code cleanup.

---

## Summary

| View | Real Data % | Status | Key Gaps |
|------|------------|--------|----------|
| Portfolio Overview | 100% | ✅ COMPLETE | All 6 metric cards real (Alpha + Concentration wired `671d41de`). 4 AI/insights endpoints live |
| Performance | 100% | ✅ COMPLETE | Attribution, risk metrics, capture ratios all wired. Only drawdown metadata missing (backend) |
| Holdings | 100% | ✅ COMPLETE | Per-position risk scores, alert badge tooltips, cash proxy detection |
| Scenario Analysis | 100% | ✅ COMPLETE | All 5 phases done. Backend history persistence, Monte Carlo, computed templates |
| Risk Analysis | 95% | ✅ COMPLETE | Risk factor descriptions computed from real data. Hedging enriched. Stress tests wired (Wave 3h) |
| Strategy Builder | 98% | ✅ COMPLETE | 6 YAML templates, backtest attribution, Active Strategies tab implemented |
| Stock Lookup | 100% | ✅ COMPLETE | Technical indicators, health scores, search history, ROE/margin fix. Commit `b6b09efc` |
| Asset Allocation | 100% | ✅ COMPLETE | Full read/write/drift/rebalance |
| Notification Center | 100% | ✅ COMPLETE | Smart Alerts + pending updates + localStorage persistence |

---

## Per-View Detail

### Portfolio Overview — ✅ COMPLETE

**All core metrics wired:** totalValue, dayChange, dayChangePercent, ytdReturn, sharpeRatio, maxDrawdown, volatilityAnnual, riskScore, lastUpdated.

**AI/Insights — all 4 hooks fully implemented and rendering:**
- `POST /api/positions/alerts` (useSmartAlerts) → 5 real alerts from position flags
- `POST /api/positions/market-intelligence` (useMarketIntelligence) → earnings + sentiment with relevance
- `POST /api/positions/ai-recommendations` (useAIRecommendations) → concentration analysis with priority
- `POST /api/positions/metric-insights` (useMetricInsights) → insights on all 6 metric cards

**Alpha & Concentration (formerly ESG):** Alpha Generation wired to CAPM alpha from performance engine. ESG replaced with Concentration (risk score component, 0-100, higher=safer). Unused _prefixed setters and stale TODOs cleaned up. Commit `671d41de`.

---

### Performance View — ✅ COMPLETE

**Wired:** Time series, period returns (1D/1W/1M/3M/1Y/YTD), volatility, sharpe, maxDrawdown, beta, monthly stats, dynamic benchmark selection (localStorage), realized mode with institution/account filtering.

**Attribution:** All 3 types rendered in clean tables — sector (allocation, return, contribution), factor/Brinson (Market/Value/Momentum betas + contributions), security (Contributors/Detractors split by contribution sign). Commits `2315fa16`, `df9de726`. Plan: `completed/PERFORMANCE_ATTRIBUTION_TAB_PLAN.md`.

**Risk-adjusted metrics (2026-03-04):** All 6 formerly-hardcoded metrics now wired from real backend data: informationRatio, trackingError, sortino, calmar, upCaptureRatio, downCaptureRatio. Up/down capture ratios added to `performance_metrics_engine.py` (geometric mean formula). Risk metrics grid expanded from 4→8 items. 165-line stale comment header removed. Plan: `completed/PERFORMANCE_VIEW_CLEANUP_PLAN.md`.

**Double-conversion fix (2026-03-04):** `PerformanceAdapter.transformRisk()` and `transformPerformanceSummary()` were multiplying already-percent backend values by 100 (e.g., volatility 8.64% → 864%). Removed all `* 100` from risk_metrics and period return paths. Re-fixed in commit `4e9e4262` after parallel session re-introduced the bug (also covered `transformReturns()` and `transformMonthlyStats()`).

**Backend gaps resolved (2026-03-04):** 4 gaps filled in one pass. Commit `592256c9`. Plan: `completed/PERFORMANCE_BACKEND_GAPS_PLAN.md`.
- Benchmark time series: `benchmark_monthly_returns` added to engine → result object → adapter. Chart now shows real SPY line.
- Rolling Sharpe/Vol: 12-month trailing window computed in engine, threaded to time series data points.
- Drawdown metadata: peak date, trough date, duration (days), recovery time (days). View renders real values (Duration: 31 days, Recovery: 61 days, Peak: 2025-09-30).
- 1M return fix: `last_month_return` from engine replaces cumulative `total_return` in 1M period. 1D/1W deferred (need daily data).

---

### Holdings View — ✅ COMPLETE

**All per-position fields wired:** ticker, name, value, shares, weight, avgCost, currentPrice, totalReturn, totalReturnPercent, dayChange, dayChangePercent, type, sector, assetClass, volatility, riskScore, beta, maxDrawdown, alerts, trend, riskPct.

**Per-position risk scores:** 0-100 composite (vol 35%, drawdown 25%, beta 20%, concentration 20%) with colored badges. Commit `8a8445ad`.

**Alert badge tooltips:** Native tooltip on hover shows alert messages (e.g., "DSU is 27.1% of exposure"). `alert_details` threaded through API → adapter → component. Commit `d644687f`.

**Cash proxy detection:** `is_cash_equivalent` threaded from provider flags through monitor payload. Belt-and-suspenders ticker fallback in route handler. `isProxy` wired in adapter, "Cash Proxy" badge in view.

---

### Scenario Analysis — ✅ COMPLETE

| Tab | Status | Notes |
|-----|--------|-------|
| Portfolio Builder | ✅ 95% | Real what-if execution. 5 computed templates from portfolio data |
| Session History | ✅ 100% | Backend persistence via `/api/scenarios/history`. Auto-save, re-run, compare |
| Stress Tests | ✅ 100% | Real execution via `useStressTest()`. 8 predefined scenarios from backend |
| Monte Carlo | ✅ 100% | Real engine. Configurable params (sims, horizon). Percentile paths + terminal distribution |
| Optimizations | ✅ 100% | Reads Strategy Builder cache. Apply-as-what-if cross-link |

**All 5 phases of the overhaul complete.** Commits `627c167f` (Phase 2), `078aed92` (Phase 3), `c3e4eb56` (Phase 4), `b6f3e45e` (Phase 5). Plan marked complete `b0194df1`.

---

### Risk Analysis — ✅ COMPLETE

**Fully wired:** Factor exposures, correlations, variance decomposition, risk contributions, risk score, risk category.

**Risk factor descriptions:** Concentration, volatility, factor, sector descriptions computed from real backend data (not hardcoded). Commit `5831c982`.

**Hedging details:** Enriched via post-transform useMemo — expectedCost, VaR, portfolioBeta from real data. Hardcoded override removed. Commit `5831c982`.

**Stress tests:** Full stress test engine (Wave 3h). 8 predefined scenarios, 3 API endpoints, real `useStressTest()` data. Commits `d1df3fee`→`a1d598fb`.

**Hedging workflow:** 4-step dialog (Review→Impact→Trades→Execute). 2 POST endpoints wrapping ScenarioService + TradeExecutionService. Commit `18aa43ae`.

---

### Strategy Builder — ✅ COMPLETE

| Tab | Status | Notes |
|-----|--------|-------|
| Strategy Builder | ✅ 95% | Real optimization engine fully wired |
| Marketplace | ✅ 95% | 6 curated YAML templates via `GET /api/strategies/templates`. Deploy→backtest with real ticker weights |
| Active Strategies | ✅ 95% | Implemented — shows active strategy cards with real metrics |
| Performance/Backtest | ✅ 95% | Backtest engine + 3 attribution tables (security, sector, factor) |

**Templates:** 6 curated templates in `strategy_templates.yaml` with real ticker weights served via `GET /api/strategies/templates`. `useStrategyTemplates()` hook, templates decoupled from optimization state. Commits `d680cf50`, `1884c9c1`.

**Backtest attribution:** Security, sector, factor attribution wired into `backtest_engine.py`. Frontend: `AttributionRow` type, `parseAttribution()`, Performance tab with annual breakdown + 3 attribution tables. Commit `2f5320ca`.

**Deploy→backtest:** Clicking Deploy on a Marketplace template triggers real backtest with the template's ticker weights. Verified live: Income Plus backtest +31.34% total return, +9.51% annualized, 0.382 Sharpe.

**Active Strategies:** Now implemented — shows active strategy cards with real performance metrics (YTD, Sharpe, Volatility, Max Drawdown), configure/pause buttons, last rebalance tracking.

---

### Stock Lookup — ✅ COMPLETE (100%)

**All analysis tabs wired:** Overview (price, market cap, sector), Risk Factors (beta, vol, sharpe, VaR), Technicals (RSI, MACD, support/resistance, Bollinger), Fundamentals (P/E, P/B, ROE, margins), Peer Comparison (real FMP data), Portfolio Fit (real what-if).

**Technical indicators (backend):** `enrich_stock_data()` now calls `get_technical_analysis()` from FMP. RSI, MACD, support/resistance, Bollinger band position all populated from real data. Commit `b6b09efc`.

**Financial health scores (frontend):** Profitability, Leverage, Valuation scores computed from real fundamentals (ROE, margins, D/E, P/E, P/B) via `useMemo`. No more hardcoded 85/72/45.

**Search autocomplete:** `useStockSearch()` hook returns real results, rendered as dropdown with symbol, name, price, and change. Quick-access buttons retained.

**Search history:** Recent searches (last 8) persisted to localStorage, shown as "RECENT" chips in empty state.

**Codex fixes:** `peRatio`/`pbRatio` default to `undefined` (not fake 15/3), ROE/profitMargin ×100'd for display, zero-division guard on support/resistance bar. Stale TODOs removed.

---

### Asset Allocation — ✅ COMPLETE

**Fully wired:** Portfolio weights from risk analysis, target allocation read/write via `useTargetAllocation()`/`useSetTargetAllocation()`, drift calculation (drift_pct, drift_status, drift_severity), rebalance trade generator via `useRebalanceTrades()`, per-asset-class holdings.

**Only fallback:** 60/30/10 allocation shown when no data loaded (acceptable loading state).

---

## Cross-View Issues

### Resolved Cross-View Issues
- ~~PortfolioOverview stale TODOs~~ — cleaned up (`b6b09efc`, `671d41de`)
- ~~PerformanceView stale TODOs~~ — already cleaned up
- ~~PerformanceView unused `_activeTab`~~ — already cleaned up
- ~~PerformanceView hardcoded metrics~~ — `infoRatio`, `trackingError`, `upCapture`, `downCapture`, `sortino`, `calmar` all wired from adapter
- ~~PortfolioOverview Alpha/ESG placeholders~~ — Alpha wired, ESG replaced with Concentration (`671d41de`)
- ~~PortfolioOverview unused `_prefixed` states~~ — cleaned up (`671d41de`)

### Minor Remaining Items
- ~~`isProxy` hardcoded to `false` in `PositionsAdapter.ts:86`~~ DONE (cash proxy detection implemented)
- ~~PerformanceView: drawdown duration/recovery/peak date show "--"~~ DONE (`592256c9`)
- ~~PerformanceAdapter: benchmark time series hardcoded to 0~~ DONE (`592256c9`)
- PerformanceAdapter: 1D/1W period returns hardcoded to 0 (needs daily data pipeline — out of scope for monthly engine)

---

## Remaining Work

**All functional wiring gaps are resolved.** All 9 views show real data. No mock data anywhere.

**Only remaining gap (needs new data pipeline):**
1. PerformanceAdapter — 1D/1W period returns hardcoded to 0 (needs daily return data, monthly engine cannot provide)

**All completed:**
- ~~Return attribution — Brinson/factor-level decomposition~~ DONE (`df9de726`)
- ~~PerformanceView hardcoded metrics~~ DONE (infoRatio, trackingError, sortino, calmar, capture ratios all wired from real data)
- ~~PerformanceAdapter double-conversion bug~~ DONE (removed `* 100` from already-percent values). Re-fixed `4e9e4262`.
- ~~PerformanceView 165-line stale header + hardcoded dollar values~~ DONE (cleanup)
- ~~PerformanceView stale TODOs + unused state~~ DONE (already cleaned)
- ~~PortfolioOverview Alpha/ESG~~ DONE (`671d41de`)
- ~~Stock Lookup wiring gaps~~ DONE (`b6b09efc`)
- ~~PerformanceView drawdown metadata~~ DONE (`592256c9`)
- ~~Benchmark time series~~ DONE (`592256c9`)
- ~~Rolling Sharpe/Vol~~ DONE (`592256c9`)
- ~~1M return using total_return instead of last month~~ DONE (`592256c9`)
- ~~Frontend Cleanup P2: hardcoded mock data~~ DONE (`1ee96537`) — RiskAnalysis mock fallbacks, StrategyBuilder fake metrics/AI recs, HoldingsView LIVE badges. See `completed/FRONTEND_CLEANUP_P2_PLAN.md`.
