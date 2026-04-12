# Equity Research Workspace — Product Spec
**Status:** PRODUCT SPEC (design + interaction model). Architecture sections superseded — see note below.
**Eng review:** 2026-04-03. Codex outside voice ran.
**Date:** 2026-04-03
**TODO ref:** Group 5
**Design preview:** `~/.gstack/projects/henrysouchien-risk_module/designs/research-workspace-20260403/research-workspace-preview.html`

> **⚠ ARCHITECTURE SUPERSEDED:** Several sections below reflect the 2026-04-03 eng review draft and were superseded by the locked architecture (2026-04-10+) after 4 Codex consult rounds and 3 storage pivots. **Superseded sections:**
>
> - §"Persistence Model" (storage, sync layer, communication paths)
> - §"Standard Template" (diligence checklist — 12 sections)
> - §"Eng Review Findings" (architecture evolution + "Final architecture" — reflects Pivot 3 hybrid model, NOT the locked per-user-everything model)
> - §"Phasing" (per-phase feature lists — detailed scope is now in the Phase 1 Plan v5; spec-level phasing is directionally correct but not binding for exact feature boundaries)
>
> **What changed:**
> - **Storage:** All research state now lives in per-user SQLite at `data/users/{user_id}/research.db` — NO Postgres research tables, no sync layer, no hybrid model. See `RESEARCH_WORKSPACE_ARCHITECTURE.md` §3 and `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` Decision 1.
> - **Identity:** Content keyed by `research_file_id` (not `ticker`), with `label` column for multi-thesis support. See Decision 5.
> - **Diligence:** 9 universal core sections + dynamic Qualitative Factors extension mechanism (not the 12-section template below). See Decision 4.
> - **Tool access:** Agent has FULL tool surface on research turns (memory, sub-agents, everything) — per-user physical isolation eliminates contamination. See Decision 1 + Invariant 2.
> - **Phase 1 scope:** Detailed Phase 1 scope (including what's deferred, e.g., stage-filter UI) is defined in the Phase 1 Plan v5, not this spec.
>
> **For current architecture, read these docs (in order):**
> 1. `RESEARCH_WORKSPACE_ARCHITECTURE.md` — locked system frame
> 2. `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` — 7 locked decisions
> 3. `RESEARCH_WORKSPACE_PHASE1_PLAN_V5.md` — implementation plan (binding for Phase 1 scope)
>
> **This spec remains authoritative for:** product vision, design principles, interaction model (§"What This Is" through §"Agent Interaction Model"), design patterns (§"New Design Patterns"), and open questions (§"Open Questions").

---

## What This Is

An IDE for equity research. Two-pane layout: a reader for source documents and exploration, and an agent panel where your AI analyst is always available. Tabs organize your work — threads emerge as you explore, documents open when you want to read, and a diligence checklist activates when you have a thesis to stress-test.

**The analogy:** Cursor is an IDE where you read code with an AI agent beside you. This is the same thing for investment research — you read filings, transcripts, and financials with an AI analyst beside you. The agent finds, extracts, computes, surfaces patterns. You read, interpret, notice what the agent misses, form judgment. Both contribute what they're best at.

**Why a reading surface matters:** Most AI investment tools give you summaries. This workspace lets you read primary sources with the AI as a reading companion. The agent does the finding and extracting. You do the reading and interpreting. There are things you'll notice from reading a filing that the agent will summarize away — tone, emphasis, what management didn't say, patterns that require domain expertise. Without a reading surface, there's nothing to look at, which is detrimental to your own learning and judgment.

**The flow:**

```
Explore → Discover → Form thesis → Stress test thesis (diligence checklist) → Report
```

Not: "fill in a checklist." The checklist is a later-stage verification tool, not the primary workspace.

**What it replaces:** The 5-tab workflow — broker app for positions, Yahoo Finance for fundamentals, SEC.gov for filings, a notes app for your thesis, ChatGPT for "summarize this earnings call." All of that lives in one place with persistent context.

**What it produces:** Repeatable research reports. When diligence is complete, the workspace generates a structured research report — thesis, key findings per section, risks, conviction, recommendation. This is the artifact that justifies a position. It's also what you review when monitoring an existing holding ("what was my thesis? has anything changed?").

---

## Design Principles

The research workspace introduces a **fourth interaction mode** to the product:

| Mode | Description | Existing examples |
|------|-------------|-------------------|
| 1. Analyst's unprompted report | Dashboard views. The analyst did the work before you arrived. | Overview, Holdings, Performance, Risk |
| 2. Analyst answering questions | Scenario tools. You ask, the analyst runs analysis and presents findings. | Stress test, Optimization, What-if, Monte Carlo |
| 3. "Tell me more" | AI chat. Escape hatch from any view into direct conversation. | Chat margin |
| **4. Working together** | **Research workspace. Neither of you has figured it out yet. You're both learning.** | **New** |

In mode 4, the analyst doesn't have the final answer. Content accumulates over days/weeks. Your notes, questions, and reactions are as important as the agent's data pulls. The hierarchy between you and the agent is flat — you're peers in this workspace.

From DESIGN.md, these patterns carry over:
- **Insight first, evidence second.** The opening take still applies when there's enough data to synthesize.
- **Every result leads somewhere.** Exit ramps from research into action (size a position, stress test, what-if).
- **The AI is everywhere.** The agent panel is always present, always contextual.
- **Density is a feature.** Financial data in monospace, tight spacing, no whitespace for its own sake.

What's new:
- **Flat hierarchy between voices.** Both you and the agent at 13px. Agent contributions have a gold left rail. Your notes have a dim left rail. Peers, not analyst-dominant.
- **The reading surface.** Source documents at full readable width (14-15px Instrument Sans). You're the analyst here — you read, the agent assists.
- **Threads emerge from exploration.** Not imposed upfront. You create structure as interesting topics crystallize.

---

## Architecture: The Two-Pane Layout

```
┌──────────────────────────────────────────────┬────────────────┐
│ APRIL 3, 2026 · VALE SA · EXPLORING         │                │
├──────────────────────────────────────────────┤  AGENT PANEL   │
│ Explore · Ownership · 10-K §2.1 · +         │                │
├──────────────────────────────────────────────┤  Conversation  │
│                                              │  contextual to │
│              READER AREA                     │  active tab.   │
│                                              │                │
│  Shows whatever tab is active:               │  You ask,      │
│  - Explore (conversation feed)               │  agent         │
│  - A thread (Ownership, Valuation...)        │  responds.     │
│  - A document (filing, transcript...)        │                │
│                                              │  Agent flags   │
│                                              │  things it     │
│                                              │  noticed.      │
├──────────────────────────────────────────────┤                │
│ [Size position] [Stress test] [What-if]      │  [input]       │
└──────────────────────────────────────────────┴────────────────┘
```

### Zone 1: Reader (main area)

The "editor pane." Shows whatever tab is active.

**Tab bar** at the top:
- "Explore" tab is always present (can't close). The main conversation/exploration feed.
- Thread tabs appear as you create them: "Ownership", "Valuation", "Mgmt Quality"
- Document tabs appear when you open a source: "10-K §2.1", "Q4 Transcript", "Insider Trades"
- "+" button to manually create a thread
- Styling: Geist Mono 11px, letter-spacing 0.04em. Active tab: `--text` + 2px bottom border in `--accent`. Inactive: `--text-muted`. Close (×) on thread/document tabs.

**Three types of tabs:**

#### Explore Tab (conversation mode)
The default. A conversation feed where you and the agent explore freely.
- Your messages: Instrument Sans 13px, `--text`, left-aligned
- Agent responses: Instrument Sans 13px, `--ink`, with 1px `--accent` left rail (same provenance mark as Canvas generated artifacts)
- Inline data: when agent surfaces metrics, tables, charts, they appear richly formatted using existing component patterns (metric strips, factor bars, comparison tables)
- "Open in tab →" on substantial content (filing sections, full transcripts) to read properly
- "Start thread →" on interesting exchanges to branch a topic
- Input at the bottom of the reader area

#### Thread Tabs
A focused workspace on one dimension. Contains all content related to that topic.
- **Pinned finding** at the top (when you've concluded something): `--surface-raised`, 14px Instrument Sans, `--ink`. Your conclusion.
- Below: accumulated content. Conversation exchanges, data, documents, your notes. Chronological.
- Agent contributions: 1px `--accent` left rail
- Your notes: 1px `--text-dim` left rail (the two-author distinction)
- Both at 13px. Peers.
- Collapsible earlier content: "5 earlier exchanges · See full thread"

#### Document Tabs (reading mode)
Source documents at full readable width. This is where the product becomes genuinely different from "ChatGPT with financial data."
- Filing sections: prose at 14-15px Instrument Sans, `--ink`. Readable, not summarized.
- Earnings transcripts: speaker labels in Geist Mono 10px uppercase, dialogue in 14px Instrument Sans. Q&A sections clearly delineated.
- Financial statements: tables in Geist Mono, using existing data table patterns.
- **Agent highlights:** passages the agent flagged with subtle `--accent-dim` background + annotation note
- **Your highlights:** select text, add a note. `--surface-2` background + annotation with `--text-dim` left rail.
- "Ask about this" prompt appears in the agent panel when you select text.

### Zone 2: Agent Panel (right, ~280px)

The "Copilot." Same width as the existing chat margin.
- **Always visible.** The analyst is always here.
- **Contextual.** Knows which tab you're on, what you're reading. If you're in the 10-K, responses are about the 10-K.
- **Conversation persists** per research file. Come back next week, the thread is there.
- Agent responses can include small data (inline metrics, mini charts — margin sketch constraints from DESIGN.md apply: 248px usable, 100-140px plot height, 2 series max)
- "Open in reader →" on anything substantial
- Input at the bottom
- Header shows context: `RESEARCH ANALYST · Exploring · VALE SA` or `Reading · 10-K §2.1`

### Exit Ramps

Bottom of the reader area. Context-dependent, using existing exit ramp pattern (gold arrows).

| Exit Ramp | Target Tool | Context Passed |
|-----------|-------------|---------------|
| Size a position | What-If | Ticker, suggested weight range |
| Stress test | Stress Test | Ticker added to portfolio, relevant scenario |
| Simulate forward | Monte Carlo | Portfolio + new position |
| Compare to holdings | Peer Comparison | Ticker vs existing portfolio peers |
| Generate trades | Trading | Ticker, direction, suggested size |
| Form thesis | Diligence tab | Activates the checklist |
| Generate report | Report generator | Compiles threads + diligence into polished output |

---

## The Exploration Flow

### Three modes that blend

1. **Conversation** — the entry point. Easiest way to start. "Tell me about VALE." "What's the ownership situation?" Just talking to the analyst in the Explore tab.

2. **Reading** — sometimes you want to look at a primary source yourself. A filing section, a transcript, the financials. The agent surfaces it or you search for it. Opens as a document tab. You read at full width, the agent is your reading companion in the panel.

3. **Threads emerge** — as conversation and reading happen, interesting topics crystallize. "The ownership story is interesting." "Management's capex guidance is worth tracking." These become named thread tabs you can return to next week.

These aren't sequential stages. They blend. You're having a conversation, pull up a filing to read, have a conversation about what you just read, and that discussion naturally becomes a thread about "regulatory risk."

### How threads form

From the Explore tab:
- You notice an interesting exchange → "Start thread →" pulls it into a new named tab
- You manually create a thread via the "+" button
- The agent suggests a thread: "This ownership investigation is getting substantial — want me to start a thread?"

From a document tab:
- You're reading the 10-K, find something important → "Start thread: Environmental liability →"
- The thread captures the document reference, your highlight, and the context

Within a thread:
- Content accumulates: conversation exchanges, data pulls, your notes, document references
- When you reach a conclusion, pin it as a finding at the top
- The finding feeds into the opening take and eventual research report

---

## The Diligence Checklist

Activates when you form a thesis. Appears as a special tab ("Diligence").

The checklist is a **stress test for the thesis**, not the primary workspace. It's structured and systematic — the analyst walks you through each dimension to verify the thesis holds.

### Standard Template

| # | Section | Data Sources | Purpose |
|---|---------|-------------|---------|
| 1 | Company Overview | `fmp_profile`, `get_stock_fundamentals` | Baseline context |
| 2 | Valuation | `fmp_fetch(key_metrics, ratios_ttm)` | Does the price make sense? |
| 3 | Estimates & Revisions | `get_estimate_revisions`, `fmp_fetch(analyst_estimates)` | Is the Street moving with or against you? |
| 4 | Earnings Quality | `get_earnings_transcript`, financials | Is the business actually performing? |
| 5 | Ownership & Flow | `get_institutional_ownership`, `get_insider_trades` | Who's buying/selling and why? |
| 6 | Technical & Price | `get_technical_analysis` | Is the timing right? |
| 7 | Risk Profile | `analyze_stock`, factor exposures | What factors drive this? |
| 8 | Portfolio Fit | `run_whatif`, `get_risk_analysis` | How does it change your portfolio? |
| 9 | Catalysts & Events | `get_events_calendar`, `get_news` | What's the trigger? |
| 10 | Filings & Disclosures | `langextract`, `sec_filings` | What's in the fine print? |
| 11 | Peer Context | `compare_peers`, `get_sector_overview` | How does it rank? |
| 12 | Thesis & Decision | (user-driven) | Your thesis, conviction, sizing |

### Checklist behavior

- Agent pre-populates sections 1-9 when diligence activates
- Each checklist item can link to exploration threads: "See Ownership thread"
- Checklist items can reference documents: "See 10-K §2.1"
- Uses the analyst's TOC pattern: named section breaks, progress indicators, finding summaries
- Agent panel shifts to systematic mode: walks through each section

### Checklist → Report

When the checklist is complete (or enough sections are concluded), "Generate research report" produces a polished, read-only document following the analyst report pattern from DESIGN.md: insight section, named section breaks, data evidence, exit ramps.

---

## The Research File (data model)

A research file is the central object. One per name (or theme).

### Identity
- **Ticker** (or theme slug for macro ideas like "MACRO_BRAZIL_EQUITIES")
- **Company name** / theme title
- **Created date**, **last updated**
- **Process stage**: Exploring → Has Thesis → Diligence → Decision → Monitoring → Closed
- **Direction**: Long / Short / Hedge / Pair
- **Strategy**: Value / Special Situation / Macro / Compounder
- **Conviction**: 1-5

### Content
- **Explore conversation** — the main exploration feed, persisted
- **Threads** — named, each with their own conversation + notes + finding
- **Document references** — pointers to filings, transcripts, with highlights and annotations
- **Diligence checklist state** — per-section status, agent snapshots, findings
- **Opening take** — agent-generated synthesis, updated on demand

---

## Persistence Model

**Hybrid: Postgres (metadata) + ai-excel-addin SQLite (content).**

Two stores, clearly separated by concern. No data duplication.

### Postgres (risk_module) — Research file metadata

Lightweight product data for listing, filtering, sorting. No agent needed.

```sql
research_files
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ticker VARCHAR(20) NOT NULL,
  company_name VARCHAR(200),
  stage VARCHAR(20) DEFAULT 'exploring',  -- exploring, has_thesis, diligence, decision, monitoring, closed
  direction VARCHAR(10),                  -- long, short, hedge, pair
  strategy VARCHAR(20),                   -- value, special_situation, macro, compounder
  conviction INTEGER,                     -- 1-5
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, ticker)
```

### ai-excel-addin SQLite (extended) — Conversation content

Agent-native storage for messages, threads, context assembly. Extended with 2 new tables.

```sql
research_threads
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,              -- links to research_files conceptually (synced via ticker)
  name TEXT NOT NULL,
  finding_summary TEXT,              -- pinned finding (nullable)
  is_explore INTEGER DEFAULT 0,     -- one per ticker
  is_panel INTEGER DEFAULT 0,       -- one per ticker
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL

research_messages
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES research_threads(id) ON DELETE CASCADE,
  author TEXT NOT NULL,              -- 'user' or 'agent'
  content TEXT NOT NULL,
  content_type TEXT DEFAULT 'message',  -- 'message', 'note', 'tool_call', 'artifact'
  tab_context TEXT,                  -- active tab when sent (for panel thread)
  metadata TEXT,                     -- JSON: tool call refs, artifact IDs, source tags, error states
  created_at REAL NOT NULL
```

### What's reused from ai-excel-addin (no changes)

| Component | How research workspace uses it |
|-----------|-------------------------------|
| `memories` table | Ticker knowledge (thesis, conviction, findings). Agent reads/writes. Source of truth synced to Postgres research_files. |
| `chunks` + `embeddings` | Search across all research content. Messages indexed as chunks for FTS/semantic search. |
| `workspace/tickers/*.md` | Markdown sync. Pinned findings flow to ticker files via `store_memory()`. |
| Daily notes | Agent continues writing session summaries. |
| Compaction | LLM context summarization at 160K tokens. Persistent transcript means you don't lose history. |
| Ingestion pipeline | Screener results → ticker files → research workspace can seed from them. |

### Sync layer (Phase 1)

Lightweight metadata sync between the two stores:
- **Postgres → Agent memories:** When UI updates stage/conviction, sync to `memories` table so agent knows.
- **Agent memories → Postgres:** When agent updates conviction/stage during research, sync to `research_files` so list view reflects it.
- Messages and conversation content are NOT synced — they live only in ai-excel-addin SQLite.

### Communication paths

```
Frontend → risk_module Postgres      (list/filter research files)
Frontend → Gateway → Agent instance  (conversation: send/receive messages)
Agent    → risk_module API           (update research_files metadata)
Agent    → own SQLite                (messages, memories, chunks — direct access)
```

### No data snapshots stored

Data comes from live MCP tool calls. Messages capture the agent's text summary with source tags (e.g., "Source: FMP key_metrics, 2026-04-03"). The conversation transcript with timestamps IS the audit trail. Agent re-fetches live data when needed.

### Connection to existing systems

```
Screener → Ingestion → ticker memory (existing SQLite)
                              ↑↓ (agent reads/writes)
                        Research Workspace
                        ├── Metadata: Postgres (multi-user list)
                        └── Content: SQLite (agent-native messages)
                              ↓ (exit ramp)
                        risk_module scenario tools
                              ↓
                        Position sizing / trading / monitoring
```

---

## Agent Interaction Model

The agent is a research partner. It operates in two modes simultaneously:

### Agent Panel (always-on)
- Contextual to the active tab
- Responds to questions, surfaces data, flags notable items
- Can include small visualizations (margin sketch constraints)
- Suggests threads, offers to dig deeper, cross-references across threads

### Agent capabilities
1. **Pull data** — any FMP endpoint, portfolio tools, estimates, etc.
2. **Search** — find passages in filings, transcripts, news (via langextract, FMP, web search)
3. **Synthesize** — generate opening take, build bull/bear case, summarize threads
4. **Flag** — highlight notable items (estimate revision acceleration, insider cluster, valuation extreme, new risk factors in filings)
5. **Compute** — quick calculations (FCF at different prices, margin scenarios, growth math)
6. **Compare** — cross-reference research files, run peer screens
7. **Annotate documents** — highlight passages in source documents with notes

### Agent cannot
1. Change your notes or findings — your annotations are yours
2. Change conviction/stage — you drive the process
3. Pin findings — you decide when a thread is concluded
4. Auto-advance diligence — you decide when a section is done

---

## New Design Patterns (additions to DESIGN.md)

Three new patterns needed beyond the existing design system:

### 1. Tab Bar
IDE-style tabs in the reader area. Lightweight navigation between exploration, threads, and documents.
- Geist Mono 11px, letter-spacing 0.04em
- Active: `--text` + 2px bottom border in `--accent`
- Inactive: `--text-muted`
- Close (×) on closeable tabs
- "+" for new thread creation

### 2. Two-Author Distinction
Flat hierarchy with authorship signals (not size hierarchy).
- Agent contributions: 1px `--accent` left rail (gold — analyst provenance)
- Your contributions: 1px `--text-dim` left rail (cool — different hand)
- Both at 13px Instrument Sans. Same weight. Different rail color.
- Exception: opening take stays at 20px in `--surface-raised` (insight section pattern)
- Exception: pinned findings at 14px in `--surface-raised` (your conclusion)

### 3. Document Reading Mode
Source documents at readable prose size with collaborative annotation.
- Filing prose: 14-15px Instrument Sans, `--ink`, max-width 640px
- Transcript: speaker labels in Geist Mono 10px uppercase, dialogue in 14px Instrument Sans
- Agent highlights: `--accent-dim` background + `--accent` annotation note
- Your highlights: `--surface-2` background + `--text-dim` left rail annotation
- "Ask about this" in agent panel on text selection

---

## Phasing

### Phase 1: Two-Pane Layout + Exploration (MVP)
- Research list view (create, list, filter by stage)
- Two-pane layout: reader + agent panel
- Explore tab with conversation feed
- Thread creation from conversation ("Start thread →")
- Agent panel with contextual conversation
- Basic persistence (research_files, threads, messages)
- Navigation: `#research/VALE` deep links

### Phase 2: Document Reading + Annotation
- Document tabs: filing sections via langextract, earnings transcripts, financial statements
- Agent document highlights (flag new/notable passages)
- User text selection + annotation
- "Ask about this" from document → agent panel
- Transcript search (find what management said about X)

### Phase 3: Diligence Checklist + Synthesis
- Diligence tab activates when thesis forms
- Agent pre-populates checklist sections 1-9
- Checklist links to threads and documents
- Opening take synthesis from threads + diligence
- Flagging system (notable items surface in opening take)

### Phase 4: Report Generation + Exit Ramps
- Research report generation from threads + diligence
- Exit ramps to scenario tools with research context
- Research file comparison (side-by-side two names)
- Conviction/decision log with history tracking

### Phase 5: Advanced
- Web search integration (investor decks, industry context)
- Custom diligence sections per name
- Per-strategy templates (Value vs Macro vs Special Situation)
- Multi-ticker theme research (e.g., "Brazil equities" = 5 names)
- Connection to idea ingestion pipeline
- Bidirectional sync with analyst-claude ticker memory
- PDF/markdown report export

---

## Open Questions

1. ~~**Explore tab input**~~ — **RESOLVED** (eng review decision #4 + Phase 1 Plan v5): Both inputs active when Explore tab is active (reader sends to explore thread, panel sends to panel thread). When a Thread or Document tab is active, reader has NO input (read-only); agent panel is the sole conversation channel (sends to panel thread with `tab_context` pointing to the active reader tab). Agent panel input is always present.
2. **Thread-to-diligence mapping** — when diligence activates, should exploration threads auto-map to checklist sections? ("Ownership" thread → Ownership & Flow section)
3. **Multi-ticker research** — some research is comparative (Brazil equities = 5 names). Support research files for themes/baskets, or keep it single-ticker with a comparison feature?
4. **Collaboration with analyst-claude** — the ticker memory workspace in ai-excel-addin has its own research state. Should research files sync bidirectionally?
5. **Reading surface scope** — how much of langextract/EDGAR integration needs to be built vs. already exists? What's the gap between "agent can extract filing sections" and "filing sections rendered in a document tab"?

---

## Eng Review Findings (2026-04-03, paused)

### Architecture decisions (accepted)
1. **Scope existing chat infrastructure** for agent panel (not a separate system)
2. **Dedicated researchStore** (Zustand) for frontend tab/UI state
3. **Stock lookup folds into Explore tab** (not a separate view)
4. **Context-dependent input** — reader input on Explore tab, agent panel input elsewhere
5. **Two conversation streams, shared context** — explore conversation + agent panel, but agent sees full research file context from both
6. **One agent panel thread with tab context tags** — single panel stream, messages tagged with active tab at send time

### Architecture evolution (3 pivots during review)

**Pivot 1:** 6 Postgres tables → extend ai-excel-addin SQLite (integrate, don't build parallel)
**Pivot 2:** All-SQLite → Postgres for metadata (multi-user is a first-order goal)
**Pivot 3:** Single store → hybrid (Postgres metadata + SQLite content, API boundary)

Final architecture:
1. **Postgres** (risk_module): `research_files` table with user_id — metadata for listing/filtering
2. **ai-excel-addin SQLite** (extended): `research_threads` + `research_messages` — conversation content, agent-native
3. **Sync layer**: lightweight metadata sync (stage, conviction) between Postgres and agent memories
4. **API boundary**: frontend → Postgres for lists, frontend → gateway → agent for conversation
5. **No data snapshots**: messages with source tags ARE the audit trail. Agent re-fetches live data.
6. **Message schema extensible**: metadata JSON column in ai-excel-addin for tool calls, artifacts, etc.

### Codex outside voice (9 findings, 4 substantive tensions resolved)
1. **Storage boundary** — resolved: hybrid Postgres + SQLite with API boundary
2. **Communication path** — resolved: gateway routes to per-user agent, REST API for metadata
3. **Chat scoping understated** — acknowledged: new chat/session architecture needed, not small adaptation
4. **Gateway contract** — acknowledged: needs protocol updates for multi-thread research context
5. **Frontend state model** — acknowledged: IDE tabs cut across existing routing/state (captured in impl plan)
6. **Message schema primitive** — resolved: metadata JSON column + ai-excel-addin native schema
7. **Research integrity** — resolved: messages with timestamps + source tags = audit trail
8. **Phase ordering** — resolved: backend-first sequencing, then UI layer
9. **Tier gating** — noted: access policy for agent panel is Phase 1 dependency

---

## References

- **TODO Group 5**: Equity Research Workspace (docs/TODO.md)
- **Idea Ingestion System**: docs/planning/IDEA_INGESTION_SYSTEM_DESIGN.md
- **Investment Planning System**: docs/planning/INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md
- **Portfolio Strategy Workflow**: docs/planning/strategy/PORTFOLIO_STRATEGY_WORKFLOW.md
- **DESIGN.md**: Product identity, design principles, scenario tool patterns
- **Design preview**: `~/.gstack/projects/henrysouchien-risk_module/designs/research-workspace-20260403/research-workspace-preview.html`
- **Design consultation**: 2026-04-03, converged on "IDE for equity research" model through iterative discussion
