# Plan #6 — `ModelInsights` + `PriceTarget` + `HandoffPatchOp` v1.0 (Investment Schema Unification)

**Status**: 🟡 **R0 SKELETON** — awaiting design-content fill + Codex review.

**Last revised**: 2026-04-23 (skeleton stubbed post-plan-#5 ship).

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

[To be refined — candidate non-goals from §6.4:]
- Auto-applying patches without analyst review (always human-in-the-loop)
- Retroactive regeneration of ModelInsights from old model builds
- Patch ops targeting Handoff-only fields (idea_provenance, assumption_lineage) — deferred to follow-on plans per §6.4 R5
- Cross-model insight aggregation (this plan is per-model-build)
- Frontend patch-review UI — skeleton API only; UI deferred

---

## 2. Sub-phase summary

[Preliminary breakdown — refine during R0→R1]

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| A | `ModelInsights` + nested types Pydantic contracts | `schema/model_insights.py`; nested types for `DriverSensitivity`, `ImpliedAssumption`, `RisksSurfaced` | ~1 day | — |
| B | `PriceTarget` Pydantic contract | `schema/price_target.py`; reuses `ValuationMethod` Literal from plan #5 alignment (str|None free-form) OR unified enum decision per §6.4 R3 | ~0.5 day | A |
| C | `HandoffPatchOp` discriminated-union grammar | `schema/handoff_patch.py`; typed op classes for all ~20 operations enumerated in §6.4 (assumptions CRUD, thesis headline fields, quantitative framing, valuation, consensus/differentiated view, risks CRUD, catalysts CRUD, invalidation triggers CRUD) | ~2 days | — |
| D | Storage + service layer | `api/research/model_insights_service.py`; DB persistence (SQLite or JSON-column on existing rows?); `model_insights_id` key | ~1.5 days | A, B, C |
| E | Patch application engine | `api/research/patch_engine.py`; applies `HandoffPatchOp` to `Thesis` (SoT); HandoffArtifact auto-re-derives via shared-slice; stable-ID invariant enforcement; dry-run vs apply modes | ~2 days | C |
| F | Modeling-studio integration | AI-excel-addin `build_model_orchestrator.py` emits ModelInsights + PriceTarget on build; optional scenario runs emit additional ModelInsights; `handoff_patch_suggestions` populated from orchestrator heuristics | ~1.5 days | A, B, C, D |
| G | risk_module MCP surface | MCP tools: `get_model_insights`, `get_price_target`, `preview_patch_ops`, `apply_patch_ops`; typed errors + agent flags | ~1.5 days | A-F |
| H | E2E + skill integration | Integration tests: build → ModelInsights → analyst reviews → patches applied → Thesis updated → HandoffArtifact re-derived. Skill integration: `/thesis-review` consumes ModelInsights + suggests applies. | ~1 day | A-G |
| I | Docs | `SKILL_CONTRACT_MAP.md` updates; `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §12 mark SHIPPED | ~0.5 day | H |

**Total estimate**: ~11.5 days (subject to revision during review rounds).

### 2.1 Dependency graph

```
        A (ModelInsights type)       B (PriceTarget type)       C (HandoffPatchOp grammar)
             │                             │                              │
             └─────────────┬───────────────┘                              │
                           ▼                                              │
                        D (storage)                                       │
                           │                                              │
                           ├──────────────────────────────────────────────┤
                           ▼                                              ▼
                        F (studio producer)                           E (patch engine)
                           │                                              │
                           └──────────────────┬───────────────────────────┘
                                              ▼
                                          G (MCP surface)
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
- UUIDv5? Deterministic hash? Per-build nonce? — to be decided

### 3.3 Storage model
- Where do ModelInsights + PriceTarget live? Candidates: new `model_insights` table, JSON column on `research_handoffs`, JSON column on `research_files`, or purely ephemeral (regenerated on demand from ModelBuildContext)
- Retention: how many historical ModelInsights per model_build_context_id?

### 3.4 Patch-apply semantics
- Dry-run vs apply modes
- Idempotency: re-applying the same op should be a no-op
- Conflict resolution when two patches target the same stable_id
- Audit trail: `research_file_history` entries with `event_type='patch_applied'`?

### 3.5 HandoffPatchOp validation
- Per-op target_id must exist in Thesis at apply time (else hard-fail with typed error)
- Per-op value shape must match op's schema (discriminated union)
- Batching semantics: apply as a single transaction or per-op?

### 3.6 Cross-plan alignment
- Plan #1 (Thesis): patches write to Thesis; HandoffArtifact re-derives via shared-slice. No Thesis schema changes.
- Plan #2 (HandoffArtifact): `scorecard_ref` field (already shipped) now has a typed consumer via PriceTarget.
- Plan #3 (ModelBuildContext): ModelInsights references a `model_build_context_id`.
- Plan #5 (ProcessTemplate): template's `valuation_methods_allowed` gate interacts with `PriceTarget.method` — do we enforce at apply time or at finalize time only?

---

## 4. Sub-phase A — `ModelInsights` Pydantic type + validators

[To fill — mirror plan #5 §4 pattern]

### 4.1 Goal

Pydantic v2 `ModelInsights` + nested types in `AI-excel-addin/schema/model_insights.py` matching §6.4 shape with `frozen=True`.

### 4.2 Design

[Code sketch — fill from §6.4]

### 4.3 Files to create

[Fill: new schema/model_insights.py, schema/__init__.py re-export, tests/schema/test_model_insights.py]

### 4.4 Tests

[Fill — validator coverage, frozen invariants, boundary test, JSON round-trip]

---

## 5. Sub-phase B — `PriceTarget` Pydantic type + validators

### 5.1 Goal

Pydantic v2 `PriceTarget` in `AI-excel-addin/schema/price_target.py`. Reuses stable-ID convention from plan #5 — does NOT use UUIDv5 for `price_target_id` (human-readable? deterministic from inputs?).

### 5.2 Design

[Code sketch — fill from §6.4]

### 5.3 Files to create

### 5.4 Tests

---

## 6. Sub-phase C — `HandoffPatchOp` discriminated-union grammar

### 6.1 Goal

Pydantic v2 discriminated-union type for model→Thesis feedback ops. All ~20 ops enumerated in §6.4 — CRUD on assumptions, thesis headline fields, quantitative framing, valuation, consensus/differentiated view, risks, catalysts, invalidation triggers.

### 6.2 Design

[Full op enumeration — fill from §6.4 lines 489-578]

### 6.3 Files to create

### 6.4 Tests

[Discriminator coverage — every op type validates independently; invalid combinations reject; JSON round-trip per op type]

---

## 7. Sub-phase D — Storage + service layer

### 7.1 Goal

### 7.2 Design

### 7.3 Files to create

### 7.4 Tests

---

## 8. Sub-phase E — Patch application engine

### 8.1 Goal

Apply `HandoffPatchOp` lists to `Thesis` (SoT) with stable-ID targeting, per-op validation, transactional semantics, dry-run support.

### 8.2 Design

[Critical: stable_id → Thesis field traversal logic. Reference existing Thesis field access patterns from `thesis_service.py`. HandoffPatchOp target format: e.g., `{assumption_id: str}` resolves to `thesis.assumptions[i] where assumptions[i].assumption_id == target`.]

### 8.3 Files to create

### 8.4 Tests

[Critical coverage: each op type end-to-end, dry-run vs apply, missing stable_id raises typed error, transactional rollback]

---

## 9. Sub-phase F — Modeling-studio integration

### 9.1 Goal

AI-excel-addin `build_model_orchestrator.py` emits `ModelInsights` + `PriceTarget` on model build. Optional scenario runs emit additional `ModelInsights`. `handoff_patch_suggestions` populated from orchestrator heuristics.

### 9.2 Design

[Which heuristics? What determines `suggests_patch: bool` on `implied_assumptions`?]

### 9.3 Files to modify/create

### 9.4 Tests

---

## 10. Sub-phase G — risk_module MCP surface

### 10.1 Goal

MCP tools for agent access:
- `get_model_insights(research_file_id, model_build_context_id?)` — retrieve
- `get_price_target(research_file_id)` — retrieve
- `preview_patch_ops(handoff_patch_ops: list)` — dry-run against Thesis, return diff
- `apply_patch_ops(handoff_patch_ops: list, research_file_id)` — transactional apply

### 10.2 Design

### 10.3 Agent flags

[To design: `model_insights_fresh`, `patch_suggestions_pending`, `patch_apply_failed`, etc.]

### 10.4 Tests

---

## 11. Sub-phase H — E2E + skill integration

### 11.1 E2E scenarios

[Mirror plan #5 §11 structure]

1. Full chain: research_file + model build → ModelInsights emitted → analyst reviews suggestions → applies patches → Thesis updated → HandoffArtifact re-derived → finalize passes template gates
2. Scenario-weighted PriceTarget: base/bull/bear model runs → three ModelInsights + one composite PriceTarget
3. Patch apply validation: missing stable_id → typed error
4. Patch apply transaction: batch of 5 ops, one fails mid-batch → full rollback, no partial apply
5. ... more to define

### 11.2 Skill integration

- `/thesis-review` skill consumes latest ModelInsights + surfaces suggestions to analyst
- `/thesis-pre-mortem` skill considers `risks_surfaced` from ModelInsights
- `/position-initiation` skill uses PriceTarget in initial sizing decision
- [SKILL_CONTRACT_MAP.md row additions]

---

## 12. Sub-phase I — Docs

- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` — ModelInsights + PriceTarget + HandoffPatchOp rows; Pattern updates for model→Thesis feedback loop
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §12 — mark plan #6 SHIPPED

---

## 13. Success criteria

[To fill — per-plan pattern from plan #5 §12/13]

- `ModelInsights v1.0` + `PriceTarget v1.0` + `HandoffPatchOp v1.0` land as Pydantic frozen types
- Modeling studio emits both on build
- Patch engine applies typed ops to Thesis with stable-ID targeting
- G3 + G4 actually closed: analyst can review/apply typed suggestions instead of parsing prose

---

## 14. Rollback

[To fill]

---

## 15. Open design questions

1. **Where does ModelInsights persist?** — JSON column on existing row vs new table. Leans toward new `model_insights` table since multiple can exist per handoff (build + scenario runs).
2. **Is ModelInsights regenerable?** — Can we recompute from ModelBuildContext + model state, or is it a snapshot? Leans toward snapshot (explicit persist on build) because build heuristics may change between invocations.
3. **Unified valuation method enum?** — §6.4 R3 says unified. Plan #5 kept `valuation_methods_allowed: list[str]` free-form to match live `Valuation.method: str | None`. Does plan #6 tighten to a Literal, or stay free-form?
4. **HandoffPatchOp op application order** — for batches with interdependent ops (e.g., add_assumption + update_thesis_quantitative referencing the new assumption), is order preserved? Leans yes, but explicit contract needed.
5. **PriceTarget composite vs per-scenario** — single PriceTarget per handoff (aggregated across bull/base/bear) or one per scenario? §6.4 sketch shows composite; revisit during design.
6. **Patch conflict resolution** — two patches targeting the same stable_id in the same batch. Last write wins? First write wins? Error? Leans error (explicit, no surprise).

---

## 16. Change log

### R0 skeleton stubbed (2026-04-23)

Initial skeleton drafted post-plan-#5 ship. Based on §6.4 of master plan. Structure mirrors plan #5 (9 sub-phases, ~11.5 days estimate).

**Before R1 Codex review, flesh out:**
- §3 cross-cutting concerns (especially §3.3 storage model, §3.4 patch apply semantics)
- §4 / §5 / §6 code sketches (lift from §6.4 lines 461-590 of master plan)
- §7 / §8 / §9 / §10 design details
- §11 full E2E scenario list
- §13 success criteria
- §14 rollback plan
- Test matrices for each sub-phase

Design questions in §15 require answers before implementation can start. Several have provisional leanings noted.

**Ready for R1 Codex review after**: §3-§6 code sketches filled and open design questions resolved.
