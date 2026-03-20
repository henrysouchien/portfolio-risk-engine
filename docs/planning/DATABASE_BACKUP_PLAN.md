# Database Backup & Recovery Plan

**Status:** NOT STARTED
**Date:** 2026-03-19
**Priority:** High (financial data, multi-user production system)

---

## Goal

Establish a comprehensive backup and recovery strategy for the risk_module PostgreSQL database across local development and AWS RDS production environments. The system handles financial portfolio data for multiple users with strict data integrity requirements.

---

## Current State

### What Exists
- **Local dev:** PostgreSQL (`risk_module_dev`) on macOS, `DATABASE_URL` from `.env`
- **Production (planned):** RDS PostgreSQL in `us-east-2`, shared instance with `fmp_data_db` (see `docs/deployment/MULTI_USER_DEPLOYMENT_PLAN.md`)
- **Schema:** `database/schema.sql` (948 lines, ~30 tables including migration-added tables)
- **Migrations:** `database/migrations/` (28 SQL files, tracked via `_migrations` table)
- **Migration runner:** `scripts/run_migrations.py` (per-file transactions, idempotent tracking)
- **Connection layer:** `app_platform/db/` (`ThreadedConnectionPool`, `SessionManager`, psycopg2)
- **Existing backup script:** `scripts/backup_system.sh` -- filesystem rsync of source code/config only, **no database backup**

### What Does NOT Exist
- No database backup script (pg_dump or otherwise)
- No RDS snapshot configuration
- No point-in-time recovery setup
- No backup verification or dry-run testing
- No pre-migration backup hook
- No user data export capability
- No disaster recovery runbook
- No backup monitoring or alerting

### Database Tables (Complete Inventory)

**Core User Data (HIGH criticality -- user-generated, irreplaceable):**

| Table | Source | Rows (est.) | Notes |
|-------|--------|-------------|-------|
| `users` | Auth flow | ~10-100 | Google/GitHub/Apple OAuth profiles |
| `portfolios` | User + auto-managed | ~2-5 per user | Portfolio definitions with date ranges |
| `positions` | Plaid/SnapTrade/IBKR sync + manual | ~50-200 per user | Holdings with cost basis, multi-currency |
| `accounts` | Provider discovery | ~5-15 per user | Financial accounts linked to data sources |
| `data_sources` | Provider connections | ~3-8 per user | Plaid/SnapTrade/Schwab connection metadata |
| `provider_items` | Webhook mapping | ~3-8 per user | Provider item_id to user lookup |
| `portfolio_accounts` | User config | ~5-15 per user | Virtual portfolio scoping |
| `risk_limits` | User config | ~1-3 per user | Custom risk parameters |
| `target_allocations` | User config | ~5-15 per user | Asset class weight targets |
| `expected_returns` | User/calculated | Grows over time | Insert-only versioned (immutable design) |
| `user_preferences` | User + AI inference | ~5-20 per user | Risk tolerance, goals, constraints |
| `scenarios` | User-created | ~2-10 per user | What-if scenario definitions |
| `scenario_positions` | User-created | ~10-50 per user | Scenario target weights |
| `user_sessions` | Auth system | Transient | Session tokens (expires_at TTL) |

**Transaction Store (HIGH criticality -- ingested from providers, expensive to re-fetch):**

| Table | Source | Rows (est.) | Notes |
|-------|--------|-------------|-------|
| `ingestion_batches` | Ingest pipeline | ~50-200 per user | Batch metadata with coverage windows |
| `raw_transactions` | Provider APIs | ~500-5000 per user | Original provider JSON preserved |
| `normalized_transactions` | Normalizer pipeline | ~500-5000 per user | Canonical trade format |
| `normalized_income` | Normalizer pipeline | ~50-500 per user | Dividends, interest, fees |
| `provider_flow_events` | Flow extractors | ~100-1000 per user | Deposits, withdrawals, transfers |
| `plaid_securities` | Plaid API | ~50-200 per user | Security metadata cache |

**Trading & Workflow (MEDIUM criticality -- audit trail, reproducible):**

| Table | Source | Rows (est.) | Notes |
|-------|--------|-------------|-------|
| `trade_previews` | Trade flow | ~10-100 per user | Preview snapshots with expiry |
| `trade_orders` | Execution | ~5-50 per user | Order fill records, brokerage response |
| `workflow_actions` | MCP tools | ~20-100 per user | Recommendation audit trail |
| `workflow_action_events` | Status transitions | ~50-300 per user | Immutable event log |
| `scenario_history` | Analysis runs | ~20-100 per user | Stress test / Monte Carlo results |

**Audit Trail (MEDIUM criticality):**

| Table | Source | Rows (est.) | Notes |
|-------|--------|-------------|-------|
| `portfolio_changes` | System events | ~100-500 per user | Position change history |
| `conversation_history` | AI context | ~20-100 per user | Key insights, action items |

**Reference Data (LOW criticality -- seeded from YAML/scripts, easily recreated):**

| Table | Source | Rows (est.) | Notes |
|-------|--------|-------------|-------|
| `factor_proxies` | Auto-calculated | ~50-200 per portfolio | Per-stock factor proxy ETFs |
| `factor_tracking` | System config | ~10-50 per portfolio | Factor analysis config |
| `user_factor_groups` | User-defined | ~1-5 per user | Custom factor groups |
| `exchange_proxies` | Seed data | ~6 rows | Exchange-to-ETF mappings |
| `industry_proxies` | Seed data | ~11 rows | Industry-to-ETF mappings |
| `asset_etf_proxies` | Seed data | ~20-50 rows | Asset class ETF catalog |
| `security_types` | FMP cache | ~200-500 rows | Auto-populated classification cache |
| `security_type_mappings` | Seed data | ~15 rows | Provider code mappings |
| `security_type_scenarios` | Seed data | ~9 rows | Crash scenario configs |
| `subindustry_peers` | GPT/manual | ~100-300 rows | Peer ticker cache |
| `futures_contracts` | Seed data | ~27 rows | Contract specifications |
| `exchange_resolution_config` | Seed data | 1 row | JSONB exchange mappings |
| `accounts_migration_state` | Migration sentinel | ~3 rows | One-time migration gates |
| `user_ticker_config` | User overrides | ~5-20 per user | Ticker-level config overrides |
| `_migrations` | Migration runner | ~28 rows | Applied migration tracking |

---

## Recovery Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| **RPO** (Recovery Point Objective) | 1 hour | Maximum acceptable data loss. RDS PITR provides 5-minute granularity; logical backups fill the portability gap. |
| **RTO** (Recovery Time Objective) | 30 minutes | Maximum time to restore service. RDS snapshot restore takes ~10-15 min; logical restore from S3 takes ~5-10 min for current data volume. |
| **Backup Window** | No downtime | All backups are non-blocking (RDS snapshots are copy-on-write; pg_dump uses `--no-lock` or runs on read replica). |
| **Retention** | Daily: 7 days, Weekly: 4 weeks, Monthly: 12 months | Balances storage cost against audit/compliance needs for financial data. |

---

## Implementation Plan

### Step 1: Local Dev Backup Script

**File:** `scripts/backup_db.sh`

```bash
#!/usr/bin/env bash
# Local dev database backup using pg_dump.
# Usage: ./scripts/backup_db.sh [output_dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${1:-$PROJECT_ROOT/backup/db}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Load DATABASE_URL from .env if not set
if [ -z "${DATABASE_URL:-}" ]; then
    if [ -f "$PROJECT_ROOT/.env" ]; then
        export $(grep -E '^DATABASE_URL=' "$PROJECT_ROOT/.env" | head -1)
    fi
fi

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL not set. Export it or add to .env" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# Schema-only dump (for disaster recovery baseline)
SCHEMA_FILE="$BACKUP_DIR/schema_${TIMESTAMP}.sql"
pg_dump --schema-only --no-owner --no-privileges "$DATABASE_URL" > "$SCHEMA_FILE"
echo "Schema backup: $SCHEMA_FILE"

# Full data dump (compressed custom format for fastest restore)
DATA_FILE="$BACKUP_DIR/full_${TIMESTAMP}.dump"
pg_dump --format=custom --compress=9 --no-owner --no-privileges "$DATABASE_URL" > "$DATA_FILE"
echo "Full backup:   $DATA_FILE ($(du -h "$DATA_FILE" | cut -f1))"

# Prune local backups older than 7 days
find "$BACKUP_DIR" -name "*.dump" -mtime +7 -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "schema_*.sql" -mtime +7 -delete 2>/dev/null || true
echo "Pruned backups older than 7 days."
```

**Testing:**
- Run manually: `./scripts/backup_db.sh`
- Verify restore: `pg_restore --dbname=risk_module_test --clean --no-owner backup/db/full_*.dump`
- Add to `.gitignore`: `backup/db/`

**Effort:** 30 minutes

---

### Step 2: Pre-Migration Backup Hook

**File:** Modify `scripts/run_migrations.py`

Add automatic backup before applying any pending migrations. This is the highest-value safety net -- schema migrations are the #1 cause of data loss in production.

```python
def _pre_migration_backup(db_url: str, migrations_dir: Path) -> Path | None:
    """Create a pg_dump backup before applying migrations."""
    import subprocess

    backup_dir = migrations_dir.parent / "migration_backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"pre_migration_{timestamp}.dump"

    try:
        result = subprocess.run(
            ["pg_dump", "--format=custom", "--compress=9",
             "--no-owner", "--no-privileges", db_url],
            capture_output=True, timeout=300,
        )
        if result.returncode == 0:
            backup_file.write_bytes(result.stdout)
            print(f"  Pre-migration backup: {backup_file} ({len(result.stdout)} bytes)")
            return backup_file
        else:
            print(f"  WARNING: Pre-migration backup failed: {result.stderr.decode()}")
            return None
    except Exception as e:
        print(f"  WARNING: Pre-migration backup skipped: {e}")
        return None
```

Insert call in `run_migrations()` after computing `applied` set, before the migration loop:

```python
    # Count pending migrations
    pending = [f for f in sorted(migrations_dir.glob("*.sql")) if f.name not in applied]
    if pending:
        print(f"  {len(pending)} pending migration(s). Creating pre-migration backup...")
        _pre_migration_backup(db_url, migrations_dir)
```

Add `database/migration_backups/` to `.gitignore`.

**Effort:** 30 minutes

---

### Step 3: RDS Automated Snapshots (Production)

RDS provides native automated backups at no additional cost (included in instance price). Configure during RDS instance creation or modify after.

**Configuration (AWS CLI):**

```bash
aws rds modify-db-instance \
  --db-instance-identifier risk-module-rds \
  --backup-retention-period 7 \
  --preferred-backup-window "06:00-06:30" \
  --copy-tags-to-snapshot \
  --region us-east-2
```

| Setting | Value | Rationale |
|---------|-------|-----------|
| `backup-retention-period` | 7 days | RDS native limit; augmented by logical backups in S3 for longer retention |
| `preferred-backup-window` | 06:00-06:30 UTC | Low-traffic window (1-1:30 AM ET) |
| PITR | Enabled automatically | 5-minute granularity within retention window |
| Multi-AZ | Not initially | Single-user/low-traffic phase; enable when scaling |

**Cost:** $0 additional (included with RDS instance). Storage for snapshots is free up to the DB storage size.

**Effort:** 15 minutes (CLI commands during deployment)

---

### Step 4: Logical Backups to S3 (Production)

RDS snapshots are fast but RDS-only (cannot restore to local dev, different AWS account, or non-RDS Postgres). Logical backups via pg_dump provide full portability.

**File:** `scripts/backup_db_to_s3.sh`

```bash
#!/usr/bin/env bash
# Production logical backup: pg_dump -> gzip -> S3.
# Designed to run on EC2 instance via cron or systemd timer.
set -euo pipefail

S3_BUCKET="${BACKUP_S3_BUCKET:-risk-module-backups}"
S3_PREFIX="${BACKUP_S3_PREFIX:-db-backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DAY_OF_WEEK=$(date +%u)  # 1=Monday, 7=Sunday
DAY_OF_MONTH=$(date +%d)
BACKUP_TYPE="daily"

# Weekly backup on Sundays
if [ "$DAY_OF_WEEK" = "7" ]; then
    BACKUP_TYPE="weekly"
fi

# Monthly backup on 1st of month
if [ "$DAY_OF_MONTH" = "01" ]; then
    BACKUP_TYPE="monthly"
fi

S3_KEY="${S3_PREFIX}/${BACKUP_TYPE}/risk_module_${TIMESTAMP}.dump.gz"

echo "$(date -Iseconds) Starting ${BACKUP_TYPE} backup..."

# Stream pg_dump through gzip directly to S3 (no local disk needed)
pg_dump --format=custom --compress=9 --no-owner --no-privileges "$DATABASE_URL" \
  | aws s3 cp - "s3://${S3_BUCKET}/${S3_KEY}"

RESULT=$?
if [ $RESULT -eq 0 ]; then
    SIZE=$(aws s3 ls "s3://${S3_BUCKET}/${S3_KEY}" | awk '{print $3}')
    echo "$(date -Iseconds) Backup complete: s3://${S3_BUCKET}/${S3_KEY} (${SIZE} bytes)"

    # Publish success metric to CloudWatch
    aws cloudwatch put-metric-data \
      --namespace "RiskModule" \
      --metric-name "BackupSuccess" \
      --value 1 \
      --unit Count \
      --dimensions BackupType="${BACKUP_TYPE}" \
      --region us-east-2
else
    echo "$(date -Iseconds) ERROR: Backup failed with exit code $RESULT" >&2

    # Publish failure metric
    aws cloudwatch put-metric-data \
      --namespace "RiskModule" \
      --metric-name "BackupFailure" \
      --value 1 \
      --unit Count \
      --dimensions BackupType="${BACKUP_TYPE}" \
      --region us-east-2

    exit 1
fi
```

**S3 Lifecycle Policy (retention):**

```json
{
  "Rules": [
    {
      "ID": "daily-retention-7d",
      "Filter": { "Prefix": "db-backups/daily/" },
      "Status": "Enabled",
      "Expiration": { "Days": 7 }
    },
    {
      "ID": "weekly-retention-28d",
      "Filter": { "Prefix": "db-backups/weekly/" },
      "Status": "Enabled",
      "Expiration": { "Days": 28 }
    },
    {
      "ID": "monthly-retention-365d",
      "Filter": { "Prefix": "db-backups/monthly/" },
      "Status": "Enabled",
      "Expiration": { "Days": 365 }
    },
    {
      "ID": "transition-to-ia",
      "Filter": { "Prefix": "db-backups/" },
      "Status": "Enabled",
      "Transitions": [
        { "Days": 30, "StorageClass": "STANDARD_IA" }
      ]
    }
  ]
}
```

**Cron (EC2):**

```bash
# /etc/cron.d/risk-module-backup
# Daily at 07:00 UTC (2 AM ET, after RDS snapshot window)
0 7 * * * ubuntu /var/www/risk_module/scripts/backup_db_to_s3.sh >> /var/log/risk-module-backup.log 2>&1
```

**S3 Bucket Setup:**

```bash
aws s3 mb s3://risk-module-backups --region us-east-2

# Enable versioning (extra safety against accidental deletion)
aws s3api put-bucket-versioning \
  --bucket risk-module-backups \
  --versioning-configuration Status=Enabled

# Block public access
aws s3api put-public-access-block \
  --bucket risk-module-backups \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Enable default encryption (SSE-S3)
aws s3api put-bucket-encryption \
  --bucket risk-module-backups \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# Apply lifecycle policy
aws s3api put-bucket-lifecycle-configuration \
  --bucket risk-module-backups \
  --lifecycle-configuration file://scripts/s3_lifecycle_policy.json
```

**IAM Policy for EC2 instance profile:**

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:DeleteObject"
            ],
            "Resource": [
                "arn:aws:s3:::risk-module-backups",
                "arn:aws:s3:::risk-module-backups/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": "cloudwatch:PutMetricData",
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "cloudwatch:namespace": "RiskModule"
                }
            }
        }
    ]
}
```

**Cost estimate:** ~$0.50/month (estimated 500 MB total across all retention tiers).

**Effort:** 1 hour

---

### Step 5: Restore Procedures

#### 5A. Full Restore from RDS Snapshot

Use case: Complete database corruption, accidental DROP TABLE, or disaster recovery.

```bash
# 1. List available snapshots
aws rds describe-db-snapshots \
  --db-instance-identifier risk-module-rds \
  --query 'DBSnapshots[*].{ID:DBSnapshotIdentifier,Time:SnapshotCreateTime,Status:Status}' \
  --output table \
  --region us-east-2

# 2. Restore to a NEW instance (non-destructive — original stays running)
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier risk-module-rds-restored \
  --db-snapshot-identifier rds:risk-module-rds-2026-03-19-06-00 \
  --db-instance-class db.t3.micro \
  --vpc-security-group-ids sg-XXXXXXXX \
  --region us-east-2

# 3. Wait for restore to complete (~10-15 minutes)
aws rds wait db-instance-available \
  --db-instance-identifier risk-module-rds-restored \
  --region us-east-2

# 4. Update DATABASE_URL in .env to point to restored instance
# 5. Restart service: sudo systemctl restart risk_module
# 6. Verify: curl http://localhost:5001/api/health
# 7. Once verified, delete old instance or rename
```

**RTO:** ~15 minutes (snapshot restore) + 5 minutes (verification).

#### 5B. Point-in-Time Recovery (PITR)

Use case: Accidental DELETE/UPDATE within the last 7 days, need to recover to exact timestamp.

```bash
# 1. Identify the target time (UTC). Example: recover to just before an accidental DELETE at 14:30.
TARGET_TIME="2026-03-19T14:25:00Z"

# 2. Restore to a new instance at that exact point in time
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier risk-module-rds \
  --target-db-instance-identifier risk-module-rds-pitr \
  --restore-time "$TARGET_TIME" \
  --db-instance-class db.t3.micro \
  --vpc-security-group-ids sg-XXXXXXXX \
  --region us-east-2

# 3. Wait for availability
aws rds wait db-instance-available \
  --db-instance-identifier risk-module-rds-pitr \
  --region us-east-2

# 4. Extract only the needed data from the PITR instance
#    (selective restore — don't replace everything)
pg_dump --table=positions --data-only \
  "postgresql://user:pw@pitr-endpoint:5432/risk_module_db" \
  | psql "$DATABASE_URL"

# 5. Clean up the PITR instance
aws rds delete-db-instance \
  --db-instance-identifier risk-module-rds-pitr \
  --skip-final-snapshot \
  --region us-east-2
```

**RPO:** 5 minutes (RDS PITR granularity).

#### 5C. Logical Restore from pg_dump (S3)

Use case: Restore to a different environment, different AWS account, or local dev.

```bash
# 1. List available backups
aws s3 ls s3://risk-module-backups/db-backups/ --recursive \
  | sort -k1,2 | tail -10

# 2. Download the backup
aws s3 cp s3://risk-module-backups/db-backups/daily/risk_module_20260319_070000.dump.gz \
  /tmp/restore.dump.gz

# 3a. Restore to existing database (destructive — drops and recreates objects)
pg_restore --dbname=risk_module_db --clean --no-owner --no-privileges \
  /tmp/restore.dump.gz

# 3b. OR restore to a fresh database (non-destructive)
createdb risk_module_restored
pg_restore --dbname=risk_module_restored --no-owner --no-privileges \
  /tmp/restore.dump.gz
```

**Prod-to-local restore (for debugging):**

```bash
# Download latest production backup to local machine
aws s3 cp s3://risk-module-backups/db-backups/daily/risk_module_latest.dump.gz \
  /tmp/prod_snapshot.dump.gz

# Restore to local dev database (separate from normal dev DB)
createdb risk_module_prod_copy
pg_restore --dbname=risk_module_prod_copy --no-owner --no-privileges \
  /tmp/prod_snapshot.dump.gz

# IMPORTANT: Scrub sensitive data if sharing with others
psql risk_module_prod_copy -c "
  UPDATE users SET email = 'user_' || id || '@test.com',
                   google_user_id = 'test_' || id,
                   api_key_hash = NULL;
  TRUNCATE user_sessions;
"
```

#### 5D. Restore to Different Environment (Prod to Staging)

```bash
# 1. Download latest production backup
aws s3 cp s3://risk-module-backups/db-backups/daily/risk_module_latest.dump.gz \
  /tmp/staging_restore.dump.gz

# 2. Create staging database on target RDS (or local)
psql "$STAGING_DATABASE_URL" -c "DROP DATABASE IF EXISTS risk_module_staging;"
psql "$STAGING_DATABASE_URL" -c "CREATE DATABASE risk_module_staging;"

# 3. Restore
pg_restore --dbname=risk_module_staging --no-owner --no-privileges \
  /tmp/staging_restore.dump.gz

# 4. Scrub PII and tokens
psql risk_module_staging -c "
  UPDATE users SET
    email = 'staging_user_' || id || '@test.com',
    name = 'Test User ' || id,
    google_user_id = 'staging_google_' || id,
    github_user_id = NULL,
    apple_user_id = NULL,
    api_key_hash = NULL;
  TRUNCATE user_sessions;
  UPDATE provider_items SET item_id = 'staging_' || id;
  UPDATE data_sources SET metadata = '{}';
"
```

**Effort:** 1 hour (writing and testing all procedures)

---

### Step 6: Backup Verification (Automated Dry-Run)

Trust but verify. A backup that cannot be restored is not a backup.

**File:** `scripts/verify_backup.sh`

```bash
#!/usr/bin/env bash
# Weekly backup verification: download latest S3 backup, restore to temp DB, run checks.
# Designed to run on EC2 via weekly cron (Sunday 08:00 UTC).
set -euo pipefail

S3_BUCKET="${BACKUP_S3_BUCKET:-risk-module-backups}"
VERIFY_DB="risk_module_verify_$$"
LATEST_BACKUP=$(aws s3 ls "s3://${S3_BUCKET}/db-backups/daily/" \
  | sort | tail -1 | awk '{print $4}')

if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: No backups found in S3" >&2
    aws cloudwatch put-metric-data \
      --namespace "RiskModule" \
      --metric-name "BackupVerifyFailure" \
      --value 1 --unit Count --region us-east-2
    exit 1
fi

echo "$(date -Iseconds) Verifying backup: $LATEST_BACKUP"

# Download
TEMP_FILE="/tmp/verify_backup_$$.dump"
aws s3 cp "s3://${S3_BUCKET}/db-backups/daily/${LATEST_BACKUP}" "$TEMP_FILE"

# Create temp database
psql "$DATABASE_URL" -c "CREATE DATABASE ${VERIFY_DB};" 2>/dev/null || true
VERIFY_URL=$(echo "$DATABASE_URL" | sed "s|/risk_module_db|/${VERIFY_DB}|")

# Restore
pg_restore --dbname="$VERIFY_URL" --no-owner --no-privileges "$TEMP_FILE"
RESTORE_RESULT=$?

if [ $RESTORE_RESULT -ne 0 ]; then
    echo "ERROR: Restore failed" >&2
    psql "$DATABASE_URL" -c "DROP DATABASE IF EXISTS ${VERIFY_DB};"
    rm -f "$TEMP_FILE"
    aws cloudwatch put-metric-data \
      --namespace "RiskModule" \
      --metric-name "BackupVerifyFailure" \
      --value 1 --unit Count --region us-east-2
    exit 1
fi

# Verify key tables have data
CHECKS_PASSED=0
CHECKS_TOTAL=0
for TABLE in users portfolios positions accounts normalized_transactions; do
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    COUNT=$(psql "$VERIFY_URL" -t -c "SELECT COUNT(*) FROM ${TABLE};" 2>/dev/null | tr -d ' ')
    if [ "${COUNT:-0}" -gt 0 ]; then
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
        echo "  OK: ${TABLE} has ${COUNT} rows"
    else
        echo "  WARN: ${TABLE} is empty (${COUNT} rows)"
    fi
done

# Verify schema completeness (compare table count)
PROD_TABLES=$(psql "$DATABASE_URL" -t -c \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';" | tr -d ' ')
VERIFY_TABLES=$(psql "$VERIFY_URL" -t -c \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';" | tr -d ' ')

echo "  Table count: production=${PROD_TABLES}, backup=${VERIFY_TABLES}"
if [ "$PROD_TABLES" != "$VERIFY_TABLES" ]; then
    echo "  WARN: Table count mismatch"
fi

# Cleanup
psql "$DATABASE_URL" -c "DROP DATABASE IF EXISTS ${VERIFY_DB};"
rm -f "$TEMP_FILE"

# Report
if [ $CHECKS_PASSED -eq $CHECKS_TOTAL ]; then
    echo "$(date -Iseconds) Verification PASSED (${CHECKS_PASSED}/${CHECKS_TOTAL})"
    aws cloudwatch put-metric-data \
      --namespace "RiskModule" \
      --metric-name "BackupVerifySuccess" \
      --value 1 --unit Count --region us-east-2
else
    echo "$(date -Iseconds) Verification PARTIAL (${CHECKS_PASSED}/${CHECKS_TOTAL})"
    aws cloudwatch put-metric-data \
      --namespace "RiskModule" \
      --metric-name "BackupVerifyFailure" \
      --value 1 --unit Count --region us-east-2
fi
```

**Cron:**

```bash
# Weekly verification on Sundays at 08:00 UTC (after daily backup at 07:00)
0 8 * * 0 ubuntu /var/www/risk_module/scripts/verify_backup.sh >> /var/log/risk-module-backup-verify.log 2>&1
```

**Effort:** 45 minutes

---

### Step 7: User Data Portability (Export)

Users should be able to export their own portfolio data. This also serves as a user-level backup mechanism.

**File:** `mcp_tools/export.py` (new MCP tool)

```python
@mcp_tool
def export_holdings(
    user_email: str,
    portfolio_name: str = "main",
    format: str = "csv",  # "csv" or "json"
) -> dict:
    """Export a user's portfolio holdings as CSV or JSON."""
```

**Tables to include per user:**
- `positions` (core holdings)
- `target_allocations` (asset class targets)
- `risk_limits` (risk parameters)
- `normalized_transactions` (trade history)
- `normalized_income` (income events)
- `provider_flow_events` (cash flows)

**REST endpoint:** `GET /api/portfolio/export?format=csv`

**Implementation notes:**
- Filter by `user_id` -- never expose other users' data
- CSV uses pandas `to_csv()` with streaming response
- JSON uses `jsonlines` format for large exports
- Include metadata header (export date, portfolio name, row counts)
- Redact sensitive fields (`provider_item_id`, `raw_data` JSONB)

**Effort:** 2 hours

---

### Step 8: Backup Monitoring & Alerting

#### CloudWatch Alarms

```bash
# Alarm: No successful backup in 26 hours (should fire daily)
aws cloudwatch put-metric-alarm \
  --alarm-name "risk-module-backup-missing" \
  --metric-name "BackupSuccess" \
  --namespace "RiskModule" \
  --statistic Sum \
  --period 93600 \
  --threshold 1 \
  --comparison-operator LessThanThreshold \
  --evaluation-periods 1 \
  --treat-missing-data breaching \
  --alarm-actions "$SNS_TOPIC_ARN" \
  --region us-east-2

# Alarm: Any backup failure
aws cloudwatch put-metric-alarm \
  --alarm-name "risk-module-backup-failure" \
  --metric-name "BackupFailure" \
  --namespace "RiskModule" \
  --statistic Sum \
  --period 3600 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 1 \
  --alarm-actions "$SNS_TOPIC_ARN" \
  --region us-east-2

# Alarm: Weekly verification failure
aws cloudwatch put-metric-alarm \
  --alarm-name "risk-module-backup-verify-failure" \
  --metric-name "BackupVerifyFailure" \
  --namespace "RiskModule" \
  --statistic Sum \
  --period 604800 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 1 \
  --alarm-actions "$SNS_TOPIC_ARN" \
  --region us-east-2
```

All alarms route to the same SNS topic used by the deployment plan (`risk-module-alerts` from Phase 8A of `MULTI_USER_DEPLOYMENT_PLAN.md`).

**Effort:** 30 minutes

---

### Step 9: Disaster Recovery Runbook

**File:** `docs/deployment/DISASTER_RECOVERY_RUNBOOK.md`

Contents (outline):

```
# Disaster Recovery Runbook

## Severity Levels
- P1: Database unavailable, all users affected
- P2: Data corruption detected, partial data loss
- P3: Single user data issue, no system-wide impact

## P1: Database Down

### Symptoms
- /api/health returns 503 or timeout
- Application logs show psycopg2.OperationalError
- CloudWatch StatusCheckFailed alarm firing

### Immediate Actions (< 5 min)
1. Check RDS status: aws rds describe-db-instances ...
2. If RDS is up but connection fails: check security groups, check EC2 status
3. If RDS is down: initiate snapshot restore (Step 5A)

### Restore Actions (< 30 min)
1. Restore from latest RDS snapshot to new instance
2. Update DATABASE_URL in /var/www/risk_module/.env
3. Restart service: sudo systemctl restart risk_module
4. Verify: curl http://localhost:5001/api/health

## P2: Data Corruption

### Symptoms
- Users report missing or incorrect data
- Application errors on specific queries
- Data integrity constraint violations in logs

### Investigation (< 10 min)
1. Identify affected tables and time range
2. Check portfolio_changes audit trail for recent modifications
3. Check _migrations table for recently applied migrations

### Recovery Options
- Option A: PITR restore to pre-corruption timestamp (Step 5B)
- Option B: Selective table restore from S3 logical backup (Step 5C)
- Option C: User-level data re-import from provider APIs

## P3: Single User Data Issue

### Recovery
1. Export user's data from last good backup
2. Restore specific user records via targeted SQL
3. Re-trigger provider sync (Plaid/SnapTrade) to refresh positions

## Post-Incident
1. Root cause analysis document
2. Update this runbook if needed
3. Review backup verification logs
4. Test restore procedure if it was not exercised during incident
```

**Effort:** 1 hour

---

## Files Created / Modified

| File | Action | Description |
|------|--------|-------------|
| `scripts/backup_db.sh` | CREATE | Local dev pg_dump backup script |
| `scripts/backup_db_to_s3.sh` | CREATE | Production pg_dump to S3 pipeline |
| `scripts/verify_backup.sh` | CREATE | Weekly backup verification dry-run |
| `scripts/s3_lifecycle_policy.json` | CREATE | S3 retention rules (7d/28d/365d) |
| `scripts/run_migrations.py` | MODIFY | Add pre-migration backup hook |
| `mcp_tools/export.py` | CREATE | User data export (CSV/JSON) |
| `docs/deployment/DISASTER_RECOVERY_RUNBOOK.md` | CREATE | DR procedures and runbook |
| `.gitignore` | MODIFY | Add `backup/db/`, `database/migration_backups/` |

---

## Implementation Order

| Step | Description | Effort | Priority | Depends On |
|------|-------------|--------|----------|------------|
| 1 | Local dev backup script (`scripts/backup_db.sh`) | 30 min | High | Nothing |
| 2 | Pre-migration backup hook in `run_migrations.py` | 30 min | High | Nothing |
| 3 | RDS automated snapshots (AWS config) | 15 min | High | RDS instance exists (deployment Phase 1) |
| 4 | Logical backups to S3 (`backup_db_to_s3.sh` + lifecycle) | 1 hour | High | S3 bucket + EC2 IAM role |
| 5 | Write and test restore procedures | 1 hour | High | Steps 1 + 4 |
| 6 | Backup verification script (`verify_backup.sh`) | 45 min | Medium | Step 4 |
| 7 | User data export tool (`mcp_tools/export.py`) | 2 hours | Medium | Nothing |
| 8 | CloudWatch monitoring alarms | 30 min | Medium | Step 4 |
| 9 | Disaster recovery runbook | 1 hour | Medium | Steps 3-6 |

**Total effort:** ~7.5 hours

**Steps 1-2** can be implemented immediately (local dev, no AWS dependency).
**Steps 3-6, 8-9** depend on the RDS production deployment (Phase 1 of `MULTI_USER_DEPLOYMENT_PLAN.md`).
**Step 7** is independent and can be implemented at any time.

---

## Testing Strategy

### Local Dev Testing (Steps 1-2)

```bash
# Test backup script
./scripts/backup_db.sh
ls -la backup/db/

# Test restore to a separate database
createdb risk_module_restore_test
pg_restore --dbname=risk_module_restore_test --no-owner backup/db/full_*.dump

# Verify row counts match
psql risk_module_dev -c "SELECT 'positions' as t, COUNT(*) FROM positions UNION ALL SELECT 'users', COUNT(*) FROM users;"
psql risk_module_restore_test -c "SELECT 'positions' as t, COUNT(*) FROM positions UNION ALL SELECT 'users', COUNT(*) FROM users;"

# Cleanup
dropdb risk_module_restore_test
```

### Pre-Migration Backup Testing

```bash
# Create a dummy migration to trigger the backup
echo "SELECT 1;" > database/migrations/99999999_test_backup_trigger.sql

# Run migrations (should create backup first, then apply)
DATABASE_URL=$DATABASE_URL python3 scripts/run_migrations.py

# Verify backup was created
ls -la database/migration_backups/

# Cleanup
rm database/migrations/99999999_test_backup_trigger.sql
psql "$DATABASE_URL" -c "DELETE FROM _migrations WHERE filename='99999999_test_backup_trigger.sql';"
```

### Production Testing (Post-Deployment)

```bash
# 1. Manual backup run
./scripts/backup_db_to_s3.sh

# 2. Verify S3 upload
aws s3 ls s3://risk-module-backups/db-backups/daily/ | tail -3

# 3. Manual verification run
./scripts/verify_backup.sh

# 4. Full restore drill (to temp database, non-destructive)
aws s3 cp s3://risk-module-backups/db-backups/daily/latest.dump.gz /tmp/drill.dump.gz
createdb risk_module_drill
pg_restore --dbname=risk_module_drill --no-owner /tmp/drill.dump.gz
# Compare counts, drop drill DB
dropdb risk_module_drill

# 5. PITR drill (restore to 1 hour ago, verify, delete)
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier risk-module-rds \
  --target-db-instance-identifier risk-module-pitr-drill \
  --restore-time "$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --region us-east-2
# Wait, connect, verify, then delete the drill instance

# 6. Verify CloudWatch metrics are reporting
aws cloudwatch get-metric-statistics \
  --namespace "RiskModule" \
  --metric-name "BackupSuccess" \
  --start-time "$(date -u -d '2 days ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 86400 \
  --statistics Sum \
  --region us-east-2
```

---

## Cost Summary

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| RDS automated snapshots | $0 | Included with instance, up to DB storage size |
| S3 backup storage | ~$0.50 | ~500 MB across all tiers, IA transition after 30d |
| CloudWatch alarms | $0.30 | 3 custom metric alarms |
| CloudWatch custom metrics | $0.90 | 3 custom metrics at $0.30/metric |
| **Total** | **~$1.70/month** | |

---

## Security Considerations

- S3 bucket: versioning enabled, public access blocked, SSE-S3 encryption at rest
- Backup files contain full database contents including PII (emails, names) -- treat as sensitive
- EC2 IAM role: least-privilege (S3 put/get + CloudWatch PutMetricData only)
- Prod-to-local restores MUST scrub PII before any sharing (see Step 5D)
- `database/migration_backups/` and `backup/db/` directories are gitignored -- never commit backup files
- Pre-migration backups use `pg_dump` subprocess with `DATABASE_URL` from environment -- no credentials stored in script files
