# Backtest Tool — Compact Layout Redesign

## Context

The backtest tool's input card is dominated by a 27-row editable weight table (~1400px tall), pushing the Run Backtest button, benchmark/period controls, and results below the fold. The primary action and output are invisible without scrolling past the entire table. The fix: default to a compact chip-based summary, reorder controls above the table, and visually differentiate the results card.

## Files to Modify

| File | Changes |
|------|---------|
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/BacktestTool.tsx` | Layout reorder, collapsible weight table, compact summary chips, preset tooltips, remove summary stats grid |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/BacktestResults.tsx` | Card variant change (1 line) |

## Changes

### 1. Collapsible Weight Table with Compact Summary (P0)

**Default state**: Collapsed. Show a chip-based summary instead of the full editable table.

**Compact view** (visible when collapsed):
- Flex-wrap chip list sorted by weight descending, reusing the existing delta-preview chip pattern: `rounded-full border border-border bg-muted px-3 py-1 text-sm`
- Inline stats below chips: `"27 positions · Largest: 28.6% · Total: 100.0%"` — replaces the current 3-tile summary grid entirely

**Expand trigger**: Collapsible trigger button below the chips:
```
[Pencil icon] Edit weights [ChevronDown]
```
Matches the MonteCarloTool "Advanced options" pattern (L536-544).

**Auto-behavior** (full state machine — all paths that change allocation):
- `handlePresetChange` → collapse (user picked a preset, no need to edit)
- `updateRows` with manual edit → expand (user is editing)
- "Add ticker" click → expand
- Empty weights → expand by default
- Context seed effect (L372, `context.weights` / `initialWeightRecord`) → collapse (fresh seed = clean state, user can expand to review)
- `handleInputModeChange` (L550) → no change (preserve current expand/collapse state across mode switch)
- **Cached incomplete rows**: On mount, if `rows` from `validUiCache` contain entries where ticker is non-empty but weight is empty (or vice versa), expand by default — prevents hiding partial manual edits behind the compact view. Check: `rows.some(r => (r.ticker.trim() && !r.weight.trim()) || (!r.ticker.trim() && r.weight.trim()))`

**New state**: `const [isWeightTableExpanded, setIsWeightTableExpanded] = useState(false)` — transient, not persisted in `BacktestUiCache`.

**New memo**: `sortedWeightEntries` = `Object.entries(activeWeights).sort((a, b) => b[1] - a[1])`

**Structure**:
```jsx
<div> {/* Resolved Allocation section */}
  {/* Header + weight sum badge (always visible) */}
  {/* Compact chips + inline stats (visible when collapsed) */}
  <Collapsible open={isWeightTableExpanded} onOpenChange={setIsWeightTableExpanded}>
    <CollapsibleTrigger> "Edit weights" / "Collapse table" </CollapsibleTrigger>
    <CollapsibleContent>
      {/* Existing weight table grid */}
      {/* "Add ticker" button */}
      {/* Allocation warning */}
    </CollapsibleContent>
  </Collapsible>
</div>
```

### 2. Layout Reorder — Controls Above Table (P1)

Move the Benchmark / Period / Run Backtest row (currently L1062-1111) **above** the Resolved Allocation section (currently L965-1060).

**Before**: Presets → Build with AI → [Delta card] → Weight table → Benchmark/Period/Run → Summary stats
**After**: Presets → Build with AI → [Delta card] → Benchmark/Period/Run → Resolved Allocation (compact) → Error

The 3-tile summary grid (Active Tickers, Largest Weight, Total Allocated) at L1113-1128 is **removed** — its data is integrated into the compact summary inline stats.

### 3. Results Card Visual Differentiation (P1)

`BacktestResults.tsx` L376: Change `variant="glass"` to `variant="glassTinted"` on the outer Card. This uses the existing `glass-tinted shadow` variant from `card.tsx` to give the results card a subtly different background treatment.

### 4. Preset Tooltip Previews (P2)

Wrap each preset `ToggleGroupItem` with `Tooltip`/`TooltipTrigger`/`TooltipContent` from `ui/tooltip.tsx`. Show the preset's composition on hover.

**Important**: `ToggleGroupItem` is a Radix button. Use `TooltipTrigger asChild` wrapping each `ToggleGroupItem` to avoid nested interactive elements. Structure:
```jsx
<TooltipProvider delayDuration={200}>
  {STRATEGY_PRESETS.map((preset) => (
    <Tooltip key={preset.id}>
      <TooltipTrigger asChild>
        <ToggleGroupItem value={preset.id} className="rounded-full px-4 text-sm">
          {preset.label}
        </ToggleGroupItem>
      </TooltipTrigger>
      <TooltipContent side="bottom">{tooltipText}</TooltipContent>
    </Tooltip>
  ))}
</TooltipProvider>
```

Format: `"VTI 60.0%, BND 40.0%"` — data already available from `presetWeightsById[preset.id]`.

For large portfolios (My Portfolio, Equal Weight), show top 5 + `"and N more"`.

Reference pattern: `ExitRampButton.tsx` L38-45 uses `TooltipProvider delayDuration={100}`.

### 5. New Imports

```typescript
// Add to BacktestTool.tsx
import { ChevronDown, Pencil } from "lucide-react"  // ChevronDown may already exist
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../../ui/collapsible"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../../ui/tooltip"
```

## Implementation Sequence

1. Add imports + `isWeightTableExpanded` state + `sortedWeightEntries` memo
2. Reorder JSX: move Benchmark/Period/Run grid above Resolved Allocation
3. Wrap weight table in Collapsible, add compact chip summary outside it
4. Remove 3-tile summary grid, integrate stats inline
5. Wire auto-expand/collapse into all handlers (`handlePresetChange`, `updateRows`, add-ticker, context seed effect, cached incomplete rows on mount)
6. Add Tooltip wrappers to preset ToggleGroupItems
7. Change BacktestResults Card variant to `glassTinted`

## Edge Cases

- **Empty weights**: Show expand trigger with "Add weights" text, auto-expand
- **Delta mode**: The "Changes from Current" card has its own resolved preview chips; the compact Resolved Allocation chips below show the full result — both visible, different purpose
- **Collapsible animation**: Radix default handles 27-row tables fine (same as attribution tables in BacktestResults)
- **UI cache**: No changes to `BacktestUiCache` — `isWeightTableExpanded` is transient
- **Cached incomplete rows**: On mount, detect partial manual entries in cached `rows` and auto-expand to avoid hiding incomplete edits behind compact view
- **Context seed / mode switch**: Context seed effect collapses (fresh data); `handleInputModeChange` preserves current state (don't fight the user)

## Verification

1. Navigate to `localhost:3000/#scenarios/backtest`
2. Verify default state shows compact chips, not full table
3. Verify Run Backtest button + benchmark/period are visible without scrolling
4. Click "Edit weights" — table expands, "Collapse table" shown
5. Select a preset — table collapses back
6. Hover a preset — tooltip shows composition
7. Run a backtest — verify results card has `glassTinted` visual treatment
8. Test delta mode — both chip previews visible
9. Test "Add ticker" — table auto-expands
10. Navigate away and back — weights preserved (UI cache unchanged)
