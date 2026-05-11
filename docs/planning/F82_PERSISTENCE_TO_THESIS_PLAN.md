# F82 — Canonical-Comps Persistence-to-Thesis

**Status**: DRAFT R3 — implementation plan for F82 (canonical-comps persistence-to-Thesis) per `docs/TODO.md` row F82.
**Created**: 2026-05-08. **Revised**: 2026-05-08 (R1: 5+2 → R2: 2P1+1HR → R3: 3P1+1cleanup; see §11 changelog).
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` R6 §7.6 (Source registry integration cross-cutting concern).
**Prerequisites**:
- V2.P11 SHIPPED 2026-05-07 — Tracks 0/A/B/C all live; producer (`risk_module/mcp_tools/industry.py::industry_peer_comparison`) emits `peer_comparison.sections` + `operating_comparison.metric_groups` + bundle-scoped `sources[]` as a function return value.
- F83 SHIPPED 2026-05-08 — three consumption skills assume `Thesis.sources[]` already contains every cited `src_N` ID; F83 Iron Law explicitly forbids emitting narrative without registered sources.
- F87 SHIPPED 2026-05-08 — renderer reads `Thesis.industry_analysis.*` and resolves cell `source_refs` against `Thesis.sources[]`.

**Authoritative code references** (verified by file read 2026-05-08):
- `AI-excel-addin/schema/source_registry.py:14-78` — **CANONICAL** registry: `register_source(sources, candidate) -> tuple[SourceId, list[SourceRecord]]`; `compute_identity_hash(type, source_id, endpoint_or_filing_id, key_fields)`; `next_source_id(existing)` mints `src_N`. Identity matches framework R6 §7.6 (logical-identity fields only; `retrieved_at` excluded). Producer already uses `SourceRecord.model_validate` per `risk_module/mcp_tools/industry.py:258-260`. **F82 builds on this — does NOT extract from legacy handoff helper.**
- `AI-excel-addin/api/research/handoff.py:119,151` — legacy `_normalize_source_record` STRIPS `provider`, `endpoint_or_filing_id`, `key_fields`, `retrieved_at`, `identity_hash`; dedups on `{type, source_id, section_header, char_start, char_end}`. **Wrong identity for canonical comps** (would collapse distinct EDGAR/transcript KPI sources). Migration helper stays as-is for legacy v1.0 → v1.1 path; F82 does NOT generalize it.
- `AI-excel-addin/api/research/handoff.py:308` — `_validate_source_refs_resolve(shared_slice)` — expects root with `sources[]`. F82 refactors to accept `known_source_ids: set[str]` + arbitrary subtree (B3 fix).
- `AI-excel-addin/schema/handoff_patch.py:458-527` — Track 0 industry_analysis patch op surface:
  - `UpdateIndustryLandscapeOp` (458) — `value: IndustryLandscape` (narrative + citations)
  - `ReplaceIndustryPeerComparisonOp` (470) — `value: IndustryPeerComparison` (whole object incl. peers, sections)
  - `AddEditorialPeerOp` (476), `RemoveEditorialPeerOp` (482), `SetEditorialPeerSetOp` (488)
  - `SetPeerComparisonSectionsOp` (521), `SetOperatingComparisonOp` (527)
  - `UpdateMacroOverlayOp` + `ReplaceStructuralTrendsOp` (Track A pre-existing — both carry `source_refs` per `thesis_shared_slice.py:488` `MacroOverlayDriver` and `StructuralTrend`)
  - F83 added `UpdateCompsNarrativeOp`
  - **NO `RegisterSourcesOp` exists** — confirmed gap
- `AI-excel-addin/api/research/patch_engine.py` — current engine folds ops in-memory + validates + does single version-checked `update_thesis_artifact_if_version_matches` at end (per Codex R0 confirmation). **Batches are effectively atomic**; F82 validation must run during the in-memory fold BEFORE persistence (do NOT pre-pass `repo.update_thesis_artifact`).
- `risk_module/mcp_server.py:2411` + `risk_module/actions/research.py:1024` — `apply_patch_ops(research_file_id, ops=[...])` MCP tool exists; forwards `{"ops": normalized_ops}`. Multi-op batches accepted; engine applies in input order today (F82 adds register-first ordering).
- `AI-excel-addin/api/memory/workspace/notes/skills/comps-narrative.md:36,80` — F83(b) Iron Law: every citation must be a registered `src_N` ID
- `AI-excel-addin/data/users/henry/workspace/theses/PCTY__f83_live_dogfood.md` — F83 dogfood evidence: fixture hand-built `Sources: [src_1]...[src_93]` BEFORE invoking F83(b)/F83(c) skills; exactly the manual step F82 automates
- `risk_module/mcp_tools/industry.py:255-260` — producer return uses `SourceRecord.model_validate` for sources; flat dict shape: `{peers, sections, industry_key, template_manifest_id, as_of, sources, operating_comparison?}` (per Codex R0 B4 — there is NO `producer.peer_comparison` namespace; agent constructs the patch-op value from these flat fields)

---

## 1. Purpose

Close the producer-to-Thesis pipeline so canonical-comps content reaches Thesis state automatically when an agent calls the producer. Closes the last production-rollout gate filed in `docs/TODO.md` row F82.

**The gap today**:
1. Producer (V2.P11) returns artifacts + bundle-scoped sources as a function return value
2. Track 0 shipped patch ops to write artifact BODIES (`set_peer_comparison_sections`, `set_operating_comparison`, etc.) but no patch op registers SOURCES into `Thesis.sources[]`
3. The body ops accept cell `source_refs` referencing IDs but DON'T validate or remap those IDs
4. Result: agent that calls the producer + emits body ops gets dangling cell `source_refs` (bundle IDs that don't resolve against any registered Thesis source)
5. F83(b)/F83(c) skills explicitly require sources to be pre-registered (Iron Law); F83 dogfood worked around this by hand-building fixture state

**What F82 ships**:
- New `RegisterSourcesOp` patch op (Track-0-style additive bump in `AI-excel-addin/schema/handoff_patch.py`) — accepts a list of `SourceRecord`s + returns an in-batch ID-mapping
- Patch engine pre-pass: process `RegisterSourcesOp`s FIRST in any batch, build bundle→stable ID mapping, REWRITE `source_refs` in subsequent ops in the same batch before applying
- Wrap the canonical `schema/source_registry.py:register_source` (already correct identity per framework R6 §7.6); legacy `_merge_legacy_sources_into_thesis` stays UNTOUCHED (different identity, different problem — see F82.D4)
- Producer-side: ensure the return shape is patch-op-compatible (already is per `industry_peer_comparison` audit)

**What's NOT in this plan**:
- Producer code changes (V2.P11 already returns artifacts in the right shape)
- F87 renderer changes (renderer already resolves `source_refs` against `Thesis.sources[]`; once F82 populates Thesis correctly, renderer just works)
- F83 skill changes (skills already require pre-registered sources; F82 makes that requirement satisfiable)
- F84 process-template migration (separate plan)

---

## 2. Audit findings (grounded by file read 2026-05-08)

### 2.1 Existing source-merge infrastructure (handoff.py:678-740)

`_merge_legacy_sources_into_thesis(thesis_row, *, legacy_shared_slice)` is load-bearing for the v1.0 → v1.1 migration path but uses the WRONG identity for canonical comps:

**Legacy dedup identity** (per `_normalize_source_record` at handoff.py:119 + dedup at `:151`):
- Strips `provider`, `endpoint_or_filing_id`, `key_fields`, `retrieved_at`, `identity_hash`
- Dedups on `{type, source_id, section_header, char_start, char_end}` — designed for legacy v1.0 sources without identity_hash
- Would COLLAPSE distinct EDGAR/transcript KPI sources for canonical comps — F82 must NOT use this path

**Canonical dedup identity** (per `schema/source_registry.py:14-78`):
- `compute_identity_hash(type, source_id, endpoint_or_filing_id, key_fields)` — matches framework R6 §7.6 logical-identity definition
- `retrieved_at` excluded (provenance only)
- Producer already mints + validates `SourceRecord` instances per `mcp_tools/industry.py:258`

F82 wraps the CANONICAL registry, NOT the legacy helper. See F82.D4.

**ID minting** (lines 685-710):
- Reads `Thesis.sources[*].id` to find max `src_N` number
- Mints new ones as `f"src_{next_source_number}"` for any source without an existing identity match

**Ref rewriting** (line 718, `_rewrite_source_refs_in_place`):
- Mutates `migrated_shared_slice` to remap cell `source_refs` from legacy IDs to assigned/existing Thesis IDs
- This is exactly the bundle→stable remap F82 needs

**Validation** (line 720, `_validate_source_refs_resolve`):
- After rewrite, asserts every `source_refs` ID exists in the merged `sources[]`
- Fail-loud if any cell ref dangles

**Persist** (lines 722-727):
- Calls `update_thesis_artifact(thesis_id, {"sources": unified_sources})`
- Audited via `append_decisions_log_entry`

**However**: this helper is the WRONG identity for canonical comps (per Codex R0 B1). Its `_normalize_source_record` at handoff.py:119 strips `provider`, `endpoint_or_filing_id`, `key_fields`, `retrieved_at`, `identity_hash`; dedup at handoff.py:151 keys on `{type, source_id, section_header, char_start, char_end}` — designed for legacy v1.0 schema-migration. F82 does NOT generalize this helper. Migration path stays untouched. F82 wraps the canonical `schema/source_registry.py` (which already has correct identity per framework R6 §7.6) — see F82.D4.

### 2.2 Track 0 patch op surface — what's there + what's missing

**Already shipped** (per `handoff_patch.py`):
| Op | Target | Body |
|---|---|---|
| `update_industry_landscape` (458) | `industry_analysis.landscape` | `IndustryLandscape` (narrative + citations) |
| `replace_industry_peer_comparison` (470) | `industry_analysis.peer_comparison` (whole object) | `IndustryPeerComparison` |
| `add_editorial_peer` (476) | `industry_analysis.editorial_peer_set` (append) | `EditorialPeer` |
| `remove_editorial_peer` (482) | `industry_analysis.editorial_peer_set` (filter) | by ticker |
| `set_editorial_peer_set` (488) | `industry_analysis.editorial_peer_set` (replace) | `list[EditorialPeer]` |
| `set_peer_comparison_sections` (521) | `industry_analysis.peer_comparison.sections` | `list[SnapshotSection]` |
| `set_operating_comparison` (527) | `industry_analysis.operating_comparison` | `OperatingComparison` |
| `update_comps_narrative` (F83) | `industry_analysis.comps_narrative` | `CompsNarrative` |

**Missing — F82 adds**:
| Op | Target | Body |
|---|---|---|
| `register_sources` | `Thesis.sources[]` (append + dedup) | `list[SourceRecord]` |

### 2.3 F83 skill expectations on Thesis state

F83(b) `comps-narrative.md` lines 36, 64, 80:
- "Every narrative claim must trace to one or more registered `src_N` IDs in `Thesis.sources[]`"
- "Required: `Thesis.sources[]`"
- "must contain every `src_N` ID used in candidate evidence"

F83 skills do NOT register sources themselves — they consume already-registered sources. Without F82, the only way for sources to land in Thesis is the legacy migration path (one-time, gated to schema_version == "1.0") OR manual handoff from upstream skills like `competitive-position` / `comparative-analysis` that emit their own sources via patch ops.

### 2.4 F83 dogfood evidence

`PCTY__f83_live_dogfood.md` was hand-built with `Sources: [src_1]...[src_93]` populated INTO the Thesis fixture before F83(b)/F83(c) ran. The hand-build copied bundle IDs from a producer call directly — keeping bundle IDs stable for the fixture's lifetime by ensuring the Thesis was empty (no collision per F83 R3 P2 fix).

This is exactly the manual step F82 automates: producer call → Thesis state with stable IDs and resolved cell refs.

### 2.5 Producer return shape

`industry_peer_comparison(symbol, *, peers, limit, editorial_peer_set, existing_sources)` returns a **FLAT** dict (per `mcp_tools/industry.py:255-275`; B4 fix from R0):
- `peers: list[IndustryPeerComparisonPeer]` (top-level)
- `sections: list[SnapshotSection]` (top-level — Track A v1.2 sectioned shape)
- `industry_key: str` (top-level)
- `template_manifest_id: str` (top-level)
- `as_of: str` (top-level)
- `sources: list[SourceRecord]` (bundle-scoped IDs)
- `operating_comparison: { industry_key, template_manifest_id, years, metric_groups }` (optional — only when Track B applies)
- **NOT returned**: `editorial_peer_set` is NOT in producer output (per `mcp_tools/industry.py:275`). Editorial peer set is curatorial INPUT to the producer (passed via `editorial_peer_set` parameter, written to Thesis by `competitive-position` / F83(a) `peer-curation` skills) — NOT an output. F82 agent flow does NOT include `set_editorial_peer_set` against producer output.
- `industry_analysis: { ... }` is NOT a producer return key. Agent constructs `IndustryPeerComparison.value` for `replace_industry_peer_comparison` op from the top-level `peers` + `sections` + `industry_key` + `template_manifest_id` + `as_of` (per F82.D6).
- `peers`, `industry_key`, `as_of`, `template_manifest_id`, etc.

The `existing_sources` parameter (per `mcp_tools/industry.py:35-50`) lets the producer mint non-colliding IDs when an existing Thesis is passed — but the MCP wrapper at `mcp_server.py:2411` does NOT expose this parameter (per F87 §5 path-b limitation). For F82, the patch-op approach makes this irrelevant: the patch engine handles dedup + remap, so bundle IDs colliding with Thesis IDs are resolved at apply time.

---

## 3. Locked design decisions

### F82.D1. New `RegisterSourcesOp` patch op (Track-0-style additive bump) — at most ONE per batch
Single new patch op class in `AI-excel-addin/schema/handoff_patch.py`:
```python
class RegisterSourcesOp(_PatchOpBase):
    op: Literal["register_sources"] = "register_sources"
    target: None = None
    value: list[SourceRecord]
```
- `value` is a list of `SourceRecord` objects with bundle IDs (typed `SourceRecord`, NOT raw dicts; producer already returns `SourceRecord.model_validate`-validated entries per `mcp_tools/industry.py:258-260`).
- **Single-register-per-batch constraint** (B2 fix): the patch engine REJECTS batches containing multiple `register_sources` ops. Two register ops in one batch is ambiguous because both bundles can mint `src_1`; body ops only carry plain source IDs (no namespace) so there's no way to disambiguate which `src_1` a cell means. Multi-bundle batches are out of scope for v1; if a future flow needs multi-bundle, that requires adding bundle namespace to body ref shape (NOT done here).
- Patch engine's apply path uses the canonical `schema.source_registry.register_source(sources, candidate)` for each candidate:
  1. Read existing `Thesis.sources[]` (validated as `list[SourceRecord]`)
  2. For each candidate in `value`: call `register_source(sources, candidate)` — returns `(stable_id, updated_sources)`. Record bundle-ID → stable-ID in a per-batch mapping table.
  3. Final `updated_sources` becomes the new `Thesis.sources[]` value (in the in-memory fold; no `repo.update_thesis_artifact` pre-pass — atomic with the rest of the batch per §6.1).
  4. Bundle→stable mapping returned to the patch-engine context for the rewrite pass (F82.D2).

### F82.D2. Patch engine in-batch ID-rewriting pass — recursive over all op values; full migration key-set
The patch engine processes the (single) `register_sources` op FIRST in any batch (stable partition: register-ops first, others in input order), then before applying each subsequent op, **recursively walks the op's `value` tree** and rewrites source-ID references using the per-batch bundle→stable mapping.

**Rewrite key-set** (matches existing migration semantics at `handoff.py:59-60`):
- List-valued: `source_refs` (cell-level), `citations` (narrative-level), `evidence` (claim-level)
- Scalar-valued: `source_ref` (single-source carrier)

R1 explicitly preserves the full key-set so future schema additions on any of these keys are auto-picked-up + behavioral parity with migration semantics is preserved (Codex R1 high-risk fix). The walker handles both list and scalar carriers.

**Recursive walk is normative** (B5 fix). Don't enumerate paths — visit every leaf of the op's value tree and rewrite when the leaf is in the source-ref key-set (per F82.D2 above: list-valued `source_refs` / `citations` / `evidence`, scalar-valued `source_ref`). Known carriers in the existing op surface include but are not limited to:
- `update_industry_landscape.value.citations` (`IndustryLandscape`)
- `update_comps_narrative.value.citations` (`CompsNarrative`)
- `update_macro_overlay.value.drivers[*].source_refs` (`MacroOverlayDriver` per `thesis_shared_slice.py:488`)
- `replace_structural_trends.value[*].source_refs` (`StructuralTrend`)
- `replace_industry_peer_comparison.value.peers[*].source_refs` (`IndustryPeerComparisonPeer`)
- `replace_industry_peer_comparison.value.sections[*].metrics[*].values[*].source_refs` AND `.median.source_refs` (`SnapshotMetric` shapes)
- `set_peer_comparison_sections.value[*].metrics[*].values[*].source_refs` AND `.median.source_refs`
- `set_operating_comparison.value.metric_groups[*].metrics[*].series[*][*].source_refs` AND `.median_series[*].source_refs`

Tests cover the carriers explicitly (per §5) but the implementation is recursive so future schema additions are automatically picked up.

**Helper sourcing**: F82 introduces a small `_rewrite_source_refs(value, mapping)` recursive walker (Python pure function on dicts/lists — operates on the JSON-shaped patch payload before Pydantic validation OR on the validated model dict; impl decides). Don't reuse the `_rewrite_source_refs_in_place` helper from `handoff.py` — that's tied to the legacy migration path's specific subtree walker. F82's walker is general-purpose recursive over any op value.

### F82.D3. Validation — refactor `_validate_source_refs_resolve` to accept `known_source_ids` + subtree
Per Codex R0 B3, running `_validate_source_refs_resolve(thesis.industry_analysis_dict)` directly fails because the helper expects a root with `sources[]` (it auto-extracts known IDs from `value.sources`). F82 refactors the helper signature:

```python
def _validate_source_refs_resolve(
    value: dict,
    *,
    known_source_ids: set[str],
) -> None:
    """Walk `value` recursively; raise if any leaf in the source-ref key-set
    (`source_refs`, `citations`, `evidence`, `source_ref` — matches
    `handoff.py:59-60` semantics) contains an ID not in known_source_ids."""
```

After batch fold, the patch engine calls:
```python
known_source_ids = {s.id for s in updated_sources}
_validate_source_refs_resolve(thesis.industry_analysis_dict, known_source_ids=known_source_ids)
```

Existing call sites at `handoff.py:255,648,720` updated to pass `known_source_ids = {s["id"] for s in shared_slice.get("sources") or []}` to preserve current semantics. **No behavioral change for migration path.**

Validation runs during the in-memory fold BEFORE persistence per §6.1 atomicity. Any unresolved cell ref → batch raises before `update_thesis_artifact_if_version_matches` — full rollback.

### F82.D4. Use canonical `schema/source_registry.py` — DO NOT extract from legacy handoff helper
**Codex R0 B1 fix**: the legacy `_merge_legacy_sources_into_thesis` helper at `handoff.py:678-740` uses the WRONG identity for canonical comps. It strips `provider`, `endpoint_or_filing_id`, `key_fields`, `retrieved_at`, `identity_hash` (per `_normalize_source_record` at line 119) and dedups on `{type, source_id, section_header, char_start, char_end}` (line 151) — designed for legacy 1.0 sources without identity_hash. Using it for canonical comps would COLLAPSE distinct EDGAR/transcript KPI sources and lose provenance.

**The canonical registry already exists** at `AI-excel-addin/schema/source_registry.py`:
- `register_source(sources, candidate) -> tuple[SourceId, list[SourceRecord]]` — dedup via `compute_identity_hash` on `{type, source_id, endpoint_or_filing_id, key_fields}` (matches framework R6 §7.6 logical-identity definition)
- `next_source_id(existing)` — mints `src_N`
- Hash-collision detection raises explicit error
- Producer already uses `SourceRecord.model_validate` per `mcp_tools/industry.py:258-260`

**F82 wraps the canonical registry, doesn't replace or extract the legacy helper.** Migration path stays untouched (it's solving a different problem — legacy sources without identity_hash). Big scope simplification: `api/research/source_merge.py` (R0) is NOT created — the core already exists.

### F82.D5. No producer-side changes
V2.P11 producer already returns artifacts in the right shape. The patch-op approach handles bundle/stable ID translation at the apply boundary. The MCP wrapper limitation (`existing_sources` not exposed) becomes irrelevant — agents emit `register_sources` op explicitly, and the patch engine handles dedup.

### F82.D6. Agent flow — single composite patch batch (corrected for actual producer return shape)
**Codex R0 B4 fix**: producer return is FLAT, not `producer.peer_comparison`. Per `risk_module/mcp_tools/industry.py:255-260`, `industry_peer_comparison()` returns dict with top-level keys `{peers, sections, industry_key, template_manifest_id, as_of, sources, operating_comparison?}` — agent must construct the patch values from these flat fields:

```yaml
# Hank emits via apply_patch_ops(research_file_id, ops=[...]) — MCP tool at risk_module/mcp_server.py:2411
ops:
  - op: register_sources
    value: <producer.sources>                           # list[SourceRecord]
  - op: replace_industry_peer_comparison
    value:                                              # IndustryPeerComparison
      peers: <producer.peers>
      sections: <producer.sections>                     # Track A v1.2 sectioned shape
      industry_key: <producer.industry_key>
      template_manifest_id: <producer.template_manifest_id>
      as_of: <producer.as_of>
  # OR alternately: split into set_peer_comparison_sections + (preserve flat peers via separate path)
  - op: set_operating_comparison
    value: <producer.operating_comparison>              # optional — only if Track B populated
```

NOTE: `set_editorial_peer_set` is NOT emitted from producer output — `editorial_peer_set` is INPUT to the producer, not output (per §2.5). The editorial peer set is written to Thesis by `competitive-position` (full strategic eval) or F83(a) `peer-curation` skill (user-confirmed peer-set writer). If the agent wants to ALSO update editorial_peer_set in the same batch, that's a separate decision driven by curation logic, not by F82's persist-producer-output pipeline.

All ops apply atomically per §6.1 — `register_sources` op processed first per F82.D2 stable partition, body ops applied with rewritten cell `source_refs`, post-fold validator runs against full Thesis state, then single version-checked persist.

The agent doesn't think about bundle/stable IDs — patch engine handles dedup + remap transparently.

The `apply_patch_ops` MCP tool at `risk_module/mcp_server.py:2411` already accepts multi-op batches via `ops=[...]` parameter (forwarded as `{"ops": normalized_ops}` per `actions/research.py:1024`); engine applies in input order today (F82 adds register-first stable partition).

### F82.D7. F83 skill emit pattern unchanged
F83 skills (`peer-curation`, `comps-narrative`, `post-comps-landscape-refresh`) continue to assume sources pre-registered (per their existing Iron Laws). The skills emit body ops with citations referencing already-stable Thesis source IDs — F82 makes this assumption holdable in production by ensuring producer-side calls register sources before skills run.

If a skill produces NEW sources of its own (e.g., a future skill that pulls additional research mid-flow), it can emit a `register_sources` op as part of its patch batch too. The op shape is general-purpose.

---

## 4. File-by-file changes

### AI-excel-addin (schema + patch-engine + validator refactor)

**Modified — schema (additive Track-0-style bump)**:
- `schema/handoff_patch.py` (around line 527 where `SetOperatingComparisonOp` lives):
  - Add `RegisterSourcesOp` class: `op: Literal["register_sources"]`, `target: None`, `value: list[SourceRecord]`
  - Add `RegisterSourcesOp` to imports + the `HandoffPatchOp` union
  - Update `__all__` export
- `schema/__init__.py` — re-export `RegisterSourcesOp` (matches existing patch-op re-export pattern)

**Modified — patch_engine.py**:
- Add `_apply_register_sources(payload, op, *, batch_state)` apply function — calls `schema.source_registry.register_source` per candidate; updates `payload.sources`; populates `batch_state.bundle_to_stable_mapping: dict[str, str]`
- Add patch-op-type branch in the dispatcher around line 544
- Add in-batch pre-pass logic at batch entry:
  1. Validate **at most one** `register_sources` op per batch (B2 fix); raise `ValueError` if multiple found
  2. Stable partition: register-op first, others in input order
  3. Apply register op (if present) → updates payload.sources + builds mapping
  4. For each subsequent op: BEFORE Pydantic validation, recursively walk op value tree and rewrite source-ID references using the mapping per F82.D2 — full key-set: list-valued `source_refs` / `citations` / `evidence`, scalar-valued `source_ref` (matches `handoff.py:59-60` migration semantics)
  5. After all ops folded, run `_validate_source_refs_resolve(payload.industry_analysis_dict, known_source_ids=...)` per F82.D3
  6. Single version-checked `update_thesis_artifact_if_version_matches` at end (existing pattern; no pre-pass `repo.update_thesis_artifact`)
- Add new helper `_rewrite_source_refs_recursive(value, mapping)` — generic recursive walker (NOT the legacy `_rewrite_source_refs_in_place` from handoff.py per F82.D2)
- Add `_describe_op` branch for `register_sources` (matches existing op-description pattern around line 996)

**Modified — handoff.py**:
- `_validate_source_refs_resolve` (line 308) — refactor signature to `(value, *, known_source_ids: set[str]) -> None` per F82.D3
- Update existing call sites at `:255, :648, :720` to pass explicit `known_source_ids` (extracted from the local `sources[]` they currently rely on as root)
- **No other changes** — `_merge_legacy_sources_into_thesis` migration path stays as-is (per F82.D4 — different identity, different problem)

**Modified — schema snapshot files**:
- `tests/schema/snapshots/handoff_v1_1.schema.json` — regenerate to include `RegisterSourcesOp` (additive)

**New tests** (`tests/research/test_patch_engine_register_sources.py`):
- Single `register_sources` op: empty Thesis + N candidates → all minted; existing Thesis + overlapping candidates → identity dedup; hash collision → explicit error
- Batch with register + body ops: verify recursive ref rewrite hits ALL carrier paths AND key-set:
  - List-valued `source_refs`: `update_macro_overlay.drivers[*].source_refs`, `replace_structural_trends[*].source_refs`, `replace_industry_peer_comparison.peers[*].source_refs` AND `.sections[*].metrics[*].values[*].source_refs` AND `.median.source_refs`, `set_peer_comparison_sections.*.values[*].source_refs` AND `.median.source_refs`, `set_operating_comparison.metric_groups[*].metrics[*].series[*][*].source_refs` AND `.median_series[*].source_refs`
  - List-valued `citations`: `update_industry_landscape.citations`, `update_comps_narrative.citations`
  - List-valued `evidence`: any op carrying claim-level `evidence: list[SourceId]` (matches migration semantics)
  - Scalar-valued `source_ref`: any op carrying single-source carrier (matches migration semantics)
  - Synthetic test op shapes covering `evidence` and scalar `source_ref` carriers if no current op surfaces them — ensures forward-compat as schemas grow
- Multi-register-per-batch raises (B2 enforcement)
- Stable partition: input order shuffled around register op → register processed first regardless
- Post-fold validation: body op cites `src_X` not in registered → batch raises BEFORE persist (atomicity per §6.1)
- Atomicity confirmation: pre-existing Thesis state intact after a failing batch
- `_validate_source_refs_resolve` signature regression: existing call sites at handoff.py work with new `known_source_ids` param

### risk_module (no changes)
- Producer return shape is already patch-op-compatible (uses `SourceRecord.model_validate` at `mcp_tools/industry.py:258`)
- Agent constructs patch-op values from flat producer return per F82.D6
- `existing_sources` MCP wrapper limitation becomes irrelevant (patch engine handles dedup)
- F82 is AI-excel-addin only

### Out of scope for this plan
- F87 renderer changes (already reads `Thesis.sources[]` correctly)
- F83 skill changes (already assumes pre-registered sources)
- F84 process-template migration (separate plan)
- Producer-side changes (return shape already correct)
- Auto-trigger of `register_sources` on producer call (agent emits patch batch explicitly; no implicit auto-persist)
- Multi-bundle batches with namespace disambiguation (single-register-per-batch lock per F82.D1; revisit only if a real flow emerges that requires this — explicit scope decision per CLAUDE.md "don't defer to dodge friction": this is "out of scope, not deferred")
- `register_sources` markdown round-trip support — patch ops are apply-time records, not Thesis sub-sections; confirmed not needed at impl start

---

## 5. Tests

| Coverage | Where |
|---|---|
| `schema.source_registry.register_source` is canonical (already tested) — F82 reuses, no new core tests | (existing `tests/schema/test_source_registry.py` covers identity hash + minting + collision; F82 reuses) |
| Patch engine `register_sources` apply path | `tests/research/test_patch_engine_register_sources.py` (new) |
| In-batch rewrite of cell `source_refs` | Same file — batch with register + `set_peer_comparison_sections` + `set_operating_comparison` + `update_comps_narrative`; assert post-apply Thesis state has stable IDs throughout |
| Post-batch validation fails atomic on unresolved ref | Same file — emit body op citing `src_X` where X isn't registered; assert batch rolls back |
| Migration-path regression | `tests/research/test_handoff_legacy_migration.py` (existing) — must still pass after `_validate_source_refs_resolve` signature refactor (no other migration-path changes per F82.D4) |
| Schema validation | `RegisterSourcesOp.value: list[SourceRecord]` constructs cleanly + rejects malformed |
| Snapshot regeneration | `tests/schema/snapshots/handoff_v1_1.schema.json` updated |

**Live verification path**:
After F82 ships, replay the F83 dogfood scenario without manual fixture-injection:
1. Run V2.P11 producer for PCTY (`industry_peer_comparison('PCTY', peers='PAYC,PAYX,ADP', limit=3)`)
2. Wrap the return value into a single patch batch: `register_sources` + `replace_industry_peer_comparison` + `set_operating_comparison` (only ops derivable from producer output per F82.D6; `set_editorial_peer_set` is NOT in this batch — editorial peer set is curatorial input, not producer output, and is updated separately via `competitive-position` / F83(a) `peer-curation` flows)
3. Apply against an empty PCTY Thesis
4. Verify `Thesis.sources[]` is populated with stable IDs, cell `source_refs` resolve, F87 renderer shows the content
5. Then invoke F83(b) `comps-narrative` skill against the now-populated Thesis — verify citations resolve, narrative emitted via `update_comps_narrative`

This is the live producer-to-Thesis-to-renderer-to-skill pipeline running end-to-end without fixture hacks.

---

## 6. Cross-cutting concerns

### 6.1 Atomicity (confirmed by Codex R0)
Patch batches are atomic via the existing in-memory fold pattern: engine folds all ops into a working Thesis dict, validates, then does a SINGLE `update_thesis_artifact_if_version_matches` at end (per `patch_engine.py:181`). F82's pre-pass + ref-rewrite + validation all run during the in-memory fold BEFORE persistence. **Do NOT call `repo.update_thesis_artifact` in a register-sources pre-pass** — would break atomicity. Any unresolved cell `source_refs` after fold → entire batch raises and rolls back; no partial Thesis state.

### 6.2 Idempotency
`register_sources` with the same source twice is a no-op for the second call (dedup via identity). Re-running the same producer call + patch batch produces the same Thesis state.

### 6.3 Ordering
The patch engine processes `register_sources` BEFORE other ops in the same batch regardless of input order. Rationale: cell `source_refs` rewriting requires the mapping table to exist before body ops apply. Implementation: stable partition + sort by op type at batch entry.

### 6.4 Migration path compatibility
The legacy v1.0 → v1.1 migration path stays UNTOUCHED — different identity, different problem (per F82.D4 + B1 changelog). Existing migration tests must continue to pass without modification (only the `_validate_source_refs_resolve` signature refactor at F82.D3 touches the migration call sites; behavior preserved).

### 6.5 Skill compatibility
F83 skills (and any future skills) emit body ops without thinking about source registration — as long as the producer's `register_sources` op runs in the same batch, refs get rewritten transparently. Skills that produce NEW sources (e.g., a future research-pulling skill) emit their own `register_sources` op.

### 6.6 No silent ID collisions
Bundle IDs colliding with existing Thesis IDs are resolved by the dedup logic (identity match wins; bundle ID gets remapped to stable ID). The agent never sees the conflict — it just gets the resolved Thesis state back.

---

## 7. Out of scope

- **F87 renderer** (already reads `Thesis.sources[]`; F82 just makes that state populated correctly)
- **F83 skill changes** (skills already assume pre-registered sources; F82 makes this satisfiable in production)
- **F84 process-template migration** (separate plan; gates auto-invocation from templates)
- **Producer code changes** — V2.P11 already returns artifacts in patch-op-compatible shape
- **Producer-side `existing_sources` MCP wrapper plumbing** (per F87 §5 path-b limitation; irrelevant after F82 because patch engine handles dedup)
- **Auto-trigger** — agents must explicitly emit the patch batch; no producer-call hook auto-persists. Agent flow stays explicit + auditable.
- **Source-version pinning** for reproducible scorecards (CANONICAL_COMPS_FRAMEWORK_PLAN.md §7.2 freshness risk; deferred to a separate freshness plan)
- **Cross-Thesis source sharing** (each Thesis has its own `sources[]`; no global registry)

---

## 8. Rollout sequence

1. **Phase 1 — schema + patch-engine + validator refactor** (one focused commit): add `RegisterSourcesOp` schema class + `__all__` exports + schema snapshot regen; refactor `_validate_source_refs_resolve` signature at handoff.py:308 to accept `known_source_ids: set[str]` (update existing call sites at :255,:648,:720); add `_apply_register_sources` in patch engine; add in-batch single-register validation + register-first stable partition + recursive ref-rewrite + post-fold validation + `_describe_op` branch. Migration tests stay green. New tests per §5 pass.
2. **Phase 2 — live verification** (no commit; verification only): run the producer-to-Thesis pipeline end-to-end against an empty test Thesis; verify F83(b)/F83(c) skills + F87 renderer all work without fixture-injection. Capture in QA report at `docs/qa/skill-qa-f82-live-pipeline-2026-05-08.md`.

Single phase / single commit + verification. (R0 had two phases via the now-dropped extraction; R1 collapses to one commit because the canonical registry already exists.)

---

## 9. Open questions

1. **Patch engine batch atomicity** — verify at impl start that the existing patch engine treats a batch as atomic (all-or-nothing). If batches today are op-by-op with no rollback on later failure, F82's post-batch validation needs to either run pre-apply (dry-run) or wrap the batch in a transaction. Likely the existing behavior is atomic, but confirm.
2. **`register_sources` markdown round-trip** — `RegisterSourcesOp` is an apply-time op, not a persisted Thesis sub-section. Confirm at impl start whether `thesis_markdown.py` needs a parse/serialize branch for it (likely NOT — patch ops are not Thesis state, they're apply-time records).
3. **F83(b) Iron Law adjustment** — F83 skills today assume sources are pre-registered. After F82 ships, an agent flow can register-then-body in a single batch. Should F83 skills' Iron Laws be relaxed to allow emitting `register_sources` themselves when needed? Lean: NO change for v1 (skills consume pre-registered sources cleanly); add later if a skill needs to mint sources mid-flow.
4. **Decisions log entry for `register_sources`** — should the apply path append a `decisions_log` entry like the migration path does? Lean: yes, for audit trail. Format: `skill="register_sources", decision=f"registered N sources ({M new + K reused})", rationale=...`. Minor — confirm at impl.

---

## 10. Summary

**Single new patch op** in AI-excel-addin: `RegisterSourcesOp` (Track-0-style additive bump).

**0 new modules** in AI-excel-addin — canonical `schema/source_registry.py` already exists; F82 wraps it.

**4 modified modules** in AI-excel-addin:
- `schema/handoff_patch.py` (add `RegisterSourcesOp` + import + union + `__all__`)
- `schema/__init__.py` (re-export)
- `api/research/handoff.py` (`_validate_source_refs_resolve` signature refactor: add `known_source_ids` param; update 3 call sites at :255,:648,:720 to pass it; NO migration logic change)
- `api/research/patch_engine.py` (add `_apply_register_sources` + in-batch single-register-validation + register-first stable partition + new `_rewrite_source_refs_recursive` walker + post-fold validation call + `_describe_op` branch)
- `tests/schema/snapshots/handoff_v1_1.schema.json` (snapshot regen for additive op)

**0 risk_module changes** — F82 is AI-excel-addin only.

**0 producer changes** — V2.P11 return shape is already patch-op-compatible.

**0 F83 skill changes** — skills continue to assume pre-registered sources; F82 makes this assumption satisfiable in production.

**0 F87 renderer changes** — already reads `Thesis.sources[]`.

After F82 ships:
- Producer-to-Thesis-to-renderer-to-skill pipeline runs end-to-end without fixture-injection
- F87 renderer displays canonical comps content for theses generated by an agent flow that emits the standard 3-4 op patch batch
- Production user-visible rollout for canonical comps becomes feasible (modulo F84 template migration for auto-invocation)
- F84 (process-template migration) is the only remaining gate

Lands as 1 phase / 1 commit in AI-excel-addin (plus Phase 2 verification — no commit).

---

## 11. Changelog

### R0 → R1 (2026-05-08)

Addresses Codex R0 review FAIL (5 blockers + 2 confirmations). All findings cite shipped code; fixes verified against canonical registry + actual producer return shape.

**B1 — Wrong source-merge core (F82.D4, §0 references, §4 file scope, §10 summary)**: R0 proposed extracting `_merge_legacy_sources_into_thesis` (handoff.py:678-740) into a new `api/research/source_merge.py` module. Codex caught that the legacy helper STRIPS provider/endpoint_or_filing_id/key_fields/retrieved_at/identity_hash and dedups on `{type, source_id, section_header, char_start, char_end}` — which would COLLAPSE distinct EDGAR/transcript KPI sources for canonical comps. R1: F82 builds on the canonical `schema/source_registry.py:14-78` (`register_source(sources, candidate)` with identity hash on `{type, source_id, endpoint_or_filing_id, key_fields}` per framework R6 §7.6) — the canonical core ALREADY EXISTS. F82.D4 reframed: wrap the canonical registry, do NOT extract from legacy helper. Major scope simplification: `api/research/source_merge.py` (new module from R0) is NOT created. Legacy migration path stays as-is.

**B2 — Multi-register-per-batch ambiguity (F82.D1, §4 patch-engine, §5 tests)**: R0 didn't constrain how many `register_sources` ops can appear in one batch. Two register ops can both mint `src_1`; body ops only carry plain source IDs (no namespace) → no way to disambiguate which `src_1` a cell means. R1: lock single-register-op-per-batch in v1; multi-bundle batches require explicit namespace design which is out of scope. Per CLAUDE.md "don't defer to dodge friction": out-of-scope explicitly, not "deferred for later" — revisit only if a real flow emerges.

**B3 — Validator scope (F82.D3, §4 handoff.py modification)**: R0 said run `_validate_source_refs_resolve(thesis.industry_analysis_dict)` post-batch. Codex caught that the helper auto-extracts `known_source_ids` from `value.sources` at root — running on the industry_analysis subtree alone produces empty known set → all citations fail. R1: refactor signature to `(value, *, known_source_ids: set[str])`; update existing call sites at handoff.py:255,648,720 to pass explicit `known_source_ids` (preserves migration semantics).

**B4 — Producer return shape (F82.D6 agent flow example, §0 references)**: R0 agent flow used `producer_output.peer_comparison.value` as if there were a nested `peer_comparison` namespace. Per `mcp_tools/industry.py:255-260`, producer return is FLAT: `{peers, sections, industry_key, template_manifest_id, as_of, sources, operating_comparison?}`. R1: F82.D6 example corrected — agent constructs `replace_industry_peer_comparison.value` (which is `IndustryPeerComparison` shape) from the flat fields explicitly.

**B5 — Rewrite scope incomplete (F82.D2, §5 tests)**: R0 enumerated 7 cell-citation paths but missed `update_macro_overlay.value.drivers[*].source_refs` (`MacroOverlayDriver` per `thesis_shared_slice.py:488`) and `replace_structural_trends.value[*].source_refs` (`StructuralTrend`). Also missed nested `replace_industry_peer_comparison.value.sections[*]...source_refs` (when full body is replaced rather than via `set_peer_comparison_sections`). R1: F82.D2 specifies recursive walk over op value trees as normative (not enumerated); enumerated paths are illustrative + tested explicitly; future schema additions auto-picked-up. F82 introduces a new `_rewrite_source_refs_recursive(value, mapping)` helper (NOT the legacy `_rewrite_source_refs_in_place` from handoff.py — that's tied to migration subtree walker).

**Confirmed (no change required, captured for §6.1)**:
- Patch batch atomicity is real today: engine folds in-memory + validates + single `update_thesis_artifact_if_version_matches` at end (`patch_engine.py:181`). F82 validation runs during the dry fold BEFORE persistence; explicitly do NOT pre-pass `repo.update_thesis_artifact`.
- Multi-op patch batches work via `apply_patch_ops(research_file_id, ops=[...])` MCP tool at `risk_module/mcp_server.py:2411`, forwarded as `{"ops": normalized_ops}` per `actions/research.py:1024`. Engine applies in input order today; F82 adds register-first stable partition.

### R1 → R2 (2026-05-08)

Addresses Codex R1 review FAIL (2 blockers + 1 high-risk).

**B1.repeated — Stale `source_merge.py` references in implementation sections (§§2.1, 5, 6.4, 8, 10)**: R1's F82.D4 + B1 changelog + §0 references correctly dropped the `api/research/source_merge.py` extraction, but six other sections still referenced it (§2.1 narrative, §5 test row, §6.4 cross-cutting "calls the new helper," §8 Phase 1 "extract source-merge core", §10 summary "1 new module" + file modification). Implementers reading those sections would have built the rejected module. R2: full grep + sweep of all `source_merge.py` / "extract source-merge" references; corrected to "wrap canonical `schema/source_registry.py`" everywhere; §10 summary now "0 new modules"; §8 collapsed to single-phase + verification.

**B4.repeated — §2.5 still described nested producer return shape (§2.5)**: R1 D6 corrected to flat shape but §2.5 audit-findings paragraph still listed `peer_comparison: { sections, peers, ... }` as a nested key. Implementers trusting §2.5 (audit findings) would have built around the wrong shape. R2: §2.5 corrected to FLAT — `peers, sections, industry_key, template_manifest_id, as_of` at top level (per `mcp_tools/industry.py:255-275`); explicit note that there is NO `industry_analysis.*` namespace in producer return; agent constructs `IndustryPeerComparison.value` from these flat fields.

**High-risk — Rewrite/validation key-set (D2, D3)**: R1 narrowed the recursive walker to `source_refs` + `citations` only. Existing migration semantics (per `handoff.py:59-60`) include the full key-set: `source_refs`, `citations`, `evidence`, `source_ref` (scalar). Since R1 promises no migration behavior change, omitting `evidence` and `source_ref` would either break migration parity OR require explicitly scoping the new walker to industry-only. R2: F82.D2 + F82.D3 explicitly preserve full migration key-set (`source_refs`, `citations`, `evidence`, `source_ref`); walker handles both list and scalar carriers; behavioral parity with migration semantics preserved + future schema additions on these keys are auto-picked-up.

### R2 → R3 (2026-05-08)

Addresses Codex R2 review FAIL (3 blockers + 1 cleanup). Pure consistency-sweep round — R1 + R2 had stale R0 text leaking into multiple sections.

**B1.repeated-again — `_merge_legacy_sources_into_thesis` reuse text (§§1, 2.1)**: §1 still said "Reuse the existing `_merge_legacy_sources_into_thesis` infrastructure (dedup, ID-mint, validate) — generalize it from migration-only to general-purpose via a shared helper" — directly contradicting F82.D4. §2.1 incorrectly described the legacy helper as using canonical identity fields. R3: §1 corrected to "Wrap the canonical `schema/source_registry.py:register_source`; legacy helper stays UNTOUCHED." §2.1 audit corrected to show ACTUAL legacy identity (`{type, source_id, section_header, char_start, char_end}` per `handoff.py:151`) is the WRONG identity for canonical comps + explicit pointer to canonical `schema/source_registry.py` as the right base.

**High-risk-residual — Rewrite scope language narrowed (F82.D2 paragraph at line 164, §4 patch_engine bullet at line 269, §5 test list at line 285)**: R2 added the full key-set declaration but body paragraphs still said "rewrites any `source_refs` / `citations` lists" (narrowed). Tests omitted `evidence` and scalar `source_ref` carriers. R3: all three sections updated to reference the full key-set explicitly; §5 tests now explicitly cover `evidence` (list-valued) and `source_ref` (scalar) carriers via synthetic test op shapes if no current op surfaces them — ensures forward-compat as schemas add carrier fields.

**B4.repeated-again — `editorial_peer_set` not in producer return (§2.5, F82.D6 agent flow)**: R2 §2.5 still listed `editorial_peer_set: list[EditorialPeer]` as an optional producer return field, and F82.D6 agent flow showed `set_editorial_peer_set: <producer.editorial_peer_set>`. Per `mcp_tools/industry.py:275`, the producer return is `peers, sections, industry_key, template_manifest_id, as_of, sources` + optional `operating_comparison` only — NO `editorial_peer_set`. Editorial peer set is INPUT to the producer (passed via `editorial_peer_set` parameter, written to Thesis by `competitive-position` / F83(a) skills), not OUTPUT. R3: §2.5 corrected to remove `editorial_peer_set` from return list + add explicit "NOT returned" note explaining it's curatorial input. F82.D6 agent flow drops the `set_editorial_peer_set` op + adds note that editorial peer set updates are out of scope for F82's persist-producer-output pipeline (curation is separate).

**Cleanup — §10 rollout count (line 413)**: §8 was collapsed to single phase + verification at R1, but §10 summary still said "2 phases / 2 commits + Phase 3." R3: §10 corrected to "1 phase / 1 commit + Phase 2 verification."
