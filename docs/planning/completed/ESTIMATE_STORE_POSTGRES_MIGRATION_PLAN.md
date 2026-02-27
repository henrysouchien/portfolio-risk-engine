# Convert EstimateStore from SQLite to Postgres

## Context

The estimate revision tracking system currently uses SQLite (`.cache/fmp/estimates.db`). We want to serve this data to other users in the future via a hosted database. Converting to Postgres now avoids a data migration later. The database should be **separate** from `risk_module_db` — a new `fmp_data_db` database on the same local Postgres instance, pointing at RDS when we go to AWS.

## Changes

### 1. Create the `fmp_data_db` database

```bash
createdb fmp_data_db
```

### 2. Schema file: `fmp/scripts/create_fmp_data_schema.sql`

New file with the Postgres version of the schema.

**SQLite → Postgres translations:**
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`
- `TEXT` dates → `DATE` for `fiscal_date`, `snapshot_date`; `TIMESTAMPTZ` for `created_at`, `started_at`, `completed_at`
- `datetime('now')` → `NOW()`
- No `PRAGMA` statements
- `JSONB` for `raw_data` and `universe_snapshot` instead of `TEXT`
- `julianday(a) - julianday(b)` → `ABS(a - b)` (date subtraction returns integer days natively in Postgres)

**Indexes (explicitly defined for primary query patterns):**
- `(ticker, period, snapshot_date DESC)` — `get_latest`, screening
- `(ticker, fiscal_date)` — `get_revisions`
- `(run_id)` — run-level queries
- `(snapshot_date)` — freshness checks

**Constraints:**
- `UNIQUE(ticker, fiscal_date, period, snapshot_date)` — dedup
- `CHECK (period IN ('annual', 'quarter'))` — enforce valid periods
- `CHECK (status IN ('running', 'completed', 'failed', 'partial'))` — enforce valid run statuses

### 3. Rewrite `fmp/estimate_store.py`

Replace `sqlite3` with `psycopg2`. Key changes:

- **Connection:** Use `psycopg2.connect()` with `FMP_DATA_DATABASE_URL` env var (default: `postgresql://postgres@localhost:5432/fmp_data_db`)
- **Connection management:**
  - **Writer (cron script):** Single dedicated connection with explicit transactions (no autocommit). Wrapped in context manager.
  - **Reader (MCP tools):** Small connection pool (`psycopg2.pool.SimpleConnectionPool`, min=1, max=3) separate from the `risk_module_db` pool. Connections opened with `RealDictCursor`. Use `autocommit=True` on reader connections to avoid idle-in-transaction state on pooled connections (psycopg2 starts a transaction even for SELECT by default).
- **Remove** all SQLite-specific code: `PRAGMA`, `WAL`, `busy_timeout`, `user_version`, `check_same_thread`, URI-based read-only, `executescript`
- **read_only mode:** Separate Postgres user with read-only grants (preferred), with `SET default_transaction_read_only = true` as fallback
- **Parameterized queries:** Change `?` placeholders to `%s`
- **Row factory:** Use `psycopg2.extras.RealDictCursor` instead of `sqlite3.Row`
- **`create_run`:** Replace `cur.lastrowid` with `INSERT ... RETURNING id` (SQLite's `lastrowid` does not exist in psycopg2)
- **`_format_snapshot_row`:** Postgres `JSONB` returns dicts natively, but `DATE`/`TIMESTAMPTZ` columns return Python `date`/`datetime` objects. Add explicit `.isoformat()` serialization so MCP JSON responses remain backward-compatible strings.
- **`save_snapshots`:** Change `INSERT OR IGNORE` to `INSERT ... ON CONFLICT (ticker, fiscal_date, period, snapshot_date) DO NOTHING`, use `cur.rowcount`
- **`get_revision_summary`:** Replace `julianday(a) - julianday(b)` with `ABS(s.fiscal_date - CURRENT_DATE)` (Postgres date subtraction returns integer days). Replace `date('now')` with `CURRENT_DATE`. Compute cutoff dates in Python and pass as parameters (avoids timezone mismatches between Python UTC and DB `CURRENT_DATE` around midnight).
- **Timezone consistency:** Set session timezone to UTC (`SET timezone = 'UTC'`) on connection initialization, and compute `snapshot_date` and `cutoff_date` in Python (UTC) rather than relying on DB-side `CURRENT_DATE` to prevent off-by-one day issues.
- **`_chunks` for `IN` queries:** Replace `?,?,?` with `%s,%s,%s`
- **Schema creation:** Move to separate SQL file (`fmp/scripts/create_fmp_data_schema.sql`). Run manually or via `_ensure_schema` on first use.

### 4. Update `fmp/scripts/snapshot_estimates.py`

- Remove `--cache-dir` argument (no longer relevant — connection string replaces it)
- Add `--database-url` argument (optional, defaults to `FMP_DATA_DATABASE_URL` env var)
- Update `EstimateStore()` instantiation to pass `database_url`

### 5. Update `mcp_tools/estimates.py`

- Update `EstimateStore()` instantiation (remove `cache_dir`, use `read_only=True` which opens from the reader pool)

### 6. Update tests

- **`tests/fmp/test_estimate_store.py`** — Convert to real Postgres integration tests using an ephemeral test database (`fmp_data_test_db`). Create DB in fixture, run schema, test, drop. Do NOT mock psycopg2 — we need to validate SQL semantics (`ON CONFLICT`, date arithmetic, transaction behavior).
- **`tests/fmp/test_snapshot_estimates_script.py`** — Minimal changes (mostly pure-function tests for `_parse_tickers`, `_is_fresh`, `_is_transient_error`, `_extract_universe`)
- **`tests/mcp_tools/test_estimates.py`** — Keep mocked (tests response-shape logic, not DB queries). Update EstimateStore mock if constructor signature changes.

### 7. Migrate existing data

Migration script or manual steps. **Order matters due to FK constraints:**

1. Migrate `snapshot_runs` first — preserve original IDs
2. Migrate `estimate_snapshots` — FK references `snapshot_runs(id)`
3. Reset sequences after data load:
   ```sql
   SELECT setval('snapshot_runs_id_seq',
     COALESCE((SELECT MAX(id) FROM snapshot_runs), 1),
     (SELECT MAX(id) IS NOT NULL FROM snapshot_runs));
   SELECT setval('estimate_snapshots_id_seq',
     COALESCE((SELECT MAX(id) FROM estimate_snapshots), 1),
     (SELECT MAX(id) IS NOT NULL FROM estimate_snapshots));
   ```
   The third argument (`is_called`) is `false` when tables are empty, so `nextval()` returns 1 instead of 2.

Approach: Python script that reads SQLite, transforms rows, bulk-inserts into Postgres via `psycopg2.extras.execute_values()`. Wrap dict/list values with `psycopg2.extras.Json()` for JSONB columns to avoid adapter errors.

### 8. Update documentation

- **`fmp/README.md`** — Update "Estimate Revision Tracking" section: change `.cache/fmp/estimates.db` references to `fmp_data_db` Postgres, update storage description
- **`docs/planning/ESTIMATE_REVISION_TRACKING_PLAN.md`** — Update storage section to reflect Postgres
- **`.env.example`** — Add `FMP_DATA_DATABASE_URL=postgresql://postgres@localhost:5432/fmp_data_db`
- **`fmp/scripts/snapshot_estimates.py`** — Update `--help` text and comments referencing SQLite/cache-dir

## Config

- **Env var:** `FMP_DATA_DATABASE_URL` (default: `postgresql://postgres@localhost:5432/fmp_data_db`)
- Separate from `DATABASE_URL` which points to `risk_module_db`
- When moving to AWS, just change this to point at RDS
- Optional: separate Postgres user for read-only MCP access

## Files
- `fmp/estimate_store.py` — rewrite (SQLite → Postgres)
- `fmp/scripts/create_fmp_data_schema.sql` — new (Postgres schema)
- `fmp/scripts/snapshot_estimates.py` — minor updates (connection args)
- `mcp_tools/estimates.py` — minor updates (EstimateStore init)
- `tests/fmp/test_estimate_store.py` — rewrite for Postgres integration tests
- `tests/fmp/test_snapshot_estimates_script.py` — minimal changes
- `tests/mcp_tools/test_estimates.py` — update mocks if needed
- `fmp/README.md` — update estimate store docs
- `.env.example` — add `FMP_DATA_DATABASE_URL`

## Verification
1. `createdb fmp_data_db && psql fmp_data_db < fmp/scripts/create_fmp_data_schema.sql`
2. Run tests: `python3 -m pytest tests/fmp/ tests/mcp_tools/test_estimates.py -v`
3. Migrate existing data from SQLite (run migration script, verify row counts + FK integrity + sequences)
4. Run snapshot script: `python3 fmp/scripts/snapshot_estimates.py --tickers AAPL,SFM --force`
5. Query via MCP: `get_estimate_revisions(ticker="SFM")`
6. Verify MCP JSON responses return string dates (not Python date objects)
