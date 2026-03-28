# Tool Registry Sync Tests

## Context

Three surfaces expose portfolio tools to the AI agent in ai-excel-addin:
1. **MCP tools** (`mcp_server.py`) — 82 `@mcp.tool()` decorated functions, called directly by the LLM
2. **Agent registry** (`services/agent_registry.py`) — 77 functions (67 tool + 10 building_block), called via `POST /api/agent/call` from `_risk.*` in code execute
3. **RiskClient** (`risk_client/__init__.py`) — convenience methods wrapping `call()`

Today there's one sync test: registry → RiskClient (`test_risk_client.py:403`). Two gaps exist:
- **Gap A**: MCP tool added to `mcp_server.py` but missing from `agent_registry.py` — invisible to `_risk.*`
- **Gap B**: Function exists in `mcp_tools/*.py` but isn't wired into `mcp_server.py` OR `agent_registry.py` — completely orphaned

## Codex Review History

### R1 Findings (addressed in R2)

1. **Exclusion set incomplete** — `manage_proxy_cache` and `manage_stress_scenarios` are intentionally MCP-only but were missing from both the exclusion set and the `agent_registry.py` comment block. **Fix**: Add both to `EXCLUDED_FROM_REGISTRY` and update `agent_registry.py` comment block.
2. **Test 3 decorator heuristic too narrow** — Some tool functions (`get_positions`, `get_portfolio_news`, `get_portfolio_events_calendar`) aren't decorated with `@handle_mcp_errors`. **Fix**: Redesign Test 3 to compare `mcp.list_tools()` names against `mcp_server.py` `from mcp_tools.*` imports — this checks that every imported tool function actually got an `@mcp.tool()` wrapper, and that every surfaced tool has an import backing it.
3. **Test 3 checked imports not surfaced tools** — Import ≠ surfaced. **Fix**: Compare both directions: (a) every MCP tool that delegates to `mcp_tools.*` should have a corresponding import, and (b) every `mcp_tools.*` import should result in a surfaced tool.
4. **Test 4 regex broken** — Comment block uses Unicode box-drawing (`─`), not ASCII hyphens. **Fix**: Match `# ─{10,}` instead.

### R2 Findings (addressed in R3)

1. **High — Test 3 missing reverse direction**: Code only asserted `imported - mcp_tool_names` but not the reverse. **Fix**: Added direction 2 assertion (`mcp_tool_names - imported - INLINE_MCP_TOOLS`). Added `INLINE_MCP_TOOLS` set for `get_mcp_context` (defined directly in `mcp_server.py`).
2. **Medium — Gap B still uncovered**: Redesigned Test 3 doesn't catch functions in `mcp_tools/*.py` never imported anywhere. **Fix**: Added Test 5 (`test_mcp_tool_modules_have_no_orphaned_functions`) — AST scans all public function defs in `mcp_tools/` and checks they appear in either `mcp_server.py` imports or the agent registry. Skips known helper files (`common.py`, `trading_helpers.py`, `aliases.py`).

### R3 Findings (addressed in R4)

1. **High — Test 5 false positives on shared builders**: 4 public functions in `mcp_tools/` (`build_ai_recommendations`, `build_metric_insights`, `build_market_events`, `has_market_intelligence_data`) are consumed by `routes/positions.py`, not orphaned. **Fix**: Added `NOT_TOOL_ENTRY_POINTS` exclusion set.
2. **Low — Test count inconsistency**: One place said 4, another 5. **Fix**: Both now say 5.

## Plan

**Two files changed**:
- `tests/test_tool_surface_sync.py` — **New** (5 tests)
- `services/agent_registry.py` — Add 2 missing exclusions to comment block

### Step 0: Update `agent_registry.py` exclusion comment

Add `manage_proxy_cache` and `manage_stress_scenarios` to the INTENTIONAL EXCLUSIONS comment block (lines 23-38):

```python
# manage_proxy_cache       — Admin-only cache inspection/invalidation tool
# manage_stress_scenarios  — Admin-only scenario catalog management (CLI agent only)
```

### Test 1: `test_mcp_tools_covered_by_agent_registry`

Validates every MCP tool in `mcp_server.py` is either registered in `agent_registry.py` OR in the explicit exclusion set.

```python
import asyncio
import mcp_server
from services.agent_registry import get_registry

EXCLUDED_FROM_REGISTRY = {
    # Intentional exclusions — must match agent_registry.py comment block
    "get_mcp_context",
    "import_portfolio",
    "import_transactions",
    "normalizer_sample_csv",
    "normalizer_stage",
    "normalizer_test",
    "normalizer_activate",
    "normalizer_list",
    "manage_instrument_config",
    "manage_proxy_cache",
    "manage_stress_scenarios",
    "initiate_brokerage_connection",
    "complete_brokerage_connection",
}

def test_mcp_tools_covered_by_agent_registry():
    mcp_tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    registry_names = set(get_registry().keys())

    uncovered = sorted(mcp_tools - registry_names - EXCLUDED_FROM_REGISTRY)
    assert uncovered == [], (
        f"MCP tools not in agent registry or exclusion list: {uncovered}. "
        "Add _register() in agent_registry.py or add to EXCLUDED_FROM_REGISTRY with reason."
    )
```

### Test 2: `test_agent_registry_tools_exist_in_mcp`

Reverse check — every `tier="tool"` registry entry should be a real MCP tool (building_blocks exempted).

```python
def test_agent_registry_tools_exist_in_mcp():
    mcp_tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    registry = get_registry()

    tool_tier_names = {name for name, entry in registry.items() if entry.tier == "tool"}
    orphaned = sorted(tool_tier_names - mcp_tools)
    assert orphaned == [], (
        f"Agent registry tool-tier entries not in MCP server: {orphaned}. "
        "These are registered for code execute but not exposed as MCP tools."
    )
```

### Test 3: `test_mcp_tool_imports_match_surfaced_tools`

Redesigned per Codex feedback. Compares two authoritative sets bidirectionally:
- **Surfaced tools**: `mcp.list_tools()` names
- **Imported backends**: `from mcp_tools.*` import names in `mcp_server.py` (via AST)

Checks both directions:
- Every imported `mcp_tools.*` function should result in a surfaced MCP tool (prevents dead imports)
- Every surfaced tool should have a `mcp_tools.*` import backing it OR be in an inline-defined set (prevents copy-paste drift)

```python
import ast
from pathlib import Path

def _collect_mcp_server_imports() -> set[str]:
    """Parse mcp_server.py for 'from mcp_tools.* import X' names."""
    tree = ast.parse(Path("mcp_server.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mcp_tools."):
            for alias in node.names:
                imported.add(alias.name)
    return imported

# Utility imports from mcp_tools.common — not tool backends
UTILITY_IMPORTS = {
    "parse_list",
    "parse_json_list",
}

# MCP tools defined inline in mcp_server.py (no mcp_tools.* import)
INLINE_MCP_TOOLS = {
    "get_mcp_context",  # Diagnostic tool defined directly in mcp_server.py
}

def test_mcp_tool_imports_match_surfaced_tools():
    mcp_tool_names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    imported = _collect_mcp_server_imports() - UTILITY_IMPORTS

    # Direction 1: Every imported backend should have a surfaced tool
    dead_imports = sorted(imported - mcp_tool_names)
    assert dead_imports == [], (
        f"mcp_tools imports in mcp_server.py with no matching @mcp.tool(): {dead_imports}. "
        "Add an @mcp.tool() wrapper or remove the dead import."
    )

    # Direction 2: Every surfaced tool should have a backing import (or be inline)
    unbacked = sorted(mcp_tool_names - imported - INLINE_MCP_TOOLS)
    assert unbacked == [], (
        f"MCP tools with no mcp_tools.* import in mcp_server.py: {unbacked}. "
        "Add the import or add to INLINE_MCP_TOOLS if defined directly in mcp_server.py."
    )
```

### Test 5: `test_mcp_tool_modules_have_no_orphaned_functions`

Closes Gap B: detects functions defined in `mcp_tools/*.py` that are never imported by `mcp_server.py` at all. Uses AST to collect all public non-underscore function defs from `mcp_tools/` modules (excluding `__init__.py`, `common.py`, and `trading_helpers.py` which are shared helpers). Compares against the import set.

Note: This is a best-effort heuristic — it catches public functions that look like they should be tools but got orphaned. Private helpers (`_foo`), known non-tool exports, and shared builders consumed by HTTP routes are excluded.

```python
# Public functions in mcp_tools/ that are NOT MCP tools — they are shared builders
# consumed by HTTP routes (routes/positions.py) or other internal callers.
NOT_TOOL_ENTRY_POINTS = {
    "build_ai_recommendations",       # factor_intelligence.py — used by routes/positions.py
    "build_metric_insights",           # metric_insights.py — used by routes/positions.py
    "build_market_events",             # news_events.py — used by routes/positions.py
    "has_market_intelligence_data",    # news_events.py — used by routes/positions.py
}

def _collect_all_public_functions() -> set[str]:
    """Collect all public (non-underscore) function defs from mcp_tools/*.py."""
    mcp_tools_dir = Path("mcp_tools")
    functions = set()
    skip_files = {"__init__.py", "common.py", "trading_helpers.py", "aliases.py"}
    for py_file in sorted(mcp_tools_dir.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name in skip_files:
            continue
        tree = ast.parse(py_file.read_text())
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                functions.add(node.name)
    return functions

def test_mcp_tool_modules_have_no_orphaned_functions():
    defined = _collect_all_public_functions()
    imported = _collect_mcp_server_imports() - UTILITY_IMPORTS
    registry_names = set(get_registry().keys())

    # A function is "covered" if it's imported by mcp_server.py, in the agent registry,
    # or is a known shared builder consumed by HTTP routes
    orphaned = sorted(defined - imported - registry_names - NOT_TOOL_ENTRY_POINTS)
    assert orphaned == [], (
        f"Public functions in mcp_tools/ not imported by mcp_server.py or in agent registry: {orphaned}. "
        "Wire into mcp_server.py, add to agent_registry.py, add to NOT_TOOL_ENTRY_POINTS, "
        "or rename with _ prefix if internal."
    )
```

### Test 4: `test_exclusion_list_matches_registry_comment`

Fixed regex to match Unicode box-drawing delimiters (`─`).

```python
import re

def test_exclusion_list_matches_registry_comment():
    source = Path("services/agent_registry.py").read_text()
    # Match Unicode box-drawing delimiter lines (─)
    block_match = re.search(
        r"# ─{10,}.*?INTENTIONAL EXCLUSIONS.*?# ─{10,}",
        source,
        re.DOTALL,
    )
    assert block_match, "Could not find INTENTIONAL EXCLUSIONS block in agent_registry.py"

    comment_tools = set(re.findall(r"^# (\w+)\s+—", block_match.group(), re.MULTILINE))
    assert comment_tools == EXCLUDED_FROM_REGISTRY, (
        f"EXCLUDED_FROM_REGISTRY does not match agent_registry.py comment. "
        f"In test only: {EXCLUDED_FROM_REGISTRY - comment_tools}. "
        f"In comment only: {comment_tools - EXCLUDED_FROM_REGISTRY}."
    )
```

## Files

| File | Action |
|------|--------|
| `tests/test_tool_surface_sync.py` | **New** — 5 tests |
| `services/agent_registry.py` | **Edit** — add 2 exclusions to comment block (lines 37-38) |

## Verification

```bash
pytest tests/test_tool_surface_sync.py -v
```

All 5 tests should pass green. Regression checks:
- Remove a `_register()` from `agent_registry.py` → Test 1 fails
- Add a `from mcp_tools.foo import bar` without `@mcp.tool()` wrapper → Test 3 fails (direction 1)
- Add an `@mcp.tool()` wrapper with no `mcp_tools.*` import → Test 3 fails (direction 2)
- Add a public function to `mcp_tools/foo.py` without importing in `mcp_server.py` → Test 5 fails
- Add/remove an exclusion from either the test set or the comment block → Test 4 fails
