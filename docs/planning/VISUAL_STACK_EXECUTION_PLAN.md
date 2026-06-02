# Visual Stack — Execution Sequence Plan

**Status:** Living tracking doc.
**Created:** 2026-05-26.
**Purpose:** Cross-workstream dependency map + wave-based sequencing for all in-flight visualization work — F147 (thesis registry, Pattern 1), F122 (HTML renderer, Pattern 2A), the `/analyst` agent-control artifact render bridge, agent-render-protocol roadmap Blocks A-E, F148 Presentation Packs, F149 Tufte-viz validation. Update as items ship.

**Authority layering (for context):**
- `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` — principles
- `docs/reference/VISUALIZATION_STACK.md` — implementation reference + plan inventory
- `docs/planning/SKILL_ARTIFACT_VISUAL_MATRIX.md` — F150 audit (closed)

---

## 1. Dependency map

```
                              VISUAL STACK
                                   │
   ┌───────────────────────────────┼───────────────────────────────┐
   │                               │                               │
PATTERN 1                     PATTERN 2A                      PATTERN 2B
Curated React                 Agent HTML                      Excalidraw
(Recharts + shadcn)           (one-off HTML)                  (diagrams)
   │                               │                               │
   F147                            F122 + addendum                 ❌ KILLED
                                                                   2026-05-23


   ┌─────────────────────────────────────────────────────────────────────┐
   │ PATTERN 1 — F147 thesis registry                                     │
   │                                                                      │
   │ F147 spec ✅ ──── PR-0 plan ✅ ─┐                                   │
   │                                  ├→ PR-2 plan ⬜ → PR-2 impl ⬜      │
   │                  PR-1 plan ✅ ─┘                  │                 │
   │                                                    ↓                 │
   │                            PR-3-13 plans ⬜ → impls ⬜               │
   └─────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────┐
   │ PATTERN 2A — F122 HTML renderer                                      │
   │                                                                      │
   │ demo-surface ✅ ──── HTML addendum spec ✅ ──→ addendum impl plan ✅  │
   │                                                       ↓              │
   │                                              addendum impl ⬜        │
   │                                                       │ (live-test   │
   │                                                       │  gate only)  │
   │ F122 spec ✅ ──── F122 impl plan ✅ ──→ F122 PR-1–PR-6 impl ⬜        │
   │                                         (mocked upstream, parallel)  │
   │                                                       │              │
   │                                                       ↓              │
   │                                              F122 live E2E ⬜        │
   │                                              (gates on both above)   │
   └─────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────┐
   │ /ANALYST AGENT-CONTROL ARTIFACT RENDER BRIDGE                       │
   │                                                                      │
   │ Agent-control surface spec ✅ ──→ bridge plan ◆                      │
   │                                     │                                │
   │                                     ├→ fallback/ref scaffold ◆       │
   │                                     ├→ F122 HtmlArtifact branch ⬜    │
   │                                     └→ F147 curated-registry branch ⬜│
   │                                                                      │
   │ Bridges ControlArtifact refs → ArtifactPanelConnected human renders  │
   └─────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────┐
   │ CROSS-CUTTING — agent-render-protocol roadmap                        │
   │                                                                      │
   │ Block A streaming impl plan ✅ ──→ Block A impl ⏸ PARKED             │
   │     (waiting on progressively-chunking skill)                        │
   │                                                                      │
   │ Block C approvals typed events ✅ SHIPPED                            │
   │     (request/decided lifecycle + replay/recap integration)           │
   │                                                                      │
   │ Block B fanout substrate ✅ SHIPPED                                  │
   │     (schema_version envelope + /chat/subscribe replay)               │
   │                                                                      │
   │ Block D session_recap ✅ SHIPPED                                     │
   │                  feeds F148 inventory; F148 owns composition ───────│
   │                                                                      │
   │ Block E spec ✅ ──→ impl plan ✅ ──→ impl ⬜                          │
   │                  (adapter/negotiation layer remains open)            │
   └─────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────┐
   │ LAYER 3 + DISCIPLINE                                                 │
   │                                                                      │
   │ F148 Presentation Packs ⬜ ←── Block D inventory available; plan next │
   │                         (F148 owns ArtifactComposition)              │
   │ F149 Tufte-viz validation ✅ DONE 2026-05-26                         │
   └─────────────────────────────────────────────────────────────────────┘
```

**Legend:** ✅ = shipped or Codex PASS · ◆ = in flight · ⬜ = not started · → = blocks · ←── = upstream input/dependency

---

## 2. What's runnable RIGHT NOW (parallel batch)

Current unblocked implementation dispatch after the 2026-06-02 reconciliation. Blocks B/C/D are no longer queued implementation work; they are live substrate in AI-excel-addin. Capacity-limited batch — realistic concurrency is ~3-4; see §5.

| # | Item | Type | Plan path | Why now |
|---|---|---|---|---|
| 1 | **F147 PR-1 impl** | Codex impl dispatch | `docs/planning/F147_PR1_IMPL_PLAN.md` §6 | Plan PASS R5; smallest F147 foundation scope; reconcile any local scaffold before duplicate dispatch |
| 2 | **F147 PR-0 impl** | Codex impl dispatch | `docs/planning/F147_PR0_IMPL_PLAN.md` §6 | Plan PASS R7; data substrate; parallel to PR-1 |
| 3 | **HTML addendum impl** | Codex impl dispatch | `../AI-excel-addin/docs/design/html-artifact-addendum-impl-plan.md` | Gateway-side impl plan PASS R7; unblocks F122 live-test once deployed (F122 PR-1–PR-6 can run in parallel with mocked upstream) |
| 4 | **F122 PR-1–PR-6 impl** | Codex impl dispatch | `docs/planning/F122_HTML_ARTIFACT_RENDERER_IMPL_PLAN.md` | Plan PASS R3; can proceed against mocked sidecar + HTML fixtures while gateway addendum is built |
| 5 | **Block E protocol versioning impl** | Codex impl dispatch | `../AI-excel-addin/docs/design/protocol-versioning-impl-plan.md` | Impl plan PASS R3; Block B envelope + subscribe prerequisite is now present |
| 6 | **F148 Presentation Packs plan** | Plan authoring | `docs/planning/PRESENTATION_PACKS_PLAN.md` | Block D recap inventory is available; design the F148-owned `ArtifactComposition`/pack layer before implementation |

---

## 3. Wave-based sequencing (recommended)

Realistic concurrency: ~3-4 in-flight Codex tasks before context-switching dominates.

### Wave 1 — Start NOW (fully parallel)

| Item | Status | Notes |
|---|---|---|
| F147 PR-1 impl | ⬜ NEXT | Validates Codex impl flow on smallest scope; reconcile any local scaffold before duplicate dispatch |
| F147 PR-0 impl | ⬜ NEXT | Bigger scope; parallel to PR-1 |
| HTML addendum impl | ⬜ NEXT | Impl plan PASS R7 2026-06-01: `AI-excel-addin/docs/design/html-artifact-addendum-impl-plan.md`; unblocks F122 live E2E once deployed |
| F122 PR-1–PR-6 impl | ⬜ NEXT | Can start with mocked upstream; PR-1–PR-5 are feature work and PR-6 closes mocked integration/anti-pattern tests |

### Wave 2 — Start as Wave 1 capacity frees

| Item | Status | Notes |
|---|---|---|
| Block E protocol versioning impl | ⬜ NEXT | Impl plan PASS R3; Block B envelope + subscribe substrate is present |
| F148 Presentation Packs plan | ⬜ NEXT | Block D recap inventory is live; write `docs/planning/PRESENTATION_PACKS_PLAN.md` around the F148-owned composition layer |
| Agent-control artifact render bridge review | ◆ DRAFT / PARTIAL WORKTREE | `docs/planning/AGENT_CONTROL_ARTIFACT_RENDER_BRIDGE_PLAN.md`; current worktree already contains fallback/ref scaffold pieces, so reconcile existing implementation before dispatching more bridge work |
| Agent-control artifact render bridge fallback scaffold | ◆ PARTIAL WORKTREE | Existing dirty worktree has `ArtifactRenderRef`/resolver/panel wiring started; next action is review/reconciliation, not duplicate scaffolding |

### Wave 3 — After F147 PR-0 + PR-1 land

| Item | Status | Notes |
|---|---|---|
| F147 PR-2 plan author | ⬜ | First plan against actually-shipped types |
| F147 PR-2 Codex review | ⬜ | Should converge faster than PR-0/PR-1 (smaller scope, real types) |

### Wave 4 — After F147 PR-2 ships

| Item | Status | Notes |
|---|---|---|
| F147 PR-3 plan + impl | ⬜ | Differential off PR-2 — fast cycle |
| F147 PR-4 plan + impl | ⬜ | Differential |
| F147 PR-5 plan + impl | ⬜ | Differential |
| F147 PR-6 plan + impl | ⬜ | Differential |
| F147 PR-8a/b plans + impls | ⬜ | Tier 2 batch |
| F147 PR-9a/b plans + impls | ⬜ | Tier 2 batch |
| F147 PR-10 plan + impl | ⬜ | Tier 2 batch 3 |
| F147 PR-11 plan + impl | ⬜ | Aggregate (consultation_summary) |
| F147 PR-12 plan + impl | ⬜ | Aggregate (review_card) |
| F147 PR-13 plan + impl | ⬜ | Aggregate (position_card_full) — most complex |

### F122 post-merge gate — independent of F147 wave cadence

| Item | Gate | Notes |
|---|---|---|
| F122 live E2E | F122 PR-1–PR-6 merged AND HTML addendum deployed | Post-merge checklist only; no F147 dependency |

### Lower-priority / deferrable

| Item | Status | Why deferred |
|---|---|---|
| Block A streaming `artifact_updated` | ⬜ PARKED | Parked in AI-excel-addin TODO #36 — waiting on a progressively-chunking skill; do NOT dispatch until that prerequisite exists |
| F148 Presentation Packs impl | ⬜ | Implementation waits on `docs/planning/PRESENTATION_PACKS_PLAN.md`; Block D recap inventory is live and ownership is locked: F148 defines `ArtifactComposition` derived from `session_recap` inventory |
| F147 PR-1b (overview migration to BuilderResult) | ⬜ | Cleanup; after F147 v1 ships |
| Excalidraw (Pattern 2B) | ❌ KILLED | Re-trigger only if irreducibly-graph artifact gets scoped |

Note on F147 PR numbering: PR-7 is a placeholder in the F147 umbrella plan that is intentionally unused — PRs jump from PR-6 to PR-8a/b. No item is missing.

---

## 4. Per-workstream critical paths

### F147 critical path (this session's work)

```
PR-0 + PR-1 impl (parallel)
  ↓
verify both merge cleanly
  ↓
PR-2 plan author → review → impl (template)
  ↓
PR-3 through PR-13 differential plans + impls (12 PRs)
  ↓
Visual coverage: ~14% → ~41%
```

**Estimated duration:** PR-0/PR-1 impl = 2-3 sessions. PR-2 plan + impl = 1-2 sessions. PR-3-13 = 6-10 sessions depending on Codex review iteration rate (probably 1-2 rounds each since template is proven).

### F122 critical path (HTML renderer)

```
HTML addendum impl (gateway side, ai-excel-addin)
  │
  ├── parallel with ──→ F122 PR-1–PR-6 impl (mocked upstream)
  │
  ↓
F122 live E2E (post-merge checklist — addendum deployed + F122 PRs merged)
  ↓
Pattern 2A capability fully live
```

Note: F122 impl plan PASS R3 states that PR-1–PR-5 feature work can proceed with mocked upstream responses; PR-6 closes mocked integration and anti-pattern tests. Live E2E is a post-merge checklist item only. Do not hold F122 impl start behind the addendum — only hold live-test.

**Estimated duration:** HTML addendum impl = 1-2 sessions. F122 impl (6 PRs) = 2-4 sessions. Live E2E after addendum deploys. Total ~4-6 sessions.

### Cross-cutting roadmap

```
Block B fanout substrate + Block C typed approvals + Block D session_recap
  ↓
Block E protocol-versioning impl (adapter / session negotiation / downgrade tests)
  ↓
F148 plan/impl against F148-owned `ArtifactComposition` derived from `session_recap`
```

---

## 5. Realistic concurrency planning

If managing ~3-4 in-flight Codex tasks simultaneously:

**Track 1 (impl):** F147 PR-1 + PR-0 (parallel) → PR-2 → PR-3-13 (long-running)
**Track 2 (impl):** HTML addendum impl and F122 PR-1–PR-6 impl with mocked upstream run in parallel → F122 live E2E (after addendum deployed + F122 PRs merged)
**Track 3 (impl):** Block E protocol-versioning implementation against the live Block B envelope/subscribe substrate
**Track 4 (plan):** F148 Presentation Packs plan → F148 implementation once `ArtifactComposition`/pack templates are designed

Block A is parked — do not put it on any track until a progressively-chunking skill exists.

Tracks 1-4 can run roughly in parallel, with F148 implementation sequenced after its plan rather than after Block D.

---

## 6. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-23 | Pattern 2B Excalidraw killed | Equity research not diagram-heavy; no current/planned artifact needs node-and-arrow diagrams |
| 2026-05-25 | F147 mega-impl-plan abandoned → per-PR plans | Dense single doc spiraled on text consistency (4 rounds, still FAIL); per-PR docs converge faster (PR-1 = 5 rounds, PR-0 = 7 rounds) |
| 2026-05-25 | F147 reframe — 15 cards pure Thesis read, 3 cards sidecar | Only 4 skills have `typed_outputs_contract`; non-contract skills don't emit `artifact_ready`. Triple invalidation (stream-complete + apply_patch_ops + opportunistic artifact_ready) covers all skill writes. |
| 2026-05-25 | F147 v1 scope locked at 18 entries, ~41% visual coverage | Audit-driven (F150 matrix); advisor/plan/review namespaces in v1.1 |
| 2026-05-26 | F147 PR-0 + PR-1 plans PASS-locked; impl path next | 23 review rounds across spec + 2 impl plans; per-PR restructure validated |
| 2026-05-31 | Block A downgraded from "impl-ready" to PARKED | AI-excel-addin TODO #36 explicitly parks Block A until a progressively-chunking skill exists; prior snapshot incorrectly listed it as ready for dispatch |
| 2026-05-31 | Block B, D, E status corrections from prior snapshot | Block B impl plan PASS R3 (2026-05-23); Block D spec PASS R5 + impl plan PASS R9 (2026-05-23); Block E spec PASS R3 (2026-05-23) — the prior snapshot missed the passed design docs and incorrectly left these as underspecified |
| 2026-05-31 | F149 Tufte-viz completed | `docs/planning/completed/F149_TUFTE_VIZ_VALIDATION.md` exists; validated as design-time companion, not CI gate |
| 2026-05-31 | F122 impl plan Codex PASS R3 | All 6 PRs reviewed; PR-1–PR-5 feature work confirmed runnable with mocked upstream; PR-6 closes mocked integration/anti-pattern tests; live E2E is post-merge checklist only |
| 2026-06-01 | HTML addendum impl plan Codex PASS R7 | `AI-excel-addin/docs/design/html-artifact-addendum-impl-plan.md`; gateway-side F122 prerequisite now ready for impl dispatch |
| 2026-06-01 | Visualization-stack doc reconciliation | Corrected stale HTML-foundation wording, F122 PR count, F163 review status, agent-control bridge partial-worktree state, and the F148/Block D composition assumption. |
| 2026-06-01 | F148 composition ownership locked | F148 owns `ArtifactComposition` as Pack-layer state derived from Block D `session_recap` inventory. Block D remains factual runtime recap and should not be amended with section/narrative/layout metadata for v1. |
| 2026-06-02 | Group 4 implementation-status reconciliation | AI-excel-addin Blocks B/C/D are no longer runnable implementation work: Block B fanout substrate, Block C typed approvals, and Block D `session_recap` inventory are present. Block E is the remaining protocol-versioning implementation; F148 is unblocked for plan writing but still owns Pack composition design. |

---

## 7. Status snapshot (as of 2026-06-02)

**PASS-ready for impl dispatch (unblocked):**
- F147 PR-1 plan (PASS R5)
- F147 PR-0 plan (PASS R7)
- HTML addendum impl (impl plan PASS R7, 2026-06-01) — `AI-excel-addin/docs/design/html-artifact-addendum-impl-plan.md`; unblocks addendum impl dispatch
- F122 PR-1–PR-6 impl (impl plan PASS R3, 2026-05-31) — can proceed with mocked upstream; live E2E gates on addendum deploy
- Block E protocol-versioning impl (impl plan PASS R3) — Block B envelope + subscribe substrate is present

**Plan-writing now unblocked:**
- F148 Presentation Packs — write `docs/planning/PRESENTATION_PACKS_PLAN.md` around F148-owned `ArtifactComposition`, `PresentationPack` templates, session-to-pack transformation, persistence/addressability, and export adapters
- F147 PR-2 through PR-13 plans (after PR-0/PR-1 land)

**Draft bridge plans needing review:**
- Agent-control artifact render bridge — `docs/planning/AGENT_CONTROL_ARTIFACT_RENDER_BRIDGE_PLAN.md`; defines the resolver/ref layer between `/control/artifacts` and `ArtifactPanelConnected`. Current worktree already contains partial fallback/ref scaffold wiring, so the next step is review/reconciliation before any additional bridge dispatch. F122/F147 branches wait on their shared infra/registry substrate.

**Parked (do not dispatch):**
- Block A streaming `artifact_updated` — AI-excel-addin TODO #36 explicitly parks until a progressively-chunking skill exists

**Blocked on upstream impl (not spec):**
- F122 live E2E — blocked until both F122 PR-1–PR-6 merge and the AI-excel-addin HTML addendum deploys
- Pattern 2A full live capability — blocked on HTML addendum + F122 + F163 prerequisites

**Completed:**
- Block B fanout substrate — `schema_version: 1` stream envelopes, `/chat/subscribe` replay, taskpane reconnect, and transcript retention are present
- Block C approvals typed events — request/decided lifecycle, taskpane ingestion, control-plane replay, and recap aggregation are live
- Block D `session_recap` inventory — terminal/explicit/GC recap paths and recap aggregation are present; F148 owns composition
- F149 Tufte-viz validation — DONE 2026-05-26 (`docs/planning/completed/F149_TUFTE_VIZ_VALIDATION.md`)
- HTML addendum impl plan — PASS R7 2026-06-01
- F122 impl plan Codex review — PASS R3 2026-05-31

**Deferred:**
- F147 PR-1b (overview migration cleanup; after F147 v1 ships)

---

## 8. References

- F147 spec: `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md` (R7 PASS)
- F147 umbrella: `docs/planning/F147_IMPL_PLAN.md`
- F147 PR-0 plan: `docs/planning/F147_PR0_IMPL_PLAN.md` (R7 PASS)
- F147 PR-1 plan: `docs/planning/F147_PR1_IMPL_PLAN.md` (R5 PASS)
- F147 audit: `docs/planning/SKILL_ARTIFACT_VISUAL_MATRIX.md`
- Visualization stack ref: `docs/reference/VISUALIZATION_STACK.md`
- Visual principles: `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md`
- F122 spec: `docs/planning/F122_HTML_ARTIFACT_RENDERER_SPEC.md` (R7 PASS)
- F122 impl plan: `docs/planning/F122_HTML_ARTIFACT_RENDERER_IMPL_PLAN.md` (R3 PASS)
- F149 validation: `docs/planning/completed/F149_TUFTE_VIZ_VALIDATION.md` (DONE 2026-05-26)
- Cross-repo (AI-excel-addin) — paths relative to `../AI-excel-addin/`:
  - `docs/design/demo-surface-html-artifact-addendum.md` (R6 PASS) + `docs/design/html-artifact-addendum-impl-plan.md` (R7 PASS — addendum impl ready for dispatch)
  - `docs/design/agent-render-protocol-roadmap.md` (R2 PASS)
  - `docs/design/streaming-artifact-updates-impl-plan.md` (R5 PASS — PARKED)
  - `docs/design/approvals-as-typed-events-impl-plan.md` (R5 PASS — Block C, shipped)
  - `docs/design/multi-client-session-fanout-spec.md` (R4 PASS) + `multi-client-session-fanout-impl-plan.md` (R3 PASS — Block B substrate shipped)
  - `docs/design/session-recap-event-spec.md` (R5 PASS) + `session-recap-event-impl-plan.md` (R9 PASS — Block D shipped)
  - `docs/design/protocol-versioning-spec.md` (R3 PASS) + `docs/design/protocol-versioning-impl-plan.md` (R3 PASS — Block E ready for implementation)
- Current TODO: `docs/TODO.md` (see "Product, UX, And Editorial" section)
