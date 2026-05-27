> **✅ DONE — Phase 3.1 shipped. Moved during 2026-05-26 docs cleanup.**

# V2.P1 Corpus — Phase 3 Ship Report

**Snapshot:** 2026-05-01
**Branch:** `main`
**Phase 1+2 reference:** `CORPUS_PHASE1_REPORT.md` / `CORPUS_PHASE2_REPORT.md`
**Implementation:** `e5c416b9` (5 deliverables) + `541768a3` (V2.P1 row update for Phase 3)
**Backfill:** 2,000-attempt run completed in ~15 min, 1,689 transcripts ingested

---

## TL;DR

Phase 3 adds **FMP earnings transcripts** to the existing 100-ticker corpus. Same universe as Phase 1+2 (no expansion). 5-year history depth matching filings. 1,689 transcripts ingested across 99/100 tickers (only BRK-B excluded — FMP doesn't cover Berkshire annual meetings). 1 real error / 2,000 attempts. New transcripts coverage gate (97% — exceeds 90% threshold) PASSES alongside the existing filings gates. Live-validated end-to-end through Hank: cross-source synthesis (filings + transcripts in one query) works, surfacing transcript-only metrics (e.g., MSFT's 20M Copilot seats / +250% YoY / Accenture 740K) that were absent from filings.

---

## 1. What shipped

### 1.1 Phase 3 implementation (`e5c416b9`)

5 net file changes:

| File | What |
|---|---|
| `scripts/corpus_phase3_bulk_ingest_transcripts.py` (NEW, ~150 LOC) | Bulk ingest script with load-bearing `output="file"` + `section="all"` args + `CORPUS_INGEST_ENABLED` env contract |
| `scripts/corpus_phase3_delta_transcripts.py` (NEW, ~98 LOC) | Daily delta detector for new transcripts |
| `workers/tasks/corpus.py` | New `transcripts_delta_daily` Celery task wrapping the delta script |
| `workers/beat_schedule.py` | New 05:00 UTC beat entry (slots between reconciler 03:00 and filings delta 06:00) |
| `scripts/corpus_health_report.py` | Extended with `transcripts_coverage` block + per-ticker `transcripts` count; `--gate-coverage` requires both filings AND transcripts gates |
| `tests/test_corpus_phase3_transcripts.py` (NEW, 4 tests) | Bulk script arg parsing + delta `quarters_to_check` helper |

Codex R2 PASS after R1 caught two real issues:
- **R1.P1** — `get_earnings_transcript()` only routes to corpus ingest when called with **both** `output="file"` AND `section="all"`. Default is `output="inline"` which skips the ingest branch entirely. Plan would have shipped a script that ran 2,000 API calls and ingested zero transcripts. The bulk script now enforces both args explicitly with a docstring note.
- **R1.P2** — Stale cron schedule reference. Plan said reconciler at 03:00 / delta at 06:00 / health at 07:00 was inverted (actual is correct in the schedule file). Confirmed against `workers/beat_schedule.py`.

Bonus: API-key redaction added in FMP exception messages before JSONL logging — prevents accidental leak in error paths.

### 1.2 Backfill execution

Ran via:
```bash
set -a && source .env && set +a
nohup env CORPUS_INGEST_ENABLED=true CORPUS_ROOT=data/filings CORPUS_DB_PATH=data/filings.db \
  FMP_API_KEY="$FMP_API_KEY" \
  python3 scripts/corpus_phase3_bulk_ingest_transcripts.py --years 5 \
  --log data/corpus/logs/phase3_bulk_2026-05-01-082623.jsonl &
```

Wall clock: ~15 min for 2,000 attempts (much faster than estimated — heavy FMP cache hits across the universe).

---

## 2. Backfill results

### 2.1 Aggregate

| Metric | Value |
|---|---|
| Attempts | 2,000 (100 tickers × 5 years × 4 quarters) |
| OK | **1,689** (84%) |
| `expected_no_transcript` | 310 (15%) — older periods + missing FMP coverage |
| Real errors | **1** (0.05%) |
| Tickers with ≥1 transcript | **99/100** |
| Tickers with 0 transcripts | 1 (BRK-B — FMP doesn't cover Berkshire annual meetings) |

### 2.2 Final corpus state

```
data/filings.db
├── documents:  ~3,354 total
│   ├── filings:     1,665  (10-K + 10-Q from Phases 1+2)
│   └── transcripts: 1,689  (fmp_transcripts source from Phase 3)
└── sections_fts:  > 11,439 sections (filings) + transcript section rows
```

### 2.3 Gate-coverage on the merged 100-ticker universe

```
10-K:        399/399  = 100.0%   (≥95% gate) ✅
10-Q:       1124/1266 =  88.8%   (≥85% gate) ✅
transcripts:  97/100  =  97.0%   (≥90% gate) ✅
gate_coverage: True
```

All three gates PASS for the first time on the multi-source corpus.

---

## 3. Live validation

Two end-to-end tests through Hank dev chat CLI:

### 3.1 Cross-source MSFT Copilot (single-ticker, written-vs-spoken)

> "What did MSFT say about Copilot in their most recent 10-Q AND their most recent earnings call transcript?"

Hank pulled both surfaces and quantified the disclosure gap:
- 10-Q: Copilot mentioned only twice in passing as an "ARPU driver" — no seat counts, no usage metrics, no customer names
- Q3 2026 transcript (ingested 25 min before the test): **20M paid seats, +250% YoY, Accenture 740K seats, Bayer/J&J/Mercedes/Roche 90K+ each, queries +20% QoQ at Outlook engagement levels**

Hank's analyst observation:
> "10-Q gives the bare disclosure required for materiality; the call is where management quantifies the narrative. Treat the call's specifics as management commentary, not audited disclosure."

Cost: $1.26 / 79s.

### 3.2 4-way hyperscaler capex aggregation (multi-ticker, transcript-heavy)

> "Calculate total 2026 AI infrastructure capex spend across MSFT, AMZN, GOOG, META."

Hank delivered: **~$710B at midpoint, $695–725B range** with verbatim quotes from Amy Hood (MSFT), Andy Jassy (AMZN), Anat Ashkenazi (GOOG), Susan Li (META). Confirmed dollar guidance is absent from each 10-Q via explicit `filings_search` checks.

Notable analyst behaviors that emerged:
1. **Discovered AMZN didn't restate the number on 4/29/26** — only had Q1 actual ($43.2B). Hank went BACK to the Q4 2025 call (2/5/26) and pulled Andy Jassy's $200B annual guide. The prompt didn't ask for this investigation.
2. **Definitional caveats**: distinguished "total CapEx vs strict AI infra," flagged MSFT's $25B component-price inflation distortion, noted META's range INCLUDES finance lease principal payments while others use gross PP&E ("apples-to-apples is rough at this level").
3. **Triangulation with prior NVDA test** — the $710B sum is consistent with NVDA's "top-5 hyperscaler 2026 capex ≈ $700B" aggregator from an earlier query. Same number, two independent sources.

Cost: $1.78 / 122s for a definitive 4-way capex aggregation.

---

## 4. What's not in scope (deferred)

**Phase 3.1 — Transcripts cron soak verifier.** SHIPPED 2026-05-01 (commit `0f2c06cd`). `corpus_phase1_soak_check.py` extended with a 4th gate for transcripts delta cron continuity (every day must have ≥1 row in `logs/corpus/transcripts_delta_<date>.jsonl`, average errors ≤ `--max-average-transcripts-errors` default 2.0). Bonus catch from R1 review: Phase 3 bulk script's `DEFAULT_LOG_DIR` was deviating from Phase 1 convention (`data/corpus/logs` vs `logs/corpus`) — would have silently blocked the soak gate. Fixed alongside. 5 new on-disk tests cover all 4 gates independently.

**Universe expansion.** Phase 3 deliberately stayed on the existing 100-ticker universe. The +1,400 ticker ramp (S&P 500 + S&P 1500) becomes Phase 4 when product needs justify.

**Quartr decks integration.** Architecture Phase 4 — adds a new `source` family without schema changes. Deferred per plan.

---

## 5. What changed vs original plan

### 5.1 Scope held

Plan: add transcripts to the existing 100-ticker universe, 5-year history depth, separate delta cron, extend health report. Implementation matches.

### 5.2 R1 found 1 P1 + 1 P2 (real bugs avoided)

- **The load-bearing `output="file"` + `section="all"` contract** — without Codex flagging this, the bulk script would have run silently with zero ingests. Critical catch.
- **Cron schedule reference correction** — minor but kept the plan accurate.

### 5.3 Discovered during execution

- **Backfill ran ~6× faster than estimated** (15 min vs predicted 1-2 hours). FMP cache hits were heavy across the universe — many transcripts were already cached server-side from prior queries.
- **Only 1 real error / 2,000 attempts** — far cleaner than Phase 2's 111 errors. FMP transcripts API is more stable than edgar_api for this workload.

---

## 6. Phase 4 entry posture

Phase 4 (full S&P 500 + S&P 1500 universe expansion to ~1,500 tickers) is the natural next deliverable per `CORPUS_ARCHITECTURE.md` §13.5.

The mechanism is in place:
- Re-run `scripts/corpus_phase2_universe_select.py --limit 450` to pull the next ramp from S&P 500
- Re-use `corpus_phase1_bulk_ingest.py` for filings ingest
- Re-use `corpus_phase3_bulk_ingest_transcripts.py` for transcripts ingest
- No architectural changes needed

Cost estimate per architecture: ~$250 for filings + ~$300 for transcripts = ~$550 incremental. Lower priority unless a product need justifies the universe size jump.

---

## 7. Sign-off

- ✅ Phase 3 implementation shipped (5 deliverables, Codex R2 PASS)
- ✅ Phase 3 backfill complete (1,689 transcripts ingested, 99/100 tickers, 1 real error / 2,000 attempts)
- ✅ Transcripts coverage gate added (97% — exceeds 90% threshold)
- ✅ Gate-coverage PASS on all three gates (10-K + 10-Q + transcripts)
- ✅ Live-validated cross-source synthesis through Hank (single-ticker MSFT Copilot + 4-way hyperscaler capex aggregation)
- 🟡 Phase 1 14-day soak still in progress (Phase 1 OPERATIONAL SHIPPED gate, due ~2026-05-14)
- ✅ Phase 3.1 SHIPPED (commit `0f2c06cd`): `corpus_phase1_soak_check.py` extended with 4th gate for transcripts delta cron + log-path alignment fix

Phase 3 ingest is shipped on the buildable surface. Phase 1 + Phase 2 + Phase 3 will all be marked OPERATIONAL SHIPPED once the soak window closes and `corpus_phase1_soak_check.py --days 14` returns clean.
