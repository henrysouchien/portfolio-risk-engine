# Thesis Write-Surface Coverage Matrix

**Status:** Living inventory — snapshot 2026-05-20. Companion to the design doc.
**Purpose:** Map every Thesis schema field to the skill(s) that write to it. Inventory of producers, gaps, and skill boundaries.
**Pairs with:** [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md) — the **unified design** (three-layer model, locked decisions D1-D10, design rules R1-R12, success criteria 1-9, verification V1-V12). This doc is inventory; the layers doc is the design authority.
**Active workstreams (close the gaps below):** F131 (strict-audit live green run), F132 (parked — post F129) — see [`../TODO.md`](../TODO.md) "Thesis & Research Artifact" section. F124/F125/F126/F127/F128/F129/F130/F133/F134/F135 completed work is archived in [`../TODO_COMPLETED.md`](../TODO_COMPLETED.md). The autonomous monitoring/exit loop (F129) is canonical-doc'd at [`../architecture/AUTONOMOUS_MONITORING_LOOP.md`](../architecture/AUTONOMOUS_MONITORING_LOOP.md).
**Scope:** Read-only audit. Source: `AI-excel-addin/schema/thesis.py`, `thesis_shared_slice.py`, `handoff.py`, `handoff_patch.py`; skill prose under `AI-excel-addin/api/memory/workspace/notes/skills/`.

## Context

The Thesis is the typed contract at the center of the autonomous investment loop: **research → thesis → model → position → monitoring → reassessment → exit**. Every stage downstream of research reads Thesis. This matrix surfaces *which fields have producers, which are latent, and which skills are advisor-only by design vs. by oversight* — feeding the design doc and the TODO workstreams.

The HandoffArtifact (versioned snapshot of Thesis) is what flows to the model build via `BuildModelOrchestrator`. Thesis is live state; HandoffArtifact is the immutable snapshot. All writes target Thesis directly. (Per [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md) — Layer 2 = typed conclusions on Thesis; Layer 3 = HandoffArtifact.)

---

## Matrix

Column legend: writer skill • patch op type / write mechanism.

### Stage A — Identity / metadata

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `thesis_id`, `user_id`, `ticker`, `label`, `version`, `created_at`, `updated_at`, `markdown_path` | `thesis-consultation` | `portfolio-mcp.thesis_create(research_file_id, initial_fields)` creates the row |
| `from_idea` | Auto-populated via `start_research` idea ingest | Server-side; only skill-driven when starting research from an idea |
| `schema_version` | Server-derived | n/a |

### Stage B — Core thesis statement

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `thesis.statement / direction / strategy / timeframe` | `thesis-articulation`, `thesis-consultation` | `replace_thesis_field_str` per field |
| `thesis.conviction` | `thesis-articulation`, `thesis-consultation` | `replace_thesis_field_int` |
| `company` | `thesis-consultation` | `thesis_create(initial_fields.company)` |

### Stage C — Differentiated framing

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `consensus_view` | `earnings-scenarios`, `earnings-review`, `thesis-review`, `thesis-consultation` | `update_consensus_view` |
| `differentiated_view[]` | `critical-factors`, `thesis-articulation`, `thesis-consultation` | `add_differentiated_view_claim`, `update_differentiated_view_claim` |
| `materiality` | `critical-factors` (sole writer) | `set_materiality` |

### Stage D — Catalysts / risks / triggers

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `catalysts[]` | `critical-factors`, `earnings-scenarios`, `earnings-review`, `thesis-articulation`, `thesis-review`, `comparative-analysis`, `thesis-consultation`, `position-initiation` | `add_catalyst`, `update_catalyst` |
| `risks[]` | `identifying-risk` (primary), `quantifying-risk`, `risk-review`, `thesis-review`, `thesis-pre-mortem`, `financial-red-flags`, `critical-factors`, `thesis-consultation`, `position-initiation` | `add_risk`, `update_risk` |
| `invalidation_triggers[]` | `identifying-risk` (sole creator), `quantifying-risk`, `risk-review`, `thesis-pre-mortem`, `financial-red-flags`, `critical-factors`, `thesis-consultation` | `add_invalidation_trigger`, `update_invalidation_trigger`. **Explicit boundary:** `thesis-articulation` is forbidden to create triggers — that's `identifying-risk` territory |

### Stage E — Business overview

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `business_overview` | `fundamental-research`, `business-quality-assessment` (secondary refresh when quality work surfaces missing/stale segment context) | Not a patch op — write through `thesis_update_section("business_overview", …)` after canonical `source_refs` exist |

### Stage F — Assumptions / quantitative framing

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `assumptions[]` (create) | `forecast-assumptions`, `position-initiation` | `add_assumption`. **`critical-factors` does NOT** — uses `typed_outputs.assumptions[]` (no value/unit yet) |
| `assumptions[]` (update fields) | `earnings-scenarios`, `earnings-review`, `dcf-relative-valuation`, `comparative-analysis`, `critical-factors` | `update_assumption_field`, `replace_assumption_value`, `set_assumption_held_at_base` |
| `quantitative_framing.revenue / margins / scenarios` | `earnings-scenarios`, `earnings-review`, `thesis-review`, `dcf-relative-valuation`, `thesis-consultation` | `update_thesis_quantitative` |
| `quantitative_framing.eps_fcf` | `earnings-scenarios`, `earnings-review` | `update_eps_fcf` |
| `valuation` | `dcf-relative-valuation` (primary), `thesis-review`, `thesis-consultation` | `update_valuation` (one field per op) |

### Stage G — Peers & industry

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `peers[]` | *No current producer skill writes directly* — peers land through `industry_analysis.editorial_peer_set` | Read-compatibility only for older markdown/data; not an active write surface |
| `industry_analysis.editorial_peer_set` | `peer-curation` (gated), `competitive-position`, `comparative-analysis`, `position-initiation` | `set_editorial_peer_set`, `add_editorial_peer` |
| `industry_analysis.peer_comparison` | `position-initiation` (via canonical-comps producer), `comparative-analysis` | `replace_industry_peer_comparison` |
| `industry_analysis.operating_comparison` | `position-initiation` | `set_operating_comparison`, `set_peer_comparison_sections` |
| `industry_analysis.landscape` | `industry-landscape`, `post-comps-landscape-refresh`, `competitive-position`, `position-initiation` | `update_industry_landscape` |
| `industry_analysis.comps_narrative` | `comps-narrative` (sole writer), `position-initiation` | `update_comps_narrative` |
| `industry_analysis.macro_overlay` | `industry-macro-overlay`, `competitive-position` | `update_macro_overlay` |
| `industry_analysis.structural_trends` | `structural-trends`, `competitive-position`, `position-initiation` | `replace_structural_trends` |

### Stage H — Position / portfolio fit

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `position_metadata.portfolio_fit` | `quantifying-risk` (primary), `risk-review` | `update_portfolio_fit`; first-write goes through `typed_outputs.portfolio_fit` |
| `position_metadata.position_size` | `position-initiation` | `update_position_size` after user-approved execution or confirmed manual initiation; target pct from sizing decision, current pct from post-trade/position data when available |
| `position_metadata.date_initiated` | `position-initiation` | `set_date_initiated` after confirmed new initiation; preserves original date on add/reduce activity |

### Stage I — Model linkage

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `model_ref` | Build orchestrator (server-side) | Set on every successful `build_model` run — not skill-driven |
| `business_model_ref` | No current Thesis producer; `business-model-construction` produces a standalone `BusinessModel` artifact | Documented parallel-artifact contract. Do not imply a Thesis write until a dedicated linkage workflow exists |
| `model_links` | `decision-log` | `thesis_upsert_link` / `thesis_remove_link` |
| `scorecard` | `thesis_run_scorecard` MCP tool (read by `thesis-review`) | Written by scorecard run, not patch op |

### Stage J — Sources & provenance

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `sources[]` | `fundamental-research` (canonical), `forecast-assumptions`, plus every other producer skill emits source_refs that resolve via `register_sources` | `register_sources` op (single-register-per-batch lock) |
| `data_gaps[]` | Almost every skill — `fundamental-research`, `critical-factors`, `identifying-risk`, `thesis-articulation`, `dcf-relative-valuation`, `comparative-analysis`, `competitive-position` | `add_data_gap`, `update_data_gap`, `remove_data_gap` |
| `historical_coincidences[]` | `critical-factors` (Step 9) | `add_historical_coincidence` op — emits one per stock-move coincidence found that maps to a selected Phase 3 factor (`critical-factors.md:299`). Wired, not a gap. |
| `decisions_log[]` | Every typed-write skill (auto-appended by orchestrator); explicit append by `peer-curation`, `decision-log`, and Thesis-linked advisor runs | `thesis_append_decisions_log` |
| `raw_markdown_extras[]` | Preserved on markdown round-trip | n/a |

### Stage K — Stewardship / monitoring (Thesis as live state)

| Thesis field | Writer skill(s) | Write mechanism |
|---|---|---|
| `qualitative_factors[]` | `business-quality-assessment` (sole skill writer; process templates may seed factors at workspace creation) | `manage_qualitative_factor` |
| `ownership` | `ownership-refresh` | **Resolved 2026-05-23 by F124:** `Ownership(institutional_pct, insider_pct, recent_activity, source_refs)` is R1-enforced; producer emits `register_sources` + `update_ownership` using FMP institutional ownership and insider-trades data. |
| `monitoring.watch_list` | `monitoring-init` | **Resolved 2026-05-23 by F124:** `Monitoring.watch_list` is typed as `list[WatchItem]`; producer emits `update_monitoring` from sourced near-term Thesis catalysts and bails out rather than overwriting an existing watch list. |

---

## Gap summary

### Schema slots with no producer (latent fields)

| Gap | Field | Why it matters for the autonomous loop |
|---|---|---|
| **G1** | `peers[]` | Compatibility-only field. Canonical peer writes go to `industry_analysis.editorial_peer_set`; old `peers[]` may still be parsed/read but is not an active contract surface. |
| ~~G2~~ | ~~`position_metadata.position_size`~~ | **Resolved 2026-05-22:** `position-initiation` applies `update_position_size` after confirmed execution/manual initiation using the resolved `research_file_id`. |
| ~~G3~~ | ~~`position_metadata.date_initiated`~~ | **Resolved 2026-05-22:** `position-initiation` applies `set_date_initiated` for new initiations and preserves the original date on add/reduce activity. |
| ~~G4~~ | ~~`historical_coincidences[]`~~ | **Resolved 2026-05-20:** `critical-factors` Step 9 emits `add_historical_coincidence` per coincidence. Not a gap. |
| ~~G5~~ | ~~`ownership`~~ | **Resolved 2026-05-23:** `ownership-refresh` writes sourced ownership through `update_ownership`. |
| ~~G6~~ | ~~`monitoring.watch_list`~~ | **Resolved 2026-05-23:** `monitoring-init` writes typed watch items through `update_monitoring`. Cadence loop closed 2026-05-29 by F129 (`position-reassess` skill + `evaluate_thesis_monitoring` MCP tool + `update_watch_item` patch op). |
| ~~G7~~ | ~~`model_links`~~ | **Resolved 2026-05-22:** `decision-log` is the producer and uses `thesis_upsert_link` / `thesis_remove_link` for durable model/claim links. |
| **G8-DOC** | `business_model_ref` | Documented as no current Thesis producer. `business-model-construction` writes a standalone BusinessModel artifact; a future explicit linkage workflow can promote this into an active Thesis field. |

### Cross-stage gaps (loop-level, not field-level)

| Gap | Description |
|---|---|
| ~~L1 — Monitoring/exit driving skill~~ | **Resolved 2026-05-29:** F129 ships `position-reassess` skill driving the loop autonomously under `research_producer` profile. `evaluate_thesis_monitoring` MCP tool runs deterministic Tier-1 breach evaluation; Tier-2/3 route to manual-review with linked catalyst `expected_date`. See [`../architecture/AUTONOMOUS_MONITORING_LOOP.md`](../architecture/AUTONOMOUS_MONITORING_LOOP.md). |
| ~~L2 — Idea→thesis bridge~~ | **Resolved 2026-05-29:** F128 idea→thesis bridge shipped (`495c4a47`) + live-verified end-to-end on 2026-05-29 re-run (under `research_producer`, 23 turns, verdict THESIS_WRITTEN). `idea-to-thesis` skill drives `thesis-consultation MODE=autonomous` via `invoke_skill` text-injection. |
| ~~L3 — Position-sizing→Thesis writeback~~ | **Resolved 2026-05-22:** `position-initiation` closes sizing → execution/manual confirmation → `Thesis.position_metadata` via `update_position_size` and `set_date_initiated`. |
| ~~L4 — Reassessment cadence~~ | **Resolved 2026-05-29:** F129 cadence wrapper (`run_position_reassess_cadence.py` + systemd timer daily 18:00 ET) fans out one autonomous run per `research_file_id` over the `thesis_list ∩ get_positions` universe. See [`../architecture/AUTONOMOUS_MONITORING_LOOP.md`](../architecture/AUTONOMOUS_MONITORING_LOOP.md). |

### Skill state classification

Per [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md) **R12**, every shipped skill declares one of: `producer`, `advisor-with-decision-log`, or `advisor-no-state` in frontmatter. `deprecated` remains an enum value for future hard-retirement work but is not used by any active shipped skill. Autonomous / scheduled skills must be `producer` or `advisor-with-decision-log` — they cannot be `advisor-no-state`.

Candidates that may need promotion to `producer` in later work:
- `assumption-audit` → flagged drift could mark `assumptions[].held_at_base = false` or append to a new `assumption_audit_log[]`.
- `performance-review` → trade scorecards could update `scorecard` or append to `decisions_log` with structured outcome data.
- `model-vs-consensus` → could be a regular write to `consensus_view` with structured delta tracking.
- `dilution-analysis`, `debt-sensitivity-analysis` → could write to `risks[]` or a new structured-risk-finding slot.
- `morning-briefing` → if scheduled / autonomous, must be at least `advisor-with-decision-log` per R12; can surface watch-list breaches now that F124 typed `watch_list` is available.

---

## How to read this matrix

1. **For the design** — see [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md). That doc has the locked decisions (D1-D10), design rules (R1-R12), success criteria (1-9), and verification table (V1-V12). This matrix is the inventory the design references.
2. **For the narrow e2e (F131)** — pick a vertical slice that exercises the wired write surface (e.g., `fundamental-research` → `critical-factors` → `identifying-risk` → `earnings-scenarios` → `dcf-relative-valuation` → `thesis-consultation` → `build-model`) and assert (a) the final Thesis shape, (b) every claim's `source_refs` resolves to a `SourceRecord` with at least one `Excerpt` atom (D1), (c) `build_model` produces the expected `.xlsx`, (d) zero same-target claim + data_gap pairs (R6), (e) all `update_*` ops in decisions_log have fresh evidence or carry-forward rationale (R9). See layers doc Success Criteria 1, 7, 8, 9.
3. **For active workstreams** — gaps map to TODO entries. **Shipped (2026-05-29 snapshot):** G5/G6 (F124), audit-chain hygiene (F125, shipped 2026-05-28), gating policy (F126), enforcement-via-F2j (F134, absorbed and closed 2026-05-27), L2 idea→thesis (F128, shipped + live-verified 2026-05-29), L1/L4 monitoring/exit (F129, shipped + live-verified 2026-05-29 — canonical doc at [`../architecture/AUTONOMOUS_MONITORING_LOOP.md`](../architecture/AUTONOMOUS_MONITORING_LOOP.md)). **Still open:** strict-audit live green run (F131), rich PositionSnapshot (F132, parked until real-use signal). F124, F126, F127, F130, F133, F135 are completed verification/wiring passes. See [`../TODO.md`](../TODO.md) and [`../TODO_COMPLETED.md`](../TODO_COMPLETED.md).

---

## Verification checklist (tracked by F130)

The matrix below is a snapshot. These items should be confirmed before treating any single row as load-bearing. F130 owns the work; layers doc V1-V12 covers a complementary verification of design-level premises (tracked by F135).

- [x] Confirm `business-model-construction` skill write surface: standalone BusinessModel artifact + memory pointer; no `Thesis.business_model_ref` write.
- [x] Confirm `decision-log` skill write surface: producer for `decisions_log` and `model_links` via `thesis_append_decisions_log` / `thesis_upsert_link`.
- [x] Confirm `earnings-review` full write surface: proposes HandoffPatchOps for scenario/consensus/quantitative refresh and writes memory freshness fields; it does not auto-apply Thesis ops.
- [x] Confirm `industry-onboarding` actual writes: owns industry staging/config output and delegates canonical peer Thesis writes to `peer-curation`.
- [x] Confirm `business-quality-assessment` writes to `business_overview`: durable path is `thesis_update_section`; `qualitative_factors[]` path is `manage_qualitative_factor`.
- [x] Run a grep across all skill prose for `op:` patterns to catch any patch ops missed by the keyword sweep.
- [x] Validate against the actual patch engine — matrix no longer lists non-patch tool writes as HandoffPatchOps (`manage_qualitative_factor`, `thesis_update_section`, `thesis_upsert_link`, `thesis_append_decisions_log` are explicit tool paths).
- [x] **Classify every shipped skill per R12** (`producer` / `advisor-with-decision-log` / `advisor-no-state`) — added to skill frontmatter with tests; no active skill uses `deprecated`.

---

## Related

- Memory: [[project_thesis_design_for_autonomous_fund]] — long-horizon scope decision (2026-05-20).
- Plan docs (completed): `HANDOFF_ARTIFACT_V1_1_PLAN.md`, `BUILD_MODEL_FOR_HANDOFF_MCP_PLAN.md`, `MODEL_BUILD_CONTEXT_PLAN.md`, `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md`.
- Schema source: `AI-excel-addin/schema/thesis.py:263` (Thesis root), `thesis_shared_slice.py:508` (IndustryAnalysis), `handoff_patch.py` (patch op registry).
- Skill source: `AI-excel-addin/api/memory/workspace/notes/skills/`.
