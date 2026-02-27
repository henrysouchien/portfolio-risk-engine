# Frontend Phase 2 — Working Doc

**Parent doc:** `FRONTEND_PACKAGE_DESIGN.md`
**Status:** Wave 1 complete + formatting foundation complete, Wave 2 next
**Last verified:** 2026-02-27 — Chrome visual audit after formatting module migration

### Related Docs
| Doc | Purpose |
|-----|---------|
| `COMPOSABLE_APP_FRAMEWORK_PLAN.md` | Phase 3 — the SDK/framework this work feeds into |
| `FRONTEND_WAVE1_IMPLEMENTATION_PLAN.md` | Wave 1 detailed implementation plan (Codex-reviewed) |
| `FRONTEND_COMPONENT_VISUAL_MAP.md` | Visual guide: what you see on screen → code component |
| `FRONTEND_DATA_WIRING_AUDIT.md` | Container/adapter audit (ported into this doc) |
| `FRONTEND_FORMATTING_MODULE_PLAN.md` | Shared formatting module plan (Codex-reviewed, complete) |

---

## Part A: Backend Wiring Status

All active hook → service → endpoint flows are wired end-to-end. No critical gaps.

| Flow | Endpoint | Hook | Adapter | UI Container | Status |
|------|----------|------|---------|-------------|--------|
| Risk analysis | `/api/analyze` | useRiskAnalysis | RiskAnalysisAdapter | RiskAnalysisModernContainer | WIRED |
| Performance | `/api/performance` | usePerformance | PerformanceAdapter | PerformanceViewContainer | WIRED |
| Risk score | `/api/risk-score` | useRiskScore | RiskScoreAdapter | (via PortfolioOverview) | WIRED |
| Portfolio summary | composite | usePortfolioSummary | PortfolioSummaryAdapter | PortfolioOverviewContainer | WIRED |
| Analysis report | `/api/analyze` | useAnalysisReport | AnalysisReportAdapter | (extended report) | WIRED |
| What-if | `/api/what-if` | useWhatIfAnalysis | WhatIfAnalysisAdapter | ScenarioAnalysisContainer | WIRED |
| Min-variance opt | `/api/min-variance` | usePortfolioOptimization | PortfolioOptimizationAdapter | StrategyBuilderContainer | WIRED |
| Max-return opt | `/api/max-return` | usePortfolioOptimization | PortfolioOptimizationAdapter | StrategyBuilderContainer | WIRED |
| Stock analysis | `/api/direct/stock` | useStockAnalysis | StockAnalysisAdapter | StockLookupContainer | WIRED |
| Risk settings | `/api/risk-settings` | useRiskSettings | RiskSettingsAdapter | RiskSettingsContainer | WIRED |
| Holdings | composite | usePortfolioSummary | — | HoldingsViewModernContainer | WIRED |
| Asset allocation | `/api/analyze` | useRiskAnalysis | RiskAnalysisAdapter | AssetAllocationContainer | WIRED |
| Chat | `/api/gateway/chat` | usePortfolioChat | — | AIChat/ChatCore | WIRED |
| Tool approval | `/api/gateway/tool-approval` | usePortfolioChat | — | — | WIRED |
| Auth | `/api/auth/*` | useAuthFlow | — | GoogleSignInButton | WIRED |
| Plaid | `/api/plaid/*` | usePlaid | — | PlaidLinkButton, AccountConnections | WIRED |
| SnapTrade | `/api/snaptrade/*` | useSnapTrade | — | SnapTradeLaunchButton | WIRED |
| Pending updates | `/api/plaid/pending-updates` | usePendingUpdates | — | HoldingsViewModernContainer | WIRED |
| Price refresh | `/api/portfolio/refresh-prices` | — | — | PortfolioInitializer | WIRED |
| Instant analysis | `/api/analyze` | useInstantAnalysis | — | InstantTryPage | WIRED |

### Backend Endpoints with No Frontend Consumer

| Endpoint | Notes |
|----------|-------|
| `/api/direct/portfolio` | Alt access (no DB) — not used by frontend |
| `/api/direct/what-if` | Frontend uses session-based `/api/what-if` |
| `/api/direct/optimize/*` | Frontend uses session-based equivalents |
| `/api/direct/performance` | Frontend uses session-based equivalent |
| `/api/direct/interpret` | No frontend consumer |
| `/api/factors/*` | Factor intelligence routes — no frontend consumer |
| `/api/factor-groups/*` | Factor group CRUD — no frontend consumer |
| `/api/positions/monitor` | Position monitor — no frontend consumer |

---

## Part B: UI Features Using Mock / Demo Data

This is the comprehensive list of every visible feature in the app that does NOT
use real backend data. Organized by dashboard view.

### Dashboard View Map (ModernDashboardApp)

The app has 8 views accessed via keyboard shortcuts or navigation:

| View | Shortcut | Container | Real Data? |
|------|----------|-----------|------------|
| Overview | ⌘1 | PortfolioOverviewContainer + PerformanceViewContainer + RiskMetricsContainer | **Partial** — see below |
| Holdings | ⌘2 | HoldingsViewModernContainer | **Partial** — see below |
| Factor Analysis | ⌘3 | FactorRiskModelContainer + RiskMetricsContainer | **Real** (Wave 1) — minor gaps: Performance tab, R², t-stat |
| Performance | ⌘4 | PerformanceViewContainer | **Partial** — see below |
| Strategy Builder | ⌘5 | StrategyBuilderContainer | **Partial** — props wired (Wave 1), mock fallbacks when no optimization data |
| Stock Research | ⌘6 | StockLookupContainer | **Partial** — see below |
| AI Assistant | ⌘7 | ChatInterface | **Real** |
| Scenario Analysis | ⌘8 | ScenarioAnalysisContainer | **Real** |

Additionally: Risk Settings and Account Connections accessible via Settings — both real.

---

### Mock Data Items — Full Inventory

#### 1. Market Intelligence section (Overview view)

- **Location:** `PortfolioOverview.tsx` lines ~1245-1308
- **What users see:** Market events with impact badges, timeline, relevance scores
- **Data source:** `generateSmartAlerts()` callback — returns hardcoded demo events
- **Backend data available?** Yes — `/api/factors/*` endpoints have market/factor data;
  fmp-mcp `get_market_context` and `get_news` tools return real market intelligence.
  No frontend consumer wired yet.
- [ ] Design data flow: which backend source feeds this?
- [ ] Create hook or extend existing hook
- [ ] Wire to real data

#### 2. Smart Alerts section (Overview view)

- **Location:** `PortfolioOverview.tsx` lines ~1311-1358
- **What users see:** Risk/opportunity alerts with severity badges (High/Medium/Low)
- **Data source:** `generateSmartAlerts()` — hardcoded demo alerts
- **Backend data available?** Partially — risk analysis flags are computed by
  `core/*_flags.py` and returned in agent-format responses. Could surface these
  as alerts. MCP `check_exit_signals` tool also produces actionable alerts.
- [ ] Design alert data model
- [ ] Wire to risk flags or exit signals
- [ ] Remove demo data

#### 3. AI Recommendations panel (Overview view)

- **Location:** `PortfolioOverview.tsx` `generateAIRecommendations()` (~lines 688-743)
- **What users see:** 3 ML-generated recommendations (Rebalance, Hedge, Opportunity)
  with confidence scores (89-96%)
- **Data source:** Hardcoded — returns static recommendation objects
- **Backend data available?** Partially — optimization suggestions come from
  `/api/min-variance` and `/api/max-return`. Factor recommendations from
  `get_factor_recommendations` MCP tool. Could compose from these.
- [ ] Design recommendation data model
- [ ] Wire to optimization/factor recommendation backend data
- [ ] Remove hardcoded recommendations

#### 4. AI Insights on metric cards (Overview view)

- **Location:** `PortfolioOverview.tsx` — each metric card has AI insight text,
  confidence scores, correlations, technical signals, future projections
- **What users see:** Per-metric AI commentary like "Portfolio shows strong
  risk-adjusted returns" with 92% confidence, benchmark comparisons, volatility
  classification
- **Data source:** Hardcoded in metric card rendering logic
- **Backend data available?** The core metrics (value, P&L, Sharpe, alpha) come
  from real data via `usePortfolioSummary()`. The AI commentary/confidence/signals
  layer is entirely demo.
- [ ] Decide: generate AI insights server-side or client-side?
- [ ] If server-side: extend analysis response with interpretive text
- [ ] If client-side: compute from real metric values

#### 5. Notification Center

- **Location:** `notification-center.tsx` + `ModernDashboardApp.tsx` lines ~157-178
- **What users see:** Bell icon with badge count, dropdown with notification list
- **Data source:** Hardcoded initial notifications ("High Tech Concentration Detected",
  "Portfolio Data Updated")
- **Backend data available?** No dedicated notification endpoint. Could be derived
  from risk flags, exit signals, pending updates.
- [ ] Design notification system (real-time vs polling?)
- [ ] Wire to backend alert sources
- [ ] Remove hardcoded notifications

#### 6. FactorRiskModel.tsx (Factor Analysis view — entire view) — DONE (Wave 1)

- **Location:** `ui/src/components/portfolio/FactorRiskModel.tsx` + `FactorRiskModelContainer.tsx`
- **Status:** ✅ Wired via `FactorRiskModelContainer` → `useRiskAnalysis()` → `RiskAnalysisAdapter`
- **What's real now:** Factor Exposure tab (6 factors with betas + contributions), Risk Attribution tab (systematic/idiosyncratic split), Total Risk
- **Known gaps:** Performance tab still hardcoded (Factor Alpha, IR, R², Key Risk Insights). R² badge = 0.847 fallback. t-stat = 0.00 (not available from backend).
- [x] Create FactorRiskModelContainer
- [x] Wire to useRiskAnalysis()
- [x] Map factor exposures + risk attribution from backend
- [x] Fix `weighted_factor_var` DataFrame summation (post-fix)
- [ ] Wire Performance tab metrics (backend enrichment needed)

#### 7. Performance view — AI mock content (Performance view)

- **Location:** `ui/src/components/portfolio/PerformanceView.tsx` lines 405-636
- **What users see:** Four large mock sections within the otherwise-wired Performance view:
  - **AI Performance Insights** (lines 428-448): 3 insight cards (Performance 94%,
    Risk 87%, Opportunity 76%) with hardcoded commentary and confidence scores
  - **Sector Performance Attribution** (lines 450-524): "AI Enhanced" badge, per-sector
    momentum scores (8.4/10, 3.2/10, etc.), AI commentary ("Driving portfolio
    outperformance with AI/cloud growth"), recommendations ("Hold - Strong fundamentals")
  - **Top Contributors** (lines 527-583): "AI Insights" badge, hardcoded stock rankings
    (AAPL Buy Target $225, MSFT Strong Buy Target $450, NVDA Buy Target $1100, etc.)
  - **Top Detractors** (lines 585-619): "Recovery Watch" badge, hardcoded stock rankings
    (META Hold Target $380, NFLX Hold Target $420, PYPL Underperform Target $75)
- **Data source:** Entirely hardcoded `performanceData` object. Basic period returns
  use real data from props with fallback, but insights/sectors/contributors/detractors
  are 100% static.
- **Backend data available?** Partially — sector allocation + returns could come from
  risk analysis. Target prices/ratings could come from FMP analyst endpoints. Momentum
  scores have no direct backend source yet.
- [ ] Separate real vs mock data in performanceData object
- [ ] Wire sector attribution to useRiskAnalysis() sector data
- [ ] Wire target prices/ratings to FMP analyst data or remove
- [ ] Decide: keep AI commentary (generate from real data) or remove?
- [ ] Remove all hardcoded mock arrays

#### 8. PerformanceChart.tsx (standalone component) — DONE (Wave 1)

- **Location:** DELETED — `ui/src/components/portfolio/PerformanceChart.tsx`
- **Status:** ✅ Replaced with `PerformanceViewContainer` in score view. File deleted.
- [x] Confirmed duplicate of PerformanceViewContainer
- [x] Removed, score view now uses PerformanceViewContainer

#### 9. AssetAllocation.tsx (standalone component) — NOT A DUPLICATE

- **Location:** `ui/src/components/portfolio/AssetAllocation.tsx`
- **Status:** This is the presentation component correctly wired through `AssetAllocationContainer` → `useRiskAnalysis()`. It receives real data as props. The hardcoded `allocations` array serves as fallback when no props provided.
- **No action needed** — confirmed during Wave 1 planning that this is NOT a dead duplicate.

#### 10. RiskMetrics.tsx (standalone component) — DONE (Wave 1)

- **Location:** `ui/src/components/portfolio/RiskMetrics.tsx` + `RiskMetricsContainer.tsx`
- **Status:** ✅ Wired via `RiskMetricsContainer` → `useRiskAnalysis()` → `RiskAnalysisAdapter`
- **What's real now:** VaR (-$1,255), Beta (1.05), Volatility (8.5%), Max Drawdown (-55.9%), Risk Summary with variance decomposition
- [x] Create RiskMetricsContainer
- [x] Wire to useRiskAnalysis()
- [x] Map VaR/Beta/Vol/Drawdown from backend
- [x] Fix percentage rounding (post-fix)

#### 11. Holdings per-position enrichment

- **Location:** `HoldingsViewModernContainer.tsx`
- **What users see:** Holdings table with 7 fields hardcoded to zero/placeholder:
  - `sector`: always 'Unknown' (backend has sector from FMP profile)
  - `avgCost`: always 0 (available from IBKR Flex, Schwab transactions)
  - `currentPrice`: always 0 (available from `latest_price()`)
  - `totalReturn`: always 0 (computable from cost basis + price)
  - `riskScore`: always 0 (per-position risk score not implemented)
  - `volatility`: always 0 (available from `analyze_portfolio`)
  - `aiScore`: always 0 (not implemented)
  - Alert count badge: always 0 (could derive from risk flags)
- **Data source:** Hardcoded zeros/placeholders
- **Backend data available?** Most fields exist in backend — sector, price, cost basis,
  volatility all available. riskScore and aiScore would need new computation.
- **Cross-ref:** `FRONTEND_DATA_WIRING_AUDIT.md` Gap 1
- [ ] Enrich `/api/portfolio/summary` response with per-holding data
- [ ] Wire sector, currentPrice, avgCost, totalReturn, volatility
- [ ] Design per-position riskScore computation (or remove)
- [ ] Wire alert counts to risk flags

#### 12. Stock Research — real-time market data

- **Location:** `StockLookupContainer.tsx`
- **What users see:** Current price, market cap, trading volume for searched stocks
- **Data source:** Analysis data is real (from `/api/direct/stock`), but current
  price/market cap/volume have TODOs for "real market data API"
- **Backend data available?** FMP endpoints have real-time quotes, market cap, volume.
  Not wired to this component yet.
- [ ] Wire real-time price data from FMP
- [ ] Wire market cap and volume

#### 14. Hedging suggestions (Overview view, Advanced Risk Analysis)

- **Location:** `ui/src/components/portfolio/RiskAnalysis.tsx` lines 338-417
- **What users see:** 3 hedging strategy cards under "Hedging" tab:
  - "Put Options on QQQ" ($12.5K cost, $450K protection, High Efficiency)
  - "VIX Call Options" ($8.2K cost, $200K protection, Medium Efficiency)
  - "Gold Position 5%" ($142K cost, Inflation hedge)
  Each with "Implement Strategy" button, detailed steps, and market impact analysis
- **Data source:** Hardcoded fallback array. Code has conditional for adapter data
  (line 338) but adapter fields have TODOs (lines 332-335), so always falls back.
- **Backend data available?** Risk analysis response has some hedge-related data.
  Adapter would need `beforeVaR`, `afterVaR`, `riskReduction`, `portfolioBeta` fields.
- [ ] Populate RiskAnalysisAdapter with hedging data from backend
- [ ] Remove hardcoded fallback once adapter fields are wired
- [ ] Wire market impact metrics (VaR reduction, beta change)

#### 15. Strategy Builder mock data (Strategy Builder view) — DONE (Wave 1)

- **Location:** `ui/src/components/portfolio/StrategyBuilder.tsx`
- **Status:** ✅ Props wired — `optimizationData`, `onOptimize`, `onBacktest`, `loading` all consumed
- **What's real now:** `currentStrategy.metrics`, `optimizedStrategy`, `templates` from container. Graceful fallback to `prebuiltStrategies` when no optimization data.
- **Known gaps:** Backtesting still uses mock timer (no backend backtesting). `prebuiltStrategies` kept as fallback (not a bug — templates may not always be available).
- [x] Wire optimizationData prop to replace hardcoded results
- [x] Wire onOptimize/onBacktest callbacks
- [x] Wire loading prop
- [ ] Wire backtesting to real backend (future — backend doesn't support it yet)

#### 16. Market status indicator

- **Location:** `ModernDashboardApp.tsx` header
- **What users see:** "Market Open" / "After Hours" / "Closed" badge
- **Data source:** Calculated from local system time (assumes 9-16 EST)
- **Backend data available?** FMP has market hours data. Current implementation
  is functional but naive (no holiday awareness, single market assumption).
- [ ] Optional: wire to real market calendar

---

### Cross-Reference: FRONTEND_DATA_WIRING_AUDIT.md

A separate audit (`FRONTEND_DATA_WIRING_AUDIT.md`) analyzed wiring from the
container/adapter layer. Key findings reconciled:

| Their Gap | Our Item | Notes |
|-----------|----------|-------|
| Gap 1: Holdings enrichment (7 zero-fields) | Item 11 | Expanded our item to cover all 7 fields |
| Gap 2: Performance attribution (empty arrays) | Item 7 | Backend returns `[]`, frontend falls back to hardcoded |
| Gap 3: Hedging strategies | Item 14 | Same issue, different angle |
| Gap 4: Benchmark selection UI | — | UI feature gap, not mock data |
| Gap 5: Allocation period selector | — | Disabled feature, not mock data |

Their doc states "No mock stubs remain" — this is true at the **container/adapter** layer
(all containers use real hooks + adapters). The mock data lives in the **presentation
components** (PortfolioOverview.tsx, PerformanceView.tsx, StrategyBuilder.tsx, etc.)
which receive real data from containers but also render hardcoded sections alongside it.

---

## Part C: Dead Code Candidates

Components that appear unused or are explicitly marked as such:

| Component | Location | Status |
|-----------|----------|--------|
| `ConnectedRiskAnalysis.tsx` | components/portfolio/ | Marked "TEMPLATE/REFERENCE — Not actively used" |
| `AnalysisSection.tsx` | components/portfolio/ | Generic stub, purpose unclear |
| Legacy DashboardApp | components/apps/ | Old dashboard, superseded by ModernDashboardApp |

---

## Summary

| Category | Count | Status |
|----------|-------|--------|
| Fully wired views (real data end-to-end) | 4 of 8 views | Factor Analysis, Scenario, Chat, Settings |
| Partially wired views (mix of real + mock) | 4 of 8 views | Overview, Holdings, Performance, Strategy Builder |
| Fully mock views | 0 of 8 views | — (Factor Analysis moved to fully wired after Wave 1) |
| Total mock data items | 16 total, **4 resolved** (Wave 1) | Items 6, 8, 10, 15 done. 12 remaining. |
| Dead components cleaned | 1 | PerformanceChart.tsx deleted |
| Backend endpoints unused by frontend | 9 | `/api/direct/*`, `/api/factors/*`, `/api/positions/*` |

### Cross-Cutting: Shared Number Formatting — COMPLETE

**Problem:** No shared formatting layer. ~150+ inline formatting calls across 5 incompatible local formatters using `.toFixed()`, `.toLocaleString()`, `Intl.NumberFormat`.

**Solution:** `@risk/chassis/src/utils/formatting.ts` — 6 shared functions:

| Function | Purpose | Example output |
|----------|---------|---------------|
| `formatCurrency(value, opts?)` | Dollar amounts, optional compact | `$1,255`, `$1.2M` |
| `formatPercent(value, opts?)` | Percentages with optional sign | `8.5%`, `+12.35%` |
| `formatNumber(value, opts?)` | General numeric display | `1.05`, `+2` |
| `formatCompact(value, opts?)` | Large numbers with suffix | `1.2T`, `$450B` |
| `formatBasisPoints(value)` | Basis points from decimal | `42 bp` |
| `roundTo(value, decimals?)` | Numeric rounding (not display) | `1.23` |

**Safety:** NaN/Infinity → `"—"`, -0 normalized, Intl caching, hardcoded `en-US`/`USD`.

**Migrated files (14):** RiskMetricsContainer, PerformanceView, StrategyBuilder, HoldingsView, PortfolioOverview, FactorRiskModel, RiskAnalysisAdapter, PerformanceAdapter, RiskSettingsAdapter, useAnalysisReport, registry. All local formatters deleted, all `.toFixed()` replaced.

**Status:** COMPLETE — Codex implemented (2 rounds: v1 + 3 follow-up fixes), verified in Chrome 2026-02-27. See `FRONTEND_FORMATTING_MODULE_PLAN.md`.

---

### Execution Plan — Three Waves + Formatting Foundation

#### Wave 1: Pure Frontend (no backend changes needed)

All data already flows through hooks/adapters. Just need presentation components to use it.

| # | Task | Items | Effort | Status |
|---|------|-------|--------|--------|
| 1a | Replace PerformanceChart with PerformanceViewContainer | 8 | Small | ✅ DONE |
| 1b | Wire FactorRiskModel via FactorRiskModelContainer | 6 | Medium | ✅ DONE (Performance tab still mock) |
| 1c | Wire RiskMetrics via RiskMetricsContainer | 10 | Medium | ✅ DONE |
| 1d | Wire StrategyBuilder props | 15 | Medium | ✅ DONE (backtesting still mock) |

**Implementation:** Codex implemented all 4 tasks. Two post-fixes applied: percentage rounding in RiskMetricsContainer, `weighted_factor_var` DataFrame summation in FactorRiskModelContainer.

**Status:** COMPLETE — verified in Chrome 2026-02-27. See `FRONTEND_WAVE1_IMPLEMENTATION_PLAN.md` for detailed verification results.

#### Wave 2: Frontend + Backend Enrichment

Backend endpoint changes needed to provide data that frontend is ready to consume.

| # | Task | Items | Effort | Description |
|---|------|-------|--------|-------------|
| 2a | Holdings enrichment | 11 | Medium | Enrich `/api/portfolio/summary` with per-holding sector, currentPrice, avgCost, totalReturn, volatility. Backend data exists, just not threaded to endpoint. |
| 2b | Hedging suggestions | 14 | Medium | Populate `RiskAnalysisAdapter` hedging fields (beforeVaR, afterVaR, riskReduction, portfolioBeta) from backend risk analysis response. Remove hardcoded fallback. |
| 2c | Performance attribution | 7 (partial) | Medium | Thread sector/factor attribution from `analyze_portfolio` into performance endpoint. Frontend already has UI for it but backend returns empty arrays. |
| 2d | Stock Research prices | 12 | Medium | Wire FMP real-time quotes (price, market cap, volume) to `StockLookupContainer`. |
| 2e | FactorRiskModel Performance tab + R² | 6 (residual) | Medium | Wire Factor Alpha (from `historical_analysis`), Information Ratio (compute from alpha/tracking error), R² (compute from `variance_decomposition.factor_variance / 100`). Wire Key Risk Insights text from real factor betas instead of hardcoded text. Also expose R² in header badge. t-stat: requires regression p-values from backend — low priority. |

**Status:** Ready — Wave 1 complete

#### Wave 3: Design Decisions + New Features

Need architectural decisions before implementation. Each item has a "server-side vs client-side" or "build vs remove" question.

| # | Task | Items | Decision needed |
|---|------|-------|-----------------|
| 3a | Market Intelligence | 1 | Which backend source? FMP news/market context vs factor endpoints? |
| 3b | Smart Alerts | 2 | Derive from risk flags / exit signals? Real-time vs polling? |
| 3c | Notification Center | 5 | Design notification system — event-driven vs derived from alerts? |
| 3d | AI Recommendations | 3 | Server-side generation (analyst agent) vs client-side from optimization data? |
| 3e | AI Insights (metric cards) | 4 | Server-side interpretive text vs client-side computed from real values? |
| 3f | Performance AI content | 7 (partial) | Wire target prices/ratings to FMP analyst data? Or strip mock AI layer? |
| 3g | Strategy Builder backtesting | 15 (residual) | Backtesting uses mock timer — build real backend backtesting or remove? Props wiring done in Wave 1. |
| 3h | Unused backend endpoints | — | Keep `/api/direct/*`, `/api/factors/*`, `/api/positions/*` for CLI/API use or deprecate? |
| 3i | Market status indicator | 16 | Optional: wire to real market calendar or keep naive time-based? |

**Status:** Blocked on design decisions
