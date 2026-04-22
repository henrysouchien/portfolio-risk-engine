# Document Corpus Architecture — Design Doc

**Status:** **Codex-reviewed PASS** after 7 rounds (R1 FAIL → R7 PASS). Architecture is locked. Implementation plan (`CORPUS_IMPL_PLAN.md` or `FILINGS_CORPUS_INDEX_PLAN.md`) can be written against this doc.
**Last updated:** 2026-04-21
**Scope:** Cross-ticker searchable corpus of SEC filings + earnings transcripts + future sources (Quartr decks, press releases, investor letters). Turns per-ticker lookup into agentic search across the universe.

**Codex review history:**
- R1 — FAIL, 3 CRITICAL + 7 MAJOR + 4 MINOR. Added D12-D15, I12-I14; rewrote I2/I3; fixed BM25 sort; closed Q1/Q4/Q11/Q14; recomputed §9 cost; added canary edge cases; split source_url / source_url_deep.
- R2 — FAIL, 2 residual CRITICAL + 5 MAJOR + 3 MINOR. Reframed document_id as source identity (not content identity); specified concurrency + zero-downtime rebuild; added `include_superseded`; renamed D3 tables to `documents`/`sections_fts`; Phase 0 canary includes transcript sample; D15 migration procedure formalized; §9.2 storage recomputed.
- R3 — FAIL, 2 residual CRITICAL + 3 MAJOR + 2 MINOR. Resolved by: switching I2 to UPSERT semantics (was `ON CONFLICT DO NOTHING`); rewriting D6 to remove tuple-based "current" and defer to `documents` row pointer + D13; correcting D14 to accept retroactive `is_superseded_by` metadata update on original at amendment ingestion; propagating `documents`/`sections_fts` naming to §15 "Not started" list; adding deterministic tiebreak rule to I12 reconciler authoritative-file selection; expanding D15 step 7 into reverse-order executable rollback procedure; fixing SearchHit amendment-comment; removing stale "if transcripts included" conditional on canary query 4; adding `has_superseded_matches` hint to §5.4 for false-negative affordance.
- R4 — FAIL, 1 CRITICAL + 3 MAJOR + 2 MINOR. Resolved by: splitting supersession pointers — `supersedes` stays in frontmatter (recorded at ingestion, immutable per I5 once written; R5 later clarified that the value is ingestion-derived rather than source-intrinsic), `is_superseded_by` becomes a **DB-only derived column** rebuildable from `supersedes` across all docs (closes I1/I5/D14 contradiction); updating D6 to surface ambiguity via `AmbiguousDocumentError` instead of silent ORDER BY LIMIT 1 pick; committing D15 to env-var-with-symlink cutover mechanism + explicit rollback triggers (Phase 0 acceptance, divergent-hash threshold, 24h query-failure); wrapping search results in `SearchResponse` envelope (carries `hits` + `has_superseded_matches` + `applied_filters` + `total_matches` + `query_warnings`); fixing terminology note + Q3 to use `documents` table; adding malformed-value fallthrough to I12 tiebreak rule.
- R5 — FAIL, 1 CRITICAL + 1 MAJOR + 1 MINOR. Resolved by: reframing `supersedes` as **ingestion-derived** (not source-intrinsic — SEC amendment filings identify the original via narrative text, not structured metadata) with provenance fields (`supersedes_source`, `supersedes_confidence`) added to frontmatter; adopting a **deterministic scalar rule** for multi-amendment `is_superseded_by` derivation (most-recent `filing_date` wins, tiebreak on lex-greater `document_id`) used identically by ingestion-time updates and I12 reconciler recomputation, guaranteeing convergence from disk alone; fixing §5.4 no-match wording to reflect the `SearchResponse` envelope instead of a bare empty list.
- R6 — FAIL, 1 BLOCKING + 1 MINOR. Resolved by: gating `is_superseded_by` derivation on `supersedes_confidence = 'high'` (low/medium-confidence supersession links do NOT hide originals from default search); adding `has_low_confidence_supersession` hint to `SearchResponse` + `SearchHit` so agent/UI can render caveats or opt-in retry; adding `include_low_confidence_supersession` parameter to both search signatures; promoting low→high confidence flows through normal re-extraction per D14; cleaning up stale "intrinsic" phrasing in R4 history entry + I1.
- **R7 — PASS.** No remaining design-level blocker. Non-blocking spec-edge (content_hash = full-file including frontmatter) folded into D6. Test-plan gap (low-confidence gating canary) added as canary query 9 in §13.6. Codex-identified top implementation-plan risks carried forward: (1) content_hash scope = full-file hash; (2) shared search predicate across both families for all supersession params/flags; (3) low-confidence canary test coverage; (4) manual override tooling must emit new immutable file, not mutate in place; (5) historical file retention/GC policy because citation durability depends on old hash-addressed files surviving canonical-pointer moves.
- **Post-R7 touch-up (2026-04-21):** added Q15 tracking where §7.5's "output validation" lives (agent self-check / post-gen middleware / gateway citation provider / UI render gate) with a layered-defense lean. §7.5 pointed at Q15 so readers don't mistake the validator for solved-elsewhere. Identified during a conversational gap-review, not a Codex round — non-blocking but load-bearing for production trust.

**Maps to:** TODO V2.P1 (Filings corpus FTS5 index — expanded scope covers transcripts + future sources), V2.P2 (Citation-first filing Q&A), V2.P8 (Quartr integration). BETA_RELEASE_GAP_AUDIT T2.2 (NL screener), T2.6 (RAG-vs-agentic decision).

**Terminology note:** "The corpus" is the umbrella multi-source document store. Per-source tool families (`filings_*`, `transcripts_*`, future `decks_*`) are thin wrappers over a single unified FTS5 index (D3). Cross-source queries use parallel per-source calls with agent-side merge (§5.2). Internal SQLite table names are `documents` (document-grain metadata) and `sections_fts` (section-grain FTS5 virtual table) per D3/D12. The SQLite file itself retains the legacy filename `filings.db` and the filesystem root is `data/filings/` — renamed only if it becomes confusing, not as part of V2.P1.

**References:**
- `docs/research/fintool/architecture-learnings.md` — Fintool's documented path from 500GB Elasticsearch to grep-over-filesystem
- `docs/planning/BETA_RELEASE_GAP_AUDIT.md` — T2.2, T2.6
- `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` — companion doc (research workspace uses the same "filesystem is truth" principle)
- `Edgar_updater/` — existing canonicalization pipeline (filings + transcripts → markdown)
- `edgar-mcp/` — existing MCP tool surface (currently stateless API proxy)

---

## 1. Problem & Goal

### The gap

Today's filing and transcript access is **per-ticker and live-fetched**:

- `get_filings(ticker)` → EDGAR metadata
- `get_filing_sections(ticker, form)` → narrative sections of one filing
- `get_earnings_transcript(ticker, year, quarter)` → one transcript
- `extract_filing_file()` → structured extraction for one filing

There is no way to ask *"which tech companies are discussing AI capex?"* or *"where in my universe is credit-quality language deteriorating?"* The agent would have to iterate ticker-by-ticker through thousands of entities — infeasible.

### The wedge

Cross-corpus semantic/keyword retrieval is Fintool's documented primary advantage over general-purpose LLM products: *"Which tech companies are discussing increasing capex for AI initiatives?"* run against 8,000 companies in under a minute. Our quantitative 7-signal screener is different — numeric filters, not language-over-corpus. This is the gap V2.P1 closes.

### Definition of done

An agent can issue a natural-language query against the filings + transcripts corpus for 1,500+ tickers and receive ranked, citable passages within seconds. From those, it can open specific filings, navigate sections, compare language across companies, and synthesize an answer with grounded citations.

### Non-goals (out of scope for this document)

- Vector databases / embeddings (explicitly rejected — see §11)
- Real-time (sub-minute) ingestion SLAs
- Per-user private corpora (filings are public; user watchlists drive ingestion priority, not access control)
- Non-English filings
- Full-text search over structured financial data (XBRL facts are a separate retrieval problem, already served by `get_metric`)

---

## 2. Architectural Bet

Four principles, one sentence each:

1. **Normalize every source to markdown-on-disk.** Filings, transcripts, decks — all canonicalized into a shared markdown convention with YAML frontmatter and canonical section headers. One format for the agent to read.
2. **Derive a section-grain search index from the filesystem.** A single SQLite database has a document-grain metadata table (one row per canonicalized document) and a section-grain FTS5 virtual table (one row per canonical section within a document). The index is **disposable** — rebuildable from disk in minutes.
3. **The agent orchestrates retrieval + navigation.** FTS5 narrows the corpus to ranked section-level candidates (fast, server-side). The agent then reads specific markdown files for reasoning context (slow, LLM-driven). Two modes, one agent.
4. **Corpus serves narrative; structured tools serve numbers; ticker is the shared key.** The corpus covers *what was said* (language in filings, transcripts, decks). Existing structured tools (`get_metric`, `get_metric_series`, `get_institutional_ownership`, `get_insider_trades`, `screen_stocks`, `compare_peers`, `model_build`, etc.) cover *what the numbers say*. The agent composes them via canonical ticker — no translation layer, no duplicate ingestion of structured data into the corpus.

### Why this shape

- **Markdown is the universal format.** LLMs reason well over it. Humans read it. Sources are fungible — any new source becomes a new converter producing the same format. No downstream changes.
- **The filesystem is the source of truth.** It's the thing that takes real extraction work to produce. Everything else (metadata, FTS5, query tool) is a cheap derivation. Corrupted index? Delete, rebuild. Schema change? Rerun extraction on the subset that needs it.
- **FTS5 earns its keep at scale.** Grep over 20,000 markdown files is slow and unranked. FTS5 gives you indexed search + BM25 ranking + metadata filters in ~10ms per query. Zero infra — it's stdlib SQLite. The RAG Obituary argued against *vector* DBs, not against *any* index — it argued for keeping retrieval simple. FTS5 is the simplest retrieval that handles "which tech companies discuss AI capex?" with ranking.
- **Agentic navigation is what the model is good at.** Once FTS5 returns 20 ranked candidates, the agent can read, grep, compare, and iterate — the operations frontier models handle natively.
- **Composition is natural when keys align.** FTS5 returns tickers; structured tools consume tickers; code execution manipulates typed outputs from both. The agent chains them without impedance mismatch as long as canonical-ticker conventions hold across surfaces — see §4.6 and §6.5.

### What we're explicitly *not* doing

- **No vector database / embeddings.** See Locked Decision D2. Fintool tore out 500GB of Elasticsearch + embeddings to do this; we're not building what they tore out.
- **No Elasticsearch / managed search service.** SQLite FTS5 ships with Python. No new infrastructure.
- **No reranker.** BM25 + LLM reading is sufficient for our query volume and universe size.
- **No vector-DB-style chunking.** Retrieval grain follows the canonical markdown section structure — not embedding-driven splits, not sliding windows. Sections are natural units because the extraction pipeline already canonicalizes headers (§4.3-4.4). One FTS5 row per section; the agent picks which sections to read at navigation time. See D12.

### Fintool parallels (inferred — product post-acquisition, details from our research corpus)

Per `docs/research/fintool/architecture-learnings.md`:

- **Three canonical formats** for every source: markdown for narrative, CSV/tables for structured data, JSON metadata per doc. *"LLMs are surprisingly good at reasoning over markdown tables. But they're terrible at reasoning over HTML `<table>` tags or raw CSV dumps."* We adopt the same normalization (YAML instead of JSON metadata — same semantics, fits markdown frontmatter convention).
- **Post-retrieval pivot to filesystem + grep + frontier context.** *"For a 100K-line codebase: Elasticsearch takes minutes to index, ripgrep searches in milliseconds."* We adopt this for the *navigation* layer but retain a lightweight FTS5 index for *retrieval* (see §6 for why both).
- **Skills as markdown files with YAML frontmatter, SQL-discoverable.** Our corpus artifacts follow the same pattern — the *content* happens to be filings/transcripts, but the file format is identical to how Fintool structures analyst skills.
- **Citations first-class, missing/malformed citations block render.** We inherit this norm: every passage returned from the query surface carries `file_path + section` (ideally + char offsets, see Open Question Q7).

The differences: our universe is smaller (1,500 tickers vs 8,000), our ingestion cadence is more relaxed (nightly vs sub-minute), and we have no paid-customer-trust constraints pushing us toward 500GB Elasticsearch parity. We can be leaner.

---

## 3. Layers

```
┌───────────────────────────────────────────────────────────────────┐
│  Layer 5 — Agent                                                  │
│  Issues queries, reads files, iterates, synthesizes with citations│
└───────────────────────────────────────────────────────────────────┘
                              ▲
                              │ MCP tool calls
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│  Layer 4 — Query Surface (MCP)                                    │
│  {family}_search → ranked section passages + file_path + doc_id  │
│  {family}_read → markdown content (doc / section / byte range)   │
│  {family}_source_excerpt → verbatim text from authoritative src  │
└───────────────────────────────────────────────────────────────────┘
                              ▲
                              │ SQL
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│  Layer 3 — SQLite Index (derived, disposable)                     │
│  documents table (one row per doc; doc_id PK; is_superseded_by)   │
│  sections_fts virtual table (one row per section; FTS5 indexed)   │
└───────────────────────────────────────────────────────────────────┘
                              ▲
                              │ rebuild from disk (reconciler)
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│  Layer 2 — Canonicalized Markdown (source of truth)               │
│  data/filings/{source}/{ticker}/{form}_{period}_{hash}.md         │
│  YAML frontmatter carries document_id; body has canonical sections│
└───────────────────────────────────────────────────────────────────┘
                              ▲
                              │ canonicalization (LLM extraction)
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│  Layer 1 — Raw Sources                                            │
│  EDGAR filings (HTML/XBRL), FMP transcripts (JSON),                │
│  Quartr decks (PDF, future), etc.                                 │
└───────────────────────────────────────────────────────────────────┘
```

**Direction of authority:** lower layers are authoritative over higher ones. Layer 2 (markdown) is the source of truth. Layer 3 (SQLite) is disposable and rebuildable from Layer 2. Layers 4-5 read from 3 and 2 — they never write.

**Direction of data flow:** Layer 1 → Layer 2 happens during ingestion (LLM-heavy, costly, infrequent). Layer 2 → Layer 3 happens during index rebuild, which is continuous (per-ingestion inserts) and periodic (reconciler walks disk to repair drift) — see D14. Layers 3-5 serve read traffic.

---

## 4. Data Contracts

This is the most important section. The markdown convention is the project-wide contract — changing it later means re-running extraction against the whole corpus.

### 4.1 Directory layout

```
data/filings/                              # repo-relative (or absolute via env var)
├── edgar/                                 # one subdirectory per source
│   ├── AAPL/
│   │   ├── 10-K_2025-FY_{hash}.md
│   │   ├── 10-Q_2025-Q3_{hash}.md
│   │   └── 8-K_2025-02-14_{hash}.md
│   └── MSFT/
│       └── ...
├── fmp_transcripts/
│   ├── AAPL/
│   │   ├── transcript_2025-Q1_{hash}.md
│   │   └── transcript_2025-Q4_{hash}.md
│   └── MSFT/
│       └── ...
└── quartr/                                # future
    └── ...
```

**Principles:**

- **Source subdirectory** — every source gets its own top-level directory. Keeps provenance explicit and lets sources be added/removed atomically.
- **Ticker subdirectory** — enables fast ticker-scoped `glob()` without hitting the index.
- **Content-addressable filename** — `{form}_{period}_{hash}.md` where `hash` is a short (e.g. 8-char) hash of the canonical content. Immutable: content change produces a new file, never an overwrite.
- **Current state:** Edgar_updater today produces `{TICKER}_{FORM}_{YEAR}_{HASH}.md` flat (no ticker subdirectory). Migration is trivial — shell move + metadata rewrite.

### 4.2 YAML frontmatter schema

Every markdown file leads with a YAML frontmatter block carrying structured metadata. This is what the metadata table is populated from — the filesystem remains the source of truth.

```yaml
---
# identity
document_id: edgar:0000789019-25-000073    # immutable; primary key across frontmatter, metadata, citations
ticker: MSFT
cik: "0000789019"
company_name: Microsoft Corporation

# document
source: edgar                    # edgar | fmp_transcripts | quartr
form_type: 10-K                  # 10-K | 10-Q | 8-K | TRANSCRIPT | DECK | ...
fiscal_period: 2025-FY           # canonical: YYYY-FY | YYYY-QN | YYYY-MM-DD
filing_date: 2025-07-30
period_end: 2025-06-30

# provenance
source_url: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000789019&type=10-K&dateb=&owner=include&count=40    # stable landing page
source_url_deep: https://www.sec.gov/Archives/edgar/data/789019/000078901925000073/msft-20250630.htm    # optional primary document
source_accession: 0000789019-25-000073
extraction_pipeline: edgar_updater@0.4.2
extraction_model: gemini-2.5-flash
extraction_at: 2025-08-01T02:13:44Z
content_hash: a3f9b211

# amendment / supersession (optional)
# Note: `supersedes` is INGESTION-DERIVED, not source-intrinsic. SEC amendment
# filings do not carry structured "this amends accession X" metadata — the link
# is narrative in the filing text. The ingestion pipeline derives it (heuristic
# on form_type + fiscal_period + filer CIK, or LLM extraction of the amendment's
# explanatory note), records the result + provenance in frontmatter, and then
# the written frontmatter becomes immutable per I5. Re-extraction with an
# improved linker produces a new file (new content_hash) carrying a corrected
# `supersedes` — same mechanism as any other re-extraction correction.
#
# The inverse pointer `is_superseded_by` is DB-only, derived from `supersedes`
# across all documents at ingestion + reconciler time. See D13, I1, D14
# "Amendment supersession," and the deterministic rule in D14 for multi-amendment
# convergence.
supersedes: null                 # document_id this filing amends, or null
supersedes_source: null          # 'sec_header' | 'heuristic' | 'llm_extraction' | 'manual' — provenance of the link
supersedes_confidence: null      # 'high' | 'medium' | 'low' — ingestion's confidence in the link; flagged for review if low

# classification (optional, filled when available)
sector: Technology               # GICS taxonomy (Q14 resolved → §4.6)
industry: Systems Software
sector_source: GICS              # taxonomy identifier — 'GICS' | 'SIC' | 'proprietary' | ...; enables traceback if reconciliation needed later
exchange: NASDAQ
---
```

**Rules:**
- All keys present-or-absent per schema; no free-form extension without schema update.
- `document_id` is **source identity**, not content identity. It is the immutable canonical ID of the underlying source document and the primary key for citations, verification calls, and cross-references. For SEC filings this is `edgar:<accession>`; for FMP transcripts it is `fmp_transcripts:<ticker>_<YYYY-QN>`; for future sources, source-specific canonical IDs. Re-extraction of the **same source** (new extraction pipeline, bug fix, better model) updates the documents row's `content_hash` and `file_path` in place; the `document_id` is stable. A **different source** (amendment, re-filing, new accession) gets a new `document_id` and its own row.
- `fiscal_period` is canonical ISO-like — fiscal calendar normalization happens at ingestion (see V2.P7 cross-reference).
- `content_hash` matches the suffix in the filename and is used for dedup + delta detection *within* a document_id (e.g., re-extraction with a new model produces a new content_hash but preserves document_id).
- `source_url` is the stable landing page for the document (SEC company filing index for EDGAR; transcript landing for FMP). `source_url_deep` is the optional direct link to the primary document HTML/PDF — preferred when stable, falls back to `source_url` when not.
- `supersedes` is the **only** supersession pointer in frontmatter. It is **ingestion-derived, not source-intrinsic** — SEC amendment filings identify the document they amend via narrative text, not structured metadata. The ingestion pipeline derives the link (via heuristic match on filer CIK + form_type + fiscal_period, or LLM extraction of the amendment's explanatory note), records it with provenance fields (`supersedes_source`, `supersedes_confidence`), and then the written frontmatter is immutable per I5. Corrections to the derivation flow through normal re-extraction (new file, new content_hash, updated row pointer per D14). `is_superseded_by` is a **DB-only derived column** on the `documents` table, computed from all documents' `supersedes` pointers at ingestion/reconciler time using a deterministic scalar rule (D14). This split preserves I1 (filesystem sufficient to reconstruct all relationships) AND I5 (file immutability). Queries that want "current" filter on `is_superseded_by IS NULL`. Amendments (10-K/A, 8-K/A) live in the index as first-class documents, never as overwrites. Low-confidence supersession links are flagged for ops review rather than silently accepted.
- Missing optional fields are tolerated — the metadata table has nullable columns for them.

### 4.3 Section taxonomy — filings

Filings use `## SECTION: {canonical header}` as the level-2 heading pattern. Canonical headers are locked per form type.

**10-K canonical sections** (inherits `Edgar_updater`'s `_CANONICAL_HEADERS`):

```
## SECTION: Item 1. Business
## SECTION: Item 1A. Risk Factors
## SECTION: Item 1B. Unresolved Staff Comments
## SECTION: Item 2. Properties
## SECTION: Item 3. Legal Proceedings
## SECTION: Item 5. Market for Registrant's Common Equity
## SECTION: Item 7. Management's Discussion and Analysis
## SECTION: Item 7A. Quantitative and Qualitative Disclosures About Market Risk
## SECTION: Item 8. Financial Statements and Supplementary Data
## SECTION: Item 9A. Controls and Procedures
```

**10-Q canonical sections:**

```
## SECTION: Item 1. Financial Statements
## SECTION: Item 2. Management's Discussion and Analysis
## SECTION: Item 3. Quantitative and Qualitative Disclosures About Market Risk
## SECTION: Item 4. Controls and Procedures
## SECTION: Part II, Item 1A. Risk Factors
```

**8-K canonical sections:** Item-specific (Item 1.01, Item 2.02, Item 5.02, etc.) — the filing typically has 1-2 items, each a section.

**Rules:**
- Missing sections are omitted, not stubbed. A 10-K with no Item 1B section simply has no `## SECTION: Item 1B.` heading.
- Section bodies preserve tables as markdown tables (already done by `Edgar_updater.section_parser.py:table_to_markdown()`).
- Cross-section references are preserved as inline markdown links if they appear in the source.

### 4.4 Section taxonomy — transcripts

Transcripts use a different but equally canonical structure:

```markdown
## PREPARED REMARKS

### SPEAKER: Satya Nadella (CEO)
Good afternoon and thank you for joining us...

### SPEAKER: Amy Hood (CFO)
Thank you, Satya. Revenue for the quarter...

## Q&A SESSION

### SPEAKER: [Analyst Name] ([Firm])
Q: Can you walk through the Copilot monetization ramp?

### SPEAKER: Satya Nadella (CEO)
A: Yes...
```

**Rules:**
- Two top-level sections always: `## PREPARED REMARKS` and `## Q&A SESSION`.
- Each speaker turn is a `### SPEAKER: {Name} ({Role})` heading. This becomes queryable via FTS5 metadata (e.g., filter to CEO turns only).
- `Q:` / `A:` inline prefixes are optional — heuristic, Q&A structure is already implied by parent `## Q&A SESSION`.

**Current state:** Edgar_updater today writes `> Date: {YYYY-MM-DD}` as a blockquote instead of YAML frontmatter. Migrating to YAML frontmatter is part of V2.P1's first step.

### 4.5 Extension pattern — adding a new source

Adding Quartr decks or any future source requires:

1. **Write a converter** — input format → canonical markdown with frontmatter + section taxonomy (invent a section taxonomy for the new form type).
2. **Register a new `source` value** — e.g., `source: quartr_deck`.
3. **Add to the ingestion scheduler** — point at the new source.

No changes to:
- The metadata table (nullable columns already accommodate missing fields)
- The FTS5 index (indexes text; doesn't care about source)
- The query tool surface (filters on `source` and `form_type`)
- The agent (reads markdown)

This is the key payoff of the design. Quartr decks flow in by writing one converter; the rest of the stack is untouched.

### 4.6 Canonical keys across surfaces

The corpus composes with structured tools (XBRL facts, fund ownership, insider trades, market data) via shared keys. For that composition to work without translation layers, keys and metadata conventions must be aligned across all surfaces.

**Document identity key — `document_id`.** Every corpus document has an immutable `document_id` (D13). For SEC filings this is `edgar:<accession>`; for FMP transcripts it is `fmp_transcripts:<ticker>_<YYYY-QN>`; future sources get their own canonical prefix. `document_id` is the primary key for the documents metadata table, the anchor for citations, and the key all `*_source_excerpt` tools accept. `(ticker, form_type, fiscal_period)` is **not** sufficient — amendments (10-K/A), same-day multiple 8-Ks, and re-filings make that tuple non-unique. `document_id` disambiguates by construction.

**Primary composition key — canonical ticker.** The ticker is the universal join between the corpus and structured tools. Corpus frontmatter `ticker`, `SearchHit.ticker`, and structured-tool inputs all use the canonical form returned by `SymbolResolver.resolve_identity()` (see `core.security_identity`, committed `1b5917cb`). This already handles:

- Share-class variants (GOOG/GOOGL, BRK.A/BRK.B)
- International listings and MIC codes (AT. vs AT.L)
- Historical tickers (FB → META, TWTR → X)
- Exchange prefixes and case normalization
- Cash / non-equity forms (`CUR:USD`)

The corpus inherits `SymbolResolver`; it does not reinvent ticker canonicalization.

**Secondary key — CIK.** SEC's Central Index Key is EDGAR's stable identifier. It survives ticker migrations (META's pre-2022 filings still live under Facebook's CIK). Frontmatter carries `cik`; the agent can cross-reference via CIK when ticker-based joins would miss historical filings.

**Fiscal period normalization.** This is the hard one. *Apple Q1 ≠ Microsoft Q1 ≠ calendar Q1.* If the corpus returns `fiscal_period: 2024-Q1` and a structured tool returns calendar Q1 capex, the numbers are a quarter off. Frontmatter canonicalizes to `YYYY-FY` or `YYYY-QN` based on the filing's own fiscal calendar metadata — but cross-company normalization requires **V2.P7 (Fiscal calendar normalization DB)**, currently deferred in the TODO. This is a hard prerequisite for composition patterns that join on period (see §6.5 Pattern 2/3). Pattern 1 (text-first, structured-later with per-ticker queries) works without it.

**Sector / industry taxonomy.** FMP, EDGAR, and portfolio tools variously use GICS, SIC, and proprietary classifications. If the agent filters "tech companies" in the corpus (via `sector='Technology'` metadata), it must use the same taxonomy downstream. Frontmatter commits to GICS (see Open Question Q14 for rationale + alternatives).

**Document identifiers.** Aligned by construction: `source_accession` matches SEC's canonical filing ID, `content_hash` is our own, Quartr deck IDs pass through untouched. Filings round-trip between corpus metadata and external sources via accession number.

**Invariant (implicit — made explicit as I11 in §10):** any tool that returns tickers or accepts tickers uses canonical form. Tools that need alternative forms internally (e.g., `edgar-financials` wants CIK for some endpoints) convert at their own boundary, never exposing the non-canonical form to the agent or to code execution. This is how composition stays clean.

---

## 5. Query Surface

### 5.1 Per-source tool families over a unified index

Each content source has its own tool family — `filings_*` for SEC filings, `transcripts_*` for earnings calls, future `decks_*` for Quartr decks, and so on. All families share the same four-tool shape: **search** (retrieval), **read** (navigation of our summarized markdown), **source_excerpt** (verification against the authoritative original), and **list** (metadata discovery). Every tool is a thin wrapper over the single unified FTS5 index — form-type filtering is preset per family, so the agent doesn't specify it.

This shape is what keeps the agent's mental model clean: *"filings live here, transcripts live here, they behave the same, and the corpus is the union."* The agent picks the family based on intent; the underlying index handles the rest.

#### Filings family — SEC 10-K, 10-Q, 8-K, proxy statements

```python
def filings_search(
    query: str,                            # FTS5 MATCH expression
    universe: list[str] | None = None,     # ticker list; default: full corpus
    sector: str | None = None,
    form_type: list[str] | None = None,    # narrow within family (default: all filings)
    date_from: str | None = None,
    date_to: str | None = None,
    include_superseded: bool = False,      # default: filter out documents with is_superseded_by set (high-confidence amendments only per D14)
    include_low_confidence_supersession: bool = False,  # default: low/medium-confidence supersession links do NOT hide originals; set True to treat them as current-hiding
    limit: int = 20,
) -> SearchResponse:
    """Ranked section-grain passages from SEC filings corpus."""

def filings_read(
    file_path: str,
    section: str | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
) -> str:
    """Markdown content from our filings corpus — full file, section, or byte range.
    For verbatim source text, use filings_source_excerpt."""

def filings_source_excerpt(
    document_id: str,                      # preferred: immutable doc identity ('edgar:<accession>')
    section: str | None = None,
    # Convenience overload (deprecated; errors on ambiguity):
    ticker: str | None = None,
    form_type: str | None = None,          # '10-K', '10-Q', '8-K', ...
    fiscal_period: str | None = None,
) -> str:
    """Verbatim text from the original EDGAR filing — not our summary.
    Backed by edgar-financials.get_filing_sections().

    Primary signature takes document_id (immutable). The (ticker, form_type,
    fiscal_period) convenience signature resolves to the latest non-superseded
    document; errors with AmbiguousDocumentError if multiple non-superseded
    matches exist (same-day 8-Ks, concurrent amendments)."""

def filings_list(
    ticker: str | None = None,
    form_type: list[str] | None = None,
    fiscal_period: str | None = None,
) -> list[FilingMetadata]:
    """Metadata rows — 'what filings do we have for MSFT?'"""
```

#### Transcripts family — earnings calls (FMP today, Quartr eventually)

```python
def transcripts_search(
    query: str,
    universe: list[str] | None = None,
    speaker_role: str | None = None,       # 'CEO', 'CFO', 'Analyst' — filter speaker turns
    section: Literal['prepared_remarks', 'qa', 'both'] = 'both',
    date_from: str | None = None,
    date_to: str | None = None,
    include_superseded: bool = False,      # rare for transcripts but supported for consistency
    include_low_confidence_supersession: bool = False,  # rarely relevant for transcripts; supported for consistency
    limit: int = 20,
) -> SearchResponse:
    """Ranked speaker-turn passages from earnings call transcripts."""

def transcripts_read(
    file_path: str,
    section: Literal['prepared_remarks', 'qa', None] = None,
    speaker: str | None = None,            # return only this speaker's turns
    char_start: int | None = None,
    char_end: int | None = None,
) -> str:
    """Markdown content from our transcripts corpus."""

def transcripts_source_excerpt(
    document_id: str,                      # preferred: 'fmp_transcripts:<ticker>_<period>'
    speaker: str | None = None,
    # Convenience overload:
    ticker: str | None = None,
    fiscal_period: str | None = None,      # 'YYYY-QN' (e.g., '2025-Q1')
) -> str:
    """Verbatim transcript text from the original source — not our summary.
    Backed by fmp-mcp.get_earnings_transcript() today; Quartr fetcher later.

    Primary signature takes document_id. Convenience (ticker, fiscal_period)
    works because transcripts rarely have multiple variants per quarter, but
    errors on ambiguity if Quartr + FMP both have the same call."""

def transcripts_list(
    ticker: str | None = None,
    fiscal_period: str | None = None,
) -> list[TranscriptMetadata]:
    """Metadata rows — 'what earnings calls do we have for MSFT?'"""
```

#### Shared return envelope — `SearchResponse`

Every `*_search` tool returns a typed `SearchResponse` envelope (not a bare list), so response-level metadata (hints, applied filters, total counts) has a defined place:

```python
@dataclass
class SearchResponse:
    hits: list[SearchHit]                  # ranked per-section hits (may be empty)
    applied_filters: dict                  # echoed query/filters for agent introspection
    total_matches: int                     # count before `limit` was applied
    has_superseded_matches: bool           # §5.4 false-negative hint: True if the filter
                                           # (include_superseded=False by default) excluded
                                           # hits that would have matched. Agent can retry
                                           # with include_superseded=True.
    has_low_confidence_supersession: bool  # True if any returned hit has a low/medium-confidence
                                           # supersedes link pointing at it (D14). Original is
                                           # still visible in default search; agent/UI may want
                                           # to render a caveat or retry with
                                           # include_low_confidence_supersession=True.
    query_warnings: list[str]              # e.g., "extraction_status=partial documents found"
```

Typical agent code: `hits = filings_search(query=..., limit=20).hits` for the common case; inspect `.has_superseded_matches` when results look sparse.

#### Shared hit type — `SearchHit`

Each `SearchResponse.hits` entry identifies a **section within a document** (D12 locks section grain):

```python
@dataclass
class SearchHit:
    # Document identity — immutable per source document; re-extraction preserves document_id,
    # amendments produce a new document_id (with supersedes pointer back to the original).
    document_id: str                       # 'edgar:<accession>' | 'fmp_transcripts:<ticker>_<period>' | ...
    ticker: str
    company_name: str
    source: str                            # 'edgar' | 'fmp_transcripts' | 'quartr' | ...
    form_type: str                         # '10-K' | '10-Q' | 'TRANSCRIPT' | 'DECK' | ...
    fiscal_period: str
    filing_date: str
    is_superseded: bool                    # true if a later high-confidence amendment exists; filter-out by default (D14)
    has_low_confidence_supersession: bool  # true if a low/medium-confidence supersedes link targets THIS doc (does NOT drive is_superseded); agent/UI may render caveat
    # Section-level hit data
    section: str                           # e.g. "Item 7. Management's Discussion and Analysis" or "Q&A — Satya Nadella"
    snippet: str                           # FTS5-generated snippet with match highlights
    file_path: str                         # absolute path to our markdown (document-level)
    char_start: int                        # section start offset in the file
    char_end: int                          # section end offset in the file
    # Authoritative source locators
    source_url: str                        # stable landing page (SEC company filing index, FMP transcript landing, ...)
    source_url_deep: str | None            # optional direct link to primary HTML/PDF
    source_accession: str | None           # SEC accession; NULL for non-SEC
    # Ranking
    rank: float                            # BM25 score from SQLite FTS5 — SMALLER IS BETTER (see §5.2)
```

#### Future sources

Adding Quartr decks = new `decks_search` / `decks_read` / `decks_source_excerpt` / `decks_list` family. Same shape, same return type, same underlying index. Investor letters and press releases would follow the same pattern when added.

### 5.2 Cross-source queries via parallel calls + merge

Some queries span sources — *"everything MSFT said about Copilot across filings and earnings calls"*, or *"where has BRK.B discussed capital allocation"*. The pattern: **parallel per-source calls, merge client-side by BM25 rank.**

```python
f_resp = filings_search(query='Copilot', universe=['MSFT'], date_from='2023-01-01', limit=30)
t_resp = transcripts_search(query='Copilot', universe=['MSFT'], date_from='2023-01-01', limit=30)
# SQLite FTS5 bm25() returns scores where SMALLER IS BETTER (most negative = most relevant).
# Sort ASCENDING to put best hits first.
merged = sorted(f_resp.hits + t_resp.hits, key=lambda h: h.rank)[:50]
# Single ranked list spanning both sources
# Inspect `f_resp.has_superseded_matches` / `t_resp.has_superseded_matches` if the
# merged list looks sparse — agent may want to retry with include_superseded=True.
```

**Why this works cleanly:** all tool families hit the same FTS5 index, so BM25 scores use identical global stats (IDF, avgdl). A filing hit at rank -7.2 and a transcript hit at rank -5.1 are directly comparable — *more negative is better* per SQLite's `bm25()` convention. The merge is a one-line ascending sort, not a heuristic re-ranking problem.

**Important — the comparability claim is conditional.** Scores are comparable across parallel calls only when: (a) the same MATCH query text is used (phrase boundary changes, operators, or weight tweaks invalidate comparability); (b) the per-family ranking function is identical (default `bm25()` with no custom column weights); (c) the FTS5 row grain matches (section-grain everywhere — D12). Violating any of these means scores come from different distributions and a pure rank-sort becomes a heuristic. The implementation must keep rank semantics consistent across families or document exceptions.

**Why no unified `corpus_search` tool:** fewer tools = less agent confusion and better prompt-cache hit rate (V2.P5). Cross-source is ~20-30% of queries; optimizing the tool surface for the common case (scoped-to-one-source) is the right priority. Cross-source pays a small tax (two calls + one sort); scoped queries pay no tax. The decision to span sources is made *explicit* by calling both tools, not masked behind a single tool. If agent usage later shows merging is a real struggle, a unified tool can be added additively.

### 5.3 Why this shape — three modes per source, per-source families over unified index

**The three modes per family** (search / read / source_excerpt) cover distinct cost+semantic profiles:

- **search** — retrieval. Narrows corpus to ranked snippets. Cheap, snippet-sized.
- **read** — navigation. Reads our summarized markdown for reasoning context. Moderate cost.
- **source_excerpt** — verification. Fetches verbatim text from the authoritative original. Higher latency (external API), used when precision matters.

A single combined tool per family would push mode decisions onto the caller. Keeping the three modes separate forces the agent to think in the right mode for each call, keeps token usage honest, and makes the cost profile of each action legible. It also mirrors the trust architecture: our markdown is an *index* into the corpus; the source is the *ground truth* (see §7).

**Per-source families** over a unified index give two wins at once: clear agent-facing naming (no overloaded `form_type=[...]`), and cross-source queries that merge cleanly because scores are comparable. If we went the opposite way (one overloaded tool), cross-source queries would be natural but the tool surface would obscure what's being queried. Per-source families surface intent.

### 5.4 Error modes

- **Malformed FTS5 query** → return structured error with query-syntax hint.
- **Input limit violation** → query string > max length, universe > max size, limit > cap, or path outside canonical root → structured `InvalidInputError` with the specific bound violated. See I13.
- **No matches** → return an empty `SearchResponse` with `hits=[]`; `applied_filters` and `has_superseded_matches` remain populated so the agent can decide whether to relax filters or retry with `include_superseded=True`.
- **File not on disk** → return metadata-table-says-it-exists error (index/filesystem drift; reconciler will heal on next pass).
- **Extraction incomplete** → if metadata flags `extraction_status: partial`, include a warning in the result.
- **Source not yet ingested** → `*_search` returns empty; agent can fall back to live-fetch via underlying MCP (`edgar-financials`, `fmp-mcp`) and note the corpus gap.
- **Ambiguous document key** (`*_source_excerpt` convenience overload) → `AmbiguousDocumentError` with list of matching `document_id`s. Happens when `(ticker, form_type, fiscal_period)` matches multiple non-superseded documents (e.g., same-day 8-Ks, concurrent amendments). Agent re-calls with explicit `document_id`.
- **Superseded document** → by default `*_search` filters out superseded documents (`is_superseded_by IS NULL`). Agent can opt into historical results via `include_superseded=True` for amendment-diff queries.
- **Superseded-only false negative** → when the query would match only superseded documents, the default-filtered response returns an empty result set with a structured `has_superseded_matches` hint in the response metadata indicating that retrying with `include_superseded=True` would produce hits. This prevents the agent from reporting "no matches found" when the information exists but is in amended / re-filed documents. Agent behavior (§6.2) should retry with the flag when the hint is set and the query is historically-significant (e.g., pre-amendment language evolution).

---

## 6. Agent Behavior

The query surface alone isn't enough — the agent has to use it in the right pattern. This section describes the intended agent behavior and what system-prompt guidance makes it work.

### 6.1 The retrieval → navigation dance

**Step 1 — broad retrieval.** Agent interprets the natural-language query and issues a `filings_search` with loose filters. Reviews 20-30 ranked hits with snippets. Forms hypotheses about which tickers/sections matter.

**Step 2 — narrow reading.** For the top 5-10 candidates, agent calls `filings_read` with `section` scoped. Reads full passages, extracts concrete facts (numbers, commitments, language), forms claims.

**Step 3 — optional refinement.** Agent may issue follow-up `filings_search` calls to sharpen: narrower query, specific ticker, different section, different form type. Iterates until the answer is grounded enough to write.

**Step 4 — synthesis with citations.** Agent writes the answer, inline-citing each claim to `{ticker} {form} §{section}`. Citations link back to `file_path` for the user to open.

### 6.2 What the system prompt must teach

- **"Search narrows, read reasons."** The agent should not try to answer from snippets alone — snippets are lossy. They exist to identify which files to read.
- **"Never grep the full corpus."** The point of FTS5 is the agent doesn't scan 20,000 files. If the agent is trying to glob the corpus directly, it has mis-modeled the tool surface.
- **"Cite everything."** Every factual claim in the answer needs a file-path-level citation. Unsupported claims are flagged.
- **"Prefer recent."** Without explicit date filters, default to the most recent filing per ticker — old 10-Ks are cached context, not current state.
- **"Pick the right per-source family."** `filings_*` for SEC filings, `transcripts_*` for earnings calls. If a query has no source cue, default to filings — that's where strategic/annual/structural language lives.
- **"Cite by document_id."** When forming citations or calling `*_source_excerpt`, prefer `document_id` (from SearchHit) over the `(ticker, form_type, fiscal_period)` convenience tuple. The tuple is not unique — amendments and same-day multi-filings exist. Falling back to the convenience overload is only safe for single-shot, non-critical paths.
- **"Cross-source queries are parallel calls, merged by rank."** For queries that span sources — *"across filings and transcripts"*, *"everything X said about Y"* — call both families in parallel and merge client-side by BM25 rank (§5.2). Don't serialize; don't try to collapse into a single tool.
- **"Cite with source_url, verify with {family}_source_excerpt."** Every citation includes both the reading reference (file_path + section) and the authoritative source_url. For high-stakes claims — specific numbers, direct quotes, anything a user might challenge — call the source_excerpt for the relevant family (`filings_source_excerpt` or `transcripts_source_excerpt`) to confirm the summary's fidelity to the source before synthesizing.

### 6.3 When the pattern breaks

The retrieval → navigation flow works for natural-language queries over narrative content. It does *not* work for:

- **Structured numeric lookups** — "What was MSFT's FY2025 revenue?" is a `get_metric` query, not an FTS5 one. Agent should route to XBRL tools.
- **Cross-filing table joins** — "Rank S&P 500 by gross margin" needs structured data, not text search.
- **Time-series comparison** — multiple quarters of the same metric → `get_metric_series`.

The agent needs to know which tool is right. A simple heuristic: **if the answer is a number, route to structured tools; if the answer is language or reasoning, route to filings_search.** This distinction belongs in the system prompt.

### 6.4 Context budget discipline

- `filings_search` with `limit=20` and snippet length ~200 chars = ~4KB payload. Cheap.
- `filings_read` of a full 10-K section (e.g., Item 7 MD&A) = 20-60KB. Moderate.
- Reading a full 10-K = 200-600KB. Expensive — avoid unless strictly needed.

Agent prompt should encode: *"Section-scoped reads are preferred. Whole-file reads only when the question spans multiple sections."*

### 6.5 Composition with structured tools and code execution

Most real queries aren't pure narrative or pure numeric — they blend. *"Top companies investing in AI"* needs the corpus to find candidates AND structured tools to rank them. *"Which of those have active-manager accumulation?"* adds a third composition step. The agent composes across surfaces, not within one.

**Three composition patterns:**

**Pattern 1 — Text-first, structured-later.** Corpus narrows the candidate set; structured tools rank/filter/enrich.

```python
# "Top AI capex spenders with active-manager accumulation"
hits = filings_search("AI capex OR AI infrastructure", form_type=['10-K'], limit=30)
tickers = list({h.ticker for h in hits})
capex = {t: get_metric_series(t, "CapitalExpenditures", periods=4) for t in tickers}
top_10 = sorted(tickers, key=lambda t: capex[t].latest, reverse=True)[:10]
ownership = {t: get_institutional_ownership(t) for t in top_10}
accumulating = [t for t in top_10 if ownership[t].qoq_net_shares > 0]
```

The corpus *identifies candidates by language*; structured tools *rank and filter by numbers*.

**Pattern 2 — Structured-first, text-later.** Numeric filter narrows the universe; corpus retrieves narrative for the filtered set.

```python
# "S&P 500 with >30% capex growth that attribute it to AI"
tickers = screen_stocks(criteria={'capex_yoy_growth': '>0.30', 'index': 'sp500'})
hits = filings_search("AI infrastructure", universe=tickers, form_type=['10-K'])
```

The `universe` parameter on `filings_search` already enables this — structured tool hands off a ticker list, corpus narrows by narrative.

**Pattern 3 — Interleaved / parallel.** Text and structured measures computed independently, joined at synthesis.

```python
# "Companies where risk-factor discussion has expanded AND leverage has worsened"
risk_growth = {t: measure_section_length_delta(t, "Item 1A") for t in universe}  # text-derived
leverage = {t: get_metric_series(t, "debt_to_equity", periods=4) for t in universe}
joined = [t for t in universe if risk_growth[t] > 0 and leverage[t].trend == 'up']
```

Both measures are computed independently; the agent joins on ticker at synthesis time.

**Code execution as the glue.** When composition requires custom math (ratios, aggregations, deltas, multi-criteria ranking), the agent invokes code execution. This works cleanly because:

1. **MCP tool outputs are typed** (`SearchHit`, metric series objects, ownership records) — code can access `.ticker`, `.value`, `.filing_date` safely without string parsing.
2. **Canonical ticker is the universal key** (§4.6) — no string mangling between tool calls.
3. **Tools handle their own internal conversions** — `get_metric` internally translates ticker→CIK for EDGAR; the agent and code never see the non-canonical form.

The pattern: agent calls corpus and structured tools, feeds outputs into code-exec for custom math, synthesizes the final answer. Code exec doesn't *replace* the tools — it *orchestrates* them.

**Choosing a composition mechanism:**

- **Direct chaining** (tool A → tool B) — when structured tools accept each other's outputs natively (e.g., `filings_search(universe=[...])`).
- **Code execution** — when composition needs math the tools don't expose (custom deltas, multi-criteria ranking, aggregations, chart generation).
- **Multi-step agent reasoning** — when the composition shape isn't known upfront and the agent needs to iterate (common with open-ended queries).

All three are available simultaneously. The agent picks based on the query shape.

**Prerequisite for Patterns 2 and 3:** cross-company period joins require **V2.P7 (Fiscal calendar normalization DB)**, still deferred. Pattern 1 works without it (per-ticker structured queries don't require cross-ticker period alignment). See §13.7 for the full dependency list.

---

## 7. Citation & Source Linking

Every claim the agent makes must be traceable to a primary source, and every user must be able to verify the claim on demand. This section defines the citation chain and the verification path. Applies to all sources — filings, transcripts, future Quartr decks, press releases — same contract.

### 7.1 The citation chain

Every fact the agent asserts has a four-rung chain, anchored on the immutable `document_id`:

```
Agent claim
  ↓
Reading passage   (document_id + section + char_range + file_path)    ← our corpus markdown
  ↓
Document identity (document_id → ticker / form_type / fiscal_period /  ← documents metadata row
                   is_superseded_by / supersedes)
  ↓
Authoritative source (source_url + source_url_deep + source_accession) ← EDGAR, FMP, Quartr, ...
```

- **Agent claim** is a sentence in the synthesis ("MSFT's FY2024 capex was $55.7B").
- **Reading passage** is where the agent got it. Anchored on `document_id + section + char_range`; `file_path` is provided as the concrete filesystem location (disposable — if the canonical path changes, `document_id + section` still resolves). Renders as *"MSFT 10-K FY2024 §Item 7"* but carries `document_id=edgar:0000789019-24-000073` internally.
- **Document identity** is the immutable `document_id`. The row exposes ticker/form/period (for human rendering), the supersession chain (for amendments), and enough metadata for agent routing.
- **Authoritative source** is the thing of record — `source_url` (stable landing page) + `source_url_deep` (optional direct link to primary HTML/PDF) + `source_accession`.

The chain is always present. Claims without a chain are flagged. **`document_id` is load-bearing** — it's what makes the chain survive amendments, re-filings, and ticker migrations. Rendering can still display the human-readable tuple, but the underlying identity is the document_id.

### 7.2 Two citation modes

| Mode | What it says | Served by |
|---|---|---|
| **Reading citation** | "This is the passage the agent read to form the claim" | `file_path + section + char_range` from `SearchHit` (our corpus) |
| **Source citation** | "This is the authoritative original — click to verify" | `source_url` from `SearchHit` (external authoritative source) |

Every rendered citation includes both. Reading citations ground the synthesis in what the agent actually saw; source citations let the user verify that nothing was distorted in summarization.

### 7.3 Source URL formats

Per-source, carried in frontmatter. Every source produces two URLs — a **stable landing page** (`source_url`, guaranteed-stable, always populated) and an **optional deep link** (`source_url_deep`, preferred when stable but may break on source restructures). Both flow through `SearchHit`:

- **EDGAR filings**
  - `source_url` — `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}&dateb=&owner=include&count=40` — the company's filing index; stable even if the accession page 404s.
  - `source_url_deep` — `https://www.sec.gov/Archives/edgar/data/{cik}/{accession-nodashes}/{primary-document}.htm` — direct link to the filing HTML. Preferred for user click-through when present.
- **FMP transcripts**
  - `source_url` — the FMP transcript landing page for the company + fiscal period.
  - `source_url_deep` — optional direct-to-transcript URL when FMP provides one.
- **Quartr decks (future)** — TBD when V2.P8 integration lands; Quartr has stable document URLs for both levels.
- **Future sources** — every converter is responsible for producing a stable `source_url`. `source_url_deep` is best-effort.

Storing both means a deep-link 404 falls back gracefully to the landing page without breaking the citation.

### 7.4 On-demand verification via per-family `*_source_excerpt`

Pre-caching verbatim source text is unnecessary and expensive (would roughly 10× corpus storage for content that's rarely read). Instead, verification is a cheap on-demand fetch via existing MCP tools, wrapped in per-family source_excerpt tools. **Primary dispatch is by immutable `document_id`** — the convenience overload (`ticker + form_type + fiscal_period`) is available but errors on amendment ambiguity.

```python
# Filings — primary path: document_id (from SearchHit.document_id)
filings_source_excerpt(document_id='edgar:0000789019-24-000073', section='Item 7')
# → edgar-financials.get_filing_sections(accession=..., section='Item 7')

# Filings — convenience overload (per §5.1 — errors if amendments/re-filings make
# (ticker, form_type, fiscal_period) non-unique):
filings_source_excerpt(ticker='MSFT', form_type='10-K', fiscal_period='2024-FY', section='Item 7')
# → resolves to the latest non-superseded document_id; raises AmbiguousDocumentError
#   if multiple non-superseded documents match the tuple. Agent should fall back to
#   the document_id signature on any AmbiguousDocumentError.

# Transcripts — primary path: document_id
transcripts_source_excerpt(
    document_id='fmp_transcripts:MSFT_2025-Q1',
    speaker='Satya Nadella',
)
# → fmp-mcp.get_earnings_transcript(ticker='MSFT', year=2025, quarter=1, speaker='Satya Nadella')

# Future — Quartr decks (V2.P8):
# decks_source_excerpt(document_id='quartr:<deck-id>', section='...')
# → quartr.get_deck_section(...)

# All return verbatim text from the original source, not our summary.
```

Each per-family source_excerpt is a thin wrapper over the source-specific fetcher already shipped for that content type. New sources add a new family with the same shape; no dispatcher, no central registry. The document_id → source-specific-identifier mapping is a one-liner per family.

**Who calls it, when:**
- **Agent** — proactively for high-stakes claims (specific numbers, direct quotes, claims a user might push back on).
- **User/UI** — on click of a citation's "verify" button. UI pulls the verbatim passage, shows it alongside the summary so the user can confirm fidelity.
- **Adversarial eval harness** (V2.P4) — compares agent-quoted language against verbatim source; flags hallucinated quotes.

**Cost:** a `get_filing_sections` call is an external API request (~100-500ms latency, per-call cost depending on provider). Fine for on-demand, too expensive for bulk pre-cache. If repeated verification queries against the same section become common, add an LRU cache in front (see Open Question Q13).

### 7.5 What the agent must do

Encoded in system-prompt guidance and enforced by output validation:

1. **Every synthesized claim carries a reading citation.** `{ticker} {form} §{section}` at minimum.
2. **Every reading citation carries a source_url.** The UI renders both — the reading reference and the authoritative link.
3. **Direct quotes must be verified.** If the agent says *"the filing says ..."* or *"on the call, the CEO said ..."*, it must either (a) quote from our markdown and mark it as a paraphrase, or (b) call the relevant per-family source_excerpt (`filings_source_excerpt` / `transcripts_source_excerpt`) and quote verbatim from the source.
4. **Unresolved claims are flagged, not elided.** If a fact can't be traced to a passage, the agent says so explicitly rather than smoothing over the gap.

**Where the validator lives is deliberately left as Q15.** *"Enforced by output validation"* is a load-bearing phrase, but the architecture doc does not yet specify which layer owns that enforcement. Candidate layers (agent self-check via prompt, post-generation middleware, gateway-level citation provider, UI-layer render gate) have different consumer/tradeoff profiles — see Q15 for the lean. Until Q15 resolves in the implementation plan, the enforcement obligation is carried by system-prompt guidance alone, which is the weakest form of enforcement. The trust architecture in §7 is not complete in production until the validator has a concrete home.

### 7.6 What breaks the chain (and how we handle it)

- **Summary paraphrases a number.** Mitigated by the per-family source_excerpt tools — agent can verify the summary's number matches source before asserting it. Adversarial eval catches regressions.
- **Amendments are first-class, not chain breaks.** When a 10-K/A is filed against a prior 10-K, the amendment becomes a new document in the index with its own `document_id` and `supersedes` pointer to the original. The original carries `is_superseded_by`. Search defaults to non-superseded. Historical queries opt in via `include_superseded=True`. Citations made against the original stay valid because they anchor on the original's `document_id` — the user sees both "current" and "as filed at time of claim."
- **Same-day multi-filings** (e.g., multiple 8-Ks) resolve cleanly because each has its own accession → its own `document_id`. No disambiguation needed when citations use `document_id`.
- **`source_url_deep` goes 404.** Document re-organizations happen (SEC restructures the filing-archive path, FMP moves transcript URLs). Fall back to `source_url` (the stable landing page) — user can navigate to the document from there.
- **`source_url` goes 404.** Rare for SEC (company CIK pages are extremely stable). If it happens, `*_source_excerpt` errors with a verification-failure flag and the agent surfaces the gap to the user rather than silently asserting.
- **Char offsets drift.** Mitigated by content-addressable filenames (D6) — re-extraction with a new extraction pipeline produces a new file (new `content_hash`) but preserves `document_id` if content is logically the same. Old offsets stay valid against the old file until garbage collection. Citations made against the old content_hash keep working.
- **Source hasn't been ingested yet.** FTS5 returns nothing. Agent falls back to live-fetch via edgar-financials / fmp-mcp and notes the gap.

### 7.7 Why this matters architecturally

The citation chain is what turns the corpus from a search index into a **trust artifact**. The corpus doesn't just tell the agent what to read — it tells the user what to believe, and gives them a frictionless path to verify. This is the layer that separates "agentic search" from "agent synthesis the user has to trust blindly."

---

## 8. End-to-End Flows

**Notation note:** for brevity, the flows below elide the `SearchResponse` envelope. A line like `hits = filings_search(...)` should be read as `hits = filings_search(...).hits` in actual agent code. The `has_superseded_matches` and `applied_filters` metadata from the envelope is assumed available to the agent between steps but not shown in each example.

### 8.1 "Which tech companies are investing heavily in AI?"

**Agent interprets:** vague-quantifier query; needs to find candidates + quantify. Broad universe (tech but maybe cross-sector). Annual strategy lives in 10-Ks.

**Retrieval:**

```python
filings_search(
    query='("AI" OR "artificial intelligence") NEAR/15 (capex OR "capital expenditure" OR invest OR spending OR infrastructure)',
    form_type=['10-K', '10-Q'],
    date_from='2024-01-01',
    limit=30,
)
```

Returns ranked hits; top results cluster in MSFT, META, GOOG, AMZN 10-Ks (Item 7), plus second-tier hits from AAPL, NVDA, CRM, ORCL.

**Navigation:** Agent reads Item 7 MD&A for top 4 hyperscalers:

```python
filings_read(file_path="data/filings/edgar/MSFT/10-K_2024-FY_{hash}.md", section="Item 7")
filings_read(file_path="data/filings/edgar/META/10-K_2024-FY_{hash}.md", section="Item 7")
filings_read(file_path="data/filings/edgar/GOOG/10-K_2024-FY_{hash}.md", section="Item 7")
filings_read(file_path="data/filings/edgar/AMZN/10-K_2024-FY_{hash}.md", section="Item 7")
```

Extracts concrete capex numbers per company.

**Refinement:** Agent wants current quarter for fresher numbers:

```python
filings_search(
    query='capex NEAR/20 "AI" AND guidance',
    universe=['MSFT', 'META', 'GOOG', 'AMZN'],
    form_type=['10-Q'],
    date_from='2024-07-01',
    limit=10,
)
```

**Synthesis:**

> The hyperscalers are the heavy AI investors, with multi-$10B+ annual capex commitments explicitly tied to AI infrastructure:
>
> - **Amazon** — $75B FY2024, AI/AWS dominant driver (AMZN 10-K §Item 7)
> - **Microsoft** — $55.7B FY2024, FY2025 expected materially higher (MSFT 10-K §Item 7)
> - **Google** — ~$50B FY2024, AI compute primary driver (GOOG 10-K §Item 7)
> - **Meta** — $38-40B FY2024 range, AI + non-AI (META 10-K §Item 7)
>
> Apple and Nvidia discuss AI investment qualitatively but do not disclose AI-specific capex figures.

**Total cost:** ~30 FTS5 search hits + 4 section reads (~150KB total) + 10 refinement search hits. All cited, all grounded.

### 8.2 "How has MSFT talked about Copilot across filings and earnings calls?"

Cross-source query — tests the parallel-calls + merge pattern (§5.2).

**Retrieval — parallel calls:**

```python
f_hits = filings_search(
    query='Copilot',
    universe=['MSFT'],
    date_from='2023-01-01',
    limit=30,
)
t_hits = transcripts_search(
    query='Copilot',
    universe=['MSFT'],
    date_from='2023-01-01',
    limit=30,
)
merged = sorted(f_hits + t_hits, key=lambda h: h.rank)[:50]
# Ascending sort — SQLite FTS5 bm25() scores are "smaller is better"
# Single ranked list; both sources' BM25 scores are comparable (same FTS5 index, same grain)
```

Agent sees Copilot language evolve across the merged timeline:
- Early 10-K (FY2023): aspirational, *"Microsoft 365 Copilot general availability"*
- Mid-period transcripts: monetization commentary, seats growth, pricing (highest-ranked passages tend to be prepared-remarks + Q&A from earnings calls)
- Recent 10-K (FY2024/25): revenue contribution language, competitive positioning

**Navigation:** Agent reads 5-6 specific passages across the timeline using `filings_read` and `transcripts_read` as appropriate, picks key quotes.

**Synthesis:** narrative arc with per-quarter citations, drawn from both sources.

**Why this works:** parallel per-source calls preserve explicit intent ("I'm querying filings AND transcripts"), and the shared FTS5 index makes cross-source ranking trivial (one `sorted()` call). No per-source loop, no merge heuristic, no unified tool needed. One extra tool call compared to a hypothetical unified `corpus_search`, but the agent's query intent is clearer and the system-prompt tool surface stays smaller (see §5.2 for the tradeoff).

### 8.3 "What tail risks do banks disclose that tech companies don't?"

Differential query — tests cross-sector comparison.

**Retrieval (two queries):**

```python
filings_search(
    query='...',  # risk-factor language
    sector='Financials',
    form_type=['10-K'],
    limit=20,
)
filings_search(
    query='...',
    sector='Technology',
    form_type=['10-K'],
    limit=20,
)
```

Or a single query across sectors with agent doing the partitioning.

**Navigation:** agent reads `Item 1A. Risk Factors` sections for top candidates in each sector.

**Synthesis:** contrast analysis — credit / liquidity / regulatory themes for banks vs. platform / competition / IP themes for tech.

**Why this matters:** demonstrates that sector-filtered queries enable comparative analysis across a pre-selected universe — which is the Fintool-style "NL screener" wedge.

### 8.4 "Top AI infrastructure investors with active-manager accumulation"

Composition flow — Pattern 1 from §6.5. Demonstrates corpus + structured tools + code execution combining via ticker as the shared key.

**Agent interprets:** multi-stage query. Stage 1 is narrative (find AI-capex discussants). Stage 2 is numeric (rank by capex $). Stage 3 is numeric+temporal (filter by institutional-flow delta). Requires cross-surface composition.

**Stage 1 — corpus narrows candidates:**

```python
hits = filings_search(
    query='("AI" OR "artificial intelligence") NEAR/15 (capex OR "capital expenditure" OR infrastructure)',
    form_type=['10-K', '10-Q'],
    date_from='2024-01-01',
    limit=50,
)
# Returns ranked hits across ~30 unique tickers
```

**Stage 2 — structured ranking by capex:**

```python
tickers = list({h.ticker for h in hits})            # deduplicate, canonical form
capex_series = {t: get_metric_series(t, "CapitalExpenditures", periods=4) for t in tickers}
# Rank by most recent annualized capex
top_10 = sorted(tickers, key=lambda t: capex_series[t].latest, reverse=True)[:10]
```

**Stage 3 — structured filter by fund accumulation:**

```python
filtered = []
for ticker in top_10:
    ownership = get_institutional_ownership(ticker)
    if ownership.qoq_net_shares_purchased > 0:  # net accumulation across top 50 holders
        filtered.append((ticker, ownership.qoq_net_shares_purchased))
```

**Stage 4 — verification via corpus re-read + source_excerpt:**

For the final 4-5 candidates, agent reads their Item 7 from the corpus (`filings_read`) and calls `filings_source_excerpt` on the key passages to confirm AI-capex language is *operational*, not aspirational. Drops any whose filings language is boilerplate.

**Synthesis with citations:**

> **Top AI infrastructure investors where active managers are accumulating:**
>
> - **Amazon** ($75B FY2024 capex, AI/AWS-dominant) — net +8.2M shares across top 50 institutional holders last quarter. [AMZN 10-K §Item 7 → EDGAR]
> - **Microsoft** ($55.7B FY2024, FY2025 materially higher) — net +3.1M shares accumulated. [MSFT 10-K §Item 7 → EDGAR]
> - **Google** (~$50B FY2024, AI compute primary) — net +6.5M shares accumulated. [GOOG 10-K §Item 7 → EDGAR]
> - **Meta** — excluded; filings language matches but 13F flow shows net distribution last 2 quarters.

**Why this works:**
- Corpus narrows 5,000-ticker universe → ~30 candidates (FTS5 in milliseconds)
- Structured tools rank + filter the narrow set (per-ticker queries, no cross-ticker period join needed)
- Code execution composes via ticker list — no translation, no impedance mismatch
- Citations chain through: claim → corpus reading → source_url → EDGAR filing

**Total cost:** ~$0.30-$0.60 — one FTS5 search, ~30 `get_metric_series` calls, ~10 `get_institutional_ownership` calls, ~5 corpus reads, ~5 source_excerpts. Comparable to a complex multi-step analyst task done by hand.

**Prerequisites:** works with V2.P7 (fiscal calendar) still deferred — all structured queries are per-ticker, not cross-ticker-by-period. Would break without D11 (canonical ticker) — the three-way ticker join between corpus hits / capex metric / ownership data is the entire mechanism.

---

## 9. Cost Back-of-Envelope

Rough numbers to validate feasibility. Refined in implementation plan.

### 9.1 Ingestion (one-time for initial corpus)

**Pricing source:** Gemini 2.5 Flash standard tier at $0.30/1M input, $2.50/1M output; batch tier at $0.15/1M input, $1.25/1M output (https://ai.google.dev/gemini-api/docs/pricing, 2026-04). Batch is preferred for initial ingestion (non-latency-sensitive); standard for incremental/ongoing.

**Filings (standard pricing):**
- ~1,500 tickers × (1 recent 10-K + 4 recent 10-Qs) = ~7,500 filings
- Avg 10-K ≈ 100-300K input tokens (~200K mid), 10-Q ≈ 50-150K input (~100K mid); output is structured markdown, typically 10-20K tokens (summarized)
- Per filing (mid): 10-K ≈ $0.06 input + $0.04 output = $0.10; 10-Q ≈ $0.03 input + $0.03 output = $0.06
- 1,500 × $0.10 (10-Ks) + 6,000 × $0.06 (10-Qs) ≈ $150 + $360 = **~$500 standard-tier**
- **Batch tier cuts this ~50%** → **~$250 batch**
- Time: ~3 concurrent workers × 10-20s/filing × 7,500 = ~10-20 hours wall clock standard; batch is async (hours-to-day completion with no wall-time pressure)

**Transcripts (standard pricing):**
- ~1,500 tickers × 4 quarters = 6,000 transcripts (last year only — recommended for V2.P1 Phase 3)
- FMP transcripts are smaller: ~30-80K input tokens, ~5-10K output
- Per transcript (mid): $0.02 input + $0.02 output = **~$0.04**
- 6,000 × $0.04 = **~$240 standard-tier** → **~$120 batch**
- 3-year backfill (18,000 transcripts): ~$720 standard / $360 batch

**Total initial cost (batch tier, which we'd use for one-time ingestion):**
- **~$250** for filings-only Phase 2
- **~$370** with 1-year transcripts (Phase 3)
- **~$610** with 3-year transcripts (optional deep backfill)

Higher than the earlier back-of-envelope because (a) pricing updated to current $0.30/$2.50 standard, (b) output tokens are non-trivial for summarized markdown. Still low absolute dollars — less than a single FinanceBench eval run ($1,500-$3,000) or a month of one employee's cloud-API spend.

### 9.2 Storage

- Markdown file sizes (summarized per current Edgar_updater output):
  - 10-K ≈ 50-200 KB summarized
  - 10-Q ≈ 30-100 KB
  - Transcript ≈ 30-80 KB
- **Filings corpus (Phase 2, ~7,500 files): ~1 GB on disk**
- **Transcripts (Phase 3, 6,000 files @ 1yr): ~300 MB**
- **Combined through Phase 3: ~1.3 GB markdown on disk**
- **SQLite `filings.db`** (section-grain FTS5 per D12):
  - `documents` metadata table: **~13,500 rows** at Phase 3 (7,500 filings + 6,000 transcripts) × ~1 KB = ~13 MB
  - `sections_fts` FTS5 index at Phase 3:
    - Filings: 1,500 × 1 (10-K × 10 sections) + 6,000 × 5 sections = 15,000 + 30,000 = ~45,000 rows
    - Transcripts: 6,000 × ~30 speaker turns avg = **~180,000 rows**
    - **Total: ~225,000 section rows**
  - Index size ~40-60% of indexed content = **~600 MB - 1 GB**
- **Total through Phase 3: ~2.5-3.5 GB** markdown + index + DB, growing ~0.5-1 GB/year

Well within single-disk territory. No blob store, no CDN, no distributed storage.

**Section-grain trade**: significantly more FTS5 rows than document-grain would produce (especially with transcripts), but SQLite handles 200K+ row FTS5 indexes trivially, each row is smaller so total index size stays reasonable, section-grain gives tighter BM25 ranking, and retrieval returns passage-level hits directly.

### 9.3 Ongoing ingestion

- New filings per day (1,500-ticker universe): ~10-50 (mostly 10-Qs in reporting season, 8-Ks continuously, 10-Ks in batches).
- Per-filing extraction cost (standard-tier pricing, not batch): ~$0.06-$0.10
- **Daily cost: $1-$5**
- **Monthly cost: $30-$150**

Still low absolute dollars, but up from the earlier BOTE because (a) current Gemini pricing is higher than we had noted, (b) 8-Ks are more frequent than quarterly reports imply. Extraction is not a cost center but also not free. Batch-tier processing of non-urgent ingestions (e.g., deferred S&P 1500 backfill) halves this.

### 9.4 Query costs

- FTS5 queries: **free** (local SQLite, no per-call cost, <10ms per query).
- LLM reasoning at query time: dominant cost, but that's not new — every agent query already pays LLM tokens. Difference is where context comes from.
- **Per-query incremental cost:** the tokens spent reading retrieved markdown. 5-10 section reads @ 50KB = ~60-100K tokens = **~$0.20-$0.50 per complex query** (Opus input pricing).

This is the same order of magnitude as non-FTS5 agent queries today — FTS5 changes *where* tokens come from, not *how many* at synthesis time.

### 9.5 Summary

| Cost | Amount | Frequency |
|---|---|---|
| Initial ingestion — filings (batch tier) | ~$250 | one-time |
| Initial ingestion — transcripts 1yr (batch) | ~$120 | one-time |
| Initial ingestion — transcripts 3yr (batch) | ~$360 | one-time, optional |
| Ongoing ingestion (standard tier) | $30-$150 | monthly |
| Storage | 2-3 GB | continuous, +0.5-1 GB/yr |
| Per query (reasoning) | $0.20-$0.50 | per complex query |

**Conclusion:** Standing up the full corpus (filings + 1yr transcripts) costs **~$370 one-time** at batch-tier pricing, plus **~$50-150/month ongoing**. No infrastructure costs. The expensive thing (extraction) is one-time per document and idempotent via `document_id` + `content_hash`. Still less than a single FinanceBench eval run to stand up, just by a smaller margin than the earlier BOTE suggested.

---

## 10. Invariants

Things that must always be true. Violations indicate bugs.

**I1. Filesystem is source of truth.**
The markdown files under `data/filings/` are authoritative for content and for all frontmatter metadata (including `document_id`, `supersedes` + provenance fields, `source_url`, `sector`, etc.). Frontmatter values are produced by the ingestion pipeline — some are truly intrinsic to the source (e.g., `source_accession` for SEC filings), others are derived at ingestion (e.g., `supersedes`, `sector`) — but once written, all frontmatter is immutable per I5. The SQLite `documents` table and `sections_fts` index are disposable derivations; the reconciler (I12) rebuilds them from disk end-to-end. Cross-document relationships expressed as *DB-only derived columns* (notably `is_superseded_by`, computed from `supersedes` + `supersedes_confidence` pointers across documents) are also rebuildable from disk, because the pointer side that lives in frontmatter is sufficient to reconstruct both sides of the relationship.

**I2. Ingestion is file-first; the filesystem is the source of truth even on partial failure.**
The ingestion sequence is: (a) extract content to a temp file under `data/filings/.staging/`, (b) atomic rename into canonical path `data/filings/{source}/{ticker}/{form}_{period}_{hash}.md` (POSIX `rename(2)` is atomic within a filesystem), (c) open a SQLite transaction that **UPSERTs** the `documents` row keyed on `document_id` (updates `content_hash`, `file_path`, `extraction_*` fields) and replaces the associated `sections_fts` rows, (d) commit. If steps (c) or (d) fail or crash, the markdown file remains on disk and the periodic reconciler (I12, D14) heals the index. There is **no cross-resource rollback** — the filesystem write is authoritative, SQLite is a derived index. Concurrent workers writing the same `document_id` are safe because content-addressable filenames are idempotent when content matches (same content_hash → same filename → `rename` is a no-op) and the UPSERT is last-commit-wins when content diverges (per I14 corollary, D14 concurrency rules).

**I3. Index rebuild from disk is logically idempotent.**
Running a full rebuild over `data/filings/` produces an index that returns the same query results as the live index (modulo timestamps, internal segment layout). SQLite FTS5 stores its index in segment b-trees that merge over time, so byte-level identity is not guaranteed; logical equivalence at the query-result level is what's guaranteed. This is how corruption is recovered.

**I4. Markdown convention changes are versioned.**
Changing the frontmatter schema or section taxonomy requires a version bump in the `extraction_pipeline` metadata field and a re-run of extraction on affected files. No silent schema evolution.

**I5. Content-addressable filenames are immutable (file-level).**
Once a file with a given `content_hash` exists on disk, its content never changes — the hash is the content. Re-extraction of the same source with different output produces a new file (new hash, new filename). The `documents` row's `file_path` may update to point at the new file; the old file remains on disk until garbage collection. `document_id` stays the same because `document_id` is source identity, not content identity (see D13, I14).

**I6. Section headers follow the canonical taxonomy exactly.**
`## SECTION: Item 7. Management's Discussion and Analysis` — not `## SECTION: Item 7` or `## MD&A`. The section string is a key into the index.

**I7. Frontmatter is valid YAML and conforms to schema.**
Every markdown file parses as YAML-frontmatter + body. Ingestion validates schema before index insert.

**I8. Queries filter by `source` / `form_type` / `ticker` before full-text scan (where possible).**
FTS5 + metadata column indexes handle this natively; ensure query tool sets these filters before the MATCH.

**I9. Citations round-trip.**
Every passage returned from `filings_search` includes `file_path`. Feeding that path to `filings_read` returns readable markdown. No stale-path results.

**I10. Every citation carries an authoritative source link.**
Every `SearchHit` includes a populated `source_url` pointing at the authoritative original (EDGAR filing page, FMP transcript, Quartr deck, etc.). No hits with empty or placeholder source URLs leave the query surface. The citation chain (agent claim → reading passage → document metadata → authoritative source) is never broken.

**I11. Every ticker on a tool boundary is canonical.**
Any tool that returns or accepts a ticker uses the canonical form from `SymbolResolver.resolve_identity()`. Tools that internally need alternative forms (e.g., `edgar-financials` wants CIK for some endpoints) convert at their own boundary — non-canonical forms never appear in agent-facing or code-execution-facing outputs. This invariant is what makes cross-surface composition (§6.5) work.

**I12. Reconciler heals filesystem/index drift.**
A periodic reconciler walks `data/filings/` and ensures that for each `document_id` present on disk, exactly one `documents` row exists with `content_hash` + `file_path` pointing at the authoritative file for that `document_id`. Authoritative file selection rule (applied in order, deterministic): (1) prefer the file whose frontmatter `extraction_at` is greatest; (2) if `extraction_at` is tied, missing, or malformed (not parseable as ISO-8601), prefer the largest `extraction_pipeline` semver; (3) if `extraction_pipeline` is tied, missing, or malformed (not parseable as semver), prefer lexicographically greater `content_hash` (arbitrary but deterministic). Malformed values at any level fall through to the next tiebreaker rather than failing; the worst case is that two files with no valid metadata are disambiguated purely by content_hash lexicographic order — deterministic, safe, logged as a data-quality issue. This rule is stable — repeated reconciler runs converge on the same choice; no oscillation is possible because none of the tiebreakers depend on reconciler-state.

Orphaned `sections_fts` rows (pointing at a document_id/file combination no longer canonical) are removed; missing `sections_fts` rows for the canonical file are inserted. Historical content files for the same `document_id` (older extractions, content_hash variants) remain on disk for citation durability but are not the canonical pointer. Content-divergence cases (multiple recent files for same document_id with different content_hashes) are logged for ops review.

**Derived `is_superseded_by` recomputation.** The reconciler recomputes the DB-only `is_superseded_by` column using the deterministic confidence-gated scalar rule from D14 (high-confidence amendments only; most-recent by filing_date wins; tiebreak on lex-greater document_id):

```sql
UPDATE documents SET is_superseded_by = (
    SELECT d2.document_id FROM documents d2
    WHERE d2.supersedes = documents.document_id
      AND d2.supersedes_confidence = 'high'
    ORDER BY d2.filing_date DESC, d2.document_id DESC
    LIMIT 1
)
```

Idempotent per I1 — `supersedes`, `supersedes_confidence`, `filing_date`, and `document_id` all live in frontmatter, so the derivation converges from disk alone and produces the same result as ingestion-time updates. Low/medium-confidence links are preserved on their respective amendment rows (queryable via `SELECT * FROM documents WHERE supersedes = ? AND supersedes_confidence IN ('low', 'medium')`) but do not drive the original's `is_superseded_by` column.

The reconciler is idempotent and safe to run concurrently with live queries. Runs on schedule (hourly/nightly) and on-demand after ingestion failures.

**I13. Tool-boundary inputs are validated.**
Every tool that accepts user-provided inputs enforces explicit bounds: max query string length (e.g., 1 KB), max `universe` list size (e.g., 5,000 tickers), `limit` capped at e.g., 500, `date_from`/`date_to` must parse as ISO-8601, `file_path` must canonicalize within `data/filings/` root (no traversal). Violations return structured `InvalidInputError` before touching the index — no opportunity for unbounded queries or path traversal to reach SQLite or the filesystem.

**I14. Document identity is source identity, not content identity.**
`document_id` is assigned from the immutable source key (SEC accession, canonical transcript slug, etc.) and never changes for the life of a `documents` row. Mutable fields on the row — `content_hash`, `file_path`, `extraction_pipeline`, `extraction_model`, `extraction_at`, `is_superseded_by` — may update as re-extraction or amendment metadata arrives. `document_id` itself is stable. Citations against a `document_id` remain resolvable forever, even if the backing file was re-extracted multiple times.

**Corollary — concurrency with content divergence.** When two workers produce different content for the same `document_id` (different extraction model versions, transient bugs), last-write-wins at the SQLite commit layer (the `documents` row's `content_hash` + `file_path` reflect whichever transaction commits last). Older content files remain on disk addressable by their `content_hash` but are no longer the row's canonical pointer. The reconciler logs a content-divergence event for ops review — it does not attempt to reconcile semantic correctness between extractions; that's an operational decision (re-run with chosen model).

---

## 11. Locked Decisions

Decisions committed to in this document. Changing one requires a successor design doc.

### D1. Single shared corpus (not per-user)

**The change:** Filings + transcripts corpus is single-tenant — one `data/filings/` directory, one `filings.db`, shared across all users.

**Why:** SEC filings and earnings transcripts are public documents. Per-user corpora would triplicate extraction cost with zero data-isolation benefit. User watchlists drive ingestion *priority* (we ingest their tickers sooner), not access control.

**Consequence:** The metadata table has no `user_id` column. The FTS5 index is global. RLS (separate item in TODO) does not apply to this corpus.

### D2. No vector database / no embeddings

**The change:** The corpus is indexed by FTS5 (keyword + BM25) only. No semantic embeddings, no vector search, no reranker.

**Why:** Documented in BETA_RELEASE_GAP_AUDIT T2.6. Fintool abandoned their 500GB Elasticsearch + embeddings stack for filesystem + frontier context. Our universe is smaller and our latency budget is more relaxed — FTS5 + agent reading is strictly simpler and handles the wedge queries ("AI capex", "Copilot discussion", "credit provisions") as well as embeddings would for the retrieval-of-candidates step.

**Consequence:** No pgvector, no Pinecone, no embedding cost. If semantic search becomes necessary later (not anticipated), it's an additive layer — FTS5 stays.

### D3. One SQLite database, one document table + one FTS5 section table, `form_type` + `source` discriminators

**The change:** All filings and transcripts share one `documents` metadata table (document-grain, one row per document) and one `sections_fts` FTS5 virtual table (section-grain per D12, one row per canonical section). Different content types (10-K, 10-Q, TRANSCRIPT, DECK, ...) are distinguished by a `form_type` column; different providers (edgar, fmp_transcripts, quartr) by a `source` column. Both tables live in one `filings.db` SQLite file (legacy filename retained per terminology note; internal table names are `documents` / `sections_fts`).

**Why:** Cross-source queries ("everything MSFT said about Copilot across filings + transcripts") are the value proposition. Splitting into `filings_fts` + `transcripts_fts` requires UNION in every query and gives up nothing. Keeping metadata in one `documents` table centralizes the supersession chain (D13) and the canonical ticker/CIK/fiscal-period normalization.

**Consequence:** Agent queries use `form_type IN (...)` and `source IN (...)` filters naturally. Adding a new form type or source requires no schema change — just a new enum value. All composition across sources (§5.2) and across families (per-family tool wrappers in §5.1) ultimately queries the same two tables.

### D4. YAML frontmatter for document metadata

**The change:** Every canonicalized markdown file leads with a YAML frontmatter block (§4.2 schema).

**Why:** YAML-frontmatter-plus-markdown is the universal convention (Jekyll, Hugo, Obsidian, Fintool skills, etc.). Parsers are stdlib. Frontmatter carries all the metadata the index table needs, so the file is self-describing — you can rebuild the metadata table from frontmatter alone.

**Consequence:** Edgar_updater's current `> Date: ...` blockquote format is migrated to frontmatter. Existing files get a one-time rewrite during V2.P1 Phase 0.

### D5. Canonical section taxonomy per form type

**The change:** Section headers within filings conform to a locked enumeration per form type (§4.3). Transcripts use `## PREPARED REMARKS` / `## Q&A SESSION` / `### SPEAKER: ...` (§4.4).

**Why:** Section headers become index keys — queries filter by `section = 'Item 7. Management's Discussion and Analysis'`. Freeform headers make this impossible. Edgar_updater already has `_CANONICAL_HEADERS`; this decision formalizes it.

**Consequence:** New form types (8-K items, decks) require a section-taxonomy specification before ingestion. Not a burden — the formats are already well-known.

### D6. Content-addressable immutable filenames

**The change:** Filenames include a short hash of the **full canonical markdown content — frontmatter plus body**: `10-K_2025-FY_a3f9b211.md`. Re-extraction with different output (including frontmatter-only changes like a `supersedes_confidence` promotion from `low` to `high` or a manual supersession override) produces a new file, never an overwrite. Old files stay on disk until garbage collection. Hashing the full file (not body-only) is what makes metadata-only promotions cleanly traversable through the D14 re-extraction path.

**Why:** Debugging and audit. If an agent cites the specific `content_hash` version of a document, that citation is stable forever — even if the `documents` row's `file_path` later updates to point at a re-extracted version, the old file is still readable at its hash-addressed path. New extraction output = new file alongside the old.

**How "current" is determined:** The authoritative pointer is the `documents` row's `file_path`, keyed on `document_id` (D13). Current = what the row points at. The "(ticker, form, period) latest" convenience lookup is a derived SQL query against the `documents` table — `SELECT document_id, file_path FROM documents WHERE ticker=? AND form_type=? AND fiscal_period=? AND is_superseded_by IS NULL`. **If that query returns more than one row, the convenience-overload tools raise `AmbiguousDocumentError`** (per §5.1 contract) — no silent winner selection, no ranked tiebreak. Ambiguity is surfaced, not hidden. Callers must retry with explicit `document_id` (from a prior SearchHit) to disambiguate. Citations that anchor on `document_id` survive re-extraction and amendment cleanly; citations that anchor on the tuple error out visibly when ambiguity arises (per D13, that's why `document_id` is preferred).

**Consequence:** Storage grows over time; garbage collection policy for content-hash versions no longer pointed at by any `documents` row is deferred (Open Q8).

### D7. Shared filesystem, source-of-truth on disk

**The change:** The markdown files live on a single filesystem (local disk, or eventually an EFS mount). Not S3, not CDN, not database BLOB.

**Why:** Agents read files via `open()`. Filesystem is the lowest-friction interface. Deferring S3 avoids premature distribution complexity — the corpus is 6-7 GB, a single disk handles it. If multi-host deployment requires shared storage later, EFS or S3-with-local-cache is additive.

**Consequence:** Must be accessible to the FastAPI backend, the MCP tools, and any batch workers. Single-node is fine for V2.P1; multi-node requires a mount strategy (not in scope here).

### D8. Canary-first rollout

**The change:** Phased ingestion — 5-10 diverse tickers, then ~50-100, then S&P 500, then extended universe.

**Why:** Markdown convention is the single most expensive thing to change after-the-fact. Canary catches taxonomy edge cases (financial-sector 10-Ks, foreign-filer quirks, unusual Q&A structure) before convention lock-in.

**Consequence:** Phase gates are explicit (see §13). No skipping to S&P 500 until canary passes acceptance criteria.

### D9. Per-source tool families over a unified index; cross-source via parallel calls + merge

**The change:** MCP surface is a per-source tool family for each source type — `filings_*` for SEC filings, `transcripts_*` for earnings calls, future `decks_*` for Quartr decks. Each family has four tools: `*_search` (retrieval), `*_read` (navigation of our summarized markdown), `*_source_excerpt` (verification against the authoritative original), `*_list` (metadata discovery). All families are thin wrappers over the single unified FTS5 index (D3). Cross-source queries use parallel per-source calls with client-side merge by BM25 rank — no unified `corpus_search` tool.

**Why:** Two wins at once. Per-source families surface intent clearly ("filings live here, transcripts live here") and avoid overloaded `form_type=[...]` parameters. Four tools per family force the agent into explicit modes — retrieval / navigation / verification are cost-distinct operations with different semantics (our index vs. our summary vs. the original source); collapsing them breaks the trust boundary (see §7). Skipping a unified cross-source tool keeps the system-prompt footprint smaller (better cache hit rate, V2.P5) and makes cross-source intent explicit in agent behavior; the tax is one extra tool call on ~20-30% of queries, which is cheap because BM25 scores are comparable across parallel calls to the same FTS5 index.

**Consequence:** System prompt guidance is required so the agent picks the right family (and calls both when cross-source). Mis-use modes (grep-whole-corpus; skipping verification on high-stakes claims; serializing per-source calls instead of parallelizing) are noticed and corrected. If agent usage later shows cross-source merging is a real struggle, a unified tool can be added additively without breaking per-source tools.

### D10. Corpus does not index structured data

**The change:** XBRL facts, 13F holdings, fund ownership tables, insider trades, market data — none of this is ingested into the filings corpus or indexed in FTS5. It remains in the existing structured-tool surfaces (`get_metric`, `get_metric_series`, `get_institutional_ownership`, `get_insider_trades`, `screen_stocks`, `compare_peers`, etc.). The corpus is narrative-only.

**Why:** Structured data is tabular. FTS5 is a text index — wrong tool. Searching "MSFT" across 13Fs to find holders is trivially true for everyone holding MSFT; the value of 13F data is *structured* (position size, QoQ delta, manager concentration). Existing tools serve that well. Indexing them in FTS5 duplicates ingestion cost, adds no retrieval value, and blurs the corpus's mental model (which is "narrative indexed by ticker + form + section").

**Consequence:** Composition patterns (§6.5) cross the corpus/structured-tool boundary. The agent is responsible for routing queries to the right surface and combining outputs. The corpus and structured surfaces meet via ticker (D11), not via a unified index.

### D11. Canonical ticker is the universal composition key

**The change:** Every tool that returns or accepts tickers uses the canonical form from `SymbolResolver.resolve_identity()` (see `core.security_identity`, committed `1b5917cb`). Tools that need alternative forms internally (CIK for EDGAR, MIC-prefixed for international feeds) convert at their own boundaries — never expose non-canonical forms to the agent or to code execution.

**Why:** Composition (corpus → structured → code-exec) only works if the join key is stable. `SymbolResolver` already handles share classes, international variants, historical tickers, exchange prefixes, cash tickers. Inheriting it costs nothing; reinventing it fragments the key space and makes cross-surface composition unreliable.

**Consequence:** Corpus ingestion passes every extracted ticker through `SymbolResolver` before writing frontmatter. `SearchHit.ticker` is always canonical. Any tool that violates this breaks composition — enforceable via the existing boundary-test layer (`tests/test_architecture_boundaries.py`).

### D12. FTS5 row grain = canonical section

**The change:** The FTS5 virtual table has one row per canonical section within a document, not one row per document. The `documents` metadata table is document-grain; the `sections_fts` FTS5 table is section-grain. A 10-K produces ~10 FTS5 rows (one per Item), a 10-Q ~5 rows, a transcript ~20-50 rows (one per speaker turn).

**Why:** Three wins. (1) Tighter BM25 ranking — retrieval scores passages, not whole documents, so "AI capex in Item 7" doesn't get diluted by the filing's other 200 pages. (2) Natural per-family filters — `speaker_role='CEO'` on transcripts is a simple column filter on the section row, not a substring hack. (3) SearchHit returns passage-level hits directly (section + char_range) without the agent having to re-segment document content. Trade: ~10× more rows in FTS5 (~100K vs ~10K for 1,500 tickers), but total index size is comparable because each row is smaller, and SQLite handles 100K rows trivially.

**Consequence:** Ingestion must parse the canonical markdown into sections before indexing (trivial — the markdown already has canonical headers per D5). SearchHit always has populated `section + char_start + char_end`. Document-grain aggregation (e.g., "how many sections did MSFT's 10-K have?") is a GROUP BY against `sections_fts` — cheap. Retrieval grain contradictions between §2 ("no pre-chunking") and §5.1 (section-level filters) are resolved: sections ARE our chunks, derived from the canonical markdown structure rather than from embedding-driven splits.

### D13. Document identity is `document_id` — `source_accession` or generated equivalent

**The change:** Every canonicalized document has an immutable `document_id` field, and it is the primary key for the `documents` metadata table, the foreign key on `sections_fts`, the anchor for citations (§7.1), and the primary argument to `*_source_excerpt` tools. Format: `{source}:{canonical_source_id}` — `edgar:<accession>` for SEC filings, `fmp_transcripts:<ticker>_<YYYY-QN>` for FMP transcripts, source-specific canonical forms for future sources. `(ticker, form_type, fiscal_period)` is **not** sufficient because amendments (10-K/A), same-day multi-filings (multiple 8-Ks), and concurrent re-filings make that tuple non-unique.

**Why:** Without immutable document identity, the citation chain is anchored on a mutable key that can disambiguate into different documents over time. An agent citing "MSFT 10-K 2024-FY" is ambiguous if an amendment is filed later — does the citation refer to the original or the amendment? `document_id` makes this explicit by construction. Amendments become first-class documents (new `document_id`, `supersedes` pointer to the original) rather than silent overwrites.

**Consequence:** Frontmatter has a `document_id` field (§4.2). `*_source_excerpt` tools take `document_id` as primary argument, with `(ticker, form_type, fiscal_period)` as a convenience overload that errors on ambiguity (§5.1). `is_superseded_by` / `supersedes` columns track the amendment chain. Default `*_search` filters to non-superseded documents; `include_superseded=True` opts in to historical + amendment-diff queries.

### D14. Ingestion is file-first with atomic rename + reconciler

**The change:** Ingestion writes content to `data/filings/.staging/<uuid>.md`, then atomic-renames into the canonical path `{source}/{ticker}/{form}_{period}_{hash}.md`, then opens a SQLite transaction that UPSERTs the `documents` row (keyed on `document_id`) and replaces its `sections_fts` rows. Failures after rename leave the filesystem canonical — the reconciler heals the index from disk. There is no cross-resource rollback; the filesystem is the arbiter.

**Concurrency rules:**
- Same `document_id`, same content → same `content_hash` → same filename → `rename(2)` target is identical, second writer's rename is a no-op. SQLite UPSERT is idempotent on the row.
- Same `document_id`, divergent content (different extraction models, bug fix in flight) → writers race on the `documents` row UPSERT; last-commit-wins on `content_hash` + `file_path`. Both content files remain on disk addressable by their hashes; reconciler logs divergence for ops review. I14 corollary governs this case.
- Different `document_id`s → independent, no coordination needed at the row level.

**Amendment supersession (derived DB-only pointer on the original):**
When an amendment (e.g., 10-K/A) is ingested: (a) the ingestion pipeline derives the supersession link (heuristic or LLM extraction) and writes `supersedes = <original_document_id>` + provenance fields into the amendment's frontmatter (now immutable per I5); (b) a new `documents` row is inserted for the amendment with its own `document_id` and the derived `supersedes` value; (c) the same transaction updates the original row's **DB-only** `is_superseded_by` column according to the deterministic rule below. The original's **frontmatter is not touched**; only its DB row's derived column updates. This preserves I1 (supersedes in frontmatter is sufficient to reconstruct the relationship on rebuild) and I5 (file content is immutable).

**Deterministic multi-amendment rule** (used identically by ingestion-time update and I12 reconciler-time recomputation):

> The original's `is_superseded_by` column points at the amendment that sorts latest by `(filing_date DESC, document_id DESC)` among amendments **whose `supersedes_confidence = 'high'`** — i.e., most recent filing date wins; lexicographically greater `document_id` tiebreaks. Low/medium-confidence links **do not drive `is_superseded_by`**; the original stays visible in default search until the link is promoted to high confidence (by re-extraction with an improved linker, or manual override, which both flow through the normal new-file / new-hash path per D14). This preserves default-search trust: a speculative heuristic link can't silently hide an original. Both sort fields and the confidence field live in frontmatter — the rule is fully derivable and state-independent.

SQL form (used by both reconciler rebuild and ingestion-time update):

```sql
UPDATE documents SET is_superseded_by = (
    SELECT d2.document_id FROM documents d2
    WHERE d2.supersedes = documents.document_id
      AND d2.supersedes_confidence = 'high'
    ORDER BY d2.filing_date DESC, d2.document_id DESC
    LIMIT 1
)
```

Ingestion-time update: when amendment X with `supersedes = Z` is ingested, rerun the above scoped to Z only. If X is `high` confidence and is the new sort-greatest among high-confidence amendments, Z's `is_superseded_by` updates to X; otherwise it stays on whatever was already greater (or NULL if no high-confidence amendment has been linked yet). Ingestion and reconcile converge on the same winner because they use the same rule against the same frontmatter fields.

**Low/medium-confidence visibility.** When a query returns an original that has any low/medium-confidence `supersedes` link pointing at it (from any amendment), the `SearchResponse.has_low_confidence_supersession` flag is set. Agents can opt in to treating such links as current-hiding via `include_low_confidence_supersession=True` on search signatures. UI can render a caveat on the citation ("a low-confidence amendment link may exist"). No information is hidden; the agent/user chooses the trust threshold.

**One-to-many supersession** (two or more amendments against the same original): all amendments are fully indexed as first-class documents with `supersedes = Z` in their frontmatter; reverse queries for "what supersedes Z?" return all of them via `SELECT * FROM documents WHERE supersedes = ?`. The scalar `is_superseded_by` column carries only the latest-by-rule; no information is lost because the `supersedes` side fully enumerates the set. Implementation plan may add a view `is_superseded_by_all(document_id) → list[document_id]` for convenience.

**Zero-downtime index rebuild:**
1. Build the new SQLite DB at `data/filings/.rebuild/<timestamp>/filings.db` from a consistent snapshot of the filesystem (rsync-to-staging or similar).
2. Writers continue against the current production DB during rebuild.
3. When new DB is complete, **briefly pause writers** (~seconds — writer count is small), apply any diffs from the pause window into the new DB, then atomically swap the config pointer / symlink to the new DB path.
4. Resume writers. Queries transition to the new DB at swap time.

This is brief-pause-not-zero-downtime, but the pause window is seconds, writer count is low, and full downtime-free rebuild would require write-log replay that's over-engineered for this workload.

**Why:** True cross-resource rollback across a filesystem and a SQLite database isn't achievable without distributed-transaction machinery (2PC, WAL coordination) that's wildly overbuilt for this use case. File-first with a reconciler is the simple, robust pattern used by systems from mail servers to filesystem indexers.

**Consequence:** I2 restated as file-first, not cross-resource-atomic. I12 formalizes the reconciler contract. I14 corollary handles content-divergence concurrency. The reconciler runs on schedule (hourly/nightly) and on-demand after known failures. Zero-downtime rebuild is brief-pause-swap, not write-log-replay.

### D15. Canonical markdown store is `data/filings/` under a single configured root

**The change:** The corpus lives under one configured root path (`CORPUS_ROOT` env var, default `<repo>/data/filings/`). Existing stores — `Edgar_updater/data/filings/`, `AI-excel-addin/data/filings/`, `~/.cache/edgar-mcp/file_output/` — are unified via explicit migration in Phase 0: the authoritative data moves to `CORPUS_ROOT`, the legacy paths are archived or symlinked for transition, and new ingestion writes exclusively to `CORPUS_ROOT`. The `edgar-mcp` ephemeral cache path remains as-is (it's a per-call scratch location, not authoritative).

**Why:** The two authoritative stores (`Edgar_updater/` and `AI-excel-addin/`) contain duplicated files (both have MSFT 10-Q 2025 samples per Codex review), and leaving them split creates a "which is canonical?" problem that propagates into metadata drift and citation ambiguity. Unifying under one root at the design stage avoids codifying a bifurcated state. Canonical root under `<repo>/data/filings/` matches D7 (shared filesystem) and keeps the store collocated with the code that reads it.

**Migration procedure (Phase 0 task):**

1. **Inventory** — scan both `Edgar_updater/data/filings/` and `AI-excel-addin/data/filings/`; produce a manifest with `(source_file_path, content_hash, parsed_ticker, parsed_form, parsed_period)` per file.
2. **Deduplicate** — for any `(ticker, form, period)` pair present in both locations, compute `content_hash` on the content. Matching hashes → single source of truth, pick `Edgar_updater/` (operational pipeline origin). Divergent hashes → flag for manual review; do NOT silently pick one.
3. **Transform** — for each accepted file: parse existing blockquote date / implicit metadata, synthesize YAML frontmatter including `document_id` (derived from source accession lookup or generated canonical key), write transformed file to `CORPUS_ROOT/{source}/{ticker}/{form}_{period}_{hash}.md` via staging-dir + atomic rename (D14 pattern).
4. **Verify** — compare section count + content hash round-trip; fail migration if any transformed file doesn't re-parse into the same sections.
5. **Cutover — env-var-to-symlink mechanism.** The canonical cutover point is the `CORPUS_ROOT` env var, which resolves (in deployment) to a **symlink** pointing at the physical corpus directory. All readers (MCP tools, Edgar_updater, `AI-excel-addin/`) consume `CORPUS_ROOT` directly (env var) or via the symlink. Cutover procedure: (a) set `CORPUS_ROOT` env var in the process-launch config; (b) atomically update the symlink (`ln -sfn <new_physical_path> $SYMLINK_PATH`) to point at the migrated directory. Rollback reverses step (b) by pointing the symlink back at the legacy-roots location (or removing it and letting readers fall back to their legacy paths via env-var unset). Specific config file locations and the symlink path are implementation details deferred to `FILINGS_CORPUS_INDEX_PLAN.md`; this doc specifies the *mechanism* (env-var-with-symlink cutover), not the concrete strings. `~/.cache/edgar-mcp/file_output/` remains as ephemeral scratch, not migrated.
6. **Archive** — rename legacy directories to `.legacy_YYYYMMDD/` suffix (not delete). Retained for ~30 days then removed after no-regression confirmation.
7. **Rollback procedure** — reverse-order undo, triggered when any of the following post-cutover verifications fail: (i) Phase 0 acceptance criteria not met (§13); (ii) reconciler reports divergent-hash counts higher than a small threshold (e.g., >1% of migrated documents); (iii) any of the 5 canonical canary queries (§13.6) fails to resolve to a cited answer within 24 hours of cutover. Each trigger is actionable and measurable. Substeps:
   a. Pause ingestion writers (they'd be writing to the new `CORPUS_ROOT`; don't let more writes accumulate).
   b. Revert Edgar_updater's output path config back to its legacy value (`Edgar_updater/data/filings/`).
   c. Revert `AI-excel-addin/data/filings/` symlink (if created) to an empty directory or its original location.
   d. Revert any MCP tool / reader config pointing at `CORPUS_ROOT`.
   e. Restore legacy roots: `mv Edgar_updater/data/filings.legacy_YYYYMMDD/ Edgar_updater/data/filings/`; same for `AI-excel-addin/` if that location was archived.
   f. Archive or discard the partially-migrated `CORPUS_ROOT/` content (keep it around as `.failed_YYYYMMDD` for post-mortem, don't delete).
   g. Resume ingestion writers against the restored legacy paths.
   
No data is deleted during the forward migration or rollback — legacy roots are archived, not removed; partial `CORPUS_ROOT` is archived on rollback, not removed. Full post-mortem inspection of both paths is always possible.

Q1 (§12) is closed by this decision.

---

## 12. Open Questions

Explicitly unresolved. Resolved in the implementation plan (`FILINGS_CORPUS_INDEX_PLAN.md`).

**Q1. ~~Which markdown store is canonical?~~** *RESOLVED → D15.* Canonical root is `CORPUS_ROOT` env var (default `<repo>/data/filings/`). Legacy stores (`Edgar_updater/data/filings/`, `AI-excel-addin/data/filings/`) migrate in Phase 0. `edgar-mcp`'s cache path stays as ephemeral scratch.

**Q2. FTS5 tokenizer choice.**
Default `unicode61` with `porter` stemming, or `trigram` for substring matches, or a custom one for financial text (`$4.2B`, `Q1 2024`)? *Lean: default + `porter`, add trigram as secondary virtual table only if specific query patterns demand it.*

**Q3. FTS5 indexed columns.**
Index only `content`? Or also structured metadata (`ticker`, `sector`, `section`) so MATCH can span them? *Lean: content-only in FTS5, structured metadata as indexed regular columns on the `documents` table joined at query time.*

**Q4. ~~Tool-surface collapse — add unified `corpus_search`?~~** *RESOLVED → D9.* Per-source families + parallel-calls-with-merge is locked. Unified `corpus_search` can be added additively post-V2.P1 if agent-usage data shows merging is a struggle.

**Q5. Ingestion trigger.**
Nightly cron against EDGAR RSS + FMP? Event-driven (SEC webhook)? Hybrid? *Lean: nightly batch for V2.P1 Phase 1+, event-driven is a V2.P3 (Feed engine) concern.*

**Q6. Delta detection.**
Is a filing "new" based on SEC accession number, EDGAR last-modified, or content hash diff? *Lean: accession number is canonical (it's SEC's unique identifier); content hash deduplicates within a given accession if re-extracted.*

**Q7. Char offsets in citations.**
`parse_filing_sections()` in `AI-excel-addin/mcp_servers/langextract_mcp/text_utils.py` today exposes char offsets per section — strong citation grounding. Do we include these in `SearchHit`? *Lean: yes, nullable — include when available, agent can use them for precise citation. Costs nothing to carry.*

**Q8. Garbage collection for superseded versions.**
When a filing is re-extracted (new extraction model, bug fix), the old content-hash file stays on disk forever. Acceptable? GC after N days with no references? *Lean: keep forever until disk pressure is real; then GC by retention policy. Not urgent.*

**Q9. Universe definition.**
Where does "S&P 500" come from? Hard-coded list, fetched from somewhere (FMP has a constituents endpoint), or joined with user watchlists? *Lean: small YAML-configured list of universes (S&P 500, S&P 1500, Russell 1000, user watchlists), each with a ticker set. Ingestion walks union.*

**Q10. Extraction failure handling.**
What happens if Gemini returns malformed output for a specific filing? Retry, flag, skip, fallback model? *Lean: retry 2x with backoff, then flag as `extraction_status: failed` in metadata — agent query surface excludes failed rows but they're visible to an ops dashboard.*

**Q11. ~~Transcripts — FMP only for V2.P1, or wait for Quartr?~~** *RESOLVED → §13 Phasing.* A small FMP transcript sample (e.g., the 2-4 transcripts already canonicalized for AAPL) is included in **Phase 0 canary** to exercise the transcripts tool family and cross-source query path at minimum scale. Phase 1/2 remain filings-only (pilot + S&P 500 ingestion focus). **Full transcript ingestion at universe scale starts in Phase 3** (backfilled with 1-year history). Quartr swaps in when V2.P8 lands (Phase 4).

**Q12. What does the system prompt look like?**
The agent-behavior section (§6) specifies the right pattern; the actual prompt wording is an implementation concern but needs to be written carefully because it's what makes the tool surface work. *Defer to implementation plan.*

**Q13. LRU cache in front of `*_source_excerpt`?**
On-demand verification fetches hit external APIs (edgar-financials, FMP) — ~100-500ms latency per call, per-call cost. If repeated verification against the same sections becomes common (UI showing verbatim side-by-side, adversarial eval runs, agent verifying the same claim across a multi-turn conversation), an in-process LRU cache keyed on `(document_id, section, speaker)` with a short TTL (hours) avoids redundant fetches. Cache key uses `document_id` (per D13) rather than ambiguous tuples. *Lean: add only if measured repeat rate >20%, not speculatively.*

**Q14. ~~Sector / industry taxonomy — GICS or source-native?~~** *RESOLVED → §4.6.* Frontmatter commits to GICS with `sector`/`industry` fields; source-native classification retained in a secondary field (`sector_source`) for traceability.

**Q15. Where does the output validator enforce citation rules (§7.5)?**
§7.5 specifies four citation / verification rules the agent must obey — "enforced by output validation" — but the architecture doc does not name the enforcement layer. Candidates with tradeoffs:

- **(a) Agent self-check** — system prompt asks the model to validate its own output before returning. *Cheapest*, weakest (relies on model compliance). Useful as a prompt-level discipline; not sufficient alone.
- **(b) Post-generation middleware** — intercept agent output before delivery, scan for citation markers, reject or flag violations. Moderate complexity; catches most violations. Couples tightly to response format.
- **(c) Gateway-level citation provider** — extend the existing `SanitizingAnthropicProvider` pattern (per `docs/ops/GATEWAY_MULTI_USER_ACTIVATION.md`) with a `CitationValidator`. Consistent with current gateway architecture; covers all API consumers (MCP tools, direct agents, third parties). Strongest backend enforcement point.
- **(d) UI-layer render gate** — frontend refuses to render a response with missing or malformed citations (Fintool's pattern: *"missing/malformed citations block render"*). Strongest user-facing guarantee; does not cover API consumers.

*Lean: layered defense.*
- **(a) system prompt always on** as the first-line discipline.
- **(c) gateway citation provider** as the canonical backend enforcement point (catches API consumers, not just UI).
- **(d) UI render gate** as the user-facing net (catches anything the backend validator missed).
- **(b) middleware** skipped unless (c) proves insufficient in practice.

Exact validator mechanism — regex vs. structured output vs. LLM-judge — deferred to implementation plan. The architecture commits to *having* a validator at the gateway layer (c); the plan owns the *how*. Without this resolution, the §7 trust architecture is correct in design but unenforced in production.

---

## 13. Phasing

### Phase 0 — Canary (8-12 tickers + filings edge cases)

**Tickers and document edge cases (proposed):**
- **Tech, canonical clean:** AAPL, MSFT (baseline 10-K + 10-Q + earnings-call transcripts)
- **Tech, share-class complexity:** GOOG (dual-class structure)
- **Diversified conglomerate, unusual structure:** BRK.B (embedded Buffett letter, unusual sections)
- **Financials, different taxonomy:** JPM (regulatory disclosures, Basel III language, credit provisions)
- **Energy, XBRL-heavy:** XOM (commodity accounting, segment reporting)
- **Consumer mid-cap:** TGT (standard retail 10-K as control)
- **Small-cap, spartan filings:** a microcap to stress edge cases (minimal sections)
- **Edge case: amendment** — include at least one `10-K/A` or `8-K/A` where the original and amendment are both in the corpus. Tests supersession chain + document_id disambiguation.
- **Edge case: same-day multi-8-K** — include a ticker with multiple 8-Ks filed on the same day (common around earnings + material events). Tests that `document_id` = accession disambiguates cleanly.
- **Edge case: proxy statement** — one DEF 14A to stress proxy-specific section taxonomy before it silently breaks ingestion later.

**Work:**
- Formalize markdown convention (§4.2-4.4) — write the spec doc
- Migrate existing AAPL/MSFT samples from `Edgar_updater/data/filings/` and `AI-excel-addin/data/filings/` into `CORPUS_ROOT` with YAML frontmatter + ticker subdirectories (D15 migration)
- Build the ingestion driver — writes frontmatter + section-canonicalized markdown for the canary set, including amendment + multi-filing cases
- Include a small transcript sample in the canary (e.g., 2-4 AAPL/MSFT earnings calls already canonicalized) to exercise the transcripts family and cross-source queries at minimum scale (per Q11 resolution)
- Build `documents` metadata table + `sections_fts` FTS5 virtual table (D12 section grain)
- Implement file-first-with-atomic-rename ingestion (D14) and the reconciler (I12)
- Build full tool families: `filings_search` + `filings_read` + `filings_source_excerpt` + `filings_list`, **plus** `transcripts_search` + `transcripts_read` + `transcripts_source_excerpt` + `transcripts_list`. All four per-family tools are mandatory for Phase 0 (needed by canary queries 4 and 7).
- Implement tool-boundary input validation (I13)
- Manual run of 8 canonical queries (5 narrative + 3 edge-case) per §13.6

**Acceptance criteria:**
- All canary tickers and edge-case documents extract cleanly with correct frontmatter + section headers + immutable `document_id`.
- Amendment chain works: querying the original filing's section returns the original; `include_superseded=True` also surfaces the amendment; citations made against the pre-amendment `document_id` still resolve.
- Same-day multi-8-K: disambiguation by `document_id` works; convenience overload errors with `AmbiguousDocumentError`.
- 5 canonical queries + 3 edge-case queries (see §13.6) return correct, citable results.
- Agent can iterate retrieve→read→synthesize without prompt gymnastics.
- Reconciler successfully heals a synthetic drift case (delete an FTS5 row by hand; reconciler restores it).
- No markdown convention issues surface that require schema change. If one does, fix and re-run extraction (still cheap at canary scale).

**Exit:** convention is locked; `document_id` / amendment / concurrency behaviors validated; scale-up is safe.

### Phase 1 — Pilot (~50-100 tickers)

**Universe:** Top 50 S&P Tech + ~25 Financials + ~25 Healthcare/Consumer. Tests cross-sector taxonomy + ranking quality.

**Work:**
- Add ingestion scheduler (nightly cron or `launchd` / `services-mcp`).
- Add delta-detection (accession number + content hash).
- Add extraction failure handling (retry, flag).
- Harden the reconciler (was stubbed in Phase 0) for production schedule + content-divergence logging.
- Exercise the query surface with 20+ realistic agent queries. Review ranking quality.

**Acceptance:**
- ≥95% of target filings extracted cleanly.
- FTS5 ranking surfaces correct answers in top 5 for 80%+ of test queries.
- Nightly ingestion completes in <2 hours.
- Agent dogfood: 10 realistic queries succeed end-to-end with no manual intervention.

### Phase 2 — S&P 500 (~500 tickers)

**Universe:** Full S&P 500.

**Work:**
- Production ingestion rollout.
- Monitoring: extraction success rate per ticker, ingestion latency, FTS5 query latency.
- Documentation: how to add a new ticker universe, how to re-extract a single ticker, how to rebuild the index.

**Acceptance:**
- Corpus covers ≥95% of S&P 500 tickers with recent 10-K + last 4 10-Qs.
- Median FTS5 query latency <50ms.
- Monitoring dashboard in place.

**Convention lock-in:** after Phase 2, changing the markdown convention requires re-running ~500 tickers ($30-$100, ~1 hour wall clock). Still doable, but expensive enough that changes should be deliberate.

### Phase 3 — Extended universe + transcripts

- Extend to ~1,500 tickers (S&P 500 + S&P 1500 + user watchlists).
- Add FMP transcript ingestion with the same convention.
- No architectural changes from Phase 2.

### Phase 4 — Quartr integration (V2.P8)

- Adds Quartr as a new `source` (decks, faster transcripts, IR events).
- Zero architectural changes — new converter, new `source` value, slot into existing index.
- Deprecation of FMP transcripts possible if Quartr coverage is complete.

### Track B (parallel) — Citation-first Q&A tool (V2.P2)

Not a new ingestion phase — a new *consumer* of the corpus. Builds a user-facing tool that takes a natural-language question about a specific company or universe and returns a cited answer. Depends on V2.P1 Phase 2 (corpus must exist) but doesn't gate further ingestion work.

### 13.6 Canary test queries (proposed)

Each must succeed end-to-end (retrieve → read → synthesize → cite) before Phase 1:

1. **Broad cross-ticker qualitative:** "What AI investments are AAPL, MSFT, GOOG, and META discussing?"
2. **Single ticker longitudinal:** "How have MSFT risk factors evolved across the last 4 quarters?"
3. **Cross-section within filing:** "What does AAPL's FY2025 10-K say about both services revenue growth (Item 7) and related risks (Item 1A)?"
4. **Cross-source:** "Where has BRK.B discussed capital allocation — in filings or transcripts?" Exercises parallel-call merge per §5.2. Phase 0 canary includes the small transcript sample per Q11 resolution, so this query is mandatory.
5. **Negative case:** "What do these companies disclose about quantum computing?" (expected: few/no matches → agent reports honestly, doesn't hallucinate)

Plus three edge-case queries to exercise D13 (document identity) and D14 (ingestion atomicity):

6. **Amendment chain:** For the canary's 10-K/A pair: "Show me the differences between the original 10-K and the amendment" — expected: both documents are individually retrievable by `document_id`; search with `include_superseded=True` returns both; citations on the original still resolve even after the amendment lands.
7. **Same-day multi-filing:** For the canary's multi-8-K day: "What 8-Ks did [ticker] file on [date]?" — expected: `filings_list` returns multiple distinct `document_id`s; convenience-overload `filings_source_excerpt(ticker, '8-K', date)` errors with `AmbiguousDocumentError` listing the specific `document_id`s.
8. **Reconciler heal — actual ingestion failure mode:** Simulate the D14 failure case directly: let ingestion rename a markdown file into `CORPUS_ROOT` successfully, then crash/abort before the SQLite transaction commits (e.g., kill the worker mid-transaction). Verify that (a) the next reconciler run detects the orphaned file, (b) inserts the `documents` row + `sections_fts` rows, and (c) subsequent queries return the now-indexed content. Also test the content-divergence case: two workers produce different content_hashes for the same document_id; verify last-commit-wins on the row, both files remain on disk, and the reconciler logs a content-divergence event.

9. **Low-confidence supersession gating:** Include an amendment whose `supersedes_confidence = 'low'` in the canary (e.g., manually produce a synthetic amendment with a heuristic-quality link to an original). Verify: (a) default `filings_search` returns the original as non-superseded (`is_superseded_by IS NULL` in the DB because the link is low-confidence); (b) the response's `has_low_confidence_supersession` flag is True and each affected SearchHit carries its own flag; (c) retrying with `include_low_confidence_supersession=True` hides the original; (d) promoting the link to `high` via re-extraction (producing a new file / new content_hash per D14/I5) causes subsequent default searches to hide the original; (e) reconciler rerun arrives at the same `is_superseded_by` value as ingestion-time derivation did (convergence check).

### 13.7 External dependencies

TODO items that gate specific V2.P1 capabilities. Called out explicitly so the implementation plan can sequence around them. **None block Phase 0 itself** — the canary queries above are single-ticker narrative (queries 2, 3, 5), intra-corpus cross-ticker without fiscal-period joins (queries 1, 4), or document-identity edge cases (queries 6-8) — none of which depend on V2.P7 cross-company fiscal calendar normalization. Cross-company period-joining composition (Patterns 2/3 in §6.5) is what hits the V2.P7 limit and is not exercised until Phase 3.

- **V2.P7 — Fiscal calendar normalization DB** (`DEFERRED`). Required for cross-company period joins — Composition Patterns 2 and 3 in §6.5. Without it, *"capex for the quarter where Copilot was discussed"* can be off by a quarter across tickers with different fiscal calendars. **Pattern 1 (text-first, structured-later with per-ticker lookups) works without it** — the §8.4 end-to-end flow is explicitly Pattern 1 for this reason. Phase 3 (extended universe + transcripts) starts to hit this limit if cross-company fiscal joins are common in real queries.
- **V2.P5 — Stable-prefix prompt caching** (`ACTIONABLE`). Not a blocker but materially affects per-query cost once query-tool schemas flow through the agent system prompt. Can happen in parallel with V2.P1 Phase 1-2.
- **V2.P4 — Adversarial eval harness** (`DEFERRED`). Not a blocker for Phase 0-2 but required before `filings_source_excerpt` can be recommended as a verification mechanism for customer-facing claims in paid/enterprise tiers. Dogfooding mitigates in the interim.
- **`SymbolResolver` / `SecurityIdentity`** (✅ shipped, commit `1b5917cb`). Dependency is satisfied — corpus inherits it per D11.

---

## 14. Out of Scope

Explicitly *not* covered by this document:

- **Vector databases / embeddings.** See D2.
- **Real-time / sub-minute ingestion.** V2.P1 is batch-nightly. Sub-minute feeds are V2.P3 (Feed engine).
- **User-specific corpora / access control on filings.** Corpus is public-document shared.
- **Non-English filings / international issuers.** US-domiciled SEC filers only for V2.P1. International via Quartr later.
- **Structured XBRL data, 13F holdings, ownership tables, insider trades, market data.** Stay in existing structured-tool surfaces (`get_metric`, `get_metric_series`, `get_institutional_ownership`, `get_insider_trades`, `screen_stocks`, etc.). Corpus composes with them via canonical ticker — see D10, D11, and §6.5. Not indexed in FTS5.
- **Full-text indexing of agent-generated content** (research notes, thesis docs). That's the research workspace (separate architecture, `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md`).
- **Cross-corpus joins** (e.g., "show me filings by companies whose portfolio I own"). Agent can orchestrate, but the corpus itself is sector/universe-agnostic.
- **Production eval harness.** Adversarial grounding, ticker-disambiguation evals, etc. — V2.P4 (separate).
- **Prompt caching optimization** for query tool schemas. V2.P5 (separate).

---

## 15. What Exists Today (Grounding)

For reference — current-state inventory so the implementation plan extends rather than duplicates.

### Already shipped

- **`Edgar_updater`** — canonicalizes SEC filings to markdown via `section_parser.py` + LLM extraction in `extraction.py`. Writes to `Edgar_updater/data/filings/`. Section-aware (`_CANONICAL_HEADERS`, `SECTIONS_10K`, `SECTIONS_10Q`). Table-to-markdown conversion. Concurrent workers (3), transient retry logic.
- **Transcripts canonicalization** — already producing transcript markdown (AAPL 1Q25, 4Q25 samples present). `## PREPARED REMARKS` / `## Q&A SESSION` / `### SPEAKER:` convention in place.
- **`edgar-mcp`** — API-proxy MCP server exposing `get_filings`, `get_financials`, `get_metric`, `get_metric_series`, `list_metrics`, `search_metrics`, `get_filing_sections`, `extract_filing_file`, `list_extraction_schemas`. Stateless; reaches remote EDGAR API. Writes per-call markdown to `~/.cache/edgar-mcp/file_output/`.
- **`langextract_mcp`** — `parse_filing_sections()` returns `SectionMap: dict[str, tuple[str, int, int]]` — section header → (text, start offset, end offset). Char offsets already supported.
- **`fmp-mcp` `get_earnings_transcript`** — live-fetched per-speaker segments (no persistence).
- **Fiscal calendar metadata** — per-filing via Edgar_updater. Not yet normalized cross-company (V2.P7).

### Verification path — already present infrastructure

The source-link + on-demand-verbatim pattern in §7 leverages tools that already exist. Each per-family `*_source_excerpt` is a thin wrapper over its source's existing fetcher — no new ingestion or API integration required:

- `filings_source_excerpt` → `edgar-financials.get_filing_sections()` — verbatim EDGAR section text.
- `transcripts_source_excerpt` → `fmp-mcp.get_earnings_transcript()` — verbatim transcript text per speaker segment.
- Future `decks_source_excerpt` → Quartr fetcher when V2.P8 integration lands.

Adding a new family requires a new fetcher binding, not changes to existing families. No central dispatcher, no shared registry.

So the entire verification subsystem is a thin wrapper over infrastructure already shipped for filings and transcripts. No new external dependencies.

### Partially shipped

- **Markdown convention** — de facto convention exists (see Edgar_updater outputs) but not formalized. Today uses `> Date: ...` blockquote, not YAML frontmatter. Filename is flat (`AAPL_10K_2025_d4de4a6e.md`), not ticker-subdirectoried. No `document_id` field. No supersession tracking. Migration to the locked convention is a Phase 0 task (D15).
- **Dual storage locations** — identical canonicalized content exists at `Edgar_updater/data/filings/` AND `AI-excel-addin/data/filings/` (verified by Codex review — same MSFT 10-Q 2025 file present in both). Needs Phase 0 consolidation to `CORPUS_ROOT` per D15.
- **LANGEXTRACT_REFACTOR_FILING_INGESTION_PLAN** — in-flight per BETA_RELEASE_GAP_AUDIT T2.6. Related but tangential (concerns `file_path` wiring in tool metadata, not FTS5).

### Not started

- SQLite `documents` metadata table (document-grain, D13 document_id PK + supersession pointers).
- `sections_fts` FTS5 virtual table (section-grain per D12).
- Per-source MCP tool families — `filings_*` (search / read / source_excerpt / list), `transcripts_*` (same four).
- Ingestion pipeline: file-first atomic rename + UPSERT + reconciler (D14, I12).
- Ingestion scheduler / universe config / delta detection.
- YAML frontmatter migration for existing files (D15 step 3).
- Dual-location consolidation into `CORPUS_ROOT` (D15 steps 1-7).
- Cross-source query agent behavior prompt + system-prompt guidance (§6.2).
- Tool-boundary input validation layer (I13).

---

## Appendix A — Fintool Inference (soft comparison)

Fintool's product has been discontinued post-Microsoft acquisition (2026-04-17), so direct feature comparison is not possible. The following is inferred from our research corpus at `docs/research/fintool/` — primarily `architecture-learnings.md` and `product-features.md` — which compile publicly-posted technical content from Nicolas Bustamante's blog, Braintrust / Datadog / ZenML case studies, and HN discussions.

| Dimension | Fintool (documented) | This design |
|---|---|---|
| Corpus scale | 70M chunks, 2M docs, 5TB | ~10K docs / ~100K section rows, ~2-3 GB |
| Sources | SEC filings, transcripts, 13Fs, news | SEC filings + FMP transcripts + (Quartr later) |
| Ingestion cadence | 3,000 filings/day via Apache Spark | Nightly batch, ~10-50 new filings/day |
| Retrieval layer (old) | 500GB Elasticsearch + embeddings + Cohere rerank | N/A (abandoned by Fintool; we never build it) |
| Retrieval layer (new) | Filesystem + ripgrep + frontier context | FTS5 + filesystem; agent navigates with reads |
| Normalization | Markdown + CSV + JSON metadata per doc | Markdown + YAML frontmatter (same principle) |
| Skill surface | Markdown + YAML frontmatter, SQL-discovered | Out of scope here (see V2.P6) but analogous |
| Citation model | Filing + section + exact table/line; missing citation blocks render | Filing + section + (optional char offsets); cite-everything norm |
| Fiscal normalization | 10K+ company fiscal calendar DB | V2.P7 (planned; bootstraps from EDGAR metadata) |
| Eval gate | ~2,000 test cases, CI-block on >5% regression | V2.P4 (planned) |

**What's different for us:**
- Smaller universe — we start at 1,500 tickers vs. their 8,000+. Coverage can be tighter.
- Relaxed latency — nightly batch vs. sub-minute. No streaming ingestion infra.
- Solo/prosumer economics — no need for Spark, no paid-customer-trust constraint pushing us toward Elasticsearch parity.
- Single-user → eventual multi-user — we can ship single-tenant and add multi-user later (corpus is public docs, so multi-user is a permission-on-ingestion-priority concern, not a data-isolation one).

**What we're adopting (strongly supported by research corpus):**
- Three-canonical-formats principle — markdown + CSV-in-tables + structured metadata per doc.
- Filesystem-is-truth architecture — the single most cited architectural move in Fintool's public writing (RAG Obituary essay).
- Grep/read agent pattern for navigation — "Claude Code model" is explicit in the source material.
- Citation-first synthesis — missing citations blocking render is a documented Fintool UX rule.
- Skills-as-markdown convention — applied here to corpus content format; the skills-as-product framing applies more directly to V2.P6.

**What we're adopting (soft alignment — our choices, Fintool-consistent but not explicitly prescribed):**
- Per-source tool families (`filings_*`, `transcripts_*`). Fintool's public writing describes a unified agent with access to multiple sources but does not specify the tool-surface shape we've picked. Our decision is informed by the documented preference for smaller tool surfaces + prompt-cache hit rate, but the specific family split is ours.
- Parallel-calls-with-BM25-merge for cross-source retrieval. Fintool's documented architecture uses a single Elasticsearch index post-pivot (per available material); we use SQLite FTS5 with per-source-filter tools. Not contradicted by the research corpus, but also not directly derived from it.
- Section-grain FTS5 rows (D12). Fintool's chunking strategy was documented for the *old* embedding stack ("hierarchical structure preservation, 10-K by section, transcripts by speaker turn"); post-RAG-Obituary they moved to filesystem+grep without documented re-chunking. Our section-grain choice is an independent judgment.

**What we're consciously *not* doing (differences from Fintool's end-state):**
- No 500GB Elasticsearch intermediary (they abandoned it too — we skip the detour).
- No Apache Spark ingestion (overkill at our scale).
- No GraphRAG / knowledge graphs (they were "exploring" — unclear they shipped; we defer).
- No multi-provider real-time routing (deferred to gateway concerns).

The Fintool research corpus **strongly supports** the filesystem-is-truth, no-vector-DB, citation-first architecture. It **does not dictate** our specific tool-surface shape or merge strategy — those are our design choices that happen to be Fintool-consistent, not Fintool-derived. Treat the comparison as *compatible* rather than *validating*.
