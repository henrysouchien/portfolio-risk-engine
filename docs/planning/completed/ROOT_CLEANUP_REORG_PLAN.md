# Root-Level Cleanup & Reorg

## Context

The risk_module root has 32 Python files — a mix of shims, server entry points, CLI runners, legacy notebook code, and library modules. After extracting `app_platform/`, `fmp/`, `ibkr/`, and `portfolio_risk_engine/` into packages, the root is the last unorganized area. This cleanup moves pure entry-point scripts and dead code out of the root, leaving only files that are actively imported as library modules.

## Scope

Move CLI runners to `scripts/`, archive dead notebook code, leave actively-imported modules at root.

---

## Phase 0: Make `scripts/` an explicit Python package

`scripts/` currently has no `__init__.py`, making it an implicit namespace package. Phase 2 rewrites test imports to `from scripts.run_cache import ...`, which relies on fragile namespace-package resolution. Adding `__init__.py` makes `scripts` an explicit package with deterministic import behavior.

**Action**: Create `scripts/__init__.py` (empty file).

## Phase 1: Move pure CLI runners to `scripts/` (no importers)

These 6 files have zero importers — they're standalone entry points:

| File | What it does |
|---|---|
| `run_factor_intelligence.py` | Factor correlation/performance CLI |
| `run_options.py` | Options strategy analysis CLI |
| `run_plaid.py` | Plaid account management CLI |
| `run_schwab.py` | Schwab API CLI (OAuth, accounts) |
| `run_snaptrade.py` | SnapTrade account management CLI |
| `run_trading_analysis.py` | Trading analyzer CLI |

**Action**: `git mv` each to `scripts/`.

## Phase 2: Move runners with test-only importers to `scripts/`

These 3 files are imported only by test files:

| File | Importer(s) |
|---|---|
| `run_cache.py` | `tests/services/test_cache_control.py` |
| `run_ibkr_data.py` | `tests/ibkr/test_client.py` |
| `run_positions.py` | `tests/services/test_position_service_provider_registry.py` |

**Action**: `git mv` each to `scripts/`, update the test import paths to `scripts.MODULE`.

## Phase 3: Archive legacy notebook code

These files have Jupyter `# In[ ]` cell markers and are legacy:

| File | Importers | Action |
|---|---|---|
| `gpt_helpers.py` | `app.py`, `proxy_builder.py`, `run_risk.py`, `core/interpretation.py` | **Leave at root** — 4 active importers, not safe to move |
| `helpers_display.py` | `run_risk.py` | **Leave at root** — imported by `run_risk.py` which itself is heavily imported |
| `helpers_input.py` | `run_risk.py`, `tests/utils/test_basic_functionality.py`, `portfolio_risk_engine/portfolio_optimizer.py` | **Leave at root** — 3 importers including portfolio_risk_engine |

**Revised decision**: All 3 legacy files have active importers. Moving them requires shims, which adds complexity for minimal gain. Leave them at root for now.

## Phase 4: Archive or leave remaining questionable files

| File | Importers | Decision |
|---|---|---|
| `ai_function_registry.py` | 1 test file | **Leave** — not worth the churn |
| `dev_monitor.py` | `app.py` (2 imports) | **Leave** — server infrastructure |

## Do NOT move (actively imported library modules)

These files have `run_` prefix but are NOT runners — they're library modules:

| File | Importers | Why it stays |
|---|---|---|
| `run_portfolio_risk.py` | 5+ (core/result_objects, core/portfolio_analysis, portfolio_risk_engine, run_risk, tests) | Exports `latest_price()`, `standardize_portfolio_input()`, `load_portfolio_config()` |
| `run_risk.py` | 8+ (app.py, services/portfolio_service, services/optimization_service, core/interpretation, run_positions, tests) | Exports `evaluate_portfolio_risk_limits()`, risk analysis orchestration |

These also stay — full explicit list of all 23 remaining root files:

**Library modules (actively imported):**
- `portfolio_risk_score.py` — imported by `app.py`, `run_risk.py`, `services/portfolio/context_service.py`, `core/result_objects/risk.py`, tests
- `risk_helpers.py` — imported by `core/portfolio_analysis.py`, `run_risk.py`
- `risk_summary.py` — imported by `run_risk.py`, `portfolio_risk_engine/stock_analysis.py`
- `schwab_client.py` — imported by `providers/schwab_positions.py`, `providers/schwab_transactions.py`, `providers/normalizers/schwab.py`, `run_schwab.py`
- `gpt_helpers.py` — imported by `app.py`, `proxy_builder.py`, `run_risk.py`, `core/interpretation.py`
- `helpers_display.py` — imported by `run_risk.py`
- `helpers_input.py` — imported by `run_risk.py`, `portfolio_risk_engine/portfolio_optimizer.py`, tests
- `run_portfolio_risk.py` — imported by 5+ modules (exports `latest_price()`, etc.)
- `run_risk.py` — imported by 8+ modules (risk analysis orchestration)
- `position_metadata.py` — imported by services
- `proxy_builder.py` — imported by `app.py`
- `dev_monitor.py` — imported by `app.py`
- `ai_function_registry.py` — imported by 1 test file

**Shims (thin re-export wrappers):**
- `portfolio_risk.py`, `data_loader.py`, `factor_utils.py`, `portfolio_optimizer.py`

**Server entry points:**
- `app.py`, `mcp_server.py`, `fmp_mcp_server.py`

**Data loaders / config:**
- `settings.py`, `plaid_loader.py`, `snaptrade_loader.py`

---

## Summary

| Action | Files | Count |
|---|---|---|
| Create `scripts/__init__.py` | (new file) | 1 |
| Move to `scripts/` | run_factor_intelligence, run_options, run_plaid, run_schwab, run_snaptrade, run_trading_analysis | 6 |
| Move to `scripts/` + update test imports | run_cache, run_ibkr_data, run_positions | 3 |
| Leave at root | Everything else | 23 |

**Root goes from 32 → 23 files.** The 9 moved files are all CLI entry points with no (or test-only) importers. `scripts/__init__.py` ensures deterministic import resolution for Phase 2.

## Files to modify

- Create `scripts/__init__.py` (empty)
- `git mv` 9 `run_*.py` files to `scripts/`
- `tests/services/test_cache_control.py` — update `run_cache` import paths (lines 573, 589, 605, 620)
- `tests/ibkr/test_client.py` — update `run_ibkr_data` import path (line 10)
- `tests/services/test_position_service_provider_registry.py` — update `run_positions` import path (line 6)
- Update user-facing command text inside moved CLIs to reflect new paths (argparse help, docstrings). Also remove or update `# File:` header comments (e.g., `# File: run_factor_intelligence.py` → remove, as the filename is self-evident from the file itself):
  - `run_plaid.py` lines 7-12 — `python3 run_plaid.py` → `python3 -m scripts.run_plaid`
  - `run_snaptrade.py` lines 7-15 — `python3 run_snaptrade.py` → `python3 -m scripts.run_snaptrade`
  - `run_cache.py` lines 4-9 — `python run_cache.py` → `python3 -m scripts.run_cache`
  - `run_ibkr_data.py` lines 5, 99 — `python run_ibkr_data.py` → `python3 -m scripts.run_ibkr_data`
  - `run_factor_intelligence.py` line 345 — `python run_factor_intelligence.py` → `python3 -m scripts.run_factor_intelligence`
  - `run_schwab.py` line 214 — `python run_schwab.py` → `python3 -m scripts.run_schwab`
- **Sweep stale references** — after the `git mv` and test import updates, grep for remaining references to the 9 moved files and manually review each match. Not all matches are stale (e.g., function names, test method names using `run_cache` as a symbol are fine). Focus on:
  - **Stale imports**: `import run_cache` or `from run_ibkr_data import` (should become `from scripts.run_cache import` etc.)
  - **Stale CLI commands**: `python3 run_plaid.py` in error messages, help text, or docs (should become `python3 -m scripts.run_plaid`)
  - **Stale file paths**: `run_schwab.py` in docs or comments referring to root location (should become `scripts/run_schwab.py`)

  Use this grep to find candidates (excludes `scripts/`, `.git/`, `.claude/`, and archival docs):
  ```bash
  rg 'run_(factor_intelligence|options|plaid|schwab|snaptrade|trading_analysis|cache|ibkr_data|positions)' \
    --glob '!scripts/**' --glob '!__pycache__/**' --glob '!.git/**' --glob '!.claude/**' \
    --glob '!docs/planning/completed/**' --glob '!docs/planning/ROOT_CLEANUP_REORG_PLAN.md' \
    --glob '!docs/guides/completed/**' --glob '!docs/architecture/legacy/**' \
    --glob '!CHANGELOG.md' --glob '!backup/**' --glob '!archive/**' -n
  ```
  Review each match — update stale imports/commands/paths, skip valid symbol references (function calls, test names, etc.).
- **Update docs with generic root-location assumptions** (these won't be caught by the filename-based sweep):
  - `docs/interfaces/cli.md:86` — update `scripts/` tier classification
  - `docs/architecture/ORGANIZATION_PROPOSAL.md:9` — update "Python CLIs live in repo root via `run_*.py`"

## Verification

1. `python3 -c "import scripts; assert scripts.__file__ is not None, 'scripts is a namespace package, not explicit'"` — verify `scripts/__init__.py` exists (namespace packages have `__file__ = None`)
2. `python3 -c "from scripts.run_cache import main"` — verify Phase 2 import path works
3. Smoke-test all 6 Phase 1 CLIs via module invocation (verifies root-level imports resolve after relocation):
   ```bash
   python3 -m scripts.run_plaid --help
   python3 -m scripts.run_schwab --help
   python3 -m scripts.run_snaptrade --help
   python3 -m scripts.run_options --help
   python3 -m scripts.run_factor_intelligence --help
   python3 -m scripts.run_trading_analysis --help
   ```
4. Run the 3 affected test files to confirm imports resolve:
   - `python3 -m pytest tests/services/test_cache_control.py -x --no-header -q`
   - `python3 -m pytest tests/ibkr/test_client.py -x --no-header -q`
   - `python3 -m pytest tests/services/test_position_service_provider_registry.py -x --no-header -q`
5. `python3 -c "import app; import mcp_server"` — verify no root imports broke
6. Verify stale references were cleaned up — check for import-style and command-style references that still use root-level paths. Note: `rg` exits with code 1 when zero matches are found — that is the **expected success case** here. Historical/archival docs (`CHANGELOG.md`, `docs/*/completed/`, `docs/architecture/legacy/`) are excluded — they record past state and should not be rewritten.
   ```bash
   # Check for stale imports at any indentation level (should find zero matches)
   rg '\b(import run_|from run_)(factor_intelligence|options|plaid|schwab|snaptrade|trading_analysis|cache|ibkr_data|positions)\b' \
     --glob '!scripts/**' --glob '!.git/**' --glob '!.claude/**' \
     --glob '!docs/planning/completed/**' --glob '!docs/planning/ROOT_CLEANUP_REORG_PLAN.md' \
     --glob '!docs/guides/completed/**' --glob '!docs/architecture/legacy/**' \
     --glob '!CHANGELOG.md' --glob '!backup/**' --glob '!archive/**'

   # Check for stale CLI commands (should find zero matches)
   rg 'python3?\s+run_(factor_intelligence|options|plaid|schwab|snaptrade|trading_analysis|cache|ibkr_data|positions)\.py' \
     --glob '!scripts/**' --glob '!.git/**' --glob '!.claude/**' \
     --glob '!docs/planning/completed/**' --glob '!docs/planning/ROOT_CLEANUP_REORG_PLAN.md' \
     --glob '!docs/guides/completed/**' --glob '!docs/architecture/legacy/**' \
     --glob '!CHANGELOG.md' --glob '!backup/**' --glob '!archive/**'

   # Check for stale command-style self-references inside the moved CLIs (should find zero)
   rg 'python3?\s+run_(factor_intelligence|options|plaid|schwab|snaptrade|trading_analysis|cache|ibkr_data|positions)\.py' \
     scripts/
   ```
   All three should return **exit code 1** (no matches found). Any output means stale references remain.

   Note: bare file-path references in docs (e.g., `run_schwab.py` without a `python3` prefix) cannot be reliably distinguished from valid post-move `scripts/run_schwab.py` paths via grep. These are caught by the manual sweep in the "Files to modify" section above. Historical/archival docs are intentionally excluded — they document past state.
7. `git status` — confirm expected changes: 9 renamed files, `scripts/__init__.py` added, plus modified test files, source files, and docs from the stale-reference sweep

## Notes

- **Docs with generic `run_*.py` assumptions**: Some docs assume CLIs live at repo root using generic language (not specific filenames), so the filename-based sweep won't catch them. These are handled by the explicit edit list in "Files to modify" above (`docs/interfaces/cli.md:86`, `docs/architecture/ORGANIZATION_PROPOSAL.md:9`).
- Phase 1 CLIs are standalone entry points. After relocation they must be invoked via module syntax: `python3 -m scripts.run_plaid` (not `python3 scripts/run_plaid.py`). Direct file execution sets `sys.path[0]` to `scripts/`, which breaks root-level imports like `plaid_loader`. Module invocation keeps the project root on `sys.path`. No shims needed at root since they have zero importers.
