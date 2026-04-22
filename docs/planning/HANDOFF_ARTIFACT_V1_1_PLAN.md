# HandoffArtifact v1.1 — Implementation Plan

**Status**: PASS (Codex R5). R1-R4 change logs preserved inline.
**Created**: 2026-04-19
**Design inputs**:
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` — contract shapes (PASS R6), §6.2 + §6.6 + §10a
- `docs/planning/THESIS_LIVING_ARTIFACT_PLAN.md` — plan #1 (PASS R7). Owns the `Thesis` Pydantic type, `schema/thesis_shared_slice.py`, and the boundary-test stub this plan replaces.
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` — skill integration map (updated by plan #1)

**Closes**: G5 (industry research), G9 (section shape inconsistencies), G11 (annotation→assumption lineage), G13-snapshot (thesis snapshot), G14 (enum normalization on Handoff writes), G15 (monitoring polymorphism documented).

**Unblocks**: plan #3 (ModelBuildContext reads HandoffArtifact v1.1), plan #5 (ProcessTemplate id stored on artifact), plan #6 (ModelInsights/PriceTarget back-channel), plan #7 (industry research tools write into `industry_analysis`), plan #10 (editorial pipeline reads v1.1 sections).

---

## 1. Purpose & scope

Evolve the live v1.0 handoff artifact (assembled by `api/research/handoff.py::HandoffService._assemble_artifact`) to v1.1 per §6.2 of the schema doc. Specifically:

1. Pydantic `HandoffArtifact v1.1` type as the Python source of truth, replacing plan #1's `_handoff_v1_1_stub.py`.
2. Derive the shared slice from `Thesis` (plan #1) on snapshot. Preserve Handoff-only fields (`idea_provenance`, `assumption_lineage`, `process_template_id`, `thesis_ref`, Handoff-shaped `model_ref`, `scorecard_ref`) through re-derivation.
3. Inherit `Thesis.sources[]` verbatim as `HandoffArtifact.sources[]` — source IDs persist across snapshots (supersedes current `_SourceRegistry` snapshot-local `src_n` generation).
4. Add stable IDs on list sections (`assumption_id`, `risk_id`, `catalyst_id`, `trigger_id` on `invalidation_triggers`, `claim_id` on `differentiated_view`) via one-time backfill on v1.0 upgrade + forward-propagation from Thesis.
5. Add new fields: `consensus_view`, `differentiated_view`, `invalidation_triggers`, `industry_analysis`, `idea_provenance`, `assumption_lineage`, `process_template_id`, `model_ref`, `scorecard_ref`, `thesis_ref`.
6. Enum canonicalization on write (direction/strategy/timeframe accept Title-Case legacy, emit snake_case).
7. Flip the boundary test from stub to real cross-type check.
8. Backward-read compatibility: v1.0 artifacts continue to deserialize; writes always emit v1.1.

**Non-goals** (deferred):
- `HandoffPatchOp` apply semantics (plan #6). Plan 2 ships the receiver surface (Thesis already has patch receivers from plan #1); application logic is plan #6.
- `ProcessTemplate` authoring (plan #5). Plan 2 reserves the `process_template_id` **Handoff-only field** (per design §10a.5); plan #5 populates it at template activation.
- `InvestmentIdea` ingest (plan #4). Plan 2 reserves `idea_provenance` as a **Handoff-only field** (per design §10a.5); plan #4 populates it at idea ingest.
- Frontend editorial re-rendering for new sections beyond basic `HandoffSectionRenderer` extensions (plan #10 owns rich rendering).
- ModelBuildContext construction (plan #3).

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| A | `HandoffArtifact v1.1` Pydantic type | Replaces stub; composes shared-slice module + Handoff-only fields | ~2 days | Plan #1 sub-phase A |
| B | Update `_build_initial_handoff_artifact` + `_ensure_handoff_artifact` | Emit v1.1 shape; enum canonicalization; new optional fields defaulted | ~2 days | A |
| C | Rewrite `_assemble_artifact` to derive from Thesis | The big one: shared slice from Thesis, Handoff-only preserved, sources inherited, stable IDs propagated | ~4 days | A, B, plan #1 (Thesis read path) |
| D | Migration — v1.0 read + v1.1 write | Readers accept both schema versions; writes emit v1.1; one-time stable-ID backfill on v1.0 → v1.1 upgrade | ~2 days | B |
| E | Stable-ID propagation in `update_handoff_section` | Per-section write path preserves/assigns IDs; enum canonicalization applied | ~2 days | B |
| F | Boundary test flip | Delete `_handoff_v1_1_stub.py`; boundary test imports real `HandoffArtifactV1_1`; golden snapshot updated | ~1 day | A, **plan #1 §13 (boundary test must be landed)** |
| G | Frontend — minimal `HandoffSectionRenderer` extensions | Render `consensus_view`, `differentiated_view`, `invalidation_triggers`, `industry_analysis` | ~3 days | A |
| H | MCP tool surface compatibility | Existing `get_handoff`, `finalize_handoff`, `new_handoff_version`, `build_model` return v1.1; agent-format adapter updated | ~2 days | C, E |
| I | Thesis-absence fallback policy | Define what happens when `finalize_handoff` is called for a research_file that has no Thesis yet | ~1 day | C |

**Total**: ~19 working days. Parallelism: D/E/F/G can run alongside C; H follows C+E.

---

## 3. Dependency graph

```
Plan #1 (Thesis + shared-slice module + stub)  ◄── prerequisite
   │
   ▼
A (v1.1 Pydantic type)
  ├── B (artifact builders)
  │     ├── C (_assemble_artifact rewrite) ◄── reads Thesis via plan #1
  │     │     ├── H (MCP tool return shapes)
  │     │     └── I (Thesis-absence fallback)
  │     ├── D (migration)
  │     └── E (update_handoff_section)
  ├── F (boundary test flip)
  └── G (frontend renderers)
```

**Hard prereqs**:
- Plan #1 sub-phases A (Pydantic types + shared-slice module) and H (boundary test stub) must be landed before plan 2 sub-phases A and F.
- Plan #1 sub-phase B (repository API) must be landed before plan 2 sub-phase C (needs `thesis_repo.get_thesis_by_research_file`, `create_thesis`, `update_thesis_artifact`, `append_decisions_log_entry`).
- Plan #1 sub-phase D (Decisions Log append helper with lock) must be landed before plan 2 sub-phase I (auto-seed path acquires plan #1's lock).
- Plan #1 sub-phases C1/C2 (markdown round-trip) are NOT required for plan 2 — plan 2 doesn't touch THESIS.md directly.

Plan 2 sub-phases G (frontend) and H (MCP) depend only on plan 2 A (the Pydantic type).

---

## 4. Cross-cutting concerns

### 4.1 Thesis as SoT for shared slice

Per §10a.5 of the schema doc, `Thesis` is source of truth for the shared slice; HandoffArtifact v1.1 derives the shared slice verbatim on finalize / new-version. This is the architectural centerpiece of plan 2.

**Consequences**:
- `_assemble_artifact` no longer merges `file_row` + `draft_artifact` + `annotations` for shared-slice fields. It reads the Thesis (via `thesis_repository.get_thesis_by_research_file`) and copies shared-slice sections verbatim.
- `create_new_version` (currently at `handoff.py:125` — deep-copies last finalized artifact) **must also be rewritten to re-derive from Thesis** on every new version, not just finalize. Otherwise drafts created between finalize events serve stale shared-slice data. Sub-phase C covers both paths.
- **Handoff-only fields** (idea_provenance, assumption_lineage, process_template_id, scorecard_ref, thesis_ref, Handoff-shaped model_ref, financials, metadata) are authored on the draft handoff (via dedicated write paths — not shared-slice routes) and preserved through re-derivation (§10a.5 invariant).
- **Shared-slice write paths must all route to Thesis** (R2 — closes R1 high #1 + #2). The full live shared-slice writer surface:

  | Writer | Location | Shared-slice sections touched |
  |---|---|---|
  | `update_handoff_section` | `repository.py:832` | thesis, business_overview, catalysts, valuation, assumptions, risks, peers, ownership, monitoring |
  | `batch_update_handoff_sections` | `repository.py:882` | same 9 sections + qualitative_factors |
  | `add_qualitative_factor` | `repository.py:957` | qualitative_factors |
  | `remove_qualitative_factor` | `repository.py:991` | qualitative_factors |
  | `DiligenceService.update_section` | `diligence_service.py:82` | wraps `update_handoff_section` + stamps `authorship="user"` |

  All 5 writers get the R2 shim: for shared-slice section keys, route to Thesis; for Handoff-only paths (none of these writers actually touch Handoff-only sections today), pass through.

  **Qualitative-factor ID semantics (R4 — closes Codex R3 medium)**: `qualitative_factors[].id` remains **integer-valued** (matches live v1.0 shape at `repository.py:937-982` and `HandoffSectionRenderer.tsx` expectations). No counter migrates to Thesis — Thesis has no `metadata` field (plan #1 §6.6 + design §6.6 make `metadata` explicitly Handoff-only, and the boundary test enforces this).

  **Counter-free ID assignment on the Thesis side**: when a qualitative factor is added to `Thesis.qualitative_factors[]` (via the R2 shim routing `add_qualitative_factor`/`batch_update_handoff_sections`/`update_handoff_section`), the Thesis assignment logic computes `new_id = max(existing_ids, default=0) + 1`. No persistent counter needed.

  **Handoff-side `metadata.next_factor_id`**: remains **Handoff-only per design §10a.5**, not copied from Thesis. Derived post-snapshot by scanning the (shared-slice-derived) `qualitative_factors[]` and setting `metadata.next_factor_id = max([f.id for f in qualitative_factors], default=0) + 1`. This keeps the contract intact: shared slice copies verbatim; metadata is authored on Handoff side from a derived computation.

  Plan #1's note about string/UUID4 stable IDs in §5.2 applies to `assumption_id`/`risk_id`/`catalyst_id`/`trigger_id`/`claim_id` (the five *new* stable-ID fields); `qualitative_factors[].id` is intentionally excluded from that pattern for v1.0 backward compatibility.

- **Exact plan #1 API call path**: plan #1 §6.4 defines `update_thesis_artifact(thesis_id, artifact_json)` (whole-artifact write). The R2 shim composes:
  1. `thesis = thesis_repo.get_thesis_by_research_file(research_file_id)` (creates via auto-seed path §13 if missing).
  2. `new_artifact = {**thesis.artifact_json, section_key: updated_section_wrapper}`.
  3. `thesis_repo.update_thesis_artifact(thesis.thesis_id, new_artifact)`.
  4. `thesis_repo.append_decisions_log_entry(thesis.thesis_id, entry)` with `date` field populated (plan #1 §6.4 API).

  For the MCP-tool layer, plan #1 §12.2 exposes `thesis_update_section` which is the cleaner path when called from the MCP boundary; the shim on the handoff-DB write path (i.e., from within `repository.py`) composes via `update_thesis_artifact` directly (avoids MCP cross-call inside a DB transaction).

  A `DeprecationWarning` is emitted on every shared-slice write via the old path, pointing callers at the Thesis-side API. Shim is removed in follow-on plan 2.5 after call-site audit.

### 4.2 Source registry inheritance (§10a.14)

Currently `_assemble_artifact:170` creates a fresh `_SourceRegistry` each snapshot, generating `src_1…src_N` IDs locally. Under v1.1:

- `Thesis.sources[]` is the canonical registry. Source IDs are assigned by the Thesis backend on first write and persist across snapshots.
- `HandoffArtifact.sources[]` = verbatim copy of `Thesis.sources[]`. No `_SourceRegistry` instantiation at snapshot time for shared-slice sources.
- For citations in Handoff-only sections (e.g., `industry_analysis` citations — WAIT: per R5, industry_analysis is shared-slice, so this case doesn't arise): N/A. Plan 2 explicitly asserts "no Handoff-only section carries source_id citations" (§10a.5 R5 note).
- Legacy v1.0 artifacts being read have their snapshot-local IDs preserved on read; upgrade path on next write (via sub-phase D) ingests the local IDs into Thesis.sources[] if a Thesis exists, or preserves them inline in the v1.1 artifact if no Thesis yet.

### 4.3 Stable-ID handling at the artifact boundary

Stable IDs (§10a.16 — assumption_id, risk_id, catalyst_id, trigger_id, claim_id) are assigned by the Thesis backend. Plan 2 rules:

- **Assembly from Thesis**: IDs copied verbatim. No reassignment.
- **v1.0 upgrade (sub-phase D)**: one-time backfill. On first write of an existing v1.0 draft artifact, assign UUIDs to list items that lack IDs. Finalized/superseded v1.0 artifacts are immutable; their list items remain without stable IDs (readers tolerate missing IDs).
- **Direct handoff-side writes** (legacy `update_handoff_section` path for shared-slice sections): deprecated per §4.1. During the deprecation window, the shim routes to Thesis which handles ID assignment.

### 4.4 Enum canonicalization (§10a.9)

Applied on every write path into v1.1. Reuses `schema/enum_canonicalizers.py` from plan #1. Reads tolerate both Title-Case (legacy v1.0) and snake_case.

### 4.5 Backward-read compatibility

- v1.0 artifacts on disk / in DB remain readable indefinitely. Reader dispatches on `schema_version`.
- v1.0 finalized artifacts are immutable — no backfill, no rewrite.
- v1.0 draft artifacts (if any exist at plan 2 rollout) are upgraded on their next write (`update_handoff_artifact` triggers migration).

### 4.6 Schema version bump

- `schema_version`: `"1.0"` → `"1.1"` on all new writes. `_ensure_handoff_artifact` sets this field.
- DB schema version (`research.db` file-level): **not bumped**. The artifact JSON's `schema_version` is independent of the DB schema. No migration to the `research_handoffs` table DDL.

---

## 5. Sub-phase A — HandoffArtifact v1.1 Pydantic type

### 5.1 Goal

Full `HandoffArtifact v1.1` Pydantic type in `schema/handoff.py` replacing `schema/_handoff_v1_1_stub.py` from plan #1.

### 5.2 Design

**Imports from plan #1's `schema/thesis_shared_slice.py`** (16 shared-slice types). Plan 2 does NOT redeclare them — any drift would break the isomorphism invariant (§10a.13).

**Handoff-only fields** (8) declared in `schema/handoff.py`:
- `idea_provenance: IdeaProvenance | None`
- `assumption_lineage: list[AssumptionLineageEntry] | None`
- `process_template_id: str | None`
- `scorecard_ref: ScorecardRef | None` — `{scorecard_id, version, scored_at, summary_status}`
- `thesis_ref: ThesisRef | None` — `{thesis_id, version, markdown_path}`
- `model_ref: HandoffModelRef | None` — Handoff-shaped: `{model_id, version, model_build_context_id, model_build_context_version, last_price_target?}`
- `financials: Financials | None` (existing in v1.0)
- `metadata: HandoffMetadata` — `{diligence_completion, diligence_sections, next_factor_id, analyst_session_id?}` (existing in v1.0)

**Top-level fields**: `schema_version: Literal["1.1"]`, `handoff_id: int`, `created_at: float`, `research_file_id: int`.

**Enum canonicalization**: `thesis.direction/strategy/timeframe` fields use validators from `schema/enum_canonicalizers.py` (shared with Thesis and IdeaPayload).

### 5.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `schema/handoff.py` | `HandoffArtifactV1_1` + Handoff-only types | ~400 |
| `tests/schema/test_handoff_types.py` | Pydantic unit tests | ~300 |

### 5.4 Files to delete

| File | Reason |
|---|---|
| `schema/_handoff_v1_1_stub.py` | Replaced by real type; plan #1 boundary test imports shift |

### 5.5 Tests (~30)

- Pydantic validation of all 16 shared-slice fields (imported from plan #1 module — drift-proof)
- Handoff-only field validation (8 fields × valid/invalid = 16)
- Enum canonicalization on write (3 fields × Title-Case + snake_case)
- `schema_version` literal enforcement (1)
- Roundtrip JSON ↔ Python (4)

### 5.6 Acceptance gate

- All tests pass.
- `schema/_handoff_v1_1_stub.py` deleted; no references remain.
- Plan #1 boundary test imports flipped to real `HandoffArtifactV1_1`.

### 5.7 Rollback

Restore stub (revert delete), revert new file. Plan #1 boundary test keeps passing (stub was equivalent shape).

---

## 6. Sub-phase B — Update artifact builders

### 6.1 Goal

Update `_build_initial_handoff_artifact` + `_ensure_handoff_artifact` in `api/research/repository.py` to emit v1.1 shape with new optional fields defaulted.

### 6.2 Design

**`_build_initial_handoff_artifact(file_row, created_at)`** (repository.py:182):
- Emit `schema_version: "1.1"`.
- Add defaulted fields: `consensus_view: None`, `differentiated_view: []`, `invalidation_triggers: []`, `industry_analysis: None`, `idea_provenance: None`, `assumption_lineage: None`, `process_template_id: None`, `model_ref: None`, `scorecard_ref: None`, `thesis_ref: None`.
- `metadata` adds `diligence_sections: {}`, `next_factor_id: 1` (already present in v1.0 — preserved for backward compat as Handoff-only per design §10a.5. Under v1.1, `next_factor_id` is recomputed post-derivation from `max(qualitative_factors[*].id) + 1` per §4.1 R4 rule — not sourced from Thesis).

**`_ensure_handoff_artifact(artifact, file_row, created_at)`** (repository.py:222):
- Gate on `schema_version`:
  - `None` or `"1.0"` → run v1.0 normalization path AND append v1.1 defaults (upgrade on access).
  - `"1.1"` → run v1.1 normalization (ensures all v1.1 fields present and correctly typed).
- Apply enum canonicalization on `thesis.direction/strategy/timeframe` regardless of input version (idempotent on snake_case input).

### 6.3 Files to modify

| File | Change |
|---|---|
| `api/research/repository.py` | Update two builder functions (~100 new lines) |
| `tests/api/research/test_repository_handoff_builders.py` | New test module (~250 lines) |

### 6.4 Tests (~25)

- Initial artifact emits v1.1 shape (3)
- `_ensure_handoff_artifact` with v1.0 input upgrades shape (5)
- `_ensure_handoff_artifact` with v1.1 input is idempotent (3)
- Enum canonicalization on each write (6)
- Defaulted fields present in fresh artifact (8)

### 6.5 Acceptance gate

- All fresh writes emit v1.1.
- Existing tests (that read v1.0 artifacts) still pass via the upgrade path.

### 6.6 Rollback

Revert builder changes. v1.0 emission resumes; v1.1 readers in plan 2 downstream must tolerate v1.0 (already do per §4.5).

---

## 7. Sub-phase C — Rewrite `_assemble_artifact` AND `create_new_version` to derive from Thesis

### 7.1 Goal

The central sub-phase. Two paths must derive shared slice from Thesis:
1. **`HandoffService._assemble_artifact`** (handoff.py:157) — runs on finalize.
2. **`HandoffService.create_new_version`** (handoff.py:125) — currently deep-copies the last finalized artifact (R2 — closes R1 high #3). Under v1.1 it must re-derive from the current Thesis to avoid serving stale shared-slice data in the new draft.

Both paths share the derivation routine; `create_new_version` additionally preserves Handoff-only fields from the prior finalized artifact (idea_provenance, model_ref, etc. — see §7.2 rules).

### 7.2 Design

**New algorithm** (replaces current implementation at `handoff.py:157-316`):

```
1. Fetch Thesis for research_file_id via thesis_repository.get_thesis_by_research_file().
   - If None (Thesis-absence): apply §4.1 fallback per sub-phase I.
2. Fetch draft_artifact from research_handoffs (existing handoff.py logic).
3. Build the v1.1 artifact:

   # Shared slice — verbatim from Thesis (16 fields)
   company            = thesis.company
   thesis             = thesis.thesis            # {statement, direction, strategy, conviction,
                                                 #  timeframe, source_refs}
   consensus_view     = thesis.consensus_view
   differentiated_view = thesis.differentiated_view
   invalidation_triggers = thesis.invalidation_triggers
   business_overview  = thesis.business_overview
   catalysts          = thesis.catalysts
   risks              = thesis.risks
   valuation          = thesis.valuation
   peers              = thesis.peers
   assumptions        = thesis.assumptions
   qualitative_factors = thesis.qualitative_factors
   ownership          = thesis.ownership
   monitoring         = thesis.monitoring
   sources            = thesis.sources          # R5: verbatim, preserves src_n IDs
   industry_analysis  = thesis.industry_analysis

   # Handoff-only — preserved from draft_artifact, NEVER overwritten by Thesis
   idea_provenance    = draft_artifact.get("idea_provenance")
   assumption_lineage = draft_artifact.get("assumption_lineage")
   process_template_id = draft_artifact.get("process_template_id")
   scorecard_ref      = draft_artifact.get("scorecard_ref")  # R2: preserve if present;
                        # ONLY populate from thesis_repo.latest_scorecard() when the
                        # draft_artifact has no scorecard_ref at all (first snapshot
                        # after scorecard run). Never overwrite an existing value.
   thesis_ref         = {thesis_id: thesis.thesis_id,
                         version: thesis.version,
                         markdown_path: thesis.markdown_path}  # computed per snapshot
                                                               # (the ONE Handoff-only
                                                               # field that refreshes on
                                                               # every assembly — it
                                                               # points at the snapshot's
                                                               # source Thesis version)
   model_ref          = draft_artifact.get("model_ref")        # Handoff-shape
   financials         = draft_artifact.get("financials")       # existing
   metadata           = draft_artifact.get("metadata")         # existing
   # R4 — recompute metadata.next_factor_id from the derived qualitative_factors[]
   # per §4.1 Handoff-only rule. Never carry the stale counter forward verbatim.
   metadata["next_factor_id"] = max(
       [int(f.get("id", 0)) for f in (qualitative_factors or [])],
       default=0,
   ) + 1

4. Validate via HandoffArtifactV1_1 Pydantic type before persist.
5. Return as dict[str, Any] matching existing callers' expectations.
```

**Removed from old algorithm**:
- `_SourceRegistry` instantiation per assembly (sources inherited now).
- `with_section_refs` per-section source ref threading (sources already typed in Thesis).
- `_normalize_annotation_source` / `_section_key_from_diligence_ref` per-section merging (annotations are Thesis's concern now; `assumption_lineage` captures annotation → assumption back-links on Handoff side).
- Per-section wrapper construction via `DILIGENCE_SECTION_KEYS` (Thesis already typed).

**Preserved**:
- `handoff_id`, `created_at`, `research_file_id` top-level fields.
- `_serialize_summary` (handoff.py:317) — preserves v1.0 summary shape but extended in sub-phase H to include v1.1 headline fields (`differentiated_view_count`, `invalidation_trigger_count`, `industry_analysis_present` bool) for agent-format flag generation. Existing `thesis_statement`, `assumptions`, `qualitative_factors`, `sources` counts in the summary dict remain unchanged.

**`create_new_version(research_file_id)` algorithm** (R2 — closes R1 high #3):

```
1. Lookup current finalized handoff: prior = repo.get_latest_handoff(research_file_id, status='finalized').
   If None → raise "no finalized handoff to supersede" (existing behavior).
2. Acquire plan #1 filesystem lock on (user_id, ticker, label) — see §16 risks.
3. Supersede prior (existing: repo.supersede_handoff).
4. Fetch current Thesis via thesis_repo.get_thesis_by_research_file().
   If None → §13 auto-seed path.
5. Build new draft artifact:
   - Shared slice: copied verbatim from Thesis (same rules as _assemble_artifact above).
   - Handoff-only: copied from the superseded finalized artifact (preserves
     idea_provenance / assumption_lineage / process_template_id / model_ref / scorecard_ref).
     thesis_ref recomputed to current Thesis version.
   - metadata.next_factor_id explicitly RECOMPUTED from the new shared-slice-derived
     qualitative_factors[] (never carried over stale). Applies same formula as
     _assemble_artifact step above.
6. Create new draft handoff with assembled artifact via repo.create_handoff(status='draft').
7. Release lock. Return draft summary.
```

Rationale: under v1.1, between finalize events, Thesis may have been updated (via new data, skills, patches). A new-version draft must reflect the current Thesis state, not the prior snapshot.

**Source-ID migration algorithm** (R2 — closes R1 medium #1):

On v1.0 → v1.1 upgrade at a draft handoff:

- **Case 1 — no existing Thesis** (first finalize triggering §13 auto-seed): v1.0 `sources[]` with local `src_N` IDs moved verbatim to `Thesis.sources[]`. IDs preserved. All `source_refs` in v1.0 artifact already point at these IDs — still valid post-inheritance.
- **Case 2 — existing Thesis** (`thesis_repo.get_thesis_by_research_file` returns existing Thesis):
  1. Content-dedupe: for each v1.0 source, check if Thesis.sources already has an entry with identical `(type, source_id, section_header?, char_start?, char_end?)` tuple.
  2. For matches: rewrite v1.0 `source_refs` entries from `src_OLD` → `src_NEW_MATCHED` everywhere they appear (across all section wrappers and qualitative_factors).
  3. For non-matches: append to `Thesis.sources[]` assigning fresh `src_N+1, src_N+2, ...`. Rewrite v1.0 source_refs similarly.
  4. Validate: all source_refs in the migrated v1.1 artifact resolve against the unified registry.
  5. Log a structured `source_migration` entry to `Thesis.decisions_log` (skill=`handoff_migration_v1_0_to_v1_1`, rationale="merged N sources from v1.0 draft").

This is a one-shot algorithm run once per draft artifact during its first write under v1.1. Finalized v1.0 artifacts are never touched.

### 7.3 Files to modify

| File | Change |
|---|---|
| `api/research/handoff.py` | Rewrite `_assemble_artifact` (~200-line net change) |
| `api/research/handoff.py` | Remove `_SourceRegistry`, `_normalize_source_ref`, etc. (cleanup) |
| `tests/api/research/test_handoff_service.py` | Update existing tests + add v1.1 coverage (~400 new lines) |

### 7.4 Tests (~35)

- Shared slice copied verbatim from Thesis (16 fields checked)
- Handoff-only fields preserved through re-derivation (8 fields, each set in draft → present in finalized)
- **R4**: `metadata.next_factor_id` explicitly RECOMPUTED post-derivation, NOT preserved (2 tests: empty qualitative_factors → `next_factor_id=1`; non-empty → `max(id)+1`; stale draft counter discarded)
- Sources inherited verbatim (2 tests: IDs preserved, no snapshot-local generation)
- `thesis_ref` computed correctly on each snapshot (2)
- Thesis-absence path (4 — see sub-phase I)
- Regression: existing tests covering v1.0 assembly flow (~8 updated to new shape)

### 7.5 Acceptance gate

- `_assemble_artifact` returns validated `HandoffArtifactV1_1` dict.
- Thesis shared-slice byte-for-byte identical on both sides post-derivation.
- Handoff-only fields NEVER overwritten by derivation.
- Existing `handoff_routes.py` + `research_gateway` integration tests pass without change.

### 7.6 Rollback

Restore old `_assemble_artifact`. Requires reverting sub-phases B, D, E, H as well (they depend on v1.1 shape). Rollback is atomic with those.

---

## 8. Sub-phase D — Migration: v1.0 read + v1.1 write

### 8.1 Goal

Read path tolerates v1.0 + v1.1; write path emits v1.1. One-time stable-ID backfill on first write of v1.0 drafts.

### 8.2 Design

**Read path** (any function returning an artifact):
- Dispatch on `artifact.schema_version`:
  - `"1.0"` or missing → apply `_v1_0_upgrade_shim` (adds defaults for new fields; leaves existing fields untouched). Does NOT persist back — read-only upgrade for callers.
  - `"1.1"` → pass through Pydantic validation and return.

**Write path** (`update_handoff_artifact`, `create_handoff`, finalize flow):
- Always validate via `HandoffArtifactV1_1`.
- Emit `schema_version: "1.1"`.
- On write of a v1.0 draft, apply stable-ID backfill: for each list section (`assumptions`, `risks`, `catalysts`, `differentiated_view`, `invalidation_triggers`), assign UUID4 to items lacking an ID. Log the backfill count for observability.

**Finalized v1.0 artifacts**: left immutable. Readers normalize to v1.1 shape in memory but never write back.

**Enum canonicalization on v1.0 → v1.1 upgrade**: Title-Case legacy values (`"Long"`, `"Value"`, `"Near-term"`) canonicalized to snake_case on first write.

### 8.3 Files to modify

| File | Change |
|---|---|
| `api/research/repository.py` | Add `_v1_0_upgrade_shim` + integrate into `_ensure_handoff_artifact` |
| `api/research/handoff.py` | ID-backfill helper in write path |
| `tests/api/research/test_handoff_migration.py` | New (~350 lines) |

### 8.4 Tests (~20)

- v1.0 draft read → shape is v1.1 in memory; DB row unchanged (3)
- v1.0 draft first-write → DB row now v1.1 with backfilled IDs (5)
- v1.0 finalized read → shape normalized; DB never written (3)
- Enum canonicalization on v1.0 → v1.1 upgrade (4)
- Backfill count logged (2)
- Idempotent: v1.1 → v1.1 write = no-op migration (3)

### 8.5 Acceptance gate

- Existing v1.0 artifacts in test fixtures read as v1.1 in memory.
- Never writes back to v1.0 finalized rows.
- Backfilled IDs survive subsequent reads.

### 8.6 Rollback

Remove `_v1_0_upgrade_shim`; backfill helper. Readers still tolerate v1.0 if writers stop emitting v1.1.

---

## 9. Sub-phase E — Stable-ID propagation in `update_handoff_section`

### 9.1 Goal

Per-section write path (`repository.py:832::update_handoff_section`) assigns stable IDs to new list items + preserves existing IDs.

### 9.2 Design

**For shared-slice sections** (all 10 per §4.1 table: thesis, business_overview, catalysts, valuation, assumptions, risks, peers, ownership, monitoring, qualitative_factors):
- Per §4.1 deprecation: emit `DeprecationWarning` pointing to the MCP-layer `thesis_update_section` tool (plan #1 §12.2) for analyst/agent callers.
- Temporary shim at the repository layer (R3 — fixes R2 medium #1): route updates via **the same compose flow as §4.1** — `get_thesis_by_research_file` → mutate one section in the artifact dict → `update_thesis_artifact(thesis_id, new_artifact)`. This uses only plan #1's passed repository API. No reference to `thesis_repository.update_thesis_section` (that API does not exist in plan #1 — it's an MCP tool name, not a repo method).
- The shim additionally updates the draft handoff artifact for legacy readers; the shim is removed in a follow-on plan 2.5 once all callers migrate to Thesis-side writes.

**For Handoff-only section write paths** (not currently exposed, but plan 2 adds e.g., `update_idea_provenance`, `update_assumption_lineage`, `update_model_ref`, `update_scorecard_ref`):
- Operate directly on the draft handoff artifact.
- Use the field shapes locked in design doc §6.2 for each section. No invented IDs — e.g., `assumption_lineage[]` uses the design-locked `{assumption_id, supporting_annotation_ids, refutes_annotation_ids?}` shape (R2 fix — R1 invented an `entry_id` not in the contract).
- Apply enum canonicalization to any enum field.

### 9.3 Files to modify

| File | Change |
|---|---|
| `api/research/repository.py` | Update `update_handoff_section` + add Handoff-only write helpers |
| `api/research/handoff.py` | Deprecation shim |
| `tests/api/research/test_update_handoff_section.py` | Extend existing + add Handoff-only tests (~200 new lines) |

### 9.4 Tests (~18)

- DeprecationWarning emitted for shared-slice section writes (5)
- Shim routes shared-slice to Thesis and updates draft artifact (5)
- Handoff-only write helpers assign IDs (4)
- Enum canonicalization on write (2)
- Idempotent re-write preserves IDs (2)

### 9.5 Acceptance gate

- DeprecationWarning surfaces with migration path.
- No ID collisions on concurrent writes.
- Handoff-only writes operate on draft artifact only.

### 9.6 Rollback

Remove shim + deprecation warnings. `update_handoff_section` reverts to v1.0 direct-edit behavior.

---

## 10. Sub-phase F — Boundary test flip

### 10.1 Goal

Replace plan #1's stub-based boundary test with a true cross-type check using real `HandoffArtifactV1_1`.

### 10.2 Design

- Delete `schema/_handoff_v1_1_stub.py` (already handled in sub-phase A).
- Update `tests/integration/test_shared_slice_isomorphism.py`:
  - Import `HandoffArtifactV1_1` from `schema/handoff.py`.
  - All existing tests (`test_shared_slice_fields_identical`, `test_handoff_only_fields_not_in_thesis`, `test_thesis_only_fields_not_in_handoff`) now check real types.
  - Golden snapshot: rename `tests/schema/snapshots/handoff_v1_1_stub.schema.json` → `handoff_v1_1.schema.json`. Regenerate from real type. PR reviews the diff.

### 10.3 Files to modify

| File | Change |
|---|---|
| `tests/integration/test_shared_slice_isomorphism.py` | Stub import → real import |
| `tests/schema/snapshots/handoff_v1_1_stub.schema.json` | Renamed to `handoff_v1_1.schema.json`, regenerated |

### 10.4 Tests (~8 — same as plan #1's test count, now against real types)

### 10.5 Acceptance gate

- All 8 boundary tests green against real type.
- Snapshot refreshed + reviewed.
- No remaining reference to `_handoff_v1_1_stub` anywhere in repo.

### 10.6 Rollback

Restore stub (plan #1 state). Boundary test reverts.

---

## 11. Sub-phase G — Frontend HandoffSectionRenderer extensions

### 11.1 Goal

Render the four new sections in the workspace UI: `consensus_view`, `differentiated_view`, `invalidation_triggers`, `industry_analysis`. Minimal — plan #10 owns rich editorial rendering.

### 11.2 Design

Four new `SectionRenderer` functions added to `HandoffSectionRenderer.tsx`:

- `renderConsensusView` — `{narrative, citations: [source_id]}` → narrative prose + source chips
- `renderDifferentiatedView` — list of `{claim_id, claim, rationale, evidence, upside_if_right, downside_if_wrong}` → card per claim with claim title, rationale, evidence chips, upside/downside metrics
- `renderInvalidationTriggers` — list of `{trigger_id, description, metric?, threshold?, direction?}` → compact list with metric+threshold where populated
- `renderIndustryAnalysis` — `{landscape?, peer_comparison?, macro_overlay?, structural_trends?}` → nested sub-sections

Section-key dispatcher (existing pattern in `HandoffSectionRenderer.tsx:58`) extended to route these four keys to the new renderers.

### 11.3 Files to modify

| File | Change |
|---|---|
| `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx` | Add 4 renderers + dispatch |
| `frontend/packages/ui/src/components/research/HandoffSectionRenderer.test.tsx` | New test coverage (~200 lines) |

### 11.4 Tests (~16)

- Each renderer with valid input (4)
- Each renderer with empty/missing input (4)
- Source chip resolution from `sourcesById` (2)
- Section-key dispatch (4 new keys routed correctly)
- Graceful fallback for v1.0 artifact (sections missing → no rendering) (2)

### 11.5 Acceptance gate

- All 4 new sections render with real v1.1 artifact fixtures.
- v1.0 artifacts still render (new sections simply absent).
- Design matches existing renderer style (see plan #10 for editorial polish).

### 11.6 Rollback

Remove 4 renderers + dispatcher entries. Workspace UI still renders v1.0 + shared-slice from v1.1 (other renderers unchanged).

---

## 12. Sub-phase H — MCP tool surface compatibility

### 12.1 Goal

Existing handoff-returning MCP tools (`get_handoff`, `finalize_handoff`, `new_handoff_version`, `build_model`) return v1.1 artifacts. Agent-format adapter includes new fields in snapshot.

### 12.2 Design

Current MCP tools in `risk_module/mcp_tools/research.py` delegate to `actions/research.py` → gateway → AI-excel-addin `api/research/handoff.py`. Plan 2 changes:

- No signature changes to MCP tools.
- Agent-format snapshot builder (in `actions/research.py` or a dedicated `research_flags.py`) extended to include v1.1 fields.
- Flag generation (`core/research_flags.py` referenced at `mcp_tools/research.py:14`) adds flags for:
  - `differentiated_view` absent on a finalized handoff (warning: "no differentiated view captured")
  - `invalidation_triggers` empty on a finalized handoff (warning)
  - `industry_analysis` absent when `strategy` is `special_situation` or `macro` (context-dependent hint)
  - `scorecard_ref.summary_status` surfaced as flag severity (invalidated → error, at_risk → warning)

**V1.0 legacy gating** (R2 — closes R1 medium #4): **all new-section warnings are gated on `artifact.schema_version == "1.1"`**. V1.0 finalized artifacts (legacy) are normalized to v1.1 shape in memory via §8.2, but the normalization layer stamps `_original_schema_version = "1.0"` on the returned dict. Flag generation reads this tag and skips new-section warnings for legacy artifacts — they predate those sections and flagging them creates noise. Only artifacts that were actually written under v1.1 (and thus had the opportunity to populate the new sections) get the warnings.

### 12.3 Files to modify

| File | Change |
|---|---|
| `risk_module/actions/research.py` | Extend snapshot builders (~100 new lines) |
| `risk_module/core/research_flags.py` | Add v1.1 flags |
| `risk_module/mcp_tools/research.py` | No changes (delegation unchanged) |
| `tests/mcp_tools/test_research_tools.py` | Extend coverage |

### 12.4 Tests (~15)

- `get_handoff` returns v1.1 shape (3)
- `finalize_handoff` returns finalized v1.1 (3)
- `new_handoff_version` drafts v1.1 (2)
- Agent-format snapshot includes v1.1 fields (4)
- New flags generate correctly (3)

### 12.5 Acceptance gate

- All existing MCP tool contracts work with v1.1 payloads.
- Agent flag generation covers new fields.

### 12.6 Rollback

Revert flag additions; MCP tools keep returning whatever `handoff.py` emits (auto-reverts with C rollback).

---

## 13. Sub-phase I — Thesis-absence fallback

### 13.1 Goal

Define behavior when `finalize_handoff` is called for a research_file that has no Thesis yet (e.g., legacy research_files created before plan #1 lands, or a research_file where the analyst skipped the thesis-consultation flow).

### 13.2 Design

**Decision (locked here, pending Codex review)**: **auto-create a Thesis from the current draft handoff artifact on `finalize_handoff`**.

Rationale:
- Forcing an explicit Thesis creation step breaks existing workflows (research_files → finalize → handoff is a well-worn path).
- Auto-creating a Thesis from the draft preserves the Thesis-is-SoT invariant going forward (subsequent re-derivation pulls from Thesis).
- The draft artifact already has all shared-slice fields (in v1.0 form); plan 2's v1.0 → v1.1 upgrade + Thesis seed is a natural composition.

**Algorithm** (runs inside `_assemble_artifact` and `create_new_version` when Thesis is None — R2 rewrite for plan #1 API compatibility):

1. Read draft_artifact (v1.0 or v1.1).
2. If v1.0 → apply v1.0→v1.1 in-memory upgrade per §8.2 (shape only, no write yet).
3. Create empty Thesis via **`thesis_repo.create_thesis(research_file_id)`** — plan #1 §6.4 signature; no `initial_fields` assumption. This creates the thesis row with empty shared-slice.
4. Seed shared slice: build a new full artifact dict from the upgraded draft's shared-slice fields, then call **`thesis_repo.update_thesis_artifact(thesis.thesis_id, seeded_artifact)`** (plan #1 §6.4 API — whole-artifact write).
5. Run source-ID migration per §7.2 "Case 1 — no existing Thesis" — sources moved verbatim from v1.0 draft to Thesis.sources[].
6. Append decisions-log entry via **`thesis_repo.append_decisions_log_entry(thesis.thesis_id, entry)`** (plan #1 §6.4 + §8 API — stored in `thesis_decisions_log` table, NOT in `artifact_json`).

   Entry shape per design §6.6 + plan #1 `DecisionsLogEntry`:
   ```python
   DecisionsLogEntry(
       entry_id=None,  # plan #1 §6.2 autofills via UUID4
       date="2026-04-19",              # REQUIRED — was missing in R1
       skill="handoff_auto_seed",
       decision="Seeded Thesis from draft handoff artifact at finalize",
       rationale="Thesis missing at finalize_handoff; auto-created per plan 2 §13",
       previous_value=None,
       new_value=None,
       patch_ops_applied=None,
   )
   ```
7. Proceed with normal derivation now that Thesis exists.

**No plan #1 amendment required** (R3 — clarifies R2 contradictory wording): plan 2's auto-seed flow uses the three-step composition (`create_thesis` → `update_thesis_artifact` → `append_decisions_log_entry`), all of which are plan #1 §6.4 APIs exactly as PASSed. Plan #1's `create_thesis(research_file_id, initial_fields=None)` signature has `initial_fields` as a forward-compat hook, but plan 2 does not use it — the `update_thesis_artifact` call handles shared-slice seeding cleanly.

**Alternative rejected**: fail with `ThesisRequired` error and require an explicit thesis-consultation step. Too disruptive for existing research files. Opt-out via `HANDOFF_REQUIRE_THESIS=1` env flag (see §16 risks).

**Guardrails**:
- Auto-creation is logged (observability: per-user count of auto-creations over time).
- Auto-created Theses start at `version=1` (plan #1 §6.2). Decisions Log entry is appended via the plan #1 typed path — never inline in artifact_json.
- If the Thesis was auto-created with empty new v1.1 fields (`consensus_view`, `differentiated_view`, `invalidation_triggers`, `industry_analysis` all null), the finalize flow emits a non-blocking warning recommending the analyst run `/thesis-review` to populate these.
- Per plan #1 §4.6 lock semantics: the auto-seed path acquires the per-(user_id, ticker, label) filesystem lock around steps 3-6 to prevent two concurrent `finalize_handoff` calls from racing to create duplicate Theses. The UNIQUE(research_file_id) constraint (plan #1 §6.2) is belt-and-suspenders.

### 13.3 Files to modify

| File | Change |
|---|---|
| `api/research/handoff.py` | Add auto-seed path in both `_assemble_artifact` AND `create_new_version` |
| `tests/api/research/test_handoff_thesis_absence.py` | New (~250 lines) |

### 13.4 Tests (~12)

- Finalize with no Thesis → Thesis auto-created (3)
- Auto-created Thesis shared-slice matches draft (3)
- Decisions log entry present post-auto-seed (1)
- Warning surfaced when new v1.1 fields are empty (2)
- Subsequent `new_handoff_version` uses the auto-created Thesis as SoT (3)

### 13.5 Acceptance gate

- Backward compat: every existing research_file continues to flow through finalize without breaking.
- Auto-seed is observable (log + decisions_log entry).
- Tests verify SoT inversion happens cleanly on first finalize.

### 13.6 Rollback

Replace auto-seed with `ThesisRequired` error; callers must then pre-create Thesis. Breaks backward compat. Only roll back if auto-seed causes unexpected drift.

---

## 14. Testing summary

- Unit tests per sub-phase: ~179 total.
- Integration: v1.0 → v1.1 upgrade round-trip, Thesis-SoT derivation end-to-end, MCP tool return shape.
- Frontend: renderer tests for 4 new sections + v1.0 backward compat.
- Boundary: plan #1's ~8 tests now green against real type (F).

---

## 15. Rollout sequencing

**Week 1**: A (2 days) + F (1 day) + G drafting (3 days starting in parallel). Plan #1 implementation gates C.
**Week 2**: B (2 days) + D (2 days, parallel). G ships (3 days continue from week 1). Plan #1 implementation completes.
**Week 3**: C (4 days) — the critical-path rewrite. E (2 days, parallel).
**Week 4**: H (2 days) + I (1 day). Integration smoke (2 days).

Total: ~19 working days with parallelism.

Sub-phase H and I require C; everything else can progress on plan #1 timeline.

---

## 16. Risks

| Risk | Mitigation |
|---|---|
| Plan #1 Thesis shape drifts during its implementation | Boundary test (plan #1 H) is the guardrail; any shared-slice change in plan #1 must update both `thesis_shared_slice.py` AND this plan's Pydantic import. Plan #1 PRs enforce it. |
| `_assemble_artifact` rewrite breaks existing handoff consumers (routes/MCP/frontend) | Shared-slice fields are byte-identical pre/post-rewrite; only shape additions. Existing consumers ignore unknowns. Test coverage includes regression on every existing handoff-returning endpoint. |
| Source registry inheritance breaks existing source IDs on v1.0 → v1.1 upgrade | v1.0 finalized artifacts untouched (immutable). v1.0 draft migration: inherit existing local `src_n` IDs into Thesis.sources[] — preserves IDs across the upgrade. |
| Thesis-absence fallback (§13) creates semantic surprises | Opt-out path: fail with `ThesisRequired` if `HANDOFF_REQUIRE_THESIS=1` env flag set (useful for strict deployments). Default is auto-seed. |
| DeprecationWarning shim (§9) doesn't force migration; callers keep using shared-slice `update_handoff_section` | Shim is a 2-phase removal: plan 2 emits warning; follow-on plan deletes shim after call-site audit. |
| Concurrent Thesis update + handoff derivation produces stale snapshot | **Lock-based serialization (R2 — drops misleading "single transaction" claim from R1)**: `_assemble_artifact` and `create_new_version` both acquire plan #1's per-(user_id, ticker, label) filesystem lock (§4.6 of plan #1) before reading Thesis. The lock serializes Thesis writes and handoff derivations for a given research file. This is not ACID across two repositories, but it is sufficient for the single-user-per-research-file semantics of the workspace. Release on normal or error exit. Timeout: 5s (matches plan #1 §9.2). |

---

## 17. Acceptance gate

- All 9 sub-phases committed, tests green.
- Boundary test F passes with real type on all 3 directions.
- `_assemble_artifact` rewrite: existing routes/MCP/frontend tests green; no regression.
- `SKILL_CONTRACT_MAP.md` updates:
  - "Primary reference" table: `HandoffArtifact v1.1` row Location changes `(planned)` → actual file path.
  - `Location` column for shared-slice contracts now refers to `schema/thesis_shared_slice.py` (since both Thesis and HandoffArtifact import from it).
  - Integration patterns §3 (Earnings / actuals skill proposing patches) updated to note `HandoffPatchOp`s now flow through Thesis (plan 2 rule per §4.1).
- `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §12 follow-on plan table: plan 2 row marked ✓ shipped.
- End-to-end smoke: create research_file → start_research → prepopulate_diligence → finalize_handoff → verify v1.1 artifact includes shared-slice from Thesis (SoT) and Handoff-only fields preserved.

---

## 18. Out of scope

- `HandoffPatchOp` apply semantics (plan #6).
- `ProcessTemplate` authoring flow (plan #5).
- `InvestmentIdea` ingestion UI (plan #4).
- Editorial rendering for new sections beyond minimal (plan #10).
- Schema migration of `research_handoffs` DDL (artifact JSON evolves, table shape unchanged).
- Multi-user handoff access / sharing (future).

---

## 19. Follow-on (post-plan-2)

- Plan #3 (ModelBuildContext) reads `HandoffArtifact v1.1.assumptions[].driver` directly; `build_model` MCP tool consumes v1.1.
- Plan #4 (InvestmentIdea) populates `HandoffArtifact.idea_provenance` at research-file creation.
- Plan #5 (ProcessTemplate) populates `HandoffArtifact.process_template_id` on first activation.
- Plan #6 (ModelInsights/PriceTarget/HandoffPatchOp) reads `HandoffArtifact.model_ref` and writes `HandoffArtifact.assumption_lineage`.
- Plan #7 (industry research tools) writes to `Thesis.industry_analysis` (shared-slice; flows to Handoff automatically).
- Plan #10 (research editorial pipeline) renders rich v1.1 artifacts for PDF/export.
- **Deprecation removal**: the shim from §4.1 + §9 gets removed in a follow-on plan 2.5 once shared-slice `update_handoff_section` callers have migrated to Thesis-side writes.
