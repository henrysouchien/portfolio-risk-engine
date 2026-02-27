# Completed TODO Items

Items moved from `docs/planning/TODO.md` as they were completed. Most recent first.

---

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
