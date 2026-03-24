# Stress Test Tool Redesign

## Context

The Stress Test tool works end-to-end but the UX needs polish — not a rewrite. The existing elements (severity badge, scenario description, verdict text, metric cards, per-position table, hedge overlay) are all present but poorly weighted visually. The fix is **reweight, simplify, and fix data issues** — not a full rebuild.

## Changes (incremental, not a rewrite)

### Change 1: Promote the verdict

The existing narrative text (line ~250 in StressTestTool.tsx) is rendered in faded gray and easy to miss. Make it prominent:

- Move the verdict text above the metric cards (currently below)
- Use `text-foreground` not `text-muted-foreground`
- Make the portfolio loss number the visual hero — larger font, bold, red for losses
- Keep the existing 4 metric cards (Portfolio Loss, Worst Position, Current Volatility, Systematic Risk) but make Portfolio Loss visually dominant (larger card or hero treatment) and the other 3 secondary

**No new narrative generation needed** — the existing verdict text is already constructed from result data. Just make it visible.

### Change 2: Pin scenario to results

**Bug fix**: When the user changes the dropdown after running, the displayed results are from the previous scenario but the dropdown shows the new selection. The narrative and results must be pinned to the scenario that produced them.

Add `lastRunScenarioId` and `lastRunScenarioName` state. When results load, save which scenario produced them. All result-adjacent outputs must use the pinned scenario, not the live dropdown:

- **Results header/body**: Display pinned scenario name, show indicator if dropdown changed ("Results shown for: Interest Rate Shock — [Re-run with new selection]")
- **Workflow step completion**: The `workflowOutput.summary` string (e.g., "Interest Rate Shock complete") must use `lastRunScenarioName`, not `selectedScenario?.name`
- **Hedge handoff label**: The `onNavigate("hedge")` context label must use `lastRunScenarioName`

This ensures no result-derived output references the wrong scenario after a post-run dropdown change.

### Change 3: Filter position impact table

Currently shows all ~30 positions, most at 0.0% impact. Fix:

- **Sort by contribution** (weight × impact), not raw impact. The position driving the most portfolio damage goes first.
- **Show only positions with `|contribution| > 0.1%`** — typically 3-8 positions
- **Add summary row** at bottom: "Other N positions: combined contribution X%" so the table reconciles with the headline loss
- **"Show all" toggle** expands to full list

### Change 4: Integrate hedge overlay

The hedge overlay card (right sidebar) is disconnected from the results flow. Move it inline below the results, presented as a natural next step:

- Same data as current (`bestHedge` from `useHedgingRecommendations`)
- **Honest framing**: "Portfolio Hedge Suggestion" not "Hedge This Exposure" — since the recommendation is based on overall portfolio risk drivers, not the specific scenario that was run
- Keep "Hedge this risk" exit ramp → navigates to Hedge tool (same as today)
- If no hedge available, show nothing (don't show an empty card)

### Change 5: Fix weight display

Position weights in the per-position table show 0.1% for BXMT (should be ~8.4%). Investigate the source:

- Check if the backend stress test API returns weights in the `position_impacts` array
- Check if `StressTestAdapter` is passing through raw API weights without conversion
- Check if there's a decimal-vs-percent mismatch (0.084 displayed as 0.1% instead of 8.4%)
- Fix at the source (adapter or backend) rather than patching in the component

### Change 6: Failure states

Add explicit handling for:
- **No portfolio loaded**: Show message "Load a portfolio to run stress tests"
- **No results yet**: Current placeholder is fine, keep it
- **`estimatedImpactDollar === null`**: Show percentage only, hide dollar amount in both the hero metric card AND the verdict narrative text (the existing verdict interpolates dollar values — guard both sites)
- **No hedge strategies**: Hide the hedge suggestion card entirely (don't show empty)
- **Empty table after filtering**: Show "No positions had material impact in this scenario"

## What does NOT change

- Scenario dropdown + "Run Stress Test" button — stays as-is
- Scenario severity badge — already exists, keep it
- Exit ramp buttons (Monte Carlo, hedge) — keep existing ones, just reposition hedge inline
- Backend / MCP tools — no changes
- `useStressTest()` / `useStressScenarios()` / `useHedgingRecommendations()` hooks — no changes

## What this does NOT attempt

- **Scenario-specific hedge recommendations** — the hedge hook uses portfolio weights, not stressed exposures. Connecting them would require a backend change. Acknowledged and deferred.
- **Industry/factor attribution in narrative** — `riskContext` doesn't carry industry labels. The narrative uses position names and percentages only (which is what the current verdict already does).
- **New narrative generation** — uses the existing verdict construction logic, just promotes it visually.
- **Cross-tool action routing** — the existing exit ramps (`onNavigate("hedge")`, `onNavigate("monte-carlo")`) already work. No changes to routing.

## Files to modify

1. `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx` — reweight layout, pin scenario, filter table, move hedge inline, failure states
2. `frontend/packages/connectors/src/adapters/StressTestAdapter.ts` — investigate + fix weight display bug

## Verification

1. Run "Interest Rate Shock" → verdict text is prominent (not faded), Portfolio Loss is the hero number
2. Change dropdown after running → results still show "Interest Rate Shock" results with "Re-run" indicator
3. Position table shows 3-8 rows sorted by contribution, "Other N positions" summary row, "Show all" toggle
4. Hedge suggestion appears inline below results (not sidebar), with honest "Portfolio Hedge Suggestion" label
5. No portfolio → shows "Load a portfolio" message
6. No hedge strategies → hedge card hidden
7. BXMT weight displays correctly (~8.4%, not 0.1%)
8. Works within "Recession Prep" workflow (progress bar visible)
