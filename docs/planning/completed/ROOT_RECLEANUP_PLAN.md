# Root Directory Re-Cleanup Plan

**Status:** REVIEW v7
**Date:** 2026-03-19

## Context
A git recovery event (commit `c73b2866`) restored ~55 files to root that had been deleted/moved in prior cleanup commits (shim removal, root reorg, structural cleanup). The import rewrites survived — **zero callers** reference root paths — so these files are pure dead weight. The root currently has ~30 .py files, 10 YAMLs, and 4 docs that don't belong.

## Codex Review v1 Findings (addressed below)

Codex flagged 4 real issues:
1. **`core/realized_performance_analysis.py`** (6,579 lines) imports `factor_utils` and `data_loader` by root path — but this is the OLD monolith replaced by `core/realized_performance/` (11 submodules). Zero Python callers. **Delete it too.**
2. **`README_PACKAGE.md`** is referenced by `pyproject.toml` (readme + sdist include). **Keep at root.**
3. **`scripts/update_secrets.sh:58`** checks for `run_risk.py`. **Update the reference.**
4. **`resolve_config_path()`** checks CWD first (line 12-13), then `config/`, then project root. When running from project root, CWD == project root, so root YAMLs would be found first. After deleting root copies, `config/` copies will be found. **This is the desired behavior** — no issue.

Other Codex findings were circular (root files importing each other — all being deleted together).

## Approach: Single-Pass Delete + Move

Since all import rewrites survived and there are zero callers of root paths (outside the root files themselves), this is a safe bulk delete. Minor code change needed: `scripts/update_secrets.sh` reference update.

### Evidence: Zero External Callers

Anchored grep confirms no non-root Python file imports from root module paths:
```
$ grep -rn '^from portfolio_risk import\|^from data_loader import\|^from plaid_loader import\|^from snaptrade_loader import\|^from proxy_builder import\|^from run_risk import' --include='*.py' core/ services/ mcp_tools/ routes/ providers/ utils/ inputs/ trading_analysis/ database/ fmp/ ibkr/ app_platform/ portfolio_risk_engine/
# (zero results)
```

The only callers are other root files being deleted in the same pass.

---

## Step 1: Delete Shim .py Files (7 files)

Zero import sites. All target modules in `portfolio_risk_engine/` exist.

```
rm data_loader.py factor_utils.py portfolio_optimizer.py portfolio_risk.py \
   portfolio_risk_score.py risk_helpers.py risk_summary.py
```

## Step 2: Delete Root run_* Scripts (11 files)

9 have updated copies in `scripts/` (with `python3 -m scripts.run_X` invocations).
2 (`run_portfolio_risk.py`, `run_risk.py`) are root-only legacy runners — **delete** (not move). They import root modules being deleted in Steps 1/3, so moving would break them. Canonical replacements: `core/run_portfolio_risk.py` (library module with `latest_price()`, `standardize_portfolio_input()`, `load_portfolio_config()`) and `core/risk_orchestration.py` (has `__main__` CLI at line 1011). Note: `core/run_portfolio_risk.py` is a library module, not a CLI — the root `run_portfolio_risk.py` CLI functionality is not preserved, but it was unused.

```
# Delete all 11:
rm run_cache.py run_factor_intelligence.py run_ibkr_data.py run_options.py \
   run_plaid.py run_positions.py run_schwab.py run_snaptrade.py run_trading_analysis.py \
   run_portfolio_risk.py run_risk.py
```

## Step 3: Delete Root Library Modules (9 files) + Stale Monolith

Zero import sites by root path (outside other root files being deleted). All functionality lives in packages.

| File | Size | Canonical Location |
|------|------|--------------------|
| `plaid_loader.py` | 40KB | `brokerage/plaid/` |
| `snaptrade_loader.py` | 97KB | `brokerage/snaptrade/` |
| `proxy_builder.py` | 35KB | `core/proxy_builder.py` |
| `gpt_helpers.py` | 9KB | `utils/gpt_helpers.py` |
| `helpers_display.py` | 14KB | `utils/helpers_display.py` |
| `helpers_input.py` | 5KB | `utils/helpers_input.py` |
| `position_metadata.py` | 3KB | `utils/position_metadata.py` |
| `schwab_client.py` | 430B | `brokerage/schwab/client.py` |
| `ai_function_registry.py` | 25KB | `services/agent_registry.py` |

```
rm plaid_loader.py snaptrade_loader.py proxy_builder.py gpt_helpers.py \
   helpers_display.py helpers_input.py position_metadata.py schwab_client.py \
   ai_function_registry.py

# Stale monolith replaced by core/realized_performance/ package (11 submodules):
rm core/realized_performance_analysis.py
```

## Step 4: Delete Duplicate YAML Files (8 files)

6 are byte-identical to `config/` copies. `cash_map.yaml` root is stale (109 lines vs config/ 28 lines — `resolve_config_path` uses config/ via `_CONFIG_DIR`). `risk_limits_adjusted.yaml` only referenced in docs (no code callers). `what_if_portfolio.yaml` only referenced in a comment in `portfolio_optimizer.py:679` (no `open()` or `resolve_config_path()` calls).

```
# Identical duplicates — safe delete:
rm asset_etf_proxies.yaml exchange_etf_proxies.yaml exchange_mappings.yaml \
   industry_to_etf.yaml portfolio.yaml risk_limits.yaml security_type_mappings.yaml

# Stale root version (config/ is canonical):
rm cash_map.yaml

# Root-only but unused in code — move to config/ for safety:
mv risk_limits_adjusted.yaml config/
mv what_if_portfolio.yaml config/
```

## Step 5: Move Root Docs (3 files) + Keep README_PACKAGE.md

`README_PACKAGE.md` must stay at root — `pyproject.toml:9` references it as readme and `pyproject.toml:32` includes it in sdist.

```
mv AI_CONTEXT.md docs/
mv architecture.md docs/
rm RELEASE_PLAN.md  # already exists in docs/
# README_PACKAGE.md — KEEP AT ROOT (pyproject.toml dependency)
```

## Step 6: Delete fmp_mcp_server.py

159-byte wrapper calling `fmp.server.main()`. Invocation is `python3 -m fmp.server`.

```
rm fmp_mcp_server.py
```

## Step 7: Clean Up Stale PID Files + .gitignore

```
rm .fmp_mcp_server_*.pid .excel_mcp_server.pid
```

Add to `.gitignore`:
```
*.pid
```

## Step 8: Delete __pycache__ at Root

```
rm -rf __pycache__
```

Verify `__pycache__` is already in `.gitignore` (it should be).

## Step 9: Fix Shell Script + CI References

**`scripts/update_secrets.sh`**:
- Line 22: references `plaid_loader.py` — update or remove
- Line 58: checks `if [ ! -f "run_risk.py" ]` — remove check (file deleted, not moved)

**`scripts/backup_system.sh`**:
- Lines 94, 97, 154: reference `architecture.md` and `AI_CONTEXT.md` at root — update to `docs/architecture.md`, `docs/AI_CONTEXT.md`

**`.github/workflows/sync-to-public.yml`**:
- Lines 9, 67, 92, 97: watches/copies root `.py`, `.md`, `.yaml` files — update paths to match new locations

## Step 10: Clean Up Stale sys.modules Guards

4 defensive `sys.modules.get("core.realized_performance_analysis")` checks in `core/realized_performance/` (fx.py:72, nav.py:836, pricing.py:68, engine.py:2325). Won't break if left, but should be removed since the monolith is deleted.

## Step 11: Sweep All Stale References (grep-based)

Rather than enumerating individual files, run a comprehensive grep sweep for all deleted module/file names and fix every hit. This catches docs, comments, docstrings, JSON fixtures, shell scripts, and archive files.

```bash
# Sweep pattern — all root modules/files being deleted.
# Matches both "module.py" and bare "module" references (imports, docstrings, comments).
grep -rn --include='*.py' --include='*.md' --include='*.json' --include='*.sh' --include='*.yml' --include='*.yaml' --include='*.txt' --include='*.toml' \
  -E '\b(data_loader|factor_utils|portfolio_optimizer|portfolio_risk_score|risk_helpers|risk_summary|run_risk|run_portfolio_risk|run_cache|run_factor_intelligence|run_ibkr_data|run_options|run_plaid|run_positions|run_schwab|run_snaptrade|run_trading_analysis|plaid_loader|snaptrade_loader|proxy_builder|gpt_helpers|helpers_display|helpers_input|position_metadata|schwab_client|ai_function_registry|fmp_mcp_server|realized_performance_analysis)\b' \
  --exclude-dir='.git' --exclude-dir='node_modules' --exclude-dir='__pycache__' \
  --exclude-dir='docs/planning/completed' \
  --exclude='ROOT_RECLEANUP_PLAN.md' .
```

**Exclude from sweep** (not actionable): `docs/planning/completed/` (historical plan docs that reference old paths — fine to leave as-is).

For each hit, triage:
- **False positives (ignore)**: Package-qualified references like `core.run_portfolio_risk`, `scripts.run_plaid`, `brokerage.plaid` — these are legitimate references to canonical locations
- **Code imports** (should be zero after Steps 1-3) — rewrite to package path
- **Docstrings/comments** referencing root paths — update to canonical path or remove
- **Docs/markdown** referencing root paths — update to canonical path
- **archive/** files — update or delete stale archive files (e.g., `archive/test_snaptrade_basic_mock.py`)
- **JSON fixtures** — update paths
- **requirements.txt comments** — update or remove

Known categories of hits (non-exhaustive, sweep will find all):
- `core/risk_orchestration.py` docstrings → update root entrypoint references
- `portfolio_risk_engine/portfolio_risk_score.py` docstrings → update root references
- `core/result_objects/{performance,risk}.py` docstrings → update root references
- `docs/reference/`, `docs/architecture/`, `docs/guides/`, `docs/interfaces/` → update paths
- `tests/utils/current_api.json` → update module paths
- `scripts/README.md` → update invocation examples
- `archive/test_snaptrade_basic_mock.py` → delete (imports deleted `snaptrade_loader`)

---

## Verification

1. `git diff --stat` — confirm deletions/moves + expected reference updates
2. `python -c "import app; print('ok')"` — app entry point still works
3. `python -c "from core.factor_intelligence import load_cash_proxies; print(load_cash_proxies())"` — config path resolution works
4. `python -m pytest tests/ -x -q --timeout=30 -k "not slow"` — no import breakage
5. Count root .py files: should be 3 (`app.py`, `mcp_server.py`, `settings.py`)
6. Re-run the Step 11 grep sweep — review remaining hits. Package-qualified references (`core.run_portfolio_risk`, `scripts.run_plaid`, etc.) are expected and fine. Only root-path references (e.g., bare `python run_risk.py`, `from plaid_loader import`) need fixing.

---

## Expected Result

**Before**: ~35 root .py files, 10 YAMLs, 4 stray docs, 12 PID files
**After**: 3 .py files (`app.py`, `mcp_server.py`, `settings.py`) + standard project files (`CLAUDE.md`, `Readme.md`, `CHANGELOG.md`, `LICENSE`, `Makefile`, `README_PACKAGE.md`, `pyproject.toml`, `pytest.ini`, `requirements*.txt`, `services.yaml`, `package.json`, lockfiles)

## Files Summary
- `.gitignore` — add `*.pid`
- `scripts/update_secrets.sh` — update `run_risk.py` + `plaid_loader.py` references
- `scripts/backup_system.sh` — update `architecture.md` + `AI_CONTEXT.md` paths
- `.github/workflows/sync-to-public.yml` — update root file paths
- `core/realized_performance/{fx,nav,pricing,engine}.py` — remove stale `sys.modules.get()` guards
- `core/risk_orchestration.py` — update docstrings referencing root entrypoints
- `portfolio_risk_engine/portfolio_risk_score.py` — update docstrings referencing root entrypoints
- All stale root path references swept and updated (grep-based, docs/comments/fixtures/archive)
- 2 files moved to `config/` (`risk_limits_adjusted.yaml`, `what_if_portfolio.yaml`)
- 2 files moved to `docs/` (`AI_CONTEXT.md`, `architecture.md`)
- ~39 files deleted from root (+ `core/realized_performance_analysis.py` + `archive/test_snaptrade_basic_mock.py`)
- `README_PACKAGE.md` — kept at root (pyproject.toml dependency)
