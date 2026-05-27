# F159 Deploy Runbook

**Plan**: `docs/planning/F159_CORPUS_PATH_RESOLVE_PLAN.md` (Codex R4 PASS)
**Code commit**: `457e8ac3` (`corpus(F159): drop .resolve() from write paths`)
**Date**: 2026-05-27
**Status**: CODEX R7 PASS 2026-05-27 — ready for execution

**R6 changes**:
- `Result=success` is not strict enough — the unit has `SuccessExitStatus=75` (lock-unavailable), so a lock-blocked run can report Result=success without doing work. R6 requires BOTH `Result=success` AND `ExecMainStatus=0` (proves the script returned 0, not exit 75)
- Reordered: writers stay stopped through Step 7/7b verification (was Step 8/8b before reorder), resume only AFTER verification completes in new Step 8. Prevents the daily timer / Celery from producing unrelated rows that would falsely satisfy the `new_docs > 0` predicate

**R5 changes**:
- Step 8 service `Result` check is now a HARD gate (R4 was advisory WARN-only — could pass with a failed service that happened to produce one good row). R5 captures `Result` into a shell variable and forwards it into the Python verifier's PASS predicate; PASS requires both `service_result=success` AND path/write checks pass

**R4 changes**:
- Step 8 false-PASS hole — R3 only checked `/filings_v1/` paths on `status='complete' AND content_changed=1` log rows, but `new_file_path` is written at `planned` state too. A non-complete row (planned/new_written/failed) could carry a bad path and Step 8 would PASS if a new filing was also inserted. R4 scans ALL `new_log_rows` for bad paths (independent of status), AND inspects `corpus_delta_ingest.service` `Result` for success, AND keeps `complete + content_changed=1` as the separate proof that the DB-upsert path was exercised

**R3 changes**:
- Step 3 — `systemctl is-active` misses `Type=oneshot` services in `activating` state. R3 polls `systemctl show -P ActiveState` and waits for exactly `inactive` or `failed`
- Step 8 — actually uses the captured `pre_trigger_count` + trigger timestamp instead of ignoring them. The "last 1 hour" filter compared ISO `T...Z` against SQLite's `YYYY-MM-DD HH:MM:SS` and could match same-day-already-repaired rows. R3 query filters by `documents` row count delta AND inspects rows by stored `extraction_at` lexicographic comparison with the captured timestamp (works for ISO `T...Z` form)
- Step 8b — `reingest_one` returns `no_change` if content hash matches, never exercising the write path. R3 canary verifies via the `corpus_reingest_log` entry (must show `status='complete'` AND `content_changed=1` OR the new row was inserted) rather than just inspecting the final document row

**R2 changes**:
- Fixed Celery drain loop (R1 was `while ! cd && ...` which exits on cd success; now uses proper polling against `inspect active` + `inspect reserved`)
- Step 3 now actually polls for systemd service inactive, not just one status check
- Step 6 repair script: `db.commit()` moved AFTER post-repair verification, with explicit rollback on failure (R1 committed first, turning a verification failure into an EBS-restore event)
- Step 6 DB path: uses `/mnt/hank-data/risk_module/filings.db` (the symlink, same as systemd services), with explicit `readlink` validation before opening
- Step 8 log path corrected to `/var/www/risk_module/logs/corpus/delta_<date>.jsonl` (was wrong in R1)
- Step 8 adds canary write to avoid false-pass when delta produces zero new rows
- Step 9 split: `--dry-run` stays as F159 unblock proof; `--execute` deferred to separate F158 session
- Rollback: capture `PRE_DEPLOY_HEAD=$(git rev-parse HEAD)` before pull instead of `HEAD~1`
- Non-terminal log row explanation corrected — Step 6's log-table repair is what makes recovery safe (the F159 fix alone does not retroactively rewrite log columns)
- Step 6 expected count corrected to 125 (was confused "84-105")
- `lsof` check expanded to include symlink + target + WAL/SHM sidecars

This is the operator-side execution checklist for plan §7. Each step has explicit verification gates. Destructive steps (stop services, SQL UPDATE) are marked **[CONFIRM]** — agent pauses, operator approves, then proceed.

---

## SSH context

```bash
export SSH_KEY=/Users/henrychien/Documents/Jupyter/Edgar_updater/edgar-updater-key.pem
export EC2_HOST=ubuntu@3.139.124.134
export REMOTE_DIR=/var/www/risk_module
export REMOTE_DATA=/mnt/hank-data/risk_module
alias prod="ssh -i $SSH_KEY -o BatchMode=yes -o ConnectTimeout=10 $EC2_HOST"
```

---

## Step 0 — Push code to GitHub

Read-only on remote; local push only.

```bash
git push origin main
```

**Verify**: `git log origin/main..HEAD` returns empty.

---

## Step 1 — Pre-deploy snapshot ⚠️ [CONFIRM]

Trigger explicit EBS snapshot of the `hank-data` volume. Beyond DLM cadence so we have a known-good rollback covering both the DB and `filings_v1/` contents.

```bash
# Get the volume ID first
prod "df -h /mnt/hank-data && lsblk -o NAME,MOUNTPOINT,SIZE"
# Then via AWS CLI from local (or operator runs from console):
aws ec2 create-snapshot \
  --volume-id <vol-XXXXXXXX> \
  --description "F159 pre-repair snapshot 2026-05-27" \
  --tag-specifications 'ResourceType=snapshot,Tags=[{Key=Name,Value=hank-data-f159-pre-repair}]'
```

**Verify**: snapshot ID returned; `aws ec2 describe-snapshots --snapshot-ids <snap-XXXX>` shows `State=pending` → wait for `completed` before proceeding.

---

## Step 2 — Inspect Celery state (read-only)

Per plan §7 step 6b — verify Celery is OFF before deciding stop sequence.

```bash
prod "cd $REMOTE_DIR && grep -E '^(CELERY_ENABLED|CORPUS_BEAT_ENABLED)' .env 2>/dev/null || echo 'env vars unset'"
prod "systemctl is-active celery_beat celery_worker_maint 2>&1 || true"
prod "pgrep -af 'celery.*(worker|beat)' || echo 'no celery processes'"
prod "cd $REMOTE_DIR && timeout 5 venv/bin/python3 -m celery -A workers.celery_app.app inspect active -d maint@\$(hostname) 2>&1 || echo 'celery unreachable (expected if disabled)'"
prod "cd $REMOTE_DIR && timeout 5 venv/bin/python3 -m celery -A workers.celery_app.app inspect reserved -d maint@\$(hostname) 2>&1 || echo 'celery unreachable (expected if disabled)'"
```

**Decision gate:**
- All four checks empty/inactive → **proceed to Step 3 (no Celery action needed)**
- Any check shows live Celery → **Step 2.5 stop-and-drain branch**

### Step 2.5 — Stop and drain Celery (only if needed) ⚠️ [CONFIRM]

R2 note: R1's drain loop was broken — `while ! cd ... && ...` exits as soon as `cd` succeeds, never inspecting tasks. R2 uses an explicit JSON-output poll against BOTH `active` and `reserved`.

```bash
# Stop beat first to prevent new corpus jobs from queuing
prod "sudo systemctl stop celery_beat"

# Wait for in-flight + reserved jobs to fully drain — JSON output for reliable parsing
prod "cd $REMOTE_DIR && while true; do
  active=\$(timeout 10 venv/bin/python3 -m celery -A workers.celery_app.app inspect active -d maint@\$(hostname) --json 2>/dev/null | venv/bin/python3 -c 'import sys,json; d=json.load(sys.stdin); print(sum(len(v) for v in d.values()))' 2>/dev/null || echo 'unreachable')
  reserved=\$(timeout 10 venv/bin/python3 -m celery -A workers.celery_app.app inspect reserved -d maint@\$(hostname) --json 2>/dev/null | venv/bin/python3 -c 'import sys,json; d=json.load(sys.stdin); print(sum(len(v) for v in d.values()))' 2>/dev/null || echo 'unreachable')
  echo \"active=\$active reserved=\$reserved\"
  if [ \"\$active\" = '0' ] && [ \"\$reserved\" = '0' ]; then break; fi
  if [ \"\$active\" = 'unreachable' ] && [ \"\$reserved\" = 'unreachable' ]; then echo 'WARN: celery unreachable during drain — verify worker actually stopped via pgrep before proceeding'; break; fi
  sleep 5
done"

# Stop maint worker
prod "sudo systemctl stop celery_worker_maint"

# Confirm worker process really gone (in case 'unreachable' was misleading above)
prod "pgrep -af 'celery.*(worker|beat)' && echo 'WARN: celery process still running' || echo 'all celery processes stopped'"
```

---

## Step 3 — Stop systemd corpus timers ⚠️ [CONFIRM]

R2: actual poll loop instead of single status check.

```bash
prod "sudo systemctl stop corpus_delta_ingest.timer corpus_transcripts_delta.timer"
prod "sudo systemctl status corpus_delta_ingest.timer corpus_transcripts_delta.timer --no-pager | head -10"

# Poll until both services exit their active/activating state.
# R3: corpus services are Type=oneshot — a running one-shot may be `activating`,
# not `active`, so `is-active --quiet` can return false while ingest is still
# running. Use `systemctl show -P ActiveState` which returns the actual state.
prod "for svc in corpus_delta_ingest.service corpus_transcripts_delta.service; do
  while :; do
    state=\$(systemctl show -P ActiveState \"\$svc\")
    case \"\$state\" in
      inactive|failed)
        echo \"\$svc: \$state\"
        break
        ;;
      *)
        echo \"waiting for \$svc (state=\$state)...\"
        sleep 5
        ;;
    esac
  done
done"
```

**Verify**: both timers show `Active: inactive (dead)`. Both services in state `inactive` or `failed` (either is fine — just not `active` or `activating`).

---

## Step 4 — Inspect non-terminal log rows (read-only)

Per plan §7 step 7 — handle in-flight reingest before code deploy.

```bash
prod "cd $REMOTE_DIR && venv/bin/python3 -c \"
import sqlite3
db = sqlite3.connect('$REMOTE_DATA/filings_v1.db')
rows = db.execute('''SELECT id, status, ticker, source_accession FROM corpus_reingest_log
WHERE status NOT IN ('complete','no_change','abandoned')
ORDER BY started_at DESC LIMIT 50''').fetchall()
print(f'non_terminal_count={len(rows)}')
for r in rows: print(r)
\""
```

**Decision gate:**
- Empty → proceed to Step 5
- Non-empty → consult plan §9 Q3. R2 correction: `normalize_corpus_path` does NOT retroactively convert existing `/filings_v1/` paths in log columns to `/filings/`. The Step 6 log-table repair IS what makes recovery safe. Two options:
  - **Preferred:** mark non-terminal rows as `abandoned` via SQL before deploy. They were transient anyway, and abandoning avoids any recovery-path entanglement.
  - **Alternative:** proceed to Step 5 with non-terminal rows in place. Step 6's log-table repair will rewrite their paths to symlink form, and post-deploy `recover_pending` will then process them safely under the NEW code with symlink-form paths.

---

## Step 5 — Deploy code to prod ⚠️ [CONFIRM]

R2: capture pre-deploy SHA for reliable rollback.

```bash
# Capture pre-deploy state for clean rollback
prod "cd $REMOTE_DIR && git rev-parse HEAD" | tee /tmp/f159_pre_deploy_head.txt
# Inspect what's about to land
prod "cd $REMOTE_DIR && git fetch origin && git log --oneline HEAD..origin/main | head -5"
prod "cd $REMOTE_DIR && git status --short"
# Pull
prod "cd $REMOTE_DIR && git pull origin main"
prod "cd $REMOTE_DIR && git log --oneline -1"
# Should show 457e8ac3 or descendant
```

**Verify**: prod HEAD includes `457e8ac3`. No conflicts. `git status` clean.

```bash
prod "sudo systemctl restart risk_module"
prod "sudo systemctl status risk_module --no-pager | head -10"
prod "curl -sf http://localhost:5001/api/health | head -5 || echo 'health check failed'"
```

**Verify**: `risk_module` service `Active: active (running)`, health endpoint returns 200.

**Other readers** (per plan §9 Q2): R2 expanded `lsof` check covers symlink + target + WAL/SHM sidecars.

```bash
# Check both symlink and version-target paths, plus WAL/SHM sidecars
prod "sudo lsof $REMOTE_DATA/filings.db $REMOTE_DATA/filings_v1.db $REMOTE_DATA/filings.db-wal $REMOTE_DATA/filings_v1.db-wal $REMOTE_DATA/filings.db-shm $REMOTE_DATA/filings_v1.db-shm 2>&1 | head -20"
```

**Verify**:
- `risk_module` read handles → acceptable (post-restart, will be on new code)
- `edgar_api` handles → if `edgar_api` doesn't import `core.corpus` write paths it's read-only and OK; if uncertain, restart it (`sudo systemctl restart edgar_api`)
- Anything else (workers, scripts) → investigate before proceeding

---

## Step 6 — Run prod SQL repair under flock ⚠️⚠️ [CONFIRM — DESTRUCTIVE]

Per plan §6. Holds the same `/run/corpus_promote.lock` as promote/pull/ingest. SQL inside `BEGIN IMMEDIATE` transaction.

**R2 critical changes:**
- DB path is `/mnt/hank-data/risk_module/filings.db` (the symlink — same as systemd services), NOT `filings_v1.db` directly. Adds an explicit `readlink` validation before opening.
- `db.commit()` moved AFTER post-repair verification, with explicit rollback on failure. R1 committed first, turning a verification failure into an EBS-restore event unnecessarily.

Build the repair script on prod first (operator can read before executing):

```bash
prod "cat > /tmp/f159_repair.py <<'PYEOF'
import os
import sqlite3
import sys

# Use the symlink path (same as systemd services). Validate it points where we expect.
DB_SYMLINK = '/mnt/hank-data/risk_module/filings.db'
EXPECTED_TARGET = 'filings_v1.db'  # relative symlink target per CORPUS_DEPLOYMENT_DESIGN.md §2.3
BAD = '/mnt/hank-data/risk_module/filings_v1/'
GOOD = '/mnt/hank-data/risk_module/filings/'

# Step 0: symlink sanity check
if os.path.islink(DB_SYMLINK):
    target = os.readlink(DB_SYMLINK)
    print(f'symlink: {DB_SYMLINK} -> {target}')
    if target != EXPECTED_TARGET:
        print(f'FAIL: symlink target {target!r} != expected {EXPECTED_TARGET!r} (operator must verify state before proceeding)')
        sys.exit(2)
else:
    print(f'FAIL: {DB_SYMLINK} is not a symlink — corpus layout may have drifted')
    sys.exit(2)

db = sqlite3.connect(DB_SYMLINK, timeout=30.0)
db.row_factory = sqlite3.Row
try:
    # Step 1: Pre-repair snapshot
    print('=== PRE-REPAIR ===')
    pre_counts = {}
    for tbl, col in [('documents','file_path'),('corpus_reingest_log','old_file_path'),('corpus_reingest_log','new_file_path')]:
        n = db.execute(f\"SELECT COUNT(*) FROM {tbl} WHERE SUBSTR({col},1,LENGTH(?))=?\", (BAD, BAD)).fetchone()[0]
        g = db.execute(f\"SELECT COUNT(*) FROM {tbl} WHERE SUBSTR({col},1,LENGTH(?))=?\", (GOOD, GOOD)).fetchone()[0]
        total = db.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]
        pre_counts[(tbl, col)] = n
        print(f'  {tbl}.{col}: bad={n} good={g} total={total}')

    # Step 2: Repair inside BEGIN IMMEDIATE — DO NOT COMMIT YET
    print('=== REPAIRING ===')
    db.execute('BEGIN IMMEDIATE')
    try:
        c1 = db.execute('UPDATE documents SET file_path = ? || SUBSTR(file_path, LENGTH(?)+1) WHERE SUBSTR(file_path,1,LENGTH(?))=?',
                        (GOOD, BAD, BAD, BAD))
        print(f'  documents updated: {c1.rowcount}')
        c2 = db.execute('UPDATE corpus_reingest_log SET old_file_path = ? || SUBSTR(old_file_path, LENGTH(?)+1) WHERE old_file_path IS NOT NULL AND SUBSTR(old_file_path,1,LENGTH(?))=?',
                        (GOOD, BAD, BAD, BAD))
        print(f'  corpus_reingest_log.old_file_path updated: {c2.rowcount}')
        c3 = db.execute('UPDATE corpus_reingest_log SET new_file_path = ? || SUBSTR(new_file_path, LENGTH(?)+1) WHERE new_file_path IS NOT NULL AND SUBSTR(new_file_path,1,LENGTH(?))=?',
                        (GOOD, BAD, BAD, BAD))
        print(f'  corpus_reingest_log.new_file_path updated: {c3.rowcount}')

        # Step 3: Post-repair verification BEFORE commit
        print('=== VERIFY (pre-commit) ===')
        bad_total = 0
        for tbl, col in [('documents','file_path'),('corpus_reingest_log','old_file_path'),('corpus_reingest_log','new_file_path')]:
            n = db.execute(f\"SELECT COUNT(*) FROM {tbl} WHERE SUBSTR({col},1,LENGTH(?))=?\", (BAD, BAD)).fetchone()[0]
            print(f'  {tbl}.{col}: still_bad={n}')
            bad_total += n
        if bad_total != 0:
            print('FAIL: still bad rows pre-commit — ROLLING BACK')
            db.rollback()
            sys.exit(1)

        # Step 4: Commit only after verification passes
        db.commit()
        print('PASS: all targeted columns clean — COMMITTED')

    except Exception as exc:
        db.rollback()
        print(f'EXCEPTION during repair, rolled back: {exc}')
        raise

    # Step 5: Post-commit spot-check
    sample = db.execute(\"SELECT file_path FROM documents WHERE ticker='GE' AND source='edgar' AND form_type='10-Q' ORDER BY filing_date DESC LIMIT 1\").fetchone()
    print(f'=== SPOT-CHECK ===')
    print(f'  sample GE 10-Q path: {sample[0] if sample else \"<no row>\"}')
    if sample and BAD in sample[0]:
        print('FAIL: spot-check still shows versioned path (committed regardless)')
        sys.exit(3)
    print('PASS: spot-check confirms symlink form')
finally:
    db.close()
PYEOF
echo '--- repair script staged ---'
cat /tmp/f159_repair.py | head -50"
```

**Operator review the script** before execution. Then execute under flock:

```bash
prod "sudo flock -x /run/corpus_promote.lock python3 /tmp/f159_repair.py"
```

**Verify** (expected output):
- Symlink check: `filings.db -> filings_v1.db`
- Pre-repair: `documents.file_path bad=125`, `log.old_file_path bad=?`, `log.new_file_path bad=?` (log counts depend on recent reingest activity)
- Repair: `documents updated: 125`, log counts match pre-repair
- Verify pre-commit: `still_bad=0` for all 3 columns
- `PASS: all targeted columns clean — COMMITTED`
- Spot-check: GE 10-Q path uses `/filings/`, not `/filings_v1/`

If verification fails pre-commit, the transaction is rolled back — DB is unchanged. Investigate before retrying.

---

## Step 7 — Verify next ingest preserves symlink form

R6 reorder: Step 7 was "Resume corpus writers" — moved to new Step 8. Verification (former Step 8) became this Step 7. Verification MUST run before resume, otherwise the daily timer / Celery could produce unrelated rows that falsely satisfy the gate.

Writers remain stopped from Step 3 (systemd) + Step 2.5 if applicable (Celery). The verification below triggers ONE controlled `corpus_delta_ingest.service` run, inspects its result, then either passes or falls to Step 7b canary.

R3 critical changes:
- Actually USES the captured `pre_trigger_count` to detect new writes (not a poorly-comparing time filter)
- Captures `pre_trigger_max_log_id` so we can inspect ONLY log entries from the triggered run

R2: log path corrected to `$REMOTE_DIR/logs/corpus/delta_<date>.jsonl` (the script writes to repo-relative `logs/corpus/`, not `/mnt/hank-data/.../logs` or `/var/log/corpus`).

Trigger one delta manually and inspect the resulting row.

```bash
# Capture pre-trigger snapshot
prod "cd $REMOTE_DIR && venv/bin/python3 -c \"
import sqlite3
db = sqlite3.connect('$REMOTE_DATA/filings.db')
doc_count = db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
max_log_id = db.execute('SELECT COALESCE(MAX(id),0) FROM corpus_reingest_log').fetchone()[0]
print(f'pre_trigger_doc_count={doc_count}')
print(f'pre_trigger_max_log_id={max_log_id}')
\"" | tee /tmp/f159_pre_trigger.txt

# Trigger the delta service
prod "sudo systemctl start corpus_delta_ingest.service"
# Wait for the one-shot to exit (use ActiveState, not is-active --quiet)
prod "while :; do
  state=\$(systemctl show -P ActiveState corpus_delta_ingest.service)
  case \"\$state\" in
    inactive|failed) echo \"corpus_delta_ingest.service: \$state\"; break ;;
    *) echo \"waiting (state=\$state)...\"; sleep 5 ;;
  esac
done"
prod "sudo systemctl status corpus_delta_ingest.service --no-pager | head -15"
prod "tail -30 $REMOTE_DIR/logs/corpus/delta_\$(date -u +%Y-%m-%d).jsonl 2>/dev/null || echo 'no delta log for today'"

# R6: capture BOTH Result and ExecMainStatus.
# The unit has SuccessExitStatus=75 (lock-unavailable), so Result=success can include exit 75
# (lock-blocked, NO work done). Strict check requires ExecMainStatus=0 too.
SERVICE_RESULT=$(prod "systemctl show -P Result corpus_delta_ingest.service")
SERVICE_EXIT=$(prod "systemctl show -P ExecMainStatus corpus_delta_ingest.service")
echo "service_result=$SERVICE_RESULT service_exit=$SERVICE_EXIT"

# Verification using the captured pre-trigger state
PRE_COUNT=$(grep pre_trigger_doc_count /tmp/f159_pre_trigger.txt | cut -d= -f2)
PRE_LOG_ID=$(grep pre_trigger_max_log_id /tmp/f159_pre_trigger.txt | cut -d= -f2)
prod "cd $REMOTE_DIR && SERVICE_RESULT='$SERVICE_RESULT' SERVICE_EXIT='$SERVICE_EXIT' venv/bin/python3 -c \"
import os, sqlite3, sys
PRE_DOC_COUNT = $PRE_COUNT
PRE_LOG_ID = $PRE_LOG_ID
SERVICE_RESULT = os.environ.get('SERVICE_RESULT', 'unknown')
SERVICE_EXIT = os.environ.get('SERVICE_EXIT', 'unknown')
print(f'service_result={SERVICE_RESULT} service_exit={SERVICE_EXIT}')

# R6: HARD gate — service must have succeeded AND returned exit 0
# (exit 75 = lock-unavailable, classified as success by systemd but NO work was done)
if SERVICE_RESULT != 'success':
    print(f'FAIL: corpus_delta_ingest.service Result = {SERVICE_RESULT!r} (expected success). STOP and investigate.')
    sys.exit(3)
if SERVICE_EXIT != '0':
    print(f'FAIL: corpus_delta_ingest.service ExecMainStatus = {SERVICE_EXIT!r} (expected 0; 75=lock-unavailable). STOP and investigate.')
    sys.exit(3)

db = sqlite3.connect('$REMOTE_DATA/filings.db')

# New documents (insertions since trigger)
post_doc_count = db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
new_docs = post_doc_count - PRE_DOC_COUNT
print(f'pre_doc_count={PRE_DOC_COUNT} post_doc_count={post_doc_count} new_docs={new_docs}')

# All log entries since trigger — covers planned/new_written/complete/failed
new_log_rows = db.execute(\\\"\\\"\\\"
    SELECT id, status, content_changed, ticker, old_file_path, new_file_path
    FROM corpus_reingest_log
    WHERE id > ?
    ORDER BY id
\\\"\\\"\\\", (PRE_LOG_ID,)).fetchall()
print(f'new_log_entries={len(new_log_rows)}')
for r in new_log_rows[:10]: print(' ', r)

# Bad-path scan — independent of status (R4: planned/failed rows also have new_file_path written)
bad = []
# New document inserts: scan their file_path
for r in db.execute('SELECT ticker, file_path FROM documents ORDER BY rowid DESC LIMIT ?', (max(new_docs, 0),)):
    if '/filings_v1/' in (r[1] or ''):
        bad.append(('doc_insert', r))
# ALL log entries inserted this run — old + new paths
for r in new_log_rows:
    if '/filings_v1/' in (r[4] or ''):
        bad.append(('log_old_path', r))
    if '/filings_v1/' in (r[5] or ''):
        bad.append(('log_new_path', r))

if bad:
    print(f'FAIL: {len(bad)} paths still use /filings_v1/ form — fix is incomplete')
    for kind, r in bad[:5]: print(f'  {kind}: {r}')
    sys.exit(1)

# Did the write path get exercised? Need new docs OR a content_changed complete reingest
write_exercised = (new_docs > 0) or any(r[1] == 'complete' and r[2] == 1 for r in new_log_rows)
if not write_exercised:
    print('NO write path exercised this run — verification INCONCLUSIVE. Fall through to Step 7b canary.')
    sys.exit(2)

print('PASS: all new writes use symlink form; write path was exercised')
\""
```

**Verify**:
- Exit code 0 = PASS (service succeeded + new writes exist + all use symlink form)
- Exit code 1 = FAIL (new writes exist but some still versioned — STOP and investigate)
- Exit code 2 = INCONCLUSIVE (no new writes this run — fall through to Step 7b)
- Exit code 3 = FAIL (service Result != success OR ExecMainStatus != 0 — STOP and investigate before relying on any other verification)

### Step 7b — Canary reingest (only if Step 7 returned exit 2)

R3: `reingest_one` returns `no_change` if content hash matches — that path skips the document upsert and doesn't exercise the fix. The canary now verifies via the `corpus_reingest_log` entry directly (must show `status='complete'` AND `content_changed=1`), AND iterates a small set of accessions to find one that actually changes.

```bash
# Try multiple accessions until one produces a content_changed reingest.
# These are F90's 5remaining (all known reingestable; if local refresh worked,
# they may already match on prod, so we try several).
prod "cat > /tmp/f159_canary.txt <<'EOF'
edgar:0000019617-22-000319
edgar:0000895421-22-000442
edgar:0001327567-23-000032
edgar:0000077476-24-000052
edgar:0001805284-25-000088
EOF

cd $REMOTE_DIR && PRE_LOG_ID=\$(venv/bin/python3 -c \"
import sqlite3; db = sqlite3.connect('$REMOTE_DATA/filings.db')
print(db.execute('SELECT COALESCE(MAX(id),0) FROM corpus_reingest_log').fetchone()[0])\")
echo \"pre_canary_log_id=\$PRE_LOG_ID\"

sudo flock -x /run/corpus_promote.lock venv/bin/python3 scripts/corpus_bulk_reingest.py \\
  --filter-document-ids /tmp/f159_canary.txt \\
  --db $REMOTE_DATA/filings.db \\
  --corpus-root $REMOTE_DATA/filings \\
  --per-document-timeout-seconds 600 \\
  --log /tmp/f159_canary.jsonl

# Verify via the log table — R4: scan ALL new log rows (any status) for bad paths,
# AND require at least one complete+content_changed to confirm write path was exercised
venv/bin/python3 -c \"
import sqlite3, sys
PRE = \$PRE_LOG_ID
db = sqlite3.connect('$REMOTE_DATA/filings.db')
rows = db.execute('SELECT id, status, content_changed, ticker, old_file_path, new_file_path FROM corpus_reingest_log WHERE id > ? ORDER BY id', (PRE,)).fetchall()
print(f'canary_log_entries={len(rows)}')
for r in rows: print(' ', r)

# Bad-path scan across ALL new rows (any status) — planned/failed rows have new_file_path too
bad_paths = []
for r in rows:
    if '/filings_v1/' in (r[4] or ''):
        bad_paths.append(('old_path', r))
    if '/filings_v1/' in (r[5] or ''):
        bad_paths.append(('new_path', r))

# Write-path-exercised proof: complete + content_changed=1 (this is the path that calls _upsert_and_mark)
content_changed_rows = [r for r in rows if r[1] == 'complete' and r[2] == 1]
print(f'content_changed_count={len(content_changed_rows)} bad_path_count={len(bad_paths)}')

if bad_paths:
    print('FAIL: canary log shows /filings_v1/ paths — fix is incomplete')
    for kind, r in bad_paths[:5]: print(f'  {kind}: {r}')
    sys.exit(1)
if not content_changed_rows:
    print('INCONCLUSIVE: all canary docs returned no_change — content was unchanged. Rely on local-side test coverage; the prod code path is the same. Optionally re-run later if you want a prod-side write-path proof.')
    sys.exit(2)
print('PASS: canary exercised write path and used symlink form')
\""
```

**Verify**: at least one log entry shows `content_changed=1, status=complete`, all log entries' `new_file_path` use `/filings/`. If exit 2 (all no-change), the F159 verification can rely on local-side test coverage instead — the prod code path is the same code, and we've already verified locally that the fix produces symlink-form paths.

---

## Step 8 — Resume corpus writers ⚠️ [CONFIRM]

R6: was Step 7. Resume happens AFTER verification proves the fix works on prod.

```bash
prod "sudo systemctl start corpus_delta_ingest.timer corpus_transcripts_delta.timer"
prod "sudo systemctl status corpus_delta_ingest.timer corpus_transcripts_delta.timer --no-pager | head -10"
```

If Step 2.5 stopped Celery:

```bash
prod "sudo systemctl start celery_worker_maint"
prod "cd $REMOTE_DIR && venv/bin/python3 -m celery -A workers.celery_app.app inspect ping -d maint@\$(hostname)"
prod "sudo systemctl start celery_beat"
prod "sudo systemctl status celery_beat celery_worker_maint --no-pager | head -10"
```

**Verify**: timers active, services running, Celery ping succeeds (if applicable).

---

## Step 9 — Unblock F158 round-trip (dry-run proof only)

R2: split — only the dry-run lives in F159's deploy window. The `--execute` + bulk refresh + promote (30-90 min) is deferred to a separate F158 session outside this prod repair rollback window.

From local:

```bash
cd /Users/henrychien/Documents/Jupyter/risk_module
bash scripts/pull_corpus_from_prod.sh --dry-run
```

**Verify**: dry-run passes preflight cleanly (no rewrite-prefix error). This is the F159 deploy proof — the bug is fixed AND the data is repaired, so cross-machine sync now works.

**Do NOT run `--execute` here.** That's a separate F158 session.

---

## Rollback procedure (if anything fails)

**Mid-deploy (Steps 1-5):** rollback before SQL repair; revert deploy via the captured pre-deploy SHA, NOT `HEAD~1` (R2 — Codex caught this: `HEAD~1` is unreliable if `git pull` brought in multiple commits).

```bash
PRE_SHA=$(cat /tmp/f159_pre_deploy_head.txt)
prod "cd $REMOTE_DIR && git reset --hard $PRE_SHA"
prod "sudo systemctl restart risk_module"
```

**Post-SQL-repair (Step 6 succeeded but Step 7/7b verification failed):** SQL repair is reversible by re-running with BAD/GOOD swapped, but easier path is EBS snapshot restore — `aws ec2 detach-volume` + create new volume from snap-XXXX + remount. Operator decision. Writers stay stopped throughout — Step 8 not reached.

**Step 7/7b reveals new bad rows:** indicates the F159 fix is incomplete OR a write path was missed. STOP. Writers stay stopped. Capture the new bad row's accession/extraction_at/parser_version, file as F159 follow-up, re-investigate before proceeding. No data rollback needed (the repair was correct; the new bad row came from the deploy).

**Step 8 (resume writers) fails:** keep writers stopped, troubleshoot timers/Celery startup, no data rollback. Step 7/7b verification already proved data + code state are good. Investigate systemd unit status, recent journalctl logs.

---

## Post-deploy verification matrix

| Check | Expected | Where |
|---|---|---|
| `documents.file_path` versioned-prefix rows | 0 | Step 6 + Step 7 |
| `corpus_reingest_log.{old,new}_file_path` versioned-prefix rows | 0 | Step 6 |
| Next delta ingest stores symlink form | yes | Step 7 (or 7b canary) |
| `pull_corpus_from_prod.sh --dry-run` passes | yes | Step 9 |
| `risk_module` service healthy | active+running | Step 5 |
| Corpus timers running | active | Step 8 |
| `corpus_delta_ingest.service` `Result=success` AND `ExecMainStatus=0` | yes | Step 7 |

---

## Notes

- All `prod "..."` commands assume the env exports in §SSH context. Operator may use direct ssh invocation instead.
- Time estimate: 15-30 minutes if all steps clean. Most time is in Step 1 (EBS snapshot wait) and Step 7 (waiting for the one-shot delta ingest to complete).
- Captures the full audit trail by piping each step's output to a log file: `prod "..." | tee -a /tmp/f159_deploy_$(date +%Y%m%d_%H%M%S).log`
