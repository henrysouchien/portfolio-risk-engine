# Earnings Estimate Revision Tracking

## Context

FMP's `analyst_estimates` endpoint only returns the **current** consensus — no revision history. Estimate revisions are one of the strongest signals in equity research, and right now we're blind to them.

**Solution:** Build an automated monthly job that snapshots consensus estimates for the full FMP universe into a dedicated Postgres database (`fmp_data_db`). MCP tools and direct Python imports query the accumulated data for revision tracking and screening.

## Architecture

```
EstimateStore (fmp/estimate_store.py)       ← core API, works anywhere
    ├── MCP tools (mcp_tools/estimates.py)      ← Claude-facing query wrappers
    ├── Collection script (fmp/scripts/)         ← monthly cron job
    └── Notebooks, scripts, CLI, etc.            ← direct import
```

This is an **FMP-domain concern** — no dependency on risk_module Postgres, portfolio logic, or user context. Estimates are market data shared across all consumers. If `fmp-mcp` is extracted as a standalone package (per release plan), this comes with it.

---

## 1. Storage: Postgres (`fmp_data_db`)

**Connection:** `FMP_DATA_DATABASE_URL` (default: `postgresql://postgres@localhost:5432/fmp_data_db`)

**Postgres configuration:**
- Separate database from `risk_module_db` (`fmp_data_db`)
- Writer uses a dedicated connection with explicit transactions
- MCP readers use a small `psycopg2.pool.SimpleConnectionPool` with read-only sessions
- Session timezone is set to UTC for consistent date handling

### Tables

#### `estimate_snapshots` — one row per ticker + fiscal period + snapshot date

```sql
CREATE TABLE estimate_snapshots (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES snapshot_runs(id),
    ticker TEXT NOT NULL,
    fiscal_date DATE NOT NULL,             -- period being estimated (e.g. '2026-06-28')
    period TEXT NOT NULL CHECK (period IN ('annual', 'quarter')),
    snapshot_date DATE NOT NULL,           -- capture date (UTC)

    -- EPS
    eps_avg REAL,
    eps_high REAL,
    eps_low REAL,
    num_analysts_eps INTEGER,

    -- Revenue
    revenue_avg REAL,
    revenue_high REAL,
    revenue_low REAL,
    num_analysts_revenue INTEGER,

    -- EBITDA
    ebitda_avg REAL,
    ebitda_high REAL,
    ebitda_low REAL,

    -- Net Income
    net_income_avg REAL,
    net_income_high REAL,
    net_income_low REAL,

    -- Overflow for EBIT, SGA, etc. — promote to columns later if needed
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(ticker, fiscal_date, period, snapshot_date)
);

-- Primary query pattern: get latest estimates for a ticker by period
CREATE INDEX idx_est_ticker_period_snap ON estimate_snapshots(ticker, period, snapshot_date DESC);
-- Revision history: all snapshots for a ticker + fiscal period
CREATE INDEX idx_est_ticker_fiscal ON estimate_snapshots(ticker, fiscal_date);
-- Run-level queries
CREATE INDEX idx_est_run_id ON estimate_snapshots(run_id);
-- Screening: filter by snapshot date across all tickers
CREATE INDEX idx_est_snapshot_date ON estimate_snapshots(snapshot_date);
```

#### `snapshot_runs` — one row per collection run (audit trail)

```sql
CREATE TABLE snapshot_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'partial')),
    tickers_attempted INTEGER DEFAULT 0,
    tickers_succeeded INTEGER DEFAULT 0,
    tickers_failed INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    last_ticker_processed TEXT,               -- cursor for resume
    error_message TEXT,
    universe_snapshot JSONB,                   -- JSON array of tickers targeted this run
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Design decisions:**
- **Insert-only** — no updates or deletes on `estimate_snapshots`. Each snapshot is immutable.
- **UNIQUE constraint** on `(ticker, fiscal_date, period, snapshot_date)` — snapshotting the same ticker twice on the same day is a no-op (`ON CONFLICT DO NOTHING`).
- **No `user_id`** — estimates are market data, not user-specific.
- **All numeric estimate fields are `REAL`** — avoids truncation of decimal values from FMP.
- **`raw_data` JSONB** — JSON blob for fields we don't promote to columns yet (EBIT, SGA). Avoids schema churn.
- **`snapshot_runs` table** — tracks run metadata for observability and enables resume after partial failures.
- **`run_id` FK** on snapshots — ties each row to the run that produced it, enabling per-run auditing.

---

## 2. Storage Layer: `fmp/estimate_store.py`

`EstimateStore` class — owns Postgres connections and all read/write operations. This is the core API that everything else consumes.

```python
class EstimateStore:
    def __init__(self, database_url: str | None = None, read_only: bool = False):
        """Connects to FMP Postgres data store.
        Uses writer connection or read-only reader pool based on mode."""

    # --- Write operations (used by collection script) ---

    def create_run(self, universe: List[str]) -> int:
        """Create a snapshot_runs row. Returns run_id."""

    def update_run(self, run_id: int, **kwargs) -> None:
        """Update run status, counts, last_ticker_processed, etc."""

    def save_snapshots(self, run_id: int, ticker: str, estimates: List[Dict],
                       period: str = "quarter") -> int:
        """Insert snapshot rows from FMP API response. Returns count inserted (skips dupes)."""

    def get_resumable_run(self) -> Optional[Dict]:
        """Find most recent run with status='running' or 'partial'. Returns run metadata
        including last_ticker_processed for cursor-based resume."""

    # --- Read operations (used by MCP tools, notebooks, etc.) ---

    def get_latest(self, ticker: str, period: str = "quarter") -> List[Dict]:
        """Most recent snapshot for each fiscal_date for a ticker."""

    def get_revisions(self, ticker: str, fiscal_date: str, period: str = "quarter") -> List[Dict]:
        """All snapshots for a specific ticker + fiscal period, ordered by snapshot_date."""

    def get_revision_summary(self, tickers: List[str], days: int = 30,
                             period: str = "quarter") -> List[Dict]:
        """Compare latest vs N-days-ago estimates. Returns per-ticker eps_delta,
        revenue_delta, direction."""

    def get_freshness(self, tickers: List[str]) -> Dict[str, Optional[str]]:
        """Return {ticker: latest_snapshot_date} for staleness checking."""
```

---

## 3. Automated Collection: `fmp/scripts/snapshot_estimates.py`

Standalone Python script run via **macOS launchd** (or crontab) on a **monthly** schedule.

### Flow
1. **Check for resumable run** — `EstimateStore.get_resumable_run()`. If a prior run was interrupted, resume from `last_ticker_processed` cursor.
2. **Get ticker universe** — use FMP `company_screener` or `stock_list` endpoint to enumerate all tickers with analyst coverage (~3-4K). Store as `universe_snapshot` JSON in the run row.
3. **Create run** (or resume existing) — `EstimateStore.create_run(universe)`
4. **Iterate tickers** (alphabetically for deterministic cursor):
   - Fetch `analyst_estimates` (quarterly) from FMP
   - `EstimateStore.save_snapshots()` per ticker
   - Update `last_ticker_processed` + counts on the run row
   - **Rate-limit** — throttle between API calls (e.g. 100ms delay)
   - **Retry with backoff** on transient errors (HTTP 429, timeouts) — 3 attempts per ticker, then log failure and continue
5. **Finalize run** — set status to `completed` (or `partial` if any tickers failed), log summary

### Freshness Logic
- Freshness is **elapsed-days based** (default: 28 days), not calendar-month gating
- Skip tickers whose latest `snapshot_date` is within the freshness window
- Support `--force` flag to bypass freshness and re-snapshot everything

### Ticker Universe
All tickers in FMP with analyst estimates. No portfolio dependency — this is a market-wide data collection. The universe is snapshotted per run so historical coverage is reproducible.

### Schedule
Monthly via launchd plist or crontab. Example cron: `0 2 1 * * /path/to/python /path/to/snapshot_estimates.py`

### Storage Growth
~4K tickers × 4 forward quarters × 12 months = **~192K rows/year**. Small for Postgres.

---

## 4. MCP Query Tools

Two read-only tools in `mcp_tools/estimates.py` (collection is automated — no snapshot MCP tool):

| Tool | Purpose | Key Params |
|------|---------|------------|
| `get_estimate_revisions` | Revision history for a single ticker | `ticker`, `fiscal_date` (optional — defaults to next quarter) |
| `screen_estimate_revisions` | Screen across tickers for estimate momentum | `tickers` (optional), `days` (lookback, default 30), `direction` (up/down/all) |

These are thin wrappers around `EstimateStore` methods — all logic lives in the store. MCP connections use Postgres read-only sessions.

---

## 5. Implementation Order

1. **`fmp/estimate_store.py`** — Postgres connection + schema bootstrap + `EstimateStore` class (write + read methods)
2. **`fmp/scripts/snapshot_estimates.py`** — automated collection script with resume/retry
3. **`mcp_tools/estimates.py`** — 2 MCP query tools calling `EstimateStore`
4. **Register tools** in MCP server
5. **Launchd plist** or crontab entry for monthly schedule
6. **Test:** run script manually for a subset of tickers, query revisions via MCP tools

## Files
- `fmp/estimate_store.py` — Postgres-backed storage layer
- `fmp/scripts/create_fmp_data_schema.sql` — Postgres schema bootstrap
- `fmp/scripts/snapshot_estimates.py` — collection script
- `fmp/scripts/migrate_estimate_store_sqlite_to_postgres.py` — one-time data migration utility
- `mcp_tools/estimates.py` — MCP query tools
