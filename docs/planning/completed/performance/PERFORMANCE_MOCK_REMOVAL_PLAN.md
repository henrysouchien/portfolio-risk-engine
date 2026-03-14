# Performance View — Remove Mock Fallbacks (Wave 3f)

**Date**: 2026-03-03
**Status**: COMPLETE — commit `52c6d95a`
**Wave**: 3f (from `completed/FRONTEND_PHASE2_WORKING_DOC.md`)

## Context

The Performance view is mostly wired to real data (period returns, risk metrics, time series, attribution). However, it still contains **hardcoded fallback arrays** that display fake data when real data is empty/missing. After B-013 (real insights from metrics, commit `14f795bd`) and B-014 (real analyst data, commit `3f14a56b`), the remaining mock data is:

1. **`fallbackSectors`** (lines 456-529): 6 fake sectors with fake insights/momentum/recommendations
2. **`fallbackTopContributors`** (lines 555-606): 5 fake stocks (XOM, UNH, COST, PG, JNJ)
3. **`fallbackTopDetractors`** (lines 608-639): 3 fake stocks (DIS, NKE, PFE)
4. **`monthlyReturns`** (lines 815-828): 12 hardcoded months with fake data
5. **`fallbackMetrics`** (lines 657-668): Hardcoded alpha/beta/Sharpe/volatility

Real data IS flowing through the pipeline:
- `sector_attribution` → `PerformanceAdapter` → `data.attribution.sectors` (real from FMP profile sector lookup)
- `security_attribution` → `PerformanceAdapter` → `data.attribution.security` (real per-ticker returns + analyst data from B-014)
- `monthly_returns` → `PerformanceAdapter.transformTimeSeries()` → `performanceTimeSeries` (cumulative return series)
- Risk metrics (alpha, beta, Sharpe, volatility, maxDrawdown) all real from backend

The fallbacks need to be removed so fake data stops displaying. **Single file change** — no backend or adapter changes needed.

---

## Data Flow (already working)

```
Backend /api/performance
  → usePerformance() hook (TanStack Query)
    → PerformanceAdapter.transform()
      → { performanceTimeSeries, performanceSummary.attribution.{sectors,security,factors}, risk.{volatility,maxDrawdown}, ... }
        → PerformanceViewContainer (maps to PerformanceView props)
          → PerformanceView component (currently uses fallbacks when arrays empty)
```

The container (`PerformanceViewContainer.tsx` lines 382-396) already:
- Sorts security attribution by `|contribution|`
- Splits into `contributorItems` (positive contribution) and `detractorItems` (negative)
- Passes as `topContributors` / `topDetractors` props

**Important**: `PerformanceViewContainer.tsx` line 339 maps `portfolioCumReturn ?? portfolioReturn` into `portfolioReturn`. This means `data.timeSeries[].portfolioReturn` contains **cumulative** returns, not per-month returns. The adapter's `transformTimeSeries()` (line 728-748) computes cumulative values from the raw `monthly_returns` dict. The raw per-month values are not directly available in the `timeSeries` prop.

---

## Changes to `PerformanceView.tsx`

### 1. Delete fallback arrays

Remove entirely:
- `fallbackSectors` array (lines 456-529) — 6 fake sectors
- `fallbackTopContributors` array (lines 555-606) — 5 fake stocks
- `fallbackTopDetractors` array (lines 608-639) — 3 fake stocks
- `fallbackMetrics` object (lines 657-668) — fake risk numbers
- `monthlyReturns` hardcoded array (lines 815-828) — 12 fake months

### 2. Update references to use empty defaults

**Sectors** (line 531-544):
```typescript
// Before:
const mappedSectors = Array.isArray(data?.attribution?.sectors) && data.attribution.sectors.length > 0
  ? data.attribution.sectors.map(...)
  : fallbackSectors

// After:
const mappedSectors = Array.isArray(data?.attribution?.sectors) && data.attribution.sectors.length > 0
  ? data.attribution.sectors.map((sector) => ({
      name: sector.name,
      allocation: sector.allocation,
      return: sector.return,
      contribution: sector.contribution,
      insight: "",
      trend: sector.return > 0 ? "bullish" : sector.return < 0 ? "bearish" : "neutral",
      riskLevel: sector.allocation > 25 ? "high" : sector.allocation > 10 ? "medium" : "low",
      momentum: 0,
      volatility: 0,
      recommendation: "",
    }))
  : []
```

**Contributors/Detractors** (lines 811-812):
```typescript
// Before:
topContributors: topContributors ?? fallbackTopContributors,
topDetractors: topDetractors ?? fallbackTopDetractors,

// After:
topContributors: topContributors ?? [],
topDetractors: topDetractors ?? [],
```

**Metrics** (lines 670-676) — fall back to `0` instead of fake numbers:
```typescript
const periodReturn = data?.periods?.[selectedPeriod as keyof typeof data.periods]?.return ?? 0
const benchmarkReturn = data?.periods?.[selectedPeriod as keyof typeof data.periods]?.benchmark ?? 0
const alpha = data?.periods?.[selectedPeriod as keyof typeof data.periods]?.alpha ?? 0
const beta = data?.beta ?? 0
const sharpeRatio = data?.sharpeRatio ?? 0
const maxDrawdown = data?.maxDrawdown ?? 0
const volatility = data?.volatility ?? 0
```

### 3. Refactor `buildInsights()` — remove `fallbackMetrics` dependency

**Problem (Codex Finding #1, High)**: `buildInsights()` at lines 699-704 compares metrics against `fallbackMetrics` values to detect fallback state:
```typescript
const hasFallbackAlpha = alpha === fallbackMetrics.alpha           // === 5.08
const hasFallbackSharpe = sharpeRatio === fallbackMetrics.sharpeRatio  // === 1.67
const hasFallbackRiskMetric = (
  volatility === fallbackMetrics.volatility ||   // === 16.8
  maxDrawdown === fallbackMetrics.maxDrawdown ||  // === -12.4
  beta === fallbackMetrics.beta                   // === 1.12
)
```

Deleting `fallbackMetrics` without updating these references would cause a TypeScript compile error.

**Fix**: With the new `?? 0` defaults, the "fallback" state is when metrics equal `0` (meaning no real data loaded yet). Replace the `hasFallback*` checks:

```typescript
// Before: compared against magic fallback numbers
const hasFallbackAlpha = alpha === fallbackMetrics.alpha
const hasFallbackSharpe = sharpeRatio === fallbackMetrics.sharpeRatio
const hasFallbackRiskMetric = (...)

// After: "no data" means metrics are at their 0 defaults
const hasNoAlpha = alpha === 0
const hasNoSharpe = sharpeRatio === 0
const hasNoRiskMetric = (volatility === 0 && maxDrawdown === 0 && beta === 0)
```

Then update the text branching:
- `hasFallbackAlpha` → `hasNoAlpha`: When alpha is 0 (no data), show generic text without specific numbers
- `hasFallbackSharpe` → `hasNoSharpe`: When Sharpe is 0 (no data), show generic text
- `hasFallbackRiskMetric` → `hasNoRiskMetric`: When all risk metrics are 0 (no data), show generic text

Note the logic change for `hasNoRiskMetric`: use `&&` (all zero = no data) instead of `||` (any match = fallback). The old `||` was checking if any single metric happened to match a magic number. The new check is: if ALL risk metrics are at their zero default, we have no real data.

The text paths remain the same — the "hasFallback" branches produced generic text without specific numbers, and the non-fallback branches include formatted metric values. This is the correct behavior: show generic text when no data, show specific numbers when real data is available.

### 4. Wire real monthly returns — compute per-month deltas from cumulative

**Problem (Codex Finding #2, High)**: `data.timeSeries[].portfolioReturn` contains **cumulative** returns (from `portfolioCumReturn`), not per-month returns. The container maps this at line 339: `portfolioReturn: p.portfolioCumReturn ?? p.portfolioReturn ?? 0`. Directly using these values in the monthly performance cards would show cumulative numbers (e.g., 0.5%, 1.2%, 3.8%) instead of monthly deltas (e.g., 0.5%, 0.7%, 2.6%).

**Fix**: Compute month-over-month deltas from the cumulative series:

```typescript
monthlyReturns: Array.isArray(data?.timeSeries) && data.timeSeries.length > 0
  ? data.timeSeries.map((point, index) => {
      // Compute per-month return from cumulative series
      // cumReturn is in percentage points (e.g., 5.2 means 5.2%)
      const cumReturn = point.portfolioReturn ?? 0
      const prevCumReturn = index > 0 ? (data.timeSeries[index - 1].portfolioReturn ?? 0) : 0
      // Convert from cumulative % to per-month %:
      // monthReturn = ((1 + cum/100) / (1 + prevCum/100) - 1) * 100
      const monthReturn = prevCumReturn === 0 && index === 0
        ? cumReturn  // First month: cumulative IS the monthly return
        : ((1 + cumReturn / 100) / (1 + prevCumReturn / 100) - 1) * 100

      const cumBenchmark = point.benchmarkReturn ?? 0
      const prevCumBenchmark = index > 0 ? (data.timeSeries[index - 1].benchmarkReturn ?? 0) : 0
      const monthBenchmark = prevCumBenchmark === 0 && index === 0
        ? cumBenchmark
        : ((1 + cumBenchmark / 100) / (1 + prevCumBenchmark / 100) - 1) * 100

      // Parse month label from date string directly (avoid timezone shift — Finding #3)
      const [year, monthNum] = point.date.split('-')
      const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
      const monthLabel = monthNames[parseInt(monthNum, 10) - 1] || point.date

      return {
        month: monthLabel,
        portfolio: Math.round(monthReturn * 100) / 100,
        benchmark: Math.round(monthBenchmark * 100) / 100,
        volatility: 0,
        marketEvent: "",
      }
    })
  : []
```

**Date parsing (Codex Finding #3, Medium)**: Uses string splitting (`point.date.split('-')`) instead of `new Date(point.date)` to avoid timezone-dependent month shifts. The adapter produces dates in `YYYY-MM-DD` format (line 738: `month + '-01'`), so splitting on `-` is reliable.

**React keys (Codex Finding #4, Medium)**: The monthly cards currently use `key={month.month}` which produces duplicate short month labels across years (e.g., two "Jan" entries). Fix: use the original date string as key, or the array index. Since `data.timeSeries` entries have unique dates, we can store the date and use it. Alternative: use index as key since the array order is stable. We'll use the date string approach — add a `date` field to the monthly return object for use as React key:

```typescript
// In the map above, also include:
return {
  date: point.date,  // For React key — unique per entry
  month: monthLabel,
  ...
}

// In JSX, use:
key={month.date}  // instead of key={month.month}
```

### 5. Guard empty states in JSX

Add empty-state guards where sectors/contributors/detractors/monthly are rendered. When arrays are empty, conditionally hide the section or show a brief "No data available" message. This is a UX improvement — empty arrays don't break rendering (JSX `.map([])` produces nothing), but hiding empty containers avoids blank space and confusing empty section headers.

- **Sector Performance Attribution** section: Conditionally render only if `performanceData.sectors.length > 0`
- **Top Contributors** section: Show "No attribution data available" when empty, or hide entirely
- **Top Detractors** section: Same
- **Monthly Performance** section: Guard against empty array

### 6. Remove "AI Enhanced" badge from Sector section

The sector header says "AI Enhanced" — change to "Portfolio Data" or remove entirely (there's no AI involved, just real FMP sector attribution data).

---

## Key Design Decisions

1. **No fake data ever**: When real data is unavailable, show empty state rather than misleading fake numbers. The `LoadingSpinner` from the container already covers the initial load.

2. **`buildInsights()` refactored, not unchanged**: With `fallbackMetrics` deleted, the `hasFallback*` checks must be updated to detect "no data" via `=== 0` comparison instead. The text branching logic stays the same — generic text when no data, specific formatted values when real data is present.

3. **Monthly returns computed as deltas from cumulative**: The adapter's `transformTimeSeries()` produces cumulative returns. Since the raw `monthly_returns` dict is not available in the component (only cumulative `timeSeries` reaches the view), we compute per-month returns by dividing consecutive cumulative factors: `monthReturn = ((1 + cum%) / (1 + prevCum%) - 1) * 100`. This correctly reverses the cumulative compounding.

4. **UTC-safe date parsing**: String splitting on the adapter-produced `YYYY-MM-DD` format avoids `new Date()` timezone issues where a UTC midnight date can shift backward a day in US timezones.

5. **Unique React keys**: Monthly cards use `point.date` (e.g., `"2025-06-01"`) as key instead of short month label (e.g., `"Jun"`), avoiding duplicates across years.

6. **Empty arrays are UX cleanup, not crash prevention**: JSX `.map([])` produces no output and doesn't throw. The empty-state guards prevent rendering empty section headers and containers, which is a UX improvement.

7. **Benchmark selector fallback (out of scope)**: The benchmark selector dropdown still has a hardcoded fallback list (SPY/QQQ/VTI/CUSTOM). This is separate functionality and not addressed in this wave.

---

## Critical Files

| File | Purpose |
|------|---------|
| `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` | **MODIFY** — only file changed. Remove 5 fallback arrays, refactor buildInsights, wire monthly returns, guard empty states |
| `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` | Reference — maps adapter output to PerformanceView props. Line 339: `portfolioCumReturn ?? portfolioReturn` = cumulative |
| `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` | Reference — `transformTimeSeries()` produces cumulative returns from `monthly_returns` dict |

---

## Verification

1. `pnpm typecheck` — no new TypeScript errors (especially: no references to deleted `fallbackMetrics`)
2. `pnpm build` — Vite build succeeds
3. Visual check in Chrome:
   - Performance view shows real sector attribution (Financial Services, Real Estate, etc. from actual portfolio)
   - Top Contributors/Detractors show real portfolio securities (DSU, STWD, MSCI, etc.) with real analyst data
   - Monthly chart shows real per-month returns (not cumulative) from backend data
   - No fake XOM/UNH/COST/DIS/NKE/PFE stocks visible
   - Empty states render cleanly when data hasn't loaded (no empty section headers)
   - Insights section still works — shows generic text when metrics are 0, specific values when real data loaded
   - "AI Enhanced" badge removed/updated on sector section
   - React DevTools: no duplicate key warnings on monthly cards

---

## Codex Review — Round 1 Findings (all addressed above)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | **High** | `buildInsights()` references `fallbackMetrics` at lines 699-704 — deleting it causes TS compile error | Section 3: Refactor `hasFallback*` → `hasNo*` checks comparing against 0 |
| 2 | **High** | Monthly wiring uses cumulative returns (`portfolioCumReturn`) not per-month | Section 4: Compute per-month deltas from consecutive cumulative values |
| 3 | **Medium** | `new Date(point.date)` can shift month backward in US timezones | Section 4: Use `point.date.split('-')` string parsing instead |
| 4 | **Medium** | `key={month.month}` produces duplicate React keys across years | Section 4: Use `key={month.date}` with unique date string |
| 5 | **Low** | Benchmark selector fallback list still hardcoded | Out of scope — acknowledged in Key Design Decisions |
| 6 | **Low** | Empty-array maps don't break runtime — "prevent breakage" framing inaccurate | Section 5: Reframed as UX cleanup (hide empty section headers) |
