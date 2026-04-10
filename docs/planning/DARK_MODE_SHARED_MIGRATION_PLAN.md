# Dark Mode -- Shared Components Token Migration

## Problem

Bug F6. The E19 design system migration missed the `frontend/packages/ui/src/components/dashboard/shared/` subtree. These components use raw Tailwind gray utilities (`bg-white`, `text-gray-900`, `border-gray-200`, etc.) instead of the project's semantic design tokens (`bg-card`, `text-foreground`, `border-border`, etc.). In dark mode the result is invisible text on white backgrounds and low-contrast UI elements.

## Scope

12 files, 3 severity tiers. All under `frontend/packages/ui/src/components/dashboard/shared/`.

**Note:** `VarianceDecompositionSlot.tsx` is excluded -- it already uses design tokens (`bg-surface`, `text-foreground`, `text-muted-foreground`, `border-border`). No changes needed.

| Tier | File | Lines with hardcoded classes | Notes |
|------|------|-----|-------|
| **Severe** | `recovery/risk-analysis-dashboard.tsx` | 363 | `@ts-nocheck` recovery artifact, not on active product surface. Migrate anyway so it renders correctly if ever re-activated. |
| **Moderate** | `charts/slots/PositionAnalysisSlot.tsx` | 19 | Card shell + table headers + cell text (including `text-gray-700` on numeric data cells) |
| **Moderate** | `charts/examples/ViewIntegrationExample.tsx` | 12 | Example code with hardcoded card shells, labels, and `text-green-600` |
| **Moderate** | `charts/slots/PerformanceBenchmarkSlot.tsx` | 11 | Card shell + summary metric labels + `text-green-600`/`text-red-600` |
| **Moderate** | `charts/slots/RiskLimitChecksSlot.tsx` | 10 | Card shell + gauge track (`bg-gray-400`) + indicator dot border (`border-white`) |
| **Moderate** | `charts/slots/CorrelationMatrixSlot.tsx` | 9 | Card shell + header/row labels (`text-gray-700`) + cell borders + legend text |
| **Moderate** | `charts/slots/PortfolioRiskMetricsSlot.tsx` | 8 | Card shell + metric value/label/description text |
| **Moderate** | `charts/slots/IndustryContributionsSlot.tsx` | 7 | Card shell + industry labels |
| **Moderate** | `charts/slots/RiskContributionSlot.tsx` | 5 | Card shell only |
| **Minor** | `ui/MetricsCard.tsx` | 3 (default props) | `valueColor`, `titleColor`, `subtitleColor` defaults (lines 51-53) |
| **Minor** | `ui/StatusIndicator.tsx` | 3 (fallback case) | Default/unknown status badge (line 69: `bg-gray-100 text-gray-800`) + dot (line 70: `bg-gray-500`) |
| **Minor** | `ui/LoadingView.tsx` | 1 | Loading message text (line 69: `text-gray-600`) |

## Authoritative Config Paths

- **Tailwind config:** `frontend/tailwind.config.js` (NOT `frontend/packages/ui/tailwind.config.js` -- that file does not exist)
- **CSS custom properties:** `frontend/packages/ui/src/index.css` (`:root` and `.dark` blocks)
- **Color utility functions:** `frontend/packages/ui/src/lib/colors.ts` (canonical `text-up`/`text-down` tokens)

## Token Mapping Reference

Confirmed from `frontend/tailwind.config.js` colors (lines 13-71) + `frontend/packages/ui/src/index.css` CSS custom properties (lines 8-101). Light `:root` and `.dark` both define every token below, so a single class works in both themes.

### Background tokens

| Raw Tailwind | Design-token class | CSS variable |
|--------------|--------------------|--------------|
| `bg-white` | `bg-card` (default — **Step 6 leaves line 1005 legend swatch as `bg-white` literal**) | `--card` |
| `bg-gray-50` | `bg-muted` (default — **Step 6 overrides per-context**) | `--muted` |
| `bg-gray-100` | `bg-muted` | `--muted` |
| `bg-gray-200` | `bg-muted` *or* `bg-border` | `--muted` (progress bar fills) / `--border` (divider rules) — **context-dependent, see Step 6** |
| `bg-gray-400` | `bg-muted-foreground` (default — **Step 6 leaves line 1001 legend swatch as `bg-gray-400` literal**) | `--muted-foreground` (gauge track) |
| `bg-gray-500` | `bg-muted-foreground` | `--muted-foreground` (status dot) |
| `bg-gray-600` | `bg-muted-foreground` (default — **Step 6 leaves line 1013 legend swatch as `bg-gray-600` literal**) | `--muted-foreground` (legend swatch) |
| `bg-gray-900` | `bg-foreground` | `--foreground` (tooltip background — **must pair with `text-background`**, see note below) |
| `hover:bg-gray-50` | `hover:bg-muted` | `--muted` |
| `hover:bg-gray-200` | `hover:bg-secondary` *(default)* | `--secondary` — **but see Step 6 line 211 override:** `--secondary` and `--muted` resolve to identical HSL values in both light and dark themes (`index.css:20,22,68,70`), so when paired with `bg-muted` it produces NO visible hover. The recovery file's line 211 toolbar button uses a paired override (`bg-surface-raised hover:bg-background`) instead. |

**`bg-gray-900 text-white` tooltip pairing:** In dark mode, `bg-foreground` resolves to a light color (`36 9.8% 90%` per `index.css:58`), so keeping `text-white` creates near-invisible white-on-light text. Any `bg-gray-900 text-white` pair must migrate as a unit to `bg-foreground text-background`. This pattern is already established in the codebase (NavBar.tsx:67,86,112; PerformanceChart.tsx:268,282,302; HedgeWorkflowDialog.tsx:500; WorkflowProgressBar.tsx:121). The recovery file's custom CSS tooltip at line 988 is the only occurrence that needs this paired migration.

**`hover:bg-gray-200` — context-dependent:** `accent` is the brand color (gold — `43 54.9% 40%` light / `42 52.6% 54.5%` dark) and is wrong for neutral button hovers, so `hover:bg-accent` is ruled out. The default mapping `hover:bg-secondary` matches `button.tsx` outline (line 17) and ghost (line 20) variants — but it only produces a visible hover when the resting background is *not* `bg-muted`/`bg-secondary`. In `index.css:20,22,68,70`, `--secondary` and `--muted` resolve to **identical HSL values** in both light (`60 4.8% 95.9%`) and dark (`12 6.5% 15.1%`) themes, so the pair `bg-muted` + `hover:bg-secondary` is a no-op visually.

For the recovery file's line 211 toolbar button — which sits at rest on `bg-gray-100` — Step 6 uses a **special-case paired override** to preserve the visible hover state: `bg-gray-100 → bg-surface-raised`, `hover:bg-gray-200 → hover:bg-background`. This pattern is already established in the codebase at `risk-analysis-dashboard.tsx:1359` and `NavBar.tsx:87` for neutral toolbar buttons. Other `hover:bg-gray-200` occurrences (none currently in scope outside line 211) keep the default `hover:bg-secondary` mapping.

### Text tokens

| Raw Tailwind | Design-token class | Context | Used where |
|--------------|--------------------|---------|------------|
| `text-gray-900` | `text-foreground` | Primary text: titles, heading, primary values, table headers | All files |
| `text-gray-800` | `text-foreground` | Primary text in badges | StatusIndicator.tsx:69 |
| `text-gray-700` (primary numeric) | `text-foreground` | Tabular numeric data cells: weight, beta, risk contribution | PositionAnalysisSlot.tsx:103,113,116,119,122 |
| `text-gray-700` (secondary label) | `text-muted-foreground` | Column headers, row labels, descriptive text | CorrelationMatrixSlot.tsx:110,119; recovery passim |
| `text-gray-600` | `text-muted-foreground` | Descriptions, labels, secondary metric labels | All files |
| `text-gray-500` | `text-muted-foreground` | Tertiary labels, limit values, footnotes | All files |

**IMPORTANT: `text-gray-700` requires context-aware mapping.** Not a blanket rule.
- When used on **primary numeric data cells** (portfolio weights, betas, risk contributions in table `<td>` elements), map to `text-foreground`. These are the primary content the user reads.
- When used on **column/row headers or descriptive labels** (correlation matrix column headers, sidebar labels), map to `text-muted-foreground`.

### Border tokens

| Raw Tailwind | Design-token class | CSS variable |
|--------------|--------------------|--------------|
| `border-gray-200` | `border-border` | `--border` |
| `border-gray-300` | `border-border` | `--border` |
| `border-gray-100` | `border-border-subtle` | `--border-subtle` |
| `border-blue-100` | `border-border` | `--border` |
| `border-white` (dot border) | `border-card` | `--card` |
| `hover:border-gray-400` | `hover:border-border` | `--border` |

### Up/down color tokens

| Raw Tailwind | Design-token class | Defined in |
|--------------|--------------------|------------|
| `text-green-600` | `text-up` | `tailwind.config.js:20`, `colors.ts:17` |
| `text-red-600` | `text-down` | `tailwind.config.js:21`, `colors.ts:17` |

These are the canonical tokens. Do NOT use `text-[hsl(var(--up))]` / `text-[hsl(var(--down))]` -- the shorthand `text-up` / `text-down` classes are already registered in the Tailwind config and used throughout the codebase (e.g., `colors.ts:getChangeColor()`).

### Status badge colors (keep as-is)

Status badge colors (`bg-green-100 text-green-800`, `bg-red-100 text-red-800`, `bg-yellow-100 text-yellow-800`) in `StatusIndicator.tsx` are intentional semantic status indicators -- only the **default/fallback** case needs migration.

## Implementation Steps (per-file, ordered by severity)

### Step 1: Slot components (Moderate tier -- 7 files)

These share a structural pattern: card shell with loading/error/empty states plus a data view. Apply the token mapping from the reference table above.

**Files:** `PositionAnalysisSlot.tsx`, `RiskLimitChecksSlot.tsx`, `CorrelationMatrixSlot.tsx`, `PerformanceBenchmarkSlot.tsx`, `IndustryContributionsSlot.tsx`, `RiskContributionSlot.tsx`, `PortfolioRiskMetricsSlot.tsx`

**Common replacements (shared card shell pattern):**
1. `bg-white` -> `bg-card` (outer card div, lines: PAS:61, RLC:61, CMS:80, PBS:105, ICS:66, RCS:69, PRMS:61)
2. `border-gray-200` -> `border-border` (card border and table header border)
3. `text-gray-900` -> `text-foreground` (section title, table headers, primary values)
4. `text-gray-600` -> `text-muted-foreground` (descriptions, labels)
5. `text-gray-500` -> `text-muted-foreground` (tertiary labels, empty state messages)
6. `hover:bg-gray-50` -> `hover:bg-muted` (table row hover, PAS:99)

**File-specific replacements:**

**PositionAnalysisSlot.tsx** -- `text-gray-700` context-aware split:
- Lines 103, 113, 116, 119, 122 (`<td>` numeric data cells: weight, risk contribution, betas): `text-gray-700` -> `text-foreground`
- Line 99: `border-gray-100` -> `border-border-subtle`, `hover:bg-gray-50` -> `hover:bg-muted`
- Line 100: `text-gray-900` on ticker cell -> `text-foreground`

**RiskLimitChecksSlot.tsx** -- gauge-specific tokens:
- Line 94: `bg-gray-100` -> `bg-muted` (gauge track background)
- Line 97: `bg-gray-400` -> `bg-muted-foreground` (gauge track bar)
- Line 103: `border-white` -> `border-card` (indicator dot border)

**CorrelationMatrixSlot.tsx** -- `text-gray-700` context-aware split:
- Lines 110 (column headers): `text-gray-700` -> `text-muted-foreground`
- Line 119 (row labels): `text-gray-700` -> `text-muted-foreground`
- Line 119: `border-gray-200` (row label right border) -> `border-border`
- Line 125: `border-gray-100` (cell borders) -> `border-border-subtle`
- Line 136: `text-gray-600` (legend) -> `text-muted-foreground`

**PerformanceBenchmarkSlot.tsx** -- up/down color migration:
- Lines 118, 132: `text-green-600` -> `text-up`, `text-red-600` -> `text-down` (alpha, excess return)
- Line 126: `text-gray-900` on beta value -> `text-foreground`

**PortfolioRiskMetricsSlot.tsx** -- conditional text:
- Line 89: `'text-gray-900'` (in ternary with `text-amber-600`) -> `'text-foreground'`
- Line 100: `text-gray-600` (metric label) -> `text-muted-foreground`
- Line 105: `'text-gray-500'` (in ternary with `text-amber-600`) -> `'text-muted-foreground'`

### Step 2: MetricsCard.tsx (Minor tier)

Change default prop values (lines 51-53):
- `valueColor` default: `"text-gray-900"` -> `"text-foreground"`
- `titleColor` default: `"text-gray-600"` -> `"text-muted-foreground"`
- `subtitleColor` default: `"text-gray-500"` -> `"text-muted-foreground"`

Callers passing explicit gray classes also need audit, but that is outside the `shared/` scope.

### Step 3: StatusIndicator.tsx (Minor tier)

Change the `default` case in `getStatusStyles()` (lines 68-71):
- Line 69 `badge`: `'bg-gray-100 text-gray-800'` -> `'bg-muted text-foreground'` (2 hardcoded gray utilities)
- Line 70 `dot`: `'bg-gray-500'` -> `'bg-muted-foreground'` (1 hardcoded gray utility)

### Step 4: LoadingView.tsx (Minor tier)

Line 69: `text-gray-600` -> `text-muted-foreground`

### Step 5: ViewIntegrationExample.tsx (Moderate tier, example code)

This is example/documentation code, not shipped UI. Apply the same token mapping for consistency so copied example snippets use design tokens.

- Lines 44, 150, 207: `bg-white` -> `bg-card`, `border-gray-200` -> `border-border`
- Lines 81, 85, 89: `bg-white` -> `bg-card` (summary cards)
- Lines 83, 87, 91: `text-gray-600` -> `text-muted-foreground` (labels)
- Line 86: `text-green-600` -> `text-up`
- Line 208: `text-gray-900` -> `text-foreground`
- Line 212: `text-gray-600` -> `text-muted-foreground`

### Step 6: risk-analysis-dashboard.tsx (Severe tier, lowest priority)

This file is a `@ts-nocheck` recovery artifact with 363 lines containing hardcoded light-mode classes. It is not on the active product surface.

**Standard token mappings apply first.** Before addressing the recovery-specific variants below, mechanically find-and-replace ALL standard tokens from the mapping table throughout the file (lines 192, 223, 248, 285, 429, 453, 1444, and all other occurrences — **but NOT lines 1001, 1005, or 1013, which are correlation-legend swatches kept as literals; see "Correlation legend swatches" override below**): `bg-white` -> `bg-card`, `text-gray-900` -> `text-foreground`, `border-gray-200` -> `border-border`, `text-gray-600` -> `text-muted-foreground`, `text-gray-500` -> `text-muted-foreground`. These are the same mappings used in Steps 1-5. Only `text-gray-700` requires per-line audit (see below).

**Recovery-specific gray variants not in the standard slot pattern:**
- `border-gray-300` (14 occurrences: select borders, button borders, input borders, legend swatches) -> `border-border`
- `border-blue-100` (1 occurrence, line 148: output panel border) -> `border-border`
- **Line 211 toolbar button — special-case paired override (NOT the default mapping).** This is a neutral toolbar action button. The default `bg-gray-100 → bg-muted` + `hover:bg-gray-200 → hover:bg-secondary` pair is a visual no-op here because `--muted` and `--secondary` resolve to identical HSL values in both themes (`index.css:20,22,68,70`). Use the paired override below instead, which matches the existing repo pattern at `risk-analysis-dashboard.tsx:1359` and `NavBar.tsx:87`:
  - `bg-gray-100` (line 211 only) → `bg-surface-raised`
  - `hover:bg-gray-200` (line 211 only) → `hover:bg-background`
  - `hover:border-gray-400` (line 211) → `hover:border-border`
- `bg-gray-100` (8 remaining occurrences after line 211 override) -> `bg-muted`: lines 526/543/559/575/591/607 (progress bar track backgrounds), lines 902/1668 (badge/tag backgrounds)
- `border-gray-100` (row/cell borders, e.g. line 898) -> `border-border-subtle` (matches CorrelationMatrixSlot pattern at line 128 of Step 1)
- `border-white` (risk-limit dot borders, e.g. line 530) -> `border-card` (matches RiskLimitChecksSlot pattern at line 122 of Step 1; dot sits on card surface)
- `bg-gray-200` — **context-dependent split**:
  - **Progress bar fills** (lines 382, 527): `bg-gray-200` -> `bg-muted` (track background under a colored fill bar)
  - **Divider rules** (lines 1172, 1173): `bg-gray-200` -> `bg-border` (these are 1px-tall horizontal separators, not progress bars; they need to read as borders, not as filled surfaces). If implementer finds these are actually `<div>` separators that would be cleaner as a `<div className="border-t border-border" />`, that refactor is acceptable; otherwise the `bg-border` swap is the minimal mechanical change.
- `bg-gray-50` (5 occurrences — context-specific, NOT blanket `bg-muted`):
  - Line 190 (page shell `min-h-screen`): `bg-gray-50` -> `bg-background` (matches `ModernDashboardApp.tsx:645`)
  - Line 959 (null correlation cells): `bg-gray-50` -> `bg-background` (matches `CorrelationMatrixSlot.tsx:62`)
  - Lines 295, 1321, 1483 (inset callout/info boxes): `bg-gray-50` -> `bg-surface-raised` (matches existing patterns at `:128`, `:1303`)
- `hover:bg-gray-50` (3 occurrences, lines 1362, 1615, 1632) -> `hover:bg-muted`
- `bg-gray-900 text-white` (1 occurrence, line 988: tooltip) -> `bg-foreground text-background` (paired migration — `text-white` alone would be invisible on light `bg-foreground` in dark mode)
- **Correlation legend swatches — preserve current state (do NOT migrate).** The correlation matrix legend has four swatches at lines 1001, 1005, 1009, and 1013 ("Positive Correlation" / "No Correlation" / "Negative Correlation" / "Perfect Correlation (1.0)"). These swatches sit directly beside the heatmap cells they label, and the heatmap cells use hardcoded inline `rgb(...)` background colors at lines 966, 973, and 977 (see "Known limitation: inline `rgb()` heatmap colors" below). Migrating any swatch to a design token that resolves differently in dark mode while the cells stay as inline `rgb()` would invert that swatch relative to its cell, making the legend disagree with what the user sees in the matrix. To keep the legend in sync with the unmigrated cells, preserve the current state of all four swatches:
  - Line 1001 ("Positive Correlation"): keep as `bg-gray-400` literal (do NOT map to `bg-muted-foreground`). Add comment.
  - Line 1005 ("No Correlation"): keep as `bg-white` literal (do NOT map to `bg-card`). Add comment.
  - Line 1009 ("Negative Correlation"): **already tokenized** as `bg-[hsl(var(--down))]/10 border border-border` in current source — leave as-is, do NOT touch. The semantic-down token + low-opacity wash already reads correctly in both themes alongside the unmigrated `rgb()` heatmap cells. No comment needed; no edit needed.
  - Line 1013 ("Perfect Correlation (1.0)"): keep as `bg-gray-600` literal (do NOT map to `bg-muted-foreground`). Add comment.
  - **Inline comment to add at lines 1001, 1005, and 1013 only** (NOT line 1009): `{/* intentional literal: paired with unmigrated inline rgb() heatmap cells at L966/973/977; see DARK_MODE_SHARED_MIGRATION_PLAN.md */}`.
  - **Note:** The default mapping table entries still apply to all OTHER occurrences in the file (gauge tracks, card shells, etc.). This override is scoped only to the three literal swatches at lines 1001, 1005, and 1013, plus the no-touch directive for line 1009.
- `bg-gray-400` (6 remaining occurrences after the line 1001 legend override: gauge tracks and other non-legend swatches) -> `bg-muted-foreground`
- `text-green-600` / `text-red-600` -> `text-up` / `text-down`

**`text-gray-700` (26 occurrences): per-line audit required at implementation time.**

Do NOT blanket-replace these. The recovery file mixes headings, form labels, button text, table headers, and table body data under a single `text-gray-700` class. Each occurrence must be cross-referenced against the already-migrated slot components to determine whether it maps to `text-foreground` or `text-muted-foreground`. Known correspondences from `VarianceDecompositionSlot.tsx` (the canonical migrated version):

| Recovery file line | Element | Slot equivalent | Correct token |
|--------------------|---------|-----------------|---------------|
| 458 | `<h4>` "Total Portfolio Variance" | `VarianceDecompositionSlot.tsx:82` | `text-foreground` |
| 477 | `<h4>` "Factor Risk Breakdown" | `VarianceDecompositionSlot.tsx:105` | `text-foreground` |

Additional lines requiring individual judgment (not exhaustive -- implementer must audit all 26):
- Line 211: button text in toolbar -> `text-foreground` (interactive element, needs full contrast)
- Line 928: correlation matrix `<th>` column headers -> `text-muted-foreground` (matches CorrelationMatrixSlot pattern)
- Line 1187: `<tbody>` on benchmark comparison table -> `text-foreground` (primary data cells)
- Line 1500: `<label>` on form input ("Maximum Volatility") -> `text-muted-foreground` (form label, secondary)
- Line 1615: button text "Reset to Defaults" -> `text-foreground` (interactive element)

Because the file is large and not type-checked, do a visual spot-check in both themes after migration.

**Known limitation: inline `rgb()` heatmap colors AND paired legend swatches.** The correlation matrix heatmap at lines 966, 973, and 977 uses hardcoded `rgb(...)` values for cell background fills. The active `CorrelationMatrixSlot.tsx:60` already uses theme-token backgrounds, so this only affects the recovery file. These inline `rgb()` colors are NOT migrated because they require a JS-level refactor to use CSS variables (e.g., interpolating between `hsl(var(--up))` and `hsl(var(--down))`), which is out of scope for a class-level token migration.

Because the legend swatches at lines 1001 (`bg-gray-400` "Positive Correlation"), 1005 (`bg-white` "No Correlation"), and 1013 (`bg-gray-600` "Perfect Correlation (1.0)") are visually paired with these unmigrated heatmap cells, they are intentionally left as their original literal Tailwind classes — see the "Correlation legend swatches" override above. If they were migrated to design tokens while the cells stayed on inline `rgb()`, dark mode would invert the swatches relative to the cells they label. The fourth swatch at line 1009 ("Negative Correlation") is already tokenized via `bg-[hsl(var(--down))]/10` in current source and reads correctly in both themes alongside the rgb() cells, so it is left untouched.

If the recovery file is ever promoted to active code, the heatmap cell coloring AND the three literal legend swatches should be migrated together to CSS custom properties for dark mode compatibility.

## Testing (visual verification checklist)

All verification in the browser at `localhost:3000`, toggling between light and dark mode.

- [ ] **Slot components**: Navigate to a view that renders each slot (risk analysis view or any view using these chart slots). Verify card backgrounds, text, borders, and hover states are correct in both light and dark themes.
- [ ] **PositionAnalysisSlot**: Verify numeric data cells (weight, beta columns) have sufficient contrast in dark mode -- they should render as `text-foreground`, not muted.
- [ ] **RiskLimitChecksSlot**: Gauge track and indicator dot border visible in dark mode.
- [ ] **CorrelationMatrixSlot**: Cell borders and header text legible in dark mode. Legend text migrated (`text-gray-600` -> `text-muted-foreground` at line 136). Row/column labels are muted weight.
- [ ] **PerformanceBenchmarkSlot**: Alpha/excess return colors render as theme-aware up/down (green/red adapt to dark mode).
- [ ] **PortfolioRiskMetricsSlot**: Metric values, labels, and descriptions show correct contrast hierarchy.
- [ ] **MetricsCard**: Verify legacy views (PerformanceAnalyticsView, StockFactorExposureCard) show correct text colors in dark mode.
- [ ] **StatusIndicator**: Unknown/default status badge renders legibly in dark mode.
- [ ] **LoadingView**: Loading message text visible in dark mode.
- [ ] **risk-analysis-dashboard.tsx**: If accessible, spot-check a few sections. Otherwise skip -- recovery artifact.
- [ ] **Light mode regression**: Confirm no visual regressions in light mode (token values match the original grays closely enough).

## Risks & Rollback

- **Low risk.** This is a mechanical find-replace of hardcoded Tailwind classes with design-token equivalents. No logic changes, no prop signature changes, no new dependencies.
- **`text-gray-700` split.** The context-aware mapping (foreground vs muted-foreground) requires per-file judgment. The line-number references above specify which mapping applies at each site.
- **MetricsCard caller audit.** Callers outside `shared/` may pass explicit `valueColor="text-gray-900"` overrides. Changing the default fixes the majority case; explicit overrides need a separate sweep.
- **Rollback.** `git revert` of the single commit. No migrations, no data changes.
