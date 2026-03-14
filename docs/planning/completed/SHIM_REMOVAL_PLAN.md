# Root Shim Removal Plan
**Status:** DONE

## Context

After the library module reorg (`53e92f9c`), 15 thin re-export shims remain at root. Each shim is just `from new.path import *`. The real code now lives in `core/`, `utils/`, `providers/`, `services/`. This plan updates all importers to use the real paths, then deletes the shims and `sys.modules` aliases.

**Note on "real path" bridges**: Some target modules (`core/risk_summary.py`, `core/risk_helpers.py`, `core/portfolio_risk_score.py`) are themselves thin re-exports from `portfolio_risk_engine.*`. And `providers/schwab_client.py` re-exports from `brokerage/schwab/client.py`. This plan only removes the ROOT shims — the package-level bridges stay (they serve a different purpose: package API encapsulation).

## Goal

Delete all 15 root shims. Root goes from 23 → 8 files (3 entry points + `settings.py` + 4 existing package bridge shims).

## Approach

Update import statements in-place — no shims, no backward compat needed. After all imports are updated, delete the shim files and remove `sys.modules` aliases from the moved modules.

**Scope**: Only active source tree. `backup/` is explicitly excluded — it contains stale snapshots that are never imported at runtime or by tests.

---

## Phase 1: Low-importer shims (1-2 importers each)

| Shim | Real path | Importers to update |
|------|-----------|-------------------|
| `ai_function_registry` | `utils.ai_function_registry` | `tests/utils/test_parameter_alignment.py:26` |
| `dev_monitor` | `utils.dev_monitor` | `app.py:973`, `app.py:1066` |
| `position_metadata` | `services.position_metadata` | `app.py:3590`, `services/portfolio_service.py:1465` |
| `risk_summary` | `core.risk_summary` | `portfolio_risk_engine/stock_analysis.py:34`, `core/risk_orchestration.py:24` |

**Total**: 4 shims, 7 import sites.
**Action**: Update imports, then `rm` each shim.

## Phase 2: Medium-importer shims (3-5 importers each)

| Shim | Real path | Importers to update |
|------|-----------|-------------------|
| `helpers_input` | `utils.helpers_input` | `portfolio_risk_engine/portfolio_optimizer.py:759`, `core/risk_orchestration.py:449`, `tests/utils/test_basic_functionality.py:87` (`import helpers_input`) |
| `helpers_display` | `utils.helpers_display` | `portfolio_risk_engine/portfolio_optimizer.py:31`, `portfolio_risk_engine/portfolio_optimizer.py:764`, `core/result_objects/optimization.py:619`, `core/risk_orchestration.py:55`, `tests/utils/test_basic_functionality.py:90` (`import helpers_display`) |
| `risk_helpers` | `core.risk_helpers` | `portfolio_risk_engine/portfolio_optimizer.py:1148`, `core/portfolio_analysis.py:44`, `core/risk_orchestration.py:47` |
| `schwab_client` | `providers.schwab_client` | `providers/schwab_positions.py:17`, `providers/normalizers/schwab.py:447`, `providers/schwab_transactions.py:22`, `scripts/run_schwab.py:12` |

**Total**: 4 shims, 15 import sites.
**Action**: Update imports, then `rm` each shim.

## Phase 3: Higher-importer shims (5-7 importers each)

| Shim | Real path | Importers to update |
|------|-----------|-------------------|
| `gpt_helpers` | `utils.gpt_helpers` | `app.py:221`, `app.py:1827`, `services/security_type_service.py:1259`, `core/interpretation.py:23`, `core/proxy_builder.py:7`, `core/risk_orchestration.py:51` |
| `run_portfolio_risk` | `core.run_portfolio_risk` | `core/portfolio_analysis.py:39`, `core/result_objects/performance.py:638`, `core/risk_orchestration.py:33`, `core/risk_orchestration.py:398`, `portfolio_risk_engine/portfolio_optimizer.py:16`, `portfolio_risk_engine/portfolio_optimizer.py:47`, `portfolio_risk_engine/portfolio_optimizer.py:65`, `tests/core/test_run_portfolio_risk_limits.py:3` |
| `portfolio_risk_score` | `core.portfolio_risk_score` | `app.py:218`, `services/portfolio/context_service.py:33`, `core/risk_orchestration.py:905`, `core/result_objects/risk.py:2171`, `tests/core/test_portfolio_risk_score_fund_weight_exemption.py:4` (`import ... as prs`), `tests/core/test_risk_score_nan_guards.py:9` (`import ... as prs`), `tests/core/test_temp_file_refactor.py:16` |
| `run_risk` | `core.risk_orchestration` | `app.py:217`, `app.py:1384`, `app.py:5234`, `app.py:5654`, `services/portfolio/context_service.py:32`, `services/optimization_service.py:46`, `services/portfolio_service.py:36`, `services/portfolio_service.py:37`, `services/portfolio_service.py:637`, `scripts/run_positions.py:105`, `core/interpretation.py:59`, `tests/api/test_api_endpoints.py:157`, `tests/api/test_api_endpoints.py:209`, `tests/utils/test_basic_functionality.py:59` (`import run_risk`) |

**Note**: `run_risk` → `core.risk_orchestration` is a **rename**, not just a path change.

**Total**: 4 shims, 35 import sites.
**Action**: Update imports, then `rm` each shim.

## Phase 4: High-importer shims (8-12 importers each)

| Shim | Real path | Importers to update |
|------|-----------|-------------------|
| `proxy_builder` | `core.proxy_builder` | `app.py:220`, `app.py:1370`, `app.py:5336`, `app.py:5483`, `app.py:5650`, `app.py:5766`, `core/factor_intelligence.py:63`, `core/proxy_builder.py:1088` (self-referential lazy import), `core/risk_orchestration.py:50`, `core/risk_orchestration.py:450`, `core/risk_orchestration.py:1030`, `inputs/returns_calculator.py:71`, `mcp_tools/risk.py:449`, `utils/sector_config.py:49`, `services/factor_proxy_service.py:45`, `services/factor_intelligence_service.py:912`, `services/factor_intelligence_service.py:1140`, `services/security_type_service.py:157`, `services/security_type_service.py:1214`, `admin/manage_security_types.py:49`, `tests/services/test_proxy_builder_paths.py:4`, `tests/trading_analysis/test_futures_ticker_collision.py:261` (`import proxy_builder`), `tests/trading_analysis/test_futures_ticker_collision.py:406` (`import proxy_builder`) |
| `plaid_loader` | `providers.plaid_loader` | `routes/plaid.py:156`, `routes/plaid.py:1007`, `routes/plaid.py:1226`, `routes/provider_routing.py:451`, `routes/provider_routing.py:504`, `scripts/run_plaid.py:18`, `scripts/explore_transactions.py:124`, `services/position_service.py:633`, `services/position_service.py:681`, `providers/plaid_positions.py:30`, `providers/plaid_positions.py:31`, `trading_analysis/data_fetcher.py:414` |
| `snaptrade_loader` | `providers.snaptrade_loader` | `routes/snaptrade.py:145`, `routes/provider_routing.py:420`, `routes/provider_routing.py:481`, `scripts/run_snaptrade.py:25`, `scripts/explore_transactions.py:30`, `services/position_service.py:637`, `services/position_service.py:692`, `providers/snaptrade_positions.py:30`, `trading_analysis/data_fetcher.py:213`, `tests/api/test_snaptrade_integration.py:29`, `tests/api/test_snaptrade_integration.py:399`, `tests/api/test_snaptrade_integration.py:412`, `tests/api/test_snaptrade_integration.py:473`, `tests/snaptrade/test_snaptrade_registration.py:17`, `tests/snaptrade/test_snaptrade_credentials.py:13`, `tests/snaptrade/test_snaptrade_integration.py:62`, `tests/snaptrade/test_snaptrade_existing_user.py:12`, `tests/snaptrade/test_snaptrade_existing_user.py:59` |

**Total**: 3 shims, 53 import sites.
**Action**: Update imports AND monkeypatch `sys.modules` string keys, then `rm` each shim.

## Phase 5: Remove `sys.modules` aliases from moved modules

All 15 moved modules have `sys.modules["OLD_NAME"] = sys.modules[__name__]` entries for compatibility. After all importers are updated, these are dead code:

| File | Line | Alias to remove |
|------|------|----------------|
| `utils/ai_function_registry.py` | 33 | `_sys.modules["ai_function_registry"]` |
| `utils/dev_monitor.py` | 17 | `_sys.modules["dev_monitor"]` |
| `utils/gpt_helpers.py` | 14 | `_sys.modules["gpt_helpers"]` |
| `utils/helpers_display.py` | 10 | `_sys.modules["helpers_display"]` |
| `utils/helpers_input.py` | 28 | `_sys.modules["helpers_input"]` |
| `services/position_metadata.py` | 13 | `_sys.modules["position_metadata"]` |
| `core/proxy_builder.py` | 16 | `_sys.modules["proxy_builder"]` |
| `core/risk_orchestration.py` | 20 | `_sys.modules["run_risk"]` |
| `core/risk_summary.py` | 3 | `sys.modules["risk_summary"]` |
| `core/risk_helpers.py` | 3 | `sys.modules["risk_helpers"]` |
| `core/portfolio_risk_score.py` | 3 | `sys.modules["portfolio_risk_score"]` |
| `core/run_portfolio_risk.py` | 14 | `_sys.modules["run_portfolio_risk"]` |
| `providers/plaid_loader.py` | 36 | `_sys.modules["plaid_loader"]` |
| `providers/schwab_client.py` | 14 | `_sys.modules["schwab_client"]` |
| `providers/snaptrade_loader.py` | 53 | `_sys.modules["snaptrade_loader"]` |

**Action**: Remove each `sys.modules` alias line. Total: 15 removals.

---

## Hot Files (multiple shim imports)

These files import from multiple shims and need the most edits:

| File | Shims imported | Import sites |
|------|---------------|-------------|
| `app.py` | 6 (dev_monitor, position_metadata, run_risk, portfolio_risk_score, proxy_builder, gpt_helpers) | 16 |
| `core/risk_orchestration.py` | 8 (risk_summary, run_portfolio_risk ×2, risk_helpers, proxy_builder ×3, gpt_helpers, helpers_display, helpers_input) | 10 |
| `portfolio_risk_engine/portfolio_optimizer.py` | 3 (helpers_input, helpers_display ×2, risk_helpers, run_portfolio_risk ×3) | 7 |
| `services/portfolio_service.py` | 2 (run_risk ×3, position_metadata) | 4 |
| `services/position_service.py` | 2 (plaid_loader ×2, snaptrade_loader ×2) | 4 |
| `routes/provider_routing.py` | 2 (plaid_loader ×2, snaptrade_loader ×2) | 4 |

## Test Monkeypatch Updates

These test files use `monkeypatch.setitem(sys.modules, "OLD_NAME", ...)` which needs the string key updated:

| File | Old key | New key | Sites |
|------|---------|---------|-------|
| `tests/trading_analysis/test_provider_routing.py` | `"plaid_loader"` | `"providers.plaid_loader"` | 1 |
| `tests/providers/test_transaction_providers.py` | `"plaid_loader"` | `"providers.plaid_loader"` | 3 |
| `tests/providers/test_transaction_providers.py` | `"snaptrade_loader"` | `"providers.snaptrade_loader"` | 4 |

---

## Summary

| Phase | Shims removed | Import sites | Risk |
|-------|--------------|-------------|------|
| Phase 1 | 4 (1-2 importers) | 7 | Low |
| Phase 2 | 4 (3-5 importers) | 15 | Low |
| Phase 3 | 4 (5-7 importers) | 35 | Medium |
| Phase 4 | 3 (8-12 importers) | 53 | Medium |
| Phase 5 | 0 (cleanup) | 15 alias removals | Low |
| **Total** | **15** | **110 import edits + 8 monkeypatch + 15 alias removals = 133** | |

## Verification

After each phase:
1. `python3 -m pytest tests/ -x --no-header -q` — full test suite
2. `python3 -c "import app; import mcp_server; import fmp_mcp_server"` — entry points
3. `python3 -c "import services; import services.portfolio_service"` — services package

After Phase 5 (final):
4. Verify no remaining import references (anchored pattern, both forms):
   ```
   rg -n '^\s*(from\s+(ai_function_registry|dev_monitor|gpt_helpers|helpers_display|helpers_input|plaid_loader|portfolio_risk_score|position_metadata|proxy_builder|risk_helpers|risk_summary|run_portfolio_risk|run_risk|schwab_client|snaptrade_loader)\s+import|import\s+(ai_function_registry|dev_monitor|gpt_helpers|helpers_display|helpers_input|plaid_loader|portfolio_risk_score|position_metadata|proxy_builder|risk_helpers|risk_summary|run_portfolio_risk|run_risk|schwab_client|snaptrade_loader)\b)' --glob '*.py' --glob '!docs/**' --glob '!.claude/**' --glob '!archive/**' --glob '!backup/**' --glob '!.ipynb_checkpoints/**'
   ```
   Note: This may still match string literals (e.g., `scripts/collect_all_schemas.py` schema strings) — those are not real imports and can be ignored.
5. `ls *.py | wc -l` should be 8
