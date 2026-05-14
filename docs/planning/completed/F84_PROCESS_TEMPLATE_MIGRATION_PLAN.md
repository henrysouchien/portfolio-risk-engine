# F84 — Process-Template Migration (canonical-comps auto-invocation)

**Status**: DRAFT R2 — implementation plan for F84 per `docs/TODO.md` row F84.
**Created**: 2026-05-09. **Revised**: 2026-05-09 (R0→R1: 3 P1 + 2 P2 fixes; R1→R2: 3 P2 fixes — idempotent-path bypass, sibling-skill assertion contradiction, D2 prose attr error; see §10 changelog).
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` R6 §7.4 (Phase 2).
**Prerequisites** (all SHIPPED 2026-05-08):
- V2.P11 (producer chain), F83 (consumption skills), F87 (renderer), F82 (persistence), F89 (published-view section title).

**Authoritative code references** (verified by file read 2026-05-09):
- `AI-excel-addin/config/process_templates/{compounder,value,macro,special_situation}.yaml` — 4 templates; all list `peers` in `section_config.required` + `section_config.order`; none include `industry_analysis`.
- `AI-excel-addin/schema/process_template.py:32-43` — `SectionKey` enum **already includes `"industry_analysis"`**; the schema accepts the new key without change.
- `AI-excel-addin/schema/process_template.py:77-93` — `SectionConfig._validate_structure` requires `order` to equal the `required` set if non-empty, and `min_completion` keys must be a subset of `required`. Adding `industry_analysis` requires lockstep edits to all three fields.
- `AI-excel-addin/api/research/diligence_service.py:30,48-50` — `SECTION_TITLES` already maps `"industry_analysis": "Industry Analysis"`; `_section_data_from_artifact` already special-cases `industry_analysis` to read the structured dict from the artifact root.
- `AI-excel-addin/api/research/template_validation.py:45-94` — `_evaluate_template_gates` reads `metadata.diligence_completion[section_key]` and compares to `min_completion[section_key]` per the `_COMPLETION_RANK` order (`empty=0 < draft=1 < confirmed=2`).
- `AI-excel-addin/api/research/repository.py:3253` — the canonical legacy section-update writer (`update_handoff_section`) bumps `diligence_completion[section_key]` to the caller-supplied state. **No equivalent bump exists for `industry_analysis` patch ops** (gap F84 closes).
- `AI-excel-addin/api/research/patch_engine.py:684-703` — `_apply_industry_analysis_patch` updates `payload["industry_analysis"]` in place but **never touches `metadata.diligence_completion`**. Same true for `_apply_set_editorial_peer_set` at `:815` and the F82 register-sources path at `:706`.
- **`AI-excel-addin/api/research/patch_engine.py:236,1328-1348`** — `apply_patch_ops` writes Thesis at line 223 then calls `_refresh_draft_handoff_artifact` (line 236) which rebuilds the handoff artifact via `build_draft_artifact_from_thesis` and saves via `repo.update_handoff_artifact`. **Thesis fold cannot carry `metadata` — `Thesis` model uses `extra="forbid"` (`schema/thesis.py:263`) and has no metadata field; metadata lives on the handoff artifact only (`schema/handoff.py:112`).** R0→R1 finding: the F84 completion bump must fire in the handoff-refresh layer, NOT inside the patch-engine Thesis fold.
- `AI-excel-addin/api/research/handoff.py:416-430,445-452` — `build_draft_artifact_from_thesis` → `_normalized_metadata` preserves prior `diligence_completion` via deepcopy. Bump fires after rebuild but before `repo.update_handoff_artifact` save in `_refresh_draft_handoff_artifact`.
- `AI-excel-addin/api/memory/workspace/notes/skills/position-initiation.md:99-108` — Step 7 already gates on `template.section_config.required` includes `"industry_analysis"`; orchestrates the OLDER 4-write chain (`industry_peer_comparison` → `industry-macro-overlay` → `structural-trends` → `industry-landscape`). **Does NOT call F83 skills.**
- `AI-excel-addin/api/memory/workspace/notes/skills/{critical-factors,thesis-pre-mortem,thesis-review,thesis-consultation}.md` — 4 additional orchestration skills with the same `template.section_config.required` includes `"industry_analysis"` gate; pull `industry_peer_comparison` for context but don't write.
- `AI-excel-addin/api/memory/workspace/notes/skills/peer-curation.md:8,40,42,152` — F83(a) skill is **explicitly user-confirmed** today (`NO PEER WRITE WITHOUT EXPLICIT USER CONFIRMATION`; requires literal `CONFIRM REPLACE {TICKER} PEERS` etc.); F84 introduces an autonomous mode for orchestrated runs.
- `AI-excel-addin/api/agent/shared/tool_catalog.py:427,488` + `tool_handlers.py:729` — **`invoke_skill` accepts only `skill_name` + one optional free-form `args` string (echoed back to skill prose verbatim); `run_agent` similarly takes only a free-form `task` string.** No structured per-call parameters. R0→R1 finding: F84 cannot pass a `caller=` structured parameter; autonomous mode must be encoded in the args/task prose and recognized by the skill.
- `AI-excel-addin/schema/handoff_patch.py` — **NO top-level `Thesis.peers[]` patch op exists** (verified by full-file grep). R0→R1 finding: the legacy `peers` field is non-writeable via patch ops today; D8's "dual-write" risk premise was false.
- `AI-excel-addin/api/research/template_validation.py:55-61` — gates check `min_completion`, NOT `required` membership. All 4 templates have `peers` in `required` but NOT in `min_completion`, so `peers` is non-gating today. Adding `peers` to `min_completion` was never the intent; F84 only adds `industry_analysis` to `min_completion`.
- `risk_module/mcp_server.py:2411` + `risk_module/mcp_tools/industry.py:29` — **`industry_peer_comparison` MCP wrapper exposes only `symbol`, `peers`, `limit`** — does NOT pass through the underlying helper's `editorial_peer_set` or `existing_sources` kwargs. R0→R1 finding: position-initiation must pass curated tickers via `peers="PAYC,PAYX,..."` string; richer pass-through is a follow-up.

---

## 1. Purpose

Close the canonical-comps framework's last production-rollout gate (per `docs/TODO.md` F84). Today an agent only invokes the canonical-comps producer + F83 skills if a process template requires `industry_analysis`; **none of the 4 shipped templates do**, so the chain only runs on explicit `invoke_skill`. F84 flips the templates so the chain auto-invokes inside `position-initiation` and the four sibling orchestration skills, AND adds the F83 consumption skills (`peer-curation`, `comps-narrative`, `post-comps-landscape-refresh`) to the orchestration sequence so the canonical-comps framework runs end-to-end as part of normal thesis production.

**The two gaps F84 closes**:
1. **Template requirement gap**: 4 templates list `peers` (legacy flat field) but not `industry_analysis`; the existing skill gates therefore never fire.
2. **Diligence-completion gap**: when the agent does run the chain (today via explicit `invoke_skill`), no patch op bumps `metadata.diligence_completion["industry_analysis"]`, so a template requiring `min_completion: { industry_analysis: draft }` would fail the gate even after the chain ran successfully. **This is a real wiring bug discovered during F84 research, not a new requirement.**

**What F84 ships** (single AI-excel-addin commit + small risk_module follow-up if any consumer needs adjustment):
- 4 process-template YAML edits (dual-required `peers` + `industry_analysis`).
- Patch engine: passive `diligence_completion["industry_analysis"] = "draft"` bump on each successful canonical-comps patch op apply.
- Orchestration skill updates: position-initiation Step 7 (and the 4 sibling read-only paths) extended to call the F83 skills in the right sequence; peer-curation gains an explicit autonomous-mode branch with mandatory decision-log rationale.
- `peer-curation.md` skill: documented autonomous-mode contract (no user confirmation required when called from orchestration; mandatory `decisions_log` write capturing the autonomous decision).
- Tests: template snapshot/validator parity, patch-engine bump tests, skill markdown sweep tests, orchestration smoke.
- Live verify: full PCTY thesis flow (template → position-initiation → all 7 skills → Thesis populated → diligence_completion=draft → renderer shows industry_analysis).

**What's NOT in this plan**:
- Phase 3 (deprecate `peers` requirement). Phase 3 fires only after Phase 2 has bake time + consumer skills updated to read `industry_analysis` instead of `peers`. Out of scope; named on the TODO row.
- F83 skill semantics changes beyond the autonomous-mode addition for `peer-curation`.
- Renderer changes (F87/F89 already complete).
- Any new agent infrastructure for "auto-skill invocation" — orchestration is via existing skill-prose orchestration, not a new pipeline.
- Frontend UI changes to surface the `industry_analysis` section as a required gate in the diligence sidebar — that's already free from `diligence_service.py:103-130` template-driven section list.

---

## 2. Audit findings

### 2.1 Schema layer is already F84-ready

`SectionKey` Literal at `schema/process_template.py:32-43` already lists `"industry_analysis"`. `SectionConfig._validate_structure` accepts it. **No schema changes required.** The 4 template YAMLs are the only edit surface for the requirement flip.

### 2.2 Diligence-service layer is already F84-ready

`api/research/diligence_service.py`:
- `SECTION_TITLES["industry_analysis"] = "Industry Analysis"` (line 30) — already present.
- `_section_data_from_artifact` (line 48-50) — already special-cases `industry_analysis` to return the structured dict from the artifact root (vs. `_default_section_wrapper_from_artifact` for legacy flat sections).
- `get_state` (line 103-130) walks `template.section_config.order` (or `required` if `order` empty) and emits a section entry with `completionState` and `minRequired`. Adding `industry_analysis` to template `required`/`order` automatically surfaces it in the diligence state response. **No diligence-service code changes required.**

### 2.3 Renderer layer is already F84-ready

- `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx:1585` — dispatch table includes `industry_analysis: renderIndustryAnalysis` (F87).
- `frontend/packages/ui/src/components/research/HandoffReviewView.tsx:24-35` — `SECTION_TITLES` includes `['industry_analysis', 'Industry Analysis']` (F89).

**No renderer changes required.**

### 2.4 Diligence-completion bump gap (NEW finding) — corrected fire site (R1)

`patch_engine.py` apply functions for canonical-comps ops (`_apply_industry_analysis_patch:684`, `_apply_set_editorial_peer_set:815`, `_apply_register_sources:706`) fold the **Thesis** in-memory; they do not touch handoff metadata. Compare to `repository.py:3253` (`update_handoff_section`) which always bumps to the caller-supplied state on the handoff artifact.

**Architectural constraint (R1 correction)**: the patch engine cannot write metadata into the Thesis fold. `Thesis` model uses `extra="forbid"` (`schema/thesis.py:263`); `metadata.diligence_completion` lives on the handoff artifact only (`schema/handoff.py:112`). The fold→Thesis-write→`_refresh_draft_handoff_artifact` flow at `patch_engine.py:223-236` is the architectural seam:
- Line 223: `update_thesis_artifact_if_version_matches` saves Thesis.
- Line 236: `_refresh_draft_handoff_artifact` loads draft handoff, rebuilds via `build_draft_artifact_from_thesis` (which preserves prior `diligence_completion` via deepcopy at `handoff.py:447-448`), and saves with `update_handoff_artifact`.

**Consequence**: a template requiring `min_completion: { industry_analysis: draft }` will FAIL the `_evaluate_template_gates` check at `template_validation.py:55-61` even after the agent runs the full canonical-comps chain successfully. The bump must land in the handoff-refresh layer, NOT inside the Thesis fold.

**Scope of bump (R1 fire site)**:
- Trigger: any successful patch batch that includes one or more **industry_analysis-write ops** (classified at the batch level, not per-op).
- Op IDs in scope: `update_industry_landscape`, `update_comps_narrative`, `replace_industry_peer_comparison`, `set_peer_comparison_sections`, `set_operating_comparison`, `set_editorial_peer_set`, `add_editorial_peer`, `remove_editorial_peer`, `update_macro_overlay`, `replace_structural_trends`. **EXCLUDES `register_sources`** (per F84.D2(b) — register-only batches don't bump).
- Target state: always `"draft"` (F84.D3).
- **Fire site**: between `build_draft_artifact_from_thesis` rebuild and `repo.update_handoff_artifact` save inside `_refresh_draft_handoff_artifact` (`patch_engine.py:1328-1348`). Pass an `applied_industry_analysis: bool` flag from `apply_patch_ops` (computed by scanning `batch.ops` for op classes in scope) down into the refresh function.
- Atomicity: the bump rides the handoff artifact's existing `update_handoff_artifact` write — no new transaction. Matches F82's "single write at end" model. If the Thesis write at line 223 succeeds but the handoff refresh at line 236 fails (currently raises `RuntimeError`), the system is already in an inconsistent state — F84 doesn't change that risk.

### 2.5 Orchestration skill scope

5 orchestration skills already gate on `template.section_config.required` includes `"industry_analysis"`:
1. **`position-initiation.md:99-108`** — full 4-write chain (only writer). **Primary edit target.**
2. `critical-factors.md:73` — pulls `industry_peer_comparison` for context (no write).
3. `thesis-pre-mortem.md:74` — pulls `industry_peer_comparison` for context.
4. `thesis-review.md:84` — re-runs `industry_peer_comparison` for context.
5. `thesis-consultation.md:146` — pulls `industry_peer_comparison` for context.

**Position-initiation is the only writer**; the other 4 already work as-is (they pull data on-demand and don't need to drive the F83 skills). F84 expands position-initiation Step 7 to integrate the 3 F83 skills into the chain. The 4 read-only skills get a one-line note pointing at the new sequence so a future engineer doesn't duplicate.

### 2.6 `peer-curation` autonomous-mode requirement

Today the skill is explicit: "NO PEER WRITE WITHOUT EXPLICIT USER CONFIRMATION" (line 40); requires literal user confirmation strings (line 152-154). F84 needs an autonomous mode for orchestrated runs.

**Design**: skill keeps the user-confirmation contract for direct `invoke_skill` (unchanged). Adds an explicit "called from orchestration" branch where the agent acts on its own judgment AND writes a mandatory `decisions_log` entry capturing:
- Mode: `autonomous`
- Caller: orchestration skill name (e.g., `position-initiation`)
- Proposed peer set + per-peer rationale
- Sources rejected and why (e.g., FMP `stock_peers` rejected as market-cap proxies)
- Caveat for user: "This peer set was selected autonomously during {caller}; review and override via standalone `peer-curation` skill if needed"

This is the user's explicit instruction: agent decides in autonomous runs / testing, writes are clear in the decisions log, standalone skill keeps human-in-loop default.

### 2.7 Test surfaces in scope

- `tests/schema/test_process_template.py` — template fixture parity tests; expect to update fixture expectations.
- `tests/research/test_template_validation.py` (or equivalent) — gate evaluation tests; add cases for `industry_analysis` min_completion gate.
- `tests/research/test_patch_engine_*.py` — add diligence_completion bump assertions to existing canonical-comps op tests.
- `tests/api/research/test_diligence_service.py` (if exists) — confirm `industry_analysis` shows up in section list when template requires it.
- `tests/research/skills/` (if exists) — orchestration skill markdown sweep tests; F84 adds skill markdown that mentions F83 skill names.
- `tests/integration/` — full template→position-initiation→F83 chain smoke (fixture or live).

### 2.8 No frontend changes required

Diligence sidebar, REPORT V1 published view, HandoffReviewView all read template-driven section lists from API responses. Adding `industry_analysis` to a template's `required` list automatically flows through.

---

## 3. Decisions

### F84.D1 — All 4 templates dual-required at once (NOT compounder-only first)

**Decision**: edit all 4 templates (`compounder.yaml`, `value.yaml`, `macro.yaml`, `special_situation.yaml`) in the same commit to dual-require `peers` AND `industry_analysis`.

**Rationale**: Framework §7.4 names "compounder first as reference" but per CLAUDE.md "don't defer to dodge friction" — Phase 2 staging-by-template has no usage signal to wait for pre-launch. All 4 templates share the same skill orchestration (position-initiation et al.), so cherry-picking compounder leaves 3 templates in a half-migrated state with no benefit. User explicit instruction: "lets do full integration."

**Out of scope**: Phase 3 deprecation of `peers` requirement (named on TODO row, separate plan after Phase 2 bake time).

### F84.D2 — Diligence-completion bump fires in `_refresh_draft_handoff_artifact` after batch fold (R1 corrected)

**Decision** (R1 corrected per Codex R0 P1#1; R2 prose-aligned per Codex R1 P2#3): classify ops at the batch level inside `_attempt_apply_patch_ops_once` — compute `applied_industry_analysis: bool = any(isinstance(op, INDUSTRY_ANALYSIS_OP_CLASSES) for op in batch.ops)` (instances expose no `op_class` attr; `_PatchOpBase` only defines `op_id`/`reason` per `schema/handoff_patch.py:34`). Thread this flag down through `_refresh_draft_handoff_artifact` (`patch_engine.py:1328-1348`). Inside the refresh function, after `build_draft_artifact_from_thesis` rebuilds the artifact dict but BEFORE `repo.update_handoff_artifact` saves, do:

```python
if applied_industry_analysis:
    metadata = rebuilt.setdefault("metadata", {})
    completion = metadata.setdefault("diligence_completion", {})
    if completion.get("industry_analysis") != "confirmed":
        completion["industry_analysis"] = "draft"
```

The "don't downgrade `confirmed`" guard mirrors `repository.py:batch_update_handoff_sections:3283` — once a user confirms a section, machine writes can't quietly downgrade it.

**Rationale (corrected)**: R0 said the bump fires inside `_apply_industry_analysis_patch`, but `Thesis` model has `extra="forbid"` and no `metadata` field — `Thesis.model_validate(payload)` at `patch_engine.py:1353` would FAIL the op. Metadata lives on the handoff artifact, written by `_refresh_draft_handoff_artifact`. That refresh call is the architectural seam where this bump belongs.

**Op classification (R1)**: `INDUSTRY_ANALYSIS_OP_CLASSES = {UpdateIndustryLandscapeOp, UpdateCompsNarrativeOp, ReplaceIndustryPeerComparisonOp, SetPeerComparisonSectionsOp, SetOperatingComparisonOp, SetEditorialPeerSetOp, AddEditorialPeerOp, RemoveEditorialPeerOp, UpdateMacroOverlayOp, ReplaceStructuralTrendsOp}`. Verified against `schema/handoff_patch.py` dispatch table at `patch_engine.py:578-608` — Codex confirmed no extra industry-analysis-write op classes exist.

**Edge case for `_apply_register_sources` — pick (b) confirmed**: `RegisterSourcesOp` is excluded from `INDUSTRY_ANALYSIS_OP_CLASSES`. Source-only batches (e.g., legacy backfill, or sources for non-industry sections) correctly do NOT bump industry_analysis completion. If a batch contains BOTH register_sources AND e.g. `set_peer_comparison_sections`, the body op triggers the bump per the classification — register_sources doesn't need to fire it independently.

### F84.D3 — Bump target state is always `"draft"`, never `"confirmed"`

**Decision**: passive bump always sets `"draft"`. `"confirmed"` requires an explicit user action via the existing `update_handoff_section` writer.

**Rationale**: matches the existing semantics (machine writes draft, user confirms). `"confirmed"` requires a UI affordance ("mark this section confirmed") that already exists for legacy sections; adding `industry_analysis` to that flow is a no-code-change consequence of the section appearing in the diligence sidebar (per §2.2). Don't auto-confirm machine-generated content.

### F84.D4 — Orchestration sequence in position-initiation Step 7 (FULL F83 integration)

**Decision**: rewrite Step 7 of `position-initiation.md:99-108` to the full 7-skill canonical-comps sequence:

```
7. Industry research (only when required by the process template).
- Load template; check `template.section_config.required` includes `"industry_analysis"`. Skip otherwise.
- Step 7.0 — Editorial peer set (peer-curation, autonomous mode):
  - Read existing Thesis. If `industry_analysis.editorial_peer_set` is empty/absent:
    - Invoke `peer-curation` skill in autonomous mode (caller="position-initiation").
    - Skill writes set_editorial_peer_set patch op + mandatory decisions_log entry per F84.D5.
- Step 7.1 — Producer chain (canonical-comps data):
  - Call `industry_peer_comparison(symbol="<TICKER>", peers="<comma-separated tickers from editorial_peer_set>", limit=N)`. The MCP wrapper exposes `symbol`/`peers`/`limit` only (per `mcp_server.py:2411`); the agent extracts the ticker list from `Thesis.industry_analysis.editorial_peer_set` and serializes as a CSV string. Per-peer rationale already lives in Thesis from Step 7.0 — no need to re-pass it.
  - Apply returned dict via single batch with: register_sources + replace_industry_peer_comparison + (set_operating_comparison if present in return).
- Step 7.2 — Comps narrative:
  - Invoke `comps-narrative` skill. Skill reads peer_comparison.sections + operating_comparison + thesis context.
  - Skill emits update_comps_narrative patch op.
- Step 7.3 — Macro overlay:
  - Invoke `industry-macro-overlay` skill. Apply with one update_macro_overlay op.
- Step 7.4 — Structural trends:
  - Invoke `structural-trends` skill. Apply with one replace_structural_trends op.
- Step 7.5 — Landscape (cold start vs refresh):
  - If prior `industry_analysis.landscape` exists: invoke `post-comps-landscape-refresh` (F83(c) refresh skill). Apply via update_industry_landscape.
  - Else: invoke `industry-landscape` (cold-start skill). Apply via update_industry_landscape.
- Recovery: if any apply_patch_ops raises PatchStaleRetryExhaustedError, re-read Thesis and decide whether to regenerate that step or abort.
```

**Rationale**:
- Sequence preserves dependency ordering: peer set → producer data → narrative anchored to data → macro/structural context → landscape (refresh-aware) reads everything before it.
- Cold-start vs refresh branch for landscape: F83(c) `post-comps-landscape-refresh` is explicitly designed as a refresh skill (per F83 memory: "comps-aware industry-structure refresh", "Sharpened, not overturned, baseline view — exactly per F83(c) refresh-only design"). Cold start with no prior landscape needs the original `industry-landscape` skill.
- Skill names verified against `AI-excel-addin/api/memory/workspace/notes/skills/`: peer-curation.md, comps-narrative.md, post-comps-landscape-refresh.md, industry-landscape.md, industry-macro-overlay.md, structural-trends.md, industry_peer_comparison (MCP tool, not a skill).

### F84.D5 — peer-curation autonomous mode contract

**Decision**: add a documented autonomous-mode branch to `peer-curation.md`:

```
## Autonomous Mode (called from orchestration only)

When invoked by `position-initiation` (or any other orchestration skill) AS PART OF an automated thesis-production flow, peer-curation operates in autonomous mode:
- NO user confirmation required before set_editorial_peer_set.
- Discovery, ranking, and proposal steps unchanged.
- After write, the skill MUST append a `thesis_append_decisions_log` entry:
  - decision_type: "editorial_peer_set_autonomous"
  - rationale (verbatim required template):
    > Autonomous peer-curation by {caller}. Selected: {peer_list}. Rejected: {rejected_list_with_reasons}. Sources used: {sources}. To override, invoke peer-curation directly: this entry is the audit trail for autonomous operation.
- Direct user invocation (`invoke_skill peer-curation`) ALWAYS uses interactive mode regardless of context. Autonomous mode is gated on an explicit `caller=` parameter passed from the orchestration skill.
```

**Rationale**: user explicit instruction — "agent defaults to curating peers itself" for autonomous runs and testing, "human in the loop normally" for direct invocation, "as long as its clear in its write up / decision." The `decisions_log` is the existing `Thesis.decisions_log` write surface (used today by both peer-curation and position-initiation per `peer-curation.md:95` and `position-initiation.md:163`); no new infrastructure required.

**Caller-detection mechanism (R1 corrected per Codex R0 P1#3)**: `invoke_skill` only accepts `skill_name` + one optional free-form `args` string (`tool_catalog.py:427`); the handler echoes that string back verbatim (`tool_handlers.py:729`). No structured per-call parameter exists. Autonomous mode is therefore encoded in the args string via a recognized prefix:

```
invoke_skill(skill_name="peer-curation", args="MODE=autonomous CALLER=position-initiation TICKER=PCTY")
```

The peer-curation skill prose adds an explicit recognition rule at the top of the existing user-confirmation contract:
> If `args` begins with `MODE=autonomous`, this invocation is from an orchestration skill. Skip the user-confirmation gate; proceed with discovery → ranking → write → mandatory `decisions_log` autonomous-mode entry. Extract the `CALLER=<name>` token (default `unknown` if absent) and use it in the rationale template.
> Otherwise (no `MODE=autonomous` prefix), treat as direct user invocation and follow the user-confirmation contract verbatim.

This is fully backward compatible — direct user invocations never include `MODE=autonomous` so the existing flow is unchanged. The skill prose change is the entire mechanism; no infrastructure additions.

### F84.D6 — Sibling read-only orchestration skills: read persisted first, refetch only if missing/stale (R1 strengthened per Codex R0 P2#4)

**Decision (R1 strengthened)**: `critical-factors.md:73`, `thesis-pre-mortem.md:74`, `thesis-review.md:84`, `thesis-consultation.md:146` each get an updated industry-analysis-conditional clause replacing the current "always re-run `industry_peer_comparison`" pattern with "read persisted first; only refetch if missing/stale":

```
- If `template.section_config.required` includes `"industry_analysis"`:
  - Read persisted state first: `Thesis.industry_analysis.peer_comparison.sections`,
    `Thesis.industry_analysis.operating_comparison`, `Thesis.industry_analysis.landscape`,
    `Thesis.industry_analysis.macro_overlay`, `Thesis.industry_analysis.structural_trends`,
    `Thesis.industry_analysis.comps_narrative` per the skill's specific need.
  - Refetch via `industry_peer_comparison(symbol=..., peers="<editorial tickers>", limit=...)`
    ONLY IF persisted data is missing OR `industry_analysis.peer_comparison.as_of` is stale
    (>30 days old) OR `template_manifest_id` mismatches the active version.
  - For peer set: prefer `Thesis.industry_analysis.editorial_peer_set` (populated by
    position-initiation Step 7.0); fall back to `compare_peers` auto-discovery only if
    editorial set is empty.
  - Do NOT invoke peer-curation, comps-narrative, or post-comps-landscape-refresh from
    this skill — those belong to position-initiation Step 7. If persisted data is missing
    AND this is a thesis-update flow, log a warning and recommend the user run
    position-initiation to populate the canonical-comps chain.
```

**Rationale (corrected)**: R0's "1-line pointer" was insufficient. Once F84 lands, these 4 skills WILL fire the industry-analysis path on every invocation (template now requires it). Re-running `industry_peer_comparison` instead of reading persisted state means duplicate work, double API costs, and potential staleness drift between sibling skills' fetched state vs. position-initiation's persisted state. Read-first + refresh-only-if-stale is the correct pattern.

**Stale threshold**: 30 days based on the framework's quarterly-statement cadence (TTM data refreshes at most 4×/year; intra-quarter refetch is wasteful). Configurable per skill if usage shows lopsided cadence needs.

### F84.D7 — No new patch op or schema additions

**Decision**: F84 introduces zero new schema fields, zero new patch ops, zero new MCP tools.

**Rationale**: every code surface exists. The work is YAML edits + 3 patch-engine apply-function bumps + skill prose updates. Don't invent new infrastructure when existing infrastructure already does the job.

### F84.D8 — `peers` stays in `required` (UI/section-display only); only `industry_analysis` lands in `min_completion` (R1 corrected per Codex R0 P2/P3#5)

**Decision (R1 corrected)**: all 4 templates list BOTH `peers` and `industry_analysis` in `required`/`order` for backward compat with existing diligence-sidebar UI; only `industry_analysis` lands in `min_completion` (per F84.D3, target=`draft`). `peers` does NOT enter `min_completion`.

**Rationale (corrected)**: R0 claimed orchestration skills had to dual-write `peers` + `industry_analysis` to satisfy a `peers` gate. **That premise was false** (Codex R0 P2/P3#5):
- No top-level `Thesis.peers[]` patch op exists in `schema/handoff_patch.py` (Codex full-file grep verified).
- `position-initiation.md:65,153` calls `compare_peers` (the FMP MCP tool) but its typed outputs do NOT emit any `Thesis.peers[]` op — `compare_peers` is a read-only tool call.
- Existing skills explicitly say top-level `Thesis.peers[]` is out of scope (`competitive-position.md:439`, `peer-curation.md:267`).
- All 4 current templates have `peers` in `required` but NOT in `min_completion` — `peers` is purely a UI section marker today, not a gating field.

**Consequence**: keeping `peers` in `required`/`order` is safe and preserves the diligence-sidebar UI ordering. The only writer that actually fires for canonical-comps content is the `industry_analysis.*` patch op chain. **No dual-write needed; no risk of dropping a legacy `peers` write because there isn't one.**

**Phase 3 follow-up scope (separate plan, NOT F84)**: when consumer skills migrate off any remaining `peers` reads (UI side, render side), drop `peers` from `required` entirely. F84 Phase 2 leaves `peers` alone.

---

## 4. Out of scope

- Phase 3 deprecation of `peers` requirement (named on TODO row F84; separate plan after Phase 2 bake).
- Adding new templates (e.g., short-only, paired-trade) — adds `industry_analysis` to `required` from day 1; not part of F84.
- Changing F83 skill semantics beyond the autonomous-mode addition for peer-curation.
- Any skill auto-invocation infrastructure beyond skill-prose orchestration (e.g., a new "template skill registry" — out of scope; orchestration skills already do this via prose).
- Frontend additions to surface autonomous-mode peer-curation decisions in the diligence sidebar (the decision lands in `Thesis.decisions_log` which the renderer already reads).
- Cross-template skill differentiation (e.g., macro template might want different industry-analysis depth) — defer until usage shows the lopsided demand.

---

## 5. Steps

### Phase 1 — Diligence-completion bump in handoff-refresh layer (R1 corrected fire site)

**Step 1.1** — Define op-classification at module scope in `AI-excel-addin/api/research/patch_engine.py` (top of file, near other constants):
```python
INDUSTRY_ANALYSIS_OP_CLASSES = (
    UpdateIndustryLandscapeOp,
    UpdateCompsNarrativeOp,
    ReplaceIndustryPeerComparisonOp,
    SetPeerComparisonSectionsOp,
    SetOperatingComparisonOp,
    SetEditorialPeerSetOp,
    AddEditorialPeerOp,
    RemoveEditorialPeerOp,
    UpdateMacroOverlayOp,
    ReplaceStructuralTrendsOp,
)
```
RegisterSourcesOp is intentionally excluded per F84.D2(b).

**Step 1.2** — In `_attempt_apply_patch_ops_once` (`patch_engine.py:200-236`), compute the flag IMMEDIATELY after `_dry_fold_detailed` succeeds (line 200) so it's available on BOTH the idempotent-replay path (line 204-221) AND the normal path (line 223-236):
```python
applied_industry_analysis = any(
    isinstance(op, INDUSTRY_ANALYSIS_OP_CLASSES) for op in batch.ops
)
```

Refresh on BOTH paths (R2 fix per Codex R1 P2#1):
- **Normal path** (line 236): pass flag to refresh:
  ```python
  _refresh_draft_handoff_artifact(
      repo,
      int(research_file_id),
      thesis_row=refreshed,
      applied_industry_analysis=applied_industry_analysis,
  )
  ```
- **Idempotent-replay path** (line 215, just BEFORE the early return): also fire refresh when industry op was in batch:
  ```python
  if applied_industry_analysis:
      # Idempotent Thesis state but draft handoff metadata may be stale
      # (legacy artifact pre-F84, or first batch after F84 ships).
      original_row = repo.get_thesis_by_id(thesis_id)
      if original_row is not None:
          _refresh_draft_handoff_artifact(
              repo,
              int(research_file_id),
              thesis_row=original_row,
              applied_industry_analysis=True,
          )
  ```

**Why fire on idempotent path**: idempotence is Thesis-equality-only (per `_is_idempotent_replay` at `patch_engine.py:1279`). A pre-F84 thesis with populated `industry_analysis` but empty `diligence_completion["industry_analysis"]` will idempotent-replay any industry op without ever bumping the gate. The idempotent-path refresh is the safety net.

**Step 1.3** — Update `_refresh_draft_handoff_artifact` signature (`patch_engine.py:1328-1348`) to accept `applied_industry_analysis: bool = False`. After `rebuilt = build_draft_artifact_from_thesis(...)` but before `repo.update_handoff_artifact(...)`:
```python
if applied_industry_analysis:
    metadata = rebuilt.setdefault("metadata", {})
    completion = metadata.setdefault("diligence_completion", {})
    if completion.get("industry_analysis") != "confirmed":
        completion["industry_analysis"] = "draft"
```
The "don't downgrade `confirmed`" guard mirrors `repository.py:batch_update_handoff_sections:3283`.

**Step 1.4** — Patch engine apply functions (`_apply_industry_analysis_patch:684-703`, `_apply_set_editorial_peer_set:815`, `_apply_register_sources:706`) get **NO change**. R0 proposed bumping inside the Thesis fold; that path was rejected because `Thesis` model uses `extra="forbid"` and has no `metadata` field.

**Step 1.5** — Tests: extend `tests/research/test_patch_engine_*.py` with new test cases (all going through `apply_patch_ops`, not the apply functions in isolation):
- `test_apply_batch_with_update_industry_landscape_bumps_diligence_completion`
- `test_apply_batch_with_set_editorial_peer_set_bumps_diligence_completion`
- `test_apply_batch_with_set_peer_comparison_sections_bumps_diligence_completion`
- `test_apply_batch_with_only_register_sources_does_not_bump_diligence_completion` (verify F84.D2(b))
- `test_apply_batch_register_sources_plus_industry_op_bumps_once` (mixed batch)
- `test_apply_batch_with_industry_op_does_not_downgrade_confirmed_state` (guard test)
- `test_apply_batch_with_industry_op_creates_metadata_dict_when_absent` (legacy artifact case)
- `test_apply_batch_with_non_industry_op_does_not_bump_industry_analysis` (e.g., update_thesis_section)
- `test_apply_batch_industry_op_idempotent_replay_still_bumps_diligence_completion` (R2: idempotent-path bypass guard per Codex R1 P2#1 — set up Thesis with `industry_analysis` already populated but `diligence_completion["industry_analysis"]` absent; replay an industry op; assert flag bumps after replay)

### Phase 2 — Template YAML edits

**Step 2.1** — `AI-excel-addin/config/process_templates/compounder.yaml`:
```yaml
required: [business_overview, thesis, valuation, assumptions, risks, peers, industry_analysis]
order: [business_overview, thesis, assumptions, valuation, risks, peers, industry_analysis]
min_completion:
  thesis: draft
  valuation: confirmed
  assumptions: draft
  industry_analysis: draft
```

**Step 2.2** — Same pattern for `value.yaml`, `macro.yaml`, `special_situation.yaml`. For `macro.yaml`, insert `industry_analysis` AFTER `peers` in both `required` and `order` (macro template currently orders `[business_overview, peers, thesis, valuation, risks]`; new order: `[business_overview, peers, industry_analysis, thesis, valuation, risks]` — keeps macro's "peers/industry context first" emphasis intact).

**Step 2.3** — Tests: update `tests/schema/test_process_template.py` template parsing fixture expectations (4 template snapshots).

### Phase 3 — peer-curation autonomous mode (R1 corrected: args-string convention)

**Step 3.1** — Add `## Autonomous Mode (called from orchestration only)` section to `AI-excel-addin/api/memory/workspace/notes/skills/peer-curation.md` after the existing user-confirmation contract block (~line 40-42). The section MUST include:
- The recognition rule per F84.D5: "If `args` begins with `MODE=autonomous`, treat as orchestration call; skip user-confirmation gate."
- The CALLER token extraction: "Extract `CALLER=<name>` from `args`; default to `unknown` if absent."
- The TICKER token extraction: "Extract `TICKER=<symbol>` from `args` (autonomous mode requires this)."
- The verbatim decisions_log template per F84.D5.

**Step 3.2** — NO infrastructure change. The skill prose is the entire mechanism; `invoke_skill` already passes `args` verbatim to skill prose (`tool_handlers.py:729`).

**Step 3.3** — Tests:
- Skill markdown sweep test asserts the autonomous-mode block is present and contains the recognition rule + token extraction rules + decisions_log template.
- `tests/integration/test_peer_curation_autonomous.py` (or wherever F83 dogfood tests live) — invoke peer-curation with `args="MODE=autonomous CALLER=position-initiation TICKER=PCTY"` and assert: no user-confirm prompt; `set_editorial_peer_set` patch op emitted; `decisions_log` entry present with autonomous-mode template.
- Backward-compat smoke: invoke without `MODE=autonomous` prefix → asserts user-confirmation prompt still fires (existing F83 behavior preserved).

### Phase 4 — position-initiation Step 7 rewrite

**Step 4.1** — Replace `position-initiation.md:99-108` Step 7 with the F84.D4 7-step sequence (Step 7.0 through Step 7.5).

**Step 4.2** — Add an inline comment near the new Step 7.0 referencing `peer-curation.md` autonomous mode and `position-initiation` as the caller.

**Step 4.3** — Sibling skills (per F84.D6 strengthened): rewrite the industry-analysis-conditional clause in EACH of `critical-factors.md:73`, `thesis-pre-mortem.md:74`, `thesis-review.md:84`, `thesis-consultation.md:146` to the read-first / refetch-only-if-stale block per F84.D6. The block MUST include:
- "Read persisted Thesis.industry_analysis.* first" with the explicit field list.
- "Refetch via `industry_peer_comparison(symbol=..., peers='<editorial tickers>', limit=...)` ONLY IF persisted data is missing OR `as_of` >30 days OR `template_manifest_id` mismatches."
- "Prefer `Thesis.industry_analysis.editorial_peer_set` over `compare_peers` auto-discovery."
- "Do NOT invoke peer-curation/comps-narrative/post-comps-landscape-refresh from this skill — those belong to position-initiation Step 7."

**Step 4.4** — Tests: skill markdown sweep tests assert:
- position-initiation references `peer-curation` (with `MODE=autonomous` invocation pattern), `comps-narrative`, `post-comps-landscape-refresh` by name in Step 7.
- The 4 sibling skills each contain the read-first block (assert presence of "Read persisted Thesis.industry_analysis" and ">30 days" stale threshold).
- **Negative assertion (R2 corrected per Codex R1 P2#2)**: 4 sibling skills do NOT contain any **invocation pattern** against the F83 skills — assert no occurrence of `invoke_skill(skill_name="peer-curation"`, `invoke_skill(skill_name="comps-narrative"`, or `invoke_skill(skill_name="post-comps-landscape-refresh"`. The "Do NOT invoke" prose mention from Step 4.3 is allowed (it's a documentation rule, not an invocation); the negative assertion targets actual invoke_skill call sites only.

### Phase 5 — Live verify

**Step 5.1** — Smoke prep: ensure local agent gateway picks up updated skill markdown (per F83 dogfood pattern; restart gateway).

**Step 5.2** — End-to-end flow:
- Create fresh test Thesis (e.g., PCTY) with template_id=compounder.
- Invoke position-initiation through the analyst-dev gateway.
- Verify Step 7 fires the full chain:
  - Step 7.0 peer-curation (autonomous; writes set_editorial_peer_set + decisions_log entry).
  - Step 7.1 industry_peer_comparison + register_sources + replace_industry_peer_comparison + set_operating_comparison.
  - Step 7.2 comps-narrative + update_comps_narrative.
  - Step 7.3 industry-macro-overlay + update_macro_overlay.
  - Step 7.4 structural-trends + replace_structural_trends.
  - Step 7.5 industry-landscape (cold start) + update_industry_landscape.
- Verify Thesis state after run:
  - `industry_analysis.editorial_peer_set` populated.
  - `industry_analysis.peer_comparison.sections` populated.
  - `industry_analysis.operating_comparison.metric_groups` populated.
  - `industry_analysis.comps_narrative` populated.
  - `industry_analysis.macro_overlay` populated.
  - `industry_analysis.structural_trends` populated.
  - `industry_analysis.landscape` populated.
  - `metadata.diligence_completion["industry_analysis"]` == "draft".
  - `decisions_log` contains the autonomous-mode peer-curation entry per F84.D5.
- Verify template gate evaluation:
  - Call `_evaluate_template_gates(artifact, compounder_template)` returns no `min_completion` failure for `industry_analysis`.

**Step 5.3** — Verify renderer (HandoffReviewView REPORT V1):
- Finalize handoff for the test PCTY thesis.
- Open in `localhost:3000/#research/PCTY` → Form thesis → Refresh Draft → Finalize Report.
- REPORT V1 view shows `Industry Analysis` section populated with comps_narrative + sectioned peer_comparison + operating_comparison + editorial_peer_set + landscape + macro overlay + structural trends.

**Step 5.4** — Document the live-verify run in `AI-excel-addin/docs/qa/skill-qa-f84-live-pipeline-2026-05-09.md` (mirror F82's QA doc).

---

## 6. Tests

| Surface | Test type | New cases |
|---|---|---|
| `tests/schema/test_process_template.py` | Snapshot parity | 4 templates dual-required (compounder/value/macro/special_situation). |
| `tests/research/test_patch_engine_*.py` | Apply behavior | 5 cases per F84 Phase 1 Step 1.4 (industry_analysis ops bump; register_sources does NOT bump; metadata-missing case). |
| `tests/research/test_template_validation.py` | Gate evaluation | `industry_analysis: draft` requirement passes when artifact has `industry_analysis` populated AND `diligence_completion["industry_analysis"]="draft"`; fails when only one is true. |
| `tests/research/skills/` (markdown sweep) | Skill prose contract | position-initiation references the 7 skills by name in Step 7; 4 sibling skills contain the F84.D6 pointer; peer-curation.md contains the autonomous-mode block + decisions_log template. |
| Live integration smoke (Phase 5) | E2E | Full canonical-comps chain populates Thesis + bumps gate + renderer shows section. |

---

## 7. Risks and open questions

### 7.1 Sibling skills firing on every invocation post-F84

`critical-factors`/`thesis-pre-mortem`/`thesis-review`/`thesis-consultation` already gate on `template.section_config.required` includes `"industry_analysis"`. Once F84 lands, these 4 skills WILL fire their conditional industry-analysis paths every time. F84.D6 (strengthened) addresses this: skills now read persisted `Thesis.industry_analysis.*` first, only refetch if missing/stale (>30 days OR template_manifest_id mismatch). **Action**: during Phase 5 live verify, run thesis-review on a populated PCTY Thesis to confirm read-first path works (no spurious `industry_peer_comparison` re-fetch when persisted data is fresh).

### 7.2 ~~`peers` legacy field dual-write~~ — RESOLVED R1

R0 raised this as a risk; Codex R0 review confirmed the premise was false (no top-level `Thesis.peers[]` patch op exists; existing skills explicitly out-of-scope it). F84.D8 (corrected) reflects this — no dual-write needed.

### 7.3 Macro template's "peers-first" ordering

Macro template currently puts `peers` second in `order` (right after `business_overview`). F84 inserts `industry_analysis` immediately after `peers` to preserve the macro template's "context first" intent. Confirm with user that this ordering is intended for the macro template OR move `industry_analysis` to the same trailing position as the other 3 templates.

### 7.4 No interrupt mechanism for partial gateway failures mid-chain

If Step 7.2 (comps-narrative) fails after Step 7.1 (producer + replace_industry_peer_comparison) succeeded, the Thesis ends with partial industry_analysis state. Existing position-initiation Step 7 already has this risk. F84 doesn't introduce new failure modes — but the chain is longer, so the partial-failure surface area grows. Mitigation: each F83 skill is independently invoke-able, so user can manually re-run the failed one. Document this in the new Step 7 prose.

### 7.5 peer-curation autonomous-mode could disagree with user's prior editorial choices

If user previously set `editorial_peer_set` manually (via standalone peer-curation), then orchestration in autonomous mode finds the set populated and SKIPS Step 7.0 (per F84.D4: only fires if `editorial_peer_set` empty/absent). Correct behavior — preserves user choice. If user wants to force a re-curation, they invoke peer-curation directly in interactive mode. **No change needed**; document this in the new Step 7.0 prose.

---

## 8. Verification checklist (pre-commit)

- [ ] All 4 template YAMLs updated; YAML parses; ProcessTemplate validates.
- [ ] `apply_patch_ops` classifies industry_analysis ops via `INDUSTRY_ANALYSIS_OP_CLASSES` and threads `applied_industry_analysis: bool` into `_refresh_draft_handoff_artifact`.
- [ ] `_refresh_draft_handoff_artifact` bumps `diligence_completion["industry_analysis"]` to "draft" when flag is set; does NOT downgrade `"confirmed"`.
- [ ] No bump fires for register-sources-only batches (F84.D2(b) negative test passes).
- [ ] peer-curation.md contains autonomous-mode block with `MODE=autonomous` recognition rule, `CALLER=`/`TICKER=` token extraction, and verbatim decisions_log template.
- [ ] position-initiation.md Step 7 lists all 7 sub-steps with skill names verified to exist in `api/memory/workspace/notes/skills/`.
- [ ] 4 sibling skills contain the F84.D6 pointer.
- [ ] All new and updated tests pass: `pytest tests/schema/test_process_template.py tests/research/test_patch_engine_*.py tests/research/test_template_validation.py -v`.
- [ ] Skill markdown sweep test passes.
- [ ] Live verify: full PCTY chain run captured in QA doc; diligence_completion gate passes; REPORT V1 renders Industry Analysis section.

---

## 9. Acceptance

F84 is complete when:
1. All 4 process templates dual-require `peers` + `industry_analysis`.
2. The canonical-comps chain auto-fires inside `position-initiation` Step 7 when template requires `industry_analysis`.
3. `peer-curation` writes autonomously in orchestration context with mandatory decisions_log audit trail.
4. `metadata.diligence_completion["industry_analysis"]` bumps to "draft" automatically on any successful canonical-comps patch op apply.
5. Template `min_completion` gate for `industry_analysis: draft` passes after position-initiation completes.
6. REPORT V1 published view renders the Industry Analysis section for theses produced via the new chain.
7. All tests pass; live verify QA doc committed.

After F84 ships, only Phase 3 (deprecate `peers` from required, after consumer-skill migration) remains in the canonical-comps framework rollout.

---

## 10. Changelog

### R0 → R1 (2026-05-09) — addresses Codex R0 FAIL

**P1 fixes (3)**:
- **D2 implementation site corrected**: bump moved from inside `_apply_industry_analysis_patch` (would FAIL `Thesis.model_validate` because Thesis has `extra="forbid"` and no `metadata` field) to `_refresh_draft_handoff_artifact` (the architectural seam where handoff metadata is written). New op-classification constant `INDUSTRY_ANALYSIS_OP_CLASSES` at module scope; flag threaded from `apply_patch_ops` through refresh call. Steps 1.1-1.5 rewritten.
- **D4 MCP wrapper limitation acknowledged**: `industry_peer_comparison` MCP tool exposes only `symbol`/`peers`/`limit`; orchestration passes editorial peer set as comma-separated `peers` string. Per-peer rationale lives in Thesis from Step 7.0 — not lost. Step 7.1 prose updated.
- **D5 caller-detection mechanism corrected**: `invoke_skill` only accepts a free-form `args` string (no structured per-call params). Autonomous mode now encoded as `MODE=autonomous CALLER=... TICKER=...` prefix in args; peer-curation skill prose recognizes the prefix. No infrastructure changes needed.

**P2 fixes (2)**:
- **D6 strengthened from 1-line pointer to read-first/refetch-only-if-stale**: sibling skills (critical-factors, thesis-pre-mortem, thesis-review, thesis-consultation) will now fire industry-analysis paths every time post-F84. Just adding a pointer would leave them re-running `industry_peer_comparison` redundantly. New rule: read persisted `Thesis.industry_analysis.*` first; refetch only if missing OR `as_of` >30 days OR `template_manifest_id` mismatch. Step 4.3 rewritten with verbatim block requirements.
- **D8 dual-write claim removed**: R0 claimed orchestration must dual-write `peers` + `industry_analysis`. Codex grep confirmed no top-level `Thesis.peers[]` patch op exists; existing skills explicitly out-of-scope it. Updated D8 to document `peers` as a non-gating UI section marker (in `required` for sidebar display, NOT in `min_completion`). §7.2 risk marked RESOLVED.

**Audit findings additions (§2)**:
- Added `patch_engine.py:236,1328-1348` reference for the refresh-layer fire site.
- Added `handoff.py:416-430,445-452` reference for `build_draft_artifact_from_thesis` metadata preservation.
- Added `tool_catalog.py:427,488` + `tool_handlers.py:729` reference for `invoke_skill` args contract.
- Added `schema/handoff_patch.py` no-peers-op finding.
- Added `template_validation.py:55-61` `min_completion`-only gating finding.
- Added `mcp_server.py:2411` + `mcp_tools/industry.py:29` MCP wrapper limitation finding.

**Status**: R1 FAIL → R2 PENDING REVIEW.

### R1 → R2 (2026-05-09) — addresses Codex R1 FAIL

**P2 fixes (3)**:
- **Idempotent-replay path bypass (R1 P2#1)**: `_attempt_apply_patch_ops_once` returns at `patch_engine.py:215` on idempotent-replay BEFORE reaching `_refresh_draft_handoff_artifact` at line 236. So a pre-F84 thesis with populated `industry_analysis` but empty `diligence_completion["industry_analysis"]` would idempotent-replay industry ops indefinitely without ever bumping the gate. Step 1.2 rewritten to compute the flag immediately after `_dry_fold_detailed` (line 200) and refresh on BOTH paths — normal path AND idempotent-replay path when industry op is in batch. New regression test `test_apply_batch_industry_op_idempotent_replay_still_bumps_diligence_completion`.
- **§4.4 negative-assertion contradiction (R1 P2#2)**: R1 Step 4.3 required sibling skills to contain the documentation rule "Do NOT invoke peer-curation/comps-narrative/post-comps-landscape-refresh" while Step 4.4 negative assertion required NO mention of those names — direct contradiction. Step 4.4 narrowed to assert no `invoke_skill(skill_name="...")` invocation pattern against the F83 skills; documentation mentions are explicitly allowed.
- **D2 prose `op.op_class` attr error (R1 P2#3)**: D2 prose said `op.op_class in INDUSTRY_ANALYSIS_OP_CLASSES` but `_PatchOpBase` only defines `op_id`/`reason` (`schema/handoff_patch.py:34`). D2 prose aligned with Step 1.2's correct `isinstance(op, INDUSTRY_ANALYSIS_OP_CLASSES)` form.

**D8 caveat (Codex non-blocking note)**: confirmed zero top-level `peers` patch ops, but legacy repo/API/prepopulate paths can still write `peers`. Doesn't reintroduce a gating issue (gates check `min_completion` only, and `peers` is not in `min_completion` per §2 audit). Noted here for completeness; no plan change.

**Status**: R2 PASS pending Codex re-review.

