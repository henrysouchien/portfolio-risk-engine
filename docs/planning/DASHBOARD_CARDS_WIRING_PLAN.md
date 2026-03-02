# Wave 1: Fix Dashboard Cards — Real Data Instead of Fake Numbers

**Date**: 2026-03-02
**Status**: PLANNING (rev 4 — complete, includes sparkline trends)

## Context

The PortfolioOverview dashboard cards show hardcoded fake values ($2,847,291 portfolio value, $18,442 daily P&L, 1.34 Sharpe, etc.) because the data pipeline has two breaks:

1. **`usePortfolioSummary()` doesn't pass performance data to the adapter** — line 345 calls `portfolioSummaryAdapter.transform(riskAnalysis, riskScore, holdings)` with only 3 args, omitting the 4th `performance` parameter. The adapter's extraction code (lines 328-355) never runs.

2. **PortfolioOverview uses falsy `||` fallbacks** — `summary?.totalValue || 2847291` means if totalValue is 0, it shows the fake number. Same pattern on all 6 cards.

The backend already returns all needed data. The individual hooks (`usePerformance`, `useRiskAnalysis`, `useRiskScore`) work fine — the dashboard sections below the cards show real data.

Full audit: `docs/planning/FRONTEND_MOCK_DATA_AUDIT.md`

---

## PerformanceAdapter Output Shape (reference)

The transformed data from `PerformanceAdapter.transform()` has this structure:

```typescript
{
  returns: { totalReturn, annualizedReturn, bestMonth, worstMonth, winRate },  // all * 100
  risk: { volatility, maxDrawdown, downsideDeviation, trackingError },         // all * 100
  performanceSummary: {
    periods: { "1D": {...}, "1W": {...}, "1M": {...}, "1Y": {...} },  // NOT "YTD"
    riskMetrics: { sharpeRatio, informationRatio, sortino, maxDrawdown, calmar, beta, alpha, trackingError },
    sectors: [...],
    security: [...]
  },
  performanceTimeSeries: [{ date, portfolioValue, benchmarkValue, cumulativeReturn }],
  timeline: [...],  // alias for performanceTimeSeries
  benchmark: { ... },
  monthly: { ... }
}
```

Key field paths for extraction:
- **Sharpe**: `performanceSummary.riskMetrics.sharpeRatio`
- **Max Drawdown**: `risk.maxDrawdown` or `performanceSummary.riskMetrics.maxDrawdown`
- **Total Return**: `returns.totalReturn`
- **Day change**: `performanceTimeSeries[-1].portfolioValue - performanceTimeSeries[-2].portfolioValue`

---

## Implementation Plan

### Step 1: Pass performance data to PortfolioSummaryAdapter

**File**: `packages/connectors/src/features/portfolio/hooks/usePortfolioSummary.ts`

Line 345 — add `performanceQuery.data` as 4th argument:

```typescript
// Before (line 345-348):
const result = portfolioSummaryAdapter.transform(
  riskAnalysisQuery.data,
  riskScoreQuery.data,
  portfolioForAdapter
);

// After:
const result = portfolioSummaryAdapter.transform(
  riskAnalysisQuery.data,
  riskScoreQuery.data,
  portfolioForAdapter,
  performanceQuery.data   // Pass performance data for summary enrichment
);
```

Also add `performanceQuery.data` and `performanceQuery.dataUpdatedAt` to the `useMemo` dependency array (line 352-361).

### Step 1b: Fix adapter cache key to include performance

**File**: `packages/connectors/src/adapters/PortfolioSummaryAdapter.ts`

The `generateCacheKey()` method (line 454) only includes riskAnalysis, riskScore, and holdings. If performance data changes but those 3 don't, the adapter returns stale cached results.

Fix: Add performance to cache key generation. Pass `performance` to `generateCacheKey()` and include `sharpeRatio` or similar in the content hash. Alternatively, pass `performance` through to `this.unifiedCache.get()` call on line 278-283 so it bypasses cache when performance arg changes.

Simplest fix: add `performance` parameter to `generateCacheKey()` and include a performance fingerprint in the content object.

### Step 2: Fix PortfolioSummaryAdapter field extraction

**File**: `packages/connectors/src/adapters/PortfolioSummaryAdapter.ts`

The adapter's performance extraction (lines 328-355) uses field names that don't match the PerformanceAdapter-transformed output. The transformed data nests Sharpe under `performanceSummary.riskMetrics.sharpeRatio`, not top-level `riskMetrics.sharpeRatio`. Periods use `1D/1W/1M/1Y`, not `YTD`.

Replace lines 328-355 with extraction that matches the **actual** PerformanceAdapter output:

```typescript
try {
  const performanceRecord = this.asRecord(performance);

  // --- Sharpe ratio ---
  // Transformed: performanceSummary.riskMetrics.sharpeRatio
  const perfSummary = this.asRecord(performanceRecord.performanceSummary);
  const perfRiskMetrics = this.asRecord(perfSummary.riskMetrics);
  derivedSharpe = this.toNumber(perfRiskMetrics.sharpeRatio, 0);

  // --- Max drawdown ---
  // Transformed: risk.maxDrawdown (already * 100 by PerformanceAdapter)
  // Also at: performanceSummary.riskMetrics.maxDrawdown
  const riskBlock = this.asRecord(performanceRecord.risk);
  derivedMaxDrawdown = this.toNumber(
    riskBlock.maxDrawdown ?? perfRiskMetrics.maxDrawdown, 0
  );

  // --- Total/YTD return ---
  // Transformed: returns.totalReturn (already * 100)
  // No "YTD" period key — use totalReturn as proxy
  const returns = this.asRecord(performanceRecord.returns);
  derivedYtdReturn = this.toNumber(returns.totalReturn, 0);

  // --- Day change (from time series) ---
  // Transformed: performanceTimeSeries or timeline
  const tsCandidate = performanceRecord.performanceTimeSeries || performanceRecord.timeline;
  const ts = Array.isArray(tsCandidate) ? tsCandidate : [];
  if (ts.length >= 2) {
    const last = this.asRecord(ts[ts.length - 1]);
    const prev = this.asRecord(ts[ts.length - 2]);
    const lastVal = this.toNullableNumber(last.portfolioValue);
    const prevVal = this.toNullableNumber(prev.portfolioValue);
    if (typeof lastVal === 'number' && typeof prevVal === 'number' && prevVal !== 0) {
      derivedDayChange = lastVal - prevVal;
      derivedDayChangePct = (derivedDayChange / prevVal) * 100;
    }
  }
} catch {
  // Leave derived values at 0 if any parsing fails
}
```

Remove the TODO comments — these fields will be wired.

### Step 3: Fix PortfolioOverview fallback pattern

**File**: `packages/ui/src/components/portfolio/PortfolioOverview.tsx`

Two sub-problems:

**3a. Fix `||` → `??` for rawValue fields.** The `||` operator treats 0 as falsy, so `summary?.totalValue || 2847291` shows the fake number when real value is 0. Change all to `??`:

```typescript
// Before:
rawValue: summary?.totalValue || 2847291,
// After:
rawValue: summary?.totalValue ?? 0,
```

**3b. Fix the string fallbacks.** The ternary `summary ? formatCurrency(...) : "$2,847,291"` shows fake strings when summary is null. Since the container already shows a loading spinner while data loads (line 149), by the time PortfolioOverview renders, `summary` should be non-null. But as a safety net, use `"—"` instead of fake values:

Apply to ALL 6 metric cards — fix `value`, `change`, `changeValue`, `lastUpdate`, and all other string fallbacks. Complete list of hardcoded strings to replace with `"—"` or `""`:

**Total Portfolio Value card:**
- `"$2,847,291"` → `"—"` (value)
- `"+12.8%"` → `"—"` (change)
- `"+$326,491"` → `"—"` (changeValue)

**Daily P&L card:**
- `"+$18,442"` → `"—"` (value)
- `"+0.65%"` → `"—"` (change)
- `"Strong performance"` → `""` (changeValue)

**Risk Score card:**
- `"7.2"` → `"—"` (value)
- `"Medium Risk"` → `""` (change)
- `"+0.3 this week"` → `""` (changeValue)
- `"5 mins ago"` → `""` (lastUpdate)

**Sharpe Ratio card:**
- `"1.34"` → `"—"` (value)
- `"Poor"` / rating string → `""` (change)
- `"+0.12 improvement"` → `""` (changeValue)
- `"1 min ago"` → `""` (lastUpdate)

**Alpha Generation card** (entirely hardcoded — no summary field exists):
- `"5.80"` → `"—"` (value)
- All change/changeValue/lastUpdate strings → `""`

**ESG Score card** (entirely hardcoded — no summary field exists):
- `"8.40"` → `"—"` (value)
- All change/changeValue/lastUpdate strings → `""`

Also fix `"Live"` lastUpdate fallbacks on the first two cards (lines ~437, ~480).

**Sparkline `trend` arrays** (lines ~435, ~478, ~515, ~547, ~574, ~605): Each card has a hardcoded array of ~15 numbers used for mini sparkline charts. Replace with `[]` — the sparkline component should handle empty arrays gracefully (hide or show flat line).

**3c. Note on animated values.** The component uses `animatedValue` seeded from `rawValue` (line ~780). With `rawValue` now `?? 0` instead of `|| fakeNumber`, the animated counter will show 0 instead of a fake number — which is correct behavior while data loads (container shows spinner anyway) or when a metric is genuinely 0.

**3d. Remove hardcoded mock content from card extra fields.** Each metric card has inline mock content for AI insights, projections, correlations, etc. Replace with empty/default values. Respect existing TypeScript types — use `undefined` for optional fields, `[]` for arrays, `""` for strings:
- `aiInsight`: hardcoded strings → `""`
- `aiConfidence`: hardcoded numbers → `0`
- `futureProjection`: hardcoded objects → `undefined` (field is optional)
- `correlations`: hardcoded arrays → `[]`
- `riskFactors`: hardcoded arrays → `[]`
- `marketSentiment`: hardcoded objects → `undefined` (field is optional)
- `technicalSignals`: hardcoded arrays → `[]`

### Step 4: Remove mock Market Intelligence, Smart Alerts, AI Recommendations

**File**: `packages/ui/src/components/portfolio/PortfolioOverview.tsx`

- **`marketEvents`** (lines 626-664): Hardcoded NVIDIA earnings, Fed rates, etc. Replace with empty array and hide the section when empty.
- **`generateSmartAlerts()`** (lines 729-761): Hardcoded alerts about benchmark outperformance, concentration risk, healthcare momentum. Replace with empty array and hide section when empty.
- **`generateAIRecommendations()`** (lines 672-727): Hardcoded AI insights. Replace with empty array and hide section when empty.

These sections should show nothing rather than fake content. They can be wired to real data sources in a future wave.

---

## Files Modified

| File | Change |
|------|--------|
| `packages/connectors/src/features/portfolio/hooks/usePortfolioSummary.ts` | Pass `performanceQuery.data` to adapter, update deps |
| `packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` | Fix field extraction for transformed performance data |
| `packages/ui/src/components/portfolio/PortfolioOverview.tsx` | Remove fake fallbacks, empty mock sections |

---

## What This Does NOT Change

- No backend changes needed — all data already available
- PerformanceAdapter, RiskAnalysisAdapter, RiskScoreAdapter unchanged
- Other views (Holdings, Performance, Risk, Factor) unchanged
- Wave 2+ mock data (HoldingsView fallbacks, RiskAnalysis mock factors, FactorRiskModel fallbacks) untouched

---

## Verification

1. **Dashboard loads with real numbers**: Portfolio value should match sum of holdings (~$145K based on asset allocation), not $2.8M
2. **Sharpe ratio**: Should match what the Performance section shows (1.836 was visible)
3. **Risk Score**: Should show real score from risk-score API (92.80 was visible in the Risk Score card lower on page)
4. **No fake content**: Market Intelligence, Smart Alerts, AI Insights sections should be hidden (empty)
5. **Zero values display correctly**: If daily P&L is truly $0, show "$0" not "—"
6. **Loading state**: While data fetches, cards should show loading spinner (container already handles this)
