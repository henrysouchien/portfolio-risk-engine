# Provider-Agnostic Ticker Aliasing — Decouple FMP Naming from Core Architecture

## Context

The `fmp_ticker_map` parameter (mapping IBKR tickers to FMP-compatible symbols, e.g. `AT` → `AT.L`) is threaded through ~130 files with ~1,145 total occurrences. While the *concept* of ticker aliasing is provider-agnostic, the *naming* (`fmp_*`) hardcodes FMP as the assumed data provider.

**Goal**: Make the core architecture provider-agnostic so swapping FMP for another data provider (Bloomberg, Polygon, etc.) doesn't require renaming 1000+ references.

## Rename Rules

### Rule 1: Blanket Python identifier rename

**Every** Python identifier (variable, parameter, field, function name, local variable, class attribute) containing `fmp_ticker` or `fmp_symbol` is renamed, with these substitutions:
- `fmp_ticker_map` → `ticker_alias_map`
- `fmp_ticker` (standalone) → `ticker_alias`
- `fmp_symbol` → `data_symbol`

This applies to ALL `.py` files in the repo **including `fmp/` package internals** (see Rule 6 for why).

Additional function renames:
| Old | New |
|-----|-----|
| `select_fmp_symbol` | `resolve_ticker_alias` |
| `infer_fmp_currency` | `infer_currency` |
| `normalize_fmp_price` | `normalize_minor_currency_price` |
| `_resolve_futures_fmp_symbol` | `_resolve_futures_alias` |
| `should_skip_fmp_profile_lookup` | `should_skip_profile_lookup` |
| `resolve_fmp_ticker` | `resolve_ticker_from_exchange` |
| `filter_fmp_eligible` | remove (already has `filter_price_eligible`) |
| Batch helpers: `fetch_fmp_quote_with_currency`, `fetch_batch_fmp_*` | Drop `fmp_` prefix |

### Rule 2: Blanket string literal rename

**Every** string literal containing `"fmp_ticker_map"`, `"fmp_ticker"`, or `"fmp_symbol"` used as:
- Dict keys (`cfg.get("fmp_ticker_map")`, `position["fmp_ticker"]`)
- JSON keys / serialization
- DataFrame `.attrs` keys or column labels
- Schema/field name strings (e.g. in `position_schema.py`)
- Attribute-name strings (e.g. `getattr(obj, "fmp_ticker")`)
- Log messages, docstrings, and comments referencing old names

is renamed to the corresponding new name. The verification grep (Rule 8) catches any missed instances.

### Rule 3: Database schema rename

| Table | Old Column | New Column |
|-------|-----------|------------|
| `positions` | `fmp_ticker` | `ticker_alias` |
| `futures_contracts` | `fmp_symbol` | `data_symbol` |

Requires:
- `database/schema.sql`: rename column definitions (lines ~153, ~678)
- `database/migrations/`: **new** migration file with `ALTER TABLE ... RENAME COLUMN`. Historical migration files (`20260201_add_fmp_ticker.sql`, `20260309_add_instrument_reference_tables.sql`) are **NOT rewritten** — they are historical records. They are excluded from the verification grep.
- `inputs/database_client.py`: ALL SQL referencing these columns
- `scripts/backfill_fmp_tickers.py` → `scripts/backfill_ticker_aliases.py` (rename file + update SQL)
- `scripts/seed_reference_data.py`: update any column refs

**Rollout order**: DB migration runs FIRST (adds new column name), then code deploy. The `ALTER TABLE RENAME COLUMN` is atomic in PostgreSQL — old name stops working immediately, so code and migration must deploy together or migration runs just before code.

### Rule 4: YAML / config file rename

| File | Old Key | New Key |
|------|---------|---------|
| `brokerage/futures/contracts.yaml` | `fmp_symbol` | `data_symbol` |
| Any portfolio YAML with `fmp_ticker_map` key | `fmp_ticker_map` | `ticker_alias_map` |

### Rule 5: File renames

| Old Path | New Path |
|----------|----------|
| `scripts/debug_fmp_ticker_map.py` | `scripts/debug_ticker_alias_map.py` |
| `scripts/backfill_fmp_tickers.py` | `scripts/backfill_ticker_aliases.py` |

### Rule 6: fmp/ package IS included in rename

Unlike earlier plan revisions, `fmp/` package **IS** renamed. The `fmp/compat.py` functions accept `fmp_ticker` / `fmp_ticker_map` kwargs that are called from `providers/fmp_price.py` and `portfolio_risk_engine/_fmp_provider.py`. Excluding `fmp/` would require a translation layer at every adapter boundary. Instead, rename the kwargs inside `fmp/compat.py` too — the parameter names are internal to our codebase, not part of the FMP API itself.

What stays FMP-named inside `fmp/`:
- Class names: `FMPClient`, `FMPError`, etc. (these describe the provider implementation)
- Module names: `fmp/client.py`, `fmp/cache.py`, `fmp/compat.py`, etc.
- FMP API endpoint names and field names from the FMP API response schema
- `fmp/server.py` MCP server identity

### Rule 7: Module names NOT renamed

These module/class names correctly describe FMP-specific implementations:
- `fmp/` package directory and all module names within
- `providers/fmp_price.py`, `providers/fmp_metadata.py`, class names `FMPProvider`, `FMPProfileProvider`
- `portfolio_risk_engine/_fmp_provider.py` module name
- `brokerage/futures/sources/fmp.py` module name

### Rule 8: Verification grep

Post-rename, this command should return ONLY:
- FMP class/module names (Rule 7)
- FMP API field names inside `fmp/` package
- Migration files in `database/migrations/` (both historical AND the new rename migration, which necessarily contains old column names in `ALTER TABLE RENAME COLUMN` statements)
- Backward-compat aliases

```bash
rg -n 'fmp_ticker|fmp_symbol|select_fmp_symbol|infer_fmp_currency|normalize_fmp_price|resolve_fmp_ticker|_resolve_futures_fmp|should_skip_fmp|fetch_fmp_quote|fetch_batch_fmp|filter_fmp_eligible' --glob '*.py' --glob '*.sql' --glob '*.yaml' | grep -v __pycache__ | grep -v 'database/migrations/'
```

## Phases

### Phase 1: Big-Bang Atomic Rename

Single atomic commit applying Rules 1-6 across ALL source, test, SQL, and YAML files simultaneously.

**Backward-compat shims** (temporary, remove in future pass):
- `PortfolioData`: property alias `fmp_ticker_map` → `ticker_alias_map` (getter + setter)
- `utils/ticker_resolver.py`: `select_fmp_symbol = resolve_ticker_alias` (+ other renamed functions)
- `portfolio_risk_engine/_ticker.py`: `select_fmp_symbol = resolve_ticker_alias`, `infer_fmp_currency = infer_currency`
- **YAML dual-read**: At every site that reads a YAML/config dict key, accept both old and new key using a **presence-based check** (not `or`, which fails on empty `{}`): `cfg.get("ticker_alias_map") if "ticker_alias_map" in cfg else cfg.get("fmp_ticker_map")`. Confirmed sites:
  - `portfolio_config.py:455` — `load_portfolio_config()`
  - `returns_calculator.py:100` — returns config loading
  - `core/proxy_builder.py:634` — proxy config loading
  - `core/proxy_builder.py:930` — proxy config loading
  - `core/proxy_builder.py:1013` — proxy config loading
  - `risk_helpers.py:428` — risk config loading
  - `data_objects.py:1146` — `from_yaml()` ingestion
  - `config_adapters.py:130` — config adapter extraction
  - `scripts/debug_ticker_alias_map.py` (renamed from `debug_fmp_ticker_map.py`) — debug script YAML read
- **Position dict dual-read**: At position ingestion boundaries, accept both `"ticker_alias"` and `"fmp_ticker"` with new name taking precedence.
- **Cache invalidation**: Flush Redis on deploy. In-process caches are ephemeral. On-disk YAML temp artifacts are overwritten on next run.

### Phase 2: Consolidate Duplicate Resolution

Small follow-up commit. Both functions use lazy imports to avoid circular dependency:

- **`resolve_ticker_alias()`**: Keep canonical in `utils/ticker_resolver.py`. Make `portfolio_risk_engine/_ticker.py` import from there (already no circular risk — `ticker_resolver.py` does not import from `portfolio_risk_engine`).
- **`infer_currency()`**: Keep canonical in `portfolio_risk_engine/_ticker.py` (uses registry). Make `utils/ticker_resolver.py` delegate via **lazy import** inside the function body: `from portfolio_risk_engine._ticker import infer_currency`. This avoids the top-level circular import.
- **`normalize_minor_currency_price()`**: Keep in `portfolio_risk_engine/_ticker.py` only, import elsewhere.

### Phase 3: Verify No Residual FMP Coupling

Run Rule 8 verification grep. Any unexpected hits get fixed.

## What's NOT in Scope

- `security_type_service.py` already goes through `ProfileMetadataProvider` via registry. No coupling to fix.
- Creating new protocols (TickerResolver, etc.) — the simple dict-lookup doesn't need a protocol.
- Frontend response contract — `"fmp_ticker"` is emitted in position response payloads from `app.py` and `routes/onboarding.py`, but **the frontend has zero references** to `fmp_ticker`, `fmpTicker`, `fmp_symbol`, or `fmpSymbol` (confirmed via grep of `frontend/`). The field is emitted but never consumed. This is an **intentional breaking API rename** with no actual breakage — no frontend code reads these fields. The response keys will change to `"ticker_alias"` / `"data_symbol"` as part of Rule 2. No dual-write shim is needed.

## Critical Files (highest impact)

| File | Occurrences | Notes |
|------|------------|-------|
| `portfolio_risk_engine/portfolio_risk.py` | 72 | Pass-through + JSON serialization + futures alias resolution |
| `portfolio_risk_engine/portfolio_optimizer.py` | 34 | Pass-through, low test coverage |
| `mcp_tools/income.py` | 38 | Per-position field + local vars |
| `services/position_service.py` | 30 | Resolution + locals (`raw_fmp_symbol`, `missing_fmp_tickers`) |
| `fmp/compat.py` | 22 | Kwarg names in function signatures — now included in rename |
| `portfolio_risk_engine/data_objects.py` | 29 | Central data structure + YAML + ingestion |
| `inputs/database_client.py` | ~20 | SQL column refs — migration required |
| `providers/snaptrade_loader.py` | 27 | Position dict emission boundary |
| `app.py` | 24 | Entry point extraction |
| `core/proxy_builder.py` | 19 | Proxy generation + YAML config reads |

## Codex Review History

### Round 1 (9 findings → FAIL)
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | CRITICAL | Backward-compat shims wrong hook points | R3: YAML dual-read rule. R4: corrected line refs, added proxy_builder:1013 |
| 2 | CRITICAL | Phase 1/3 inconsistent on fmp_symbol | R2: merged into Phase 1 |
| 3 | HIGH | Missed function renames | R2: added to rename map |
| 4 | HIGH | More runtime boundaries | R3: Rule 1+2 blanket approach |
| 5 | HIGH | Dict/JSON/attrs string keys | R3: Rule 2 blanket. R4: expanded to cover DataFrame cols, schema fields, attribute strings |
| 6 | HIGH | Redis/pickle cache | R2: added FLUSHDB |
| 7 | MEDIUM | _fmp_provider.py contents need renaming | R2: clarified |
| 8 | MEDIUM | Verification grep incomplete | R3: comprehensive rg pattern. R4: added historical migration exclusion |
| 9 | MEDIUM | Test coverage gap | Noted — manual verification for portfolio_optimizer.py |

### Round 2 (6 findings → FAIL)
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | CRITICAL | Backward-compat shims still wrong sites | R3: restructured as rule + site list. R4: corrected config_adapters to :130, added proxy_builder:1013 |
| 2 | CRITICAL | DB migration missed schema.sql, seeds, contracts.yaml | R3: Rule 3+4 added. R4: clarified historical migrations NOT rewritten |
| 3 | HIGH | Dict key list incomplete | R3: Rule 2 blanket |
| 4 | MEDIUM | Missed local vars | R3: Rule 1 covers all identifiers |
| 5 | MEDIUM | Verification grep incomplete | R3: comprehensive pattern. R4: added migration exclusion |
| 6 | LOW | On-disk YAML artifacts | R3: clarified |

### Round 3 (5 findings → FAIL)
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | CRITICAL | fmp/ exclusion breaks adapter boundary — compat.py still expects old kwargs | R4: Rule 6 — fmp/ IS included in rename. Kwargs in compat.py are our code, not FMP API names |
| 2 | CRITICAL | YAML dual-read list wrong refs + missing site | R4: corrected config_adapters.py to :130, added proxy_builder:1013 |
| 3 | HIGH | Rules 1-2 don't cover DataFrame cols, schema fields, attribute strings, log messages | R4: Rule 2 expanded to explicitly cover these categories |
| 4 | HIGH | DB historical migrations + rollout order | R4: Rule 3 clarifies historical migrations NOT rewritten + excluded from grep. Rollout order documented |
| 5 | MEDIUM | Phase 2 circular import risk | R4: explicit lazy import strategy documented |

### Round 4 (3 findings → FAIL)
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | Dual-read `or` fails on empty `{}` — silently revives stale aliases | R5: presence-based check (`if "key" in cfg`) instead of `or` |
| 2 | MEDIUM | New rename migration also contains old names — grep exclusion too narrow | R5: grep excludes ALL `database/migrations/` files |
| 3 | LOW | Debug script YAML read site not listed | R5: added to dual-read site list |

### Round 5 (1 finding → FAIL)
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | API responses emit `"fmp_ticker"` — breaking rename with no compat plan | R6: confirmed frontend has ZERO references to these fields (grep verified). Intentional rename, no actual breakage. Documented explicitly. |
