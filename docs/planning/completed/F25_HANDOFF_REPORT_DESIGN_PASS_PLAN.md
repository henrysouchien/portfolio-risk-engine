# F25 — Handoff Report Design Pass

**Status**: DRAFT v3 (post-Codex R2 FAIL)
**Scope**: Redesign the Research Workspace handoff report body to match DESIGN.md analyst-report patterns. Visual/rendering only — no data shape changes.

**Lane**: E (frontend bug). Bug ID: F25.

---

## Changelog

- **v3.1 (this draft — POST R3 PASS, non-blocking polish)**: Folded Codex R3 non-blocking suggestions. (1) Sources block at `HandoffReviewView.tsx:333` now renders the same `[S1]` format as inline chips (consistency). (2) `company` section uses local `<dl>` as primary (not MetricStrip) on design grounds — MetricStrip's tabular-number styling fits numerics better. (3) Tightened `qualitative_factors[].data` fallback rule: any non-plain-object JSON (arrays at top level, `null`, primitives, nested objects) falls through to the `<pre>JSON.stringify</pre>` path. (4) Replaced "React key uses factor id" test with behavioral assertion (key stability via re-render + input-preservation test).
- **v3**: Addresses Codex R2 blockers. (1) Fixed DataTable column API — real contract is `{key, label, render, ...}` (render mandatory), not `{key, header, className}`. (2) `qualitative_factors[].data` now guaranteed to surface fully: scalar keys as `<dl>`, nested objects/arrays fall through to `<pre>JSON.stringify(data, null, 2)</pre>` inside the disclosure so nothing is dropped. (3) Source chip format pinned: `src_1` → `[S1]` (strip `src_` prefix, uppercase remainder; fall back to raw id if no prefix). (4) Factor rows keyed on `qualitative_factors[].id`. (5) Rewrite existing `HandoffReviewView.test.tsx` fixture from old `statement/summary` shapes to locked schema names. (6) `ResearchCompareView.tsx` schema drift logged as separate follow-up — out of F25 scope.
- **v2**: Section-key dispatch + hero thesis enrichment + Radix Tooltip. Rejected by Codex R2 on DataTable API + nested `data` lossy handling.
- **v1**: Shape-driven renderer with unsafe thesis dedupe. Rejected by Codex R1.

---

## 1. Problem

After a diligence handoff is finalized, `HandoffReviewView` renders the artifact. Commit `c540a973` shipped the top frame (Thesis hero, Report Snapshot, Decision Lens, Decision Log, Sources, Build Model). The body — 11 artifact sections iterated via `HandoffSectionRenderer` — still renders as uniform tile grids (raw field dump).

Evidence:

- `frontend/packages/ui/src/components/research/HandoffReviewView.tsx:345-352` iterates `SECTION_TITLES` (11 keys) and passes each to `HandoffSectionRenderer`.
- `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx:102-118` is the fallback `renderObject` path — when the section object has no `statement`/`summary`, it renders a 2-column grid of identical labeled tiles.
- `HandoffSectionRenderer.tsx:133-172` renders arrays as uniform `rounded-[8px] border bg-surface-raised` cards. Catalysts, Risks, Assumptions, Peers all look visually identical.
- `HandoffSectionRenderer.tsx:46-57` emits source citations as full-text rounded-full pills inline with each section — duplicates data in the bottom Sources block (`HandoffReviewView.tsx:326-343`).
- **Thesis rendered twice** — hero at `HandoffReviewView.tsx:218-223` (statement only) and body via `SECTION_TITLES` → `HandoffSectionRenderer`.

Memory: `feedback_no_generic_previews.md` — "Clean Inter + emerald + uniform surfaces IS AI slop. Think domain-appropriate density." The current body is the canonical failure example.

---

## 2. Non-Goals

- **No upstream artifact data changes.** The artifact schema is locked in `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md:283-380` and owned by the ai-excel-addin gateway.
- **No new sections, no section removal** beyond the thesis dedupe covered in §4.1.
- **No new exit ramps.** Build Model button stays (`HandoffReviewView.tsx:324`); do not speculatively add "Hedge this risk →" or similar unless trivially wired.
- **No redesign of the top frame** — Thesis hero (stays, enriched), Report Snapshot, Decision Lens, Decision Log, Sources keep their current design.
- **No pixel-snapshot tests.** Regression coverage is shape-level via unit tests.
- **No data-shape fallback exploration beyond the locked schema.** If upstream emits a key we don't recognize, the generic fallback handles it — we don't try to be smart.

---

## 3. Design North Star

Per `DESIGN.md` and existing scenario-tool composition (`ScenarioInsightCard`, `InsightSection`, `NamedSectionBreak`, `MetricStrip`, `DataTable`, `AttributionTable`):

- **Narrative first, evidence second, metadata last.** A section with narrative content leads with `InsightSection` (analyst prose). Evidence values follow as `MetricStrip` numeric tiles. Secondary metadata is small text-dim aside copy, not tiled.
- **Hierarchy through typography, not surface proliferation.** Primary statement = InsightSection (~16-21px). Numeric evidence = MetricStrip. Metadata = small muted lines.
- **Short citations inline, full attribution in Sources section.** Emit compact `[S1] [S2]` chips next to each claim; full text lives in the bottom Sources section.
- **Section-appropriate density.** A Catalyst (time-bound description with severity) and a Peer comp (ticker + name) should not look identical. Each section renderer is type-aware.
- **Section key is the source of truth for dispatch.** The artifact schema is locked per-section (`RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md:283-380`). Dispatch by section key, not by inferring shape.

---

## 4. Scope of Changes

### 4.1 `HandoffReviewView.tsx` — enrich hero thesis + dedupe + pass sectionKey

**Problem 4.1.a**: Hero only renders `artifact.thesis.statement` (line 101-108 extracts `statement`; 218-223 renders it). Schema allows additional artifact-specific fields: `direction`, `strategy`, `conviction`, `timeframe`, `source_refs` (`RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md:299-302`). "Decision Lens" at line 242-291 is `activeFile`-sourced, not `artifact.thesis`-sourced — it represents **current file state**, not **state as-of-finalization**. Dropping `thesis` from the body today would silently lose the artifact-locked framing.

**Change 4.1.a**: Expand the hero Thesis section (`HandoffReviewView.tsx:218-223`) to render:
- `thesis.statement` as `InsightSection(variant="hero")` (unchanged).
- `thesis.source_refs` (if present) as a trailing row of `[S1] [S2]` chips (uses new `renderSourceRefs()` helper from §4.2.1).
- `thesis.direction`, `thesis.strategy`, `thesis.conviction`, `thesis.timeframe` (if any present) as a single small-text metadata line below the InsightSection, styled `text-[12px] text-[hsl(var(--text-dim))]` with middle-dot separators (same pattern as existing `decisionSummary` at line 121-128). Label them "Report framing" to distinguish from `activeFile`-sourced "Decision Lens".

Fallback: if `thesis` is absent or only has `statement`, the hero behaves exactly as today.

**Problem 4.1.b**: `SECTION_TITLES` at line 23-35 includes `['thesis', 'Thesis']`, causing body re-render via `HandoffSectionRenderer`.

**Change 4.1.b**: After 4.1.a lands, remove `['thesis', 'Thesis']` from `SECTION_TITLES`. Safe because the hero now carries every locked thesis field.

**Problem 4.1.c**: `HandoffSectionRenderer` receives `title` (human label) but not `sectionKey` (schema key). Section-key dispatch needs the key.

**Change 4.1.c**: Extend `HandoffSectionRenderer` props to include `sectionKey: string`. Update the iteration at line 345-352 to pass the first element of each `SECTION_TITLES` tuple as `sectionKey`.

### 4.2 `HandoffSectionRenderer.tsx` — rewrite with section-key dispatch

Rewrite. Keep file path. Export signature changes from `{title, value, sourcesById}` to `{sectionKey, title, value, sourcesById}`. Only consumer is `HandoffReviewView.tsx:346`.

#### 4.2.1 Shared primitives — source citations

Replace `renderSourceRefs()` (current line 37-58). New behavior:

- Inline chip, `font-mono text-[10px] text-[hsl(var(--text-dim))]`, baseline-aligned. No `rounded-full` pill.
- **Chip label format**: derived from schema id per `ARCHITECTURE_DECISIONS.md:364-367` (schema convention is `src_1`, `src_2`, …).
  - If id matches `/^src_(.+)$/i` → display `[S{remainder.toUpperCase()}]` — e.g., `src_1` → `[S1]`, `src_42` → `[S42]`.
  - Otherwise → display `[{id}]` verbatim (safety fallback for non-conforming ids).
- Each chip wrapped in Radix `Tooltip` (from `frontend/packages/ui/src/components/ui/tooltip.tsx`). Tooltip content = full source text from `sourcesById[id].text || sourcesById[id].source_id || id`.
- Provider placement: wrap each chip group (row of chips for one claim) in a single `<TooltipProvider>` so hover delays are shared. `data-table.tsx:87` does not set its own provider pattern; this is a minor addition.
- `source_ref` (singular string) and `source_refs` (array) both accepted; normalizer stays from current code.
- Extract as a named export `SourceChips({ refs, sourcesById })` from `HandoffSectionRenderer.tsx` so the hero block in `HandoffReviewView.tsx` can reuse it (Change 4.1.a).

#### 4.2.2 Section dispatch

New top-level flow:

```tsx
const renderers = {
  company: renderCompany,
  business_overview: renderBusinessOverview,
  catalysts: renderCatalystsOrRisks,  // shared — both are narrative-list w/ severity
  risks: renderCatalystsOrRisks,
  valuation: renderValuation,
  peers: renderPeers,
  assumptions: renderAssumptions,
  qualitative_factors: renderQualitativeFactors,
  ownership: renderOwnership,
  monitoring: renderMonitoring,
};

export default function HandoffSectionRenderer({ sectionKey, title, value, sourcesById }) {
  const body = renderers[sectionKey]?.(value, sourcesById) ?? renderGeneric(value, sourcesById);
  return (
    <section className="space-y-3">
      <NamedSectionBreak label={title} />
      {body}
    </section>
  );
}
```

All renderers accept `value` (already narrowed to this section's subtree) and `sourcesById`. Each returns `ReactNode`.

#### 4.2.3 Per-section renderers (locked schema from `ARCHITECTURE_DECISIONS.md:283-380`)

**`company`** (object) — `{ticker, name, sector, industry, fiscal_year_end, most_recent_fy, exchange}`
- Local horizontal `<dl>` (not MetricStrip). Rationale: `MetricStrip` renders values in monospace/tabular-number style (`MetricStrip.tsx:62`) which fits numeric sections like `valuation` / `ownership` but clashes with text descriptors like "Financials" / "NYSE".
- Layout: grid of 4-6 columns at `md+`, stacking at `sm`. `<dt>` = `font-mono text-[10px] uppercase tracking-[0.12em] text-[hsl(var(--text-dim))]`. `<dd>` = `text-[14px] text-foreground mt-1`.
- Omit fields whose value is null/empty string — don't render "—" placeholders.
- No narrative prose for this section.

**`business_overview`** (object) — `{description, segments[], source_refs}`
- `description` → `InsightSection(variant="section")` with trailing `<SourceChips />`.
- `segments[]` (each `{name, rev_pct}`) → small segment strip: one `<dl>` row per segment, "Segment: Revenue %" format, or inline comma-separated line if ≤ 5 segments.
- Empty `description` → render segments alone. Empty both → "No business overview recorded."

**`catalysts` / `risks`** (array) — `[{description, expected_date|severity|type, severity, source_ref}]`
- Shared renderer (both are "narrative list with qualifiers").
- Each row:
  - Primary line: `description` (`text-[15px] text-foreground leading-[1.55]`).
  - Qualifier line below: `expected_date` (catalysts) or `type` (risks), plus `severity` (if present) rendered as small uppercase text (`font-mono text-[10px] uppercase text-[hsl(var(--text-dim))]`), middle-dot separators.
  - Trailing `<SourceChips />`.
- Rows separated by `border-b border-border/60`, last row no border. No per-row card surface (no `bg-surface-raised`, no individual `rounded`).

**`valuation`** (object) — `{method, low, mid, high, current_multiple, rationale, source_refs}`
- `rationale` → `InsightSection(variant="section")`.
- `low` / `mid` / `high` / `current_multiple` → `MetricStrip` (reuse existing block). 4-slot strip.
- `method` → small uppercase line above the MetricStrip, `font-mono text-[10px] uppercase`.
- Trailing `<SourceChips refs={source_refs} />`.

**`peers`** (array) — `[{ticker, name}]`
- Use `DataTable` (named export from `frontend/packages/ui/src/components/blocks/index.ts:12`, source `blocks/data-table.tsx`).
- Real column API per `data-table.tsx:24-32`: `{ key, label, render (mandatory), tooltip?, width?, align?, sortable? }`. No `header`, no `className` on column.
- Explicit columns — no inference:
  ```tsx
  type PeerRow = { ticker: string; name: string };
  const columns: DataTableColumn<PeerRow>[] = [
    {
      key: 'ticker',
      label: 'Ticker',
      render: (row) => <span className="font-mono">{row.ticker}</span>,
    },
    {
      key: 'name',
      label: 'Name',
      render: (row) => row.name,
    },
  ];
  ```
- `keyExtractor: (row) => row.ticker`.
- If upstream ever adds fields beyond `{ticker, name}`, the DataTable simply ignores them — do not infer.

**`assumptions`** (array) — `[{driver, value, unit, rationale, source_refs}]`
- Compact definition-list style. Each row:
  - Left: `driver` in `font-mono text-[11px]` (it's a machine key like `revenue.segment_1.volume_growth`).
  - Center: `value` + `unit` (e.g., "12 %") as `text-[14px] text-foreground`.
  - Right / below: `rationale` as `text-[12px] text-[hsl(var(--text-dim))]` with trailing `<SourceChips />`.
- Rows separated by `border-b border-border/60`.

**`qualitative_factors`** (array) — `[{id, category, label, assessment, rating, data, source_refs}]`
- Each row:
  - React `key` = `id` (schema defines it as stable identity per `ARCHITECTURE_DECISIONS.md:334-337`).
  - Heading: `label` (fallback to `category`) as `text-[14px] text-foreground font-medium`.
  - Rating (if present) as uppercase chip (`font-mono text-[10px] uppercase`, color by rating — `accent` for high, `text-dim` for low/medium).
  - `assessment` → narrative paragraph below, `text-[13px] leading-[1.6]`.
  - `data` (schema-free structured JSON per category — e.g., `short_interest: {short_pct_float, days_to_cover}` or `street_view: {analyst_count, rating_mix: {...}}` per `ARCHITECTURE_DECISIONS.md:342-345, 397-398`) → **expandable details** via `<details>`:
    - Summary label: "Show details".
    - Body (decision tree, in order):
      1. If `data` is `null`, `undefined`, or an empty object `{}` → omit the `<details>` block entirely.
      2. Else, if `data` is a **plain object** (not an array, not a primitive) AND every top-level key has a primitive value (string/number/boolean/null) → render as compact `<dl>` with `font-mono text-[10px] uppercase` labels and `text-[13px]` values.
      3. **All other cases** (top-level array, primitive, or object with any non-primitive value) → fall through to `<pre className="whitespace-pre-wrap text-[11px] text-foreground/80">{JSON.stringify(data, null, 2)}</pre>`. Guarantees no information is dropped.
  - Trailing `<SourceChips />`.
- Rows separated by `border-b border-border/60`.

**`ownership`** (object) — `{institutional_pct, insider_pct, recent_activity, source_refs}`
- `institutional_pct` + `insider_pct` → 2-slot `MetricStrip`.
- `recent_activity` → `InsightSection(variant="section")` (it's narrative).
- Trailing `<SourceChips />`.

**`monitoring`** (object) — `{watch_list: [...]}`
- `watch_list` is schema-free per `ARCHITECTURE_DECISIONS.md:355-357`. Render as a generic list:
  - If `watch_list` items are strings → bulletless vertical list, `text-[13px] leading-[1.6]`.
  - If items are objects with a `description` or `summary` or `label` field → render like a narrow catalysts-style list (primary text + small qualifier line), but no severity column.
  - Fallback to primitive stringify (`JSON.stringify`).

#### 4.2.4 Generic fallback — `renderGeneric`

Reached only when `sectionKey` is not in the dispatch map (upstream adds a new section post-schema-lock). Behavior:

- Primitive → `InsightSection(variant="section")` with `formatPrimitive(value)`.
- Array of primitives → vertical list, no cards.
- Array of objects → narrative-row mode (primary text from first `description|statement|summary|label|driver` field found, metadata as small aside, source chips).
- Object with `summary` or `statement` → `InsightSection` + scalar fields as text-dim aside line + source chips.
- Object without narrative → `<dl>` definition list of scalar keys; nested objects collapse to `JSON.stringify` inside a `<pre>` (explicit "unknown shape" signal).

Drop the current 2-col tile grid entirely.

### 4.3 Imports / reuse

- `MetricStrip` — `frontend/packages/ui/src/components/design/MetricStrip.tsx`.
- `DataTable` + `DataTableColumn<T>` — named exports from `frontend/packages/ui/src/components/blocks/index.ts:12` (source `data-table.tsx`). Required props: `columns`, `data`, `keyExtractor`.
- `Tooltip`, `TooltipTrigger`, `TooltipContent`, `TooltipProvider` — `frontend/packages/ui/src/components/ui/tooltip.tsx`. Already used by `blocks/data-table.tsx:87`, so the pattern is established.
- `InsightSection`, `NamedSectionBreak` — kept.
- No new dependencies.

---

## 5. Detailed Edits

| File | Area | Edit |
|------|------|------|
| `frontend/packages/ui/src/components/research/HandoffReviewView.tsx` | 23-35 | Remove `['thesis', 'Thesis']` entry (after 4.1.a lands). |
| `frontend/packages/ui/src/components/research/HandoffReviewView.tsx` | 101-108 | Keep `thesisStatement` extraction. Also extract `thesisFraming = { direction, strategy, conviction, timeframe }` and `thesisSourceRefs = thesisRecord?.source_refs`. |
| `frontend/packages/ui/src/components/research/HandoffReviewView.tsx` | 218-223 | Enrich hero: InsightSection (statement) + `SourceChips` (source_refs) + small "Report framing" metadata line (direction/strategy/conviction/timeframe) when present. |
| `frontend/packages/ui/src/components/research/HandoffReviewView.tsx` | 326-343 | Sources block: replace `{String(record.id ?? \`src_${index + 1}\`)}` label at line 333-335 with the chip-format helper (`src_1` → `[S1]`). Source label format now matches inline citation chips. |
| `frontend/packages/ui/src/components/research/HandoffReviewView.tsx` | 345-352 | Pass `sectionKey={key}` to `HandoffSectionRenderer`. |
| `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx` | full file | Rewrite per §4.2. Keep file path. Add `sectionKey` prop. Export new `SourceChips` + a shared `formatSourceChipLabel(id: string): string` helper so `HandoffReviewView.tsx` Sources block can reuse the same formatting. |

---

## 6. Testing

### 6.1 Unit — `HandoffSectionRenderer.test.tsx` (new file at `frontend/packages/ui/src/components/research/__tests__/`)

Cover each explicit section with one fixture pulled from the locked schema:

1. `company` — renders metadata strip with all 7 fields.
2. `business_overview` — renders `description` as InsightSection + `segments[]` inline.
3. `catalysts` — renders `description`-based rows with `severity` chip + source chip.
4. `risks` — same shape as catalysts, shares renderer; tests both severity and type qualifiers.
5. `valuation` — renders `rationale` as InsightSection + MetricStrip with low/mid/high/current_multiple.
6. `peers` — renders DataTable. Assert against the real API contract: `columns[].key`, `columns[].label`, `columns[].render` present; rendered DOM contains ticker (in `font-mono`) + name values.
7. `assumptions` — renders driver (monospace) / value+unit / rationale row.
8. `qualitative_factors` — four cases:
   - (a) **scalar-only `data`**: `{short_pct_float: 0.12, days_to_cover: 3.4}` → `<details>` contains a `<dl>` with those keys.
   - (b) **nested `data`**: `{rating_mix: {buy: 5, hold: 3, sell: 1}, analyst_count: 9}` → `<details>` contains a `<pre>` with the full JSON (nothing dropped). This directly covers Codex R2 blocker #2.
   - (c) **array-at-top-level `data`** (e.g., `[{ticker: "X"}, {ticker: "Y"}]`) and **primitive `data`** (e.g., `"n/a"`) → both fall through to `<pre>` (covers the v3.1 tightened fallback rule).
   - (d) **empty `data`** (`null`, `undefined`, `{}`) → `<details>` block omitted entirely.
   - **Key stability (behavioral, not key-inspection)**: render a factors list with `id=7` and `id=9`; re-render after toggling `<details>` open on the `id=9` row; mutate the list (remove `id=7`); assert the `id=9` row's `<details>` remains open. Validates that `id`-based React keys preserve row identity across reconciliation. If the renderer used array index as key, the open state would leak to the wrong row.
9. `ownership` — renders MetricStrip (2 slots) + `recent_activity` InsightSection.
10. `monitoring` — renders `watch_list` items; test both string and object variants.
11. Generic fallback — unknown section key → InsightSection for primitive, `<dl>` for object, JSON fallback for nested.
12. Empty / null value for each section → empty-state copy or section omitted; no crashes.
13. Missing `source_refs` → no chip row rendered.
14. `SourceChips` — id `src_1` renders as `[S1]`; id `custom_xyz` renders as `[custom_xyz]`; Tooltip content = source text.

### 6.2 Smoke — `HandoffReviewView.test.tsx` (existing file at `frontend/packages/ui/src/components/research/HandoffReviewView.test.tsx`)

Existing fixture at lines 50-60 uses stale shapes (`statement` on catalysts/risks, `summary` on business_overview/valuation/ownership/monitoring) that don't match the locked schema. **Rewrite the fixture** to locked-schema field names so this test exercises real artifact shapes:

- `business_overview.description` (not `summary`)
- `catalysts[].description` (not `statement`)
- `risks[].description` (not `statement`)
- `valuation.rationale` (not `summary`); add `low/mid/high` numeric fields
- `ownership.recent_activity` (not `summary`); add `institutional_pct` + `insider_pct`
- `monitoring.watch_list: [...]` (not `summary`)
- `thesis.{statement, direction, strategy, conviction, timeframe, source_refs}` — fully populated to exercise hero enrichment.
- One `qualitative_factors[]` entry with `id`, `label`, `assessment`, `rating`, and nested `data`.

Assertions:
- Thesis statement text appears exactly once in the rendered output (dedupe verification).
- Thesis chips `[S1] [S2]` present in hero area.
- Thesis framing metadata line (`direction · strategy · …`) appears when present.
- All 10 body sections render (`NamedSectionBreak` label visible for each).

### 6.3 Type check + lint

`pnpm tsc --noEmit` + `pnpm lint` must pass from `frontend/` root.

### 6.4 Live verification

Per CLAUDE.md UI testing rule: start dev server via `services-mcp` (`service_start risk_module` + `service_start risk_module_frontend`), log in, open a finalized research handoff, visually confirm each section renders per design. Capture before/after screenshots for the commit body.

---

## 7. Risks / Open Questions

1. **Schema drift**. If the ai-excel-addin gateway adds a field to `thesis` or `valuation` post-ship, the hero/renderer silently drops it until the risk_module renderer catches up. Acceptable for v1 — the locked schema is the contract. Add a lint check only if it becomes a recurring problem.
2. **`monitoring.watch_list` is schema-free**. Rendering is best-effort. If a distinct shape emerges in practice, add a dedicated branch later.
3. **`qualitative_factors[].data` is schema-free per category**. `<details>` disclosure is the lowest-risk fallback. A category-specific visual treatment (e.g., `short_interest` dashboard) is follow-up work.
4. **`MetricStrip` API fit for scalar strings**. If `MetricStrip` expects numeric-only data, `company` + `ownership` sections fall back to a local inline `<dl>`. Implementation confirms API before adoption; the plan supports either path.
5. **DataTable renders only `{ticker, name}`**. If a user expects peer comp numerics (pe, pb, etc.), they won't appear until the schema expands. Matches locked schema today.
6. **Source anchors**. Plan uses Tooltip for inline chips (transient disclosure). A follow-up could make `[S1]` also an anchor link scrolling to the Sources section (durable navigation). Not in v1 scope.
7. **`ResearchCompareView.tsx` schema drift** (out of F25 scope). `frontend/packages/ui/src/components/research/ResearchCompareView.tsx:31-44` and `:47-78` still assume `statement`/`summary`/`label`/`driver` instead of the locked schema's `description`/`rationale`. Log as a separate Lane E follow-up (new bug ID); F25 intentionally does not touch that file — scope discipline per memory `feedback_accept_codex_scope_reduction.md`.

---

## 8. Delivery

- Single PR, one commit.
- Est. effort: 1-2 days (per-section renderers + hero enrichment + tests + live verification).
- No migrations, no backend changes, no config changes.

---

## 9. Codex R3 Ask

1. Are the R2 blockers now fully addressed?
   - DataTable column API — peers renderer uses `{key, label, render}` matching `data-table.tsx:24-32` (§4.2.3).
   - `qualitative_factors[].data` nested-payload preservation — scalar-only path uses `<dl>`; any nested keys fall through to `<pre>JSON.stringify</pre>`, nothing dropped (§4.2.3).
2. Chip label derivation (§4.2.1) — `src_1` → `[S1]`, non-conforming ids rendered verbatim. Any issue with that rule?
3. Is the fixture rewrite in §6.2 sufficient, or should we also pin the locked schema as a TypeScript type (`HandoffArtifact`) imported in the renderer to catch future drift at compile time instead of test time?
4. Anything else missing before implementation?
