# ibkr-mcp: Self-Contained Package Extraction

**Status:** Completed 2026-02-23
**Commit:** `ff8a1836`

## Context

Make `ibkr/` a self-contained package that can run as a standalone MCP server, while staying in the monorepo so the rest of risk_module imports from it with zero code duplication. Follows the same pattern as the fmp-mcp extraction.

**Result:** `ibkr/` is fully self-contained. `ibkr/server.py` is the MCP server. `~/.claude.json` uses `python -m ibkr.server`. 103 tests passing, 6/6 tools verified live against IB Gateway. All monorepo consumers work unchanged.

---

## Strategy: Create 4 Internal Shims, Rewire 8 Modules

The ibkr package has 3 categories of external dependency to eliminate:

| Dependency | Used by | Solution |
|-----------|---------|----------|
| `settings.py` (6 IBKR_* vars) | connection.py, market_data.py, client.py | New `ibkr/config.py` — loads .env then reads env vars |
| `utils.logging` (2 loggers) | connection.py, market_data.py, contracts.py, compat.py, flex.py | New `ibkr/_logging.py` — fallback to stdlib logging |
| `trading_analysis.instrument_meta` (type + function) | contracts.py, profiles.py, flex.py | New `ibkr/_types.py` — vendor the 34-line module |
| `trading_analysis.models/symbol_utils` + `utils.ticker_resolver` | flex.py only | New `ibkr/_vendor.py` + guarded import |

---

## Implementation Steps

### Phase 1: Create shims (4 new files, no existing code touched)

**1. `ibkr/config.py`** — Env-var config replacing `settings.py` imports

Must auto-load `.env` to match `settings.py` behavior (which calls `load_dotenv()` on import). Without this, monorepo scripts like `run_ibkr_data.py` and `run_options.py` that previously got `.env` values via `settings.py` would lose them.

```python
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Load from ibkr/ dir first, then parent (monorepo root)
    _pkg_dir = Path(__file__).resolve().parent
    load_dotenv(_pkg_dir / ".env", override=False)
    load_dotenv(_pkg_dir.parent / ".env", override=False)
except Exception:
    pass

IBKR_GATEWAY_HOST: str = os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1")
IBKR_GATEWAY_PORT: int = int(os.getenv("IBKR_GATEWAY_PORT", "7496"))
IBKR_CLIENT_ID: int = int(os.getenv("IBKR_CLIENT_ID", "1"))
IBKR_TIMEOUT: int = int(os.getenv("IBKR_TIMEOUT", "10"))
IBKR_READONLY: bool = os.getenv("IBKR_READONLY", "false").lower() == "true"
IBKR_AUTHORIZED_ACCOUNTS: list[str] = [
    a.strip() for a in os.getenv("IBKR_AUTHORIZED_ACCOUNTS", "").split(",") if a.strip()
]
```

**2. `ibkr/_logging.py`** — Logging with monorepo fallback

Catch `Exception` (not just `ImportError`) to handle cases where `utils.logging` exists but fails to initialize.

```python
import logging, sys

def _make_fallback_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"ibkr.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

try:
    from utils.logging import portfolio_logger, trading_logger
except Exception:
    portfolio_logger = _make_fallback_logger("portfolio")
    trading_logger = _make_fallback_logger("trading")
```

**3. `ibkr/_types.py`** — Vendored `InstrumentType` + `coerce_instrument_type` (34 lines from `trading_analysis/instrument_meta.py`)

**4. `ibkr/_vendor.py`** — Vendored `safe_float` + `normalize_strike` (used only by flex.py)

### Phase 2: Rewire existing modules (8 files, import-line changes only)

| File | Change |
|------|--------|
| `ibkr/connection.py` | `from settings import ...` → `from .config import ...`; `from utils.logging` → `from ._logging` |
| `ibkr/market_data.py` | Same pattern as connection.py |
| `ibkr/client.py` | `import settings` → `from .config import IBKR_AUTHORIZED_ACCOUNTS` |
| `ibkr/contracts.py` | `from trading_analysis.instrument_meta` → `from ._types`; `from utils.logging` → `from ._logging` |
| `ibkr/profiles.py` | `from trading_analysis.instrument_meta` → `from ._types` |
| `ibkr/compat.py` | `from utils.logging` → `from ._logging` |
| `ibkr/flex.py` | All 5 external imports → vendored/guarded equivalents. `resolve_fmp_ticker` fallback should accept kwargs and log a warning when active. |
| `ibkr/cache.py` | Harden `_project_root()` — use `IBKR_CACHE_DIR` env var → monorepo detection (check for `settings.py` in parent) → `~/.cache/ibkr-mcp` fallback (matching fmp pattern). |

### Phase 3: Move the MCP server

**1. Create `ibkr/server.py`** — Move tool definitions from root `ibkr_mcp_server.py` into the package. Add `_kill_previous_instance()` (matching fmp pattern), add `main()` entry point. Uses `from .client import IBKRClient` (relative imports). **Must preserve stdout/stderr MCP safety** — the current server redirects `sys.stdout` to `sys.stderr` before imports (line 15-20) and wraps every tool call with `_with_stderr_stdout()` (line 28-34) to prevent accidental stdout output from corrupting MCP JSON-RPC. Both patterns must be carried over to `ibkr/server.py`.

**2. Delete root `ibkr_mcp_server.py`** — no wrapper needed.

**3. Update docs referencing old entrypoint** — replace `ibkr_mcp_server.py` with `ibkr/server.py` / `python -m ibkr.server` in:
- `docs/interfaces/README.md`
- `docs/interfaces/mcp.md`
- `docs/reference/MCP_SERVERS.md`
- `docs/reference/API_REFERENCE.md`
- `docs/reference/DATABASE_REFERENCE.md`
- `docs/guides/usage_notes.md`
- `docs/reference/ENVIRONMENT_SETUP.md`
- `docs/guides/DEVELOPER_ONBOARDING.md`
- `mcp_tools/README.md`
- `readme.md`
- `AI_CONTEXT.md`
- `docs/guides/BROKERAGE_ADMIN.md`
- `docs/architecture/FRONTEND_BACKEND_CONNECTION_MAP.md`

Note: Historical/archived docs (e.g. `docs/architecture/legacy/`) are intentionally excluded — they describe past state and don't need updating. Use `grep -rn "ibkr_mcp_server" docs/ *.md` after migration to catch any remaining stragglers.

**4. Update `~/.claude.json`** — use `python -m ibkr.server` (NOT `python ibkr/server.py`, which breaks relative imports):
```json
"ibkr-mcp": {
  "type": "stdio",
  "command": "python3",
  "args": ["-m", "ibkr.server"],
  "env": {}
}
```

### Phase 4: Package metadata

**1. `ibkr/pyproject.toml`** — Standalone build config. Uses Hatch's `root = ".."` to build from the parent directory so `ibkr/` is a proper top-level package in the wheel:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ibkr-mcp"
version = "0.1.0"
description = "MCP server for Interactive Brokers Gateway - 6 tools for market data and account access via Claude"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
dependencies = [
    "ib_async",
    "nest_asyncio",
    "pandas",
    "pyarrow",
    "pyyaml",
    "python-dotenv",
    "fastmcp",
    "certifi",
    "zstandard",
]

[project.scripts]
ibkr-mcp = "ibkr.server:main"

[tool.hatch.build.targets.wheel]
# Build from parent so "ibkr" is a proper top-level package in the wheel
root = ".."
packages = ["ibkr"]

[tool.hatch.build.targets.sdist]
root = ".."
include = ["ibkr/", "ibkr/pyproject.toml", "ibkr/README.md"]
```

Install with `pip install -e ./ibkr/` from monorepo root (or `pip install ibkr-mcp` once published).

`exchange_mappings.yaml` is automatically included since Hatch includes all non-Python files in the package directory by default. Verify with `hatch build` that the YAML is in the wheel.

**2. `ibkr/README.md`** — 6 tools, env var config, Claude Code setup, IB Gateway prerequisites

---

## Files Unchanged (7 of 14 modules need no edits)

`__init__.py`, `account.py`, `capabilities.py`, `exceptions.py`, `locks.py`, `metadata.py`, `exchange_mappings.yaml`

## Monorepo Consumers (complete inventory — no changes needed to any)

All import from `ibkr.*` submodules which will still work after the rewiring:

**Services & core:**
- `services/ibkr_broker_adapter.py` → `IBKRConnectionManager`, `ibkr_shared_lock`
- `services/cache_adapters.py` → `ibkr.cache.clear_disk_cache`, `disk_cache_stats`
- `providers/ibkr_price.py` → `fetch_ibkr_*_monthly_close` from `ibkr.compat`
- `providers/symbol_resolution.py` → `get_ibkr_futures_fmp_map`
- `core/realized_performance_analysis.py` → compat functions
- `core/data_objects.py` → `get_ibkr_futures_exchanges`
- `portfolio_risk.py` → `get_futures_currency`, `get_ibkr_futures_exchanges`
- `trading_analysis/data_fetcher.py` → `fetch_ibkr_flex_payload`

**Tools & scripts:**
- `mcp_tools/options.py` → `IBKRClient`
- `options/analyzer.py` → `resolve_option_contract`
- `run_ibkr_data.py` → `IBKRClient`, `get_profiles`, `get_ibkr_futures_exchanges`
- `run_options.py` → `IBKRClient`
- `scripts/fetch_ibkr_trades.py` → `normalize_flex_trades`

**Tests:**
- `tests/ibkr/` (5 files) — `test_client.py`, `test_market_data.py`, `test_cache.py`, `test_flex.py`, `test_compat.py`
- `tests/services/test_cache_control.py` → `ibkr.cache`
- `tests/core/test_portfolio_risk.py`, `tests/providers/test_provider_switching.py` (indirect)
- `tests/trading_analysis/test_instrument_tagging.py` → `ibkr.flex`
- `tests/providers/test_transaction_providers.py`, `tests/unit/test_positions_data.py` (indirect)

---

## Verification

Run after each phase and fix any failures before moving to the next phase.

### After Phase 2 (rewiring): Core correctness
1. **`pytest tests/ibkr/ -v`** — all 5 ibkr test files pass
2. **`pytest tests/ -v`** — full test suite passes (catches breakage in indirect consumers like `test_portfolio_risk.py`, `test_instrument_tagging.py`, `test_cache_control.py`, `test_transaction_providers.py`, etc.)
3. **Grep for stale imports** inside `ibkr/` (exclude shims):
   ```bash
   grep -rn "from settings \|import settings" ibkr/ --include='*.py' | grep -v _logging | grep -v config  # should be empty
   grep -rn "from utils\." ibkr/ --include='*.py' | grep -v _logging  # should be empty
   grep -rn "from trading_analysis" ibkr/ --include='*.py' | grep -v _types | grep -v _vendor  # should be empty
   ```

### After Phase 3 (server migration): Import + runtime checks
4. **Import smoke tests** — verify all key entry points resolve:
   ```bash
   python -c "from ibkr import IBKRClient"
   python -c "from ibkr.compat import fetch_ibkr_monthly_close"
   python -c "from ibkr.connection import IBKRConnectionManager"
   python -c "from ibkr.server import main"
   python -c "from ibkr.flex import normalize_flex_trades"
   python -c "from ibkr.cache import get_cached, put_cache"
   ```
5. **Server startup:** `python -m ibkr.server` starts correctly (NOT `python ibkr/server.py`)
6. **`pytest tests/ -v`** — full suite again after server move + root file deletion

### After Phase 4 (packaging): End-to-end
7. **Package build smoke test:**
   ```bash
   cd ibkr && pip install -e . && python -c "from ibkr.server import main; print('OK')"
   ```
   Verify `exchange_mappings.yaml` is in the installed package.
8. **Doc reference check:**
   ```bash
   grep -rn "ibkr_mcp_server" docs/ *.md  # should be empty (except archived/legacy docs)
   ```

---

## Key Design Decisions

- **`config.py` auto-loads `.env`** — matches `settings.py` behavior so monorepo scripts (`run_ibkr_data.py`, `run_options.py`) keep getting env values without changes.
- **`cache.py` gets hardened cache path** — env var `IBKR_CACHE_DIR` → monorepo detection (parent has `settings.py`) → `~/.cache/ibkr-mcp` fallback. Prevents write failures if installed as site-package.
- **`flex.py` stays in package** with guarded imports. `resolve_fmp_ticker` fallback accepts kwargs, logs a warning, returns ticker unchanged. Flex tools aren't exposed as MCP tools — they're monorepo-only.
- **`compat.py` stays in package** — after rewiring to `_logging.py`, it has no external deps.
- **No changes to `ibkr/__init__.py`** — once upstream modules are rewired, existing public API imports resolve cleanly.
- **`pyproject.toml` goes inside `ibkr/`** (not root) since root already has fmp-mcp's pyproject.toml.
- **No root wrapper** — delete `ibkr_mcp_server.py`, use `python -m ibkr.server` in `~/.claude.json`.
- **`exchange_mappings.yaml` included as package-data** — loaded via `Path(__file__).with_name()` so it must ship with the package.
- **`_logging.py` catches `Exception`** not just `ImportError` — handles cases where `utils.logging` exists but fails to initialize.

---

## Implementation Notes

- **`python -m ibkr.server` requires CWD to be the monorepo root** (so Python can find the `ibkr` package on `sys.path`). This is the same constraint as today — Claude Code launches from risk_module. The `~/.claude.json` registration should include `"cwd"` if needed.
- **`ibkr/server.py` imports must be relative for internal modules** (`from .client import IBKRClient`) **but stay absolute for external packages** (`from ib_async import Option, Contract, Stock`). The current server has lazy `from ib_async import ...` inside tool functions — keep those as-is.
- **`config.py` constants are evaluated once at import time** — same as `settings.py` today. Not a regression, but means `.env` must be loadable before first import of `ibkr.config`.
- **Test the Hatch `root = ".."` build early** — run `cd ibkr && pip install -e .` right after creating `pyproject.toml` to confirm the layout works. If Hatch can't resolve the parent, fallback: move pyproject.toml to repo root (swap with fmp's).
