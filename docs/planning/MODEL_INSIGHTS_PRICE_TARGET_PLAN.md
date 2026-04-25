# Plan #6 — `ModelInsights` + `PriceTarget` + `HandoffPatchOp` v1.0 (Investment Schema Unification)

**Status**: ✅ **SHIPPED 2026-04-24** — Sub-phases A-prereq through H implemented across AI-excel-addin + risk_module; closes G3 (typed `ModelInsights`) + G4 (typed `PriceTarget`) per master plan §6.4.

**Last revised**: 2026-04-24 (SHIPPED — final status banner + ship log).

**Authoritative design reference**: `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §6.4 (Codex PASS R6). This plan implements what §6.4 designed.

**Companion docs**:
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` (skill + modeling-studio consumers)
- `docs/planning/completed/MODEL_BUILD_CONTEXT_PLAN.md` (plan #3 — produces `ModelBuildContext` that this plan's `ModelInsights` references)
- `AI-excel-addin/docs/planning/completed/HANDOFF_ARTIFACT_V1_1_PLAN.md` (plan #2 — `scorecard_ref`, `idea_provenance`, and Thesis shared-slice that patch ops target)

**Closes**: **G3** (model output ambiguity — no typed contract for driver sensitivities / implied assumptions / model-surfaced risks) and **G4** (no typed price target — price-target prose scattered across thesis markdown). §6.4 of master plan.

---

## 1. Purpose & scope

Ship three related typed Pydantic contracts that make the modeling studio's outputs first-class + turn the model→Thesis feedback loop into a typed grammar:

1. **`ModelInsights v1.0`** — typed snapshot of what a model build produced beyond raw numbers: driver sensitivities, implied assumptions (made explicit by the build), risks surfaced during the build, and a list of suggested patches to the originating Thesis.
2. **`PriceTarget v1.0`** — typed representation of a scenario-weighted price target: ranges (low/mid/high), method, driver sensitivities, time horizon, implied return.
3. **`HandoffPatchOp v1.0`** — typed discriminated-union grammar for the model→Thesis feedback loop. Each op targets a stable ID (`assumption_id`, `risk_id`, `catalyst_id`, `claim_id`, `trigger_id`) and carries a typed value. Applied (after analyst review) to the Thesis SoT — HandoffArtifact re-derives via shared-slice isomorphism.

### 1.1 Out of scope (v1)

- Auto-applying patches without analyst review (always human-in-the-loop)
- Retroactive regeneration of ModelInsights from old model builds
- Patch ops targeting Handoff-only fields (idea_provenance, assumption_lineage) — deferred to follow-on plans per §6.4 R5
- Cross-model insight aggregation (this plan is per-model-build)
- Frontend patch-review UI — skeleton API only; UI deferred

### 1.2 Scope additions (surfaced by Codex R1)

Two prerequisite items that grew out of Codex R1 integration-reality checks:

1. **MBC `valuation.method` enum widening** — Shipped `ModelBuildContext.valuation.method: ValuationMethod = Literal["dcf", "multiples", "sum_of_parts", "hybrid"]` (at `schema/model_build_context.py:21`) rejects `"relative"`, but shared-slice `Valuation.method: str | None` accepts it and plan #5's prepopulate emits it. Today's MBC builder at `mbc_service.py:162` silently drops or errors when handoff method is `"relative"`. Plan #6 widens `ValuationMethod` alias to `str | None` (or equivalently keeps the Literal as Union of existing 4 + `"relative"`). This unblocks §3.6 Q3 supersession. **Scope impact**: one type-alias change + updated MBC validator tests. Bundled into sub-phase A-prereq.

2. **Optimistic concurrency control (OCC) on `theses` rows** (R2.4 pivot per Codex R5, R2.5 simplification per Codex R6). The patch engine's core safety invariant is:

   > When patch engine writes `S' = fold(S)`, the row version at write-time must equal the version at read-time. If any other writer committed between read and write, the write must fail — not proceed with stale data.

   This is a compare-and-swap on the `theses` row — the textbook pattern for multi-writer row safety (Django, Rails, Hibernate, SQLAlchemy all ship this).

   **R2.5 discovery (Codex R6)**: the required infrastructure is **already shipped in v7**:
   - `theses.version INTEGER NOT NULL DEFAULT 1` column exists at `repository.py:54,61`
   - `_persist_thesis_payload` at `repository.py:1302` already bumps `version = version + 1` on every write (via the `increment_version: bool = True` default — no caller passes `False`, so every shipped writer already participates)
   - `Thesis` Pydantic model at `schema/thesis.py:222` already includes `version: int = Field(default=1, ge=1)`

   **Plan #6's actual scope for OCC** is much smaller than R2.4 specified:
   - **NO schema migration** (v7 already has the column)
   - **NO edit to `_persist_thesis_payload`** (it already bumps on every write)
   - **ONLY add**: a new repository method `update_thesis_artifact_if_version_matches(thesis_id, thesis, expected_version) → bool` that issues `UPDATE theses SET ..., version = ? WHERE thesis_id = ? AND version = ?` with `new_version = expected_version + 1`. Returns `True` on `rowcount==1`, `False` on mismatch. All other shipped write paths (rename, watcher, link, scorecard, decisions-log, apply_process_template, finalize seed/merge) continue to use existing `_persist_thesis_payload` and bump `version` as they do today.
   - Patch engine pipeline (§8.2): reads `version` at dry-fold time, does fold, calls the new CAS method. Mismatch → `PatchStaleError` → bounded retry (3 attempts, 50ms backoff).

   **Why this supersedes the R2.1-R2.3 lock-expansion plan**:
   - `_handoff_lock` (fcntl.flock) is NOT re-entrant in-process (Codex R5 local-verified: second acquire → `EAGAIN`). Existing callers like `finalize_handoff`, `_persist_shared_slice_write`, and `apply_process_template` already hold it and reach writers through private helpers — wrapping the writers directly would deadlock.
   - Lock-order inversion: `update_file()` opens `BEGIN IMMEDIATE` BEFORE calling `update_thesis_parent_snapshot`; patch-apply used `_handoff_lock → BEGIN IMMEDIATE`. Wrapping the snapshot call would invert the order and risk deadlock.
   - Decisions-log exemption was wrong at the method level — direct callers bypass the helper's lock.
   - OCC sidesteps ALL of these issues AND uses existing infrastructure.

   **`_handoff_lock` keeps its current role**: handoff lifecycle serialization (plan #2/#5 state-machine concerns — finalize, draft transitions, template application). Plan #6 does NOT expand it. Patch engine does not take `_handoff_lock` at all — OCC is the only coordination needed.

   **Bonus for existing writers** (R2.5 clarified): existing shipped writers (link, scorecard, watcher, rename) already bump version on every write, but they don't DETECT stale reads — they just overwrite, last-writer-wins. Plan #6 introduces CAS for the patch engine only. If product need later arises for other writers to detect stale reads, they can adopt the same `_if_version_matches` pattern independently; plan #6 doesn't force that change.

   **Scope impact**: ~15 lines total — one new repository method (~10 lines) + retry loop in patch engine (~5 lines) + 3 OCC tests. A-prereq for OCC work: near-zero (MBC method widen is the only remaining A-prereq task). **A-prereq total duration: ~0.25 day.**

**Scope placement**: MBC method widen ships in sub-phase A-prereq (blocks all type work downstream). OCC work (new CAS method + retry loop) ships in sub-phase E (patch engine) — no A-prereq work required for OCC because the underlying column + bump already ship in v7 (R2.5 discovery). Both are preconditions for correctness, not features. Refusing MBC widen would make the modeling-studio emit flow silently drop valid `"relative"` valuations; refusing OCC CAS would leave the patch engine racy against every concurrent write.

**Historical note**: R2.1-R2.3 attempted to solve the row-safety problem by retrofitting `_handoff_lock` across shipped writers. That path hit re-entrancy deadlock, lock-order inversion, and exemption-soundness issues across 5 Codex rounds before R2.4 pivoted to OCC. See §16 change log for the full trail.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| **A-prereq** | **MBC method widen** | Widen `ValuationMethod` alias in `schema/model_build_context.py:21` to accept `"relative"` (or `str \| None`); update MBC validator tests. **OCC does NOT require A-prereq work** — `theses.version` column + `_persist_thesis_payload` version bump already shipped in v7 (R2.5 discovery). Patch engine owns its own CAS method in sub-phase E. | ~0.25 day | — |
| A | `ModelInsights` + nested types Pydantic contracts | `schema/_insights_shared.py` (new — `_FROZEN_CONTRACT`, `Severity`, `Confidence`, `DriverCategory` to break cycle) + `schema/model_insights.py`; nested types for `DriverSensitivity`, `ImpliedAssumption`, `RiskSurfaced`; forward-ref to `HandoffPatchOp` resolved post-import | ~1 day | A-prereq |
| B | `PriceTarget` Pydantic contract | `schema/price_target.py`; `method: str \| None` (Q3); `price_target_id` UUIDv5 namespace `(research_file_id, handoff_id)` — stable across scenario upserts | ~0.5 day | A |
| C | `HandoffPatchOp` discriminated-union grammar | `schema/handoff_patch.py`; **all 21 concrete op classes (20 logical ops)** + `HandoffPatchBatch`; per-field typed `ReplaceThesis*` ops (int for conviction) | ~2 days | A (imports `_insights_shared` only) |
| D | Storage + service layer | Migration v8 + `model_insights_service.py`; **no FK on `model_build_context_id`** (snapshot retention, §3.3); upsert uses `(research_file_id, handoff_id)`-pinned PT id | ~1.5 days | A, B, C |
| E | Patch application engine | `api/research/patch_engine.py`; **dry-fold pre-validation** (§3.4) — builds virtual Thesis incrementally so `add_X + update_X` in same batch is legal; applies whole-Thesis replace via new `repo.update_thesis_artifact_if_version_matches` (OCC CAS, §1.2); bounded 3-attempt retry on `PatchStaleError`; HandoffArtifact re-derives via plan #2 shared-slice; NO `_handoff_lock` acquisition | ~2 days | C |
| F | Modeling-studio integration | AI-excel-addin `BuildModelOrchestrator.build_and_annotate` emit hook (non-critical); scenario refresh preserves `price_target_id`; producer-side UUIDv5 helper for `Add*Value` payloads | ~1.5 days | A, B, C, D |
| G | risk_module MCP surface | 4 MCP tools + 6 agent flags + typed-error extension to **`services/research_gateway.py`** `_THESIS_ERROR_TYPES` map (§10.4) | ~1.5 days | A-F |
| H | E2E + skill integration | 10 scenarios in §11.1; skill integration: `/thesis-review`, `/thesis-pre-mortem`, `/position-initiation` | ~1 day | A-G |
| I | Docs | `SKILL_CONTRACT_MAP.md` updates; master plan §12 SHIPPED mark | ~0.5 day | H |

**Total estimate**: ~11.75 days (A-prereq is 0.25 day for MBC method widen only; OCC work folds into sub-phase E as one new repository method + retry loop in the patch engine).

### 2.1 Dependency graph

```
                                A-prereq (MBC method widen)
                                              │
         ┌────────────────────────────────────┼────────────────────────────────┐
         ▼                                    ▼                                 ▼
  A (ModelInsights + _insights_shared)  B (PriceTarget)         C (HandoffPatchOp — imports _insights_shared only)
             │                                │                                 │
             └──────────────┬─────────────────┘                                │
                            ▼                                                   │
                         D (storage — no MBC FK)                                │
                            │                                                   │
                            ├───────────────────────────────────────────────────┤
                            ▼                                                   ▼
                         F (studio emit hook)                             E (patch engine — dry-fold)
                            │                                                   │
                            └─────────────────┬────────────────────────────────┘
                                              ▼
                                          G (MCP surface — research_gateway.py classifier)
                                              │
                                              ▼
                                          H (E2E + skills)
                                              │
                                              ▼
                                          I (docs)
```

---

## 3. Cross-cutting concerns

[To fill — candidate sections per plan #5 pattern]

### 3.1 Scope fences
- Stable-ID targeting only (no index-based) — R4 decision from §6.4
- Patches target the Thesis (SoT) for shared-slice fields; HandoffArtifact snapshots re-derive automatically — R5 decision
- `PriceTarget.method` and `valuation.method` unified per §6.4 R3 (single str field or single enum)

### 3.2 `model_insights_id` identity

Deterministic UUIDv5 derived from `(model_build_context_id, generated_at_iso)` namespace. Guarantees:
- Unique per build emission (new build → new ID even if MBC unchanged, because `generated_at` differs)
- Deterministic (replayable in tests; no hidden server clock state)
- Stable across processes (namespace-scoped; not a per-process nonce)

Same convention as plan #2 `scorecard_ref` / plan #3 `model_build_context_id`.

### 3.3 Storage model — new `model_insights` table (Q1+Q2 resolved, Blocker 5 resolved)

New SQLite table `model_insights` (migration v8). Rows are **snapshots** — persist on `build_model` emission, never regenerated.

**Schema**:
- `model_insights_id` PK (UUIDv5 per §3.2)
- `research_file_id` FK → `research_files(id)` ON DELETE CASCADE
- `handoff_id` FK → `research_handoffs(id)` ON DELETE CASCADE
- `model_build_context_id` TEXT **— NO FK** (see Blocker 5 resolution below)
- `generated_at` ISO8601 (frozen at build time)
- `schema_version` str (= "1.0")
- `insights_json` (serialized `ModelInsights` Pydantic, frozen)

**Blocker 5 resolution — MBC linkage is TEXT provenance, not FK**: shipped `model_build_contexts` lifecycle includes `delete_mbc()` + `delete_expired_mbcs()` (`repository.py:2622`). A hard FK would break those lifecycle paths; `ON DELETE CASCADE` would violate the snapshot rule (Q2: MI must survive MBC pruning). Keeping `model_build_context_id` as plain TEXT with no FK preserves both:
- MBC cleanup runs unchanged — no constraint errors
- MI rows survive as frozen snapshots even when MBC is pruned
- Reference is provenance-only — analyst can still follow it, may find MBC pruned (MCP response exposes `flags.mbc_pruned` in §10.3 so agents surface this gracefully)

**PriceTarget storage**: separate `price_targets` table — see §7.2 schema. Unique index on `handoff_id` (one PT per handoff per Q5). `price_target_id` UUIDv5 namespace is `(research_file_id, handoff_id)` — stable by construction across scenario upserts (Blocker 3 resolution; superseded §7.2's earlier `first_as_of` scheme which drifted).

**Cardinality**: many-to-one with `research_file_id`. One row per build (base model + each scenario run emits its own row). Retention: keep all; analyst reviews build history.

**Why not JSON-on-existing**: Q5 resolves to one composite PriceTarget but many ModelInsights per handoff (base + scenarios). JSON-column cramps the 1-to-N shape + makes scenario replay awkward.

**Why not ephemeral**: Q2 snapshot decision — orchestrator `suggests_patch` heuristics may drift between build invocations; replay from MBC would not match original.

### 3.4 Patch-apply semantics (Q4+Q6 resolved, Blocker 4 resolved)

**Blocker 4 resolution — dry-fold pre-validation**: Codex R1 surfaced that the R0.2 design's "pre-validation flags any stable_id reuse as duplicate" was incompatible with Q4's "later ops reference earlier-added ids." R2 replaces per-op-stateless pre-validation with **dry-fold validation**: walk the ops in order, maintaining a *virtual Thesis* that starts equal to the real SoT and absorbs each op's effect incrementally. Each op is validated against the virtual-Thesis state at its position — so an `add_X(id=a1)` at position 0 legalizes `update_X(id=a1)` at position 1.

**Ordering**: batch ops execute in list order. Dry-fold runs in the same order — position matters.

**Stable-ID pre-assignment** (Q4): `add_*` ops (`add_assumption`, `add_risk`, `add_catalyst`, `add_invalidation_trigger`, `add_differentiated_view_claim`) require the client to include the target stable_id in the op payload. Convention: UUIDv5 deterministic from content (driver_key/description + reason+rationale). Modeling-studio producer generates these at `ModelInsights` emit time (sub-phase F). Benefit: no apply-time round-trip, batch is idempotent on replay, dry-run preview matches apply.

**Transactionality (R2.4 — OCC, not _handoff_lock)**: full batch is all-or-nothing. Patch engine reads the current thesis row (including `version`) at dry-fold time, does the fold in-memory, writes `UPDATE theses SET ..., version = version + 1 WHERE thesis_id = ? AND version = $read_version`. Zero rows affected → `PatchStaleError` → retry dry-fold from fresh state (bounded 3 attempts). Per-op failure during fold → full rollback in-memory (nothing is written), typed error, no retry. No `_handoff_lock` acquisition — OCC on the row is the sole coordination mechanism. SQLite's `BEGIN IMMEDIATE` still provides storage-layer atomicity inside the repository write.

**Conflict detection rules** (Q6, updated per Blocker 4):

| Sequence in same batch | Verdict |
|---|---|
| `add_X(a1)` + `add_X(a1)` | **conflict** — can't add same id twice |
| `add_X(a1)` + `update_X(a1)` | **legal** — update applies to just-added (dry-fold) |
| `add_X(a1)` + `remove_X(a1)` | **legal** — weird but explicit; ops cancel to no-op |
| `update_X(a1, v=1)` + `update_X(a1, v=2)` (different values) | **conflict** — divergent end-state ambiguity |
| `update_X(a1, v=1)` + `update_X(a1, v=1)` (same value) | **legal** — redundant but idempotent |
| `update_X(a1)` + `remove_X(a1)` | **legal** — remove supersedes update |
| `remove_X(a1)` + `any_X(a1)` | **conflict** — target gone mid-batch |

Pre-validation **runs dry-fold to termination**: if the fold raises (target missing, field validator fails on virtual intermediate state, etc.) → the raising op's `op_id` is surfaced in `PatchBatchConflictError.conflicts[].op_ids`. No "last wins" fallback — all errors are explicit.

**Dry-run vs apply modes**: `preview_patch_ops(ops)` returns the diff + validation errors without touching the DB (reads version; does not CAS). `apply_patch_ops(ops, research_file_id)` runs same dry-fold, then writes via OCC CAS (`update_thesis_artifact_if_version_matches`). Stale CAS → bounded retry (§3.4). No per-op mutator methods on `ThesisService` are required (shipped `thesis_service.py` does not have them; R0.2 incorrectly assumed it did).

**Idempotency** (R2-revised for add_* ops):
- `add_X(a1, payload=P)` where `a1` already exists in real Thesis with identical `P` → idempotent-replay (no-op, tag batch)
- `add_X(a1, payload=P)` where `a1` exists with **different** payload → `DuplicateStableIdError` (not idempotent — real conflict)
- `update_X` / `remove_X` / `replace_*`: per-op pre-check compares target state to op value, skips if already matching
- Batch-level: batch is idempotent-replay iff every op is individually idempotent against the real Thesis

**Audit trail**: `research_file_history` entries with `event_type='patch_applied'`, payload = `{op_count, op_types, batch_hash, idempotent_replay}`. Individual op diffs are replay-derivable from MBC + insight snapshot, so not stored inline.

### 3.5 HandoffPatchOp validation
- Per-op target_id must exist in Thesis at apply time (else hard-fail with typed error)
- Per-op value shape must match op's schema (discriminated union)
- Batching semantics: apply as a single transaction or per-op?

### 3.6 Cross-plan alignment
- Plan #1 (Thesis): patches write to Thesis; HandoffArtifact re-derives via shared-slice. No Thesis schema changes. All 5 stable-ID fields (`claim_id`, `trigger_id`, `catalyst_id`, `risk_id`, `assumption_id`) already exist on `schema/thesis_shared_slice.py` as `str | None` — plan #6 depends on them but does not modify them. **`ThesisField.conviction` is `int | None`** (at `thesis_shared_slice.py:94`) — per-field typed `replace_thesis_*` op classes distinguish int vs str values (see §6.2).
- Plan #2 (HandoffArtifact): `scorecard_ref` field (already shipped) now has a typed consumer via PriceTarget. `HandoffModelRef.last_price_target: float | None` already shipped at `handoff.py:91` — plan #6 service mirrors PT mid into it on each upsert.
- Plan #3 (ModelBuildContext): ModelInsights references `model_build_context_id` as **plain TEXT** (no FK — Blocker 5 resolution, §3.3). Plan #6 widens MBC's `ValuationMethod` Literal to include `"relative"` (or `str | None`, §1.2 scope addition) — resolves Blocker 6 where shipped MBC rejected the live `"relative"` value propagating from handoff.
- Plan #5 (ProcessTemplate): template's `valuation_methods_allowed` gate applies at **finalize time only** (already shipped in `_assemble_artifact_locked`). Patch apply does NOT re-check the gate — by construction patches write free-form strings; the finalize gate is the sole enforcement point. Consistent with plan #5's design. `_handoff_lock` remains exclusively for handoff-lifecycle coordination (plan #2/#5 state machines) — patch engine does **not** acquire it. OCC (§1.2) covers row-level safety instead.
- **§6.4 R3 supersession (Q3 resolved)** — R2 full propagation: master plan §6.4 R3 proposed unifying `PriceTarget.method` as `Literal[dcf | multiples | sum_of_parts | hybrid]` with `valuation.method`. Plan #5 shipped `Valuation.method: str | None` free-form because `prepopulate.py:323` emits `"relative"` as a live method string (not in the R3 proposed enum) and default templates include `"relative"` in `valuation_methods_allowed`. Plan #6 follows suit: **`PriceTarget.method` is `str | None` (non-empty when set), not a Literal**. Tightening to a Literal would diverge from `Valuation.method` and break the "shared method" intent. Template gate remains the sole subset enforcer. **MBC's Literal is widened** (§1.2 scope addition) so `"relative"` flows end-to-end (`Valuation → MBC.valuation → PriceTarget`). Master plan §6.4 R3 updated with this revision note in sub-phase I docs.

---

## 4. Sub-phase A — `ModelInsights` Pydantic type + validators

### 4.1 Goal

Pydantic v2 `ModelInsights` + 4 nested types in `AI-excel-addin/schema/model_insights.py` using plan #5's `_ContractModel` base (frozen, `extra="forbid"`, `str_strip_whitespace`, `populate_by_name`). Identity via deterministic UUIDv5 per §3.2.

### 4.2 Design

Top-level shape from master plan §6.4 lines 466-487; nested types match the dict entries shown there.

**Blocker 2 resolution — imports + shared module**: R0.2 incorrectly named `from ._shared_slice import SourceId` and `from .enum_canonicalizers import canonicalize_optional_confidence` — neither export exists. Verified locations (R2):
- `SourceId` lives at `schema/thesis_shared_slice.py:21` (not `_shared_slice`)
- No `canonicalize_optional_confidence` helper exists — use a plain Literal + `field_validator(mode="before")` to lowercase

R2 also introduces `schema/_insights_shared.py` to host types shared by both `model_insights.py` and `handoff_patch.py`. Without this split, the two modules cycle — `handoff_patch.py` needs `Severity/Confidence/DriverCategory/_FROZEN_CONTRACT` and `model_insights.py` needs `HandoffPatchOp`. With the split, `handoff_patch.py` imports only from `_insights_shared.py`, and `model_insights.py` imports both.

```python
# schema/_insights_shared.py  (NEW — Blocker 2 resolution)
from __future__ import annotations
from typing import Literal
from pydantic import ConfigDict

_FROZEN_CONTRACT = ConfigDict(
    extra="forbid",
    str_strip_whitespace=True,
    populate_by_name=True,
    frozen=True,
)

Severity = Literal["low", "medium", "high"]
Confidence = Literal["low", "medium", "high"]
DriverCategory = Literal[
    "revenue", "unit_economics", "cost_structure",
    "reinvestment", "capital_sources", "valuation", "other",
]
DriverUnit = Literal[
    "dollars", "percentage", "ratio", "count", "per_share", "days", "multiple",
]
```

```python
# schema/model_insights.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator

from .thesis_shared_slice import SourceId          # actual location
from ._insights_shared import (
    _FROZEN_CONTRACT, Severity, Confidence, DriverCategory, DriverUnit,
)
from .handoff_patch import HandoffPatchOp          # forward dep OK — handoff_patch does NOT re-import this module


class ModelVersionRef(BaseModel):
    """Composite version ref shared by ModelInsights.model_ref + PriceTarget.model_ref.
    Matches §8 composite versioning rule; subset of HandoffModelRef (model_id + version only)."""
    model_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    model_config = _FROZEN_CONTRACT


class DriverSensitivity(BaseModel):
    driver_key: str = Field(min_length=1)           # same key space as MBC.drivers + assumptions[].driver
    target_metric: str = Field(min_length=1)         # e.g., "eps_2027", "ebitda_margin_2027"
    impact_per_unit: float                            # sensitivity coefficient: d(target)/d(driver)
    rank: int = Field(ge=1)                          # 1 = highest absolute impact
    periods: list[int] | None = None                 # None = applies to all projection years
    model_config = _FROZEN_CONTRACT


class ImpliedAssumption(BaseModel):
    """Assumption the model made explicit beyond what the handoff stated."""
    driver_key: str = Field(min_length=1)
    sia_category: DriverCategory | None = None
    value: float
    unit: DriverUnit                                 # shared Literal from _insights_shared
    rationale: str = Field(min_length=1)
    suggests_patch: bool = False                     # producer heuristic — true = emit HandoffPatchOp in handoff_patch_suggestions

    @field_validator("sia_category", mode="before")
    @classmethod
    def _canonicalize_sia(cls, v):
        """Lowercase + snake_case per plan #5 enum_canonicalizers pattern (no shared helper exists for this enum)."""
        if v is None: return None
        import re
        return re.sub(r"[\s\-_]+", "_", str(v).strip()).lower()

    model_config = _FROZEN_CONTRACT


class RiskSurfaced(BaseModel):
    """Risk the build process uncovered (not necessarily already in Thesis.risks)."""
    description: str = Field(min_length=1)
    severity: Severity
    type: str | None = None                          # free-form classification (e.g., "execution", "macro")
    evidence: list[SourceId] = Field(default_factory=list)   # src_* refs from handoff.sources
    model_config = _FROZEN_CONTRACT


class ModelInsights(BaseModel):
    model_insights_id: str = Field(min_length=1)     # UUIDv5 per §3.2
    model_ref: ModelVersionRef
    model_build_context_id: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)          # ISO8601 — frozen at build time (§3.3)

    driver_sensitivities: list[DriverSensitivity] = Field(default_factory=list)
    implied_assumptions: list[ImpliedAssumption] = Field(default_factory=list)
    risks_surfaced: list[RiskSurfaced] = Field(default_factory=list)
    handoff_patch_suggestions: list[HandoffPatchOp] = Field(default_factory=list)   # direct import from §6 (no forward-ref — Blocker 2)

    schema_version: Literal["1.0"] = "1.0"

    @field_validator("driver_sensitivities")
    @classmethod
    def _rank_is_dense_from_one(cls, v: list[DriverSensitivity]):
        """If ranks are emitted, they must be dense [1..N] with no gaps/duplicates."""
        if not v: return v
        ranks = sorted(s.rank for s in v)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f"driver_sensitivities.rank must be dense [1..{len(ranks)}]; got {ranks}")
        return v

    model_config = _FROZEN_CONTRACT
```

### 4.3 Files to create/modify

- **Create**: `AI-excel-addin/schema/_insights_shared.py` — `_FROZEN_CONTRACT`, `Severity`, `Confidence`, `DriverCategory`, `DriverUnit` (Blocker 2 split)
- **Create**: `AI-excel-addin/schema/model_insights.py` — types above
- **Modify**: `AI-excel-addin/schema/__init__.py` — re-export `ModelInsights`, `ModelVersionRef`, `DriverSensitivity`, `ImpliedAssumption`, `RiskSurfaced` (append to `__all__` + the typed exports block near line 327)
- **Create**: `AI-excel-addin/tests/schema/test_insights_shared.py` — enum values + import order
- **Create**: `AI-excel-addin/tests/schema/test_model_insights.py`

### 4.4 Tests

Mirror plan #5 `test_process_template.py` coverage pattern:

| Test | Coverage |
|---|---|
| `test_model_insights_minimal_valid` | Only required fields → constructs clean |
| `test_model_insights_full_roundtrip` | All nested types populated → `.model_dump_json()` → `.model_validate_json()` → equal |
| `test_frozen_contract` | Mutation attempt raises `ValidationError` |
| `test_extra_forbid` | Unknown field → `ValidationError` |
| `test_driver_sensitivities_dense_rank` | Gaps/duplicates in rank → `ValidationError` |
| `test_implied_assumption_sia_canonicalization` | `"Revenue"` → `"revenue"` (validator-mode before) |
| `test_risk_surfaced_severity_enum` | Non-enum severity → `ValidationError` |
| `test_evidence_source_id_format` | Invalid `src_*` ID → `ValidationError` (inherited from `SourceId` alias) |
| `test_model_version_ref_version_ge_1` | `version=0` → `ValidationError` |
| `test_generated_at_iso_format` | Non-ISO string accepted (no strict ISO validator at v1 — just non-empty); document as intentional |

**Boundary**: 1 test verifying the module's public surface matches `__all__` additions in `schema/__init__.py`.

**Import order tests** (Blocker 2 defense):
- `test_import_handoff_patch_first` — `from schema import handoff_patch` then `from schema import model_insights` works without `ImportError` (verifies `handoff_patch` does NOT back-reference `model_insights`).
- `test_import_model_insights_first` — reverse order also works.
- `test_both_modules_import_insights_shared` — both modules can import `_insights_shared` without cycle.

---

## 5. Sub-phase B — `PriceTarget` Pydantic type + validators

### 5.1 Goal

Pydantic v2 `PriceTarget` in `AI-excel-addin/schema/price_target.py`.

**Resolved design constraints** (per §15 R0.1 + R2 refinements):
- **Cardinality (Q5)**: composite — one `PriceTarget` per handoff, `ranges: {low, mid, high}` aggregates bull/base/bear scenarios. Scenario runs update the existing row in place (not new rows).
- **Method field (Q3)**: `method: str | None` with non-empty validator when set — **NOT** a Literal. Superseded §6.4 R3's proposed `Literal[dcf|multiples|sum_of_parts|hybrid]` to stay aligned with live `Valuation.method: str | None`. Template gate at finalize time (plan #5) is the sole subset enforcer.
- **Identity (Blocker 3 resolution)**: `price_target_id` — UUIDv5 from `(research_file_id, handoff_id)` → **stable by construction** across all scenario upserts on the same handoff. Service computes the id deterministically on every upsert; row key and payload id therefore cannot drift. R0.2's `first_as_of` scheme rejected because caller had to remember "first" across processes — race-prone; the handoff-scoped namespace is race-free.

### 5.2 Design

Shape from master plan §6.4 lines 580-590 with Q3+Q5 constraints applied.

```python
# schema/price_target.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from ._insights_shared import _FROZEN_CONTRACT, Confidence
from .model_insights import ModelVersionRef       # ModelVersionRef owned by model_insights — one-way import OK


class PriceTargetDriverSensitivity(BaseModel):
    """Price-target-specific sensitivity — differs from ModelInsights.DriverSensitivity
    because impact_per_unit → delta_per_pct (1pp shock in driver → $ change in PT)."""
    driver_key: str = Field(min_length=1)
    delta_per_pct: float                              # $ change in mid-point PT per 1pp driver move
    rank: int = Field(ge=1)
    model_config = _FROZEN_CONTRACT


class PriceTargetRanges(BaseModel):
    """Composite ranges aggregating bull/base/bear scenario outputs (Q5)."""
    low: float                                        # bear-case equivalent
    mid: float                                        # base-case equivalent
    high: float                                       # bull-case equivalent
    model_config = _FROZEN_CONTRACT

    @model_validator(mode="after")
    def _ordered(self):
        if not (self.low <= self.mid <= self.high):
            raise ValueError(f"ranges must satisfy low≤mid≤high; got ({self.low}, {self.mid}, {self.high})")
        return self


class PriceTarget(BaseModel):
    price_target_id: str = Field(min_length=1)       # UUIDv5 per §5.1 (research_file_id, handoff_id) — Blocker 3
    model_ref: ModelVersionRef
    as_of: str = Field(min_length=1)                 # ISO8601 — updated on each scenario refresh (composite in-place)

    ranges: PriceTargetRanges
    confidence: Confidence
    method: str | None = Field(default=None, min_length=1)   # Q3: free-form, NOT Literal; aligns with Valuation.method
    driver_sensitivities: list[PriceTargetDriverSensitivity] = Field(default_factory=list)

    time_horizon_months: int = Field(ge=1, le=120)   # 1 month to 10 years
    current_price: float = Field(gt=0)
    implied_return_pct: float                         # signed; derivable from mid/current-1 but stored for audit

    schema_version: Literal["1.0"] = "1.0"

    @field_validator("driver_sensitivities")
    @classmethod
    def _rank_dense(cls, v):
        """Same dense-rank invariant as ModelInsights.driver_sensitivities."""
        if not v: return v
        ranks = sorted(s.rank for s in v)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f"driver_sensitivities.rank must be dense [1..{len(ranks)}]")
        return v

    model_config = _FROZEN_CONTRACT
```

**Cardinality note** (Q5): composite, one per handoff. Scenario runs update `as_of` + `ranges` + `driver_sensitivities` in place (not new rows). `price_target_id` is stable by construction because the UUIDv5 namespace is `(research_file_id, handoff_id)` — every upsert recomputes the same id (R2 Blocker 3 fix). Sub-phase D pins the storage semantics.

**Alignment with HandoffArtifact**: `HandoffModelRef.last_price_target: float | None` (already shipped at `handoff.py:91`) is set to the current `PriceTarget.ranges.mid` on each scenario update — this is how the Handoff surface sees the latest PT without duplicating the full record.

### 5.3 Files to create/modify

- **Create**: `AI-excel-addin/schema/price_target.py` — types above
- **Modify**: `AI-excel-addin/schema/__init__.py` — re-export `PriceTarget`, `PriceTargetRanges`, `PriceTargetDriverSensitivity`
- **Create**: `AI-excel-addin/tests/schema/test_price_target.py`

### 5.4 Tests

| Test | Coverage |
|---|---|
| `test_price_target_minimal_valid` | Required fields only → constructs |
| `test_roundtrip_json` | Full payload → dump → parse → equal |
| `test_ranges_ordering_enforced` | `low > mid` → `ValidationError` |
| `test_method_free_form_accepts_relative` | `method="relative"` accepts (Q3 supersedes R3 Literal) |
| `test_method_rejects_empty_string` | `method=""` → `ValidationError` (min_length=1) |
| `test_method_none_allowed` | `method=None` → accepts (aligns with `Valuation.method: str \| None`) |
| `test_current_price_positive` | `current_price=0` or negative → `ValidationError` |
| `test_time_horizon_bounds` | `time_horizon_months=0` or `>120` → `ValidationError` |
| `test_driver_sensitivities_dense_rank` | Gaps/duplicates → `ValidationError` |
| `test_frozen` | Mutation raises |
| `test_extra_forbid` | Unknown field raises |

---

## 6. Sub-phase C — `HandoffPatchOp` discriminated-union grammar

### 6.1 Goal

Pydantic v2 discriminated-union type for model→Thesis feedback ops. All ~20 ops enumerated in §6.4 — CRUD on assumptions, thesis headline fields, quantitative framing, valuation, consensus/differentiated view, risks, catalysts, invalidation triggers.

### 6.2 Design

20 ops across 8 categories (per §6.4 lines 489-578). Pydantic v2 discriminated union via `Field(discriminator="op")`. All ops share a base envelope (`op_id`, `reason`). `target` shape + `value` shape vary per op.

**Q4 convention — client-pre-assigned stable IDs**: all `add_*` ops embed the new stable_id directly in the `value` payload (not generated on apply). Producer (modeling studio, §9) computes UUIDv5 from content (e.g., `assumption_id = uuid5(ns_driver, driver_key + value + rationale)`) — deterministic, idempotent on replay, later ops in the same batch can reference the ID before it's applied.

**Op category map** (20 total):

| Category | Count | Ops |
|---|---|---|
| Assumptions | 4 | `replace_assumption_value`, `update_assumption_field`, `add_assumption`, `remove_assumption` |
| Thesis headline | 1 | `replace_thesis_field` |
| Thesis quantitative | 1 | `update_thesis_quantitative` |
| Valuation (shared slice) | 1 | `update_valuation` |
| Consensus view | 1 | `update_consensus_view` |
| Differentiated view claims | 3 | `add_differentiated_view_claim`, `update_differentiated_view_claim`, `remove_differentiated_view_claim` |
| Risks | 3 | `add_risk`, `update_risk`, `remove_risk` |
| Catalysts | 3 | `add_catalyst`, `update_catalyst`, `remove_catalyst` |
| Invalidation triggers | 3 | `add_invalidation_trigger`, `update_invalidation_trigger`, `remove_invalidation_trigger` |

**Code sketch — R2 complete enumeration** (all 20 logical ops / 21 concrete classes fully typed; Blocker 1 resolved):

```python
# schema/handoff_patch.py
from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from .thesis_shared_slice import SourceId        # actual location (Blocker 2)
from ._insights_shared import (
    _FROZEN_CONTRACT, Severity, Confidence, DriverCategory, DriverUnit,
)
# NOTE: NO import from .model_insights — breaks cycle (Blocker 2 resolution)


# ─── Envelope mixin ─────────────────────────────────────────────────────────

class _PatchOpBase(BaseModel):
    """Common envelope: op_id (batch-unique) + reason (audit trail)."""
    op_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    model_config = _FROZEN_CONTRACT


# ─── Targets (discriminated by op, not a union themselves) ──────────────────

class AssumptionTarget(BaseModel):
    assumption_id: str = Field(min_length=1)
    model_config = _FROZEN_CONTRACT

class AssumptionFieldTarget(BaseModel):
    assumption_id: str = Field(min_length=1)
    field: Literal["rationale", "confidence", "unit", "driver_category"]
    model_config = _FROZEN_CONTRACT

class ThesisFieldTargetStr(BaseModel):
    """Target for string-typed Thesis fields (per shipped ThesisField at thesis_shared_slice.py:90-95).
    `statement: str | None`, `direction: DirectionValue | None`, `strategy: StrategyValue | None`, `timeframe: TimeframeValue | None`."""
    field: Literal["statement", "direction", "strategy", "timeframe"]
    model_config = _FROZEN_CONTRACT

class ThesisFieldTargetInt(BaseModel):
    """Target for int-typed Thesis fields. `conviction: int | None` (shipped as int). Blocker 1 fix."""
    field: Literal["conviction"]
    model_config = _FROZEN_CONTRACT

class ThesisQuantitativeTarget(BaseModel):
    section: Literal[
        "revenue", "margins", "eps_fcf",
        "scenarios.bull", "scenarios.base", "scenarios.bear",
    ]
    field: str = Field(min_length=1)      # free-form sub-field (e.g., "base", "target_price", "return_pct")
    model_config = _FROZEN_CONTRACT

class ValuationTarget(BaseModel):
    field: Literal["low", "mid", "high", "method", "current_multiple", "rationale"]
    model_config = _FROZEN_CONTRACT

class StableIdTarget(BaseModel):
    """Reusable for risk_id / catalyst_id / trigger_id / claim_id."""
    id: str = Field(min_length=1)
    model_config = _FROZEN_CONTRACT


# ─── Value payloads for add_* ops (stable_id pre-assigned — Q4) ─────────────

class AddAssumptionValue(BaseModel):
    assumption_id: str = Field(min_length=1)         # Q4 — client pre-assigns
    driver: str = Field(min_length=1)
    value: float
    unit: Literal["dollars", "percentage", "ratio", "count", "per_share", "days", "multiple"]
    rationale: str = Field(min_length=1)
    source_refs: list[SourceId] = Field(default_factory=list)
    driver_category: DriverCategory | None = None
    confidence: Confidence | None = None
    model_config = _FROZEN_CONTRACT

class AddRiskValue(BaseModel):
    risk_id: str = Field(min_length=1)               # Q4 — client pre-assigns
    description: str = Field(min_length=1)
    severity: Severity
    type: str | None = None
    model_config = _FROZEN_CONTRACT

class AddCatalystValue(BaseModel):
    catalyst_id: str = Field(min_length=1)           # Q4
    description: str = Field(min_length=1)
    expected_date: str | None = None                 # ISO8601
    severity: Severity
    model_config = _FROZEN_CONTRACT

class AddTriggerValue(BaseModel):
    trigger_id: str = Field(min_length=1)            # Q4
    description: str = Field(min_length=1)
    metric: str | None = None
    threshold: float | None = None
    direction: Literal["above", "below"] | None = None
    model_config = _FROZEN_CONTRACT

class AddClaimValue(BaseModel):
    claim_id: str = Field(min_length=1)              # Q4
    claim: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence: list[SourceId] = Field(min_length=1)   # differentiated view REQUIRES evidence
    upside_if_right: str | None = None
    downside_if_wrong: str | None = None
    model_config = _FROZEN_CONTRACT


# ─── Per-op classes (discriminator = op) ────────────────────────────────────
# 20 total — showing representative ops across all 8 categories. Sub-phase C
# implementation fills the remaining ops in the same pattern.

# Assumptions (4)
class ReplaceAssumptionValueOp(_PatchOpBase):
    op: Literal["replace_assumption_value"] = "replace_assumption_value"
    target: AssumptionTarget
    value: float

class UpdateAssumptionFieldOp(_PatchOpBase):
    op: Literal["update_assumption_field"] = "update_assumption_field"
    target: AssumptionFieldTarget
    value: str | float | Confidence                  # typed-by-field at model_validator(mode="after")

    @model_validator(mode="after")
    def _value_matches_field(self):
        f = self.target.field
        if f == "confidence" and self.value not in ("low", "medium", "high"):
            raise ValueError("confidence must be one of low/medium/high")
        if f in ("rationale", "unit", "driver_category") and not isinstance(self.value, str):
            raise ValueError(f"{f} requires str value")
        return self

class AddAssumptionOp(_PatchOpBase):
    op: Literal["add_assumption"] = "add_assumption"
    target: None = None                              # add_* ops have no target
    value: AddAssumptionValue

class RemoveAssumptionOp(_PatchOpBase):
    op: Literal["remove_assumption"] = "remove_assumption"
    target: AssumptionTarget
    value: None = None                               # remove_* ops have no value

# Thesis headline (1 logical op, 2 concrete classes per Blocker 1 — type-split on value)
class ReplaceThesisFieldStrOp(_PatchOpBase):
    """statement / direction / strategy / timeframe — str | None; direction/strategy/timeframe
    canonicalized on write by shipped Thesis validators (no extra validation here)."""
    op: Literal["replace_thesis_field_str"] = "replace_thesis_field_str"
    target: ThesisFieldTargetStr
    value: str | None = Field(default=None, min_length=1)   # None = explicit clear

class ReplaceThesisFieldIntOp(_PatchOpBase):
    """conviction — int | None. Blocker 1 fix: R0.2 rejected valid int input because value: str."""
    op: Literal["replace_thesis_field_int"] = "replace_thesis_field_int"
    target: ThesisFieldTargetInt
    value: int | None = None                              # None = explicit clear

# Thesis quantitative (1)
class UpdateThesisQuantitativeOp(_PatchOpBase):
    op: Literal["update_thesis_quantitative"] = "update_thesis_quantitative"
    target: ThesisQuantitativeTarget
    value: float | str                               # varies: target_price=float, rationale=str

# Valuation shared slice (1)
class UpdateValuationOp(_PatchOpBase):
    op: Literal["update_valuation"] = "update_valuation"
    target: ValuationTarget
    value: float | str                               # low/mid/high=float, method/rationale=str

# Consensus view (1) — typed payload, NOT bare dict (R2 Blocker 1 completion)
class UpdateConsensusViewOp(_PatchOpBase):
    op: Literal["update_consensus_view"] = "update_consensus_view"
    target: None = None
    value: "UpdateConsensusViewValue"                # defined below; forward-ref within same module OK

# Differentiated view (3)
class AddDifferentiatedViewClaimOp(_PatchOpBase):
    op: Literal["add_differentiated_view_claim"] = "add_differentiated_view_claim"
    target: None = None
    value: AddClaimValue

class UpdateDifferentiatedViewClaimOp(_PatchOpBase):
    op: Literal["update_differentiated_view_claim"] = "update_differentiated_view_claim"
    target: StableIdTarget                           # target.id = claim_id
    value: "UpdateClaimValue"                        # defined below; forward-ref within same module OK (R2 Blocker 1)

class RemoveDifferentiatedViewClaimOp(_PatchOpBase):
    op: Literal["remove_differentiated_view_claim"] = "remove_differentiated_view_claim"
    target: StableIdTarget
    value: None = None

# Risks (3) — R2 complete per Blocker 1
class UpdateRiskValue(BaseModel):
    """Partial update — all fields optional; None means no-change."""
    description: str | None = Field(default=None, min_length=1)
    severity: Severity | None = None
    type: str | None = None
    model_config = _FROZEN_CONTRACT

class AddRiskOp(_PatchOpBase):
    op: Literal["add_risk"] = "add_risk"
    target: None = None
    value: AddRiskValue

class UpdateRiskOp(_PatchOpBase):
    op: Literal["update_risk"] = "update_risk"
    target: StableIdTarget                           # target.id = risk_id
    value: UpdateRiskValue

class RemoveRiskOp(_PatchOpBase):
    op: Literal["remove_risk"] = "remove_risk"
    target: StableIdTarget
    value: None = None

# Catalysts (3) — R2 complete
class UpdateCatalystValue(BaseModel):
    description: str | None = Field(default=None, min_length=1)
    expected_date: str | None = None
    severity: Severity | None = None
    model_config = _FROZEN_CONTRACT

class AddCatalystOp(_PatchOpBase):
    op: Literal["add_catalyst"] = "add_catalyst"
    target: None = None
    value: AddCatalystValue

class UpdateCatalystOp(_PatchOpBase):
    op: Literal["update_catalyst"] = "update_catalyst"
    target: StableIdTarget                           # target.id = catalyst_id
    value: UpdateCatalystValue

class RemoveCatalystOp(_PatchOpBase):
    op: Literal["remove_catalyst"] = "remove_catalyst"
    target: StableIdTarget
    value: None = None

# Invalidation triggers (3) — R2 complete
class UpdateTriggerValue(BaseModel):
    description: str | None = Field(default=None, min_length=1)
    metric: str | None = None
    threshold: float | None = None
    direction: Literal["above", "below"] | None = None
    model_config = _FROZEN_CONTRACT

class AddInvalidationTriggerOp(_PatchOpBase):
    op: Literal["add_invalidation_trigger"] = "add_invalidation_trigger"
    target: None = None
    value: AddTriggerValue

class UpdateInvalidationTriggerOp(_PatchOpBase):
    op: Literal["update_invalidation_trigger"] = "update_invalidation_trigger"
    target: StableIdTarget                           # target.id = trigger_id
    value: UpdateTriggerValue

class RemoveInvalidationTriggerOp(_PatchOpBase):
    op: Literal["remove_invalidation_trigger"] = "remove_invalidation_trigger"
    target: StableIdTarget
    value: None = None

# Differentiated view claims — typed update payload (R2 replaces bare dict)
class UpdateClaimValue(BaseModel):
    claim: str | None = Field(default=None, min_length=1)
    rationale: str | None = Field(default=None, min_length=1)
    evidence: list[SourceId] | None = None            # None = no-change; [] = clear
    upside_if_right: str | None = None
    downside_if_wrong: str | None = None
    model_config = _FROZEN_CONTRACT

# UpdateDifferentiatedViewClaimOp.value is refactored to use UpdateClaimValue (above, replaces bare dict)

# Consensus view — typed payload (R2 replaces bare dict)
class UpdateConsensusViewValue(BaseModel):
    narrative: str | None = None
    citations: list[SourceId] | None = None
    model_config = _FROZEN_CONTRACT
# UpdateConsensusViewOp.value is refactored to use UpdateConsensusViewValue


# ─── Discriminated union — all 20 logical ops / 21 concrete classes (Blocker 1 resolved) ─────────────────

HandoffPatchOp = Annotated[
    Union[
        # Assumptions (4)
        ReplaceAssumptionValueOp, UpdateAssumptionFieldOp, AddAssumptionOp, RemoveAssumptionOp,
        # Thesis headline (2 classes, 1 logical op — type-split on value per Blocker 1)
        ReplaceThesisFieldStrOp, ReplaceThesisFieldIntOp,
        # Thesis quantitative (1)
        UpdateThesisQuantitativeOp,
        # Valuation shared slice (1)
        UpdateValuationOp,
        # Consensus view (1)
        UpdateConsensusViewOp,
        # Differentiated view (3)
        AddDifferentiatedViewClaimOp, UpdateDifferentiatedViewClaimOp, RemoveDifferentiatedViewClaimOp,
        # Risks (3)
        AddRiskOp, UpdateRiskOp, RemoveRiskOp,
        # Catalysts (3)
        AddCatalystOp, UpdateCatalystOp, RemoveCatalystOp,
        # Invalidation triggers (3)
        AddInvalidationTriggerOp, UpdateInvalidationTriggerOp, RemoveInvalidationTriggerOp,
    ],
    Field(discriminator="op"),
]
# 4 + 2 + 1 + 1 + 1 + 3 + 3 + 3 + 3 = 21 concrete classes (20 logical ops; "replace_thesis_field" has 2 classes)


class HandoffPatchBatch(BaseModel):
    """Batch wrapper — used by preview_patch_ops / apply_patch_ops APIs + ModelInsights.handoff_patch_suggestions."""
    ops: list[HandoffPatchOp] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_op_ids(self):
        """op_id must be unique within the batch (required for dry-run diff + audit payload)."""
        ids = [op.op_id for op in self.ops]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"op_ids must be unique within batch; duplicates: {dupes}")
        return self

    model_config = _FROZEN_CONTRACT
```

**Why a `HandoffPatchBatch` wrapper** (beyond §6.4 shape): batch-level invariants (unique `op_id`, Q6 conflict detection in §3.4) need a validation site. Bare `list[HandoffPatchOp]` can't carry model_validators. `ModelInsights.handoff_patch_suggestions` uses `list[HandoffPatchOp]` (a producer hint, no batch semantics); `preview_patch_ops` / `apply_patch_ops` APIs accept `HandoffPatchBatch` (consumer site where Q6 applies).

**Handoff-only fields deferred** (per §6.4 R5): ops for `idea_provenance`, `assumption_lineage`, `process_template_id` are NOT in plan #6 — follow-on plans. Rarely written by model feedback; explicit out-of-scope per §1.1.

### 6.3 Files to create/modify

- **Create**: `AI-excel-addin/schema/handoff_patch.py` — ops + batch wrapper
- **Modify**: `AI-excel-addin/schema/__init__.py` — re-export `HandoffPatchOp`, `HandoffPatchBatch`, all 21 concrete op classes (or a `HandoffPatchOps` namespace)
- **Create**: `AI-excel-addin/tests/schema/test_handoff_patch.py`
- **No forward-ref `model_rebuild()` needed** (R2 Blocker 2): direct one-way import works because `handoff_patch.py` no longer imports from `model_insights.py`.

### 6.4 Tests

| Test | Coverage |
|---|---|
| `test_discriminator_rejects_unknown_op` | `{"op": "nonsense", ...}` → `ValidationError` (union discriminator rejects) |
| `test_each_op_roundtrips_independently` | Parametrized over all 21 concrete op classes (20 logical ops; `replace_thesis_field_str` + `_int` are 2 classes) — dump → parse → equal |
| `test_add_ops_require_pre_assigned_id` | `AddAssumptionOp.value` missing `assumption_id` → `ValidationError` (Q4 invariant) |
| `test_remove_ops_reject_value` | `RemoveAssumptionOp(value="anything")` → `ValidationError` (`value: None = None`) |
| `test_add_ops_reject_target` | `AddAssumptionOp(target={"assumption_id": "a1"})` → `ValidationError` (`target: None = None`) |
| `test_update_assumption_field_value_matches_field` | `field="confidence"` + `value=3.14` → `ValidationError` |
| `test_differentiated_view_claim_requires_evidence` | `AddClaimValue` with `evidence=[]` → `ValidationError` (`min_length=1`) |
| `test_thesis_quantitative_section_enum` | Invalid section string → `ValidationError` |
| `test_valuation_field_enum` | Invalid field literal → `ValidationError` |
| `test_batch_unique_op_ids` | Two ops with same `op_id` in batch → `ValidationError` |
| `test_batch_serialization_preserves_order` | Q4 invariant — round-trip preserves list order |
| `test_frozen_op` | Mutation on any op raises |
| `test_extra_forbid_on_op` | Unknown field in op raises |
| `test_union_parse_from_dict` | `HandoffPatchOp` TypeAdapter parses dicts → correct concrete class |

**Parametrization**: representative ops × "happy path" + "value type mismatch" + "target shape mismatch" = ~60 parametrized cases. Aim: every op class exercised at least twice (valid + one failure mode).

**Discriminator invariant**: `test_each_op_roundtrips_independently` uses `pydantic.TypeAdapter(HandoffPatchOp)` — verifies that parsing a plain dict with `op` discriminator produces the correct concrete class (not just works with the class passed directly).

---

## 7. Sub-phase D — Storage + service layer

### 7.1 Goal

Persist `ModelInsights` (many-per-handoff, snapshot) + `PriceTarget` (one-per-handoff, composite-updated-in-place) via a v8 SQLite migration. Provide `ModelInsightsService` + `PriceTargetService` mirroring plan #5's catalog/repository split.

### 7.2 Design

**Schema migration (v8)** — pattern mirrors v7 (`_create_process_template_storage`). v8 adds two new tables: `model_insights` and `price_targets`. OCC uses the **existing** `theses.version` column (shipped in v7, verified R2.5) — no schema change needed for OCC.

```python
# api/research/repository.py

CURRENT_SCHEMA_VERSION = 8   # was 7

# ── OCC note (§1.2) ───────────────────────────────────────────────────────
# theses.version column ALREADY EXISTS at v7 (repository.py:54,61,
# DEFAULT 1, NOT NULL). _persist_thesis_payload ALREADY bumps it on every
# write via increment_version=True default (repository.py:1302). The shipped
# Thesis Pydantic model ALREADY carries version: int = Field(default=1, ge=1)
# at schema/thesis.py:222. Plan #6 does NOT add/alter this column or its
# bumping behavior — it only introduces a new CAS method
# `update_thesis_artifact_if_version_matches` that the patch engine calls
# instead of `update_thesis_artifact`.

MODEL_INSIGHTS_STORAGE_SQL = """
CREATE TABLE IF NOT EXISTS model_insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_insights_id TEXT NOT NULL UNIQUE,          -- UUIDv5 (§3.2)
  research_file_id INTEGER NOT NULL
    REFERENCES research_files(id) ON DELETE CASCADE,
  handoff_id INTEGER NOT NULL
    REFERENCES research_handoffs(id) ON DELETE CASCADE,
  -- NO FK on model_build_context_id (Blocker 5): MBC has its own lifecycle
  -- (delete_mbc, delete_expired_mbcs at repository.py:2622). MI rows outlive MBC.
  model_build_context_id TEXT NOT NULL,            -- provenance only
  generated_at TEXT NOT NULL,                       -- ISO8601
  insights_json TEXT NOT NULL,                      -- serialized ModelInsights
  schema_version TEXT NOT NULL DEFAULT '1.0',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_insights_file
  ON model_insights(research_file_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_insights_handoff
  ON model_insights(handoff_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_insights_mbc
  ON model_insights(model_build_context_id);       -- non-unique; for "all MI for this MBC" queries
"""

PRICE_TARGET_STORAGE_SQL = """
CREATE TABLE IF NOT EXISTS price_targets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  price_target_id TEXT NOT NULL UNIQUE,             -- UUIDv5 (§5.1) stable across updates
  research_file_id INTEGER NOT NULL
    REFERENCES research_files(id) ON DELETE CASCADE,
  handoff_id INTEGER NOT NULL
    REFERENCES research_handoffs(id) ON DELETE CASCADE,
  payload_json TEXT NOT NULL,                       -- serialized PriceTarget (composite, updated in place)
  as_of TEXT NOT NULL,                              -- denormalized from payload for quick queries
  schema_version TEXT NOT NULL DEFAULT '1.0',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
-- One PriceTarget per handoff (Q5 composite cardinality)
CREATE UNIQUE INDEX IF NOT EXISTS idx_price_targets_handoff
  ON price_targets(handoff_id);
"""
```

**Migration gate** (at `_maybe_migrate`):

```python
if current_version < 8:
    # v8 is purely additive — two new tables. No ALTER on theses (version column shipped in v7).
    conn.executescript(MODEL_INSIGHTS_STORAGE_SQL)
    conn.executescript(PRICE_TARGET_STORAGE_SQL)
```

**Fresh install (no `schema_version` table)**: add calls alongside existing helpers in the cold-start block (line ~1049 in v7):

```python
if row is None:
    conn.executescript(CREATE_ALL_SQL)
    _create_research_files_idea_id_unique_index(conn)
    _create_research_handoffs_unique_draft_index(conn)
    _create_process_template_storage(conn)
    _create_model_insights_storage(conn)   # NEW
    _create_price_targets_storage(conn)    # NEW
    ...
```

**Why separate `price_targets` table** (not JSON on `research_handoffs`): Q5 resolves to composite-in-place updates. A unique index on `handoff_id` cleanly enforces "one per handoff" at the DB level + makes upsert semantics trivial (`INSERT ... ON CONFLICT(handoff_id) DO UPDATE SET payload_json=excluded.payload_json, as_of=...`). JSON-on-handoff would require reading+rewriting the whole handoff row for every scenario refresh.

**Service layer** — new file `api/research/model_insights_service.py`:

```python
class ModelInsightsService:
    """Read/write for ModelInsights + PriceTarget. Stateless; mirrors ThesisService pattern."""
    def __init__(self, repo: ResearchRepository): ...

    # ── ModelInsights (many-per-handoff, append-only snapshots) ────────────
    def record_insights(
        self,
        research_file_id: int,
        handoff_id: int,
        insights: ModelInsights,
    ) -> int:
        """Insert new snapshot row. UUIDv5 collision → IntegrityError (signals duplicate build emit)."""

    def list_insights_for_handoff(
        self,
        handoff_id: int,
        limit: int | None = None,
    ) -> list[ModelInsights]:
        """Ordered by generated_at DESC. limit=None returns all (audit replay)."""

    def get_insights_by_id(self, model_insights_id: str) -> ModelInsights | None: ...

    def latest_insights_for_handoff(self, handoff_id: int) -> ModelInsights | None:
        """Convenience — ORDER BY generated_at DESC LIMIT 1."""

    # ── PriceTarget (one-per-handoff, upsert semantics) ────────────────────
    def upsert_price_target(
        self,
        research_file_id: int,
        handoff_id: int,
        pt: PriceTarget,
    ) -> None:
        """INSERT ON CONFLICT(handoff_id) DO UPDATE — scenario refresh semantics.
        Service computes canonical id = price_target_id(research_file_id, handoff_id)
        and ENFORCES that pt.price_target_id matches — raises `PriceTargetIdMismatchError`
        if caller passed a different id. This eliminates the R0.2 drift where row key
        and payload id could diverge (Blocker 3).
        Also mirrors pt.ranges.mid into the handoff's model_ref.last_price_target
        via _repo.update_handoff_model_ref_last_price_target (plan #2 handoff writer — uses
        its own existing path, not plan #6's OCC. Out of scope for patch-engine row safety)."""

    def get_price_target(self, handoff_id: int) -> PriceTarget | None: ...
```

**UUIDv5 namespacing** (stable across processes):

```python
# schema/_uuid.py  (new module — reused by studio producer in §9)
import uuid

# One fixed namespace UUID per type. Choose random UUIDv4s committed to the repo
# so every producer/consumer derives the same IDs from the same content.
_NS_MODEL_INSIGHTS = uuid.UUID("d6e2b8f4-..." )    # pin at sub-phase A implementation
_NS_PRICE_TARGET   = uuid.UUID("a3c1d9e2-..." )
_NS_ASSUMPTION     = uuid.UUID("7f4e6a1b-..." )
_NS_RISK           = uuid.UUID("2b8c5d3e-..." )
_NS_CATALYST       = uuid.UUID("9e1a4f7c-..." )
_NS_TRIGGER        = uuid.UUID("4d2b8a6f-..." )
_NS_CLAIM          = uuid.UUID("1c9e7b3d-..." )

def model_insights_id(mbc_id: str, generated_at_iso: str) -> str:
    return str(uuid.uuid5(_NS_MODEL_INSIGHTS, f"{mbc_id}|{generated_at_iso}"))

def price_target_id(research_file_id: int, handoff_id: int) -> str:
    """Handoff-scoped: stable by construction across scenario upserts.
    R2 Blocker 3 fix — `first_as_of` scheme (R0.2) drifted because caller had to remember
    'first' across process boundaries. Handoff-scoped namespace is race-free."""
    return str(uuid.uuid5(_NS_PRICE_TARGET, f"{research_file_id}|{handoff_id}"))

def assumption_id(driver: str, value: float, rationale: str) -> str:
    return str(uuid.uuid5(_NS_ASSUMPTION, f"{driver}|{value}|{rationale}"))
# risk_id, catalyst_id, trigger_id, claim_id — analogous: hash on
# (description + severity) / (description + expected_date) / etc.
```

### 7.3 Files to create/modify

**AI-excel-addin**:
- **Create**: `AI-excel-addin/schema/_uuid.py` — UUIDv5 namespaces + helpers
- **Create**: `AI-excel-addin/api/research/model_insights_service.py`
- **Modify**: `AI-excel-addin/api/research/repository.py`:
  - Bump `CURRENT_SCHEMA_VERSION = 8`
  - Add `MODEL_INSIGHTS_STORAGE_SQL`, `PRICE_TARGET_STORAGE_SQL`, `_create_model_insights_storage`, `_create_price_targets_storage` helpers
  - Migration gate `if current_version < 8:` block
  - Cold-start block adds the two helpers
  - New repository methods: `insert_model_insights`, `list_model_insights_by_handoff`, `get_model_insights`, `upsert_price_target`, `get_price_target_by_handoff`
- **Modify**: `AI-excel-addin/schema/__init__.py` — re-export `_uuid` helpers under a `schema.ids` namespace

**Tests**:
- **Create**: `AI-excel-addin/tests/api/research/test_model_insights_repository.py`
- **Create**: `AI-excel-addin/tests/api/research/test_model_insights_service.py`
- **Create**: `AI-excel-addin/tests/api/research/test_migration_v8.py` — cold-install + v7→v8 migration path
- **Create**: `AI-excel-addin/tests/schema/test_uuid_helpers.py`

### 7.4 Tests

| Test | Coverage |
|---|---|
| `test_v8_migration_creates_tables` | v7 DB → migrate → `model_insights` + `price_targets` tables exist with expected columns + indexes |
| `test_v8_migration_idempotent` | Second run is a no-op (CREATE TABLE IF NOT EXISTS + schema_version guard) |
| `test_cold_install_v8` | Fresh install lands at `CURRENT_SCHEMA_VERSION = 8` with all tables |
| `test_model_insights_insert_roundtrip` | Insert MI → fetch by `model_insights_id` → payload equal |
| `test_model_insights_list_ordered_by_generated_at_desc` | 3 inserts with varying timestamps → list returns newest-first |
| `test_model_insights_id_uniqueness_integrity_error` | Duplicate `model_insights_id` → sqlite3.IntegrityError |
| `test_model_insights_cascade_on_file_delete` | Delete research_file → MI rows gone |
| `test_price_target_upsert_inserts_first_time` | Empty table → upsert creates row |
| `test_price_target_upsert_updates_second_time` | Second upsert (same handoff_id) → same `price_target_id`, updated `payload_json` + `as_of` + `updated_at` |
| `test_price_target_unique_per_handoff` | Two different `price_target_id` values on same `handoff_id` → IntegrityError |
| `test_price_target_id_stable_across_updates` | Upsert with new as_of → `price_target_id` unchanged (handoff-scoped UUIDv5 — Blocker 3 fix) |
| `test_price_target_id_mismatch_raises` | Caller passes PT with wrong price_target_id → `PriceTargetIdMismatchError` (defense against drift) |
| `test_mbc_delete_does_not_cascade_model_insights` | Delete row from `model_build_contexts` → MI rows with that mbc_id survive unchanged (Blocker 5 no-FK semantics) |
| `test_price_target_cascade_on_handoff_delete` | Delete handoff → PT row gone |
| `test_uuid_v5_deterministic_same_inputs` | Same inputs → same UUID across processes |
| `test_uuid_v5_differs_by_namespace` | Same content, different namespace (`_NS_ASSUMPTION` vs `_NS_RISK`) → different UUIDs |
| `test_last_price_target_mirror_on_upsert` | `upsert_price_target` also updates `handoff.model_ref.last_price_target` to `pt.ranges.mid` |

---

## 8. Sub-phase E — Patch application engine

### 8.1 Goal

Apply `HandoffPatchBatch` to `Thesis` (SoT) with stable-ID targeting, per-op validation, transactional semantics, dry-run support, and idempotent replay. HandoffArtifact snapshots re-derive via plan #2's shared-slice isomorphism (no direct artifact writes).

### 8.2 Design

**Pipeline** (R2.4 — dry-fold + OCC compare-and-swap; NO `_handoff_lock`):

```
preview_patch_ops(batch) OR apply_patch_ops(batch, research_file_id)
  │
  ├── 1. Parse batch → HandoffPatchBatch (Pydantic validation — per-op shape, unique op_ids)
  │
  ├── 2. Dry-fold pre-validation
  │     • Load current Thesis SoT via shipped repo.get_thesis_by_id(thesis_id) — returned row already includes version column (shipped v7)
  │     • Make deep copy (virtual_thesis). Remember read_version = current_thesis.version.
  │     • For each op in list order:
  │         - Check preconditions against virtual_thesis (add_* target must not exist;
  │           update_*/remove_* target must exist; value shape must type-check)
  │         - Apply op effect to virtual_thesis in-memory (update dict, append to list, etc.)
  │         - Pydantic re-validation after each op: Thesis.model_validate(virtual_thesis.model_dump())
  │     • Compute idempotent_replay flag: True iff virtual_thesis == original Thesis (before fold)
  │
  ├── 3. (dry-run only) return PatchPreview {diff, idempotent_replay, validation_ok=True, folded_thesis?}
  │
  ├── 4. (apply only) OCC compare-and-swap write
  │     • Call repo.update_thesis_artifact_if_version_matches(
  │         thesis_id=..., folded_thesis=virtual_thesis, expected_version=read_version
  │       )
  │     • Repo executes UPDATE theses SET ..., version = version + 1
  │       WHERE thesis_id = ? AND version = ?
  │     • If rows_affected == 0: raise PatchStaleError — someone committed between step 2 and here.
  │     • If rows_affected == 1: write committed. HandoffArtifact draft re-assembles via
  │       existing _assemble_artifact path; research_file_history entry written
  │       (event_type='patch_applied', payload = {op_count, op_types, batch_hash, idempotent_replay,
  │       fresh_version}).
  │
  ├── 5. Stale retry (bounded) — on PatchStaleError:
  │     • retry_count < 3 and batch is not preview → increment retry_count, go back to step 2
  │     • retry_count >= 3 → raise PatchStaleRetryExhaustedError to caller (surfaces via MCP agent flag)
  │
  └── 6. Return PatchApplyResult {applied_op_ids, idempotent_replay, audit_id, retry_count}
```

**Why OCC instead of `_handoff_lock`** (R2.4 pivot per Codex R5): the R0.2/R2.0 "acquire `_handoff_lock` + `BEGIN IMMEDIATE`" pattern hit three fatal issues on shipped code (re-entrancy deadlock, lock-order inversion, exemption soundness — see §1.2). OCC is the textbook solution for multi-writer row safety and sidesteps all three: no lock to be re-entrant, no order to invert, no exemption to get wrong. Other writers keep doing what they do today — they automatically participate via the `version = version + 1` bump in `_persist_thesis_payload`.

**Why whole-Thesis replace**: shipped `thesis_service.py` does not expose per-field mutators — routes.py:1440 pattern is "load Thesis, mutate dict, `Thesis.model_validate`, `repo.update_thesis_artifact`". Plan #6 adopts the same pattern: the dry-fold produces a fully-validated target `Thesis` object, and apply is a single writer call with CAS semantics.

**Retry semantics**: the 3-attempt bound protects against pathological contention; 50ms backoff between retries avoids thundering herd. Real-world contention is low (one analyst, one agent, occasional watcher); retry rarely fires.

**Preview cannot stale-retry**: `preview_patch_ops` does not write, so it reports the dry-fold result against whatever `version` was current at read time. The `read_version` is returned in the preview response so callers can gate their follow-up `apply_patch_ops` on a matching version (optional defensive pattern).

**Stable_id → Thesis traversal** (the core resolver — new module `api/research/patch_engine.py`):

```python
def _resolve_target(thesis: Thesis, op: HandoffPatchOp) -> _ResolvedTarget:
    """Map op to the concrete Thesis mutation. Raises MissingStableIdError / InvalidTargetError."""
    # Example for assumption ops:
    if isinstance(op, (ReplaceAssumptionValueOp, RemoveAssumptionOp)):
        idx = _index_of(thesis.assumptions, "assumption_id", op.target.assumption_id)
        if idx is None:
            raise MissingStableIdError(
                stable_id=op.target.assumption_id,
                target_collection="assumptions",
                op_id=op.op_id,
            )
        return _ResolvedTarget(collection="assumptions", index=idx)

    if isinstance(op, UpdateAssumptionFieldOp):
        ...  # same assumption_id lookup + field dispatch

    # Thesis headline — singleton field, no lookup needed
    if isinstance(op, (ReplaceThesisFieldStrOp, ReplaceThesisFieldIntOp)):
        return _ResolvedTarget(collection="thesis", field=op.target.field)

    # ... one branch per op class
```

**Conflict detection** (R2 — dry-fold replaces standalone `_detect_conflicts`):

Since the dry-fold builds virtual_thesis incrementally, conflicts fall out naturally from the fold itself:

```python
def _dry_fold(thesis: Thesis, batch: HandoffPatchBatch) -> tuple[Thesis, list[PatchConflict]]:
    """Apply ops to a virtual copy of thesis in list order. Each op validates its preconditions
    against the *current state of virtual_thesis* (not the original) — so earlier ops' effects are visible.
    Any precondition failure produces a PatchConflict; the fold continues so we can surface multiple issues
    in one pass (better UX than stopping at first error)."""
    virtual = thesis.model_copy(deep=True)
    conflicts: list[PatchConflict] = []
    for op in batch.ops:
        try:
            virtual = _apply_op_to_virtual(virtual, op)  # see per-op mapping below
        except (MissingStableIdError, DuplicateStableIdError, InvalidTargetError) as err:
            conflicts.append(PatchConflict(op_id=op.op_id, reason=str(err)))
        # Continue — accumulate all conflicts for single-shot reporting
    return virtual, conflicts
```

`_apply_op_to_virtual(thesis, op)` — builds the new Thesis by applying the op's effect to the mutable dict form, then `Thesis.model_validate(new_dict)`. Precondition checks per the rule matrix in §3.4:

| Op class | Precondition in virtual | On fail raise |
|---|---|---|
| `AddAssumptionOp` | `virtual.assumptions` must not contain `value.assumption_id` | `DuplicateStableIdError` |
| `ReplaceAssumptionValueOp`, `RemoveAssumptionOp`, `UpdateAssumptionFieldOp` | `virtual.assumptions` must contain `target.assumption_id` | `MissingStableIdError` |
| `ReplaceThesisFieldStrOp` / `ReplaceThesisFieldIntOp` | Target field is always singleton — no precondition beyond value type | `InvalidTargetError` if value type mismatch |
| `UpdateValuationOp` | `virtual.valuation` must exist (shared slice presence) | `InvalidTargetError` if None |
| `AddRiskOp` / `AddCatalystOp` / `AddInvalidationTriggerOp` / `AddDifferentiatedViewClaimOp` | Same as AddAssumption — no duplicate id in respective list | `DuplicateStableIdError` |
| `UpdateRiskOp` / `RemoveRiskOp` (and analogous for catalyst/trigger/claim) | id must exist in respective list | `MissingStableIdError` |
| `UpdateConsensusViewOp`, `UpdateThesisQuantitativeOp` | No stable-id precondition — singleton sections | Pydantic re-validation catches type issues |

**Idempotent replay detection** (R2 Blocker 4 refinement):

```python
def _is_idempotent_replay(original: Thesis, virtual: Thesis) -> bool:
    """True iff the fold produced no effective change. Covers all op types including add_*.
    For add_X(a1, P) where a1 already exists with identical payload P in original:
      precondition would fire DuplicateStableIdError — but only if payload differs.
      If payload matches, we skip the 'duplicate' error AND the add is a no-op.
      Implementation: _apply_op_to_virtual sees add_X with matching-existing-id-and-payload
      → returns virtual unchanged, no error."""
    return original.model_dump(mode="json") == virtual.model_dump(mode="json")
```

Note: this subtle `add_*` idempotent-replay semantics requires `_apply_op_to_virtual` to distinguish "duplicate id with same payload" (idempotent, skip) from "duplicate id with different payload" (conflict). Test `test_add_idempotent_with_matching_payload_is_noop` covers this.

**Idempotent replay** (§3.4):

```python
def _is_idempotent_replay(thesis: Thesis, batch: HandoffPatchBatch) -> bool:
    """True iff every op's target already matches its value. Runs BEFORE apply so we can
    tag the audit entry without executing writes."""
    for op in batch.ops:
        if not _current_value_matches_op(thesis, op):
            return False
    return True
```

**Transactional invariants** (R2.4 — OCC + SQLite `BEGIN IMMEDIATE`):
- Single CAS write: `UPDATE theses SET ..., version = version + 1 WHERE thesis_id = ? AND version = ?` — one statement, atomic at the DB level.
- Dry-fold exception before write → nothing persisted, typed error, no audit row, no retry.
- CAS miss (`rows_affected = 0`) → raise `PatchStaleError`, retry loop (max 3 attempts). On retry, dry-fold starts over with fresh read — all ops re-validated against the new SoT.
- Post-commit, `_assemble_artifact` refreshes HandoffArtifact via plan #2 shared-slice — caller gets consistent state. No lock involved (the shared-slice re-assembly is pure; it reads from Thesis + draft handoff row).

**Typed errors** (new module `api/research/errors.py` — extends plan #5's):

```python
class PatchBatchConflictError(ResearchError):          # 409
    conflicts: list[PatchConflict]
class MissingStableIdError(ResearchError):              # 404
    stable_id: str
    target_collection: str
    op_id: str
class DuplicateStableIdError(ResearchError):            # 409
    stable_id: str
    target_collection: str
    op_id: str
class InvalidTargetError(ResearchError):                # 400
    op_id: str
    reason: str
class PatchApplyError(ResearchError):                   # 500 — wraps unexpected internal failure
    op_id: str
    cause: str
```

### 8.3 Files to create/modify

- **Create**: `AI-excel-addin/api/research/patch_engine.py` — `_dry_fold`, `_apply_op_to_virtual`, `preview_patch_ops`, `apply_patch_ops`, `_is_idempotent_replay`, bounded-retry wrapper
- **Modify**: `AI-excel-addin/api/research/errors.py` — add 7 typed errors (`MissingStableIdError`, `DuplicateStableIdError`, `PatchBatchConflictError`, `InvalidTargetError`, `PatchStaleError`, `PatchStaleRetryExhaustedError`, `PriceTargetIdMismatchError`)
- **Modify**: `AI-excel-addin/api/research/repository.py` — add ONE new method `update_thesis_artifact_if_version_matches(thesis_id, thesis, expected_version) → bool` (sub-phase E scope — patch engine owns this). Issues a single `UPDATE theses SET ticker=?, label=?, version=?, updated_at=?, markdown_path=?, artifact_json=?, schema_version=? WHERE thesis_id=? AND version=?` with `new_version = expected_version + 1`. Must mirror the full write shape of the existing `_persist_thesis_payload` sink (all 7 columns, not just `artifact_json` + `version`) to stay consistent with shipped semantics. Returns `True` on `rowcount==1`, `False` on version mismatch. **Implementation note (Codex R8 nit)**: extract the normalization + serialization logic from `_persist_thesis_payload` (specifically `_coerce_thesis_input`, label normalization, markdown-path derivation, `updated_at` + `schema_version` stamping) into a shared private helper `_prepare_thesis_row_fields(thesis, row)` so both the CAS method AND the existing sink call the same code path. Reimplementing the derivation ad hoc would risk drift.
- **Modify**: `AI-excel-addin/api/research/repository.py` — extend `research_file_history` helper to accept `event_type='patch_applied'` payloads (with `retry_count` field)
- **Patch engine adds no new methods to `thesis_service.py`** — the engine reads via existing `get_thesis_by_id()` (which returns the row including `version`) and writes via the new CAS method above.
- **A-prereq does NOT touch OCC code**. R2.5 discovery: `theses.version` column, `_persist_thesis_payload` version bump, and `Thesis.version` Pydantic field all already ship in v7. A-prereq is ONLY `ValuationMethod` widen. Prior R2.1-R2.3 plans to wrap writers in `_handoff_lock` are dropped entirely.

### 8.4 Tests

| Test | Coverage |
|---|---|
| `test_preview_reads_version_no_write` | Dry-run reads thesis version but does NOT CAS; inspect DB row — version unchanged after preview |
| `test_apply_round_trip_each_op` | Parametrized over all 21 concrete op classes — apply → Thesis state changes as expected |
| `test_missing_stable_id_raises_typed` | `update_assumption` with unknown `assumption_id` → `MissingStableIdError` (with op_id in payload) |
| `test_duplicate_stable_id_on_add` | `add_assumption` with `assumption_id` that already exists → `DuplicateStableIdError` |
| `test_batch_conflict_same_target` | Two `replace_assumption_value` on same `assumption_id` with different values → `PatchBatchConflictError` |
| `test_batch_no_conflict_update_then_remove` | `update_assumption_field` followed by `remove_assumption` on same id → applies cleanly (remove wins by sequence) |
| `test_batch_conflict_op_after_remove` | `remove_assumption` then `update_assumption_field` on same id → `PatchBatchConflictError` |
| `test_add_then_reference_in_same_batch` | Q4 — `add_risk(risk_id=r1)` + later op referencing `r1` → applies (client pre-assigned id resolves) |
| `test_apply_is_transactional` | Op #3 in a 5-op batch forced to raise during dry-fold → fold halts before CAS write → no thesis mutation at all (whole-Thesis replace design: nothing is written until the full fold succeeds) |
| `test_idempotent_replay_flag` | Apply same batch twice → second apply tagged `idempotent_replay=true`, Thesis unchanged on second pass, both batches audit-logged |
| `test_handoff_artifact_rederives` | After apply, calling `_assemble_artifact` produces HandoffArtifact reflecting patched Thesis state (plan #2 isomorphism) |
| `test_research_file_history_entry` | Apply creates one row in `research_file_history` with `event_type='patch_applied'`, payload contains `op_count`, `op_types`, `batch_hash` |
| `test_occ_stale_write_raises_patch_stale` | Two patch-applies race on same thesis: one commits, the other's CAS misses → `PatchStaleError` raised (not silent overwrite) |
| `test_occ_retry_succeeds_on_second_attempt` | Seed transient stale condition (external writer commits once during first dry-fold) → retry succeeds cleanly; audit entry has `retry_count=1` |
| `test_occ_retry_exhausted_raises_user_error` | Force CAS to miss 3 consecutive times (mock `update_thesis_artifact_if_version_matches` → False always) → `PatchStaleRetryExhaustedError` raised to caller |
| `test_no_handoff_lock_acquired` | Inspect patch engine execution — asserts `_handoff_lock` is NOT acquired anywhere in the preview or apply path (OCC is the sole coordination mechanism) |
| `test_all_ops_fold_coverage` | Parametrized over all 21 concrete op classes — asserts `_apply_op_to_virtual(thesis, op)` handles each without raising `NotImplementedError` |
| `test_add_idempotent_with_matching_payload_is_noop` | `add_X(a1, P)` where a1 already in Thesis with identical P → no-op, tagged idempotent_replay=true, no DuplicateStableIdError |
| `test_add_with_different_payload_raises_duplicate` | `add_X(a1, P2)` where a1 exists with P1 (P1 ≠ P2) → `DuplicateStableIdError` |
| `test_fold_accumulates_multiple_conflicts` | Batch with 3 separate failures → all 3 surface in `PatchBatchConflictError.conflicts` (not first-fail-only) |

**Property-based tests**: use `hypothesis` to generate batches of 1-10 random ops + verify `apply(batch) == reduce(apply_single, batch.ops, thesis)` when batch is conflict-free. (Optional; skip if outside plan #5 style.)

---

## 9. Sub-phase F — Modeling-studio integration

### 9.1 Goal

AI-excel-addin `build_model_orchestrator.py` emits `ModelInsights` on every build (base + each scenario). `PriceTarget` upserted after valuation step. `handoff_patch_suggestions` populated from orchestrator heuristics so analysts see typed suggestions instead of prose.

### 9.2 Design

**Insertion point** (R2 — shipped entry point verified): post-build hook inside `BuildModelOrchestrator.build_and_annotate()` at `api/research/build_model_orchestrator.py:114` (and the `build_and_annotate_from_mbc_id` convenience wrapper). Runs AFTER annotation + valuation, BEFORE return. R0.2 named a non-existent `BuildModelOrchestrator.build_and_annotate()` function (Codex R1 nit fixed here).

```python
# api/research/build_model_orchestrator.py (modification inside BuildModelOrchestrator.build_and_annotate)
# Shipped signature (verified 2026-04-23 at build_model_orchestrator.py:114):
#   def build_and_annotate(self, handoff_id, user_id, business_model=None) -> BuildResult
# The orchestrator loads the MBC internally from handoff_id — caller passes only identifiers.

class BuildModelOrchestrator:
    def build_and_annotate(self, handoff_id: int, user_id: str, business_model=None) -> BuildResult:
        ...  # existing: load MBC, run build + annotate
        mbc = self._load_mbc(handoff_id, user_id)          # existing path, not new
        model_state = self._apply_formula_first(...)
        self._annotate_model(...)

    # ── NEW: emit ModelInsights + upsert PriceTarget ─────────────────────
    insights = _derive_model_insights(mbc=mbc, model_state=model_state)
    price_target = _derive_price_target(mbc=mbc, model_state=model_state)

    model_insights_service.record_insights(
        research_file_id=mbc.handoff_ref.research_file_id,
        handoff_id=mbc.handoff_ref.handoff_id,
        insights=insights,
    )
    model_insights_service.upsert_price_target(
        research_file_id=mbc.handoff_ref.research_file_id,
        handoff_id=mbc.handoff_ref.handoff_id,
        pt=price_target,
    )
    ...
```

**Derivation heuristics** (preliminary — refined during implementation):

1. **`driver_sensitivities`**: for each driver in `mbc.drivers`, run a ±1pp shock against the model and record the delta in (a) target metrics like `eps_{projection_last_year}`, `ebitda_margin_{year}`, (b) price-target mid. Rank by absolute `impact_per_unit`.
2. **`implied_assumptions`**: walk the post-build model state and identify assumptions the build *made explicit* that weren't in the handoff's `assumptions[]` list (e.g., terminal growth rate defaulted from sector, margin trajectory implied by formula chain). For each:
   - `driver_key`: matched via reverse-lookup of `driver_mapping.yaml`
   - `suggests_patch: bool = True` **iff** (a) the implied value differs from any handoff `assumption` by >5% on the same driver_key, OR (b) there's no handoff assumption at all for that driver_key AND the driver has rank ≤ 3 in `driver_sensitivities` (i.e., it's material).
3. **`risks_surfaced`**: enumerate build-time warnings (e.g., "WACC calculation fell back to manual 9% because CAPM inputs missing", "terminal growth 3% exceeds nominal GDP assumption"). Severity mapping:
   - `high` = build-blocking resolved via fallback (could affect output materially)
   - `medium` = input-quality issue (missing data, stale filing)
   - `low` = cosmetic (label fallback, segment-naming default)
4. **`handoff_patch_suggestions`**: emit ops from the above, primarily:
   - `add_assumption` for each `implied_assumption` with `suggests_patch=True` — stable_id pre-assigned via `assumption_id(driver, value, rationale)` UUIDv5 helper
   - `add_risk` for each high-severity entry in `risks_surfaced` — stable_id pre-assigned via `risk_id(description, severity)` helper
   - `update_valuation` for the computed `ranges.low/mid/high` (mirrors into `Valuation` if Thesis carries different ranges)
   - `update_thesis_quantitative` for `scenarios.base.target_price` if it diverges from current

**PriceTarget composite derivation** (Q5):
- Base build → sets `ranges.mid`, `ranges.low`, `ranges.high` to the valuation's `low/mid/high`
- Scenario runs (bull/base/bear, or custom scenarios declared in `mbc.scenarios`) update the PT by taking:
  - `ranges.low = min(all scenario target prices)`
  - `ranges.high = max(...)`
  - `ranges.mid = base-scenario target price` (stable anchor)
- `as_of` updates to the latest build's timestamp
- `price_target_id` is always `price_target_id(research_file_id, handoff_id)` — stable across upserts (Blocker 3); producer recomputes on every emit and the service validates it matches.

**No forward-ref rebuild needed** (R2 Blocker 2): the one-way import (`model_insights.py` imports `HandoffPatchOp` from `handoff_patch.py`; `handoff_patch.py` imports only from `_insights_shared.py`) removes the cycle. No `ModelInsights.model_rebuild()` call required. R0.2 mistakenly prescribed one because of the assumed cycle.

**Shim for existing callers**: the orchestrator hook is purely additive. If `_derive_model_insights` raises, log + continue (model build succeeds even if insight derivation fails; insight emission is not build-critical). Feature-flag gate `EMIT_MODEL_INSIGHTS=true` (default on after R1 soak).

### 9.3 Files to create/modify

- **Modify**: `AI-excel-addin/api/research/build_model_orchestrator.py` — hook inside `BuildModelOrchestrator.build_and_annotate()` at line 114 (verified shipped entry point, R2)
- **Create**: `AI-excel-addin/api/research/insights_deriver.py` — `_derive_model_insights`, `_derive_price_target`, shock-based sensitivity runner
- **NO `model_rebuild()` needed** (R2 Blocker 2): one-way imports break the former cycle, no forward-ref to materialize
- **Create**: `AI-excel-addin/tests/api/research/test_insights_deriver.py`
- **Create**: `AI-excel-addin/tests/api/research/test_build_orchestrator_insights_hook.py`

### 9.4 Tests

| Test | Coverage |
|---|---|
| `test_build_emits_insights_and_price_target` | After `BuildModelOrchestrator.build_and_annotate`, MI row + PT row exist with matching `model_build_context_id` |
| `test_driver_sensitivities_ranked_dense` | Sensitivity shock runner produces `rank` = dense [1..N] |
| `test_implied_assumption_suggests_patch_on_5pct_deviation` | Implied value differs from handoff assumption by 6% → `suggests_patch=True` |
| `test_implied_assumption_no_suggest_when_matches` | Implied value within 5% → `suggests_patch=False` |
| `test_implied_assumption_suggests_when_material_and_missing` | No handoff assumption for driver + rank ≤ 3 → `suggests_patch=True` |
| `test_risks_surfaced_severity_mapping` | Build warnings → expected severity levels |
| `test_handoff_patch_suggestions_populate_from_implied_assumptions` | Implied assumptions with `suggests_patch=True` → corresponding `add_assumption` ops emitted with pre-assigned `assumption_id` |
| `test_price_target_composite_from_scenarios` | 3 scenario runs (bull/base/bear) → PT.ranges.low=min, high=max, mid=base |
| `test_price_target_id_stable_across_scenarios` | First build generates PT id X; scenario refresh 2h later → PT id still X |
| `test_build_survives_insight_derivation_failure` | `_derive_model_insights` raises → build_model still returns successfully (non-critical hook) |
| `test_feature_flag_disables_emit` | `EMIT_MODEL_INSIGHTS=false` → no MI/PT rows written |

---

## 10. Sub-phase G — risk_module MCP surface

### 10.1 Goal

Expose ModelInsights + PriceTarget + patch engine through the risk_module MCP surface following plan #5's pattern (`mcp_tools/research.py` tools + `actions/research.py` business layer + gateway 4xx classifier + typed agent flags + `format="agent"` response composition).

### 10.2 Tool surface

4 new tools in `mcp_tools/research.py`:

```python
@handle_mcp_errors
def get_model_insights(
    research_file_id: int,
    model_insights_id: str | None = None,    # if None, returns latest for handoff
    user_email: str | None = None,
    format: Literal["summary", "agent"] = "agent",
) -> dict[str, Any]:
    """Retrieve ModelInsights — either a specific snapshot or the latest for the handoff."""

@handle_mcp_errors
def get_price_target(
    research_file_id: int,
    user_email: str | None = None,
    format: Literal["summary", "agent"] = "agent",
) -> dict[str, Any]:
    """Retrieve the composite PriceTarget for a research file (one per handoff)."""

@handle_mcp_errors
def preview_patch_ops(
    research_file_id: int,
    ops: list[dict[str, Any]],               # batch of HandoffPatchOp dicts
    user_email: str | None = None,
    format: Literal["summary", "agent"] = "agent",
) -> dict[str, Any]:
    """Dry-run patch batch — returns diff + validation errors without mutating Thesis."""

@handle_mcp_errors
def apply_patch_ops(
    research_file_id: int,
    ops: list[dict[str, Any]],
    user_email: str | None = None,
    format: Literal["summary", "agent"] = "agent",
) -> dict[str, Any]:
    """Transactionally apply batch to Thesis. Full rollback on any failure."""
```

All 4 route through `actions/research.py` (business-layer consolidation per existing architecture) and then to the gateway for remote execution.

### 10.3 Agent flags

Extend `_build_research_agent_response` flag dict with 6 new flags:

| Flag | Triggers | Agent semantics |
|---|---|---|
| `model_insights_fresh` | Latest MI `generated_at` within 24h of current time | Suggestions are current; safe to act on |
| `model_insights_stale` | Latest MI older than 7 days | Rebuild before acting on suggestions |
| `price_target_missing` | No PT row exists for handoff | Build model before asking for sizing signal |
| `patch_suggestions_pending` | Latest MI has `handoff_patch_suggestions` non-empty AND none applied since emit | Analyst review recommended |
| `patch_apply_failed` | Last `apply_patch_ops` call raised | Surface error detail + retry guidance |
| `patch_applied_idempotent_replay` | `apply_patch_ops` succeeded but was a no-op | Signal to agent that it's already done |
| `patch_stale_retry_exhausted` | OCC retry loop exhausted after 3 attempts | High contention on thesis; agent should refresh context and retry later |

### 10.4 Typed errors + gateway classifier (R2 Blocker 8 — corrected location + shape)

**Location** (verified 2026-04-23): shipped classifier lives in `services/research_gateway.py:203` in method `_classify_and_raise()`. There is no `gateway/classifier.py`. The method dispatches via a `_THESIS_ERROR_TYPES` dict and `_build_typed_error()` helper at `services/research_gateway.py:275`.

**Error extraction shape**: `_extract_error_code()` at `services/research_gateway.py:277` reads `body.get("error")` first, then falls back to `body.get("detail", {}).get("error")`. The key is **`error`** (singular, not `error_type`). R0.2 named the wrong key.

**Route emission shape** (verified at `api/research/routes.py:274` and analogous helpers): typed errors raise HTTPException with `detail={"error": "<code>", "message": ..., **extra_fields}`. Plan #6 route handlers follow the same pattern.

**Plan #6 extension** — add 8 entries to the `_THESIS_ERROR_TYPES` map (the existing dispatcher handles the HTTP status mapping + invocation of `_build_typed_error`):

| HTTP | Classifier match (`body.error` OR `body.detail.error`) | Typed exception |
|---|---|---|
| 404 | `"missing_stable_id"` | `MissingStableIdError` |
| 404 | `"model_insights_not_found"` | `ModelInsightsNotFoundError` |
| 404 | `"price_target_not_found"` | `PriceTargetNotFoundError` |
| 409 | `"duplicate_stable_id"` | `DuplicateStableIdError` |
| 409 | `"patch_batch_conflict"` | `PatchBatchConflictError` |
| 409 | `"patch_stale_retry_exhausted"` | `PatchStaleRetryExhaustedError` (R2.4 OCC — retry loop gave up; caller should refresh state and retry manually) |
| 400 | `"invalid_patch_target"` | `InvalidTargetError` |
| 422 | Pydantic body validation on `HandoffPatchBatch` | existing `ActionStructuredValidationError` (no change) |

Note: transient `PatchStaleError` (single CAS miss) is caught and retried INSIDE the route handler — it never surfaces via the MCP surface. Only the terminal `PatchStaleRetryExhaustedError` reaches the classifier.

Each new exception class lives in `actions/errors.py` following plan #5's pattern (see `TemplateSwitchError`, `TemplateIdConflictError`, `TemplateRequirementsError`).

### 10.5 Files to create/modify

**risk_module** (R2 Blocker 8 + nits corrected):
- **Modify**: `mcp_tools/research.py` — 4 new tool functions above; `_build_research_agent_response` helper lives HERE at line 436 (no separate file)
- **Modify**: `actions/research.py` — 4 business-layer functions that call the gateway
- **Modify**: `services/research_gateway.py` — extend `_THESIS_ERROR_TYPES` dict (line ~203) with 6 new typed-error entries; no new extractor logic needed (existing `_extract_error_code` handles `body.error` + `body.detail.error`)
- **Modify**: `actions/errors.py` — add `MissingStableIdError`, `DuplicateStableIdError`, `PatchBatchConflictError`, `InvalidTargetError`, `ModelInsightsNotFoundError`, `PriceTargetNotFoundError` (follow plan #5 exception pattern)
- **Modify**: `mcp_tools/research.py` `_build_research_agent_response` — add 6 new flag rules

**AI-excel-addin** (server-side handlers):
- **Create**: `AI-excel-addin/api/research/routes.py` — new route handlers `POST /research/files/{id}/patch-ops/preview`, `POST /research/files/{id}/patch-ops/apply`, `GET /research/files/{id}/model-insights`, `GET /research/files/{id}/price-target`
- Raise typed errors with `detail={"error": "<code>", "message": ...}` payloads matching `_THESIS_ERROR_TYPES` entries (R2 Blocker 8 shape)

**Tests**:
- **Create**: `tests/mcp_tools/test_model_insights.py` — 4 new tools × summary+agent format
- **Create**: `tests/actions/test_research_patch_ops.py` — business layer
- **Create**: `tests/gateway/test_patch_ops_classifier.py` — classifier branches

### 10.6 Tests

| Test | Coverage |
|---|---|
| `test_get_model_insights_returns_latest_when_id_omitted` | Omit `model_insights_id` → service returns latest-by-generated_at |
| `test_get_model_insights_by_id` | Specific id → that snapshot |
| `test_get_model_insights_agent_format` | `format="agent"` → response carries `flags.model_insights_fresh` |
| `test_get_price_target_agent_format` | Includes `implied_return_pct` + ranges + confidence in agent shape |
| `test_preview_patch_ops_no_mutation` | Preview → Thesis unchanged, response includes diff + validation_ok |
| `test_apply_patch_ops_success` | Valid batch → response includes `applied_op_ids` + `audit_id` + `idempotent_replay=False` |
| `test_apply_patch_ops_conflict_409` | Same-target conflicts in batch → HTTP 409 → `PatchBatchConflictError` on gateway side |
| `test_apply_patch_ops_missing_stable_id_404` | Unknown assumption_id → HTTP 404 → `MissingStableIdError` |
| `test_apply_patch_ops_idempotent_replay_flag` | Apply twice → second response flags `patch_applied_idempotent_replay` |
| `test_classifier_maps_error_code_correctly` | Parametrized over all 6 new `_THESIS_ERROR_TYPES` entries — `body={"error": "<code>", ...}` → correct typed exception |
| `test_classifier_falls_back_to_detail_error` | Same as above but `body={"detail": {"error": "<code>"}}` — exercises the existing fallback path |
| `test_agent_flags_patch_suggestions_pending` | MI with non-empty suggestions + no prior apply → flag set |
| `test_agent_flags_model_insights_stale` | MI > 7 days old → `model_insights_stale` true + `model_insights_fresh` false |

---

## 11. Sub-phase H — E2E + skill integration

### 11.1 E2E scenarios

Mirror plan #5 §11 pattern — each scenario exercises a full chain: research_file seed → API calls → DB state assertion + `HandoffArtifact` re-derive.

**Scenario 1 — Full feedback loop (happy path)**
1. Seed research_file + draft handoff (via `bootstrap_from_idea` or direct API)
2. Build model via `BuildModelOrchestrator.build_and_annotate(handoff_id, user_id)` (shipped signature) → assert MI row + PT row exist
3. Call `get_model_insights(research_file_id)` → assert `handoff_patch_suggestions` non-empty
4. Call `preview_patch_ops(ops=suggestions)` → assert `validation_ok=true`, diff returned
5. Call `apply_patch_ops(ops=suggestions)` → assert 200 OK, `applied_op_ids` matches
6. Re-fetch Thesis → assert `assumptions[]` contains newly-added entries with correct stable_ids
7. Call `HandoffService._assemble_artifact(file_row, draft)` → assert HandoffArtifact reflects patched Thesis (plan #2 isomorphism)
8. Call `finalize_handoff(research_file_id)` → assert template gates pass (G7/G12 from plan #5)

**Scenario 2 — Composite PriceTarget from scenario runs**
1. Build base model → PT row exists with `ranges = {low: X, mid: X, high: X}` (single-point)
2. Run bull scenario by rebuilding MBC with bull overrides + calling `BuildModelOrchestrator.build_and_annotate(handoff_id, user_id)` → PT upserted: `ranges.high` updated, `mid` stable, `price_target_id` unchanged
3. Run bear scenario → `ranges.low` updated
4. Assert final PT: `low ≤ mid ≤ high`, single row in `price_targets` table, `as_of` = latest scenario timestamp

**Scenario 3 — Missing stable_id typed error**
1. Build MI with `handoff_patch_suggestions` for `assumption_id=a1`
2. Manually delete `a1` from Thesis (simulating analyst edit between MI emit and apply)
3. Call `apply_patch_ops(ops=[update_assumption_field(a1, ...)])` → assert HTTP 404
4. Gateway classifier produces `MissingStableIdError` with `stable_id=a1`, `op_id` populated
5. Assert no partial apply — Thesis unchanged

**Scenario 4 — Dry-fold failure halts before CAS** (R2.5 — no SAVEPOINT, no lock involved)
1. Build a 5-op batch; op #3 deliberately references a missing stable_id (or produces a Pydantic re-validation failure on the virtual Thesis during fold)
2. Call `apply_patch_ops(ops=batch)` → assert 404/409/422 (per error type — §10.4)
3. Assert Thesis unchanged — dry-fold raised before the CAS method was invoked (whole-Thesis-replace design: nothing is written until the full fold succeeds). No `BEGIN IMMEDIATE` transaction ever opened for this batch.
4. Assert NO row written to `research_file_history` with `event_type='patch_applied'` (atomic audit — no write, no audit).

**Scenario 5 — Batch conflict detection**
1. Build batch with two `replace_assumption_value` ops on same `assumption_id` with different values
2. Call `preview_patch_ops` → assert `validation_ok=false`, error payload lists the conflict
3. Call `apply_patch_ops` → assert HTTP 409, `PatchBatchConflictError`
4. Assert no write, no audit entry

**Scenario 6 — Idempotent replay**
1. Apply a valid batch → success, Thesis mutated, audit entry #1 with `idempotent_replay=false`
2. Apply the SAME batch again → success, Thesis unchanged (no-op), audit entry #2 with `idempotent_replay=true`
3. Assert both audit entries exist (replay is logged even when no-op)
4. Assert `apply_patch_ops` response flags `patch_applied_idempotent_replay=true` on second call

**Scenario 7 — OCC stale-read detection + retry** (R2.5 refined: differentiate retry exhaustion from domain conflict)
1. Start apply on batch B1; stall between step 2 (dry-fold) and step 4 (OCC write) via test hook
2. Concurrently apply batch B2 (or any other writer — link update, watcher, etc.) that commits before B1's CAS
3. Resume B1 → CAS misses (`rows_affected=0`) → `PatchStaleError` → retry fires step 2 with fresh state
4. Two sub-outcomes to distinguish clearly:
   - **(a) Retry's dry-fold succeeds against new state** → B1 CAS writes cleanly → success (possibly after N<3 retries). Audit entry carries `retry_count=N`.
   - **(b) Retry's dry-fold raises a domain conflict** (e.g., B2 deleted an `assumption_id` that B1 wants to `update_X`) → surface the *domain error directly* (`MissingStableIdError` / `PatchBatchConflictError`), **not** `PatchStaleRetryExhaustedError`. Retry exhaustion is reserved for pathological CAS contention (3 consecutive CAS misses on folds that individually would have applied).
5. Assert B2's changes persisted in all cases; B1 either succeeds (with correct fold of B2's state) or fails loudly with the correct error class (no silent overwrite, no misattribution of domain conflict to retry exhaustion)

**Scenario 8 — Agent flag lifecycle**
1. Fresh MI emitted → call `get_model_insights(format="agent")` → `flags.model_insights_fresh=true`
2. Apply all suggestions → call again → `flags.patch_suggestions_pending=false`
3. Fast-forward 8 days (test fixture clock) → `flags.model_insights_stale=true`, `model_insights_fresh=false`

**Scenario 9 — Concurrency with plan #5 `apply_process_template`** (R2.4 — OCC-based)
1. Start `apply_process_template` on handoff H (acquires `_handoff_lock` — plan #5 behavior, unchanged)
2. Concurrently call `apply_patch_ops(H, ...)` — does NOT take `_handoff_lock`; proceeds with dry-fold
3. Two possible interleavings:
   - (a) Patch-apply reads version first → template apply commits (bumping version via `_persist_thesis_payload`) → patch-apply's CAS misses → retry picks up new template state → retry re-folds and writes successfully
   - (b) Patch-apply writes first → template apply reads patched state (inside its `_handoff_lock`) → template apply commits on top
4. Either way: final Thesis reflects both template + patches; no silent overwrite. OCC makes the interaction loss-free without requiring plan #5's lock to cover plan #6's writes.

**Scenario 10 — Build failure does not crash insight emit**
1. Force `_derive_model_insights` to raise mid-execution
2. Assert `BuildModelOrchestrator.build_and_annotate` still returns success (insight hook is non-critical, §9.2)
3. Assert no MI row written, no PT row written, no partial state

### 11.2 Skill integration

**`SKILL_CONTRACT_MAP.md` row additions** (AI-excel-addin):
- `/thesis-review` — add `read: get_model_insights(latest)`, `read: get_price_target`. Consume `handoff_patch_suggestions`; surface to analyst with dry-run diff from `preview_patch_ops`.
- `/thesis-pre-mortem` — add `read: get_model_insights`. Consume `risks_surfaced`; merge into pre-mortem risk list.
- `/position-initiation` — add `read: get_price_target`. Use `ranges.mid` + `confidence` + `implied_return_pct` as sizing input.
- `/model-build` — existing skill now produces MI + PT as side effects (no analyst action required, transparent).

**New skill** (optional, v2 candidate): `/patch-review` — pure consumer of the new surface. Reads latest MI, shows suggestions with diffs, invokes `apply_patch_ops` on analyst confirmation. Skeleton only in plan #6; full skill deferred.

### 11.3 Tests

| Test | Coverage |
|---|---|
| `test_e2e_full_feedback_loop` | Scenario 1 end-to-end via pytest + real SQLite temp DB |
| `test_e2e_composite_price_target` | Scenario 2 — 3 builds, one PT row throughout |
| `test_e2e_missing_stable_id` | Scenario 3 — deleted assumption → 404 |
| `test_e2e_transactional_rollback` | Scenario 4 — mid-batch failure → no partial apply |
| `test_e2e_batch_conflict` | Scenario 5 — same-target conflict → 409 |
| `test_e2e_idempotent_replay` | Scenario 6 — double-apply, second is no-op |
| `test_e2e_occ_stale_detection_and_retry` | Scenario 7 — interleaved applies; CAS miss → retry → final state consistent |
| `test_e2e_agent_flag_lifecycle` | Scenario 8 — flag state across time |
| `test_e2e_occ_with_template_apply` | Scenario 9 — template + patch interleave via OCC; final state consistent regardless of order |
| `test_e2e_build_survives_insight_failure` | Scenario 10 — non-critical hook |
| `test_skill_map_thesis_review_reads_mi` | `SKILL_CONTRACT_MAP.md` row parses + tool names resolve |

**Fixture strategy**: reuse plan #5's `bootstrap_from_idea` fixture + `start_research_from_idea` test helper for seeding research_files. MBC fixture needs minimal `handoff_ref` + one driver for sensitivity shock. Use `freezegun` or monkey-patched clock for timestamp-dependent tests (scenarios 2, 8).

---

## 12. Sub-phase I — Docs

- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` — ModelInsights + PriceTarget + HandoffPatchOp rows; Pattern updates for model→Thesis feedback loop
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §12 — mark plan #6 SHIPPED

---

## 13. Success criteria

Plan #6 ships successfully when ALL of the following hold:

**Schema layer**:
- `ModelInsights v1.0`, `PriceTarget v1.0`, `HandoffPatchOp v1.0` + `HandoffPatchBatch` land as Pydantic frozen types in `AI-excel-addin/schema/`
- All nested types (`ModelVersionRef`, `DriverSensitivity`, `ImpliedAssumption`, `RiskSurfaced`, `PriceTargetRanges`, `PriceTargetDriverSensitivity`, all 21 concrete op classes, all `Add*Value` / `Update*Value` payloads, all `*Target` types) materialize as frozen `extra="forbid"` models
- Schema `__init__.py` re-exports are in place; boundary test confirms the public surface
- UUIDv5 helpers in `schema/_uuid.py` deterministic across processes

**Storage layer**:
- v8 migration runs cleanly from v7 (existing deployments) AND from cold install
- `model_insights` + `price_targets` tables exist with indexes + FK cascades as specified in §7.2 (NO FK on `model_build_context_id` — Blocker 5)
- `CURRENT_SCHEMA_VERSION = 8`
- `ModelInsightsService` exposes the read/write surface in §7.2; 100% of its methods have unit test coverage
- `price_target_id` stable across upserts; row key and payload id never drift (Blocker 3)

**Patch engine**:
- `preview_patch_ops` + `apply_patch_ops` functions in `patch_engine.py` deliver the pipeline in §8.2 (parse → dry-fold pre-validate → dry-run OR CAS-write+audit, with bounded retry on `PatchStaleError`)
- All 21 concrete op classes handled by `_apply_op_to_virtual` (no `NotImplementedError` at runtime); whole-Thesis replace via new `repo.update_thesis_artifact_if_version_matches` (OCC CAS, §8.3) — no ThesisService mutators required
- Transactional invariants verified: dry-fold failure halts before CAS — nothing written, no audit row; CAS miss → retry; retry exhaustion → typed error
- Batch-level conflict detection (Q6) via dry-fold rejects ambiguous batches at pre-validation — `add_X + update_X`-same-batch legal (Blocker 4)
- Idempotent replay tagged in audit + returned in response; `add_*` with matching existing payload is no-op (Blocker 4 refinement)

**Studio integration**:
- `BuildModelOrchestrator.build_and_annotate` emits MI + upserts PT on every build
- Build failure mode: if `_derive_model_insights` raises, build still returns success (non-critical hook)
- Feature flag `EMIT_MODEL_INSIGHTS` honored

**MCP surface**:
- 4 MCP tools in `mcp_tools/research.py` operational
- Gateway classifier (`services/research_gateway.py:203`) handles 6 new `_THESIS_ERROR_TYPES` entries via `body.error` / `body.detail.error` extraction
- 6 new agent flags populate correctly in `format="agent"` responses

**E2E**:
- All 10 E2E scenarios in §11.1 pass end-to-end against a real SQLite temp DB (not mocked)

**Design gates (G3/G4 closure)**:
- **G3**: A model build produces a typed `ModelInsights` snapshot queryable via MCP. Agents + skills consume it instead of parsing free-form narrative. `risks_surfaced` and `driver_sensitivities` expose information that today is scattered in build logs + prose. ✅ when `/thesis-review` successfully shows typed suggestions from `get_model_insights` on a real ticker.
- **G4**: A composite `PriceTarget` exists per handoff, queryable via `get_price_target`, used by `/position-initiation` for sizing. ✅ when `last_price_target` mirror updates on every scenario refresh and `/position-initiation` reads it via MCP instead of prose parsing.

**Cross-plan integrity**:
- Plan #1/#2 shared-slice isomorphism holds under patching (HandoffArtifact re-derives from patched Thesis — no drift)
- Plan #3 MBC ↔ MI linkage via `model_build_context_id` TEXT column (no FK — Blocker 5): MI survives MBC pruning; agent flag `mbc_pruned` surfaces dangling provenance
- Plan #5 `_handoff_lock` unchanged (concurrency scenario 9 now runs via OCC, not lock expansion); plan #6 does NOT modify `_handoff_lock`'s scope. Row-level safety for patch engine comes from OCC (§1.2) — the patch engine uses the **already-shipped** `theses.version` column (v7) + already-shipped `_persist_thesis_payload` bump behavior. Plan #6's only addition is a new CAS method the patch engine calls instead of `update_thesis_artifact`. Other shipped writers keep their existing behavior — they bump `version` on write but do not CAS-check themselves; a potential future hardening of those writers is out of scope for plan #6
- `SKILL_CONTRACT_MAP.md` rows added for `/thesis-review`, `/thesis-pre-mortem`, `/position-initiation`, `/model-build`
- Master plan §12 marked SHIPPED with commit refs

**Review bar**:
- Codex plan review: R0→…→R? PASS before sub-phase A implementation begins
- Codex implementation review per sub-phase per plan #5 pattern
- Memory updated with ship notes matching `project_plan_5_process_template_shipped.md` template

---

## 14. Rollback

Plan #6 is additive — no existing tables modified, no existing fields renamed or removed, no existing behaviors changed except the optional `BuildModelOrchestrator.build_and_annotate` emit hook (feature-flagged).

**Rollback strategy by layer**:

**Feature flag rollback (immediate, no deploy)**:
- Set `EMIT_MODEL_INSIGHTS=false` → orchestrator skips MI/PT emit. Existing data preserved. No callers affected unless they actively read the new tables (which returns empty/404 — handled gracefully by MCP tools).
- Set `ENABLE_PATCH_OPS=false` (add flag at §10.5 time) → `preview_patch_ops` + `apply_patch_ops` return `503 feature_disabled` via gateway classifier. Skills that consume these tools must degrade gracefully (check flag in `@handle_mcp_errors` → fall back to manual-analyst prompt).

**Code rollback (revert commit range)**:
- Sub-phases A-C (schema types): revert → types gone from `schema/`. No runtime impact since nothing depends on them yet.
- Sub-phase D (storage): revert → migration v8 helpers gone. CAVEAT: `CURRENT_SCHEMA_VERSION = 8` rows in `schema_version` table persist. Writing an explicit DOWN migration is NOT required (SQLite tolerant of higher-stored-version vs lower-code-expectation — the check is `current_version < CURRENT_SCHEMA_VERSION`), BUT if re-reverted forward later, bumping to v9 will skip v8 steps. Document this in rollback notes; operationally safe because the `model_insights` + `price_targets` tables can persist unused.
- Sub-phase E (patch engine): revert → `patch_engine.py` gone, new typed errors gone. Gateway classifier loses 7 branches (fall back to generic `ActionError`).
- Sub-phase F (studio): revert → orchestrator hook gone; already safe because of feature flag.
- Sub-phase G (MCP surface): revert → 4 tools gone. Clients calling them get "unknown tool" — expected rollback behavior.
- Sub-phases H/I (E2E + docs): tests removed, docs revert.

**Data rollback**:
- `model_insights` + `price_targets` tables are append-only-plus-upsert. Safe to retain on code rollback.
- `research_file_history` entries with `event_type='patch_applied'` are audit records — retain on rollback for forensics.
- No destructive migrations. No `DROP TABLE` needed unless DB size pressure demands it (unlikely at current scale).

**Partial rollback scenarios**:
- **Schema types ship; storage doesn't**: Types exist but unused. Safe — schemas don't force DB presence.
- **Storage ships; studio doesn't**: Empty tables. Reads return 404. Safe.
- **MCP surface ships; patch engine doesn't**: `apply_patch_ops` would raise `NotImplementedError` → `500` with clear typed error. Gate behind `ENABLE_PATCH_OPS=false` from day 1 during staged rollout to avoid this.

**Rollback test matrix** (sub-phase I adds):
- `test_rollback_flag_disables_emit` — already covered in §9.4
- `test_rollback_flag_disables_patch_ops` — new; calling disabled tool returns typed `FeatureDisabledError`
- Operational test: deploy v8 → toggle `EMIT_MODEL_INSIGHTS=false` → confirm no writes to new tables → toggle back → confirm writes resume

**Non-rollback forward-only cases**:
- Once a patch is applied, the Thesis mutation is real. Patch ops are NOT reversible via a compensating `remove_*` op chain (that's an analyst-level undo, not a system rollback). `research_file_history` is the audit trail for manual revert if needed.
- HandoffArtifact re-derivation is deterministic from Thesis — no separate artifact rollback needed.

---

## 15. Design questions — RESOLVED (R0.1, 2026-04-23)

All six open questions resolved before R1 Codex review. Rationale captured below; detailed propagation lives in §3.2-§3.6 and §5.

1. **Where does ModelInsights persist?** — **New `model_insights` table** (v8 migration). Many-to-one with `research_file_id` (one row per build; base + scenarios each emit their own). See §3.3. JSON-column-on-existing rejected: Q5's 1-to-N cardinality with PriceTarget makes it cramped.
2. **Is ModelInsights regenerable?** — **Snapshot, not regenerable**. Persisted on `build_model` emission; `generated_at` is frozen at that instant. See §3.3. Replay from ModelBuildContext rejected: orchestrator `suggests_patch` heuristics may drift between invocations — original insights would not reproduce.
3. **Unified valuation method enum?** — **No. `PriceTarget.method` is `str` (non-empty validator), not a Literal.** §6.4 R3's proposed `Literal[dcf|multiples|sum_of_parts|hybrid]` is **superseded** by plan #5's shipped reality: `Valuation.method: str | None` is free-form, `prepopulate.py:323` emits `"relative"` as a valid live value, default templates allow `"relative"` in `valuation_methods_allowed`. Tightening PriceTarget.method to a Literal would diverge from Valuation.method and break "shared method" alignment. Subset enforcement stays at template finalize gate (plan #5, `_assemble_artifact_locked`). See §3.6.
4. **HandoffPatchOp op application order** — **Ordered + client-pre-assigned stable IDs + transactional**. Ops execute in list order. All `add_*` ops require the client to pre-assign the new stable_id (convention: UUIDv5 deterministic from content) in the op payload so later ops in the same batch can reference it. Full batch is all-or-nothing (rollback on any per-op failure). See §3.4. Apply-time ID assignment rejected: breaks idempotency + requires round-trip.
5. **PriceTarget composite vs per-scenario** — **Composite, one per handoff**. §6.4 already models it composite via `ranges: {low, mid, high}` aggregating bull/base/bear. Scenario runs update the PriceTarget in place (not new rows). Consumer contract stays unambiguous (`model_ref.last_price_target` singular). See §5. Per-scenario rejected: multiplies consumer complexity for no added signal beyond ranges.
6. **Patch conflict resolution** — **Error at pre-validation**. Two ops in the same batch targeting the same stable_id with conflicting changes → reject whole batch before lock acquisition with typed `PatchBatchConflictError`. Dry-run surfaces the conflict. See §3.4. Last-wins / first-wins rejected: breaks replay determinism + idempotency invariants.

---

## 16. Change log

### R0 skeleton stubbed (2026-04-23)

Initial skeleton drafted post-plan-#5 ship. Based on §6.4 of master plan. Structure mirrors plan #5 (9 sub-phases, ~11.5 days estimate).

### R0.1 design questions resolved (2026-04-23)

All six §15 open questions resolved before R1 review; rationale + propagation into §3.2-§3.6 and §5:

1. **Q1 storage** → new `model_insights` table (§3.3)
2. **Q2 regenerable** → snapshot only (§3.3)
3. **Q3 valuation method enum** → free-form `str`, **supersedes §6.4 R3** (§3.6)
4. **Q4 batch ordering** → ordered + client-pre-assigned stable IDs + transactional (§3.4)
5. **Q5 PriceTarget cardinality** → composite, one per handoff (§5 / §3.3)
6. **Q6 conflict resolution** → pre-validation error, whole-batch reject (§3.4)

**Before R1 Codex review, still need to flesh out:**
- §4 / §5 / §6 code sketches (lift from §6.4 lines 461-590 of master plan; update §5 for Q3 + Q5 decisions; update §6 for Q4 pre-assigned-ID convention)
- §7 sub-phase D design (pin the v8 migration shape now that storage model is decided)
- §8 sub-phase E design (pin pre-validation + transactional semantics now that Q4/Q6 are resolved)
- §9 / §10 design details
- §11 full E2E scenario list (add: pre-assigned-ID round-trip, PatchBatchConflictError path, idempotent replay)
- §13 success criteria
- §14 rollback plan
- Test matrices for each sub-phase

**Ready for R1 Codex review after**: §4-§6 code sketches filled; §7-§11 designs drafted per resolved decisions.

### R0.2 draft-complete (2026-04-23)

Filled remaining sections:

- **§4** — ModelInsights + 4 nested types (`ModelVersionRef`, `DriverSensitivity`, `ImpliedAssumption`, `RiskSurfaced`), 10 tests, dense-rank invariant
- **§5** — PriceTarget composite + ranges-ordering validator + free-form `method: str` per Q3, 11 tests, `last_price_target` mirror into `HandoffModelRef`
- **§6** — HandoffPatchOp discriminated union (20 ops, 8 categories), `HandoffPatchBatch` wrapper for batch-level invariants, Q4 pre-assigned-stable-ID convention in `Add*Value` payloads, 14 tests + parametrization
- **§7** — v8 migration pattern + `model_insights` + `price_targets` tables, `ModelInsightsService`, UUIDv5 namespace helpers, 15 tests
- **§8** — Patch engine pipeline (parse → pre-validate → dry-run OR lock+apply+audit), stable_id resolver, conflict detection (Q6), idempotent replay, 15 tests incl. concurrency
- **§9** — Build-orchestrator emit hook, `suggests_patch` heuristics (5pp threshold + material-rank rule), composite PT scenario update, non-critical-hook semantics, 11 tests
- **§10** — 4 MCP tools + 6 agent flags + 7 gateway classifier branches, 12 tests
- **§11** — 10 E2E scenarios (full loop, composite PT, missing id, rollback, conflict, idempotent replay, concurrent mod, flag lifecycle, lock contention with plan #5, build failure tolerance), skill integration list, 11 tests
- **§13** — Success criteria across schema/storage/engine/studio/MCP/E2E/G3-G4-closure/cross-plan-integrity
- **§14** — Rollback by layer (feature flag, code revert, data, partial scenarios) + forward-only notes on patch irreversibility

**Total test count estimate**: ~130 new tests across schema, service, engine, studio, MCP layers + 10 E2E. Comparable to plan #5's ~150.

**Ready for R1 Codex review.**

### R2 Codex-R1 FAIL response (2026-04-23)

Codex R1 returned **FAIL with 8 blockers + 3 nits** — 5 blockers surfaced by local execution (Pydantic imports, SQLite FK tests, MBC constructor validation). R2 addresses all:

**Blocker resolutions:**
1. **§6.2 incomplete + conviction type** — Materialized all 21 concrete op classes (20 logical ops; `replace_thesis_field` splits into `Str` / `Int` per-field ops for `ThesisField.conviction: int | None`).
2. **Circular imports + wrong import paths** — New `schema/_insights_shared.py` hosts shared enums/`_FROZEN_CONTRACT`; `handoff_patch.py` imports only from it (no back-reference to `model_insights.py`). `SourceId` corrected to `schema.thesis_shared_slice`. `canonicalize_optional_confidence` replaced with inline `field_validator`.
3. **PT id drift** — `price_target_id` UUIDv5 namespace changed from `(research_file_id, model_id, first_as_of)` to `(research_file_id, handoff_id)` — stable by construction across upserts. Service enforces id match via new `PriceTargetIdMismatchError`.
4. **Patch semantics contradictions** — §3.4 rewritten with dry-fold pre-validation (virtual Thesis built incrementally so `add_X + update_X` in same batch is legal). `_would_conflict` matrix expanded. `add_*` idempotent-replay distinguishes matching-payload (no-op) from conflicting-payload (`DuplicateStableIdError`).
5. **MBC FK conflicts** — `model_insights.model_build_context_id` is now plain TEXT with no FK. Shipped `delete_mbc()` + `delete_expired_mbcs()` unaffected. Snapshot rule preserved. MCP response exposes `flags.mbc_pruned` when provenance reference dangles.
6. **Q3 supersession only partial** — Added §1.2 scope addition to widen MBC's `ValuationMethod` Literal so `"relative"` flows end-to-end. Bundled into sub-phase A-prereq.
7. **Lock gap** — Added §1.2 scope addition: sub-phase A-prereq wraps `update_thesis_section` route (routes.py:1440) in `_handoff_lock`, closing the only shipped Thesis writer that bypassed serialization.
8. **MCP classifier location/shape wrong** — §10.4 corrected: classifier lives in `services/research_gateway.py:203`; `_THESIS_ERROR_TYPES` dict; `body.error` / `body.detail.error` extraction (not `error_type`).

**Nit resolutions:**
- Duplicate `## 10. Sub-phase G` stub removed
- `build_model_from_context` → `BuildModelOrchestrator.build_and_annotate` (shipped entry point at `build_model_orchestrator.py:114`)
- `mcp_tools/research_agent_response.py` → `mcp_tools/research.py` (no separate file; helper at line 436)

**Design change from Codex R1 discovery**: R0.2 assumed `ThesisService` exposed per-field mutator methods. It does not (shipped `thesis_service.py` has only `load_thesis`, `bootstrap_from_idea`, markdown sync helpers). R2 patch engine now uses **whole-Thesis replace** via existing `repo.update_thesis_artifact()` — same pattern as `routes.py:1440` `update_thesis_section`. Simpler engine, no mutator wiring required.

**Ready for Codex R2 review.**

### R2.1 — Codex R2 response (2026-04-23)

Codex R2 verdict: **7-of-8 R1 blockers PASSed** (import cycle, 21 typed op classes, PT identity, MBC FK, MBC method widen, dry-fold semantics, MCP classifier location all verified by local execution). **1 remaining blocker + 3 nits** addressed in R2.1:

**Remaining blocker — watcher lock gap**:
- R2 had sub-phase A-prereq wrapping `update_thesis_section` route (routes.py:1440) in `_handoff_lock`. Codex R2 grepped further and found a second unlocked Thesis writer: `on_watcher_markdown_change()` at `thesis_service.py:215` calls `repo.upsert_thesis_from_markdown()` with no lock. Markdown watcher can race `apply_patch_ops` and invalidate the plan's stale-overwrite argument.
- R2.1 extends sub-phase A-prereq to also wrap `on_watcher_markdown_change()` in `_handoff_lock` — now ALL shipped Thesis writers share the serialization contract. §1.2 expanded to document both writers + explicit serialization-contract invariant. Added boundary test `test_lock_coverage_boundary` that enumerates shipped writers and asserts lock acquisition.

**Nits**:
- §13 success criteria scrubbed: "All 20 op classes wired to ThesisService mutators" → "21 concrete op classes handled by `_apply_op_to_virtual`; no mutators required (whole-Thesis replace)". "MBC ↔ MI linkage via FK is valid" → "TEXT column (no FK); `mbc_pruned` flag surfaces dangling provenance".
- §9.2 orchestrator code sketch updated to shipped signature `(self, handoff_id, user_id, business_model=None)` — R0.2 invented an `mbc` positional arg that doesn't exist.
- §11.1 Scenario 4 rewritten for dry-fold semantics: "forces a ThesisService mutator to raise" → "produces a Pydantic re-validation failure on the virtual Thesis during fold"; note that whole-Thesis replace means no intermediate mutator writes to roll back.

**Ready for Codex R3 review.**

### R2.2 — Codex R3 response (2026-04-23)

Codex R3 verdict: **watcher blocker PASS**, but contract over-reach caught: R2.1's "ALL Thesis writers share the lock" was too broad — shipped repo has writers on `thesis_links`, `thesis_scorecards`, `thesis_decisions_log` that don't need to serialize against patch engine (orthogonal tables, not shared-slice content). R2.2 narrows the contract:

**Contract refinement**:
- **In scope (must hold lock)**: any caller of `ResearchRepository._persist_thesis_payload()` — the single authoritative write sink for shared-slice content on the `theses` row. Shipped callers outside the lock: (1) `update_thesis_section` route, (2) `on_watcher_markdown_change`, (3) `update_thesis_parent_snapshot`.
- **Out of scope**: writers to `thesis_links`, `thesis_scorecards` (separate tables, don't race patch engine). `thesis_decisions_log` already lock-serialized via `thesis_log_helpers.py:99-121`.
- **Boundary test** `test_lock_coverage_boundary` uses AST scan on `_persist_thesis_payload` callers with explicit allowlist for in-lock-private-helpers — sound, not over-broad.

A-prereq now wraps 3 writers (up from 2 in R2.1); §1.2, §2 (sub-phase table), §8.3 claims, §13 cross-plan integrity all updated.

**Remaining R3 nits swept**:
- §8.3 — "NO changes to `thesis_service.py`" clarified: patch engine adds no new methods, but A-prereq modifies the file for lock wraps.
- §11.1 Scenarios 1 & 2 — `build_and_annotate(mbc)` corrected to shipped signature `(handoff_id, user_id, business_model=None)`.
- §6.4 + §8.4 test descriptions — "all 20 ops" → "all 21 concrete op classes (20 logical ops)" for consistency with §6.2 enumeration.

**Ready for Codex R4 review.**

### R2.3 — Codex R4 response (2026-04-23)

Codex R4 verdict: contract over-reach caught (again) — R2.2's "exempt thesis_links/thesis_scorecards because separate tables" was wrong. Codex verified via AST scan + `_hydrate_thesis_row` read:
- `_hydrate_thesis_row` at `repository.py:1264` folds `model_links` AND `scorecard` back into the thesis payload
- `upsert_thesis_link`, `remove_thesis_link`, `save_scorecard` ALL call `_persist_thesis_payload` directly
- Also: `update_thesis_parent_snapshot` has a 4th entry point via `patch_file` → `update_file` rename path (not just `on_parent_rename`)

**R2.3 resolution**: commit to the comprehensive contract. **All 6 `_persist_thesis_payload` callers wrap `_handoff_lock` at the repository method level** (not at each route — cleaner, single-point-of-enforcement). Single exemption: `append_decisions_log_entry` already uses the equivalent thesis-log flock (Codex R3 verified same primitive). Sub-phase A-prereq duration bumps 0.5 → 1 day. Scope: ~60 lines in `repository.py` + up to 6 concurrency tests + AST boundary test.

§1.2 + §2 sub-phase table + §13 cross-plan integrity all updated to match comprehensive contract.

**Remaining R3 nits** (§6.2 code sketch + §6 union comment) — changed "all 20 ops" to "all 20 logical ops / 21 concrete classes" for consistency.

**Ready for Codex R5 review.**

### R2.4 — Codex R5 response + architectural pivot (2026-04-23)

Codex R5 returned FAIL on R2.3. The lock-expansion approach was architecturally wrong:
- `fcntl.flock` is not re-entrant → `finalize_handoff`, `_persist_shared_slice_write`, `apply_process_template` (all holding the lock already) would deadlock against wrapped methods. Codex local-verified the `EAGAIN` behavior.
- `update_file()` does `BEGIN IMMEDIATE → call method` whereas patch engine does `lock → BEGIN IMMEDIATE`. Wrapping `update_thesis_parent_snapshot` at the method level would invert the order and risk deadlock.
- `append_decisions_log_entry` exemption was wrong at the repository-method level — direct internal callers bypass the helper.

**Decision**: pivot to **optimistic concurrency control** (§1.2 rewritten). The R2.1-R2.3 lock-expansion design is dropped in its entirety. Replaced with:
- `version INTEGER NOT NULL DEFAULT 0` column on `theses` (v8 migration).
- One-line edit in `_persist_thesis_payload`: `version = version + 1` on write. All 7 existing writers participate automatically — no audit burden, no skip-lock flag, no lock-order discipline.
- Patch engine (§3.4, §8.2) reads version at dry-fold, writes `UPDATE ... WHERE version = $read_version`. CAS miss → `PatchStaleError` → bounded retry (3 attempts, 50ms backoff). Retry exhaustion → `PatchStaleRetryExhaustedError` surfaces via MCP classifier + agent flag.
- `_handoff_lock` is UNCHANGED — continues serving handoff lifecycle coordination for plan #2/#5. Patch engine does NOT acquire it.

**Bonus**: OCC strictly improves shipped safety. Today's concurrent writers (link, scorecard, watcher, rename) race each other silently — last-writer-wins. After OCC, the loser gets a typed error and can retry.

**Sections rewritten**: §1.2 (scope addition 2 — OCC block replaces the 6-writer lock table), §2 (A-prereq row + E row updated), §3.4 (transactionality paragraph), §3.6 (Plan #5 alignment bullet), §7 (v8 migration adds `version` column), §8.2 (pipeline + steps 4-6 rewrite for OCC), §8.3 (files + new repo methods), §8.4 (4 new OCC tests replace lock tests), §10.4 (`_THESIS_ERROR_TYPES` gains `patch_stale_retry_exhausted`), §10.3 (new agent flag), §11.1 (Scenarios 7 + 9 rewritten), §13 (cross-plan integrity bullet).

**A-prereq scope**: ~20 lines + 3 OCC tests (0.5 day). Down from R2.3's ~60 lines + 6 tests + AST boundary test (1 day).

**Ready for Codex R6 review.**

### R2.5 — Codex R6 response (2026-04-24)

Codex R6 returned FAIL on R2.4 with two findings:

**Big discovery (Blocker 1)**: R2.4's OCC design specified adding `theses.version INTEGER NOT NULL DEFAULT 0` in v8 and editing `_persist_thesis_payload` to bump it. Codex local-verified the entire thing is already shipped at v7:
- `theses.version INTEGER NOT NULL DEFAULT 1` at `repository.py:54,61`
- `_persist_thesis_payload` already bumps on every write at `repository.py:1302` (via `increment_version: bool = True` default; grep confirmed no caller passes `False`)
- `Thesis` Pydantic model already carries `version: int = Field(default=1, ge=1)` at `schema/thesis.py:222`

**R2.5 simplification**: plan #6's OCC scope shrinks to JUST adding the new CAS method `update_thesis_artifact_if_version_matches`. No v8 migration work for OCC. No edit to `_persist_thesis_payload`. No edit to `Thesis`. A-prereq is now exclusively MBC method widen (~0.25 day). Patch engine's CAS method ships in sub-phase E.

**Stale active references (Blocker 2)**: Codex R6 named 5 places where active plan text still specified the lock/SAVEPOINT model. R2.5 swept them:
- §2 sub-phase C row: "all 20" → "all 21 concrete op classes (20 logical ops)"
- §8.4 `test_apply_is_transactional`: SAVEPOINT language replaced with dry-fold-halts-before-CAS
- §11.1 Scenario 4: "dry-fold failure under lock" → "dry-fold failure halts before CAS"
- §13 success criteria: "dry-run OR lock+apply+audit" → "dry-run OR CAS-write+audit, with bounded retry"
- §13 transactional invariants: SAVEPOINT rollback language → dry-fold-halts-before-CAS

**Nit clarifications applied**:
- §13 "bonus side effect" overreach — R2.5 clarified that other shipped writers bump version on writes but DO NOT CAS-check themselves. They still last-writer-wins against each other; plan #6 only makes the patch engine CAS-safe. Future hardening of other writers is out of scope.
- §11.1 Scenario 7 — explicitly differentiated two retry sub-outcomes: (a) transient CAS miss retries cleanly → carry `retry_count=N`; (b) retry dry-fold hits a real domain conflict → surface the *domain* error class directly (`MissingStableIdError` / `PatchBatchConflictError`), NOT `PatchStaleRetryExhaustedError`. The exhaustion error is reserved for pathological CAS contention only.

**A-prereq scope after R2.5**: MBC method widen ONLY. ~0.25 day. Patch engine CAS method + retry loop live in sub-phase E.

**Ready for Codex R7 review.**

### R2.6 — Codex R7 response (2026-04-24)

Codex R7 returned FAIL on a narrow but real residual-staleness finding + two nits. All addressed:

**Blocker**: §8.3 files list still had R2.4-era claims that A-prereq would (a) add the OCC column, (b) edit `_persist_thesis_payload` to bump version, (c) add `load_thesis_with_version` + `update_thesis_artifact_if_version_matches` methods. After R2.5 we established (a)+(b) are already shipped in v7 and `load_thesis_with_version` is redundant (existing `get_thesis_by_id` returns version). R2.6 rewrites §8.3 to match: A-prereq has zero OCC work; sub-phase E owns ONE new method `update_thesis_artifact_if_version_matches`.

**Nit 1 (CAS method write shape)**: R2.5 described the new CAS method's SQL without enumerating the full write-shape of the existing `_persist_thesis_payload` sink. Codex flagged that the existing sink writes 7 columns (`ticker`, `label`, `version`, `updated_at`, `markdown_path`, `artifact_json`, `schema_version`), not just `artifact_json` + `version`. R2.6 §8.3 now pins the full column list — CAS method must mirror it to keep write semantics consistent.

**Nit 2 (total estimate)**: "~12 days (A-prereq adds 0.5 day vs R0.2)" was stale — A-prereq is now 0.25 day. R2.6 corrects to ~11.75 days.

**Ready for Codex R8 review.**

### R2.7 — Codex R8 response (2026-04-24)

Three residual active-section stale refs swept:
- §8.2 pipeline step 2: `repo.load_thesis_with_version(thesis_id)` → `repo.get_thesis_by_id(thesis_id)` (the method we settled on in R2.6; the stale reference at line 1092 had been missed).
- §13 patch engine success criterion: "whole-Thesis replace via existing `repo.update_thesis_artifact`" → "via new `repo.update_thesis_artifact_if_version_matches` (OCC CAS, §8.3)".
- §1.2 footer: "Both additions ship in sub-phase A-prereq" → explicit split — MBC widen in A-prereq, OCC work in E.

**Nit applied (Codex R8)**: §8.3 now directs the new CAS method to reuse a shared private helper `_prepare_thesis_row_fields(thesis, row)` extracted from `_persist_thesis_payload` rather than reimplement normalization (`_coerce_thesis_input`, label normalization, markdown-path derivation, `updated_at` + `schema_version` stamping) ad hoc. Eliminates drift risk between CAS writes and existing sink writes.

**Ready for Codex R9 review.**

## 17. Ship log

Plan #6 is **SHIPPED** (2026-04-24) across two repos.

**AI-excel-addin** (branch `feat/plan-6-model-insights`):
- `fa02ce9` — A-prereq (MBC `ValuationMethod` widen)
- `eb02369` — A+C (`ModelInsights` + `HandoffPatchOp` schemas, 21 concrete op classes, `threshold_direction` fix)
- `0b073dd` — B (`PriceTarget`)
- `2f5ab7e` — D (v8 migration + `ModelInsights` storage + service + UUIDv5 helpers)
- `29750e6` — E (OCC patch engine + dry-fold + CAS)
- `882abb5` — F (studio orchestrator emit hook)
- `e799667` — G part 2 (HTTP route handlers)
- `429f832` — H (E2E integration tests + skill contract map)
- `8611733` — snapshot regeneration cleanup

**risk_module**:
- `99ee8301` — docs (R2.8 plan doc + V5 ship notes) landed on `main`
- `4d88846d` — G part 1 (MCP surface — 4 tools + 7 agent flags + 8 classifier entries + 8 typed errors) on branch `feat/plan-6-mcp-surface`

**Key architectural learning**:
- 10 Codex review rounds (R1–R10) converged on the OCC pivot at R2.4: retrofitting `_handoff_lock` across writers deadlocks; CAS on `theses.version` isolates concurrency safety to the patch engine.
