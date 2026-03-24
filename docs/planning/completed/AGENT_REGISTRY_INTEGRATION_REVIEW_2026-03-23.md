# Agent Registry Integration Review

**Status:** Completed  
**Date:** 2026-03-23  
**Scope:** Review the live agent execution registry/API/client surface before wiring it into `ai-excel-addin`.

## Summary

The live agent surface is broader than the original Phase 1 plan:

- `75` total registry entries
- `65` tool-tier functions
- `10` building blocks

The main integration risk was not tool count. It was **contract drift**:

1. some registry-exposed user-scoped tools were not actually using injected `user_email`
2. `risk_client` was missing convenience wrappers for several registry-exposed tools
3. target-allocation tools were categorized inconsistently with the rest of the docs

Those issues were fixed in this pass.

## Findings

### 1. User Scoping Gap in Allocation + Audit Tools

**Severity:** High  
**Status:** Fixed

Five registry-exposed tools were still resolving user context from ambient defaults instead of the agent API's server-side injected user:

- `get_target_allocation`
- `set_target_allocation`
- `get_action_history`
- `record_workflow_action`
- `update_action_status`

That meant the agent API could authenticate a caller correctly, but these tools would ignore the injected identity because their signatures lacked `user_email`.

**Fix shipped:**

- added optional `user_email` parameters to those tools
- threaded that value through their user-resolution helpers
- verified the registry now marks them as `has_user_email=True`

## 2. `risk_client` Wrapper Drift

**Severity:** Medium  
**Status:** Fixed

The thin HTTP client did not expose convenience wrappers for several registry tools, even though they were available server-side:

- `analyze_basket`
- `export_holdings`
- `get_action_history`
- `get_portfolio_events_calendar`
- `get_portfolio_news`
- `get_target_allocation`
- `list_accounts`
- `list_portfolios`
- `set_target_allocation`

This was not a server bug, but it weakens parity for an external caller integrating through the packaged client.

**Fix shipped:**

- added the missing wrappers to `risk_client`
- added a parity test asserting every tool-tier registry function has a client convenience wrapper

## 3. Category Drift for Target Allocation Tools

**Severity:** Low  
**Status:** Fixed

`get_target_allocation` / `set_target_allocation` were registered under `analysis`, but the rest of the docs and tool-surface references treat them as `allocation`.

**Fix shipped:**

- moved both tools to registry category `allocation`

## 4. Discovery Schema Is Still Too Weak for Tool Synthesis

**Severity:** Medium  
**Status:** Not fixed in this pass

`GET /api/agent/registry` currently exposes parameter metadata that is useful for humans, but still thin for automatic tool synthesis:

- `Literal` types are surfaced inconsistently as strings
- dict/list payloads do not expose structured JSON-schema-like shapes
- discovery returns signature-derived metadata, not a stable contract format

Examples observed during review:

- `preview_trade.side` appears as `type: "Literal"`
- `run_whatif.target_weights` appears as `type: "Optional"`
- object payloads like `allocations` only surface `type: "dict"`

This does not block manual integration, but it is the next thing to improve if `ai-excel-addin` wants to synthesize tool definitions directly from registry output.

## 5. Preview Tools Being Write-Gated Is Intentional

**Severity:** Info  
**Status:** Verified

The trading preview tools look read-only at the business level, but they are currently persisted server-side to support idempotent execution by `preview_id`:

- `preview_trade`
- `preview_basket_trade`
- `preview_futures_roll`
- `preview_option_trade`

Because previews write short-lived preview rows, keeping them behind write gating is consistent with current implementation.

This is important for external consumers so they do not assume preview calls are side-effect-free.

## Files Changed

- `mcp_tools/allocation.py`
- `mcp_tools/audit.py`
- `services/agent_registry.py`
- `risk_client/__init__.py`
- `tests/routes/test_agent_api.py`
- `tests/test_risk_client.py`
- `tests/mcp_tools/test_allocation.py`
- `tests/mcp_tools/test_audit.py`

## Recommended Next Step

If `ai-excel-addin` will consume registry discovery dynamically rather than through a handwritten adapter, add a **machine-readable discovery schema** to `/api/agent/registry`:

- normalized primitive type
- enum values for `Literal`
- nullable marker for optional params
- array/object shape hints

That is the main remaining gap after this review.
