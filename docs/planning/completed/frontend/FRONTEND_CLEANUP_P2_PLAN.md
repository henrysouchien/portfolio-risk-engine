# Frontend Cleanup P2: Remove Hardcoded Mock Data

**Date:** 2026-03-04
**Status:** ✅ COMPLETE (2026-03-04, commit `62106f7b`)
**Source:** `completed/FRONTEND_CLEANUP_AUDIT.md` Priority 2 items

---

## Approach

For every item: replace hardcoded mock/fake data with either (a) real data from the adapter/hook, or (b) a clean empty state ("No data available" / "—"). Never show fabricated numbers as if they're real.

**Type strategy:** Do NOT widen the `Strategy` interface to `number | null`. Instead, use `NaN` for unknown metrics (the formatting helpers `formatNumber(NaN)` and `formatPercent(NaN)` already return "—" via `toFiniteValue`). This avoids breaking ~10 downstream call sites. For `strategyPreview` (local object, not Strategy type), use null with inline ternary guards.

---

## P2-1. RiskAnalysis: Full mock fallback arrays

**File:** `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` lines 278-416

**Problem:** `riskFactors`, `stressTests`, and `hedgingStrategies` all have hardcoded mock fallback arrays with fake dollar amounts ("$127K", "$569K", "25 contracts"). These render when `data?.riskFactors` etc. are empty/absent.

**Fix:** Replace mock fallback with empty array `[]`. The rendering code already maps over these arrays — an empty array produces no cards, which is the correct empty state.

```typescript
// Before:
const riskFactors = (data?.riskFactors && data.riskFactors.length > 0) ? data.riskFactors : [
  { id: "concentration", name: "Concentration Risk", level: "High", score: 8.5, impact: "$127K", ... },
  ...
]

// After:
const riskFactors = data?.riskFactors ?? []
const stressTests = data?.stressTests ?? []
const hedgingStrategies: HedgeStrategy[] = (data?.hedgingStrategies ?? []).map(hs => ({ ...hs }))
```

Also remove the stale comment block at lines 272-275 (`// DATA INTEGRATION & FALLBACK LOGIC // Hybrid data approach...`).

---

## P2-2. RiskAnalysis: Hardcoded prose summary

**File:** `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` lines 571-585

**Problem:** Static text: `"Your portfolio shows moderate resilience to market shocks. The highest risk comes from tech sector concentration."` — always renders regardless of actual portfolio.

**Fix:** Conditionally render the summary card only when stress tests exist, and replace hardcoded text with a data-driven count:

```typescript
{stressTests.length > 0 && (
  <Card className="border-emerald-200/60 bg-gradient-to-br from-emerald-50/50 to-green-50/30">
    <CardContent className="p-4">
      <div className="flex items-start space-x-3">
        <Target className="w-5 h-5 text-emerald-600 mt-0.5" />
        <div>
          <h4 className="font-semibold text-emerald-900 mb-1">Stress Test Summary</h4>
          <p className="text-sm text-emerald-800">
            {stressTests.length} scenarios analyzed across your portfolio.
          </p>
        </div>
      </div>
    </CardContent>
  </Card>
)}
```

---

## P2-3. StrategyBuilder: Hardcoded "AI Recommendations"

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` lines 864-892

**Problem:** Three static recommendation strings ("Consider adding technology exposure during earnings season", etc.) not connected to any real analysis.

**Fix:** Delete the entire AI Recommendations card (lines 864-892). Real AI recommendations live on Portfolio Overview via `useAIRecommendations()`.

---

## P2-4. StrategyBuilder: strategyPreview fallback with fake metrics

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` lines 373-378

**Problem:** `currentMetrics?.expectedReturn ?? 14.2` — shows fake 14.2% return, 19.8% vol, 1.24 Sharpe when no optimization has been run.

**Fix:** Fall back to `null` so the rendering shows "—". `strategyPreview` is a local object (not typed as `Strategy`), so null is safe here:

```typescript
const strategyPreview = {
  expectedReturn: currentMetrics?.expectedReturn ?? null,
  volatility: currentMetrics?.volatility ?? null,
  sharpeRatio: currentMetrics?.sharpeRatio ?? null,
  maxDrawdown: currentMetrics?.maxDrawdown ?? null,
}
```

Update the 4 rendering blocks (~lines 838-860) with inline null guards:

```typescript
// expectedReturn
{strategyPreview.expectedReturn != null ? formatPercent(strategyPreview.expectedReturn, { decimals: 1 }) : "—"}
// volatility
{strategyPreview.volatility != null ? formatPercent(strategyPreview.volatility, { decimals: 1 }) : "—"}
// sharpeRatio
{strategyPreview.sharpeRatio != null ? formatNumber(strategyPreview.sharpeRatio, { decimals: 2 }) : "—"}
// maxDrawdown
{strategyPreview.maxDrawdown != null ? formatPercent(strategyPreview.maxDrawdown, { decimals: 1 }) : "—"}
```

---

## P2-5. StrategyBuilder: Marketplace templates + placeholder show zeroed metrics

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`

**Problem:** Two sources of fake zero metrics:

1. `templatesAsStrategies` (lines 408-411): sets `expectedReturn: 0`, `volatility: 0`, `sharpeRatio: 0`, `maxDrawdown: 0`. Cards show `0.00` Sharpe, `+0.0%` YTD.
2. `prebuiltStrategies` placeholder (lines 357-360): same fake zeroes. This drives the Featured Strategy spotlight at line 943 and active strategy cards.

**Fix:** Use `NaN` instead of `0` for all unknown metrics. The `Strategy` type stays `number` (no widening needed). `formatNumber(NaN)` → "—" and `formatPercent(NaN)` → "—" via existing `toFiniteValue()` check. Also `performance.ytd: NaN` etc.

```typescript
// In templatesAsStrategies (lines 408-411):
expectedReturn: NaN,
volatility: NaN,
sharpeRatio: NaN,
maxDrawdown: NaN,

// In performance block (lines 414-418):
performance: {
  ytd: NaN,
  oneYear: NaN,
  threeYear: NaN,
  inception: NaN,
},

// In prebuiltStrategies placeholder (lines 357-363):
expectedReturn: NaN,
volatility: NaN,
sharpeRatio: NaN,
maxDrawdown: NaN,
// ... and performance:
performance: { ytd: NaN, oneYear: NaN, threeYear: NaN, inception: NaN },
```

**Downstream call sites that consume `Strategy` fields through `formatNumber`/`formatPercent` (lines 943, 948, 981, 987, 1062, 1067, 1071, 1075):** All already call `formatPercent(strategy.performance.ytd, ...)` or `formatNumber(strategy.sharpeRatio, ...)`. Since `NaN` is a valid `number`, these compile. `formatPercent(NaN)` returns "—". No type errors.

**Edge case: color conditional at line 980:**
```typescript
strategy.performance.ytd >= 0 ? 'text-emerald-600' : 'text-red-600'
```
`NaN >= 0` is `false`, so it defaults to red. Guard with:
```typescript
Number.isFinite(strategy.performance.ytd) && strategy.performance.ytd >= 0 ? 'text-emerald-600' : strategy.performance.ytd < 0 ? 'text-red-600' : 'text-neutral-600'
```

---

## P2-6. HoldingsView: "LIVE" badge always shown

**File:** `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx` lines 304, 357

**Problem:** `lastUpdate: 'Live'` hardcoded at two locations (initial useMemo and useEffect sync). Green pulsing "LIVE" dot appears for every position.

**Fix:** Change both to empty string:

```typescript
lastUpdate: '',  // No freshness metadata available yet
```

The LIVE badge rendering at line 766 (`holding.lastUpdate === "Live"`) already gates on the value — with `''` it won't render. No rendering changes needed.

---

## P2-7. PortfolioOverview: Sparklines — SKIPPED

**Reason:** Not showing fake data — just an empty UI element. `trend: []` produces no visual output (sparkline renderer returns null for arrays < 2 elements). Needs intraday data pipeline for real data. Deferred.

---

## Files Modified

| File | Changes |
|------|---------|
| `RiskAnalysis.tsx` | Remove 3 mock fallback arrays (~130 lines deleted), conditional summary card |
| `StrategyBuilder.tsx` | Delete AI Recommendations card (~28 lines), `strategyPreview` fallbacks → null with guards, `prebuiltStrategies` + `templatesAsStrategies` zeroes → NaN, color guard for NaN |
| `HoldingsView.tsx` | `lastUpdate: 'Live'` → `''` (2 locations) |

## Verification

1. `cd frontend && pnpm typecheck` — must pass (no type widening, NaN is valid `number`)
2. Visual check: RiskAnalysis factors/stress/hedging tabs show real data or empty state (no fake "$127K")
3. Visual check: StrategyBuilder metrics show "—" when no optimization run, not "14.2%"
4. Visual check: Marketplace template cards show "—" instead of "0.00" for all metrics
5. Visual check: Holdings table has no green "LIVE" badges
6. Visual check: Featured Strategy spotlight shows "—" for metrics (not "0.0%")
