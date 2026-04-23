# Plan #5 — `ProcessTemplate` v1.0 (Investment Schema Unification)

**Status**: ✅ **PASS (Codex R7)** — implementation-ready.

**Last revised**: 2026-04-22 (R6 → R7 PASS; convergence sequence R0 6 → R1 6 → R2 4 → R3 4 → R4 2 → R5 1 → R6 1 → R7 PASS. Full disposition in §15).

**Authoritative design reference**: `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §6.5 (Codex PASS R6). This plan implements what §6.5 designed.

**Companion docs**:
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` (skill consumers)
- `docs/planning/completed/INVESTMENT_IDEA_INGRESS_PLAN.md` (plan #4 — supplies `suggested_process_template_id` hint)
- `AI-excel-addin/docs/planning/completed/HANDOFF_ARTIFACT_V1_1_PLAN.md` (plan #2 — shipped `HandoffArtifact.process_template_id` field)

**Closes**: **G7** (Diligence not configurable per investor process) and **G12** (Qualitative factor seed categories). §6.5 of master plan.

---

## 1. Purpose & scope

Ship a typed `ProcessTemplate v1.0` Pydantic contract + catalog + loader + **working consumers** that turn the `suggested_process_template_id` hint (persisted by plan #4) into concrete workspace behavior: seeded qualitative factors, required section completion, ordered diligence, valuation method allow-list, source coverage gates at finalize.

Specifically:

1. **`ProcessTemplate v1.0` Pydantic type** in `AI-excel-addin/schema/process_template.py` matching §6.5 shape with `frozen=True` immutability.
2. **Default catalog as YAML** (shipped-with-app, under `AI-excel-addin/config/process_templates/`) + **user-created templates in SQLite** (per-user `process_templates` table).
3. **Backend CRUD routes** for user-created templates — `GET/POST /process_templates`, `GET/PATCH/DELETE /process_templates/{id}`.
4. **Loader service** that unions YAML defaults + user-created DB rows, validates each, caches per user, invalidates on writes.
5. **`start_research(idea)` extension**: when `idea.suggested_process_template_id` resolves to a catalog hit, seed `Thesis.qualitative_factors[]` from template AND **mirror them into the draft `HandoffArtifact` via `build_draft_artifact_from_thesis()`** so `DiligenceService.get_state()` (which reads from artifact, NOT Thesis) surfaces them immediately.
6. **Diligence state + prepopulate integration**: `DiligenceService.get_state()` consults the applied template for section filtering + ordering; `prepopulate_*_section()` helpers in `api/research/prepopulate.py` respect `section_config.required`.
7. **Finalize validation — G7/G12 CLOSURE**: `HandoffService.finalize_handoff()` (at `api/research/handoff.py:490`) consults the applied template and blocks finalization when (a) `section_config.min_completion` states aren't met, (b) `valuation_methods_allowed` doesn't include the artifact's declared `valuation.method` (live field at `schema/thesis_shared_slice.py:199-200` is `method: str | None`, FREE-FORM string not an enum), (c) `required_source_coverage` mins aren't met — counted by enumerating `artifact.sources[]` (typed `SourceRecord` list at `schema/thesis_shared_slice.py:287`) and bucketing unique `src_N` IDs by `.type` (live `SourceType = Literal["filing", "transcript", "investor_deck", "other"]` at `thesis_shared_slice.py:20`). Without a template, finalize behavior is unchanged (backwards compat).
8. **Explicit `set_process_template(research_file_id, template_id)` API** for post-hoc selection. Audit trail in `research_file_history` via `event_type='process_template_applied'`, same inline-SQL pattern as plan #4 sub-phase B's `migration_duplicate_draft_sweep` and the existing `metadata_update` pattern at `repository.py:1527`.
9. **risk_module MCP surface**: `list_process_templates`, `get_process_template`, `set_process_template`, plus agent flags for template-aware `start_research` + switch + unknown-template responses.
10. **Ship 4 default templates**: `value`, `compounder`, `special_situation`, `macro`.

### 1.1 Out of scope (v1)

- **Section-space redefinition** — `DILIGENCE_SECTION_KEYS` (9-tuple: `business_overview, thesis, catalysts, valuation, assumptions, risks, peers, ownership, monitoring`; relocating from `api/research/repository.py:226` to `schema/_shared_slice.py` per §4.1a) stays fixed. Template only overlays (required/order/min_completion). §6.5 R3 decision.
- `DriverCategory` enum customization per template.
- `QualitativeFactor` schema modification (`schema/thesis_shared_slice.py:241`).
- Template authoring UI (CRUD frontend). Plan #5 ships YAML-on-disk + SQLite-backed custom templates with backend CRUD APIs; frontend editor deferred.
- Template versioning migration (`schema_version` stays `"1.0"` throughout plan #5).
- Cross-user template sharing.
- Auto-selection of template based on idea heuristics. Plan #5 only applies templates when `suggested_process_template_id` is EXPLICITLY set on the idea, OR when analyst calls `set_process_template` post-hoc. No implicit selection.
- Widening legacy `start_research(ticker, label)` (non-idea path) to accept `template_id` — explicit `set_process_template` is the sole non-idea path. Codex Q2 confirmation.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| A | `ProcessTemplate` Pydantic type + validators | `schema/process_template.py`; subset/permutation validators + duplicate rejection for `section_config`; `min_completion ⊆ required` guard; factor-shape validators | ~1 day | — |
| B | Backend storage + CRUD routes + loader | `config/process_templates/*.yaml` (4 defaults, glob-loaded); v6→v7 per-user migration with `process_templates` table; 5 REST routes; `TemplateCatalog` loader + cache | ~2.5 days | A |
| C | `start_research(idea)` hook — Thesis seed + draft artifact mirror | `thesis_service.bootstrap_from_idea()` extended; factors mirrored into draft artifact via `handoff.build_draft_artifact_from_thesis()`; `research_service.start_research_from_idea` response includes `process_template_applied: bool` | ~1.5 days | A, B, plan #4 |
| D | Explicit template setter + audit | `POST /files/{id}/process_template` route; `research_service.set_process_template()`; inline SQL insertion of `research_file_history` row with `event_type='process_template_applied'` | ~1 day | B |
| E | Template-aware diligence state + prepopulate | `DiligenceService.get_state()` filters + orders sections per template (falls back to full 9-tuple natural order when no template); `api/research/prepopulate.py` scopes section processing to template's `required` | ~1.5 days | B, D |
| F | Finalize validation — G7/G12 closure | `HandoffService.finalize_handoff()` wraps full flow in `_handoff_lock`; `_assemble_artifact` → `_assemble_artifact_locked` (caller-owned lock) consults template; enforces `min_completion`, `valuation_methods_allowed`, `required_source_coverage`; raises 409 `template_requirements_unmet` with detail payload | ~1.5 days | B, D, E |
| G | risk_module MCP surface | 3 MCP tools + `TemplateSwitchError` gateway classifier + `TemplateRequirementsError` gateway classifier + 3 agent flags | ~1 day | A–F |
| H | Default catalog + E2E tests | 4 YAML templates; integration tests across ingress→research→thesis→diligence→finalize chain; boundary + pinned snapshot | ~1 day | A–G |
| I | Docs — `SKILL_CONTRACT_MAP.md` + `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §12 | Mechanical doc updates | ~0.5 day | H |

**Total**: ~11.5 days (up from R0 estimate of 9.5 after adding sub-phase F + expanding B/C/E).

### 2.1 Dependency graph

```
        A (Pydantic type)
           │
           ▼
        B (storage + CRUD + loader)       plan #4 (idea.suggested_process_template_id)
           │                                         │
      ┌────┼─────────────┐                           │
      ▼    ▼             ▼                           │
      C    D             E       ◄───────────────────┘
      │    │             │
      └────┴─────────────┘
           │
           ▼
           F (finalize validation)
           │
           ▼
           G (MCP surface)
           │
           ▼
           H (default catalog + E2E)
           │
           ▼
           I (docs)
```

---

## 3. Cross-cutting concerns

### 3.1 Scope fences (enforced as exit gates)

- **Section space immutable in v1**: `DILIGENCE_SECTION_KEYS` stays a 9-tuple. Template `section_config.required/order/min_completion` keys MUST be validated against that exact tuple. No template may reference a key outside it.
- **`DILIGENCE_SECTION_KEYS` relocates to `schema/_shared_slice.py`** (R3 blocker #4 resolution): R2 proposed importing the constant from `research.repository` into `schema/process_template.py`, which would create a `schema → repository → schema` cycle. Sub-phase A's first step MOVES the tuple from `repository.py:226` to `schema/_shared_slice.py` (already imported by repository at line 16 via `SHARED_SLICE_FIELD_PATHS` — zero new import direction). **6 pre-move live sites** (definition at `repository.py:226` + consumer at `repository.py:758` + `synthesis.py:6,33` + `diligence_service.py:8,67`) — post-move they all resolve to the single canonical definition via `repository.py`'s re-export. Full inventory + steps in §4.1a. Additive migration — no behavior change.
- **`QualitativeFactor` shape immutable**: plan #5 seeds instances (`category`, `label`, `assessment` [required str], `rating` [ConfidenceLevel | None], `data` [dict | None], `source_refs` [list]) but does not add fields to `schema/thesis_shared_slice.py:241`.
- **Plan #2's `HandoffArtifact.process_template_id` field is authoritative**: plan #5 writes via existing `repository.update_process_template_id()` at `repository.py:2643`. `_HANDOFF_ONLY_FIELD_KEYS` frozenset at `repository.py:256` already includes it.
- **Plan #4's `InvestmentIdea.suggested_process_template_id` shape is authoritative**: plan #5 reads it; does NOT add a parallel idea-side template field.
- **Factor mirroring invariant**: when factors are written to Thesis, they MUST be mirrored into the draft artifact via `api/research/handoff.build_draft_artifact_from_thesis()` (live helper at `handoff.py:381`) so `DiligenceService.get_state()` (at `diligence_service.py:49-84`, reads `artifact.qualitative_factors` line 82) surfaces them without waiting for a separate sync.
- **Plan #2 finalize-lock coverage extension** (R4 blocker #1 resolution — lock ownership shifts to `finalize_handoff()` + `_handoff_lock`): sub-phase F rewrites `HandoffService.finalize_handoff()` to acquire `_handoff_lock()` at its top and hold it through the entire flow (fresh-read draft → assemble → artifact write → status flip). R3's "3-line fresh-read inside `_assemble_artifact`" fixed only one of two race windows; this rewrite closes both by moving lock ownership UP the call chain to the top-level finalize flow. `_assemble_artifact` renames to `_assemble_artifact_locked` (caller owns lock; internal method no longer acquires). Live grep confirms `_assemble_artifact` has ONLY ONE caller — `finalize_handoff()` at `handoff.py:498`. `create_new_version()` at `handoff.py:507` does NOT call `_assemble_artifact` — it calls `_build_validated_artifact` directly (which is unaffected by the rename). No API-break — internal method signature + lock-holding shift only. Details + code in §9.2.

### 3.2 Template identity

- `template_id` is a lower-snake-case string, regex `^[a-z][a-z0-9_]{2,63}$`, globally unique across YAML + user-created DB rows.
- YAML defaults use stable hand-picked IDs (`value`, `compounder`, `special_situation`, `macro`). Glob-discovered from `config/process_templates/*.yaml`; filename `X.yaml` MUST match `template_id=X` (validator fails load otherwise).
- **User-created template IDs**: caller supplies via `POST /process_templates` body. ID MUST match the regex AND MUST NOT collide with a YAML default. Backend route returns 409 `template_id_conflict` on collision.
- **No UUID** — template IDs are human-readable and typed freely into idea payloads. Diverges from plan #4's `idea_id` UUIDv5 by design: ideas are deterministic auto-minted from origin; templates are author-named.

### 3.3 Storage model

Two-tier:

**Tier 1 — YAML defaults** (`AI-excel-addin/config/process_templates/*.yaml`):
- Shipped with the app, read-only at runtime.
- Glob-discovered at app startup. Each file loaded via `yaml.safe_load()` → `ProcessTemplate.model_validate(dict)`. Filename == `template_id` enforced.
- Duplicate `template_id` across YAML files fails startup (fail-fast).
- Any invalid YAML fails startup with the path + Pydantic error for actionable debugging.
- Note: this is a NEW YAML-loading pattern in AI-excel-addin; no existing AI-excel-addin `config/` loader to reuse. (The `stress_scenarios.yaml` reference in the R0 draft was wrong — that file lives in risk_module, not AI-excel-addin.)

**Tier 2 — SQLite per-user templates** (new `process_templates` table on per-user DB, v6 → v7 migration at `_maybe_migrate()` — follow the exact pattern plan #4 sub-phase B used for v5 → v6):

```sql
CREATE TABLE IF NOT EXISTS process_templates (
  template_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  template_json TEXT NOT NULL,       -- full ProcessTemplate JSON (schema_version="1.0")
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_process_templates_updated
  ON process_templates(updated_at DESC);
```

**Loader precedence** (for the `TemplateCatalog.list()` + `get()` APIs): YAML default wins over user-created on `template_id` collision — loader FILTERS user rows whose IDs match a default. This is defense-in-depth because the CRUD route also rejects the collision at write time, but a partial-migration or pre-feature row could exist.

**Caching**: loader holds an in-memory dict `{user_id → {template_id: ProcessTemplate}}` for user templates. Defaults cached globally (one dict, shared). Per-user cache invalidated on `create/update/delete` via a direct `invalidate_user(user_id)` call from the repo write methods.

### 3.4 Seed factor application

Templates seed `qualitative_factors[]` onto the Thesis draft when `bootstrap_from_idea()` runs AND the idea carries a resolved `suggested_process_template_id`. Application rules:

1. **Fresh Thesis only**: if Thesis already exists for the research_file, seed factors are NOT applied (consistent with plan #4's Thesis-preservation policy). Analyst adds them manually via `POST /diligence/factors` if they switch template mid-flight.
2. **Each seed entry becomes a `QualitativeFactor`** with:
   - `id` = computed from `_recompute_next_factor_id(existing_factors)` at `handoff.py:398` (max+1 recomputation — preserves the live invariant that `id` is monotonic and derived from existing factor IDs, not from a counter)
   - `category` = `seed.category`
   - `label` = `seed.label`
   - `rating` = `seed.default_rating` (nullable per `QualitativeFactor` schema)
   - `assessment` = `seed.guidance` (REQUIRED string on `SeedQualitativeFactor` per §4.2 — ensures `QualitativeFactor.assessment` required-str is always satisfied; see Codex R1 blocker #6)
   - `data` = `seed.default_data_shape` (nullable dict per `QualitativeFactor.data`)
   - `source_refs` = `[]` (seeded factors have no source provenance — analyst adds later)
3. **Artifact mirror** (R1 blocker #2 resolution): after seeding Thesis, call `handoff.build_draft_artifact_from_thesis(repo, file_row=..., handoff_row=draft_handoff, draft_artifact=existing_draft_artifact, thesis_row=seeded_thesis)` to rebuild the draft artifact. This carries `qualitative_factors` through the shared-slice mirroring path that `HandoffService._build_validated_artifact()` uses today. `DiligenceService.get_state()` then surfaces the seeded factors from `artifact.qualitative_factors` (line 82) without any extra sync.
4. **Idempotency** (`set_process_template` path, sub-phase D): re-applying the SAME template is a no-op on factors — existing factors matched by `(category, label)` tuple are skipped (Codex Q1 confirmation). New factors from a DIFFERENT template add to the union (analyst prunes unwanted manually).
5. **Duplicate seed rejection**: `SeedQualitativeFactor` list validator rejects duplicate `(category, label)` tuples at validation time (Codex Q4 confirmation) — catches YAML author mistakes early.

### 3.5 HandoffArtifact `process_template_id` propagation

Field lives on `HandoffArtifact v1.1` at `schema/handoff.py:140` (plan #2 shipped). Plan #5 seeds it via three paths:

1. **`start_research(idea)` with resolved template** (sub-phase C): after draft-handoff creation, call `repo.update_process_template_id(handoff_id, template_id)` (live method at `repository.py:2643`).
2. **`set_process_template(user_id, research_file_id, template_id)` explicit call** (sub-phase D): look up LATEST handoff via `repo.get_latest_handoff(research_file_id, status=None)` (live method; must pass `status=None` explicitly to include finalized/superseded — default is `status="draft"` per `repository.py:2220`). Inspect the returned row's `.status`: (a) None → 409 `no_draft_handoff`, (b) status != "draft" → 409 `cannot_change_finalized_template`, (c) status == "draft" → proceed. Call same update hook. The R0 draft's `get_draft_handoff(...)` doesn't exist as a separate method.
3. **Finalize pass-through** (plan #2's `handoff.py` finalize path at `finalize_handoff()` line 490): finalized artifact inherits draft's `process_template_id` via `_assemble_artifact_locked()` → `_build_validated_artifact()` (rename per §9.2). Plan #5 ADDS validation gates in `_assemble_artifact_locked()` (sub-phase F) but does NOT alter the propagation of the field itself.

### 3.6 Cross-plan alignment

- **Plan #1 (Thesis)**: plan #5 writes to `Thesis.qualitative_factors[]` (existing shared-slice field). Does not add Thesis-only fields. Markdown round-trip stays compatible (serializer/parser for `qualitative_factors` already at `schema/thesis_markdown.py:129,623,1151`).
- **Plan #2 (HandoffArtifact v1.1)**: plan #5 consumes `process_template_id` field at `handoff.py:140`; uses existing `update_process_template_id()` at `repository.py:2643`. Finalize pass-through unchanged.
- **Plan #4 (InvestmentIdea)**: plan #5 resolves `idea.suggested_process_template_id` via catalog lookup. Unknown template_id → warning log + proceed with legacy no-template behavior (does NOT fail start_research — preserves idea ingress robustness).
- **Plan #9 (future, Knowledge Wiki)**: unblocked by plan #5.

---

## 4. Sub-phase A — `ProcessTemplate` Pydantic type + validators

### 4.1 Goal

Pydantic v2 `ProcessTemplate` + nested types in `AI-excel-addin/schema/process_template.py` matching §6.5 shape. `frozen=True` via explicit `ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True, frozen=True)` — mirrors `InvestmentIdea`'s inline pattern at `schema/investment_idea.py:23`. (The R0 draft cited a `CONTRACT_CONFIG` constant that doesn't exist in `schema/_shared_slice.py`.)

### 4.1a Prerequisite: relocate `DILIGENCE_SECTION_KEYS` to schema layer

Before writing `process_template.py`, move the tuple from `api/research/repository.py:226` to `schema/_shared_slice.py` as a new top-level constant (and re-export via `schema/__init__.py`). This is a **purely mechanical import-direction fix** — plan #5 proper (this sub-phase A) cannot land without it because `schema/process_template.py` imports the constant, and the schema layer currently cannot import from `api/research/` without inducing a cycle (repository.py imports schema at line 16).

Full live hit inventory pre-move (R4 should-fix #2 correction — R3 miscounted at 4):

1. `api/research/repository.py:226` — definition (will become re-export `from schema._shared_slice import DILIGENCE_SECTION_KEYS`)
2. `api/research/repository.py:758` — consumer inside `_normalize_section_wrapper()` (imports via module scope — no change needed once repository.py re-exports)
3. `api/research/synthesis.py:6` — import
4. `api/research/synthesis.py:33` — usage
5. `api/research/diligence_service.py:8` — import
6. `api/research/diligence_service.py:67` — usage

Steps:
1. Add `DILIGENCE_SECTION_KEYS = ("business_overview", "thesis", "catalysts", "valuation", "assumptions", "risks", "peers", "ownership", "monitoring")` to `schema/_shared_slice.py`.
2. Add `DILIGENCE_SECTION_KEYS` to `schema/__init__.py` re-exports.
3. `repository.py:226` changes from defining the tuple to re-exporting it: `from schema._shared_slice import DILIGENCE_SECTION_KEYS` (added to the existing schema-imports block at line 16). Remove the literal definition. Sites 2, 3, 5 continue to import from `research.repository` unchanged — minimal-diff style, no functional impact.
4. Optional (defer unless needed): switch sites 3 + 5 to import from `schema._shared_slice` directly. Not required for plan #5 correctness.

Verification: `grep -rn DILIGENCE_SECTION_KEYS AI-excel-addin` after the move shows the same 6 sites (+1 for the new definition in `schema/_shared_slice.py`, but the old definition at `repository.py:226` becomes a re-export, so total grep count is 7). Each reference resolves to the single canonical definition. No behavior change; existing tests stay green.

### 4.2 Design

```python
# AI-excel-addin/schema/process_template.py
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal

# DILIGENCE_SECTION_KEYS lives at schema/_shared_slice.py (moved there by sub-phase A's
# first step — was at api/research/repository.py:226 pre-plan-5, but that direction
# created a schema→repository→schema import cycle). Importing from schema/_shared_slice
# is safe because repository.py already imports from schema at line 16.
from schema._shared_slice import DILIGENCE_SECTION_KEYS
_DILIGENCE_KEYS = frozenset(DILIGENCE_SECTION_KEYS)

_FROZEN_CONTRACT = ConfigDict(
    extra="forbid",
    str_strip_whitespace=True,
    populate_by_name=True,
    frozen=True,
)

SectionKey = Literal[
    "business_overview", "thesis", "catalysts", "valuation", "assumptions",
    "risks", "peers", "ownership", "monitoring",
]
CompletionState = Literal["empty", "draft", "confirmed"]
StrategyBias = Literal["value", "special_situation", "macro", "compounder"]
HoldingPeriodBias = Literal["near_term", "medium", "long_term"]
# valuation_methods_allowed is list[str] (free-form). Live Valuation.method at
# schema/thesis_shared_slice.py:200 is `method: str | None`, NOT an enum —
# prepopulate.py:323 emits "relative", thesis_scorecard uses "dcf"/"multiples"/etc.
# Template authors can allow any strings that show up on live artifacts.


class InvestorProfile(BaseModel):
    strategy_bias: StrategyBias | None = None
    holding_period_bias: HoldingPeriodBias | None = None
    style_notes: str | None = None
    model_config = _FROZEN_CONTRACT


class SectionConfig(BaseModel):
    required: list[SectionKey] = Field(default_factory=list)
    order: list[SectionKey] = Field(default_factory=list)
    min_completion: dict[SectionKey, CompletionState] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_structure(self) -> "SectionConfig":
        # Subset/permutation checks. Literal covers the key universe at the type
        # level; we layer structural invariants on top.
        if len(set(self.required)) != len(self.required):
            raise ValueError("required contains duplicate section keys")
        if self.order:
            if len(set(self.order)) != len(self.order):
                raise ValueError("order contains duplicate section keys")
            if set(self.order) != set(self.required):
                raise ValueError("order must be a permutation of required (same set, any order)")
        if not set(self.min_completion).issubset(set(self.required)):
            unknown = set(self.min_completion) - set(self.required)
            raise ValueError(f"min_completion keys not in required: {sorted(unknown)}")
        return self

    model_config = _FROZEN_CONTRACT


class SeedQualitativeFactor(BaseModel):
    category: str = Field(min_length=1)
    label: str = Field(min_length=1)
    guidance: str = Field(min_length=1)           # REQUIRED — maps to QualitativeFactor.assessment (required str)
    default_rating: Literal["high", "medium", "low"] | None = None
    default_data_shape: dict | None = None
    model_config = _FROZEN_CONTRACT


class RequiredSourceCoverage(BaseModel):
    # Field names aligned to live SourceType = Literal["filing","transcript","investor_deck","other"]
    # at schema/thesis_shared_slice.py:20. Counted by enumerating unique src_N IDs in
    # artifact.sources[] (SourceRecord list at thesis_shared_slice.py:287) bucketed by .type.
    # NO "industry_ref" bucket exists in the live enum — R2 blocker #1 correction.
    min_filings: int | None = Field(default=None, ge=0)
    min_transcripts: int | None = Field(default=None, ge=0)
    min_investor_decks: int | None = Field(default=None, ge=0)
    min_other: int | None = Field(default=None, ge=0)
    model_config = _FROZEN_CONTRACT


class ProcessTemplate(BaseModel):
    template_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    name: str = Field(min_length=1)
    description: str | None = None
    investor_profile: InvestorProfile | None = None
    section_config: SectionConfig = Field(default_factory=SectionConfig)
    seed_qualitative_factors: list[SeedQualitativeFactor] = Field(default_factory=list)
    valuation_methods_allowed: list[str] = Field(default_factory=list)      # free-form; matches Valuation.method str|None
    required_source_coverage: RequiredSourceCoverage | None = None
    schema_version: Literal["1.0"] = "1.0"

    @field_validator("seed_qualitative_factors")
    @classmethod
    def _reject_duplicate_seeds(cls, value: list[SeedQualitativeFactor]) -> list[SeedQualitativeFactor]:
        seen: set[tuple[str, str]] = set()
        for seed in value:
            key = (seed.category, seed.label)
            if key in seen:
                raise ValueError(f"duplicate seed_qualitative_factors entry: category={seed.category!r}, label={seed.label!r}")
            seen.add(key)
        return value

    @field_validator("valuation_methods_allowed")
    @classmethod
    def _reject_duplicate_valuation_methods(cls, value: list[str]) -> list[str]:
        # Each entry also non-empty str (free-form but must be meaningful)
        stripped = [v.strip() for v in value]
        if any(not v for v in stripped):
            raise ValueError("valuation_methods_allowed entries must be non-empty strings")
        if len(set(stripped)) != len(stripped):
            raise ValueError("valuation_methods_allowed contains duplicates")
        return stripped

    model_config = _FROZEN_CONTRACT
```

### 4.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `AI-excel-addin/schema/process_template.py` | `ProcessTemplate` + nested types | ~220 |
| `AI-excel-addin/schema/__init__.py` | Re-export `ProcessTemplate` + all nested types | ~+6 |
| `AI-excel-addin/tests/schema/test_process_template.py` | Pydantic unit tests | ~280 |

### 4.4 Tests (~26)

- Required-field validation (`template_id`, `name`) + happy path (2)
- `template_id` regex (accept + reject — empty, uppercase, too short, too long, special chars) (3)
- `section_config.required` subset/typing via `Literal` → invalid key rejected at type check (1)
- `section_config.order` is permutation of `required` (happy + disagreement reject + empty-order permitted) (3)
- `section_config.required` and `section_config.order` reject DUPLICATES (2)
- `section_config.min_completion` keys ⊆ `required` (1 positive + 1 negative for key outside required) (2)
- `valuation_methods_allowed` rejects duplicates + empty strings (free-form `list[str]` per R2 blocker #4 alignment with live `Valuation.method str | None`) (2)
- `seed_qualitative_factors` rejects duplicate `(category, label)` tuples (1)
- `SeedQualitativeFactor.guidance` REQUIRED (empty/missing rejected — ensures downstream `QualitativeFactor.assessment` required-str always satisfied) (2)
- `required_source_coverage` non-negative integer validators across all 4 live SourceType buckets (`min_filings`, `min_transcripts`, `min_investor_decks`, `min_other`) (2)
- `schema_version` pinned to `"1.0"` (1)
- All types frozen — mutation attempts raise (1)
- **Boundary test** (triple sync): `SectionKey` Literal values == `_DILIGENCE_KEYS` frozenset == `DILIGENCE_SECTION_KEYS` tuple content (all three in lockstep) (1)
- **Boundary test** (triple sync): `CompletionState` Literal values == live `VALID_DILIGENCE_COMPLETION_STATES` at `repository.py:222` (1)
- JSON round-trip preserves shape (1)
- `model_json_schema()` deterministic output for §10 snapshot pinning (1)

---

## 5. Sub-phase B — Backend storage + CRUD routes + loader

### 5.1 Goal

Ship the catalog storage layer, CRUD REST API, and loader service.

### 5.2 Storage & loader

**YAML layout** (glob-discovered at startup):
```
AI-excel-addin/config/process_templates/
  value.yaml
  compounder.yaml
  special_situation.yaml
  macro.yaml
```

Each file = one template. Filename stem MUST equal `template_id`. Duplicate template_id across YAML files fails startup.

**SQLite schema** per §3.3. v6→v7 migration in `_maybe_migrate()` mirrors plan #4's v5→v6 pattern: check-existence-before-create for columns/tables/indexes; update schema_version row in same transaction.

**`TemplateCatalog` loader** (new at `AI-excel-addin/api/research/template_catalog.py`):

```python
class TemplateCatalog:
    def __init__(self, repo_factory: ResearchRepositoryFactory):
        self._defaults: dict[str, ProcessTemplate] = _load_yaml_defaults()
        self._repo_factory = repo_factory
        self._user_cache: dict[str, dict[str, ProcessTemplate]] = {}
        self._cache_lock = threading.RLock()

    # Public API takes user_id EXPLICITLY — matches the dominant request-model pattern.
    # Research routes thread user_id via `user_id: str = Depends(get_trusted_user_id)` at
    # routes.py:81 (applied to every route). Services receive it directly:
    # bootstrap_from_idea(user_id, ...), HandoffService(repo), DiligenceService(repo).
    # The only route that uses memory_user_scope is the MBC route at routes.py:962 —
    # because build_model_context() calls get_current_user_id() internally. Most services
    # do NOT install memory scope, so a get_current_user_id()-based catalog would fail
    # silently. (R3 blocker #2 resolution — reverts R2's incorrect scope-context-based design.)

    def get(self, user_id: str, template_id: str) -> ProcessTemplate | None:
        if template_id in self._defaults:
            return self._defaults[template_id]
        return self._user_templates(user_id).get(template_id)

    def list(self, user_id: str) -> list[ProcessTemplate]:
        user = self._user_templates(user_id)
        safe_user = {tid: t for tid, t in user.items() if tid not in self._defaults}
        return [*self._defaults.values(), *safe_user.values()]

    def invalidate_user(self, user_id: str) -> None:
        with self._cache_lock:
            self._user_cache.pop(user_id, None)

    def _user_templates(self, user_id: str) -> dict[str, ProcessTemplate]:
        with self._cache_lock:
            if user_id in self._user_cache:
                return self._user_cache[user_id]
            repo = self._repo_factory.get(user_id)
            rows = repo.list_process_templates()
            parsed = {
                row["template_id"]: ProcessTemplate.model_validate_json(row["template_json"])
                for row in rows
            }
            self._user_cache[user_id] = parsed
            return parsed
```

Module-level factory `get_template_catalog()`. Repo `create/update/delete_process_template()` invalidate the per-user cache after each write by calling `catalog.invalidate_user(repo._current_user_id())`. All other call sites pass user_id as explicit parameter matching their own signatures (see §6.2, §7.2, §8.2, §9.2).

### 5.3 Backend REST routes (new — R1 blocker #5 resolution)

All routes under the existing `/api/research` prefix, same `@router.<verb>` decorator pattern as `routes.py:523+`:

| Method | Path | Body | Response | Errors |
|---|---|---|---|---|
| `GET` | `/process_templates` | — | Bare `ProcessTemplate[]` list (defaults + user) — matches live `GET /files` bare-list convention at `routes.py:523` | — |
| `GET` | `/process_templates/{template_id}` | — | `ProcessTemplate` object (bare) | 404 unknown |
| `POST` | `/process_templates` | `ProcessTemplate` (client supplies `template_id`) | Created `ProcessTemplate` (bare) | 409 `template_id_conflict` (collides with default or existing user), 422 invalid |
| `PATCH` | `/process_templates/{template_id}` | Partial ProcessTemplate (merges on top) | Updated `ProcessTemplate` (bare) | 404 unknown, 409 `cannot_modify_default` (YAML defaults read-only), 422 invalid after merge |
| `DELETE` | `/process_templates/{template_id}` | — | 200 with `{"deleted": true, "template_id": "..."}` body (R3 nit #1 — picked one contract; 204 deferred for consistency with `DELETE /files/{id}` at `routes.py:595-605` which also returns 200 with a body) | 404 unknown, 409 `cannot_delete_default` |

All write paths invalidate `TemplateCatalog` cache for the current user.

### 5.4 Files to create/modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/research/template_catalog.py` | **NEW** — `TemplateCatalog` + YAML loader + singleton factory | ~200 |
| `AI-excel-addin/api/research/repository.py` | v6→v7 migration + `create/update/delete/get/list_process_templates()` methods | ~+150 |
| `AI-excel-addin/api/research/routes.py` | 5 new REST routes per §5.3 | ~+140 |
| `AI-excel-addin/tests/api/research/test_repository_schema.py` | Extend with migration + method tests | ~+90 |
| `AI-excel-addin/tests/api/research/test_template_catalog.py` | **NEW** — catalog unit tests | ~+200 |
| `AI-excel-addin/tests/api/research/test_template_routes.py` | **NEW** — route tests | ~+180 |

### 5.5 Tests (~26)

- Fresh v7 schema creation: table + index present (2)
- v6→v7 migration: v6 fixture → migration runs → table created → idempotent re-run (3)
- YAML loader: loads 4 valid defaults (1); rejects malformed YAML with path in error (1); rejects `template_id` mismatch with filename (1); rejects duplicate template_ids across files (1)
- Catalog `get(user_id, template_id)`: default hit, user hit, miss (3)
- Catalog `list(user_id)`: returns defaults + user templates (1)
- Catalog cross-user isolation: user A's custom templates not visible to user B (regression — validates per-user cache keying) (1)
- Catalog `list()` filters user rows colliding with defaults (R1 should-fix #5) (1)
- Cache invalidation after create/update/delete (1)
- Route `POST /process_templates` happy path (1)
- Route `POST` collision with default → 409 `template_id_conflict` (1)
- Route `POST` collision with existing user template → 409 `template_id_conflict` (1)
- Route `GET /process_templates/{id}` hit + miss (2)
- Route `GET /process_templates` list includes defaults + user (1)
- Route `PATCH` on user template: partial merge validated (1)
- Route `PATCH` on default → 409 `cannot_modify_default` (1)
- Route `DELETE` on user template: row removed + cache invalidated (1)
- Route `DELETE` on default → 409 `cannot_delete_default` (1)
- Schema version row updated to v7 after migration (1)
- Rollback on mid-flight migration failure (schema_version stays v6) (1)

---

## 6. Sub-phase C — `start_research(idea)` hook — Thesis seed + draft artifact mirror + response flag

### 6.1 Goal

When `bootstrap_from_idea()` runs AND the idea carries `suggested_process_template_id`, (a) seed Thesis with template's `seed_qualitative_factors[]`, (b) **mirror seeded factors into the draft artifact via `build_draft_artifact_from_thesis()`** (R1 blocker #2), (c) set draft handoff's `process_template_id`, (d) surface `process_template_applied: bool` in the `start_research_from_idea()` response (R1 should-fix #3).

### 6.2 Design

Extend `AI-excel-addin/api/research/thesis_service.py:123` (`bootstrap_from_idea`):

```python
def bootstrap_from_idea(user_id: str, research_file_id: int, idea: InvestmentIdea) -> dict[str, Any] | None:
    validated_idea = InvestmentIdea.model_validate(idea)
    repo = get_repository_factory().get(user_id)
    if repo.get_thesis_by_research_file(int(research_file_id)) is not None:
        return None

    # Resolve template (if idea provides a hint). user_id is the explicit param to
    # bootstrap_from_idea — thread it through to the catalog.
    template: ProcessTemplate | None = None
    if validated_idea.suggested_process_template_id:
        template = get_template_catalog().get(user_id, validated_idea.suggested_process_template_id)
        if template is None:
            log.warning(
                "unknown process_template_id=%s on idea=%s; proceeding without template",
                validated_idea.suggested_process_template_id, validated_idea.idea_id,
            )

    # Seed qualitative_factors from template
    seeded_factors = (
        [_seed_factor_to_qualitative_factor(seed, next_id=i + 1) for i, seed in enumerate(template.seed_qualitative_factors)]
        if template else []
    )

    try:
        created = repo.create_thesis(
            int(research_file_id),
            {
                "thesis": {...},                       # unchanged from plan #4
                "from_idea": {...},                    # unchanged from plan #4
                "qualitative_factors": seeded_factors, # NEW
            },
        )
    except ValueError as exc:
        if "thesis already exists" in str(exc):
            return None
        raise

    save_thesis_markdown(Thesis.model_validate(created))

    # NEW: mirror seeded factors into the draft artifact + set process_template_id
    if template:
        file_row = repo.get_file(int(research_file_id))
        draft_handoff = repo.get_latest_handoff(int(research_file_id), status="draft")
        if draft_handoff is None:
            # start_research(idea) always creates a draft before bootstrap_from_idea;
            # if missing, something invariant-breaking happened. Surface.
            raise RuntimeError("start_research(idea) drew a blank draft handoff")
        draft_artifact = _artifact_from_row(draft_handoff, file_row=file_row)
        rebuilt = build_draft_artifact_from_thesis(
            repo,
            file_row=file_row,
            handoff_row=draft_handoff,
            draft_artifact=draft_artifact,
            thesis_row=created,
        )
        repo.update_handoff_artifact(int(draft_handoff["id"]), rebuilt)
        repo.update_process_template_id(int(draft_handoff["id"]), template.template_id)

    return created  # caller (research_service.start_research_from_idea) wraps it w/ template flag
```

Then in `api/research/research_service.py:start_research_from_idea()`, the response dict adds `process_template_applied: bool` — true iff a resolved template was applied (i.e., template was non-None AND thesis was freshly bootstrapped). Field threads through to the route response.

**Helper** `_seed_factor_to_qualitative_factor(seed: SeedQualitativeFactor, next_id: int) -> dict`:

```python
def _seed_factor_to_qualitative_factor(seed: SeedQualitativeFactor, next_id: int) -> dict[str, Any]:
    return {
        "id": next_id,
        "category": seed.category,
        "label": seed.label,
        "assessment": seed.guidance,                  # required-str on QualitativeFactor — guaranteed by §4.2 SeedQualitativeFactor.guidance required
        "rating": seed.default_rating,                # nullable
        "data": seed.default_data_shape,              # nullable dict
        "source_refs": [],
    }
```

Note `id` assignment: for fresh Thesis (all seeded factors from one template, no prior), IDs are 1..N linearly. The `_recompute_next_factor_id()` invariant (max+1 over existing IDs) is naturally satisfied here since there are no prior factors. If `set_process_template` later adds factors (sub-phase D), that path uses `_recompute_next_factor_id(existing_factors)` to avoid ID collisions.

### 6.3 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/research/thesis_service.py` | Extend `bootstrap_from_idea()` per §6.2 | ~+80 |
| `AI-excel-addin/api/research/research_service.py` | `start_research_from_idea()` response adds `process_template_applied: bool` | ~+15 |
| `AI-excel-addin/tests/api/research/test_start_research_from_idea.py` | Extend with template cases (the existing file from plan #4 sub-phase D) | ~+220 |

### 6.4 Tests (~18)

- Idea with `suggested_process_template_id=None`: behavior identical to pre-plan-5 (regression from plan #4 sub-phase D) (1)
- Idea with unknown `suggested_process_template_id`: Thesis seeded without factors, warning logged, `process_template_applied=false` in response, no error (2)
- Idea with valid default template: Thesis `qualitative_factors[]` matches seed count + mapping, `process_template_applied=true` in response (2)
- Seed factor mapping: `category/label/guidance→assessment/default_rating→rating/default_data_shape→data` correct (3)
- **Draft artifact `qualitative_factors` populated after bootstrap** (R1 blocker #2 coverage — `DiligenceService.get_state()` surfaces factors without separate sync) (1)
- Draft handoff `process_template_id` populated (1)
- Existing Thesis: bootstrap short-circuits, no factor seeding, no template_id change, `process_template_applied=false` (1)
- User-created template resolved via catalog (1)
- Idempotency: same idea twice → second call returns None (regression from plan #4) (1)
- `_recompute_next_factor_id` invariant holds on fresh seed (ids 1..N monotonic) (1)
- Seed factors appear in Thesis markdown round-trip (1)
- HandoffArtifact finalize pass-through preserves `process_template_id` (regression on plan #2 behavior) (1)
- Seed with `default_data_shape=None` → factor `data=None` (validates nullable mapping) (1)
- **Concurrency**: two concurrent `start_research(idea)` calls with SAME idea_id but DIFFERENT `suggested_process_template_id` — exactly one `research_files` row via plan #4 sub-phase B partial UNIQUE; winner's template_id survives; loser's template_id ignored (R1 should-fix #6) (1)

---

## 7. Sub-phase D — Explicit template setter + audit

### 7.1 Goal

Allow analysts to apply a template post-hoc. Record in `research_file_history` via `event_type='process_template_applied'`.

### 7.2 Design

**REST endpoint**: `POST /files/{research_file_id}/process_template` with body `{"template_id": str}`:
- 200: `{research_file_id, template_id, prior_template_id, handoff_id, seeded_factor_count}`
- 404: template_id unknown
- 422 `thesis_required_first`: Thesis doesn't exist yet — analyst must bootstrap or create Thesis first.
- 409 `no_draft_handoff`: no handoff exists at all (analyst hasn't called `activate_diligence()`).
- 409 `cannot_change_finalized_template`: latest handoff is finalized / superseded.
- 422: malformed request body.

**Single atomic repo helper** (R2 blocker #3 resolution — addresses race against `finalize_handoff`):

Define `ResearchRepository.apply_process_template(research_file_id, template_id, seed_factor_rows) -> dict[str, Any]` in `api/research/repository.py`. Runs the entire mutation under the same `_handoff_lock()` that `HandoffService.finalize_handoff()` now owns at its top level (per §9.2 rewrite) — ensures `set_process_template` can't interleave with finalize. Single `BEGIN IMMEDIATE` transaction wraps the DB writes. Method body:

```python
def apply_process_template(
    self,
    research_file_id: int,
    template_id: str,
    seed_factor_rows: list[dict[str, Any]],   # new factors dedup'd by (category, label) upstream
) -> dict[str, Any]:
    file_row = self.get_file(research_file_id)
    if file_row is None:
        raise ValueError("research file not found")

    with _handoff_lock(self, file_row=file_row):
        # R2 blocker #3 branch: distinguish "no handoff" from "latest is finalized"
        # by looking up WITHOUT a status filter first.
        # CRITICAL (R6 blocker): get_latest_handoff DEFAULTS status="draft" at
        # repository.py:2220 — must pass status=None EXPLICITLY to return
        # finalized/superseded handoffs too, otherwise FinalizedHandoffError branch
        # collapses into NoDraftHandoffError for finalized cases.
        latest_any = self.get_latest_handoff(int(research_file_id), status=None)
        if latest_any is None:
            raise NoDraftHandoffError(research_file_id=research_file_id)
        if latest_any["status"] != "draft":
            raise FinalizedHandoffError(
                research_file_id=research_file_id,
                status=latest_any["status"],
            )

        draft = latest_any                                           # it's a draft at this point
        thesis_row = self.get_thesis_by_research_file(int(research_file_id))
        if thesis_row is None:
            raise ThesisRequiredError(research_file_id=research_file_id)

        # Parse artifact from raw handoff row. get_latest_handoff returns sqlite3.Row
        # with artifact stored as JSON TEXT — use _artifact_from_row() from handoff.py
        # (the same helper HandoffService uses internally). Do NOT attempt draft["artifact"]
        # as a dict — it's JSON text and .get() on str raises.
        from research.handoff import _artifact_from_row
        hydrated_artifact = _artifact_from_row(latest_any, file_row=file_row)
        prior_template_id = hydrated_artifact.get("process_template_id") if isinstance(hydrated_artifact, dict) else None

        with self._conn() as conn:
            self._begin_immediate(conn)

            # Union seed_factor_rows into thesis.qualitative_factors (dedup by (category, label))
            existing_factors = list(thesis_row.get("qualitative_factors") or [])
            existing_keys = {(f["category"], f["label"]) for f in existing_factors}
            new_factors = [f for f in seed_factor_rows if (f["category"], f["label"]) not in existing_keys]
            next_id = _recompute_next_factor_id(existing_factors)
            for i, factor in enumerate(new_factors):
                factor["id"] = next_id + i                           # monotonic
            merged_factors = existing_factors + new_factors

            # Thesis write (R5 should-fix #1 resolution — concrete against live helpers):
            # _persist_thesis_payload() at repository.py:1236 ALREADY takes a conn as its
            # first parameter and writes the full thesis payload (version bump + updated_at
            # stamp + UPDATE theses SET ... via line 1264). We don't need a new
            # _update_thesis_qualitative_factors_tx helper — just call _persist_thesis_payload
            # directly with a payload that has merged_factors substituted:
            updated_thesis_payload = dict(thesis_row)        # start from the current row
            updated_thesis_payload["qualitative_factors"] = merged_factors
            self._persist_thesis_payload(                    # live helper; conn-scoped
                conn,
                thesis_row,
                updated_thesis_payload,
                increment_version=True,                      # version bump required per §7.2 (a)
            )
            # Decisions-log: _persist_thesis_payload does NOT append decisions_log on factor
            # updates (decisions_log writes are explicit via append_decisions_log at a
            # different call path). For template-seeded audit parity, apply_process_template
            # writes the research_file_history row below — that's the audit trail for this
            # action. Thesis-level decisions_log stays untouched.
            #
            # Markdown: save_thesis_markdown() at thesis_service.py:116 is called AFTER
            # commit by apply_process_template's caller (the service-layer wrapper), outside
            # the DB transaction. Best-effort; not tx-atomic.

            # Rebuild draft artifact via build_draft_artifact_from_thesis. Note:
            # _normalized_metadata (which recomputes next_factor_id from qualitative_factors)
            # runs DURING ARTIFACT ASSEMBLY inside _build_validated_artifact at handoff.py:727
            # — NOT inside _ensure_handoff_artifact (R6 should-fix #2 correction).
            rebuilt = build_draft_artifact_from_thesis(
                self, file_row=file_row, handoff_row=latest_any,
                draft_artifact=hydrated_artifact,
                thesis_row={**thesis_row, "qualitative_factors": merged_factors},
            )

            # Set process_template_id directly on the rebuilt artifact BEFORE persistence —
            # avoids a second update_process_template_id call (which would open its own
            # conn and deadlock our BEGIN IMMEDIATE anyway). process_template_id is listed
            # in _HANDOFF_ONLY_FIELD_KEYS at repository.py:256-262 so it survives the
            # _ensure_handoff_artifact normalization without being stripped.
            rebuilt["process_template_id"] = template_id

            # Persist rebuilt artifact — inline the FULL body of update_handoff_artifact()
            # at repository.py:2173-2214 using the externally-owned conn. Steps matching
            # live body VERBATIM (R6 should-fix correction — previously omitted
            # _incoming_handoff_schema_version + _log_handoff_id_backfill + reselect):
            original_schema_version = _incoming_handoff_schema_version(rebuilt)
            artifact_payload = _ensure_handoff_artifact(
                rebuilt,
                file_row=file_row,
                created_at=latest_any.get("created_at"),
                handoff_id=int(latest_any["id"]),
                for_write=True,
            )
            artifact_payload, backfill_count = _maybe_backfill_legacy_handoff_ids(
                artifact_payload,
                original_schema_version=original_schema_version,
                status=str(latest_any.get("status") or ""),
            )
            artifact_payload = _validate_handoff_artifact(artifact_payload)
            _log_handoff_id_backfill(
                backfill_count=backfill_count,
                original_schema_version=original_schema_version,
                research_file_id=int(research_file_id),
                handoff_id=int(latest_any["id"]),
            )
            conn.execute(
                "UPDATE research_handoffs SET artifact=? WHERE id=?",
                (json.dumps(artifact_payload), int(latest_any["id"])),
            )
            # Reselect for return (mirrors live update_handoff_artifact's return):
            updated_handoff_row = conn.execute(
                "SELECT * FROM research_handoffs WHERE id=?",
                (int(latest_any["id"]),),
            ).fetchone()

            # Insert research_file_history row — inline SQL pattern per repository.py:1527.
            # created_at is REAL epoch time matching existing history writes (line 1533 uses
            # updates["updated_at"] which is set to time.time() at repository.py:1257).
            # R4 blocker #1 correction — R3 incorrectly used _now_iso() (ISO string).
            history_changes = json.dumps({
                "template_id": template_id,
                "prior_template_id": prior_template_id,
                "seeded_factor_count": len(new_factors),
            })
            conn.execute(
                "INSERT INTO research_file_history (research_file_id, event_type, changes, created_at) "
                "VALUES (?, 'process_template_applied', ?, ?)",
                (int(research_file_id), history_changes, time.time()),
            )

        # Cache invalidation outside the DB transaction (safe — cache is read-through).
        get_template_catalog().invalidate_user(self._current_user_id())

        # Re-read thesis row for caller's markdown sync (R7 should-fix resolution).
        updated_thesis_row = self.get_thesis_by_research_file(int(research_file_id))

        return {
            "research_file_id": int(research_file_id),
            "template_id": template_id,
            "prior_template_id": prior_template_id,
            "handoff_id": int(latest_any["id"]),
            "seeded_factor_count": len(new_factors),
            "thesis_row": updated_thesis_row,   # for post-commit save_thesis_markdown() in action layer
        }
```

**Action layer** (`AI-excel-addin/api/research/research_service.py` — new function `set_process_template(user_id, research_file_id, template_id)` — explicit user_id parameter matching the DI pattern the route layer already uses via `get_trusted_user_id` at `routes.py:81`; same signature shape as `bootstrap_from_idea(user_id, ...)`):

1. Resolve template via `get_template_catalog().get(user_id, template_id)` → raise `TemplateNotFoundError` if miss (route maps to 404 `template_not_found`).
2. Compute `seed_factor_rows` from template's `seed_qualitative_factors` (via `_seed_factor_to_qualitative_factor` helper used in §6.2). IDs are reassigned INSIDE `apply_process_template` to preserve monotonicity against existing factors.
3. Call `repo.apply_process_template(research_file_id, template_id, seed_factor_rows)` — returns result dict on success; raises typed exceptions that propagate to the route. Route-level handler maps: `ThesisRequiredError`→422 `thesis_required_first`, `NoDraftHandoffError`→409 `no_draft_handoff`, `FinalizedHandoffError`→409 `cannot_change_finalized_template`.
4. **Post-commit markdown sync** (R6 should-fix #3 resolution): call `thesis_service.save_thesis_markdown(Thesis.model_validate(updated_thesis_row))` AFTER `apply_process_template` returns. `apply_process_template`'s return dict (see §7.2 repo body) is extended to include `"thesis_row": updated_thesis_row` — the service re-uses it directly here instead of re-reading (R7 should-fix resolution). Markdown is best-effort (not tx-atomic with the DB write); a crash here leaves DB correct and markdown stale — the watcher-import re-sync path at `thesis_service.on_watcher_markdown_change` (line 156) handles the reverse direction on next file touch, but the forward direction has no automatic retry. Document this limitation in the action-layer docstring.
5. Return repo's result dict — route hands to JSONResponse.

**Typed exceptions** in `api/research/errors.py` (new module — R2 should-fix #2 resolution; mirrors the service-local error pattern `IdeaConflictError` at `research_service.py:13` uses):
- `TemplateNotFoundError` (404 — unknown template_id on any route that accepts one)
- `ThesisRequiredError`
- `NoDraftHandoffError`
- `FinalizedHandoffError`
- `TemplateRequirementsError` (for sub-phase F finalize gate failures — MOVED here from §9.2's R1 draft that placed it in `research_service.py`)
- `DanglingSourceRefError` (defense-in-depth for the source walker — see §9.2)

**Route-level exception mapping sketch** (R3 should-fix #2 resolution — prevents drift between backend route status codes and risk_module gateway classifiers):

```python
# api/research/routes.py (additions)

@router.post("/files/{research_file_id}/process_template")
def set_research_file_process_template(
    research_file_id: int,
    body: SetProcessTemplateBody,
    user_id: str = Depends(get_trusted_user_id),
) -> dict[str, Any]:
    try:
        result = research_service.set_process_template(
            user_id, int(research_file_id), body.template_id,
        )
    except TemplateNotFoundError as exc:
        _raise_typed_http_error(404, "template_not_found", str(exc))
    except ThesisRequiredError as exc:
        _raise_typed_http_error(422, "thesis_required_first", str(exc))
    except NoDraftHandoffError as exc:
        _raise_typed_http_error(409, "no_draft_handoff", str(exc))
    except FinalizedHandoffError as exc:
        _raise_typed_http_error(409, "cannot_change_finalized_template", str(exc))
    return result


# POST /handoffs/finalize — finalize_handoff route EXISTING at routes.py:930 gains:
#     except TemplateRequirementsError as exc:
#         raise HTTPException(
#             status_code=409,
#             detail={
#                 "error": "template_requirements_unmet",
#                 "template_id": exc.template_id,
#                 "failed_gates": exc.failed_gates,
#             },
#         )
#     except DanglingSourceRefError as exc:
#         # Should never happen given _validate_source_refs_resolve; surface explicitly.
#         _raise_typed_http_error(500, "dangling_source_ref", str(exc))
```

`_raise_typed_http_error` already exists in the routes module (used by MBC route at `routes.py:968` and others). Error bodies match the `{error: "<slug>", ...detail}` convention that risk_module's gateway classifier at `services/research_gateway.py:218` inspects. Plan #5's gateway additions in §10.3 key on the `error` slug verbatim.

### 7.3 Files to modify/create

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/research/routes.py` | New `POST /files/{id}/process_template` route | ~+55 |
| `AI-excel-addin/api/research/research_service.py` | `set_process_template()` function (thin adapter around repo helper) | ~+60 |
| `AI-excel-addin/api/research/repository.py` | `apply_process_template()` atomic helper (reuses live `_persist_thesis_payload(conn,...)` + INLINES `update_handoff_artifact` body with external conn — no new conn-scoped tx helpers required) | ~+150 |
| `AI-excel-addin/api/research/errors.py` | **NEW** module — `ThesisRequiredError`, `NoDraftHandoffError`, `FinalizedHandoffError`, `TemplateRequirementsError` (R2 should-fix #2) | ~+40 |
| `AI-excel-addin/tests/api/research/test_set_process_template.py` | **NEW** — end-to-end tests | ~+240 |

### 7.4 Tests (~16)

- Happy path: valid template, no prior → factors seeded + draft artifact updated + handoff field set + history row (2)
- Re-apply SAME template: idempotent by `(category, label)`, no duplicate factors, history row still recorded with `seeded_factor_count=0` (1)
- Switch from template A to template B: new factors from B added union-style (A's remain — analyst prunes manually), history row records both prior and new template_id (1)
- Unknown template_id → 404 (1)
- No handoff at all (analyst didn't call `activate_diligence()`) → 409 `no_draft_handoff` (latest_any is None branch) (1)
- Latest handoff is FINALIZED → 409 `cannot_change_finalized_template` (latest_any.status != "draft" branch — R2 blocker #3 correction: the R1 draft's `get_latest_handoff(status="draft")` could NOT distinguish this case) (1)
- Latest handoff is SUPERSEDED → 409 `cannot_change_finalized_template` (same branch covers other non-draft statuses) (1)
- Thesis doesn't exist yet → 422 `thesis_required_first` (1)
- Malformed body (missing template_id) → 422 (1)
- History row `event_type` + `changes` shape + JSON-decodable payload (2)
- Factor IDs assigned via `_recompute_next_factor_id` over existing factors (1)
- Draft artifact `qualitative_factors` match Thesis after set (mirror invariant) (1)
- **Atomicity** (R2 blocker #3 coverage): concurrent `set_process_template` + `finalize_handoff` under `_handoff_lock()` — `set_process_template` either fully completes BEFORE finalize (finalize sees seeded factors + template_id) OR `finalize_handoff` wins and `set_process_template` raises `FinalizedHandoffError` (never a half-applied state where factors seeded but template_id missing or history missing) (2)
- **Concurrency**: two concurrent `set_process_template` calls with DIFFERENT templates on same research_file — second call sees first's factors, unions correctly under shared lock (1)
- User-created template applied via setter (1)
- Default template applied via setter (1)

---

## 8. Sub-phase E — Template-aware diligence state + prepopulate

### 8.1 Goal

`DiligenceService.get_state()` (at `diligence_service.py:49-84`) consults the applied template for section filtering + ordering. `prepopulate_*_section()` helpers in `api/research/prepopulate.py` scope section processing to template's `required`. Fallback: when no template resolved, behavior is identical to pre-plan-5 (full 9-tuple in natural order).

### 8.2 `get_state()` extension

Today's body (diligence_service.py:67-75):

```python
sections = [
    {
      "key": section_key,
      "title": SECTION_TITLES[section_key],
      "completionState": completion.get(section_key, "empty"),
      "data": _default_section_wrapper_from_artifact(artifact, section_key),
    }
    for section_key in DILIGENCE_SECTION_KEYS   # HARDCODED 9-tuple in natural order
]
```

R1 extension: if `artifact.process_template_id` resolves to a template, use `template.section_config.required` (filter) + `template.section_config.order` (if non-empty, override ordering; else preserve filtered natural order per Codex Q3).

```python
# Load template from artifact's process_template_id (if present).
# DiligenceService holds `self._repo`; repo has `_current_user_id()` at repository.py:1077
# which returns the user_id the repo was bound to. Thread it to the catalog. (R3 blocker #2
# resolution — research routes use explicit user_id DI via get_trusted_user_id at routes.py:81,
# not memory scope, so catalog must receive user_id explicitly.)
user_id = self._repo._current_user_id()
template_id = artifact.get("process_template_id")
template = get_template_catalog().get(user_id, template_id) if template_id else None

if template and template.section_config.required:
    required_set = set(template.section_config.required)
    filtered_keys = [k for k in DILIGENCE_SECTION_KEYS if k in required_set]
    if template.section_config.order:
        # Order is a permutation of required (validated at §4.2); use as-is
        ordered_keys = list(template.section_config.order)
    else:
        # Codex Q3: fall back to DILIGENCE_SECTION_KEYS natural order filtered to required
        ordered_keys = filtered_keys
else:
    ordered_keys = list(DILIGENCE_SECTION_KEYS)

sections = [
    {
        "key": section_key,
        "title": SECTION_TITLES[section_key],
        "completionState": completion.get(section_key, "empty"),
        "data": _default_section_wrapper_from_artifact(artifact, section_key),
    }
    for section_key in ordered_keys
]
```

**`min_completion` reflected in completionState floor**: template may specify `min_completion[key] = "draft"` or `"confirmed"` to guide analysts. `get_state()` passes this through as metadata (new key `minRequired`), not as an override of actual state — floor enforcement happens at finalize (sub-phase F), not at view time.

### 8.3 `prepopulate` extension (simplified per R2 nit #3)

Live `prepopulate_diligence(sections=...)` at `api/research/prepopulate.py:532` already accepts a `sections: list[str] | None` parameter. Plan #5 does NOT extend the dispatcher signature — instead the route handler `POST /diligence/prepopulate` at `routes.py:882` resolves the template and derives the sections list BEFORE invoking:

```python
@router.post("/diligence/prepopulate")
async def trigger_diligence_prepopulate(research_file_id: int, request: DiligencePrepopulateRequest):
    # R2 nit #3: route layer derives sections from template; dispatcher unchanged.
    sections = request.sections
    if sections is None:
        # Default behavior: if artifact carries a template, scope to its required sections.
        # Route-layer already has user_id from get_trusted_user_id DI (routes.py:81 pattern).
        repo = get_repository_factory().get(user_id)
        handoff = repo.get_latest_handoff(research_file_id, status="draft")
        # NOTE: handoff["artifact"] is JSON TEXT (raw row), not a dict — use
        # _artifact_from_row() from handoff.py (same pattern as §7.2).
        from research.handoff import _artifact_from_row
        file_row = repo.get_file(research_file_id)
        hydrated = _artifact_from_row(handoff, file_row=file_row) if handoff and file_row else {}
        template_id = hydrated.get("process_template_id") if isinstance(hydrated, dict) else None
        template = get_template_catalog().get(user_id, template_id) if template_id else None
        if template and template.section_config.required:
            sections = list(template.section_config.required)

    return await prepopulate_diligence(research_file_id, sections=sections)
```

Sections outside `required` are NOT pre-populated; analyst may still add them manually via direct update APIs. Caller can override template scoping by passing `sections=[...]` explicitly.

### 8.4 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/research/diligence_service.py` | `get_state()` template-aware section filtering + ordering | ~+50 |
| `AI-excel-addin/api/research/prepopulate.py` | No change — live `prepopulate_diligence(sections=...)` at line 532 already accepts the scoped-sections parameter (R2 nit #3 simplification) | 0 |
| `AI-excel-addin/api/research/routes.py` | `POST /diligence/prepopulate` route derives `sections` from template before invoking the dispatcher | ~+25 |
| `AI-excel-addin/tests/test_research_prepopulate.py` | Template-scoped prepopulate cases (existing file — R1 nit #2 corrected location) | ~+120 |
| `AI-excel-addin/tests/api/research/test_update_handoff_section.py` | Template-aware get_state cases if coverage belongs here; else new `tests/api/research/test_diligence_state.py` | ~+100 |

### 8.5 Tests (~14)

- `get_state` without template: 9 sections in natural order (regression) (1)
- `get_state` with template (required=[business_overview, thesis, risks]): 3 sections only (1)
- `get_state` with template + order=[risks, thesis, business_overview]: sections in template order (1)
- `get_state` with template + empty order: filtered sections in natural DILIGENCE_SECTION_KEYS order (Codex Q3) (1)
- `get_state` with template exposing `minRequired` metadata per section (1)
- `get_state` with `process_template_id` on artifact but template deleted/unknown: falls back to default 9 sections + warning (1)
- `prepopulate` without template: all sections processed (regression) (1)
- `prepopulate` with template (required subset): only required sections processed (1)
- `prepopulate` with template + empty required: falls back to all sections (degenerate path) (1)
- Integration: start_research(idea with template) → get_state uses template automatically (1)
- Integration: set_process_template applied post-activate → subsequent get_state uses new template (1)
- Thesis markdown export still includes all factors (regression — template scopes diligence view, not factor storage) (1)
- Sections outside template's required are NOT overwritten (preserve any pre-existing section data) (1)
- `minRequired` metadata empty for sections where template doesn't specify (1)

---

## 9. Sub-phase F — Finalize validation (G7/G12 closure)

### 9.1 Goal

**G7/G12 actual closure** (R1 blocker #1 resolution, R2 blocker #1 correction on source coverage mechanics). `HandoffService.finalize_handoff()` at `api/research/handoff.py:490` consults the template (via artifact's `process_template_id`) and enforces:

1. **`section_config.min_completion`** — artifact's `metadata.diligence_completion[key]` must meet or exceed the template's required state for each key (ordering: `empty(0) < draft(1) < confirmed(2)`).
2. **`valuation_methods_allowed`** — `artifact.valuation.method` (live field at `schema/thesis_shared_slice.py:199-200`, `method: str | None`, FREE-FORM string) MUST be in the template's `valuation_methods_allowed` list (if non-empty; empty list = no restriction). If `artifact.valuation is None` OR `artifact.valuation.method is None` AND the template list is non-empty, gate fails with `"valuation.method is required but absent"`. This is why default templates MUST include `"relative"` in their allow-list if they allow prepopulate's output (which emits `method="relative"` per `prepopulate.py:323` — R2 blocker #4 alignment).
3. **`required_source_coverage`** (R2 blocker #1 correction) — counted over `artifact.sources[]` (typed `SourceRecord` list at `schema/thesis_shared_slice.py:287`). Enumerate unique `src_N` IDs actually REFERENCED from sections/factors (walker below), resolve each ID → `SourceRecord`, bucket by `.type` (live `SourceType = Literal["filing", "transcript", "investor_deck", "other"]`). Template's `min_filings`, `min_transcripts`, `min_investor_decks`, `min_other` are each a non-null integer floor on the corresponding bucket count.
   - The R1 draft's `source_ref.type` + `backfill_v1_0_stable_ids` references were wrong. Live finalize sees a validated `HandoffArtifactV1_1` where refs are stable `src_N` IDs (per `schema/thesis_shared_slice.py:21`: `SourceId = Annotated[str, ..., pattern=r"^src_[1-9]\d*$"]`), the typed records live in `artifact.sources[]`, and the legacy inline-ref normalization is `_normalize_legacy_shared_slice_sources()` at `handoff.py:199` — but by the time finalize runs, normalization has already happened and the artifact is schema-valid. The walker just enumerates `SourceId` references reachable from section bodies + qualitative_factors and resolves each against `artifact.sources[]`.

If ANY gate fails, finalize raises a typed exception surfaced as HTTP 409 `template_requirements_unmet` with a detail payload listing failed gates:

```json
{
  "error": "template_requirements_unmet",
  "template_id": "value",
  "failed_gates": {
    "min_completion": {"valuation": "required=confirmed, got=draft"},
    "valuation_methods_allowed": "declared=dcf_lite not in [dcf, multiples, relative]",
    "required_source_coverage": {"min_filings": "required=3, got=1"}
  }
}
```

**Source-ID walker** (helper in `template_validation.py`) — **REUSES the live generic ref iterator at `handoff.py:245` (currently `_iter_source_refs`; renamed to public `iter_source_refs` as part of sub-phase F)** (R3 blocker #1 resolution — the hand-rolled walker in R2 missed singular `Catalyst.source_ref` / `Risk.source_ref` at `thesis_shared_slice.py:173,186`, `ConsensusView.citations` at `:125`, `DifferentiatedViewClaim.evidence` at `:130`, and nested `industry_analysis` refs at `:304`. The live iterator already handles every ref topology via `_SOURCE_REF_LIST_KEYS` + `_SOURCE_REF_SCALAR_KEYS`):

```python
from research.handoff import iter_source_refs   # promote to public export in §9.3 file list

def _count_sources_by_type(artifact: dict[str, Any]) -> dict[str, int]:
    """Bucket unique SourceId references by SourceRecord.type. Only referenced IDs
    count — records in artifact.sources[] that aren't cited anywhere don't contribute.

    A referenced src_N not present in artifact.sources[] is a dangling reference —
    the validated artifact schema should have rejected this already via
    _validate_source_refs_resolve at handoff.py:290. This helper raises
    DanglingSourceRefError if it ever observes one (defense-in-depth; finalize
    should never reach this state, but plan #5 surfaces the class explicitly in
    errors.py so the failure mode is typed if it ever occurs)."""
    referenced_ids = set(iter_source_refs(artifact))   # live iterator, all ref topologies
    sources = artifact.get("sources") or []
    by_id = {str(s.get("id") or "").strip(): str(s.get("type") or "").strip()
             for s in sources if isinstance(s, dict)}
    counts: dict[str, int] = {"filing": 0, "transcript": 0, "investor_deck": 0, "other": 0}
    for src_id in referenced_ids:
        src_type = by_id.get(src_id)
        if src_type is None:
            raise DanglingSourceRefError(src_id=src_id)
        if src_type in counts:
            counts[src_type] += 1
    return counts
```

**Promotion step** (`iter_source_refs` rename): sub-phase F renames the module-private `_iter_source_refs` at `handoff.py:245` to public `iter_source_refs` (drop underscore). Update the one internal caller `_validate_source_refs_resolve` at `handoff.py:290` (renames reference: `ref for ref in iter_source_refs(...)`). Grep confirms zero external importers of `_iter_source_refs` by name today — safely scoped rename. Live tests for handoff source-ref validation catch any breakage.

Without a template, `finalize_handoff()` behavior is unchanged (backwards compat).

### 9.2 Design

Rewrite `HandoffService.finalize_handoff()` at `handoff.py:490` + rename/extend `_assemble_artifact` → `_assemble_artifact_locked`:

Plan #2's `finalize_handoff()` at `handoff.py:490` today reads the draft, calls `_assemble_artifact()` (which internally acquires `_handoff_lock`), then calls `update_handoff_artifact()` + `finalize_handoff()` OUTSIDE the lock. That leaves two race windows:
1. Between initial draft read (`handoff.py:494`) and lock acquisition inside assemble.
2. Between lock release (after assemble) and subsequent writes (`update_handoff_artifact` + status flip at `:499-502`).

A fresh-read inside assemble closes window 1, but `set_process_template` can still slip into window 2 and have its writes silently overwritten by the finalize's pending assembly. **The lock must cover the entire finalize flow, not just assemble.** (R4 blocker #1 resolution.)

### 9.2.1 Minimum change to plan #2's finalize

Rewrite `HandoffService.finalize_handoff()` to acquire `_handoff_lock()` at the top and hold it through assemble + artifact write + status flip. `_assemble_artifact()` is kept as an internal method but no longer acquires the lock itself (caller owns it now).

```python
# AI-excel-addin/api/research/handoff.py — finalize_handoff() rewrite

def finalize_handoff(self, research_file_id: int) -> dict[str, Any]:
    file_row = self._repo.get_file(research_file_id)
    if file_row is None:
        raise ValueError("research file not found")

    with _handoff_lock(self._repo, file_row=file_row):
        # Fresh read INSIDE the lock — no stale state.
        draft = self._repo.get_latest_handoff(research_file_id, status="draft")
        if draft is None:
            raise ValueError("draft handoff not found")

        artifact = self._assemble_artifact_locked(file_row, draft)   # NEW: caller owns lock
        updated = self._repo.update_handoff_artifact(draft["id"], artifact)
        if updated is None:
            raise ValueError("handoff not found")
        finalized = self._repo.finalize_handoff(draft["id"])
        if finalized is None:
            raise ValueError("draft handoff not found")
    return self._serialize_summary(finalized, artifact)


# Renamed from _assemble_artifact. No longer acquires the lock (caller owns it).
# Signature unchanged otherwise.
def _assemble_artifact_locked(self, file_row, handoff_row):
    draft_artifact = _artifact_from_row(handoff_row, file_row=file_row)
    thesis_row = self._resolve_thesis_row(file_row, ...)
    artifact = self._build_validated_artifact(file_row, handoff_row, draft_artifact, thesis_row)

    # Template-aware finalize gates (operate on locked state).
    user_id = self._repo._current_user_id()
    template_id = artifact.get("process_template_id")
    if template_id:
        template = get_template_catalog().get(user_id, template_id)
        if template is not None:
            failed_gates = _evaluate_template_gates(artifact, template)
            if failed_gates:
                raise TemplateRequirementsError(
                    template_id=template_id,
                    failed_gates=failed_gates,
                )
        else:
            log.warning("finalize: template_id=%s unknown; skipping gate enforcement", template_id)

    return artifact
```

**Delta vs plan #2's shipped code:**
1. `finalize_handoff()` body restructured: lock at top; fresh-read inside lock; internal assemble/write/finalize all under the same lock. ~12 line change.
2. `_assemble_artifact` renamed to `_assemble_artifact_locked` (signal that caller owns lock). No behavior change for other callers — audit + fix them below.
3. Template gate block added inside the locked assemble helper (new).

**Other callers of `_assemble_artifact`** (live grep audit — R5 should-fix #2 correction):
- Live grep shows ONLY ONE caller of `_assemble_artifact` — `finalize_handoff()` at `handoff.py:498`. The R4 draft incorrectly claimed `create_new_version()` at `handoff.py:507` also called it; live `create_new_version` instead calls `_build_validated_artifact()` directly under its own `_handoff_lock` block at `:516-537` (which already wraps the full read → supersede → build → write flow correctly). No change needed for `create_new_version`.
- `build_draft_artifact_from_thesis()` at `handoff.py:381` (module-level helper used by plan #5 sub-phase C) calls `HandoffService._build_validated_artifact()` directly — unaffected by the rename.
- Net: the `_assemble_artifact` → `_assemble_artifact_locked` rename is a one-site rename (`finalize_handoff` caller + the method definition itself). Scope is smaller than R4 suggested.

This completes finalize atomicity. `apply_process_template()` (which also holds `_handoff_lock`) and `finalize_handoff()` now serialize against each other on the same lock; whichever acquires first completes its mutation before the other reads.

**`_evaluate_template_gates(artifact, template) -> dict`**: dedicated validator module (`api/research/template_validation.py`, new). Three sub-checks (one per gate type). Returns dict of failed_gates (empty if all pass).

**Error type `TemplateRequirementsError`** lives in the NEW `api/research/errors.py` module (R2 should-fix #2 — NOT in `research_service.py` as R1 draft said; placing it in `handoff.py` would require `research_service.py` to reach into `handoff.py` for error catching, which is not the live service-local convention demonstrated by `IdeaConflictError` at `research_service.py:13`). All four typed exceptions (§7.2 list + `TemplateRequirementsError`) live in the same `errors.py` for a single import surface. Route handler at `routes.py:930` (`POST /handoffs/finalize`) catches → returns HTTP 409 with payload.

### 9.3 Files to create/modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/research/template_validation.py` | **NEW** — `_evaluate_template_gates()` + `_enumerate_referenced_source_ids()` + `_count_sources_by_type()` helpers | ~+180 |
| `AI-excel-addin/api/research/errors.py` | (already created in sub-phase D — this adds `TemplateRequirementsError` to the same module) | (see §7.3) |
| `AI-excel-addin/api/research/handoff.py` | `finalize_handoff()` rewrite (lock at top, fresh-read draft inside lock); `_assemble_artifact` renamed to `_assemble_artifact_locked`; `_assemble_artifact_locked` calls validator + raises `TemplateRequirementsError`; `_iter_source_refs` renamed to public `iter_source_refs` | ~+40 |
| `AI-excel-addin/api/research/routes.py` | `POST /handoffs/finalize` maps `TemplateRequirementsError` → 409 | ~+15 |
| `AI-excel-addin/tests/api/research/test_finalize_template_gates.py` | **NEW** — gate tests incl. source walker | ~+320 |

### 9.4 Tests (~18)

- Finalize without template: unchanged behavior (regression) (1)
- Finalize with template + all gates passing: succeeds (1)
- **`min_completion` gate**: artifact completion below template floor → 409 with failed_gates shape (2)
- **`min_completion` gate**: state ordering (`empty < draft < confirmed`) (2)
- **`valuation_methods_allowed` gate**: declared method not in list → 409 (1)
- **`valuation_methods_allowed` gate**: empty list = no restriction, finalize succeeds regardless (1)
- **`valuation.method` absent + non-empty allow-list**: gate fails with explicit "required but absent" error (R2 blocker #4 coverage — live prepopulate emits `"relative"`; gate must still block when method is None) (1)
- **`required_source_coverage` gate** — each of `min_filings/min_transcripts/min_investor_decks/min_other` individually (4)
- **`_enumerate_referenced_source_ids` walker** (R2 blocker #1 coverage): source_refs spread across sections + factors counted uniquely; sources in `artifact.sources[]` that are NOT referenced don't contribute to coverage; duplicate ID references count once (2)
- **`_count_sources_by_type` bucketing**: resolves each referenced `src_N` → `SourceRecord.type`, buckets correctly across the 4 live SourceType values (1)
- Multiple gates fail simultaneously: `failed_gates` dict includes all (1)
- Template_id set but unknown (deleted mid-session): warning logged, no gate enforcement, finalize succeeds (graceful degradation — mirrors plan #4's unknown-template policy at ingest) (1)
- Error detail payload JSON-serializable (1)
- Finalize with template that has ZERO gates configured (empty required, empty valuation_methods_allowed, null required_source_coverage): finalize succeeds regardless of artifact state (1)
- Concurrency: finalize happens under existing `_handoff_lock()` at `handoff.py:553` (regression test — no new deadlock) (1)

---

## 10. Sub-phase G — risk_module MCP surface

### 10.1 Goal

Expose template operations + finalize-error surfacing to the agent surface. 3 new MCP tools + 3 new typed errors + 4 agent flags. (R2 nit #1 — count reconciled with §10.3/§10.4.)

### 10.2 MCP tools (in `risk_module/mcp_tools/research.py`)

```python
@mcp.tool()
def list_process_templates(user_email: str | None = None, format: Literal["summary", "agent"] = "agent") -> dict:
    """List all available templates (YAML defaults + user-created)."""

@mcp.tool()
def get_process_template(template_id: str, user_email: str | None = None, format: Literal["summary", "agent"] = "agent") -> dict:
    """Get a specific template by ID."""

@mcp.tool()
def set_process_template(research_file_id: int, template_id: str, user_email: str | None = None, format: Literal["summary", "agent"] = "agent") -> dict:
    """Apply a template to an existing research file."""
```

Each tool calls `risk_module/actions/research.py`, which calls AI-excel-addin backend via `research_gateway`.

### 10.3 Gateway error classifier extensions (in `risk_module/services/research_gateway.py`)

Plan #4 ships `IdeaConflictError` mapping on HTTP 409 with body `{error: "idea_conflict"}`. Plan #5 adds:

- HTTP 404 (template miss on `GET /process_templates/{id}`, `POST /files/{id}/process_template`) → maps to **existing** `ActionNotFoundError` at `risk_module/services/research_gateway.py:218` (R2 should-fix #1 correction — plan #5 does NOT reinvent 404 handling; tests in §10.6 assert `ActionNotFoundError`, not `ActionValidationError`).
- HTTP 409 `error=cannot_change_finalized_template` → `TemplateSwitchError(ActionValidationError)` with `research_file_id` detail.
- HTTP 409 `error=no_draft_handoff` → `TemplateSwitchError` (same class — both are "can't apply template now" variants).
- HTTP 409 `error=template_id_conflict` → `TemplateIdConflictError(ActionValidationError)` with `template_id`, `conflict_source` (`"default"`/`"user"`).
- HTTP 409 `error=template_requirements_unmet` → `TemplateRequirementsError(ActionValidationError)` with `template_id`, `failed_gates`.

New typed errors in `risk_module/actions/errors.py` (3 classes added — not 2 as R1 draft said). `ActionNotFoundError` is reused as-is from plan #3 G's existing surface.

### 10.4 Agent flags (in `risk_module/core/research_flags.py`)

| Condition | Flag | Severity |
|---|---|---|
| `start_research(idea)` response has `process_template_applied=true` | `research_template_applied` | info |
| `set_process_template` succeeded | `process_template_switched` | info |
| Idea had `suggested_process_template_id` but action response has `process_template_applied=false` with no other error | `process_template_unknown` | warning |
| `TemplateRequirementsError` caught at finalize | `finalize_template_gates_failed` | warning |

The `_normalize_file_snapshot()` at `actions/research.py:747` (plan #4 sub-phase F extended it) must ALSO preserve:
- Top-level `process_template_applied` bool on `start_research_from_idea` responses
- Top-level `failed_gates` dict on finalize error responses (propagated through action layer into MCP agent response)

### 10.5 Files to modify/create

| File | Change | Est. lines |
|---|---|---|
| `risk_module/mcp_tools/research.py` | 3 new tools | ~+60 |
| `risk_module/actions/research.py` | 3 new action functions + normalizer extension for `process_template_applied` / `failed_gates` | ~+140 |
| `risk_module/actions/errors.py` | `TemplateSwitchError`, `TemplateIdConflictError`, `TemplateRequirementsError` | ~+20 |
| `risk_module/services/research_gateway.py` | 3 new 409 classifier branches | ~+30 |
| `risk_module/core/research_flags.py` | 4 new flag generators | ~+50 |
| `risk_module/agent/registry.py` | Register 3 new callables | ~+30 |
| `risk_module/mcp_server.py` | Register tools | ~+9 |
| `risk_module/tests/mcp_tools/test_process_template.py` | **NEW** — MCP-layer tests | ~+260 |
| `risk_module/tests/routes/test_agent_api_templates.py` | **NEW** — agent-API registry + dispatch tests | ~+60 |

### 10.6 Tests (~22)

- `list_process_templates` happy path + agent format snapshot normalization (2)
- `get_process_template` default hit + miss → `ActionNotFoundError` (R2 should-fix #1 — 404 is `NotFound`, not `ValidationError`) (2)
- `set_process_template` happy path + agent format (2)
- `set_process_template` unknown template → `ActionNotFoundError` (1)
- `set_process_template` finalized handoff → `TemplateSwitchError` (2)
- `set_process_template` no draft handoff → `TemplateSwitchError` (1)
- Gateway 409 mapping exercised (4 `TemplateXxxError` classes × 1 test = 4)
- Agent flag `research_template_applied` on idea-seeded start_research (1)
- Agent flag `process_template_switched` on explicit set (1)
- Agent flag `process_template_unknown` on unknown-template-id idea (1)
- Agent flag `finalize_template_gates_failed` on TemplateRequirementsError (1)
- Normalizer preserves `process_template_applied` + `failed_gates` (drives through action layer, NOT stubs MCP wrapper — same pattern plan #4 sub-phase F R9 blocker resolution enforced) (2)
- Registry advertises 3 new callables via `GET /api/agent/registry` (2)
- `POST /api/agent/call` accepts new calls end-to-end (1)

---

## 11. Sub-phase H — Default catalog + E2E tests

### 11.1 Default catalog

4 YAML templates in `AI-excel-addin/config/process_templates/`. Illustrative `value.yaml`:

```yaml
template_id: value
name: Value Investor
description: Classic value investing — undervalued businesses with margin of safety.
investor_profile:
  strategy_bias: value
  holding_period_bias: long_term
section_config:
  required: [business_overview, thesis, valuation, assumptions, risks, peers]
  order:    [business_overview, thesis, valuation, assumptions, risks, peers]
  min_completion:
    thesis: draft
    valuation: confirmed
    risks: draft
seed_qualitative_factors:
  - {category: moat, label: Durable competitive advantage, guidance: "Brand / scale / network / switching cost"}
  - {category: balance_sheet, label: Financial strength, guidance: "Net cash or low debt / interest coverage"}
  - {category: capital_allocation, label: Management capital allocation, guidance: "Buybacks / dividends / M&A track record"}
valuation_methods_allowed: [dcf, multiples, sum_of_parts, relative]   # "relative" INCLUDED so prepopulate.py:323 output passes gate (R2 blocker #4)
required_source_coverage:
  min_filings: 3
  min_transcripts: 2
```

Other three:
- `compounder.yaml` — growth + quality bias, longer holding, `valuation_methods_allowed: [dcf, multiples, hybrid, relative]`
- `special_situation.yaml` — catalyst-driven, emphasis on catalysts + risks sections, `min_filings: 1, min_transcripts: 0` (permissive), `valuation_methods_allowed: [sum_of_parts, multiples, relative]`
- `macro.yaml` — top-down, emphasis on business_overview + peers (sector), `min_other: 2` (ad-hoc research notes bucket via `SourceType="other"`; NOT `min_industry_refs` — that bucket doesn't exist in live `SourceType` enum, R2 blocker #1 correction), `valuation_methods_allowed: [multiples, relative]`

**All default templates** must include `"relative"` in `valuation_methods_allowed` to stay compatible with `prepopulate.py:323` output. Alternative: change prepopulate to emit a different method, but that's a scope expansion touching plan-3-era code for marginal benefit. Chose to widen the template allow-lists instead.

### 11.2 E2E scenarios (~12 tests)

1. **Scenario 1** — Full chain with default template: connector emits `InvestmentIdea(suggested_process_template_id="value")` → `ingest_idea()` → `start_research(idea)` → Thesis seeded with 3 factors → draft artifact mirrors factors → draft `process_template_id="value"` → `activate_diligence()` uses 6-section subset → `prepopulate` scoped to 6 sections → `finalize_handoff()` with passing gates → final artifact preserves `process_template_id="value"`.
2. **Scenario 2** — Unknown template_id on idea: warning logged, Thesis seeded without factors, `process_template_id=None` on handoff, diligence uses default 9 sections, finalize has no template gates.
3. **Scenario 3** — User-created template: `POST /process_templates` creates it → `InvestmentIdea` references it → full chain works identically to default.
4. **Scenario 4** — Post-hoc switch via `set_process_template`: research_file initialized without template → `set_process_template("compounder")` → handoff `process_template_id` updated + history row + factors added (union, not replace).
5. **Scenario 5** — Finalize blocked by `min_completion`: `finalize_handoff` on artifact with incomplete valuation section returns 409 `template_requirements_unmet`.
6. **Scenario 6** — Finalize blocked by `valuation_methods_allowed`: artifact with method not in allow-list → 409.
7. **Scenario 7** — Finalize blocked by `required_source_coverage`: artifact with insufficient filings → 409.
8. **Scenario 8** — Finalized handoff blocks `set_process_template`: → 409 `cannot_change_finalized_template`.
9. **Scenario 9** — Schema round-trip: `ProcessTemplate.model_dump_json()` → load → equal.
10. **Scenario 10** — Pinned snapshot: `ProcessTemplate.model_json_schema()` matches committed JSON file.
11. **Scenario 11** — Each of 4 default YAML templates loads + validates at startup.
12. **Scenario 12** — Template-applied Thesis markdown round-trip preserves seeded factors + the factors propagate into draft + finalized artifact correctly.

### 11.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `AI-excel-addin/config/process_templates/value.yaml` | Default | ~35 |
| `AI-excel-addin/config/process_templates/compounder.yaml` | Default | ~35 |
| `AI-excel-addin/config/process_templates/special_situation.yaml` | Default | ~35 |
| `AI-excel-addin/config/process_templates/macro.yaml` | Default | ~35 |
| `AI-excel-addin/tests/integration/test_process_template_end_to_end.py` | E2E scenarios 1-8, 12 | ~320 |
| `AI-excel-addin/tests/schema/test_process_template_boundary.py` | Scenarios 9-11 | ~90 |
| `AI-excel-addin/tests/schema/snapshots/process_template_v1_0.schema.json` | Pinned schema | generated |

---

## 12. Sub-phase I — Docs

### 12.1 `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` updates

- **Key contracts table**: add `ProcessTemplate` row pointing at `schema/process_template.py`; drop "(planned)" markers.
- **Integration patterns**: insert "Pattern 0.5 — Template-aware research start" between existing Pattern 0 (idea ingress, plan #4) and Pattern 1. Describe: idea arrives with `suggested_process_template_id` → `start_research` resolves → Thesis pre-seeded → draft artifact mirrored → diligence state uses template filter/order → finalize enforces gates.
- **Skill rows**: annotate `/thesis-consultation` and `/position-initiation` to note they read template-seeded `qualitative_factors[]` as prior context.
- **Cross-repo references**: add rows for `AI-excel-addin/schema/process_template.py`, `AI-excel-addin/config/process_templates/`, `AI-excel-addin/api/research/template_catalog.py`, `AI-excel-addin/api/research/template_validation.py`.

### 12.2 `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §12 update

Mark plan #5 as **SHIPPED** once merged. Move `PROCESS_TEMPLATE_PLAN.md` from "not yet drafted" to "completed".

### 12.3 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` | Per §12.1 | ~+35 |
| `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` | Mark plan #5 SHIPPED | ~+2 |

---

## 13. Success criteria

- `ProcessTemplate v1.0` Pydantic type lands in `AI-excel-addin/schema/process_template.py` with `frozen=True`, `assessment`-required-str preservation via mandatory `SeedQualitativeFactor.guidance`.
- 4 default templates (`value`, `compounder`, `special_situation`, `macro`) ship as YAML and glob-load at startup with fail-fast validation.
- SQLite v6→v7 migration idempotent; CRUD routes + methods work.
- `TemplateCatalog` loader unions defaults + user-created, caches per-user, invalidates on writes, filters user-rows colliding with defaults.
- **G7/G12 actually closed** (R1 blocker #1 fix): `finalize_handoff()` enforces `min_completion` + `valuation_methods_allowed` + `required_source_coverage` gates and returns 409 `template_requirements_unmet` on failure.
- `start_research(idea)` with resolvable `suggested_process_template_id` seeds `Thesis.qualitative_factors[]` AND mirrors into draft `HandoffArtifact.qualitative_factors` (so `DiligenceService.get_state()` surfaces them immediately).
- `set_process_template()` explicit setter + `research_file_history` audit via inline-SQL pattern at `repository.py:1527`.
- `DiligenceService.get_state()` + `prepopulate_*_section()` respect template's `required/order`; fallback = natural DILIGENCE_SECTION_KEYS order when no template.
- risk_module MCP surface: 3 tools + 3 typed errors + 4 agent flags.
- `HandoffArtifact.process_template_id` propagates draft → finalized unchanged.
- Unknown `template_id` on idea does NOT fail `start_research` — warning logged, legacy path.
- Schema boundary snapshot pinned.
- SKILL_CONTRACT_MAP.md reflects shipped state.

**Cumulative test target**: ~140 new tests across sub-phases A-H (up from R0's 112 after expanding A, adding F, adding backend route tests in B).

---

## 14. Rollback

- A/B independent from everything downstream — either can ship alone without consumer hooks.
- C requires A+B + plan #4. Rollback: revert C commit; idea.suggested_process_template_id is still persisted by plan #4 but ignored (forward-compatible).
- D requires B. Rollback: revert D; no explicit setter, templates still applied via C.
- E requires B. Rollback: revert E; diligence state hardcodes 9 sections again.
- F requires B+D+E (writes that make a template-aware artifact). Rollback: revert F; finalize has no gate enforcement (reverts to pre-plan-5 behavior — backwards compat).
- G requires A+B+C+D+F. Rollback: revert G; agent surface loses template tools + error surfacing but backend still works.
- No DB rollback scripted — v6→v7 is additive. Un-ALTER requires backup restore.

---

## 15. Change log

### R0 → R1 (2026-04-22)

Codex R1 verdict: **FAIL**. 6 blockers + 7 should-fix + 3 nits. All resolved in-place.

**Blockers resolved:**

1. **`valuation_methods_allowed` / `required_source_coverage` / `min_completion` had no consumers**. Fixed by adding **sub-phase F (finalize validation)** — `HandoffService._assemble_artifact()` calls `_evaluate_template_gates()` and raises `TemplateRequirementsError` → HTTP 409 `template_requirements_unmet`. G7/G12 now actually close. §9, §13 success criteria.
2. **Bootstrap seeded Thesis but not draft artifact** — `DiligenceService.get_state()` reads from `artifact.qualitative_factors` (diligence_service.py:82), not Thesis. Fixed by mirroring via `handoff.build_draft_artifact_from_thesis()` at `handoff.py:381` after Thesis seeding. §3.1, §3.4 rule 3, §6.2.
3. **Wrong diligence code paths**. Fixed §8 targeting: `DiligenceService.get_state()` at `diligence_service.py:49-84` gets template-aware filtering/ordering; `api/research/prepopulate.py` (not `diligence_service.py`) gets template-aware section scoping. Test locations corrected to `tests/test_research_prepopulate.py` + `tests/api/research/test_update_handoff_section.py`. §8.2, §8.3, §8.4.
4. **Code sketches didn't compile**. Fixed: (a) inline `ConfigDict(..., frozen=True)` instead of phantom `CONTRACT_CONFIG` (§4.2); (b) `repo.get_latest_handoff(..., status="draft")` / `repo.get_or_create_draft_handoff()` instead of phantom `get_draft_handoff()` (§3.5, §6.2, §7.2); (c) inline SQL insertion of `research_file_history` rows matching pattern at `repository.py:1527` — no named helper exists (§7.2 step 8); (d) template_id regex violation in minted example removed (§3.2).
5. **Missing backend CRUD endpoints**. Fixed by expanding sub-phase B to include **5 new REST routes** (GET list, GET by id, POST create, PATCH update, DELETE) + corresponding repo methods + route tests. §5.3, §5.4, §5.5.
6. **`QualitativeFactor.assessment` is REQUIRED `str`, R0 treated mapping source as nullable**. Fixed by making `SeedQualitativeFactor.guidance` REQUIRED non-empty string in §4.2, guaranteeing the downstream mapping always produces a valid `QualitativeFactor`. §3.4 rule 2, §4.2 SeedQualitativeFactor schema, §4.4 test.

**Should-fix resolved:**

1. Boundary test insufficient → triple-sync test in §4.4 covering `SectionKey Literal` + `_DILIGENCE_KEYS` frozenset + `DILIGENCE_SECTION_KEYS` tuple. Also added duplicate-rejection for `required/order` lists. §4.2 SectionConfig validator + §4.4 tests.
2. `min_completion` keys not checked vs `required` → added to SectionConfig validator. §4.2.
3. `process_template_applied` response flag added to `start_research_from_idea()`. §6.2, §6.4.
4. §3.4 rule 3 factor IDs reworded: `_recompute_next_factor_id` at `handoff.py:398` is the live mechanism (max+1 recomputation, not counter). Docstring updated.
5. `TemplateCatalog.list()` filters user rows colliding with defaults. §5.2, §5.5 test.
6. Concurrency tests added: same-idea/different-template in §6.4, concurrent set_process_template in §7.4.
7. §7.4 wording precise: "Thesis doesn't exist yet → 422 `thesis_required_first`" not "via start_research" — accounts for legacy `start_research(ticker, label)` not creating a Thesis.

**Nits resolved:**

1. `stress_scenarios.yaml` reference in §3.3 removed (that file lives in risk_module, not AI-excel-addin; plan #5 introduces a new YAML loader pattern without prior art claim).
2. Test file locations corrected in §8 (`test_diligence_service.py` doesn't exist; use `test_research_prepopulate.py` + `test_update_handoff_section.py` or new `test_diligence_state.py`).
3. §14 (was §14.3) "spec says natural order" removed; §8.2 now labels filtered-natural-order as plan's choice (aligned with Codex Q3 recommendation).

**Open questions answered** (Codex Q1-Q5 positions adopted):

- Q1: `(category, label)` dedup key. §3.4 rule 4.
- Q2: Don't widen legacy `start_research(ticker, label)`. §1.1 out-of-scope.
- Q3: Empty `order` → filtered DILIGENCE_SECTION_KEYS natural order. §8.2.
- Q4: Reject duplicate `(category, label)` in `seed_qualitative_factors` at validation. §4.2 ProcessTemplate validator + §4.4 test.
- Q5: Glob discovery for YAML + fail-fast dup-ID + filename/template_id equality. §3.3, §5.2.

### R1 → R2 (2026-04-22)

Codex R2 verdict: **FAIL**. 4 blockers + 2 should-fix + 3 nits. All resolved in-place.

**Blockers resolved:**

1. **`required_source_coverage` gate under-specified + `min_industry_refs` referenced non-existent SourceType bucket**. Fixed: (a) `RequiredSourceCoverage` field names aligned to live `SourceType = Literal["filing","transcript","investor_deck","other"]` at `schema/thesis_shared_slice.py:20` — now `min_filings / min_transcripts / min_investor_decks / min_other` (§4.2). (b) Gate mechanics rewritten to enumerate referenced `src_N` IDs via `_enumerate_referenced_source_ids()` walker and resolve via `artifact.sources[]` typed `SourceRecord` list at `thesis_shared_slice.py:287` (§9.1, §9.2). Explicit `_count_sources_by_type()` helper specified. R1's incorrect `backfill_v1_0_stable_ids` reference removed.

2. **Template lookup user scope broken** (§§8.2, 9.2 — `file_row["user_id"]` doesn't exist at `repository.py:124`). Fixed: `TemplateCatalog.get(template_id)` + `TemplateCatalog.list()` now read user_id from `memory.get_current_user_id()` contextvar (same pattern `thesis_service.py:189` + `mbc_service.py:88` use). `_require_user_scope()` helper raises if no memory scope active. Removed all `user_id` args from public catalog API calls throughout §5.2, §6.2, §8.2, §9.2. `invalidate_user(user_id)` still takes user_id (called from repo writes which already know their user).

3. **`set_process_template` not atomic vs `finalize_handoff`** (§7.2-§7.4). Fixed: new `ResearchRepository.apply_process_template()` repo-level atomic helper wraps the whole mutation in a SINGLE `_handoff_lock()` (same lock `HandoffService._assemble_artifact()` uses at `handoff.py:553`) + SINGLE `BEGIN IMMEDIATE` DB transaction. Introduces conn-scoped private helpers `_update_thesis_qualitative_factors_tx/_update_handoff_artifact_tx/_update_process_template_id_tx` so the outer method owns the lock. Service-layer `set_process_template()` becomes a thin adapter catching the typed exceptions. Also fixed the finalized-vs-no-draft branch: `get_latest_handoff(research_file_id)` WITHOUT `status=` filter first, branch on `.status` → distinguishes "no handoff" (`NoDraftHandoffError`) from "latest is finalized/superseded" (`FinalizedHandoffError`). R1's `get_latest_handoff(status="draft")` couldn't tell the cases apart.

4. **Default valuation method mismatch with prepopulate output** (§4.2 + §11). Fixed: `valuation_methods_allowed` is now `list[str]` (free-form), matching live `Valuation.method: str | None` at `thesis_shared_slice.py:199-200` which is NOT an enum. Removed the `ValuationMethod = Literal[...]` type alias. All 4 default YAML templates add `"relative"` to their `valuation_methods_allowed` lists to remain compatible with `prepopulate.py:323` which emits `method="relative"`. Also: gate fails explicitly when `valuation.method is None` and allow-list is non-empty (§9.1 rule 2).

**Should-fix resolved:**

1. **Template miss = 404, not 422**. Fixed: §10.3 now maps 404 to existing `ActionNotFoundError` at `research_gateway.py:218` (the same class plan #3 G already uses for MBC not-found). Plan #5 does NOT reinvent 404 handling. §10.6 test expectations switched to `ActionNotFoundError`.

2. **`TemplateRequirementsError` placement — not `research_service.py`**. Fixed: created new `api/research/errors.py` module housing all four typed exceptions (`ThesisRequiredError`, `NoDraftHandoffError`, `FinalizedHandoffError`, `TemplateRequirementsError`). Mirrors the `IdeaConflictError` pattern (currently at `research_service.py:13` — that lives WITH its raising module). `handoff.py` imports from `errors.py` without pulling in `research_service.py`.

**Nits resolved:**

1. §10.1 count reconciled: "3 MCP tools + 3 typed errors + 4 agent flags" (was mismatched against §10.3/§10.4).

2. §5.3 routes flattened to bare `ProcessTemplate` / `ProcessTemplate[]` responses instead of `{template: ...}` / `{templates: [...]}` wrappers. Matches live `GET /files` convention at `routes.py:523`.

3. §8.3 prepopulate simplification: live `prepopulate_diligence(sections=...)` at `prepopulate.py:532` already accepts scoped-sections param. Route handler derives `sections=template.section_config.required` before invoking; dispatcher signature unchanged.

### R2 → R3 (2026-04-22)

Codex R3 verdict: **FAIL**. 4 blockers + 2 should-fix + 1 nit. Deep architecture read before revising (per user directive — "consider if we're not understanding the architecture or proposing a flawed architecture"). Diagnosis: ~75% understanding gap / 25% architecture reality. All resolved.

**Blockers resolved:**

1. **Source walker missed citation types**. Fixed: delete the hand-rolled walker, REUSE the live generic recursive iterator `iter_source_refs()` at `handoff.py:245` (promoted from private to public by renaming to `iter_source_refs`). That iterator already handles every ref topology: `_SOURCE_REF_LIST_KEYS` (source_refs lists, citations lists, evidence lists) + `_SOURCE_REF_SCALAR_KEYS` (singular source_ref fields on Catalyst/Risk/etc. at `thesis_shared_slice.py:173,186`). Also: added `DanglingSourceRefError` raise if the walker observes a referenced src_N not in `artifact.sources[]` — defense-in-depth because `_validate_source_refs_resolve` at `handoff.py:290` already rejects these at write time. §9.2.

2. **TemplateCatalog user-scope mismatch with live request model**. Fixed: reverted R2's memory-context-based design; restored explicit `user_id` parameter on `get()` and `list()`. Research routes use explicit DI via `get_trusted_user_id` at `routes.py:81` — applied to every route. `bootstrap_from_idea(user_id, ...)` + `DiligenceService(repo)` + `HandoffService(repo)` all have user_id at hand (via parameter or `repo._current_user_id()`). Only MBC route at `routes.py:962` uses `memory_user_scope` — because `build_model_context()` internally calls `get_current_user_id()`, and the MBC route WRAPS that call. Most research services do NOT install memory scope, so a context-based catalog would fail silently. R3 call sites threading user_id: §6.2 (bootstrap has user_id param), §8.2 (`self._repo._current_user_id()`), §8.3 (route DI), §9.2 (`self._repo._current_user_id()`). R0/R1's explicit-param design was correct; R2 broke it.

3. **finalize_handoff pre-lock race**. Root cause: live `HandoffService.finalize_handoff()` loads `draft` at `handoff.py:494` BEFORE `_handoff_lock` is acquired inside `_assemble_artifact()` at line 553. `set_process_template` could land after the pre-read, leaving finalized gates evaluated against stale state. Fixed with a **3-line delta to `_assemble_artifact`** (§9.2 code sketch): (a) acquire `_handoff_lock` first, (b) re-read the draft row from the DB via `self._repo.get_handoff(handoff_row["id"])`, (c) use `fresh_handoff` throughout the rest of the method. Signature unchanged; `_build_validated_artifact` receives strictly-more-up-to-date data; no breaking change to plan #2. Additive hardening of shipped code.

4. **Import cycle risk (`schema → research.repository → schema`)**. Fixed: **sub-phase A's first step (§4.1a prerequisite) relocates `DILIGENCE_SECTION_KEYS` from `repository.py:226` to `schema/_shared_slice.py`**. Repository.py already imports from `schema/_shared_slice` at line 16 — zero new import direction. 4 live references (`repository.py:226` + `synthesis.py:6,33` + `diligence_service.py:8,67`) updated to import from new location. Purely mechanical; no behavior change. §3.1, §4.1a, §4.2.

**Should-fix resolved:**

1. **Tx helpers underspecified**. Fixed: §7.2 code comments now EXPLICITLY state that `_update_thesis_qualitative_factors_tx` delegates to `_persist_thesis_payload()` at `repository.py:1236` + `_persist_shared_slice_write()` at `repository.py:2019` (preserves thesis version bumps, decisions_log authorship, markdown serialization, artifact normalization). `_update_handoff_artifact_tx` delegates to the existing `update_handoff_artifact()` at `repository.py:2173` body (preserves normalization + `_normalized_metadata` at `handoff.py:410`). `_tx` suffix means ONLY the conn is externally-owned; other behavior preserved verbatim.

2. **Route-level exception mapping too implicit**. Fixed: §7.2 now includes a concrete route sketch for `POST /files/{research_file_id}/process_template` showing exact exception-to-status-body mapping via `_raise_typed_http_error(status, slug, detail)` (the live helper used by MBC routes at `routes.py:968`). §9.3 references the same pattern for the finalize route's new TemplateRequirementsError branch. Error body format `{error: "<slug>", ...detail}` aligns with risk_module's gateway classifier pattern at `services/research_gateway.py:218`.

**Nit resolved:**

1. §5.3 DELETE response contract consistency. Fixed: one contract — 200 with `{"deleted": true, "template_id": "..."}` body. Matches `DELETE /files/{id}` at `routes.py:595-605` which also returns 200 with a body.

### R3 → R4 (2026-04-22)

Codex R4 verdict: **FAIL**. 2 blockers + 2 should-fix + 1 nit. All resolved.

**Blockers resolved:**

1. **Finalize atomicity still incomplete with R3's inside-assemble fresh-read**. R3 fixed window 1 (pre-lock stale draft read) but missed window 2 (lock released after assemble, writes happen outside). Fixed: **§9.2 rewritten — `HandoffService.finalize_handoff()` acquires `_handoff_lock()` at its TOP and holds through fresh-read + assemble + artifact write + status flip**. `_assemble_artifact` renames to `_assemble_artifact_locked` (caller owns lock). `create_new_version()` callsite already wraps its own flow under `_handoff_lock` at `handoff.py:516-537` — gets the method rename but no other change. Net: `apply_process_template` and `finalize_handoff` now serialize on the same lock end-to-end.

2. **§7.2 action-layer signature still claimed "no user_id param, reads from memory context"** despite R3 reverting the catalog design. Fixed: §7.2 action-layer prose updated to `set_process_template(user_id, research_file_id, template_id)` explicit signature matching `bootstrap_from_idea(user_id, ...)`. §5.5 catalog tests rewritten around explicit `user_id` inputs; deleted memory-scope test cases.

**Should-fix resolved:**

1. Tx helper contract made concrete (R3 comments were partly inaccurate — claimed `_persist_shared_slice_write` did markdown serialization, which it doesn't). Fixed: §7.2 now enumerates the exact factoring: (a) version bump reuses `_persist_thesis_payload`'s SQL, (b) shared-slice write delegates to `_persist_shared_slice_write` at `repository.py:2019` (passes existing conn; JSON persist only, no markdown), (c) markdown save via `save_thesis_markdown()` at `thesis_service.py:116` is called AFTER commit (best-effort, not tx-atomic), (d) decisions_log entry appended with authorship="system" for audit parity. The `_update_handoff_artifact_tx` factoring: inlines `update_handoff_artifact` body preserving `_ensure_handoff_artifact` validation + `_normalized_metadata` recompute; only difference is externally-owned conn.

2. DILIGENCE_SECTION_KEYS relocation inventory undercounted (R3 said 4 sites, Codex flagged 6). Fixed: §4.1a now lists all 6 live sites + clarifies that `repository.py:758` (`_normalize_section_wrapper` consumer) works unchanged because repository.py keeps its own re-export after the move. Post-move grep count = 7 (new definition + 6 existing references preserved).

**Nit resolved:**

1. Source-walker code sketch used `_iter_source_refs` (old underscore name) in some places and `iter_source_refs` (new public name) in others. Fixed: §9.2 consistently uses `iter_source_refs` everywhere in code sketches; prose acknowledges the symbol is currently `_iter_source_refs` and sub-phase F performs the rename.

### R4 → R5 (2026-04-22)

Codex R5 verdict: **FAIL**. 1 blocker + 2 should-fix + 0 nits. Convergence: 6→6→4→4→2→1. All resolved.

**Blocker resolved:**

1. **§7.2 `apply_process_template` sketch had two concrete bugs**. Fixed:
   - `draft["artifact"]` is JSON TEXT in the raw row returned by `get_latest_handoff()` — R4 incorrectly treated it as a dict via `.get()`, which would crash or collapse `prior_template_id` to None. R5 uses `_artifact_from_row(draft, file_row=file_row)` (the same helper HandoffService uses internally) to hydrate the artifact before reading `process_template_id`.
   - `research_file_history.created_at` column is `REAL` epoch time (existing writes use `time.time()` / `updates["updated_at"]` numeric, per `repository.py:1257,1533`). R4 wrote `_now_iso()` (ISO string). R5 uses `time.time()` to match column type + existing history-write convention.

**Should-fix resolved:**

1. **Tx helper factoring still inaccurate against live helpers**. Fixed: R5 replaces the custom `_update_thesis_qualitative_factors_tx` helper with a direct call to `self._persist_thesis_payload(conn, thesis_row, updated_payload, increment_version=True)` — live `_persist_thesis_payload` at `repository.py:1236` ALREADY takes a conn parameter; no new helper needed. For the handoff artifact side: R5 INLINES the body of `update_handoff_artifact` (from `repository.py:2173`) into `apply_process_template` (reusing external conn); enumerates the exact body steps (load row, validate via `_ensure_handoff_artifact(for_write=True)`, backfill legacy IDs, schema validation, UPDATE SQL). Removed the incorrect R4 claim about `update_handoff_artifact` owning an `updated_at` bump (it doesn't). Removed the "markdown via `_persist_shared_slice_write`" path (not what that helper does) — markdown save is already spec'd to run after commit via `save_thesis_markdown()` at `thesis_service.py:116` (best-effort, not tx-atomic).

2. **Doc drift between current-state prose and claimed R4 cleanup**. Fixed:
   - §3.1 DILIGENCE_SECTION_KEYS reference: updated from "4 live references" to "6 pre-move live sites" with pointer to §4.1a for the full inventory.
   - §3.1 + §9.2 lock-ownership prose: now explicitly anchored to `finalize_handoff()` + `_handoff_lock` (was ambiguously anchored to `_assemble_artifact` in places).
   - §9.2 `create_new_version()` claim: live grep confirms only ONE caller of `_assemble_artifact` (= `finalize_handoff` at `handoff.py:498`). `create_new_version` calls `_build_validated_artifact` directly (not `_assemble_artifact`) and doesn't need the rename. §9.2 text corrected.

### R5 → R6 (2026-04-22)

Codex R6 verdict: **FAIL**. 1 blocker + 3 should-fix + 1 nit. All resolved.

**Blocker resolved:**

1. **`get_latest_handoff()` defaults `status="draft"`** (live at `repository.py:2220`). R5's `self.get_latest_handoff(int(research_file_id))` call in `apply_process_template` would default to draft-only, collapsing finalized/superseded cases into `NoDraftHandoffError`. Fixed: pass `status=None` explicitly. §3.5 + §7.2 updated.

**Should-fix resolved:**

1. **Tx helper drift**: R5 prose said "inlined" but §7.2 sketch + §7.3 file plan still referenced `_update_handoff_artifact_tx` / `_update_process_template_id_tx` helpers. Fixed: §7.2 sketch now inlines the full `update_handoff_artifact` body verbatim (including `_incoming_handoff_schema_version`, `_ensure_handoff_artifact(for_write=True)`, `_maybe_backfill_legacy_handoff_ids`, `_validate_handoff_artifact`, `_log_handoff_id_backfill`, UPDATE SQL, and reselect). `process_template_id` set directly on the rebuilt artifact dict before persistence (no separate update_process_template_id call — avoids deadlock since that helper opens its own conn). §7.3 file plan rewritten to remove the phantom helpers.

2. **Inline body still missing steps**: Codex flagged `_incoming_handoff_schema_version` + `_log_handoff_id_backfill` + reselect omissions, and a wrong attribution of `_normalized_metadata` recompute to `_ensure_handoff_artifact` (it actually runs during `_build_validated_artifact` at `handoff.py:727`). Fixed: §7.2 comment and code both corrected — metadata recompute attributed to artifact assembly (not `_ensure_handoff_artifact`); all body steps listed.

3. **`save_thesis_markdown` missing from action-layer steps**: R5 had it only in an inline comment. Fixed: added as explicit step 4 in the action-layer procedure with a docstring note about the best-effort (non-tx-atomic) nature + watcher-side re-sync behavior.

**Nit resolved:**

1. Stale `_assemble_artifact` anchors (without `_locked` suffix). Fixed in §2 sub-phase table, §7.2 apply_process_template prose, §9.1 prose, §9.2 section heading, §9.3 file changes.

### R6 → R7 ✅ **PASS** (2026-04-22)

Codex R7 verdict: **PASS**. "I would start sub-phase A without another review round." — Codex R7.

Two should-fix items cleaned up post-PASS (non-gating):
1. Prepopulate route sketch in §8.3 now uses `_artifact_from_row()` to hydrate `handoff["artifact"]` (was treating JSON text as dict — same correction §7.2 already had).
2. `apply_process_template` return dict now includes `"thesis_row"` so the service-layer markdown sync has the updated row without re-reading.

Header status bumped to ✅ PASS.

### Convergence summary

| Round | Blockers | Should-fix | Nits | Disposition |
|---|---|---|---|---|
| R0 | 6 | 3 | 0 | FAIL — first draft |
| R1 | 6 | 7 | 3 | FAIL — deeper research surfaced |
| R2 | 4 | 2 | 3 | FAIL — user_id scope wrong direction |
| R3 | 4 | 2 | 1 | FAIL — architecture deep-read |
| R4 | 2 | 2 | 1 | FAIL — lock coverage incomplete |
| R5 | 1 | 2 | 0 | FAIL — tx helper factoring |
| R6 | 1 | 3 | 1 | FAIL — get_latest_handoff default |
| R7 | 0 | 2 | 2 | ✅ **PASS** — non-gating cleanup |

7 rounds total (comparable to plan #4's 11). Each round surfaced substantive real issues; no bikeshedding.

Architectural decisions (stable from R5 onward):
- Import graph: `schema/_shared_slice` owns `DILIGENCE_SECTION_KEYS`; repository re-exports
- User scope: explicit `user_id` via `get_trusted_user_id` DI; services use param or `repo._current_user_id()`
- Finalize lock: `finalize_handoff()` owns `_handoff_lock` at top, holds through entire flow; `_assemble_artifact` → `_assemble_artifact_locked` rename
- Source walker: reuses `iter_source_refs` (rename of live `_iter_source_refs`)
- Tx composition: `_persist_thesis_payload(conn, ...)` called directly (already conn-scoped); `update_handoff_artifact` body fully inlined with external conn
- `process_template_id` set on rebuilt artifact before persistence (no separate call — avoids nested transaction deadlock)
- History writes: `time.time()` numeric timestamp
- Post-commit markdown sync via `save_thesis_markdown` — best-effort, not tx-atomic

Architectural decisions stable across R5/R6:
- Import graph: `schema/_shared_slice` owns `DILIGENCE_SECTION_KEYS`; repository re-exports
- User scope: explicit `user_id` via `get_trusted_user_id` DI; services use param or `repo._current_user_id()`
- Finalize lock: `finalize_handoff()` owns `_handoff_lock` at top, holds through entire flow
- Source walker: reuses `iter_source_refs` (rename of live `_iter_source_refs`)
- Tx composition: `_persist_thesis_payload(conn, ...)` called directly (already conn-scoped); `update_handoff_artifact` body fully inlined with external conn
- History writes: `time.time()` numeric timestamp
- `process_template_id` set on rebuilt artifact before persistence (no separate update_process_template_id call — avoids nested transaction deadlock)
- Post-commit markdown sync via `save_thesis_markdown` — best-effort, not tx-atomic
