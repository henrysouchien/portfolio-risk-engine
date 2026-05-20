# Track 0 — Schema & Patch Ops (Canonical Comps Framework)

**Status**: DRAFT R4 — addresses Codex R3 FAIL (0 blockers + 1 should-fix; parent framework R5 → R6 amended).
**Created**: 2026-05-07 (R0); revised 2026-05-07 (R1, R2, R3, R4).
**Revision history**:
- R4 — addresses Codex R3 FAIL: parent framework plan §4 Track A example still used unqualified `industry_comps_v1`; amended in framework plan R5 → R6 (one-line wording fix, no functional change). With R6 in place, no live reference to the unqualified `industry_comps_v1` remains across either document [P2].
- R3 — addresses Codex R2 FAIL: normalized `industry_comps_generic_v1` template id throughout the document, including narrative in earlier-revision changelog entries (Codex flagged that implementers read revision history when reconciling intent) [P2].
- R2 — addresses Codex R1 FAIL: (1) made source-id reconciliation an **explicit erratum** to framework R5 §7.6 — Track 0 supersedes R5 wording on stable-id format (R5 functional intent preserved); no parent-doc edit needed [P1]; (2) added `identity_hash: str | None` field to `SourceRecord` (§4.3) — `extra="forbid"` requires explicit field declaration, can't be hand-waved [P1]; (3) cleaned up leftover output-side feature-flag wording in §11 test row and §16 summary that contradicted the corrected write-gating semantics [P2]; (4) standardized template id to `industry_comps_generic_v1` everywhere live in the document (matches framework R5 D9 wording) [P2].
- R1 — addresses Codex R0 FAIL: (1) reconciled source-registry id contract with framework R5 — both docs now treat `src_N` as the public stable id (per existing `^src_[1-9]\d*$` regex at `thesis_shared_slice.py:30-32`) and the identity-hash as internal dedupe state; framework R5 §7.6 wording amended in this plan's §6 with a back-reference [P1]; (2) `SetPeerComparisonSectionsOp.value` narrowed from `IndustryPeerComparison` (would clobber legacy `peers`) to `list[SnapshotSection]` (patches only the new field) [P1]; (3) feature flag `INDUSTRY_ANALYSIS_V1_2_ENABLED` aligned with framework R5 — gates **writes**, not output (matches §3.5 of framework) [P2]; (4) added editorial peer focal-exclusion **enforcement** in patch-engine apply paths + tests (Pydantic model can't enforce without thesis context) [P2]; (5) ship one reference manifest + fixture in Track 0 (generic `industry_comps_generic_v1`) to validate loader/parity-test plumbing; extended CompsManifestMetric with source bindings, ordering, formulas per framework §7.7 [P2]; (6) resolved versioning-rename contradiction — no rename in v1 (matches §4.4); T0.D1 updated [P3].
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` (Codex R5 PASS) — see §3.5 for Track 0 scope.
**Closes**: prerequisite for Tracks A/B/C of the canonical comps framework.

**Authoritative code references** (verified by file read 2026-05-07):
- `AI-excel-addin/schema/thesis_shared_slice.py` — all comp-related types live here (SourceId at L30, SourceType at L29, IndustryAnalysis at L442, IndustryPeerComparison at L417, IndustryPeerComparisonPeer at L404, SourceRecord at L378)
- `AI-excel-addin/schema/handoff.py:119` — `HandoffArtifactV1_1` with `schema_version: Literal["1.1"]` and `industry_analysis: IndustryAnalysis | None = None`
- `AI-excel-addin/schema/handoff_patch.py:425-491` — existing 4 industry_analysis patch ops + discriminated union registration
- `AI-excel-addin/scripts/migrations/handoff_v1_0_to_v1_1.py` — migration pattern reference
- `AI-excel-addin/api/research/patch_engine.py` — patch apply path
- `risk_module/mcp_tools/industry.py:11-58` — current dual-write target shape

---

## 1. Purpose

Ship the schema and patch-op infrastructure that Tracks A, B, C all consume. Per the framework plan §3.5, Track 0 is a hard prerequisite: the new fields don't exist without it.

This plan does **not** populate data (Tracks A/B) or curate peers (Track C). It only adds the contract.

---

## 2. Audit findings (grounded by code read)

| Finding | File | Implication |
|---|---|---|
| `IndustryPeerComparison` currently has ONLY `peers: list[IndustryPeerComparisonPeer]` | `thesis_shared_slice.py:417-418` | New fields must be added to this model |
| `IndustryPeerComparisonPeer` shape exactly matches `mcp_tools/industry.py` output | `thesis_shared_slice.py:404-414` vs `mcp_tools/industry.py:48-57` | Dual-write semantic parity is structurally already there — no churn |
| All comp models extend `_ContractModel` with `extra="forbid"` | `thesis_shared_slice.py:66-69` | Additive fields require Pydantic class edits, NOT just on-wire additions |
| `SourceId = str` matching `^src_[1-9]\d*$` | `thesis_shared_slice.py:30-32` | **Registry IDs are sequential `src_N`, NOT content hashes**. Framework plan's "hash" is the dedupe key; registry assigns `src_N` after dedupe |
| `SourceType` closed enum: `filing \| transcript \| investor_deck \| other` | `thesis_shared_slice.py:29` | FMP → `other`, EDGAR → `filing`, transcripts → `transcript` (matches framework plan R4 fix) |
| `HandoffArtifactV1_1.schema_version: Literal["1.1"]` | `handoff.py:155` | Cannot add v1.2 by extending Literal in place; need either new class `HandoffArtifactV1_2` or widen Literal |
| Existing industry_analysis patch ops use `target: None, value: <full-type>` (replace-whole-section) | `handoff_patch.py:429-450` | Granular peer add/remove needs different pattern (similar to `AddRiskOp` / `RemoveRiskOp`) |
| `HandoffPatchOp` discriminated union explicitly enumerates each op class | `handoff_patch.py:453-491` | New ops must be added to this Annotated[Union[...]] |
| Migration scripts live at `scripts/migrations/handoff_v1_0_to_v1_1.py` | (path) | Pattern to follow for v1.1 → v1.2 |

**Gap summary:** the comp-framework new fields (`editorial_peer_set`, `operating_comparison`, `peer_comparison.sections`/etc.) require:
1. New Pydantic classes (EditorialPeer, OperatingComparison, Section, etc.)
2. Extension of `IndustryPeerComparison` and `IndustryAnalysis`
3. Either `HandoffArtifactV1_2` or widened Literal — decided in §4.1
4. New patch ops + registration in discriminated union
5. Migration script v1.1 → v1.2
6. Industry-key taxonomy decision (per framework D9)
7. Template-manifest yaml schema (per framework §7.7)
8. Source-registry helpers (`src_N` minting + dedupe)
9. Feature flag wiring

---

## 3. Locked design decisions (Track-0-specific, inherit from framework R5)

### T0.D1. Versioning approach: widen `schema_version` Literal; keep class name
Add `schema_version: Literal["1.1", "1.2"] = "1.2"` to `HandoffArtifactV1_1`. **Class name stays `HandoffArtifactV1_1` in this track** (rename to `HandoffArtifact` is a separate cleanup follow-up that touches every import site). Rationale: matches existing additive-field pattern; avoids forking Pydantic class hierarchy; minimal blast radius. Old payloads with `schema_version: "1.1"` validate cleanly because new fields are optional with defaults.

### T0.D2. Patch op granularity for editorial peers
Editorial peer set gets **granular ops** (`add_editorial_peer`, `remove_editorial_peer`, `set_editorial_peer_set`) following the existing `AddRiskOp`/`RemoveRiskOp`/`UpdateRiskOp` pattern. Track A's generated `peer_comparison.sections` and Track B's `operating_comparison` get **replace ops** (`set_peer_comparison_sections`, `set_operating_comparison`) following the existing `ReplaceIndustryPeerComparisonOp` pattern.

### T0.D3. SourceId minting (reconciles framework R5 §7.6 with code reality)

**Code constraint**: existing `SourceId = Annotated[str, StringConstraints(pattern=r"^src_[1-9]\d*$")]` at `thesis_shared_slice.py:30-32` requires `src_N` integer-suffix format. Changing this regex would invalidate every existing thesis and is out of scope.

**Framework reconciliation**: framework R5 §7.6 says `Thesis.sources[].id` is "computed from logical-identity fields"; existing code requires `src_N` format. Track 0 reconciles by treating these as **layered concerns**:

- **Public stable id (`src_N`)** — the registry-assigned token used in cells and across snapshots. Format constrained by existing regex. Once minted, never changes.
- **Internal identity hash** — deterministic hash of `{type, source_id, endpoint_or_filing_id, key_fields}`, stored on the registry entry as a **non-exposed dedupe key**. Same logical source pulled at different times resolves to the same hash → same registered `src_N` returned.

**Functional contract preserved** (matches framework R5 intent):
- Cells reference registry ids ✓ (via `src_N`)
- Same logical source dedupes across pulls ✓ (via internal hash)
- IDs stable across snapshots ✓ (`src_N` once assigned doesn't change)

**Registry helper** `register_source(sources, candidate) -> tuple[SourceId, list[SourceRecord]]`:
1. Compute identity hash of candidate's logical-identity fields
2. Look up hash in `sources` — if present (matched on stored hash field), return existing `id`
3. If not present, mint next sequential `src_N` (where N = max(existing) + 1, starting at `src_1`), append SourceRecord with `identity_hash` field stored, return new `id`

**ERRATUM TO FRAMEWORK R5 §7.6** (Track 0 R2 supersedes the parent on stable-id format):

Framework R5 §7.6 says: *"each registry entry has a deterministic `id` computed from logical-identity fields"* — wording made without verifying the existing `^src_[1-9]\d*$` regex constraint at `thesis_shared_slice.py:30-32`.

**This Track 0 plan supersedes that R5 wording on the stable-id format**:
- Stable id format is `src_N` (sequential, integer-suffixed) — required by existing code; changing it would invalidate every existing thesis with sources
- Identity-hash is internal dedupe state stored as `SourceRecord.identity_hash` (§4.3), not the public id
- Cells reference the `src_N` id (per existing convention)

**R5 functional requirements preserved** (the actual contract that matters):
- Cells reference registry ids ✓
- Same logical source dedupes across pulls ✓ (via internal hash)
- IDs stable across snapshots ✓ (`src_N` once minted doesn't change)

This erratum is the authoritative spec for Track 0 implementation and downstream tracks. Framework R5 wording remains historically committed for traceability but the contract on stable-id format follows this section.

### T0.D4. Industry-key taxonomy: editorial mapping with FMP-industry as primary key
v1 taxonomy:
- Primary key: FMP `industry` field (lowercased, snake-cased) — comes from `compare_peers` already via `fmp_profile`
- Editorial overlay: `config/industry_taxonomy.yaml` maps FMP industries → editorial buckets where they need to be combined or split (e.g., `"software—application"` + `"software—infrastructure"` → editorial `"software"`)
- Reserved value: `"unknown"` (per framework D9) — used when FMP industry is missing OR no editorial mapping exists yet
- v1 enumerated reference industries: `hr_payroll`, `grocers`, `+1 TBD` (chosen during impl)

GICS sub-industry deferred — FMP coverage is sufficient for v1 and avoids a second classifier dependency.

### T0.D5. Template-manifest yaml lives at `config/comps_templates/`
- One file per template: `<template_id>.yaml` (e.g., `industry_comps_generic_v1.yaml`, `operating_comps_hr_payroll_v1.yaml`)
- Companion CSV fixture: `<template_id>.fixture.csv` (per framework §7.7)
- Manifest schema is a Pydantic model at `AI-excel-addin/schema/comps_template.py`
- Yaml is the editable spec; fixture is the deterministic test artifact

### T0.D6. Feature flag gates writes (matches framework R5)
`INDUSTRY_ANALYSIS_V1_2_ENABLED` env var (default off). Per framework R5 §3.5, the flag gates **v1.2 writes** during rollout — when off, producers do NOT populate the new fields (`editorial_peer_set`, `operating_comparison`, `peer_comparison.sections`/`industry_key`/`template_manifest_id`/`as_of`); when on, producers populate them.

Rationale: avoids raw-storage/API inconsistency during rollout. If writes are gated off, no v1.2 data exists yet, so consumers gated on don't see partial/inconsistent data. Easier to reason about than "write-always, project-output."

Schema additions ship behind the flag in the off state (additive fields with defaults — no behavioral change). Tracks A/B/C populate fields once the flag is on.

Read paths do not need a flag check — readers tolerate empty new fields by virtue of optional defaults. Once the flag is permanently on, the flag check is removed in a follow-up cleanup.

---

## 4. Schema changes (concrete Pydantic edits)

All edits in `AI-excel-addin/schema/thesis_shared_slice.py` unless noted.

### 4.1 New types

```python
class EditorialPeer(_ContractModel):
    ticker: str
    name: str
    source: Literal["editorial"] = "editorial"
    added_by: str | None = None
    added_at: str | None = None  # ISO 8601
    rationale: str | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def _validate_ticker(cls, value: object) -> str:
        return _normalize_ticker(value)

class CompMetricCell(_ContractModel):
    value: ScalarValue | None = None
    source_refs: list[SourceId] = Field(default_factory=list)
    derived: bool = False  # true for medians, computed ratios

class SnapshotMetric(_ContractModel):
    key: str = Field(min_length=1)
    label: str
    units: str | None = None
    values: dict[str, CompMetricCell] = Field(default_factory=dict)  # ticker -> cell
    median: CompMetricCell | None = None

class SnapshotSection(_ContractModel):
    name: str
    metrics: list[SnapshotMetric] = Field(default_factory=list)

class TimeseriesMetric(_ContractModel):
    key: str = Field(min_length=1)
    label: str
    units: str | None = None
    series: dict[str, dict[int, CompMetricCell]] = Field(default_factory=dict)  # ticker -> year -> cell
    median_series: dict[int, CompMetricCell] = Field(default_factory=dict)

class TimeseriesGroup(_ContractModel):
    name: str
    metrics: list[TimeseriesMetric] = Field(default_factory=list)

class OperatingComparison(_ContractModel):
    industry_key: str
    template_manifest_id: str
    years: list[int] = Field(default_factory=list)
    metric_groups: list[TimeseriesGroup] = Field(default_factory=list)
```

### 4.2 Extensions to existing types (additive only)

```python
# IndustryPeerComparison — add 4 fields, keep `peers` unchanged
class IndustryPeerComparison(_ContractModel):
    peers: list[IndustryPeerComparisonPeer] = Field(default_factory=list)  # UNCHANGED
    industry_key: str | None = None  # NEW
    template_manifest_id: str | None = None  # NEW
    as_of: str | None = None  # NEW (ISO 8601 date)
    sections: list[SnapshotSection] = Field(default_factory=list)  # NEW

# IndustryAnalysis — add 2 fields
class IndustryAnalysis(_ContractModel):
    landscape: IndustryLandscape | None = None
    peer_comparison: IndustryPeerComparison | None = None
    macro_overlay: MacroOverlay | None = None
    structural_trends: list[StructuralTrend] = Field(default_factory=list)
    editorial_peer_set: list[EditorialPeer] = Field(default_factory=list)  # NEW
    operating_comparison: OperatingComparison | None = None  # NEW
```

### 4.3 SourceRecord additive provenance + identity fields

```python
class SourceRecord(_ContractModel):
    # existing fields unchanged: id, type, source_id, section_header, char_start, char_end, text, annotation_id
    # NEW additive fields:
    provider: str | None = None
    endpoint_or_filing_id: str | None = None
    key_fields: dict[str, ScalarValue] | None = None
    retrieved_at: str | None = None  # ISO 8601, provenance only — NOT identity
    identity_hash: str | None = None  # internal dedupe state; required because models use extra="forbid"
                                       # — register_source() looks up by this field to detect existing entries
```

**Why `identity_hash` is a stored field (not recomputed on lookup)**: `_ContractModel` uses `extra="forbid"`, so the helper can't store hash state out-of-band. Lookups by recomputation each call would be O(n²) on large registries. Stored field is the simple, correct choice. `identity_hash` is `None` for entries created before Track 0 ships; the helper handles that case via fall-through (recompute identity, compare against derived hash of existing entries until first call mints + stores).

### 4.4 HandoffArtifact version widening

In `handoff.py:155`:
```python
schema_version: Literal["1.1", "1.2"] = "1.2"
```

No class rename in v1; the `V1_1` suffix becomes mildly misleading but renaming is a follow-up cleanup (impacts all imports — out of scope here).

### 4.5 Update `__all__` exports

Add to `thesis_shared_slice.py:449` `__all__`: `CompMetricCell`, `EditorialPeer`, `OperatingComparison`, `SnapshotMetric`, `SnapshotSection`, `TimeseriesGroup`, `TimeseriesMetric`.

---

## 5. Patch ops

In `AI-excel-addin/schema/handoff_patch.py`.

### 5.1 New op classes (follow existing pattern)

```python
class AddEditorialPeerOp(_PatchOpBase):
    op: Literal["add_editorial_peer"] = "add_editorial_peer"
    target: None = None
    value: EditorialPeer

class RemoveEditorialPeerOp(_PatchOpBase):
    op: Literal["remove_editorial_peer"] = "remove_editorial_peer"
    target: StableIdTarget  # use existing target type with id=ticker
    value: None = None

class SetEditorialPeerSetOp(_PatchOpBase):
    op: Literal["set_editorial_peer_set"] = "set_editorial_peer_set"
    target: None = None
    value: list[EditorialPeer]

class SetPeerComparisonSectionsOp(_PatchOpBase):
    op: Literal["set_peer_comparison_sections"] = "set_peer_comparison_sections"
    target: None = None
    value: PeerComparisonSectionsValue  # narrow payload — patches ONLY .sections + accompanying scalar fields, leaves legacy .peers alone

class PeerComparisonSectionsValue(_ContractModel):
    """Narrow payload for SetPeerComparisonSectionsOp — patches only the new v1.2
    fields on IndustryPeerComparison. Does NOT touch legacy `peers` (which is
    written by Track A's dual-write surface, not by this op)."""
    sections: list[SnapshotSection] = Field(default_factory=list)
    industry_key: str | None = None
    template_manifest_id: str | None = None
    as_of: str | None = None

class SetOperatingComparisonOp(_PatchOpBase):
    op: Literal["set_operating_comparison"] = "set_operating_comparison"
    target: None = None
    value: OperatingComparison
```

### 5.2 Discriminated union registration

Append all 5 new ops to `HandoffPatchOp` union at `handoff_patch.py:453-491`. Append matching exports to `__all__`.

### 5.3 Patch engine apply paths

In `AI-excel-addin/api/research/patch_engine.py`, add apply branches for the 5 new op types. Pattern follows existing `_apply_industry_analysis_patch` helper.

**Critical apply-path semantics:**

- **`AddEditorialPeerOp` / `SetEditorialPeerSetOp`** — must enforce focal-ticker exclusion at apply time (Pydantic model can't, since it lacks Thesis context). Reject (or filter, behind a strict-mode flag) any `EditorialPeer` whose `ticker` matches the focal ticker resolved from the parent Thesis/Handoff. Default behavior: **reject** with explicit error (matches project's "fail loudly" pattern). Strict-mode flag for filter-instead-of-reject is out of scope for v1.

- **`SetPeerComparisonSectionsOp`** — applies the narrow `PeerComparisonSectionsValue` payload by merging into existing `peer_comparison` (creating it if absent). Specifically: copies `value.sections`, `value.industry_key`, `value.template_manifest_id`, `value.as_of` onto the existing `peer_comparison` instance; **does NOT touch `peer_comparison.peers`** (legacy field, written by Track A's dual-write surface). If `peer_comparison` is None, create a new `IndustryPeerComparison` with `peers=[]` (matches default) and the new fields populated.

- **`RemoveEditorialPeerOp`** — `target.id` is interpreted as the ticker (since editorial peers don't have separate ids). Apply removes the peer with matching ticker; no-op if not present (or fail-loud — decided in impl by parity with existing remove-ops).

- **`AddEditorialPeerOp` / `RemoveEditorialPeerOp` / `SetEditorialPeerSetOp`** also enforce ticker uniqueness within `editorial_peer_set` (no two entries with same ticker). Pydantic-level uniqueness validator on the field is preferable; apply path is the backstop.

---

## 6. Source-registry helpers

New module: `AI-excel-addin/schema/source_registry.py`.

```python
def compute_identity_hash(
    type: SourceType,
    source_id: str,
    endpoint_or_filing_id: str | None,
    key_fields: dict[str, ScalarValue] | None,
) -> str: ...

def register_source(
    sources: list[SourceRecord],
    candidate: SourceRecord,
) -> tuple[SourceId, list[SourceRecord]]:
    """Dedupe via identity hash; mint sequential src_N if new.
    Returns (registered_id, updated_sources_list).
    Pure function — caller writes back."""
    ...

def next_source_id(existing: list[SourceRecord]) -> SourceId:
    """Find max src_N in existing, return src_(N+1). src_1 if empty."""
    ...
```

Helper consumers (Track A/B downstream):
- `risk_module/fmp/tools/peers.py` (registers FMP endpoint snapshots)
- `risk_module/mcp_tools/industry.py` (registers via dual-write)
- `AI-excel-addin/...edgar/...` paths for filings (Track B)

Cross-repo PYTHONPATH-based import per master plan §7.

---

## 7. Industry-key taxonomy

### 7.1 New module: `AI-excel-addin/config/industry_taxonomy.yaml`

```yaml
schema_version: "1.0"
reference_industries:
  hr_payroll:
    display_name: "HR / Payroll"
    fmp_industries: ["software—application"]  # subset; manually curated
    fmp_industry_filter: "payroll|HCM|human capital"  # case-insensitive substring on company description
  grocers:
    display_name: "Grocers"
    fmp_industries: ["grocery stores"]
  # +1 TBD during impl
```

### 7.2 Resolver helper

`AI-excel-addin/schema/industry_resolver.py`:
```python
def resolve_industry_key(fmp_profile: dict) -> str:
    """Return reference industry key, or 'unknown' if no mapping."""
```

Used by Track A and Track B at artifact-build time.

---

## 8. Template-manifest schema

New module: `AI-excel-addin/schema/comps_template.py`.

Per framework R5 §7.7, manifests must capture: section names + ordering, metric keys + display labels + units + null policy, aggregation rules per metric, source bindings (formula / endpoint), source editorial template metadata.

```python
class CompsManifestSourceBinding(_ContractModel):
    """How a metric is computed/sourced (per framework §7.7 'formulas')."""
    kind: Literal["fmp_endpoint", "edgar_concept", "transcript_kpi", "derived"]
    # For fmp_endpoint: which endpoint + key
    fmp_endpoint: str | None = None       # e.g., "ratios_ttm"
    fmp_field: str | None = None          # e.g., "priceToEarningsRatioTTM"
    # For edgar_concept: which us-gaap concept
    edgar_concept: str | None = None
    # For transcript_kpi: which KPI key (Track B operating-comps domain)
    kpi_key: str | None = None
    # For derived: formula string (parsed by Track A/B impls)
    derived_formula: str | None = None    # e.g., "free_cash_flow / revenue"

class CompsManifestMetric(_ContractModel):
    key: str
    label: str
    units: str | None = None
    order: int                            # explicit ordering within section (per framework §7.7)
    aggregation: Literal["median", "mean", "weighted"] = "median"
    null_policy: Literal["skip", "zero", "fail"] = "skip"
    source: CompsManifestSourceBinding   # how to compute/fetch this metric

class CompsManifestSection(_ContractModel):
    name: str
    order: int                            # explicit ordering across sections
    metrics: list[CompsManifestMetric]

class CompsTemplateManifest(_ContractModel):
    template_id: str
    template_kind: Literal["industry_comps", "operating_comps"]
    industry_key: str | None = None       # required for operating_comps; None for generic industry_comps
    source_gsheet_id: str | None = None   # editorial reference
    source_gsheet_version: str | None = None
    sections: list[CompsManifestSection]
```

Yaml files at `config/comps_templates/<template_id>.yaml` deserialize via this Pydantic model.

**Reference manifest shipped in Track 0** (validates the loader + parity-test plumbing):
- `config/comps_templates/industry_comps_generic_v1.yaml` — generic industry-comps manifest used by Track A's `unknown` fallback per framework D9; covers the FMP-addressable metrics
- `config/comps_templates/industry_comps_generic_v1.fixture.csv` — companion fixture exported from the editorial gsheet at manifest creation time; deterministic offline reference for parity tests

Per-industry manifests (operating-comps for HR-Payroll, Grocers, +1 TBD) are populated by Tracks A/B, not Track 0.

Loader: `AI-excel-addin/config/comps_template_loader.py` — reads yaml, validates against Pydantic, returns model. Parity test in `tests/schema/test_comps_template_manifest.py` compares loaded manifest against `<template_id>.fixture.csv` (deterministic, offline; no live gsheets required).

---

## 9. Migration

`AI-excel-addin/scripts/migrations/handoff_v1_1_to_v1_2.py`:
- No payload changes (additive). Migration is a no-op for existing rows: just bump `schema_version` from `"1.1"` to `"1.2"`.
- Backfill of `editorial_peer_set` / `operating_comparison` etc. is **out of scope** (per framework §8 out-of-scope). Existing rows have empty defaults.

Optional: add a parity test asserting v1.1 payloads validate as v1.2 (since all new fields default).

---

## 10. Feature flag wiring

`INDUSTRY_ANALYSIS_V1_2_ENABLED` env var (default off) — gates **writes**, per T0.D6 / framework R5:

- Read at gateway/API startup
- **When off**: producers do NOT populate v1.2 fields (`editorial_peer_set`, `operating_comparison`, `peer_comparison.sections|industry_key|template_manifest_id|as_of`). Schema accepts them but defaults remain in place. Patch ops that target v1.2 fields raise an explicit `FeatureFlagDisabledError` rather than silently no-oping.
- **When on**: producers populate v1.2 fields normally. Tracks A/B/C populate via their own surfaces.
- Read paths require no flag check — readers tolerate empty new fields (all are optional with safe defaults).

**Producer surfaces that must check the flag**:
- Patch-engine apply paths for the 5 new ops (raise FeatureFlagDisabledError when off)
- (Future, in Track A's plan) `mcp_tools/industry.py` dual-write surface
- (Future, in Tracks B/C plans) per-track populating tools

Flag check helper: `AI-excel-addin/api/research/feature_flags.py:is_industry_analysis_v1_2_enabled()`. Existing env-var feature-flag pattern in `AI-excel-addin/api/research/`: `RESEARCH_EDITORIAL_BRIEF_ENABLED`. Track 0 follows the same convention.

Once the flag is permanently on (after Tracks A/B/C ship), the flag check is removed in a cleanup follow-up.

---

## 11. Tests

| Test file | Coverage |
|---|---|
| `AI-excel-addin/tests/schema/test_thesis_shared_slice_v1_2.py` (new) | New types accept valid input, reject invalid; existing types still accept v1.1 payloads |
| `AI-excel-addin/tests/schema/test_handoff_patch_v1_2_ops.py` (new) | Each new patch op validates and registers in HandoffPatchOp union; op_id uniqueness enforced |
| `AI-excel-addin/tests/api/research/test_patch_engine_v1_2.py` (new) | Apply paths for each new op; idempotency where applicable; **focal-ticker rejection on `add_editorial_peer` and `set_editorial_peer_set` when peer matches Thesis focal**; **`SetPeerComparisonSectionsOp` does NOT touch legacy `peers` field**; **FeatureFlagDisabledError raised when flag off** |
| `AI-excel-addin/tests/schema/test_source_registry.py` (new) | Identity-hash dedupe across repeated registrations; sequential `src_N` minting; collision handling |
| `AI-excel-addin/tests/scripts/test_handoff_migration_v1_1_to_v1_2.py` (new) | v1.1 payload validates as v1.2; schema_version bump |
| `AI-excel-addin/tests/schema/test_industry_resolver.py` (new) | FMP profile → industry_key resolution; `unknown` fallback |
| `AI-excel-addin/tests/schema/test_comps_template_manifest.py` (new) | Yaml manifest validates; fixture-CSV parity test pattern |
| `AI-excel-addin/tests/api/research/test_feature_flag_v1_2.py` (new) | When flag off, patch ops targeting v1.2 fields raise `FeatureFlagDisabledError`; producers do NOT populate v1.2 fields. When flag on, v1.2 writes succeed. (Read paths require no flag check — covered by other tests.) |
| `AI-excel-addin/tests/integration/test_handoff_v1_2_e2e.py` (new) | End-to-end: write artifact with new fields, read back via API with flag on |

Approximate count: ~9 new test files, ~30-50 test cases. Existing tests must continue to pass unchanged.

---

## 12. File-by-file changes

### AI-excel-addin (primary)
- `schema/thesis_shared_slice.py` — add 7 new types; extend IndustryPeerComparison + IndustryAnalysis + SourceRecord; update `__all__`
- `schema/handoff.py` — widen `schema_version` Literal
- `schema/handoff_patch.py` — add 5 new patch op classes; extend HandoffPatchOp union; update `__all__`
- `schema/source_registry.py` — NEW (helpers)
- `schema/industry_resolver.py` — NEW
- `schema/comps_template.py` — NEW (manifest Pydantic)
- `config/industry_taxonomy.yaml` — NEW
- `config/comps_templates/` — NEW directory; ships with one reference template:
  - `config/comps_templates/industry_comps_generic_v1.yaml` — generic snapshot manifest (validates loader + parity test)
  - `config/comps_templates/industry_comps_generic_v1.fixture.csv` — companion deterministic fixture
  - Per-industry manifests populated by Tracks A/B
- `config/comps_template_loader.py` — NEW
- `api/research/patch_engine.py` — extend apply dispatch for 5 new ops
- `api/research/feature_flags.py` — NEW (or extend existing)
- `scripts/migrations/handoff_v1_1_to_v1_2.py` — NEW
- `tests/schema/test_*.py` and `tests/api/research/test_*.py` — 9 new test files per §11

### risk_module (consumer)
- No changes in Track 0. Track A's follow-on plan introduces dual-write at `mcp_tools/industry.py` and registry calls at `fmp/tools/peers.py`.

---

## 13. Rollout sequence

1. **Phase 1**: ship schema additions + patch ops + helpers (no behavioral change yet — v1.2 fields exist but nothing populates them)
2. **Phase 2**: ship feature flag wiring + migration + tests
3. **Phase 3**: keep flag off in production until Tracks C/A/B start populating
4. Feature-flag flip happens after Track A's first deploy (handled in Track A's plan)

Each phase is a separate PR. Phases 1 and 2 can ship together if review bandwidth allows.

---

## 14. Out of scope

- Data population — Tracks A and B
- Editorial peer curation skill — downstream
- Renderer changes — Track A/B follow-on plans
- Dual-write at `mcp_tools/industry.py` — Track A
- Removal of legacy `peer_comparison.peers` — major bump (v2.0); future
- Backfill of historical Thesis snapshots to v1.2 fields — explicit non-goal per framework §8
- KPI registry yaml files — Track B
- Class rename `HandoffArtifactV1_1` → `HandoffArtifact` — cleanup follow-up (impacts every import)

---

## 15. Open questions (deferrable)

1. **Reference industry #3** — beyond HR-Payroll and Grocers. Pick during impl based on existing analyst coverage. Not blocking.
2. **Identity-hash collision policy** — when `compute_identity_hash` collides (extremely unlikely with logical-identity fields), do we fail-loud or version-suffix? Decided by impl; default fail-loud per project convention.
3. **`src_N` overflow / large registries** — sequential IDs work for the foreseeable future. If we ever hit `src_999_999`, revisit. Not v1 concern.
4. **Cross-repo PYTHONPATH wiring** — already in place per master plan §7; verify during impl that new module paths (`schema/source_registry.py` etc.) resolve cleanly.

---

## 16. Summary

Track 0 adds the contract for canonical comps without changing any existing behavior:
- **9 new Pydantic types** (EditorialPeer, OperatingComparison, snapshot/timeseries section/metric/cell types, manifest types)
- **3 extended types** (IndustryPeerComparison, IndustryAnalysis, SourceRecord — strictly additive fields)
- **5 new patch ops** registered in the discriminated union (with focal-ticker enforcement + narrow `SetPeerComparisonSectionsOp` payload that doesn't clobber legacy `peers`)
- **3 new modules** (source_registry, industry_resolver, comps_template)
- **2 new yaml configs** (industry_taxonomy, comps_templates/ dir)
- **1 schema_version widening** (Literal["1.1"] → Literal["1.1", "1.2"])
- **1 migration script** (no-op except version bump)
- **1 feature flag** (env-var-gated **write path** — patch ops to v1.2 fields raise `FeatureFlagDisabledError` when off)
- **~9 new test files**

All edits are additive. Existing v1.1 payloads continue to validate. Tracks C, A, B unblock as soon as Phase 1 lands.

---
