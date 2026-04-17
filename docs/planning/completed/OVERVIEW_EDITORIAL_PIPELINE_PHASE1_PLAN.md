# Overview Editorial Pipeline — Phase 1 Implementation Plan

**Status**: Codex PASS (R12, 2026-04-11) — ready for implementation
**Created**: 2026-04-11
**Inputs**:
- Product/editorial design: `docs/planning/OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md` (APPROVED)
- Architecture spec: `docs/planning/OVERVIEW_EDITORIAL_PIPELINE_ARCHITECTURE.md` (Codex PASS round 6, commit `8a9c8273`)
- E20a validation: `docs/planning/completed/LLM_BRIEFING_EXPERIMENT_PLAN.md` (VALIDATED)

This is the implementation plan for **Phase 1** of the Overview Editorial Pipeline. It breaks the architecture spec into 8 independently committable sub-phases (6 backend + 2 frontend) with concrete file paths, test counts, acceptance gates, risks, and rollback stories.

---

## 1. Plan Purpose

The architecture spec (§17 decision table) locks the *what*. This document locks the *how*: sub-phase ordering, dependencies, file boundaries, acceptance gates for each review round, and the critical path.

**Goals of this plan**:
- Break Phase 1 into ~1-week committable units, each independently reviewable and revertible
- Define acceptance gates per sub-phase so Codex + reviewers know what to check
- Identify the critical path + parallelizable sub-phases
- Surface per-sub-phase risks and rollback stories
- Establish the QA checklist that verifies §14 ship criteria

**Non-goals**:
- Re-deriving architectural decisions (already locked in the arch spec)
- Writing actual code (this plan is the input to code, not code itself)
- Phase 2 scope (deferred to its own spec + plan when Phase 1 ships)

**Timeline estimate**: 6-7 weeks end-to-end (honest serial backend critical path + parallel frontend work).

---

## 2. Sub-phase Summary

**Restructured after Codex round 1 review** — round 1 found the original B5-parallel-with-B2-B4 claim was false (B5 imports `invalidate_brief_cache` from B3 and `load_editorial_state` from B2). Also: `actions/` cannot import FastAPI per `tests/test_architecture_boundaries.py:200`. Sub-phases restructured so the data layer (B2) owns all state store helpers, the action layer (B4) stays transport-neutral, and the transport layer (B5) owns FastAPI/MCP surface.

| # | Sub-phase | Scope | Duration | Depends on | Commits |
|---|---|---|---|---|---|
| B1 | Migration + Pydantic models | `user_editorial_state` table + `models/overview_editorial.py` | ~3 days | — | 1 |
| B2 | Data layer: PortfolioContext + orchestrator + full editorial_state_store + diff.py | Data gathering + state persistence + diff computation | ~5 days | B1 | 1 |
| B3 | Generators + policy + brief cache + directive/annotation emission | Editorial selection + brief cache with invalidation helper | ~5 days | B2 | 1 |
| B4 | Action layer + LLM arbiter (transport-neutral, NO FastAPI) | Business action composing the pipeline; arbiter enhancement | ~4 days | B3 | 1 |
| B5 | Transport layer: route + gateway enricher + MCP tool + BackgroundTasks + founder bootstrap | REST endpoint, MCP tool, gateway per-process cache, BackgroundTasks dispatch, founder seed script | ~4 days | B4 | 1 |
| B6 | Auto-seeder + hook integration | First-connection seeding + invalidation wiring at real hook sites | ~3 days | B5 | 1 |
| F1a | Frontend types + registry stubs + ChatMargin prop + overviewBriefStore | No user-visible change while store is empty | ~3 days | — | 1 |
| F1b | Container refactor + hook + adapter + margin threading + composition flatten | Full editorial integration | ~5 days | F1a, B5 | 1 |

**Total committable units**: 8 (6 backend + 2 frontend).
**Total duration on critical path**: ~29 working days (~6 weeks) — backend is fully serial.
**Parallelizable work**: F1a can run fully in parallel with B1–B6 (no backend dependency). F1b can overlap with B6 (both depend on B5, not each other).

**Key restructuring decisions** (from round 1 review findings):
- **B2 absorbs ALL of editorial_state_store.py** (load + set_editorial_memory + seed_editorial_memory_if_missing + set_previous_brief) + `diff.py`. Previous draft split state store across B2 (read-only) and B5 (writers), creating a false parallelism claim and orphaning diff.py.
- **B3 adds directive/annotation emission** — generators now emit `ArtifactDirective` and `MarginAnnotation` candidates alongside metric/lead_insight/attention_item candidates, per arch spec §9.8.2 and §9.9.2. Previous draft only selected metric/lead/attention, making the §14 directive/annotation ship criteria impossible.
- **B4 is transport-neutral** — `actions/overview_brief.py` does NOT import `fastapi.BackgroundTasks` (forbidden by `tests/test_architecture_boundaries.py:200`). It returns the brief + a callback for the arbiter; the route layer (B5) dispatches via BackgroundTasks.
- **B5 is the transport layer** — `routes/overview.py` + gateway enricher + MCP tool + BackgroundTasks + founder bootstrap. All FastAPI/MCP surface lives here.
- **Auth is dict-based** — `user["user_id"]`, `user["email"]`, NOT `user.id`. Per real auth at `app_platform/auth/dependencies.py:14-27`.
- **PositionService** at `services/position_service.py:336` requires `user_email` (positional). `get_all_positions()` takes `consolidate`, `force_refresh`, etc. — NOT `user_id` or `portfolio_id`.
- **result_cache** snapshot functions need `portfolio_name`, `portfolio_data`, `risk_limits_data`, `performance_period`, and a zero-arg `builder` callable. NOT just `user_id + portfolio_id`.
- **MCP tools** receive `user_email` as a function parameter, not via `ctx.user`.
- **Structured logging** — `overview_brief_generated`, `overview_brief_enhanced`, `editorial_memory_updated`, `editorial_memory_auto_seed_skipped` events are instrumented in the sub-phase that emits them (B4 for brief events, B2 for memory events, B6 for auto-seed events).

---

## 3. Dependency Graph

```
B1 (migration + models)
  ↓
B2 (data layer: orchestrator + state store + diff)
  ↓
B3 (generators + policy + brief cache + directive emission)
  ↓
B4 (action layer — transport-neutral, no FastAPI)
  ↓
B5 (transport layer: route + MCP + gateway + BackgroundTasks + founder bootstrap)
  ↓
B6 (auto-seeder + hook integration)

F1a (frontend prep) — independent, starts Week 1, no backend dependency
  ↓
F1b (full integration) — depends on F1a + B5 (REST endpoint live)
```

**Backend is fully serial**: B1 → B2 → B3 → B4 → B5 → B6. Each sub-phase imports from the previous. No false parallelism claims.

**Frontend parallelizes with backend**: F1a starts Week 1 alongside B1, ships independently. F1b starts after B5 lands (needs the REST endpoint). F1b and B6 can overlap.

**Critical path**: B1 → B2 → B3 → B4 → B5 → B6 → QA (24 working days on the serial chain). F1b adds ~5 days overlapping with B6.

**Longest single sub-phase**: B2 (~5 days, absorbs state store + diff), B3 (~5 days, adds directive emission), F1b (~5 days, full refactor). These are the pacing gates.

**Timeline**:
- Week 1: B1 (~3 days) + F1a (parallel, ~3 days)
- Week 2: B2 (~5 days)
- Week 3: B3 (~5 days)
- Week 4: B4 (~4 days, starts late Week 3 or early Week 4)
- Week 5: B5 (~4 days) + F1b starts (parallel, depends on B5's route landing mid-week)
- Week 6: B6 (~3 days, overlaps with F1b) + QA checklist starts late Week 6
- Week 7 (buffer): QA + telemetry validation + ship criteria verification

Total: **~6-7 weeks** (was ~5.5 weeks with the false B5 parallelism; honest serial chain is longer).

---

## 4. Cross-Cutting Concerns

These constraints apply to every sub-phase. Reviewers check them per sub-phase.

### 4.1 Wire schema authority

The backend Pydantic model at `models/overview_editorial.py` is the one source of truth for the wire format. Frontend TS types in `overviewBrief.tsx` + `BackendBriefAdapter.ts` must match exactly. Schema drift is the #1 risk mitigated by the adapter's strict validation (returns null on mismatch → container falls back to `buildOverviewBrief()` TS path).

**Rule**: any change to `OverviewBrief`, `MetricStripItem`, `LeadInsight`, `ArtifactDirective`, `MarginAnnotation`, or `EditorialMetadata` in the backend requires a matching TS update in the same commit. No "I'll fix the TS side next PR."

### 4.2 Cache invalidation contract

Every write path that mutates positions, performance/risk data, or editorial_memory MUST call `invalidate_brief_cache(user_id)`. The helper also clears `clear_result_snapshot_caches()` (L2). Three hook sites are verified:
1. `workers/tasks/positions.py:48` (post-sync, inside Celery task)
2. `routes/onboarding.py:810` (post-CSV-import, inside FastAPI handler)
3. `core/overview_editorial/editorial_state_store.py:set_editorial_memory()` + `:seed_editorial_memory_if_missing()` (post-DB-upsert)

No new write path may land in Phase 1 without the hook. Codex reviews each sub-phase for this.

### 4.3 Failure mode coverage

Every new code path must preserve the fallback story from arch spec §5.4:
- Generator fails → empty candidate list, brief composed with fewer candidates
- All 3 generators fail → `BriefPipelineError` / `BriefNoCandidatesError` → 503 → frontend TS fallback
- DB unavailable → seed file fallback for memory, None anchor
- LLM arbiter fails → deterministic brief stands
- Adapter validation fails → null → TS fallback
- `/api/overview/brief` unreachable → React Query onError → TS fallback

**Rule**: Every PR touching a failure path must include a test that simulates the failure and verifies the fallback fires.

### 4.4 Testing strategy

**Unit tests**: each new module gets unit tests with fixed fixtures. No real DB, no real LLM, no network. Target: >85% line coverage per new module.

**Integration tests**: per-sub-phase integration tests stitch multiple modules together with mocked boundaries (mocked `CompletionProvider`, mocked `PositionService`, mocked `result_cache`). Verify end-to-end contracts.

**Regression tests**: for sub-phases that touch existing code (B6 hooks, F1a prop additions, F1b container refactor), DOM-level or output-level regression tests verify zero-change-when-empty.

**Manual smoke tests**: per-sub-phase manual verification checklist at the end of each sub-phase section.

### 4.5 Rollback story

Each sub-phase is independently revertible. The plan specifies the exact revert operation per sub-phase. If a sub-phase ships and later needs to be rolled back:
- **Schema migration (B1)**: drop the table (`DROP TABLE user_editorial_state`) + revert migration file
- **Module additions (B2/B3/B4/B6)**: delete new files, revert modified files. No data loss.
- **Route + transport (B5)**: delete `routes/overview.py` from `app.py`, delete `mcp_tools/overview_editorial.py`, revert `gateway_proxy.py`. B2 state store writers continue to work (lazy imports no-op without the gateway enricher). Frontend fallback path handles the absent endpoint automatically.
- **Frontend refactors (F1a/F1b)**: revert the container to the pre-refactor state, delete new files. Phase 0 seam stays intact.

---

## 5. Sub-phase B1 — Migration + Pydantic Models

### 5.1 Goal

Lay the data foundations. New DB table + all Pydantic models for the wire schema. No runtime behavior yet.

### 5.2 Scope

- New DB migration: `user_editorial_state` table with `editorial_memory JSONB`, `previous_briefs JSONB` (map keyed by portfolio_id), `created_at`, `updated_at`
- New Pydantic models covering every type referenced in arch spec §7: `OverviewBrief`, `MetricStripItem`, `LeadInsight`, `ExitRamp`, `AttentionItem`, `EditorialMetadata`, `ArtifactDirective`, `MarginAnnotation`, `InsightCandidate`, `EditorialMemory` (memory blob shape for validation)
- No orchestrator, no generators, no route. Just types + table.

**Out of scope**:
- `PortfolioContext` dataclass (lives in B2 as a pure Python dataclass, not a Pydantic model)
- Any logic that reads/writes the table (comes in B2 and B5)

### 5.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `database/migrations/<timestamp>_add_user_editorial_state.sql` | Migration (up + down) | ~30 |
| `models/overview_editorial.py` | All Pydantic models | ~300 |
| `tests/models/test_overview_editorial.py` | Pydantic validation + round-trip | ~250 |

### 5.4 Files to modify

None. Pure additions.

### 5.5 Migration shape

```sql
-- database/migrations/<timestamp>_add_user_editorial_state.sql

-- Up
CREATE TABLE IF NOT EXISTS user_editorial_state (
  user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  editorial_memory JSONB NOT NULL DEFAULT '{}'::jsonb,
  previous_briefs  JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_editorial_state_updated ON user_editorial_state(updated_at);

-- Down
DROP INDEX IF EXISTS idx_user_editorial_state_updated;
DROP TABLE IF EXISTS user_editorial_state;
```

The `previous_briefs` column is a JSONB map keyed by portfolio_id string (or `"default"` when portfolio_id is None). Each value is a serialized `OverviewBrief` blob. This is the diff/novelty anchor per portfolio — see arch spec §9.1 for rationale.

### 5.6 Pydantic model shape

Match arch spec §7 exactly. Key structure:

```python
# models/overview_editorial.py

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class MetricStripItem(BaseModel):
    id: str
    title: str
    value: str
    change: str | None = None
    context_label: str | None = None
    tone: Literal["up", "down", "neutral"] = "neutral"
    why_showing: str | None = None

class ExitRamp(BaseModel):
    label: str
    action_type: Literal["navigate", "chat_prompt"]
    payload: str

class LeadInsight(BaseModel):
    headline: str
    evidence: list[str] = []
    exit_ramps: list[ExitRamp] = []

class AttentionItem(BaseModel):
    category: str
    headline: str
    urgency: Literal["alert", "act", "watch"]
    action: ExitRamp | None = None

class EditorialMetadata(BaseModel):
    generated_at: datetime
    editorial_memory_version: int
    candidates_considered: int
    selection_reasons: list[str] = []
    confidence: Literal["high", "partial", "summary only"]
    source: Literal["live", "mixed", "summary"]
    llm_enhanced: bool = False
    changed_slots: list[str] = []

class ArtifactDirective(BaseModel):
    artifact_id: str
    position: int
    visible: bool = True
    annotation: str | None = None
    highlight_ids: list[str] = []
    editorial_note: str | None = None
    changed_from_previous: bool = False

class MarginAnnotation(BaseModel):
    anchor_id: str
    type: Literal["ask_about", "editorial_note", "context"]
    content: str
    prompt: str | None = None
    changed_from_previous: bool = False

class OverviewBrief(BaseModel):
    metric_strip: list[MetricStripItem]
    lead_insight: LeadInsight
    artifact_directives: list[ArtifactDirective] = []
    margin_annotations: list[MarginAnnotation] = []
    attention_items: list[AttentionItem] = []
    editorial_metadata: EditorialMetadata

class InsightCandidate(BaseModel):
    slot_type: Literal["metric", "lead_insight", "attention_item"]
    category: Literal["concentration", "risk", "performance", "income",
                      "trading", "factor", "tax", "events"]
    content: dict
    relevance_score: float = Field(ge=0, le=1)
    urgency_score: float = Field(ge=0, le=1)
    novelty_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1, default=1.0)
    evidence: list[str] = []
    why: str
    source_tool: str

class EditorialMemory(BaseModel):
    """Loose validation envelope for the editorial_memory blob.
    Most fields are optional because the AI writes arbitrary shapes within convention."""
    version: int = 1
    investor_profile: dict = {}
    editorial_preferences: dict = {}
    current_focus: dict = {}
    conversation_extracts: list[dict] = []
```

### 5.7 Implementation order

1. Draft migration SQL, apply to a fresh dev DB, verify table + index exist
2. Apply migration rollback, verify clean drop
3. Write `models/overview_editorial.py`, import from pydantic v2
4. Write `tests/models/test_overview_editorial.py`:
   - Happy-path construction for each model
   - ValidationError on required field omission
   - `ge/le` bound enforcement on scoring floats
   - JSON round-trip (model → `model_dump_json()` → `model_validate_json()` → identical)
   - Optional field defaults
5. Run `pytest tests/models/test_overview_editorial.py` — confirm 0 failures

### 5.8 Test requirements

Target: 20+ unit tests. Coverage:
- 1 happy-path test per model (10 models × 1)
- 1 validation-error test per required-field omission (10 tests)
- 5 round-trip tests (the 5 most-serialized models)
- 5 edge cases (empty lists, None values, invalid enum literals)

Total: ~30 tests.

### 5.9 Acceptance gate

Reviewer (Codex or human) verifies:
- Migration applies cleanly and rolls back cleanly on a fresh dev DB
- `previous_briefs` column is `JSONB NOT NULL DEFAULT '{}'::jsonb` (not a single-value column — this was the P1 multi-portfolio fix from round 2 of arch spec review)
- All Pydantic models compile and validate correctly
- `OverviewBrief` accepts `artifact_directives=[]` and `margin_annotations=[]` without error
- `EditorialMetadata.changed_slots` is present and defaults to `[]`
- JSON round-trip on `OverviewBrief` produces byte-identical output

### 5.10 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Migration naming collision with an in-flight parallel session | Low | Use `<timestamp>_add_user_editorial_state.sql` format matching existing conventions |
| Pydantic v1 vs v2 drift — repo uses v2, verify imports | Low | Test at commit time; failing imports surface immediately |
| `Literal` type narrowing issues with older type checkers | Low | Repo already uses `Literal` elsewhere — follow existing pattern |

### 5.11 Rollback

Delete the migration file (if not yet applied to prod), delete `models/overview_editorial.py`, delete the test file. If the migration has been applied, run the down-migration (`DROP INDEX...; DROP TABLE...`).

### 5.12 Manual smoke test

```bash
# Apply migration
cd /Users/henrychien/Documents/Jupyter/risk_module
python scripts/run_migrations.py  # scans database/migrations/

# Verify table exists
psql -d risk_module -c "\d user_editorial_state"

# Verify JSONB defaults
psql -d risk_module -c "SELECT column_name, column_default FROM information_schema.columns WHERE table_name='user_editorial_state';"

# Run tests
pytest tests/models/test_overview_editorial.py -v
```

---

## 6. Sub-phase B2 — Data Layer: PortfolioContext + Orchestrator + Full Editorial State Store + Diff

### 6.1 Goal

Build the complete data layer: parallel fan-out to positions/risk/performance, editorial state persistence (ALL read + write helpers), and the diff computation function. This sub-phase owns every function that touches `user_editorial_state` or normalizes tool outputs.

**Restructured from round 1 review**: original plan split the state store across B2 (read-only) and B5 (writers), creating false parallelism. Now B2 owns the full state store including `set_editorial_memory`, `seed_editorial_memory_if_missing`, and `set_previous_brief`. Also adds `diff.py` which was orphaned in the original plan.

### 6.2 Scope

- `core/overview_editorial/__init__.py` — package init
- `core/overview_editorial/context.py` — `PortfolioContext` dataclass + `tool_snapshot()` / `tool_flags()` helpers
- `core/overview_editorial/orchestrator.py` — `DataGatheringOrchestrator` with `ThreadPoolExecutor` fan-out
- `core/overview_editorial/editorial_state_store.py` — **ALL helpers**: `load_editorial_state`, `set_editorial_memory`, `seed_editorial_memory_if_missing`, `set_previous_brief`
- `core/overview_editorial/diff.py` — `compute_changed_slots(new_brief, previous_brief_anchor) -> list[str]`

**Out of scope**:
- Generators, policy, brief cache, LLM arbiter, route, MCP tool, gateway enricher (all in later sub-phases)

**Critical API corrections** (from code investigation):
- `PositionService` is at `services/position_service.py:336`, needs `user_email` (positional), `user_id` optional. `get_all_positions()` takes `consolidate`, `force_refresh`, etc. — NOT `user_id/portfolio_id` args.
- `result_cache.get_analysis_result_snapshot()` at `services/portfolio/result_cache.py:221` needs `user_id`, `portfolio_name`, `portfolio_data`, `risk_limits_data`, `performance_period`, and a zero-arg `builder` callable. NOT just `user_id + portfolio_id`.
- `result_cache.get_performance_result_snapshot()` at `:295` — similar shape, needs `portfolio_name`, `portfolio_data`, `benchmark_ticker`, and a `builder` callable.
- DB access: `from database import get_db_session; with get_db_session() as conn: db_client = DatabaseClient(conn)` — raw psycopg2 connection, not a session object.
- Auth objects are dicts: `user["user_id"]`, `user["email"]` — not object attributes.

### 6.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/__init__.py` | Package init | ~5 |
| `core/overview_editorial/context.py` | `PortfolioContext` dataclass | ~100 |
| `core/overview_editorial/orchestrator.py` | `DataGatheringOrchestrator` | ~200 |
| `core/overview_editorial/editorial_state_store.py` | Full state store: `load_editorial_state`, `set_editorial_memory`, `seed_editorial_memory_if_missing`, `set_previous_brief` | ~300 |
| `core/overview_editorial/diff.py` | `compute_changed_slots(new_brief, previous_brief_anchor) -> list[str]` | ~80 |
| `tests/core/overview_editorial/__init__.py` | Test package init | ~5 |
| `tests/core/overview_editorial/test_context.py` | `PortfolioContext` tests | ~120 |
| `tests/core/overview_editorial/test_orchestrator.py` | Orchestrator fan-out + failure modes | ~250 |
| `tests/core/overview_editorial/test_editorial_state_store.py` | All state store paths: load + seed fallback + writers + previous_brief + invalidation callbacks | ~350 |
| `tests/core/overview_editorial/test_diff.py` | Slot-level diff computation | ~120 |

### 6.4 Files to modify

None.

### 6.5 `PortfolioContext` shape (arch spec §6.1)

```python
# core/overview_editorial/context.py

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

@dataclass(frozen=True)
class PortfolioContext:
    user_id: int
    portfolio_id: str | None
    tool_results: dict[str, dict]  # {"positions": {...}, "risk": {...}, "performance": {...}}
    data_status: dict[str, Literal["loaded", "partial", "failed"]]
    editorial_memory: dict
    previous_brief_anchor: dict | None  # per-portfolio, loaded from user_editorial_state.previous_briefs[portfolio_id]
    generated_at: datetime

    def tool_snapshot(self, name: str) -> dict | None:
        if self.data_status.get(name) == "failed":
            return None
        return self.tool_results.get(name, {}).get("snapshot")

    def tool_flags(self, name: str) -> list[dict]:
        if self.data_status.get(name) == "failed":
            return []
        return self.tool_results.get(name, {}).get("flags", [])
```

### 6.6 Orchestrator shape

Uses `concurrent.futures.ThreadPoolExecutor` following the existing pattern in `core/factor_intelligence.py` and `core/realized_performance/engine.py`.

**API corrections** (verified via code investigation — previous draft used wrong signatures):
- `PositionService` at `services/position_service.py:336` — constructor requires `user_email` (positional), `user_id` optional. `get_all_positions()` accepts `consolidate`, `force_refresh`, etc. — NOT `user_id/portfolio_id`.
- `result_cache` snapshot functions at `services/portfolio/result_cache.py:221` and `:295` — need `portfolio_name`, `portfolio_data`, `risk_limits_data`/`benchmark_ticker`, and a zero-arg `builder` callable. NOT just `user_id + portfolio_id`.

The orchestrator needs to adapt these real API shapes into the generic `{snapshot, flags}` format that generators consume. This requires loading portfolio data first (to get the inputs the cache functions need), then passing the expensive compute steps as builder closures.

```python
# core/overview_editorial/orchestrator.py

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.editorial_state_store import load_editorial_state
from services.position_service import PositionService  # NOT services/portfolio/
from services.portfolio.result_cache import (
    get_analysis_result_snapshot,
    get_performance_result_snapshot,
)

_logger = logging.getLogger(__name__)

def gather_portfolio_context(
    user_email: str,
    user_id: int,
    portfolio_id: str | None,
) -> PortfolioContext:
    """Parallel fan-out to the 3 Phase 1 data sources + load editorial state.

    Note: accepts user_email because PositionService requires it (positional).
    user_id is used for cache keys and editorial state lookup.
    """
    tool_results: dict[str, dict] = {}
    data_status: dict[str, str] = {}

    def _gather_positions():
        try:
            ps = PositionService(user_email=user_email, user_id=user_id)
            result = ps.get_all_positions(consolidate=True)
            return "positions", _normalize_positions(result), "loaded"  # uses get_top_holdings()
        except Exception:
            _logger.warning("positions gather failed for user %s", user_id, exc_info=True)
            return "positions", None, "failed"

    def _gather_risk():
        try:
            # result_cache needs portfolio_data + risk_limits_data + a builder callable.
            # Implementation note: the orchestrator must obtain these inputs first,
            # then wrap the expensive computation as a zero-arg builder closure.
            # The exact inputs depend on how the existing callers (mcp_tools/risk.py)
            # obtain them — trace during implementation.
            result = get_analysis_result_snapshot(
                user_id=user_id,
                portfolio_name="CURRENT_PORTFOLIO",
                portfolio_data=...,      # obtain from PositionService or DB
                risk_limits_data=...,    # obtain from risk limits config
                performance_period="1Y",
                builder=lambda: _build_risk_analysis(...),  # expensive compute
            )
            return "risk", _normalize_risk(result), "loaded"
        except Exception:
            _logger.warning("risk gather failed for user %s", user_id, exc_info=True)
            return "risk", None, "failed"

    def _gather_performance():
        try:
            result = get_performance_result_snapshot(
                user_id=user_id,
                portfolio_name="CURRENT_PORTFOLIO",
                portfolio_data=...,      # obtain from PositionService or DB
                benchmark_ticker="SPY",  # from user config or default
                builder=lambda: _build_performance_analysis(...),
            )
            return "performance", _normalize_performance(result), "loaded"
        except Exception:
            _logger.warning("performance gather failed for user %s", user_id, exc_info=True)
            return "performance", None, "failed"

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_gather_positions),
            executor.submit(_gather_risk),
            executor.submit(_gather_performance),
        ]
        for future in as_completed(futures):
            tool_name, normalized, status = future.result()
            if normalized is not None:
                tool_results[tool_name] = normalized
            data_status[tool_name] = status

    # Load editorial state (single DB read, portfolio-scoped previous_brief)
    editorial_memory, previous_brief_anchor = load_editorial_state(user_id, portfolio_id)

    return PortfolioContext(
        user_id=user_id,
        portfolio_id=portfolio_id,
        tool_results=tool_results,
        data_status=data_status,
        editorial_memory=editorial_memory,
        previous_brief_anchor=previous_brief_anchor,
        generated_at=datetime.now(timezone.utc),
    )

def _normalize_positions(result) -> dict:
    """PositionResult → normalized {snapshot, flags} for generators.

    PositionResult does NOT have get_agent_snapshot() — the canonical MCP agent
    shape is assembled in mcp_tools/positions.py:464 (adds top_holdings, flags,
    sector enrichment outside the result object). The normalizer must replicate
    the relevant subset.

    Normalized schema (generators consume this):
      snapshot.holdings: list[{ticker, weight_pct, value, type}]  # from get_top_holdings(10)
      snapshot.total_value: float
      snapshot.hhi: float  # from sum(weight^2)
      snapshot.position_count: int
    flags: list[dict]  # from core/position_flags.py if available, else []
    """
    holdings = result.get_top_holdings(10) if hasattr(result, "get_top_holdings") else []
    total_value = getattr(result, "total_value", 0.0) or 0.0
    return {
        "snapshot": {
            "holdings": holdings,  # [{ticker, weight_pct, value, type}]
            "total_value": total_value,
            "hhi": sum((h.get("weight_pct", 0) / 100) ** 2 for h in holdings),
            "position_count": len(getattr(result, "data", {}).get("positions", []) if hasattr(result, "data") else []),
        },
        "flags": [],  # Position flags require separate computation; omit for Phase 1
    }

def _normalize_risk(result) -> dict:
    """RiskAnalysisResult → normalized {snapshot, flags} for generators.

    Uses get_summary() for portfolio-level metrics and get_agent_snapshot()
    for the full agent shape.

    Normalized schema (generators consume this):
      snapshot.volatility_annual: float
      snapshot.herfindahl: float
      snapshot.risk_drivers: list[dict]
      snapshot.leverage: float
      snapshot.factor_variance_pct: float
    flags: list[dict]  # from core/risk_flags.py
    """
    summary = result.get_summary() if hasattr(result, "get_summary") else {}
    agent_snap = result.get_agent_snapshot() if hasattr(result, "get_agent_snapshot") else {}
    return {
        "snapshot": {
            "volatility_annual": summary.get("volatility_annual"),
            "herfindahl": summary.get("herfindahl"),
            "risk_drivers": summary.get("risk_drivers", []),
            "leverage": summary.get("leverage"),
            "factor_variance_pct": summary.get("factor_variance_pct"),
            "risk_limit_violations": agent_snap.get("risk_limit_violations_summary"),
        },
        "flags": [],  # Risk flags are added by mcp_tools/risk.py, not the result object.
                      # Phase 1 omits flag threading — generators use snapshot data only.
    }

def _normalize_performance(result) -> dict:
    """PerformanceResult → normalized {snapshot, flags} for generators.

    Uses get_agent_snapshot() which returns the nested {returns, risk, benchmark} shape.

    Normalized schema (generators consume this):
      snapshot.total_return_pct: float
      snapshot.annualized_return_pct: float
      snapshot.max_drawdown_pct: float
      snapshot.sharpe_ratio: float
      snapshot.alpha_annual_pct: float
      snapshot.beta: float
    flags: list[dict]  # from core/performance_flags.py
    """
    agent_snap = result.get_agent_snapshot() if hasattr(result, "get_agent_snapshot") else {}
    returns = agent_snap.get("returns", {})
    risk = agent_snap.get("risk", {})
    benchmark = agent_snap.get("benchmark", {})
    return {
        "snapshot": {
            "total_return_pct": returns.get("total_return_pct"),
            "annualized_return_pct": returns.get("annualized_return_pct"),
            "max_drawdown_pct": risk.get("max_drawdown_pct"),
            "sharpe_ratio": risk.get("sharpe_ratio"),
            "alpha_annual_pct": benchmark.get("alpha_annual_pct"),
            "beta": benchmark.get("beta"),
        },
        "flags": [],  # Perf flags are added by mcp_tools/performance.py, not the result object.
                      # Phase 1 omits flag threading — generators use snapshot data only.
    }
```

**Implementation note — result object APIs** (MUST resolve during B2 implementation):

The code examples above use **illustrative field names that are NOT the real API**. The verified result object APIs (from code investigation):

- **`PositionResult.get_top_holdings(n=10)`** (`core/result_objects/positions.py:687`):
  Returns list of `{"ticker", "weight_pct", "value", "type"}`. Note: `weight_pct` not `weight`, `type` not `asset_type`. **No sector field** — sector must be resolved separately via factor proxy or profile lookup.

- **`RiskAnalysisResult.get_summary()`** (`core/result_objects/risk.py:250`):
  Returns `{"total_value", "net_exposure", "gross_exposure", "leverage", "notional_leverage", "position_count", "volatility_annual", "volatility_monthly", "herfindahl", "factor_variance_pct", "idiosyncratic_variance_pct", "risk_drivers"}`. Note: `volatility_annual` not `annual_volatility`. **No `risk_score` or `max_drawdown`** on get_summary() — risk_score comes from `get_risk_score()` (separate compute), max_drawdown comes from PerformanceResult.
  `get_agent_snapshot()` (`:276`) wraps summary + portfolio_factor_betas + variance_decomposition + risk_limit_violations + beta_exposure_checks + coverage.

- **`PerformanceResult.get_agent_snapshot()`** (`core/result_objects/performance.py:267`):
  Returns `{"period", "returns", "risk", "benchmark", "verdict", "insights"}`.
  Key paths: `returns.total_return_pct`, `returns.annualized_return_pct`, `risk.volatility_pct`, `risk.max_drawdown_pct`, `risk.sharpe_ratio`, `benchmark.alpha_annual_pct`, `benchmark.beta`.
  Note: `total_return_pct` not `ytd_return`, `max_drawdown_pct` not `max_drawdown`.

**All generator and seeder field references in B3/B6 are illustrative** and must be updated to match the real normalized snapshot shape during implementation. The normalizers in B2 (`_normalize_positions`, `_normalize_risk`, `_normalize_performance`) are the translation layer — they produce a stable `{snapshot, flags}` dict that generators consume. Define the normalized schema during B2 implementation and update generators accordingly.

The normalizers (`_normalize_positions`, `_normalize_risk`, `_normalize_performance`) must translate these real APIs into the `{snapshot, flags}` shape that generators consume. The generators in B3 and the seeder in B6 then access fields via the normalized shape. Trace the exact field paths from `mcp_tools/risk.py`, `mcp_tools/performance.py`, and `mcp_tools/positions.py` during implementation — those are the canonical callers.

The `...` placeholders for `portfolio_data`, `risk_limits_data`, and builder functions must also be resolved by tracing how existing callers obtain these inputs. The orchestrator likely needs to call `PositionService.get_all_positions()` first to get the `PositionResult`, then thread it into the risk/performance builders. This is the main implementation challenge of B2.

### 6.7 Editorial State Store (full: load + set + seed + set_previous_brief + diff)

The state store owns ALL functions that touch `user_editorial_state`. **Restructured from round 1**: previous draft split readers into B2 and writers into B5 — this created false parallelism (B4 needs `set_previous_brief` for rotation, which would have imported from B5 transport layer). Now B2 owns the complete store.

**Circular import avoidance**: writers call `invalidate_brief_cache` (from `brief_cache.py`, B3) and `_invalidate_user_memory_cache` (from `gateway_proxy.py`, B5). Both callees are created in later sub-phases. B2 ships the writer functions with the callback calls present but guarded:
- `invalidate_brief_cache`: import from `core.overview_editorial.brief_cache` — does not exist until B3. B2 ships with a **lazy import** inside the function body, wrapped in try/except ImportError that logs and continues. B3 landing makes the import resolve.
- `_invalidate_user_memory_cache`: import from `routes.gateway_proxy` — does not exist until B5. Same lazy import pattern. B5 landing makes it resolve.

This means B2 writers are callable from B4 (rotation) without B3/B5 existing — the cache invalidation just no-ops. When B3 and B5 land, the lazy imports resolve and invalidation fires. This is the honest dependency chain.

```python
# core/overview_editorial/editorial_state_store.py

import json
import logging
from pathlib import Path
from database import get_db_session

_logger = logging.getLogger(__name__)
_SEED_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "editorial_memory_seed.json"


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def load_editorial_state(user_id: int, portfolio_id: str | None) -> tuple[dict, dict | None]:
    """Returns (editorial_memory, previous_brief_anchor).
    Falls back to editorial_memory_seed.json if row doesn't exist or DB unavailable.
    previous_brief_anchor is extracted from previous_briefs->>portfolio_id (or 'default' if None)."""
    try:
        with get_db_session() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT editorial_memory, previous_briefs FROM user_editorial_state WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return _load_seed_fallback(), None
            editorial_memory = row["editorial_memory"] or {}
            previous_briefs = row["previous_briefs"] or {}
            key = portfolio_id or "default"
            anchor = previous_briefs.get(key)
            return editorial_memory, anchor
    except Exception:
        _logger.warning("editorial_state_db_miss for user %s", user_id, exc_info=True)
        return _load_seed_fallback(), None


def _editorial_state_row_exists(user_id: int) -> bool:
    """Direct row-exists check. Used by auto-seeder to skip expensive LLM calls.
    Does NOT fall back to seed — returns False if no row or DB unavailable."""
    try:
        with get_db_session() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM user_editorial_state WHERE user_id = %s",
                (user_id,),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _load_seed_fallback() -> dict:
    try:
        if _SEED_PATH.exists():
            return json.loads(_SEED_PATH.read_text())
    except Exception:
        _logger.warning("editorial_memory_seed_missing", exc_info=True)
    return {}


# ---------------------------------------------------------------------------
# Write path — chat-driven memory update
# ---------------------------------------------------------------------------

def set_editorial_memory(user_id: int, memory: dict) -> None:
    """Chat write path. Upsert editorial_memory; always replaces (last writer wins).
    Fires brief cache + gateway enricher cache invalidation."""
    with get_db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_editorial_state (user_id, editorial_memory, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET editorial_memory = EXCLUDED.editorial_memory,
                  updated_at = NOW()
            """,
            (user_id, json.dumps(memory)),
        )
        conn.commit()

    size_bytes = len(json.dumps(memory))
    if size_bytes > 10240:
        _logger.warning("editorial_memory > 10KB for user %s: %d bytes", user_id, size_bytes)

    _fire_invalidation_callbacks(user_id)

    _logger.info(
        "editorial_memory_updated",
        extra={"user_id": user_id, "source": "chat_tool", "memory_size_bytes": size_bytes},
    )


# ---------------------------------------------------------------------------
# Write path — auto-seed (insert-only, no clobber)
# ---------------------------------------------------------------------------

def seed_editorial_memory_if_missing(user_id: int, seed_memory: dict, log_extra: dict | None = None) -> bool:
    """Auto-seed write path. Inserts ONLY if no row exists (ON CONFLICT DO NOTHING).
    Returns True if row created, False if row already existed.
    Fires invalidation callbacks only on successful insert.

    log_extra: optional dict merged into the telemetry event (e.g., auto_seed_trigger,
    auto_seed_llm_duration_ms). Callers (B6 seeder) provide context B2 can't know."""
    with get_db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_editorial_state (user_id, editorial_memory, previous_briefs, updated_at)
            VALUES (%s, %s::jsonb, '{}'::jsonb, NOW())
            ON CONFLICT (user_id) DO NOTHING
            RETURNING user_id
            """,
            (user_id, json.dumps(seed_memory)),
        )
        inserted = cur.rowcount > 0
        conn.commit()

    if inserted:
        _fire_invalidation_callbacks(user_id)
        event = {"user_id": user_id, "source": "auto_seed", "memory_size_bytes": len(json.dumps(seed_memory))}
        if log_extra:
            event.update(log_extra)  # B6 passes auto_seed_trigger, auto_seed_llm_duration_ms, etc.
        _logger.info("editorial_memory_updated", extra=event)

    return inserted


# ---------------------------------------------------------------------------
# Write path — previous brief rotation (called by B4 action on each cold path)
# ---------------------------------------------------------------------------

def set_previous_brief(user_id: int, portfolio_id: str | None, brief: dict) -> None:
    """Store the just-generated brief as the anchor for the NEXT cold-path diff.
    Upserts into user_editorial_state.previous_briefs[portfolio_id] via jsonb_set.
    Does NOT invalidate caches — the brief is actively being generated."""
    key = portfolio_id or "default"
    with get_db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_editorial_state (user_id, previous_briefs, updated_at)
            VALUES (%s, jsonb_build_object(%s, %s::jsonb), NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET previous_briefs = jsonb_set(
                    COALESCE(user_editorial_state.previous_briefs, '{}'::jsonb),
                    ARRAY[%s],
                    %s::jsonb
                  ),
                  updated_at = NOW()
            """,
            (user_id, key, json.dumps(brief), key, json.dumps(brief)),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Invalidation helpers (lazy imports — callees land in B3 / B5)
# ---------------------------------------------------------------------------

def _fire_invalidation_callbacks(user_id: int) -> None:
    """Best-effort cache invalidation. Lazy imports because the callees live in
    later sub-phases (brief_cache in B3, gateway enricher cache in B5).
    If the import fails (sub-phase not yet landed), log and continue."""
    try:
        from core.overview_editorial.brief_cache import invalidate_brief_cache
        invalidate_brief_cache(user_id)
    except ImportError:
        _logger.debug("brief_cache not available yet (B3 not landed)")

    try:
        from routes.gateway_proxy import _invalidate_user_memory_cache
        _invalidate_user_memory_cache(user_id)
    except ImportError:
        _logger.debug("gateway enricher cache not available yet (B5 not landed)")
```

### 6.7b Diff computation

```python
# core/overview_editorial/diff.py

from models.overview_editorial import OverviewBrief


def compute_changed_slots(new_brief: OverviewBrief, previous_anchor: dict | None) -> list[str]:
    """Slot-level diff between new brief and previous anchor (from DB).
    Returns list of slot IDs that changed. Empty if no previous anchor (first generation)."""
    if previous_anchor is None:
        return []

    changed: list[str] = []

    # Metric strip: compare by stable id → flag if value or tone differs
    prev_metrics = {m["id"]: m for m in previous_anchor.get("metric_strip", []) if "id" in m}
    for item in new_brief.metric_strip:
        prev = prev_metrics.get(item.id)
        if prev is None:
            changed.append(f"metric.{item.id}")  # new metric
        elif prev.get("value") != item.value or prev.get("tone") != item.tone:
            changed.append(f"metric.{item.id}")

    # Lead insight: flag if headline differs
    prev_headline = previous_anchor.get("lead_insight", {}).get("headline", "")
    if new_brief.lead_insight.headline != prev_headline:
        changed.append("lead_insight")

    # Artifact directives: compare by artifact_id
    prev_directives = {
        d["artifact_id"]: d for d in previous_anchor.get("artifact_directives", []) if "artifact_id" in d
    }
    for directive in new_brief.artifact_directives:
        prev = prev_directives.get(directive.artifact_id)
        if prev is None or _directive_changed(directive, prev):
            changed.append(f"artifact.{directive.artifact_id}")

    # Margin annotations: compare by anchor_id
    prev_annotations = {
        a["anchor_id"]: a for a in previous_anchor.get("margin_annotations", []) if "anchor_id" in a
    }
    for annotation in new_brief.margin_annotations:
        prev = prev_annotations.get(annotation.anchor_id)
        if prev is None or prev.get("content") != annotation.content:
            changed.append(f"annotation.{annotation.anchor_id}")

    return changed


def _directive_changed(new, prev: dict) -> bool:
    return (
        new.annotation != prev.get("annotation")
        or new.visible != prev.get("visible", True)
        or new.position != prev.get("position", 0)
        or sorted(new.highlight_ids) != sorted(prev.get("highlight_ids", []))
    )
```

### 6.8 Implementation order

1. Create `core/overview_editorial/__init__.py`
2. Create `context.py` with `PortfolioContext` dataclass + helper methods + basic unit tests
3. Create `editorial_state_store.py` with ALL functions: `load_editorial_state` (read path + seed fallback), `set_editorial_memory` (chat write), `seed_editorial_memory_if_missing` (auto-seed write), `set_previous_brief` (rotation write), `_fire_invalidation_callbacks` (lazy imports)
4. Create `diff.py` with `compute_changed_slots()` + `_directive_changed()` helper
5. Create `orchestrator.py` with `gather_portfolio_context()` + the 3 normalization helpers
6. Write state store tests — load path, writers, seed idempotency, previous_brief JSONB upsert, invalidation callbacks (mocked)
7. Write diff tests — happy path, no anchor, metric change, lead change, directive change, annotation change
8. Write orchestrator tests with mocked `PositionService`, `get_analysis_result_snapshot`, `get_performance_result_snapshot`
9. Verify data_status flags correctly reflect worker success/failure
10. Verify the fan-out is actually parallel (timing assertion with time.sleep stubs)
11. Run full test suite: `pytest tests/core/overview_editorial/`

### 6.9 Test requirements

Target: 55+ tests. Coverage:

**`test_context.py`** (~8 tests):
- `PortfolioContext` construction happy path
- `tool_snapshot()` returns None for failed tool
- `tool_snapshot()` returns snapshot dict for loaded tool
- `tool_flags()` returns empty list for failed tool
- `tool_flags()` returns flags list for loaded tool
- Immutability (`@dataclass(frozen=True)` enforcement)
- Timezone-aware `generated_at`
- Missing tool name returns None/empty

**`test_orchestrator.py`** (~12 tests):
- Happy path: all 3 workers succeed �� PortfolioContext with 3 loaded tools
- Positions worker fails → `data_status["positions"] = "failed"`, positions absent from `tool_results`
- Risk worker fails → `data_status["risk"] = "failed"`
- Performance worker fails → `data_status["performance"] = "failed"`
- All 3 fail → PortfolioContext with empty tool_results, all failed
- Fan-out parallelism: 3 workers each sleeping 100ms → total <200ms (not 300ms)
- Normalization handles `get_agent_snapshot()` method missing gracefully
- `load_editorial_state` returns seed + None anchor → PortfolioContext has seed memory
- DB unavailable → seed fallback + None anchor
- `portfolio_id=None` → orchestrator uses "default" key for anchor lookup
- Normalization for positions (no canonical `get_agent_snapshot` today)
- Orchestrator returns `PortfolioContext` with `generated_at` timestamp in UTC

**`test_editorial_state_store.py`** (~25 tests):

*Load path (~10 tests):*
- Row present with populated memory + previous_briefs[portfolio_id] → returns (memory, anchor)
- Row present with empty previous_briefs → returns (memory, None)
- Row present, previous_briefs[portfolio_id] missing → returns (memory, None)
- Row absent → returns (seed_file, None)
- portfolio_id=None → looks up `previous_briefs["default"]`
- DB exception → returns (seed_file, None)
- Seed file missing → returns ({}, None)
- Seed file corrupt JSON → returns ({}, None)
- `previous_briefs` is non-JSONB (migration regression) → falls back gracefully
- Multiple portfolio IDs in previous_briefs → returns correct one per query

*Writer path — set_editorial_memory (~6 tests):*
- Creates row when missing
- Updates row when present (last write wins, ON CONFLICT DO UPDATE)
- Calls `_fire_invalidation_callbacks` (verified via mock — lazy imports may not resolve yet)
- Logs `editorial_memory_updated` with `source="chat_tool"` + `memory_size_bytes`
- Warns on >10KB memory (no rejection)
- Memory content round-trips through JSONB correctly

*Writer path — seed_editorial_memory_if_missing (~5 tests):*
- Creates row when missing → returns True
- No-op when row exists → returns False (ON CONFLICT DO NOTHING)
- Calls `_fire_invalidation_callbacks` only on successful insert
- Logs `editorial_memory_updated` with `source="auto_seed"` only on insert
- Race: `set` then `seed` → seed no-ops; `seed` then `set` → set always wins

*Writer path — set_previous_brief (~4 tests):*
- Creates row with initial previous_briefs map when row missing
- Upserts into existing row without clobbering other portfolio keys
- `portfolio_id=None` uses "default" key
- Does NOT call `_fire_invalidation_callbacks` (brief is being generated)

**`test_diff.py`** (~10 tests):
- `previous_anchor=None` → returns `[]`
- Metric value changed → `"metric.<id>"` in result
- Metric tone changed → `"metric.<id>"` in result
- New metric (not in anchor) → `"metric.<id>"` in result
- Lead headline changed → `"lead_insight"` in result
- Lead headline unchanged → `"lead_insight"` NOT in result
- New directive (not in anchor) → `"artifact.<id>"` in result
- Directive annotation changed → `"artifact.<id>"` in result
- Annotation content changed → `"annotation.<anchor_id>"` in result
- All unchanged → returns `[]`

### 6.10 Acceptance gate

- Orchestrator returns valid `PortfolioContext` on happy path with mocked data sources
- `data_status` correctly flags partial/failed workers
- Fan-out parallelism verified (timing assertion)
- `load_editorial_state` falls back to seed file when row missing or DB unavailable
- `previous_brief_anchor` correctly extracted from JSONB map by portfolio_id key
- `set_editorial_memory` creates/updates rows and fires invalidation callbacks
- `seed_editorial_memory_if_missing` is truly idempotent (DO NOTHING on existing row)
- `set_previous_brief` upserts into JSONB map without clobbering other portfolio keys
- `compute_changed_slots` returns correct slot IDs for changed vs unchanged briefs
- `compute_changed_slots` returns `[]` when `previous_anchor` is None
- All tests pass with `pytest tests/core/overview_editorial/`

### 6.11 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `PositionService.get_all_positions()` API shape doesn't match expectations | Medium | Verify signature before B2 starts; fix normalization helper if needed |
| `result_cache` snapshot shape differs per tool | Medium | Handle each normalizer independently; test per tool |
| Editorial memory loader races with concurrent chat writes | Low | Upsert semantics (DO UPDATE / DO NOTHING) — single-statement SQL, no read-modify-write window |
| ThreadPoolExecutor deadlocks if workers reuse same DB session | Low | Each worker gets its own session via `get_db_session()` context manager |

### 6.12 Rollback

Delete `core/overview_editorial/` directory + `tests/core/overview_editorial/` directory. No changes to existing files.

### 6.13 Manual smoke test

```bash
# Run all B2 tests
pytest tests/core/overview_editorial/ -v

# Smoke-test orchestrator (requires running DB with migration applied)
python -c "
from core.overview_editorial.orchestrator import gather_portfolio_context
ctx = gather_portfolio_context(user_email='founder@example.com', user_id=1, portfolio_id=None)
print(f'data_status: {ctx.data_status}')
print(f'memory keys: {list(ctx.editorial_memory.keys())}')
print(f'anchor present: {ctx.previous_brief_anchor is not None}')
"

# Smoke-test writers (requires running DB)
python -c "
from core.overview_editorial.editorial_state_store import set_editorial_memory, load_editorial_state, set_previous_brief
set_editorial_memory(1, {'version': 1, 'test': True})
mem, anchor = load_editorial_state(1, None)
print(f'memory after set: {mem}')
set_previous_brief(1, None, {'metric_strip': [], 'lead_insight': {'headline': 'test'}})
_, anchor = load_editorial_state(1, None)
print(f'anchor after rotation: {anchor is not None}')
"

# Smoke-test diff
python -c "
from core.overview_editorial.diff import compute_changed_slots
from models.overview_editorial import OverviewBrief, LeadInsight, EditorialMetadata, MetricStripItem
from datetime import datetime, timezone
brief = OverviewBrief(
    metric_strip=[MetricStripItem(id='return', title='Return', value='5.2%', tone='up')],
    lead_insight=LeadInsight(headline='Test headline'),
    editorial_metadata=EditorialMetadata(
        generated_at=datetime.now(timezone.utc), editorial_memory_version=1,
        candidates_considered=1, confidence='high', source='live',
    ),
)
print(f'diff vs None: {compute_changed_slots(brief, None)}')
print(f'diff vs changed: {compute_changed_slots(brief, {\"metric_strip\": [{\"id\": \"return\", \"value\": \"3.1%\", \"tone\": \"down\"}], \"lead_insight\": {\"headline\": \"Old\"}})}')
"
```

---

## 7. Sub-phase B3 — Generators + Policy Layer + Brief Cache

### 7.1 Goal

Build the editorial selection layer: 3 generators that produce `InsightCandidate[]` + a policy layer that ranks and selects + an in-memory brief cache with the unified invalidation helper.

### 7.2 Scope

- 3 generators (Concentration, Risk, Performance) under `core/overview_editorial/generators/`
- `EditorialPolicyLayer` with weighted additive scoring (arch spec §6.4)
- `brief_cache.py` with `TTLCache` + `invalidate_brief_cache()` that also calls `clear_result_snapshot_caches()` (L2 clear per §3.3)

**Out of scope**:
- LLM arbiter (in B4)
- Action layer (in B4)
- Route, MCP tool, gateway enricher (in B5)
- Auto-seeder (in B6)

### 7.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/generators/__init__.py` | Package init | ~5 |
| `core/overview_editorial/generators/base.py` | `InsightGenerator` Protocol | ~40 |
| `core/overview_editorial/generators/concentration.py` | Concentration generator | ~200 |
| `core/overview_editorial/generators/risk.py` | Risk generator | ~200 |
| `core/overview_editorial/generators/performance.py` | Performance generator | ~200 |
| `core/overview_editorial/policy.py` | `EditorialPolicyLayer` | ~180 |
| `core/overview_editorial/brief_cache.py` | `TTLCache` + invalidate helper | ~100 |
| `tests/core/overview_editorial/generators/test_concentration.py` | Concentration tests | ~150 |
| `tests/core/overview_editorial/generators/test_risk.py` | Risk tests | ~150 |
| `tests/core/overview_editorial/generators/test_performance.py` | Performance tests | ~150 |
| `tests/core/overview_editorial/test_policy.py` | Policy layer tests | ~200 |
| `tests/core/overview_editorial/test_brief_cache.py` | Cache tests | ~150 |

### 7.4 Files to modify

None.

### 7.5 `InsightGenerator` Protocol

**Restructured from round 1**: generators now produce three outputs — `InsightCandidate[]` for slot selection, `ArtifactDirective[]` for artifact editorial metadata, and `MarginAnnotation[]` for chat margin annotations. The §14 ship criteria require `directive_count avg ≥1` and `annotation_count avg ≥1` — generators that only emit slot candidates cannot satisfy this.

```python
# core/overview_editorial/generators/base.py

from dataclasses import dataclass
from typing import Protocol
from core.overview_editorial.context import PortfolioContext
from models.overview_editorial import InsightCandidate, ArtifactDirective, MarginAnnotation


@dataclass
class GeneratorOutput:
    """All outputs from a single generator run."""
    candidates: list[InsightCandidate]
    directives: list[ArtifactDirective]
    annotations: list[MarginAnnotation]


class InsightGenerator(Protocol):
    name: str

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        """Produce insight candidates + artifact directives + margin annotations.
        MUST NOT raise — return GeneratorOutput([], [], []) on any failure.
        Generators are responsible for defensive handling of their own tool output."""
        ...
```

### 7.6 Concentration generator (example shape)

**Stable metric slot IDs**: generators use the canonical IDs from the arch spec: `"return"`, `"volatility"`, `"diversification"`, `"beta"`, `"maxDrawdown"`, `"sharpe"`, `"alpha"`. Concentration uses `"diversification"` (HHI-based) as its primary metric slot. This is how the diff function tracks changes across generations.

**Directive/annotation emission**: each generator emits directives for the artifacts it owns (Concentration → `overview.concentration`) and margin annotations anchored to those artifacts and its slot candidates.

```python
# core/overview_editorial/generators/concentration.py

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators.base import GeneratorOutput
from models.overview_editorial import InsightCandidate, ArtifactDirective, MarginAnnotation

class ConcentrationGenerator:
    name = "concentration"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        positions_snapshot = context.tool_snapshot("positions")
        if positions_snapshot is None:
            return GeneratorOutput([], [], [])

        holdings = positions_snapshot.get("holdings", [])  # [{ticker, weight_pct, value, type}]
        if not holdings:
            return GeneratorOutput([], [], [])

        candidates: list[InsightCandidate] = []
        directives: list[ArtifactDirective] = []
        annotations: list[MarginAnnotation] = []

        # Lead insight candidate: single-name concentration
        top = max(holdings, key=lambda h: h.get("weight_pct", 0.0))
        if top.get("weight_pct", 0.0) >= 15.0:
            candidates.append(InsightCandidate(
                slot_type="lead_insight",
                category="concentration",
                content={
                    "headline": f"{top['ticker']} is {top['weight_pct']:.0f}% of the book",
                    "ticker": top["ticker"],
                    "weight_pct": top["weight_pct"],
                    "type": top.get("type"),  # asset type from normalized holdings
                },
                relevance_score=min(top["weight_pct"] / 30.0, 1.0),
                urgency_score=0.6,
                novelty_score=self._novelty_vs_previous(context.previous_brief_anchor, top["ticker"]),
                confidence=1.0,  # positions data is always available if snapshot present
                evidence=[f"{top['ticker']} weight {top['weight_pct']:.1f}%"],
                why="Single-name concentration over 15%",
                source_tool="get_positions",
            ))

        # Metric candidate: diversification (stable ID = "diversification")
        hhi = sum((h.get("weight_pct", 0) / 100) ** 2 for h in holdings)
        candidates.append(InsightCandidate(
            slot_type="metric",
            category="concentration",
            content={
                "id": "diversification",
                "title": "Diversification",
                "value": f"HHI {hhi:.2f}",
                "context_label": f"{len(holdings)} positions",
                "tone": "down" if hhi > 0.15 else "neutral",
            },
            relevance_score=min(hhi / 0.3, 1.0),
            urgency_score=0.4 if hhi > 0.15 else 0.2,
            novelty_score=0.5,
            confidence=1.0,
            evidence=[f"HHI = {hhi:.3f}"],
            why="Portfolio concentration metric",
            source_tool="get_positions",
        ))

        # Artifact directive for overview.concentration
        top_tickers = [h["ticker"] for h in sorted(holdings, key=lambda h: -h.get("weight_pct", 0))[:3]]
        directives.append(ArtifactDirective(
            artifact_id="overview.concentration",
            position=0,
            visible=True,
            annotation=f"Top holdings: {', '.join(top_tickers)}" if top_tickers else None,
            highlight_ids=[t for t in top_tickers if any(
                h["ticker"] == t and h.get("weight_pct", 0) >= 15 for h in holdings
            )],
        ))

        # Margin annotation: ask about concentration
        if top.get("weight_pct", 0.0) >= 10.0:
            annotations.append(MarginAnnotation(
                anchor_id="artifact.overview.concentration",
                type="ask_about",
                content=f"{top['ticker']} is {top['weight_pct']:.0f}% of the portfolio",
                prompt=f"What's the risk of having {top['weight_pct']:.0f}% in {top['ticker']}?",
            ))

        return GeneratorOutput(candidates, directives, annotations)

    def _novelty_vs_previous(self, previous: dict | None, ticker: str) -> float:
        if previous is None:
            return 1.0
        prev_lead = previous.get("lead_insight", {}).get("headline", "")
        return 0.3 if ticker in prev_lead else 0.8
```

Similar shape for `RiskGenerator` (wraps risk_snapshot from `_normalize_risk` — emits `"volatility"` metric candidate from `volatility_annual`, risk-driver attention items from `risk_drivers`, `overview.composition.asset_allocation` directive, risk-related margin annotations) and `PerformanceGenerator` (wraps perf_snapshot from `_normalize_performance` — emits `"return"` / `"sharpe"` / `"alpha"` / `"beta"` / `"maxDrawdown"` metric candidates from the normalized fields `total_return_pct`, `sharpe_ratio`, `alpha_annual_pct`, `beta`, `max_drawdown_pct` respectively, `overview.performance_attribution` directive, performance annotations).

**Metric ownership** (which generator owns which stable ID):
- **ConcentrationGenerator** (positions_snapshot): `"diversification"` (HHI)
- **RiskGenerator** (risk_snapshot): `"volatility"` (from `volatility_annual`)
- **PerformanceGenerator** (perf_snapshot): `"return"`, `"sharpe"`, `"alpha"`, `"beta"`, `"maxDrawdown"` (from `total_return_pct`, `sharpe_ratio`, `alpha_annual_pct`, `beta`, `max_drawdown_pct`)

### 7.7 Policy layer shape

```python
# core/overview_editorial/policy.py

from dataclasses import dataclass
from models.overview_editorial import InsightCandidate

@dataclass
class RankedCandidate:
    candidate: InsightCandidate
    composite_score: float
    memory_fit: float

class EditorialPolicyLayer:
    def rank(
        self,
        candidates: list[InsightCandidate],
        editorial_memory: dict,
        previous_brief: dict | None,
    ) -> list[RankedCandidate]:
        """Weighted additive scoring per arch spec §6.4:
        composite = 0.35*rel + 0.25*urg + 0.25*memory_fit + 0.15*nov"""
        ranked = []
        for candidate in candidates:
            memory_fit = self._compute_memory_fit(candidate, editorial_memory)
            composite = (
                0.35 * candidate.relevance_score
                + 0.25 * candidate.urgency_score
                + 0.25 * memory_fit
                + 0.15 * candidate.novelty_score
            )
            ranked.append(RankedCandidate(candidate, composite, memory_fit))
        ranked.sort(key=lambda rc: rc.composite_score, reverse=True)
        return ranked

    def _compute_memory_fit(self, candidate: InsightCandidate, memory: dict) -> float:
        """See arch spec OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md for the ladder:
          1.0 if category in memory.editorial_preferences.lead_with
          0.7 if category in memory.editorial_preferences.care_about
          0.1 if category in memory.editorial_preferences.less_interested_in
          0.3 default (candidate not in any list)"""
        prefs = memory.get("editorial_preferences", {})
        if candidate.category in prefs.get("lead_with", []):
            return 1.0
        if candidate.category in prefs.get("care_about", []):
            return 0.7
        if candidate.category in prefs.get("less_interested_in", []):
            return 0.1
        return 0.3

    def select_slots(self, ranked: list[RankedCandidate]) -> dict[str, list[RankedCandidate]]:
        """Top-N per slot_type: metric→6, lead_insight→1, attention_item→0-3."""
        metric = [rc for rc in ranked if rc.candidate.slot_type == "metric"][:6]
        lead = [rc for rc in ranked if rc.candidate.slot_type == "lead_insight"][:1]
        attention = [rc for rc in ranked if rc.candidate.slot_type == "attention_item"][:3]
        return {"metric": metric, "lead_insight": lead, "attention_item": attention}
```

### 7.8 Brief cache + invalidation

```python
# core/overview_editorial/brief_cache.py

from cachetools import TTLCache
from threading import Lock
from models.overview_editorial import OverviewBrief
from services.portfolio.result_cache import clear_result_snapshot_caches

_BRIEF_CACHE: TTLCache = TTLCache(maxsize=1000, ttl=3600)
_CACHE_LOCK = Lock()

def get_cached_brief(user_id: int, portfolio_id: str | None) -> OverviewBrief | None:
    key = (user_id, portfolio_id or "default")
    with _CACHE_LOCK:
        return _BRIEF_CACHE.get(key)

def set_cached_brief(user_id: int, portfolio_id: str | None, brief: OverviewBrief) -> None:
    key = (user_id, portfolio_id or "default")
    with _CACHE_LOCK:
        _BRIEF_CACHE[key] = brief

def invalidate_brief_cache(user_id: int) -> int:
    """Evict all brief cache entries for a user AND clear L2 result snapshot cache.
    The L2 clear is module-level (not user-scoped) — acceptable for Phase 1 because
    result cache entries are small and rebuild quickly under normal load.
    Returns number of brief cache entries evicted."""
    evicted = 0
    with _CACHE_LOCK:
        keys_to_evict = [k for k in _BRIEF_CACHE if k[0] == user_id]
        for k in keys_to_evict:
            del _BRIEF_CACHE[k]
            evicted += 1
    clear_result_snapshot_caches()
    return evicted
```

### 7.9 Implementation order

1. Create `generators/__init__.py` and `generators/base.py` with Protocol
2. Write `concentration.py` first (simpler starting point) + its unit tests
3. Write `risk.py` + unit tests
4. Write `performance.py` + unit tests
5. Write `policy.py` + unit tests (including memory_fit ladder)
6. Write `brief_cache.py` + unit tests (TTL, invalidation, L2 clear)
7. Run full test suite, confirm green
8. Manual sanity check: with a fixed portfolio fixture, verify each generator produces reasonable candidates

### 7.10 Test requirements

Target: 50+ tests.

**Generators (~12 tests each × 3 = 36 tests):**
- Happy path (expected candidates + directives + annotations for fixture portfolio)
- Empty input (no positions / no risk / no performance) → `GeneratorOutput([], [], [])`
- `data_status == "failed"` for relevant tool → `GeneratorOutput([], [], [])`
- Missing snapshot keys → defensive fallback (empty output, no exception)
- Candidate score bounds (0 ≤ score ≤ 1)
- Novelty scoring when `previous_brief_anchor` is None
- Novelty scoring when `previous_brief_anchor` has the same candidate
- Category label matches spec
- `source_tool` matches spec
- Candidate `content.id` uses stable metric IDs ("return", "volatility", "diversification", "beta", "maxDrawdown", "sharpe", "alpha")
- At least 1 `ArtifactDirective` emitted for owned artifact ID (e.g., `overview.concentration`)
- At least 1 `MarginAnnotation` emitted when data warrants it (e.g., top holding ≥10%)

**Policy (~10 tests):**
- Rank a fixed candidate set, verify ordering
- Memory fit: `lead_with` → 1.0, `care_about` → 0.7, `less_interested_in` → 0.1, default → 0.3
- Tie-breaking is deterministic (stable sort)
- `select_slots` top-N counts: metric=6, lead_insight=1, attention_item=0-3
- Empty candidate list → empty output, no error
- All candidates same category → still ranks correctly
- Mixed categories → interleaved correctly
- Memory_fit with empty `editorial_preferences` → default 0.3
- Weights sum to 1.0
- Composite score is bounded [0, 1]

**Brief cache (~8 tests):**
- Set + get round-trip
- TTL expiry (with mocked time)
- `invalidate_brief_cache(user_id)` evicts all portfolios for that user
- Invalidation of user A does not affect user B
- Invalidation calls `clear_result_snapshot_caches()` (verified via mock)
- Key is `(user_id, portfolio_id or "default")`
- Concurrent access doesn't corrupt state (simple thread safety test)
- `get_cached_brief` returns None when key missing

### 7.11 Acceptance gate

- All 3 generators produce valid `InsightCandidate[]` for a fixed fixture portfolio
- Each generator gracefully handles missing/failed input
- Policy scores are deterministic for fixed inputs
- Memory fit ladder correct per arch spec §6.4
- Brief cache TTL works
- `invalidate_brief_cache` evicts correctly AND triggers L2 clear

### 7.12 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Generator scoring feels wrong in practice (qualitative) | High | Expected — tune weights in Phase 2 after telemetry |
| Concentration generator's threshold (15% weight) is arbitrary | Medium | Document as tunable; Phase 2 adds configuration |
| Performance generator needs YTD + drawdown + Sharpe all available | Medium | Defensive null handling — emit what's available |
| Risk generator's factor exposure candidates may be verbose | Low | Limit to top-3 factors per candidate |
| `clear_result_snapshot_caches()` is not user-scoped, may over-evict | Low | Acceptable for Phase 1; Phase 2 adds scoping |
| `TTLCache` thread safety under high concurrency | Low | Use `Lock()` for writes; reads are safe |

### 7.13 Rollback

Delete `core/overview_editorial/generators/` + `policy.py` + `brief_cache.py` + associated tests. No upstream dependencies.

### 7.14 Manual smoke test

```python
# Repl smoke test
from core.overview_editorial.orchestrator import gather_portfolio_context
from core.overview_editorial.generators.concentration import ConcentrationGenerator
from core.overview_editorial.generators.risk import RiskGenerator
from core.overview_editorial.generators.performance import PerformanceGenerator
from core.overview_editorial.policy import EditorialPolicyLayer

ctx = gather_portfolio_context(user_email='founder@example.com', user_id=1, portfolio_id=None)
gens = [ConcentrationGenerator(), RiskGenerator(), PerformanceGenerator()]
all_outputs = [g.generate(ctx) for g in gens]
all_candidates = [c for o in all_outputs for c in o.candidates]
all_directives = [d for o in all_outputs for d in o.directives]
all_annotations = [a for o in all_outputs for a in o.annotations]
print(f"Total candidates: {len(all_candidates)}, directives: {len(all_directives)}, annotations: {len(all_annotations)}")

policy = EditorialPolicyLayer()
ranked = policy.rank(all_candidates, ctx.editorial_memory, ctx.previous_brief_anchor)
slots = policy.select_slots(ranked)
print(f"Selected: metric={len(slots['metric'])}, lead={len(slots['lead_insight'])}, attention={len(slots['attention_item'])}")
for rc in slots['lead_insight']:
    print(f"Lead: {rc.candidate.category} — score {rc.composite_score:.3f}")
```

---

## 8. Sub-phase B4 — Action Layer + LLM Arbiter (Transport-Neutral)

### 8.1 Goal

Build the transport-neutral action that composes the full pipeline: orchestrator → generators → policy → brief composition → diff → cache → rotation → arbiter callback. The action does NOT import FastAPI, does NOT dispatch BackgroundTasks, and does NOT mount routes. Those belong in B5.

**Architecture boundary rule** (from `tests/test_architecture_boundaries.py:200-211`): `actions/` MUST NOT import `fastapi` or `mcp_tools`. The action layer is transport-neutral — it returns the brief + a callable for the arbiter; the transport layer (B5) dispatches.

### 8.2 Scope

- `actions/overview_brief.py` — business action returning `(OverviewBrief, Callable | None)` where the callable is the arbiter enhancement to be dispatched by the caller
- `core/overview_editorial/llm_arbiter.py` — enhancement logic (accepts brief + memory, returns enhanced brief or None)

**ActionError convention**: the existing `actions/errors.py` only defines plain marker exception classes (no structured fields). The route needs a structured error with `http_status` and a dict payload. Two options during implementation:
1. **Extend `actions/errors.py`**: add a `BriefPipelineError(Exception)` with `http_status: int` and `detail: dict` attributes. The route catches it and maps to `HTTPException`.
2. **Use existing marker pattern**: define `BriefPipelineError` and `BriefNoCandidatesError` as plain exceptions, and have the route map each to a specific HTTP status (matching the pattern in `routes/income.py:29`).

The plan's code examples now use `BriefPipelineError` / `BriefNoCandidatesError` marker exceptions, matching the existing pattern (e.g., `routes/income.py:29`). The route catches each by type and maps to HTTP 503. Key contract: data-source all-fail → 503, no-candidates → 503, auth missing → 401.
- Structured logging: `overview_brief_generated` event emitted on every cold-path generation, `overview_brief_enhanced` event on arbiter completion
- `set_previous_brief` rotation (full implementation, not a stub — B2 ships the helper)

**NOT in scope** (moved to B5):
- `routes/overview.py` — lives in B5 (transport layer)
- `app.py` router registration — lives in B5
- `BackgroundTasks` dispatch — lives in B5 (route calls `background_tasks.add_task(arbiter_callback)`)

**Auth convention**: action receives `user_email: str` and `user_id: int` as explicit parameters (not a dict, not a FastAPI dependency). The route (B5) extracts these from the auth dict and passes them in.

### 8.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `actions/overview_brief.py` | Business action (cold + warm paths + rotation) — NO FastAPI imports | ~250 |
| `core/overview_editorial/llm_arbiter.py` | Arbiter enhancement logic (accepts brief + memory, returns enhanced or None) | ~200 |
| `tests/actions/test_overview_brief.py` | Action integration test | ~300 |
| `tests/core/overview_editorial/test_llm_arbiter.py` | Arbiter unit tests | ~200 |

**Not in this sub-phase** (moved to B5): `routes/overview.py`, `app.py` router mount, `tests/routes/test_overview.py`.

### 8.4 Files to modify

| File | Change |
|---|---|
| `actions/errors.py` | Add `BriefPipelineError` and `BriefNoCandidatesError` marker exception classes (plain `Exception` subclasses, matching existing pattern) |

### 8.5 `actions/overview_brief.get_brief` shape

**Transport-neutral**: the action does NOT import `fastapi`, does NOT accept `BackgroundTasks`, and does NOT dispatch the arbiter. It returns `(OverviewBrief, Callable | None)` — the brief and an optional arbiter callback. The transport layer (B5 route) dispatches the callback via `BackgroundTasks`.

This satisfies `tests/test_architecture_boundaries.py:200-211` which forbids `actions/` → `fastapi` imports.

```python
# actions/overview_brief.py
# NOTE: NO fastapi imports — this module is transport-neutral

from datetime import datetime, timezone
from typing import Callable

from core.overview_editorial.orchestrator import gather_portfolio_context
from core.overview_editorial.generators.concentration import ConcentrationGenerator
from core.overview_editorial.generators.risk import RiskGenerator
from core.overview_editorial.generators.performance import PerformanceGenerator
from core.overview_editorial.policy import EditorialPolicyLayer
from core.overview_editorial.brief_cache import get_cached_brief, set_cached_brief
from core.overview_editorial.editorial_state_store import set_previous_brief
from core.overview_editorial.llm_arbiter import LLMArbiter
from core.overview_editorial.diff import compute_changed_slots
from models.overview_editorial import OverviewBrief
from actions.errors import BriefPipelineError, BriefNoCandidatesError

_GENERATORS = [ConcentrationGenerator(), RiskGenerator(), PerformanceGenerator()]
_POLICY = EditorialPolicyLayer()

def get_brief(
    user_email: str,
    user_id: int,
    portfolio_id: str | None,
) -> tuple[OverviewBrief, Callable | None]:
    """Returns (brief, arbiter_callback_or_None). Caller dispatches the callback.

    The action is synchronous (orchestrator uses ThreadPoolExecutor internally).
    The arbiter callback, if returned, should be dispatched via BackgroundTasks
    by the transport layer.
    """
    # Warm path
    cached = get_cached_brief(user_id, portfolio_id)
    if cached is not None:
        _log_brief_event(user_id, portfolio_id, cached, cache_state="hit")
        return cached, None  # no arbiter needed on cache hit

    # Cold path
    context = gather_portfolio_context(
        user_email=user_email,
        user_id=user_id,
        portfolio_id=portfolio_id,
    )
    if all(status == "failed" for status in context.data_status.values()):
        raise BriefPipelineError("All data sources failed for user")

    # Run generators — collect candidates + directives + annotations
    all_candidates: list = []
    all_directives: list = []
    all_annotations: list = []
    for gen in _GENERATORS:
        output = gen.generate(context)
        all_candidates.extend(output.candidates)
        all_directives.extend(output.directives)
        all_annotations.extend(output.annotations)

    # If all generators returned empty, there's nothing to compose → 503
    if not all_candidates:
        raise BriefNoCandidatesError("All generators returned empty — no brief to compose")

    ranked = _POLICY.rank(all_candidates, context.editorial_memory, context.previous_brief_anchor)
    slots = _POLICY.select_slots(ranked)

    new_brief = _compose_brief(slots, all_directives, all_annotations, context)

    # Diff against previous anchor (from DB read at orchestrator step)
    new_brief.editorial_metadata.changed_slots = compute_changed_slots(
        new_brief, context.previous_brief_anchor
    )

    # Cache write
    set_cached_brief(user_id, portfolio_id, new_brief)

    # Rotate: the NEW brief becomes the anchor for the NEXT cold generation
    set_previous_brief(user_id, portfolio_id, new_brief.model_dump())

    # Telemetry: lead_insight_category comes from the winning candidate's category field.
    # The selected lead's category is available from the ranked output.
    lead_category = slots["lead_insight"][0].candidate.category if slots.get("lead_insight") else None
    _log_brief_event(
        user_id, portfolio_id, new_brief,
        cache_state="miss",
        data_status=context.data_status,
        lead_insight_category=lead_category,
        duration_ms=int((datetime.now(timezone.utc) - context.generated_at).total_seconds() * 1000),
    )

    # Build the arbiter callback (caller dispatches via BackgroundTasks)
    arbiter = LLMArbiter()
    arbiter_callback = lambda: arbiter.enhance_and_replace(
        user_id, portfolio_id, new_brief, context.editorial_memory
    )

    return new_brief, arbiter_callback

def _compose_brief(slots: dict, directives: list, annotations: list, context) -> OverviewBrief:
    """Assemble the deterministic OverviewBrief from ranked candidates + directives + annotations."""
    ...

def _log_brief_event(
    user_id: int,
    portfolio_id: str | None,
    brief: OverviewBrief,
    cache_state: str,
    data_status: dict[str, str] | None = None,
    lead_insight_category: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Emit overview_brief_generated on both cache hit and miss paths.
    Per arch spec §10.1: cache_state, data_status, lead_insight_category,
    directive_count, annotation_count, changed_slots_count, duration_ms.

    On cache hit, data_status/lead_insight_category/duration_ms are not available
    (the brief was generated in a prior request). The event still fires for
    request-level telemetry (cache_state=hit, user_id, portfolio_id).
    """
    import logging
    logging.getLogger(__name__).info(
        "overview_brief_generated",
        extra={
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "cache_state": cache_state,
            "data_status": data_status,  # None on cache hit
            "lead_insight_category": lead_insight_category,  # None on cache hit
            "candidates_considered": brief.editorial_metadata.candidates_considered,
            "directive_count": len(brief.artifact_directives),
            "annotation_count": len(brief.margin_annotations),
            "changed_slots_count": len(brief.editorial_metadata.changed_slots),
            "confidence": brief.editorial_metadata.confidence,
            "llm_enhanced": brief.editorial_metadata.llm_enhanced,
            "duration_ms": duration_ms,  # None on cache hit
        },
    )
```

### 8.7 LLM arbiter shape

```python
# core/overview_editorial/llm_arbiter.py

import logging
import os
from models.overview_editorial import OverviewBrief
from core.overview_editorial.brief_cache import set_cached_brief
from core.overview_editorial.diff import compute_changed_slots
from providers.completion import get_completion_provider

_logger = logging.getLogger(__name__)

_EDITORIAL_MODEL = os.environ.get("EDITORIAL_LLM_MODEL")  # e.g., "claude-haiku-4-5-20251001" or "gpt-4o-mini"
# If not set, use the provider's default model (CompletionProvider picks its own default)

class LLMArbiter:
    def __init__(self, model: str | None = _EDITORIAL_MODEL, timeout_s: float = 10.0):
        self.model = model  # None → provider uses its default
        self.timeout_s = timeout_s
        self._provider = get_completion_provider()

    def enhance_and_replace(
        self,
        user_id: int,
        portfolio_id: str | None,
        deterministic_brief: OverviewBrief,
        editorial_memory: dict,
    ) -> None:
        """Called via BackgroundTasks. Rewrites the brief in analyst voice and replaces cache."""
        try:
            prompt = self._build_prompt(deterministic_brief, editorial_memory)
            response_text = self._provider.complete(
                prompt=prompt,
                model=self.model,
                timeout=self.timeout_s,
                max_tokens=2000,
            )
            enhanced = OverviewBrief.model_validate_json(response_text)
            enhanced.editorial_metadata.llm_enhanced = True
            # Rerun diff with the same anchor (diff result is consistent across det + enhanced)
            enhanced.editorial_metadata.changed_slots = (
                deterministic_brief.editorial_metadata.changed_slots
            )
            set_cached_brief(user_id, portfolio_id, enhanced)
            _logger.info(
                "overview_brief_enhanced",
                extra={
                    "user_id": user_id,
                    "portfolio_id": portfolio_id,
                    "llm_model": self.model,
                    "parse_success": True,
                },
            )
        except Exception as exc:
            _logger.warning(
                "llm_arbiter_failed for user %s: %s", user_id, exc,
                exc_info=True,
            )
            # Deterministic brief stands in cache; no replacement.

    def _build_prompt(self, brief: OverviewBrief, memory: dict) -> str:
        return f"""You are rewriting an investment briefing in the analyst's voice.
The deterministic brief is:
{brief.model_dump_json(indent=2)}

The user's editorial_memory is:
{memory}

Rewrite the lead_insight.headline and metric_strip items in analyst voice.
Do NOT change artifact_directives, margin_annotations, or the overall structure.
Return valid JSON matching the OverviewBrief schema.
"""
```

### 8.8 Implementation order

1. `llm_arbiter.py` — write the class + `enhance_and_replace` method + prompt template
2. `actions/overview_brief.py` — write `get_brief` function returning `(OverviewBrief, Callable | None)`. Uses `set_previous_brief` from B2 (already landed). Collects `GeneratorOutput` (candidates + directives + annotations) from generators.
3. Write action integration tests with all mocks (orchestrator, generators, arbiter, cache)
4. Write arbiter unit tests (mocked `CompletionProvider`)
5. Verify: `import actions.overview_brief` does NOT trigger any `fastapi` import (architecture boundary)
6. Run full test suite
7. Manual smoke test: call `get_brief()` directly from a Python repl with mocked data

### 8.9 Test requirements

Target: 25+ tests.

**Action tests (~17 tests):**
- Cache hit → returns `(cached_brief, None)` — no orchestrator call, no arbiter callback
- Cache miss → full cold path → returns `(composed_brief, arbiter_callback)`
- All tools failed ��� `BriefPipelineError` raised → route catches by type → 503
- Partial tool failure → brief composed with fewer candidates, no error
- `previous_brief_anchor = None` → diff returns empty `changed_slots`
- `previous_brief_anchor = {...}` → diff returns correct `changed_slots`
- Rotation: `set_previous_brief` called with the new brief after cache write
- Arbiter callback is a callable (not None) on cold path
- Calling the arbiter callback invokes `arbiter.enhance_and_replace` with correct args
- `get_brief()` does NOT import `fastapi` (verified via `sys.modules` check or architecture boundary test)
- `get_brief()` accepts `user_email` as first arg (PositionService requires it)
- Generator outputs collected correctly: candidates + directives + annotations from all 3 generators
- Editorial memory empty → policy layer defaults work
- Editorial memory present → memory_fit applied to candidates
- Multi-portfolio: different portfolio_id → different cache key
- `editorial_metadata.candidates_considered` matches candidate count
- `selection_reasons` populated

**Route tests** — moved to B5. B4 does NOT create `routes/overview.py`.

**Arbiter tests (~8 tests):**
- Happy path: valid JSON → enhanced brief replaces cache
- Parse failure (malformed JSON) → no replacement, log warning
- Timeout → no replacement, log warning
- Provider raises exception → no replacement, log warning
- `parse_success=True` log on success
- `parse_success=False` log on failure
- Diff preserved from deterministic brief (not recomputed)
- `llm_enhanced=True` flag set on enhanced brief

### 8.10 Acceptance gate

- `get_brief()` returns `(OverviewBrief, Callable)` on cold path, `(OverviewBrief, None)` on cache hit
- `import actions.overview_brief` does NOT import `fastapi` (run `python -c "import actions.overview_brief; import sys; assert 'fastapi' not in sys.modules"`)
- Cache miss triggers cold path with generator output collection (candidates + directives + annotations)
- Deterministic brief always returned even when arbiter is mocked to fail
- `previous_brief_anchor` rotated on each cold path (verified via test)
- `BriefPipelineError` / `BriefNoCandidatesError` raised → route maps to 503
- Arbiter callback callable returns without error when invoked

### 8.11 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `previous_brief` rotation logic drift (has 3 rounds of review history) | Medium | Write the rotation test FIRST, then implement |
| `CompletionProvider` JSON parsing drift | Medium | Strict Pydantic validation catches any shape change |
| `BackgroundTasks` lifecycle (task runs after response returned) | Low | Use `FastAPI`'s `BackgroundTasks` dependency, verified pattern |
| Router mount conflicts with existing routes | Low | Verify `/api/overview/brief` is not already registered |
| LLM arbiter timeout + retry → excessive load | Low | Phase 1 has no retry; arbiter fails silently |
| `set_previous_brief` signature drift between B2 and B4 | Low | B4 imports from B2 directly; verified signature in checkpoint |

### 8.12 Rollback

Delete `actions/overview_brief.py` and `core/overview_editorial/llm_arbiter.py`. No route or `app.py` changes to revert (those are in B5). Frontend's React Query `useOverviewBrief` onError fires → TS fallback renders normally.

### 8.13 Manual smoke test

```bash
# Run action + arbiter tests
pytest tests/actions/test_overview_brief.py tests/core/overview_editorial/test_llm_arbiter.py -v

# Verify architecture boundary (NO fastapi imports)
python -c "
import sys
import actions.overview_brief
assert 'fastapi' not in sys.modules, 'actions/overview_brief.py imports fastapi!'
print('Architecture boundary OK: no fastapi import in actions/')
"

# Repl smoke test (with mocked data — requires B1-B3 landed)
python -c "
from actions.overview_brief import get_brief
brief, callback = get_brief(user_email='founder@example.com', user_id=1, portfolio_id=None)
print(f'Brief lead: {brief.lead_insight.headline}')
print(f'Metrics: {len(brief.metric_strip)}')
print(f'Directives: {len(brief.artifact_directives)}')
print(f'Annotations: {len(brief.margin_annotations)}')
print(f'Arbiter callback: {callback is not None}')
print(f'Changed slots: {brief.editorial_metadata.changed_slots}')
"
```

---

## 9. Sub-phase B5 — Transport Layer: Route + MCP Tool + Gateway Enricher + BackgroundTasks + Founder Bootstrap

### 9.1 Goal

All FastAPI/HTTP/MCP transport surfaces. The REST endpoint for the brief, the MCP tool for chat-driven memory updates, the gateway enricher extension for per-user memory, BackgroundTasks dispatch for the LLM arbiter, and the founder bootstrap script.

**Restructured from round 1 review**: the original plan had B5 own the state store writers. Those now live in B2 (data layer). B5 is purely the transport surface that calls into the data + action layers.

### 9.2 Scope

**Restructured from round 1**: original plan had B5 own the state store writers. Those now live in B2 (data layer). B5 is purely the transport surface — it takes the B4 action output and wires it to HTTP, MCP, and gateway enricher.

- New: `routes/overview.py` — `GET /api/overview/brief` with auth + BackgroundTasks (moved from B4)
- Modify: `app.py` — mount `overview_router`
- New: `mcp_tools/overview_editorial.py` — `update_editorial_memory` tool (user identity via `user_email` parameter, NOT `ctx.user`)
- Modify: `routes/gateway_proxy.py` — `_load_user_memory_cached`, `_invalidate_user_memory_cache`, `_enrich_context` extension
- New: `scripts/seed_founder_editorial_memory.py`
- Create or modify: `config/skills/morning-briefing.md` — add "Maintaining editorial_memory" section (file may not exist yet — create it if needed, following the skill prompt format used by the analyst chat)
- Register `update_editorial_memory` in MCP tool registry

**Auth convention** (verified via code investigation): `app_platform/auth/dependencies.py:14-27` returns a dict. Routes access `user["user_id"]` and `user["email"]` as dict keys. The route extracts these and passes them to the B4 action as explicit parameters.

**MCP tool convention** (verified): existing MCP tools receive `user_email` as a function parameter, not via a context object. The MCP harness resolves the session user and passes `user_email` to the function.

### 9.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `routes/overview.py` | REST endpoint `GET /api/overview/brief` with auth + BackgroundTasks dispatch | ~80 |
| `mcp_tools/overview_editorial.py` | `update_editorial_memory` MCP tool | ~80 |
| `scripts/seed_founder_editorial_memory.py` | One-off founder bootstrap | ~60 |
| `tests/routes/test_overview.py` | Route tests (moved from B4) | ~200 |
| `tests/mcp_tools/test_update_editorial_memory.py` | MCP tool test | ~150 |
| `tests/routes/test_gateway_proxy_enricher.py` | Enricher cache tests | ~200 |

### 9.4 Files to modify

| File | Change |
|---|---|
| `app.py` | Mount `overview_router` from `routes/overview.py` |
| `routes/gateway_proxy.py:23-36` | Extend `_enrich_context` with per-process cache helpers (`_load_user_memory_cached`, `_invalidate_user_memory_cache`) |
| `config/skills/morning-briefing.md` | Create or modify — add "Maintaining editorial_memory" section (file may not exist yet) |
| MCP tool registry config | Register `update_editorial_memory` |
| `mcp_tools/__init__.py` (or equivalent) | Export the new tool |

**NOT in this sub-phase**: State store writers (`set_editorial_memory`, `seed_editorial_memory_if_missing`, `set_previous_brief`) — these already landed in B2.

### 9.5 Route shape (moved from B4 — this is the transport layer)

The route extracts auth fields from the dict and dispatches the arbiter callback via `BackgroundTasks`. The B4 action returns `(brief, callback)` — the route unpacks it.

**Auth dict access** (verified at `app_platform/auth/dependencies.py:14-27`): `user["user_id"]` and `user["email"]`, NOT `user.id`.

```python
# routes/overview.py

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from actions import overview_brief
from actions.errors import BriefPipelineError, BriefNoCandidatesError  # marker exceptions
from app_platform.auth.dependencies import create_auth_dependency
from models.overview_editorial import OverviewBrief

overview_router = APIRouter()

# Auth dependency follows the existing route pattern (e.g., routes/factor_intelligence.py:44)
# The actual auth_service instance is wired at app startup in app.py when mounting the router.
# For the plan, show the pattern:
# get_current_user = create_auth_dependency(auth_service)

@overview_router.get("/api/overview/brief", response_model=OverviewBrief)
async def get_overview_brief(
    background_tasks: BackgroundTasks,
    portfolio_id: str | None = None,
    user: dict = Depends(get_current_user),
) -> OverviewBrief:
    try:
        brief, arbiter_callback = overview_brief.get_brief(
            user_email=user["email"],
            user_id=user["user_id"],
            portfolio_id=portfolio_id,
        )
        # Dispatch the arbiter callback if present (cold path only)
        if arbiter_callback is not None:
            background_tasks.add_task(arbiter_callback)
        return brief
    except (BriefPipelineError, BriefNoCandidatesError) as e:
        raise HTTPException(status_code=503, detail={"error": str(e)})
```

**Implementation note**: `get_current_user` is created via `create_auth_dependency(auth_service)` at module scope, following the pattern in `routes/factor_intelligence.py:44`. The exact wiring depends on how `auth_service` is passed to the router — trace the existing pattern during implementation.

### 9.6 MCP tool shape

```python
# mcp_tools/overview_editorial.py

import json
from typing import Any
from core.overview_editorial.editorial_state_store import set_editorial_memory
from mcp_tools.common import handle_mcp_errors, require_db
from utils.user_resolution import resolve_user_id

@handle_mcp_errors
@require_db
def update_editorial_memory(
    new_memory: dict[str, Any],
    user_email: str,  # MCP harness resolves session user and passes this
) -> dict[str, Any]:
    """Replace the current user's editorial memory with new_memory.

    The current memory is available in your chat context under `editorial_memory`.
    Read it, merge your changes, and pass the full updated blob as new_memory.
    The memory captures how the user thinks about investing — goals, style,
    risk tolerance, what they care about, what they ignore, current focus,
    recent actions, upcoming watchpoints.

    Update it when the user tells you something worth remembering. Examples:
    - "I only care about concentration risk, not daily P&L" → update editorial_preferences
    - "I just harvested losses in BABA" → append to current_focus.recent_actions
    - "Actually I don't care about dividends anymore" → update editorial_preferences

    Keep memory under ~10KB. Prune oldest conversation_extracts if needed.
    """
    user_id = resolve_user_id(user_email)
    set_editorial_memory(user_id, new_memory)
    return {
        "status": "ok",
        "memory_size_bytes": len(json.dumps(new_memory)),
    }
```

### 9.7 Gateway enricher extension

```python
# routes/gateway_proxy.py — extended

import json
import logging
from pathlib import Path
from core.overview_editorial.editorial_state_store import load_editorial_state

_logger = logging.getLogger(__name__)
_SEED_PATH = Path(__file__).resolve().parent.parent / "config" / "editorial_memory_seed.json"

# Process-local cache: avoids DB hit on every chat message.
# Invalidated by BOTH set_editorial_memory AND seed_editorial_memory_if_missing
# via _invalidate_user_memory_cache.
_MEMORY_CACHE: dict[int, dict] = {}

def _load_user_memory_cached(user_id: int) -> dict:
    if user_id not in _MEMORY_CACHE:
        memory, _ = load_editorial_state(user_id, portfolio_id=None)
        _MEMORY_CACHE[user_id] = memory
    return _MEMORY_CACHE[user_id]

def _invalidate_user_memory_cache(user_id: int) -> None:
    """Called by set_editorial_memory AND seed_editorial_memory_if_missing after DB upsert."""
    _MEMORY_CACHE.pop(user_id, None)

def _enrich_context(request, user, context):
    user_id = getattr(user, "id", None) or (user.get("user_id") if isinstance(user, dict) else None)
    if user_id:
        try:
            context["editorial_memory"] = _load_user_memory_cached(user_id)
        except Exception:
            _logger.warning("editorial_memory DB read failed for user %s", user_id, exc_info=True)
            if _SEED_PATH.exists():
                context["editorial_memory"] = json.loads(_SEED_PATH.read_text())
    elif _SEED_PATH.exists():
        context["editorial_memory"] = json.loads(_SEED_PATH.read_text())
    return context
```

### 9.8 Analyst skill prompt update

Add this section to `config/skills/morning-briefing.md`:

> **Maintaining editorial_memory**
>
> You have access to `editorial_memory` in your context. It captures how this user thinks about investing. You also have a tool `update_editorial_memory(new_memory)` that writes to it.
>
> Update memory when the user tells you something worth remembering about their preferences, goals, risk tolerance, focus, or recent actions. You decide when — no confirmation needed. Read the current memory, merge your changes, pass the full updated blob.
>
> If memory grows past ~10KB, prune the oldest `conversation_extracts` entries.
>
> If the user corrects something ("actually I don't care about dividends"), update memory accordingly.

### 9.9 Founder bootstrap script

```python
# scripts/seed_founder_editorial_memory.py

"""One-off script to seed user_id=1 (founder) with the current editorial_memory_seed.json.
Runs outside of normal application flow — called manually after the first migration lands
and the founder account exists."""

import json
import sys
from pathlib import Path
from core.overview_editorial.editorial_state_store import seed_editorial_memory_if_missing

SEED_PATH = Path(__file__).resolve().parent.parent / "config" / "editorial_memory_seed.json"

def main():
    founder_user_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    if not SEED_PATH.exists():
        print(f"ERROR: seed file not found at {SEED_PATH}")
        sys.exit(1)

    seed = json.loads(SEED_PATH.read_text())
    inserted = seed_editorial_memory_if_missing(founder_user_id, seed)
    if inserted:
        print(f"Seeded founder user_id={founder_user_id} with editorial_memory_seed.json")
    else:
        print(f"Founder user_id={founder_user_id} already has a user_editorial_state row — no change")

if __name__ == "__main__":
    main()
```

### 9.10 Implementation order

1. Write `routes/overview.py` — REST endpoint that calls B4 action, unpacks `(brief, callback)`, dispatches callback via `BackgroundTasks`. Auth via `user["user_id"]` / `user["email"]` dict access.
2. Mount `overview_router` in `app.py`
3. Update `gateway_proxy.py` with `_load_user_memory_cached` + `_invalidate_user_memory_cache` + extended `_enrich_context`
4. Write `mcp_tools/overview_editorial.py` (receives `user_email` parameter) + register in MCP tool registry
5. Write `scripts/seed_founder_editorial_memory.py`
6. Add the skill prompt section to `morning-briefing.md`
7. Write tests (route, MCP tool, gateway enricher)
8. Run full suite
9. Manual smoke test: `curl /api/overview/brief`, founder bootstrap, chat-driven memory update

**Lazy import resolution**: B2's writer functions use lazy imports to call `_invalidate_user_memory_cache` from `gateway_proxy.py`. Now that B5 lands the gateway enricher, the lazy imports resolve and invalidation fires on every writer call. Verify this with an integration test that calls `set_editorial_memory` and asserts the gateway cache is cleared.

### 9.11 Test requirements

Target: 30+ tests.

**Route tests (~13 tests — moved from B4):**
- GET without auth → 401
- GET with valid auth, happy path → 200 + valid `OverviewBrief` JSON
- GET with valid auth, pipeline failure (`BriefPipelineError`) → 503 + error detail
- GET with `?portfolio_id=abc` → action called with `portfolio_id="abc"`
- GET without portfolio_id → action called with `portfolio_id=None`
- Response matches `OverviewBrief` Pydantic schema exactly (no extra fields)
- Auth dict access: action receives `user["user_id"]` and `user["email"]` (not `user.id`)
- Cache hit path → `BackgroundTasks.add_task` NOT called (callback is None)
- Cold path → `BackgroundTasks.add_task` called with the arbiter callback
- Error format consistent with `structured error detail dict`
- Route mounted on `/api/overview/brief` (verified via test client)
- `response_model` strict mode catches schema drift
- Concurrent requests → no crash (basic concurrency test)

**MCP tool tests (~7 tests):**
- Valid memory dict → writes to DB, returns `{status: "ok"}`
- Memory size computed correctly
- DB error wrapped by `@handle_mcp_errors` decorator (returns structured error dict)
- `user_email` parameter resolves to correct `user_id` via DB lookup
- Tool callable from mocked chat session
- Soft size warning on large memory
- Returns memory_size_bytes in response

**Gateway enricher tests (~10 tests):**
- First call for a user → DB read + cache populate
- Subsequent call for same user → cache hit, no DB read
- Cache miss → DB fail → seed file fallback
- Seed file missing → empty memory returned
- `_invalidate_user_memory_cache(user_id)` evicts only that user's entry
- `_enrich_context` with None user → seed file fallback
- `_enrich_context` with dict user → extracts user_id
- `_enrich_context` with object user → extracts user.id
- Cache isolation: user A's cache update does not affect user B
- Cache persists across multiple chat messages within the same process

### 9.12 Acceptance gate

- `curl -H "Cookie: session_id=..." /api/overview/brief` returns valid `OverviewBrief` JSON
- Route dispatches arbiter callback via `BackgroundTasks` on cold path (non-blocking)
- Route returns 503 when action raises `BriefPipelineError`/`BriefNoCandidatesError`
- Route returns 401 when unauthenticated
- B2 writer lazy imports now resolve (gateway enricher landed): `set_editorial_memory` → `_invalidate_user_memory_cache` fires
- MCP tool is registered and callable from a mocked chat session
- Gateway enricher correctly reads from the per-process cache
- Founder bootstrap script runs cleanly: `python scripts/seed_founder_editorial_memory.py 1`
- No circular import errors at module load time

### 9.13 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| B2 lazy imports don't resolve after B5 lands | Medium | Integration test: call `set_editorial_memory` → verify gateway cache cleared |
| Circular import between editorial_state_store and gateway_proxy | Medium | B2 uses lazy imports; B5 lands the target module; verified pattern |
| Route dispatch of arbiter callback races with response | Low | BackgroundTasks lifecycle is FastAPI-managed; verified pattern |
| MCP tool registry may have project-specific registration conventions | Medium | Check existing tools (`mcp_tools/*.py`) for pattern |
| Founder bootstrap script fails if `user_id=1` doesn't exist | Low | Script prints error and exits; document as manual op |
| Chat context object shape drift (`user.id` vs `user["user_id"]`) | Low | Defensive extraction in enricher |

### 9.14 Rollback

- Delete `routes/overview.py` and remove router mount from `app.py`
- Delete `mcp_tools/overview_editorial.py` and unregister from MCP tool registry
- Revert `routes/gateway_proxy.py:23-36` to original
- Delete `scripts/seed_founder_editorial_memory.py`
- Revert the skill prompt section in `morning-briefing.md`

B2's state store writers remain intact (they use lazy imports — without the gateway enricher, `_invalidate_user_memory_cache` just no-ops). The existing `editorial_memory_seed.json` static path remains functional in all cases. Frontend's `useOverviewBrief` onError fires → TS fallback renders normally.

### 9.15 Manual smoke test

```bash
# After B1-B4 landed + B5 code merged
# Start dev server via services-mcp

# Test the REST endpoint (cold path)
curl -s -H "Cookie: session_id=$SESSION" http://localhost:8000/api/overview/brief | jq .

# Verify structure
curl -s -H "Cookie: session_id=$SESSION" http://localhost:8000/api/overview/brief \
  | jq '.metric_strip | length, .lead_insight.headline, .editorial_metadata.confidence'

# Cache hit (warm path, <50ms)
time curl -s -H "Cookie: session_id=$SESSION" http://localhost:8000/api/overview/brief > /dev/null

# After B1 migration applied + B5 code merged

# Seed the founder
python scripts/seed_founder_editorial_memory.py 1

# Verify row exists
psql -d risk_module -c "SELECT user_id, jsonb_pretty(editorial_memory) FROM user_editorial_state WHERE user_id = 1;"

# Test MCP tool via chat (manual)
# In the chat: "I care about concentration risk more than daily P&L."
# Verify the analyst calls update_editorial_memory with an updated blob
# Then:
psql -d risk_module -c "SELECT editorial_memory->'editorial_preferences' FROM user_editorial_state WHERE user_id = 1;"

# Test gateway enricher cache invalidation
# (The next chat message should see the fresh memory in its context)

# Run tests
pytest tests/core/overview_editorial/test_editorial_state_store.py -v
pytest tests/mcp_tools/test_update_editorial_memory.py -v
pytest tests/routes/test_gateway_proxy_enricher.py -v
```

---

## 10. Sub-phase B6 — Auto-seeder + Hook Integration

### 10.1 Goal

Wire the auto-seeder to fire after a new user's first sync/import, and wire all 3 invalidation hooks to call `invalidate_brief_cache(user_id)`.

### 10.2 Scope

- `core/overview_editorial/memory_seeder.py` — `auto_seed_from_portfolio` + `build_portfolio_composition_summary`
- Hook integration: `workers/tasks/positions.py:48` + `routes/onboarding.py:810`
- Telemetry: `editorial_memory_auto_seed_skipped` WARN event for failed seedings

### 10.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/memory_seeder.py` | Seeder + composition helper + LLM prompt | ~350 |
| `tests/core/overview_editorial/test_memory_seeder.py` | Unit tests | ~250 |
| `tests/workers/test_positions_sync_hooks.py` | Post-sync hook integration | ~150 |
| `tests/routes/test_onboarding_import_hooks.py` | Post-import hook integration | ~150 |

### 10.4 Files to modify

| File | Change |
|---|---|
| `workers/tasks/positions.py:48` | Add direct calls: `invalidate_brief_cache(user_id)` + `auto_seed_from_portfolio(user_id, user_email=user_email, trigger="sync_completion")` (wrapped in try/except) after `record_success()` |
| `routes/onboarding.py:~794` (`/import-csv` handler) | Add `invalidate_brief_cache(user["user_id"])` + `background_tasks.add_task(auto_seed_from_portfolio, ...)` after `import_portfolio()` returns |
| `routes/onboarding.py:~833` (`/import-csv-full` handler) | Same hook wiring as `/import-csv` — both endpoints trigger the same editorial pipeline invalidation + auto-seed |

### 10.5 Seeder shape

```python
# core/overview_editorial/memory_seeder.py

import logging
from typing import Any
from core.overview_editorial.editorial_state_store import (
    seed_editorial_memory_if_missing,
    _editorial_state_row_exists,
)
from core.overview_editorial.orchestrator import gather_portfolio_context
from providers.completion import get_completion_provider
from models.overview_editorial import EditorialMemory

_logger = logging.getLogger(__name__)
_MIN_POSITIONS = 3
_MIN_PORTFOLIO_VALUE = 1000.0
_LLM_TIMEOUT_S = 10.0

def auto_seed_from_portfolio(user_id: int, user_email: str, trigger: str = "unknown") -> dict | None:
    """One-shot LLM pass that infers editorial preferences from portfolio composition.

    Returns the seeded memory blob on success, None on any failure.
    Idempotent — safe to call multiple times (seed_editorial_memory_if_missing is DO NOTHING).

    Args:
        user_id: DB user ID
        user_email: required by gather_portfolio_context (PositionService needs it)
        trigger: "csv_import" or "sync_completion" — logged in telemetry
    """
    # Step 1: Early-exit if row already exists in DB (skip expensive LLM call).
    # Can't use load_editorial_state() for this — it falls back to the seed file
    # when no row exists, so the returned memory is truthy either way.
    # Use a direct row-exists query instead.
    if _editorial_state_row_exists(user_id):
        _log_skip(user_id, reason="row_already_exists", trigger=trigger)
        return None

    # Step 2: Gather portfolio composition summary
    try:
        summary = build_portfolio_composition_summary(user_id, user_email)
    except Exception:
        _log_skip(user_id, reason="composition_summary_failed", trigger=trigger)
        return None

    if summary.get("position_count", 0) < _MIN_POSITIONS:
        _log_skip(user_id, reason="portfolio_too_small", trigger=trigger)
        return None
    if summary.get("portfolio_value", 0) < _MIN_PORTFOLIO_VALUE:
        _log_skip(user_id, reason="portfolio_too_small", trigger=trigger)
        return None

    # Step 3: Call LLM
    import time
    _llm_start = time.monotonic()
    try:
        provider = get_completion_provider()
        if provider is None:
            _log_skip(user_id, reason="no_completion_provider", trigger=trigger)
            return None
        import os
        _seed_model = os.environ.get("EDITORIAL_LLM_MODEL")  # provider default if unset
        response = provider.complete(
            prompt=_build_seed_prompt(summary),
            model=_seed_model,
            timeout=_LLM_TIMEOUT_S,
            max_tokens=1500,
        )
    except Exception as exc:
        _log_skip(user_id, reason="llm_timeout" if "timeout" in str(exc).lower() else "llm_error", trigger=trigger)
        return None

    # Step 4: Validate via Pydantic
    try:
        seeded_memory_model = EditorialMemory.model_validate_json(response)
        seeded_memory = seeded_memory_model.model_dump()
    except Exception:
        _log_skip(user_id, reason="llm_parse_failed", trigger=trigger)
        return None

    # Step 5: Insert if missing (safe under concurrent chat writes — DO NOTHING)
    llm_duration_ms = int((time.monotonic() - _llm_start) * 1000)
    inserted = seed_editorial_memory_if_missing(user_id, seeded_memory, log_extra={
        "auto_seed_trigger": trigger,
        "auto_seed_llm_duration_ms": llm_duration_ms,
    })
    if not inserted:
        _log_skip(user_id, reason="row_already_exists", trigger=trigger)
        return None

    return seeded_memory

def build_portfolio_composition_summary(user_id: int, user_email: str) -> dict[str, Any]:
    """Gathers a compact LLM-friendly portfolio summary via cached builders.
    Wraps PositionService + result_cache snapshots — no new data layer."""
    context = gather_portfolio_context(user_email=user_email, user_id=user_id, portfolio_id=None)
    positions_snapshot = context.tool_snapshot("positions") or {}
    risk_snapshot = context.tool_snapshot("risk") or {}
    perf_snapshot = context.tool_snapshot("performance") or {}

    # Use normalized schema fields from B2 normalizers
    holdings = positions_snapshot.get("holdings", [])  # [{ticker, weight_pct, value, type}]
    return {
        "top_positions": [
            {"ticker": h["ticker"], "type": h.get("type"), "weight_pct": h.get("weight_pct", 0)}
            for h in sorted(holdings, key=lambda h: -h.get("weight_pct", 0))[:10]
        ],
        "hhi": positions_snapshot.get("hhi", _compute_hhi(holdings)),
        "risk_summary": {
            "volatility_annual": risk_snapshot.get("volatility_annual"),
            "herfindahl": risk_snapshot.get("herfindahl"),
            "max_drawdown_pct": perf_snapshot.get("max_drawdown_pct"),
        },
        "performance_summary": {
            "total_return_pct": perf_snapshot.get("total_return_pct"),
            "sharpe_ratio": perf_snapshot.get("sharpe_ratio"),
        },
        "position_count": positions_snapshot.get("position_count", len(holdings)),
        "portfolio_value": positions_snapshot.get("total_value", sum(h.get("value", 0) for h in holdings)),
    }

def _build_seed_prompt(summary: dict) -> str:
    return f"""You are inferring an initial editorial_memory for a new user from their portfolio composition. Be conservative. Only populate fields the portfolio directly reveals. Leave fields requiring user intent (time_horizon, primary_goals, experience_level) empty — those come from conversation.

Portfolio summary:
{summary}

Return valid JSON matching the EditorialMemory schema:
- investor_profile.style: "active_stock_picker" if mostly single names, "passive_index" if mostly ETFs, "mixed" otherwise
- investor_profile.risk_tolerance: "high" if volatility > 0.25, "low" if mostly bonds/cash, "moderate" otherwise
- editorial_preferences.lead_with: up to 2 categories based on biggest signals (concentration if HHI > 0.15, risk if drawdown > 10%, performance if total_return_pct > 15% or < -10%)
- editorial_preferences.care_about: 3-4 categories inferred from composition
- current_focus.watching: specific tickers or themes from outlier positions
- conversation_extracts: exactly one entry noting this was auto-seeded, with a one-line summary

Do NOT populate: less_interested_in, time_horizon, primary_goals, concerns, recent_actions, upcoming.
"""

def _log_skip(user_id: int, reason: str, trigger: str):
    _logger.warning(
        "editorial_memory_auto_seed_skipped",
        extra={"user_id": user_id, "reason": reason, "trigger": trigger},
    )

def _compute_hhi(holdings) -> float:
    weights = [h.get("weight_pct", 0) / 100 for h in holdings]
    return sum(w * w for w in weights)
```

### 10.6 Hook integration

**`workers/tasks/positions.py:48`** — add after `record_success()`:

```python
from core.overview_editorial.brief_cache import invalidate_brief_cache
from core.overview_editorial.memory_seeder import auto_seed_from_portfolio

# Inside sync_provider_positions() after record_success():
# user_email and user_id are available from the Celery task args/context
invalidate_brief_cache(user_id)
try:
    auto_seed_from_portfolio(user_id, user_email=user_email, trigger="sync_completion")
except Exception:
    _logger.warning("auto_seed_from_portfolio failed for user %s", user_id, exc_info=True)
    # Seed failure MUST NOT fail the sync task — the sync already succeeded
```

**`routes/onboarding.py:810`** — add after `import_portfolio()` returns:

```python
from fastapi import BackgroundTasks
from core.overview_editorial.brief_cache import invalidate_brief_cache
from core.overview_editorial.memory_seeder import auto_seed_from_portfolio

# Inside the /import-csv handler:
@router.post("/import-csv")
async def import_csv(
    ...,
    background_tasks: BackgroundTasks,
    user = Depends(get_current_user),
):
    result = await run_in_threadpool(import_portfolio, ...)
    invalidate_brief_cache(user["user_id"])
    background_tasks.add_task(auto_seed_from_portfolio, user["user_id"], user_email=user["email"], trigger="csv_import")
    return result
```

### 10.7 Implementation order

1. Write `memory_seeder.py` — start with `build_portfolio_composition_summary` (pure, no LLM), then the LLM prompt builder, then `auto_seed_from_portfolio` with all early-exits
2. Write unit tests for each piece
3. Modify `workers/tasks/positions.py` — add 2 imports + 2 direct calls after `record_success()`
4. Write integration test for the post-sync hook
5. Modify `routes/onboarding.py` — add 2 imports + `background_tasks` dependency + 2 calls
6. Write integration test for the post-CSV-import hook
7. Manual smoke test: fresh test user → CSV import → verify telemetry + DB row

### 10.8 Test requirements

Target: 25+ tests.

**Seeder tests (~15 tests):**
- Happy path: mocked LLM returns valid JSON → row inserted, telemetry logged
- Row already exists → skip + log
- Portfolio empty → skip + log
- Portfolio < 3 positions → skip + log
- Portfolio value < $1000 → skip + log
- Composition summary helper fails → skip + log
- LLM timeout → skip + log
- LLM parse fails → skip + log
- Pydantic validation fails on LLM output → skip + log
- Race: row created between check and insert → `seed_editorial_memory_if_missing` no-ops → skip + log
- Returned memory has expected shape
- Composition summary has all expected keys
- HHI computation correct
- Idempotent: calling twice → second is a no-op
- Memory size < 10KB

**Hook integration tests (~10 tests):**
- Post-sync hook: Celery task completes successfully → `invalidate_brief_cache` called + `auto_seed_from_portfolio` called
- Post-sync hook: Celery task fails → hooks not called
- Post-sync hook: `auto_seed_from_portfolio` exception does not crash the sync task (defensive)
- Post-import hook: `/import-csv` (at `routes/onboarding.py:~794`) happy path → `invalidate_brief_cache` called + `BackgroundTasks.add_task` called
- Post-import hook: `/import-csv-full` (at `routes/onboarding.py:~833`) same wiring verified
- Post-import hook: import failure → hooks not called
- Post-import hook: auto-seed dispatched via BackgroundTasks (non-blocking)
- Multi-user: hooks fire with correct user_id
- Idempotency: second sync for same user → auto_seed no-ops
- End-to-end: fresh user CSV import → row created within 10s (async dispatch)

### 10.9 Acceptance gate

- Fresh user CSV import creates a `user_editorial_state` row within ~10 seconds (verified via telemetry + DB query)
- `editorial_memory_updated` event emitted with `source="auto_seed"` and `auto_seed_trigger="csv_import"` or `"sync_completion"`
- `editorial_memory_auto_seed_skipped` event emitted for skip cases with the correct reason
- Auto-seed idempotent across multiple invocations
- Brief cache invalidation confirmed after each mutation path (hooks + writers)
- No regression in existing sync or CSV import flows

### 10.10 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| LLM prompt quality affects seed quality | High | Iterate on prompt during smoke testing; Phase 2 can tune |
| Celery worker auto_seed failure crashes sync task | Medium | Wrap in try/except; log but don't re-raise |
| Post-import hook file:line drift (may not be exactly :810) | Low | Search for `import_portfolio(` callsite in current code before editing |
| `BackgroundTasks` injection pattern differs from existing code | Low | Follow the stock-search-prewarm pattern at `app.py:~980` |
| LLM returning markdown-wrapped JSON | Medium | Seed prompt says "return valid JSON"; defensive parser strips fences |

### 10.11 Rollback

- Revert `workers/tasks/positions.py` (delete the 2 new lines)
- Revert `routes/onboarding.py` (delete the 2 new lines + the `BackgroundTasks` parameter if it was added)
- Delete `core/overview_editorial/memory_seeder.py`

Hooks revert cleanly — the rest of the sync and import flows are unchanged.

### 10.12 Manual smoke test

```bash
# Create a fresh test user in the DB with a known user_id
# (Or use the founder user_id=1 with the row deleted first:
psql -d risk_module -c "DELETE FROM user_editorial_state WHERE user_id = 1;"

# Trigger a CSV import as that user (via /import-csv endpoint)
curl -X POST -H "Cookie: session_id=$SESSION" \
  -F "file=@test_portfolio.csv" \
  http://localhost:8000/api/onboarding/import-csv

# Wait a few seconds, then verify
sleep 5
psql -d risk_module -c "SELECT user_id, editorial_memory->'editorial_preferences' FROM user_editorial_state WHERE user_id = 1;"

# Verify telemetry
grep "editorial_memory_updated" logs/app.log | tail -5
grep "editorial_memory_auto_seed_skipped" logs/app.log | tail -5

# Idempotency: run CSV import again
curl -X POST -H "Cookie: session_id=$SESSION" -F "file=@test_portfolio.csv" http://localhost:8000/api/onboarding/import-csv
sleep 5
grep "editorial_memory_auto_seed_skipped.*row_already_exists" logs/app.log | tail -1
```

---

## 11. Sub-phase F1a — Frontend Types + Registry Stubs + ChatMargin Prop + overviewBriefStore

### 11.1 Goal

Pure additive frontend changes. **No user-visible change while the store is empty** (corrected wording from round 1 review — F1a does add new reachable behavior in ChatMargin when `annotations` is non-empty, but since no writer exists in F1a the prop is always empty/undefined). Independently shippable (no backend dependency).

### 11.2 Scope

- New: `artifacts/types.ts`, `artifacts/registry.ts`, `design/marginAnchors.ts`, `stores/overviewBriefStore.ts`
- Extend existing brief types with optional `editorial?: OverviewArtifactEditorial` field
- Extend `MetricStripItem` interface with optional `id?`, `change?`, `whyShowing?` fields
- Extend `ChatMargin` with optional `annotations?` prop (fallback to `VIEW_CONTEXT`)
- Extend `ModernDashboardApp` to read from store + pass annotations prop (always empty in F1a)

**Zero behavior change**: every new field is optional, every new prop defaults to existing behavior. Regression tests verify identical DOM.

### 11.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/types.ts` | `OverviewArtifactEditorial` interface | ~30 |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` | `OVERVIEW_ARTIFACT_REGISTRY` with 6 descriptors | ~80 |
| `frontend/packages/ui/src/components/design/marginAnchors.ts` | Anchor ID constants | ~20 |
| `frontend/packages/connectors/src/stores/overviewBriefStore.ts` | Zustand slice | ~60 |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.test.ts` | Registry smoke test | ~80 |
| `frontend/packages/connectors/src/stores/overviewBriefStore.test.ts` | Store tests | ~100 |
| `frontend/packages/ui/src/components/design/ChatMargin.test.tsx` | Regression test (if missing) | ~150 |

### 11.4 Files to modify

| File | Change |
|---|---|
| `frontend/packages/ui/src/components/dashboard/views/modern/overviewArtifactBrief.ts` | Add optional `editorial?: OverviewArtifactEditorial` field |
| `frontend/packages/ui/src/components/dashboard/views/modern/overviewCompositionBrief.ts` | Add optional `editorial?: OverviewArtifactEditorial` field |
| `frontend/packages/ui/src/components/design/MetricStrip.tsx:3-8` | Add optional `id?: string`, `change?: string`, `whyShowing?: string` to `MetricStripItem` |
| `frontend/packages/ui/src/components/design/ChatMargin.tsx` | Add optional `annotations?: MarginAnnotationUI[]` prop; falls back to `VIEW_CONTEXT` when empty/undefined |
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx:685` | Read `useOverviewBriefStore().marginAnnotationsByPortfolioId[currentPortfolio?.id]`, pass into `<ChatMargin annotations={...} />` |
| `frontend/packages/connectors/src/index.ts` | Export `useOverviewBriefStore` |

### 11.5 `OverviewArtifactEditorial` interface

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/artifacts/types.ts

export interface OverviewArtifactEditorial {
  id: string;
  claim?: string;                   // editable by LLM in Phase 1b
  interpretation?: string;           // editable by LLM in Phase 1b
  annotation?: string | null;       // new: LLM-written editorial note
  highlightIds?: string[];          // new: rows/items to highlight
  editorialNote?: string | null;    // new: top-level context
  visible?: boolean;
  position?: number;
  changedFromPrevious?: boolean;
}
```

### 11.6 Registry stubs

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts

export interface ArtifactDescriptor {
  id: string;
  label: string;
  builderRef: string;  // name of the existing builder function (metadata only in Phase 1a)
  requiresHooks: string[];  // hook data the builder needs (metadata only)
}

export const OVERVIEW_ARTIFACT_REGISTRY: readonly ArtifactDescriptor[] = [
  { id: 'overview.concentration', label: 'Concentration', builderRef: 'buildOverviewConcentrationArtifactBrief', requiresHooks: ['usePositions', 'usePortfolioSummary'] },
  { id: 'overview.performance_attribution', label: 'Performance Attribution', builderRef: 'buildOverviewPerformanceArtifact', requiresHooks: ['usePerformance'] },
  { id: 'overview.tax_opportunity', label: 'Tax Opportunity', builderRef: 'buildOverviewTaxOpportunityArtifact', requiresHooks: ['usePortfolioSummary'] },
  { id: 'overview.composition.asset_allocation', label: 'Asset Allocation', builderRef: 'buildOverviewCompositionBrief.assetAllocationArtifact', requiresHooks: ['useRiskAnalysis'] },
  { id: 'overview.composition.product_type', label: 'Product Type', builderRef: 'buildOverviewCompositionBrief.productTypeArtifact', requiresHooks: ['usePositions'] },
  { id: 'overview.decision', label: 'Decision', builderRef: 'buildOverviewDecisionArtifact', requiresHooks: [] },
] as const;
```

### 11.7 `overviewBriefStore` shape

```ts
// frontend/packages/connectors/src/stores/overviewBriefStore.ts

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

export interface MarginAnnotationUI {
  anchorId: string;
  type: 'ask_about' | 'editorial_note' | 'context';
  content: string;
  prompt?: string;
  changedFromPrevious?: boolean;
}

interface OverviewBriefState {
  marginAnnotationsByPortfolioId: Record<string, MarginAnnotationUI[]>;
  setMarginAnnotations: (portfolioId: string, annotations: MarginAnnotationUI[]) => void;
  clearMarginAnnotations: (portfolioId: string) => void;
}

export const useOverviewBriefStore = create<OverviewBriefState>()(
  devtools((set) => ({
    marginAnnotationsByPortfolioId: {},
    setMarginAnnotations: (portfolioId, annotations) =>
      set((s) => ({
        marginAnnotationsByPortfolioId: {
          ...s.marginAnnotationsByPortfolioId,
          [portfolioId]: annotations,
        },
      })),
    clearMarginAnnotations: (portfolioId) =>
      set((s) => {
        const next = { ...s.marginAnnotationsByPortfolioId };
        delete next[portfolioId];
        return { marginAnnotationsByPortfolioId: next };
      }),
  })),
);
```

### 11.8 `ChatMargin` prop extension

```ts
// frontend/packages/ui/src/components/design/ChatMargin.tsx

import type { MarginAnnotationUI } from '@risk/connectors';

interface ChatMarginProps {
  activeView: ViewId;
  onOpenFullChat: () => void;
  summary?: SummarySnapshot | null;
  featuredEvent?: {...} | null;
  annotations?: MarginAnnotationUI[];  // NEW — Phase 1a default undefined
}

// Inside the component body:
export const ChatMargin = ({ activeView, onOpenFullChat, summary, featuredEvent, annotations }: ChatMarginProps) => {
  // ... existing logic ...

  // Phase 1a: when annotations is non-empty, render them above VIEW_CONTEXT.
  // When empty/undefined, fall back to existing VIEW_CONTEXT[activeView] behavior.
  const hasAnnotations = annotations && annotations.length > 0;

  return (
    <div>
      {hasAnnotations && (
        <div className="overview-brief-annotations">
          {annotations.map((a) => (
            <AnnotationBlock key={a.anchorId} annotation={a} />
          ))}
        </div>
      )}
      {/* existing VIEW_CONTEXT rendering — unchanged */}
    </div>
  );
};
```

### 11.9 `ModernDashboardApp` integration

```ts
// frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx

import { useOverviewBriefStore } from '@risk/connectors';

// Inside ModernDashboardApp render body:
const currentPortfolio = useCurrentPortfolio();
const marginAnnotations = useOverviewBriefStore(
  (s) => s.marginAnnotationsByPortfolioId[currentPortfolio?.id ?? ''] ?? []
);

// At line ~685 where ChatMargin is rendered:
<ChatMargin
  activeView={activeView}
  onOpenFullChat={openAIChat}
  summary={chatMarginSummary}
  featuredEvent={featuredMarketEvent}
  annotations={marginAnnotations}
/>
```

### 11.10 Implementation order

1. Create `artifacts/types.ts` with the interface
2. Create `stores/overviewBriefStore.ts` following the `scenarioWorkflowStore` pattern
3. Create `artifacts/registry.ts` with the 6 stub descriptors
4. Create `design/marginAnchors.ts`
5. Extend `overviewArtifactBrief.ts` and `overviewCompositionBrief.ts` type signatures
6. Extend `MetricStrip.tsx` interface with the 3 new optional fields
7. Extend `ChatMargin.tsx` with the new prop + fallback rendering
8. Extend `ModernDashboardApp.tsx` to read from store + pass prop
9. Update `frontend/packages/connectors/src/index.ts` to export `useOverviewBriefStore`
10. Write unit tests for the new files
11. Write regression test for `ChatMargin` (empty annotations → identical DOM)
12. Run existing tests: `PortfolioOverviewContainer.test.tsx`, `ChatMargin.test.tsx` — must stay green
13. Verify TypeScript compilation succeeds

### 11.11 Test requirements

Target: 20+ tests.

**Types + registry (~5 tests):**
- `OVERVIEW_ARTIFACT_REGISTRY` has the 6 expected IDs in expected order
- Each descriptor has required fields (`id`, `label`, `builderRef`, `requiresHooks`)
- No duplicate IDs
- Readonly enforcement (array is frozen)
- Import cycle sanity check

**`overviewBriefStore` (~6 tests):**
- Initial state: empty `marginAnnotationsByPortfolioId`
- `setMarginAnnotations` writes to correct key
- `setMarginAnnotations` does not affect other portfolio keys
- `clearMarginAnnotations` removes the key
- Multiple portfolios can coexist
- Zustand subscribe fires on write

**`ChatMargin` regression (~6 tests):**
- With `annotations={[]}` → renders identical DOM to current (byte-level or snapshot)
- With `annotations={undefined}` → renders identical DOM to current
- Without `annotations` prop at all → renders identical DOM to current
- With non-empty annotations → renders annotation blocks AND VIEW_CONTEXT content
- Annotations respect `type` field (ask_about vs editorial_note vs context)
- Click on `ask_about` annotation with `prompt` calls `sendMessage(prompt)` via `useSharedChat()`

**`ModernDashboardApp` integration (~3 tests):**
- Reads from store correctly
- Passes empty annotations to `ChatMargin` when store is empty
- Passes non-empty annotations when store has entries

### 11.12 Acceptance gate

- All existing frontend tests still pass
- New regression tests pass
- `PortfolioOverviewContainer.test.tsx` DOM is byte-identical to pre-refactor
- `ChatMargin.test.tsx` DOM is byte-identical for empty/undefined annotations
- TypeScript compilation succeeds with `--strict`
- No new ESLint warnings
- Manual browser smoke test: open Overview, verify nothing looks different

### 11.13 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Circular import between connectors and ui packages | Medium | Follow existing pattern (connectors exports types, ui imports them) |
| `@risk/connectors` export of `useOverviewBriefStore` breaks existing imports | Low | Additive export; nothing removed |
| `ChatMargin` snapshot test flaky if styling changes | Low | Use semantic assertions, not full snapshot |
| `ModernDashboardApp.tsx:685` line drift in parallel sessions | Medium | Grep for `<ChatMargin` before editing to find the actual line |

### 11.14 Rollback

Delete new files, revert the modifications to existing files. All changes are additive — revert is mechanical.

### 11.15 Manual smoke test

```bash
cd frontend && pnpm install
pnpm --filter @risk/connectors build  # ensure store exports
pnpm --filter @risk/ui test -- --testPathPattern="overviewBriefStore|ChatMargin|PortfolioOverviewContainer"

# Browser smoke test (services-mcp for dev server)
# 1. Start risk_module + risk_module_frontend via services-mcp
# 2. Open localhost:3000
# 3. Log in, navigate to Overview
# 4. Verify nothing looks different
# 5. Open React DevTools, find ChatMargin, verify `annotations` prop is `[]`
```

---

## 12. Sub-phase F1b — Container Refactor + Hook + Adapter + Margin Threading + Composition Flatten + Diff Rendering

### 12.1 Goal

Full editorial integration. Container uses backend brief for the first fold, registry loop for artifacts (with directives applied), store for margin annotations, diff markers for slot changes. Composition brief flattens into 2 separate artifacts.

**Package boundary correction** (from round 1 review): `useOverviewBrief` hook + `BackendBriefAdapter` must live in `@risk/connectors` (NOT `@risk/ui`) because connectors owns data-fetching hooks and adapters. The dependency direction is strictly unidirectional: `chassis → connectors → ui`. Connectors CANNOT import from ui (verified: zero existing imports in that direction). The adapter transforms the backend wire format into a connectors-exported type that ui then consumes.

### 12.2 Scope

- New: `useOverviewBrief.ts` hook (React Query)
- New: `BackendBriefAdapter.ts` adapter (runtime validation + null on failure)
- New: per-slot diff marker rendering
- Major modification: `PortfolioOverviewContainer.tsx:1440-1600` — artifact JSX refactored to registry loop, composition flattened, directives applied
- Modification: `overviewBrief.tsx` — extend TS `OverviewBrief` interface, update `buildOverviewBrief()` to emit new shape
- Modification: `overviewCompositionBrief.ts` — refactor to emit flat sub-artifacts
- Modification: `artifacts/registry.ts` — upgrade from metadata to render-capable descriptors
- Modification: `ModernDashboardApp.tsx` — wire up store writes from container (via the brief query result)

### 12.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `frontend/packages/connectors/src/features/overview/hooks/useOverviewBrief.ts` | React Query hook (follows `useRiskAnalysis` pattern at `connectors/src/features/risk/hooks/`) | ~80 |
| `frontend/packages/connectors/src/adapters/BackendBriefAdapter.ts` | Runtime adapter + all exported types (`OverviewBriefData`, `MetricStripItemData`, etc.) — follows `PortfolioSummaryAdapter` pattern | ~250 |
| `frontend/packages/connectors/src/adapters/BackendBriefAdapter.test.ts` | Adapter tests | ~250 |
| `frontend/packages/connectors/src/features/overview/hooks/useOverviewBrief.test.ts` | Hook tests | ~150 |

**Package boundary**: both hook and adapter live in `@risk/connectors` (data-fetching layer). The adapter exports typed `OverviewBriefData` and sub-types which `@risk/ui` components import via the connectors barrel export. This follows the established pattern: `PortfolioSummaryAdapter` (connectors) → `PortfolioSummaryData` type (exported from connectors index.ts) → consumed by `PortfolioOverviewContainer` (ui). **No connectors→ui imports** — the dependency direction is strictly `ui imports from connectors`.

### 12.4 Files to modify

| File | Change |
|---|---|
| `overviewBrief.tsx` | Extend `OverviewBrief` TS interface to match wire schema; update `buildOverviewBrief()` fallback to emit new shape |
| `overviewBrief.test.tsx` | Update fixtures for new shape |
| `overviewCompositionBrief.ts` | Refactor to emit flat asset_allocation + product_type artifact briefs |
| `overviewCompositionBrief.test.ts` | Update for flattened shape (verify DOM still matches current) |
| `artifacts/registry.ts` | Upgrade descriptors: add `builder` function (not just `builderRef` string) |
| `PortfolioOverviewContainer.tsx:1440-1600` | Refactor artifact JSX to registry loop; apply directives; preserve chrome; write margin annotations to store on brief arrival |
| `PortfolioOverviewContainer.test.tsx` | DOM regression test for fixed fixture |
| `frontend/packages/connectors/src/index.ts` | Export `useOverviewBrief`, `OverviewBriefData`, and adapter sub-types |

### 12.5 `useOverviewBrief` hook

**Package boundary correction** (from round 1): hook + adapter MUST live in `@risk/connectors`. The dependency direction is strictly `chassis → connectors → ui`. Connectors CANNOT import from ui (zero existing imports in that direction). Types live in connectors; ui imports them from the connectors barrel export.

```ts
// frontend/packages/connectors/src/features/overview/hooks/useOverviewBrief.ts

import { useQuery } from '@tanstack/react-query';
import { adaptBackendBrief } from '../../../adapters/BackendBriefAdapter';
import type { OverviewBriefData } from '../../../adapters/BackendBriefAdapter';

/**
 * Fetches the backend editorial brief. Returns OverviewBriefData on success,
 * null if the adapter rejects the response (schema mismatch → TS fallback).
 */
export function useOverviewBrief(portfolioId: string | null) {
  return useQuery<OverviewBriefData | null>({
    queryKey: ['overview-brief', portfolioId],
    queryFn: async () => {
      const url = portfolioId
        ? `/api/overview/brief?portfolio_id=${encodeURIComponent(portfolioId)}`
        : '/api/overview/brief';
      const response = await fetch(url, { credentials: 'include' });
      if (!response.ok) {
        throw new Error(`Brief fetch failed: ${response.status}`);
      }
      const raw = await response.json();
      return adaptBackendBrief(raw);  // returns null on validation failure
    },
    staleTime: 5 * 60 * 1000,   // 5 minutes
    gcTime: 30 * 60 * 1000,      // 30 minutes
    retry: 1,                     // one retry on transient failure
  });
}
```

### 12.6 Adapter shape

The adapter lives in `@risk/connectors` and exports `OverviewBriefData` — a connectors-owned type that `@risk/ui` components import. This follows the established `PortfolioSummaryAdapter` → `PortfolioSummaryData` pattern.

```ts
// frontend/packages/connectors/src/adapters/BackendBriefAdapter.ts

// Types exported from connectors (ui imports these, NOT the other way around)
export interface OverviewBriefData {
  leadInsight: { headline: string; evidence: string[]; exitRamps: ExitRampData[] };
  metricStrip: MetricStripItemData[];
  artifactDirectives: ArtifactDirectiveData[];
  marginAnnotations: MarginAnnotationData[];
  attentionItems: never[];  // Phase 1 ignores
  editorialMetadata: EditorialMetadataData;
}

export interface MetricStripItemData {
  id: string;
  label: string;
  value: string;
  change?: string;
  detail?: string;
  tone: 'up' | 'down' | 'neutral';
  whyShowing?: string;
}

export interface ExitRampData {
  label: string;
  actionType: 'navigate' | 'chat_prompt';
  payload: string;
}

export interface ArtifactDirectiveData {
  artifactId: string;
  position: number;
  visible: boolean;
  annotation?: string;
  highlightIds: string[];
  editorialNote?: string;
  changedFromPrevious: boolean;
}

export interface MarginAnnotationData {
  anchorId: string;
  type: 'ask_about' | 'editorial_note' | 'context';
  content: string;
  prompt?: string;
  changedFromPrevious: boolean;
}

export interface EditorialMetadataData {
  confidence: 'high' | 'partial' | 'summary only';
  source: 'live' | 'mixed' | 'summary';
  llmEnhanced: boolean;
  generatedAt: string;
  changedSlots: string[];
}

export function adaptBackendBrief(apiResponse: unknown): OverviewBriefData | null {
  if (!apiResponse || typeof apiResponse !== 'object') return null;

  try {
    const raw = apiResponse as Record<string, any>;

    const metricStrip: MetricStripItemData[] = (raw.metric_strip ?? []).map((m: any) => ({
      id: String(m.id ?? ''),
      label: String(m.title ?? ''),
      value: String(m.value ?? ''),
      change: m.change ?? undefined,
      detail: m.context_label ?? undefined,
      tone: (m.tone ?? 'neutral') as 'up' | 'down' | 'neutral',
      whyShowing: m.why_showing ?? undefined,
    }));

    const leadInsight = {
      headline: String(raw.lead_insight?.headline ?? ''),
      evidence: Array.isArray(raw.lead_insight?.evidence) ? raw.lead_insight.evidence.map(String) : [],
      exitRamps: (raw.lead_insight?.exit_ramps ?? []).map((er: any) => ({
        label: String(er.label ?? ''),
        actionType: er.action_type as 'navigate' | 'chat_prompt',
        payload: String(er.payload ?? ''),
      })),
    };

    const artifactDirectives: ArtifactDirectiveData[] = (raw.artifact_directives ?? []).map((d: any) => ({
      artifactId: String(d.artifact_id),
      position: Number(d.position ?? 0),
      visible: d.visible !== false,
      annotation: d.annotation ?? undefined,
      highlightIds: Array.isArray(d.highlight_ids) ? d.highlight_ids.map(String) : [],
      editorialNote: d.editorial_note ?? undefined,
      changedFromPrevious: d.changed_from_previous === true,
    }));

    const marginAnnotations: MarginAnnotationData[] = (raw.margin_annotations ?? []).map((a: any) => ({
      anchorId: String(a.anchor_id),
      type: a.type as 'ask_about' | 'editorial_note' | 'context',
      content: String(a.content),
      prompt: a.prompt ?? undefined,
      changedFromPrevious: a.changed_from_previous === true,
    }));

    const editorialMetadata = {
      confidence: (raw.editorial_metadata?.confidence ?? 'summary only') as 'high' | 'partial' | 'summary only',
      source: (raw.editorial_metadata?.source ?? 'summary') as 'live' | 'mixed' | 'summary',
      llmEnhanced: raw.editorial_metadata?.llm_enhanced === true,
      generatedAt: String(raw.editorial_metadata?.generated_at ?? ''),
      changedSlots: Array.isArray(raw.editorial_metadata?.changed_slots) ? raw.editorial_metadata.changed_slots.map(String) : [],
    };

    return {
      leadInsight,
      metricStrip,
      artifactDirectives,
      marginAnnotations,
      attentionItems: [] as never[],  // Phase 1 ignores
      editorialMetadata,
    } satisfies OverviewBriefData;
  } catch (err) {
    console.warn('brief_adapter_validation_failed', err);
    return null;
  }
}
```

### 12.7 Composition flatten

```ts
// overviewCompositionBrief.ts — refactored

// BEFORE: single OverviewCompositionBrief with nested assetAllocationArtifact + productTypeArtifact

// AFTER: two separate artifact briefs
export interface OverviewAssetAllocationArtifactBrief extends OverviewArtifactEditorial {
  kind: 'composition.asset_allocation';
  // existing fields from the nested structure
}

export interface OverviewProductTypeArtifactBrief extends OverviewArtifactEditorial {
  kind: 'composition.product_type';
  // existing fields
}

// The shared insight + annotations move to a new "section header" piece
export interface OverviewCompositionSection {
  insight: string;
  annotations: AnnotationTagItem[];
}

export function buildOverviewCompositionBrief(...): {
  section: OverviewCompositionSection;
  assetAllocationBrief: OverviewAssetAllocationArtifactBrief | null;
  productTypeBrief: OverviewProductTypeArtifactBrief | null;
} {
  // ... same logic but returns 3 values instead of 1 nested object
}
```

### 12.8 Container refactor sketch

```ts
// PortfolioOverviewContainer.tsx — the critical refactor
// Imports from @risk/connectors (NOT from local adapter files)
import { useOverviewBrief } from '@risk/connectors';
import type { OverviewBriefData } from '@risk/connectors';

const { data: backendBrief } = useOverviewBrief(currentPortfolio?.id ?? null);

// When brief arrives, write margin annotations to the store
useEffect(() => {
  if (backendBrief && currentPortfolio) {
    useOverviewBriefStore.getState().setMarginAnnotations(
      currentPortfolio.id,
      backendBrief.marginAnnotations.map(toMarginAnnotationUI),
    );
  }
  return () => {
    if (currentPortfolio) {
      useOverviewBriefStore.getState().clearMarginAnnotations(currentPortfolio.id);
    }
  };
}, [backendBrief, currentPortfolio?.id]);

// Determine which brief drives the first fold
const effectiveBrief: OverviewBrief = backendBrief ?? buildOverviewBrief({ /* existing hook-sourced inputs */ });

// Render the first fold (metric strip + lead insight) from effectiveBrief
const { metricStrip, leadInsight, editorialMetadata } = effectiveBrief;
const changedSlotsSet = new Set(editorialMetadata.changedSlots);

// Registry-driven artifact rendering (replaces the hand-rolled JSX)
const artifactOrder = applyDirectives(OVERVIEW_ARTIFACT_REGISTRY, backendBrief?.artifactDirectives ?? []);

return (
  <div>
    {/* chrome elements: section breaks, tier gates, etc. — preserved */}
    <MetricStrip items={metricStrip.map(enrichWithDiffMarker(changedSlotsSet))} />
    <NamedSectionBreak label="Concentration" />

    {/* Registry loop for artifacts */}
    {artifactOrder.map((artifactEntry) => {
      const directive = artifactEntry.directive;
      if (directive && directive.visible === false) return null;
      const props = artifactEntry.builder(context);  // calls the existing builder
      if (!props) return null;
      return (
        <GeneratedArtifact
          key={artifactEntry.id}
          {...props}
          annotation={directive?.annotation}
          highlightedIds={directive?.highlightIds ?? []}
          changedFromPrevious={directive?.changedFromPrevious ?? false}
          onNavigate={handleOverviewArtifactNavigate}
        />
      );
    })}

    {/* More chrome: Market Context section, Analyst Queue, etc. — preserved */}
  </div>
);
```

### 12.9 Implementation order

1. Write `useOverviewBrief.ts` React Query hook
2. Write `BackendBriefAdapter.ts` with strict validation + null-on-failure
3. Write adapter tests (happy, malformed, missing fields, type drift)
4. Update `overviewBrief.tsx` `OverviewBrief` interface + `buildOverviewBrief()` to emit new shape
5. Refactor `overviewCompositionBrief.ts` to emit 2 flat artifacts + section header
6. Update `overviewCompositionBrief.test.ts` to verify flat output still produces identical DOM
7. Upgrade `artifacts/registry.ts` descriptors with actual `builder` functions
8. Refactor `PortfolioOverviewContainer.tsx` to:
   - Call `useOverviewBrief`
   - Use backend brief when available, fall back to `buildOverviewBrief()` on null
   - Loop over registry with directive application
   - Preserve all chrome (section breaks, conditionals, tier gates)
   - Preserve hidden coupling at line 1454 (`showExitRamps={!overviewGeneratedArtifact}`)
   - Write margin annotations to store on brief arrival
   - Render diff markers on slots in `changedSlots`
9. Update `PortfolioOverviewContainer.test.tsx` with DOM regression test
10. Manual smoke test: load Overview with backend brief → verify render → kill endpoint → verify fallback

### 12.10 Test requirements

Target: 35+ tests.

**`useOverviewBrief` hook (~8 tests):**
- Happy path: fetch succeeds → adapter returns brief → hook returns data
- Fetch fails (5xx) → onError → hook returns error
- Fetch succeeds but adapter returns null → hook returns null data
- `portfolio_id=null` → URL has no query param
- `portfolio_id="abc"` → URL encodes correctly
- `staleTime` respected
- Retry on transient failure (retry=1)
- Loading state exposed correctly

**`adaptBackendBrief` (~15 tests):**
- Happy path: full valid brief → returns correctly shaped object
- Malformed JSON (not an object) → null
- Missing `metric_strip` → null or empty array
- Missing `lead_insight` → null
- `metric_strip` item missing `id` → default empty string, still valid
- `artifact_directives` with non-array → empty array
- `margin_annotations` with unknown `type` → defensive default
- `changed_slots` not an array → empty array
- Field name translation: `context_label` → `detail`, `title` → `label`
- `tone` missing → defaults to 'neutral'
- `llm_enhanced` not boolean → defaults to false
- `editorial_metadata.confidence` unknown value → defaults to 'summary only'
- Exception during mapping → caught, null returned, warning logged
- `attention_items` always empty (Phase 1 ignores)
- Round-trip: backend-generated JSON → adapt → TS shape matches interface

**Container integration (~12 tests):**
- Backend brief available → uses it for first fold
- Backend brief null (fetch error) → falls back to `buildOverviewBrief()`
- Backend brief null (adapter rejection) → falls back
- Loading state → shows existing loading placeholder
- Directives empty → registry renders in default order
- Directive with `visible=false` → artifact skipped
- Directive with `position` → artifacts reordered
- Directive with `annotation` → artifact renders with annotation
- Directive with `highlightIds` → rows highlighted
- Margin annotations written to store on brief arrival
- Margin annotations cleared on portfolio change
- Diff markers rendered on slots in `changedSlots`

### 12.11 Acceptance gate

- `curl` the backend endpoint, verify valid `OverviewBrief` JSON
- Load Overview in dev server, verify rendering with backend brief
- Kill the endpoint (return 503), verify TS fallback renders correctly
- Verify `useOverviewBrief` fetches once per portfolio (React Query dedup)
- Verify `MarginAnnotations` appear in `ChatMargin` when backend emits them
- Verify diff markers render subtly on changed slots
- Verify existing tests for `PortfolioOverviewContainer`, `ChatMargin`, `MetricStrip` still pass
- DOM regression test with fixed fixture passes (no drift from current)
- Manual QA: click-to-ask on a margin annotation → calls `sendMessage(prompt)` via `useSharedChat`

### 12.12 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Container JSX refactor breaks the hidden coupling at line 1454 | High | Write the coupling test FIRST, then refactor |
| Composition flatten disturbs the section header layout | Medium | Regression test with fixed fixture |
| Adapter schema drift from backend Pydantic | Medium | Strict validation + null-on-failure; adapter tests catch drift |
| React Query staleTime too aggressive → stale briefs | Low | 5-minute staleTime is conservative; tune if needed |
| `useEffect` for store writes causes infinite loop | Medium | Dependency array is stable; test with React Testing Library |
| Backend brief format mismatch with TS interface | High | Pydantic + adapter validation is the safety net; any drift → null → TS fallback |

### 12.13 Rollback

Revert all changes to `PortfolioOverviewContainer.tsx`, `overviewBrief.tsx`, `overviewCompositionBrief.ts`, `artifacts/registry.ts`. Delete `useOverviewBrief.ts`, `BackendBriefAdapter.ts`, and their tests. The F1a stubs stay in place.

### 12.14 Manual smoke test

```bash
# Services-MCP dev server start (both risk_module + risk_module_frontend)

# 1. Log in, navigate to Overview
# 2. Verify backend brief is being fetched (Network tab: /api/overview/brief → 200)
# 3. Verify first fold renders with backend data
# 4. Verify ChatMargin shows margin annotations (if backend emitted them)
# 5. Kill the backend: docker-compose stop risk_module
# 6. Reload Overview → verify TS fallback renders, no console errors
# 7. Restart backend, reload → verify backend brief is used again
# 8. Multi-portfolio test: switch portfolios, verify annotations clear + refetch
# 9. Diff test: trigger a CSV import or sync, verify brief regenerates + changed_slots populated

# Run tests
pnpm --filter @risk/ui test -- --testPathPattern="Overview|ChatMargin|adaptBackendBrief"
pnpm --filter @risk/connectors test -- --testPathPattern="useOverviewBrief|overviewBriefStore"
```

---

## 13. QA Checklist — Phase 1 Ship Verification

Before Phase 1 ships to beta, every item on this checklist must pass. Each maps to a §14 ship criterion from the arch spec.

### 13.1 Founder Verification (Week 6, Day 1)

- [ ] Founder's `user_editorial_state` row exists with populated `editorial_memory` (via founder bootstrap script)
- [ ] Open Overview — backend brief renders in first fold (verified via React DevTools: `useOverviewBrief` returns `isSuccess`)
- [ ] `overview_brief_generated` log emitted with `cache_state=miss`, `data_status` all loaded, `lead_insight_category` non-null
- [ ] LLM arbiter completes within ~3s and replaces the cache (second log: `overview_brief_enhanced`, `parse_success=true`)
- [ ] Reload Overview within 5 minutes → `cache_state=hit`, response time <100ms
- [ ] Lead insight reflects a meaningful editorial choice (not just "highest severity flag")

### 13.2 Fallback Path (Week 6, Day 1)

- [ ] Kill `/api/overview/brief` endpoint (debug toggle or service stop)
- [ ] Reload Overview → TS fallback renders (`buildOverviewBrief()` path)
- [ ] No console errors
- [ ] No broken UI state
- [ ] Restore endpoint, reload → backend brief returns

### 13.3 Auto-Seed New User (Week 6, Day 2)

- [ ] Delete founder's row temporarily: `DELETE FROM user_editorial_state WHERE user_id = 1;`
- [ ] Trigger a CSV import
- [ ] Verify row is created within ~10s via: `SELECT * FROM user_editorial_state WHERE user_id = 1;`
- [ ] Verify `editorial_memory_updated` log with `source="auto_seed"`, `auto_seed_trigger="csv_import"`
- [ ] Verify `auto_seed_llm_duration_ms` field present and <5000
- [ ] Reload Overview → brief uses the auto-seeded memory
- [ ] Re-seed founder from script for normal operation

### 13.4 Editorial Memory Write Path (Week 6, Day 2)

- [ ] In chat: "I care about concentration risk more than daily P&L"
- [ ] Verify `editorial_memory_updated` log with `source="chat_tool"`
- [ ] Verify DB row updated: `SELECT editorial_memory->'editorial_preferences' FROM user_editorial_state WHERE user_id = 1;`
- [ ] Reload Overview → brief reflects the new preference (lead_insight_category biased toward concentration)
- [ ] Compare `selection_reasons` before and after → they differ

### 13.5 Diff Markers (Week 6, Day 3)

- [ ] Trigger a sync or memory update to invalidate the brief cache
- [ ] Reload Overview → verify `editorial_metadata.changed_slots` is non-empty
- [ ] Verify diff markers render on the changed slots (subtle visual indicator)
- [ ] Verify `changed_slots_count` field in telemetry log > 0

### 13.6 Multi-Portfolio (Week 6, Day 3)

- [ ] User has 2+ portfolios
- [ ] Load portfolio A → cache entry created
- [ ] Switch to portfolio B → separate cache entry
- [ ] Switch back to portfolio A → cache hit
- [ ] Verify `previous_briefs` in DB has 2 keys: `previous_briefs->>'A'` and `previous_briefs->>'B'`
- [ ] Generation for A does not clobber B's anchor

### 13.7 Artifact Directives (Week 6, Day 4)

- [ ] Backend brief contains `artifact_directives` with at least 1 annotation
- [ ] Verify annotation renders on the correct artifact
- [ ] `directive_count` in `overview_brief_generated` > 0
- [ ] `highlightIds` renders as subtle row highlight

### 13.8 Chat Margin Annotations (Week 6, Day 4)

- [ ] Backend brief contains `margin_annotations` with at least 1 `ask_about` entry
- [ ] Verify annotation renders in the chat margin
- [ ] `annotation_count` in `overview_brief_generated` > 0
- [ ] Click the annotation → `sendMessage(prompt)` called → message appears in chat thread
- [ ] Verify via React DevTools that `annotations` prop is populated from `overviewBriefStore`

### 13.9 Telemetry Audit (Week 6, Day 5)

- [ ] Run a synthetic 7-day log sample (or accelerate via test harness)
- [ ] `lead_insight_category` distribution has ≥3 distinct values over 5 days
- [ ] `parse_success` rate on `overview_brief_enhanced` ≥90%
- [ ] `directive_count` average ≥1
- [ ] `annotation_count` average ≥1
- [ ] `changed_slots_count` non-zero on ≥30% of briefs
- [ ] Zero error events for 100 consecutive generations on founder portfolio
- [ ] All telemetry fields present as defined in §10.1

### 13.10 Regression Sweep (Week 6, Day 5)

- [ ] Existing Overview tests pass: `PortfolioOverviewContainer.test.tsx`, `ChatMargin.test.tsx` (note: `MetricStrip.test.tsx` does not exist today — write one in F1a when extending the interface)
- [ ] Existing backend tests pass: `tests/services/test_portfolio.py`, `tests/routes/test_*.py`
- [ ] Full test suite green: `pytest` + `pnpm test`
- [ ] No new ESLint warnings
- [ ] TypeScript compilation clean: `pnpm tsc --noEmit`
- [ ] Architecture boundary test still passes: `pytest tests/test_architecture_boundaries.py`

---

## 14. Implementation Execution Order

Actual timeline + commit sequence. **Backend is fully serial** (each sub-phase imports from the previous). No false parallelism on the backend chain. F1a is the only parallel track.

### Week 1
- **Day 1-3**: B1 (migration + models) — 1 commit
- **Day 1-3** (parallel): F1a (frontend types + stubs + ChatMargin prop + overviewBriefStore) — 1 commit
- End-of-week gate: B1 + F1a merged, test suite green, migration applies/rolls back cleanly

### Week 2
- **Day 1-5**: B2 (data layer: orchestrator + full editorial_state_store + diff.py) — 1 commit
- End-of-week gate: B2 merged. `gather_portfolio_context()` returns valid PortfolioContext with real `PositionService` data. `load_editorial_state()` + `set_editorial_memory()` + `set_previous_brief()` all work. `compute_changed_slots()` returns correct diffs for fixture inputs.

### Week 3
- **Day 1-5**: B3 (generators + policy + brief cache + directive/annotation emission) — 1 commit
- End-of-week gate: B3 merged. Each generator produces candidates including directive/annotation candidates. Policy ranks correctly. Brief cache TTL + invalidation + L2 clear verified.

### Week 4
- **Day 1-4**: B4 (action layer + LLM arbiter, transport-neutral) — 1 commit
- End-of-week gate: B4 merged. `get_brief()` action returns valid `OverviewBrief` with populated `artifact_directives`, `margin_annotations`, `changed_slots`. Arbiter enhancement works with mocked provider. `set_previous_brief` rotation verified. No FastAPI imports in `actions/`.

### Week 5
- **Day 1-4**: B5 (transport layer: route + MCP tool + gateway enricher + BackgroundTasks + founder bootstrap) — 1 commit
- End-of-week gate: `curl /api/overview/brief` returns valid JSON for founder. MCP `update_editorial_memory` tool callable from chat. Gateway enricher reads per-user memory from DB. Founder bootstrap script runs.
- **Day 3-5** (F1b starts, overlapping): F1b (container refactor + hook + adapter) — begins once B5's route is live

### Week 6
- **Day 1-3**: B6 (auto-seeder + hook integration) — 1 commit
- **Day 1-5** (F1b continues): F1b (full frontend integration) — 1 commit
- End-of-week gate: Full end-to-end pipeline working. Auto-seed fires on fresh user. Frontend renders backend brief. Fallback to TS builder verified. QA checklist starts.

### Week 7 (buffer)
- **Day 1-5**: QA checklist execution + telemetry verification + manual scenario runs + ship criteria verification
- End-of-week gate: §14 ship criteria verified, Phase 1 ships to founder + beta cohort

Total: 8 committable units across 6-7 weeks. Each commit goes through its own Codex diff review per the mandatory plan-first workflow. The ~1 week extension vs. original estimate is honest accounting for the serial backend chain (was falsely parallelized in the first draft).

---

## 15. Known Deferred Items

Explicitly out-of-scope for Phase 1, listed here so reviewers don't flag them:

- Events, Income, Trading, Factor, Tax Harvest generators (Phase 2)
- `attention_items` UI rendering (backend schema present, frontend ignores)
- Revision markers beyond slot-level diff (Phase 2)
- Dedicated onboarding wizard (only if conversational memory updates prove insufficient)
- `CompletionProvider.complete_structured()` protocol extension (Phase 2)
- Engagement tracking / click logging (Phase 2+)
- Multi-process gateway enricher cache (Redis / LISTEN-NOTIFY) — deferred until multi-process is a real requirement
- In-process singleflight on brief generation — deferred unless telemetry shows duplicate generations are common
- User-scoped L2 result cache keys — deferred unless hot rebuilds are a problem
- Architecture test for invalidation hooks — Phase 2
- Eval framework for brief quality regression — Phase 2
- Observability dashboards — Phase 2

---

## 16. Cross-Sub-Phase Checklist

Every sub-phase must satisfy these before its commit lands:

- [ ] **Wire schema alignment**: any backend Pydantic change has a matching TS change in the same commit
- [ ] **Cache invalidation contract**: any new write path calls `invalidate_brief_cache(user_id)`
- [ ] **Failure mode preservation**: every new code path has a fallback test
- [ ] **Test coverage**: >85% line coverage for new modules
- [ ] **Regression tests**: for sub-phases touching existing code, DOM or output regression tests verify zero-change-when-empty
- [ ] **Rollback verified**: the rollback story in the sub-phase section is actually revertible
- [ ] **Manual smoke test completed**: the smoke test section was run and passed
- [ ] **Architecture boundary test passes**: `pytest tests/test_architecture_boundaries.py`
- [ ] **Code review**: Codex diff review for the sub-phase's commit
- [ ] **Logging present**: new structured log events match §10.1 schema

---

## 17. Summary

Phase 1 ships in **8 committable units** over **6-7 weeks**, with a fully serial backend critical path of **B1 → B2 → B3 → B4 → B5 → B6**. Frontend Phase 1a runs fully in parallel starting Week 1. F1b starts in Week 5 alongside B6 once B5's route is live.

**Restructured from round 1 Codex review** (10 P1s addressed):
- Backend is honestly serial (false B5 parallelism removed)
- Sub-phase boundaries redrawn: B2 owns full state store + diff.py, B4 is transport-neutral (no FastAPI), B5 is the transport layer
- All API signatures corrected: `PositionService(user_email=...)`, `result_cache(builder=...)`, auth dicts with `user["user_id"]`
- Architecture boundary respected: `actions/` does not import FastAPI
- Frontend package boundary fixed: hook + adapter in `@risk/connectors`, not `@risk/ui`
- Missing sub-phase ownership resolved: diff.py → B2, directive/annotation emission → B3, structured logging → B4/B5/B6
- MetricStripItem.id uses stable slot keys (not ticker-specific)
- F1a wording corrected to "no user-visible change while store is empty"

Each sub-phase:
- Has a precise scope bounded by file paths from the arch spec + verified line numbers from code investigation
- Specifies files to create + files to modify with `file:line` touchpoints where known
- Lists test counts + acceptance gates Codex will check
- Flags risks with mitigations
- Has a rollback story
- Has a manual smoke test

**Cross-cutting discipline** (wire schema, cache invalidation, failure modes) enforced by the §16 checklist for every commit.

**Ship verification** follows the §14 criteria from the arch spec, now operationalized as a 10-day QA checklist in §13 of this plan.

**Total committable artifacts**: 1 migration, ~24 new files, ~12 modified files, ~300 tests, ~8000 lines of new code.

---

**Next step**: Codex review of this plan. If PASS, implementation starts with B1 + F1a in Week 1. If FAIL, iterate to PASS.
