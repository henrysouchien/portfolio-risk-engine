# Metric Cards + Strip Reshuffling

## Context
The Overview metric cards and performance strip have metric overlap (Sharpe, Alpha appear in both) and the card selection doesn't tell the clearest investor story.

**New cards:** Value, YTD Return, Max Drawdown | Risk Score, Sharpe, Alpha
**New strip:** Annualized Return, Volatility, Concentration, Beta (vs benchmark)
Zero duplication.

## Codex Findings (all addressed)
1. **Fixed:** MaxDrawdown is already in percent-points (converted from decimal by PerformanceAdapter — see line 64 comment "✅ Converted from decimal to percentage"). Thresholds `> -5 / > -10 / > -20` are correct. No `sign: true` — use `formatPercent(value, { decimals: 1 })` which naturally shows negative sign
2. **Fixed:** Missing data — show `"—"` when value is null/undefined. Add explicit `summary?.maxDrawdown != null` checks. Don't coerce to 0
3. **Fixed:** Beta label includes benchmark — "Beta (vs SPY)" using `summary.benchmarkTicker` from portfolio summary
4. **Fixed:** No redundant hook — pass `concentrationScore` and `benchmarkTicker` as props to the strip from PortfolioOverviewContainer (which already has the summary data)
5. **Fixed:** Concentration label — use "Diversification" as label with color coding (green ≥70, amber ≥40, red <40). The color gives interpretive context without text
6. **Fixed:** MaxDrawdown edge cases — no `sign: true`. Value of 0 shows "0.0%" (no drawdown = good, gets "Minimal" badge). Null/undefined shows "—"
7. **Fixed:** Verification expanded

## Plan

### Change 1: Replace Concentration card with Max Drawdown + reorder

**File:** `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts`

Remove Concentration metric (index 5). Add Max Drawdown. Reorder to narrative flow:

**New order:**
1. Total Portfolio Value (unchanged)
2. YTD Return (unchanged)
3. **Max Drawdown** (NEW)
4. Risk Score (was index 2)
5. Sharpe Ratio (was index 3)
6. Alpha Generation (was index 4)

**Max Drawdown definition:**
```typescript
{
  title: "Max Drawdown",
  value: summary?.maxDrawdown != null ? formatPercent(summary.maxDrawdown, { decimals: 1 }) : "—",
  rawValue: summary?.maxDrawdown ?? 0,
  change: summary?.maxDrawdown != null
    ? (summary.maxDrawdown > -5 ? "Minimal"
      : summary.maxDrawdown > -10 ? "Moderate"
      : summary.maxDrawdown > -20 ? "Significant"
      : "Severe")
    : "",
  changeValue: "",
  changeType: summary?.maxDrawdown != null
    ? (summary.maxDrawdown > -5 ? "positive"
      : summary.maxDrawdown > -10 ? "warning"
      : "negative")
    : "neutral",
  icon: TrendingDown,
  description: "worst peak-to-trough decline",
  priority: "high",
  aiInsight: metricInsights["maxDrawdown"]?.aiInsight ?? "",
  aiConfidence: metricInsights["maxDrawdown"]?.aiConfidence ?? 0,
  marketContext: metricInsights["maxDrawdown"]?.marketContext ?? "",
  alertLevel: "none"
}
```

Add `TrendingDown` to the lucide-react import.

### Change 2: Update Performance Strip — replace Alpha+Sharpe with Concentration+Beta

**File:** `frontend/packages/ui/src/components/dashboard/cards/DashboardPerformanceStrip.tsx`

**Add props** for data the strip can't fetch itself:
```typescript
interface DashboardPerformanceStripProps {
  concentrationScore?: number | null;
  benchmarkTicker?: string;
}
```

**Remove** Sharpe and Alpha StatPairs. **Add** Concentration and Beta:

```typescript
const metrics = useMemo(() => ({
  annualizedReturn: performanceData?.returns?.annualizedReturn,
  volatility: performanceData?.risk?.volatility,
  concentration: concentrationScore,
  beta: performanceData?.performanceSummary?.riskMetrics?.beta,
}), [performanceData, concentrationScore]);
```

**StatPair entries:**
- Annualized Return: stays as-is
- Volatility: stays as-is
- Diversification: label "Diversification", value `${score}/100` or `"—"` if null, color based on threshold
- Beta: label `Beta (vs ${benchmarkTicker || 'SPY'})`, value formatted to 2 decimals or `"—"` if null, color "neutral"

Grid stays `grid-cols-2 md:grid-cols-4` (still 4 metrics).

### Change 3: Pass props to strip from container

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

The container already has `portfolioOverviewData` with `concentrationScore` and `benchmarkTicker`. Update the `renderAfterMetrics` slot rendering — but wait, the slot is passed by ModernDashboardApp, not the container.

**Better approach:** The strip is passed as `renderAfterMetrics` from ModernDashboardApp. ModernDashboardApp doesn't have the summary data directly. Two options:
- A) Strip calls `usePortfolioSummary()` itself (cached, no extra load)
- B) Container clones the slot and injects props

Option A is simpler and the hook is cached. Use it:
```typescript
const { data: summaryData } = usePortfolioSummary();
```
This IS a second `usePortfolioSummary()` call but it returns from TanStack Query cache — zero network requests. The container's call already populated the cache.

**Updated strip:**
```typescript
export default function DashboardPerformanceStrip() {
  const { data: perfData, loading } = usePerformance();
  const { data: summaryData, isLoading: summaryLoading } = usePortfolioSummary();
  const setActiveView = useUIStore((s) => s.setActiveView);
  const performanceData = perfData as PerformanceData | undefined;
  const isLoading = loading || summaryLoading;
  const benchmarkTicker = (summaryData?.summary as any)?.benchmarkTicker ?? 'SPY';
  const concentrationScore = summaryData?.summary?.concentrationScore;
  // ... rest
}
```

### Change 4: No changes to PortfolioOverviewContainer or ModernDashboardApp

The container passes `renderAfterMetrics={<DashboardPerformanceStrip />}` — no props needed since the strip fetches from cache.

## Files Modified
1. `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` — replace Concentration with Max Drawdown, reorder array, add TrendingDown import
2. `frontend/packages/ui/src/components/dashboard/cards/DashboardPerformanceStrip.tsx` — replace Alpha+Sharpe with Diversification+Beta, add `usePortfolioSummary()` for concentration+benchmark

## Verification
1. `cd frontend && npx tsc --noEmit` — no type errors
2. Visual: Row 1 cards show Value | YTD Return | Max Drawdown
3. Visual: Row 2 cards show Risk Score | Sharpe | Alpha
4. Max Drawdown shows negative percentage with severity badge (Minimal/Moderate/Significant/Severe)
5. Max Drawdown shows "—" when data unavailable (not "0.0%")
6. Strip shows: Annualized Return | Volatility | Diversification | Beta (vs SPY)
7. Diversification shows score/100 with green/amber/red color
8. Beta shows benchmark name in label
9. No metric appears in both cards and strip
10. Strip still clickable → navigates to Performance view
