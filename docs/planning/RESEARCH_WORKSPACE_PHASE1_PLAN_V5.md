# Research Workspace — Phase 1 Implementation Plan (v5)

**Status:** DRAFT — supersedes `RESEARCH_WORKSPACE_PHASE1_PLAN.md` v4 (commit `7b4c8a76`)
**Date:** 2026-04-11
**Anchor:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md` (the locked system frame)
**Decisions:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` (the 7 locked decisions)
**Product spec:** `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md`

**Codex review history:**
- v4 plan: 5 review rounds, all findings addressed (committed `7b4c8a76`)
- Pivot 2 override: thread `019d792b` (per-user SQLite cohabitation)
- Per-user SQLite follow-up: thread `019d7935`
- Decisions 3/5/6/7 bundle: thread `019d794e`
- Architecture + decisions coherence review: thread `019d7d6a` (2 rounds, all 4 structural gaps closed)
- v5 review: pending

**What v5 supersedes in v4:**
- v4 Step 1 (Postgres migration `research_files`) → **DELETED**. Per Decision 1: research state lives in per-user SQLite at `data/users/{user_id}/research.db`, NOT Postgres.
- v4 Step 2 (`routes/research.py` Postgres CRUD) → **DELETED**. Replaced by thin proxy to ai-excel-addin.
- v4 Step 4a (gateway context enricher) → **DELETED**. Agent reads research state directly from per-user `research.db` via `ResearchRepository` at prompt-build time; no enricher needed.
- v4 "lightweight metadata sync between Postgres research_files and agent memories" → **DELETED**. Single store; no sync mechanism.
- v4 Step 3 (SQLite tables in shared `analyst_memory.db`) → **MODIFIED**. Tables now live in per-user `research.db`, scoped by `research_file_id` instead of `user_key`, with `label` column on `research_files` for multi-thesis disambiguation.
- v4 Step 4b (system prompt injection) → **MODIFIED**. Now routed through Research-Mode Policy Layer.
- v4 Step 4c (research content proxy) → **MODIFIED**. Now covers metadata CRUD too; simplified.
- v4 Step 4d (server-side message persistence) → **MODIFIED**. Writes via `ResearchRepository`; "commit before first SSE yield" ordering rule.
- v4 Steps 5-10 (frontend: researchStore, useResearchChat, stream manager, hash routing, components, hooks, integration) → **PRESERVED** with file_id/policy-layer adaptations.

---

## What Phase 1 Delivers

- **Research file CRUD** — create, list, filter by stage, update metadata, delete. Multi-thesis support via `label` column (first file on a ticker has `label=''`, subsequent files require a label, e.g., "long thesis" vs "pre-earnings").
- **Two-pane workspace** — reader (main) + agent panel (280px right), inspired by Cursor IDE. Resizable via `ResizablePanelGroup`.
- **IDE-style tabs at top of reader** — Explore tab (always open, not closeable) + named thread tabs (created from conversation, closeable).
- **Explore tab with streaming conversation** — free-form exploration; messages persisted server-side during turn processing.
- **Agent panel with tab-aware context** — when user sends from panel while reader is on a different tab, panel sees the reader's active thread via `tab_context`.
- **Thread creation** — "Start thread →" action from a conversation pivot creates a named thread; opens as a new reader tab.
- **Thread resumption on return** — bootstrap hydration loads all existing threads + last 50 messages per thread.
- **Deep links** — `#research/VALE` (default file) and `#research/VALE:long-thesis` (labeled file) with proper hash → state hydration.
- **Paid-tier gate** — `UpgradeSurface` component when user tier is not `paid`/`business`; deep link preserved for upgrade CTA context.
- **User is sole authority on stage/conviction** — agent suggests changes via message metadata (`proposed_stage`, `proposed_conviction`), never writes directly to `research_files`.
- **Per-user-everything migration** — existing `analyst_memory.db` + `workspace/tickers/*.md` migrate from shared `api/memory/` paths to per-user `data/users/{user_id}/` paths. All ai-excel-addin state becomes per-user by physical isolation. The research agent retains full access to memory tools + `run_agent` + sub-agents on research turns because cross-user contamination is impossible under this model.
- **Research-Mode Policy Layer** provides research-specific prompt stack + file context injection (NO tool restrictions — agent has full tool surface).
- **Commit-before-first-SSE-yield persistence** — user message saved before any agent bytes stream to the client; save failure rejects the turn before stream starts.

**NOT in Phase 1:**
- Document tabs (filings, transcripts, investor decks) — Phase 2
- Agent document highlights / user annotations — Phase 2
- Diligence checklist + qualitative factors — Phase 3
- Research handoff artifact + model build integration — Phase 4
- Report export to PDF/markdown — Phase 5
- Web search integration — Phase 5
- Multi-ticker theme research — Phase 5
- Bidirectional sync with existing EAV ticker memory — Phase 5 (if ever)
- Per-thread gateway sessions for conversational isolation — deferred to Phase 2+ if bleed observed

---

## Architecture Anchor

This plan realizes the following sections from `RESEARCH_WORKSPACE_ARCHITECTURE.md`:

- **Section 2 (System Topology)** — research layer, policy layer, repository abstraction
- **Section 3 (Storage Topology)** — per-user `research.db`, file-scoped content tables
- **Section 4 (Cross-Repo Boundaries)** — risk_module proxy + ai-excel-addin research layer
- **Section 5 Flows 1-3** — load file list, bootstrap, send message (Flows 4-5 are Phase 2/4)
- **Section 6 (Agent Context Flow)** — policy layer + `build_research_context`
- **Section 7 Invariants 1-5, 11, 12, 14, 15** — all enforced in Phase 1

**Invariants Phase 1 must uphold:**

| Invariant | Enforcement in Phase 1 |
|---|---|
| 1 — Per-user isolation is physical | `ResearchRepository` opens per-user file; no cross-user queries possible |
| 2 — Research agent has full tool access (memory, sub-agents) | Per-user physical isolation (Step 0 migration) — NO tool denylist needed; per-user directories eliminate contamination |
| 3 — User_id always proxy-injected | `routes/research_content.py` extracts from session; gateway strict mode validates |
| 4 — Tier gating at proxy | `create_tier_dependency(minimum_tier="paid")` on proxy routes |
| 5 — User message persisted before first SSE yield | Runtime hook in Step 3 commits user message before stream starts |
| 11 — User sole authority on stage/conviction | PATCH endpoints only invoked from UI; agent writes via message metadata only |
| 12 — Connection-per-request | `ResearchRepository` open → use → close pattern in Step 1 |
| 14 — Finalization never blocked (Phase 3+) | N/A in Phase 1 (no finalization) |
| 15 — Content scoped by research_file_id | All tables and API endpoints use file_id; Step 1 schema enforces |

Invariants 6-10, 13 (filing immutability, char offsets, handoff contract, model_build unchanged, recalc advisory, qualitative factors extensible) are Phase 2/3/4 concerns.

---

## Step 0 — Memory Layer Per-User Migration

**Owner:** ai-excel-addin
**Extended files:**
- `api/memory/store.py` — `AnalystMemoryStore` accepts `db_path` arg; `MemoryStoreFactory` resolves `user_id → path`
- `api/memory/markdown_sync.py` — per-user workspace directory paths
- `api/memory/ingest.py` + 9 screener connectors — pass `user_id` through ingest chain
- Runtime memory injection (`api/agent/shared/system_prompt.py`) — uses per-user store

**One-time data migration:**
- Move `api/memory/analyst_memory.db` → `data/users/{first_user_id}/analyst_memory.db`
- Move `api/memory/workspace/tickers/*.md` → `data/users/{first_user_id}/workspace/tickers/*.md`
- For the sole current user (henrychien), this is a file move + config update. No data transformation.
- New users get empty stores on first memory write (lazy creation, same pattern as `ResearchRepository._maybe_migrate`).

### `MemoryStoreFactory`

```python
# Same factory pattern as ResearchRepositoryFactory

class MemoryStoreFactory:
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir

    def get(self, user_id: int) -> AnalystMemoryStore:
        db_path = self._base_dir / "users" / str(user_id) / "analyst_memory.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return AnalystMemoryStore(db_path=str(db_path))
```

### `AnalystMemoryStore` extension

Add optional `db_path` parameter to `__init__` (default to None for backward compat during migration). When provided, use it instead of the hardcoded path. All existing methods unchanged; only path resolution is per-user.

### Markdown sync path update

`markdown_sync.py` currently writes to `api/memory/workspace/tickers/{TICKER}.md`. Change to resolve per-user: `data/users/{user_id}/workspace/tickers/{TICKER}.md`. The `user_id` flows from the chat runtime context through to the sync hooks.

### Connector updates (9 touch points)

Each screener connector in `api/memory/connectors/` calls `memory_store.store_memory(...)`. The `memory_store` instance must now come from `MemoryStoreFactory.get(user_id)` instead of the global singleton. The user_id flows from the ingestion trigger (usually the chat runtime or a scheduled job) through to the connector.

Connectors: `estimate_revisions`, `insider_buying`, `ownership`, `biotech_catalyst`, `special_situations`, `quality_screen`, `fingerprint_screen`, `oi_analysis`, `newsletter`.

### Runtime integration

`get_memory_store()` call sites in the runtime (`system_prompt.py`, `tool_catalog.py`, tool handlers) must accept and pass `user_id`. The gateway strict-mode `user_id` (already available in the chat context) is the trusted value.

### Tests

- `test_memory_factory_per_user` — two users create independent DBs; user A's memories not visible to user B
- `test_memory_migration_path` — opening a per-user store at a new path creates the DB + runs migrations
- `test_markdown_sync_per_user` — sync writes to per-user directory, not shared
- `test_connector_user_routing` — connector writes to authenticated user's store (mock factory, verify path)

---

## Step 1 — `ResearchRepository` + Per-User SQLite Schema

**Owner:** ai-excel-addin
**New files:**
- `api/research/__init__.py`
- `api/research/repository.py`
- `api/research/migrations.py`

**`api/memory/store.py` is EXTENDED in Step 0** (memory per-user migration) — see Step 0 below. `AnalystMemoryStore` accepts a `db_path` argument and is accessed via `MemoryStoreFactory(user_id)`.

### Schema

Stored in per-user file at `data/users/{user_id}/research.db`. Tables created lazily on first open via `_maybe_migrate()`.

```sql
CREATE TABLE IF NOT EXISTS research_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  company_name TEXT,
  stage TEXT NOT NULL DEFAULT 'exploring',
  direction TEXT,
  strategy TEXT,
  conviction INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(ticker, label)
);

CREATE TABLE IF NOT EXISTS research_threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_file_id INTEGER NOT NULL REFERENCES research_files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  finding_summary TEXT,
  is_explore INTEGER NOT NULL DEFAULT 0,
  is_panel INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_file ON research_threads(research_file_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_threads_explore
  ON research_threads(research_file_id) WHERE is_explore = 1;
CREATE UNIQUE INDEX IF NOT EXISTS idx_threads_panel
  ON research_threads(research_file_id) WHERE is_panel = 1;

CREATE TABLE IF NOT EXISTS research_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES research_threads(id) ON DELETE CASCADE,
  author TEXT NOT NULL CHECK (author IN ('user','agent','system')),
  content TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'message'
    CHECK (content_type IN ('message','note','tool_call','artifact','pending_error')),
  tab_context INTEGER,
  metadata TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread
  ON research_messages(thread_id, created_at);

-- Stubbed tables for Phase 2/4 prep (created now; unused in Phase 1)
CREATE TABLE IF NOT EXISTS annotations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_file_id INTEGER NOT NULL REFERENCES research_files(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  section_header TEXT,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  selected_text TEXT NOT NULL,
  note TEXT,
  author TEXT NOT NULL,
  diligence_ref TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_annotations_file_source
  ON annotations(research_file_id, source_type, source_id);

CREATE TABLE IF NOT EXISTS research_handoffs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_file_id INTEGER NOT NULL REFERENCES research_files(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft',
  artifact TEXT NOT NULL,
  created_at REAL NOT NULL,
  finalized_at REAL
);
CREATE INDEX IF NOT EXISTS idx_handoffs_file
  ON research_handoffs(research_file_id, version DESC);

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);
```

**Rationale for stubbing Phase 2/4 tables now:** creating the empty tables in Phase 1 means schema migrations only run once per user. Phase 2/4 add indexes or columns but don't re-bootstrap the file. Alternative — create them in Phase 2/4 — is fine but adds complexity.

### ResearchRepository class

```python
# api/research/repository.py

import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

CURRENT_SCHEMA_VERSION = 1

class ResearchRepository:
    """Per-user SQLite facade for research workspace state.

    Instances are short-lived — one per operation. Do not cache connections
    across requests by default; see Invariant 12 in architecture doc.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path

    @contextmanager
    def _conn(self):
        """Open → apply PRAGMAs → yield → close. Connection-per-request."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA journal_mode = WAL")  # persistent, but safe to re-apply
            self._maybe_migrate(conn)
            yield conn
        finally:
            conn.close()

    def _maybe_migrate(self, conn: sqlite3.Connection) -> None:
        """Idempotent schema migrations. Run on every connection open.
        Must be tested thoroughly — production state = many DBs at mixed versions."""
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if row is None:
            # Fresh DB — run all creates
            conn.executescript(CREATE_ALL_SQL)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)",
                         (CURRENT_SCHEMA_VERSION,))
            return
        current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        # Phase 1 ships with version 1; future migrations add UP steps here.
        if current < CURRENT_SCHEMA_VERSION:
            # (future) run migration SQL up to CURRENT_SCHEMA_VERSION
            pass

    # ---- research_files ----

    def upsert_file(self, ticker: str, label: str = "",
                    company_name: Optional[str] = None) -> dict:
        """Create-or-get. Returns full file row."""
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO research_files (ticker, label, company_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (ticker, label) DO UPDATE
                     SET company_name = COALESCE(excluded.company_name, research_files.company_name),
                         updated_at = excluded.updated_at""",
                (ticker, label, company_name, now, now)
            )
            return dict(conn.execute(
                "SELECT * FROM research_files WHERE ticker=? AND label=?",
                (ticker, label)
            ).fetchone())

    def get_file(self, research_file_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM research_files WHERE id=?", (research_file_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_files(self, stage: Optional[str] = None) -> list[dict]:
        with self._conn() as conn:
            if stage:
                rows = conn.execute(
                    "SELECT * FROM research_files WHERE stage=? ORDER BY updated_at DESC",
                    (stage,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_files ORDER BY updated_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def update_file(self, research_file_id: int, **fields) -> Optional[dict]:
        """Update stage, conviction, direction, strategy, label, company_name.
        User-driven only — agent never calls this directly (Invariant 11)."""
        allowed = {"stage", "conviction", "direction", "strategy", "label", "company_name"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_file(research_file_id)
        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        params = list(updates.values()) + [research_file_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE research_files SET {set_clause} WHERE id=?", params)
            row = conn.execute(
                "SELECT * FROM research_files WHERE id=?", (research_file_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_file(self, research_file_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM research_files WHERE id=?", (research_file_id,))
            return cur.rowcount > 0

    # ---- research_threads ----

    def get_or_create_explore_thread(self, research_file_id: int) -> int:
        return self._get_or_create_reserved_thread(
            research_file_id, name="Explore", is_explore=True
        )

    def get_or_create_panel_thread(self, research_file_id: int) -> int:
        return self._get_or_create_reserved_thread(
            research_file_id, name="Panel", is_panel=True
        )

    def _get_or_create_reserved_thread(self, research_file_id: int, name: str,
                                        is_explore: bool = False,
                                        is_panel: bool = False) -> int:
        now = time.time()
        flag_col = "is_explore" if is_explore else "is_panel"
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT id FROM research_threads WHERE research_file_id=? AND {flag_col}=1",
                (research_file_id,)
            ).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                """INSERT INTO research_threads
                   (research_file_id, name, is_explore, is_panel, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (research_file_id, name, int(is_explore), int(is_panel), now, now)
            )
            return cur.lastrowid

    def create_thread(self, research_file_id: int, name: str) -> dict:
        """Create a named (non-reserved) thread. For 'Start thread →' action."""
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO research_threads
                   (research_file_id, name, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (research_file_id, name, now, now)
            )
            row = conn.execute(
                "SELECT * FROM research_threads WHERE id=?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def list_threads_for_file(self, research_file_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM research_threads WHERE research_file_id=?
                   ORDER BY is_explore DESC, is_panel DESC, created_at ASC""",
                (research_file_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def update_thread_finding(self, thread_id: int, finding_summary: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE research_threads SET finding_summary=?, updated_at=? WHERE id=?",
                (finding_summary, time.time(), thread_id)
            )

    # ---- research_messages ----

    def save_message(self, thread_id: int, author: str, content: str,
                     content_type: str = "message", tab_context: Optional[int] = None,
                     metadata: Optional[str] = None) -> int:
        """Persist a message. MUST be called synchronously BEFORE any SSE bytes
        are yielded to the client for user messages (Invariant 5)."""
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO research_messages
                   (thread_id, author, content, content_type, tab_context, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (thread_id, author, content, content_type, tab_context, metadata, now)
            )
            # Also bump thread updated_at so listing reflects recency
            conn.execute(
                "UPDATE research_threads SET updated_at=? WHERE id=?",
                (now, thread_id)
            )
            return cur.lastrowid

    def list_messages(self, thread_id: int, limit: int = 50,
                      before_id: Optional[int] = None) -> list[dict]:
        with self._conn() as conn:
            if before_id:
                rows = conn.execute(
                    """SELECT * FROM research_messages
                       WHERE thread_id=? AND id < ?
                       ORDER BY id DESC LIMIT ?""",
                    (thread_id, before_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM research_messages
                       WHERE thread_id=?
                       ORDER BY id DESC LIMIT ?""",
                    (thread_id, limit)
                ).fetchall()
            return [dict(r) for r in reversed(rows)]  # return chronological

    def thread_belongs_to_file(self, thread_id: int, research_file_id: int) -> bool:
        """Guard for message list endpoint — caller must prove file scope."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM research_threads WHERE id=? AND research_file_id=?",
                (thread_id, research_file_id)
            ).fetchone()
            return row is not None


class ResearchRepositoryFactory:
    """Resolves user_id → per-user file path → ResearchRepository instance.

    Does NOT cache connections. Creates a new repository per request;
    each repository creates a new connection per operation.
    """

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir

    def get(self, user_id: int) -> ResearchRepository:
        db_path = self._base_dir / "users" / str(user_id) / "research.db"
        return ResearchRepository(db_path)
```

### Configuration

- `base_dir` defaults to `os.environ.get("RESEARCH_WORKSPACE_DATA_DIR", "data")`
- Per-user paths resolved as `{base_dir}/users/{user_id}/research.db`
- Ensures parent directory exists before opening file (`mkdir parents=True`)

### Tests

- `test_repository_schema.py` — fresh DB creates all tables + indexes; `_maybe_migrate` is idempotent (run 3x, no errors)
- `test_repository_files.py` — `upsert_file` insert + upsert-on-conflict returns same row; `UNIQUE(ticker, label)` enforced; label='' allowed once per ticker; `list_files` filters by stage
- `test_repository_threads.py` — `get_or_create_explore_thread` idempotent (returns same id on repeat calls); `get_or_create_panel_thread` same; partial unique indexes enforce one-explore-one-panel per file; two files on same ticker can each have their own explore + panel (no cross-file collision)
- `test_repository_messages.py` — `save_message` inserts + bumps thread `updated_at`; `list_messages` returns chronological order; `before_id` pagination works
- `test_repository_isolation.py` — two users have independent DBs; creating files as user A does not affect user B's file list (physical isolation test)
- `test_repository_migration.py` — opening an existing DB from a prior schema version runs migrations cleanly without data loss

---

## Step 2 — Research-Mode Policy Layer (Prompt Routing Only)

**Owner:** ai-excel-addin
**New file:**
- `api/research/policy.py`

**Extended files:**
- `api/agent/shared/system_prompt.py`
- `api/agent/interactive/runtime.py`

The policy layer routes research turns to a research-specific prompt stack + file context block. It does NOT restrict tool access — the per-user-everything migration (Step 0) eliminates the contamination concern that would otherwise require a denylist. The agent retains full access to `memory_*`, `run_agent`, and all other tools.

### `api/research/policy.py`

```python
"""Research-Mode Policy Layer (prompt routing only).

Routes research workspace turns to a research-specific prompt stack that
injects the file context block. Does NOT restrict tool access — all
ai-excel-addin state is per-user by physical isolation (Invariant 1),
so memory tools and sub-agents are safe to use on research turns.
"""

from typing import Any

RESEARCH_WORKSPACE_PURPOSE = "research_workspace"


def is_research_workspace(context: dict[str, Any]) -> bool:
    return context.get("purpose") == RESEARCH_WORKSPACE_PURPOSE


def build_research_prompt_stack(context: dict[str, Any]) -> list[dict]:
    """Assemble system prompt blocks for a research workspace turn.

    Includes the generic memory guidance (agent has full memory access)
    PLUS the research file context block.
    """
    from api.research.context import build_research_context

    blocks = [
        _BASE_RESEARCH_SYSTEM_BLOCK,
        _RESEARCH_WORKSPACE_INSTRUCTIONS_BLOCK,
    ]

    research_block = build_research_context(
        user_id=context["user_id"],
        research_file_id=context["research_file_id"],
        thread_id=context.get("thread_id"),
        tab_context=context.get("tab_context"),
    )
    if research_block:
        blocks.append({"type": "system", "content": research_block})

    return blocks


_BASE_RESEARCH_SYSTEM_BLOCK = {
    "type": "system",
    "content": (
        "You are a collaborative equity research assistant working with the "
        "analyst inside the research workspace. Your role is co-pilot: you pull "
        "data, surface context, and synthesize on demand, but you do not act "
        "unilaterally. The analyst is the sole authority on thesis, conviction, "
        "and stage — you may suggest changes via message content, but you cannot "
        "write them directly."
    )
}

_RESEARCH_WORKSPACE_INSTRUCTIONS_BLOCK = {
    "type": "system",
    "content": (
        "You have access to all tools: memory (for general ticker observations "
        "across sessions), model_build, edgar, fmp, langextract, portfolio-mcp, "
        "sheetsfinance, and sub-agents via run_agent. Use memory tools for "
        "cross-session ticker knowledge that isn't specific to this research file. "
        "Workspace-specific state (thesis, stage, conviction, diligence on THIS "
        "file) is managed by the research workspace UI and flows to you "
        "automatically via the research context block below."
    )
}
```

### `api/agent/shared/system_prompt.py` extension

```python
from api.research.policy import is_research_workspace, build_research_prompt_stack

def build_system_prompt_blocks(context):
    if is_research_workspace(context):
        return build_research_prompt_stack(context)
    # ... existing generic path (unchanged)
```

**No changes to `tool_catalog.py` or `tool_handlers.py`** — research turns use the same full tool catalog + local handlers as all other turns. The agent has its complete natural capability surface.

### Tests (2 for policy layer)

- `test_policy_prompt_stack.py` — `build_research_prompt_stack` includes the file context block with ticker, stage, direction, thread list, and recent messages; is distinct from the generic prompt stack
- `test_policy_predicate.py` — `is_research_workspace` returns True for `purpose='research_workspace'`, False for `purpose='research'` (different product), False for no purpose
- `test_policy_full_catalog_available.py` — research turns' tool catalog includes memory_* tools and run_agent (no regression — confirm full catalog is preserved)

---

## Step 3 — `build_research_context` + Chat Runtime Integration

**Owner:** ai-excel-addin
**New file:**
- `api/research/context.py`

**Extended file:**
- `api/agent/interactive/runtime.py`

### `api/research/context.py`

```python
"""Research context prompt block assembly.

Called from api/research/policy.py::build_research_prompt_stack().
Queries the per-user research.db via ResearchRepository at prompt-build time.
"""

from typing import Optional
from api.research.repository import ResearchRepositoryFactory

# Injected by app startup
_repo_factory: Optional[ResearchRepositoryFactory] = None


def set_repository_factory(factory: ResearchRepositoryFactory) -> None:
    global _repo_factory
    _repo_factory = factory


def build_research_context(
    user_id: int,
    research_file_id: int,
    thread_id: Optional[int] = None,
    tab_context: Optional[int] = None,
) -> Optional[str]:
    """Build a research context prompt block for the current turn.

    Args:
        user_id: trusted from proxy
        research_file_id: identity for this workspace session (NOT ticker)
        thread_id: the thread the user is sending to
        tab_context: numeric thread_id of the reader's active tab
                     (may differ from thread_id if sending from panel)

    Returns:
        Formatted text block for system prompt, or None if file not found.
    """
    if _repo_factory is None:
        return None

    repo = _repo_factory.get(user_id)
    file = repo.get_file(research_file_id)
    if not file:
        return None

    threads = repo.list_threads_for_file(research_file_id)

    active_messages = []
    if thread_id:
        active_messages = repo.list_messages(thread_id, limit=20)

    reader_messages = []
    if tab_context and tab_context != thread_id:
        reader_messages = repo.list_messages(tab_context, limit=10)

    return _format(file, threads, active_messages, reader_messages)


def _format(file: dict, threads: list[dict], active_messages: list[dict],
            reader_messages: list[dict]) -> str:
    label_suffix = f" — {file['label']}" if file.get("label") else ""
    header = (
        f"RESEARCH WORKSPACE CONTEXT\n"
        f"File: {file['ticker']}{label_suffix}"
        f" ({file.get('company_name') or 'unknown company'})\n"
        f"Stage: {file['stage']}"
    )
    if file.get("direction"):
        header += f" · Direction: {file['direction']}"
    if file.get("strategy"):
        header += f" · Strategy: {file['strategy']}"
    if file.get("conviction"):
        header += f" · Conviction: {file['conviction']}/5"

    thread_lines = []
    for t in threads:
        marker = " [active]" if t["id"] == (active_messages and active_messages[0]["thread_id"]) else ""
        finding = f" — {t['finding_summary']}" if t.get("finding_summary") else ""
        thread_lines.append(f"  · {t['name']}{marker}{finding}")

    lines = [header, "", "Threads in this file:"] + thread_lines

    if active_messages:
        lines += ["", "Recent messages on active thread:"]
        for m in active_messages[-20:]:
            author = m["author"]
            content = m["content"][:200] + ("..." if len(m["content"]) > 200 else "")
            lines.append(f"  [{author}] {content}")

    if reader_messages:
        lines += ["", "Reader tab context (user is reading but messaging you from panel):"]
        for m in reader_messages[-10:]:
            author = m["author"]
            content = m["content"][:150] + ("..." if len(m["content"]) > 150 else "")
            lines.append(f"  [{author}] {content}")

    return "\n".join(lines)
```

### Chat Runtime Integration — Server-Side Message Persistence

The critical Phase 1 ordering rule: **user messages MUST be committed to disk BEFORE any SSE bytes are yielded to the client**. This implements Invariant 5's honest failure semantics.

**Extension to `api/agent/interactive/runtime.py`:**

At the request handler entry point, before the runner starts streaming, check if the turn is research and add pre-turn + post-turn hooks:

```python
from api.research.policy import is_research_workspace
from api.research.repository import ResearchRepositoryFactory

async def handle_chat_request(request, context):
    # ... existing setup

    research_context = None
    if is_research_workspace(context):
        research_context = _prepare_research_context(request, context)
        # [CRITICAL] Commit user message to disk BEFORE starting the stream
        try:
            research_context["repo"].save_message(
                thread_id=context["thread_id"],
                author="user",
                content=_extract_last_user_message(request.messages),
                content_type="message",
                tab_context=context.get("tab_context"),
            )
        except Exception as e:
            # Reject turn before first SSE yield. Return 500 to client.
            raise RuntimeError(f"research persistence failed: {e}") from e

    # ... existing streaming path

    async for chunk in run_agent(request, context):
        yield chunk

    # [POST-STREAM] Save agent message after stream completes successfully
    if research_context and research_context.get("agent_buffer"):
        try:
            research_context["repo"].save_message(
                thread_id=context["thread_id"],
                author="agent",
                content=research_context["agent_buffer"],
                content_type="message",
                metadata=research_context.get("metadata_json"),
            )
        except Exception:
            # Agent message LOST server-side. Client has streamed content in
            # memory but it's not durable. User reload will show only user
            # message. Accept per Invariant 5 Phase 1.
            logger.error("research agent message persistence failed")


def _prepare_research_context(request, context):
    from api.research.repository import ResearchRepositoryFactory
    factory = get_research_repo_factory()  # module singleton
    return {
        "repo": factory.get(context["user_id"]),
        "agent_buffer": "",  # accumulates chunks for post-stream save
        "metadata_json": None,
    }
```

**Agent chunk accumulation:** the streaming loop must accumulate assistant response chunks into `research_context["agent_buffer"]` so the post-stream save has the complete content. Existing runtime patterns may already do this for logging; if so, reuse. Otherwise, tap the chunk stream with a side-effect accumulator.

**Client disconnect behavior:** the gateway cancels the runner on client disconnect. This is the existing behavior at `packages/agent-gateway/agent_gateway/server.py:621`. When cancellation fires, the post-stream save code never runs, so the agent message is lost. User message is still persisted (Step 3 ordering guarantees). Client reload shows user message only. This matches Invariant 5 Phase 1 semantics.

### Tests

- `test_build_research_context_basic` — mock repo returns file + threads + messages; assert output contains ticker, stage, direction, thread names, and recent messages in chronological order
- `test_build_research_context_missing_file` — mock repo returns None for file; assert result is None (not a crash)
- `test_build_research_context_panel_tab` — when `tab_context != thread_id`, reader messages are included; when equal, only active messages shown
- `test_build_research_context_no_memory_guidance` — ensure output string does NOT contain "memory_read" or "memory_recall" (defense vs accidental reinclusion)
- `test_runtime_pre_turn_persistence` — mock repo.save_message raises; assert handler raises before any SSE yield happens (use in-memory async stream collector)
- `test_runtime_post_turn_persistence` — simulate full successful stream; assert agent message saved with accumulated content
- `test_runtime_disconnect_loss` — simulate runner cancellation mid-stream; assert user message persisted, agent message NOT persisted

---

## Step 4 — Research REST Endpoints (ai-excel-addin)

**Owner:** ai-excel-addin
**New file:**
- `api/research/routes.py`

Registered in `api/main.py` or equivalent FastAPI app startup.

### Endpoints

```python
# api/research/routes.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from api.research.repository import ResearchRepositoryFactory

router = APIRouter(prefix="/api/research", tags=["research"])

# User_id is trusted (proxy-injected via gateway); see Invariant 3.
# This dependency extracts it from the incoming gateway context.
def get_trusted_user_id(...) -> int: ...


class UpsertFileBody(BaseModel):
    ticker: str
    label: str = ""
    company_name: Optional[str] = None


class PatchFileBody(BaseModel):
    stage: Optional[str] = None
    conviction: Optional[int] = None
    direction: Optional[str] = None
    strategy: Optional[str] = None
    label: Optional[str] = None
    company_name: Optional[str] = None


class CreateThreadBody(BaseModel):
    research_file_id: int
    name: Optional[str] = None
    is_explore: bool = False
    is_panel: bool = False


@router.get("/files")
def list_files(stage: Optional[str] = None,
               user_id: int = Depends(get_trusted_user_id)):
    repo = get_repo_factory().get(user_id)
    return {"files": repo.list_files(stage=stage)}


@router.post("/files")
def upsert_file(body: UpsertFileBody,
                user_id: int = Depends(get_trusted_user_id)):
    repo = get_repo_factory().get(user_id)
    file = repo.upsert_file(body.ticker, body.label, body.company_name)
    return file


@router.patch("/files/{research_file_id}")
def patch_file(research_file_id: int, body: PatchFileBody,
               user_id: int = Depends(get_trusted_user_id)):
    repo = get_repo_factory().get(user_id)
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    file = repo.update_file(research_file_id, **updates)
    if not file:
        raise HTTPException(404, "research file not found")
    return file


@router.delete("/files/{research_file_id}")
def delete_file(research_file_id: int,
                user_id: int = Depends(get_trusted_user_id)):
    repo = get_repo_factory().get(user_id)
    ok = repo.delete_file(research_file_id)
    if not ok:
        raise HTTPException(404, "research file not found")
    return {"deleted": True}


@router.get("/threads")
def list_threads(research_file_id: int,
                 user_id: int = Depends(get_trusted_user_id)):
    repo = get_repo_factory().get(user_id)
    # Implicit ownership check: file is in user's own DB
    if not repo.get_file(research_file_id):
        raise HTTPException(404, "research file not found")
    return {"threads": repo.list_threads_for_file(research_file_id)}


@router.post("/threads")
def create_thread(body: CreateThreadBody,
                  user_id: int = Depends(get_trusted_user_id)):
    repo = get_repo_factory().get(user_id)
    if not repo.get_file(body.research_file_id):
        raise HTTPException(404, "research file not found")
    if body.is_explore:
        tid = repo.get_or_create_explore_thread(body.research_file_id)
    elif body.is_panel:
        tid = repo.get_or_create_panel_thread(body.research_file_id)
    else:
        if not body.name:
            raise HTTPException(400, "name required for non-reserved thread")
        thread = repo.create_thread(body.research_file_id, body.name)
        return thread
    # Return full thread row for reserved-thread creates
    threads = repo.list_threads_for_file(body.research_file_id)
    thread = next((t for t in threads if t["id"] == tid), None)
    return thread


@router.get("/messages")
def list_messages(thread_id: int, research_file_id: int, limit: int = 50,
                  user_id: int = Depends(get_trusted_user_id)):
    """List messages for a thread. Requires research_file_id for ownership check."""
    repo = get_repo_factory().get(user_id)
    if not repo.thread_belongs_to_file(thread_id, research_file_id):
        raise HTTPException(404, "thread not found in this file")
    return {"messages": repo.list_messages(thread_id, limit=limit)}
```

### Notes

- **No POST /messages endpoint** — messages are persisted server-side during turn processing (Step 3), never posted from the client
- **Ownership checks are implicit** by per-user file scoping: if a file/thread exists in the user's `research.db`, it belongs to them
- `thread_belongs_to_file` on the message list is defense-in-depth for client-supplied thread_ids
- Pagination via `before_id` is TODO for Phase 1 if infinite scroll is wanted; otherwise list_messages caps at 50

### Tests

- `test_routes_files_crud` — upsert returns row with id; patch updates fields; delete removes row; list returns ordered by updated_at
- `test_routes_label_disambiguation` — POST with same ticker+label=empty twice is idempotent; POST with same ticker + different labels creates two files
- `test_routes_threads` — get-or-create explore/panel is idempotent; two files on same ticker each get independent explore threads
- `test_routes_messages_ownership` — asking for thread_id from wrong research_file_id returns 404
- `test_routes_user_isolation` — user A's files are not visible to user B (integration test with two users)

---

## Step 5 — Risk_module Research Content Proxy

**Owner:** risk_module
**New file:**
- `routes/research_content.py`

**Registered in** `app.py`.

### Thin proxy responsibilities

1. Tier gate (`minimum_tier="paid"`)
2. Extract `user_id` from authenticated session
3. Inject `user_id` into gateway forwarding context
4. Forward request to `{GATEWAY_URL}/api/research/*`
5. Return response verbatim (no business logic, no transformation)

```python
# routes/research_content.py

from fastapi import APIRouter, Depends, Request
from app_platform.auth.dependencies import create_tier_dependency
from services.auth_service import auth_service
from routes.gateway_proxy import forward_to_gateway  # reuse existing pattern

_get_paid_user = create_tier_dependency(auth_service, minimum_tier="paid")

research_content_router = APIRouter(
    prefix="/api/research/content",
    tags=["research-content"],
)

# Catchall forwarder
@research_content_router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PATCH", "DELETE"],
)
async def forward_research(path: str, request: Request,
                           user = Depends(_get_paid_user)):
    """Forward any /api/research/content/* call to ai-excel-addin's
    /api/research/* with user_id injected as a trusted gateway header."""
    return await forward_to_gateway(
        request=request,
        upstream_path=f"/api/research/{path}",
        user_id=user["user_id"],
    )
```

### Gateway forwarding contract

The existing `forward_to_gateway` helper (or equivalent) must support injecting `user_id` into the upstream request. If it doesn't, extend it. The ai-excel-addin side expects user_id in either a header (`X-Research-User-Id`) or a context payload — pick one convention and document.

### Tests

- `test_proxy_tier_gate` — request without paid tier returns 402/403 at the proxy, never reaches gateway
- `test_proxy_user_id_injection` — mock gateway records the forwarded user_id; assert it matches the authenticated session's user_id, not any client-supplied value
- `test_proxy_forwarding_methods` — GET/POST/PATCH/DELETE all forward correctly
- `test_proxy_error_translation` — gateway 404 → proxy returns 404; gateway 500 → proxy returns 502

---

## Step 6 — Zustand `researchStore`

**Owner:** frontend (risk_module)
**New file:**
- `frontend/packages/connectors/src/stores/researchStore.ts`

Adapted from v4 Step 5 with identity updates: `activeFile.id` (research_file_id) is the identity threaded through everything.

### State shape

```typescript
interface ResearchTab {
  id: string;            // 'explore' | thread_id as string
  type: 'explore' | 'thread' | 'document';  // document is Phase 2
  label: string;         // 'Explore' | 'Ownership' | ...
  closeable: boolean;    // explore = false; others = true
  threadId?: number;
}

interface ResearchMessage {
  id: number | string;   // server id after persist, 'pending-*' optimistic
  threadId: number;
  author: 'user' | 'agent' | 'system';
  content: string;
  contentType: 'message' | 'note' | 'tool_call' | 'artifact' | 'pending_error';
  tabContext?: number;
  metadata?: Record<string, unknown>;
  createdAt: number;
}

interface ResearchFile {
  id: number;            // research_file_id — the identity
  ticker: string;
  label: string;
  companyName?: string;
  stage: string;
  direction?: string;
  strategy?: string;
  conviction?: number;
}

interface ResearchState {
  activeFile: ResearchFile | null;
  exploreThreadId: number | null;
  panelThreadId: number | null;
  tabs: ResearchTab[];
  activeTabId: string;
  messagesByThread: Record<number, ResearchMessage[]>;
  isStreaming: boolean;
  streamingThreadId: number | null;
  isBootstrapped: boolean;
}

interface ResearchActions {
  // Bootstrap
  hydrate(params: {
    file: ResearchFile;
    exploreThreadId: number;
    panelThreadId: number;
    threads: Array<{ id: number; name: string; finding_summary?: string }>;
    messagesByThread: Record<number, ResearchMessage[]>;
  }): void;

  // File
  setActiveFile(file: ResearchFile | null): void;

  // Tabs
  openTab(tab: ResearchTab): void;
  closeTab(tabId: string): void;
  setActiveTab(tabId: string): void;

  // Messages
  addMessage(threadId: number, message: ResearchMessage): void;
  appendToLastMessage(threadId: number, text: string): void;
  replaceMessages(threadId: number, messages: ResearchMessage[]): void;

  // Threads
  createThread(name: string): Promise<number>;  // returns new thread id

  // Streaming
  setStreaming(threadId: number | null): void;

  // Reset
  reset(): void;
}
```

**Pattern:** `createWithEqualityFn` + `devtools` middleware + `shallow` equality selectors (follows existing `uiStore.ts`).

### `hydrate()` implementation

1. Sets `activeFile`, `exploreThreadId`, `panelThreadId`
2. Builds initial `tabs` array: Explore tab + one tab per non-explore/non-panel thread
3. Populates `messagesByThread` from loaded messages
4. Sets `activeTabId = 'explore'`
5. Sets `isBootstrapped = true`

### Tests

- `test_researchStore_hydrate` — hydrate initializes tabs + messagesByThread correctly
- `test_researchStore_addMessage` — adds to correct thread; agent placeholder pattern works
- `test_researchStore_appendToLastMessage` — streams correctly into last agent message
- `test_researchStore_replaceMessages` — reconciliation overwrites in-memory state

---

## Step 7 — `useResearchChat` + `ResearchStreamManager`

**Owner:** frontend (risk_module)
**New files:**
- `frontend/packages/chassis/src/services/GatewayClaudeService.ts` (EXTEND — add `streamWithContext`)
- `frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts`
- `frontend/packages/connectors/src/features/external/contexts/ResearchStreamContext.tsx`

**Preserved from v4 Step 6** with one key change: context payload uses `purpose: 'research_workspace'` and `research_file_id` instead of `ticker`.

### GatewayClaudeService refactor (v4 preserved)

Extract shared streaming logic; add `streamWithContext`:

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

async* sendMessageStream(message, history, portfolioName?, purpose?, signal?) {
  // Existing — delegates to _streamRequest (unchanged behavior)
}

async* streamWithContext(
  messages: Array<{ role: string; content: string }>,
  contextOverrides: Record<string, unknown>,
  signal?: AbortSignal,
): AsyncGenerator<ClaudeStreamChunk> {
  yield* this._streamRequest(messages, contextOverrides, signal);
}
```

### ResearchStreamManager (v4 preserved wholesale)

All the v4 mechanisms preserved exactly:
- React context singleton at `ResearchWorkspace` level
- Promise-based sequencing (`currentSend.catch(() => {})` before new send)
- `AbortController` per send, aborted on new send
- 409 retry with 2.5s backoff
- Error chunk → throw conversion (for gateway stream lock contention)
- `hasError` state locks input until retry

See v4 Step 6 "ResearchStreamManager" section for the full class — copy verbatim to the new file `ResearchStreamContext.tsx`.

### useResearchChat hook

```typescript
const TRANSCRIPT_LIMIT = 50;

function useResearchChat(options: {
  researchFileId: number;
  threadId: number;
  tabContext?: number;  // numeric thread_id of active reader tab
}) {
  const streamManager = useContext(ResearchStreamContext);
  const { researchFileId, threadId, tabContext } = options;

  const sendMessage = async (text: string) => {
    const store = researchStore.getState();

    // Build transcript (exclude pending_error messages)
    const all = store.messagesByThread[threadId] ?? [];
    const confirmed = all.filter(m => m.contentType !== 'pending_error');
    const recent = confirmed.slice(-TRANSCRIPT_LIMIT);
    const transcript = recent.map(m => ({
      role: m.author === 'agent' ? 'assistant' : 'user',
      content: m.content,
    }));
    transcript.push({ role: 'user', content: text });

    // Optimistic UI
    store.addMessage(threadId, {
      id: `pending-${Date.now()}`,
      threadId,
      author: 'user',
      content: text,
      contentType: 'message',
      createdAt: Date.now() / 1000,
    });
    // Agent placeholder BEFORE streaming (matches usePortfolioChat pattern)
    store.addMessage(threadId, {
      id: `agent-${Date.now()}`,
      threadId,
      author: 'agent',
      content: '',
      contentType: 'message',
      createdAt: Date.now() / 1000,
    });
    store.setStreaming(threadId);

    await streamManager.send({
      threadId,
      messages: transcript,
      context: {
        purpose: 'research_workspace',              // NEW — not 'research'
        research_file_id: researchFileId,           // NEW — not ticker
        thread_id: threadId,
        tab_context: tabContext ?? store.exploreThreadId,
      },
      service: gatewayService,
      onChunk: (chunk) => {
        if (chunk.type === 'text_delta') {
          store.appendToLastMessage(threadId, chunk.content);
        }
      },
      onComplete: () => { store.setStreaming(null); },
      onError: (err) => {
        store.setStreaming(null);
        showErrorToast(`Research chat error: ${err.message}`);
      },
    });
  };

  const retry = async () => {
    // Reload messages from server before unlocking input
    const serverMessages = await fetchResearchMessages(researchFileId, threadId, TRANSCRIPT_LIMIT);
    researchStore.getState().replaceMessages(threadId, serverMessages);
    streamManager.clearError();
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

### MessageInput disable rules (v4 preserved)

1. When `streamManager.isStreaming` → all inputs disabled, stop button shown
2. When `streamManager.hasError` → all inputs disabled, retry button shown
3. Otherwise → active tab's input enabled

### Tests

- `test_useResearchChat_optimistic` — sending a message adds user + agent placeholder to store
- `test_useResearchChat_streaming` — chunk accumulation appends to last agent message
- `test_useResearchChat_abort_on_new_send` — new send aborts previous
- `test_useResearchChat_409_retry` — 409 error retries after 2.5s with backoff
- `test_useResearchChat_error_lock` — error locks input; retry clears
- `test_useResearchChat_context_payload` — sent context includes `purpose: 'research_workspace'` and `research_file_id` (NOT ticker)

---

## Step 8 — Hash Routing Extension

**Owner:** frontend (risk_module)
**Extended files:**
- `frontend/packages/connectors/src/navigation/hashSync.ts`
- `frontend/packages/connectors/src/navigation/useHashSync.ts`

Preserved from v4 Step 7 with one addition: support labeled deep links `#research/VALE:long-thesis` in addition to `#research/VALE`.

### Extended ParsedHash

```typescript
interface ParsedHash {
  view: ViewId;
  tool?: ScenarioToolId;
  context?: { ticker?: string; label?: string };
}
```

### parseHash addition

```typescript
// Existing segments: const [viewSegment, secondSegment] = normalized.split('/');
if (view === 'research' && secondSegment) {
  // secondSegment may be 'VALE' or 'VALE:long-thesis'
  const [ticker, ...labelParts] = secondSegment.split(':');
  const label = labelParts.join(':');  // allow colons inside label if encoded
  return { view, context: { ticker: ticker.toUpperCase(), label } };
}
```

### buildHash addition

```typescript
if (view === 'research' && context?.ticker) {
  const labelSuffix = context.label ? `:${context.label}` : '';
  return `#research/${context.ticker}${labelSuffix}`;
}
```

### hydrateFromHash (v4 preserved)

Runs before `setInitialHash` to prevent URL overwrite on first load. See v4 Step 7 full implementation — the only change is passing `navigationContext` with both `ticker` and `label`.

### Tests

- `test_parseHash_research_default` — `#research/VALE` returns `{ view: 'research', context: { ticker: 'VALE', label: '' } }`
- `test_parseHash_research_labeled` — `#research/VALE:long-thesis` returns `{ ... label: 'long-thesis' }`
- `test_buildHash_research` — state with file label produces correct hash
- `test_hydrateFromHash_first_load` — URL preserved on initial load (no overwrite)

---

## Step 9 — Component Tree

**Owner:** frontend (risk_module)
**New directory:** `frontend/packages/ui/src/components/research/`
**Modified file:** `frontend/packages/ui/src/components/dashboard/views/modern/ResearchContainer.tsx` (gutted to re-export new container)

Preserved from v4 Step 8 with identity/label adaptations: all components use `research_file_id` as the identity; `ResearchFileCard` and workspace header show label when non-empty.

### Component tree

```
ResearchWorkspaceContainer (entry point)
├── TierGate — checks user tier, shows UpgradeSurface if not paid
│   └── UpgradeSurface — "Upgrade to research {pendingTicker}"
├── ResearchListView (when activeFile is null)
│   ├── ResearchFileCard × N — shows "{ticker}" or "{ticker} — {label}"
│   └── NewResearchButton — creates file + opens workspace
└── ResearchWorkspace (when activeFile is set)
    └── ResizablePanelGroup (horizontal)
        ├── ResizablePanel (defaultSize=75, minSize=50) — Reader
        │   ├── ResearchTabBar
        │   │   ├── Tab ("Explore" — always open)
        │   │   ├── Tab × N — thread tabs
        │   │   └── NewThreadButton (+)
        │   └── TabContent
        │       ├── ExploreTab → ConversationFeed + MessageInput
        │       └── ThreadTab → PinnedFinding + ConversationFeed + MessageInput
        ├── ResizableHandle
        └── ResizablePanel (defaultSize=25, minSize=15, maxSize=35) — Agent Panel
            ├── AgentPanelHeader — shows "RESEARCH · {stage} · {ticker}{label suffix}"
            ├── ConversationFeed (panel thread messages)
            └── MessageInput (disabled when any stream active)
```

### Bootstrap flow in ResearchWorkspaceContainer

1. Read `navigationContext?.ticker` and `navigationContext?.label` from uiStore
2. If ticker present → call `useResearchBootstrap({ticker, label})`:
   - **Step A:** `POST /api/research/content/files` with `{ticker, label}` — returns file with `id`
   - **Step B+C parallel:** `POST /api/research/content/threads` with `{research_file_id: file.id, is_explore: true}` and `{..., is_panel: true}`
   - **Step D:** `GET /api/research/content/threads?research_file_id={file.id}`
   - **Step E:** For each thread: `GET /api/research/content/messages?thread_id={id}&research_file_id={file.id}&limit=50`
   - **Step F:** `researchStore.hydrate({ file, exploreThreadId, panelThreadId, threads, messagesByThread })`
3. If no ticker → show `ResearchListView`
4. Clicking a file in ResearchListView sets `navigationContext({ticker, label})` + `setActiveView('research')`

### Tier gate

```typescript
const { user } = useAuth();
if (user?.tier !== 'paid' && user?.tier !== 'business') {
  return <UpgradeSurface ticker={pendingTicker} label={pendingLabel} />;
}
```

### New files (11 components)

1. `ResearchWorkspaceContainer.tsx` — bootstrap + tier gate + routing
2. `ResearchListView.tsx` — file list + create
3. `ResearchWorkspace.tsx` — two-pane layout with `ResizablePanelGroup`
4. `ResearchTabBar.tsx` — IDE-style tab bar
5. `ExploreTab.tsx` — explore conversation feed
6. `ThreadTab.tsx` — thread with pinned finding
7. `AgentPanel.tsx` — right panel
8. `ConversationFeed.tsx` — shared message renderer (two-author rail distinction)
9. `MessageInput.tsx` — shared input, disabled during streaming
10. `ResearchFileCard.tsx` — list view card
11. `UpgradeSurface.tsx` — paid-tier gate

### Reused components

- `ResizablePanelGroup/ResizablePanel/ResizableHandle` from `components/ui/resizable.tsx`
- `MarkdownRenderer` from chat components
- shadcn/ui primitives (Button, Input, Badge, ScrollArea)
- `DashboardErrorBoundary` from shared components

### Styling per spec + DESIGN.md

- Tab bar: Geist Mono 11px, letter-spacing 0.04em
- Active tab: `--text` + 2px bottom border `--accent`
- Agent messages: 13px Instrument Sans, `--ink`, 1px `--accent` left rail
- User messages: 13px Instrument Sans, `--text`, 1px `--text-dim` left rail
- Two-author flat hierarchy (both 13px)

### Tests

- `test_ResearchWorkspaceContainer_tier_gate` — non-paid user sees UpgradeSurface with pending ticker
- `test_ResearchWorkspaceContainer_bootstrap` — with ticker, bootstrap flow runs steps A-F in order
- `test_ResearchListView_empty` — empty state
- `test_ResearchFileCard_label` — shows ticker alone when label empty; shows "ticker — label" when label set
- `test_ResearchTabBar_explore_not_closeable` — no close button on explore tab

---

## Step 10 — React Query Hooks

**Owner:** frontend (risk_module)
**New files:**
- `frontend/packages/connectors/src/features/external/hooks/useResearchFiles.ts`
- `frontend/packages/connectors/src/features/external/hooks/useResearchContent.ts`

### Hooks

```typescript
// useResearchFiles — file-level CRUD

export function useResearchFiles(filters?: { stage?: string }) {
  return useQuery({
    queryKey: ['research-files', filters],
    queryFn: () => api.get('/api/research/content/files', { params: filters }),
  });
}

export function useUpsertResearchFile() {
  return useMutation({
    mutationFn: (data: { ticker: string; label?: string; company_name?: string }) =>
      api.post('/api/research/content/files', data),
    onSuccess: () => queryClient.invalidateQueries(['research-files']),
  });
}

export function useUpdateResearchFile() {
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number; stage?: string; conviction?: number; ... }) =>
      api.patch(`/api/research/content/files/${id}`, data),
    onSuccess: () => queryClient.invalidateQueries(['research-files']),
  });
}

// useResearchContent — threads + messages

export function useResearchThreads(researchFileId: number | null) {
  return useQuery({
    queryKey: ['research-threads', researchFileId],
    queryFn: () => api.get('/api/research/content/threads', {
      params: { research_file_id: researchFileId }
    }),
    enabled: researchFileId !== null,
  });
}

export function useResearchMessages(threadId: number | null, researchFileId: number | null) {
  return useQuery({
    queryKey: ['research-messages', threadId],
    queryFn: () => api.get('/api/research/content/messages', {
      params: { thread_id: threadId, research_file_id: researchFileId, limit: 50 }
    }),
    enabled: threadId !== null && researchFileId !== null,
  });
}

// useResearchBootstrap — orchestrates the full bootstrap sequence
export function useResearchBootstrap(ticker: string, label: string = '') {
  // Implementation: sequential mutations + queries as per Step 9 bootstrap flow
  // Returns { isLoading, error, isComplete }
}
```

### Tests

- `test_useResearchFiles_query` — fetches file list, caches by filter
- `test_useResearchBootstrap_full_flow` — mock API sequence returns expected store state after hydration
- `test_useResearchBootstrap_existing_file` — upsert returns existing file; threads already exist (get-or-create idempotent); messages load

---

## Step 11 — Integration Wiring

**Owner:** frontend (risk_module) + risk_module backend
**Modified files:**
- `frontend/packages/ui/src/components/dashboard/views/modern/ResearchContainer.tsx` (re-export)
- `frontend/packages/ui/src/components/dashboard/views/modern/ModernDashboardApp.tsx` (deep link handling)
- `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` (exit ramp to research)
- `app.py` (register `research_content_router`)

### Wiring list

1. `ResearchContainer.tsx` becomes a thin re-export:
   ```typescript
   import ResearchWorkspaceContainer from '../../../research/ResearchWorkspaceContainer';
   export default ResearchWorkspaceContainer;
   ```

2. Sidebar "Research" link → `setActiveView('research')` (already wired; no change)

3. Deep link `#research/VALE` → `parseHash` returns context → `setNavigationContext({ ticker: 'VALE', label: '' })` → `ResearchWorkspaceContainer` reads context → bootstrap flow runs

4. Deep link `#research/VALE:long-thesis` → same flow with `label: 'long-thesis'`

5. Exit ramp from `StockLookupContainer` "Open Research →" button:
   ```typescript
   const handleOpenResearch = () => {
     setNavigationContext({ ticker: currentTicker, label: '' });
     setActiveView('research');
   };
   ```

6. `app.py` registers the proxy router:
   ```python
   from routes.research_content import research_content_router
   app.include_router(research_content_router)
   ```

### Tests

- `test_deep_link_to_workspace` — visiting `#research/VALE` hydrates store and renders workspace
- `test_exit_ramp_from_stock_lookup` — clicking "Open Research →" sets context and navigates

---

## Dependency Batches & Parallelization

```
Batch 0 (first, no deps — pre-requisite for everything else):
  Step 0: Memory layer per-user migration (ai-excel-addin)
  (NOTE: Step 0 could run in parallel with frontend-only steps, but the
   backend Steps 1-4 all depend on the per-user path infrastructure it creates.)

Batch 1 (parallel, depends on Step 0):
  Step 1: ResearchRepository + schema (ai-excel-addin, uses same per-user dir)
  Step 6: researchStore (frontend, types from arch doc — contract-first)
  Step 8: Hash routing extension (frontend)

Batch 2 (depends on Batch 1):
  Step 2: Research-Mode Policy Layer — prompt routing (needs Step 1 for repo)
  Step 3: build_research_context + runtime integration (needs Step 1 + 2)
  Step 4: Research REST endpoints (needs Step 1)

Batch 3 (depends on Batch 2):
  Step 5: Risk_module proxy (needs Step 4 to exist for forwarding target)
  Step 7: useResearchChat + ResearchStreamManager (needs Step 6 + gateway contract)
  Step 10: React Query hooks (needs Step 5)

Batch 4 (depends on Batch 3):
  Step 9: Component tree (needs Steps 6, 7, 8, 10)

Batch 5:
  Step 11: Integration wiring (needs Step 9)
```

**Estimated duration** (single implementer, sequential within batch, parallel across batch):
- Batch 0: 1-2 days (memory migration — mechanical but touches many files)
- Batch 1: 1 day
- Batch 2: 1-2 days (policy layer is lighter now; Step 3 is the main work)
- Batch 3: 1 day
- Batch 4: 2-3 days
- Batch 5: 0.5 day

**Total: ~7-9 days of implementation work for a single developer,** plus Codex review rounds per batch.

---

## Test Summary

**Phase 1 test requirements (comprehensive):**

**Step 1 — ResearchRepository (7 tests):**
- Schema creation + idempotent migration
- File upsert + label disambiguation
- Thread get-or-create for explore/panel
- Message save + list
- Two-user isolation
- Two-file-same-ticker isolation

**Step 0 — Memory Per-User Migration (4 tests):**
- MemoryStoreFactory per-user isolation (two users have independent DBs)
- Migration path creates DB + runs migrations at new per-user location
- Markdown sync writes to per-user directory
- Connector user routing (writes to authenticated user's store)

**Step 2 — Policy Layer (3 tests — prompt routing only):**
- Prompt stack includes research-specific file context block
- Predicate correctly identifies research_workspace purpose
- Full tool catalog (memory_*, run_agent) preserved on research turns — no regression

**Step 3 — Context + Persistence (7 tests):**
- `build_research_context` basic
- `build_research_context` missing file
- `build_research_context` panel tab (reader messages included)
- No memory guidance in output string
- Pre-turn persistence failure rejects turn before SSE yield
- Post-turn persistence captures full stream
- Disconnect mid-stream loses agent message but preserves user message

**Step 4 — REST endpoints (5 tests):**
- Files CRUD
- Label disambiguation on POST
- Threads get-or-create idempotent; two files on same ticker get independent threads
- Messages ownership check
- User isolation

**Step 5 — Proxy (4 tests):**
- Tier gate
- User_id injection (cannot be overridden by client)
- All methods forward correctly
- Error translation

**Steps 6-10 — Frontend:**
- researchStore actions (4 tests)
- useResearchChat behavior (6 tests)
- Hash routing (4 tests)
- Component tier gate + bootstrap (5 tests)
- React Query hooks (3 tests)

**Step 11 — Integration (2 tests):**
- Deep link end-to-end
- Exit ramp from stock lookup

**Total new Phase 1 tests: ~52**

---

## Scope Boundaries — NOT in Phase 1

- Document tabs (filing reading, transcripts, investor decks) — Phase 2
- Agent document highlights + langextract overlay rendering — Phase 2
- User annotations on source text — Phase 2
- 3 new langextract schemas (`management_commentary`, `competitive_positioning`, `segment_discussion`) — Phase 2
- Filing content-hash versioning — Phase 2
- Diligence checklist (9 core sections + qualitative factors UI) — Phase 3
- Style-aware qualitative factor suggestions — Phase 3
- `fetch_data_for(category, ticker)` data puller registry — Phase 3
- Research handoff artifact assembly — Phase 4
- `annotate_model_with_research()` MCP tool + `BuildModelOrchestrator` — Phase 4
- SIA template driver-name → cell-address mapping — Phase 4
- Report export to PDF/markdown — Phase 5
- Web search integration — Phase 5
- Multi-ticker theme research — Phase 5
- Bidirectional sync with existing EAV ticker memory — Phase 5
- Run-to-completion or incremental persistence for disconnect resilience — Phase 2+
- Per-thread gateway sessions for conversation isolation — Phase 2+ if needed

---

## Cross-Repo Change Summary

| Repo | Changes |
|---|---|
| **ai-excel-addin** | New `api/research/` package (5 files: `repository.py`, `policy.py`, `context.py`, `routes.py`, `__init__.py`). Extensions to `api/agent/shared/system_prompt.py`, `tool_catalog.py`, `tool_handlers.py` and `api/agent/interactive/runtime.py` to honor the policy layer. New per-user storage directory `data/users/{user_id}/research.db`. Total: ~1500 lines of new code + ~50 lines of extension points. |
| **risk_module (backend)** | New `routes/research_content.py` thin proxy (~80 lines). Registration in `app.py`. No Postgres migration. No gateway enricher. |
| **risk_module (frontend)** | 11 new React components in `components/research/`. New `researchStore.ts`, `useResearchChat.ts`, `ResearchStreamContext.tsx`, `useResearchFiles.ts`, `useResearchContent.ts`. Extensions to `GatewayClaudeService.ts`, `hashSync.ts`, `useHashSync.ts`, `ResearchContainer.tsx`, `ModernDashboardApp.tsx`, `StockLookupContainer.tsx`. Total: ~2000 lines of new code + ~200 lines of extension points. |

---

## What This Plan DOES Touch in Existing Code (Step 0 Migration)

The per-user-everything model requires extending (not replacing) existing memory infrastructure:

- `api/memory/store.py` — EXTENDED: `AnalystMemoryStore` accepts `db_path` arg; `MemoryStoreFactory` resolves per-user
- `api/memory/analyst_memory.db` — MIGRATED: moved to `data/users/{user_id}/analyst_memory.db`
- `api/memory/workspace/tickers/*.md` — MIGRATED: moved to `data/users/{user_id}/workspace/tickers/*.md`
- `api/memory/markdown_sync.py` — EXTENDED: per-user path resolution
- `api/memory/ingest.py` + 9 connectors — EXTENDED: pass `user_id` through ingest chain
- Runtime memory injection (`system_prompt.py`) — EXTENDED: use per-user store
- Existing `memory_*` tools — FULLY AVAILABLE on research turns (no restrictions)
- Existing `run_agent` — FULLY AVAILABLE on research turns (no restrictions)

**All extensions are backward-compatible:** if `user_id` is not provided (e.g., legacy code paths during migration), fallback to henrychien's user_id or a default path. Once migration completes, all paths flow user_id explicitly.

---

## References

- Locked architecture: `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md`
- 7 locked decisions: `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md`
- Product spec: `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md`
- Historical v4 plan: `docs/planning/RESEARCH_WORKSPACE_PHASE1_PLAN.md` (superseded by this document)
- Design preview: `~/.gstack/projects/henrysouchien-risk_module/designs/research-workspace-20260403/`
- DESIGN.md research workspace section
- Codex consult threads: `019d792b`, `019d7935`, `019d794e`, `019d7d6a`
