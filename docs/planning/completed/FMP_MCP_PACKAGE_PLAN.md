# Plan: Ship `fmp-mcp` as a pip-installable package (v2 — restructured)

**Status:** Completed 2026-02-23
**Commit:** `5f1257e9` feat(fmp): restructure as pip-installable fmp-mcp package

## Context

Publish the FMP MCP server from this repo as `fmp-mcp` on PyPI. Package 1 in the release plan.

The previous plan (v1) kept FMP tools in `mcp_tools/` and added 9 import guards to make them work standalone. This v2 plan instead **moves** FMP tools into `fmp/tools/`, creating a self-contained `fmp/` package with zero portfolio dependencies. Cleaner package, fewer guards, no namespace collision with `mcp_tools`.

## New structure

```
fmp/
├── __init__.py              (existing — minor edit)
├── client.py                (existing — no changes)
├── cache.py                 (existing — 2 small fixes)
├── registry.py              (existing — no changes)
├── exceptions.py            (existing — no changes)
├── estimate_store.py        (existing — no changes)
├── server.py                (moved from fmp_mcp_server.py, import paths updated)
└── tools/                   (NEW — moved from mcp_tools/)
    ├── __init__.py           (new, re-exports all tool functions)
    ├── fmp_core.py           (moved from mcp_tools/fmp.py, renamed to avoid fmp.tools.fmp)
    ├── screening.py          (moved from mcp_tools/screening.py)
    ├── peers.py              (moved from mcp_tools/peers.py)
    ├── market.py             (moved from mcp_tools/market.py)
    ├── institutional.py      (moved from mcp_tools/institutional.py)
    ├── insider.py            (moved from mcp_tools/insider.py)
    ├── etf_funds.py          (moved from mcp_tools/etf_funds.py)
    ├── news_events.py        (moved from mcp_tools/news_events.py — FMP functions only)
    ├── technical.py          (moved from mcp_tools/technical.py)
    ├── transcripts.py        (moved from mcp_tools/transcripts.py)
    ├── estimates.py          (moved from mcp_tools/estimates.py)
    └── aliases.py            (copied from mcp_tools/aliases.py — shared utility)
```

## What ships

**19 MCP tools**, **Config:** `FMP_API_KEY` environment variable only.

---

## File moves and edits

### Move 1: `mcp_tools/fmp.py` → `fmp/tools/fmp_core.py`
- Rename to `fmp_core.py` to avoid `fmp.tools.fmp` (confusing).
- Update imports: `from fmp.client` → `from ..client`, `from fmp.exceptions` → `from ..exceptions`, `from fmp.registry` → `from ..registry`

### Move 2: `mcp_tools/screening.py` → `fmp/tools/screening.py`
- Update: `from fmp.client` → `from ..client`

### Move 3: `mcp_tools/peers.py` → `fmp/tools/peers.py`
- Update: `from fmp.client` → `from ..client`

### Move 4: `mcp_tools/market.py` → `fmp/tools/market.py`
- Update: `from fmp.client` → `from ..client`, `from fmp.exceptions` → `from ..exceptions`

### Move 5: `mcp_tools/institutional.py` → `fmp/tools/institutional.py`
- Update: `from fmp.client` → `from ..client`, `from fmp.exceptions` → `from ..exceptions`

### Move 6: `mcp_tools/insider.py` → `fmp/tools/insider.py`
- Update: `from fmp.client` → `from ..client`, `from fmp.exceptions` → `from ..exceptions`

### Move 7: `mcp_tools/etf_funds.py` → `fmp/tools/etf_funds.py`
- Update: `from fmp.client` → `from ..client`, `from fmp.exceptions` → `from ..exceptions`

### Move 8: `mcp_tools/news_events.py` → `fmp/tools/news_events.py`
- **Split required:** `news_events.py` currently contains:
  - `get_news`, `get_events_calendar` — FMP tools → move to `fmp/tools/`
  - `get_portfolio_news`, `get_portfolio_events_calendar` — portfolio wrappers → stay in `mcp_tools/`
  - `_load_portfolio_symbols` — portfolio helper → stays in `mcp_tools/`
- **Action:**
  - Move to `fmp/tools/news_events.py` with ONLY `get_news`, `get_events_calendar`, and their non-portfolio helpers
  - Update: `from fmp.client` → `from ..client`, `from mcp_tools.aliases` → `from .aliases`
  - Remove portfolio auto-fill logic (`_load_portfolio_symbols`) from the moved copy — standalone users pass symbols explicitly
  - Keep `mcp_tools/news_events.py` with portfolio functions. Update it to import FMP functions from new location:
    ```python
    from fmp.tools.news_events import get_news, get_events_calendar
    ```

### Move 9: `mcp_tools/technical.py` → `fmp/tools/technical.py`
- Update: `from fmp.client` → `from ..client`

### Move 10: `mcp_tools/transcripts.py` → `fmp/tools/transcripts.py`
- Update: `from fmp.client` → `from ..client`, `from fmp.exceptions` → `from ..exceptions`
- Fix cache path (Change C below)

### Move 11: `mcp_tools/estimates.py` → `fmp/tools/estimates.py`
- Update: `from fmp.estimate_store` → `from ..estimate_store`
- Guard import (Change D below)

### Move 12: `mcp_tools/aliases.py` → `fmp/tools/aliases.py` (COPY, not move)
- `aliases.py` is also used by `mcp_tools/positions.py` (portfolio tool). Keep the original in `mcp_tools/`.
- The copy in `fmp/tools/` is identical — it's a pure utility with zero imports.

### Move 13: `fmp_mcp_server.py` → `fmp/server.py`
- Update all imports from `mcp_tools.X` → `fmp.tools.X` (and `fmp_core` for the renamed file)
- Guard estimate imports (Change E below)
- Add `main()` entry point (Change E below)
- Keep `fmp_mcp_server.py` as a thin backward-compat wrapper:
  ```python
  from fmp.server import main
  if __name__ == "__main__":
      main()
  ```

---

## Source changes (in existing fmp/ files)

Only 5 changes needed (down from 9 in v1):

### Change A: `fmp/__init__.py` — guard EstimateStore import
**Why:** `psycopg2` hard dep at module level.
```python
try:
    from .estimate_store import EstimateStore
except ImportError:
    EstimateStore = None
```

### Change B: `fmp/cache.py` — inline config constant + fix cache path + add `import os`
**Why:** `utils.config` dep + site-packages write issue.
```python
import os  # add to imports

# Replace line 25:
SERVICE_CACHE_MAXSIZE = int(os.getenv("FMP_CACHE_MAXSIZE", "200"))

# Replace get_cache() function:
def _default_cache_base() -> Path:
    env = os.getenv("FMP_CACHE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    project_root = Path(__file__).parent.parent
    if (project_root / "settings.py").exists():
        return project_root
    xdg = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return Path(xdg) / "fmp-mcp"
```

### Change C: `fmp/tools/transcripts.py` — fix cache path
**Why:** Same site-packages write issue as cache.py.
```python
# Replace lines 122-123:
def _transcript_cache_base() -> Path:
    env = os.getenv("FMP_CACHE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    project_root = Path(__file__).parent.parent.parent
    if (project_root / "settings.py").exists():
        return project_root
    xdg = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return Path(xdg) / "fmp-mcp"

_CACHE_BASE = _transcript_cache_base()
PARSED_CACHE_DIR = _CACHE_BASE / "cache" / "transcripts_parsed"
FILE_OUTPUT_DIR = _CACHE_BASE / "cache" / "file_output"
```
Note: `parent.parent.parent` because file is now at `fmp/tools/transcripts.py` (3 levels to project root).

### Change D: `fmp/tools/estimates.py` — guard EstimateStore import
**Why:** `psycopg2` hard dep.
```python
try:
    from ..estimate_store import EstimateStore
except ImportError:
    EstimateStore = None
```
Both tool functions return error dict if `EstimateStore is None`.

### Change E: `fmp/server.py` — guard estimate imports + add `main()` + fix PID file path
```python
try:
    from fmp.tools.estimates import (
        get_estimate_revisions as _get_estimate_revisions,
        screen_estimate_revisions as _screen_estimate_revisions,
    )
    _HAS_ESTIMATES = True
except ImportError:
    _HAS_ESTIMATES = False

def main():
    _kill_previous_instance()
    mcp.run()

if __name__ == "__main__":
    main()
```
If `_HAS_ESTIMATES` is False, register stubs that return an error dict.

**PID file fix:** `_kill_previous_instance()` writes PID files next to `__file__`. After moving to `fmp/server.py`, this resolves to `site-packages/fmp/` in standalone installs (not writable). Fix: use a temp directory instead.
```python
# Before:
server_dir = Path(__file__).resolve().parent

# After:
import tempfile
server_dir = Path(tempfile.gettempdir()) / "fmp-mcp"
server_dir.mkdir(exist_ok=True)
```

---

## Monorepo backward compatibility

After the moves, update these consumers:

1. **`fmp_mcp_server.py`** — thin wrapper: `from fmp.server import main`
2. **`mcp_tools/__init__.py`** — update FMP imports to `fmp.tools.*`:
   ```python
   from fmp.tools.screening import screen_stocks
   from fmp.tools.peers import compare_peers
   from fmp.tools.market import get_economic_data, get_sector_overview, get_market_context
   from fmp.tools.news_events import get_news, get_events_calendar
   from fmp.tools.technical import get_technical_analysis
   from fmp.tools.transcripts import get_earnings_transcript
   ```
3. **`mcp_tools/news_events.py`** — keep portfolio functions, import FMP functions from `fmp.tools.news_events`
4. **`mcp_server.py`** (portfolio-mcp) — no changes needed (imports from `mcp_tools/news_events` which still exists)
5. **Test files** — update imports from `mcp_tools.X` to `fmp.tools.X`:
   - `tests/mcp_tools/test_peers.py`
   - `tests/mcp_tools/test_screening.py`
   - `tests/mcp_tools/test_market.py`
   - `tests/mcp_tools/test_market_calendar_country_filter.py`
   - `tests/mcp_tools/test_etf_funds.py`
   - `tests/mcp_tools/test_news_events.py`
   - `tests/mcp_tools/test_institutional.py`
   - `tests/mcp_tools/test_insider.py`
   - `tests/mcp_tools/test_technical.py`
   - `tests/mcp_tools/test_estimates.py`
   - `tests/mcp_tools/test_brokerage_aliases.py` — no change (tests mcp_tools/aliases.py which stays)

---

## pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "fmp-mcp"
version = "0.1.0"
description = "MCP server for Financial Modeling Prep — 19 tools for market data via Claude"
readme = "README_PACKAGE.md"
license = "MIT"
requires-python = ">=3.11"
dependencies = [
    "requests",
    "pandas",
    "pyarrow",
    "python-dotenv",
    "fastmcp",
    "zstandard",
]

[project.optional-dependencies]
estimates = ["psycopg2-binary"]

[project.scripts]
fmp-mcp = "fmp.server:main"

[tool.hatch.build.targets.wheel]
packages = ["fmp"]
exclude = ["fmp/compat.py", "fmp/fx.py", "fmp/scripts/"]

[tool.hatch.build.targets.sdist]
include = ["fmp/", "pyproject.toml", "README_PACKAGE.md", "LICENSE"]
exclude = ["fmp/compat.py", "fmp/fx.py", "fmp/scripts/"]
```

Much cleaner: `packages = ["fmp"]` with a short exclude list.

---

## Steps

### Step 1: Create `fmp/tools/` directory + `__init__.py`

### Step 2: Move 12 files from `mcp_tools/` to `fmp/tools/`
- Move files, update internal imports to relative (`from ..client`, `from ..exceptions`, etc.)
- Rename `fmp.py` → `fmp_core.py`
- Split `news_events.py` (FMP functions move, portfolio functions stay)
- Copy `aliases.py` (keep original in `mcp_tools/`)

### Step 3: Move `fmp_mcp_server.py` → `fmp/server.py`
- Update imports, add `main()`, guard estimate imports
- Leave thin wrapper at `fmp_mcp_server.py`

### Step 4: Apply 5 source changes (A-E)
- Guard psycopg2 imports, fix cache paths, inline config constant

### Step 5: Update monorepo consumers
- `mcp_tools/__init__.py`, `mcp_tools/news_events.py`, test files

### Step 6: Add `pyproject.toml`, `README_PACKAGE.md`, `LICENSE`

### Step 7: Update existing test suites
All test files under `tests/mcp_tools/` that import from the moved modules must be updated.
Change imports from `from mcp_tools.X import ...` to `from fmp.tools.X import ...`.

**Files to update (10 total):**
- `tests/mcp_tools/test_peers.py` — `from mcp_tools.peers` → `from fmp.tools.peers`
- `tests/mcp_tools/test_screening.py` — `from mcp_tools.screening` → `from fmp.tools.screening`
- `tests/mcp_tools/test_market.py` — `from mcp_tools.market` → `from fmp.tools.market`
- `tests/mcp_tools/test_market_calendar_country_filter.py` — `from mcp_tools import market` → `from fmp.tools import market`
- `tests/mcp_tools/test_etf_funds.py` — `from mcp_tools.etf_funds` → `from fmp.tools.etf_funds`
- `tests/mcp_tools/test_news_events.py` — `from mcp_tools.news_events` → `from fmp.tools.news_events`
- `tests/mcp_tools/test_institutional.py` — `from mcp_tools.institutional` → `from fmp.tools.institutional`
- `tests/mcp_tools/test_insider.py` — `from mcp_tools.insider` → `from fmp.tools.insider`
- `tests/mcp_tools/test_technical.py` — `from mcp_tools.technical` → `from fmp.tools.technical`
- `tests/mcp_tools/test_estimates.py` — `from mcp_tools import estimates` → `from fmp.tools import estimates`

**IMPORTANT: Also update `@patch` / `patch()` targets in these test files.**
Many tests mock functions using the old module path (e.g., `@patch("mcp_tools.peers._fetch_ratios")`).
These must ALL be updated to the new path (e.g., `@patch("fmp.tools.peers._fetch_ratios")`).
Search each file for all occurrences of `mcp_tools.` in patch strings and update to `fmp.tools.`.

**Files that stay unchanged:**
- `tests/mcp_tools/test_brokerage_aliases.py` — tests `mcp_tools/aliases.py` which stays
- `tests/mcp_tools/test_news_events_portfolio.py` — tests portfolio functions which stay in `mcp_tools/`

**Run the full existing test suite after updates:**
```bash
python3 -m pytest tests/mcp_tools/ -v
```

### Step 8: Create FMP MCP smoke test

Create `tests/mcp_tools/test_fmp_mcp_smoke.py` — an end-to-end smoke test that imports the
FMP MCP server and verifies all 19 tools are registered and callable.

**What it tests:**
1. `fmp.server` module imports without error
2. All 19 tools are registered on the FastMCP server instance
3. Each tool function is callable and returns a dict with `"status"` key
4. Estimate tools gracefully return error when psycopg2/Postgres unavailable (not crash)
5. Server `main()` entry point exists and is callable

**Approach — test the tool functions directly (not via MCP protocol):**
Each tool in `fmp_mcp_server.py` (now `fmp/server.py`) is a thin wrapper that calls the
underlying `fmp.tools.*` function. Test by importing the underlying functions from
`fmp.tools.*` and calling them with minimal valid args, mocking `FMPClient.fetch` to
avoid real API calls.

```python
"""Smoke test: all 19 FMP MCP tools import and return structured responses."""

import os
os.environ.setdefault("FMP_API_KEY", "test_api_key")

import pytest
from unittest.mock import patch, MagicMock
import pandas as pd

# --- Import verification: all tool modules import from fmp.tools ---

def test_fmp_core_imports():
    from fmp.tools.fmp_core import fmp_fetch, fmp_search, fmp_profile, fmp_list_endpoints, fmp_describe
    assert all(callable(f) for f in [fmp_fetch, fmp_search, fmp_profile, fmp_list_endpoints, fmp_describe])

def test_screening_imports():
    from fmp.tools.screening import screen_stocks
    assert callable(screen_stocks)

def test_peers_imports():
    from fmp.tools.peers import compare_peers
    assert callable(compare_peers)

def test_market_imports():
    from fmp.tools.market import get_economic_data, get_sector_overview, get_market_context
    assert all(callable(f) for f in [get_economic_data, get_sector_overview, get_market_context])

def test_institutional_imports():
    from fmp.tools.institutional import get_institutional_ownership
    assert callable(get_institutional_ownership)

def test_insider_imports():
    from fmp.tools.insider import get_insider_trades
    assert callable(get_insider_trades)

def test_etf_funds_imports():
    from fmp.tools.etf_funds import get_etf_holdings
    assert callable(get_etf_holdings)

def test_news_events_imports():
    from fmp.tools.news_events import get_news, get_events_calendar
    assert all(callable(f) for f in [get_news, get_events_calendar])

def test_technical_imports():
    from fmp.tools.technical import get_technical_analysis
    assert callable(get_technical_analysis)

def test_transcripts_imports():
    from fmp.tools.transcripts import get_earnings_transcript
    assert callable(get_earnings_transcript)

def test_estimates_imports():
    from fmp.tools.estimates import get_estimate_revisions, screen_estimate_revisions
    assert all(callable(f) for f in [get_estimate_revisions, screen_estimate_revisions])

# --- Functional tests: tools return dict with status ---

def test_fmp_list_endpoints_returns_success():
    from fmp.tools.fmp_core import fmp_list_endpoints
    result = fmp_list_endpoints()
    assert isinstance(result, dict)
    assert result["status"] == "success"
    assert result["endpoint_count"] > 0

def test_fmp_describe_returns_success():
    from fmp.tools.fmp_core import fmp_describe
    result = fmp_describe("income_statement")
    assert isinstance(result, dict)
    assert result["status"] == "success"

@patch("fmp.client.FMPClient.fetch")
def test_fmp_fetch_returns_dict(mock_fetch):
    mock_fetch.return_value = pd.DataFrame({"symbol": ["AAPL"], "price": [150.0]})
    from fmp.tools.fmp_core import fmp_fetch
    result = fmp_fetch(endpoint="profile", symbol="AAPL")
    assert isinstance(result, dict)
    assert "status" in result

def test_estimate_revisions_graceful_without_postgres():
    """Estimate tools should return error dict, not crash, when Postgres unavailable."""
    from fmp.tools.estimates import get_estimate_revisions
    result = get_estimate_revisions(ticker="AAPL")
    assert isinstance(result, dict)
    # Should either succeed (if Postgres running) or return status=error (not crash)
    assert "status" in result

# --- Server module tests ---

def test_server_module_imports():
    """fmp.server module imports without error."""
    import fmp.server  # should not raise

def test_server_has_main():
    """fmp.server exposes main() entry point."""
    from fmp.server import main
    assert callable(main)

def test_server_has_mcp_instance():
    """fmp.server has FastMCP instance with tools registered."""
    from fmp.server import mcp
    assert mcp is not None

EXPECTED_TOOLS = sorted([
    "fmp_fetch", "fmp_search", "fmp_profile", "fmp_list_endpoints", "fmp_describe",
    "screen_stocks", "compare_peers", "get_technical_analysis",
    "get_economic_data", "get_sector_overview", "get_market_context",
    "get_institutional_ownership", "get_insider_trades", "get_etf_holdings",
    "get_news", "get_events_calendar", "get_earnings_transcript",
    "get_estimate_revisions", "screen_estimate_revisions",
])

def test_server_registers_all_19_tools():
    """All 19 MCP tools are registered on the FastMCP server."""
    from fmp.server import mcp
    # FastMCP stores tools in mcp._tool_manager._tools dict
    registered = sorted(mcp._tool_manager._tools.keys())
    missing = set(EXPECTED_TOOLS) - set(registered)
    extra = set(registered) - set(EXPECTED_TOOLS)
    assert not missing, f"Missing tools: {missing}"
    assert not extra, f"Unexpected tools: {extra}"
    assert len(registered) == 19
```

**Run the smoke test:**
```bash
python3 -m pytest tests/mcp_tools/test_fmp_mcp_smoke.py -v
```

**Run ALL FMP-related tests together (smoke + existing unit tests):**
```bash
python3 -m pytest tests/mcp_tools/ -v
```

### Step 9: Verify monorepo integration
After all changes, verify the monorepo still works end-to-end:

```bash
# 1. All MCP tool tests pass (376+ tests)
python3 -m pytest tests/mcp_tools/ -v

# 2. FMP smoke test passes (all 19 tools import, register, respond)
python3 -m pytest tests/mcp_tools/test_fmp_mcp_smoke.py -v

# 3. FMP import check — all tool modules load cleanly
python3 -c "
from fmp.tools.fmp_core import fmp_fetch, fmp_search, fmp_profile, fmp_list_endpoints, fmp_describe
from fmp.tools.screening import screen_stocks
from fmp.tools.peers import compare_peers
from fmp.tools.market import get_economic_data, get_sector_overview, get_market_context
from fmp.tools.institutional import get_institutional_ownership
from fmp.tools.insider import get_insider_trades
from fmp.tools.etf_funds import get_etf_holdings
from fmp.tools.news_events import get_news, get_events_calendar
from fmp.tools.technical import get_technical_analysis
from fmp.tools.transcripts import get_earnings_transcript
from fmp.tools.estimates import get_estimate_revisions, screen_estimate_revisions
print('OK: all 19 tool functions import')
"

# 4. Server module loads with all 19 tools registered
python3 -c "
from fmp.server import mcp, main
tools = list(mcp._tool_manager._tools.keys())
print(f'OK: server loads with {len(tools)} tools: {sorted(tools)}')
assert len(tools) == 19, f'Expected 19 tools, got {len(tools)}'
"

# 5. Backward compat wrapper still works
python3 -c "from fmp_mcp_server import main; print('OK: fmp_mcp_server.py wrapper works')"

# 6. Portfolio MCP server still loads (imports from mcp_tools/news_events)
python3 -c "
from mcp_tools.news_events import get_portfolio_news, get_portfolio_events_calendar, get_news, get_events_calendar
print('OK: mcp_tools/news_events.py intact (portfolio + FMP re-exports)')
"

# 7. mcp_tools.__init__ still exports all FMP tools (via fmp.tools)
python3 -c "
from mcp_tools import screen_stocks, compare_peers, get_news, get_events_calendar
from mcp_tools import get_economic_data, get_sector_overview, get_market_context
from mcp_tools import get_technical_analysis, get_earnings_transcript
print('OK: mcp_tools re-exports all FMP tools')
"

# 8. Portfolio-mcp server file still imports correctly
python3 -c "
import mcp_server  # portfolio-mcp — should not raise
print('OK: mcp_server.py (portfolio-mcp) imports cleanly')
"
```

### Step 10: Publish
- Tag `v0.1.0`, `python -m build && twine upload dist/*`

---

## Known limitations (v0.1.0, accepted)
1. **`fmp` package name** — generic, potential collision. Mitigated by `uvx` isolation.
2. **Estimate revision tools** require optional `psycopg2` + Postgres. Gracefully error when unavailable.
3. **News/events portfolio auto-fill** not available in standalone. Users pass symbols explicitly.
4. **EstimateStore write-mode** references `fmp/scripts/` (excluded). Read-mode works fine standalone.
