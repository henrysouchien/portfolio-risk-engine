# Document Corpus — Implementation Plan (Phase 0 Canary)

**Status:** Codex R1 findings applied — ready for R2
**Last updated:** 2026-04-22

**Codex review history:**
- R1 — FAIL with 2 CRITICAL + 6 MAJOR + 3 MINOR. Resolved by: (1) adding transcript ingestion tasks A6-A7 with `### EXCHANGE` header removal + YAML frontmatter injection; (2) reworking `filings_source_excerpt` to fetch the accession-keyed `source_url_deep` HTML directly instead of translating back to `(ticker, year, quarter)` (which violates D13); (3) reworking A0 to be a self-contained Anthropic+OpenAI wrapper in Edgar_updater with no risk_module package dependency; (4) adding META to canary ticker list (Q1 requirement); (5) removing invalid `CREATE INDEX` on FTS5 virtual table from B1 schema; (6) introducing A8 as the single authoritative file-write orchestrator (collapses file-write ownership split between Block A and B2); (7) explicit `extraction_status` value rules — Phase 0 writes only `'complete'`, other values reserved for Phase 1; (8) splitting L-sized B4 reconciler into B4a-e pieces (walker, db_sync, sections_fts sync, supersession recompute, orchestrator); (9) fixing low-confidence SQL sketch in C1 so `include_low_confidence_supersession=True` actually hides originals (not the inverse); (10) parametrizing F3 rollback drill for tmp_path execution.

**Scope:** Phase 0 canary of V2.P1 (Document corpus FTS5 index). Ships 8-12 canary tickers into `CORPUS_ROOT` with locked YAML frontmatter + canonical sections, a working SQLite `documents` + `sections_fts` index, 8 per-family MCP tools (`filings_*` + `transcripts_*`), and end-to-end validation against the 9 canary queries from the architecture doc.

**Implements:** `docs/planning/CORPUS_ARCHITECTURE.md` (Codex PASS R7 + Q15 touch-up). This plan is strictly downstream of that architecture — it does not re-open any locked decisions (D1-D15) or invariants (I1-I14). If a locked item proves unimplementable, the architecture doc is the place to push back.

**References:**
- `docs/planning/CORPUS_ARCHITECTURE.md` — architecture (locked)
- `docs/TODO.md` V2.P1 — TODO entry, expanded scope noted
- `memory/project_corpus_architecture_locked.md` — context, headline bets, top 5 impl-plan risks from R7
- `Edgar_updater/` — existing canonicalization pipeline (reused, extended)
- `edgar-mcp/` — existing MCP surface for verbatim source fetch
- `fmp-mcp-dist/fmp/server.py` — existing MCP surface for transcript verbatim fetch
- `AI-excel-addin/mcp_servers/langextract_mcp/text_utils.py` — existing `parse_filing_sections()` with char offsets

---

## 1. Scope and Non-Scope

### 1.1 In scope — Phase 0 canary

- 8-12 canary tickers ingested into `CORPUS_ROOT` per D15 migration procedure
- Canary edge cases: one amendment (10-K/A), one same-day multi-8-K day, one DEF 14A proxy
- YAML frontmatter convention formalized (§4.2 of arch doc) and written to all canary files
- `documents` SQLite table + `sections_fts` FTS5 virtual table created, populated, and queryable
- File-first atomic-rename ingestion primitive (D14) with UPSERT + `ON CONFLICT` idempotency
- Reconciler module (I12) that heals filesystem/index drift with deterministic tie-breaks
- `SearchResponse` + `SearchHit` + `AmbiguousDocumentError` typed return contracts (§5.1)
- 8 MCP tools: `filings_{search, read, source_excerpt, list}` + `transcripts_{search, read, source_excerpt, list}`
- Tool-boundary input validation (I13): query length, universe size, limit cap, path canonicalization
- Cross-source parallel-call + BM25 merge pattern (§5.2) exercised by canary query 4
- Supersession handling: `supersedes` in frontmatter (manually authored for the canary amendment case — amendment linker deferred); DB-only `is_superseded_by` derivation using the deterministic scalar rule (D14); `has_superseded_matches` / `has_low_confidence_supersession` response-envelope hints
- End-to-end validation via all 9 canary queries from §13.6 of the architecture doc
- Dual-location (Edgar_updater + AI-excel-addin) consolidation per D15 with archive + verify

### 1.2 Explicitly deferred (NOT Phase 0)

- **Phase 1-4 scale-up** — nothing beyond the canary set. Pilot (~50-100 tickers), S&P 500, extended universe, Quartr are separate plans.
- **Amendment linker (automated)** — Phase 0 uses a **manually-authored** `supersedes` pointer for the canary's amendment edge case. Automated ingestion-time derivation (heuristic / LLM extraction of the amendment's explanatory note + confidence scoring) is a Phase 1 task. This simplifies Phase 0 scope and lets the canary validate all the downstream semantics (confidence gating, deterministic multi-amendment rule, retroactive DB-only `is_superseded_by`) before we invest in the linker.
- **Gateway citation provider (Q15)** — `SanitizingAnthropicProvider` doesn't exist in the risk_module codebase today (grep confirmed). Standing up a gateway-layer output validator is net-new plumbing and is deferred to Phase 1. Phase 0 enforcement is: (a) system-prompt guidance (weakest) + (b) canary-test assertion that all 9 queries produce cited responses + (c) per-hit citation fields on `SearchHit` that make downstream validation trivial when the gateway provider lands.
- **Full-universe ingestion scheduling** — no cron, no delta-detection, no event-driven triggers. All Phase 0 ingestion is one-shot batch against the canary ticker set.
- **Zero-downtime rebuild machinery** — D14's brief-pause-swap is specified at the architecture level; Phase 0 ingests once and does not exercise rebuild-while-queries-are-live. The reconciler is implemented (for drift-heal canary tests), but the swap-pointer mechanism waits until Phase 1 when ongoing writes are real.
- **Production eval harness (V2.P4)** — adversarial grounding tests, ticker disambiguation evals, etc. are separate.
- **Universe config** (YAML-configured list of S&P 500, watchlists) — Phase 0 uses a hardcoded canary ticker list in the plan itself.

### 1.3 Why this scope

Phase 0 is the **convention lock-in** phase. The things that are cheap to change before canary ingestion (markdown schema, section taxonomy, frontmatter fields, tool return shapes) are expensive to change after Phase 1's S&P 500 ingestion. Phase 0's job is to produce a working end-to-end stack on 8-12 tickers with enough edge-case coverage that schema mistakes are discovered cheaply. Everything downstream (pilot, S&P 500, transcripts scale, Quartr) inherits the Phase 0 schema; everything upstream of the schema (amendment linker sophistication, gateway provider, ops scheduling) is better built after the schema is proven.

---

## 2. Success Criteria

Phase 0 ships when all of the following are true:

1. **All 8-12 canary tickers are fully ingested** into `CORPUS_ROOT` with valid YAML frontmatter + canonical section headers per §4.2-§4.4 of the arch doc. Validation: schema-check script passes for every `.md` file.
2. **All 9 canary queries from §13.6 pass end-to-end** (retrieve → read → synthesize → cite). Each query has an explicit acceptance criterion. See §7 of this plan.
3. **Reconciler convergence** — running the reconciler against a fresh DB built from `CORPUS_ROOT` produces the same query results as the live-ingested DB (modulo timestamps). Verifies I3 (logical equivalence).
4. **Convention lock signal** — no schema issue discovered during canary that requires re-extraction at larger scale. If one surfaces, we iterate the convention and re-run canary before scale-up.
5. **Dual-location consolidation complete** per D15. Legacy `Edgar_updater/data/filings/` and `AI-excel-addin/data/filings/` archived under `.legacy_YYYYMMDD/`; new writes go to `CORPUS_ROOT`; rollback tested without actually rolling back.
6. **8 MCP tools functional** — `filings_*` + `transcripts_*` families, all four operations per family, smoke-tested via pytest + a manual MCP-dispatch verification.
7. **Citation fields populated** on every `SearchHit` — `document_id`, `source_url`, `source_url_deep`, `file_path`, `char_start`, `char_end`, `section`. Downstream Q15 validator can assert on these when it lands.

---

## 3. Architecture Mapping

Which arch-doc D/I each task implements. Ensures traceability.

| Arch item | Implemented by task block |
|---|---|
| D1 (single shared corpus) | Block B (schema has no user_id) |
| D2 (no vector DB) | N/A (negative — nothing to do) |
| D3 (one SQLite, documents + sections_fts) | Block B |
| D4 (YAML frontmatter) | Block A |
| D5 (canonical section taxonomy) | Block A (inherits Edgar_updater's `_CANONICAL_HEADERS`) |
| D6 (content-addressable filenames, full-file hash) | Block A (extend `_canonical_hash8`) + Block C |
| D7 (shared filesystem) | Block F (CORPUS_ROOT under repo data/) |
| D8 (canary-first) | This entire plan is the canary |
| D9 (per-source tool families) | Block C |
| D10 (corpus doesn't index structured data) | N/A (negative) |
| D11 (canonical ticker via SymbolResolver) | Block A (ingestion wrapper calls SymbolResolver) |
| D12 (section-grain FTS5) | Block B + Block A (char-offset backfill via `parse_filing_sections`) |
| D13 (document_id = source identity) | Block A (frontmatter) + Block B (schema PK) |
| D14 (file-first ingestion) | Block B + Block E |
| D15 (CORPUS_ROOT + migration) | Block F |
| I1 (filesystem is truth) | Block B (reconciler rebuilds from disk) |
| I2 (file-first UPSERT) | Block B |
| I3 (logical equivalence rebuild) | Block B + success criterion 3 |
| I4 (versioned convention) | Block A (`extraction_pipeline` field) |
| I5 (content-addressable immutable files) | Block A + Block C |
| I6 (canonical section headers) | Block A |
| I7 (valid YAML frontmatter) | Block A + Block B (validator) |
| I8 (metadata-column filter before MATCH) | Block C (query construction) |
| I9 (citation round-trip) | Block C (file_path in SearchHit) |
| I10 (every citation has source_url) | Block A + Block C |
| I11 (canonical ticker on boundaries) | Block A |
| I12 (reconciler) | Block B |
| I13 (tool-boundary validation) | Block C |
| I14 (document identity immutable, content mutable) | Block A + Block B |
| Q15 (validator location) | Deferred to Phase 1 — system prompt + canary test for now |

Every D/I has at least one task covering it. Missing rows would be a plan gap.

---

## 4. Task Blocks

Seven blocks, ~20 concrete tasks, rough sequencing with dependencies called out. Each task has: goal, files touched, tests, depends-on, effort estimate (S/M/L ≈ <4h / 4-16h / >16h).

### Block A — Canonicalization + frontmatter (ingestion-side convention)

Lock the markdown convention, swap the extraction model, and wire Edgar_updater to emit spec-compliant output.

#### A0. Swap Edgar_updater's LLM client to risk_module's CompletionProvider

**Goal:** Replace Edgar_updater's hardcoded Gemini 2.5 Flash client with a small **self-contained** Anthropic/OpenAI wrapper in Edgar_updater — **no cross-package dependency on risk_module**. `CompletionProvider` exists at `providers/interfaces.py:205` as a design pattern worth matching, but risk_module's only packaged client in-tree is `risk-client` (HTTP, not LLM), so Edgar_updater cannot import it cleanly. Phase 0 defaults to **Claude Haiku 4.5**. Gemini has been unreliable in recent operation; Haiku is the reliability floor we want for a long-lived corpus.

**Rationale:**
- Edgar_updater's retry / concurrency / fetch / section-parsing infra is real and worth preserving; only the LLM call changes.
- Self-contained wrapper avoids a packaging-dependency problem between Edgar_updater and risk_module. The wrapper's *shape* follows risk_module's `CompletionProvider` pattern (protocol-like interface, env-var-driven, swappable implementations) but the code lives in Edgar_updater. If we ever need to share, we extract to a published utility package — Phase 1+ concern.
- `LLM_PROVIDER` env var makes model swap deploy-time rather than code change — Phase 1+ can bump specific filings to Sonnet via routing logic without revisiting this work.
- Cost delta: Phase 0 canary ~$2 (was ~$0.30 on Gemini Flash); Phase 2 full corpus ~$1,500 (was ~$250). Acceptable one-time spend for reliability.

**Files touched:**
- `Edgar_updater/edgar_parser/llm_client.py` (new) — self-contained Anthropic + OpenAI client wrapper. Exports `CompletionClient` protocol + `AnthropicClient` + `OpenAIClient` impls + `get_default_client()` factory reading `LLM_PROVIDER` env var (default `anthropic`) + model override (default `claude-haiku-4-5-20251001`). Direct SDK calls, no risk_module import. ~200 lines target.
- `Edgar_updater/edgar_parser/extraction.py` — replace the Gemini-specific invocation (lines 29, 150+) with an injected `CompletionClient` instance from `llm_client.py`. Existing retry/concurrency loops wrap the new call path.
- `Edgar_updater/pyproject.toml` — add `anthropic>=0.40` and `openai>=1.50` as optional deps (current deps listed in the package are our baseline to extend).

**Phase 0 default config:**
- `LLM_PROVIDER=anthropic`
- Model: `claude-haiku-4-5-20251001`
- Retry: keep Edgar_updater's existing 4-attempt exponential backoff; Anthropic SDK errors map cleanly onto its transient-retry classification
- Prompt caching: if Anthropic's cache-control feature is available in the provider impl, enable it for stable-prefix sections of the extraction prompt (matches V2.P5 direction; small win per-doc but adds up at scale)

**Depends on:** nothing. Can start before A1.

**Tests:**
- `Edgar_updater/tests/test_llm_client_swap.py::test_completion_client_dispatch` — monkeypatch `CompletionClient` to return canned output; verify extraction pipeline consumes it correctly.
- `Edgar_updater/tests/test_llm_client_swap.py::test_retry_on_rate_limit` — raise `anthropic.RateLimitError` from the wrapper; verify Edgar_updater's exponential backoff kicks in.
- `Edgar_updater/tests/test_llm_client_swap.py::test_provider_env_var_override` — set `LLM_PROVIDER=openai`; verify OpenAI client instantiated.
- Smoke test against canary AAPL 10-K: real Anthropic API call, verify output is structurally valid (correct section headers per convention) and triggers no downstream task failures. **Do NOT require "structurally equivalent to Gemini output"** — Claude may produce different section lengths or phrasings. The schema and section-taxonomy compliance is what matters; surface-text equivalence is not a goal.

**Effort:** M.

**Follow-ups deferred to later phases:**
- Per-filing model routing (Sonnet for complex XBRL-heavy filings) — Phase 1 optimization.
- Batch API support for Anthropic (currently Anthropic's batch tier is message-batches API, different shape) — Phase 2 cost optimization.
- Re-evaluating Gemini or other providers — if a specific future version proves reliable, the CompletionProvider abstraction makes the swap a one-line change.

#### A1. Write the markdown convention spec

**Goal:** Single-source-of-truth for the file format. Codifies §4.2-§4.4 of the arch doc into a validator-friendly form.

**Deliverable:** `docs/planning/completed/CORPUS_MARKDOWN_CONVENTION.md` (short — ~150 lines). Frontmatter field list with types + required/optional markers; canonical section taxonomy per form type (10-K, 10-Q, 8-K, DEF 14A, TRANSCRIPT); file path layout; content_hash definition (full-file SHA-1 including frontmatter, first 8 hex chars); `document_id` format per source.

**Depends on:** nothing (pure spec).

**Tests:** N/A (doc).

**Effort:** S.

#### A2. Extend Edgar_updater to emit YAML frontmatter

**Goal:** Edgar_updater's output becomes spec-compliant.

**Files touched:**
- `Edgar_updater/edgar_parser/section_parser.py` — `_write_sections_markdown()` (around line 780) emits `---\n{yaml}\n---\n{body}` instead of blockquote metadata + H1.
- `Edgar_updater/edgar_parser/tools.py` — extend the caller that computes `source_url` / `source_url_deep` / `source_accession` / `cik` / `filing_date` / `period_end` and passes them to the writer.
- Possibly new module `Edgar_updater/edgar_parser/frontmatter.py` — small helper: `build_frontmatter(doc_metadata: dict) -> str` that validates + serializes YAML per A1 spec.

**Fields populated at write time:**
- `document_id` — derived from SEC accession: `f"edgar:{accession}"`
- `ticker`, `cik`, `company_name` — from the filing metadata tools already use
- `source=edgar`, `form_type`, `fiscal_period`, `filing_date`, `period_end` — already tracked
- `source_url` (company filing index), `source_url_deep` (primary HTML) — build via EDGAR URL templates in `frontmatter.py` helper
- `source_accession` — the accession number
- `extraction_pipeline` — e.g., `edgar_updater@0.5.0`
- `extraction_model` — the concrete model the `CompletionProvider` used (e.g., `claude-haiku-4-5-20251001`). Recorded per-file so re-extractions with a different model produce a new hash and are auditable.
- `extraction_at` — ISO-8601 timestamp
- `content_hash` — computed after frontmatter + body are assembled, then spliced back in (A3 handles this)
- `sector`, `industry`, `sector_source=GICS`, `exchange` — optional, populated if available via FMP profile lookup; otherwise NULL
- `supersedes`, `supersedes_source`, `supersedes_confidence` — NULL at Phase 0 (linker is Phase 1). Canary amendment gets manually-authored values per task E1.

**Depends on:** A1.

**Tests:**
- `tests/test_edgar_frontmatter.py` — unit tests for `build_frontmatter()` covering required/optional fields, invalid input rejection, URL template correctness.
- `tests/test_edgar_frontmatter.py::test_roundtrip` — write a sample doc, re-parse its frontmatter, assert fields match.

**Effort:** M.

#### A3. Full-file content_hash

**Goal:** Per R7 + D6 — `content_hash` is a SHA-1 of the full canonical markdown (frontmatter + body), first 8 hex chars. Currently `_canonical_hash8()` hashes the extraction inputs, which doesn't support metadata-only changes (e.g., confidence promotion) producing a new file.

**Approach:** Two-pass write: (1) assemble frontmatter with `content_hash` placeholder → (2) compute hash over assembled text → (3) substitute placeholder → (4) rename file to include the hash.

**Files touched:**
- `Edgar_updater/edgar_parser/frontmatter.py` — add `finalize_with_hash(text_with_placeholder: str) -> tuple[str, str]` returning `(finalized_text, content_hash)`.
- `section_parser.py` — use the two-pass flow.

**Depends on:** A2.

**Tests:**
- `tests/test_edgar_frontmatter.py::test_content_hash_deterministic` — identical content → identical hash; whitespace-only change → different hash.
- `tests/test_edgar_frontmatter.py::test_content_hash_full_file` — frontmatter-only change produces a new hash (supports Q15 confidence-promotion flow when the linker lands in Phase 1).

**Effort:** S.

#### A4. Directory layout + ticker canonicalization

**Goal:** Output path is `CORPUS_ROOT/{source}/{canonical_ticker}/{form_type}_{fiscal_period}_{hash}.md`.

**Files touched:**
- `Edgar_updater/edgar_parser/section_parser.py` — output path computation.
- New caller-side shim that calls `SymbolResolver.resolve_identity()` before writing the frontmatter `ticker` field + before computing the output path. See `providers/symbol_resolution.py:203`.

**Depends on:** A2.

**Tests:**
- `tests/test_corpus_paths.py::test_canonical_output_path` — various (ticker, form, period) inputs → exact expected paths.
- `tests/test_corpus_paths.py::test_share_class_canonicalization` — GOOG/GOOGL, BRK.A/BRK.B handled via SymbolResolver.
- `tests/test_corpus_paths.py::test_international_ticker` — AT./AT.L round-trip.

**Effort:** M.

#### A6. Retrofit transcript writer for canonical headers + YAML frontmatter

**Goal:** The existing transcript canonicalizer at `fmp/tools/transcripts.py:682` (`_write_transcript_markdown`) emits partially-canonical output — correct `## PREPARED REMARKS` / `## Q&A SESSION` / `### SPEAKER:` headers, but also non-canonical `### EXCHANGE {idx}: ...` sub-headers in Q&A (lines ~738). The arch doc's §4.4 locks the transcript section taxonomy to just `## PREPARED REMARKS`, `## Q&A SESSION`, and `### SPEAKER: {Name} ({Role})`. `### EXCHANGE` is not canonical and breaks section-grain FTS5 indexing.

**Changes:**
- Drop `### EXCHANGE {idx}:` headers entirely. Each speaker turn in Q&A becomes a standalone `### SPEAKER: {name} ({role})` heading, matching the prepared-remarks structure. Question/Answer pairing is implicit in order (analyst first, management next), not explicit in header naming.
- Inject YAML frontmatter at the top of the file, matching the A2 frontmatter schema (`document_id`, `ticker`, `cik`, `company_name`, `source=fmp_transcripts`, `form_type=TRANSCRIPT`, `fiscal_period`, `filing_date`, `period_end`, `source_url`, `source_url_deep`, `extraction_pipeline`, `extraction_model`, `extraction_at`, `content_hash` — no `supersedes` fields on transcripts in Phase 0).
- `document_id` format: `fmp_transcripts:{ticker}_{fiscal_period}` (e.g., `fmp_transcripts:MSFT_2025-Q1`).
- Full-file `content_hash` via the A3 two-pass flow (shared helper extracted to `fmp/tools/_frontmatter.py` — or vendored from Edgar_updater if a common helper lands).

**Files touched:**
- `fmp/tools/transcripts.py` — rewrite `_write_transcript_markdown` (line 682+) to emit frontmatter + drop `### EXCHANGE` headers.
- New `fmp/tools/_frontmatter.py` (or shared location) — mirror of Edgar_updater's frontmatter helper. Consider extracting both writers' frontmatter logic to a single shared module (probably `core/corpus/frontmatter.py` since that's risk_module-owned) — but be careful of import direction (Edgar_updater can't import from risk_module per A0 rationale).

**Actually — recommended structure:** Put frontmatter spec compliance in `core/corpus/frontmatter.py` (risk_module side), and make both Edgar_updater and fmp/tools call it **via a filesystem boundary** — they write a raw body (no frontmatter); an ingestion orchestrator (new in risk_module, see A8 below) adds the frontmatter wrapping during the write-to-`CORPUS_ROOT` step. This consolidates file-write ownership (resolving Codex MAJOR #6: one authoritative write path).

**Depends on:** A1 (convention), A8 (see below — orchestrator ownership).

**Tests:**
- `fmp/tests/test_transcript_writer.py::test_no_exchange_headers` — Q&A block produces only `### SPEAKER:` headings.
- `fmp/tests/test_transcript_writer.py::test_speaker_order_preserved` — analyst-then-management turn order preserved through the new layout.
- `fmp/tests/test_transcript_writer.py::test_frontmatter_schema_valid` — emitted file parses as YAML-frontmatter + markdown body; frontmatter fields match spec.

**Effort:** M.

#### A7. Amendment link field threading (transcript case: no-op)

**Goal:** Confirm transcripts don't carry `supersedes` fields in Phase 0 (transcripts don't amend each other in the Phase 0 canary; if a company re-issues a transcript with corrections it's rare enough to defer to Phase 1+). Frontmatter omits `supersedes` / `supersedes_source` / `supersedes_confidence` for `source=fmp_transcripts`. Documented here so reviewers don't assume parity with filings.

**Effort:** S (documentation task — no code).

#### A8. Ingestion orchestrator (single authoritative write path) — resolves Codex MAJOR #6

**Goal:** One module in risk_module that owns the canonical write-to-`CORPUS_ROOT` flow. Both Edgar_updater (filings) and fmp/tools (transcripts) produce **raw canonicalized bodies** (section-structured markdown without frontmatter); the orchestrator in risk_module wraps them with frontmatter, computes content_hash, writes to staging, atomic-renames into `CORPUS_ROOT/{source}/{ticker}/{form}_{period}_{hash}.md`.

**Files touched:**
- New `core/corpus/ingest.py::ingest_raw(body: str, metadata: dict, corpus_root: Path, db: sqlite3.Connection) -> IngestResult`:
  1. Validate `metadata` against the spec (A1): required fields present, types valid.
  2. Call `core/corpus/frontmatter.py::build_frontmatter(metadata, content_hash='0' * 8)` → assembled markdown with placeholder.
  3. Write assembled text to `staging/{uuid}.md`.
  4. Compute full-file SHA-1, first 8 hex chars.
  5. Rewrite frontmatter with real hash, rewrite staging file.
  6. Compute canonical path. Atomic `os.rename(staging_path, canonical_path)`.
  7. Parse sections via A5 offsets.
  8. Open SQLite transaction: UPSERT `documents` row keyed on `document_id`; DELETE + INSERT `sections_fts` rows for this document_id; if `supersedes` is set with `supersedes_confidence='high'`, run the D14 scoped is_superseded_by update for the superseded original.
  9. Return `IngestResult(status='complete'|'failed', document_id, content_hash, canonical_path, warnings=[])`.

**Edgar_updater integration:**
- `Edgar_updater/edgar_parser/section_parser.py::_write_sections_markdown` is modified to return the body text + metadata dict **instead of writing to disk**. The caller (risk_module's ingestion driver, see G2) passes both to `ingest_raw()`.

**fmp transcripts integration:**
- `fmp/tools/transcripts.py::_write_transcript_markdown` similarly returns `(body, metadata)` instead of writing. Caller passes to `ingest_raw()`.

**This collapses Codex MAJOR #6**: `Block A` is no longer about writing files; it's about producing canonicalized bodies + metadata. `ingest_raw()` is the sole writer. Atomic-rename + UPSERT + reconciler hook all live in one place.

**Depends on:** A1, A2, A3 (body/frontmatter helpers), A5 (offsets), B1 (schema), B3 (types).

**Tests:**
- `tests/test_corpus_ingest.py::test_ingest_raw_filing` — canned body + metadata → disk file + DB row + sections_fts rows.
- `tests/test_corpus_ingest.py::test_ingest_raw_transcript` — same for transcript body.
- `tests/test_corpus_ingest.py::test_validation_rejects_missing_required` — metadata missing `document_id` → `InvalidInputError` before any file write.
- `tests/test_corpus_ingest.py::test_atomic_rename_crash_before_commit` — simulate crash between rename and SQLite commit (kill the process in test); verify reconciler heals.

**Effort:** M.

#### A5. Char-offset backfill via langextract_mcp

**Goal:** For each canonicalized markdown file, compute the `char_start` + `char_end` for every canonical section. Needed for D12 section-grain FTS5 rows.

**Files touched:**
- New module `core/corpus/offsets.py` (probably — subject to Q1 in §10 of this plan) — imports `parse_filing_sections()` from `AI-excel-addin/mcp_servers/langextract_mcp/text_utils.py`. Returns `list[(section_header, content_text, char_start, char_end)]` for a given markdown file path.
- Alternatively: copy/vendor the function into risk_module under `core/corpus/section_map.py` if the AI-excel-addin import isn't clean. Arch doc's §15 confirms `parse_filing_sections` exists and is already the right shape.

**Depends on:** A4 (files must exist in canonical layout before we parse).

**Tests:**
- `tests/test_section_map.py::test_filings_sections_offsets` — parse a real canary 10-K markdown, assert each `## SECTION: Item N.` header is detected with non-overlapping offsets covering the full body.
- `tests/test_section_map.py::test_transcripts_offsets` — same for a canary transcript with `## PREPARED REMARKS` / `## Q&A SESSION` / `### SPEAKER:` structure.
- `tests/test_section_map.py::test_empty_sections_omitted` — files with missing sections (e.g., no Item 1B) produce no rows for that section.

**Effort:** S (mostly integration + tests, the parser exists).

### Block B — Schema + ingestion + reconciler (DB-side)

#### B1. `documents` + `sections_fts` schema

**Goal:** SQLite schema matching D3 + D12 + D13.

**Files touched:**
- New `core/corpus/schema.sql` — DDL:

```sql
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    cik TEXT,
    company_name TEXT,
    source TEXT NOT NULL,                   -- edgar | fmp_transcripts | quartr
    form_type TEXT NOT NULL,
    fiscal_period TEXT,
    filing_date DATE,
    period_end DATE,
    source_url TEXT NOT NULL,
    source_url_deep TEXT,
    source_accession TEXT,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    extraction_pipeline TEXT,
    extraction_model TEXT,
    extraction_at TIMESTAMP,
    extraction_status TEXT DEFAULT 'complete',    -- see status-rules below
    sector TEXT,
    industry TEXT,
    sector_source TEXT,
    exchange TEXT,
    supersedes TEXT REFERENCES documents(document_id),
    supersedes_source TEXT,                 -- sec_header | heuristic | llm_extraction | manual
    supersedes_confidence TEXT,             -- high | medium | low
    is_superseded_by TEXT REFERENCES documents(document_id),  -- DB-ONLY DERIVED (D14)
    last_indexed TIMESTAMP,
    CHECK (supersedes_confidence IS NULL OR supersedes_confidence IN ('high', 'medium', 'low'))
);

CREATE INDEX IF NOT EXISTS idx_documents_ticker ON documents(ticker);
CREATE INDEX IF NOT EXISTS idx_documents_form_type ON documents(form_type);
CREATE INDEX IF NOT EXISTS idx_documents_is_superseded ON documents(is_superseded_by);
CREATE INDEX IF NOT EXISTS idx_documents_supersedes ON documents(supersedes);
CREATE INDEX IF NOT EXISTS idx_documents_sector ON documents(sector);

-- extraction_status value rules (Phase 0):
--   'complete'  — full extraction succeeded (all expected sections present).
--                 DEFAULT for all successful ingestions in Phase 0.
--   'partial'   — NOT USED in Phase 0. Reserved for Phase 1 when per-section
--                 fallback is implemented (some sections extract, others fail).
--   'failed'    — NOT USED in Phase 0 (ingestion either succeeds and writes
--                 'complete', or raises an exception and writes no row at all —
--                 canary scale is small enough that silent failures are worse
--                 than explicit manual intervention). Reserved for Phase 1.
--   'orphaned'  — NOT USED in Phase 0. Reserved for Phase 1 GC when a file
--                 on disk is no longer the canonical pointer.
-- Phase 0 query surface filters WHERE extraction_status = 'complete' (implicit
-- via default). query_warnings on SearchResponse is populated only for
-- non-'complete' rows, which is the empty set in Phase 0.

CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    document_id UNINDEXED,
    section UNINDEXED,
    content,
    char_start UNINDEXED,
    char_end UNINDEXED,
    speaker_name UNINDEXED,                 -- transcripts only; NULL for filings
    speaker_role UNINDEXED,                 -- transcripts only
    tokenize = 'porter unicode61'
);
-- Note: SQLite does not support CREATE INDEX on FTS5 virtual tables. Lookups by
-- document_id go through WHERE clauses on the UNINDEXED columns; SQLite's FTS5
-- handles this efficiently via bitmap scans of the index's row metadata. If
-- document_id-only lookups become hot, mirror (document_id -> rowid) in a
-- companion regular table and join — Phase 1 optimization only.
```

- New `core/corpus/db.py` — `open_corpus_db(path: Path) -> sqlite3.Connection` that runs schema.sql idempotently on open.

**Depends on:** nothing schema-wise; the design is fully specified in the arch doc.

**Tests:**
- `tests/test_corpus_schema.py::test_schema_idempotent` — opening an existing DB twice doesn't double-insert rows.
- `tests/test_corpus_schema.py::test_fts5_available` — smoke test that SQLite build has FTS5 (fail fast if not).
- `tests/test_corpus_schema.py::test_confidence_check_constraint` — inserting a doc with `supersedes_confidence='invalid'` is rejected.

**Effort:** S.

#### B2. Confidence-gated `is_superseded_by` SQL helper

**Goal:** Isolate the D14 deterministic multi-amendment rule as a reusable helper. Consumed by A8 (ingestion orchestrator, at ingest-time) and B4 tasks (reconciler, at global-recompute time).

File-first atomic-rename + UPSERT ownership lives in A8 (not here). This task is SQL-only.

**Files touched:**
- New `core/corpus/supersession.py::update_is_superseded_by(db, document_id: str | None = None)`:

```python
def update_is_superseded_by(
    db: sqlite3.Connection,
    document_id: str | None = None,
) -> int:
    """
    Confidence-gated D14 rule: only `supersedes_confidence = 'high'` drives
    the derived column. Tiebreak: filing_date DESC, document_id DESC.

    If document_id is provided, scope the update to that original only
    (ingest-time: called when a new amendment lands).
    If None, recompute globally (reconciler: full sweep).

    Returns rows updated.
    """
    if document_id is None:
        # Global recompute — set all originals' is_superseded_by from scratch
        db.execute("UPDATE documents SET is_superseded_by = NULL")
        db.execute("""
            UPDATE documents SET is_superseded_by = (
                SELECT d2.document_id FROM documents d2
                WHERE d2.supersedes = documents.document_id
                  AND d2.supersedes_confidence = 'high'
                ORDER BY d2.filing_date DESC, d2.document_id DESC
                LIMIT 1
            )
        """)
    else:
        # Scoped update — single original
        db.execute("""
            UPDATE documents SET is_superseded_by = (
                SELECT d2.document_id FROM documents d2
                WHERE d2.supersedes = documents.document_id
                  AND d2.supersedes_confidence = 'high'
                ORDER BY d2.filing_date DESC, d2.document_id DESC
                LIMIT 1
            )
            WHERE document_id = ?
        """, (document_id,))
    return db.total_changes
```

**Depends on:** B1.

**Tests:**
- `tests/test_corpus_supersession.py::test_single_amendment_high_confidence_sets_pointer`
- `tests/test_corpus_supersession.py::test_low_confidence_amendment_ignored`
- `tests/test_corpus_supersession.py::test_two_amendments_tiebreak_by_filing_date` — both high-confidence, later filing_date wins.
- `tests/test_corpus_supersession.py::test_two_amendments_same_date_tiebreak_by_document_id` — lex-greater wins.
- `tests/test_corpus_supersession.py::test_global_vs_scoped_agree` — scoped update for one original + global recompute produce identical final state.
- `tests/test_corpus_supersession.py::test_malformed_confidence_ignored` — `supersedes_confidence='maybe'` (not in CHECK allow-list — CHECK constraint blocks insertion; test asserts the CHECK rejects).

**Effort:** S.

#### B3. `SearchResponse` + `SearchHit` + `AmbiguousDocumentError` types

**Goal:** The typed return contracts from §5.1.

**Files touched:**
- New `core/corpus/types.py` — dataclasses exactly matching §5.1 + §5.4:

```python
@dataclass(frozen=True)
class SearchHit:
    document_id: str
    ticker: str
    company_name: str
    source: str
    form_type: str
    fiscal_period: str
    filing_date: str
    is_superseded: bool
    has_low_confidence_supersession: bool
    section: str
    snippet: str
    file_path: str
    char_start: int
    char_end: int
    source_url: str
    source_url_deep: Optional[str]
    source_accession: Optional[str]
    rank: float  # BM25; smaller is better


@dataclass(frozen=True)
class SearchResponse:
    hits: List[SearchHit]
    applied_filters: Dict[str, Any]
    total_matches: int
    has_superseded_matches: bool
    has_low_confidence_supersession: bool
    query_warnings: List[str]


@dataclass(frozen=True)
class DocumentMetadata:
    """Return type for *_list tools. Document-grain, no sections/snippets."""
    document_id: str
    ticker: str
    form_type: str
    fiscal_period: str
    filing_date: str
    is_superseded: bool
    file_path: str
    source_url: str


class AmbiguousDocumentError(Exception):
    """Raised by tuple-overload *_source_excerpt when multiple non-superseded
    documents match (ticker, form_type, fiscal_period). Carries candidate
    document_ids so the caller can retry with explicit document_id."""
    def __init__(self, candidates: List[str], *, ticker: str, form_type: str, fiscal_period: str):
        self.candidates = candidates
        self.ticker = ticker
        self.form_type = form_type
        self.fiscal_period = fiscal_period
        super().__init__(
            f"Ambiguous document: {len(candidates)} matches for "
            f"({ticker}, {form_type}, {fiscal_period}): {candidates}"
        )


class InvalidInputError(Exception):
    """Raised by I13 tool-boundary validation on limit/length/path violations."""
```

**Depends on:** nothing.

**Tests:**
- `tests/test_corpus_types.py::test_searchhit_is_frozen` — attempting to mutate raises.
- `tests/test_corpus_types.py::test_ambiguous_error_carries_candidates` — error rendering includes all document_ids.

**Effort:** S.

#### B4a. Reconciler — disk walker + frontmatter parser

**Goal:** Walk `CORPUS_ROOT`, group files by `document_id`, pick authoritative file per I12 tiebreak rule. Pure inspection, no writes.

**Files touched:**
- New `core/corpus/reconciler/walker.py::scan_corpus(corpus_root: Path) -> dict[str, AuthoritativeFile]`:

```python
@dataclass(frozen=True)
class AuthoritativeFile:
    document_id: str
    file_path: Path
    content_hash: str
    frontmatter: dict        # fully parsed + validated per A1 spec
    other_files: list[Path]  # non-authoritative files for same document_id (for divergence logging)

def scan_corpus(corpus_root: Path) -> dict[str, AuthoritativeFile]:
    """
    Walk all .md files under corpus_root. Parse each file's YAML frontmatter.
    Group by document_id. For each group:
      - Pick authoritative file via (extraction_at DESC, extraction_pipeline semver DESC, content_hash lex DESC)
      - Malformed values (unparseable ISO-8601 extraction_at, non-semver extraction_pipeline) fall through to the next tiebreak level.
    Return {document_id: AuthoritativeFile}.
    """
```

**Depends on:** A1 (frontmatter schema for validation).

**Tests:**
- `tests/test_reconciler_walker.py::test_single_file_per_doc_id` — basic scan.
- `tests/test_reconciler_walker.py::test_tiebreak_extraction_at_desc` — two files, later extraction_at wins.
- `tests/test_reconciler_walker.py::test_tiebreak_pipeline_semver` — tied extraction_at, pipeline semver tiebreaks.
- `tests/test_reconciler_walker.py::test_tiebreak_content_hash_lex` — both above tied.
- `tests/test_reconciler_walker.py::test_malformed_extraction_at_fallthrough`
- `tests/test_reconciler_walker.py::test_malformed_pipeline_fallthrough`
- `tests/test_reconciler_walker.py::test_malformed_yaml_skipped_with_warning`

**Effort:** M.

#### B4b. Reconciler — DB sync (documents table)

**Goal:** Apply scan results to the `documents` table. Upsert rows, update file_path/content_hash/authoritative metadata to point at the right file. No sections_fts changes here.

**Files touched:**
- New `core/corpus/reconciler/db_sync.py::sync_documents(db, scan_result, logger) -> DBSyncReport`:
  - For each `document_id` in scan_result: UPSERT row with authoritative file's data.
  - For rows in `documents` table whose file_path points at a path NOT in scan_result (deleted/renamed file): mark as orphaned, log, and either keep-in-place (conservative) or mark `extraction_status='orphaned'` (clearer) — Phase 0 keeps in place and logs; Phase 1+ may add GC.

**Depends on:** B4a, B1.

**Tests:**
- `tests/test_reconciler_db_sync.py::test_inserts_missing_row`
- `tests/test_reconciler_db_sync.py::test_updates_row_to_new_authoritative_file`
- `tests/test_reconciler_db_sync.py::test_leaves_orphan_in_place_and_logs`
- `tests/test_reconciler_db_sync.py::test_idempotent_second_run`

**Effort:** S.

#### B4c. Reconciler — sections_fts sync

**Goal:** Rebuild the `sections_fts` rows for each document_id. Delete existing rows, re-parse via A5 offsets, insert.

**Files touched:**
- `core/corpus/reconciler/db_sync.py::sync_sections_fts(db, scan_result) -> SectionsFtsReport`:
  - For each document_id: DELETE FROM sections_fts WHERE document_id = ?; INSERT new rows from the authoritative file's parsed sections.
  - This is a DELETE-then-INSERT per document_id, not per-section diff. Simpler and idempotent.

**Depends on:** B4a, A5 (offsets), B1.

**Tests:**
- `tests/test_reconciler_sections_fts.py::test_inserts_missing_sections`
- `tests/test_reconciler_sections_fts.py::test_replaces_stale_sections`
- `tests/test_reconciler_sections_fts.py::test_idempotent_second_run`

**Effort:** S.

#### B4d. Reconciler — global `is_superseded_by` recomputation

**Goal:** Full recompute of the derived column per B2's confidence-gated SQL.

**Files touched:**
- `core/corpus/reconciler/db_sync.py::recompute_supersession(db) -> int` — thin wrapper over `core.corpus.supersession.update_is_superseded_by(db, document_id=None)` (the global form).

**Depends on:** B2, B4a/b/c (so pointer recompute happens after document rows are fresh).

**Tests:**
- `tests/test_reconciler_supersession.py::test_rebuilds_from_disk` — zero out `is_superseded_by`, run recompute, verify reconstructed from `supersedes` pointers.
- `tests/test_reconciler_supersession.py::test_low_confidence_stays_null` — low-confidence amendment doesn't drive the column.
- `tests/test_reconciler_supersession.py::test_convergence_with_b2` — B2 scoped update + B4d global recompute produce identical state.

**Effort:** S.

#### B4e. Reconciler — orchestrator + report

**Goal:** Glue B4a-d together behind a single `reconcile()` entrypoint with a consolidated `ReconcilerReport`.

**Files touched:**
- `core/corpus/reconciler/__init__.py::reconcile(corpus_root: Path, db: sqlite3.Connection, logger: Logger) -> ReconcilerReport`:

```python
def reconcile(corpus_root, db, logger) -> ReconcilerReport:
    with db:  # transaction
        scan = scan_corpus(corpus_root)
        doc_report = sync_documents(db, scan, logger)
        sec_report = sync_sections_fts(db, scan)
        sup_updates = recompute_supersession(db)
        divergences = [af for af in scan.values() if af.other_files]
        for af in divergences:
            logger.warning(f"content_divergence: document_id={af.document_id} ...")
    return ReconcilerReport(doc_report, sec_report, sup_updates, divergences)
```

**Depends on:** B4a, B4b, B4c, B4d.

**Tests:**
- `tests/test_reconciler.py::test_full_end_to_end_heal` — simulate all drift cases at once, verify `reconcile()` heals everything in one pass.
- `tests/test_reconciler.py::test_convergence` — run twice, second is no-op.
- `tests/test_reconciler.py::test_transactional` — simulate a DB error mid-reconcile, verify partial-state rollback.
- `tests/test_reconciler.py::test_full_rebuild_equivalence` — ingest docs via A8; delete DB entirely; run reconcile(); assert query results byte-identical (I3 logical equivalence).

**Effort:** M.

**Net effort of B4a-e: ~M+S+S+S+M ≈ 1 M + 3 S + 1 M = roughly same total as L-sized B4, but each piece is independently testable/reviewable.**

### Block C — Tool surface

#### C1. Core search implementation (shared by both families)

**Goal:** Single internal search function that both `filings_search` and `transcripts_search` wrap.

**Files touched:**
- New `core/corpus/search.py`:

```python
def _search(
    db: sqlite3.Connection,
    query: str,
    form_types: list[str],           # preset per family
    sources: list[str],              # preset per family
    universe: Optional[list[str]] = None,
    sector: Optional[str] = None,
    section: Optional[str] = None,   # for transcripts section filter
    speaker_role: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_superseded: bool = False,
    include_low_confidence_supersession: bool = False,
    limit: int = 20,
) -> SearchResponse:
    """
    Constructs a single SQL query joining documents + sections_fts, applying
    all filters BEFORE the MATCH (I8), computes has_superseded_matches and
    has_low_confidence_supersession by running variant queries with filters
    removed, returns a fully-populated SearchResponse.
    """
```

Key query shape:

```sql
SELECT d.document_id, d.ticker, d.company_name, d.source, d.form_type,
       d.fiscal_period, d.filing_date, d.source_url, d.source_url_deep, d.source_accession,
       d.is_superseded_by IS NOT NULL AS is_superseded,
       EXISTS (SELECT 1 FROM documents d3
               WHERE d3.supersedes = d.document_id
                 AND d3.supersedes_confidence IN ('low', 'medium')) AS has_low_confidence_supersession,
       s.section, snippet(sections_fts, 2, '<b>', '</b>', '...', 20) AS snippet,
       d.file_path, s.char_start, s.char_end,
       bm25(sections_fts) AS rank
FROM sections_fts s
JOIN documents d USING (document_id)
WHERE d.form_type IN (?) AND d.source IN (?)
  AND (? IS NULL OR d.ticker IN (?))
  AND (? IS NULL OR d.sector = ?)
  AND (? IS NULL OR d.filing_date >= ?)
  AND (? IS NULL OR d.filing_date <= ?)
  AND (:include_superseded OR d.is_superseded_by IS NULL)
  -- When include_low_confidence_supersession=TRUE, treat low/medium-confidence
  -- superseders as current-hiding (hide the original if any such superseder exists).
  -- Default (FALSE) keeps the original visible regardless of low-confidence links.
  AND (
      NOT :include_low_confidence_supersession
      OR NOT EXISTS (
          SELECT 1 FROM documents d3
          WHERE d3.supersedes = d.document_id
            AND d3.supersedes_confidence IN ('low', 'medium')
      )
  )
  AND s.content MATCH ?
ORDER BY rank  -- ASCENDING (smaller BM25 = better, per R2 fix)
LIMIT ?
```

**Depends on:** B1, B3.

**Tests:**
- `tests/test_corpus_search.py::test_basic_query` — single ticker, single form, verify rank ordering ascending.
- `tests/test_corpus_search.py::test_universe_filter` — scoped to ticker list.
- `tests/test_corpus_search.py::test_date_range` — filing_date bounds respected.
- `tests/test_corpus_search.py::test_include_superseded` — amendment hidden by default, surfaced with flag.
- `tests/test_corpus_search.py::test_include_low_confidence_supersession` — low-confidence link doesn't hide by default, does when flag set.
- `tests/test_corpus_search.py::test_has_superseded_matches_hint` — query that would match only superseded docs returns empty hits but True hint.
- `tests/test_corpus_search.py::test_bm25_ascending_sort` — explicit check that smaller rank values come first (guards against R2 regression).

**Effort:** M.

#### C2. `filings_*` family (4 tools)

**Goal:** Per-family thin wrappers over `_search` / direct DB reads / source fetchers.

**Files touched:**
- New `core/corpus/filings.py`:
  - `filings_search(query, ..., include_low_confidence_supersession=False, limit=20) -> SearchResponse` — calls `_search` with `form_types=['10-K', '10-Q', '8-K', 'DEF 14A']`, `sources=['edgar']`.
  - `filings_read(file_path, section=None, char_start=None, char_end=None) -> str` — opens the markdown file, slices by section or byte range.
  - `filings_source_excerpt(document_id=None, section=None, ticker=None, form_type=None, fiscal_period=None) -> str` — primary dispatch on `document_id`. Implementation:
    1. Look up the `documents` row by `document_id`.
    2. Read `source_url_deep` (primary document HTML URL, stable per accession).
    3. Fetch the HTML directly (`httpx.get(source_url_deep, headers={'User-Agent': 'hank-corpus/0.1'})`).
    4. Parse for the named `section` using Edgar_updater's existing section-boundary logic (callable from `Edgar_updater.edgar_parser.section_parser.extract_section_by_header`), return verbatim.
    5. **Do NOT translate back to `(ticker, year, quarter)` and call `edgar-mcp.get_filing_sections`** — that was the original sketch but it violates D13 (tuple is ambiguous for amendments/same-day multi-8-Ks). The accession-keyed HTML URL is unambiguous.
    - Convenience overload: `(ticker, form_type, fiscal_period)` resolves via SQL (`SELECT document_id FROM documents WHERE ... AND is_superseded_by IS NULL`). If >1 row matches → raise `AmbiguousDocumentError` with candidate document_ids; caller retries with explicit document_id.
  - `filings_list(ticker=None, form_type=None, fiscal_period=None) -> list[DocumentMetadata]` — SQL query against `documents` table.

**Depends on:** C1, B3, A4 (canonical ticker integration for inputs).

**Tests:**
- `tests/test_filings_tools.py::test_filings_search_smoke` — basic query returns ranked SearchResponse.
- `tests/test_filings_tools.py::test_filings_read_section` — returns only the named section.
- `tests/test_filings_tools.py::test_filings_read_byte_range` — returns exact byte slice.
- `tests/test_filings_tools.py::test_filings_source_excerpt_document_id` — primary path.
- `tests/test_filings_tools.py::test_filings_source_excerpt_tuple_ambiguity` — multiple non-superseded docs → AmbiguousDocumentError with candidates.
- `tests/test_filings_tools.py::test_filings_list` — metadata-only return.

**Effort:** M.

#### C3. `transcripts_*` family (4 tools)

**Goal:** Mirror of filings family, for transcripts.

**Files touched:**
- New `core/corpus/transcripts.py`:
  - `transcripts_search(query, ..., speaker_role=None, section='both', include_low_confidence_supersession=False, limit=20) -> SearchResponse` — calls `_search` with `form_types=['TRANSCRIPT']`, `sources=['fmp_transcripts']`.
  - `transcripts_read(file_path, section=None, speaker=None, ...) -> str`
  - `transcripts_source_excerpt(document_id=None, speaker=None, ticker=None, fiscal_period=None) -> str` — primary dispatch on `document_id`:
    1. Parse the `fmp_transcripts:{ticker}_{fiscal_period}` format to extract `(ticker, year, quarter)` — this is a **reversible canonical encoding**, not a lossy lookup. The document_id IS the tuple for FMP transcripts (one transcript per ticker/quarter is the FMP data model — confirmed by research: `get_earnings_transcript(symbol, year, quarter)`).
    2. Call `fmp-mcp.get_earnings_transcript(symbol=ticker, year=year, quarter=quarter, filter_speaker=speaker, format='full', output='file')`.
    3. Return verbatim text.
    - Convenience overload `(ticker, fiscal_period)` constructs the document_id and dispatches. No ambiguity for transcripts (FMP's data model is one-per-quarter), so tuple overload doesn't need `AmbiguousDocumentError` path in practice — but the surface keeps the error type for consistency with filings.
  - `transcripts_list(ticker=None, fiscal_period=None) -> list[DocumentMetadata]`.

**Depends on:** C1, B3.

**Tests:** Structurally identical to C2's test set, per-tool.

**Effort:** M.

#### C4. Tool-boundary input validation (I13)

**Goal:** Every tool validates inputs before touching DB/filesystem.

**Files touched:**
- New `core/corpus/validation.py`:

```python
MAX_QUERY_LEN = 1024
MAX_UNIVERSE_SIZE = 5000
MAX_LIMIT = 500

def validate_search_inputs(query: str, universe: Optional[list[str]], limit: int) -> None:
    if len(query) > MAX_QUERY_LEN: raise InvalidInputError(...)
    if universe and len(universe) > MAX_UNIVERSE_SIZE: raise InvalidInputError(...)
    if limit > MAX_LIMIT: raise InvalidInputError(...)
    # ...

def validate_read_path(file_path: str, corpus_root: Path) -> Path:
    """Resolve + canonicalize; ensure result is under corpus_root. No traversal."""
    p = Path(file_path).resolve()
    if not p.is_relative_to(corpus_root.resolve()):
        raise InvalidInputError(f"Path {p} outside corpus root")
    return p
```

**Depends on:** B3 (for InvalidInputError).

**Tests:**
- `tests/test_corpus_validation.py::test_query_length_cap` — 2KB query rejected.
- `tests/test_corpus_validation.py::test_universe_size_cap` — 10K-ticker universe rejected.
- `tests/test_corpus_validation.py::test_limit_cap` — limit=10000 rejected.
- `tests/test_corpus_validation.py::test_path_traversal_blocked` — `../../../etc/passwd` rejected.
- `tests/test_corpus_validation.py::test_symlink_escape` — symlink pointing outside corpus rejected (via `.resolve()`).

**Effort:** S.

#### C5. MCP tool registration

**Goal:** Wire the 8 Python functions into the risk_module MCP server so agents can call them.

**Files touched:**
- `mcp_server.py` or wherever `@mcp.tool()` decorators live — register all 8 tools with JSON-schema compatible parameter/return shapes.
- Return-shape handling: MCP marshaling converts `SearchResponse` / `SearchHit` / `DocumentMetadata` / exceptions into JSON-safe dicts.

**Depends on:** C2, C3, C4.

**Tests:**
- `tests/test_mcp_corpus_tools.py::test_tool_registered` — introspect mcp_server, confirm all 8 tool names present.
- `tests/test_mcp_corpus_tools.py::test_tool_dispatch_round_trip` — invoke each tool via MCP protocol, verify JSON-serializable response.

**Effort:** M.

### Block D — Composition with existing MCP surfaces

#### D1. Cross-source merge helper + agent prompt

**Goal:** Document the parallel-call + BM25-ascending-merge pattern from §5.2, and wire it into the agent system prompt.

**Files touched:**
- Update the agent system prompt (location TBD, depends on current prompt architecture) with the routing + cross-source guidance from §6.2 of arch doc.
- Optionally: a helper `core/corpus/merge.py::merge_responses(responses: list[SearchResponse]) -> list[SearchHit]` that does `sorted(all_hits, key=lambda h: h.rank)` — makes the pattern a one-liner for the agent. Not required (agent can do the sort inline), but documented in the prompt.

**Depends on:** C2, C3.

**Tests:**
- `tests/test_corpus_merge.py::test_merge_ascending` — explicit BM25-ascending ordering check.
- `tests/test_corpus_merge.py::test_merge_preserves_all_hits` — no dedup (each hit is a unique document_id + section pair).

**Effort:** S.

### Block E — Supersession handling (manual for Phase 0)

#### E1. Manually-authored canary amendment

**Goal:** Phase 0 validates D14 / I14 / confidence gating via a hand-built amendment pair. Amendment linker is deferred; we hand-author one `supersedes` pointer to exercise downstream semantics.

**Approach:**
- Pick one canary ticker that has a real 10-K/A in the last ~2 years (e.g., research an actual SEC filing to use as the case).
- Ingest the original 10-K normally.
- Ingest the 10-K/A with frontmatter `supersedes: edgar:<original_accession>`, `supersedes_source: manual`, `supersedes_confidence: high`.
- Verify: D14 SQL populates `is_superseded_by` on the original; default `filings_search` hides the original; `include_superseded=True` surfaces it; reconciler rerun arrives at same result.

**Also build one low-confidence case:**
- Hand-author a second "amendment" with `supersedes_confidence: low`.
- Verify: `is_superseded_by` is NOT populated for the original; `has_low_confidence_supersession` flag set on search results; `include_low_confidence_supersession=True` hides the original.

**Files touched:**
- `docs/planning/CORPUS_PHASE0_CANARY.md` — a small companion doc listing the exact tickers, their filings, the manually-authored amendment case, and the low-confidence synthetic case. Canary dataset spec.

**Depends on:** A2 (frontmatter), B2 (ingestion), C1 (search).

**Tests:**
- Covered by canary queries 6 (amendment chain), 7 (multi-filing disambiguation), 9 (low-confidence gating) — see §7 of this plan.

**Effort:** S (manual data prep, not code).

### Block F — D15 migration

#### F1. Inventory dual-location stores

**Goal:** Build manifest of all files in `Edgar_updater/data/filings/` + `AI-excel-addin/data/filings/`. Identify duplicates + divergent hashes.

**Files touched:**
- New script `scripts/corpus_migration_inventory.py` — walks both locations, produces `inventory.json` with per-file: source_location, content_hash, parsed_ticker (best-effort from filename), size, mtime.

**Depends on:** nothing.

**Tests:**
- `tests/test_migration_inventory.py::test_inventory_both_locations` — synthetic fixture with files in both locations, verify dedup logic + divergent-hash flagging.

**Effort:** S.

#### F2. Transform + write migrated files

**Goal:** For each accepted legacy file: parse existing content → synthesize spec-compliant frontmatter (document_id from filename-derived accession + metadata lookup) → write to `CORPUS_ROOT/{source}/{ticker}/{form}_{period}_{hash}.md` via the B2 atomic-rename flow.

**Files touched:**
- New script `scripts/corpus_migration_transform.py`.

**Depends on:** F1, A2 (frontmatter helper), A3 (hash), A4 (path), B2 (ingestion primitive).

**Tests:**
- `tests/test_migration_transform.py::test_transforms_blockquote_to_yaml` — legacy file with `> Date: ...` blockquote becomes YAML frontmatter.
- `tests/test_migration_transform.py::test_divergent_hash_flagged_not_picked` — divergent-hash files surface for manual review.

**Effort:** M.

#### F3. Cutover + archive

**Goal:** Symlink `CORPUS_ROOT` to the new physical path; archive legacy locations; update Edgar_updater's output path config.

**Files touched:**
- `scripts/corpus_migration_cutover.sh` (bash — it's a few file operations). **Must accept `--corpus-root`, `--legacy-edgar`, `--legacy-aiexcel`, `--dry-run`, and `--symlink-target` flags so it can run against temp-directory fixtures in tests without touching real paths.** No hardcoded paths; all come from flags or env vars. The rollback drill test exercises the full flow against a tmp_path fixture.
- Edgar_updater's output path config — whatever env var or constant governs `FILE_OUTPUT_DIR` becomes `$CORPUS_ROOT/edgar/`.
- Legacy locations renamed to `.legacy_YYYYMMDD/` (not deleted).

**Depends on:** F2.

**Tests:**
- `tests/test_migration_cutover.py::test_symlink_points_at_corpus_root` — dry-run mode, verify planned symlink structure.
- `tests/test_migration_cutover.py::test_rollback_restores_legacy` — exercise the D15 step-7 rollback in a `tmp_path` sandbox (pytest fixture). Test invokes the script with `--dry-run=false` against temp paths, seeds legacy dirs with fake files, performs cutover, then rollback; asserts (a) all legacy files restored to their original paths, (b) partial CORPUS_ROOT archived as `.failed_YYYYMMDD/` not deleted, (c) symlinks reverted. No real filesystem paths touched.

**Effort:** S.

### Block G — Canary dataset + acceptance

#### G1. Canary ticker list + filings selection

**Goal:** Lock exactly which tickers + filings make up the canary.

**Canary set (proposed — finalize during task execution):**
- **AAPL** — one recent 10-K + 4 recent 10-Qs + 2 earnings transcripts (last 2 quarters). Clean tech baseline.
- **MSFT** — same breadth. Includes the existing MSFT_10Q_2025 sample from both legacy locations (migration test).
- **GOOG** — share-class edge case (confirms SymbolResolver integration).
- **META** — required by canary query Q1 (§7); tech baseline with AI-related language.
- **BRK.B** — diversified conglomerate, unusual filing structure.
- **JPM** — financials taxonomy (Basel III / credit provisions language).
- **XOM** — XBRL-heavy, segment reporting.
- **TGT** — consumer retail baseline.
- **One microcap** — TBD (see P5), stress-test spartan filings (probably a recent IPO or small-cap with minimal sections).
- **Amendment edge case** — one real 10-K/A + its original (per E1).
- **Multi-8-K day** — one ticker with multiple 8-Ks on same day (common around earnings + material events).
- **DEF 14A** — one proxy statement to exercise proxy section taxonomy.

**Files touched:**
- `docs/planning/CORPUS_PHASE0_CANARY.md` (from E1) — finalized during this task.

**Depends on:** E1.

**Effort:** S (research + authoring).

#### G2. Ingest the canary

**Goal:** Run the ingestion pipeline against the canary set; produce `CORPUS_ROOT` + populated `filings.db`.

**Depends on:** G1, all of Block A + B + F.

**Tests:** success = all tickers ingest without errors; row counts match expectations; frontmatter schema-valid on every file.

**Effort:** M (includes iterating if schema/extraction issues surface).

#### G3. Run the 9 canary queries

**Goal:** Execute each of the 9 canary queries from §13.6 end-to-end. Verify acceptance criteria (see §7 of this plan for per-query spec).

**Depends on:** G2, all of Block C + D.

**Files touched:**
- `tests/canary/test_corpus_canary.py` — pytest tests running each query and asserting acceptance.

**Effort:** M.

#### G4. Ship criterion + convention-lock signal

**Goal:** Final checklist + explicit sign-off. If any canary query fails due to convention issue, iterate the convention + re-run canary (Phase 0 can re-extract 10 tickers in <1 hour; cheap loop).

**Depends on:** G3.

**Effort:** S.

---

## 5. Testing Strategy

### 5.1 Unit tests (per-task)

Already enumerated per-task in §4. Target: every task adds ≥2 tests, one happy-path + one edge-case.

### 5.2 Integration tests

- `tests/integration/test_corpus_end_to_end.py` — ingest one canary ticker fresh, run all 8 tools against it, verify full round-trip including citation chain (SearchHit.file_path → filings_read → matches frontmatter in DB → source_url resolves to a real EDGAR URL format).

### 5.3 Reconciler drift tests (I12/I3)

- `tests/test_corpus_reconciler.py::test_synthetic_drift_*` — simulate various failure modes (orphaned file, orphaned row, content divergence, stale is_superseded_by); verify reconciler heals each deterministically.
- `tests/test_corpus_reconciler.py::test_full_rebuild_equivalence` — build DB via live ingestion; delete DB; run reconciler end-to-end from disk; assert every query produces the same results (I3 logical equivalence).

### 5.4 Canary query tests (§7)

See §7 — these are the highest-value tests.

### 5.5 What's NOT tested in Phase 0

- **Gateway citation validation** (Q15) — deferred to Phase 1.
- **Scale** — 500+ tickers, 20k+ files. Phase 0 tops out at ~15 documents.
- **Concurrency stress** — Phase 0 tests cover 2-worker races; heavier concurrency in Phase 1.
- **Amendment linker** — manual only.
- **Cross-host / multi-node** — single-host Phase 0.

---

## 6. Sequencing & Dependencies

### 6.1 Critical path

```
A1 (spec) ─┐
           ├─→ A2 (frontmatter) ─→ A3 (hash) ─→ A4 (paths) ─→ A5 (offsets) ─┐
           │                                                                  │
B1 (schema) ─→ B3 (types) ─→ B2 (ingest) ─────────────────────────────────┐  │
                                                                            ↓  ↓
                                                                          B4 (reconciler)
                                                                                │
C1 (search) ─→ C2 (filings) + C3 (transcripts) + C4 (validation) ─→ C5 (MCP)  │
                                                                                │
D1 (merge + prompt)                                                             │
                                                                                ↓
F1 (inventory) ─→ F2 (transform) ─→ F3 (cutover)                         G1 (canary dataset)
                                                                                │
E1 (manual amendment) ────────────────────────────────────────────────────────→ G2 (ingest canary)
                                                                                │
                                                                                ↓
                                                                          G3 (run 9 queries)
                                                                                │
                                                                                ↓
                                                                          G4 (ship)
```

### 6.2 Parallelizable tracks

- **Track X (spec + frontmatter):** A1 → A2 → A3 → A4 → A5
- **Track Y (schema + primitives):** B1 → B3 (parallel with X from start)
- **Track Z (tool surface):** C1 + C4 (after B1/B3) → C2 + C3 in parallel → C5
- **Track W (migration prep):** F1 in parallel with Track X; F2 needs X+Y complete; F3 comes late

B4 (reconciler) blocks on A5 + B2; it's a mid-path item.

E1 (canary amendment authoring) is research-bound, not code-bound; can happen anytime before G2.

### 6.3 Estimated total effort (rough)

| Block | Tasks | Effort |
|---|---|---|
| A (canonicalization) | 5 | M + M + S + M + S = ~4-5 days |
| B (schema + ingest) | 4 | S + M + S + L = ~5-7 days |
| C (tool surface) | 5 | M + M + M + S + M = ~5-6 days |
| D (composition) | 1 | S = <1 day |
| E (supersession) | 1 | S = <1 day |
| F (migration) | 3 | S + M + S = ~2-3 days |
| G (canary) | 4 | S + M + M + S = ~2-3 days |
| **Total** | **23 tasks** | **~3-4 weeks of focused work** |

Parallelizable tracks can cut calendar time to ~2 weeks with one engineer, ~1 week with two. Serial single-engineer: 3-4 weeks.

---

## 7. Canary Acceptance — Per-Query Spec

Each of the 9 canary queries from §13.6 of the arch doc maps to a concrete acceptance criterion in Phase 0.

### Q1. "What AI investments are AAPL, MSFT, GOOG, META discussing?"

- `filings_search(query='"AI capital" OR "AI infrastructure" OR "AI investment"', universe=['AAPL','MSFT','GOOG','META'], form_type=['10-K'])`
- **Pass:** returns ≥3 hits across ≥3 different tickers; every hit has populated `file_path`, `source_url`, `section`, `snippet`, `rank`.

### Q2. "How have MSFT risk factors evolved across the last 4 quarters?"

- `filings_search(query='risk', universe=['MSFT'], form_type=['10-K','10-Q'], section='Item 1A. Risk Factors')` — or equivalent with post-filter on section.
- **Pass:** returns hits ordered by `filing_date DESC`; all from `Item 1A` sections; agent can diff content between periods.

### Q3. "AAPL FY2025 10-K on services revenue growth (Item 7) AND related risks (Item 1A)"

- Two queries: `filings_search(query='services revenue', universe=['AAPL'], form_type=['10-K'])` + `filings_search(query='services', universe=['AAPL'], form_type=['10-K'])` with section filter on Item 1A.
- **Pass:** both return hits from the same `document_id`; `filings_read(file_path, section='Item 7')` and `filings_read(file_path, section='Item 1A')` both succeed and return section-scoped content.

### Q4. "Where has BRK.B discussed capital allocation — filings or transcripts?"

- Parallel calls:
  - `filings_search(query='capital allocation', universe=['BRK.B'], limit=20)`
  - `transcripts_search(query='capital allocation', universe=['BRK.B'], limit=20)`
- Merge: `sorted(f.hits + t.hits, key=lambda h: h.rank)[:30]`
- **Pass:** merged list has hits from both sources (if both have matches); every hit's `rank` is ascending; agent sees `source` field distinguishing filings from transcripts.

### Q5. "What do these companies disclose about quantum computing?"

- `filings_search(query='quantum computing', universe=<canary tech subset>, form_type=['10-K'])`
- **Expected:** few/no matches.
- **Pass:** `SearchResponse.hits` is empty or very small; `total_matches` field reflects the sparsity; agent's synthesis honestly reports "no/few matches" without hallucination.

### Q6. Amendment chain

- For the canary amendment pair (original 10-K + 10-K/A manually authored in E1):
  - Default `filings_search(query=..., universe=[ticker])` returns amendment, not original.
  - `include_superseded=True` returns both.
  - `filings_source_excerpt(document_id=<original_accession>)` still resolves and returns original's verbatim text (citation durability).
- **Pass:** all three behaviors verified.

### Q7. Same-day multi-8-K disambiguation

- For a canary ticker with multiple 8-Ks on the same day:
  - `filings_list(ticker=X, form_type=['8-K'], fiscal_period=<date>)` returns multiple `document_id` rows.
  - `filings_source_excerpt(ticker=X, form_type='8-K', fiscal_period=<date>)` (convenience overload) raises `AmbiguousDocumentError` with the candidate list.
  - `filings_source_excerpt(document_id=<specific accession>)` (explicit) resolves cleanly.
- **Pass:** all three behaviors verified.

### Q8. Reconciler heal (actual failure mode)

- Simulation:
  1. Ingest a doc normally.
  2. Kill the process mid-transaction (before SQLite commit) — simulate by manually deleting the `documents` row after ingestion but leaving the file.
  3. Run reconciler.
  4. Verify row + sections_fts rows restored from disk.
  - Then: content-divergence case — two ingestions for same `document_id` with different content produce two files on disk; reconciler picks tiebreak-winner; both files remain addressable; divergence logged.
- **Pass:** both heal cases succeed; queries work after reconciler run.

### Q9. Low-confidence supersession gating (R7 addition)

- Using the synthetic low-confidence case from E1:
  - Default `filings_search` returns the original as non-superseded (low-confidence link does NOT hide it).
  - `SearchResponse.has_low_confidence_supersession=True` and each affected `SearchHit.has_low_confidence_supersession=True`.
  - `include_low_confidence_supersession=True` → original is hidden.
  - Promote confidence by re-extracting the synthetic amendment with `supersedes_confidence: high` (produces new file + hash); after promotion, default search hides the original.
  - Reconciler rerun converges on the same `is_superseded_by` as ingestion-time derivation.
- **Pass:** all five behaviors verified.

---

## 8. Risk Mitigation

R7's top 5 implementation-plan risks, each mapped to a concrete plan element:

| Risk (R7) | Mitigation in this plan |
|---|---|
| content_hash scope = full-file hash | Task A3 explicitly two-pass computes hash over frontmatter+body; test `test_content_hash_full_file` asserts frontmatter-only change produces new hash. |
| Shared search predicate across both families | Task C1 is the single internal `_search` function both families wrap; all supersession params/flags live there once. Divergence is a code review red flag. |
| Low-confidence canary test coverage | Canary query 9 (§7 Q9 above) explicitly exercises confidence gating end-to-end. |
| Manual override emits new file | Via A3's two-pass hash: any frontmatter change (including `supersedes_confidence` promotion) changes `content_hash` → new filename → D14 flow. Not a separate code path. |
| Historical file retention / GC | Phase 0 policy: **never delete old hash-addressed files**. GC is explicitly deferred to Phase 1+. Every file written stays until a deliberate retention policy is implemented. |

Additional Phase-0-specific risks:

- **Schema drift between `schema.sql` and live DB** — mitigated by running schema.sql idempotently on every `open_corpus_db` call (task B1) + test `test_schema_idempotent`.
- **Canary reveals convention flaw** — budgeted for: ≤1 hour wall-clock to re-extract the canary set; ~$2 per re-extraction cycle at Claude Haiku 4.5 pricing. If we need 3+ iterations of the convention, flag as a planning concern (probably means §4 of the arch doc needs a revision, which is unexpected at this stage).
- **LLM provider reliability** — Gemini 2.5 Flash was unreliable in recent operation; Phase 0 defaults to Claude Haiku 4.5 via the existing `CompletionProvider` abstraction (A0). If Anthropic has an outage during canary ingestion, the existing 4-attempt backoff handles transient errors; `LLM_PROVIDER=openai` env var swaps to OpenAI without code change. If both fail simultaneously, canary ingestion blocks — but at 8-12 ticker scale, manual intervention is tractable.
- **Parallel session collisions on risk_module files** — migration tasks (F1-F3) touch config paths that the parallel `feat/*` sessions may also touch. Mitigation: Block F runs on `feat/corpus-impl-phase0-migration` branch, not on main; merge back to main only after all canary tests pass.

---

## 9. Out of Scope (Explicitly)

Everything already deferred in §1.2 plus:

- **Implementation plan for Phases 1-4** — separate plans per phase, drafted as we approach each.
- **`FILINGS_CORPUS_INDEX_PLAN.md`** — this doc is the phase-0 version; later phase plans may consolidate under that name or remain per-phase.
- **Research workspace integration** — the corpus stands alone; any integration with `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` artifacts is a separate project.
- **Cost accounting / LLM usage tracking** — Phase 0 consumes ~$2-5 of Anthropic API spend total; not worth instrumentation at this scale. Phase 1+ warrants per-filing token accounting when scale hits S&P 500.
- **Admin tools** — "re-extract this ticker", "rebuild this document's sections", "promote supersession confidence" are helpful but Phase 1 conveniences.

---

## 10. Open Questions for Plan Review

Resolved in Codex review round 1 (or by the user before sending to Codex):

**P1. ~~Which canonical path for new risk_module modules?~~** *RESOLVED 2026-04-21.* Core logic under `core/corpus/` (matches `core/security_identity/`, `core/result_objects/`, `core/factor_intelligence/` patterns).

**P2. ~~MCP tool registration location?~~** *RESOLVED 2026-04-21.* Core logic in `core/corpus/` (functions return typed `SearchResponse`/`SearchHit`/etc.). MCP adapters in `mcp_tools/corpus/` — thin wrappers that register the tool with MCP decorators and marshal dataclasses to JSON. Separation of concerns — core functions are importable + testable without MCP runtime; MCP adapters only deal with dispatch/serialization.

**P3. ~~langextract_mcp import or vendor?~~** *RESOLVED 2026-04-21.* Vendor. Copy `parse_filing_sections()` from `AI-excel-addin/mcp_servers/langextract_mcp/text_utils.py` into `core/corpus/section_map.py` with a module-level docstring crediting the origin. Cross-repo imports are fragile (env/installability varies); vendored copy is small (~30 lines) and we own the evolution path.

**P4. ~~CORPUS_ROOT default path?~~** *RESOLVED 2026-04-21.* `<repo>/data/filings/` (matches D7, matches current Edgar_updater output relative location, aligns with D15 migration target). Env-var override supported for deployment configs.

**P5. Microcap canary pick.**
Need an actual small-cap ticker with a recent spartan 10-K. No strong lean — propose during G1 task execution.

**P6. Amendment canary pick.**
Need a real 10-K/A + original pair. Candidates: look for recent SEC amendments in the last 12 months across mid-cap tickers. Propose during E1 task execution.

**P7. LLM extraction rerun policy.**
If Phase 0 canary ingestion fails for an intermittent reason (API rate limit, transient model error), retry policy: use Edgar_updater's existing 4-attempt exponential backoff (`extraction.py:RETRY_MAX_ATTEMPTS`) — which is now driven by the `CompletionProvider` abstraction (A0) and handles both Anthropic and OpenAI errors uniformly. Failures exceeding 4 attempts flag for manual review; do NOT silently write `extraction_status='failed'` in Phase 0 (too few docs to tolerate silent partial corpus — every failure is worth a human look).

**P8. Test DB location.**
Proposed: pytest fixture creates temp SQLite DB per test; fixtures for pre-populated corpus in `tests/fixtures/corpus/` (small canonical filings as test data). Confirm pattern.

---

## 11. What's NOT in this plan but IS in scope for Phase 0 execution

Things every engineer implementing Phase 0 needs to do, even though they're not their own tasks:

- **Per-task commits.** Each task lands as its own commit (matches the `feat(corpus): ...` pattern in current repo history).
- **Keep `docs/TODO.md` V2.P1 entry updated.** Status transitions: `ARCH PASS — IMPL PLAN NEXT` → `IMPL PLAN APPROVED` (when this plan PASS'es Codex) → `IN PROGRESS` (when Block A starts) → `PHASE 0 COMPLETE` (when G4 ships).
- **Update `CORPUS_ARCHITECTURE.md` header's status line** when Phase 0 completes — mark the canary validation.
- **Drop a memory note** on any surprise — e.g., if `parse_filing_sections()` doesn't work as expected from the research, or the gateway citation-provider pattern turns out to be more lift than expected. Keeps the memory system in sync with actual reality.
