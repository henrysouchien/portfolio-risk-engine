# Risk Analysis Card — Formatting & Redundancy Fixes

## Context

The "Advanced Risk Analysis" card on the Overview page has three tabs (Risk Score, Stress Tests, Hedging). Two of the three have rendering issues:
- **Risk Score tab**: Each of the 4 factor cards shows the same score 4 redundant ways (badge, number, impact text, progress bar). The `impact` field just echoes "Concentration risk score: 100/100" which repeats the header.
- **Stress Tests tab**: Raw floats (`-18.504274000000002`) and unformatted probabilities (`0.1`) instead of clean percentages (`-18.5%`, `10%`). Scenario names are lowercase (`market Stress Test`).
- **Hedging tab**: Already fine — data arrives pre-formatted from `useHedgingRecommendations`.

The codebase has centralized formatting utilities in `@risk/chassis` that should be used instead of inline formatters.

## Files to Modify

1. **`frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`** — presentational component (all rendering changes here)

## Existing Utilities to Reuse

- **`formatPercent(value, { decimals?, sign? })`** from `@risk/chassis` (`frontend/packages/chassis/src/utils/formatting.ts:165`)
  - Handles NaN/Infinity → `"—"`, negative zero, locale formatting
  - `formatPercent(-18.5, { decimals: 1 })` → `"-18.5%"`
  - `formatPercent(10, { decimals: 0 })` → `"10%"`
- **`getLevelBadgeClasses(level)`** from `../../lib/colors` — already imported, no change needed

Note: `scenario/helpers.ts` has `formatFactorLabel` for title-casing factor names, but it's tightly coupled to scenario types. The container already has a `toTitleCase` helper (line 164) that handles `_`-separated names, but scenario names arrive with spaces not underscores (e.g., "market Stress Test"), so a simple inline `.replace(/\b\w/g, c => c.toUpperCase())` is sufficient here.

## Changes

### 1. Add `formatPercent` import

```tsx
import { formatPercent } from "@risk/chassis"
```

### 2. Tab 1 (Risk Score) — Remove redundant impact row

**Remove** lines 202-205 (the "Risk Level" / `impact` display):
```tsx
// DELETE this block:
<div className="flex items-center justify-between mb-2">
  <span className="text-xs font-medium text-neutral-500">Risk Level</span>
  <span className="text-sm font-semibold text-red-600">{risk.impact}</span>
</div>
```

The remaining card structure keeps all useful information:
- Header: name + badge + score/100
- Description (from `buildRiskFactorDescription` — the actually useful contextual info)
- Progress bar (visual indicator)
- Expandable: mitigation + timeline

### 3. Tab 2 (Stress Tests) — Format impact, probability, scenario names

**Line 248** — Title-case scenario name:
```tsx
// Before:
<h4 className="font-semibold text-neutral-900 mb-1">{test.scenario}</h4>
// After:
<h4 className="font-semibold text-neutral-900 mb-1">
  {test.scenario.replace(/\b\w/g, (c) => c.toUpperCase())}
</h4>
```

**Line 249** — Format probability (value is 0-1 decimal, multiply by 100):
```tsx
// Before:
<p className="text-xs text-neutral-500">Probability: {test.probability}</p>
// After:
<p className="text-xs text-neutral-500">
  Probability: {formatPercent(test.probability * 100, { decimals: 0 })}
</p>
```

**Line 253** — Format impact (value is already in percentage points):
```tsx
// Before:
<p className="text-xl font-bold text-red-600">{test.impact}</p>
// After:
<p className="text-xl font-bold text-red-600">
  {formatPercent(test.impact, { decimals: 1 })}
</p>
```

### 4. Fix stale `impact` comment in props interface

The `impact` field comment (line 51) says `// Dollar impact (e.g., "$127K")` but the container actually populates it with score text like `"Concentration risk score: 100/100"`. Update the comment to match reality since `impact` is still part of the interface even though the row is removed:
```tsx
// Before:
impact: string;          // Dollar impact (e.g., "$127K")
// After:
impact: string;          // Score summary text (no longer rendered, kept for data contract)
```

### 5. No changes to Tab 3 (Hedging)

### 6. No changes to `RiskAnalysisModernContainer.tsx`

The container's `toPercentLabel` helper duplicates `formatPercent` from chassis, but it works and is only used internally by `buildRiskFactorDescription`. Not worth the churn to refactor now.

## Out of Scope

- **Volatility Risk score = 0/100 "Extreme"** while description says "8.5% - low": This is a backend scoring issue (the `useRiskScore` hook returns 0 for the Volatility Risk component score), not a frontend formatting problem. Flagged for separate investigation.
- **Container NaN guard**: Container checks `typeof loss === 'number'` (line 577) instead of `Number.isFinite(loss)`, so `NaN` could leak through. Low risk since `formatPercent` from chassis handles NaN → `"—"` gracefully. Could tighten later.
- Container `toPercentLabel` → chassis migration (works fine, low value refactor)

## Verification

1. `npx tsc --noEmit` — TypeScript passes
2. Browser: Overview → scroll to "Advanced Risk Analysis" card
   - **Risk Score tab**: Confirm impact row removed, cards show name+badge+score, description, progress bar
   - **Stress Tests tab**: Confirm impacts show as `-18.5%`, probabilities as `10%`, scenario names title-cased
   - **Hedging tab**: Confirm unchanged (still shows pre-formatted cost/protection)
