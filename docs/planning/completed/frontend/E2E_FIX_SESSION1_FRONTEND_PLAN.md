# E2E Fix Session 1: Frontend Quick Fixes

**Status**: NOT STARTED
**Date**: 2026-03-16
**Source**: `docs/planning/REVIEW_FINDINGS.md` (R1, R2, R5, R10, R11, R13, R19, R20)
**Scope**: 8 frontend-only fixes across 5 files. No backend changes. No adapter changes.

---

## Overview

This session handles 8 findings from the E2E user-perspective review — all small frontend
changes in mostly different files. The goal is to knock out every quick visual/label win
in a single pass.

| Finding | Severity | File(s) | Summary |
|---------|----------|---------|---------|
| R1 | Medium | `index.css` | Popover transparency — `--popover` CSS var undefined |
| R19 | High | `index.css` | Dark mode partial — text faded/unreadable in content area |
| R5 | High | `useOverviewMetrics.ts` | Risk Score label inversion (89 = "Low Risk") |
| R10 | Medium | `useOverviewMetrics.ts`, `PortfolioOverview.tsx`, `types.ts` | "Across all accounts" subtitle hardcoded |
| R11 | Medium | `PortfolioSelector.tsx` | Internal IDs visible in dropdown |
| R13 | Low | `DashboardHoldingsCard.tsx`, `HoldingsTable.tsx` | Day change rounds to "$0" |
| R20 | Medium | `SettingsPanel.tsx` | "Volatility Alert Level" label says "risk score" |
| R2 | High | `PortfolioOverview.tsx`, `sparkline-chart.tsx` | Performance Trend chart squashed to 80px |

---

## Constraints

- Do NOT touch any backend Python files.
- Do NOT touch adapter files in `frontend/packages/connectors/`.
- Keep changes minimal — fix the issue, don't refactor surrounding code.
- Read each file before editing.
- Run tests after all changes.

---

## Steps

### Step 1 — R1: Add `--popover` / `--popover-foreground` CSS variables

**File**: `frontend/packages/ui/src/index.css`

**Problem**: The `--popover` and `--popover-foreground` CSS variables are never defined.
The shadcn `DropdownMenuContent` component uses `bg-popover` which resolves to
`hsl(var(--popover))` — with no value set, the background is effectively transparent.
Dashboard content bleeds through every dropdown/popover.

**Change**: Add two CSS variables to the `:root` block (light theme, after `--card-foreground`
around line 136) and to the `.dark` block (after `--card-glass` around line 240).

Light theme values (match `--card`):
```css
--popover: 0 0% 100%;              /* White popover background */
--popover-foreground: 213 27% 20%; /* Dark text on popovers */
```

Dark theme values (match `--card`):
```css
--popover: 213 23% 11%;            /* Dark popover background */
--popover-foreground: 210 17% 96%; /* Light text on dark popovers */
```

**Verification**: The `frontend/tailwind.config.js` already maps `popover` to
`hsl(var(--popover))` at lines 20-23, so defining the variable is all that's needed.
Every shadcn popover/dropdown component will pick it up globally.

---

### Step 2 — R19: Audit dark mode `.dark` block for missing/incorrect CSS variables

**File**: `frontend/packages/ui/src/index.css`

**Problem**: Dark mode header/sidebar render correctly but main content text becomes faded.
Company name subtitles and headings become nearly invisible (light gray on near-white).

**Root cause**: The `.dark` block (lines 222-265) is missing shadow variables that some
components reference. More importantly, the existing dark-mode foreground values are
correct (`--foreground: 210 17% 96%`, `--muted-foreground: 210 9% 65%`, etc.) but there
may be component-level hardcoded light-mode colors (e.g., `text-neutral-600`,
`text-neutral-900`) that don't respond to theme changes.

**Change**: Add the missing shadow variables to the `.dark` block so components that use
custom shadows work in dark mode:
```css
/* Shadow hues (DARK THEME) */
--shadow-soft: 213 27% 3%;
--shadow-medium: 213 30% 2%;
--shadow-strong: 0 0% 0%;
```

Note: The primary dark-mode text issue is component-level hardcoded colors like
`text-neutral-900` and `text-neutral-600` that don't switch with the theme. A full fix
requires auditing each component to use semantic classes (`text-foreground`,
`text-muted-foreground`) instead. That is beyond the scope of this quick-fix session.
This step only ensures the CSS variable layer is complete. A follow-up task should
convert hardcoded neutral-* text classes to semantic theme classes.

---

### Step 3 — R5: Fix Risk Score label inversion

**File**: `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts`

**Problem**: Line 51 uses inverted labels:
```typescript
change: summary ? (summary.riskScore >= 80 ? "Low Risk" : summary.riskScore >= 60 ? "Medium Risk" : "High Risk") : ""
```
Risk score is 0-100 where higher = better risk management. The backend
(`core/risk_score_flags.py:48-63`) correctly uses: >= 90 "Excellent", >= 80 "Good",
>= 70 "Moderate", >= 60 "Elevated", < 60 "High Risk". The frontend labels don't match.

**Change**: Replace lines 51-53 with:

```typescript
change: summary
  ? (summary.riskScore >= 90 ? "Excellent"
    : summary.riskScore >= 80 ? "Good"
    : summary.riskScore >= 70 ? "Moderate"
    : summary.riskScore >= 60 ? "Elevated"
    : "High Risk")
  : "",
changeValue: "",
changeType: summary
  ? (summary.riskScore >= 80 ? "positive"
    : summary.riskScore >= 60 ? "warning"
    : "negative")
  : "neutral",
```

This aligns with `core/result_objects/risk.py` scale:
- 90-100: Excellent (positive)
- 80-89: Good (positive)
- 70-79: Moderate (warning)
- 60-69: Elevated (warning)
- <60: High Risk (negative)

---

### Step 4 — R10: Make "Across all accounts" subtitle conditional

**Files**:
- `frontend/packages/ui/src/components/portfolio/overview/types.ts`
- `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts`
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`
- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

**Problem**: The Total Portfolio Value metric card always shows "Across all accounts" even
for single-account portfolios (line 18 of `useOverviewMetrics.ts`).

**Change**:

1. **`types.ts`**: Add optional `portfolioType` and `portfolioDisplayName` fields to
   `PortfolioOverviewProps`:
   ```typescript
   export interface PortfolioOverviewProps {
     // ... existing fields ...
     portfolioType?: string
     portfolioDisplayName?: string
   }
   ```

2. **`useOverviewMetrics.ts`**: Accept `portfolioType` and `portfolioDisplayName` as
   additional parameters. Change the subtitle logic:
   ```typescript
   export const useOverviewMetrics = (
     data: PortfolioOverviewProps["data"],
     metricInsights: PortfolioOverviewProps["metricInsights"] = {},
     portfolioType?: string,
     portfolioDisplayName?: string,
   ): MetricData[] => {
   ```
   Then update the `subtitle` in the Total Portfolio Value metric:
   ```typescript
   subtitle: portfolioType === "combined" || !portfolioType
     ? "Across all accounts"
     : portfolioDisplayName || "Single account",
   ```

3. **`PortfolioOverview.tsx`**: Destructure the new props and pass them through:
   ```typescript
   export default function PortfolioOverview({
     // ... existing props ...
     portfolioType,
     portfolioDisplayName,
   }: PortfolioOverviewProps) {
     // ...
     const metrics = useOverviewMetrics(data, metricInsights, portfolioType, portfolioDisplayName)
   ```

4. **`PortfolioOverviewContainer.tsx`**: Pass portfolio type info from the existing
   `currentPortfolio` object (already available from `usePortfolioSummary()`):
   ```tsx
   <PortfolioOverview
     // ... existing props ...
     portfolioType={currentPortfolio?.portfolio_type}
     portfolioDisplayName={currentPortfolio?.display_name}
   />
   ```

---

### Step 5 — R11: Hide internal IDs in portfolio selector dropdown

**File**: `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx`

**Problem**: Line 265 renders the internal slug below the display name:
```tsx
<div className="truncate text-xs text-neutral-500">{portfolio.name}</div>
```
This shows system IDs like `_auto_charles_schwab_25524...` and `CURRENT_PORTFOLIO`.

**Change**: Remove or hide line 265. Replace with nothing (just delete the line), or
replace with a friendlier description if desired. The display name on line 264 already
shows the user-friendly name. The internal `portfolio.name` slug is not useful to users.

```tsx
// BEFORE (line 264-265):
<div className="truncate font-medium">{portfolio.display_name}</div>
<div className="truncate text-xs text-neutral-500">{portfolio.name}</div>

// AFTER (line 264 only):
<div className="truncate font-medium">{portfolio.display_name}</div>
```

---

### Step 6 — R13: Fix day change rounding to "$0"

**Files**:
- `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx`
- `frontend/packages/ui/src/components/portfolio/holdings/HoldingsTable.tsx`

**Problem**: Small dollar day changes (e.g., -$13, -$17) display as "$0" or "-$0". The
`DashboardHoldingsCard.tsx` uses a local `formatCurrency` function (line 19-24) with
`maximumFractionDigits: 0` which rounds to the nearest dollar. For values like -$13.45
on a $2,372 position, this correctly shows `-$13`. But the issue is that the `dayChange`
*dollar* value coming from the adapter may be very small (close to zero) when computed
differently than expected.

The `HoldingsTable.tsx` uses the shared `formatCurrency` from `@risk/chassis` (which also
defaults to 0 decimal places).

**Root cause analysis**: The `formatCurrency` function at line 19 of
`DashboardHoldingsCard.tsx` rounds to whole dollars. For day change *dollar* amounts
between -$0.50 and +$0.50, this produces "$0" or "-$0". These small dollar values are
legitimate for low-priced positions with few shares.

**Change**: In both files, add a minimum display threshold. When the absolute dollar
value is less than $0.50 but not zero, show it with cents:

1. **`DashboardHoldingsCard.tsx`** — The day-change column renders at line 145-157 using
   `row.dayChangePercent`. It only shows the percentage, not the dollar amount. So this
   file may not need changes for the "$0" issue. However, if the percentage is also
   rounding (it uses `.toFixed(2)` which preserves precision), no change is needed here.

2. **`HoldingsTable.tsx`** — Line 244 renders `formatCurrency(holding.dayChange)`. This
   is the source of the "$0" display. Fix by adding a decimal parameter for small values:
   ```typescript
   // BEFORE:
   {formatCurrency(holding.dayChange)}

   // AFTER:
   {Math.abs(holding.dayChange) > 0 && Math.abs(holding.dayChange) < 1
     ? formatCurrency(holding.dayChange, { decimals: 2 })
     : formatCurrency(holding.dayChange)}
   ```

   This shows "$0.47" instead of "$0" for tiny day changes, but keeps "$13" (no decimals)
   for normal-sized changes.

---

### Step 7 — R20: Fix alert threshold label mismatch

**File**: `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx`

**Problem**: Lines 352-364 show a field labeled "Volatility Alert Level" with help text
"Alert when risk score exceeds this level." The field name says volatility but the
description says risk score. The field has `max="20"` and default value `8.0`, suggesting
it controls volatility percentage (not risk score which is 0-100).

**Change**: Fix the help text to match the field name. The field controls volatility
alert threshold (a percentage), so the label should say:

```tsx
// BEFORE (line 364):
<p className="text-xs text-neutral-500">Alert when risk score exceeds this level</p>

// AFTER:
<p className="text-xs text-neutral-500">Alert when portfolio volatility (%) exceeds this level</p>
```

Also update the label to include units for clarity:

```tsx
// BEFORE (line 352):
<Label className="text-sm font-medium">Volatility Alert Level</Label>

// AFTER:
<Label className="text-sm font-medium">Volatility Alert Level (%)</Label>
```

And update `max` from `20` to `100` (line 357) since volatility can exceed 20% in
volatile markets:

```tsx
// BEFORE:
max="20"

// AFTER:
max="100"
```

---

### Step 8 — R2: Fix Performance Trend chart height and aspect ratio

**Files**:
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`
- `frontend/packages/ui/src/components/blocks/sparkline-chart.tsx`

**Problem**: The Performance Trend chart is hardcoded to `height={80}` (line 103 of
`PortfolioOverview.tsx`), making it squashed flat. Y-axis labels at `fontSize={6}` SVG
units become ~4.8px rendered — illegible. The `preserveAspectRatio="none"` on the SVG
(line 128 of `sparkline-chart.tsx`) distorts text/labels at small heights.

**Changes**:

1. **`PortfolioOverview.tsx`** — Line 103: Increase height from 80 to 180:
   ```tsx
   // BEFORE:
   height={80}

   // AFTER:
   height={180}
   ```

2. **`sparkline-chart.tsx`** — Line 128: Change `preserveAspectRatio` to prevent
   text distortion. The value `"none"` stretches everything non-uniformly. Change to
   `"xMidYMid meet"` which preserves proportions:
   ```tsx
   // BEFORE:
   preserveAspectRatio="none"

   // AFTER:
   preserveAspectRatio="xMidYMid meet"
   ```

   Note: This may change the layout of sparkline charts used elsewhere (they will
   maintain proportions instead of stretching to fill width). If other sparkline
   usages rely on the stretching behavior, consider making `preserveAspectRatio` a
   prop instead of changing the default. Check other sparkline usages before deciding.

   If a prop approach is needed:
   ```typescript
   // Add to SparklineChartProps:
   preserveAspectRatio?: string

   // Default in component:
   preserveAspectRatio = "none"

   // Pass in SVG:
   preserveAspectRatio={preserveAspectRatio}
   ```
   Then pass `preserveAspectRatio="xMidYMid meet"` only from `PortfolioOverview.tsx`.

---

## File Summary

| File | Steps | Changes |
|------|-------|---------|
| `frontend/packages/ui/src/index.css` | 1, 2 | Add `--popover`/`--popover-foreground` vars; add dark shadow vars |
| `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` | 3, 4 | Fix risk score labels; accept portfolio type for subtitle |
| `frontend/packages/ui/src/components/portfolio/overview/types.ts` | 4 | Add `portfolioType`, `portfolioDisplayName` to props |
| `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` | 4, 8 | Pass portfolio type to hook; increase chart height |
| `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx` | 4 | Pass `portfolioType`/`portfolioDisplayName` from `currentPortfolio` |
| `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx` | 5 | Remove internal ID line from dropdown items |
| `frontend/packages/ui/src/components/portfolio/holdings/HoldingsTable.tsx` | 6 | Add decimal formatting for small day-change dollar amounts |
| `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx` | 7 | Fix volatility alert label/description/max |
| `frontend/packages/ui/src/components/blocks/sparkline-chart.tsx` | 8 | Fix preserveAspectRatio (via prop or default change) |

---

## Testing

### Automated
```bash
cd /Users/henrychien/Documents/Jupyter/risk_module/frontend && npm run test
```

Key test files to watch:
- `frontend/packages/ui/src/components/dashboard/__tests__/PortfolioSelector.test.tsx`
- Any existing tests for `useOverviewMetrics`, `PortfolioOverview`, `HoldingsTable`
- CSS changes (Steps 1-2) have no unit tests — verify visually

### Manual Verification
1. **R1** — Open portfolio selector dropdown; background should be opaque white/dark
2. **R19** — Toggle dark mode; content area text should be readable
3. **R5** — View Risk Score card; score 89 should show "Good" (not "Low Risk")
4. **R10** — Switch between "All Accounts" and single account; subtitle should update
5. **R11** — Open portfolio dropdown; no `_auto_*` or `CURRENT_PORTFOLIO` slugs visible
6. **R13** — View Holdings; small day changes should show "$0.47" not "$0"
7. **R20** — Open Settings; volatility field label should say "volatility (%)" not "risk score"
8. **R2** — Dashboard Performance Trend chart should be ~180px tall with readable labels

### TypeScript
```bash
cd /Users/henrychien/Documents/Jupyter/risk_module/frontend && npx tsc --noEmit
```

---

## Dependencies Between Steps

Steps are independent and can be done in any order. Steps 3 and 4 both edit
`useOverviewMetrics.ts` — do them together to avoid merge conflicts within the file.

---

## Out of Scope

These are NOT addressed in this session:
- R3 (All Accounts slow load) — backend optimization
- R4 (Holdings empty on initial load) — race condition, backend
- R6 (Weight denominator) — adapter + backend
- R7 (Single > combined portfolio value) — backend data integrity
- R8 (Margin debt inconsistency) — backend
- R9 (AI recommendation contradiction) — backend logic
- R12 (Holdings count mismatch) — backend consolidation count
- R14 (Sector misclassification) — FMP data quality
- R15 (Volatility inconsistency) — backend computation paths
- R16 (SGOV phantom position) — backend risk analysis
- R17 (71 API requests) — frontend performance, separate session
- R18 (Session logout on navigation) — auth, separate session
- R21 (Asset allocation gap) — backend
- R22 (Margin value conflict) — backend

Dark mode component-level hardcoded color migration (converting `text-neutral-900` etc.
to semantic classes) is partially noted in Step 2 but deferred to a dedicated follow-up.
