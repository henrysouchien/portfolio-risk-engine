---
status: in-progress
branch: main
timestamp: 2026-04-04T08:09:45+08:00
session_duration_s: ~21600
files_modified:
  - docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md
  - docs/TODO.md
  - docs/planning/strategy/PORTFOLIO_STRATEGY_WORKFLOW.md
  - DESIGN.md
---

## Working on: Research Workspace Spec + Architecture

### Summary

Designed the Equity Research Workspace from scratch: product spec, design consultation, and full eng review with Codex outside voice. The workspace is an "IDE for equity research" with a two-pane layout (reader + agent panel) and IDE-style tabs. Started as a checklist-driven tool, evolved through design consultation to a collaborative exploration surface, then had the storage architecture completely reworked through the eng review (3 pivots: all-Postgres → all-SQLite → hybrid).

### Decisions Made

**Product / Design:**
- Research workspace is a 4th interaction mode: "working together" (not analyst report, not Q&A, not chat)
- Two-pane layout: reader (main) + agent panel (280px right), inspired by Cursor IDE
- IDE-style tabs at top of reader: Explore (always open), threads (emerge from exploration), documents (filing sections, transcripts)
- Flat voice hierarchy within workspace: agent gold left rail, user dim left rail, both 13px
- The workspace PRODUCES a report, it ISN'T one. Exploration → discovery → thesis → diligence checklist → report
- Reading surface is the differentiator: render primary sources at full width, not just summaries
- Stock lookup folds into the Explore tab (not a separate view)
- Context-dependent input: reader input on Explore tab, agent panel input elsewhere
- Two conversation streams (explore + panel), shared context, one panel thread with tab context tags
- Agent panel role adapts: context sidebar when reader is conversational, conversation channel when reader is content
- Research workspace is a paid-tier feature
- Diligence checklist is a later-stage stress test for a thesis, not the primary workspace

**Architecture (final, after 3 pivots):**
- **Hybrid storage**: Postgres (risk_module) for research_files metadata + ai-excel-addin SQLite for conversation content
- Postgres: `research_files` table (user_id, ticker, stage, conviction, direction, strategy) — for listing/filtering
- ai-excel-addin SQLite: `research_threads` + `research_messages` tables — conversation content, agent-native
- Reuses existing: memories (EAV ticker knowledge), chunks + embeddings (search), markdown sync, workspace, compaction
- Lightweight metadata sync between Postgres research_files and agent memories (stage, conviction)
- API boundary between repos: frontend → Postgres for lists, frontend → gateway → agent for conversation
- ai-excel-addin runtime assembles LLM context (existing memory injection + new research context layer)
- No data snapshots stored. Messages with source tags ARE the audit trail. Agent re-fetches live data via MCP.
- Message schema: extensible metadata JSON column in ai-excel-addin for tool calls, artifacts, etc.
- Backend-first sequencing for Phase 1 (integration layer before UI)

**Eng review findings (Codex outside voice, 9 findings):**
- Storage boundary: resolved via hybrid Postgres + SQLite
- Communication path: resolved via gateway routing + REST API
- Chat scoping understated: acknowledged, new chat/session architecture needed
- Gateway contract needs protocol updates for multi-thread research
- Frontend state model: IDE tabs cut across existing routing (captured for impl plan)
- Message schema: resolved via metadata JSON + ai-excel-addin native schema
- Research integrity: resolved via messages as audit trail with source tags
- Phase ordering: resolved via backend-first sequencing
- Tier gating: decided, research workspace is paid feature

### Remaining Work

1. **Write Phase 1 implementation plan** — backend pre-reqs (Postgres migration, REST endpoints, gateway protocol extension), ai-excel-addin extensions (message schema, thread tables, context injection), frontend (two-pane layout, tabs, researchStore, agent panel)
2. **Codex review on implementation plan** — before any code
3. **Gateway protocol extension design** — TODO: multi-thread research context, resumable threads, tab-scoped panel
4. **ai-excel-addin message schema design** — TODO: examine current agent message flow, design research_messages + research_threads tables to fit
5. **Implement Phase 1** — backend-first, then frontend
6. **Phase 2+** — document reading (langextract), annotation, diligence checklist, report generation

### Notes

- The ai-excel-addin repo is at `/Users/henrychien/Documents/Jupyter/AI-excel-addin/`
- analyst_memory.db is 367MB, 2,101 memories, 7,605 chunks, 201 ticker files
- The ai-excel-addin memory store uses entity/attribute/value pattern, NOT relational message storage
- "Compaction" is LLM context window summarization at 160K tokens, not database compaction
- "Session notes" are agent-written daily .md files, not automated code
- No individual message persistence exists yet in either repo — this is the primary gap
- The existing ChatProvider/usePortfolioChat is one app-wide in-memory conversation — extending to multi-thread is a new chat architecture, not a small adaptation
- Design preview HTML at: `~/.gstack/projects/henrysouchien-risk_module/designs/research-workspace-20260403/research-workspace-preview.html`
- Spec file: `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md`
- DESIGN.md updated with Research Workspace section + 5 decision log entries
- TODO.md updated with Group 5 status
- Working tree is clean — all changes committed in `8b9f6418` and `9faec439`
