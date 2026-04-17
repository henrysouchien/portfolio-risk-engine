# E22: Multi-User DB Connection Pooling via pgbouncer

## Context

Current architecture: every process opens its own `psycopg2.ThreadedConnectionPool` (max 10) directly to PostgreSQL. With 6+ processes (Uvicorn, 4 Celery workers, Celery beat), the theoretical max is ~130 connections for a single user — already exceeding PostgreSQL's default `max_connections=100`. Each PostgreSQL connection costs 5-10MB (dedicated backend process), so raising the limit doesn't scale.

pgbouncer solves this by sitting between all app processes and PostgreSQL, multiplexing many cheap app-side connections through a small pool of real database connections. In **transaction mode**, a real connection is assigned only for the duration of a transaction, then returned to the shared pool — perfect for this codebase's short-lived `get_db_session()` context managers.

**Compatibility verified**: The codebase's `autocommit` toggling is psycopg2 client-side (controls implicit BEGIN), not a PostgreSQL SET command — fully compatible with transaction mode. The only SET session variables (`SET timezone`, `SET default_transaction_read_only`) are in `fmp/estimate_store.py` which uses a separate `FMP_DATA_DATABASE_URL` and direct `psycopg2.connect()` — not affected.

## Architecture

```
BEFORE:
  Uvicorn ──────────┐
  Celery workers ───┼──→ PostgreSQL (max_connections=100)
  Celery beat ──────┘
  (each holds up to 10 real connections)

AFTER:
  Uvicorn ──────────┐
  Celery workers ───┼──→ pgbouncer (:6432) ──→ PostgreSQL (:5432)
  Celery beat ──────┘     20 real conns          max_connections=100
  (many cheap logical connections)

  FMP EstimateStore ────────────────────→ PostgreSQL (direct, separate DB)
  Migrations ───────────────────────────→ PostgreSQL (direct)
```

- **App traffic** → pgbouncer (port 6432) via `DATABASE_URL`
- **Migrations** → PostgreSQL direct (port 5432) via `DATABASE_URL_DIRECT`
- **FMP data** → PostgreSQL direct via `FMP_DATA_DATABASE_URL` (unchanged)

---

## Changes

### Change 1: pgbouncer config for local dev

**New file:** `config/pgbouncer/pgbouncer.ini`

```ini
[databases]
; Backend credentials — match user/password from DATABASE_URL_DIRECT in .env
risk_module_db = host=127.0.0.1 port=5432 dbname=risk_module_db user=user password=password

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = any
pool_mode = transaction

; Pool sizing — real connections to PostgreSQL
default_pool_size = 20
min_pool_size = 5
reserve_pool_size = 5
reserve_pool_timeout = 3

; Client-side limits (cheap, be generous)
max_client_conn = 200

; Connection lifecycle
server_idle_timeout = 300
server_lifetime = 3600
server_connect_timeout = 5
client_idle_timeout = 0
query_wait_timeout = 120

; Logging
log_connections = 0
log_disconnections = 0
stats_period = 60

; Admin — '*' allows any user to run SHOW commands in dev
admin_users = *
ignore_startup_parameters = extra_float_digits
```

Key decisions:
- `auth_type = any` for local dev — skips client auth entirely (no auth_file needed). pgbouncer uses the `user`/`password` from the `[databases]` stanza to authenticate to PostgreSQL backend
- `admin_users = *` for dev — allows any user to run `SHOW POOLS`/`SHOW STATS` on the virtual `pgbouncer` database
- `default_pool_size = 20`: comfortable for dev with ~6 processes
- `server_idle_timeout = 300`: recycle idle real connections after 5 min
- `server_lifetime = 3600`: recycle all real connections after 1 hour
- `ignore_startup_parameters = extra_float_digits`: psycopg2 sends this on connect; pgbouncer must ignore it

**Note:** The `user`/`password` in `[databases]` must match the PostgreSQL credentials. For local dev, update these to match your `DATABASE_URL_DIRECT`. This file is a template — developers should copy and customize, not commit credentials.

### Change 2: pgbouncer production config template

**New file:** `config/pgbouncer/pgbouncer.prod.ini`

Same as dev, with these differences:
```ini
[databases]
risk_module_db = host=<rds-endpoint> port=5432 dbname=risk_module_db user=risk_module_user password=<pw>

[pgbouncer]
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt

; Production: restrict admin access
admin_users = pgbouncer

; Tighter logging in prod
log_connections = 1
log_disconnections = 1
```

Production uses `auth_type = md5` with an `auth_file` for client authentication (app → pgbouncer). The `auth_file` must contain password hashes for every user that connects through pgbouncer. Backend credentials (pgbouncer → RDS) are in the `[databases]` stanza.

**New file:** `config/pgbouncer/userlist.txt.example`
```
; Generate hash: echo -n '<password><username>' | md5sum | awk '{print "md5"$1}'
; App user — used by DATABASE_URL connections
"risk_module_user" "md5<hash>"
; Admin user — used for SHOW POOLS / SHOW STATS monitoring
"pgbouncer" "md5<hash>"
```

Both users must be in `auth_file` for production. The `pgbouncer` admin user needs a password hash so `admin_users = pgbouncer` can authenticate for monitoring commands (`SHOW POOLS`, `SHOW STATS`, `RELOAD`, etc.).

### Change 3: Add pgbouncer to services.yaml

**File:** `services.yaml`

Add pgbouncer as a managed service before `risk_module`:

```yaml
  pgbouncer:
    command:
      - pgbouncer
      - config/pgbouncer/pgbouncer.ini
    port: 6432
    description: Connection pooling proxy for PostgreSQL
    expected_cmd:
      - pgbouncer
```

No `env_file` needed — pgbouncer reads its own config.

### Change 4: Update .env.example

**File:** `.env.example`

Update the database config section:

```bash
# Database Configuration
# App traffic goes through pgbouncer (port 6432)
DATABASE_URL=postgresql://user:password@localhost:6432/risk_module_db
# Direct connection for migrations and admin (port 5432)
DATABASE_URL_DIRECT=postgresql://user:password@localhost:5432/risk_module_db
FMP_DATA_DATABASE_URL=postgresql://postgres@localhost:5432/fmp_data_db
DB_POOL_MIN=2
DB_POOL_MAX=10
```

### Change 5: Migration script uses direct connection

**File:** `scripts/run_migrations.py` (line 9)

```python
# Before:
db_url = os.environ["DATABASE_URL"]

# After:
db_url = os.getenv("DATABASE_URL_DIRECT") or os.environ["DATABASE_URL"]
```

Migrations should bypass pgbouncer — they run DDL and are a one-time admin operation. Falls back to `DATABASE_URL` if `DATABASE_URL_DIRECT` isn't set (backward compatible).

### Change 6: Update deployment plan

**File:** `docs/deployment/MULTI_USER_DEPLOYMENT_PLAN.md`

**6a. Add new Phase 2B′ — pgbouncer setup** (after 2B environment file, before 2C systemd):

Content:
- Install: `sudo apt install pgbouncer`
- Copy `config/pgbouncer/pgbouncer.prod.ini` to `/etc/pgbouncer/pgbouncer.ini`
- Fill in RDS endpoint and credentials in `[databases]` stanza
- Generate `userlist.txt` with both app and admin users:
  ```bash
  PW_HASH=$(echo -n '<pw>risk_module_user' | md5sum | cut -d' ' -f1)
  ADMIN_HASH=$(echo -n '<admin_pw>pgbouncer' | md5sum | cut -d' ' -f1)
  cat > /etc/pgbouncer/userlist.txt <<EOF
  "risk_module_user" "md5${PW_HASH}"
  "pgbouncer" "md5${ADMIN_HASH}"
  EOF
  ```
- pgbouncer runs as a systemd service (ships with apt package): `sudo systemctl enable --now pgbouncer`
- Verify: `psql -h localhost -p 6432 -U pgbouncer -d pgbouncer -c "SHOW POOLS"`

**6b. Update Phase 2B env file template** (~line 215):
- `DATABASE_URL` → `postgresql://risk_module_user:<pw>@localhost:6432/risk_module_db`
- Add `DATABASE_URL_DIRECT=postgresql://risk_module_user:<pw>@<rds-endpoint>:5432/risk_module_db`

**6c. Update Phase 2C systemd service** (~line 267):
- Add `After=pgbouncer.service` and `Requires=pgbouncer.service` to `risk_module.service` unit's `[Unit]` section, so Uvicorn waits for pgbouncer before starting

**6d. Update migration runner references** (~line 413):
- Note that `scripts/run_migrations.py` uses `DATABASE_URL_DIRECT` (direct to RDS) for DDL operations. The `DATABASE_URL` (pgbouncer) should not be used for migrations.

**6e. Update ECS/Fargate notes** (~line 854):
- Note that pgbouncer runs as a sidecar container in ECS, or as an RDS Proxy (managed pgbouncer). `DATABASE_URL` always points to the proxy, never directly to RDS.

---

## Files touched

| File | Change |
|------|--------|
| `config/pgbouncer/pgbouncer.ini` | **New** — local dev config |
| `config/pgbouncer/pgbouncer.prod.ini` | **New** — production config template |
| `config/pgbouncer/userlist.txt.example` | **New** — auth file template |
| `services.yaml` | Add pgbouncer service |
| `.env.example` | Update DATABASE_URL to pgbouncer, add DATABASE_URL_DIRECT |
| `scripts/run_migrations.py` | Prefer DATABASE_URL_DIRECT (1 line) |
| `docs/deployment/MULTI_USER_DEPLOYMENT_PLAN.md` | Add pgbouncer deployment section |

**No application code changes.** Pool manager, session manager, all services — unchanged.

---

## What this does NOT change

- **`app_platform/db/pool.py`** — unchanged. App-side pools still work, they just connect to pgbouncer instead of PostgreSQL
- **`app_platform/db/session.py`** — unchanged
- **`database/__init__.py`** — unchanged (is_db_available probes through pgbouncer, which is fine)
- **`fmp/estimate_store.py`** — unchanged (uses FMP_DATA_DATABASE_URL, direct connection)
- **Celery workers** — unchanged. The E20 fork handlers still work. pgbouncer just means inherited connections point at pgbouncer instead of PostgreSQL
- **Per-process pool sizing** — deferred. With pgbouncer, app-side pool sizes matter less. Can tune later if needed

---

## Pool sizing math

| Setting | Value | Rationale |
|---------|-------|-----------|
| pgbouncer `default_pool_size` | 20 | Real connections to PostgreSQL |
| pgbouncer `reserve_pool_size` | 5 | Burst overflow |
| pgbouncer `max_client_conn` | 200 | App-side connections (cheap) |
| PostgreSQL `max_connections` | 100 | RDS default |
| Real connections used | 5-25 | Normal: min_pool_size to default+reserve |
| Headroom | 75 | For admin, monitoring, FMP reader, migrations |

### Long-lived transaction note

Trade execution in `services/trade_execution_service.py` opens `FOR UPDATE` transactions and then calls external broker APIs (IBKR, Schwab, SnapTrade) before committing. These transactions pin a real PostgreSQL connection for the full broker round-trip (100ms–10s depending on broker latency).

This is **compatible** with transaction-mode pgbouncer — the connection stays assigned for the transaction duration, which is correct. The concern is pool utilization: each in-flight trade execution holds one of the 20 real connections.

**Why 20 is adequate**: Trade execution is user-initiated, typically sequential per account, and concurrent trades across different users are rare at current scale. Even 5 simultaneous trade executions would use 5 of 20 connections, leaving 15 for all other app traffic (position queries, risk calculations, sync jobs). The reserve pool adds 5 more for bursts.

**If this becomes a bottleneck**: The solution is to split trade execution into separate transactions (SELECT FOR UPDATE → release → broker API → re-acquire → UPDATE). This decouples the lock duration from broker latency but adds complexity — not needed at current scale.

---

## Verification

1. **Local setup**:
   - `brew install pgbouncer` (macOS)
   - Start pgbouncer via services-mcp or `pgbouncer config/pgbouncer/pgbouncer.ini`
   - Verify listening: `psql -h localhost -p 6432 -d risk_module_db -c "SELECT 1"`
   - Start all services, run full test suite: `pytest tests/ -x --timeout=120`
   - Check connection count: `psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname='risk_module_db'"`
   - Verify connections stay bounded (should be ≤20 real connections under load)

2. **pgbouncer admin** (connect to virtual `pgbouncer` database):
   - `psql -h localhost -p 6432 -U pgbouncer -d pgbouncer -c "SHOW POOLS"` — see pool utilization (dev config uses `admin_users = *` so any `-U` value works)
   - `psql -h localhost -p 6432 -U pgbouncer -d pgbouncer -c "SHOW STATS"` — request/query counts

3. **Migration test**:
   - With `DATABASE_URL_DIRECT` set: migrations go direct to PostgreSQL
   - Without `DATABASE_URL_DIRECT`: migrations fall back to `DATABASE_URL` (pgbouncer) — still works, just not ideal

4. **E2E**:
   - Start all services with pgbouncer in the stack
   - Trigger concurrent brokerage syncs + API requests
   - Monitor `pg_stat_activity` — real connections should stay in 5-25 range
   - Frontend should work normally — zero behavioral changes
