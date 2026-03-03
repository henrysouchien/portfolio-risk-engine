# TODO

Active work items and setup tasks. Completed items archived in `completed/TODO_COMPLETED.md`.

## In Progress

### 1. Excel Add-In MCP End-to-End Testing
MCP server is registered. Need to test the full relay pipeline end-to-end: Claude Code -> MCP -> FastAPI -> SSE -> Office.js -> read/understand financial model via schema.
- Validate agent-tools schema against real financial model spreadsheets

## Next Up (Actionable)

### Institution-Based Realized Performance Routing
Make `get_performance` MCP tool route purely by institution (e.g., `institution="merrill"`) with the backend automatically resolving which provider pipeline to use (Merrill → Plaid, Schwab → Schwab API, IBKR → IBKR Flex). The `source` parameter becomes an internal implementation detail rather than a user-facing concept. Requires adding institution→provider mappings to `TRANSACTION_ROUTING` in `providers/routing_config.py` (currently only has `interactive_brokers → ibkr_flex` and `charles_schwab → schwab`; Merrill is missing). Dependency satisfied: per-account aggregation generalized (commit `af30d415`).

### Frontend Views → Defined Workflows (Phase 4)
Phases 1-3 complete (workflow definitions, backend layer, agent skills). Phase 4 not started: upgrade each view from data display to interactive multi-step workflow. Design doc: `docs/planning/WORKFLOW_DESIGN.md`.

### EDGAR FastAPI Migration — Phase 4 Cleanup
Phases 0-3 complete (2026-02-27). nginx routing live. Remaining: remove dead Flask `/api/*` route handlers from `app.py` after stability gate (~March 6). Audit doc: `Edgar_updater/docs/plans/PLAN-fastapi-migration-audit.md`.

## Backlog

### Realized Performance: Investigate Bad Data Quality
Poor data quality across all providers. Coverage: Schwab 37.5%, Plaid 12.5%, SnapTrade 0%. Combined gives 58% with 14 synthetic positions.
- Schwab: 176% total return, Sharpe 1.60 — likely inflated by missing cost basis on 19 synthetic positions
- SnapTrade: 0% coverage, all 24 positions synthetic
- Plaid: 12.5% coverage, 24 synthetic
- Diagnose: transaction sourcing gap, synthetic position inference issue, or cash flow reconstruction problem?

### Architecture: Break Up Large Monolithic Files
- `core/realized_performance_analysis.py` (115KB) — extract pricing chain logic

### Frontend: SDK Testing — Remaining Coverage
Additional feature hooks (useRiskAnalysis, usePerformance, etc.), interaction primitives (useSharedState, useFlow), conformance checks (descriptor fields match adapter output types).

### Futures Phase 8-9
Full design: `docs/planning/FUTURES_DESIGN.md`. Phases 1-7 complete.
- [ ] **Phase 8 — Polish**: Daily bars → risk pipeline (requires frequency-aware refactor of 8+ annualization sites), DB persistence for `instrument_types`.
- [ ] **Phase 9 — Live futures pricing in trade preview**: Add `fetch_snapshot()` to `preview_futures_roll` for live bid/ask/mid on front and back contracts before `whatIfOrder`.

### Options: Live Pricing + Continuous Monitoring
- [ ] **Live options pricing** — Real-time bid/ask/mid from IBKR via `fetch_snapshot()` for options contracts. Current `analyze_option_strategy()` uses Black-Scholes model pricing.
- [ ] **Continuous hedge monitoring** — Alerts when portfolio drifts beyond hedge targets, hedge ratios become stale, or expiring options need rolling.

### Workflow Gaps: Scenario & Strategy Infrastructure
- [ ] **Predefined scenario templates** — Backend-driven templates ("defensive rotation", "growth tilt", "derisking") with configurable intensity.
- [ ] **Stress test presets** — Predefined market shock scenarios ("market -20%", "rates +200bp", "stagflation").
- [ ] **Scenario persistence** — Save/load/history for scenario runs.
- [ ] **Return attribution (Brinson/Fama-French)** — Decompose portfolio returns by factor/sector/selection.
- [ ] **Backtesting engine** — Historical strategy validation (walk-forward, out-of-sample).
- [ ] **Efficient frontier visualization** — Plot optimal portfolios across risk/return spectrum.
- [ ] **Strategy versioning** — Track strategy iterations with constraint snapshots and optimization results.

### Earnings Estimates: Verify Skip-List in Production
Skip-list deployed. 142 run-1 failures investigated — all benign. Verify skip-list log output after next monthly run (April 1).

### Architecture: Add Settings Validation
Adopt `pydantic.BaseSettings` for `settings.py` to catch misconfiguration at startup. Low priority — settings.py is 454 lines, env is stable.

### Tool Reliability & Known Limitations
- [ ] **IBKR config hardcoded values** — `_request_bars` 2s retry delay, `fetch_snapshot` 0.5s poll interval should be named constants or env-configurable
- [ ] **IBKR market data subscription detection** — distinguish "no data because not subscribed" from "no data because timeout"
- **`analyze_option_chain`** — market hours required (Mon-Fri 9:30am-4pm ET)

### Macro Review Chart Book
Repeatable macro review workflow: market/economic data → charts → structured "chart book". Phases: data pipeline, visualization, template/automation, analyst-claude integration, publishing. Leverages existing `get_market_context()`, `get_economic_data()`, `get_sector_overview()`, `get_news()`, `get_events_calendar()`, `get_technical_analysis()`.

### Investment Idea Ingestion System
Source-agnostic pipeline for ingesting ideas into ticker memory workspace. Phases 1-2 complete (pipeline core + first connectors). Design: `docs/planning/IDEA_INGESTION_SYSTEM_DESIGN.md`.
- [ ] **Phase 3** — Enrichment + orchestration (needs real usage to inform design)
- [ ] **Phase 4** — Additional connectors (Newsletter/Gmail, insider trades, corporate events, earnings transcripts)
- [ ] **Phase 5** — Analyst-claude queue (idea pickup + triage workflow)
- [ ] **Process stage definitions** — transitions, criteria, enrichment tiers per stage

### Autonomous Analyst-Claude (Overnight Work)
Infrastructure for analyst-claude to work autonomously during off-hours on long-form research. Prerequisite: agent scheduling/nudging mechanism (cron/launchd, Claude Agent SDK, or lightweight scheduler). See `TODO_COMPLETED.md` history for full design notes.

### AI Analyst — Package and Release
- [ ] Agent-first review of all MCP packages
- [ ] Wire `portfolio-mcp` into analyst as MCP connection
- [ ] Dogfood: daily usage, refine agent runner + memory + tools
- [ ] Clean up `AI-excel-addin` repo for open source release
- [ ] `portfolio-mcp` as standalone pip package
- [ ] README + setup guide
- Reference: `RELEASE_PLAN.md`, `docs/PRODUCT_ARCHITECTURE.md`, `docs/DEPLOY.md`

### Portfolio Risk Engine — Pre-v1.0
- [ ] Methodology docs (factor model, optimization approach)
- [ ] Math validation against known benchmarks
- [ ] Unit tests for core calculations
- [ ] Evaluate core optimization functions (correctness, constraints, solver options)

### Frontend: AI-Assisted UI Component Development
Use Claude with browser plugin to adjust/create UI components. Build starter kit of polished components covering core use cases.

### Frontend: Agent-Driven Dynamic UI Generation
Design chassis + UI infrastructure for AI agents to build on-the-fly visualizations and workflow UIs at runtime. Component registry, schema-driven renderer, workflow templates, sandbox/preview mode, versioning.

### Analyst Feedback & Performance Review Loop
Two loops: (1) operational self-improvement from chat transcripts/tool usage, (2) investment decision review — thesis vs outcome, systematic bias detection, track record building. Requires: decision log, performance attribution, review cadence.

### Research & AI
- Perplexity MCP — evaluate as research/search layer for investment agent. Compare vs Brave Search.
