# Portfolio Risk Engine Shim Removal Plan
**Status:** DONE

## Context

After the first shim removal (`498392d2`), 4 thin re-export shims remain at root. Each shim is 3 lines (`import sys; import portfolio_risk_engine.X as _mod; sys.modules[__name__] = _mod`). The real code lives in `portfolio_risk_engine/`. This plan updates all importers to use the real paths, then deletes the shims.

**Goal:** Delete all 4 root shims. Root goes from 8 → 4 files (3 entry points + `settings.py`).

**Scope**: Only active source tree. `.claude/worktrees/`, `backup/`, `.ipynb_checkpoints/` are excluded.

---

## Phase 1: Low-importer shims (1-2 importers)

| Shim | Real path | Importers to update |
|------|-----------|---------------------|
| `portfolio_optimizer` | `portfolio_risk_engine.portfolio_optimizer` | `core/risk_orchestration.py:37`, `tests/core/test_temp_file_refactor.py:15` |

**Total**: 1 shim, 2 import sites.

## Phase 2: Medium-importer shims (6-11 importers)

| Shim | Real path | Importers to update |
|------|-----------|---------------------|
| `portfolio_risk` | `portfolio_risk_engine.portfolio_risk` | `core/portfolio_analysis.py:43`, `core/factor_intelligence.py:53`, `core/risk_orchestration.py:36`, `core/run_portfolio_risk.py:26`, `services/factor_intelligence_service.py:1139` (lazy), `utils/helpers_input.py:95` (lazy), `tests/core/test_portfolio_risk.py:5` (`import portfolio_risk as pr`), `tests/core/test_performance_metrics_engine.py:9`, `tests/utils/test_basic_functionality.py:18,55` (`import portfolio_risk`), `tests/utils/test_final_status.py:17` (`import portfolio_risk`) |

**Total**: 1 shim, 11 import sites.

## Phase 3: High-importer shims (20-24 importers)

| Shim | Real path | Importers to update |
|------|-----------|---------------------|
| `factor_utils` | `portfolio_risk_engine.factor_utils` | `core/run_portfolio_risk.py:15`, `core/factor_intelligence.py:59` (top-level), `core/factor_intelligence.py:1030` (lazy), `core/factor_intelligence.py:1090` (lazy), `core/factor_intelligence.py:1104` (lazy), `core/factor_intelligence.py:1188` (lazy), `core/factor_intelligence.py:1296` (lazy), `core/realized_performance/__init__.py:17`, `core/realized_performance/_helpers.py:17`, `core/realized_performance/aggregation.py:18`, `core/realized_performance/backfill.py:17`, `core/realized_performance/engine.py:19`, `core/realized_performance/fx.py:17`, `core/realized_performance/holdings.py:17`, `core/realized_performance/nav.py:18`, `core/realized_performance/pricing.py:17`, `core/realized_performance/provider_flows.py:17`, `core/realized_performance/timeline.py:17`, `admin/verify_proxies.py:51`, `mcp_tools/signals.py:23` |
| `data_loader` | `portfolio_risk_engine.data_loader` | `core/factor_intelligence.py:55`, `core/proxy_builder.py:715` (lazy), `core/realized_performance/__init__.py:16`, `core/realized_performance/_helpers.py:16`, `core/realized_performance/aggregation.py:17`, `core/realized_performance/backfill.py:16`, `core/realized_performance/engine.py:18`, `core/realized_performance/fx.py:16`, `core/realized_performance/holdings.py:16`, `core/realized_performance/nav.py:17`, `core/realized_performance/pricing.py:16`, `core/realized_performance/provider_flows.py:16`, `core/realized_performance/timeline.py:16`, `providers/bs_option_price.py:12`, `options/portfolio_greeks.py:56` (lazy), `inputs/returns_calculator.py:70` (lazy), `services/returns_service.py:616` (lazy), `admin/verify_proxies.py:50`, `mcp_tools/signals.py:22`, `tests/fmp/test_fmp_migration.py:9` (`import data_loader`), `tests/performance/test_performance_benchmarks.py:35`, `tests/utils/test_basic_functionality.py:21,83` (`import data_loader`), `tests/utils/test_final_status.py:18` (`import data_loader`) |

**Total**: 2 shims, 44 import sites.

**Note**: `data_loader` and `factor_utils` share 11 files in `core/realized_performance/` — those files need both imports updated in the same pass.

---

## Phase 4: Delete shims and clean up

**Action**: Delete all 4 root shim files:
- `rm data_loader.py factor_utils.py portfolio_risk.py portfolio_optimizer.py`

**Note**: Unlike the previous 15 shims, these 4 shims do NOT have `sys.modules` aliases in the real modules. The shims themselves create the alias via `sys.modules[__name__] = _mod`. Deleting the shim file is sufficient — no alias cleanup needed in the target modules.

---

## Hot Files (multiple shim imports)

| File | Shims imported | Import sites |
|------|---------------|-------------|
| `core/risk_orchestration.py` | 2 (portfolio_risk, portfolio_optimizer) | 2 |
| `core/run_portfolio_risk.py` | 2 (factor_utils, portfolio_risk) | 2 |
| `core/factor_intelligence.py` | 3 (portfolio_risk, data_loader, factor_utils ×6) | 8 |
| `core/realized_performance/*` (11 submodules) | 2 each (data_loader, factor_utils) | 22 |
| `admin/verify_proxies.py` | 2 (data_loader, factor_utils) | 2 |
| `mcp_tools/signals.py` | 2 (data_loader, factor_utils) | 2 |
| `tests/utils/test_basic_functionality.py` | 2 (portfolio_risk, data_loader) | 4 |
| `tests/utils/test_final_status.py` | 2 (portfolio_risk, data_loader) | 2 |

---

## Summary

| Phase | Shims removed | Import sites | Risk |
|-------|--------------|-------------|------|
| Phase 1 | 1 (portfolio_optimizer) | 2 | Low |
| Phase 2 | 1 (portfolio_risk) | 11 | Low |
| Phase 3 | 2 (factor_utils, data_loader) | 44 | Low (mechanical, many are identical `realized_performance` lines) |
| Phase 4 | 0 (delete shim files) | 0 | Low |
| **Total** | **4** | **57 import edits** | |

---

## Verification

After all phases:
1. `python3 -m pytest tests/ -x --no-header -q` — full test suite
2. `python3 -c "import app; import mcp_server; import fmp_mcp_server"` — entry points
3. `python3 -c "import services; import services.portfolio_service"` — services package
4. Verify no remaining import references (anchored pattern):
   ```
   rg -n '^\s*(from\s+(data_loader|factor_utils|portfolio_risk|portfolio_optimizer)\s+import|import\s+(data_loader|factor_utils|portfolio_risk|portfolio_optimizer)\b)' --glob '*.py' --glob '!docs/**' --glob '!.claude/**' --glob '!archive/**' --glob '!backup/**' --glob '!.ipynb_checkpoints/**'
   ```
   Note: May match string literals in `scripts/collect_all_schemas.py` — those are not real imports and can be ignored.
5. `ls *.py | wc -l` should be **4** (`app.py`, `mcp_server.py`, `fmp_mcp_server.py`, `settings.py`)

## Files modified

| Category | Count |
|----------|-------|
| Shim files deleted | 4 |
| Source files with import edits | 24 unique files |
| Test files with import edits | 7 |
| **Total files touched** | **35** |
