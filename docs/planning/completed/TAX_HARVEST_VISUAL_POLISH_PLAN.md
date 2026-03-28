# Tax Harvest Tool — Visual Polish Plan

## Context

Tax Harvest Scanner frontend is functionally complete (committed `b01e5c1d` + `613ae48d`). This plan addresses 6 visual polish findings from the Step 6 design review. All are direct-edit items — no backend changes, no new components, no Codex review needed.

---

## Findings & Fixes

### 1. Min loss input oversized
**Problem**: Input stretches full width minus the button (~80% of the card). For a single number field this is excessive.
**Fix**: Constrain the input container to `max-w-[200px]` instead of `flex-1`. Keep the row layout but make the input compact, with the Run button right next to it.

### 2. Insight card title too dense
**Problem**: Title is the full backend verdict string ("$14,668 harvestable losses across 109 lots, 67% data coverage, wash sale risk on 7 tickers") — too long for a headline. Body then repeats wash sale info.
**Fix**: Use a short headline for the title. Move the detailed verdict to the body:
- `candidateCount === 0` → title: "No harvestable losses", body: verdict
- `washSaleTickerCount > 0` → title: `${formatCurrency(totalHarvestableLoss)} in harvestable losses`, body: `${verdict}. Wash sale risk flagged on ${count} ticker(s) — review warnings before selling.`
- Default → title: `${formatCurrency(totalHarvestableLoss)} in harvestable losses`, body: verdict + "Review candidates below."

### 3. System flag overlay makes insight body too long
**Problem**: `applyScenarioSignalToInsight` appends system flag messages to the body, creating a very long block ("+ 4 more" text).
**Fix**: This is inherent to how `applyScenarioSignalToInsight` works across all tools. The real fix is #2 — shortening the base content so the overlay doesn't overflow. No code change needed for this item specifically.

### 4. Candidates card-in-card visual weight
**Problem**: "Candidates" section inside the glass card creates a nested-card look.
**Fix**: Keep the structure (consistent with StressTest position table) but reduce visual weight: remove the Card wrapper from the candidates section. Use a `border-t border-border/50` separator + section title instead. The table rows provide enough structure on their own.

### 5. Pre-run duplicate text
**Problem**: "Run the scanner to see tax-loss candidates" appears in both CardDescription and the dashed placeholder box.
**Fix**: Make CardDescription dynamic — show "Run the scanner to see tax-loss candidates" only pre-run. Post-run, show the "Top X tickers from Y lots" text. Remove the duplicate from the dashed placeholder, replace with a shorter prompt like "No data yet".

### 6. Exit ramp feels orphaned
**Problem**: "Go to Trading" button below the card with no visual grouping.
**Fix**: Move exit ramps inside the main card's `CardContent`, below the last section, with a `border-t border-border/50 pt-4` separator. Matches how other tools present action buttons within the card flow rather than floating below.

---

## Files Modified

| File | Changes |
|------|---------|
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/TaxHarvestTool.tsx` | All 6 fixes |

## Verification

1. Browser: pre-run state — compact input, no duplicate text, exit ramp inside card
2. Browser: post-run state — short insight title, readable body, no card-in-card heaviness, exit ramp grouped
3. TypeScript: `npx tsc --noEmit` — zero errors
