# Overview Editorial Pipeline — Architecture Spec (Phase 1)

**Status**: DRAFT — pending Codex review
**Created**: 2026-04-10
**Supersedes**: none (sits between `OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md` and the forthcoming Phase 1 implementation plan)
**Related**:
- Product/editorial design: `OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md` (APPROVED)
- E20a validation: `completed/LLM_BRIEFING_EXPERIMENT_PLAN.md` (VALIDATED)
- Frontend seam: `frontend/packages/ui/src/components/dashboard/views/modern/overviewBrief.tsx` (`e97ca546` + `4cc21bb3`)
- Gateway enricher: `routes/gateway_proxy.py` (`e4de1107`)

## 1. Purpose

The product design doc answers *what* the Overview should feel like. This spec answers *how* the system is built: layer boundaries, data flow, wire format, caching contract, failure modes. It is the reference the Phase 1 implementation plan will expand into step-by-step tasks.

Goals of this doc:
- Resolve the three scope/caching blockers surfaced during pre-implementation investigation.
- Lock the wire schema so frontend and backend can implement in parallel.
- Define the caching and invalidation contract precisely enough that it can be reviewed independently of the generator logic.
- Identify the minimal set of new files/modules and the boundary between new code and existing infrastructure.

Non-goals:
- Step-by-step implementation tasks (that's the Phase 1 plan).
- Phase 2 scope (additional generators, engagement logging, attention items UI, onboarding wizard).
- Visual/UX decisions beyond what's already settled in `OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md` and DESIGN.md.

## 2. Phase 1 Scope

**In scope:**
- 3 insight generators: Concentration, Risk, Performance (see §3.1 for the Events decision)
- Deterministic editorial policy (weighted scoring; no LLM in the critical render path)
- Async LLM arbiter that rewrites the brief in analyst voice via `CompletionProvider`
- `GET /api/overview/brief` REST endpoint
- `user_editorial_state` DB table with **read + write** (chat-driven memory updates)
- `update_editorial_memory` MCP tool so the analyst can update memory during conversation
- **Auto-seed editorial_memory from portfolio composition** on first connection (CEO review cherry-pick #4)
- **Artifact directive plumbing** — prep refactor + editorial pipeline can select/order/annotate existing Overview artifacts (§9.8)
- **Chat margin annotations** — prep refactor + editorial pipeline emits annotations consumed by existing `ChatMargin` (§9.9)
- **Diff view** — subtle "changed since yesterday" markers on slots whose content differs from `previous_brief` (§9.10, CEO review cherry-pick #1)
- Brief cache with event-driven invalidation on position/transaction changes (and editorial_memory updates)
- Frontend contract extension: backend-driven brief with deterministic TS fallback
- Telemetry: structured logging for every brief generation (selection reasons, confidence, data status)

**Out of scope (Phase 2 or later):**
- Events, Income, Trading, Factor, Tax Harvest generators
- Engagement logging (click tracking, "why you're seeing this" open rate)
- Attention items UI rendering (backend schema includes the field; frontend ignores it in Phase 1)
- Revision/diff markers on changed insights
- Editorial confidence badge as a dedicated UI element
- `complete_structured()` on CompletionProvider (Phase 1 uses string JSON + Pydantic validation)
- Dedicated onboarding wizard (Phase 1 relies on free-form analyst conversation to populate memory)

## 3. Key Decisions (Prescriptive)

Each decision resolves a blocker surfaced in investigation. These are prescriptive; flag for re-evaluation if wrong.

### 3.1 Events generator → dropped from Phase 1

**Decision**: Phase 1 ships with 3 generators (Concentration, Risk, Performance). Events moves to Phase 2.

**Why**: `get_portfolio_events_calendar()` has no cached builder — it's a live FMP call. Wrapping it directly violates Eng review decision #1 ("wrap cached builders, not raw services"). The alternatives are all bad:
- Build an events cache layer just for Phase 1 → scope creep, new invalidation surface
- Accept live FMP call as a documented exception → drift from Eng review decision
- Delay Phase 1 until events caching exists → blocks editorial pipeline on unrelated work

**Editorial cost is minimal**: Concentration + Risk + Performance cover the founder's primary lead-story categories. Events is calendar information, not editorial judgment — "earnings Tuesday" is a fact, not an insight. The pipeline proves its value on the 3 highest-signal generators.

**Phase 2 re-entry**: When events is added, add a `build_events_snapshot()` cached builder in `services/portfolio/result_cache.py` following the existing pattern. No pipeline changes.

### 3.2 Positions data source → wrap `PositionService` directly

**Decision**: The Concentration generator reads from `PositionService.get_all_positions()` directly, not through a new cached snapshot layer.

**Why**: `PositionService` already owns freshness for positions. Adding a second cached snapshot on top would create two sources of truth and a second invalidation surface. The "cached builders" Eng review decision #1 guards against re-calling MCP tool wrappers from inside the pipeline — wrapping the service layer is fine, and is in fact what the other generators do for risk/performance via `result_cache.py`.

**Normalization**: The generator accepts the `PositionService` output and normalizes into the same `{snapshot, flags}` shape the risk/performance generators consume. Normalization logic lives in `core/overview_editorial/context.py`, not in the generator itself.

### 3.3 Brief cache invalidation → scoped helper called from real mutation paths

**Decision**: Phase 1 adds one helper — `invalidate_brief_cache(user_id)` — and calls it from exactly **three** verified write paths. The helper also clears the L2 result snapshot cache for the affected user so the next regenerated brief reads fresh risk/performance data.

Verified hook points (locations confirmed via code investigation):

1. **Brokerage sync completion**: inside the Celery task `sync_provider_positions()` at `workers/tasks/positions.py:48`, immediately after `record_success()` returns. This is the post-commit point — `PositionService.refresh_provider_positions()` has already committed by the time `record_success()` runs. NOT in `services/sync_runner.py` (which only enqueues the task; the work happens in the worker).

2. **CSV import completion**: inside the `/import-csv` and `/import-csv-full` route handlers in `routes/onboarding.py` at line 810, immediately after `import_portfolio()` returns successfully and before the response is sent. The import is synchronous inside the request handler (runs via `run_in_threadpool`), so a direct call after the return is safe.

3. **editorial_memory write**: inside `set_editorial_memory()` in `core/overview_editorial/editorial_state_store.py`, immediately after the DB upsert commits. This ensures the next brief reflects the updated memory without waiting for the 1hr TTL.

**Phantom hook removed**: Earlier drafts of this spec listed a fourth hook for "transaction ingest" via `routes/transactions.py`. **No such code path exists** — transactions are only written via brokerage sync or CSV/statement import, both of which are already covered by Hooks 1 and 2. The phantom was an artifact of speculation, not a real write path.

**L2 result cache invalidation**: The existing `services/portfolio/result_cache.py` 30s `RESULT_SNAPSHOT_TTL_SECONDS` cache is NOT currently invalidated by sync or import completion (verified — no callers of `clear_result_snapshot_caches()` in mutation paths). This means a brief regenerated immediately after a sync would read up-to-30s-old risk/performance data. **Phase 1 fix**: `invalidate_brief_cache(user_id)` ALSO calls `clear_result_snapshot_caches()` (module-level clear, not user-scoped, but acceptable for Phase 1 — the result cache has small entries and will rebuild quickly under normal load). User-scoped result cache keys are deferred to Phase 2.

**Why this shape**: The critical gap flagged in design review was "cache invalidation on position changes within the 1hr window." This fix is scoped to the brief cache plus the upstream result cache, both invalidated together so that "fresh values from real-time hooks" (Eng review decision #8) actually holds. Three hook points cover all known mutation paths; any new write path added later becomes a grep target for `invalidate_brief_cache`.

**What we accept**: If a write path is added in the future and the author forgets to call `invalidate_brief_cache`, the user sees a stale brief for up to 1 hour. Mitigation: add an architecture test in Phase 2 that fails if a known mutation entry point lacks the call. Phase 1 relies on review discipline.

### 3.4 Schema authority → backend is the source of truth

**Decision**: The backend `OverviewBrief` Pydantic model defines the wire format. The current TS seam (`overviewBrief.tsx`) is extended to match the backend schema exactly. The seam remains responsible for rendering structured fields (`lead_insight.headline`, `lead_insight.evidence`) into ReactNode — the backend does not emit ReactNode, only structured text.

**Why**: Two sources of truth is the worst outcome. The seam was Phase 0 and explicitly framed as a bridge implementation. Extending it to match backend costs a few type additions and one render helper; keeping them divergent costs weeks of drift.

**Exception**: `attention_items` is part of the backend schema in Phase 1 (empty array valid) but the frontend does NOT render it. This preserves the contract without forcing Phase 1 UI work. When attention items ship in Phase 2, it's purely additive on the frontend.

### 3.5 editorial_memory → read + write in Phase 1, AI-managed

**Decision**: Phase 1 ships with both read and write. The analyst reads `editorial_memory` via the existing chat `context_enricher` and writes to it via a new MCP tool `update_editorial_memory(new_memory)`. No confirmation UX, no patch schemas, no undo history, no audit trail.

**Why**: The write path is not a design problem — it's a one-function tool. Same pattern as Claude Code's own memory system: the model decides what to write, writes the JSON, moves on. If it writes something wrong, the next conversation corrects it. The original "NEEDS DESIGN" framing in the design doc open question #5 was an over-complication — treating the AI as untrusted when it's already trusted with the user's full portfolio.

**What the write path actually is**:
1. One helper in `editorial_state_store.py`: `set_editorial_memory(user_id, memory: dict) -> None` — upsert into `user_editorial_state` via `INSERT ... ON CONFLICT (user_id) DO UPDATE SET editorial_memory = EXCLUDED.editorial_memory, updated_at = NOW()`. Always replaces (chat is the authoritative writer).
2. One MCP tool: `update_editorial_memory(new_memory: dict)` — calls the helper. Current memory is already in the chat context, so the AI reads it, merges changes itself, and writes the full updated blob.
3. One prompt instruction added to the analyst skill: *"You maintain editorial_memory. Update it when the user tells you something worth remembering about how they think about investing."*
4. Invalidate the brief cache for that user after a successful write (so the next brief reflects the new memory).

**Concurrency story (chat write vs. auto-seed race)**: Both the MCP tool and the auto-seeder (§9.7) can target the same `user_editorial_state` row. The race is made safe by design at the upsert level:

- **Chat writes** use `INSERT ... ON CONFLICT DO UPDATE` — they always replace whatever's in the row. Last writer wins. Acceptable because the AI is the authoritative editor.
- **Auto-seeder** uses `INSERT ... ON CONFLICT DO NOTHING` — it only creates a row if none exists. If a chat write got there first (unlikely on a brand-new user, but possible), auto-seed silently no-ops.
- **Both writes are single Postgres statements** — no read-modify-write window, no advisory locks, no version columns.
- **Stale chat-context risk**: the chat enricher loads `editorial_memory` once per chat session start (or per message, depending on §9.6 decision). If the AI calls `update_editorial_memory` with stale memory in context, it will overwrite a fresh write that happened mid-session. Mitigation: the analyst skill prompt instructs the AI to call the tool with intentional updates only, not bulk replays. Phase 2 can add a `version` column for optimistic locking if this becomes a real problem.

**What we explicitly do NOT build**:
- Confirmation cards in chat ("I'll remember X, confirm?") — the AI is already trusted; corrections happen conversationally.
- Patch validation with restricted field access — the AI writes the full JSON; Pydantic validates the shape on read.
- `editorial_memory_history` undo table — if the AI writes wrong, the user says so in the next message and the AI fixes it.
- Dedicated onboarding wizard — the analyst conversation is the onboarding flow.
- Retention policy beyond a soft size cap — if memory grows past ~10KB the prompt instruction tells the AI to prune the oldest `conversation_extracts`.

**Fallback**: If the DB row doesn't exist for a user (new user, no conversation yet), the orchestrator falls back to `config/editorial_memory_seed.json`. First write creates the row.

**Phase 1 guarantees**: Every user — not just the founder — gets a personalized brief once they've had a conversation with the analyst. Beta opens on ship.

### 3.6 LLM structured output → string JSON + strict validation

**Decision**: Phase 1 uses the existing `CompletionProvider.complete() → str` interface. The arbiter prompt requests JSON output. The response is parsed with `OverviewBrief.model_validate_json()`. On parse failure, the deterministic brief stands.

**Why**: Extending `CompletionProvider` with a structured-output method is a protocol change that ripples across providers (OpenAI `response_format`, Anthropic tool use, future providers). Not Phase 1 material. String JSON + Pydantic validation is a 10-line implementation with a clean fallback.

**Phase 2 hook**: When a second caller needs structured output (likely the editorial_memory extraction path), add `complete_structured()` to the protocol at that point.

### 3.7 Background runtime → FastAPI `BackgroundTasks` for non-durable work, Celery already handles sync

**Decision**: Phase 1 uses **FastAPI `BackgroundTasks`** for the LLM arbiter and auto-seeder. The brief cache invalidation helper is a direct in-process call (~1ms, no async needed). Celery already handles brokerage sync; Phase 1 does not introduce new Celery tasks.

**Why**: The codebase already uses both runtimes (verified):
- **Celery**: heavy, durable work — `workers/tasks/positions.py`, `workers/tasks/orders.py`. Used for sync because it's slow (2-5s) and benefits from worker durability.
- **FastAPI `BackgroundTasks`**: lightweight, fire-and-forget — example at `app.py:~980` where the stock search endpoint kicks off `background_tasks.add_task(stock_service.schedule_stock_lookup_prewarm, symbol)` after returning the response.

The LLM arbiter and auto-seeder are both 2-3s LLM calls that should not block the request response but also do not require durability across process restarts (Phase 1 founder + small beta scale; if a process dies mid-arbiter, the deterministic brief remains in the cache and the next request gets retried). `BackgroundTasks` is the right tool.

**Concrete patterns**:
- **Brief invalidation**: `invalidate_brief_cache(user_id)` is a synchronous in-process call from the 3 hook sites. No background runtime needed.
- **LLM arbiter**: `routes/overview.py` accepts a `BackgroundTasks` dependency, calls `background_tasks.add_task(llm_arbiter.enhance, brief, editorial_memory, user_id, portfolio_id)` after writing the deterministic brief to the cache and before returning the response.
- **Auto-seeder**: the post-sync hook in `workers/tasks/positions.py` cannot use FastAPI `BackgroundTasks` (no request context inside a Celery worker). Instead, it directly calls `auto_seed_from_portfolio(user_id)` synchronously inside the Celery task — Celery's worker already provides the background runtime. The CSV import hook in `routes/onboarding.py` DOES use `BackgroundTasks` because it has request context.

**Asymmetry note**: This means the auto-seeder is invoked from two places with two different runtimes (sync hook = Celery direct call, CSV import hook = FastAPI BackgroundTasks). The function itself is the same; only the call site differs. Acceptable.

**Phase 2 upgrade path**: If LLM arbiter durability becomes a requirement (e.g., recover from a process restart mid-enhancement), migrate to a new Celery task. The pipeline core does not change.

## 4. System Context

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (modern Overview)                       │
│                                                                          │
│  PortfolioOverviewContainer.tsx                                          │
│    │                                                                    │
│    ├─ useOverviewBrief(portfolio_id)  ◄── NEW React Query hook           │
│    │     │                                                              │
│    │     └─ GET /api/overview/brief ─────────────────┐                   │
│    │                                                  │                   │
│    ├─ buildOverviewBrief(...)  ◄── existing deterministic TS (fallback) │
│    │                                                  │                   │
│    └─ adaptBackendBrief(apiResponse) ◄── NEW adapter  │                   │
│         │                                             │                   │
│         └─> OverviewBrief (TS, extended)              │                   │
└──────────────────────────────────────────────────────┼───────────────────┘
                                                        │
┌──────────────────────────────────────────────────────┼───────────────────┐
│                              BACKEND                  │                   │
│                                                        ▼                   │
│  routes/overview.py  ◄── NEW                                              │
│     GET /api/overview/brief                                               │
│     │                                                                    │
│     └─> actions/overview_brief.py  ◄── NEW                                │
│            │                                                             │
│            ├─> core/overview_editorial/brief_cache.py  ◄── NEW           │
│            │     (TTLCache[user_id] → OverviewBrief, 1hr)                │
│            │                                                             │
│            │   [cache miss path]                                         │
│            │                                                             │
│            ├─> core/overview_editorial/orchestrator.py  ◄── NEW          │
│            │     ThreadPoolExecutor fan-out:                             │
│            │       ├─ PositionService.get_all_positions()                │
│            │       ├─ result_cache.get_analysis_result_snapshot()        │
│            │       └─ result_cache.get_performance_result_snapshot()     │
│            │     │                                                       │
│            │     └─> PortfolioContext {tool_results, data_status,        │
│            │                           editorial_memory,                 │
│            │                           previous_brief_for_this_portfolio}│
│            │                                                             │
│            ├─> core/overview_editorial/generators/*.py  ◄── NEW          │
│            │     Concentration, Risk, Performance                        │
│            │     → List[InsightCandidate]                                │
│            │                                                             │
│            ├─> core/overview_editorial/policy.py  ◄── NEW                │
│            │     Weighted additive scoring:                              │
│            │       composite = 0.35*rel + 0.25*urg + 0.25*mem + 0.15*nov │
│            │     → ranked candidates, top N per slot_type                │
│            │                                                             │
│            └─> OverviewBrief (deterministic)                             │
│                 │                                                        │
│                 ├─> return to route (synchronous render path)            │
│                 │                                                        │
│                 └─> async task: core/overview_editorial/llm_arbiter.py   │
│                       CompletionProvider.complete(...) → str             │
│                       → OverviewBrief.model_validate_json()              │
│                       → replaces brief in cache                          │
│                                                                          │
│  DB:                                                                     │
│    user_editorial_state (user_id PK, editorial_memory JSONB,             │
│                          previous_briefs JSONB map keyed by portfolio_id)│
└──────────────────────────────────────────────────────────────────────────┘
         ▲                                        ▲
         │                                        │
         │ invalidate_brief_cache(user_id)        │ invalidate_brief_cache(user_id)
         │                                        │
  workers/tasks/positions.py:48           routes/onboarding.py:810
  (post-record_success in Celery)         (post-import_portfolio in CSV route)

  Plus: editorial_state_store.set_editorial_memory() → invalidate_brief_cache after upsert
```

## 5. Data Flow

### 5.1 Cold path (cache miss, first load)

1. Frontend: `useOverviewBrief(portfolio_id)` fires on mount.
2. `GET /api/overview/brief?portfolio_id=X` → `routes/overview.py` → `actions/overview_brief.get_brief(user, portfolio_id)`.
3. Brief cache miss for `(user_id, portfolio_id)`.
4. `DataGatheringOrchestrator` spawns a ThreadPoolExecutor with 3 workers:
   - Worker 1: `PositionService.get_all_positions(user_id, portfolio_id)` → positions dict
   - Worker 2: `result_cache.get_analysis_result_snapshot(...)` → `RiskAnalysisResult`
   - Worker 3: `result_cache.get_performance_result_snapshot(...)` → `PerformanceResult`
5. Each worker's result is normalized into `{snapshot, flags}` shape by the orchestrator. On individual worker failure, `data_status[tool] = "failed"` and the tool_result is `None`.
6. Orchestrator calls `load_editorial_state(user_id, portfolio_id)` which returns `(editorial_memory, previous_brief_anchor)` in a single DB read. Falls back to `editorial_memory_seed.json` for memory if the row doesn't exist; `previous_brief_anchor` is None for first generation of this portfolio.
7. Orchestrator returns `PortfolioContext`.
8. Each of the 3 generators is called with the relevant tool_result. Generators with `data_status == "failed"` input return empty candidate lists. Generator output: `List[InsightCandidate]`.
9. `EditorialPolicyLayer.rank(candidates, editorial_memory, previous_brief_anchor)` → scored + sorted candidates.
10. Policy layer selects top-N per slot_type (metric=6, lead_insight=1, attention_item=0-3).
11. Deterministic `OverviewBrief` is composed using `previous_brief_anchor` (loaded from DB at step 6) for novelty scoring.
12. **Diff computation**: `diff_function.compute_changed_slots(new_brief, previous_brief_anchor)` populates `new_brief.editorial_metadata.changed_slots`. The anchor is the DB-loaded previous brief from step 6 — no extra DB reads.
13. New brief is written to in-memory cache with TTL=1hr.
14. **`previous_brief` rotation (synchronous, ~10ms)**: `set_previous_brief(user_id, portfolio_id, new_brief)` writes the new brief to `user_editorial_state.previous_briefs[portfolio_id]`. The new brief becomes the diff/novelty anchor for the NEXT cold-path generation. The DB is the durable source of truth — this works even after cache TTL expiry.
15. Deterministic brief is returned to the route (response time dominated by step 4: risk engine cold computation, 2-5s; step 14 adds ~10ms).
16. Response serialized via existing `make_json_safe()` helper.
17. Frontend receives brief → `adaptBackendBrief()` → stored via `useOverviewBrief` → `PortfolioOverviewContainer` renders.

Meanwhile, an async task is kicked off via `BackgroundTasks.add_task()` after step 13 and before step 16 returns the response:

A. `llm_arbiter.enhance(deterministic_brief, editorial_memory, user_id, portfolio_id)` runs in the FastAPI background runtime.
B. Arbiter builds a prompt with the deterministic brief + editorial memory + analyst voice instructions.
C. `CompletionProvider.complete(prompt, ...)` returns string JSON.
D. `OverviewBrief.model_validate_json(response)` — strict parse.
E. On success: enhanced brief replaces deterministic brief in cache (same TTL). The diff function re-runs against `previous_brief` so the enhanced brief carries up-to-date `changed_slots`.
F. On parse failure / timeout / exception: log warning, leave deterministic brief in cache unchanged.
G. Frontend does NOT poll for enhancement. Next page load within the 1hr TTL gets the enhanced brief. This matches the "LLM enhancement is a quality upgrade, not a requirement" decision.

### 5.2 Warm path (cache hit)

1. Frontend: `useOverviewBrief(portfolio_id)` fires.
2. `GET /api/overview/brief` → route → action.
3. Brief cache hit for `(user_id, portfolio_id)`.
4. Cached brief returned directly. No orchestrator, no generators, no LLM call.
5. Response time: <50ms + network.

### 5.3 Invalidation path (position change)

1. User triggers a position-mutating action — brokerage sync completes (Celery task) OR CSV import completes (FastAPI route).
2. Write path calls `invalidate_brief_cache(user_id)`:
   - **Hook 1**: `workers/tasks/positions.py:48` after `record_success()` returns inside the Celery task
   - **Hook 2**: `routes/onboarding.py:810` after `import_portfolio()` returns inside the route handler
3. `invalidate_brief_cache(user_id)` evicts all brief cache entries for that user (across all their portfolio_ids) AND calls `clear_result_snapshot_caches()` so the L2 risk/performance cache cannot serve stale data on the next regeneration.
4. Next `GET /api/overview/brief` → cache miss → cold path → fresh data from upstream cached builders.

### 5.3a Invalidation path (editorial memory update)

1. Analyst calls `update_editorial_memory(new_memory)` MCP tool from chat.
2. Tool calls `set_editorial_memory(user_id, new_memory)` in `editorial_state_store.py`.
3. After the DB upsert commits, `set_editorial_memory` calls `invalidate_brief_cache(user_id)`.
4. Next `GET /api/overview/brief` → cache miss → cold path → policy layer reads the new memory and re-scores candidates.

### 5.4 Failure modes

| Failure | Fallback | Logs |
|---|---|---|
| One generator fails | `data_status[tool] = "failed"`; other generators still contribute; brief composed with fewer candidates | WARN: `generator_failed` with tool name + exception |
| All 3 generators fail (or orchestrator raises) | Action returns `ActionError`; route returns HTTP 503; frontend falls back to `buildOverviewBrief()` TS | ERROR: `brief_pipeline_failed` |
| DB (user_editorial_state) unavailable | editorial_memory falls back to seed file; previous_brief is None | WARN: `editorial_state_db_miss` |
| editorial_memory_seed.json missing | editorial_memory = empty dict; policy layer `memory_fit = 0.3` default | WARN: `editorial_memory_seed_missing` |
| LLM arbiter fails (timeout, parse error, provider down) | Deterministic brief stands in cache | WARN: `llm_arbiter_failed` with reason |
| `CompletionProvider` not configured | LLM enhancement skipped entirely; deterministic only | INFO: `llm_arbiter_disabled` (one-time at startup) |
| Brief cache write fails | Brief is still returned; next request re-computes | WARN: `brief_cache_write_failed` |
| Frontend receives malformed brief | Zod/Pydantic schema mismatch → adapter returns null → container falls back to `buildOverviewBrief()` TS | WARN (client-side): `brief_adapter_validation_failed` |
| `GET /api/overview/brief` returns 5xx | `useOverviewBrief` onError → container falls back to `buildOverviewBrief()` | WARN (client-side): `brief_fetch_failed` |

The ultimate fallback — `buildOverviewBrief()` deterministic TS — continues to work in Phase 1 because all its inputs come from hooks that are already called by the container (`usePortfolioSummary`, `usePerformance`, `useRiskAnalysis`, `usePositions`). No regressions on total pipeline failure.

## 6. Layer Contracts

### 6.1 `PortfolioContext` (new dataclass)

```python
# core/overview_editorial/context.py

@dataclass(frozen=True)
class PortfolioContext:
    user_id: int
    portfolio_id: str | None
    tool_results: dict[str, dict]  # {"positions": {...}, "risk": {...}, "performance": {...}}
    data_status: dict[str, Literal["loaded", "partial", "failed"]]
    editorial_memory: dict         # parsed JSON, may be empty
    previous_brief: dict | None    # parsed JSON, None if no prior brief
    generated_at: datetime         # UTC

    def tool_snapshot(self, name: str) -> dict | None:
        """Return the `snapshot` sub-dict for a tool, or None if failed/missing."""
        if self.data_status.get(name) == "failed":
            return None
        return self.tool_results.get(name, {}).get("snapshot")

    def tool_flags(self, name: str) -> list[dict]:
        """Return the flags list for a tool, or empty list if failed/missing."""
        if self.data_status.get(name) == "failed":
            return []
        return self.tool_results.get(name, {}).get("flags", [])
```

### 6.2 `InsightGenerator` Protocol (new)

```python
# core/overview_editorial/generators/base.py

class InsightGenerator(Protocol):
    name: str  # "concentration" | "risk" | "performance"

    def generate(self, context: PortfolioContext) -> list[InsightCandidate]:
        """Produce insight candidates. MUST NOT raise — return [] on failure.
        Generators are responsible for defensive handling of their own tool output."""
        ...
```

### 6.3 `InsightCandidate` (new Pydantic model)

```python
# models/overview_editorial.py

class InsightCandidate(BaseModel):
    slot_type: Literal["metric", "lead_insight", "attention_item"]
    category: Literal["concentration", "risk", "performance", "income",
                      "trading", "factor", "tax", "events"]
    content: dict  # slot-type-specific payload; see §7 for metric/lead_insight shapes
    relevance_score: float = Field(ge=0, le=1)
    urgency_score: float = Field(ge=0, le=1)
    novelty_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1, default=1.0)
    evidence: list[str] = []
    why: str             # human-readable "why you're seeing this"
    source_tool: str     # "get_positions" | "get_risk_analysis" | "get_performance"
```

### 6.4 `EditorialPolicyLayer` (new)

```python
# core/overview_editorial/policy.py

class EditorialPolicyLayer:
    def rank(
        self,
        candidates: list[InsightCandidate],
        editorial_memory: dict,
        previous_brief: dict | None,
    ) -> list[RankedCandidate]:
        """Score candidates via weighted additive:
            composite = 0.35*relevance + 0.25*urgency + 0.25*memory_fit + 0.15*novelty
        Returns sorted descending by composite."""

    def select_slots(
        self,
        ranked: list[RankedCandidate],
    ) -> dict[str, list[RankedCandidate]]:
        """Select top-N per slot_type:
            metric → top 6 (pad with defaults if < 6)
            lead_insight → top 1
            attention_item → top 0-3 (by urgency threshold)"""
```

### 6.5 `LLMArbiter` (new, async)

```python
# core/overview_editorial/llm_arbiter.py

class LLMArbiter:
    def __init__(self, provider: CompletionProvider, model: str, timeout_s: float = 3.0):
        ...

    async def enhance(
        self,
        deterministic_brief: OverviewBrief,
        editorial_memory: dict,
    ) -> OverviewBrief | None:
        """Rewrite lead_insight + metric labels in analyst voice.
        Returns enhanced brief on success, None on any failure (parse, timeout, provider)."""
```

### 6.6 Brief cache (new)

```python
# core/overview_editorial/brief_cache.py

_BRIEF_CACHE: TTLCache[tuple[int, str | None], OverviewBrief] = TTLCache(maxsize=1000, ttl=3600)

def get_cached_brief(user_id: int, portfolio_id: str | None) -> OverviewBrief | None: ...
def set_cached_brief(user_id: int, portfolio_id: str | None, brief: OverviewBrief) -> None: ...
def invalidate_brief_cache(user_id: int) -> int:
    """Evict all brief cache entries for a user. Returns number evicted."""
```

### 6.7 Action layer

```python
# actions/overview_brief.py

async def get_brief(
    ctx: ActionContext,
    portfolio_id: str | None,
) -> OverviewBrief:
    """Composition: cache → orchestrator → generators → policy → deterministic brief → return.
    Async LLM enhancement kicked off as a background task before return."""
```

### 6.8 Route

```python
# routes/overview.py

@overview_router.get("/api/overview/brief", response_model=OverviewBrief)
async def get_overview_brief(
    portfolio_id: str | None = None,
    user: User = Depends(get_current_user),
) -> OverviewBrief:
    ctx = ActionContext(user=user, request_id=...)
    try:
        return await actions.overview_brief.get_brief(ctx, portfolio_id)
    except ActionError as e:
        raise HTTPException(status_code=e.http_status, detail=e.to_dict())
```

## 7. Wire Schema

The backend Pydantic model is the source of truth. The frontend TS type is derived from it (manual for Phase 1; code-generated in Phase 2 if we add schema codegen).

```python
# models/overview_editorial.py

class MetricStripItem(BaseModel):
    id: str                          # stable key: "return" | "volatility" | "concentration" | ...
    title: str                       # "Return"
    value: str                       # pre-formatted display string, e.g. "+12.4%"
    change: str | None = None        # optional delta vs previous brief, e.g. "+1.2pts"
    context_label: str | None = None # "YTD vs SPY" | "annualized" | ...
    tone: Literal["up", "down", "neutral"] = "neutral"
    why_showing: str | None = None   # "Return is elevated by concentration in Real Estate"

class LeadInsight(BaseModel):
    headline: str                    # "Your portfolio is concentrated in Real Estate and it's costing you 4.7% YTD"
    evidence: list[str] = []         # ["DSU 18% weight", "Real Estate -6.3% YTD", ...]
    exit_ramps: list[ExitRamp] = []  # ["Hedge this risk" → /scenarios/hedge, ...]

class ExitRamp(BaseModel):
    label: str                       # "Hedge this risk"
    action_type: Literal["navigate", "chat_prompt"]
    payload: str                     # view id for navigate, prompt text for chat_prompt

class AttentionItem(BaseModel):
    category: str
    headline: str
    urgency: Literal["alert", "act", "watch"]
    action: ExitRamp | None = None

class EditorialMetadata(BaseModel):
    generated_at: datetime
    editorial_memory_version: int
    candidates_considered: int
    selection_reasons: list[str] = []           # short trace: "concentration led due to 18% DSU weight"
    confidence: Literal["high", "partial", "summary only"]
    source: Literal["live", "mixed", "summary"]
    llm_enhanced: bool = False                  # True if the cached copy is post-arbiter
    changed_slots: list[str] = []               # §9.10 — slot IDs whose content differs from previous_brief
                                                # e.g. ["metric.return", "lead_insight", "artifact.overview.concentration"]

class ArtifactDirective(BaseModel):
    """Editorial direction for an existing Overview artifact.
    Backend emits; frontend applies over registry defaults. Empty list → defaults."""
    artifact_id: str                            # stable ID from frontend registry, e.g. "overview.concentration"
    position: int                               # render order among directed artifacts
    visible: bool = True                        # hide/show; default visible
    annotation: str | None = None               # LLM-written editorial note shown with the artifact
    highlight_ids: list[str] = []               # which rows/items to visually highlight (e.g., ["DSU", "AAPL"])
    editorial_note: str | None = None           # "Why this artifact is relevant right now" — top-level context
    changed_from_previous: bool = False         # True if this artifact's directive differs from previous_brief

class MarginAnnotation(BaseModel):
    """Editorial annotation rendered in the chat margin alongside the briefing."""
    anchor_id: str                              # "lead_insight" | "metric.return" | "artifact.overview.concentration"
    type: Literal["ask_about", "editorial_note", "context"]
    content: str                                # prose — LLM-written
    prompt: str | None = None                   # optional "click to ask Hank" pre-filled message
    changed_from_previous: bool = False         # True if this annotation is new or changed vs. previous_brief

class OverviewBrief(BaseModel):
    metric_strip: list[MetricStripItem]         # length: 3–6 (pad with defaults if < 6)
    lead_insight: LeadInsight
    artifact_directives: list[ArtifactDirective] = []    # §9.8 — empty → frontend uses registry defaults
    margin_annotations: list[MarginAnnotation] = []      # §9.9 — empty → frontend uses VIEW_CONTEXT defaults
    attention_items: list[AttentionItem] = []   # 0–3; empty valid in Phase 1
    editorial_metadata: EditorialMetadata
```

### Frontend TS reconciliation

The existing `OverviewBrief` TS type in `overviewBrief.tsx` is extended to match. The key changes:

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/overviewBrief.tsx

// BEFORE (Phase 0 seam):
export interface OverviewBrief {
  leadInsight: React.ReactNode;             // ← ReactNode, rendering baked in
  leadInsightRevisionText: string;
  metricStrip: MetricStripItem[];
  editorialMetadata: { confidence, source };
}

// AFTER (Phase 1, wire-format-aligned):
export interface OverviewBrief {
  leadInsight: {                            // ← structured, container renders
    headline: string;
    evidence: string[];
    exitRamps: ExitRamp[];
  };
  leadInsightRevisionText: string;          // kept for diff/revision text
  metricStrip: MetricStripItem[];           // id + whyShowing added
  artifactDirectives: ArtifactDirective[];  // §9.8 — empty → registry defaults
  marginAnnotations: MarginAnnotation[];    // §9.9 — empty → VIEW_CONTEXT defaults
  attentionItems: AttentionItem[];          // Phase 1: ignored by render
  editorialMetadata: {
    confidence: 'high' | 'partial' | 'summary only';
    source: 'live' | 'mixed' | 'summary';
    llmEnhanced: boolean;
    generatedAt: string;
    changedSlots: string[];                 // §9.10 — slot IDs flagged as changed since previous_brief
  };
}
```

**`MetricStrip.tsx` interface extension** (real gap, verified):

The current `MetricStripItem` at `frontend/packages/ui/src/components/design/MetricStrip.tsx:3-8` is `{ label, value, detail?, tone? }`. The backend wire schema needs `id` (for diff targeting), `change` (delta string), and `whyShowing` (Phase 2). Phase 1 adds the first two; `whyShowing` is optional and unused by the renderer until Phase 2.

```ts
// frontend/packages/ui/src/components/design/MetricStrip.tsx (modified)
export interface MetricStripItem {
  id?: string;                              // NEW — stable ID matching backend `id` field, used for diff targeting
  label: string;                            // existing — maps to backend `title`
  value: string;                            // existing
  change?: string;                          // NEW — delta vs previous brief, e.g. "+1.2pts"
  detail?: string;                          // existing — maps to backend `context_label`
  tone?: 'up' | 'down' | 'neutral';         // existing
  whyShowing?: string;                      // NEW — reserved for Phase 2 hover/tooltip; renderer ignores in Phase 1
}
```

The adapter (`adaptBackendBrief.ts`) maps backend `MetricStripItem.title → label`, `context_label → detail`, passes `id`, `change`, `tone`, `value` directly. No renderer change needed for Phase 1.

The deterministic TS `buildOverviewBrief()` fallback is updated to emit the new structured shape. `PortfolioOverviewContainer.tsx` gets a small `renderLeadInsight(lead: LeadInsightShape) → ReactNode` helper — this is the only new rendering logic in Phase 1.

### Adapter

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/adaptBackendBrief.ts

export function adaptBackendBrief(apiResponse: unknown): OverviewBrief | null {
  // Runtime validation via zod schema mirroring the Pydantic model.
  // Returns null on validation failure → container falls back to buildOverviewBrief().
}
```

## 8. Caching & Invalidation

### 8.1 Cache layers

| Layer | Location | Scope | TTL | Invalidation |
|---|---|---|---|---|
| L1: Brief cache | `core/overview_editorial/brief_cache.py` (new) | `(user_id, portfolio_id)` → `OverviewBrief` | 1 hour | `invalidate_brief_cache(user_id)` + TTL expiry |
| L2: Result cache | `services/portfolio/result_cache.py` (existing) | Risk/Performance/Analysis snapshots | 30s (env-tunable) | Passive TTL (unchanged) |
| L3: Service cache | `services/cache_adapters.py` + downstream (existing) | Provider data (prices, returns, fundamentals) | Varies | Existing `clear_all_caches()` / TTL |

The brief cache piggybacks on L2/L3 for data freshness. When the brief cache misses, the orchestrator calls into L2 snapshot builders which in turn use L3. This means cold-path brief generation is fast when L2 is warm (typical during normal session use) and slow (2-5s) only when L2 is also cold.

### 8.2 Invalidation hooks

The brief cache is invalidated by `invalidate_brief_cache(user_id)` at exactly **three** verified call sites:

**Hook 1 — Brokerage sync completion**
`workers/tasks/positions.py:48` — inside the `sync_provider_positions()` Celery task, immediately after `record_success()` returns. The DB commit has already happened (inside `PositionService.refresh_provider_positions()` → `_save_positions_to_db()` → `db_client.save_positions_from_dataframe()`). This is a direct synchronous call inside the worker task — no Celery signal or callback registry needed.

**Hook 2 — CSV import completion**
`routes/onboarding.py:810` — inside the `/import-csv` and `/import-csv-full` route handlers, after `import_portfolio()` returns successfully and before the response is sent. The import is synchronous inside the request handler (runs via `run_in_threadpool`).

**Hook 3 — editorial_memory write**
`set_editorial_memory()` in `core/overview_editorial/editorial_state_store.py` — calls `invalidate_brief_cache(user_id)` after a successful DB upsert. The next brief reflects the new editorial preferences immediately, not after the 1hr TTL.

**No transaction-ingest hook**: Earlier drafts mentioned a fourth hook for "transaction ingest" via `routes/transactions.py`. Code investigation confirmed no such path exists — transactions are only written via brokerage sync (Hook 1) or CSV/statement import (Hook 2). Removed from the spec.

**`invalidate_brief_cache` implementation** (also clears L2 result cache):
```python
def invalidate_brief_cache(user_id: int) -> int:
    """Evict brief cache entries for a user AND clear the L2 result snapshot cache.
    The L2 clear is module-level (not user-scoped) — acceptable for Phase 1 because
    result cache entries are small and rebuild quickly under normal load."""
    evicted = _evict_brief_cache_entries_for_user(user_id)
    clear_result_snapshot_caches()  # from services/portfolio/result_cache.py
    return evicted
```

The three sites are the only known write paths that affect what the brief reads from (positions/risk/performance OR editorial memory). Any new write path added later MUST call `invalidate_brief_cache`. Phase 2 may add an architecture test that fails if a known mutation entry point lacks the call.

### 8.3 Cache key choice

Key: `(user_id, portfolio_id)` where `portfolio_id` may be `None` (user's default portfolio).

Rationale: Users with multiple portfolios see different briefs per portfolio. `invalidate_brief_cache(user_id)` evicts all entries for that user (typically 1-3 portfolios), which is acceptable because position changes on one portfolio often signal changes to the user's overall state. Over-invalidation is cheap; under-invalidation shows stale briefs.

### 8.4 LLM-enhanced brief caching

The LLM-enhanced brief replaces the deterministic brief in the cache once the arbiter returns (§5.1 step E). The cached entry's `editorial_metadata.llm_enhanced = true`. TTL is reset on replacement (1hr from enhancement time, not original generation time) — this means the enhanced brief lives longer than the original deterministic would have, which is the intended behavior.

## 9. State Persistence

### 9.1 New DB table

```sql
-- db/migrations/<timestamp>_add_user_editorial_state.sql

CREATE TABLE user_editorial_state (
  user_id           INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  editorial_memory  JSONB NOT NULL DEFAULT '{}'::jsonb,
  previous_briefs   JSONB NOT NULL DEFAULT '{}'::jsonb,  -- map: portfolio_id (string) → brief blob
  created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_editorial_state_updated ON user_editorial_state(updated_at);
```

**Why `user_id` as PK**: one row per user, upsert-friendly, no surrogate key churn. Editorial state is inherently per-user singleton.

**Why JSONB (not separate columns)**: The AI writes the full memory blob each update, and the schema will evolve as we discover what the analyst actually needs to remember. Locking columns now would require migrations on every schema iteration. JSONB gives us flexibility while keeping the table queryable via `->` operators.

**Why `previous_briefs` is a JSONB map keyed by portfolio_id (corrected from earlier draft)**: an earlier draft used a single `previous_brief JSONB` column, but the brief cache is keyed `(user_id, portfolio_id)` and a user can have multiple portfolios. A single column would have one portfolio's generation overwriting another portfolio's diff anchor — making the diff/novelty contract impossible for any multi-portfolio user. The JSONB map shape is `{"portfolio_a": {...brief...}, "portfolio_b": {...brief...}, "default": {...brief...}}` (key `"default"` is used when `portfolio_id` is None). Reads use `previous_briefs->>'<portfolio_id>'`; writes use `jsonb_set(previous_briefs, '{<portfolio_id>}', <new_brief>::jsonb)`. Single-row read for the generator; no join. Novelty scoring only needs the most recent brief per portfolio, not history.

### 9.2 Read & write paths

`core/overview_editorial/editorial_state_store.py`:

```python
def load_editorial_state(user_id: int, portfolio_id: str | None) -> tuple[dict, dict | None]:
    """Returns (editorial_memory, previous_brief_for_this_portfolio).
    editorial_memory is the full per-user memory blob (or seed file fallback).
    previous_brief is the brief stored under this specific portfolio_id key (or None).
    Falls back to editorial_memory_seed.json if row doesn't exist or DB unavailable.
    Pure read — no writes, no side effects."""

def set_editorial_memory(user_id: int, memory: dict) -> None:
    """Chat write path. Upsert editorial_memory for a user; always replaces.
    SQL: INSERT ... ON CONFLICT (user_id) DO UPDATE SET editorial_memory = EXCLUDED.editorial_memory, updated_at = NOW()
    After successful upsert, calls invalidate_brief_cache(user_id) AND fires
    `_invalidate_user_memory_cache(user_id)` callback for the gateway enricher cache (§9.6).
    Soft size validation (WARN if memory > 10KB; does not reject)."""

def seed_editorial_memory_if_missing(user_id: int, seed_memory: dict) -> bool:
    """Auto-seed write path. Inserts editorial_memory ONLY if no row exists; no-op otherwise.
    SQL: INSERT ... ON CONFLICT (user_id) DO NOTHING
    Returns True if a row was created, False if a row already existed.
    After successful insert, calls invalidate_brief_cache(user_id) AND fires
    `_invalidate_user_memory_cache(user_id)` callback for the gateway enricher cache (§9.6)."""

def set_previous_brief(user_id: int, portfolio_id: str | None, brief: dict) -> None:
    """Store the just-generated brief as the previous_brief for this (user, portfolio).
    Called at the END of the cold path (§9.3). Becomes the diff anchor for the NEXT generation.
    SQL: INSERT ... ON CONFLICT (user_id) DO UPDATE
         SET previous_briefs = jsonb_set(
             COALESCE(user_editorial_state.previous_briefs, '{}'::jsonb),
             ARRAY[%s],  -- portfolio_id key (or 'default' if portfolio_id is None)
             %s::jsonb   -- new brief blob
         )
    Does NOT invalidate the brief cache — the brief itself is being generated, no need to invalidate."""
```

`load_editorial_state` is called by the orchestrator at §5.1 step 6 with the current `portfolio_id`. `set_editorial_memory` is called by the MCP write tool (§9.5). `seed_editorial_memory_if_missing` is called by the auto-seeder (§9.7). `set_previous_brief` is called synchronously at the END of the cold path (§9.3).

**Concurrency story**: The race between chat writes (`set_editorial_memory`) and auto-seed (`seed_editorial_memory_if_missing`) is safe by design (§3.5). Chat writes use REPLACE upsert; auto-seed uses INSERT-only. Both are single Postgres statements — no read-modify-write window.

### 9.3 Previous brief rotation — DB-sourced anchor, durable across cache misses

**Corrected from earlier drafts**: an earlier version of this section sourced the rotation from the in-memory cache, which is wrong because the cold path only runs on cache miss — the cache value is `None` by definition at that point, so the rotation persisted nothing. After a TTL expiry or process restart, the diff anchor would be lost. The correct source is the DB.

**The contract**: `user_editorial_state.previous_briefs->>'<portfolio_id>'` always holds **the brief that was generated by the most recent prior cold-path run for this `(user_id, portfolio_id)`**. The current cold path reads it as the diff/novelty anchor at step 6, generates a new brief, then writes the new brief into that slot at the end. The "rotation" is just "the new brief becomes the anchor for the next generation."

**This works across cache misses** because the DB is the source of truth, not the in-memory cache. After a TTL expiry, the next cold path still finds the previous brief in the DB and uses it as the anchor.

**Cold path rotation logic** (§5.1 step 14):

```python
# inside actions/overview_brief.get_brief() cold path:

# Step 6 (already happens): read the current diff anchor from DB
editorial_memory, previous_brief_anchor = load_editorial_state(user_id, portfolio_id)
# previous_brief_anchor may be None (first ever generation for this portfolio)

# Steps 8-11: compose new brief, score against previous_brief_anchor for novelty
new_brief = compose_deterministic_brief(
    portfolio_context,
    editorial_memory=editorial_memory,
    previous_brief=previous_brief_anchor,
)

# Step 12: compute diff using the same anchor (no DB read needed — already loaded)
new_brief.editorial_metadata.changed_slots = diff_function.compute_changed_slots(
    new_brief, previous_brief_anchor
)

# Step 13: write new brief to cache
brief_cache.set_cached_brief(user_id, portfolio_id, new_brief)

# Step 14: rotate — new brief BECOMES the anchor for the NEXT cold generation
set_previous_brief(user_id, portfolio_id, new_brief.model_dump())  # DB write, ~10ms

return new_brief
```

**Note**: the rotation source is `previous_brief_anchor` (read from DB at step 6) for novelty/diff, and `new_brief` (composed at step 11) is what gets WRITTEN as the new anchor. The in-memory cache is irrelevant to rotation — it only serves the warm path.

**Why synchronous, not async**: Rotation is one Postgres upsert (~10ms). If it were async, concurrent cold-path requests would race on rotation order, AND the next cold-path generation could read a stale anchor. Synchronous rotation guarantees that by the time a request returns, the DB anchor is updated for the next request.

**LLM arbiter and rotation**: When the LLM arbiter (§5.1 steps A-G) finishes and replaces the cached brief, it does NOT re-rotate `previous_brief` in DB. The deterministic and enhanced briefs both share the same diff anchor (the previous DB-stored brief), so the diff in `editorial_metadata.changed_slots` is consistent across both. The rotation happens exactly once per cold generation, at step 14.

**Edge cases**:
- **First generation ever for this `(user_id, portfolio_id)`**: `previous_brief_anchor` is None at step 6. Diff function returns `changed_slots = []`. New brief is still rotated into DB (becomes the anchor for the next generation).
- **Cache miss after TTL expiry**: `previous_brief_anchor` is still in DB (from the last cold-path generation). Diff function works correctly because the anchor is durable.
- **Multi-portfolio user**: each portfolio has its own slot in `previous_briefs`. Generation for portfolio A reads/writes `previous_briefs->>'A'`; portfolio B uses `previous_briefs->>'B'`. No cross-portfolio interference.
- **Concurrent cold-path requests for the same `(user_id, portfolio_id)`**: both will rotate; the second one's `set_previous_brief` overwrites the first one's. Both briefs are semantically valid; whichever wins the cache write determines the user-visible state. **§13 risk row: in-flight dedupe (singleflight) is a known Phase 2 enhancement — see §13.**

### 9.4 Seed fallback and founder bootstrap

`config/editorial_memory_seed.json` is the default memory for any user who has not had a conversation with the analyst yet. When `load_editorial_state` finds no row, it returns the seed as-is. The first `update_editorial_memory` call for that user creates the row and memory becomes per-user from then on.

For the founder specifically, Phase 1 pre-seeds `user_id=1` with the current `editorial_memory_seed.json` via a one-off script (`scripts/seed_founder_editorial_memory.py`) so the founder's brief is immediately personalized without requiring a bootstrap conversation. All other users get the seed fallback until they talk to the analyst.

### 9.5 MCP write tool — `update_editorial_memory`

```python
# mcp_tools/overview_editorial.py

@mcp.tool(name="update_editorial_memory")
def update_editorial_memory(new_memory: dict[str, Any]) -> dict[str, Any]:
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
    user = ctx.user
    set_editorial_memory(user.id, new_memory)
    return {"status": "ok", "memory_size_bytes": len(json.dumps(new_memory))}
```

The tool is registered in the MCP gateway and exposed to the analyst chat. Chat infrastructure is unchanged. The `context_enricher` in `routes/gateway_proxy.py` already reads memory per-user (Phase 1 extension: instead of always reading the seed file, read from DB first, fall back to seed).

**Gateway enricher extension** (~20 lines in `routes/gateway_proxy.py`).

**Current state** (verified): `_enrich_context` at `routes/gateway_proxy.py:23-36` is **synchronous** and has **no DB access**. It reads `config/editorial_memory_seed.json` from disk on every chat message (~1ms). It runs on every chat request.

**Phase 1 implementation choice — sync with per-process cache**:
```python
# routes/gateway_proxy.py — extended

# Process-local cache: avoids DB hit on every chat message.
# Invalidated by set_editorial_memory() via a registered callback.
_MEMORY_CACHE: dict[int, dict] = {}

def _load_user_memory_cached(user_id: int) -> dict:
    if user_id not in _MEMORY_CACHE:
        # Gateway only needs editorial_memory, not previous_brief_anchor.
        # Pass portfolio_id=None — load_editorial_state ignores portfolio_id when only memory is consumed.
        memory, _ = load_editorial_state(user_id, portfolio_id=None)  # sync DB read
        _MEMORY_CACHE[user_id] = memory
    return _MEMORY_CACHE[user_id]

def _invalidate_user_memory_cache(user_id: int) -> None:
    """Called by set_editorial_memory() after a successful upsert."""
    _MEMORY_CACHE.pop(user_id, None)

def _enrich_context(request, user, context):
    user_id = getattr(user, "id", None) or (user.get("user_id") if isinstance(user, dict) else None)
    if user_id:
        try:
            context["editorial_memory"] = _load_user_memory_cached(user_id)
        except Exception:
            _logger.warning("editorial_memory DB read failed for user %s", user_id, exc_info=True)
            if _EDITORIAL_MEMORY_SEED_PATH.exists():
                context["editorial_memory"] = json.loads(_EDITORIAL_MEMORY_SEED_PATH.read_text())
    elif _EDITORIAL_MEMORY_SEED_PATH.exists():
        context["editorial_memory"] = json.loads(_EDITORIAL_MEMORY_SEED_PATH.read_text())
    return context
```

**Why sync + per-process cache, not async**: Making `_enrich_context` async would require plumbing `async def` through the gateway router (`app_platform/gateway/proxy.py`) which is a much wider change than Phase 1 wants. A per-process in-memory cache (one entry per user, evicted on every write to `user_editorial_state`) keeps the per-message latency at ~0ms after first hit, with one DB read per user per process restart.

**Cache invalidation wiring** — both write paths must register the callback:
```python
# core/overview_editorial/editorial_state_store.py — module init

from routes.gateway_proxy import _invalidate_user_memory_cache

def set_editorial_memory(user_id: int, memory: dict) -> None:
    _do_replace_upsert(user_id, memory)
    invalidate_brief_cache(user_id)
    _invalidate_user_memory_cache(user_id)  # gateway enricher cache

def seed_editorial_memory_if_missing(user_id: int, seed: dict) -> bool:
    inserted = _do_insert_only_upsert(user_id, seed)
    if inserted:
        invalidate_brief_cache(user_id)
        _invalidate_user_memory_cache(user_id)  # gateway enricher cache (chat → next message reads fresh)
    return inserted
```

**BOTH writers fire the gateway cache callback.** If only `set_editorial_memory` invalidated the cache, a process that had cached the seed-file fallback for a new user would stay stale even after auto-seed creates the DB row. Both call sites are required.

**Multi-process note**: With multiple gateway processes, each process has its own `_MEMORY_CACHE`. After a write in process A, process B's cache stays stale until process B's entry expires (no per-message TTL today — the cache is eternal until explicit invalidation). **Phase 1 acceptance**: the founder and small beta cohort run single-process. If multi-process becomes a requirement before Phase 2 ships, switch to a Redis-backed cache or use Postgres LISTEN/NOTIFY. Documented in §13 risks. (Earlier drafts of this section incorrectly claimed reconnects refresh the cache — the cache key is `user_id`, not session_id, so reconnecting does nothing. That sentence has been removed.)

### 9.6 Analyst skill prompt update

The existing `workspace/notes/skills/morning-briefing.md` skill file is extended with one section:

> **Maintaining editorial_memory**
>
> You have access to `editorial_memory` in your context. It captures how this user thinks about investing. You also have a tool `update_editorial_memory(new_memory)` that writes to it.
>
> Update memory when the user tells you something worth remembering about their preferences, goals, risk tolerance, focus, or recent actions. You decide when — no confirmation needed. Read the current memory, merge your changes, pass the full updated blob.
>
> If memory grows past ~10KB, prune the oldest `conversation_extracts` entries.
>
> If the user corrects something ("actually I don't care about dividends"), update memory accordingly.

### 9.7 Auto-seeding from portfolio composition

New users with no `user_editorial_state` row get a one-shot LLM pass that infers initial editorial preferences from their portfolio composition. Fires on first brokerage sync completion or first CSV import, runs as a background task, writes to DB. Next Overview load uses the auto-seeded memory instead of the founder-flavored fallback.

**Why**: Without this, new users see a founder-flavored brief until they happen to have a conversation with Hank. The first impression is wrong — someone else's editorial preferences are driving their briefing. Auto-seeding produces a personalized brief from the moment they open the Overview. Conversation refines from there.

**Trigger conditions** (all must be true):
1. `user_editorial_state` row does NOT exist for this user
2. Portfolio has meaningful positions (skip if empty or trivially small — e.g., < 3 positions or < $1000 total value)
3. Post-sync callback or CSV import completion event fires

**Module**: `core/overview_editorial/memory_seeder.py`

```python
def auto_seed_from_portfolio(user_id: int) -> dict | None:
    """One-shot LLM pass that infers editorial preferences from portfolio composition.

    Returns the seeded memory blob on success, None on any failure (LLM error, empty portfolio,
    row already exists, validation failure). Idempotent — safe to call multiple times.

    Concurrency-safe by design: writes via seed_editorial_memory_if_missing() which uses
    INSERT ... ON CONFLICT DO NOTHING. Cannot clobber an existing chat-driven write.

    Steps:
      1. Early-exit if user_editorial_state row already exists (check before LLM call)
      2. Gather portfolio composition summary (positions, sectors, exposures, risk)
      3. Call LLM with constrained prompt asking for initial editorial_memory
      4. Validate LLM output with Pydantic (EditorialMemory model)
      5. seed_editorial_memory_if_missing(user_id, seeded_memory) → INSERT ... ON CONFLICT DO NOTHING
         (cannot clobber a chat-driven write that landed first; auto-seed silently no-ops in that case)
      6. invalidate_brief_cache(user_id) so the next brief uses the seeded memory
      7. Log telemetry event
    """
```

**Portfolio composition summary** (what the LLM sees): gathered via a helper that wraps existing cached builders, not a new data layer.

```python
def build_portfolio_composition_summary(user_id: int) -> dict:
    """Returns a compact, LLM-friendly summary:
      - top_positions: top 10 by weight with ticker, sector, weight
      - asset_allocation: {equity, bond, cash, other} percentages
      - sector_concentration: HHI + top-3 share
      - geographic_mix: {us, international, em}
      - factor_exposures: beta, size, value, momentum (if available)
      - risk_summary: volatility, max_drawdown, risk_score
      - performance_summary: ytd_return, sharpe, alpha (if available)
      - position_count: int
      - portfolio_value: float
    """
```

All fields come from existing cached snapshots — `PositionService.get_all_positions()`, `result_cache.get_analysis_result_snapshot()`, `result_cache.get_performance_result_snapshot()`. No new providers.

**LLM prompt** — constrained, structured output, Pydantic validation. Stored inline in `memory_seeder.py` (or `workspace/notes/skills/editorial-memory-seeder.md` if we want it editable like the morning-briefing skill). Key instructions:

> You are inferring an initial editorial_memory for a new user from their portfolio composition. Be conservative. Only populate fields the portfolio directly reveals. Leave fields requiring user intent (time_horizon, primary_goals, experience_level) empty — those come from conversation.
>
> Infer:
> - `investor_profile.style`: "active_stock_picker" if mostly single names, "passive_index" if mostly ETFs, "mixed" otherwise
> - `investor_profile.risk_tolerance`: "high" if volatility > 25%, "low" if mostly bonds/cash, "moderate" otherwise
> - `editorial_preferences.lead_with`: up to 2 categories based on biggest signals (concentration if HHI > 0.15, risk if drawdown > 10%, performance if YTD return > 15% or < -10%)
> - `editorial_preferences.care_about`: 3-4 categories inferred from composition
> - `current_focus.watching`: specific tickers or themes from outlier positions
>
> Do NOT infer:
> - `editorial_preferences.less_interested_in` (can't tell from portfolio what the user ignores)
> - `investor_profile.time_horizon`, `primary_goals`, `concerns`
> - `current_focus.recent_actions`, `upcoming`
>
> Include exactly one `conversation_extracts` entry noting this was auto-seeded, with a one-line summary of the portfolio signals you observed.

**Field coverage** (what auto-seed populates vs. what's left for conversation):

| Field | Auto-seeded? | Rationale |
|---|---|---|
| `investor_profile.style` | Yes (cautious guess) | Inferable from mix of single names vs ETFs |
| `investor_profile.risk_tolerance` | Yes (volatility-driven) | Inferable from portfolio vol + allocation |
| `investor_profile.time_horizon` | No | Requires user intent |
| `investor_profile.primary_goals` | No | Requires user intent |
| `investor_profile.concerns` | No | Requires user conversation |
| `editorial_preferences.lead_with` | Yes (signal-driven) | Inferable from biggest outliers |
| `editorial_preferences.care_about` | Yes (composition-driven) | Inferable from sector/factor tilts |
| `editorial_preferences.less_interested_in` | No | Cannot infer absence from presence |
| `current_focus.watching` | Yes (outlier positions) | Inferable from concentration outliers |
| `current_focus.recent_actions` | No | Requires transaction history context |
| `current_focus.upcoming` | No | Requires calendar awareness |
| `conversation_extracts` | Yes (one entry) | Auto-seed event itself is the extract |

**Hook points**: same 2 mutation paths that invalidate the brief cache now ALSO trigger auto-seed:

1. **Brokerage sync completion** (`workers/tasks/positions.py:48`, post-`record_success()`): direct synchronous call to `auto_seed_from_portfolio(user_id)`. Runs INSIDE the Celery worker (no FastAPI request context, so `BackgroundTasks` is not available — but Celery itself provides the background runtime, so blocking the worker for an extra 2-3s is acceptable). Adds ~2-3s to the worker task duration on first sync only; subsequent syncs early-exit at step 1.

2. **CSV import completion** (`routes/onboarding.py:810`, post-`import_portfolio()`): uses FastAPI `BackgroundTasks` to dispatch — `background_tasks.add_task(auto_seed_from_portfolio, user_id)`. Does NOT block the import response. The user gets the response quickly; auto-seed runs in the background (typically completes within 2-3s).

**Asymmetry note** (per §3.7): the same function is invoked from two different runtimes (Celery direct vs. FastAPI BackgroundTasks). The function itself is identical; only the call site differs.

**Idempotency**: `auto_seed_from_portfolio` checks for an existing row at step 1 and early-exits. Safe to call repeatedly from multiple hook points. A user whose first sync failed but then succeeded on retry gets seeded on the successful run; a user who imports via CSV and then connects a broker gets seeded on whichever fires first. The `seed_editorial_memory_if_missing` upsert at step 5 is the second safety net — even if the early-exit check races, the upsert will not clobber.

**Failure modes**:

| Failure | Behavior | Fallback |
|---|---|---|
| LLM returns malformed JSON | Log warning, skip seed | `load_editorial_state` returns seed file on next read |
| LLM timeout (> 10s) | Log warning, skip seed | Seed file fallback |
| Portfolio empty or trivially small | Skip seed (early exit) | Seed file fallback until user has real positions |
| Portfolio composition summary fails (cached snapshots unavailable) | Log warning, skip seed | Seed file fallback; next sync will retry |
| Pydantic validation fails on LLM output | Log warning, skip seed | Seed file fallback |
| `user_editorial_state` row created between step 1 and step 5 (race with a chat-driven write) | `seed_editorial_memory_if_missing` upsert with `DO NOTHING` no-ops | Benign; chat write is the authoritative writer |
| User opens Overview in the ~2-3s window before seeding finishes | First brief uses seed file fallback; second brief (after seeding completes) uses auto-seeded memory | Benign race; ship criterion §14 is honest about this window |

**Observability**: auto-seed uses the consolidated `editorial_memory_updated` event defined in §10.1, with `source = "auto_seed"`. Auto-seed-specific signals (portfolio composition the LLM saw, inferred preferences) are appended as optional fields on the same event:

```json
{
  "event": "editorial_memory_updated",
  "user_id": 42,
  "source": "auto_seed",
  "memory_size_bytes": 4231,
  "cache_invalidated": true,
  "auto_seed_trigger": "sync_completion",
  "auto_seed_portfolio_signals": {
    "position_count": 45,
    "top_sector_share": 0.38,
    "hhi": 0.14,
    "volatility": 0.22,
    "ytd_return": -0.08
  },
  "auto_seed_lead_with": ["concentration", "risk"],
  "auto_seed_care_about": ["sector_exposure", "factor_tilt", "single_name_risk"],
  "auto_seed_llm_duration_ms": 2140,
  "auto_seed_llm_model": "claude-haiku-4-5-20251001"
}
```

The `auto_seed_*` fields are only present when `source == "auto_seed"`. For chat writes (`source == "chat_tool"`) and manual scripts (`source == "manual_script"`) they are absent. WARN events on auto-seed skip/failure use a separate `editorial_memory_auto_seed_skipped` event with the skip reason.

**Separation from the MCP write tool**: auto-seeding is server-side, triggered by a sync event, not by a chat tool call. It shares `set_editorial_memory` (the DB write helper) but has its own trigger and its own prompt. Keeping them in separate modules makes each one reviewable independently:
- `memory_seeder.py` = server-initiated, one-shot, portfolio-driven
- `mcp_tools/overview_editorial.py` = chat-initiated, recurring, conversation-driven

### 9.8 Artifact directives

The Overview already renders a set of structured "artifacts" — concentration table, performance attribution, composition mix, tax opportunity, decision — each built via a `buildOverview*ArtifactBrief()` pure function that emits a brief object containing both data and editorial text (`claim`, `interpretation`, `tags`, `exitRamps`, etc.). The editorial pipeline should direct these artifacts: select which to show, in what order, with what annotations and highlights. NOT generate new artifacts, NOT render `:::ui-blocks`, NOT rewrite their internals.

**Honest framing** (corrected after frontend code investigation): the previous draft of this section claimed both the registry plumbing AND the JSX refactor could happen in a "zero-behavior-change prep sub-phase." Investigation showed that's not credible — the artifact JSX in `PortfolioOverviewContainer.tsx:1440-1600` is entangled with `NamedSectionBreak`, `InsightSection`, `ExitRamps`, per-section conditionals, tier gates (`isPaid`), and data-availability gates. Replacing the JSX with a registry loop is a real (small but real) restructure, not a no-op refactor.

**Revised split**:
- **Phase 1a (truly zero behavior change)**: type extension + stable ID assignment + registry stubs. NO JSX changes.
- **Phase 1b (small restructure + editorial threading)**: JSX refactor to use the registry, composition flattening, backend directive threading.

#### 9.8.1 Prep sub-phase 1a — types + registry stubs ONLY (verifiably zero change)

**Goal**: assign stable IDs and extend the type surface so backend directives have a target. Do NOT touch JSX. Independently shippable, regression test trivially passes (no JSX changed).

**Current state (evidence from investigation)**:
- 5 top-level artifacts as inline `useMemo` blocks in `PortfolioOverviewContainer.tsx`: `overviewTaxOpportunityArtifact` (904), `overviewGeneratedArtifact` (1001), `overviewPerformanceArtifact` (1025), `overviewDecisionArtifact` (1136), and `overviewCompositionBrief` (1011).
- Composition has 2 NESTED sub-artifacts inside the same brief object: `overviewCompositionBrief.assetAllocationArtifact` and `overviewCompositionBrief.productTypeArtifact`. They render at lines 1525 and 1530 via `<GeneratedArtifact {...overviewCompositionBrief.assetAllocationArtifact} />`.
- No stable ID strings — identity is implicit via variable name.
- Brief shapes differ per artifact (concentration has `bars/rows/claim/interpretation`; composition has `insight/annotations/assetAllocationArtifact/productTypeArtifact`) — no common "editorial fields" interface.
- Hidden coupling at line 1454: `showExitRamps={!overviewGeneratedArtifact}` — concentration table's exit ramps depend on whether the concentration artifact exists.

**Phase 1a changes**:
1. **New file**: `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/types.ts`
   ```ts
   export interface OverviewArtifactEditorial {
     id: string;
     claim?: string;                   // editable by LLM in Phase 1b
     interpretation?: string;           // editable by LLM in Phase 1b
     annotation?: string | null;       // new: LLM-written editorial note
     highlightIds?: string[];          // new: rows/items to highlight
     editorialNote?: string | null;    // new: top-level context
     visible?: boolean;
     position?: number;
   }
   ```
2. **New file**: `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts`
   - Exports `OVERVIEW_ARTIFACT_REGISTRY: readonly ArtifactDescriptor[]` — ordered list with stable IDs:
     - `overview.concentration`
     - `overview.performance_attribution`
     - `overview.tax_opportunity`
     - `overview.decision`
     - `overview.composition.asset_allocation` (flattened from `overviewCompositionBrief.assetAllocationArtifact`)
     - `overview.composition.product_type` (flattened from `overviewCompositionBrief.productTypeArtifact`)
   - Each descriptor: `{ id, label, builderRef: 'name of existing builder', requiresHooks: string[] }`. In Phase 1a, `builderRef` is purely metadata — the registry does not yet drive rendering.
3. **Existing brief types extend the interface** (additive only): `OverviewConcentrationArtifactBrief`, `OverviewCompositionBrief`, `OverviewPerformanceArtifactBrief`, etc. each gain an optional `editorial?: OverviewArtifactEditorial` field. Existing builders don't populate it; existing JSX doesn't read it. **Zero behavior change.**
4. **No JSX changes in `PortfolioOverviewContainer.tsx`**. The container continues to hand-roll the JSX exactly as today. The registry exists as a metadata reference for Phase 1b.
5. **Regression test**: trivial — DOM is byte-identical to current because nothing is rendered differently.

**What Phase 1a explicitly does NOT do**:
- No JSX changes.
- No backend changes.
- No brief payload changes.
- No registry-driven rendering.
- No composition flattening at the data level (composition brief still nests its sub-artifacts; the registry just records the flat IDs).

**Why this is shippable on its own**: it's purely additive types + a metadata file. If Phase 1 stalls on the editorial pipeline, Phase 1a still leaves the codebase in a slightly better state (stable artifact IDs available for any future work).

#### 9.8.2 Phase 1b — JSX refactor + composition flattening + editorial threading

Phase 1b is the real work. Honest scope: this is a small but real frontend restructure that ships together with the backend directive plumbing.

**Changes**:
1. **Composition flattening**: `buildOverviewCompositionBrief()` is refactored to return TWO separate artifact briefs (one for asset allocation, one for product type) instead of one composite brief with nested sub-artifacts. The shared `insight` and `annotations` move into a new "composition section header" piece that's rendered separately from the artifacts. **This is a real behavior risk** — the regression test must verify identical DOM for the composition section.
2. **Container refactor (`PortfolioOverviewContainer.tsx:1440-1600`)**:
   - Preserve all chrome elements (`NamedSectionBreak`, `InsightSection`, `ExitRamps`, `OverviewSectionLoadingPlaceholder`, tier gates `isPaid && shouldShowMarketContext`, etc.) as hand-rolled JSX.
   - Replace the hand-rolled artifact JSX (the 5 `<GeneratedArtifact {...x} />` blocks) with a registry-driven loop that takes `(registry, directives) → ordered list of artifacts to render`.
   - Preserve the hidden coupling at line 1454 (`showExitRamps={!overviewGeneratedArtifact}`) by having the registry loop expose a `concentrationArtifactRendered` boolean that the chrome JSX reads.
   - Phase 1b directives may be empty (no backend yet) — registry defaults match current order.
3. **Wire schema**: `artifact_directives: list[ArtifactDirective]` on `OverviewBrief` (already in §7).
4. **Container directive application**: when `useOverviewBrief` returns a brief with non-empty `artifactDirectives`, the registry loop applies `visible`, `position`, `annotation`, `highlightIds`, `editorialNote` over the registry default. If directives are empty (Phase 1b initial state, before backend emits them), defaults match Phase 1a behavior.
5. **Generator directive emission**: Phase 1 generators optionally emit `ArtifactDirective` in their `InsightCandidate.content` payload. The editorial policy layer collects emitted directives, deduplicates by `artifact_id` (keep the highest-scoring candidate's directive), and attaches to the final brief.
6. **LLM arbiter extension**: the arbiter prompt learns to emit up to 2 `annotation` strings on directed artifacts + reorder/highlight based on the portfolio story. Pydantic validates the structured output.
7. **Frontend highlight rendering**: existing artifact components get a lightweight `highlightedIds` prop — rows in the prop set get a subtle background tint or "eye" affordance. Non-invasive (no layout change).
8. **Regression test**: `PortfolioOverviewContainer.test.tsx` verifies the refactored container produces DOM identical to the current implementation when `artifactDirectives === []` for a fixed portfolio fixture. This is the gating test for Phase 1b.

**Phase 1 scope limits on the editorial sub-phase**:
- LLM can write `annotation` strings but NOT rewrite `claim` or `interpretation` — those stay deterministic from the builders. Phase 2 extends arbiter authority.
- LLM can reorder and hide artifacts but NOT add new ones. The registry is the universe.
- `highlight_ids` is limited to ticker strings present in the artifact's existing rows — no DOM-level highlighting of arbitrary elements.
- Generators emit directives cautiously — empty list is valid and common.

**Failure modes**:

| Failure | Fallback |
|---|---|
| Backend directive references unknown `artifact_id` | Frontend ignores silently, logs WARN |
| `highlight_ids` references a row that doesn't exist in the artifact | Highlight skipped, no crash |
| Directive `position` out of range | Clamped to registry bounds |
| `visible: false` on a required artifact (e.g., concentration is empty and hidden) | Respected; the user sees fewer artifacts |
| LLM arbiter emits malformed directives | Pydantic fails → deterministic brief stands, directive list empty |
| Registry `builder` throws | Artifact skipped, logged; other artifacts still render |
| Composition flattening regresses the section header layout | Caught by regression test in Phase 1b CI; revert to nested if needed |

### 9.9 Chat margin annotations

`ChatMargin.tsx` renders a hardcoded `VIEW_CONTEXT` record keyed by `ViewId` — each view has static `label`, `askLabel`, `note`, `update`, `prompts[]`, `related[]`. The content is editorial-quality already (good prose, specific to the view) but it's the same every time for every user and every portfolio state. The editorial pipeline should be able to inject per-brief margin annotations anchored to specific slots or artifacts.

**Architecture correction** (after frontend code investigation): the previous draft of this section said `PortfolioOverviewContainer` would thread annotations directly into `ChatMargin`. **That's wrong** — `ChatMargin` is owned by `ModernDashboardApp.tsx:685`, NOT by the Overview container. The container has no direct ownership of the margin and cannot pass props to it.

**Verified facts**:
- `ChatMargin` is mounted in `ModernDashboardApp.tsx:685` as a grid sibling (column 3) of the main content (column 2). NOT nested inside any view container.
- Props passed today: `activeView` (from `useActiveView()` uiStore), `onOpenFullChat` (callback), `summary` (from `chatMarginSummary` useMemo at lines 321-354, derived from `usePortfolioSummary` + `usePerformance`), `featuredEvent` (from `useMarketIntelligence`).
- **`ChatMargin` IS coupled to chat state** (corrected from earlier draft). At `ChatMargin.tsx:9` it imports `useSharedChat` from `../chat/ChatContext`; at line 1328 it destructures `messages`, `sendMessage`, `chatStatus` from the hook; at line 1331 it derives `recentMessages` from the message stream; and at lines 1360, 1371, 1394, 1410 it calls `sendMessage(...)` to inject prompts directly into the active chat thread. The margin is not a passive sidebar — it is an interactive chat surface that shares state with the main chat panel.
- **Implication for the editorial pipeline**: the store-bridge architecture below is still the correct approach, but the rationale is NOT "ChatMargin is decoupled from chat." The rationale is "ChatMargin is mounted by the app shell, so the Overview container has no direct ownership path; the store bridge is needed because of mount-point ownership, not chat-state isolation."
- The Phase 1 editorial pipeline does NOT touch the chat-state coupling. Annotations are an additive prop alongside the existing `useSharedChat` integration. When the user clicks an `ask_about` annotation with a `prompt` field, the most natural Phase 1 wiring is to call the existing `sendMessage(prompt)` from inside `ChatMargin` (it already has the function from `useSharedChat`) — the annotation just provides the prompt text.

**Threading via shared store** (replaces the original "container threads in" approach): annotations flow from the Overview to the margin via a new Zustand store in `frontend/packages/connectors/src/stores/overviewBriefStore.ts`, following the existing `scenarioWorkflowStore` precedent. The Overview writes annotations when a brief arrives; `ModernDashboardApp` reads them and passes to `ChatMargin` via a new prop.

This is a **prep sub-phase + editorial sub-phase** split, similar to §9.8 but the prep shape is different (it's pure prop additions + a new store, not a JSX restructure).

#### 9.9.1 Prep sub-phase (pure prop additions + new store, zero behavior change)

**Prep changes**:

1. **New Zustand store** at `frontend/packages/connectors/src/stores/overviewBriefStore.ts` — pattern copied from `scenarioWorkflowStore`:
   ```ts
   import { create } from 'zustand';
   import { devtools } from 'zustand/middleware';

   export interface MarginAnnotationUI {
     anchorId: string;                         // "lead_insight" | "metric.return" | "artifact.overview.concentration"
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
           marginAnnotationsByPortfolioId: { ...s.marginAnnotationsByPortfolioId, [portfolioId]: annotations },
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
   Exported from `frontend/packages/connectors/src/index.ts` so both the Overview container and `ModernDashboardApp` can import it.

2. **Extend `ChatMargin` props** to accept an optional `annotations?: MarginAnnotationUI[]`:
   ```ts
   // ChatMargin.tsx
   interface ChatMarginProps {
     activeView: ViewId;
     onOpenFullChat: () => void;
     summary?: SummarySnapshot | null;
     featuredEvent?: {...} | null;
     annotations?: MarginAnnotationUI[];        // NEW — Phase 1a default undefined
   }
   ```
   - Fallback behavior: when `annotations` is `undefined` or empty, `ChatMargin` uses `VIEW_CONTEXT[activeView]` exactly as today. Zero regression.
   - When `annotations` is non-empty: render them as margin blocks above the existing `VIEW_CONTEXT` content. Phase 1 rendering is a simple list (one block per annotation); DOM-level positional anchoring is deferred.

3. **Anchor registry**: new file `frontend/packages/ui/src/components/design/marginAnchors.ts` — a const of known anchor IDs the backend can target. Prevents typos.

4. **`ModernDashboardApp.tsx` minimal extension**: read `useOverviewBriefStore((s) => s.marginAnnotationsByPortfolioId[currentPortfolio?.id ?? ''])` and pass into `<ChatMargin annotations={...} />`. **Phase 1a always returns empty** because no writer exists yet — zero behavior change.

5. **Regression test**: `ChatMargin` renders byte-identical output for `annotations={[]}`, `annotations={undefined}`, or no `annotations` prop at all. `ModernDashboardApp` test verifies the prop is passed correctly (mocked store returns empty).

**What the prep sub-phase does NOT do**:
- No DOM-level anchor resolution.
- No backend integration.
- No writes to the store from `PortfolioOverviewContainer` (that's the editorial sub-phase).
- `VIEW_CONTEXT` stays in place as the fallback.

#### 9.9.2 Editorial sub-phase

1. **Wire schema**: `margin_annotations: list[MarginAnnotation]` on `OverviewBrief` (already in §7).
2. **Container writes to store**: when `useOverviewBrief` returns a brief, `PortfolioOverviewContainer` calls `useOverviewBriefStore().setMarginAnnotations(currentPortfolio.id, brief.marginAnnotations)`. On unmount or portfolio change, calls `clearMarginAnnotations(portfolioId)`.
3. **App shell reads from store**: `ModernDashboardApp` already reads from the store in Phase 1a. With the editorial sub-phase active, the store will start having non-empty entries, and the existing pass-through prop will start delivering them to `ChatMargin`.
4. **Generator emission**: Phase 1 generators optionally emit `MarginAnnotation` candidates. Policy layer collects them, deduplicates by `anchor_id`, attaches to the final brief.
5. **LLM arbiter**: arbiter prompt learns to write 1–2 margin annotations per brief (typically `ask_about` prompts anchored to the lead insight or the top artifact).
6. **Anchor resolution** (limited): margin annotations with `anchor_id = "lead_insight"` or `anchor_id = "artifact.*"` render in the margin at the top of the panel above `VIEW_CONTEXT` content. DOM-level positional anchoring is Phase 2.

**Phase 1 scope limits**:
- Annotations render as a list in the margin, not positioned next to their anchor DOM element.
- Only 3 annotation types: `ask_about`, `editorial_note`, `context`.
- Maximum 3 annotations per brief (policy layer enforces).
- **Click-to-ask uses the existing `useSharedChat()` integration inside `ChatMargin`**: when the user clicks an `ask_about` annotation with a `prompt` field, `ChatMargin` calls `sendMessage(prompt)` directly via the same `useSharedChat` hook it already uses (lines 1328, 1360, 1371, 1394, 1410 in `ChatMargin.tsx`). This matches the verified ChatMargin coupling above. No new chat infrastructure, no `setActiveView('chat')` navigation — the message lands in the active chat thread immediately, the same way the existing static `VIEW_CONTEXT` prompts work today.

**Why this architecture is cleaner**:
- The Overview container does NOT need to know about `ChatMargin` — it just writes to a store keyed by portfolio_id.
- `ModernDashboardApp` does NOT need to know about the editorial pipeline — it just reads a store and passes a prop.
- The store is the contract between the two surfaces, exactly the same way `scenarioWorkflowStore` bridges scenario tools and the workflow panel today.
- If the Overview container is ever moved or replaced, the margin annotation flow is unaffected as long as some writer pushes into the store.

**Failure modes**:

| Failure | Fallback |
|---|---|
| Empty annotations list (or store entry missing) | `VIEW_CONTEXT` default stands |
| Unknown `anchor_id` | Annotation renders anyway at top of margin; logged WARN |
| Annotation list > 3 items | Policy layer caps; extras dropped with INFO log |
| LLM arbiter emits malformed annotation | Pydantic fails → deterministic annotations stand (or empty list) |
| `ChatMargin` is not mounted (e.g., narrow viewport) | Store still gets written; nothing rendered; no error |
| User switches portfolios mid-session | `clearMarginAnnotations(oldPortfolioId)` on unmount; new portfolio's annotations populate on next brief fetch |

### 9.10 Diff view — "what changed since yesterday"

CEO review cherry-pick #1: surface what changed in the brief versus the previous generation. The infrastructure is already in place (`previous_brief` stored in `user_editorial_state`, §9.1); this section covers the render contract.

**Scope**: render subtle visual markers on slots whose content differs from the previous brief. No dedicated "diff modal" or detailed changelog — just an inline affordance the user can notice at a glance.

**Backend**:
1. During brief generation, the orchestrator loads `previous_brief_anchor` from `user_editorial_state.previous_briefs->>'<portfolio_id>'` (already part of §5.1 cold path step 6). After the new brief is composed, a diff function compares slot-by-slot:
   - `metric_strip` items: compare by `id`. Mark `tone_changed` or `value_changed` (both produce a "changed" marker on the UI).
   - `lead_insight.headline`: if different string → `lead_insight_changed = True`.
   - `artifact_directives`: compare by `artifact_id`. Mark `changed_from_previous = True` on any directive whose `annotation`, `highlight_ids`, `position`, or `visible` differs.
   - `margin_annotations`: compare by `anchor_id`. Mark `changed_from_previous = True` on any new or modified annotation.
2. Diff metadata is set inline on the brief fields (see §7 — `ArtifactDirective.changed_from_previous`, `MarginAnnotation.changed_from_previous`). A new `EditorialMetadata` field `changed_slots: list[str]` lists all changed slot IDs for overall rendering.
3. On first-ever generation (no `previous_brief`), all fields are flagged as NOT changed (false everywhere) — the first brief doesn't need diff markers.

**Frontend**:
1. Container reads `brief.editorialMetadata.changedSlots` to know which slots have markers.
2. Metric strip: items in `changedSlots` get a small "↑ changed" pill or a subtle dot indicator — design TBD in implementation plan, but non-intrusive.
3. Lead insight: if `"lead_insight"` is in `changedSlots`, a tiny "new today" affordance appears next to the headline.
4. Artifact directives: registry renderer reads `directive.changedFromPrevious` and draws a subtle border accent on changed artifacts.
5. Margin annotations: annotations with `changedFromPrevious = true` get a small "new" tag in the margin.

**What the diff view is NOT**:
- NOT a standalone diff page or modal.
- NOT a full changelog — it's a glance-level "this is different from yesterday" signal.
- NOT interactive — clicking a marker does not open a diff panel. Phase 2 could add that.
- NOT historical beyond the single `previous_brief` slot — we don't track a week of briefs, only "what's different from most-recent."

**Phase 1 scope limits**:
- The first load after cache invalidation compares against whatever was last stored in `previous_briefs[portfolio_id]` (could be from earlier today if cache was invalidated by a sync, or from yesterday if TTL expired). The DB is the durable anchor, not the cache.
- `previous_brief` rotation logic: at step 6 the cold path reads the existing anchor from DB; at step 12 the diff is computed against that anchor; at step 14 the NEW brief is written into the DB slot, becoming the anchor for the NEXT generation. See §9.3 for the full rotation contract.
- LLM-enhanced briefs and deterministic briefs share the same diff anchor (the previous DB-stored brief), so the `changed_slots` field is consistent whether the user sees the deterministic or enhanced version. The enhanced brief does NOT re-rotate the anchor.

**Failure modes**:

| Failure | Fallback |
|---|---|
| `previous_brief` is None (first ever generation) | All flags false; no markers rendered |
| `previous_brief` has a schema mismatch (version drift) | Diff function treats all slots as "changed"; logged WARN |
| Diff computation throws | No markers rendered; brief still returns; logged WARN |

## 10. Observability

Phase 1 includes structured logging but NOT engagement tracking (deferred to Phase 2 per CEO review decision).

### 10.1 Logging

Every brief generation emits a single structured log entry at INFO. **All fields below are required for the §14 ship criteria to be auditable.**

```json
{
  "event": "overview_brief_generated",
  "user_id": 42,
  "portfolio_id": "p_abc",
  "cache_state": "miss",
  "data_status": {"positions": "loaded", "risk": "loaded", "performance": "partial"},
  "candidates_by_category": {"concentration": 3, "risk": 4, "performance": 2},
  "lead_insight_category": "concentration",
  "lead_insight_score": 0.82,
  "selection_reasons": ["DSU 18% weight exceeds memory.concern threshold"],
  "editorial_memory_present": true,
  "previous_brief_present": true,
  "directive_count": 2,
  "annotation_count": 1,
  "changed_slots_count": 3,
  "llm_enhanced": false,
  "duration_ms": 2341
}
```

Field references for the §14 ship criteria:
- `lead_insight_category` — variety check ("at least 3 distinct categories over 5 days")
- `directive_count` — average of ≥1 over 7 days
- `annotation_count` — average of ≥1 over 7 days
- `changed_slots_count` — non-zero on ≥30% of briefs over 7 days
- `cache_state` + `duration_ms` — cold vs warm latency
- `data_status` — `partial`/`failed` rate

When the LLM arbiter completes (async), a second log entry:

```json
{
  "event": "overview_brief_enhanced",
  "user_id": 42,
  "portfolio_id": "p_abc",
  "llm_model": "claude-haiku-4-5-20251001",
  "llm_duration_ms": 1823,
  "parse_success": true,
  "duration_ms": 1850
}
```

`parse_success` is the field for the §14 "≥90% over 7-day window" criterion.

When the editorial memory is updated (chat write or auto-seed), a third event:

```json
{
  "event": "editorial_memory_updated",
  "user_id": 42,
  "source": "chat_tool",
  "memory_size_bytes": 4231,
  "cache_invalidated": true
}
```

`source` is one of `"chat_tool"` (MCP `update_editorial_memory`), `"auto_seed"` (`seed_editorial_memory_if_missing`), or `"manual_script"` (founder bootstrap or admin tool). The `cache_invalidated` field reflects whether `invalidate_brief_cache(user_id)` AND `_invalidate_user_memory_cache(user_id)` were both called successfully.

When `source == "auto_seed"`, the event carries additional fields documenting what the LLM saw and inferred (see §9.7 for the full shape):
- `auto_seed_trigger`: "sync_completion" | "csv_import"
- `auto_seed_portfolio_signals`: composition summary the LLM saw
- `auto_seed_lead_with`, `auto_seed_care_about`: inferred preferences
- `auto_seed_llm_duration_ms`, `auto_seed_llm_model`

These fields are absent for `chat_tool` and `manual_script` sources.

When auto-seed is **skipped** (early exit, LLM error, validation failure), a WARN event is emitted instead:

```json
{
  "event": "editorial_memory_auto_seed_skipped",
  "user_id": 42,
  "reason": "row_already_exists" | "portfolio_too_small" | "llm_timeout" | "llm_parse_failed" | "composition_summary_failed",
  "trigger": "sync_completion" | "csv_import"
}
```

This is the canonical event for §14 ship criteria covering both chat writes AND auto-seed activity. There is NO separate `editorial_memory_auto_seeded` event — that name was used in earlier drafts but has been consolidated into `editorial_memory_updated` with `source == "auto_seed"`.

Failure events (see §5.4) log at WARN/ERROR with the event name in the table.

### 10.2 Metrics we care about (not Phase 1 instrumented, but enabled by the logs above)

- Brief generation latency (p50/p95/p99) — cold vs warm
- LLM arbiter success rate
- LLM arbiter latency
- Generator failure rate (per generator)
- Category distribution of `lead_insight_category` — validates that the editorial model produces variety
- `data_status == "partial"` / `"failed"` rate

These become dashboards in Phase 2 (or whenever observability tooling is chosen).

## 11. File Boundaries

**New files (backend):**
- `db/migrations/<timestamp>_add_user_editorial_state.sql`
- `models/overview_editorial.py` — Pydantic models (OverviewBrief, InsightCandidate, etc.)
- `core/overview_editorial/__init__.py`
- `core/overview_editorial/context.py` — `PortfolioContext`
- `core/overview_editorial/orchestrator.py` — `DataGatheringOrchestrator`
- `core/overview_editorial/generators/__init__.py`
- `core/overview_editorial/generators/base.py` — `InsightGenerator` Protocol
- `core/overview_editorial/generators/concentration.py`
- `core/overview_editorial/generators/risk.py`
- `core/overview_editorial/generators/performance.py`
- `core/overview_editorial/policy.py` — `EditorialPolicyLayer`
- `core/overview_editorial/llm_arbiter.py` — LLM arbiter
- `core/overview_editorial/brief_cache.py` — TTLCache + `invalidate_brief_cache`
- `core/overview_editorial/editorial_state_store.py` — DB read/write for `user_editorial_state` (load + `set_editorial_memory` + `set_previous_brief`)
- `actions/overview_brief.py` — business action
- `routes/overview.py` — `GET /api/overview/brief`
- `core/overview_editorial/memory_seeder.py` — `auto_seed_from_portfolio` + `build_portfolio_composition_summary`
- `mcp_tools/overview_editorial.py` — `update_editorial_memory` MCP tool
- `scripts/seed_founder_editorial_memory.py` — one-off founder bootstrap
- `tests/core/overview_editorial/` — unit tests per module
- `tests/core/overview_editorial/test_memory_seeder.py` — auto-seed unit tests
- `tests/actions/test_overview_brief.py` — integration test
- `tests/mcp_tools/test_update_editorial_memory.py` — MCP tool test

**Modified files (backend)** (file:line locations verified by code investigation):
- `workers/tasks/positions.py:48` — direct calls to `invalidate_brief_cache(user_id)` + `auto_seed_from_portfolio(user_id)` after `record_success()` returns inside the `sync_provider_positions()` Celery task
- `routes/onboarding.py:810` — `invalidate_brief_cache(user_id)` direct call + `background_tasks.add_task(auto_seed_from_portfolio, user_id)` after `import_portfolio()` returns inside `/import-csv` and `/import-csv-full` handlers
- `app.py` / router registration — mount `overview_router`; ensure `BackgroundTasks` is wired into the new `/api/overview/brief` endpoint
- `routes/gateway_proxy.py` — `_enrich_context` extended with `_load_user_memory_cached()` per-process cache + `_invalidate_user_memory_cache()` callback registered with `set_editorial_memory` (§9.6)
- `workspace/notes/skills/morning-briefing.md` — add "Maintaining editorial_memory" section with the prompt instruction in §9.6
- MCP tool registry — register `update_editorial_memory`
- `services/portfolio/result_cache.py` — verified: `clear_result_snapshot_caches()` already exists at module level. `invalidate_brief_cache` will call it. No other change needed in this file.

**New files (frontend):**
- `frontend/packages/connectors/src/stores/overviewBriefStore.ts` — Zustand slice for margin annotations bridging Overview container and `ModernDashboardApp` (§9.9.1, pattern from `scenarioWorkflowStore`)
- `frontend/packages/connectors/src/hooks/useOverviewBrief.ts` — React Query hook (singleflight comes free via React Query v5.90.21)
- `frontend/packages/ui/src/components/dashboard/views/modern/adaptBackendBrief.ts` — backend → TS adapter
- `frontend/packages/ui/src/components/dashboard/views/modern/adaptBackendBrief.test.ts`
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` — artifact registry with stable IDs (§9.8.1)
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.test.ts`
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/types.ts` — `OverviewArtifactEditorial` shared interface
- `frontend/packages/ui/src/components/design/marginAnchors.ts` — anchor ID constants for chat margin (§9.9.1)

**Modified files (frontend)** (file:line locations verified):
- `overviewBrief.tsx` — extend `OverviewBrief` interface to match wire schema (add `artifactDirectives`, `marginAnnotations`, `editorialMetadata.changedSlots`); update `buildOverviewBrief()` to emit new structured shape; mark as bridge impl
- `overviewBrief.test.tsx` — update for new shape
- `overviewArtifactBrief.ts` / `overviewCompositionBrief.ts` — Phase 1a: extend brief types with optional `editorial?: OverviewArtifactEditorial` field (additive). Phase 1b: composition brief refactored to emit two separate flat artifact briefs (asset_allocation + product_type) instead of nested sub-artifacts
- `frontend/packages/ui/src/components/design/MetricStrip.tsx:3-8` — extend `MetricStripItem` interface with optional `id?: string`, `change?: string`, `whyShowing?: string` (renderer untouched in Phase 1; Phase 2 wires `whyShowing` into a tooltip)
- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx:1440-1600` — Phase 1b: call `useOverviewBrief()` at the container level; on success use adapted backend brief, on failure/loading fall back to existing `buildOverviewBrief()`; add `renderLeadInsight()` helper; refactor artifact JSX to loop over registry while preserving chrome (`NamedSectionBreak`, `InsightSection`, `ExitRamps`, tier gates); preserve hidden coupling at line 1454 (`showExitRamps={!overviewGeneratedArtifact}`); write margin annotations to `useOverviewBriefStore` on brief arrival
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx:685` — read `marginAnnotationsByPortfolioId[currentPortfolio?.id]` from `useOverviewBriefStore`, pass into `<ChatMargin annotations={...} />` (§9.9.2)
- `frontend/packages/ui/src/components/design/ChatMargin.tsx:24-37` — add optional `annotations?: MarginAnnotationUI[]` prop to `ChatMarginProps`; render annotations above `VIEW_CONTEXT` content when non-empty; fall back to `VIEW_CONTEXT` when empty (§9.9.1)
- `ChatMargin.test.tsx` (or create if missing) — regression test verifying empty annotations match current behavior
- `ModernDashboardApp.test.tsx` — verify the `annotations` prop is correctly threaded from store to `ChatMargin`

## 12. Testing Strategy

**Unit tests:**
- Each generator (deterministic, no IO): `tests/core/overview_editorial/generators/test_*.py`
- `EditorialPolicyLayer.rank` with fixed inputs → assert deterministic scoring
- `brief_cache` TTL + invalidation (including `set_editorial_memory` triggering invalidation)
- `editorial_state_store` — `load_editorial_state` (row present, row absent → seed fallback, DB unavailable → seed fallback), `set_editorial_memory` (create, update, > 10KB warning), `set_previous_brief` (upsert)
- `adaptBackendBrief` happy path + malformed input (returns null)

**Integration tests:**
- `actions/overview_brief.get_brief` with mocked `PositionService` + mocked result_cache — full pipeline end-to-end
- Route `GET /api/overview/brief` with test client — auth, 200, 503 on total failure
- MCP `update_editorial_memory` tool — call with valid memory, verify DB write + cache invalidation, verify next brief reflects new memory
- Gateway enricher — verify per-user DB memory reads take precedence over seed file fallback
- `auto_seed_from_portfolio` unit tests:
  - Happy path: portfolio composition → LLM called → memory written → cache invalidated
  - Skip when row already exists (idempotency)
  - Skip when portfolio empty / < 3 positions / < $1000 value
  - Skip when composition summary helper fails
  - LLM returns malformed JSON → Pydantic validation fails → skip, no DB write
  - LLM timeout → skip, no DB write
  - Race: row created between check and write → upsert wins, no crash
- Post-sync callback integration test: fresh user, sync completes → auto-seed triggers → row exists after test
- CSV import completion integration test: fresh user, import completes → auto-seed triggers → row exists after test

**Regression tests:**
- `buildOverviewBrief()` TS fallback still works with existing inputs
- `PortfolioOverviewContainer` renders deterministic fallback when `useOverviewBrief` is in error state
- **Artifact registry prep regression** (§9.8.1): container refactored to loop over registry produces identical DOM output for a fixed portfolio fixture when `artifactDirectives` is empty
- **ChatMargin prep regression** (§9.9.1): `ChatMargin` renders identical output for `annotations={[]}` or `annotations={undefined}` as for the current `VIEW_CONTEXT`-only path

**Editorial sub-phase integration tests:**
- Directive applied: backend brief with `artifact_directives` containing `{artifact_id: "overview.concentration", annotation: "Concentration up sharply", highlight_ids: ["DSU"]}` → container renders the concentration artifact with annotation visible and DSU row highlighted
- Directive unknown ID: brief with `{artifact_id: "overview.bogus"}` → frontend ignores, logs WARN, other directives still apply
- Directive visibility: brief with `{artifact_id: "overview.tax_opportunity", visible: false}` → frontend skips that artifact
- Margin annotation applied: brief with `marginAnnotations: [{anchor_id: "lead_insight", type: "ask_about", content: "...", prompt: "..."}]` → ChatMargin renders the annotation
- Margin annotation empty: brief with `marginAnnotations: []` → ChatMargin falls back to `VIEW_CONTEXT`
- Diff flag: brief with `editorialMetadata.changedSlots: ["metric.return", "lead_insight"]` → those slots render "changed" marker
- Diff first-ever generation: `previous_brief = None` → `changedSlots` is empty, no markers rendered

**What we explicitly don't test in Phase 1:**
- LLM arbiter output quality (Phase 2 eval framework)
- Cache invalidation race conditions under load
- Cross-portfolio isolation beyond basic key scoping

## 13. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cold-path latency >3s feels slow | Medium | Medium | Brief cache hides most calls; first load per hour is acceptable |
| LLM arbiter hallucinates structured fields | Medium | Low | Strict Pydantic validation → fallback to deterministic brief |
| Invalidation hook forgotten on new write path | Medium | Medium | Phase 2 arch test; Phase 1 relies on review discipline |
| `previous_brief` rotation race between concurrent cold-path requests | Low | Low | Synchronous DB upsert (§9.3); concurrent requests both rotate, second one's write wins. Both briefs are semantically valid; whichever wins the cache write determines user-visible state. Singleflight is a Phase 2 enhancement |
| Founder's manual seed gets out of sync with `editorial_memory_seed.json` | Medium | Low | Seed file is the canonical source; document that founder DB row should be re-synced if seed is updated |
| Schema drift between Pydantic and TS | Low | High | Phase 2 schema codegen; Phase 1 manual with adapter validation as the safety net |
| Policy layer scoring weights need tuning | High | Low | Telemetry logs capture every score; tune in Phase 2 after observing 1-2 weeks of briefs |
| Events absence feels like a gap to the founder | Low | Low | Events is calendar data, not editorial insight; founder uses the calendar view elsewhere |
| Auto-seeder produces a bad initial guess that alienates a new user | Medium | Low | Memory is a starting point; any conversation refines it immediately; seed prompt is explicitly constrained to conservative inferences |
| Auto-seed LLM latency delays first-connection flow | Low | Low | Runs as background task after sync, not inline; user's first brief may use seed file if they load Overview in the 2-3s window before seeding finishes (ship criterion §14 is honest about this) |
| Phase 1b artifact JSX refactor introduces a behavior regression | Medium | Medium | Phase 1a is pure additive types + registry stubs (zero JSX change). Phase 1b has a DOM-level regression test gate. Composition flattening is the highest-risk piece — caught by the test |
| `ChatMargin` annotation prop drift from static `VIEW_CONTEXT` semantics | Low | Low | `VIEW_CONTEXT` stays as fallback; regression test verifies empty annotations match current behavior; store-based threading via `overviewBriefStore` is explicit and isolated |
| Diff markers feel noisy (too many slots flagged changed every load) | Medium | Low | Phase 1 marker is subtle; if noise is bad, Phase 2 adds a "significant change" threshold to the diff function |
| Concurrent cold-path requests duplicate work (no singleflight on brief generation) | Medium | Low | React Query's native query-key dedup handles client-side; backend can race on rotation but `previous_brief` writes are upserts so the worst case is a benign double-rotate. Phase 2 adds in-process singleflight if telemetry shows duplicate generations are common |
| Per-process editorial_memory cache stale across multiple gateway processes | Low | Low | Phase 1 is single-process (founder + small beta). Phase 2 switches to Redis-backed cache or Postgres LISTEN/NOTIFY if multi-process becomes a requirement |
| `clear_result_snapshot_caches()` is module-level, evicting cache entries for unrelated users on a single user's invalidation | Low | Low | Acceptable for Phase 1 — result cache entries are small and rebuild quickly. Phase 2 adds user-scoped cache keys if telemetry shows hot rebuilds |

## 14. Phase Boundaries

### Phase 1 (this spec)
- 3 generators: Concentration, Risk, Performance
- Deterministic pipeline + async LLM enhancement
- `GET /api/overview/brief`
- `user_editorial_state` table with read + write
- `update_editorial_memory` MCP tool (analyst-managed memory)
- Auto-seed editorial_memory from portfolio composition on first connection
- Gateway enricher extended to read per-user memory from DB
- Analyst skill updated with memory maintenance instructions
- Brief cache + invalidation hooks (3 verified sites: `workers/tasks/positions.py:48`, `routes/onboarding.py:810`, `set_editorial_memory`)
- Frontend backend-driven brief with TS fallback
- Structured logging
- **Artifact directive plumbing** — prep refactor (registry, stable IDs, shared editorial interface) + editorial sub-phase (directives in brief payload, container applies them) (§9.8)
- **Chat margin annotations** — prep refactor (`ChatMargin` accepts annotations prop, falls back to `VIEW_CONTEXT`) + editorial sub-phase (brief emits annotations, container threads them) (§9.9)
- **Diff view** — slot-level "changed since yesterday" markers driven by `previous_brief` comparison (§9.10)
- **Ships when** (verifiable acceptance gates — most map to telemetry fields in §10.1; one is a manual functional check, called out explicitly):

  **Telemetry-audited gates** (each references a specific field defined in §10.1):
  - **Founder briefing variety** (`overview_brief_generated.lead_insight_category`): founder's distribution over 5 consecutive days has at least 3 distinct values (proves editorial selection is varied, not collapsed to a single mode)
  - **Auto-seed first-load honest behavior** (`editorial_memory_updated.auto_seed_trigger` + `auto_seed_llm_duration_ms`): new users connecting their first portfolio emit an `editorial_memory_updated` event with `source="auto_seed"` and `auto_seed_trigger="sync_completion"` (or `"csv_import"`). The 2-3s seeding window is audited via the existing `auto_seed_llm_duration_ms` field on that event — if the field is consistently under ~5 seconds across the founder + beta cohort, the seeding window is acceptable. No correlation against an external sync-completion event is needed; the auto-seed event itself carries the trigger source AND the duration, making this gate auditable from a single event. First brief load AFTER auto-seed completes uses the auto-seeded memory. Briefs loaded during the 2-3s seeding window may use the seed file fallback — documented as acceptable and NOT a ship blocker. (Skip events `editorial_memory_auto_seed_skipped` are tolerated for known reasons: `portfolio_too_small`, `row_already_exists`.)
  - **Telemetry health** (`overview_brief_generated`): event emitted on every generation with `cache_state`, `data_status`, `lead_insight_category`, `duration_ms`, `directive_count`, `annotation_count`, `changed_slots_count`. No error events for at least 100 consecutive generations on the founder portfolio
  - **LLM arbiter health** (`overview_brief_enhanced.parse_success`): rate ≥ 90% over a 7-day rolling window
  - **Editorial memory loop** (`editorial_memory_updated` event with `source="chat_tool"`): founder has at least one such event in telemetry, AND the next `overview_brief_generated` after that event reflects the change (verified by comparing `selection_reasons` before/after)
  - **Directives + annotations active** (`overview_brief_generated.directive_count` and `.annotation_count`): both fields average ≥ 1 across the 7-day window. Frontend regression test passes (DOM identical when directives/annotations are empty)
  - **Diff markers active** (`overview_brief_generated.changed_slots_count`): non-zero on ≥ 30% of briefs over the 7-day window (proves the diff function is working, not just always returning empty)

  **Manual functional gates** (NOT auditable from §10.1 telemetry — verified by hand before ship):
  - **Fallback path**: kill the new `/api/overview/brief` endpoint (e.g., return 503 from a debug toggle); verify the Overview still renders via the deterministic `buildOverviewBrief()` TS path with no console errors and no broken UI states. This is a manual check, not a telemetry assertion.

The telemetry-audited gates are objectively measurable from structured logs alone. The manual gate exists because the fallback path is, by design, the absence of pipeline activity — there's nothing meaningful to log when the pipeline never runs. "Feels editorial" is operationalized as "lead insight category distribution is non-degenerate" — the founder doesn't need to make a subjective call on every brief.

### Phase 2 (next)

Informed by post-Phase 1 audit (`EDITORIAL_PIPELINE_AUDIT.md`, 2026-04-13). Items grouped by priority.

**P1 — Personalization depth (net-new from audit):**
- **Loss screening generator** — positions with large unrealized losses as persistent attention cards (e.g., PCTY -39%). Screens for biggest dollar losers, largest drawdowns, positions needing exit decisions. Emits `attention_item` candidates with exit ramps to tax-loss harvest and exit signal tools.
- **Deep editorial memory usage** — `investor_profile.concerns` drives always-on metric rules (e.g., `concentration_risk` in concerns → lead weight metric is permanent, not competitive). `current_focus.watching` surfaces specific tickers as attention cards or margin annotation boosts. `briefing_philosophy` feeds the LLM editorial pass for tone/posture.
- **Benchmark comparison on metrics** — `MetricStripItem` schema enrichment (structured `benchmark_value` field or richer `context_label` population from performance snapshot). Side-by-side values (e.g., "Sharpe -1.10 vs 0.77 bmk"), not just "vs SPY" labels.

**P1 — Generator expansion (originally planned):**
- Events generator (pull-forward — deferred from Phase 1 per §3.1; re-entry: add `build_events_snapshot()` cached builder in `result_cache.py`)
- Income generator
- Trading, Factor, Tax Harvest generators

**P2 — Infrastructure + UI:**
- Attention items UI rendering (backend schema exists; frontend needs design system component)
- `complete_structured()` on `CompletionProvider` (structured output protocol method)
- Architecture test for invalidation hooks (automated check for missing `invalidate_brief_cache` calls)
- Eval framework (predefined portfolio scenarios)
- Observability dashboards
- LLM arbiter model benchmarking (currently uses `gpt-4.1`; no Anthropic/model comparison done)
- Dedicated onboarding wizard (if free-form analyst conversation proves insufficient)
- Revision/diff markers (richer diff beyond Phase 1's `changed_slots`)

**P3 — Nice to have:**
- Alert vs default state detection — rule-based state detector as policy-layer input (boost risk candidates globally in alert mode). Lower priority in persistence framing — overview's persistent signals speak for themselves.
- New information awareness — beyond `changed_slots` diff. Becomes relevant when events generator exists.

### Phase 3+ (deferred)
- Engagement tracking (click logging, implicit preference signals)
- Per-user generator activation (selective generator runs based on editorial_memory)
- Brief quality regression detection
- ~~Editorial_memory seeding from portfolio composition~~ — SHIPPED in Phase 1 (B6 auto-seeder)

## 15. Open Questions

Questions deferred to Phase 2 (not blocking Phase 1):

- **Attention items UI spec**: design system rendering for category + urgency + action. Current seam has no AttentionItems component.
- **Relationship to existing AIRecommendationsSection**: design doc open question #3. For Phase 1, AIRecommendationsSection stays as-is (unchanged). Phase 2 decides whether to absorb into the pipeline or keep separate.
- **LLM arbiter model choice**: design doc says "Haiku for speed, Sonnet for quality (config)." Phase 1 defaults to Haiku (cheapest, fastest); config-driven. Model benchmarking is Phase 2.
- **Memory schema evolution**: the AI writes whatever shape makes sense; if patterns emerge that deserve structured fields or dedicated tools (e.g., separate `record_recent_action`), promote them in Phase 2.
- **In-process singleflight** for brief generation: React Query handles client-side dedup; backend can race on `previous_brief` rotation. Phase 2 adds in-process singleflight if telemetry shows duplicate generations are common.
- **Multi-process editorial_memory cache**: Phase 1 uses a per-process cache in `gateway_proxy.py`. Phase 2 switches to Redis-backed or LISTEN/NOTIFY if multi-process gateway becomes a requirement.
- **DOM-level margin anchor positioning**: Phase 1 renders annotations as a list at the top of the margin. Phase 2 positions them next to their anchor DOM element via scroll-spy or similar.

**All questions previously flagged as "answer before Phase 1 plan is drafted" are now resolved:**
- Hook file locations → §3.3 + §8.2 reference verified `workers/tasks/positions.py:48` and `routes/onboarding.py:810`. Transaction ingest dropped (phantom).
- Background runtime → §3.7 specifies FastAPI `BackgroundTasks` for the LLM arbiter and CSV-import auto-seeder; direct synchronous calls inside the Celery worker for sync-completion auto-seeder; direct calls for invalidation.

## 16. Implementation Plan Hook

This arch spec is the input to `OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md` (to be drafted after this spec passes Codex review). The plan should:

- Break the backend into 4–6 sub-phases (migration → models → orchestrator+context → generators → policy+cache → LLM+route), each independently Codex-reviewable and committable
- Resolve the two "need an answer before plan" questions in §15
- Specify test counts per sub-phase
- Identify the exact line-level touchpoints for invalidation hooks
- Specify the frontend sub-phases (hook → adapter → container wiring → fallback verification)
- Include a QA checklist (founder opens Overview, brief looks editorial, deterministic fallback works, cache invalidates on CSV import, etc.)

## 17. Summary of Prescriptive Decisions

| # | Decision | Reasoning (1 line) |
|---|---|---|
| 3.1 | Drop Events from Phase 1 | No cached builder exists; scope creep to add one; editorial cost is minimal |
| 3.2 | Wrap `PositionService` directly for positions | Existing service owns freshness; second cache would create two sources of truth |
| 3.3 | Scoped invalidation: 3 verified hook sites + L2 result cache clear | Honors Eng decision #8; transaction ingest hook dropped (phantom); brief invalidation also clears L2 result cache for fresh data |
| 3.4 | Backend is schema source of truth; TS seam extended to match | Two sources of truth is the worst outcome |
| 3.5 | editorial_memory read + write in Phase 1; concurrency via REPLACE upsert (chat) + DO NOTHING upsert (auto-seed) | One-function tool, not a design problem; race is safe by design at the SQL level — no merge logic, no version columns |
| 3.6 | String JSON + Pydantic validation for LLM output | Protocol extension not Phase 1 material; fallback is clean |
| 3.7 | Background runtime: FastAPI `BackgroundTasks` for LLM arbiter + CSV-import auto-seeder; direct calls inside Celery worker for sync-completion auto-seeder | Codebase already uses both runtimes; no new infrastructure needed |
| 9.3 | `previous_brief` is DB-sourced; new brief becomes the next anchor at end of cold path (sync, ~10ms). Stored per `(user_id, portfolio_id)` in JSONB map | Cache-sourced rotation broke on cache misses; user-scoped storage broke for multi-portfolio users |
| 9.7 | Auto-seed editorial_memory from portfolio composition on first connection | New users get personalized briefs on day one instead of founder-flavored fallback; CEO cherry-pick #4 |
| 9.8 | Artifact directives split into Phase 1a (types + IDs, zero change) and Phase 1b (JSX refactor + composition flatten + editorial threading) | Earlier "zero behavior change" claim was false; honest split is independently shippable in Phase 1a |
| 9.9 | Chat margin annotations threaded via new `overviewBriefStore` (Zustand), not container-to-margin | `ChatMargin` is owned by `ModernDashboardApp`, not the container; store-based bridge follows existing `scenarioWorkflowStore` precedent |
| 9.10 | Diff view driven by `previous_brief` comparison; `changed_slots` field on `EditorialMetadata` | Infra already exists; slot-level markers are the minimum viable diff; CEO cherry-pick #1 |
| 5 | 3 generators (Concentration, Risk, Performance) | Covers the lead-story categories without Events scope creep |
| 9.1 | `user_editorial_state` with JSONB | Schema is evolving; JSONB stays queryable |

---

**Next step**: Codex review of this spec. If PASS, draft `OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md` with implementation sub-phases.
