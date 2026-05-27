# Visual Stack — Execution Sequence Plan

**Status:** Living tracking doc.
**Created:** 2026-05-26.
**Purpose:** Cross-workstream dependency map + wave-based sequencing for all in-flight visualization work — F147 (thesis registry, Pattern 1), F122 (HTML renderer, Pattern 2A), agent-render-protocol roadmap Blocks A-E, F148 Presentation Packs, F149 Tufte-viz validation. Update as items ship.

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
   │ demo-surface ✅ ──── HTML addendum spec ✅ ──→ addendum impl plan ⬜  │
   │                                                       │              │
   │                                                       ↓              │
   │                                              addendum impl ⬜        │
   │ F122 spec ✅ ──── F122 impl plan ◆ ───────────────────┤              │
   │                                                       ↓              │
   │                                              F122 impl ⬜            │
   │                                              (live-test gated on     │
   │                                               addendum impl)         │
   └─────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────┐
   │ CROSS-CUTTING — agent-render-protocol roadmap                        │
   │                                                                      │
   │ Block A streaming impl plan ✅ ──→ Block A impl ⬜                   │
   │     (F147 + F122 both consume)                                       │
   │                                                                      │
   │ Block C approvals impl plan ✅ ──→ Block C impl ⬜                   │
   │     (production hardening)                                           │
   │                                                                      │
   │ Block B fanout sketch ⬜ ──→ review → impl                           │
   │                                                                      │
   │ Block D session summary ⬜ ──→ spec → impl ──→ unblocks F148         │
   │                                                                      │
   │ Block E protocol versioning ⬜ (may fold into B)                     │
   └─────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────┐
   │ LAYER 3 + DISCIPLINE                                                 │
   │                                                                      │
   │ F148 Presentation Packs ⬜ ←── BLOCKED on Block D                    │
   │ F149 Tufte-viz validation ⬜ (independent, cheap)                    │
   └─────────────────────────────────────────────────────────────────────┘
```

**Legend:** ✅ = shipped or Codex PASS · ◆ = in flight · ⬜ = not started · → = blocks · ←── = blocked on

---

## 2. What's runnable RIGHT NOW (parallel batch)

Six items, no mutual blockers. Could dispatch in parallel.

| # | Item | Type | Plan path | Why now |
|---|---|---|---|---|
| 1 | **F147 PR-1 impl** | Codex impl dispatch | `docs/planning/F147_PR1_IMPL_PLAN.md` §6 | Plan PASS R5; smallest scope; validates impl flow |
| 2 | **F147 PR-0 impl** | Codex impl dispatch | `docs/planning/F147_PR0_IMPL_PLAN.md` §6 | Plan PASS R7; substrate; parallel to PR-1 |
| 3 | **Block A streaming impl** | Codex impl dispatch | `AI-excel-addin/docs/design/streaming-artifact-updates-impl-plan.md` | Impl plan PASS R5; F147 + F122 both consume |
| 4 | **Block C approvals impl** | Codex impl dispatch | `AI-excel-addin/docs/design/approvals-as-typed-events-impl-plan.md` | Impl plan PASS R5; hardens approval surface |
| 5 | **HTML addendum impl plan author** | Plan-writing | `AI-excel-addin/docs/design/demo-surface-html-artifact-addendum.md` (spec PASS R6) | Gateway-side; unblocks F122 live-test |
| 6 | **F149 Tufte-viz trial** | Validation pass | `https://gist.github.com/aparente/...` (skill gist) | Cheap; informs visual decisions |

---

## 3. Wave-based sequencing (recommended)

Realistic concurrency: ~3-4 in-flight Codex tasks before context-switching dominates.

### Wave 1 — Start NOW (fully parallel)

| Item | Status | Notes |
|---|---|---|
| F147 PR-1 impl | ⬜ NEXT | Validates Codex impl flow on smallest scope |
| Block C approvals impl | ⬜ NEXT | Independent; hardens existing surface |
| HTML addendum impl plan author | ⬜ NEXT | Plan-writing track; doesn't compete with impl |

### Wave 2 — Start as Wave 1 capacity frees

| Item | Status | Notes |
|---|---|---|
| F147 PR-0 impl | ⬜ | Bigger scope; kick off after PR-1 validates flow |
| Block A streaming impl | ⬜ | Moderate-size; unlocks in-flight artifact growth UX |
| F149 Tufte-viz trial | ⬜ | Independent; interleave with anything |

### Wave 3 — After F147 PR-0 + PR-1 land

| Item | Status | Notes |
|---|---|---|
| F147 PR-2 plan author | ⬜ | First plan against actually-shipped types |
| F147 PR-2 Codex review | ⬜ | Should converge faster than PR-0/PR-1 (smaller scope, real types) |
| HTML addendum impl | ⬜ | Once addendum impl plan PASS |

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
| F122 impl | ⬜ | After HTML addendum impl ships |

### Lower-priority / deferrable

| Item | Status | Why deferred |
|---|---|---|
| Block B fanout review + impl | ⬜ | Needs multi-frontend pressure to justify |
| Block D session summary spec | ⬜ | Unblocks F148; not urgent unless F148 prioritized |
| F148 Presentation Packs plan + impl | ⬜ | Blocked on Block D |
| Block E protocol versioning | ⬜ | May fold into Block B |
| F147 PR-1b (overview migration to BuilderResult) | ⬜ | Cleanup; after F147 v1 ships |
| Excalidraw (Pattern 2B) | ❌ KILLED | Re-trigger only if irreducibly-graph artifact gets scoped |

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
HTML addendum impl plan author
  ↓
Codex review until PASS
  ↓
Addendum impl (gateway side, ai-excel-addin)
  ↓
F122 impl plan finish review (currently in draft)
  ↓
F122 impl (risk_module side) — live-tests after addendum live
  ↓
Pattern 2A capability shipped
```

**Estimated duration:** Each step 1-2 sessions. Total ~6-8 sessions.

### Cross-cutting roadmap

```
Block A impl + Block C impl in parallel (independent)
  ↓
Block B sketch → review → impl
Block D spec → review → impl → unblocks F148
```

---

## 5. Realistic concurrency planning

If managing ~3-4 in-flight Codex tasks simultaneously:

**Track 1 (impl):** F147 PR-1 → PR-0 → PR-2 → PR-3-13 (long-running)
**Track 2 (impl):** Block C → Block A (independent cross-cutting)
**Track 3 (plan):** HTML addendum impl plan → F122 impl plan → F122 impl
**Track 4 (trial):** F149 Tufte-viz validation (one-off; interleave when capacity)

Tracks 1-3 run roughly in parallel. Track 4 interleaves whenever there's a gap.

---

## 6. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-23 | Pattern 2B Excalidraw killed | Equity research not diagram-heavy; no current/planned artifact needs node-and-arrow diagrams |
| 2026-05-25 | F147 mega-impl-plan abandoned → per-PR plans | Dense single doc spiraled on text consistency (4 rounds, still FAIL); per-PR docs converge faster (PR-1 = 5 rounds, PR-0 = 7 rounds) |
| 2026-05-25 | F147 reframe — 15 cards pure Thesis read, 3 cards sidecar | Only 4 skills have `typed_outputs_contract`; non-contract skills don't emit `artifact_ready`. Triple invalidation (stream-complete + apply_patch_ops + opportunistic artifact_ready) covers all skill writes. |
| 2026-05-25 | F147 v1 scope locked at 18 entries, ~41% visual coverage | Audit-driven (F150 matrix); advisor/plan/review namespaces in v1.1 |
| 2026-05-26 | F147 PR-0 + PR-1 plans PASS-locked; impl path next | 23 review rounds across spec + 2 impl plans; per-PR restructure validated |

---

## 7. Status snapshot (as of 2026-05-26)

**PASS-ready for impl dispatch:**
- F147 PR-1 plan
- F147 PR-0 plan
- Block A streaming impl plan
- Block C approvals impl plan

**In-flight planning:**
- F122 impl plan (draft, round 2)

**Needs plan-writing:**
- HTML addendum impl plan (gateway side)
- F147 PR-2 through PR-13 plans (after PR-0/PR-1 land)
- Block B fanout (sketch needs review)
- Block D session summary (not specced)

**Deferred:**
- F148 Presentation Packs (blocked on Block D)
- F149 Tufte-viz validation (cheap, can interleave)
- F147 PR-1b (overview migration cleanup; after v1)

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
- Cross-repo (AI-excel-addin):
  - `docs/design/demo-surface-html-artifact-addendum.md` (R6 PASS)
  - `docs/design/agent-render-protocol-roadmap.md` (R2 PASS)
  - `docs/design/streaming-artifact-updates-impl-plan.md` (R5 PASS)
  - `docs/design/approvals-as-typed-events-impl-plan.md` (R5 PASS)
- Current TODO: `docs/TODO.md` (see "Product, UX, And Editorial" section)
