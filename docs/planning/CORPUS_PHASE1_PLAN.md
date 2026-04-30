# Corpus Phase 1 — Scale to 50-100 Ticker Universe

## Status: v4 — addresses Codex R3 FAIL (1 P1 + 2 P2) on 2026-04-29

Scales V2.P1 corpus from Phase 0's 10-ticker canary to a 50-100 ticker production-grade universe with automated ingestion, delta detection, production reconciler. Per `CORPUS_ARCHITECTURE.md` §13 Phase 1 spec: "~50-100 tickers, one sector + adjacent: ingestion scheduler, delta detection, production reconciler."

**Scope-tightened from v1 per Codex R1 findings:**
- Filings-only (10-K + 10-Q) per architecture lock — transcripts deferred to Phase 3
- Latest-per-period only (no historical 8-K depth) — bridge limitation honored
- Reconciler explicitly detection-only — orphan purge filed as follow-up script
- External MCP dependencies (`notify-mcp`, `db_backup`) explicitly called out
- Universe math fixed; 52/53-week + ADR exclusions correctly applied

## Hard prerequisites (RESOLVED 2026-04-29 — verified live)

1. ✅ **`AI-excel-addin e1abb24`** (HIGH) — agent gateway dispatcher channel wiring. Verified: `mcp__portfolio-mcp__filings_search` returned `status: success` 2026-04-29.
2. ✅ **`Edgar_updater de7c533`** (P2) — nginx 502 mega-cap timeouts. Verified: JPM + BAC `/api/filings` cold-cache returned HTTP 200 2026-04-29.
3. ✅ **Source-excerpt v10 rescue fix** — risk_module commit `6a513150` concatenates text + tables[*] for Phase 4 v10 critical-key rescue.

Validation re-ingest of 4 mega-cap holdouts post-fixes: **4/4 succeeded** (was 0/4). Validation DB now at 50/50 = 100%.

## Goal

By Phase 1 completion:
- 50 (initial; expand to 100 later) tickers with **latest 5 years of 10-K + 10-Q** ingested into corpus
- Automated daily ingestion of new 10-K/10-Q filings with delta detection
- Production reconciler (detection-only) running on cron with daily drift report
- Coverage monitoring + alerting on ingest failures
- Operational runbook: add ticker, remove ticker, debug ingest failure, retry, full rebuild
- All 8 corpus MCP tools fully agent-callable end-to-end via gateway (already verified)

## Scope

### In scope

- **Universe selection** — 50 tickers (initial), with explicit criteria + extension path to 100
- **Bulk ingest** — latest 5 years per ticker, 10-K + 10-Q only (1 10-K/yr + 3 10-Q/yr × 5yr = 20 filings/ticker × 50 = ~1,000 docs)
- **Production corpus location** — promote from `/tmp/corpus_validation_25/` to permanent at `data/filings.db` + `data/filings/`; both gitignored
- **Ingestion scheduler** — daily cron via Celery beat (or new launchd plist; see open questions) to run delta ingest
- **Delta detection** — bridge already UPSERTs by `document_id = edgar:<accession>`; new accessions ingest, existing skip
- **Production reconciler** — daily cron walks CORPUS_ROOT ↔ documents table; **logs drift only** (does not delete; orphan purge is a separate script)
- **Coverage monitoring** — daily JSON report (custom script): per-ticker section count vs Phase 4 expected, latest filing date, ingest errors
- **Alerting** — via `mcp__alerts__notify_send` (external MCP server, NOT in this repo) for failure conditions
- **Operational runbook** — add/remove ticker, debug, retry, full rebuild

### Out of scope (parked or deferred)

- **Transcripts** — per `CORPUS_ARCHITECTURE.md` §13, full transcript ingest is Phase 3. Note: `fmp/tools/transcripts.py` already has corpus ingest path via `CORPUS_INGEST_ENABLED` env; mechanism exists but Phase 1 doesn't activate it.
- **8-K filings** — bridge takes (ticker, year, quarter) and selects ONE filing; can't reliably ingest the 5-50 8-Ks/quarter most filers produce without bridge enhancement. Defer to dedicated Phase 1.5 follow-up (`PLAN-corpus-8k-bulk-ingest.md`, TBD).
- **Historical 8-K** — same as above
- **Amendments (10-K/A, 10-Q/A)** — F43 territory, deferred
- **Vector embeddings / semantic search** — locked NO in `CORPUS_ARCHITECTURE.md` D2
- **KPI/fact surfacing in SearchHit** — Bucket C corpus extension
- **Markdown↔HTML offset map for source highlighting** — F44

## Universe selection

### Selection criteria (clean math)

Build from 21 confirmed-clean validation tickers (excl. AAPL — 52/53-week filer) + 3 mega-cap post-fix-verified tickers + 26 new = **50 total**.

| Source | Count | Tickers |
|---|---|---|
| Validation set, confirmed clean (excl. AAPL — 52/53-week filer) | 21 | MSFT, GOOG, META, NVDA, INTC, WFC, BK, EQH, MET, BRK-B, GE, HON, XOM, AES, TGT, MCD, JNJ, UNH, PLD, T, DUOT |
| Mega-cap (validation failures, fixed 2026-04-29) | 3 | JPM, BAC, MS |
| New adds (sector breadth + 13F importance) | 26 | (see sector table below) |
| **Total** | **50** | |

**AAPL note (Codex R2 [P2]):** Apple Inc. is a 52/53-week fiscal year filer (FY ends late September). Per Phase 1 Hard Exclusions, removed from Phase 1 universe. AAPL added back in a Phase 1.5 follow-up if/when fiscal-calendar handling helper lands. In the meantime AAPL filings remain accessible via the API (just not pre-ingested into corpus).

### New adds (26) — sector breadth, calendar-FY, US-domestic only

Apply Phase 1 hard exclusions (ADRs / FPI, 52/53-week fiscal year, recently-IPO/spun) to the 26 new tickers.

| Sector | Count | Examples (US-domestic, calendar-FY, no ADR) |
|---|---|---|
| Tech (mega) | 2 | ORCL, CRM |
| Tech (semis) | 2 | AMD, AVGO (TSM excluded — Taiwan ADR) |
| Banks | 2 | C, USB |
| Capital markets | 1 | GS |
| Insurance | 1 | PRU or ALL |
| Conglomerate / industrial | 3 | MMM, RTX, CAT |
| Energy | 2 | CVX, COP |
| Utility | 2 | NEE, DUK |
| Retail / Consumer | 3 | AMZN, HD, PEP (WMT/COST excluded — 52/53-week filers) |
| Healthcare / pharma | 3 | PFE, LLY, ABBV |
| REIT | 1 | AMT |
| Telecom | 1 | VZ |
| Custody | 1 | STT |
| Tech (software / data) | 1 | NOW |
| Tech (mega replacement for AAPL) | 1 | IBM (calendar-FY mega) |
| **Total** | **26** | |

(Specific tickers are illustrative — final list locked at implementation time, capped at 26 with same sector targets to keep total at 50 after AAPL exclusion.)

### Hard exclusions for Phase 1

- **ADRs / foreign private issuers** (TSM, BABA, etc.) — different filing patterns; Phase 2 weighted sample
- **52/53-week fiscal year filers** (WMT, COST, AAPL — all excluded from Phase 1 universe) — special fiscal-calendar handling needed; deferred to Phase 1.5
- **Recently IPO'd** (no historical depth, <5 years public)
- **Recently spun-off / merged-out tickers** — CIK ambiguity
- **Amendment-heavy filers** — F43 territory

### Extension to 100

Once Phase 1 stabilizes (no ingest failures for 14 days, all dashboards green), extend to 100 by:
1. Pulling another 50 from S&P 500 by 13F holder count + aggregate value
2. Re-running ingest cycle
3. Re-validating coverage gates

This is the natural Phase 1 → Phase 2 ramp.

## Ingestion strategy

### Bridge capability constraints (verified 2026-04-29)

Per `scripts/corpus_ingest_accession.py` source review:

| Bridge accepts | Picks | Limitation |
|---|---|---|
| `--year Y --quarter Q` (quarter ∈ 1..4) | Latest matching 10-K (q=4) or 10-Q (q≠4) | One filing per (ticker, year, quarter) |
| `--source 8k` + `--year Y --quarter Q` | Latest matching 8-K in that quarter | One 8-K per quarter — can't enumerate all |

**No accession arg, no form_type override, no "auto" source.** Plan honors these constraints; 8-K + amendments deferred to bridge-enhancement follow-up.

### Phase 1.A — Initial bulk ingest

**Goal:** latest 5 years of 10-K + 10-Q per ticker for 50 tickers.

**Per-ticker per-form scope:**
| Form | Frequency | 5-year count |
|---|---|---|
| 10-K | annual (q=4) | 5 |
| 10-Q | quarterly (q=1,2,3) | 15 |

**Per-ticker total:** 20 docs.
**Universe total:** 50 × 20 = **1,000 docs**.

**API cost (revised with retry budget):**
- 2 calls per filing (`/api/filings` + `/api/sections`) = 2,000 base calls
- + 20% retry overhead for cold-cache + transient errors = 2,400 effective calls
- + per-ticker discovery overhead (one `/api/filings` per (ticker, year) to find quarter accessions): 50 × 5 = 250 calls
- **Total: ~2,650 API calls**
- Cost estimate: $5-15 depending on tier; alert at $25 threshold

**Time budget (revised):**
- Per filing: 5-30s warm-cache; 30-90s cold-cache mega-caps
- Realistic mean: 15s/filing × 1,000 = 15,000s = ~4.2 hours sequential
- + 20% retry buffer = ~5 hours
- + manual checkpoint review between batches (e.g., per 10 tickers) = 6-7h elapsed wall time
- Run as 2 overnight batches (25 tickers each) for safety + checkpointing

**Sequencing:**
1. Run ingest in **per-ticker chunks** (1 ticker × all quarters × both forms at a time); checkpoint after each ticker.
2. Order tickers by **expected cold-cache cost** (small first, mega-caps last) to amortize warm-up overhead.
3. **Idempotent re-runs** — bridge UPSERTs by `document_id`; running same ticker twice is safe + skips already-ingested.
4. Per-ticker JSONL log mirroring `/tmp/corpus_validation_25/ingest.jsonl` format.

**Sub-script needed:** `scripts/corpus_phase1_bulk_ingest.py` — wraps bridge calls per the per-ticker chunked sequencing. ~50 LOC. Listed in implementation checklist.

### Phase 1.B — Ongoing delta ingest

**Goal:** detect + ingest new 10-K / 10-Q as they appear at SEC.

**Cadence:** daily cron at 06:00 UTC (post typical SEC EDGAR overnight publishing window).

**Algorithm per ticker per day:**
1. Determine current calendar quarter Y/Q + previous quarter (boundary handling).
2. For each (Y, Q) ∈ {current, previous}: call `/api/filings?ticker=X&year=Y&quarter=Q`.
3. **Filter returned filings to bridge-supported forms only:** keep `form ∈ {"10-K", "10-Q"}`. **Drop amendments** (`form` ending in `/A`) and 8-K — bridge can't target either, and amendments would otherwise show up as "new" every day forever (Codex R2 [P2]).
4. Compare filtered `(form, accession)` tuples against `documents` table for that ticker.
5. For each new (form, accession): invoke bridge with `--year Y --quarter Q` (form derived from quarter per bridge convention: q=4 → 10-K, else 10-Q).
6. Log results to JSONL daily ingest log.
7. Alert via `mcp__alerts__notify_send` on: bridge errors, parser failures.

**Daily volume estimate:**
- 50 tickers × ~6 new 10-K/10-Q docs/year = 300/year ÷ 250 trading days = ~1.2 docs/day average
- Spikes during 10-K season (Feb-Mar): 5-10 10-Ks/day for 1-2 weeks
- Cron runtime: <5 min on average days, <30 min on heavy days

**Sub-script needed:** `scripts/corpus_phase1_delta_ingest.py` — ~80 LOC. Listed in implementation checklist.

## Production deployment

### Corpus location

**Decision:** repo `data/filings/` (current default per `core/corpus/filings.py:43-44`); add `data/filings/` and `data/filings.db` to `.gitignore`.

`CORPUS_DB_PATH` and `CORPUS_ROOT` env vars already exist for override.

### DB sizing

- 1,000 docs × ~50KB markdown average + FTS5 ~30% overhead = ~80MB markdown + ~30MB DB
- Phase 2 extrapolation (10x): ~800MB markdown, ~300MB DB — well within SQLite operational range

### Backup strategy

**Note:** plan v1 referenced `db_backup` MCP tool. Per Codex R1 [P2], that's an external MCP (not in repo). For Phase 1, use repo-local SQLite `.backup` command or the existing finance-cli `db_backup` MCP if available externally.

**Cadence:**
- Daily DB snapshot: `data/filings.db` → `data/backups/filings_<date>.db`
- Markdown is source-of-truth (D14); DB is reconstructable
- Retention: 7 daily + 4 weekly + 12 monthly
- Restore drill: monthly — restore from backup + run reconciler

**Backup script needed:** `scripts/corpus_backup.py` — ~30 LOC. Listed in implementation checklist.

## Reconciler — honest scope

### What `core/corpus/reconciler/` actually does (verified 2026-04-29 + corrected per Codex R2)

Per Codex R2 [P2] correction (v2 over-corrected):

- `walker.py` walks CORPUS_ROOT for markdown files
- `db_sync.py::sync_documents()` — **inserts/updates `documents` rows for files on disk that are missing or stale in DB; LOGS orphan DB rows (file deleted, DB row remains) but does NOT delete them**
- `db_sync.py::sync_sections_fts()` — **rebuilds FTS rows for EVERY scanned file (not just changed ones) per Codex R3 verification; does NOT delete FTS rows for files that disappeared**

So reconciler is **asymmetric heal**:
- ✅ Heals direction A: file present on disk → DB ingests / refreshes (auto)
- ❌ Does NOT heal direction B: file deleted from disk → DB row + FTS row remain (orphan; logged only)

Direction-A behavior means a fresh corpus DB can be reconstructed from disk by running the reconciler. Direction-B requires manual purge via separate script.

### Phase 1 use of reconciler

**Cadence:** daily cron at 03:00 UTC (before delta ingest at 06:00 UTC)

**Outcome:**
- Logs + counts orphan DB/FTS rows (file deleted from disk)
- Auto-heals missing DB rows + stale FTS by re-ingesting from disk (direction A)
- Counts emitted to monitoring dashboard
- Alert if orphan-drift > 5 items per run (direction B issues — manual purge needed)

**Manual remediation** for actual cleanup:
- Orphan rows (direction B): separate `scripts/corpus_purge_orphans.py` script (TBD; needs FTS5 sections deletion + documents deletion). Run on-demand when drift report shows orphans.
- Missing rows (direction A): handled automatically by reconciler on next run.

Purge orphans reads orphan IDs from the Celery worker application log (where `logger.warning('orphan_document_row: ...')` lines are emitted by `core/corpus/reconciler/db_sync.py`), not from the per-run JSONL summary at `logs/corpus/reconciler_<date>.jsonl`.

**Future enhancement (post-Phase-1):** extend `reconciler/db_sync.py` to ALSO delete orphans (direction B). Filed as TODO entry. Not Phase-1-blocking since drift volume in normal operation is near-zero (filings rarely deleted from disk).

### Edge case: full rebuild

Required when:
- Schema bump to documents/sections_fts (no current bumps planned)
- Corpus markdown convention changes (locked per Phase 0)
- Disaster recovery from backup

**Procedure** (manual for Phase 1):
1. Stop ingest cron
2. Backup current DB
3. Drop tables → re-create per `schema.sql`
4. Walk CORPUS_ROOT and re-ingest from disk via `core/corpus/ingest.py::ingest_raw` (NEW helper script needed: `scripts/corpus_full_rebuild.py`, ~40 LOC)
5. Restart ingest cron

## Monitoring + alerting

### Per-day dashboard report

Daily JSON report at `data/corpus/health/<date>.json` (generated by `scripts/corpus_health_report.py`, NEW, ~80 LOC):
- Total docs by ticker × form
- Latest filing date per ticker (and days-since-last)
- Ingest errors today (count, sample)
- Reconciler drift this run (orphans, missing)
- API call count + estimated cost (from bridge JSONL)

### Alerts via `mcp__alerts__notify_send` (EXTERNAL MCP)

**Note:** `mcp__alerts__notify_send` is an external MCP server (Telegram bridge) registered in user's MCP config — not in this repo. Phase 1 uses it but acknowledges it as external dependency. Fallback: log-only if MCP not connected.

Alert classes:
- **CRITICAL:** any ticker with no ingestion attempt in 7 days
- **WARNING:** ingest error rate > 10% on a daily run
- **WARNING:** reconciler drift > 5 files per run
- **INFO:** new filing detected and ingested cleanly (optional, default off)

## Operational runbook

### Add a ticker to Phase 1 universe

1. Add ticker symbol to `data/corpus/universe.json` (NEW file — Phase 1 introduces this)
2. Run bulk ingest for that ticker only:
   ```bash
   python3 scripts/corpus_phase1_bulk_ingest.py --ticker XYZ --years 5
   ```
3. Verify via `python3 scripts/corpus_health_report.py --ticker XYZ`

### Remove a ticker — corrected per Codex R1 [P2]

Manual SQL `DELETE` doesn't sync FTS5 — would leave searchable orphans. Correct procedure:

1. Drop ticker from `data/corpus/universe.json`
2. Use `scripts/corpus_purge_ticker.py` (NEW, ~40 LOC) which:
   - Identifies all `document_id`s for that ticker via `documents` table
   - Deletes from `sections_fts` first (FTS5 needs explicit removal — NOT cascaded)
   - Deletes from `documents`
   - Removes corresponding markdown files from `CORPUS_ROOT/edgar/<ticker>/`
3. Run reconciler to verify no orphans remain

### Debug ingest failure

1. Read JSONL ingest log for the failing record
2. Reproduce manually with bridge command + capture stderr
3. Triage:
   - API error → check Edgar `/api/filings` health; retry with longer timeout
   - Parser issue → check upstream parser status; file Edgar_updater bug
   - Frontmatter validation → check input row; fix data and re-ingest

### Manual retry

```bash
# Single ticker, single period
python3 scripts/corpus_ingest_accession.py --ticker XYZ --year 2025 --quarter 3 --db data/filings.db --corpus-root data/filings

# All failures from a previous run (jsonl log)
python3 scripts/corpus_retry_failures.py --log /var/log/corpus/<date>.jsonl  # NEW script, ~40 LOC
```

### Full rebuild

```bash
# Backup first
python3 scripts/corpus_backup.py --pre-rebuild
# Drop + walk + re-ingest
python3 scripts/corpus_full_rebuild.py --db data/filings.db --corpus-root data/filings
```

## Phase 1 done criteria — under-tooled gates fixed

| Gate | Target | How measured (specific) |
|---|---|---|
| Universe ingested | ≥48 of 50 tickers (96%) with ≥1 10-K + ≥3 10-Q in last fiscal year | `scripts/corpus_health_report.py --gate-coverage` returns PASS |
| Coverage on ingested filings | ≥95% of 10-K with ≥8 sections; ≥85% of 10-Q with ≥6 sections | Same script — per-doc section count vs Phase 4 expected |
| Daily delta ingest | runs cleanly for 14 consecutive days, ≤2 errors per run avg | Cron + JSONL ingest log; `scripts/corpus_phase1_soak_check.py` (NEW) |
| Reconciler | runs cleanly for 14 consecutive days, ≤5 drift items per run | Cron + JSONL reconciler log; same soak-check script |
| Agent gateway corpus calls | end-to-end via `/api/gateway/chat` returns hits with citations | Manual test mirroring Track 4 Level 3 — single-shot prompt, expect non-empty hits |
| Monitoring dashboard | ≥7 days of daily JSON reports with content (not just file existence) | `scripts/corpus_phase1_soak_check.py` validates JSON shape + non-zero content |
| Operational runbook documented | this plan + per-script docstrings | Doc review |
| Ship report committed | `CORPUS_PHASE1_REPORT.md` (analog to Phase 0 + Track 4 reports) | git log |

8 gates (down from v1's 9 — transcripts gate dropped per architecture). All gates have a specific verification path.

## Risk register — added bridge limitations + scope discipline

| Risk | Likelihood | Mitigation |
|---|---|---|
| Bridge can't ingest historical 8-Ks at scale | high | Out of scope for Phase 1 per Codex R1 [P1]; defer to bridge-enhancement follow-up |
| Bridge can't target specific accessions | high | Phase 1 = latest-per-period only; document the limitation in operational runbook |
| Reconciler doesn't actually heal orphans | high | Phase 1 reconciler = detection-only; manual purge via separate script when needed |
| External MCP dependencies (notify-mcp, db_backup) not present | med | Make alerting + backup degrade gracefully (log-only, repo-local SQLite .backup) if MCP not connected |
| Bulk ingest takes longer than 5h estimate | med | Per-ticker checkpoint; restart-safe; 2 overnight batches with manual review between |
| API cost overrun | low | Track budget per run; alert at $25 threshold |
| New parser-failure-class ticker discovered | med | Per-ticker ingest log captures section counts; weekly review surfaces new issues |
| Disk space exhaustion (Phase 2 prep) | low | Phase 1 ~80MB markdown + ~30MB DB; well under 1GB |
| FMP transcript ingest accidentally activated | low | `CORPUS_INGEST_ENABLED` env defaults to off in Phase 1 deploy; verify before cron starts |
| Reconciler false-positive drift on race conditions | low | Skip files modified in last 60s (in-flight ingest); reconciler logs surface real drift |
| Cron jobs not running on hosting platform | med | Validate cron + log capture in deploy environment before Phase 1 ingest cycle starts |
| Schema bump from upstream parser breaks ingest | med | Reconciler + UPSERT semantics handle re-ingest gracefully; just costs API calls + time |
| Ticker selection includes 52/53-week filer accidentally | med | Build a screening helper (`scripts/corpus_universe_screen.py`, ~30 LOC) that fails the universe.json entry if ticker is on the exclusion list |

## Open questions for Codex (R1 fixes + new)

R1 questions resolved:

1. **Transcript ingest path:** RESOLVED — `fmp/tools/transcripts.py::get_earnings_transcript(output="file", section="all")` already does corpus ingest behind `CORPUS_INGEST_ENABLED`. No new script needed. Phase 1 explicitly does NOT activate this (transcripts deferred to Phase 3 per architecture).
2. **Universe location:** confirmed `data/corpus/universe.json` (new file).
3. **Cron infrastructure:** Codex R1 noted `workers/beat_schedule.py` uses interval schedules, no crontab. Two options:
   - (a) Add new Celery beat task with `crontab(hour=3)` / `crontab(hour=6)` — requires importing `crontab` from celery.schedules and adding entries to existing `BEAT_SCHEDULE` dict
   - (b) Use macOS `launchd` plist via `mcp__scheduler-mcp__schedule_create` — separate from Celery, simpler
   - **Lean: (a) Celery beat with crontab** — already in repo, integrates with existing job infra
4. **Backup retention:** confirmed 7+4+12; deferred hard storage numbers until Phase 1 measured
5. **Phase 1 → Phase 2 ramp timing:** confirmed 14-day soak before Phase 2
6. **8-K depth cap:** RESOLVED via scope reduction — 8-K out of scope for Phase 1; bridge enhancement deferred

New questions:

7. **AAPL fiscal-year handling:** RESOLVED in v3 — AAPL removed from Phase 1 universe per the 52/53-week filer exclusion. IBM substituted as calendar-FY tech mega replacement. AAPL added back in Phase 1.5 follow-up if/when fiscal-calendar handling helper lands.
8. **Universe screening test:** should universe.json have a CI gate that runs `corpus_universe_screen.py` on every change?
9. **Reconciler full enhancement** (orphan delete + missing auto-ingest) — file as Phase 1.5 plan now or wait until drift volume justifies?
10. **`corpus_purge_ticker.py` FTS5 deletion semantics** — verify FTS5 supports `DELETE FROM sections_fts WHERE document_id IN (...)` and that it correctly removes from the inverted index (not just the row).

## References

- `CORPUS_ARCHITECTURE.md` — V2.P1 architecture (R7 PASS) — §13 phasing locks transcripts to Phase 3
- `CORPUS_PRE_PHASE1_HARDENING_PLAN.md` v2 — pre-Phase-1 hardening milestone (complete)
- `CORPUS_PHASE1_VALIDATION_REPORT.md` v2 — Track 4 results + Level 3 finding
- `CORPUS_PHASE0_CHECKPOINT.md` — Phase 0 ship signal + canonical convention
- `Edgar_updater/docs/plans/PLAN-targeted-corpus-prewarm-strategy.md` v1 — universe selection signals (ex-ante importance proxies)
- `AI-excel-addin e1abb24` — RESOLVED 2026-04-29 (gateway dispatcher channel wiring)
- `Edgar_updater de7c533` — RESOLVED 2026-04-29 (nginx 502 mega-cap)
- ~~`Edgar_updater 0b2b213`~~ — RESOLVED as misdiagnosis; consumer-side fix at risk_module `6a513150`
- Track 3 implementation: `risk_module 5ba29000`
- Validation report v2: `risk_module 4f362e4c`
- Source-excerpt v10 rescue fix: `risk_module 6a513150`

---

## Implementation checklist (post-prerequisites — both prereqs DONE 2026-04-29)

1. **Lock final 50-ticker universe** in `data/corpus/universe.json` per Universe Selection criteria (21 validation carryover excl. AAPL + 3 mega-caps + 26 new = 50).
2. **Build sub-scripts** (estimated total ~400 LOC):
   - `scripts/corpus_phase1_bulk_ingest.py` — per-ticker chunked bulk wrapper
   - `scripts/corpus_phase1_delta_ingest.py` — daily delta detector
   - `scripts/corpus_health_report.py` — daily JSON dashboard report
   - `scripts/corpus_phase1_soak_check.py` — 14-day clean-cron verification
   - `scripts/corpus_purge_ticker.py` — manual ticker purge (FTS5-aware)
   - `scripts/corpus_purge_orphans.py` — manual orphan cleanup from reconciler logs
   - `scripts/corpus_full_rebuild.py` — disaster recovery / schema bump
   - `scripts/corpus_backup.py` — daily DB snapshot
   - `scripts/corpus_universe_screen.py` — exclusion-list checker
   - `scripts/corpus_retry_failures.py` — JSONL log → retry batch
3. **Build Celery task wrappers** at `workers/tasks/corpus.py` (NEW; ~40 LOC). Reconciler entry point is `core.corpus.reconciler.reconcile(corpus_root, db)` per Codex R3 [P1] verification — open the DB explicitly:
   ```python
   from celery import shared_task
   from pathlib import Path

   from core.corpus.db import open_corpus_db
   from core.corpus.reconciler import reconcile
   from scripts import corpus_phase1_delta_ingest, corpus_health_report

   _DEFAULT_DB = Path('data/filings.db')
   _DEFAULT_ROOT = Path('data/filings')

   @shared_task(name="corpus.delta_ingest_daily")
   def delta_ingest_daily(): ...   # wraps corpus_phase1_delta_ingest.main()

   @shared_task(name="corpus.reconciler_daily")
   def reconciler_daily():
       db = open_corpus_db(_DEFAULT_DB)
       try:
           return reconcile(_DEFAULT_ROOT, db)
       finally:
           db.close()

   @shared_task(name="corpus.health_report_daily")
   def health_report_daily(): ...  # wraps corpus_health_report.main()
   ```
   Add `'workers.tasks.corpus'` to `workers/celery_app.py`'s `include` list (currently only includes positions/orders/maintenance per Codex R2 [P1]).
4. **Wire daily reconciler cron** into `workers/beat_schedule.py` via Celery beat with `crontab(hour=3, minute=0)` targeting task name `"corpus.reconciler_daily"` — runs 03:00 UTC.
5. **Wire daily delta ingest cron** via `crontab(hour=6, minute=0)` targeting `"corpus.delta_ingest_daily"` — runs 06:00 UTC.
6. **Wire daily health report cron** via `crontab(hour=7, minute=0)` targeting `"corpus.health_report_daily"` — runs 07:00 UTC after delta ingest completes.
7. **Wire alerting** via `mcp__alerts__notify_send` for the 4 alert classes (or fallback to log-only if not configured).
8. **Run Phase 1.A bulk ingest** as 2 overnight batches (25 tickers each) with manual checkpoint review.
9. **Soak Phase 1.B daily cron for 14 days** — observe clean runs, surface any quality issues.
10. **Coverage verification + commit `CORPUS_PHASE1_REPORT.md`** when all 8 gates met.
11. **Update memory + TODO** to mark Phase 1 SHIPPED + queue Phase 2.

---

## v3 → v4 changelog (Codex R3 fixes)

- **[P1] Reconciler entry-point name** — verified actual export is `core.corpus.reconciler.reconcile(corpus_root, db)` (NOT `run_reconciler` or `reconciler.run()`). Updated celery task wrapper code shape to open the DB explicitly + call the right name.
- **[P2] Universe math** — fixed inconsistency: 21 + 3 + 26 = 50 throughout (was mixing "25 new" / "capped at 25" with table showing 26).
- **[P2] Reconciler FTS wording** — corrected: `sync_sections_fts()` rebuilds FTS for EVERY scanned file, not just changed ones (Codex R3 verified).

## v2 → v3 changelog (Codex R2 fixes)

- **[P1] Celery cron under-specified** — added explicit `workers/tasks/corpus.py` task module with 3 `@shared_task` wrappers (`corpus.delta_ingest_daily`, `corpus.reconciler_daily`, `corpus.health_report_daily`) + import in `workers/celery_app.py`. Beat entries target task names (not raw script paths).
- **[P2] Reconciler description over-corrected in v2** — corrected per Codex inspection: reconciler is **asymmetric heal** (heals direction A: file→DB auto-ingest; does NOT heal direction B: orphan-DB→file deletion). Updated description, outcome bullets, and remediation guide.
- **[P2] AAPL exclusion contradiction** — RESOLVED. AAPL removed from Phase 1 universe (52/53-week filer per Hard Exclusions). IBM substituted as calendar-FY tech mega. Open question #7 closed.
- **[P2] Delta ingest amendment loop** — added explicit filter step: drop `form` ending in `/A` (amendments) before comparing accessions; drop 8-K too. Bridge can't ingest either, so they'd otherwise show up as "new" every daily cron run forever.

## v1 → v2 changelog (Codex R1 fixes)

- **[P1] Bulk ingest scope** — dropped historical 8-K (25-50 per ticker × 50 = 1,250-2,500 docs unrealistic given bridge limitations). Phase 1 = 10-K + 10-Q only; 1,000 total docs. 8-K deferred to bridge-enhancement follow-up.
- **[P1] Delta ingest algorithm** — removed reference to non-existent `--source <auto>`; bridge derives form from quarter + accepts only `--source 8k`. Plan now describes the actual flow.
- **[P1] Reconciler scope** — explicitly described as detection-only. Manual orphan purge via separate script. Future auto-heal enhancement filed as follow-up.
- **[P1] External MCPs** — `notify-mcp` and `db_backup` explicitly called out as external (not in repo) with fallback to log-only / repo-local SQLite `.backup`.
- **[P1] Transcript ingest** — RESOLVED. `fmp/tools/transcripts.py` already has corpus ingest path via `CORPUS_INGEST_ENABLED`. Phase 1 doesn't activate it (transcripts = Phase 3 per architecture).
- **[P2] Architecture deviation** — transcripts removed from Phase 1 done-criteria. Phase 1 = filings-only per architecture lock.
- **[P2] Universe math** — fixed (22 + 3 + 25 = 50, no double-counting). TSM removed (Taiwan ADR), WMT/COST removed (52/53-week filers). 25 new sector adds re-listed with US-domestic + calendar-FY constraints.
- **[P2] Celery beat** — explicit reference to `crontab` import + crontab-style entries (not interval schedules).
- **[P2] Done criteria** — all 8 gates have specific verification paths (script names, exact metrics).
- **[P2] Backup strategy** — `db_backup` flagged as external MCP; repo-local fallback specified.
- **[P2] API cost/time estimates** — added retry budget (20%), discovery overhead, 2-batch sequencing for safety.
- **[P2] Runbook removal** — fixed to use FTS5-aware purge script; manual `DELETE FROM documents` flagged as broken (leaves searchable orphans).
- **New risks** — added 4 risks tied to the new findings (bridge limitations, external MCPs, scope discipline).
