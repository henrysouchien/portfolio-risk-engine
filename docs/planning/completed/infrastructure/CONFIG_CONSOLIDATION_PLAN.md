# Config Consolidation Plan

_Status: **APPROVED** (Codex R3 PASS)_

## Context

`settings.py` is an 853-line monolithic file imported widely across the codebase. It mixes user resolution logic, provider routing tables, risk thresholds, factor intelligence defaults, trading config, and brokerage credentials. The goal is to shrink it by extracting cohesive groups into their natural package homes, without creating cross-package coupling.

**Key constraint**: Package-local configs (`ibkr/config.py`, `brokerage/config.py`) that load from env directly are *correct* — they're self-contained. The "duplication" with settings.py is a feature (standalone packages). We do NOT make packages import from each other.

**Strategy**: Extract cohesive groups *out of settings.py* into either (a) their natural owning package or (b) a new utils/ module. Re-export from settings.py for backward compatibility. Each package keeps its own env loading.

## Phase 1: Extract user resolution → `utils/user_context.py` (HIGH VALUE)

**Why**: Lines 22-148 of settings.py (~126 lines) are a self-contained user resolution subsystem. 9 MCP tool files import `resolve_user_email` + `format_missing_user_error`, plus `news_events.py` and `run_risk.py` import `get_default_user`. These have zero coupling to any other settings — they only use `os`, `pathlib`, `functools.lru_cache`, and read from `.env`.

**What moves** (settings.py lines 22-148):
- `RISK_MODULE_USER_EMAIL_ENV` constant
- `_default_dotenv_path()`, `_normalize_email_value()`, `_read_key_from_env_file()`, `_read_env_or_dotenv()`
- `resolve_default_user()`, `get_default_user_context()`, `resolve_user_email()`, `format_missing_user_error()`, `get_default_user()`

**Files to modify**:
- **NEW** `utils/user_context.py` — All user resolution code moves here (leaf module: imports only `os`, `pathlib`, `functools`)
- **`settings.py`** — Replace lines 22-148 with re-exports:
  ```python
  from utils.user_context import (
      RISK_MODULE_USER_EMAIL_ENV,
      _normalize_email_value, _read_key_from_env_file, _read_env_or_dotenv,
      resolve_default_user, get_default_user_context,
      resolve_user_email, format_missing_user_error,
      get_default_user,
  )
  ```
  **Critical**: `_read_env_or_dotenv` must be re-exported because:
  - Schwab config (settings.py lines 833-846) calls it directly
  - `providers/routing.py` imports it from settings (line 31)

**Importers (no changes needed — re-exports cover them)**:
- `mcp_tools/risk.py`, `mcp_tools/performance.py`, `mcp_tools/trading.py`, `mcp_tools/positions.py`, `mcp_tools/tax_harvest.py`, `mcp_tools/trading_analysis.py`, `mcp_tools/factor_intelligence.py`, `mcp_tools/income.py`, `mcp_tools/signals.py` — import `resolve_user_email` + `format_missing_user_error`
- `mcp_tools/news_events.py` — imports `get_default_user`
- `mcp_server.py` — imports `get_default_user_context` + `format_missing_user_error`
- `run_risk.py` — imports `get_default_user`
- `scripts/plaid_reauth.py` — imports `get_default_user`
- `providers/routing.py` — imports `_read_env_or_dotenv`

**Verification**: `python -c "from settings import resolve_user_email, _read_env_or_dotenv"` + `python -c "from utils.user_context import resolve_user_email"` + `pytest tests/mcp_tools/ -x`

## Phase 2: Extract provider routing tables → `providers/routing_config.py` (MEDIUM VALUE)

**Why**: settings.py contains ~279 lines of routing tables and institution mappings. These belong in the `providers/` package alongside `providers/routing.py` which is their primary consumer.

**What moves** (routing tables and institution mappings only, lines 502-780, ~279 lines):
- `PROVIDER_PRIORITY_CONFIG` (line 502)
- `PROVIDER_CAPABILITIES` + documentation (lines 510-610)
- `PROVIDER_ROUTING_CONFIG` (lines 612-618)
- `INSTITUTION_PROVIDER_MAPPING` + documentation (lines 669-706)
- `TRANSACTION_ROUTING`, `POSITION_ROUTING` (lines 727-740)
- `DEFAULT_POSITION_PROVIDERS`, `DEFAULT_TRANSACTION_PROVIDERS` (lines 744-756)
- `TRANSACTION_FETCH_POLICY` (lines 762-768)
- `INSTITUTION_SLUG_ALIASES` + documentation (lines 775-780)

**What stays in settings.py** (credentials, not routing):
- All SnapTrade credential vars (`SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, etc., lines 487-499) — consumed by `brokerage/config.py` self-contained loading, not by routing
- `ENABLE_SNAPTRADE` (line 491)
- `PROVIDER_CREDENTIALS` (line 824)
- `PROVIDER_CACHE_HOURS` (line 849)
- All Schwab, IBKR, trading config

**Files to modify**:
- **NEW** `providers/routing_config.py` — Routing tables and institution mappings (leaf module: imports only `os`)
- **`settings.py`** — Replace extracted lines with re-exports from `providers.routing_config`
- **`providers/routing.py`** — Change `from settings import DEFAULT_POSITION_PROVIDERS, ...` → `from providers.routing_config import ...` (within-package import, no boundary violation)

**Importers (no changes needed — re-exports cover them)**:
- `trading_analysis/data_fetcher.py` — imports `INSTITUTION_SLUG_ALIASES`, `TRANSACTION_FETCH_POLICY` from settings
- `routes/provider_routing_api.py` — imports `INSTITUTION_PROVIDER_MAPPING`, `PROVIDER_CAPABILITIES`, `PROVIDER_ROUTING_CONFIG` from settings
- `tests/providers/test_transaction_providers.py` — monkeypatches `settings.TRANSACTION_FETCH_POLICY` (re-export preserves this)

**Circular import safety**: `providers/routing_config.py` must NOT import from `settings` — it's a leaf module. Settings re-exports from it, not the other way around.

**Verification**: `python -c "from providers.routing_config import INSTITUTION_PROVIDER_MAPPING"` + `python -c "from settings import INSTITUTION_PROVIDER_MAPPING"` + `pytest tests/providers/ -x`

## Phase 3: Re-export IBKR gateway vars from `ibkr/config.py` (LOW VALUE)

**Why**: Lines 811-819 of settings.py duplicate what `ibkr/config.py` already has. Since ibkr/config.py is the package-local source of truth, settings.py should re-export from it instead of loading from env independently.

**What changes**:
- **`settings.py`** — Replace IBKR gateway env var loading (lines 812-819) with:
  ```python
  from ibkr.config import (
      IBKR_GATEWAY_HOST, IBKR_GATEWAY_PORT, IBKR_CLIENT_ID,
      IBKR_TIMEOUT, IBKR_READONLY, IBKR_AUTHORIZED_ACCOUNTS,
  )
  ```
  Keep in settings.py: `IBKR_ENABLED` (feature flag), `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY_ID` (Flex credentials — not in ibkr/config.py)
- **`brokerage/config.py`** — No changes. Self-contained package.
- **`ibkr/config.py`** — No changes. Already correct.

**Verification**: `python -c "from settings import IBKR_GATEWAY_HOST"` + `pytest tests/ -k ibkr -x`

## Phase 4: No-op (documentation only)

- **`portfolio_risk_engine/config.py`** — Already correct standalone-with-fallback pattern. No changes.
- **YAML files** — Stay at root, loaded by dedicated functions with DB fallback. No changes.
- **`utils/config.py`** — 23 importers, infrastructure config. Low value to consolidate. Skip.
- **`brokerage/config.py`** — Self-contained, correct pattern. No changes.

## Summary

| Phase | Lines removed from settings.py | Risk | Boundary violation? |
|-------|-------------------------------|------|---------------------|
| 1: user_context | ~126 | Zero | No — new utils/ leaf module |
| 2: routing_config | ~279 | Low | No — within providers/ package |
| 3: IBKR re-export | ~8 | Zero | No — settings re-exports from ibkr/ |
| Total | ~413 lines | | settings.py: 853 → ~440 lines |

## Key Files

| File | Action |
|------|--------|
| `settings.py` (853 lines) | Shrink to ~440 via extraction + re-exports |
| **NEW** `utils/user_context.py` | Phase 1: user resolution subsystem |
| **NEW** `providers/routing_config.py` | Phase 2: routing tables + institution mappings |
| `providers/routing.py` | Phase 2: update imports to within-package |
| `ibkr/config.py` (39 lines, unchanged) | Phase 3: settings.py re-exports from here |
| `brokerage/config.py` (52 lines, unchanged) | No changes — self-contained |

## Design Decisions

1. **No config/ directory** — Over-engineering. Extract into natural package homes.
2. **No pydantic BaseSettings** — Adds dependency for minimal benefit.
3. **No cross-package imports** — `brokerage/config.py` keeps its own env loading. `ibkr/config.py` keeps its own env loading. Neither imports from the other or from `providers/`.
4. **Backward-compatible re-exports** — settings.py re-exports everything so all existing importers (widespread across the codebase) continue working unchanged.
5. **`_read_env_or_dotenv` re-exported** — Schwab config in settings.py uses this utility, and `providers/routing.py` imports it. It moves to user_context.py and is re-exported.
6. **Credentials stay in settings.py** — SnapTrade/Schwab/Plaid credentials are NOT routing tables. They stay in settings.py (or are loaded independently by package-local configs). `providers/routing_config.py` is strictly routing tables and institution mappings.
7. **`providers/routing_config.py` not `providers/config.py`** — More descriptive name, avoids confusion with `brokerage/config.py`.
8. **New modules are leaf modules** — `utils/user_context.py` and `providers/routing_config.py` must NOT import from `settings` to avoid circular imports.
9. **Each phase is an independent commit** — Self-contained, testable, revertible.
10. **Monkeypatch compatibility** — Tests that monkeypatch `settings.TRANSACTION_FETCH_POLICY` etc. continue working because re-exports make the symbol available on the `settings` module.

## Verification

After each phase:
1. `python -c "from settings import <moved_var>"` — re-exports work
2. `python -c "from <new_location> import <moved_var>"` — canonical import works
3. Phase 1: `pytest tests/mcp_tools/ -x`
4. Phase 2: `pytest tests/providers/ -x`
5. Phase 3: `pytest tests/ -k ibkr -x`
6. After all: `pytest tests/ -x --timeout=30`
