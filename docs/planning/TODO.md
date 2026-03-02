# TODO

Active work items and setup tasks. Completed items archived in `completed/TODO_COMPLETED.md`.

## In Progress

### 1. Excel Add-In MCP End-to-End Testing
MCP server is registered. Need to test the full relay pipeline end-to-end: Claude Code -> MCP -> FastAPI -> SSE -> Office.js -> read/understand financial model via schema.
- Validate agent-tools schema against real financial model spreadsheets

## Next Up (Actionable)

### Frontend Views → Defined Workflows
Workflow design doc: `docs/planning/WORKFLOW_DESIGN.md` (2,457 lines).

**Phase 1 — Define workflows:** COMPLETE. All 7 workflows fully defined with 5-step sequences, tool mappings, inputs/outputs, and gap analysis: Hedging, Scenario Analysis, Allocation Review, Risk Review, Performance Review, Stock Research, Strategy Design.

**Phase 2 — Backend workflow layer:** Not started. Approach: **Option A (orchestrator functions)** — lightweight Python functions that chain existing MCP tools, passing outputs between steps. Each workflow becomes a composable function that UI or agent can call. No heavy state machine needed for now; evolve toward persistence/resumability (Option B) only for workflows that need it (e.g., Strategy Design with multi-day iteration). See `WORKFLOW_DESIGN.md` → Implementation Approach for full option comparison.

**Start with cross-cutting gaps** before workflow orchestration — these unblock execution in all 7 workflows:
- ~~**Rebalance trade generator** (highest leverage)~~ — COMPLETE. `generate_rebalance_trades()` MCP tool. Plan: `REBALANCE_TRADE_GENERATOR_PLAN.md`. Commit `e19f9e28`.
- ~~**Batch scenario/optimization comparison**~~ — COMPLETE. `compare_scenarios()` MCP tool. Plan: `BATCH_COMPARISON_PLAN.md`. Commit `56d773a8`.
- **Action audit trail** — Risk, Allocation, Performance lack history of which recommendations were taken

**Phase 3 — UI second pass:** Not started. Upgrade each view from data display to interactive multi-step workflow. Depends on Phase 2.

**Phase 4 — Agent integration:** Not started. Workflows callable from Claude Chat/MCP. Depends on Phase 2.

## Recently Completed

### ~~Frontend: Package Formalization + Component Data Wiring~~ — COMPLETE (2026-02-27 to 2026-03-01)
All 3 phases done. Audit: `docs/planning/FRONTEND_DATA_WIRING_AUDIT.md`.
- **Phase 1** — Package formalization (chassis/connectors/ui split, boundaries enforced, build works)
- **Phase 2** — Data wiring audit (9/9 containers wired to real APIs, no mock stubs)
- **Phase 3** — Backend data enrichment (7 items): Holdings (`FRONTEND_HOLDINGS_ENRICHMENT_PLAN.md`), MCP positions (`MCP_POSITIONS_ENRICHMENT_PLAN.md`), Performance attribution (`PERFORMANCE_ATTRIBUTION_PLAN.md`), Factor attribution (`FACTOR_ATTRIBUTION_PLAN.md`), Benchmark selection (`BENCHMARK_SELECTION_UI_PLAN.md`), Hedging (`FRONTEND_HEDGING_WIRING_PLAN.md`), Asset allocation + period selector + drift (`P5_ASSET_ALLOCATION_PLAN.md`)

### ~~Frontend: Block Component Refactoring~~ — COMPLETE
5 block components adopted across 9 views in 3 waves. Plans: `FRONTEND_BLOCK_REFACTOR_PLAN.md`, `FRONTEND_BLOCK_REFACTOR_WAVE{1,2,3}.md`. Commits: `9506643d`, `93e5ed9e`, `750dea25`.

### ~~Frontend: TypeScript Cleanup~~ — COMPLETE
16 TS errors→0, `no-explicit-any` 590→0 (100%), `as any` 180→5, total lint warnings 704→114. See `docs/planning/FRONTEND_TYPESCRIPT_CLEANUP_PLAN.md`.

### ~~Performance: Short Portfolio Return History~~ — COMPLETE
Fixed `compute_portfolio_returns()` truncation. Added `compute_portfolio_returns_partial()` with gross-exposure scaling. Verified in Chrome 2026-03-01. See `docs/planning/PORTFOLIO_RETURN_HISTORY_FIX_PLAN.md`.

### ~~Trading Analysis: Date Range Parameters~~ — COMPLETE
Added `start_date`/`end_date` to `get_trading_analysis()`. Commit `5919122e`. See `docs/planning/TRADING_DATE_RANGE_PLAN.md`.

### ~~Target Allocations: DB Migration + MCP Set/Get Tools~~ — COMPLETE
Write path for target allocations: DB migration (`003_target_allocations.sql`), `save_target_allocations()` in database_client + repository, `set_target_allocation()` + `get_target_allocation()` MCP tools, target_allocation DB load in MCP risk path. 12 tests. Drift now flows end-to-end in `get_risk_analysis()`. Commit `55967d7b`. Plan: `docs/planning/TARGET_ALLOCATIONS_PLAN.md`.

### ~~Architecture: Fix Circular Imports in app.py~~ — COMPLETE
Extracted rate limiter to `utils/rate_limiter.py` (breaking `app → routes → app` circular import). Deleted dead `routes/claude.py` (replaced by gateway channel). Commit `5c4d3995`. Plan: `docs/planning/CIRCULAR_IMPORT_FIX_PLAN.md`.

### ~~Frontend: SDK Testing (Phase 1+2)~~ — COMPLETE
75 Vitest tests across 8 files. Phase 1: pure function tests (54 tests, commit `5d490407`). Phase 2: hook tests (21 tests, commit `6c59f7e7`). Plan: `FRONTEND_SDK_TESTING_PLAN.md`.

### ~~Frontend: Analyst Mode~~ — COMPLETE
Chat-focused UI at `/analyst` — thin icon sidebar with 3 views (chat, holdings, connections). Reuses all existing auth, services, chat, and portfolio infrastructure. Commit `ea9f2fd3`. Plan: `ANALYST_MODE_PLAN.md`.

### ~~Rebalance Trade Generator~~ — COMPLETE
`generate_rebalance_trades()` MCP tool in `mcp_tools/rebalance.py`. Accepts `target_weights` or `weight_changes`, produces sequenced BUY/SELL legs. 26 tests. Commit `e19f9e28`. Plan: `REBALANCE_TRADE_GENERATOR_PLAN.md`.

### ~~Concentration: Leverage-Aware Flag~~ — COMPLETE
Added `leveraged_concentration` flag to `core/position_flags.py`. Fires when leverage > 1.1x and a single-issuer position exceeds 25% of net equity. Shows both equity and gross weight perspectives. Existing gross-based concentration unchanged. 8 new tests (40 total). Commit `8741d6ac`. Plan: `LEVERAGED_CONCENTRATION_FLAG_PLAN.md`.

## Backlog

### ~~IBKR Direct Trading via IB Gateway~~ — COMPLETE
Two bugs fixed: (1) connection leak from non-singleton `IBKRConnectionManager` — added module-level singleton, (2) account routing gap — added `TRADE_ROUTING` + `TRADE_ACCOUNT_MAP` in `routing_config.py` (follows `TRANSACTION_ROUTING`/`POSITION_ROUTING` pattern). Position validation resolves mapped account aliases. Verified live: both SnapTrade UUID and native IBKR account ID route correctly. Commits `ab8bff60`, `8a20f4b8`. Plan: `docs/planning/IBKR_DIRECT_TRADING_PLAN.md`.
- **Remaining:** End-to-end execute test (preview works, haven't confirmed actual order placement yet)

### Frontend: SDK Testing — Remaining Coverage (backlog)
Additional feature hooks (useRiskAnalysis, usePerformance, etc.), interaction primitives (useSharedState, useFlow), conformance checks (descriptor fields match adapter output types).

### Realized Performance: Investigate Bad Data Quality
`get_performance(mode="realized", format="agent")` shows poor data quality across all providers. Coverage is low everywhere: Schwab 37.5%, Plaid 12.5%, SnapTrade 0%. Combined gives 58% with 14 synthetic positions.
- **Schwab specifically looks off**: 176% total return, Sharpe 1.60 — likely inflated by missing cost basis on 19 synthetic positions. Needs investigation.
- **SnapTrade**: 0% coverage, all 24 positions synthetic — essentially no transaction data.
- **Plaid**: 12.5% coverage, 24 synthetic — minimal data.
- Need to diagnose whether this is a transaction sourcing gap, synthetic position inference issue, or cash flow reconstruction problem.

### Architecture: Break Up Large Monolithic Files
- `core/realized_performance_analysis.py` (115KB) — extract pricing chain logic
- Note: `core/result_objects.py` already split into `core/result_objects/` package (10 submodules, commit `3758c186`)

### Architecture: Add Settings Validation
Adopt `pydantic.BaseSettings` (or similar) for `settings.py` to catch misconfiguration at startup. Low priority — settings.py is now 454 lines after consolidation, env is stable, and misconfigurations are rare in practice. Adding pydantic as a dependency may not be worth the migration cost.

### Futures & Portfolio
Full design: `docs/planning/FUTURES_DESIGN.md`. Phased implementation (8 phases). Phases 1-7 complete.
- [x] **Phase 1 — Data foundation**: Done.
- [x] **Phase 2 — Pricing dispatch**: Done.
- [x] **Phase 3 — Portfolio integration**: Done (commit `dcf481a0`).
- [x] **Phase 4 — Risk integration**: Done (commit `a1c4aefc`).
- [x] **Phase 5 — Performance + trading**: Done. Futures P&L metadata threading + segment filter on `get_trading_analysis()` (commit `a5f82977`, `0a7b2691`).
- [x] **Phase 6 — Monthly contracts, curve & roll**: Done. Monthly contract resolution, `get_futures_curve()` term structure tool, `preview_futures_roll()`/`execute_futures_roll()` BAG combo orders (commits `8ff76db9`, `63a948a0`). Plan: `docs/planning/FUTURES_MONTHLY_CURVE_ROLL_PLAN.md`.
- [x] **Phase 7 — Contract verification**: ESTX50 and DAX verified live against TWS (conIds 621358639, 621358482; monthly close data confirmed; ESTX50 via FMP `^STOXX50E`, DAX via IBKR fallback since `^GDAXI` returns 402). IBV removed — not available on IBKR (no CME Ibovespa futures product found). Contract catalog: 26 symbols.
- [ ] **Phase 8 — Polish (backlog)**: Daily bars → risk pipeline (requires frequency-aware refactor of 8+ annualization sites), DB persistence for `instrument_types`.

### EDGAR FastAPI Migration — Phase 4 Cleanup
Phases 0-3 complete (2026-02-27). nginx on `financialmodelupdater.com` now routes `/api/*` → FastAPI (port 8000), everything else → Flask (port 5000). 36/36 parity tests pass. All 6 edgar-mcp tools + AI-excel-addin gateway validated. No client code changes needed.

**Remaining (Phase 4):** Remove dead Flask `/api/*` route handlers from `app.py` after 1-week stability gate (~March 6). Optionally migrate `/generate_key` webhook to FastAPI. Audit doc: `Edgar_updater/docs/plans/PLAN-fastapi-migration-audit.md`.

### Earnings Estimates: Collection Failure Skip-List — Verify in Production
Skip-list implemented and deployed (commit `5b8268d` edgar_updater, `6f14ceb6` risk_module). 142 failures from run 1 investigated — all benign: `no_estimates` (95 tickers: warrants, preferred, micro-caps) and `no_income_statement` (6 tickers). Zero `api_error`. `get_skip_set()` added to `EstimateStore` with 180-day decay window. Wired into collector with `--ignore-skip-list` and `--skip-min-runs` flags. After run 2, persistent failures will be auto-skipped on run 3+. Verify skip-list log output after next monthly run (April 1).

### Research & AI
- Perplexity MCP — evaluate Perplexity as research/search layer for the investment agent. Compare vs Brave Search.

### Frontend: AI-Assisted UI Component Development
Gateway channel is live. Use Claude with the frontend browser plugin (or Antigravity/Gemini) to adjust, modify, and create UI components that match key functionality. Goal: build a starter kit of polished components that cover the core use cases (risk dashboard, portfolio overview, analysis views, settings). The AI can iterate on layout, styling, and interaction patterns directly in the browser with live feedback.

### Frontend: Agent-Driven Dynamic UI Generation
Design the chassis + UI infrastructure so that AI agents (analyst-claude, design-claude, visualizer-claude) can build on-the-fly visualizations, workflow UIs, and app scaffolding at runtime. The idea: when a Claude skill needs a visualization or interactive workflow that doesn't exist yet, the agent generates the component dynamically using the chassis primitives and Radix building blocks. This could mean:
- A component registry that agents can populate at runtime
- A schema-driven renderer that turns agent output into live React components
- Workflow templates that map to Claude skills (e.g., "earnings review" skill → multi-step UI with charts, tables, and action buttons)
- Sandbox/preview mode so generated UIs can be validated before persisting
- Versioning so good generated UIs get saved as reusable templates

This is the longer-term vision — the chassis + gateway architecture is the foundation that makes this possible.

### Workflow Gaps: Hedging Infrastructure
Identified during hedging workflow definition (see `docs/planning/WORKFLOW_DESIGN.md`). These are building blocks needed for the full hedge-to-execution pipeline, but each is independently useful.

- [ ] **Multi-leg options execution** — `preview_option_trade()` / `execute_option_trade()` for atomic multi-leg orders (spreads, collars, strangles). Currently must execute legs individually via `preview_trade()` which creates slippage risk between legs. IBKR supports combo/BAG orders for options (same pattern as futures roll).
- [x] ~~**Batch scenario comparison**~~ — COMPLETE. `compare_scenarios(mode="whatif")` runs N hedging scenarios, ranks by vol_delta/conc_delta. Commit `56d773a8`.
- [x] ~~**Rebalance-to-target trade generator**~~ — COMPLETE. `generate_rebalance_trades()` MCP tool. Commit `e19f9e28`.
- [ ] **Live options pricing** — Real-time bid/ask/mid from IBKR via `fetch_snapshot()` for options contracts. Current `analyze_option_strategy()` uses Black-Scholes model pricing. Related to the IBKR live Greeks path below.
- [ ] **Continuous hedge monitoring** — Alerts when portfolio drifts beyond hedge targets, hedge ratios become stale, or expiring options need rolling. Requires some form of periodic check or event-driven monitoring — may tie into the autonomous analyst / scheduled agent infrastructure.

### Workflow Gaps: Cross-Cutting Infrastructure
Identified across all 7 workflow definitions (see `docs/planning/WORKFLOW_DESIGN.md`). These gaps appear in 3+ workflows and are the highest-leverage items to build.

- [x] ~~**Rebalance trade generator**~~ — COMPLETE. `generate_rebalance_trades()` MCP tool in `mcp_tools/rebalance.py`. Accepts `target_weights` or `weight_changes`, produces sequenced BUY/SELL legs. Shared helpers in `mcp_tools/trading_helpers.py`. 26 tests. Commit `e19f9e28`.
- [x] ~~**Batch scenario/optimization comparison**~~ — COMPLETE. `compare_scenarios()` MCP tool in `mcp_tools/compare.py`. Runs N scenarios on same portfolio (deep-copied per run), ranks by configurable metric, 5 comparison-level flags. 32 tests. Commit `56d773a8`. Plan: `BATCH_COMPARISON_PLAN.md`.
- [ ] **Action audit trail** — Persist which recommendations were generated, accepted, rejected, and executed. No tracking today — conversation context only. Needed by: Risk Review, Allocation Review, Performance Review.

### Workflow Gaps: Scenario & Strategy Infrastructure
Identified during Scenario Analysis and Strategy Design workflow definitions.

- [ ] **Predefined scenario templates** — Backend-driven templates ("defensive rotation", "growth tilt", "derisking") with configurable intensity. Currently templates are hardcoded in frontend only.
- [ ] **Stress test presets** — Predefined market shock scenarios ("market -20%", "rates +200bp", "stagflation") that translate to delta_changes. No backend implementation today.
- [ ] **Scenario persistence** — Save/load/history for scenario runs. Currently fire-and-forget.
- [ ] **Return attribution (Brinson/Fama-French)** — Decompose portfolio returns by factor/sector/selection. Fields exist in `PerformanceResult` but are never populated. Needed by Performance Review workflow.
- [ ] **Backtesting engine** — Historical strategy validation (walk-forward, out-of-sample). No implementation exists. Needed by Strategy Design workflow.
- [ ] **Efficient frontier visualization** — Plot optimal portfolios across risk/return spectrum. Requires running optimization at many vol targets. Needed by Strategy Design workflow.
- [ ] **Strategy versioning** — Track strategy iterations with constraint snapshots and optimization results. Currently save-as-basket only workaround.

### Options: Portfolio Risk Integration
Core options module complete. IBKR integration done. Chain analysis MCP tool done (`analyze_option_chain` on portfolio-mcp, commit `cd9f032b`). Phases 1-2 complete.
- [x] Expose `chain_analysis.py` via MCP tool (OI/volume by strike, put/call ratio, max pain) — COMPLETE
- [x] Option position enrichment — `enrich_option_positions()` with contract metadata (strike, expiry, underlying, DTE), 3 position flags (near_expiry, expired, concentration). Commit `6e62c5d6`.
- [x] Portfolio Greeks aggregation — `compute_portfolio_greeks()` with dollar-scaled delta/gamma/theta/vega, wired into `get_exposure_snapshot()`, 4 Greeks flags (theta_drain, significant_net_delta, high_vega, computation_failures). Commit `6e62c5d6`.
- [ ] IBKR live Greeks path — use `fetch_snapshot()` for real-time Greeks instead of computed (Black-Scholes) path. Per-position fallback when TWS unavailable.

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

### Investment Idea Ingestion System
Source-agnostic pipeline to ingest ideas from any origin (manual reading, newsletters, screens, insider trades, corporate events, earnings, etc.) into the ticker memory workspace. Ideas flow through a common schema and pipeline — adding a new source is just writing a new connector.

**Design docs:**
- System design: `docs/planning/IDEA_INGESTION_SYSTEM_DESIGN.md`
- Phase 1 plan (Codex-reviewed, PASS): `AI-excel-addin/docs/design/idea-ingestion-phase1-plan.md`
- Phase 2 plan (5 Codex reviews, PASS): `AI-excel-addin/docs/design/idea-ingestion-phase2-connectors.md`
- Connector dev guide: `AI-excel-addin/docs/design/connector-development-guide.md`
- Source tool dev guide: `investment_tools/docs/IDEA_SOURCE_DEVELOPMENT_GUIDE.md`

**Architecture:** Connectors → `IdeaPayload` → `ingest.py` → ticker markdown files → watcher → SQLite. File-based, no API needed. Ticker memory workspace is the canonical store.

**Phases:**
1. ~~**Pipeline core**~~ — COMPLETE. `IdeaPayload` dataclass + `ingest_idea()` + `ingest_batch()` in `api/memory/ingest.py`. Dedup (create vs append), source log audit trail, strict ticker validation. 36 tests. Commit `632a551`.
2. ~~**First connectors**~~ — COMPLETE. Two connectors in `api/memory/connectors/`: `from_estimate_revisions()` (estimate revision screen → IdeaPayloads) and `from_quality_screen()` (quality screener → IdeaPayloads). Pure functions, None-safe, NaN-safe, conditional pandas. 28 tests. Commit `de30308`.
3. **Enrichment workflow** — `fmp_profile` on new tickers (sector, market cap). Tiered enrichment on stage advancement.
4. **Additional connectors** — Newsletter (Gmail MCP), insider trades, corporate events, earnings transcripts. Each independent.
5. **Analyst-claude queue** — Idea pickup + triage workflow, enrichment tied to process stage transitions.

**Process stages:** `idea` → `initial_review` → `diligence` → `decision` → `monitoring`
- Two attributes on each ticker: `status` (what it is — `idea`) and `process_stage` (where it is in the workflow)
- Both set to `idea` on ingestion, `process_stage` advances as research progresses

**TODO — Process stage definitions:**
- [ ] Define process stage transitions and criteria (what triggers advancement from `idea` → `initial_review`, etc.)
- [ ] Update analyst-claude system prompt / AGENT.md with process stage definitions so it knows when to advance ideas
- [ ] Define what enrichment tier runs at each stage (Tier 1 at initial_review, Tier 2 at diligence, Tier 3 at decision)

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
