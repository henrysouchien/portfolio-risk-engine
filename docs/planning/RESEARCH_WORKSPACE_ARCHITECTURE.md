# Research Workspace — Architecture

**Status:** Frame document for Phase 1-5 implementation
**Last updated:** 2026-04-10
**Synthesizes:** `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` (7 locked decisions)
**References:**
- `EQUITY_RESEARCH_WORKSPACE_SPEC.md` — product spec + design consultation
- `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` — locked architectural decisions
- `RESEARCH_WORKSPACE_PHASE1_PLAN.md` v4 (commit `7b4c8a76`) — superseded by v5 (pending)
- `DESIGN.md` — research workspace visual design section

This doc is the high-level frame. Phase plans (Phase 1-4) sit inside this frame as implementation detail. Decisions doc sits behind this as rationale. Product spec sits behind as motivation. Read this first; drill into others as needed.

---

## 1. Purpose + Pipeline

The research workspace is an **IDE for equity research** — a collaborative surface where a human analyst and an AI agent work together on active investment research. It's the front half of an investment pipeline:

```
explore → diligence → report → model-build handoff
```

- **Explore** (Phase 1) — free-form two-pane conversation (reader + agent panel), IDE-style tabs, threads emerge from discovery
- **Diligence** (Phase 3) — structured checklist collects the fields the report needs (9 universal core sections + dynamic Qualitative Factors extension)
- **Report** (Phase 4) — `research_handoff` — a structured JSON artifact, not a document. Multi-consumer contract.
- **Model-build handoff** (Phase 4) — artifact flows into `model_build()` + `annotate_model_with_research()` which populates a SIA-template Excel financial model

**The workspace is the factory; the model builder is the downstream consumer.** The report is the stable contract between them.

**Core principle:** working backwards from the model builder defines what diligence must produce → what exploration must capture → what storage must hold → what the UI must expose.

---

## 2. System Topology

```
┌──────────────────────────────────────────────────────────────────┐
│                    Risk_module (Web App)                          │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │            Frontend (React + Zustand)                       │  │
│  │  ┌──────────────┐  ┌────────────────────┐  ┌────────────┐  │  │
│  │  │researchStore │  │ ResearchStream     │  │ Hash       │  │  │
│  │  │  (Zustand)   │  │ Manager (React ctx)│  │ Routing    │  │  │
│  │  └──────────────┘  └────────────────────┘  └────────────┘  │  │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │  Component Tree (11 new components in Phase 1)        │  │  │
│  │  │  ResearchWorkspace · ResearchTabBar · ExploreTab      │  │  │
│  │  │  ThreadTab · AgentPanel · ConversationFeed · ...     │  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              ↕                                     │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │            Backend (FastAPI + Postgres)                      │  │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │  routes/research_content.py                           │  │  │
│  │  │  (thin proxy — auth + tier gate + forward)           │  │  │
│  │  │                                                        │  │  │
│  │  │  • create_tier_dependency(minimum_tier="paid")        │  │  │
│  │  │  • Extract user_id from authenticated session         │  │  │
│  │  │  • Forward to gateway with user_id injected          │  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  │  Postgres: users, portfolios, baskets, etc. (UNCHANGED)     │  │
│  │  NO research tables in risk_module Postgres.                │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              ↕
                    ┌──────────────────────┐
                    │   Gateway            │
                    │   (app-platform)     │
                    │                      │
                    │   • Multi-user       │
                    │     routing          │
                    │   • SSE streaming    │
                    │   • Strict-mode      │
                    │     user_id validate │
                    └──────────────────────┘
                              ↕
┌──────────────────────────────────────────────────────────────────┐
│                      AI-Excel-Addin                                │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │       NEW: Research Layer (Phase 1+)                       │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │  api/research/routes.py                           │    │    │
│  │  │  REST endpoints: /api/research/{files,threads,    │    │    │
│  │  │  messages,annotations,documents,extractions,      │    │    │
│  │  │  handoffs,handoffs/{id}/build-model}              │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │  api/research/repository.py                       │    │    │
│  │  │  ResearchRepository — per-user SQLite routing,    │    │    │
│  │  │  file-scoped queries (research_file_id),          │    │    │
│  │  │  connection-per-request, lazy schema migrations   │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │  api/research/policy.py                           │    │    │
│  │  │  RESEARCH-MODE POLICY LAYER (prompt routing only) │    │    │
│  │  │  • is_research_workspace(context) predicate       │    │    │
│  │  │  • build_research_prompt_stack(context) —         │    │    │
│  │  │    research-specific system prompt + file         │    │    │
│  │  │    context block                                  │    │    │
│  │  │  NO tool denylist. NO handler strip. Agent has    │    │    │
│  │  │  full memory/run_agent access on research turns   │    │    │
│  │  │  because all ai-excel-addin state is per-user     │    │    │
│  │  │  by physical isolation (Invariant 1).             │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │  api/research/context.py                          │    │    │
│  │  │  build_research_context(user_id,                  │    │    │
│  │  │    research_file_id, thread_id, tab_context)      │    │    │
│  │  │  → prompt block (called from policy layer)        │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │  api/research/handoff.py                          │    │    │
│  │  │  Artifact assembly from research state →          │    │    │
│  │  │  research_handoffs row (file-scoped)              │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │  api/research/document_service.py         [Phase 2]│    │    │
│  │  │  Stateless filing + extraction read service       │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │  api/research/build_model_orchestrator.py [Phase 4]│    │    │
│  │  │  Two-step orchestration: model_build() →          │    │    │
│  │  │  annotate_model_with_research(). Server-side      │    │    │
│  │  │  only — NOT called directly by frontend.          │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                              ↕                                     │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │       Agent Runtime (existing, extended)                   │    │
│  │  • build_system_prompt_blocks — delegates to              │    │
│  │    research.policy when purpose='research_workspace'      │    │
│  │  • Turn hooks — server-side message persistence           │    │
│  │  • MCP tool calls to model engine, FMP, langextract, etc. │    │
│  └──────────────────────────────────────────────────────────┘    │
│                              ↕                                     │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  MCP Tools (existing + new)                                │    │
│  │  • model_build, update_model (existing, unchanged)        │    │
│  │  • annotate_model_with_research (NEW, Phase 4)            │    │
│  │  • langextract.extract_filing_file (existing,              │    │
│  │    schemas extended in Phase 2)                            │    │
│  │  • edgar_mcp, fmp_mcp, etc.                                │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  EXTENDED in Phase 1 Step 0: Per-user memory store         │    │
│  │  • api/memory/store.py — AnalystMemoryStore                │    │
│  │    accessed via MemoryStoreFactory (user_id → store)       │    │
│  │  • data/users/{user_id}/analyst_memory.db                  │    │
│  │    (migrated from api/memory/analyst_memory.db)            │    │
│  │  • data/users/{user_id}/workspace/tickers/*.md             │    │
│  │    (markdown sync, per-user path)                          │    │
│  │                                                            │    │
│  │  Agent has FULL access to memory + run_agent on research   │    │
│  │  turns. Per-user physical isolation eliminates cross-user  │    │
│  │  contamination concern. Research workspace tables live     │    │
│  │  alongside in the same per-user directory.                 │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Storage Topology

**Per-user physical isolation** — each user's research state lives in their own SQLite file + filesystem directory. No shared state with `user_key` columns. No cross-user queries possible by construction.

```
Risk_module Postgres                       AI-excel-addin filesystem
────────────────────                       ─────────────────────────
users                                      data/                          [per-user everything]
portfolios                                 ├─ filings/                    [shared, immutable]
baskets                                    │  └─ VALE_10K_2024_a3f8b2c1.md
other app state                            │  (content-hash-suffixed; read-only reference;
                                           │   safe to share across users because filings
NO research tables                         │   are public SEC documents and the hash
                                           │   guarantees immutability)
                                           │
                                           └─ users/{user_id}/             [per-user, all state]
                                              ├─ analyst_memory.db          [MIGRATED Phase 1 Step 0]
                                              │  (existing EAV memory — previously at
                                              │   api/memory/analyst_memory.db, now per-user)
                                              ├─ workspace/
                                              │  └─ tickers/*.md            [MIGRATED Phase 1 Step 0]
                                              │  (existing markdown sync — per-user path)
                                              ├─ research.db                 [NEW Phase 1]
                                              │  ├─ research_files
                                              │  │   (id, ticker, label, company_name, stage,
                                              │  │    direction, strategy, conviction, timestamps)
                                              │  │   UNIQUE(ticker, label)
                                              │  ├─ research_threads
                                              │  │   (id, research_file_id FK, name,
                                              │  │    finding_summary, is_explore, is_panel,
                                              │  │    timestamps)
                                              │  ├─ research_messages
                                              │  │   (id, thread_id FK, author, content,
                                              │  │    content_type, tab_context, metadata,
                                              │  │    created_at)
                                              │  ├─ annotations               [Phase 2]
                                              │  │   (id, research_file_id FK, source_type,
                                              │  │    source_id, section_header, char_start,
                                              │  │    char_end, selected_text, note, author,
                                              │  │    diligence_ref, created_at)
                                              │  └─ research_handoffs         [Phase 4]
                                              │      (id, research_file_id FK, ticker SNAPSHOT,
                                              │       version, status, artifact JSON,
                                              │       timestamps)
                                              └─ exports/                     [Phase 4+]
                                                 ├─ research_handoff_{research_file_id}_v{N}.json
                                                 └─ model_{research_file_id}_v{N}.xlsx
                                                 (keyed by research_file_id — NOT ticker —
                                                  to prevent collisions across labeled files
                                                  on the same ticker)
```

**Per-user-everything model:** ALL ai-excel-addin persistent state lives under `data/users/{user_id}/`. This includes both the NEW research workspace (`research.db`) AND the EXISTING analyst memory (`analyst_memory.db`, `workspace/tickers/*.md`) after a one-time migration in Phase 1 Step 0. No shared single-user state remains in ai-excel-addin after Phase 1 ships. Two users have physically isolated directories; cross-user contamination is impossible by construction. This lets the research agent use the full tool surface (memory tools, `run_agent`, sub-agents) without restrictions — everything the agent touches is already user-scoped.

**Critical identity model:** All research content (threads, annotations, handoffs) is keyed by `research_file_id`, NOT `ticker`. The `label` column on `research_files` supports multiple concurrent theses per ticker (long vs short, pre-earnings vs core, etc.); propagating `research_file_id` through the rest of the schema is what makes that real. Ticker is a display attribute of the file, not a lookup key for content.

**Key constraints:**
- `research_files.ticker` is NOT unique by itself — multiple files allowed per ticker via `label` disambiguator; `UNIQUE(ticker, label)` is the file-level constraint
- `label=''` for the default file on a ticker; UI prompts for a label on the 2nd+ file
- `research_threads` has partial unique indexes: one explore thread **per research_file_id**, one panel thread **per research_file_id** — NOT per ticker (so two files on VALE each get their own Explore/Panel)
- `research_messages.thread_id` is a FK into `research_threads` (which is FK to `research_files`) — messages inherit file scope transitively
- `annotations.research_file_id` is a FK — annotations belong to a specific file/thesis, not a ticker. The same filing passage annotated under two different theses on VALE creates two distinct rows.
- `annotations.source_id` for filings must include the content hash (immutable filing reference)
- `research_handoffs.research_file_id` is the lookup key. `research_handoffs.ticker` is a **denormalized snapshot field** for display only, NOT a lookup key.
- `research_handoffs` versioning: `version=1, 2, 3...` per `research_file_id`; old versions stay after regeneration (audit trail)

**Filing cache framing (pragmatic):** The shared `data/filings/` directory holds content-addressed, immutable markdown files. Sharing across users is safe because (a) filings are public SEC documents, (b) the content hash guarantees the file text can't change after ingest, (c) any user-specific state (annotations, citations, workspace context) lives in the per-user `research.db`, not in the filing file. Re-ingesting the same filing with different normalization produces a new hash → new file → both versions coexist. No garbage collection in Phase 2; add if disk usage matters.

---

## 4. Cross-Repo Boundaries

| Responsibility | Owner | Notes |
|---|---|---|
| UI rendering + state management | risk_module frontend | All React + Zustand code |
| Authentication + session management | risk_module backend | Existing auth stack |
| Tier gating (`minimum_tier="paid"`) | risk_module backend | CRUD: enforced at `routes/research_content.py` proxy. Chat: enforced at existing gateway proxy (`routes/gateway_proxy.py`) via `purpose` field check |
| User_id resolution + injection | risk_module backend | CRUD: extracted from session at `routes/research_content.py`, forwarded to ai-excel-addin. Chat: extracted at existing gateway proxy, injected via strict-mode context |
| Non-research app state (portfolios, baskets, users) | risk_module Postgres | Unchanged |
| Multi-user routing + SSE streaming | gateway (app-platform) | Existing |
| Research data storage | ai-excel-addin per-user SQLite | NEW per-user files; NO Postgres tables for research in risk_module |
| Research REST endpoints (CRUD) | ai-excel-addin `api/research/routes.py` | New endpoints called via gateway proxy |
| `ResearchRepository` abstraction | ai-excel-addin `api/research/repository.py` | Hides SQLite routing; future Postgres migration hook |
| Agent prompt assembly for research | ai-excel-addin `api/research/context.py` + runtime | `build_research_context()` reads from ResearchRepository |
| Server-side message persistence | ai-excel-addin runtime hooks | Pre/post turn persistence via ResearchRepository |
| Research handoff artifact assembly | ai-excel-addin `api/research/handoff.py` | Phase 4 |
| Model engine (`model_build`, `update_model`) | ai-excel-addin existing | Unchanged |
| `annotate_model_with_research()` tool | ai-excel-addin | NEW Phase 4 tool |
| Langextract extraction schemas | ai-excel-addin `mcp_servers/langextract_mcp/schemas.py` | 4 existing + 3 new in Phase 2 |
| Filing retrieval + content-hash versioning | ai-excel-addin + edgar-mcp | Ingest renames output with hash suffix (Phase 2) |
| EAV memory + markdown sync | ai-excel-addin existing, MIGRATED to per-user in Phase 1 Step 0 | `MemoryStoreFactory` resolves `user_id → per-user analyst_memory.db`; markdown sync uses per-user paths; 9 screener connectors pass user_id |

**API surface** (new in research layer, all scoped by `research_file_id` except the file list):

Phase 1:
- `GET /api/research/content/files` — list user's research files (user-scoped by per-user DB)
- `POST /api/research/content/files` — upsert `{ticker, label?, company_name?}`, returns file row including `id`
- `PATCH /api/research/content/files/{research_file_id}` — update stage/conviction/direction/strategy/label (user-driven only; agent never calls this)
- `DELETE /api/research/content/files/{research_file_id}`
- `GET /api/research/content/threads?research_file_id=...` — list threads for a file
- `POST /api/research/content/threads` — create thread `{research_file_id, name, is_explore?, is_panel?, seed_message_ids?}` (idempotent when `is_explore=true` or `is_panel=true`; `seed_message_ids` copies messages from explore into the new thread — file-scope validated via join)
- `PATCH /api/research/content/threads/{thread_id}?research_file_id=...` — update `finding_summary` (file-scope ownership check)
- `GET /api/research/content/messages?thread_id=...&research_file_id=...&limit=...` — message history (thread ownership verified via `thread_belongs_to_file` guard)

**Separate auth boundary for chat:** `POST /chat` is the **existing gateway chat endpoint** (routed through `routes/gateway_proxy.py`, NOT through `routes/research_content.py`). For research turns, the frontend sends `purpose='research_workspace'` + `research_file_id` + `thread_id` + `tab_context` in the context payload. The existing gateway proxy already handles auth + `user_id` injection for chat. Tier gating for research chat is enforced at the gateway level via the `purpose` field — if `purpose='research_workspace'` and user is not paid tier, the gateway rejects the turn. The research content proxy (`routes/research_content.py`) handles ONLY the CRUD endpoints above.

Phase 2:
- `GET /api/research/content/documents?filing_id=...` — load filing, return `{section_map, available_sections}`
- `GET /api/research/content/extractions?filing_id=...&section=...&schemas=...` — run langextract on a specific section
- `GET /api/research/content/annotations?research_file_id=...` — list annotations for a file
- `POST /api/research/content/annotations` — create annotation `{research_file_id, filing_id, section_header, char_start, char_end, selected_text, note, diligence_ref?}`

Phase 4:
- `POST /api/research/content/handoffs` — build handoff from current research state `{research_file_id}`, returns `{handoff_id, version, artifact_summary}`
- `GET /api/research/content/handoffs/{handoff_id}` — fetch handoff artifact for review
- `POST /api/research/content/handoffs/{handoff_id}/build-model` — orchestrates `model_build()` + `annotate_model_with_research()`, returns `{model_path, handoff_id, build_status}`

**CRUD routes go through `routes/research_content.py` proxy**, which enforces `minimum_tier="paid"`, extracts `user_id` from the authenticated session, and forwards to ai-excel-addin via the gateway. **Chat route (`POST /chat`) goes through the existing `routes/gateway_proxy.py`** with research context in the payload. **No direct-MCP-from-frontend path** for any of these endpoints.

---

## 5. Key Data Flows

### Flow 1: Load research file list (landing page)

```
User opens #research
  → Frontend: useResearchFiles() hook fires
  → Frontend → GET /api/research/content/files
  → Risk_module proxy: verify paid tier, extract user_id from session
  → Proxy → gateway → ai-excel-addin: GET /api/research/files (proxy strips /content prefix; with user_id header/context injected by gateway)
  → Ai-excel-addin: ResearchRepository.list_files(user_id)
      → opens data/users/{user_id}/research.db
      → SELECT * FROM research_files ORDER BY updated_at DESC
      → closes connection
  → Returns list with metadata (ticker, label, stage, conviction, timestamps)
  → Bubble back to frontend → render file cards
```

### Flow 2: Start research on VALE (bootstrap)

```
User clicks "Start research" or deep-links #research/VALE (or #research/VALE:long-thesis)
  → Frontend: hashSync.hydrateFromHash() → setNavigationContext({ ticker: 'VALE', label?: 'long-thesis' })
  → Frontend: ResearchWorkspaceContainer mounts
  → Frontend: useResearchBootstrap({ticker, label?}) orchestrates:
       A. POST /api/research/content/files {ticker: 'VALE', label: ''}    (upsert)
          → returns { id: 42, ticker, label, ... }  ← research_file_id = 42
       B. POST /api/research/content/threads {research_file_id: 42, is_explore: true}  ┐ parallel
       C. POST /api/research/content/threads {research_file_id: 42, is_panel: true}    ┘
       D. GET /api/research/content/threads?research_file_id=42
       E. For each thread: GET /api/research/content/messages?thread_id=...&research_file_id=42&limit=50
       F. researchStore.hydrate({ file, exploreThreadId, panelThreadId, threads, messagesByThread })
  → UI renders two-pane workspace with Explore tab active
```

**Critical change from v4 plan:** every call after Step A carries `research_file_id`, not `ticker`. Ticker is only used for the initial upsert and is stored in the file row; subsequent content queries are file-scoped.

### Flow 3: Send message in Explore tab

```
User types message → hits enter
  → Frontend: useResearchChat.sendMessage(text)
     1. Optimistic: add user message to researchStore
     2. Create agent placeholder message (follows usePortfolioChat pattern)
     3. Build transcript from last 50 messages (TRANSCRIPT_LIMIT)
     4. ResearchStreamManager.send({ threadId, messages, context })
        where context = { purpose: 'research_workspace', research_file_id, thread_id, tab_context }
                       ────────────────────────────────  ───────────────
                       (NEW identifier, avoids collision  (file is the scope,
                        with existing context.mode='research')  not ticker)
     5. GatewayClaudeService.streamWithContext(messages, context)
     6. Frontend → POST /chat (gateway proxy)

  → Gateway → ai-excel-addin chat runtime
     7. Runtime receives request with purpose='research_workspace', user_id (trusted from proxy),
        research_file_id, thread_id, tab_context
     8. [BEFORE first SSE yield — save must commit to disk before any bytes go to the client]
        ResearchRepository.save_message(user_id, thread_id, author='user', content=last_user_message)
        → If save fails (exception, disk full, schema migration mid-flight, etc.):
          reject turn before stream starts (500 to client; user sees error toast; no bytes yielded)
        → If save succeeds and commits: proceed to stream
        → Ordering invariant: the gateway MUST NOT yield the first SSE byte until the save has
          committed. This is implementable in the existing gateway shape because the runner is
          synchronous up to the point the agent begins streaming.
     9. Research-Mode Policy Layer applies (purpose='research_workspace'):
        - System prompt: research-specific blocks + file context block from ResearchRepository
        - Tool catalog: UNCHANGED — agent has full access to memory_*, run_agent, and all
          other tools (per-user isolation via Invariant 1 eliminates the contamination concern)
        - See Section 6 and Section 8 for policy layer details
     10. build_system_prompt_blocks(context):
        - Base blocks (includes memory guidance — agent has full memory access per Invariant 2)
        - Call build_research_context(user_id, research_file_id, thread_id, tab_context)
          which queries ResearchRepository:
          * get_file(research_file_id) → ticker, label, stage, direction, strategy, conviction
          * list_threads(research_file_id) → all thread names + pinned findings for this file
          * list_messages(thread_id, limit=20) → active thread context
          * If tab_context != thread_id: list_messages(tab_context, limit=10) → reader tab context
          * get_latest_handoff(research_file_id, status='draft') → draft diligence state (Phase 3+)
        - Format into prompt block: "You are working on research file VALE — long-thesis
          (stage: exploring, direction: long, strategy: value). Active thread: Ownership..."
     11. Agent generates response using FULL tool catalog (memory_*, run_agent, all tools —
         per-user isolation eliminates contamination concern; see Invariant 2)
     12. Streams response via SSE
  
  → Frontend:
     13. onChunk handler: appendToLastMessage(threadId, chunk.content)
     14. [ON stream complete, server-side]
         ResearchRepository.save_message(user_id, thread_id, author='agent', content=full_response,
                                         metadata={tool_calls?, artifacts?, diligence_ref?})
         → If save fails: return terminal error chunk to client; agent message is LOST (no retry
           mechanism in Phase 1); user reconciles from server on next bootstrap
     15. onComplete: setStreaming(null)
     16. On stream error: mark last agent message as error in UI, lock input until retry,
         reconcile from server on retry (server is source of truth)
```

**Persistence failure model (Invariant 5, honest version):**
- **User message fails to save (Step 8):** turn rejected before stream; user sees error; no state drift
- **Agent message fails to save (Step 14):** agent reply is LOST server-side; client may have streamed content in memory but it's not persisted; user sees terminal error and can reload to see only the user message
- **Client disconnects mid-stream:** gateway cancels the runner (current behavior); user message is already persisted (Step 8); agent message is NOT persisted (Step 14 never fires); client reconciles on reload and sees only the user message
- **Phase 1 accepts partial loss on disconnect.** Run-to-completion or incremental persistence are upgrades for later phases if UX hurts.

### Flow 4: Open document tab on filing (Phase 2)

```
User clicks "Open 10-K" in thread or agent message (in a workspace scoped to research_file_id=42)
  → Frontend: researchStore.openTab({ type: 'document', source_id: 'VALE_10K_2024_a3f8b2c1' })
  → Frontend → GET /api/research/content/documents?filing_id=VALE_10K_2024_a3f8b2c1
  → Ai-excel-addin: DocumentService.get_document(filing_id)
     → look up filing file path at data/filings/VALE_10K_2024_a3f8b2c1.md  (shared immutable cache)
     → read markdown file
     → parse_filing_sections() → SectionMap
     → return { section_map, available_sections }
  → Frontend: render document tab with section selector, user picks "Item 7 MD&A"
  → Frontend → GET /api/research/content/extractions?filing_id=...&section=Item 7&schemas=risk_factors,management_commentary
  → Ai-excel-addin: langextract.extract_filing_file(path, schema, sections_filter=[section])
     → returns grounded extractions with char_start/char_end
  → Frontend: render section text + langextract overlay as colored highlights
  → User selects text → capture (char_start, char_end) relative to full file
  → User clicks "Add annotation":
     → POST /api/research/content/annotations
       {research_file_id: 42, filing_id, section_header, char_start, char_end,
        selected_text, note, diligence_ref?}
     → ResearchRepository.save_annotation(user_id, research_file_id=42, ...)
     → Note: annotations are keyed by research_file_id, so the SAME filing passage can
       be annotated independently under two different theses on VALE (file 42 vs file 57)
  → User clicks "Ask about this":
     → openTab("panel") + prefill panel input with source citation + question
     → sendMessage flow (Flow 3) with research_file_id=42 and annotation reference in metadata
```

**Note:** Filings live in `data/filings/` (shared, immutable content-addressed). Annotations live in the user's per-user `research.db` and are scoped to `research_file_id`. These are decoupled concerns — filings are reference material, annotations are per-user research state.

### Flow 5: Finalize report → model build (Phase 4)

```
User clicks "Finalize Report" in workspace (scoped to research_file_id=42)
  → Frontend → POST /api/research/content/handoffs {research_file_id: 42}
  → Ai-excel-addin: HandoffService.build_handoff(user_id, research_file_id=42)
     → reads file metadata, threads, messages, annotations, diligence state via ResearchRepository
     → assembles research_handoff JSON artifact (schema in Decision 2)
     → INSERT INTO research_handoffs (research_file_id=42, ticker='VALE' [snapshot],
       status='finalized', version=N, artifact=...)
     → return { handoff_id, version, ticker, artifact_summary }
  → Frontend: navigate to handoff review view, display artifact + "Build Model" button

User clicks "Build Model"
  → Frontend → POST /api/research/content/handoffs/{handoff_id}/build-model
    (REST endpoint — NOT a direct MCP call from the frontend)
  → Ai-excel-addin BuildModelOrchestrator:
     Step 1: model_build(
       ticker="VALE", company_name="Vale S.A.", fiscal_year_end="12-31",
       most_recent_fy=2025, output_path="data/users/{user_id}/exports/model_{research_file_id}_v{N}.xlsx",
       source="fmp", financials=handoff.financials.data, sector=handoff.company.sector
     )
     → Model engine builds populated SIA-template workbook
     → Returns { output_path, build_status }

     Step 2: annotate_model_with_research(model_path=output_path, handoff_id=handoff.id)
     → Load research_handoffs row
     → openpyxl: open workbook
     → Write handoff.assumptions[] to SIA driver cells (via driver-name → cell-address mapping)
     → Write handoff.{thesis, catalysts, risks, peers, valuation, qualitative_factors} to hidden metadata sheet
     → Save with fullCalcOnLoad=True + forceFullCalc=True
     → Clear model-engine cache
     → Return { model_path, annotated_at }

     Step 3: Return { model_path, handoff_id, build_status } to frontend
  → Frontend: render "Model ready" state with download link

User opens workbook in Excel
  → Excel recalculates on load → fully-populated model with research-driven assumptions
```

**Note on MCP tool invocation path:** the frontend does NOT call MCP tools directly. Model build and annotation are orchestrated server-side via the REST endpoint. MCP is the transport between ai-excel-addin's internal orchestrator and the model engine — not a frontend-accessible interface. The `BuildModelOrchestrator` is a new Phase 4 module in `api/research/` that owns the two-step sequence.

**Server-side readback caveat (Invariant 10):** Neither Step 2 nor any Phase 4 code is expected to read and trust numerical values from the annotated workbook server-side. openpyxl does not recompute formulas on save, and the model-engine reader relies on cached values. The workbook is valid only once Excel opens it and recalculates. If Phase 4+ surfaces a need for trusted server-side numerics (e.g., automated sanity-check against thesis valuation range), that's a separate tool — likely headless Excel invocation — not a smoke test.

---

## 6. Agent Context Flow

When the agent runs a turn with `purpose='research_workspace'`, it sees research state through the per-user `research.db` via `ResearchRepository`, AND continues to have access to the per-user analyst memory (`analyst_memory.db`) via standard `memory_*` tools. Both stores are physically isolated under `data/users/{user_id}/` — the agent has full read/write access to both, the same way it accesses any other per-user state. The **Research-Mode Policy Layer** provides the research-specific system prompt + file context block; it does NOT restrict tool access.

```
Agent runtime receives chat request:
  context = {
    purpose: "research_workspace",   # NEW identifier, distinct from existing context.mode="research"
    user_id: 42,                     # trusted value injected by risk_module proxy
    research_file_id: 17,            # THE identity for everything below
    thread_id: 103,                  # active thread user is sending to
    tab_context: 99,                 # reader tab's active thread (may differ if sending from panel)
    messages: [...]                  # transcript
  }

# STEP 1: Research-Mode Policy Layer applies BEFORE prompt assembly
# NOTE: No tool catalog modification. The agent has full access to memory_*,
# run_agent, and all other tools — per-user physical isolation (Invariant 1)
# eliminates the cross-user contamination concern that would otherwise require
# a denylist. Research state just lives alongside existing memory state in the
# same per-user directory.

# STEP 2: Build system prompt blocks
blocks = research_policy.build_research_prompt_stack(context)
  # This is a DIFFERENT prompt stack than the generic one.
  # Includes research-workspace-specific instructions + file context block.
  # Includes general memory guidance (agent has full memory access per Invariant 2;
  # prompt guidance tells the agent which store to use for which data — research.db
  # for workspace state, memory tools for general cross-session ticker observations).

repo = ResearchRepositoryFactory.get(user_id)   # returns per-user ResearchRepository (no persistent connection; connection-per-operation per Invariant 12)

file = repo.get_file(research_file_id)
  # → { id, ticker, label, company_name, stage, direction, strategy, conviction }

threads = repo.list_threads_for_file(research_file_id)
  # → [{ id, name, finding_summary, is_explore, is_panel }, ...]
  # file-scoped, not ticker-scoped

active_messages = repo.list_messages(thread_id, limit=20)

if tab_context != thread_id:
  reader_messages = repo.list_messages(tab_context, limit=10)
else:
  reader_messages = []

# Phase 3+: include draft handoff state so agent knows what diligence is populated
draft_handoff = repo.get_latest_handoff(research_file_id, status='draft')

blocks.append(format_research_block(
  file, threads, active_messages, reader_messages, draft_handoff
))

# No repo.close() needed — ResearchRepository uses connection-per-operation
# (open → use → close inside each method call). See Invariant 12.

# The prompt block looks like:
#   "You are working on research file VALE — long-thesis (Vale S.A.).
#    Stage: exploring. Direction: long. Strategy: value. Conviction: 3.
#    Active thread: Ownership (5 messages).
#    Other threads for this file: Valuation (empty), Catalysts (3 messages).
#    Reader tab context: Catalysts thread, last 10 messages: ...
#    Draft diligence state: Business Overview (draft), Thesis (empty), Catalysts (draft), ..."
#    The agent has full access to memory_read, memory_recall, run_agent, and all
#    other tools — per-user physical isolation (Invariant 1) eliminates cross-user
#    contamination. Prompt guidance (not code enforcement) tells the agent which
#    store to use for which data (research.db for workspace state, memory tools
#    for general ticker observations).

# STEP 3: Runtime calls LLM with FULL tool catalog (unchanged) + research prompt stack
# STEP 4: Streams response back via SSE
# STEP 5: Server-side persistence hook saves agent message to research.db after stream completes
```

**Context freshness:** because `ResearchRepository` reads from the per-user file at prompt-build time, every turn sees the latest state. No separate context enricher, no sync mechanism needed.

**Identity:** `research_file_id` (NOT `ticker`) is the identity threaded through the entire context flow. A workspace session is scoped to exactly one research file; two concurrent theses on the same ticker get different file IDs and therefore different threads, annotations, diligence state, and handoffs.

**Policy layer role (after per-user migration):** The policy layer now provides research-specific prompt guidance + file context block injection only. It does NOT restrict tool access — the agent retains full memory + sub-agent capability because all ai-excel-addin state is per-user (Invariant 1). Invariant 11 (user sole authority on stage/conviction) is enforced by code review of `PATCH /files/{id}` callers. See Section 8 for where the policy lives.

---

## 7. Key Invariants

These are the architecture rules that must hold across all code. Each invariant is marked **enforced** (code prevents violation), **tested** (test suite catches violation), or **advisory** (documented but not mechanically enforced).

1. **Per-user isolation is physical across ALL ai-excel-addin state** — [ENFORCED by construction]. Every piece of user-owned persistent state lives under `data/users/{user_id}/` — research workspace (`research.db`), existing analyst memory (`analyst_memory.db`, migrated from `api/memory/analyst_memory.db` in Phase 1 Step 0), markdown sync (`workspace/tickers/*.md`, also per-user), filing annotations (Phase 2 stubs), exports (Phase 4). No `user_key` columns. Cross-user queries impossible because the filesystem directory itself is the scope. Both stores (research and memory) are accessed via factory patterns (`ResearchRepositoryFactory`, `MemoryStoreFactory`) that resolve `user_id → per-user path → store instance`.

2. **Research workspace code DOES touch memory tools** — [DELIBERATE]. Under the per-user-everything model, the research agent has full access to `memory_*` tools and `run_agent`. There's no contamination risk because `memory_store` / `memory_recall` / `memory_read` read and write to the user's OWN `analyst_memory.db` under `data/users/{user_id}/`, not a shared file. The research agent benefits from accumulated ticker knowledge across sessions exactly the way the general analyst agent does. The two stores (research workspace and general memory) coexist in the same per-user directory, and the agent is trusted to write workspace-specific state to `research.db` and general ticker observations to `analyst_memory.db` based on context. Prompt guidance (not code enforcement) tells the agent which store is appropriate for which data.

3. **User_id is always proxy-injected** — [ENFORCED at proxy layer, TRUSTED downstream]. **Two proxy paths:** (a) CRUD requests go through `routes/research_content.py` which extracts user_id from the authenticated session and forwards. (b) Chat requests (`POST /chat`) go through `routes/gateway_proxy.py` which extracts user_id from the authenticated session and injects via gateway strict mode. In both cases, user_id is NEVER trusted from client input. Ai-excel-addin does NOT re-validate. **Scope of trust:** applies to proxy-routed requests only.

4. **Tier gating lives at the proxy boundary** — [ENFORCED at proxy layer]. **Two enforcement points:** (a) CRUD: `create_tier_dependency(minimum_tier="paid")` at `routes/research_content.py`. (b) Chat: gateway proxy checks tier when `purpose='research_workspace'` is in the context payload. Ai-excel-addin does not duplicate the check in either case.

5. **User messages are persisted before the turn runs; agent messages are persisted on stream completion** — [ENFORCED by runtime hook]. **Honest failure semantics:**
   - User message save fails → reject turn before stream starts (no drift)
   - Agent message save fails after stream → agent reply is lost server-side; client may have streamed content in memory but it's not durable; reload shows only user message
   - Client disconnects mid-stream → gateway cancels runner (current behavior); user message persisted, agent reply not persisted; reload shows only user message
   - **Phase 1 accepts partial loss on disconnect.** Run-to-completion and incremental persistence are later-phase upgrades if UX hurts.

6. **Filing text is immutable once ingested** — [ENFORCED by content-addressed naming]. `filing_id` includes an 8-char content hash suffix (e.g., `VALE_10K_2024_a3f8b2c1`). Re-ingesting the same filing produces a NEW filing_id; does not overwrite the old file. Annotations keep pointing at the exact text they were created against.

7. **Char offsets are the stable annotation reference** — [ENFORCED by schema]. Paragraph numbers are display sugar, computed lazily at citation-render time from immutable filing text. NEVER persisted as annotation fields. Annotation schema does NOT include a `para_id` column.

8. **Handoff artifact is the contract between research and model builder** — [ENFORCED by schema]. Not EAV writes. Not side effects. A structured JSON blob in `research_handoffs` table with stable schema (versioned). All research → model flow goes through this contract. `research_handoffs.research_file_id` is the lookup key; `research_handoffs.ticker` is a denormalized snapshot field only.

9. **`model_build()` stays unchanged** — [ENFORCED by code review]. Research integration is via additive post-build tool `annotate_model_with_research()` orchestrated by `BuildModelOrchestrator`. The research workspace does NOT modify the stable, Codex-reviewed model build path.

10. **Post-annotation workbook numerics are NOT trusted server-side** — [ADVISORY, not mechanically enforced]. openpyxl does not recompute formulas on save; the model-engine reader falls back to cached values in some cases. `annotate_model_with_research()` sets `fullCalcOnLoad=True` + `forceFullCalc=True` and clears the model-engine cache, but this only helps **when Excel opens the file**. **No server-side readback smoke test can close this gap** — that would require a headless Excel instance, out of Phase 4 scope. **The workbook is valid only once Excel opens it and recalculates.** If Phase 4+ surfaces a need for trusted server-side numerics, add a dedicated headless-Excel invocation tool; do not attempt to close it via openpyxl tricks.

11. **User is sole authority on conviction/stage** — [ENFORCED by code review]. Agent MAY suggest changes via message metadata (`proposed_stage`, `proposed_conviction`), but NEVER writes directly to `research_files`. PATCH endpoints for these fields are only invoked from UI actions.

12. **Connection-per-request for SQLite** — [ENFORCED by `ResearchRepository` pattern]. Open → use → close per operation. Long-lived connection caching is OPT-IN, added only after profiling shows opens matter, with explicit in-use/idle tracking, LRU eviction, and forced close on eviction. Default is no caching.

13. **Qualitative factors are extensible by design** — [ENFORCED by schema]. Free-form `category` strings, schema-free per-category `data` blobs. Schema changes are NOT required to add new factor types. Seed categories are suggestions, not enumerations.

14. **Diligence finalization is never blocked on completion state** — [ENFORCED by service layer]. Users can finalize handoffs with any combination of `empty/draft/confirmed` section states. Forcing completion creates rubber-stamp incentive.

15. **Research content is scoped by `research_file_id`, not `ticker`** — [ENFORCED by schema + code review]. All `research_threads`, `research_messages` (via thread_id), `annotations`, and `research_handoffs` carry `research_file_id` as their primary identity. The `ticker` field appears on `research_files` (user-facing) and `research_handoffs` (denormalized snapshot), but is NEVER used as a lookup key for content. Two concurrent theses on the same ticker create two file rows and two independent content trees.

---

## 8. Component Responsibilities

### Frontend (risk_module)
| Component | Owns |
|---|---|
| `researchStore.ts` | Zustand state — tabs, messagesByThread, activeFile, bootstrap state |
| `ResearchStreamManager` | React context singleton, promise-sequenced aborts, 409 retry, input lock on error |
| `useResearchChat` | Per-thread send/retry, optimistic UI + reconciliation, agent placeholder creation |
| `useResearchBootstrap` | File upsert + thread get-or-create + message hydration + store.hydrate() |
| `useResearchFiles/Threads/Messages` | React Query cache for CRUD |
| `hashSync.ts` | `#research/VALE` deep link parsing + hydration, `hydrateFromHash` before `setInitialHash` |
| Component tree | 11 new components rendering the two-pane workspace + tabs + upgrade gate |

### Backend (risk_module)
| File | Owns |
|---|---|
| `routes/research_content.py` | Thin proxy: tier gate, user_id injection, forward to gateway. NO business logic, NO DB access. |
| `routes/gateway_proxy.py` | Existing, unchanged (no research-specific enricher — Decision 1 deleted it) |

### Gateway (app-platform)
| Component | Owns |
|---|---|
| Multi-user routing | Existing, unchanged |
| SSE streaming | Existing, unchanged |
| Strict-mode user_id validation | Consumer-side (Phase 1.4, already shipped) |

### AI-Excel-Addin (new research layer)
| File | Owns |
|---|---|
| `api/research/routes.py` | REST endpoints for research CRUD (files, threads, messages, documents, extractions, annotations, handoffs, build-model); validates inputs; delegates to services |
| `api/research/repository.py` | `ResearchRepository` + factory; per-user file routing; connection lifecycle (connection-per-request); lazy schema migrations; all SQLite access for research tables |
| `api/research/policy.py` | **Research-Mode Policy Layer (prompt routing only)** — `is_research_workspace(context)` predicate and `build_research_prompt_stack(context)` which assembles research-specific system prompt blocks + the file context block from `context.py`. Does NOT restrict tool access: the agent retains full `memory_*` + `run_agent` + all other tools because all ai-excel-addin state is per-user (Invariant 1). The policy layer's sole job is routing research turns to a research-appropriate prompt stack that doesn't drag in inappropriate guidance from the generic prompt path. |
| `api/research/context.py` | `build_research_context(user_id, research_file_id, thread_id, tab_context)` — assembles the research context prompt block from repository queries. Called from `policy.build_research_prompt_stack()`. |
| `api/research/handoff.py` | Handoff artifact assembly from research state; `research_handoffs` row construction; diligence state snapshot. |
| `api/research/build_model_orchestrator.py` | **Phase 4** — orchestrates the two-step `model_build()` → `annotate_model_with_research()` sequence for the `POST /handoffs/{id}/build-model` endpoint. Not a direct MCP path from the frontend. |
| `api/research/document_service.py` | **Phase 2** — reads filings from shared `data/filings/`, parses sections, calls langextract for extractions. Stateless read-only service. |
| `api/agent/interactive/runtime.py` (extended) | Chat runtime hooks for server-side message persistence (pre-turn save of user message committed to disk BEFORE first SSE yield, post-stream save of agent message). When `purpose='research_workspace'`, delegates prompt assembly to the research policy layer. Tool catalog and local handlers are UNCHANGED for research turns — agent has full tool surface. |
| `api/agent/shared/system_prompt.py` (extended) | When `purpose='research_workspace'`: delegate to `research.policy.build_research_prompt_stack()` instead of the default prompt assembly. |
| `api/memory/store.py` (extended) | `AnalystMemoryStore` accepts a `db_path` argument so instances can be constructed per-user. `get_memory_store(user_id)` resolves to `data/users/{user_id}/analyst_memory.db`. |
| `api/memory/markdown_sync.py` (extended) | Workspace directory resolution uses `data/users/{user_id}/workspace/tickers/`, not the shared `api/memory/workspace/`. |
| `api/memory/ingest.py` + 9 screener connectors | Each writes to the authenticated user's memory store by passing `user_id` through the ingest chain. |

### AI-Excel-Addin (existing, extended)
| Component | Change |
|---|---|
| `api/agent/shared/system_prompt.py` | Extended: when `purpose='research_workspace'`, delegates to `research.policy.build_research_prompt_stack()` which calls `build_research_context()` |
| `mcp_servers/langextract_mcp/schemas.py` | Phase 2: add 3 new schemas (`management_commentary`, `competitive_positioning`, `segment_discussion`) |
| `mcp_servers/langextract_mcp/text_utils.py` | Phase 2: filing output naming convention adds content hash suffix |
| Model engine (`schema/build.py`, `update_model`) | UNCHANGED |

### AI-Excel-Addin (existing, migrated in Phase 1 Step 0)
| Component | Change |
|---|---|
| `AnalystMemoryStore` | Extended to accept per-user `db_path`. Accessed via `MemoryStoreFactory(user_id)`. Same EAV schema; same API; same 9 screener connectors. Only the path resolution changes. |
| `workspace/tickers/*.md` markdown sync | Paths resolved per-user: `data/users/{user_id}/workspace/tickers/{TICKER}.md`. Sync logic unchanged. |
| `analyst_memory.db` | Migrated once from `api/memory/analyst_memory.db` to `data/users/{first_user_id}/analyst_memory.db`. New users get empty DBs on first memory write. |

### New MCP Tools (Phase 4)
| Tool | Owns |
|---|---|
| `annotate_model_with_research(model_path, handoff_id)` | Load handoff, write assumptions to driver cells, write research context to hidden metadata sheet, save with `fullCalcOnLoad=True` + `forceFullCalc=True`, clear model-engine cache. **Does NOT perform server-side readback** — openpyxl can't verify recalc. Workbook is only valid once Excel opens it. |

---

## 9. Phase Delivery Map

What each phase delivers, anchored to this architecture:

- **Phase 1** — Storage layer (`research.db` schema, `ResearchRepository`), REST endpoints for files/threads/messages, agent context flow, chat streaming with research context, frontend two-pane workspace with Explore tab and panel, `#research/VALE` deep links, tier gate. **No documents, no annotations, no diligence, no handoff.**

- **Phase 2** — Document tabs (filing + transcript rendering via existing tooling), annotation schema + UI, text-selection → agent panel plumbing, agent highlights from langextract extractions, 3 new langextract schemas, filing content-hash versioning, deterministic paragraph split rule. **No diligence, no handoff.**

- **Phase 3** — Diligence checklist UI (9 core + qualitative factors), per-section state model, agent initial pull sequence, style-aware factor suggestions, `fetch_data_for(category, ticker)` registry. **No handoff, no model build.**

- **Phase 4** — `research_handoffs` table + lifecycle, handoff artifact assembly, "Finalize Report" flow, `annotate_model_with_research()` MCP tool, SIA driver-name → cell-address mapping, workbook recalc safeguards. **This closes the pipeline.**

- **Phase 5** — Deferred (scope doc only): multi-ticker themes, `valuation_signals`/`capital_structure_detail` langextract schemas, bidirectional analyst-memory sync, web search integration, PDF/markdown report export.

**Note:** Per-user markdown sync for `tickers/*.md` is a **Phase 1 Step 0** deliverable (part of the memory per-user migration), NOT deferred to Phase 5. After Phase 1 Step 0, ALL ai-excel-addin state — including existing `analyst_memory.db` and `workspace/tickers/*.md` — lives under `data/users/{user_id}/` with per-user physical isolation.

---

## 10. What This Architecture Is NOT

Being explicit about non-goals prevents scope creep.

- **Not a multi-host scalable service.** Per-user SQLite on local disk is a transitional design for single-host deploy (Phase 6A). Horizontal scaling requires Postgres consolidation; that's a post-Phase-4 migration, not a Phase 1-4 concern.
- **Not a replacement for the existing analyst memory.** After Phase 1 Step 0, `AnalystMemoryStore` + markdown sync are migrated to per-user paths (`data/users/{user_id}/`) alongside `research.db`. Both stores coexist in the same per-user directory. The research workspace is a separate domain from general ticker memory; both are now per-user by physical isolation. Eventual convergence (bidirectional sync) is deferred to Phase 5.
- **Not a document editor.** Filings and transcripts render as read-only. Annotations are overlays, not edits to source documents.
- **Not a collaborative multi-analyst workspace.** Single analyst per research file. No real-time co-editing, no concurrent writes from multiple sessions. If needed later, handled by Postgres migration + operational transforms.
- **Not a chat history replacement.** Research threads + messages are scoped to a ticker + research file. Not a general chat history for the agent.
- **Not an autonomous research agent.** Human + agent collaborate; the agent doesn't run research unattended. Autonomous runners are a Phase 5+ consideration.
