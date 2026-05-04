# V2.P10 Phase 0e - Hidden Dependencies Audit

## Scope Summary

This audit covers the three hidden dependencies called out by `docs/planning/V2_P10_RESEARCH_MCP_SPLIT_PLAN.md`: `_MCP_META_INJECT_SERVERS`, `_RESEARCH_AUTO_LOAD_SERVERS`, and `get_mcp_context` response consumers. It is investigation-only. No code changes were made to `risk_module`, `AI-excel-addin`, `agent-gateway-dist`, or `investment_tools` outside this new audit artifact directory.

Canonical repositories checked: `risk_module`, `AI-excel-addin`, `agent-gateway-dist`, and `investment_tools`. The user-prohibited paths `~/.claude/`, `~/.agents/`, `.claude/skills/`, and `agents/` were not read.

## Methodology

Commands run:

```bash
rg -n "_MCP_META_INJECT_SERVERS|_RESEARCH_AUTO_LOAD_SERVERS" \
  ~/Documents/Jupyter/AI-excel-addin ~/Documents/Jupyter/agent-gateway-dist \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'

rg -n "get_mcp_context" \
  ~/Documents/Jupyter/risk_module ~/Documents/Jupyter/AI-excel-addin \
  ~/Documents/Jupyter/agent-gateway-dist ~/Documents/Jupyter/investment_tools \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'

rg -n "server.*portfolio-mcp|portfolio-mcp.*server|get_mcp_context" \
  ~/Documents/Jupyter/risk_module/tests ~/Documents/Jupyter/AI-excel-addin/tests \
  ~/Documents/Jupyter/agent-gateway-dist/tests \
  --glob '!**/__pycache__/**' --glob '!**/.git/**'
```

Additional targeted reads used `nl -ba`/`sed` around the matching files to classify each consumer.

## Findings

1. `_MCP_META_INJECT_SERVERS` is defined only in `AI-excel-addin/api/agent/interactive/runtime.py` and is passed into dispatcher construction paths. The gateway packages do not import the constant directly; they consume the resolved `mcp_meta_inject_servers` set on `ToolDispatcher` instances.
2. `_RESEARCH_AUTO_LOAD_SERVERS` is also defined only in `runtime.py`. It is the F56 auto-load workaround and currently injects `portfolio-mcp` into research-mode sessions when missing.
3. `get_mcp_context` is already per-server after Phase 0c: `risk_module/mcp_server.py` returns `portfolio-mcp`; `risk_module/mcp_server_research.py` returns `research-mcp`. I found no direct consumer asserting that the `server` field of the `get_mcp_context` response must equal `portfolio-mcp`.
4. Several tests assert or instantiate hard-coded meta-injection values and must be updated with the runtime constant in Phase 1.

## Master Table

| Dependency | Current state | Consumers found | Tests asserting value/shape | Required action |
|---|---:|---:|---:|---|
| `_MCP_META_INJECT_SERVERS` | `frozenset({"portfolio-mcp"})` at `AI-excel-addin/api/agent/interactive/runtime.py:97` | 3 runtime pass-through call sites plus dynamic gateway dispatcher logic | 6 assertion/fixture sites | Phase 1: extend to `{"portfolio-mcp", "research-mcp"}` and update hard-coded expectations |
| `_RESEARCH_AUTO_LOAD_SERVERS` | `frozenset({"portfolio-mcp"})` at `AI-excel-addin/api/agent/interactive/runtime.py:90` | 1 runtime auto-load block | No direct constant assertions found | Phase 4: retire or reduce after research entrypoint and meta-injection audits pass |
| `get_mcp_context.server` | `portfolio-mcp` in portfolio server; `research-mcp` in research server | Tool-list/policy/test surfaces; no direct server-field assertion found | No direct `server == "portfolio-mcp"` assertion tied to `get_mcp_context` found | Phase 1: keep per-server responses; update only consumers that assume research tools still live on portfolio-mcp |

## `_MCP_META_INJECT_SERVERS`

### Current State

`AI-excel-addin/api/agent/interactive/runtime.py:97`

```python
_MCP_META_INJECT_SERVERS = frozenset({"portfolio-mcp"})
```

This is the allowlist that lets the gateway inject MCP call metadata, including resolved `user_id`, into calls for selected servers.

### Consumers

| Path | Line | What it does |
|---|---:|---|
| `AI-excel-addin/api/agent/interactive/runtime.py` | 318 | `_build_dispatcher(...)` passes `_MCP_META_INJECT_SERVERS` into `ToolDispatcher` for the main interactive runtime. |
| `AI-excel-addin/api/agent/interactive/runtime.py` | 630 | `make_run_agent_handler(...)` passes `_MCP_META_INJECT_SERVERS` into sub-agent/agent run dispatchers. |
| `AI-excel-addin/api/agent/interactive/runtime.py` | 645 | `make_resume_background_agent_handler(...)` passes `_MCP_META_INJECT_SERVERS` into resumed background agent dispatchers. |
| `agent-gateway-dist/agent_gateway/tool_dispatcher.py` | 405-412 | Dynamic consumer. If `server in self._mcp_meta_inject_servers`, it injects `{"session_id": ..., "user_id": ...}` into MCP tool calls. |
| `AI-excel-addin/packages/agent-gateway/agent_gateway/tool_dispatcher.py` | 405-412 | Package mirror of the same dynamic dispatcher behavior. |

There are no direct imports of `_MCP_META_INJECT_SERVERS` in `agent-gateway-dist`; all runtime wiring happens from `AI-excel-addin`.

### Tests Asserting On The Value

| Path | Line | Assertion/fixture |
|---|---:|---|
| `AI-excel-addin/tests/test_interactive_runtime_phase6.py` | 15 | Imports `_MCP_META_INJECT_SERVERS` from runtime. |
| `AI-excel-addin/tests/test_interactive_runtime_phase6.py` | 71 | Asserts dispatcher state equals `_MCP_META_INJECT_SERVERS`. This should continue to pass if the constant is updated. |
| `AI-excel-addin/tests/test_interactive_runtime_phase6.py` | 82 | Hard-codes `frozenset({"portfolio-mcp"})` in dispatcher construction. |
| `AI-excel-addin/tests/test_interactive_runtime_phase6.py` | 92 | Expects meta injection only when the server is portfolio-mcp. |
| `agent-gateway-dist/tests/test_mcp_meta_transport.py` | 65 | Constructs dispatcher with `mcp_meta_inject_servers=frozenset({"portfolio-mcp"})`. |
| `agent-gateway-dist/tests/test_mcp_meta_transport.py` | 105 | Verifies non-allowlisted servers do not receive injected meta. |
| `agent-gateway-dist/tests/test_sub_agent_mcp_session_injection.py` | 66 | Constructs dispatcher with `frozenset({"portfolio-mcp"})`. |
| `agent-gateway-dist/tests/test_sub_agent_mcp_session_injection.py` | 77 | Asserts injected meta reaches portfolio-mcp sub-agent MCP calls. |

### Phase 1 Plan

Required direct code change in Phase 1:

| Path | Line | Change |
|---|---:|---|
| `AI-excel-addin/api/agent/interactive/runtime.py` | 97 | Change `_MCP_META_INJECT_SERVERS = frozenset({"portfolio-mcp"})` to include `"research-mcp"`. |

Consumer-specific Phase 1 edits:

| Path | Line | Change |
|---|---:|---|
| `AI-excel-addin/api/agent/interactive/runtime.py` | 318 | No call-site shape change; this pass-through should pick up the updated constant. |
| `AI-excel-addin/api/agent/interactive/runtime.py` | 630 | No call-site shape change; this pass-through should pick up the updated constant. |
| `AI-excel-addin/api/agent/interactive/runtime.py` | 645 | No call-site shape change; this pass-through should pick up the updated constant. |
| `AI-excel-addin/tests/test_interactive_runtime_phase6.py` | 82, 92 | Update hard-coded fixture/expectation to cover `research-mcp` as an allowed meta-injection server, or add a second research-mcp case while preserving the portfolio-mcp case. |
| `agent-gateway-dist/tests/test_mcp_meta_transport.py` | 65, 105 | Add or update a fixture proving any allowlisted server, including `research-mcp`, receives injected meta; keep a non-allowlisted negative case. |
| `agent-gateway-dist/tests/test_sub_agent_mcp_session_injection.py` | 66, 77 | Add or update a sub-agent fixture for `research-mcp` if Phase 1 expects research-mcp tools to work in sub-agents. |

## `_RESEARCH_AUTO_LOAD_SERVERS`

### Current State

`AI-excel-addin/api/agent/interactive/runtime.py:90`

```python
_RESEARCH_AUTO_LOAD_SERVERS = frozenset({"portfolio-mcp"})
```

The F56 workaround is documented around `runtime.py:87` and executed around `runtime.py:475-481`. It force-adds missing research-mode servers before the active tool catalog is computed:

```python
missing = _RESEARCH_AUTO_LOAD_SERVERS - (session.loaded_mcp_servers or set())
if missing:
  session.loaded_mcp_servers = set(session.loaded_mcp_servers or set()) | missing
```

### Consumers

| Path | Line | What it does |
|---|---:|---|
| `AI-excel-addin/api/agent/interactive/runtime.py` | 90 | Defines the F56 research auto-load server set. |
| `AI-excel-addin/api/agent/interactive/runtime.py` | 476 | Computes missing auto-load servers for research sessions. |
| `AI-excel-addin/api/agent/interactive/runtime.py` | 477-481 | Mutates `session.loaded_mcp_servers` to include missing auto-load servers. |

No tests were found that import `_RESEARCH_AUTO_LOAD_SERVERS` or assert its exact value.

### Required Audit Path A - Research Entry Points Load `research-mcp`

Phase 1 must prove all research-mode entrypoints actually load `research-mcp` without depending on the F56 portfolio-mcp workaround.

| Surface | Current finding | Phase 1 expectation |
|---|---|---|
| `AI-excel-addin/api/agent/shared/tool_catalog.py:41-58` | `CHANNEL_TIERS` currently always-loads `fmp-mcp` and `edgar-financials`, and defers `portfolio-mcp`/`research-workbench-mcp` by channel. No `research-mcp` entry exists. | Add `research-mcp` to the always tier for research-capable channels per the V2.P10 contract. |
| `AI-excel-addin/api/agent/shared/tool_catalog.py:667-670` | Active tools are computed from tier defaults and `session.loaded_mcp_servers`. | Confirm `research-mcp` tools appear in active tool definitions for research-mode sessions without `load_tools`. |
| `AI-excel-addin/api/agent/interactive/runtime.py:488` | Active servers derive from always-tier servers plus loaded servers in the dev-mode path. | Confirm `research-mcp` is present in `active_servers` for all intended research entrypoints. |
| `AI-excel-addin/api/agent/interactive/runtime.py:413, 518, 593, 618` | Prompt/context construction passes active/loaded MCP server state through runtime helpers. | Add/update tests that prove restricted research prompts cannot lose the research server. |

### Required Audit Path B - Meta Injection Updated Coherently

Phase 1 must update `_MCP_META_INJECT_SERVERS` at the same time. A research-mode auto-load without meta injection would expose `research-mcp` but break tools requiring user identity.

Required coherence check:

| Check | Expected result |
|---|---|
| `research-mcp` is in `CHANNEL_TIERS` always tier | Yes |
| `research-mcp` is in MCP client allowlist | Yes |
| `research-mcp` is in server policies | Yes |
| `research-mcp` is in `_MCP_META_INJECT_SERVERS` | Yes |
| A research-mode entrypoint can call `research-mcp` with resolved `user_id` meta | Yes |

### Phase 4 Plan

Per Decisions #11/#37 and the Phase 0 acceptance criteria, the F56 block at `runtime.py:87` and `runtime.py:475-481` can be retired after both audit paths pass.

Recommended Phase 4 disposition:

| Option | Condition | Risk |
|---|---|---|
| Retire block | All research entrypoints always load `research-mcp` and meta injection is proven in tests | Lowest long-term complexity |
| Keep belt-and-suspenders | There are still legacy sessions that may lack explicit server state | Avoids immediate regressions, but hides future server-tier mistakes |

If kept temporarily, the block should not keep auto-loading `portfolio-mcp` for research-only corpus tools after the Phase 1 cutover.

## `get_mcp_context` Server Field

### Current State

The plan reference mentioned `mcp_server.py:396`, but the current file has shifted after Phase 0c. Current definitions:

| Path | Line | Response field |
|---|---:|---|
| `risk_module/mcp_server.py` | 221 | Returns `"server": "portfolio-mcp"`. |
| `risk_module/mcp_server_research.py` | 70 | Returns `"server": "research-mcp"`. |

The per-server response is already correct.

### Consumers Checked

| Path | Line | What it does | Server-field assertion? |
|---|---:|---|---|
| `AI-excel-addin/api/agent/shared/server_policies.py` | 232 | Lists `get_mcp_context` as a known portfolio-mcp read tool. | No |
| `AI-excel-addin/tests/test_server_policy_drift.py` | 393 | Expected portfolio-mcp policy tool list includes `get_mcp_context`. | No direct response assertion |
| `risk_module/tests/test_user_identity_bypass_sites.py` | 121-133 | Calls `module.get_mcp_context()` to verify identity bypass behavior. | No |
| `risk_module/tests/test_tool_surface_sync.py` | 13, 35 | Includes `get_mcp_context` in inline MCP tool surface synchronization. | No |
| `risk_module/tests/routes/test_agent_api.py` | 893 | Includes `get_mcp_context` in agent tool registry response. | No |
| `risk_module/docs/interfaces/mcp.md` | 30 | Documents MCP tool surface. | Documentation only |

No consumer was found that asserts `get_mcp_context()["server"] == "portfolio-mcp"`.

### Phase 1 Plan

No direct response change is needed for `get_mcp_context`; the per-server values are already correct. Phase 1 should update only consumers that expected research-flavored tools to be served by `portfolio-mcp`.

Specific caution:

| Path | Line | Caution |
|---|---:|---|
| `AI-excel-addin/api/agent/shared/server_policies.py` | 232 | If `get_mcp_context` is exposed on both portfolio-mcp and research-mcp, server policy uniqueness/collision behavior must be explicit. |
| `AI-excel-addin/tests/test_server_policy_drift.py` | 393 | Drift test should reflect whether `get_mcp_context` remains portfolio-only or appears in both server policies. |

## Open Questions For User

| Question | Why it matters |
|---|---|
| Should `get_mcp_context` be exposed on both servers in AI-excel server policies, or remain portfolio-only for policy purposes? | The risk_module research server already implements it, but AI-excel policy does not yet model `research-mcp`. |
| Should meta-injection tests in `agent-gateway-dist` explicitly name `research-mcp`, or stay generic with arbitrary allowlisted server names? | Explicit names improve V2.P10 confidence; generic tests preserve package neutrality. |
| Should the F56 auto-load workaround be removed in the same PR as Phase 4, or kept for one release after cutover? | Keeping it may protect old sessions, but it can hide missing tier configuration. |

## Phase 1+ Implications

1. Phase 1 must update `_MCP_META_INJECT_SERVERS` and server-tier/allowlist/policy surfaces in the same cutover PR. Exposing `research-mcp` without meta injection is a likely user-identity regression.
2. Phase 1 tests should prove a `research-mcp` MCP call receives injected meta through both main interactive runtime and sub-agent dispatch paths.
3. Phase 4 should not retire the F56 block until a test proves restricted research-mode sessions can see and call research-mcp tools without `load_tools`.

## In-Scope But Flagged For Caution

| Item | Caution |
|---|---|
| Duplicate `get_mcp_context` tool name across servers | The implementation is per-server correct, but policy/tool-catalog code must define whether duplicate diagnostic tool names are allowed when both servers are active. |
| Hard-coded test fixtures | Several tests manually pass `frozenset({"portfolio-mcp"})`; update intentfully so negative tests still cover non-allowlisted servers. |
| F56 retirement | Do not remove the auto-load block based only on code inspection; verify actual research entrypoints and active tool definitions first. |
