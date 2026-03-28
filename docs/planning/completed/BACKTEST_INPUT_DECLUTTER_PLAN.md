# Backtest Input Card — Declutter & Simplify

## Context

The backtest input card (committed in `01c92cc2`) has the compact layout working but still feels cluttered and unintuitive. 6 distinct visual blocks when it should feel like 3. Specific problems:
- "Full Allocation / Changes from Current" toggle in header — advanced feature given prime visual weight
- "Resolved Allocation" heading is jargon
- "Weight sum 100%" badge duplicates "Total: 100.0%" in inline stats
- "Build with AI" floats alone between presets and controls
- 2-line subtitle nobody reads
- "STRATEGY PRESETS" uppercase label is unnecessary

## File to Modify

`frontend/packages/ui/src/components/portfolio/scenarios/tools/BacktestTool.tsx`

## Changes

### 1. Remove mode toggle from header

Delete the `ToggleGroup` for `inputMode` from `CardHeader`. The mode switch moves into the expanded weight table's `CollapsibleContent`, replacing the existing "Add ticker in Full Allocation" button text when in delta mode. The current code already has `{inputMode === "deltas" ? "Add ticker in Full Allocation" : "Add ticker"}` — this implicitly switches modes. Add a dedicated ghost button next to it for explicit mode switching:

```jsx
<Button variant="ghost" onClick={() => handleInputModeChange(inputMode === "weights" ? "deltas" : "weights")} className="rounded-full text-sm text-muted-foreground">
  {inputMode === "deltas" ? "Switch to full allocation" : "Adjust from current holdings"}
</Button>
```

**Auto-expand on cached delta mode**: When `inputMode` is restored from cache as `"deltas"`, auto-expand the weight table so the mode switch link is visible. Add to the mount-time expansion effect: `if (validUiCache?.inputMode === "deltas") setIsWeightTableExpanded(true)`.

The delta card still renders in its current position when `inputMode === "deltas"`. Only the header toggle is removed.

### 2. Move "Build with AI" into presets row

Delete the standalone "Build with AI" section (L866-885 — the `div.flex.flex-wrap` containing the button and delta mode hint text). Place the button inside the presets `flex flex-wrap` container (L829), after the `ToggleGroup` closing tag and before the Imported/Custom indicators. Keep `variant="outline"` and `rounded-full` styling to distinguish it from the preset selections.

The delta mode hint text (`"Delta mode always resolves from your current portfolio weights."`) moves into the delta card's `CardDescription` (append to the existing description text). This hint is important — delta mode ignores presets/imports and always uses `initialWeightRecord`, which is non-obvious. It must remain visible when delta mode is active.

### 3. Remove "STRATEGY PRESETS" label

Delete L828: `<div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Strategy Presets</div>`. The preset pills are self-explanatory as the first content in CardContent.

### 4. Simplify title and subtitle

**Title**: `"Backtest Allocation"` → `"Backtest"`
**Subtitle**: Replace 2-line description (L805-807) with: `"Pick a strategy or adjust weights, then run against a benchmark."`

### 5. Rename heading and remove clutter

- L1072: `"Resolved Allocation"` → `"Allocation"`
- Delete L1073-1075 (subtitle: "Final weights sent to the backtest engine...")
- Delete L1077-1085 (the "Weight sum 100.0%" badge)

### 6. Amber inline stats for off-100%

When `totalAllocated` is off by more than `WEIGHT_WARNING_TOLERANCE`, style the "Total: XX%" portion of the inline stats line (L1101) with `text-amber-700` instead of default `text-muted-foreground`. This replaces the separate badge. The existing text warning inside CollapsibleContent (L1192-1196) stays for the expanded state.

## Target Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Backtest                                                     │
│  Pick a strategy or adjust weights, then run against a        │
│  benchmark.                                                   │
│                                                               │
│  [My Portfolio] [60/40] [All-Weather] [Equal] [Balanced]     │
│  [Top 5] [Build with AI]  ● Custom                           │
│                                                               │
│  BENCHMARK [SPY ▾]  PERIOD [1Y][3Y][5Y][10Y][MAX]  [▶ Run]  │
│                                                               │
│  Allocation                                                   │
│  DSU 28.6%  STWD 12.1%  MSCI 11.7%  ENB 8.1% ...           │
│  27 positions · Largest: 28.6% · Total: 100.0%               │
│  ✏ Edit weights ▾                                            │
└──────────────────────────────────────────────────────────────┘
```

## Implementation Sequence

1. Remove mode toggle from CardHeader
2. Move "Build with AI" button into presets flex container
3. Remove "STRATEGY PRESETS" label
4. Simplify title → "Backtest", subtitle → single line
5. Rename "Resolved Allocation" → "Allocation", delete subtitle and badge
6. Add amber styling to inline stats Total when off-100%
7. Add mode switch link inside CollapsibleContent

## Edge Cases

- **Delta mode access**: Reachable via "Adjust from current holdings" link inside expanded table. Delta card still renders in same position.
- **Cached delta mode**: When `validUiCache?.inputMode === "deltas"`, auto-expand the weight table on mount so the mode switch and delta card are immediately visible. Prevents hidden delta state behind collapsed view.
- **Delta hint text**: Moved to delta card's `CardDescription`, not removed. Important because delta mode always uses `initialWeightRecord` regardless of presets/imports.
- **"Add ticker in Full Allocation"**: Already exists in the button row when in delta mode — the new mode switch link sits next to it. Not redundant: one adds a ticker (switching modes as side effect), the other explicitly switches modes without adding a row.
- **Off-100% warning**: Amber "Total" in inline stats (always visible) + text warning in expanded table (visible when editing)
- **"Build with AI" in presets row**: Same `rounded-full border-input bg-card` styling. The `variant="outline"` distinguishes it from toggle selections.
- **Imported/Custom indicators**: Remain after "Build with AI" in the flex row.
- **`handleInputModeChange`**: Function unchanged, just called from a different UI element.

## Verification

1. No mode toggle in header — just title + subtitle
2. "Build with AI" in the presets row, not standalone
3. No "STRATEGY PRESETS" label
4. Heading says "Allocation" — no subtitle, no badge
5. Expand table → "Adjust from current holdings" link present
6. Click it → delta card appears, link says "Switch to full allocation"
7. Set weights off 100% → "Total" in inline stats turns amber
8. All existing functionality preserved: presets, tooltips, run, exit ramps
