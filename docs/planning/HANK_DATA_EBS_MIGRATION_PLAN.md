# Hank Data Volume — EBS Migration Plan

**Status:** v0.5 — DRAFT, awaiting Codex re-review
**Date:** 2026-04-30

**v0.4 → v0.5 changes (Codex R4 FAIL response):**
- **Celery worker handling.** R4 flagged that `services.yaml:113` defines `celery_worker_maint` and `workers/tasks/corpus.py:35` opens `data/filings.db`. Verified live on edgar-updater via SSH — **no Celery systemd services exist, no Celery processes running**, RabbitMQ inactive (only Redis is active, but unused without workers). Documented as Hard Prerequisite + flagged in §Future Work that ANY future Celery deployment must include `RequiresMountsFor=/mnt/hank-data` and be added to `service_stop` in cutover.
- **SQLite PRAGMA result-row assertions.** R4 caught that `PRAGMA wal_checkpoint(TRUNCATE)` and `PRAGMA integrity_check` return success-as-row, not via process exit code. v0.5 captures and asserts: checkpoint first column must be `0` (SQLITE_OK), integrity output must equal `ok`. Hard-fail otherwise.
- **`BACKUP_DIR` creation tightened.** Use `install -d -m 700 -o root -g root` instead of `mkdir + chown + chmod`. Persist current backup path to `/root/hank-data-preebs-current` for rollback discoverability.
- **`findmnt` and `lsof/fuser` rollback checks** rewritten as explicit `if … fi` blocks with hard exit instead of `&& echo` warnings.
- **`cache` exclude anchored to repo root.** R4 noted `--exclude='cache'` matches any path component named `cache` (could affect future `data/corpus/cache` etc.). Changed to `--exclude='/cache'` (anchored to source root, only matches top-level `cache/`).

**v0.3 → v0.4 changes (Codex R3 FAIL response):**
- **`data/corpus/corpus.db` cut from scope.** Verified live on box: 0 bytes, empty, not opened by any production code path. Production corpus data lives in `data/filings.db`. The `corpus.db` file appears to be a stale placeholder. Removed all symlink / copy / verification steps for it. Migration is now: filings.db + filings/ + users/ only.
- **`.preebs` backups moved out of `REMOTE_DIR`.** v0.3 kept them under `/var/www/risk_module/data/` where `scripts/deploy.sh --delete` could remove them during the 24h backup window if any deploy fired. v0.4 stages them under `/var/backups/risk_module/hank-data-preebs-<timestamp>/` outside the rsync target. Owned by root, safe.
- **Removed all `2>/dev/null || true` patterns** that hid copy failures. Replaced with explicit `if [ -f ... ]` conditionals or hard-fail rsync (no error suppression).
- **Rollback unmount hardened.** Added `lsof +f -- /mnt/hank-data` and `fuser -vm` checks; `umount` runs without `|| true` so failures surface; `findmnt /mnt/hank-data` empty-verify before AWS detach/delete.
- **`cache/` added to `scripts/deploy.sh` excludes.** Local repo has 148 MB populated `cache/`; box doesn't (verified empty). Without exclude, first future deploy would push 148 MB of dev cache to prod and then `--delete` could clobber prod-generated cache files later.
- **Verified `RISK_MODULE_DATA_DIR` unset in prod.** R3 left this open due to sandbox SSH restriction. Confirmed via SSH this session — env var not set, CSV providers fall back to `~/.risk_module` (outside repo). CSV scope concern closed; documented in Appendix A.

**v0.2 → v0.3 changes (Codex R2 FAIL response):**
- **Cutover #1 hardened (already landed in this session).** Original deploy.sh excludes were insufficient. Now covers SQLite WAL/SHM sidecars (`*.db-wal`, `*.db-shm`), `data/brokerage-exports/`, `data/corpus/logs/`, `data/users/` (post-symlink protection), and switched to non-trailing-slash patterns to protect future symlinks. Verify: `grep -A20 'rsync -avz' scripts/deploy.sh`.
- **WAL checkpoint before copy** — Phase 3B now stops services, runs `lsof` to verify no open writers, executes `PRAGMA wal_checkpoint(TRUNCATE); PRAGMA integrity_check;`, then copies main DB + any remaining `-wal`/`-shm` sidecars. v0.2 missed this; would have left committed transactions in the WAL.
- **USER_DATA_DIR path corrected.** v0.2 set `USER_DATA_DIR=/var/www/risk_module/data/users` — wrong. AI-excel-addin's `api/memory/__init__.py:148-150` appends `users/<id>` itself, so v0.2 produces `data/users/users/<id>`. Correct value is `/var/www/risk_module/data` (the base — append happens in code).
- **Scope cut: DLM automation deferred.** Plan ships with one manual snapshot taken at end of cutover. Daily DLM lifecycle becomes a follow-up. Removes one moving piece from the cutover, doesn't change the EBS data layout.
- **Scope cut: `data/corpus/health/`, `data/backups/`, `data/brokerage-exports/`** stay on root volume (deploy-excluded). Out of EBS scope. They're regeneratable / low-value / inconsistently used; not worth migration churn.
- **Scope cut: CSV provider state.** `RISK_MODULE_DATA_DIR` (used by `providers/csv_*.py`) stays on root. CSV provider files (`positions.json`, `transactions.json`) are an import staging path; not user-data tier 2.
- **Rollback overhaul:** added `sudo systemctl revert` for drop-ins, `lsof` pre-unmount check, removed (now obsolete) DLM deletion steps, explicit post-24h copy-back sequence, env-var rollback notes.
- **Confirmed service user = `ubuntu`** for risk_module + edgar_api via `systemctl cat`. v0.2 assumed; v0.3 verified.

**v0.1 → v0.2 changes (Codex R1 FAIL response):** sequencing split, symlink approach, full path audit, boot ordering drop-ins, rollback rewrite, `skills/` removed, AWS command corrections, KMS-shipped→queued text fix.

---

## Motivation

risk_module's RDS migration shipped today (V4b.1, Phase 1A-D) — structured user data lives in `fmp-data-db` RDS. The KMS credentials migration (R6 PASS, queued) will move OAuth tokens / API keys into KMS-encrypted columns in the same RDS. But the **filesystem-shaped** data tier still lives on the EC2 root volume:

- `/var/www/risk_module/data/filings.db` (369 MB) — SEC filings cache (production corpus)
- `/var/www/risk_module/data/filings/` (300 MB) — raw filing markdown files (per-ticker subdirs)
- AI-excel-addin agent runtime (Phase 2C', not yet deployed) needs per-user SQLite at `data/users/<user_id>/...`

Three problems with status quo:

1. **Doesn't survive instance replacement.** Root volume `DeleteOnTermination=true` (default). Reprovisioning destroys the corpus cache.
2. **Clobbered by `scripts/deploy.sh`.** rsync `--delete` was removing files from the prod box that didn't exist locally. **Fixed in pre-KMS Cutover #1, this session.**
3. **Co-located with app code at the OS layer.** Code-vs-data lifecycle should be split.

Tier this out: code on root volume, filesystem-state on EBS, structured + credential data on RDS+KMS.

---

## Sequencing

| Order | Change | Status | Why this order |
|---|---|---|---|
| 1 | `scripts/deploy.sh` rsync exclude hardening | **DONE** (this session) | Stops the data-clobber bug from firing during KMS deploy |
| 2 | KMS credentials migration | R6 PASS, queued | Schema changes scoped to RDS only; no filesystem dependency |
| 3 | This plan (EBS migration) | v0.3 DRAFT | Final layer; no schema impact |

The deploy.sh hardening must NOT wait for EBS time, because every KMS-related deploy in between would re-trigger the clobber.

---

## Hard prerequisites

1. **KMS credentials migration deployed and verified.**
2. **AWS account access** — IAM permissions for EBS create/attach/modify, EBS snapshot create.
3. **Path audit complete** — see Appendix A. Every code path that reads/writes `data/...` either (a) resolves through `core/corpus/filings.py` helpers, (b) defaults via REPO_ROOT (works transparently with symlinks), or (c) is documented in Appendix A with explicit handling.
4. **EBS volume sized + provisioned** before service stop in Phase 3.
5. **Confirmed `User=ubuntu` for risk_module + edgar_api** via `systemctl cat`. Ownership of EBS volume must match.
6. **Confirmed Celery NOT running in prod.** `systemctl list-units` shows no celery services; no celery processes via `pgrep`. RabbitMQ inactive. If Celery is later deployed, the cutover plan must be amended to: (a) `service_stop celery_*` before Phase 3A, (b) add `RequiresMountsFor=/mnt/hank-data` to all celery service units, (c) `service_start celery_*` after Phase 3E, and (d) include celery DBs in the WAL checkpoint loop.

---

## Goal

By migration completion:

- `/mnt/hank-data` mounted on edgar-updater, backed by 50 GB gp3 EBS volume in us-east-2a, encrypted, `DeleteOnTermination=false`
- Production corpus DB + raw filings + per-user SQLite (when gateway lands) live on EBS
- Repo-relative paths (`data/filings.db`, `data/filings/`, `data/users/`) resolve through symlinks to EBS — **no source code changes required**
- Every systemd service that reads `/mnt/hank-data` declares `RequiresMountsFor=/mnt/hank-data`
- One manual snapshot taken post-cutover
- Pre-launch single user — same blast-radius profile as KMS migration

---

## Architecture

### Before (today, post-V4b.1, post-deploy.sh hardening)

```
EC2 edgar-updater (us-east-2a, t3a.medium, 4 GB RAM)
├── /dev/nvme0n1 (root, 20 GB, 11 GB free)
│   └── /var/www/risk_module/
│       ├── (app code, rsynced from repo, deploy.sh excludes mutable data)
│       └── data/
│           ├── filings.db          ← 369 MB, mutable (production corpus)
│           ├── filings/            ← 300 MB, mutable, per-ticker
│           └── corpus/
│               └── universe.json   ← tracked, ships via deploy
└── (no data volume)
```

### After

```
EC2 edgar-updater (us-east-2a, t3a.medium, 4 GB RAM)
├── /dev/nvme0n1 (root, 20 GB)
│   └── /var/www/risk_module/
│       ├── (app code)
│       └── data/                              ← preserved as a real directory
│           ├── filings.db -> /mnt/hank-data/risk_module/filings.db
│           ├── filings   -> /mnt/hank-data/risk_module/filings/
│           ├── corpus/
│           │   └── universe.json              ← real file, ships via deploy
│           └── users     -> /mnt/hank-data/risk_module/users/
├── /dev/nvme1n1 (NEW data, 50 GB gp3, encrypted, DoT=false)
│   └── /mnt/hank-data/
│       └── risk_module/
│           ├── filings.db
│           ├── filings/                      ← per-ticker raw markdown
│           └── users/<user_id>/              ← per-user SQLite (Phase 6)
└── (gateway service Phase 2C' — out of scope here)

External (unchanged):
└── RDS fmp-data-db (us-east-2a) ← structured user data + (post-KMS) encrypted creds
```

### Data tiering by sensitivity × replaceability

| Tier | Storage | Examples | Why |
|---|---|---|---|
| 1: Code (replaceable) | Root volume | App code, deps, `data/corpus/universe.json` | Rsynced on deploy; loss recoverable |
| 2: Filesystem state | `/mnt/hank-data` EBS | Corpus DB, raw filings, per-user SQLite | Encrypted at rest, snapshotted, isolated from deploy |
| 3: Structured + credential | RDS Postgres + KMS | Portfolios, positions, OAuth tokens, API keys | Network-isolated, KMS-encrypted columns |

### Why symlinks (not bind mounts, not env-var sweep)

- **Symlinks vs bind mounts:** symlinks are simpler — no per-directory fstab entries. SQLite/rsync/Python `pathlib` follow them transparently.
- **Symlinks vs env-var sweep:** sweep would touch CORPUS_ROOT, CORPUS_DB_PATH, USER_DATA_DIR, RESEARCH_WORKSPACE_DATA_DIR + argparse defaults in 8+ scripts. Each is a place where a path could drift. Symlinks let existing REPO_ROOT-relative defaults Just Work.
- **rsync risk:** `--delete` could remove a symlink if the source has nothing at that path. Mitigated by Cutover #1 excludes — symlinks live at the excluded paths, so rsync skips them. (Critical: excludes use non-trailing-slash patterns to match the symlink itself, not just directory contents.)

---

## Phase 1 — Provision EBS volume

### 1A. Create encrypted gp3 volume in us-east-2a

```bash
VOLUME_ID=$(aws ec2 create-volume \
  --region us-east-2 \
  --availability-zone us-east-2a \
  --size 50 \
  --volume-type gp3 \
  --iops 3000 \
  --throughput 125 \
  --encrypted \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=hank-data},{Key=Purpose,Value=corpus-and-user-data}]' \
  --query VolumeId --output text)
echo "Created volume: $VOLUME_ID"
```

### 1B. Wait for volume available

```bash
aws ec2 wait volume-available --region us-east-2 --volume-ids "$VOLUME_ID"
```

### 1C. Attach to edgar-updater as `/dev/sdf`

```bash
aws ec2 attach-volume \
  --region us-east-2 \
  --volume-id "$VOLUME_ID" \
  --instance-id i-0228d881348b290c7 \
  --device /dev/sdf

aws ec2 wait volume-in-use --region us-east-2 --volume-ids "$VOLUME_ID"
```

### 1D. Set DeleteOnTermination=false on the attachment

```bash
aws ec2 modify-instance-attribute \
  --region us-east-2 \
  --instance-id i-0228d881348b290c7 \
  --block-device-mappings "DeviceName=/dev/sdf,Ebs={VolumeId=$VOLUME_ID,DeleteOnTermination=false}"

aws ec2 describe-volumes \
  --region us-east-2 \
  --volume-ids "$VOLUME_ID" \
  --query 'Volumes[0].Attachments[0].DeleteOnTermination' --output text
# Expected: False
```

Per AWS docs, EBS volumes attached after instance launch via CLI default to **preserved** (`DeleteOnTermination=false`). Setting explicitly is idempotent + defensive.

---

## Phase 2 — Format, mount, boot ordering

### 2A. Format as ext4

```bash
ssh -i "$SSH_KEY" ubuntu@52.14.87.149
lsblk  # confirm device name (likely /dev/nvme1n1; varies)
sudo mkfs.ext4 -L hank-data /dev/nvme1n1
```

### 2B. Mount at `/mnt/hank-data` and persist via fstab

```bash
sudo mkdir -p /mnt/hank-data
sudo mount -L hank-data /mnt/hank-data
echo "LABEL=hank-data /mnt/hank-data ext4 defaults,nofail,x-systemd.device-timeout=10s 0 2" | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
```

`nofail` prevents boot from hanging if volume detaches. Services depending on the mount must declare `RequiresMountsFor=` (Phase 2D below).

### 2C. Layout directories + ownership

Service user is `ubuntu` (confirmed: `systemctl cat risk_module | grep User` → `User=ubuntu`).

```bash
sudo mkdir -p /mnt/hank-data/risk_module/{filings,users}
sudo chown -R ubuntu:ubuntu /mnt/hank-data/risk_module
sudo chmod 750 /mnt/hank-data/risk_module
```

Directory layout intentionally minimal: only what the production code paths actually use. No `corpus/` subdir — the `data/corpus/corpus.db` placeholder is a 0-byte file with no production readers (verified live).

### 2D. Add `RequiresMountsFor` drop-ins for services that read EBS

Services that touch `/mnt/hank-data` (currently: `risk_module`, `edgar_api`; Phase 6: `ai-agent-gateway`):

```bash
sudo systemctl edit risk_module
# Editor opens with override blank; add:
[Unit]
RequiresMountsFor=/mnt/hank-data

# Save + exit. Repeat for edgar_api (it also reads filings.db per Codex finding):
sudo systemctl edit edgar_api
# Same [Unit] / RequiresMountsFor block.

sudo systemctl daemon-reload
```

Verify drop-in active:
```bash
systemctl cat risk_module | grep -A1 RequiresMountsFor
systemctl cat edgar_api  | grep -A1 RequiresMountsFor
# Expected: RequiresMountsFor=/mnt/hank-data on each
```

`edgar_updater` (the webhook receiver) does NOT read corpus paths. Verify before assuming:
```bash
sudo grep -rE "data/(filings|corpus|users)" /var/www/edgar_updater/ 2>/dev/null | head
# If anything matches: add the drop-in to edgar_updater too.
```

---

## Phase 3 — Migrate existing data (cutover)

### 3A. Stop services that write under `data/` (with WAL safety)

```bash
sudo systemctl stop risk_module edgar_api
# Leave edgar_updater running (webhook receiver — verified does not read corpus paths).

# Verify no open SQLite writers remain. lsof returns 0 if there are matches, 1 if none:
sudo lsof /var/www/risk_module/data/filings.db && \
  { echo "ERROR: open handle on filings.db. Stop the offending process before continuing."; exit 1; } || \
  echo "filings.db has no open handles, OK."
```

If `lsof` shows writers, identify and stop them before continuing. Common culprits: cron jobs, manual `python3 scripts/corpus_*.py` invocations, future Celery workers (currently NOT deployed — see Hard Prerequisite #6).

### 3B. Checkpoint WAL, integrity-check, then copy

`core/corpus/db.py:20` enables `PRAGMA journal_mode=WAL`. The WAL file holds committed transactions until checkpointed back to the main DB. A naive `cp` of just the main DB loses unflushed WAL data.

PRAGMAs return success-as-result-row (not via process exit code), so we capture and assert each output:

```bash
set -euo pipefail
SRC=/var/www/risk_module/data/filings.db

# 1) WAL checkpoint. Result row format: "<status>|<wal_pages>|<checkpointed_pages>"
#    where status=0 means SQLITE_OK (checkpoint not blocked).
CHECKPOINT_RESULT=$(sudo sqlite3 "$SRC" "PRAGMA wal_checkpoint(TRUNCATE);")
echo "checkpoint result: $CHECKPOINT_RESULT"
STATUS=$(echo "$CHECKPOINT_RESULT" | awk -F'|' '{print $1}')
if [ "$STATUS" != "0" ]; then
  echo "ERROR: WAL checkpoint blocked (status=$STATUS). Stop and investigate."
  exit 1
fi

# 2) Integrity check. Output must be exactly 'ok' for a clean DB.
INTEGRITY=$(sudo sqlite3 "$SRC" "PRAGMA integrity_check;")
if [ "$INTEGRITY" != "ok" ]; then
  echo "ERROR: integrity_check returned: $INTEGRITY"
  exit 1
fi

# 3) Copy main DB + any remaining sidecars (post-checkpoint there should be none,
#    but the glob copies defensively):
sudo rsync -aP /var/www/risk_module/data/filings.db*  /mnt/hank-data/risk_module/
sudo rsync -aP /var/www/risk_module/data/filings/     /mnt/hank-data/risk_module/filings/

# 4) Verify byte-identical:
sudo cmp /var/www/risk_module/data/filings.db /mnt/hank-data/risk_module/filings.db
echo "filings.db byte-identical OK"

sudo diff -rq /var/www/risk_module/data/filings/ /mnt/hank-data/risk_module/filings/
# Expected: no output (no diffs). Any diff lines → STOP.

# 5) Re-run integrity check on EBS copy:
EBS_INTEGRITY=$(sudo sqlite3 /mnt/hank-data/risk_module/filings.db "PRAGMA integrity_check;")
if [ "$EBS_INTEGRITY" != "ok" ]; then
  echo "ERROR: EBS integrity_check returned: $EBS_INTEGRITY"
  exit 1
fi

# 6) Fix ownership on EBS copies:
sudo chown -R ubuntu:ubuntu /mnt/hank-data/risk_module/
```

### 3C. Cutover via move-aside-then-symlink

Move originals OUT of `REMOTE_DIR` to `/var/backups/risk_module/` (so a future deploy can't `--delete` them during the 24h backup window), then symlink to EBS:

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="/var/backups/risk_module/hank-data-preebs-$TS"
sudo install -d -m 700 -o root -g root /var/backups/risk_module
sudo install -d -m 700 -o root -g root "$BACKUP_DIR"

# Persist current backup path for rollback discoverability:
echo "$BACKUP_DIR" | sudo tee /root/hank-data-preebs-current >/dev/null

cd /var/www/risk_module/data

# filings.db: move to backup, symlink to EBS:
sudo mv filings.db "$BACKUP_DIR/filings.db"
sudo ln -s /mnt/hank-data/risk_module/filings.db filings.db
# Sidecar files (-wal, -shm) are recreated by SQLite on next open; no symlink needed.

# filings/: move to backup, symlink to EBS:
sudo mv filings "$BACKUP_DIR/filings"
sudo ln -s /mnt/hank-data/risk_module/filings filings

# Per-user data directory (gateway uses this in Phase 6):
if [ -d users ] && [ ! -L users ]; then
  sudo mv users "$BACKUP_DIR/users"
fi
sudo ln -s /mnt/hank-data/risk_module/users users

# universe.json stays as-is — real file, tracked in repo, on root volume.
# corpus/ subdirectory: NOT migrated (corpus.db was 0-byte placeholder, no production use).

# Symlink ownership (chown -h applies to the symlink itself, not the target):
sudo chown -h ubuntu:ubuntu filings.db filings users

echo "Pre-EBS backups staged at: $BACKUP_DIR"
```

Verify:
```bash
ls -la /var/www/risk_module/data/
# Expected: 3 symlinks (filings.db, filings, users) + corpus/ dir (containing universe.json)

sudo ls -la "$BACKUP_DIR"
# Expected: filings.db, filings/ (and possibly users/ if it pre-existed)
```

### 3D. (No `.env` changes required for this plan)

The symlink approach means existing path resolution Just Works. No env vars need setting in this plan.

For the future gateway (Phase 6, out of scope here): `USER_DATA_DIR=/var/www/risk_module/data` (NOT `/data/users` — AI-excel-addin's `api/memory/__init__.py:148-150` appends `users/<id>` itself). Or equivalently `USER_DATA_DIR=/mnt/hank-data/risk_module` — same inode via symlink.

### 3E. Restart services

```bash
sudo systemctl start risk_module edgar_api
sudo systemctl status risk_module edgar_api --no-pager | head -30
journalctl -u risk_module -n 50 --no-pager | grep -iE 'error|fail|missing' | head
journalctl -u edgar_api -n 50 --no-pager | grep -iE 'error|fail|missing' | head
```

### 3F. Smoke test

```bash
# From local machine:
curl -s -c /tmp/hank_cookies.txt -X POST https://<ec2-host>/auth/dev-login
curl -s -b /tmp/hank_cookies.txt https://<ec2-host>/api/research/content/files | python3 -m json.tool
curl -s https://<ec2-host>/api/health | python3 -m json.tool

# Validate corpus reads (hits filings.db):
curl -s -b /tmp/hank_cookies.txt -X POST https://<ec2-host>/api/portfolio/risk_score -d '{}'
# Expected: green response, no 'filings.db missing' errors in journalctl
```

### 3G. Take initial manual EBS snapshot

```bash
SNAPSHOT_ID=$(aws ec2 create-snapshot \
  --region us-east-2 \
  --volume-id "$VOLUME_ID" \
  --description "hank-data initial post-cutover snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --tag-specifications "ResourceType=snapshot,Tags=[{Key=Name,Value=hank-data-initial}]" \
  --query SnapshotId --output text)
echo "Initial snapshot: $SNAPSHOT_ID"

aws ec2 wait snapshot-completed --region us-east-2 --snapshot-ids "$SNAPSHOT_ID"
```

DLM lifecycle policy automation is **out of scope for this plan** — tracked as a follow-up. Manual snapshot here gives a known-good restore point.

### 3H. Wait 24 hours, then delete pre-EBS backup directory

```bash
BACKUP_DIR=$(sudo cat /root/hank-data-preebs-current)
sudo rm -rf "$BACKUP_DIR"
sudo rm /root/hank-data-preebs-current
```

The 24-hour delay gives time for issues to surface with cheap rollback available. Backup directory is outside `REMOTE_DIR`, so any deploys during the window cannot accidentally clobber it.

---

## Phase 4 — (Out of scope) DLM lifecycle automation

Tracked as a follow-up plan. After the EBS migration is verified stable, set up daily snapshot lifecycle via `aws dlm create-default-role` + `create-lifecycle-policy`. Not on the cutover path because:
- Manual snapshot in 3G covers the initial restore point.
- DLM setup has its own failure modes (IAM role, policy syntax, tag matching) that shouldn't share a cutover window with the data migration.

---

## Phase 5 — (Out of scope) AI-excel-addin gateway deployment

Phase 2C' from `MULTI_USER_DEPLOYMENT_PLAN.md` is unblocked once `/mnt/hank-data/risk_module/users/` exists (Phase 2C above). Tracked separately.

When that work happens, the gateway's systemd unit must include:
- `[Unit] RequiresMountsFor=/mnt/hank-data`
- Env: `USER_DATA_DIR=/var/www/risk_module/data` (base — AI-excel-addin appends `users/<id>` per `api/memory/__init__.py:148-150`)
- Optionally `RESEARCH_WORKSPACE_DATA_DIR` if want to override default fallback to `USER_DATA_DIR`

Skill definitions ship with the PyPI package source, NOT loaded from `USER_DATA_DIR` (verified `api/memory/__init__.py:54`). No skills directory on EBS.

---

## Verification checklist

- [ ] EBS volume created, encrypted, `DeleteOnTermination=false` confirmed via `describe-volumes`
- [ ] `/mnt/hank-data` mounted, persists across reboot (test: `sudo reboot`, wait, SSH back, `df -h /mnt/hank-data`)
- [ ] All 3 symlinks correct: `ls -la /var/www/risk_module/data/` shows symlinks for `filings.db`, `filings`, `users` (no `corpus/corpus.db` symlink — corpus.db cut from scope)
- [ ] `du -sh /mnt/hank-data/risk_module/` ≈ pre-migration size (~669 MB)
- [ ] SQLite integrity OK on EBS: `sqlite3 /mnt/hank-data/risk_module/filings.db 'PRAGMA integrity_check;'` returns `ok`
- [ ] `risk_module` and `edgar_api` services started cleanly post-cutover; no path-related errors in journalctl
- [ ] `RequiresMountsFor=/mnt/hank-data` present in `systemctl cat risk_module` and `systemctl cat edgar_api`
- [ ] `/api/health` returns ok
- [ ] `/api/research/content/files` returns content list (validates corpus path)
- [ ] At least one risk-score / portfolio-analysis API call succeeds (validates filings.db reachability)
- [ ] Initial manual snapshot exists in `aws ec2 describe-snapshots`
- [ ] `bash scripts/deploy.sh` no-op deploy: rsync excludes `data/filings.db`, `-wal`, `-shm`, `data/filings`, `data/users`, `cache`, etc.
- [ ] `data/corpus/universe.json` still ships during deploy (verify in rsync output)
- [ ] `df -h /` shows ~7-8 GB freed on root volume
- [ ] `$BACKUP_DIR` exists and contains pre-migration data (`/var/backups/risk_module/hank-data-preebs-<ts>/`)
- [ ] After 24h: `$BACKUP_DIR` removed (Phase 3H)

---

## Rollback

### If Phase 1 or 2 fails (volume creation, attach, mount, format)

No data has moved yet. Clean up:

```bash
# Hard-fail if anything is using the mount (lsof returns 0 on match):
if sudo lsof +f -- /mnt/hank-data 2>/dev/null; then
  echo "ERROR: open handles on /mnt/hank-data. Stop offenders before continuing."
  exit 1
fi
if sudo fuser -vm /mnt/hank-data 2>/dev/null; then
  echo "ERROR: processes using /mnt/hank-data. Stop them before continuing."
  exit 1
fi

# Unmount (no || true — failure surfaces):
sudo umount /mnt/hank-data

# Verify unmounted:
if sudo findmnt /mnt/hank-data >/dev/null; then
  echo "ERROR: /mnt/hank-data still mounted after umount"
  exit 1
fi

sudo sed -i '/hank-data/d' /etc/fstab
sudo systemctl daemon-reload
sudo systemctl revert risk_module edgar_api  # remove RequiresMountsFor drop-ins

aws ec2 detach-volume --region us-east-2 --volume-id "$VOLUME_ID"
aws ec2 wait volume-available --region us-east-2 --volume-ids "$VOLUME_ID"
aws ec2 delete-volume --region us-east-2 --volume-id "$VOLUME_ID"
```

### If Phase 3 cutover fails (services don't restart, corpus reads fail)

Symlinks + `$BACKUP_DIR` make this clean:

```bash
set -euo pipefail
sudo systemctl stop risk_module edgar_api
cd /var/www/risk_module/data

# Load backup path from marker file:
BACKUP_DIR=$(sudo cat /root/hank-data-preebs-current)

# Remove symlinks (they're the only things that should exist post-Phase 3C):
sudo rm filings.db filings users

# Restore from backup directory:
sudo mv "$BACKUP_DIR/filings.db" filings.db
sudo mv "$BACKUP_DIR/filings"    filings
if [ -d "$BACKUP_DIR/users" ]; then
  sudo mv "$BACKUP_DIR/users" users
else
  sudo mkdir -p users
  sudo chown ubuntu:ubuntu users
fi

sudo systemctl start risk_module edgar_api
sudo systemctl status risk_module edgar_api
# Verify green.

# Once stable, remove the (now-empty) backup directory + marker:
sudo rmdir "$BACKUP_DIR"
sudo rm /root/hank-data-preebs-current
```

Then unwind EBS volume (Phase 1/2 rollback above).

### Post-Phase 3H rollback (after backup directory removal)

If issues surface AFTER 24h and `$BACKUP_DIR` is gone, copy data back from EBS to root:

```bash
sudo systemctl stop risk_module edgar_api
cd /var/www/risk_module/data

# Verify nothing has the EBS paths open. lsof returns 0 on match (problem):
sudo lsof /mnt/hank-data/risk_module/filings.db && \
  { echo "ERROR: open handle on EBS filings.db. Stop offender first."; exit 1; }
echo "filings.db has no open handles, OK."

# Checkpoint EBS-side WAL with assertion (hard-fail on error):
CHECKPOINT_RESULT=$(sudo sqlite3 /mnt/hank-data/risk_module/filings.db "PRAGMA wal_checkpoint(TRUNCATE);")
STATUS=$(echo "$CHECKPOINT_RESULT" | awk -F'|' '{print $1}')
if [ "$STATUS" != "0" ]; then
  echo "ERROR: WAL checkpoint blocked on EBS-side filings.db (status=$STATUS)"
  exit 1
fi

INTEGRITY=$(sudo sqlite3 /mnt/hank-data/risk_module/filings.db "PRAGMA integrity_check;")
if [ "$INTEGRITY" != "ok" ]; then
  echo "ERROR: integrity_check on EBS-side filings.db returned: $INTEGRITY"
  exit 1
fi

# Remove symlinks:
sudo rm filings.db filings users

# Copy from EBS back to root:
sudo rsync -aP /mnt/hank-data/risk_module/filings.db*  .
sudo rsync -aP /mnt/hank-data/risk_module/filings/     filings/
sudo mkdir -p users
sudo chown -R ubuntu:ubuntu /var/www/risk_module/data/

# Verify byte-identical:
sudo cmp /var/www/risk_module/data/filings.db /mnt/hank-data/risk_module/filings.db
echo "filings.db byte-identical OK"

sudo systemctl start risk_module edgar_api
sudo systemctl status risk_module edgar_api
```

Then unwind EBS volume (Phase 1/2 rollback above).

### Cleanup snapshots if rolling back

```bash
aws ec2 delete-snapshot --region us-east-2 --snapshot-id "$SNAPSHOT_ID"
```

---

## Open decisions

1. **Volume size.** 50 GB gp3 chosen. Storage cheap; resizing later requires modify + filesystem grow (online but operational friction).
2. **Mount point.** `/mnt/hank-data`. Bikeshed.

---

## Estimated cost impact

- 50 GB gp3 in us-east-2: $0.08/GB/mo = **$4/mo**
- Initial manual snapshot: ~669 MB compressed → S3 snapshot pricing $0.05/GB/mo. **<$0.10/mo.**
- DLM lifecycle (when added later): ~$0.50–1/mo for 7 daily incrementals.
- **Total this plan: ~$4/mo additional.**

---

## Out of scope (cut from v0.2)

- DLM lifecycle automation (deferred to follow-up; one manual snapshot in 3G covers initial restore point)
- `data/corpus/corpus.db` — 0-byte placeholder, no production readers (verified). Cut entirely.
- `data/corpus/health/`, `data/backups/`, `data/brokerage-exports/` migration — stay on root, deploy-excluded
- CSV provider state — `RISK_MODULE_DATA_DIR` not set in prod env (verified); CSV providers fall back to `~/.risk_module` outside repo. No migration needed.
- `cache/fmp/`, `cache/ibkr/`, `cache/ibkr_timeseries/` — separate decision; regeneratable, low priority
- AI-excel-addin gateway deployment itself (Phase 2C' in `MULTI_USER_DEPLOYMENT_PLAN.md`)
- nginx + frontend deployment (Phase 2D)
- Multi-AZ resilience for the EBS volume
- Cross-account/cross-region snapshot replication

---

## Appendix A — Path audit

Every code path that defaults to `data/...` paths in risk_module:

| Path | Default | Override env | Affected by symlink approach? | Notes |
|---|---|---|---|---|
| `data/filings.db` | `core/corpus/filings.py:47` (REPO_ROOT-relative) | `CORPUS_DB_PATH` | ✓ resolves through symlink | Primary corpus DB |
| `data/filings.db` | `core/corpus/transcripts.py:29` | `CORPUS_DB_PATH` | ✓ resolves through symlink | Same DB, different module |
| `data/filings.db` | `workers/tasks/corpus.py:18` (`Path('data/filings.db')`) | none — used as-is | ✓ resolves through symlink (CWD = `/var/www/risk_module`) | Worker task |
| `data/filings.db` | 8+ scripts in `scripts/corpus_*.py` | argparse `--db` | ✓ resolves through symlink | CLI defaults |
| `data/filings/` | `core/corpus/filings.py:46`, `core/corpus/transcripts.py:28` | `CORPUS_ROOT` | ✓ resolves through symlink | Raw markdown |
| `data/filings/` | `workers/tasks/corpus.py:20` | none | ✓ resolves through symlink | Worker task |
| `data/corpus/universe.json` | `scripts/corpus_*.py` | argparse `--universe` | ✗ tracked file, on root | NOT migrated |
| `data/corpus/corpus.db` | (test only — `tests/canary/`) | `CORPUS_CANARY_DB` | ✗ NOT migrated (0-byte placeholder; no production readers) | Test canary only |
| `data/corpus/health/` | `scripts/corpus_health_report.py:19` | argparse `--out-dir` | ✗ stays on root (out of scope) | Health reports |
| `data/backups/` | `scripts/corpus_backup.py:10` | argparse `--backup-dir` | ✗ stays on root (out of scope) | Corpus backups |
| `data/transactions.json` (CSV provider) | `providers/csv_transactions.py:240` | `RISK_MODULE_DATA_DIR` falls back to `~/.risk_module` | ✗ stays on root (out of scope) | CSV import |
| `data/positions.json` (CSV provider) | `providers/csv_positions.py:100` | `RISK_MODULE_DATA_DIR` (same) | ✗ stays on root (out of scope) | CSV import |

**Other env vars touching the filesystem (NOT affected by EBS migration — separate concerns):**

| Env var | Default | What it controls | In/out of EBS scope |
|---|---|---|---|
| `LOG_DIR` | `logs/` | App logs | OUT — root, deploy-excluded |
| `FMP_CACHE_DIR` | `cache/fmp/` | FMP API response cache | OUT — root, regeneratable |
| `IBKR_CACHE_DIR` | `cache/ibkr/` | IBKR API cache | OUT — root, regeneratable |
| `IBKR_TIMESERIES_CACHE_DIR` | `cache/ibkr_timeseries/` | IBKR timeseries | OUT — root, regeneratable |
| `IBKR_STATEMENT_DB_PATH` | empty | IBKR Flex DB | OUT — op-specific |
| `SCHWAB_TOKEN_PATH` | `~/.schwab_token.json` | OAuth token | OUT — outside repo |

**AI-excel-addin path resolution (verified 2026-04-30):**

| Module | Path config | Effective path with `USER_DATA_DIR=/var/www/risk_module/data` |
|---|---|---|
| `api/memory/__init__.py:148-150` | `_default_data_dir() / "users" / <id>` where `_default_data_dir()` = `USER_DATA_DIR` | `/var/www/risk_module/data/users/<id>` ✓ |
| `api/research/repository.py:376` | `RESEARCH_WORKSPACE_DATA_DIR` falls back to `USER_DATA_DIR` (then appends `users/<id>` similar) | same |
| `api/memory/__init__.py:54` (skills) | loads from package source | NOT user-data, NOT migrated |

Effective `USER_DATA_DIR` value: **`/var/www/risk_module/data`** (the base directory; AI-excel-addin appends `users/<user_id>` itself). Plan v0.2 had this wrong as `/var/www/risk_module/data/users` which would have produced `/data/users/users/<id>`.

**Deploy.sh excludes (live, post-Cutover #1, post-R3 hardening):**
```
--exclude='/cache'                   ← Codex R3+R4 (anchored to repo root; 148 MB local cache; box doesn't have one)
--exclude='data/filings.db'
--exclude='data/filings.db-wal'      ← SQLite WAL sidecar (Codex R2)
--exclude='data/filings.db-shm'      ← SQLite SHM sidecar (Codex R2)
--exclude='data/filings'             ← non-trailing-slash; protects symlink (Codex R2)
--exclude='data/corpus/corpus.db'
--exclude='data/corpus/corpus.db-wal'
--exclude='data/corpus/corpus.db-shm'
--exclude='data/corpus/health'
--exclude='data/corpus/logs'         ← Codex R2
--exclude='data/backups'
--exclude='data/brokerage-exports'   ← Codex R2
--exclude='data/users'               ← Codex R2 (post-symlink protection)
```
Tracked file `data/corpus/universe.json` continues to ship via deploy. Pre-EBS backups stage to `/var/backups/risk_module/` outside `REMOTE_DIR`, so they cannot be touched by deploy `--delete`.
