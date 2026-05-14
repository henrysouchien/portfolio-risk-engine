# F83 — Canonical Comps Consumption Skills

**Status**: DRAFT R4 — implementation plan for F83 (canonical-comps consumption skills) per `docs/TODO.md` row F83 (commit `8097cacc`).
**Created**: 2026-05-08. **Revised**: 2026-05-08 (R1: 4P1 → R2: 4P1+1P2 → R3: 3P1 → R4: 2P1+2P2; see §11 changelog).
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` R6 — §6 (Track C) names peer-curation explicitly; §7.3 (SIA wiki + methodology) explicitly defers skill design downstream.
**Prerequisites**:
- V2.P11 SHIPPED 2026-05-07 — Tracks 0/A/B/C all live (10 commits across risk_module + AI-excel-addin; 45 new tests passing; flag-off behind `INDUSTRY_ANALYSIS_V1_2_ENABLED`).
- Plan committed at `b0300b86`; bug B in `compare_peers` filed at `376cb15d`.
- TODO.md V2.P11 row + F81-F86 rollup committed at `8097cacc`.

**Authoritative code/skill references** (verified by file read 2026-05-08):
- `AI-excel-addin/schema/thesis_shared_slice.py:504-510` — `IndustryAnalysis` 6 fields (landscape, peer_comparison, macro_overlay, structural_trends, editorial_peer_set, operating_comparison)
- `AI-excel-addin/api/memory/workspace/notes/skills/competitive-position.md:248,260,287` — writes `set_editorial_peer_set` + `add_editorial_peer` as 1 of 4 channels in 4-pillar strategic eval
- `AI-excel-addin/api/memory/workspace/notes/skills/comparative-analysis.md:467` — confirms "competitive-position writes the canonical editorial_peer_set; this skill refreshes editorial_peer_set only when Step 4 finds peer-set drift"
- `AI-excel-addin/api/memory/workspace/notes/skills/peer-comparison-analysis.md` — UNCOMMITTED ad-hoc no-Thesis ranking skill (created 2026-05-08 ~10:12am; `persist_state: false`, no patch ops, max 8 turns / $1.50)
- `AI-excel-addin/api/memory/workspace/notes/methodology/strategic-evaluation/{comparative-analysis,competitive-position}.md` — methodology units already exist for those two skills
- `AI-excel-addin/api/memory/workspace/notes/methodology/wiki/_index.md` — 32 concepts + 11 frameworks + 7 patterns + 10 cases (incl. `paylocity.md` HR-Payroll exemplar)
- `AI-excel-addin/api/memory/workspace/notes/skills/_playbook.md` — skill-wiring playbook with exemplars `business-quality-assessment.md` + `financial-red-flags.md`
- `CANONICAL_COMPS_FRAMEWORK_PLAN.md:317` — explicit naming of peer-curation skill: "proposes a peer list (e.g., from FMP discovery + sub-industry classifier + user description), user confirms, skill writes via `set_editorial_peer_set` / `add_editorial_peer` patch ops"
- `AI-excel-addin/config/process_templates/{compounder,value,macro,special_situation}.yaml` — all require `peers` section, none reference `peer_comparison`/`operating_comparison`/`editorial_peer_set` (F84 gate; out of scope here)

---

## 1. Purpose

Three new agent-callable skills that consume V2.P11 producer artifacts. Closes F83 of the canonical-comps follow-ups in `docs/TODO.md`.

- **F83(a) `peer-curation`** — user-in-the-loop confirmation peer-curation. Proposes peer set from FMP discovery + sub-industry classifier + user description, **shows the user the proposed list with rationale per peer**, applies `set_editorial_peer_set` (full replace) or `add_editorial_peer` (augment) **only after explicit user confirmation**.
- **F83(b) `comps-narrative`** — synthesizes commentary across `peer_comparison.sections` (Track A) + `operating_comparison` (Track B) into a single readable narrative. Cross-section reading, NOT per-peer relative_position (that's `comparative-analysis`'s job).
- **F83(c) `post-comps-landscape-refresh`** (renamed at R2 from `industry-analysis-synthesis` per Codex P1.B reframe) — narrow comps-aware refresh of existing `Thesis.industry_analysis.landscape` field. Runs AFTER comps populate (peer_comparison + operating_comparison present). Reads new comps cells + SIA-wiki industry-structure articles + the existing `landscape` narrative + `competitive-position.md` 4-pillar lens; rewrites the `landscape` narrative to integrate the new comps signals via existing `update_industry_landscape` patch op. NOT a parallel synthesizer to `competitive-position` (which runs at initiation, before comps); this is a focused post-comps update of an existing field.

What's NOT in this plan:
- Producer code (V2.P11 already shipped)
- F81 renderer (gates flag-on display; separate plan)
- F82 persistence-to-Thesis (gates the producer-to-Thesis-to-skill pipeline; separate plan; F83(b)/F83(c) live smokes use fixture-injection until F82 lands per §5)
- F84 process-template migration (gates which templates invoke F83 skills; separate plan)
- v1.1 reference industry data (F85; F83 skills are industry-agnostic)
- v2 enhancements (F86)

---

## 2. Audit findings (grounded by file read 2026-05-08)

### 2.1 Existing skill landscape (peer / comps / industry space)

| Skill | Status | Scope | Writes patch ops | When-NOT-to-use anchor |
|---|---|---|---|---|
| `peer-comparison-analysis` | UNCOMMITTED (AI-excel-addin) | Ad-hoc, no Thesis | None (returns ranking table only) | "Full strategic operating-comps work that needs a Thesis artifact; use `comparative-analysis`" |
| `competitive-position` | shipped | Full 4-pillar strategic eval, Thesis-bound | `set_editorial_peer_set`, `add_editorial_peer` (1 of 4 channels) + 3 industry_analysis section ops | "Pure peer metric table — use `comparative-analysis` after this skill defines the curated peer set" |
| `comparative-analysis` | shipped | Operating comps after `competitive-position`, Thesis-bound | `replace_industry_peer_comparison` (primary); `set_editorial_peer_set` only on drift | "Pure strategic-evaluation framing — use `competitive-position`; this skill tests whether the strategy is working in the numbers" |
| `industry-landscape` | shipped | Single-section industry structure narrative | `update_industry_landscape` | "User needs deterministic peer metric table — use industry peer comparison tool" |
| `industry-macro-overlay` | shipped | Single-section macro narrative | `update_macro_overlay` | (sector macro only) |
| `structural-trends` | shipped | Single-section structural shifts narrative | `update_structural_trends` | (one section, narrow) |

### 2.2 F83 boundary lines (vs existing skills)

- **F83(a) `peer-curation` is NOT a duplicate of `competitive-position`'s editorial_peer_set channel.** The differentiator is the conversational confirmation step: `competitive-position` writes editorial_peer_set as a side effect of running 30-min, 20-turn 4-pillar strategic eval. F83(a) is a focused mode for users who want to LOCK IN or EDIT peer set without re-running strategic eval. Use case: "I trust my strategic read; I just want to update the peer roster after a new IPO peer or M&A."
- **F83(a) is NOT a duplicate of `peer-comparison-analysis`** — that skill is no-Thesis, no patch ops, ad-hoc rankings; F83(a) is Thesis-bound and writes to `industry_analysis.editorial_peer_set`.
- **F83(b) `comps-narrative` is NOT `comparative-analysis`'s per-peer `relative_position` narrative** (which is a single peer's standing in one column of one row). F83(b) is cross-section/cross-metric/cross-peer commentary — a reading of the full Track A `peer_comparison.sections` + Track B `operating_comparison` artifacts as a coherent picture.
- **F83(c) `post-comps-landscape-refresh` is NOT `industry-landscape`** even though both write to `landscape`. `industry-landscape` is **comps-blind**: it pulls EDGAR Item 1 + transcripts to refresh `landscape.narrative` and explicitly says "Do NOT touch `peer_comparison`" (per `industry-landscape.md:56`). F83(c) is **comps-aware**: it reads `peer_comparison.sections` + `operating_comparison.metric_groups` + the existing `landscape` narrative + SIA-wiki + 4-pillar methodology, and rewrites the narrative to integrate comps signals. Both target the same `landscape: IndustryLandscape` field; **last writer wins** — the skill invoked most recently determines current state. Operationally distinct triggers: `industry-landscape` for filing-driven section refresh; F83(c) for post-comps-update integration. F83(c) does NOT invoke other skills (synthesizer of inputs, not orchestrator).

### 2.3 IndustryAnalysis schema (target write surface)

Per `thesis_shared_slice.py:504-510`:
```python
class IndustryAnalysis(_ContractModel):
    landscape: IndustryLandscape | None = None        # industry-landscape skill writes
    peer_comparison: IndustryPeerComparison | None = None  # Track A producer writes
    macro_overlay: MacroOverlay | None = None         # industry-macro-overlay skill writes
    structural_trends: list[StructuralTrend] = Field(default_factory=list)  # structural-trends skill writes
    editorial_peer_set: list[EditorialPeer] = Field(default_factory=list)   # competitive-position; comparative-analysis on drift; F83(a) target
    operating_comparison: OperatingComparison | None = None  # Track B producer writes
```

**F83(a)**: writes only `editorial_peer_set` via existing Track 0 patch ops. No schema bump.
**F83(b)**: writes new typed field `IndustryAnalysis.comps_narrative: CompsNarrative | None` via new `update_comps_narrative` patch op. `CompsNarrative` mirrors existing `IndustryLandscape` shape (`thesis_shared_slice.py:404-406`): `narrative: str` + `citations: list[SourceId]` so cell-level provenance is preserved through patch validation, markdown round-trip, and downstream tooling. Patch op shape mirrors `UpdateIndustryLandscapeOp` (`handoff_patch.py:457-460`): `target: None`, `value: CompsNarrative`. Track-0-style additive schema bump (per F83b.D3 + §4).
**F83(c)**: writes to existing `landscape: IndustryLandscape | None` field via existing `update_industry_landscape` patch op (per F83c.D4). Comps-aware refresh — distinct from `industry-landscape` (comps-blind single-section refresh) and `competitive-position` (full 4-pillar at initiation, runs before comps). No schema bump for F83(c).

### 2.4 Methodology + SIA-wiki landscape

**Existing methodology units** at `methodology/strategic-evaluation/`:
- `comparative-analysis.md` ✓ (wrapped by `comparative-analysis` skill via `Applied: methodology/strategic-evaluation/comparative-analysis.md` literal in decisions_log)
- `competitive-position.md` ✓ (wrapped by `competitive-position` skill same way)

**SIA-wiki at `methodology/wiki/_index.md`** — 32 concepts, 11 frameworks, 7 patterns, 10 cases. Concept articles directly load-bearing for F83:
- `concepts/industry-structure.md` — concentration, profit share, entry barriers (F83(c) anchor)
- `concepts/competitive-advantage.md` — scale loop / proprietary asset / switching costs / network effects / process-execution (F83(c) anchor)
- `concepts/comparative-analysis.md` — peer benchmarking toolkit (F83(b) + F83(c) anchor)
- `concepts/addressable-market.md` — TAM, penetration, secular drivers (F83(c) anchor)
- `concepts/business-model-identification.md` — what business does + how it charges (F83(b) anchor)

Frameworks load-bearing for F83(c):
- `frameworks/strategic-evaluation-framework.md` — 8-question Module 3 framework
- `frameworks/quality-assessment-framework.md` — 5-pillar quality

Cases for F83(c) industry-specific synthesis:
- `cases/paylocity.md` — HR-Payroll exemplar (extra leverage given Track B v1 ships HR-Payroll)
- `cases/msci.md` — quality compounder exemplar
- `cases/gartner.md` — dual-case (timing win + priced-to-perfection lesson)

**Methodology gaps for F83**:
- **F83(a)** has no dedicated methodology unit. Two options: write a new lightweight `methodology/strategic-evaluation/peer-curation.md` (deliberate small unit), OR `Applied:`-cite `comparative-analysis.md` Step 4 (peer set construction) since that IS the canonical peer-set methodology. **R1 decision** (§9 Q1).
- **F83(b)** has no methodology unit on cross-comp commentary patterns. **Plan creates new methodology unit** `methodology/strategic-evaluation/comps-narrative-composition.md` (TB.D2 below).
- **F83(c)** uses `Applied:`-citation of existing `competitive-position.md` (4-pillar framework) as analytical lens; SIA-wiki articles cited via inline `memory_read` references. No new methodology unit needed.

### 2.5 Patch op surface

**Track 0 already shipped**:
- `set_editorial_peer_set` (full list replacement) — F83(a) primary
- `add_editorial_peer` (single peer augment) — F83(a) for "add this one" mode
- `replace_industry_peer_comparison` (Track A; F83 doesn't write — comparative-analysis is the canonical writer)
- `update_industry_landscape`, `update_macro_overlay`, `update_structural_trends` (existing single-section narrative ops)

**Patch ops F83 needs**: F83(b) gets a new `update_comps_narrative` patch op (additive Track-0-style; per F83b.D3). F83(c) reuses existing `update_industry_landscape` (per F83c.D4). F83(a) reuses existing `set_editorial_peer_set` + `add_editorial_peer`.

### 2.6 Skill-wiring playbook (template constraint)

Per `_playbook.md` Path A "New Atomic Skill Wrapper":
1. Pre-flight: confirm methodology unit exists (or plan creates it)
2. Skill body: frontmatter (name, scope, agent_callable, max_turns, max_budget_usd, persist_state) + Workflow phases with gates + Iron Law + Verdict YAML + Typed Outputs + Patch Ops + Decision Log Entry + chunked memory_write persist
3. QA report at `docs/qa/skill-qa-{skill-name}.md`

Exemplars: `business-quality-assessment.md` (~260 lines), `financial-red-flags.md`. F83 skills follow this template structurally.

---

## 3. Locked design decisions

### F83a.D1. Scope: user-in-the-loop confirmation peer-curation
F83(a) workflow is **propose → display → confirm → apply**. Three modes:
- **Replace mode**: full peer set replacement → `set_editorial_peer_set` patch op
- **Augment mode**: add a single peer to existing set → `add_editorial_peer` patch op
- **Inspect mode** (read-only escape): show current set + proposed delta, no write

NEVER auto-applies a patch op. Confirmation step is mandatory and must be a literal user response, not a skill-internal heuristic.

### F83a.D2. When-to-use vs adjacent skills (explicit boundary table in skill body)
- Use F83(a) when: user wants peer set lock-in WITHOUT running 4-pillar strategic eval; user has a candidate peer in mind and wants to verify/add; periodic peer roster refresh after IPOs/M&A.
- Use `competitive-position` instead when: full 4-pillar strategic re-assessment IS the goal; first-time position initiation; market regime shift audit.
- Use `comparative-analysis` instead when: comp matrix work IS the goal; F83(a)'s peer set already locked in.
- Use `peer-comparison-analysis` instead when: ad-hoc no-Thesis ranking question.

### F83a.D3. Methodology grounding — `Applied:`-cite existing `comparative-analysis.md` Step 4
Decision (locked R1, per Codex R0 non-blocking note): F83(a) does NOT introduce a new methodology unit. Skill `Applied:`-cites `methodology/strategic-evaluation/comparative-analysis.md` Step 4 (peer set construction) — that IS the canonical peer-set methodology already vetted by Codex through `comparative-analysis` skill review. Less moving parts; reuses validated framework.

### F83a.D4. Patch-op contract — never silent overwrite
- `set_editorial_peer_set` REPLACES the full list. F83(a) shows the OUTGOING list explicitly to user before applying.
- `add_editorial_peer` adds one peer. F83(a) shows the ONE peer being added before applying.
- Each `EditorialPeer` write includes `added_by="peer-curation"`, `added_at=<ISO timestamp>`, `rationale=<one line>`, `source="editorial"`.

### F83a.D5. Frontmatter targets
- `agent_callable: true`, `scope: ticker`, `persist_state: true`
- `max_turns: 8`, `max_budget_usd: 2.0` (lighter than `competitive-position` 20-turn / `comparative-analysis` 20-turn / $4.0)
- Iron Law: NO PEER WRITE WITHOUT EXPLICIT USER CONFIRMATION

### F83b.D1. Inputs (read-only at skill entry)
- `Thesis.industry_analysis.peer_comparison.sections` (Track A producer output)
- `Thesis.industry_analysis.operating_comparison.metric_groups` (Track B producer output)
- `Thesis.industry_analysis.editorial_peer_set` (peer roster context)
- `Thesis.business_overview` (focal company context)
- `Thesis.materiality` + `Thesis.assumptions[]` (assumption-tied narrative framing)

### F83b.D2. New methodology unit at `methodology/strategic-evaluation/comps-narrative-composition.md` (full playbook spec)
Per `methodology/_playbook.md` lines 118-173, methodology units must include Core Framework (~1000-1500 words) + Execute Mode (~800-1000 words) + Guide Mode (~600-900 words) + Typed Outputs section + Cite the Methodology section, totaling 2000-4500 words.

**Core Framework topics**: cross-comp commentary patterns — which observations rise to verdict-level (vs incidental); how to weight financial peers (FMP statements) vs operational peers (KPI registry); when median is misleading vs informative (e.g., bimodal peer distributions); anchoring commentary to existing `Thesis.materiality.threshold_pct` + `Thesis.assumptions[*]`; signal vs noise in operating_comparison time-series cells; cell-level citation handling.

**Execute Mode**: tool sequence reads `peer_comparison.sections` + `operating_comparison.metric_groups` + `editorial_peer_set` + Thesis context; verdict format (CROSS_COMP_NARRATIVE_BUILT / NARRATIVE_INSUFFICIENT_SIGNAL / INSUFFICIENT_DATA); typed output mapping (per F83b.D3 below).

**Guide Mode**: Socratic sequence on cross-comp reading — Q1 framing the cross-section question, Q2 identifying load-bearing patterns, Q3 connecting to assumptions, Q4 quality checks. Tier-1 SIA case calibration via `cases/paylocity.md`.

Authored as Phase 1 of the rollout sequence (§8) before any F83 skill ships.

### F83b.D3. Output channel — typed object field + new patch op (Track-0-style additive bump, mirrors `IndustryLandscape` shape)
Per Codex R0 + R1 review, F83(b) output must be a structured typed object with cell-level citations (matching the rest of the industry_analysis section writers), not a bare string.

**Reference shape** — `IndustryLandscape` at `thesis_shared_slice.py:404-406`:
```python
class IndustryLandscape(_ContractModel):
    narrative: str
    citations: list[SourceId] = Field(default_factory=list)
```
Existing patch op `UpdateIndustryLandscapeOp` at `handoff_patch.py:457-460`:
```python
class UpdateIndustryLandscapeOp(_PatchOpBase):
    op: Literal["update_industry_landscape"] = "update_industry_landscape"
    target: None = None
    value: IndustryLandscape
```

**Schema bump (additive)** — `thesis_shared_slice.py`:
```python
class CompsNarrative(_ContractModel):
    narrative: str
    citations: list[SourceId] = Field(default_factory=list)
```
Extend `IndustryAnalysis` (line 504-510) with:
```python
comps_narrative: CompsNarrative | None = None  # F83(b) — cross-section comps commentary
```

**New patch op** — `handoff_patch.py`:
```python
class UpdateCompsNarrativeOp(_PatchOpBase):
    op: Literal["update_comps_narrative"] = "update_comps_narrative"
    target: None = None
    value: CompsNarrative
```

**F83(b) writes** via `update_comps_narrative` only (full-object replace; `narrative` is markdown text + `citations` is registered SourceId list — preserves cell-level provenance from the comps artifacts F83(b) reads).

In addition, F83(b) does standard chunked `memory_write` to `skills/comps-narrative/{YYYY-MM-DD}-{TICKER}.md` (the per-skill memory file is the audit trail; the typed field is the consumer surface — pattern matches `SKILL_CONTRACT_MAP.md:261-268`).

**Patch-engine + serialization integration scope** (per Codex R1 P1.D — full file list at §4): the new field + op require coordinated changes across `thesis_shared_slice.py` (schema), `handoff_patch.py` (op class), `api/research/patch_engine.py:527` (op application + descriptor), `schema/__init__.py` (exports), `schema/thesis_markdown.py:798,1453` (markdown serialize/parse round-trip), and round-trip tests.

### F83b.D4. Boundaries vs `comparative-analysis` per-peer relative_position
F83(b) is cross-section commentary; relative_position is per-peer single-column narrative. F83(b) reads relative_position as input but doesn't write to it.

### F83c.D1. Scope: comps-aware `landscape` refresh (NOT a parallel synthesizer to `competitive-position`)
Per Codex R0 review, F83(c)'s original framing as "industry-analysis synthesis" overlapped with `competitive-position`'s 4-pillar synthesis (per `SKILL_CONTRACT_MAP.md:133`: "Supersedes the three per-section sub-skills (industry-landscape, industry-macro-overlay, structural-trends) for full-framework runs"). Reframe:

**F83(c) is a NARROW post-comps refresh of `Thesis.industry_analysis.landscape`.** It runs AFTER comps populate (peer_comparison + operating_comparison present) and refreshes `landscape` with comps-informed framing. The genuine gap it fills: `competitive-position` runs BEFORE comps, so its `landscape` output doesn't reflect the new comp matrix data; nothing else updates `landscape` based on comps.

**Sharp boundaries**:
- vs `competitive-position`: CP is the canonical 4-pillar full-framework synthesizer; runs at position initiation or strategic re-assessment; produces all 4 industry_analysis channels. F83(c) is a single-channel post-comps refresh; assumes CP has already run.
- vs `industry-landscape`: the existing single-section refresh skill is **comps-blind** — it reads filings + transcripts only. F83(c) is comps-aware: it reads peer_comparison.sections + operating_comparison + the existing landscape + SIA-wiki for analytical framing.
- vs `comparative-analysis`: CA writes `peer_comparison`, not `landscape`; F83(c) consumes CA's output and reflects it in `landscape`.

F83(c) does NOT invoke other skills (synthesizer, not orchestrator).

### F83c.D2. SIA-wiki article selection (mandatory + per-industry)
**Mandatory wiki reads**: `concepts/industry-structure.md`, `concepts/competitive-advantage.md`, `concepts/comparative-analysis.md`.
**Conditional wiki reads** (when matching ticker industry): per-industry case files (e.g., `cases/paylocity.md` for HR-Payroll tickers; `cases/msci.md` for quality-compounder tickers).
**Optional wiki reads** (skill-driven escalation): `concepts/addressable-market.md`, `frameworks/strategic-evaluation-framework.md`, `frameworks/quality-assessment-framework.md`.

### F83c.D3. Methodology citation: 4-pillar framework
`Applied: methodology/strategic-evaluation/competitive-position.md` literal in decisions_log — F83(c) uses the 4-pillar lens (addressable market / industry structure / competitive forces / competitive advantage) as the analytical framing for the post-comps refresh. No new methodology unit needed.

### F83c.D4. Output channel — existing `landscape` field via existing `update_industry_landscape` patch op
**No schema bump for F83(c).** F83(c) writes to the EXISTING `IndustryAnalysis.landscape` field via the EXISTING `update_industry_landscape` patch op (Track-0-style; per `competitive-position.md` line 213+ and `industry-landscape.md`). This mirrors how `industry-landscape` itself writes single-section refreshes today.

The narrative content is comps-aware (cites peer_comparison.sections + operating_comparison cells via `Thesis.sources[]` registered IDs), but the OUTPUT TARGET is the same `landscape: IndustryLandscape` typed field.

In addition, F83(c) does standard chunked `memory_write` to `skills/post-comps-landscape-refresh/{YYYY-MM-DD}-{TICKER}.md` for the audit trail (matches the convention).

### F83c.D5. Frontmatter targets
- `agent_callable: true`, `scope: ticker`, `persist_state: true`
- `max_turns: 12`, `max_budget_usd: 2.5` (lighter than original R0 estimate — narrower scope after Codex P1.2 reframe)
- **Iron Law: NO LANDSCAPE REFRESH WITHOUT BOTH COMPS ARTIFACTS PRESENT AND PRIOR `landscape` PRESENT.** Three preconditions, all required:
  1. `Thesis.industry_analysis.peer_comparison` populated (Track A producer must have run)
  2. `Thesis.industry_analysis.operating_comparison` populated (Track B producer must have run)
  3. `Thesis.industry_analysis.landscape` already exists (CP or `industry-landscape` must have written one)
- Skip-and-flag with **explicit recovery routing** if any precondition missing:
  - **If comps missing** AND user wants comps-aware refresh → run the canonical comps producer (`industry_peer_comparison()` with `INDUSTRY_ANALYSIS_V1_2_ENABLED=true`) FIRST to populate `peer_comparison` + `operating_comparison`; OR use the §5 fixture-injection path if running outside production. Do NOT fall back to `industry-landscape` here — `industry-landscape` is comps-blind and would silently degrade to a non-comps-aware landscape (per `industry-landscape.md:20,56`: explicitly does not touch peer_comparison; deterministic peer metric work belongs to industry peer comparison tool). Only fall back to `industry-landscape` if the user explicitly accepts a comps-blind baseline.
  - **If `landscape` missing** AND comps already populated → run `competitive-position` (full 4-pillar at initiation) OR `industry-landscape` (single-section refresh) FIRST to establish baseline narrative, then F83(c) refreshes it with comps awareness.
  - **F83(c) does NOT create-from-empty in v1** — refresh-only semantics keep the boundary with the canonical landscape writers sharp. Iron Law: skill exits with `INSUFFICIENT_DATA` verdict + explicit `recommended_next_action` naming the right upstream skill/tool to run first.

---

## 4. File-by-file changes

### AI-excel-addin (skills + methodology + schema)

**Modified — schema + patch-engine + serialization (per F83b.D3 + Codex R1 P1.D + R2 confirmation, additive Track-0-style bump)**:
- `schema/thesis_shared_slice.py`:
  - Add new `CompsNarrative` class (mirrors `IndustryLandscape:404-406` shape with `narrative: str` + `citations: list[SourceId] = Field(default_factory=list)`)
  - Extend `IndustryAnalysis` (line 504-510) with `comps_narrative: CompsNarrative | None = None` (additive only; existing 6 fields untouched, backward-compatible)
  - Update `__all__` export to include `CompsNarrative`
- `schema/handoff_patch.py` (around line 457 where `UpdateIndustryLandscapeOp` lives):
  - Add `UpdateCompsNarrativeOp` class (mirrors `UpdateIndustryLandscapeOp` exactly: `target: None`, `value: CompsNarrative`)
  - Add `CompsNarrative` to imports from `thesis_shared_slice`
  - Add `UpdateCompsNarrativeOp` to the `HandoffPatchOp` union
  - Update `__all__` export to include `UpdateCompsNarrativeOp`
- `schema/__init__.py` — re-export `CompsNarrative` + `UpdateCompsNarrativeOp` from the schema package public surface (matches existing `IndustryLandscape` / `UpdateIndustryLandscapeOp` re-export pattern).
- `api/research/patch_engine.py`:
  - Around line 527 — add patch-application branch for `update_comps_narrative` op (mirrors how `update_industry_landscape` is applied; target attribute path is `Thesis.industry_analysis.comps_narrative` with replace-not-merge semantics)
  - Around line 996 — add `_describe_op` branch for `update_comps_narrative` so dry-run and audit logs render the op correctly (matches existing op-description pattern)
- `schema/thesis_markdown.py`:
  - Around line 798 — extend the markdown serialize path to render the new `comps_narrative` section (matches how `landscape` is serialized today; new section header + narrative body + citations footer)
  - Around line 1453 — extend the markdown parse path to read the section back into a `CompsNarrative` object on round-trip
- Round-trip tests:
  - Schema validation: `CompsNarrative` constructs cleanly with empty citations + with multiple citations; rejects malformed citations
  - Patch-engine apply: `update_comps_narrative` op applies cleanly; replace-semantics confirmed
  - Markdown serialize → parse → schema equivalence (per existing `IndustryLandscape` round-trip test pattern; should mirror that test 1:1)
  - `__all__` exports test (matches existing schema-package export coverage test if one exists; otherwise add)
- **Schema snapshot files** (per Codex R3 P2.A — adding `comps_narrative` to shared `IndustryAnalysis` will change pinned snapshots checked at `tests/integration/test_shared_slice_isomorphism.py:198`):
  - `tests/schema/snapshots/thesis_v1_0.schema.json` — regenerate with new field
  - `tests/schema/snapshots/handoff_v1_1.schema.json` — regenerate with new patch op
  - Both snapshot updates land in the same Phase 3 commit as the schema bump (otherwise CI fails).

**New**: `api/memory/workspace/notes/skills/peer-curation.md` (~250-300 lines, F83(a))
- Frontmatter per F83a.D5 (max_turns: 8, max_budget_usd: 2.0)
- Workflow: propose phase (FMP discovery + sub-industry classifier + user-description filter) → display phase (show proposed set with per-peer rationale + diff vs current set) → confirm phase (mandatory user confirmation) → apply phase (`set_editorial_peer_set` OR `add_editorial_peer`)
- Iron Law: NO PEER WRITE WITHOUT EXPLICIT USER CONFIRMATION
- Decision Log Entry with `Applied: methodology/strategic-evaluation/comparative-analysis.md` citation (per F83a.D3 — re-uses existing methodology unit; no new unit)

**New**: `api/memory/workspace/notes/skills/comps-narrative.md` (~250-300 lines, F83(b))
- Frontmatter: `agent_callable: true`, `scope: ticker`, `persist_state: true`, `max_turns: 12`, `max_budget_usd: 2.5`
- Workflow: read inputs (per F83b.D1) → identify cross-section patterns → frame anchored narrative (vs assumptions/materiality) → emit `update_comps_narrative` patch op + chunked memory_write
- Iron Law: NO NARRATIVE WITHOUT BOTH COMPS ARTIFACTS PRESENT
- `Applied: methodology/strategic-evaluation/comps-narrative-composition.md` citation

**New**: `api/memory/workspace/notes/skills/post-comps-landscape-refresh.md` (~250-300 lines, F83(c))
- Frontmatter per F83c.D5 (max_turns: 12, max_budget_usd: 2.5)
- Workflow: **confirm three preconditions present** (peer_comparison, operating_comparison, AND existing landscape) → read `peer_comparison.sections` + `operating_comparison` + existing `landscape.narrative` + SIA-wiki articles + methodology framing → produce comps-aware landscape narrative → emit `update_industry_landscape` patch op (existing) + chunked memory_write
- Iron Law per F83c.D5: NO LANDSCAPE REFRESH WITHOUT ALL THREE PRECONDITIONS — peer_comparison present, operating_comparison present, AND existing `landscape` present (refresh-only, NOT create-from-empty in v1). Skip-and-flag with `INSUFFICIENT_DATA` verdict + explicit `recommended_next_action` naming the right upstream skill/tool when any precondition is missing (per F83c.D5 routing).
- `Applied: methodology/strategic-evaluation/competitive-position.md` citation

**New**: `api/memory/workspace/notes/methodology/strategic-evaluation/comps-narrative-composition.md` (F83b.D2)
- Full playbook spec per `methodology/_playbook.md:118-173`: Core Framework (~1000-1500 words) + Execute Mode (~800-1000 words) + Guide Mode (~600-900 words) + Typed Outputs section + Cite the Methodology section
- Total: 2000-4500 words per playbook hard target

**New**: `docs/qa/skill-qa-peer-curation.md`, `docs/qa/skill-qa-comps-narrative.md`, `docs/qa/skill-qa-post-comps-landscape-refresh.md` — QA reports per playbook.

**Modified**: `docs/SKILL_CONTRACT_MAP.md` — add 3 new skill rows + reflect schema additive bump.

### risk_module (no production code changes expected)
- F83 skills are runtime artifacts loaded by the agent gateway; they don't ship from risk_module's Python.
- Schema bump for `comps_narrative` lives in AI-excel-addin (per established pattern).
- Producer-side: V2.P11's existing source registration + cell-citation paths cover what F83(b)/F83(c) need to read; no risk_module changes.

### Out of scope for this plan
- F81 renderer integration (separate plan; renderer needs a new branch for the new `comps_narrative` field once F83 ships)
- F82 persistence-to-Thesis (separate plan; F83(b)/F83(c) live smokes use fixture-injection per §5)
- F84 process-template migration (separate plan)
- Drop F83(c) (was considered at R1 — kept after reframing as comps-aware `landscape` refresh)

---

## 5. Tests

| Coverage area | Where |
|---|---|
| QA reports per playbook | `docs/qa/skill-qa-{peer-curation,comps-narrative,post-comps-landscape-refresh}.md` |
| Live smoke against existing PCTY Thesis (F83(a)) | replace + augment + inspect modes; verifies confirmation flow + patch op application |
| **Live smoke for F83(b)/F83(c) — fixture-injection with source-ID collision avoidance** (per Codex R0 P1.4 + R1 P2 + R2 P1) | F82 (persistence-to-Thesis) is still a rollout gate — V2.P11 producers populate `peer_comparison.sections` + `operating_comparison` in their flag-on output, BUT the source IDs in those artifacts are bundle-scoped, not Thesis-stable, until F82 lands (per `docs/TODO.md:91`). The schema requires `SourceRecord.id` to follow the `src_N` pattern (per `thesis_shared_slice.py:30`). Bundle-minted IDs collide with existing Thesis.sources[] entries if both share the same N. Smoke must use ONE of these three feasible paths: (a) **blank-Thesis fixture** — fresh Thesis with `sources=[]`, run producer → inject artifacts (their bundle IDs occupy src_1..src_N exclusively); (b) **producer-aware fixture** — call producer with `existing_sources=thesis.sources` (per `mcp_tools/industry.py:35,143`) so producer mints non-colliding IDs **NOTE: only feasible via direct Python/test-harness call — the MCP wrapper at `mcp_server.py:2411` does NOT expose `existing_sources` parameter; using path (b) via MCP would require adding wrapper support, which is out of scope here per "no risk_module changes expected"**; (c) **QA remap helper** — rewrite captured artifacts' cell `source_refs` to point at remapped Thesis.sources[] entries before injection. Recommended default: (a) for first smoke (cleanest, fully MCP-callable); (b) for "test against existing Thesis state" smoke variants when running Python harness directly; (c) when neither (a) nor (b) is acceptable.

**F83(c)-specific fixture requirement** (per Codex R4 non-blocking note): the blank-Thesis fixture path (a) solves source-ID collision but does NOT satisfy F83(c)'s "prior `landscape` present" precondition (per F83c.D5). For F83(c) **positive** smoke (verifying the refresh produces comps-aware narrative), the fixture must additionally inject an existing `Thesis.industry_analysis.landscape` value (e.g., a CP-shaped landscape captured from a prior run, or a hand-crafted minimal landscape with `narrative` + `citations`). For F83(c) **negative** smoke (verifying skip-and-flag), use a fixture WITHOUT prior landscape and assert `INSUFFICIENT_DATA` verdict + `recommended_next_action` routing per §5 boundary tests. **No production migration helper required** — fixture is QA-only bridge, NOT reusable production plumbing (production path waits for F82). Test asserts: `update_comps_narrative.value.citations` are all valid `Thesis.sources[].id` references; `update_industry_landscape.value.citations` same. |
| Skill registry/loader registration | Verify three skills are discoverable + invokable via the agent gateway after sync (`scripts/sync_agent_gateway.sh`) |
| Boundary tests | F83(a): skip-with-error when no Thesis. F83(b): skip-and-flag when `peer_comparison` OR `operating_comparison` missing. F83(c) — three-precondition tests: skip-and-flag when (i) `peer_comparison` missing, (ii) `operating_comparison` missing, OR (iii) prior `landscape` missing. Each skip-case must produce `INSUFFICIENT_DATA` verdict + `recommended_next_action` naming the right upstream skill/tool (per F83c.D5 routing). Critical: F83(c) MUST NOT silently apply `update_industry_landscape` when `landscape` is absent — `patch_engine.py:631`'s generic patch path will accept the write blindly, so the skill itself is the precondition gate. |
| Patch-op safety | F83(a) mock confirmation flow: confirm-yes applies; confirm-no skips; no-confirmation-default skips with explicit log line. F83(b) `update_comps_narrative` round-trip: write → read → verify Thesis state. F83(c) `update_industry_landscape` round-trip: write → read → verify `landscape.narrative` reflects comps content. |

No automated unit tests for the skill .md files themselves (they're data, not code) — QA reports + live smokes are the gates.

---

## 6. Cross-cutting concerns

### 6.1 Citations
- F83(a): cite registered `Thesis.sources[]` only (per existing skill convention). For peer rationales sourced from FMP / sub-industry classifier output, leave `source_refs` empty if the FMP pull isn't a registered source — don't fabricate.
- F83(b): cite `Thesis.sources[]` registered by Track A/B producers (which already populate sources). The narrative cells reference cell-level `source_refs` from the artifact; the narrative itself cites `decisions_log` rationales of upstream skills.
- F83(c): cite both `Thesis.sources[]` AND SIA-wiki articles via `memory_read` literal paths in the synthesis text (e.g., "per `methodology/wiki/concepts/industry-structure.md`...").

### 6.2 Methodology citation literal
Every F83 skill MUST include `Applied: methodology/strategic-evaluation/<unit>.md` verbatim in `decisions_log.rationale` for provenance. Without this literal, the typed output is unprovenanced (existing convention from `comparative-analysis.md:476`).

### 6.3 Patch-op safety
- F83(a): two-mode (replace + augment), never silent overwrite. Iron Law: NO PEER WRITE WITHOUT EXPLICIT USER CONFIRMATION.
- F83(b): writes typed `comps_narrative` via `update_comps_narrative` patch op. Last-writer-wins on the field (matching all other industry_analysis section writers).
- F83(c): writes typed `landscape` via existing `update_industry_landscape` patch op. **Shares target with `industry-landscape` and `competitive-position`'s landscape channel** — last-writer-wins; F83(c)'s comps-aware narrative supersedes earlier comps-blind versions when re-run; `industry-landscape` re-run after F83(c) reverts to comps-blind state. This is operationally fine because the trigger conditions are different (comps populated vs not) but caller must know which they want.

### 6.4 Boundaries
Each skill's `When NOT to Use` section explicitly points at adjacent skills (per F83a.D2 table; mirrored for F83(b)/F83(c)).

### 6.5 Performance + caching
F83(a): one FMP pull (`get_subindustry_peers_from_ticker` or equivalent) + one user round-trip. Sub-second after FMP fetch.
F83(b): no external API calls — reads existing Thesis state. Fast (<5s).
F83(c): same — reads Thesis + memory. Multi-pass `memory_read` calls add modest latency. Budget allows up to 16 turns.

### 6.6 Logging
Per existing skill convention — `portfolio_logger.warning` only on fallback events (no Thesis, missing artifact, FMP discovery failure). No per-call structured log.

---

## 7. Out of scope

- **F81 renderer** — separate plan; gates flag-on display
- **F82 persistence-to-Thesis** — separate plan; F83(b)/F83(c) write typed Thesis fields, but the producer-to-Thesis pipeline that auto-populates `peer_comparison` + `operating_comparison` requires F82. Live smokes for F83(b)/F83(c) use fixture-injection until F82 lands (per §5).
- **F84 process-template migration** — separate plan; gates which templates invoke F83 skills
- **F85 v1.1 reference industries** — F83 skills are industry-agnostic; they work whenever Track B has a registry yaml for the ticker's industry_key
- **F86 v2 enhancements** — quarterly KPIs, LLM-based peer scoring (F83(a) v1 uses regex/sub-industry classifier; LLM peer scoring is v2)
- **Skill-invokes-skill orchestration** — F83(c) is a synthesizer not an orchestrator; running multiple skills in sequence is up to higher-level agent flow
- **Renderer-side narrative rendering** — F83(b)/F83(c) produce text; how it's displayed is F81 territory
- **Auto-trigger** — F83 skills are explicit-invoke; no auto-fire on producer artifact change in v1

---

## 8. Rollout sequence

1. **Phase 1**: write methodology unit `comps-narrative-composition.md` (F83b.D2). New file; no skill yet. Codex review → land.
2. **Phase 2**: ship F83(a) `peer-curation.md` skill + QA report. Lightest skill; only writes existing patch ops (`set_editorial_peer_set` + `add_editorial_peer`); reuses existing methodology unit (`comparative-analysis.md` Step 4) per F83a.D3 — no new methodology unit. Live smoke against PCTY Thesis. Sync to agent gateway.
3. **Phase 3**: **schema bump + F83(b) skill** (per Codex R2 P1.A + R3 split recommendation). One Codex review round, two focused commits inside it for cleaner review boundary:
   - **3a — Schema bump commit**: all 6 schema files (per F83b.D3 + §4 file list) — new `CompsNarrative` class, `IndustryAnalysis.comps_narrative` field, `UpdateCompsNarrativeOp`, `__all__` exports, patch-engine application + describe branches, markdown round-trip, schema snapshot regeneration (`thesis_v1_0.schema.json` + `handoff_v1_1.schema.json`). Round-trip tests pass.
   - **3b — F83(b) skill commit**: ship `comps-narrative.md` skill + QA report — writes `update_comps_narrative` patch op against the new typed field. Live smoke for F83(b) uses §5 fixture-injection path (F83(a) Phase 2 smoke does NOT verify comps artifacts — F83(a) only writes editorial_peer_set; the comps artifacts come from running the V2.P11 producer, captured fresh per fixture protocol).

   Sync to agent gateway after 3b lands.
4. **Phase 4**: ship F83(c) `post-comps-landscape-refresh.md` skill + QA report. Comps-aware refresh of existing `landscape` field; reads peer_comparison + operating_comparison + existing landscape + SIA-wiki + 4-pillar methodology; rewrites narrative via existing `update_industry_landscape` patch op. No schema bump (reuses existing field + patch op). Live smoke for F83(c) uses §5 fixture-injection path. Sync.

Each phase = one focused commit per repo + one QA report commit. AI-excel-addin sync via `scripts/sync_agent_gateway.sh` after each phase per existing pattern. No risk_module commits.

Phases 1-4 land **flag-off-equivalent** — skills are present in skill registry but only fire when explicitly invoked. No auto-trigger. The actual user-visible cutover is gated by F81 renderer (for narrative display) + F84 process-template migration (for template-driven invocation).

---

## 9. Open questions

R0 had 6 open questions; R1 closes 4 of them. Remaining:

1. **F83(a) sub-industry classifier source** [open]: framework §6 names "FMP discovery + sub-industry classifier + user description" — what's the sub-industry classifier? Existing `industry_resolver.resolve_industry_key()` returns coarse industry_key (`hr_payroll` / `grocers` / `unknown` / `semiconductors`). Is that the classifier, or is something more granular needed? **Verify at impl start of F83(a) phase.**

**Closed at R1**:
- ~~F83a.D3 methodology unit~~ — locked: `Applied:`-cite existing `comparative-analysis.md` Step 4 (no new unit)
- ~~F83b.D3 output channel~~ — locked: typed field `IndustryAnalysis.comps_narrative` + new patch op `update_comps_narrative`
- ~~F83c.D4 output channel~~ — locked: existing `landscape` field via existing `update_industry_landscape` patch op (F83(c) reframed as comps-aware landscape refresh)
- ~~F83(c) vs `industry-landscape` boundary~~ — locked: F83(c) is comps-aware; `industry-landscape` is comps-blind single-section refresh. Both write to `landscape`; different inputs, different triggers.
- ~~Process-template gating~~ — confirmed by Codex non-blocking: invokable now via direct skill catalog; F84 is the template migration gate.

---

## 10. Summary

**3 new agent-callable skills** in AI-excel-addin (`api/memory/workspace/notes/skills/`):
- F83(a) `peer-curation` — user-in-the-loop confirmation peer-set writer; writes `set_editorial_peer_set` / `add_editorial_peer` patch ops only after explicit user confirmation. Reuses existing methodology unit (`comparative-analysis.md`).
- F83(b) `comps-narrative` — cross-section commentary on Track A + Track B artifacts; writes new `IndustryAnalysis.comps_narrative: CompsNarrative | None` typed object field via new `update_comps_narrative` patch op (Track-0-style, mirrors `IndustryLandscape` shape with `narrative: str` + `citations: list[SourceId]`)
- F83(c) `post-comps-landscape-refresh` (renamed at R2 from `industry-analysis-synthesis`) — comps-aware refresh of existing `IndustryAnalysis.landscape` field via existing `update_industry_landscape` patch op; runs after comps populate to integrate comp signals into the existing landscape narrative; last-writer-wins on shared field

**1 new methodology unit** at `methodology/strategic-evaluation/comps-narrative-composition.md` (full playbook spec, 2000-4500 words target — Codex R1 confirms achievable near 2000-2500 word lower bound; F83(b) only).

**1 additive schema bump in AI-excel-addin** spanning 6 files (per Codex R1 P1.D): new `CompsNarrative` typed object + `IndustryAnalysis.comps_narrative` field + `UpdateCompsNarrativeOp` + patch-engine descriptor + schema/__init__.py exports + thesis_markdown.py round-trip + tests.

**3 QA reports** at `docs/qa/skill-qa-{...}.md`.

**0 risk_module code changes** (skills + methodology + schema all in AI-excel-addin).

After F83 ships (flag-off-equivalent — skills present but only explicitly invoked; producer flag also off until F81 lands):
- V2.P11 has its consumption layer
- F81 (renderer) needs a new branch for `comps_narrative` field rendering before flag-on display
- F82 (persistence-to-Thesis) becomes operational requirement once full producer-to-Thesis-to-skill pipeline is wired — until then F83(b)/F83(c) live smokes use fixture-injection (per §5)
- F84 (process-template migration) becomes the remaining gate for template-driven invocation

Lands as 4 phases (1 methodology unit + 1 schema bump + 3 skills), one focused commit per phase, sync to agent gateway after each skill.

---

## 11. Changelog

### R0 → R1 (2026-05-08)

Addresses Codex R0 review FAIL (4 P1 blockers + 2 non-blocking confirmations). All findings cite shipped code; fixes verified against `SKILL_CONTRACT_MAP.md:125-153` industry-skill writing patterns + `methodology/_playbook.md:118-173` methodology-unit shape.

**P1.1 — F83(b)/F83(c) memory-only contradicted skill ecosystem (F83b.D3, F83c.D4, §4)**: R0 defaulted both to `memory_write` + `decisions_log` only. Per `SKILL_CONTRACT_MAP.md:261-268` industry skills produce typed Thesis fields plus free-form notes (notes are audit trail, not consumer surface). Adjacent industry skills (`industry-landscape`, `industry-macro-overlay`, `structural-trends`, `competitive-position`) all write typed fields via patch ops. R1: F83(b) gets new typed field `IndustryAnalysis.comps_narrative: str | None` + new `update_comps_narrative` patch op (Track-0-style additive bump). F83(c) reuses existing `landscape` field via existing `update_industry_landscape` patch op (after the F83(c) reframe per P1.2).

**P1.2 — F83(c) boundary depended on a non-existent field (F83c.D1, F83c.D4)**: R0 said F83(c) ran alongside `industry-landscape` because they used different fields, but with memory-only output there was no distinct field. Per `SKILL_CONTRACT_MAP.md:133` `competitive-position` already supersedes the per-section sub-skills for full-framework runs and emits 4-pillar synthesis to `landscape`. R1 reframe: F83(c) is now a NARROW post-comps refresh of `landscape` (writes via existing `update_industry_landscape` patch op). Genuine gap filled: `competitive-position` runs BEFORE comps populate, so its `landscape` is comps-blind; F83(c) is comps-aware. Sharp boundaries vs CP (full 4-pillar at initiation), `industry-landscape` (comps-blind single-section), `comparative-analysis` (writes `peer_comparison`, not `landscape`).

**P1.3 — methodology unit underspecified (F83b.D2)**: R0 proposed `comps-narrative-composition.md` at ~150-200 lines. Per `methodology/_playbook.md:118-173`, methodology units require Core Framework (~1000-1500 words) + Execute Mode (~800-1000 words) + Guide Mode (~600-900 words) + Typed Outputs section + Cite the Methodology section, totaling 2000-4500 words. R1: F83b.D2 expanded to full playbook spec — Socratic sequence, calibration anchors, voice split, etc.

**P1.4 — F83(b)/F83(c) input availability misstated relative to F82 (§5)**: R0 didn't acknowledge that `peer_comparison.sections` + `operating_comparison` aren't auto-persisted to Thesis without F82 (still a rollout gate per `docs/TODO.md:90`). R1: §5 specifies fixture-injection live smoke path — run V2.P11 producer to populate artifacts, capture, inject into test Thesis fixture, run F83(b)/F83(c) against the fixture. Smoke verified end-to-end without F82 dependency.

**Non-blocking confirmations (Codex R0 final paragraphs)**:
- F83(a) standalone `peer-curation` boundary is sharp enough — materially narrower than `competitive-position`, Thesis-bound unlike `peer-comparison-analysis`. R1 locks F83a.D3 to `Applied:`-cite `comparative-analysis.md` Step 4 (no new methodology unit).
- Process-template gating is safe — direct invocation works through existing skill catalog/`invoke_skill` path; F84 remains the template migration gate. R1 closes §9 Q5 with this confirmation.

### R1 → R2 (2026-05-08)

Addresses Codex R1 review FAIL (4 P1 + 1 P2). All findings cite shipped code; fixes verified against existing schema/patch-op shapes.

**P1.A — Stale R0 text contradicted R1 typed-output lock (§§1, 2.3, 6.3 + others)**: R1 added typed-field locks at F83b.D3 / F83c.D4 but left contradictory R0 paragraphs in earlier sections (line 76 still said F83(b) target OPEN, line 299 said "no Thesis mutation in v1," line 331 said memory-only). R2: full sweep + correction — every F83(b) / F83(c) reference now reflects the typed-field decision; only changelog historical refs preserved.

**P1.B — F83(c) reframe inconsistent (§§1 description, 2.2 NOT-vs)**: R1's narrow post-comps-refresh reframe was clear at F83c.D1 but earlier text still framed F83(c) as a broad "strategic READ" synthesizer reading "all `industry_analysis.*`" — would have steered implementation back toward R0 overlap with `competitive-position`. R2: §1 description and §2.2 boundary explicitly limit F83(c) to comps-aware `landscape` refresh; SKILL FILE RENAMED from `industry-analysis-synthesis.md` to `post-comps-landscape-refresh.md` per Codex suggestion to lock the framing into the artifact name. Last-writer-wins behavior on shared `landscape` is now stated explicitly (§6.3).

**P1.C — F83(b) schema should be structured object, not bare str (F83b.D3, §4)**: R1 declared `comps_narrative: str | None`, but every existing industry_analysis narrative typed output uses a structured object with citations (e.g., `IndustryLandscape.narrative` + `citations: list[SourceId]` at `thesis_shared_slice.py:404-406`; `UpdateIndustryLandscapeOp.value: IndustryLandscape` at `handoff_patch.py:457-460`). Bare string would hide source refs from contract validation, markdown round-trip, and downstream tooling. R2: introduce `CompsNarrative` class with `narrative: str` + `citations: list[SourceId] = Field(default_factory=list)` mirroring `IndustryLandscape` shape exactly; `UpdateCompsNarrativeOp.value: CompsNarrative` mirrors `UpdateIndustryLandscapeOp` exactly.

**P1.D — Schema-bump scope under-specified (§4)**: R1 listed only `thesis_shared_slice.py` + `handoff_patch.py` for the schema bump. Adding a new patch op requires more: `api/research/patch_engine.py:527` (op application + descriptor), `schema/__init__.py` (exports), `schema/thesis_markdown.py:798,1453` (markdown serialize/parse round-trip), plus round-trip tests. R2: §4 file list now spans all 6 files + tests; F83b.D3 also enumerates the integration scope inline.

**P2 — Fixture-injection smoke needs source-ID hygiene (§5)**: R1's fixture-injection path captured artifacts but not their bundle-scoped sources. Per `docs/TODO.md:91`, F82 exists because bundle-scoped source IDs aren't Thesis-stable yet; naive injection would pass artifact-presence checks but fail citation integrity (cell `source_refs` would point to IDs not in `Thesis.sources[]`). R2: fixture injection now (a) injects `sources` into `Thesis.sources[]` FIRST keeping bundle IDs for the fixture's lifetime, (b) injects artifacts whose `source_refs` resolve correctly, (c) explicitly notes fixture is QA-only, NOT reusable production plumbing. Live smoke asserts citation integrity (all `update_comps_narrative.value.citations` and `update_industry_landscape.value.citations` IDs are valid `Thesis.sources[].id` references).

**Non-blocking confirmations from R1 review**:
- Methodology unit scope (P1.3 closure check): full playbook compliance achievable near 2000-2500 word lower bound; no waiver needed.
- Fixture injection clean as QA-only bridge; no production-plumbing concern as long as it's not reused.

### R2 → R3 (2026-05-08)

Addresses Codex R2 review FAIL (3 P1). All findings cite shipped code; fixes verified against existing schema/producer call sites.

**P1.A — Stale memory-only at Phase 3 (§8)**: R2 closed memory-only refs in design sections but Phase 3 still said "F83(b) memory-only" + erroneously claimed F83(a) Phase 2 smoke verified comps artifacts (F83(a) only writes editorial_peer_set; doesn't touch comps). Would have steered impl back to memory-only. R3: Phase 3 reframed as "**schema bump + F83(b) skill**" (single phase landing all 6 schema files with the skill that consumes them); F83(b) live smoke explicitly uses §5 fixture-injection path; F83(a)'s smoke scope corrected (peer-curation only).

**P1 — Fixture source-ID hygiene must avoid collisions (§5)**: R2's "keep bundle IDs in Thesis.sources[]" only works for blank-Thesis fixtures. Per `thesis_shared_slice.py:30`, `SourceRecord.id` follows `src_N` pattern; bundle-minted IDs collide with existing Thesis.sources[] entries if both share the same N. Per `mcp_tools/industry.py:35,143`, `industry_peer_comparison()` accepts `existing_sources` to mint non-colliding IDs. R3: §5 specifies three feasible paths — (a) blank-Thesis fixture (default for first smoke), (b) producer-aware fixture (`existing_sources=thesis.sources`), (c) QA remap helper rewriting cell `source_refs`. No production migration helper needed; fixture remains QA-only bridge.

**P2 — F83(c) preconditions under-specified (F83c.D5)**: R2's Iron Law required both comps artifacts but didn't require existing `landscape`. F83(c) is a "refresh," not "create-from-empty"; without prior landscape, refresh has nothing to refresh. R3: F83(c) Iron Law now lists three required preconditions — peer_comparison present, operating_comparison present, AND existing `landscape`. Skip-and-flag with explicit guidance (route to `industry-landscape` if comps missing; route to `competitive-position` or `industry-landscape` first if landscape missing). F83(c) is refresh-only in v1 — keeps boundary sharp with canonical landscape writers.

**Non-blocking confirmations from R2 review**:
- F83(c) rename to `post-comps-landscape-refresh` is net positive (Codex notes "post" can imply auto-trigger but acceptable if explicit-invoke is clear; R3 keeps the name).
- 6-file schema-bump scope is correct top-level; sub-requirements added inline at §4 (`__all__` exports, `handoff_patch` import + union, `_describe_op` branch around `patch_engine.py:996`). No frontend type defs / DB migration needed for F83.

### R3 → R4 (2026-05-08)

Addresses Codex R3 review FAIL (2 P1 + 2 P2). All findings cite shipped code; fixes verified against `industry-landscape.md`, `mcp_server.py`, and `test_shared_slice_isomorphism.py`.

**P1.A — F83(c) recovery routing pointed at wrong tool (F83c.D5)**: R3's "if comps missing → industry-landscape is the right tool" would let an agent silently degrade to comps-blind landscape. Per `industry-landscape.md:20,56`, that skill explicitly does NOT touch peer_comparison and routes deterministic peer metric work elsewhere. R4: F83c.D5 routing now requires running the canonical comps producer (or §5 fixture-injection path) FIRST when comps are missing; falling back to `industry-landscape` is allowed only when the user explicitly accepts a comps-blind baseline.

**P1.B — F83(c) precondition not propagated to §4 + §5 (§§4 skill description, 5 boundary tests)**: F83c.D5 was updated to 3 preconditions in R3 but §4 Iron Law still said "BOTH COMPS ARTIFACTS PRESENT" (2 preconditions); §5 boundary tests only covered missing peer_comparison/operating_comparison. `update_industry_landscape` will write into `industry_analysis` blindly via `patch_engine.py:631`, so the skill itself is the precondition gate. R4: §4 skill description Iron Law updated to 3 preconditions; §5 boundary tests now explicitly cover missing prior `landscape` case + assert `INSUFFICIENT_DATA` verdict + correct `recommended_next_action`.

**P2.A — Schema snapshot files missing from §4 (§4 schema bump)**: Adding `comps_narrative` to shared `IndustryAnalysis` changes pinned schemas checked at `tests/integration/test_shared_slice_isomorphism.py:198`. Without snapshot updates, CI fails on the schema bump commit. R4: §4 explicitly lists `tests/schema/snapshots/thesis_v1_0.schema.json` + `handoff_v1_1.schema.json` regeneration; both land in the same Phase 3a schema bump commit.

**P2.B — Producer-aware fixture path (b) MCP-wrapper limitation (§5)**: `mcp_tools/industry.py:35,143` accepts `existing_sources`, but the MCP wrapper at `mcp_server.py:2411` does NOT expose it. Path (b) only feasible via direct Python/test-harness call. Adding wrapper support would contradict "no risk_module changes expected." R4: §5 path (b) annotated with the MCP-wrapper limitation; recommended-default order updated — (a) for MCP-callable smoke, (b) for harness-only variants, (c) when neither is acceptable.

**Non-blocking confirmations from R3 review**:
- Phase 3 split into two commits (3a schema, 3b skill) within one Codex review round — adopted per Codex recommendation.
- No other P1/P2 blockers found in core schema/patch-op/fixture model — only routing + propagation cleanup.
