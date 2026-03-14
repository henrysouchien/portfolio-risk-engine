# Core Shim Removal Plan

## Context

After completing the root cleanup arc (CLI runners → library reorg → shim removal → PRE shim removal → config/docs move), `core/` still has **18 `sys.modules` shim files** + **1 wrapper shim** that forward `core.X` → `portfolio_risk_engine.X`. These are backward-compat artifacts from the library reorg. Removing them makes the import graph honest — `portfolio_risk_engine/` is the canonical location, `core/` keeps only its own real logic (~30 files: flags, analysis, orchestration, result_objects/, realized_performance/).

**Goal:** Delete all 19 shim files, rewrite ~153 import sites + ~29 monkeypatch/patch targets + ~4 bare `import core.X` sites. No logic changes. (Per-shim counts are approximate; verification section catches all.)

**Scope:** Same playbook as root shim removal and PRE shim removal — mechanical import rewrites only.

---

## Shim Inventory

### 18 `sys.modules` shims (3-line files, zero logic)

| Shim | core.X importers | Already on PRE.X |
|------|:---:|:---:|
| `data_objects.py` | 46 | 7 |
| `performance_metrics_engine.py` | 15 | 3 |
| `exceptions.py` | 11 | 0 |
| `portfolio_config.py` | 11 | 9 |
| `constants.py` | 7 | 5 |
| `portfolio_risk_score.py` | 6 | 0 |
| `optimization.py` | 4 | 0 |
| `risk_profiles.py` | 4 | 0 |
| `config_adapters.py` | 3 | 6 |
| `exit_signals.py` | 3 | 0 |
| `income_projection.py` | 3 | 0 |
| `risk_flags.py` | 3 | 0 |
| `risk_helpers.py` | 3 | 10 |
| `scenario_analysis.py` | 3 | 0 |
| `asset_class_performance.py` | 2 | 0 |
| `risk_summary.py` | 2 | 0 |
| `stock_analysis.py` | 2 | 0 |
| `performance_analysis.py` | 1 | 0 |
| **Subtotal** | **129** | |

### 1 wrapper shim (different pattern)

| Shim | Importers | Pattern |
|------|:---:|-------|
| `realized_performance_analysis.py` | 24 | `from core.realized_performance import *` + wraps `analyze_realized_performance()`. NOT `sys.modules`. |

### Test monkeypatch/patch targets (29 unique targets across 5 files)

**`tests/core/test_temp_file_refactor.py`** (23 targets):
- `core.config_adapters.load_portfolio_config`, `core.config_adapters.config_from_portfolio_data`
- `core.optimization.resolve_portfolio_config`, `.resolve_risk_config`, `.standardize_portfolio_input`, `.run_min_var`, `.run_max_return_portfolio`
- `core.scenario_analysis.resolve_portfolio_config`, `.resolve_risk_config`, `.standardize_portfolio_input`, `.build_portfolio_view`, `.run_what_if_scenario`, `.WhatIfResult.from_core_scenario`
- `core.portfolio_risk_score.resolve_portfolio_config`, `.resolve_risk_config`, `.standardize_portfolio_input`, `.build_portfolio_view`, `.calc_max_factor_betas`, `.calculate_portfolio_risk_score`, `.calculate_suggested_risk_limits`, `.analyze_portfolio_risk_limits` (8 targets)
- `core.risk_helpers.calc_max_factor_betas`, `core.risk_helpers.compute_max_betas`

**`tests/core/test_asset_class_performance.py`** (1 target):
- `core.asset_class_performance.fetch_monthly_close` (×2 `@patch`)

**`tests/services/test_portfolio_service_futures.py`** (2 targets):
- `core.portfolio_config.get_cash_positions` (×2), `core.portfolio_config.latest_price` (×2)

**`tests/services/test_portfolio_service_asset_class_perf.py`** (3 targets):
- `core.asset_class_performance.fetch_monthly_close`, `.group_holdings_by_asset_class`, `.calculate_asset_class_returns`

**`tests/conftest.py`** (1 target):
- `core.realized_performance_analysis.TRANSACTION_STORE_READ`

### Bare `import core.X` in tests (4 sites, 4 files)

- `tests/core/test_risk_score_nan_guards.py:9` — `import core.portfolio_risk_score as prs`
- `tests/core/test_portfolio_risk_score_fund_weight_exemption.py:4` — `import core.portfolio_risk_score as prs`
- `tests/core/test_stock_analysis_factor_fallback.py:1` — `import core.stock_analysis as stock_analysis`
- `tests/inputs/test_legacy_portfolio_file_service.py:51` — `import core.portfolio_config`

(Note: `tests/mcp_tools/test_optimization_agent_format.py` uses `import core.optimization_flags` — this is a real file, NOT a shim, so it stays.)

### Internal cross-imports (real core/ and PRE/ files importing shims)

These files import shims and MUST be rewritten mechanically:

**Real `core/` files:**
- `core/risk_orchestration.py` — imports `config_adapters`, `data_objects`, `optimization`, `performance_analysis`, `portfolio_config`, `portfolio_risk_score`, `risk_helpers`, `risk_summary`, `scenario_analysis`, `stock_analysis` (10 shims)
- `core/portfolio_analysis.py` — imports `config_adapters`, `constants`, `data_objects`, `portfolio_config`, `risk_helpers` (5 shims)
- `core/run_portfolio_risk.py` — imports `constants`, `portfolio_config` (2 shims)
- `core/result_objects/positions.py` — imports `data_objects` (1 shim)
- `core/result_objects/risk.py` — imports `constants`, `portfolio_config`, `portfolio_risk_score` (3 shims)
- `core/result_objects/whatif.py` — imports `portfolio_config` (1 shim)
- `core/realized_performance/__init__.py` + 10 submodules — all import `performance_metrics_engine` (11 sites)

**`portfolio_risk_engine/` files (circular shim deps):**
- `portfolio_risk_engine/stock_analysis.py:34` — `from core.risk_summary import ...`
- `portfolio_risk_engine/portfolio_optimizer.py:1148` — `from core.risk_helpers import ...`

---

## Phased Approach

### Phase 1: Small shims (≤4 importers each) — 12 shims, ~33 external sites

Delete and rewrite imports for: `performance_analysis` (1), `asset_class_performance` (2), `risk_summary` (2), `stock_analysis` (2), `config_adapters` (3), `exit_signals` (3), `income_projection` (3), `risk_flags` (3), `risk_helpers` (3), `scenario_analysis` (3), `optimization` (4), `risk_profiles` (4)

Transform: `from core.X import Y` → `from portfolio_risk_engine.X import Y`

Also rewrite:
- Internal core/ imports in `risk_orchestration.py`, `portfolio_analysis.py` for these 12 shims
- PRE circular deps: `portfolio_risk_engine/stock_analysis.py` (risk_summary), `portfolio_risk_engine/portfolio_optimizer.py` (risk_helpers)
- Test monkeypatch targets in `test_temp_file_refactor.py` (config_adapters, optimization, scenario_analysis, risk_helpers targets)
- Test monkeypatch targets in `test_asset_class_performance.py`, `test_portfolio_service_asset_class_perf.py`
- Bare `import core.stock_analysis` in `test_stock_analysis_factor_fallback.py`

### Phase 2: Medium shims — 3 shims, ~24 external sites

`portfolio_risk_score` (6), `constants` (7), `portfolio_config` (11)

Also rewrite:
- Internal core/ imports in `risk_orchestration.py`, `portfolio_analysis.py`, `run_portfolio_risk.py`, `result_objects/*.py`
- Test monkeypatch targets in `test_temp_file_refactor.py` (portfolio_risk_score targets), `test_portfolio_service_futures.py` (portfolio_config targets)
- Bare `import core.portfolio_risk_score` in 2 test files, `import core.portfolio_config` in 1 test file

### Phase 3: Large shims — 3 shims, ~72 external sites

`data_objects` (46), `exceptions` (11), `performance_metrics_engine` (15)

Also rewrite:
- Internal core/ imports: `portfolio_analysis.py` (data_objects), `result_objects/positions.py` (data_objects), `realized_performance/` (11 files importing performance_metrics_engine)

### Phase 4: Wrapper shim — 1 shim, ~24 sites

`realized_performance_analysis.py` — re-exports from `core.realized_performance.*` (a real package in `core/`, NOT in `portfolio_risk_engine`).

Rewrite targets:
- **13 test files**: `from core import realized_performance_analysis as rpa` → `from core import realized_performance as rpa`
- **`mcp_tools/performance.py`**: → `from core.realized_performance.aggregation import analyze_realized_performance`
- **`services/portfolio_service.py`**: same pattern
- **`services/performance_helpers.py`**: → `from core.realized_performance import nav as rpa_nav`
- **`tests/providers/test_registry_parity.py`**: → `from core.realized_performance.pricing import _build_default_price_registry`
- **`tests/providers/test_price_chain.py`**: → `from core.realized_performance.pricing import _fetch_price_from_chain`
- **`scripts/ibkr_*.py`**: diagnostic scripts, same import rewrite
- **`tests/conftest.py`**: `core.realized_performance_analysis.TRANSACTION_STORE_READ` → `core.realized_performance._helpers.TRANSACTION_STORE_READ`

**Verified:** `core/realized_performance/__init__.py` exports every public name from `realized_performance_analysis.py` (runtime parity confirmed, only `annotations` extra in package).

---

## Summary

| Phase | Shims deleted | External import sites | Internal core/PRE rewrites | Risk |
|-------|:---:|:---:|:---:|------|
| Phase 1 | 12 | ~33 | ~15 (core/ + PRE/) | None |
| Phase 2 | 3 | ~24 | ~10 (core/ + tests) | None |
| Phase 3 | 3 | ~72 | ~13 (core/ + realized_perf) | Low (largest, mechanical) |
| Phase 4 | 1 | ~24 | 1 (conftest monkeypatch) | Low (wrapper pattern) |
| **Total** | **19** | **~153** | **~39** | |

---

## Verification

After all phases:
1. `python3 -m pytest tests/ -x --no-header -q` — full test suite
2. `python3 -c "import app; import mcp_server; import fmp_mcp_server"` — entry points
3. `python3 -c "import services; import services.portfolio_service"` — services package
4. Verify no remaining shim imports (all 3 import forms):
   ```bash
   SHIMS="asset_class_performance|config_adapters|constants|data_objects|exceptions|exit_signals|income_projection|optimization|performance_analysis|performance_metrics_engine|portfolio_config|portfolio_risk_score|risk_flags|risk_helpers|risk_profiles|risk_summary|scenario_analysis|stock_analysis|realized_performance_analysis"
   # Form 1: from core.SHIM import ...
   rg "from core\.(${SHIMS}) import" --glob '*.py' --glob '!.claude/**'
   # Form 2: from core import SHIM
   rg "from core import (${SHIMS})\\b" --glob '*.py' --glob '!.claude/**'
   # Form 3: import core.SHIM
   rg "import core\.(${SHIMS})\\b" --glob '*.py' --glob '!.claude/**'
   ```
   All three should return zero matches.
5. Verify no circular shim deps in portfolio_risk_engine/:
   ```bash
   rg "from core\.(${SHIMS})" --glob '*.py' portfolio_risk_engine/
   ```
6. Verify monkeypatch targets updated:
   ```bash
   rg "core\.(${SHIMS})\." --glob '*.py' tests/
   ```
7. `ls core/*.py | wc -l` — should drop from ~50 to ~31
