# F159 — Corpus `file_path` Symlink Resolution Bug

**Status**: CODEX R4 PASS 2026-05-26 — ready for implementation via Codex MCP
**Filed**: 2026-05-26
**TODO row**: moved to `docs/TODO_COMPLETED.md` on 2026-05-31
**Blocks**: F160 corpus deploy round-trip (`pull → refresh → promote`)

**R2 changes from R1** (Codex R1 FAIL):
- Added missed write paths: `fmp/tools/transcripts.py:868`, `scripts/corpus_migration_transform.py:316`
- Reclassified `reingest.py:226` as storage-affecting (flows to `documents.file_path` via `new_written` recovery)
- Added repair scope for `corpus_reingest_log.old_file_path` / `new_file_path` columns
- Fixed invariant — use `os.path.abspath()` (makes absolute WITHOUT following symlinks) instead of bare `Path(...)`, which would store relative paths if caller passes relative root
- Walker fix uses same abspath helper
- Tightened repair SQL to prefix-boundary check, added log-table repair
- Reordered deploy: pause timers BEFORE code deploy, snapshot before repair, hold flock during repair
- Added in-flight non-terminal log row handling to open questions

**R3 changes from R2** (Codex R2 FAIL):
- Corrected lock path: `/run/corpus_promote.lock` (verified across `scripts/promote_corpus.sh:119`, `docs/deployment/systemd/corpus_delta_ingest.service:15`, `workers/tasks/corpus.py:28`) — R2 had the wrong path
- Added Celery beat handling — `workers/beat_schedule.py:114` registers corpus jobs when `CELERY_ENABLED && CORPUS_BEAT_ENABLED`, and `workers/tasks/corpus.py:49,73` can write `documents.file_path` via reconcile. Deploy order now gates on proving the Celery beat is off OR draining `celery_beat` / `celery_worker_maint` before repair
- Added `fmp/tools/transcripts.py` implementation note: keep `core.corpus` helper imports inside the existing lazy import block (or pass raw expanded root and let `ingest_raw` normalize), so the standalone `fmp` package doesn't break

**R4 changes from R3** (Codex R3 FAIL):
- Tightened Celery no-action branch (§7 6b) — env-disabled alone is insufficient; require env-disabled AND processes-inactive before skipping the stop sequence. Celery reads env at process start, and `workers/tasks/corpus.py:49,73` paths don't pass `--lock-file`, so a still-running maint worker could bypass the corpus lock
- `flock -x` (R3 specific note) — added explicit `-x` flag in §7 step 9 for clarity (default behavior, but more readable)
- Added real Celery inspection commands per Codex R3: `python3 -m celery -A workers.celery_app.app inspect active -d maint@$(hostname)` plus `reserved` check
- Split restart commands per Codex R3 — `systemctl start <single>` invocations to make order explicit (workers first, then beat)
- Closed §9 question 6 (F95 cross-ref) — F95 is already in `TODO_COMPLETED.md:104` with `CORPUS_BEAT_ENABLED` gate noted; F159 deploy just cross-links, doesn't re-open

---

## 1. Problem

`scripts/pull_corpus_from_prod.sh` fails preflight in the WAL-safe export step:

```
ERROR: documents.file_path rows outside rewrite prefix
       '/mnt/hank-data/risk_module/filings';
       sample: /mnt/hank-data/risk_module/filings_v1/edgar/GE/10-Q_2026-Q1_153f0d72.md; ...
```

The export tool's path-rewrite invariant requires every `documents.file_path` row to share a single prefix (`/mnt/hank-data/risk_module/filings/`). 125 of 3,390 rows on prod (3.7%) instead point at the versioned target (`/mnt/hank-data/risk_module/filings_v1/...`).

Distribution on prod:

| Source | Form | Count |
|---|---|---|
| edgar | 10-Q | 84 |
| edgar | 10-K | 21 |
| fmp_transcripts | TRANSCRIPT | 20 |
| **Total** | | **125** |

Affected tickers: 25 distinct. `extraction_at` range: 2026-04-30 → 2026-05-22 (intermittent over 22 days). All bad rows came from writes that hit the post-promote (2026-05-05) symlink layout.

**Production read impact: none.** The files exist at the versioned path (`filings → filings_v1` symlink, so the absolute path resolves correctly). Hank reads work fine today.

**Production sync impact: blocking.** Cross-machine sync requires the rewrite-prefix invariant; pull-down and promote round-trips are blocked until the prod data is repaired and the write path is fixed.

**Recurrence: certain.** Every future `promote_corpus.sh` swap (`filings_v2`, `filings_v3`, ...) will start producing bad rows under the new versioned target.

---

## 2. Root cause

`Path.resolve()` (Python `pathlib`) follows symlinks by default. The corpus write path calls `.resolve()` on `corpus_root` before composing `documents.file_path`. On prod, where `/mnt/hank-data/risk_module/filings` is a symlink to `filings_v1`, this rewrites the stored path to the versioned target.

### 2.1 Smoking-gun lines

**`core/corpus/ingest.py`** — single authoritative write path for new corpus markdown:

```python
102:    corpus_root = Path(corpus_root).resolve()        # ← resolves symlink
103:    staging_dir = corpus_root / '.staging'
...
111:    finalized_path = canonical_path(finalized_metadata, corpus_root).resolve()   # ← double-resolve
...
117:    document_row = _build_document_row(finalized_metadata, finalized_path)
...
162:    row['file_path'] = str(canonical_file_path)       # ← stores resolved path
```

**`core/corpus/reingest.py`** — reingest path (called by daily delta + bulk reingest + invalidation + version-floor):

```python
106:    corpus_root = Path(corpus_root).resolve()         # ← resolves symlink
...
188:    result = _recover_row(db, row, Path(corpus_root).resolve())  # ← same
...
340:    finalized_path = canonical_path(finalized_metadata, corpus_root).resolve()   # ← double
...
357:    new_file_path=path.resolve(),                     # ← resolves file path on disk
```

### 2.2 Why only 125 of 3,390 are affected

Pre-promote corpus (~3,265 rows) was built on local Mac with no symlink — local `data/filings/` is a real directory, so `.resolve()` is a no-op. During promote (2026-05-05), `corpus_export_artifact.py --rewrite-prefix` mapped local-Mac paths → `/mnt/hank-data/risk_module/filings/...` (the unversioned symlink prefix). All pre-promote rows are correctly stored.

Post-promote (2026-05-05 onward), prod's daily delta + drain runs invoked `reingest_one` and `ingest_raw` with `corpus_root=/mnt/hank-data/risk_module/filings`. The first `.resolve()` follows the symlink to `filings_v1`, and all subsequent path composition is under the versioned target. The 125 bad rows are exactly the post-promote write count.

### 2.3 Why this wasn't caught earlier

- Reads work transparently — the file exists at the resolved path
- Local dev has no symlink — bug is invisible locally
- No existing test asserts "stored `file_path` matches caller-supplied `corpus_root` prefix"
- First cross-machine sync attempt after a meaningful number of post-promote writes was F158's pull-down round-trip on 2026-05-26

---

## 3. Full audit of `.resolve()` calls

Sweep across `core/corpus/`, `scripts/corpus_*.py`, and `core/corpus/reconciler/`. Excluding `Path(__file__).resolve().parents[N]` (file-self-locate, never bugs).

### 3.1 Storage paths — MUST DROP `.resolve()` and replace with absolute-no-resolve

These compose a path that ends up in `documents.file_path` OR `corpus_reingest_log.{old_file_path, new_file_path}`:

| Location | Code | Reason to drop |
|---|---|---|
| `core/corpus/ingest.py:102` | `corpus_root = Path(corpus_root).resolve()` | Resolves symlink, contaminates all downstream paths written to `documents.file_path` |
| `core/corpus/ingest.py:111` | `canonical_path(...).resolve()` | Same path written to `documents.file_path` via `_build_document_row` → `row['file_path']` |
| `core/corpus/reingest.py:106` | `corpus_root = Path(corpus_root).resolve()` | Same root used to compose `documents.file_path` AND `corpus_reingest_log.new_file_path` |
| `core/corpus/reingest.py:111` | `old_file_path = ... .resolve()` | **Codex R1 finding 3:** stored into `corpus_reingest_log.old_file_path` via `_insert_log` (`reingest.py:521`). Was misclassified in R1 as comparison-only |
| `core/corpus/reingest.py:188` | `_recover_row(..., Path(corpus_root).resolve())` | Passes resolved root through recovery; recovery in turn writes back to `documents.file_path` via `_upsert_and_mark` |
| `core/corpus/reingest.py:226` | `new_file_path = Path(str(row['new_file_path'])).resolve()` | **Codex R1 finding 2:** for `status='new_written'`, this resolved value flows into `_prepare_from_file` (line 261) → `_upsert_and_mark` → `documents.file_path`. Was misclassified in R1 as read-only |
| `core/corpus/reingest.py:340` | `canonical_path(...).resolve()` | Stored into `corpus_reingest_log.new_file_path` |
| `core/corpus/reingest.py:357` | `new_file_path=path.resolve()` | `_prepare_from_file` return propagated into `documents.file_path` |
| `core/corpus/reconciler/walker.py:63` | `file_path=path.resolve()` | **Codex R1 finding 5:** propagates through `AuthoritativeFile.file_path` → `db_sync.py:219` → `documents.file_path` |
| `fmp/tools/transcripts.py:868` | `Path(corpus_root_raw).expanduser().resolve()` | **Codex R1 finding 1, missed entirely in R1:** transcript ingest entry point pre-resolves corpus root before calling `ingest_raw`. Fixing only the phase3 wrapper is not sufficient |
| `scripts/corpus_migration_transform.py:316` | `corpus_root = args.corpus_root.resolve()` | **Codex R1 finding 6:** resolves `--corpus-root` then calls `ingest_raw` at line 266. In scope if script is still supported (decision in §4.3) |

### 3.2 Comparison/canonicalization — KEEP `.resolve()`

These use the resolved form for equality checks or in-process logic, NOT for storage:

| Location | Code | Reason to keep |
|---|---|---|
| `core/corpus/reingest.py:470-471` | `old_file_path = old_file_path.resolve(); if old_file_path == new_file_path.resolve()` | Pure path-equality check ("are these the same file?") — resolve is correct here |
| `core/corpus/reingest.py:667` | `_optional_path` helper returning `Path(str(value)).resolve()` | Codex R1 confirmed: `_optional_path` itself does not write back to DB; used as a Path constructor for in-process comparisons. Keep |
| `core/corpus/validation.py:163-164` | `p = Path(file_path).resolve(); root = Path(corpus_root).resolve()` | Read-time validation: `p.is_relative_to(root)`. Resolve safe for read; not stored |
| `scripts/corpus_export_artifact.py:52, 92` | Internal `src/dst` comparison + URI generation | Not stored in DB; comparing on-disk paths |

### 3.3 Default-path canonicalization — KEEP `.resolve()` BUT REVIEW

These resolve the CORPUS_ROOT env default. If the env var is set to a symlink, this resolves it before any caller sees it — same root-cause issue, just one hop earlier:

| Location | Code |
|---|---|
| `core/corpus/transcripts.py:398, 403` | `_corpus_root()` / `_corpus_db_path()` |
| `core/corpus/filings.py:536, 541` | Same pattern |

**Decision:** drop `.resolve()` from these defaults too. Symlink-form is the canonical storage form; we should preserve it consistently from env → core → DB.

### 3.4 Recovery row-parsing — INVESTIGATE

`reingest.py:667` `_optional_path()` resolves on read. Called from:

- `reingest.py:225` (`old_file_path = _optional_path(row['old_file_path'])`) — passed to `_run_planned_work` then to `_insert_log`. If `_insert_log` writes `old_file_path` back into a log row, the resolved form is stored.

Action: trace `_insert_log` and `_run_planned_work` to confirm whether resolved `old_file_path` is stored anywhere. If yes, drop the resolve. If no (purely in-process comparison), keep.

### 3.5 Script-level pre-resolution — INVESTIGATE

Several scripts resolve `args.corpus_root` before passing to core:

| Location | Code | Risk |
|---|---|---|
| `scripts/corpus_phase3_bulk_ingest_transcripts.py:67` | `os.environ['CORPUS_ROOT'] = str(corpus_root.expanduser().resolve())` | Sets resolved path into env; downstream core reads via `_corpus_root()` |
| `scripts/corpus_ingest_accession.py:225` | `corpus_root = args.corpus_root.resolve()` | Passes resolved root to `ingest_raw` |
| `scripts/corpus_canary_synthetic_lowconf.py:99` | `corpus_root = args.corpus_root.resolve()` | Same |
| `scripts/corpus_phase1_delta_ingest.py` | No explicit `.resolve()` on `args.corpus_root` (good — but core resolves it anyway) | Bug fix in core captures this |

**Decision:** drop `.expanduser().resolve()` from script wrappers' `corpus_root` propagation; keep `.expanduser()` only (handles `~` but doesn't follow symlinks).

---

## 4. Proposed fix

### 4.1 Invariant

**`documents.file_path` and `corpus_reingest_log.{old_file_path, new_file_path}` always store ABSOLUTE paths in caller-supplied (unresolved) form.** If the caller passes the symlink, the stored path uses the symlink. If the caller passes a relative path, it gets absolutized **without following symlinks**.

This is achieved with `os.path.abspath()` (or equivalently `Path(p).absolute()` in pathlib), NOT `.resolve()`:

| Helper | Makes absolute? | Follows symlinks? |
|---|---|---|
| `Path(p)` | No | No |
| `Path(p).absolute()` / `os.path.abspath(p)` | Yes | **No** ← what we want |
| `Path(p).resolve()` / `os.path.realpath(p)` | Yes | Yes ← the bug |

### 4.2 Helper (new)

Add to `core/corpus/_paths.py` (new module) or inline in `core/corpus/ingest.py` if minimal:

```python
import os
from pathlib import Path

def normalize_corpus_path(path: str | Path) -> Path:
    """Return an absolute Path with `~` expanded but symlinks NOT followed.

    Used for all paths that get stored in documents.file_path or
    corpus_reingest_log.{old_file_path, new_file_path} columns. Preserves
    the unversioned `filings/` symlink form so cross-machine sync
    (corpus_export_artifact.py) rewrite-prefix invariant holds.
    """
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))
```

`os.path.abspath` is preferred over `Path(...).absolute()` because `absolute()` does NOT call `expanduser` and explicitly documents that it's "not the same as `resolve()`" — the abspath form normalizes `.` / `..` traversals deterministically without OS lstat side effects.

### 4.3 Changes — core/corpus/

**`core/corpus/ingest.py`:**
- L102: `corpus_root = Path(corpus_root).resolve()` → `corpus_root = normalize_corpus_path(corpus_root)`
- L111: `canonical_path(finalized_metadata, corpus_root).resolve()` → `canonical_path(finalized_metadata, corpus_root)` (already absolute via §4.1)

**`core/corpus/reingest.py`:**
- L106: `corpus_root = Path(corpus_root).resolve()` → `corpus_root = normalize_corpus_path(corpus_root)`
- L111: `old_file_path = Path(str(old_row['file_path'])).resolve() if old_row['file_path'] else None` → `old_file_path = normalize_corpus_path(old_row['file_path']) if old_row['file_path'] else None`
- L188: `_recover_row(db, row, Path(corpus_root).resolve())` → `_recover_row(db, row, normalize_corpus_path(corpus_root))`
- L226: `new_file_path = Path(str(row['new_file_path'])).resolve()` → `new_file_path = normalize_corpus_path(row['new_file_path'])`
- L340: `canonical_path(finalized_metadata, corpus_root).resolve()` → `canonical_path(finalized_metadata, corpus_root)`
- L357: `new_file_path=path.resolve()` → `new_file_path=normalize_corpus_path(path)` (in `_prepare_from_file`)

**`core/corpus/reconciler/walker.py`:**
- L63: `file_path=path.resolve()` → `file_path=normalize_corpus_path(path)`. `walker.py:47` shows `path` is built from `corpus_root` join, so absolutization-from-relative is the right behavior; symlink resolution must NOT happen here.

**`core/corpus/transcripts.py`:**
- L398: `Path(raw).expanduser().resolve() if raw else _DEFAULT_CORPUS_ROOT.resolve()` → `normalize_corpus_path(raw) if raw else _DEFAULT_CORPUS_ROOT`
- L403: same pattern. Codex R1 noted: `_corpus_db_path()` is not storage-relevant; if revert helpful for clarity, can keep resolve for the DB path only — but uniform helper reduces footguns.

**`core/corpus/filings.py`:**
- L536, L541: same pattern as transcripts

### 4.4 Changes — scripts/

**`fmp/tools/transcripts.py` (R2 add, R3 implementation note):**
- L868: `Path(corpus_root_raw).expanduser().resolve()` → `Path(corpus_root_raw).expanduser()` (drop `.resolve()`; `ingest_raw` will normalize via §4.3, and we avoid importing `core.corpus` from `fmp/`)
- **Per Codex R2 note**: keep this file's `core.corpus.ingest` import inside the existing lazy import block (line 860). Do NOT add a `core.corpus._paths` import to `fmp/tools/transcripts.py`, since `fmp/` is a standalone package and that import would break its packaging. Letting `ingest_raw` normalize is the right boundary

**`scripts/corpus_phase3_bulk_ingest_transcripts.py`:**
- L67: `os.environ['CORPUS_ROOT'] = str(corpus_root.expanduser().resolve())` → `os.environ['CORPUS_ROOT'] = str(normalize_corpus_path(corpus_root))`
- L68: same for `CORPUS_DB_PATH` (keep resolve here is also fine — DB path isn't stored, but uniformity preferred)

**`scripts/corpus_ingest_accession.py`:**
- L225: `corpus_root = args.corpus_root.resolve()` → `corpus_root = normalize_corpus_path(args.corpus_root)`

**`scripts/corpus_canary_synthetic_lowconf.py`:**
- L99: same pattern

**`scripts/corpus_migration_transform.py` (R2 add):**
- L316: `corpus_root = args.corpus_root.resolve()` → `corpus_root = normalize_corpus_path(args.corpus_root)`
- **Scope decision**: include in this fix because the script remains supported (one-shot migration historically used; still callable). Out of scope: the `Path(record.source_path).resolve()` and similar inventory-parsing resolves in this script — those resolve LOCAL inventory paths during a build-time transform, not paths that become `documents.file_path`. Leave alone.

### 4.5 What NOT to change

- `core/corpus/validation.py:163-164` — read-time path validation, `is_relative_to` check
- `core/corpus/reingest.py:470-471` — pure path-equality comparison
- `core/corpus/reingest.py:667` (`_optional_path`) — Codex R1 confirmed no DB write-back
- `scripts/corpus_export_artifact.py` — read-time comparison only
- `Path(__file__).resolve().parents[N]` patterns — file-self-locate
- `scripts/corpus_migration_inventory.py` and `scripts/corpus_migration_transform.py` build-time inventory resolves (NOT the `args.corpus_root.resolve()` at line 316, which IS in scope)

---

## 5. Tests

### 5.1 Regression — `documents.file_path` AND log columns preserve caller-supplied root

Add `tests/core/corpus/test_ingest_path_invariant.py` covering:

- `ingest_raw` with symlinked `corpus_root` → stored path uses symlink prefix
- `ingest_raw` with relative `corpus_root` → stored path is absolutized but NOT symlink-resolved
- `reingest_one` (content-changed branch) → both `documents.file_path` AND `corpus_reingest_log.{old_file_path, new_file_path}` use symlink prefix
- `reingest_one` (no-change branch) → log row's `old_file_path` / `new_file_path` use symlink prefix
- `recover_pending` from `new_written` log row (Codex R1 non-blocking) → resulting `documents.file_path` uses symlink prefix
- Transcript ingest via `fmp.tools.transcripts._persist_transcript` (or equivalent) with `CORPUS_ROOT` env set to symlink → stored path uses symlink prefix
- Reconciler walker with symlinked corpus root → `documents.file_path` updates preserve symlink prefix

Skeleton:

```python
def test_ingest_raw_stores_unresolved_corpus_root(tmp_path):
    real_root = tmp_path / 'filings_v1'
    real_root.mkdir()
    symlink_root = tmp_path / 'filings'
    symlink_root.symlink_to(real_root)

    result = ingest_raw(body=..., metadata=..., corpus_root=symlink_root, db=db)

    row = db.execute('SELECT file_path FROM documents WHERE document_id = ?', ...).fetchone()
    assert str(symlink_root) in row['file_path']
    assert 'filings_v1' not in row['file_path']

    # File still exists at the resolved path via symlink — read path works
    assert Path(row['file_path']).exists()


def test_reingest_one_logs_symlink_form(tmp_path):
    # ... setup symlinked root ...
    # ... seed an existing documents row with symlink-form file_path ...
    reingest_one(..., corpus_root=symlink_root, ...)

    log_row = db.execute(
        'SELECT old_file_path, new_file_path FROM corpus_reingest_log ORDER BY id DESC LIMIT 1'
    ).fetchone()
    assert 'filings_v1' not in (log_row['old_file_path'] or '')
    assert 'filings_v1' not in log_row['new_file_path']
```

### 5.2 Defense-in-depth — preflight check (per Codex R1 non-blocking)

NOT a runtime fail-hard startup assert (would block service if anything corrupted). Instead:

- **Test-time:** add a CI test that walks `documents` + `corpus_reingest_log` after each test that writes rows; asserts all `file_path`-class columns share a single prefix
- **Operational preflight:** add a prefix-uniformity check to `pull_corpus_from_prod.sh` (and `promote_corpus.sh`) that runs BEFORE invoking `corpus_export_artifact.py`. Fail fast with a clear error pointing at affected rows. Avoids the cryptic "rows outside rewrite prefix" surprise we hit on 2026-05-26

### 5.3 Snapshot test for `corpus_export_artifact.py`

Build a small fixture corpus with intentional symlink, run the script's path-rewrite check; assert it accepts the symlink-form corpus.

---

## 6. Prod data repair

Once the code fix is shipped + deployed AND ingest timers paused, run a one-shot SQL repair on prod. Uses **prefix-boundary check** (same form as `corpus_export_artifact.py:118`) instead of broad `LIKE '%/filings_v1/%'`, AND repairs the side log table.

Variables for clarity (the SQL substitutes plain strings; shown as variables for the operator):
- `BAD_PREFIX = '/mnt/hank-data/risk_module/filings_v1/'`
- `GOOD_PREFIX = '/mnt/hank-data/risk_module/filings/'`

```sql
BEGIN IMMEDIATE;

-- 1. Snapshot pre-repair counts (defense — confirm scope matches triage)
SELECT 'documents' AS tbl,
       SUM(CASE WHEN SUBSTR(file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/' THEN 1 ELSE 0 END) AS bad,
       SUM(CASE WHEN SUBSTR(file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings/')) = '/mnt/hank-data/risk_module/filings/' THEN 1 ELSE 0 END) AS good,
       COUNT(*) AS total
  FROM documents
UNION ALL
SELECT 'corpus_reingest_log.old_file_path',
       SUM(CASE WHEN SUBSTR(old_file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/' THEN 1 ELSE 0 END),
       SUM(CASE WHEN SUBSTR(old_file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings/')) = '/mnt/hank-data/risk_module/filings/' THEN 1 ELSE 0 END),
       COUNT(*) FILTER (WHERE old_file_path IS NOT NULL)
  FROM corpus_reingest_log
UNION ALL
SELECT 'corpus_reingest_log.new_file_path',
       SUM(CASE WHEN SUBSTR(new_file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/' THEN 1 ELSE 0 END),
       SUM(CASE WHEN SUBSTR(new_file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings/')) = '/mnt/hank-data/risk_module/filings/' THEN 1 ELSE 0 END),
       COUNT(*) FILTER (WHERE new_file_path IS NOT NULL)
  FROM corpus_reingest_log;

-- 2. Repair documents.file_path (prefix-boundary, NOT global REPLACE)
UPDATE documents
   SET file_path = '/mnt/hank-data/risk_module/filings/' ||
                   SUBSTR(file_path, LENGTH('/mnt/hank-data/risk_module/filings_v1/') + 1)
 WHERE SUBSTR(file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/';

-- 3. Repair corpus_reingest_log.old_file_path (Codex R1 finding 3 — side table)
UPDATE corpus_reingest_log
   SET old_file_path = '/mnt/hank-data/risk_module/filings/' ||
                       SUBSTR(old_file_path, LENGTH('/mnt/hank-data/risk_module/filings_v1/') + 1)
 WHERE old_file_path IS NOT NULL
   AND SUBSTR(old_file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/';

-- 4. Repair corpus_reingest_log.new_file_path
UPDATE corpus_reingest_log
   SET new_file_path = '/mnt/hank-data/risk_module/filings/' ||
                       SUBSTR(new_file_path, LENGTH('/mnt/hank-data/risk_module/filings_v1/') + 1)
 WHERE new_file_path IS NOT NULL
   AND SUBSTR(new_file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/';

-- 5. Verify zero rows remain on versioned prefix across all three columns
SELECT 'documents' AS tbl, COUNT(*) AS still_bad FROM documents
 WHERE SUBSTR(file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/'
UNION ALL
SELECT 'corpus_reingest_log.old_file_path', COUNT(*) FROM corpus_reingest_log
 WHERE SUBSTR(old_file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/'
UNION ALL
SELECT 'corpus_reingest_log.new_file_path', COUNT(*) FROM corpus_reingest_log
 WHERE SUBSTR(new_file_path, 1, LENGTH('/mnt/hank-data/risk_module/filings_v1/')) = '/mnt/hank-data/risk_module/filings_v1/';
-- Expected: all three rows show still_bad = 0

-- 6. Spot-check: one repaired documents row + os-level stat verification (manual)
SELECT file_path FROM documents WHERE ticker='GE' AND source='edgar' AND form_type='10-Q' LIMIT 1;
-- Manually outside SQL: stat <returned-path> — should succeed via symlink

COMMIT;
```

**Safety:**
- `BEGIN IMMEDIATE` acquires the SQLite reserved lock immediately, avoiding write-skew if any read transaction is concurrently open
- Prefix-boundary match (not `LIKE '%pattern%'`) — won't accidentally rewrite a row containing the substring elsewhere
- Idempotent: post-repair, the `SUBSTR(...) = bad_prefix` check is false for the rewritten rows, so re-running is a no-op
- Files at `filings/...` and `filings_v1/...` are the same inode via symlink; reads continue to work transparently during the transaction
- No FTS index references `file_path` (sections_fts keyed on `document_id`)
- **Pre-repair operational gates** (in §7): timers stopped, `flock` held on the corpus lock, EBS snapshot taken

---

## 7. Deploy order

Reordered per Codex R1 finding 8 — pause timers BEFORE code deploy (not after), add snapshot, hold flock during repair, handle in-flight non-terminal log rows before deploy.

1. **Codex review** of this plan → iterate to PASS
2. **Implement via Codex MCP** — code changes from §4.3-4.4 + helper from §4.2 + tests from §5
3. **Local verification:**
   - All corpus tests pass (existing + new from §5)
   - Run a local ingest with a symlinked corpus_root; verify stored path preserves symlink (regression test from §5.1)
4. **Push to GitHub** (no deploy yet)
5. **Pre-deploy snapshot on prod:**
   - SSH to edgar-updater
   - Trigger explicit EBS snapshot of the `hank-data` volume (manual, beyond DLM cadence) so we have a known-good rollback point covering both the DB and `filings_v1/` contents
6. **Pause ALL corpus writers FIRST (before code deploy):**

   **6a. Systemd timers:**
   - `systemctl stop corpus_delta_ingest.timer corpus_transcripts_delta.timer`
   - Wait for any in-flight ingest unit to exit (`systemctl status corpus_delta_ingest.service corpus_transcripts_delta.service` — confirm `inactive`)

   **6b. Celery beat / workers (Codex R2 finding 2, R3 tightening):**

   Per Codex R3: env-disabled alone is insufficient. Celery reads env at process start, and `workers/tasks/corpus.py:49,73` paths don't pass `--lock-file`, so even a stale maint worker process could bypass the corpus lock. Require BOTH conditions before skipping the stop sequence.

   - **Inspect env:** prod `.env` / SSM for `CELERY_ENABLED` and `CORPUS_BEAT_ENABLED`
   - **Inspect processes:** `systemctl status celery_beat celery_worker_maint` (or whatever prod unit names are) AND `python3 -m celery -A workers.celery_app.app inspect active -d maint@$(hostname)` AND `python3 -m celery -A workers.celery_app.app inspect reserved -d maint@$(hostname)`
   - **No-action branch (skip 6b stop)**: ALL of the following must hold (Codex R4 caution: "worker unreachable" is NOT proof on its own — pair with independent process evidence):
     - `CELERY_ENABLED=false` (in env)
     - `celery_beat`/`celery_worker_maint` systemd units inactive (`systemctl status`)
     - `pgrep -af 'celery.*(worker|beat)'` returns empty
     - `inspect active`+`inspect reserved` return empty (treat unreachable as suggestive but not sufficient — only valid when paired with the systemd + pgrep checks above)
     - Record the verification snapshot. Per F95 (already closed in `TODO_COMPLETED.md:104`), this is the expected current prod state
   - **Stop-and-drain branch (any condition above fails)**: STOP the beat AND drain the maint worker before repair:
     1. `systemctl stop celery_beat` (stop scheduling new corpus jobs first)
     2. Wait for active maint worker jobs to drain — poll `inspect active`+`reserved` until both return empty
     3. `systemctl stop celery_worker_maint`
     4. Re-verify both `active` and `reserved` are empty before proceeding to step 7
   - Either way: capture the verification output (env values, systemd status, celery inspect output) in the deploy log before proceeding

   Reason: deploying mid-ingest (systemd OR Celery) could leave non-terminal `corpus_reingest_log` rows that the new code's `recover_pending` then processes with mixed-form paths. Pausing first ensures the log is at a stable state before code change
7. **Handle non-terminal log rows (Codex R1 non-blocking + open question):**
   - On prod: `SELECT id, status, old_file_path, new_file_path FROM corpus_reingest_log WHERE status NOT IN ('complete','no_change','abandoned')` — capture
   - If empty → proceed
   - If non-empty → decide row-by-row: either let the OLD code finish them (re-enable timer briefly, then re-stop) OR explicitly `abandon` them via `_mark_failed` so post-deploy recover doesn't touch mixed-form paths
8. **Deploy code to prod:**
   - SSH to edgar-updater
   - `git pull` in `/var/www/risk_module`
   - `systemctl restart risk_module` (and other corpus consumers per §9 question 5)
9. **Acquire flock + run prod data repair (§6 SQL):**
   - `flock -x /run/corpus_promote.lock python3 -c "exec_repair_sql()"` — hold the same exclusive lock `promote_corpus.sh` uses (Codex R3: `-x` is default but explicit is clearer)
   - Run repair inside `BEGIN IMMEDIATE` transaction
   - Verify post-repair counts (all three columns: documents + log.old + log.new)
   - Release flock
10. **Resume corpus writers:**
    - `systemctl start corpus_delta_ingest.timer corpus_transcripts_delta.timer`
    - If 6b stopped Celery (Codex R3: split into separate commands so order is explicit, not argv-positional):
      1. `systemctl start celery_worker_maint`
      2. Verify worker is up — `python3 -m celery -A workers.celery_app.app inspect ping -d maint@$(hostname)`
      3. `systemctl start celery_beat` (only after worker is verified live, so beat-scheduled jobs land on a ready queue)
11. **Verify next daily run preserves symlink form:**
    - Wait for next 06 UTC tick OR trigger manually with a known accession (e.g., `systemctl start corpus_delta_ingest.service` once)
    - Query the new row's `documents.file_path` — must use `/mnt/hank-data/risk_module/filings/`, NOT `/filings_v1/`
12. **Unblock F160 round-trip:**
    - `bash scripts/pull_corpus_from_prod.sh --dry-run` from local — should pass preflight (no rewrite-prefix error)
    - `bash scripts/pull_corpus_from_prod.sh --execute` — execute the pull
    - Re-run bulk reingest locally against the now-merged corpus
    - `scripts/promote_corpus.sh` back up

---

## 8. Verification gates

After each deploy step, the following must hold:

- **Code:** `git grep -n "corpus_root.*\.resolve()" core/ scripts/corpus_*.py` returns no STORAGE-context matches (only comparison-context matches from §3.2)
- **Tests:** all corpus tests pass, including new regression in §5.1
- **Prod data:** `SELECT COUNT(*) FROM documents WHERE file_path LIKE '%/filings_v1/%'` returns 0
- **Next ingest:** new daily-delta row has `file_path LIKE '/mnt/hank-data/risk_module/filings/%'` (not `filings_v1`)
- **Pull-down:** `pull_corpus_from_prod.sh --dry-run` no longer surfaces the rewrite-prefix error

---

## 9. Open questions for Codex review (R3)

R1 questions resolved: ~~Q1 _optional_path~~, ~~Q2 walker~~, ~~Q4 flock (R3 corrected path)~~
R2 questions resolved by R2/R3 itself or Codex R2: ~~Q4 abspath vs absolute (R2 §4.2 documented choice; Codex R2 confirmed sound)~~, ~~Q6 fmp resolve intent (R3 keeps lazy-import boundary)~~

**Remaining R3 questions:**

1. **Defense-in-depth check (§5.2)** — R2 settled on test-time + preflight, NOT runtime startup fail-hard. Final confirm: is the preflight check best placed inside `pull_corpus_from_prod.sh` and `promote_corpus.sh` (one assertion before invoking the export tool), or should it live inside `corpus_export_artifact.py` itself with a clearer error message? The current export-tool error ("documents.file_path rows outside rewrite prefix") IS already an effective preflight failure — should we just improve the error message rather than add a new check?

2. **Service restart set (§7 step 8)** — `systemctl restart risk_module` covers the main service. Are there other consumers (workers, gateways, MCP servers, edgar_api itself) that hold open `filings.db` handles and would survive a code deploy without picking up the new code? Specifically: does `edgar_api` ever import `core.corpus` write paths, or is it strictly read-side?

3. **Non-terminal log rows pre-deploy (§7 step 7)** — what's the expected count on prod day-of-deploy? If non-zero and we choose "let OLD code finish them" path, the timer restart-then-stop window risks fresh log rows. Acceptable, or should we hard-abandon all non-terminal rows via SQL update before deploy?

4. **`corpus_migration_transform.py` scope (§4.4)** — included for safety. Is this script known-quiescent (no longer invoked from any pipeline), in which case it could be marked DEPRECATED and skipped without risk?

5. **`recover_pending` from `new_written` test fixturing (§5.1)** — confirm whether that path can be exercised in unit tests with reasonable fixtures, or if it requires a full integration test against a sqlite tmp DB seeded with a `new_written` log row.

6. ~~F95 cross-ref~~ — closed in R4: Codex R3 confirmed F95 is already in `TODO_COMPLETED.md:104` with `CORPUS_BEAT_ENABLED` gate noted. F159 deploy cross-links F95 in §7 step 6b — no new open question.

---

## 10. Out of scope

- Schema-level enforcement (e.g., a CHECK constraint on `file_path` prefix) — defer to a future hardening pass
- The 30-day retention pruning logic for `filings_v(N-1)` — unchanged
- F158 empty-sections bucket — separate parser-side issue, tracked in Edgar_updater
- Renaming or restructuring `documents.file_path` — keep current absolute-path schema
