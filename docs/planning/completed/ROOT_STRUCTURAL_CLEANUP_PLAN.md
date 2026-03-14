# Root Structural Cleanup Plan
**Status:** DONE

## Context

After deleting all 19 root shims (commits `498392d2`, `6e28e62a`), the root has 4 .py files (clean) but still has 11 YAML configs (9 active + 2 stale), 7 markdown docs, and other loose files cluttering it. This plan moves configs to `config/`, docs to `docs/`, and deletes unused files — reducing root noise while preserving all runtime behavior.

**Goal:** Move YAML configs into `config/`, relocate root docs into `docs/`, delete stale files. Root goes from ~25 non-build files to ~12 (4 .py + standard build/config files).

**Scope:** Active source tree only. `.claude/worktrees/`, `backup/`, `.ipynb_checkpoints/` excluded.

---

## Phase 1: Delete stale files

| File | Evidence |
|------|----------|
| `risk_limits_adjusted.yaml` | 0 references in Python code |
| `what_if_portfolio.yaml` | Only referenced in a comment at `portfolio_risk_engine/portfolio_optimizer.py:679` |

**Action:** `rm risk_limits_adjusted.yaml what_if_portfolio.yaml`

---

## Phase 2: Move root docs to `docs/`

| File | Destination |
|------|------------|
| `CHANGELOG.md` | `docs/CHANGELOG.md` |
| `RELEASE_PLAN.md` | `docs/RELEASE_PLAN.md` |
| `TODO.md` | `docs/TODO.md` |
| `README_APP_PLATFORM.md` | `docs/guides/README_APP_PLATFORM.md` |
| `README_FMP_MCP.md` | `docs/reference/README_FMP_MCP.md` |

**Keep at root:** `CLAUDE.md` (required by Claude Code), `readme.md` (standard project README — `docs/README.md` already exists as a docs index, so root readme stays).

**Shell scripts to update:**
- `scripts/sync_app_platform.sh:35` — `cp "$MONOREPO/README_APP_PLATFORM.md"` → update path to `docs/guides/README_APP_PLATFORM.md`
- `scripts/sync_fmp_mcp.sh:39` — `cp "$MONOREPO/README_FMP_MCP.md"` → update path to `docs/reference/README_FMP_MCP.md`
- `scripts/backup_system.sh:94,152` — `CHANGELOG.md` → update path to `docs/CHANGELOG.md`
- `scripts/update_secrets.sh:23-29` — YAML file paths in `FILES_TO_SYNC` array → update to `config/` prefix; also remove stale entries (`risk_limits_adjusted.yaml`, `what_if_portfolio.yaml`)

**Risk:** Low — shell scripts need path updates but are not runtime-critical.

---

## Phase 3: Create `config/` directory and move YAML configs

### 3a. Create centralized config resolver

Create `config/__init__.py` with a `resolve_config_path()` function (based on existing `_resolve_config_path()` in `core/proxy_builder.py:375`):

```python
"""Centralized config file resolution."""
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parent

def resolve_config_path(filename: str) -> Path:
    """Resolve a config filename to its absolute path in the config/ directory."""
    candidate = Path(filename)
    if candidate.is_absolute():
        return candidate
    # Check CWD first (backward compat for tests passing custom paths)
    if candidate.exists():
        return candidate.resolve()
    # Canonical location
    config_candidate = _CONFIG_DIR / candidate
    if config_candidate.exists():
        return config_candidate
    # Fallback: project root (transition period)
    project_root = _CONFIG_DIR.parent
    root_candidate = project_root / candidate
    if root_candidate.exists():
        return root_candidate
    return config_candidate  # return expected path even if missing
```

### 3b. Move YAML files

| File | Destination |
|------|------------|
| `asset_etf_proxies.yaml` | `config/asset_etf_proxies.yaml` |
| `cash_map.yaml` | `config/cash_map.yaml` |
| `exchange_etf_proxies.yaml` | `config/exchange_etf_proxies.yaml` |
| `exchange_mappings.yaml` | `config/exchange_mappings.yaml` |
| `industry_to_etf.yaml` | `config/industry_to_etf.yaml` |
| `security_type_mappings.yaml` | `config/security_type_mappings.yaml` |
| `strategy_templates.yaml` | `config/strategy_templates.yaml` |
| `portfolio.yaml` | `config/portfolio.yaml` |
| `risk_limits.yaml` | `config/risk_limits.yaml` |

**Note:** `ibkr/exchange_mappings.yaml` is a DIFFERENT file (IBKR exchange→MIC mappings vs root's MIC→FMP suffix mappings). It stays in `ibkr/`.

### 3c. Update all YAML load sites

There are 7 load patterns to update. Patterns 1-5 become `from config import resolve_config_path`; Pattern 6 updates relative paths in admin/scripts:

**Pattern 1: `_PROJECT_ROOT / "filename.yaml"` (5+ sites)**
- `portfolio_risk_engine/data_objects.py:73` — `cash_map.yaml`
- `portfolio_risk_engine/data_objects.py:1018` — general config resolve
- `portfolio_risk_engine/portfolio_config.py:478` — general config resolve
- `core/factor_intelligence.py:95` — `asset_etf_proxies.yaml`
- `core/factor_intelligence.py:158` — `cash_map.yaml`
- Remove per-file `_PROJECT_ROOT` definitions from these files (keep non-YAML `_PROJECT_ROOT` per Phase 3d)

**Pattern 2: Local `_resolve_*_path()` resolvers (2 files, 5+ sites)**
- `core/proxy_builder.py:375` — `_resolve_config_path()` used for `exchange_etf_proxies.yaml`, `industry_to_etf.yaml`, other YAML loads
- `portfolio_risk_engine/risk_helpers.py:195` — `_resolve_yaml_path()` used for YAML config resolution
- Replace both local resolvers with `from config import resolve_config_path`

**Pattern 3: `Path(__file__).parent.parent / "filename.yaml"` (3 sites)**
- `app.py` — `strategy_templates.yaml` (`Path(__file__).parent / ...`)
- `utils/ticker_resolver.py:39` — `exchange_mappings.yaml` (`Path(__file__).resolve().parent.parent / ...`)
- `admin/migrate_reference_data.py:92` — `exchange_etf_proxies.yaml` (relative `"../exchange_etf_proxies.yaml"`)

**Pattern 4: Hardcoded default parameter strings `"risk_limits.yaml"` / `"portfolio.yaml"` (~30+ sites)**
- These are default parameter values like `def func(filepath="risk_limits.yaml")` or `base_dir + config_file` patterns
- Update to use `resolve_config_path()` at the call site
- Major files: `core/run_portfolio_risk.py`, `portfolio_risk_engine/portfolio_config.py`, `core/config_adapters.py`, `services/portfolio_service.py`, `inputs/risk_limits_manager.py:113` (`config_file="risk_limits.yaml"`), `inputs/returns_calculator.py:31` (`portfolio_file="portfolio.yaml"`)

**Pattern 5: Bare `Path("filename.yaml")` / `open("filename.yaml")` in source files (10+ sites)**
- `services/security_type_service.py` — `security_type_mappings.yaml`
- `utils/security_type_mappings.py:88` — `Path("security_type_mappings.yaml")` (CWD-relative)
- `utils/etf_mappings.py:27` — `open('industry_to_etf.yaml')` (CWD-relative)
- `inputs/database_client.py` — `cash_map.yaml`, `security_type_mappings.yaml`
- `inputs/portfolio_manager.py:579` — `portfolio.yaml` (bare path)
- `portfolio_risk_engine/portfolio_config.py:96` — `portfolio.yaml` (bare path)
- `providers/plaid_loader.py`, `providers/snaptrade_loader.py` — `cash_map.yaml`
- `settings.py` — `security_type_mappings.yaml`

**Pattern 6: `load_yaml_file()` / `PROJECT_ROOT / "*.yaml"` / argparse defaults in admin/scripts (15+ sites)**
- `admin/migrate_reference_data.py:60,92,131,184,222` — `load_yaml_file()` with relative paths to root YAMLs
- `admin/manage_reference_data.py:126,393` — argparse defaults referencing `cash_map.yaml`, `exchange_etf_proxies.yaml`, `asset_etf_proxies.yaml`; also `open(yaml_path)` consumers
- `scripts/collect_all_schemas.py:110,150,173,194,195` — `PROJECT_ROOT / 'portfolio.yaml'`, `'risk_limits.yaml'`
- `scripts/collect_all_schemas.py:355-379` — CLI string args referencing `"portfolio.yaml"`, `"risk_limits.yaml"`

**Pattern 7: Test files with hardcoded paths (10+ sites)**
- Tests that reference YAML filenames in fixture paths or assertions

**Implementation note:** The patterns above are representative, not exhaustive. The implementer should run the verification greps (see Verification section) after all edits to catch any remaining sites.

### 3d. Keep `_PROJECT_ROOT` for non-YAML uses

`_PROJECT_ROOT` in `utils/logging.py`, `utils/json_logging.py`, `admin/run_migration.py` is used for log dirs and sys.path — NOT for YAML configs. Leave these unchanged.

---

## Phase 4: Delete old local resolvers

After Phase 3, delete the two local resolver functions now replaced by `config.resolve_config_path()`:
- `core/proxy_builder.py:375` — `_resolve_config_path()` (lines 375–390)
- `portfolio_risk_engine/risk_helpers.py:195` — `_resolve_yaml_path()` (lines 195–207)

---

## Hot Files (multiple YAML references)

| File | YAMLs referenced | Sites |
|------|-----------------|-------|
| `core/factor_intelligence.py` | asset_etf_proxies, cash_map + `_PROJECT_ROOT` | 3 |
| `portfolio_risk_engine/data_objects.py` | cash_map + `_PROJECT_ROOT` | 3 |
| `portfolio_risk_engine/portfolio_config.py` | portfolio.yaml, risk_limits + `_PROJECT_ROOT` | 3 |
| `inputs/database_client.py` | cash_map, security_type_mappings, asset_etf_proxies | 3 |
| `services/security_type_service.py` | security_type_mappings, industry_to_etf | 2 |
| `core/proxy_builder.py` | exchange_etf_proxies, industry_to_etf + local resolver | 4 |
| `settings.py` | security_type_mappings | 1 |

---

## Summary

| Phase | Action | Files touched | Risk |
|-------|--------|--------------|------|
| Phase 1 | Delete 2 stale YAMLs | 2 deleted | None |
| Phase 2 | Move 5 docs to `docs/`, update 4 shell scripts | 5 moved + 4 scripts | Low (shell scripts only) |
| Phase 3 | Create `config/`, move 9 YAMLs, update all load sites | ~30 .py files + 9 YAMLs moved | Low (mechanical, testable) |
| Phase 4 | Delete 2 old local resolvers | 2 files (already counted in Phase 3) | None |
| **Total** | | **~50 files touched** (2 deleted + 5 moved + 4 scripts + 9 YAMLs + ~30 .py edits) | |

---

## Verification

After all phases:
1. `python3 -m pytest tests/ -x --no-header -q` — full test suite
2. `python3 -c "import app; import mcp_server; import fmp_mcp_server"` — entry points
3. `python3 -c "from config import resolve_config_path; print(resolve_config_path('cash_map.yaml'))"` — resolver works
4. `python3 -c "import services; import services.portfolio_service"` — services package
5. Verify no remaining direct filesystem loads of root YAML filenames. Run all checks:
   ```bash
   # Check for direct filesystem access patterns that bypass resolve_config_path()
   # These patterns indicate YAML loads that would break after the move:
   rg -n '(Path\(|open\(|PROJECT_ROOT|load_yaml_file|base_dir|with_name\().*\b(asset_etf_proxies|cash_map|exchange_etf_proxies|exchange_mappings|industry_to_etf|security_type_mappings|strategy_templates|portfolio|risk_limits)\.yaml' --glob '*.py' --glob '!docs/**' --glob '!.claude/**' --glob '!config/**' --glob '!tests/**' --glob '!ibkr/**' --glob '!providers/ibkr_positions.py'
   # Also check shell scripts for stale root YAML paths:
   rg -n '\b(asset_etf_proxies|cash_map|exchange_etf_proxies|exchange_mappings|industry_to_etf|security_type_mappings|strategy_templates|portfolio|risk_limits)\.yaml' --glob '*.sh'
   ```
   Both should return zero matches (or only matches with `config/` prefix). Legitimate calls like `resolve_config_path("cash_map.yaml")` are NOT matched by these patterns. `ibkr/exchange_mappings.yaml` loads in `ibkr/` and `providers/ibkr_positions.py` are correctly excluded.

   **Note:** Single-line greps cannot catch split-line patterns where a YAML filename default (e.g., `config_file="risk_limits.yaml"`) is on a different line from the filesystem access (e.g., `Path(self.config_file).read_text()`). After the automated checks, also run:
   ```bash
   # Find all filesystem reads of variables that could hold YAML paths
   rg -n '(\.read_text\(\)|\.is_file\(\)|open\([a-z_]+\)|yaml\.safe_load)' --glob '*.py' --glob '!tests/**' --glob '!.claude/**'
   ```
   Review each match to confirm the variable's source goes through `resolve_config_path()`. Shell script matches in test fixtures (e.g., `setup-e2e-tests.sh`) can be ignored if they use `config/` prefix.
6. `ls *.yaml | wc -l` should be **1** (`pnpm-lock.yaml` only)
7. `ls *.md | wc -l` should be **2** (`CLAUDE.md` + `readme.md`)
