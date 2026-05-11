# F87 — Canonical-Comps Renderer

**Status**: DRAFT R2 — implementation plan for F87 (canonical-comps frontend renderer) per `docs/TODO.md` row F87 (renumbered from F81 → F87 on 2026-05-08 to resolve collision with parallel-session F81 workbook plumbing).
**Created**: 2026-05-08. **Revised**: 2026-05-08 (R1: 5 blockers → R2: 1 P1; see §11 changelog).
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` R6 §7.5 (Renderer cross-cutting concern — explicitly defers renderer impl downstream).
**Prerequisites**:
- V2.P11 SHIPPED 2026-05-07 — Tracks 0/A/B/C all live (typed shapes for `peer_comparison.sections`, `operating_comparison.metric_groups`, `editorial_peer_set` exist in `Thesis.industry_analysis`).
- F83 SHIPPED 2026-05-08 — adds `Thesis.industry_analysis.comps_narrative: CompsNarrative | None` typed field via `update_comps_narrative` patch op.
- Existing `HandoffSectionRenderer.tsx` + `HandoffReviewView.tsx` + `ResearchWorkspace.tsx` chain mounted in modern dashboard's Research container; live on hank.investments.

**Authoritative code/UI references** (verified by file read 2026-05-08):
- `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx` (1070 lines) — current renderer
- `:420-540` — existing `renderIndustryAnalysis` dispatch with branches for `landscape`, `peer_comparison.peers` (flat), `macro_overlay.drivers`, `structural_trends`
- `:297-307` — `renderNarrativeWithChips(narrative, citations, sourcesById)` helper (reusable for comps_narrative + landscape patterns)
- `:438-494` — current flat `peer_comparison.peers` DataTable rendering (4 columns: Ticker / Name / Relative / Key Metrics + source chips per row)
- Imports at `:1-7` — `DataTable`, `InsightSection`, `MetricStrip`, `NamedSectionBreak`, `Tooltip` primitives available
- Loose typing convention: `UnknownRecord = Record<string, unknown>` at line 21; runtime shape checks via `isPlainObject` + `formatPrimitive` — F87 follows the same pattern (no strict TS Thesis interface to extend; runtime validation only)
- `frontend/packages/ui/src/components/research/__tests__/HandoffSectionRenderer.test.tsx:148-195` — existing industry_analysis test with mock data shape; F87 follows same pattern for new branches
- F83 dogfood artifact `AI-excel-addin/data/users/henry/workspace/theses/PCTY__f83_live_dogfood.md` — concrete `operating_comparison` shape (4 metric_groups × ~10 metrics × 4 peers × 8 years per peer); concrete `peer_comparison.sections` shape (6 sections × N metrics × M peers TTM)
- Schema typed shapes: `AI-excel-addin/schema/thesis_shared_slice.py` — `CompsNarrative` (line ~510-ish post-F83), `IndustryLandscape:404-406`, `IndustryAnalysis:504-510` (now 7 fields incl. `comps_narrative`)

---

## 1. Purpose

Add 4 new render branches to `renderIndustryAnalysis` so the canonical-comps producer + consumer outputs become user-visible in the Research workspace at hank.investments.

What's new vs today's renderer:
- **`comps_narrative`** (F83(b) field) — render as narrative paragraph + inline citation chips, prominent placement at top of industry_analysis
- **`peer_comparison.sections`** (Track A v1.2 shape) — render multi-section comp tables (6 sections × N metrics × M peers, TTM); preserve flat-peers backward compat
- **`operating_comparison.metric_groups`** (Track B v1.2 shape) — render multi-year time-series KPI matrix (4 groups × ~10 metrics × M peers × 8 years)
- **`editorial_peer_set`** (Track C field) — render compact metadata block (peer roster + per-peer rationale tooltips)

What's NOT in this plan:
- Producer code (V2.P11 + F83 already shipped)
- F82 persistence-to-Thesis (separate plan; until F82 lands, only theses with manually-injected comps state will render the new content; production user flow waits for F82)
- F84 process-template migration (separate plan; doesn't gate F87)
- Visual design exploration (`/design-shotgun`) — design is locked by typed schemas; rendering decisions follow established patterns in this renderer per F87.D1-D7

---

## 2. Audit findings (grounded by file read 2026-05-08)

### 2.1 Existing renderer state

`renderIndustryAnalysis` at `HandoffSectionRenderer.tsx:420` reads from `value` (the `industry_analysis` object) and pushes branches into a `sections: Array<{key, label, body: ReactNode}>` array. Today's branches:

| Field | Pattern | Building blocks |
|---|---|---|
| `landscape.{narrative, citations}` | narrative paragraph + inline `[Sn]` chips | `renderNarrativeWithChips` |
| `peer_comparison.peers[]` (flat) | DataTable (4 cols) + per-row source chips | `DataTable<row>`, `SourceChips` |
| `macro_overlay.drivers[]` | per-driver narrative cards with sensitivity metadata | `renderMetadataLine`, `SourceChips` |
| `structural_trends[]` | per-trend narrative cards with time_horizon metadata | (same pattern as drivers) |

### 2.2 Missing branches (F87 scope)

Verified absent in current renderer (grep confirmed):
- No `comps_narrative` reference
- No `peer_comparison.sections` handling (flat `.peers` only)
- No `operating_comparison` reference
- No `editorial_peer_set` reference

### 2.3 Concrete data shapes from F83 dogfood

**`peer_comparison.sections`** (Track A v1.2 — schema verified at `thesis_shared_slice.py:441-485`):
```
{
  industry_key: str | None,
  template_manifest_id: str | None,
  as_of: str | None,
  sections: list[SnapshotSection],   # SnapshotSection { name: str, metrics: list[SnapshotMetric] }
  # SnapshotMetric { key: str, label: str, units: str | None,
  #                  values: dict[str, CompMetricCell],   ← PER-PEER cells keyed by ticker
  #                  median: CompMetricCell | None }      ← single median cell (NOT per-peer)
  # CompMetricCell { value: ScalarValue | None, source_refs: list[SourceId], derived: bool }
  peers: list[IndustryPeerComparisonPeer],   # flat shape preserved for backward compat per Track A
}
```
Critical R0 fix: R0 incorrectly named per-peer cells `cells` and described `median` as a per-peer dict. Actual schema uses `values` (per-peer dict keyed by ticker) and `median` (single CompMetricCell, not per-peer). Implementing R0 as written would have rendered blank tables.

**`operating_comparison.metric_groups`** (Track B v1.2):
```
{
  industry_key: "hr_payroll",
  template_manifest_id: "operating_comps_hr_payroll_v1",
  years: [2018, 2019, ..., 2025],
  metric_groups: [
    { name: "Growth", order: 1, metrics: [
      { key: "revenue", label: "Revenue", units: "usd",
        series: { ADP: {2018: {value, source_refs, derived}, ..., 2025: {...}},
                  PCTY: {...}, PAYC: {...}, PAYX: {...} },
        median_series: {2018: {...}, ..., 2025: {...}} }
    ] },
    // ... 3 more groups (Customer Base, Investment, Margins)
  ]
}
```

**`comps_narrative`** (F83(b) typed field): same shape as `IndustryLandscape` — `{narrative: str, citations: list[SourceId]}`.

**`editorial_peer_set`** (Track C field): `list[EditorialPeer]` where each peer has `{ticker, name, source, added_by, added_at, rationale}`.

### 2.4 Loose typing convention (matters for F87)

The renderer does NOT import a strict TS `IndustryAnalysis` type. It uses `UnknownRecord = Record<string, unknown>` with runtime shape checks (`isPlainObject`, `formatPrimitive`, `Array.isArray`). F87 follows this convention — adds runtime checks for the new shapes, no schema-side TS work.

---

## 3. Locked design decisions

### F87.D1. Narrative-first architecture (ordering within `renderIndustryAnalysis`)
F83(b) `comps_narrative` is the analyst's reading of ~440 raw cells (~352 peer-year + ~88 median-year cells across 11 metrics × 4 peers × 8 years per the F83 dogfood) — built precisely because "no human reads 300+ cells." Render order in `industry_analysis` section is therefore narrative-first / data-on-demand:

1. `comps_narrative` (analyst reading of comps — present iff F83(b) skill ran)
2. `landscape` (industry-structure narrative — existing)
3. `peer_comparison` (TTM comp matrix — sectioned new shape OR flat fallback)
4. `operating_comparison` (multi-year KPI time-series — collapsed by default per group)
5. `macro_overlay.drivers` (existing)
6. `structural_trends` (existing)
7. `editorial_peer_set` (compact metadata block, last)

Rationale: narratives load-bear the section; tabular data is a drilldown surface. Compresses visual density of the default view; expandable when the user wants depth.

### F87.D2. Backward compat — preserve flat `peer_comparison.peers` rendering
Track A v1.2 emits both `peer_comparison.sections` (new) AND `peer_comparison.peers` (flat shape preserved for backward compat). Renderer dispatch:
- If `peer_comparison.sections` is non-empty → render the sectioned view (F87.D3)
- Else if `peer_comparison.peers` is non-empty → render the existing flat DataTable (no change)
- Else: skip the section

This means existing theses (pre-V2.P11) continue to render identically. New theses (with `sections`) get the richer view.

### F87.D3. `peer_comparison.sections` rendering — multi-section nested tables (sections-first; flat peers fallback)
Each section in `peer_comparison.sections` renders as:
- Section header (uses `NamedSectionBreak` primitive for visual separation — already imported at `:5`)
- DataTable per section with columns: `Metric` | `<peer1>` | `<peer2>` | ... | `<peerN>` | `Median`
- Per-peer cells read from `metric.values[<ticker>]: CompMetricCell` (NOT `cells` — see §2.3 schema correction)
- Median cell from `metric.median: CompMetricCell | None` (single cell, NOT per-peer dict)
- Cell content: `formatCompValue(cell.value, metric.units)` per F87.D8 unit-aware formatting
- **Citation rendering (F87.D3 lock)**: inline `[Sn]` chips per cell. Sectioned tables are bounded (~6 sections × ~4 metrics × ~5 peers = ~120 cells max), well within visual budget. Use existing `SourceChips` component (already used in flat `peer_comparison` rendering at `:475`).
- Empty cells render as em-dash (existing pattern)

Sectioning preserves the comp-matrix mental model used by analysts (Growth / Profitability / Returns / Capital Allocation / Valuation / Sentiment per the manifest).

**Sections-first dispatch (per F87.D2)**: when `peer_comparison.sections` is non-empty, render sectioned view AND the flat `peers` is used only for ticker ordering/labels (not as a separate table). When `sections` is absent, fall back to existing flat-peers DataTable rendering unchanged.

### F87.D4. `operating_comparison.metric_groups` rendering — collapsible per group via native `<details>`, Peer × Year tables
Conservative pattern (no sparklines in v1; design-locked per F87.D1 narrative-first):
- Each `metric_group` renders as a native HTML `<details>` element with `<summary>` (locked at R1 per Codex P4 — matches existing intra-section disclosure pattern at `HandoffSectionRenderer.tsx:721-724`; Radix Accordion exists at `accordion.tsx:7` but native `<details>` is the in-renderer convention)
- `<summary>`: group name + metric count (e.g., `Customer Base · 4 metrics`); use existing typographic styling from `:723`
- Inside group, one mini-table per metric:
  - Title: metric label + units
  - Columns: `Peer` | `2018` | ... | `2025` | `Median`
  - Rows: one per peer + one for median (visually distinct via subtle background or italic emphasis)
  - Per-peer cells read from `metric.series[<ticker>][<year>]: CompMetricCell`
  - Median row from `metric.median_series[<year>]: CompMetricCell`
  - Cell content: `formatCompValue(cell.value, metric.units)` per F87.D8
- **Citation rendering (F87.D4 lock)**: tooltip-only for operating_comparison cells (NOT inline chips). At ~440 cells across all metric_groups fully expanded (~352 peer-year + ~88 median-year per F83 dogfood: 11 metrics × 4 peers × 8 years), inline chips would visually overwhelm. Each cell's `source_refs` surfaces via Tooltip on hover/click using the existing `Tooltip` / `TooltipContent` / `TooltipProvider` / `TooltipTrigger` primitives (already imported at `:7`). Tooltip content lists `[Sn]` chips that link to `sourcesById`.
- Default state: groups collapsed (avoid 440-cell wall on initial render); user expands per group

Sparkline visualization is OOS for v1 (open question §9 Q3 — additive improvement once usage shows the dense table is the wrong default).

**Citation pattern split (F87.D3 inline vs F87.D4 tooltip)**: deliberate hybrid per density. Sectioned `peer_comparison` (max ~120 cells, mostly TTM single-row data) renders chips inline for at-a-glance audit. `operating_comparison` (up to ~440 cells across all groups when expanded) uses tooltip-only to keep the table scannable. Tests assert both behaviors — `[Sn]` chips visible in DOM for sectioned cells; chip text only inside Tooltip-content slot for operating cells.

### F87.D5. `comps_narrative` rendering — copy `landscape` branch
Identical pattern to `landscape`:
```tsx
if (isPlainObject(value.comps_narrative)) {
  const narrative = typeof value.comps_narrative.narrative === 'string'
    ? value.comps_narrative.narrative.trim() : '';
  if (narrative) {
    sections.push({
      key: 'comps_narrative',
      label: 'Comps Narrative',
      body: renderNarrativeWithChips(narrative, value.comps_narrative.citations, sourcesById),
    });
  }
}
```
Inserted at top of the section ordering per F87.D1. Reuses existing helper — no new primitive.

### F87.D6. `editorial_peer_set` rendering — compact metadata block
List render:
- Each peer entry: `<ticker>` chip + name + source badge ("editorial" / "auto" / etc.) + `<Tooltip>` on hover showing `rationale`
- `added_by` + `added_at` rendered as muted metadata line below the peer list
- Empty/missing list → no section

Compact pattern — this isn't analytical content, it's curation provenance.

### F87.D7. Test pattern — extend existing test file with exact-shape mocks (no cross-repo imports)
All new branches get tests in `HandoffSectionRenderer.test.tsx` following the existing pattern (line 148-195). Mock data uses **exact** schema-shape literals (`values` per ticker, `median` single cell, `series[ticker][year]`, `median_series[year]`, real unit examples like `usd`, `usd_millions`, `percent`, `multiple`) — tests are local; do NOT import the cross-repo F83 dogfood markdown directly into frontend tests (per Codex R1 design call; keeps frontend tests self-contained).
Empty-state tests for each branch. Backward-compat test verifies flat `peer_comparison.peers` still renders when `sections` is absent. Citation-pattern tests verify F87.D3 inline chips (visible in DOM) and F87.D4 tooltip-only (chip text only inside Tooltip-content slot, not in default DOM).

### F87.D8. Numeric formatting — locked `formatCompValue(value, units)` helper
Cell content rendering MUST go through a unit-aware formatter (NOT `formatPrimitive(value) + units suffix`, which would emit analyst-hostile cells like `1595221000 usd`). Add a new helper `formatCompValue(value: ScalarValue | null, units: string | null): string` co-located with the renderer. Locked behavior per units:
- `usd` → format as `$1.6B` / `$595.0M` / `$12,345` (auto-scale by magnitude; thousand separators below $1M)
- `usd_millions` → format as `$1,595M` (input value already in millions; thousand separators)
- `usd_per_share` → format as `$12.34` (always 2 decimals)
- `percent` → magnitude-based heuristic (R2): if `abs(value) <= 1`, treat as decimal ratio and multiply by 100 before formatting (`0.09767` → `9.8%`, `0.04583` → `4.6%`, `0.04731` → `4.7%`); else treat as already-percentage-point and format directly (`90.4` → `90.4%`, `12.3` → `12.3%`). All emit 1 decimal; negative supported as `-1.2%`. Tests assert BOTH branches against representative values from the F83 dogfood (decimal ratios: eps_2y_cagr, dividend_yield, capex_ratio; percent-points: retention).
- `multiple` → format as `12.3x` (1 decimal)
- `count` → format as `1,234` (thousand separators, no unit suffix; e.g., client count)
- `null` / unknown unit → fall back to `formatPrimitive(value)` (existing helper)
- `value is None` → render em-dash (matches existing empty-cell convention)

This helper applies to cells in BOTH F87.D3 (peer_comparison.sections) AND F87.D4 (operating_comparison) tables. Tests assert each unit type's output format on representative values.

---

## 4. File-by-file changes

### risk_module/frontend (only)

**Modified**: `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx`
- Extend `renderIndustryAnalysis` (line 420) with 4 new branches per F87.D3-D6
- Insert ordering per F87.D1: `comps_narrative` first, `editorial_peer_set` last
- Preserve flat `peer_comparison.peers` fallback per F87.D2
- Add helper functions if needed (e.g., `renderCompsSectionsTable`, `renderOperatingComparisonGroup`, `renderEditorialPeerSet`) — keep top-level dispatch readable
- No schema-side TS type extension needed (renderer uses runtime shape checks per `UnknownRecord` convention)

**Modified**: `frontend/packages/ui/src/components/research/__tests__/HandoffSectionRenderer.test.tsx`
- Add tests for each new branch with realistic mock data (comps_narrative, peer_comparison.sections, operating_comparison, editorial_peer_set)
- Backward-compat test: flat `peer_comparison.peers` renders when `sections` absent
- Empty-state tests for each new branch
- Combined-state test: industry_analysis with all 7 sub-sections present renders all 7 in correct order per F87.D1

### Out of scope for this plan
- F82 persistence-to-Thesis (no schema work in F87)
- F84 process-template migration (no template work)
- Sparkline / time-series visualization variants for operating_comparison (open question §9 Q3 — additive in v1.1+)
- Mobile-specific responsive layout beyond what existing peer_comparison DataTable already provides
- Print/export styling
- Renderer for invocation surfaces other than Research workspace (no other consumers per `HandoffSectionRenderer` grep)

---

## 5. Tests

| Coverage area | Where |
|---|---|
| Each new branch renders correctly with representative mock data | `HandoffSectionRenderer.test.tsx` — new test cases per F87.D7 |
| Backward compat: flat `peer_comparison.peers` still renders when `sections` absent | New test case verifying existing behavior unchanged |
| Empty-state per branch | One test per new branch with empty/null sub-field |
| Section ordering per F87.D1 | Combined-state test with all 7 sub-sections; assert DOM ordering |
| Citation chip resolution | Each branch test verifies `[Sn]` chips link to provided `sourcesById` |
| Operating_comparison group expansion behavior | Test default-collapsed state + expansion interaction |

All tests added to existing `HandoffSectionRenderer.test.tsx` file; no new test files. Run via existing Vitest config:
```bash
cd /Users/henrychien/Documents/Jupyter/risk_module/frontend
pnpm vitest run packages/ui/src/components/research/__tests__/HandoffSectionRenderer.test.tsx
```

Live verification: build frontend, navigate to Research workspace, open a Thesis with the new comps state populated (via fixture-injection per F83 plan §5 until F82 ships).

---

## 6. Cross-cutting concerns

### 6.1 Citation integrity
Every cell + narrative branch passes `source_refs` / `citations` through `sourcesById` map (existing pattern). Renderer relies on caller (HandoffReviewView) to provide the resolved sources. F87 doesn't fetch sources — it consumes the existing pipe.

### 6.2 Visual density
Operating_comparison is the densest payload (~440 cells across all metric_groups when fully expanded — per F83 dogfood: 11 metrics × 4 peers × 8 years + median per-year). F87.D4 collapsibles + narrative-first ordering keep default view tight. If user feedback shows the dense table is still overwhelming, sparkline variant is the v1.1 escape (open question §9 Q1).

### 6.3 Loose-typing discipline
F87 follows the renderer's existing `UnknownRecord` runtime-shape-check convention. No strict TS Thesis interface added. This keeps the renderer flexible to schema additions (consistent with how Track 0 / F83 schema bumps landed without breaking the renderer's ground truth).

### 6.4 Backward compat
Flat `peer_comparison.peers` shape preserved (F87.D2). Theses with empty `industry_analysis.*` fields render the existing "No industry analysis recorded." empty state. New fields are additive — no breaking changes to existing render output.

### 6.5 Performance
Render is O(N peers × Y years × M metrics) for operating_comparison default — ~440 cells worst case (~352 peer-year + ~88 median-year per F83 dogfood). Well within React render budget. No virtualization needed in v1.

---

## 7. Out of scope

- **F82 persistence-to-Thesis** (separate plan; F87 doesn't depend on F82 — renders whatever is in `Thesis.industry_analysis.*`, fixture or persisted)
- **F84 process-template migration** (separate plan; F84 changes WHEN the renderer fires, not WHAT it renders)
- **Sparkline / time-series visualization variants** for operating_comparison (v1.1+ if usage shows tables are too dense — open §9 Q3)
- **Mobile-specific layout** beyond existing DataTable responsive behavior
- **Print/export styling** (Research workspace doesn't offer print/export today)
- **Renderer for non-Research surfaces** (no other consumers per grep)
- **Animations / transitions** for collapsibles (use whatever the existing collapsible primitive provides; no custom animation work)
- **Sourcing the underlying primitive components** — `DataTable`, `Tooltip`, `NamedSectionBreak`, etc. already exist; F87 doesn't add new design-system primitives

---

## 8. Rollout sequence

1. **Phase 1**: extend `renderIndustryAnalysis` with all 4 new branches + helpers; preserve flat `peer_comparison.peers` fallback; add tests for each branch + backward compat + ordering. One focused commit.
2. **Phase 2**: live verify by mounting Research workspace against a Thesis with comps state populated (use F83 dogfood fixture path until F82 ships) — confirm visual rendering matches plan, no regressions on existing theses.

Both phases land in one Codex review round (Phase 1 is the implementation; Phase 2 is the live verification). Single commit pattern matches the prior frontend renderer changes in this codebase.

No agent gateway sync needed (frontend-only). Frontend dev server (`risk_module_frontend` on port 3000) picks up changes via Vite HMR; no service restart required for development. For production rollout to hank.investments, the standard frontend deploy (Vite build + serve) applies — outside F87 scope.

---

## 9. Open questions

R0 had 2 deferred questions; R1 closes both. Remaining:

1. **Sparkline / time-series viz for `operating_comparison`** [open] — explicitly v1.1+ per F87.D4; deferred unless usage signals the dense table is the wrong default.
2. **Section labels** [open] — F87 uses "Comps Narrative" / "Peer Comparison" / "Operating Comparison" / "Editorial Peer Set" as English labels. Confirm copy aligns with product voice (BRAND.md). May need adjustment at impl start.

**Closed at R1**:
- ~~Collapsible primitive~~ — locked to native `<details>` + `<summary>` per Codex R0 P4 (matches existing intra-section pattern at `HandoffSectionRenderer.tsx:721-724`; Radix `Accordion` exists at `accordion.tsx:7` but native is the in-renderer convention). See F87.D4.
- ~~Citation chip placement in dense tables~~ — locked to hybrid: F87.D3 inline chips for sectioned `peer_comparison` (~120 cells); F87.D4 tooltip-only for `operating_comparison` (~440 cells). See both decisions.

---

## 10. Summary

**1 file modified** in risk_module: `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx` — extends `renderIndustryAnalysis` with 4 new branches (comps_narrative, peer_comparison.sections, operating_comparison, editorial_peer_set) per F87.D3-D6. Preserves flat peer_comparison.peers backward compat (F87.D2). Narrative-first ordering (F87.D1).

**1 test file modified**: `HandoffSectionRenderer.test.tsx` — adds tests for each new branch + backward compat + ordering + empty states.

**0 schema changes**: renderer uses runtime shape checks per existing `UnknownRecord` convention; no TS type work needed.

**0 cross-repo changes**: F87 is risk_module/frontend only.

**0 production-rollout dependencies on F82**: F87 renders whatever is in `Thesis.industry_analysis.*`. Until F82 ships, only fixture-injected theses (or future producer-to-Thesis pipeline) will populate the new fields. After F87 + F82 both land, the producer-to-renderer pipeline is end-to-end live.

After F87 ships:
- Research workspace at hank.investments displays canonical-comps content (narrative + sectioned comps + operating time-series + editorial peer set)
- F82 (persistence-to-Thesis) becomes the next gate for fully automated end-user flow
- F84 (process-template migration) becomes the gate for template-driven invocation of F83 skills

Lands as 1 phase / 1 commit in risk_module. Frontend-only.

---

## 11. Changelog

### R0 → R1 (2026-05-08)

Addresses Codex R0 review FAIL (5 blockers + 1 design-call set). All findings cite shipped code; fixes verified by file read.

**B1 — F-number tracking wrong (header, §2.2, throughout)**: R0 was filed/titled F81 but TODO renumbered the canonical-comps renderer to **F87** on 2026-05-08 to resolve collision with parallel-session F81 (workbook plumbing). R1: plan file renamed `F81_RENDERER_PLAN.md → F87_RENDERER_PLAN.md`; all `F81.D*` decisions renamed `F87.D*`; all in-text references swapped except historical changelog/renumber notes.

**B2 — Wrong field name for `peer_comparison.sections` cells (§2.3)**: R0 said per-peer cells live under `metric.cells` and described `median` as a per-peer dict. Schema actually uses `metric.values: dict[str, CompMetricCell]` (per-peer keyed by ticker) and `metric.median: CompMetricCell | None` (single median cell). Per `thesis_shared_slice.py:447-453`. R1: §2.3 schema block corrected; F87.D3 cell read path explicitly reads `metric.values[<ticker>]` and `metric.median`. Implementing R0 as written would have rendered blank tables.

**B3 — Citation rendering contradiction (F87.D3, F87.D4, §9)**: R0 had inline chips per cell (D3, D4) but §9 deferred to tooltip-only for dense cells. Tests would have asserted both DOM patterns. R1: locked deliberate hybrid — F87.D3 (sectioned peer_comparison, ~120 cells) uses inline chips for at-a-glance audit; F87.D4 (operating_comparison, ~440 cells per F83 dogfood — R1 estimated ~320; corrected R2) uses tooltip-only via existing `Tooltip` primitive imports. Tests assert both behaviors explicitly.

**B4 — Collapsible primitive deferred when codebase already has answer (§9 Q1)**: R0 punted to "verify at impl start." Codex flagged that native `<details>` is already used at `HandoffSectionRenderer.tsx:721-724` (intra-section disclosure) and Radix `Accordion` exists at `accordion.tsx:7`. R1: F87.D4 locks native `<details>` per Codex recommendation (matches in-renderer convention; avoids design drift). §9 Q1 closed.

**B5 — Numeric formatting under-specified (F87.D8 new)**: R0 said `formatPrimitive(value) + units suffix`, which would produce hostile cells like `1595221000 usd` and ambiguous percentages. R1: locked `formatCompValue(value, units)` helper with per-unit behavior for `usd` (auto-scale `$1.6B`/`$595.0M`/`$12,345`), `usd_millions`, `usd_per_share`, `percent`, `multiple`, `count`, plus null/unknown fallback to `formatPrimitive`. Helper is co-located with the renderer; F87.D3 + F87.D4 both route cells through it.

**Design-call confirmations (Codex R0 final paragraphs, non-blocking)**:
- Narrative-first ordering (F87.D1) is the right call for this workspace.
- Sections-first with flat-peers fallback (F87.D2) is right; flat `peers` used for ticker ordering/labels when both present, NOT as a separate table. R1 §F87.D3 clarified.
- `comps_narrative` copying `landscape` branch (F87.D5) is fine.
- `editorial_peer_set` at bottom (F87.D6) is defensible as provenance. Optional: add a compact one-line peer-universe summary above tables for scoping visibility — R1 leaves this as a v1.1 polish; current R1 keeps the metadata block at bottom only.
- F87.D7 mock-data convention: do NOT import cross-repo dogfood markdown into frontend tests — keep frontend tests local with exact-shape literals. R1 D7 clarified.

### R1 → R2 (2026-05-08)

Addresses Codex R1 review FAIL (1 P1 + 1 non-blocking cleanup).

**P1 — `percent` formatting heuristic missing (F87.D8)**: R1's percent rule (`12.3%` from raw value) was ambiguous. Per the F83 dogfood, the artifact mixes decimal ratios (`eps_2y_cagr=0.09767` should render `9.8%`) and percent-points (`retention=90.4` should render `90.4%`). Without a heuristic, an implementer could render `0.09767` as `0.1%` or `0.0%` — materially wrong. R2: F87.D8 percent rule locked with magnitude-based heuristic — if `abs(value) <= 1`, treat as decimal ratio and multiply by 100; else treat as already-percentage-point. Tests assert both branches against representative values from the F83 dogfood (decimal: eps_2y_cagr, dividend_yield, capex_ratio; percent-point: retention).

**Non-blocking — operating_comparison cell count (§§1, F87.D4, 6.2, 6.5, 9 closures)**: R1 used `~320 cells per group/per ticker` in a few places. F83 dogfood actual: 11 metrics × 4 peers × 8 years = 352 peer-year cells, plus 88 median-year cells = ~440 total when all groups expanded. R2: cleaned to ~440 across all language sites; clarified that the count is across all groups, not per group.
