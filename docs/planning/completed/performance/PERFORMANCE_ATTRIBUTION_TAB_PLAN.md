# Performance View — Attribution Tab Rebuild

## Context

The Performance view's Attribution tab renders all 3 attribution types (sector, security, factor) but the current rendering is inconsistent and the header comment incorrectly says "❌ TODO". Sector attribution uses fancy card layout with hardcoded `momentum: 0`, `volatility: 0`, `recommendation: ""` fields that show nothing useful. Security attribution is split into Contributors/Detractors cards but not shown as a complete table. Factor attribution renders as a simple list. Meanwhile, the backtest Performance tab in StrategyBuilder already has clean, proven attribution tables for all 3 types.

**Goal:** Replace the current Attribution tab content with clean attribution tables matching the proven backtest pattern, plus keep the Contributors/Detractors split for security data. Update stale TODO comment. No backend changes needed — all data is already flowing.

## Changes

### 1. `PerformanceView.tsx` — Rebuild Attribution tab content

**File:** `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

#### 1a. Update stale TODO comment (line 49)

```
- • Attribution Analysis: ❌ TODO - Sector/factor/security contribution analysis
+ • Attribution Analysis: ✅ INTEGRATED - Sector/factor/security contribution tables
```

#### 1b. Simplify `mappedSectors` (lines 456-469)

Remove the unused fields (`insight`, `trend`, `riskLevel`, `momentum`, `volatility`, `recommendation`). These are holdovers from mock data and render nothing useful. Keep just the fields from the backend: `name`, `allocation`, `return`, `contribution`.

```typescript
const mappedSectors = Array.isArray(data?.attribution?.sectors) && data.attribution.sectors.length > 0
  ? data.attribution.sectors
  : []
```

#### 1c. Replace Attribution tab content (lines 1243-1525)

Replace the entire `<TabsContent value="attribution">` block with:

1. **Sector Attribution Table** — full-width card with table (name, allocation%, return%, contribution%). Same table pattern as `StrategyBuilder.tsx:1237-1269`. Sort by absolute contribution descending.

2. **Factor Attribution Table** — card with table (factor name, beta, return%, contribution%). Same pattern as `StrategyBuilder.tsx:1271-1303`. Only render if `mappedFactors.length > 0`; otherwise show "Factor attribution requires ≥12 months of data" message.

3. **Security Attribution — Contributors & Detractors** — 2-column grid. Left: Top Contributors (positive contribution, sorted desc). Right: Top Detractors (negative contribution, sorted by absolute desc). Each is a simple table with (ticker, weight%, return%, contribution%). Keep using the `topContributors`/`topDetractors` props already computed by the container.

All tables use the proven pattern from StrategyBuilder backtest:
- `<Card className="p-6 bg-white border-neutral-200/60">`
- `<table className="w-full text-sm">` with `thead` styling: `text-xs uppercase tracking-wide text-neutral-500 border-b border-neutral-200`
- Row styling: `border-b border-neutral-100`
- Contribution color: `text-emerald-600` (≥0) / `text-red-600` (<0)
- Empty state: `<td colSpan={N}>` centered message
- Format helpers: `formatPercent(value, { decimals: 2, sign: true })`, `formatOptionalPercent(value, 2)`, `formatOptionalNumber(value, 3)` (for beta)

#### 1d. Remove unused helper functions

Since we're removing the card-based sector rendering, the following become unused:
- `getTrendIcon()` — attribution-only, safe to remove
- `getAnalystRatingBadgeColor()` — attribution-only (Contributors/Detractors cards being replaced with tables), safe to remove
- **`getRiskBadgeColor()` — KEEP, used at line 1192 for AI insights badges outside the attribution tab**

### 2. `PerformanceViewContainer.tsx` — No changes needed

The container already:
- Maps `attribution.sectors`, `attribution.factors`, `attribution.security` from adapter (lines 516-520)
- Computes `topContributors`/`topDetractors` from security attribution sorted by |contribution| (lines 542-556)
- Passes all data to PerformanceView via props (lines 613-623)

### 3. `PerformanceAdapter.ts` — No changes needed

Already transforms all 3 attribution arrays from backend response.

## Files to Modify

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` | Rebuild Attribution tab with tables, simplify mappedSectors, update TODO comment |

## Key Design Decisions

1. **Reuse backtest table pattern** — Proven, clean, consistent across the app. No new component abstraction needed.
2. **Keep Contributors/Detractors split** — More useful than a raw security table for quick read. Container already computes the split.
3. **No new components** — Inline tables in the existing component. The pattern is simple enough to not warrant extraction.
4. **Frontend-only change** — All backend data is already flowing correctly. Zero backend changes.

## Verification

1. `cd frontend && pnpm exec tsc --noEmit -p packages/ui/tsconfig.json` — TypeScript passes
2. Live test: Navigate to Performance view → Attribution tab
   - Sector table shows real sectors with allocation, return, contribution
   - Factor table shows Market/Momentum/Value with betas and contributions (or empty state message if <12 months data)
   - Contributors shows positive-contribution positions sorted by |contribution|
   - Detractors shows negative-contribution positions sorted by |contribution|
3. All numbers should use consistent formatting with sign prefix on returns/contributions
