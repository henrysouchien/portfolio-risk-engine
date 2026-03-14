# Frontend Phase 2 — Working Doc

**Parent doc:** `completed/FRONTEND_PACKAGE_DESIGN.md`
**Status:** ALL WAVES COMPLETE (Wave 1 + formatting + Wave 2a-2e + Wave 2.5 + Wave 2.6 + Wave 3a-3i). All 16 original mock data items resolved. Phase 4 workflow upgrades in progress (see TODO.md).
**Last verified:** 2026-03-03 (full audit)

### Related Docs
| Doc | Purpose |
|-----|---------|
| `COMPOSABLE_APP_FRAMEWORK_PLAN.md` | Phase 3 — the SDK/framework this work feeds into |
| `completed/FRONTEND_WAVE1_IMPLEMENTATION_PLAN.md` | Wave 1 detailed implementation plan (Codex-reviewed) |
| `FRONTEND_COMPONENT_VISUAL_MAP.md` | Visual guide: what you see on screen → code component |
| `completed/FRONTEND_DATA_WIRING_AUDIT.md` | Container/adapter audit (ported into this doc) |
| `completed/FRONTEND_FORMATTING_MODULE_PLAN.md` | Shared formatting module plan (Codex-reviewed, complete) |
| `completed/FRONTEND_HOLDINGS_ENRICHMENT_PLAN.md` | Holdings enrichment via PositionService + sector (COMPLETE) |
| `MCP_POSITIONS_ENRICHMENT_PLAN.md` | MCP agent format: sector + P&L + 4 new flags (planning) |

---

## Drift Corrections (2026-03-03)

This file is still the main tracking doc, but several references in earlier sections were stale.

- Scenario Analysis is **fully** real. What-if, stress tests, Monte Carlo all wired. Scenario history now persists to database (`93b7ce83`).
- `PerformanceChart.tsx` is still present in `ui/src/components/portfolio/`, but it is legacy and not rendered by `ModernDashboardApp`.
- Completed docs have moved under `docs/planning/completed/`; links in this file are updated where referenced.

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
| Holdings | `/api/positions/holdings` | usePositions | PositionsAdapter | HoldingsViewModernContainer | WIRED (Wave 2a) |
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
| `/api/positions/monitor` | Position monitor — no frontend consumer (holdings uses `/api/positions/holdings`) |

---

## Part B: UI Features Using Mock / Demo Data

This is the comprehensive list of every visible feature in the app that does NOT
use real backend data. Organized by dashboard view.

### Dashboard View Map (ModernDashboardApp)

The app has 8 views accessed via keyboard shortcuts or navigation:

| View | Shortcut | Container | Real Data? |
|------|----------|-----------|------------|
| Overview | ⌘1 | PortfolioOverviewContainer + PerformanceViewContainer + RiskMetricsContainer | **Real** — metric cards + metric insights on all 6 cards, Smart Alerts (5 real), Market Intelligence (earnings + sentiment + relevance), AI Recommendations (concentration + priority). All 4 AI/insight hooks live. Residual: hedging dialog impact metrics (cosmetic only). |
| Holdings | ⌘2 | HoldingsViewModernContainer | **Real** — P&L, sectors, day change, sparklines, alerts with tooltip messages (`d644687f`), per-position risk scores (`8a8445ad`) |
| Factor Analysis | ⌘3 | FactorRiskModelContainer + RiskMetricsContainer | **Real** (Wave 1 + 2e) — factor exposures, risk attribution, Performance tab (Alpha, IR, R²). Gap: t-stat |
| Performance | ⌘4 | PerformanceViewContainer | **Real** (Wave 2c + 3f) — all mock fallbacks removed, real sector/security attribution, real monthly returns |
| Strategy Builder | ⌘5 | StrategyBuilderContainer | **Real** — optimization + backtesting (3g) wired. `prebuiltStrategies` fallback when no data. Perf issue: optimization blocks 60+ sec. |
| Stock Research | ⌘6 | StockLookupContainer | **Real** (Wave 2d + 2.6 + Phase 4) — search, profile, quote, ratios, chart, risk metrics, factor analysis, peer comparison, portfolio fit (`3337f2d1`). Residual: analyst consensus, technical indicators (synthetic fallbacks) |
| AI Assistant | ⌘7 | ChatInterface | **Real** |
| Scenario Analysis | ⌘8 | ScenarioAnalysisContainer | **Real** — what-if execution, stress tests (Wave 3h), Monte Carlo simulation (`078aed92`), scenario history persisted to DB (`93b7ce83`), optimization tab (`b6f3e45e`). All 5 phases of overhaul complete + DB persistence. |

Additionally: Risk Settings and Account Connections accessible via Settings — both real.

---

### Mock Data Items — Full Inventory

#### ~~1. Market Intelligence section (Overview view)~~ ✓ DONE (Wave 3a)

- **Completed:** `5151dd0a`. Shared `build_market_events()` in `mcp_tools/news_events.py` reuses existing `get_portfolio_news()` / `get_portfolio_events_calendar()`. Thin `/api/positions/market-intelligence` endpoint. `useMarketIntelligence()` hook + container wiring. Internal `marketEvents = []` stub removed.
- **Plan:** `completed/MARKET_INTELLIGENCE_WAVE3A_PLAN.md`
- [x] Design data flow: which backend source feeds this?
- [x] Create hook or extend existing hook
- [x] Wire to real data

#### ~~2. Smart Alerts section (Overview view)~~ ✓ DONE (Wave 3b)

- **Completed:** `1dea17ba`. New `/api/positions/alerts` endpoint aggregates `generate_position_flags()` into frontend `SmartAlert` shape. `useSmartAlerts()` hook + container wiring. `generateSmartAlerts()` stub removed.
- **Plan:** `completed/SMART_ALERTS_WAVE3B_PLAN.md`
- [x] Design alert data model
- [x] Wire to risk flags or exit signals
- [x] Remove demo data

#### ~~3. AI Recommendations panel (Overview view)~~ ✓ DONE (Wave 3d)

- **Completed:** `aae47747`. `build_ai_recommendations()` shared builder in `mcp_tools/factor_intelligence.py` composes risk drivers + hedge suggestions from `FactorIntelligenceService.recommend_portfolio_offsets()`. `GET /api/positions/ai-recommendations` endpoint. `useAIRecommendations()` hook with 10-min cache. Container passes `aiRecommendations` prop to `PortfolioOverview`. Up to 6 recommendations with priority/confidence/action items. Toggle in display settings.
- **Plan:** `completed/AI_RECOMMENDATIONS_WAVE3D_PLAN.md`
- [x] Design recommendation data model
- [x] Wire to optimization/factor recommendation backend data
- [x] Remove hardcoded recommendations

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
- [x] Decide: generate AI insights server-side or client-side? → Server-side (Option B)
- [x] Wire backend flags into metric card AI insights (Wave 3e, commit `bc107e04`)
- [x] ~~If client-side~~ N/A — implemented server-side (Option B)

#### ~~5. Notification Center~~ ✓ DONE (Wave 3c)

- **Completed:** `1505c1f1`. Frontend composition hook `useNotifications()` composing `useSmartAlerts()` + `usePendingUpdates()` + `useNotificationStorage()` (localStorage). Backend fix: alert ID uniqueness (`_build_alert_id()` in `routes/positions.py`). `alertMappings.ts` maps ~20 flag types → titles + navigation actions. Plan: `completed/NOTIFICATION_CENTER_WIRING_PLAN.md`.
- [x] Design notification system (real-time vs polling?)
- [x] Wire to backend alert sources
- [x] Remove hardcoded notifications

#### 6. FactorRiskModel.tsx (Factor Analysis view — entire view) — DONE (Wave 1)

- **Location:** `ui/src/components/portfolio/FactorRiskModel.tsx` + `FactorRiskModelContainer.tsx`
- **Status:** ✅ Wired via `FactorRiskModelContainer` → `useRiskAnalysis()` → `RiskAnalysisAdapter`
- **What's real now:** Factor Exposure tab (6 factors with betas + contributions), Risk Attribution tab (systematic/idiosyncratic split), Total Risk
- **Known gaps:** t-stat not available from backend (needs regression p-values).
- [x] Create FactorRiskModelContainer
- [x] Wire to useRiskAnalysis()
- [x] Map factor exposures + risk attribution from backend
- [x] Fix `weighted_factor_var` DataFrame summation (post-fix)
- [x] Wire Performance tab metrics — Factor Alpha, IR, R² wired from `variance_decomposition` + `historical_analysis` (Wave 2e, commit `dbcee8c9`)

#### ~~7. Performance view — AI mock content (Performance view)~~ ✓ DONE (Wave 3f)

- **Completed:** `52c6d95a`. Deleted 5 fallback arrays (fallbackSectors, fallbackTopContributors, fallbackTopDetractors, fallbackMetrics, hardcoded monthlyReturns). Refactored `buildInsights()` to detect no-data via `=== 0` instead of comparing against deleted fallbackMetrics. Wired real monthly returns by computing per-month deltas from cumulative timeSeries. Added empty-state guards. Changed "AI Enhanced" badge to "Portfolio Data". Plan: `completed/PERFORMANCE_MOCK_REMOVAL_PLAN.md`.
- [x] Separate real vs mock data in performanceData object
- [x] Wire sector attribution to useRiskAnalysis() sector data
- [x] Wire target prices/ratings to FMP analyst data or remove
- [x] Decide: keep AI commentary (generate from real data) or remove?
- [x] Remove all hardcoded mock arrays

#### 8. PerformanceChart.tsx (standalone component) — LEGACY UNUSED

- **Location:** `ui/src/components/portfolio/PerformanceChart.tsx`
- **Status:** Not mounted in `ModernDashboardApp`; overview and performance views use `PerformanceViewContainer`.
- [x] Replaced in active dashboard routing
- [ ] Optional cleanup: remove file when no external import/dependency needs it

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

#### 11. Holdings per-position enrichment — DONE (Wave 2a)

- **Location:** `HoldingsViewModernContainer.tsx` → `usePositions()` → `/api/positions/holdings`
- **Status:** ✅ Core fields wired via `PositionsAdapter` from `PositionService.to_monitor_view()` + `PortfolioService.enrich_positions_with_sectors()`
- **What's real now:** ticker, value, weight, currency, type, account, brokerage, sector (via FMP), P&L (unrealized_pnl_usd, pnl_percent), cost basis, current price, quantity, gross/net exposure
- **Implementation:** New `/api/positions/holdings` endpoint, `usePositions()` hook (direct TanStack Query), `PositionsAdapter` with null→undefined normalization. Weight formatting fix applied.
- **Cross-ref:** `completed/FRONTEND_HOLDINGS_ENRICHMENT_PLAN.md` (COMPLETE), `completed/FRONTEND_DATA_WIRING_AUDIT.md` Gap 1
- [x] New `/api/positions/holdings` endpoint with P&L + sector
- [x] Wire sector via `PortfolioService.enrich_positions_with_sectors()`
- [x] Wire price, cost basis, P&L, weight, exposure
- [x] Wire remaining fields — volatility, alerts, dayChange, trend (Wave 2.5), aiScore/riskScore removed

#### ~~12. Stock Research — real-time market data~~ ✓ DONE (Wave 2d)

- **Completed:** `4ae8115f` (wiring) + `a252407c` (field fixes) + `941c92e0` (refactor to service layer)
- Search endpoint (`GET /api/direct/stock/search`) with real FMP search + batch quote
- Stock enrichment (profile, quote, ratios_ttm, historical chart) via `StockService.enrich_stock_data()`
- Frontend: `useStockSearch` hook, search dropdown in StockLookup, adapter pass-through
- Plans: `completed/STOCK_RESEARCH_FMP_WIRING_PLAN.md`, `completed/STOCK_ENRICHMENT_REFACTOR_PLAN.md`

#### 14. Hedging suggestions (Overview view, Advanced Risk Analysis)

- **Location:** `ui/src/components/portfolio/RiskAnalysis.tsx` lines 338-417
- **What users see:** 3 hedging strategy cards under "Hedging" tab:
  - "Put Options on QQQ" ($12.5K cost, $450K protection, High Efficiency)
  - "VIX Call Options" ($8.2K cost, $200K protection, Medium Efficiency)
  - "Gold Position 5%" ($142K cost, Inflation hedge)
  Each with "Implement Strategy" button, detailed steps, and market impact analysis
- **Data source:** Mixed. Container now provides hedging recommendations via
  `useHedgingRecommendations` + `HedgingAdapter`, but detailed impact metrics in
  dialog content still rely on fallback placeholders.
- **Backend data available?** Risk analysis response has some hedge-related data.
  Adapter would need `beforeVaR`, `afterVaR`, `riskReduction`, `portfolioBeta` fields.
- [ ] Populate RiskAnalysisAdapter with hedging data from backend
- [ ] Remove hardcoded fallback once adapter fields are wired
- [ ] Wire market impact metrics (VaR reduction, beta change)

#### 15. Strategy Builder mock data (Strategy Builder view) — DONE (Wave 1)

- **Location:** `ui/src/components/portfolio/StrategyBuilder.tsx`
- **Status:** ✅ Props wired — `optimizationData`, `onOptimize`, `onBacktest`, `loading` all consumed
- **What's real now:** `currentStrategy.metrics`, `optimizedStrategy`, `templates` from container. Graceful fallback to `prebuiltStrategies` when no optimization data.
- **Known gaps:** `prebuiltStrategies` kept as fallback (not a bug — templates may not always be available).
- [x] Wire optimizationData prop to replace hardcoded results
- [x] Wire onOptimize/onBacktest callbacks
- [x] Wire loading prop
- [x] Wire backtesting to real backend — Wave 3g complete (`76bf0121` backend, `6e007162` frontend, `733b8c9e` endpoint). `useBacktest()` hook + `POST /api/backtest` + `BacktestAdapter`.

#### 16. Market status indicator

- **Location:** `ModernDashboardApp.tsx` header
- **What users see:** "Market Open" / "After Hours" / "Closed" badge
- **Data source:** Calculated from local system time (assumes 9-16 EST)
- **Backend data available?** FMP has market hours data. Current implementation
  is functional but naive (no holiday awareness, single market assumption).
- [ ] Optional: wire to real market calendar

---

### Cross-Reference: completed/FRONTEND_DATA_WIRING_AUDIT.md

A separate audit (`completed/FRONTEND_DATA_WIRING_AUDIT.md`) analyzed wiring from the
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
| Fully wired views (real data end-to-end) | 8 of 8 views | Overview, Holdings, Factor Analysis, Performance, Strategy Builder, Stock Research, AI Assistant, Scenario Analysis |
| Partially wired views (mix of real + residual placeholders) | 0 of 8 views | — (Overview hedging dialog impact metrics are cosmetic only) |
| Fully mock views | 0 of 8 views | — |
| Total mock data items | 16 total, **16 resolved** (Wave 1 + 2a-2e + 2.5 + 2.6 + 3a-3i) | All original items done. |
| Dead components cleaned | 0 | `PerformanceChart.tsx` still exists but is legacy/unused in active dashboard routes |
| Backend endpoints unused by frontend | 15 annotated | Wave 3h: deprecation comments added to 6 `/api/direct/*`, 3 factor-intelligence, 5 factor-groups CRUD, 1 positions/monitor |
| Market status indicator | Fixed | Wave 3i: ET timezone-aware (Intl.DateTimeFormat) with pre-market/open/after-hours/closed + weekend detection |

### Post-Wave 3 Features (Phase 4 Workflow Upgrades)

Features completed after the original 16-item mock data audit:

| Feature | Commit | Description |
|---------|--------|-------------|
| Per-position risk scores | `8a8445ad` | Risk score badges on Holdings view (High/Medium/Low color-coded) |
| Stock Lookup workflow | `3337f2d1` | Peer Comparison + Portfolio Fit + trade preview tabs (Phase 4) |
| Backtesting engine | `76bf0121` + `6e007162` | 5-phase engine: BacktestEngine class, POST /api/backtest, useBacktest hook, Strategy Builder wiring |
| Stress test engine | `d1df3fee`→`a1d598fb` | 8 scenarios, 3 API endpoints, full frontend wiring (Wave 3h). useStressTest/useStressScenarios hooks, StressTestAdapter, live Run with position impacts + factor contributions. |
| Schwab RECEIVE_AND_DELIVER | `d2bfa1dd` | Account 252 aggregated return 273.92% → 0.82% |
| Alert badge tooltip | `d644687f` | Per-position alert details threaded through API → adapter → native title tooltip on Holdings badge |
| Hedging workflow plan | `bf87623d` | Phase 4 plan written (Codex-reviewed PASS), not yet implemented |

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

**Status:** COMPLETE — Codex implemented (2 rounds: v1 + 3 follow-up fixes), verified in Chrome 2026-02-27. See `completed/FRONTEND_FORMATTING_MODULE_PLAN.md`.

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

**Status:** COMPLETE — verified in Chrome 2026-02-27. See `completed/FRONTEND_WAVE1_IMPLEMENTATION_PLAN.md` for detailed verification results.

#### Wave 2: Frontend + Backend Enrichment

Backend endpoint changes needed to provide data that frontend is ready to consume.

| # | Task | Items | Effort | Description |
|---|------|-------|--------|-------------|
| 2a | Holdings enrichment | 11 | Medium | ✅ DONE — `/api/positions/holdings` + `usePositions()` + `PositionsAdapter` + sector via FMP. Plan: `completed/FRONTEND_HOLDINGS_ENRICHMENT_PLAN.md`. |
| 2b | Hedging suggestions | 14 | Medium-High | ✅ PARTIAL — `useHedgingRecommendations` hook + `HedgingAdapter` + container wiring (commit `1c66dae7`). Backend fixes: ETF→sector label resolution, correlation threshold -0.2→0.3 (commit `475a67e5`). Dialog impact metrics still fallback. Plan: `completed/FRONTEND_HEDGING_WIRING_PLAN.md`. |
| 2c | Performance attribution | 7 (partial) | Medium | ✅ DONE — Sector + security attribution computed in `calculate_portfolio_performance_metrics()` from `df_ret` + `filtered_weights`. FMP profile sector lookup. Threaded through `PerformanceResult` → API → `PerformanceAdapter` → `PerformanceView`. Factor attribution deferred to P2b. Verified in Chrome 2026-02-28. Plan: `completed/PERFORMANCE_ATTRIBUTION_PLAN.md`. |
| 2d | ~~Stock Research prices~~ | 12 | ~~Medium~~ | **DONE** (`4ae8115f` + `941c92e0`). Search + enrichment wired via StockService. |
| 2e | FactorRiskModel Performance tab + R² | 6 (residual) | Medium | ✅ DONE — Factor Alpha, IR, R² wired from backend `variance_decomposition` + `historical_analysis`. Key Risk Insights from real factor betas. R² in header badge. Commit `dbcee8c9`. |

**Status:** Wave 2 COMPLETE (2a-2e all done).

#### Wave 2.5: Holdings Enrichment Part 2 — DONE

Per-position fields added to `/api/positions/holdings` endpoint. Plan: `completed/HOLDINGS_ENRICHMENT_WAVE2_5_PLAN.md`. Commit `06e8759b`.

| Field | Status |
|-------|--------|
| `dayChange` / `dayChangePercent` | ✅ DONE — FMP batch quote endpoint |
| `trend` (30-day sparkline) | ✅ DONE — FMP `historical_price_eod`, parallel fetch |
| `volatility` (annualized) | ✅ DONE — computed from same historical data |
| `alerts` (per-position count) | ✅ DONE — `generate_position_flags()` per-ticker counting |
| `aiScore` removed from UI | ✅ DONE — undefined field, no spec |
| `riskScore` removed from UI | ✅ DONE — undefined field, no spec |
| `mockHoldings` deleted | ✅ DONE — all mock data removed, fallback defaults fixed |

#### Wave 2.6: Stock Research — Wire Real Risk Data — DONE

Backend + frontend fixes to wire real risk metrics into the Stock Research view. Plan: `completed/STOCK_RESEARCH_WAVE2_6_PLAN.md`. Commit `03f010ea`.

| Fix | Status |
|-----|--------|
| `max_drawdown` added to `vol_metrics` (both analysis paths) | ✅ DONE |
| `sharpe_ratio`/`sortino_ratio` added to multi-factor path | ✅ DONE |
| Volatility display scale fixed (decimal → percentage) | ✅ DONE |
| Sharpe ratio reads from correct source (was hardcoded 1.2) | ✅ DONE |
| Max drawdown reads real value (was synthetic vol*-2) | ✅ DONE |
| Correlation bug fixed (was R², now √R²·sign(β)) | ✅ DONE |
| VaR 95/99% uses daily vol (was annual vol) | ✅ DONE |
| Risk Factors tab replaced with real factor_summary data | ✅ DONE |
| Adapter extended: volatility_metrics + full factor_summary | ✅ DONE |

#### Wave 3: Design Decisions + New Features

Need architectural decisions before implementation. Each item has a "server-side vs client-side" or "build vs remove" question.

| # | Task | Items | Decision needed |
|---|------|-------|-----------------|
| ~~3a~~ | ~~Market Intelligence~~ | ~~1~~ | **DONE** (`5151dd0a`). FMP news + earnings calendar via shared `build_market_events()`. |
| 3b | ~~Smart Alerts~~ | 2 | ✅ DONE — `/api/positions/alerts` endpoint + `useSmartAlerts()` hook. Commit `1dea17ba`. Plan: `completed/SMART_ALERTS_WAVE3B_PLAN.md`. |
| ~~3c~~ | ~~Notification Center~~ | ~~5~~ | **DONE** (`1505c1f1`). `useNotifications()` composing `useSmartAlerts()` + `usePendingUpdates()`. Plan: `completed/NOTIFICATION_CENTER_WIRING_PLAN.md`. |
| ~~3d~~ | ~~AI Recommendations~~ | ~~3~~ | **DONE** (`aae47747`). `build_ai_recommendations()` shared builder + `GET /ai-recommendations` endpoint + `useAIRecommendations()` hook. Plan: `completed/AI_RECOMMENDATIONS_WAVE3D_PLAN.md`. |
| ~~3e~~ | ~~AI Insights (metric cards)~~ | ~~4~~ | **DONE** (`bc107e04`). `build_metric_insights()` shared builder + `GET /metric-insights` endpoint + `useMetricInsights()` hook. 3 flag generators → 7 metric cards. Plan: `completed/METRIC_INSIGHTS_WAVE3E_PLAN.md`. |
| ~~3f~~ | ~~Performance AI content~~ | ~~7 (partial)~~ | **DONE** (`52c6d95a`). Deleted 5 fallback arrays, refactored buildInsights(), wired real monthly returns, empty-state guards. Plan: `completed/PERFORMANCE_MOCK_REMOVAL_PLAN.md`. |
| ~~3g~~ | ~~Strategy Builder backtesting~~ | ~~15~~ | **DONE** (`76bf0121` backend, `6e007162` frontend, `733b8c9e` endpoint). 5-phase backtesting engine: `BacktestEngine` class, `POST /api/backtest`, `useBacktest()` hook, `BacktestAdapter`, Strategy Builder tab wiring. Plan: `completed/BACKTESTING_ENGINE_PLAN.md`. |
| ~~3h~~ | ~~Unused backend endpoints~~ | ~~—~~ | **DONE** — Added deprecation comments to 15 unused endpoints (6 `/api/direct/*`, 3 factor-intelligence, 5 factor-groups CRUD, 1 positions/monitor). Active endpoints kept. |
| ~~3i~~ | ~~Market status indicator~~ | ~~16~~ | **DONE** — ET timezone-aware market hours via `Intl.DateTimeFormat`. Handles pre-market/open/after-hours/closed + weekend detection. |

**Status:** ALL WAVES 3a-3i COMPLETE. All 16 original mock data items resolved.
