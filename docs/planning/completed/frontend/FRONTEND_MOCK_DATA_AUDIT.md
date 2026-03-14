# Frontend Mock Data & Unwired Components Audit

**Date**: 2026-03-02
**Status**: AUDIT COMPLETE — ready for planning

## Summary

16 issues found: 7 HIGH, 6 MEDIUM, 3 LOW. The dashboard shows fake numbers ($2.8M portfolio value, $18K daily P&L, etc.) because adapter fields return 0/null and components fall back to hardcoded mock values.

**Key insight**: The container→adapter→hook infrastructure is mostly in place. The gap is in the adapters not extracting fields that the backend already provides, plus some components with inline mock datasets that were never replaced.

---

## HIGH — User-Facing Fake Numbers

### 1. PortfolioOverview.tsx — Top-Level Dashboard Cards
**File**: `packages/ui/src/components/portfolio/PortfolioOverview.tsx` (lines 425-623)

| Card | Fake Value | Real Field | Adapter Status |
|------|-----------|------------|---------------|
| Total Portfolio Value | $2,847,291 | `summary.totalValue` | Wired but returning null |
| Daily P&L | $18,442 | `summary.dayChange` | TODO in adapter |
| Daily P&L % | +0.65% | `summary.dayChangePercent` | TODO in adapter |
| Risk Score | 7.2 | `summary.riskScore` | Wired |
| Sharpe Ratio | 1.34 | `summary.sharpeRatio` | TODO in adapter |
| Alpha Generation | 5.80 | `summary.alphaGeneration` | Not connected |
| ESG Score | 8.40 | — | Not connected |

**Adapter**: `connectors/src/adapters/PortfolioSummaryAdapter.ts` (lines 403-420) — 5 TODO comments on field mappings.

**Backend has the data**: `/api/performance` returns sharpe, max_drawdown, daily returns. `/api/risk-score` returns risk score. The adapter just isn't extracting them properly.

### 2. HoldingsView.tsx — Mock Holdings Array
**File**: `packages/ui/src/components/portfolio/HoldingsView.tsx` (lines 213-358)

Hardcoded `mockHoldings` with AAPL, MSFT, GOOGL, TSLA, VTI, BND. Used as fallback when real holdings unavailable.

**Backend has the data**: `/api/positions` returns real holdings. Container is wired via `usePortfolio()`. Issue is likely the fallback path triggering when it shouldn't.

### 3. RiskAnalysis.tsx — Mock Risk Factors, Stress Tests, Hedging
**File**: `packages/ui/src/components/portfolio/RiskAnalysis.tsx` (lines 264-440)

- **Risk Factors**: Concentration $127K, Correlation $89K, Volatility $156K, Liquidity $23K — all hardcoded
- **Stress Tests**: Market Crash -$569K, Tech Decline -$384K, Rate Spike -$142K, Geopolitical -$298K — all hardcoded
- **Hedging**: QQQ puts $12.5K, VIX calls $8.2K, Gold 5% $142K — all hardcoded

**Backend has partial data**: `/api/risk-analysis` returns VaR, stress tests. Hedging via `/api/portfolio-recommendations`. But the component uses its own inline mock objects instead of the adapter output.

### 4. PerformanceView.tsx — Mock Sector Attribution
**File**: `packages/ui/src/components/portfolio/PerformanceView.tsx` (lines 433-506)

`fallbackSectors` with Technology 42.3%, Healthcare 18.2%, etc. Used when `data?.attribution?.sectors` unavailable.

**Backend has the data**: `/api/performance` returns sector attribution. The real data IS flowing for some sections (we saw correct Financial Services 46.16% on the dashboard), but this fallback covers a different code path.

### 5. RiskMetrics.tsx — Mock VaR, Beta, Volatility, Drawdown
**File**: `packages/ui/src/components/portfolio/RiskMetrics.tsx` (lines 191-238)

`fallbackMetrics`: VaR -$42,891, Beta 1.23, Volatility 18.4%, Max Drawdown -8.7%. Plus `fallbackSummary` with 72% efficiency.

**Note**: The dashboard actually shows REAL risk metrics (VaR -$1,349, Beta 1.04, Vol 8.9%, Drawdown -55.9%) in the "Risk Assessment" section — so this fallback may only trigger in a different view.

### 6. FactorRiskModel.tsx — Mock Factor Exposures
**File**: `packages/ui/src/components/portfolio/FactorRiskModel.tsx` (lines 220-320)

`fallbackFactorExposures`: 8 Fama-French factors all hardcoded. Plus `fallbackRiskAttribution` with mock systematic/idiosyncratic split.

**Backend has the data**: `/api/factor-analysis` returns real factor exposures. Container is wired.

### 7. ScenarioAnalysis.tsx — Mock Pricing, Volatility, Monte Carlo
**File**: `packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`

- Line 515: `Math.random() * 200 + 50` for new position pricing
- Line 516: Hardcoded 2.5% weight for new positions
- Lines 897-908: Mock market caps for rebalancing
- Lines 918-922: `Math.random() * 0.3 + 0.1` for volatility
- Lines 562-567: Placeholder Monte Carlo simulation
- Lines 654-700: Hardcoded optimization suggestions

---

## MEDIUM — Adapter Gaps & Template Wiring

### 8. PortfolioSummaryAdapter.ts — 5 TODO Fields
**File**: `connectors/src/adapters/PortfolioSummaryAdapter.ts` (lines 403-420)

Fields with TODO: `dayChange`, `dayChangePercent`, `ytdReturn`, `sharpeRatio`, `maxDrawdown`. All currently default to 0.

**Fix**: Map these from the performance API response that's already being fetched.

### 9. PerformanceAdapter.ts — Benchmark Analysis
**File**: `connectors/src/adapters/PerformanceAdapter.ts` (line 986)

TODO: "Request benchmark analysis implementation in backend performance endpoint"

### 10. ScenarioAnalysisContainer.tsx — Hardcoded Templates
**File**: `packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` (line 258)

TODO: "Add dynamic scenario templates to WhatIfAnalysisAdapter"

### 11. StrategyBuilderContainer.tsx — Hardcoded Templates
**File**: `packages/ui/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx` (line 206)

TODO: "Add dynamic strategy templates to OptimizationAdapter"

### 12. StrategyBuilder.tsx — Hardcoded Metric Defaults
**File**: `packages/ui/src/components/portfolio/StrategyBuilder.tsx` (lines 396-399)

Defaults: 12% return, 16% volatility, 1.0 Sharpe, -15% drawdown when real data unavailable.

### 13. StockLookup.tsx — Mock Stock Data
**File**: `packages/ui/src/components/portfolio/StockLookup.tsx` (line 291)

Hardcoded `mockStocks` object used when no real stock selected.

---

## LOW — Recovery/Demo Data (Intentional)

### 14. Recovery Dashboard
`packages/ui/src/components/dashboard/shared/recovery/risk-analysis-dashboard.tsx` — intentional fallback

### 15. Chart Examples
`packages/ui/src/components/dashboard/shared/charts/examples/ChartExamples.tsx` — demo/docs

### 16. RiskAnalysisAdapter.ts — Leverage Field
Line 59: TODO for leverage field not yet in backend.

---

## What the Backend Already Provides

Most of the data exists — the issue is adapter extraction, not missing endpoints:

| Backend Endpoint | Available Data | Frontend Gap |
|-----------------|---------------|-------------|
| `/api/performance` | Sharpe, max drawdown, daily returns, sector attribution, YTD return | PortfolioSummaryAdapter TODOs, PerformanceView fallback sectors |
| `/api/risk-analysis` | VaR, beta, volatility, stress tests, factor exposures | RiskAnalysis inline mocks, RiskMetrics fallbacks |
| `/api/risk-score` | Composite risk score (0-100) | Working but totalValue null |
| `/api/portfolio-recommendations` | Hedging strategies | RiskAnalysis inline hedging mocks |
| `/api/factor-analysis` | Factor exposures, risk attribution | FactorRiskModel fallbacks |
| `/api/positions` | Real holdings with prices | HoldingsView mockHoldings |

---

## Proposed Fix Priority

**Wave 1 — Dashboard cards (highest visibility)**
Fix PortfolioSummaryAdapter to properly extract: totalValue, dayChange, sharpeRatio, maxDrawdown, ytdReturn from performance/risk APIs. Remove or guard the $2.8M fallback.

**Wave 2 — Remove inline mock datasets**
Replace the 5 inline mock objects (holdings, risk factors, stress tests, sectors, factor exposures) with proper "no data" / loading states or wire to existing adapters.

**Wave 3 — Scenario/Strategy templates**
Wire scenario templates and strategy templates from backend configuration instead of hardcoded arrays.

**Wave 4 — Real-time pricing & Monte Carlo**
These require new backend capabilities (live stock pricing API, Monte Carlo engine).
