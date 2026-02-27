# Realized Performance MCP Plan

**Status:** COMPLETE (superseded by REALIZED_PERFORMANCE_IMPLEMENTATION_PLAN.md — integrated as `mode="realized"` on existing `get_performance` tool + CLI `--realized-performance` flag)
**Parent:** `docs/planning/MCP_EXTENSIONS_PLAN.md`
**Prerequisite:** `docs/planning/PERFORMANCE_METRICS_ENGINE_PREIMPLEMENTATION_PLAN.md` (COMPLETE)

---

## Overview

Add a new MCP tool, `get_realized_performance`, that computes **realized portfolio performance** from transaction history (Plaid + SnapTrade), while preserving the same user-facing structure and formatting model as `get_performance`.

This does **not** replace `get_performance`. Both tools serve different purposes:

1. `get_performance`: hypothetical/backfilled performance of current portfolio composition
2. `get_realized_performance`: realized performance from actual transaction/cashflow history

---

## Goals

1. Provide realized portfolio-level metrics in the same contract shape as `get_performance`.
2. Reuse service/result patterns already used by risk/performance MCP tools.
3. Integrate cleanly across core, service, CLI, and MCP layers.
4. Support `summary`, `full`, and `report` output formats.

---

## Non-Goals (Phase 1)

1. No replacement or behavior change to existing `get_performance`.
2. No major redesign of trading analysis grading features.
3. No hard dependency on DB persistence of completed trades (can compute on demand first).

---

## Contract Strategy (Parity with `get_performance`)

`get_realized_performance` keeps the same format semantics:

1. `summary`: same top-level KPI shape as `get_performance`
2. `full`: same base sections returned by `PerformanceResult.to_api_response()`
3. `report`: same human-readable report pattern

### Summary Fields (same keys as `get_performance`)

1. `status`
2. `total_return`
3. `annualized_return`
4. `volatility`
5. `sharpe_ratio`
6. `max_drawdown`
7. `win_rate`
8. `analysis_years`
9. `benchmark_ticker`
10. `alpha_annual`
11. `beta`
12. `performance_category`
13. `key_insights`

### Realized-Specific Additions (in `full`)

1. `realized_method` (`twr`, `mwr`, or `both`)
2. `money_weighted_return` (if computed)
3. `net_contributions`
4. `realized_pnl`
5. `unrealized_pnl`
6. `cashflow_coverage`
7. `data_warnings`
8. `source_breakdown`

---

## Architecture

## 1) Core Layer

Create new module:

- `core/realized_performance_analysis.py`

Responsibilities:

1. fetch/normalize provider transactions (via existing trading data fetchers)
2. build realized return series (monthly)
3. build benchmark series and align
4. call shared metrics engine (from prerequisite refactor track)
5. return `PerformanceResult`-compatible structure + realized metadata

## 2) Service Layer

Add to `PortfolioService`:

- `analyze_realized_performance(...)`

Responsibilities:

1. caching and cache keys (consistent with existing service patterns)
2. error wrapping to `PortfolioAnalysisError`
3. returning structured result object for downstream formatting

## 3) CLI/Wrapper Layer

Add wrapper in `run_risk.py`:

- `run_portfolio_realized_performance(...)`

Responsibilities:

1. match dual-mode pattern (`return_data=True` vs CLI print)
2. keep consistency with existing `run_portfolio_performance`

## 4) MCP Layer

Create:

- `mcp_tools/realized_performance.py` (new tool implementation)

Register:

1. `mcp_tools/__init__.py`
2. `mcp_server.py`
3. `mcp_tools/README.md`

Tool signature (initial):

1. `portfolio_name: str = "CURRENT_PORTFOLIO"`
2. `benchmark_ticker: str = "SPY"`
3. `source: Literal["all", "snaptrade", "plaid"] = "all"`
4. `method: Literal["twr", "mwr", "both"] = "twr"`
5. `format: Literal["full", "summary", "report"] = "summary"`
6. `use_cache: bool = True`
7. `start_date: Optional[str] = None`
8. `end_date: Optional[str] = None`

---

## Concrete File Plan

| Action | File | Change |
|--------|------|--------|
| **Create** | `core/realized_performance_analysis.py` | Realized analysis pipeline + shared metrics engine adapter |
| **Modify** | `services/portfolio_service.py` | Add `analyze_realized_performance()` with caching/error handling |
| **Modify** | `run_risk.py` | Add CLI wrapper `run_portfolio_realized_performance()` |
| **Create** | `mcp_tools/realized_performance.py` | MCP tool with summary/full/report outputs |
| **Modify** | `mcp_tools/__init__.py` | Export `get_realized_performance` |
| **Modify** | `mcp_server.py` | Register new `@mcp.tool()` |
| **Modify** | `mcp_tools/README.md` | Add documentation and examples |
| **Modify** | `tests/TESTING_COMMANDS.md` | Add concrete test commands for new tool |
| **Create** | `tests/core/test_realized_performance_analysis.py` | Core realized metric tests |
| **Create** | `tests/services/test_portfolio_service_realized_perf.py` | Service-level tests |
| **Create** | `tests/mcp/test_realized_performance_tool.py` | MCP format and error contract tests |

---

## Data Pipeline Design

1. Pull raw transactions from existing sources:
   - `trading_analysis/data_fetcher.py`
2. Normalize with stronger schema:
   - include `transaction_datetime` when available
   - include cancellation/reference IDs
   - preserve account/currency/source IDs
3. Build cashflow/equity timeline:
   - external contributions/withdrawals separated from performance
   - fees/dividends/interest applied correctly
4. Build monthly portfolio return series (TWR path)
5. Optionally compute MWR (`money_weighted_return`) in parallel
6. Align to benchmark series and compute parity metrics through shared engine

---

## Output/Result Model Strategy

Prefer extending existing `PerformanceResult` usage rather than introducing a totally separate report object:

1. base performance sections remain identical
2. realized-only fields appended in `full`
3. `summary` remains minimal and parity-aligned

This keeps downstream consumers (MCP, APIs, frontend adapters) predictable.

---

## Edge Cases and Rules

1. Incomplete transaction history:
   - return success with warnings if enough data exists
   - return explicit error if no usable window remains
2. Mixed currencies:
   - preserve source currency context; aggregate in base currency path with clear warning fields
3. Canceled/reversed transactions:
   - remove/offset via cancellation IDs when available
4. Options and corporate actions:
   - support current logic first; include warnings for unhandled action types
5. Date windows:
   - default to provider-supported available range if no explicit dates supplied

---

## Testing and Verification

## Unit Tests

1. realized monthly return series generation
2. contribution/withdrawal separation
3. benchmark alignment and empty-overlap handling
4. MWR computation and fallback behavior

## Service Tests

1. cache key isolation by user + params
2. exception wrapping parity with existing service methods
3. format parity (`summary/full/report`)

## MCP Tool Tests

1. summary key parity with `get_performance`
2. `full` contains base + realized fields
3. `report` human-readable output
4. error path contract (`status: "error"`, `error` message)

## Manual Checks

1. compare realized vs hypothetical for same period and explain expected differences
2. test all sources (`all`, `snaptrade`, `plaid`)
3. test each format in MCP

---

## Rollout Plan

## Phase 0 (Prerequisite)

Complete and merge:

- `PERFORMANCE_METRICS_ENGINE_PREIMPLEMENTATION_PLAN.md`

Gate: existing `get_performance` behavior unchanged.

## Phase 1

Implement core realized pipeline + service method.

## Phase 2

Add CLI wrapper and MCP tool integration.

## Phase 3

Harden edge cases, warnings, and docs; run regression suite.

---

## Success Criteria

1. `get_realized_performance` available in MCP with `summary/full/report`.
2. Summary contract matches `get_performance`.
3. Existing `get_performance` remains unchanged.
4. Realized calculations are auditable with warnings/coverage metadata.
5. Tests cover core math, service contracts, and MCP integration.

---

## Example MCP Prompts

1. "Show my realized performance over the last 2 years."
2. "How did I actually perform vs SPY?"
3. "Give me full realized performance metrics using only SnapTrade data."

