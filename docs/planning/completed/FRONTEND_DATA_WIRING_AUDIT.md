# Frontend Data Wiring Audit

**Date**: 2026-02-25
**Status**: Audit complete — gaps documented
**Ported to**: `FRONTEND_PHASE2_WORKING_DOC.md` — all 5 gaps reconciled with the
comprehensive mock data inventory (16 items). See that doc's cross-reference table
for the mapping. That doc is the single source of truth for Phase 2 work.

### Related Docs
| Doc | Purpose |
|-----|---------|
| `FRONTEND_PHASE2_WORKING_DOC.md` | Phase 2 master doc — this audit's findings are merged there |
| `FRONTEND_COMPONENT_VISUAL_MAP.md` | Visual guide mapping on-screen UI to code components |

## Summary

All 9 modern dashboard containers are wired to real backend APIs. No mock stubs or placeholders remain. The frontend package split is clean and enforced. The remaining gaps are **backend data enrichment** — the frontend has the wiring ready but the backend doesn't provide the data yet.

## Phase 1: Package Formalization — Complete

| Check | Status |
|-------|--------|
| Clean separation (chassis/connectors/ui) | Done |
| ESLint boundary enforcement | Done |
| package.json exports / public API | Done |
| TypeScript project references + build | Done |
| Typecheck: 0 errors | Done |
| Lint: 0 errors, 308 warnings | Done |

## Phase 2: Container Data Wiring — Complete

All 9 modern containers use real API data via the adapter pattern:

| Container | Hook | Adapter | API | Status |
|-----------|------|---------|-----|--------|
| PortfolioOverview | `usePortfolioSummary` | PortfolioSummaryAdapter | POST /api/portfolio/summary | Real data |
| HoldingsView | `usePortfolioSummary` + `usePlaid` | PortfolioSummaryAdapter | /portfolio/summary + /plaid/accounts | Real data |
| PerformanceView | `usePerformance` | PerformanceAdapter | POST /api/performance | Real data |
| RiskAnalysis | `useRiskAnalysis` + `useRiskScore` | RiskAnalysis/RiskScoreAdapter | POST /api/analyze + /api/risk-score | Real data |
| AssetAllocation | `useRiskAnalysis` | RiskAnalysisAdapter | POST /api/analyze | Real data |
| RiskSettings | `useRiskSettings` + `useRiskMetrics` | RiskSettingsAdapter | GET/POST /api/risk-settings | Real data + save |
| ScenarioAnalysis | `useWhatIfAnalysis` | WhatIfAnalysisAdapter | POST /api/portfolio/whatif | Real data |
| StockLookup | `useStockAnalysis` | StockAnalysisAdapter | GET /api/stocks/{ticker} | Real data |
| StrategyBuilder | `usePortfolioOptimization` | PortfolioOptimizationAdapter | POST /api/portfolio/optimize | Real data |

### Data flow pattern (all containers)

```
Backend API → SessionManager → CacheService (30-min TTL) + TanStack Query (5-min stale)
  → Adapter.transform() → useXxx hook → Container → Presentation Component
```

All containers include: EventBus cache invalidation, error handling (LoadingSpinner/ErrorMessage/NoDataMessage), React.memo optimization, frontendLogger lifecycle tracking.

## Gaps: Backend Data Enrichment Needed

These are places where the frontend has the wiring/UI ready but the backend response is empty or incomplete.

### Gap 1: Holdings Per-Position Enrichment

**Container**: HoldingsViewModernContainer
**File**: `packages/ui/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx`

Currently the holdings table shows basic data (ticker, name, value, shares, weight) but hardcodes zeros for enriched fields:

| Field | Current | Backend source available? |
|-------|---------|--------------------------|
| `sector` | `'Unknown'` | Yes — `get_positions` returns sector from FMP profile |
| `avgCost` | `0` | Partial — available from IBKR Flex, Schwab transactions |
| `currentPrice` | `0` | Yes — `latest_price()` in run_portfolio_risk |
| `totalReturn` | `0` | Yes — computable from cost basis + current price |
| `riskScore` | `0` | No — per-position risk score not implemented |
| `volatility` | `0` | Yes — available from `analyze_portfolio` risk metrics |
| `aiScore` | `0` | No — AI analysis score not implemented |

**Action**: Enrich the `/api/portfolio/summary` response to include sector, currentPrice, avgCost, totalReturn, and volatility per holding. These are all available from existing backend data — just not threaded into the summary endpoint.

### Gap 2: Performance Attribution

**Container**: PerformanceViewContainer
**File**: `packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`

The performance view has UI for attribution breakdowns but the backend returns empty arrays:

```typescript
attribution: {
  sectors: [],   // Sector-level return attribution
  factors: [],   // Factor-level attribution
  security: []   // Security-level attribution
}
```

**Action**: The backend `analyze_portfolio` already computes variance decomposition and factor exposures. Thread sector/factor attribution into the performance endpoint response. Security-level attribution requires per-position return tracking.

### Gap 3: Hedging Strategies

**Container**: RiskAnalysisModernContainer
**File**: `packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx`

```typescript
hedgingStrategies: [] // Backend doesn't provide hedging strategies yet
```

**Action**: This is a new feature — generate hedging recommendations based on portfolio risk exposures (e.g., "Buy SPY puts to hedge market beta", "Add TLT to reduce equity correlation"). Could be an AI-generated feature via the analyst agent.

### Gap 4: Configurable Benchmark Selection

**Container**: PerformanceViewContainer

Performance comparison uses a default benchmark. No UI for the user to select alternative benchmarks.

**Action**: Add benchmark selector UI (SPY, QQQ, custom) that passes to the backend performance endpoint. Backend already supports `benchmark` parameter.

### Gap 5: Asset Allocation Period Selector

**Container**: AssetAllocationContainer
**File**: `packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx`

Period selector is disabled but wiring is preserved for future re-enable.

**Action**: Low priority — re-enable when historical allocation snapshots are available from backend.

## Priority Ranking

| Priority | Gap | Effort | Value |
|----------|-----|--------|-------|
| **P1** | Holdings enrichment (sector, price, cost, return) | Medium — data exists, needs endpoint threading | High — core portfolio view |
| **P2** | Performance attribution (sector/factor) | Medium — partial data exists in risk analysis | High — key analytical feature |
| **P3** | Benchmark selection UI | Low — backend param exists, just needs UI | Medium — user-facing config |
| **P4** | Hedging strategies | High — new feature, possibly AI-generated | Medium — advanced feature |
| **P5** | Asset allocation periods | Low — re-enable existing code | Low — historical data needed |

## Frontend Cleanup Remaining

| Item | Count | Notes |
|------|-------|-------|
| `no-explicit-any` | **0** | Fully resolved (590→0). `as any` tokens: 180→5. |
| `no-console` | 41 | `console.log/warn/error` calls |
| `react/no-array-index-key` | 29 | Array index as React key |
| `react-hooks/exhaustive-deps` | 22 | Missing hook deps — fix carefully |
| Other | 22 | Empty functions, unescaped entities, etc. |
| **Total** | **114** | 0 errors |
