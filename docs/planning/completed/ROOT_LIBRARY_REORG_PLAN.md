# Root Library Module Reorg
**Status:** DONE

## Context

After the CLI runner cleanup (32→23 root files), 23 Python files remain at root. Of these, only ~4 are true entry points (`app.py`, `mcp_server.py`, `fmp_mcp_server.py`, `settings.py`). The other ~19 are library modules and shims that belong in package directories. Moving them makes `pyproject.toml` packaging clean — just list package dirs, no loose `py_modules`.

## Goal

Move root library modules into their natural package directories. Root goes from 23 → 4-5 files (entry points + config only).

## Approach

Each moved file gets a **thin shim** left at root that re-imports from the new location. This avoids a big-bang import rewrite. Shims can be removed later in a follow-up pass once all importers are updated.

Exception: the 4 existing shims (`portfolio_risk.py`, `data_loader.py`, `factor_utils.py`, `portfolio_optimizer.py`) which re-export from `portfolio_risk_engine/` — these stay as-is since they bridge to an external package.

**Note on `.ipynb_checkpoints/`**: Importer counts below exclude `docs/`, `.claude/`, `archive/`, `backup/`, `__pycache__/`, and `.ipynb_checkpoints/`. Checkpoint files are stale notebook artifacts and should not block moves.

---

## Phase 1: Minimal-risk moves (0-2 importers, no root cross-deps)

| File | Destination | Importers | Notes |
|------|-------------|-----------|-------|
| `dev_monitor.py` | `utils/dev_monitor.py` | 1 (`app.py`) | Dev tooling |
| `ai_function_registry.py` | `utils/ai_function_registry.py` | 1 (test only: `tests/utils/test_parameter_alignment.py`) | AI function registry |
| `position_metadata.py` | `services/position_metadata.py` | 2 (`app.py`, `services/portfolio_service.py`) | Position enrichment |

**Action**: `git mv` each file, leave thin shim at root, update importers to new path.

## Phase 2: Low-risk moves (2-4 importers)

| File | Destination | Importers | Notes |
|------|-------------|-----------|-------|
| `risk_helpers.py` | `core/risk_helpers.py` | 3 (`core/portfolio_analysis.py`, `run_risk.py`, `portfolio_risk_engine/portfolio_optimizer.py`) | Risk computation |
| `risk_summary.py` | `core/risk_summary.py` | 2 (`portfolio_risk_engine/stock_analysis.py`, `run_risk.py`) | Risk formatting |
| `helpers_input.py` | `utils/helpers_input.py` | 3 (`portfolio_risk_engine/portfolio_optimizer.py`, `run_risk.py`, `tests/utils/test_basic_functionality.py`) | Input parsing |
| `helpers_display.py` | `utils/helpers_display.py` | 4 (`core/result_objects/optimization.py`, `portfolio_risk_engine/portfolio_optimizer.py`, `run_risk.py`, `tests/utils/test_basic_functionality.py`) | Display formatting — **exports `_drop_factors`** (see shim note) |
| `schwab_client.py` | `providers/schwab_client.py` | 4 (`providers/normalizers/schwab.py`, `providers/schwab_positions.py`, `providers/schwab_transactions.py`, `scripts/run_schwab.py`) | Schwab API |

**Action**: `git mv` each file, leave thin shim at root, update importers to new path.

## Phase 3: Medium-risk moves (5-9 importers)

| File | Destination | Importers | Notes |
|------|-------------|-----------|-------|
| `gpt_helpers.py` | `utils/gpt_helpers.py` | 5 (`app.py`, `core/interpretation.py`, `proxy_builder.py`, `run_risk.py`, `services/security_type_service.py`) | AI interpretation |
| `run_portfolio_risk.py` | `core/run_portfolio_risk.py` | 5 (`core/portfolio_analysis.py`, `core/result_objects/performance.py`, `portfolio_risk_engine/portfolio_optimizer.py`, `run_risk.py`, `tests/core/test_run_portfolio_risk_limits.py`) | Exports `latest_price()`, `standardize_portfolio_input()`, `load_portfolio_config()` |
| `plaid_loader.py` | `providers/plaid_loader.py` | 7 (`providers/plaid_positions.py`, `routes/plaid.py`, `routes/provider_routing.py`, `services/position_service.py`, `trading_analysis/data_fetcher.py`, `scripts/explore_transactions.py`, `scripts/run_plaid.py`) | Plaid SDK wrapper |
| `portfolio_risk_score.py` | `core/portfolio_risk_score.py` | 7 (`app.py`, `core/result_objects/risk.py`, `run_risk.py`, `services/portfolio/context_service.py`, `tests/core/test_portfolio_risk_score_fund_weight_exemption.py`, `tests/core/test_risk_score_nan_guards.py`, `tests/core/test_temp_file_refactor.py`) | Risk scoring |

**Action**: `git mv` each file, leave thin shim at root, update importers to new path.

## Phase 4: Higher-risk moves (10+ importers)

| File | Destination | Importers | Notes |
|------|-------------|-----------|-------|
| `proxy_builder.py` | `core/proxy_builder.py` | 12 (`app.py`, `core/factor_intelligence.py`, `inputs/returns_calculator.py`, `run_risk.py`, `mcp_tools/risk.py`, `services/factor_intelligence_service.py`, `services/factor_proxy_service.py`, `services/security_type_service.py`, `utils/sector_config.py`, `tests/services/test_proxy_builder_paths.py`, `tests/trading_analysis/test_futures_ticker_collision.py`, `admin/manage_security_types.py`) | Factor proxy ETF builder |
| `snaptrade_loader.py` | `providers/snaptrade_loader.py` | 12 (`providers/snaptrade_positions.py`, `routes/provider_routing.py`, `routes/snaptrade.py`, `services/position_service.py`, `trading_analysis/data_fetcher.py`, 5 tests, 2 scripts) | SnapTrade SDK wrapper |
| `run_risk.py` | `core/risk_orchestration.py` | 8 (`app.py`, `core/interpretation.py`, `scripts/run_positions.py`, `services/optimization_service.py`, `services/portfolio/context_service.py`, `services/portfolio_service.py`, `tests/api/test_api_endpoints.py`, `tests/utils/test_basic_functionality.py`) | Risk analysis orchestration — **rename** since it's not a CLI runner |

**Note on `run_risk.py` destination**: This file moves to `core/risk_orchestration.py`, NOT `services/`. Moving it under `services/` would create a circular import: `run_risk` shim → `services.risk_orchestration` → triggers `services/__init__.py` which eagerly imports `services.portfolio_service` and `services.optimization_service`, both of which import `run_risk` — deadlock. The `core/` package has no eager `__init__` imports, so it's safe.

**Action**: `git mv` each file (rename `run_risk.py` → `core/risk_orchestration.py`), leave thin shim at root, update importers to new path.

## Phase 5: Existing shims (leave as-is)

These 4 files are thin re-export wrappers for `portfolio_risk_engine/`. They stay at root — they're the bridge between the internal package namespace and the external published package:

| File | Importers | What it re-exports |
|------|-----------|-------------------|
| `portfolio_risk.py` | 10 | `build_portfolio_view()`, `get_returns_dataframe()`, etc. |
| `data_loader.py` | 23 | Data loading utilities |
| `factor_utils.py` | 15 | Factor analysis utilities |
| `portfolio_optimizer.py` | 2 | Optimizer wrappers |

**Decision**: Leave at root for now. Moving these shims is high churn for minimal gain. They can be eliminated in a future pass by updating all ~50 importers to use `portfolio_risk_engine.*` directly.

---

## Shim Pattern

Each moved file leaves a thin shim at root for backward compatibility. Two variants:

### Standard shim (no private names exported):

```python
# risk_helpers.py (root shim)
"""Shim — moved to core/risk_helpers.py"""
from core.risk_helpers import *  # noqa: F401,F403
```

### Private-name shim (for modules that export `_`-prefixed names):

```python
# helpers_display.py (root shim)
"""Shim — moved to utils/helpers_display.py"""
from utils.helpers_display import *  # noqa: F401,F403
from utils.helpers_display import _drop_factors  # noqa: F401
```

**Why**: `import *` skips names starting with `_` unless `__all__` is defined. Two active callers import `_drop_factors` by name (`core/result_objects/optimization.py:619`, `portfolio_risk_engine/portfolio_optimizer.py:31`). The explicit re-import in the shim ensures backward compatibility.

**Before creating each shim**, check the module for `_`-prefixed names that are imported elsewhere. If found, add explicit re-imports.

This means:
- Existing code keeps working immediately (no import changes required on day 1)
- New code should import from the real location
- Shims can be removed later when all importers are updated

## Post-Move: Update Importers (Optional Follow-Up)

After all moves complete, a separate pass can update importers to use the real paths and remove shims. This is lower priority — the shims add no runtime cost and keep things working.

---

## Summary

| Phase | Files | Importers (max) | Risk |
|-------|-------|-----------------|------|
| Phase 1 | 3 | 0-2 | Minimal |
| Phase 2 | 5 | 2-4 | Low |
| Phase 3 | 4 | 5-9 | Medium |
| Phase 4 | 3 | 8-12 | Higher |
| Phase 5 | 4 (stay) | 2-23 | N/A (no move) |

**Root goes from 23 → 3 entry points + `settings.py` + 4 existing shims + up to 15 new shims = 23 files temporarily.**

After shim removal follow-up: **root → 3 entry points (`app.py`, `mcp_server.py`, `fmp_mcp_server.py`) + `settings.py` (config) + 4 existing shims = 8 files.**

## Files to Modify

Per phase:
- `git mv` the file to destination
- Create thin shim at original root location (standard or private-name variant)
- Optionally update direct importers to use new path (reduces shim dependency)

## Verification

Per phase:
1. `python3 -c "from OLD_MODULE import KNOWN_EXPORT"` — verify shim works for public names
2. `python3 -c "from OLD_MODULE import _PRIVATE_NAME"` — verify shim works for private names (if applicable)
3. `python3 -c "from NEW.MODULE import KNOWN_EXPORT"` — verify new path works
4. `python3 -m pytest tests/ -x --no-header -q -k "RELEVANT_TEST"` — run related tests
5. `python3 -c "import app; import mcp_server; import fmp_mcp_server"` — verify entry points still work
6. `python3 -c "import run_risk"` — verify no circular imports after Phase 4
7. `python3 -c "import services; import services.portfolio_service; import services.optimization_service"` — verify services package still loads after Phase 4

## Notes

- Move order matters: `run_risk.py` imports from 10 other root files — move it last (Phase 4).
- `run_risk.py` must go to `core/`, NOT `services/`. `services/__init__.py` has eager imports of `portfolio_service` and `optimization_service`, which both import `run_risk` — this would create a circular import if `run_risk` moved under `services/`.
- `proxy_builder.py` imports from `gpt_helpers.py` and `data_loader.py` — move `gpt_helpers` first (Phase 3), `data_loader` stays (Phase 5 shim).
- `run_portfolio_risk.py` imports from `portfolio_risk.py` and `factor_utils.py` — both stay as shims (Phase 5), so no conflict.
- `helpers_display.py` exports `_drop_factors` (underscore-prefixed) — shim must explicitly re-import this name since `import *` skips it.
- The 4 existing shims in Phase 5 bridge to `portfolio_risk_engine` (external package). They serve a different purpose than the new move-shims and should stay until a dedicated migration replaces all importers.
- `.ipynb_checkpoints/` files are stale notebook artifacts. They are not counted as importers and do not block moves. They may break after moves but this is acceptable — they are not production code.
