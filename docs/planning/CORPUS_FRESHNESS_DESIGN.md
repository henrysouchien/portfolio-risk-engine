# Corpus Cache Freshness Design

## Status: DRAFT v5.1 — addresses Codex R5 (0 P1 + 2 P2 doc-comment fixes); pending Codex R6 PASS confirmation

**Created:** 2026-05-04
**Updated:** 2026-05-04 — v5 in R4; v4 in R3; v3 in R2; v2 in R1. Convergence: R1 8 P1 → R2 4 → R3 4 → R4 1.
**Author:** Henry (with Claude)

### v5 Revision Summary

R4 returned FAIL-WITH-CHANGES with 1 P1 + 4 P2. R4 explicitly confirmed the UPSERT-+-status-flip bundle, `old_deleted`/`complete` two-transaction split, and sweeper logic — only refinements needed. Material changes:

1. **`planned` recovery completeness fix (§4.2).** v4 left a hole: process death between new-file-write and `new_written` commit could leave an orphan file unrecoverable. v5: `new_file_path` + `new_content_hash` are computed and stored at the `planned` INSERT (both derivable from the API response before any write). Recovery for `planned` now: check `Path(new_file_path).exists()`; if yes + hash matches, advance to `new_written` (file already there); if yes + hash mismatch, alert (foreign file collision); if no, write file fresh. Uniquely recoverable.
2. **`abandoned` transition ownership clarified (§4.2 recovery).** Recovery script writes the transition in the SAME small transaction that inserts the replacement `planned` row. Normal ingest call doesn't touch stale siblings — it's not its job to know about them.
3. **Post-filter implementation constraint added (§4.4).** Single query into a `set` of active `old_file_path`s, then linear pass over divergences. Forbid per-divergence SQL.
4. **Tokenizer LoC estimate corrected (§7 Q4).** R4 said ~130 LoC is realistic only for minimal errors; production code with dataclasses + good errors is ~180–220 LoC. Approach unchanged.
5. **`producer_deployment_id` absence: NULL not `'unknown'` (§7 Q8).** v4 mixed sentinel + valid label. v5: NULL when missing; warning logged via existing logger; if queries need to distinguish, add a lightweight `producer_deployment_missing INTEGER DEFAULT 0` flag column instead of polluting the label space.

### v4 Revision Summary

R3 returned FAIL-WITH-CHANGES with 4 P1 + 7 P2. Material changes:

1. **Status semantics inverted to "last completed phase" (§4.2).** v3 said "write log status BEFORE doing the work." That's wrong — process death between status write and work = recovery falsely thinks work is done. v4: status = last successfully completed phase, written AFTER the work commits. Initial insert is `planned`. Recovery reads status as "phase X succeeded; phase X+1 may or may not have started."
2. **`old_deleted` → `complete` transition added (§4.2 + §4.4).** v3 left `old_deleted` as a non-terminal active state with no recovery rule, creating orphan-row deadlock. v4 has sweeper verify old file is gone and advance status to `complete`.
3. **`abandoned` state added to CHECK constraint (§4.2).** v3 recovery mentioned marking `planned` rows abandoned but the CHECK didn't list it. v4 adds it as terminal.
4. **Per-phase small transactions specified (§4.2).** v3 was ambiguous. v4 explicit: each status update is its own `with db:` block; phases never wrapped in a single mega-transaction.
5. **Walker `expected_during_reingest` moved out of walker (§4.4).** Walker is disk-only; making it DB-aware is a layering violation. v4 does the tagging in `workers/tasks/corpus.py reconciler_daily` after the walker reports raw divergences. Handles missing `corpus_reingest_log` (fresh corpus pre-migration) as empty.
6. **Predicate parser: from-scratch tokenizer (§7 Q4).** v3 suggested `sqlparse` with allow-lists. v4 prefers ~50-line from-scratch tokenizer + parser — narrower surface, no dep, easier to audit.
7. **`producer_deployment_id` consistency fix (§4.1, §7 Q8).** v3 said "required env label" but DB/frontmatter treatment was nullable — internally inconsistent. v4: nullable on consumer (warn + record `unknown` if absent), required on producer side (enforced via Edgar_updater CI/contract test).
8. **`_UPSERT_MUTABLE_COLUMNS` covers ALL new provenance fields (§4.2).** Not just `parser_*`. Includes `producer_deployment_id`, `producer_instance_id`, `producer_build_id`, `cross_reference_target`, `parser_state`, `parser_result_status`.

### v3 Revision Summary

R2 returned FAIL-WITH-CHANGES with 4 P1 + 6 P2. Material changes:

1. **Re-ingest mechanism is a state machine, NOT an atomic transaction.** v2 falsely claimed "delete old file atomically as part of the same transaction." SQLite + filesystem ops cannot be atomic. v3 rewrites §4.2 as an explicit state machine: log entry written FIRST with `status='planned'`, then advances through `new_written` / `db_upserted` / `old_deleted` / `complete`. Recovery script reads pending/failed entries on startup.
2. **Sweeper rewritten with DB-state guards (§4.4).** v2 sweeper used `Path.exists()` only — couldn't distinguish old-file survivors from new unlogged duplicates, and could race-delete authoritative files of subsequent re-ingests. v3 sweeper queries `documents` table state + checks for active log entries before deleting.
3. **Predicate language safety strengthened (§7 Q4).** v2 said "trivial." v3 specifies real tokenizer + EOF consumption + illegal-token rejection (`;`, `--`) + parameterized SQL only.
4. **Schema parity test corrected (§4.1).** v2 asserted "all 4 sets equal" — wrong. DB has `file_path`, `is_superseded_by`, `last_indexed` that frontmatter lacks. v3 uses Codex's exact assertion shape.
5. **`producer_deployment_id` split into three fields (§4.1).** v2 had a single field. v3: `producer_deployment_id` (required env label like `edgar-prod`), optional `producer_instance_id` (hostname/pod), optional `producer_build_id` (image digest).
6. **`NULLABLE_INT_FIELDS` validator: bool subclass note (§4.1).** Python `bool` is `int` subclass; reject explicitly if schema means true integer.
7. **Lock-file default specified (§4.2 prereqs).** `_DEFAULT_LOCK_PATH = Path(os.environ.get('CORPUS_LOCK_FILE', '/run/corpus_promote.lock'))` matches systemd.

### v2 Revision Summary

R1 surfaced 8 P1 blockers + 5 P2 nice-to-fix. Material changes:

1. **Schema citation corrected** — `documents` has 28 columns, not 25 (§2.2).
2. **Lockstep-edit count corrected** — adding fields touches 5 files, not 3: `schema.sql`, `frontmatter.py`, `core/corpus/ingest.py:29-55` (`_DOCUMENT_COLUMNS`), `core/corpus/reconciler/db_sync.py:15-43` (separate `_DOCUMENT_COLUMNS`), and a new `NULLABLE_INT_FIELDS` for `parser_schema_version` (§3, §4.1).
3. **Re-ingest model rewritten** — old "supersedes linkage" was fiction. `canonical_path` includes `content_hash` in the filename (`frontmatter.py:252`), so re-ingest **always** writes a new file at a new path. Old file would otherwise live forever as walker `other_files`. v2 chooses overwrite-with-cleanup: re-ingest deletes old file, UPSERTs the document_id, audit log captures (old_hash, old_path, new_hash, new_path). `supersedes` columns stay reserved for amendments (their original purpose) (§4.2, §4.3).
4. **Soak decoupling moved to divergence source** — reconciler drift is `rows_marked_orphan + divergences`, not content_hash drift (`workers/tasks/corpus.py:62`). Old "filter at soak check" approach fixed nothing because the divergence had already been logged. v2 eliminates the divergence by deleting old files atomically with re-ingest (§4.4).
5. **Lock-file gap closed** — Celery task `delta_ingest_daily` calls `main([])` with no `--lock-file` arg (`workers/tasks/corpus.py:33`), bypassing the lock entirely. Systemd uses it; Celery doesn't. Re-ingest runner adds a third concurrent path. v2 mandates wiring `--lock-file` through Celery as a precondition (§4.2 prerequisites, §6 risks).
6. **P1 phasing prerequisite added** — "consumer captures producer fields" assumed those fields are already populated at TOP LEVEL of `SectionsResponse`. Repo tests fixture only section-level `state` / `cross_reference_target`. v2 adds an explicit P1 prerequisite: probe a real Edgar_updater `/api/sections` response and confirm top-level field population. If not present, P1 depends on P2 (§5).
7. **Invalidation failure policy added** — fail-CLOSED on malformed YAML (§4.2). Producer endpoint returns 503; consumer logs and skips invalidation step but continues normal delta ingest. Stale corpus persists; no NEW staleness is hidden.
8. **Consumer DOS guards added** — accessions-per-entry cap, accessions-per-run cap, predicate evaluation timeout, log size cap (§4.2).

P2 folds: phasing flexibility documented, FMP transcript staleness flagged for future work, cross-deployment producer identity added to provenance, walker validation noted, migration-scaffold question elevated to §7.


**Companion to:** `docs/deployment/CORPUS_DEPLOYMENT_DESIGN.md` (F54 prod-refresh strategy), `docs/planning/CORPUS_WEAK_DOC_GATE_PLAN.md` (F50 10-Q parser-bug gate).
**Cross-repo dependency:** `Edgar_updater/docs/plans/PLAN-parser-health-phase3-sections.md` (parser-health observability — Phase 1+2 shipped 2026-04-29, Phase 3 in DRAFT v4).

**TODO rows covered:** F52 (Edgar_updater ↔ corpus invalidation contract), F65 (cache versioning — parser provenance on `documents`), F66 (corpus cache freshness design).

---

## 1. Problem

The corpus cache (`data/filings.db` + `data/filings/*.md`) goes stale silently when Edgar_updater fixes a parser bug that affects already-ingested filings.

**Concrete trigger:** F50 filed three upstream section-parser bugs (Citi-class absorption + GE-class dropout + STT untagged) at Edgar_updater commit `7ed2f86`. F64 added a sibling concern: an in-flight Item 7 (10-K MD&A) cross-reference rescue fix may affect a much wider 10-K set, but F50's 10-Q-only weak-doc gate doesn't cover it. Each fix today requires manual archeology to scope blast radius — there's no machine-readable answer to "which of our 1,665 cached filings were produced by the broken parser?"

**Root cause:** the corpus has no parser-version provenance and no upstream-driven invalidation channel. Delta ingest (`scripts/corpus_phase1_delta_ingest.py:88-120`) only fetches NEW accessions; existing accessions are frozen until a human runs a re-fetch script.

## 2. Verified Current State

### 2.1 Edgar_updater (producer)

`SectionsResponse` (`Edgar_updater/edgar_api/schemas.py:143-162`) **already exposes** per-section parser provenance in the response body:

```python
class SectionsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["success"]
    result_status: Literal["ok", "all_missing", "partial"] | None = None
    sections: Any | None = None
    state: str | None = None                                 # Phase 4 four-state: body|cross_reference|absent|missing
    sections_by_state: dict[str, list[str]] | None = None
    cross_reference_target: str | None = None                # captures Item 7 cross-reference pattern
    declaration_type: str | None = None
    parser_path: str | None = None                           # main vs. rescue path discriminator
    toc_detection_method: str | None = None
    toc_confidence: float | None = None
    toc_table_count: int | None = None
```

Parser-health Phase 1+2 shipped 2026-04-29 (`Edgar_updater/edgar_api/health.py`). Tables: `health_runs` + `health_run_modes` + `filing_health`. The `filing_health` schema already includes `parser_path` (`health.py:130,205`). Phase 3 (sections-mode wiring) is in DRAFT v4 (`PLAN-parser-health-phase3-sections.md`).

Package version is `__version__ = "0.1.0"` (`edgar_api/__init__.py:3`). No `pyproject.toml`. No git-SHA stamping into responses today.

In-flight Item 7 fix is **not yet committed** — latest is `980143a docs(todo): re-diagnose JPM 10-K Item 7 miss as cross-reference filing pattern`. Working tree has `BUGS.md` + multiple plan docs modified. Diagnosis still in progress.

### 2.2 risk_module corpus (consumer)

**API client drops parser provenance.** `core/corpus/edgar_api_client.py:60-71` uses `_request_json()` which returns `resp.json()` — body parsed, but the new fields above (`parser_path`, `cross_reference_target`, `state`, `result_status`) are **never read** by callers. They're silently discarded.

**Schema has no parser provenance.** `core/corpus/schema.sql:1-36` — `documents` table has **28 columns** (verified via `sqlite3 ... .schema documents`) including `extraction_pipeline`, `extraction_model`, `extraction_at`, `extraction_status`, `content_hash`, `last_indexed`, plus `supersedes` / `supersedes_source` / `supersedes_confidence` / `is_superseded_by` (amendment linkage). None of these are parser-version. (`extraction_*` is intended for LLM extraction provenance, not section-parser provenance.)

**No corpus migration mechanism.** No `corpus_schema_version` table. `CREATE TABLE IF NOT EXISTS` everywhere — schema is implicitly first-run-wins. The repo HAS migration scaffolds elsewhere (`app_platform/db/migration.py` for Postgres, `database/migrations/` for app DB, `scripts/run_migrations.py`), but none of them are wired to corpus SQLite. v2 §7 elevates this to an open question: build new vs. extend `app_platform/db/migration.py`.

**Frontmatter is strict allow-list, AND mirrored in two more places.** `core/corpus/frontmatter.py:30,57-58,284` — `FIELD_ORDER` enumerates 25 valid fields; unknown fields raise `'unexpected field'`. **But the document-column tuple is ALSO duplicated in two ingest paths**:
- `core/corpus/ingest.py:29-55` — `_DOCUMENT_COLUMNS` (used by accession-bridged ingest).
- `core/corpus/reconciler/db_sync.py:15-43` — separate `_DOCUMENT_COLUMNS` (used by full-rebuild reconciler).

Adding a new column requires lockstep edits in **5 locations**: `schema.sql`, `frontmatter.FIELD_ORDER` + appropriate nullable set, `ingest._DOCUMENT_COLUMNS`, `reconciler/db_sync._DOCUMENT_COLUMNS`. For `parser_schema_version: int`, none of the existing nullable sets fit (`NULLABLE_STRING_FIELDS` is string-only) — a new `NULLABLE_INT_FIELDS` is required. Walker also re-uses the parser and skips files that fail validation (`core/corpus/reconciler/walker.py:88`), so any breakage cascades into corpus invisibility.

**Canonical path is content-hash-derived.** `core/corpus/frontmatter.py:252` — filename = `f"{form_type}_{fiscal_period}_{content_hash}.md"`. **Re-ingestion with new parser output produces a different content_hash → different filename → different file path.** The old file persists on disk. The walker (`core/corpus/reconciler/walker.py:60-82`) sees both files mapped to the same `document_id`, picks the highest-sort-key one as authoritative, lists the rest as `other_files`. This is a load-bearing constraint for the re-ingest design (§4.2).

**Delta ingest is accession-additive only.** `scripts/corpus_phase1_delta_ingest.py:88-120` — `discover_new_filings` calls `existing_accessions(db, ticker)` and skips any accession already in DB. There is no path that re-fetches an existing accession.

**Lock-file is bypassed in production.** `scripts/corpus_phase1_delta_ingest.py:217` — lock-file logic runs only when caller passes `--lock-file`. Systemd timers pass it. **Celery worker `delta_ingest_daily` (`workers/tasks/corpus.py:31-37`) calls `main([])` with no args** — no lock. Means current Celery + systemd can already race; adding a re-ingest runner adds a third concurrent path. Wiring `--lock-file` through Celery is a v2 prerequisite.

**Soak observable is divergence-counted, not hash-counted.** `scripts/corpus_phase1_soak_check.py:34-76` reads `delta_<date>.jsonl` for delta errors and `reconciler_<date>.jsonl` for drift. Drift is computed in `workers/tasks/corpus.py:62` as `rows_marked_orphan + len(report.divergences)`, NOT direct content_hash diff. The divergence source is `core/corpus/reconciler/walker.py:70` (the same-document_id grouping that produces `other_files`). v1 framed soak decoupling as a soak-check filter; v2 moves it to the divergence source by deleting old files at re-ingest time so no divergence ever surfaces.

**Full rebuild does not re-fetch.** `scripts/corpus_full_rebuild.py:14-37` calls `reconcile(corpus_root, db)` which walks markdown already on disk. It rebuilds the index from frozen content; it does not call Edgar_updater. A "fresh ingest" that pulls the upstream fix requires re-fetching markdown first.

## 3. Gaps to Close

| Gap | Why it matters | Proposed location |
|---|---|---|
| Producer doesn't stamp `parser_version` | Without a version stamp, consumer can't detect drift even if it captures the fields | Edgar_updater `SectionsResponse` |
| Producer has no invalidation feed | Bug fixes flow into new accessions only; existing docs need explicit nudge | Edgar_updater new endpoint + checked-in YAML |
| Consumer drops the parser-provenance fields it already receives | `parser_path`, `cross_reference_target`, `state`, `result_status` are visible TODAY but never read | risk_module `edgar_api_client.py` + schema + frontmatter |
| No `corpus_schema_version` migration mechanism | Field additions require manual lockstep edits across **5 files**; no rollback signal. Existing migration scaffolds (`app_platform/db/migration.py`, `database/migrations/`) are not wired to corpus SQLite. | risk_module `core/corpus/migrations/` (new) OR extend `app_platform/db/migration.py` (open question §7) |
| Document-column tuple duplicated across 3 files | `frontmatter.FIELD_ORDER`, `ingest._DOCUMENT_COLUMNS`, `reconciler/db_sync._DOCUMENT_COLUMNS` must stay in lockstep | Either consolidate into a single shared tuple (refactor) OR document the lockstep requirement and add a parity test (cheaper) |
| Delta ingest has no re-fetch hook | Hardcoded "new accessions only" — invalidation feed has nowhere to inject | risk_module `scripts/corpus_phase1_delta_ingest.py` |
| Re-ingest creates walker divergence | New content_hash → new filename; old file persists; walker logs divergence; reconciler counts it; soak gate fails | Re-ingest must atomically write new + delete old; no divergence is ever logged (§4.2, §4.4) |
| Lock-file bypassed by Celery worker | `delta_ingest_daily` calls `main([])` with no `--lock-file`; concurrent runs already possible today, re-ingest runner makes it worse | `workers/tasks/corpus.py:33` — wire `--lock-file` arg through |
| No re-ingest provenance log | "Did the F64 sweep land?" requires human memory + git archeology | risk_module new table |
| No invalidation failure policy (producer) | Malformed `INVALIDATIONS.yaml` could fail-open (silent staleness) or fail-closed (broken delta ingest) | Edgar_updater endpoint must define behavior; v2 specifies fail-closed (§4.2) |
| No consumer DOS guards | Single invalidation entry with 10,000 accessions overwhelms parse/queue/log even if daily ingest cap holds | risk_module — entry-level cap, run-level cap, predicate timeout, log size cap (§4.2) |

## 4. Proposed Design

Two-layer contract; both sides implement halves.

### 4.1 Layer 1 — passive provenance (every response stamps itself)

**Producer (Edgar_updater):**

1. **Add `parser_version` field to `SectionsResponse`** — string. Source: git SHA of `edgar_api/` + `edgar_parser/` packages, computed at server start (read once, cached). Bumps when those packages change. Example: `"a1b2c3d"`.
2. **Add `parser_schema_version: int` constant** — bumped manually when section taxonomy changes (rescue path added, new state added, four-state contract changed). Coarser than `parser_version`. Source: constant in `edgar_parser/__init__.py`. Today implicitly = current Phase 4 four-state contract; explicit value should be `1`.
3. Both fields appear at top level of `SectionsResponse` (extra fields permitted by `ConfigDict(extra="allow")`, so no breaking change).

**Consumer (risk_module):**

1. **Capture parser-provenance fields** in `edgar_api_client.get_filing_sections()` — extract `parser_version`, `parser_schema_version`, `parser_path`, `state`, `result_status`, `cross_reference_target`, `producer_deployment_id` (P2 fold — see open question §7) from the response and thread through the ingest pipeline.
2. **Add columns to `documents` (lockstep with `core/corpus/ingest.py:29-55` `_DOCUMENT_COLUMNS` AND `core/corpus/reconciler/db_sync.py:15-43` `_DOCUMENT_COLUMNS`):**
   - `parser_version TEXT`
   - `parser_schema_version INTEGER`
   - `parser_path TEXT`
   - `parser_state TEXT`             — Phase 4 four-state per-document summary (or NULL if mixed)
   - `parser_result_status TEXT`
   - `cross_reference_target TEXT`
   - `producer_deployment_id TEXT`   — required env label like `edgar-prod`, `edgar-staging`, `local-henry`
   - `producer_instance_id TEXT`     — optional: hostname / k8s pod / ECS task ARN (debugging only)
   - `producer_build_id TEXT`        — optional: image digest / CI build SHA (debugging only)
3. **Add `corpus_schema_version` migration mechanism** — see §7 open question for build-new vs. extend-`app_platform/db/migration.py`. Either way, the table itself:
   ```sql
   CREATE TABLE corpus_schema_version (
     version INTEGER PRIMARY KEY,
     applied_at TIMESTAMP NOT NULL,
     description TEXT NOT NULL
   );
   ```
   Bump from implicit `1` → explicit `2` for the parser-provenance columns. Migrations run idempotently from `core/corpus/migrations/NNNN_*.sql` (or chosen scaffold's equivalent). Walker validation (`core/corpus/reconciler/walker.py:88`) skips files that fail frontmatter validation, so a half-applied migration could disappear corpus content — migration runner must be transactional.
4. **Mirror in frontmatter** — add the nine fields to `FIELD_ORDER`. Eight are nullable strings → add to `NULLABLE_STRING_FIELDS`. `parser_schema_version` is `int` → add a NEW `NULLABLE_INT_FIELDS` set + corresponding validation branch right after the nullable-string loop (`core/corpus/frontmatter.py:294`):
   ```python
   for field in NULLABLE_INT_FIELDS:
       value = normalized.get(field)
       if value is None:
           continue
       # Reject bool: Python's bool is a subclass of int, but schema semantics
       # require true integers. isinstance(True, int) → True, hence the explicit guard.
       if isinstance(value, bool) or not isinstance(value, int):
           invalid_types.append((field, f'expected int or null, got {type(value).__name__}'))
   ```
5. **Backfill at ingest time only** — existing rows have NULL parser_version (unknown). No retroactive backfill — that's what the invalidation sweep is for.
6. **Add a parity test** — `tests/test_corpus_schema_parity.py`. Codex R2 P2 #1 corrected v2's "all four sets equal" claim — DB has columns frontmatter doesn't (`file_path`, `is_superseded_by`, `last_indexed`). Correct shape:
   ```python
   def test_schema_parity():
       # Load schema into in-memory SQLite
       conn = sqlite3.connect(':memory:')
       conn.executescript(Path('core/corpus/schema.sql').read_text())
       db_columns = {row[1] for row in conn.execute('PRAGMA table_info(documents)')}

       from core.corpus.ingest import _DOCUMENT_COLUMNS as ingest_cols
       from core.corpus.reconciler.db_sync import _DOCUMENT_COLUMNS as recon_cols
       from core.corpus.frontmatter import FIELD_ORDER

       # Two ingest tuples must agree exactly (and in order — both UPSERT against schema)
       assert ingest_cols == recon_cols

       # Ingest tuple = DB columns minus DB-only metadata
       DB_ONLY = {'is_superseded_by', 'last_indexed'}
       assert set(ingest_cols) == db_columns - DB_ONLY

       # Frontmatter = ingest tuple minus computed fields
       FRONTMATTER_EXCLUDED = {'file_path'}  # canonical_path computes this
       assert set(FIELD_ORDER) == set(ingest_cols) - FRONTMATTER_EXCLUDED
   ```
   Catches the most common drift (column added to schema.sql but missed in tuples) by asserting set equality with explicit exclusions, not just superset.

**Rationale for two version axes:** `parser_version` is fine-grained and auto-bumps on any code change (cheap to compare). `parser_schema_version` is coarse and human-curated (semantic — bumps mean "this is a different parser now"). Together they let invalidation predicates target either narrow regressions or full taxonomy shifts.

### 4.2 Layer 2 — active invalidation feed

**Prerequisites (must land before §4.2 ships):**

- **Wire `--lock-file` through Celery.** `workers/tasks/corpus.py:33` (`delta_ingest_daily`) currently calls `corpus_phase1_delta_ingest.main([])` with no args. Original commit `745d00c5` predates the `--lock-file` support; the no-lock call was inertia, not intent (verified per Codex R2). Change to:
  ```python
  _DEFAULT_LOCK_PATH = Path(os.environ.get('CORPUS_LOCK_FILE', '/run/corpus_promote.lock'))

  @shared_task(name='corpus.delta_ingest_daily')
  def delta_ingest_daily() -> dict[str, Any]:
      code = corpus_phase1_delta_ingest.main(['--lock-file', str(_DEFAULT_LOCK_PATH)])
      ...
  ```
  Default path matches systemd's existing `/run/corpus_promote.lock`. Add same wiring to the future re-ingest task. Without this, three concurrent paths (systemd, Celery, re-ingest) race on the same DB.

**Producer (Edgar_updater):**

1. **Checked-in `Edgar_updater/INVALIDATIONS.yaml`** — append-only log. Each entry:
   ```yaml
   - id: F50-citi-class
     parser_version_introduced: "7ed2f86"
     parser_version_fixed: "<sha-when-fix-lands>"
     fixed_at: "2026-05-XX"
     rationale: "Citi-class section absorption — Financial Statements absorbs through end of doc."
     scope:
       form_types: ["10-Q"]
       predicate:
         # SQL-ish over consumer's documents columns (allow-list; not raw SQL)
         where: "ticker = 'C' AND form_type = '10-Q'"
       # Optional explicit list (precise; from human probe). Producer SHOULD cap at 1,000 per entry.
       accessions:
         - "0000831001-25-000086"
         - "..."
   - id: F64-item7-rescue
     parser_version_introduced: "TBD"
     parser_version_fixed: "TBD"
     scope:
       form_types: ["10-K"]
       predicate:
         where: "cross_reference_target IS NOT NULL OR parser_path = 'rescue_v2'"
   ```
2. **New endpoint `GET /api/invalidations?since=<parser_version>`** — returns all entries with `parser_version_fixed > since` (ordered chronologically). Backed by `INVALIDATIONS.yaml` rendered through Pydantic. Cached in-memory; re-read on file mtime change.
3. **Failure policy: fail-CLOSED.** If `INVALIDATIONS.yaml` fails Pydantic validation, the endpoint returns `503 Service Unavailable` with the validation error, NOT an empty list. Rationale: returning `[]` on parse failure silently preserves stale corpus across all consumers — worse failure mode than a noisy alarm. Producer alerts on 503; consumer logs and skips invalidation step but continues normal delta ingest. New staleness is impossible; old staleness persists until YAML is fixed.
4. **PR discipline:** parser-touching PRs require an `INVALIDATIONS.yaml` entry OR an explicit `# no-corpus-impact` annotation in the PR description. Pre-commit hook checks the diff against a list of parser-touching paths and warns if neither is present.

**Consumer (risk_module):**

1. **New step in `corpus_phase1_delta_ingest.py`** — BEFORE `discover_new_filings`:
   ```python
   floor_version = db.execute(
       "SELECT MIN(parser_version) FROM documents WHERE source = 'edgar' AND parser_version IS NOT NULL"
   ).fetchone()[0]
   try:
       invalidations = edgar_api_client.get_invalidations(since=floor_version, timeout=30)
       accessions_to_refresh = resolve_invalidations(db, invalidations)
   except (EdgarAPIError, InvalidationParseError) as exc:
       _LOG.warning('invalidation feed unavailable; skipping refresh', exc_info=True)
       accessions_to_refresh = []
   # Treat as new even if present in DB; gated by per-run cap
   ```
   Predicate resolution runs against the local `documents` table — no Edgar_updater queries beyond fetching the YAML. Explicit accession lists short-circuit predicate evaluation.
2. **Re-ingest is a recoverable state machine, NOT an atomic transaction.** SQLite + filesystem operations cannot be atomic — Codex R2 P1 #1. v3 explicitly models re-ingest as a state machine where the log entry is the source of truth for in-progress work. Recovery is deterministic.

   **Why not supersession**: bumping `document_id` to `edgar:<accession>:v2` would (a) break the "one row per accession" assumption used across the codebase, (b) require every reader to handle multi-row results, (c) leave the old markdown on disk as walker `other_files`. Overwrite-with-state-machine keeps the data model unchanged; audit + recovery live in the log.

   **Phases (status = last *completed* phase, written AFTER work commits):**

   | Status | Set after | What it means | What may not yet have happened |
   |---|---|---|---|
   | `planned` | initial INSERT | old_path/old_hash/old_parser_version captured; **`new_file_path` and `new_content_hash` ALSO captured** (both computable from API response via `canonical_path()` + content hashing before any disk write); started_at = now() | new file not yet written |
   | `new_written` | new markdown file successfully written | file is on disk at `new_file_path` (which was already recorded at `planned`) | DB still points at old file |
   | `db_upserted` | UPSERT commits | `documents.file_path` now points at new_path; all new provenance columns populated | old file may still exist on disk |
   | `old_deleted` | `Path(old_file_path).unlink()` succeeds | old markdown file is gone | `completed_at` not yet set |
   | `complete` | `completed_at` written | terminal success | — |
   | `no_change` | hash short-circuit | `new_hash == old_hash`; no writes done | — terminal |
   | `<phase>_failed` | exception caught at phase boundary | `error` field captured; phase's work did NOT complete | next phase didn't start |
   | `abandoned` | recovery determines retry-from-scratch is safer | terminal — superseded by a fresh `planned` entry | — |

   **Each status update is its own small DB transaction** (`with db:` block per phase). Never wrap multiple phases in a single transaction — that would hide partial state from recovery. Specifically:
   - INSERT `planned` → commit.
   - Write new file (filesystem op, no DB).
   - UPDATE `new_written` → commit.
   - UPSERT documents row + UPDATE log status to `db_upserted` → SAME transaction (these MUST be atomic together so DB and log agree about what's authoritative).
   - Unlink old file (filesystem op, no DB).
   - UPDATE `old_deleted` → commit.
   - UPDATE `complete` + `completed_at` → commit.

   **Phase ordering rationale:**
   - `planned` insert before any work means partial work is always traceable.
   - DB UPSERT bundled atomically with status flip to `db_upserted` ensures recovery never sees DB pointing at new file with status still `new_written` (would corrupt sweeper logic).
   - `old_deleted` and `complete` are separate commits so sweeper has a clean target state to advance.

   **No-change short-circuit:** if `new_hash == old_hash` (computed before any writes), skip phases entirely; INSERT log entry with `content_changed=0`, `status='no_change'`, both paths set to old_path. Saves disk + walker work.

   **Recovery on startup** (read `corpus_reingest_log WHERE status NOT IN ('complete', 'no_change', 'abandoned')` ordered by `started_at`). The recovery script (NOT the normal ingest call) owns all transitions; ingest never has to know about stale siblings. Per status:
   - `planned`: new file write may or may not have happened. Because `new_file_path` + `new_content_hash` were captured at `planned` (v5 fix), recovery is uniquely determinable:
     - `Path(new_file_path).exists()` AND file's frontmatter content_hash matches `new_content_hash` → file was written but status flip never landed. Advance to `new_written`.
     - `Path(new_file_path).exists()` AND hash mismatch → foreign file collision (extremely unlikely under content-hash-derived paths, but possible). Alert; do NOT delete; mark this row `*_failed` for operator.
     - `Path(new_file_path)` does NOT exist → file was never written (or was cleaned up). Choose: (a) write file fresh, then advance through phases; or (b) if older than retry-threshold (e.g., 24h), mark `abandoned` and let invalidation feed re-queue.
     - When recovery decides to ABANDON: write `abandoned` status AND the replacement `planned` row (if any) **in the same small transaction**, so a death between leaves no inconsistent state.
   - `new_written`: new file exists; DB still points at old. Retry the UPSERT-+-status-flip transaction (idempotent — UPSERT updates same row to same target).
   - `db_upserted`: DB on new; old file may exist. Proceed to delete old (advance to `old_deleted`, then `complete`).
   - `old_deleted`: old file should be gone; just need `complete` flip. Verify `not Path(old_file_path).exists()`; if it exists (rare race), retry unlink first.
   - `*_failed`: alert operator; do not auto-retry without human ack. Optionally allow operator to flip status back to the prior successful phase to resume.

3. **Provenance + recovery log table:**
   ```sql
   CREATE TABLE corpus_reingest_log (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     document_id TEXT NOT NULL,
     accession TEXT NOT NULL,
     ticker TEXT NOT NULL,
     old_file_path TEXT,                      -- captured at 'planned'; nullable for first-ingest edge cases
     new_file_path TEXT NOT NULL,             -- captured at 'planned' (computable via canonical_path() before any write); immutable thereafter
     old_content_hash TEXT,
     new_content_hash TEXT NOT NULL,          -- captured at 'planned' (hash of API response body); immutable thereafter
     content_changed INTEGER NOT NULL DEFAULT 0,  -- 0 if no-change re-ingest, 1 if changed
     parser_version_before TEXT,
     parser_version_after TEXT,
     reason TEXT NOT NULL,                    -- 'invalidation' | 'manual' | 'version_floor'
     invalidation_id TEXT,
     status TEXT NOT NULL,                    -- see CHECK below
     started_at TIMESTAMP NOT NULL,
     completed_at TIMESTAMP,                  -- NULL until terminal state (complete | no_change | abandoned)
     error TEXT,                              -- captured on *_failed states
     CHECK (status IN (
       -- Active (non-terminal) states
       'planned', 'new_written', 'db_upserted', 'old_deleted',
       -- Terminal success states
       'complete', 'no_change',
       -- Terminal abandonment
       'abandoned',
       -- Failure states (can be retried after operator ack)
       'planned_failed', 'new_written_failed', 'db_upserted_failed', 'old_deleted_failed'
     ))
   );
   CREATE INDEX idx_reingest_invalidation ON corpus_reingest_log(invalidation_id);
   CREATE INDEX idx_reingest_document ON corpus_reingest_log(document_id, started_at);
   CREATE INDEX idx_reingest_active ON corpus_reingest_log(status)
     WHERE status NOT IN ('complete', 'no_change', 'abandoned');
   ```
   Active states: `planned`, `new_written`, `db_upserted`, `old_deleted`. Terminal states: `complete`, `no_change`, `abandoned`. Failure states are non-terminal but require operator action (no auto-retry).

   `status`/`completed_at`/`error` are mutated as the state machine advances. **All other columns** — including `new_file_path` and `new_content_hash` — **are set at INSERT (`planned`) and immutable thereafter.** This is what makes `planned` recovery uniquely determinable: the recovery script knows the expected new file's path AND hash before any disk write occurred. Powers both audit (`WHERE invalidation_id = 'F64-item7-rescue' AND status = 'complete'`) and recovery (`WHERE status NOT IN ('complete', 'no_change', 'abandoned')`).

   **`_UPSERT_MUTABLE_COLUMNS` in `core/corpus/ingest.py:57` must be extended to include ALL new provenance columns** so re-ingest UPDATEs them, not just on first INSERT:
   - `parser_version`, `parser_schema_version`, `parser_path`, `parser_state`, `parser_result_status`, `cross_reference_target`
   - `producer_deployment_id`, `producer_instance_id`, `producer_build_id`
4. **API budget cap:** new env `EDGAR_REINGEST_DAILY_CAP` (default 100). Delta ingest stops queuing after the cap; remainder rolls to next day. Logged so it's visible.
5. **DOS guards (defense in depth):**
   - `EDGAR_INVALIDATION_MAX_ACCESSIONS_PER_ENTRY` (default 1,000) — consumer rejects entries with explicit accession lists exceeding this. Logs as `invalidation_entry_too_large`. Producer policy mirrors but consumer doesn't trust producer.
   - `EDGAR_INVALIDATION_MAX_QUEUED_PER_RUN` (default 500) — total accessions queued from invalidations in one delta-ingest run. Larger sets spread across multiple runs.
   - `EDGAR_INVALIDATION_PREDICATE_TIMEOUT_SEC` (default 30) — wall-clock cap on predicate evaluation against `documents`. SQL allow-list (§7) makes this hard to exceed but defense-in-depth.
   - Provenance log rotation: nightly job archives entries older than 90 days to a separate file (size cap on the live table).

### 4.3 Refresh policy (composition)

Three triggers, in priority order:

1. **Invalidation feed** (highest priority) — bug fixes. Bounded scope, human-curated.
2. **Version floor sweep** (medium priority) — catches silent drift. Configurable `MIN_PARSER_VERSION` env; any doc below it gets queued. Default: unset (off). Used for forced upgrades after big parser milestones.
3. **Periodic full refresh** (low priority, off by default) — quarterly cadence in production. Burns API budget; bulletproof. Disabled by default; enabled via cron + `--all` flag on the delta script.

All three feed the same `accessions_to_refresh` queue, gated by the daily budget cap.

### 4.4 Soak-clock decoupling — at the divergence source + recovery sweeper

**v1 was wrong.** v1 proposed filtering drift at the soak-check layer. But by then the divergence is already logged in `reconciler_*.jsonl`, the alert in `workers/tasks/corpus.py:64` (`if drift > 5:`) already fired, and the soak counter is already perturbed. The fix has to happen UPSTREAM of all that.

**Real source of divergence**: `core/corpus/reconciler/walker.py:60-82` groups markdown files by `document_id`. When two files map to the same `document_id` (the inevitable result of a re-ingest under content-hash-derived filenames per `frontmatter.py:252`), the walker picks one as authoritative and tags the others as `other_files`. That `other_files` list flows into `report.divergences` in `db_sync.sync_documents`, which becomes part of `reconciler_*.jsonl`'s drift count.

**Approach: eliminate divergence at the happy path; recover from failures via a state-aware sweeper.** The state machine in §4.2 deletes the old markdown file as the `old_deleted` phase. On success, only ONE file maps to that `document_id`. Walker sees no extra files. Soak counter unperturbed.

**Why this works on the happy path**: soak measures *ingest-machinery health* via *unexpected on-disk state*. A re-ingest that cleans up after itself produces no unexpected state. We're not "filtering" drift — we're not creating drift in the first place.

**Failure paths require a state-aware sweeper.** v2's sweeper used `Path.exists()` only, which Codex R2 P1 #2 + #3 correctly flagged as insufficient and race-prone. v3 sweeper rules (run nightly):

```sql
-- Eligible rows for sweeper attention:
SELECT log.id, log.document_id, log.old_file_path
FROM corpus_reingest_log log
JOIN documents doc ON doc.document_id = log.document_id
WHERE log.status IN ('db_upserted', 'old_deleted', 'old_deleted_failed')
  AND log.old_file_path IS NOT NULL
  -- DB must point at the NEW path, not the old one
  AND doc.file_path != log.old_file_path
  -- No other in-progress re-ingest of this document
  AND NOT EXISTS (
    SELECT 1 FROM corpus_reingest_log active
    WHERE active.document_id = log.document_id
      AND active.status NOT IN ('complete', 'no_change', 'abandoned')
      AND active.id != log.id
  )
  -- Path.exists() check happens in Python AFTER the DB query (filesystem state is racy)
```

For each row passing the filter:
1. Re-verify `Path(old_file_path).exists()`. If file is already gone (status was `db_upserted`, file already deleted by something else, or status was `old_deleted` but `complete` flip never landed), skip to step 4.
2. **Belt-and-suspenders**: read the old file's frontmatter and verify its `content_hash` matches `log.old_content_hash`. If mismatch (filename collision, foreign file in path), skip and alert. Do NOT delete.
3. Unlink old file. Advance `status` to `old_deleted` (separate small transaction).
4. Advance `status` to `complete`, set `completed_at = now()` (separate small transaction).
5. Log the recovery action.

**Sweeper covers all post-`new_written` death points:**
- Death after `new_written` → SQL filter excludes (status not in target set); recovery script handles it (retry UPSERT).
- Death after `db_upserted` → SQL filter includes; sweeper deletes old file + advances to `complete`.
- Death after `old_deleted` → SQL filter includes; sweeper sees file already gone, advances to `complete`.
- Death after `complete` → already terminal; SQL filter excludes.

**Why the DB-state guard matters (R2 P1 #3)**: under rapid successive re-ingests of the same accession, log entry 1's `old_file_path` could become log entry 2's `new_file_path` if hashes happen to match historically. Naive `Path.exists()` deletion would clobber a now-authoritative file. The `documents.file_path != log.old_file_path` check + content_hash verification prevent this.

**Walker behavior during the small window between `db_upserted` and `old_deleted`**: walker would see two files, report `other_files` divergence. Mitigation lives in the reconciler/task layer, NOT the walker (Codex R3 P2 #2 — walker is disk-only by design; making it DB-aware is a layering violation). Specifically:

- `core/corpus/reconciler/walker.py` keeps reporting raw `other_files` divergences as today. No DB dependency added.
- `workers/tasks/corpus.py reconciler_daily` (line 49+), AFTER calling `reconcile()`, runs ONE query into a Python `set`:
  ```python
  try:
      active_old_paths = {
          row[0] for row in db.execute(
              "SELECT old_file_path FROM corpus_reingest_log "
              "WHERE status IN ('db_upserted', 'old_deleted', 'old_deleted_failed') "
              "AND old_file_path IS NOT NULL"
          )
      }
  except sqlite3.OperationalError:
      active_old_paths = set()  # fresh corpus, table not yet created
  ```
  Then a single linear pass over `report.divergences`: each divergence whose extra file path is in `active_old_paths` is reclassified as `expected_during_reingest`. **Forbid per-divergence SQL queries** — the set lookup is O(1) per divergence, total O(divergences + active_reingests).
- Drift threshold (`if drift > 5:`) and soak counter both consume the post-filtered count.
- **Fresh-corpus / pre-migration handling**: the `try/except sqlite3.OperationalError` above (`no such table: corpus_reingest_log`) treats missing table as empty. New installs and pre-P1 corpora keep working without the table existing yet.

**This IS a narrow soak-check filter**, scoped strictly to known in-flight re-ingests (matched by exact `old_file_path`). Not a blanket "ignore all drift."

**Test coverage required:**
- Happy path: re-ingest end-to-end → new file exists → old does not → DB updated → log entry `complete` → reconcile reports zero divergences.
- Process death simulations at each phase boundary; assert recovery on next startup completes the work or marks `*_failed`.
- Sweeper race test: spawn two concurrent re-ingests of the same accession, assert sweeper doesn't delete the wrong file.
- Sweeper file-mismatch test: place a foreign file at `old_file_path` (different content_hash); assert sweeper skips and alerts instead of deleting.

## 5. Phasing

Each phase is independently mergeable and produces a useful outcome. **Phasing is partially flexible**: P2 can ship before P1 (pre-P1 consumer ignores extra JSON fields), P4-cleanup can ship with P3. Strict ordering only matters where called out.

### P0 — Lock-file prerequisite (risk_module-only, must ship first)

Wire `--lock-file` through the Celery `delta_ingest_daily` task. Independent of parser-version work; closes a pre-existing concurrent-run race that re-ingest would amplify.

**Acceptance:**
- `workers/tasks/corpus.py:33` passes `--lock-file` arg.
- Test: two parallel calls to `delta_ingest_daily` — second exits with lock-acquired-failure code, not by writing to DB.

### P1 — Consumer captures existing provenance (risk_module-only)

Capture `parser_path`, `state`, `result_status`, `cross_reference_target` from `SectionsResponse`. Add columns + frontmatter + migration. **Forward-only backfill.**

**Prerequisite verification (before P1 ships):** probe a real Edgar_updater `/api/sections` response (live or recorded fixture) and confirm `parser_path`, `state`, `result_status`, `cross_reference_target` are populated at TOP LEVEL of the response, not just per-section. Repo tests today only fixture section-level state (`tests/test_corpus_ingest_accession.py:81`), so this is unverified from this repo. **If top-level fields are NOT populated, P1 depends on P2** (a producer change to thread per-document summaries to top level) and the phasing inverts.

**Outcome:** for every doc ingested after P1 ships, we know which parser path produced it. Item 7 cross-reference docs become queryable. Sets up everything else.

**Acceptance:**
- Prerequisite probe documented with response sample.
- New columns exist on `documents`; migration test asserts old + new schemas both load.
- Schema-parity test passes (asserts `frontmatter.FIELD_ORDER`, `ingest._DOCUMENT_COLUMNS`, `reconciler/db_sync._DOCUMENT_COLUMNS` all agree).
- One end-to-end test: ingest one fixture filing, assert columns populated.
- Frontmatter round-trips the new fields.
- `NULLABLE_INT_FIELDS` validator branch has direct unit-test coverage.

### P2 — Producer stamps parser_version + parser_schema_version + producer_deployment_id (Edgar_updater)

Add the three fields to `SectionsResponse`. Stamp at server start. Bump `parser_schema_version` to `1` (explicit). `producer_deployment_id` distinguishes dev vs. prod Edgar_updater (handles cross-deployment skew per §7). Slot as a sub-phase under `PLAN-parser-health-phase3-sections.md` or as Phase 4 of the parser-health observability plan — confirm with that plan's owner.

**Outcome:** every response self-identifies its parser version + deployment. Combined with P1, the corpus knows what produced each doc and from where.

**Acceptance:**
- `SectionsResponse` includes all three fields.
- Restart-time SHA computation; cached for the process lifetime.
- One contract test: `/api/sections` response includes non-null `parser_version` + `producer_deployment_id`.

### P3 — Invalidation feed (Edgar_updater + risk_module)

`INVALIDATIONS.yaml` + `/api/invalidations` endpoint + consumer hook + provenance log + budget cap + DOS guards + overwrite-with-cleanup re-ingest mechanism. Backfill the YAML with F50 + F64 entries when their upstream fixes land.

**Outcome:** parser fixes flow into the corpus automatically within one delta-ingest run.

**Acceptance:**
- YAML schema validation in Edgar_updater CI.
- Producer endpoint returns 503 on malformed YAML (fail-closed test).
- Consumer hook unit test: given a YAML entry, queues the right accessions.
- End-to-end test: simulated invalidation entry triggers re-fetch, overwrites markdown atomically (new file present + old file absent), updates `documents` row, writes provenance log entry.
- Reconcile-after-reingest test: zero divergences post-re-ingest.
- Budget cap test: queue exceeding cap rolls remainder to next run.
- DOS-guard tests: entry with 10,001 explicit accessions rejected; per-run queue bounded.
- Cleanup-failure test: simulated old-file-delete failure → entry in log, sweeper detects + cleans next run.

### P4 — Version-floor sweep + periodic refresh (risk_module)

Version-floor env + optional periodic refresh. P4 does NOT include soak filtering (that work moved into P3 — divergence elimination at re-ingest time per §4.4).

**Outcome:** F51 soak gate survives invalidation sweeps automatically (P3 guarantees zero divergence). Operator can force a parser-version upgrade with `MIN_PARSER_VERSION=...`.

**Acceptance:**
- Version-floor sweep dry-run reports queued count without ingesting.
- Periodic-refresh cron entry documented; off by default.

## 6. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Producer adds `parser_version` but consumer hasn't shipped P1 yet | High during rollout | Both sides default-tolerant: P2 can ship independently because pre-P1 consumer's `_request_json` ignores extra fields (Pydantic on producer = `extra="allow"`; consumer just `resp.json()` discards unread keys). |
| `INVALIDATIONS.yaml` discipline erodes over time | Medium | Pre-commit hook on parser-touching paths; quarterly review of YAML coverage vs. parser commits; add to `BUGS.md` review checklist. |
| Predicate resolution diverges between Edgar_updater intent and corpus query | Medium | Predicates run against the *consumer's* `documents` table using a SQL allow-list (column whitelist + operator whitelist; see §7 Q4). Producer documents the column semantics expected by predicates; consumer test asserts predicate parser handles each documented operator and rejects everything else. |
| Invalidation sweep blows past API budget | Low if cap shipped | Daily cap + per-run cap + per-entry cap (§4.2). Spillover to next run. Queue persists across runs. Operator visibility via log. |
| Re-ingest produces *new* drift the parser missed | Low | Same content_hash → no-op (skip write, log "no-change re-ingest"). Different hash → log to `corpus_reingest_log` with full provenance. |
| Concurrent re-ingest + delta-ingest + Celery race | **High today, mitigated by P0** | Pre-P0: lock-file is bypassed by `workers/tasks/corpus.py:33`, so systemd + Celery already race. P0 wires `--lock-file` through Celery before P3 ships. Re-ingest runner uses the same lock path. Verified by parallel-task test. |
| Cleanup-failure leaves orphan markdown after re-ingest | Low | §4.4 sweeper script reads `corpus_reingest_log` for entries with non-null `old_file_path`, deletes any survivors. Runs nightly. Tagged in soak as expected drift if found. |
| Walker validation skips files after migration | Medium during P1 deploy | `walker.py:88` skips files that fail frontmatter validation. A half-applied migration (new schema, old frontmatter) makes corpus invisible. Migration runner must be transactional + Phase-1-style canary deploy (run on staging slice first; verify reconcile drift = 0 before prod). |
| `parser_version` SHA bumps for unrelated code (docstring edits) | Medium | Acceptable — version-floor is opt-in; default policy uses invalidation feed (human-curated). Noisy bumps don't trigger re-ingests, just inflate "we have N versions in our corpus" diversity. |
| Malformed `INVALIDATIONS.yaml` silently preserves staleness (fail-open trap) | Low — design choice locked | §4.2 chooses fail-CLOSED: producer endpoint returns 503; consumer skips invalidation step but normal delta ingest continues. Producer must alert on 503 (already covered by existing health monitoring). |
| Single invalidation entry with 10,000+ accessions DOSs consumer | Low if guards shipped | §4.2 DOS guards: `MAX_ACCESSIONS_PER_ENTRY=1,000`, `MAX_QUEUED_PER_RUN=500`, predicate timeout, log rotation. Consumer rejects entries exceeding per-entry cap; logs as `invalidation_entry_too_large`. |
| Cross-deployment version skew (dev vs. prod Edgar_updater) | Medium | `producer_deployment_id` field on `SectionsResponse` (§4.1) + `documents.producer_deployment_id` column. Provenance log + invalidation predicates can scope to a specific deployment. Version-floor sweep can target by deployment. |
| Schema-tuple drift between `frontmatter`, `ingest`, `reconciler/db_sync` | Medium-historical | Three duplicates exist today (`frontmatter.FIELD_ORDER`, `ingest._DOCUMENT_COLUMNS`, `reconciler/db_sync._DOCUMENT_COLUMNS`). v2 adds parity test (§4.1). Long-term refactor to single shared tuple is desirable but out of scope. |

## 7. Open Questions

1. **`parser_version` boundary** — whole-package SHA (simple, noisy) vs. per-module hash of `edgar_parser/section_parser.py` + rescue helpers (precise, fragile to file moves). **Recommendation:** whole-package SHA for v1; per-module if noise becomes a real problem.

2. **Where does parser-version computation live in Edgar_updater?** Options: (a) read at server start from `git rev-parse HEAD` over the package paths, (b) bake into a `_version.py` at deploy time via CI, (c) read from `edgar_api/__init__.py` + bump manually. **Recommendation:** (a) for dev, (b) for prod — Phase 3 health work may already need this; coordinate.

3. **`parser_schema_version` ownership** — who decides when to bump? **Recommendation:** Edgar_updater maintainer, on PRs that change `SectionsResponse` shape or add a new `state` value or new `parser_path` value. Document the bump rules in `Edgar_updater/CONTRIBUTING.md`.

4. **Predicate language safety — NOT trivial.** Codex R2 P1 #4 corrected v2's understatement. Allow-listing operators alone is insufficient if we string-concatenate; predicates must be tokenized, parsed to an AST, validated against allow-lists, and compiled to *parameterized* SQL. Required:

   **Tokenizer + parser:**
   - Tokens: `IDENT` (column names), `STRING_LIT` (quoted), `INT_LIT`, `OP` (`=`), `KEYWORD` (`IN`, `IS`, `NULL`, `NOT`, `AND`, `OR`), `LPAREN`, `RPAREN`, `COMMA`, `EOF`.
   - **Illegal tokens cause immediate rejection**: `;`, `--`, `/*`, `*/`, `||`, backticks, any unrecognized character.
   - Parser MUST consume to `EOF`. Trailing tokens after a valid expression → reject.

   **Allow-lists:**
   - Columns: hardcoded set matching `documents` table columns (`ticker`, `form_type`, `parser_path`, `parser_state`, `parser_version`, `cross_reference_target`, `producer_deployment_id`, etc.). Anything else → reject at parse.
   - Operators: `=`, `IN`, `IS NULL`, `IS NOT NULL`, `AND`, `OR`. No `>`, `<`, `LIKE`, no arithmetic.

   **Compilation:**
   - Parsed AST → parameterized SQL via prepared statement. NEVER concatenate raw `where`.
   - Example: `where: "ticker = 'C' AND form_type IN ('10-K', '10-Q')"` →
     `WHERE ticker = ? AND form_type IN (?, ?)` with params `['C', '10-K', '10-Q']`.

   **Rejection walkthrough for `where: "1=1; DROP TABLE documents; --"`:**
   1. Tokenizer: `INT_LIT(1)`, `OP(=)`, `INT_LIT(1)`, illegal `;` → reject at tokenize step. Done.
   2. Even if `;` were tokenized as KEYWORD: parser expects `IDENT` (column name) at start of comparison, gets `INT_LIT` → reject.
   3. Even if `1` were parsed as a degenerate column: `1` is not in column allow-list → reject.
   4. Even if all the above failed: `DROP` is not in the parser's keyword set → reject as unknown token.

   Four independent layers must all fail for an injection to land.

   **Implementation: from-scratch tokenizer + recursive-descent parser, no `sqlparse` dep.** Codex R3 P2 #3: `sqlparse` accepts a much broader SQL surface than we need; even with allow-list wrappers it imports a transitive surface we'd have to audit. Hand-rolling is smaller, narrower, easier to reason about, and avoids a runtime dependency. **LoC estimate: ~180–220** (Codex R4 P2 #3 corrected v3's ~130 estimate — minimal-error code is ~130, but production code with dataclasses + useful errors lands closer to ~200). Approach unchanged.

5. **Invalidation idempotency** — what if delta ingest replays an invalidation entry? **Recommendation:** consumer tracks `(invalidation_id, document_id)` pairs already applied (`corpus_reingest_log` has both). Entries already applied at the same `parser_version_after` are skipped.

6. **Cross-package vendoring of `INVALIDATIONS.yaml`** — does risk_module need a copy, or always fetch live? **Recommendation:** always live via the API; cache the response for the duration of a delta-ingest run. Stateless consumer is simpler.

7. **Migration scaffold — build new vs. extend existing.** No corpus-specific migration mechanism exists. The repo has:
   - `app_platform/db/migration.py` — Postgres-targeted, used by app DB.
   - `database/migrations/` — also Postgres/app-DB-targeted.
   - `scripts/run_migrations.py` — runner for the above.

   Corpus is SQLite. None of the existing tooling targets SQLite. Options:
   - **(a) Build new `core/corpus/migrations/`** with a small idempotent runner. Cheap; isolates corpus from app-DB churn. Recommendation default.
   - **(b) Extend `app_platform/db/migration.py`** to support SQLite + add a corpus migrations dir. Reuses runner code; couples corpus migration semantics to app DB migration semantics; adds risk if app-DB migration patterns change.

   **Recommendation:** (a). The corpus DB is conceptually a separate system (different storage engine, different deployment lifecycle, different scale). Coupling its migrations to app-DB migrations would be a layering mistake. The new runner is ~100 lines.

8. **Cross-deployment producer identity scope.** `producer_deployment_id` distinguishes dev vs. prod Edgar_updater. Should risk_module REJECT documents from non-allowlisted deployments, or just record? **Recommendation:** record (column populated, log warning if unknown deployment). Rejection is too aggressive for v1; visibility is enough. Operator can grep the log for unexpected deployment IDs.

   **Required-vs-nullable consistency** (Codex R3 P2 #5 + R4 P2 #4): consumer treatment is **NULLABLE** — column allows NULL; absent value → store NULL (NOT a literal sentinel like `'unknown'`, which would mix absence with a valid label namespace). Side-channel: log warning at ingest time via existing logger; counter/metric exposed via `corpus_health_report` for visibility. If queries later need to distinguish "we didn't get one" from "we got the label `unknown`," add a separate `producer_deployment_missing INTEGER DEFAULT 0` flag column rather than poisoning the label space. Producer treatment is **REQUIRED** (Edgar_updater CI/contract test asserts every `SectionsResponse` includes a non-null `producer_deployment_id` matching `^[a-z0-9-]+$`). This split prevents v1-rollout breakage if the producer hasn't shipped the field yet but commits us to fixing the producer side via discipline rather than runtime enforcement.

## 8. Out of Scope

- Re-fetching transcripts (FMP, not Edgar_updater). **Same staleness pattern applies later** — `scripts/corpus_phase3_delta_transcripts.py:48` is also accession-additive only; FMP transcript provenance is currently just `fmp_transcripts@version` (`fmp/tools/transcripts.py:822`). When FMP ships its own parser-bug class, a sibling design doc applies the same primitives (per-doc parser_version + invalidation feed) to transcripts. Filed as future work; not addressed here.
- UI surfacing of "this doc was ingested with an old parser." Out of scope; downstream concern.
- Backfilling `parser_version` on docs ingested before P1. Out of scope — these docs land with NULL `parser_version`; the version-floor sweep (P4) is the right tool to upgrade them.
- Long-term refactor to consolidate the three duplicated `_DOCUMENT_COLUMNS` tuples (frontmatter, ingest, reconciler/db_sync) into a single shared source of truth. Worthwhile but unrelated to freshness; v2 adds parity test as the cheaper interim fix.
- Rejecting `SectionsResponse` from non-allowlisted producer deployments. v2 records `producer_deployment_id` but doesn't gate on it (see §7 Q8).

## 9. References

**Edgar_updater (producer — outside this sandbox):**
- `Edgar_updater/edgar_api/schemas.py:143-162` — current `SectionsResponse`.
- `Edgar_updater/edgar_api/health.py:87,130,205` — `parser_path` already in `filing_health`.
- `Edgar_updater/docs/plans/PLAN-parser-health-phase3-sections.md` — in-flight Phase 3.
- `Edgar_updater/docs/TODO.md:207-214` — JPM Item 7 cross-reference diagnosis.
- `Edgar_updater/edgar_api/__init__.py:3` — `__version__ = "0.1.0"`; no `pyproject.toml`.

**risk_module (consumer):**
- `core/corpus/edgar_api_client.py:60-71,76-102` — current consumer (drops extras from response body).
- `core/corpus/schema.sql:1-36` — current `documents` schema (28 columns).
- `core/corpus/frontmatter.py:30,57-58,252,284` — strict allow-list + content-hash-derived canonical path.
- `core/corpus/ingest.py:29-55,57+` — `_DOCUMENT_COLUMNS` + `_UPSERT_MUTABLE_COLUMNS` (lockstep target #1).
- `core/corpus/reconciler/db_sync.py:15-43` — separate `_DOCUMENT_COLUMNS` (lockstep target #2).
- `core/corpus/reconciler/walker.py:60-82,88` — divergence source (`other_files`) + validation skip.
- `scripts/corpus_phase1_delta_ingest.py:88-120,217` — accession-additive delta logic + lock-file.
- `scripts/corpus_phase1_soak_check.py:34-76` — soak observable definition.
- `scripts/corpus_full_rebuild.py:14-37` — proves full rebuild does NOT re-fetch.
- `scripts/corpus_phase3_delta_transcripts.py:48` — FMP transcripts also additive-only.
- `workers/tasks/corpus.py:33,62` — Celery task bypasses `--lock-file`; reconciler drift = `rows_marked_orphan + divergences`.
- `app_platform/db/migration.py` — existing migration scaffold (Postgres; not corpus SQLite — see §7 Q7).
- `fmp/tools/transcripts.py:822` — FMP transcript provenance (`fmp_transcripts@version`).
- `tests/test_corpus_ingest_accession.py:81` — fixture only stubs section-level state (P1 prerequisite probe note).

**Planning siblings:**
- `docs/planning/CORPUS_WEAK_DOC_GATE_PLAN.md` — F50 / F64 source.
- `docs/planning/CORPUS_PHASE1_REPORT.md` — F51 soak gate definition.
- `docs/deployment/CORPUS_DEPLOYMENT_DESIGN.md` — F54 prod-refresh strategy (sibling).

## 10. Codex Review Brief — R5

**v4 (R4) findings folded in.** R4 returned FAIL-WITH-CHANGES with 1 P1 + 4 P2. R4 explicitly confirmed the UPSERT-+-status-flip bundle, `old_deleted`/`complete` two-transaction split, and sweeper logic. v5 addresses each remaining issue:

| R4 Finding | v5 Section | Status |
|---|---|---|
| `planned` recovery incomplete (orphan-file ambiguity) | §4.2 status table + recovery | `new_file_path` + `new_content_hash` captured at `planned` INSERT; recovery uniquely determined |
| `abandoned` ownership unclear | §4.2 recovery | Recovery script writes transition in same txn as new `planned` row; ingest never touches stale siblings |
| Post-filter performance constraint missing | §4.4 | Single query into Python `set`; linear pass; per-divergence SQL forbidden |
| Tokenizer LoC estimate too low (~130) | §7 Q4 | Updated to ~180–220 (production w/ dataclasses + good errors) |
| `producer_deployment_id` literal `'unknown'` mixes semantics | §7 Q8 | NULL when missing; warning via logger; optional separate flag column if needed |

**For R5, this should be the convergence check.** Please verify the v5 changes specifically:

1. **`planned` recovery uniqueness** — with `new_file_path` + `new_content_hash` captured upfront, is there ANY (status=planned, on-disk-state, hash-match) tuple that's still ambiguous?
2. **`abandoned` transition transaction** — recovery writes both `abandoned` (old row) + `planned` (new row) in one transaction. Verify this is sufficient and there's no SQLite gotcha (e.g., autocommit issue).
3. **Post-filter set-lookup pattern** — verify the `try/except sqlite3.OperationalError` correctly handles the missing-table case in fresh-corpus / pre-migration scenarios. Is there any other SQLite error that should be caught?
4. **NULL vs flag for `producer_deployment_missing`** — v5 defers the flag column until queries need it. Is that the right call, or should we add it now to avoid a future migration?
5. **Anything genuinely new in v5** (the diff from v4 is small — ~5 targeted edits). Scan the §4.2 status table and §4.2 recovery section for any new inconsistency.

If v5 is PASS, please say PASS explicitly. If FAIL-WITH-CHANGES, P1/P2 breakdown.

---

## 10b. Historical: Codex R4 Review Brief (resolved)

**v3 (R3) findings folded in.** R3 returned FAIL-WITH-CHANGES with 4 P1 + 7 P2. v4 addresses each:

| R3 Finding | v4 Section | Status |
|---|---|---|
| §4.2 status semantics inverted (BEFORE → AFTER) | §4.2 phases table | Status now means "last completed phase"; per-phase commit ordering explicit |
| `old_deleted` recovery missing | §4.2 recovery + §4.4 sweeper | Sweeper now selects `old_deleted` rows; advances them to `complete` |
| `abandoned` not in CHECK | §4.2 schema | Added to CHECK; defined as terminal state |
| Per-phase small transactions ambiguous | §4.2 | Explicit per-phase `with db:` blocks; UPSERT+status-flip bundled atomically |
| Walker `expected_during_reingest` shouldn't depend on DB | §4.4 | Tagging moved to `workers/tasks/corpus.py reconciler_daily`; missing-table handled |
| §7 Q4 prefer from-scratch tokenizer over sqlparse | §7 Q4 | Switched to ~50-line tokenizer + ~80-line parser; no dep |
| §4.4 SQL guard directionally correct | §4.4 | No change needed |
| `NULLABLE_INT_FIELDS` placement fine | §4.1 | No change needed |
| `producer_deployment_id` internal inconsistency | §4.1 + §7 Q8 | Nullable on consumer, required on producer (CI-enforced) |
| `_UPSERT_MUTABLE_COLUMNS` extension additive | §4.2 | Explicit list of all 9 new provenance columns |
| Producer claims still need maintainer verification | §9, §10 | Acknowledged |

**For R4 specifically, please verify:**

1. **State machine recovery completeness** — walk through process death at every commit boundary again with the new "status = last completed phase" semantics. Is every (status, on-disk, DB) tuple now uniquely recoverable?
2. **The atomic UPSERT-+-status-flip bundle** (§4.2). v4 says these MUST be in the same transaction. Verify this doesn't violate the "one phase = one small transaction" rule, and that there's no other phase pair that should also be bundled.
3. **`old_deleted` → `complete` separation.** Is having two separate transactions here actually necessary, or could they be one? Tradeoff: one = simpler; two = recovery has finer granularity. Plan picks two; is that the right call?
4. **Sweeper SQL with new `old_deleted` inclusion** (§4.4). Walk through: row is `old_deleted` (file already deleted by re-ingest worker, but `complete` flip never landed). Sweeper picks it up, `Path.exists()` returns False (file gone), step 1 says "skip to step 4" — does that mean skip to advancing `complete`? Make sure the prose matches the intended behavior.
5. **`abandoned` state transitions** (§4.2). Recovery says "if re-attempt creates fresh `planned` row, mark THIS row abandoned." Who writes that update — the recovery script, or the new ingest call? If the new ingest call: how does it know there's a stale row to abandon (search by `document_id`)?
6. **Reconciler post-filter performance** (§4.4). The post-filter reads `corpus_reingest_log WHERE status IN ('db_upserted', 'old_deleted_failed')` once per `reconciler_daily` run. With the active-state index, this is O(active_reingests). Confirm there's no per-divergence-row query (would be O(divergences × log_size)).
7. **From-scratch tokenizer LoC estimate** (§7 Q4). Is "~50 + ~80 = ~130 LoC" actually realistic for this grammar? Sketch the smallest viable implementation.
8. **`producer_deployment_id` literal `'unknown'`** (§7 Q8). Storing literal `'unknown'` mixes "we don't know" with "deployment named unknown." Should it be NULL instead, with a separate boolean column or warning side-channel for "Edgar_updater didn't send one"?
9. **Anything genuinely NEW** in v4. The diff from v3 is mostly tightening, but please scan §4.2 and §4.4 for new cracks.

If v4 is PASS, please say so explicitly. If FAIL-WITH-CHANGES, P1/P2 breakdown.

---

## 10b. Historical: Codex R3 Review Brief (resolved)

**v2 (R2) findings folded in.** R2 returned FAIL-WITH-CHANGES with 4 P1 + 6 P2. v3 addresses each:

| R2 Finding | v3 Section | Status |
|---|---|---|
| §4.2 atomic-transaction claim is false; needs state machine | §4.2 | Rewritten as 6-phase state machine; log entry written first |
| §4.4 sweeper too naive (race-prone) | §4.4 | DB-state guard + content_hash verify before delete |
| Race on rapid successive re-ingests | §4.4 | `documents.file_path != log.old_file_path` + no-active-entries check |
| Predicate parser safety understated | §7 Q4 | Tokenizer + parser + allow-list + parameterized SQL spec |
| Schema parity test shape wrong | §4.1 | Uses `PRAGMA table_info` + explicit DB-only/frontmatter-excluded sets |
| `NULLABLE_INT_FIELDS` slot-in confirmed; bool subclass note | §4.1 | Explicit `isinstance(value, bool)` rejection |
| Lock-file Celery wiring (no-lock was inertia not intent) | §4.2 prereqs | `_DEFAULT_LOCK_PATH` constant + env override + systemd-matching default |
| Migration runner ~100 lines confirmed fair | §7 Q7 | No change; estimate confirmed |
| `producer_deployment_id` source: env label not hostname | §4.1 | Three fields: `producer_deployment_id` (required label), optional `producer_instance_id`, optional `producer_build_id` |
| Edgar_updater claims still need maintainer verification | §9, §10 | Acknowledged; still pending |

**For R3 specifically, please verify:**

1. **State machine completeness** (§4.2). Walk through process death between EVERY phase boundary. Is there any combination where recovery cannot determine the right action from `(status, on-disk state, DB state)`? Edge case: process dies AFTER log INSERT (phase = `planned`) but BEFORE the new file is written — recovery script sees `planned` with no new file. Is "retry from scratch" safe, or is there a hidden constraint?
2. **Sweeper SQL guard correctness** (§4.4). The query joins `corpus_reingest_log` to `documents` and excludes rows with active siblings. Run mentally on this scenario: re-ingest A starts (entry 1, status=planned), completes (status=complete) with old=p1, new=p2; sweeper hasn't run; re-ingest A starts AGAIN immediately (entry 2, status=planned, old=p2, new=p3). Does sweeper correctly skip entry 1's p1 deletion until entry 2 reaches a safe state? (It should, because entry 2 is "active"; verify the SQL clause expresses this.)
3. **Walker `expected_during_reingest` tagging** (§4.4). The walker needs to read `corpus_reingest_log` to tag in-flight divergences as expected. Does this introduce a circular dependency or test-fixture problem? What if the log table doesn't exist yet (fresh corpus)?
4. **Predicate parser library choice** (§7 Q4). Plan suggests `sqlparse` for tokenization but our own allow-lists for safety. Is there a risk that `sqlparse` accepts something our allow-list misses? Better to write the tokenizer from scratch (~50 lines) and avoid the dep entirely?
5. **`NULLABLE_INT_FIELDS` validator placement** (§4.1). Confirm the snippet slots in at `frontmatter.py:294` without disrupting downstream validation logic (specifically the `document_id` / `source` cross-validation at line 298+).
6. **`producer_deployment_id` as a required field** (§4.1). Required vs. optional matters: if Edgar_updater forgets to populate, every `SectionsResponse` becomes invalid for the consumer. Recommend NULLABLE for v1 with a CI assertion on the producer side, OR required with a fallback default like `unknown`?
7. **`_UPSERT_MUTABLE_COLUMNS` extension** (§4.2). New parser_* columns must be added to `core/corpus/ingest.py:57` so re-ingest UPDATEs them. Verify this is just an additive list edit, not a deeper change to the UPSERT SQL.
8. **State machine phase commit pattern** (§4.2). Each phase is "write log status → do work → write log status." Are these wrapped in their own small transactions, or is the entire re-ingest one big transaction? If one-big, recovery is wrong because partial commits can't surface; if many-small, each phase needs its own `with db:`. Plan should specify.
9. **Anything else NEW in v3** that v2 lacked.

Return PASS / FAIL-WITH-CHANGES with P1/P2 breakdown.

---

## 10b. Historical: Codex R2 Review Brief (resolved)

**v1 (R1) findings folded in.** R1 returned FAIL-WITH-CHANGES with 8 P1 + 5 P2. v2 addresses each:

| R1 Finding | v2 Section | Status |
|---|---|---|
| schema.sql 28 cols not 25 | §2.2 | Corrected |
| Lockstep edits across 5 files (not 3) | §2.2, §3, §4.1 | Documented + parity test added |
| Re-ingest UPSERTs not "supersedes" | §4.2 | Rewritten as overwrite-with-cleanup |
| Soak claim partly wrong (divergence not hash) | §4.4 | Moved decoupling to divergence source |
| Lock-file bypassed by Celery | §4.2 prereqs, §6 | P0 wires it through Celery |
| P1 "no producer change" unverifiable | §5 P1 | Added prerequisite probe step |
| Missing fail-closed/fail-open policy | §4.2 | Fail-CLOSED specified |
| Missing DOS guards | §4.2, §6 | Per-entry + per-run + timeout + log rotation |
| No migration scaffold today (P2) | §3, §4.1, §7 | Open question elevated |
| Phasing flexibility (P2) | §5 intro | Noted |
| Transcripts staleness later (P2) | §8 | Note added |
| Cross-deployment skew (P2) | §4.1, §6, §7 | `producer_deployment_id` field added |
| Walker validation note (P2) | §2.2 | Added |

**For R2 specifically, please verify:**

1. **Re-ingest mechanism feasibility** — §4.2 describes overwrite-with-cleanup: write new file → DB UPSERT → delete old file → commit, all inside `with db:`. Does this ordering actually survive failures cleanly given that file ops aren't transactional with sqlite? What happens if process dies between step 5 (file write) and step 7 (audit log entry)? Is the sweeper script in §4.4 sufficient, or do we need a recovery state machine?
2. **Schema parity test design** — §4.1 calls for a test asserting `schema.sql`, `frontmatter.FIELD_ORDER`, `ingest._DOCUMENT_COLUMNS`, `reconciler/db_sync._DOCUMENT_COLUMNS` all agree. Is the right test surface "column names match exactly" or "intersection with expected set is empty + new entries flagged"? Can the test detect a column added to schema.sql but NOT to the tuples (most common drift)?
3. **`NULLABLE_INT_FIELDS` validator branch** — §4.1 calls for a NEW nullable-int validation path in `frontmatter._validate_field_types`. Walk through the existing `NULLABLE_STRING_FIELDS` validator and confirm the int variant slots in cleanly (or flag if it's a deeper refactor than expected).
4. **Predicate language safety** — §7 Q4 specifies an allow-list (`=`, `IN`, `IS NULL`, `IS NOT NULL`, `AND`, `OR`) over allow-listed columns. Is parsing this safely actually trivial, or am I underestimating? Sketch the rejection path for a malicious entry like `where: "1=1; DROP TABLE documents; --"`.
5. **P0 lock-file wiring** — §5 P0 says wire `--lock-file` through Celery. Is `_DEFAULT_LOCK_PATH` a reasonable constant to add, or does the existing systemd path live somewhere more sensible? Is there a reason the original Celery task was written without it (intentional?) — check git history of `workers/tasks/corpus.py:33`.
6. **Migration runner shape (§7 Q7 recommendation)** — is "build new ~100-line idempotent runner under `core/corpus/migrations/`" a fair estimate? What's the minimum viable shape — discover `*.sql` files in order, check `corpus_schema_version`, apply missing ones in a transaction?
7. **Cleanup-failure recovery** — §4.4 sweeper: does `corpus_reingest_log` have enough information to detect orphaned old files? (It records `old_file_path`; existence check is `Path.exists()`.) Is there a race where a fast successive re-ingest could mis-attribute an orphan to the wrong entry?
8. **`producer_deployment_id` source** — §4.1 adds the field but doesn't say how producer derives it. Should it be (a) hostname, (b) deployment env tag (`prod`/`dev`/`staging`), (c) ECS task ARN / k8s pod label? Recommendation?
9. **Verify Edgar_updater claims you couldn't access in R1** — the producer-side citations (`Edgar_updater/edgar_api/schemas.py:143-162`, `health.py:87,130,205`, `__init__.py:3`) are still in v2's §2.1 + §9. Mark them as still requiring maintainer verification (R1 noted you can't reach that repo from this sandbox).

Return PASS / FAIL-WITH-CHANGES with P1/P2 breakdown.
