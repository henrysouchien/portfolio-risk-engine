# Plan #10 — Research Editorial Pipeline v1 (Investment Schema Unification)

**Status**: SHIPPED 2026-04-28
**Created**: 2026-04-27
**Last revised**: 2026-04-28 (R4-SHIPPED — final docs + ship marker; prior R3 addressed Codex R2 FAIL: 4 High, 3 Medium, plus useful Low/Ask responses.)

**SHIPPED 2026-04-28 summary**:
- All 9 sub-phases A-I are committed.
- Cross-repo commits: AI-excel-addin A/B/C/D/E/H (`f7a33ca`, `02bf99c`, `756579c`, `4a71d74`, `c627529`, `79d7245`); risk_module F/G (`e07580e9`, `11403b46`); plan-doc commit `888eefe2`.
- Test surface shipped: 89 editorial-suite tests + 91 full editorial+adjacent + 6 eval-scenario snapshot tests, plus 11 frontend tests.
- Codex iteration arc: R1 FAIL → R2 FAIL → R3 PASS.

**Authoritative design reference**: `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §5 G10, §9 (Editorial vs Structural), §12 row 10. This plan does **not** add a new typed contract group to the master plan; the editorial brief is a render-layer envelope, not a schema.

**Closes**: **G10** (master plan §5) — *"Editorial layer for research report. F25 `HandoffSectionRenderer` does structural rendering. The `core/overview_editorial/` pipeline is a proven pattern for portfolio overview briefs; it hasn't been cloned for research."*

**Depends on**:
- Plan #2 `HANDOFF_ARTIFACT_V1_1_PLAN.md` — `HandoffArtifactV1_1` (Pydantic at `AI-excel-addin/schema/handoff.py:116`). **SHIPPED** per Codex R1 verification (commits `f69aa72`, `203ad57`, `5e47452`, `03a43ac`).
- Plan #1 `THESIS_LIVING_ARTIFACT_PLAN.md` — `Thesis` (Pydantic at `AI-excel-addin/schema/thesis.py:222`). **SHIPPED** per Codex R1 verification (commit `5370a50` "feat(thesis): sub-phase A...").
- Plan #5 `PROCESS_TEMPLATE_PLAN.md` — `ProcessTemplate` at `AI-excel-addin/schema/process_template.py:115`; uses `ProcessTemplate.investor_profile.strategy_bias` + `ProcessTemplate.section_config.required` (R2 fix — R1 cited the non-existent `required_sections`). **SHIPPED 2026-04-23** (master plan §12 row 5).

**Companion docs**:
- `docs/planning/OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md` — clone-pattern reference. Approved 2026-04-02.
- `docs/planning/completed/OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md` — implementation reference (B1–B6 sub-phases shipped).
- `docs/planning/EDITORIAL_PIPELINE_AUDIT.md` — gap analysis on overview pipeline. **Read first**: explains why we clone the *Phase 1 patterns* (proven), not the *Phase 2 personalization-depth work* (still settling).
- `core/overview_editorial/` (risk_module) — the pattern to mirror. ~13 modules + 10 generators + 20 test files / ~4,200 LOC.
- `AI-excel-addin/api/research/handoff.py:HandoffService.finalize_handoff()` — the natural trigger point.
- `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx` — the precedent for a workspace UI render component reading typed handoff sections.

---

## 1. Purpose & scope

Plan #10 builds the **research editorial pipeline** — the render-layer that takes a finalized `HandoffArtifactV1_1` and produces a typed `ResearchBrief` envelope for the workspace UI. Today the workspace renders handoff *sections* polymorphically via `HandoffSectionRenderer`, but it does **not** produce an editorially curated brief. That gap (G10) is what the master plan §9 anticipated when it said *"a future research-editorial pipeline for PDF/export"*.

Three deliverables in v1:

1. **`ResearchBrief v1.0`** — Pydantic source-of-truth envelope. Contains `headline`, three structured slot groups (`differentiated_view_slot`, `path_slot`, `valuation_slot`), `editorial_metadata`. Lives at `AI-excel-addin/schema/research_brief.py`.
2. **3-generator pipeline** — `ThesisDifferentiationGenerator`, `CatalystRiskGenerator`, `ValuationConvictionGenerator`. Each reads the typed `ResearchContext` (HandoffArtifact + ProcessTemplate; analyst intent comes from the embedded `handoff.thesis: ThesisField` snapshot — no separate Thesis fetch in v1) and emits scored `ResearchInsightCandidate`s. Editorial policy layer composes the brief from candidates.
3. **Async post-finalize hook + workspace UI section** — finalize emits the artifact synchronously (existing behavior preserved); pipeline runs as a background task; brief surfaces in the workspace UI under a new "Research Brief" section, with `pending` / `ready` / `failed` status states for polling.

### 1.1 Non-goals (v1)

- **No PDF, markdown, or email export.** v1 ships the typed envelope and one consumer (workspace UI section). Markdown/PDF/email are downstream renders of the same envelope and are **explicitly Phase 2**, not "build if needed." See §11 for the Phase 2 sequence.
- **No editorial_memory / personalization profile coupling.** Lane C's `editorial_memory_seed.json` migration (canonical-vocab + memory-seeder) is actively in flight. Research personalization in v1 derives entirely from `Thesis` (analyst intent), `ProcessTemplate.investor_profile` (process-level prefs), and `HandoffArtifact` (the data). Phase 2 hooks editorial_memory once Lane C settles.
- **No LLM arbiter (deterministic-only v1).** Overview Phase 1 shipped with the LLM arbiter; the audit (`EDITORIAL_PIPELINE_AUDIT.md`) showed delivery-gap problems (arbiter writes to in-memory cache, frontend doesn't see enhanced version unless reloaded). v1 ships a clean deterministic pipeline. LLM enhancement is Phase 2 once the delivery mechanism is settled (see §11).
- **No qualitative-factor rollup, no thesis-coherence cross-check, no industry-context generator.** Phase 2. Industry context specifically belongs to Plan #7 `INDUSTRY_RESEARCH_TOOLS_PLAN.md` — keeping it separate avoids two plans fighting over the same surface.
- **No regenerate button.** Finalize-a-new-version is the regenerate path. A button is workflow-redundant in v1.
- **No websocket / push delivery.** Frontend polls `GET /handoffs/{handoff_id}/brief` with backoff. Websocket is Phase 2.
- **No on-demand pre-finalize brief.** Brief is **of** a finalized handoff. Drafts don't get briefs.
- **No content authoring of "voice" or "tone" templates beyond what generators emit.** Generators emit structured fields with literal phrasing. Voice-rewrite is the LLM arbiter's job, deferred to Phase 2.
- **No frontend export affordance** (PDF download button, share link, etc.). Phase 2.

### 1.2 What this plan adds to the master design

Master plan `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §9 explicitly frames editorial as render-layer, **not a new schema contract group**. Plan #10 therefore does NOT add a §6.X to the master plan. Sub-phase I instead lands a `§12 row 10 SHIPPED` marker plus a small §9 footnote pointing to this plan as the implementation of the "future research-editorial pipeline" the master plan anticipated.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| **A** | `ResearchBrief` + `ResearchInsightCandidate` Pydantic contracts | `AI-excel-addin/schema/research_brief.py` (new) — `ResearchBrief`, `ResearchInsightCandidate`, `ResearchBriefStatus` enum, `ResearchEditorialMetadata`. Reuses `_FROZEN_CONTRACT` pattern from existing schema. Zero runtime deps. | ~0.5 day | — (verify Plan #2 SHIPPED) |
| B | `ResearchContext` builder + `artifact_from_row` lift | `AI-excel-addin/api/research/editorial/context.py` (new) — assembles typed `ResearchContext` from `HandoffArtifactV1_1` + `ProcessTemplate`. Lifts `_artifact_from_row` (today private at `handoff.py:522`) into `api/research/handoff_loader.py` as the typed loader entrypoint (Codex R2 confirmed `schema/handoff_loader.py` does NOT exist; the right home is API/research, not schema/). | ~0.5 day | A; Plans #1, #2, #5 SHIPPED |
| C | 3 generators + `ResearchInsightGenerator` Protocol | `AI-excel-addin/api/research/editorial/generators/` (new dir). `base.py` (Protocol + scoring helpers), `thesis_differentiation.py`, `catalyst_risk.py`, `valuation_conviction.py`. Each generator pure: `(ResearchContext) → list[ResearchInsightCandidate]`. | ~2 days | A, B |
| D | Policy layer + brief cache | `AI-excel-addin/api/research/editorial/policy.py` (compose brief from candidates; slot selection rules), `editorial/cache.py` (in-memory LRU keyed by `(user_id, handoff_id)`; eternal-while-row-stable). | ~1 day | A, C |
| E | Editorial service + async finalize-hook (route layer) | `AI-excel-addin/api/research/editorial/service.py` (orchestrates context → generators → policy → cache; emits `ResearchBrief` with status). Hook lives at the FastAPI route `routes.py:1430` via `BackgroundTasks` injection — `HandoffService` signature unchanged. New `GET /handoffs/{handoff_id}/brief` endpoint returns `ResearchBrief` with status. | ~1 day | A, B, C, D |
| F | risk_module MCP tool surface | New action + MCP tool `get_research_brief(handoff_id)` slotted into existing `actions/research.py`, `mcp_tools/research.py`, registered in `mcp_server.py`. Proxies via gateway client. Typed errors: `BriefNotReady`, `BriefFailed`, `BriefNotFound`. Agent-format wrapper. | ~0.5 day | E |
| G | Frontend UI section | `frontend/packages/ui/src/components/research/ResearchBriefSection.tsx` (new) + polling hook. Renders `headline`, the three slot groups, status states (`pending` skeleton, `ready` brief, `failed` retry-prompt). Wired into existing research workspace detail view. | ~1 day | A, E |
| H | Eval fixtures + golden scenarios | `AI-excel-addin/tests/research/editorial/fixtures/` — 3 golden handoffs covering distinct narrative shapes (high-conviction-differentiated, defensive-risk-focused, catalyst-driven). Snapshot tests on the deterministic brief output. | ~0.5 day | A–E |
| I | Docs — master plan §12 ship marker + plan #10 ship notes | Patch `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §12 row 10 `→ (SHIPPED)` + add §9 footnote pointing to this plan. Update `docs/TODO.md` V2.P9j (or equivalent) row from `R0 DRAFT` → `SHIPPED`. | ~0.25 day | A–H |

**Total estimate**: ~7.25 days.

### 2.1 Dependency graph

```
A (Pydantic contracts)
└── B (ResearchContext builder) ── C (3 generators) ── D (policy + cache)
                                                      └── E (service + finalize-hook + REST endpoint)
                                                          ├── F (risk_module MCP tool)
                                                          └── G (frontend UI section)

H (eval fixtures) — depends on A–E
I (docs)         — last, depends on A–H
```

Generators (C) can be implemented in parallel after B lands. F and G can be parallelized after E.

---

## 3. Cross-cutting concerns

### 3.1 Wire schema authority

`ResearchBrief` is owned by **AI-excel-addin** per master plan §3 ("Pydantic source of truth for all seven contract groups"). Although the brief is not one of the seven contract groups (it's a render envelope), the same authority rule applies: AI-excel-addin owns the wire shape; risk_module's MCP tool returns whatever AI-excel-addin's gateway endpoint returns; the frontend consumes the JSON via existing TypeScript shadow types or codegen (whichever the workspace UI already uses for handoff sections — sub-phase G follows the established convention, no new pattern).

### 3.2 Cache contract

**R3 fix**: Codex R2 caught a multi-user collision: `repository.py:3705` shows repos are per-user SQLite DBs, so `handoff_id=1` is non-unique across the cache. Cache key now `(user_id, handoff_id)`.

| Aspect | Decision |
|---|---|
| Cache key | `(user_id, handoff_id)` (R3 fix — R2's `handoff_id`-only key collided across users in per-user repo factory; see `repository.py:3705`). |
| Invalidation | Never. `(user_id, handoff_id)` tuples are immutable post-finalize; each `create_new_version` produces a new `handoff_id` so a new tuple → new cache entry. Old entries LRU-evicted. |
| TTL | None (eternal-while-row-stable). The brief is a deterministic function of the artifact + ProcessTemplate. |
| Cap | LRU with `RESEARCH_EDITORIAL_BRIEF_CACHE_SIZE` env (default 256 entries — process-global, NOT per-user). |
| Storage | In-memory only in v1. Persistent storage is Phase 2 if cache thrash becomes a real cost. |
| Failure cache | Failed briefs (status=`failed`) cached for 60s only, so retries fan out cleanly. |

### 3.3 Async finalize-hook contract

**R2 fix**: `HandoffService.finalize_handoff(research_file_id)` is sync, takes only `research_file_id`, and returns a serialized summary dict (live shape per `AI-excel-addin/api/research/handoff.py:496`). It is called from a sync FastAPI route at `routes.py:1430` (POST `/handoffs/finalize`). The pipeline therefore hooks at the **route layer** via FastAPI's `BackgroundTasks`, not inside the service. The service stays pure.

```
POST /handoffs/finalize  (route — modified)
  1. summary = handoff_service.finalize_handoff(research_file_id)  # unchanged
  2. if RESEARCH_EDITORIAL_BRIEF_ENABLED:
        background_tasks.add_task(editorial_service.compose_brief, user_id, summary["id"])
  3. return summary

editorial_service.compose_brief(user_id, handoff_id):
  1. key = (user_id, handoff_id); acquire idempotency lock on key
  2. cache[key] = ResearchBrief(status="pending")
  3. build ResearchContext (loads handoff via per-user repo.get_handoff(handoff_id))
  4. run generators (try/except per generator; partial-failure tolerated)
  5. policy.compose() → ResearchBrief(status="ready")
  6. cache[key] = brief
  on exception:
     cache[key] = ResearchBrief(status="failed", error_summary=...)
```

Frontend polls `GET /handoffs/{handoff_id}/brief` (auth-derived `user_id` from `Depends(get_trusted_user_id)` — frontend never sends user_id explicitly):
- 404 → handoff doesn't exist OR `status != "finalized"` (R3: drafts excluded; per Codex R2 ask response).
- `pending` → keep polling (backoff: 500ms, 1s, 2s, 4s, 8s; cap at 8s; max 60s total).
- `ready` → render brief.
- `failed` → show error state with "couldn't compose brief — retry?" affordance (Phase 2 wires retry to a new endpoint; v1 leaves it as a non-functional prompt to keep scope tight).

### 3.4 Failure-mode coverage

**R2 fix**: dropped the "Thesis missing for `(user_id, ticker, label)` → failed" row. The handoff already carries `thesis: ThesisField` as an embedded snapshot at `handoff.py:122` (default_factory=ThesisField, never null). The brief reads thesis intent off the handoff snapshot, not via a separate Thesis repo lookup. `ThesisField` fields (statement, conviction, timeframe) can individually be `None` — generators tolerate this gracefully (degrade signal, don't fail).

| Failure | Behavior |
|---|---|
| One generator throws | Brief still composes. Policy layer marks the missing slot `unavailable`; frontend hides that slot. `editorial_metadata.partial_failure: true`. |
| All 3 generators throw | Brief status = `failed`. `error_summary` lists each generator's exception type (no PII / no stack). |
| `handoff.thesis.statement is None` (or other ThesisField fields None) | Generators read what's present; missing fields → lower scores, not failure. `editorial_metadata.degraded: true` only when a generator emits zero candidates because every field it depends on was None. |
| HandoffArtifact missing required slot inputs (e.g., `differentiated_view == []`, `valuation is None`) | Affected generator no-ops; brief composes from remaining slots. `editorial_metadata.degraded: true`. |
| ProcessTemplate missing | Default ProcessTemplate used; `editorial_metadata.fallback_template: true`. |
| Race: two route requests finalize same research_file_id | Service-level `_handoff_lock` (handoff.py:500) already serializes finalize. Each successful finalize creates a distinct `handoff_id` — distinct cache entries, no collision. |
| Cache eviction during pending | If pending entry evicted before pipeline finishes, second-comer poll triggers re-compose. Acceptable: rare, deterministic. |
| Background task crashes process | Finalize already returned successfully. Next poll → service sees no cache entry → no idempotency lock held → re-enqueue. (See §3.5.) |

### 3.5 Re-enqueue on missing brief

Because the pipeline runs as a `BackgroundTasks` task (not a durable queue in v1), a process crash mid-compose leaves no cache entry. The endpoint handler `GET /handoffs/{handoff_id}/brief` therefore implements a **lazy re-enqueue**:

```
GET /handoffs/{handoff_id}/brief:
  1. user_id = Depends(get_trusted_user_id)
  2. key = (user_id, handoff_id); cache.get(key) → return if present
  3. row = per-user-repo.get_handoff(handoff_id)
     a. 404 if row is None
     b. 404 if row["status"] != "finalized"   # R3: drafts excluded
  4. enqueue compose_brief(user_id, handoff_id); return ResearchBrief(status="pending")
```

This means: the brief is *eventually-composed-on-read* if the post-finalize task never ran. v1 accepts the latency (one compose run on first read after a crash) in exchange for not requiring a durable queue. Phase 2 adds a durable queue if crash-recovery latency becomes a real complaint.

### 3.6 Testing strategy

| Layer | Coverage |
|---|---|
| Unit (per generator) | Fixture `ResearchContext` → expected `list[ResearchInsightCandidate]`. Includes empty-input cases (no `differentiated_view`, no `catalysts`, etc.). |
| Unit (policy) | Synthetic candidate sets → expected `ResearchBrief` slot composition. Tests slot-fill order, missing-slot handling, scoring tie-breaks. |
| Unit (cache) | Key correctness, LRU eviction, idempotency lock, failed-brief TTL. |
| Integration (service) | Full pipeline from `compose_brief(handoff_id)` against a real handoff fixture. |
| Integration (finalize-hook) | `finalize_handoff()` returns artifact + enqueues task; polling endpoint sees `pending` → `ready`. |
| MCP (sub-phase F) | `get_research_brief` tool returns typed errors for each failure mode in §3.4. |
| Frontend (sub-phase G) | Component renders each status state (pending skeleton, ready brief, failed prompt). Polling hook backoff. |
| Eval (sub-phase H) | 3 golden handoffs → snapshot tests on deterministic brief output. Snapshots regenerate on intentional design changes only. |

### 3.7 Rollback story

The pipeline is feature-flagged behind `RESEARCH_EDITORIAL_BRIEF_ENABLED` (env, default `false` until ops greenlights production rollout). When disabled:
- `finalize_handoff()` does NOT enqueue compose task (existing behavior).
- `GET /api/research/brief/...` returns 404 unconditionally.
- MCP tool returns `BriefNotEnabled` typed error.
- Frontend hides the Research Brief section entirely.

To roll back a faulty deploy: flip the flag, ship the toggle. No DB migrations, no data cleanup. Cache is in-memory and process-local; restart clears it.

### 3.8 Editorial-vs-structural boundary

Per master plan §9: editorial = render concern over structure. The brief MUST NOT mutate `HandoffArtifact`, `Thesis`, or `ProcessTemplate`. Generators are read-only over the typed inputs. The brief is a **derivative artifact** — analogous to how `OverviewBrief` is a derivative of portfolio data, not a new portfolio data type. This boundary is enforced by:
- Generators take `ResearchContext` (immutable dataclass) — no DB session, no service handles.
- Policy layer takes candidates + context — no write surfaces.
- Service layer is the only seam that touches the cache (the only writeable surface).
- Architecture boundary test (see §3.9 below) enforces no `import` of mutation paths from `editorial/`.

### 3.9 Architecture boundary test

**R2 correction**: `tests/test_architecture_boundaries.py` does NOT yet exist in AI-excel-addin (Codex R1 verified). The risk_module test at `risk_module/tests/test_architecture_boundaries.py:112` enforces `actions/` transport neutrality only — it does not generalize to enforce editorial=read-only across repos.

Sub-phase A therefore bootstraps **new test infrastructure in AI-excel-addin** under `AI-excel-addin/tests/test_architecture_boundaries.py`, using the assertion pattern from the risk_module helper. Initial assertions:
- `api/research/editorial/` cannot import from `api/research/handoff.py` write paths (`finalize_handoff`, `_assemble_artifact_locked`, `update_handoff_artifact`, etc.) — only the Pydantic `HandoffArtifactV1_1` class.
- `api/research/editorial/` cannot import write-side methods from `api/research/repository.py` (e.g., `update_handoff_artifact`, `finalize_handoff`, `supersede_handoff`, `create_*`). Read-side `get_handoff`, `get_file`, `get_thesis_*` allowed.
- `api/research/editorial/` cannot import `fastapi` (transport neutral). Allowed only in the service-orchestration seam (`editorial/service.py`) if it injects `BackgroundTasks` from the route — but this plan keeps `BackgroundTasks` at the route layer per §3.3, so the editorial module stays fully transport-neutral.

---

## 4. Sub-phase A — `ResearchBrief` + `ResearchInsightCandidate` Pydantic contracts

### 4.1 Goal

Land the typed source-of-truth shapes for the brief envelope and candidate stream, with zero runtime dependencies. Everything downstream binds to these.

### 4.2 Design

```python
# AI-excel-addin/schema/research_brief.py

from typing import Literal
from pydantic import BaseModel, Field
from schema._insights_shared import _FROZEN_CONTRACT  # R3 fix — actual import path (R2 cited non-existent schema._frozen)

ResearchBriefStatus = Literal["pending", "ready", "failed"]
ResearchSlotKey = Literal["differentiated_view", "path", "valuation"]

class ResearchInsightCandidate(BaseModel):
    """One scored candidate emitted by a single generator."""
    model_config = _FROZEN_CONTRACT

    slot_key: ResearchSlotKey
    headline: str = Field(..., min_length=1, max_length=240)
    evidence: list[str] = Field(default_factory=list)            # supporting data points (verbatim from artifact)
    source_refs: list[str] = Field(default_factory=list)         # ids/anchors back into HandoffArtifact
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    conviction_score: float = Field(..., ge=0.0, le=1.0)         # generator's confidence in the call
    why: str = Field(..., min_length=1)                          # human-readable selection reason
    generator_id: str                                            # "thesis_differentiation" | "catalyst_risk" | "valuation_conviction"

class ResearchBriefSlot(BaseModel):
    """Selected slot content for the brief. Empty when no candidate available."""
    model_config = _FROZEN_CONTRACT

    slot_key: ResearchSlotKey
    selected: ResearchInsightCandidate | None = None             # None = unavailable / skipped
    candidates_considered: int = 0                               # for transparency / debugging

class ResearchEditorialMetadata(BaseModel):
    model_config = _FROZEN_CONTRACT

    schema_version: Literal["1.0"] = "1.0"
    generated_at: float                                          # unix ts
    handoff_id: int
    process_template_id: str | None = None                       # R3: dropped thesis_label per Codex R2 ("a truncated thesis statement is not a label")
    partial_failure: bool = False                                # one or more generators threw
    degraded: bool = False                                       # required input field missing
    fallback_template: bool = False                              # default ProcessTemplate used
    error_summary: dict[str, str] = Field(default_factory=dict)  # generator_id → exception class

class ResearchBrief(BaseModel):
    """Top-level brief envelope returned by GET /api/research/brief/.../...."""
    model_config = _FROZEN_CONTRACT

    schema_version: Literal["1.0"] = "1.0"
    status: ResearchBriefStatus
    headline: str | None = None                                  # composite headline; None when status != "ready"
    differentiated_view_slot: ResearchBriefSlot | None = None
    path_slot: ResearchBriefSlot | None = None
    valuation_slot: ResearchBriefSlot | None = None
    editorial_metadata: ResearchEditorialMetadata | None = None
    error_code: str | None = None                                # set when status="failed"
```

**Key design choices**:
- **Three fixed slots** (`differentiated_view`, `path`, `valuation`) — one per generator. Fixed-shape envelope mirrors `OverviewBrief.metricStrip` discipline; eliminates any ambiguity about layout.
- **Slot can be `None`** (`unavailable`) without breaking the brief — degrades gracefully when a generator no-ops (e.g., no `differentiated_view` in artifact).
- **No nested narrative blocks** — each slot has a single selected candidate. Multi-candidate exploration is Phase 2.
- **`error_summary` is generator_id → exception class name only** — no message bodies (leak risk), no stack traces (noise). Sufficient for debugging without contaminating logs.

### 4.3 Files to create / modify

Create:
- `AI-excel-addin/schema/research_brief.py` (~120 LOC including imports and docstrings)

Modify:
- `AI-excel-addin/schema/__init__.py` — re-export `ResearchBrief`, `ResearchInsightCandidate`, `ResearchBriefStatus`, `ResearchBriefSlot`, `ResearchEditorialMetadata`, `ResearchSlotKey`.

### 4.4 Tests

New: `AI-excel-addin/tests/schema/test_research_brief.py`
- ✅ Round-trip: serialize → deserialize → equality.
- ✅ `status="pending"` allows all optional fields `None`.
- ✅ `status="ready"` validates required fields populated by policy layer (cross-field validator).
- ✅ `status="failed"` requires `error_code` (cross-field validator).
- ✅ `relevance_score` and `conviction_score` reject out-of-range values.
- ✅ `headline` enforces `min_length=1, max_length=240`.
- ✅ `_FROZEN_CONTRACT` rejects extra fields (forward-compat trap).
- ✅ `ResearchSlotKey` literal rejects unknown slot keys.

**Estimate**: ~8 new tests.

---

## 5. Sub-phase B — `ResearchContext` builder

### 5.1 Goal

Build the typed input context generators read. **R2 simplification**: drops the separate Thesis repository lookup. The handoff already carries an embedded `thesis: ThesisField` snapshot at `handoff.py:122`; that snapshot IS the analyst's intent as-of-finalize, which is what the brief is *of*. Live Thesis fetch (decisions_log, scorecard) is a Phase 2 enhancement only if "is this brief stale vs current Thesis?" features get prioritized.

### 5.2 Design

```python
# AI-excel-addin/api/research/editorial/context.py

from dataclasses import dataclass
from schema.handoff import HandoffArtifactV1_1
from schema.process_template import ProcessTemplate, SectionConfig
from api.research.repository import ResearchRepository
from api.research.template_catalog import TemplateCatalog
from api.research.handoff_loader import artifact_from_row  # NEW (sub-phase B lift)

# R3: live TemplateCatalog has no get_default() getter (template_catalog.py:67–83);
# editorial defines its own minimal-default, used only when the artifact's
# process_template_id is unset OR the catalog returns None for the cited id.
_EDITORIAL_DEFAULT_TEMPLATE = ProcessTemplate(
    template_id="research_editorial_default",
    name="Research Editorial Default",
    description="Synthesized default used when no ProcessTemplate is linked or resolvable.",
    section_config=SectionConfig(),  # empty required/order/min_completion
)

@dataclass(frozen=True)
class ResearchContext:
    """Immutable input bundle for the editorial pipeline."""
    handoff: HandoffArtifactV1_1
    process_template: ProcessTemplate
    fallback_template: bool              # True when _EDITORIAL_DEFAULT_TEMPLATE is in use
    generated_at: float                  # unix ts (used by brief metadata)

def build_research_context(
    user_id: str,
    handoff_id: int,
    *,
    repo: ResearchRepository,
    template_catalog: TemplateCatalog,
) -> ResearchContext:
    """Pure assembly. No background work. Raises HandoffNotFound on missing/draft."""
    row = repo.get_handoff(handoff_id)                       # repository.py:2902 — single-arg lookup
    if row is None or row.get("status") != "finalized":
        raise HandoffNotFound(handoff_id)
    artifact = artifact_from_row(row)                        # row → HandoffArtifactV1_1 (sub-phase B lift)

    template: ProcessTemplate | None = None
    if artifact.process_template_id is not None:
        template = template_catalog.get(user_id, artifact.process_template_id)  # template_catalog.py:70
    fallback = template is None
    if fallback:
        template = _EDITORIAL_DEFAULT_TEMPLATE

    return ResearchContext(
        handoff=artifact,
        process_template=template,
        fallback_template=fallback,
        generated_at=time.time(),
    )
```

**Key design choices**:
- **Frozen dataclass** — generators can't accidentally mutate. Reinforces editorial-vs-structural boundary (§3.8).
- **No separate Thesis repo lookup** (R2 simplification). `handoff.thesis: ThesisField` is the source of analyst intent for brief composition. ThesisField fields (statement, conviction `int 1–5`, timeframe, strategy, direction, source_refs) can individually be `None` — generators tolerate gracefully (§3.4).
- **`get_handoff` is single-arg** — versioning is row-encoded, not a lookup parameter (Codex R1; `repository.py:2902`).
- **`TemplateCatalog`, not `ProcessTemplateRepository`** (R3 fix). Live API: `TemplateCatalog.get(user_id, template_id)` at `template_catalog.py:70`. No `get_default()` exists; editorial synthesizes its own minimal default constant (`_EDITORIAL_DEFAULT_TEMPLATE`).
- **Status guard**: raise `HandoffNotFound` if `status != "finalized"`. Briefs are only OF finalized handoffs (Codex R2 endorsed; drafts excluded per §1.1).

### 5.3 Files to create / modify

Create:
- `AI-excel-addin/api/research/editorial/__init__.py`
- `AI-excel-addin/api/research/editorial/context.py` (~80 LOC)
- `AI-excel-addin/api/research/handoff_loader.py` (NEW — sub-phase B lifts `_artifact_from_row` out of `handoff.py:522` into a typed public loader. Codex R2 confirmed `schema/handoff_loader.py` does not exist; the right home is API/research per Codex's R2 ask response, not `schema/`).

Modify:
- `AI-excel-addin/api/research/handoff.py` — replace internal `_artifact_from_row` calls with imports from the new `handoff_loader.py` (mechanical refactor; no behavior change). Keep test coverage on the existing call sites.

### 5.4 Tests

New: `AI-excel-addin/tests/research/editorial/test_context.py`
- ✅ Assembles full context from a valid finalized handoff row.
- ✅ Raises `HandoffNotFound` when row missing.
- ✅ Raises `HandoffNotFound` when row exists but `status="draft"` (briefs only of finalized).
- ✅ Returns `_EDITORIAL_DEFAULT_TEMPLATE` + `fallback_template=True` when `process_template_id` unset.
- ✅ Returns `_EDITORIAL_DEFAULT_TEMPLATE` + `fallback_template=True` when `process_template_id` set but `template_catalog.get(user_id, ...)` returns `None`.
- ✅ Frozen dataclass mutation attempts raise `FrozenInstanceError`.
- ✅ `template_catalog.get` called with `user_id` from caller (verifies multi-user isolation at the catalog boundary).

New: `AI-excel-addin/tests/research/test_handoff_loader.py` (NEW — sub-phase B lift)
- ✅ `artifact_from_row(row)` round-trip on a finalized row produces equal `HandoffArtifactV1_1` to the existing private path's output (regression-pin against `handoff.py:522`).
- ✅ Raises `ValueError` on rows that fail Pydantic validation.

**Estimate**: ~9 new tests (7 for context, 2 for loader).

---

## 6. Sub-phase C — 3 generators + `ResearchInsightGenerator` Protocol

### 6.1 Goal

Three concrete generators producing the brief's narrative spine: edge / path / value.

### 6.2 Design — Protocol

```python
# AI-excel-addin/api/research/editorial/generators/base.py

from typing import Protocol
from ..context import ResearchContext
from schema.research_brief import ResearchInsightCandidate

class ResearchInsightGenerator(Protocol):
    generator_id: str  # "thesis_differentiation" | "catalyst_risk" | "valuation_conviction"

    def generate(self, ctx: ResearchContext) -> list[ResearchInsightCandidate]:
        """Pure function: ResearchContext → candidates. Empty list = generator no-ops cleanly."""
```

Generators MUST:
- Be pure (no I/O, no DB session, no LLM calls in v1).
- Be exception-safe internally (raise `ResearchGeneratorError` for catastrophic failures the policy layer should treat as partial-failure).
- Cite source_refs back into the artifact (e.g., `"differentiated_view.claim_id:abc123"`).

### 6.3 Design — `ThesisDifferentiationGenerator`

**R2 fix**: rewritten to bind to live `DifferentiatedViewClaim` and `ThesisField` shapes (`thesis_shared_slice.py:131`, `thesis_shared_slice.py:91`). R1 cited non-existent fields (`differentiated_view.claims`, `claim.statement`, `claim.evidence_refs`, `claim.statement_summary`); R2 uses `handoff.differentiated_view` (a `list[DifferentiatedViewClaim]`) and the actual claim fields `claim`, `rationale`, `evidence`, `upside_if_right`, `downside_if_wrong`.

**Reads**: `handoff.differentiated_view: list[DifferentiatedViewClaim]`, `handoff.invalidation_triggers: list[InvalidationTrigger]`, `handoff.consensus_view: ConsensusView | None`, `handoff.thesis: ThesisField` (specifically `thesis.conviction: int | None` in 1–5).

**Emits**: 0–3 candidates (`slot_key="differentiated_view"`).

**Logic**:
- If `handoff.differentiated_view == []`: no-op (returns `[]`). Generator no-ops are normal.
- For each `claim_obj` in `handoff.differentiated_view` (top 3 by order — analyst authored most-important first):
  - `headline = claim_obj.claim` (truncated to 240 chars at `[:237] + "..."` if longer; field is required `str`).
  - `evidence = list(claim_obj.evidence)` (the source-id list) + `[claim_obj.rationale]` (rationale is the *why* of the claim, useful as supporting line).
  - `source_refs = [f"differentiated_view[{idx}].claim_id={claim_obj.claim_id}"]` (claim_id may be None — fall back to `f"differentiated_view[{idx}]"`).
- `relevance_score`: 0.7 base; +0.15 if `claim_obj.evidence` non-empty; +0.10 if `handoff.invalidation_triggers != []` (high-stakes thesis where claims are tied to rebuttable conditions); +0.05 if `claim_obj.upside_if_right` populated (analyst quantified the payoff). Clamp to [0, 1].
- `conviction_score`: derived from `handoff.thesis.conviction` (int 1–5) → mapping `{1: 0.2, 2: 0.4, 3: 0.6, 4: 0.8, 5: 1.0}`; default 0.5 when `conviction is None`.
- `why`: `f"Central edge: {claim_obj.claim[:80]}…. Rationale: {claim_obj.rationale[:60]}…."` — template, no LLM. Truncation kept short and predictable for snapshot stability.

### 6.4 Design — `CatalystRiskGenerator`

**R2 fix**: rewritten to use embedded `handoff.thesis.timeframe` (not separate `thesis.timeframe` lookup). Catalyst/Risk fields verified against live `thesis_shared_slice.py:175` (Catalyst) and `:188` (Risk).

**Reads**: `handoff.catalysts: list[Catalyst]` (`catalyst_id, description, expected_date, severity, source_ref`), `handoff.risks: list[Risk]` (`risk_id, description, severity, type, source_ref`), `handoff.monitoring: Monitoring | None`, `handoff.invalidation_triggers`, `handoff.thesis.timeframe`.

**Emits**: 0–3 candidates (`slot_key="path"`).

**Logic**:
- If `handoff.catalysts == []` AND `handoff.risks == []`: no-op.
- Build a unified "watch item" stream: each catalyst is a watch item (type=catalyst); each risk is a watch item (type=risk).
- Sort priority for emission (descending): (a) catalyst with `expected_date` within 90 days, (b) risk with severity matching `"high"` from `schema._insights_shared.Severity` (R3 — the canonical Severity literal is `"low" | "medium" | "high"`; substring match with `("high",)` against analyst-authored free-form `severity: str`), (c) catalyst with `expected_date > 90 days`, (d) risk with `"medium"` severity, (e) any remaining items.
- Take top 3.
- For each watch item:
  - `headline`: `f"{type.upper()}: {description[:200]}"` (description is required str on both Catalyst and Risk).
  - `evidence`: `[source_ref.id]` if `source_ref is not None` else `[]`. Plus a date string for catalysts (`f"expected: {expected_date}"`) when populated.
  - `source_refs`: `[f"{type}s[{idx}].id={catalyst_id_or_risk_id}"]`.
- `relevance_score`: 0.6 base; +0.2 if catalyst within 90 days OR severity matches `"high"` (per `_insights_shared.Severity`); +0.1 if `monitoring.watch_list` (when populated) references this catalyst's description keyword (case-insensitive substring). Clamp to [0,1].
- `conviction_score`: 0.5 default; +0.2 if catalyst has `expected_date` (timing certainty); −0.2 if no `expected_date` AND no `source_ref` (low-grounding event).
- `why`: `f"Path-watch ({type}): {description[:80]}…."` — template.

**v1 deliberate simplification**: catalyst↔risk pairing is dropped from §6.4 R1 because the live schemas don't share a category axis (Catalyst has no `category` field, Risk has only a free-form `type: str | None`). Pairing-by-keyword is brittle and snapshot-unstable. Each catalyst and each risk emit independently as candidates, top-3 selected — preserves the path-slot story without manufacturing a relationship the data doesn't carry.

### 6.5 Design — `ValuationConvictionGenerator`

**R2 fix**: drops upside-from-current-price computation. Live `Peer` (`thesis_shared_slice.py:211`) has only `ticker, name, source_refs` — no `reference_price`. `handoff.financials` (`handoff.py:104`) is `{source: "fmp"|"edgar", data: dict[str, Any]}` — opaque, no typed current-price contract. v1 ships a valuation slot WITHOUT upside %; valuation conviction comes from `range_breadth` and `thesis.conviction`. Phase 2 adds upside if a typed quote source surfaces (live portfolio-mcp quote at compose time would break the no-I/O-in-generators principle — flagging for Codex).

**Reads**: `handoff.valuation: Valuation | None` (`method, low, mid, high, current_multiple, rationale, source_refs`), `handoff.assumptions: list[Assumption]`, `handoff.peers`, `handoff.thesis.conviction`.

**Emits**: 0–1 candidates (`slot_key="valuation"`). Single-candidate slot — valuation is one call.

**Logic**:
- If `handoff.valuation is None` OR `valuation.mid is None`: no-op.
- Compute `range_breadth`: `(high - low) / mid` if all three present and `mid > 0`; clamp [0, 1]; treat `None` as `1.0` (worst-case wide-range signal). Wide range → lower conviction.
- `headline`: `f"{method or 'valuation'}: ${mid:,.2f} mid; range ${low:,.2f}–${high:,.2f}"` if all three present; else fallback `f"{method or 'valuation'}: ${mid:,.2f} mid"`.
- `evidence`: top 3 `assumption_obj.rationale` strings filtered by `assumption_obj.unit in {"price", "multiple", "growth", "margin"}` (the load-bearing valuation assumptions). `unit` may be `None` — skip those. Falls back to first 3 non-empty rationales if filter yields fewer than 3.
- `source_refs`: `["valuation"]` + `[f"assumptions[{i}].id={a.assumption_id}" for i in selected_assumption_indexes]`.
- `relevance_score`: 0.7 base; +0.15 if `handoff.peers != []` (relative valuation context); +0.10 if `len(handoff.assumptions) >= 5` (well-grounded model); +0.05 if `valuation.rationale` populated (analyst wrote the why).
- `conviction_score`: `thesis_term × 0.7 + range_term × 0.3` where:
  - `thesis_term`: from `handoff.thesis.conviction` int 1–5 → `{1: 0.2, 2: 0.4, 3: 0.6, 4: 0.8, 5: 1.0}`; 0.5 if `None`.
  - `range_term`: `1.0 - range_breadth` (narrow band → high; wide band → low).
- `why`: `f"Valuation: {method or 'method'} mid case ${mid:,.2f}. Range breadth {range_breadth:.0%}."` — template.

### 6.6 Files to create / modify

Create:
- `AI-excel-addin/api/research/editorial/generators/__init__.py`
- `AI-excel-addin/api/research/editorial/generators/base.py` (~50 LOC: Protocol + `ResearchGeneratorError`)
- `AI-excel-addin/api/research/editorial/generators/thesis_differentiation.py` (~120 LOC)
- `AI-excel-addin/api/research/editorial/generators/catalyst_risk.py` (~140 LOC)
- `AI-excel-addin/api/research/editorial/generators/valuation_conviction.py` (~110 LOC)

### 6.7 Tests

New (per generator): `AI-excel-addin/tests/research/editorial/generators/test_<generator>.py`

Per-generator coverage:
- ✅ Empty input → empty candidate list.
- ✅ Required fields present → expected candidates with correct slot_key.
- ✅ Score boundaries (0.0 ≤ scores ≤ 1.0; no overflow).
- ✅ `source_refs` resolve to artifact fields.
- ✅ Generator-specific edge cases (e.g., catalyst without expected_date, valuation with `mid=None`, etc.).
- ✅ `ResearchGeneratorError` raised on catastrophic input (cross-validates with §3.4 partial-failure path).

Plus a shared test for the Protocol contract (pyright/mypy structural check).

**Estimate**: ~30 new tests (~10 per generator).

---

## 7. Sub-phase D — Policy layer + brief cache

### 7.1 Goal

Compose the `ResearchBrief` envelope from candidates. Cache-aware, status-aware.

### 7.2 Policy design

```python
# AI-excel-addin/api/research/editorial/policy.py

def compose_brief(
    ctx: ResearchContext,
    candidate_streams: dict[str, list[ResearchInsightCandidate]],  # generator_id → candidates
    *,
    failures: dict[str, str] = {},                                  # generator_id → exception class
) -> ResearchBrief:
    """Pure compose. No I/O. Deterministic given inputs."""
    slots = {
        "differentiated_view": _select_slot("differentiated_view", candidate_streams),
        "path":               _select_slot("path", candidate_streams),
        "valuation":          _select_slot("valuation", candidate_streams),
    }
    headline = _compose_headline(slots, ctx)
    metadata = _build_metadata(ctx, failures, candidate_streams)
    status: ResearchBriefStatus = (
        "failed" if len(failures) == 3
        else "ready"
    )
    return ResearchBrief(
        status=status,
        headline=headline if status == "ready" else None,
        differentiated_view_slot=slots["differentiated_view"],
        path_slot=slots["path"],
        valuation_slot=slots["valuation"],
        editorial_metadata=metadata,
        error_code="all_generators_failed" if status == "failed" else None,
    )

def _select_slot(slot_key, streams) -> ResearchBriefSlot:
    """Per-slot selection: highest composite_score = 0.6*relevance + 0.4*conviction."""
    # R3 fix — Codex R2 caught the typo: list comp was appending whole stream lists.
    candidates = [
        cand
        for stream in streams.values()
        for cand in stream
        if cand.slot_key == slot_key
    ]
    if not candidates:
        return ResearchBriefSlot(slot_key=slot_key, selected=None, candidates_considered=0)
    ranked = sorted(candidates, key=lambda c: 0.6 * c.relevance_score + 0.4 * c.conviction_score, reverse=True)
    return ResearchBriefSlot(slot_key=slot_key, selected=ranked[0], candidates_considered=len(candidates))

def _compose_headline(slots, ctx) -> str:
    """Single-line headline summarizing the brief. Template-based, no LLM."""
    diff = slots["differentiated_view"].selected
    val = slots["valuation"].selected
    if diff and val:
        return f"{ctx.handoff.company.ticker}: {diff.headline} ({val.headline})"
    if diff:
        return f"{ctx.handoff.company.ticker}: {diff.headline}"
    if val:
        return f"{ctx.handoff.company.ticker}: {val.headline}"
    return f"{ctx.handoff.company.ticker} brief"
```

**Key design choices**:
- **Composite score = 0.6×relevance + 0.4×conviction.** Relevance > conviction because a high-conviction-but-irrelevant slot is worse than a relevant-but-uncertain one. Tunable via constant in v1; no env config (keep it deterministic).
- **One winner per slot.** No tie-breaking dance — sort is stable; identical-score ties resolve to insertion order (which is generator declaration order).
- **`status="failed"` only when ALL 3 generators threw.** 1–2 failures = `partial_failure=True` but `status="ready"`. Brief is useful even with 1 of 3 slots populated.

### 7.3 Cache design

```python
# AI-excel-addin/api/research/editorial/cache.py

from cachetools import LRUCache
from threading import Lock

# R3 fix: cache key is (user_id, handoff_id) — per-user repos make handoff_id non-unique globally.
BriefKey = tuple[str, int]   # (user_id, handoff_id)

_CACHE: LRUCache = LRUCache(maxsize=int(os.environ.get("RESEARCH_EDITORIAL_BRIEF_CACHE_SIZE", "256")))
_LOCKS: dict[BriefKey, Lock] = {}
_LOCKS_GUARD = Lock()

def get_or_pending(key: BriefKey) -> ResearchBrief | None:
    return _CACHE.get(key)

def set_brief(key: BriefKey, brief: ResearchBrief) -> None:
    _CACHE[key] = brief
    if brief.status == "failed":
        _schedule_failed_eviction(key, after_seconds=60)  # short TTL on failures

def acquire_compose_lock(key: BriefKey) -> Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, Lock())

def release_compose_lock(key: BriefKey) -> None:
    with _LOCKS_GUARD:
        _LOCKS.pop(key, None)
```

### 7.4 Files to create / modify

Create:
- `AI-excel-addin/api/research/editorial/policy.py` (~120 LOC)
- `AI-excel-addin/api/research/editorial/cache.py` (~80 LOC)

### 7.5 Tests

New: `AI-excel-addin/tests/research/editorial/test_policy.py`
- ✅ Three populated streams → all three slots filled with top candidate.
- ✅ One empty stream → that slot `selected=None`, others populated.
- ✅ All empty streams → all slots `selected=None`, status still `ready` (zero failures), headline = `f"{ticker} brief"`.
- ✅ Three generator failures → status=`failed`, error_code=`all_generators_failed`.
- ✅ Tie-break: identical scores → first-by-insertion wins (deterministic).
- ✅ Composite score math is `0.6*rel + 0.4*conv` (regression test on a known-input candidate).
- ✅ Headline composition: diff+val present, diff only, val only, neither.

New: `AI-excel-addin/tests/research/editorial/test_cache.py`
- ✅ Get-then-set round-trip.
- ✅ LRU eviction at capacity.
- ✅ Idempotency lock: two concurrent acquires return same Lock instance (then second blocks).
- ✅ Failed-brief eviction after 60s (use freezegun or time-mock).

**Estimate**: ~12 new tests.

---

## 8. Sub-phase E — Editorial service + async finalize-hook + REST endpoint

### 8.1 Goal

Wire the pipeline into the live finalize flow. Expose the brief over HTTP for the workspace UI.

### 8.2 Service design

```python
# AI-excel-addin/api/research/editorial/service.py

class ResearchEditorialService:
    def __init__(self, repo, template_catalog: TemplateCatalog):
        self.repo = repo                                        # ResearchRepository (per-user instance, read-only here)
        self.template_catalog = template_catalog
        self.generators = [
            ThesisDifferentiationGenerator(),
            CatalystRiskGenerator(),
            ValuationConvictionGenerator(),
        ]

    def compose_brief(self, user_id: str, handoff_id: int) -> None:
        """Background task entrypoint. Idempotent. Writes to cache."""
        key = (user_id, handoff_id)
        lock = acquire_compose_lock(key)
        if not lock.acquire(blocking=False):
            return  # another worker is composing; skip
        try:
            existing = get_or_pending(key)
            if existing is not None and existing.status != "pending":
                return  # already composed
            set_brief(key, ResearchBrief(status="pending"))
            ctx = build_research_context(
                user_id,
                handoff_id,
                repo=self.repo,
                template_catalog=self.template_catalog,
            )
            streams: dict[str, list[ResearchInsightCandidate]] = {}
            failures: dict[str, str] = {}
            for gen in self.generators:
                try:
                    streams[gen.generator_id] = gen.generate(ctx)
                except Exception as e:
                    failures[gen.generator_id] = type(e).__name__
                    streams[gen.generator_id] = []
            brief = compose_brief(ctx, streams, failures=failures)
            set_brief(key, brief)
        except HandoffNotFound:
            set_brief(key, ResearchBrief(status="failed", error_code="handoff_not_found"))
        except Exception as e:
            set_brief(key, ResearchBrief(status="failed", error_code=type(e).__name__))
        finally:
            lock.release()
            release_compose_lock(key)
```

### 8.3 Finalize-hook wiring (route layer)

**R2 fix**: hook lives at the **route layer**, not the service. Live `HandoffService.finalize_handoff(research_file_id)` is sync, takes only `research_file_id`, returns `dict[str, Any]` (`api/research/handoff.py:496`). Live route is `POST /handoffs/finalize` at `routes.py:1430`. Adding `BackgroundTasks` is a route-level injection — service signature untouched.

```python
# AI-excel-addin/api/research/routes.py — modify finalize_handoff

@router.post("/handoffs/finalize")
def finalize_handoff(
    body: FinalizeHandoffBody,
    background_tasks: BackgroundTasks,                                 # NEW
    user_id: str = Depends(get_trusted_user_id),
) -> dict[str, Any]:
    repo = get_repository_factory().get(user_id)
    service = HandoffService(repo)
    try:
        summary = _serialize_handoff(service.finalize_handoff(body.research_file_id))
    except TemplateRequirementsError as exc:
        raise HTTPException(409, detail={...}) from exc
    except DanglingSourceRefError as exc:
        _raise_typed_http_error(500, "dangling_source_ref", str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc)) from exc

    if os.environ.get("RESEARCH_EDITORIAL_BRIEF_ENABLED", "false") == "true":
        editorial = ResearchEditorialService(repo, get_template_catalog())
        background_tasks.add_task(editorial.compose_brief, user_id, summary["id"])

    return summary
```

### 8.4 REST endpoint

```python
# AI-excel-addin/api/research/routes.py — add

@router.get("/handoffs/{handoff_id}/brief")
def get_research_brief(
    handoff_id: int,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_trusted_user_id),
):
    if os.environ.get("RESEARCH_EDITORIAL_BRIEF_ENABLED", "false") != "true":
        raise HTTPException(404, "research-editorial-brief disabled")

    key = (user_id, handoff_id)
    brief = get_or_pending(key)
    if brief is not None:
        return brief

    repo = get_repository_factory().get(user_id)
    row = repo.get_handoff(handoff_id)
    if row is None:
        raise HTTPException(404, "handoff not found")
    if row.get("status") != "finalized":                              # R3: drafts excluded per Codex R2 ask response
        raise HTTPException(404, "handoff not finalized")

    editorial = ResearchEditorialService(repo, get_template_catalog())
    background_tasks.add_task(editorial.compose_brief, user_id, handoff_id)
    return ResearchBrief(status="pending")
```

`get_template_catalog()` is a process-singleton accessor following the existing `get_repository_factory()` pattern. If it doesn't exist today, sub-phase E lands it as a thin wrapper around `TemplateCatalog()` (defaults loaded once per process).

Endpoint path follows the existing `/handoffs/...` namespace at `routes.py` (consistent with `/handoffs/finalize` and `/handoffs/new-version`). Frontend polling URL is `/handoffs/{handoff_id}/brief`.

### 8.5 Files to create / modify

Create:
- `AI-excel-addin/api/research/editorial/service.py` (~140 LOC)

Modify:
- `AI-excel-addin/api/research/routes.py` — modify `finalize_handoff` (add `BackgroundTasks` injection + conditional enqueue; ~10 LOC delta) + new `get_research_brief` endpoint (~25 LOC).
- `AI-excel-addin/api/research/__init__.py` — export `ResearchEditorialService`.

**No edits to `api/research/handoff.py`** — `HandoffService` stays untouched (R2 simplification).

### 8.6 Tests

New: `AI-excel-addin/tests/research/editorial/test_service.py`
- ✅ `compose_brief` happy path: ctx → streams → cache populated with `status="ready"`.
- ✅ `compose_brief` partial failure: one generator throws → status=`ready`, partial_failure=True.
- ✅ `compose_brief` total failure: all generators throw → status=`failed`, error_code=`all_generators_failed`.
- ✅ `compose_brief` idempotency: second call no-ops while first runs.
- ✅ `compose_brief` HandoffNotFound → status=`failed`, error_code=`handoff_not_found`.

New: `AI-excel-addin/tests/research/test_finalize_hook.py`
- ✅ With flag on: finalize returns artifact + background task enqueued.
- ✅ With flag off: finalize returns artifact, NO task enqueued.
- ✅ Finalize errors don't break brief (independent paths).

New: `AI-excel-addin/tests/api/research/test_brief_endpoint.py`
- ✅ Returns cached brief when present.
- ✅ Returns `pending` and enqueues task when not cached but handoff exists.
- ✅ Returns 404 when handoff doesn't exist.
- ✅ Returns 404 when flag is off.

**Estimate**: ~14 new tests.

---

## 9. Sub-phase F — risk_module MCP tool surface

### 9.1 Goal

Expose the brief through the agent surface, following the existing risk_module → AI-excel-addin gateway proxy pattern.

### 9.2 Tool surface

```python
# risk_module/mcp_tools/research.py — add (alongside existing research MCP tools)

@mcp.tool()
def get_research_brief(handoff_id: int) -> dict:
    """Fetch the editorial brief for a finalized research handoff.

    Returns agent-format envelope with the typed ResearchBrief payload.
    Statuses:
      - ready: brief composed; payload contains all slots
      - pending: composing — caller may retry after backoff
      - failed: error_code populated; brief unavailable
    """
```

Typed errors:
- `BriefNotEnabled` — feature flag off (404 from gateway).
- `BriefNotFound` — handoff/version doesn't exist (404).
- `BriefPending` — `status=pending`; caller retries (200 with status field).
- `BriefFailed` — `status=failed`; surface `error_code` in agent format.

### 9.3 Files to create / modify

**R3 fix**: Codex R2 caught that `risk_module/agent_format/classifier.py` does not exist — research MCP surface today flows through `actions/research.py`, `mcp_tools/research.py`, and `mcp_server.py` registration. Real paths used below.

Create:
- (none — the new tool slots into existing `mcp_tools/research.py` rather than introducing a new module file; consistent with how other research MCP tools live there per `mcp_tools/research.py:327`).

Modify:
- `risk_module/actions/research.py` — add `get_research_brief(user_id, handoff_id)` action that proxies via the gateway client and unwraps the typed `ResearchBrief`. Mirrors the pattern at `actions/research.py:554`.
- `risk_module/mcp_tools/research.py` — add the `get_research_brief` MCP tool (agent-format wrapper around the action).
- `risk_module/mcp_server.py` — register the tool (mirror the pattern at `mcp_server.py:2573`).

### 9.4 Tests

New tests added to `risk_module/tests/mcp_tools/test_research.py` (existing file — colocate with other research tool tests):
- ✅ Happy path: gateway returns `ready` brief → tool returns agent-format `{status: "ok", format: "agent", snapshot, flags}`.
- ✅ `pending` → tool returns agent-format with `status="pending"` flag.
- ✅ `failed` → tool returns agent-format with `error_code` flag.
- ✅ 404 from gateway → `BriefNotFound` typed error.
- ✅ Gateway disabled → `BriefNotEnabled` typed error.
- ✅ Tool registered in `mcp_server.py` (smoke test that the registration ran).

**Estimate**: ~6 new tests.

---

## 10. Sub-phase G — Frontend UI section

### 10.1 Goal

Surface the brief in the workspace UI alongside structural sections. Status-aware rendering.

### 10.2 Component design

`frontend/packages/ui/src/components/research/ResearchBriefSection.tsx`

```tsx
type Props = {
  handoffId: number;
};

// Polls /handoffs/{handoffId}/brief with backoff: 500ms, 1s, 2s, 4s, 8s; cap 8s; max 60s total.
// Hides the section entirely if RESEARCH_EDITORIAL_BRIEF_ENABLED is off (404 unconditionally → hide).

const ResearchBriefSection: React.FC<Props> = ({ handoffId }) => {
  const { data: brief, status: queryStatus } = useResearchBriefPoll(handoffId);

  if (queryStatus === "error" /* 404 */) return null;            // feature flag off or no brief — hide
  if (!brief || brief.status === "pending") return <BriefSkeleton />;
  if (brief.status === "failed") return <BriefErrorPrompt errorCode={brief.error_code} />;
  return <BriefBody brief={brief} />;                             // headline + 3 slot cards
};
```

`<BriefBody>` renders:
- Headline as section title.
- Three slot cards in fixed order: differentiated_view, path, valuation. Each card shows `headline`, `evidence` (bulleted), `why` (small print, expandable).
- `editorial_metadata.partial_failure` → small "incomplete" badge near title.
- `editorial_metadata.degraded` → small "limited data" badge.

### 10.3 Files to create / modify

Create:
- `frontend/packages/ui/src/components/research/ResearchBriefSection.tsx` (~180 LOC).
- `frontend/packages/ui/src/components/research/ResearchBriefSection.test.tsx` (~120 LOC).
- `frontend/packages/ui/src/hooks/useResearchBriefPoll.ts` (~80 LOC).

Modify:
- The research workspace detail container that hosts `HandoffSectionRenderer` (path TBD during impl — Codex grep-locates precisely; the section mounts adjacent to existing handoff sections, not replacing any). Add `<ResearchBriefSection ... />` above the structural sections.

### 10.4 Tests

New tests in `ResearchBriefSection.test.tsx`:
- ✅ Renders skeleton while `status="pending"`.
- ✅ Renders BriefBody when `status="ready"`.
- ✅ Renders error prompt when `status="failed"` (with `error_code`).
- ✅ Hides component on 404 (feature flag off path).
- ✅ Polls with correct backoff schedule (mock timer).
- ✅ Stops polling after 60s and renders "still composing — try refresh" prompt.
- ✅ Three slots render in fixed order regardless of API response field order.
- ✅ `partial_failure` badge renders when flag set.

**Estimate**: ~8 new tests.

---

## 11. Sub-phase H — Eval fixtures + golden scenarios

### 11.1 Goal

3 golden handoff fixtures producing snapshot-stable briefs. Catches regressions when generator scoring or policy logic drifts.

### 11.2 Fixtures

Create at `AI-excel-addin/tests/research/editorial/fixtures/`:

| Fixture | Narrative shape | What it stresses |
|---|---|---|
| `high_conviction_differentiated.json` | Strong differentiated view, multiple claims with consensus deltas, valuation ranges narrow, catalysts well-timed. | All 3 slots populate strongly; high conviction scores. |
| `defensive_risk_focused.json` | Thin differentiated_view, multiple material risks, valuation range wide, no near-term catalysts. | path slot dominates; valuation conviction scores low (wide range); differentiated_view slot may no-op. |
| `catalyst_driven.json` | M&A or earnings event within 30 days, modest differentiated_view, valuation moderate. | path slot near-term boost (+0.2 within 90 days); brief leads with timing. |

Each fixture includes:
- Full finalized `HandoffArtifactV1_1` JSON (including the embedded `thesis: ThesisField` snapshot — R3: no separate Thesis JSON, since R2 dropped Thesis fetch).
- Linked `ProcessTemplate` JSON (one fixture omits to exercise `_EDITORIAL_DEFAULT_TEMPLATE` fallback).
- Expected `ResearchBrief` snapshot.

### 11.3 Snapshot test

`AI-excel-addin/tests/research/editorial/test_eval_scenarios.py`:
- For each fixture, runs the full pipeline (`build_research_context` → generators → policy) and snapshots the `ResearchBrief` against `expected_brief.json`.
- Snapshots regenerate via env flag `RESEARCH_EDITORIAL_REGEN_SNAPSHOTS=1` (manual, not CI).
- A non-snapshot assertion validates score boundaries [0,1] and slot count == 3 (catches structural drift even when content drifts).

**Estimate**: ~3 fixtures + ~6 tests (3 snapshots + 3 structural).

---

## 12. Sub-phase I — Docs + master plan §12 ship marker

### 12.1 Master plan patch

In `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md`:

1. §12 row 10 status update: `RESEARCH_EDITORIAL_PIPELINE_PLAN.md` → mark **(SHIPPED)** with date + commit refs (cross-repo: AI-excel-addin commits A–H + risk_module commit F + frontend commit G).
2. §9 footnote append (one paragraph): "The research-editorial pipeline anticipated above shipped 2026-MM-DD as plan #10 (`RESEARCH_EDITORIAL_PIPELINE_PLAN.md`). v1 ships the deterministic three-generator pipeline + workspace UI section. LLM arbiter, markdown/PDF export, and editorial_memory coupling are Phase 2."
3. §12 ship-notes block — same shape as plan #9's, capturing test counts + commit refs + V2.P9 status delta (8 SHIPPED → 9 SHIPPED; remaining DESIGNED: #7, #8).

### 12.2 Other docs

- `docs/TODO.md` — V2.P9 row for plan #10 → SHIPPED (cross-reference §12 ship notes).
- No updates to `SKILL_CONTRACT_MAP.md` in v1 — the brief is a render envelope, not a typed-contract field skills populate. Phase 2 may add a row if generators absorb skill outputs.

### 12.3 Files to create / modify

Modify:
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` — §12 row 10 + §9 footnote + §12 ship-notes.
- `docs/TODO.md` — V2.P9 row.
- `docs/planning/RESEARCH_EDITORIAL_PIPELINE_PLAN.md` (this doc) — header status `DRAFT` → `SHIPPED` + ship summary.

---

## 13. Decisions

### 13.1 Locked

1. **Three fixed slots, one winner each.** No multi-candidate exploration in v1.
2. **Composite score = 0.6×relevance + 0.4×conviction.** Tunable via constant only — no env config in v1.
3. **`status="failed"` requires ALL 3 generators failing.** 1–2 failures = `status="ready"` with `partial_failure=True`.
4. **Cache eternal-while-version-stable.** No TTL on `status="ready"`; 60s TTL on `status="failed"` for retry fan-out.
5. **No LLM arbiter in v1.** Deterministic-only. Phase 2.
6. **No editorial_memory coupling in v1.** Lane C migration in flight; coupling later. Personalization in v1 = Thesis + ProcessTemplate.
7. **Async post-finalize, lazy re-enqueue on read.** No durable queue; process crash → next read re-composes.
8. **One consumer (workspace UI section) in v1.** Markdown/PDF/email = Phase 2.
9. **Frontend polls; no websocket.** Backoff 500ms→8s; 60s max.
10. **Pipeline lives in AI-excel-addin.** Per master plan §3 ownership; risk_module proxies via gateway.
11. **Architecture boundary test enforces editorial=read-only.** New test in `tests/test_architecture_boundaries.py` (§3.9).
12. **Feature flag `RESEARCH_EDITORIAL_BRIEF_ENABLED` (default false until ops greenlights).** Clean rollback path.

### 13.2 Open for Codex review (R3)

R1+R2 questions all closed via Codex iteration:
- ~~Composite weights~~ — endorsed.
- ~~Current_price / upside~~ — RESOLVED (dropped from v1).
- ~~Lazy re-enqueue tradeoff~~ — endorsed.
- ~~Thesis_label~~ — DROPPED from `ResearchEditorialMetadata` per Codex R2 ("a truncated thesis statement is not a label").
- ~~Status guard for drafts~~ — RESOLVED (`status != "finalized"` → 404 in GET endpoint).
- ~~Catalyst↔risk pairing~~ — endorsed drop.
- ~~`artifact_from_row` location~~ — RESOLVED: `api/research/handoff_loader.py` (lifted from private `_artifact_from_row` at `handoff.py:522`).
- ~~Severity vocabulary~~ — RESOLVED: bind to `schema._insights_shared.Severity` literal (`"low" | "medium" | "high"`).
- ~~Architecture boundary test scaffold~~ — bootstrapping new `tests/test_architecture_boundaries.py` in AI-excel-addin (sub-phase A).
- ~~Cross-repo deployment story~~ — refined in §3.1 + §9.3.

Remaining open for R3:

1. **"All 3 failed = `status=failed`" threshold.** Too lenient? Should `status="failed"` also trigger when `differentiated_view` slot fails specifically (centerpiece)? Or 2-of-3 threshold?
2. **Snapshot test stability** — Templates use `${mid:,.2f}` — float-bound but analyst-authored static numbers per finalize. Snapshots should be stable. Codex: confirm or suggest a fixture-freezing pattern.
3. **Cache size default (256).** Per-process, NOT per-tenant. In a multi-user gateway deployment, 256 entries shared across N users could thrash. v1 single-user dev — fine. Codex: confirm v1 sizing or call for an env-driven scaling rule.
4. **`status="failed"` with `error_code="handoff_not_found"`** — log level? Currently warn. Could indicate data-integrity smell (recently deleted) or normal user error (frontend cached old id).
5. **`get_template_catalog()` singleton** — does this accessor exist already (analogous to `get_repository_factory()`) or does sub-phase E need to land it? Codex confirm.
6. **Multi-user cache eviction fairness** — with `(user_id, handoff_id)` keys and a 256-cap LRU, a heavy user can evict another user's briefs. Acceptable v1 simplicity or worth per-user partitioning?

---

## 14. Out of scope (v1) — explicit non-goals recap

Per §1.1, none of these are "build if needed" deferrals — each has a concrete reason:

| Out-of-scope item | Reason | Phase 2 target |
|---|---|---|
| LLM arbiter / voice rewrite | Overview audit (`EDITORIAL_PIPELINE_AUDIT.md`) flagged delivery-gap problems with arbiter; resolve those first. | Phase 2.1 |
| Markdown/PDF export | Render layer over the typed envelope; mechanical add-on once envelope is locked. Sequencing: get the envelope right first. | Phase 2.2 |
| Email digest | Same as above. Layer-3 consumer. | Phase 2.3 |
| editorial_memory coupling | Lane C canonical-vocab migration is in flight; coupling now imports unsettled state. | Phase 2.4 (after Lane C settles) |
| Industry-context generator (G5 surface) | Plan #7 `INDUSTRY_RESEARCH_TOOLS_PLAN.md` owns G5. Two plans on same surface = scope fight. | Plan #7. |
| Qualitative-factor rollup generator | Process-template-dependent; pattern still settling per audit. | Phase 2.5 |
| Thesis-coherence cross-section generator | Cross-section reasoning is sophisticated; needs its own design pass. | Phase 2.6 |
| Regenerate button | Finalize-a-new-version IS the regenerate path. UI button is workflow-redundant. | Phase 2.7 (only if user research surfaces a real gap). |
| Websocket push delivery | Polling is sufficient at v1 user count + 60s window. | Phase 2.8 |
| Frontend export affordance (PDF download / share link) | Depends on Phase 2.2 (markdown/PDF export). | Phase 2.9 |
| Persistent cache (DB/Redis) | In-memory LRU sufficient at v1 cardinality. | Phase 2.10 (revisit when cache thrash measurable). |

---

## 15. Plan #10 fits in the Investment Schema Unification series

Per `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §12 (as of 2026-04-28):

| # | Plan | Status |
|---|---|---|
| 1 | THESIS_LIVING_ARTIFACT | PASS R7 (verify SHIPPED) |
| 2 | HANDOFF_ARTIFACT_V1_1 | PASS R5 (verify SHIPPED) |
| 3 | MODEL_BUILD_CONTEXT | PASS R8 (verify SHIPPED) |
| 4 | INVESTMENT_IDEA_INGRESS | SHIPPED 2026-04-22 |
| 5 | PROCESS_TEMPLATE | SHIPPED 2026-04-23 |
| 5b | EXTENSIBLE_STRATEGY_CATEGORY | SHIPPED 2026-04-26 |
| 6 | MODEL_INSIGHTS_PRICE_TARGET | SHIPPED 2026-04-24 |
| 7 | INDUSTRY_RESEARCH_TOOLS | DESIGNED — Codex PASS R7 (commit `a5cb7222`); no SHIPPED marker found in risk_module git log |
| 8 | EDGAR_FMP_PRECEDENCE | SHIPPED 2026-04-28 (commit `10176e3b`) |
| 9 | KNOWLEDGE_WIKI_SCHEMA | SHIPPED 2026-04-25 |
| **10** | **RESEARCH_EDITORIAL_PIPELINE (this plan)** | **SHIPPED 2026-04-28** |

V2.P9 status after plan #10 ships: **10 SHIPPED / 1 DESIGNED** (Plan #7 remains Codex PASS/pre-ship per risk_module git log; Plan #8 shipped in commit `10176e3b`).

---

## 16. Test count target

| Sub-phase | New tests (estimate) |
|---|---|
| A | 8 |
| B | 6 |
| C | 30 (10 per generator × 3) |
| D | 12 |
| E | 14 |
| F | 6 |
| G | 8 |
| H | 6 (3 snapshot + 3 structural) |
| I | — (docs only) |
| **Total** | **~90 new tests** |

Plus: 1 architecture boundary test (§3.9), 1 classifier-row test (sub-phase F).

---

## 17. Acceptance gates

Plan ships when:

- [ ] All Pydantic contracts (§4) imported in `AI-excel-addin/schema/__init__.py`, type-checked.
- [ ] `ResearchContext` builder (§5) assembles cleanly from a real (non-fixture) finalized handoff in the dev workspace.
- [ ] Three generators (§6) produce non-empty candidate lists on the `high_conviction_differentiated` fixture; produce empty (no-op) lists on a synthetic empty-input handoff (e.g., `differentiated_view==[]`, `valuation is None`, `catalysts==[] && risks==[]`).
- [ ] Policy layer (§7) compose result is deterministic across 100 runs on a fixed input (no hidden non-determinism — e.g., `dict` iteration order).
- [ ] Route-level finalize-hook (§8.3) integrates behind feature flag; flag-off path = no enqueued task (asserted in tests). `HandoffService.finalize_handoff` signature unchanged.
- [ ] Lazy re-enqueue (§3.5) verified: cache cleared mid-pending → next GET re-composes.
- [ ] MCP tool (§9) end-to-end via gateway returns typed agent-format envelope.
- [ ] Frontend section (§10) renders all four states (pending, ready, failed, hidden-on-flag-off) — manual smoke + automated tests.
- [ ] All 3 eval fixtures (§11) snapshot-stable; one regen pass committed before ship.
- [ ] Architecture boundary test (§3.9) lands in **AI-excel-addin** (new file, sub-phase A bootstrap) and passes.
- [ ] Master plan §12 row 10 → SHIPPED (sub-phase I).
- [ ] Codex PASS R≥2 on this plan.

---

## 18. Codex review request

Send to Codex with:
- This file (`docs/planning/RESEARCH_EDITORIAL_PIPELINE_PLAN.md`).
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` (master).
- `docs/planning/OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md` (clone-pattern reference).
- `docs/planning/EDITORIAL_PIPELINE_AUDIT.md` (Phase 1 gap analysis — explains why we don't blind-clone).
- `docs/planning/completed/OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md` (implementation reference).
- `AI-excel-addin/schema/handoff.py` (HandoffArtifactV1_1 source — confirm field availability).
- `AI-excel-addin/schema/thesis.py` (Thesis source — confirm shipped).
- `AI-excel-addin/schema/process_template.py` (ProcessTemplate source).
- `AI-excel-addin/api/research/handoff.py` (`HandoffService.finalize_handoff` — confirm hook point shape).

**Asks for Codex (R3)**:

R1+R2-closed (no need to re-ask): plan #1/#2 ship status, 3-generator cut, 0.6/0.4 weights, lazy re-enqueue, status-guard for drafts, catalyst↔risk pairing drop, valuation upside drop, severity vocab binding, `artifact_from_row` location, thesis_label drop, schema field paths, finalize-hook at route layer, `_FROZEN_CONTRACT` import, `_select_slot` typo, multi-user cache key.

R3 open:
1. **§13.2 R3 questions 1–6** — fail-threshold, snapshot stability, cache sizing, log level, `get_template_catalog()` accessor existence, multi-user cache eviction fairness.
2. **§8.4 `get_template_catalog()` singleton** — does this exist or does sub-phase E land it as a thin singleton wrapper? (Mirror `get_repository_factory()` pattern.)
3. **§9.3 risk_module wiring** — confirm the right insertion points for `actions/research.py`, `mcp_tools/research.py`, `mcp_server.py`. Path-stitch claims based on Codex R2 cites — re-verify.
4. **R3 multi-user safety** — `(user_id, handoff_id)` cache key, `template_catalog.get(user_id, ...)` in §5.2. Anything else that crosses a user boundary I missed?

**Reviewer note**: encourage local execution. R3 binds to `AI-excel-addin/schema/{handoff.py:116, thesis_shared_slice.py:91/131/201/211, _insights_shared.py:8/15, process_template.py:60/115}`, `api/research/{handoff.py:496/522, repository.py:2902/3705, template_catalog.py:55/70/76, routes.py:1430}`. Verify still accurate.

---

## 19. Change log

- **R1** (2026-04-27) — Initial draft. Three-generator narrative-spine cut (§1, §6). Async post-finalize hook with lazy re-enqueue (§3.5). Deterministic-only v1 (no LLM arbiter, no editorial_memory coupling). Workspace UI section as the single v1 consumer. ~90 new tests across 9 sub-phases.
- **R2** (2026-04-27) — Codex R1 returned FAIL with 5 High, 3 Medium, 5 Low. R1 had been written against an inferred schema; R2 binds to live Pydantic shapes verified via Codex local execution. Fixes:
  - **High #1** (§6.3): `differentiated_view` is `list[DifferentiatedViewClaim]` (not `differentiated_view.claims`); claim fields are `claim, rationale, evidence, upside_if_right, downside_if_wrong` (not `statement, evidence_refs, statement_summary`). Generator rewritten.
  - **High #2** (§6.3, §6.4, §6.5): `Thesis` has nested `thesis: ThesisField` (path is `Thesis.thesis.statement`); `conviction` is int 1–5, not `high/medium/low`. Generators read off `handoff.thesis: ThesisField` (the embedded snapshot at `handoff.py:122`), conviction mapped via `{1:0.2, ..., 5:1.0}`.
  - **High #3** (§6.5): `Peer` has only `ticker, name, source_refs` — no `reference_price`. `handoff.financials` is opaque `dict[str, Any]`. **Dropped upside-from-current-price computation entirely** for v1. Valuation slot ships with mid/low/high + range_breadth; conviction comes from `thesis.conviction × 0.7 + (1 - range_breadth) × 0.3`. Phase 2 adds upside if a typed quote source surfaces.
  - **High #4** (§5.2): `ResearchRepository.get_handoff(handoff_id)` is single-arg (versioning row-encoded); `ThesisRef` has only `thesis_id, version, markdown_path` (no `(user_id, ticker, label)` anchor). Builder simplified — drops separate Thesis fetch entirely; uses `handoff.thesis` snapshot. `ResearchContext` no longer carries a `thesis: Thesis | None` field.
  - **High #5** (§8.3): `HandoffService.finalize_handoff` is sync, takes only `research_file_id`, has no `BackgroundTasks` parameter. Hook moved to **route layer** at `routes.py:1430`. Service stays untouched. `BackgroundTasks` injected at the route.
  - **Medium #1** (§3.4 ↔ §5.2 conflict): "Thesis missing → failed" path removed. `handoff.thesis: ThesisField` is always present (default_factory); individual fields can be None and generators tolerate.
  - **Medium #2** (Dependency block): `ProcessTemplate.required_sections` → `ProcessTemplate.section_config.required` (live path).
  - **Medium #3** (§3.9): `tests/test_architecture_boundaries.py` does NOT exist in AI-excel-addin (Codex-verified). Plan now bootstraps the test file in AI-excel-addin from sub-phase A onward. Existing risk_module test only enforces `actions/` neutrality, not `core/overview_editorial/` — claim corrected.
  - **Low #1** (Dependency block): Plans #1 and #2 confirmed SHIPPED (Codex saw `5370a50` Thesis + `f69aa72/203ad57/5e47452/03a43ac` Handoff v1.1 commits). Block updated.
  - **Low #2–#5**: Codex R1 endorsed 3-generator cut, 0.6/0.4 weights, lazy re-enqueue, and `Thesis.label` as canonical thesis_label. R2 dropped the `thesis_label` question (moot — no Thesis fetch).
  - **Cache key** (§3.2, §3.3, §3.5, §7.3, §8, §9, §10): `(handoff_id, version)` → `handoff_id`. Each `create_new_version` produces a new row with a new `handoff_id`; the version tuple was redundant.
  - **§13.2 reset**: R1 questions 1, 4, 7 closed; R2 introduces 7 new open questions (severity vocab, status guard, simplification choices, arch-boundary bootstrap, etc.).
  - **§6.4 simplification** beyond Codex findings: dropped catalyst↔risk pairing because live schemas don't share a category axis; each catalyst and risk emits independently.
- **R3** (2026-04-27) — Codex R2 returned FAIL with 4 High, 3 Medium, plus useful Ask responses. Fixes:
  - **High #1** (§3.2, §3.3, §3.5, §7.3, §8, §9, §10): cache key `handoff_id` → `(user_id, handoff_id)`. Per Codex R2: per-user SQLite repos make `handoff_id` non-unique globally; a process-global cache keyed only by int could leak briefs across users (`repository.py:3705` is the per-user repo factory). All cache plumbing updated; service.compose_brief now takes `(user_id, handoff_id)`; route layer threads `user_id` from `Depends(get_trusted_user_id)`.
  - **High #2** (§5.2, §8.3, §8.4): `ProcessTemplateRepository` was fictitious. Live API is `TemplateCatalog.get(user_id, template_id)` and `is_default(template_id)` — no `get_default()` accessor (`template_catalog.py:55–83`). R3 introduces `_EDITORIAL_DEFAULT_TEMPLATE` (synthesized minimal default in editorial code) and `get_template_catalog()` singleton wrapper.
  - **High #3** (§4.2): Wrong `_FROZEN_CONTRACT` import path. Live module is `schema._insights_shared` (`_insights_shared.py:8`), not `schema._frozen` (which doesn't exist). Import corrected.
  - **High #4** (§7.2): Code typo in `_select_slot` — comprehension built `[c for c in streams.values() ...]` (full lists) instead of `[cand for stream in streams.values() for cand in stream ...]`. Fixed.
  - **Medium #1** (§9.3): Wrong risk_module paths — `agent_format/classifier.py` doesn't exist. Real wiring goes through `actions/research.py:554`, `mcp_tools/research.py:327`, `mcp_server.py:2573`. Updated.
  - **Medium #2** (§1, §2): R1 "Thesis + HandoffArtifact + ProcessTemplate" framing still appeared in summary text. Updated to "embedded `handoff.thesis: ThesisField` snapshot only" matching §5.2 R2 simplification.
  - **Medium #3** (§11): Fixtures still referenced linked Thesis JSON / no-Thesis path. Dropped — fixtures now full handoff + optional ProcessTemplate only.
  - **Codex Ask responses adopted**: `artifact_from_row` lifted into `api/research/handoff_loader.py` (NOT `schema/`, per Codex's "row hydration is repository/API concern"); `thesis_label` field dropped from `ResearchEditorialMetadata`; severity vocab bound to `schema._insights_shared.Severity` literal; GET endpoint adds `status == "finalized"` guard explicitly.
  - **§13.2 reset**: 6 R3 open questions (fail threshold, snapshot stability, cache sizing, log level, `get_template_catalog()` existence, multi-user eviction fairness).
- **R3-post-PASS** (2026-04-27) — Codex R3 returned **PASS**. Confirmed: `get_template_catalog()` exists at `template_catalog.py:117`; `TemplateCatalog.get(user_id, template_id)` is correct; per-user repo scoping justifies the cache key. All 6 R3 open questions answered:
  - **Fail threshold**: keep all-3-failed-only; missing differentiated_view → degraded, not failed.
  - **Snapshot stability**: acceptable (analyst-authored static numbers, not live quotes).
  - **Cache size 256 process-global**: fine for v1; env var = escape hatch.
  - **`handoff_not_found` log level**: warn at compose-time, normal access logs at route 404.
  - **Multi-user eviction fairness**: defer until production pressure exists.
  - **Risk-module insertion points**: confirmed `actions/research.py:554`, `mcp_tools/research.py:327`, `mcp_server.py:2573`.

  Non-blocking doc polish swept after PASS verdict: §2 row D cache key wording (`handoff_id` → `(user_id, handoff_id)`); §2 row F + §9.2 file path (drop `mcp_tools/research_brief.py`, slot into existing `mcp_tools/research.py`); §9.4 dropped classifier registry test (replaced with `mcp_server.py` registration smoke test); §15 series row updated (`DRAFT R1` → `DRAFT R3 — Codex PASS`).
- **R4-SHIPPED** (2026-04-28) — Plan #10 fully implemented across 2 repos.
  9 sub-phases A–I committed. Master plan §12 row 10 → SHIPPED. V2.P9 advanced
  to 10 SHIPPED / 1 DESIGNED. Plan ready for production rollout once
  RESEARCH_EDITORIAL_BRIEF_ENABLED feature flag flips on (default false until
  ops greenlights).

**Plan implemented.** Production rollout remains gated on `RESEARCH_EDITORIAL_BRIEF_ENABLED` flipping on after ops greenlights.
