# V2.P1 Corpus — Phase 0 Canary Dataset

**Status:** LOCKED 2026-04-23. Covers E1 + G1 from `CORPUS_IMPL_PLAN.md` §4 Blocks E + G.
**Purpose:** Defines the exact tickers, SEC accessions, and edge-case documents that Phase 0 ingestion (G2) and acceptance (G3) run against.
**Scope:** 10 primary tickers + 1 amendment-pair ticker + 1 microcap + 1 synthetic low-confidence amendment.

Every accession in this doc was verified via `mcp__edgar-financials__get_filings` on 2026-04-23 against live SEC metadata. Re-verify before G2 execution if >30 days have passed.

---

## 1. Primary canary tickers

Eight names covering tech baselines, share-class edge cases, financials, energy, retail, and a diversified conglomerate. All have a most-recent 10-K (FY2025) plus the four most-recent 10-Q accessions. Form types: `10-K`, `10-Q`. Source: `edgar`.

### 1.1 AAPL — Apple Inc. (tech baseline)

CIK: 320193. Fiscal year ends late September.

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0000320193-25-000079` | 2025-10-31 | 2025-09-27 | FY2025 Q4 |
| 10-Q | `0000320193-25-000073` | 2025-08-01 | 2025-06-28 | FY2025 Q3 |
| 10-Q | `0000320193-25-000057` | 2025-05-02 | 2025-03-29 | FY2025 Q2 |
| 10-Q | `0000320193-25-000008` | 2025-01-31 | 2024-12-28 | FY2025 Q1 |
| 10-Q | `0000320193-24-000081` | 2024-08-02 | 2024-06-29 | FY2024 Q3 |

Transcripts: 2 most recent earnings call transcripts — resolved via FMP at G2 kickoff (FMP doesn't use SEC-style accessions; use most-recent two fiscal periods from `mcp__fmp-mcp__get_earnings_transcript`).

### 1.2 MSFT — Microsoft Corporation (tech baseline + legacy migration test)

CIK: 789019. Fiscal year ends June 30. Existing `MSFT_10Q_2025_6f90a2a7.md` is present in both legacy stores (Edgar_updater + AI-excel-addin) — F2 migration verifies the dedup path on this ticker.

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0000950170-25-100235` | 2025-07-30 | 2025-06-30 | FY2025 Q4 |
| 10-Q | `0000950170-25-061046` | 2025-04-30 | 2025-03-31 | FY2025 Q3 |
| 10-Q | `0000950170-25-010491` | 2025-01-29 | 2024-12-31 | FY2025 Q2 |
| 10-Q | `0000950170-24-118967` | 2024-10-30 | 2024-09-30 | FY2025 Q1 |
| 10-Q | `0000950170-24-048288` | 2024-04-25 | 2024-03-31 | FY2024 Q3 |

Transcripts: 2 most recent earnings call transcripts via FMP at G2 kickoff.

### 1.3 GOOG — Alphabet Inc. Class C (share-class edge case)

CIK: 1652044. Fiscal year ends December 31. GOOG/GOOGL share-class split tests `SymbolResolver` canonicalization.

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0001652044-26-000018` | 2026-02-05 | 2025-12-31 | FY2025 Q4 |
| 10-Q | `0001652044-25-000091` | 2025-10-30 | 2025-09-30 | FY2025 Q3 |
| 10-Q | `0001652044-25-000062` | 2025-07-24 | 2025-06-30 | FY2025 Q2 |
| 10-Q | `0001652044-25-000043` | 2025-04-25 | 2025-03-31 | FY2025 Q1 |
| 10-Q | `0001652044-24-000118` | 2024-10-30 | 2024-09-30 | FY2024 Q3 |

### 1.4 META — Meta Platforms Inc. (tech baseline with AI language)

CIK: 1326801. Required for canary query Q1 (AI capex discussion).

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0001628280-26-003942` | 2026-01-29 | 2025-12-31 | FY2025 Q4 |
| 10-Q | `0001628280-25-047240` | 2025-10-30 | 2025-09-30 | FY2025 Q3 |
| 10-Q | `0001628280-25-036791` | 2025-07-31 | 2025-06-30 | FY2025 Q2 |
| 10-Q | `0001326801-25-000054` | 2025-05-01 | 2025-03-31 | FY2025 Q1 |
| 10-Q | `0001326801-24-000081` | 2024-10-31 | 2024-09-30 | FY2024 Q3 |

### 1.5 BRK-B — Berkshire Hathaway Class B (diversified conglomerate)

CIK: 1067983. Filings only — Berkshire does not hold traditional quarterly earnings calls, and FMP transcript coverage is absent. Note the ticker comes through EDGAR as `BRK-B` (dash), not `BRK.B` (period).

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0001193125-26-083899` | 2026-03-02 | 2025-12-31 | FY2025 Q4 |
| 10-Q | `0001193125-25-261548` | 2025-11-03 | 2025-09-30 | FY2025 Q3 |
| 10-Q | `0000950170-25-101578` | 2025-08-04 | 2025-06-30 | FY2025 Q2 |
| 10-Q | `0000950170-25-063112` | 2025-05-05 | 2025-03-31 | FY2025 Q1 |
| 10-Q | `0000950170-24-120241` | 2024-11-04 | 2024-09-30 | FY2024 Q3 |

### 1.6 JPM — JPMorgan Chase & Co. (financials — Basel III / credit provisions)

CIK: 19617. The edgar-financials MCP tool intermittently timed out on JPM requests; all accessions below were resolved on retry. Re-verify before G2.

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0001628280-26-008131` | 2026-02-13 | 2025-12-31 | FY2025 Q4 |
| 10-Q | `0001628280-25-048859` | 2025-11-04 | 2025-09-30 | FY2025 Q3 |
| 10-Q | `0000019617-25-000615` | 2025-08-05 | 2025-06-30 | FY2025 Q2 |
| 10-Q | `0000019617-25-000421` | 2025-05-01 | 2025-03-31 | FY2025 Q1 |
| 10-Q | `0000019617-24-000611` | 2024-10-30 | 2024-09-30 | FY2024 Q3 |

### 1.7 XOM — Exxon Mobil Corp. (XBRL-heavy, segment reporting)

CIK: 34088.

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0000034088-26-000045` | 2026-02-18 | 2025-12-31 | FY2025 Q4 |
| 10-Q | `0000034088-25-000061` | 2025-11-03 | 2025-09-30 | FY2025 Q3 |
| 10-Q | `0000034088-25-000042` | 2025-08-04 | 2025-06-30 | FY2025 Q2 |
| 10-Q | `0000034088-25-000024` | 2025-05-05 | 2025-03-31 | FY2025 Q1 |
| 10-Q | `0000034088-24-000068` | 2024-11-04 | 2024-09-30 | FY2024 Q3 |

### 1.8 TGT — Target Corporation (consumer retail baseline)

CIK: 27419. Fiscal year ends late January/early February; Q4 FY2025 period end = 2026-01-31.

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0000027419-26-000016` | 2026-03-11 | 2026-01-31 | FY2025 Q4 |
| 10-Q | `0000027419-25-000126` | 2025-11-26 | 2025-11-01 | FY2025 Q3 |
| 10-Q | `0000027419-25-000118` | 2025-08-29 | 2025-08-02 | FY2025 Q2 |
| 10-Q | `0000027419-25-000101` | 2025-05-30 | 2025-05-03 | FY2025 Q1 |
| 10-Q | `0000027419-24-000179` | 2024-11-27 | 2024-11-02 | FY2024 Q3 |

---

## 2. Microcap — DUOT (Duos Technologies Group, Inc.)

CIK: 1396536. Stress-tests spartan filings. Micro-cap industrial tech, recent 10-Ks are compact relative to mega-cap peers.

| Form | Accession | Filing date | Period end | Fiscal |
|---|---|---|---|---|
| 10-K | `0001079973-26-000405` | 2026-03-31 | 2025-12-31 | FY2025 Q4 |
| 10-Q | `0001079973-25-001713` | 2025-11-13 | 2025-09-30 | FY2025 Q3 |
| 10-Q | `0001079973-25-001297` | 2025-08-14 | 2025-06-30 | FY2025 Q2 |
| 10-Q | `0001553350-25-000046` | 2025-05-15 | 2025-03-31 | FY2025 Q1 |
| 10-Q | `0001079973-24-001587` | 2024-11-19 | 2024-09-30 | FY2024 Q3 |

**Expected brittleness:** DUOT's 10-K is typically <100 pages and may omit Items that section parsers assume are present (e.g., a thin Item 7A, sparse or absent Item 9A). If G2 ingestion surfaces unparseable sections, flag the convention for adjustment before expanding to Phase 1.

---

## 3. Amendment pair — EQH (Equitable Holdings, Inc.)

> **Status 2026-04-23: DEFERRED (Phase 0)** — high-confidence amendment live-test (Q6 acceptance) waived for Phase 0 ship per F43. Only the EQH 10-K **original** (`0001333986-26-000012`) was ingested; the 10-K/A amendment is blocked by upstream `edgar-parser` accession-aware routing gaps. Supersession write-path is unit-tested (`tests/test_corpus_supersession.py`, `tests/test_corpus_ingest.py:178`); Q9 low-confidence gating is live-tested via §4 synthetic fixture below. Revisit when restatement-tracking becomes a product priority.

CIK: 1333986. Real 10-K/A filed 2026-04-21 amends the original 10-K filed 2026-02-25. The amendment adds Part III governance/compensation information that was originally incorporated by reference from the proxy. Clean example because (a) both filings are publicly available, (b) the amendment explicitly names the original in its cover text, (c) both carry the same fiscal period end (2025-12-31).

| Role | Form | Accession | Filing date | Period end |
|---|---|---|---|---|
| Original | `10-K` | `0001333986-26-000012` | 2026-02-25 | 2025-12-31 |
| Amendment | `10-K/A` | `0001333986-26-000017` | 2026-04-21 | 2025-12-31 |

**E1 manual authoring (done during G2):** when ingesting the 10-K/A, hand-author frontmatter:

```yaml
supersedes: edgar:0001333986-26-000012
supersedes_source: manual
supersedes_confidence: high
```

Per D14 + I14, the `high` confidence drives the `is_superseded_by` derived column on the original. Default `filings_search` must hide the original; `include_superseded=True` must surface it; reconciler rerun must arrive at the same result. Acceptance covered by canary query Q6 (§4.6).

---

## 4. Low-confidence synthetic amendment (Q9 acceptance fixture)

> **Status 2026-04-23: PARTIAL PASS.** Fixture authored and ingested at canonical path `/private/tmp/corpus_canary/store/edgar/EQH/10-K/A_2025-FY_e0ec03d7.md` with `document_id: edgar:synthetic_lowconf_eqh_2025`. Verified: (✓) default `filings_search` returns the EQH original unhidden, (✓) response carries `has_low_confidence_supersession=true`, (✓) D14 gating — `is_superseded_by` NULL on both original and synthetic, (✓) `include_low_confidence_supersession=True` hides the original. **DEFERRED** per F43: the "surface the synthetic" sub-criterion — `filings_search` excludes `10-K/A` via `FILINGS_FAMILY_FORM_TYPES` so the synthetic can never appear in hits regardless of the flag. Filings-family widening lives under F43 follow-up; core supersession gating is proven.

**The only synthetic data in the canary.** Everything else is real SEC/FMP source material.

Hand-author one file at G2 time that mimics the shape of an amendment but carries `supersedes_confidence: low`. It points at one of the real originals above — recommend targeting EQH's 10-K (`0001333986-26-000012`) so the confidence-gating path is exercised on the same document the high-confidence amendment targets. The canary doc text remains the original's high-confidence-superseded state; the low-confidence synthetic exists purely to test the read-path gating.

Filename: `CORPUS_ROOT/edgar/EQH/10-K/A_2025-FY_<synthetic_hash>.md`

Frontmatter stub:

```yaml
document_id: edgar:synthetic_lowconf_eqh_2025
ticker: EQH
source: edgar
form_type: 10-K/A
fiscal_period: 2025-FY
supersedes: edgar:0001333986-26-000012
supersedes_source: heuristic
supersedes_confidence: low
extraction_status: complete
content_hash: <filled by finalize_with_hash>
```

**Acceptance (Q9):**
- Default `filings_search` returns the EQH original (not hidden by the low-confidence pointer).
- Response carries `has_low_confidence_supersession=true`.
- `include_low_confidence_supersession=True` hides the original and surfaces the synthetic.
- Reconciler re-run does not populate `is_superseded_by` on the original from this pointer (confidence-gated per D14).

---

## 5. Same-day multi-8-K case (TBD — resolve at G2 kickoff)

**Status: UNLOCKED.** The `mcp__edgar-financials__get_filings` tool surfaces at most one 8-K per fiscal quarter (the earnings release), not the full 8-K history, so same-day-multi-8-K pairs were not directly discoverable through the tool at lockdown time. Direct EDGAR access (`sec.gov/cgi-bin/browse-edgar`) is 403-blocked from WebFetch.

**Resolution procedure** — execute at G2 kickoff (before canary ingest):
1. For any primary canary ticker (AAPL recommended — its 2026-04-20 CEO transition is likely to have triggered multiple 8-Ks), manually browse EDGAR's 8-K index for that ticker.
2. Identify one date with ≥2 8-K accessions filed.
3. Lock the chosen (ticker, date, accession_a, accession_b) tuple into §5 of this doc before starting ingestion.
4. Ingest both 8-Ks; verify canary query Q7 (multi-filing disambiguation) correctly disambiguates by `document_id`.

If no suitable natural case surfaces in any canary ticker's 8-K history, fall back to ingesting two real same-day 8-Ks from a ticker outside the primary set — the multi-8-K fixture does not need to be on a canary ticker to exercise Q7.

---

## 6. Acceptance summary

| Edge case | Exercised by | Fixture location |
|---|---|---|
| Amendment chain (high confidence) | Q6 | EQH 10-K + 10-K/A (§3) |
| Multi-filing disambiguation | Q7 | TBD (§5) |
| Low-confidence supersession gating | Q9 | Synthetic file against EQH original (§4) |
| Share-class canonicalization | MCP surface | GOOG (§1.3) |
| Migration dedup | F1/F2 verify | MSFT (§1.2, both legacy stores) |
| Spartan section structure | G2 ingest | DUOT (§2) |
| Transcript + filings interplay | MCP surface | AAPL, MSFT transcripts (FMP, resolve at G2) |

**Total ingested documents at G2 completion:** 10 primary tickers × 5 filings + 1 microcap × 5 filings + 1 amendment (EQH 10-K/A) + 1 synthetic low-confidence + ~4 transcripts (AAPL×2 + MSFT×2) + ~2 multi-8-K (§5) ≈ **~63 documents**.

---

## 7. Re-verification checklist (before G2)

Before starting G2 ingestion, re-run these checks to guard against stale metadata:

- [ ] For each ticker in §1 and §2, call `mcp__edgar-financials__get_filings` to confirm the listed accessions still match what EDGAR returns. If a newer 10-Q has been filed since 2026-04-23, update the "most-recent" list accordingly.
- [ ] Confirm EQH 10-K/A (§3) is still accessible at its accession URL and the original is still on EDGAR.
- [ ] Pick the same-day multi-8-K case (§5) and lock its accessions into this doc.
- [ ] Decide whether to swap JPM for a financials alternative (BAC/WFC/GS) if the tool timeouts persist at G2 ingest time.
- [ ] Confirm AAPL and MSFT transcripts via `mcp__fmp-mcp__get_earnings_transcript` for the two most recent fiscal periods each.
