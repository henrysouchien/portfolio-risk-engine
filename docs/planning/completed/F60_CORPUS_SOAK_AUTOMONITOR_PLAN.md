> **✅ SHIPPED — F60 auto-monitor soak gate live (commit `38aba763`; see `docs/TODO_COMPLETED.md`). Moved from `docs/planning/` during 2026-05-26 docs cleanup.**

# F60 — Corpus cron-continuity auto-monitor

**Scope:** Surface beat-cron silence within ~1 day of it happening, instead of within weeks (manually) or via downstream user-visible failure (the F58 / F59 path that surfaced the original incident).

**Trigger:** F60 in `docs/TODO.md` (filed 2026-05-03 during F59 investigation). The 4 corpus crons added at Phase 1 ship 2026-04-30 sat dormant for 3 days because `celery_beat` had been running since 2026-04-16 and Celery's scheduler doesn't auto-reload schedule changes. F51's manual `corpus_phase1_soak_check.py --days 14` would have detected this on day 1, but nobody ran it.

**Effort:** ~25 LOC production + ~50 LOC test. Half-day end to end.

---

## Decisions taken (closed before this plan)

1. **Fix shape (a) from F60**: fold the soak gate into the existing `corpus.health_report_daily` task. Cheapest, piggybacks on infrastructure already on disk + already wired to `_notify_or_log`. Decision rationale: the "external monitor outside the broken scheduler" framing is more robust on paper but adds a whole notification pipeline; we're solving for "next time beat goes silent, we hear about it within 24h," not for "beat is actively hostile."
2. **Window auto-adapts during ramp**: `days = max(1, min((date.today() - PHASE1_SHIP_ANCHOR).days, 14))`. Without this, the soak gate would fire CRITICAL daily for the first ~2 weeks post Phase 1 ship because most days in a 14-day window would have no log files yet. Auto-adapt closes that window over time without operator intervention. Anchor is a hardcoded `date(2026, 4, 30)` constant; once today exceeds anchor + 14 days the constant is functionally inert.
3. **Soak result is transient**: included in the task's return payload (visible via celery result backend / worker logs) but NOT persisted to a daily JSONL. The underlying logs already exist — a soak-result log would be redundant.

---

## Files touched

| File | Change | Approx LOC |
|---|---|---|
| `workers/tasks/corpus.py` | Extend `health_report_daily()` with soak invocation + alert path | +20 |
| `tests/test_workers_corpus_tasks.py` | NEW. Cover happy/soak-fail/soak-raise paths | +50 |

That's it. No changes to `corpus_phase1_soak_check.py` (consumed as-is via the `check_soak()` pure function) or `workers/beat_schedule.py` (the existing 07:00 UTC entry continues to fire `corpus.health_report_daily`).

---

## Concrete code shape

### `workers/tasks/corpus.py` — diff intent

Existing:

```python
@shared_task(name='corpus.health_report_daily')
def health_report_daily() -> dict[str, Any]:
    code = corpus_health_report.main([])
    result = {'ok': code == 0, 'exit_code': code}
    if code != 0:
        _notify_or_log('CRITICAL', 'Corpus health report failed', result)
    return result
```

After:

```python
PHASE1_SHIP_ANCHOR = date(2026, 4, 30)
SOAK_WINDOW_MAX_DAYS = 14


@shared_task(name='corpus.health_report_daily')
def health_report_daily() -> dict[str, Any]:
    code = corpus_health_report.main([])
    result: dict[str, Any] = {'ok': code == 0, 'exit_code': code}
    if code != 0:
        _notify_or_log('CRITICAL', 'Corpus health report failed', result)

    # F60: piggyback the soak gate so cron silence surfaces daily.
    # Window auto-adapts during the ramp window so we don't alert CRITICAL
    # daily before there are 14 days of logs to evaluate.
    today = date.today()
    days_in_window = max(1, min((today - PHASE1_SHIP_ANCHOR).days, SOAK_WINDOW_MAX_DAYS))
    try:
        soak = corpus_phase1_soak_check.check_soak(
            log_dir=corpus_phase1_soak_check.DEFAULT_LOG_DIR,
            health_dir=corpus_phase1_soak_check.DEFAULT_HEALTH_DIR,
            as_of=today,
            days=days_in_window,
            max_average_errors=2.0,
        )
    except Exception as exc:  # noqa: BLE001 — soak is monitoring; never crash the host task
        _notify_or_log('WARNING', 'Corpus soak check raised', {'error': str(exc)})
        return result

    result['soak'] = soak
    if not soak['ok']:
        _notify_or_log('CRITICAL', 'Corpus soak gate failed', soak)
    return result
```

New imports:

```python
from datetime import date  # already imported via `datetime`; add bare `date`
from scripts import corpus_phase1_soak_check
```

The existing `from scripts import corpus_health_report, corpus_phase1_delta_ingest, corpus_phase3_delta_transcripts` becomes a 4-tuple including `corpus_phase1_soak_check`.

### Why thresholds match `corpus_phase1_soak_check.main([])` defaults

The soak script's CLI defaults are `--max-average-errors 2.0`, `--max-drift-per-run 5`, `--max-average-transcripts-errors 2.0`. The wrapper passes `max_average_errors=2.0` explicitly; the other two threshold params on `check_soak()` already default to `5` and `2.0` (visible in `corpus_phase1_soak_check.py:31-32`), so we don't need to thread them. If thresholds need to change later, they live in one place (`check_soak` defaults).

---

## Test plan — `tests/test_workers_corpus_tasks.py`

Pattern: monkeypatch the underlying `corpus_health_report.main` and `corpus_phase1_soak_check.check_soak` so the test never opens the corpus DB / filesystem. Capture `_notify_or_log` calls via monkeypatch. Capture `check_soak` invocations by replacing it with a recorder that stores call kwargs.

Four mandatory cases:

1. **Happy path** — `corpus_health_report.main` returns 0, `check_soak` returns `{ok: True, days: N, ...}`. Assert:
   - Returned dict has `ok=True, exit_code=0, soak={...}`.
   - `_notify_or_log` is NOT called (no failures, no exceptions).
   - `check_soak` was called with `log_dir=corpus_phase1_soak_check.DEFAULT_LOG_DIR`, `health_dir=corpus_phase1_soak_check.DEFAULT_HEALTH_DIR`, `as_of=<today>`, `days=<expected_window>`, `max_average_errors=2.0`. (Captured kwargs from the recorder are checked exactly.)

2. **Soak gate fails** — `corpus_health_report.main` returns 0, `check_soak` returns `{ok: False, daily: [...], ...}`. Assert:
   - Returned dict has `ok=True` (health_report still passed) and `soak.ok=False`.
   - `_notify_or_log` IS called once with `level='CRITICAL'`, `message='Corpus soak gate failed'`, payload includes `ok=False`.

3. **Soak check raises** — `corpus_health_report.main` returns 0, `check_soak` raises `RuntimeError("malformed jsonl")`. Assert:
   - Returned dict does NOT contain a `soak` key (we returned early after the exception).
   - Returned dict has `ok=True` (host task didn't crash).
   - `_notify_or_log` IS called once with `level='WARNING'`, `message='Corpus soak check raised'`, payload contains the error string.

4. **Window adaptation (mandatory — accepted design decision)** — parameterize three sub-cases by patching the `date` symbol *inside* `workers.tasks.corpus` (NOT `datetime.date.today` directly — `date` is C-implemented and immutable). Use a fake `date` subclass whose `today()` classmethod returns a fixed date:

   ```python
   class FakeDate(date):
       @classmethod
       def today(cls):
           return cls._today
   FakeDate._today = date(2026, 5, 5)  # ship + 5
   monkeypatch.setattr('workers.tasks.corpus.date', FakeDate)
   ```

   Sub-cases:
   - Today = ship + 5 days → assert `check_soak` received `days=5`.
   - Today = ship + 50 days → assert `days=14` (capped).
   - Today = ship - 1 day (anchor in future) → assert `days=1` (floored).

---

## Acceptance

The task ships when:

1. Tests above pass locally.
2. **Worker restart**: `celery_worker_maint` (the worker subscribed to the `sync.maintenance` queue that runs corpus tasks) must be restarted after the code lands. Celery worker processes hold the parent module in memory; `worker_max_tasks_per_child=1` recycles child processes per task but children are forked from the still-old parent, so code changes do NOT hot-load. `celery_beat` does NOT need restart for this F60 code-only change (no `beat_schedule.py` change), but always does for any `beat_schedule.py` edit (per the F60 root incident).
3. **Manual exercise**: after worker restart, invoke the task once via `celery -A workers.celery_app.app call corpus.health_report_daily --queue sync.maintenance`, then `celery -A workers.celery_app.app result <task-id>`. The `--queue sync.maintenance` flag is load-bearing — beat routes `corpus.health_report_daily` to `sync.maintenance` via `workers/beat_schedule.py:105` `options.queue`, but `celery call` does NOT inherit beat options. Workers only consume named queues, so without the flag the task lands on default `celery` queue and never runs. Returned payload MUST contain a `soak` key with `ok` boolean. With today's state (corpus has been ingesting since Phase 1 ship, but cron only just started running for real today after the F60 restart), expected `soak.ok=False` and the daily breakdown shows the missing days. A CRITICAL log entry should land via `_notify_or_log` (which degrades to a structured log warning since the worker doesn't have the alerts MCP bridge).
4. **F51 closure mechanism (concrete)**: on the closure date, run `python3 scripts/corpus_phase1_soak_check.py --days 14` and paste the green summary (`"ok": true` plus the 14-day daily breakdown) into a closeout note in `docs/planning/CORPUS_PHASE1_REPORT.md`. Update F51's TODO row to reference the closeout note + F60 as the gate. The "inspect worker log" path is too weak as a closure record — the script invocation produces a self-contained artifact.

---

## Edge cases + failure modes

1. **`PHASE1_SHIP_ANCHOR` is in the future** — `(today - anchor).days < 0`. `max(1, min(negative, 14)) = 1`. Soak runs against today only. Acceptable; means we deployed F60 before Phase 1 (impossible in practice) but degrades gracefully.

2. **`check_soak` raises on malformed JSONL** — caught by try/except, alerted as WARNING. Host task still returns success for the health-report half.

3. **`check_soak` returns very large `daily` list** — task return payload includes the soak result, which includes daily breakdown. For 14 days of logs, this is ~14 small dicts. Celery result backend handles it fine. No truncation needed.

4. **Notification volume during persistent silence** — if cron stays broken for N days, `_notify_or_log('CRITICAL', ...)` fires once per day for N days. That's the desired behavior (persistent loud signal). Operator silences by fixing the cron.

5. **Soak-check anchor expires** — once today exceeds anchor + 14 days, `min(big, 14) = 14`. The anchor constant is functionally inert. Worth a comment in the code that it can be removed after that date if desired, but doesn't have to be.

6. **Worker CWD vs log paths** — `corpus_phase1_soak_check.DEFAULT_LOG_DIR = Path('logs/corpus')` and `DEFAULT_HEALTH_DIR = Path('data/corpus/health')` are CWD-relative. Producer paths split: the script-based producers (`corpus_phase1_delta_ingest`, `corpus_phase3_delta_transcripts`, `corpus_health_report`) anchor defaults to `REPO_ROOT = Path(__file__).resolve().parents[1]` — repo-root absolute. But the celery-task-resident `reconciler_daily` in `workers/tasks/corpus.py:18` uses `_DEFAULT_LOG_DIR = Path('logs/corpus')` — CWD-relative, same as the soak check. So it splits as: **delta / transcripts / health are absolute; reconciler and soak-check are CWD-relative.** A worker CWD change would break reconciler writes AND the soak check (they break together because they share the relative path), while delta/transcripts/health log writes would still land correctly. The current celery worker effectively requires CWD = repo root for its existing imports anyway, so paths align by construction today, but F60 inherits the soak-check's CWD-relative contract. Acceptable for now (matches the existing reconciler-task contract). If we want defense-in-depth later, anchor both `reconciler_daily` and the F60 `check_soak` invocation to repo-root absolute paths in one pass.

---

## Out of scope

- **Generalized cron-silence detection** beyond corpus tasks. F60 closes the loop for the corpus cron pair specifically. The same pattern (piggyback monitor on a downstream task) generalizes if other beat tasks acquire similar silence risk later, but that's a separate filing.
- **Soak result trend storage**. Decided transient (see Decisions §3). If we ever want a trend view we can rebuild it from the underlying log files.
- **Threshold tuning** (`max_average_errors=2.0` etc.). Inherited from `corpus_phase1_soak_check`'s defaults; tuning happens at the soak script level and propagates here automatically.
- **F51 closure action**. F60 enables the gate to close; the closure itself is a doc edit + V2.P1 row update in `docs/TODO.md`, deferred until the gate has held green for 14 days.

---

## Cross-references

- `docs/TODO.md` F60 (this is the implementation), F51 (manual soak check this automates), F59 (the bug whose silence motivated this).
- `scripts/corpus_phase1_soak_check.py` (the pure function consumed).
- `workers/tasks/corpus.py` (file modified).
- Phase 1 ship report: `docs/planning/CORPUS_PHASE1_REPORT.md`.
