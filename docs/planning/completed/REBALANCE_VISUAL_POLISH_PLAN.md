# Rebalance Tool Visual Polish Plan

## Context

The rebalance tool's 3-phase redesign (Diagnose → Select Targets → Review Trades) has been implemented and is functional. This plan addresses visual polish issues identified during the Step 5b browser walkthrough — matching the quality bar set by other polished scenario tools (Monte Carlo, Optimization, Backtest).

All changes are frontend-only, no backend work needed.

---

## Fixes

### Fix 1: Remove "Phase N:" prefixes from section headers
**Files**: `rebalance/RebalanceDiagnostic.tsx`, `rebalance/RebalanceTargets.tsx`, `rebalance/RebalanceResults.tsx`

The `Phase 1:`, `Phase 2:`, `Phase 3:` prefixes are developer-facing. No other scenario tool numbers its sections. Change to purpose-driven titles:
- "Phase 1: Diagnose Allocation" → "Allocation Health"
- "Phase 2: Select Targets" → "Rebalance Targets"
- "Phase 3: Review Trades" → "Rebalance Trades"

**Note (from Codex review)**: The `RebalanceInsightCard` inside Phase 3 already has `title="Trade Preview"`. Using "Trade Preview" as the section header would create duplicate adjacent titles. Use "Rebalance Trades" instead to differentiate the section header from the insight card title.

Also remove the tutorial-style subtitle paragraphs ("Start with the portfolio's biggest..."), ("Compare the current allocation..."), ("Inspect the generated trade set..."). These read like instructions rather than results. The insight cards and the UI itself communicate the purpose. Matches reference tools which don't have instructional subtitles under section headers.

### Fix 2: Factor driver strip — human-readable labels + filter zero values
**Files**: `rebalance/FactorDriverStrip.tsx`, `rebalance/helpers.ts`

Currently shows raw factor keys (`rate_10y`, `momentum`) and includes zero-value entries (`OT: market 0 · momentum 0`). Fix:

1. Add `FACTOR_LABELS` map to `helpers.ts`:
   ```
   rate_10y → "10Y Rate", rate_30y → "30Y Rate", market → "Market",
   momentum → "Momentum", value → "Value", size → "Size",
   volatility → "Volatility", quality → "Quality", credit → "Credit"
   ```
   Add `formatFactorName()` helper that falls back to title-casing the raw key.

2. In `FactorDriverStrip.tsx`, filter out factors where `Math.abs(beta) < 0.01` before slicing to top 2. This removes the zero-value entries.

3. Use full asset class name instead of abbreviation for clarity: "Real Estate:" instead of "RE:". The abbreviations are cryptic.

### Fix 3: Risk vs. Weight chart — add percentage labels to bar ends
**File**: `rebalance/RiskWeightChart.tsx`

The `renderValueLabel` function already renders `risk% / weight%` at the end of each pair. Looking at the code, labels are only on the `risk_pct` bar via the Recharts `label` prop. The values ARE showing (confirmed in accessibility tree) but may be getting clipped or positioned off-screen for smaller bars.

Investigate and fix: ensure the labels render visibly for all asset classes, including those with very small bars (Cash, Commodities). The current right margin of 110 should be sufficient. May need to adjust positioning for near-zero bars to avoid overlap with the axis.

### Fix 4: Trade table truncation
**File**: `rebalance/TradeTable.tsx`

24 rows showing uncollapsed pushes the action bar off screen. Add truncation matching the optimization tool's `WeightChangesTable.tsx` pattern:

- `INITIAL_VISIBLE = 10`
- Show first 10 rows by default
- Toggle button: "Show all 24" / "Show top 10"
- Button styled as `variant="ghost" size="sm"` centered below table

### ~~Fix 5: Hide Custom Targets editor when not selected~~ — DROPPED

Investigated during Codex review: the conditional gating at `RebalanceTargets.tsx:79` is correct (`selectedPreset?.id === "custom"`). The fallback chain in `RebalanceTool.tsx:323-330` is `cached → optimizer → currentTargets → templates[0] → custom`, so "custom" is only selected as a last resort. The editor appearing in the walkthrough was because "Custom" was the initially cached preset from a prior session. No code change needed.

### Fix 5 (renumbered): Swap arrows (⇆) in comparison table — visual noise
**File**: `rebalance/AllocationCompare.tsx`

The swap arrows between Current and Target columns add visual noise without being interactive. Remove them — the column headers "Current" and "Target" are sufficient context. Replace the arrow column with slightly more space between the two number columns.

---

## Files to Modify

All paths relative to `frontend/packages/ui/src/components/portfolio/scenarios/tools/`:

| File | Fix |
|------|-----|
| `rebalance/RebalanceDiagnostic.tsx` | Fix 1: rename header, remove subtitle |
| `rebalance/RebalanceTargets.tsx` | Fix 1: rename header, remove subtitle |
| `rebalance/RebalanceResults.tsx` | Fix 1: rename header, remove subtitle |
| `rebalance/helpers.ts` | Fix 2: add FACTOR_LABELS map + formatFactorName() |
| `rebalance/FactorDriverStrip.tsx` | Fix 2: human-readable labels, filter zeros, full asset class name |
| `rebalance/RiskWeightChart.tsx` | Fix 3: investigate and fix bar-end label visibility |
| `rebalance/TradeTable.tsx` | Fix 4: add INITIAL_VISIBLE truncation |
| `rebalance/AllocationCompare.tsx` | Fix 5: remove swap arrows |

## Existing Patterns to Reuse

- **Table truncation**: `optimize/WeightChangesTable.tsx` lines 18, 66, 80-83 — `INITIAL_VISIBLE = 10`, `isExpanded` state, slice, toggle button
- **Factor labels**: No existing map in the codebase — create new `FACTOR_LABELS` + `formatFactorName()` in `rebalance/helpers.ts`
- **Asset class labels**: Already exists as `ASSET_CLASS_LABELS` in `rebalance/helpers.ts` — use `formatAssetClassName()` instead of `getAssetClassAbbreviation()` in FactorDriverStrip

## Verification

1. **TypeScript**: `cd frontend && npx tsc -b` — zero errors (project uses composite/references, not `--noEmit`)
2. **Browser walkthrough**:
   - Section headers: "Allocation Health", "Rebalance Targets", "Rebalance Trades" (no "Phase N:" prefixes, no subtitle paragraphs)
   - Factor strip: "Real Estate: 10Y Rate -34.32 · 30Y Rate 21.44" (not "RE: rate_10y -34.32"). No zero-value entries (OT row gone).
   - Chart bar labels: visible for all asset classes including small bars
   - Trade table: 10 rows visible + "Show all 24" toggle. Action bar visible without scrolling.
   - Comparison table: no swap arrows
3. **Existing tests**: `npx vitest run --reporter=verbose` on rebalance test files — zero regressions
