# Research Workspace — Architecture Decisions Log

**Status:** Phase 1+ planning anchor
**Last updated:** 2026-04-13 (final cross-doc consistency sweep)
**Supersedes:** Pivot 2 from `RESEARCH_WORKSPACE_ARCHITECTURE_CHECKPOINT.md` (2026-04-04). Phase 1 Plan v4 (commit `7b4c8a76`) is fully superseded by `RESEARCH_WORKSPACE_PHASE1_PLAN_V5.md` (Codex PASS R15).

**Codex consult thread history:**
- `019d792b` — Pivot 2 override to Option X (cohabit research in ai-excel-addin SQLite)
- `019d7935` — Per-user SQLite files follow-up
- `019d794e` — Decisions 3/5/6/7 bundle review
- `019d7d6a` — Architecture + decisions coherence review (2026-04-11). Surfaced 4 structural gaps: (1) `research_file_id` propagation needed for Decision 5 to be real, (2) Research-Mode Policy Layer required to enforce Invariant 2, (3) Invariant 5 softened for honest disconnect semantics, (4) Invariant 10 softened to advisory because openpyxl readback can't verify recalc. All refinements applied.

**References:**
- `EQUITY_RESEARCH_WORKSPACE_SPEC.md` — product spec, design consultation, eng review findings
- `RESEARCH_WORKSPACE_ARCHITECTURE_CHECKPOINT.md` (2026-04-04) — prior hybrid-storage decision
- `RESEARCH_WORKSPACE_PHASE1_PLAN_V5.md` — Phase 1 implementation plan (Codex PASS R15; supersedes v4)
- `DESIGN.md` — research workspace design section
- Design preview: `~/.gstack/projects/henrysouchien-risk_module/designs/research-workspace-20260403/`

---

## Pipeline Framing (2026-04-10)

The research workspace is the **front half** of an investment pipeline:

```
explore → diligence → report → model-build handoff
```

- **Explore** (Phase 1): human + agent conversation in a two-pane workspace, threads emerge from exploration
- **Diligence** (Phase 3): structured checklist that collects the fields the report needs
- **Report** (Phase 4): structured, user-scoped artifact — not a document, a multi-consumer contract
- **Model-build handoff** (Phase 4): report flows to `model_build()` in ai-excel-addin which populates a SIA-template Excel model

The report is a **multi-consumer contract**:
1. Human — rendered report view
2. Model builder agent — populates `model_build()` + post-build assumption writes
3. Ticker memory — (eventual) durable per-ticker knowledge

Phase planning works **backwards from the handoff** — the report shape determines the diligence sections, which determine what exploration must capture, which determines the Phase 1 storage + schema.

---

## Investigation Findings (2026-04-10)

Three parallel Explore agents surfaced the following. Full transcripts in task logs; compressed findings below.

### Inv-A — Model Builder Context Shape

- `model_build()` exists at `financial-modeling-tools/mcp-server/model_engine_mcp_server.py` (also registered as `model-engine` MCP server). Takes `ticker`, `company_name`, `fiscal_year_end`, `most_recent_fy`, `output_path`, `source` (`fmp`|`edgar`), `financials` dict (for FMP) or `edgar_fetcher` callable, optional `sector`, `n_historical`, `n_projection`.
- **Caller pre-fetches FMP data.** EDGAR is fetched lazily via callable. Model builder does NOT fetch FMP itself.
- **No slot for research metadata today.** Thesis, catalysts, risks, peers, valuation range, assumption overrides are NOT part of the current tool contract.
- **No assumption overrides at build time.** Assumptions are written post-build via `update_model`, not during `model_build()`.
- Recent commit `1f0bf96` ("knowledge layer + thesis-as-source-of-truth skill architecture") signals intended direction but isn't shipped.
- TODO at `AI-excel-addin/docs/design/TODO-equity-research-modeling.md` lists "research → model handoff contract" as open, "per-ticker memory" as aspirational.

### Inv-B — Reading Surface (~70% already built)

- **Filing retrieval works end-to-end.** `get_filing_sections()` writes markdown to disk under `~/.cache/edgar-mcp/file_output/` (or `EDGAR_MCP_OUTPUT_DIR`). `parse_filing_sections()` at `AI-excel-addin/mcp_servers/langextract_mcp/text_utils.py:11-26` returns `SectionMap: dict[str, tuple[str, int, int]]` — section header → (text, start offset, end offset). **Offsets are exact** — tables are whitespace-filled, not stripped, so character positions are stable.
- **Rendering unit = filing section** (e.g., "Item 1A Risk Factors"). Each section is a standalone tuple, renderable without reconstructing the full filing.
- **Langextract** returns structured extractions with `(class, text, attributes, char_start, char_end)` — perfect grounding for agent highlights as overlays on raw section text. 4 hardcoded schemas today: `risk_factors`, `forward_guidance`, `capital_allocation`, `liquidity_leverage`.
- **Transcripts** via `fmp-mcp-dist/fmp/server.py` `get_earnings_transcript(symbol, year, quarter, format="full")` — returns per-speaker segments with prepared remarks vs Q&A separated. **Correction (Phase 2 plan investigation):** FMP transcripts do NOT return `char_start`/`char_end` per speaker segment. The parser returns `speaker`, `role`, `text`, `word_count` only. Phase 2 resolves this by writing transcripts as immutable content-hashed markdown files and using char offsets within that markdown (same approach as filings). The annotation schema remains unified.
- **Annotations = greenfield.** No existing annotation/highlight schema anywhere. ~30% new work: annotation table, React document tab components, text selection capture, overlay rendering.
- **Chunks + embeddings store exists but filings don't flow through it today.** If Phase 3+ needs semantic search across research sources, ingestion wiring is new work (can defer).
- **No paragraph-level addressing.** Char offsets are the only stable reference. If report citations need "Item 7 para 3" strings, a post-processor can inject paragraph markers (Decision 6).

### Inv-C — Existing AI-Excel-Addin Memory

- **No message storage exists anywhere today.** `session_id` columns in `memories`/`chunks` are stub fields, never queried. The research workspace's `research_threads`/`research_messages` tables are genuinely new with no overlap.
- **EAV ticker memory** in `AI-excel-addin/api/memory/store.py` stores per-ticker: `thesis`, `conviction`, `direction` (long/short/hedge/pair), `strategy` (value/special_situation/macro/compounder), `catalyst`, `timeframe`, `process_stage`, `status`, `source_log_*`.
- **Bidirectional markdown sync** exists: `workspace/tickers/{TICKER}.md` ↔ EAV SQLite. Human edits override DB. Magic-comment header guards imports.
- **No `user_key` scoping** — single-user model today. `memories` has `UNIQUE(entity, attribute)` which is globally unique per (ticker, attribute) — **cannot support multi-user as-is.**
- **No 160K-token compaction** — the prior checkpoint misrepresented this. What exists is per-prompt truncation to `MEMORY_MAX_PROMPT_TOKENS` (default 800) at prompt-build time, with a `[use memory_recall for full content]` fallback notice. No persistent summary table.
- **Field overlap with proposed `research_files`:** the EAV already stores most of the fields the Phase 1 plan wanted to put in Postgres. If not handled carefully, this risks either (a) duplicate authority + sync drift or (b) cross-user contamination via the existing single-user EAV path.

---

## Decision 1 — Storage Architecture (LOCKED 2026-04-10)

**The change (one sentence):** All research workspace state goes into **per-user SQLite files** under `AI-excel-addin/data/users/{user_id}/research.db`, with physical filesystem isolation instead of row-level `user_key` scoping. Risk_module Postgres does NOT hold any research workspace tables.

**This supersedes:**
- Pivot 2 from the 2026-04-04 checkpoint ("all-SQLite → Postgres for metadata; multi-user is first-order")
- Steps 1, 2, 4a from `RESEARCH_WORKSPACE_PHASE1_PLAN.md` v4
- The "lightweight metadata sync between Postgres research_files and agent memories" handwave

### Why

1. **Field overlap is nearly 1:1 with existing EAV ticker memory** — splitting the domain to preserve "metadata in Postgres" creates an undefined sync problem for no benefit.
2. **Codex's multi-user caveat** (2 consult rounds): the existing `memories` + `workspace/tickers/*.md` path is single-user and **cannot be extended with research state without cross-user contamination.** Research must live in a new, user-scoped path from day one.
3. **Physical isolation is stronger than row-level scoping.** Per-user files eliminate an entire class of leak bugs (missing `WHERE user_key=?` filters).
4. **Concurrency.** Codex flagged that `analyst_memory.db` uses a process-wide lock serializing all writes. Per-user files give each user their own lock.
5. **Testability.** Temp dir per test = throwaway DB. Hermetic migrations. Trivial cleanup.
6. **The research domain is self-contained.** It doesn't join with any other risk_module Postgres tables (portfolios, baskets) beyond tier gating, which is enforced at the proxy boundary (CRUD: `routes/research_content.py`; Chat: existing gateway proxy via `purpose` field).

### File Structure

```
AI-excel-addin/
  data/
    filings/                     # SHARED immutable content-addressed filing cache (Phase 2+)
                                 # Safe to share across users because filings are public SEC
                                 # documents and the content hash in the filename guarantees
                                 # immutability.
    users/
      {user_id}/                 # EVERYTHING user-owned lives here (per-user physical isolation)
        analyst_memory.db        # MIGRATED Phase 1 Step 0 — was api/memory/analyst_memory.db
        workspace/
          tickers/{TICKER}.md    # MIGRATED Phase 1 Step 0 — per-user markdown sync
        research.db              # NEW Phase 1 — research_files, threads, messages, annotations, handoffs
        exports/                 # (Phase 4+) per-user report exports
                                 #   research_handoff_{research_file_id}_v{N}.json
                                 #   model_{research_file_id}_v{N}.xlsx
                                 # (keyed by research_file_id, NOT ticker, to prevent collisions
                                 #  across labeled files on the same ticker)
```

**Per-user-everything model:** Under this decision, ALL ai-excel-addin persistent state is per-user. The existing `analyst_memory.db` and `workspace/tickers/*.md` are **migrated in Phase 1 Step 0** from their old shared paths (`api/memory/analyst_memory.db`, `api/memory/workspace/tickers/*.md`) to the new per-user locations (`data/users/{user_id}/analyst_memory.db`, `data/users/{user_id}/workspace/tickers/*.md`). After migration, they become per-user the same way `research.db` is. Multi-user contamination is impossible by physical isolation.

**Consequence: the Research-Mode Policy Layer is a lightweight prompt router, not a sandbox.** Because the memory store is now per-user, there's no contamination risk from a research turn calling `memory_store`/`memory_recall`/`memory_read` — those read and write to the user's OWN memory file under `data/users/{user_id}/`. The research agent has full access to all tools (memory, run_agent, sub-agents, everything) on research turns. The policy layer's sole job is routing research turns to a research-specific prompt stack that injects the research file context block; it does NOT restrict tool access or strip handlers.

**Research-Mode Policy Layer responsibilities** (`api/research/policy.py`):

1. **Predicate:** `is_research_workspace(context)` — true when `context.purpose == "research_workspace"` (new identifier, distinct from the existing `context.mode == "research"` which has different product semantics and different prompt behavior).
2. **Prompt stack:** `build_research_prompt_stack(context)` — assembles research-specific system prompt blocks + the file context block from `api/research/context.py`. The research prompt gives the agent guidance about which store is appropriate for which kind of data (workspace state → `research.db`; general ticker observations → memory tools), but this is trust + transparency, NOT code enforcement.
3. **No tool denylist. No handler strip. No sub-agent restriction.** The agent retains full capability on research turns. If the agent writes research-workspace-specific state to the memory store by mistake, that's a recoverable product bug, not a security issue.

**Test requirements:** Phase 1 test suite verifies:
- Research turns receive the research-specific prompt stack (not the generic stack)
- The research prompt includes the file context block with file metadata + thread list + recent messages
- `is_research_workspace()` correctly identifies research turns from context
- Research turns' tool catalog is UNCHANGED (no regression — confirm the full catalog is still available)

**Context key choice — `purpose='research_workspace'` (not `research`):** the existing runtime already uses `context.mode == "research"` for a different product concept (a general research mode within the addin). Reusing `research` as the key would inherit the wrong prompt behavior. The workspace uses `purpose='research_workspace'` to distinguish.

**What about the existing EAV workflow?** After Phase 1 Step 0 migration, the existing analyst memory workflow (including the 9 screener connectors, markdown sync, memory tools in general chat) all continue to work — they just resolve paths per-user instead of from the shared location. For the only existing user (henrychien), the migration is a copy-first cutover (copy → verify → switch code → archive old), not a destructive file move. See Phase 1 Plan v5 Step 0 for the 7-step cutover plan with rollback story. `MemoryStoreFactory.get()` requires explicit `user_id` — missing user_id raises `ValueError`, no default-user fallback. Functionally nothing changes from henrychien's perspective after migration.

### Schema Sketch (research.db)

```sql
CREATE TABLE research_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',                -- disambiguator for multiple theses on same ticker
                                                 -- empty for default file; required for 2nd+ file on same ticker
  company_name TEXT,
  stage TEXT NOT NULL DEFAULT 'exploring',       -- exploring|has_thesis|diligence|decision|monitoring|closed
  direction TEXT,                                -- long|short|hedge|pair
  strategy TEXT,                                 -- value|special_situation|macro|compounder
  conviction INTEGER,                            -- 1..5
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(ticker, label)                          -- file is the user scope; (ticker, label) is unique within user
                                                 -- first file on ticker has label='' and shows as "VALE"
                                                 -- subsequent files require a label and show as "VALE — short thesis"
);

CREATE TABLE research_threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_file_id INTEGER NOT NULL REFERENCES research_files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  finding_summary TEXT,
  is_explore INTEGER NOT NULL DEFAULT 0,
  is_panel INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX idx_threads_file ON research_threads(research_file_id);
CREATE UNIQUE INDEX idx_threads_explore
  ON research_threads(research_file_id) WHERE is_explore = 1;
CREATE UNIQUE INDEX idx_threads_panel
  ON research_threads(research_file_id) WHERE is_panel = 1;

CREATE TABLE research_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES research_threads(id) ON DELETE CASCADE,
  author TEXT NOT NULL,                          -- user|agent|system
  content TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'message',  -- message|note|tool_call|artifact|pending_error
  tab_context INTEGER,                           -- thread_id of active reader tab (numeric)
  metadata TEXT,                                 -- JSON: tool_calls, artifacts, diligence_ref, proposed_stage, etc.
  created_at REAL NOT NULL
);
CREATE INDEX idx_messages_thread ON research_messages(thread_id, created_at);

-- Phase 2
CREATE TABLE annotations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_file_id INTEGER NOT NULL REFERENCES research_files(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL,                     -- filing|transcript|investor_deck
  source_id TEXT NOT NULL,                       -- content-hashed source identifier (e.g., `VALE_10K_2024_a3f8b2c1` for filings, `VALE_4Q24_transcript_b7c3e1f2` for transcripts)
  section_header TEXT,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  selected_text TEXT NOT NULL,
  note TEXT,
  author TEXT NOT NULL,                          -- user|agent
  diligence_ref TEXT,                            -- which Phase 3 section/field this supports
  created_at REAL NOT NULL
);
CREATE INDEX idx_annotations_file_source ON annotations(research_file_id, source_type, source_id);

-- Phase 4
CREATE TABLE research_handoffs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_file_id INTEGER NOT NULL REFERENCES research_files(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,                          -- DENORMALIZED SNAPSHOT — display only, never a lookup key
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft',          -- draft|finalized|superseded
  artifact TEXT NOT NULL,                        -- JSON: the full research_handoff schema
  created_at REAL NOT NULL,
  finalized_at REAL
);
CREATE INDEX idx_handoffs_file ON research_handoffs(research_file_id, version DESC);
```

**No `user_key` column on any table.** The file is the scope.

**Critical identity invariant:** All research content (threads, messages via thread FK, annotations, handoffs) is keyed by `research_file_id`, NOT `ticker`. The `label` column on `research_files` combined with `research_file_id` propagation through the content schema is what makes multiple concurrent theses per ticker actually isolated. Two files on VALE get independent threads, messages, annotations, diligence state, and handoffs. `research_handoffs.ticker` is a denormalized snapshot for display; it's NEVER used as a lookup key.

### Ai-Excel-Addin Layer: `ResearchRepository` Abstraction

New abstraction layer in `AI-excel-addin/api/research/repository.py` (new module):

- Factory: `ResearchRepositoryFactory(base_dir: Path)` — resolves `user_id → Path → ResearchRepository` (no persistent connection; each repository method opens its own connection-per-operation)
- **Connection-per-request default** (per Codex): open → use → close. No long-lived cache.
- Applied on every open: `busy_timeout`, `foreign_keys`, WAL mode (persistent). Don't assume one-time PRAGMA setup is enough.
- Lazy schema migrations on DB open — run `_maybe_migrate()` idempotently. **Must be tested thoroughly** because production state = many DBs at possibly different schema versions.
- Optional: small capped idle cache with LRU + idle TTL + explicit in-use/idle tracking + forced close on eviction. **Only add after profiling shows opens matter.** Beware of file descriptor exhaustion (`.db` + `-wal` + `-shm` per cached user).
- Methods: `create_research_file`, `get_research_file`, `list_research_files`, `update_research_file`, `delete_research_file`, `get_or_create_explore_thread`, `get_or_create_panel_thread`, `list_threads`, `list_messages`, `save_message`, `update_thread_finding`, `list_annotations`, `save_annotation`, etc.
- **Never writes to existing `AnalystMemoryStore`** — stays in its own lane.

### Phase 1 Plan Delta

#### DELETED from v4 plan
- **Step 1:** Postgres migration `database/migrations/20260404_research_files.sql` — does not exist
- **Step 2:** REST CRUD `routes/research.py` — replaced by thin proxy to ai-excel-addin
- **Step 4a:** Context enricher `_research_context_enricher` in `routes/gateway_proxy.py` — agent queries per-user `research.db` directly via `ResearchRepository`, no enricher needed
- **"Lightweight metadata sync between Postgres research_files and agent memories"** — single store, no sync

#### MODIFIED from v4 plan
- **Step 3 (SQLite tables):** Move from `analyst_memory.db` to per-user `research.db`. Drop `user_key` columns (file is scope). Add `annotations` table for Phase 2 prep.
- **Step 4b (System prompt injection):** `build_research_context()` queries the per-user `research.db` via `ResearchRepository`, not the shared `AnalystMemoryStore`. System prompt block reads metadata + threads + messages from a single store.
- **Step 4c (Research content proxy):** Now covers metadata CRUD too (previously just threads/messages). Endpoints:
  - `GET/POST/PATCH/DELETE /api/research/content/files`
  - `GET/POST /api/research/content/threads`
  - `GET /api/research/content/messages`
  - (Phase 2) `GET/POST /api/research/content/annotations`
  - Risk_module proxy (`routes/research_content.py`) enforces `minimum_tier="paid"`, injects `user_id` from session, forwards to ai-excel-addin's new `api/research/*` routes.
- **Step 4d (Server-side message persistence):** Unchanged in intent — runtime hook persists user message before turn + agent response after. Now writes to per-user `research.db` via `ResearchRepository`.

#### PRESERVED from v4 plan
- **Step 5:** Zustand `researchStore` (tabs, messagesByThread, bootstrap, hydrate)
- **Step 6:** `useResearchChat` hook + `ResearchStreamManager` (React context singleton, promise-sequenced aborts, 409 retry with 2.5s backoff, error-chunk → throw conversion, input lock on error)
- **Step 7:** Hash routing extension (`hydrateFromHash` before `setInitialHash`, `buildHash` with context, `handlePopState` context handling)
- **Step 8:** Component tree (11 components: `ResearchWorkspaceContainer`, `ResearchListView`, `ResearchWorkspace`, `ResearchTabBar`, `ExploreTab`, `ThreadTab`, `AgentPanel`, `ConversationFeed`, `MessageInput`, `ResearchFileCard`, `UpgradeSurface`)
- **Step 9:** React Query hooks (`useResearchFiles`, `useResearchBootstrap`, `useResearchThreads`, `useResearchMessages`) — pointed at proxy endpoints
- **Step 10:** Integration wiring (sidebar, deep links `#research/VALE`, StockLookupContainer exit ramp)
- **GatewayClaudeService refactor** (extract `_streamRequest`, add `streamWithContext` with `contextOverrides`)
- **Authority model:** User is sole authority on stage/conviction in Phase 1. Agent suggests via message metadata `proposed_stage`/`proposed_conviction`, never writes directly.
- **Scope boundaries** (NOT in Phase 1): document tabs, annotations, diligence checklist, report generation, exit ramps, web search, opening-take synthesis, multi-ticker themes, bidirectional EAV sync, per-thread gateway sessions.

### Operational Tradeoffs (accepted)

Per-user files has real operational costs we're taking on consciously:

- **N-database schema migration management.** Mitigated by lazy migration on open + thorough test coverage. Don't skimp on migration tests.
- **Fragmented backups.** Per-user file-level backups are trivial per user but harder to aggregate. Acceptable for Phase 6A (single-host) deploy.
- **Cross-user analytics are harder.** No admin dashboards over aggregate research state in Phase 1. Fine — not a current product goal.
- **Per-file corruption handling.** Treated as fleet management when it becomes a real problem.
- **Horizontal scaling story.** Codex flagged this as the real architectural cliff. For Phase 6A (single-host EC2), per-user files on local disk is fine — no sticky sessions needed. **Treat this as intentional interim design.** The escape hatch if we ever go horizontal is Postgres consolidation (scan N files, merge into shared schema with `user_id` FK). The `ResearchRepository` abstraction is designed to make this swap mechanical.

---

## Decisions (All Locked)

All 7 architectural decisions locked as of 2026-04-10. Decisions 1-2-4 were walked interactively; Decisions 3-5-6-7 were sent to Codex consult as a bundle (thread 019d794e) and accepted as a block. Ready to proceed to phase spec drafting.

### Decision 2 — `research_handoff` Artifact Schema + `model_build()` Integration (LOCKED 2026-04-10)

**The artifact:** A structured, user-scoped JSON blob produced at Phase 4 report finalization. It's the multi-consumer contract between research workspace → human reader + model builder agent + (eventual) durable ticker knowledge. Working backwards from this shape determines Phase 3 diligence sections, Phase 2 annotation schema requirements, and Phase 1 message metadata.

#### 2A — Artifact Schema

Schema sketch (`schema_version: "1.0"`):

```jsonc
{
  "schema_version": "1.0",
  "handoff_id": "hf_abc123",
  "created_at": "2026-04-10T14:30:00Z",
  "research_file_id": 42,

  "company": {
    "ticker", "name", "sector", "industry",
    "fiscal_year_end", "most_recent_fy", "exchange"
  },

  "thesis": {
    "statement", "direction", "strategy", "conviction", "timeframe",
    "source_refs": [...]
  },

  "business_overview": {
    "description", "segments": [{ "name", "rev_pct" }],
    "source_refs": [...]
  },

  "catalysts": [{ "description", "expected_date", "severity", "source_ref" }],
  "risks":     [{ "description", "severity", "type", "source_ref" }],

  "valuation": {
    "method", "low", "mid", "high", "current_multiple", "rationale",
    "source_refs": [...]
  },

  "peers": [{ "ticker", "name" }],

  "assumptions": [
    {
      "driver",          // semantic segment-qualified key resolved to SIA template
                         // item_id via schema/templates/driver_mapping.yaml.
                         // Convention: "revenue.segment_1.volume_growth", "tax_rate",
                         // "dso", etc. The "raw:" prefix passes a literal SIA item_id
                         // for company-specific overrides (e.g., "raw:tpl.a.revenue_drivers.operating_metric").
                         // Mapping validated at load time against sia_standard.json item_types.
      "value", "unit", "rationale",
      "source_refs": [...]
    }
  ],

  "qualitative_factors": [
    {
      "id",              // integer — stable identity per factor entry, auto-assigned
                         // via artifact.metadata.next_factor_id counter (Invariant 13).
                         // All mutation operations (edit, delete) use factor_id, not category.
                         // Two factors can share a category.
      "category",        // free-form string — NOT an enum
      "label",           // human-readable display string
      "assessment",      // narrative markdown/text — analyst's judgment
      "rating",          // optional: "high" | "medium" | "low" | null
      "data",            // optional: category-specific structured JSON blob
                         // (e.g., short_interest: { short_pct_float, days_to_cover, borrow_rate };
                         //  street_view: { analyst_count, median_pt, rating_mix, ... })
                         // Schema-free per category; each category can have its own shape.
      "source_refs": [...]
    }
  ],

  "ownership": {
    "institutional_pct", "insider_pct", "recent_activity",
    "source_refs": [...]
  },

  "monitoring": {
    "watch_list": [...]
  },

  "financials": {
    "source": "fmp" | "edgar",
    "data": {...}           // FMP statement dict, OR edgar_fetch_hint for lazy fetch
  },

  "sources": [
    {
      "id",              // "src_1", referenced by source_refs above
      "type",            // "filing" | "transcript" | "investor_deck" | "other"
      "source_id",              // content-hashed identifier, unified across filings and transcripts
      "section_header",
      "char_start", "char_end",
      "text",
      "annotation_id"    // back-link to per-user research.db annotations table
    }
  ],

  "metadata": {
    "analyst_session_id",
    "diligence_completion": {
      "<section_key>": "empty" | "draft" | "confirmed"
    }
  }
}
```

**Key design decisions:**

1. **`schema_version` is top-level** — artifact will evolve; readers gate on version.
2. **Indexed sources, not inline citations** — every claim points into `sources[]` via `source_ref`/`source_refs`. Cleaner re-use, easier agent construction, supports one source feeding multiple claims.
3. **`sources[]` entries back-link to `annotation_id`** — lets the workspace UI navigate "show me where this came from" and re-open the source document at the exact character span.
4. **`assumptions[]` driver keys are resolved to SIA template item_ids via `driver_mapping.yaml`** — segment-qualified keys (e.g., `revenue.segment_1.volume_growth`) map to specific template input rows. The `raw:` prefix passes literal SIA item_ids for company-specific overrides. Requires the driver mapping YAML + `driver_resolver.py` to exist in the template schema.
5. **`qualitative_factors[]` is the extension mechanism.** Not overflow for "stuff that didn't fit the 9 core sections" — it's how different investment styles carry their specific lenses on a name. The 9 core sections are universal baseline; qualitative factors are style-scoped. Design details:
   - `category` is free-form string, NOT an enum. Any new category requires no schema change.
   - **Seed categories** (full list in Decision 4): style-independent (`street_view`, `management_team`, `short_interest`, `earnings_view`, `financing`, `positioning`, `management_quality`, `competitive_moat`, `capital_structure`, `esg`), plus style-specific lists surfaced by Phase 3 diligence UI based on `research_files.strategy` (value / special_situation / macro / compounder).
   - `label` is human-readable display string (category is the identifier, label is what the UI renders — lets analyst customize per-name).
   - `assessment` is narrative markdown/text — no structure imposed.
   - `rating` is optional qualitative (`high`|`medium`|`low`|`null`), not numeric — avoids false precision.
   - `data` is optional, schema-free per category — carries structured attachments for categories that benefit from them (e.g., `short_interest` → `{ short_pct_float, days_to_cover, borrow_rate }`; `street_view` → `{ analyst_count, median_pt, rating_mix }`). Narrative-first factors (moat, management quality) simply omit `data`.
   - **`fetch_data_for(category, ticker)` registry in ai-excel-addin** (ships in Phase 3, moved forward from Phase 4) — per-category data pullers so the pre-population orchestrator can populate `data` during the server-side initial pull. Start with 3 categories, grow as needed.
6. **`diligence_completion`** per-section state (`empty`|`draft`|`confirmed`) lets the handoff be partial ("draft a model now, finalize research later").
7. **No `user_id` field** — implicit from the per-user `research.db` the artifact lives in.

#### 2B — Storage Location

**`research_handoffs` table in per-user `research.db`:**

```sql
CREATE TABLE research_handoffs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_file_id INTEGER NOT NULL REFERENCES research_files(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,      -- incremented on create_new_version
  status TEXT NOT NULL DEFAULT 'draft',    -- draft | finalized | superseded
  artifact JSON NOT NULL,                  -- the full schema above
  created_at REAL NOT NULL,
  finalized_at REAL
);
CREATE INDEX idx_handoffs_file ON research_handoffs(research_file_id, version DESC);
```

**Lifecycle:**
- **Draft** — created when diligence tab activates (Phase 3). Updated progressively as sections are populated via `update_handoff_section()` and `batch_update_handoff_sections()`.
- **Finalized** — user clicks "Finalize Report"; `finalized_at` set; version becomes immutable.
- **Superseded** — user clicks "New Version" on a finalized handoff; old finalized row updated to `status='superseded'`, new row created with `version+1, status='draft'`.

**Optional JSON export:** on user-triggered "Export Handoff" action → write `data/users/{user_id}/exports/research_handoff_{research_file_id}_v{version}.json`. Keyed by `research_file_id`, NOT ticker, to prevent filename collisions across two labeled files on the same ticker. The export is a materialization for archival/sharing, NOT the source of truth. The row in `research_handoffs` is authoritative.

**Why not JSON-on-disk as source of truth:**
- Transactional with rest of research state (handoff version = snapshot of research at finalization time)
- Queryable history (`SELECT * FROM research_handoffs WHERE research_file_id=? ORDER BY version DESC`) — NOTE: lookup key is `research_file_id`, not `ticker`. `research_handoffs.ticker` is a denormalized snapshot field for display only.
- No file fleet management or orphaned blobs
- `annotate_model_with_research()` just loads the row by handoff_id at call time; no filesystem dependency at handoff

#### 2C — Integration with `model_build()`

**Mechanic: Option B — additive two-step tool, not `model_build()` extension.**

```python
# Step 1: build (unchanged)
result = model_build(
    ticker="VALE",
    company_name="Vale S.A.",
    fiscal_year_end="12-31",
    most_recent_fy=2025,
    output_path="data/users/{user_id}/exports/model_{research_file_id}_v{N}.xlsx",
    source="fmp",
    financials=handoff.financials.data,
    sector=handoff.company.sector,
)

# Step 2: annotate with research context (NEW TOOL)
annotate_model_with_research(
    model_path=result.output_path,
    handoff_id=handoff.id,          # loads row from research_handoffs
    user_id=user_id,                # per-user DB routing
)
```

**New Phase 4 tool: `annotate_model_with_research(model_path, handoff_id, user_id)`**

Lives in ai-excel-addin as a new MCP tool. Responsibilities:
1. Load `research_handoffs` row by `handoff_id` from the user's `research.db` (via `ResearchRepositoryFactory.get(user_id)`)
2. Open the workbook at `model_path` (openpyxl)
3. Write `handoff.assumptions[]` to SIA template driver cells (requires driver-name → cell-address mapping — either new YAML or extension of existing driver metadata)
4. Write research context to a hidden metadata sheet (or named range) — JSON blob of `thesis`, `catalysts`, `risks`, `peers`, `valuation`, `qualitative_factors` for future reference by automation
5. Save workbook, return `{model_path, annotated_at}`

**Why Option B over Option A (`model_build()` extension):**
1. `model_build()` is Codex-reviewed and stable — additive tool is lower risk than modifying working code
2. Composability — if research updates after a model is built, user can re-annotate without rebuilding (rebuilds are slow, especially for EDGAR-sourced models)
3. Forward-compatible — if build-time research injection becomes compelling later, Option A can be added without breaking Option B; the `research_handoff` artifact stays the stable contract
4. SIA template modification is deferred — adding a visible "Research Context" sheet can ship later as polish

**Option B tradeoff accepted:** Non-atomic. Build succeeds, annotate fails = partial state. Mitigation: `annotate_model_with_research()` is idempotent (re-runs cleanly); user or agent can retry on failure. For Phase 4 MVP, acceptable.

**Phase 4 MVP rendering choice:** hidden metadata sheet (JSON blob in a named range or hidden sheet), NOT a visible rendered sheet. The primary human-readable render lives in the research workspace UI, not Excel. A visible research context sheet is a later polish item — requires SIA template modification + formatted row layout work.

#### What This Decision Changes for Earlier Phases

- **Phase 1 `research_messages.metadata` JSON column** — must support `diligence_ref` (which diligence section a message contributes to) and `proposed_*` fields (agent suggestions for stage/conviction/assessments).
- **Phase 2 `annotations` table** — must have `diligence_ref` column to thread annotations to Phase 3 sections, and the annotation table's `id` is what `sources[].annotation_id` references.
- **Phase 3 diligence sections** — the 9 sections I back-propagated earlier need to be updated. Instead of 9 fixed sections, we now have **9 structured sections + 1 dynamic "Qualitative Factors" section** that allows multiple typed-but-extensible entries. Decision 4 will capture this properly.
- **Phase 4 ai-excel-addin work** — need to define the driver-name → SIA template cell-address mapping (either new YAML file or extension of existing `schema/` driver metadata). Scope item.

#### Integration uses a REST orchestrator, NOT a direct MCP path from the frontend

Surfaced by architecture coherence review (Codex thread 019d7d6a): Flow 5 originally sketched the frontend calling `model_build()` and `annotate_model_with_research()` as MCP tools directly. This is incorrect — the frontend does not have direct MCP access, and introducing one for research would be a new security + architecture pattern.

**Corrected Phase 4 flow:**
1. Frontend → `POST /api/research/content/handoffs/{handoff_id}/build-model` (authenticated REST call through the research content proxy)
2. Ai-excel-addin's `BuildModelOrchestrator` (new Phase 4 module at `api/research/build_model_orchestrator.py`) runs the two-step sequence:
   - Step A: `model_build()` with financials from the handoff
   - Step B: `annotate_model_with_research()` with the handoff_id + user_id
3. Returns `{model_path, handoff_id, build_status, annotation_status}` to the frontend

The MCP tool layer is the transport between the orchestrator and the model engine — internal to ai-excel-addin, not exposed to the frontend.

### Decision 3 — Assumption Overrides: Build-Time vs Post-Build (LOCKED 2026-04-10, refined 2026-04-11)

**Decision: Option B — post-build writes via `annotate_model_with_research()`** (matches Decision 2C integration mechanic). Keep `model_build()` unchanged. No formula gotchas in SIA template (Codex probed: no `IF`/`ISBLANK`/`IFERROR` patterns that would behave differently between initial blank and post-write override). Excel recalcs on file open; user-facing workbooks are fine.

**Critical caveat surfaced by Codex consult (thread 019d794e):** openpyxl does NOT recompute formulas on save. The model-engine reader at `financial-modeling-tools/schema/reader.py` falls back to cached values for some cases. **Post-annotation workbook numerics are NOT safe to trust server-side without an Excel recalc round-trip.**

**Architecture coherence review (Codex thread 019d7d6a) refined this further:** a server-side "smoke test on annotated-workbook readback" does NOT close the trust gap — the smoke test would read via the same cached-value path that the original concern flags. **No Phase 4 MVP mechanism can close the gap via openpyxl alone.** Closing the gap requires a headless Excel instance to force recalc, which is out of Phase 4 scope.

**Phase 4 safeguards to implement in `annotate_model_with_research()`:**
1. Set `fullCalcOnLoad=True` and `forceFullCalc=True` on workbook save (Excel will recalc when user opens)
2. Clear any model-engine cache after annotation runs (prevents stale reads from a session that ran pre-annotation)
3. **NO server-side readback smoke test.** It would provide false confidence.

**Invariant 10 (in architecture doc) is ADVISORY, not enforced:** "Post-annotation workbook numerics are NOT trusted server-side. The workbook is valid only once Excel opens it and recalculates." If Phase 4+ surfaces a genuine need for trusted server-side numerics (e.g., automated sanity-check against thesis valuation range), add a dedicated headless-Excel invocation tool — do not attempt to close the gap via openpyxl tricks.

**Document in the `annotate_model_with_research()` tool contract:** the tool returns `{model_path, annotated_at}`. Any downstream consumer that opens the workbook server-side to read numerical values is a bug. Enforced by code review, not code.

### Decision 4 — Diligence Checklist Sections (LOCKED 2026-04-10)

**Structure: 9 universal core sections + 1 dynamic Qualitative Factors extension section.** The 9 core sections are the universal baseline every name gets; qualitative factors are where different investment styles diverge.

#### Core sections (in narrative order)

| # | Section | Feeds report field(s) | Auto-populatable? | Tooling available |
|---|---|---|---|---|
| 1 | **Business Overview** | `company.sector`, `company.industry`, `business_overview.description`, `business_overview.segments[]` | Mostly | FMP profile, 10-K Item 1 via langextract |
| 2 | **Thesis** | `thesis.statement/direction/strategy/conviction/timeframe` | No | Agent drafts from exploration conversation only |
| 3 | **Catalysts & Timing** | `catalysts[]` | Partially | FMP events calendar, langextract `forward_guidance` |
| 4 | **Valuation** | `valuation.method/low/mid/high/current_multiple/rationale` | Partially | FMP multiples, `compare_peers` |
| 5 | **Assumptions** | `assumptions[]` (segment-qualified driver keys resolved via `driver_mapping.yaml`) | Partially | FMP historicals, langextract `forward_guidance` |
| 6 | **Risks** | `risks[]` | Yes | langextract `risk_factors` schema (already exists — 1 of 4 hardcoded) |
| 7 | **Peer Comps** | `peers[]` | Yes | FMP profile peers, `compare_peers` |
| 8 | **Ownership & Flow** | `ownership.institutional_pct/insider_pct/recent_activity` | Yes | `get_institutional_ownership`, `get_insider_trades` |
| 9 | **Monitoring** | `monitoring.watch_list[]` | Partially | Agent suggests based on thesis dependencies |

**Narrative flow**: What is this company? → Why interested? → Why now? → What's it worth? → What are we modeling? → What could go wrong? → How does it compare? → Who owns it? → What do we track?

#### Dynamic Qualitative Factors section

**Framing: extension mechanism, not overflow bucket.** Each investment style has its own "what to look at" list that extends the core 9 sections. The 9 core sections are the universal baseline; `qualitative_factors[]` is where style diverges.

**Seed category list** (free-form, users can add custom):

*Style-independent (useful across all strategies):*
- `street_view` — sell-side consensus, price targets, estimate trajectory, coverage sentiment
- `management_team` — tenure, track record, incentive alignment, bench depth
- `short_interest` — float short, days-to-cover, borrow rate, squeeze dynamics
- `earnings_view` — pre-earnings positioning, whisper estimates, IV percentile, post-earnings drift
- `financing` — debt maturity runway, credit facility access, refinancing setup
- `positioning` — institutional flow, hedge fund crowding, recent 13F activity
- `management_quality` — decision-making track record, capital discipline
- `competitive_moat` — barriers to entry, pricing power, customer switching costs
- `capital_structure` — debt profile, liquidity, rating, covenants
- `esg` — environmental/social/governance risks

*Style-scoped suggestions* (agent surfaces these based on `research_files.strategy`):

| Strategy | Typical factors |
|---|---|
| **value** | competitive_moat, capital_structure, management_quality, cyclicality, capital_allocation, book_value_quality |
| **special_situation** | catalyst_mechanics, activist_setup, financing_structure, deal_terms, arbitrage_spread, legal_risk |
| **macro** | macro_exposure, geographic_exposure, currency_exposure, regulatory_exposure, supply_chain, commodity_linkage |
| **compounder** | brand_strength, long_term_growth_drivers, management_quality, capital_allocation, tam_expansion, reinvestment_runway |

**Factor entry shape** (per Decision 2A qualitative_factors schema):
- `id` — integer, auto-assigned, stable identity for CRUD operations (scoped to artifact, tracked via `artifact.metadata.next_factor_id`)
- `category` — free-form identifier
- `label` — human-readable display (customizable per-name, e.g., `regulatory_exposure` → "Brazilian Mining Licensing")
- `assessment` — narrative markdown/text
- `rating` — optional `high`/`medium`/`low`
- `data` — optional schema-free JSON blob for structured attachments (short interest %, consensus PT, IV percentile, etc.)
- `source_refs` — citations into `sources[]`

**Factor data pullers** — ships in **Phase 3** (moved forward from Phase 4 because qualitative factors need data to be useful at creation time). Registry in ai-excel-addin: `fetch_data_for(category, ticker) -> {"data": {...}, "source_refs": [...]}`. Per-category functions that pre-populate `data` and `source_refs` during server-side pre-population orchestration. Each puller returns both a structured data blob and provenance entries. Start with 3 high-value pullers (short_interest, street_view, positioning), grow as needed. Phase 4 may extend with additional pullers if gaps are found.

#### Completion state model

`empty → draft → confirmed` per section. Drives `handoff.metadata.diligence_completion` field.

- Pre-populated by server-side orchestrator = `draft`
- User edit = still `draft`
- User clicks Confirm = `confirmed`
- **Finalization is never blocked on section state.** User can finalize with any combination of states. Real analysis is iterative; forcing completion creates rubber-stamp incentive.

#### Server-side pre-population flow

On diligence activation (or "Refresh Checklist" action):
1. Server-side orchestrator runs initial pull sequence **in parallel** (direct tool calls) across auto-populatable core sections (Business, Catalysts, Valuation, Assumptions, Risks, Peers, Ownership). Agent intelligence layers on in future phases.
2. For Qualitative Factors: pre-population orchestrator fetches `data` via registry for style-appropriate categories (based on `research_files.strategy`), lands as `draft` with data populated, narrative empty
3. Thesis + Monitoring start empty — require analyst judgment + thesis-dependent respectively
4. **Refresh semantics**: confirmed sections are sticky (preserved), draft sections are volatile (overwritten). User must explicitly click "Re-draft this section" to overwrite a confirmed section.
5. If user changes `research_files.strategy` after initial pull: agent prompts "You switched from value to special_situation — want me to suggest special situation factors?" Non-destructive; existing factors stay.

#### Qualitative Factors UI

- Section renders as a list, not a form
- "Add Factor" button opens modal with category picker: style-suggested at top → full seed list → custom option
- Each factor is editable in place: category, label, narrative assessment textarea, rating dropdown, optional data strip
- Data strip (if `data` is populated): rendered above the narrative as "22% short · 7 DTC · 15% borrow" style compact summary
- Agent suggestions surface inline: "I noticed the 10-K emphasized management tenure — want me to draft a `management_quality` factor?" → click accept = new draft factor
- No minimum count required

### Decision 5 — Multi-Ticker Themes + Schema Fix for Concurrent Theses (LOCKED 2026-04-10)

**Decision: Defer themes entirely (Option A).** Phase 1/2/3/4 do NOT add `research_themes` table or theme schema. Multi-ticker research is handled via tags + cross-links in artifacts until Phase 5 surfaces concrete theme-specific workflows (theme-level monitoring, theme-level outputs, dedicated theme UI). Don't front-load speculative schema for a feature that's 5 phases out.

**But Codex consult (thread 019d794e) caught a real Phase 1 schema bug:** `UNIQUE(ticker)` blocks multiple concurrent theses on the same name. This is MORE likely to bite than multi-ticker themes. Real scenarios:
- Long thesis + short thesis on the same name (pair trade)
- Core thesis + event-driven thesis ("VALE long-term value" vs "VALE pre-earnings")
- Value thesis + macro thesis (different analysis lenses by same analyst)

Each should be its own research file with its own exploration, diligence, and handoff.

**Schema fix — applied to Decision 1's `research_files` table:**

```sql
ticker TEXT NOT NULL,
label TEXT NOT NULL DEFAULT '',   -- disambiguator
UNIQUE(ticker, label)
```

**Semantics:**
- First file on a ticker: `label=''` → UI displays as just "VALE"
- Second file on the same ticker: UI prompts user for a label ("short thesis", "pre-earnings", etc.) → UI displays as "VALE — short thesis"
- Common case (single thesis per ticker) stays friction-free
- Multi-thesis case is opt-in via labeling
- Listing/filtering can group by ticker or show files flat

**Critical propagation fix — surfaced by architecture coherence review (Codex thread 019d7d6a, 2026-04-11):** the `label` column alone is NOT sufficient. All research *content* (threads, messages via thread FK, annotations, handoffs) must ALSO be keyed by `research_file_id` — NOT by `ticker`. Without this propagation, two concurrent theses on the same ticker would silently share threads, annotations, and prompt context, and the `label` would be cosmetic.

**Propagation applied:**
- `research_threads.research_file_id` (FK to research_files.id)
- `research_threads` partial unique indexes are `(research_file_id)` scoped — one explore and one panel thread PER FILE, not per ticker
- `research_messages.thread_id` FK inherits file scope transitively
- `annotations.research_file_id` (FK) — annotations belong to a specific file/thesis, not a ticker. The same filing passage annotated under two different theses on VALE creates two distinct annotation rows.
- `research_handoffs.research_file_id` (FK) is the lookup key; `research_handoffs.ticker` is a denormalized snapshot field only
- Chat context payload carries `research_file_id`, NOT `ticker`
- `build_research_context()` signature: `(user_id, research_file_id, thread_id, tab_context)` — no ticker parameter
- Bootstrap flow: upsert file FIRST to get `research_file_id`, then thread all subsequent calls through it
- Frontend state: `researchStore.activeFile.id` is what every downstream call uses; ticker is display-only

See `RESEARCH_WORKSPACE_ARCHITECTURE.md` Section 3 (Storage Topology) and Invariant 15 for the enforced form of this propagation.

**What's deferred to Phase 5:**
- `research_themes` table (if ever)
- Theme-scoped diligence sections
- Theme-level report aggregation
- "Brazil equities = 5 files" collection UX

**Out-of-scope signal:** If during Phase 2-4 we find theme-awareness would measurably improve the feature, revisit. Otherwise stay deferred.

### Decision 6 — Citation Precision: Hybrid with Snapshot Requirement (LOCKED 2026-04-10)

**Decision: Option C — hybrid.** Char offsets stay the stable, persisted reference in the annotation table. Paragraph numbers are **display sugar**, generated lazily at citation-render time from the filing's exact stored text. NEVER persist `para_id` as a first-class annotation field.

**Critical condition Codex consult (thread 019d794e) surfaced:** Paragraph numbering must derive from an **immutable filing text snapshot tied to `filing_id`**, not from whatever the latest re-ingested markdown happens to be. Two lookups against re-ingested filings can produce different paragraph numbers due to whitespace normalization, list formatting, section slicing, or table handling changes. There is no canonical SEC "paragraph 3" in the current tooling — char offsets are the only real identifier.

**Phase 2 annotation requirements:**

1. **`filing_id` must uniquely identify filing + ingest version.** Not generic "VALE_10K_2024" but content-hashed like `VALE_10K_2024_a3f8b2c1` (8-char hash suffix from file content).
2. **Filing files on disk are content-addressable.** The file at the stored `filing_id` path is the exact text the annotation was created against.
3. **Idempotency model:** Same content bytes → same SHA hash → same filing_id (idempotent). Different normalization of the same SEC filing → different content bytes → different hash → different filing_id. Both old and new versions coexist. The filing_id includes a content hash, so identical content always produces the identical filing_id. Old annotations continue pointing at their original filing version.
4. **Citation render time:** load exact filing text from stored `filing_id` path, find `char_start` position, count paragraphs before it using the deterministic split rule → "Item 7, para 3".

**Deterministic paragraph split rule** (locked for consistent rendering):
- Normalize newlines (CRLF → LF)
- Preserve whitespace-filled tables as today (char offsets depend on this — see Inv-B finding on `strip_table_blocks()`)
- Split on `\n\n+` (2+ consecutive newlines)
- Treat bullet/numbered list runs as one paragraph
- Treat figure/table captions as one paragraph

**Phase 2 filing ingest scope add:** filing output file naming convention changes to include content hash suffix. Existing `get_filing_sections()` pipeline in `edgar-mcp` / `AI-excel-addin/mcp_servers/langextract_mcp/text_utils.py` needs a small rename step at output time. Low effort, high leverage.

**Strong Codex pushback:** Do NOT invest in paragraph-level addressing as stored identifiers. It creates false precision and migration pain for little product value.

### Decision 7 — Phase 2 Langextract Schemas Scope (LOCKED 2026-04-10)

**Decision: Option B — author 3 new schemas as part of Phase 2 scope.** Ship Phase 2 with 7 total extraction schemas (4 existing + 3 new).

**Overrode original lean** (ship with 4, iterate). Codex consult (thread 019d794e) pushed back: the compounding cost is product quality, not platform debt. Phase 3 qualitative pre-population with only `risk_factors` / `forward_guidance` / `capital_allocation` / `liquidity_leverage` would feel "mechanically narrow and downside-biased" — bad first impression for the feature.

**Phase 2 scope add — 3 new langextract schemas:**
1. **`management_commentary`** — feeds qualitative factors `management_team`, `management_quality`. Extracts management tone, capital discipline signals, operational track record references, succession/bench depth mentions.
2. **`competitive_positioning`** — feeds qualitative factor `competitive_moat`. Extracts barriers to entry, pricing power claims, customer switching costs, market share commentary, moat references.
3. **`segment_discussion`** — feeds Business Overview section. Extracts segment revenue/margin breakdowns, segment-level commentary, product mix shifts, geographic segmentation.

**Deferred to Phase 3+ (wait for concrete workflow gaps):**
- `valuation_signals` — mgmt-stated book value, guidance multiples, intrinsic value commentary
- `capital_structure_detail` — more granular than `liquidity_leverage` for detailed debt/capital analysis

**Rejected options:**
- **Option C** (author all 5-6 schemas now): too much speculative authoring
- **Option D** (data-driven schemas via YAML/JSON): premature — needs validation infrastructure, versioning, evals, likely non-engineer authorship first. Just moves complexity out of Python and makes debugging worse. Revisit when schema library grows to 10+.

**Schema authoring pattern:** add new dataclasses to `AI-excel-addin/mcp_servers/langextract_mcp/schemas.py` following the existing pattern. Each new schema is ~100-200 lines (extraction classes + attribute definitions + prompt guidance).

---

## Planning Order (Remaining Work)

All architectural decisions locked. Remaining work is phase spec drafting + implementation.

1. ~~**Re-review Phase 1 plan**~~ — **DONE.** `RESEARCH_WORKSPACE_PHASE1_PLAN_V5.md` Codex PASS R15 (14 review rounds). v4 fully superseded.
2. **Phase 2 plan** — `docs/planning/completed/RESEARCH_WORKSPACE_PHASE2_PLAN.md`. Covers: reading surface (document tabs for filings + transcripts), annotation schema + UI, text-selection → agent panel plumbing, agent highlights from langextract extractions, 3 new langextract schemas (`management_commentary`, `competitive_positioning`, `segment_discussion`), filing_id content-hash versioning, deterministic paragraph split rule.
3. **Phase 3 plan** — `docs/planning/completed/RESEARCH_WORKSPACE_PHASE3_PLAN.md`. Covers: diligence checklist UI (9 core sections + dynamic Qualitative Factors), per-section state model, server-side parallel data pull (direct tool calls, not agent-mediated), style-aware qualitative factor suggestion, `fetch_data_for(category, ticker)` data puller registry.
4. **Phase 4 plan** — `docs/planning/completed/RESEARCH_WORKSPACE_PHASE4_PLAN.md`. Covers: `research_handoffs` table schema + lifecycle, artifact shape implementation, `annotate_model_with_research()` MCP tool design (with workbook recalc safeguards per Decision 3), SIA template driver-name → cell-address mapping, optional JSON export flow, "Finalize Report" UX.
5. **Phase 5: deferred (scope doc TBD).** Captures deferred items (multi-ticker themes, langextract valuation_signals/capital_structure_detail schemas, bidirectional analyst-memory sync, web search integration, PDF/markdown export) without over-designing.
6. **Ship Phase 1 implementation** — backend-first per `RESEARCH_WORKSPACE_PHASE1_PLAN_V5.md` dependency batches (12 steps, 6 batches, ~68 tests). Implementation in progress.
7. **Ship Phase 2** — reading surface + annotations + 3 new langextract schemas.
8. **Ship Phase 3** — diligence checklist + qualitative factor UI + data pullers.
9. **Ship Phase 4** — report finalization + `annotate_model_with_research()` tool.
