# RELEASE PLAN — risk_module

## Background & Context

See these docs for the broader strategy and execution plan:
- `~/.openclaw/workspace/MARKET_HYPOTHESIS.md` — market segments (H1 builder / H2 institutional / H3 aspiring investor), guiding principle, strategic edge, GTM path
- `~/.openclaw/workspace/WEEKEND_SPRINT.md` — phased release plan (Phase 1–7), execution order, per-package checklists

---

This repo contains multiple layered packages. Release in order — each phase depends on prior ones.

---

## Phase 1: Quick MCP Release (Completed 2026-02-23)
**Goal:** Publish three already-built MCP servers as public repos.

### Completed
- [x] `gsheets-mcp` — https://github.com/henrysouchien/gsheets-mcp (tag: `v0.1.0`)
- [x] `drive-mcp` — https://github.com/henrysouchien/drive-mcp (tag: `v0.1.0`)
- [x] `gmail-mcp` — https://github.com/henrysouchien/gmail-mcp (tag: `v0.1.0`)

---

## Package 1: `fmp-mcp` (Phase 4 — Extracted 2026-02-23)
**Goal:** Standalone MCP for Financial Modeling Prep data — 19 tools for market/fundamental data via Claude.

### Completed
- [x] Restructured as self-contained `fmp/` package within monorepo
- [x] `fmp/server.py` with 19 MCP tools, `fmp/tools/` module layer
- [x] `pyproject.toml`, `README_PACKAGE.md`, env-var config, smart cache paths
- [x] Output management: `columns`, `output="file"`, auto-summary, `limit`, `last_n` across 5 tools
- [x] Shared file-output utilities (`fmp/tools/_file_output.py`)
- [x] Fixed `get_market_context` indices endpoint (batch_index_quotes → per-symbol fallback)
- [x] 412 tests passing, all 19 tools verified live

### Shipped to Public GitHub (2026-02-23)
- [x] Create standalone repo, copy `fmp/` + `pyproject.toml` + `README_PACKAGE.md` + `LICENSE`
- [x] Scrub for secrets and local paths
- [x] Push to GitHub as `fmp-mcp` public repo — https://github.com/henrysouchien/fmp-mcp
- [x] Tag `v0.1.0`
- [x] Build and publish to PyPI — https://pypi.org/project/fmp-mcp/0.1.0/
- [x] Verify: `uvx fmp-mcp` starts server, Claude Code config works

---

## Package 2: `ibkr-mcp` (Phase 4 — Extracted 2026-02-23)
**Goal:** Standalone MCP for Interactive Brokers data — 6 tools for market data/account access via Claude.

### Completed
- [x] Extracted as self-contained `ibkr/` package within monorepo
- [x] 4 internal shims: `config.py`, `_logging.py`, `_types.py`, `_vendor.py`
- [x] 8 modules rewired (zero external deps on settings/utils/trading_analysis)
- [x] `ibkr/server.py` with 6 MCP tools, `pyproject.toml`, `README.md`
- [x] 103 tests passing, 6/6 tools verified live against IB Gateway
- [x] Public GitHub repo + `v0.1.0` tag — https://github.com/henrysouchien/ibkr-mcp
- [x] Sync script: `scripts/sync_ibkr_mcp.sh`

---

## Release Steps: fmp-mcp

### Completed (2026-02-23)
- [x] Created standalone repo at `~/Documents/Jupyter/fmp-mcp/`
- [x] Synced `fmp/` package (excluding `compat.py`, `fx.py`, `scripts/`)
- [x] Added MIT LICENSE, `.gitignore`, `pyproject.toml` (readme → `README.md`)
- [x] Scrubbed hardcoded paths and secrets
- [x] Committed and pushed to GitHub: https://github.com/henrysouchien/fmp-mcp
- [x] Tagged `v0.1.0`
- [x] Built package: `dist/fmp_mcp-0.1.0.tar.gz` + `.whl` (twine check passed)
- [x] Created sync script: `scripts/sync_fmp_mcp.sh` (rsync-based, auto-captures new files)

### Published to PyPI (2026-02-23)
- [x] `twine upload dist/*` — https://pypi.org/project/fmp-mcp/0.1.0/

### Claude Code config:
```json
{
  "mcpServers": {
    "fmp-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["fmp-mcp"],
      "env": { "FMP_API_KEY": "your_key" }
    }
  }
}
```

### Syncing changes

Source of truth is the monorepo (`risk_module/fmp/`). After making changes:

```bash
./scripts/sync_fmp_mcp.sh    # rsync to ~/Documents/Jupyter/fmp-mcp/
cd ~/Documents/Jupyter/fmp-mcp
git add . && git commit -m "description" && git push
# Bump version in pyproject.toml, rebuild, re-upload if publishing to PyPI
```

---

## Release Steps: ibkr-mcp

### Shipped to Public GitHub (2026-02-23)
- [x] Created standalone repo at `~/Documents/Jupyter/ibkr-mcp/`
- [x] Synced `ibkr/` package via rsync (excluded pyproject.toml, README.md from inner package)
- [x] `pyproject.toml` — hatchling build backend, `ibkr-mcp` entry point
- [x] Public `README.md`, MIT `LICENSE`, `.gitignore`
- [x] Scrub audit passed — no secrets, no hardcoded paths
- [x] Pushed to GitHub: https://github.com/henrysouchien/ibkr-mcp
- [x] Tagged `v0.1.0`
- [x] Created sync script: `scripts/sync_ibkr_mcp.sh`

### Published to PyPI (2026-02-23)
- [x] PyPI name: `interactive-brokers-mcp` (`ibkr-mcp` was taken)
- [x] Built and uploaded — https://pypi.org/project/interactive-brokers-mcp/0.1.0/
- [x] `pip install interactive-brokers-mcp` then `ibkr-mcp` to start server

### Syncing changes

Source of truth is the monorepo (`risk_module/ibkr/`). After making changes:

```bash
./scripts/sync_ibkr_mcp.sh    # rsync to ~/Documents/Jupyter/ibkr-mcp/
cd ~/Documents/Jupyter/ibkr-mcp
git add . && git commit -m "description" && git push
```

---

## Package 3: `brokerage-connect` (Phase 4 — Extracted 2026-02-23)
**Goal:** Unified Python interface for brokerage data — connect your code to IBKR, Schwab, SnapTrade, Plaid.

### Completed
- [x] Extracted pure broker API layer into self-contained `brokerage/` package within monorepo
- [x] Three-layer architecture: Pure API (extracted) → Normalization (stays) → Portfolio System (stays)
- [x] `brokerage/schwab/` — client + adapter (OAuth token auth, account hashes, positions, trading)
- [x] `brokerage/snaptrade/` — 6 submodules (client, secrets, users, connections, trading, adapter)
- [x] `brokerage/ibkr/` — adapter with `ibkr_to_common_status` (delegates to existing `ibkr/` package)
- [x] `brokerage/plaid/` — extracted pure Plaid API layer (`client`, `secrets`, `connections`) with `providers/plaid_loader.py` provider module (2026-02-24)
- [x] Core contracts: `trade_objects.py` (dataclasses + constants), `broker_adapter.py` (ABC)
- [x] Infrastructure shims: `_logging.py`, `_vendor.py`, `config.py`, `pyproject.toml`
- [x] `on_refresh` callback pattern — adapters no longer import `database` directly
- [x] Re-export shims at original paths — zero consumer code changes required
- [x] `TradeExecutionService` wires `on_refresh` via `_build_refresh_callback`
- [x] 1143 tests passing, all 3 adapters verified live
- [x] Plan doc: `docs/planning/BROKERAGE_CONNECT_PLAN.md`

### Shipped to Public GitHub (2026-02-23)
- [x] Created standalone repo at `~/Documents/Jupyter/brokerage-connect/`
- [x] Synced `brokerage/` package via rsync (excluded `__pycache__`, `*.pyc`, `.DS_Store`)
- [x] `pyproject.toml` — hatchling build backend, optional dep groups (`schwab`, `snaptrade`, `ibkr`, `plaid`)
- [x] Public `README.md`, MIT `LICENSE`, `.gitignore`
- [x] Scrub audit passed — no secrets, no hardcoded paths
- [x] Pushed to GitHub: https://github.com/henrysouchien/brokerage-connect
- [x] Tagged `v0.1.0`
- [x] Verified clean install: `pip install ./brokerage-connect` + `from brokerage import BrokerAdapter`
- [x] Created sync script: `scripts/sync_brokerage_connect.sh` (rsync-based, same pattern as fmp-mcp)
- [x] Plaid extraction shipped (v0.2.0) — `brokerage/plaid/` with lazy boto3/plaid imports
- [x] Tagged `v0.2.0`

### Published to PyPI (2026-02-23)
- [x] Built and uploaded — https://pypi.org/project/brokerage-connect/

### Syncing changes

Source of truth is the monorepo (`risk_module/brokerage/`). After making changes:

```bash
./scripts/sync_brokerage_connect.sh    # rsync to ~/Documents/Jupyter/brokerage-connect/
cd ~/Documents/Jupyter/brokerage-connect
git add . && git commit -m "description" && git push
# Bump version in pyproject.toml, rebuild, re-upload if publishing to PyPI
```

---

## Package 4: `portfolio-risk-engine` (Phase 5 — Extracted 2026-02-23)
**Goal:** Core quant analytics library — factor analysis, risk decomposition, optimization, performance metrics.

### Completed
- [x] Extracted as self-contained `portfolio_risk_engine/` package within monorepo
- [x] Moved root-level math modules: `portfolio_risk_engine/portfolio_risk.py` (1780 lines), `portfolio_risk_engine/factor_utils.py` (622), `portfolio_risk_engine/portfolio_optimizer.py` (1399), `portfolio_risk_engine/portfolio_risk_score.py` (1930), `portfolio_risk_engine/data_loader.py`, `portfolio_risk_engine/risk_helpers.py`, `portfolio_risk_engine/risk_summary.py`
- [x] Moved `core/` modules: `exceptions`, `constants`, `risk_profiles`, `risk_flags`, `income_projection`, `exit_signals`, `data_objects`, `performance_metrics_engine`, `portfolio_config`, `config_adapters`, `performance_analysis`, `stock_analysis`, `scenario_analysis`, `optimization`, `asset_class_performance`
- [x] `PriceProvider` / `FXProvider` protocol abstraction — pluggable data sources, FMP auto-detected
- [x] `_logging.py`, `_vendor.py`, `config.py` shims — standalone mode with no-op fallbacks
- [x] Module-alias shims at all original paths — zero consumer code changes
- [x] Injectable `evaluate_portfolio_risk_limits` / `evaluate_portfolio_beta_limits` in optimizer
- [x] Guarded service imports (`factor_proxy_service`, `security_type_service`) with graceful fallbacks
- [x] Lightweight `results.py` dataclasses (monorepo `result_objects.py` stays with presentation logic)
- [x] `pyproject.toml` — hatchling build, deps: pandas, numpy, statsmodels, cvxpy, pyyaml, requests
- [x] 1143 tests passing, live-verified: `build_portfolio_view`, `analyze_stock`, custom `PriceProvider`
- [x] Plan doc: `docs/planning/PORTFOLIO_RISK_ENGINE_PLAN.md`
- [x] Codex-reviewed (4 rounds): P0 shim strategy, protocol completeness, phase ordering, coupling gaps

### ⚠️ Requires math validation before public release
Built with AI assistance — needs methodology audit before others rely on it for investment decisions.

### Shipped to Public GitHub (2026-02-23)
- [x] Created standalone repo at `~/Documents/Jupyter/portfolio-risk-engine/`
- [x] Synced `portfolio_risk_engine/` package via rsync (excluded `__pycache__`, `*.pyc`, `.DS_Store`)
- [x] `pyproject.toml` — hatchling build backend, deps: pandas, numpy, statsmodels, pyarrow, cvxpy, requests, pyyaml
- [x] Public `README.md`, MIT `LICENSE`, `.gitignore`
- [x] Scrub audit passed — no secrets, no hardcoded paths
- [x] Pushed to GitHub: https://github.com/henrysouchien/portfolio-risk-engine
- [x] Tagged `v0.1.0`
- [x] Verified: `pip install -e .` + imports work
- [x] Built package: `dist/portfolio_risk_engine-0.1.0.tar.gz` + `.whl` (twine check passed)
- [x] Created sync script: `scripts/sync_portfolio_risk_engine.sh`
- [x] Published to PyPI — https://pypi.org/project/portfolio-risk-engine/0.1.0/

### Later: Validation Sprint (before v1.0)
- [ ] Methodology documentation: what factor model, what optimization approach, why
- [ ] Math validation: compare outputs against known benchmarks
- [ ] Unit tests for core calculations (factor regression, optimization, risk decomposition)
- [ ] Write README — position as institutional-methodology quant library

---

## Phase 6: AI Analyst — Package and Release ⬅️ CURRENT PRIORITY

**Goal:** Package the full AI analyst system (from `AI-excel-addin`) as a distributable open source agent. Proof of concept for the platform.

**What exists** (in `AI-excel-addin/api/`):
- Agent runner with agentic tool loop
- Tool dispatcher with approval gates + multi-executor routing
- Memory store (SQLite + embeddings + semantic recall + markdown sync)
- MCP client manager (dynamic server connections to fmp-mcp, edgar, portfolio tools)
- FastAPI gateway with JWT auth + SSE streaming
- Surfaces: Excel add-in, Telegram bot, TUI, Claude MCP

### Tasks
- [ ] Agent-first review of all MCP packages — audit tool outputs, descriptions, and response formats for agent usability (are outputs structured for agent reasoning? do tool descriptions guide Claude to pick the right tool? do outputs compose well across multi-step workflows?)
- [ ] Wire `portfolio-mcp` into the analyst as an MCP connection
- [ ] Dogfood: use the analyst daily, refine agent runner + memory + tool connections
- [ ] Clean up `AI-excel-addin` repo for open source release
- [ ] Package as distributable agent (openclaw-style: clone, configure, run)
- [ ] Accessible entry point: web chat or TUI — wide entry, progressive engagement
- [ ] `portfolio-mcp` as standalone package for Claude Chat/MCP users
- [ ] README + setup guide

### Strategic context
Open source is distribution. The real business is helping institutions translate their workflows into AI agents. Ship everything, hold nothing back. See `docs/PRODUCT_ARCHITECTURE.md` for full architecture.

---

## Phase 7: Additional Surfaces + Polish (post-launch)

### `react-ai-chassis` (optional)
- [ ] Extract generic multi-user AI app infra from React frontend
- [ ] Component library for financial visualizations
- [ ] AI-assisted dashboard assembly
- [ ] Risk module frontend becomes the reference implementation

### Hosted service
- [ ] Web chat interface — wide entry, freemium (free stock analysis → paid portfolio)
- [ ] Handle API costs (FMP, Claude, EDGAR) for users
- [ ] Plaid OAuth for quick portfolio connection
