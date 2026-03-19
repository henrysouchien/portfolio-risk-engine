# Workflow Guides — Portfolio-MCP Domain Knowledge

> **Created**: 2026-03-19
> **Parent**: `docs/OPEN_SOURCE_LAUNCH_GAPS.md` (item A3 — replaces skill-loader-spec)
> **Goal**: Ship workflow guides as domain knowledge attached to portfolio-mcp tools.

---

## Context

Portfolio-mcp has 60+ tools. The agent can call any of them, but **how to combine them effectively** is domain knowledge that should ship with the tools — not live in the gateway or in a separate skill system.

The gateway (ai-excel-addin) already has a working skill system:
- `SkillLoader` + `run_agent(agent="skill-name")` for sub-agent execution
- 18 skill markdown files (including allocation-review, risk-review, earnings-review, stock-pitch, etc.)
- State persistence, tool packs, deliverable writing

**This plan does NOT duplicate that.** Instead, portfolio-mcp exposes workflow guides as a tool — domain-specific instructions for how to use its tools together. Any agent (gateway, finance-cli, Claude Code) can call `get_workflow()` to learn how to combine portfolio tools for a task.

### Why here, not in the gateway?

The people who build and maintain the tools know best how they should be combined. When a tool changes (new params, new flags, new output format), the workflow guide should update in the same commit. Domain knowledge lives with domain code.

### Relationship to gateway skills

- **Gateway skills** = agent execution profiles (sub-agent spawn, tool packs, state persistence)
- **Workflow guides** = domain knowledge ("here's how to use these tools for this task")
- Gateway skills can reference workflow guides: `run_agent("risk-review")` internally calls `get_workflow("risk-review")` to get the domain instructions
- Or agents can use them directly without spawning a sub-agent

---

## Design

### Workflow file format

Same format as ai-excel-addin skills (YAML frontmatter + markdown body):

```markdown
---
name: stock-analysis
description: 7-step stock analysis using EDGAR filings, FMP data, and portfolio tools.
servers: [portfolio-mcp, fmp-mcp, edgar-financials]
tools:
  - fmp-mcp.fmp_profile
  - fmp-mcp.get_earnings_transcript
  - fmp-mcp.get_news
  - fmp-mcp.compare_peers
  - fmp-mcp.get_technical_analysis
  - edgar-financials.get_filing_sections
  - edgar-financials.get_financials
  - edgar-financials.get_metric
  - analyze_stock
---

# Stock Analysis

## When to Use
...

## Workflow
1. Company Identification — `fmp_profile(symbol=TICKER)` ...
2. Data Collection — ...
...
```

Fields:
- `name` (required): workflow identifier (lowercase, hyphens). NOT automatically mapped to audit workflow names — audit integration is per-workflow and only applies to recommendation-style workflows (allocation-review, risk-review). Informational workflows (stock-analysis, morning-briefing) have no audit trail.
- `audit_workflow` (optional): explicit audit workflow name if this workflow uses `record_workflow_action()`. Must match `_ALLOWED_WORKFLOWS` in `mcp_tools/audit.py`. Example: `audit_workflow: allocation_review`
- `description` (required): one-line summary
- `tools` (required): list of tools used, namespaced by server. Format: `server_id.tool_name` for cross-server tools, bare `tool_name` for portfolio-mcp tools. Example: `[fmp-mcp.fmp_profile, edgar-financials.get_filing_sections, analyze_stock]`
- `servers` (optional): list of MCP servers the workflow depends on (for documentation). Example: `[portfolio-mcp, fmp-mcp, edgar-financials]`
- Body: markdown workflow instructions (the actual domain knowledge)

### Storage

```
workflows/
├── stock-analysis.md        # v1 — detailed content from skill-loader-spec
├── risk-review.md           # v1 — adapt from ai-excel-addin risk-review.md
├── allocation-review.md     # v1 — adapt from ai-excel-addin allocation-review.md
├── earnings-review.md       # v2 — needs full spec (ai-excel-addin has source material)
├── performance-review.md    # v2 — needs full spec
└── morning-briefing.md      # v2 — needs full spec
```

**V1 scope: 3 workflows** (stock-analysis, risk-review, allocation-review). These have complete source material. The remaining 3 are v2 — add them when content is written.

Repo-relative `workflows/` directory. Git-tracked. **Loaded once at server startup** (not re-read per request). Workflow content changes require a server restart to take effect. This prevents filesystem mutation from silently changing served content.

Tool name validation runs in the test suite (`tests/test_workflow_loader.py`). Bare tool names validated against portfolio-mcp registry, `fmp-mcp.*` tools validated against the local FMP server registry. No CI pipeline in v1 — tests are run manually before merge (consistent with existing repo workflow).

### MCP tools (2 new tools on portfolio-mcp)

#### `list_workflows()`

Returns available workflows with names and descriptions.

```python
@mcp.tool()
def list_workflows() -> dict:
    """List available workflow guides — domain-specific instructions for combining portfolio tools."""
    workflows = loader.list_workflows()
    return {"status": "success", "workflows": workflows}
```

Response follows the standard portfolio-mcp `{status, ...}` pattern (same as `@handle_mcp_errors`):
```json
{
  "status": "success",
  "workflows": [
    {"name": "stock-analysis", "description": "7-step stock analysis...", "tools": ["fmp-mcp.fmp_profile", "analyze_stock", ...], "servers": ["portfolio-mcp", "fmp-mcp", "edgar-financials"]},
    {"name": "risk-review", "description": "Portfolio risk assessment...", "tools": ["get_risk_analysis", "get_factor_analysis"], "servers": ["portfolio-mcp"]}
  ]
}
```

#### `get_workflow(name)`

Returns the full workflow instructions for a specific workflow.

```python
@mcp.tool()
def get_workflow(name: str) -> dict:
    """Get workflow guide — step-by-step instructions for combining portfolio tools.

    The workflow tells you which tools to call, in what order, and how to interpret results.
    Follow the steps using the MCP tools you already have access to."""
    try:
        content = loader.get_workflow(name)
        return {"status": "success", "name": name, "content": content}
    except loader.WorkflowError as e:
        return {"status": "error", "error": str(e)}
```

Error responses (distinct messages from `WorkflowError`):
- Invalid name: `{"status": "error", "error": "Invalid workflow name '..': must be lowercase alphanumeric with hyphens."}`
- Not found: `{"status": "error", "error": "Workflow 'foo' not found. Use list_workflows() to see available workflows."}`

### Parser

Minimal — port from ai-excel-addin's `parse_skill_file()`:

```python
# workflows/loader.py

import re
import yaml
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parent
_NAME_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')

# Cache: loaded once at import time. Server restart required for changes.
_CACHE: dict[str, dict] = {}  # name → validated metadata
_CONTENT_CACHE: dict[str, str] = {}  # name → full file content

def _load_all():
    """Scan and validate all workflow files. Called once at module import."""
    for path in sorted(WORKFLOWS_DIR.glob("*.md")):
        validated = _validate_workflow(path)
        if validated:
            try:
                _CACHE[validated["name"]] = validated
                _CONTENT_CACHE[validated["name"]] = path.read_text()
            except Exception:
                pass  # skip unreadable files silently

# ... (functions below use _CACHE and _CONTENT_CACHE) ...

def _validate_workflow(path: Path) -> dict | None:
    """Shared validation for both list and get paths.
    Returns validated metadata dict or None (with logged warning) on failure.
    Checks: valid frontmatter, name matches filename, required fields present."""
    meta = _parse_frontmatter(path)
    if meta is None:
        return None
    stem = path.stem
    if not _NAME_RE.match(stem):
        return None
    # Required fields: name (str, must match filename), description (str), tools (list of str)
    fm_name = meta.get("name")
    if not isinstance(fm_name, str) or fm_name != stem:
        return None
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        return None
    tools = meta.get("tools")
    if not isinstance(tools, list) or not all(isinstance(t, str) and t.strip() for t in tools) or not tools:
        return None
    # Validate tool name format: bare name (alphanumeric + underscores) or namespaced (server.tool)
    _TOOL_RE = re.compile(r'^([a-z0-9-]+\.)?[a-z_][a-z0-9_]*$')
    if not all(_TOOL_RE.match(t) for t in tools):
        return None
    # Optional fields: servers (list of str), audit_workflow (str in _ALLOWED_WORKFLOWS)
    servers = meta.get("servers", [])
    if not isinstance(servers, list) or not all(isinstance(s, str) for s in servers):
        return None
    audit_wf = meta.get("audit_workflow")
    if audit_wf is not None:
        if not isinstance(audit_wf, str):
            return None
        from mcp_tools.audit import _ALLOWED_WORKFLOWS
        if audit_wf not in _ALLOWED_WORKFLOWS:
            return None
    return {"name": stem, "description": description, "tools": tools, "servers": servers,
            **({"audit_workflow": audit_wf} if audit_wf else {}), **{k: v for k, v in meta.items()
            if k not in ("name", "description", "tools", "servers", "audit_workflow")}}

def list_workflows() -> list[dict]:
    """List available workflows from startup cache."""
    return [{"name": v["name"], "description": v["description"],
             "tools": v.get("tools", []), "servers": v.get("servers", [])}
            for v in _CACHE.values()]

class WorkflowError(Exception):
    pass

def get_workflow(name: str) -> str:
    """Get workflow content from startup cache.
    Raises WorkflowError for invalid name or not found."""
    if not _NAME_RE.match(name):
        raise WorkflowError(f"Invalid workflow name '{name}': must be lowercase alphanumeric with hyphens.")
    if name not in _CONTENT_CACHE:
        raise WorkflowError(f"Workflow '{name}' not found. Use list_workflows() to see available workflows.")
    return _CONTENT_CACHE[name]

def _parse_frontmatter(path: Path) -> dict | None:
    """Extract YAML frontmatter from a markdown file.
    Returns dict on success, None on any parse failure (missing delimiters,
    invalid YAML, non-dict result). Never raises."""
    try:
        text = path.read_text().replace("\r\n", "\n").replace("\r", "\n")
        if not text.startswith("---\n"):
            return None
        end = text.find("\n---\n", 4)
        if end == -1:
            return None
        body = text[end + 5:].strip()
        if not body:
            return None  # no workflow body — metadata-only file rejected
        result = yaml.safe_load(text[4:end])
        if not isinstance(result, dict):
            return None
        return result
    except Exception:
        return None  # malformed file — skip silently in list, raise in get

# Called AFTER all functions are defined — this is the actual call order in the file.
_load_all()
```

---

## Files to Create

| File | Purpose |
|------|---------|
| `workflows/loader.py` | Discover + parse workflow markdown files |
| `workflows/__init__.py` | Package exports |
| `workflows/stock-analysis.md` | Stock analysis workflow — 7-step SIA framework. Adapt tool-call steps from skill-loader-spec, removing runner-specific behavior (no headless/interactive branching, no `--check-servers`). Keep: tool names, parameter signatures, per-step fetching pattern, EDGAR section keys. |
| `workflows/risk-review.md` | Risk assessment workflow — adapt from ai-excel-addin skill file. Source verified at `ai-excel-addin/api/memory/workspace/notes/skills/risk-review.md` (filesystem confirmed 2026-03-19). Remove `memory_read`/`memory_write` calls, reference portfolio-mcp tool names directly. |
| `workflows/allocation-review.md` | Allocation drift check workflow — adapt from ai-excel-addin skill file. Source at same directory. Same adaptation pattern. |
| `tests/test_workflow_loader.py` | Tests: loader, validation, path traversal, tool format, error paths |

## Files to Modify

| File | Change |
|------|--------|
| `mcp_server.py` | Register `list_workflows()` and `get_workflow()` tools |
| `docs/interfaces/mcp.md` | Add workflow tools to tool inventory (deferred — update when stable) |

---

## Workflow Content

### Where to source workflow content

The 7 workflow skills already exist in ai-excel-addin:
- `allocation-review.md`, `risk-review.md`, `earnings-review.md`, `performance-review.md`, `stock-pitch.md`, `scenario-analysis.md`, `strategy-design.md`

These are written for the gateway agent with `memory_read()`/`memory_write()` calls. The portfolio-mcp versions should be **adapted** — same domain knowledge, but:
- Reference portfolio-mcp tool names directly (not `memory_read`)
- Include exact parameter names (e.g., `analyze_stock(ticker=...)` not `symbol`)
- Focus on tool usage, not agent lifecycle (no `persist_state`, no `memory_write`)

The `stock-analysis.md` workflow from the skill-loader-spec has detailed per-step tool calls with correct EDGAR/FMP signatures — reuse that content.

---

## Verification

```bash
cd /path/to/risk_module

# Test loader
python3 -c "
from workflows.loader import list_workflows, get_workflow
print(list_workflows())
print(get_workflow('stock-analysis')[:200])
"

# Test MCP tools (via Claude Code or any MCP client)
# list_workflows() → returns workflow catalog
# get_workflow(name="stock-analysis") → returns full workflow instructions
```

### Acceptance Criteria

1. `list_workflows()` returns all **valid** workflow `.md` files from `workflows/` (files passing `_validate_workflow()`) with name + description + tools + servers
2. `get_workflow("stock-analysis")` returns `{"status": "success", "name": "stock-analysis", "content": "..."}`
3. `get_workflow("../etc/passwd")` returns `{"status": "error", "error": "Invalid workflow name..."}`
4. `get_workflow("nonexistent")` returns `{"status": "error", "error": "Workflow 'nonexistent' not found..."}`
5. Workflow files are readable without any env vars or server connections
6. MCP tools registered and callable via portfolio-mcp
7. Test validates every workflow's `tools` field: bare tool names checked against portfolio-mcp's registered tools (from `mcp_server.py`), `fmp-mcp.*` tools checked against the FMP server's MCP tool list (from `fmp.server.mcp` FastMCP instance — use sync wrapper around `mcp.list_tools()`). `edgar-financials.*` tools validated structurally only (external repo — manual verification required at implementation time against the live EDGAR server's tool list). **Note**: This validation runs in the test suite only, not in the loader at import time — the loader uses regex format validation only, to avoid importing heavy MCP server modules at startup.
8. Workflow body tool-call examples (parameter names, signatures) are NOT machine-validated — they are the author's responsibility. The body is reviewed at PR time. Automated body parsing is a v2 concern.

---

## What This Does NOT Do

- **No runner** — the agent follows the workflow instructions itself
- **No sub-agent spawning** — that's the gateway's `run_agent()` job
- **No state persistence** — that's the gateway's `SkillStateStore` job
- **No tool packs / deferred loading** — that's the gateway's concern
- **No CLI** — agents are the consumers, not humans
- **No sync** — files are in-repo, git-tracked
- **No scheduling** — that's a gateway/cron concern

---

## Future

- **Gateway integration**: Gateway's `SkillLoader` could add an MCP source — load workflow guides from portfolio-mcp alongside local skill files
- **Tool-level guides**: Attach short usage hints to individual tool schemas (not just multi-tool workflows)
- **Versioning**: Workflow files could include `version` in frontmatter for compatibility checking
