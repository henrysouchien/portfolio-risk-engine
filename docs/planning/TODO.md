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
- **Rebalance trade generator** (highest leverage) — all 7 execution steps need weight → shares → trade list
- **Batch scenario/optimization comparison** — Hedging, Scenarios, Strategy all need parallel run + rank
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

## Backlog

### Target Allocations: DB Setup + Population
`target_allocations` table schema defined in `database/schema.sql` but not yet migrated. Drift detection infrastructure is fully built (`allocation_drift.py`, threaded through risk pipeline + frontend) — just needs actual target data.
- [ ] Run DB migration to create `target_allocations` table
- [ ] Define default target allocations for the main portfolio (e.g., Equity 60%, Fixed Income 25%, Real Estate 10%, Commodities 5%)
- [ ] Add MCP tool or API endpoint to set/update target allocations per portfolio
- [ ] Optional: historical allocation trend tracking (periodic snapshots for time-series view)

### IBKR Direct Trading via IB Gateway
SnapTrade IBKR connection is **Flex (read-only)** — `preview_trade` returns `"Brokerage INTERACTIVE-BROKERS-FLEX does not support trading"`. To trade IBKR positions, need to route through the direct IBKR adapter (`brokerage/ibkr/adapter.py`) which connects to IB Gateway.

**Investigation findings (2026-03-01):**
- Account `cb7a1987-bce1-42bb-afd5-6fc2b54bbf12` resolves correctly via SnapTrade
- Symbol resolution works for existing portfolio tickers (NVDA), fails for non-portfolio tickers (AAPL) on Flex
- BUY passes validation but fails on buying power (margin account, expected)
- SELL hits the wall: SnapTrade Flex doesn't support order placement
- Schwab trading works fine (3 accounts: `25524252`, `87656165`, `51388013`)

**What exists:**
- `brokerage/ibkr/adapter.py` — IBKR trading adapter with `preview_order()` / `place_order()` via IB Gateway
- `ibkr/client.py` — IBKRClient facade (read-only data, client ID 20)
- Trading adapter uses client ID 22 (separate from ibkr-mcp on 20 and market data on 21)
- `IBKR_AUTHORIZED_ACCOUNTS` env var for account whitelist

**TODO:**
- [ ] Register `IBKRBrokerAdapter` in `TradeExecutionService` alongside SnapTrade/Schwab adapters
- [ ] Configure `IBKR_AUTHORIZED_ACCOUNTS` with the real IBKR account number (U-series, not SnapTrade UUID)
- [ ] Ensure IB Gateway is running when trading (auto-start or pre-flight check)
- [ ] Account routing: detect when a position came from SnapTrade-IBKR-Flex and route trades to direct IBKR adapter instead
- [ ] Test end-to-end: preview → confirm → execute for an IBKR equity order

### Concentration: Denominator Choice for Position Flags
`core/position_flags.py` uses `gross_non_cash` (sum of abs(value) of all non-cash positions) as the denominator for concentration thresholds. For levered portfolios this dilutes concentration — DSU at 35% of net equity shows as 28% of gross positions, potentially missing the threshold. Consider switching to `total_value` (net equity) as the denominator, which better captures leverage-amplified concentration risk. Alternatively, offer both views or use the more conservative denominator.

### Frontend: SDK Testing
Vitest installed and configured. One test file exists (`chassis/src/services/__tests__/DataCatalog.test.ts`). Remaining coverage needed: classifyError (HTTP status mapping, edge cases), useDataSource (resolver integration, loading/error states), conformance checks (descriptor fields match adapter output types), interaction primitives (useSharedState, useFlow). Also test migrated hooks (useRiskScore, useRiskAnalysis, usePerformance) to verify they produce the same output as before via the resolver path.

### Realized Performance: Investigate Bad Data Quality
`get_performance(mode="realized", format="agent")` shows poor data quality across all providers. Coverage is low everywhere: Schwab 37.5%, Plaid 12.5%, SnapTrade 0%. Combined gives 58% with 14 synthetic positions.
- **Schwab specifically looks off**: 176% total return, Sharpe 1.60 — likely inflated by missing cost basis on 19 synthetic positions. Needs investigation.
- **SnapTrade**: 0% coverage, all 24 positions synthetic — essentially no transaction data.
- **Plaid**: 12.5% coverage, 24 synthetic — minimal data.
- Need to diagnose whether this is a transaction sourcing gap, synthetic position inference issue, or cash flow reconstruction problem.

### Architecture: Break Up Large Monolithic Files
- `core/realized_performance_analysis.py` (115KB) — extract pricing chain logic
- Note: `core/result_objects.py` already split into `core/result_objects/` package (10 submodules, commit `3758c186`)

### Architecture: Fix Circular Imports in app.py
`app.py` is a 4,602-line monolith with a massive top-level import block (lines 108-223) pulling from models, core/result_objects, inputs, run_risk, services/*, utils/*, and many other internal modules. This causes circular import issues as the dependency graph grows. Needs investigation into which imports are circular, then fix via:
- Lazy imports (move imports inside functions that need them)
- Route module extraction (break app.py into smaller route blueprints)
- Breaking up the file itself (app.py shouldn't define routes + helpers + initialization all in one place)
- `routes/claude.py` already extracted as a pattern to follow

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
- [ ] **Batch scenario comparison** — Evaluate multiple hedge candidates in one call and rank by risk-reduction / cost efficiency. Current `run_whatif()` is single-scenario only. May need to refactor what-if to accept a list of scenarios, or build a separate `compare_scenarios()` orchestrator. Also evaluate whether `run_whatif()` needs to be more flexible generally (e.g., support mixed instrument types, options payoffs in the risk model).
- [ ] **Rebalance-to-target trade generator** — Given current portfolio + target weights (from optimization, what-if, or manual), auto-generate the trade list with share quantities, estimated costs, and suggested execution sequence. Currently must manually calculate deltas from what-if output and create trades one by one.
- [ ] **Live options pricing** — Real-time bid/ask/mid from IBKR via `fetch_snapshot()` for options contracts. Current `analyze_option_strategy()` uses Black-Scholes model pricing. Related to the IBKR live Greeks path below.
- [ ] **Continuous hedge monitoring** — Alerts when portfolio drifts beyond hedge targets, hedge ratios become stale, or expiring options need rolling. Requires some form of periodic check or event-driven monitoring — may tie into the autonomous analyst / scheduled agent infrastructure.

### Workflow Gaps: Cross-Cutting Infrastructure
Identified across all 7 workflow definitions (see `docs/planning/WORKFLOW_DESIGN.md`). These gaps appear in 3+ workflows and are the highest-leverage items to build.

- [ ] **Rebalance trade generator** — Given current weights + target weights + portfolio value, auto-generate sequenced trade list (sells first to free capital, then buys) with share quantities, estimated costs, and odd-lot handling. Needed by: all 7 workflows at execution step. Currently must manually compute from what-if `position_changes`.
- [ ] **Batch scenario/optimization comparison** — Run N scenarios or optimizations in parallel and return a ranked comparison table. Currently must call `run_whatif()` or `run_optimization()` per variant and assemble manually. Needed by: Hedging (Step 4), Scenarios (Step 3), Strategy Design (Step 3).
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
