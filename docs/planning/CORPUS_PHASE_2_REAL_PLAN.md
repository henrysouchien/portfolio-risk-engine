# Corpus Phase 2-Real — Full S&P 500 Expansion

**Status**: DRAFT — pending Codex review
**Author**: 2026-05-07
**Replaces what?** The architecture-spec Phase 2 (`CORPUS_ARCHITECTURE.md` §13.1417) that was renumbered/truncated as a "next-50 by 13F" run in `CORPUS_PHASE2_REPORT.md`. This plan executes the original spec's Phase 2 scope.

**Pre-condition**: F51 closed as superseded by freshness machinery (`completed/CORPUS_PHASE1_REPORT.md` §8). No soak-gate prerequisite on this expansion.

---

## 1. Goal

Expand the corpus from the current 100-ticker S&P 500 13F-ranked subset (Phase 1+2) plus 43-ticker operational manifest to the **full S&P 500 universe** (~503 tickers per current SPY constituents). Match Phase 1's 5-year history depth for each form type the filer uses.

**Success criteria**:
1. Every current S&P 500 constituent has at least one ingested filing OR is documented as upstream-blocked (single-letter ticker / delisted / unsupported) OR is documented as recent-IPO under the form-appropriate annual-count threshold.
2. Both domestic filers (10-K/10-Q) and foreign private issuers (20-F/6-K) covered. **8-K is out of scope** (deferred per §2.2).
3. `corpus_health_report --gate-coverage --phase 2-real` passes on the merged universe (semantics defined in §5.1).
4. Hank live-smoke against ≥3 newly-ingested tickers spanning at least 1 foreign filer returns real corpus content with citations.

**Non-success-blocking**: tickers excluded as recent-IPO under the form-appropriate annual-count threshold (`<5` 10-Ks for domestic, `<5` 20-Fs for foreign) — flagged in `upstream_blocked.json` with `reason: recent_ipo`, re-evaluated per current filing count on each universe-select run.

---

## 2. Scope

### 2.1 In scope
- Universe selection: take current SPY constituents (~503), subtract our existing 129-ticker covered set, ingest the remainder (~374 net new).
- Exclusion policy lifted (per architecture-spec re-evaluation):
  - **52/53-week fiscal year**: dropped entirely. Edgarparser handles the calendar correctly today (verified 2026-05-07 against AAPL/WMT/COST/TAP/KR — `period_end_source="expected_fiscal_calendar"` confirms upstream awareness).
  - **ADR/FPI**: dropped. Foreign filers ingested via explicit `--source 20f` and `--source 6k` passes (verified 2026-05-07 against TSM and DHT — 21 + 18 docs respectively, capex content cited live in Hank).
  - **Recent IPO/spun**: re-checked per current annual-filing count, **form-aware** (per §3.3) — `<5` 10-Ks for domestic-tagged tickers, `<5` 20-Fs for foreign-tagged tickers, classified by filing history first. The previous hardcoded list (ARM, KVUE, GEHC, VLTO, SOLV) was 2026-04-30; some may have crossed the threshold by now and will be re-evaluated live.
- Three ingest passes per ticker: domestic (10-K/10-Q default), `--source 20f`, `--source 6k`. Domestic pass auto-skips foreign filers (no 10-K filed); foreign passes auto-skip domestic filers (no 20-F filed). Wasted attempts cost a 400 from `/api/filings` per (ticker, year, quarter) tuple — ~10 wasted calls per misclassified ticker, acceptable.
- Cost-guard config: confirm V4 thresholds + Telegram alerting handle a ~$50-150 spike before kicking off.
- Verification: gate-coverage check on merged universe + Hank live smoke (3 tickers, mix of domestic/foreign).

### 2.2 Explicitly NOT in scope
- **Transcripts** for new tickers — Phase 3 already shipped against the 100-ticker universe; expanding transcripts to ~500 tickers is a separate Phase 3-real plan (similar shape, different data source). Defer.
- **8-K bulk ingest** — `Phase 1.5 8-K` was deferred per `CORPUS_PHASE1_PLAN.md`; still deferred. **Important**: `corpus_phase1_bulk_ingest.py:87` default form is `10-K` for Q4 and `10-Q` for Q1-Q3; **no 8-K is pulled in default mode**. 8-K bulk requires explicit `--source 8k`, which Phase 2-real does not pass. Full 5-50 8-Ks/quarter is a separate plan.
- **S&P 1500 + watchlists** (architecture-spec Phase 3) — keep deferred. This plan's success closes architecture-spec Phase 2 only.
- **Universe maintenance automation** — the SPY constituent list drifts as companies are added/removed. Keeping the corpus universe in sync is a separate ongoing-ops concern, not a one-time ingest task.

---

## 3. Universe selection

### 3.1 Source list
- **Primary**: `etf_holdings(symbol='SPY')` via FMP — same source as Phase 2 used. Returns ~503 current S&P 500 constituents.
- **Subtract**: union of current `data/corpus/universe.json` (Phase 1+2, 100 tickers) + `data/corpus/universe_operational.json` (43 tickers; 14 overlap with Phase 1+2 → 29 net new from operational that aren't in Phase 1+2).
- Already-covered set: 129 tickers (verified 2026-05-07 by intersection of the two manifest files).

### 3.2 Net-new candidate set
Estimated **~374 tickers** to ingest. Final number determined by the universe-select script's run.

### 3.3 Universe-select script — extension
Current `scripts/corpus_phase2_universe_select.py` takes the top 50 from S&P 500 by 13F-rank (after exclusions). Extend with two new orthogonal flags (Codex R1):
- `--mode {next-50, all-remaining}` (default: `next-50` for back-compat with Phase 2's invocation). `all-remaining` skips the `--limit` cap and skips the 13F ranking step.
- `--covered-universe PATH` (repeatable): paths to JSON manifests already-covered. The script unions all of them and subtracts from the candidate set. For Phase 2-real: `--covered-universe data/corpus/universe.json --covered-universe data/corpus/universe_operational.json`.

When `--mode all-remaining` is selected:
- Drops the `52/53-week fiscal year` and `ADR/FPI` exclusion filters per §2.1 (verified safe today).
- Drops the hardcoded `recent-IPO/spun` exclusion path (Codex R1 — `corpus_phase2_universe_select.py:496` excludes hardcoded names BEFORE the live count).
- **Recent-IPO check is form-aware** (Codex R2 finding 2): runs **AFTER** §3.4 filing-history classification. For tickers tagged `domestic`, exclude when live `10-K` count `<5`. For tickers tagged `foreign`, exclude when live `20-F` count `<5`. For `mixed/unknown` tag, exclude when neither `10-K` nor `20-F` reaches 5 (rare; survivorship of edge cases). Excluded tickers go into `data/corpus/upstream_blocked.json` with `reason: recent_ipo` (per §3.5).
- Keeps `CIK collision` filter (catches share-class duplicates).
- Keeps the per-ticker FMP profile fetch + cache.

### 3.4 Foreign-filer detection — filing-history first
**(Codex R1 finding 4.)** `profile.country` confuses domicile with SEC filer status; some non-US-domiciled S&P 500 names file `10-K`/`10-Q` (e.g., LIN). Using `profile.country` to gate pass selection would mean tagging real domestic filers as foreign and skipping their domestic pass entirely → zero coverage.

**Authoritative source: filing history.** For each candidate, probe `get_filings(ticker, year=2025, quarter=4)` then `(year=2024, quarter=4)` and look at the dominant form returned:
- `10-K` → tag `forms=["10-K","10-Q"]` (domestic pass only).
- `20-F` → tag `forms=["20-F","6-K"]` (foreign passes only).
- Mixed or no recent annual filing → tag `forms=["10-K","10-Q","20-F","6-K"]` (run all passes; misclassification cost is small per Codex's note).

**Profile as disagreement flag**: still fetch `profile.country` and `profile.isAdr` for every candidate. Log a per-ticker `_profile_disagreement` field when filing-history says "domestic" but profile says non-US (or vice versa). Doesn't affect routing — surfaces edge cases for follow-up.

### 3.5 Single-letter ticker pre-flight + upstream-blocked registry
**(Codex R1 finding — adopt separate registry.)** Before kicking off the bulk run, probe each single-letter ticker (and any other tickers historically flagged) against `/api/filings`. Any that return HTTP 400 "Invalid or unsupported ticker" (the F76 X-pattern) are recorded in:

- `data/corpus/upstream_blocked.json` (new file, persistent across runs):
  ```json
  {
    "version": 1, "last_probed": "2026-05-07",
    "blocked": [
      {"symbol": "X", "reason": "single-letter ticker rejected by /api/filings", "first_seen": "2026-05-07", "last_probed": "2026-05-07"},
      {"symbol": "RDFN", "reason": "delisted post Rocket Companies acquisition", ...},
      {"symbol": "SAVE", "reason": "delisted post Chapter 11", ...}
    ]
  }
  ```
- Also record the master `universe_phase_2_real.json` with a `status` field per entry (`eligible`, `upstream_blocked`, `recent_ipo`) so the manifest is self-describing.
- **`upstream_blocked` and `recent_ipo` entries are NOT included in the per-pass sub-manifests** (Codex R2 finding 4). Sub-manifests must contain only `status: eligible` entries. The bulk wrapper at `corpus_phase1_bulk_ingest.py:38` reads `symbol` only and would attempt ingest on any entry; gating must happen at sub-manifest emission time.

Re-runs after upstream fixes: just re-probe and remove from `upstream_blocked.json`; the next universe-select picks them up.

---

## 4. Ingest execution

### 4.1 Per-pass manifest split
**(Codex R1 finding 2 — bulk wrapper does not honor manifest `forms` field.)** `scripts/corpus_phase1_bulk_ingest.py:38` only loads `symbol` from each manifest entry; it does not respect a `forms` array, an `upstream_blocked` flag, or any other per-ticker routing. Two paths to fix this:
- **(a)** Patch the bulk wrapper to filter by `entry.forms` and skip `upstream_blocked=true` entries.
- **(b)** Generate three separate single-purpose manifests at universe-select time:
  - `data/corpus/universe_phase_2_real_domestic.json` (only entries tagged `forms ⊇ {"10-K","10-Q"}`)
  - `data/corpus/universe_phase_2_real_20f.json`
  - `data/corpus/universe_phase_2_real_6k.json`

**Pick (b)** — smaller code change (universe-select emits 3 files; bulk wrapper untouched), each pass invocation is auditable, restartable, and obvious.

**Drift assertion (Codex R2 finding 4 — corrected)**: `union(domestic, foreign_20f, foreign_6k) == {entry.symbol for entry in master if entry.status == "eligible"}`. The blocked + recent-IPO entries are intentionally excluded from sub-manifests but stamped in the master with `status` for traceability. If the assertion fails, fail-loud and halt before any pass runs.

### 4.2 Sequencing
1. **Domestic pass**: `python3 scripts/corpus_phase1_bulk_ingest.py --universe data/corpus/universe_phase_2_real_domestic.json --years 5 --start-year 2025 --log logs/corpus/phase_2_real_domestic_<date>.jsonl`
2. **Foreign 20-F pass**: `--universe data/corpus/universe_phase_2_real_20f.json --source 20f --years 5 --start-year 2025`
3. **Foreign 6-K pass**: `--universe data/corpus/universe_phase_2_real_6k.json --source 6k --years 5 --start-year 2025`

Each pass restartable; each writes its own JSONL log. Failure of one pass doesn't block the others.

**Note on default form behavior** (Codex R1 finding 5): `bulk_ingest:87` default form is `10-K` for Q4 and `10-Q` for Q1-Q3. There is **no 8-K pulled in default mode**; 8-K bulk requires explicit `--source 8k`. Phase 2-real does not pass `--source 8k`; 8-K bulk stays deferred per §2.2.

**Note on `--start-year`** (Codex R1 missing-gates note): explicitly pin `--start-year 2025` rather than relying on the default `date.today().year`. Reason: re-runs from a different calendar year would shift the 5-year window and re-ingest different periods; pinning makes the run reproducible. Re-evaluate the pin yearly.

### 4.3 Pre-run gates (must hold)
1. **Disk capacity**: current footprint 1.8 GB (985 MB DB + 809 MB markdown) at 3,823 docs. Phase 2-real estimated +6,300 docs → +3 GB → total ~5 GB. Local 366 GB free; prod EBS volume needs verification (`/mnt/hank-data/risk_module/`). **Action: ssh prod check before kickoff.**
2. **Cost / quota oversight** (Codex R1 finding 3 — corrected): the V4 budget guard wraps **FMP** calls only (`fmp/client.py:212`); the corpus ingest path goes through `httpx.get` directly in `core/corpus/edgar_api_client.py:56` and is **NOT covered**. Flipping V4 live is neither necessary nor sufficient for this run. **Decision**: accept manual oversight + Edgarparser's internal rate-limits as the cap for Phase 2-real. Wrapping `edgar_api_client` with a budget provider is filed as a separate follow-up (NOT a Phase 2-real prereq).
3. **Gateway running fresh**: per `feedback_long_running_processes_stale_module_state.md`, restart gateway before the verification phase to ensure live smoke runs against current code.
4. **WAL-safe DB snapshot before pass 1 only** (Codex R1 finding 6 + R2 finding 6 — single snapshot, justification in §6.2): `data/filings.db` is opened with `PRAGMA journal_mode=WAL` (`core/corpus/db.py:23`); `cp` alone misses the WAL contents. Use SQLite's online backup:
   ```bash
   sqlite3 data/filings.db ".backup data/filings.db.pre_phase2_real_<date>"
   ```
   Run with bulk ingest paused (or before pass 1 starts) so writers aren't appending mid-backup. SQLite's `.backup` is WAL-aware; safe. Passes 2 and 3 do not get separate snapshots — see §6.2 for the rationale (idempotent re-run model + per-pass log isolation).

### 4.4 Post-ingest merge
**(Codex R2 finding 1 — operational entries that are in SPY must be folded into the master.)** Final merged `universe.json` covers the architecture-spec Phase 2 scope: every current SPY constituent we've ever ingested, regardless of which manifest run brought it in.

Inputs to merge:
1. Current `data/corpus/universe.json` (Phase 1+2, 100 tickers).
2. **Operational entries that are also in current SPY** (e.g., AAPL, FOUR, NET, ALL, PCTY) — fold into the merged master with `forms` tags backfilled from filing history.
3. New Phase 2-real master entries (`status: eligible` only).

Operational entries that are NOT in current SPY (e.g., RDFN, SAVE, BBSI, BROS, LDI, LMND, etc.) **stay in `universe_operational.json` separately** — they're VAL-benchmark / Hank-probe additions, not S&P 500 members. The two manifests are unioned at query time wherever needed; the merged `universe.json` is the canonical "S&P 500 corpus universe."

Output: `data/corpus/universe.json` with `version: 4, phase: '1+2+2_real'` and per-entry `forms` + `status` fields.

**Backfill `forms` for legacy entries (Codex R2 finding 3 prereq)**: legacy `universe.json` entries pre-date the `forms` tag. Before running the gate, derive `forms` for each legacy entry from filing history (same probe as §3.4) and write back. Do this once at merge time; subsequent runs preserve.

---

## 5. Verification

### 5.1 Coverage gate — Phase 2-real-shaped
**(Codex R1 finding 1 — existing gate is Phase 1/2-shaped and inappropriate for Phase 2-real.)** `corpus_health_report.gate_passes()` (`scripts/corpus_health_report.py:140`) currently:
- Hardcodes `tickers_meeting_minimum >= 48` (intent: 48-of-50 Phase 1 floor).
- Only checks `coverage['10-K']` and `coverage['10-Q']` ratios.
- Requires `transcripts_coverage.ratio >= 0.90`.

For a 500-ticker filings-only Phase 2-real, this gate would either fail-on-transcripts (we're not running Phase 3-real here) or pass a meaningless filings threshold. **Extend the gate** with a new `--phase` flag:

```
python3 scripts/corpus_health_report.py --gate-coverage --phase 2-real
```

Phase 2-real gate semantics:
- `tickers_meeting_minimum` floor scales with universe size — e.g., `>= 0.95 * (universe_size - upstream_blocked_count - recent_ipo_count)`.
- Per-form coverage thresholds:
  - `10-K` ≥ 0.95 across **domestic-tagged** tickers only.
  - `10-Q` ≥ 0.85 across **domestic-tagged** tickers only.
  - `20-F` ≥ 0.90 across **foreign-tagged** tickers only.
  - `6-K` is informational; not a gate (filing volume varies wildly per filer).
- **Drops the transcripts gate**. Phase 3-real (transcript expansion) will reintroduce when that plan ships.
- Excludes tickers with `status: upstream_blocked` or `status: recent_ipo` in the manifest from the denominator.

**Cohorts come from manifest, not from `documents.form_type` (Codex R2 finding 3).** Survivorship bias: a ticker that failed all ingest attempts has zero `documents` rows, so a DB-only cohort would silently exclude it from the denominator and inflate the ratio. Cohorts must read from the manifest's `forms` field; `documents.form_type` rows are numerator evidence only.

Concretely: for each `(ticker, status, forms)` in the manifest:
- If `status != "eligible"`: skip from cohorts entirely.
- If `forms ⊇ {"10-K","10-Q"}`: count toward domestic cohort denominator. Numerator = 1 if `documents` has a row for that ticker × that form within the target year window.
- If `forms ⊇ {"20-F"}`: count toward foreign cohort denominator. Same numerator pattern.

Implementation: small extension to `corpus_health_report.py`. Reads the merged `universe.json` (per §4.4 with `forms` + `status` fields backfilled). Codex implements alongside the universe-select extension.

### 5.2 Hank live smokes
Three smokes against newly-ingested tickers (post-gateway-restart):
- One large-cap S&P 500 not previously covered (e.g., HD, JPM-C-class, or whatever first lands in the new universe).
- One mid-cap less-traded name to confirm tail coverage.
- One foreign filer (BABA, NVO, ASML, SAP, TM, or SNY) to confirm the 20-F/6-K path works for newly-added ADRs.

Each smoke confirms `filings_list(ticker)` and `filings_search(query, universe=[ticker])` return non-zero hits, and Hank cites real content.

### 5.3 Continuous monitor unaffected
Existing daily `corpus_health_report.py` cron continues unchanged. Phase 2-real adds no new gate; the merged universe is just bigger.

---

## 6. Rollback / recovery

### 6.1 Rollback signals
- Bulk pass returns rc=1 with >50% of attempts failing on infrastructure errors (HTTP 5xx from edgarparser, not future-filing misses).
- Disk fills before pass completes (early-exit, not corruption).
- Gate-coverage drops below pre-run baseline (Phase 1+2's 98%).

### 6.2 Recovery
The bulk ingest is **idempotent at the (ticker, year, quarter) grain**. Re-runs upsert based on `(ticker, accession)`; partial coverage from a failed run becomes the baseline for the retry pass.

Pre-run safety: **one WAL-safe corpus DB snapshot before pass 1** (Codex R2 finding 6 — single snapshot, not per-pass):
```bash
sqlite3 data/filings.db ".backup data/filings.db.pre_phase2_real_<date>"
```
**Not** plain `cp` — the DB runs in WAL mode (`core/corpus/db.py:23`); `cp` would miss uncheckpointed WAL contents. SQLite's online backup is WAL-aware and safe with concurrent readers; pause writers (no bulk-ingest running) for a fully-consistent snapshot.

**Why one snapshot, not per-pass**: passes 2 and 3 (foreign 20-F + 6-K) only insert new (ticker, accession) rows; they don't mutate domestic-pass data. If a foreign pass produces bad data, the recovery is a targeted re-run on the affected tickers, not a full DB restore. The pre-pass-1 snapshot is the rollback point for catastrophic regressions; intermediate states are recoverable via the idempotent re-run model. (Decision recorded vs. Codex R2 finding 6's snapshot-before-each-pass alternative — chose simpler over more conservative because the bulk ingest is `INSERT OR REPLACE` keyed on `(ticker, accession)`, not destructive.)

Also note: rc=1 from `corpus_phase1_bulk_ingest.py` returns at `:117` for **any** miss — including future-filing not-yet-filed cases that aren't real failures. **Filed as missing-gate**: a small log-classifier helper that reads a JSONL log and bucketizes failures by reason (`future_filing`, `upstream_blocked`, `infrastructure_error`, `parser_error`) so the rollback-signal threshold is computable. Implement alongside the bulk run, not before.

---

## 7. Implementation order

1. **Codex plan review R2** of this doc — iterate to PASS.
2. **Codex implementation** of three small code changes (single Codex MCP call with workspace-write):
   - Extend `corpus_phase2_universe_select.py` with `--mode {next-50,all-remaining}` and repeatable `--covered-universe PATH` (§3.3). Replace hardcoded recent-IPO exclusion list with a **form-aware live count check** — classify via filing history first (§3.4), then exclude when `<5` 10-Ks (domestic), `<5` 20-Fs (foreign), or neither reaches 5 (mixed/unknown). Emit three sub-manifests + the master manifest + stamp `upstream_blocked` and `recent_ipo` statuses (§4.1, §3.5).
   - Extend `corpus_health_report.py` with `--phase 2-real` gate semantics (§5.1).
   - Add `scripts/corpus_phase2_real_log_classifier.py` — small helper to bucketize ingest log failures by reason (§6.2 note).
3. Run universe-select: `python3 scripts/corpus_phase2_universe_select.py --mode all-remaining --covered-universe data/corpus/universe.json --covered-universe data/corpus/universe_operational.json` → emits master + 3 sub-manifests + updates `upstream_blocked.json`.
4. **Pre-flight gates**:
   - Disk check: prod EBS volume free space (§4.3.1).
   - Manual quota oversight noted (§4.3.2 — V4 doesn't apply, accept manual cap).
   - Gateway restart timing decision (§4.3.3 — restart AFTER ingest completes, BEFORE smokes).
   - WAL-safe DB snapshot before pass 1 (§4.3.4).
5. **Domestic pass** (§4.2.1). Watch the live JSONL log for systemic errors.
6. **Foreign 20-F pass** (§4.2.2).
7. **Foreign 6-K pass** (§4.2.3).
8. Run `corpus_phase2_real_log_classifier.py` on each pass log; if `infrastructure_error` count > 5% of attempts, halt and investigate.
9. Merge sub-manifests into master `universe.json`; stamp `version: 4, phase: '1+2+2_real'`.
10. **Restart gateway** to load any code that landed during ingest (per memory: long-running processes hold stale module state).
11. Run Phase 2-real coverage gate (§5.1).
12. Run 3 Hank live smokes (§5.2).
13. Update TODO.md (close Phase 2-real, advance V2.P1) + create `CORPUS_PHASE_2_REAL_REPORT.md`.

---

## 8. Open questions — RESOLVED in R1 review

All R1 plan-review questions have answers from Codex. Recording the answers here for traceability:

1. ✅ **Universe-select interface** (§3.3): keep the script, add modes (`next-50` default + `all-remaining`) plus repeatable `--covered-universe`. Don't replace.
2. ✅ **Foreign-filer detection** (§3.4): filing history first; profile as disagreement flag.
3. ✅ **Single-letter ticker registry** (§3.5): separate `data/corpus/upstream_blocked.json` + manifest stamp.
4. ✅ **Cost-guard prerequisite** (§4.3.2): V4 doesn't cover Edgarparser; manual oversight is the cap; live-flip not required.
5. ✅ **Universe drift maintenance**: punt to manual re-run when noticed; not on critical path.
6. ✅ **8-K bulk**: deferred (was already; correction: Phase 2-real does NOT pull 8-Ks at all in default mode — earlier draft's claim was wrong).
7. ✅ **Recent-IPO threshold**: form-aware live re-fetch — classify via filing history first (§3.4), then exclude when `<5` 10-Ks (domestic), `<5` 20-Fs (foreign), or neither reaches 5 (mixed/unknown). Remove the hardcoded exclusion list in `all-remaining` mode.
8. ✅ **Missing gates**: form-aware coverage gate (§5.1), per-pass manifest split (§4.1), Edgarparser quota-oversight clarification (§4.3.2), WAL-safe snapshot (§4.3.4 + §6.2), explicit `--start-year` (§4.2 note), log classifier (§6.2 note).

---

## 9. Effort + cost rollup

- Universe-select extension: S (couple hours, one Codex implement round)
- Domestic ingest: ~30 min wall clock, ~$30-90 cost
- Foreign 20-F ingest: ~5 min, <$5
- Foreign 6-K ingest: ~10 min, ~$5-15
- Verification: ~10 min (gate + smokes)
- **Total: ~1 hour wall clock + ~$40-110 spend**, well within the architecture's $250 estimate.
