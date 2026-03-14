# Portfolio Overview — Wire Alpha & Concentration + Cleanup

**Date:** 2026-03-04
**Status:** Codex-reviewed, PASS

## Context

The Portfolio Overview displays 6 metric cards. The first 4 (Total Value, Daily P&L, Risk Score, Sharpe Ratio) show real data. The last 2 ("Alpha Generation" and "ESG Score") are hardcoded placeholders showing "—". ESG has no data source (FMP has no ESG endpoints). We're replacing these with:

- **Alpha Generation** → wire from existing CAPM alpha (already computed by performance engine)
- **Concentration** → replace ESG with concentration risk score (already computed by risk score engine)

Additionally, PortfolioOverview.tsx has dead code: unused `_prefixed` setters, unused props, and stale TODOs.

## Codex Review Findings (addressed)

1. **Concentration name mismatch**: RiskScoreAdapter emits `"Concentration Risk"` (display name), NOT `"concentration_risk"`. Fixed below.
2. **Dead code list overbroad**: Many listed variables ARE used (values read in render). Only `_prefixed` setters and props are truly unused. Corrected section 4.
3. **Score semantics inverted**: Higher concentration score = safer (100=best, 0=worst). Labels corrected.
4. **Missing type update**: `PortfolioOverviewProps.summary` also needs `alphaAnnual` and `concentrationScore`. Added.
5. **Import cleanup**: `Award` import must be removed when replaced by `PieChart`. Added.
6. **Alpha defaults to 0**: PerformanceAdapter defaults alpha to 0, not null. Display "0.0%" when 0 (valid), not "—".

## Changes

### 1. Wire Alpha & Concentration through PortfolioSummaryAdapter (MEDIUM)

**Problem:** `usePortfolioSummary` already fetches performance + risk score data, but `PortfolioSummaryAdapter` doesn't extract alpha or concentration from those payloads.

**Data already available in queries:**
- Alpha: `performanceQuery.data.performanceSummary.riskMetrics.alpha` (number, already ×100 in PerformanceAdapter line 796, defaults to 0)
- Concentration: `riskScoreQuery.data.component_scores` array → find item where `name === "Concentration Risk"` → `.score` (0-100, higher=safer)

**Fix:**
1. Add `alphaAnnual: number` and `concentrationScore: number` to `PortfolioSummaryMetrics` interface (default 0, not null — adapters already default to 0)
2. In `performTransformation()`, extract alpha from performance payload:
   ```typescript
   // Alpha is already ×100 in PerformanceAdapter (line 796)
   const perfSummary = this.asRecord(performanceRecord.performanceSummary);
   const perfRiskMetrics = this.asRecord(perfSummary.riskMetrics);
   const derivedAlpha = this.toNumber(perfRiskMetrics.alpha, 0);
   ```
3. Extract concentration from risk score payload:
   ```typescript
   // RiskScoreAdapter emits component_scores as array of {name: "Concentration Risk", score: number, maxScore: number}
   const componentScoresArr = Array.isArray(riskScoreRecord.component_scores)
     ? riskScoreRecord.component_scores : [];
   const concEntry = componentScoresArr.find(
     (c: unknown) => this.asRecord(c).name === "Concentration Risk"
   );
   const derivedConcentration = concEntry
     ? this.toNumber(this.asRecord(concEntry).score, 0) : 0;
   ```
4. Set `summary.alphaAnnual = derivedAlpha` and `summary.concentrationScore = derivedConcentration`
5. Update `generateCacheKey()` to include alpha + concentration in the content hash

**Files:**
- `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` — add fields to interface + extraction logic

### 2. Thread through Container to Component (LOW)

**Fix:** Pass new fields from adapter through container to component.

In `PortfolioOverviewContainer.tsx`, add to `portfolioOverviewData.summary`:
```typescript
alphaAnnual: Number(data.summary?.alphaAnnual ?? 0),
concentrationScore: Number(data.summary?.concentrationScore ?? 0),
```

Also update the summary type in PortfolioOverview's props interface.

**Files:**
- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

### 3. Replace Alpha & ESG Metric Cards (MEDIUM)

**Fix:** In `PortfolioOverview.tsx`, replace the two placeholder metric cards:

**Update component props type** (around line 310):
- Add `alphaAnnual: number` and `concentrationScore: number` to the summary type in `PortfolioOverviewProps`

**Alpha Generation card (lines 517-539):**
- `value`: `formatPercent(summary.alphaAnnual, { decimals: 1, sign: true })` (e.g. "+2.5%")
- `rawValue`: `summary.alphaAnnual`
- `change`: Quality label: > 2 "Strong Alpha", > 0 "Positive", ≤ 0 "Underperforming"
- `changeType`: positive if alpha > 0, negative if ≤ 0
- `icon`: Brain (keep existing)
- `description`: "excess return vs benchmark"

**Concentration card (replaces ESG, lines 540-562):**
- `title`: "Concentration"
- `value`: `formatNumber(summary.concentrationScore, { decimals: 0 })` + "/100"
- `rawValue`: `summary.concentrationScore`
- `change`: Risk label (HIGHER = SAFER): ≥70 "Well Diversified", ≥40 "Moderate", <40 "Concentrated"
- `changeType`: "positive" if ≥70, "warning" if ≥40, "negative" if <40
- `icon`: Replace `Award` with `PieChart` (from lucide-react)
- `description`: "portfolio diversification score"

**Import changes:**
- Remove `Award` from lucide-react imports
- Add `PieChart` to lucide-react imports

**Files:**
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

### 4. Dead Code Cleanup (LOW)

**ONLY remove `_prefixed` variables that are truly unused.** The values (without underscore prefix) ARE used in render logic.

Remove from `PortfolioOverview.tsx`:

**Unused `_prefixed` setters (the state values ARE used, only the setters are dead):**
- `_setRealTimeEnabled` (line 353)
- `_setStreamingData` (line 355)
- `_setMarketMode` (line 356)
- `_setAdvancedMode` (line 361 — note: `advancedMode` value IS used)
- `_setAlertsEnabled` (line 364)

**Unused read value (setter IS called, but value never consumed):**
- `_lastMarketUpdate` (line 354) — value never read. `setLastMarketUpdate` IS called (lines 603, 646) so keep the setter; just note the value is unused (leave as-is, cosmetic only)

**Unused destructured props:**
- `_onRefresh`, `_loading`, `_className` (lines 337-339)

**Stale TODOs in JSDoc (lines 86-91):**
- 6 TODOs saying "TODO:ADD to PortfolioSummaryAdapter" for fields that ARE already wired

**DO NOT remove:** `realTimeEnabled`, `streamingData`, `marketMode`, `advancedMode`, `alertsEnabled`, `displaySettings`, `refreshSettings`, `alertSettings`, `chartSettings`, `exportSettings` — these values and/or their setters are used in render logic.

**Files:**
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

## Implementation Order

1. PortfolioSummaryAdapter — add alpha + concentration extraction
2. PortfolioOverviewContainer — thread new fields
3. PortfolioOverview — update props type, replace Alpha/ESG cards, update imports
4. PortfolioOverview — dead code cleanup (only _prefixed unused items)

## Key Files Reference

| File | Role |
|------|------|
| `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` | Adapter — multi-source aggregation, add alpha + concentration fields |
| `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx` | Container — threads adapter output to component props |
| `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` | Component — 6 metric cards, replace Alpha/ESG + cleanup dead code |
| `frontend/packages/connectors/src/features/portfolio/hooks/usePortfolioSummary.ts` | Hook — already fetches riskScore + riskAnalysis + performance (NO CHANGES NEEDED) |
| `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` | Reference — alpha at `performanceSummary.riskMetrics.alpha` (line 796, already ×100, defaults to 0) |
| `frontend/packages/connectors/src/adapters/RiskScoreAdapter.ts` | Reference — concentration at `component_scores[].score` where `name === "Concentration Risk"` (display name, not snake_case) |

## Verification

1. Frontend typecheck: `cd frontend && pnpm typecheck`
2. Frontend lint: `cd frontend && pnpm lint`
3. Frontend tests: `cd frontend && pnpm test`
4. Manual: Load Portfolio Overview → verify Alpha card shows real percent value, Concentration card shows score 0-100 with diversification label
5. Verify existing 4 cards (Total Value, Daily P&L, Risk Score, Sharpe) still render correctly
