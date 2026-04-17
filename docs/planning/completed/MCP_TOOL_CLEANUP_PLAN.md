# E11 MCP Tool Cleanup — Parameter & Verb Standardization

**Status:** Re-audited 2026-04-12, Codex R3 PASS
**Scope:** portfolio-mcp tool surface (86 registered tools in `mcp_server.py`)

## Context

The portfolio-mcp tool surface has 86 registered tools. An audit reveals parameter naming inconsistencies and a verb mismatch that make the surface harder for AI agents to navigate. This cleanup standardizes naming conventions — zero behavior change.

## Scope

**In scope (Phases 1-2, 4):** Parameter renames, verb renames, documentation comment. All are naming-only changes — no logic changes.

**Deferred:** Phase 3 (`export_holdings` consolidation — it's a useful standalone tool with unique CSV functionality) and Phase 5 (docs — do after renames settle).

## Breaking Change Strategy

`risk_client` is installed locally only (editable install, not published to PyPI). No external consumers. Renames are safe — just rename methods and `self.call()` strings directly, no deprecated aliases needed.

## Phase 1: Parameter Standardization

### 1A. Date params: `from_date`/`to_date` → `start_date`/`end_date`

2 MCP tools use `from_date`/`to_date`, 12+ tools use `start_date`/`end_date`. Standardize to the majority.

**Tools affected:**
- `get_portfolio_news()` — `mcp_tools/news_events.py:291`
- `get_portfolio_events_calendar()` — `mcp_tools/news_events.py:356`

**Internal call nuance:** Inside `news_events.py`, the portfolio events builder calls these functions internally:
- Lines 699, 835: Call `get_portfolio_events_calendar(from_date=..., to_date=...)` — MUST update kwargs to `start_date`/`end_date` (same function being renamed)
- Line 757: Call `get_economic_data(from_date=..., to_date=...)` — DO NOT rename. This calls `fmp.tools.market.get_economic_data()` which is in the FMP package and uses `from_date`/`to_date` as its own convention.

**Files to change:**
| File | Change |
|------|--------|
| `mcp_tools/news_events.py` | Rename params in `get_portfolio_news()` (line 291) and `get_portfolio_events_calendar()` (line 356) function signatures. Update internal calls at lines 699 and 835 to use `start_date`/`end_date`. Leave line 757 (`get_economic_data`) untouched. |
| `mcp_server.py` | Update wrapper param names in `get_portfolio_news()` and `get_portfolio_events_calendar()` wrappers |
| `tests/mcp_tools/test_news_events_portfolio.py` | Update param names in test calls |
| `tests/mcp_tools/test_news_events_builder.py` | Update param names in test calls |

Note: `tests/mcp_tools/test_news_events.py` tests `fmp.tools.news_events`, not the MCP wrapper — no change needed. `risk_client/__init__.py` uses `**kw` passthrough — no signature change needed.

### 1B. Remove deprecated `brokerage` param from `get_positions`

`get_positions` has both `brokerage` and `institution` params, with `institution` taking precedence. Remove `brokerage`, keep `institution` only.

**Files to change:**
| File | Change |
|------|--------|
| `mcp_tools/positions.py` | Remove `brokerage` param from function signature (line 501), simplify filter logic (line 594: `institution_filter = institution` instead of `institution if institution is not None else brokerage`), remove `brokerage` from schema dict (line 990) |
| `mcp_server.py` | Remove `brokerage` from wrapper function signature and passthrough |
| `tests/mcp_tools/test_positions_agent_format.py` | Update backward-compat test (lines 419-448) to use `institution` |
| `tests/mcp_tools/test_brokerage_aliases.py` | Update tests (lines 55-89) to use `institution` param |
| `docs/reference/DATA_SCHEMAS.md` | Update usage examples at lines 1910-1911: `get_positions(brokerage="Schwab")` and `get_positions(brokerage="Interactive Brokers")` → `get_positions(institution=...)` |

### 1C. `brokerage` → `institution` on `import_transaction_file`

Only the MCP-exposed function param is renamed. The 4 private helper functions (`_resolve_ibkr_request`, `_resolve_requested_txn_normalizer`, `_needs_txn_normalizer_response`, `_parse_statement_dir` at lines 132, 163, 184, 201) use `brokerage` as an internal concept param — these stay as-is.

**Files to change:**
| File | Change |
|------|--------|
| `mcp_tools/import_transactions.py` | Rename `brokerage` → `institution` in `import_transaction_file()` function signature (line 365) + the passthrough to internal helpers. Private helpers keep `brokerage` param name. |
| `mcp_server.py` | Update wrapper param name |
| `tests/mcp_tools/test_import_transactions.py` | Update param name in tests |
| `tests/mcp_tools/test_import_transactions_csv.py` | Update param name in tests |

## Phase 2: Verb Standardization

### 2A. Rebalance preview tool naming

Aligns with the `preview_*/execute_*` pattern used by all other trading tools:

| Domain | Preview | Execute |
|--------|---------|---------|
| Equities | `preview_trade` | `execute_trade` |
| Options | `preview_option_trade` | `execute_option_trade` |
| Futures | `preview_futures_roll` | `execute_futures_roll` |
| Baskets | `preview_basket_trade` | `execute_basket_trade` |
| **Rebalance** | `preview_rebalance_trades` | (uses `execute_trade` per leg) |

**Files to change:**
| File | Change |
|------|--------|
| `mcp_tools/rebalance.py` | Rename function (line 217) |
| `mcp_server.py` | Rename import alias + wrapper function |
| `agent/registry.py` | Update import (line 905) + registration (line 987) |
| `risk_client/__init__.py` | Rename method + `self.call()` string (line 129) |
| `mcp_tools/__init__.py` | Update import + `__all__` entry |
| `app.py` | Update import + usage (lines 289, 3046) |
| `tests/mcp_tools/test_rebalance_agent_format.py` | Update all function name references |
| `tests/mcp_tools/test_rebalance_asset_class_targets.py` | Update all function name references |
| `tests/api/test_allocation_workflow_endpoints.py` | Update monkeypatch references (lines 174, 225, 247) |
| `tests/routes/test_agent_api.py` | Update registry coverage test |
| `tests/test_risk_client.py` | Update client test |
| `tests/test_tool_surface_sync.py` | Update if referenced |
| `docs/interfaces/mcp.md` | Update tool name |

### 2B. `import_transaction_file` + `fetch_provider_transactions`

These two tools have critically different purposes but confusingly similar names:
- `import_transaction_file` = load CSV from filesystem → staging
- `fetch_provider_transactions` = fetch from live brokerage APIs → transaction store

Note: `refresh_transactions` already exists as a separate MCP tool (`mcp_tools/transactions.py:544`) — cannot reuse that name. `fetch_provider_transactions` clearly describes the operation (fetch from provider APIs) without colliding.

**`import_transaction_file` — files to change:**
| File | Change |
|------|--------|
| `mcp_tools/import_transactions.py` | Rename function (line 365) |
| `mcp_server.py` | Rename import alias + wrapper function |
| `agent/registry.py` | Update exclusion comment (line 44) |
| `tests/mcp_tools/test_import_transactions.py` | Update function references |
| `tests/mcp_tools/test_import_transactions_csv.py` | Update function references |
| `tests/routes/test_agent_api.py` | Update exclusion assertion (line 478) |
| `tests/test_tool_surface_sync.py` | Update exclusion list entry |
| `docs/interfaces/mcp.md` | Update tool name (line 42) |

Note: `import_transaction_file` is intentionally excluded from agent registry (filesystem-backed mutator). Keep excluded under this name.

**`fetch_provider_transactions` — files to change:**
| File | Change |
|------|--------|
| `mcp_tools/transactions.py` | Rename function (line 238) |
| `mcp_server.py` | Rename import alias + wrapper function |
| `agent/registry.py` | Update import + registration (lines 943, 1111) |
| `risk_client/__init__.py` | Rename method + `self.call()` string (line 340) |
| `mcp_tools/performance.py` | Update user-facing hint (line 157): "Use 'fetch_provider_transactions'..." |
| `mcp_tools/trading_analysis.py` | Update user-facing hint (line 182): "Use 'fetch_provider_transactions'..." |
| `tests/routes/test_agent_api.py` | Update registry coverage test |
| `tests/test_risk_client.py` | Update client test (lines 365-368) |
| `docs/interfaces/mcp.md` | Update tool name |

## Phase 4: Document Orphaned Implementation

### 4A. Add comment to `mcp_tools/metric_insights.py`

Add a module-level comment explaining this is intentionally REST-only (used by frontend metric cards via `GET /api/positions/metric-insights`), not exposed as MCP tool. AI agents get the same data via raw flags from existing tools.

**Files to change:**
| File | Change |
|------|--------|
| `mcp_tools/metric_insights.py` | Add module-level docstring/comment |

## Execution Order

Phases are independent — can execute in any order. Suggested: 1A → 1B → 1C → 2A → 2B → 4.

Each phase should be its own commit for clean bisectability.

## Verification

After each phase:
1. `python3 -m pytest tests/mcp_tools/ -v` — MCP tool tests pass
2. `python3 -m pytest tests/routes/test_agent_api.py -v` — agent registry coverage passes
3. `python3 -m pytest tests/test_risk_client.py -v` — client tests pass
4. `python3 -m pytest tests/test_tool_surface_sync.py -v` — tool surface sync passes
5. `python3 -m pytest tests/api/test_allocation_workflow_endpoints.py -v` — allocation workflow tests pass

After all phases:
6. Full test suite: `python3 -m pytest tests/ -x`
7. Start MCP server and verify renamed tools appear with correct params
