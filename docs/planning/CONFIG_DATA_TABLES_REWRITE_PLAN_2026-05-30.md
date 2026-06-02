# Plan: Rewrite `docs/reference/CONFIG_DATA_TABLES.md`

**Date:** 2026-05-30 · **Status:** for Codex review → implement
**Why:** The Batch-2 autonomous draft fabricated ~30 file paths, functions, and mechanisms
(config/database.yaml, inputs/risk_config.py, 5 nonexistent utils/etf_mappings.py functions,
5 nonexistent utils/config.py functions, a DB feature-flag subsystem, wrong YAML key structures,
nonexistent config/ YAML files). That draft must be replaced with a fully grep-verified doc.

**Contract:** every concrete claim in the rewritten doc must carry a `file:line` citation
matching the facts below. Anything not in "Verified facts" must NOT be asserted as existing.

---

## Verified facts (grep-confirmed; the writer cites these)

### 1. Config files that EXIST in config/

All in `config/`. Verified via `ls config/`:

| File | Top-level keys | Purpose |
|---|---|---|
| `config/industry_to_etf.yaml` | 174 industry-name keys (Title-Case: "Technology", "Healthcare", ...) — NOT wrapped under `industry_proxies:` | Industry → ETF proxy mapping for factor analysis |
| `config/risk_limits.yaml` | `portfolio_limits`, `concentration_limits`, `variance_limits`, `max_single_factor_loss` — NO `leverage_limits` key | Risk limit defaults |
| `config/cash_map.yaml` | `proxy_by_currency`, `cash_equivalent_tickers`, `alias_to_currency` | Cash ticker classification |
| `config/routing.yaml` | `positions`, `trades`, `transactions` | Runtime routing overrides |
| `config/stress_scenarios.yaml` | `interest_rate_shock`, `credit_spread_widening`, `bear_flattener` (and more) | Stress scenario definitions |
| `config/security_type_mappings.yaml` | `provider_mappings`, `crash_scenarios`, `canonical_types` | Security type classification |
| `config/asset_etf_proxies.yaml` | (verify at write time) | Asset class ETF proxies |
| `config/exchange_etf_proxies.yaml` | (verify at write time) | Exchange ETF proxies |
| `config/exchange_mappings.yaml` | (verify at write time) | Exchange name mappings |
| `config/portfolio.yaml` | (verify at write time) | Portfolio config defaults |
| `config/api_budget_costs.py` | Python module: `COST_PER_CALL` dict (`:32`), `SUBSCRIPTION_COSTS_PER_ITEM_MONTH` (`:59`), `SNAPTRADE_PER_CONNECTED_USER_MONTH_RATE` (`:72`) | API cost config |
| `config/profile_overrides.yaml` | (verify at write time) | Agent profile overrides |
| `config/sector_overrides.yaml` | (verify at write time) | Sector classification overrides |
| `config/strategy_templates.yaml` | (verify at write time) | Strategy templates |
| `config/what_if_portfolio.yaml` | (verify at write time) | What-if analysis config |
| `config/editorial_memory_seed.json` | (verify at write time) | Editorial memory seed |

**Files that do NOT exist** (do not cite):
`config/database.yaml`, `config/settings.py`, `config/proxy_defaults.py`,
`config/portfolio_defaults.py`, `config/leverage_limits.yaml`, `config/expected_returns.yaml`,
`config/example_returns.yaml`, `config/api_keys.yaml`, `config/edgar_keys.yaml`,
`config/edgar_tickers.yaml`, `config/dividend_calendar.yaml`,
`config/products/hank/PRODUCTS.yaml`, `config/PRODUCTS.yaml`, `config/CHANNELS.yaml`

### 2. DB tables that ARE the config/reference store (from `database/schema.sql`)

| Table | Purpose | Seeded from |
|---|---|---|
| `industry_proxies` | Industry → ETF proxy (matches `industry_to_etf.yaml`) | `admin/manage_reference_data.py` |
| `exchange_proxies` | Exchange → ETF proxy (matches `exchange_etf_proxies.yaml`) | `admin/manage_reference_data.py` |
| `factor_proxies` | Factor → ETF proxy | `admin/manage_reference_data.py` |
| `futures_contracts` | Futures contract specs (matches `contracts.yaml` in brokerage-connect) | `scripts/seed_reference_data.py:38` |
| `exchange_resolution_config` | Exchange resolution config | (verify at write time) |
| `user_factor_groups` | Per-user factor grouping | (verify at write time) |
| `subindustry_peers` | Subindustry peer groups | migration `20250801_add_subindustry_peers.sql` |
| `security_types` | Canonical security type cache | `services/security_type_service.py` |
| `security_type_mappings` | Provider code → canonical type | `admin/manage_reference_data.py` |
| `security_type_scenarios` | Security type → crash scenario | `admin/manage_reference_data.py` |

Table names are as stated — no `reference_` prefix (the fabricated draft used `reference_industry_proxies` etc.).

### 3. Code that actually reads these configs

**`utils/etf_mappings.py`** — actual functions (verified via grep):
- `get_etf_to_industry_map()` (`utils/etf_mappings.py:15`) — DB-first (calls `DatabaseClient.get_canonical_etf_to_industry()`), YAML fallback via `is_reference_database_available()`. Returns `Dict[str, str]` (ETF ticker → industry name).
- `format_ticker_with_label(ticker, ...)` (`utils/etf_mappings.py:65`) — formatting helper.
- **Does NOT have**: `_load_mappings()`, `get_all_mappings()`, `get_etf_for_industry()`, `industry_proxies()`, `_mappings_cache`, `reload_mappings()` — these were fabricated.

**`utils/config.py`** — actual functions (verified via grep):
- `gpt_enabled()` (`utils/config.py:58`)
- `snaptrade_enabled()` (`utils/config.py:104`)
- `load_yaml_config(file_path)` (`utils/config.py:139`)
- `save_yaml_config(data, file_path)` (`utils/config.py:151`)
- `validate_portfolio_data(data)` (`utils/config.py:162`)
- **Does NOT have**: `is_database_enabled()`, `should_use_database_for_risk_limits()`, `should_use_database_for_portfolios()`, `should_use_database_for_factor_proxies()`, `get_database_features()` — these were fabricated.

**`inputs/risk_limits_manager.py`** — the actual risk-limits loader (`inputs/risk_limits_manager.py:64`):
- `RiskLimitsManager` class (`:64`) with `load_risk_limits(portfolio_name)` (`:180`).
- DB-first, YAML fallback: loads from `risk_limits.yaml` (default) or `risk_limits_adjusted.yaml`.
- **`inputs/risk_config.py` does NOT exist.**

**`inputs/database_client.py`** — reference-data DB methods (verified via grep):
- `get_exchange_mappings()` (`:2862`)
- `get_futures_contracts()` (`:2905`)
- `get_exchange_resolution_config()` (`:2930`)
- `get_industry_mappings()` (`:3098`)
- `get_industry_asset_class()` (`:3481`)
- `get_industry_sector_groups()` (`:3520`)
- `get_risk_limits()` (`:4155`)
- **Does NOT have**: `get_risk_config()`, `get_portfolio()` — these were fabricated.

**`settings.py:95`** — `PORTFOLIO_DEFAULTS` dict (start_date, end_date, normalize_weights, worst_case_lookback_years, expected_returns_lookback_years, expected_returns_fallback_default, cash_proxy_fallback_return). **Lives in `settings.py`, not `config/portfolio_defaults.py`.**

**`admin/manage_reference_data.py`** — the CLI for managing reference data:
- Uses argparse subcommands (`exchange`, `industry`, `security_type`, etc.) — not `DEFAULT_FILES`, `import_cash_map`, `export_cash_map`, `import_industry_proxies`, `import_risk_limits` (those were fabricated).
- Real functions: `list_exchange_mappings`, `sync_exchange_from_yaml`, `add_exchange_proxy`, `delete_exchange_proxy`, `add_industry_proxy`, `set_industry_primary`, `delete_industry_proxy`, `list_security_type_mappings`, `add_security_type_mapping`, `add_crash_scenario` (`:55-282`).

### 4. No DB feature-flag subsystem exists

There is no `config/database.yaml`, no `use_database` / `use_database_portfolios` / `use_database_factor_proxies` flags, and no `is_database_enabled()` / `get_database_features()` functions. The DB-vs-YAML gate is handled per-loader via `utils/reference_data.is_reference_database_available()` (a thin wrapper around `database.is_db_available()`).

---

## Section outline

1. **Overview** — what this doc covers: YAML files in `config/`, DB reference tables that shadow them, and the Python loaders that mediate. One paragraph.
2. **Config YAML files** — table: file → top-level keys → purpose → primary loader. One row per file that exists. No fabricated files.
3. **DB reference tables** — table: table → purpose → seeded-from → admin CLI command. Real table names (no `reference_` prefix).
4. **The DB-vs-YAML gate** — `utils/reference_data.is_reference_database_available()` is the single gate; each loader calls it independently. No global feature-flag system.
5. **Key loaders** — `utils/etf_mappings.py` (actual two functions), `inputs/risk_limits_manager.py`, `admin/manage_reference_data.py` subcommands.
6. **Add-a-config-table checklist** — YAML → admin CLI → seed script → loader function → DB table (per the data-config-not-code-alias rule from CLAUDE.md).

## Acceptance

- Zero references to fabricated files (`config/database.yaml`, `inputs/risk_config.py`, `config/settings.py`, etc.).
- Zero references to fabricated functions (`is_database_enabled`, `get_risk_config`, `get_etf_for_industry`, `_load_mappings`, etc.).
- DB table names match `database/schema.sql` (no `reference_` prefix).
- `industry_to_etf.yaml` top-level keys are industry names (not wrapped under `industry_proxies:`).
- All `file:line` citations match live code.
