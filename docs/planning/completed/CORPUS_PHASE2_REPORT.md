> **✅ DONE — Phase 2 report (shipped). Moved during 2026-05-26 docs cleanup.**

# V2.P1 Corpus — Phase 2 Ship Report

**Snapshot:** 2026-05-01
**Branch:** `main`
**Phase 1 reference:** `CORPUS_PHASE1_REPORT.md` (commit `fba7008e`)
**Implementation:** `f418fe77` (universe selection script + universe_phase2.json) + `6276ed73` (ingest results + universe merge)
**Ingest validation:** initial bulk + 7-ticker retry pass

---

## TL;DR

Phase 2 universe expansion **functionally complete**. Added 50 new S&P 500 tickers (ranked by 13F institutional ownership) on top of Phase 1's 50, bringing the corpus to a 100-ticker production universe. DB grew ~2× (820 → 1,665 docs / 5,617 → 11,439 FTS sections). Gate-coverage PASS on the merged universe. 98/100 tickers fully covered; 1 partial (BLK, upstream Edgar_updater bug filed as F53), 1 partial carryover from Phase 1 (CAT). Live-validated end-to-end through Hank — cross-phase semis capex query (NVDA Phase 1 + AMAT/LRCX/KLAC Phase 2) returned analyst-grade synthesis with table-anchored citations.

**2026-05-05 update:** F53 is resolved. Live Edgar API recheck returned supported BLK filings for 2022 Q1 through 2025 Q4, and the promoted corpus now has full BLK gate coverage (4 10-K + 12 10-Q, no weak docs or ingest errors). The historical Phase 2 counts below are retained as the original 2026-05-01 ship snapshot.

---

## 1. What shipped

### 1.1 Universe selection script (`f418fe77`)

`scripts/corpus_phase2_universe_select.py` — one-shot selector that picks the next 50 tickers from S&P 500 ranked by 13F institutional ownership signal. ~250 LOC. Codex R3 PASS after 4 review rounds (R1-R3 caught real bugs — see §5).

**Algorithm:**

1. **Source list**: `etf_holdings(symbol='SPY')` returns ~503 S&P 500 constituents
2. **CIK resolution**: `profile(symbol).cik` for each candidate, cached at `data/corpus/cache/phase2_ciks/{symbol}.json`
3. **Six-stage exclusion filter** (in order):
   - Symbol collision with existing `data/corpus/universe.json`
   - **CIK collision** (catches share-class duplicates — e.g., BRK-A vs existing BRK-B)
   - `profile.isAdr == True` (programmatic ADR detection)
   - Hardcoded `EXCLUDED['ADRs / FPI']` from `scripts/corpus_universe_screen.py` (backstop with mismatch warnings)
   - Hardcoded `EXCLUDED['52/53-week fiscal year']` (AAPL, WMT, COST, TAP, KR)
   - `sec_filings(symbol, type='10-K')` count <5 (strict recent-IPO filter)
4. **13F fetch**: `institutional_positions_summary(symbol, year=2025, quarter=4)` for survivors. Q4 2025 because Q1 2026 13Fs aren't due until 2026-05-15
5. **Composite ranking**: `score = z(log1p(holder_count)) + z(log1p(aggregate_value))` — `log1p` damps mega-cap dominance before z-scoring, z-scores normalize across the candidate pool
6. **Sector mapping**: FMP `profile.sector` → Phase 1 bucket via static map; raw `fmp_sector` preserved alongside

**Output:** `data/corpus/universe_phase2.json` (50 tickers, score + holders + invested + CIK per row, exclusion provenance metadata).

**Default invocation produces correct quarter automatically** via `_latest_due_13f_quarter(date.today())` helper — works without code changes when run later in 2026 or beyond.

### 1.2 Bulk ingest (re-used Phase 1 script)

No new ingest code. `scripts/corpus_phase1_bulk_ingest.py` accepts `--universe data/corpus/universe_phase2.json` and runs identically.

Required two operational gotchas:
- `EDGAR_API_TIMEOUT=120` env override (carryover from Phase 1)
- `set -a && source .env && set +a` first — the Phase 1 script spawns subprocesses that need `EDGAR_API_URL` + `EDGAR_API_KEY` in their inherited env, not just the current shell

### 1.3 Universe merge (commit `6276ed73`)

Inline Python (not a new script):

```python
merged_tickers = list(p1['tickers']) + list(p2['tickers'])
merged = {
    'version': 3, 'phase': '1+2', 'merged_date': '...',
    'tickers': merged_tickers,
    'phase_breakdown': {phase1_count: 50, phase2_count: 50, total: 100},
    'phase2_provenance': {selection_date, selection_method, based_on_quarter},
}
```

Validated no symbol overlap before writing. Schema is the union of fields — Phase 1 entries keep their minimal `{symbol, sector, source}`, Phase 2 entries carry the richer 13F provenance.

The merged file replaces `data/corpus/universe.json` so cron jobs (delta ingest, reconciler, health report) handle the full 100 tickers automatically. No code changes to consumers.

`universe_phase2.json` retained as a historical artifact.

---

## 2. Bulk-ingest results

### 2.1 Initial run + retry

| Run | Attempts | OK | Expected-no-filing | Real errors | Notes |
|---|---|---|---|---|---|
| Initial bulk (50 Phase 2 tickers) | 1000 | 756 | 133 | 111 | Most errors HTTP 502 from edgar_api on specific historical periods |
| Targeted retry (7 partial-coverage tickers) | 140 | 88 | 30 | 22 | 6/7 recovered cleanly; BLK lone holdout |

### 2.2 Per-ticker resolution after retry

| Status | Count | Tickers |
|---|---|---|
| Fully covered (≥4 10-K + ≥8 10-Q) | 98 | All except CAT and BLK |
| Partial — Phase 1 carryover | 1 | CAT (10-K=3, 10-Q=11) |
| Partial — Phase 2 (upstream) | 1 | BLK (10-K=2, 10-Q=4) |
| Zero coverage | 0 | — |

### 2.3 Final corpus state

```
data/filings.db
├── documents:        1,665   (Phase 1: 820 → +845)
└── sections_fts:    11,439   (Phase 1: 5,617 → +5,822)
```

### 2.4 Gate coverage on merged 100-ticker universe

```
10-K: 399/399 = 100.0%   (gate: ≥95%) ✅
10-Q: 1124/1266 = 88.8%   (gate: ≥85%) ✅
gate_coverage: True
```

---

## 3. Live validation

End-to-end test through Hank dev chat CLI on the merged 100-ticker universe:

> "Compare semiconductor capex outlook commentary across NVDA, AMAT, LRCX, and KLAC using their most recent 10-Qs."

NVDA from Phase 1, AMAT/LRCX/KLAC from Phase 2 (cross-phase synthesis).

**Result:**
- All 4 returned hits without F47 OR-fallback firing
- KLAC's 10-Q (filed 2026-04-30, the same day as the test) was searchable
- Hank stayed entirely on corpus tools — no `run_bash` workaround
- Output included verbatim management quotes, table-anchored citations, and 2nd-order analyst inference (KLAC's gross margin pressure from internal DRAM purchases as a corroborating signal of DRAM market tightness)

Wall clock 93.6s, $1.18.

---

## 4. Phase 2 follow-ups

### F53 — BLK 2022-2024 upstream issue (filed 2026-04-30; resolved 2026-05-05)

Original 2026-05-01 snapshot: BLK was the only Phase 2 ticker that didn't reach the gate. Two distinct upstream failure modes were present:
- **2022 Q1-Q4**: edgar_api `/api/filings` returns HTTP 500 Internal Server Error for all four quarters, persistent across initial bulk + retry
- **2023 Q1-Q4 + 2024 Q1-Q2**: edgar_api returns empty filings list (upstream data gap)
- **2024 Q3-Q4 + 2025 Q1-Q4**: came through cleanly (6 docs total)

Cross-repo home: Edgar_updater. Reproduction logs at `data/corpus/logs/phase2_bulk_2026-04-30-192004.jsonl` + `data/corpus/logs/phase2_retry_2026-04-30-220904.jsonl`. Severity: medium-low — 1 of 100 universe tickers, partial coverage rather than zero, doesn't block Phase 2 ship.

Resolved 2026-05-05 after the upstream API began returning BLK filings for the missing historical periods and the corpus promote carried the refreshed local corpus to prod. Verification: live `/api/filings` succeeded for BLK 2022 Q1 through 2025 Q4; local and prod `documents` each contained 16 BLK EDGAR docs; `corpus_health_report --ticker BLK` showed full 10-K/10-Q coverage and no ingest errors.

### Carryover from Phase 1

- **CAT** — 10-K=3 vs target 4. Pre-existed Phase 2 work; tracked under Phase 1 soak gates.
- **F42** — `edgar-parser` financials/insurance section dropouts. Upstream.
- **F43** — amendment full support, deferred.
- **F44** — markdown↔HTML highlight map (backlog).
- **F47** — RESOLVED 2026-04-30 (commit `f4e7dc4d`).
- **F48** — file_grep absolute-path bug (cross-repo AI-excel-addin gateway tool).
- **F50** — 3 Phase 4 parser bugs filed in Edgar_updater (re-ingest pending upstream fix).
- **F51** — 14-day soak verification, due ~2026-05-14.
- **F52** — parser-health observability integration (backlog).

---

## 5. What changed vs original plan

### 5.1 Scope held

Plan: pull 50 from S&P 500 by 13F holder count + aggregate value, dedupe, exclude per Phase 1 rules, ingest. Implementation matches.

### 5.2 Codex review rounds caught 5 P1s + 2 P2s

The R1→R2→R3→R4 review pipeline caught real bugs that would have shipped:
- **R1.P1**: 13F quarter math wrong (had 2024-Q4 vs correct 2025-Q4 — Q1 2026 13Fs not due until May 15 2026)
- **R1.P1**: Symbol-only dedupe unsafe — needed CIK dedupe to catch share-class collisions (BRK-A vs existing BRK-B)
- **R1.P1**: Hardcoded 52/53-week list incomplete — `corpus_universe_screen.py:9-13` already had the canonical 5-entry list (AAPL, WMT, COST, TAP, KR) vs my proposed 3
- **R2 P1**: `profile.fiscalYearEnd` doesn't exist in FMP profile contract — must derive from `income_statement` period dates
- **R3 P1**: FMP `sec_filings` field is `type`, not `form_type` — naive check would have over-excluded everything
- **R1.P2 #1**: Plan had no recommendation on which signal (z-score vs raw product) — Codex picked z(log1p) blend with optional winsorization
- **R1.P2 #2**: Plan left sector mapping ambiguous — Codex picked static FMP→Phase-1-bucket map preserving raw `fmp_sector`

### 5.3 Discovered during execution

- **Phase 1 bulk script silently filters `--ticker` to the loaded universe** — burned a debugging cycle when retrying Phase 2 tickers without the explicit `--universe` flag (BLK isn't in the default Phase 1 universe, so `--ticker BLK` returned empty). Worth a docstring note in the script.
- **Mid-run progress check missed cluster failures** — at the 64% mark, the per-ticker breakdown showed only 5 real errors, but the final tally was 111 because failures came from a few clustered tickers (BKNG, COF, GILD, DE, BMY) where every quarter failed. A per-ticker zero-doc detector during the run would surface this earlier than the post-hoc analysis.

---

## 6. Phase 3 entry posture

Phase 3 (transcripts ingest pipeline) is the natural next deliverable per `CORPUS_ARCHITECTURE.md` §13.

The mechanism is already in place:
- `core/corpus/transcripts.py` exists with full ingest path
- `transcripts_*` MCP tools wired into agent registry
- `CORPUS_INGEST_ENABLED` env flag in `fmp/tools/transcripts.py` activates ingest path

Scope when ready:
1. Pull FMP transcripts for the 100-ticker universe (~5 years × ~4 quarters/yr × 100 = ~2,000 transcripts)
2. Run through existing ingest path
3. Validate `transcripts_search` end-to-end through Hank
4. Add transcripts coverage gate to `corpus_health_report.py`

No architectural changes needed.

Alternative ramp: **Phase 4 (full S&P 500 expansion)** — re-run `corpus_phase2_universe_select.py` with `--limit 450` against the now-100-ticker existing universe to produce `universe_phase4.json`. Architecture estimates ~$250 incremental cost, ~7,500 files total. Lower priority unless a product need justifies the universe size jump.

---

## 7. Sign-off

- ✅ Phase 2 universe selected (data-driven 13F ranking, 4 Codex review rounds)
- ✅ Phase 2 bulk ingest completed (756 OK + 133 expected + 111 transient errors)
- ✅ 6/7 retry-ticker recoveries in the original Phase 2 run; BLK/F53 resolved on 2026-05-05 after upstream recovery and corpus promote
- ✅ Universe merged (50 Phase 1 + 50 Phase 2 = 100 tickers, no overlap, no consumer code changes needed)
- ✅ Gate-coverage PASS on merged 100-ticker universe (10-K 100%, 10-Q 88.8%)
- ✅ Live-validated through Hank cross-phase semis test
- 🟡 Phase 1 14-day soak still in progress (Phase 1 OPERATIONAL SHIPPED gate, due ~2026-05-14)

Phase 2 ingest is shipped on the buildable surface. Phase 1 + Phase 2 will both be marked OPERATIONAL SHIPPED once the soak window closes and `corpus_phase1_soak_check.py --days 14` returns clean.
