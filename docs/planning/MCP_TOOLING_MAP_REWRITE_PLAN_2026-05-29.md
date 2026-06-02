# Plan: Rewrite `docs/architecture/agent-maps/MCP_TOOLING_AGENT_MAP.md`

**Date:** 2026-05-29 · **Status:** for Codex review → implement
**Why:** The Batch-1 autonomous draft fabricated a 4-tier tool system (`TOOL_TIERS`/`TIER_HIERARCHY`/`should_load_tool`/`MCP_TOOL_TIER`/`CURRENT_TIER` — **no code occurrences**; these symbols appear only in docs). That draft was reverted to HEAD. This is the grounded re-author, per the plan→Codex pipeline.

**Contract:** every concrete claim in the rewritten doc must carry a `file:line` citation matching the facts below. Anything not in "Verified facts" must NOT be asserted as existing. Follow `docs/standards/AGENT_DOCUMENTATION_STANDARD.md`. Cross-link `docs/reference/MCP_SERVERS.md` as the count owner — do not hard-code drifting counts.

---

## Verified facts (grep-confirmed; the writer cites these)

### 1. Server roster / construction / entrypoints
- **portfolio-mcp**: `FastMCP("portfolio-mcp", instructions=..., lifespan=pool_cleanup)` `mcp_server.py:184-188`; run via `_run_server()` → `mcp.run()` `mcp_server.py:3571-3573`; guard `:3576-3577`. **No `main()`.**
- **research-mcp**: `FastMCP("research-mcp", ...)` `mcp_server_research.py:58-66`; `_run_server()` → `mcp_research.run()` `:115-117`; guard `:120-121`. Variable is `mcp_research`. **No `main()`.**
- **fmp-mcp**: `FastMCP("fmp-mcp", ...)` `fmp/server.py:83-114`; **has `def main()`** `:1267` → `mcp.run()` `:1268-1269`.
- **ibkr-mcp**: `FastMCP("ibkr-mcp", ...)` `ibkr/server.py:55-58`; **has `def main()`** `:422` → `mcp.run()` `:423-424`.

### 2. Counts (owned by MCP_SERVERS.md — cross-link, don't hard-code)
- portfolio=115, research=22, fmp=20, ibkr=7 (total 164), per `docs/reference/MCP_SERVERS.md:5-16`. Count methods: `grep -c "@mcp.tool()"` for portfolio/fmp/ibkr; `grep -c "mcp_research.tool()"` for research. (`fmp/server.py:1018 get_stock_fundamentals` is defined but undecorated → not a tool; count is 20.)

### 3. Registration mechanics
- portfolio-mcp / fmp / ibkr use the **`@mcp.tool()` decorator**; research-mcp uses **call-form `mcp_research.tool()(_func)`** `mcp_server_research.py:71-92`.
- portfolio-mcp has a `structured_tool` wrapper `mcp_server.py:194-215` (exception → `{"status":"error",...}`).
- **Anti-misread guard:** `mcp_server.py:55-175` is one contiguous `from mcp_tools.* import ... as _x` block (imports, NOT definitions — this is exactly what the fabricated draft misread). FastMCP construction starts `:184`. research-mcp import block `:31-52`.

### 4. REAL gating — role-based, NOT tiers
- `mcp_tools/_tier_policy.py:7-31` `INTERNAL_ONLY_PORTFOLIO_TOOLS = frozenset({...})` — **23 tools**. `write_internal_only_json()` `:34-40` mirrors to `mcp_tools/internal_only_portfolio_tools.json`.
- **Enforcement (single site):** `UserIdMiddleware.on_call_tool` `mcp_middleware.py:124-128` — `if tool_name in INTERNAL_ONLY_PORTFOLIO_TOOLS and role != "owner": raise ToolError(...)`. Import `:9`; role from request meta `:121`.
- Semantics: **owner vs not-owner** only (unknown/None treated as not-owner). Pinned by `tests/portfolio_mcp_multi_user/test_tier_isolation.py:68-72` (len==23 + JSON parity) and behavioral tests `:22-65`.
- **"always-tier" / "deferred" is a cross-repo gateway (AI-excel-addin `CHANNEL_TIERS`) concept**, described in READMEs (`MCP_SERVERS.md:12,73`; `mcp_tools/README.md:52,81`) — NOT a risk_module code construct. Do not document its internals here.

### 5. Auth / user scoping
- Middleware: `mcp.add_middleware(UserIdMiddleware())` `mcp_server.py:191`; `mcp_research.add_middleware(...)` `mcp_server_research.py:68`. **fmp-mcp and ibkr-mcp register NO middleware — unscoped.**
- `UserIdMiddleware` `mcp_middleware.py:117-141`: reads user_id/channel/role from meta `:119-122` (role at `:122`); role check `:124-128`; resolves email via `_resolve_email_for_user_id` (DB `SELECT email FROM users WHERE id=%s`, 300s cache) `:82-114`; sets `_USER_EMAIL_CTX` + `_GATEWAY_REQUEST_ACTIVE` `:135-141`.
- `resolve_user_email` `utils/user_context.py:216-234`, re-exported `settings.py:89`. **Resolution order:** (1) explicit `email` arg — ignored if gateway active `:221-228`; (2) gateway-injected `_USER_EMAIL_CTX` (source=gateway) `:148-150,187-189`; (3) gateway-active-but-unresolved → raise `:191-196`; (4) env `RISK_MODULE_USER_EMAIL` `:122-124`; (5) `.env` fallback `:129-134` unless `MCP_SUBPROCESS=true` `:96-97,126-127`; (6) else raise `:209-213`. No api-key/google-id branch in this function (the numeric user_id→email DB lookup is the middleware's job).

### 6. Response envelope (no single function — conventions)
- `{"status":"success"|"error", ...}` via: `handle_mcp_errors` decorator `mcp_tools/common.py:21-51` (~132 `@handle_mcp_errors` decorators across ~48 `mcp_tools/` files; auth errors add `"auth_required":True`); `structured_tool` `mcp_server.py:194-215`; per-result `to_api_response()` methods under `core/result_objects/*.py` (e.g. `positions.py:144,159`), `options/result_objects.py`, `trading_analysis/models.py`. `require_db` `mcp_tools/common.py:54-83`.

### 7. V2.P10 split + read-only invariant
- Plan: `docs/planning/completed/V2_P10_RESEARCH_MCP_SPLIT_PLAN.md` — separate FastMCP entrypoint (Option B), triggered by citation tools failing in the deferred portfolio surface. Always-tier eligibility = read-only AND user-owned AND bounded AND no artifact/side-effects (plan:38). **Read-only contract on research-mcp = curation convention, NOT a runtime check** (only docstring `:5` + `instructions=` `:63` mention it; no guard rejects writes).

### 8. Add-a-tool flow
- Thin adapter in `mcp_tools/` delegating to `actions/` where applicable (`mcp_tools/research.py:8` imports `actions.research as research_actions` and delegates to it; `mcp_tools/README.md:18-31`). Register on the right server (`@mcp.tool()` vs `mcp_research.tool()(_fn)`), per `mcp_tools/README.md:78-83`. fmp/ibkr sync via `scripts/sync_fmp_mcp.sh` / `scripts/sync_ibkr_mcp.sh` (portfolio/research are NOT -dist-synced; registered via `scripts/register_claude_mcp.sh`). Restart client to reload (`MCP_SERVERS.md:169`). Tests: `tests/mcp_tools/`, parity in `tests/test_tool_surface_sync.py`, `tests/test_research_mcp.py`.

### 9. Bootstrap
- `mcp_bootstrap.bootstrap()` `mcp_bootstrap.py:136` (stdout→stderr, .env, env-validate, nest_asyncio) + `configure_mcp_process_db_pool(...)` `mcp_lifecycle.py:18` — called `mcp_server.py:22-26`, `mcp_server_research.py:20-24`. fmp/ibkr use inline redirect + `bootstrap_env.bootstrap(...)`.

## Do NOT document (unverifiable from this repo)
- CHANNEL_TIERS / always-vs-deferred loading mechanism (cross-repo gateway).
- `_MCP_META_INJECT_SERVERS`, citation-envelope extractors (cross-repo).
- Full `role` enum beyond owner/not-owner (gateway-owned).
- Any 4-tier system (does not exist).

## Section outline (per AGENT_DOCUMENTATION_STANDARD.md)
1. Server Topology / Source-&-Routing Summary (4-server table; cross-link counts to MCP_SERVERS.md)
2. Read Order (mcp_server.py → mcp_server_research.py → mcp_middleware.py → _tier_policy.py → utils/user_context.py → mcp_tools/common.py → README → MCP_SERVERS.md)
3. Registration Mechanics (decorator vs call-form; structured_tool; import-block anti-misread guard)
4. Real Tool Gating — `INTERNAL_ONLY_PORTFOLIO_TOOLS` (role-based; enforcement site; "NOT a 4-tier system" note)
5. Auth / User Scoping (middleware + resolution order; fmp/ibkr unscoped)
6. Response Envelope / Contracts — Canonical Payload / Contract Keys (`{status: success|error}`; the 4 mechanisms)
7. portfolio↔research Split (V2.P10; read-only = convention)
8. Add-a-Tool Checklist
9. Smoke Commands (tools/list snippets from MCP_SERVERS.md:147-162; pytest; grep-count cmds)
10. Quick Triage Map (symptom → first file)
11. Upstream / Cross-links — upstream API links **and where each is used** (MCP protocol + FastMCP for registration/runtime; FMP/IBKR maps + reference docs for provider upstreams) + `docs/reference/MCP_SERVERS.md` (count owner), `mcp_tools/README.md`, `docs/interfaces/mcp.md`

## Acceptance
- Zero claims about a 4-tier system. Gating documented as role-based owner-only.
- Every load-bearing claim carries a `file:line` from the verified list.
- Counts cross-linked to MCP_SERVERS.md, not hard-coded.
- Follows the agent-map conventions in the standard.
