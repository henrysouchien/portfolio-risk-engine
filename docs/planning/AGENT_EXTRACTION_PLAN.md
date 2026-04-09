# Agent Extraction Plan

> **Status**: Draft
> **Created**: 2026-03-19
> **Parent doc**: `docs/planning/launch/OPEN_SOURCE_LAUNCH_GAPS.md` (item C3)
> **Source repo**: `AI-excel-addin/` (`api/agent/`, `api/memory/`, `api/tools.py`, `packages/agent-gateway/`)
> **Target**: Standalone `openclaw-agent` package in this repo

---

## 1. Executive Summary

The autonomous analyst agent lives in `AI-excel-addin/api/` as a profile config + orchestration layer on top of the `agent-gateway` package. Extracting it into a standalone package requires:

1. **Prerequisite**: Split `api/tools.py` (2,801-line monolith) into focused modules (Phase B refactor — already designed)
2. **Decouple memory**: Extract protocol interface from SQLite implementation
3. **Decouple skills**: Make filesystem-independent via pluggable loaders
4. **Decouple system prompt**: Remove imports from tools.py, make template-driven
5. **Package the agent runner**: Standalone entry point with CLI and programmatic API
6. **Configure MCP servers**: Declarative YAML config instead of hardcoded server sets

The `agent-gateway` package is already extracted with a `ModelProvider` protocol (Anthropic + OpenAI implementations), `AgentRunner`, `ToolDispatcher`, `McpClientManager`, and `MemoryStore`. The agent extraction builds on top of this foundation.

---

## 2. Current Architecture

### What exists in `agent-gateway` (already extracted)

| Module | LOC | Purpose |
|--------|-----|---------|
| `runner.py` | 1,313 | `AgentRunner` — agentic loop, streaming, tool execution, sub-agents |
| `tool_dispatcher.py` | ~300 | `ToolDispatcher` — routes calls to local handlers or MCP servers, approval gates |
| `mcp_client.py` | ~400 | `McpClientManager` — server discovery from `~/.claude.json`, lifecycle, tool routing |
| `memory.py` | 733 | `MemoryStore` — SQLite EAV, markdown sync, embedding-based recall, watchdog |
| `skills.py` | 260 | `SkillLoader`, `SkillProfile`, `SkillStateStore`, YAML frontmatter parsing |
| `providers/base.py` | ~60 | `ModelProvider` protocol, `ModelInfo`, `StreamEvent`, `CostEstimate` |
| `providers/anthropic.py` | ~400 | `AnthropicProvider` — Messages API streaming, normalize_messages |
| `providers/openai.py` | ~400 | `OpenAIProvider` — ChatCompletion streaming, message normalization |
| `event_log.py` | ~80 | `EventLog` — append-only event stream |
| `session.py` | ~200 | `AuthManager`, `Session`, `SessionStore` |
| `server.py` | ~300 | `create_gateway_app()` — FastAPI factory with chat/init/tool-approval routes |
| `send_prompt.py` | ~100 | One-shot prompt execution (non-streaming) |

### What exists in `AI-excel-addin/api/` (needs extraction)

| Module | LOC | Purpose | Extraction status |
|--------|-----|---------|-------------------|
| `agent/profiles/__init__.py` | 79 | `ProfileConfig` dataclass, `load_profile()` | Extract as-is |
| `agent/profiles/analyst.py` | 771 | Analyst profile: MCP servers, tool packs, system prompts, excluded tools | Extract + generalize |
| `agent/runner.py` | 650 | `AgentRunner` subclass: trade journal hooks, fill classification, memory helpers | Extract app-specific hooks only |
| `agent/autonomous.py` | 546 | `run_autonomous()`: MCP startup, prompt assembly, state persistence, Telegram notify | Extract core loop |
| `agent/hooks.py` | ~100 | Cost tracking, tool timing hooks | Extract |
| `memory/store.py` | 1,056 | `MemoryStore` subclass: enhanced recall, workspace sync, ticker-specific logic | Decouple (Phase 3) |
| `memory/__init__.py` | ~50 | Global store singleton, `init_memory()`, `get_workspace_dir()` | Replace with config |
| `memory/embeddings.py` | ~150 | `OpenAIEmbedder`, `NoOpEmbedder` | Extract |
| `skill_loader.py` | 128 | State extraction, JSON parsing, skill state management | Already delegates to gateway |
| `system_prompt.py` | 862 | Chat system prompt builder (Excel-addin-specific) | Does NOT move — addin-specific |
| `tools.py` | 2,801 | Monolith: tool defs, handlers, profiles, auth, prompt builder | Split first (prerequisite) |
| `mcp_client.py` | ~150 | App-level MCP config: `ALLOWED_SERVERS`, `TIMEOUT_OVERRIDES` | Replace with YAML config |

### Dependency graph (current)

```
analyst.py (profile config)
  → tools.py (ANALYST_TOOLS, LOCAL_TOOLS, MEMORY_TOOLS, build_workspace_context, build_available_agents_section)
  → skill_loader.py (SKILL_STATE_FILE_NAME)

agent/runner.py (AgentRunner subclass)
  → agent_gateway.runner (base AgentRunner)
  → agent_gateway.providers (AnthropicProvider, ModelProvider)
  → tools.py (_execute_memory_tool, _get_cached_tools, get_active_tool_definitions, get_anthropic_config, _execute_run_agent)

agent/autonomous.py (orchestrator)
  → agent_gateway (AgentRunner, EventLog, ToolDispatcher, AnthropicProvider)
  → agent.profiles (ProfileConfig)
  → tools.py (_build_local_tool_handlers, get_active_tool_definitions, get_anthropic_config, make_run_agent_handler)
  → mcp_client.py (mcp_clients global)
  → memory/* (global store singleton)
```

---

## 3. What Gets Extracted vs What Stays

### Moves to `openclaw-agent` package

| Component | Source | Notes |
|-----------|--------|-------|
| `ProfileConfig` | `api/agent/profiles/__init__.py` | As-is — clean dataclass |
| Analyst profile config | `api/agent/profiles/analyst.py` | Generalized — remove hardcoded paths, use YAML for MCP server config |
| Autonomous runner | `api/agent/autonomous.py` | Core loop extracted; Telegram notify becomes a pluggable notifier |
| Gateway `AgentRunner` | `agent-gateway` | Used as dependency (pip install) |
| Gateway `ToolDispatcher` | `agent-gateway` | Used as dependency |
| Gateway `McpClientManager` | `agent-gateway` | Used as dependency |
| Gateway `MemoryStore` | `agent-gateway` | Used as dependency; app-level subclass stays in addin |
| Gateway `SkillLoader` | `agent-gateway` | Used as dependency |
| Gateway `ModelProvider` | `agent-gateway` | Used as dependency |
| Skill state helpers | `api/skill_loader.py` | Thin wrappers over gateway — extract |
| Embedding providers | `api/memory/embeddings.py` | `OpenAIEmbedder`, `NoOpEmbedder` |
| Memory init helper | `api/memory/__init__.py` | Rewritten as config-driven factory |

### Stays in AI-excel-addin

| Component | Reason |
|-----------|--------|
| `api/agent/runner.py` (trade journal hooks, fill classification) | Excel-addin-specific trade execution UX |
| `api/system_prompt.py` (chat system prompt) | Excel/workbook-specific context injection |
| `api/tools.py` → `api/tool_catalog.py` (tool definitions) | Excel-addin tool catalog with channel tiers |
| `api/tools.py` → `api/tool_handlers.py` (stream_chat_events, etc.) | FastAPI gateway streaming handlers |
| `api/memory/store.py` (ticker-specific recall) | App-specific memory extensions |
| `api/main.py` (FastAPI app) | Web app routes |
| `mcp_servers/excel_mcp_server.py` | Excel-specific MCP relay |

### Shared via `agent-gateway` dependency

The `agent-gateway` package (`packages/agent-gateway/`) is the shared foundation. Both the standalone agent and AI-excel-addin import it. It already contains the core abstractions:

- `ModelProvider` protocol + `AnthropicProvider` + `OpenAIProvider`
- `AgentRunner` (agentic loop, streaming, tool execution, sub-agents)
- `ToolDispatcher` (local + MCP routing, approval gates)
- `McpClientManager` (stdio server discovery + lifecycle)
- `MemoryStore` (SQLite EAV + markdown sync + embedding recall)
- `SkillLoader` + `SkillProfile` (YAML skill parsing)

---

## 4. Phased Implementation

### Phase 0: Prerequisite — tools.py Split (in AI-excel-addin)

**Why**: The analyst profile (`analyst.py`) imports from `tools.py`: `ADDIN_TOOL_NAMES`, `ANALYST_TOOLS`, `LOCAL_TOOLS`, `MEMORY_TOOLS`, `build_available_agents_section`, `build_workspace_context`. These are tangled with Excel-specific tool definitions, channel tiers, and handler code. The split makes it possible to import just the constants without pulling in the entire monolith.

**Design**: Already specified in `docs/design/gateway-refactoring-task.md` (Phase B1). Creates 5 focused modules with a thin re-export facade:

```
api/credentials.py      (~110 lines) — auth config
api/tool_catalog.py     (~350 lines) — tool defs, channel tiers, classification
api/agent_profiles.py   (~100 lines) — AgentProfile, _AGENT_PROFILES
api/system_prompt.py    (~550 lines) — chat prompt builder (Excel-specific)
api/tool_handlers.py    (~950 lines) — handlers, streaming, run_agent
api/tools.py            (~120 lines) — re-export facade
```

**Sequencing**: Execute this in AI-excel-addin BEFORE starting agent extraction. The split is independently valuable and reduces extraction complexity.

**Estimated effort**: 2-3 hours (6 incremental commits, each independently testable).

---

### Phase 1: Define Package Structure

Create `agent/` directory in this repo (risk_module) with the standalone agent package.

```
agent/
├── __init__.py              # Public API: run_agent, AgentConfig, ProfileConfig
├── __main__.py              # CLI entry point: python -m agent
├── config.py                # AgentConfig dataclass + YAML loader
├── profiles/
│   ├── __init__.py          # ProfileConfig + load_profile()
│   └── analyst.py           # Default analyst profile (generalized)
├── runner.py                # AutonomousRunner — the core orchestration loop
├── hooks.py                 # Pluggable hook system (cost tracking, tool timing, notifications)
├── prompt_builder.py        # Template-based system prompt assembly
├── memory_factory.py        # Memory store initialization from config
├── notifiers/
│   ├── __init__.py          # NotifierProtocol
│   ├── telegram.py          # Telegram notifier (extracted from autonomous.py)
│   └── console.py           # Console/stdout notifier (default for CLI)
├── cli.py                   # Click CLI: `openclaw agent run`, `openclaw agent skill`
└── py.typed                 # PEP 561 marker
```

**Key design decisions**:

1. **`agent-gateway` as a pip dependency** — not vendored, not copied. The agent package declares `agent-gateway>=0.x` in its dependencies. This is the same pattern as `app-platform`.

2. **No FastAPI dependency** — the agent package is pure Python + asyncio. It can be embedded in a FastAPI app (as AI-excel-addin does) or run standalone via CLI.

3. **No database dependency** — memory uses SQLite (via gateway's `MemoryStore`), configurable via YAML. No Postgres required.

4. **No hardcoded paths** — all paths derived from config (`~/.openclaw/` default, overridable).

---

### Phase 2: Extract Core Runner

**Source**: `api/agent/autonomous.py` (546 lines)

**What moves**: The `run_autonomous()` orchestration flow:
1. Load profile config
2. Start MCP servers (from config, not hardcoded set)
3. Build system prompt (from profile's prompt builder)
4. Load previous state
5. Create `AgentRunner` + `ToolDispatcher`
6. Execute the agentic loop
7. Extract state update from response
8. Persist state
9. Notify (pluggable)

**What changes**:

- `mcp_clients` global → `McpClientManager` created from config
- `get_anthropic_config()` → read from `AgentConfig.model_config`
- `AnthropicProvider` hardcoded → `ModelProvider` from config (Anthropic or OpenAI)
- `_build_local_tool_handlers()` → local tools defined in profile config
- `ChannelRegistry` (Excel-specific) → removed; the standalone agent has no channel concept
- Telegram notification → `NotifierProtocol` with Telegram as one implementation

**New `AgentConfig` dataclass**:

```python
@dataclass
class AgentConfig:
    # Model
    provider: str = "anthropic"           # "anthropic" | "openai" | "local"
    model: str = "claude-sonnet-4-6"
    api_key: str = ""                     # or read from env
    max_tokens: int = 16384
    thinking: bool = True

    # MCP servers
    mcp_config_path: Path = Path("~/.claude.json")
    always_on_servers: Set[str] = field(default_factory=lambda: {"portfolio-mcp", "fmp-mcp"})
    deferred_servers: Set[str] = field(default_factory=set)
    timeout_overrides: Dict[str, int] = field(default_factory=dict)

    # Agent behavior
    max_turns: int = 40
    timeout_seconds: float = 600
    profile: str = "analyst"

    # Memory
    memory_enabled: bool = True
    memory_db_path: Path = Path("~/.openclaw/memory.db")
    embedding_provider: str = "openai"    # "openai" | "none"
    embedding_api_key: str = ""           # or read from env

    # Workspace
    workspace_dir: Path = Path("~/.openclaw/workspace")
    state_dir: Path = Path("~/.openclaw/state")

    # Notifications
    notifier: str = "console"             # "console" | "telegram" | "none"
    telegram_chat_id: str = ""
    telegram_bot_token: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> "AgentConfig":
        """Load config from ~/.openclaw/agent.yaml"""
        ...
```

**Estimated effort**: 4-5 hours. Core extraction is mechanical; the complexity is in wiring config instead of globals.

---

### Phase 3: Decouple Memory Store

**Current state**: `api/memory/store.py` (1,056 lines) extends the gateway's `MemoryStore` (733 lines) with:
- Enhanced hybrid recall (keyword + semantic + recency fusion scoring)
- Numpy-based matrix cache for fast cosine similarity
- Markdown workspace sync (ticker files, notes)
- Content-hash deduplication for embeddings

**Problem**: The gateway `MemoryStore` is already a clean SQLite implementation with embedding support. The app-level subclass adds domain-specific recall tuning. For the standalone agent, the gateway's base `MemoryStore` is sufficient.

**Approach**: No new protocol needed. The gateway's `MemoryStore` already accepts an `EmbeddingProvider` protocol:

```python
class MemoryStore:
    def __init__(self, db_path: str | Path, *, embedding_fn: EmbeddingProvider | None = None):
        ...
```

**What the agent package does**:
1. Use `MemoryStore` from `agent-gateway` directly
2. Provide `memory_factory.py` that creates a store from `AgentConfig`:
   - Reads `memory_db_path` from config
   - Creates `OpenAIEmbedder` or `NoOpEmbedder` based on config
   - Returns configured `MemoryStore` instance
3. If users want the enhanced recall from AI-excel-addin, they can subclass — but the default is the gateway's implementation

**No interface extraction needed** — the gateway already has the right abstraction.

**Estimated effort**: 1-2 hours.

---

### Phase 4: System Prompt Extraction

**Current state**: Two separate prompt systems:
1. `api/system_prompt.py` (862 lines) — Excel/chat system prompt (Excel-specific, stays in addin)
2. `api/agent/profiles/analyst.py` — Autonomous analyst system prompt (domain-specific, moves)

The analyst profile's `SYSTEM_PROMPT_TEMPLATE` (~110 lines) defines the autonomous workflow: portfolio check, market scan, idea triage, research, briefing. This is the analyst persona, not Excel infrastructure.

**What moves to `agent/prompt_builder.py`**:
- `SYSTEM_PROMPT_TEMPLATE` (main analyst workflow)
- `SKILL_SYSTEM_PROMPT_TEMPLATE` (skill execution wrapper)
- `INITIAL_USER_MESSAGE_TEMPLATE` (state-aware first message)
- `describe_market_status()` (US market hours helper)
- `format_tool_catalog()` (MCP tool inventory for prompt)
- `build_tool_packs_section()` (deferred tool pack descriptions)
- `build_system_prompt()` / `build_skill_system_prompt()` / `build_initial_user_message()`
- `_inject_workspace_context()` helper

**What changes**:
- Remove `from tools import build_available_agents_section, build_workspace_context` — these move to the agent package directly
- `DEV_MODE_SYSTEM_PROMPT_TEMPLATE` and dev mode sections do NOT move (developer-specific, not user-facing)
- Hardcoded paths (`INVESTMENT_TOOLS_DIR`, `ANALYST_DEV_DIR`) removed — these are development environment artifacts
- Templates become configurable (users can override via profile YAML)

**Template customization**:
```yaml
# ~/.openclaw/profiles/analyst.yaml
name: analyst
system_prompt_template: |
  You are an autonomous investment analyst...
  {today} {market_status} {tool_catalog} {workspace_context}
# OR reference a file:
system_prompt_file: ~/.openclaw/prompts/analyst.md
```

**Estimated effort**: 3-4 hours. The prompt templates are large but the extraction is mostly mechanical.

---

### Phase 5: Skill Loader Decoupling

**Current state**: `api/skill_loader.py` (128 lines) is already thin — it delegates to the gateway's `SkillLoader`, `SkillStateStore`, and `parse_skill_file()`. The main additions are state extraction helpers (`_extract_state_update`, `_extract_summary`).

**The gateway's `SkillLoader`** discovers skills from a filesystem directory (markdown files with YAML frontmatter). This is already filesystem-path-configurable via constructor args.

**What moves**:
- `_extract_state_update()` and `_extract_summary()` — utility functions, move to `agent/skill_helpers.py`
- `SKILL_STATE_FILE_NAME` constant — move to `agent/config.py`

**What the agent package does**:
- Instantiate `SkillLoader(skills_dir=config.workspace_dir / "skills")` from config
- Skills directory is user-configurable, defaults to `~/.openclaw/workspace/skills/`
- Built-in skills ship in the package's `data/skills/` directory and are copied to workspace on first run

**Built-in skills** (6 initial, matching `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md`):
```
agent/data/skills/
├── morning-briefing.md
├── risk-check.md
├── rebalance-analysis.md
├── earnings-preview.md
├── exit-signal-scan.md
└── performance-review.md
```

Each is a markdown file with YAML frontmatter (the format the gateway's `parse_skill_file()` already supports).

**Estimated effort**: 2 hours.

---

### Phase 6: MCP Server Configuration

**Current state**: MCP servers are hardcoded in `analyst.py`:

```python
ALWAYS_ON_MCP_SERVERS: Set[str] = {"fmp-mcp", "edgar-financials", "portfolio-mcp", "jobs-mcp"}
DEFERRED_MCP_SERVERS: Set[str] = {"roam-research", "gsheets-mcp", "drive-mcp", "research-mcp"}
```

Server spawn commands come from `~/.claude.json` (the MCP config file shared with Claude Code).

**Approach**: Keep `~/.claude.json` as the MCP server registry (it already works and is shared with Claude Code). The agent config specifies WHICH servers to connect:

```yaml
# ~/.openclaw/agent.yaml
mcp:
  config_path: ~/.claude.json        # where server spawn commands live
  always_on:
    - portfolio-mcp                  # start immediately
    - fmp-mcp
  deferred:
    - roam-research                  # start on demand via load_tools()
    - gsheets-mcp
  timeout_overrides:
    portfolio-mcp: 60
    fmp-mcp: 30
```

**For users WITHOUT `~/.claude.json`**: The CLI setup wizard (C2, separate work item) generates it. For manual setup, document the format.

**Tool packs**: Currently hardcoded in `analyst.py` as `ANALYST_TOOL_PACKS`. Move to profile YAML:

```yaml
tool_packs:
  portfolio-analytics:
    server: portfolio-mcp
    description: "Factor analysis, optimization, backtesting"
    tools: [get_factor_analysis, run_optimization, run_backtest, ...]
  fmp-screening:
    server: fmp-mcp
    description: "Stock screening, estimates, peer comparison"
    tools: [screen_stocks, screen_estimate_revisions, ...]
```

**Estimated effort**: 2-3 hours.

---

### Phase 7: CLI Entry Point

**What**: `python -m agent` or `openclaw agent run` command that runs the autonomous analyst.

```
Usage:
  openclaw agent run [OPTIONS]
  openclaw agent skill <SKILL_NAME> [OPTIONS]
  openclaw agent chat [OPTIONS]

Options:
  --config PATH        Config file (default: ~/.openclaw/agent.yaml)
  --profile NAME       Agent profile (default: analyst)
  --task TEXT           Override task description
  --model TEXT          Override model
  --max-turns INT      Override max turns
  --dry-run            Show system prompt and exit
  --verbose            Enable debug logging
```

**Implementation**: `agent/cli.py` using Click:

```python
@click.group()
def agent():
    """Run the autonomous investment analyst."""

@agent.command()
@click.option("--config", type=click.Path(), default="~/.openclaw/agent.yaml")
@click.option("--profile", default="analyst")
@click.option("--task", default=None)
@click.option("--dry-run", is_flag=True)
def run(config, profile, task, dry_run):
    """Execute a full autonomous analyst run."""
    cfg = AgentConfig.from_yaml(Path(config).expanduser())
    if dry_run:
        # Build and print the system prompt, then exit
        ...
        return
    asyncio.run(run_autonomous(cfg, profile_name=profile, task_override=task))

@agent.command()
@click.argument("skill_name")
@click.option("--config", type=click.Path(), default="~/.openclaw/agent.yaml")
def skill(skill_name, config):
    """Execute a named skill workflow."""
    cfg = AgentConfig.from_yaml(Path(config).expanduser())
    asyncio.run(run_skill(cfg, skill_name=skill_name))
```

**Estimated effort**: 2-3 hours.

---

### Phase 8: Integration with portfolio-mcp

**Current coupling**: The analyst agent calls portfolio-mcp tools via MCP stdio transport. The agent doesn't import portfolio-mcp code directly — it sends JSON tool calls over the MCP protocol.

**No code change needed for integration.** The agent talks to portfolio-mcp the same way it does today: via `McpClientManager` connecting to the server process defined in `~/.claude.json`.

**What the setup wizard does** (C2, separate work item):
1. Detects if `portfolio-mcp` is installed (`pip show portfolio-mcp`)
2. Generates the MCP server entry in `~/.claude.json`:
   ```json
   {
     "mcpServers": {
       "portfolio-mcp": {
         "command": "python3",
         "args": ["-m", "portfolio_mcp.server"],
         "env": { "PORTFOLIO_CONFIG": "~/.openclaw/portfolio.yaml" }
       }
     }
   }
   ```
3. Adds `portfolio-mcp` to `always_on` in agent config

**Estimated effort**: 0 hours (no code change — MCP transport is already the integration layer).

---

### Phase 9: Testing Strategy

#### Unit tests (in this repo)

| Test area | Count | Description |
|-----------|-------|-------------|
| Config loading | 8-10 | YAML parsing, defaults, env var override, validation |
| Prompt builder | 10-12 | Template rendering, market status, tool catalog formatting |
| Profile loading | 5-6 | `load_profile()`, profile validation, custom profiles |
| Memory factory | 4-5 | Store creation from config, embedding provider selection |
| Skill helpers | 4-5 | State extraction, summary extraction |
| CLI | 6-8 | Argument parsing, --dry-run, --config, error handling |
| Notifiers | 4-5 | Console output, Telegram formatting, notifier protocol |
| Hook system | 4-5 | Cost tracking, tool timing, hook composition |

**Total**: ~50-55 unit tests

#### Integration tests

| Test area | Description |
|-----------|-------------|
| End-to-end run (mocked model) | Full `run_autonomous()` with stubbed `ModelProvider` that returns canned responses + tool calls |
| MCP server startup | Verify `McpClientManager` connects to a test MCP server |
| Memory round-trip | Store → recall → verify content via `MemoryStore` |
| Skill execution (mocked) | Load a skill YAML, verify prompt assembly, mock execution |

#### Existing gateway tests

The `agent-gateway` package has its own test suite covering `AgentRunner`, `ToolDispatcher`, `McpClientManager`, `MemoryStore`, and providers. These do NOT move — they stay with the gateway package.

---

### Phase 10: Migration Path for AI-excel-addin

After extraction, AI-excel-addin should depend on `openclaw-agent` instead of duplicating the autonomous runner code.

**Migration steps**:

1. Add `openclaw-agent` to AI-excel-addin's dependencies
2. Replace `from agent.profiles import ProfileConfig` with `from openclaw_agent import ProfileConfig`
3. `api/agent/autonomous.py` becomes a thin wrapper that:
   - Creates `AgentConfig` from the existing env vars
   - Calls `openclaw_agent.run_autonomous(config, ...)`
   - Adds the trade journal hooks via the hook system
4. `api/agent/runner.py` (trade journal hooks, fill classification) stays as an app-specific `AgentRunner` subclass — no change
5. `api/memory/store.py` stays as the enhanced recall implementation — no change
6. `api/system_prompt.py` stays as the Excel chat prompt — no change

**Risk**: Low. The migration is additive — AI-excel-addin gains a dependency but doesn't lose functionality. The trade journal hooks, Excel-specific prompts, and enhanced memory recall all stay in the addin.

---

## 5. Dependency Summary

```
openclaw-agent
├── agent-gateway (pip)      # AgentRunner, ToolDispatcher, McpClientManager, MemoryStore, providers
├── click (pip)               # CLI
├── pyyaml (pip)              # Config loading
└── (optional) openai (pip)   # For OpenAI embedding provider
```

No dependency on:
- FastAPI (web framework)
- PostgreSQL / psycopg2 (database)
- risk_module internals (talks to portfolio-mcp via MCP protocol)
- AI-excel-addin code (fully standalone)

---

## 6. Sequencing and Effort

| Phase | Description | Depends on | Effort | Repo |
|-------|-------------|------------|--------|------|
| **0** | tools.py split (B1 refactor) | None | 2-3 hrs | AI-excel-addin |
| **1** | Package structure + AgentConfig | Phase 0 | 2 hrs | risk_module |
| **2** | Core runner extraction | Phase 1 | 4-5 hrs | risk_module |
| **3** | Memory factory | Phase 1 | 1-2 hrs | risk_module |
| **4** | System prompt extraction | Phase 0, 1 | 3-4 hrs | risk_module |
| **5** | Skill loader | Phase 1 | 2 hrs | risk_module |
| **6** | MCP server config | Phase 1 | 2-3 hrs | risk_module |
| **7** | CLI entry point | Phases 2-6 | 2-3 hrs | risk_module |
| **8** | portfolio-mcp integration | None | 0 hrs | N/A |
| **9** | Tests | Phases 1-7 | 4-5 hrs | risk_module |
| **10** | AI-excel-addin migration | Phases 1-7 | 2-3 hrs | AI-excel-addin |

**Total estimated effort**: 25-33 hours (~4-5 sessions)

**Critical path**: Phase 0 (tools.py split) blocks Phases 1-7. Once Phase 0 is done, Phases 1-6 can proceed largely in parallel. Phase 7 (CLI) depends on all of 2-6. Phase 10 (migration) is independent of launch.

---

## 7. Open Questions

1. **Package name**: `openclaw-agent` vs `portfolio-agent` vs just `agent/` subdirectory in this repo (same pattern as `fmp/`, `ibkr/`)? The in-repo pattern avoids PyPI publish complexity initially.

2. **agent-gateway publish**: The gateway package is currently in AI-excel-addin. It needs to be on PyPI (or vendored) before the agent can depend on it. Should we publish `agent-gateway` to PyPI first, or vendor the relevant modules?

3. **Dev mode**: The analyst profile has an elaborate dev mode (file_write, file_edit, run_bash, custom PYTHONPATH). Does this move to the agent package or stay as an addin-specific feature?

4. **Agent profiles beyond analyst**: The addin also has an `advisor` profile. Do we extract that too, or ship with just `analyst`?

5. **Workspace directory structure**: The analyst uses `workspace/tickers/`, `workspace/notes/`, `workspace/daily/`, `workspace/trades/`. Should the agent package enforce this structure or let profiles define it?

---

## 8. Success Criteria

- [ ] `pip install openclaw-agent` (or `python -m agent`) works without AI-excel-addin
- [ ] `openclaw agent run` executes a full autonomous analyst loop with portfolio-mcp + fmp-mcp
- [ ] `openclaw agent skill morning-briefing` executes a built-in skill
- [ ] Configuration is entirely YAML-driven (no hardcoded paths or env vars required)
- [ ] Works with Anthropic (Claude) and OpenAI (GPT-4) via `ModelProvider` protocol
- [ ] Memory persists across runs (SQLite in `~/.openclaw/memory.db`)
- [ ] AI-excel-addin can migrate to depend on this package (Phase 10)
- [ ] 50+ tests, all passing

---

*This plan covers item C3 from `docs/planning/launch/OPEN_SOURCE_LAUNCH_GAPS.md`. It depends on C1 (Gateway Model Abstraction) being partially complete — specifically, the `ModelProvider` protocol and `OpenAIProvider` already exist in `agent-gateway`. Full model-agnostic support (Gemini, local models) is a separate effort.*
