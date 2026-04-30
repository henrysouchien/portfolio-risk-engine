# V2.P1 Corpus — Phase 1 Ship Report

**Snapshot:** 2026-04-30
**Branch:** `main`
**Phase 1 plan:** `CORPUS_PHASE1_PLAN.md` v4-final (Codex R4 PASS at `c68726be`)
**Implementation:** `745d00c5` (16 files, ~1001 LOC, 90/90 tests)
**Bulk validation:** initial run + mega-cap retry (this report)

---

## TL;DR

Phase 1 universe ingest **functionally complete**. 50 tickers × 5-year history loaded into corpus; gate-coverage check PASS; daily cron + reconciler installed and running. Three soak-window gates (14-day delta, 14-day reconciler, 7-day dashboard) are in flight and report against per-day JSONL output as time accumulates.

| Gate | Status | Verification |
|---|---|---|
| 1. Universe ingested | ✅ PASS | `--gate-coverage` returned True; 50/50 tickers; all 7 mega-cap banks fully covered |
| 2. Per-doc section coverage | ✅ PASS | 10-K 200/200 (100%) ≥ 95%; 10-Q 539/620 (87%) ≥ 85% |
| 3. Daily delta ingest 14-day soak | 🟡 IN FLIGHT | Cron installed in `workers/beat_schedule.py`; soak-check tooling in `scripts/corpus_phase1_soak_check.py` |
| 4. Reconciler 14-day soak | 🟡 IN FLIGHT | Same — cron + JSONL log + soak-check |
| 5. Agent gateway corpus calls | ✅ PASS | Validated 2026-04-29 during pre-Phase-1 hardening (Track 4 Level 3, e1abb24 fix) |
| 6. Dashboard 7-day continuity | 🟡 IN FLIGHT | First report at `data/corpus/health/2026-04-30.json` |
| 7. Operational runbook | ✅ PASS | Phase 1 plan v4-final + per-script docstrings |
| 8. Ship report committed | ✅ PASS | This document |

5/8 gates closed at ship; 3/8 are time-window gates that close on their own as the cron runs. **Phase 1 is shipped on the buildable surface**; soak gates will validate operational stability.

---

## 1. What shipped

### 1.1 Phase 1 implementation (`745d00c5`)

16 files, ~1001 LOC, 90/90 tests passing. Plan v4-final at `c68726be` was Codex PASS after 4 rounds (R1–R3 caught 7 P1 + 11 P2 issues — universe math, reconciler entry-point name, Celery cron specifics, transcript scope, AAPL contradiction, amendment loop in delta detector).

Key components:
- `data/corpus/universe.json` — 50 tickers locked
- `scripts/corpus_phase1_bulk_ingest.py` — bulk wrapper with per-attempt JSONL log
- `scripts/corpus_phase1_delta_ingest.py` — daily delta detector (filters `/A` amendments + 8-Ks)
- `scripts/corpus_health_report.py` — daily JSON dashboard with `--gate-coverage`
- `scripts/corpus_phase1_soak_check.py` — soak-window validator (delta + reconciler + dashboard)
- `workers/tasks/corpus.py` — 3 `@shared_task` wrappers around `core.corpus.reconciler.reconcile()`
- `workers/celery_app.py` + `workers/beat_schedule.py` — 3 crontab entries (03:00 delta, 06:00 reconciler, 07:00 dashboard UTC)
- 6 other operational scripts (purge, backup, rebuild, screen, retry, etc.)

### 1.2 Cold-cache fix — `EDGAR_API_TIMEOUT` env override (`058926dd`)

Default `httpx` client timeout was 30s. Mega-cap historical 10-K/10-Q parses regularly exceed that on cold cache (JPM/C/GS were 100% timeout in initial bulk; MS/BAC heavily affected). Added env-var override in `core/corpus/edgar_api_client.py::_resolve_default_timeout` so operators can bump for batch jobs without code changes.

**Follow-up 2026-04-30:** the fallback default is now 600s, matching Edgar_updater's nginx ceiling. `EDGAR_API_TIMEOUT` still overrides the default when operators want a shorter or longer per-process setting.

```python
# .env or shell
EDGAR_API_TIMEOUT=120
```

Validated: 7-ticker mega-cap retry achieved **113/113 real attempts ok** (100% success on filings that exist; the 27 errors are 2026-quarter filings that don't exist yet).

This closes P-Med filed at `0961c877`.

---

## 2. Bulk-ingest results

### 2.1 Initial run + retry

| Run | Attempts | OK | Error | Notes |
|---|---|---|---|---|
| Initial bulk (50 tickers) | 1000 | 728 | 272 | 156 expected-failures (52/53-week filers, missing periods) + 116 cold-cache timeouts |
| Mega-cap retry (7 tickers, EDGAR_API_TIMEOUT=120) | 140 | 113 | 27 | 27 errors all 2026 future quarters (no filing exists) |

### 2.2 Final corpus state

```
data/filings.db
├── documents:        820
└── sections_fts:   5,617
```

### 2.3 Mega-cap bank coverage (the cohort that triggered the timeout fix)

| Ticker | 10-K | 10-Q |
|---|---|---|
| BAC | 4 | 12 |
| C | 4 | 12 |
| GS | 4 | 12 |
| JPM | 4 | 12 |
| MS | 4 | 12 |
| USB | 4 | 12 |
| WFC | 4 | 13 |

All 7 fully covered for the 5-year window.

### 2.4 Coverage ratios (`scripts/corpus_health_report.py --gate-coverage`)

```
10-K: 200/200 = 100.0%   (gate: ≥95%) ✅
10-Q: 539/620 = 86.9%    (gate: ≥85%) ✅
gate_coverage: True
```

Per-doc section weakness: 81 documents have section counts below the per-source expected threshold (most concentrated in GE 10-Q where Phase 4 parser finds 3-4 sections vs expected 6). These are recorded in `weak_documents` per-ticker in the dashboard JSON for monitoring; they do not block the aggregate gate.

---

## 3. What changed vs Phase 1 plan

### 3.1 Scope-faithful

Plan v4-final scope held: 50-ticker universe, 5-year history, daily cron, reconciler detection-only, dashboard, soak gates. Implementation matches.

### 3.2 Discovered during execution

- **Cold-cache mega-cap timeout** — not anticipated in plan; added env override + retry, no scope change.
- **2026 future-quarter "errors"** — bulk script attempts all years × quarters. For 2026, only Q1 has been filed by some issuers as of ship date. The script's per-attempt error correctly reports "no filing matched"; these surface as expected failures, not bugs.

### 3.3 Open Phase-1 follow-ups (none block ship)

- **F-Med (NEW)** — 81 weak documents below per-source section threshold, 10 of which are GE 10-Q (Phase 4 finds 3-4 sections instead of 6). Upstream parser issue. Track in dashboard `weak_documents`; revisit if it impacts retrieval quality.
- **F42 (carry from Phase 0)** — `edgar-parser` drops MD&A + Financial Statements for JPM 10-Q. Upstream. Phase 4 v10 critical-key rescue mitigates content loss; consumer reads `text + tables[*]` (closed at `6a513150`).
- **F43 (carry from Phase 0)** — amendment full support. Deferred per plan.

---

## 4. Verifying the soak gates

The 3 in-flight gates close on time-window evidence, not on a moment-in-time check. To verify them after the soak window:

```bash
python3 scripts/corpus_phase1_soak_check.py --days 14
```

Validates:
- Delta cron: every day in window has `logs/corpus/delta_<date>.jsonl`; window-average errors ≤ `--max-average-errors` (default 2)
- Reconciler cron: every day in window has `logs/corpus/reconciler_<date>.jsonl` with ≥1 row; max drift across any single run ≤ `--max-drift-per-run` (default 5)
- Dashboard: every day in window has valid health JSON at `data/corpus/health/<date>.json` (with `tickers` + `coverage` + `ingest_errors` keys)

---

## 5. Phase 2 entry posture

Phase 1 ships the buildable surface. Phase 2 is a natural ramp:

1. Pull another 50 tickers from S&P 500 by 13F holder count + aggregate value
2. Re-run ingest cycle (now with 600s fallback timeout; `EDGAR_API_TIMEOUT` can override per environment)
3. Re-validate coverage gates against 100-ticker universe
4. Begin transcripts ingest (deferred from Phase 1 per architecture)

No architectural blockers identified. Plan-first workflow continues to apply.

---

## 6. Sign-off

- ✅ 5/8 gates closed at ship
- 🟡 3/8 gates time-window — closes on cron continuity (verify with `corpus_phase1_soak_check.py --days 14`)
- ✅ Cold-cache fix shipped + live-validated
- ✅ All 7 mega-cap banks fully covered after retry
- ✅ Implementation tests 90/90 pass
- ✅ Codex R4 PASS plan + R1 PASS source-excerpt fix

Phase 1 is ready to be marked SHIPPED in `docs/TODO.md` once the 14-day soak completes.
