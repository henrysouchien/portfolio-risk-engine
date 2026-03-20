# Portfolio-MCP Extraction Plan

> **Status**: PLANNED
> **Created**: 2026-03-19
> **Parent docs**: `docs/OPEN_SOURCE_LAUNCH_GAPS.md` (B4), `docs/OPEN_SOURCE_LAUNCH_STRATEGY.md`
> **Tracking ID**: B4
> **Predecessor extractions**: `fmp-mcp` (PyPI v0.3.1), `app-platform` (PyPI v0.2.1), `web-app-platform` (npm v0.1.0)

---

## Goal

Extract the portfolio-mcp server (`mcp_server.py` + `mcp_tools/` + transitive dependencies) into a standalone, pip-installable package that a user can install and run with Claude Code (or any MCP client) without cloning the monorepo.

```
pip install portfolio-mcp
claude mcp add portfolio-mcp -e RISK_MODULE_USER_EMAIL=you@example.com -e FMP_API_KEY=xxx -- portfolio-mcp
```

The monorepo remains the authoritative source. The standalone package is a sync artifact, following the same pattern as `fmp-mcp`.

---

## Current Architecture

### Server

`mcp_server.py` (2,565 lines) registers **75 `@mcp.tool()` functions** on a FastMCP server. Each tool is a thin wrapper that delegates to an implementation function in `mcp_tools/`.

### Tool Modules

`mcp_tools/` contains **40 Python modules** (~17,500 lines total):

| Module | Tools | Key dependencies |
|--------|-------|-----------------|
| `positions.py` | get_positions, export_holdings | services.position_service, core.result_objects, core.position_flags |
| `risk.py` | get_risk_score, get_risk_analysis, get_leverage_capacity, set_risk_profile, get_risk_profile | portfolio_risk_engine.*, inputs.risk_limits_manager, services.factor_proxy_service |
| `performance.py` | get_performance | services.performance_helpers, portfolio_risk_engine.performance_metrics_engine |
| `trading_analysis.py` | get_trading_analysis | trading_analysis.*, providers.csv_transactions |
| `factor_intelligence.py` | get_factor_analysis, get_factor_recommendations | services.factor_intelligence_service |
| `optimization.py` | run_optimization, get_efficient_frontier | portfolio_risk_engine.optimization, services.optimization_service |
| `whatif.py` | run_whatif | services.scenario_service |
| `backtest.py` | run_backtest | portfolio_risk_engine.backtest_engine |
| `income.py` | get_income_projection | services.position_snapshot_cache |
| `tax_harvest.py` | suggest_tax_loss_harvest | trading_analysis.*, providers.csv_transactions |
| `signals.py` | check_exit_signals | portfolio_risk_engine.exit_signals |
| `stock.py` | analyze_stock | services.stock_service |
| `options.py` | analyze_option_strategy | options.* |
| `chain_analysis.py` | analyze_option_chain | options.chain_analysis, ib_async |
| `hedge_monitor.py` | monitor_hedge_positions | options.portfolio_greeks |
| `trading.py` | preview_trade, execute_trade, get_orders, cancel_order | services.trade_execution_service |
| `baskets.py` | 7 basket tools | database, fmp.client, portfolio_risk_engine.* |
| `basket_trading.py` | preview/execute_basket_trade | services.trade_execution_service |
| `rebalance.py` | generate_rebalance_trades | services.trade_execution_service |
| `transactions.py` | 8 transaction store tools | inputs.transaction_store |
| `portfolio_management.py` | list_accounts, list_portfolios, create/update/delete_portfolio, account_activate/deactivate | inputs.database_client |
| `audit.py` | record/update/get workflow actions | inputs.database_client |
| `allocation.py` | set/get_target_allocation | inputs.portfolio_repository |
| `import_portfolio.py` | import_portfolio | providers.csv_positions, inputs.normalizers |
| `import_transactions.py` | import_transactions | providers.csv_transactions, inputs.transaction_normalizers |
| `normalizer_builder.py` | 5 normalizer tools | inputs.position_schema |
| `news_events.py` | get_portfolio_news, get_portfolio_events_calendar | fmp.tools.* |
| `instrument_config.py` | manage_instrument_config | inputs.database_client |
| `user_overrides.py` | manage_ticker_config | inputs.database_client |
| `quote.py` | get_quote | fmp.client |
| `futures_curve.py` | get_futures_curve | (internal) |
| `futures_roll.py` | preview/execute_futures_roll | (via trading.py) |
| `multi_leg_options.py` | preview/execute_option_trade | options.* |
| `compare.py` | compare_scenarios | services.scenario_service |
| `metric_insights.py` | (internal helper — not directly registered) | services.portfolio.* |
| `common.py` | (decorators + helpers) | utils.logging, database, app_platform.db |
| `aliases.py` | (helper) | trading_analysis.data_fetcher |
| `trading_helpers.py` | (helper) | fmp.client |

### Transitive Dependency Graph

The full import closure from `mcp_tools/` touches these internal packages:

```
mcp_tools/
  -> core/                        (result objects, flags, analysis modules)
  -> portfolio_risk_engine/       (risk math, optimization, backtest, factor utils)
  -> services/                    (service layer — portfolio, position, factor, scenario, stock, trade)
  -> providers/                   (brokerage adapters, CSV, FMP price, routing)
  -> inputs/                      (risk limits, portfolio manager, normalizers, DB client, transaction store)
  -> database/                    (connection pool, session, is_db_available)
  -> trading_analysis/            (FIFO, analyzers, data fetcher)
  -> options/                     (option analyzer, chain analysis, greeks)
  -> utils/                       (logging, user context, date utils, serialization, ticker resolver)
  -> config/                      (YAML files: risk limits, portfolio, ETF mappings)
  -> settings.py                  (PORTFOLIO_DEFAULTS, feature flags, provider config)
  -> app_platform/                (db pool, logging, auth — via database/ and common.py)
  -> fmp/                         (FMP client, tools — for quote, news, events)
  -> ibkr/                        (IBKR client — for chain analysis, trading, positions)
  -> brokerage/                   (trade objects — for audit)
  -> models/                      (factor intelligence DB models — for baskets)
```

**This is the core challenge**: portfolio-mcp is not a leaf package. It is an orchestration layer that touches nearly every part of the codebase.

---

## Package Boundary Decision

### What goes IN the standalone package

Everything needed to run the MCP server:

1. **`mcp_tools/`** — all 40 modules, wholesale
2. **`core/`** — result objects, flags, analysis modules
3. **`portfolio_risk_engine/`** — risk math engine (already published as separate PyPI package, but the standalone package needs it as a dependency or vendored)
4. **`services/`** — service layer
5. **`providers/`** — brokerage adapters, CSV position/transaction providers, routing
6. **`inputs/`** — normalizers, risk limits manager, portfolio manager, DB client
7. **`database/`** — connection pool, session management, `is_db_available()`
8. **`trading_analysis/`** — FIFO matcher, analyzer, data fetcher
9. **`options/`** — option analyzer, chain analysis, portfolio greeks
10. **`utils/`** — shared utilities
11. **`config/`** — YAML configuration files
12. **`settings.py`** — settings module
13. **`models/`** — SQLAlchemy models (subset used by baskets/factor intelligence)

### What stays OUT (monorepo-only)

1. **`app.py`** — FastAPI web application
2. **`routes/`** — REST API endpoints
3. **`frontend/`** — React web app
4. **`fmp/`** — fmp-mcp is its own package (listed as dependency)
5. **`ibkr/`** — ibkr-mcp is its own package (listed as optional dependency)
6. **`app_platform/`** — app-platform is its own package (listed as dependency)
7. **`scripts/`** — monorepo operational scripts
8. **`tests/`** — monorepo test suite (standalone package gets its own test subset)
9. **`docs/`** — monorepo docs
10. **`user_data/`** — local user data files

### Dependency Strategy

Rather than vendoring everything, the standalone package declares published PyPI packages as dependencies:

```
portfolio-risk-engine >= 0.1.0    # Risk math (already on PyPI)
fmp-mcp >= 0.3.0                  # FMP data tools (already on PyPI)
app-platform >= 0.2.0             # DB pool, logging (already on PyPI)
brokerage-connect >= 0.2.0        # Brokerage adapters (already on PyPI)
```

The remaining internal code (`core/`, `services/`, `providers/`, `inputs/`, `trading_analysis/`, `options/`, `utils/`, `database/`, `config/`, `models/`) ships as part of the `portfolio_mcp` package itself.

---

## Package Structure

```
portfolio-mcp-dist/
  pyproject.toml
  README.md
  LICENSE
  portfolio_mcp/
    __init__.py
    __main__.py                    # `python -m portfolio_mcp`
    server.py                      # FastMCP server (from mcp_server.py)
    settings.py                    # Package-level settings
    tools/                         # From mcp_tools/ (renamed to avoid collision)
      __init__.py
      common.py
      positions.py
      risk.py
      performance.py
      ... (all 40 modules)
    core/                          # From core/
      __init__.py
      result_objects/
      position_flags.py
      ...
    engine/                        # From portfolio_risk_engine/ (or as dep)
      ... OR just declare as PyPI dependency
    services/
      ...
    providers/
      ...
    inputs/
      ...
    database/
      ...
    trading_analysis/
      ...
    options/
      ...
    utils/
      ...
    config/                        # YAML files
      portfolio.yaml
      risk_limits.yaml
      ...
    models/
      ...
```

### Entry Points

```toml
[project.scripts]
portfolio-mcp = "portfolio_mcp.server:main"
```

Users can invoke as:
```bash
portfolio-mcp                          # CLI entry point
python -m portfolio_mcp                # Module entry point
```

---

## Implementation Phases

### Phase 1: Package Scaffolding (Small)

Create the package directory and build infrastructure without moving code yet.

**Steps:**
1. Create `portfolio_mcp/` directory at repo root
2. Create `portfolio_mcp/pyproject.toml` with build config
3. Create `portfolio_mcp/__init__.py` with version
4. Create `portfolio_mcp/__main__.py` (`from portfolio_mcp.server import main; main()`)
5. Create `portfolio_mcp/server.py` — stub that imports and delegates

**Key decision**: The `portfolio_mcp/` directory in the monorepo is the source of truth, just like `fmp/` is for fmp-mcp and `app_platform/` is for app-platform.

### Phase 2: Import Rewriting (Large — the hard step)

The core challenge is that all 40 tool modules use bare imports (`from core.result_objects import ...`, `from services.position_service import ...`, etc.). These work in the monorepo because `risk_module/` is the working directory. In the standalone package, they must be relative or qualified.

**Strategy: Conditional import paths**

Rather than rewriting every import in the monorepo (which would break existing flows), use a path setup approach:

**Option A — sys.path injection at server startup** (simpler, proven by fmp-mcp):
```python
# portfolio_mcp/server.py
import sys
from pathlib import Path
# Add package root to sys.path so bare imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

This means the package internal structure mirrors the monorepo structure, and all existing imports (`from core.X import Y`, `from services.X import Y`) work unchanged. The sync script copies directories into the package at the same relative paths.

**Option B — full relative import rewrite** (cleaner but very large diff):
Rewrite every import in all 40 tool modules + all transitive dependencies to use `from portfolio_mcp.core.X import Y`. This is ~500+ import statements. Not worth doing unless there's a collision risk.

**Recommendation: Option A.** It is proven by the fmp-mcp pattern (which uses `from fmp.tools.X import Y` internally, with the package structure mirroring the monorepo). The sync script handles the directory layout.

**Steps:**
1. In `portfolio_mcp/server.py`, add `sys.path.insert(0, ...)` for the package root
2. Copy the tool registration code from `mcp_server.py` into `portfolio_mcp/server.py`
3. Adjust imports from `from mcp_tools.X import Y` to `from tools.X import Y` (or keep `mcp_tools` as the directory name inside the package)
4. Ensure `settings.py` works standalone (see Phase 3)
5. Verify all tools load without import errors

**Import mapping (monorepo -> package):**

| Monorepo import | Package internal path | Change needed? |
|---|---|---|
| `from mcp_tools.X import Y` | `from tools.X import Y` | Yes — rename directory |
| `from core.X import Y` | `from core.X import Y` | No (sys.path) |
| `from services.X import Y` | `from services.X import Y` | No (sys.path) |
| `from settings import X` | `from settings import X` | No (sys.path) |
| `from database import X` | `from database import X` | No (sys.path) |
| `from fmp.X import Y` | External dep | Handled by PyPI dep |
| `from app_platform.X import Y` | External dep | Handled by PyPI dep |
| `from ibkr.X import Y` | Optional dep | Guarded import |

**Alternative: keep `mcp_tools/` name in package.** Avoids changing any tool-to-tool imports (`from mcp_tools.common import handle_mcp_errors`). The sync script copies `mcp_tools/` as-is. Only `mcp_server.py -> server.py` import lines need updating.

**Recommendation: Keep `mcp_tools/` as the directory name inside the package.** This minimizes diff and ensures cross-references within tools (`from mcp_tools.risk import _load_portfolio_for_analysis`) work without changes.

### Phase 3: Settings Abstraction (Medium)

`settings.py` is a monolith (458 lines) that loads `.env`, imports from `ibkr.config`, `providers.routing_config`, and `utils.user_context`. It defines `PORTFOLIO_DEFAULTS`, `RISK_ANALYSIS_THRESHOLDS`, `FACTOR_INTELLIGENCE_DEFAULTS`, feature flags, and provider credentials.

**For standalone mode, settings.py needs to:**
1. Work without IBKR config (guard the import)
2. Work without all provider credentials (graceful degradation)
3. Support user-level config override via `~/.portfolio-mcp/config.yaml` or environment variables

**Steps:**
1. Guard the `from ibkr.config import ...` block with try/except (IBKR is optional)
2. Guard the `from providers.routing_config import ...` block with try/except + sensible defaults
3. Add config file discovery: check `PORTFOLIO_MCP_CONFIG` env var, then `~/.portfolio-mcp/config.yaml`, then package defaults
4. Settings that users commonly override (FMP_API_KEY, DATABASE_URL, RISK_MODULE_USER_EMAIL, TRADING_ENABLED) should work from environment variables as they do today

**Config file format for standalone users:**
```yaml
# ~/.portfolio-mcp/config.yaml
user_email: you@example.com
fmp_api_key: your_key_here

# Optional: database for full features
# database_url: postgresql://localhost/portfolio

# Optional: IBKR for live trading
# ibkr:
#   enabled: true
#   gateway_host: 127.0.0.1
#   gateway_port: 4002

# Portfolio definition (alternative to CSV import)
# portfolio:
#   AAPL: {shares: 100}
#   MSFT: {shares: 50}
```

### Phase 4: Database Abstraction (Medium)

The package must work in **three modes**:

**Mode 1: No database (YAML-only)** — The default for new users.
- `is_db_available()` returns False
- `@require_db` tools return helpful error messages
- Analysis tools (risk, performance, optimization, etc.) work via CSV import or YAML config
- Portfolio management tools (list_portfolios, create_portfolio, etc.) are disabled
- Transaction store tools are disabled

**Mode 2: SQLite** — Lightweight persistence for single-user CLI use.
- Future enhancement (post-extraction)
- Would replace the Postgres pool with SQLite connection
- Enables transaction store, portfolios, baskets without running Postgres

**Mode 3: PostgreSQL** — Full features, same as monorepo.
- User sets `DATABASE_URL`
- Everything works as today

**Steps:**
1. Ensure `database/__init__.py` handles missing `psycopg2` gracefully (it currently imports it at module level)
2. Make `app_platform.db` import conditional in `database/__init__.py` and `mcp_tools/common.py`
3. Verify all `@require_db` decorations are correct (22 tools currently decorated)
4. Add clear user-facing messages: "This tool requires a database. Set DATABASE_URL to enable."

**Current no-DB readiness (from Phase A Step 1 work):**
The codebase already has `is_db_available()` positive-only caching, `@require_db` on 22 tools, `RiskLimitsManager` YAML fallback, and `PositionService` cache guards. This is 80% of what's needed. The remaining work is making the import-time DB dependencies optional.

### Phase 5: Sync Script (Small)

Create `scripts/sync_portfolio_mcp.sh` following the established pattern.

```bash
#!/usr/bin/env bash
# Sync portfolio-mcp public repo from monorepo source of truth.
set -euo pipefail

MONOREPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$HOME/Documents/Jupyter/portfolio-mcp-dist"

# Ensure target exists
if [ ! -d "$TARGET" ]; then
    echo "Target repo not found at $TARGET"
    echo "Run: mkdir $TARGET && cd $TARGET && git init"
    exit 1
fi

echo "Syncing portfolio-mcp from monorepo..."

COMMON_EXCLUDE=(
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='.DS_Store'
)

# Sync mcp_tools/ -> portfolio_mcp/mcp_tools/
rsync -av --delete "${COMMON_EXCLUDE[@]}" \
    "$MONOREPO/mcp_tools/" "$TARGET/portfolio_mcp/mcp_tools/"

# Sync internal packages
for pkg in core services providers inputs database trading_analysis options utils config models; do
    if [ -d "$MONOREPO/$pkg" ]; then
        rsync -av --delete "${COMMON_EXCLUDE[@]}" \
            "$MONOREPO/$pkg/" "$TARGET/portfolio_mcp/$pkg/"
    fi
done

# Sync settings.py
cp "$MONOREPO/settings.py" "$TARGET/portfolio_mcp/settings.py"

# Sync server entry point (maintained in monorepo as portfolio_mcp/server.py)
cp "$MONOREPO/portfolio_mcp/server.py" "$TARGET/portfolio_mcp/server.py"
cp "$MONOREPO/portfolio_mcp/__init__.py" "$TARGET/portfolio_mcp/__init__.py"
cp "$MONOREPO/portfolio_mcp/__main__.py" "$TARGET/portfolio_mcp/__main__.py"

# Copy root-level files
cp "$MONOREPO/docs/reference/README_PORTFOLIO_MCP.md" "$TARGET/README.md"

# Scrub monorepo-specific paths
find "$TARGET" -name "*.py" -exec sed -i '' \
    's|/Users/.*/risk_module|<project_root>|g' {} +

echo ""
echo "Sync complete. Review changes:"
echo "  cd $TARGET && git status"
```

### Phase 6: Dependency Specification (Small)

`pyproject.toml` for the standalone package:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "portfolio-mcp"
version = "0.1.0"
description = "75 MCP tools for portfolio risk analysis, performance tracking, and trading — works with Claude Code"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
dependencies = [
    "fastmcp",
    "pandas",
    "numpy",
    "scipy",
    "requests",
    "python-dotenv",
    "python-dateutil",
    "pyyaml",
    "fmp-mcp >= 0.3.0",
    "app-platform >= 0.2.0",
]

[project.optional-dependencies]
db = ["psycopg2-binary"]
ibkr = [
    "ib_async",
    "nest_asyncio",
    "interactive-brokers-mcp >= 0.1.0",
]
trading = [
    "portfolio-mcp[db]",
    "portfolio-mcp[ibkr]",
]
optimization = ["cvxpy"]
all = [
    "portfolio-mcp[db]",
    "portfolio-mcp[ibkr]",
    "portfolio-mcp[optimization]",
]

[project.scripts]
portfolio-mcp = "portfolio_mcp.server:main"

[tool.hatch.build.targets.wheel]
packages = ["portfolio_mcp"]

[tool.hatch.build.targets.sdist]
include = ["portfolio_mcp/", "pyproject.toml", "README.md", "LICENSE"]
```

### Phase 7: Standalone Testing (Medium)

**Test strategy:**

1. **Import smoke test**: Verify the package loads without errors in a clean venv
   ```bash
   pip install -e .
   python -c "from portfolio_mcp.server import mcp; print('OK')"
   ```

2. **Tool registration test**: Verify all 75 tools register on the FastMCP server
   ```python
   from portfolio_mcp.server import mcp
   tools = mcp.list_tools()
   assert len(tools) >= 75
   ```

3. **No-DB mode test**: Verify analysis tools work with CSV-imported data and no DATABASE_URL
   ```bash
   unset DATABASE_URL
   portfolio-mcp  # Should start successfully
   # Via MCP: import_portfolio(file_path="sample.csv", ...) -> get_positions() -> get_risk_analysis()
   ```

4. **Subset of monorepo tests**: Extract tests that exercise tool-level functionality without needing the full web app:
   - `tests/mcp_tools/` (tool unit tests)
   - `tests/core/` (flags, result objects)
   - `tests/services/` (service unit tests)

5. **CI pipeline**: GitHub Actions workflow in the standalone repo
   ```yaml
   - Install portfolio-mcp[all]
   - Run import smoke test
   - Run tool registration test
   - Run extracted test subset
   ```

### Phase 8: Documentation (Small)

Create `docs/reference/README_PORTFOLIO_MCP.md` (synced to `README.md` in the dist repo):

- Quick start (pip install + claude mcp add)
- Configuration (env vars, config file)
- Tool catalog (grouped by category)
- No-DB vs DB mode explanation
- Optional features (IBKR, optimization)
- Link to full docs

---

## Tool Tiers for Standalone

Not all 75 tools make sense without the full monorepo infrastructure. Categorize by standalone readiness:

### Tier 1: Works out of the box (no DB, no broker API)

These tools work with CSV-imported portfolio data and FMP for market data:

- `import_portfolio` (CSV import)
- `get_positions` (from imported data)
- `export_holdings`
- `get_risk_score`
- `get_risk_analysis`
- `get_leverage_capacity`
- `get_performance` (hypothetical mode)
- `analyze_stock`
- `run_optimization`
- `get_efficient_frontier`
- `run_whatif`
- `run_backtest`
- `compare_scenarios`
- `get_factor_analysis`
- `get_factor_recommendations`
- `get_income_projection`
- `check_exit_signals`
- `get_quote`
- `set_risk_profile` / `get_risk_profile`
- `normalizer_sample_csv` / `normalizer_stage` / `normalizer_test` / `normalizer_activate` / `normalizer_list`
- `get_portfolio_news` / `get_portfolio_events_calendar`
- `get_mcp_context`

**~30 tools** — this is the core standalone experience.

### Tier 2: Requires database

- `list_accounts` / `list_portfolios` / `create_portfolio` / `update_portfolio_accounts` / `delete_portfolio`
- `account_activate` / `account_deactivate`
- `set_target_allocation` / `get_target_allocation`
- `record_workflow_action` / `update_action_status` / `get_action_history`
- `manage_instrument_config` / `manage_ticker_config`
- `ingest_transactions` / `list_transactions` / `list_ingestion_batches` / `inspect_transactions`
- `list_flow_events` / `list_income_events` / `refresh_transactions` / `transaction_coverage`
- `suggest_tax_loss_harvest` (needs transaction history)
- `get_trading_analysis` (needs transaction history)
- `get_performance` (realized mode — needs transaction store)
- `create_basket` / `list_baskets` / `get_basket` / `analyze_basket` / `update_basket` / `delete_basket` / `create_basket_from_etf`
- `import_transactions`

**~35 tools** — available when user sets `DATABASE_URL`.

### Tier 3: Requires IBKR connection

- `preview_trade` / `execute_trade` / `get_orders` / `cancel_order`
- `preview_futures_roll` / `execute_futures_roll`
- `preview_option_trade` / `execute_option_trade`
- `preview_basket_trade` / `execute_basket_trade`
- `analyze_option_chain` (needs IBKR chain data)
- `monitor_hedge_positions`
- `get_futures_curve`
- `generate_rebalance_trades` (execution path)

**~14 tools** — available when user has IBKR configured.

---

## Configuration Design

### Environment Variables (backward compatible)

All existing env vars continue to work:

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `RISK_MODULE_USER_EMAIL` | Yes | User identity for MCP tools |
| `FMP_API_KEY` | Yes | Market data access |
| `DATABASE_URL` | No | PostgreSQL for full features |
| `TRADING_ENABLED` | No | Enable trade execution (default: false) |
| `IBKR_ENABLED` | No | Enable IBKR gateway (default: false) |
| `IBKR_FLEX_ENABLED` | No | Enable IBKR Flex query (default: false) |
| `IBKR_FLEX_TOKEN` | No | IBKR Flex authentication |
| `IBKR_FLEX_QUERY_ID` | No | IBKR Flex query ID |

### Config File (new, optional)

For users who prefer file-based config over env vars:

```
~/.portfolio-mcp/config.yaml        # User config
~/.portfolio-mcp/risk_limits.yaml   # Risk limit overrides
~/.portfolio-mcp/portfolio.yaml     # Static portfolio definition
```

Config file discovery order:
1. `PORTFOLIO_MCP_CONFIG` env var (explicit path)
2. `~/.portfolio-mcp/config.yaml`
3. Package-bundled defaults in `portfolio_mcp/config/`

### Minimal Quick Start (zero config files)

```bash
pip install portfolio-mcp
export FMP_API_KEY=your_key
export RISK_MODULE_USER_EMAIL=you@example.com
claude mcp add portfolio-mcp -- portfolio-mcp
```

Then in Claude: "Import my portfolio from /path/to/holdings.csv" -- the CSV normalizer handles the rest.

---

## What Gets Simplified for Standalone

### Removed from standalone package

1. **Web app integration** — no `routes/`, no `app.py`, no `frontend/`
2. **Auth service** — no user sessions, no Google OAuth, no tier enforcement. The MCP server trusts `RISK_MODULE_USER_EMAIL` directly.
3. **Gateway proxy** — no agent chat relay
4. **Redis cache** — `services/redis_cache.py` guarded or removed
5. **Order watcher** — background thread disabled by default (opt-in via `ORDER_WATCHER_ENABLED`)
6. **Plaid/SnapTrade/Schwab OAuth flows** — the OAuth redirect handlers live in `routes/`. The underlying data adapters (`providers/plaid_positions.py`, etc.) still work if tokens are configured.

### Graceful degradation behavior

| Missing component | Behavior |
|---|---|
| No DATABASE_URL | ~35 DB tools return "requires database" error. Analysis tools work via CSV import. |
| No FMP_API_KEY | Startup warning. Tools that need market data return clear error. Position import still works. |
| No IBKR | ~14 trading/IBKR tools return "requires IBKR" error. Everything else works. |
| No psycopg2 | DB tools unavailable. Same as no DATABASE_URL. |
| No cvxpy | Optimization tools return "install portfolio-mcp[optimization]" error. |
| No ib_async | IBKR tools return "install portfolio-mcp[ibkr]" error. |

---

## Sync Script Design

### Files to sync

| Source (monorepo) | Target (dist repo) | Notes |
|---|---|---|
| `portfolio_mcp/server.py` | `portfolio_mcp/server.py` | Entry point (maintained in monorepo) |
| `portfolio_mcp/__init__.py` | `portfolio_mcp/__init__.py` | Version + package metadata |
| `portfolio_mcp/__main__.py` | `portfolio_mcp/__main__.py` | Module runner |
| `mcp_tools/` | `portfolio_mcp/mcp_tools/` | All tool modules |
| `core/` | `portfolio_mcp/core/` | Result objects, flags |
| `services/` | `portfolio_mcp/services/` | Service layer |
| `providers/` | `portfolio_mcp/providers/` | Brokerage adapters |
| `inputs/` | `portfolio_mcp/inputs/` | Portfolio/transaction management |
| `database/` | `portfolio_mcp/database/` | DB infrastructure |
| `trading_analysis/` | `portfolio_mcp/trading_analysis/` | Trading analysis |
| `options/` | `portfolio_mcp/options/` | Option analysis |
| `utils/` | `portfolio_mcp/utils/` | Shared utilities |
| `config/` | `portfolio_mcp/config/` | YAML configs |
| `models/` | `portfolio_mcp/models/` | DB models |
| `settings.py` | `portfolio_mcp/settings.py` | Settings |
| `brokerage/` | `portfolio_mcp/brokerage/` | Trade objects |

### Scrub rules (post-sync)

1. Remove hardcoded monorepo paths (`/Users/*/risk_module`)
2. Remove personal API keys or credentials
3. Remove monorepo-only test fixtures
4. Verify no `sys.path` hacks reference monorepo locations

### Version management

`pyproject.toml` is maintained in the **package repo** (same as fmp-mcp) to avoid version regression during sync. The sync script does NOT overwrite `pyproject.toml`.

---

## Risk Assessment

### High risk: Import path conflicts

The package bundles `core/`, `services/`, `providers/`, `utils/`, etc. as top-level directories inside `portfolio_mcp/`. If a user has other packages with the same names on their Python path, there could be collisions.

**Mitigation**: The `sys.path.insert(0, ...)` approach scopes to the package directory. The server process is a separate stdio process (MCP model), so Python path pollution is limited to that process.

### Medium risk: Transitive dependency size

The package is large — it includes most of the monorepo's Python code. This is fundamentally because the MCP server IS the main product surface.

**Mitigation**: This is acceptable for a pip package. Users install it once. The alternative (splitting into 5+ packages with complex inter-dependencies) would be worse for users and harder to maintain.

### Medium risk: Settings coupling

`settings.py` imports from `ibkr.config` and `providers.routing_config` at module level. If IBKR is not installed, this crashes.

**Mitigation**: Phase 3 wraps these in try/except with sensible defaults. Already partially done for `ibkr/` via lazy `__init__.py`.

### Low risk: DB import at module level

`database/__init__.py` does `import psycopg2` at the top. Without `portfolio-mcp[db]` installed, this fails at import time.

**Mitigation**: Make the import conditional: `try: import psycopg2 except ImportError: psycopg2 = None`. All downstream code already checks `is_db_available()`.

---

## Execution Estimate

| Phase | Effort | Dependencies |
|---|---|---|
| Phase 1: Package scaffolding | 1 session | None |
| Phase 2: Import rewriting | 2-3 sessions | Phase 1 |
| Phase 3: Settings abstraction | 1 session | Phase 1 |
| Phase 4: Database abstraction | 1 session | Phase 1 |
| Phase 5: Sync script | 0.5 session | Phase 1 |
| Phase 6: Dependency spec | 0.5 session | Phase 2 |
| Phase 7: Standalone testing | 1-2 sessions | Phases 2-4 |
| Phase 8: Documentation | 0.5 session | Phase 7 |

**Total: ~8-10 sessions**

### Suggested execution order

1. Phase 1 + 5 (scaffolding + sync script) -- get the pipeline working
2. Phase 3 + 4 (settings + DB abstraction) -- make standalone mode viable
3. Phase 2 (import rewriting) -- the main work
4. Phase 6 (pyproject.toml) -- formalize dependencies
5. Phase 7 (testing) -- verify in clean environment
6. Phase 8 (docs) -- polish for users

---

## PyPI Publishing Workflow

Following the established `DEPLOY_CHECKLIST.md` pattern:

1. All changes committed in monorepo (authoritative)
2. Run `./scripts/sync_portfolio_mcp.sh`
3. Review diff in dist repo: `cd ~/Documents/Jupyter/portfolio-mcp-dist && git diff`
4. Verify no monorepo internals leaked
5. Run smoke tests in dist repo
6. Commit + push dist repo
7. Tag version: `git tag v0.1.0 && git push --tags`
8. Build + publish: `python -m build && twine upload dist/*`
9. Verify install: `pip install portfolio-mcp && portfolio-mcp --help`

---

## Breaking Changes / API Surface

### MCP tool interface: No changes

All 75 tools keep their exact same signatures. The extraction is transparent to MCP clients (Claude, etc.).

### Python import paths: Changed

Users who imported `from mcp_tools.positions import get_positions` directly (not via MCP) would need to update to `from portfolio_mcp.mcp_tools.positions import get_positions`. However, the primary consumer is the MCP protocol, not Python imports, so this is low impact.

### Settings: Backward compatible

All existing env vars continue to work. The new config file is additive, not replacing.

### Database: Backward compatible

Existing users with DATABASE_URL continue to work unchanged. New users without a database get graceful degradation (already implemented via no-DB mode).

---

## Related Documents

- `docs/OPEN_SOURCE_LAUNCH_GAPS.md` — Gap analysis (this is item B4)
- `docs/OPEN_SOURCE_LAUNCH_STRATEGY.md` — Strategic context
- `docs/DEPLOY_CHECKLIST.md` — Publish workflow
- `scripts/sync_fmp_mcp.sh` — Reference sync script (fmp-mcp)
- `scripts/sync_app_platform.sh` — Reference sync script (app-platform)
- `fmp/pyproject.toml` — Reference pyproject.toml (fmp-mcp)

---

*This plan was created 2026-03-19. It covers the extraction of portfolio-mcp as a standalone PyPI package, following the proven sync-script pattern used by fmp-mcp and app-platform.*
