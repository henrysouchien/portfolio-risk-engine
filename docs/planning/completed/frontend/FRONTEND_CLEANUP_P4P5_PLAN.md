# Frontend Cleanup P4 + P5 — Dead Code & Stale Comments

## Context

`completed/FRONTEND_CLEANUP_AUDIT.md` P1+P2 complete. P4 (dead code) and P5 (stale TODOs) remain. 4 of 13 items already fixed by prior work. 9 items remain. Pure cleanup — no behavioral changes except P5-5 (remove misleading "Coming Soon" banners) and P5-6 (remove misleading "Excel Workbook" label).

All paths relative to `frontend/packages/ui/src/components/portfolio/` unless noted.

---

## P4: Dead Code (4 items)

### ~~P4-1. PortfolioOverview: 5 settings state objects~~ — NOT DEAD
**Status:** SKIP. Codex R1 found these ARE used — bound to settings panel UI, setters called on save action. Not dead code.

### P4-3. RiskAnalysis: 5 unused `_` prefixed props
**File:** `RiskAnalysis.tsx` ~lines 251-255
**Problem:** `_hasData`, `_loading`, `_error`, `_onRefresh`, `_className` — destructured but never used.
**Fix:** Remove all 5 from the destructuring. If the props interface declares them, keep the interface (container passes them), just stop destructuring.

### P4-3b. StockLookup: unused `_className` prop
**File:** `StockLookup.tsx` line ~386
**Problem:** `className: _className = ""` — destructured but never used (same pattern as P4-3).
**Fix:** Remove from destructuring. Keep in props interface.

### P4-5. PerformanceView: `animationEnabled` never gates anything
**File:** `PerformanceView.tsx` ~line 132
**Problem:** `animationEnabled` state stored + localStorage-persisted but never conditionally renders any animation.
**Fix:** Delete the `useState`, any localStorage sync, and remove from dependency arrays.

---

## P5: Stale TODOs / Comments (6 items)

### P5-1. HoldingsView: 13 stale header TODOs
**File:** `HoldingsView.tsx` ~lines 62-102
**Problem:** 13 `// TODO: ADD to PortfolioSummaryAdapter` comments for fields already wired (sector, assetClass, avgCost, currentPrice, totalReturn, totalReturnPercent, dayChange, dayChangePercent, weight, beta, volatility, alerts, trend).
**Fix:** Replace `TODO: ADD to PortfolioSummaryAdapter` with `✅` on each line. Keep `dividend` TODOs at lines ~303 and ~356 (genuinely unwired).

### P5-2. RiskAnalysis: 164-line ASCII header
**File:** `RiskAnalysis.tsx` lines 1-164
**Fix:** Replace with a concise 10-line header: component name, purpose, data flow (Container → Hook → Adapter → API), key sections, integration status.

### P5-3. StrategyBuilder: Stale "MOCK DATA REPLACEMENT" block
**File:** `StrategyBuilder.tsx` ~lines 292-302
**Fix:** Delete the entire comment block — the work it describes has been done.

### P5-4. StockLookup: Stale "BACKEND INTEGRATION" header
**File:** `StockLookup.tsx` ~lines 85-156
**Fix:** Replace ~70-line header with concise 10-line header: component name, purpose, integration status (complete), key features.

### P5-5. ScenarioAnalysis: Misleading "Coming Soon" text (8 locations)
**File:** `ScenarioAnalysis.tsx`
**Problem:** Container passes real `onRunScenario`, `onRunStressTest`, `onRunMonteCarlo` handlers — all three features ARE implemented. The "Coming Soon" text is either dead code or misleading. 8 locations across 2 tabs:

**Historical tab** (genuinely unimplemented — historical replay is backlog):
1. **Line ~1447** — Run Analysis button text: `canRunScenario ? "Run Analysis" : "Coming Soon"`. Shows "Coming Soon" on non-scenario tabs. **Fix:** Change fallback to `"Run Analysis"` — the `disabled` prop already handles UX.
2. **Line ~1455** — `showGlobalComingSoonBanner`: "Historical scenario replay is coming soon." Shows on the historical tab. **Fix:** Change text to `"Historical scenario replay is not yet available."` (remove "coming soon").
3. **Line ~1886** — Static banner: "Historical stress testing is coming soon." Always rendered in the historical tab (NOT gated by `canRunStressTests`). **Fix:** Change text to `"Historical stress testing is not yet available."` (remove "coming soon").
4. **Line ~1908** — Per-scenario `<Badge>`: "Coming soon". Always rendered for each historical scenario card. **Fix:** Change text to `"Not yet available"`.
5. **Line ~1955** — Per-row button `title`: `"Historical stress testing — coming soon"`. Button is permanently `disabled`. **Fix:** Change title to `"Historical stress testing is not yet available"`.

**Stress Tests tab** (dead code — `canRunStressTests` is always true since container passes `onRunStressTest`):
6. **Lines ~1978-1982** — `{!canRunStressTests && (...)}` banner: "Factor shock stress tests are coming soon." Dead code — condition never true. **Fix:** Delete the entire block.
7. **Lines ~2007-2011** — `{!canRunStressTests ? <Badge>Coming soon</Badge>}` fallback. Dead code. **Fix:** Remove the ternary, always render the "Live" badge (or just the badge without the conditional).
8. **Line ~2045** — Per-row button `title`: `"Stress testing — coming soon"`. Dead code — `!canRunStressTests` is always false. **Fix:** Delete the `title` prop.

### P5-6. PerformanceView: "Excel Workbook" label on CSV export
**File:** `PerformanceView.tsx` ~lines 755-759
**Problem:** Menu item labeled "Excel Workbook" calls `handleExport('csv')` — misleading.
**Fix:** Remove the "Excel Workbook" option entirely (keep the CSV option which already exists).

---

## Files

| File | Changes |
|------|---------|
| `RiskAnalysis.tsx` | P4-3: remove 5 unused props; P5-2: trim 164-line header to ~10 lines |
| `PerformanceView.tsx` | P4-5: remove `animationEnabled`; P5-6: remove "Excel Workbook" option |
| `HoldingsView.tsx` | P5-1: update 13 stale TODO comments |
| `StrategyBuilder.tsx` | P5-3: delete stale comment block |
| `StockLookup.tsx` | P4-3b: remove unused `_className`; P5-4: trim header to ~10 lines |
| `ScenarioAnalysis.tsx` | P5-5: fix 8 "Coming Soon" locations (3 dead blocks removed, 5 text fixes) |

## Verification

1. `cd frontend && pnpm typecheck` — 0 TS errors
2. `cd frontend && pnpm build` — clean build
3. Visual check: all 7 views render correctly, no missing UI elements
