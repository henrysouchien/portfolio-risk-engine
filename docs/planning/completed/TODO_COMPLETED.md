# Completed TODO Items

Items moved from `docs/planning/TODO.md` as they were completed. Most recent first.

---

### 2026-03-01 — Workflow Design Phase 1: All 7 Workflows Defined
Audited all 7 frontend views and defined complete 5-step workflows with tool mappings, inputs/outputs, and gap analysis. Design doc: `docs/planning/WORKFLOW_DESIGN.md` (2,457 lines). Workflows: Hedging, Scenario Analysis, Allocation Review, Risk Review, Performance Review, Stock Research, Strategy Design. Cross-cutting gaps identified: rebalance trade generator (all 7), batch comparison (3), action audit trail (3). Workflow-specific gaps catalogued (templates, backtesting, attribution, frontier, versioning). Commits: `5df192f2` through `92f99987`.

### 2026-03-01 — Trading Analysis: Date Range Parameters
Added `start_date`/`end_date` to `get_trading_analysis()` MCP tool. FIFO runs on full history, results filtered post-analysis. Income pre-filtered. Aggregates recomputed; grades/behavioral/return-stats nulled for partial windows. 33 tests. Commit `5919122e`.
See: `docs/planning/TRADING_DATE_RANGE_PLAN.md`

### Earnings Estimates: Investigate Collection Failures — COMPLETE (2026-03-01)
Investigated 142 failures from first snapshot run. Breakdown: `no_estimates` 136 records (95 tickers — warrants, preferred shares, Toronto-listed, micro-caps with no analyst coverage), `no_income_statement` 6 records (6 tickers). Zero `api_error` — infra healthy. All failures benign, no systemic bugs or ticker format issues. 2.9% failure rate out of 4,880 tracked tickers.

Implemented skip-list: `get_skip_set()` on `EstimateStore` queries `collection_failures` for tickers failing 2+ runs with persistent error types, within 180-day decay window. Wired into `run_collection()` after universe build, before freshness check. CLI flags: `--ignore-skip-list`, `--skip-min-runs`. Stored `universe_snapshot` NOT modified (auditability). Tests: 6 passing. Plan: `docs/planning/ESTIMATE_SKIP_LIST_PLAN.md`. Codex review: R1 FAIL, R2 FAIL, R3 PASS. Commits: `5b8268d` (edgar_updater), `6f14ceb6` (risk_module sync).

---

### 2026-03-01 — Options Portfolio Risk Integration (Phases 1-2)
Option position enrichment + portfolio Greeks aggregation. `enrich_option_positions()` adds contract metadata (strike, expiry, underlying, DTE) to option positions at 3 call sites. `compute_portfolio_greeks()` aggregates dollar-scaled delta/gamma/theta/vega across all option positions, wired into `get_exposure_snapshot()`. 3 position flags (near_expiry, expired, concentration) + 4 Greeks flags (theta_drain, net_delta, high_vega, computation_failures). IBKR live Greeks path deferred. 76 tests. Commit `6e62c5d6`.
See: `docs/planning/OPTIONS_PORTFOLIO_RISK_PLAN.md`

### 2026-03-01 — Environment Variable & Config Consolidation
Removed redundant `load_dotenv()` from 4 library modules, eliminated duplicate IBKR env var reads in `brokerage/config.py` (now imports from `ibkr/config.py`), deleted 12 dead Schwab/SnapTrade credential vars from `settings.py`, moved `FRONTEND_BASE_URL` to single source, standardized `ibkr/server.py` override semantics, fixed frontend `VITE_API_BASE_URL` → `VITE_API_URL` naming mismatch. 16 files, 2084 tests passing. Commit `def8fd3f`.
See: `docs/planning/ENV_CONFIG_CONSOLIDATION_PLAN.md`

### 2026-02-28 — Realized Performance: Bond/Treasury Pricing via CUSIP
Security identifiers (CUSIP/ISIN/FIGI) captured and threaded into `PortfolioData.security_identifiers`. `resolve_bond_contract()` extended with CUSIP fallback. CUSIP → IBKR conId resolver via `reqContractDetails()` + `secIdList` matching. Live-tested: CUSIP 912810EW4 → conId 15960420 → 7 monthly closes. US Treasury bonds supported (prefix 912 → symbol US-T). Corporate bonds deferred. 18 new tests.
See: `docs/planning/BOND_PRICING_CUSIP_RESOLVER_PLAN.md`, `docs/planning/BOND_CUSIP_REQCONTRACTDETAILS_PLAN.md`

### 2026-02-28 — Futures Phase 7: Contract Verification (ESTX50, DAX)
Live-tested ESTX50 and DAX against TWS (port 7496). Both resolve, qualify, and return monthly close data. ESTX50 priced via FMP `^STOXX50E`; DAX via IBKR fallback (`^GDAXI` returns 402). IBV removed from catalog — no CME Ibovespa futures product found on IBKR (27→26 contracts). Added repeatable verification runbook.
See: `docs/reference/FUTURES_CONTRACT_VERIFICATION.md`, `docs/planning/FUTURES_DESIGN.md`

### 2026-02-28 — Schwab Per-Account Realized Performance Aggregation
Per-account aggregation for Schwab realized performance. Investigation + implementation. Commit `8ce1a340`.
See: `docs/planning/SCHWAB_PER_ACCOUNT_PLAN.md`

### 2026-02-28 — P4 Hedging Strategies (Frontend Wiring)
Frontend hedging tab wired to backend `portfolio-recommendations` endpoint. `useHedgingRecommendations` hook + `HedgingAdapter` + container wiring. Backend fixes: ETF→sector label resolution, correlation threshold adjustment, driver label resolution. Commits `1c66dae7`, `475a67e5`.
See: `docs/planning/FRONTEND_HEDGING_WIRING_PLAN.md`

### 2026-02-28 — Futures Phase 5: Performance + Trading
Futures P&L metadata threading + segment filter on `get_trading_analysis()`. Commits `a5f82977`, `0a7b2691`.
See: `docs/planning/FUTURES_DESIGN.md`

### 2026-02-28 — Earnings Estimates: AWS Migration Complete (All 9 Steps)
All 9 steps done. Local fallback removed (`7d9dab24`), HTTP-only with hardcoded default URL. EC2 systemd timer active. fmp-mcp 0.2.0 on PyPI. Commit `08febe10`.
See: `docs/planning/EARNINGS_ESTIMATE_AWS_MIGRATION_PLAN.md`, `docs/planning/ESTIMATE_CLEANUP_PLAN.md`

### 2026-02-27 — Stock Basket / Custom Index (All 5 Phases Complete)
Full basket feature: CRUD, analysis, custom factor injection, multi-leg trading, and ETF seeding.
- Phase 1: CRUD MCP tools — `create_basket`, `list_baskets`, `get_basket`, `update_basket`, `delete_basket` (commit `39930617`)
- Phase 2: Basket returns analysis — `analyze_basket` with Sharpe, drawdown, alpha/beta, component attribution, portfolio correlation (commit `240f00ea`)
- Phase 3: Basket as custom factor — inject into `get_factor_analysis()` alongside standard factors (commit `509326b0`)
- Phase 4: Multi-leg trade execution — `preview_basket_trade`, `execute_basket_trade` (commit `7b3b78c2`)
- Phase 5: ETF seeding — `create_basket_from_etf` from FMP holdings (commit `4d98b43d`)
See: `docs/planning/STOCK_BASKET_PLAN.md`

### 2026-02-27 — Option Chain Analysis MCP Tool
`analyze_option_chain` on portfolio-mcp. Exposes OI/volume concentration, put/call ratio, max pain via live IBKR chain data. Raw-dict agent format with 9 interpretive flags. 19 tests, 53 total options tests. Codex-reviewed plan (2 rounds, 8/8 PASS).
See: `docs/planning/OPTION_CHAIN_MCP_PLAN.md`

### 2026-02-27 — MCP Positions Enrichment (P1-MCP)
Added sector breakdown, P&L summary, enriched top holdings, and 4 new flags to `get_positions(format="agent")`. Reuses holdings enrichment `to_monitor_view()` + `enrich_positions_with_sectors()`. Commit `d37bcdbc`.
See: `docs/planning/MCP_POSITIONS_ENRICHMENT_PLAN.md`

### 2026-02-27 — Futures Phase 3: Portfolio Integration
Futures in holdings view with margin + notional overlay. Commit `dcf481a0`.
See: `docs/planning/FUTURES_DESIGN.md`

### 2026-02-27 — Futures Phase 4: Risk Integration
Notional weights, proxy factors (macro/asset-class instead of equity), segment view. Commit `a1c4aefc`.
See: `docs/planning/FUTURES_DESIGN.md`

### 2026-02-27 — Earnings Estimates: AWS Migration Steps 1-8
RDS created, estimates package, API routes, systemd timer, MCP HTTP migration, data migrated (59,546 snapshots), deployment scripts, API live + fmp-mcp 0.2.0 on PyPI. Only Step 9 cleanup remaining.
See: `docs/planning/EARNINGS_ESTIMATE_AWS_MIGRATION_PLAN.md`

### 2026-02-27 — Options Tools: Core Module
Full `options/` package with `OptionLeg`/`OptionStrategy` class framework, payoff calculator (max profit/loss, breakevens, P&L at various DTE), Greeks computation, and `analyze_option_strategy` MCP tool with `format="agent"` support. Remaining: IBKR OI integration, IBKR chains/Greeks as data source, portfolio risk integration.

### 2026-02-27 — Architecture: Pricing Provider Pluggability Review
Completed the pricing provider refactor plan across equity/general pricing paths. Legacy `PriceProvider` now delegates to registry-backed providers, FX routing goes through `get_fx_provider()`, scattered `fmp.fx` pricing-path imports were reduced, and provider integration tests were added for registry custom-provider handling, `set_price_provider()` override behavior, and `data_loader.fetch_monthly_close()` registry flow.
See: `docs/planning/PRICING_PROVIDER_REFACTOR_PLAN.md`

### 2026-02-27 — Futures Phase 2: Pricing Dispatch + Pluggable Pricing Chain
Decoupled contract catalog from IBKR into `brokerage/futures/contracts.yaml` (27 contracts). Built pluggable `FuturesPricingChain` protocol with broker-agnostic `alt_symbol` parameter — default chain: FMP commodity endpoints → IBKR historical data fallback. Added futures dispatch to `latest_price()` and `get_returns_dataframe()` via `instrument_types` dict. Threaded `instrument_types` through ~20 call sites (config_adapters, optimization, performance, risk score, scenario, portfolio_optimizer full chain, portfolio_service special case, factor_intelligence). Second pass in `to_portfolio_data()` populates `fmp_ticker_map` from contract specs. Slimmed `ibkr/exchange_mappings.yaml` (removed multiplier/tick_size/fmp mapping). Live tested: ES $6,874.75, GC $5,257.40 via FMP. 11/27 FMP symbols working (rest 402 — IBKR fallback). 56 new tests, 1943 total passing. Codex-reviewed plan (18 rounds).
See: `docs/planning/FUTURES_P2_PRICING_DISPATCH_PLAN.md`, `docs/planning/FUTURES_DESIGN.md`

### 2026-02-26 — Futures Phase 1: Data Foundation
Created `brokerage/futures/` package with `FuturesContractSpec` frozen dataclass (27 contracts), notional/P&L/tick value calculations, and asset class taxonomy (equity_index, fixed_income, metals, energy). Extended `ibkr/exchange_mappings.yaml` with multiplier + tick_size. Added `get_ibkr_futures_contract_meta()` to `ibkr/compat.py` (backward compatible). 34 new tests, 1814 total passing. Codex-reviewed plan (2 rounds, 3 spec corrections: IBV, DAX, ZT).
See: `docs/planning/FUTURES_P1_DATA_FOUNDATION_PLAN.md`, `docs/planning/FUTURES_DESIGN.md`

### 2026-02-26 — Security Identifier Capture + Currency Classification
Captured CUSIP/ISIN from Plaid, CUSIP from Schwab, FIGI from SnapTrade — threaded through PositionService consolidation into new `PortfolioData.security_identifiers` field. Added explicit CUR:XXX → cash detection in SecurityTypeService `get_security_types()` and `get_asset_classes()`. Extended `to_portfolio_data()` is_cash check to honor provider `is_cash_equivalent` flag. Bond positions now log available identifiers. 1794 tests passing. Codex-reviewed plan (3 rounds).
See: `docs/planning/SECURITY_IDENTIFIERS_PLAN.md`

### 2026-02-25 — Architecture: MCP Error Handling Decorator
Extracted shared `@handle_mcp_errors` decorator into `mcp_tools/common.py`. Applied to 20 tool functions across 12 files, removing ~200 lines of duplicated stdout-redirect + try/except boilerplate. 603 tests passing.
See: `docs/planning/MCP_ERROR_DECORATOR_PLAN.md`

### 2026-02-25 — Architecture: Break Up result_objects.py
Converted `core/result_objects.py` (355KB) into `core/result_objects/` package with 10 domain submodules + `__init__.py` re-exports (commit `3758c186`).

### 2026-02-25 — Architecture: Consolidate Config Files
Extracted cohesive groups from `settings.py` (853→454 lines) into natural package homes with backward-compatible re-exports. Phase 1: user resolution → `utils/user_context.py`. Phase 2: routing tables → `providers/routing_config.py`. Phase 3: IBKR gateway vars re-exported from `ibkr/config.py`. No cross-package coupling. 3 Codex review rounds.
See: `docs/planning/CONFIG_CONSOLIDATION_PLAN.md`

### 2026-02-25 — Architecture: Clarify IBKR Dual Entry Points
`ibkr/client.py` (facade for data) vs `brokerage/ibkr/adapter.py` (trade execution) confirmed as architecturally correct. Added adapter docstring cross-reference and removed dead shim `services/ibkr_broker_adapter.py`.
See: `docs/planning/IBKR_DUAL_ENTRY_CLEANUP_PLAN.md`

### 2026-02-25 — Gateway Channel Integration (All Phases Complete)
Full gateway channel migration across both repos. Risk-module: backend proxy + frontend wiring (Phase 0+3). AI-excel-addin: portfolio-mcp allowlist, channel filtering, prompt awareness (Phases 1-2), AgentRunner sole chat path cutover (Phase 4).
See: `docs/planning/portfolio-channel-task.md`, `docs/design/portfolio-tool-parity.md`

### 2026-02-25 — Surface IBKR TWS Connection Status + Graceful Provider Auth Failures
Implemented in `8a38713a`. Provider status surfaced in both positions and performance agent responses. IBKR pricing degradation detected via `IBKR_PRICING_REASON_CODES`. Per-provider try/except in `get_all_positions()`, errors in `_cache_metadata`, `provider_error` flags in `position_flags.py`, `provider_status` dict in agent responses.
See: `docs/planning/PROVIDER_STATUS_PLAN.md`

### 2026-02-25 — Gateway Channel Integration Phase 0+3
Backend proxy (`routes/gateway_proxy.py`) + frontend `GatewayClaudeService` for web-channel chat through the shared AI gateway. Per-user session stickiness, SSE passthrough, stream locking, 401 token refresh, tool-approval flow (approve/deny banner in ChatCore). Feature flag `VITE_CHAT_BACKEND=legacy|gateway` for coexistence. Parity audit: 10/16 legacy tools mapped, 6 intentionally dropped, 0 gaps. 11 unit tests, live end-to-end verified.
See: `docs/planning/portfolio-channel-task.md`, `docs/design/portfolio-tool-parity.md`

### 2026-02-25 — All 7 Agent Format Tools Live-Tested
Live-tested all 7 `format="agent"` tools against real portfolio data: `get_positions`, `get_performance`, `get_trading_analysis`, `analyze_stock`, `run_optimization`, `run_whatif`, `get_factor_analysis`. All returning structured snapshots + flags. MCP agent audit updated — all HIGH+MEDIUM priority tools now grade A.
See: `docs/planning/MCP_AGENT_AUDIT.md`

### 2026-02-25 — Agent-Optimized Factor Analysis Output
Added `format="agent"` + `output="file"` to `get_factor_analysis()`. Three-layer architecture across all 3 analysis modes. Interpretive flags in `core/factor_flags.py` dispatch by `analysis_type`. 21 Codex review rounds, 90 new tests.
See: `docs/planning/completed/FACTOR_ANALYSIS_AGENT_FORMAT_PLAN.md`

### 2026-02-25 — Agent-Optimized What-If Output
Added `format="agent"` + `output="file"` to `run_whatif()`. Three-layer architecture: `get_agent_snapshot()` on `WhatIfResult` → `core/whatif_flags.py`. 5 Codex review rounds, 64 new tests.
See: `docs/planning/completed/WHATIF_AGENT_FORMAT_PLAN.md`

### 2026-02-25 — Agent-Optimized Optimization Output
Added `format="agent"` + `output="file"` to `run_optimization()`. Three-layer architecture: `get_agent_snapshot()` on `PortfolioOptimizationResult` → `core/optimization_flags.py`. 7 Codex review rounds, 51 new tests.
See: `docs/planning/completed/OPTIMIZATION_AGENT_FORMAT_PLAN.md`

### 2026-02-25 — Factor Performance Double-Scaling Bug Fix
Fixed `FactorPerformanceResult.get_agent_snapshot()` double-scaling `annual_return_pct` and `volatility_pct`. Upstream `compute_performance_metrics()` already returns values in percent. 2 tests updated.

### 2026-02-24 — NaN → null in Agent JSON Output
Fixed `make_json_safe()` in `utils/serialization.py` to coerce `float('nan')` and `np.float64('nan')` to `None`. All callers of `make_json_safe` benefit from the fix.

### 2026-02-24 — Frontend Logging Overhaul
Overhauled frontend logging system (`frontendLogger.ts`). JWT token sanitization, EventBus/UnifiedAdapterCache suppression (~43% noise removed), React StrictMode dedup, silent cache warming, semantic data summaries, session summaries via `sendBeacon`, error context enrichment, data truncation. 7 files changed, ~60-70% log volume reduction.
See: `docs/planning/completed/FRONTEND_LOGGING_PLAN.md`

### 2026-02-24 — Agent-Optimized Performance Output
Added `format="agent"` + `output="file"` to `get_performance()`. 12 interpretive flags in `core/performance_flags.py`. Also fixed pre-existing `_categorize_performance()` bug. 10 Codex review rounds, 43 new tests.
See: `docs/planning/completed/PERFORMANCE_AGENT_FORMAT_PLAN.md`

### 2026-02-24 — Agent-Optimized Positions Output
Added `format="agent"` + `output="file"` to `get_positions()`. Interpretive flags in `core/position_flags.py`. 4 Codex review rounds. Also created MCP agent audit doc.
See: `docs/planning/completed/POSITIONS_AGENT_FORMAT_PLAN.md`, `docs/planning/MCP_AGENT_AUDIT.md`

### 2026-02-24 — Plaid Re-Authentication via Link Update Mode
Full re-auth flow for expired Plaid OAuth connections (`ITEM_LOGIN_REQUIRED`). Backend, frontend, CLI, DB migration. 9 Codex review rounds, tested end-to-end.
See: `docs/planning/completed/PLAID_REAUTH_PLAN.md`

### 2026-02-24 — Frontend Three-Package Split
Split frontend monolith into pnpm workspace with three packages: `@risk/chassis`, `@risk/connectors`, `@risk/ui`. Includes CRA → Vite migration, 32 wrapper shim cleanup, ESLint standalone config migration, render bug fix, ticker validation fix. 400 files changed.
See: `docs/planning/completed/FRONTEND_PACKAGE_SPLIT_PLAN.md`, `docs/planning/completed/FRONTEND_WRAPPER_CLEANUP_PLAN.md`

### 2026-02-23 — Brokerage Package Extraction
Extracted pure broker API layer into standalone `brokerage/` package. Three-layer split. 1143 tests passing, live smoke tests verified.
See: `docs/planning/completed/BROKERAGE_CONNECT_PLAN.md`

### 2026-02-19 — Plaid/SnapTrade Cost Reduction
Full webhook-driven refresh notification pipeline. Phases 1-5+7 complete. Only remaining: deploy SnapTrade relay route (Phase 6 infra — see `WEBHOOK_RELAY_SETUP.md`).
See: `docs/planning/completed/PLAID_COST_REDUCTION_PLAN.md`, `docs/planning/completed/WEBHOOK_REFRESH_NOTIFICATION_PLAN.md`

### 2026-02-19 — Logging System Overhaul
Rewrote logging from 2,208 to 856 lines. 104 files changed, -4,327 net lines.
See: `docs/planning/completed/LOGGING_OVERHAUL_PLAN.md`

### 2026-02-18 — Risk Preferences Config Layer
Moved from baked-in limits to preferences-first model. User intent stored as first-class config, limits derived at analysis time.

### 2026-02-18 — RiskAnalysisResult Redundancy Cleanup
Removed `risk_checks`, `beta_checks`, and nested `industry_variance` from `to_api_response()`.
See: `docs/planning/completed/RISK_ANALYSIS_RESULT_CLEANUP_PLAN.md`

### 2026-02-18 — Profile-Based Risk Limits
Added 4 risk profiles with `set_risk_profile()` and `get_risk_profile()` MCP tools.
See: `docs/planning/completed/RISK_LIMITS_PROFILE_PLAN.md`

### 2026-02-18 — Agent-Optimized Risk Analysis Output
Implemented `format="agent"` + `output="file"` for `get_risk_analysis()`.
See: `docs/planning/completed/RISK_ANALYSIS_AGENT_FORMAT_PLAN.md`

### 2026-02-17 — Interface Documentation Debt Cleanup
Cleared stale MCP tool count references, documented OpenAPI and CI posture.
See: `docs/interfaces/README.md`, `docs/interfaces/mcp.md`, `docs/interfaces/test-matrix.md`

### 2026-02-17 — Provider-Native Flows: Plaid, SnapTrade, IBKR
Extended provider-native flows to all remaining providers. Coverage gating and validation complete.
See: `docs/planning/completed/PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md`

### 2026-02-17 — Schwab Dividend Description → Ticker Resolution (Bug 23)
Fixed unresolved ENB dividends ($612).
See: `docs/planning/completed/SCHWAB_DIVIDEND_RESOLUTION_PLAN.md`

### 2026-02-17 — Portfolio Manager Complexity Audit + Refactor (Phase 1)
Extracted repository, assembler, and legacy file helper services. PortfolioManager is now a thin facade.
See: `docs/planning/completed/PORTFOLIO_MANAGER_COMPLEXITY_AUDIT.md`
