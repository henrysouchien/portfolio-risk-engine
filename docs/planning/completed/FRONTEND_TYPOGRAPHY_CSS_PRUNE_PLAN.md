# Frontend Phase 5 Polish: Typography + CSS Pruning Batch

## Context
Continuing Phase 5 Visual Polish. This batch applies `text-balance-optimal` typography to view-level headings and removes unused CSS classes.

`text-balance-optimal` provides: `text-wrap: balance`, `line-height: 1.45`, `letter-spacing: -0.015em`, `font-variant-ligatures: common-ligatures`. Currently used in 1 portfolio component (PerformanceHeaderCard `<h1>`).

## Changes

### 1. Add `text-balance-optimal` to SectionHeader block title

**File:** `frontend/packages/ui/src/components/blocks/section-header.tsx`

**Line 86:** Change `<h2>` className from:
```
text-base font-semibold text-neutral-900 md:text-lg
```
to:
```
text-base font-semibold text-neutral-900 md:text-lg text-balance-optimal
```

This propagates to all `SectionHeader` consumers:
- **`size="md"` (view-level):** ScenarioAnalysis ("Advanced Scenario Analysis"), StrategyBuilder ("Investment Strategies"), StockLookup ("Stock Risk Lookup")
- **`size="sm"` (section-level):** BenchmarksTab:32, PeriodAnalysisTab:21, RiskAnalysisTab:18, AttributionTab:142/155/173/193

The `size="sm"` consumers are section headings within performance tabs — `text-balance-optimal` is harmless on these (short single-line titles, `text-wrap: balance` is a no-op on single lines).

Note: `SectionHeader` is also registered in the chat block system (`register-defaults.ts` as `"section-header"`). Adding `text-balance-optimal` there is harmless — chat section headers are short labels where `text-wrap: balance` is a no-op.

### 2. Add `text-balance-optimal` to standalone view-level CardTitle headings

These top-level view titles use `CardTitle` directly (not through `SectionHeader`):

- `RiskAnalysis.tsx` line 138: `<CardTitle className="text-xl font-semibold flex items-center">` → add `text-balance-optimal`
- `FactorRiskModel.tsx` line 314: `<CardTitle className="text-lg font-semibold text-neutral-900">` → add `text-balance-optimal`
- `holdings/HoldingsTableHeader.tsx` line 30: `<CardTitle className="flex items-center text-lg font-semibold text-neutral-900">` → add `text-balance-optimal`
- `RiskMetrics.tsx` line 269: `<CardTitle className="text-xl font-bold text-neutral-900 tracking-tight">` → add `text-balance-optimal`
- `AssetAllocation.tsx` line 174: `<CardTitle className="text-lg font-medium flex items-center">` → add `text-balance-optimal`

### 3. Remove unused `dashboard-layout` CSS class

**File:** `frontend/packages/ui/src/index.css`

Delete lines 689-719 (the `.dashboard-layout` block with its 2 media query variants). This class is defined but never referenced in any TSX file. The comment block and all 3 rule blocks (base, tablet, desktop) should be removed.

## Dropped
- No changes to `<h3>` section headings within tabs (e.g., "Valuation Metrics", "Support & Resistance", "Volatility Metrics"). These are small card-level labels where `text-wrap: balance` has no visual effect (single-line text).
- No changes to `<h4>` headings — same rationale, all short single-line labels.
- No changes to SettingsPanel `<h3>` headings — settings section labels, single-line.
- No changes to metric value `<div>` elements with `text-xl font-bold` — these are numeric values, not prose headings.
- No changes to `PerformanceHeaderCard.tsx` line 90 — already has `text-balance-optimal`.
- `AssetAllocation.tsx` line 174: `<CardTitle>` "Asset Allocation" — added to Changes (top-level dashboard panel).
- No changes to `PerformanceChart.tsx` line 237 — `<CardTitle>` has no active render path in the modern app (unused/unwired legacy component).
- No changes to `StockLookup.tsx` line 255 `<h2>` — renders `selectedStock.symbol` (a ticker symbol, not prose). The StockLookup view heading is already covered by `SectionHeader` at line 115.
- No changes to `AIChat.tsx` line 84, `SnapTradeSuccess.tsx` line 69, `PlaidSuccess.tsx` line 69 — these are outside the portfolio component scope of this polish pass.
- No other unused CSS classes found — all remaining custom classes (32 after removing `dashboard-layout`, including Tailwind overrides like `.rounded-2xl`/`.rounded-3xl`) have active TSX consumers.
