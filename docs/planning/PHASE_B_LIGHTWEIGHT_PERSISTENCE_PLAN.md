# Onboarding Phase B — Lightweight Persistence Plan
**Status:** DEFERRED — CSV import (Phase A Step 2) is higher priority. Plan is Codex-reviewed and approved; ready to implement if needed later.
**Prerequisite:** Phase A (Steps 1-3) — Step 1 done (`ecc66f7d`), Steps 2-3 not started
**Date:** 2026-03-10

## Goal

Extend the no-DB mode from 22 tools to ~37 tools by providing lightweight JSON/YAML-file persistence for user config, baskets, target allocations, instrument config, and audit trail. No PostgreSQL required.

After Phase B, a single-user MCP setup works with:
```
pip install -r requirements.txt
echo "FMP_API_KEY=your_key" > .env
echo "RISK_MODULE_USER_EMAIL=you@example.com" >> .env
claude mcp add portfolio-mcp -e RISK_MODULE_USER_EMAIL=you@example.com -- python mcp_server.py
```
**37+ tools operational.** Only the transaction store and realized performance still require Postgres.

**Note:** `RISK_MODULE_USER_EMAIL` is required for user-scoped tools (baskets, allocations, audit). Step 6 (Local Auth) removes this requirement for the frontend.

---

## Current State

### Phase A Step 1 (Done)
- `is_db_available()` returns False when no `DATABASE_URL`
- `@require_db` decorator on 23 tools returns clear error
- `RiskLimitsManager` falls back to YAML when DB unavailable
- `PortfolioRepository` has file-mode for expected returns
- Sentinel `user_id=0` for no-auth mode

### Tools Blocked by `@require_db` (Phase B targets)

| Category | Tools | Count |
|----------|-------|-------|
| **Baskets** | create_basket, list_baskets, get_basket, update_basket, delete_basket, create_basket_from_etf, analyze_basket | 7 |
| **Basket Trading** | preview_basket_trade, execute_basket_trade | 2 |
| **Allocations** | set_target_allocation, get_target_allocation | 2 |
| **Audit** | record_workflow_action, update_action_status, get_action_history | 3 |
| **Transactions** | ingest_transactions, list_transactions, + 6 more | 8 |
| **Instrument Config** | manage_instrument_config | 1 |

Phase B targets: **Baskets (7) + Basket Trading (2) + Allocations (2) + Audit (3) + Instrument Config (1) = 15 tools**.
Transactions (8) stay Postgres-only — complex batch lifecycle, normalization, and query/reporting flows. See `BROKERAGE_STATEMENT_IMPORT_PLAN.md`.

**Scope clarification — Expected Returns:** Already handled by `PortfolioRepository` file-mode fallback (`get_expected_returns_file()` / `update_expected_returns_file()`). Not part of `ConfigStore` — `PortfolioRepository` remains authoritative for portfolio-level config (positions, expected returns, factor proxies). `ConfigStore` owns only user-level config (baskets, allocations, audit, instrument overrides).

**Scope clarification — Instrument Config:** `manage_instrument_config` is admin CRUD over YAML-seeded reference data (`futures_contracts`, `exchange_resolution_config`, etc.). The DB values are ephemeral — overwritten by `seed_all()`. File-backed persistence is natural here since the canonical source is already YAML.

---

## Architecture: ConfigStore Interface

### Design Decision: JSON Files (not SQLite)
- **Zero additional dependencies** — no `sqlite3` quirks, no migration framework
- **Human-readable** — users can inspect/edit their config files
- **Git-friendly** — config can be version-controlled
- **Pattern exists** — `RiskLimitsManager` YAML fallback already proven
- **Tradeoff**: No SQL queries, but all Phase B data is simple key-value / small collections

### File Layout
```
~/.risk_module/                    # or $RISK_MODULE_DATA_DIR
├── config/
│   ├── risk_limits.yaml           # Already exists (RiskLimitsManager)
│   └── target_allocations.json    # {portfolio_name: {asset_class: pct}}
├── baskets.json                   # All baskets in one file (keyed by exact group_name)
├── instrument_overrides.yaml      # User overrides for YAML-seeded reference data
└── audit/
    └── actions.jsonl              # Append-only JSON Lines (with fcntl file lock)
```

**Note:** Expected returns stay in `PortfolioRepository` file-mode (`config/portfolio.yaml`). Risk limits stay in `RiskLimitsManager` file-mode (`config/risk_limits.yaml`). Both already work without DB.

### ConfigStore Protocol

```python
# inputs/config_store.py

from typing import Protocol, Optional, Any

class ConfigStore(Protocol):
    """Backend-agnostic persistence for user config.

    Constructed with user_id (scoping key). Methods do not repeat user_id.

    NOT included (already have file-mode fallbacks):
    - Risk limits → RiskLimitsManager (use_database + YAML fallback)
    - Expected returns → PortfolioRepository (file-mode)
    """

    # --- Baskets ---
    def create_basket(self, group_name: str, tickers: list, **kwargs) -> dict: ...
    def get_basket(self, group_name: str) -> Optional[dict]: ...
    def list_baskets(self) -> list[dict]: ...
    def update_basket(self, group_name: str, **kwargs) -> dict: ...
    def delete_basket(self, group_name: str) -> bool: ...

    # --- Target Allocations ---
    def get_target_allocations(self, portfolio_name: str) -> dict: ...
    def save_target_allocations(self, portfolio_name: str, allocations: dict) -> None: ...

    # --- Audit Trail ---
    def save_workflow_action(self, **kwargs) -> Optional[str]: ...  # returns action_id or None (non-fatal skip)
    def get_workflow_actions(self, portfolio_name: str, **kwargs) -> list[dict]: ...
    def update_workflow_action_status(self, action_id: str, new_status: str, **kwargs) -> dict: ...

    # --- Instrument Config ---
    def list_contracts(self) -> list[dict]: ...
    def get_contract(self, symbol: str) -> Optional[dict]: ...
    def upsert_contract(self, symbol: str, fields: dict) -> dict: ...
    def delete_contract(self, symbol: str) -> bool: ...
    def get_exchange_config(self) -> dict: ...
    def update_exchange_section(self, section_name: str, section_data: dict) -> dict: ...
```

### Two Implementations

1. **`FileConfigStore`** — JSON/YAML files in `~/.risk_module/` (or `$RISK_MODULE_DATA_DIR`)
   - Single-user, no auth needed
   - Human-readable, git-friendly
   - Used when `DATABASE_URL` not set

2. **`PostgresConfigStore`** — Wraps existing `DatabaseClient` methods
   - Multi-user, auth-scoped
   - Used when `DATABASE_URL` is set
   - Thin adapter over existing DB code — no rewrite

### Resolution

```python
# inputs/config_store.py

def _is_db_configured() -> bool:
    """Return True when DATABASE_URL is set (regardless of connectivity)."""
    import os
    return bool(os.getenv("DATABASE_URL", "").strip())

def get_config_store(user_id: int = 0) -> ConfigStore:
    """Return the appropriate config store backend.

    IMPORTANT: Uses _is_db_configured() (env var check), NOT is_db_available()
    (connectivity check). A production deployment with DATABASE_URL set must
    NEVER silently fall back to file storage during a transient outage — that
    would fork state and break user isolation. File mode is only for setups
    that intentionally omit DATABASE_URL.
    """
    if _is_db_configured():
        return PostgresConfigStore(user_id)
    return FileConfigStore(user_id)
```

---

## Implementation Steps

### Step 1: ConfigStore Protocol + FileConfigStore Core (Allocations)

**Files:**
- NEW: `inputs/config_store.py` — Protocol + `get_config_store()` + `FileConfigStore` + `PostgresConfigStore`

**FileConfigStore internals:**
- `_data_dir()` → `$RISK_MODULE_DATA_DIR` or `~/.risk_module/`
- `_read_json(path)` / `_write_json(path, data)` — atomic write via tempfile + rename
- `_read_yaml(path)` / `_write_yaml(path, data)` — reuse existing YAML helpers
- `_file_lock(path)` — `fcntl.flock()` on a **stable sidecar lock file** (`{path}.lock`) for concurrent MCP request safety. Locking the data file itself is unsafe with tempfile+rename (old inode replaced). The sidecar `.lock` file persists across renames.

**Note:** Risk limits already work without DB via `RiskLimitsManager` YAML fallback. Expected returns already work via `PortfolioRepository` file-mode. Neither needs `ConfigStore`.

**Target Allocations:**
- File: `~/.risk_module/config/target_allocations.json`
- Schema: `{portfolio_name: {asset_class: target_pct, ...}}`
- Full-replace semantics on write (same as DB: DELETE + INSERT)

**Remove `@require_db` from:**
- `mcp_tools/allocation.py`: `set_target_allocation`, `get_target_allocation`

**Tests:** 8-10 unit tests for FileConfigStore read/write/missing-file/concurrent-access behavior

### Step 2: Basket CRUD via ConfigStore

**FileConfigStore basket implementation:**
- Single file: `~/.risk_module/baskets.json` (all baskets in one file, keyed by exact `group_name`)
- **No slugification needed**: Since all baskets are in one JSON file (not individual filenames), the key is the exact `group_name` string — matching DB behavior where `group_name` is a VARCHAR column with exact-match lookups. No path safety concerns because names are JSON keys, not filenames.
- Schema:
  ```json
  {
    "Tech Leaders": {
      "group_name": "Tech Leaders",
      "description": "Large-cap tech basket",
      "tickers": ["AAPL", "MSFT", "GOOGL"],
      "weights": {"AAPL": 0.4, "MSFT": 0.35, "GOOGL": 0.25},
      "weighting_method": "custom",
      "created_at": "2026-03-10T12:00:00Z",
      "updated_at": "2026-03-10T12:00:00Z"
    }
  }
  ```
- `list_baskets()` → read file, return all values sorted by `group_name` (matches DB `ORDER BY group_name`)
- `get_basket()` → read file, lookup by exact group_name
- `create_basket()` → read-modify-write, error if group_name exists
- `update_basket()` → read-modify-write
- `delete_basket()` → read-modify-write, remove entry
- All writes use `_file_lock()` + atomic tempfile+rename

**Refactor `mcp_tools/baskets.py` + `mcp_tools/basket_trading.py`:**
- Replace direct `DatabaseClient` calls with `get_config_store()` calls
- Remove `@require_db` from 7 basket tools + 2 basket trading tools (9 total)
- `basket_trading.py` reads baskets via `store.get_basket()` instead of `DatabaseClient.get_factor_group()`

**PostgresConfigStore basket implementation:**
- Thin wrapper over existing `DatabaseClient.create_factor_group()`, etc.
- No behavior change for DB mode

**Tests:** 10-12 unit tests for basket CRUD + edge cases (duplicate names, missing baskets, concurrent writes)

### Step 3: Audit Trail via ConfigStore

**FileConfigStore audit implementation:**
- File: `~/.risk_module/audit/actions.jsonl` (JSON Lines, append-only)
- Each line = one action record (full snapshot including events)
- `save_workflow_action()` → generate UUID, append JSON line with `fcntl.flock()` lock
- `get_workflow_actions()` → read all lines, deduplicate by action_id (latest wins), filter by portfolio_name/status/workflow, sort by created_at DESC, apply limit/offset
- `update_workflow_action_status()` → read + validate + append new line with updated status

**State machine — IMPORTANT:** The transition validation logic currently lives in `DatabaseClient.update_workflow_action_status()` (lines 1438-1478), NOT in `mcp_tools/audit.py`. It includes:
- `valid_transitions` dict: `pending → {accepted, rejected, expired}`, `accepted → {executed, expired}`
- `terminal_states`: `{rejected, executed, expired}` — no transitions allowed out
- Idempotent no-op when `current_status == new_status`
- User-scoped lookup (action_id + user_id)

This logic must be **extracted into a shared module** (e.g., `inputs/audit_state_machine.py`) that both `FileConfigStore` and `PostgresConfigStore` use. Otherwise file mode will not enforce transitions.

**Design choice — append-only with latest-wins:**
- Each action_id may have multiple JSONL entries (one per status change)
- Read path: scan backwards, collect latest entry per action_id
- Trade-off: Simple append (no file rewriting), slightly slower reads for large files
- For single-user scale (hundreds of actions), performance is fine
- **Rotation**: If file exceeds 10MB, compact by keeping only latest entry per action_id

**Concurrency:** All JSONL appends use `fcntl.flock(LOCK_EX)` advisory lock. MCP server is single-process but may have overlapping async requests.

**Remove `@require_db` from:**
- `mcp_tools/audit.py`: `record_workflow_action`, `update_action_status`, `get_action_history`

**Tests:** 10-12 unit tests for audit CRUD + state machine validation + idempotent transitions + terminal state rejection

### Step 4: Instrument Config via ConfigStore

**Goal:** Make `manage_instrument_config` work without Postgres. This tool dispatches 6 actions: `list_contracts`, `get_contract`, `upsert_contract`, `delete_contract`, `get_exchange_config`, `update_exchange_section`.

**Canonical data sources** (already YAML, loaded by runtime):
- `brokerage/futures/contract_spec.py` — loads contract specs (DB-first read at line 141, YAML fallback)
- `utils/ticker_resolver.py` — loads exchange resolution config
- Exchange sections validated: `currency_aliases`, `currency_to_fx_pair`, `currency_to_usd_fallback`, `mic_to_exchange_short_name`, `mic_to_fmp_suffix`, `minor_currencies`, `us_exchange_mics` (from `VALID_EXCHANGE_SECTIONS` in `instrument_config.py`)

**FileConfigStore instrument config implementation:**
- Override file: `~/.risk_module/instrument_overrides.yaml`
- Structure:
  ```yaml
  contracts:
    ESM6: {fmp_symbol: ES, multiplier: 50, ...}
  deleted_contracts: [NQZ5]   # tombstones — hide base YAML entries
  exchange_sections:
    currency_aliases: {GBp: GBP}
  ```
- `list_contracts()` → load base specs + merge overrides, exclude tombstoned symbols
- `get_contract(symbol)` → override wins over base, tombstone = not found
- `upsert_contract(symbol, fields)` → write to overrides, remove from tombstones if present
- `delete_contract(symbol)` → add to `deleted_contracts` tombstone list (hides base YAML entry, matching DB behavior where delete removes from active dataset)
- `get_exchange_config()` → load base + merge override sections
- `update_exchange_section(name, data)` → write section to overrides only

**Runtime wiring — IMPORTANT:** In DB mode, the runtime loaders (`contract_spec.py:141` DB-first read, `ticker_resolver.py:36` DB-first read) already read DB-backed config live, and the write paths call `_clear_instrument_caches()` (`instrument_config.py:345/369/410`) so changes take effect immediately. File mode must provide equivalent behavior. Two approaches:
- **(a) Loader patching**: Patch `contract_spec.py` and `ticker_resolver.py` to check the override file when DB is not configured. After writes, call `_clear_instrument_caches()` (already exists) to force reload from override-merged source. This gives parity with DB mode.
- **(b) Restart-only**: Accept a known regression — file-mode writes persist but only take effect after MCP server restart.

**Recommended: Approach (a)** — the loaders already have a DB-first → YAML-fallback pattern. Adding a file-override check in the fallback path is minimal work and avoids a behavioral regression. The `_clear_instrument_caches()` call already exists in all write paths.

**Refactor `mcp_tools/instrument_config.py`:**
- Replace `DatabaseClient` calls with `get_config_store()` calls
- Remove `@require_db`

**Tests:** 6-8 unit tests (CRUD + override merge + tombstone hide + exchange section merge)

### Step 5: Wire All MCP Tools to ConfigStore

**Refactor pattern for each tool file:**

```python
# Before (baskets.py example):
@handle_mcp_errors
@require_db  # ← REMOVE
def create_basket(...):
    db = DatabaseClient(...)
    db.create_factor_group(...)

# After:
@handle_mcp_errors
def create_basket(...):
    store = get_config_store(user_id)
    store.create_basket(...)
```

**Files to modify (if not already done in Steps 1-4):**
- `mcp_tools/baskets.py` — 7 tools
- `mcp_tools/basket_trading.py` — 2 tools
- `mcp_tools/allocation.py` — 2 tools
- `mcp_tools/audit.py` — 3 tools
- `mcp_tools/instrument_config.py` — 1 tool

**Key constraint:** `PostgresConfigStore` must produce identical behavior to current `DatabaseClient` calls. This is a thin adapter, not a rewrite.

**Note:** Steps 1-4 each modify the relevant MCP tool files. Step 5 is a verification/cleanup pass to ensure all 15 tools are wired correctly and `@require_db` is removed from all of them.

### Step 6: Local Auth / Dev Mode

**Goal:** Skip Google OAuth for local development and single-user MCP usage.

**Implementation:**
- Add `AUTH_MODE` env var: `google` (default, current behavior) or `local`
- `AUTH_MODE=local`:
  - Auto-creates a dev user (email from `RISK_MODULE_USER_EMAIL` or `dev@localhost`)
  - Skips Google token verification
  - Returns a fixed session token
  - All requests authenticated as the dev user
- MCP server already uses `RISK_MODULE_USER_EMAIL` for user scoping — no change needed there

**Files:**
- `services/auth_service.py` — Add `LocalAuthService` that returns fixed user
- `app.py` — Route to `LocalAuthService` when `AUTH_MODE=local`
- `settings.py` — Add `AUTH_MODE` env var

**Tests:** 4-6 unit tests

### Step 7: Sample Portfolio

**Goal:** Ship a realistic demo portfolio so tools work out of the box.

**Implementation:**
- New file: `config/sample_portfolio.json` — 15-20 positions
- Mix: large-cap (AAPL, MSFT, GOOGL, AMZN), mid-cap (CRWD, DDOG), international (TSM, ASML), ETFs (SPY, QQQ, TLT), REIT (O), energy (XOM)
- Fields per position: ticker, shares, cost_basis, currency
- Load on first run when no positions exist (no brokerage connected, no CSV imported)
- Trigger: `PositionService` returns empty → offer to load sample
- Or: explicit `--demo` flag on MCP server start

**Files:**
- NEW: `config/sample_portfolio.json`
- `services/position_service.py` — Sample portfolio fallback

**Tests:** 2-3 unit tests

---

## DB Schema Summary (for ConfigStore interface design)

| Category | DB Schema | File Schema | In ConfigStore? |
|----------|-----------|-------------|-----------------|
| Risk Limits | 10 cols + JSONB, PK (user_id, portfolio_id) | Existing YAML | **No** — RiskLimitsManager owns this |
| Baskets | 6 cols + JSONB arrays, PK (user_id, group_name) | Single JSON (name-keyed) | **Yes** |
| Allocations | 4 cols, PK (user_id, portfolio_name, asset_class) | Single JSON file | **Yes** |
| Expected Returns | 5 cols, PK (user_id, ticker, effective_date) | Existing YAML | **No** — PortfolioRepository owns this |
| Audit Trail | 14 cols + events table, UUID PK | JSONL append-only | **Yes** |
| Instrument Config | DB-seeded from YAML | Override YAML file | **Yes** |

---

## Implementation Order

| Step | Scope | Tools Unlocked | Effort |
|------|-------|---------------|--------|
| 1 | ConfigStore protocol + FileConfigStore + Allocations | 2 (allocations) | Medium |
| 2 | Basket CRUD (+ basket trading wiring) | 9 (7 basket + 2 basket trading) | Medium |
| 3 | Audit Trail (+ extract state machine) | 3 (audit) | Medium |
| 4 | Instrument Config | 1 (manage_instrument_config) | Small |
| 5 | Wire all MCP tools (verification pass) | — | Small |
| 6 | Local Auth (`AUTH_MODE=local`) | — (UX) | Small |
| 7 | Sample Portfolio | — (UX) | Small |

**Total: 15 tools unlocked, ~7 steps, each independently committable.**

---

## Risk & Constraints

- **No data migration needed** — Phase B is for new single-user setups. Existing Postgres users keep their data path unchanged.
- **Concurrent MCP requests** — MCP server is single-process but may have overlapping async requests. All read-modify-write operations use `fcntl.flock(LOCK_EX)` on a **stable sidecar `.lock` file** (not the data file itself — atomic rename replaces the inode, breaking locks on the old file). JSON files use sidecar lock + read + tempfile+rename. JSONL appends use sidecar lock + append + flush.
- **Atomic writes** — Use tempfile + rename pattern for JSON files to prevent corruption on crash. JSONL uses append mode (OS guarantees atomic appends up to PIPE_BUF on POSIX).
- **JSONL rotation** — If `actions.jsonl` exceeds 10MB, compact by keeping only latest entry per action_id. Single-user scale (hundreds of actions) unlikely to hit this.
- **Backward compatibility** — `PostgresConfigStore` is a thin wrapper over existing `DatabaseClient`. Zero behavior change for DB users.
- **user_id=0 scoping** — File mode uses sentinel user_id=0 (established in Phase A Step 1). **Production safety**: When `DATABASE_URL` is set (production), `PostgresConfigStore` is selected and must fail fast if user resolution returns sentinel 0 during a transient DB outage — rather than silently writing to user_id=0 scope. The `resolve_user_id()` function in `utils/user_resolution.py` currently returns 0 when DB is unavailable; `PostgresConfigStore` must reject sentinel 0 with a clear error to prevent cross-user data leakage.
- **Basket name safety** — All baskets in a single JSON file, keyed by exact `group_name`. No filenames derived from user input. Matches DB exact-match behavior.
- **State machine parity** — Audit trail transition logic extracted from `DatabaseClient` into shared module. Both `FileConfigStore` and `PostgresConfigStore` use the same validation. Tests verify parity.

---

## Verification

1. **Unit tests** per step (see above, ~40-50 tests total)
2. **Integration**: Start MCP server without `DATABASE_URL`, verify all 37 tools respond (22 existing + 15 new)
3. **Regression**: `python3 -m pytest tests/ -x -q --ignore=tests/integration` — no regressions for DB-mode users
4. **State machine parity**: Verify `FileConfigStore` and `PostgresConfigStore` produce identical results for all audit transition scenarios
5. **Sentinel rejection**: Unit test that `PostgresConfigStore` rejects `user_id=0` when `DATABASE_URL` is set (prevents cross-user leakage during transient outages)
6. **Manual smoke test**: Create basket → list baskets → set allocation → record action → update status → get history — all via MCP without Postgres
