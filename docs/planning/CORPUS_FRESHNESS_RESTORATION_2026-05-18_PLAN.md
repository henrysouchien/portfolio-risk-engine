# Corpus Freshness Restoration Plan — 2026-05-18

## Status as of 2026-05-19 end-of-session

| Step | Code | Prod deploy | Notes |
|---|---|---|---|
| A — venv ExecStart + SuccessExitStatus=75 + hardened ExecStopPost | ✅ `c29973aa` | ✅ live | First clean ingest in 13 days completed 19:52 UTC, 26min run, exit 0 |
| B — SSM-backed Telegram wrapper | ✅ `162a4bc7` | ✅ live 2026-05-19 | F93 resolved option (a): `hank_alert_bot` created; SSM params provisioned (us-east-1, `risk-module-credentials-prod` KMS); alert.service + wrapper deployed; transient drop-in test triggered Telegram receipt end-to-end |
| C1 — natural catch-up | n/a | ✅ in progress | Today's run drained 100 version_floor docs |
| D — transcripts systemd unit + lock parity | ✅ `b1570b2c` | ✅ live 2026-05-19 | Script refreshed (May-1 stale → b1570b2c), 3 units installed, timer enabled (next Wed 11:00 UTC), manual run: 58s, exit 0, `transcripts_delta_2026-05-19.jsonl` (30KB) clean |
| E — post-deploy import smoke | ✅ `d44a3b27` | ⏳ next deploy | Runs automatically on next `scripts/deploy.sh` invocation |
| Bonus — EDGAR_API_URL prod `.env` domain fix | n/a | ✅ live | financialmodelupdater.com → edgarparser.com |

**Open follow-ups filed in `docs/TODO.md`:** ~~F93 (admin alert channel) — SHIPPED 2026-05-19~~, ~~F94 (deploy D to EC2) — SHIPPED 2026-05-19~~, F95 (Celery beat consolidation), F96 (lock helper extract), F97 (transcripts digest), F98 (templated alert unit), F99 (BACKEND_BASE_URL/ESTIMATE_API_URL domain drift). **All four plan steps (A/B/D/E) now structurally complete; E auto-fires on next `deploy.sh`.**

**Provisioning footgun discovered 2026-05-19 (saved to memory):** `scripts/provision_ssm_params.py` imports `bootstrap_env`, which loads `.env` AWS creds (runtime read-only `plaid-access-token-service`) into `os.environ`. These env vars shadow any provisioning identity in `~/.aws/credentials` (`finance-web-deploy` admin) — PutParameter then fails as `AccessDeniedException` against the runtime user. Workaround: export `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION=us-east-1` from your shell profile before running the script. Also: `/risk-module/*` params live in us-east-1, not the shell-default us-east-2.

---

## 1. Problem statement

The corpus delta ingest on prod (EC2 `3.139.124.134`) has been **failing every day for 9+ days, silently**:

- Last successful delta: 2026-05-05 (`/var/www/risk_module/logs/corpus/delta_2026-05-05.jsonl`)
- May 10–14: `ModuleNotFoundError: No module named 'httpx'`
- May 15–18 (today): `ModuleNotFoundError: No module named 'dotenv'` (after `c42cae42` wired `bootstrap_env` into the entry point)
- Alert pipeline (`corpus_delta_ingest_alert.service` → `notify_telegram.sh`) also failed every day: `ERROR: TELEGRAM_BOT_TOKEN or API_BUDGET_TELEGRAM_BOT_TOKEN is not set`

Net: corpus has been stale 13 days, with no notification.

## 2. Root causes (three independent)

### RC-1 — Systemd unit does not use the venv

`docs/deployment/systemd/corpus_delta_ingest.service` invokes:

```
ExecStart=/usr/bin/env bash -lc 'python3 scripts/corpus_phase1_delta_ingest.py …'
```

`/usr/bin/env bash -lc 'python3 …'` resolves to **system Python** at `/usr/bin/python3` → `/usr/local/lib/python3.12/dist-packages`. The venv at `/var/www/risk_module/venv/` exists and has the right deps, but the unit never activates it.

**Every other systemd unit on this host uses the venv explicitly:**

| Unit | Python invocation |
|---|---|
| `risk_module.service` | `ExecStart=/var/www/risk_module/venv/bin/python3 -m uvicorn …` |
| `analyst-daily@.service` | `ExecStart=…/venv/bin/python3 scripts/run_analyst.py` |
| `edgar_api.service` | `ExecStart=/var/www/edgar_updater/venv/bin/uvicorn …` |
| `corpus_delta_ingest.service` | `ExecStart=/usr/bin/env bash -lc 'python3 …'` ← outlier |

Two new code changes since the last successful run added imports the system Python doesn't have:

1. `core/corpus/edgar_api_client.py` line 13 → `import httpx`
2. `scripts/corpus_phase1_delta_ingest.py` line 22 → `import bootstrap_env` → `bootstrap_env.py` line 15 → `from dotenv import dotenv_values, load_dotenv`

Both packages **are** in `requirements.txt` and **are** installed in the venv. Switching the unit to the venv python fixes both.

### RC-2 — Alert pipeline has no Telegram secret

`scripts/notify_telegram.sh` reads `TELEGRAM_BOT_TOKEN` / `API_BUDGET_TELEGRAM_BOT_TOKEN` from environment. The `corpus_delta_ingest_alert.service` loads `/var/www/risk_module/.env`, which does **not** contain either key. Confirmed by:

```
sudo grep -E "^TELEGRAM|^API_BUDGET_TELEGRAM" /var/www/risk_module/.env
# (no output)
```

The alert service has failed every single day since the corpus ingest started failing on 2026-05-10 — 9 consecutive silent failures of the failure-notification pipeline.

### RC-3 — Transcripts delta is not on EC2 at all

Only `corpus_delta_ingest.service` / `.timer` exist on EC2. There is no `corpus_transcripts_delta` unit.

**Celery beat state on prod (verified via SSH 2026-05-18):** NO Celery worker or beat process running. No `celery-*.service` units. `workers/beat_schedule.py` defines four corpus tasks (`corpus-reconciler-daily` @03 UTC, `corpus-transcripts-delta-daily` @05 UTC, `corpus-delta-ingest-daily` @06 UTC, `corpus-health-report-daily` @07 UTC) — none of which fire today because beat is absent. So:

1. Corpus IS 13 days stale (no parallel beat scheduler running silently).
2. **Future duplicate-scheduler risk:** the moment anyone starts Celery beat on prod, the systemd timer (filings) and beat entries would BOTH fire `corpus.delta_ingest_daily` — same task, same lock, same DB. Reconciler/health/transcripts beat entries would similarly compete with any future systemd units. Tracked as follow-up F-CELERY-BEAT-CONSOLIDATION.
3. For this plan: prod is systemd-only. Step D's new transcripts systemd unit is safe today. Resolving beat-vs-systemd duplication is out of scope; flagged for the follow-up.

## 3. Scope

In scope:
- **A** — Fix `corpus_delta_ingest.service` to use the venv (RC-1)
- **B** — Wire Telegram secret into the alert path (RC-2)
- **C** — Catch up the 13 missed days of filings delta
- **D** — Decide and ship the transcripts-delta-on-EC2 path (RC-3)
- **E** — Post-deploy smoke that catches the "imports added but deps not installed" class

Out of scope (filed as follow-ups, not deferred):
- **F-CELERY-BEAT** — Celery beat schedule status for the other four corpus tasks (`reingest_log_rotate_daily`, `reconciler_daily`, `health_report_daily`, `transcripts_delta_daily`). Verify on prod. If beat is not running, the alert hook in `health_report_daily` that emits CRITICAL via alerts-mcp also hasn't been firing.
- **F-VENV-REQUIREMENTS-DRIFT** — broader question of whether prod venv is in sync with `requirements.txt` after each deploy. `deploy.sh` does `pip install -q -r requirements.txt` so this should be solved by deploy, but verify.
- **F-RECONCILER-DRIFT** — 13 days of no reconciler runs may have accumulated filesystem/index drift. Run dry-run reconciler after A is verified.

## 4. Plan

### Step A — Fix systemd unit to use venv

**Files to change:**

- `docs/deployment/systemd/corpus_delta_ingest.service` — switch ExecStart to use the venv python, set PATH explicitly, AND add `SuccessExitStatus=75` so lock-unavailable exits (from `corpus_phase1_delta_ingest.py:728,742`) don't fire `OnFailure=corpus_delta_ingest_alert.service`:

  ```
  [Service]
  Type=oneshot
  WorkingDirectory=/var/www/risk_module
  EnvironmentFile=-/var/www/risk_module/.env
  Environment="PATH=/var/www/risk_module/venv/bin:/usr/local/bin:/usr/bin:/bin"
  TimeoutStartSec=1h
  SuccessExitStatus=75
  ExecStart=/var/www/risk_module/venv/bin/python3 scripts/corpus_phase1_delta_ingest.py \
      --universe data/corpus/universe.json \
      --db /mnt/hank-data/risk_module/filings.db \
      --corpus-root /mnt/hank-data/risk_module/filings \
      --lock-file /run/corpus_promote.lock \
      --lock-timeout-seconds 30
  ```

  Remove the `/usr/bin/env bash -lc` wrapper since we're calling python directly.

  **Make `ExecStopPost` best-effort AND exit-0-gated (Codex r4 MAJOR + r5 semantic clarification):**

  ```
  ExecStopPost=-/usr/bin/env bash -lc 'if [ "$SERVICE_RESULT" = success ] && [ "$EXIT_STATUS" = 0 ]; then digest="logs/corpus/delta_$(date -u +%%F).digest"; if [ -s "$digest" ]; then /var/www/risk_module/venv/bin/python3 scripts/notify_with_bootstrap.py < "$digest"; fi; fi'
  ```

  Three changes from the existing unit:
  1. `-` prefix → systemd ignores exec failures (so a Telegram outage can't fail an otherwise-successful ingest)
  2. `$SERVICE_RESULT = success` gate → not on failed starts (which also trigger `ExecStopPost`)
  3. `$EXIT_STATUS = 0` gate → not on lock-contention skips (Codex r5: `SuccessExitStatus=75` makes exit 75 "successful" from systemd's POV, but no real work happened, so the digest would be empty/stale)

  Per systemd docs, `ExecStopPost=` runs after both successful stops AND failed starts; systemd populates `$SERVICE_RESULT` / `$EXIT_CODE` / `$EXIT_STATUS` for `ExecStopPost=` use.

  **Why `SuccessExitStatus=75`:** the existing unit was missing this, so any lock-unavailable run (separate from the ImportError class) would have ALSO triggered the alert pipeline. Codex r2 MAJOR.

**Deploy steps (manual, this is config not code):**

1. Copy updated unit file to EC2: `sudo cp /var/www/risk_module/docs/deployment/systemd/corpus_delta_ingest.service /etc/systemd/system/`
2. `sudo systemctl daemon-reload`
3. Manually trigger once: `sudo systemctl start corpus_delta_ingest.service`
4. Watch: `sudo journalctl -u corpus_delta_ingest.service -f`
5. Confirm new `logs/corpus/delta_2026-05-18.jsonl` written

**Verification gate:**
- `delta_2026-05-18.jsonl` exists and is non-empty
- Service `Active: inactive (dead)` with `code=exited, status=0/SUCCESS` (the previous-run line in `systemctl status`)
- No tracebacks in journal for the run

### Step B — Restore Telegram alert pipeline via SSM hydration

**Decision:** B2 chosen — SSM-only rotation; no Telegram secrets in `.env`.

**Implementation:**

1. **Provision SSM params** (two-tier prod/dev). `bootstrap_env` discovers params by path prefix `/risk-module/<env>/shared/` and maps kebab→SCREAMING_SNAKE automatically — NO allowlist there (`bootstrap_env.py:214–235`). But `scripts/provision_ssm_params.py` DOES have an allowlist (`provision_ssm_params.py:35`) and rejects unexpected keys (`:154`); it always writes `SecureString` (`:223`).

   **Two-step:**
   - Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to the shared-tier allowlist in `provision_ssm_params.py`. Chat-id will be SecureString — that's fine (chat IDs aren't sensitive but encryption is harmless and keeps the helper symmetric).
   - Provision the four params:
     - `/risk-module/prod/shared/telegram-bot-token` (SecureString)
     - `/risk-module/prod/shared/telegram-chat-id` (SecureString)
     - `/risk-module/dev/shared/telegram-bot-token` (SecureString)
     - `/risk-module/dev/shared/telegram-chat-id` (SecureString)

2. **New Python wrapper:** `scripts/notify_with_bootstrap.py`. Critical fixes from Codex r1: needs sys.path prelude (script is in `scripts/` so repo root isn't on path by default); MUST call `bootstrap_env.bootstrap(required=[…])` (bare `import bootstrap_env` does NOT hydrate — hydration only happens inside `.bootstrap()`, see `bootstrap_env.py:267`). Also builds the failure-alert message internally to avoid systemd shell-expansion mess.

   ```python
   #!/usr/bin/env python3
   """Notify via Telegram with bootstrap_env (SSM) hydration first.

   For use from systemd alert + digest services where TELEGRAM_BOT_TOKEN must
   come from SSM, not the .env file.

   Usage:
       # Service-failure mode (constructs standard alert message):
       notify_with_bootstrap.py --service-failed corpus_delta_ingest.service

       # Pass-through mode (any other notify_telegram.sh args):
       notify_with_bootstrap.py --message "test alert"
       echo "digest body" | notify_with_bootstrap.py
   """
   from __future__ import annotations

   import socket
   import subprocess
   import sys
   from datetime import datetime, timezone
   from pathlib import Path

   REPO_ROOT = Path(__file__).resolve().parent.parent
   if str(REPO_ROOT) not in sys.path:
       sys.path.insert(0, str(REPO_ROOT))

   import bootstrap_env  # noqa: E402

   bootstrap_env.bootstrap(required=["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])

   args = sys.argv[1:]
   if args[:1] == ["--service-failed"] and len(args) >= 2:
       unit = args[1]
       ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
       message = (
           f"{unit} failed on {socket.gethostname()} at {ts} UTC. "
           f"Check: journalctl -u {unit} -n 200 --no-pager"
       )
       args = ["--message", message, *args[2:]]

   script = REPO_ROOT / "scripts" / "notify_telegram.sh"
   raise SystemExit(subprocess.call([str(script), *args], cwd=REPO_ROOT))
   ```

   `subprocess.call` inherits `os.environ` by default; `bootstrap.bootstrap()` writes into `os.environ` (`bootstrap_env.py:202`); child shell sees the hydrated tokens. `notify_telegram.sh` stays unchanged.

3. **Update `corpus_delta_ingest_alert.service`** to invoke the wrapper via the venv python:

   ```
   ExecStart=/var/www/risk_module/venv/bin/python3 scripts/notify_with_bootstrap.py --service-failed corpus_delta_ingest.service
   ```

   No shell-expansion needed; the wrapper builds the message.

4. **Update `corpus_delta_ingest.service`'s ExecStopPost** (Telegram digest send on success path) — Step A already locks in the canonical form (best-effort + success-gated, see Step A snippet). The Step B change is just confirming the wrapper script path is correct (`/var/www/risk_module/venv/bin/python3 scripts/notify_with_bootstrap.py < "$digest"`). Pipe-stdin works because `notify_with_bootstrap.py` falls through to `notify_telegram.sh`, which reads stdin when no `--message` is provided.

**Files to change:**
- `scripts/notify_with_bootstrap.py` (new, ~40 lines per snippet above)
- `scripts/provision_ssm_params.py:44` — append `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` to shared allowlist
- `tests/test_provision_ssm_params.py:113,230` — update hard-coded `1/11` and `10/11` shared-key counts to `1/13` and `12/13` (Codex r2 MINOR)
- `docs/deployment/systemd/corpus_delta_ingest.service` (ExecStopPost line)
- `docs/deployment/systemd/corpus_delta_ingest_alert.service` (ExecStart line)
- SSM params (out-of-band; via the updated `provision_ssm_params.py`)
- `bootstrap_env.py` — **no change needed** (path-prefix discovery already picks up new keys, `bootstrap_env.py:214-235`)

**Verification gate:**
- **Confirm prod `.env` sets `ENVIRONMENT=prod` (or `production`)** before running the SSM probe. Codex r3 MAJOR: `bootstrap_env._environment()` defaults to dev when `ENVIRONMENT` is unset (`bootstrap_env.py:106`), and a dev-namespace hydration would let this gate pass while pointing at `/risk-module/dev/...` instead of `/risk-module/prod/...`.
- On prod, run (with explicit `sys.path` since the script lives in `scripts/`):
  ```
  /var/www/risk_module/venv/bin/python3 -c "
  import sys; sys.path.insert(0, '/var/www/risk_module')
  import bootstrap_env
  bootstrap_env.bootstrap(required=['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'])
  import os
  assert bootstrap_env._BOOTSTRAP_ENVIRONMENT == 'prod', f'wrong env: {bootstrap_env._BOOTSTRAP_ENVIRONMENT}'
  assert bootstrap_env._BOOTSTRAP_USE_SSM is True, 'SSM hydration not active'
  print('env=', bootstrap_env._BOOTSTRAP_ENVIRONMENT)
  print('ssm_active=', bootstrap_env._BOOTSTRAP_USE_SSM)
  print('TELEGRAM_BOT_TOKEN present:', bool(os.environ.get('TELEGRAM_BOT_TOKEN')))
  print('TELEGRAM_CHAT_ID present:', bool(os.environ.get('TELEGRAM_CHAT_ID')))
  "
  ```
  Expected: `env=prod`, `ssm_active=True`, both Telegram keys present. (Bare `import bootstrap_env` does NOT hydrate — must call `.bootstrap()`. Codex r2 MAJOR.)
- Manual trigger: `/var/www/risk_module/venv/bin/python3 /var/www/risk_module/scripts/notify_with_bootstrap.py --message "alert-pipe test 2026-05-18"` → Telegram receipt
- **Deterministic alert-path test (Codex r4 MINOR + r5 MAJOR):** the unit lives under `/etc/systemd/system/` so `systemctl edit --runtime` (which writes under `/run/`) won't take precedence. Use a persistent drop-in under `/etc/systemd/system/<unit>.d/`, then remove it after:
  ```
  # Set up a failure-forcing drop-in
  sudo mkdir -p /etc/systemd/system/corpus_delta_ingest.service.d
  sudo tee /etc/systemd/system/corpus_delta_ingest.service.d/test-failure.conf <<'EOF'
  [Service]
  ExecStart=
  ExecStart=/bin/false
  EOF
  sudo systemctl daemon-reload

  # Force the failure
  sudo systemctl start corpus_delta_ingest.service
  # Expect: service enters failed state → OnFailure fires corpus_delta_ingest_alert.service → Telegram message received

  # Cleanup — remove drop-in, reload, AND reset the failed-state flag
  sudo rm /etc/systemd/system/corpus_delta_ingest.service.d/test-failure.conf
  sudo rmdir /etc/systemd/system/corpus_delta_ingest.service.d 2>/dev/null || true
  sudo systemctl daemon-reload
  sudo systemctl reset-failed corpus_delta_ingest.service
  ```

### Step C — Catch up 13 missed days of filings delta (C1: natural)

**Decision:** C1 chosen — let the next-day delta + invalidation feed do its job. No forced rerun.

Once A is green, the daily delta plus the invalidation feed naturally picks up doc changes; the machinery was designed for exactly this kind of gap. The 13-day staleness will not produce permanent data loss unless a document was published, amended, AND withdrawn entirely within that window (vanishingly rare for SEC filings).

**Verification gate:**
- Tomorrow's (2026-05-19) `delta_*.jsonl` shows normal new-doc count
- `data/corpus/health/2026-05-19.json` clean (no bug-class spikes)
- If 2026-05-20 health snapshot is also clean, mark resolved

**Escalation:** if a specific Hank query hits a known-missed doc, manually invoke `scripts/corpus_ingest_accession.py <accession>` to pull just that one.

### Step D — Ship transcripts delta on EC2 (D1: parallel systemd pattern)

**Decision:** D1 chosen — new systemd unit + timer mirroring the filings pattern. Defer Celery beat consolidation to F-CELERY-BEAT-CONSOLIDATION (see RC-3 update).

**Lock handling (Codex r1 MAJOR):** `scripts/corpus_phase3_delta_transcripts.py:81` opens the same `filings.db` as the filings script. Filings defines `LockUnavailableError` + `acquire_lock` inline at `corpus_phase1_delta_ingest.py:84,763`; lock acquisition is wrapped at `:611`. Transcripts has neither. SQLite uses WAL but has no busy-timeout (`core/corpus/db.py:18`). Add lock arg parity to the transcripts script — small code change, same shape as filings.

**Helper-location decision:** **duplicate the small helper into transcripts** for minimum blast radius this round. Extraction to `core/corpus/lock.py` is the cleaner long-term move but expands scope (touches filings too); filed as follow-up F-CORPUS-LOCK-HELPER-EXTRACT.

**Code change to `scripts/corpus_phase3_delta_transcripts.py`:**
- Add `--lock-file` and `--lock-timeout-seconds` args matching filings' argparse signature
- Duplicate the small `LockUnavailableError` + `acquire_lock` helpers from filings
- Wrap the DB-touching section in `acquire_lock(...)`
- Return `LOCK_UNAVAILABLE_EXIT_CODE` (= 75, mirror filings) on contention

**Test additions** (Codex r3 MINOR): `tests/test_corpus_phase3_transcripts.py` currently covers parser defaults + quarter selection, no lock semantics. Mirror the filings lock-contention test shape from `tests/test_corpus_phase1_delta_ingest.py:508` — at minimum: (a) lock contention returns exit code 75, (b) `--lock-file` arg parses, (c) lock released after successful run.

**Files to create (in `docs/deployment/systemd/`):**

- `corpus_transcripts_delta.service` — mirrors the filings unit, with `SuccessExitStatus=75` and concrete prod paths (Codex r2 MAJOR — no `[as required]` placeholder):

  ```
  [Unit]
  Description=Hank corpus daily transcripts delta ingest
  Wants=network-online.target
  After=network-online.target
  RequiresMountsFor=/mnt/hank-data
  OnFailure=corpus_transcripts_delta_alert.service

  [Service]
  Type=oneshot
  WorkingDirectory=/var/www/risk_module
  EnvironmentFile=-/var/www/risk_module/.env
  Environment="PATH=/var/www/risk_module/venv/bin:/usr/local/bin:/usr/bin:/bin"
  TimeoutStartSec=1h
  SuccessExitStatus=75
  ExecStart=/var/www/risk_module/venv/bin/python3 scripts/corpus_phase3_delta_transcripts.py \
      --universe data/corpus/universe.json \
      --db /mnt/hank-data/risk_module/filings.db \
      --corpus-root /mnt/hank-data/risk_module/filings \
      --lock-file /run/corpus_promote.lock \
      --lock-timeout-seconds 30
  ```

  **No `ExecStopPost` digest send** — the transcripts script has no digest writer (`scripts/corpus_phase3_delta_transcripts.py:35` only emits `--log` JSONL). Adding digest support is filed as follow-up F-CORPUS-TRANSCRIPTS-DIGEST, not a blocker for the systemd unit. Success path goes silent on Telegram; failure path still fires the alert.

- `corpus_transcripts_delta.timer` — schedule at **11:00 UTC** (1 hour after filings' 10:00 UTC; filings' `TimeoutStartSec=1h` so the lock can still be held until 11:00 in worst case — but `SuccessExitStatus=75` plus the `LOCK_UNAVAILABLE_EXIT_CODE` script return makes that a clean skip).

- `corpus_transcripts_delta_alert.service` — same template as filings alert, calls `notify_with_bootstrap.py --service-failed corpus_transcripts_delta.service`.

**Deploy steps:**
1. Author files + transcript-script lock changes in repo, commit, push
2. Deploy via `scripts/deploy.sh` (which runs `pip install -q -r requirements.txt` inside the venv)
3. On EC2: `sudo cp docs/deployment/systemd/corpus_transcripts_delta*.{service,timer} /etc/systemd/system/`
4. `sudo systemctl daemon-reload`
5. `sudo systemctl enable --now corpus_transcripts_delta.timer`
6. Manual trigger: `sudo systemctl start corpus_transcripts_delta.service`
7. Verify `transcripts_delta_2026-05-XX.jsonl` written and service `code=exited, status=0/SUCCESS`

**Verification gate:**
- First scheduled run creates `transcripts_delta_2026-05-XX.jsonl` on prod
- Health snapshot the next day shows non-zero transcript counts

### Step E — Post-deploy import smoke (NOT dry-run)

After deploy, run a syntactic **import-only** smoke of the corpus entry points against the deployed venv. Catches the "import broke" class without doing a full ingest.

**IMPORTANT (Codex r1 MINOR):** do NOT run the scripts with `--dry-run` as part of deploy. `corpus_phase1_delta_ingest.py --dry-run` still calls the invalidation feed and filings discovery (`:638`, `:706`) — has side effects (rate-limit hits) and network deps that don't belong in the deploy critical path. Import-only is correct.

**Where:** Append to `scripts/deploy.sh` after the `pip install` step:

```bash
$SSH "cd $REMOTE_DIR && source venv/bin/activate && python3 -c 'import scripts.corpus_phase1_delta_ingest; import scripts.corpus_phase3_delta_transcripts; import bootstrap_env'"
```

Fast (<1s), no side effects, fails the deploy if imports break.

**Verification gate:**
- Intentional break (e.g., add `import nonexistent` to a covered script): deploy fails before declaring success
- After revert: deploy succeeds

**Optional (post-A-deploy, not in deploy.sh):** operator runs `python3 scripts/corpus_phase1_delta_ingest.py --dry-run --log /tmp/sanity.jsonl --digest /tmp/sanity.digest` once after first deploy to confirm the full code path works end-to-end. Not automated.

## 5. Sequencing

Recommended order:

1. **A first** — switch corpus_delta_ingest unit to venv python. Unblocks the daily filings run. Lowest risk; isolated to one unit file.
2. **B** — provision SSM Telegram params + ship `notify_with_bootstrap.py` + update alert unit. Once live, manually fire the alert path to verify Telegram receipt.
3. **C1** — observe natural delta tomorrow (2026-05-19) + day after. No action needed unless health snapshot flags.
4. **E** — add post-deploy import smoke to `scripts/deploy.sh`. One-line append. Catches the class of failure for next time.
5. **D** — ship transcripts systemd unit + timer + alert. Independent of A/B; can ship in parallel once A pattern is proven.

**Critical-path order: A → B → E.** D can ship any time after A. C is observe-only.

**Why A before B:** A is the only step that gets the daily filings ingest running again. B fixes notifications but doesn't fix data freshness. If we only ship B, alerts work but corpus stays stale; if we only ship A, ingest works but failures remain silent. Both are required, A more urgent.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Manual `sudo cp` on prod for the unit file is error-prone | Have user copy/paste the exact command; verify file contents with `diff` after copy |
| The venv on prod may itself be stale (missing some other dep not flagged today) | After Step A, also run `cd /var/www/risk_module && source venv/bin/activate && pip install -q -r requirements.txt` to ensure venv tracks `requirements.txt` |
| `bootstrap_env` needs SSM read + KMS decrypt access for BOTH `/risk-module/<env>/shared/` AND `/risk-module/<env>/broker/` paths | `bootstrap_env._hydrate_from_ssm` iterates both tiers (`bootstrap_env.py:214`); prod forces `require_broker_tier=True` (`bootstrap_env.py:121`), so the broker tier failing returns hard error, not graceful skip. AWS creds already in `.env` (used by existing app boot — same identity, same creds). Successful hydration is silent; only failures log. Verify via Step B's explicit `bootstrap.bootstrap(...)` + `_BOOTSTRAP_ENVIRONMENT == 'prod'` + `_BOOTSTRAP_USE_SSM is True` check. |
| 13 days of `parser_version` drain didn't run (F69) | Resumes automatically once daily delta is green. Track via `data/corpus/health/YYYY-MM-DD.json` `version_floor` field |

## 7. Open questions

All previously-open questions resolved during plan iteration:

- ~~`--since DATE` flag in filings script?~~ — does not exist (`corpus_phase1_delta_ingest.py:88` has `--backfill-days`, not `--since`). Moot: chosen path is C1 (natural delta), not a forced rerun.
- ~~Celery beat running on prod?~~ — verified absent (RC-3 update). Filed as F-CELERY-BEAT-CONSOLIDATION.
- ~~Telegram credentials location?~~ — moot under B2 (SSM-only).

No open questions remain.

## 8. Out-of-band: TODO.md row updates

**Done (2026-05-18 end-of-session):**
- ✅ **F54** updated with full diagnosis + Step A ship marker
- ✅ **F93** filed — admin alert channel decision (blocks Step B prod deploy)
- ✅ **F94** filed — push Step D systemd units to EC2 (operator action)
- ✅ **F95** filed — Celery beat / systemd duplicate-scheduler consolidation (latent risk)
- ✅ **F96** filed — extract lock helper to `core/corpus/lock.py`
- ✅ **F97** filed — add digest writer to transcripts script
- ✅ **F98** filed — templated systemd corpus alert unit
- ✅ **F99** filed (in Infra section) — `BACKEND_BASE_URL` + `ESTIMATE_API_URL` domain drift cleanup

**Pending:**
- **F64, F69, F90** still cite "gated on F54 verify" — should be re-evaluated after F94 ships (transcripts unit) and a few days of clean daily runs prove the drain is resuming. Defer this re-evaluation to whoever picks up F94.

## 8a. Codex review log

### Round 1 — FAIL → addressed
- **CRITICAL 1** (Step B wrapper didn't actually hydrate SSM): rewritten with sys.path prelude + explicit `bootstrap_env.bootstrap(required=…)` call (Section 4 Step B).
- **CRITICAL 2** (Celery beat duplicate-scheduler risk for transcripts): verified on prod — no Celery beat/worker running (RC-3 update). Plan stays systemd-only. Beat-vs-systemd consolidation tracked as F-CELERY-BEAT-CONSOLIDATION.
- **MAJOR 1** (transcripts script has no lock; same DB as filings): adds `--lock-file` / `--lock-timeout-seconds` arg parity, duplicated `LockUnavailableError`/`acquire_lock` helpers from filings.
- **MAJOR 2** (`provision_ssm_params.py` has allowlist, always writes SecureString): add `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` to allowlist; both keys SecureString.
- **MAJOR 3** (alert ExecStart unresolved shell expansion): message construction moved into the Python wrapper via `--service-failed UNIT` flag.
- **MINOR 1** (--dry-run is NOT side-effect-free): Step E uses import-only smoke; explicit warning against dry-run in deploy.
- **MINOR 2** (Step A sufficient): confirmed.
- **Non-blocking** namespace sweep noted; no other tracked systemd unit at risk.

### Round 5 — FAIL → addressed
- **MAJOR** (`systemctl edit --runtime` writes under `/run/` and won't override units installed under `/etc/`): replaced runtime override with a persistent drop-in at `/etc/systemd/system/corpus_delta_ingest.service.d/test-failure.conf`, manually removed after.
- **MINOR** (cleanup didn't reset the failed-state flag): added `sudo systemctl reset-failed corpus_delta_ingest.service` to cleanup.
- **Semantic clarification from Codex r5:** `SuccessExitStatus=75` makes exit 75 (lock-contention skip) "success" to systemd, which means `$SERVICE_RESULT = success` would also trigger a digest send for empty-skip runs. Added `$EXIT_STATUS = 0` to the ExecStopPost gate so the digest only sends on truly-completed runs.
- **Confirmed by Codex r5:** Step A `ExecStopPost` syntax + `-` prefix placement correct; `/bin/false` is the right failure payload; `$SERVICE_RESULT` available to `ExecStopPost=` use.

### Round 4 — FAIL → addressed
- **MAJOR** (`ExecStopPost=` runs after BOTH successful stops AND failed starts; current shape isn't best-effort or success-gated — a Telegram outage can fail an otherwise-successful ingest): added `-` prefix (ignore exec failures) + `$SERVICE_RESULT = success` gate to both filings (Step A) and transcripts wherever ExecStopPost appears.
- **MINOR 1** ("stop service mid-run" alert test is flaky as operator-requested termination): replaced with deterministic transient `ExecStart=/bin/false` override via `systemctl edit --runtime`.
- **MINOR 2** (Section 10 still listed `bootstrap_env.py` as code change despite "no change needed"): removed entirely from files-to-change list.
- **Confirmed by Codex r4:** `_BOOTSTRAP_ENVIRONMENT` private-API probe is acceptable for one-off verification.

### Round 3 — FAIL → addressed
- **MAJOR 1** (Step B verification doesn't prove **prod** namespace — `bootstrap_env._environment()` defaults to dev when `ENVIRONMENT` unset): added explicit precondition that prod `.env` must have `ENVIRONMENT=prod`/`production` + `assert _BOOTSTRAP_ENVIRONMENT == 'prod'` + `assert _BOOTSTRAP_USE_SSM is True` to the verification snippet.
- **MAJOR 2** (Section 6 risk row understated SSM access — `bootstrap_env` iterates BOTH `shared` AND `broker` tiers; prod forces `require_broker_tier=True`): risk row corrected to call out both tiers and the hard-error semantics.
- **MINOR 1** (transcripts lock tests missing from files-to-change): added `tests/test_corpus_phase3_transcripts.py` mirroring `tests/test_corpus_phase1_delta_ingest.py:508` lock-contention shape.
- **MINOR 2** (Section 10 summary listed `bootstrap_env.py` as edit target — wrong, allowlist lives in `provision_ssm_params.py`): Section 10 rewritten with the canonical files-to-change list, removed `bootstrap_env.py`.
- **Confirmed by Codex r3:** `SuccessExitStatus=75` is the correct systemd semantic (suppresses `OnFailure` for exit 75); transcript ExecStart args are right after `--lock-file`/`--lock-timeout-seconds` are added.

### Round 2 — FAIL → addressed
- **MAJOR 1** (`LOCK_UNAVAILABLE_EXIT_CODE=75` not a clean systemd skip without `SuccessExitStatus=75`): added to BOTH the existing filings unit (Step A) AND the new transcripts unit (Step D). Without this, every lock-contention run would have fired the alert pipeline.
- **MAJOR 2** (transcripts systemd ExecStart left `[other args as the script's CLI requires]` placeholder): replaced with concrete prod paths matching filings — `/mnt/hank-data/risk_module/{filings.db,filings}` instead of the script's repo-local defaults.
- **MAJOR 3** (Step B verification command was `import bootstrap_env` only — does not hydrate): updated to call `bootstrap_env.bootstrap(required=['TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID'])` explicitly before checking `os.environ`.
- **MINOR** (lock helper inline, not shared): decision locked — duplicate into transcripts; extract to `core/corpus/lock.py` filed as F-CORPUS-LOCK-HELPER-EXTRACT.
- **MINOR** (transcript success digest planned but unsupported by the script): dropped from plan; filed as F-CORPUS-TRANSCRIPTS-DIGEST.
- **MINOR** (allowlist test counts need bumping): added `tests/test_provision_ssm_params.py:113,230` to the files-to-change list with concrete count changes (1/11→1/13, 10/11→12/13).
- **Non-blocking** (stale open questions, SSM access description): Section 7 cleaned up to "no open questions remain"; Section 6 risks-table SSM line corrected to "read + KMS decrypt access; successful hydration is silent."

## 9. Codex review request

Send sections 1–6 to Codex with prompt:
> Review this plan. The goal: restore corpus freshness on prod after 13 days of silent failure. Three independent root causes (RC-1 systemd not in venv, RC-2 no Telegram secret accessible, RC-3 transcripts delta never on EC2). The plan addresses all three plus catch-up and post-deploy import smoke. Focus on:
> (a) Step A — is the venv-python ExecStart sufficient, or are there other env vars (PYTHONPATH, etc.) the bash login shell was providing that need to be set explicitly?
> (b) Step B — does the `notify_with_bootstrap.py` wrapper correctly hand off env to the shell script? Will `subprocess.call` inherit `os.environ` changes from `bootstrap_env`? Are there race / shell-quoting issues with the alert ExecStart's message construction?
> (c) Step D — does mirroring the filings systemd unit pattern miss anything specific to transcripts (different DB lock? different rate-limit profile)?
> (d) Step E — is a one-line import smoke enough, or should we also run a `--dry-run` on the corpus script?
> (e) Namespace sweep — what OTHER prod entry points import `bootstrap_env` and could break the same way? Sweep `scripts/*.py` for `import bootstrap_env` and confirm they all have a venv-aware launcher.
> (f) Anything missed.
>
> Iterate until PASS. Do not skip findings tagged non-blocking.

## 10. Implementation note

This plan mixes config/deploy and code:
- **Code changes:**
  - `scripts/notify_with_bootstrap.py` (new, ~40 lines)
  - `scripts/provision_ssm_params.py` — append `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` to shared allowlist
  - `tests/test_provision_ssm_params.py` — bump shared-count assertions (1/11→1/13, 10/11→12/13)
  - `scripts/corpus_phase3_delta_transcripts.py` — lock-arg parity + helper duplication
  - `tests/test_corpus_phase3_transcripts.py` — new lock-semantics tests mirroring filings
  - `scripts/deploy.sh` — one-line import-smoke append
- **Config/deploy changes:**
  - Updated `docs/deployment/systemd/corpus_delta_ingest.service` (venv ExecStart + `SuccessExitStatus=75`)
  - Updated `docs/deployment/systemd/corpus_delta_ingest_alert.service` (calls `notify_with_bootstrap.py`)
  - New `docs/deployment/systemd/corpus_transcripts_delta.{service,timer}`
  - New `docs/deployment/systemd/corpus_transcripts_delta_alert.service`
  - SSM param provisioning for 4 new params
  - Manual EC2 actions: `sudo cp` + `daemon-reload` + `systemctl enable --now`
  - Confirm prod `.env` has `ENVIRONMENT=prod`

Per the mandatory plan-first workflow: code changes go through Codex MCP implementation after this plan PASSes review. Config/deploy steps are operator actions that the user executes (or asks me to execute with explicit approval since they touch prod). The plan is the contract.
