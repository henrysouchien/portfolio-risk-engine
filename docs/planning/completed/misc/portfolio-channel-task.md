# Web App Channel — Task Spec

## Context

The analyst platform has the multi-channel gateway (Phase 3, `5022fae`), Telegram channel, and persistent memory all working. The `risk_module` at `/Users/henrychien/Documents/Jupyter/risk_module` has a full standalone chat stack — React frontend, FastAPI backend, and its own Claude service layer — that is entirely separate from the gateway. This migration makes the risk_module frontend a new gateway channel, giving it the **same Claude** as the TUI, Excel, and Telegram channels — same tools, same memory, same identity. (Known limitation: `portfolio-mcp` is currently single-user — see Open Questions #3.)

### Core Principle

The web app Claude is **the same agent as every other channel**. It gets its tools from the same infrastructure — `TOOL_DEFINITIONS` + `mcp_clients.get_tool_definitions()` (which includes FMP, EDGAR, model-engine, and after this migration, `portfolio-mcp`). No custom tool proxy, no separate tool definitions, no special plumbing. The web app is just a different frontend talking to the same gateway. Channel-specific differences: Excel tools are filtered out for non-Excel channels, the system prompt adapts context headings per channel, and the frontend/SSE event mapping differs. This filtering is new — Phase 1 adds it for both web and Telegram simultaneously (Telegram doesn't send `channel` context today; Phase 1 fixes that too).

### Prerequisite: Add `portfolio-mcp` to gateway's MCP allowlist

`McpClientManager` in `api/mcp_client.py` has an `ALLOWED_SERVERS` set that controls which MCP servers are loaded at startup. Currently: `{"fmp-mcp", "edgar-financials", "model-engine"}`. `portfolio-mcp` is NOT in this list, so its tools are not available to the gateway today.

**Required change**: Add `"portfolio-mcp"` to `ALLOWED_SERVERS`:
```python
ALLOWED_SERVERS = {"fmp-mcp", "edgar-financials", "model-engine", "portfolio-mcp"}
```

This makes portfolio tools available to ALL channels (TUI, Excel, Telegram, web app) — which is the correct behavior. The portfolio-mcp server must be configured in `~/.claude.json` (it already is for Claude Code usage).

**Deployment topology**: `McpClientManager` launches MCP servers as **local stdio subprocesses** (see `StdioServerParameters` usage in `api/mcp_client.py` — uses a `command` + `args` list from `~/.claude.json`). This means the gateway process and `portfolio-mcp` must run on the **same machine** with access to the same filesystem and Python environment. In the current dev setup, both repos are on the same machine and `~/.claude.json` has the correct path to `risk_module/mcp_server.py`. For production deployment, either: (a) co-locate gateway and portfolio-mcp on the same host, or (b) migrate portfolio-mcp to an SSE/HTTP transport (a separate, follow-up effort).

**Timeout override**: Portfolio tools can be slow (optimization, scenario analysis). Add to `_SERVER_TIMEOUT_OVERRIDES`:
```python
_SERVER_TIMEOUT_OVERRIDES = {"model-engine": 600, "portfolio-mcp": 120}
```

### Tool parity: `portfolio-mcp` vs `ai_function_registry`

The old risk_module chat had 16 tools via `ai_function_registry.py`. `portfolio-mcp` (`mcp_server.py`) exposes a different (larger) set of tools built for the MCP pattern. Some old AI-registry tools have direct equivalents in portfolio-mcp, some are covered differently, and a few may be missing:

**Available in portfolio-mcp**: `get_positions`, `get_risk_score`, `get_risk_analysis`, `get_leverage_capacity`, `set_risk_profile`, `get_risk_profile`, `get_performance`, `get_trading_analysis`, `analyze_option_strategy`, `analyze_stock`, `run_optimization`, `run_whatif`, `get_factor_analysis`, `get_factor_recommendations`, `get_income_projection`, `get_portfolio_news`, `get_portfolio_events_calendar`, `suggest_tax_loss_harvest`, `preview_trade`, `execute_trade`, `get_orders`, `cancel_order`, `check_exit_signals`

**Old AI-registry tools that may NOT have portfolio-mcp equivalents**:
- `create_portfolio_scenario` — creates YAML scenario files. May need to be added to portfolio-mcp or handled differently.
- `estimate_expected_returns` / `set_expected_returns` — forward return estimation. Check if covered by `get_factor_analysis` or `run_whatif`.
- `list_portfolios` / `switch_portfolio` — portfolio switching. The MCP tools take `portfolio_name` as a parameter per-call instead of maintaining stateful context. This is actually cleaner.

**Action**: Before migration, create a parity matrix at `docs/design/portfolio-tool-parity.md`: a table mapping each AI-registry tool to its portfolio-mcp equivalent. Each tool must be categorized as one of: "mapped" (equivalent exists), "intentionally dropped" (not needed in new architecture, with reason), or "to be added" (gap, must implement in `portfolio-mcp` before migration). Pass criteria: zero "to be added" entries remaining. Any missing tools are added to `portfolio-mcp`'s `mcp_server.py` as part of Phase 0 — this is a prerequisite blocking Phase 1. **Enforcement**: The completed parity matrix must be reviewed and approved (PR review or document sign-off) before Phase 1 work begins. This is a manual gate, not a CI check — the matrix is a one-time artifact.

**Tool name collision audit**: `McpClientManager` filters out duplicate tool names across MCP servers AND against built-in tools in `TOOL_DEFINITIONS` (see `api/mcp_client.py:231,243`). Verify that `portfolio-mcp` tool names do not collide with (a) tools from other MCP servers (FMP, EDGAR, model-engine), or (b) built-in tools in `TOOL_DEFINITIONS`. If any collisions exist, rename the conflicting tools in `portfolio-mcp` before adding it to `ALLOWED_SERVERS`. Add a test (`test_portfolio_mcp_no_tool_collisions`) that asserts all expected portfolio-mcp tools survive registration against both MCP and built-in tool names.

### What exists in risk_module today

**Frontend** (`frontend/packages/connectors/src/features/external/` and `frontend/packages/ui/src/components/chat/`):
- `AIChat.tsx` — modal chat interface (floating panel)
- `ChatCore.tsx` (`chat/shared/ChatCore.tsx`) — shared chat logic (message rendering, file handling, streaming)
- `ChatInterface.tsx` — full-screen chat
- `ChatContext.tsx` — state management (`useSharedChat()`, `useChatTransition()`)

**Frontend hooks/services**:
- `useChat.ts` — generic chat hook (used by non-portfolio chat surfaces)
- `usePortfolioChat.ts` — portfolio-specific chat hook (streaming, portfolio context loading)
- `ClaudeService.ts` (`frontend/packages/chassis/src/services/ClaudeService.ts`) — HTTP client that calls the risk_module backend
- `APIService.ts` (`frontend/packages/chassis/src/services/APIService.ts`) — also has Claude chat methods (non-streaming)

**Backend** (`routes/claude.py`):
- `POST /api/claude_chat` — synchronous chat
- `POST /api/claude_chat_stream` — SSE streaming
- Request: `{user_message, chat_history, portfolio_name}`

**Backend services** (`services/claude/`):
- `chat_service.py` (~81KB) — full Claude orchestration: Anthropic client, tool loop, prompt caching
- `function_executor.py` (~82KB) — executes portfolio tools via `ai_function_registry`

**What gets eliminated**: `chat_service.py` (~81KB) is fully removed. `function_executor.py` (~82KB) — the Phase 4 dependency audit determines what stays. If `portfolio-mcp` imports the executor class, it stays; if not, the whole file is removed. The gateway's `AgentRunner` replaces chat orchestration. The risk_module backend keeps running as: (a) the host for `portfolio-mcp`, and (b) the auth/SSE proxy for the gateway (Phase 3b — thin passthrough, not chat orchestration).

## Architecture

```
Web App Frontend          risk_module Backend        Gateway (AI-excel-addin)
─────────────────        ──────────────────         ──────────────────────
React chat UI ────────→  /api/gateway/chat  ─────→  /api/chat/init (session)
  (GatewayClaudeService) /api/gateway/      ─────→  /api/chat (SSE stream)
  (same-origin, cookie)   tool-approval     ─────→  /api/chat/tool-approval
                         (backend proxy,             │
                          API key hidden)             ▼
                         Also hosts:             AgentRunner
                          portfolio-mcp               │
                          (stdio MCP server      ToolDispatcher
                           at mcp_server.py)          │
                                    ┌────────────────┼────────────────┐
                                    ▼                ▼                 ▼
                              Excel tools      MCP tools          Local tools
                              (when open)    (portfolio-mcp,      (file_*, memory_*,
                                              FMP, EDGAR,          run_bash)
                                              model-engine)
```

**Key principle**: The web app is a **pure consumer channel** — same as Telegram. It provides no tools of its own. It uses the same gateway protocol and agent runner as other channels, accessed via a backend proxy (the frontend never calls the gateway directly — see Phase 3b).

**Boundary between repos after migration**: The gateway (`AI-excel-addin`) owns all chat orchestration — agent loop, tool dispatch, prompt building, memory. The risk_module backend has exactly two roles: (1) **host `portfolio-mcp`** as a stdio MCP server (the gateway connects to it like any other MCP), and (2) **thin auth/SSE proxy** for the web app frontend (Phase 3b — cookie auth in, API key out, no chat logic). Legacy orchestration code is removed in Phase 4: `chat_service.py` is fully deleted; `function_executor.py` removal is conditional on a dependency audit (see Phase 4 step 5 — dependency audit) — retain anything that `portfolio-mcp` actually imports.

Portfolio tools are available via `portfolio-mcp` through `McpClientManager` — once the prerequisite is completed (adding `"portfolio-mcp"` to `ALLOWED_SERVERS`). No separate tool proxy or tool definition sync needed.

### What the web app gains for free
- Persistent analyst memory (memory_recall, memory_store, MEMORY.md)
- All MCP tools currently in `ALLOWED_SERVERS`: FMP market data, EDGAR filings, model-engine — plus `portfolio-mcp` once added per the prerequisite. Note: `sheets-finance` is also not in `ALLOWED_SERVERS` today; add it if needed for web app workflows.
- Adaptive system prompt
- Single analyst brain across all surfaces (TUI, Excel, Telegram, web app)

### Limitation: Excel tools NOT available from web app
Excel tool execution requires a `tool_execute_request` → `tool-result` handshake over the Excel add-in's SSE stream (`/api/mcp/events`). The web app frontend does not connect to this SSE endpoint, so Excel tools (read_cells, write_cells, update_model, etc.) will time out if invoked. This is the **same limitation as the Telegram channel** (see `docs/design/telegram-channel-task.md` line 21).

Hard enforcement (after Phase 1): `get_active_tool_definitions()` will exclude Excel tools from the tool list when `channel_context` is in `_NON_EXCEL_CHANNELS` (`"web"` or `"telegram"`), so Claude cannot call them.

**Prerequisite**: This enforcement only works on the agent runner path (`USE_AGENT_RUNNER=true`), which is the current default (`api/main.py:66`). The legacy path (`USE_AGENT_RUNNER=false`) uses `_get_cached_tools()` and `build_system_prompt()` without channel context — it does not filter tools.

**Phased enforcement** (no runtime phase config — these are sequential code changes):

1. **Phase 1 commit**: Add a startup warning log (`log.warning`, matching the existing logger name in `api/main.py`) if `USE_AGENT_RUNNER=false`. The warning is a static code check — it ships in Phase 1 and remains until the Phase 4 cutover.

2. **Phase 4 commit**: Replace the warning with a hard `SystemExit("USE_AGENT_RUNNER=false is no longer supported")`. This is a one-line code change in `api/main.py`, committed as part of the Phase 4 cleanup PR. By this point, all channels use the agent runner path and the legacy path is dead code.

3. **Request-time guard (ships in Phase 1, stays through Phase 4)**: If a request includes `channel_context` (web or telegram) and the legacy code path is active, reject with HTTP 503 **before** `session.stream_active = True` is set, to avoid deadlocking the session. This guard is the safety net while `USE_AGENT_RUNNER` is still configurable.

Tests: `test_use_agent_runner_false_warns` (#22) tests the Phase 1 warning behavior. `test_use_agent_runner_false_exits` (#23) is added in Phase 1 with `@pytest.mark.skip("Phase 4")` and unskipped in Phase 4 when the code changes. Both tests monkeypatch `USE_AGENT_RUNNER` directly.

Note: `USE_AGENT_RUNNER` is a module-level constant evaluated at import time (`api/main.py:66`). Tests that toggle this value must monkeypatch the constant directly or use an app-factory pattern with config injection.

**Deployment ordering**: The Telegram `context.channel` fix (Phase 1b, in `telegram_bot/bot.py`) and the gateway filtering + 503 guard (Phase 1a, in `api/`) ship in the same release. Both are in the same repo. Since `USE_AGENT_RUNNER=true` is the current default, the 503 guard is a safety net only — it won't trigger in normal operation. Ensure `USE_AGENT_RUNNER=true` is active before deploying Phase 1.

## Key Differences to Bridge

| Dimension | Gateway | risk_module |
|-----------|---------|-------------|
| **Request shape** | `{messages: [{role,content}], context: {channel?, portfolio_name?}}` | `{user_message, chat_history, portfolio_name}` |
| **Auth** | Bearer token from `/api/chat/init` | Session cookie from auth_service |
| **SSE text event** | `{type:"text_delta", text:"..."}` | `{type:"text_delta", content:"..."}` |
| **SSE stream end** | `{type:"stream_complete", usage:{...}}` | `{type:"message_stop"}` + `{type:"usage"}` |
| **SSE tool start** | `{type:"tool_call_start", tool_call_id, tool_name, tool_input}` | `{type:"tool_call_start", tool_name}` |
| **Tool execution** | Server-side via ToolDispatcher → MCP clients | Server-side via ClaudeFunctionExecutor |
| **Tools** | `TOOL_DEFINITIONS` + all MCP servers (filtered per channel — Excel tools excluded for non-Excel channels) | 16 portfolio analysis functions (standalone) |

## Implementation Steps

### Phase 1: Per-Channel Tool Filtering in Gateway

The web app channel can't use Excel tools (no SSE handshake). Rather than relying on prompt instructions, hard-exclude them from the tool list.

**1a. Add `channel_context` to `get_active_tool_definitions()`**

In `api/tools.py`:
```python
# Channels that cannot use Excel tools (no SSE handshake)
_NON_EXCEL_CHANNELS = {"web", "telegram"}

def get_active_tool_definitions(
    registry: "ChannelRegistry",
    channel_context: Optional[str] = None,
) -> List[Dict[str, Any]]:
    import copy
    from mcp_client import mcp_clients

    available = registry.get_available_tool_names()

    # Per-channel exclusion: web/telegram channels cannot use Excel tools
    # (Excel tool execution requires the add-in's SSE handshake)
    if channel_context in _NON_EXCEL_CHANNELS:
        from excel_mcp.relay import ChannelType
        for ch in registry.get_active_channels():
            if ch.channel_type == ChannelType.EXCEL:
                available = available - ch.tool_names

    tools = [copy.deepcopy(tool) for tool in TOOL_DEFINITIONS if tool["name"] in available]
    for tool in mcp_clients.get_tool_definitions():
        if tool.get("name") in available:
            tools.append(copy.deepcopy(tool))

    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools
```

**1b. Fix Telegram bot to send `channel_context`**

The Telegram bot's `BackendClient.stream_chat()` (`telegram_bot/backend_client.py`) currently sends `context: context or {}`, where `context` comes from the bot's caller. The bot does NOT set `channel: "telegram"` today, so the Excel-tool filtering won't trigger for Telegram either.

**Fix**: In `telegram_bot/bot.py`, ALL `stream_chat()` call sites must pass `context={"channel": "telegram"}`. There are 3 call sites:
1. `bot.py:334` — main message handler
2. `bot.py:280` — compaction/summarization (`_summarize`)
3. `bot.py:311` — session-capture stream

`BackendClient.stream_chat()` already accepts a `context` parameter (`backend_client.py:131`). The fix is just passing `context={"channel": "telegram"}` at each call site.

This is a small change to the Telegram bot, but it's required for the filtering to work. Without it, Telegram sessions could include Excel tools in the tool list (which would time out if called).

**1c. Plumb `channel_context` into `AgentRunner.run()`**

Add an optional parameter (note: `model_override` already exists in the current signature — no change to it here. The gateway handler always passes `model_override=body.model`. For web requests, the proxy strips `model` so `body.model` is `None` and the gateway uses its default. Other channels like Telegram can still set `body.model` directly):
```python
async def run(
    self,
    messages: List[Dict[str, Any]],
    system_prompt: Optional[str] = None,
    model_override: Optional[str] = None,  # existing param, unchanged
    channel_context: Optional[str] = None,  # NEW
) -> None:
```

In `run()`, pass `channel_context` to both tool definitions and dispatcher:
```python
if self._channel_registry is not None:
    cached_tools = get_active_tool_definitions(self._channel_registry, channel_context=channel_context)
else:
    cached_tools = _get_cached_tools()

# Store for dispatcher use
self._channel_context = channel_context
```

And when calling dispatch:
```python
result, error = await self._dispatcher.dispatch(tool_id, tool_name, tool_input, channel_context=self._channel_context)
```

**1d. Add channel enforcement to `ToolDispatcher.dispatch()`**

In `api/agent/tool_dispatcher.py`, add a `channel_context` parameter to `dispatch()`. Before approval gating, check if the tool belongs to an Excel channel and reject it for non-Excel channels:

```python
async def dispatch(self, tool_id, tool_name, tool_input, channel_context=None):
    # Defense-in-depth: reject Excel tools for non-Excel channels
    # Must run BEFORE approval gating to avoid emitting tool_approval_request
    from tools import _NON_EXCEL_CHANNELS
    if channel_context in _NON_EXCEL_CHANNELS and self._channel_registry is not None:
        from excel_mcp.relay import ChannelType
        for ch in self._channel_registry.get_active_channels():
            if ch.channel_type == ChannelType.EXCEL and tool_name in ch.tool_names:
                return None, {
                    "code": "tool_unavailable",
                    "message": f"Tool '{tool_name}' is not available from this channel",
                }
    # ... rest of dispatch logic (approval check, execution)
```

Note: uses `self._channel_registry` (the existing attribute name in `ToolDispatcher`). Error dict uses `{"code", "message"}` shape — matching the existing dispatch error contract (`tool_dispatcher.py:85`).

This prevents any tool execution bypass — even if the LLM somehow calls an Excel tool that wasn't in its tool list, the dispatcher rejects it before approval or execution.

In `api/main.py`, extract and normalize `channel_context` once at the top of the endpoint handler, then pass to all consumers:
```python
# Canonical extraction + normalization (once, at top of handler)
_raw_channel = (body.context or {}).get("channel")
channel_context = _raw_channel.strip().lower() if isinstance(_raw_channel, str) else None

# Pass to runner — model_override uses existing body.model passthrough (unchanged).
# The proxy strips `model` from web requests (see Phase 3b), so body.model is None for web.
# Telegram's /model command still works because it sends model in the request body directly.
await runner.run(
    messages=messages,
    system_prompt=system_prompt,
    model_override=body.model,  # existing behavior, unchanged
    channel_context=channel_context,  # NEW — normalized
)
```

All references to `channel_context` in this spec mean the normalized string extracted above. The term `context.channel` refers to the raw field in the request body.

### Phase 2: System Prompt Channel Awareness

**2a. Pass `channel_context` to `build_system_prompt()`**

The current `build_system_prompt()` uses `channel_registry.is_channel_type_connected(ChannelType.EXCEL)` to decide whether to include Excel-specific prompt sections (column identification, update_model guide, Excel tool usage). This is **wrong for web/telegram channels** — if Excel happens to be connected, the web app gets Excel-focused prompts even though it can't use Excel tools.

**Fix**: Add a `channel_context` parameter and use it to override the `excel_connected` decision:

```python
def build_system_prompt(
    context: Optional[Dict[str, Any]] = None,
    channel_registry: Optional["ChannelRegistry"] = None,
    channel_context: Optional[str] = None,  # NEW
) -> str:
    # Excel prompt sections only shown if:
    # 1. Excel is actually connected, AND
    # 2. The requesting channel can use Excel tools
    excel_connected = True
    if channel_registry is not None:
        try:
            from excel_mcp.relay import ChannelType
            excel_connected = channel_registry.is_channel_type_connected(ChannelType.EXCEL)
        except Exception:
            excel_connected = False

    # Non-Excel channels never get Excel prompt sections, even if Excel is connected
    # Track whether Excel is filtered by channel (vs actually disconnected) for wording
    channel_restricted = False
    if channel_context in _NON_EXCEL_CHANNELS and excel_connected:
        channel_restricted = True
        excel_connected = False

    sections = [
        _build_identity_section(excel_connected, channel_restricted=channel_restricted),
        _build_edgar_section(),
    ]
    # ... existing section-building logic unchanged ...
    # The existing _build_context_section() call gains the new parameter:
    # _build_context_section(context, channel_context=channel_context)
```

This ensures the web app and Telegram always get the "no Excel" prompt path (broader identity, no update_model guide, no column identification, no Excel tool usage section).

**Note on wording**: Both `_build_identity_section()` and `_build_no_excel_section()` hardcode "Excel is not currently connected" phrasing. When `channel_context` forces `excel_connected = False` but Excel IS actually connected (for other channels), this wording is technically incorrect. Fix both functions:
- Pass a `channel_restricted: bool` flag (true when `channel_context in _NON_EXCEL_CHANNELS` and Excel is actually connected)
- When `channel_restricted`: "Excel tools are not available from this channel" (identity section), "You do not have access to Excel tools in this session" (no-Excel section)
- When truly disconnected: keep existing "Excel is not currently connected" wording

In `api/main.py`, pass the same normalized `channel_context` (extracted once at top of handler) to the prompt builder:
```python
system_prompt = build_system_prompt(
    context=body.context or {},
    channel_registry=CHANNEL_REGISTRY,
    channel_context=channel_context,  # same normalized value used everywhere
)
```

**2b. Make context section channel-aware**

The current `_build_context_section()` unconditionally renders the heading `## Current Workbook Context`. This is wrong for non-Excel channels. Two fixes:

1. **Rename the heading dynamically**: When `channel_context == "web"`, use `## Current Portfolio Context`. When `channel_context == "telegram"`, use `## Current Session Context`. When no channel context or default, keep `## Current Workbook Context`.

2. **Portfolio context rendering**: When `channel_context == "web"`, `_build_context_section()` renders `portfolio_name` under the "Current Portfolio Context" heading. Same mechanism as workbook context for Excel, just different heading and content. Position data is NOT sent inline — Claude calls `get_positions` (portfolio-mcp) on demand when it needs portfolio data. This keeps the request payload lean.

**Memory entity extraction**: Extend `_extract_entities_from_context()` to extract tickers from `portfolio_name` when present (e.g., "MSCI Model" → `{"MSCI"}`). This ensures relevant memories auto-inject for web channel the same way workbook filename triggers extraction for Excel.

When no portfolio context is provided in a web request, the unconditional `_build_context_section()` will still render the context dict (which contains `{channel: "web"}`). This is fine — it's small and gives the model channel awareness.

**2c. No new `ChannelType` needed**

The web app is a pure consumer (like Telegram) — it provides no tools of its own and doesn't register with the `ChannelRegistry`. The `channel_context` string in the request context (`"web"`) is sufficient for prompt adaptation and tool filtering. No enum change needed.

### Phase 3: Frontend Service Swap

**3a. Create `GatewayClaudeService`**

New service class (or parallel file alongside `ClaudeService.ts`). In Phase 3, it only needs streaming + approval methods (used by `usePortfolioChat`). Non-streaming methods (`useChat.ts`, `APIService.ts`) continue using the legacy `ClaudeService` until Phase 4 migration. The feature flag (3c) only affects `usePortfolioChat`'s service selection, not a global provider swap:

```typescript
class GatewayClaudeService {
    private proxyUrl: string;

    constructor({ url }: { url: string }) {
        this.proxyUrl = url;  // same-origin proxy, e.g. "/api/gateway"
    }

    async *sendMessageStream(
        message: string,
        history: ChatMessage[],
        portfolioName?: string,  // optional — display name from PortfolioMetadata.name (not Portfolio.id). usePortfolioChat must map from the portfolio metadata, not the holdings object.
    ): AsyncGenerator<ClaudeStreamChunk> {
        // Convert to gateway format
        const messages = [
            ...history.map(m => ({ role: m.role, content: m.content })),
            { role: "user", content: message },
        ];

        // Calls risk_module proxy (same-origin, session cookie auth)
        // Proxy handles gateway session init + API key — never exposed to browser
        // portfolio_name used for prompt context heading
        const resp = await fetch(`${this.proxyUrl}/chat`, {
            method: "POST",
            credentials: "include",  // send session cookie
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                messages,
                context: {
                    channel: "web",
                    ...(portfolioName ? { portfolio_name: portfolioName } : {}),
                },
            }),
        });

        // Handle non-200 responses (401 auth failure, 409 concurrent stream, 503 legacy path)
        if (!resp.ok) {
            const body = await resp.text();
            yield { type: "error", content: `Gateway error (${resp.status}): ${body}` };
            return;
        }

        // Parse gateway SSE → ClaudeStreamChunk (skip unhandled events)
        // parseSSE: async generator that reads ReadableStream<Uint8Array>, yields parsed {type, ...} objects.
        // Implement as a simple SSE line parser or use an existing SSE client library.
        for await (const event of parseSSE(resp.body)) {
            const mapped = this.mapEvent(event);
            if (mapped !== null) {
                yield mapped;
            }
        }
    }

    async respondToApproval(
        toolCallId: string,
        nonce: string,
        approved: boolean,
        allowToolType?: boolean,
    ): Promise<void> {
        const resp = await fetch(`${this.proxyUrl}/tool-approval`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tool_call_id: toolCallId,
                nonce,
                approved,
                ...(allowToolType !== undefined ? { allow_tool_type: allowToolType } : {}),
            }),
        });
        if (!resp.ok) {
            const body = await resp.text();
            throw new Error(`Approval failed (${resp.status}): ${body}`);
        }
    }

    private mapEvent(event: GatewayEvent): ClaudeStreamChunk | null {
        switch (event.type) {
            case "text_delta":
                return { type: "text_delta", content: event.text };
            case "tool_call_start":
                return { type: "tool_call_start", tool_name: event.tool_name };
            case "tool_call_complete":
                return {
                    type: "tool_result",
                    tool_call_id: event.tool_call_id,
                    tool_name: event.tool_name,
                    result: event.result,
                    error: event.error ?? null,
                };
            case "tool_approval_request":
                return {
                    type: "tool_approval_request",
                    tool_call_id: event.tool_call_id,
                    nonce: event.nonce,
                    tool_name: event.tool_name,
                    tool_input: event.tool_input,
                };
            case "stream_complete":
                return { type: "done" };
            case "error":
                return { type: "error", content: event.error };
            case "tool_execute_request":
                // This should never happen for web channel (Excel tools filtered out).
                // If it leaks through, treat as a hard error — don't silently wait for timeout.
                return { type: "error", content: `Unexpected Excel tool execution request: ${event.tool_name}` };
            // Silently skip events not relevant to the web frontend:
            // thinking_delta, heartbeat
            default:
                return null;
        }
    }
}
```

**Key insight**: `usePortfolioChat` and `ChatCore` need changes for tool approval handling (see 3d below), but the core streaming logic stays the same — they consume `ClaudeStreamChunk` objects. The service swap happens inside `usePortfolioChat` via the feature flag (see 3c).

**3b. Auth: backend proxy, NOT browser-direct**

The gateway authenticates via API key → session JWT. Exposing the API key in browser JavaScript is unsafe — anyone could mint sessions and call gated tools (including `run_bash`).

**Solution**: The web app frontend does NOT call the gateway directly. Instead, the risk_module backend acts as a **trusted proxy**:

```
Browser → risk_module backend (authenticated via session cookie) → gateway (authenticated via API key)
```

New endpoint on risk_module backend:
```
POST /api/gateway/chat
Headers: Cookie (existing session auth)
Body: {messages, context}
Response: SSE stream (Content-Type: text/event-stream, Cache-Control: no-cache, X-Accel-Buffering: no)
  - Proxy MUST disable response buffering (Starlette StreamingResponse) and forward each SSE event as it arrives from the gateway
  - Events are forwarded verbatim (no parsing/re-serialization) to preserve ordering and timing

POST /api/gateway/tool-approval
Headers: Cookie (existing session auth)
Body: {tool_call_id, nonce, approved, allow_tool_type?}
Response: 200 OK
```

This endpoint:
1. Validates the user's session cookie (existing auth_service)
2. Calls the gateway's `/api/chat/init` with the server-side API key (env var, never exposed to browser) and **caches the session token** for the user's session
3. Proxies the gateway's `/api/chat` SSE stream back to the browser
4. Proxies `/api/chat/tool-approval` for approval responses, **reusing the same session token** from step 2

**Channel enforcement**: The proxy MUST enforce `context.channel = "web"` server-side. Merge rule: `upstream_context = {**client_context, "channel": "web"}` — preserve all client-provided fields (`portfolio_name`, etc.) but override `channel`. This ensures the gateway always sees `channel: "web"`.

**Model stripping**: The proxy MUST strip any `model` field from the client payload before forwarding to the gateway. The web channel always uses the gateway's configured default model. If the client sends `{model: "..."}`, the proxy drops it — the gateway's own allowlist would reject unknown models, but stripping at the proxy prevents unnecessary round-trips and ensures the "no web model override" policy is enforced at the boundary.

**Session stickiness is critical**: The gateway ties tool approval nonces to the session that initiated the stream. If the proxy creates a new session token for the `/tool-approval` call, the gateway will reject the nonce.

**Token storage — multi-user ready**: Each authenticated user gets their own gateway session token. Storage options:
- **Phase 3 (development)**: In-memory `Dict[str, str]` keyed by user ID. Simple, works for single-worker.
- **Production / multi-worker**: Redis or similar shared store, keyed by user ID. Required when running multiple uvicorn workers behind a load balancer — without it, `/chat` and `/tool-approval` may hit different processes and lose token affinity.

The proxy creates a gateway session token on the user's first `/api/gateway/chat` call and reuses it for all subsequent calls. Tokens are NOT stored in Starlette's cookie-backed `request.session` (which would expose the gateway token to the browser). **Cleanup**: The in-memory token/lock dicts have no automatic eviction — they grow with the number of distinct authenticated users. For the current single-user deployment this is a non-issue. For multi-user: add a TTL-based sweep (e.g., evict entries unused for >24h) or tie eviction to session expiry events from the auth layer. Low priority follow-up.

**Token refresh policy**: Never rotate the gateway token during an active stream or while an approval is pending. If `/api/gateway/tool-approval` gets a 401 from the gateway, return an error to the frontend (not a retry with new token) — the nonce is bound to the old session and a new token would invalidate it. The user must send a new message to restart the stream. Token refresh only happens on the next `/api/gateway/chat` call when no stream is active.

**Concurrent streams**: The gateway allows only one active stream per gateway session token. Each user gets their own gateway session, so **different users can stream concurrently** without conflict. Within a single user, concurrent streams (e.g., multiple browser tabs) conflict. Enforcement: return 409 from proxy if that user already has an active stream. Frontend disables send button while streaming.

**Stream state machine**: The proxy maintains **per-user** stream state: `idle` → `streaming` → `idle`. State transitions:
- `idle → streaming`: on `/api/gateway/chat` request (acquire user's lock)
- `streaming → idle`: on `stream_complete` event, stream error, or client disconnect
- **Client disconnect cleanup**: The proxy SSE generator must use a `try/finally` block. On client disconnect (detected via `Request.is_disconnected()` or `asyncio.CancelledError`), the `finally` block must: (1) close/cancel the upstream `httpx` response (which tells the gateway the stream is done and clears its `stream_active` flag), and (2) release the user's lock. Without explicit upstream cancellation, the gateway's `stream_active` stays true and all subsequent requests from that user get 409.
- Lock implementation: `Dict[str, asyncio.Lock]` keyed by user ID. Lazily created on first request per user. **Lock scope**: The lock only guards `/api/gateway/chat` (prevents concurrent streams per user). `/api/gateway/tool-approval` does NOT acquire the lock — it must be callable while the stream lock is held (the stream is waiting for the approval response). Note: like the in-memory token dict, this is single-worker only. In multi-worker production, stream locking would need a shared store (Redis). For this migration, single-worker is sufficient — multi-worker is a follow-up concern alongside Redis token storage.

The `GatewayClaudeService` in the frontend calls this proxy endpoint (same-origin), not the gateway directly.

**3c. Feature flag for coexistence**

In `usePortfolioChat` (or the module that selects the streaming service), read the flag from the app's runtime config. `loadRuntimeConfig()` in `frontend/packages/chassis/src/utils/loadRuntimeConfig.ts` uses a **Zod schema** (`ConfigSchema`) with explicit fields. To add a new config field:

1. Add `chatBackend` to `ConfigSchema` in `loadRuntimeConfig.ts`:
   ```typescript
   chatBackend: z.enum(['legacy', 'gateway']).default('legacy'),
   ```
2. Add matching entry to `DEFAULT_CONFIG` (same file, ~line 29):
   ```typescript
   chatBackend: 'legacy',
   ```
3. Add the corresponding env var to `.env`: `VITE_CHAT_BACKEND=legacy` (or `gateway`)
4. Map in `loadRuntimeConfig()`: `chatBackend: import.meta.env.VITE_CHAT_BACKEND || 'legacy'`

Usage in `usePortfolioChat`:
```typescript
const config = loadRuntimeConfig();
const chatBackend = config.chatBackend;

// Only affects streaming portfolio chat — non-streaming call sites (useChat, APIService) stay on legacy until Phase 4
// Note: ClaudeService constructor takes injected request/requestStream functions (see SessionServicesProvider.tsx:219).
// GatewayClaudeService uses fetch directly with same-origin proxy URL.
const streamingService = chatBackend === "gateway"
    ? new GatewayClaudeService({ url: "/api/gateway" })
    : existingClaudeService;  // the ClaudeService already instantiated by SessionServicesProvider

// Service contract difference: legacy sendMessageStream(message, history, portfolioId: string)
// vs gateway sendMessageStream(message, history, portfolioName?: string).
// usePortfolioChat has access to both:
//   - currentPortfolio.id (from Portfolio type, used by legacy path)
//   - portfolio metadata name — must be wired in Phase 3
// The hook must resolve the display name from PortfolioMetadata.name (not Portfolio.id).
// usePortfolioChat does NOT currently have metadata access. Phase 3 must add it:
// either accept portfolio display name as a prop/param from the parent component,
// or add a metadata query inside the hook (e.g., via the existing portfolio API).
// In Phase 3 (coexistence), the hook passes the right value to whichever service is active:
//   legacy path: existingClaudeService.sendMessageStream(msg, history, currentPortfolio.id)
//   gateway path: gatewayService.sendMessageStream(msg, history, portfolioMetadata?.name)
// If metadata is not yet loaded, portfolioName is omitted (optional param).
```

Both paths coexist during migration. Flip the flag to test, flip back if issues.

**3d. Tool approval handling (required)**

The gateway emits `tool_approval_request` events for gated tools (file_write, file_edit, run_bash, update_model). If the frontend ignores these events, gated tool calls will **stall until the 120s approval timeout**, then fail.

**Five-part solution:**

1. **Most tools auto-execute**: MCP tools (portfolio-mcp, FMP, EDGAR, etc.) bypass the approval gate because `_needs_approval()` in `tool_dispatcher.py:123` only gates `ChannelType.EXCEL` and `ChannelType.LOCAL` channels — MCP tools fall through ungated. Memory tools and read-only local tools (file_read, file_glob, file_grep) are in `AUTO_APPROVE_TOOLS`. Only file_write, file_edit, run_bash (local gated), and update_model (Excel gated) require approval.

   **Note on `execute_trade`**: This MCP tool has real side effects (places orders) but currently bypasses the gateway approval gate — same as in Claude Code and TUI today. The portfolio-mcp server itself has its own confirmation flow (preview_trade → execute_trade requires explicit user intent in the prompt). Adding gateway-level approval for high-impact MCP tools is a follow-up concern, not in scope for this migration. Track in backlog if needed.

   **Note on local tools in web channel**: `run_bash`, `file_write`, `file_edit` are gated (require user approval) but still present in the web channel's tool list. This is the **same exposure as TUI and Telegram today** — the system is single-user. For multi-user web deployment, these tools must be filtered out for non-admin users (add to `_NON_EXCEL_CHANNELS` filtering or introduce role-based tool filtering). This is out of scope for this migration but tracked as a known limitation. See Open Questions #5 (local tool RBAC).

2. **Extend `ClaudeStreamChunk` type**: The current `ClaudeStreamChunk` type in `ClaudeService.ts` only handles `text_delta`, `tool_call_start`, `error`, etc. It does NOT have a `tool_approval_request` variant. Add it:
   ```typescript
   // In ClaudeService.ts (or shared types file)
   type ClaudeStreamChunk =
     | { type: "text_delta"; content: string }
     | { type: "tool_call_start"; tool_name: string }
     | { type: "tool_result"; ... }
     | { type: "tool_approval_request"; tool_call_id: string; nonce: string; tool_name: string; tool_input: object }  // NEW
     | { type: "done" }
     | { type: "error"; content: string };
   ```

3. **Add approval state to `usePortfolioChat`**: The current hook has no concept of pending approvals. `ChatContext` is a thin wrapper that calls `usePortfolioChat()` and provides its return value via React Context (see `ChatContext.tsx:209`). Therefore, new state belongs in the hook, not the context wrapper. Add to `usePortfolioChat`:
   ```typescript
   // New state in usePortfolioChat
   const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);

   const respondToApproval = async (approved: boolean, allowToolType?: boolean) => {
     if (!pendingApproval) return;
     await gatewayService.respondToApproval(pendingApproval.toolCallId, pendingApproval.nonce, approved, allowToolType);
     setPendingApproval(null);
   };

   // Expose in hook return value (ChatContext passes through automatically)
   return { ...existing, pendingApproval, respondToApproval };
   ```

   **Data flow**: `usePortfolioChat` owns `pendingApproval` state and `respondToApproval` action. `ChatContext` (which wraps `usePortfolioChat`) exposes them via context. The stream loop in `usePortfolioChat` calls `setPendingApproval` on `tool_approval_request` chunks. `ChatCore` reads `pendingApproval` from context and calls `respondToApproval` on user approve/deny.

   Update `ChatContextType` interface to include the new fields:
   ```typescript
   pendingApproval: PendingApproval | null;
   respondToApproval: (approved: boolean, allowToolType?: boolean) => Promise<void>;
   ```

4. **Update `usePortfolioChat` to handle approval events**: The current hook only processes `text_delta`, `tool_call_start`, and `error` in its stream loop. It needs a new branch that calls `setPendingApproval` (the hook's own setter, exposed to `ChatCore` via `ChatContext`):
   ```typescript
   case "tool_approval_request":
     setPendingApproval({
       toolCallId: chunk.tool_call_id,
       nonce: chunk.nonce,
       toolName: chunk.tool_name,
       toolInput: chunk.tool_input,
     });
     break;
   ```

5. **Add approval UI to `ChatCore.tsx`** (`frontend/packages/ui/src/components/chat/shared/ChatCore.tsx`): When `pendingApproval` is set, render a confirm/deny banner. On user decision, call `respondToApproval()` from context. Reference: Excel add-in's existing approval handler in `src/taskpane/taskpane.ts:634` and Telegram bot's inline keyboard pattern.

**Additionally**: The `mapEvent()` function returns `null` for unhandled gateway event types (`thinking_delta`, `heartbeat`), and the caller skips nulls. `tool_execute_request` is handled explicitly as a hard error (see `mapEvent` code above) — it should never occur for web channel, but if it leaks through, the user sees an error immediately rather than waiting for a timeout.

### Phase 4: Cutover and Cleanup

1. Flip `VITE_CHAT_BACKEND=gateway` as default (maps to `chatBackend` in runtime config)
2. Validate for a period (both paths still available)
3. **Migrate all Claude chat call sites** — not just `usePortfolioChat`:
   - `useChat.ts` — the generic chat hook also calls `ClaudeService`. Must be migrated to use `GatewayClaudeService` or unified with `usePortfolioChat`.
   - `APIService.ts` — has non-streaming Claude chat methods (`claudeChat`) plus non-chat utility methods (`extractPortfolioData`). Chat methods must be migrated; utility methods handled per step 4.
   - Audit all imports of `ClaudeService` and `useChat` across the frontend to ensure no call sites are missed.
4. **Non-chat `ClaudeService` consumers**: `PortfolioManager.ts` uses `ClaudeService.extractPortfolioData()` and `APIService.ts` delegates `claudeChat()` and `extractPortfolioData()`. These are NOT chat-streaming methods and are not affected by the gateway migration. Options: (a) keep `ClaudeService` as a non-streaming utility class (rename to `ClaudeUtilService`), or (b) migrate these methods to standalone API calls on the risk_module backend. Decision deferred to Phase 4 implementation — audit all `ClaudeService` imports to determine the cleanest cut.
5. **Dependency audit (before any removal)**: Two-layer check:
   - **Static**: `grep -r "ai_function_registry\|ClaudeFunctionExecutor\|function_executor" mcp_server.py mcp_tools/` to find direct imports.
   - **Runtime**: Start portfolio-mcp in isolation (`python mcp_server.py`) and call each tool via MCP protocol to verify no `ImportError` or missing dependency at runtime. This catches transitive imports that grep misses (e.g., a tool function importing a helper that imports `function_executor`).
   Only keep files that pass both checks. This audit must complete before step 6.
6. Remove (gated by audit in step 5):
   - `ClaudeService.ts` streaming methods (or the whole file if non-chat consumers are migrated per step 4)
   - `routes/claude.py` chat endpoints (`/api/claude_chat`, `/api/claude_chat_stream`)
   - `services/claude/chat_service.py` (~81KB)
   - Chat orchestration logic in `function_executor.py` (retain only what `portfolio-mcp` actually imports per step 5)
7. Keep (per audit):
   - `portfolio-mcp` server (`mcp_server.py`) — the MCP server that makes portfolio tools available to all channels
   - Any files that `mcp_server.py` or `mcp_tools/` actually import (may include `ai_function_registry.py`, `ClaudeFunctionExecutor`, or neither)

## Migration Strategy

**Both old and new paths coexist** through Phases 0–3 (Phase 4 removes the legacy path):

| Phase | risk_module backend | risk_module frontend | Gateway |
|-------|-------------|---------------------|---------|
| 0 | Audit portfolio-mcp parity + add any missing tools to `mcp_server.py` | No changes | Add `portfolio-mcp` to `ALLOWED_SERVERS` + verify `USE_AGENT_RUNNER=true` is active |
| 1 | No changes | No changes | Add per-channel tool filtering (gateway). Also: fix Telegram bot to send `channel: "telegram"` context (`telegram_bot/bot.py`) |
| 2 | No changes | No changes | Add `channel_context` to system prompt builder + `portfolio_name` rendering + entity extraction |
| 3 | Add gateway proxy endpoints (`/api/gateway/chat` + `/api/gateway/tool-approval`) | Add `GatewayClaudeService` + approval UI behind flag | Ready |
| 4 | Remove legacy chat endpoints + chat_service.py | Migrate all call sites + remove legacy `ClaudeService` | Upgrade `USE_AGENT_RUNNER=false` warning to `SystemExit` + production deployment |

Each phase can be deployed and validated independently. **Prerequisite**: `USE_AGENT_RUNNER=true` must be the active default in all environments before Phase 1. If any environment still runs with `USE_AGENT_RUNNER=false`, the request-time 503 guard (see Limitation note above) ensures channel-aware requests are safely rejected — but the feature set only works on the agent runner path.

**Note**: The risk_module backend gets two new thin proxy endpoints (`/chat` + `/tool-approval` under `/api/gateway/`, Phase 3) and keeps running portfolio-mcp. The proxy is just auth + SSE forwarding — no chat orchestration logic.

## Design Decisions

1. **Same agent, different frontend**: The web app Claude gets tools from the same infrastructure as TUI/Excel/Telegram — `TOOL_DEFINITIONS` + `mcp_clients.get_tool_definitions()`, filtered per-channel (Excel tools excluded for non-Excel channels). No custom tool proxy, no separate definitions, no sync concerns.

2. **Pure consumer channel**: The web app doesn't register with `ChannelRegistry` or provide tools. It's a consumer like Telegram. The `channel_context` string in the request is sufficient for prompt adaptation and tool filtering.

3. **Tool approval**: Gated tools (file_write, etc.) get a proper approval UI in the frontend. Most tools auto-execute.

4. **Excel tools**: NOT available from web app (same as Telegram). Enforced at two levels: (a) tool-list filtering in `get_active_tool_definitions()` removes Excel tools from the LLM's tool list, so Claude won't attempt to call them; (b) defense-in-depth: pass `channel_context` to `ToolDispatcher` and reject `ChannelType.EXCEL` tool execution for non-Excel channels at dispatch time. This prevents edge cases where a hallucinated or cached tool call bypasses list filtering.

5. **Portfolio context**: `portfolio_name` passed in the request context dict and rendered in the system prompt. Position data loaded on demand via `get_positions` tool call.

6. **Model version**: The gateway handler always passes `model_override=body.model` to `AgentRunner.run()`. For **web** requests, the proxy strips `model` from the payload (see Phase 3b "Model stripping"), so `body.model` is `None` and the gateway uses its configured default (`claude-sonnet-4-6`). Other channels (Telegram `/model` command) can still set `body.model` to switch models. No gateway-side change needed — the enforcement is at the proxy layer.

### Canonical API References

These are the correct names/patterns — all code snippets in this spec must match:
- **Runtime config**: `loadRuntimeConfig()` from `frontend/packages/chassis/src/utils/loadRuntimeConfig.ts` — NOT `getRuntimeConfig()`
- **ClaudeService constructor**: Takes injected `request`/`requestStream` functions (see `SessionServicesProvider.tsx:219`) — NOT `{ url }`
- **GatewayClaudeService constructor**: Takes `{ url }` — different from `ClaudeService`, by design
- **Feature flag**: `loadRuntimeConfig().chatBackend` (Zod schema field, not `CHAT_BACKEND`) — scoped to `usePortfolioChat` streaming only, not a global provider swap

## Open Questions

1. **Chat history management**: The gateway does NOT persist chat history server-side — each request includes full `messages` array from the frontend. The risk_module frontend currently manages history client-side via `usePortfolioChat`. This means the frontend continues to own history (same pattern). Verify the gateway handles full conversation histories correctly at scale.

2. **Model version**: risk_module is on `claude-3-5-sonnet-20241022`. Gateway defaults to `claude-sonnet-4-6`. **Decision**: The web channel uses the gateway default model — no `model` field in the request. The gateway default is newer and configurable. No per-request model override needed.

3. **User identity for portfolio-mcp**: `portfolio-mcp` currently resolves the user from `RISK_MODULE_USER_EMAIL` env var (single-user). For multi-user deployments, portfolio-mcp needs to accept user context per-request (e.g., via tool input parameter or MCP context header) so it can resolve the correct portfolio. This is a portfolio-mcp concern, not a gateway concern — the gateway already creates per-user sessions. **Scope for this migration**: The proxy and gateway are designed multi-user-ready (per-user tokens, per-user locks). Portfolio-mcp multi-user support is out of scope — it stays single-user via env var until a follow-up task addresses it. This means multi-user deployments work for chat/tools but all users see the same portfolio in portfolio-mcp. **Note**: Multi-user portfolio resolution is a separate follow-up task. No startup warning or guardrail is required for this migration — the limitation is documented here and in the Open Questions section.

4. **Multi-user gateway sessions** (related to #3): The gateway creates one session per `/api/chat/init` call. The proxy creates one gateway session per authenticated user. This means each user gets isolated chat state, tool approvals, and stream locks. The gateway itself is stateless across users — no changes needed for multi-user support at the gateway level. The proxy token storage and stream locks are the multi-user-sensitive components (see Phase 3b).

5. **Local tool RBAC for web channel**: `run_bash`, `file_write`, `file_edit` are currently gated by per-request user approval but still available to any authenticated web user. In the current single-user deployment this is fine (same exposure as TUI/Telegram). For multi-user deployments, these tools should be restricted to admin users — either filter them out of the tool list for non-admin `channel_context="web"` requests, or add role-based checks to the approval gate. Out of scope for this migration; separate follow-up.

## Files Summary

**Cross-repo note**: This spec spans two repos. Files under **Gateway** and **Telegram bot** live in this repo (`AI-excel-addin`). Files under **risk_module backend** and **risk_module frontend** live in the `risk_module` repo (`/Users/henrychien/Documents/Jupyter/risk_module`). Frontend paths like `frontend/packages/chassis/...` and `frontend/packages/ui/...` are relative to the risk_module repo root.

| Action | File | Description |
|--------|------|-------------|
| **Gateway** | | |
| Modify | `api/mcp_client.py` | Add `"portfolio-mcp"` to `ALLOWED_SERVERS` + timeout override |
| Modify | `api/tools.py` | Add `channel_context` to `get_active_tool_definitions()` + `build_system_prompt()`, make context section heading channel-aware |
| Modify | `api/agent/runner.py` | Add `channel_context` param to `run()`, pass to tool definitions and dispatcher |
| Modify | `api/agent/tool_dispatcher.py` | Add `channel_context` param, reject Excel tool dispatch for non-Excel channels |
| Modify | `api/main.py` | Pass `channel_context` from request context to runner + prompt builder. Phase 1: add `USE_AGENT_RUNNER=false` startup warning + 503 request guard. Phase 4: upgrade warning to `SystemExit`. |
| Create | `tests/test_web_channel.py` | Channel filtering + prompt tests |
| Create | `docs/design/portfolio-tool-parity.md` | Phase 0 audit artifact: side-by-side comparison of `ai_function_registry` tools vs `portfolio-mcp` tool names, confirming parity or documenting gaps |
| **Telegram bot** | | |
| Modify | `telegram_bot/bot.py` | Add `context={"channel": "telegram"}` to all 3 `stream_chat()` call sites |
| **risk_module backend** | | |
| Create | `routes/gateway_proxy.py` | Proxy endpoints. Route handlers define paths as `/chat` and `/tool-approval` (no `/api/gateway/` prefix in handler). Integration: `app.include_router(gateway_proxy_router, prefix="/api/gateway")` in `app.py` adds the prefix, yielding final paths `/api/gateway/chat` and `/api/gateway/tool-approval`. Uses existing `get_current_user` dependency for auth. Env vars: `GATEWAY_URL` (gateway base URL), `GATEWAY_API_KEY` (server-side API key). Gateway tokens stored in server-side in-memory dict (NOT cookie-backed session) keyed by authenticated user ID. |
| **risk_module frontend** | | |
| Create | `GatewayClaudeService.ts` | Gateway-protocol service class (~100 lines), calls `/api/gateway/*` (same-origin proxy) |
| Modify | `ClaudeService.ts` (types) | Add `tool_approval_request` to `ClaudeStreamChunk` union type |
| Modify | `ChatContext.tsx` | Update `ChatContextType` interface to expose `pendingApproval` + `respondToApproval` (state owned by `usePortfolioChat`, passed through context) |
| Modify | `usePortfolioChat.ts` | Add `pendingApproval` state + `respondToApproval` action + handle `tool_approval_request` chunk in stream loop |
| Modify | `ChatCore.tsx` | Add tool approval UI component (confirm/deny banner) |
| Modify | Service provider / runtime config | Feature flag for backend selection (`loadRuntimeConfig().chatBackend`). Requires adding `chatBackend` to Zod `ConfigSchema` in `loadRuntimeConfig.ts` + `VITE_CHAT_BACKEND` env var. |

## Tests

**Cross-repo test locations**:
- **Gateway tests** and **Telegram tests**: Run in this repo (`AI-excel-addin`). `pytest tests/test_web_channel.py tests/test_channel_plumbing.py tests/test_telegram_channel_context.py`.
- **Existing impacted suites** (regression — run alongside new tests): `tests/test_tool_dispatcher.py`, `tests/test_api_approval_gate.py`, `tests/test_telegram_bot.py`. These exercise code paths modified by Phase 1-2 (channel filtering, dispatcher changes).
- **Proxy tests**: Run in `risk_module` repo. `pytest tests/test_gateway_proxy.py`.
- **Frontend tests**: Run in `risk_module` repo. `npm test` (vitest) in `frontend/`.
- **Phases 1-2**: Only gateway + Telegram tests. **Phase 3+**: All test suites.

**Phase-scoped tests**: Tests #22 and #23 in the gateway test list are mutually exclusive — #22 tests the Phase 1-3 warning behavior, #23 tests the Phase 4 SystemExit behavior. In CI during Phases 1-3, #23 should be skipped (`@pytest.mark.skip` or gated on a phase marker). In Phase 4, #22 is removed and #23 is active.

### Gateway tests (`tests/test_web_channel.py`)

**Mocking strategy**: All tests monkeypatch `mcp_clients.get_tool_definitions()` to return synthetic tool definitions (no live MCP servers required). Channel registries use synthetic `Channel` objects with explicit `tool_names` sets. This matches the existing test pattern in `tests/test_channel_registry.py`.
1. `test_portfolio_mcp_in_allowed_servers` — `"portfolio-mcp"` is in `ALLOWED_SERVERS`
2. `test_portfolio_mcp_timeout_override` — portfolio-mcp has 120s timeout in `_SERVER_TIMEOUT_OVERRIDES`
3. `test_web_channel_excludes_excel_tools` — `get_active_tool_definitions(channel_context="web")` excludes Excel tool names even when Excel channel is registered
4. `test_non_web_channel_includes_excel_tools` — `get_active_tool_definitions(channel_context=None)` includes Excel tools when Excel channel is registered
5. `test_web_channel_includes_mcp_tools` — portfolio-mcp, FMP, EDGAR tools all present in web channel tool list
6. `test_web_channel_includes_local_tools` — memory and file tools present (gated ones still listed, just require approval)
7. `test_system_prompt_web_channel_no_excel_sections` — prompt omits column identification, update_model guide, and Excel tool usage sections when `channel_context="web"`, even if Excel is connected
8. `test_system_prompt_web_with_portfolio_context` — portfolio data serialized into prompt when provided
9. `test_system_prompt_non_web_no_portfolio_heading` — prompt omits "Current Portfolio Context" heading when `channel_context` is not `"web"` (e.g., `None` or `"telegram"`)
10. `test_system_prompt_excel_channel_keeps_excel_sections` — prompt includes all Excel sections when `channel_context=None` and Excel is connected
11. `test_runner_passes_channel_context_to_tool_defs` — `channel_context` flows from `run()` to `get_active_tool_definitions()`
12. `test_runner_passes_channel_context_to_dispatcher` — `channel_context` flows from `run()` to `ToolDispatcher.dispatch()` (mock dispatcher, verify `channel_context` kwarg)
13. `test_telegram_also_excludes_excel_tools` — `channel_context="telegram"` triggers same filtering
14. `test_telegram_prompt_no_excel_sections` — prompt omits Excel sections when `channel_context="telegram"`
15. `test_portfolio_mcp_no_tool_collisions` — mocked unit test: inject mock tool definitions for all MCP servers into `McpClientManager`, verify all expected portfolio-mcp tool names survive collision filtering against both (a) other MCP servers (FMP/EDGAR/model-engine) and (b) built-in tools in `TOOL_DEFINITIONS`. Does NOT require live MCP servers.
16. `test_use_agent_runner_is_default` — verify `USE_AGENT_RUNNER` defaults to `true` (Phase 0 go/no-go gate)
17. `test_dispatcher_rejects_excel_tool_for_web` — `ToolDispatcher.dispatch()` with `channel_context="web"` rejects Excel tool calls with error
18. `test_dispatcher_allows_excel_tool_for_default` — `ToolDispatcher.dispatch()` with `channel_context=None` allows Excel tool calls
19. `test_dispatcher_rejects_before_approval` — when `channel_context="web"` and tool is Excel-backed, dispatcher returns error without invoking approval callback (no `tool_approval_request` event emitted)
20. `test_legacy_path_rejects_channel_context` — `/api/chat` with `USE_AGENT_RUNNER=false` and `context.channel="web"` returns HTTP 503
21. `test_context_heading_telegram` — `_build_context_section()` with `channel_context="telegram"` uses "Current Session Context" heading
22. `test_use_agent_runner_false_warns` — monkeypatch `USE_AGENT_RUNNER=false` → startup emits deprecation warning. *Ships in Phase 1; replaced by #23 in Phase 4 cutover.*
23. `test_use_agent_runner_false_exits` — monkeypatch `USE_AGENT_RUNNER=false` → startup raises `SystemExit`. *Added in Phase 1 with `@pytest.mark.skip("Phase 4")`; unskipped in Phase 4 when code changes. Replaces #22.*
24. `test_legacy_path_rejects_telegram_channel` — `/api/chat` with `USE_AGENT_RUNNER=false` and `context.channel="telegram"` returns HTTP 503
25. `test_503_guard_no_stuck_stream_active` — trigger 503 guard, then send normal request on same session → succeeds (no 409 from stuck `stream_active`)
26. `test_channel_normalization_uppercase` — `context.channel="WEB"` normalizes to `"web"` and triggers Excel filtering
27. `test_channel_normalization_whitespace` — `context.channel=" Telegram "` normalizes to `"telegram"` and triggers filtering
28. `test_entity_extraction_from_portfolio_name` — `_extract_entities_from_context()` with `context.portfolio_name="MSCI Model"` extracts `{"MSCI"}`
29. `test_system_prompt_web_channel_identity_wording` — `_build_identity_section()` with `channel_context="web"` and Excel connected uses "not available from this channel" wording (not "not currently connected")
30. `test_system_prompt_web_channel_no_excel_wording` — `_build_no_excel_section()` with `channel_context="web"` and Excel connected uses "not available from this channel" wording
31. `test_context_heading_web` — `_build_context_section()` with `channel_context="web"` uses "Current Portfolio Context" heading
32. `test_context_heading_default` — `_build_context_section()` with `channel_context=None` uses workbook-based heading (existing behavior preserved)
33. `test_web_channel_no_portfolio_name` — `build_system_prompt()` with `channel_context="web"` and no `portfolio_name` in context → prompt still renders "Current Portfolio Context" heading with minimal channel info (no crash, no empty section)
34. `test_web_channel_uses_default_model` — POST `/api/chat` with `context.channel="web"` and no `body.model` → `AgentRunner.run()` called with `model_override=None` (gateway default used). Note: the gateway handler always passes `model_override=body.model` — for web, the proxy strips the `model` field so `body.model` is `None`. Telegram can still set `body.model` directly.

### Gateway proxy tests (`tests/test_gateway_proxy.py` — in risk_module)
1. `test_proxy_caches_gateway_session_token` — first `/api/gateway/chat` call stores session token in in-memory dict; second call reuses it (no second `/api/chat/init`)
2. `test_proxy_approval_uses_same_session_token` — `/api/gateway/tool-approval` uses the same session token as the preceding `/api/gateway/chat` call
3. `test_proxy_chat_refreshes_token_on_401` — when `/api/gateway/chat` gets 401 from gateway (no active stream), proxy re-initializes session token and retries
4. `test_proxy_approval_401_returns_error` — when `/api/gateway/tool-approval` gets 401 from gateway, proxy returns error to frontend (no token refresh — nonce is session-bound)
5. `test_proxy_rejects_unauthenticated_request` — request without valid session cookie returns 401
6. `test_proxy_forwards_allow_tool_type` — `allow_tool_type` field is forwarded to gateway's `/api/chat/tool-approval`
7. `test_proxy_sse_passthrough_ordering` — events from gateway are forwarded in order without reordering or dropping
8. `test_proxy_sse_termination` — stream ends cleanly when gateway sends `stream_complete`
9. `test_proxy_enforces_channel_web` — proxy overrides `context.channel` to `"web"` regardless of client input
10. `test_proxy_rejects_concurrent_stream` — second `/api/gateway/chat` while a stream is active returns 409
11. `test_proxy_disconnect_releases_lock` — client disconnect mid-stream releases proxy lock, next request succeeds
12. `test_proxy_disconnect_cancels_upstream` — client disconnect cancels the upstream gateway stream (mock httpx response, verify `.aclose()` called)
13. `test_proxy_disconnect_then_immediate_chat` — disconnect mid-stream → immediate new `/api/gateway/chat` → succeeds (no 409)
14. `test_proxy_preserves_client_context` — client sends `{channel: "x", portfolio_name: "main"}` → proxy forwards `{channel: "web", portfolio_name: "main"}` (channel overridden, other fields preserved)
15. `test_proxy_no_token_refresh_during_stream` — start stream, mock gateway stream disconnecting with an error event → proxy surfaces error to client and does NOT call `/api/chat/init` to refresh token (token refresh only happens on next idle `/chat` request)
16. `test_proxy_concurrent_streams_different_users` — two different authenticated users stream simultaneously → both succeed (no 409, each uses own gateway token)
17. `test_proxy_no_token_refresh_during_pending_approval` — stream is active with pending `tool_approval_request`, mock gateway 401 on approval call → proxy returns error, does NOT refresh token
18. `test_proxy_token_not_in_cookies` — after `/api/gateway/chat` call, verify gateway session token is NOT present in response `Set-Cookie` headers or Starlette session store
19. `test_proxy_approval_bypasses_stream_lock` — while a `/api/gateway/chat` stream is active (lock held), `/api/gateway/tool-approval` succeeds without deadlocking
20. `test_proxy_strips_model_field` — client sends `{model: "claude-opus-4-6", messages: [...]}` → proxy forwards without `model` field (gateway uses default)
21. `test_proxy_cross_user_approval_rejected` — User A starts a stream with a pending approval → User B sends `/api/gateway/tool-approval` with User A's `tool_call_id` and `nonce` → proxy rejects (User B's gateway token is different from User A's, so the nonce doesn't match)
22. `test_proxy_forwards_tool_approval_request_event` — gateway emits `tool_approval_request` SSE event → proxy forwards it verbatim to the client (mock gateway stream with approval event, verify client receives it with all fields intact)
23. `test_proxy_sse_response_headers` — `/api/gateway/chat` response has `Content-Type: text/event-stream`, `Cache-Control: no-cache`, and `X-Accel-Buffering: no`

### Frontend tests (in risk_module, vitest/RTL)
1. `test_mapEvent_text_delta` — `text_delta` gateway event maps to `{type: "text_delta", content: ...}`
2. `test_mapEvent_tool_approval_request` — `tool_approval_request` maps with all fields (tool_call_id, nonce, tool_name, tool_input)
3. `test_mapEvent_stream_complete` — `stream_complete` maps to `{type: "done"}`
4. `test_mapEvent_unknown_event_returns_null` — unknown event types (e.g., `thinking_delta`) return `null`
5. `test_pendingApproval_state_transitions` — `setPendingApproval` sets state, `respondToApproval(true)` clears it and calls proxy
6. `test_respondToApproval_posts_to_proxy` — `respondToApproval` POSTs to `/api/gateway/tool-approval` with correct body
7. `test_approval_banner_renders_on_pending` — `ChatCore` renders approval banner when `pendingApproval` is non-null
8. `test_approval_banner_hidden_when_no_pending` — no banner when `pendingApproval` is null
9. `test_respondToApproval_deny` — `respondToApproval(false)` posts `approved: false` and clears pending state
10. `test_approval_timeout_clears_pending` — if stream ends (`done` event) while `pendingApproval` is set, pending state is cleared and error shown
11. `test_new_approval_replaces_pending` — second `tool_approval_request` replaces the first (only one pending at a time)
12. `test_mapEvent_tool_execute_request_is_hard_error` — `tool_execute_request` gateway event maps to `{type: "error", content: "Unexpected Excel tool execution request: ..."}` (not null/ignored)
13. `test_feature_flag_gateway_service` — when `chatBackend="gateway"`, `usePortfolioChat` uses `GatewayClaudeService` for streaming
14. `test_feature_flag_legacy_service` — when `chatBackend="legacy"` (or unset), `usePortfolioChat` uses legacy `ClaudeService` for streaming
15. `test_send_button_disabled_during_stream` — send button is disabled while streaming is active, re-enabled on `done` or `error`
16. `test_sendMessageStream_non_200_yields_error` — when proxy returns 409 (or other non-200), `sendMessageStream` yields `{type: "error", content: "Gateway error (409): ..."}` and stops
17. `test_mapEvent_tool_call_complete` — `tool_call_complete` gateway event maps to `{type: "tool_result", ...}` with tool_name and result
18. `test_respondToApproval_failure_throws` — when proxy returns non-200 on approval POST, `respondToApproval` throws error and `pendingApproval` remains set (caller shows error)
19. `test_useChat_migrated_to_gateway` — *(Phase 4 — skip in Phases 1-3 via `describe.skip` or equivalent)* `useChat` hook uses `GatewayClaudeService` when `chatBackend="gateway"`
20. `test_no_legacy_ClaudeService_streaming_imports` — *(Phase 4 — skip in Phases 1-3)* no remaining imports of `ClaudeService.sendMessageStream` or `ClaudeService.sendMessage` across frontend chat code (grep/static check). Non-chat utility methods (`extractPortfolioData`) may still be imported if option (a) from Phase 4 step 4 is chosen.
21. `test_gateway_sends_portfolio_name_not_id` — when `chatBackend="gateway"`, `usePortfolioChat` passes `PortfolioMetadata.name` (not `Portfolio.id`) to `GatewayClaudeService.sendMessageStream`
22. `test_gateway_omits_portfolio_name_when_unavailable` — when portfolio metadata is not loaded, `sendMessageStream` is called with `portfolioName` as `undefined`
23. `test_parseSSE_split_chunks` — SSE data split across two ReadableStream chunks (e.g., `data: {"ty` then `pe":"text_delta",...}\n\n`) is reassembled correctly
24. `test_parseSSE_multiline_data` — multi-line `data:` frames are concatenated per SSE spec
25. `test_parseSSE_trailing_buffer_flush` — stream ends without final `\n\n` → buffered event is still yielded

### Telegram bot tests (`tests/test_telegram_channel_context.py`)
1. `test_message_handler_sends_channel_telegram` — mock `BackendClient.stream_chat()`, send a message → verify `context={"channel": "telegram"}` was passed
2. `test_summarize_sends_channel_telegram` — trigger compaction → verify `context={"channel": "telegram"}` was passed
3. `test_session_capture_sends_channel_telegram` — trigger session-end capture → verify `context={"channel": "telegram"}` was passed

### Integration tests (`tests/test_channel_plumbing.py`)
1. `test_chat_endpoint_web_channel_filters_tools` — POST `/api/chat` with `context.channel="web"` → tool list in LLM call excludes Excel tools (mock Anthropic client, inspect `tools` kwarg)
2. `test_chat_endpoint_web_channel_prompt_no_excel` — POST `/api/chat` with `context.channel="web"` → system prompt excludes Excel sections
3. `test_chat_endpoint_no_channel_includes_excel` — POST `/api/chat` with no `context.channel` → tool list includes Excel tools (when Excel connected)
4. `test_chat_endpoint_unknown_channel_defaults` — POST `/api/chat` with `context.channel="unknown"` → treated as default (includes Excel tools), not as non-Excel channel
5. `test_chat_endpoint_telegram_channel_filters_tools` — POST `/api/chat` with `context.channel="telegram"` → Excel tools excluded
6. `test_approval_flow_end_to_end` — POST `/api/chat` with `context.channel="web"` → mock LLM calls a gated tool → stream emits `tool_approval_request` → POST `/api/chat/tool-approval` with `approved=true` → stream continues with `tool_call_complete` → `stream_complete`

### Cleanup verification tests (in risk_module, Phase 4)
1. `test_portfolio_mcp_starts_after_cleanup` — after legacy files are removed, `import mcp_server` succeeds and all expected portfolio-mcp tools are registered

## E2E Verification

**Note**: Items 1-3 and 7-10 are covered by automated tests (see Tests section). Items 4-6 are **manual only** by design — they exercise real MCP servers + LLM tool routing, which cannot be meaningfully unit-tested. Items 1-2 also serve as automated smoke tests to catch configuration regressions (see gateway tests #1-2).

1. Start gateway with portfolio-mcp in `ALLOWED_SERVERS` → verify portfolio tools appear in `mcp_clients.get_tool_definitions()` output
2. Verify portfolio-mcp tools loaded: call `mcp_clients.get_tool_definitions()` (or inspect startup logs) → confirm portfolio-mcp tool names are present (status endpoint reports channel-level counts only, not per-MCP-server breakdown)
3. Frontend with `chatBackend=gateway` → chat sends to gateway → response streams back correctly
4. _(Manual)_ Ask "what positions do I have?" → gateway routes to portfolio-mcp `get_positions` tool → result rendered in chat
5. _(Manual)_ Ask "catch me up on MSCI earnings" → gateway uses FMP + EDGAR tools → works seamlessly
6. _(Manual)_ Ask "what's in my memory about MSCI?" → `memory_recall` tool works → analyst memory available
7. Verify Excel tools do NOT appear in the tool list for `channel_context="web"` requests
8. Verify Telegram bot sends `channel: "telegram"` in context → Excel tools excluded
9. Verify system prompt for web channel does NOT include column identification or update_model sections
10. Trigger a gated tool (e.g., `file_write`) → approval UI appears in chat → approve → tool executes

## Reference

- Telegram channel task spec: `docs/design/telegram-channel-task.md` — closest reference (also a pure consumer channel)
- Telegram bot `backend_client.py` — reference for how a client talks to the gateway (session init, SSE parsing)
- Gateway architecture: `docs/design/multi-channel-gateway-task.md`
- Channel registry: `packages/excel-mcp/python/excel_mcp/relay.py` (lines 237-288)
- portfolio-mcp: `risk_module/mcp_server.py` (in the risk_module repo)
