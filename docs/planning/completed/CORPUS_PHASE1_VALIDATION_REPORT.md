> **✅ DONE — Phase 1 validation report (Phase 1 shipped). Moved during 2026-05-26 docs cleanup.**

# Corpus Pre-Phase-1 Hardening — Track 4 Validation Re-Ingest Report

## Status: REVISED 2026-04-29 — INGEST-READY, AGENT-INTEGRATION-BLOCKED

Track 4 of `CORPUS_PRE_PHASE1_HARDENING_PLAN.md` v2. Validation re-ingest of 25-ticker set (Appendix A) against the Phase 3+4 deployed parser via the new HTTP API integration (commit `5ba29000`).

**Bottom line:** 46/50 ingestions succeeded (92%); 100% 10-K coverage and 91.7% 10-Q coverage on ingested filings — both exceed Phase-1 entry gates. Corpus engine + MCP wrappers verified working end-to-end (Levels 1+2 of post-ingest live test).

**HOWEVER, Level 3 live-test discovered a Phase-1 user-facing blocker:** the agent gateway dispatcher's `_channel_registry` returns `None` for all 8 corpus tools (`filings_*`, `transcripts_*`), so the agent can name-discover them and call them but the calls fail with `tool_unavailable / "channel may not be connected"`. Filed as **`AI-excel-addin/e1abb24` (HIGH)**. Phase 1 ingest is technically achievable today; **agent-callable corpus is not** until that wiring is fixed.

**Original "green light" claim revised** — see Recommendations for Phase 1 below.

## Setup

- Validation DB: `/tmp/corpus_validation_25/filings.db`
- Validation corpus root: `/tmp/corpus_validation_25/store/`
- Ingest log: `/tmp/corpus_validation_25/ingest.jsonl` (50 entries)
- Retry log: `/tmp/corpus_validation_25/retry.jsonl` (5 entries)
- Tickers ingested: 25 from `CORPUS_PRE_PHASE1_HARDENING_PLAN.md` Appendix A
- Form scope: latest 10-K (year=2024, quarter=4) + latest 10-Q (year=2025, quarter=3) per ticker = 50 attempts
- API: `https://www.financialmodelupdater.com` via new `core/corpus/edgar_api_client.py`
- Bridge: `scripts/corpus_ingest_accession.py` (post-API-integration, commit `5ba29000`)

## T4.1 — Ingest results

50 attempts, 46 successes (92%):

| Outcome | Count | Tickers |
|---|---|---|
| ✅ Both forms ingested | 22 | AAPL, MSFT, GOOG, META, NVDA, INTC, WFC, BK, EQH, MET, BRK-B, GE, HON, XOM, AES, TGT, MCD, JNJ, UNH, PLD, T, DUOT |
| 🟡 10-Q only (10-K failed) | 1 | JPM (10-K hit nginx 502) |
| 🟡 10-Q only (after retry) | 1 | MS (10-K timed out on `/api/sections`) |
| ❌ Both forms failed | 1 | BAC (both forms hit nginx 502) |

Net: 22 tickers fully covered + 2 partially + 1 failed = 23 of 25 with usable data.

### 4 failures detail (filed as Edgar_updater bug `de7c533`)

| Ticker | Form | Year/Q | Failure Mode | Cause |
|---|---|---|---|---|
| JPM | 10-K | 2024 Q4 | HTTP 502 (fast 0-1s) | Nginx upstream timeout (server cold-cache > 120s nginx limit) |
| BAC | 10-K | 2024 Q4 | HTTP 502 (fast 0-1s) | Same |
| BAC | 10-Q | 2025 Q3 | HTTP 502 (fast 0-1s) | Same |
| MS | 10-K | 2024 Q4 | Client 30s timeout on `/api/sections` | Same root cause class (server too slow on cold mega-cap parse) |

Pre-warm reduced timeouts from 5 → 4 (MS 10-Q succeeded on retry). All 4 remaining failures are mega-cap-filer + cold-cache + nginx-timeout combination. Filed at `Edgar_updater/docs/TODO.md de7c533` with concrete fix shape (extend nginx `proxy_read_timeout` for `/api/filings` and `/api/sections` paths to 600s, matching the 2026-04-28 fix for `/api/extractions` + `/api/documents/extract`).

## T4.2 — Canary regression check

Skipped against the original Phase 0 fixture (`/tmp/corpus_canary/` is wiped after reboot per Phase 0 design). Engine correctness covered by:

- **85/85 broader regression** in `pytest tests/test_filings_*.py tests/test_corpus_*.py -v` during Track 3 implementation (commit `5ba29000`)
- **46/46 targeted** in `pytest tests/test_edgar_api_client.py tests/test_filings_tools.py tests/test_corpus_ingest_accession.py -v`
- **Live E2E via T4.4 spot-checks below** confirming source-excerpt path returns real content for AES + MSFT + EQH

No engine regression observed. The canary acceptance tests would re-prove this against the Phase 0 fixture but require re-priming `/tmp/corpus_canary/` per `completed/CORPUS_PHASE0_CHECKPOINT.md §7`.

## T4.3 — Coverage measurement

Per-doc section count vs Phase 4 expected (10-K = 8, 10-Q = 6):

```
10-K: 22/22 (100.0%) — gate ≥93% ✅
10-Q: 22/24 (91.7%)  — gate ≥80% ✅
Total: 44/46 (95.7%)
```

### Above-gate filings

All 22 ingested 10-Ks have ≥8 sections. Most over-deliver with 9 sections (Phase 4's `item_8_notes` split).

### Under-gate but ingested partial-coverage cases

| Ticker | Form | Sections | Expected | Cause |
|---|---|---|---|---|
| GE | 10-Q | 3/6 | 6 | Phase 4 Intel-style TOC bug class (per Edgar_updater audit `parser_audit_20260423.md`) |
| XOM | 10-Q | 5/6 | 6 | Missing `Part II, Item 1A. Risk Factors` — likely brief "no material changes" wording not matching Phase 4 anchors |

Both are documented Phase 4 known issues, not regressions from Track 3 work.

## T4.4 — Spot-check `filings_source_excerpt`

Three end-to-end source-excerpt fetches via the new API path (pre-flight `/api/filings` accession alignment + `/api/sections` content fetch):

| Ticker | Form | Section | Result |
|---|---|---|---|
| AES | 10-K Item 8 | Financial Statements | 740 words returned (auditor's report header; Phase 4 splits financial detail to `item_8_notes`) ✅ |
| MSFT | 10-K Item 7 | MD&A | 6,792 words ✅ — healthy baseline |
| EQH | 10-K Item 7 | MD&A | 20,291 words ✅ — F42 insurance issuer class fully recovered |

All three: pre-flight accession alignment passed + API call returned real content + `state=body` + meaningful text. **End-to-end validation of the new edgar_api_client integration.**

## T4.5 — Expected-failure baseline + new findings

### Documented expected failures (all NOT regressions, all known-issue classes)

| # | Item | Class | Status |
|---|---|---|---|
| 1 | JPM 10-K | nginx 502 mega-cap | Filed Edgar_updater `de7c533` |
| 2 | BAC 10-K | nginx 502 mega-cap | Filed Edgar_updater `de7c533` |
| 3 | BAC 10-Q | nginx 502 mega-cap | Filed Edgar_updater `de7c533` |
| 4 | MS 10-K | nginx 502 mega-cap (client-side timeout variant) | Filed Edgar_updater `de7c533` |
| 5 | GE 10-Q | Phase 4 Intel-style TOC bug | Pre-existing Edgar_updater audit |
| 6 | XOM 10-Q | "No material changes" Risk Factors anchor miss | Pre-existing Edgar_updater audit |

Validation set was designed (per Appendix A) to include 7 Phase 4 known-failure tickers; 6 of those passed cleanly (INTC, WFC, BK, GE [partial], HON, JPM 10-Q), exceeding pre-validation expectations.

### Findings discovered during T4.4 spot-check (resolved 2026-04-29)

**JPM `part1_item1` truncated source-excerpt — RESOLVED, was misdiagnosed:**
- Initial observation: bridge full-fetch returned ~3,566 chars; source-excerpt sections-filter returned only 67 chars (`source: layered_rescue, state: body`).
- Filed as Edgar_updater `0b2b213` thinking it was an API bug.
- Edgar same-day investigation 2026-04-29 closed as not-a-bug. The Phase 4 v10 critical-key rescue (Edgar `abbf412` deployed 2026-04-29) splits rescued sections in the API response: `text` = heading only, `tables[*]` = actual content (3,399 chars of income-statement markdown for JPM `part1_item1`).
- Consumer-side fix in risk_module: `core/corpus/filings.py::filings_source_excerpt` was reading only `text` and discarding `tables[*]`. Fixed at risk_module commit `6a513150` — concatenates text + tables[*] preserving v10 rescue semantics. Bridge ingest already had parity (matches the 3,566-char observation). Codex PASS first round; 87/87 regression tests green.

### Phase 4 money-center bank TOC bug — partially RESOLVED upstream

JPM 10-Q `part1_item1` is now PRESENT in our ingest (3,566 chars). Earlier curl tests on 2026-04-28 returned `state=missing` for the same query. Either:
- Edgar_updater's in-flight Phase 4 money-center fix landed between 2026-04-28 and 2026-04-29
- Or the prewarm pass refreshed cached state to working

JPM 10-Q now ingests as 7 sections (matching the canonical 7 for 10-Q with notes split). Worth confirming with Edgar_updater team whether the bug is fully fixed or just for JPM specifically.

## Post-Track-4 Live Test (added 2026-04-29) — 3 levels

Run after the validation re-ingest to verify the corpus is usable end-to-end before Phase 1.

### Level 1 — direct core function calls — ✅ PASS

Direct Python invocation of `filings_search` / `filings_read` / `filings_source_excerpt` against the validation DB:
- Cross-ticker search `cloud revenue` for MSFT/GOOG/META/AAPL → 16 matches, top hits all MSFT (correct sector signal).
- Bank/insurance `credit risk` for JPM/WFC/BK/MS/EQH/MET → 32 matches, top hits JPM/WFC.
- `filings_read` on a hit → 352K chars retrieved from disk.
- `filings_source_excerpt` MSFT 10-K Item 7 → 6,792 words via API.

### Level 2 — MCP tool wrapper (envelope serialization) — ✅ PASS

Tested via `mcp_tools/corpus/filings.py` decorated functions:
- Wrapper return shape includes all 7 envelope fields (`status`, `hits`, `applied_filters`, `has_low_confidence_supersession`, `has_superseded_matches`, `query_warnings`, `total_matches`).
- Per-hit payload includes all 18 expected fields (ticker, section, snippet, char_start/end, source_url_deep, etc.).
- Error envelope: `status=error`, `error_type=invalid_input`, clean message.
- JSON serializes cleanly (3,395 bytes for a 3-hit response).

### Level 3 — backend integration (agent gateway → corpus tools) — ❌ BLOCKER FOUND

Real agent call via `POST /api/gateway/chat` with prompt: *"Use filings_search to find SEC filing sections discussing cloud revenue across MSFT, NVDA, and GOOG. Return the top 3 hits with ticker, section, and snippet."*

**Result:** agent CORRECTLY emitted `filings_search({"query":"cloud revenue","universe":["MSFT","NVDA","GOOG"],"limit":3})` — proving the tool name is name-discoverable via `risk_module/agent/registry.py:1500-1507`. But the gateway dispatcher returned:

```json
{
  "code": "tool_unavailable",
  "message": "Tool 'filings_search' is not currently available. The channel that provides it may not be connected."
}
```

Agent then attempted to recover via `load_tools(portfolio-mcp)` and `load_tools(finance-cli)` — both loaded but neither contains corpus tools. Stream hung after loading 190+ unrelated tools (likely context bloat / no clear next action).

**Root cause area:** `AI-excel-addin/api/agent/interactive/tool_dispatcher.py` — `_channel_registry.get_channel_for_tool('filings_search')` returns `None`. The 8 corpus tools are registered to the agent's tool registry (so the LLM knows their names + descriptions) but NOT to the dispatcher's channel registry (so calls can't route).

**Filed:** `AI-excel-addin e1abb24` HIGH — full repro + investigation path + acceptance criteria self-contained for fix pickup.

**Net Phase 1 implication:** corpus engine works (Levels 1+2 prove this). User-facing agent path doesn't (Level 3 proves this). Phase 1 corpus scaling can proceed with INGEST work but the result is invisible to users until the gateway wiring is fixed.

## T4.6 — Phase 1 entry gates

| Gate | Required | Actual | Status |
|---|---|---|---|
| Layered parser Phase 3 + Phase 4 deployed | Yes | Yes | ✅ |
| 25-ticker validation set defined | 25 | 25 (Appendix A) | ✅ |
| Corpus plumbing merged + tests passing | Yes | Yes (commit `5ba29000`, 85/85 regression) | ✅ |
| Live smoke test passes via API integration | Yes | Yes (T4.4: AES + MSFT + EQH all OK) | ✅ |
| No canary regressions | Yes | Yes (broader regression 85/85 in Track 3) | ✅ |
| 10-K coverage ≥93% | ≥93% | 100% on ingested filings | ✅ |
| 10-Q coverage ≥80% | ≥80% | 91.7% on ingested filings | ✅ |
| Validation report committed | Yes | This document | ✅ |

### Phase 1 entry gate REVISED 2026-04-29

Original "green light" claim retracted. With Level 3 finding:

| Gate | Status | Note |
|---|---|---|
| All ingest-side gates above | ✅ PASS | Unchanged — corpus engine + ingestion ready |
| **Agent gateway corpus tool routing** | ❌ FAIL | Filed `AI-excel-addin e1abb24` HIGH |

**Ingest-readiness: green.** **User-facing-readiness: blocked on gateway wiring fix.** Two separate gates; first satisfied, second is the new blocker.

## Recommendations for Phase 1 (REVISED 2026-04-29)

**True readiness order:**

1. **AI-excel-addin gateway channel wiring fix (`e1abb24`) — BLOCKING.** Without this, Phase 1 corpus is invisible to the agent UI. Likely a small wiring change (cross-repo: risk_module agent registry ↔ ai-agent-gateway dispatcher channel registry); investigation path documented in the bug entry.
2. **Edgar_updater nginx 502 fix (`de7c533`) — preferred-before but not strictly blocking.** Phase 1's 50-100 universe likely includes more mega-caps; running Phase 1 now would inherit cold-cache failures at higher rates. Server-side fix is small (~10 lines of nginx config). When fixed, retry the 4 mega-caps to reach 50/50.
3. ~~**Edgar_updater `/api/sections` sections-filter discrepancy (`0b2b213`) — low priority.**~~ **RESOLVED 2026-04-29 as misdiagnosis.** Was a consumer-side bug in risk_module's source-excerpt path; fixed at risk_module commit `6a513150` to concatenate text + tables[*] for Phase 4 v10 rescue pattern.
4. **Optionally re-prime `/tmp/corpus_canary/` for canary acceptance tests** — for full Phase 0 regression coverage. Not blocking but cleaner provenance.
5. **Phase 1 universe selection (after gates 1+2)** — pull 50-100 tickers from S&P 500 + the 22 confirmed-clean validation tickers as the baseline. Avoid the 4 cold-cache-failed mega-caps until the nginx fix lands.

**Realistic sequencing:**

- **Now:** wait on `e1abb24` (HIGH) — gateway wiring is the user-facing blocker.
- **In parallel:** wait on `de7c533` (P2) — operationally cleaner Phase 1 ingest at scale.
- **When both land:** retest Level 3 (agent calls corpus) with validation DB, retry the 4 mega-caps, then kick off Phase 1 universe selection + ingest.

## Track 4 SHIPPED — Pre-Phase-1 hardening milestone status

Pre-Phase-1 hardening milestone (`CORPUS_PRE_PHASE1_HARDENING_PLAN.md` v2) is COMPLETE on the corpus side:

- ✅ Track 1 (parser ship) — Phase 3 + Phase 4 deployed; in-flight Phase 4 fixes upstream
- ✅ Track 2 (validation set) — 25-ticker Appendix A locked
- ✅ Track 3 (corpus plumbing) — API integration shipped (commit `5ba29000`)
- ✅ Track 4 (validation re-ingest + live test) — this report

**Phase 1 corpus scaling kickoff: BLOCKED by `AI-excel-addin e1abb24`** (HIGH — agent gateway dispatcher missing channel for corpus tools). Surface ingest can proceed without it; user-facing agent path cannot. Plus recommended-but-not-strictly-blocking: `Edgar_updater de7c533` (nginx 502 mega-cap fix) before Phase 1 ingest at scale.

## References

- `docs/planning/CORPUS_PRE_PHASE1_HARDENING_PLAN.md` v2 — parent milestone
- `docs/planning/CORPUS_EDGAR_API_INTEGRATION_PLAN.md` v8 — Track 3 plan (Codex R8 PASS)
- `docs/planning/completed/CORPUS_LAYERED_PARSER_PLUMBING_PLAN.md` — abandoned Track 3 predecessor
- `docs/planning/CORPUS_ARCHITECTURE.md` — V2.P1 architecture
- Validation DB: `/tmp/corpus_validation_25/filings.db`
- Ingest logs: `/tmp/corpus_validation_25/ingest.jsonl`, `retry.jsonl`
- Edgar_updater bug `de7c533` — nginx 502 mega-cap fix (P2)
- ~~Edgar_updater bug `0b2b213`~~ — RESOLVED 2026-04-29 as misdiagnosis; consumer-side fix at risk_module `6a513150`
- AI-excel-addin bug `e1abb24` — gateway dispatcher missing channel for corpus tools (HIGH — Phase 1 agent-callable blocker)
- Track 3 implementation commit: `5ba29000` (risk_module)
