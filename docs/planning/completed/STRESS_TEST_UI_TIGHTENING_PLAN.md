# Stress Test Tool — UI Tightening (Completed)

## Summary

Full UI overhaul of the StressTestTool component. 13 commits, 771 tests passing, no regressions.

## What Changed

### Header (input area)
- Removed card subtitle and "SCENARIO" label — title + dropdown + Run button on two lines
- Dropdown and Run button inline on same row (was grid with button floating right)
- Severity badge moved inline with description text (was top-right corner)
- Expandable "View assumptions" collapsible below dropdown — shows full factor × shock table per scenario (Radix Collapsible + existing formatFactorLabel/formatShockValue helpers)

### Verdict Card (results)
- Custom gradient card (`bg-gradient-to-br from-{color}-50 to-card`) with shadow-sm
- Title `text-lg`, body `text-sm leading-6` (was `text-lg` / `text-base leading-7`)
- Icon: `h-8 w-8 rounded-xl` badge (was `rounded-full p-2`)
- Single action: "Ask AI about this →" with full scenario context (was two buttons: "Ask AI" + "Run Monte Carlo")
- Monte Carlo references removed from verdict narratives

### Impact Summary
- Unified stat strip replacing 4 separate cards — single container with vertical dividers
- `text-base` values, `text-[10px]` labels, `py-2.5` padding, `tabular-nums`
- Lead metric gets subtle color tint, others neutral

### Position Table
- Row padding `py-3` → `py-2` (matching peer table in stock research)
- Header `text-xs font-semibold` (was `text-[10px]` briefly, reverted)
- `tabular-nums` on all numeric cells, `hover:bg-muted/30` on rows
- Summary row ("Other N positions") consistent font size with body rows

### Hedge Card
- Removed entirely — was generic portfolio-level recommendations unrelated to specific stress scenario
- Exit ramp button "Hedge this risk →" retained for navigation to dedicated Hedge Tool
- Future: scenario-specific hedge recommendations (backend feature, tracked in TODO)

### Spacing
- ScenariosRouter `space-y-6` → `space-y-3` (breadcrumb-to-card gap)
- CardHeader `space-y-4` → `space-y-3 pb-4`

## Files Modified
- `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx` (primary)
- `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx` (spacing only)

## Future Work (tracked in TODO.md)
- Scenario-specific hedge recommendations (backend)
- Pass stress test context to Monte Carlo navigation
