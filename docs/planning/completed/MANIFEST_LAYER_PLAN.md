# Composable App Framework — Phase 4: Manifest Layer

**Status:** Plan — Codex review round 8
**Date:** 2026-03-23
**Goal:** Let the AI chat agent generate JSON specs that render live, data-fetching SDK Bridge dashboards inline in chat and artifacts.

## Context

Phase 3 shipped the SDK Bridge — `MetricGrid`, `SourceTable`, `ChartPanel`, `FlagBanner`, layout primitives (`Page`, `Grid`, `Split`, `Tabs`). These require writing TSX. Phase 4 makes them accessible via JSON specs so the AI can emit them through the existing `:::ui-blocks` protocol.

The chat already has a spec-driven rendering system: `UIBlockSpec` → `BlockRegistry` → `sanitizeProps` → `React.createElement`. 8 presentation blocks are registered (metric-card, data-table, etc.). Phase 4 extends this to include SDK data-fetching components.

## Design Decisions

1. **Extend block registry with `sdk:` prefix** — register SDK components as new block keys (`sdk:metric-grid`, `sdk:chart-panel`, etc.) in the existing registry. Reuses parser, renderer, streaming, artifact panel. Zero new fence syntax.
2. **Extend `UILayoutSpec` as a discriminated union** for SDK layouts — `UIBaseLayoutSpec` (grid/stack/row) + `UIPageLayoutSpec` + `UISplitLayoutSpec` + `UITabsLayoutSpec` + `UITabLayoutSpec`. Each variant has its own required/optional fields. `UILayoutSpec = UIBaseLayoutSpec | UIPageLayoutSpec | UISplitLayoutSpec | UITabsLayoutSpec | UITabLayoutSpec`.
3. **Extract sanitizer helpers** — `createSanitizer`, `stringProp`, `numberProp`, etc. are currently private to `register-defaults.ts`. Extract to shared module so SDK sanitizers reuse them.
4. **One parser hardening** — `parseMessageContent()` adds `parsed.filter(isValidSpec)` after `JSON.parse` to strip null/primitive/array items before pushing to segments. `isValidSpec` exported from `parse-ui-blocks.ts` for reuse. `stripUIBlocks()` unchanged.
5. **Runtime layout validation** — `LayoutRenderer` validates incoming specs before rendering. Malformed page/split/tabs/tab payloads render the existing fallback div, never throw.
6. **Source validation in sanitizers** — SDK block sanitizers validate `source` against `dataCatalog.has(id)`. Invalid source → sanitizer returns `null` → `BlockRenderer` renders fallback. This prevents `dataCatalog.describe()` from throwing in `useDataSource`.

## Codex Review Round 1 — Findings Addressed

| # | Finding | Resolution |
|---|---------|------------|
| 1 | **No runtime validation for layout specs** — `parseMessageContent()` casts with no runtime check, malformed specs can throw in LayoutRenderer | LayoutRenderer validates each new layout type before rendering: checks `typeof spec.title === 'string'` for page, `Array.isArray(spec.ratio)` for split, children are arrays. Invalid → render fallback div (same pattern as the existing `Unknown layout` fallback). |
| 2 | **UILayoutSpec too loose for tabs/tab** — `value`/`label` optional but SDK Tabs.Tab requires both | Discriminated union: `UITabsLayoutSpec` requires `layout: 'tabs'`, `UITabLayoutSpec` requires `layout: 'tab'` + `value: string` + `label: string`. LayoutRenderer's tabs branch validates each tab child has `value` and `label` before rendering, skips invalid tabs. |
| 3 | **Invalid source throws** — `dataCatalog.describe()` throws on unknown IDs, not graceful error | SDK block sanitizers validate `source` against `dataCatalog.has(id)` (which returns boolean, never throws). Unknown source → sanitizer returns `null` → BlockRenderer renders fallback "Unknown block" div. `useDataSource` is never called with an invalid ID. |
| 4 | **Sanitizers under-specified** — format enums incomplete, seriesLabels needs Record validation, empty arrays should be rejected, semantic validation missing | Tightened: `SourceTableColumn.format` validates against full `FormatType` union (text\|number\|currency\|percent\|badge\|date\|compact). `seriesLabels` uses `validateStringRecord()` (all keys+values must be strings). `fields` and `yKeys` reject empty arrays. `Split.ratio` validates 2-element number array with positive values. `height`/`maxItems` validate positive integers. `defaultValue` validated as non-empty string. |
| 5 | **Tests miss high-risk paths** — need parse→render integration, unknown source handling, artifact pipeline | Added: integration test file `sdk-manifest-integration.test.tsx` covering malformed JSON → fallback, unknown source → fallback, valid manifest → full render pipeline, artifact panel rendering. |

## Codex Review Round 7 — Findings Addressed

| # | Finding | Resolution |
|---|---------|------------|
| R7-1 | **`spec.gap` read before narrowing won't compile** — LayoutRenderer reads `spec.gap` at line 33 before any layout branch, but discriminated union removes `gap` from tabs/tab variants. `strict: true` rejects this. | Add `gap?: 'sm' \| 'md' \| 'lg'` to ALL 5 layout variants (UIBaseLayoutSpec, UIPageLayoutSpec, UISplitLayoutSpec, UITabsLayoutSpec, UITabLayoutSpec). It's harmless on tabs/tab — just ignored. This keeps LayoutRenderer's existing `spec.gap` read before narrowing working under strict mode. |

## Codex Review Round 6 — Findings Addressed

| # | Finding | Resolution |
|---|---------|------------|
| R6-1 | **Tabs `defaultValue` may point at filtered-out tab** — `Tabs.tsx` only falls back to first tab when `defaultValue` is `undefined`, not non-matching string | Tabs branch in LayoutRenderer coerces: `const resolvedDefault = validTabs.some(t => t.value === spec.defaultValue) ? spec.defaultValue : validTabs[0]?.value`. Non-matching or typoed defaultValue falls back to first surviving tab. |

## Codex Review Round 4 — Findings Addressed

| # | Finding | Resolution |
|---|---------|------------|
| R4-1 | **Malformed top-level items crash ChatCore/ArtifactPanel/BlockRenderer** — `'layout' in spec` throws on null/primitives. `parseMessageContent()` only checks array, not element shapes. `renderChildren` guard doesn't help at top level. | Add `isValidSpec()` as a shared utility in `chassis/src/services/parse-ui-blocks.ts`: `(s: unknown): s is UIRenderableSpec => s !== null && typeof s === 'object' && !Array.isArray(s)`. Filter in `parseMessageContent()` at line 125: `parsed.filter(isValidSpec)` before pushing to segments. This is the single canonical entry point — all downstream renderers (ChatCore, ArtifactPanel, BlockRenderer, LayoutRenderer) receive only valid object specs. Export `isValidSpec` for use in tabs branch filter too. |
| R4-2 | **Tabs branch filter unsafe** — `'layout' in child` throws on null/primitives in children before `Array.isArray(child.children)` | Tabs branch applies `isValidSpec` filter to children first (same shared utility from parser), then checks `child.layout === 'tab'` etc. on guaranteed-object items. |

## Codex Review Round 3 — Findings Addressed

| # | Finding | Resolution |
|---|---------|------------|
| NEW-R3-1 | **`renderChildren` crashes on `null`/primitives in children array** — `isLayoutSpec` uses `'layout' in spec` which throws on non-objects | `renderChildren()` helper filters items: `specs.filter(isValidSpec)` where `isValidSpec = (s): s is UIRenderableSpec => s !== null && typeof s === 'object' && !Array.isArray(s)`. Invalid items silently skipped. This protects all layout branches including existing grid/stack/row. |
| NEW-R3-2 | **Tab shell valid but `tab.children` null → crash** | Tab filter adds `Array.isArray(child.children)` as a condition. Tabs with missing/null children are skipped alongside those missing value/label. |
| NEW-R3-3 | **Verification vitest command won't match test files** | Fixed: `npx vitest run packages/ui/src/components/chat/blocks/__tests__/` (matches all test files in that directory). |

## Codex Review Round 2 — Findings Addressed

| # | Finding | Resolution |
|---|---------|------------|
| 1 (still open) | **LayoutRenderer eagerly maps `spec.children` at line 34 before branching** — malformed `children` throws before any layout case runs | Step 5 restructures LayoutRenderer: add `if (!Array.isArray(spec.children)) return renderFallback(...)` guard at top. Then move child rendering into a `renderChildren(specs)` helper called inside each branch (not eagerly at top). Existing grid/stack/row also benefit from this guard. |
| NEW | **`props: null` crashes `createSanitizer`** — `BlockRenderer` passes `spec.props` to sanitizer without null check | Step 4 adds guard in `BlockRenderer`: `if (!spec.props \|\| typeof spec.props !== 'object' \|\| Array.isArray(spec.props)) return renderFallback(...)` before calling `entry.sanitizeProps(spec.props)`. |
| 4 (partial) | **`dateGranularity` enum missing `"intraday"`** — `DateGranularity = "intraday" \| "daily" \| "monthly" \| "yearly"` | ChartPanel sanitizer `dateGranularity` enum updated to `['intraday', 'daily', 'monthly', 'yearly']`. |
| 5 (partial) | **Malformed JSON test expectation wrong** — parser silently drops invalid JSON (parse-ui-blocks.ts:123 catch block), never renders fallback | Integration test expectations corrected: malformed JSON → segment silently dropped (no blocks rendered, no fallback div). Valid JSON with malformed children → layout fallback. These are distinct behaviors tested separately. |

## Implementation Steps

### Step 1: Extract sanitizer helpers (~85 lines)

**New file: `packages/ui/src/components/chat/blocks/sanitizer-helpers.ts`**

Move from `register-defaults.ts`:
- `PropRule<T>` type
- `isRecord()`, `stringProp()`, `numberProp()`, `booleanProp()`, `enumProp()`, `primitiveProp()`, `numberArrayProp()`
- `createSanitizer<T>()` factory

Add new helpers:
- `objectProp()` — validates plain object (not array, not null)
- `validateStringRecord()` — validates `Record<string, string>` (all keys and values are strings)
- `positiveIntProp()` — validates finite number > 0, truncates to integer

**Edit: `register-defaults.ts`** — replace local definitions with imports from `sanitizer-helpers.ts`.

### Step 1b: Harden parser with isValidSpec (~10 lines)

**Edit: `packages/chassis/src/services/parse-ui-blocks.ts`**

Add and export `isValidSpec`:
```typescript
export function isValidSpec(value: unknown): value is UIRenderableSpec {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
```

At line 125, after `JSON.parse`, filter: `const specs = parsed.filter(isValidSpec)`. Use `specs` instead of `parsed` when checking length and pushing to segments.

This is the **single canonical entry point** for all UI spec arrays. All downstream renderers (ChatCore, ArtifactPanel, BlockRenderer, LayoutRenderer) now receive only valid object specs. Payloads like `[null, 1, "bad"]` are silently stripped.

**Also edit: `packages/chassis/src/services/index.ts`** — add `isValidSpec` to the re-export list (currently only exports `parseMessageContent` and `stripUIBlocks`). This makes it available via `import { isValidSpec } from '@risk/chassis'` for the tabs branch in layout-renderer.

### Step 2: Extend UILayoutSpec as discriminated union (~30 lines)

**Edit: `packages/chassis/src/types/index.ts`**

Replace the single `UILayoutSpec` with a discriminated union:

```typescript
export interface UIBaseLayoutSpec {
  layout: 'grid' | 'stack' | 'row';
  columns?: number;
  gap?: 'sm' | 'md' | 'lg';
  children: UIRenderableSpec[];
}

export interface UIPageLayoutSpec {
  layout: 'page';
  title?: string;
  subtitle?: string;
  gap?: 'sm' | 'md' | 'lg';
  children: UIRenderableSpec[];
}

export interface UISplitLayoutSpec {
  layout: 'split';
  ratio?: [number, number];
  gap?: 'sm' | 'md' | 'lg';
  children: UIRenderableSpec[];
}

export interface UITabsLayoutSpec {
  layout: 'tabs';
  gap?: 'sm' | 'md' | 'lg';  // present on all variants for LayoutRenderer compat
  defaultValue?: string;
  children: UIRenderableSpec[];  // should contain UITabLayoutSpec children
}

export interface UITabLayoutSpec {
  layout: 'tab';
  gap?: 'sm' | 'md' | 'lg';  // present on all variants for LayoutRenderer compat
  value: string;     // REQUIRED
  label: string;     // REQUIRED
  children: UIRenderableSpec[];
}

export type UILayoutSpec =
  | UIBaseLayoutSpec
  | UIPageLayoutSpec
  | UISplitLayoutSpec
  | UITabsLayoutSpec
  | UITabLayoutSpec;
```

Existing consumers that check `spec.layout === 'grid'` etc. work unchanged via discriminant narrowing. The `columns` field moves to `UIBaseLayoutSpec` only (page/split/tabs/tab don't use it).

### Step 3: SDK block sanitizers (~140 lines)

**New file: `packages/ui/src/components/chat/blocks/sdk-block-sanitizers.ts`**

4 sanitizer functions. All validate `source` against `dataCatalog.has(id)`:

```typescript
import { dataCatalog } from '@risk/chassis'

function sourceProp(): PropRule<string> {
  return {
    required: true,
    validate: (value) => {
      if (typeof value !== 'string' || value.trim().length === 0) return undefined
      // Validate source exists in catalog — prevents describe() throw in useDataSource
      return dataCatalog.has(value as any) ? value : undefined
    }
  }
}
```

**Sanitizer details:**

| Sanitizer | Required | Optional | Semantic validation |
|-----------|----------|----------|-------------------|
| `sanitizeMetricGridProps` | `source` (catalog-checked), `fields` (non-empty array of string \| FieldConfig) | `columns` (1-4 int), `params` (object) | `fields`: each element is string or `{key: string, label?: string, format?: MetricFormatType, colorScheme?: ColorScheme}`. Empty array → null. |
| `sanitizeSourceTableProps` | `source`, `field` (non-empty string), `columns` (non-empty array of SourceTableColumn), `rowKey` (non-empty string) | `emptyMessage` (string), `params` (object) | `columns`: each element `{key: string, label: string, format?: FormatType, align?: left\|center\|right, sortable?: boolean, tooltip?: string}`. `format` validated against full FormatType (incl date/compact). |
| `sanitizeChartPanelProps` | `source`, `field`, `xKey` (string), `yKeys` (non-empty string array) | `chartType` (line\|bar\|area), `seriesLabels` (Record<string,string> via `validateStringRecord`), `title` (string), `height` (positive int), `legend` (boolean), `dateGranularity` (intraday\|daily\|monthly\|yearly), `yFormat` (currency\|percent\|number), `params` (object) | `yKeys` rejects empty. `seriesLabels` validated via `validateStringRecord()`. `height` via `positiveIntProp()`. |
| `sanitizeFlagBannerProps` | `source` | `severityFilter` (array of error\|warning\|info), `maxItems` (positive int), `params` (object) | `maxItems` via `positiveIntProp()`. |

### Step 4: Register SDK blocks (~15 lines)

**New file: `packages/ui/src/components/chat/blocks/register-sdk-blocks.ts`**

```typescript
import { registerBlock } from './block-registry'
import { MetricGrid } from '../../../sdk/MetricGrid'
import { SourceTable } from '../../../sdk/SourceTable'
import { ChartPanel } from '../../../sdk/ChartPanel'
import { FlagBanner } from '../../../sdk/FlagBanner'
import { sanitizeMetricGridProps, sanitizeSourceTableProps, sanitizeChartPanelProps, sanitizeFlagBannerProps } from './sdk-block-sanitizers'

registerBlock('sdk:metric-grid', MetricGrid, sanitizeMetricGridProps)
registerBlock('sdk:source-table', SourceTable, sanitizeSourceTableProps)
registerBlock('sdk:chart-panel', ChartPanel, sanitizeChartPanelProps)
registerBlock('sdk:flag-banner', FlagBanner, sanitizeFlagBannerProps)
```

**Edit: `block-renderer.tsx`** — two changes:
1. Add side-effect import: `import "./register-sdk-blocks"`
2. Add props null guard before `entry.sanitizeProps(spec.props)`: `if (!spec.props || typeof spec.props !== 'object' || Array.isArray(spec.props)) return renderFallback(...)`. This prevents `createSanitizer` from crashing on `props: null` or `props: [1,2]`.

### Step 5: Restructure LayoutRenderer + add SDK layouts (~90 lines)

**Edit: `packages/ui/src/components/chat/blocks/layout-renderer.tsx`**

**Key structural change**: The current renderer eagerly maps `spec.children` at line 34 before any branch logic. This means malformed `children` (null, undefined, non-array) throws before reaching a layout case. The fix:

1. Add `if (!Array.isArray(spec.children)) return renderFallback('Invalid layout: missing children')` guard at the top of the function body.
2. Extract a `renderChildren(specs: UIRenderableSpec[])` helper that:
   - Filters items with `isValidSpec(s) = s !== null && typeof s === 'object' && !Array.isArray(s)` — silently skips `null`, primitives, and arrays that would crash `'layout' in spec` / `'block' in spec` checks.
   - Maps valid specs to `LayoutRenderer`/`BlockRenderer` elements (the logic currently at lines 34-50).
3. Each layout branch calls `renderChildren(spec.children)` instead of using the pre-computed `children` variable.

This guard protects ALL layout types (existing grid/stack/row + new SDK layouts) from malformed input.

Then add 3 new branches after `row`:

**`page`**: Render SDK `Page` with `spec.title`, `spec.subtitle`, `spec.gap`, `renderChildren(spec.children)`.

**`split`**: If `spec.ratio` is present, validate it's a 2-element array of positive numbers; invalid → use default `[1,1]`. Render SDK `Split` with ratio + gap + `renderChildren(spec.children)`.

**`tabs`**: First filter children through `isValidSpec` (imported from `@risk/chassis`) to strip null/primitives. Then filter for valid tabs: `child.layout === 'tab' && typeof child.value === 'string' && typeof child.label === 'string' && Array.isArray(child.children)`. Two-pass: `isValidSpec` makes `'layout' in child` safe; then property checks on guaranteed objects. If no valid tabs → render fallback. Coerce `defaultValue`: `const resolvedDefault = validTabs.some(t => t.value === spec.defaultValue) ? spec.defaultValue : validTabs[0]?.value` — non-matching or typoed defaultValue falls back to first surviving tab (SDK `Tabs.tsx` only falls back when `defaultValue` is `undefined`, not non-matching string). Render SDK `Tabs` with `resolvedDefault`. For each valid tab, render `Tabs.Tab` with `value`/`label`, `renderChildren(tab.children)` inside.

**`tab`**: Standalone tab outside of tabs → render fallback.

Import `Page`, `Split`, `Tabs` from `../../../sdk/layout`.

### Step 6: Tests (~400 lines, 5 files)

All in `packages/ui/src/components/chat/blocks/__tests__/`:

| Test file | ~Lines | Covers |
|-----------|--------|--------|
| `sanitizer-helpers.test.ts` | 50 | Extracted helpers (stringProp, numberProp, createSanitizer, objectProp, positiveIntProp, validateStringRecord) |
| `sdk-block-sanitizers.test.ts` | 140 | Each sanitizer: valid/invalid/missing props, catalog source validation (mock `dataCatalog.has`), empty array rejection, format enum coverage, semantic validation |
| `register-sdk-blocks.test.ts` | 30 | resolveBlock('sdk:metric-grid') etc. returns entries |
| `layout-renderer-sdk.test.tsx` | 100 | page/split/tabs+tab rendering, malformed spec → fallback, missing tab value/label → skipped, standalone tab → fallback, invalid ratio → default |
| `sdk-manifest-integration.test.tsx` | 80 | **End-to-end**: (1) Malformed JSON in `:::ui-blocks` fence → `parseMessageContent()` silently drops (catch block, no blocks segment produced). (2) Valid JSON with malformed `children: null` → LayoutRenderer renders fallback. (3) Valid JSON with unknown source → sanitizer returns null → BlockRenderer renders fallback. (4) Valid full SDK manifest → renders MetricGrid + ChartPanel etc. (mock useDataSource). (5) `props: null` → BlockRenderer guard renders fallback. |

## File Summary

| Category | Files | Lines |
|----------|-------|-------|
| Sanitizer helpers extraction | 2 (new + edit) | ~85 |
| Parser hardening (isValidSpec) | 1 (edit) | ~10 |
| Type extension (discriminated union) | 1 (edit) | ~30 |
| SDK sanitizers | 1 (new) | ~140 |
| SDK registration | 2 (new + edit) | ~20 |
| Layout renderer restructure + SDK layouts | 1 (edit) | ~90 |
| BlockRenderer props guard | 1 (edit) | ~5 |
| Tests | 5 (new) | ~400 |
| **Total** | **14** | **~780** |

## Sequencing

```
Step 1 (extract helpers) ──→ Step 3 (SDK sanitizers) ──→ Step 4 (register) ──→ Step 6 (tests)
Step 2 (type union) ───────→ Step 5 (layout renderer) ─────────────────────────↗
```

Steps 1+2 are independent (parallel). Steps 3→4 depend on 1. Step 5 depends on 2. Tests depend on all.

## Example: AI generates a live dashboard

```
:::ui-blocks
[{
  "layout": "page",
  "title": "Risk Dashboard",
  "gap": "lg",
  "children": [
    { "block": "sdk:flag-banner", "props": { "source": "risk-score", "severityFilter": ["warning", "error"] } },
    { "block": "sdk:metric-grid", "props": { "source": "risk-score", "fields": [
      { "key": "overall_risk_score", "label": "Risk Score", "format": "number" },
      { "key": "risk_category", "label": "Category" }
    ], "columns": 2 } },
    { "layout": "split", "ratio": [2, 1], "children": [
      { "block": "sdk:chart-panel", "props": { "source": "performance", "field": "performanceTimeSeries", "chartType": "line", "xKey": "date", "yKeys": ["portfolioCumReturn", "benchmarkCumReturn"], "seriesLabels": { "portfolioCumReturn": "Portfolio", "benchmarkCumReturn": "Benchmark" }, "yFormat": "percent", "title": "Returns" } },
      { "block": "sdk:metric-grid", "props": { "source": "performance", "fields": [
        { "key": "returns.totalReturn", "label": "Total Return", "format": "percent" },
        { "key": "risk.volatility", "label": "Volatility", "format": "percent" }
      ], "columns": 1 } }
    ] },
    { "layout": "tabs", "defaultValue": "holdings", "children": [
      { "layout": "tab", "value": "holdings", "label": "Holdings", "children": [
        { "block": "sdk:source-table", "props": { "source": "positions-enriched", "field": "holdings", "columns": [
          { "key": "ticker", "label": "Ticker" },
          { "key": "value", "label": "Value", "format": "currency", "align": "right" }
        ], "rowKey": "ticker" } }
      ] }
    ] }
  ]
}]
:::
```

## Verification

1. **TypeScript**: `cd frontend && npx tsc --noEmit` — zero errors
2. **New tests**: `cd frontend && npx vitest run packages/ui/src/components/chat/blocks/__tests__/` — all pass (includes existing + new SDK tests)
3. **Existing tests**: `cd frontend && npx vitest run` — no regressions
4. **Visual**: In the running app, have the AI chat emit `:::ui-blocks` with SDK specs and verify the dashboard renders in both chat and artifact panel

## Deferred (not in this phase)

- **System prompt update** — teaching the AI the new SDK block keys and their schemas. Backend change, separate task.
- **`onRowClick` action mapping** — SourceTable row clicks → `send-message` action. Needs template syntax design.

## Critical Files

- `packages/chassis/src/types/index.ts` — `UILayoutSpec` to replace with discriminated union (line 704)
- `packages/chassis/src/catalog/DataCatalog.ts` — `has(id)` method used by sanitizers for source validation (never throws)
- `packages/ui/src/components/chat/blocks/register-defaults.ts` — sanitizer helper source (extract from here)
- `packages/ui/src/components/chat/blocks/block-registry.ts` — `registerBlock()`, `resolveBlock()`
- `packages/ui/src/components/chat/blocks/block-renderer.tsx` — rendering entry point (add import)
- `packages/ui/src/components/chat/blocks/layout-renderer.tsx` — add page/split/tabs/tab cases with runtime validation
- `packages/ui/src/sdk/MetricGrid.tsx` — props interface to match in sanitizer
- `packages/ui/src/sdk/SourceTable.tsx` — props interface to match in sanitizer
- `packages/ui/src/sdk/ChartPanel.tsx` — props interface to match in sanitizer
- `packages/ui/src/sdk/FlagBanner.tsx` — props interface to match in sanitizer
- `packages/chassis/src/services/parse-ui-blocks.ts` — add `isValidSpec()` export + filter at line 125 (single canonical entry point for spec validation)
- `packages/chassis/src/services/index.ts` — add `isValidSpec` to re-export list (currently exports only `parseMessageContent` + `stripUIBlocks`)
