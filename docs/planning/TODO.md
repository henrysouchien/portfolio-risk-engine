# TODO

Active work items and setup tasks.

## In Progress

### 1. Provider-Native Flows: Plaid, SnapTrade, IBKR (Priority)
Framework and Schwab flows are complete. Extend to remaining providers:
- [x] **Plaid/SnapTrade** — wire up FetchMetadata so coverage gating eligibility/diagnostics works
- [x] **IBKR Flex** — parse cash sections (deposits, withdrawals, fees) beyond Trade rows
- [x] Add focused validation for provider coverage gating + IBKR cash-section parsing
- See: `PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md`
- Next: `PROVIDER_NATIVE_FLOWS_CUTOVER_PLAN.md`

### 2. Comp Sheets Experiment
Google Drive MCP is registered and working. Try building comp tables using Google Sheets FINANCE functions (auto-refreshing market data built into Sheets). Two paths:
1. SheetsFinance-native — leverage built-in auto-refresh, see how far it goes
2. Own data source — rebuild with FMP/our data if SheetsFinance is too limited, but lose auto-refresh convenience
- Evaluate which approach (or hybrid) works best for equity research comps

### 3. Excel Add-In MCP End-to-End Testing
MCP server is registered. Need to test the full relay pipeline end-to-end: Claude Code -> MCP -> FastAPI -> SSE -> Office.js -> read/understand financial model via schema.
- Validate agent-tools schema against real financial model spreadsheets

## Recently Completed

### 2026-02-17 — Schwab Dividend Description → Ticker Resolution (Bug 23)
Fixed unresolved ENB dividends ($612) by enriching security lookup with Schwab quote API descriptions + prefix matching fallback.
See: `docs/planning/completed/SCHWAB_DIVIDEND_RESOLUTION_PLAN.md`

### 2026-02-17 — Portfolio Manager Complexity Audit
Reviewed portfolio manager complexity and mapped CLI/MCP relevance.  
See: `docs/planning/PORTFOLIO_MANAGER_COMPLEXITY_AUDIT.md`
Implementation plan: `docs/planning/PORTFOLIO_MANAGER_REFACTOR_IMPLEMENTATION_PLAN.md`

### 2026-02-17 — Portfolio Manager Refactor Implementation
Completed modular extraction and compatibility hardening from the implementation plan:
- Extracted repository, assembler, and legacy file helper services
- Refactored `PortfolioManager` into a facade with preserved compatibility surface
- Fixed expected-returns wrapper contract and file-mode per-portfolio behavior
- Added focused tests under `tests/inputs/` and refreshed CRUD regression coverage
- Ran targeted smoke tests on manager, returns service, app bootstrap, and executor flows
See: `docs/planning/PORTFOLIO_MANAGER_REFACTOR_IMPLEMENTATION_PLAN.md`

## Next Up (Actionable)

### 1. Interface Documentation Debt Follow-Through
Source: `docs/interfaces/README.md`
- [ ] Sweep stale `portfolio-mcp` references that still say 19 tools; source of truth is 20 tools including `get_mcp_context`
- [ ] Add a canonical OpenAPI artifact under `docs/interfaces/` and document how/when it is refreshed
- [ ] Decide CI posture for interface docs (`sync-only` vs adding a test gate) and document the decision in `docs/interfaces/test-matrix.md`

## Backlog
