# V2.P1 Corpus — Phase 0 Checkpoint

**Snapshot:** 2026-04-23
**Branch:** `feat/corpus-phase0` (worktree at `/Users/henrychien/Documents/Jupyter/risk_module-corpus-phase0/`)
**Head:** `9dd2b1bc` (before this checkpoint commit — G4 ship signal at head)

Full context — what's committed, what's live-validated, what's ephemeral, and exactly how to resume in a future session.

---

## 0. G4 — Ship Signal (2026-04-23)

**Phase 0 SHIPPED.** Convention locked. Ready for Phase 1 handoff.

**Final worktree state**:
- 19 commits on `feat/corpus-phase0` (from A0 vendoring through G4 signal)
- 161 tests passing (151 Phase 0 scaffold + 10 F40 ticker-canonicality)
- 50-document canary at `/tmp/corpus_canary/filings.db` — 46 EDGAR filings (10 tickers × 10-K + 4 10-Qs) + 4 FMP transcripts (AAPL × 2 + MSFT × 2) + 1 synthetic low-confidence amendment (EQH 10-K/A)

**Locked conventions** (do not change without a versioned migration):

| Area | Convention |
|---|---|
| Frontmatter | `core/corpus/frontmatter.py::FIELD_ORDER` — 24 fields, schema with required vs nullable sets, document_id format `{source}:{source_id}`, canonical hash placeholder |
| Canonical path | `{CORPUS_ROOT}/{source}/{TICKER}/{form_type}_{fiscal_period}_{content_hash}.md` (amendments intentionally subfolder at `{form_type}/A_...md`) |
| Ticker | Uppercase, no whitespace, no `:`/`/` chars, hyphens + dots allowed (mirrors `canonical_path` predicate and `validate_search_inputs` F40 check) |
| Section parsers | `core/corpus/section_map.py` — per-source (edgar + fmp_transcripts) section header conventions |
| Form types | `FILINGS_FAMILY_FORM_TYPES = {10-K, 10-Q, 8-K}` (amendments `/A` variants EXCLUDED from search surface — deferred per F43) |
| Supersession | D14 confidence gating — `is_superseded_by` auto-triggered by `ingest_raw` only when `supersedes_confidence='high'` |

**§13.6 canary queries (A5 verification)**: Q1-Q5 + bonus cross-source PASS. Q6 (amendment chain) deferred per F43. Q7 (multi-8-K) never locked. Q8 (reconciler heal) — operational test, not a query — unit-tested in `tests/test_corpus_reconciler.py`. Q9 — 4/5 sub-criteria PASS; "surface synthetic" deferred per F43.

**Open Phase 0 follow-ups** (none block ship):
- **F41** — corpus scalar `ticker=` args canonicalization (read-side parity with F40). S effort, orthogonal.
- **F42** — `edgar-parser` drops MD&A + Financial Statements for JPM 10-Q. UPSTREAM. Blocks Phase 1 financials coverage.
- **F43** — amendment full support (upstream routing + filings-family widening). DEFERRED / LOW PRIORITY. Revisit only if restatement-tracking becomes a product priority.

**Phase 1 handoff**: corpus primitives stable. New arrivals should read this checkpoint, then `CORPUS_ARCHITECTURE.md` §7 (verification pattern), §8 (end-to-end flow), and `CORPUS_IMPL_PLAN.md` Phase 1-2 blocks for next-step scope.

---

## 1. What's committed

### 1.1 Edgar_updater main (separate repo, 3 commits)

| SHA | Task | Description |
|---|---|---|
| `7ae3c8b` | A0a | Vendored `edgar_api/documents/llm_client.py` (~412 lines) + `openai>=1.50` in requirements.txt |
| `a9b3e92` | A0b | `extraction.py` swap — `_require_google_api_key` → typed `_require_llm_provider_configured` + `LLMProviderNotConfiguredError` |
| `d2b9334` | A0c | `routes/documents.py` 503 handler + `validate_extraction_schemas.py` + 3 existing test updates |

### 1.2 risk_module worktree `feat/corpus-phase0` (13 commits)

| SHA | Task | Description |
|---|---|---|
| `a0e9d1ff` | A0a | Vendoring parity test + source-side marker |
| `20affd0a` | A1-A4 | Markdown convention doc + frontmatter library (`core/corpus/frontmatter.py`) + paths |
| `789fea6c` | A5 | Per-source section parsers (`core/corpus/section_map.py`) |
| `9d01b741` | A6+A8+B1-B3 | Ingestion stack — `schema.sql`, `db.py`, `types.py`, `supersession.py`, `ingest.py` + transcript writer refactor |
| `ca29994f` | B4a-e | Reconciler — walker + db_sync + orchestrator |
| `126f875a` | C1-C5 | Tool surface — `filings.py`, `transcripts.py`, `search.py`, `edgar_urls.py`, `validation.py`, `mcp_tools/corpus/` |
| `2f7ba461` | D1 | Cross-source merge helper + MCP tool docstrings |
| `da267ba2` | F1 | Migration inventory script |
| `c646a237` | F2 | Migration transform script |
| `e1aea54e` | F3 | Cutover + rollback bash script |
| `dc2e9702` | E1+G1 | Phase 0 canary dataset locked (`CORPUS_PHASE0_CANARY.md`) |
| `9dd2b1bc` | G2 | `corpus_ingest_accession.py` bridge script |
| `<THIS COMMIT>` | Checkpoint | This doc + TODO.md update |

**151 tests passing on worktree at checkpoint time.**

---

## 2. What's been live-validated (G2 smoke)

### 2.1 G2.1 — Migration path (F1 → F2 real run)

Ran F1 inventory + F2 transform against the 4 existing legacy files:
- `Edgar_updater/data/filings/AAPL_10K_2025_d4de4a6e.md`
- `Edgar_updater/data/filings/AAPL_1Q25_transcript_0f8bb74b.md`
- `Edgar_updater/data/filings/AAPL_4Q25_transcript_d3b65636.md`
- `Edgar_updater/data/filings/MSFT_10Q_2025_6f90a2a7.md` (+ duplicate in AI-excel-addin/)

Result: all 4 transformed into `/tmp/corpus_phase0/store/` with `migrated_` document_ids + `extraction_status='orphaned'`. MSFT deduped correctly (edgar source picked over aiexcel). sections_fts populated (AAPL 10-K → 2 sections, MSFT 10-Q → 6, transcripts → 3 each). FTS5 search for `iPhone` returned 2 hits with BM25 ranking.

### 2.2 G2.2 — Fresh extraction (bridge script)

Invoked `scripts/corpus_ingest_accession.py` against the full DUOT 10-Q `0001553350-25-000046`:
- Bridge calls `edgar_parser.tools.get_filings` + `get_filing_sections`
- Synthesizes frontmatter metadata (zero-padded CIK, fiscal period, ISO dates, canonical source URLs)
- Calls `core.corpus.ingest.ingest_raw` → atomic-rename write to canonical path + DB UPSERT

Result: real `document_id: edgar:0001553350-25-000046`, `extraction_status='complete'`, 7 sections parsed matching Edgar_updater's output exactly.

### 2.3 G2 scale smoke (A-lite: AAPL + MSFT + DUOT × 5 filings)

Looped the bridge through 15 canary filings into `/tmp/corpus_canary/filings.db`:

```bash
DB=/tmp/corpus_canary/filings.db ROOT=/tmp/corpus_canary/store
for TICKER in AAPL MSFT DUOT; do
  for SPEC in "2025/4" "2025/3" "2025/2" "2025/1" "2024/3"; do
    YEAR="${SPEC%/*}"; QUARTER="${SPEC#*/}"
    python3 scripts/corpus_ingest_accession.py \
      --ticker "$TICKER" --year "$YEAR" --quarter "$QUARTER" \
      --db "$DB" --corpus-root "$ROOT"
  done
done
```

All 15 succeeded. Every `document_id` matches the locked accession in `CORPUS_PHASE0_CANARY.md`. 10-Ks → 8 sections, 10-Qs → 6 sections, consistent across all three tickers.

**Cross-ticker FTS5 queries verified:**
- `"artificial intelligence"` → top hit DUOT Item 1 Business (microcap explicitly discussing AI), then DUOT MD&A, AAPL Risk Factors, MSFT Legal Proceedings
- `"cloud revenue"` → dominated by MSFT across all 6 top hits (correct sector signal)

### 2.4 MCP surface validation

`mcp_tools/corpus/filings.py` wrappers invoked end-to-end:

- **Envelope contract**: returns all 7 keys — `status`, `applied_filters`, `has_low_confidence_supersession`, `has_superseded_matches`, `hits`, `query_warnings`, `total_matches`
- **Cross-ticker filter**: `filings_search(query='risk factors', universe=['AAPL','MSFT','DUOT'], form_type=['10-Q'])` → 33 matches, correct sorting
- **List API**: `filings_list(ticker='MSFT')` → 5 docs descending by filing_date
- **Invalid input surface**: returns `{status: error, error: <message>}` rather than raising

**I13 validation verified:**
- `limit=0` → rejected with "limit must be >= 1"
- `limit=999` → rejected with "limit exceeds cap 500"
- `universe` with >5000 entries → rejected
- `form_type=['20-F']` → rejected with helpful message listing valid types
- `form_type=[]` → rejected with "must not be empty"

**Gap found** (see §4): lowercase ticker (`universe=['msft']`) passes validation but silently returns zero hits because `documents.ticker` stores canonical uppercase.

---

## 3. What's ephemeral

The G2 smoke DB and corpus store live under `/tmp/` and will be wiped by system reboot. Nothing is persistent outside git.

**Also ephemeral:**
- `/Users/henrychien/Documents/Jupyter/risk_module/exports/file_output/DUOT_1Q25_sections.md` — produced by `get_filing_sections`, persists in the risk_module export dir until cleanup. Other AAPL/MSFT/DUOT section markdowns from the A-lite run are also there.
- `/tmp/corpus_phase0/` (G2.1 migration smoke artifacts)
- `/tmp/corpus_canary/` (G2.2 scale smoke artifacts)

To re-create the smoke state, re-run the loop in §2.3 above — deterministic output.

---

## 4. Known gaps / follow-ups

### 4.1 F40 — I13 validation should reject non-canonical tickers

`core/corpus/validation.py::validate_search_inputs` currently only checks size/length/limit. It doesn't enforce canonical ticker format (uppercase, no whitespace, no colons, no slashes) per `frontmatter.py`'s ticker rules. Lowercase or whitespace-wrapped tickers in `universe` filter pass through and silently miss all docs.

**Fix**: add a ticker-canonicality check in `validate_search_inputs` that mirrors the rules enforced in `core/corpus/frontmatter.py::_validated_metadata` (lines 309-248). Should raise `InvalidInputError` at the boundary, consistent with how other I13 checks behave.

### 4.2 Unlocked canary slots (carried from E1/G1 to G2 kickoff)

These blocked until G2 kickoff per the canary doc §5/§7:

- **Multi-8-K same-day case**: `mcp__edgar-financials__get_filings` tool surfaces at most one 8-K per fiscal quarter; needs direct EDGAR walk for a canary ticker (AAPL 2026-04-20 CEO transition recommended).
- **AAPL + MSFT transcripts**: FMP resolution — use `mcp__fmp-mcp__get_earnings_transcript` for the 2 most recent fiscal periods each. Adds 4 transcript docs to the canary.
- **Synthetic low-confidence amendment**: hand-author against the EQH original (`edgar:0001333986-26-000012`) per canary doc §4.

### 4.3 Full-canary scale (remaining 35 extractions)

After A-lite (AAPL + MSFT + DUOT × 5), these 7 tickers × 5 filings × bridge script remain:
- GOOG, META, BRK-B, JPM, XOM, TGT (primary, each with 10-K + 4 10-Qs per locked accessions)
- EQH (amendment pair — needs manual frontmatter edit for the 10-K/A because the bridge doesn't know about `supersedes` fields yet)

### 4.4 G3 — canary queries

Codify 9 queries from `CORPUS_ARCHITECTURE.md` §13.6 as `tests/canary/test_corpus_canary.py`. Each query has a named acceptance criterion (Q1-Q9 covering cross-ticker, amendment chain, multi-filing disambig, low-confidence gating, etc.). **Blocked on full-canary ingest completion** — some queries need the full 10-ticker set.

### 4.5 G4 — ship signal + convention lock

Final checklist per `CORPUS_IMPL_PLAN.md` §4.G4. If any canary query fails due to convention issue, iterate the convention and re-run canary (Phase 0 can re-extract 10 tickers in <1 hour per the design — bridge script makes this cheap).

### 4.6 F3 cutover not yet executed

The cutover script is committed + tested but has not been run against real paths. Real cutover (legacy → CORPUS_ROOT) is a pre-Phase-1 operational step.

### 4.7 A0 Edgar_updater integration not live-exercised

The A0 A0a/b/c commits on Edgar_updater main changed the structured-extraction pipeline (`extract_filing` with schemas + LangExtract + Anthropic). **G2 uses `get_filing_sections` (deterministic section parsing), not `extract_filing`**, so A0 integration has never run against real filings. A0 is Phase 1 structured-extraction territory, not Phase 0 corpus territory.

---

## 5. How to resume

### 5.1 Fast context recovery

1. Read this doc
2. `cd /Users/henrychien/Documents/Jupyter/risk_module-corpus-phase0`
3. `git log --oneline -15` — confirm head is at or ahead of `<THIS COMMIT>`
4. `pytest tests/test_corpus_*.py tests/test_frontmatter.py tests/test_section_map.py tests/test_reconciler*.py tests/test_filings_tools.py tests/test_transcripts_tools.py tests/test_edgar_urls.py tests/test_mcp_corpus_tools.py tests/test_migration_inventory.py tests/test_migration_transform.py tests/test_migration_cutover.py tests/test_corpus_ingest_accession.py -v` — verify 151 tests pass
5. Re-run §2.3 loop to re-create smoke corpus at `/tmp/corpus_canary/filings.db`

### 5.2 Recommended next action (pick one)

**Option A — scale to full canary (M effort):**
- Extend §2.3 loop over all 10 tickers × 5 filings each
- Add transcript ingest (new bridge variant? or reuse F2 pattern + FMP source)
- Hand-author EQH 10-K/A with `supersedes` frontmatter
- Hand-author synthetic low-confidence file

**Option B — codify G3 canary queries (S effort, blocked on A partially):**
- Create `tests/canary/test_corpus_canary.py`
- Translate §13.6 of arch doc into pytest cases
- Some tests can use the A-lite subset already ingested; others need full 10-ticker set

**Option C — fix F40 I13 lowercase ticker gap (S effort, orthogonal):**
- Plan-first via Codex: tighten `validate_search_inputs` ticker rules
- One-shot, independent of A/B

**Option D — execute F3 cutover (S effort, operational):**
- Run the F3 script against real paths
- Requires operator decision on where `CORPUS_ROOT` symlink lives
- Blocks future `get_filing_sections` output auto-landing in new format

**Recommended order:** C (F40 quick win) → A (full canary) → B (G3 queries) → G4 (ship). D (cutover) can slot anywhere; it's an ops step, not an impl gate.

---

## 6. Key file reference

| Area | File |
|---|---|
| Architecture | `docs/planning/CORPUS_ARCHITECTURE.md` (Codex PASS R7) |
| Impl plan | `docs/planning/CORPUS_IMPL_PLAN.md` (Codex PASS R14) |
| Canary dataset | `docs/planning/CORPUS_PHASE0_CANARY.md` (locked 2026-04-23) |
| Checkpoint | `docs/planning/CORPUS_PHASE0_CHECKPOINT.md` (this doc) |
| Frontmatter library | `core/corpus/frontmatter.py` |
| Ingest primitive | `core/corpus/ingest.py::ingest_raw` |
| DB bootstrap | `core/corpus/db.py::open_corpus_db` |
| Schema | `core/corpus/schema.sql` |
| Tool surface | `core/corpus/filings.py`, `core/corpus/transcripts.py`, `mcp_tools/corpus/` |
| Validation | `core/corpus/validation.py` (F40 lives here) |
| Migration scripts | `scripts/corpus_migration_{inventory,transform,cutover}.{py,sh}` |
| Fresh-extraction bridge | `scripts/corpus_ingest_accession.py` |

---

## 7. Commands cheat-sheet

```bash
# Activate worktree
cd /Users/henrychien/Documents/Jupyter/risk_module-corpus-phase0

# Full regression
pytest tests/test_corpus_*.py tests/test_frontmatter.py tests/test_section_map.py \
  tests/test_reconciler*.py tests/test_filings_tools.py tests/test_transcripts_tools.py \
  tests/test_edgar_urls.py tests/test_mcp_corpus_tools.py tests/test_migration_inventory.py \
  tests/test_migration_transform.py tests/test_migration_cutover.py \
  tests/test_corpus_ingest_accession.py -v

# G2 scale smoke (re-creates /tmp/corpus_canary/)
DB=/tmp/corpus_canary/filings.db ROOT=/tmp/corpus_canary/store
mkdir -p $(dirname "$DB")
for TICKER in AAPL MSFT DUOT; do
  for SPEC in "2025/4" "2025/3" "2025/2" "2025/1" "2024/3"; do
    YEAR="${SPEC%/*}"; QUARTER="${SPEC#*/}"
    python3 scripts/corpus_ingest_accession.py \
      --ticker "$TICKER" --year "$YEAR" --quarter "$QUARTER" \
      --db "$DB" --corpus-root "$ROOT"
  done
done

# Inspect the resulting DB
CORPUS_DB_PATH=/tmp/corpus_canary/filings.db CORPUS_ROOT=/tmp/corpus_canary/store \
  python3 -c "from core.corpus.filings import filings_search; \
    r = filings_search(query='cloud', universe=['MSFT'], limit=3); \
    print(r.total_matches, 'matches')"
```
