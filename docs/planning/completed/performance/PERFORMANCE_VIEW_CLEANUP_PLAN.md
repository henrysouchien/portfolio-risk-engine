# PerformanceView Cleanup + Wire Real Metrics

**Status:** ✅ COMPLETE (2026-03-04)

## What Was Done

### 1. Backend — Up/Down Capture Ratios
Added geometric-mean capture ratio computation to `performance_metrics_engine.py`. Returns `None` when < 3 months of benchmark data. Values in "ratio × 100" form (108.5 = 108.5% capture). Added to `risk_adjusted_returns` dict.

### 2. Adapter — Thread Capture Ratios + Fix Double-Conversion Bug
- Added `upCaptureRatio`/`downCaptureRatio` to `PerformanceResult` interface, `PerformanceData.riskMetrics`, and `RealizedPerformanceAdapter`
- **Fixed critical double-conversion bug**: Backend `compute_performance_metrics()` returns values already in percent (e.g., `volatility: 8.64` = 8.64%). The adapter's `transformRisk()` and `transformPerformanceSummary()` were multiplying by 100 again, producing values like 864% instead of 8.64%. Removed `* 100` from: volatility, maxDrawdown, downsideDeviation, trackingError (in `transformRisk()`), portfolioReturn/benchmarkReturn/activeReturn/volatility (in period summaries), maxDrawdown and alpha (in riskMetrics)
- Added `up_capture_ratio`/`down_capture_ratio` to `RealizedPerformanceApiResponse` in chassis types

### 3. Container — Thread 6 New Metrics
Expanded `PerformanceViewContainer` types and `mappedData` with: `informationRatio`, `trackingError`, `sortino`, `calmar`, `upCaptureRatio`, `downCaptureRatio` — all from `performanceSummary.riskMetrics` path.

### 4. View — Cleanup + Wire Real Values
- Replaced 165-line stale comment header with 8-line summary
- Replaced hardcoded metrics (`infoRatio: 0.34`, `trackingError: 4.2`, `upCaptureRatio: 108.5`, `downCaptureRatio: 92.3`) with real prop values
- Added sortino + calmar to metrics grid (now 8 items: Info Ratio, Tracking Error, Sortino, Calmar, Up Capture, Down Capture, Max Drawdown, Downside Dev)
- Replaced hardcoded drawdown values (89 days, 156 days, Feb 2024, 11.4%, -$47,200) with "--" (backend doesn't provide these)
- Removed hardcoded `currentValue`/`totalReturn`/`totalReturnPercent` dollar amounts

## Files Modified

| File | Change |
|------|--------|
| `portfolio_risk_engine/performance_metrics_engine.py` | Capture ratios |
| `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` | Capture ratios + double-conversion fix |
| `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` | Capture ratios |
| `frontend/packages/chassis/src/types/index.ts` | Realized API type |
| `frontend/packages/ui/.../PerformanceViewContainer.tsx` | Thread 6 metrics |
| `frontend/packages/ui/.../PerformanceView.tsx` | Header cleanup, wire real values, expand grid |

## Verified

- `pnpm typecheck` — passed
- Live test in Chrome — all values correct (Info Ratio -0.10, Tracking Error 10.63%, Sortino 2.29, Calmar 7.18, Up Capture 66.9%, Down Capture 7.4%, Volatility 8.64%, Max Drawdown -2.43%)

---

# Phase 2: Dead Export + Unused Prop Cleanup

**Date:** 2026-03-04
**Status:** Pending Codex review

## Context

Two remaining dead code issues in PerformanceView.tsx:

1. **Dead export simulation**: `handleExport` (lines 262-295) simulates a 2s delay and creates a DOM toast instead of calling the real `onExport` prop. Meanwhile, `_handleExportData` (lines 177-192) correctly calls `onExport` but is prefixed unused.
2. **Unused `_className` prop**: Accepted at line 113 but never applied.

## Codex Review Findings (addressed)

1. **Excel export not supported**: Container/intent system only handles `'pdf' | 'csv'`. No `export-excel` intent exists. Fix: keep prop type as `'pdf' | 'csv'`, change Excel button to pass `'csv'` format.

## Changes

### 1. Fix export handler (PerformanceView.tsx)

- **Delete** the dead `handleExport` function (lines 262-295) — the DOM toast simulation
- **Rename** `_handleExportData` → `handleExport` (lines 177-192) — this already calls `onExport` correctly
- **Keep** prop type as `onExport?: (format: 'pdf' | 'csv') => void` (line 99) — no change
- **Change** Excel button at line 790 from `handleExport('excel')` → `handleExport('csv')` (intent system routes non-pdf to CSV anyway)

### 2. Remove unused `_className` prop (PerformanceView.tsx)

- Remove `className: _className = ""` from destructuring (line 113)
- Keep `className?: string` in the interface (line 101) — container may pass it

## Files

- `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. Verify export buttons still render (no broken references)
