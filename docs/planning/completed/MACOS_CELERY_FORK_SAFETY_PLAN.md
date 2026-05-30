# macOS Celery Fork-Safety — Threads Pool + Recycle

**Status:** Part A **SHIPPED + LIVE-VERIFIED** (`985262b2`; threads pool, real syncs run in-thread, 0 crashes). Part B (B1 launchd recycle) implemented + live-tested → **NON-VIABLE, DISABLED** — see the §4 callout (recycle-launched workers never connect to the broker under launchd's env; 4 bugs surfaced in testing). **Next: B-front-door** (services-mcp-owned recycle). Part A Codex path: r0 BLOCK (4) → r3 PASS.
**ARCHIVED to `docs/planning/completed/` 2026-05-29** — Part A is the shipped deliverable; the open follow-up (B-front-door) is tracked live at AI-excel-addin `docs/design/services-mcp-recycle-interval-task.md` + `docs/TODO.md`.
**Scope:** local/macOS only. Production (EC2/Linux) runtime behavior must be unchanged.
**Owner repo:** risk_module (all changed files live here).

---

## 1. Problem

On macOS, Celery's **prefork** pool forks a worker child that then resolves a
hostname via `socket.getaddrinfo` (the redis broker/result-backend connection,
and — during real sync tasks — external broker API hosts such as
`api.schwab.com`). On macOS 26 `getaddrinfo` routes through Apple's
`Network.framework` (NAT64 synthesis → `os_log`), which is **not fork-safe**, so
the forked child segfaults:

```
*** multi-threaded process forked *** / crashed on child side of fork pre-exec
  socket_getaddrinfo -> getaddrinfo -> _gai_nat64_second_pass
    -> Network.framework (nw_path_evaluator_evaluate) -> os_log -> SIGSEGV
```

`task_acks_late=True` + `task_reject_on_worker_lost=True` (celery_app.py:52-53)
re-queue a task whose worker died, so each crash re-runs → re-forks → re-crashes:
an infinite retry loop. Observed: ~25 crash reports in a ~10-minute window
(2026-05-28).

### Evidence (already gathered)
- **Idle prefork worker boots clean** (0 crashes): a contained baseline run
  reached `celery@… ready` with `concurrency: 4 (prefork)` and no segfault.
  ⇒ the crash is in **task execution**, not pool warm-up.
- redis-py 7.3.0 resolves the host with `socket.getaddrinfo(...)` — matches the
  crash stack (`socket_getaddrinfo`).
- `CELERY_BROKER_URL` is unset in `.env` → defaults to `redis://localhost:6379/1`
  (celery_app.py:32), a hostname.
- Prior art: this file already neutralizes one macOS fork trigger —
  `os.environ.setdefault("PGGSSENCMODE", "disable")` (celery_app.py:24-26, commit
  `e8f16bee`) stops libpq's GSS probe. The current crash is the same *class*, a
  different trigger (Python `socket.getaddrinfo`).

### Why a surgical "fix the probe" approach was rejected
The redis trigger is IP-swappable (`localhost` → `127.0.0.1`), but the workers'
actual job is resolving **external** broker hostnames in the forked child, which
cannot be turned into IPs. Neutralizing one probe cannot make this workload safe
under prefork on macOS. The only fix **certain by construction** is to not fork.

### Why production is unaffected
Prod runs these workers under **systemd on EC2/Linux** with its own unit files
(`docs/ops/CELERY_DEPLOYMENT.md:194-199`) — it never reads this repo's
`services.yaml`/`Makefile`. On Linux `getaddrinfo` does not route through Apple
frameworks, so prefork + per-task recycling is correct and optimal there.

---

## 2. Goal & constraints

1. Eliminate the macOS crash **certainly** (not best-effort).
2. Keep production **behaviorally unchanged**: on Linux the gate resolves to
   `prefork` with the existing concurrency + `worker_max_tasks_per_child` +
   `worker_max_memory_per_child` recycling. (The shared module *file* changes; the
   Linux *runtime behavior* does not.)
3. Preserve memory-leak protection **locally** at a coarser grain (Part B).
4. **Do not introduce a correctness regression** by moving from process isolation
   (prefork) to shared-process threads — see §3.2/§3.3/§3.4.
5. Cover **all** local launch paths: services-mcp (`services.yaml`), the
   `Makefile` targets, and manual `celery … worker`.

---

## 3. Part A — macOS threads pool, done safely

**Primary file:** `workers/celery_app.py`. **Local-launch files:** `services.yaml`,
`Makefile` (macOS dev launch only — never prod systemd).

### 3.1 Pool gate + concurrency pin (the crash fix)
1. Add a real `import sys` near `import os` (celery_app.py:5). NOTE: `sys` is
   currently imported only transiently as `_bootstrap_sys` and `del`'d at line 17,
   so it is **not** in module scope today (verified r0 #6).
2. In `app.conf.update(...)` add:

```python
    # macOS prefork forks into Apple Network.framework on getaddrinfo
    # (fork-unsafe) -> SIGSEGV. Threads pool locally (no fork); prefork on
    # Linux/prod where fork is safe + optimal. Mirrors the PGGSSENCMODE guard.
    worker_pool="threads" if sys.platform == "darwin" else "prefork",
    # Threads share one process, so concurrent tasks would share broker-SDK
    # singletons that prefork kept isolated per child. Pin macOS concurrency to 1
    # to preserve single-flight-per-worker semantics. No-op on Linux/prefork.
    worker_concurrency=1 if sys.platform == "darwin" else app.conf.worker_concurrency,
```

`"threads"` is a valid alias (no fork; tasks run in a `ThreadPoolExecutor` of the
main process — r0 #5). On EC2 `sys.platform == "linux"` → `prefork` (r0 #8).

3. **Local launch commands (services.yaml + Makefile only):** change the CLI
   `--concurrency=2` → `--concurrency=1` on slow/fast/orders
   (`services.yaml:138,166,194`; `Makefile:47,50,53`). Rationale:
   - The explicit CLI `--concurrency=2` would otherwise re-introduce the
     shared-state race that §3.1.2's config pin prevents. Pin in **both** places so
     no CLI/config precedence ambiguity remains (r0 #5 noted CLI does **not**
     reliably override a configured value in this code path; belt-and-suspenders).
     The config pin also governs manual `celery worker` launches that pass no flag.
   - **Keep** the `--max-tasks-per-child` / `--max-memory-per-child` flags as-is:
     they are silently ignored under threads (r0 #7 — Codex booted a threads worker
     with both; reached ready, no warning/error), so removing them buys nothing for
     correctness while churning `tests/workers/test_celery_app_config.py`. They stay
     active + meaningful on Linux/prefork.
   - `celery_worker_maint` is already `--concurrency=1`; leave it.
   - **Prod systemd unit files are NOT touched** — they keep prefork + per-task
     recycling. (`services.yaml`/`Makefile` are local-launch-only — r1 #6.)
   - **Test:** if `tests/workers/test_celery_app_config.py` pins `--concurrency=2`
     for slow/fast/orders, update it to `=1` (r1 #6).

### 3.2 Loss of task time-limit enforcement → macOS-gated client timeouts (r0 #1 / r1 #1)
The threads pool **cannot** kill a hung task; `task_time_limit=120` /
`task_soft_time_limit=100` (celery_app.py:48-49) are prefork-only. So an unbounded
broker HTTP call would pin the worker's single thread forever and silently stop it
draining its queue. Codex r1 verified the current state:
  - **Plaid — unbounded.** `Configuration(...)` carries no timeout
    (`brokerage-connect/brokerage/plaid/client.py:82`); SDK calls pass no
    `_request_timeout` (`:313`). **Must fix.**
  - **SnapTrade — unbounded, and NOT fixable via a public kwarg** (r2 #1). The
    public methods (`list_user_accounts(...)` etc., `:175`) accept no `timeout`/
    `**kwargs`, and `Configuration` has no timeout field
    (`snaptrade_client/configuration.py:122`) — passing `timeout=`/`request_timeout=`
    raises `TypeError`. The only timeout seam is the REST chokepoint
    `RESTClientObject.request(..., timeout=None)` (`snaptrade_client/rest.py:103`),
    reached via `api_client.call_api`. **Mechanic (chosen):** on darwin only, in the
    SnapTrade client wrapper's `__init__`, wrap the constructed instance's
    `api_client.call_api` (or its `rest_client.request`) to inject a default 30s
    timeout **when the caller passes none**. One gated patch at construction; every
    call inherits the bound. Non-darwin passes nothing → SDK behaves exactly as
    today. (Alternative rejected: rewriting each call site to the private
    `_..._oapg(..., timeout=...)` — spreads underscore-private API across N sites.)
    **Implementer notes (r3):** the shared `ApiClient` is reachable via a namespace
    (e.g. `client.account_information.api_client.rest_client`), not `client.api_client`.
    Replace **only** `timeout is None` (generated calls pass `timeout=None`) — do NOT
    `setdefault` — and preserve any non-`None` caller timeout (incl. tuple /
    `urllib3.Timeout`).
  - **Schwab — OK** (schwab-py sets a default 30s client timeout). No change.
  - **IBKR — OK** (bounded connect/request/snapshot timeouts —
    `brokerage-connect/brokerage/ibkr/config.py:59`, `connection.py:105`,
    `relay_adapter.py:82`). No change.

**Resolution (in-scope, hard pre-rollout gate):** add a client-side HTTP timeout to
the Plaid and SnapTrade calls, **gated to macOS** (`sys.platform == "darwin"` ⇒ a
bounded timeout e.g. 30s, comfortably under the 120s prod task limit; otherwise
pass nothing → **prod path byte-for-byte unchanged**, prod keeps relying on its
prefork 120s hard kill). This bounds the macOS single thread without altering prod.
  - Belt-and-suspenders: Part B's recycle bounds a still-wedged worker; manual
    `service_restart <worker>` is the immediate remedy.
  - **Open upgrade (NOT in this change):** making the timeout unconditional would
    also harden prod (a strict improvement) but is a prod behavior change — left to
    the operator's call; default here is macOS-gated per the standing prod
    constraint.

### 3.3 Process-init/shutdown signals do not fire under threads (r0 #3 — corrected)
`worker_process_init` / `worker_process_shutdown` (celery_app.py:69-84) are
**prefork-only** signals; under the threads pool they **do not fire at all**
(not "once per process" as the r0 draft wrongly stated). Their job was to drop
DB pools/connections inherited across `fork()`. In a non-forking single-process
threads worker there is no inherited-FD problem, so *not firing* is correct — with
one exception handled in §3.4. Document this explicitly in the code comment so a
future reader does not "fix" the missing per-child reset.

### 3.4 Thread-mode startup DB-pool reset (r0 #4)
`on_worker_ready` runs `reconcile_on_startup()` in-process (celery_app.py:61-66),
which uses the DB pool (`services/sync_jobs_service.py:236-261`) and is where the
pre-existing psycopg `"connection already closed"` wart fires. Under prefork the
per-child `worker_process_init` reset meant task children never inherited that
parent pool state; under threads, task threads **share** the very pool
`reconcile_on_startup()` just used. Add a once-at-ready reset that runs **only**
under the threads pool, after reconcile. Two corrections from r1 #3:
(i) `close_pool`/`reset_db_availability` are **not** in scope in `on_worker_ready`
today — it imports only `reconcile_on_startup` (celery_app.py:61); the pool/reset
imports are local to `on_worker_process_init` (celery_app.py:69), so add the same
local imports here. (ii) Celery logs-and-swallows signal-handler exceptions
(`celery/utils/dispatch/signal.py:278`), so if `reconcile_on_startup()` raises
(`services/sync_jobs_service.py:236`) the reset would be skipped and the worker
would keep running with the stale pool — run the reset in a `finally`:

```python
@worker_ready.connect
def on_worker_ready(**_):
    # exact imports worker_process_init uses (they live in DIFFERENT modules — r2 #2)
    from app_platform.db.pool import close_pool
    from database import reset_db_availability
    try:
        reconcile_on_startup()
    finally:
        if app.conf.worker_pool == "threads":   # macOS: process-init reset never fires
            try:
                close_pool()
                reset_db_availability()
            except Exception:
                log.exception("thread-mode DB-pool reset failed")  # don't mask a reconcile error
```

This mirrors the prefork per-child reset's intent (give task execution a clean
pool) and is a true **no-op on Linux/prefork** (the branch is gated on the threads
pool). **Validation item:** confirm the psycopg `on_worker_ready` "connection
already closed" wart is resolved / no worse.

### Why config, not a `--pool` CLI flag
`app.conf.worker_pool` is the worker's default when no `--pool` is passed;
none of the three launch paths pass `--pool` (`services.yaml:126-246`,
`Makefile:46-59`), so the config value governs all of them — including manual
launches. (r0 #5 nuance: a manual `--pool=prefork` would **not** override the
configured value in this celery code path; acceptable — we never want prefork on
macOS anyway.)

---

## 4. Part B — coarse recycle (replaces per-task reclamation, macOS-only)

> **⚠️ STATUS (2026-05-29): B1 IMPLEMENTED, LIVE-TESTED, FOUND NON-VIABLE → DISABLED.**
> `launchctl kickstart` testing of `scripts/recycle_celery_local.py` surfaced four
> issues. Three were fixed: (1) `_pid_alive` false-positive on zombies — the
> recycler isn't the workers' parent, so killed procs zombie until services-mcp
> reaps them and `os.kill(pid,0)` reports them alive → spurious abort (fixed: `ps`
> state check); (2) launchd SIGKILLs the job's process group when the script exits,
> killing the just-started workers (fixed: `start_new_session=True`); (3) the
> hand-rolled `.env` parser kept inline comments → injected
> `PORTFOLIO_RISK_LRU_SIZE='100  # default 100'` which shadowed bootstrap_env's
> correct value → workers crashed on boot (fixed: python-dotenv `dotenv_values`).
> **The blocker (4): even after 1–3, recycle-launched workers never connect to the
> redis broker** — controlled lsof showed a services-mcp worker holding ~10
> ESTABLISHED conns to `:6379` and logging `ready`, while a recycle-launched worker
> had zero and logged nothing past app-module import. Root cause: launchd's minimal
> environment differs from the environment services-mcp inherited, and reproducing
> it from a standalone script is a rabbit hole. The LaunchAgent has been
> `bootout`+`disable`d. **The correct fix is B-front-door** (see §4.3): services-mcp
> already launches these workers correctly, so the recycle belongs there, not in a
> separate launchd authority. The fixed-but-disabled script + plist remain in the
> repo as a base/record; do not re-enable B1.


The threads pool shares one process, so per-task memory reclamation
(`max_tasks_per_child`/`max_memory_per_child`) is gone on macOS. Re-add a coarse
guard, **macOS/local only** (Linux/prod keeps per-task recycling via prefork).
**Chosen mechanism: B1 — a launchd periodic recycle.**

### 4.1 Relaunch authority — RESOLVED to (b) generate from services.yaml (r0 Part B)
A **Python** recycle script (`scripts/recycle_celery_local.py` — YAML parsing ⇒
Python, not shell) that:
- Parses the five Celery services from `services.yaml` (single source of truth),
  honoring each entry's `command`, `env_file`, `env`, and `pgrep_pattern`.
- Order: **stop beat → stop the four workers → start workers → start beat.**
- **Stop semantics must be kill-escalating (r1 #2).** A warm stop cannot be
  trusted: the threads pool's `on_stop()` calls `ThreadPoolExecutor.shutdown()`
  with blocking wait semantics (`celery/concurrency/thread.py:41`), so a wedged
  task makes a warm shutdown **hang**. The recycler must: send **SIGTERM** → wait a
  bounded grace (e.g. 30s) → if still alive, **SIGKILL** (cold) → log the
  escalation. This is precisely what lets Part B recover the §3.2 wedged-worker
  case that the threads pool otherwise can't. (Direct main-PID SIGKILL suffices for
  a threads worker; if the recycler starts workers in a new session or a task
  spawns subprocesses, signal the **process group** instead — hardening note, r2.)
- `cd`s to repo root (or sets the equivalent import path) before
  `python3 -m celery` so `bootstrap_env` self-hydrates `.env`
  (`bootstrap_env.py:34-35,274-275` — r0 #10).
- Takes an **exclusive flock** so two recycler runs cannot overlap.
- **Refuses to run (no-op + warn)** if it detects Celery worker processes that do
  **not** match the catalog `pgrep_pattern`s (e.g. a `Makefile`-launched worker
  with no `-n slow@/fast@/...`), to avoid double-launch / orphaned PIDs.

This keeps `services.yaml` authoritative (no command drift, unlike hardcoding) and
makes the script idempotent + refuse-unsafe rather than clever.

### 4.2 launchd trigger
A `launchd` agent (`ops/launchd/com.<user>.celery-recycle.plist`,
`StartCalendarInterval`, nightly off-hours e.g. 04:00 local) invokes the recycle
script. Nightly cadence is accepted as the first local-only leak bound (r0 Part B:
RSS-threshold recycling is more precise but **not materially better** without
evidence of same-day growth; deferred as **B-RSS**).

### 4.3 Rejected / deferred
- **B-RSS** (RSS-threshold watchdog): deferred — revisit only if same-day growth is observed.
- **B-front-door** (a `recycle_interval`/`max_lifetime` primitive in services-mcp
  so the catalog owns periodic restart): architecturally cleanest, avoids a second
  launch authority entirely; larger build, **recommended long-term home**, out of
  scope here.

### Honest sizing
For this local, I/O-bound, intermittently-run, now-single-flight workload the leak
risk is low (most resident memory is shared baseline import cost, not leak). Part B
is belt-and-suspenders; nightly recycle bounds growth to ~one day.

---

## 5. Validation

1. **Threads worker boots clean** on macOS: no segfault, reaches `ready`,
   `concurrency: 1 (thread)`. The kept `--max-*-per-child` flags are silently
   ignored under threads (r0 #7 / r2 #3) — no warning/error expected.
2. **No-fork proof:** confirm under load no `fork()`/child crash reports appear
   (`~/Library/Logs/DiagnosticReports/Python-*.ips`) — crash count holds at **0**
   over a real sync cycle.
3. **Single-flight:** confirm only one task runs at a time per worker (no
   concurrent use of a shared broker SDK client) — i.e. concurrency really is 1.
4. **A real sync task runs in a thread** and resolves an external broker hostname
   **in-process (no fork)** without crashing.
5. **§3.4 DB reset:** the psycopg `on_worker_ready` "connection already closed"
   wart is resolved / no worse; tasks execute DB work cleanly post-reset.
6. **§3.2 macOS timeouts:** Plaid + SnapTrade calls carry a bounded client-side
   timeout on the macOS path (and the Linux path is unchanged / passes none).
7. **Prod gate:** the config resolves to `prefork` and existing concurrency when
   `sys.platform != "darwin"` (unit test asserting the gate on a faked platform).
8. **Part B recycler:** dry-run proves it parses `services.yaml`, restarts in the
   beat→workers order, holds the lock, refuses when an off-catalog celery worker is
   present, and — against a deliberately wedged worker — escalates SIGTERM→SIGKILL
   within the grace window and restarts cleanly (r1 #2).
9. **Test fixup:** `tests/workers/test_celery_app_config.py` passes after any
   `--concurrency` assertion update (r1 #6).

---

## 6. Rollout / sequencing

1. Land Part A (celery_app.py + services.yaml + Makefile) and Part B.
2. Reload the stale services-mcp daemon so it parses the post-cleanup catalog
   (separate known blocker — `unknown field(s): external, start_hint`).
3. `service_start` the workers (threads, concurrency 1 on macOS); confirm crash
   count stays 0 over a sync cycle.
4. Install + `launchctl load` the Part B agent.

---

## 7. Files

- `workers/celery_app.py` — §3.1 `import sys` + `worker_pool`/`worker_concurrency`
  gate; §3.3 comment; §3.4 thread-mode DB reset in `on_worker_ready`.
  **agent-mail reserve before edit.**
- `services.yaml` — slow/fast/orders → `--concurrency=1` (keep `--max-*-per-child`;
  local launch only). **agent-mail reserve.**
- `Makefile` — same `--concurrency=1` change on the celery worker targets
  (~lines 47-59, local launch only). **agent-mail reserve.**
- `brokerage-connect/brokerage/plaid/client.py` + `.../snaptrade/client.py` — §3.2
  macOS-gated client HTTP timeout. **agent-mail reserve.**
- `tests/workers/test_celery_app_config.py` — update if it pins `--concurrency=2`
  for slow/fast/orders (r1 #6).
- `scripts/recycle_celery_local.py` (new) + `ops/launchd/com.<user>.celery-recycle.plist`
  (new) — Part B, macOS/local only.
- `docs/ops/CELERY_DEPLOYMENT.md` — extend the "macOS Fork Safety" section
  (lines 210-212; also fix its stale `celery_app.py:9` ref → `:24-26`) to document
  the pool gate, concurrency pin, the §3.2 time-limit caveat, and the recycle.
  **agent-mail reserve.**

---

## 8. Process

- **Review:** Codex (read-only) → iterate to PASS. (r0 BLOCK resolved here.)
- **Implement:** via Codex MCP — `approval-policy: never`, `sandbox: workspace-write`,
  `cwd` = risk_module repo root, inherit model/reasoning from `~/.codex/config.toml`.
  All changes within risk_module → no cross-repo escalation needed.
- **Coordination:** agent-mail reserve the four shared files above before edits.
- **After implement:** flip this doc's status to DONE, update the
  `CELERY_DEPLOYMENT.md` macOS section, and update the cross-session memory
  landmine note.

---

## 9. Out of scope

- Production celery launch (systemd/EC2) — untouched.
- The services-mcp staleness blocker — tracked separately.
- The `127.0.0.1` broker swap — superseded by the threads pool.
- **B-RSS** and **B-front-door** — recommended future work, not this change.
- Making the broker SDK clients thread-safe for concurrency > 1 — unnecessary
  given the §3.1 concurrency=1 pin; would only matter if macOS ever wanted >1.

---

## 10. Codex review — findings & resolutions

### r2 (verified r1 #2/#3 resolved; 1 blocker)

| r2 finding | Severity | Resolution in this revision |
|---|---|---|
| #1 SnapTrade timeout not implementable via public SDK kwarg (Plaid OK via `_request_timeout`) | BLOCKING | §3.2 — darwin-gated wrap of the SnapTrade `call_api`/`rest_client.request` chokepoint (`rest.py:103`) injecting a default 30s timeout |
| #2 §3.4 placeholder import wrong (funcs in two modules) + finally could mask reconcile error | NON-BLOCKING | §3.4 — real imports (`app_platform.db.pool` / `database`) + reset wrapped in try/except-log |
| #3 §5 said "now-removed" flags, contradicting §3.1 "keep" | NON-BLOCKING | §5 #1 reworded — flags kept, inert under threads |
| recycler SIGKILL-to-process-group | hardening note | §4.1 note added |

### r1 (verified r0 #2/#3 fully resolved; 3 new blockers)

| r1 finding | Severity | Resolution in this revision |
|---|---|---|
| #1 Plaid + SnapTrade HTTP calls unbounded → hung thread (no task-kill under threads) | BLOCKING | §3.2 — macOS-gated client timeout on Plaid + SnapTrade, in-scope (Schwab/IBKR already bounded) |
| #2 Recycler warm-stop can hang on a wedged threads worker | BLOCKING | §4.1 — SIGTERM → bounded grace → SIGKILL escalation + log |
| #3 §3.4 snippet: `close_pool`/`reset_db_availability` not in scope; reset skipped if reconcile raises | BLOCKING | §3.4 — local imports in `on_worker_ready` + run reset in `finally` |
| #6 `test_celery_app_config.py` asserts the worker flags | NON-BLOCKING | §7 — update the `--concurrency` assertion; keep `--max-*-per-child` flags so its memory assertion is unaffected |
| #2/#3 from r0 confirmed resolved; worker_concurrency Linux branch valid | NON-BLOCKING | confirmed by Codex |

### r0 (initial)



| r0 finding | Severity | Resolution in this revision |
|---|---|---|
| #1 Threads pool drops task time-limit enforcement | BLOCKING | §3.2 — accepted local-only + provider-timeout audit (val #6) + Part B recycle bound |
| #2 Shared broker-SDK singletons race under threads @ concurrency=2 | BLOCKING | §3.1.3 — pin macOS concurrency to 1 (config + CLI) → single-flight per worker |
| #3 `worker_process_init/shutdown` don't fire under threads (draft said "once") | BLOCKING | §3.3 — corrected; documented as intentionally not-fired (no inherited-FD problem) |
| #4 `on_worker_ready` DB pool shared by task threads | BLOCKING | §3.4 — threads-only `close_pool()`+`reset_db_availability()` after reconcile |
| #5 Pool-gate precedence claim imprecise (CLI ≯ configured pool) | NON-BLOCKING | §3.1.3 / "Why config" — pin both config + CLI; no reliance on CLI override |
| #6 `import sys` claim correct | NON-BLOCKING | confirmed |
| #7 max-child flags don't error under threads (Codex booted to verify) | NON-BLOCKING | confirmed; flags KEPT (inert under threads) — see §3.1.3, revised after r1 |
| #8 "byte-for-byte" overstated | NON-BLOCKING | §2.2 reworded to "behaviorally unchanged on Linux" |
| #9 ops doc stale `celery_app.py:9` ref | NON-BLOCKING | §7 — fix to `:24-26` when editing the doc |
| #10 recycle must `cd` to repo root for bootstrap | NON-BLOCKING | §4.1 — encoded in the script's contract |
| Part B authority | recommendation | §4.1 — adopted (b) generate-from-services.yaml + flock + refuse-unsafe |
