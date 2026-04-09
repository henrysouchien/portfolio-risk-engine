# Research Workspace — Phase 1 Implementation Plan

**Status:** DRAFT v4 — Codex review rounds 1-3 complete. All findings addressed.
**Date:** 2026-04-04
**Spec:** `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md`
**Checkpoint:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_CHECKPOINT.md`
**TODO ref:** Group 5

---

## What Phase 1 Delivers

- Research file CRUD (create-or-get upsert, list, filter by stage)
- Two-pane layout: reader (main) + agent panel (280px right)
- IDE-style tabs (Explore always open, thread tabs)
- Explore tab with conversation feed
- Thread creation from conversation ("Start thread →")
- Agent panel with contextual conversation (tab-aware)
- Server-side message persistence (user message before turn, agent message on completion)
- Thread resumption on return (bootstrap hydration)
- Navigation: `#research/VALE` deep links
- Paid-tier gate with upgrade surface
- User is sole authority on conviction/stage (agent may suggest, never writes)

---

## Codex Review Findings

### Round 1 (v1 → v2): 10 findings, all addressed

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | SQLite tables have no `user_key` | CRITICAL | `user_key NOT NULL` on threads + unique indexes |
| 2 | `GatewayClaudeService` doesn't accept arbitrary context | HIGH | Extract shared `_streamRequest()`, add `contextOverrides` |
| 3 | Stream lock has no abort/queue | HIGH | Module-level `ResearchStreamManager` singleton |
| 4 | "Persist after exchange" loses messages | HIGH | Server-side persistence during turn |
| 5 | Thread resumption not wired | HIGH | `useResearchBootstrap` + `hydrate()` |
| 6 | Agent can't load thread context | HIGH | `build_research_context()` in prompt assembly |
| 7 | Container import path split | LOW | Re-export from same path |
| 8 | Shared session — state bleed | HIGH | Stateless-per-turn transcript |
| 9 | Deep-link needs context + tier gate | HIGH | `ParsedHash.context` + upgrade surface |
| 10 | No CRUD proxy infrastructure | HIGH | `research_content_router` |

### Round 2 (v2 → v3): 6 partial + 3 new findings, all addressed

| # | Finding | Severity | Fix in v3 |
|---|---------|----------|-----------|
| 1p | Message endpoint ownership-blind | HIGH | `GET /messages` joins on `research_threads.user_key` to verify ownership |
| 3p | StreamManager not singleton, missing cleanup/retry | HIGH | Module-level singleton via React context, `onComplete` clears controller, 200ms delay after abort before retry |
| 4p | Client/server consistency contradictory | HIGH | Server is sole source of truth. No "frontend fallback". On error, mark message pending, reconcile from server on next bootstrap |
| 5p | Bootstrap missing create-or-get semantics | HIGH | File POST is upsert (ON CONFLICT returns existing). Bootstrap calls `get_or_create_explore_thread` + `get_or_create_panel_thread` |
| 9p | hashSync `handlePopState`/`buildHash` incomplete | HIGH | Explicit changes listed for both functions + `setNavigationContext` call |
| 10p | Explore/panel thread creation not defined in bootstrap | HIGH | Proxy endpoint: `POST /threads` with `is_explore=true` uses `get_or_create_explore_thread` |
| N1 | Panel `tab_context` sent but never consumed | HIGH | `build_research_context()` accepts + resolves `tab_context` into active reader thread content |
| N2 | `sendResearchStream` duplicates transport | LOW | Extract `_streamRequest()` private method, both public methods call it |
| N3 | Conviction/stage authority contradictory | MEDIUM | User-only writes in Phase 1. Agent suggestions via proposed_stage/proposed_conviction in message metadata |

### Round 3 (v3 → v4): 4 remaining + 2 new findings, all addressed

| # | Finding | Severity | Fix in v4 |
|---|---------|----------|-----------|
| 3p | 200ms delay too short for 2s poll; cleanup race | HIGH | Promise-based sequencing + error chunk → throw conversion (GatewayClaudeService yields error chunks, not throws). 409 retry with 2.5s backoff. |
| 4p | Client builds transcript from local state with pending rows | HIGH | After error, lock sending until user retries. On retry, reconcile from server before building transcript. |
| 9p | `setInitialHash()` overwrites `#research/VALE` on first load | HIGH | `hydrateFromHash()` before `setInitialHash`. `setInitialHash` updated to pass `navigationContext` to `buildHash`. `handlePopState` handles context-only changes. |
| N1 | `tab_context` 'explore' string not resolved | HIGH | Frontend sends numeric thread IDs as `tab_context`, never strings. Explore tab sends `exploreThreadId`. |
| NEW1 | `ClaudeStreamChunk` uses `content` not `text`; placeholder timing | MEDIUM | Use `chunk.content`. Create agent placeholder before streaming (matching usePortfolioChat pattern). |
| NEW2 | 50-message bootstrap truncates long threads | MEDIUM | Known Phase 1 limitation. Agent prompt notes context window. Phase 2: server-side compaction. |

---

## Step 1: Postgres Migration — `research_files` table

**File:** `database/migrations/20260404_research_files.sql`

```sql
CREATE TABLE IF NOT EXISTS research_files (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ticker VARCHAR(20) NOT NULL,
  company_name VARCHAR(200),
  stage VARCHAR(20) NOT NULL DEFAULT 'exploring',
  direction VARCHAR(10),
  strategy VARCHAR(20),
  conviction INTEGER,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_research_files_user ON research_files(user_id);
CREATE INDEX IF NOT EXISTS idx_research_files_stage ON research_files(user_id, stage);
```

**Constraints:** `stage IN ('exploring','has_thesis','diligence','decision','monitoring','closed')`, `direction IN ('long','short','hedge','pair')`, `strategy IN ('value','special_situation','macro','compounder')`, `conviction` 1-5.

**Pattern:** Follows `database/migrations/20260327_add_short_cover_sides.sql`.

---

## Step 2: REST CRUD — `/api/research/files`

**New file:** `routes/research.py`

**Endpoints:**

| Method | Path | Body/Params | Returns | Auth |
|--------|------|-------------|---------|------|
| `GET` | `/api/research/files` | `?stage=exploring` | `[{id, ticker, company_name, stage, direction, strategy, conviction, created_at, updated_at}]` | paid |
| `POST` | `/api/research/files` | `{ticker, company_name?, direction?, strategy?}` | `{id, ticker, ...}` (upsert — returns existing on conflict) | paid |
| `PATCH` | `/api/research/files/{id}` | `{stage?, conviction?, direction?, strategy?}` | `{id, ticker, ...}` | paid |
| `DELETE` | `/api/research/files/{id}` | — | `204` | paid |

**Pattern:** Follows `routes/baskets_api.py` — FastAPI `APIRouter`, `create_tier_dependency(auth_service, minimum_tier="paid")`, raw SQL via `get_db_session()`.

**Register in `app.py`:**
```python
from routes.research import research_router
app.include_router(research_router)
```

**PATCH also touches `updated_at`** via `SET updated_at = NOW()`.

**POST upsert semantics** (Fix for Finding 5p): `INSERT ... ON CONFLICT (user_id, ticker) DO UPDATE SET updated_at = NOW() RETURNING *`. Returns 200 with existing row on conflict, not 409. This lets the bootstrap flow call POST idempotently.

---

## Step 3: ai-excel-addin SQLite Extensions

**File:** `/Users/henrychien/Documents/Jupyter/AI-excel-addin/api/memory/store.py` — extend `AnalystMemoryStore._maybe_migrate()`

> **[Fix for Finding 1]** All tables include `user_key TEXT NOT NULL` for multi-user isolation. Unique constraints prevent duplicate explore/panel threads per user+ticker.

**New tables:**
```sql
CREATE TABLE IF NOT EXISTS research_threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_key TEXT NOT NULL,
  ticker TEXT NOT NULL,
  name TEXT NOT NULL,
  finding_summary TEXT,
  is_explore INTEGER NOT NULL DEFAULT 0,
  is_panel INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_threads_user_ticker ON research_threads(user_key, ticker);
CREATE UNIQUE INDEX IF NOT EXISTS idx_research_threads_explore
  ON research_threads(user_key, ticker) WHERE is_explore = 1;
CREATE UNIQUE INDEX IF NOT EXISTS idx_research_threads_panel
  ON research_threads(user_key, ticker) WHERE is_panel = 1;

CREATE TABLE IF NOT EXISTS research_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES research_threads(id) ON DELETE CASCADE,
  author TEXT NOT NULL,
  content TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'message',
  tab_context TEXT,
  metadata TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_messages_thread ON research_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_research_messages_created ON research_messages(thread_id, created_at);
```

**New methods on `AnalystMemoryStore`:**
- `create_research_thread(user_key, ticker, name, is_explore=False, is_panel=False) -> int`
- `get_or_create_explore_thread(user_key, ticker) -> int` — idempotent, returns existing explore thread or creates one
- `get_or_create_panel_thread(user_key, ticker) -> int` — same for panel
- `get_research_threads(user_key, ticker) -> list[dict]`
- `save_research_message(thread_id, author, content, content_type="message", tab_context=None, metadata=None) -> int`
- `get_research_messages(thread_id, limit=100, before_id=None) -> list[dict]`
- `update_thread_finding(thread_id, finding_summary) -> None`
- `get_thread_summary(thread_id) -> dict | None` — returns thread with message count, last message timestamp

**Pattern:** Same raw sqlite3 + threading lock pattern as existing `store_memory()`/`get_memories()`.

---

## Step 4: Gateway Protocol Extension

### 4a: Context enricher (risk_module)

**File:** `routes/gateway_proxy.py` — add `context_enricher` to `GatewayConfig`

```python
def _research_context_enricher(request, user, context):
    """Inject research file metadata when purpose=research."""
    if context.get("purpose") != "research":
        return context
    ticker = context.get("ticker")
    if not ticker:
        return context
    user_id = user.get("user_id")
    if not user_id:
        return context
    from database import get_db_session
    with get_db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT stage, conviction, direction, strategy FROM research_files WHERE user_id=%s AND ticker=%s",
            (user_id, ticker)
        )
        row = cur.fetchone()
    if row:
        context["research_file"] = dict(row)
    return context

_config = GatewayConfig(
    gateway_url=lambda: os.getenv("GATEWAY_URL", ""),
    api_key=lambda: os.getenv("GATEWAY_API_KEY", ""),
    ssl_verify=lambda: _parse_ssl_verify(os.getenv("GATEWAY_SSL_VERIFY", "")),
    context_enricher=_research_context_enricher,
)
```

The enricher runs via `asyncio.to_thread()` in `app_platform/gateway/proxy.py` line 198 so synchronous DB calls are safe.

### 4b: System prompt injection (ai-excel-addin)

> **[Fix for Finding 6]** Agent loads thread context directly from its own SQLite, not via the enricher.

**File:** `api/agent/shared/system_prompt.py` — extend `build_system_prompt_blocks()`

When `context.get("purpose") == "research"`:

1. Read `context["research_file"]` (from enricher) for stage/conviction/direction/strategy
2. Call new `build_research_context(user_key, thread_id, ticker)` which:
   - Queries `research_threads` for this user+ticker to get all thread names + pinned findings
   - Queries `research_messages` for the active `thread_id` (last 20 messages for context)
   - Queries `research_messages` for the panel thread (last 10 for panel awareness)
   - Returns a formatted context block
3. Inject as a system prompt block: research file metadata + thread summaries + recent messages + active findings

**New file:** `api/agent/shared/research_context.py`

> **[Fix for New Finding 1]** `build_research_context()` accepts `tab_context` and resolves it into the active reader thread's content for panel contextuality.

```python
def build_research_context(
    memory_store: AnalystMemoryStore,
    user_key: str,
    ticker: str,
    thread_id: int | None,
    tab_context: str | None,
    research_file: dict | None,
) -> str:
    """Build research context block for system prompt injection.
    
    Args:
        thread_id: The thread being sent to (explore or panel).
        tab_context: The numeric thread ID of the active reader tab.
                     Frontend ALWAYS sends numeric IDs (explore sends exploreThreadId,
                     named threads send their thread ID). Never a string like 'explore'.
                     Used to load the reader's recent messages so the panel agent
                     knows what you're looking at.
    """
    # 1. Get all threads for this ticker
    threads = memory_store.get_research_threads(user_key, ticker)
    # 2. Get recent messages for the sending thread
    active_messages = memory_store.get_research_messages(thread_id, limit=20) if thread_id else []
    # 3. If this is a panel request with tab_context, also load the active reader thread
    reader_context_messages = []
    if tab_context and str(tab_context) != str(thread_id):
        reader_thread_id = int(tab_context)
        reader_context_messages = memory_store.get_research_messages(reader_thread_id, limit=10)
    # 4. Collect pinned findings across threads
    findings = [t for t in threads if t.get("finding_summary")]
    # 5. Format into a prompt block
    return _format_research_block(research_file, threads, active_messages, reader_context_messages, findings)
```

**Called from:** `build_system_prompt_blocks()` when `context.get("purpose") == "research"`. The `user_key` comes from `context["user_id"]` (injected by the proxy). `tab_context` comes from `context["tab_context"]` (sent by frontend).

### 4c: Research content proxy (risk_module)

> **[Fix for Finding 10]** New dedicated proxy router for thread/message CRUD. Not on the streaming gateway — separate JSON proxy.

**New file:** `routes/research_content.py`

A lightweight JSON proxy that forwards authenticated requests to `{GATEWAY_URL}/api/research/*`:

```python
from app_platform.auth.dependencies import create_tier_dependency
from services.auth_service import auth_service

_get_paid_user = create_tier_dependency(auth_service, minimum_tier="paid")

research_content_router = APIRouter(prefix="/api/research/content", tags=["research-content"])

@research_content_router.get("/threads")
async def list_threads(ticker: str, user = Depends(_get_paid_user)):
    """Proxy thread list to ai-excel-addin."""
    # Forward to GATEWAY_URL/api/research/threads?user_key={user_key}&ticker={ticker}
    ...

@research_content_router.post("/threads")
async def create_thread(body: CreateThreadRequest, user = Depends(_get_paid_user)):
    ...

@research_content_router.get("/messages")
async def list_messages(thread_id: int, limit: int = 100, user = Depends(_get_paid_user)):
    ...
```

Uses the same `GatewaySessionManager` session token for auth to the upstream. Reuses `_get_user_key()` from the gateway proxy pattern.

**ai-excel-addin side:** New router registered in `api/main.py`:

```python
# api/routes/research_api.py

@router.get("/api/research/threads")
async def list_threads(user_key: str, ticker: str):
    threads = memory_store.get_research_threads(user_key, ticker)
    return {"threads": threads}

@router.post("/api/research/threads")
async def create_thread(body: CreateThreadBody):
    """Create a thread. If is_explore=true or is_panel=true, uses get_or_create for idempotency."""
    if body.is_explore:
        thread_id = memory_store.get_or_create_explore_thread(body.user_key, body.ticker)
    elif body.is_panel:
        thread_id = memory_store.get_or_create_panel_thread(body.user_key, body.ticker)
    else:
        thread_id = memory_store.create_research_thread(body.user_key, body.ticker, body.name)
    thread = memory_store.get_thread_summary(thread_id)
    return thread

@router.get("/api/research/messages")
async def list_messages(user_key: str, thread_id: int, limit: int = 100):
    """List messages. Verifies thread belongs to user_key via JOIN before returning."""
    # SELECT m.* FROM research_messages m
    # JOIN research_threads t ON t.id = m.thread_id
    # WHERE m.thread_id = ? AND t.user_key = ?
    # ORDER BY m.created_at ASC LIMIT ?
    messages = memory_store.get_research_messages_for_user(user_key, thread_id, limit=limit)
    return {"messages": messages}

# No POST /messages from frontend — messages are persisted server-side during turn processing (Finding 4)
```

> **[Fix for Finding 1p]** `get_research_messages_for_user()` JOINs on `research_threads.user_key` to verify the requesting user owns the thread. Direct `get_research_messages(thread_id)` is only used server-side (prompt assembly, turn persistence).
>
> **[Fix for Finding 10p]** `POST /threads` with `is_explore=true` calls `get_or_create_explore_thread()` — idempotent. Bootstrap calls this to ensure explore+panel threads exist before hydrating.

**risk_module proxy side** (`routes/research_content.py`): Each endpoint injects `user_key` from the authenticated session (via `_get_user_key(user)`), never trusts the client. The `user_key` parameter on ai-excel-addin endpoints comes from the proxy, not the frontend.

**Register in `app.py`:**
```python
from routes.research_content import research_content_router
app.include_router(research_content_router)
```

### 4d: Server-side message persistence (ai-excel-addin)

> **[Fix for Finding 4]** Messages persist server-side during turn processing, not after-the-fact from the frontend. Tab close doesn't lose messages.

**File:** `api/agent/interactive/runtime.py`

When `context.get("purpose") == "research"` and `context.get("thread_id")` is present:

1. **Before agent runs:** Persist the user message to `research_messages` (the last message in `request.messages`)
2. **After agent completes:** Persist the agent response to `research_messages`
3. Both happen inside `_build_chat_runtime()` setup via a new `on_turn_complete` hook, or as wrapper logic around the runner invocation in the gateway server's chat handler.

Implementation: Add an `on_turn_start` and `on_turn_complete` callback to `ChatRuntime` (or use the existing `on_tool_result` pattern). The runtime checks `context["purpose"] == "research"` and calls `memory_store.save_research_message()`.

**Key:** The user message is persisted *before* the agent runs, so even if streaming fails mid-turn, the user's input is captured. The agent response is persisted on stream completion.

---

## Step 5: Zustand `researchStore`

**New file:** `frontend/packages/connectors/src/stores/researchStore.ts`

> **[Fix for Finding 5]** Added `hydrate()` action, `exploreThreadId`, and bootstrap flow.

**State shape:**
```typescript
interface ResearchTab {
  id: string;           // 'explore' | thread_id string
  type: 'explore' | 'thread' | 'document';
  label: string;        // 'Explore' | 'Ownership' | '10-K §2.1'
  closeable: boolean;   // explore=false, others=true
  threadId?: number;
}

interface ResearchMessage {
  id: string;
  threadId: number;
  author: 'user' | 'agent';
  content: string;
  contentType: 'message' | 'note' | 'tool_call' | 'artifact';
  tabContext?: string;
  metadata?: Record<string, unknown>;
  createdAt: number;
}

interface ResearchState {
  // Active research file
  activeFile: { id: number; ticker: string; companyName?: string; stage: string; } | null;
  
  // Thread IDs for the two fixed threads
  exploreThreadId: number | null;
  panelThreadId: number | null;
  
  // Tabs (reader pane only — panel is always visible, not a tab)
  tabs: ResearchTab[];
  activeTabId: string;
  
  // Messages per thread (keyed by threadId)
  messagesByThread: Record<number, ResearchMessage[]>;
  
  // Streaming state
  isStreaming: boolean;
  streamingThreadId: number | null;
  
  // Bootstrap
  isBootstrapped: boolean;
}

interface ResearchActions {
  // Bootstrap — called once when opening a research file
  hydrate(params: {
    file: ResearchState['activeFile'];
    exploreThreadId: number;
    panelThreadId: number;
    threads: Array<{ id: number; name: string; finding_summary?: string }>;
    messagesByThread: Record<number, ResearchMessage[]>;
  }): void;
  
  // File
  setActiveFile(file: ResearchState['activeFile']): void;
  
  // Tabs
  openTab(tab: ResearchTab): void;
  closeTab(tabId: string): void;
  setActiveTab(tabId: string): void;
  
  // Messages
  addMessage(threadId: number, message: ResearchMessage): void;
  appendToLastMessage(threadId: number, text: string): void; // streaming
  
  // Threads
  createThread(name: string, ticker: string): void;
  
  // Streaming
  setStreaming(threadId: number | null): void;
  
  // Reset
  reset(): void;
}
```

**Pattern:** `createWithEqualityFn` + `devtools` middleware + `shallow` equality selectors (follows `uiStore.ts`).

**`hydrate()` implementation:**
1. Sets `activeFile`, `exploreThreadId`, `panelThreadId`
2. Builds initial `tabs` array: Explore tab + one tab per non-explore/non-panel thread
3. Populates `messagesByThread` with loaded messages
4. Sets `activeTabId = 'explore'`
5. Sets `isBootstrapped = true`

---

## Step 6: `useResearchChat` Hook + Stream Manager

**New file:** `frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts`

> **[Fix for Finding 2 + N2]** Extract `_streamRequest()` in `GatewayClaudeService`, add `contextOverrides` param.
> **[Fix for Finding 3 + 3p + v4-3p]** React context singleton. Promise-based sequencing (await previous unwind, not timed delay). 409 retry with backoff.
> **[Fix for Finding 4p + v4-4p]** Server is source of truth. After error, lock input until retry. On retry, reconcile from server first.
> **[Fix for Finding 8]** Stateless-per-turn: each request includes full thread transcript. Shared session only holds auth + tool approvals (low-risk, not conversation state). Per-thread sessions deferred to Phase 2 if bleed observed.
> **[Fix for NEW1]** Use `chunk.content` (not `chunk.text`). Create agent placeholder before streaming (matching `usePortfolioChat` pattern).
> **[Fix for NEW2]** Phase 1: 50-message bootstrap is a known limitation. Older messages not in context window. Phase 2: server-side compaction/summary.

### GatewayClaudeService Refactor

**File:** `frontend/packages/chassis/src/services/GatewayClaudeService.ts`

Extract shared streaming logic into a private method. Both existing chat and research use it:

```typescript
// Private shared transport
private async* _streamRequest(
  messages: Array<{ role: string; content: string }>,
  context: Record<string, unknown>,
  signal?: AbortSignal,
): AsyncGenerator<ClaudeStreamChunk> {
  const response = await fetch(`${this.proxyUrl}/chat`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Accept': 'text/event-stream', 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, context: { channel: 'web', ...context } }),
    signal,
  });
  // ... existing SSE parsing + error handling (same as current sendMessageStream)
}

// Existing method — preserved for backward compat, delegates to _streamRequest
async* sendMessageStream(message, history, portfolioName?, purpose?, signal?) {
  const messages = [...history.map(...), { role: 'user', content: message }];
  const context = { ...(portfolioName ? { portfolio_name: portfolioName } : {}), ...(purpose ? { purpose } : {}) };
  yield* this._streamRequest(messages, context, signal);
}

// New: caller-controlled context for research workspace
async* streamWithContext(
  messages: Array<{ role: string; content: string }>,
  contextOverrides: Record<string, unknown>,
  signal?: AbortSignal,
): AsyncGenerator<ClaudeStreamChunk> {
  yield* this._streamRequest(messages, contextOverrides, signal);
}
```

### ResearchStreamManager

> **[v4 fix for 3p]** Promise-based sequencing replaces timed delay. `send()` awaits previous `send()`'s full unwind before starting new stream. 409 retry with exponential backoff.

Provided via React context at the `ResearchWorkspace` level so all tabs and the panel share one manager:

```typescript
// ResearchStreamContext.tsx
const ResearchStreamContext = createContext<ResearchStreamManager>(null!);

// Created once per ResearchWorkspace mount
const streamManager = useMemo(() => new ResearchStreamManager(), []);

class ResearchStreamManager {
  private abortController: AbortController | null = null;
  private activeThreadId: number | null = null;
  private currentSend: Promise<void> = Promise.resolve();  // tracks in-flight send for sequencing
  private _hasError: boolean = false;  // tracks error state for input locking
  
  async send(options: {
    threadId: number;
    messages: Array<{ role: string; content: string }>;
    context: Record<string, unknown>;
    service: GatewayClaudeService;
    onChunk: (chunk: ClaudeStreamChunk) => void;
    onComplete: () => void;
    onError: (error: Error) => void;
  }): Promise<void> {
    // 1. Abort previous stream if any
    if (this.abortController) {
      this.abortController.abort();
    }
    // 2. AWAIT previous send's full unwind (AbortError catch completes, cleanup runs)
    //    This ensures the backend stream is closed and the lock is released.
    await this.currentSend.catch(() => {});
    
    // 3. Start new send
    this.currentSend = this._doSend(options);
    return this.currentSend;
  }
  
  private async _doSend(options: Parameters<ResearchStreamManager['send']>[0]): Promise<void> {
    this.abortController = new AbortController();
    this.activeThreadId = options.threadId;
    this._hasError = false;
    
    const attempt = async (retryCount = 0): Promise<void> => {
      try {
        for await (const chunk of options.service.streamWithContext(
          options.messages, options.context, this.abortController!.signal
        )) {
          // CRITICAL: GatewayClaudeService yields { type: 'error', content: '...' } chunks
          // for non-200 responses instead of throwing. Convert to thrown errors so the
          // catch/retry path handles them (especially 409 stream lock contention).
          if (chunk.type === 'error') {
            throw new GatewayStreamError(chunk.content ?? 'Unknown gateway error');
          }
          options.onChunk(chunk);
        }
        this.cleanup();
        options.onComplete();
      } catch (err) {
        this.cleanup();
        if ((err as Error).name === 'AbortError') return; // intentional abort, no error callback
        
        // Retry once on 409 (stream lock contention) with backoff > 2s disconnect poll
        const errMsg = (err as Error).message || '';
        const is409 = errMsg.includes('409') || errMsg.includes('already active');
        if (is409 && retryCount < 1) {
          await new Promise(r => setTimeout(r, 2500));
          // Re-create abort controller for retry
          this.abortController = new AbortController();
          return attempt(retryCount + 1);
        }
        
        this._hasError = true;
        options.onError(err as Error);
      }
    };
    
    return attempt();
  }
  
  abort(): void {
    this.abortController?.abort();
    // Don't cleanup here — let _doSend's catch block handle it to avoid race
  }
  
  private cleanup(): void {
    this.abortController = null;
    this.activeThreadId = null;
  }
  
  get isStreaming(): boolean { return this.abortController !== null; }
  get currentThreadId(): number | null { return this.activeThreadId; }
  get hasError(): boolean { return this._hasError; }
  clearError(): void { this._hasError = false; }
}
```

### useResearchChat Hook

> **[v4 fix for NEW1]** Uses `chunk.content` (the actual `ClaudeStreamChunk` field, not `text`). Creates agent placeholder BEFORE streaming (matching `usePortfolioChat` pattern lines 620+).
> **[v4 fix for 4p]** After error, input is locked. On retry, reconcile from server first.
> **[v4 fix for NEW2]** `TRANSCRIPT_LIMIT = 50` messages sent per turn. Known Phase 1 limitation — older messages not in agent context window. Server-side compaction in Phase 2.

```typescript
const TRANSCRIPT_LIMIT = 50;  // Phase 1: agent sees last 50 messages per thread

function useResearchChat(options: {
  ticker: string;
  threadId: number;
  tabContext?: string;  // numeric thread ID of active reader tab (not string 'explore')
}) {
  const streamManager = useContext(ResearchStreamContext);
  
  const sendMessage = async (text: string) => {
    const store = researchStore.getState();
    
    // Build transcript from local state (last N messages, excluding any with pending status)
    const allMessages = store.messagesByThread[threadId] ?? [];
    const confirmedMessages = allMessages.filter(m => m.contentType !== 'pending_error');
    const recentMessages = confirmedMessages.slice(-TRANSCRIPT_LIMIT);
    const transcript = recentMessages.map(m => ({
      role: m.author === 'agent' ? 'assistant' : 'user',
      content: m.content,
    }));
    transcript.push({ role: 'user', content: text });
    
    // Optimistic UI: add user message
    store.addMessage(threadId, {
      id: `pending-${Date.now()}`, author: 'user', content: text, contentType: 'message',
      createdAt: Date.now() / 1000, threadId,
    });
    // Create agent placeholder BEFORE streaming (matches usePortfolioChat pattern)
    store.addMessage(threadId, {
      id: `agent-${Date.now()}`, author: 'agent', content: '',
      contentType: 'message', createdAt: Date.now() / 1000, threadId,
    });
    store.setStreaming(threadId);
    
    await streamManager.send({
      threadId,
      messages: transcript,
      context: {
        purpose: 'research',
        ticker,
        thread_id: threadId,
        tab_context: String(tabContext ?? store.exploreThreadId),  // always numeric
      },
      service: gatewayService,
      onChunk: (chunk) => {
        if (chunk.type === 'text_delta') {
          store.appendToLastMessage(threadId, chunk.content);  // .content not .text
        }
        // tool_call_start, tool_result etc. can be handled later
      },
      onComplete: () => { store.setStreaming(null); },
      onError: (err) => {
        store.setStreaming(null);
        // Don't remove messages — server may have persisted the user message.
        // Mark last agent message as error state for visual feedback.
        // Input stays locked (streamManager.hasError === true) until retry.
        showErrorToast(`Research chat error: ${err.message}`);
      },
    });
  };
  
  const retry = async () => {
    // Reconcile: reload messages from server to ensure transcript consistency
    const serverMessages = await fetchResearchMessages(threadId, TRANSCRIPT_LIMIT);
    researchStore.getState().replaceMessages(threadId, serverMessages);
    streamManager.clearError();
    // User can now type again
  };

  return {
    sendMessage,
    isStreaming: streamManager.isStreaming && streamManager.currentThreadId === threadId,
    hasError: streamManager.hasError,
    stop: () => streamManager.abort(),
    retry,
  };
}
```

**`researchStore.replaceMessages(threadId, messages)`** — new action that overwrites `messagesByThread[threadId]` with server-authoritative messages. Used during bootstrap AND error reconciliation.

**Client/server consistency model** (Fix for Finding 4p + v4-4p):
- **Server is source of truth.** Messages are persisted server-side during the turn (Step 4d).
- **On success:** Frontend's optimistic messages match server state. No reconciliation needed.
- **On error:** Input is locked (`streamManager.hasError`). User must click "Retry" which calls `retry()` — reconciles from server, then unlocks input.
- **On return visit:** `useResearchBootstrap` loads messages from server, replacing stale in-memory state.
- **Transcript limit:** Last 50 messages sent per turn. Acknowledged Phase 1 limitation.

**MessageInput disable rules:**
1. When `streamManager.isStreaming` → all inputs disabled, stop button shown
2. When `streamManager.hasError` → all inputs disabled, retry button shown
3. Otherwise → active tab's input enabled

---

## Step 7: Hash Routing Extension

> **[Fix for Finding 9 + 9p + v4-9p]** Extended `ParsedHash` with context. Proper initial-load hydration. All 6 touch points in hashSync addressed.

**File:** `frontend/packages/connectors/src/navigation/hashSync.ts`

**Problem (v4 fix):** On first load with URL `#research/VALE`, `setInitialHash()` reads the store's default `activeView` ('score'), builds `#score`, and **overwrites** the URL. The ticker is lost before any component mounts.

**Solution:** New `hydrateFromHash()` function runs BEFORE `setInitialHash`. It parses the URL hash and hydrates the store if valid.

**Change 1:** Extend `ParsedHash` interface:
```typescript
interface ParsedHash {
  view: ViewId;
  tool?: ScenarioToolId;
  context?: { ticker?: string };  // NEW
}
```

**Change 2:** Extend `parseHash()` — add research branch. The existing code splits on `/` at line 89 (`const [viewSegment, toolSegment] = normalized.split('/')`) — reuse this:
```typescript
export function parseHash(hash: string): ParsedHash | null {
  const normalized = normalizeHash(hash);
  if (!normalized) return null;

  const [viewSegment, secondSegment] = normalized.split('/');
  
  // Legacy alias
  if (viewSegment === 'factors') return { view: 'risk' };
  
  if (!viewSegment || !NAVIGABLE_VIEW_IDS.includes(viewSegment as ViewId)) return null;
  const view = viewSegment as ViewId;
  
  // NEW: research deep links (#research/VALE)
  if (view === 'research' && secondSegment) {
    return { view, context: { ticker: secondSegment.toUpperCase() } };
  }
  
  // Existing: scenarios (#scenarios/what-if)
  if (view === 'scenarios') {
    if (secondSegment && VALID_TOOL_IDS.includes(secondSegment as ScenarioToolId)) {
      return { view, tool: secondSegment as ScenarioToolId };
    }
  }
  
  return { view };
}
```

**Change 3:** Extend `buildHash()` signature — add optional `context` parameter:
```typescript
export function buildHash(view: ViewId, tool?: ScenarioToolId, context?: { ticker?: string }): string | null {
  if (view === 'report') return null;
  if (view === 'strategies') return '#scenarios';
  
  // NEW: research with ticker
  if (view === 'research' && context?.ticker) {
    return `#research/${context.ticker}`;
  }
  
  if (view === 'scenarios') {
    if (!tool || tool === 'landing') return '#scenarios';
    return `#scenarios/${tool}`;
  }
  
  return `#${view}`;
}
```

**Change 4:** NEW `hydrateFromHash()` — runs on initial load to prevent URL overwrite:
```typescript
export function hydrateFromHash(store: HashSyncStore): void {
  const parsed = parseHash(window.location.hash);
  if (!parsed) return;
  
  const state = store.getState();
  
  // Hydrate view
  if (state.activeView !== parsed.view) {
    _navigatingFromHash = true;
    try {
      state.setActiveView(parsed.view);
    } finally {
      _navigatingFromHash = false;
    }
  }
  
  // Hydrate tool (scenarios)
  if (parsed.view === 'scenarios' && parsed.tool) {
    const latestState = store.getState();
    if (latestState.activeTool !== parsed.tool) {
      latestState.setActiveTool(parsed.tool);
    }
  }
  
  // Hydrate context (research deep links)
  if (parsed.context) {
    store.getState().setNavigationContext(parsed.context);
  }
}
```

**Change 5:** Update `handlePopState()` — handle context changes even on same view:
```typescript
export function handlePopState(store: HashSyncStore): void {
  _pendingHash = null;
  _pendingReplace = false;
  
  const parsed = parseHash(window.location.hash);
  if (!parsed) return;
  
  const state = store.getState();
  const nextTool = parsed.view === 'scenarios' ? parsed.tool ?? 'landing' : 'landing';
  const hasSameView = state.activeView === parsed.view;
  const hasSameTool = state.activeTool === nextTool;
  
  // NEW: Check for context change even if view is the same (e.g., #research/VALE → #research/AAPL)
  const hasContextChange = JSON.stringify(parsed.context) !== JSON.stringify(state.navigationContext);
  
  if (hasSameView && !hasContextChange && (parsed.view !== 'scenarios' || hasSameTool)) {
    return;
  }
  
  _navigatingFromHash = true;
  try {
    if (!hasSameView) { state.setActiveView(parsed.view); }
    if (parsed.view === 'scenarios') {
      const latest = store.getState();
      if (latest.activeTool !== nextTool) { latest.setActiveTool(nextTool); }
    }
    // NEW: Set navigation context for research deep links
    if (parsed.context) { store.getState().setNavigationContext(parsed.context); }
    else if (hasContextChange) { store.getState().setNavigationContext(null); }
  } finally {
    _navigatingFromHash = false;
  }
}
```

**Change 6:** Update `initHashSync()` store subscription to pass context:
```typescript
export function initHashSync(store: HashSyncStore): () => void {
  let previousState = store.getState();
  return store.subscribe((state) => {
    const prevState = previousState;
    previousState = state;
    // NEW: pass navigationContext to buildHash
    const nextHash = buildHash(state.activeView, state.activeTool, state.navigationContext);
    // ... rest unchanged
  });
}
```

**File:** `frontend/packages/connectors/src/navigation/useHashSync.ts`

**Change 7:** Call `hydrateFromHash` BEFORE `setInitialHash`:
```typescript
export function useHashSync(): void {
  useEffect(() => {
    const store = useUIStore;
    hydrateFromHash(store);  // NEW — parse URL first, hydrate store
    setInitialHash(store);   // Now store matches URL, this is a no-op
    // ... rest unchanged
  }, []);
}
```

**Change 8:** Update `setInitialHash()` to pass `navigationContext` to `buildHash`:
```typescript
export function setInitialHash(store: HashSyncStore): void {
  const state = store.getState();
  // v4 fix: pass navigationContext so #research/VALE is preserved, not collapsed to #research
  const initialHash = buildHash(state.activeView, state.activeTool, state.navigationContext);
  if (initialHash === null) return;
  
  const currentHash = window.location.hash || '#';
  if (initialHash === currentHash) return;
  
  window.history.replaceState(null, '', initialHash);
}
```

**Note on store initialization:** `uiStore` already initializes `activeView` from the URL hash via `getStoredActiveView()` (line 112), which reads the first segment. So for `#research/VALE`, the store starts with `activeView = 'research'`. But `navigationContext` is NOT set during store init — that's why `hydrateFromHash()` is needed to set it before `setInitialHash()` runs.

**File:** `frontend/packages/connectors/src/stores/uiStore.ts`

No changes needed — `setNavigationContext` and `navigationContext` already exist.

---

## Step 8: Frontend Component Tree

> **[Fix for Finding 7]** Replace the existing `ResearchContainer.tsx` file in place — same import path, no lazy-import change needed in `ModernDashboardApp.tsx`.
> **[Fix for Finding 9]** Tier gate with upgrade surface inside `ResearchWorkspaceContainer`.

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/ResearchContainer.tsx` — gutted and replaced. This file becomes a thin shell that imports from `components/research/`:

```typescript
import ResearchWorkspaceContainer from '../../../research/ResearchWorkspaceContainer';
export default ResearchWorkspaceContainer;
```

**New component tree (in `frontend/packages/ui/src/components/research/`):**

```
ResearchWorkspaceContainer (entry point)
├── TierGate — checks user tier, shows upgrade surface if not paid
│   └── UpgradeSurface — "Research workspace requires a paid subscription" + CTA
├── ResearchListView (when no activeFile — list/create research files)
│   ├── ResearchFileCard (per file — ticker, stage, conviction, last updated)
│   └── NewResearchButton (creates file + opens workspace)
└── ResearchWorkspace (when activeFile is set)
    └── ResizablePanelGroup (horizontal)
        ├── ResizablePanel (defaultSize=75, minSize=50) — Reader
        │   ├── ResearchTabBar (IDE-style tabs)
        │   │   ├── Tab ("Explore" — always open, not closeable)
        │   │   ├── Tab (thread tabs — closeable)
        │   │   └── NewThreadButton (+)
        │   └── TabContent (renders based on activeTab)
        │       ├── ExploreTab → ConversationFeed + MessageInput
        │       └── ThreadTab → PinnedFinding + ConversationFeed + MessageInput
        ├── ResizableHandle
        └── ResizablePanel (defaultSize=25, minSize=15, maxSize=35) — Agent Panel
            ├── AgentPanelHeader ("RESEARCH ANALYST · Exploring · VALE")
            ├── ConversationFeed (panel thread messages)
            └── MessageInput (disabled when any stream is active)
```

**Bootstrap flow in ResearchWorkspaceContainer:**
1. Read `navigationContext?.ticker` from uiStore
2. If ticker present → call `useResearchBootstrap(ticker)`:
   - **Step A:** `POST /api/research/files` with `{ticker}` — upsert semantics, returns existing or creates new
   - **Step B:** `POST /api/research/content/threads` with `{ticker, is_explore: true}` — `get_or_create_explore_thread`, idempotent
   - **Step C:** `POST /api/research/content/threads` with `{ticker, is_panel: true}` — `get_or_create_panel_thread`, idempotent
   - **Step D:** `GET /api/research/content/threads?ticker=VALE` — load all threads (explore + panel + named)
   - **Step E:** For each thread: `GET /api/research/content/messages?thread_id=N&limit=50`
   - **Step F:** Call `researchStore.hydrate({ file, exploreThreadId, panelThreadId, threads, messagesByThread })`
   - Steps B+C can run in parallel. Steps D+E run after B+C complete. Step F runs last.
3. If no ticker → show `ResearchListView`
4. Clicking a file in `ResearchListView` sets `navigationContext({ ticker })` + `setActiveView('research')`, which triggers bootstrap

**Tier gate:**
```typescript
const { user } = useAuth();
if (user?.tier !== 'paid' && user?.tier !== 'business') {
  return <UpgradeSurface ticker={pendingTicker} />;
}
```
The `pendingTicker` is preserved from the deep link so the upgrade surface can say "Upgrade to research VALE".

**New files:**
1. `ResearchWorkspaceContainer.tsx` — bootstrap + tier gate + routing
2. `ResearchListView.tsx` — file list + create
3. `ResearchWorkspace.tsx` — two-pane layout with ResizablePanelGroup
4. `ResearchTabBar.tsx` — IDE-style tab bar
5. `ExploreTab.tsx` — explore conversation feed
6. `ThreadTab.tsx` — thread with pinned finding
7. `AgentPanel.tsx` — right panel with header + conversation + input
8. `ConversationFeed.tsx` — shared message renderer (two-author rail distinction)
9. `MessageInput.tsx` — shared input, disabled during streaming
10. `ResearchFileCard.tsx` — card for list view
11. `UpgradeSurface.tsx` — paid-tier gate

**Reused components:**
- `ResizablePanelGroup/ResizablePanel/ResizableHandle` from `components/ui/resizable.tsx`
- `MarkdownRenderer` from chat components (agent message rendering)
- shadcn/ui primitives (Button, Input, Badge, ScrollArea)
- `DashboardErrorBoundary` from shared components

**Styling per spec:**
- Tab bar: Geist Mono 11px, letter-spacing 0.04em. Active: `--text` + 2px bottom border `--accent`. Inactive: `--text-muted`.
- Agent messages: 13px Instrument Sans, `--ink`, 1px `--accent` left rail
- User messages: 13px Instrument Sans, `--text`, 1px `--text-dim` left rail
- Agent panel header: uppercase, 10px Geist Mono
- Two-author flat hierarchy (both 13px, different rail colors)

---

## Step 9: React Query Hooks

**New file:** `frontend/packages/connectors/src/features/external/hooks/useResearchFiles.ts`

```typescript
export function useResearchFiles(filters?: { stage?: string }) {
  return useQuery({
    queryKey: ['research-files', filters],
    queryFn: () => fetch('/api/research/files?' + params).then(r => r.json()),
  });
}

export function useCreateResearchFile() {
  return useMutation({
    mutationFn: (data: { ticker: string; company_name?: string }) => ...,
    onSuccess: () => queryClient.invalidateQueries(['research-files']),
  });
}

export function useUpdateResearchFile() { ... }
export function useDeleteResearchFile() { ... }
```

**New file:** `frontend/packages/connectors/src/features/external/hooks/useResearchContent.ts`

> **[Fix for Finding 5]** Hooks for thread/message loading (hydration).

```typescript
export function useResearchThreads(ticker: string) {
  return useQuery({
    queryKey: ['research-threads', ticker],
    queryFn: () => fetch(`/api/research/content/threads?ticker=${ticker}`).then(r => r.json()),
    enabled: !!ticker,
  });
}

export function useResearchMessages(threadId: number | null) {
  return useQuery({
    queryKey: ['research-messages', threadId],
    queryFn: () => fetch(`/api/research/content/messages?thread_id=${threadId}&limit=50`).then(r => r.json()),
    enabled: threadId !== null,
  });
}

export function useResearchBootstrap(ticker: string) {
  // Orchestrates: create/get file → load threads → load messages → hydrate store
  // Returns { isLoading, error }
}
```

---

## Step 10: Integration Wiring

1. **ResearchContainer.tsx** at existing path re-exports from `components/research/ResearchWorkspaceContainer` — no change needed in `ModernDashboardApp.tsx`
2. Wire navigation: sidebar "Research" link → `setActiveView('research')` → hash sync → `#research`
3. Wire deep links: `#research/VALE` → `parseHash` returns context → `setNavigationContext({ ticker: 'VALE' })` → `ResearchWorkspaceContainer` reads context → bootstrap flow
4. Wire exit ramp: from StockLookupContainer "Open Research →" button → `setActiveView('research')` + `setNavigationContext({ ticker })`

---

## Authority Model (Fix for New Finding 3)

**In Phase 1, the user is the sole writer of conviction and stage.** The agent may suggest changes via message content (e.g., "Based on the ownership data, this might warrant upgrading conviction to 4") but NEVER writes to `research_files.conviction` or `research_files.stage` directly.

- `PATCH /api/research/files/{id}` is only called from UI actions (user clicks a stage/conviction control)
- The agent's system prompt includes an instruction: "You may suggest stage or conviction changes, but you cannot change them. The user decides."
- In later phases, the agent can propose changes via `proposed_stage`/`proposed_conviction` in message metadata, surfaced as actionable suggestions in the UI

---

## Scope Boundaries — NOT in Phase 1

- Document tabs (filing reading, transcripts) — Phase 2
- Agent document highlights / user annotations — Phase 2
- Diligence checklist — Phase 3
- Report generation — Phase 4
- Exit ramps to scenario tools — Phase 4
- Opening take synthesis — Phase 3
- Web search — Phase 5
- Multi-ticker theme research — Phase 5
- Bidirectional ai-excel-addin memory sync — Phase 5
- Per-thread gateway sessions (if bleed becomes an issue) — Phase 2

---

## Dependencies & Parallelization

```
Batch 1 (parallel, no deps):
  Step 1: Postgres migration
  Step 3: SQLite tables + methods (ai-excel-addin)
  Step 5: researchStore (Zustand)

Batch 2 (depends on Batch 1):
  Step 2: REST CRUD (needs Step 1)
  Step 4a: Context enricher (needs Step 2)
  Step 4c: Research content proxy + ai-excel-addin endpoints (needs Step 3)
  Step 7: Hash routing (needs Step 5)

Batch 3 (depends on Batch 2):
  Step 4b: System prompt injection + research_context.py (needs Steps 3, 4a)
  Step 4d: Server-side message persistence (needs Steps 3, 4b)
  Step 6: useResearchChat + ResearchStreamManager + GatewayClaudeService extension (needs Steps 4a, 5)
  Step 9: React Query hooks — files + content (needs Steps 2, 4c)

Batch 4 (depends on Batch 3):
  Step 8: Component tree (needs Steps 5, 6, 7, 9)

Batch 5:
  Step 10: Integration wiring (needs Step 8)
```

---

## Verification

1. **Backend (risk_module)**: `pytest` — research_files CRUD (create, list, filter, update, delete, auth/tier, unique constraint on duplicate ticker)
2. **Backend (risk_module)**: Test context enricher injects `research_file` when `purpose=research`, passes through when not research
3. **Backend (risk_module)**: Test research content proxy forwards requests with auth to ai-excel-addin
4. **ai-excel-addin**: `pytest` — research_threads/messages CRUD on AnalystMemoryStore (user_key isolation, explore/panel uniqueness, message ordering)
5. **ai-excel-addin**: Test `build_research_context()` returns formatted prompt block with thread summaries + messages
6. **ai-excel-addin**: Test server-side message persistence (user message saved before turn, agent message saved after)
7. **Frontend**: Component tests for ResearchTabBar, ConversationFeed, MessageInput, UpgradeSurface
8. **Frontend**: Test `ResearchStreamManager` abort behavior (abort previous stream on new send, input disable)
9. **Frontend**: Test `useResearchBootstrap` hydration flow
10. **E2E**: `#research/VALE` → tier gate → two-pane layout → type in Explore → agent responds (message persisted server-side) → "Start thread" → thread tab opens → switch tabs → panel shows context → close tab, reopen → messages restored from server

---

## Cross-Repo Change Summary

| Repo | Changes |
|------|---------|
| **risk_module** | Migration, REST router, context enricher, research content proxy, frontend (store, hooks, stream manager, 11 components, GatewayClaudeService extension, hash routing) |
| **ai-excel-addin** | SQLite tables + methods (user_key scoped), research REST endpoints, `build_research_context()`, system prompt extension, server-side message persistence hooks |
