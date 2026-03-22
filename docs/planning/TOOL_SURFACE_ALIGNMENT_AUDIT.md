# Tool Surface Alignment Audit

> **Date**: 2026-03-22
> **Status**: AUDIT COMPLETE — Codex R1 FAIL (5 issues), R2 FAIL (stale counts), R3 FAIL (1 count), **R4 PASS**
> **TODO ref**: `docs/TODO.md` lines 122-141 ("Tool Surface Alignment Audit")

---

## Executive Summary

Three consumer surfaces expose overlapping tool sets backed by the **same underlying engines**. The overlap is architecturally intentional — MCP wraps for AI, REST wraps for the frontend, and the Agent Registry wraps for code execution. Drift has occurred: 19 MCP tools are missing from the Agent Registry (9 likely oversights, 10 intentional), and the REST surface retains legacy v1 endpoints alongside v2 replacements. Auth is consistent — all REST routers enforce session or tier-based auth.

**Overall grade: B+** — Unified core layer is clean. Consumer interfaces are well-separated. Auth is consistent. Main issue is registry gaps (9 tools that should be added).

---

## Architecture (confirmed)

```
Unified Core Layer (source of truth):
├─ PositionService, PortfolioService
├─ Portfolio Risk Analysis Engine
├─ Performance Metrics Engine
├─ Trading Analysis, Factor Intelligence
└─ Scenario engines (stress, MC, backtest, whatif, optimization)
        ↓
Three Consumer Interfaces:
├─ MCP Tools (75 portfolio-mcp + 19 fmp-mcp = 94 total)
│  └─ Schema-validated, agent-format responses with interpretive flags
│  └─ Auth: user_email from env, stdio protocol
├─ Agent Code Execution Registry (66 functions: 56 tools + 10 building blocks)
│  └─ POST /api/agent/call — dynamic dispatcher, bearer token auth
│  └─ Mutation-gated (AGENT_API_ALLOW_WRITES), param sanitization
├─ Frontend REST API (134 endpoints across app.py + 22 routers)
│  └─ Session-cookie auth, adapter-transformed responses
│  └─ Frontend exclusively uses REST — never calls MCP tools directly
```

All three surfaces call the **same underlying functions** at the service/engine layer. Response shapes differ by consumer needs:
- **MCP**: `{status, format: "agent", snapshot, flags}` — for AI interpretation
- **REST**: Pydantic models via `to_api_response()` — structured JSON
- **Frontend**: REST response → Adapter transform → camelCase, percentages, time series

---

## Surface 1: MCP Tools (94 total)

### portfolio-mcp (75 tools in `mcp_server.py`)

Registered via `@mcp.tool()` decorators. All import from `mcp_tools/*.py`. No self-registration in tool files.

**By category:**
- Positions/risk (8): get_positions, get_risk_analysis, get_risk_score, get_risk_profile, set_risk_profile, get_leverage_capacity, monitor_hedge_positions, check_exit_signals
- Performance (2): get_performance, get_income_projection
- Scenarios (7): run_whatif, run_optimization, run_backtest, get_efficient_frontier, compare_scenarios, suggest_tax_loss_harvest, generate_rebalance_trades
- Trading (11): get_trading_analysis, get_orders, preview_trade, execute_trade, cancel_order, preview_basket_trade, execute_basket_trade, preview_futures_roll, execute_futures_roll, preview_option_trade, execute_option_trade
- Stock analysis (2): analyze_stock, analyze_option_chain, analyze_option_strategy
- Factor (3): get_factor_analysis, get_factor_recommendations, get_futures_curve
- Portfolio mgmt (8): list_portfolios, create_portfolio, delete_portfolio, update_portfolio_accounts, list_accounts, account_activate, account_deactivate, import_portfolio
- Baskets (7): list_baskets, get_basket, create_basket, update_basket, delete_basket, create_basket_from_etf, analyze_basket
- Transactions (8): ingest_transactions, list_transactions, list_ingestion_batches, inspect_transactions, list_flow_events, list_income_events, refresh_transactions, transaction_coverage
- Allocation (2): set_target_allocation, get_target_allocation
- Market data (3): get_quote, get_portfolio_news, get_portfolio_events_calendar
- Normalizer builder (5): normalizer_sample_csv, normalizer_stage, normalizer_test, normalizer_activate, normalizer_list
- Config (2): manage_instrument_config, manage_ticker_config
- Audit (3): record_workflow_action, update_action_status, get_action_history
- Import/export (2): export_holdings, import_transactions
- Internal (1): get_mcp_context

### fmp-mcp (19 tools in `fmp/server.py`)

Separate MCP server. All read-only financial data queries.

---

## Surface 2: Agent Code Execution Registry (66 functions)

### Registered in `services/agent_registry.py` → `_build_registry()`

**56 tools** (tier="tool") + **10 building blocks** (tier="building_block").

All 56 tools import the **same function** from `mcp_tools/*.py` via `_unwrap()` (strips `@handle_mcp_errors` decorator). Building blocks import from `services/agent_building_blocks.py`.

### MCP tools NOT in Agent Registry (19 gaps)

| MCP Tool | Category | Why missing? |
|----------|----------|-------------|
| `export_holdings` | import/export | Likely oversight — supports `output="inline"`, works without file I/O |
| `import_portfolio` | portfolio mgmt | Uses `file_path` param (not `backfill_path`) — file system interaction |
| `import_transactions` | transactions | Uses `file_path` param — file system interaction |
| `list_accounts` | portfolio mgmt | Likely oversight — read-only, safe for agent |
| `list_portfolios` | portfolio mgmt | Likely oversight — read-only, safe for agent |
| `manage_instrument_config` | config | Admin config mutation — intentional exclusion |
| `manage_ticker_config` | config | Admin config mutation — intentional exclusion |
| `set_target_allocation` | allocation | Likely oversight — mutation but safe with write gating |
| `get_target_allocation` | allocation | Likely oversight — read-only, safe for agent |
| `normalizer_sample_csv` | normalizer | File system interaction — intentional exclusion |
| `normalizer_stage` | normalizer | File system interaction — intentional exclusion |
| `normalizer_test` | normalizer | File system interaction — intentional exclusion |
| `normalizer_activate` | normalizer | File system interaction — intentional exclusion |
| `normalizer_list` | normalizer | Read-only but normalizer family grouped — intentional exclusion |
| `get_portfolio_news` | market data | Likely oversight — read-only, safe for agent |
| `get_portfolio_events_calendar` | market data | Likely oversight — read-only, safe for agent |
| `analyze_basket` | baskets | Likely oversight — read-only analysis |
| `get_action_history` | audit | Likely oversight — read-only, safe for agent |
| `get_mcp_context` | internal | Internal MCP diagnostic — intentional exclusion |

**Classification:**
- **Intentional exclusions (10)**: File system tools (`import_portfolio`, `import_transactions`, normalizer family ×5), admin config tools (`manage_instrument_config`, `manage_ticker_config`), internal MCP diagnostic (`get_mcp_context`)
- **Likely oversights (9)**: `export_holdings`, `list_accounts`, `list_portfolios`, `set_target_allocation`, `get_target_allocation`, `get_portfolio_news`, `get_portfolio_events_calendar`, `analyze_basket`, `get_action_history`

Note: `BLOCKED_PARAMS` only covers `backfill_path`, `output`, and `debug_inference`. The file-path exclusions for `import_portfolio`/`import_transactions` are based on their `file_path` parameter (not blocked by `BLOCKED_PARAMS` but inappropriate for agent API). `export_holdings` supports inline mode and could work in the registry.

### Building blocks (10, not in MCP)

These are internal composition primitives exposed only via the agent API, not as standalone MCP tools:

| Function | Source | Purpose |
|----------|--------|---------|
| `get_price_series` | agent_building_blocks | Raw price series data |
| `get_returns_series` | agent_building_blocks | Returns time series |
| `get_portfolio_weights` | agent_building_blocks | Current weight vector |
| `get_correlation_matrix` | agent_building_blocks | Correlation matrix |
| `compute_metrics` | agent_building_blocks | Raw metric computation |
| `run_stress_test` | agent_building_blocks | Stress test engine |
| `run_monte_carlo` | agent_building_blocks | Monte Carlo engine |
| `get_factor_exposures` | agent_building_blocks | Factor exposure data |
| `fetch_fmp_data` | agent_building_blocks | Raw FMP API access |
| `get_dividend_history` | agent_building_blocks | Dividend history |

These are intentionally NOT MCP tools — they're lower-level primitives for agent code execution.

---

## Surface 3: Frontend REST API (134 endpoints)

### Duplication with MCP tools

18 REST endpoints in `app.py` duplicate MCP tool functionality. Both call the same underlying engine — REST applies `to_api_response()`, MCP returns agent format.

| REST Endpoint | MCP Equivalent | Same engine? |
|---------------|---------------|--------------|
| `POST /api/analyze` | `get_risk_analysis()` | Yes |
| `POST /api/risk-score` | `get_risk_score()` | Yes |
| `POST /api/performance` | `get_performance()` | Yes |
| `POST /api/portfolio-analysis` | `get_risk_analysis()` | Yes |
| `POST /api/what-if` | `run_whatif()` | Yes |
| `POST /api/backtest` | `run_backtest()` | Yes |
| `POST /api/min-variance` | `run_optimization(type=min_variance)` | Yes |
| `POST /api/max-return` | `run_optimization(type=max_return)` | Yes |
| `POST /api/efficient-frontier` | `get_efficient_frontier()` | Yes |
| `POST /api/stress-test` | stress test building block | Yes |
| `POST /api/monte-carlo` | Monte Carlo building block | Yes |
| `POST /api/direct/stock` | `analyze_stock()` | Yes |
| `GET/POST /api/allocations/target` | `get/set_target_allocation()` | Yes |
| `POST /api/allocations/rebalance` | `generate_rebalance_trades()` | Yes |
| `GET /api/income/projection` | `get_income_projection()` | Yes |
| `POST /api/tax-harvest` | `suggest_tax_loss_harvest()` | Yes |
| `GET /api/positions/holdings` | `get_positions()` | Yes |
| `GET /api/hedge-monitor` | `monitor_hedge_positions()` | Yes (router calls MCP function directly) |
| `POST /api/baskets/{name}/analyze` | `analyze_basket()` | Yes (router calls MCP function directly) |
| `GET/POST /api/risk-settings` | `get_risk_profile()` / `set_risk_profile()` | Yes (same `RiskLimitsManager` backend) |
| `POST /api/trading/preview` | `preview_trade()` | Yes (router wraps MCP function) |
| `POST /api/trading/execute` | `execute_trade()` | Yes (router wraps MCP function) |

Note: `POST /api/interpret` calls `interpret_portfolio_risk()` (GPT helper) — this has **no MCP equivalent**. It's REST-only.

**This duplication is deliberate and correct.** The frontend needs REST endpoints with session auth and adapter-compatible response shapes. MCP tools need agent format with interpretive flags. Both call the same core functions.

### REST-only endpoints (no MCP equivalent)

These are intentionally REST-only — they're infrastructure/integration endpoints, not analytical tools:

| Category | Endpoints | Count |
|----------|-----------|-------|
| Auth | `/auth/*` (login, logout, status) | 5 |
| Plaid integration | `/plaid/*` (link, holdings, webhook) | 11 |
| SnapTrade integration | `/api/snaptrade/*` | 9 |
| Onboarding | `/api/onboarding/*` (CSV, status) | 9 |
| Provider routing | `/api/provider-routing/*` | 4 |
| Gateway proxy | `/api/gateway/*` (SSE chat) | dynamic |
| Frontend logging | `/api/log-frontend` | 2 |
| Admin | `/admin/*` | 6 |
| Debug | `/api/debug/*` | 1 |
| Factor groups CRUD | `/api/factor-groups/*` | 6 |
| v2 portfolios | `/api/v2/portfolios/*`, `/api/v2/accounts` | 5 |
| AI/data providers | `/api/v2/ai-providers`, `/api/v2/data-providers` | 2 |

### Auth model

All route modules enforce auth. Some use FastAPI `Depends(get_current_user)`, others use manual `_require_authenticated_user()` session checks, and some use `_require_paid_user` tier gates.

| Auth Pattern | Route Modules |
|-------------|--------------|
| `Depends(get_current_user)` | auth, plaid, snaptrade, factor_intelligence, hedging, realized_performance, v2 portfolios, app.py endpoints |
| `_require_authenticated_user()` (manual session check) | baskets, hedge_monitor, tax_harvest, positions |
| `Depends(_require_paid_user)` (tier gate) | income, trading |
| Bearer token | agent_api |
| Admin-only | admin |

No unprotected endpoints found — all router modules enforce session or tier-based auth.

### Legacy v1/v2 endpoint duplication

Only 3 endpoints overlap. Each version also has unique endpoints.

| Capability | v1 (app.py) | v2 (routers/portfolios.py) | Overlap? |
|------------|------------|---------------------------|----------|
| List portfolios | `GET /api/portfolios` | `GET /api/v2/portfolios` | **Yes** |
| Create portfolio | `POST /api/portfolios` | `POST /api/v2/portfolios` | **Yes** |
| Delete portfolio | `DELETE /api/portfolios/{name}` | `DELETE /api/v2/portfolios/{name}` | **Yes** |
| Get portfolio | `GET /api/portfolios/{name}` | — | v1 only |
| Update portfolio (full) | `PUT /api/portfolios/{name}` | — | v1 only |
| Update portfolio (partial) | `PATCH /api/portfolios/{name}` | — | v1 only |
| List accounts | — | `GET /api/v2/accounts` | v2 only |
| Link accounts | — | `PUT /api/v2/portfolios/{name}/accounts` | v2 only |

v2 is not a full replacement for v1 — it adds account management but lacks get/update endpoints. Both must coexist until v2 achieves full parity.

---

## Design Intent Per Surface

| Surface | Target Consumer | Auth Model | Response Shape | Design Intent |
|---------|----------------|------------|----------------|---------------|
| MCP Tools | Claude / AI agents | user_email from env (stdio) | Agent format (snapshot + flags) | AI discoverability, interpretive flags for reasoning |
| Agent Registry | Code execution API | Bearer token + mutation gate | Same as MCP (unwrapped function) | Programmatic access for agent-written code |
| Frontend REST | React frontend | Session cookie | Pydantic → adapter → camelCase | UI-ready data with caching and transformation |

**Why three surfaces exist (not consolidation target):**
1. MCP tools need schema validation and agent-format flags — can't serve raw REST responses
2. Frontend needs session auth, adapter transforms, and REST conventions — can't consume MCP stdio
3. Agent code execution needs dynamic dispatch + param sanitization — bridges the gap

---

## Drift Analysis

### Recent tool additions — surface coverage check

| Recent MCP Tool | In Agent Registry? | Has REST equivalent? |
|-----------------|-------------------|---------------------|
| `monitor_hedge_positions` | Yes | Yes (`/api/hedge-monitor`) |
| `generate_rebalance_trades` | Yes | Yes (`/api/allocations/rebalance`) |
| `compare_scenarios` | Yes | No (MCP-only, agent use case) |
| `get_portfolio_events_calendar` | **No** | No |
| `get_portfolio_news` | **No** | No |
| `analyze_basket` | **No** | Yes (`/api/baskets/{name}/analyze`) |

3 recent MCP tools are missing from the agent registry.

### Flag coverage — MCP flags vs frontend rendering

All 16 agent-format MCP tools emit interpretive flags via `core/*_flags.py`. The frontend does NOT render these flags directly — it uses adapters that extract specific fields. Flags are consumed by:
1. **AI chat** (via gateway proxy) — flags inform Claude's reasoning
2. **Frontend insight cards** — some flag content surfaces as insights/alerts, but through separate adapter logic, not by consuming the flag objects directly

No gap here — the frontend intentionally uses a different rendering path from the flag system.

---

## Recommendations

### Tier 1 — Registry gaps (should fix)

| # | Item | Effort |
|---|------|--------|
| 1 | Add 9 missing read-only/safe MCP tools to agent registry (`export_holdings`, `list_accounts`, `list_portfolios`, `set/get_target_allocation`, `get_portfolio_news`, `get_portfolio_events_calendar`, `analyze_basket`, `get_action_history`) | 30min |

### Tier 2 — Cleanup (nice to have)

| # | Item | Effort |
|---|------|--------|
| 3 | Deprecate v1 portfolio endpoints in `app.py` (favor v2 routers) | 2hr |
| 4 | Document exclusion rationale for 10 intentionally-excluded MCP tools | 30min |

### Tier 3 — Not recommended

| # | Item | Why skip |
|---|------|----------|
| 5 | Consolidate REST + MCP into single surface | Architecture is correct — different consumers need different shapes |
| 6 | Add MCP equivalents for Plaid/SnapTrade/onboarding | These are integration endpoints, not analytical tools |
| 7 | Make frontend consume MCP tools directly | Frontend needs REST conventions, session auth, adapter transforms |

---

## Audit Checklist (from TODO)

- [x] Build full matrix: every capability × which surface exposes it × response format × auth model
- [x] Identify gaps — 19 MCP tools missing from agent registry (9 likely oversights, 10 intentional)
- [x] Identify shape mismatches — shapes differ by design (agent format vs Pydantic vs adapter), not by accident
- [x] Document design intent per surface — AI discoverability vs programmatic access vs UI-ready data
- [x] Check for drift — 3 recent MCP tools missing from registry
- [x] Verify flag coverage — flags consumed by AI chat, not frontend directly (intentional)
