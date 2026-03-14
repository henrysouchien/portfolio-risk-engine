# Claude API — Untapped Features & Infrastructure Gaps

**Status:** DESIGN | **Date:** 2026-03-14
**Related:** `FINANCIAL_ADVISOR_AGENT_ARCHITECTURE.md`, `COMPOSABLE_APP_FRAMEWORK_PLAN.md`, `PRODUCT_TIERS.md`

## Context

### What We Already Have

The `claude_gateway` package (in `AI-excel-addin/packages/claude-gateway/`) is a **production agent runtime** that already covers core Claude API integration:

| Capability | Implementation | Status |
|---|---|---|
| Agentic loop + streaming | `AgentRunner` (1,200 lines) — multi-turn, retries, stall watchdog | Done |
| Sub-agent spawning | `spawn_sub_agent()` with independent event logs, cancellation propagation | Done |
| Extended thinking | `_thinking_param()` — adaptive for 4.6, budget-based for older models | Done |
| Prompt caching | System prompt + last tool get `cache_control: {"type": "ephemeral"}` | Done |
| Tool approval gates | `ApprovalRequest`/`ApprovalDecision` with nonce-based coordination | Done |
| MCP server management | `McpClientManager` — reads ~/.claude.json, stdio lifecycle, collision filtering | Done |
| Channel-tier config | `CHANNEL_TIERS` + `AgentProfile` (max_turns, timeout, model, tool_packs) | Done |
| Context accounting | Token estimation (system, messages, tools), 80% context warnings | Done |
| SSE event stream | `EventLog` with sequence numbers, `iter_from()` for resumable tailing | Done |
| Session/auth | JWT + `SessionStore` (in-memory), OAuth + API key modes | Done |
| Tool timing/tracking | Per-tool duration + bytes, `on_tool_timing` callback | Done |
| Memory tools | `memory_recall`, `memory_store`, `memory_write`, `memory_read`, `memory_delete` defined | Done (tools defined, handlers app-specific) |
| Local file tools | `file_read`, `file_write`, `file_edit`, `file_glob`, `file_grep`, `run_bash` | Done |
| Chat transcripts | JSONL logging in `api/chat_logs/`, `read_chat.py` viewer | Done (AI-excel-addin only) |

The `app_platform` package (in `risk_module/app_platform/`) handles web infra:

| Capability | Implementation | Status |
|---|---|---|
| Multi-tenant auth | Protocol-based `SessionStore`/`UserStore`/`TokenVerifier`, Postgres + in-memory | Done |
| Gateway proxy | `create_gateway_router()`, SSE passthrough, per-user stream locks | Done |
| DB pool/sessions | Connection management, migrations | Done |

**Bottom line:** The agent loop, tool orchestration, streaming, thinking, caching, and approval flow are all implemented. This doc focuses on **Claude API features that sit on top of the existing runtime** — capabilities the API provides that we haven't wired into `claude_gateway` or our apps yet.

---

## Part 1: New API Features (genuinely additive)

### 1.1 Batch API — Bulk Analysis at 50% Cost

**What it is:** Async batch endpoint (`POST /v1/messages/batches`) processes up to 100K requests at half price. Results within 1 hour.

**Why we don't have this:** `AgentRunner` is real-time/streaming only. There's no batch path.

**Use cases:**
- **Nightly portfolio report generation** — batch `analyze_stock` across all holdings
- **Earnings season screening** — batch transcript analysis for 50+ companies
- **Multi-scenario comparison** — submit 20 what-if scenarios, collect ranked results
- **Watchlist model updates** — batch EDGAR extraction for a universe of tickers

**What to build:**
- Batch job runner that converts MCP tool prompts → `BatchRequest` format
- Result storage (filesystem or DB, keyed by `batch_id`)
- Poll-and-notify pattern (scheduler-mcp polls, notify sends results)
- Could be an MCP tool itself: `submit_batch()`, `get_batch_results()`

**Effort:** 1-2 weeks. The prompts and tool definitions exist; wrapping them in batch format is mechanical.

**Constraint:** Not real-time. Complements `AgentRunner`, doesn't replace it.

---

### 1.2 Code Execution Tool — Anthropic-Hosted Python Sandbox

**What it is:** Claude runs Python in an Anthropic-hosted sandbox. Pre-installed: pandas, numpy, matplotlib, scipy, scikit-learn, openpyxl, python-docx. No compute on our infra.

**Why we don't have this:** Our tools execute on our backend. Code execution is a server-side tool — Claude calls it autonomously, Anthropic runs the code.

**Use cases:**
- **Ad-hoc visualizations** — "Plot my sector allocation" → actual PNG, not text description
- **Custom quantitative analysis** — user describes a computation, Claude writes and runs it
- **Data transformation** — "Convert this CSV to the format portfolio-mcp expects"
- **Report generation** — formatted DOCX/PDF output via python-docx/matplotlib
- **Exploratory backtesting** — quick Monte Carlo without our engine (complement, not replacement)

**What to build:**
- Add `{"type": "code_execution_20260120", "name": "code_execution"}` to `AgentRunner`'s tool set
- Wire file download in frontends (web chat: inline images + download links; Excel: write back via `write_cells`; Telegram: send as photo)
- Container reuse across turns (API returns `container_id`)

**Effort:** Low for basic (add tool definition, hours). Medium to wire file download in all surfaces (1 week).

**Synergy:** Claude can pull data via portfolio-mcp, then analyze/visualize in the sandbox. Keeps custom computation off our backend.

---

### 1.3 Structured Outputs — Schema-Enforced JSON

**What it is:** `output_config.format` constrains Claude's response to match a JSON schema. The API **guarantees** the output is valid JSON matching the schema.

**Why we don't have this:** Agent format responses (`{status, snapshot, flags}`) are convention-enforced via system prompts. Claude usually complies, but malformed responses are possible.

**Use cases:**
- **Agent format responses** — guarantee `{status, format, snapshot, flags}` shape
- **Trade proposals** — structured `{action, symbol, quantity, price, rationale}` for approval UI
- **Plan review artifacts** — machine-readable review snapshots (advisor workflow)
- **UI block protocol** — `:::ui-blocks` definitions with strict block schemas

**What to build:**
- Define JSON schemas for key response types
- Wire `output_config` into `AgentRunner._call_api()` (conditional — only when structured output is needed, not for free-form chat)
- Frontend can trust schema compliance, simplify parsing

**Effort:** Low — incremental adoption per response type.

**Caveat:** Incompatible with citations. `stop_reason: "refusal"` may not match schema. First request per schema incurs compilation latency. Best for tool-like responses, not conversational text.

---

### 1.4 Server-Side Web Search & Fetch

**What it is:** Claude searches the web and fetches pages server-side. Dynamic filtering on Opus 4.6/Sonnet 4.6 — Claude writes code to filter search results before they enter context.

**Why we don't have this:** We use FMP and EDGAR MCP tools for financial data. These are structured APIs — great for financials, but no general web search.

**Use cases:**
- **Real-time news** — "What's the latest on NVDA earnings?" without FMP news tool
- **SEC filing discovery** — search for filings not yet in EDGAR structured data
- **Analyst commentary** — fetch and summarize sell-side research or articles
- **Competitor analysis** — web research to complement FMP fundamentals

**What to build:**
- Add tool definitions: `{"type": "web_search_20260209", "name": "web_search"}` + `{"type": "web_fetch_20260209", "name": "web_fetch"}`
- Channel-tier decision: maybe web search in `web`/`telegram` tiers but not in `excel` (model updates don't need web search)

**Effort:** Very low — add 2 tool definitions, possibly update `CHANNEL_TIERS`.

**Complements FMP/EDGAR:** Web search fills gaps structured APIs miss (breaking news, commentary, niche sources). FMP/EDGAR remain authoritative for financial data.

---

### 1.5 Compaction — Long Conversation Support

**What it is:** Server-side context summarization when conversations approach 200K tokens. Beta, Opus 4.6 / Sonnet 4.6.

**Why we don't have this:** `AgentRunner` warns at 80% context and caps `max_turns`. Long sessions eventually hit the wall. Compaction would let them continue by summarizing earlier context server-side.

**Use cases:**
- **Advisor review workflow** — 7-step review cycle with many MCP tool calls
- **Model building sessions** — iterative Excel model construction with many read/write cycles
- **Extended analysis** — multi-hour portfolio deep dives

**What to build:**
- Pass `betas=["compact-2026-01-12"]` and `context_management={"edits": [{"type": "compact_20260112"}]}` in `AgentRunner._call_api()`
- **Critical:** `AgentRunner` must append `response.content` (full list, not just text) to message history. Compaction blocks in `response.content` must be preserved — the API uses them on the next request.
- Audit `AgentRunner`'s message handling to confirm this is the case

**Effort:** Low — beta header + message handling audit.

**Risk:** Compaction may lose details from early turns. Test with long advisor sessions.

---

### 1.6 Files API — Persistent Document References

**What it is:** Upload files once, reference by `file_id` across multiple API calls. Files persist until deleted.

**Why we don't have this:** Excel add-in re-reads model content each turn. Web chat has no file upload path to the API (files go through MCP tools, not the Messages API).

**Use cases:**
- **Financial model sessions** — upload Excel model once, ask multiple questions
- **10-K review** — upload filing, ask follow-up questions without re-uploading
- **Portfolio CSV** — upload once, use across import + analysis + comparison

**What to build:**
- File upload endpoint in gateway (proxy to Anthropic Files API)
- `file_id` storage per session
- `container_upload` content block support in `AgentRunner`
- Cleanup policy (delete after session? after TTL?)

**Effort:** Medium — upload plumbing in backend + frontend (1-2 weeks).

**Constraint:** 500 MB/file, 100 GB/org. Beta (`files-api-2025-04-14` header). File ops are free; content billed as input tokens.

---

### 1.7 Programmatic Tool Calling

**What it is:** Claude writes code that calls your tools directly, keeping intermediate results out of context. Reduces token usage for multi-step workflows.

**Why we don't have this:** Every MCP tool result currently goes into the conversation context. For "compare 5 rebalancing strategies," that's 5 full tool results consuming context.

**Use cases:**
- "Compare portfolio against 3 rebalancing strategies" — Claude writes code calling `run_optimization` 3x, compares in code, surfaces summary only
- "Screen all tech holdings for exit signals" — loop in code, only surface flagged positions
- "Build a tear sheet for top 5 positions" — code loops `analyze_stock`, assembles report

**What to build:**
- Enable via server-side tool definitions (similar to code execution)
- Ensure MCP tools are accessible from the code execution environment

**Effort:** Low — configuration. But need to verify MCP tool accessibility from sandbox.

---

## Part 2: Runtime Extensions

These aren't new API features — they're extensions to `claude_gateway` and `app_platform` to fill operational gaps.

### 2.1 Cross-Session Memory for Web/Telegram

**Current state:** Memory tools are defined in `claude_gateway` (`memory_recall`, `memory_store`, etc.) with app-specific handlers. Claude Code sessions use filesystem auto-memory (MEMORY.md). The analyst workspace uses markdown files.

**Gap:** Web chat and Telegram sessions are ephemeral — no memory between sessions. The API provides a `memory` tool type (`memory_20250818`) with a structured SDK helper (`BetaAbstractMemoryTool`).

**What to build:**
- Implement `BetaAbstractMemoryTool` subclass backed by per-user filesystem or DB storage
- Wire into `AgentRunner` tool set for web/Telegram channels
- Or: continue using the existing `memory_*` local tools with persistent per-user directories

**Effort:** 1-2 weeks. Decision: use API-level memory tool vs extend existing local memory tools with persistence.

---

### 2.2 Cost Tracking & Budget Enforcement

**Current state:** `AgentRunner` tracks `usage.input_tokens` and `usage.output_tokens` per turn via `on_usage` callback. AI-excel-addin logs token counts in JSONL transcripts. But there's no aggregation, no budget enforcement, and no visibility dashboard.

**What to build:**
- Accumulate usage per session → per user → per day (in `AgentRunner.on_usage` callback)
- Store aggregates (filesystem or DB)
- Budget enforcement: abort session if cumulative cost exceeds threshold
- Alert via notify when daily spend exceeds limit
- Surface in admin/settings UI

**Effort:** 1 week. The per-turn data is already available — need aggregation + enforcement + UI.

---

### 2.3 Transcript Logging in risk_module

**Current state:** AI-excel-addin has JSONL chat transcripts (`api/chat_logs/`, `read_chat.py`). Risk module's gateway proxy has no transcript storage.

**What to build:**
- Add JSONL logging to risk_module's gateway proxy (same format as AI-excel-addin)
- Or: extract transcript logging into `claude_gateway` as a built-in EventLog listener
- Index by user + session + timestamp

**Effort:** < 1 week. The JSONL format and reader already exist.

---

## Part 3: Infrastructure Gaps

### 3.1 claude_gateway as a Shared Dependency

**Problem:** `claude_gateway` lives in AI-excel-addin but risk_module needs agent loop capabilities for batch jobs, scheduled workflows, and Tier 1 local MCP mode.

**Current state:** Risk module delegates to an external gateway service. If it ever needs direct API access (batch jobs, scheduled agents, Tier 1 MCP-only mode), it would need the agent loop.

**Options:**
1. **Import `claude_gateway` as a pip dependency** — it's already packaged (`ai-agent-gateway` on PyPI or local). Risk module adds it to requirements.
2. **Keep delegating** — risk_module uses gateway proxy for real-time, adds a thin batch client for batch jobs. No need for the full agent loop.
3. **Extract to shared repo** — move `claude_gateway` to its own repo (already has sync script: `scripts/sync_claude_gateway.sh`). Both apps import.

**Recommendation:** Option 1 or 3. The sync script already exists, suggesting option 3 is the intended direction. No urgency until batch/scheduled work begins.

**Priority:** Low — becomes relevant when building batch jobs or Tier 1 local MCP.

---

### 3.2 AgentProfile Generalization

**Problem:** `AgentProfile` and `CHANNEL_TIERS` exist only in AI-excel-addin's `api/tools.py`. Risk module has no equivalent — tool availability is hardcoded.

**Why it matters for risk_module:** The Financial Advisor Architecture defines 3 agent profiles (analyst, advisor, finance-cli) with different MCP server sets. The web chat, Telegram, and scheduled agents each need different tool subsets.

**What to build:**
- Extract `AgentProfile` dataclass + `CHANNEL_TIERS` resolution to `claude_gateway` (it's gateway-level logic, not app-specific)
- Both apps configure their tiers in YAML or env, not code
- Advisor agent profile would be defined once, used from any channel

**Effort:** 1 week. Mostly restructuring existing code.

**Priority:** Medium — useful when building the advisor agent or adding new channels.

---

## Prioritized Roadmap

### Phase A: Quick Wins (hours to days)

| Item | What | Effort | Impact |
|------|------|--------|--------|
| Web search/fetch | Add 2 server-side tool definitions | Hours | General web research in chat |
| Compaction | Beta header + message handling audit in AgentRunner | Hours | Longer conversations |
| Code execution | Add tool definition + basic file return | 1-2 days | Visualizations + ad-hoc analysis |

### Phase B: New Capabilities (1-2 weeks each)

| Item | What | Effort | Impact |
|------|------|--------|--------|
| Batch API | Batch runner + result storage + poll/notify | 1-2 weeks | 50% cost on bulk analysis |
| Structured outputs | Schemas for agent format, trade proposals | 1 week | Reliable parsing |
| Cost tracking | Aggregate usage + budget enforcement | 1 week | Cost visibility + caps |
| Transcript logging | JSONL logging in risk_module gateway | < 1 week | Debugging + compliance |

### Phase C: Medium-Term (2-4 weeks each)

| Item | What | Effort | Impact |
|------|------|--------|--------|
| Files API | Upload/download plumbing in gateway + frontends | 1-2 weeks | Multi-turn document analysis |
| Cross-session memory | Persistent memory for web/Telegram channels | 1-2 weeks | Session continuity |
| AgentProfile extraction | Move to claude_gateway, YAML config | 1 week | Multi-channel agent profiles |
| claude_gateway as dep | Publish/import for risk_module use | 1 week | Enables batch + scheduled agents |

---

## Decision Points

1. **Code execution vs our engines** — Code execution is for ad-hoc, exploratory analysis. Our engines (Monte Carlo, backtest, optimization) are for production workflows with known parameters. Complement, not replace.

2. **Batch API vs real-time** — Batch is 50% cheaper but async (up to 1 hour). Good for background sweeps. Not a replacement for interactive chat.

3. **Memory: API tool vs local tools** — `claude_gateway` already defines `memory_*` local tools. The API's `memory_20250818` tool type is an alternative with SDK helpers. Either works — the question is whether the SDK helper adds value over the existing local tool approach.

4. **claude_gateway distribution** — Import as pip dep, or extract to shared repo? The sync script exists (`sync_claude_gateway.sh`), suggesting shared repo is the intended path. Decide when risk_module needs direct API access.

5. **Structured outputs scope** — Use for all responses (constraining), or only for machine-consumed responses like trade proposals and agent format (practical)? Conversational text shouldn't be schema-constrained.
