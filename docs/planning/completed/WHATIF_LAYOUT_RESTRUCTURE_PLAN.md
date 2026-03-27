# What-If Layout Restructure Plan

> **Codex review**: R1 FAIL (4). R2 FAIL (2). **R3 PASS.**

## Context

User feedback after the What-If redesign + visual polish (commits `278b331c`, `fa5bf670`):

1. **Input panel dominates results** — the weight table sprawls while results are cramped in a sticky card
2. **Templates are the primary input** — weight table is rarely used directly; templates and AI handle allocation
3. **Insight card: too many CTAs** — "Ask AI" should be the only action; "Backtest this" belongs with exit ramps
4. **Risk Checks: cards-in-cards looks off** — the three inner bordered cards (Risk Limits, Beta Checks, Violations) feel heavy inside the outer card
5. **Insight copy restates data, not insight** — "Volatility -5.0%, concentration -49.5%" just repeats the table below. Should explain *why* the numbers changed.

**Tool purpose**: "If I change my portfolio, how does risk/return change?" The tool should be results-oriented — setup should be frictionless (click template, done), results should dominate.

## Approach — 5 Fixes

### Fix 1: Collapse the weight table, promote templates

The weight table is the least-used input path (templates > AI > manual). Collapse it like the Backtest tool does (`BacktestTool.tsx:1139` uses `Collapsible` from radix-ui).

**Before**: Title + Description + Weights/Deltas toggle + full weight table (14+ rows) + Add ticker + Reset + Templates + Run

**After**:
```
Templates:  [Equal Weight] [Conservative] [Risk Parity] [Concentrated] [Hedge]
            [Build with AI →]  [▶ Run Simulation]

[Weights | Deltas]                                    ← toggle OUTSIDE trigger
▸ Edit allocation (14 tickers)   Total: 100.0%        ← trigger (weights mode)
▸ Edit deltas (0 changes)                             ← trigger (deltas mode, no total badge)
  ┌─────────────────────────────────────────────────┐
  │  (collapsed by default — Collapsible)           │
  │  AAPL  2.1%  7.14    ×                          │
  │  ...                                            │
  │  + Add ticker   ↺ Reset to portfolio            │
  └─────────────────────────────────────────────────┘
```

- Templates + Run Simulation move **above** the weight table
- **Weights/Deltas toggle is placed OUTSIDE the `CollapsibleTrigger`** — above the trigger row. Putting interactive toggles inside a trigger button is invalid HTML nesting (`<button>` inside `<button>`). The toggle is a sibling, not a child.
- Weight table wrapped in `Collapsible` (import from `../../ui/collapsible`, same as `BacktestTool.tsx:19`), starts collapsed
- Collapsible trigger is a simple button showing mode-aware text:
  - Weights mode: "Edit allocation (N tickers)" + Total badge
  - Deltas mode: "Edit deltas (N changes)" — NO Total badge (deltas don't sum to 100%)
- **Template click auto-collapses + mode-syncs**: When `handleTemplateRun` fires: (1) set `isWeightTableExpanded = false` to collapse the table, and (2) the collapsible header must reflect the template's mode. `handleTemplateRun` already calls `initWeightInputs` (for weight templates) or `initDeltaInputs` (for delta templates like Hedge Overlay), which internally calls `setInputMode('weights'|'deltas')`. So `inputMode` will update correctly and the collapsed header will show the right text. No additional mode-switch logic needed — just verify the collapsible header reads from `inputMode`.
- "Build with AI →" button next to templates (uses existing `openScenarioChat` from `useScenarioChatLauncher`)
- Description text shortened: "Choose a template or edit weights to test a scenario."

**Files**: `WhatIfTool.tsx`

### Fix 2: Give results more column space

The current grid is `xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]` — inputs get 55%, results get 45%. With the weight table collapsed, the input card will be much shorter. Flip the ratio so results get more space:

- Change to `xl:grid-cols-[minmax(300px,0.8fr)_minmax(0,1.2fr)]` — inputs get 40%, results get 60%
- This gives the results panel significantly more horizontal room, reducing text wrapping in the insight banner and tables

**Files**: `WhatIfTool.tsx` (line 574, grid-cols definition)

### Fix 3: Insight card — single CTA + interpretive copy

**Single CTA**: Remove `actionLabel` ("Backtest this") from `ScenarioInsightCard`. Promote "Ask AI about this" from `secondaryActionLabel` to `actionLabel` so it renders with the more prominent outline styling instead of the ghost secondary treatment (`ScenarioInsightCard.tsx:34` vs `:38`). "Backtest this" is already in the exit ramp footer.

**Interpretive copy**: Replace the data-restating body with an interpretive sentence derived from:
- `factor_exposures_comparison` — top factor delta (tells *why* risk changed)
- `position_changes` — top mover (tells *what* drove it)
- The verdict (improves/increases/marginal)

**Interpretive copy structure** (3 branches):

- **Pass** (no violations): Combine top position mover + top factor delta into a causal sentence. Example: "Equal weighting halves concentration by spreading weight from NVDA (-13.5pp). Market beta drops 0.33 as no single stock dominates."

- **Fail** (violations exist): Lead with the violation-specific detail from `failingMetricNames` (already extracted at `WhatIfTool.tsx:473` from `risk_analysis.risk_violations` + `beta_analysis.*_violations`), then add factor context. Example: "Annual Volatility exceeds the 20% limit. Market exposure increases 0.4 from heavy NVDA weighting." The current code already extracts `failingMetricNames` and `totalViolationCount` — the interpretive copy builder must consume these alongside factor/position data.

- **Marginal** (is_marginal flag from verdict): "Minor weight shifts — risk profile is essentially unchanged."

The key difference from current copy: instead of restating "Volatility -5.0%, concentration -49.5%", explain *why* via the top factor delta and top mover. Keep violation-specific names for failures.

**Parsing approach**: The raw `factor_exposures_comparison` and `position_changes` from the API response are `unknown` typed in WhatIfTool. The sorting/normalization logic currently lives inside the child sections (`FactorExposuresSection.tsx:31`, `PositionChangesSection.tsx:35`). To avoid duplicating that parsing:

1. **Extract shared parsers** into small utility functions (e.g., `getTopFactorDelta(factorData: unknown): {factor: string, delta: number} | null` and `getTopPositionChange(positionData: unknown): {ticker: string, changePct: number} | null`)
2. Place these in `whatif/helpers.ts` (new file) so both the insight builder and the child sections can reuse them
3. These parsers must handle: `factor_exposures_comparison` being a `Record<string, {current, scenario, delta}>` OR missing (fallback to `factor_comparison` rows), and `position_changes` being an array of `{position, before, after}` objects where `before`/`after` may be numbers or formatted strings like `"21.2%"`
4. If parsing fails or data is missing, fall back to the current data-restating copy (graceful degradation)

**Files**: `WhatIfTool.tsx` (insight body), new `whatif/helpers.ts` (shared parsers)

### Fix 4: Risk Checks — inline stats, no nested cards

Replace the three bordered inner cards (Risk Limits / Beta Checks / Violations) with a simple inline stat row:

**Before**: Three `rounded-2xl border border-border bg-card px-4 py-3` cards inside the Risk Checks card

**After**: A flex row with dividers:
```
Risk Limits: Pass  |  Beta Checks: Pass  |  Violations: 0
```

Use a `flex gap-6` row with pipe dividers or subtle `border-r` separators. Each stat is label (uppercase muted) + value (colored). No card wrapper, no padding boxes. This is the same density but without the visual weight of nested borders.

**Files**: `whatif/RiskChecksSection.tsx`

### Fix 5: "Backtest this" moves to exit ramp footer

The insight banner no longer has "Backtest this". Ensure it's prominently available in the exit ramp footer (it already is — just verify it's there and potentially give it primary visual weight as the most common next step).

**Files**: `WhatIfTool.tsx` (verify exit ramp footer, no change expected)

## Key Files

| File | Changes |
|------|---------|
| `frontend/.../tools/WhatIfTool.tsx` | Fix 1 (collapsible weight table, templates promoted, auto-collapse on template run), Fix 2 (grid ratio), Fix 3 (insight copy + single CTA promoted to actionLabel), Fix 5 (verify) |
| `frontend/.../tools/whatif/RiskChecksSection.tsx` | Fix 4 (inline stats replacing nested cards) |
| `frontend/.../tools/whatif/helpers.ts` | **NEW** — shared parsers: `getTopFactorDelta()`, `getTopPositionChange()` for interpretive copy |
| `frontend/.../tools/__tests__/WhatIfTool.test.tsx` | Update assertions: collapsible default state, expand/collapse, delta-mode trigger text, template auto-collapse, single CTA, interpretive copy with/without factor data, Build with AI button |

## What's NOT in Scope

- Backend changes for insight generation (frontend derives from existing API data)
- Template redesign (templates themselves are fine — just promoting their position)
- Mobile/responsive layout changes (scoped to xl: as before)

## Verification

1. **TypeScript**: `cd frontend && pnpm exec tsc --noEmit`
2. **Tests**: `cd frontend && pnpm exec vitest run packages/ui/src/components/portfolio/scenarios/tools/__tests__/WhatIfTool.test.tsx`
3. **Browser** (`localhost:3000/#scenarios/what-if`):
   - Verify templates + Run button are above the fold, weight table collapsed
   - Click "Edit weights" — table expands with full ticker list
   - Run Equal Weight — results panel dominates with more horizontal space
   - Insight banner shows interpretive copy (not data restating), single "Ask AI" CTA
   - Risk Checks shows inline Pass/Pass/0 row, no nested cards
   - "Backtest this" is in the exit ramp footer, not the insight banner
   - Scroll through inputs — results stay sticky and readable
