# Frontend Cleanup Audit

**Date:** 2026-03-04
**Status:** P1 ✅ P2 ✅ P3 ✅ P4 ✅ P5 ✅ Stragglers ✅ — Only P6 backend gaps remain.

---

## Priority 1: Active Harmful Code — ✅ COMPLETE (`62106f7b`)

All 4 items fixed. Plan: `completed/FRONTEND_CLEANUP_P1_PLAN.md`.

### ~~P1-1. PortfolioOverview: Simulated market fluctuations corrupt real values~~ ✅ DONE
Removed streaming interval, mount animation, `animatedValues` state, dead state variables. Metrics now display `rawValue` directly.

### ~~P1-2. PortfolioOverview: Refresh button ignores onRefresh prop~~ ✅ DONE
`handleDataRefresh` now calls `onRefresh?.()`. DOM toast injections removed (both refresh and settings save).

### ~~P1-3. PerformanceView: Hardcoded year "2024" in tooltip~~ ✅ DONE
Year derived from `month.date?.split('-')[0]`.

### ~~P1-4. PerformanceView: Broken period selector keys~~ ✅ DONE
Period selector trimmed to `1M` and `1Y` — the only periods with real adapter data.

---

## Priority 2: Hardcoded Mock Data Still Rendering — ✅ COMPLETE (`62106f7b`)

All 6 actionable items resolved. P2-7 deferred (not harmful). Plan: `completed/FRONTEND_CLEANUP_P2_PLAN.md`.

### ~~P2-1. RiskAnalysis: Full mock fallback arrays~~ ✅ DONE
Mock fallback arrays (~130 lines) replaced with `data?.riskFactors ?? []` etc. Empty array = no cards = correct empty state.

### ~~P2-2. RiskAnalysis: Hardcoded prose summary~~ ✅ DONE
Replaced with conditional render: only shows when `stressTests.length > 0`, displays data-driven count instead of fake prose.

### ~~P2-3. StrategyBuilder: Hardcoded "AI Recommendations"~~ ✅ DONE
Entire AI Recommendations card deleted (~28 lines). Real AI recommendations live on Portfolio Overview via `useAIRecommendations()`.

### ~~P2-4. StrategyBuilder: strategyPreview fallback with fake metrics~~ ✅ DONE
Fallbacks changed from fake numbers (14.2%, 19.8%, 1.24, -22.4%) to `null` with inline null guards → renders "—".

### ~~P2-5. StrategyBuilder: Marketplace templates show zeroed metrics~~ ✅ DONE
`prebuiltStrategies` + `templatesAsStrategies` zeroes → `NaN`. `NaN` is valid `number` (no type widening), `formatNumber(NaN)` → "—" via `toFiniteValue()`. Color guard added for `NaN >= 0` edge case.

### ~~P2-6. HoldingsView: "LIVE" badge always shown~~ ✅ DONE
`lastUpdate: 'Live'` → `''` at both locations. Badge rendering already gates on `=== "Live"`.

### P2-7. PortfolioOverview: Sparklines permanently dead — SKIPPED
Not showing fake data — just empty UI element. `trend: []` produces no visual output. Needs intraday data pipeline. Deferred.

---

## Priority 3: Dead UI / Inert Buttons — ✅ COMPLETE (`b99dc188`, `396da1c3`)

All 4 actionable items resolved. P3-5 reclassified as not-a-bug. Plan: `completed/FRONTEND_CLEANUP_P3_PLAN.md`.

### ~~P3-1. PortfolioOverview: 6+ inert buttons~~ ✅ DONE (`b99dc188`)
Deleted dropdown menu (5 items), Star+Layers buttons, Action+Dismiss buttons, Implement+Learn More buttons. Cleaned unused imports.

### ~~P3-2. HoldingsView: Inert row action buttons and Export CSV~~ ✅ DONE (`396da1c3`)
Deleted row Eye/MoreVertical buttons + actions column header, Filter icon button, Export CSV button.

### ~~P3-3. ScenarioAnalysis: Inert Export/Details buttons~~ ✅ DONE (`396da1c3`)
Deleted Export + Details buttons from analysis results summary.

### ~~P3-4. StrategyBuilder: Uncontrolled Strategy Rules inputs~~ ✅ DONE (`396da1c3`)
Deleted Strategy Rules card (~57 lines), View Details button, Configure+Pause buttons. Removed `Switch`, `Settings` imports.

### P3-5. StockLookup: Trade side hardcoded "BUY" — NOT A BUG
`TradePreviewData` has no `side` field. Trade preview is always "add position" = always BUY. Correct behavior.

---

## Priority 4: Unused State / Dead Code

Code that exists but serves no purpose. Increases maintenance burden and confuses future readers.

### ~~P4-1. PortfolioOverview: Unused state variables~~ ✅ DONE
- `realTimeEnabled`, `streamingData`, `marketMode`, `_lastMarketUpdate` removed in P1-1 (`62106f7b`)
- `advancedMode`, `alertsEnabled` removed (dead no-setter state)
- 5 settings objects (`displaySettings` etc.) are **not unused** — fully wired to settings panel UI

### ~~P4-2. PortfolioOverview: DOM-injected toasts~~ ✅ DONE (P1-2, `62106f7b`)
Both DOM toast sites removed as part of P1-2 refresh handler fix.

### ~~P4-3. RiskAnalysis: 5 props destructured but never used~~ ✅ DONE
Underscore-prefixed props removed; component now only destructures `data`.

### ~~P4-4. StrategyBuilder: Dead state variable~~ ✅ DONE (`f0073bc9`)
Removed `_selectedStrategy` / `_setSelectedStrategy`.

### ~~P4-5. PerformanceView: animationEnabled never gates anything~~ ✅ DONE
Completely removed — no traces remain.

### ~~P4-6. RiskAnalysisAdapter: Dead methods~~ ✅ DONE (`f0073bc9`)
Deleted `transformRiskContributions()`, `transformCorrelations()`, stale comments, orphaned `formatBasisPoints` import.

### ~~P4-7. Adapter cache key bugs~~ ✅ DONE (`f0073bc9`)
Removed `Date.now()` from `PortfolioOptimizationAdapter` and `RiskSettingsAdapter` cache keys. Added proper content-based dependencies.

---

## Priority 5: Stale TODOs / Comment Blocks

Documentation debt that makes the codebase harder to read.

### P5-1. HoldingsView: Stale header TODOs — KEEP
2 dividend TODOs remain (lines 300, 353) — genuinely unwired. Stale header TODOs for wired fields already cleaned.

### ~~P5-2. RiskAnalysis: 164-line ASCII header~~ ✅ DONE
Replaced with clean JSDoc header.

### ~~P5-3. StrategyBuilder: Stale "MOCK DATA REPLACEMENT" block~~ ✅ DONE
Block removed.

### ~~P5-4. StockLookup: Stale "BACKEND INTEGRATION" header~~ ✅ DONE
Header removed.

### P5-5. ScenarioAnalysis: "Coming Soon" banners — INTENTIONAL
Three "not yet available" messages for historical stress testing — legitimate disabled feature UX, not stale debt.

### ~~P5-6. PerformanceView: "Excel Workbook" label on CSV export~~ ✅ DONE
Now correctly labeled "CSV Data".

---

## Priority 6: Adapter Gaps (Need Backend Work) — Tracked in TODO.md

Remaining gaps where the backend doesn't provide the data. 3 items were misidentified (data already flows).

| Adapter | Gap | Status |
|---------|-----|--------|
| PerformanceAdapter | 1D/1W period returns = 0 | Genuine gap — no intraday/weekly engine |
| ~~PerformanceAdapter~~ | ~~Benchmark time series = 0~~ | **Not a gap** — backend computes `benchmark_monthly_returns`, adapter `?? 0` is null-safe fallback |
| ~~PerformanceAdapter~~ | ~~Rolling Sharpe/Vol = null~~ | **Not a gap** — backend computes 12-month trailing `rolling_sharpe`/`rolling_volatility`, adapter `?? null` is correct |
| RealizedPerformanceAdapter | `data_availability` all false | Genuine gap — backend doesn't send these fields |
| RealizedPerformanceAdapter | Benchmark flat in realized mode | Genuine gap — only aggregate return, no monthly series |
| HedgingAdapter | cost/VaR = 0/'N/A' | Genuine gap — backend API doesn't provide |
| ~~RiskSettingsAdapter~~ | ~~8 defaults (10%-50%)~~ | **Not a gap** — backend provides all 8 fields, defaults are smart fallbacks |

---

## Deletable Dead Code

| File | Reason |
|------|--------|
| `frontend/archive/legacy/NotificationCenter.tsx` | Deprecated, not imported anywhere. Full mock data. |

---

## Files Modified Summary

| Priority | Count | Impact |
|----------|-------|--------|
| P1: Active harmful | 4 items | Fake data shown as real, broken UI |
| P2: Mock data rendering | 7 items | Fabricated numbers displayed to user |
| P3: Dead UI | 5 items | Buttons that do nothing |
| P4: Dead code | 7 items | Maintenance burden, confusion |
| P5: Stale docs | 6 items | Readability |
| P6: Backend gaps | 4 genuine (3 misidentified) | Need backend work first |
