# Research Artifact Layers — Unified Design

**Status:** Design — decisions locked 2026-05-20. Canonical authority for the Thesis / Research Artifact / autonomous-loop architecture.
**Purpose:** Single coherent design for how the three layers (Evidence / Typed Conclusions / Frozen Snapshot) fit together, what invariants they uphold, what decisions resolve formerly-open architecture questions, and what success looks like end-to-end.
**Pairs with:** [`THESIS_WRITE_SURFACE_COVERAGE.md`](THESIS_WRITE_SURFACE_COVERAGE.md) — the producer-side inventory (skill × Thesis section). This doc is the design; the matrix is the inventory.
**Active workstreams:** F125 (W2), F128, F129, F131, F132, F134 (W3 enforcement) — see [`../TODO.md`](../TODO.md) "Thesis & Research Artifact" section. F124/F126/F127/F130/F133/F135 completed work is archived in [`../TODO_COMPLETED.md`](../TODO_COMPLETED.md).

---

## TL;DR

"Research artifact" isn't a single object. It's a **stacked pipeline**:

```
LAYER 3 — Frozen snapshot       (HandoffArtifact, versioned)
    ↑ promoted by finalize_handoff / new_handoff_version
LAYER 2 — Typed conclusions     (Thesis sections — risks, assumptions, catalysts, etc.)
    ↑ written by ~24 producer skills via patch ops
LAYER 1 — Evidence              (Thesis.sources[] with typed Excerpt atoms + data_gaps; annotations are derived UI rendering, not authoritative storage)
    ↑ written by reading filings/transcripts, registering sources, flagging gaps
```

**The evidence layer is the audit/traceability backbone.** Every Layer 2 claim carries `source_refs` pointing to Layer 1; without that linkage, claims are unfalsifiable opinions. As the autonomous investment loop ladders up to monitoring, reassessment, and exit decisions, the audit chain is what makes those decisions trustworthy.

---

## The three layers in detail

### Layer 1 — Evidence

**What it is:** The granular ground truth — what was read, what was found, what was looked-for-and-missing.

**Where it lives (authoritative storage):**
- `Thesis.sources[]` — registry of registered `SourceRecord` rows with stable `src_N` IDs (filings, transcripts, FMP queries, EDGAR concepts, peer comps producers, etc.); identity-hashed for deduplication across snapshots; each `SourceRecord` carries `excerpts: list[Excerpt]` atoms (per D1) which are the canonical quoted-text storage.
- `Thesis.data_gaps[]` — structured "tried to find X, didn't" entries with severity (`blocking`, `approximate`, `minor`), workaround notes, and rationale.

**Where it lives (derived / non-authoritative):**
- `annotations` table — UI render-cache over `Excerpt` atoms (collapse/highlight/comment metadata only, per D1). NOT authoritative; deleting the annotations table does not break the audit chain.
- `research_messages` table — chat thread inside the research workspace (agent's reasoning scratchpad, per D4). Not formal audit material; the audit primitive is typed claim + source_refs + Excerpt linkage + `decisions_log` rationale.

**Write surface (authoritative):**
- MCP: `register_sources` patch op (single-register-per-batch lock; see `patch_engine.py:735`) — also persists cited `Excerpt` atoms (D1, F125).
- MCP: `add_data_gap` / `update_data_gap` / `remove_data_gap`.

**Write surface (UI-only / non-authoritative):**
- UI: `AnnotationPopover.tsx`, `TextSelectionHandler.tsx`, `HighlightLayer.tsx` (text selection → annotation create as UI render-cache entry).
- MCP: `create_annotation` / `create_annotations` (`mcp_tools/research.py:189,247`) — creates render-cache rows; underlying Excerpt must already exist on a `SourceRecord` per R4.
- Implicit: every research thread interaction lands a `research_message` (reasoning trace, not audit).

**Producers:** `fundamental-research` (canonical evidence assembler — registers sources, names gaps), plus every other producer skill that emits `source_refs` on its typed claims (which transitively requires registering those sources first).

### Layer 2 — Typed conclusions

**What it is:** Synthesized claims with typed shape. The Thesis itself.

**Where it lives:**
- `theses` table (SQLite, AI-excel-addin)
- `schema/thesis.py:263` (Thesis root, 365 lines)
- `schema/thesis_shared_slice.py` (sections — 580 lines)
- Top-level fields: company, thesis statement, consensus_view, differentiated_view, invalidation_triggers, business_overview, catalysts, risks, valuation, peers, assumptions, qualitative_factors, ownership, monitoring, industry_analysis, materiality, historical_coincidences, quantitative_framing, position_metadata, model_ref, business_model_ref — see matrix doc for full enumeration

**Write surface:**
- `apply_patch_ops` (canonical agent path) — 30+ typed `HandoffPatchOp` kinds in `schema/handoff_patch.py`
- `update_handoff_section` / `batch_update_handoff_sections` — section-level writes from UI
- `thesis_update_section` — used by orchestrator for business_overview after `register_sources` resolves canonical IDs
- `manage_qualitative_factor` — qualitative factor add/remove/update

**Producers:** 24 skills (see matrix doc Stage A-K). Most analytical skills operate here — `critical-factors`, `identifying-risk`, `earnings-scenarios`, `dcf-relative-valuation`, `industry-landscape`, etc.

### Layer 3 — Frozen snapshot

**What it is:** Versioned promotion of Thesis state for downstream build consumption. Immutable once finalized.

**Where it lives:**
- `research_handoffs` table (one row per version)
- `schema/handoff.py` — `HandoffArtifactV1_2` Pydantic. **Production default is v1.2** (`schema_version: Literal["1.1", "1.2"] = "1.2"` at line 155); v1.1 is read-only legacy compat (verified F135).
- Derives shared slice from Thesis verbatim on snapshot, layers on handoff-only fields: `idea_provenance`, `assumption_lineage`, `process_template_id`, `thesis_ref`, `model_ref` (Handoff-shaped), `scorecard_ref`

**Write surface:**
- `finalize_handoff` — draft → finalized state transition
- `new_handoff_version` — finalized → new draft (re-derives from Thesis)
- `BuildModelOrchestrator.build_and_annotate` — reads finalized handoff, produces .xlsx + ModelInsights + PriceTarget

**Consumers:** The model build is the primary consumer. Future consumers (monitoring agent, exit agent, audit/replay process) read here when they need the exact decision context at a point in time.

---

## The evidence-as-audit-backbone principle

Every Layer 2 claim must trace back to Layer 1 evidence or be flagged in `data_gaps`. This is the falsifiability discipline that makes the system trustworthy.

**Already enforced in code:**

| Discipline | Where enforced | Source |
|---|---|---|
| `add_differentiated_view_claim` requires non-empty `evidence: [SourceId]` | Patch engine rejects op | `patch_engine.py` + `schema/handoff_patch.py:387` |
| `source_refs` field present on Assumption, Risk, Catalyst, Valuation, BusinessOverview, IndustryLandscape, MacroOverlayDriver, StructuralTrend, GaapNonGaapBridge, HistoricalCoincidence, MaterialityThreshold, Peer, Ownership, Monitoring, QualitativeFactor | Pydantic schema | `schema/thesis_shared_slice.py` (multiple classes) |
| `register_sources` runs under single-register-per-batch lock | Patch batch validation | `patch_engine.py:735` |
| Sources are identity-hashed for dedup across snapshots | `_SourceRefRegistry` class (v1.1+) → Thesis-rooted `sources[]` | `api/research/handoff.py:138` (verified F135) |
| `iter_source_refs` walks the full payload to validate that every `src_N` reference resolves to a registered source | Patch engine validation | `api/research/handoff.py:238` |
| `decisions_log[]` auto-appended on every patch batch with rationale + ops summary | Orchestrator after `apply_patch_ops` | `patch_engine.py` |
| `add_data_gap` is the explicit "we tried, didn't find" channel — and many skills emit it gates downstream insufficient-data verdicts | Skill prose (`fundamental-research`, `critical-factors`, `identifying-risk`, etc.) |  |

**Partially enforced / discipline-dependent:**

- Most Thesis nested models have `source_refs` as an *optional* field (default empty list). The patch engine doesn't reject claims with empty `source_refs` outside `differentiated_view_claim`. Skills are expected to populate it; nothing forces them to.
- `historical_coincidences[]` captures "when X happened in the past, the stock moved Y" — evidence that supports invalidation-trigger calibration. Produced by `critical-factors` Step 9 via `add_historical_coincidence` (per D2, matrix gap G4 resolved).
- The chat thread (`research_messages`) is the agent's reasoning trace, but isn't formally part of the audit chain that the patch engine validates. Replay today reconstructs Thesis state, not the reasoning that produced it.

---

## How the layers relate

```
                       reads/promotes
   Layer 1 evidence ─────────┐
        │                    │
        │ source_refs        ▼
        │              Layer 3 snapshot (HandoffArtifact)
        ▼                    ▲
   Layer 2 typed             │
   conclusions (Thesis) ─────┘
                       finalize_handoff
                       new_handoff_version
```

- **Layer 1 → Layer 2:** Producer skills register sources first (Layer 1 write), then emit typed claims that reference those sources via `source_refs` (Layer 2 write). The same patch batch can do both; `register_sources` runs first under the batch lock.
- **Layer 2 → Layer 3:** `finalize_handoff` derives the shared slice from Thesis verbatim and writes a `research_handoffs` row. Layer 3 is immutable once finalized.
- **Layer 3 → consumer (build):** Build orchestrator reads finalized handoff, runs build + annotate atomically, emits ModelInsights + PriceTarget as non-critical side effects.
- **Layer 3 → audit (latent):** A monitoring/exit/reassessment agent reading Layer 3 sees the frozen decision context. Adding new conclusions requires `new_handoff_version` (which re-derives from current Thesis).

---

## Why the framing matters for the autonomous loop

In a human-in-the-loop workspace, the audit chain is nice-to-have — the analyst remembers why they wrote a claim. In an autonomous-investment-loop, the audit chain is the **trust mechanism**:

- **Monitoring agent** asks: "Has Risk-3's invalidation trigger fired?" — must trace from the trigger back to which evidence anchored it (Layer 1) and which assumption it pairs with (Layer 2).
- **Exit agent** asks: "Has the differentiated view broken?" — must trace from the consensus delta to the consensus_view sources (Layer 1) and the differentiated_view evidence (Layer 1).
- **Reassessment agent** asks: "What's changed since the last finalize?" — diffs Layer 3 snapshots, then drills into Layer 2 changes, then asks Layer 1 "did the underlying evidence change or just the synthesis?"
- **Audit/replay** asks: "Reconstruct what we knew at time T" — Layer 3 snapshot anchors the typed conclusions; Layer 1 anchors the evidence those conclusions cited.

Decisions made without traceable evidence chains is the failure mode the layer model exists to prevent.

---

## Design decisions

Each decision below resolves a question raised in the 2026-05-20 review. Decisions are locked; revisit only with new evidence.

### Wiring-level decisions

**D1 — Excerpts are first-class on `Thesis.sources[]` as typed `Excerpt` atoms. Annotations are UI rendering of those atoms, not authoritative storage.**
Autonomous skills bypass annotations today (verified — only 4 skills mention them, none as producers). The audit chain needs the actual quoted text native to Thesis so replay/finalize captures it without an off-Thesis sidecar. **Decision:**
- Extend `SourceRecord` with `excerpts: list[Excerpt]` where `Excerpt = {excerpt_id, text, locator, hash, claim_ids, created_by, created_at}`. `locator` is structured (char range / page / section anchor). `hash` is content-addressable for dedup. `claim_ids` enables source→claim back-reference for UI rendering.
- When `register_sources` runs, the agent persists each cited excerpt as an `Excerpt` atom under its `SourceRecord`. Cardinality: many excerpts per source; multiple claims may reference the same excerpt (via `Excerpt.claim_ids`).
- Annotations are **derived UI state** — the `annotations` table becomes a render-cache over Excerpt atoms (collapse/highlight/comment metadata only). Annotations are no longer authoritative; deleting them does not break the audit chain.
- HandoffArtifact snapshot preserves the full Excerpt atoms verbatim via the shared-slice inherit of `Thesis.sources[]`. Layer 3 immutability holds without a separate evidence-snapshot table.

Closes by F125 (W2). *Formerly Q1.*

**D2 — `historical_coincidences[]` is wired.** `critical-factors` Step 9 emits `add_historical_coincidence` per coincidence found that maps to a Phase 3 factor (`critical-factors.md:299`). Matrix G4 is closed. No further action. *Formerly Q2.*

**D3 — Type `WatchItem` + add `update_ownership` / `update_monitoring` patch ops + wire producers. Completed 2026-05-23.**
`monitoring.watch_list` was intentionally schema-free per `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md:355-357` (deferred-to-usage punt — usage never came). `ownership` was unwired with no rationale. For the autonomous loop, both are required slots — monitoring/exit agents read them. **Decision shipped by F124:** `Monitoring.watch_list` is typed as `list[WatchItem]`, `Ownership` carries R1 evidence validation, `update_ownership` + `update_monitoring` patch ops are supported by the patch engine, `ownership-refresh` writes FMP-derived ownership, and `monitoring-init` derives initial watch items from sourced Thesis catalysts. *Formerly Q3.*

**D4 — `research_messages` (chat thread) is NOT formal audit material.**
90%+ of messages are exploratory back-and-forth; treating them as audit material drowns the signal. The audit primitive that matters is **typed claim + source_refs + decisions_log rationale**. **Decision:** the chat thread stays as the reasoning scratchpad; audit material is Layer 1 evidence + Layer 2 claims with source_refs + Layer 2 `decisions_log` entries. Discipline gap (some skills write thin rationales) is closed by F125 (W2) extending `decisions_log` for zero-patch entries with rationale. *Formerly Q4.*

### Architecture-level decisions

**D5 — Three-layer model is the right factoring. No Layer 2.5.**
The "computed vs argued" distinction (`quantitative_framing.scenarios` is model-computed; `risks[]` is filings-argued) is real but encoded in `source_refs` + `confidence` + `derived` flag on `CompMetricCell`. Adding a tier increases cognitive load without giving consumers a new affordance. **Decision:** discipline goes in `source_refs` hygiene (D1), not in a new tier. *Formerly Q5.*

**D6 — Introduce `PositionSnapshot` to compose HandoffArtifact + runtime state for monitoring/exit consumers. Minimal contract is part of F129; richer schema is F132.**
HandoffArtifact is correct for the **build** consumer (decision context as of finalize time) and must stay immutable. Monitoring/exit need decision context **plus** live runtime state (current price, holding period, position size, recent invalidation breaches). **Decision:** introduce `PositionSnapshot` as a composition: `{handoff_artifact: HandoffArtifact, runtime: PositionRuntimeState}`. Do not bloat HandoffArtifact with mutable runtime fields. **Minimal contract** (`{current_price, position_size, holding_period_days, recent_invalidation_breaches[]}`) is part of F129 — monitoring agent cannot function without it. **Richer schema expansion** (additional runtime fields as use cases emerge) is F132, sequenced after F129 ships against the minimal contract. *Formerly Q6.*

**D7 — Layer 1 writes follow the same lock/dedup discipline as `register_sources`.**
Today Layer 2 has OCC under the patch engine, Layer 3 has versioned-immutable. Layer 1 (annotations) has write-once-no-validation — weak link for autonomous concurrent writes. **Decision:** before more agents write Layer 1, formalize the Layer 1 write contract with the same single-register-per-batch lock + identity-hash dedup story `register_sources` already has. Closes by F125 (W2) item (c). *Formerly Q7.*

**D8 — Move `ModelInsights` + `PriceTarget` onto Thesis as Layer 2 fields with `derived_from: model_build_context_id` provenance. Completed 2026-05-23.**
They previously lived only in side tables. A monitoring agent asking "what's the current price target?" had to know to look elsewhere — which violated Success Criterion 6 (monitoring reads only Thesis + PositionSnapshot). **Decision shipped by F133:** `Thesis.model_insights[]` and `Thesis.price_target` are first-class Layer 2 projection fields with explicit `derived_from_model_build_context_id` provenance. Side tables remain historical snapshot storage; Thesis fields are the canonical current read path. `Thesis.model_insights[]` deliberately omits `handoff_patch_suggestions` to avoid the `ModelInsights -> HandoffPatchOp -> Thesis` schema cycle and to keep advisory patch queues out of durable current state. *Formerly Q8.*

**D9 — Extend `decisions_log[]` to accept zero-patch entries. Don't build a separate event log.**
`decisions_log` covers *write audit* correctly. Gaps: (a) skills running `INSUFFICIENT_DATA` verdicts disappear (no batch applied); (b) read audit (which sources consulted before deciding) — covered by D1's `Excerpt` atoms on `Thesis.sources[]` (the citing claim is linked via `Excerpt.claim_ids`). **Decision:** small schema change — `DecisionsLogEntry` accepts zero-op entries with `verdict` + `rationale`. "Skill ran, found nothing actionable" becomes auditable. No separate event log. Closes by F125 (W2) item (b). *Formerly Q9.*

**D10 — Autonomous-write gating policy: reversibility × confidence × blast radius. Policy AND enforcement.**
Today's discipline is ad-hoc (only `peer-curation` has an explicit gate). Implicit "all Thesis writes reversible" assumption is false once a build/trade has acted. **Decision — uniform policy:**
- **Thesis-only writes** (no downstream side effects): autonomous OK.
- **Build-affecting writes** (e.g. `update_thesis_quantitative` that triggers a rebuild): autonomous with auto-build OK; emit a "build-triggered" `decisions_log` entry.
- **Portfolio-affecting writes** (anything chaining to `execute_trade`): **always** human gate. `position-initiation` does not autonomously execute trades.
- **Low-confidence writes** (no `source_refs` or no resolved evidence): blocked at the patch engine. `add_differentiated_view_claim` is one instance of the evidence-required pattern; R1 generalizes it to **all Thesis mutation paths** (add ops, update ops, section writes, qualitative_factor writes, direct repository writes).

**Two-part delivery** — policy doc alone is insufficient because R7 + Success Criterion 4 require actual enforcement:
- **F126** shipped the policy document (decision-only) in [`F126_AUTONOMOUS_WRITE_GATING_POLICY.md`](F126_AUTONOMOUS_WRITE_GATING_POLICY.md).
- **F134** ships the enforcement — orchestrator dispatch gate keyed on op classification, skill-level boundary checks, tests for "no execute_trade without human gate" and "build-affecting writes emit decisions_log entry." D10 is not closed until both ship.

*Formerly Q10.*

---

## Design rules / invariants

These are the discipline rules a new skill, schema field, or patch op must satisfy. They derive from the decisions above and are the checks anyone proposing a change should run against.

| # | Invariant | Enforcement |
|---|---|---|
| **R1** | **All Thesis mutation paths run the audit validator before commit/finalize.** Not just `add_*` patch ops — also `update_*` patch ops, `update_handoff_section`, `batch_update_handoff_sections`, `thesis_update_section`, `manage_qualitative_factor`, and any direct repository write. Validator enforces: any field carrying a positive factual/analytical claim has non-empty `source_refs` resolving to a `SourceRecord` that contains at least one `Excerpt` atom whose `claim_ids` includes the citing claim's stable ID (per D1). Source-existence alone is insufficient — the specific claim must be linked to the specific excerpt(s) supporting it. `add_differentiated_view_claim`'s evidence-required pattern is one instance of this rule, not the boundary. | Patch engine + action-layer validator covering all write paths; claim→excerpt linkage check at op-validation time. |
| **R2** | **Schema-free fields are tech debt — both new and existing.** Any new Thesis field added without a typed shape requires a typed-by-or-removed date in the design doc that introduces it. **Existing schema-free fields require the same sunset commitment**: migration owner, typed replacement, compatibility window, reader behavior during migration, and removal/deprecation criteria. (Lesson from `monitoring.watch_list` punt — D3; F124 closed that sunset.) | Code review + plan doc gate. |
| **R3** | Producer-skill description must declare which Thesis sections / patch ops it writes. Advisor-only skills must justify in description why they don't persist. | Skill frontmatter convention + `tests/skill_evals/` shape tests. |
| **R4** | Layer 1 writes follow the same lock/dedup discipline as `register_sources`. No new write-once-no-validation paths to Layer 1. (D7.) | Write contract enforced at the action layer (`actions/research.py`). |
| **R5** | `decisions_log` captures **every** skill-driven Thesis interaction including zero-patch verdicts. "Skill ran, found nothing actionable" must be auditable, not invisible. (D9.) | Orchestrator post-skill hook. |
| **R6** | **A positive factual or analytical claim cannot be paired with a same-target `add_data_gap` to legalize speculation.** The two are mutually exclusive per field: either the field carries a sourced claim, OR the field carries a `data_gap` entry — not "claim X" + "missing evidence for X." Producer skills with `INSUFFICIENT_DATA` verdicts emit the data_gap and abstain from the claim. | Patch engine validation (rejects same-target claim + data_gap pairs in one batch) + audit-chain replay validates over time. |
| **R7** | Build-affecting writes auto-trigger build + emit "build-triggered" `decisions_log` entry. Portfolio-affecting writes (chains to `execute_trade`) **always** require human gate. Thesis-only writes are autonomous. (D10.) | Orchestrator dispatch + skill-level gate (`position-initiation` is the canonical example for trade-affecting). Enforcement tracked by F134. |
| **R8** | HandoffArtifact stays immutable. Runtime state (price, position size, holding period, breaches) lives in `PositionSnapshot` as a composition, not on HandoffArtifact. (D6.) | Schema — HandoffArtifact has no mutable runtime fields. PositionSnapshot is the runtime-augmented read shape. |
| **R9** | **Update-op invariant.** Updates that materially change claim semantics (text / value / severity / threshold / direction) require either fresh `source_refs` resolving to a `SourceRecord` with at least one new `Excerpt` atom, OR an explicit carry-forward rationale recorded in `decisions_log`. Update paths cannot clear `source_refs` unless the update converts the field to a `data_gap` or deprecated state. | Patch engine validation on every `update_*` op. |
| **R10** | **Canonical state + read compatibility.** Each state surface has one current canonical write target. Older shapes may stay readable as compatibility input, but new skill/tool contracts must not advertise multiple active write homes for the same concept. Compatibility handling requires: (a) mapping from old shape to canonical typed shape, (b) reader fallback for in-flight data, (c) tests proving canonical writes do not mutate the compatibility field. Applies to `peers[]` → `industry_analysis.editorial_peer_set` (F130) and `monitoring.watch_list` schema-free → typed transition (F124). | Plan doc gate + parity tests at code review. |
| **R11** | **Source identity + conflict resolution.** `SourceRecord` identity is computed by `identity_hash` over `(type, source_id, accession, period)` (or equivalent stable key per source type). Duplicate sources across `register_sources` calls dedupe to the existing record; metadata divergences must reconcile or fail loudly (not silently overwrite). Excerpts within a `SourceRecord` dedupe by `Excerpt.hash`. URL/accession changes generate a new `SourceRecord` (immutable IDs) and link via `superseded_by` rather than mutating in place. | Patch engine validation on `register_sources` + integration tests for refresh/replay scenarios. |
| **R12** | **Skill classification.** Every shipped skill declares one of: `producer` (writes typed durable state through a supported tool path, including HandoffPatchOps, Thesis section/link/log tools, workbook writes, schedules, or canonical artifacts), `advisor-with-decision-log` (no typed state mutation but leaves an auditable verdict / recommendation / run record), or `advisor-no-state` (purely conversational; never runs autonomously, never appears in scheduled jobs). `deprecated` is reserved for future hard-retirement work and is not used for active shipped skills. **Autonomous / scheduled skills must be `producer` or `advisor-with-decision-log`** — they cannot be `advisor-no-state` (would leave invisible runs). Closes the advisor-only boundary problem from the matrix. | Skill frontmatter + validation tests + autonomous scheduler reads classification on load. |

---

## Success criteria

How we know the design works end-to-end. Each criterion is a check that should pass against any in-production Thesis once F124-F135 ship (specifically: F124, F125, F126, F130, F134, plus shipped F127 position lifecycle writeback and F133 model-output Thesis projections — F128/F129/F131/F132/F135 close criterion 7 and the long-horizon loop).

1. **Audit chain.** Pick any claim in any production Thesis; trace it to a registered `SourceRecord` containing at least one `Excerpt` atom (text + locator + hash) whose `claim_ids` includes that claim's stable ID. The link is bidirectional: claim → source_refs → excerpt → claim_ids. Zero claims pointing to opaque `src_N` IDs without a specific resolvable Excerpt linked back. (D1, R1)
2. **Replay.** A `research_handoffs` row finalized at time T reconstructs exactly — same sources (with full Excerpt atoms verbatim), data_gaps, typed conclusions, decisions_log entries. No off-Thesis state needed for replay (annotations are derived UI state per D1, not authoritative). (D1)
3. **Coverage.** Every shipped skill is classified per R12 (`producer` / `advisor-with-decision-log` / `advisor-no-state`). Autonomous-scheduled skills emit patch ops or explicit zero-patch `decisions_log` entries — never `advisor-no-state`. No autonomous skill run goes invisible. (R5, R12)
4. **Boundary — enforced.** No autonomous skill chains to `execute_trade` without an explicit human gate. No build-affecting Thesis write fires without an accompanying build attempt. **Enforced by orchestrator gate + tests, not policy alone** (F134, R7).
5. **Schema completeness.** Every Thesis field either has a documented producer (per matrix doc) or is explicitly documented as compatibility-only / parallel-artifact / future-work. The matrix doc has zero ambiguous "Unwired" rows.
6. **Cross-stage read.** A monitoring/exit/reassessment agent answers its questions reading only `Thesis` + `PositionSnapshot` — no detour to `model_insights`, `price_targets`, or other side tables. F133 closed the ModelInsights/PriceTarget Thesis read path; F129 still adds the PositionSnapshot runtime half. (D8 + D6)
7. **Narrow e2e.** F131 LLM-in-the-loop e2e passes: agent does research, Thesis populated correctly, every claim traces to a `SourceRecord` with at least one `Excerpt` atom whose `claim_ids` references it, `finalize_handoff` succeeds, `build_model` produces `.xlsx`. (R1, R6)
8. **Audit invariant.** No production Thesis contains a same-target claim + `data_gap` pair (R6). Audit chain replay over the full production set returns zero violations.
9. **Update invariant.** All `update_*` ops in `decisions_log` history have either fresh `source_refs` or an explicit carry-forward rationale. Zero updates silently cleared evidence. (R9)

When all 9 hold, the autonomous-loop foundation is shippable. Monitoring/exit/reassessment agents (F129 and beyond) build on top of this foundation; they don't need to renegotiate the contracts.

---

## Mapping decisions → workstreams

| Decision | Closed by | Status |
|---|---|---|
| D1 (excerpts as typed atoms on `Thesis.sources[]`; annotations as UI rendering) | F125 (W2) | NEEDS PLAN |
| D2 (`historical_coincidences` already wired via `critical-factors` Step 9) | — | Resolved 2026-05-20 |
| D3 (type `watch_list` + ownership patch ops) | F124 (W1) | Completed 2026-05-23 |
| D4 (`research_messages` not audit material; rationale discipline) | F125 (W2) item (b) | NEEDS PLAN |
| D5 (three layers, no 2.5) | — | Decided; no action |
| D6 (PositionSnapshot composition — minimal in F129, rich in F132) | F129 (minimal) + F132 (rich) | NEEDS PLAN (F129) / PARKED (F132) |
| D7 (Layer 1 write contract) | F125 (W2) item (c) | NEEDS PLAN |
| D8 (ModelInsights/PriceTarget → Thesis — prereq for F129) | F133 | Completed 2026-05-23 |
| D9 (`decisions_log` zero-patch entries) | F125 (W2) item (b) | NEEDS PLAN |
| D10 (autonomous-write gating policy + enforcement) — *decision locked; policy shipped, enforcement pending* | F126 (policy) + F134 (enforcement) | F126: Completed 2026-05-23 / F134: PLAN DRAFTED |

**Dependency chain for the monitoring/exit loop:** F125 + F134 must ship before F129 starts. F124 and F126 shipped 2026-05-23, F127 shipped 2026-05-22, and F133 shipped 2026-05-23, so none of those block this chain. F134 enforcement is a hard prerequisite — monitoring agents make autonomous Thesis writes, so the gating policy must be enforced before they ship. F132 (rich PositionSnapshot) follows F129. **Recommended start order:** F125 → F134 (enforcement) → F129.

Plus enabling/dependent work:
- ~~F124~~ — typed Thesis watch-list / ownership wiring (G5/G6/D3) — **completed 2026-05-23**
- ~~F126~~ — autonomous-write gating policy decision (D10 policy half) — **completed 2026-05-23**
- ~~F127~~ — position lifecycle Thesis writeback (G2/G3/L3) — **completed 2026-05-22** (`update_position_size` + `set_date_initiated` wired through `position-initiation`)
- F128 — idea→thesis autonomous bridge (L2)
- F129 — reassessment cadence skill (L1/L4) — depends on F125 + F134
- ~~F130~~ — verify latent writers + canonicalize `peers[]` read-compatibility + skill classification per R12 — **completed 2026-05-22**
- F131 — agent-driven narrow e2e (success criterion 7)
- ~~F133~~ — ModelInsights + PriceTarget Thesis integration — **completed 2026-05-23** (`Thesis.model_insights[]` + `Thesis.price_target` projection fields)
- F134 — W3 enforcement (orchestrator gates + skill-level boundaries + tests for R7) — **plan drafted 2026-05-23**
- F135 — verify load-bearing premises in this doc against the implementation (see Verification section below)

---

## Verification — load-bearing premises to confirm before implementation

This doc makes claims about how the existing system works. Several reference code in the sibling `AI-excel-addin/` repo and cannot be auto-verified from this sandbox. Confirm before any F124-F134 work lands, since wrong premises invalidate downstream design:

| # | Claim | Source asserted | How to verify |
|---|---|---|---|
| V1 | `register_sources` runs under single-register-per-batch lock | `patch_engine.py:735` | `grep -n "RegisterSources\|register.*lock\|single.*register" AI-excel-addin/api/research/patch_engine.py` |
| V2 | `add_differentiated_view_claim` is the only patch op that hard-rejects empty `evidence` | `handoff_patch.py:387` | Read `handoff_patch.py` AddDifferentiatedViewClaimOp validator + grep other `Add*Op` validators for similar |
| V3 | `source_refs` is on Assumption, Risk, Catalyst, Valuation, BusinessOverview, IndustryLandscape, MacroOverlayDriver, StructuralTrend, GaapNonGaapBridge, HistoricalCoincidence, MaterialityThreshold, Peer, Ownership, Monitoring, QualitativeFactor | `thesis_shared_slice.py` | `grep -n "source_refs" AI-excel-addin/schema/thesis_shared_slice.py` |
| V4 | `iter_source_refs` walks the full payload validating `src_N` resolution | `api/research/handoff.py:238` | Read function + grep for callers |
| V5 | Source identity-hash dedup across snapshots in v1.1+ | `api/research/handoff.py:138` | Read `_SourceRegistry` |
| V6 | `decisions_log` auto-appended on every patch batch | `patch_engine.py` (asserted) | `grep -n "decisions_log\|append.*log" AI-excel-addin/api/research/patch_engine.py` |
| V7 | `monitoring.watch_list` schema-free per ADR | `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md:355-357` | Read the cited ADR section directly |
| V8 | `critical-factors` Step 9 emits `add_historical_coincidence` | `critical-factors.md:299` | Read the skill at the cited line |
| V9 | `position-initiation` chains to `execute_trade` | Skill chain | Read `position-initiation.md` execute step |
| V10 | HandoffArtifact `_assemble_artifact` re-derives shared slice from Thesis verbatim on finalize | `api/research/handoff.py:449` | Read `_assemble_artifact_locked` |
| V11 | `register_sources` rewrites `source_refs` recursively via `_rewrite_source_refs_recursive` | `patch_engine.py:763` | Read the function |
| V12 | HandoffArtifact v1.1 (`schema_version: "1.1"`) or v1.2 — which is current production? | `schema/handoff.py:155` `schema_version: Literal["1.1", "1.2"] = "1.2"` | Confirm — v1.2 may already be live |

Tracked by F135.

---

## Related

- [`THESIS_WRITE_SURFACE_COVERAGE.md`](THESIS_WRITE_SURFACE_COVERAGE.md) — Skill × Thesis section producer matrix. Concrete inventory of who writes what at Layer 2.
- Memory: [[project_thesis_design_for_autonomous_fund]] — Thesis designed for full autonomous loop (research → model → position → monitor → exit). Locked 2026-05-20.
- Schema source: `AI-excel-addin/schema/thesis.py:263` (Thesis root), `thesis_shared_slice.py:508` (IndustryAnalysis), `handoff.py` (HandoffArtifact), `handoff_patch.py` (patch op registry).
- Plan docs: `HANDOFF_ARTIFACT_V1_1_PLAN.md`, `BUILD_MODEL_FOR_HANDOFF_MCP_PLAN.md`, `MODEL_BUILD_CONTEXT_PLAN.md`, `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md`.
- Code: `api/research/patch_engine.py` (write engine), `api/research/handoff.py` (HandoffService, _SourceRegistry, shared_slice_write_lock), `api/research/build_model_orchestrator.py` (Layer 3 → build).
