# Plan: Migrate Earnings Estimate System to AWS

## Context

The earnings estimate system (monthly FMP snapshot collection + PostgreSQL storage + MCP query tools) runs entirely on the local machine. This creates fragility (local Postgres must be running, launchd must fire, machine must be on) and limits access. The edgar_updater repo already has an EC2 instance (3.136.23.202, us-east-2) running Flask + FastAPI + Nginx. We'll add an RDS database, deploy the collection job and a thin API layer to that EC2, and update the local MCP tools to query via HTTP instead of direct Postgres.

## Architecture

```
Before:  Local launchd → snapshot_estimates.py → local Postgres ← EstimateStore ← MCP tools
After:   EC2 systemd timer → collector.py → RDS Postgres ← API routes ← HTTP ← MCP tools
```

## Steps

### Step 1: RDS Setup (Manual, AWS Console/CLI)

- Create RDS PostgreSQL 15+ instance:
  - Class: `db.t4g.micro` (free tier eligible)
  - Storage: 20 GB gp3
  - VPC: same as EC2 (us-east-2 default)
  - Security group: inbound 5432 from EC2 security group only, no public access
  - DB name: `fmp_data_db`, master user: `estimateadmin`
- Verify connectivity from EC2: `psql postgresql://estimateadmin:<pw>@<rds-endpoint>:5432/fmp_data_db`
- Apply schema: `psql <connection> < schema.sql`
- Add env vars to EC2 (`.env` or systemd `EnvironmentFile`):
  - `FMP_DATA_DATABASE_URL=postgresql://estimateadmin:<pw>@<rds-endpoint>:5432/fmp_data_db`
  - `FMP_API_KEY=<fmp-key>`

### Step 2: Create `estimates/` Package in Edgar_updater Repo

Copy needed files from risk_module into a new `estimates/` package in edgar_updater. This is a copy, not a shared package — edgar_updater has its own deploy pipeline (zip + SCP) and cross-repo dependencies would break it.

**Source repo absolute path:** `~/Documents/Jupyter/risk_module/`

| File | Source (absolute path) | Notes |
|------|------------------------|-------|
| `estimates/__init__.py` | New | Empty |
| `estimates/store.py` | `~/Documents/Jupyter/risk_module/fmp/estimate_store.py` | Self-contained (psycopg2 only) |
| `estimates/scripts/create_fmp_data_schema.sql` | `~/Documents/Jupyter/risk_module/fmp/scripts/create_fmp_data_schema.sql` | Idempotent DDL — must be at `scripts/` relative to `store.py` (see `_SCHEMA_PATH` in `estimate_store.py:19`) |
| `estimates/collector.py` | Adapted from `~/Documents/Jupyter/risk_module/fmp/scripts/snapshot_estimates.py` | Replace `FMPClient` with direct `requests` (see below) |

**Collector adaptation — replace FMPClient with direct requests:**

```python
import csv
import io

_FMP_BASE_STABLE = "https://financialmodelingprep.com/stable"
_FMP_BASE_V4 = "https://financialmodelingprep.com/api/v4"

def _fmp_fetch(path: str, response_type: str = "json", **params) -> list[dict]:
    """Fetch from FMP API. Handles both JSON and CSV response types."""
    params["apikey"] = os.getenv("FMP_API_KEY")
    base = _FMP_BASE_V4 if path.startswith("/v4/") else _FMP_BASE_STABLE
    url = f"{base}{path.replace('/v4/', '/')}" if path.startswith("/v4/") else f"{base}{path}"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    if response_type == "csv":
        text = resp.text or ""
        if not text.strip():
            return []
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]
    data = resp.json()
    return data if isinstance(data, list) else [data] if isinstance(data, dict) else []
```

FMP endpoint mapping (uses `stable` base URL, matching current FMPClient behavior, except v4 endpoints):
- `"company_screener"` → `stable/stock-screener` (JSON)
- `"earnings_surprises_bulk"` → `api/v4/earnings-surprises-bulk?year={year}` (**CSV** — must use `response_type="csv"`)
- `"income_statement"` → `stable/income-statement/{symbol}?period=quarter&limit=1` (JSON)
- `"analyst_estimates"` → `stable/analyst-estimates/{symbol}?period={period}&limit=12` (JSON)

**Important:** The `earnings_surprises_bulk` endpoint returns CSV, not JSON. The current `FMPClient` handles this via the registry's `response_type="csv"` flag (see `fmp/registry.py:575`). The collector must replicate this CSV parsing.

Replace `FMPRateLimitError`/`FMPAPIError` checks with HTTP status code checks (429, 5xx).

### Step 3: API Layer — Add Estimate Routes to edgar_api

Create `edgar_api/routes/estimates.py` with 6 endpoints following existing patterns (auth via `require_api_key`, rate limiting via `limiter`).

| Endpoint | Params | Maps to |
|----------|--------|---------|
| Endpoint | Params | Maps to | Response Shape |
|----------|--------|---------|----------------|
| `GET /estimates/latest` | `ticker`, `period` | `EstimateStore.get_latest()` | `list[dict]` — each dict is a snapshot row with `ticker`, `fiscal_date`, `snapshot_date`, `estimated_eps`, `estimated_revenue`, etc. |
| `GET /estimates/revisions` | `ticker`, `fiscal_date`, `period` | `EstimateStore.get_revisions()` | `list[dict]` — same shape as `/latest`, ordered by `snapshot_date` ascending |
| `GET /estimates/revision-summary` | `tickers` (comma-sep), `days`, `period` | `EstimateStore.get_revision_summary()` | `list[dict]` — each dict has `ticker`, `fiscal_date`, `latest`, `baseline`, `eps_delta`, `revenue_delta`, `direction` |
| `GET /estimates/freshness` | `tickers` (comma-sep), `period` | `EstimateStore.get_freshness()` | `dict[str, str|null]` — map of `{ticker: latest_snapshot_date_iso}` |
| `GET /estimates/failures` | `min_runs` | `EstimateStore.get_failure_summary()` | `list[dict]` — each dict has `ticker`, `period`, `error_type`, `failure_count`, `last_failure` |
| `GET /estimates/tickers` | (none) | `EstimateStore.list_tickers()` | `list[str]` — plain list of ticker strings |

**Note on response wrapping:** All endpoints return the raw store output as JSON. No additional envelope (`{data: ...}`) is needed — the MCP tools consume the raw shapes directly. The `_api_get` helper in Step 5 must handle the varying return types: `list[dict]`, `dict[str, ...]`, and `list[str]`.

**Connection management:** `EstimateStore(read_only=True)` uses a `SimpleConnectionPool(1, 3)` internally, but grabs a single connection at init and reuses it. This is NOT safe for concurrent `run_in_executor` calls from multiple async requests. Two options:

- **Option A (preferred):** Create a new `EstimateStore` per request (lightweight — pool is class-level, shared across instances). Each request gets its own connection from the pool.
- **Option B:** Add a threading lock around store method calls in the route handlers.

Use Option A: instantiate `EstimateStore(read_only=True)` in a dependency function, use it for the request, close at end.

```python
def get_store() -> EstimateStore:
    store = EstimateStore(read_only=True)
    if not store._available:
        raise HTTPException(503, "Estimate database unavailable")
    return store
```

**Startup validation:** On app startup, verify `FMP_DATA_DATABASE_URL` is set and the store can connect. If missing or unreachable, log an explicit error and disable the estimates router (return 503 on all endpoints). Do NOT silently return empty results — `EstimateStore` swallows `OperationalError` in read-only mode and sets `_available=False`, so check this flag explicitly.

**Validation → HTTP error mapping:** `EstimateStore._clean_period()` raises `ValueError` for invalid period values, and `get_failure_summary()` raises `ValueError` if `min_runs < 1`. Wrap store calls with `try/except ValueError` → `HTTPException(400, str(e))` to avoid 500s on bad input.

Register in `edgar_api/routes/__init__.py`:
```python
from .estimates import router as estimates_router
api_router.include_router(estimates_router)
```

**Service env wiring:** The existing `edgar_api.service` does NOT load `.env` — it only sets `PATH`. Add `EnvironmentFile=/var/www/edgar_updater/.env` to the `[Service]` section of `edgar_api.service` (same as the collector service). This makes `FMP_DATA_DATABASE_URL` available to the API process. Alternatively, add it as an explicit `Environment=` line in the service file.

Add `psycopg2-binary` to `requirements.txt`.

### Step 4: Collection Job Scheduling

`estimate_collector.service`:
```ini
[Unit]
Description=Monthly FMP Estimate Snapshot Collection
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/edgar_updater
EnvironmentFile=/var/www/edgar_updater/.env
Environment="PATH=/var/www/edgar_updater/venv/bin"
ExecStart=/var/www/edgar_updater/venv/bin/python -m estimates.collector --period both
Type=oneshot
```

`estimate_collector.timer`:
```ini
[Unit]
Description=Monthly FMP Estimate Snapshot Timer

[Timer]
OnCalendar=*-*-01 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### Step 5: Update MCP Tools (risk_module + fmp-mcp package)

Two copies of the estimate tools need the same update:
1. **`risk_module/fmp/tools/estimates.py`** — local dev copy
2. **`fmp-mcp/fmp/tools/estimates.py`** — published PyPI package (`~/Documents/Jupyter/fmp-mcp/`)

Both currently call `EstimateStore` (psycopg2 → local Postgres). Update both to call the HTTP API when `ESTIMATE_API_URL` is set.

```python
_ESTIMATE_API_URL = os.getenv("ESTIMATE_API_URL")  # e.g. "https://financialmodelupdater.com"
_ESTIMATE_API_KEY = os.getenv("EDGAR_API_KEY")

def _api_get(path: str, params: dict) -> list | dict:
    """Fetch from the estimates API. Returns the raw JSON — may be list[dict], dict, or list[str]."""
    if _ESTIMATE_API_KEY:
        params["key"] = _ESTIMATE_API_KEY
    resp = requests.get(f"{_ESTIMATE_API_URL}{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()
```

Changes per tool:
- `get_estimate_revisions`: replace `store.get_latest()` / `store.get_revisions()` with `_api_get()`. Keep `_select_default_fiscal_date()` and delta computation local.
- `screen_estimate_revisions`: replace `store.get_revision_summary()` with `_api_get()`. Keep direction filtering and sorting local.

**Transition**: when `ESTIMATE_API_URL` is unset, fall back to local EstimateStore. Remove fallback after verification.

**fmp-mcp package note**: The fmp-mcp package is positioned as an FMP data accessor. The estimate revision tools are a value-add on top of raw FMP data — we collect and track FMP estimates over time to provide revision history that FMP itself doesn't offer. With the API migration, this becomes even cleaner: the tools call our own hosted API (which aggregates FMP data), making `psycopg2` an optional dependency only needed if someone wants to run their own local estimate database. The `ESTIMATE_API_URL` env var makes this seamless — set it and the tools just work over HTTP, no database setup required.

**fmp-mcp packaging:** `psycopg2-binary` is already an optional `[estimates]` extra in `pyproject.toml:26`. No change needed to the extras definition. After verification, update the README to document the two modes (HTTP via `ESTIMATE_API_URL` vs local DB via `pip install fmp-mcp[estimates]`).

**fmp-mcp release:** After the HTTP migration is verified, bump the version in `pyproject.toml` and publish a new release (`hatch build && hatch publish` or equivalent). The version bump should reflect that the estimate tools now default to HTTP mode.

### Step 6: Data Migration (One-Time)

```bash
# Local: dump
pg_dump -Fc fmp_data_db > fmp_data_db.dump

# SCP to EC2
scp -i edgar-updater-key.pem fmp_data_db.dump ubuntu@3.136.23.202:/tmp/

# EC2: restore to RDS
pg_restore -h <rds-endpoint> -U estimateadmin -d fmp_data_db --no-owner /tmp/fmp_data_db.dump

# Verify row counts match
```

### Step 7: Deployment Script Updates

**`update_local.sh`** — add `estimates/` and timer files to the zip.

**`update_remote.sh`** — add atomic swap for `estimates/` directory (same pattern as `edgar_parser/`), copy timer/service files to systemd, enable timer.

### Step 8: Testing & Verification

1. Deploy to EC2, hit each API endpoint manually (curl)
2. Run collection for small universe: `python -m estimates.collector --tickers AAPL,MSFT,GOOGL`
3. Set `ESTIMATE_API_URL` locally, reconnect fmp-mcp, run both MCP tools
4. Compare output to local-DB path (should be identical)
5. Add unit tests for API routes (mocked EstimateStore)
6. Add unit tests for HTTP-path MCP tools (mock `requests.get`)

### Step 9: Cleanup

- Remove fallback branch from `fmp/tools/estimates.py` (HTTP-only)
- Remove local launchd plist for snapshot collection
- Keep `fmp/estimate_store.py` in risk_module as canonical source (add comment noting EC2 copy)
- Update `docs/reference/EARNINGS_ESTIMATES.md`
- Optionally drop local `fmp_data_db`

## Files Modified

**Edgar_updater repo (new):**
- `estimates/__init__.py`, `estimates/store.py`, `estimates/scripts/create_fmp_data_schema.sql`, `estimates/collector.py`
- `edgar_api/routes/estimates.py`
- `estimate_collector.service`, `estimate_collector.timer`

**Edgar_updater repo (modified):**
- `edgar_api/routes/__init__.py` (register estimates router)
- `edgar_api.service` (add `EnvironmentFile` for DB URL)
- `requirements.txt` (add psycopg2-binary)
- `update_local.sh`, `update_remote.sh` (include new files)

**Risk_module repo (modified):**
- `fmp/tools/estimates.py` (HTTP client instead of EstimateStore)

**fmp-mcp repo (modified):**
- `fmp/tools/estimates.py` (HTTP client instead of EstimateStore)
- `pyproject.toml` (version bump for new release)
- `README.md` (document HTTP vs local-DB modes)

## Verification

1. `curl https://financialmodelupdater.com/estimates/tickers` → returns ticker list
2. `curl https://financialmodelupdater.com/estimates/latest?ticker=AAPL&period=quarter` → returns snapshots
3. MCP: `get_estimate_revisions(ticker="AAPL")` → same data as before
4. MCP: `screen_estimate_revisions(direction="up", days=30)` → same data as before
5. `systemctl status estimate_collector.timer` → active, next trigger visible
