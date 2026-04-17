# Research Workspace — Phase 4 Implementation Plan: Report + Model Build Handoff

**Status:** DRAFT — Codex reviewed (R1-R5 + cross-doc sync + R6 handoff lifecycle split). Findings fixed.
**Date:** 2026-04-13 (R2 fixes: 2026-04-11, R3 fixes: 2026-04-11, R4 fixes: 2026-04-11, R5 fixes: 2026-04-11)
**Anchor:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md` (locked system frame)
**Decisions:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` (7 locked decisions)
**Phase 1 plan:** `docs/planning/RESEARCH_WORKSPACE_PHASE1_PLAN_V5.md` (implementation baseline)
**Product spec:** `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md` (UX authoritative)

Phase 4 closes the pipeline: explore → diligence → **report → model-build handoff**.

---

## What Phase 4 Delivers

1. **`research_handoffs` table lifecycle** — draft → finalized → superseded. Version incrementing per `research_file_id`. Table already stubbed in Phase 1 schema.
2. **Handoff artifact assembly** — `HandoffService.finalize_handoff()` refreshes artifact from current research state and finalizes the draft; `HandoffService.create_new_version()` supersedes a finalized handoff and creates a new draft. Both produce structured JSON per Decision 2A schema.
3. **"Finalize Report" UX** — user triggers from workspace; frontend navigates to handoff review view.
4. **`annotate_model_with_research(model_path, handoff_id, user_id)` new MCP tool** — loads handoff row by ID from per-user `research.db`, post-build openpyxl writes: assumptions to SIA template driver cells + research context JSON to hidden metadata sheet.
5. **`BuildModelOrchestrator`** — server-side two-step: `model_build()` (unchanged) → `annotate_model_with_research()` (new).
6. **REST endpoints** — `POST /handoffs/finalize`, `POST /handoffs/new-version`, `GET /handoffs/{id}`, `GET /handoffs`, `POST /handoffs/{id}/build-model`, `POST /handoffs/{id}/re-annotate`, `POST /handoffs/{id}/export`, `GET /handoffs/{id}/download`.
7. **SIA template driver-name → cell-address mapping** — YAML registry mapping handoff `assumptions[].driver` keys to SIA template `LineItem.id` values.
8. **Workbook recalc safeguards** — `fullCalcOnLoad=True`, `forceFullCalc=True`, model-engine cache clear, NO server-side readback trust (Invariant 10).
9. **Optional JSON export** — `exports/research_handoff_{research_file_id}_v{N}.json` on user action.

## What's NOT in Phase 4

- Report export to PDF/markdown — Phase 5
- Visible "Research Context" formatted sheet in Excel (hidden metadata sheet only) — future polish
- Headless-Excel server-side recalc verification — out of scope
- Bidirectional analyst-memory sync — Phase 5
- Multi-ticker theme handoffs — Phase 5

---

## Investigation Findings

### Inv-1: model_build() contract

**Location:** `AI-excel-addin/mcp_servers/model_engine_mcp_server.py` wraps `schema/build.py:build_model()`.

**Parameters:** `ticker`, `output_path`, `company_name`, `fiscal_year_end`, `most_recent_fy`, `source` ("fmp"|"edgar"), `financials` (pre-fetched FMP statements), `sector`, `n_historical`, `n_projection`.

**Returns:** `BuildResult` with `output_path`, `stats`, and in-memory `FinancialModel`. The MCP tool returns only the summary dict, but the orchestrator can import `build_model` directly to get the full `BuildResult` (including the model for cell address resolution).

**Key:** Caller pre-fetches FMP data. Model written via `write_xlsx()` using openpyxl. Template loaded from `schema/templates/sia_standard.json`.

### Inv-2: SIA template structure

`sia_standard.json` (~27K lines). Two sheets: `Assumptions` (18 sections, 227 items) and `Financial_model` (8 sections, 162 items). ~42 `input`-type items in Assumptions sheet with stable IDs (e.g., `tpl.a.revenue_drivers.volume_2_growth`). These are the cells `annotate_model_with_research()` writes to.

**Critical:** `volume_1_growth` is `item_type: "derived"` (scenario-linked OFFSET formula), NOT input. The correct primary segment volume input is `volume_2_growth` (`item_type: "input"`). Revenue drivers use a repeat-group pattern: segment 1 = `volume_2_growth` + `price_1_growth` + `operating_metric`; segment 2 = `business_segment_2_volume_growth` + `business_segment_2_price_growth`. Driver mapping must use segment-qualified keys.

**No existing driver-name → cell mapping.** Must be created.

### Inv-3: openpyxl patterns

`excel_writer.py` only uses `Workbook()` (create new). `annotate_model_with_research()` needs `load_workbook()` — new pattern. Must use `data_only=False` to preserve formulas.

### Inv-4: update_model tool

`update_model` is addin-side (Office.js API in Excel browser context), NOT server-side. Different pattern than `annotate_model_with_research()`. The prior art for server-side writes is `excel_writer.py`.

### Inv-5: Artifact field sourcing

All Decision 2A fields have Phase 1-3 sources. **Gap:** `company.fiscal_year_end` and `company.most_recent_fy` not in `research_files` today. Resolution: add as optional columns (schema v2 migration) or fetch from FMP at build time.

### Inv-6: Export naming

Per architecture: `exports/research_handoff_{research_file_id}_v{N}.json` and `model_{research_file_id}_v{N}.xlsx`. Keyed by `research_file_id`, NOT ticker.

---

## Step 0 — Schema Migration + Repository Extensions

**Owner:** ai-excel-addin
**Extended file:** `api/research/repository.py`

Schema version 2 migration: add `fiscal_year_end TEXT` and `most_recent_fy INTEGER` columns to `research_files`. Add handoff CRUD methods.

```python
def create_handoff(self, research_file_id, ticker, artifact, status="draft") -> dict: ...
def get_handoff(self, handoff_id) -> Optional[dict]: ...
def get_latest_handoff(self, research_file_id, status=None) -> Optional[dict]: ...
def list_handoffs(self, research_file_id) -> list[dict]: ...
def finalize_handoff(self, handoff_id) -> Optional[dict]: ...
def supersede_handoff(self, handoff_id) -> None: ...
```

**Tests (8):**
- `test_create_handoff_auto_increments_version`
- `test_get_handoff_returns_artifact`
- `test_get_latest_with_status_filter`
- `test_list_handoffs_ordered_by_version_desc`
- `test_finalize_sets_timestamp_and_status`
- `test_supersede_only_changes_finalized`
- `test_schema_v2_migration_from_v1`
- `test_handoff_belongs_to_file_scope`

---

## Step 1 — HandoffService: Artifact Assembly

**Owner:** ai-excel-addin
**New file:** `api/research/handoff.py`

```python
class HandoffService:
    def finalize_handoff(self, research_file_id: int) -> dict:
        """Finalize the existing draft handoff for a research file.

        Lifecycle (matches architecture Flow 5 + Decision 2B):
        1. Reads the latest draft handoff (created by Phase 3 on diligence activation)
        2. Refreshes artifact from current research state (threads, annotations, source_refs)
        3. UPDATES the draft row: status='draft' → 'finalized', sets finalized_at
        4. Does NOT create a new row — finalization mutates the existing draft
        Returns: {handoff_id, version, ticker, status, artifact_summary}"""

    def create_new_version(self, research_file_id: int) -> dict:
        """Create a new draft version from a finalized handoff.

        Called by 'New Version' UI action on a finalized handoff:
        1. Marks the current finalized handoff as 'superseded'
        2. Creates a NEW row with version+1, status='draft', copying the artifact
        Returns: {handoff_id, version, ticker, status, artifact_summary}"""
```

Artifact assembly reads diligence section data from the draft `research_handoffs` row's `artifact` JSON field (Phase 3 progressively updates it via `update_handoff_section()` -- locked per Decision 2B), overlays file metadata, and collects sources from: (a) per-section `source_refs` arrays populated during Phase 3 pre-population and user edits, (b) annotations with `diligence_ref` linking them to diligence sections, (c) any additional `source_refs` from qualitative factor entries. Assembles the indexed `sources[]` array with `annotation_id` back-links per Decision 2A.

**Tests (8):**
- `test_finalize_handoff_updates_draft_to_finalized` — existing draft row gets status='finalized' + finalized_at; no new row created
- `test_finalize_handoff_no_draft_raises` — raises if no draft exists for file
- `test_create_new_version_supersedes_old` — old finalized → superseded, new draft with version+1
- `test_artifact_includes_all_schema_fields`
- `test_artifact_sources_backreference_annotations`
- `test_artifact_sources_include_section_source_refs`
- `test_finalize_handoff_with_partial_diligence`
- `test_artifact_json_roundtrip`

---

## Step 2 — SIA Driver-Name → Cell-Address Mapping

**Owner:** ai-excel-addin
**New files:** `schema/templates/driver_mapping.yaml`, `schema/driver_resolver.py`

```yaml
# driver_mapping.yaml — maps handoff assumption driver keys to SIA item IDs
# EVERY target item_id MUST have item_type: "input" in sia_standard.json.
# Validated at load time by _validate_mapping().
#
# Revenue drivers use segment-qualified keys (R1 Findings 2+3):
#   revenue.segment_1.* maps to the primary segment inputs
#   revenue.segment_2.* maps to the secondary (business_segment_2_*) inputs
# The "raw:" prefix escape hatch allows literal SIA item_ids for custom drivers.

mappings:
  # --- Revenue: Segment 1 (primary) ---
  revenue.segment_1.volume_growth: tpl.a.revenue_drivers.volume_2_growth          # input
  revenue.segment_1.price_growth:  tpl.a.revenue_drivers.price_1_growth           # input
  revenue.segment_1.operating_metric: tpl.a.revenue_drivers.operating_metric      # input

  # --- Revenue: Segment 2 (secondary) ---
  revenue.segment_2.volume_growth: tpl.a.revenue_drivers.business_segment_2_volume_growth  # input
  revenue.segment_2.price_growth:  tpl.a.revenue_drivers.business_segment_2_price_growth   # input

  # --- Operating leverage ---
  sales_marketing_pct: tpl.a.operating_leverage.sales_and_marketing_pct_revenue
  rd_pct: tpl.a.operating_leverage.research_and_development_pct_revenue
  ga_pct: tpl.a.operating_leverage.general_and_administrative_pct_revenue

  # --- Depreciation / CapEx ---
  depreciation_rate: tpl.a.depreciation_amortization.depreciation_pct_beginning_property_and_equipment
  capex_pct: tpl.a.capital_investments.property_and_equipment_pct_revenue

  # --- Tax / Shares ---
  tax_rate: tpl.a.tax_net_income.tax_rate
  share_dilution: tpl.a.tax_net_income.diluted_shares_growth

  # --- Working capital ---
  dso: tpl.a.balance_sheet_wc.days_sales_outstanding
  dpo: tpl.a.balance_sheet_wc.days_payable_outstanding

  # --- Capital sources ---
  debt_change: tpl.a.capital_sources.debt_change
```

```python
# driver_resolver.py

def load_driver_mapping() -> dict[str, str]:
    """Load YAML mapping. Calls _validate_mapping() on first load."""

def _validate_mapping(mapping: dict[str, str], template_path: str = None) -> None:
    """Load sia_standard.json, verify every mapped item_id has item_type: 'input'.
    Raises ValueError listing all violations. Called at module load or test time."""

def resolve_driver_key(driver_key: str) -> str:
    """Resolve a handoff assumption driver key to a SIA item_id.
    If driver_key starts with 'raw:', treat remainder as literal SIA item_id
    (escape hatch for company-specific customizations).
    Otherwise, look up in the YAML mapping.
    Returns the SIA item_id, or raises KeyError for unmapped keys."""

def resolve_driver_cells(model: FinancialModel, driver_key: str,
                         periods: list[int] = None) -> list[tuple[str, str, int]]:
    """Returns (sheet_name, cell_address, period) tuples for projection periods."""
```

**`raw:` escape hatch (R1 Finding 3):** If `assumptions[].driver` starts with `raw:`, the remainder is treated as a literal SIA `item_id` (e.g., `raw:tpl.a.revenue_drivers.operating_metric`). This handles company-specific customizations without requiring mapping updates. The `_validate_mapping()` check does NOT apply to `raw:` keys -- those are validated at resolve time against the loaded model.

**Tests (8):**
- `test_load_mapping_all_keys_resolve`
- `test_validate_mapping_rejects_derived_items`
- `test_validate_mapping_passes_for_input_items`
- `test_resolve_cells_returns_projection_periods`
- `test_resolve_cells_correct_column_offset`
- `test_unknown_driver_key_raises`
- `test_raw_prefix_passes_through_literal_item_id`
- `test_mapping_covers_handoff_assumption_keys`

---

## Step 3 — `annotate_model_with_research()` MCP Tool

**Owner:** ai-excel-addin
**New file:** `schema/annotate.py`
**Extended file:** `mcp_servers/model_engine_mcp_server.py`

```python
def annotate_model_with_research(model_path: str, handoff_id: int,
                                  user_id: int,
                                  model: FinancialModel = None) -> dict:
    """Loads the authoritative handoff row, then annotates the built model.

    1. Load handoff row from per-user research.db:
       ResearchRepositoryFactory.get(user_id).get_handoff(handoff_id)
    2. Parse artifact JSON from the handoff row
    3. Load workbook (preserving formulas)
    4. Write assumptions[] to driver cells via driver_resolver
    5. Write research context JSON to hidden _ResearchContext sheet
    6. Save with fullCalcOnLoad + forceFullCalc
    7. Clear model-engine cache (defense-in-depth, P4-F3 fix —
       cache is also cleared by orchestrator, belt-and-suspenders)
    8. Return {model_path, annotated_at, assumptions_written,
              assumptions_skipped: [{driver, reason}]}

    The tool owns handoff loading — callers pass handoff_id, never artifact dicts.
    This enforces Invariant 8 (handoff is the contract).

    INVARIANT 10: Does NOT read back or trust any numerical values."""
```

**Why handoff_id, not artifact dict (R1 Finding 1):** Decision 2C requires the tool itself to load the authoritative row from `research_handoffs` by `handoff_id`. Passing an arbitrary artifact dict weakens Invariant 8. The `BuildModelOrchestrator` passes `handoff_id` only; the tool loads and validates.

Hidden sheet `_ResearchContext` contains labeled rows for each artifact field + full artifact JSON blob.

**Tests (10):**
- `test_annotate_writes_assumption_to_correct_cell`
- `test_annotate_creates_hidden_sheet`
- `test_annotate_hidden_sheet_contains_artifact_json`
- `test_annotate_sets_fullCalcOnLoad`
- `test_annotate_unmapped_drivers_in_skipped_list`
- `test_annotate_preserves_existing_formulas`
- `test_annotate_idempotent`
- `test_annotate_nonexistent_workbook_raises`
- `test_annotate_invalid_handoff_id_raises`
- `test_annotate_clears_model_cache` — verify `clear_model_cache()` called after save (defense-in-depth, P4-F3)

---

## Step 4 — BuildModelOrchestrator

**Owner:** ai-excel-addin
**New file:** `api/research/build_model_orchestrator.py`

```python
class BuildModelOrchestrator:
    def build_and_annotate(self, handoff_id: int, user_id: int) -> dict:
        """Step 1: model_build() (unchanged, Invariant 9)
        Step 2: annotate_model_with_research(model_path, handoff_id, user_id)
                Tool loads handoff row internally — orchestrator passes handoff_id only.
        Step 3: Clear model-engine cache (Decision 3 safeguard)
        Returns: {model_path, handoff_id, build_status, annotation_status,
                  assumptions_written, assumptions_skipped}"""

    def re_annotate(self, handoff_id: int, user_id: int) -> dict:
        """Re-run ONLY Step 2 (annotate) on an existing model file.
        Skips Step 1 (build). Checks if model_{file_id}_v{version}.xlsx
        already exists at the expected path — if not, raises.
        Returns: {model_path, handoff_id, annotation_status,
                  assumptions_written, assumptions_skipped}"""
```

Non-atomic: build succeeds + annotate fails = partial state (model exists without annotations). Accepted tradeoff per Decision 2C. `annotate_model_with_research()` is idempotent (retry safe). The `re_annotate()` method is the retry path when annotation fails but build succeeded (R1 Finding 5).

Output path: `data/users/{user_id}/exports/model_{research_file_id}_v{version}.xlsx`.

**Tests (8):**
- `test_build_and_annotate_produces_xlsx`
- `test_build_and_annotate_with_fmp_source`
- `test_annotation_failure_returns_model`
- `test_clears_cache`
- `test_rejects_non_finalized`
- `test_output_path_uses_file_id`
- `test_re_annotate_skips_build`
- `test_re_annotate_missing_model_raises`

---

## Step 5 — REST Endpoints for Handoffs

**Owner:** ai-excel-addin
**Extended file:** `api/research/routes.py`

```
POST   /handoffs/finalize               — finalize existing draft {research_file_id} → updates draft to finalized
POST   /handoffs/new-version            — create new draft from finalized {research_file_id} → supersedes old, creates v+1
GET    /handoffs/{handoff_id}           — fetch for review
GET    /handoffs                        — list ?research_file_id=...
POST   /handoffs/{id}/build-model       — orchestrated build (requires finalized status)
POST   /handoffs/{id}/re-annotate       — re-run annotation only (retry path, R1 Finding 5)
POST   /handoffs/{id}/export            — JSON export
GET    /handoffs/{id}/download          — binary file download ?type=model|json (P4-F5 fix)
```

**`GET /handoffs/{id}/download` (P4-F5 fix):** Returns the file as a binary download response (`Content-Disposition: attachment`). Query parameter `type=model` returns the xlsx from per-user exports directory, `type=json` returns the JSON export. Frontend cannot use filesystem paths directly; this endpoint provides the HTTP download path. Returns 404 if the requested file does not exist.

**`POST /handoffs/{id}/re-annotate` (R1 Finding 5):** Runs ONLY Step 2 (annotate) on an existing model file, skipping Step 1 (build). This is the retry path when annotation fails but the build succeeded. Calls `BuildModelOrchestrator.re_annotate()`. Returns 404 if model file does not exist at expected path.

Proxy passthrough: existing `research_content_router` catchall handles new paths automatically.

**Tests (12):**
- `test_finalize_handoff_returns_summary`
- `test_new_version_creates_draft`
- `test_get_handoff_returns_artifact`
- `test_list_handoffs_filtered`
- `test_build_model_returns_path`
- `test_build_model_rejects_draft`
- `test_handoff_requires_valid_file_scope`
- `test_re_annotate_succeeds_when_model_exists`
- `test_re_annotate_404_when_no_model`
- `test_download_model_returns_xlsx` — `GET /handoffs/{id}/download?type=model` returns binary xlsx with Content-Disposition
- `test_download_json_returns_export` — `GET /handoffs/{id}/download?type=json` returns JSON export
- `test_download_404_when_no_file` — download returns 404 when file does not exist

---

## Step 6 — JSON Export

**Owner:** ai-excel-addin
**Extended file:** `api/research/handoff.py`, `api/research/routes.py`

```python
def export_handoff(self, handoff_id: int) -> str:
    """Write artifact JSON to exports/research_handoff_{file_id}_v{version}.json."""
```

**Tests (3):**
- `test_export_creates_json_file`
- `test_export_uses_file_id`
- `test_export_idempotent`

---

## Step 7 — Factor Data Puller Registry (Conditional)

**Owner:** ai-excel-addin
**Conditional file:** `api/research/factor_data_registry.py`

If Phase 3 has already shipped `api/research/factor_data_registry.py` with the seed pullers (`short_interest`, `street_view`, `positioning`), Phase 4 skips this step entirely and extends the existing registry with additional pullers if needed. The file name is `factor_data_registry.py` (matching Phase 3), NOT `factor_pullers.py`.

**Tests (4):**
- `test_fetch_data_registered`
- `test_fetch_data_unknown`
- `test_list_categories`
- `test_puller_error_handling`

---

## Step 8 — Frontend: Handoff Review View + Build Model Flow

**Owner:** frontend (risk_module)
**New components:**
- `HandoffReviewView.tsx` — renders artifact as structured report (InsightSection, NamedSectionBreak, per-section renderers, source citations)
- `FinalizeReportAction.tsx` — button → `POST /handoffs/finalize` → navigate to review
- `BuildModelButton.tsx` — `POST /handoffs/{id}/build-model` with loading/success/error states
- `HandoffSectionRenderer.tsx` — per-section artifact renderer

**Store extensions:**
```typescript
activeHandoff: { id, version, status, artifact } | null;
buildModelState: { status: 'idle'|'building'|'success'|'error', modelPath?, error? };
handoffList: { id, version, status, created_at, finalized_at }[];
```

**React Query hooks:** `useFinalizeHandoff(researchFileId)`, `useCreateNewVersion(researchFileId)`, `useGetHandoff`, `useListHandoffs`, `useBuildModel`, `useReAnnotate`, `useExportHandoff`, `useDownloadHandoff`.

**Version history sidebar (R1 Finding 6):** List of `{version, status, created_at, finalized_at}` from `useListHandoffs`. Active version highlighted. Clicking a superseded version loads it read-only (artifact rendered in review view, build actions disabled).

**"New Version" button (R1 Finding 6):** Visible on a finalized handoff. Creates a new draft handoff (version+1) via `POST /handoffs/new-version` with `research_file_id` and navigates to the diligence tab for editing. The previous finalized version transitions to `superseded` status.

**Partial failure recovery (R1 Finding 6):**
- When `annotation_status="error"`: warning banner "Model built successfully. Research annotations failed." with "Retry Annotations" button that calls `POST /handoffs/{id}/re-annotate`.
- When build itself fails: error banner with "Retry Build" button that calls `POST /handoffs/{id}/build-model` again.
- Both states are visible in `buildModelState` and rendered by `BuildModelButton`.

**Export/download (R1 Finding 6, P4-F5 fix):**
- "Export JSON" button → `POST /handoffs/{id}/export` (creates the file), then `GET /handoffs/{id}/download?type=json` (downloads via HTTP).
- "Download Model" link → appears after successful build, pointing to `GET /handoffs/{id}/download?type=model` (HTTP download, not filesystem path). Frontend NEVER uses filesystem paths for downloads.

**Tests (15):**
- `test_setActiveHandoff`
- `test_buildModelState_transitions`
- `test_useFinalizeHandoff_endpoint`
- `test_useCreateNewVersion_endpoint`
- `test_useBuildModel_partial_failure`
- `test_HandoffReviewView_renders_sections`
- `test_FinalizeReportAction_navigates`
- `test_BuildModelButton_loading_state`
- `test_version_history_renders_list`
- `test_version_history_highlights_active`
- `test_superseded_version_loads_readonly`
- `test_new_version_creates_draft`
- `test_annotation_failure_shows_retry_banner`
- `test_build_failure_shows_retry_banner`
- `test_export_and_download_buttons`

---

## Dependency Batches

```
Batch A (parallel, no deps):
  Step 0: Schema migration + repository
  Step 2: SIA driver mapping
  Step 7: Factor data registry (if not in Phase 3)

Batch B (depends on Batch A):
  Step 1: HandoffService (needs Step 0)
  Step 3: annotate_model_with_research (needs Step 2)

Batch C (depends on Batch B):
  Step 4: BuildModelOrchestrator (needs Steps 1, 3)

Batch D (depends on Batch C):
  Step 5: REST endpoints (needs Step 4)
  Step 6: JSON export (needs Step 1)

Batch E (depends on Batch D):
  Step 8: Frontend (needs Step 5)
```

**Estimated duration:** ~8-12 days single developer, plus review rounds.

---

## Test Summary

| Step | Tests | Delta |
|------|-------|-------------|
| Step 0 — Schema + repo | 8 | — |
| Step 1 — HandoffService | 8 | +2 R6 (finalize_handoff updates draft, no_draft_raises) |
| Step 2 — Driver mapping | 8 | +3 R1 (validate, raw prefix) |
| Step 3 — annotate tool | 10 | +1 R1 (invalid handoff_id) +1 R2 (cache clear) |
| Step 4 — Orchestrator | 8 | +2 R1 (re_annotate) |
| Step 5 — REST endpoints | 12 | +2 R1 (re-annotate endpoint) +3 R2 (download model/json/404) +1 R6 (split create→finalize+new-version) |
| Step 6 — JSON export | 3 | — |
| Step 7 — Factor registry | 4 | — |
| Step 8 — Frontend | 15 | +7 R1 (version history, partial failure, export) +1 R6 (split into useFinalizeHandoff+useCreateNewVersion) |
| **Total** | **76** | **+15 R1, +4 R2, +4 R6** |

---

## Cross-Repo Change Summary

| Repo | Changes |
|---|---|
| **ai-excel-addin** | Extended `repository.py` (handoff CRUD + schema v2). New `handoff.py` (HandoffService), `build_model_orchestrator.py` (build_and_annotate + re_annotate). Conditional: `factor_data_registry.py` (only if Phase 3 has not already shipped it; extends existing registry otherwise — NOT counted as new file if Phase 3 created it). New `schema/annotate.py` (takes handoff_id, loads row internally), `schema/driver_resolver.py` (segment-qualified keys + raw: escape hatch + _validate_mapping), `schema/templates/driver_mapping.yaml`. Extended `mcp_servers/model_engine_mcp_server.py` (new tool). Extended `routes.py` (8 endpoints incl. finalize, new-version, re-annotate, download). ~1600 lines new + ~350 extensions. |
| **risk_module (backend)** | No changes — catchall proxy handles new paths. |
| **risk_module (frontend)** | Extended `researchStore.ts` (handoff state). New `useHandoff.ts`, `HandoffReviewView.tsx`, `FinalizeReportAction.tsx`, `BuildModelButton.tsx`, `HandoffSectionRenderer.tsx`. ~1200 lines new + ~100 extensions. |
| **financial-modeling-tools** | NO CHANGES — `model_build()` unchanged (Invariant 9). |

---

## Architectural Compliance

| Invariant | Phase 4 Compliance |
|---|---|
| 1 — Per-user isolation | Handoffs + exports under `data/users/{user_id}/` |
| 8 — Handoff is the contract | Artifact assembly produces Decision 2A schema JSON. `annotate_model_with_research()` loads handoff by ID (not arbitrary dict). |
| 9 — model_build() unchanged | BuildModelOrchestrator calls it with no modifications |
| 10 — No server-side readback | annotate sets recalc flags, does NOT read back values |
| 12 — Connection-per-request | Repository pattern unchanged |
| 14 — Finalization never blocked | HandoffService accepts any diligence completion state |
| 15 — Scoped by research_file_id | Handoffs keyed by file_id; ticker is snapshot; exports named by file_id |

---

## Flags / Risks

1. **Phase 3 diligence storage contract.** Phase 4 reads diligence section data from the draft `research_handoffs` row's `artifact` JSON field, which Phase 3 progressively updates via `update_handoff_section()`. This is locked per Decision 2B. The draft handoff is the single source of truth for diligence state.
2. **FMP financials at build time.** If not cached in handoff, orchestrator must fetch. HandoffService should handle.
3. **Driver mapping completeness.** Initial ~15 segment-qualified drivers. Company-specific customizations handled via `raw:` prefix escape hatch (in-plan). `_validate_mapping()` ensures all mapped targets are `input`-type.
4. **openpyxl load_workbook compatibility.** New usage pattern (existing code only creates). Step 3 tests verify roundtrip.

---

## Review History

### R1 — Codex Review (2026-04-13)

6 findings, all applied:

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | `annotate_model_with_research` takes artifact dict instead of handoff_id — weakens Invariant 8 | Changed signature to `(model_path, handoff_id, user_id)`. Tool loads handoff row internally via `ResearchRepositoryFactory.get(user_id).get_handoff(handoff_id)`. Orchestrator passes handoff_id only. |
| 2 | High | SIA mapping wrong: `revenue_growth` → `volume_1_growth` is `derived`, not `input` | Fixed to `volume_2_growth` (verified `input` in sia_standard.json). Added `_validate_mapping()` that checks all targets are `input`-type. Unmapped drivers → logged warning + `assumptions_skipped` in return value (not silent skip). |
| 3 | High | Driver mapping too flat for repeat-grouped revenue inputs | Segment-qualified keys: `revenue.segment_1.volume_growth`, `revenue.segment_2.price_growth`, etc. Added `raw:` prefix escape hatch for literal SIA item_ids. |
| 4 | Medium | Phase 3 dependency still provisional — plan reopens what Decision 2B locked | Replaced hedging language with definitive statement: draft handoff `artifact` JSON field is the single source of truth, locked per Decision 2B. |
| 5 | Medium | Retry story for annotation failure underspecified | Added `POST /handoffs/{id}/re-annotate` endpoint + `BuildModelOrchestrator.re_annotate()` method. Runs annotation only, skips build. Removed "Model re-annotation" from out-of-scope list. |
| 6 | Medium | Frontend handoff review too thin — no version history, partial failure, new version | Added concrete UI spec: version history sidebar, "New Version" button, partial failure recovery banners (annotation error vs build error), export/download buttons. +7 frontend tests. |

**Test delta:** 53 → 68 (+15 tests)

### R2 — Codex Review (2026-04-11)

**5 findings, all applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | Architecture docs not updated for annotate tool signature — still show `(model_path, handoff_id)` without `user_id`. | Updated architecture doc: Section 8 MCP tools table, Section 5 Flow 5 annotate call, and decisions doc Decision 2C code example all now show `(model_path, handoff_id, user_id)`. |
| 2 | High | Driver key schema contradictory — Decision 2A says "matches SIA template driver row key" but plan uses semantic segment-qualified keys + `raw:` escape. | Updated decisions doc Decision 2A `assumptions[]` driver description: now says "semantic segment-qualified key resolved to SIA template item_id via `driver_mapping.yaml`". Convention documented. `raw:` prefix for literal SIA item_ids. Mapping validated at load time. |
| 3 | Medium | Cache clear should be in annotate tool, not just orchestrator — Decision 3 says cache clearing is a safeguard in the tool itself. | Added `clear_model_cache()` call to Step 3 `annotate_model_with_research()` after saving workbook (defense-in-depth). Orchestrator also clears cache (belt-and-suspenders). Added `test_annotate_clears_model_cache` test. |
| 4 | Medium | Architecture API surface missing new endpoints — plan has 6 endpoints but architecture doc only shows 3. | Updated architecture doc Section 4 Phase 4 API surface to include all 7 endpoints (POST, GET by id, GET list, build-model, re-annotate, export, download). |
| 5 | Medium | No HTTP download endpoint for exports — frontend can't use filesystem paths. | Added `GET /handoffs/{id}/download?type=model|json` endpoint to Step 5. Returns binary file with `Content-Disposition: attachment`. Updated frontend Step 8 to use download URL. Updated architecture doc. Added 3 tests. |

**Test delta:** 68 → 72 (+4 tests: cache clear, download model, download json, download 404)

### R3 — Codex Review (2026-04-11)

**4 findings, all applied (2 in anchor docs, 2 in plan body):**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | build-model response contract inconsistent — architecture API surface says `{model_path, handoff_id, build_status, annotation_status}` but Flow 5 and decisions doc return only `{model_path, handoff_id, build_status}`. | Added `annotation_status` to architecture doc Flow 5 Step 3 return and decisions doc Decision 2C corrected flow. All three locations now agree: `{model_path, handoff_id, build_status, annotation_status}`. |
| 2 | Medium | "What Phase 4 Delivers" item 6 lists only 6 endpoints. Cross-repo summary also says 6. Should be 7 (added download in R2). | Updated item 6 to list all 7 endpoints including `GET /handoffs/{id}/download`. Updated cross-repo summary from "6 endpoints" to "7 endpoints incl. re-annotate + download". |
| 3 | Medium | Decisions doc Decision 2A rationale still says "driver keys map 1:1 to SIA template assumption rows" — contradicts resolver/mapping model. | Updated to: "driver keys are resolved to SIA template item_ids via `driver_mapping.yaml`. Segment-qualified keys map to specific template input rows. The `raw:` prefix passes literal SIA item_ids for company-specific overrides." |
| 4 | Medium | Architecture API surface framing line says "all scoped by research_file_id except the file list" but Phase 4 handoff-action endpoints use handoff_id. | Updated to: "all scoped by `research_file_id` except the file list and handoff-action endpoints (which use `handoff_id` — a transitive FK to `research_file_id`)." |

**Test delta:** No change (72 tests). Fixes were consistency/propagation corrections.

### R4 — Codex Review (2026-04-11)

**3 findings, all applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | Medium | Architecture doc component diagram (line 86) and ownership row (line 645) only show `handoffs` and `handoffs/{id}/build-model` — missing re-annotate, export, download endpoints added in R2. | Updated diagram endpoint list to include `re-annotate, export, download`. Updated ownership row to list all Phase 4 endpoints. |
| 2 | Medium | Decisions doc "Planning Order" (line 700) references nonexistent `_SPEC.md` files. | Changed references from `RESEARCH_WORKSPACE_PHASE{N}_SPEC.md` to `RESEARCH_WORKSPACE_PHASE{N}_PLAN.md` (the actual files). Phase 5 scope doc noted as "deferred (scope doc TBD)." |
| 3 | Medium | Phase 4 plan test count drift — Step 3 says "Tests (9)" but lists 10, Step 5 says "Tests (8)" but lists 11. | Updated Step 3 header to "Tests (10)" and Step 5 header to "Tests (11)". Summary table already correct. |

**Test delta:** No change (72 tests). Fixes were stale wording/count corrections.

### R5 — Codex Review (2026-04-11)

**3 findings, all applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | Medium | Phase 3 "NOT in Phase 3" says "JSON/PDF/markdown export — Phase 5" but Phase 4 delivers JSON export. | Updated Phase 3 to say "PDF/markdown export — Phase 5 (JSON export is Phase 4)". |
| 2 | Medium | Factor registry still drifting — Step 7 says `factor_pullers.py` but Phase 3 already ships `factor_data_registry.py`. | Updated Step 7 heading to "(Conditional)", file reference to `factor_data_registry.py`, and full conditional text. Updated cross-repo summary to mark factor registry as conditional (not counted as new file if Phase 3 created it). |
| 3 | Low | Test count headers wrong in Phase 2 and Phase 3 — Phase 2 Step 7 says "Tests (11)" but lists 12; Phase 3 Step 1 says "Tests (11)" but lists 13. | Fixed Phase 2 Step 7 to "Tests (12)". Fixed Phase 3 Step 1 to "Tests (13)". Summary tables already correct in both plans. |

**Test delta:** No change (72 tests). Fixes were propagation/consistency corrections.

### R6 — Codex Review (handoff lifecycle split + cross-doc sync)

**6 findings across multiple rounds, all fixed:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | `build_handoff()` lifecycle: plan said create+supersede, architecture said update existing draft | Split into `finalize_handoff()` (updates draft→finalized) + `create_new_version()` (supersedes old, creates v+1 draft). Propagated through Flow 5, REST endpoints (POST /handoffs → POST /handoffs/finalize + POST /handoffs/new-version), frontend hooks, tests. |
| 2 | High | POST /handoffs return shape had 3 variants across docs | Standardized to `{handoff_id, version, ticker, status, artifact_summary}` everywhere |
| 3 | Medium | build_handoff signature drift (user_id param vs factory resolution) | Architecture Flow 5 updated to show `ResearchRepositoryFactory.get(user_id)` → `HandoffService(repo).finalize_handoff()` |
| 4 | Medium | Decisions doc "incremented on regenerate" stale | Changed to "incremented on create_new_version" |
| 5 | Medium | Decisions doc assumptions table still said "matching SIA template" | Changed to "segment-qualified driver keys resolved via driver_mapping.yaml" |
| 6 | Medium | Test summary counts + endpoint counts stale after split | Step 1: 6→8, Step 5: 11→12, Step 8: 14→15, total: 53→76. Cross-repo: 7→8 endpoints. |

**Test delta:** 53 → 76 (+23 across R1-R6).
