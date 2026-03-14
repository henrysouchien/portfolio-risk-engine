# MCP Extensions Plan

> **Status:** 🟢 ALL TOOLS COMPLETE — 7/7 tools implemented. Chaining/recovery metadata deferred.
> **Depends on:** Position Service Refactor (for cache params) — ✅ DONE
> **Parent:** [Position Module MCP Spec](./completed/POSITION_MODULE_MCP_SPEC.md) (completed)

---

## Overview

Extensions to the portfolio-mcp server after the core implementation is complete.

## Current State

The MCP core is implemented:
- `mcp_server.py` - FastMCP server registered as `portfolio-mcp`
- `mcp_tools/positions.py` - `get_positions()` tool
- `mcp_tools/README.md` - Guidelines for adding new tools

## Planned Extensions

### 1. Cache Control Parameters ✅

**Depends on:** Position Service Refactor — ✅ DONE

After the refactor adds `use_cache` and `force_refresh` to PositionService, expose them in MCP:

```python
@mcp.tool()
def get_positions(
    source: Literal["all", "plaid", "snaptrade"] = "all",
    consolidate: bool = True,
    format: Literal["full", "summary", "list"] = "full",
    use_cache: bool = True,       # NEW
    force_refresh: bool = False   # NEW
) -> dict:
```

**Use cases:**
- "Get my positions" → `use_cache=True` (fast, uses 24h cache)
- "Refresh my positions from brokerages" → `force_refresh=True` (hits APIs)

### 2. New Tools (As Modules Are Built)

Following the pattern in `mcp_tools/README.md`, add tools as CLI modules are created:

| Tool | Source Module | Result Object | Priority | Status |
|------|---------------|---------------|----------|--------|
| `get_risk_analysis` | `mcp_tools/risk.py` | `RiskAnalysisResult` | High | ✅ Done (+ `include` section filtering) |
| `get_risk_score` | `mcp_tools/risk.py` | `RiskScoreResult` | High | ✅ Done |
| `run_optimization` | `mcp_tools/optimization.py` | `OptimizationResult` | Medium | ✅ Done |
| `get_performance` | `mcp_tools/performance.py` | `PerformanceResult` | Medium | ✅ Done |
| `run_whatif` | `mcp_tools/whatif.py` | `WhatIfResult` | Low | ✅ Done |
| `analyze_stock` | `mcp_tools/stock.py` | `StockAnalysisResult` | Low | ✅ Done |

**Pattern for each:**
1. Create `mcp_tools/{name}.py` wrapping the service
2. Register in `mcp_server.py` with `@mcp.tool()`
3. Return structured dict with `status` field

### 3. Tool Chaining Metadata 🔲

Enhance tool responses with chaining hints for AI:

```python
{
    "status": "success",
    "data": {...},
    "chain": {
        "can_chain_to": ["run_risk_analysis", "get_risk_score"],
        "suggested_next": "run_risk_analysis",
        "context": {
            "position_count": 24,
            "has_options": false
        }
    }
}
```

This helps AI decide what to call next without explicit user instruction.

### 4. Error Recovery Hints 🔲

Add actionable error responses:

```python
{
    "status": "error",
    "error": "Plaid token expired",
    "recovery": {
        "action": "reauthorize",
        "provider": "plaid",
        "user_action_required": true,
        "message": "Please reconnect your Plaid account in the app"
    }
}
```

---

## Implementation Order

1. ~~**Position Service Refactor** → Enables cache params~~ ✅
2. ~~**Cache params in MCP** → Quick update after refactor~~ ✅
3. ~~**Risk analysis tool** → Most requested next tool~~ ✅ (`get_risk_analysis` + `get_risk_score`)
4. ~~**Section filtering** → `include` param on `get_risk_analysis`~~ ✅ ([Plan](./MCP_SECTION_FILTERING_PLAN.md))
5. ~~**Optimization + What-If tools** → `run_optimization` + `run_whatif`~~ ✅ ([Optimization Plan](./OPTIMIZATION_MCP_PLAN.md), [What-If Plan](./WHATIF_MCP_PLAN.md))

---

## Files to Create/Modify

| File | Change | Status |
|------|--------|--------|
| `mcp_tools/positions.py` | Add `use_cache`, `force_refresh` params | ✅ Done |
| `mcp_tools/risk.py` | Risk tools + `RISK_ANALYSIS_SECTIONS` dict + `include` filtering | ✅ Done |
| `mcp_server.py` | Register new tools | ✅ Done |

---

## Success Criteria

- [x] Cache params work after Position Service Refactor
- [x] At least 3 tools available (positions, risk_score, risk_analysis)
- [x] All tools follow same response pattern (`status` field)
- [x] `mcp_tools/README.md` updated with risk tools documentation

---

## Related Documents

- [Position Service Refactor Plan](./POSITION_SERVICE_REFACTOR_PLAN.md) - Prerequisite for cache
- [Modular CLI Architecture](./MODULAR_CLI_ARCHITECTURE_PLAN.md) - CLI modules to wrap
- [MCP Tools README](../mcp_tools/README.md) - Pattern for adding tools

---

*Document created: 2026-01-30*
*Last updated: 2026-02-07*
*Status: All tools complete (7/7). Tool chaining metadata and error recovery hints remain as future enhancements.*
