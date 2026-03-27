# What-If Visual Polish Plan

> **Codex review**: R1 FAIL (4). R2 FAIL (2). R3 FAIL (3). R4 FAIL (3). **R5 PASS.**

## Context

The What-If redesign (Phase 1+2) shipped in `278b331c`. The results panel now surfaces rich data (position changes, risk limit checks, factor exposures, violation details) but the visual presentation needs polish. The Chrome audit identified 6 structural issues:

1. **Insight banner text cramped** — title wraps to 3 lines, body text at ~25 chars/line, action buttons disconnected
2. **All sections look the same** — identical white card treatment, no visual hierarchy between primary results and supporting detail
3. **Right panel too dense** — 6 sections stacked requires excessive scrolling
4. **Risk Limit Checks has developer-facing copy** — "Old versus scenario portfolio risk-limit metrics returned by the current API response"
5. **Scenario Results vs Risk Limit Checks feel redundant** — similar data, unclear visual distinction
6. **Section descriptions verbose** — accurate but could be trimmer

## Approach — Polish Fixes (direct edit + Chrome verify)

These are CSS/copy changes within existing components. No new components, no backend changes, no architectural restructuring.

### Fix 1: Collapse secondary sections by default

Risk Limit Checks, Factor Exposures, and Risk Checks are supporting detail — they should start collapsed so the primary results (Scenario Results + Position Changes) dominate. Users who want the detail can expand.

- **RiskLimitChecksSection**: Add a whole-section collapsible (new pattern — PositionChangesSection only truncates rows, not the whole section). When collapsed: show card header with title + "Show details ↓" button, hide the table. When expanded: show the full table + "Hide ↑" button. Start collapsed by default.
- **FactorExposuresSection**: Same whole-section collapsible as RiskLimitChecksSection. Currently it only truncates overflow rows — change to collapse the entire table. Start collapsed by default.
- **RiskChecksSection**: Already has collapsible sub-sections with auto-expand on violations. No changes needed.

**Failure-state rule**: When violations exist (totalViolationCount > 0), Risk Limit Checks and Factor Exposures should **auto-expand** to surface relevant detail. Use an **effect-driven pattern**, not a one-time `defaultExpanded` prop — violations can change across re-runs without remounting (user runs clean scenario, then failing scenario in the same session).

Implementation: Each section accepts a `hasViolations: boolean` prop from WhatIfTool. WhatIfTool passes `totalViolationCount > 0` (both sections expand together on any violation — this is intentional since Risk Limit Checks shows the limit-specific detail and Factor Exposures shows which factors shifted, both useful context when something fails). Internally:

```ts
const [isExpanded, setIsExpanded] = useState(false)
const prevHasViolations = useRef(false)

useEffect(() => {
  if (hasViolations && !prevHasViolations.current) {
    setIsExpanded(true)
  }
  prevHasViolations.current = hasViolations
}, [hasViolations])
```

This tracks the **transition** from no-violations to violations (not the count value), so it reliably re-expands on a new failing run even if previous run also had violations (the `false→true` transition is guaranteed across clean→failing runs). It does NOT force-collapse on clean runs.

**Render order**: The actual render order in `WhatIfTool.tsx` (lines 790-830) is: ScenarioResultsPanel → RiskLimitChecksSection → PositionChangesSection → FactorExposuresSection → RiskChecksSection. Reorder to put Position Changes before Risk Limit Checks since it's more important:

```
Insight Banner (fixed top)
├── Scenario Results (4 metrics, always visible)
├── Position Changes (top 5 visible, "Show all" for overflow)
├── Risk Limit Checks (collapsed by default, auto-expands on violations)
├── Factor Exposures (collapsed by default, auto-expands on violations)
├── Risk Checks (summary visible, detail sub-sections collapsible)
Exit Ramps (fixed footer)
```

**Files**: `RiskLimitChecksSection.tsx`, `FactorExposuresSection.tsx`, `WhatIfTool.tsx` (reorder sections)

### Fix 2: Visual hierarchy — primary vs secondary sections

Give the Scenario Results card more visual weight and demote supporting sections:

- **Scenario Results**: The card wrapper lives in `ScenarioResultsPanel.tsx:76`, not WhatIfTool. Add an optional `className` prop to `ScenarioResultsPanel` and pass a tint from WhatIfTool keyed off the existing `scenarioInsight.colorScheme` (which is already computed from violations/improvements at lines 460-510). When `colorScheme === "emerald"` → `bg-emerald-50/30`, when `"amber"` or `"red"` → `bg-amber-50/30`, otherwise no tint. This reuses the existing signal rather than re-deriving "improving" from individual metrics (factor variance and idiosyncratic variance always move inversely, making "all improving" unreachable).
- **Collapsed secondary sections** (Risk Limit Checks, Factor Exposures): Use reduced opacity card treatment — `opacity-80` on the card when collapsed, full opacity when expanded. Do NOT use dashed borders — in this codebase, dashed cards signal empty/inactive states (confirmed by `ScenarioResultsPanel.tsx:88` and `HedgeTool.tsx:194`).
- **Position Changes**: Keep current card treatment — it's the second-most-important section.

**Files**: `ScenarioResultsPanel.tsx` (add className prop), `WhatIfTool.tsx` (pass tint className), `RiskLimitChecksSection.tsx`, `FactorExposuresSection.tsx`

### Fix 3: Clean up section copy

Replace developer-facing descriptions with user-facing copy:

| Section | Current | Proposed |
|---------|---------|----------|
| Risk Limit Checks | "Old versus scenario portfolio risk-limit metrics returned by the current API response." | "How risk metrics compare against portfolio limits." |
| Position Changes | "Before and after target weights, ranked by the largest absolute moves." | "Largest weight changes in the scenario." |
| Factor Exposures | "Current versus scenario factor betas, ordered by the largest delta." | "Factor exposure shifts, largest first." |
| Risk Checks | "Portfolio guardrails across risk limits, factor betas, and proxy exposures." | Keep — this is already user-facing. |
| Scenario Results empty state | "Run a simulation to see projected volatility, concentration, factor variance, and idiosyncratic variance." | "Run a simulation to see how your changes affect portfolio risk." |

**Files**: `RiskLimitChecksSection.tsx`, `PositionChangesSection.tsx`, `FactorExposuresSection.tsx`, `WhatIfTool.tsx`

### Fix 4: Insight banner sizing

The insight banner text wraps poorly in the narrow right column. The `ScenarioInsightCard` wraps `InsightBanner` which has its own internal layout. The fix is to use `size="lg"` on the InsightBanner to give it more breathing room, and shorten the body text:

- Use `size="lg"` prop on `ScenarioInsightCard` (if supported) or adjust the body text to be shorter
- Shorten insight body: "Volatility -5.0%, concentration -49.5% (HHI 0.152→0.077). All checks passed." (drop the "Backtest this to confirm..." — the button is right there)
- The title can stay as-is

**Files**: `WhatIfTool.tsx` (insight body generation at lines ~460-510)

### ~~Fix 5: Tighten exit ramp footer~~ **DROPPED (R4 finding #3)**

The footer already has `xl:border-t` (`WhatIfTool.tsx:822`) and the test asserts it (`WhatIfTool.test.tsx:334`). No change needed.

## Key Files

| File | Changes |
|------|---------|
| `frontend/.../tools/WhatIfTool.tsx` | Fix 1 (reorder sections, pass `hasViolations` boolean to sections), Fix 2 (Scenario Results tint via `scenarioInsight.colorScheme`), Fix 3 (empty state copy), Fix 4 (insight body + size="lg") |
| `frontend/.../shared/ScenarioResultsPanel.tsx` | Fix 2 (add optional className prop for tint passthrough) |
| `frontend/.../tools/whatif/RiskLimitChecksSection.tsx` | Fix 1 (whole-section collapsible + effect-driven expand via `hasViolations` boolean), Fix 2 (opacity treatment), Fix 3 (copy) |
| `frontend/.../tools/whatif/FactorExposuresSection.tsx` | Fix 1 (whole-section collapsible + effect-driven expand via `hasViolations` boolean), Fix 2 (opacity treatment), Fix 3 (copy) |
| `frontend/.../tools/whatif/PositionChangesSection.tsx` | Fix 3 (copy) |
| `frontend/.../tools/__tests__/WhatIfTool.test.tsx` | Update existing assertions (expand-before-assert, footer border class). Add new tests: (1) Risk Limit Checks + Factor Exposures start collapsed when violationCount=0, (2) **rerender test**: render with violationCount=0 (collapsed), then rerender with violationCount>0 WITHOUT remounting — assert sections expand. This pins down the cross-run regression path. (3) sections stay expanded after manual expand followed by rerender with violationCount=0 |

## What's NOT in Scope

- Insight banner layout restructure (would need changes to shared `InsightBanner` block)
- Before/after bar chart visualization (deferred to future visual enhancement)
- Position Changes color semantics (contextual good/bad vs directional — needs design decision)

## Verification

1. **TypeScript**: `cd frontend && pnpm exec tsc --noEmit`
2. **Tests**: `cd frontend && pnpm exec vitest run packages/ui/src/components/portfolio/scenarios/tools/__tests__/WhatIfTool.test.tsx`
3. **Browser** (Chrome at `localhost:3000/#scenarios/what-if`):
   - Run Equal Weight template
   - Verify: Scenario Results is visually primary (4 metrics prominent)
   - Verify: Risk Limit Checks starts collapsed (title only, one click to expand)
   - Verify: Factor Exposures starts collapsed
   - Verify: Position Changes shows top 5 (not collapsed)
   - Verify: Right panel requires minimal scrolling with sections collapsed
   - Verify: All copy is user-facing, not developer-facing
   - Verify: Insight body text is shorter, doesn't wrap excessively
   - Verify: Exit ramp footer has top border separator
