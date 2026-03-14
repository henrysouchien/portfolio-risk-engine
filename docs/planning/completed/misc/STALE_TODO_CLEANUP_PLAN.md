# Stale TODO Cleanup — PortfolioOverview & PerformanceView

## Context

TODO.md item "Stale TODO Cleanup": 8+ stale TODO comments across PortfolioOverview and PerformanceView reference fields that are now wired. Also unused `_prefixed` state variables in both files. This is the last open item under "Frontend Wiring Gaps (Pre-Redesign)".

**Goal:** Remove stale TODO comments and unused state variables from 3 files. Pure cleanup — no behavioral changes.

---

## Changes

### 1. `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

**A. Remove 6 stale `TODO:ADD to PortfolioSummaryAdapter` comments (lines 86-91)**

These are in the header comment block. All 6 fields (`totalValue`, `dayChange`, `dayChangePercent`, `ytdReturn`, `sharpeRatio`, `maxDrawdown`) are already wired through `PortfolioSummaryAdapter`. Remove the `TODO:ADD to PortfolioSummaryAdapter` suffix from each line, keeping the field description.

Before:
```
*       totalValue: number;           // Real portfolio value TODO:ADD to PortfolioSummaryAdapter
```
After:
```
*       totalValue: number;           // Real portfolio value ✅
```

**B. Remove 5 truly unused state variables (lines 360, 366-368, 372)**

Delete these 5 `useState` declarations entirely — neither the value nor the setter is referenced anywhere else in the component:

- Line 360: `const [_personalizedView, _setPersonalizedView] = useState(true)`
- Line 366: `const [_predictiveMode, _setPredictiveMode] = useState(false)`
- Line 367: `const [_correlationAnalysis, _setCorrelationAnalysis] = useState(false)`
- Line 368: `const [_riskRadar, _setRiskRadar] = useState(false)`
- Line 372: `const [_selectedTimeframe, _setSelectedTimeframe] = useState<"1D" | "1W" | "1M" | "1Y">("1D")`

**NOT removing** (value or setter IS used elsewhere in the component):
- `realTimeEnabled` (line 353, value read at lines 605/638)
- `_lastMarketUpdate` / `setLastMarketUpdate` (line 354, setter called at lines 608/651 — value not read but setter is active)
- `streamingData` (line 355, value read at lines 605/1170)
- `marketMode` (line 356, value read at lines 634/1527)
- `advancedMode` (line 361, value read at line 681)
- `alertsEnabled` (line 365, value read at line 1110)

### 2. `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

**A. Update stale status markers (lines 49-50)**

Sector + security attribution wired in commit `2315fa16`. Dynamic benchmarks wired via benchmark selection UI (commit `33e5b78b`). Update:

Before:
```
 * • Attribution Analysis: ❌ TODO - Sector/factor/security contribution analysis
 * • Dynamic Benchmarks: ❌ TODO - Multiple benchmark selection (currently SPY default)
```
After:
```
 * • Attribution Analysis: ✅ INTEGRATED - Sector/security attribution (factor/Brinson backlog)
 * • Dynamic Benchmarks: ✅ INTEGRATED - SPY/QQQ/VTI/custom benchmark selection
```

**B. Update stale TODO in architecture diagram (line 133)**

Before:
```
 *   └── Attribution analysis (TODO: backend enhancement)
```
After:
```
 *   └── Attribution analysis (sector/security wired; factor/Brinson backlog)
```

**C. Update Enhancement Opportunities block (lines 155-157)**

Lines 156-157 reference attribution and multiple benchmarks as TODOs — both now partially/fully wired. Update:

Before:
```
 * • Attribution Analysis: Add comprehensive sector/factor/security contribution analysis
 * • Multiple Benchmarks: Support for multiple benchmark selection (SPY, QQQ, IWM, custom)
```
After:
```
 * • Attribution Analysis: ✅ Sector/security wired. Backlog: factor/Brinson attribution
 * • Multiple Benchmarks: ✅ SPY/QQQ/VTI/custom benchmark selection wired
```

**D. Clean aspirational TODO block (lines 87-105)**

Replace the 15+ `TODO: ADD` lines in the data structure comment with `✅` markers where wired, and mark the remaining items as backlog:

- Lines 87-101 (attribution `sectors`/`factors`/`security`): Sector + security are wired. Factor/Brinson is backlog. Update comments to reflect.
- Lines 102-105 (benchmarks): Wired via benchmark selection UI. Mark `✅`.

**C. Update mock data TODOs (lines 607-627)**

- Lines 607-610 (`currentValue`, `totalReturn`, `totalReturnPercent`): These are hardcoded values. Keep the values (they serve as fallbacks) but update TODO comments to note they're fallback/display values, not blocking items.
- Lines 623-627 (`infoRatio`, `trackingError`, `upCaptureRatio`, `downCaptureRatio`): These are genuinely not yet computed by backend. Change `TODO: integrate with backend when available` → `Backlog: computed when backend supports these metrics` to distinguish from blocking TODOs.

**D. Remove unused `_activeTab` state (line 288)**

Delete: `const [_activeTab, _setActiveTab] = useState("attribution")`

Neither `_activeTab` nor `_setActiveTab` is referenced elsewhere.

### 3. `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`

**A. Remove stale "MINOR ENHANCEMENTS NEEDED" block (lines 62-65)**

All 3 items are stale: benchmark selection is wired, sector/security attribution is wired, and export intents are wired. Remove the entire block.

Before:
```
 * MINOR ENHANCEMENTS NEEDED:
 * - Add dynamic benchmark selection (currently uses SPY as default)
 * - Add sector/factor attribution analysis (backend enhancement)
 * - Add 'refresh-performance', 'export-pdf', 'export-csv' intents to NavigationIntents.ts
```
After: (delete these 4 lines)

**B. Remove stale TODO comment (line 310)**

Before:
```
// usePerformance Hook (TanStack Query + PerformanceAdapter - TODO: Enhance for full requirements)
```
After:
```
// usePerformance Hook (TanStack Query + PerformanceAdapter)
```

---

## Files

| File | Action |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` | MODIFY — remove 6 stale TODOs + 5 unused state vars |
| `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` | MODIFY — update stale markers + clean TODOs + remove 1 unused state var |
| `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` | MODIFY — remove stale ENHANCEMENTS block + 1 TODO comment |

## Codex Review (R1)

**FAIL** — 2 findings, both addressed above:
1. **Medium** — `_lastMarketUpdate` value is not read (only setter is used). Plan inaccurately said "value IS read". → Fixed: clarified "setter called" in NOT-removing list.
2. **Medium** — 4 additional stale TODOs missed: `PerformanceView.tsx:133` (architecture diagram TODO), `PerformanceView.tsx:156-157` (Enhancement Opportunities), `PerformanceViewContainer.tsx:62-65` (MINOR ENHANCEMENTS NEEDED block). → Fixed: added sections 2B, 2C, 3A.

## Verification

1. `pnpm typecheck` — no TS errors (removing unused vars should only help)
2. `pnpm build` — clean build
3. Visual inspection: no behavioral changes, component renders identically
