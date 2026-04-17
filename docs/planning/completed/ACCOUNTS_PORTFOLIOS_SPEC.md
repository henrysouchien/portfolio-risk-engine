# Spec: Data Sources / Accounts / Portfolios Infrastructure

## Context

The app currently conflates two things under "portfolio": **data sources** (how we get data — Plaid, IBKR Flex, CSV) and **financial accounts** (where money lives — Schwab IRA, IBKR Margin). There's no concept of accounts as first-class entities. In the **MCP tool path** (e.g., `_load_portfolio_for_analysis()` in `mcp_tools/risk.py`), positions from ALL providers are always loaded together via `PositionService.get_all_positions()` — `portfolio_name` is used for config lookups (factor_proxies, risk_limits, target_allocations), not for filtering positions. The **REST API + PortfolioManager path** (`PortfolioManager.load_portfolio_data()`, `GET /api/portfolios/{name}`, REST risk/performance handlers in `app.py`) loads positions via `DatabaseClient.get_portfolio_positions(user_id, portfolio_name)` which does a SQL `JOIN portfolios WHERE name=%s` — this scopes positions to the named portfolio row, but in practice all synced positions live under `CURRENT_PORTFOLIO` so the effect is the same when the default name is used.

This spec introduces a three-layer model:
- **Data Sources** — provider connections (Plaid items, IBKR Flex, CSV imports)
- **Accounts** — financial accounts at institutions (Schwab Rollover IRA, IBKR Margin)
- **Portfolios** — logical groupings of accounts for analysis

Switching portfolios scopes everything — positions, risk, performance, trading analysis, income — to that portfolio's linked accounts.

## Current State

**Position flow today:**
1. Provider sync saves positions to `positions` table with per-account metadata (`position_source`, `account_id`, `brokerage_name`, `account_name`)
2. All positions stored under one portfolio row named `CURRENT_PORTFOLIO`
3. `_load_portfolio_for_analysis()` (mcp_tools/risk.py:398) calls `PositionService.get_all_positions(consolidate=True)` — no portfolio-based position filtering
4. `get_all_positions()` already supports `institution` and `account` params — unused for portfolio scoping
5. Transaction store `load_from_store()` accepts `source`, `institution`, `account` string params — BUT `institution` is explicitly deleted (`del institution`) in `load_fifo_transactions()`, `load_income_events()`, `load_provider_flow_events()`, `load_futures_mtm()`. Actual filtering uses `(account_id = %s OR account_name = %s)` only.
6. `CURRENT_PORTFOLIO` is hardcoded in ~60 production sites (position_service, routes/plaid, routes/snaptrade, MCP tools, services, app.py)

**Two distinct portfolio storage models today:**
- **Provider-synced (virtual):** `CURRENT_PORTFOLIO` receives ALL synced positions. MCP tools load via `PositionService.get_all_positions()` which fetches from providers on a fresh call, or reads from the DB cache on a warm hit (`_load_cached_positions()` → `DatabaseClient.get_portfolio_positions(user_id, "CURRENT_PORTFOLIO")`). The DB copy is a cache populated by `_save_positions_to_db()` after each fresh provider fetch.
- **Manual (physical):** `save_portfolio()` in `database_client.py` upserts a portfolio row (inserts if missing via `INSERT INTO portfolios ... RETURNING id`, or updates if existing via `get_portfolio_id()` + `UPDATE`), then stores positions directly under that portfolio_id. The default `position_source` parameter is `'database'`, but per-row overrides are possible via `position_data.get('position_source', position_source)` — callers like `PortfolioRepository.save_portfolio_to_database()` may pass a non-`'database'` provider extracted from the portfolio metadata. Provider-scoped deletion (`DELETE FROM positions WHERE portfolio_id = %s AND position_source = %s`) only clears positions matching the given source. `PortfolioManager._load_portfolio_from_database()` reads via `repository.load_full_portfolio()` which does a physical SQL JOIN (`positions.portfolio_id = portfolios.id WHERE portfolios.name = %s`).

**Existing tables:**
- `portfolios` — (id, user_id, name, start_date, end_date, pending_update flags). UNIQUE(user_id, name)
- `positions` — per-account rows with UNIQUE(portfolio_id, position_source, account_id, ticker, currency). NULL account_id allowed for manual rows (schema comment).
- `provider_items` — maps provider item_id → user for webhook routing. Plaid stores `item_id=item_id` (per-institution connection). SnapTrade stores `item_id=snaptrade_user_hash` (user-level, NOT per-connection — actual connection IDs are `authorization_id` from the SnapTrade API).
- `risk_limits`, `factor_proxies` — scoped to portfolio_id
- `target_allocations` — scoped to (user_id, portfolio_name)
- `expected_returns` — scoped to (user_id, ticker) — NOT portfolio-scoped

**Institution slug coverage:** `resolve_institution_slug()` only covers 9 aliases (IBKR, Schwab, Merrill). Many real `brokerage_name` values from aggregator providers (Fidelity, Vanguard, Chase, etc.) return `None`. Direct providers (IBKR, Schwab) always resolve.

**Transaction store filtering semantics (critical):**
All store read methods (`load_fifo_transactions`, `load_income_events`, `load_provider_flow_events`) explicitly `del institution` and filter only by `(account_id = %s OR account_name = %s)`. `load_futures_mtm()` also deletes `institution` but uses a three-way OR: `(account_id = %s OR COALESCE(raw_data->>'account_id', '') = %s OR COALESCE(raw_data->>'account_name', '') = %s)` — checking both the top-level column AND JSONB-extracted fields. The `institution` parameter is accepted at the call site but **never used in SQL** across all four methods. The comment says: "Caller applies alias-aware institution filtering." This means:
- Portfolio-scoped transaction loading must filter by `account` param only
- If the same `account_id` string appears in multiple institutions (unlikely but possible), we must post-filter the results by institution
- `load_flex_option_prices` ignores both `institution` and `account` — always returns all IBKR option price rows

---

## Phase 1: Accounts + Data Sources (Pure Additive — No Behavior Change)

**Goal:** Create `accounts` and `data_sources` tables, discover accounts from position data during sync. No changes to `portfolios` table, no changes to any existing behavior.

### 1.1 New Tables

```sql
-- Data Sources: provider connections
CREATE TABLE data_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,              -- 'plaid', 'snaptrade', 'ibkr', 'schwab', 'csv'
    provider_item_id VARCHAR(255),              -- Plaid item_id, SnapTrade connection_id
    institution_slug VARCHAR(100),              -- Canonical slug (nullable — not all institutions resolve)
    institution_display_name VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    last_sync_at TIMESTAMP,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Partial unique indexes for data_sources (avoids COALESCE in constraint)
CREATE UNIQUE INDEX uq_data_sources_with_item
    ON data_sources(user_id, provider, provider_item_id)
    WHERE provider_item_id IS NOT NULL;
CREATE UNIQUE INDEX uq_data_sources_without_item
    ON data_sources(user_id, provider)
    WHERE provider_item_id IS NULL;

-- Accounts: financial accounts at institutions
CREATE TABLE accounts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    data_source_id INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
    -- data_source_id is NULLABLE by design:
    --   - Backfilled accounts from existing positions have NULL (no data_source row yet)
    --   - Going forward, newly discovered accounts during sync get linked to data_sources
    --   - Application code must tolerate NULL (no eager backfill of data_sources)
    account_id_external VARCHAR(255) NOT NULL,  -- Provider-native account ID
    position_source VARCHAR(50),               -- Provider that discovered this account ('plaid', 'snaptrade', 'ibkr', 'schwab', 'csv')
    institution_key VARCHAR(100) NOT NULL,      -- ALWAYS populated via normalize_institution_slug()
    institution_display_name VARCHAR(255),       -- "Charles Schwab", "Fidelity" (original raw name)
    account_name VARCHAR(255),                  -- "Rollover IRA", "Individual Brokerage"
    account_type VARCHAR(50),                   -- 'brokerage', 'ira', '401k'
    currency VARCHAR(10) DEFAULT 'USD',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_position_sync_at TIMESTAMP,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Account identity: institution_key is always populated (never NULL), so unique index is safe.
-- Same physical account via Plaid + SnapTrade = 2 rows (different account_id_external)
-- partition_positions() prevents duplicate positions for routed institutions (Schwab, IBKR only).
CREATE UNIQUE INDEX uq_accounts_identity
    ON accounts(user_id, institution_key, account_id_external);

-- Standard indexes
CREATE INDEX idx_data_sources_user ON data_sources(user_id);
CREATE INDEX idx_data_sources_provider ON data_sources(provider);
CREATE INDEX idx_accounts_user ON accounts(user_id);
CREATE INDEX idx_accounts_institution ON accounts(institution_key);
CREATE INDEX idx_accounts_active ON accounts(user_id, is_active);

-- Triggers
CREATE TRIGGER update_data_sources_updated_at BEFORE UPDATE ON data_sources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_accounts_updated_at BEFORE UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

### 1.1a NULL account_id Handling

Existing `positions` rows may have NULL `account_id` (manual portfolio imports, legacy data). The backfill migration handles these:

- **Grouping key:** `(user_id, normalize_institution_slug(brokerage_name), position_source)`. This ensures each institution+provider combo gets its own pseudo-account, not a single catch-all.
- **Account values:** `account_id_external = '_unknown_{position_source}'` (source-qualified to avoid unique index collision when same institution has NULL account_id from two providers), `institution_key = normalize_institution_slug(brokerage_name)` (or `'manual'` if brokerage_name is also NULL), `account_name = 'Unknown Account ({position_source})'`.
- **Rationale:** These positions still need an account row for portfolio linkage, but they can't be meaningfully attributed to a real account. Grouping by institution avoids collapsing distinct institutions into one pseudo-account.
- **Position filter matching for pseudo-accounts:** `filter_position_result()` / `filter_positions_to_accounts()` (§2.6) must handle NULL/empty `account_id` in positions: when a position's `account_id` is NULL/empty, the filter maps it to `_unknown_{position_source}` before comparing against `account_filters`. This ensures positions with NULL `account_id` match the pseudo-account's `account_id_external`.
- **Transaction filter does NOT map to pseudo key:** `_row_matches()` in `load_from_store_for_portfolio()` (§2.8) does NOT apply pseudo-account mapping for transaction rows. Transaction rows with NULL/empty `account_id` will not match pseudo-account filters — this is intentional and consistent with §2.8's "Pseudo-account limitation" note. Pseudo-account positions (from legacy/manual imports) typically have no transaction history. Single-account portfolios linked to pseudo-accounts will show positions but no realized performance/trading data.
- **Going forward:** `account_id` should always be populated during sync. The pseudo-account is a backward-compat safety net, not a pattern to encourage.

### 1.2 Expand Institution Slug Coverage

Add to `providers/routing_config.py` INSTITUTION_SLUG_ALIASES:
```python
# Existing: interactive_brokers, charles_schwab, merrill (9 aliases)
# Add major aggregator institutions:
"fidelity": "fidelity",
"td ameritrade": "td_ameritrade",
"tda": "td_ameritrade",
"etrade": "etrade",
"e*trade": "etrade",
"vanguard": "vanguard",
"chase": "chase",
"wells fargo": "wells_fargo",
"citibank": "citibank",
"citi": "citibank",
"us bank": "us_bank",
"robinhood": "robinhood",
"webull": "webull",
```

Add fallback slug generator in `providers/routing.py`:
```python
def normalize_institution_slug(brokerage_name: str | None) -> str:
    """Resolve institution slug with fallback to sanitized name.
    NULL/empty brokerage_name → 'manual' (canonical fallback for unknown institutions).
    """
    if not brokerage_name or not brokerage_name.strip():
        return 'manual'
    slug = resolve_institution_slug(brokerage_name)
    if slug:
        return slug
    # Fallback: lowercase, replace spaces/special chars with underscore
    import re
    return re.sub(r'[^a-z0-9]+', '_', brokerage_name.lower()).strip('_') or 'manual'
```

**Slug harmonization (critical):** `normalize_institution_slug()` becomes the single canonical slug resolver for all institution identity. Existing call sites that produce their own slugs must be harmonized:
- `INSTITUTION_PROVIDER_MAPPING` in `providers/routing_config.py` uses `merrill_edge` as a key, but `INSTITUTION_SLUG_ALIASES` canonicalizes Merrill names to `merrill`. The mapping keys must match canonical slugs (either update `INSTITUTION_PROVIDER_MAPPING` to use `merrill`, or add `merrill_edge` → `merrill` to `INSTITUTION_SLUG_ALIASES`).
- `routes/onboarding.py` has its own raw slugifier (line ~43) for status display. Replace with `normalize_institution_slug()` to prevent drift.
- All sites that compare institution strings must use `normalize_institution_slug()` — not raw brokerage names or ad-hoc slugification.

### 1.3 Account Registry Service

**New file: `services/account_registry.py`**

```python
class AccountRegistry:
    """Discovers accounts from position data, populates accounts table."""

    def __init__(self, user_id: int):
        self.user_id = user_id

    def discover_accounts_from_positions(self, df: pd.DataFrame, provider: str) -> list[dict]:
        """Extract distinct (account_id, brokerage_name, account_name) from position DataFrame.
        Upsert into accounts table. Returns created/updated account dicts.

        Uses normalize_institution_slug() for institution_key (never None).
        Stores `provider` as `position_source` on the account row — this enables
        link_accounts_to_data_source() to match accounts to data_source rows.
        On first call for an account, data_source_id is NULL.
        """

    def ensure_data_source(self, provider: str, provider_item_id: str | None = None,
                           institution_name: str | None = None) -> int:
        """Get or create data_source row. Returns data_source.id.
        Called from provider-specific sync routes (NOT from _save_positions_to_db()),
        because only the sync route has the connection-level ID (Plaid item_id,
        SnapTrade connection_id). NOT backfilled from provider_items."""

    def link_accounts_to_data_source(self, data_source_id: int) -> int:
        """Link accounts to a data_source row by matching (user_id, position_source, institution_key).
        Sets data_source_id on matching accounts. Only links when exactly one data_source
        matches per (user_id, position_source, institution_key) tuple to avoid ambiguity.
        Returns count of accounts linked."""

    def get_user_accounts(self, active_only: bool = True) -> list[dict]:
        """List all accounts for user."""

    def get_account_by_external_id(self, institution_slug: str, account_id_external: str) -> dict | None:
        """Lookup account by identity tuple."""
```

### 1.4 Integration Hooks

**Data source creation (runs AFTER position save)** — in provider-specific sync routes.

**Multi-connection providers (critical):** Plaid and SnapTrade load all connections in one pass:
- `plaid_loader.py` iterates all Plaid tokens (each token = one `item_id` = one institution connection)
- `snaptrade_loader.py` iterates all SnapTrade authorizations per user

Position rows carry per-row metadata (`brokerage_name`, `account_id`) but NOT the connection-level identifier. Loaders receive only `user_email` via the provider interface — they do NOT have DB `user_id`. The `_save_positions_to_db()` method receives a single merged DataFrame with only `provider` string.

**Design:** Data source creation happens at the **route/webhook layer** where both `user_id` and connection identifiers are available. Routes call `PositionService.get_positions()` (which triggers `_save_positions_to_db()` internally), then run data source hooks AFTER positions are saved.

**Multi-connection provider enumeration:** For Plaid and SnapTrade, a single post-refresh call is insufficient because the refresh path doesn't expose per-connection IDs. Instead:

- `routes/plaid.py` — **Token exchange** (line ~881) has `(item_id, institution_name)` directly → `registry.ensure_data_source("plaid", provider_item_id=item_id, institution_name=institution_name)`. **Refresh** path (line ~998) calls `get_positions(provider="plaid")` which merges all connections → after refresh, read all `(item_id, institution_name)` pairs from the `provider_items` table (where `provider='plaid' AND user_id=user_id`) and call `ensure_data_source()` for each. Note: `_ensure_plaid_item_mappings_for_user()` backfills `provider_items` but returns None — a separate read query is needed (add `DatabaseClient.get_provider_items(user_id, provider='plaid')` or use `AccountRegistry.get_provider_items()`).
- `routes/snaptrade.py` — **Refresh** (line ~843) calls `get_positions(provider="snaptrade")` → after refresh, enumerate connections via the SnapTrade connection-list API (`routes/snaptrade.py` line ~643) or the onboarding helper (`routes/onboarding.py` line ~126) and call `ensure_data_source()` for each `(authorization_id, brokerage_name)`.
- `routes/onboarding.py` — after IBKR/Schwab sync completes: `registry.ensure_data_source("ibkr")` / `registry.ensure_data_source("schwab")` (single connection per provider, no enumeration needed).

**CSV import path:** CSV imports flow through `mcp_tools/import_portfolio.py` → `CSVPositionProvider.save_positions()` (file-backed). `CSVPositionProvider` is registered as `"csv"` in `PositionService` and its positions are included in combined `get_all_positions()` calls. However, the `csv` branch in `_get_positions_df()` returns before reaching `_save_positions_to_db()` — CSV positions are served directly from the file store and are NOT saved to the DB positions table via that path. Therefore, account discovery for CSV imports MUST be hooked directly into `import_portfolio.py` — after `CSVPositionProvider.save_positions()` completes, construct a DataFrame from the imported positions and call `registry.discover_accounts_from_positions(df, provider="csv")`, then `registry.ensure_data_source("csv")`. Use `provider="csv"` consistently (matching the registered provider key) so that `accounts.position_source` matches `data_sources.provider`. This is the ONLY path for CSV account discovery.

**Account-to-data-source linking (best-effort, same sync):** On each sync (provider-synced portfolios only), the order is: (1) `_save_positions_to_db()` runs (saves positions AND discovers accounts — `discover_accounts_from_positions()` stores `position_source` on the account row from the `provider` param), (2) route calls `ensure_data_source()` (creates/finds data_source row), (3) route calls `registry.link_accounts_to_data_source(data_source_id)` — matches accounts by `(user_id, position_source, institution_key)` and sets `data_source_id` on matching accounts. The `position_source` column on accounts (populated by `discover_accounts_from_positions()`) enables this match. This runs after both accounts and data_source rows exist. When the match is ambiguous (e.g., two Plaid items for the same institution), `data_source_id` is left NULL — the link only happens when there is exactly one matching `data_source` row for that `(user_id, position_source, institution_key)` tuple. Accounts may have `data_source_id=NULL` in ambiguous cases — this is acceptable (data_source_id is optional metadata, not required for portfolio scoping).

**Account discovery (runs AFTER position save)** — in `services/position_service.py` `_save_positions_to_db()`:
```python
# Discover accounts from position data (Phase 1: data only, no portfolio changes)
try:
    if is_db_available():
        registry = AccountRegistry(user_id)
        registry.discover_accounts_from_positions(df_for_save, provider)
except Exception as exc:
    portfolio_logger.warning(f"Account discovery failed (non-fatal): {exc}")
```

`discover_accounts_from_positions()` groups by `(account_id, brokerage_name)` and upserts account rows. `data_source_id` is set by matching against existing `data_sources` rows for this user/provider/institution, or left NULL if no match.

### 1.5 Initial Population

**New file: `database/migrations/20260312b_accounts_data_sources.sql`**

Single SQL migration file. `scripts/run_migrations.py` processes all `*.sql` files in lexical order (existing basenames are mixed: `003_...`, `2025-09-...`, `20250801_...`, `migration_add_...`). Note: `20260312_drop_cash_tables.sql` already exists — use `20260312b_accounts_data_sources.sql` (or a later date) to ensure the new migration runs after the existing `20260312` file. On a fresh database, all migrations run in lexical order. Note: some existing migrations assume base-schema objects exist (e.g., `portfolios` table created by `schema.sql`, not by a migration). The new migration files use idempotent DDL (`CREATE TABLE IF NOT EXISTS`, `ON CONFLICT DO NOTHING`) for their own objects, but the base schema must already be applied (as is the case in any real deployment).

The backfill logic uses `normalize_institution_slug()` which lives in Python. Since SQL migrations can't call Python functions, the migration DDL and backfill are split:

1. **DDL section** (in the `.sql` file): CREATE TABLE data_sources, CREATE TABLE accounts, CREATE TABLE accounts_migration_state (sentinel for fixup scripts), indexes, triggers
2. **Backfill section** (in the `.sql` file): INSERT INTO accounts using raw SQL:
   ```sql
   -- Backfill accounts from distinct position tuples
   INSERT INTO accounts (user_id, account_id_external, position_source, institution_key, institution_display_name, account_name)
   SELECT DISTINCT
       port.user_id,
       COALESCE(NULLIF(p.account_id, ''), '_unknown_' || p.position_source),
       p.position_source,
       COALESCE(NULLIF(LOWER(REGEXP_REPLACE(NULLIF(p.brokerage_name, ''), '[^a-z0-9]+', '_', 'gi')), ''), 'manual'),
       p.brokerage_name,
       p.account_name
   FROM positions p
   JOIN portfolios port ON p.portfolio_id = port.id
   ON CONFLICT DO NOTHING;
   ```
   The SQL `REGEXP_REPLACE` produces preliminary slugs that may differ from the Python alias map (e.g., SQL produces `merrill_edge` while Python returns `merrill`; SQL produces `interactive_brokers_llc` while Python returns `interactive_brokers`). These differences **will break** account identity matching in Phase 2 (position filtering compares `normalize_institution_slug(brokerage_name)` against `accounts.institution_key`).
3. **Post-migration Python fixup** (**MANDATORY** — must run before Phase 2): `scripts/fixup_account_slugs.py` — re-resolves every `accounts.institution_key` using the full Python `normalize_institution_slug()` with `INSTITUTION_SLUG_ALIASES`.

   **Collision handling:** Two preliminary rows (e.g., `merrill_edge` + `merrill_lynch`) may canonicalize to the same slug (`merrill`), causing a unique constraint violation on `(user_id, institution_key, account_id_external)`. The fixup script must:
   1. Group accounts by `(user_id, canonical_slug, account_id_external)`
   2. If a group has >1 row (collision), merge: keep the row with the lowest `id` (deterministic), delete the other(s)
   3. Then update `institution_key` to the canonical slug

   **Note:** This runs in Phase 1, before `portfolio_accounts` exists. No FK references need updating — only `accounts.institution_key` values change. The Phase 2 Python linking script (`scripts/link_portfolio_accounts.py`) runs after this fixup and uses the already-canonical slugs.

   This is a one-time fixup. Going forward, `discover_accounts_from_positions()` always uses `normalize_institution_slug()` at insert time, so no preliminary→canonical drift occurs.
4. Do NOT backfill `data_sources` from `provider_items` (unreliable — SnapTrade stores user hash, not connection). Populate going forward during sync.
5. Verify: `SELECT COUNT(*) FROM accounts` matches distinct account tuples in positions (with NULL→pseudo mapping)

### 1.6 Files Changed

| File | Action |
|------|--------|
| `database/migrations/20260312b_accounts_data_sources.sql` | **New** — DDL + backfill (SQL) |
| `scripts/fixup_account_slugs.py` | **New** (**mandatory** before Phase 2) — Python slug resolution fixup |
| `database/schema.sql` | Add new table DDL (reference copy) |
| `services/account_registry.py` | **New** — discovery service |
| `inputs/database_client.py` | Add ~4 CRUD methods (upsert_account, upsert_data_source, get_user_accounts, get_account_by_external_id) |
| `services/position_service.py` | Hook account discovery in `_save_positions_to_db()` |
| `routes/plaid.py` | Hook `ensure_data_source()` with Plaid item_id after position refresh (route has both user_id and item_id) |
| `routes/snaptrade.py` | Hook `ensure_data_source()` with authorization_id after position refresh |
| `routes/onboarding.py` | Hook `ensure_data_source()` for IBKR direct sync and Schwab sync paths |
| `mcp_tools/import_portfolio.py` | Hook account discovery + `ensure_data_source("csv")` after CSV portfolio save |
| `providers/routing_config.py` | Expand INSTITUTION_SLUG_ALIASES |
| `providers/routing.py` | Add `normalize_institution_slug()` fallback |

### 1.6a Known Limitations

- **Cash-only Plaid accounts:** `plaid_loader.py` skips accounts with no holdings before `patch_cash_gap_from_balance()` synthesizes a cash position. These accounts produce no position rows, so `discover_accounts_from_positions()` cannot discover them. Mitigation: add a secondary discovery path in the Plaid loader that registers accounts directly from the Plaid `/accounts/get` response (which lists all accounts including cash-only). This is a low-priority edge case — cash-only investment accounts are rare — and can be addressed in a follow-up.
- **Direct-provider ownership (IBKR/Schwab):** IBKR and Schwab connections are process-level (shared gateway, shared token file), not per-user. `ensure_data_source("ibkr")` / `ensure_data_source("schwab")` creates a `data_sources` row for the authenticated user making the refresh request. In the current single-user deployment, this is unambiguous. In multi-user deployments, multiple users could share the same physical connection — each gets their own `data_sources` row, which is correct (data_sources track "user X gets data from provider Y", not "user X owns the physical connection"). The global connection state is a pre-existing limitation unrelated to this spec.
- **CSV positions are global (not per-user):** `CSVPositionProvider._resolve_path()` ignores `user_email` and always returns the same `positions.json` file. In the current single-user deployment, this is fine — `ensure_data_source("csv")` correctly attributes CSV positions to the only user. In multi-user deployments, CSV rows would be attributed to whichever user triggers the combined load. Per-user CSV storage is a pre-existing limitation deferred to follow-up work (same as the CSV storage redesign noted in §2.6b/§2.6c).

### 1.7 Tests

- Unit: `AccountRegistry.discover_accounts_from_positions()` with mock DataFrame
- Unit: `normalize_institution_slug()` fallback for unknown institutions
- Unit: Backfill migration produces correct accounts
- Integration: sync positions → accounts table populated
- **Backward compat: ALL existing tools work unchanged** (portfolios table untouched)

---

## Phase 2: Portfolio Model + Scoped Position Loading

**Goal:** Extend portfolios with types and account linkage. Enable portfolio-scoped position loading and transaction filtering via a **shared resolver** used by BOTH the MCP tool path AND the REST API/PortfolioManager path. `CURRENT_PORTFOLIO` stays as the physical DB name for the combined portfolio — no hardcoded references need to change.

### 2.1 Schema Changes

```sql
-- Portfolio ↔ Account linkage
CREATE TABLE portfolio_accounts (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(portfolio_id, account_id)
);

CREATE INDEX idx_portfolio_accounts_portfolio ON portfolio_accounts(portfolio_id);
CREATE INDEX idx_portfolio_accounts_account ON portfolio_accounts(account_id);

-- Extend existing portfolios table (add columns WITHOUT defaults first, then backfill, then set defaults)
ALTER TABLE portfolios
    ADD COLUMN IF NOT EXISTS portfolio_type VARCHAR(20),
    ADD COLUMN IF NOT EXISTS display_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS auto_managed BOOLEAN,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN;

-- Backfill existing rows BEFORE setting defaults (see §2.4 for full migration sequence)
-- This ensures non-CURRENT_PORTFOLIO rows are tagged 'manual', not 'combined'

-- After backfill, set defaults for future rows
ALTER TABLE portfolios
    ALTER COLUMN portfolio_type SET DEFAULT 'combined',
    ALTER COLUMN auto_managed SET DEFAULT FALSE,
    ALTER COLUMN is_active SET DEFAULT TRUE;
```

### 2.2 Portfolio Types

| `portfolio_type` | `auto_managed` | Storage Model | Description |
|---|---|---|---|
| `combined` | `true` | **Virtual** — fetch all positions, no filter | "All Accounts" — all provider-sourced positions (sync-backed + CSV file-backed). The CURRENT_PORTFOLIO row becomes this. CSV positions are included via the provider registry (`CSVPositionProvider` is registered alongside Plaid/SnapTrade/IBKR/Schwab), subject to `_apply_csv_api_safety_guard()` which may skip CSV positions when matching API brokerage data is available. **CSV account linking:** CSV positions are file-backed (not in DB `positions` table), so the SQL-based `link_portfolio_accounts.py` script (§2.4 step 5) cannot discover them. Instead, CSV accounts are linked to CURRENT_PORTFOLIO directly in `import_portfolio.py` via `registry.link_csv_accounts_to_combined(csv_account_ids)` — a dedicated method that inserts `portfolio_accounts` rows for CSV accounts pointing to the CURRENT_PORTFOLIO portfolio_id. The `clear` action in `import_portfolio.py` (which calls `CSVPositionProvider.clear_source()`) must also unlink stale CSV accounts: call `registry.unlink_csv_accounts(cleared_account_ids)` + `registry.ensure_single_account_portfolios()` to remove `portfolio_accounts` rows and soft-hide `_auto_*` portfolios for cleared CSV sources. Manual-only DB portfolios are NOT linked. |
| `single_account` | `true` | **Virtual** — fetch all, filter to 1 account | Auto-created per discovered account. Linked via `portfolio_accounts`. |
| `custom` | `false` | **Virtual** — fetch all, filter to N accounts | User-created. User picks accounts from `list_accounts()`. |
| `manual` | `false` | **Physical** — positions stored directly under portfolio_id | Created via `save_portfolio()` (e.g., PortfolioManager DB saves). Positions in DB keyed by portfolio_id. **No portfolio_accounts linkage.** Note: CSV imports go through `CSVPositionProvider` (file-backed) and are included in the combined virtual portfolio, NOT as manual portfolios. |

**Virtual vs Physical distinction:**
- **Virtual** portfolios (combined/single_account/custom) use the fetch-all-then-filter pattern. Positions live under `CURRENT_PORTFOLIO` in the `positions` table. The `portfolio_accounts` join table defines which accounts are in scope.
- **Physical** portfolios (manual) store their own positions directly in the `positions` table with their own `portfolio_id`. They're read via the existing `repository.load_full_portfolio()` SQL JOIN. They have NO `portfolio_accounts` linkage — their positions are self-contained.
- The shared resolver (§2.5) distinguishes these: `portfolio_type='manual'` → `LoadStrategy.PHYSICAL`, everything else → `LoadStrategy.VIRTUAL` (with `account_filters=None` for combined).

### 2.3 CURRENT_PORTFOLIO Strategy (Critical)

**CURRENT_PORTFOLIO stays as the physical DB `name`.** The ~60 hardcoded references do NOT change because:
- Position saves always go to CURRENT_PORTFOLIO → correct (combined portfolio holds all positions)
- Webhook pending updates go to CURRENT_PORTFOLIO → correct
- MCP tools default to CURRENT_PORTFOLIO → correct (combined = all positions)
- Cache freshness checks use CURRENT_PORTFOLIO → correct

**What changes:** When `portfolio_name` is something OTHER than `CURRENT_PORTFOLIO` (e.g., `"_auto_schwab_rollover_ira"`), the load path resolves to account filters and returns a subset of positions. When `portfolio_type='manual'`, the existing physical DB load path is used.

### 2.4 Migration

**File: `database/migrations/20260313_portfolio_accounts.sql`**

**Migration ordering (critical):** This file is dated `20260313`, after the Phase 1 migration (`20260312b_accounts_data_sources.sql`). `scripts/run_migrations.py` runs `*.sql` files in lexical order.

**Deployment sequence:**

**Critical:** `20260313_portfolio_accounts.sql` must NOT be present in the migrations directory when step 1 runs. `scripts/run_migrations.py` applies ALL unapplied `*.sql` files in lexical order — if both files exist, it will attempt `20260313` immediately after `20260312` and hit the sentinel guard (since slug fixup hasn't run yet). The recommended approach: commit/deploy Phase 1 files first, run steps 1-2, then commit/deploy Phase 2 files and run steps 3-4.

1. `scripts/run_migrations.py` — applies `20260312b_accounts_data_sources.sql` (Phase 1 DDL + backfill). `20260313` must not be in the migrations dir yet.
2. `python scripts/fixup_account_slugs.py` — canonicalizes account slugs (MANDATORY). On completion, writes a sentinel row: `INSERT INTO accounts_migration_state (step, completed_at) VALUES ('slug_fixup', NOW())` (table created in `20260312`).
3. Add `20260313_portfolio_accounts.sql` to the migrations dir, then `scripts/run_migrations.py` — applies it (Phase 2 DDL + portfolio type tagging). The sentinel guard passes because step 2 completed.
4. `python scripts/link_portfolio_accounts.py` — links accounts to portfolios, creates `_auto_*` portfolios. Requires `portfolio_accounts` table (created in step 3).

**Note:** `link_portfolio_accounts.py` runs AFTER `20260313`, not before, because it needs the `portfolio_accounts` table and `portfolios.portfolio_type` column that step 3 creates.

To prevent accidental application of Phase 2 before the slug fixup, the `20260313` migration opens with a guard:
```sql
DO $$ BEGIN
  -- Abort if slug fixup hasn't run
  IF NOT EXISTS (
    SELECT 1 FROM accounts_migration_state WHERE step = 'slug_fixup'
  ) THEN
    RAISE EXCEPTION 'Run scripts/fixup_account_slugs.py before applying this migration';
  END IF;
END $$;
```

The `accounts_migration_state` table is created in `20260312`:
```sql
CREATE TABLE IF NOT EXISTS accounts_migration_state (
    step VARCHAR(50) PRIMARY KEY,
    completed_at TIMESTAMP DEFAULT NOW()
);
```

Steps 1-4 below are pure SQL (DDL + DML) in the `.sql` migration file. Step 5 is a separate Python script (`scripts/link_portfolio_accounts.py`) that runs outside the migration runner:

1. DDL: CREATE TABLE portfolio_accounts, ALTER TABLE portfolios (add columns WITHOUT defaults — see §2.1)
2. Tag non-CURRENT_PORTFOLIO rows FIRST (before setting defaults): `UPDATE portfolios SET portfolio_type='manual', auto_managed=false, is_active=true WHERE name != 'CURRENT_PORTFOLIO'`. This works because columns are NULL at this point — all non-CURRENT rows become manual. **Note:** Any config data (risk_limits, factor_proxies) previously stored under these portfolio names is preserved in DB but becomes unused — all config now routes to CURRENT_PORTFOLIO. This data is not deleted; if per-portfolio config is added later, it can be re-activated.
3. **Tag existing CURRENT_PORTFOLIO rows** (do NOT create new ones for users without synced positions):
   ```sql
   UPDATE portfolios SET portfolio_type='combined', display_name='All Accounts', auto_managed=true, is_active=true WHERE name='CURRENT_PORTFOLIO';
   ```
   Users without CURRENT_PORTFOLIO rows are typically those who have never synced positions — they have no combined portfolio to tag. (Note: `POST /api/portfolios` can also create a CURRENT_PORTFOLIO row manually, but this is a degenerate case — the Phase 2 guards in §2.9 will prevent manual creation of CURRENT_PORTFOLIO going forward.) Creating empty CURRENT_PORTFOLIO rows for unsynced users would cause the frontend `PortfolioInitializer` to show the onboarding/empty fallback, blocking access to any manual portfolios they may have. CURRENT_PORTFOLIO rows are created naturally during the first position sync (existing behavior, unchanged).
4. Set column defaults for future rows: `ALTER TABLE portfolios ALTER COLUMN portfolio_type SET DEFAULT 'combined', ALTER COLUMN auto_managed SET DEFAULT FALSE, ALTER COLUMN is_active SET DEFAULT TRUE`
5. **Account linking + `_auto_*` creation** — run as a **Python script** (`scripts/link_portfolio_accounts.py`), NOT pure SQL. This runs AFTER the mandatory slug fixup (§1.5 step 3), so `accounts.institution_key` contains canonical Python-resolved slugs. The script:
   - For each user, find accounts that have positions under CURRENT_PORTFOLIO by comparing `normalize_institution_slug(pos.brokerage_name)` against `accounts.institution_key` and `COALESCE(NULLIF(pos.account_id, ''), '_unknown_' || pos.position_source)` against `accounts.account_id_external` (handles both NULL and empty-string `account_id`, matching the SQL backfill in §1.5 step 2)
   - Link those accounts to CURRENT_PORTFOLIO via `portfolio_accounts` INSERT
   - Accounts whose positions only exist under manual portfolios (not CURRENT_PORTFOLIO) are NOT linked — their positions aren't visible through virtual reads
   - Create `_auto_*` single_account portfolios only for CURRENT_PORTFOLIO-linked accounts, with collision resolution (see §2.9)
   **Why Python, not SQL:** The linking JOIN must compare position `brokerage_name` against canonical `institution_key`, which requires `normalize_institution_slug()` (Python alias map). Raw SQL `REGEXP_REPLACE` would produce non-canonical slugs (e.g., `merrill_edge` vs canonical `merrill`), missing matches.
7. Guard: existing `save_portfolio()` in `database_client.py` must set `portfolio_type='manual'` on new rows

### 2.5 Shared Portfolio Scope Resolver

**New file: `services/portfolio_scope.py`** — Used by BOTH `_load_portfolio_for_analysis()` (MCP) AND `PortfolioManager._load_portfolio_from_database()` (REST API).

```python
from enum import Enum
from dataclasses import dataclass

class LoadStrategy(Enum):
    VIRTUAL_ALL = "virtual_all"       # combined: fetch all, no filter
    VIRTUAL_FILTERED = "virtual_filtered"  # single_account/custom: fetch all, filter to linked accounts
    PHYSICAL = "physical"             # manual: load from DB by portfolio_id

@dataclass
class PortfolioScope:
    strategy: LoadStrategy
    portfolio_name: str
    config_portfolio_name: str = "CURRENT_PORTFOLIO"  # always CURRENT_PORTFOLIO (§2.7)
    expected_returns_portfolio_name: str = "CURRENT_PORTFOLIO"  # PHYSICAL→portfolio_name, else CURRENT_PORTFOLIO
    account_filters: list[tuple[str, str, str | None]] | None = None  # (institution_key, account_id_external, account_name)
    # account_filters populated only for VIRTUAL_FILTERED
    # account_name included because transaction store SQL matches `(account_id = %s OR account_name = %s)`

def resolve_portfolio_scope(user_id: int, portfolio_name: str) -> PortfolioScope:
    """Central resolver for portfolio load strategy.

    Rules:
    1. 'CURRENT_PORTFOLIO' (by name, before DB lookup) → VIRTUAL_ALL (no filtering)
    2. DB unavailable + portfolio_name != 'CURRENT_PORTFOLIO' → raise error
       (cannot determine type/accounts without DB — silent fallback to all positions is wrong)
    3. combined-type → VIRTUAL_ALL
    4. single_account/custom → VIRTUAL_FILTERED (resolve linked accounts from portfolio_accounts)
    5. manual → PHYSICAL (use existing DB load path)
    6. Unknown portfolio_name → raise PortfolioNotFoundError

    No-DB behavior (MCP only — REST hard-exits without DATABASE_URL):
    - CURRENT_PORTFOLIO without DB: rule 1 short-circuits (no DB query needed). MCP loads via PositionService→providers.
    - Non-CURRENT_PORTFOLIO without DB: always errors (rule 2) — cannot determine type/accounts

    Called by:
    - mcp_tools/risk.py: _load_portfolio_for_analysis()
    - mcp_tools/performance.py: _load_portfolio_for_performance()
    - mcp_tools/trading_analysis.py: get_trading_analysis()
    - mcp_tools/income.py: get_income_projection()
    - inputs/portfolio_manager.py: _load_portfolio_from_database()
    - app.py: GET /api/portfolios/{name}
    """
```

### 2.6 Position Loading Change

All position-loading entry points must use the shared resolver. The primary entry points are §2.6a-e below, plus additional call sites that load positions via `get_all_positions()`:

#### 2.6f Additional position-loading call sites

The following also call `PositionService.get_all_positions()` and need portfolio scoping:
- `mcp_tools/positions.py` — `get_positions()` (already accepts `portfolio_name` but doesn't filter) and `export_holdings()` (no portfolio param)
- `routes/positions.py` — REST positions endpoint
- `routes/hedging.py` — hedging analysis endpoint
- `mcp_tools/rebalance.py` — `preview_rebalance_trades()` loads positions for rebalancing

All must resolve scope and filter for VIRTUAL_FILTERED, pass through for VIRTUAL_ALL. A grep-based audit during implementation (`grep -rn 'get_all_positions' mcp_tools/ routes/ services/`) will surface any remaining call sites.

**Two filter helpers** (in `services/portfolio_scope.py`):

1. **`filter_positions_to_accounts(positions: list[dict], account_filters) -> list[dict]`** — filters raw position dicts. Used by the REST/PortfolioManager path (§2.6d).

2. **`filter_position_result(result: PositionResult, account_filters) -> PositionResult`** — filters a `PositionResult` object in-place and rebuilds metadata. Used by the MCP path (§2.6a, §2.6b, §2.6e). This replaces the `_filter_positions_to_accounts(position_result)` + `_reconsolidate(position_result)` pattern from earlier drafts. Implementation:
   - Filters `result.data.positions` using the same matching logic as `filter_positions_to_accounts()`
   - Rebuilds `result.total_value`, `result.position_count`, `result.by_type`, `result.by_source` from the filtered positions (aggregates live on the `PositionResult` wrapper, NOT on `result.data`)
   - Invalidates `result.data._cache_key` to prevent cross-portfolio cache collisions
   - Returns the modified `PositionResult` (mutated in-place for efficiency)

Both use the same matching logic:
```python
def _position_matches(p, filter_by_id: set, filter_by_name: set, ambiguous_names: set) -> bool:
    """Check if a position dict matches account_filters.

    Primary match: (institution_key, account_id_external) — always authoritative.
    Fallback match: (institution_key, account_name) — ONLY when the row has no account_id
    AND the name is NOT ambiguous (i.e., not shared by multiple accounts at the same institution).
    """
    inst = normalize_institution_slug(p.get("brokerage_name"))
    acct_id = p.get("account_id") or ""
    # Pseudo-account mapping: empty account_id → _unknown_{source}
    if not acct_id:
        acct_id = f"_unknown_{p.get('position_source', 'unknown')}"
    if (inst, acct_id) in filter_by_id:
        return True
    # account_name fallback: only when row has no real account_id AND name is unambiguous
    if not p.get("account_id") and p.get("account_name"):
        name_key = (inst, p["account_name"])
        if name_key in filter_by_name and name_key not in ambiguous_names:
            return True
    return False

def _build_filter_sets(account_filters):
    """Build filter lookup sets from account_filters, including ambiguity detection."""
    filter_by_id = {(inst, acct_id) for inst, acct_id, _ in account_filters}
    filter_by_name = {(inst, name) for inst, _, name in account_filters if name}
    # Detect ambiguous names: (inst, name) pairs that appear in >1 account_filter tuple
    name_counts = {}
    for inst, _, name in account_filters:
        if name:
            key = (inst, name)
            name_counts[key] = name_counts.get(key, 0) + 1
    ambiguous_names = {k for k, v in name_counts.items() if v > 1}
    return filter_by_id, filter_by_name, ambiguous_names

def filter_positions_to_accounts(positions: list[dict], account_filters: list[tuple]) -> list[dict]:
    """Filter raw position dicts to those matching account_filters."""
    filter_by_id, filter_by_name, ambiguous_names = _build_filter_sets(account_filters)
    return [p for p in positions if _position_matches(p, filter_by_id, filter_by_name, ambiguous_names)]

def filter_position_result(result: "PositionResult", account_filters: list[tuple]) -> "PositionResult":
    """Filter PositionResult in-place: remove non-matching positions, rebuild aggregates.

    PositionResult stores aggregates on self (not self.data):
    - result.total_value, result.position_count (floats/ints)
    - result.by_type, result.by_source (dicts)
    Positions use 'value' key (not 'market_value') and 'type' key (not 'instrument_type').
    """
    filter_by_id, filter_by_name, ambiguous_names = _build_filter_sets(account_filters)
    result.data.positions = [
        p for p in result.data.positions
        if _position_matches(p, filter_by_id, filter_by_name, ambiguous_names)
    ]
    # Rebuild aggregates from filtered positions (mirrors __post_init__ logic)
    result.position_count = len(result.data.positions)
    result.total_value = sum(float(p.get("value", 0) or 0) for p in result.data.positions)
    result.by_type = {}
    for p in result.data.positions:
        t = p.get("type", "other")
        result.by_type[t] = result.by_type.get(t, 0) + 1
    result.by_source = {}
    for p in result.data.positions:
        for src in str(p.get("position_source", "unknown")).split(","):
            src = src.strip()
            result.by_source[src] = result.by_source.get(src, 0) + 1
    # Invalidate PositionsData cache key to prevent cross-portfolio cache collisions.
    # The cache key is generated once in __post_init__ and reused by get_cache_key().
    # After filtering, force regeneration by clearing the cached value.
    if hasattr(result.data, '_cache_key'):
        result.data._cache_key = None  # will be regenerated on next access
    return result
```

#### 2.6a `mcp_tools/risk.py` — `_load_portfolio_for_analysis()`

```python
from services.portfolio_scope import resolve_portfolio_scope, LoadStrategy

def _load_portfolio_for_analysis(user_email, portfolio_name, use_cache=True):
    user, user_context = resolve_user_email(user_email)
    user_id = _resolve_user_id(user)

    scope = resolve_portfolio_scope(user_id, portfolio_name)

    if scope.strategy == LoadStrategy.PHYSICAL:
        # Manual portfolio: load from DB via existing PortfolioManager path
        manager = PortfolioManager(use_database=True, user_id=user_id)
        portfolio_data = manager._load_portfolio_from_database(portfolio_name)
        return user, user_id, portfolio_data  # preserves existing return order

    position_service = PositionService(user)
    if scope.strategy == LoadStrategy.VIRTUAL_FILTERED:
        # Fetch all (cached), filter to linked accounts, then consolidate
        position_result = position_service.get_all_positions(
            use_cache=use_cache, force_refresh=not use_cache, consolidate=False
        )
        position_result = filter_position_result(position_result, scope.account_filters)
    else:
        # VIRTUAL_ALL: all positions (unchanged behavior)
        position_result = position_service.get_all_positions(
            use_cache=use_cache, force_refresh=not use_cache, consolidate=True
        )
    # ... rest uses config_portfolio_name (see §2.7)
```

#### 2.6b `mcp_tools/performance.py` — `_load_portfolio_for_performance()`

Position loading for performance has **two entry points**:
- **REST route** (`routes/realized_performance.py`) calls `services/performance_helpers.load_portfolio_for_performance()`.
- **MCP tool** (`mcp_tools/performance.py`) uses its own `_select_load_portfolio_for_performance()` → `_load_portfolio_for_performance()` (local function, NOT the shared helper).

Both must add scope resolution. The cleanest approach: add scope resolution to the shared helper (`services/performance_helpers.load_portfolio_for_performance()`), then rewire the MCP tool to call it too (eliminating the local `_load_portfolio_for_performance()`). If that's too risky, update BOTH entry points in parallel:

```python
# In services/performance_helpers.py AND mcp_tools/performance.py:
def load_portfolio_for_performance(user_email, portfolio_name, ..., institution=None, account=None, ...):
    # ... existing user resolution ...
    scope = resolve_portfolio_scope(user_id, portfolio_name)

    if scope.strategy == LoadStrategy.PHYSICAL:
        # Manual portfolios: reject for realized mode (no transaction history)
        if mode == "realized":
            raise ValueError("Manual portfolios do not support realized performance (no transaction history)")
        # For hypothetical mode: load positions from DB via PortfolioManager
        # The shared helper returns a 4-tuple (user, user_id, portfolio_data, position_result).
        # For PHYSICAL, there is no PositionResult — construct a minimal one from DB positions
        # or refactor the caller to accept a 3-tuple. Recommended: add a `position_result=None`
        # sentinel, and guard callers that destructure it. The MCP hypothetical path only uses
        # portfolio_data (not position_result), so None is safe there.
        manager = PortfolioManager(use_database=True, user_id=user_id)
        portfolio_data = manager._load_portfolio_from_database(portfolio_name)
        return user, user_id, portfolio_data, None  # position_result=None for manual portfolios
    elif scope.strategy == LoadStrategy.VIRTUAL_FILTERED:
        # Override institution/account params with scope's account_filters
        position_result = position_service.get_all_positions(consolidate=False, ...)
        position_result = filter_position_result(position_result, scope.account_filters)
    else:
        # VIRTUAL_ALL: existing behavior (respect explicit institution/account if passed)
        position_result = position_service.get_all_positions(
            institution=institution, account=account, ...)
```

For realized performance specifically: `account_filters` must thread through the full call chain:

1. **`mcp_tools/performance.py`** (`get_performance()` line 440): Passes `scope.account_filters` to `_run_realized_with_service()` (new param)
2. **`mcp_tools/performance.py`** (`_run_realized_with_service()` line 165): Passes `account_filters` to `PortfolioService.analyze_realized_performance()` (new param)
3. **`services/portfolio_service.py`** (`analyze_realized_performance()` line 703): Add `account_filters: list[tuple[str, str, str | None]] | None = None` param (3-tuple: `institution_key, account_id_external, account_name`). Passes through to `analyze_realized_performance()` in aggregation module.
4. **`core/realized_performance/aggregation.py`** (`analyze_realized_performance()` line 63): Add `account_filters` param. Passes through to `_analyze_realized_performance_single_scope()` in engine.
5. **`core/realized_performance/engine.py`** (`_analyze_realized_performance_single_scope()`): Add `account_filters` param. The actual `load_from_store()` call lives HERE. When `account_filters` is not None, call `load_from_store_for_portfolio(user_id, account_filters, source=source)` instead of `load_from_store(user_id, source=source, institution=institution, account=account)`. When `account_filters` is None, use existing `load_from_store()` path unchanged.

**Additional store-read site:** `aggregation.py` also reads transactions directly via `_prefetch_fifo_transactions()` → `load_from_store()` for institution-aggregated analysis paths. When `account_filters` is present, this must also use `load_from_store_for_portfolio()` — or bypass the institution-aggregation path entirely (since portfolio scoping replaces institution-level scoping).

**Note:** `services/performance_helpers.py` is NOT in the store-load chain — it handles position loading and date validation, not transaction store reads. The store read happens inside engine.py.

The `source` param is preserved throughout (allows filtering by provider within the scoped accounts). The `institution`/`account` string params are ignored when `account_filters` is provided — the scope resolver has already resolved the correct account set.

**CSV transaction sources (deferred):** `aggregation.py` line 85-92 checks `CSVTransactionProvider.has_source()` BEFORE the DB store path. CSV storage is global (file-based, not per-user or per-account) — `CSVTransactionProvider` stores by source name only, and imported rows typically lack `institution`/`account_id` metadata. Portfolio-scoped CSV analysis is NOT supported in Phase 2. When `account_filters` is provided AND the source hits the CSV path:
- Realized performance: skip CSV path, fall through to DB store path (CSV data should have been ingested to DB via `fetch_provider_transactions` for scoped analysis)
- Trading analysis: same — skip CSV, use DB store
- If the user explicitly requests a CSV-only source with a non-CURRENT_PORTFOLIO, return a clear error: "CSV sources do not support portfolio scoping. Use 'fetch_provider_transactions' to import into the transaction store first."

CSV storage redesign (per-user, per-import keyed) is deferred to follow-up work.

#### 2.6c `mcp_tools/trading_analysis.py` — `get_trading_analysis()`

Currently has three branches: (1) CSV store via `CSVTransactionProvider`, (2) DB store via `load_from_store()`, (3) live fetch via `fetch_transactions_for_source()`. Must add portfolio scope to all three.

Add `portfolio_name` param (default `"CURRENT_PORTFOLIO"`) and resolve scope early:

```python
def get_trading_analysis(user_email=None, portfolio_name="CURRENT_PORTFOLIO", ...):
    # ... existing validation + user resolution ...
    scope = resolve_portfolio_scope(user_id, portfolio_name)

    if scope.strategy == LoadStrategy.PHYSICAL:
        # Manual portfolios: reject (no transaction history — positions are static DB rows)
        raise ValueError("Manual portfolios do not support trading analysis (no transaction history)")

    # Branch 1: CSV store — portfolio scoping NOT supported
    csv_store = CSVTransactionProvider()
    if csv_store.has_source(user, source):
        if scope.strategy == LoadStrategy.VIRTUAL_FILTERED:
            raise ValueError(
                "CSV sources do not support portfolio scoping. "
                "Use 'fetch_provider_transactions' to import into the transaction store first."
            )
        # VIRTUAL_ALL: existing CSV path unchanged
        store_data = csv_store.load_transactions(user, source)
        fifo_transactions = list(store_data.get("fifo_transactions") or [])
        # ... existing TradingAnalyzer setup ...

    # Branch 2: DB transaction store
    elif TRANSACTION_STORE_READ and is_db_available():
        if scope.strategy == LoadStrategy.VIRTUAL_FILTERED:
            # Use scoped loader instead of load_from_store()
            store_data = load_from_store_for_portfolio(user_id, scope.account_filters, source=source)
        else:
            # VIRTUAL_ALL: existing load_from_store() path unchanged
            store_data = load_from_store(user_id=user_id, source=source, institution=institution, account=account)
        # ... existing TradingAnalyzer setup ...

    # Branch 3: Live fetch (no DB)
    else:
        # VIRTUAL_FILTERED without DB: impossible (resolve_portfolio_scope raises in rule 2)
        # VIRTUAL_ALL: existing fetch_transactions_for_source() path unchanged
        fetch_result = fetch_transactions_for_source(user_email=user, source=source, ...)
        # ... existing TradingAnalyzer setup ...
```

#### 2.6d `inputs/portfolio_manager.py` — `_load_portfolio_from_database()`

```python
from services.portfolio_scope import resolve_portfolio_scope, LoadStrategy

def _load_portfolio_from_database(self, portfolio_name: str) -> PortfolioData:
    scope = resolve_portfolio_scope(self.internal_user_id, portfolio_name)

    if scope.strategy == LoadStrategy.PHYSICAL:
        # Manual portfolio: load POSITIONS + EXPECTED RETURNS from physical DB (portfolio_id JOIN)
        portfolio_payload = self.repository.load_full_portfolio(
            self.internal_user_id, portfolio_name)
        # Override factor_proxies + target_allocations from CURRENT_PORTFOLIO (§2.7):
        # These are portfolio-scoped config that manual portfolios inherit.
        # But NOT expected_returns — manual portfolios may have unique tickers
        # not in CURRENT_PORTFOLIO (§2.7 expected_returns_portfolio_name).
        # Fallback: if CURRENT_PORTFOLIO doesn't exist (manual-only user), use empty config.
        try:
            config_payload = self.repository.load_full_portfolio(
                self.internal_user_id, "CURRENT_PORTFOLIO")
        except PortfolioNotFoundError:
            config_payload = {"factor_proxies": {}, "target_allocations": {}}
        portfolio_payload["factor_proxies"] = config_payload.get("factor_proxies", {})
        portfolio_payload["target_allocations"] = config_payload.get("target_allocations", {})
        # expected_returns stays from the manual portfolio's own ticker set
        # _ensure_factor_proxies() uses "CURRENT_PORTFOLIO" (scope.config_portfolio_name)
    elif scope.strategy == LoadStrategy.VIRTUAL_FILTERED:
        # Fetch all CURRENT_PORTFOLIO positions, filter to linked accounts
        portfolio_payload = self.repository.load_full_portfolio(
            self.internal_user_id, "CURRENT_PORTFOLIO")
        raw_positions = portfolio_payload["raw_positions"]
        # Use shared filter helper (same as MCP path — handles pseudo-account mapping)
        raw_positions = filter_positions_to_accounts(raw_positions, scope.account_filters)
        portfolio_payload["raw_positions"] = raw_positions
        # expected_returns, factor_proxies, target_allocations pass through unchanged:
        # they are ticker-keyed, not account-keyed, so extra entries for tickers
        # not in the filtered positions are harmless (unused by downstream)
        # portfolio_metadata (start_date, end_date) from CURRENT_PORTFOLIO is correct:
        # virtual portfolios share the same analysis window as the combined portfolio
        # _ensure_factor_proxies() MUST use "CURRENT_PORTFOLIO", not the virtual portfolio name,
        # to avoid persisting phantom proxy rows under auto-generated names
        # ... rest of assembly (pass "CURRENT_PORTFOLIO" to _ensure_factor_proxies)
    else:
        # VIRTUAL_ALL: load CURRENT_PORTFOLIO (unchanged)
        portfolio_payload = self.repository.load_full_portfolio(
            self.internal_user_id, "CURRENT_PORTFOLIO")
        # ... existing assembly logic unchanged
```

#### 2.6e `mcp_tools/income.py` — `get_income_projection()`

Currently calls `_load_positions_for_income()` → `PositionService.get_all_positions(consolidate=True)` with no portfolio scoping. Add `portfolio_name` param (default `"CURRENT_PORTFOLIO"`):

```python
def get_income_projection(user_email=None, portfolio_name="CURRENT_PORTFOLIO", ...):
    scope = resolve_portfolio_scope(user_id, portfolio_name)

    if scope.strategy == LoadStrategy.PHYSICAL:
        # Manual portfolios: income projection NOT supported.
        # DB position rows (from get_portfolio_positions()) lack `value` (current market value),
        # which the income engine needs for portfolio yield-on-value and position weighting.
        # Manual portfolios store static position data at import time without live pricing.
        # Price enrichment would require a full ProviderRegistry lookup per ticker — too
        # heavyweight for income projection and not consistent with the manual portfolio model.
        raise ValueError(
            "Manual portfolios do not support income projection (no live market values). "
            "Use a provider-synced portfolio for income analysis."
        )
    elif scope.strategy == LoadStrategy.VIRTUAL_FILTERED:
        position_result = position_service.get_all_positions(consolidate=False, ...)
        position_result = filter_position_result(position_result, scope.account_filters)
        positions = [p for p in position_result.data.positions if ...]
    else:
        # VIRTUAL_ALL: existing behavior
        positions = _load_positions_for_income(user_email, use_cache)
```

Income projection uses only positions + FMP dividend API data — no transaction store access. Virtual portfolio types (combined, single_account, custom) support it. Manual portfolios do NOT — their DB position rows lack live `value` (market value) needed for yield-on-value calculations.

**Design: fetch all → filter.** Simple, preserves provider caching, O(n) filter on in-memory list. DB unavailable + non-CURRENT_PORTFOLIO → error (not silent all-positions fallback).

### 2.7 Config Resolution Strategy

**Config splits into two categories:**

1. **Shared config** (always from CURRENT_PORTFOLIO): Factor proxies, risk limits, target allocations. These are portfolio-scoped config that ALL portfolios (virtual AND manual) inherit from CURRENT_PORTFOLIO. Using CURRENT_PORTFOLIO avoids `RiskLimitsManager` auto-creating phantom default rows for auto-generated portfolio names.

2. **Expected returns** (portfolio-type dependent): Virtual portfolios use CURRENT_PORTFOLIO (positions live there). Manual portfolios use **their own portfolio name** — manual portfolios may contain unique tickers not in CURRENT_PORTFOLIO, so using CURRENT_PORTFOLIO would return incomplete ticker coverage for optimization/efficient frontier.

**Why shared config from CURRENT_PORTFOLIO?** Manual portfolios (CSV imports) rarely have meaningful config — they're typically used for what-if analysis, not ongoing risk management. The `RiskLimitsManager.load_risk_limits()` auto-creates default risk limits when a portfolio name has no rows — if we pass a virtual portfolio name like `_auto_schwab_ira`, it would create phantom risk_limits rows in the DB. Using CURRENT_PORTFOLIO for shared config avoids this hazard.

**Mechanism:** `PortfolioScope` includes a `config_portfolio_name` field, always set to `"CURRENT_PORTFOLIO"`. All code paths that load config must use `scope.config_portfolio_name` instead of the raw `portfolio_name`. **Fallback for manual-only users:** If CURRENT_PORTFOLIO doesn't exist (user has never synced positions), config-loading callers must catch `PortfolioNotFoundError` and fall back to empty config (`{}` for factor_proxies, target_allocations). `RiskLimitsManager` must also handle this — check portfolio exists before auto-creating defaults.

```python
@dataclass
class PortfolioScope:
    strategy: LoadStrategy
    portfolio_name: str
    config_portfolio_name: str = "CURRENT_PORTFOLIO"  # always CURRENT_PORTFOLIO
    expected_returns_portfolio_name: str = "CURRENT_PORTFOLIO"  # PHYSICAL→portfolio_name, else CURRENT_PORTFOLIO
    account_filters: list[tuple[str, str, str | None]] | None = None  # (institution_key, account_id_external, account_name)
```

Every site that passes `portfolio_name` to a config-loading function (`RiskLimitsManager.load_risk_limits()`, `ensure_factor_proxies()`, `get_target_allocations()`, `save_risk_limits()`, `get_factor_proxies()`) must use `scope.config_portfolio_name` instead. `get_expected_returns()` uses `scope.expected_returns_portfolio_name` (see §2.7 Expected returns section). The implementation step is:
1. `grep -rn 'portfolio_name' mcp_tools/ app.py inputs/portfolio_manager.py services/` to find all config call sites
2. For each, if the call passes `portfolio_name` to a config function, replace with `scope.config_portfolio_name`
3. This is a mechanical replacement — the PortfolioScope object flows through all entry points (§2.6a-d)

**Known config-loading functions** (all must receive `config_portfolio_name`):
- `RiskLimitsManager.load_risk_limits(portfolio_name)` — auto-creates defaults if missing (line 412)
- `RiskLimitsManager.save_risk_limits(limits, portfolio_name)` — persists under portfolio_name
- `ensure_factor_proxies(user_id, portfolio_name, ...)` — persists proxies under portfolio_name
- `repo.get_target_allocations(user_id, portfolio_name)` — reads from target_allocations table
- `repo.get_factor_proxies(user_id, portfolio_name)` — reads from factor_proxies table

**Expected returns — strategy depends on portfolio type:**
- `repo.get_expected_returns(user_id, portfolio_name)` first queries tickers via `positions JOIN portfolios WHERE name=%s` (database_client.py line 844-848), then fetches user-level expected_returns for those tickers.
- **Virtual portfolios** (combined/single_account/custom): Always pass `config_portfolio_name` (= CURRENT_PORTFOLIO). Virtual portfolios have no physical portfolio row with their name — all positions live under CURRENT_PORTFOLIO. This returns a superset of tickers — extra entries for tickers not in the filtered position set are harmless (unused by downstream).
- **Manual portfolios**: Pass the **manual portfolio's own name** (not CURRENT_PORTFOLIO). Manual portfolios have their own physical portfolio row + positions in the DB — `get_expected_returns(user_id, "manual_test")` correctly resolves the manual portfolio's ticker set. Manual portfolios may contain tickers not present in CURRENT_PORTFOLIO (e.g., imported CSV with different holdings). Using CURRENT_PORTFOLIO would miss these tickers, breaking optimization/efficient frontier.
- **Implementation:** `PortfolioScope` adds a `expected_returns_portfolio_name` field: for PHYSICAL strategy = `portfolio_name`; for VIRTUAL_ALL/VIRTUAL_FILTERED = `config_portfolio_name` (= CURRENT_PORTFOLIO). Call sites use this instead of a blanket `config_portfolio_name`.

**Expected returns routing (critical):** Optimization and compare tools call `DatabaseClient.get_expected_returns(user_id, portfolio_name)` DIRECTLY (optimization.py line 130, compare.py line 159), bypassing `ReturnsService`. The `get_expected_returns()` query resolves tickers via `positions JOIN portfolios WHERE name=%s` — for virtual portfolios, the virtual name has no physical portfolio row → empty result. Similarly, `get_expected_returns_dates()` uses the same `positions JOIN portfolios` query. ALL callers that pass `portfolio_name` to expected-returns functions must use `scope.expected_returns_portfolio_name`:
- `mcp_tools/optimization.py` line 130 — direct `db_client.get_expected_returns()` call
- `mcp_tools/compare.py` line 159 — direct `db_client.get_expected_returns()` call
- `services/returns_service.py` `get_complete_returns()` — also loads expected returns with portfolio_name
- `services/returns_service.py` `validate_returns_coverage()` / `_validate_complete_coverage()` — calls `PortfolioManager.get_expected_returns(portfolio_name)` directly
- `app.py` `/api/expected-returns` handler — calls `pm.get_expected_returns(portfolio_name)` and `pm.get_expected_returns_dates(portfolio_name)` directly

**Sample sites** (non-exhaustive — grep-based audit required during implementation):
- `mcp_tools/risk.py` lines 454, 573, 707, 782, 999
- `mcp_tools/optimization.py` lines 107, 210
- `mcp_tools/whatif.py` lines 132, 143
- `mcp_tools/compare.py` lines 240, 248, 261
- `services/returns_service.py` line 354 (`get_complete_returns`)
- `app.py` lines 1211, 1508, 1829, 4704
- `inputs/portfolio_manager.py` lines 343, 625

Per-portfolio config customization is a future enhancement.

### 2.8 Transaction Store Scoping

**Critical implementation detail:** All transaction store read methods (`load_fifo_transactions`, `load_income_events`, `load_provider_flow_events`, `load_futures_mtm`) explicitly `del institution` — the `institution` parameter is accepted but **never used in SQL**. FIFO transaction dicts use `_institution` (underscore prefix) as the institution key (line 1008 in transaction_store.py), not `institution`.

**Design: call individual TransactionStore methods directly, then post-filter.** We cannot use the top-level `load_from_store()` convenience function because:
- It wraps income events in `StoreBackedIncomeProvider` (stores `NormalizedIncome` objects, not raw dicts — no `_events` attribute to filter)
- Multiple per-account calls would duplicate reference data and overwrite non-list return values

Instead, `load_from_store_for_portfolio()` opens one DB connection, calls each `TransactionStore` method directly to get raw lists, post-filters, then wraps:

```python
def load_from_store_for_portfolio(
    user_id: int,
    account_filters: list[tuple[str, str, str | None]],  # (institution_key, account_id_external, account_name)
    source: Optional[str] = None,  # preserves provider filtering (e.g., source="ibkr_flex")
) -> dict[str, Any]:
    """Load transaction data scoped to a portfolio's linked accounts.

    1. Open ONE DB connection, call individual TransactionStore methods (no account filter)
    2. Post-filter each result list by (institution_key, account_id) from account_filters
    3. Wrap filtered income events in StoreBackedIncomeProvider

    The source= param is passed through to all store methods (provider filtering).
    The institution/account SQL params are NOT used (store methods del institution anyway).

    Key field mappings per result type:
    - fifo_transactions: institution in '_institution' key, account in 'account_id' key
    - provider_flow_events: institution in 'institution' key, account in 'account_id' key
    - income_events: raw dicts with 'institution' key, account in 'account_id' key
    - futures_mtm_events: always IBKR, filter by _row_matches() (account_id or account_name)
    - flex_option_price_rows: reference data, no filtering needed
    - fetch_metadata: per-provider ingestion batch metadata. Contains `account_id` and
      `institution` fields. Filtered by the same _row_matches() logic — the realized
      performance engine uses fetch_metadata for flow authority and statement-cash anchors,
      so unscoped metadata would corrupt those calculations.
      **Known limitation:** `load_fetch_metadata()` selects only the latest completed
      ingestion batch per provider (via `ROW_NUMBER() OVER (PARTITION BY provider ...)`).
      Post-filtering this already-collapsed list works correctly when all accounts are
      ingested in the same batch (the common case). However, if an account's last successful
      ingest is NOT the provider's latest batch (e.g., due to a partial failure), its
      metadata will be absent. This is a pre-existing limitation of the batch-level
      granularity — portfolio scoping does not make it worse. A per-account metadata
      query would be a future enhancement if needed.
    """
    provider = TransactionStore._normalized_provider_filter(source)

    # Build allowed sets — include both account_id and account_name for matching
    # (transaction store SQL matches `account_id = %s OR account_name = %s`)
    allowed_by_id = {(inst_key, acct_id) for inst_key, acct_id, _ in account_filters}
    allowed_by_name = {(inst_key, acct_name) for inst_key, _, acct_name in account_filters if acct_name}
    # Detect ambiguous names (same institution+name in multiple accounts)
    name_counts: dict = {}
    for inst_key, _, acct_name in account_filters:
        if acct_name:
            key = (inst_key, acct_name)
            name_counts[key] = name_counts.get(key, 0) + 1
    ambiguous_names = {k for k, v in name_counts.items() if v > 1}

    def _row_matches(row: dict) -> bool:
        inst = normalize_institution_slug(
            row.get("_institution") or row.get("institution") or row.get("brokerage_name") or ""
        )
        acct_id = row.get("account_id") or ""
        if acct_id and (inst, acct_id) in allowed_by_id:
            return True
        # account_name match: check regardless of whether account_id is present,
        # matching the existing `match_account()` OR semantics (account_id OR account_name).
        # This handles cases where positions and transactions use different IDs for the same account
        # (e.g., provider format differences). Only match unambiguous names.
        acct_name = row.get("account_name") or ""
        if acct_name:
            name_key = (inst, acct_name)
            if name_key in allowed_by_name and name_key not in ambiguous_names:
                return True
        return False

    with get_db_session() as conn:
        store = TransactionStore(conn)

        # Load raw data (no account/institution filters — we filter in Python)
        fifo_raw = store.load_fifo_transactions(user_id, provider=provider)
        income_raw = store.load_income_events(user_id, provider=provider)
        flow_raw = store.load_provider_flow_events(user_id, provider=provider)
        fetch_metadata = store.load_fetch_metadata(user_id, provider=provider)

        futures_mtm = []
        flex_option_prices = []
        if provider in {None, "ibkr_flex"}:
            futures_mtm = store.load_futures_mtm(user_id)
            flex_option_prices = store.load_flex_option_prices(user_id)

    # Post-filter by account
    fifo_filtered = [r for r in fifo_raw if _row_matches(r)]
    flow_filtered = [r for r in flow_raw if _row_matches(r)]
    income_filtered = [r for r in income_raw if _row_matches(r)]
    futures_filtered = [r for r in futures_mtm if _row_matches(r)]
    # flex_option_prices: reference data (IBKR option pricing), keep all
    # fetch_metadata: has account_id/institution — filter for scoped flow authority
    fetch_metadata_filtered = [r for r in fetch_metadata if _row_matches(r)]

    return {
        "fifo_transactions": fifo_filtered,
        "futures_mtm_events": futures_filtered,
        "flex_option_price_rows": flex_option_prices,
        "provider_flow_events": flow_filtered,
        "fetch_metadata": fetch_metadata_filtered,
        "income_provider": StoreBackedIncomeProvider(income_filtered),
    }
```

**Pseudo-account limitation:** Pseudo-accounts (NULL account_id → `_unknown_{source}`) exist only as position-level constructs for portfolio linkage. Transaction rows with NULL account_id will NOT match pseudo-account filters because their `account_id` is empty/NULL, not `_unknown_plaid`. This is acceptable: pseudo-account positions typically come from legacy imports without transaction history. If a combined portfolio includes pseudo-accounts, their transactions naturally appear in the unfiltered CURRENT_PORTFOLIO path. Single-account portfolios linked to pseudo-accounts will show positions but no realized performance/trading data — consistent with the manual portfolio behavior.

**Call sites that must use `load_from_store_for_portfolio()`** when `scope.strategy == VIRTUAL_FILTERED`:
- `core/realized_performance/engine.py` (`_analyze_realized_performance_single_scope()`): this is the **actual** `load_from_store()` call site for realized performance. `aggregation.py` passes `account_filters` through; `services/performance_helpers.py` is NOT in the store-load chain (it handles positions/dates).
- `mcp_tools/trading_analysis.py`: new portfolio-scoped path (§2.6c)

### 2.9 Auto-Managed Portfolio Guards

**Naming:**
- Auto-generated single_account portfolios use `_auto_` prefix: e.g., `_auto_schwab_rollover_ira`
- Name generation: `_auto_{institution_key}_{sanitized_account_name}` where `sanitized_account_name = re.sub(r'[^a-z0-9]+', '_', account_name.lower()).strip('_')`
- **Collision resolution:** If the generated name already exists for this user (e.g., two Schwab accounts both named "Brokerage"), append `__{account_id_external[-6:]}` (last 6 chars of external ID). Example: `_auto_schwab_brokerage__abc123`. If account_name is blank/None, use `_auto_{institution_key}__{account_id_external[-8:]}`
- Users cannot create portfolio names starting with `_auto_` or `_system_`
- `CURRENT_PORTFOLIO` is a reserved name — undeletable, unrenameable

**Guards on DatabaseClient/API:**
- `delete_portfolio`: reject if `auto_managed=true` OR `name='CURRENT_PORTFOLIO'`
- `rename_portfolio`: reject if `auto_managed=true`
- `create_portfolio`: reject if name starts with `_auto_` or `_system_`, or name is `CURRENT_PORTFOLIO`
- Existing delete in `app.py` (line 3804) and `inputs/portfolio_manager.py` (line 535) must check `auto_managed` before executing

**Same-user integrity for portfolio_accounts:**
All `portfolio_accounts` write operations (`create_portfolio`, `update_portfolio_accounts`, auto-sync) must validate that every `account_id` belongs to the same user as the portfolio. The `portfolio_accounts` join table has FKs to `portfolios` and `accounts` but no user-level constraint — a guessed `accounts.id` from another user could be linked without validation. Enforce at the service layer:
```python
# In create_portfolio / update_portfolio_accounts:
user_accounts = {a["id"] for a in registry.get_user_accounts()}
invalid = set(account_ids) - user_accounts
if invalid:
    raise ValueError(f"Account IDs {invalid} do not belong to this user")
```

**Legacy mutation route guards (critical):**
The existing `POST /api/portfolios` (app.py) and `PortfolioRepository.save_portfolio_to_database()` (called by `PortfolioManager.save_portfolio_data()` → private `_save_portfolio_to_database()`) can create/overwrite any portfolio by name. These must be hardened:
- `PortfolioRepository.save_portfolio_to_database()` / `DatabaseClient.save_portfolio()`: reject if target name is `CURRENT_PORTFOLIO`, starts with `_auto_` or `_system_`, or targets an existing row with `portfolio_type != 'manual'`. Only `manual`-type portfolios may be created/overwritten via this path.
- `POST /api/portfolios` (app.py): same guards at the route level — validate name + type before calling save
- `PUT /api/portfolios/{name}` (app.py): reject if target portfolio has `auto_managed=true` or `portfolio_type` in (`combined`, `single_account`, `custom`)
- These guards ensure legacy save routes cannot overwrite virtual portfolios (combined/single_account/custom) — only manual portfolios flow through the physical save path

**List response includes type info:**
- `GET /api/v2/portfolios` (Phase 3) returns `portfolio_type` and `auto_managed` per portfolio
- Existing `GET /api/portfolios` response is backward-compatible (no new fields required)

### 2.10 Sync Hook Update

Update the position sync hook from Phase 1:
```python
# In _save_positions_to_db(), after account discovery:
registry.ensure_combined_portfolio_metadata()
# On EVERY sync (idempotent): ensure CURRENT_PORTFOLIO row has correct metadata.
# database_client.save_portfolio() only sets (user_id, name, start_date, end_date) on INSERT —
# it does NOT set portfolio_type, display_name, auto_managed, is_active.
# This method runs: UPDATE portfolios SET portfolio_type='combined', display_name='All Accounts',
#   auto_managed=true, is_active=true WHERE user_id=%s AND name='CURRENT_PORTFOLIO'
# This is idempotent and handles both first-sync (row just created with NULLs) and subsequent syncs.

registry.refresh_combined_portfolio()
# Replaces (not appends) CURRENT_PORTFOLIO's portfolio_accounts membership with the
# exact set of accounts that currently have positions under CURRENT_PORTFOLIO.
# Steps:
# 1. Find all accounts matching current CURRENT_PORTFOLIO positions (same predicate as §2.4 step 5)
# 2. DELETE any portfolio_accounts rows linking CURRENT_PORTFOLIO to accounts NOT in that set
# 3. INSERT any missing portfolio_accounts rows for newly discovered accounts
# This handles position-level account removal during sync. However, provider disconnect/delete
# routes (Plaid unlink, SnapTrade disconnect) may bypass _save_positions_to_db() entirely
# and call delete_provider_positions() directly. These disconnect routes MUST also call
# registry.refresh_combined_portfolio() + registry.ensure_single_account_portfolios()
# after deleting positions, to clean up stale portfolio_accounts links and soft-hide
# _auto_* portfolios for removed accounts. Add hooks in:
# - routes/plaid.py: unlink path (~line 1554) AND DELETE /plaid/user (~line 1626)
# - routes/snaptrade.py: disconnect path (~line 969) AND DELETE /api/snaptrade/user (~line 1059)

registry.ensure_single_account_portfolios()
# For each account linked to CURRENT_PORTFOLIO:
# - If no _auto_* portfolio exists → create one (with collision resolution per §2.9)
# - If an _auto_* portfolio exists but its account is no longer linked → mark is_active=false
#   on the _auto_* portfolio (soft-hide, not delete — preserves name reservation)
# For stale _auto_* portfolios (is_active=false), the list API excludes them by default
# but they can be shown with include_inactive=true.
```

**Empty portfolio handling:** If a position sync results in zero positions for a previously populated account (e.g., all holdings sold), that account's `_auto_*` portfolio becomes empty. To avoid the `PortfolioData` empty-input validation error:
- `resolve_portfolio_scope()` for VIRTUAL_FILTERED: if `account_filters` resolves to zero matching positions, return early with a clear error "No positions found for this portfolio" BEFORE attempting PortfolioData construction.
- The `list_portfolios` API includes a `position_count` field per portfolio so the frontend can show empty portfolios as "(empty)" rather than triggering a load.

### 2.11 Files Changed

| File | Action |
|------|--------|
| `database/migrations/20260313_portfolio_accounts.sql` | **New** — DDL + portfolio type tagging (SQL, steps 1-4, with slug-fixup guard) |
| `scripts/link_portfolio_accounts.py` | **New** — Account linking + `_auto_*` creation (Python, step 5 — runs after slug fixup) |
| `services/portfolio_scope.py` | **New** — shared `resolve_portfolio_scope()` + `LoadStrategy` enum |
| `services/account_registry.py` | Add portfolio management methods, name collision resolution |
| `mcp_tools/risk.py` | `_load_portfolio_for_analysis()` — use shared resolver; config callers use `config_portfolio_name` |
| `mcp_tools/performance.py` | Rewire to shared helper OR update local `_load_portfolio_for_performance()` + `_select_load_portfolio_for_performance()` — both must use shared resolver; store scoping for realized perf |
| `mcp_tools/trading_analysis.py` | Add `portfolio_name` param, use shared resolver for scoped transactions |
| `mcp_tools/income.py` | Add `portfolio_name` param, use shared resolver for scoped positions |
| `mcp_tools/positions.py` | Add scope resolution to `get_positions()` and `export_holdings()` — both call `get_all_positions()` without portfolio filtering |
| `mcp_tools/optimization.py` | `load_risk_limits()` calls use `config_portfolio_name` |
| `mcp_tools/whatif.py` | `load_risk_limits()` calls use `config_portfolio_name` |
| `mcp_tools/compare.py` | `load_risk_limits()` calls use `config_portfolio_name` |
| `services/portfolio_service.py` | `analyze_realized_performance()` — add `account_filters` param, pass through to aggregation |
| `services/performance_helpers.py` | Add scope resolution via `resolve_portfolio_scope()`. `load_portfolio_for_performance()` must filter positions for VIRTUAL_FILTERED and reject/redirect for PHYSICAL. Currently used by REST (`routes/realized_performance.py`). The MCP tool (`mcp_tools/performance.py`) uses its own local `_load_portfolio_for_performance()` wrapper — either rewire it to use the shared helper, or add scope resolution to BOTH. |
| `services/returns_service.py` | `get_complete_returns()` must receive `scope.expected_returns_portfolio_name` (not raw portfolio_name) |
| `core/realized_performance/aggregation.py` | Thread `account_filters` param through to engine. Also update `_prefetch_fifo_transactions()` to use `load_from_store_for_portfolio()` when `account_filters` is present — this method also reads transactions directly via `load_from_store()` for institution-aggregated analysis. |
| `core/realized_performance/engine.py` | Accept `account_filters`, call `load_from_store_for_portfolio()` when present (this is where the actual store read lives) |
| `inputs/portfolio_manager.py` | `_load_portfolio_from_database()` — use shared resolver, normalize brokerage_name for filter |
| `inputs/transaction_store.py` | Add `load_from_store_for_portfolio()` — fetch-all-then-post-filter design |
| `inputs/database_client.py` | Add portfolio_accounts CRUD, auto_managed guards, `portfolio_type='manual'` on `save_portfolio()` |
| `app.py` | Guard DELETE, use shared resolver for GET, risk_limits calls use config_portfolio_name |
| `services/position_service.py` | Add `refresh_combined_portfolio()` to sync hook |
| `routes/plaid.py` | Add `refresh_combined_portfolio()` + `ensure_single_account_portfolios()` to unlink (~line 1554) and DELETE user (~line 1626) paths |
| `routes/snaptrade.py` | Add `refresh_combined_portfolio()` + `ensure_single_account_portfolios()` to disconnect (~line 969) and DELETE user (~line 1059) paths |
| `mcp_server.py` | Expose `portfolio_name` param on `get_trading_analysis`, `get_income_projection`, `export_holdings`, and any other MCP tool registrations that accept portfolio scoping (default `"CURRENT_PORTFOLIO"`) |

### 2.12 Tests

- Unit: `resolve_portfolio_scope()` returns VIRTUAL_ALL for CURRENT_PORTFOLIO
- Unit: `resolve_portfolio_scope()` returns VIRTUAL_FILTERED for single_account with correct account_filters
- Unit: `resolve_portfolio_scope()` returns PHYSICAL for manual portfolio
- Unit: `resolve_portfolio_scope()` raises error when DB unavailable + non-CURRENT_PORTFOLIO
- Unit: `filter_positions_to_accounts()` correctly filters raw position dict list
- Unit: `filter_position_result()` filters PositionResult and rebuilds metadata (total_value, by_type, by_source)
- Unit: Position filter normalizes brokerage_name before comparing to institution_key
- Unit: `load_from_store_for_portfolio()` post-filters FIFO rows using `_institution` key (not `institution`)
- Unit: `load_from_store_for_portfolio()` rebuilds StoreBackedIncomeProvider from filtered events
- Unit: `load_from_store_for_portfolio()` preserves flex_option_price_rows unfiltered, filters fetch_metadata by account
- Unit: account_name fallback skipped when name is ambiguous (same institution, multiple accounts with same name)
- Unit: auto_managed guard blocks delete/rename
- Unit: reserved name guard blocks `_auto_*` and `CURRENT_PORTFOLIO` creation
- Unit: auto-generated name collision resolved with account_id suffix
- Unit: manual portfolios loaded via physical DB path (existing `load_full_portfolio()`)
- Unit: config_portfolio_name = "CURRENT_PORTFOLIO" used for risk_limits in virtual portfolios
- Integration: `get_risk_analysis(portfolio_name="_auto_schwab_rollover_ira")` → only Schwab IRA positions
- Integration: `get_risk_analysis(portfolio_name="CURRENT_PORTFOLIO")` → all positions (no regression)
- Integration: `GET /api/portfolios/_auto_schwab_rollover_ira` → scoped positions via PortfolioManager
- Integration: `get_performance(portfolio_name="_auto_schwab_rollover_ira")` → scoped realized performance
- Integration: `get_trading_analysis(portfolio_name="_auto_schwab_rollover_ira")` → scoped trading analysis
- Unit: manual portfolio + realized performance → clear error "no transaction history"
- Unit: manual portfolio + trading analysis → clear error "no transaction history"
- No-DB mode (MCP only — REST requires DB): CURRENT_PORTFOLIO works (MCP→providers); non-CURRENT_PORTFOLIO errors

---

## Phase 3: Portfolio Management MCP Tools + API

**Goal:** Tools for listing accounts, listing/creating/editing portfolios. Both MCP and REST.

### 3.1 New MCP Tools

**New file: `mcp_tools/portfolio_management.py`**

```python
@handle_mcp_errors
@require_db
def list_accounts(user_email=None, active_only=True) -> dict:
    """List financial accounts grouped by institution.
    Returns: institution_key, institution_display_name, account_id_external,
    account_name, account_type, is_active, data_source provider (if linked)."""

@handle_mcp_errors
@require_db
def list_portfolios(user_email=None, include_accounts=False, include_inactive=False) -> dict:
    """List portfolios with type, account count, display name.
    Always returns portfolio_type and auto_managed fields.
    include_accounts=True adds linked account details per portfolio.
    include_inactive=False (default) excludes portfolios with is_active=false
    (stale _auto_* portfolios whose accounts were disconnected)."""

@handle_mcp_errors
@require_db
def create_portfolio(user_email=None, name="", display_name="", account_ids=None) -> dict:
    """Create a custom portfolio with selected accounts.
    account_ids: list of accounts.id integers from list_accounts().
    Validates: name not starting with '_auto_' or '_system_', not 'CURRENT_PORTFOLIO'.
    Validates: account_ids must be non-empty (at least one account required).
    Validates: all account_ids must be linked to CURRENT_PORTFOLIO (i.e., sync-backed
    accounts with positions in the virtual pool). Manual-only accounts cannot be added
    to custom portfolios because virtual reads fetch from CURRENT_PORTFOLIO — an account
    with no positions there would contribute zero positions, which is confusing.
    Sets portfolio_type='custom', auto_managed=false."""

@handle_mcp_errors
@require_db
def update_portfolio_accounts(user_email=None, portfolio_name="", add=None, remove=None) -> dict:
    """Add/remove accounts from a custom portfolio.
    Rejects changes to auto_managed portfolios.
    Rejects changes to manual portfolios (positions are self-contained).
    Added account_ids must be linked to CURRENT_PORTFOLIO (same validation as create_portfolio).
    Rejects removal that would leave zero linked accounts — custom portfolios must always
    have at least one account."""

@handle_mcp_errors
@require_db
def delete_portfolio(user_email=None, portfolio_name="") -> dict:
    """Delete a custom or manual portfolio.
    Rejects auto_managed portfolios (combined + single_account)."""
```

### 3.2 REST API

```
GET  /api/v2/accounts                         → list accounts
GET  /api/v2/portfolios                       → list portfolios with metadata
POST /api/v2/portfolios                       → create custom portfolio
PUT  /api/v2/portfolios/{name}/accounts       → modify portfolio accounts
DELETE /api/v2/portfolios/{name}              → delete custom/manual portfolio (rejects auto_managed)
```

Response shape for `GET /api/v2/portfolios`:
```json
{
  "portfolios": [
    { "name": "CURRENT_PORTFOLIO", "display_name": "All Accounts", "portfolio_type": "combined", "account_count": 5, "position_count": 42, "auto_managed": true, "supported_modes": ["risk", "performance_hypothetical", "performance_realized", "trading", "income", "optimization"] },
    { "name": "_auto_schwab_rollover_ira", "display_name": "Schwab Rollover IRA", "portfolio_type": "single_account", "account_count": 1, "position_count": 15, "auto_managed": true, "supported_modes": ["risk", "performance_hypothetical", "performance_realized", "trading", "income", "optimization"] },
    { "name": "active_trading", "display_name": "Active Trading", "portfolio_type": "custom", "account_count": 2, "position_count": 28, "auto_managed": false, "supported_modes": ["risk", "performance_hypothetical", "performance_realized", "trading", "income", "optimization"] },
    { "name": "manual_test", "display_name": "Manual Test", "portfolio_type": "manual", "account_count": 0, "position_count": 5, "auto_managed": false, "supported_modes": ["risk", "performance_hypothetical", "optimization"] }
  ]
}
```

**`supported_modes` derivation:**
- **Virtual portfolios** (combined/single_account/custom): Derived per-portfolio based on linked account characteristics:
  - If ALL linked accounts are pseudo-accounts (`account_id_external` starts with `_unknown_`): `["risk", "performance_hypothetical", "optimization"]` — same as manual (pseudo-accounts have no transaction history)
  - If ANY linked account is a real account: full mode set `["risk", "performance_hypothetical", "performance_realized", "trading", "income", "optimization"]`
  - Combined portfolio (CURRENT_PORTFOLIO): full mode set if ANY linked account is real (which is the typical case — a user has at least one provider-synced account). If ALL accounts are pseudo (degenerate edge case — user has only legacy/manual data), reduced set.
- **Manual portfolios**: `["risk", "performance_hypothetical", "optimization"]`. No `performance_realized` or `trading` (no transaction history). No `income` (DB position rows lack live market values — income engine requires `value` for yield-on-value).
- The backend explicitly rejects unsupported modes (§2.6b, §2.6c) — `supported_modes` lets the frontend disable them proactively.
- **Single derivation rule:** `list_portfolios()` (MCP) and `GET /api/v2/portfolios` (REST) both call a shared `derive_supported_modes(portfolio_type, linked_accounts)` function that: (a) for `manual` → static set without realized/trading, (b) for `combined`/`single_account`/`custom` → inspect linked accounts for pseudo-account presence (all pseudo → reduced set same as manual, any real → full mode set). This function lives in `services/portfolio_scope.py` alongside the resolver. In practice, combined portfolios almost always have at least one real (non-pseudo) account and thus get the full mode set.
```

### 3.3 Files Changed

| File | Action |
|------|--------|
| `mcp_tools/portfolio_management.py` | **New** — 5 MCP tools |
| `mcp_server.py` | Register new tools |
| `routes/portfolios.py` | **New** — REST endpoints |
| `app.py` | Import + `app.include_router()` for new `routes/portfolios.py` router |

---

## Phase 4: Frontend Portfolio Selector

**Goal:** Dropdown in dashboard header to switch portfolios.

### 4.1 Frontend Changes

Based on PORTFOLIO_SELECTOR_SPEC.md with adaptations:
- `usePortfolioList` hook fetches `GET /api/v2/portfolios` → typed PortfolioInfo[]
- `PortfolioSelector` component shows portfolio type badges (combined/single/custom)
- Switching: load new portfolio by name, set as current, invalidate React Query cache
- `PortfolioInitializer` **rewritten** with a cascade fallback replacing the current behavior (which uses localStorage only for the onboarding-completed flag, picks the first existing store row or fetches `DEFAULT_PORTFOLIO_NAME="CURRENT_PORTFOLIO"`, and traps manual-only users). New cascade: (1) localStorage last-used portfolio (if still in list), (2) first portfolio from `GET /api/v2/portfolios` list (sorted: combined first, then single_account, then custom, then manual), (3) show onboarding/empty state only if the list response has zero portfolios

### 4.2 Key Behavior

When user selects a non-combined portfolio:
1. Frontend loads the portfolio data via API: `const res = await api.getPortfolio(name)`
2. Upserts into store: `const id = PortfolioRepository.add({ ...res.portfolio_data, portfolio_name: name })`
3. Sets as active: `PortfolioRepository.setCurrent(id)`
   **Note:** `setCurrent()` only swaps `currentPortfolioId` in the store — `useCurrentPortfolio()` reads from `byId[currentPortfolioId]`, so the portfolio MUST be added to the store first via `add()`. If `setCurrent()` is called without a prior `add()`, the store returns `null` for the portfolio and some resolvers will throw "No active portfolio is available" while others may silently fall back. Always call `add()` before `setCurrent()`.
4. Invalidates all React Query caches: `queryClient.invalidateQueries()`
5. All data hooks read the current portfolio name and pass it to API calls
6. Backend resolves to account filters → scoped positions
7. Risk, performance, trading analysis all return scoped results

**Frontend `portfolio_name` threading (critical):**
Currently, many frontend API calls and backend REST routes either hardcode `CURRENT_PORTFOLIO` or omit `portfolio_name` entirely. These must all be updated to pass the active portfolio name:

**Implementation approach:** A grep-based audit during Phase 4 implementation identifies the exact call sites. The codebase uses a resolver pattern (`useDataSource` + adapters) between hooks and API calls, so the exact method names differ from the service-level names. The audit steps:

1. **Backend REST routes** — current state and gaps:
   **Already accept `portfolio_name`:** Most `app.py` risk/performance/optimization handlers already accept `portfolio_name` via their request models (e.g., `risk_score_request.portfolio_name`, `performance_request.portfolio_name`, `optimization_request.portfolio_name`). These need no new parameter — only verify they pass it through to `resolve_portfolio_scope()`.
   **Missing `portfolio_name`:**
   - `routes/realized_performance.py` — `POST /api/performance/realized` hardcodes CURRENT_PORTFOLIO
   - `routes/trading.py` — trading analysis endpoint (no portfolio_name param)
   - `routes/income.py` — income projection endpoint (no portfolio_name param)
   - `routes/positions.py` — positions/holdings endpoint (no portfolio_name param)
   - `routes/hedging.py` — hedging analysis (loads positions without scoping)
   - `app.py` `/api/expected-returns` handler — passes `portfolio_name` to `get_expected_returns()` but must use `scope.expected_returns_portfolio_name`
   - `app.py` `/api/risk-settings` handler — uses portfolio_name for risk_limits, must use `scope.config_portfolio_name`

   **Deferred surfaces (known gaps):** `mcp_tools/metric_insights.py`, `mcp_tools/factor_intelligence.py`, `mcp_tools/news_events.py` — these derive data from portfolio positions but may be deferred to a follow-up. If deferred, they show data for all positions regardless of portfolio selection (equivalent to CURRENT_PORTFOLIO behavior).

2. **Frontend service + type layer** — The connector stack uses `portfolioId` as the client-side scoping primitive (maps to `portfolio_name` on the backend). Current state and gaps:
   - `RiskAnalysisService.ts` **already sends** `portfolio_name` for risk/portfolio/performance methods — no changes needed.
   - `frontend/packages/chassis/src/catalog/types.ts` — `SDKSourceParamsMap` entries for `trading-analysis` and `income-projection` already have `portfolioId?: string`. `realized-performance` and `positions-enriched` do NOT — add `portfolioId?: string` to both.
   - `frontend/packages/chassis/src/services/APIService.ts` — `getRealizedPerformance()`, `getTradingAnalysis()`, `getIncomeProjection()`, `getPositionsHoldings()` do NOT currently pass portfolio to the backend. Add `portfolio_name` (mapped from `portfolioId`) to their request params.
   Audit: `grep -n 'portfolioId\|portfolio_name' frontend/packages/chassis/src/` to find existing patterns.

3. **Resolver layer (the primary gap):** `buildDataSourceQueryKey()` already serializes the full params object generically — if `SDKSourceParamsMap` entries include `portfolioId`, query keys incorporate it automatically. The actual missing work is in `registry.ts` resolver dispatch functions:
   - Positions enriched resolver (~line 158): does not pass portfolio to `api.getPositionsHoldings()`
   - Realized performance resolver (~line 298): does not pass portfolio to `api.getRealizedPerformance()`
   - Trading analysis resolver (~line 343): does not pass portfolio to `api.getTradingAnalysis()`
   - Income projection resolver (~line 789): does not pass portfolio to `api.getIncomeProjection()`
   - Each must read `portfolioId` from the resolved params and pass as `portfolio_name` to the API call

4. **Frontend data hooks** — hooks using `useDataSource` inherit query keys from the resolver (automatic invalidation if params include `portfolioId`). The unscoped hooks that need updating:
   - `usePositions.ts` — currently passes no params to `useDataSource('positions-enriched')`; must pass `{ portfolioId }`
   - `useRealizedPerformance.ts`, `useTradingAnalysis.ts`, `useIncomeProjection.ts` — verify they include `portfolioId` in their `useDataSource` params

5. **Validation:** After implementation, grep for any remaining `"CURRENT_PORTFOLIO"` hardcodes in frontend service/hook code — all should be replaced with the dynamic portfolio name from the store.

**Manual portfolio frontend behavior:**
- Manual portfolios appear in the selector but with a badge indicating limited support (e.g., "Static" or "Manual" chip).
- The `PortfolioInfo` type includes `supported_modes: string[]` from the list API (§3.2).
- When a portfolio with reduced `supported_modes` is selected (manual or pseudo-account-only), the frontend uses `supported_modes` to:
  - **Disable** the Realized Performance tab/toggle (show "Not available for this portfolio" tooltip)
  - **Disable** the Trading Analysis view (same tooltip)
  - **Enable** Risk Analysis, Hypothetical Performance, and Optimization (these only need positions, not transaction history)
  - **Disable** Income Projection for manual portfolios (show "No live pricing" tooltip — DB rows lack market values)
- This prevents the user from triggering backend errors. The backend still rejects unsupported modes as a safety net (§2.6b, §2.6c), but the frontend should never send those requests for manual portfolios.

### 4.3 Files Changed

| File | Action |
|------|--------|
| `frontend/packages/chassis/src/services/RiskAnalysisService.ts` | Add `listPortfoliosV2()` method. Existing risk/portfolio/performance methods already send `portfolio_name` — verify they read from the active store, not a hardcoded default. |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `portfolio_name` param to `getRealizedPerformance()`, `getTradingAnalysis()`, `getIncomeProjection()`, `getPositionsHoldings()` (these currently omit it) |
| `frontend/packages/connectors/src/features/portfolio/hooks/usePortfolioList.ts` | **New** — React Query hook for portfolio list |
| `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx` | **New** — dropdown component with type badges + manual portfolio gating |
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | Wire selector into header + switching logic |
| `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx` | Rewrite with cascade fallback (localStorage → list API → onboarding) |
| `frontend/packages/connectors/src/resolver/core.ts` | No changes needed — `buildDataSourceQueryKey()` already serializes the full params object generically. Portfolio name is included automatically if `SDKSourceParamsMap` entries contain it. |
| `frontend/packages/connectors/src/resolver/registry.ts` | Ensure `portfolioId` is forwarded to backend API calls. Currently: `trading-analysis` (~line 340) and `income-projection` (~line 762) already read `portfolioId` from params for internal routing (e.g., `getPortfolio()`), but do NOT forward it to the backend API call (`getTradingAnalysis()`, `getIncomeProjection()`). `positions-enriched` (~line 158) and `realized-performance` (~line 298) do not read `portfolioId` at all. All four must forward `portfolioId` → `portfolio_name` to the backend API. Note: `allocation` uses both `portfolioId` and `portfolioName` as a dual-key pattern — this is an existing convention. |
| `frontend/packages/chassis/src/catalog/types.ts` | Add `portfolioId?: string` to `SDKSourceParamsMap` entries for `positions-enriched` (currently `Record<string, never>`) and `realized-performance` (currently has `benchmarkTicker`, `source`, `institution`, `account`, `startDate`, `endDate`, `includeSeries`, `_runId` — but no `portfolioId`). `trading-analysis` and `income-projection` already have `portfolioId`. |
| `frontend/packages/connectors/src/features/positions/hooks/usePositions.ts` | Pass active `portfolioId` in `useDataSource` params so holdings are scoped |
| `frontend/packages/connectors/src/features/*/hooks/use*.ts` | Add `portfolioId` to `useDataSource` params (audit via grep — resolvers/adapters sit between hooks and services, and `buildDataSourceQueryKey()` already serializes the full params object) |
| `routes/realized_performance.py` | Accept `portfolio_name` param (currently hardcodes CURRENT_PORTFOLIO) |
| `routes/trading.py` | Accept `portfolio_name` param |
| `routes/income.py` | Accept `portfolio_name` param |
| `routes/positions.py` | Accept `portfolio_name` param |
| `app.py` | Verify `portfolio_name` is threaded through to scope resolver in risk/performance/optimization handlers (many already accept it — audit for any that still hardcode CURRENT_PORTFOLIO or omit it) |
| `mcp_tools/metric_insights.py` | Accept `portfolio_name` param (or document as deferred gap) |
| `mcp_tools/factor_intelligence.py` | Accept `portfolio_name` param (or document as deferred gap) |
| `mcp_tools/news_events.py` | Accept `portfolio_name` param (or document as deferred gap) |

---

## Key Design Decisions

### CURRENT_PORTFOLIO stays as physical DB name
The ~60 hardcoded references do NOT need to change. CURRENT_PORTFOLIO IS the combined portfolio. Position saves, webhook updates, cache checks all correctly target it. New behavior only activates when `portfolio_name != "CURRENT_PORTFOLIO"`.

### Virtual vs Physical portfolio storage (dual model)
Two fundamentally different storage models coexist:
- **Virtual** (combined/single_account/custom): Positions live under `CURRENT_PORTFOLIO`. Scoping is done at read time via `portfolio_accounts` → account filter → position filter. No duplicate position storage.
- **Physical** (manual): Positions stored directly under portfolio_id via `save_portfolio()`. Read via existing SQL JOIN in `load_full_portfolio()`. No `portfolio_accounts` linkage.
The shared `resolve_portfolio_scope()` function (§2.5) routes to the correct strategy for both MCP and REST API callers.

### institution_key is always populated (NOT nullable)
`accounts.institution_key` is always set via `normalize_institution_slug()`, which either returns a known slug from `INSTITUTION_SLUG_ALIASES` or falls back to a sanitized version of the brokerage display name. This eliminates the COALESCE fragility of the previous design — the unique index is simply `(user_id, institution_key, account_id_external)`.

### Cross-provider account dedup deferred
Each provider-account combo gets a separate `accounts` row. `partition_positions()` prevents duplicate positions per institution **only for institutions in `POSITION_ROUTING`** (currently Schwab and IBKR). Unrouted institutions (Fidelity, Vanguard, etc.) can still be double-counted if connected via both Plaid and SnapTrade. This is a pre-existing limitation unrelated to this spec. Mitigation: either expand `POSITION_ROUTING` for commonly multi-connected institutions, or implement cross-provider account matching. Both are deferred to follow-up work. True cross-provider account matching (Plaid account = SnapTrade account for same institution) is a later enhancement.

### Config inheritance (shared config + expected returns)
Shared config (factor_proxies, risk_limits, target_allocations): ALL portfolios inherit from CURRENT_PORTFOLIO. Avoids `RiskLimitsManager` auto-creating phantom default rows.
Expected returns: Virtual portfolios use CURRENT_PORTFOLIO (superset of tickers). Manual portfolios use their own physical portfolio name (may have unique tickers not in CURRENT_PORTFOLIO). `PortfolioScope.expected_returns_portfolio_name` encodes this.
Per-portfolio config customization for shared config is future work.

### Fetch all → filter (not per-account fetching)
Position loading fetches all positions (cached), then filters by account in memory. Simpler, preserves provider caching, O(n) filter. No-DB + CURRENT_PORTFOLIO returns all positions (existing behavior). No-DB + non-CURRENT_PORTFOLIO errors.

### Transaction store scoping: direct method calls, post-filter
`load_from_store()` wraps income events in `StoreBackedIncomeProvider` (NormalizedIncome objects, not raw dicts) — this makes post-filtering impractical via the convenience function. Design: `load_from_store_for_portfolio()` opens ONE DB connection and calls individual `TransactionStore` methods directly (`load_fifo_transactions`, `load_income_events`, etc.) to get raw lists, post-filters each by `(institution_key, account_id)`, then wraps filtered income events in a new `StoreBackedIncomeProvider`. Key detail: FIFO dicts use `_institution` (underscore prefix, line 1008), not `institution`. The `source` param passes through for provider filtering. `flex_option_price_rows` (IBKR option pricing) passes through unfiltered. `fetch_metadata` IS filtered — it contains per-account `account_id`/`institution` fields used by the realized engine for flow authority and statement-cash anchors.

### data_sources populated going forward, not backfilled
`provider_items` is unreliable as a source (SnapTrade stores user hash). `data_sources` populated during future syncs via `ensure_data_source()`. Backfilled `accounts` rows have `data_source_id=NULL` — this is expected and tolerated.

### NULL account_id handling
Existing positions with NULL `account_id` (manual imports, legacy data) are grouped into pseudo-accounts per `(user_id, institution_key, position_source)` with `account_id_external='_unknown_{position_source}'` during backfill. The source-qualified external ID avoids unique index collisions when the same institution has NULL account_id rows from two providers. Grouping by institution prevents collapsing distinct institutions into one pseudo-account.

### DB unavailable behavior
- **REST API requires DB**: `app.py` hard-exits (`sys.exit(1)`) when `DATABASE_URL` is unset (line 269). Portfolio scoping is irrelevant for REST without DB — the server never starts. This is existing behavior and unchanged by this spec.
- **MCP without DB + CURRENT_PORTFOLIO**: Works. `PositionService` fetches from providers directly (not SQL). `resolve_portfolio_scope()` short-circuits: `portfolio_name == "CURRENT_PORTFOLIO"` → `VIRTUAL_ALL` without any DB query (rule 1 in §2.5). Config loading falls back to YAML via `PortfolioManager._should_fallback_to_file()`.
- **MCP without DB + non-CURRENT_PORTFOLIO**: `resolve_portfolio_scope()` checks `is_db_available()` → false → raises `PortfolioNotFoundError(user_id, portfolio_name)` (constructor signature: `(user_id, portfolio_name, original_error=None)`). This short-circuits before any downstream code runs.
- **Enforcement**: The resolver is called first in all MCP entry points (§2.6a-d). The CURRENT_PORTFOLIO fast path (rule 1) never touches the DB. All other portfolio names require DB to determine type and linked accounts.

### Auto-managed portfolio guards + reserved names
- `auto_managed=true` portfolios (combined + single_account) cannot be deleted or renamed
- Auto-generated names use `_auto_` prefix: `_auto_{institution_key}_{sanitized_account_name}`
- Collision resolution: if name exists, append `__{account_id_external[-6:]}` suffix. Blank account_name uses `__{account_id_external[-8:]}`.
- User-created portfolios cannot use `_auto_*`, `_system_*` prefixes, or `CURRENT_PORTFOLIO` as name
- `list_portfolios` response always includes `portfolio_type`, `auto_managed`, and `supported_modes` fields
- `supported_modes` derived by `derive_supported_modes(portfolio_type, linked_accounts)` in `services/portfolio_scope.py`:
  - `manual` → `["risk", "performance_hypothetical", "optimization"]` (no transaction history)
  - `combined`/`single_account`/`custom` with ANY real (non-pseudo) account → full mode set
  - `combined`/`single_account`/`custom` with ALL pseudo accounts → same as manual (no transaction history)
- Frontend uses `supported_modes` to disable unsupported views proactively

---

## Verification

### Phase 1
```bash
# IMPORTANT: Do NOT use scripts/run_migrations.py if 20260313 already exists in the migrations dir.
# The all-files runner would hit the Phase 2 guard and fail.
# Option A: Apply Phase 1 migration BEFORE adding 20260313 to the migrations dir.
# Option B: Apply targeted:
#   psql -f database/migrations/20260312b_accounts_data_sources.sql
#   Then record it: psql -c "INSERT INTO _migrations (filename) VALUES ('20260312b_accounts_data_sources.sql') ON CONFLICT DO NOTHING"
#   Without this, run_migrations.py will re-apply Phase 1 on next run (SQL is idempotent via
#   IF NOT EXISTS / ON CONFLICT DO NOTHING, but recording avoids the redundant execution).
python scripts/fixup_account_slugs.py  # MANDATORY before Phase 2 — resolves canonical slugs
# Verify: accounts table populated from existing positions
# Verify: no changes to portfolios table
# Verify: ALL existing tools work unchanged
pytest tests/ -x  # All existing tests pass
```

### Phase 2
```bash
# Deployment order:
# 1. fixup_account_slugs.py must have run (writes sentinel row)
# 2. Apply 20260313_portfolio_accounts.sql (has guard check for sentinel)
# 3. Run link_portfolio_accounts.py (needs portfolio_accounts table from step 2)
# Verify: CURRENT_PORTFOLIO marked as combined, linked to all sync-backed accounts
# Verify: single_account portfolios created per account
# Via MCP: get_risk_analysis(portfolio_name="_auto_schwab_rollover_ira") → only Schwab IRA positions
# Via MCP: get_risk_analysis(portfolio_name="CURRENT_PORTFOLIO") → all positions (no regression)
# Via MCP: get_performance(portfolio_name="_auto_schwab_rollover_ira") → scoped realized performance
# Verify: cannot delete auto_managed portfolios
pytest tests/ -x
```

### Phase 3
```bash
# Via MCP: list_accounts() → shows discovered accounts by institution
# Via MCP: list_portfolios(include_accounts=True) → all portfolios with linked accounts
# Via MCP: create_portfolio(name="growth", account_ids=[1,3]) → custom portfolio
# Via MCP: get_risk_analysis(portfolio_name="growth") → scoped to accounts 1,3
# Via MCP: delete_portfolio(portfolio_name="growth") → success
# Via MCP: delete_portfolio(portfolio_name="CURRENT_PORTFOLIO") → rejected (auto_managed)
```

### Phase 4
```bash
cd frontend && npx tsc --noEmit
# Visual: portfolio selector in header, switching reloads all data
# Visual: single-account portfolios show institution + account name
# Visual: combined portfolio shows "All Accounts"
# Visual: refresh page → same portfolio selected (localStorage)
# Visual: manual portfolio selected → realized perf tab disabled with tooltip
# Visual: manual portfolio selected → trading analysis view disabled with tooltip
# Visual: manual portfolio selected → risk analysis + hypothetical perf work normally
```

## Implementation Order

Phase 1 → Phase 2 → Phase 3 → Phase 4. Each phase is independently shippable.

- **Phase 1** is invisible to users (just populates new tables, no behavior change)
- **Phase 2** enables scoped analysis via `portfolio_name` parameter on existing MCP tools
- **Phase 3** adds management tools for listing/creating portfolios
- **Phase 4** adds the frontend selector UI
