# F125 — Evidence Layer Audit Backbone

**Status:** **SHIPPED 2026-05-28** in AI-excel-addin across PR-A `7b6b9281` + PR-B `3a77105c` + PR-C `953425f6` + PR-A1 `4f680bdd` (markdown excerpt round-trip latent gap discovered via 3 live F131 runs, fixed via shared preservation helper). Mutation-aware `validate_mutation` enforces R1 (per-cited-source) + R9 (new-edge) at both write checkpoints (patch engine + `_persist_thesis_payload`), R6 detector at `api/research/f125_r6_adapter.py` (the path F131's `thesis_e2e_audit` dynamic-imports) reused for write-time batch + audit-time invariant, derived-claim carry-forward via explicit `WatchItem.derived_from_handle/derived_from_kind` lineage. 1676 unit tests + schema smoke PASS; live-verified end-to-end via `load_thesis(user_id='1', research_file_id=1157)` returning 4 sources / 6 excerpts. Local plan: `AI-excel-addin/docs/design/completed/f125-pr2-pr3-impl-plan.md` + `AI-excel-addin/docs/design/completed/f125-pr-a1-markdown-excerpt-roundtrip.md`. **Original status — In progress 2026-05-23. Phase A/B + compatibility-mode audit hook implemented locally; strict new-write enforcement, direct-write integration, annotation render-cache alignment, and skill-contract updates remain** (preserved for history).
**Closes:** Research Artifact Layers D1, D4, D7, D9; supports R1, R4, R5, R6, R9, R11.
**Blocks:** F129 monitoring / exit reassessment agent, because autonomous writes need a replayable audit chain before scheduled agents mutate Thesis state.
**Verification so far:** `python3 -m pytest tests/api/research/test_patch_engine.py tests/api/research/test_repository_thesis.py tests/api/research/test_update_handoff_section.py tests/api/research/test_thesis_log_helpers.py tests/integration/test_shared_slice_isomorphism.py tests/api/research/test_evidence_audit.py tests/research/test_patch_engine_register_sources.py tests/schema/test_source_registry.py tests/schema/test_thesis_types.py tests/schema/test_thesis_markdown.py -q` -> 450 passed.
**Design inputs:**
- [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md) D1, D4, D7, D9 and R1/R4/R5/R6/R9/R11.
- [`THESIS_WRITE_SURFACE_COVERAGE.md`](THESIS_WRITE_SURFACE_COVERAGE.md) Layer 1 / Layer 2 write-surface matrix.
- [`F124_THESIS_WATCHLIST_OWNERSHIP_WIRING_PLAN.md`](completed/F124_THESIS_WATCHLIST_OWNERSHIP_WIRING_PLAN.md) §8.5 F125 compatibility contract.

**Primary codebase:** `AI-excel-addin`.
**Planning / product repo:** `risk_module`.

---

## 1. Problem Statement

Today the evidence layer is split across three surfaces:

1. `Thesis.sources[]` carries `SourceRecord` rows with a broad `text` field and optional coarse character range.
2. The `annotations` table stores selected text and UI ranges as a side table.
3. `source_refs` validators prove only that a referenced `src_N` exists.

That means a saved Thesis can say "claim X cites `src_1`" without preserving the exact excerpt that supports claim X in the Thesis artifact itself. A reviewer can often infer the source, but the system cannot reliably reconstruct the support chain from the durable snapshot alone.

There is a second audit gap: `DecisionsLogEntry.patch_ops_applied=[]` already validates, but skill runs that end in `INSUFFICIENT_DATA` can still disappear unless the skill explicitly appends a decision-log entry. The schema permits a no-op entry; the orchestration contract does not yet guarantee one.

F125 closes both gaps by making evidence a typed, durable, replayable graph:

```text
claim handle -> source_refs[] -> SourceRecord.excerpts[] -> Excerpt.claim_ids[]
```

The audit chain must live in `Thesis`, not in chat messages and not in a UI-only annotation side table.

---

## 2. Contract Decisions

### 2.1 Canonical Evidence Contract

`Thesis.sources[].excerpts[]` becomes the canonical Layer 1 evidence atom.

`SourceRecord.text` remains as source-level context. It is not the claim-support primitive once F125 lands. New producer writes must attach one or more `Excerpt` atoms for cited claim support.

### 2.2 Compatibility Without a Second Active Contract

F125 must accept pre-F125 `SourceRecord` rows where `excerpts` is missing, `null`, or empty. Those records are historical data, not malformed data.

This is compatibility input only. New F125-era writes have one active contract: positive claims require cited sources with linked excerpts. There is no legacy write path, feature flag, or deprecation-mode branch.

### 2.3 Annotations Are Render Cache

The annotations table remains available for UI highlights, collapse state, comments, and visual ranges, but it is not authoritative audit storage. Deleting annotation rows must not break replay.

F125 does not need to delete old annotations. It adds the contract that new authoritative evidence lives under `SourceRecord.excerpts[]`; annotation rows may reference an excerpt as render metadata.

### 2.4 Chat Is Not Audit Material

`research_messages` remains scratchpad / workflow context. Audit material is:

1. Layer 1 sources + excerpts.
2. Layer 2 typed claims with `source_refs`.
3. `decisions_log` entries, including zero-patch verdicts.

---

## 3. Cross-Repo Touchpoints

### 3.1 AI-excel-addin

- `schema/thesis_shared_slice.py` — add `ExcerptLocator`, `Excerpt`, and `SourceRecord.excerpts`.
- `schema/source_registry.py` — compute excerpt hashes, merge excerpts on existing source identity matches, dedupe within a source.
- `schema/thesis.py` — extend `DecisionsLogEntry` with optional `verdict` and `run_id`.
- `schema/thesis_markdown.py` — preserve excerpts and new decision-log fields through markdown render / parse.
- `schema/snapshots/*.schema.json` — regenerate schema snapshots.
- `schema/handoff_patch.py` — `RegisterSourcesOp.value` automatically accepts the extended `SourceRecord`; no new op shape is required unless implementation finds a validation gap.
- `api/research/patch_engine.py` — enforce claim -> source -> excerpt linkage for new patch writes; enforce same-target claim/data-gap rejection.
- `api/research/handoff.py` — preserve excerpts in shared-slice handoff snapshots and reuse source-ref audit helpers.
- `api/research/repository.py` — apply audit validation to direct Thesis mutation paths and persist decision-log no-op entries safely.
- `api/research/thesis_log_helpers.py` — keep locked/idempotent decisions-log appends as the standard path.
- `api/research/routes.py` — keep annotation routes but add excerpt-aware validation and response fields.
- `api/memory/workspace/notes/skills/*.md` — update producer / advisor-with-decision-log skill contracts.
- `tests/schema/`, `tests/research/`, `tests/api/research/`, `tests/skill_evals/` — coverage described in §9.

### 3.2 risk_module

- `docs/TODO.md` — mark F125 as plan-drafted.
- `docs/planning/RESEARCH_ARTIFACT_LAYERS.md` — update status after implementation.
- Frontend annotation UI is not a required F125 blocker unless the implementation changes annotation response shape consumed by the Hank UI.

---

## 4. Schema Design

### 4.1 `ExcerptLocator`

Recommended shape:

```python
class ExcerptLocator(_ContractModel):
    kind: Literal["text_range", "section", "page", "external_anchor", "unknown"]
    section_header: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    page: int | None = None
    anchor: str | None = None
```

Validation:

- `char_end >= char_start` when both are present.
- `kind="text_range"` requires both `char_start` and `char_end`.
- `kind="page"` requires `page >= 1`.
- `kind="section"` requires `section_header`.
- `kind="unknown"` is allowed for tool outputs that preserve exact text but lack a reliable source coordinate.

### 4.2 `Excerpt`

Recommended shape:

```python
class Excerpt(_ContractModel):
    excerpt_id: str
    text: str = Field(min_length=1)
    locator: ExcerptLocator
    hash: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    created_by: str = "agent"
    created_at: str
```

Validation:

- `claim_ids` are normalized, unique, and sorted for deterministic storage.
- `hash` is optional on input and computed during registration if omitted.
- `text` must be non-empty after stripping.

### 4.3 `SourceRecord`

Add:

```python
excerpts: list[Excerpt] = Field(default_factory=list)
```

Backwards compatibility:

- Missing `excerpts`, `null`, and `[]` all normalize to `[]`.
- Existing stored rows do not need an immediate migration before reads continue working.

### 4.4 `DecisionsLogEntry`

Add optional fields:

```python
verdict: str | None = None
run_id: str | None = None
```

`patch_ops_applied` stays `default_factory=list`. Zero-patch entries are already structurally legal; F125 makes the contract explicit and test-covered.

Do not require `verdict` for historical rows. Require it for new orchestrator-generated zero-patch entries and for updated skill examples.

---

## 5. Source Registration And Dedup

`schema/source_registry.py::register_source` is the right insertion point because it already owns stable source identity and source-ID minting.

Current behavior:

- Compute source identity hash.
- If an existing source matches, return the existing `src_N`.
- If no match, mint the next `src_N`.

F125 behavior:

1. Compute the same source identity hash.
2. Normalize and hash candidate excerpts.
3. If the source is new, mint `src_N` and persist all normalized excerpts.
4. If the source already exists, merge candidate excerpts into the existing source:
   - Dedupe by `Excerpt.hash`.
   - If an excerpt hash exists, merge `claim_ids`.
   - If the same hash has conflicting text or locator after normalization, fail loudly.
   - Preserve source identity immutability.
5. Return the canonical `src_N`.

Excerpt hash payload:

```json
{
  "source_identity_hash": "...",
  "text": "normalized exact excerpt text",
  "locator": {"kind": "...", "...": "..."}
}
```

This makes identical excerpts stable across retries and prevents two agents from creating duplicate atoms for the same support text.

---

## 6. Audit Validator

Add a central validator module rather than scattering checks across write paths. Suggested module:

```text
AI-excel-addin/api/research/evidence_audit.py
```

### 6.1 Claim Handle

Every positive claim checked by F125 gets a deterministic claim handle.

Resolution order:

1. Use explicit stable IDs when present: `claim_id`, `assumption_id`, `risk_id`, `catalyst_id`, `factor_id`, `watch_item_id`, `driver_id`, etc.
2. For singleton claim fields, use a path handle: `thesis.statement`, `business_overview`, `ownership`, `valuation`, `price_target`, etc.
3. For list objects without stable IDs, F125 should either use an existing deterministic field already treated as stable by the patch engine or add a stable ID in the same PR before enforcing excerpts on that object type.

The validator should expose diagnostics listing unsupported positive-claim paths so the test suite can catch unhandled fields.

### 6.2 Validation Rule

For each mutated positive claim:

1. `source_refs` must be non-empty unless the mutation is explicitly a `data_gap`, deletion, or neutral metadata update.
2. Every `source_ref` must resolve to `Thesis.sources[]`.
3. Each referenced `SourceRecord` must contain at least one `Excerpt` whose `claim_ids` includes the claim handle.

Source-existence alone is no longer sufficient for F125-era writes.

### 6.3 Historical Compatibility

Do not reject a full Thesis only because old claims cite pre-F125 sources with no excerpts.

Enforcement applies to:

- Claims created by the current patch batch.
- Claims materially updated by the current patch batch.
- Direct section writes performed after F125 lands.

Read/hydrate paths may surface diagnostics for historical rows but must not make old rows unreadable.

### 6.4 Same-Target Claim/Data-Gap Rejection

Implement R6 in the same validator:

- A patch batch cannot add or update a positive claim and add a same-target `data_gap` for that claim in the same batch.
- Same-target keys should use the same claim-handle/path normalization as excerpt validation.
- Historical audit can report existing same-target pairs, but F125 write-time enforcement should block new pairs.

---

## 7. Write Path Integration

### 7.1 Patch Engine

Patch batches should run the audit validator after `register_sources` has been applied and bundle source refs have been rewritten, but before commit.

The current order in `_dry_fold_detailed` already gives F125 the right hook:

1. Apply single `register_sources` op first.
2. Rewrite bundle source refs to canonical `src_N`.
3. Apply typed ops to the virtual Thesis.
4. Validate source refs.
5. Add F125 audit validation for mutated positive claims.

Validation errors should be surfaced as `InvalidTargetError` where possible so API callers get the existing typed-conflict response shape.

### 7.2 Direct Thesis Mutation Paths

F125 must not only protect `HandoffPatchOp` paths. The audit validator must cover direct mutation paths called by MCP tools and routes, including:

- `update_handoff_section`
- `batch_update_handoff_sections`
- `thesis_update_section`
- `update_thesis_from_diligence_sections`
- `save_qualitative_factor`
- `remove_qualitative_factor` only for deletion semantics, not evidence requirements
- any direct `update_thesis_artifact` caller that writes positive claim fields

For direct section writes that currently accept inline source objects, infer excerpts from the inline source object's `text` field and attach the current claim handle during registration.

For direct section writes that cite scalar `src_N` values, require that the existing source already has a matching excerpt for the mutated claim handle.

### 7.3 Finalize / Handoff Snapshot

`finalize_handoff` must preserve `SourceRecord.excerpts[]` through the shared-slice snapshot. It should not require all historical sources to have excerpts, but a post-F125 finalized handoff produced from new writes should pass the full audit invariant.

### 7.4 Layer 1 Locking

Layer 1 writes must use the same concurrency discipline as source registration and decisions-log append:

- Source/excerpt writes flow through `register_sources` within the Thesis patch/update transaction.
- Decisions-log appends use `thesis_log_helpers.append_decisions_log_entry`.
- Annotation render-cache writes must validate against an existing Thesis/source/excerpt when they are attached to audit evidence.

No new write-once-no-validation Layer 1 path should be introduced.

---

## 8. Decisions Log And Skill Contract

### 8.1 Zero-Patch Entries

New zero-patch entry shape:

```yaml
date: "2026-05-23"
skill: "critical-factors"
verdict: "INSUFFICIENT_DATA"
decision: "INSUFFICIENT_DATA: could not enumerate five sourced candidates"
rationale: "10-K MD&A and model output were unavailable after two attempts."
patch_ops_applied: []
run_id: "<optional orchestrator run id>"
```

`decision` remains human-readable. `verdict` makes it machine-queryable.

### 8.2 Orchestrator Post-Skill Hook

The orchestrator should append a decision-log entry whenever a scheduled/autonomous skill completes and emits no patch ops, as long as the skill is classified as `producer` or `advisor-with-decision-log`.

The hook should be idempotent:

- Deterministic `entry_id` or `run_id` if the orchestration layer has one.
- Reuse locked append helper.
- On retry, return existing entry instead of duplicating.

### 8.3 Skill Updates

Update producer and advisor-with-decision-log skill prose so `INSUFFICIENT_DATA`, `AMBIGUOUS`, `SPREAD_TOO_NARROW`, and other zero-write verdicts explicitly produce a decision-log entry.

Priority skills:

1. `critical-factors.md`
2. `earnings-scenarios.md`
3. `ownership-refresh.md`
4. `monitoring-init.md`
5. `thesis-articulation.md`
6. `dcf-relative-valuation.md`
7. Any scheduled skill eligible for F129 reuse.

---

## 9. Test Plan

### 9.1 Schema Tests

- `SourceRecord` accepts missing/null/empty `excerpts`.
- `ExcerptLocator` validates ranges and locator-specific requirements.
- `Excerpt` normalizes `claim_ids` deterministically.
- `DecisionsLogEntry` accepts zero `patch_ops_applied` and optional `verdict`.
- JSON schema snapshots include `excerpts`, `verdict`, and `run_id`.

### 9.2 Source Registry Tests

- New source persists excerpts and computes missing hashes.
- Existing source identity match merges new excerpts.
- Existing excerpt hash merges `claim_ids`.
- Conflicting same-hash text/locator fails loudly.
- Registration retry is idempotent.

### 9.3 Patch Engine Tests

- Claim add with `source_refs=["src_1"]` but no linked excerpt is rejected.
- Claim add with linked excerpt succeeds.
- `register_sources` predicted ID is rewritten before excerpt validation.
- Same-target claim + data_gap in one batch is rejected.
- Historical pre-F125 source with no excerpts remains readable.
- Updating a material claim requires fresh excerpt support or explicit carry-forward rationale.

### 9.4 Direct Write Tests

- Inline source dict in `update_thesis_from_diligence_sections` creates a `SourceRecord.excerpts[]` atom linked to the mutated claim handle.
- Scalar `src_N` direct write succeeds only when the source already has a matching excerpt.
- Existing tests that currently assert no decisions-log append on direct UI edits stay valid unless the write is skill/orchestrator driven.

### 9.5 Decisions Log Tests

- Zero-patch `INSUFFICIENT_DATA` entry persists.
- Duplicate retry returns existing entry by `entry_id`/`run_id`.
- Markdown render/parse preserves `verdict`, `run_id`, and empty `patch_ops_applied`.

### 9.6 Annotation Tests

- Annotation create/list continues working for old rows.
- New excerpt-backed annotation validates `source_id` + `excerpt_id`.
- Annotation deletion does not remove `SourceRecord.excerpts[]`.

### 9.7 Integration / Live Tests

- Run one producer skill that writes a claim and registers excerpt-backed sources.
- Run one skill that returns `INSUFFICIENT_DATA` and verify a zero-patch decision-log entry.
- Finalize handoff and assert excerpts survive in the frozen artifact.
- Build model remains unaffected by excerpt-bearing sources.

---

## 10. Implementation Phases

### Phase A — Schema And Registry

1. Add `ExcerptLocator` / `Excerpt`.
2. Add `SourceRecord.excerpts`.
3. Add decision-log `verdict` / `run_id`.
4. Update schema exports, markdown parser/renderer, and schema snapshots.
5. Update `source_registry.register_source` to merge excerpts.

### Phase B — Audit Validator

1. Add central claim-handle collection and audit validator.
2. Support source-ref resolution plus excerpt-link validation.
3. Support R6 same-target claim/data-gap detection.
4. Add diagnostics mode for historical rows.

### Phase C — Patch Engine Integration

1. Wire audit validation into `_dry_fold_detailed` after register-source rewrite.
2. Return typed conflicts for missing excerpt support.
3. Extend patch tests.

### Phase D — Direct Write Integration

1. Route section-update and qualitative-factor writes through the validator.
2. Convert inline source dicts to excerpt-bearing `SourceRecord` candidates.
3. Reject new scalar citations that lack linked excerpts.

### Phase E — Decisions Log / Skill Contract

1. Add zero-patch decision-log tests.
2. Add orchestrator post-skill append path if a run has no patch ops.
3. Update priority skill docs and skill-eval fixtures.

### Phase F — Annotations Render Cache

1. Add `excerpt_id` to annotation persistence if the table does not already have a generic metadata slot.
2. Validate excerpt-backed annotations against Thesis source/excerpt state.
3. Keep old annotation rows readable.

### Phase G — Audit Script / Backfill Prep

1. Add `scripts/audit_excerpt_coverage.py` or equivalent diagnostic.
2. Report:
   - sources with no excerpts,
   - claims with scalar source refs and no linked excerpt,
   - annotations that could seed a future backfill,
   - same-target claim/data-gap pairs.
3. Do not force backfill as part of core F125. Backfill is a follow-up once diagnostics show the production shape.

---

## 11. Rollout

No feature flags.

Suggested PR split:

1. **PR 1:** Schema + source registry + tests.
2. **PR 2:** Audit validator + patch engine integration + tests.
3. **PR 3:** Direct write paths + decisions-log zero-patch contract + skill updates.
4. **PR 4:** Annotation render-cache alignment + audit diagnostics.
5. **PR 5:** Live skill smoke + finalize/build regression.

Deployment requirement:

- Run tests before deploy.
- Run audit diagnostic in read-only mode before enabling scheduled/autonomous agents that depend on F125.
- Do not block deploy on historical excerpt gaps; block only on F125-era write-path failures.

Rollback:

- Code revert is sufficient for schema additions because fields are additive.
- Rows written with `excerpts` remain readable by newer code; older code may ignore unknown fields depending on model config. Confirm before deploy if rollback to older strict models is a realistic operational path.

---

## 12. Acceptance Criteria

F125 is complete when:

1. New producer writes can register sources with typed excerpts and cite them from claims.
2. Patch-engine writes reject positive claims whose source refs do not resolve to linked excerpts.
3. Direct Thesis mutation paths used by MCP/actions enforce the same audit rule for new writes.
4. `INSUFFICIENT_DATA` / no-op skill runs persist a zero-patch decision-log entry with `verdict` and `rationale`.
5. Annotations are documented and tested as render-cache rows, not authoritative audit state.
6. Pre-F125 rows with empty excerpts remain readable and finalizable.
7. A handoff snapshot preserves excerpt atoms verbatim.
8. Focused schema, source-registry, patch-engine, route/repository, markdown, and skill-eval tests pass.

---

## 13. Non-Goals

- No full production backfill in the core F125 implementation.
- No frontend redesign of annotation UX unless required by response-shape changes.
- No separate event-log table.
- No second active source/annotation write contract.
- No F129 monitoring-agent implementation; F125 only unblocks it.
