# Design: Investment Idea Ingestion System

## Context

We have a Notion workspace with a well-structured relational model (Tickers ↔ Ideas ↔ Portfolio ↔ Journal ↔ Files ↔ Rules) and a growing set of MCP tools for market data, portfolio analysis, and enrichment. Today, ideas enter the system through one path: manual capture in Apple Notes / Roam → `investment-sync` skill → Notion Ideas DB.

We want to build a **source-agnostic ingestion layer** so that ideas from any origin — manual reading, newsletters, programmatic screens, insider trade signals, corporate events, earnings transcripts, etc. — flow into the same system through a common schema and pipeline. The set of sources will keep evolving, so the architecture must make adding a new source trivial.

The system serves two consumers: **you** (reviewing ideas manually) and **analyst-claude** (running deeper research workflows autonomously).

## Design Principles

1. **Schema first** — Define what an idea looks like, independent of source
2. **Source-agnostic pipeline** — Every source is a connector that outputs the common schema
3. **Notion as canonical store** — Ideas DB is the single source of truth (already has relational links to Tickers, Portfolio, Journal, Files)
4. **Tiered enrichment** — Minimal auto-enrichment on ingestion (profile + sector), full enrichment as a separate workflow step
5. **Dedup over duplicate** — Same ticker/thesis from multiple sources gets merged, not duplicated
6. **Low friction for manual ideas** — Your own reading → Apple Notes → system should stay as simple as it is today

## 1. Idea Schema

### Core Fields (every idea must have)

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| **Thesis** | title | All | `TICKER - Brief thesis` (existing format) |
| **Ticker** | relation | All | Link to Tickers DB |
| **Process Stage** | multi_select | System | `Idea Selection` on ingestion (existing) |
| **Strategy** | multi_select | Connector | `Value`, `Special Situation`, `Macro`, `Compounder` (existing) |
| **Source** | select | Connector | **NEW** — Where the idea came from |
| **Source Date** | date | Connector | **NEW** — When the idea was captured/generated |
| **Direction** | select | Connector | **NEW** — `Long`, `Short`, `Hedge`, `Pair` |

### Extended Fields (populated by enrichment or connector)

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| **Conviction** | multi_select | Manual | 1-5 scale (existing, set during review) |
| **Expected Return** | number | Manual/Enrichment | % (existing) |
| **Catalyst** | rich_text | Connector | **NEW** — What triggers the thesis (earnings, event, macro shift) |
| **Timeframe** | select | Connector | **NEW** — `Near-term (<3mo)`, `Medium (3-12mo)`, `Long-term (>12mo)` |
| **Last Review** | date | System | Existing |
| **Publish Ready** | checkbox | Manual | Existing |

### Existing Relations (unchanged)

- **Parent Idea** — self-relation for sub-ideas/themes
- **Portfolio** — links to active positions
- **Files** — links to research docs
- **Journal** — links to decision log entries
- **Rules** — links to investment rules

### Notion DB Changes Required

**Ideas DB — add 4 new properties:**
- `Source` (select): Options built as connectors are added. Initial set: `Manual`, `Newsletter`, `Screen`, `Signal`, `Earnings`, `Corporate Event`
- `Source Date` (date)
- `Direction` (select): `Long`, `Short`, `Hedge`, `Pair`
- `Catalyst` (rich_text)
- `Timeframe` (select): `Near-term`, `Medium`, `Long-term`

**Tickers DB — no changes needed.** Already has Status (Watchlist → Invested → Exited), Sector, Factor/Type, and all the relational links.

## 2. Connector Interface

Every source connector must produce an **IdeaPayload** — a normalized dict that the pipeline can process:

```
IdeaPayload:
  ticker: str              # Symbol (e.g., "AAPL"). None for macro themes.
  company_name: str        # Full name (for Ticker creation if needed)
  thesis: str              # Brief thesis description
  strategy: str            # Value | Special Situation | Macro | Compounder
  direction: str           # Long | Short | Hedge | Pair
  source: str              # Source identifier (e.g., "newsletter:morning_brew", "screen:fallen_quality")
  source_date: date        # When captured/generated
  catalyst: str | None     # What triggers the thesis
  timeframe: str | None    # Near-term | Medium | Long-term
  conviction: int | None   # 1-5 (usually None on ingestion, set during review)
  body_markdown: str       # Structured content for the Notion page body
  tags: list[str]          # Optional tags for categorization
```

Each connector is responsible for:
1. Reading its source (email, screen results, signal output, etc.)
2. Extracting one or more `IdeaPayload` objects
3. Inferring `strategy` using the existing keyword heuristic (or explicit mapping)

The connector does NOT handle dedup, Notion writes, or enrichment — that's the pipeline's job.

## 3. Pipeline Flow

```
Source → Connector → [IdeaPayload] → Pipeline
                                        │
                                        ├─ 1. Dedup Check
                                        │     Search Tickers DB + Ideas DB
                                        │     Same ticker + similar thesis? → MERGE
                                        │     Same ticker + different thesis? → NEW IDEA
                                        │     New ticker? → CREATE TICKER + NEW IDEA
                                        │
                                        ├─ 2. Store
                                        │     Create or update Notion Ideas entry
                                        │     Link to Ticker, set Process Stage, Source, etc.
                                        │
                                        ├─ 3. Minimal Enrichment (auto)
                                        │     fmp_profile → sector, market cap, basic metrics
                                        │     Populate Tickers DB Sector field if empty
                                        │
                                        └─ 4. Queue for Review
                                              Idea lands at "Idea Selection" stage
                                              Available for you or analyst-claude to pick up
```

### Dedup Rules (extending existing investment-sync logic)

The existing `investment-sync` dedup is good — search Tickers by symbol, search Ideas by `"TICKER thesis"`. Extend with:

1. **Same ticker, same source** → Always merge (append new insights)
2. **Same ticker, different source** → Merge if thesis is similar (e.g., both say "value play on cheap P/E"). Create new idea if thesis is fundamentally different (e.g., one is long value, another is short momentum).
3. **Similarity check** — For automated sources, a simple keyword overlap or LLM-based similarity check on thesis text. For manual sources, always create (you'll merge yourself if needed).
4. **Macro themes without tickers** — Match on theme name (existing pattern: `"Macro Theme - [Theme Name]"`)

### Merge Behavior

When merging into an existing idea:
- Append a new section to page body: `## [Source] Update ([Date])`
- Update `Source Date` to latest
- Do NOT overwrite Strategy, Conviction, or Process Stage (those are your manual overrides)
- Add source to a sources log in the page body (audit trail)

## 4. Source Connectors (Initial Set)

### Already Built
- **Manual (Apple Notes / Roam)** → `investment-sync` skill — already produces the right shape, just needs to output `Source: "Manual"` and `Source Date`

### To Build (as skills)

Each is a Claude skill that can be invoked manually or by analyst-claude:

- **Newsletter** — Read emails via Gmail MCP, extract ideas with LLM, output IdeaPayloads
- **Screen** — Run FMP screens (estimate revisions, valuation, technicals), output top candidates as IdeaPayloads
- **Signal** — Query portfolio MCP tools (exit signals, insider trades, institutional ownership changes), output actionable signals as IdeaPayloads
- **Earnings** — After earnings, pull transcript via `get_earnings_transcript`, extract key takeaways and thesis updates
- **Corporate Event** — Monitor `get_events_calendar` for M&A, spinoffs, special dividends, output event-driven IdeaPayloads

### Adding a New Source

To add a new source connector:
1. Write a skill (or Python module) that reads the source
2. Output one or more `IdeaPayload` dicts
3. Call the shared pipeline function to dedup + store + enrich
4. Done — no changes to schema, pipeline, or Notion structure

## 5. Enrichment Tiers

### Tier 0: On Ingestion (automatic, every idea)
- `fmp_profile` → sector, market cap, company name
- Populate Tickers DB `Sector` and `Company Name` if empty
- ~1 API call per idea, fast

### Tier 1: Initial Review (when idea moves to "Initial Review" stage)
- `get_technical_analysis` → trend/momentum signals
- `analyze_stock` → volatility, beta, factor exposures
- `get_news` → recent headlines (last 7 days)
- `get_estimate_revisions` → analyst momentum
- Appended to idea page body as structured sections

### Tier 2: Diligence (when idea moves to "Diligence" stage)
- `compare_peers` → valuation vs peer group
- `get_institutional_ownership` → smart money positioning
- `get_insider_trades` → insider activity
- `get_events_calendar` → upcoming catalysts
- `get_earnings_transcript` → latest management commentary
- `get_sector_overview` → sector context

### Tier 3: Decision (portfolio context, when idea moves to "Decision" stage)
- `get_positions` → current portfolio overlap
- `get_risk_analysis` → how adding this position affects portfolio risk
- `run_whatif` → simulate adding position at various sizes
- `get_factor_analysis` → factor correlation with existing holdings

Enrichment can be triggered:
- **Manually** — You invoke the enrichment skill for a specific idea
- **By analyst-claude** — As part of its research workflow when it picks up an idea
- **On stage change** — When you move an idea from one Process Stage to the next (future automation)

## 6. Analyst-Claude Integration

The ingestion system feeds analyst-claude's research queue:

1. **Idea pickup** — Query Ideas DB for entries at "Idea Selection" with no review date, sorted by Source Date
2. **Triage** — Run Tier 1 enrichment, assess if idea warrants deeper analysis
3. **Research** — For promising ideas, run Tier 2 enrichment, build structured thesis
4. **Recommendation** — For ideas moving to Decision, run Tier 3 enrichment, produce sizing/risk analysis
5. **Journal** — Log each research step as a Journal entry linked to the idea

This is the same workflow described in the TODO's "Autonomous Analyst-Claude" section — the ingestion system provides the front door.

## 7. Implementation Phases

### Phase 1: Schema + Pipeline Core
- Add 5 new properties to Ideas DB (Source, Source Date, Direction, Catalyst, Timeframe)
- Build shared pipeline logic (dedup, store, merge) as a reusable skill or module
- Update `investment-sync` to use the pipeline and populate new fields
- Verify round-trip: Apple Notes → investment-sync → Notion with new fields

### Phase 2: First Automated Connector
- Pick one automated source (suggest: estimate revision screen — high signal, uses existing `screen_estimate_revisions` tool)
- Build as a skill that outputs IdeaPayloads → pipeline
- Add Tier 0 enrichment (fmp_profile on ingestion)
- Test end-to-end: screen → ideas in Notion with sector/market cap

### Phase 3: Enrichment Workflow
- Build enrichment skill that runs Tier 1/2/3 based on Process Stage
- Test on existing ideas in the DB
- Document the enrichment output format in idea page bodies

### Phase 4: Additional Connectors
- Newsletter connector (Gmail MCP → extract → pipeline)
- Signal connector (insider trades, exit signals → pipeline)
- Earnings connector (transcript → thesis updates → pipeline)
- Each follows the same pattern: read source → IdeaPayload → pipeline

### Phase 5: Analyst-Claude Queue
- Build the idea pickup + triage workflow
- Connect enrichment tiers to Process Stage transitions
- Journal logging for research steps

## Verification

- **Schema**: Notion DB properties visible and filterable in Ideas views
- **Pipeline**: Same idea from two sources merges correctly (no duplicates)
- **Enrichment**: Idea page body contains structured enrichment sections
- **Round-trip**: Manual idea in Apple Notes → Notion → enriched → visible in Ideas DB with all fields populated
