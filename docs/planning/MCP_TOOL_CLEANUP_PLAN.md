# MCP Tool Cleanup Plan

**Status:** Draft
**Date:** 2026-03-24
**Scope:** portfolio-mcp tool surface (82 tools in `mcp_server.py`)

## Problem

The portfolio-mcp tool surface has grown to 82 tools organically. An audit reveals parameter naming inconsistencies, confusingly-named tool pairs, one orphaned implementation, and a consolidation opportunity. None of these are bugs — they're API hygiene issues that make the tool surface harder for AI agents to navigate.

## Non-Goals

- Changing tool behavior or business logic
- Removing tools that are actively used (even if overlapping)
- Restructuring `mcp_tools/` directory layout
- Frontend changes

---

## Phase 1: Parameter Standardization (Low Risk)

Normalize parameter names across tools for consistency. All changes are backward-compatible renames with deprecation aliases where needed.

### 1A. Date Parameters: `from_date`/`to_date` → `start_date`/`end_date`

Two tools use non-standard date parameter names:

| Tool | Current | Target |
|------|---------|--------|
| `get_portfolio_events_calendar` | `from_date`, `to_date` | `start_date`, `end_date` |
| `get_portfolio_news` | `from_date`, `to_date` | `start_date`, `end_date` |

All other date-filtered tools (10+) already use `start_date`/`end_date`.

**Files:** `mcp_server.py`, `mcp_tools/market.py`

### 1B. Institution Filter: `brokerage` → `institution`

Four tools use `brokerage` where the standard is `institution`:

| Tool | Current Param | Notes |
|------|---------------|-------|
| `get_positions` | `brokerage` (+ separate `institution` that takes precedence) | Has both — remove `brokerage`, keep `institution` |
| `import_portfolio` | `brokerage` | Rename to `institution` |
| `import_transactions` | `brokerage` | Rename to `institution` |
| `list_supported_brokerages` | `brokerage_name` (output field) | Tool name itself says "brokerages" — rename param only |

Nine other tools already use `institution`.

**Files:** `mcp_server.py`, `mcp_tools/positions.py`, `mcp_tools/portfolio_import.py`, `mcp_tools/transactions.py`

### 1C. Dual `brokerage`+`institution` on `get_positions`

`get_positions` currently accepts both `brokerage` and `institution` with `institution` taking precedence. Remove `brokerage` parameter, keep `institution` only.

**Files:** `mcp_server.py`, `mcp_tools/positions.py`

---

## Phase 2: Verb Standardization (Low Risk)

### 2A. `generate_rebalance_trades` → `preview_rebalance_trades`

This tool generates proposed trade legs without executing them — it's a preview operation. The current name `generate_` breaks the `preview_X`/`execute_X` pattern used by all other trading tools:

| Existing Pattern | Preview | Execute |
|-----------------|---------|---------|
| Equities | `preview_trade` | `execute_trade` |
| Options | `preview_option_trade` | `execute_option_trade` |
| Futures | `preview_futures_roll` | `execute_futures_roll` |
| Baskets | `preview_basket_trade` | `execute_basket_trade` |
| **Rebalance** | ~~`generate_rebalance_trades`~~ → `preview_rebalance_trades` | (uses execute_trade per leg) |

**Files:** `mcp_server.py`, `mcp_tools/rebalance.py`, agent registry in `services/agent_registry.py`

### 2B. `import_transactions` / `ingest_transactions` Rename

These two tools have critically different purposes but confusingly similar names:

| Current Name | Purpose | Proposed Name |
|-------------|---------|---------------|
| `import_transactions` | Load transactions from a local CSV/statement file | `import_transaction_file` |
| `ingest_transactions` | Fetch + persist from live brokerage APIs (Plaid, Schwab, etc.) | `sync_provider_transactions` |

**Files:** `mcp_server.py`, `mcp_tools/transactions.py`, `mcp_tools/portfolio_import.py`, agent registry

---

## Phase 3: Tool Consolidation (Medium Risk)

### 3A. Consolidate `export_holdings` into `get_positions`

`export_holdings` returns a CSV export of current holdings. `get_positions` already has an `output="file"` parameter and 6 format modes. Adding `format="csv"` to `get_positions` would subsume `export_holdings`.

**Current `get_positions` formats:** full, summary, list, by_account, monitor, agent
**Proposed addition:** `format="csv"` (produces the same CSV output as current `export_holdings`)

After migration:
- Remove `export_holdings` tool registration
- Keep underlying `_export_holdings()` as internal helper called by `get_positions(format="csv")`

**Files:** `mcp_server.py`, `mcp_tools/positions.py`

---

## Phase 4: Orphaned Implementation (Low Risk)

### 4A. `mcp_tools/metric_insights.py` — Decide: Register or Document

`MetricInsightBuilder` (1,099 lines) maps interpretive flags → metric card insights. Currently:
- Used by REST endpoint `GET /api/positions/metric-insights` (frontend only)
- NOT registered as MCP tool
- NOT reachable by AI agents

**Options:**
1. **Register as MCP tool** — `get_metric_insights()` for agent access to flag-based insights
2. **Document as REST-only** — add comment noting intentional exclusion from MCP surface
3. **No action** — it's not broken, just undiscoverable by agents

**Recommendation:** Option 2 (document). The insights are presentation-layer for frontend metric cards. AI agents already get the raw flags from existing tools. Exposing the same data reformatted for card rendering adds noise to the tool surface.

---

## Phase 5: Documentation (No Code Risk)

### 5A. Tool Domain Map

Create `docs/reference/MCP_TOOL_DOMAINS.md` documenting the logical grouping of all tools:

| Domain | Tools | Purpose |
|--------|-------|---------|
| Accounts | 3 | Account discovery + activation |
| Baskets | 9 | Custom index/basket CRUD + trading |
| Connections | 3 | Brokerage OAuth + listing |
| Config/Admin | 3 | Instrument/ticker/proxy config |
| Factor Analysis | 2 | Factor exposure + recommendations |
| Futures | 3 | Curve, preview roll, execute roll |
| Income | 2 | Projection + event listing |
| Monitoring | 2 | Exit signals + hedge tracking |
| Normalizers | 5 | CSV normalizer pipeline |
| Optimization | 2 | Single-point solve + frontier sweep |
| Performance | 1 | Hypothetical + realized returns |
| Portfolio Mgmt | 6 | Portfolio CRUD + news/events |
| Positions | 1 | Holdings with CSV export |
| Risk | 4 | Score, analysis, profile get/set |
| Scenario | 5 | Whatif, backtest, Monte Carlo, stress, compare |
| Stock Analysis | 3 | Stock, option strategy, option chain |
| Target Allocation | 2 | Set + get allocation targets |
| Trading | 8 | Preview/execute for equities, options, futures, baskets, rebalance |
| Transactions | 8 | File import, API sync, list, inspect, flow/income events |
| Workflow Audit | 3 | Action recording + history |
| System | 1 | get_mcp_context |

### 5B. Parameter Convention Guide

Document standard parameter names in the domain map:

| Concept | Standard Param | Type |
|---------|---------------|------|
| Output format | `format` | Literal["full", "summary", "agent", ...] |
| File delivery | `output` | Literal["inline", "file"] |
| Date range start | `start_date` | str (YYYY-MM-DD) |
| Date range end | `end_date` | str (YYYY-MM-DD) |
| Result limit | `limit` | str or int |
| Institution filter | `institution` | str |
| Account filter | `account_id` or `account` | str |
| Portfolio selector | `portfolio_name` | str (default "CURRENT_PORTFOLIO") |
| Cache bypass | `use_cache` | bool (default True) |

---

## Execution Order

| Phase | Risk | Estimated Scope | Dependencies |
|-------|------|-----------------|--------------|
| 1 (Params) | Low | ~8 files | None |
| 2 (Verbs) | Low | ~6 files + agent registry | None |
| 3 (Consolidation) | Medium | ~3 files | Phase 1B (institution param) |
| 4 (Orphan) | None | 1 file comment | None |
| 5 (Docs) | None | 2 new docs | Phases 1-3 |

Phases 1, 2, 4 are independent and can run in parallel. Phase 3 depends on Phase 1B. Phase 5 should run last.

## Agent Registry Impact

Tool renames in Phases 2-3 require updating `services/agent_registry.py` to match new function names. The agent registry maps tool names → callable functions for code execution agents.

## Migration Notes

- MCP tool names are the Python function names — renaming the function renames the tool
- No versioning/deprecation mechanism exists in MCP protocol — renames are breaking for any saved agent prompts referencing old names
- All renames should be done atomically (tool registration + underlying function + agent registry + any hardcoded references)
