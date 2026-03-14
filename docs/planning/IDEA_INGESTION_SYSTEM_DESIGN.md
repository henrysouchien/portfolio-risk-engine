# Design: Investment Idea Ingestion System
**Status:** ACTIVE

## Context

Analyst-claude (in AI-excel-addin) already maintains per-ticker markdown files (`api/memory/workspace/tickers/*.md`) with structured attributes (thesis, key_risk, valuation, catalyst, earnings snapshots). These are backed by SQLite with bidirectional sync — agent writes via `memory_store`, auto-exports to markdown; you edit markdown, file watcher imports back to DB. This is the proven working layer.

Today, ideas enter informally — you mention a ticker in conversation, or run `investment-sync` from Apple Notes/Roam to Notion. There's no systematic pipeline for feeding ideas from multiple sources (screens, newsletters, signals, earnings, your own reading) into the system.

This design builds an **idea ingestion layer** that takes ideas from any source, normalizes them, and writes them into the ticker memory workspace. Analyst-claude picks them up from there and runs its research workflow. You read/edit the markdown files directly.

## Architecture

```
Sources                    Ingestion Pipeline              Ticker Memory Workspace
─────────                  ──────────────────              ───────────────────────
Your notes (Apple/Roam) ─┐                                tickers/
Newsletter emails       ─┤                                  SNOW.md
FMP screens             ─┼─→ Connector → IdeaPayload ─→    IT.md
Portfolio signals       ─┤        ↓                         NEWNAME.md  ← new idea
Insider trade alerts    ─┤   Dedup check                    ...
Earnings transcripts    ─┤        ↓
Corporate events        ─┘   Write to workspace           memory/
                              (file-based)                  MEMORY.md
                                  ↓                         daily/
                             File watcher                   skills/
                              imports to DB
                                  ↓
                             Analyst-claude
                             picks up & researches
```

### Why This Architecture

- **Ticker memory is the canonical store.** It already exists, analyst-claude already writes to it, you already read it. No new system to build.
- **File-based ingestion.** Connectors write properly formatted markdown files into `tickers/`. The existing file watcher picks them up and imports to SQLite. No API needed, no cross-repo imports.
- **Notion becomes optional downstream.** `investment-sync` can still push to Notion for the relational views (Portfolio links, Journal entries), but it's not the primary interface.
- **Each source is just a connector.** Produces an `IdeaPayload`, writes a markdown file. Adding a new source doesn't touch the pipeline.

## Idea Schema

Every idea gets written as attributes in a ticker markdown file, following the existing format:

```markdown
<!-- memory-sync: TICKER -->
<!-- edit freely - changes sync on server restart -->
<!-- format: ## entity header, then - **attribute**: value bullets -->
<!-- multi-line: indent continuation lines with 2 spaces -->

## TICKER

- **thesis**: Brief investment thesis description
- **source**: Where this idea came from and when (e.g., "screen:estimate_revisions, 2026-03-01")
- **direction**: Long | Short | Hedge | Pair
- **strategy**: Value | Special Situation | Macro | Compounder
- **catalyst**: What triggers the thesis
- **timeframe**: Near-term (<3mo) | Medium (3-12mo) | Long-term (>12mo)
- **process_stage**: Idea Selection | Initial Review | Diligence | Decision | Monitoring
- **conviction**: 1-5 (set during review, not on ingestion)
```

These are just attributes in the existing `memory_store` system. No schema migration needed — `memory_store(entity="TICKER", attribute="thesis", value="...")` already works.

### Attributes Set on Ingestion vs Later

| Attribute | On Ingestion | During Review | During Research |
|-----------|-------------|---------------|-----------------|
| thesis | Yes | Update | Update |
| source | Yes | — | — |
| direction | Yes (if known) | Yes | — |
| strategy | Yes (inferred) | Override | — |
| catalyst | If known | Yes | Yes |
| timeframe | If known | Yes | — |
| process_stage | "Idea Selection" | Advance | Advance |
| conviction | — | Yes | — |
| key_risk | — | — | Yes |
| valuation | — | — | Yes |
| earnings_snapshot | — | — | Yes |
| peer_context | — | — | Yes |

## Connector Interface

Every source connector produces one or more `IdeaPayload` dicts:

```python
IdeaPayload = {
    "ticker": str,              # Symbol (e.g., "AAPL"). None for macro themes.
    "company_name": str,        # Full name
    "thesis": str,              # Brief thesis description
    "strategy": str,            # Value | Special Situation | Macro | Compounder
    "direction": str,           # Long | Short | Hedge | Pair
    "source": str,              # e.g., "screen:estimate_revisions", "newsletter:morning_brew"
    "source_date": str,         # ISO date
    "catalyst": str | None,     # What triggers the thesis
    "timeframe": str | None,    # Near-term | Medium | Long-term
    "body_markdown": str,       # Additional context for the ticker file
}
```

Strategy inference uses the existing keyword heuristic from `investment-sync`:
- "cheap/undervalued/margin of safety" → Value
- "moat/growth/compounder" → Compounder
- "catalyst/event/spinoff/merger" → Special Situation
- "commodity/sector/rates/macro" → Macro

## Pipeline: Connector → Workspace

The pipeline takes `IdeaPayload` objects and writes them to the ticker memory workspace.

### Step 1: Dedup Check

Check if `tickers/{TICKER}.md` already exists in the workspace:

- **File exists** → This is an existing idea. Append new source info without overwriting existing attributes.
- **File doesn't exist** → New idea. Create the file with all ingestion attributes.

For macro themes without a ticker, use a slugified theme name (e.g., `tickers/MACRO_CHINA_RECOVERY.md`).

### Step 2: Write

**New ticker file:**
```markdown
<!-- memory-sync: TICKER -->
<!-- edit freely - changes sync on server restart -->
<!-- format: ## entity header, then - **attribute**: value bullets -->
<!-- multi-line: indent continuation lines with 2 spaces -->

## TICKER

- **thesis**: [from payload]
- **source**: [source identifier, date]
- **direction**: [from payload]
- **strategy**: [from payload]
- **process_stage**: Idea Selection
- **catalyst**: [from payload, if present]
- **timeframe**: [from payload, if present]
```

**Existing ticker file — append:**
Add a source log entry and any new attributes that don't already exist. Don't overwrite thesis, conviction, or process_stage (those are your manual overrides).

### Step 3: Minimal Enrichment

After writing the file, optionally run `fmp_profile` to populate:
- `company_name` (if not provided by connector)
- `sector` (useful for filtering)
- `market_cap` (useful for sizing context)

This is a single API call, fast, non-blocking.

### Step 4: File Watcher Picks Up

The existing `MemoryWatcher` in AI-excel-addin detects the new/modified file, calls `import_markdown()`, and the idea is in SQLite — queryable by analyst-claude via `memory_recall`.

## Source Connectors

Each connector is a Claude skill or Python function. They all output `IdeaPayload` dicts and call the shared pipeline writer.

### Built

| Connector | Source | Function | Status |
|-----------|--------|----------|--------|
| **Screen: Estimate Revisions** | FMP | `from_estimate_revisions()` | COMPLETE (Phase 2) |
| **Screen: Quality** | FMP | `from_quality_screen()` | COMPLETE (Phase 2) |
| **Manual (Apple Notes / Roam)** | `investment-sync` | Update to write to ticker workspace | Existing, needs update |

### To Build

| Connector | Source | Trigger | Tool |
|-----------|--------|---------|------|
| **Screen: Fallen Quality** | FMP | Scheduled or manual | `screen_stocks` + filters |
| **Screen: Technical Breakout** | FMP | Manual | `get_technical_analysis` |
| **Newsletter** | Gmail | Manual review | Gmail MCP tools |
| **Insider Trades** | FMP | Scheduled or manual | `get_insider_trades` |
| **Corporate Events** | FMP | Scheduled or manual | `get_events_calendar` |
| **Earnings** | FMP | Post-earnings | `get_earnings_transcript` |
| **Portfolio Signals** | Portfolio MCP | On signal | `check_exit_signals` |

Adding a new connector: write a function that reads the source, produces `IdeaPayload` dicts, calls the pipeline writer. That's it.

## Enrichment Tiers

Enrichment happens when analyst-claude picks up an idea for research. It writes enrichment results as new attributes in the ticker file using `memory_store`.

### Tier 1: Initial Review (quick validation)
- `fmp_profile` → sector, market cap, basic metrics
- `get_technical_analysis` → trend/momentum signals
- `analyze_stock` → volatility, beta, factor exposures
- `get_news` → recent headlines

### Tier 2: Diligence (full research)
- `compare_peers` → valuation vs peer group
- `get_institutional_ownership` → smart money positioning
- `get_insider_trades` → insider activity
- `get_events_calendar` → upcoming catalysts
- `get_earnings_transcript` → latest management commentary

### Tier 3: Decision (portfolio context)
- `get_positions` → current portfolio overlap
- `get_risk_analysis` → impact on portfolio risk
- `run_whatif` → simulate adding at various sizes
- `get_factor_analysis` → factor correlation with existing holdings

These map directly to the existing research playbook (8 steps documented in `investment-research-process.md`).

## Analyst-Claude Integration

Analyst-claude's workflow with the ingestion system:

1. **Idea queue** — `memory_recall("process_stage Idea Selection")` finds all ideas awaiting triage
2. **Triage** — Run Tier 1 enrichment, update process_stage to "Initial Review" or reject
3. **Research** — For promising ideas, run Tier 2, build out ticker file (following the 8-step playbook)
4. **Recommendation** — Run Tier 3, write conviction and valuation_target
5. **Daily note** — Log what was researched in `memory/daily/YYYY-MM-DD.md`

This is the autonomous analyst workflow from the TODO — the ingestion system provides the front door.

## Implementation Phases

### Phase 1: Pipeline Core — COMPLETE
- `IdeaPayload` dataclass + `ingest_idea()` + `ingest_batch()` in `api/memory/ingest.py`
- Dedup logic: create (new ticker) vs merge (existing — append source log, fill missing catalyst/timeframe, protect thesis/conviction/status/process_stage/strategy/direction)
- Source log audit trail: `source_log_{YYYY_MM_DD}_{slug}_{seq}` with sequence suffix for collision avoidance
- Strict ticker validation via `TICKER_RE` from `markdown_sync.py`, sync header guard before parsing
- 36 tests. Plan: `AI-excel-addin/docs/design/idea-ingestion-phase1-plan.md`. Commit `632a551`.

### Phase 2: First Automated Connectors — COMPLETE
- Two connectors in `api/memory/connectors/`: `from_estimate_revisions()` and `from_quality_screen()`
- Pure functions: take pre-fetched screen data → return `IdeaPayload` lists. Caller passes to `ingest_batch()`.
- Estimate revisions: direction/eps_delta filtering, None-safe formatting, flat/unknown direction skipping
- Quality screen: dynamic signal count, `is True` signal check (NaN-safe), conditional pandas import, string-only error detection
- Both: per-row `(KeyError, ValueError, TypeError)` catch for graceful skip on bad data
- 28 tests. Plan: `AI-excel-addin/docs/design/idea-ingestion-phase2-connectors.md` (5 Codex review rounds). Commit `de30308`.

### Phase 3: Update investment-sync
- Update `investment-sync` skill to write to ticker workspace (file-based) instead of or in addition to Notion
- Maintains the Apple Notes / Roam → system flow

### Phase 4: Enrichment Workflow
- Build enrichment as a skill analyst-claude can invoke
- Tier-based: runs appropriate tools based on process_stage
- Writes results as ticker attributes

### Phase 5: Additional Connectors
- Newsletter, insider trades, corporate events, earnings — each follows the same pattern
- Each is independently useful, no dependencies between connectors

## Key Files

- `AI-excel-addin/api/memory/workspace/tickers/` — ticker markdown files (canonical store)
- `AI-excel-addin/api/memory/ingest.py` — `IdeaPayload` dataclass + `ingest_idea()` + `ingest_batch()` (Phase 1)
- `AI-excel-addin/api/memory/connectors/` — source connectors package (Phase 2)
  - `estimate_revisions.py` — `from_estimate_revisions()` (estimate revision screen → payloads)
  - `quality_screen.py` — `from_quality_screen()` (quality screener → payloads)
- `AI-excel-addin/api/memory/store.py` — MemoryStore (SQLite backing)
- `AI-excel-addin/api/memory/markdown_sync.py` — bidirectional sync
- `AI-excel-addin/api/memory/watcher.py` — file watcher for live import
- `AI-excel-addin/api/memory/workspace/AGENT.md` — analyst-claude operating instructions
- `AI-excel-addin/docs/design/connector-development-guide.md` — recipe for adding new connectors
- `investment_tools/docs/IDEA_SOURCE_DEVELOPMENT_GUIDE.md` — recipe for building new source tools
- `AI-excel-addin/tests/test_ingest.py` — 36 pipeline core tests
- `AI-excel-addin/tests/test_connectors.py` — 28 connector tests
- `risk_module/mcp_tools/` — enrichment tools (analyze_stock, etc.)
- `risk_module/fmp/server.py` — FMP tools (screens, profiles, estimates)

## Verification

- New ticker file appears in `tickers/` with correct format and magic comment
- File watcher imports it to SQLite (check `analyst_memory.db`)
- `memory_recall` finds the new idea
- Enrichment adds attributes without overwriting existing ones
- Editing the markdown file manually syncs back to DB on restart
