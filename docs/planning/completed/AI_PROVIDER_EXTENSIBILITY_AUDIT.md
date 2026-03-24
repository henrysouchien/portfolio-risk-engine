# AI/Agent Provider Extensibility Audit

> **Date**: 2026-03-21
> **Status**: AUDIT COMPLETE
> **Overall grade**: **B+** — Gateway proxy pattern isolates AI provider from both frontend and backend. Switching providers is a gateway-side change, not a risk_module change.
> **TODO ref**: `docs/TODO.md` lines 84-102 ("AI/Agent Provider Extensibility")

---

## Executive Summary

The risk_module codebase is **well-decoupled from specific AI providers**. The gateway proxy pattern (`app_platform/gateway/`) acts as a clean abstraction layer — the backend sends `{messages, context}` upstream and streams SSE events back. No Anthropic or OpenAI API formats, model IDs, thinking blocks, or provider-specific streaming protocols exist in production code.

The provider coupling breaks into two separate concerns:

**Chat/streaming (well-decoupled):**
1. Gateway proxy is fully provider-agnostic — env-driven URL + API key
2. Frontend SSE client parses generic gateway events, not Anthropic-specific format
3. Naming conventions ("Claude" in class/type names) are cosmetic only

**Non-chat AI tasks (tightly coupled to OpenAI):**
1. `utils/gpt_helpers.py` makes direct `openai.OpenAI()` calls with hardcoded model IDs
2. Three actively-used functions: risk interpretation, peer generation, asset classification
3. Called from 4 production sites (REST API, CLI, proxy builder, security type service)

**Bottom line**: Switching the chat provider is a gateway config change (zero risk_module changes). But the 3 non-chat AI functions are hardwired to OpenAI and need abstraction work to become provider-swappable.

---

## Audit Questions & Answers

### Q1: Every AI provider touchpoint in risk_module?

**6 gateway touchpoints (provider-agnostic) + 1 OpenAI module (actively used).**

| File | Role | Provider-specific? |
|------|------|--------------------|
| `app_platform/gateway/proxy.py` | Gateway proxy factory — routes chat to upstream, streams SSE back | **No** — provider-agnostic pass-through |
| `app_platform/gateway/session.py` | Per-user session token management | **No** — generic token cache |
| `app_platform/gateway/models.py` | Request/response Pydantic models | **No** — `model` field exists but is stripped before forwarding |
| `routes/gateway_proxy.py` | Thin shim wiring gateway router to FastAPI | **No** — env-driven config only |
| `frontend/.../GatewayClaudeService.ts` | Frontend SSE client + event mapper | **No** — generic SSE parser, gateway-defined event types |
| `frontend/.../ClaudeStreamTypes.ts` | TypeScript union type for stream chunks | **No** — type definitions only |
| `utils/gpt_helpers.py` | **ACTIVE** — direct OpenAI SDK calls for non-chat AI tasks | **YES** — hardcoded `gpt-4.1`, `gpt-4o-mini` model IDs |

Callers of `gpt_helpers.py` (production):
- `app.py:2049` — `interpret_portfolio_risk()` in the `/api/analyze` REST endpoint
- `core/interpretation.py:66` — `interpret_portfolio_risk()` in CLI analysis path
- `core/proxy_builder.py:845` — `generate_subindustry_peers()` for peer discovery
- `services/security_type_service.py:1291` — `generate_asset_class_classification()` for unknown tickers
- `core/risk_orchestration.py:49` — imports (used transitively)

### Q2: How much is Anthropic-specific vs provider-agnostic?

**Two distinct layers with different answers.**

**Chat/streaming layer — zero Anthropic-specific code:**
- Gateway proxy sends generic `{messages: [...], context: {...}}` upstream (line 94-97 of `proxy.py`)
- No `anthropic` import anywhere in the codebase (only in `.env` for API key)
- No `/v1/messages` endpoint references (Anthropic API format)
- No thinking blocks, tool_use schema, or Claude-specific content block handling
- SSE events (`text_delta`, `tool_call_start`, `tool_approval_request`, `done`) are gateway-defined, not Anthropic-defined
- `GatewayChatRequest.model` field exists but is **never forwarded** to the gateway — model selection is server-side
- The `claude-gateway` package (separate repo) is where provider-specific code lives. It has a `ModelProvider` protocol with Anthropic + OpenAI implementations. Risk_module only talks to the gateway's provider-agnostic API.

**Non-chat AI layer — fully OpenAI-specific:**
- `utils/gpt_helpers.py` imports `openai` and creates `openai.OpenAI(api_key=...)` client
- Hardcoded model IDs: `gpt-4.1` (interpretation + peers), `gpt-4o-mini` (asset classification)
- Uses `client.chat.completions.create()` (OpenAI chat API format)
- System prompts embedded in function bodies (e.g., "You are a portfolio risk analysis expert")
- Gated by `USE_GPT_SUBINDUSTRY` env var for peers/classification, but interpretation has no gate
- **4 production callers** across `app.py`, `core/interpretation.py`, `core/proxy_builder.py`, `services/security_type_service.py`

### Q3: Can we leverage claude-gateway's ModelProvider protocol?

**We already do, implicitly.** The gateway handles model routing; risk_module doesn't need its own abstraction.

Architecture:
```
Frontend (GatewayClaudeService)
    → POST /api/gateway/chat {messages, context}
    → risk_module gateway proxy (pass-through)
    → claude-gateway (ModelProvider protocol selects Anthropic/OpenAI/etc.)
    → SSE stream back through the chain
```

Risk_module has no reason to import or reimplement `ModelProvider`. The gateway is the abstraction boundary.

### Q4: Frontend hardcoded to Anthropic's SSE format?

**No.** `GatewayClaudeService.ts` implements a generic SSE parser:

1. `parseSSE()` — reads `data:` lines from any SSE byte stream (standard protocol)
2. `parseSSEEvent()` — JSON-parses each event, falls back to `text_delta` for raw text
3. `mapEvent()` — maps gateway event types to `ClaudeStreamChunk` union

The event types (`text_delta`, `tool_call_start`, `tool_call_complete`, `tool_approval_request`, `code_execution_start`, `code_execution_result`, `error`, `stream_complete`) are **gateway-defined**, not Anthropic-defined. Any backend that emits these event shapes works.

### Q5: What changes for a user wanting OpenAI/Gemini/local model?

**Two scopes: chat (easy) and non-chat AI tasks (moderate).**

**Chat provider swap (gateway-side only):**

| Step | Where | What |
|------|-------|------|
| 1. Add model provider | `claude-gateway` | Implement `ModelProvider` protocol for new provider |
| 2. Configure model routing | `claude-gateway` config | Point to new provider, set model ID |
| 3. (Optional) Update env | risk_module `.env` | If gateway URL changes |

Frontend, MCP tools, agent registry continue working unchanged.

**Non-chat AI task provider swap (risk_module changes needed):**

| Step | Where | What |
|------|-------|------|
| 1. Abstract `gpt_helpers.py` | `utils/gpt_helpers.py` | Replace direct `openai.OpenAI()` with config-driven provider (or route through gateway) |
| 2. Externalize model IDs | `.env` or config | Move `gpt-4.1`/`gpt-4o-mini` to env vars |
| 3. (Optional) Route through gateway | `app_platform/gateway/` | Use gateway for all LLM calls, not just chat |

Effort: ~1-2 days. The functions are simple prompt→completion calls — the abstraction is straightforward.

### Q6: Are MCP tool descriptions / system prompts Claude-optimized?

**No.** All 75+ MCP tool descriptions are purely functional:
- Input parameters with types and descriptions
- Output format documentation
- Usage examples
- No Claude-specific language, no model-capability references
- No "thinking" or "chain-of-thought" instructions

The only Claude reference is the server instructions metadata:
```python
mcp = FastMCP(
    "portfolio-mcp",
    instructions="Portfolio analysis and position management tools for Claude Code",
)
```
This is cosmetic — it's MCP server metadata, not a system prompt sent to the model.

---

## Provider Coupling Map

### Production code — CLEAN (no provider coupling)

| Component | Files | Coupling | Notes |
|-----------|-------|----------|-------|
| Gateway proxy | `app_platform/gateway/*.py` (3 files) | **NONE** | Pure HTTP proxy + SSE pass-through |
| Gateway shim | `routes/gateway_proxy.py` | **NONE** | Env-driven config wiring |
| Frontend SSE | `GatewayClaudeService.ts`, `ClaudeStreamTypes.ts` | **NONE** | Generic SSE parser, gateway event types |
| MCP tools | `mcp_server.py`, `mcp_tools/*.py` (75+ tools) | **NONE** | Model-agnostic protocol |
| Agent registry | `services/agent_registry.py` (33 functions) | **NONE** | Pure function dispatch, no AI awareness |
| Result objects | `core/result_objects/*.py` | **NONE** | Docstrings reference "Claude/AI" but no runtime coupling |

### OpenAI direct usage — ACTIVE (production, non-chat)

`utils/gpt_helpers.py` contains 3 functions with direct `openai.OpenAI()` calls (hardcoded `gpt-4.1` / `gpt-4o-mini` model IDs). These are **actively called** in production for non-chat AI tasks:

| Function | Model | Callers | Purpose |
|----------|-------|---------|---------|
| `interpret_portfolio_risk()` | `gpt-4.1` | `app.py:2049` (REST API), `core/interpretation.py:66` (CLI) | Summarize portfolio risk analysis in natural language |
| `generate_subindustry_peers()` | `gpt-4.1` | `core/proxy_builder.py:845` | Generate peer companies for a ticker using GPT |
| `generate_asset_class_classification()` | `gpt-4o-mini` | `services/security_type_service.py:1291` | Classify unknown tickers into asset classes |

**Gating**: `utils/config.py:gpt_enabled()` controls `generate_subindustry_peers` and `generate_asset_class_classification` (env var `USE_GPT_SUBINDUSTRY`, default True in dev, False in prod). `interpret_portfolio_risk` has no gate — it's called unconditionally from the risk analysis API endpoint.

**Coupling**: HIGH — hardcoded OpenAI SDK, model IDs, and `chat.completions.create()` API format. No abstraction layer. Swapping to a different LLM for these functions requires rewriting all 3.

**Mitigation path**: These functions are simple prompt→completion calls. They could trivially be routed through the gateway (which already has `ModelProvider` for Anthropic + OpenAI), or wrapped with a thin LLM abstraction (provider + model from config).

### Dead code — SAFE TO DELETE

| Component | File | Coupling | Notes |
|-----------|------|----------|-------|
| Legacy ClaudeService | `frontend/.../ClaudeService.ts` | **DEAD** | Non-functional stubs, superseded by GatewayClaudeService |
| Legacy claude module | `services/claude/__init__.py` | **DEAD** | Empty file, comment says "removed during gateway cutover" |

### Naming cruft — COSMETIC (no runtime impact)

| Location | Reference | Impact |
|----------|-----------|--------|
| `GatewayClaudeService` class name | "Claude" in name | None — could be `GatewayAIService` |
| `ClaudeStreamChunk` type name | "Claude" in name | None — could be `AIStreamChunk` |
| `ClaudeService.ts` (legacy) | Entire file | Dead code |
| `container-claude` CSS class | "Claude" in class | Styling only |
| ~30 docstring references | "Claude/AI" in result_objects | Documentation only |
| MCP server instructions | "for Claude Code" | Metadata only |

---

## Decoupling Backlog

### Tier 1 — Functional (enables provider switching for non-chat AI tasks)

| # | Item | Effort | Priority |
|---|------|--------|----------|
| 1 | Abstract `gpt_helpers.py` — config-driven provider + model | 1 day | Medium |
| 2 | Externalize model IDs (`gpt-4.1`, `gpt-4o-mini`) to env vars | 30min | Medium |
| 3 | Add `COMPLETION_PROVIDER` env var (openai/anthropic/gateway) | 30min | Medium |
| 4 | (Optional) Route non-chat completions through gateway | 1 day | Low |

### Tier 2 — Cosmetic (naming cleanup, no functional impact)

| # | Item | Effort | Priority |
|---|------|--------|----------|
| 5 | Rename `ClaudeStreamChunk` → `AIStreamChunk` | 30min | Low |
| 6 | Rename `GatewayClaudeService` → `GatewayAIService` | 30min | Low |
| 7 | Update MCP instructions from "Claude Code" to "AI assistants" | 1min | Low |
| 8 | Delete `services/claude/__init__.py` (empty) | 1min | Low |
| 9 | Delete `frontend/.../ClaudeService.ts` (dead code) | 5min | Low |
| 10 | Update docstring references from "Claude/AI" to "AI" | 30min | Very low |

**Recommendation**: Tier 1 items are worth doing if multi-provider support is on the roadmap — they're small and unlock provider flexibility for all AI tasks, not just chat. Tier 2 is pure cosmetic — skip unless rebranding.

---

## Comparison with Data Provider Audit

| Dimension | Data providers (C-) | AI providers (B+) |
|-----------|---------------------|---------------------|
| Protocol/abstraction layer | Excellent (6 Protocols) | Excellent (gateway proxy for chat) |
| Actual usage of abstraction | Poor (~60% bypass) | Chat: ~100% through gateway. Non-chat: 0% (direct OpenAI) |
| Config-driven switching | No mechanism | Chat: Yes (env vars). Non-chat: No (hardcoded) |
| Frontend coupling | None | None |
| Direct provider calls | 18 files with inline FMPClient() | 1 file (gpt_helpers.py, 3 functions, 4 callers) |
| Effort to add new provider | ~2 days price chain, ~4 weeks full | Chat: zero (gateway). Non-chat: ~1-2 days |

The chat architecture learned from the data provider mistakes — the gateway abstraction is honored everywhere. The non-chat AI tasks (`gpt_helpers.py`) are a smaller-scale version of the same problem the data provider audit found: direct SDK calls bypassing the abstraction layer.
