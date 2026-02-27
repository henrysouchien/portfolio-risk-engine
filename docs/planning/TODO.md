# TODO

Active work items and setup tasks. Completed items archived in `completed/TODO_COMPLETED.md`.

## In Progress

### 1. Excel Add-In MCP End-to-End Testing
MCP server is registered. Need to test the full relay pipeline end-to-end: Claude Code -> MCP -> FastAPI -> SSE -> Office.js -> read/understand financial model via schema.
- Validate agent-tools schema against real financial model spreadsheets

## Next Up (Actionable)

### Frontend: Package Formalization + Component Data Wiring
Audit complete — see `docs/planning/FRONTEND_DATA_WIRING_AUDIT.md` for full findings.

**Phase 1 — Package formalization:** Done (separation clean, boundaries enforced, exports defined, build works)

**Phase 2 — Data wiring audit:** Done (9/9 containers wired to real APIs, no mock stubs)

**Phase 3 — Backend data enrichment** (gaps identified in audit):
- [ ] P1: Holdings enrichment — thread sector, currentPrice, avgCost, totalReturn, volatility into summary endpoint
- [ ] P2: Performance attribution — thread sector/factor attribution from risk analysis into performance endpoint
- [ ] P3: Benchmark selection UI — add selector that passes benchmark param to backend
- [ ] P4: Hedging strategies — new feature, AI-generated recommendations from risk exposures
- [ ] P5: Asset allocation periods — re-enable when historical snapshots available

### Frontend: Remaining Cleanup — Done
- [x] ~~Reduce `no-explicit-any` warnings~~ — Complete: 590→0 (100% reduction). `as any` tokens: 180→5.
- Remaining 114 lint warnings are non-`any`: `no-console` (41), `react/no-array-index-key` (29), `react-hooks/exhaustive-deps` (22), minor (22)

### Architecture: Pricing Provider Pluggability Review
Review the pricing pipeline to ensure we can easily swap or add a new price provider (e.g., replace FMP, add a Bloomberg/Refinitiv feed, or use a different market data vendor). Audit all pricing entry points (`latest_price()`, `get_returns_dataframe()`, `ProviderRegistry` price chain, FMP client calls) and confirm the abstraction boundaries are clean — a new provider should be addable without touching core analysis logic. Identify any hard-coded FMP assumptions or tight coupling that would make switching painful.

## Backlog

### Frontend: SDK Testing
Set up vitest for the frontend and write tests for the SDK layer. Key areas: DataCatalog (register, describe, search, cycle detection), classifyError (HTTP status mapping, edge cases), useDataSource (resolver integration, loading/error states), conformance checks (descriptor fields match adapter output types), interaction primitives (useSharedState, useFlow). Also test migrated hooks (useRiskScore, useRiskAnalysis, usePerformance) to verify they produce the same output as before via the resolver path.

### Realized Performance: Investigate Bad Data Quality
`get_performance(mode="realized", format="agent")` shows poor data quality across all providers. Coverage is low everywhere: Schwab 37.5%, Plaid 12.5%, SnapTrade 0%. Combined gives 58% with 14 synthetic positions.
- **Schwab specifically looks off**: 176% total return, Sharpe 1.60 — likely inflated by missing cost basis on 19 synthetic positions. Needs investigation.
- **SnapTrade**: 0% coverage, all 24 positions synthetic — essentially no transaction data.
- **Plaid**: 12.5% coverage, 24 synthetic — minimal data.
- Need to diagnose whether this is a transaction sourcing gap, synthetic position inference issue, or cash flow reconstruction problem.

### Realized Performance: Bond/Treasury Pricing — Identifier Capture Done, Pricing TBD
`US Treasury Note - 4.25% 15/10/2025 USD 100` cannot be priced — valued as $0 in NAV. Root cause: Plaid uses a long description string as the ticker (not a standard symbol), and the bond has no IBKR `con_id` so IBKR pricing is skipped (`bond_missing_con_id`).
- **Done**: Security identifiers (CUSIP/ISIN from Plaid, CUSIP from Schwab, FIGI from SnapTrade) now captured and threaded into `PortfolioData.security_identifiers`. Bond positions log available identifiers.
- **Remaining**: Build CUSIP → IBKR con_id resolver (via IBKR contract search API or OpenFIGI) to unlock IBKR bond pricing. Low dollar impact (single position) but demonstrates the pricing gap.
- See: `docs/planning/SECURITY_IDENTIFIERS_PLAN.md`

### Portfolio System: Currency Position Handling — Done
~~Brokerage imports include currency positions (`CUR:CAD`, `CUR:HKD`, `CUR:JPY`, `CUR:MXN`). Quick fix applied — added `:` to ticker validation regex so they pass validation. But need to audit how these flow through the full analysis pipeline.~~
- **Done**: Full pipeline audit complete. `to_portfolio_data()` correctly converts CUR:XXX → cash proxy ETFs via `cash_map.yaml`. `SecurityTypeService` now has explicit CUR: → cash detection in both `get_security_types()` and `get_asset_classes()`. Provider `is_cash_equivalent` flag honored in `to_portfolio_data()`.
- See: `docs/planning/SECURITY_IDENTIFIERS_PLAN.md`

### Architecture: Break Up Large Monolithic Files
- `core/realized_performance_analysis.py` (115KB) — extract pricing chain logic

### Architecture: Add Settings Validation
Adopt `pydantic.BaseSettings` (or similar) for `settings.py` to catch misconfiguration at startup. Low priority — settings.py is now 454 lines after consolidation, env is stable, and misconfigurations are rare in practice. Adding pydantic as a dependency may not be worth the migration cost.

### Futures & Portfolio
Full design: `docs/planning/FUTURES_DESIGN.md`. Phased implementation (6 phases).
- **Phase 1 — Data foundation**: Done. `brokerage/futures/` package with `FuturesContractSpec` (27 contracts), notional/P&L math, asset class taxonomy. Multiplier + tick_size in `ibkr/exchange_mappings.yaml`. See `docs/planning/FUTURES_P1_DATA_FOUNDATION_PLAN.md`.
- **Phase 2 — Pricing dispatch**: Next. Route futures tickers to IBKR/FMP commodity endpoints in `latest_price()` and `get_returns_dataframe()`. Auto-detect currency from contract spec.
- **Phase 3 — Portfolio integration**: Futures in holdings view with margin + notional overlay.
- **Phase 4 — Risk integration**: Macro/asset-class factors instead of equity factors. Wire `fx_attribution` into `RiskAnalysisResult`.
- **Phase 5 — Performance + trading**: Futures P&L with multiplier awareness. Trading analysis integration.
- **Phase 6 — Polish**: Daily bars → risk pipeline, DB persistence for `instrument_types`, IBKR contract verification (IBV, ESTX50, DAX).

### Migrate EDGAR MCP to FastAPI endpoint
Currently the `edgar-mcp` package (`edgar_mcp/server.py`) hits the Flask app at `financialmodelupdater.com`. Migrate to use the FastAPI service (`edgar_api`) endpoints instead — simple base URL + path swap. Moves toward Flask = web UI only, FastAPI = all programmatic access.

### Earnings Estimates: AWS Migration
Migrate the estimate collection system (currently local Postgres + launchd) to an AWS instance with its own database. Stand up a simple API to serve estimate revision data externally — decouples it from the local dev machine and makes the data accessible to other services/users. Covers: RDS instance (`fmp_data_db`), EC2/Lambda for the monthly snapshot job, lightweight API (FastAPI or Lambda+API Gateway) for `get_estimate_revisions` and `screen_estimate_revisions` queries.

### Research & AI
- Perplexity MCP — evaluate Perplexity as research/search layer for the investment agent. Compare vs Brave Search.

### Stock Basket / Custom Index
Plan: `docs/planning/STOCK_BASKET_PLAN.md`. Phase 1 (CRUD MCP tools) complete.
- [x] Phase 1: CRUD MCP tools — `create_basket`, `list_baskets`, `get_basket`, `update_basket`, `delete_basket` (commit `39930617`)
- [x] Phase 2: Basket returns analysis — `analyze_basket` tool with weighted returns, Sharpe, drawdown, alpha/beta, component attribution, portfolio correlation (commit `240f00ea`)
- [ ] Phase 3: Basket as custom factor — inject into `get_factor_analysis()` alongside standard factors
- [ ] Phase 4: Multi-leg trade execution — `preview_basket_trade`, `execute_basket_trade`
- [ ] Phase 5: ETF seeding — `create_basket_from_etf` from FMP holdings

### Frontend: AI-Assisted UI Component Development (Post-Gateway)
Once the gateway channel is live, use Claude with the frontend browser plugin (or Antigravity/Gemini) to adjust, modify, and create UI components that match key functionality. Goal: build a starter kit of polished components that cover the core use cases (risk dashboard, portfolio overview, analysis views, settings). The AI can iterate on layout, styling, and interaction patterns directly in the browser with live feedback.

### Frontend: Agent-Driven Dynamic UI Generation
Design the chassis + UI infrastructure so that AI agents (analyst-claude, design-claude, visualizer-claude) can build on-the-fly visualizations, workflow UIs, and app scaffolding at runtime. The idea: when a Claude skill needs a visualization or interactive workflow that doesn't exist yet, the agent generates the component dynamically using the chassis primitives and Radix building blocks. This could mean:
- A component registry that agents can populate at runtime
- A schema-driven renderer that turns agent output into live React components
- Workflow templates that map to Claude skills (e.g., "earnings review" skill → multi-step UI with charts, tables, and action buttons)
- Sandbox/preview mode so generated UIs can be validated before persisting
- Versioning so good generated UIs get saved as reusable templates

This is the longer-term vision — the chassis + gateway architecture is the foundation that makes this possible.

### Options Tools
Port option payoff/strategy analysis from draft notebook (`~/Documents/jupyter/investment_system/Option-calculator.ipynb`) into a proper module. Existing `OptionLeg`/`OptionStrategy` class framework covers payoff curves for multi-leg strategies.
- Payoff calculator: max profit/loss, breakevens, P&L at various DTE
- Integration with IBKR OI data (overlay strategy payoff on OI clusters)
- Evaluate IBKR API as primary options data source (chains, Greeks, pricing)
- Options Greeks could feed into portfolio risk analysis

### Macro Review Chart Book
Build a repeatable macro review workflow that pulls market/economic data, generates charts and visuals, and produces a structured "chart book" for reviewing the current macro landscape. Should be runnable on a regular cadence (weekly/monthly).

**Existing infrastructure to leverage:**
- `get_market_context()` — indices, sectors, movers, events in one call
- `get_economic_data()` — economic indicators and calendar
- `get_sector_overview()` — sector/industry performance and P/E
- `get_news()` — market and sector news
- `get_events_calendar()` — earnings, dividends, splits
- `get_technical_analysis()` — trend/momentum/volatility signals
- FMP endpoints for treasuries, commodities, FX rates

**Phases:**
1. **Data pipeline** — define the macro data pulls (rates, curves, sector rotation, breadth, sentiment, etc.) and structure the output
2. **Visualization** — chart generation (matplotlib/plotly) for key macro views: yield curve, sector heatmap, factor performance, economic surprise, etc.
3. **Template / automation** — repeatable notebook or script that produces a dated chart book output (PDF/HTML)
4. **Analyst-claude integration** — AI-assisted commentary, narrative generation, and highlight extraction for publishable output
5. **Publishing** — format for distribution (Notion page, PDF report, email digest)

### Investment Idea Sourcing Pipeline
Automated pipeline to ingest investment newsletters via email, extract actionable ideas, and surface them for review. Dedicated email account partially set up already.

**Concept:**
- Subscribe to investment newsletters (sell-side research, independent analysts, macro commentators) with a dedicated email
- AI reads incoming emails, extracts investment ideas with structured metadata (ticker, direction, thesis summary, catalyst, timeframe, conviction level, source)
- Customizable categorization (macro, sector, single-name, event-driven, etc.) and filtering (relevance, quality, overlap with existing portfolio)
- Summarized feed of ideas with thesis + key data points, ready for quick review
- Track idea lifecycle: sourced → reviewed → acted on / passed / expired

**Infrastructure considerations:**
- Gmail MCP tools already available for email access
- Notion MCP for idea database storage (ties into existing Ideas database)
- FMP tools for enriching ideas with current data (price, valuation, estimates, technicals)
- Portfolio MCP for checking overlap/correlation with existing positions

**Phases:**
1. **Email setup** — finalize dedicated email, subscribe to target newsletters, organize with Gmail labels/filters
2. **Extraction engine** — Claude-based email parsing: identify investment ideas vs noise, extract structured fields, handle varied newsletter formats
3. **Idea database** — schema design for idea storage (Notion or DB), categorization taxonomy, dedup logic
4. **Enrichment** — auto-attach current market data, estimate revisions, technicals, portfolio overlap to each idea
5. **Review workflow** — daily/weekly digest format, priority scoring, customizable filters
6. **Feedback loop** — track which sourced ideas performed well, tune extraction and scoring over time

**Future extension:** Once the sourcing pipeline is stable, analyst-claude can run deeper analysis workflows on promising ideas — pull comps, check estimate revisions and momentum, run technicals, assess factor exposure and correlation against existing portfolio, size a potential position via optimization, build a quick thesis doc. The sourcing pipeline becomes the front door to a full analyst workbench.

### Autonomous Analyst-Claude (Overnight Work)
Infrastructure and workflow design for analyst-claude to work autonomously during off-hours (overnight), running longer-form research and analysis projects that are ready for review in the morning.

**Concept:**
- Set up analyst-claude to run unattended on multi-hour research tasks
- Leverage the full tool stack (FMP data, EDGAR filings, portfolio context, Notion, etc.) for deep analysis
- Morning deliverable: a completed analysis, strategy recommendation, or built-out workflow ready for human review

**Example workflow — "Fallen quality" screen:**
1. Define a thesis template: good business + stock down + low expectations + signs of improving conditions
2. Screen universe against criteria (fundamentals, estimate revisions, technicals, sentiment)
3. For each candidate: pull detailed data (financials, transcript analysis, peer comps, institutional ownership changes)
4. Build a structured thesis doc per name with supporting data
5. Score/rank candidates, size potential positions against current portfolio
6. Deliver a morning brief with actionable recommendations

**Infrastructure needs:**
- Long-running agent execution (scheduling, error recovery, checkpointing)
- Sub-agent orchestration (parallel research on multiple names)
- Workflow templates that define rigorous, repeatable research processes (keep it data-driven, avoid hallucinated reasoning)
- Output format and delivery (Notion pages, file artifacts, summary digest)
- Guardrails: no autonomous trading, human approval gates for any actions
- Logging/audit trail so the morning review can trace how conclusions were reached

**Key design question:** How to keep the research process rigorous and grounded — need to define the high-level workflow/process manually first (what data to pull, what criteria to apply, what constitutes a signal), then let the agent execute that process systematically rather than freestyling. Think of it as coding a research SOP that the agent follows.

**Infrastructure prerequisite — agent scheduling/nudging:**
Need to figure out the mechanism for triggering and keeping an autonomous agent session alive. Options to explore:
- `cron` / `launchd` plist invoking Claude Code CLI with a task prompt (similar to existing estimate snapshot job)
- Claude Agent SDK's built-in patterns for long-running/scheduled agents
- A lightweight scheduler script that monitors agent state and re-prompts if idle or stalled
- Checkpointing so an agent can resume where it left off if the session dies
- This is a prerequisite for both the overnight analyst and the idea sourcing pipeline (which also benefits from scheduled runs)

### Analyst Feedback & Performance Review Loop
Two complementary feedback loops for continuous improvement of both the AI analyst and investment decision-making.

**Loop 1 — Operational self-improvement:**
- Periodic review of chat transcripts, tool usage patterns, and interaction quality
- Identify where the agent was inefficient, made wrong assumptions, required too many corrections, or missed context
- Turn findings into actionable guidance (memory updates, workflow adjustments, prompt improvements)
- Goal: the agent gets better at its job over time based on how interactions actually went

**Loop 2 — Investment decision review (equally or more important):**
- Track decisions/analysis made → what actually happened in the market → actual performance
- Compare thesis at time of recommendation vs realized outcome (was the reasoning sound? were the right data points used? was the timing right?)
- Identify systematic biases or blind spots (e.g., consistently underweighting a risk factor, overweighting momentum, poor position sizing)
- Feed learnings back into research SOPs, screening criteria, and analyst-claude guidance
- Build a track record that shows what types of analysis/setups have the best hit rate

**Infrastructure:**
- Decision log: structured record of each idea/recommendation with thesis, data at time, action taken, and outcome fields
- Performance attribution: link decisions to actual P&L using portfolio data (positions, trades, realized performance)
- Review cadence: monthly or quarterly retrospective comparing analyst output vs market outcomes
- Actionable output: updated guidance docs, adjusted screening parameters, refined research templates
