# Frontend Redesign — Phase 1a: Color Consolidation

**Date:** 2026-03-05
**Status:** COMPLETE (`d8d985a6`, 2026-03-05)
**Source:** `FRONTEND_REDESIGN_PLAN.md` Phase 1a
**Codex Review:** R1-R5 all addressed, R6 PASS. Implementation by Codex, verified visually in Chrome.

---

## Context

The frontend has 20 color mapping functions scattered across 9 files, with 3 major duplicated patterns and 15+ inline ternary chains. Every view component defines its own `getRiskColor()`, `getChangeColor()`, etc. with slightly different signatures but identical semantics. The existing `theme/colors.ts` only covers risk score colors.

Phase 1a consolidates all color helpers into `packages/ui/src/lib/colors.ts`, creating the shared design-system layer that Phase 2+ component decomposition depends on. Without this, extracting sub-components would just move the duplication into more files.

---

## Step 1: Create `lib/colors.ts` with consolidated helpers

**New file:** `frontend/packages/ui/src/lib/colors.ts`

### 1a. `getChangeColor(value: number, zeroPositive = false): string`

Replaces: `HoldingsView:491`, `PerformanceView:477` (default mode), inline ternaries in `StockLookup`, `StrategyBuilder`, `PerformanceView`, `ScenarioAnalysis`.

**Codex fix #1:** Many inline sites use `>= 0` (zero=green). Add `zeroPositive` parameter to preserve existing behavior per call site.

```typescript
export function getChangeColor(value: number, zeroPositive = false): string {
  if (value > 0) return 'text-emerald-600'
  if (value < 0) return 'text-red-600'
  if (zeroPositive && value === 0) return 'text-emerald-600'
  return 'text-neutral-600'
}
```

- `HoldingsView:491`, `PerformanceView:477` default → `getChangeColor(value)` (zero=neutral, matches current)
- `StrategyBuilder:940,974,1008,1042`, `PerformanceView:1023,1058,1092,1126`, `StockLookup:496,595,794` → `getChangeColor(value, true)` (zero=green, matches current `>= 0` ternaries)
- `ScenarioAnalysis:1754,1760,1766,1772` (factor impact ternaries) → `getChangeColor(value, true)`
- `StockLookup:1176` (portfolio delta) → leave as-is (inverted logic: higher=red, not standard change color)

### 1b. `getLevelBadgeClasses(level: string): string`

**Codex fix #2:** Current implementations have divergent styles. Instead of dynamic template literals (Tailwind JIT unsafe), use a **static lookup map** returning full class strings.

**Codex fix #3 (Tailwind safety):** All class names are complete string literals — no template interpolation. Tailwind purge sees them all.

```typescript
const LEVEL_BADGE_MAP: Record<string, string> = {
  // emerald family
  low: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  good: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  success: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  // amber family
  medium: 'bg-amber-100 text-amber-700 border-amber-200',
  moderate: 'bg-amber-100 text-amber-700 border-amber-200',
  warning: 'bg-amber-100 text-amber-700 border-amber-200',
  // red family — "high" maps to red (matches RiskAnalysis, PerformanceView, FactorRiskModel)
  high: 'bg-red-100 text-red-700 border-red-200',
  extreme: 'bg-red-100 text-red-700 border-red-200',
  severe: 'bg-red-100 text-red-700 border-red-200',
  poor: 'bg-red-100 text-red-700 border-red-200',
  error: 'bg-red-100 text-red-700 border-red-200',
}
const LEVEL_BADGE_DEFAULT = 'bg-neutral-100 text-neutral-700 border-neutral-200'

export function getLevelBadgeClasses(level: string): string {
  return LEVEL_BADGE_MAP[level.toLowerCase()] ?? LEVEL_BADGE_DEFAULT
}
```

**Per-component migration notes:**
- `RiskAnalysis:125` — Currently returns `text-{color}-600 bg-{color}-100` (no border). After migration, badge gains border class. Additive/harmless — Badge already has `border` in base styles. High→red preserved.
- `PerformanceView:506` — Currently uses `text-*-800` + `border-*/60`. Minor visual change: 800→700 text shade, border opacity removed. Acceptable — standardizing on one look. High→red preserved.
- `FactorRiskModel:228` — High→red preserved. Low currently uses `bg-green-100 text-green-700` → now `bg-emerald-100 text-emerald-700`. Minor shade shift for consistency.
- `ScenarioAnalysis:320` — Has 4-tier scheme (Low/Medium/High/Extreme). High will change orange→red to match shared helper. Extreme stays red. This is acceptable — "High" and "Extreme" both being red is fine for severity badges. If orange distinction is desired later, add `ScenarioAnalysis`-specific overrides.
- `StockLookup:297` — Also 4-tier (Low/Medium/High/Extreme) with High=orange today. **Keep local `getRiskColor`** — it has a `.replace()` chain at line 708 that derives gradient Card backgrounds from badge classes. This runtime string manipulation is a pre-existing Tailwind purge risk that needs separate refactoring (noted below). Migrating it now would compound changes.

### 1c. `getTrendColor(trend: string): string`

Replaces: `RiskMetrics:245`.

**Codex fix:** Match current fallback `text-neutral-500` (not 600).

```typescript
export function getTrendColor(trend: string): string {
  const t = trend.toLowerCase()
  if (t === 'increasing' || t === 'up') return 'text-red-600'
  if (t === 'decreasing' || t === 'down') return 'text-emerald-600'
  if (t === 'stable') return 'text-neutral-600'
  return 'text-neutral-500'
}
```

### 1d. `getChangeStrokeColor(changeType: string): string`

Replaces: `PortfolioOverview:632`. Codex confirmed this is a correct replacement.

```typescript
export function getChangeStrokeColor(changeType: string): string {
  if (changeType === 'positive') return 'stroke-emerald-500'
  if (changeType === 'negative') return 'stroke-red-500'
  if (changeType === 'warning') return 'stroke-amber-500'
  return 'stroke-neutral-400'
}
```

### 1e. Risk score helpers — keep in `theme/colors.ts`

**Codex fix #5:** `data/index.ts` imports `riskColors` from `theme/colors.ts`. To avoid circular deps and unnecessary churn, keep `getRiskColor()`, `getRiskCategoryColor()`, and all risk constants in `theme/colors.ts`. Do NOT move them. `lib/colors.ts` is for the new consolidated helpers only.

### 1f. Category badge helpers (unique, keep in-component)

These are component-specific and NOT duplicated — leave in place:
- `getStrategyTypeColor()` (StrategyBuilder) — maps strategy types
- `getStatusColor()` (StrategyBuilder) — maps strategy statuses
- `getMetricColorSystem()` (PortfolioOverview) — complex 4-system object
- `getAlphaStrength()` (PerformanceView) — returns label + color
- `getExposureColor()` (FactorRiskModel) — numeric threshold
- `statusToColorScheme()` / `getStatusConfig()` (RiskMetrics) — component-specific gradient configs

---

## Step 2: Update consuming components

**Import path:** Use relative imports (`../lib/colors` or `../../lib/colors`) since `@risk/ui/lib/colors` is not a configured path alias in `tsconfig.base.json`. Only `@risk/ui` (pointing to `packages/ui/src/index.ts`) is configured.

Alternatively, add `export * from './lib/colors'` to `packages/ui/src/index.ts` so consumers can `import { getChangeColor } from '@risk/ui'`. **Preferred approach** — avoids deep relative paths and works with existing tsconfig.

| File | Local function(s) removed | Replaced with import |
|------|--------------------------|---------------------|
| `HoldingsView.tsx` | `getChangeColor` (line 491) | `getChangeColor` |
| `PerformanceView.tsx` | `getPerformanceColor` default branch (line 477), `getRiskBadgeColor` (line 506) | `getChangeColor`, `getLevelBadgeClasses` |
| `RiskAnalysis.tsx` | `getRiskColor` (line 125) | `getLevelBadgeClasses` |
| `ScenarioAnalysis.tsx` | `getSeverityColor` (line 320) | `getLevelBadgeClasses` |
| `StockLookup.tsx` | — (keep local `getRiskColor`, see note) | — |
| `FactorRiskModel.tsx` | `getSignificanceColor` (line 228) | `getLevelBadgeClasses` |
| `PortfolioOverview.tsx` | `getTrendColor` (line 632) | `getChangeStrokeColor` |
| `RiskMetrics.tsx` | `getTrendColor` (line 245) | `getTrendColor` |

**Inline ternaries** — replace with `getChangeColor()`:

| File | Lines | Current pattern | Replacement |
|------|-------|----------------|-------------|
| `StrategyBuilder.tsx` | 740-745, 940, 974, 1008, 1042 | NaN guard + `>= 0` ternaries | `getChangeColor(value, true)` (740: already has NaN guard, simplify with helper) |
| `PerformanceView.tsx` | 1023, 1058, 1092, 1126 | `row.contribution >= 0 ? "text-emerald-600" : "text-red-600"` | `getChangeColor(row.contribution, true)` |
| `StockLookup.tsx` | 496, 595 | `result.change >= 0 ? ... : ...` | `getChangeColor(result.change, true)` |
| `StockLookup.tsx` | 794 | `selectedStock.technicals.macd >= 0 ? ... : ...` | `getChangeColor(selectedStock.technicals.macd, true)` |
| `ScenarioAnalysis.tsx` | 1754, 1760, 1766, 1772, 1852 | `scenario.factors.equity < 0 ? ... : ...`, `shock.shock < 0 ? ... : ...` | `getChangeColor(value, true)` |

**Leave as-is** (not standard change coloring):
- `StockLookup.tsx:1176` — inverted logic (higher metric = red = worse), not a standard change pattern
- `HoldingsView.tsx:744` — severity dot colors (error/warning/info), use `getLevelBadgeClasses` only if it maps cleanly, otherwise leave as-is

**Special case — `PerformanceView.getPerformanceColor()`:** Has an "alpha" context mode with 4-tier thresholds. Keep the alpha branch as a local `getAlphaColor()` function; replace the default branch with imported `getChangeColor()`.

---

## Step 3: Export from `@risk/ui` barrel

Add to `frontend/packages/ui/src/index.ts`:
```typescript
export { getChangeColor, getLevelBadgeClasses, getTrendColor, getChangeStrokeColor } from './lib/colors'
```

`theme/colors.ts` stays unchanged — `data/index.ts` and `RiskMetrics.tsx` continue importing `riskColors` from it.

---

## Files Modified

| File | Changes |
|------|---------|
| `lib/colors.ts` | **NEW** — 4 helpers (~50 lines) |
| `index.ts` (ui barrel) | Add 1 re-export line |
| `HoldingsView.tsx` | Delete `getChangeColor`, add import (~3 lines net) |
| `PerformanceView.tsx` | Delete `getPerformanceColor` default + `getRiskBadgeColor`, add imports, replace 4 inline ternaries (~15 lines net) |
| `RiskAnalysis.tsx` | Delete `getRiskColor`, add import (~3 lines net) |
| `ScenarioAnalysis.tsx` | Delete `getSeverityColor`, add import, replace 5 inline ternaries (~9 lines net) |
| `StockLookup.tsx` | Keep local `getRiskColor` (4-tier + `.replace()` chain). Replace 3 inline ternaries only (~3 lines net) |
| `FactorRiskModel.tsx` | Delete `getSignificanceColor`, add import (~4 lines net) |
| `PortfolioOverview.tsx` | Delete `getTrendColor`, add import (~3 lines net) |
| `RiskMetrics.tsx` | Delete `getTrendColor`, add import (~3 lines net) |
| `StrategyBuilder.tsx` | Add import, replace 4 inline ternaries + 1 NaN guard chain (~5 lines net) |

**NOT modified:** `theme/colors.ts`, `data/index.ts`, `StockLookup.tsx` local `getRiskColor`

**Pre-existing issue (out of scope):** `StockLookup.tsx:708` uses `.replace()` chains to derive gradient Card classes from badge classes at runtime — a Tailwind purge risk that predates this work. Will address in Phase 2+ component decomposition.

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. `cd frontend && pnpm lint` — must pass
3. `cd frontend && pnpm build` — must pass (confirms Tailwind purge sees all classes)
4. Visual spot-check in Chrome:
   - Positive values green, negative red, zero follows per-site convention
   - Risk badges: Low=emerald, Medium=amber, High=red, Extreme=red (StockLookup keeps local High=orange)
   - Trend colors: increasing=red, decreasing=green, stable=neutral
5. Verify no stale local definitions remain (excluding kept locals):
   ```
   rg "const (getChangeColor|getSeverityColor|getSignificanceColor|getRiskBadgeColor|getTrendColor)\b" frontend/packages/ui/src/components/portfolio/
   ```
   Should return 0 matches. `getRiskColor` in `StockLookup.tsx` is intentionally kept. Other kept locals (`getStrategyTypeColor`, `getStatusColor`, `getMetricColorSystem`, `getAlphaStrength`, `getExposureColor`, `getStatusConfig`) are not in the search pattern.
