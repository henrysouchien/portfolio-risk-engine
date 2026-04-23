# Document Corpus — Implementation Plan (Phase 0 Canary)

**Status:** **Codex-reviewed PASS** after 14 rounds (R1 FAIL → R14 PASS). Phase 0 plan is locked. Ready for implementation.
**Last updated:** 2026-04-22

**Codex review history:**
- R1 — FAIL with 2 CRITICAL + 6 MAJOR + 3 MINOR. Resolved by: adding transcript ingestion tasks; reworking `filings_source_excerpt` to use `source_url_deep`; reworking A0 for self-contained Anthropic wrapper; adding META to canary; removing invalid `CREATE INDEX` on FTS5; introducing A8 as sole writer; explicit `extraction_status` rules; splitting B4 into B4a-e; fixing low-confidence SQL; parametrizing F3 rollback.
- **R14 — PASS.** *"A developer can execute A0 from this plan plus the cited refs today."* Minor editorial polish applied (stale `~300 lines` → `~400 lines`, stale `MissingProviderCredentialsError` → `LLMProviderNotConfiguredError`, service.py "add a parallel branch" → "no changes needed — typed exception flows through", Phase-0-tops-out `~15 documents` → `~60-80 documents`). Codex-flagged top execution risks carried forward: (1) LangExtract `model=` path ignores `use_schema_constraints` — A0 depends on prompt-following quality; (2) vendored import rewrite must be exact; (3) parity test can skip when Edgar_updater absent, weakening drift protection if not run in full-repo CI; (4) validator model reporting drift risk if implemented via env-var re-read; (5) retry tuning was Gemini/OpenAI-era — Anthropic failure modes need smoke-test confirmation.
- R13 — FAIL with 1 CRITICAL + 1 MAJOR + 3 MINOR. Narrow; Codex noted "after those doc fixes, a dev can execute A0 today." Resolved by: **(1)** `_require_llm_provider_configured()` sketch corrected to raise `LLMProviderNotConfiguredError` consistently in both error branches (prior RuntimeError inconsistency would have let the generic `extract_filing()` wrapper swallow the exception); **(2)** adapter threading through `_extract_text()` / `_extract_section()` / executor call sites at `extraction.py:568,593,633` specified — `api_key` parameter renamed to `adapter: VendoredProviderAdapter` across helper signatures; full refactor shape shown; **(3)** `llm_client.py` size updated to ~400 lines (Codex verified by assembling the file from current source; was "~250" / "~300" inconsistently); **(4)** A0 effort rollup in §6.3 fixed: M→L with note on scope expansion reason; **(5)** validator-test wording clarified — `:98` + `:130` are two call sites inside a single existing test, not two standalone tests.
- R12 — FAIL with 2 CRITICAL + 3 MAJOR + 3 MINOR. Resolved by: **(1)** vendoring recipe corrected to include `logger` + `T` TypeVar at providers/completion.py:16-17 (prior "from line 18 onward" omitted them; would break runtime) + `@runtime_checkable` decorator on the inlined Protocol (from providers/interfaces.py:204); **(2)** stale `_require_llm_provider_configured(api_key)` call-site fixed to match parameter-less signature; **(3)** typed-exception re-raise added at extract_filing() before the generic try/except wrapper (prior version's LLMProviderNotConfiguredError would be swallowed by line 665 status-dict wrapper — R12 finding). Plus parallel service.py handler specified; **(4)** parity-test CI prerequisite specified — Phase 0 uses pytest.skip guard when Edgar_updater checkout missing, with alternatives documented; **(5)** three existing Google-specific tests added to A0 scope: test_document_routes.py:284, test_validate_extraction_schemas.py:98 + :130; **(6)** MINORs: `provider._default_model` (underscore-prefixed private attr) named correctly, or alternative via LLM_DEFAULT_MODEL env var re-read; A0 effort bumped from M to L with split suggestion (A0a/A0b/A0c optional); `api_key_env` metadata noted as cleaner alternative for Phase 1.
- R11 — FAIL with 1 CRITICAL + 3 MAJOR + 2 MINOR. Codex drilled into Edgar_updater integration surfaces A0 didn't cover. Resolved by: **(1)** making vendoring recipe executable — line-by-line structure for `llm_client.py` with explicit import-rewrite rule (remove `from providers.interfaces import CompletionProvider` since Edgar_updater has no providers/interfaces.py; inline the Protocol instead; preserve `from __future__ import annotations` as first statement); **(2)** real provider validation in `_require_llm_provider_configured()` — checks API key env var presence per provider (ANTHROPIC_API_KEY for anthropic, OPENAI_API_KEY for openai) not just None-result; fails fast before any extraction; **(3)** expanding A0 scope to cover other Google-hardcoded surfaces: `scripts/validate_extraction_schemas.py:1193` (hard-fail on GOOGLE_API_KEY, :990 records DEFAULT_MODEL_ID), `routes/documents.py:65` (ValueError → 503 only matches GOOGLE_API_KEY string), `service.py:221` (converts error dicts to ValueError). Introduced `LLMProviderNotConfiguredError` typed exception class with route-layer handler; **(4)** making Haiku default explicit via `LLM_DEFAULT_MODEL=claude-haiku-4-5-20251001` env var in the config block — previously only prose; Anthropic provider's internal default is actually `claude-sonnet-4-6` (3-5x cost), so env var must be set; **(5)** MINOR: fixed swapped line refs (OpenAI is :90, Anthropic is :190 — not :89 and :190); removed unused `api_key` param from `_require_llm_provider_configured()` signature.
- R10 — FAIL with 1 CRITICAL + 2 MAJOR + 2 MINOR. Codex confirmed A0 adapter is finally correct; surrounding Edgar_updater integration had issues. Resolved by: **(1)** replacing `_require_google_api_key()` (which aborts if `GOOGLE_API_KEY` unset, breaking Phase 0's Anthropic default) with `_require_llm_provider_configured()` that builds provider via `build_completion_provider()` and raises a clear error if unconfigured. Threads null-check through provider construction so `VendoredProviderAdapter` never receives `None`. Updated call-site sketch shows the full three-step replacement (provider build → adapter → lx_extract with `model=adapter`); **(2)** expanding vendoring scope from "public functions + helpers" to "entire module body of `providers/completion.py` + CompletionProvider Protocol from `providers/interfaces.py` + append `VendoredProviderAdapter`" — captures the private runtime state (`_PROVIDER_FACTORIES`, `_completion_provider`, `_completion_provider_initialized`, `_completion_lock`, `_reset_completion_provider`) that public functions depend on. Parity test still enforces public-surface equality; whole-module rule enforces private state comes along; **(3)** fixed `system=""` → `system=None`; **(4)** fixed line references to `lx_extract` call site (`extraction.py:227`); **(5)** fixed remaining `infer(prompts, **kwargs)` prose.
- R9 — FAIL with 1 CRITICAL + 1 MAJOR + 2 MINOR. A0 adapter signature errors surfaced AGAIN because Codex inspected live code and found 3 more issues I spec'd incorrectly. Resolved by verifying against actual source: **(1)** LangExtract calls `infer(batch_prompts=...)` — parameter name MUST match (verified at `annotation.py:392`). Also `CompletionProvider.complete(prompt, *, system=None, ...)` takes `prompt` positionally + `system` keyword (verified at `providers/interfaces.py:210`) — my `user=prompt_text` was an invented parameter. Real factory is `build_completion_provider()` (verified at `providers/completion.py:268`), not imagined `get_default_provider()`. All three corrected inline with line-number citations so future rounds can verify; **(2)** aligning vendoring scope with parity test — plan now explicitly lists all four public functions in `providers/completion.py` for vendoring (`get_provider_metadata`, `build_completion_provider`, `get_completion_provider`, `complete_structured`) + the underscore helpers that `complete_structured` depends on. `SOURCE_ONLY_SYMBOLS` allowlist stays empty unless intentional additions arrive later; **(3)** adding `mcp_tools/corpus/__init__.py` + `core/corpus/__init__.py` empty package markers to C5 / file-touched lists; **(4)** making `form_type` subset validation placement explicit — in `filings_search` wrapper BEFORE delegating to `_search`, using `FILINGS_FAMILY_FORM_TYPES = frozenset({'10-K', '10-Q', '8-K'})` constant + example error message.
- R8 — FAIL with 1 CRITICAL + 1 MAJOR + 3 MINOR. Codex inspected installed LangExtract package again; found A0 adapter broken in three ways. Resolved by: **(1)** fixing A0 `VendoredProviderAdapter` to match real installed-package API — `ScoredOutput` imported from `langextract.core.types` (not `core.base_model`); `infer()` signature is `Iterator[Sequence[ScoredOutput]]` yielding one sequence per prompt (consumed by `annotation.py:392`); `super().__init__()` called in `__init__` so `_schema` + `requires_fence_output` are set (read at `base_model.py:38`); **(2)** resolving AST parity contradiction between strict-equality code and "shared symbols" prose — strict equality IS intentional, with explicit `SOURCE_ONLY_SYMBOLS` allowlist (initially empty) for intentional source-only additions; error message tells implementer how to resolve; **(3)** documenting SQLite `rowcount` nuance — counts matched rows including no-op UPDATEs, which is the right semantic for supersession use case but worth calling out; **(4)** C5 file-touched reconciled with P2 resolution — explicit `mcp_tools/corpus/` package + `tests/test_tool_surface_sync.py` recursion update now listed as C5 scope (was stale "mcp_server.py or wherever"); **(5)** filings_search form_type subset rule stays in C2 wrapper (per-family contract), not C4 universal validation — made explicit.
- R7 — FAIL with 2 MAJOR + 4 MINOR. Codex inspected installed LangExtract package to ground findings. Resolved by: **(1)** locking A0 LangExtract contract to verified installed-package API — `VendoredProviderAdapter` inherits from `langextract.core.base_model.BaseLanguageModel`, `infer()` returns `Sequence[ScoredOutput]` (not `list[str]`), adapter wraps each completion as `ScoredOutput(output=..., score=1.0)`. Documented that `model=` path **ignores `use_schema_constraints`** (per `langextract/extraction.py:232`) — plan explicitly commits to prompt-following contract as the mitigation. Removed duplicate `anthropic` from Edgar_updater requirements (already present); **(2)** locking filings_search form_type contract — None defaults to family (`['10-K', '10-Q', '8-K']`), caller-supplied list must be a subset, cross-family (e.g., 'TRANSCRIPT') raises `InvalidInputError`. Matches §7 canary queries Q1/Q2/Q3/Q5 usage; **(3)** upgraded G1 to BLOCKING-for-G2 with explicit lockdown acceptance criteria — 8-12 canonical tickers with exact accessions, real amendment pair, real multi-8-K case, real microcap. P5/P6 tied to G1 lockdown; **(4)** fixing `update_is_superseded_by()` return value from `db.total_changes` (connection-cumulative) to `cur.rowcount` per-call; **(5)** tightening AST parity test to assert full key-set match (catches add/remove, not just in-place drift) for both public functions and module constants; **(6)** C3 transcripts_source_excerpt flattening now emits `## PREPARED REMARKS` + `## Q&A SESSION` parent headers before speaker blocks — matches corpus-file structure so `filings_read` output and `transcripts_source_excerpt` output are parallel in shape.
- R6 — FAIL with 2 MAJOR + 2 MINOR. No CRITICAL. Resolved by: **(1)** rewriting A0 to match the actual Edgar_updater extraction path which uses `langextract.extraction.extract` (not raw Gemini API calls). Plan now specifies a `VendoredProviderAdapter` class in the vendored `llm_client.py` that wraps `AnthropicCompletionProvider` / `OpenAICompletionProvider` and conforms to LangExtract's `BaseLanguageModel` interface (exact class name to be confirmed at implementation time — inspection step added as A0 prerequisite). Extraction schema/prompts/concurrency/retry loops and downstream parsing stay unchanged. `lx_extract()` call site modified to accept adapter instance; if LangExtract version doesn't support pluggable models, escalate to user; **(2)** tightened AST comparator: `_func_signature()` now captures `is_async: bool` field (flipping sync↔async is drift); `test_vendored_provider_ast_matches_source()` now compares all public module-level functions (not just one named factory) + all module-level ALL_CAPS constants (catches DEFAULT_MODEL drift) across the symbols both source and vendored expose; **(3)** C3 error handling uses `result.get('error', 'unknown FMP error')` (no KeyError on malformed payloads) + specifies deterministic precedence (prepared_remarks check first, then qa; first-failure raises); **(4)** A5/A6 prose corrected to match the locked conditional `### SPEAKER: {name}` + optional ` ({role})` format (wording cleanup).
- R5 — FAIL with 2 MAJOR + 2 MINOR. Narrow findings. Resolved by: **(1)** explicit `status='error'` handling in `transcripts_source_excerpt` mapping FMP error responses to `ExcerptUnavailableError` BEFORE any flattening (FMP returns `{'status': 'error', 'error': ...}` for missing transcripts per `transcripts.py:947,966`, not empty lists); **(2)** rewritten A0 AST comparator covering full signature surface — positional/kwonly/posonly args, varargs/kwargs, defaults, kw_defaults, return types, decorators (sorted), class bases (catches Protocol drops), class-level typed attrs, plus module-level factory function check. Per-symbol comparison with detailed failure messages; **(3)** transcript excerpt format corrected to `### SPEAKER: {name}` with `({role})` suffix only when role non-empty — matches A6 + `fmp/tools/transcripts.py:713` + `AI-excel-addin/api/research/document_service.py:236` locked convention; **(4)** added CHECK constraint on `fiscal_period` column — accepts only canonical forms (`YYYY-FY`, `YYYY-QN`, `YYYY-MM-DD`) via SQLite GLOB patterns. Malformed fiscal_period rejected at INSERT/UPDATE, preventing the C1 COALESCE from synthesizing garbage URLs.
- R4 — FAIL with 5 MAJOR + 3 MINOR. No CRITICAL. Stale-block pattern again — edits added new content but left adjacent pre-refactor content. Resolved by: **(1)** fixing `transcripts_source_excerpt` to avoid preview-mode truncation at `transcripts.py:873` — spec'd two-call retrieval strategy (per-section calls when no speaker filter) + empty-match contract raises `ExcerptUnavailableError`; **(2)** removing the direct-import-vs-vendoring contradiction in A0 — vendoring is the only strategy, with explicit AST-level parity test using `ast.unparse()` on class signatures (ignores docstrings/whitespace/imports, catches semantic drift); **(3)** full DEF 14A sweep — removed from §1 canary edge cases, A1 taxonomy deliverable, C2 `filings_search` default form_types; Phase 0 filings scope is now strictly 10-K/10-Q/8-K; **(4)** pinning `source_url` synthesis to `_search`'s SQL via explicit `COALESCE(d.source_url, CASE WHEN d.source='fmp_transcripts' THEN ... END)` so `SearchHit.source_url` is non-null by construction at query time; **(5)** deleted the stale duplicate A6 block that reintroduced file-I/O expectations; **(6)** removed the duplicate `FrontmatterValidationError` definition from B3's types.py sketch — single owner is `core/corpus/frontmatter.py` (A2); A8 test corrected to expect `FrontmatterValidationError` not `InvalidInputError`; **(7)** fixed §4 "~20 tasks" → "31 tasks total (see §6.3)".
- R3 — FAIL with 6 MAJOR + 3 MINOR. No CRITICAL (progress). R2 fixes had stale pre-refactor details from earlier rewrites. Resolved by: **(1)** adding `max_words=None` + response-shape flattening spec to `transcripts_source_excerpt` (default 3000-word truncation was returning preview not verbatim); **(2)** specifying Edgar_updater's `parse_filing_sections()` real return shape (sections keyed by canonical IDs like `item_7`, not corpus header strings) + adding `corpus_header_to_edgar_id()` mapping helper; **(3)** DROPPED DEF 14A from Phase 0 canary (parse_filing_sections rejects it outright at `section_parser.py:198`; proxy-statement support deferred to Phase 1 with explicit paths); **(4)** replaced A0 comment-only vendoring with enforceable 3-layer drift protection — parity test in CI + source-side marker + version marker in vendored file with sha/date; **(5)** rewrote A8 against current A2/A3/A4/A6 APIs — 16-zero CANONICAL_HASH_PLACEHOLDER, `assemble_canonical_text()` + `finalize_with_hash()` call sequence, `_build_transcript_body()` integration; **(6)** LOCKED Q4 ticker to MSFT (guaranteed FMP quarterly transcript coverage); dropped BRK.B transcript hand-wave; **(7)** relaxed `documents.source_url` to NULLABLE for sources without canonical URLs (FMP transcripts), spec'd synthetic URL template `https://financialmodelingprep.com/financial-summary/{ticker}?transcript={year}Q{quarter}` with query-surface synthesis fallback if NULL; **(8)** defined `ExcerptUnavailableError` + `FrontmatterValidationError` in B3; **(9)** renamed all `CompletionClient` references to `CompletionProvider`; **(10)** rewrote §6 critical path diagram + parallelizable tracks + effort table to reflect current 31-task structure.
- R2 — FAIL with 2 CRITICAL + 5 MAJOR + 3 MINOR. R1 fixes were partly cosmetic; R2 identified: **(1)** `parse_filing_sections` from langextract_mcp only matches filing headers — cannot produce transcript sections_fts rows; transcript parser exists separately at `AI-excel-addin/api/research/document_service.py:234`. **(2)** A2/A4/A6 still assigned writes to source-specific writers despite A8 claim. **(3)** `filings_source_excerpt` named a non-existent `extract_section_by_header`; real helper is `parse_filing_sections(html, filing_type)` at `Edgar_updater/edgar_parser/section_parser.py:242`; `source_url_deep IS NULL` fallback not spec'd. **(4)** `transcripts_source_excerpt` used `output='file'` which returns metadata not text; must use `output='inline'`. **(5)** A0 overstated packaging difficulty — `CompletionProvider` IS importable; file path `edgar_parser/extraction.py` doesn't exist (real is `edgar_api/documents/extraction.py`); package file is `requirements.txt` not `pyproject.toml`. **(6)** Q4 canary regressed — mandatory BRK.B transcript dropped + acceptance weakened to conditional. **(7)** A3/A8 hash flow self-referential — needed explicit canonical-form convention. **(8)** F3 rollback didn't test app-level config flip. **(9)** Q2 criterion expected filing_date DESC but C1 defines BM25 only. **(10)** P2 mcp_tools/corpus/ breaks existing tool-surface sync test. All resolved by: adding per-source section parsers (A5 now covers both filings `parse_filing_sections` + transcripts `parse_transcript_sections` via dispatcher); fully rewriting A2/A3/A4/A6 as pure body+metadata producers with NO file I/O (A8 owns all writes); specifying `filings_source_excerpt` fallback via accession-keyed URL construction when `source_url_deep` null; fixing `transcripts_source_excerpt` to use `output='inline'`; grounding A0 in real file paths with vendoring decision for CompletionProvider; making BRK.B transcript mandatory (or substitute ticker with guaranteed coverage); specifying canonical-form hash convention with placeholder literal; adding app-config flip test to F3; clarifying Q2 ordering is client-side; adding tool-surface sync test update to C5.

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
- Canary edge cases: one amendment (10-K/A), one same-day multi-8-K day. (DEF 14A / proxy statements **dropped from Phase 0** — `parse_filing_sections()` rejects DEF 14A at `Edgar_updater/edgar_parser/section_parser.py:198`; proxy-statement support deferred to Phase 1 per G1 + C2.)
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

Seven blocks, 31 concrete tasks total (see §6.3 effort table for breakdown), rough sequencing with dependencies called out. Each task has: goal, files touched, tests, depends-on, effort estimate (S/M/L ≈ <4h / 4-16h / >16h).

### Block A — Canonicalization + frontmatter (ingestion-side convention)

Lock the markdown convention, swap the extraction model, and wire Edgar_updater to emit spec-compliant output.

#### A0. Swap Edgar_updater's LLM client to risk_module's CompletionProvider

**Goal:** Replace Edgar_updater's Gemini 2.5 Flash extraction with Claude Haiku 4.5. **Use vendored copies** of risk_module's existing `CompletionProvider` abstraction (`providers/interfaces.py:205` Protocol + `providers/completion.py:55,146` OpenAI + Anthropic impls) inside Edgar_updater, with enforceable AST-level parity checking to prevent drift. Gemini has been unreliable in recent operation; Haiku is the reliability floor we want for a long-lived corpus.

**Why vendor, not direct import:** direct import requires cross-repo Python path setup that varies by dev/prod environment, deploy scripts, and per-user `pip install` conventions. Edgar_updater uses `requirements.txt` (no PyPI-published risk_module distribution), so declarative dependency on risk_module's providers is not currently available. Vendoring is the stable Phase 0 path; Phase 1+ may publish `risk-module-llm` as a separate package and replace the vendored copies with a pip dependency.

**Rationale:**
- `CompletionProvider` already exists, so vendoring is copy-paste, not redesign.
- `LLM_PROVIDER` env var (honored by the factory in `providers/completion.py`) makes model swap deploy-time rather than code change. Phase 1+ can bump specific filings to Sonnet via routing logic without revisiting this work.
- Cost delta: Phase 0 canary ~$2 (was ~$0.30 on Gemini Flash); Phase 2 full corpus ~$1,500 (was ~$250). Acceptable one-time spend for reliability.

**Enforceable drift protection — AST-level parity check:**

1. **Vendor target — `Edgar_updater/edgar_api/documents/llm_client.py`.** Executable vendoring recipe:

```
Line 1:     # Vendored from risk_module/providers/ on <DATE>
            # vendored_sha: <commit>
            # vendored_date: <YYYY-MM-DD>
            # Parity-tested by risk_module/tests/test_provider_vendoring_parity.py
            # Sync rule: re-vendor on source changes (parity test fails otherwise).

Line 2:     from __future__ import annotations    # MUST be the first non-comment statement

Line 3-N:   # Imports — copy providers/completion.py's import block EXCEPT drop
            #   `from providers.interfaces import CompletionProvider` (Edgar_updater has no
            #   providers/interfaces.py; Protocol is inlined below).
            # Keep: import os, threading, logging, from typing import ..., etc.
            # Include the TypeVar declaration: `T = TypeVar("T", bound=BaseModel)` — appears
            #   at providers/completion.py:17 — `complete_structured()` references it, so
            #   omitting breaks the vendored module.
            # Include the `logger = logging.getLogger(__name__)` line at providers/completion.py:16
            #   — same reasoning; private state references it.
            # Add (new to vendored file): `from typing import Iterator, Sequence`
            # Add: `from langextract.core.base_model import BaseLanguageModel`
            # Add: `from langextract.core.types import ScoredOutput`

Line N+1:   # --- Inlined CompletionProvider Protocol (verbatim from providers/interfaces.py:204-221) ---
            #   Must include `@runtime_checkable` decorator at line 204 — not optional; some
            #   code paths may rely on isinstance() checks against the Protocol.
            @runtime_checkable
            class CompletionProvider(Protocol):
                """Provider contract for text completion (prompt -> str) tasks."""
                provider_name: str
                def complete(self, prompt: str, *, system: str | None = None,
                             model: str | None = None, max_tokens: int = 2000,
                             temperature: float = 0.5, timeout: float | None = None) -> str: ...
            # Also need: `from typing import Protocol, runtime_checkable` in imports.

Line N+2-M: # --- Body of providers/completion.py (from line 20 onward — after imports + `T` + logger) ---
            # All classes + module-level functions + private state + helpers + exceptions,
            # verbatim byte-for-byte. Includes:
            #   - UnsupportedStructuredOutputSchemaError  (line 20)
            #   - _normalize_openai_strict_schema         (line 24)
            #   - _openai_strict_json_schema              (line 49)
            #   - OpenAICompletionProvider                (line 55)
            #   - AnthropicCompletionProvider             (line 146)
            #   - _PROVIDER_FACTORIES                     (line 238 — required by build_completion_provider)
            #   - _completion_provider + _completion_provider_initialized + _completion_lock (line ~243 — required by get_completion_provider)
            #   - get_provider_metadata                   (line 248)
            #   - build_completion_provider               (line 268)
            #   - get_completion_provider                 (line 293)
            #   - complete_structured                     (line 311)
            #   - _reset_completion_provider              (line 356)

Line M+1:   # --- NEW: LangExtract adapter (Phase 0) ---
            class VendoredProviderAdapter(BaseLanguageModel):
                # ... (see the adapter definition below)
```

**Key import-rewrite rule:** the vendored file MUST start with `from __future__ import annotations` as the first non-comment statement (Python language requirement). All other imports must come before any code. Specifically: REMOVE the `from providers.interfaces import CompletionProvider` line from the source — the Protocol is inlined above the body. ADD the LangExtract imports for `BaseLanguageModel` and `ScoredOutput`. Everything else from source is preserved.

**Vendored scope** (what's being copied):
   - `CompletionProvider` Protocol (inlined from `providers/interfaces.py:205`)
   - `AnthropicCompletionProvider` + `OpenAICompletionProvider` classes
   - All four public module-level functions: `get_provider_metadata`, `build_completion_provider`, `get_completion_provider`, `complete_structured`. **All MUST be vendored** — AST parity test compares the full public surface.
   - Private runtime state: `_PROVIDER_FACTORIES`, `_completion_provider`, `_completion_provider_initialized`, `_completion_lock`, `_reset_completion_provider`. Parity test catches signature drift but NOT missing module state — these are required at runtime.
   - Private helpers: `_normalize_openai_strict_schema`, `_openai_strict_json_schema`, `UnsupportedStructuredOutputSchemaError`.
   - NEW: `VendoredProviderAdapter(BaseLanguageModel)` (LangExtract integration, appended).

**Operational rule:** "copy the whole module body verbatim, rewrite imports per the rule above, append `VendoredProviderAdapter`." The parity test enforces public-symbol match; the "whole-module-body" rule enforces private state comes along; the import-rewrite rule makes the file compile on first read.

Vendored file header:

```python
# Vendored from risk_module/providers/interfaces.py + providers/completion.py
# vendored_sha: <source-commit-sha>
# vendored_date: <YYYY-MM-DD>
# Parity-tested by risk_module/tests/test_provider_vendoring_parity.py
# On source changes: update sha + date, re-copy, re-run parity test.
```

2. **Source-side marker** — comment at top of `providers/completion.py`: `# Vendored into Edgar_updater/edgar_api/documents/llm_client.py — update both on change.`

3. **Parity test in risk_module CI** — new `tests/test_provider_vendoring_parity.py`.

**CI prerequisite (R12):** the parity test reads `../Edgar_updater/edgar_api/documents/llm_client.py` from the risk_module test suite, which assumes both repos are checked out side-by-side (`<parent>/risk_module/` + `<parent>/Edgar_updater/`). Phase 0 dev-environment convention already sets this up (both repos cloned into the same parent dir). Three implementation options to make this robust:
   - **(a) [chosen, simplest]** Skip the test if Edgar_updater is not present: `pytest.skip("Edgar_updater checkout not found at ../Edgar_updater — parity check unavailable in this CI environment")`. Test runs locally + in full-repo CI; CI environments that only check out risk_module skip it. Trade: silent skip can hide drift if only run in one env.
   - **(b)** Require side-by-side checkout via an explicit `ENV_EDGAR_UPDATER_PATH` env var; fail test hard if unset. More explicit but requires CI config.
   - **(c)** Publish the vendored file to a pip package and check parity against the installed package. Phase 1+.

Phase 0 uses **option (a)** — skip if missing, with clear skip message. Implementation adds a `pytest.skip()` guard at the top of the test function.

Operational comparator covers the full surface the provider contract exposes — positional args, keyword-only args, defaults, bases (including Protocol), decorators, class attributes, plus the module-level factory:

```python
import ast

def _arg_sig(arg: ast.arg) -> tuple:
    """(name, annotation_text) — unparse() gives normalized annotation source."""
    return (arg.arg, ast.unparse(arg.annotation) if arg.annotation else None)

def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    """Extract full function signature surface."""
    args = node.args
    return {
        'name': node.name,
        'is_async': isinstance(node, ast.AsyncFunctionDef),  # async/sync drift matters — a provider flipping async breaks every caller
        'positional': [_arg_sig(a) for a in args.args],
        'posonly': [_arg_sig(a) for a in args.posonlyargs],
        'kwonly': [_arg_sig(a) for a in args.kwonlyargs],
        'vararg': _arg_sig(args.vararg) if args.vararg else None,
        'kwarg': _arg_sig(args.kwarg) if args.kwarg else None,
        'defaults': [ast.unparse(d) for d in args.defaults],
        'kw_defaults': [ast.unparse(d) if d else None for d in args.kw_defaults],
        'returns': ast.unparse(node.returns) if node.returns else None,
        'decorators': sorted(ast.unparse(d) for d in node.decorator_list),  # sorted: order-independent
    }

def _class_signature(node: ast.ClassDef) -> dict:
    """Extract full class signature surface: bases, decorators, methods, class attrs."""
    methods = {}
    class_attrs = {}
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods[item.name] = _func_signature(item)
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            # class-level typed attributes (e.g., `model: str`)
            class_attrs[item.target.id] = ast.unparse(item.annotation) if item.annotation else None
    return {
        'bases': sorted(ast.unparse(b) for b in node.bases),
        'decorators': sorted(ast.unparse(d) for d in node.decorator_list),
        'methods': methods,
        'class_attrs': class_attrs,
    }

def _find_class(tree: ast.AST, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None

def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None

def test_vendored_provider_ast_matches_source():
    """Fails if vendored copy diverges from source in any load-bearing way.
    Compares AST structures per-symbol; ignores docstrings, comments, whitespace,
    import ordering. Fails on: method signature changes (positional/kwonly/varargs),
    defaults changes, class-attribute type changes, base-class changes (e.g., Protocol
    dropped), decorator changes, factory-function signature changes."""
    source_interfaces = ast.parse(_read('providers/interfaces.py'))
    source_completion = ast.parse(_read('providers/completion.py'))
    vendored_tree = ast.parse(_read('../Edgar_updater/edgar_api/documents/llm_client.py'))

    # Classes — CompletionProvider lives in interfaces.py; impls in completion.py
    for class_name, source_tree in [
        ('CompletionProvider', source_interfaces),
        ('AnthropicCompletionProvider', source_completion),
        ('OpenAICompletionProvider', source_completion),
    ]:
        source_sig = _class_signature(_find_class(source_tree, class_name))
        vendored_sig = _class_signature(_find_class(vendored_tree, class_name))
        assert source_sig == vendored_sig, (
            f"Vendored CompletionProvider drift detected in class {class_name}.\n"
            f"  Source signature:   {source_sig}\n  Vendored signature: {vendored_sig}\n"
            "Re-vendor Edgar_updater/edgar_api/documents/llm_client.py and bump vendored_sha + vendored_date."
        )

    # Module-level functions — compare every public callable in providers/completion.py
    # that is part of the vendored surface. Allowlist mechanism: SOURCE_ONLY_SYMBOLS
    # lists public source-only symbols that the vendored copy intentionally omits
    # (e.g., risk_module-specific helpers). Adding a symbol to SOURCE_ONLY_SYMBOLS
    # is an explicit policy decision; the test fails on implicit drift.
    SOURCE_ONLY_SYMBOLS: set[str] = {
        # Populate with names of public functions/constants in providers/completion.py
        # that are intentionally NOT vendored into Edgar_updater/edgar_api/documents/llm_client.py.
        # Example: 'streaming_complete' if that's risk_module-only.
        # Empty by default — every public symbol must be vendored unless listed here.
    }

    def _public_functions(tree: ast.AST) -> dict[str, dict]:
        return {
            node.name: _func_signature(node)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith('_')
        }

    source_funcs = _public_functions(source_completion)
    vendored_funcs = _public_functions(vendored_tree)
    # Assert full key-set match AFTER removing allowlisted source-only symbols.
    # Catches implicit drift (new source symbol not in allowlist and not vendored,
    # or vendored-side-only symbol) while permitting intentional source-only additions.
    source_vendored_surface = source_funcs.keys() - SOURCE_ONLY_SYMBOLS
    assert source_vendored_surface == vendored_funcs.keys(), (
        f"Vendored public function set drift.\n"
        f"  In source (not allowlisted) but missing from vendored: {source_vendored_surface - vendored_funcs.keys()}\n"
        f"  In vendored but not in source: {vendored_funcs.keys() - source_funcs.keys()}\n"
        f"Options: re-vendor the missing symbol, or add it to SOURCE_ONLY_SYMBOLS with a comment explaining why."
    )
    for fn_name in source_vendored_surface:
        assert source_funcs[fn_name] == vendored_funcs[fn_name], (
            f"Vendored function {fn_name} drift: source != vendored"
        )

    # Module-level constants that callers rely on (e.g., DEFAULT_MODEL, DEFAULT_PROVIDER)
    def _module_constants(tree: ast.AST) -> dict[str, str]:
        """Extract module-level ALL_CAPS constant bindings. Value comparison via ast.unparse."""
        result = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        result[t.id] = ast.unparse(node.value) if node.value else None
        return result

    source_consts = _module_constants(source_completion)
    vendored_consts = _module_constants(vendored_tree)
    # Full key set — catches add/remove of module-level constants.
    assert source_consts.keys() == vendored_consts.keys(), (
        f"Vendored module-constant set drift. "
        f"In source not vendored: {source_consts.keys() - vendored_consts.keys()}. "
        f"In vendored not source: {vendored_consts.keys() - source_consts.keys()}."
    )
    for const_name in source_consts:
        assert source_consts[const_name] == vendored_consts[const_name], (
            f"Vendored constant {const_name} drift: {source_consts[const_name]} != {vendored_consts[const_name]}"
        )
```

The comparator covers everything that matters for duck-typed API parity: positional args, posonly, kwonly, defaults, return types, decorators, class bases (catches `Protocol` drops or similar), class-level typed attrs, and the module-level factory. Ignores docstrings, comments, imports, whitespace — things that don't affect behavior. Sorted decorators/bases to avoid false failures on rearrangement.

Phase 1+ may promote to a published `risk-module-llm` package; vendoring is stable for Phase 0 scope.

**The integration is NOT a raw-completion swap.** The real extraction path at `Edgar_updater/edgar_api/documents/extraction.py:540` uses `langextract.extraction.extract` (imported as `lx_extract`) — a structured-extraction library that takes `prompt_description`, `examples`, `model_id`, and returns an `AnnotatedDocument` with `extractions` attribute. Downstream parsing at `extraction.py:227+` depends on this shape. Replacing `lx_extract` with a raw `CompletionProvider.complete()` call would break everything downstream.

**Chosen approach — LangExtract adapter, contract locked against installed package:**

LangExtract's pluggable-model path is `extract(..., model=<BaseLanguageModel instance>, ...)`. Three package facts from inspecting the installed LangExtract (R8 verified):

1. `ScoredOutput` lives in `langextract.core.types` (NOT `langextract.core.base_model`). Constructible with `ScoredOutput(output=..., score=...)`.
2. `BaseLanguageModel.infer(batch_prompts, **kwargs)` yields `Iterator[Sequence[ScoredOutput]]` — **one `Sequence[ScoredOutput]` per prompt**, not a flat `Sequence[ScoredOutput]`. `annotation.py:392` consumes it as `for prompt_outputs in infer_result: ...`, so flat-list return breaks downstream. Parameter name is `batch_prompts` (LangExtract's calls are keyword-based).
3. `VendoredProviderAdapter.__init__()` MUST call `super().__init__()` — otherwise `_schema` + `requires_fence_output` are unset and `extract()` crashes at `base_model.py:38` when it reads `language_model.requires_fence_output`.

```python
# In Edgar_updater/edgar_api/documents/llm_client.py (vendored)
from typing import Iterator, Sequence
from langextract.core.base_model import BaseLanguageModel
from langextract.core.types import ScoredOutput
# CompletionProvider Protocol + AnthropicCompletionProvider/OpenAICompletionProvider
# + build_completion_provider / get_completion_provider / get_provider_metadata /
# complete_structured are vendored in this same file (see vendoring scope below).

class VendoredProviderAdapter(BaseLanguageModel):
    def __init__(self, provider: CompletionProvider):
        super().__init__()   # BaseLanguageModel.__init__() initializes
                             # _constraint, _schema, _fence_output_override, _extra_kwargs.
                             # Required because extract() later reads
                             # requires_fence_output at langextract/extraction.py:300.
        self._provider = provider

    def infer(
        self,
        batch_prompts: Sequence[str],   # LangExtract's annotation.py calls
                                        # infer(batch_prompts=prompts, ...) —
                                        # parameter name MUST match
        **kwargs,
    ) -> Iterator[Sequence[ScoredOutput]]:
        """Generator — yields one Sequence[ScoredOutput] per prompt.
        LangExtract's annotation.py:392 iterates the outer level as prompts,
        inner level as samples-per-prompt. We emit one ScoredOutput per
        prompt (single-sample mode). score=1.0 since CompletionProvider.complete()
        doesn't expose model confidence; score is used only for ranking when
        num_samples > 1."""
        for prompt_text in batch_prompts:
            completion = self._provider.complete(
                prompt_text,           # positional — per providers/interfaces.py:210
                                       # signature: complete(self, prompt, *, system=None,
                                       # model=None, max_tokens=2000, temperature=0.5, timeout=None)
                system=None,           # no system prompt. Both OpenAICompletionProvider.complete
                                       # (providers/completion.py:90) and AnthropicCompletionProvider.complete
                                       # (line 190) only forward `system` when truthy, so "" and None
                                       # behave identically — None is clearer.
                max_tokens=4000,
                temperature=0.0,
            )
            yield [ScoredOutput(score=1.0, output=completion)]
            # ScoredOutput is a dataclass with field order (score, output) per
            # langextract/core/types.py:54; we use kwargs to avoid coupling to order.
```

**Schema constraints behavior (critical — was a blocker before R7):** LangExtract's `extract(..., model=<instance>, ...)` path IGNORES `use_schema_constraints` (per inspection of installed `langextract/extraction.py:232`). This means when we pass our adapter, LangExtract will not apply its Gemini-specific schema-enforcement passes. **Mitigation:** the extraction prompts already include `prompt_description` + `examples` (defined in `Edgar_updater`'s schema objects); the model produces structured output based on those. The downstream parser in `extraction.py:227+` works against the unconstrained-model output shape that Gemini produces today, so Claude producing the same markdown-shaped output via prompt-following is the contract — NOT schema enforcement. If Claude consistently deviates from the prompt-described shape, the A0 smoke test will catch it; either (a) prompt refinement, or (b) re-enabling LangExtract's schema pass via a different integration mode, are fallbacks.

**Files touched:**
- `Edgar_updater/edgar_api/documents/llm_client.py` (new, ~400 lines — Codex verified by assembling the vendored file from current source). Vendored `CompletionProvider` + `AnthropicCompletionProvider` + `OpenAICompletionProvider` + all four public functions + private state + helpers + `LLMProviderNotConfiguredError` + `VendoredProviderAdapter(BaseLanguageModel)`. Header comment pins vendoring source.
- `Edgar_updater/edgar_api/documents/extraction.py` — three coordinated changes:
  1. **`lx_extract(...)` call site** at line 227 (inside the retry loop — verified; line 540 was the `from langextract.extraction import extract as lx_extract` import). Swap `model_id="gemini-2.5-flash"` for `model=adapter` where adapter is constructed as below. `model_id` kwarg may still be accepted by lx_extract for backward compat; when `model=` is set, `model_id` is ignored.
  2. **Replace `_require_google_api_key()`** (defined at `extraction.py:133`, called at `extract_filing()` around line 544). Current behavior: raises `RuntimeError("Missing GOOGLE_API_KEY environment variable.")` before any LangExtract work. For Anthropic/OpenAI providers this check aborts the run even though no Google key is needed. Replace with `_require_llm_provider_configured()`:
```python
def _require_llm_provider_configured() -> CompletionProvider:
    """Phase 0 replacement for _require_google_api_key(). Resolves the configured
    provider per LLM_PROVIDER env var and validates its API key is present BEFORE
    returning — so a misconfigured env fails fast here, not at first .complete() call.

    Validation layers (in order):
      (1) Provider name resolves — build_completion_provider() returns None only for
          unknown provider names (per providers/completion.py:282). Caught first.
      (2) Required API key present — the provider's credential env var must be set
          + non-empty. build_completion_provider() itself only stashes env values in
          constructors (providers/completion.py:63 + :158); it does NOT validate
          presence. We validate here.
    """
    provider = build_completion_provider()
    provider_name = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if provider is None:
        raise LLMProviderNotConfiguredError(
            f"LLM_PROVIDER={provider_name!r} is not a known provider. "
            f"Valid values: {sorted(_PROVIDER_FACTORIES.keys())}."
        )

    # Validate API-key env var presence based on resolved provider name
    required_env_var = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get(provider_name)
    if required_env_var and not os.getenv(required_env_var, "").strip():
        raise LLMProviderNotConfiguredError(
            f"LLM_PROVIDER={provider_name!r} requires {required_env_var} to be set + non-empty. "
            f"Export it: `export {required_env_var}=<your-key>`."
        )
    return provider
```

`LLMProviderNotConfiguredError(RuntimeError)` is defined in the vendored `llm_client.py` (see "Simpler alternative" below). Raising it here (not plain RuntimeError) is what makes the typed-exception propagation path at `extract_filing()` → `service.py` → `routes/documents.py` work as spec'd — plain RuntimeError would be caught by the generic wrapper at `extraction.py:665` and lose type.
  3. **Build adapter once at the top of `extract_filing()`, thread it through helpers:**

Current code (confirmed via inspection) passes `api_key=resolved_api_key` through `_extract_text()` (`extraction.py:568`), `_extract_section()` (`:593`), and the executor call site (`:633`). The adapter replaces `api_key` in those signatures — adapter is the new unit of work that helpers call `lx_extract()` with.

```python
# In extract_filing() at the top (where _require_google_api_key used to be called):
provider = _require_llm_provider_configured()   # raises LLMProviderNotConfiguredError if unconfigured
adapter = VendoredProviderAdapter(provider)

# Existing helpers currently signed as _extract_text(text, schema, api_key, ...) and
# _extract_section(text, schema, api_key, ...) get their `api_key` parameter renamed to
# `adapter: VendoredProviderAdapter`. Each helper passes `model=adapter` to lx_extract(...)
# instead of `model_id="gemini-2.5-flash"` + `api_key=api_key`:
def _extract_text(text, schema, adapter, ...):   # was: def _extract_text(text, schema, api_key, ...)
    result = lx_extract(
        text_or_documents=stripped_text,
        prompt_description=schema.prompt_description,
        examples=list(schema.examples),
        model=adapter,                 # was model_id="gemini-2.5-flash", api_key=api_key
        extraction_passes=DEFAULT_EXTRACTION_PASSES,
        max_workers=DEFAULT_MAX_WORKERS,
        max_char_buffer=DEFAULT_MAX_CHAR_BUFFER,
        show_progress=DEFAULT_SHOW_PROGRESS,
    )
    ...

# Executor call site at :633 similarly updated — `adapter` passed instead of `resolved_api_key`.
```

Cleanup: the `resolved_api_key = _require_google_api_key(api_key)` line (at ~:544) is deleted; the old `api_key` parameter on `extract_filing()` is no longer needed (backward-compat note: keep accepting it with a deprecation warning for one release cycle, or drop if no external callers — Phase 0 is greenfield for this pipeline).

This threads the null-check through the provider construction — `VendoredProviderAdapter` never receives a None provider. Existing retry/concurrency/fetch loops unchanged.

**Additional Google-hardcoded surfaces in Edgar_updater that A0 must also update** (surfaced by R11 inspection):

- `Edgar_updater/scripts/validate_extraction_schemas.py:1193` — hard-fails on `GOOGLE_API_KEY` unset. Replace with the same `_require_llm_provider_configured()` pattern, or (simpler) update to call Edgar_updater's own helper after A0 defines it. Line 990 also records `DEFAULT_MODEL_ID` (still `"gemini-2.5-flash"`); update to record the resolved provider's actual model. The provider classes store the default as a private `_default_model` attr (see `providers/completion.py:64` for OpenAI, `:159` for Anthropic); access via `provider._default_model` OR — cleaner — via `os.getenv("LLM_DEFAULT_MODEL", "")` directly since that's what the factory honored anyway.

- `Edgar_updater/edgar_api/routes/documents.py:65` — maps `ValueError` to HTTP 503 only when the message contains `GOOGLE_API_KEY`. Update to catch the typed `LLMProviderNotConfiguredError` (defined in vendored `llm_client.py`) explicitly and map to HTTP 503.

- `Edgar_updater/edgar_api/documents/service.py:221` — converts extraction-error dicts from `extract_filing()` back to `ValueError`. The 503-mapping in `routes/documents.py` depends on the message content, so if we raise a typed exception in `_require_llm_provider_configured()`, the `service.py:221` path needs to preserve the type (not flatten to ValueError with a generic message).

**Simpler alternative (Phase 0 choice):** define a new exception class `LLMProviderNotConfiguredError(RuntimeError)` in `Edgar_updater/edgar_api/documents/llm_client.py` (vendored file). Raise it from `_require_llm_provider_configured()`. Update `routes/documents.py:65` to catch `LLMProviderNotConfiguredError` → HTTP 503. This is cleaner than string-match updates and matches the typed-exception pattern used elsewhere in risk_module.

**Critical exception-propagation fix** (R12 surfaced this): `extract_filing()` at `Edgar_updater/edgar_api/documents/extraction.py:665` wraps ALL exceptions in a status dict (`{"status": "error", ...}`), which would swallow `LLMProviderNotConfiguredError` before it reaches `service.py:221` or `routes/documents.py`. Fix: add an explicit re-raise BEFORE the generic try/except wrapper:

```python
# In extract_filing(), at the top of the try block (before line 665's generic except):
try:
    provider = _require_llm_provider_configured()   # raises LLMProviderNotConfiguredError if unconfigured
    # ... rest of extraction work ...
except LLMProviderNotConfiguredError:
    raise   # Don't wrap in status dict — let the typed exception propagate to service.py → route
except Exception as exc:
    return {"status": "error", "error": str(exc), ...}   # existing generic fallback (unchanged)
```

`service.py:221` (error-dict-to-ValueError converter) requires NO change for the typed exception — since `extract_filing()` now re-raises `LLMProviderNotConfiguredError` BEFORE wrapping in the error dict, the typed exception never reaches service.py's dict-to-ValueError code path. The typed exception flows through `service.py` unchanged as Python exception propagation. Example sequence for completeness:

```python
# In service.py, where extract_filing's error dict is converted:
result = extract_filing(...)   # may raise LLMProviderNotConfiguredError directly now
if result.get("status") == "error":
    raise ValueError(result["error"])   # existing behavior for other errors
# LLMProviderNotConfiguredError flows through as-is since extract_filing re-raises it
```

This ensures the typed exception reaches `routes/documents.py` where the 503 handler catches it.

**Existing Google-specific tests that A0 must update** (R12 surfaced these — A0 isn't complete without them):
- `Edgar_updater/tests/test_document_routes.py:284` — asserts the specific `GOOGLE_API_KEY` string-match path in route 503-mapping. Update to assert `LLMProviderNotConfiguredError` routing behavior instead.
- `Edgar_updater/tests/test_validate_extraction_schemas.py:98` + `:130` — two call sites inside a single existing test that exercise the validator script's current Google-specific failure paths. Update both assertions to cover the new provider-neutral validation + the resolved-model reporting (replaces the `DEFAULT_MODEL_ID` constant-match).

Adding these test updates makes A0 properly end-to-end; without them, the new error paths would be unreachable through existing test suites + the old Google-path tests would fail against the new code.
- `Edgar_updater/requirements.txt` — add `openai>=1.50` (confirmed NOT already present). `anthropic>=0.40` is **already present** in requirements.txt — do not duplicate.
- `providers/completion.py` (risk_module) — add the source-side marker comment noted in the vendoring section.

**Phase 0 default config — explicit env-var setup:**

```bash
# Provider selection — Anthropic (Claude) is the Phase 0 default per user reliability concerns with Gemini
export LLM_PROVIDER=anthropic

# Model override — AnthropicCompletionProvider's internal default is `claude-sonnet-4-6`
# (providers/completion.py:156). Phase 0 wants Haiku for cost reasons (canary + pilot scale).
# The factory (build_completion_provider) honors LLM_DEFAULT_MODEL env var
# (providers/completion.py:279) which flows into the provider constructor as default_model.
# MUST be set explicitly — prose "defaults to Haiku" is not enough; without this export,
# the provider will default to Sonnet and cost ~3-5x per filing.
export LLM_DEFAULT_MODEL=claude-haiku-4-5-20251001

# Required API key — _require_llm_provider_configured() validates this is present + non-empty
export ANTHROPIC_API_KEY=<your-anthropic-key>
```

- Retry: keep Edgar_updater's existing 4-attempt exponential backoff; Anthropic SDK errors map cleanly onto its transient-retry classification.
- Prompt caching: if Anthropic's cache-control feature is available in the provider impl, enable it for stable-prefix sections of the extraction prompt (matches V2.P5 direction; small win per-doc but adds up at scale).

**Depends on:** nothing. Can start before A1.

**Tests:**
- `Edgar_updater/tests/test_llm_client_swap.py::test_completion_provider_dispatch` — monkeypatch the vendored `AnthropicCompletionProvider.complete()` to return canned output; verify extraction pipeline consumes it correctly.
- `Edgar_updater/tests/test_llm_client_swap.py::test_retry_on_rate_limit` — raise `anthropic.RateLimitError` from the wrapper; verify Edgar_updater's exponential backoff kicks in.
- `Edgar_updater/tests/test_llm_client_swap.py::test_provider_env_var_override` — set `LLM_PROVIDER=openai`; verify OpenAI client instantiated.
- Smoke test against canary AAPL 10-K: real Anthropic API call, verify output is structurally valid (correct section headers per convention) and triggers no downstream task failures. **Do NOT require "structurally equivalent to Gemini output"** — Claude may produce different section lengths or phrasings. The schema and section-taxonomy compliance is what matters; surface-text equivalence is not a goal.

**Effort:** L (grew from M during R11/R12 reviews). Task now covers: vendored `llm_client.py` (~400 lines), extraction.py swap + `_require_llm_provider_configured()` + typed-exception re-raise, validator script update, route-handler 503 update (service.py needs no changes — typed exception flows through unchanged), parity test with CI-skip guard, test updates for 3 existing test files (`test_document_routes.py`, `test_validate_extraction_schemas.py` × 2 call sites), requirements.txt update, smoke test. Consider splitting into A0a (vendoring + parity), A0b (extraction swap + provider helper), A0c (route/validator integration + test updates) if one developer; keep unified if treated as a single coordinated change.

**Follow-ups deferred to later phases:**
- Per-filing model routing (Sonnet for complex XBRL-heavy filings) — Phase 1 optimization.
- Batch API support for Anthropic (currently Anthropic's batch tier is message-batches API, different shape) — Phase 2 cost optimization.
- Re-evaluating Gemini or other providers — if a specific future version proves reliable, the CompletionProvider abstraction makes the swap a one-line change.

#### A1. Write the markdown convention spec

**Goal:** Single-source-of-truth for the file format. Codifies §4.2-§4.4 of the arch doc into a validator-friendly form.

**Deliverable:** `docs/planning/completed/CORPUS_MARKDOWN_CONVENTION.md` (short — ~150 lines). Frontmatter field list with types + required/optional markers; canonical section taxonomy per form type (10-K, 10-Q, 8-K, TRANSCRIPT — proxy statements / DEF 14A deferred to Phase 1); file path layout; content_hash definition (full-file SHA-1 including frontmatter, first 8 hex chars per A3 canonical-form convention); `document_id` format per source.

**Depends on:** nothing (pure spec).

**Tests:** N/A (doc).

**Effort:** S.

#### A2. `core/corpus/frontmatter.py` — schema validator + serializer (risk_module side, no file I/O)

**Goal:** A single frontmatter builder + validator that both filings ingestion and transcripts ingestion pipe *body text + metadata dict* through. **This task does NOT touch the filesystem** — it's a pure-function library. File writes live in A8.

**Files touched:**
- New `core/corpus/frontmatter.py`:

```python
from dataclasses import dataclass

CANONICAL_HASH_PLACEHOLDER = "0" * 16  # hex chars; replaced with real 8-hex content_hash post-hash

@dataclass(frozen=True)
class FrontmatterValidationError(Exception):
    missing_required: list[str]
    invalid_types: list[tuple[str, str]]  # (field, reason)

def build_frontmatter(metadata: dict, *, with_placeholder_hash: bool = True) -> str:
    """Validate metadata against the spec (A1), serialize to YAML.
    Uses CANONICAL_HASH_PLACEHOLDER for content_hash field when with_placeholder_hash=True.
    Returns '---\\n{yaml}\\n---'."""

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split '---\\n{yaml}\\n---\\n{body}' into (metadata_dict, body_text)."""

def assemble_canonical_text(metadata: dict, body: str) -> str:
    """build_frontmatter(metadata, with_placeholder_hash=True) + '\\n' + body."""
```

**Fields populated by callers before passing to build_frontmatter:**
- `document_id` — for filings: `f"edgar:{accession}"`; for transcripts: `f"fmp_transcripts:{ticker}_{fiscal_period}"`; for future Quartr decks: TBD in V2.P8.
- `ticker`, `cik`, `company_name`, `source`, `form_type`, `fiscal_period`, `filing_date`, `period_end` — from the source pipeline's metadata.
- `source_url` (stable landing), `source_url_deep` (optional direct HTML) — per arch §7.3 URL templates.
- `source_accession` — SEC accession (filings); NULL for transcripts.
- `extraction_pipeline` — e.g., `edgar_updater@0.5.0` or `fmp_transcripts@3.2.1` (package semver).
- `extraction_model` — e.g., `claude-haiku-4-5-20251001`, recorded per-file for auditability.
- `extraction_at` — ISO-8601 timestamp.
- `content_hash` — **left as `CANONICAL_HASH_PLACEHOLDER` by the caller**; A3's `finalize_with_hash()` computes the real hash over the assembled text + substitutes.
- `sector`, `industry`, `sector_source=GICS`, `exchange` — optional.
- `supersedes`, `supersedes_source`, `supersedes_confidence` — NULL at Phase 0 except for the canary amendment authored per E1.

**Depends on:** A1 (spec).

**Tests:**
- `tests/test_frontmatter.py::test_required_fields_enforced` — missing `document_id` raises `FrontmatterValidationError`.
- `tests/test_frontmatter.py::test_type_check` — invalid `filing_date` raises with field name.
- `tests/test_frontmatter.py::test_placeholder_hash_in_output` — `build_frontmatter(..., with_placeholder_hash=True)` emits literal `"0000000000000000"` in the content_hash slot.
- `tests/test_frontmatter.py::test_roundtrip` — `parse_frontmatter(assemble_canonical_text(meta, body))` yields `(meta, body)`.

**Effort:** S.

#### A3. Canonical content_hash convention

**Goal:** Define `content_hash` so the stored hash can be verified by re-hashing the file. Per R7 (D6): *"content_hash is a SHA-1 of the full canonical markdown — frontmatter + body — first 8 hex chars."* The self-referential problem (you can't hash a file whose content includes its own hash) is solved by defining the **canonical form**:

> The canonical form of a corpus markdown file is the file as written, but with the `content_hash` frontmatter field value replaced by `CANONICAL_HASH_PLACEHOLDER = "0000000000000000"` (16 zeros). `content_hash` = first 8 hex chars of SHA-1(canonical_form).

Verification for any existing file: read file → replace the `content_hash: <stored>` line with `content_hash: 0000000000000000` → SHA-1 → first 8 hex chars → compare to stored. This is reproducible, human-explainable, and does not require storing the canonical form separately.

**Files touched:**
- `core/corpus/frontmatter.py` — add `finalize_with_hash(assembled_text_with_placeholder: str) -> tuple[str, str]` that (1) SHA-1's the input, (2) returns the text with placeholder replaced by the real 8-hex hash + the hash string.
- `core/corpus/frontmatter.py` — add `verify_content_hash(text: str) -> bool` that implements the verification protocol above.

**Depends on:** A2.

**Tests:**
- `tests/test_frontmatter.py::test_hash_is_of_canonical_form` — produce a file via `finalize_with_hash`; re-run the canonical-form derivation; re-hash; assert match.
- `tests/test_frontmatter.py::test_verify_detects_tampering` — flip a byte in the body; `verify_content_hash` returns False.
- `tests/test_frontmatter.py::test_verify_ignores_stored_hash_value` — changing only the `content_hash` frontmatter line (e.g., rotating to another valid-looking hex) and re-verifying recomputes to a different hash, flagging tampering.
- `tests/test_frontmatter.py::test_frontmatter_change_produces_new_hash` — changing `supersedes_confidence` from `low` to `high` produces a different hash (metadata-only promotion works).

**Effort:** S.

#### A4. Directory layout + ticker canonicalization

**Goal:** Define the canonical output path computation as a pure function, plus document the ticker normalization that callers must apply before calling it. **No file writes in this task.**

**Files touched:**
- `core/corpus/frontmatter.py` — add `canonical_path(metadata: dict, corpus_root: Path) -> Path` returning `corpus_root / metadata['source'] / metadata['ticker'] / f"{metadata['form_type']}_{metadata['fiscal_period']}_{metadata['content_hash']}.md"`.
- `core/corpus/ingest.py` will call `SymbolResolver.resolve_identity()` (at `providers/symbol_resolution.py:203`) before constructing the metadata dict, so `metadata['ticker']` is already canonical when `canonical_path` sees it.

**Depends on:** A2.

**Tests:**
- `tests/test_corpus_paths.py::test_canonical_output_path` — various metadata dicts → expected paths.
- `tests/test_corpus_paths.py::test_share_class_canonicalization` — pre-canonicalized GOOG/GOOGL, BRK.A/BRK.B produce different paths (canonicalization must happen before this function is called).
- `tests/test_corpus_paths.py::test_international_ticker` — pre-canonicalized AT./AT.L round-trip.
- `tests/test_corpus_paths.py::test_rejects_noncanonical_ticker` — passing a lowercase/exchange-prefixed ticker raises (sanity check on caller contract).

**Effort:** S.

#### A6. Retrofit transcript writer to return (body, metadata) — drop file I/O

**Goal:** `fmp/tools/transcripts.py:682` (`_write_transcript_markdown`) currently emits directly to a file via `atomic_write_text()`. Refactor to return `(body: str, metadata: dict)` — no file I/O, no frontmatter, no staging. The caller (A8) wraps with frontmatter + writes to CORPUS_ROOT. Also: drop the non-canonical `### EXCHANGE {idx}: ...` sub-headers (lines ~738) — arch §4.4 only allows `## PREPARED REMARKS` / `## Q&A SESSION` / `### SPEAKER: {Name}` (with optional ` ({Role})` suffix when role is known — matches the parser at `AI-excel-addin/api/research/document_service.py:236` + locked fmp convention at `fmp/tools/transcripts.py:713`).

**Changes:**
- Rename `_write_transcript_markdown(result, file_path)` → `_build_transcript_body(result) -> tuple[str, dict]`. Returns body string + metadata dict ready for `core/corpus/frontmatter.py::build_frontmatter()`.
- Drop `### EXCHANGE {idx}:` headers. Each Q&A speaker turn becomes a standalone `### SPEAKER: {name}` heading with ` ({role})` appended only when role is non-empty (matches the conditional format used by `fmp/tools/transcripts.py:713`'s current output and the parser at `document_service.py:236`).
- Preserve analyst-then-management turn order (implicit question/answer pairing; no explicit header).
- Caller at `fmp/tools/transcripts.py:1023` (`_write_transcript_markdown(result, attempted_path)`) updated to: call `_build_transcript_body(result)` → pass `(body, metadata)` to `core/corpus/ingest.py::ingest_raw()` (A8) instead of writing directly.
- Metadata dict includes: `document_id=f"fmp_transcripts:{ticker}_{fiscal_period}"`, `source='fmp_transcripts'`, `form_type='TRANSCRIPT'`, `ticker`, `fiscal_period` (canonical `YYYY-QN`), `filing_date` (from `result['date']`), `period_end` (same as filing_date for FMP transcripts), `extraction_pipeline`, `extraction_model`, `extraction_at`. No supersedes fields.
- **Transcript URL construction** — FMP's API response gives only `symbol`, `quarter`, `year`, `date`, `content` — no canonical URL. Per arch §7.3 the synthetic template is `source_url = f"https://financialmodelingprep.com/financial-summary/{ticker}?transcript={year}Q{quarter}"`. Use this as a best-effort stable link. If the page 404s on some quarters, citations still resolve via `document_id` — the `source_url` is a human-clickable convenience, not a verification requirement. `source_url_deep` is NULL for FMP transcripts (no direct text URL). **The schema was relaxed in B1 to allow nullable source_url**; transcripts actually populate it via the template above, so the nullable allowance is a safety net, not routine use. For `SearchHit` output layer: if `source_url` is somehow NULL at query time, the query surface synthesizes it from ticker+period at marshaling time to preserve I10 (every citation carries a source link).

**Files touched:**
- `fmp/tools/transcripts.py` — refactor `_write_transcript_markdown` → `_build_transcript_body`; remove `atomic_write_text()` call; drop `### EXCHANGE` lines; update call site at line 1023 to call `core/corpus/ingest.py::ingest_raw()`.

**Depends on:** A2 (frontmatter helper), A8 (ingest_raw exists).

**Tests:**
- `fmp/tests/test_transcript_writer.py::test_returns_body_and_metadata` — function signature change; no file produced in test.
- `fmp/tests/test_transcript_writer.py::test_no_exchange_headers` — Q&A block contains only `### SPEAKER:` headings; no `### EXCHANGE`.
- `fmp/tests/test_transcript_writer.py::test_speaker_order_preserved` — analyst-then-management turn order intact.
- `fmp/tests/test_transcript_writer.py::test_metadata_document_id_format` — metadata dict has correct `document_id=fmp_transcripts:MSFT_2025-Q1`.
- Integration test: `fmp/tests/test_transcript_writer.py::test_via_ingest_raw` — full flow from FMP API response → `_build_transcript_body()` → `ingest_raw()` → file on disk + DB row.

**Effort:** M.

#### A7. Amendment link field threading (transcript case: no-op)

**Goal:** Confirm transcripts don't carry `supersedes` fields in Phase 0 (transcripts don't amend each other in the Phase 0 canary; if a company re-issues a transcript with corrections it's rare enough to defer to Phase 1+). Frontmatter omits `supersedes` / `supersedes_source` / `supersedes_confidence` for `source=fmp_transcripts`. Documented here so reviewers don't assume parity with filings.

**Effort:** S (documentation task — no code).

#### A8. Ingestion orchestrator (single authoritative write path) — resolves Codex MAJOR #6

**Goal:** One module in risk_module that owns the canonical write-to-`CORPUS_ROOT` flow. Both Edgar_updater (filings) and fmp/tools (transcripts) produce **raw canonicalized bodies** (section-structured markdown without frontmatter); the orchestrator in risk_module wraps them with frontmatter, computes content_hash, writes to staging, atomic-renames into `CORPUS_ROOT/{source}/{ticker}/{form}_{period}_{hash}.md`.

**Files touched:**
- New `core/corpus/ingest.py::ingest_raw(body: str, metadata: dict, corpus_root: Path, db: sqlite3.Connection) -> IngestResult`:
  1. Validate `metadata` via `core/corpus/frontmatter.py::build_frontmatter(metadata, with_placeholder_hash=True)` — this is a pure function that validates + serializes; `FrontmatterValidationError` raised for required-field / type violations **before** any file I/O.
  2. Call `core/corpus/frontmatter.py::assemble_canonical_text(metadata, body)` → canonical markdown with `CANONICAL_HASH_PLACEHOLDER` (16 zeros per A3 convention) in the content_hash slot.
  3. Write canonical text to `staging/{uuid}.md`.
  4. Call `core/corpus/frontmatter.py::finalize_with_hash(canonical_text)` → returns `(finalized_text, content_hash)` where `content_hash` is the first 8 hex of SHA-1 of the placeholder form (NOT the finalized form — the hash is of the canonical form per A3 to make verification round-trip work).
  5. Update metadata dict with the real `content_hash`. Rewrite staging file with `finalized_text` (placeholder replaced).
  6. Compute canonical path via `core/corpus/frontmatter.py::canonical_path(metadata, corpus_root)`.
  7. Atomic `os.rename(staging_path, canonical_path)`.
  8. Parse sections via `core/corpus/section_map.py::parse_sections(finalized_text, metadata['source'])` (the dispatcher — routes filings vs transcripts automatically).
  9. Open SQLite transaction: UPSERT `documents` row keyed on `document_id`; DELETE + INSERT `sections_fts` rows for this document_id; if `supersedes` is set with `supersedes_confidence='high'`, call `core/corpus/supersession.py::update_is_superseded_by(db, document_id=supersedes)` (B2 helper — scoped).
  10. Return `IngestResult(status='complete', document_id, content_hash, canonical_path, warnings=[])`.

**Edgar_updater integration:**
- `Edgar_updater/edgar_api/documents/extraction.py` — modified so the extraction pipeline returns `(body, metadata)` tuples instead of writing to disk. Caller invokes `ingest_raw()` (G2's ingestion driver).

**fmp/tools/transcripts.py integration:**
- Per A6: `_write_transcript_markdown` renamed to `_build_transcript_body(result) -> tuple[body, metadata]`. Call site at line 1023 (was `_write_transcript_markdown(result, attempted_path)`) updated to call `ingest_raw(body, metadata, corpus_root, db)`.

**This collapses Codex MAJOR #6**: `Block A` is no longer about writing files; it's about producing canonicalized bodies + metadata. `ingest_raw()` is the sole writer. Atomic-rename + UPSERT + reconciler hook all live in one place.

**Depends on:** A1, A2, A3 (body/frontmatter helpers), A5 (offsets), B1 (schema), B3 (types).

**Tests:**
- `tests/test_corpus_ingest.py::test_ingest_raw_filing` — canned body + metadata → disk file + DB row + sections_fts rows.
- `tests/test_corpus_ingest.py::test_ingest_raw_transcript` — same for transcript body.
- `tests/test_corpus_ingest.py::test_validation_rejects_missing_required` — metadata missing `document_id` → `FrontmatterValidationError` before any file write. (Raised by `build_frontmatter()` in step 1 of `ingest_raw`, not `InvalidInputError` which is the tool-boundary validation exception from C4/I13.)
- `tests/test_corpus_ingest.py::test_atomic_rename_crash_before_commit` — simulate crash between rename and SQLite commit (kill the process in test); verify reconciler heals.

**Effort:** M.

#### A5. Section/offset parser — per-source (filings + transcripts have different taxonomies)

**Goal:** For each canonicalized markdown file, compute the `char_start` + `char_end` for every canonical section. Needed for D12 section-grain FTS5 rows. **Two parsers are required because filings and transcripts have incompatible section conventions:**

- **Filings** use `^## SECTION: {header}$` (per arch §4.3). Vendor `parse_filing_sections()` from `AI-excel-addin/mcp_servers/langextract_mcp/text_utils.py:11` into `core/corpus/section_map.py::parse_filing_sections(text: str) -> SectionMap`. Single-parser reuse.
- **Transcripts** use `## PREPARED REMARKS` / `## Q&A SESSION` + `### SPEAKER: {Name} ({Role})` (per arch §4.4). The **transcript parser already exists** at `AI-excel-addin/api/research/document_service.py:234` as `DocumentService.parse_transcript_sections(text) -> list[dict]`. Vendor that into `core/corpus/section_map.py::parse_transcript_sections(text) -> list[(section, content, char_start, char_end, speaker_name, speaker_role)]`, adapting the return shape to match filings' `SectionMap` contract + speaker fields.

Both functions return a common shape compatible with the section-row INSERT in B1's `sections_fts` schema.

**Files touched:**
- New `core/corpus/section_map.py` — both parsers, plus a `parse_sections(text: str, source: str) -> list[SectionRow]` dispatcher that routes by `source` (from the file's frontmatter). Callers (A8 ingestion, B4c reconciler) use the dispatcher — they never pick a parser by hand.

```python
@dataclass(frozen=True)
class SectionRow:
    section: str                 # canonical header
    content: str                 # full section text
    char_start: int
    char_end: int
    speaker_name: str | None     # transcripts only
    speaker_role: str | None     # transcripts only

def parse_sections(text: str, source: str) -> list[SectionRow]:
    if source == 'edgar':
        return _parse_filing_sections(text)
    elif source == 'fmp_transcripts':
        return _parse_transcript_sections(text)
    # Future: 'quartr' -> _parse_deck_sections
    raise ValueError(f"Unknown source: {source}")
```

**Depends on:** A1 (convention — section taxonomies live there).

**Tests:**
- `tests/test_section_map.py::test_filings_sections_offsets` — real canary 10-K markdown; every `## SECTION: Item N.` header detected with non-overlapping offsets covering body.
- `tests/test_section_map.py::test_transcripts_offsets` — canary transcript with prepared remarks + Q&A + speaker turns; section bounds correct; `speaker_name`/`speaker_role` populated per row.
- `tests/test_section_map.py::test_dispatcher_routes_correctly` — `parse_sections(text, source='edgar')` hits filings path; `source='fmp_transcripts'` hits transcript path; unknown source raises.
- `tests/test_section_map.py::test_filings_empty_sections_omitted` — 10-K missing Item 1B produces no row for it.
- `tests/test_section_map.py::test_transcript_no_qa_section` — transcript with prepared remarks only (rare) still parses cleanly.

**Effort:** M (two parsers to vendor + dispatcher + tests).

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
    source_url TEXT,                        -- NULLABLE: some sources (FMP transcripts) expose no stable canonical URL — see A6 transcript notes. I10 still enforces non-null on SearchHit outputs by deriving a fallback URL template at query time for such sources.
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
    CHECK (supersedes_confidence IS NULL OR supersedes_confidence IN ('high', 'medium', 'low')),
    -- fiscal_period format validator — needed because C1's SQL source_url synthesis
    -- for transcripts does `substr(fiscal_period, 1, 4)` + `substr(fiscal_period, 7, 1)`
    -- and would produce garbage URLs on malformed input. Accepts canonical forms:
    --   YYYY-FY   (annual, e.g., '2025-FY')
    --   YYYY-QN   (quarterly, e.g., '2025-Q1')
    --   YYYY-MM-DD (8-K date-specific)
    -- Any other shape rejected at INSERT/UPDATE time.
    CHECK (
        fiscal_period IS NULL
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-FY'
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-Q[1-4]'
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    )
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

    Returns matched-rows count for THIS call. Uses Cursor.rowcount rather than
    db.total_changes (which is connection-level cumulative across the whole session).

    SQLite rowcount semantic nuance: counts MATCHED rows — including no-op UPDATEs
    where the new value equals the existing value. Callers that care about "actually
    changed" vs "visited" should compare before/after snapshots, not rely on rowcount.
    For the supersession use case, matched-rows is the right count (we want to know
    how many rows the query touched, not whether the pointer value actually flipped).
    """
    if document_id is None:
        # Global recompute — set all originals' is_superseded_by from scratch
        cur1 = db.execute("UPDATE documents SET is_superseded_by = NULL")
        cur2 = db.execute("""
            UPDATE documents SET is_superseded_by = (
                SELECT d2.document_id FROM documents d2
                WHERE d2.supersedes = documents.document_id
                  AND d2.supersedes_confidence = 'high'
                ORDER BY d2.filing_date DESC, d2.document_id DESC
                LIMIT 1
            )
        """)
        return (cur1.rowcount or 0) + (cur2.rowcount or 0)
    else:
        # Scoped update — single original
        cur = db.execute("""
            UPDATE documents SET is_superseded_by = (
                SELECT d2.document_id FROM documents d2
                WHERE d2.supersedes = documents.document_id
                  AND d2.supersedes_confidence = 'high'
                ORDER BY d2.filing_date DESC, d2.document_id DESC
                LIMIT 1
            )
            WHERE document_id = ?
        """, (document_id,))
        return cur.rowcount or 0
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


class ExcerptUnavailableError(Exception):
    """Raised by *_source_excerpt when the authoritative source can't be fetched
    (e.g., source_url_deep 404s, URL construction fails, form_type not supported
    for verbatim excerpt in Phase 0). Carries document_id and the reason so the
    agent/UI can surface the gap honestly rather than silently substitute
    non-verbatim content."""
    def __init__(self, document_id: str, reason: str):
        self.document_id = document_id
        self.reason = reason
        super().__init__(f"Source excerpt unavailable for {document_id}: {reason}")

# NOTE: FrontmatterValidationError is defined in core/corpus/frontmatter.py (A2),
# not here. Importable from there; raised by build_frontmatter/assemble_canonical_text.
# Keeping exception definitions close to the module that raises them.
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
    form_types: list[str],           # resolved form_type list — per-family DEFAULT unless caller narrows (see below)
    sources: list[str],              # preset per family (filings → ['edgar']; transcripts → ['fmp_transcripts'])
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
       d.fiscal_period, d.filing_date,
       -- source_url synthesis at query time: documents.source_url is NULLABLE per
       -- B1 schema (FMP transcripts sometimes don't carry one at ingestion). SearchHit
       -- contract (B3) types source_url as non-optional str — preserve I10 by COALESCING
       -- to a synthetic URL at query time.
       COALESCE(
           d.source_url,
           CASE
               WHEN d.source = 'fmp_transcripts'
                   THEN 'https://financialmodelingprep.com/financial-summary/' || d.ticker
                        || '?transcript=' || substr(d.fiscal_period, 1, 4)
                        || 'Q' || substr(d.fiscal_period, 7, 1)
               ELSE NULL
           END
       ) AS source_url,
       d.source_url_deep, d.source_accession,
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
  - `filings_search(query, ..., form_type: list[str] | None = None, include_low_confidence_supersession=False, limit=20) -> SearchResponse` — **form_type contract**: subset-of-family validation happens in `filings_search`'s own wrapper code (in `core/corpus/filings.py`) **before** delegation to `_search`. If `form_type` is None, resolve to the full filings family default `['10-K', '10-Q', '8-K']` and pass through. If caller passes a non-empty list, verify every element is in `FILINGS_FAMILY_FORM_TYPES = frozenset({'10-K', '10-Q', '8-K'})`; if not, raise `InvalidInputError` (imported from `core.corpus.types` per B3) with a message naming the offending form type and the valid family. `_search` itself (C1) does NOT do this validation — it receives already-resolved `form_types` and passes them to SQL as-is. This keeps the per-family constraint in the per-family wrapper; universal tool-boundary validation (query length, universe size, limit cap, path canonicalization per I13) stays in C4. Example: `filings_search(form_type=['10-K'])` narrows; `filings_search(form_type=['TRANSCRIPT'])` raises `InvalidInputError` with message "form_type 'TRANSCRIPT' not in filings family; use transcripts_search instead."
  - `filings_read(file_path, section=None, char_start=None, char_end=None) -> str` — opens the markdown file, slices by section or byte range.
  - `filings_source_excerpt(document_id=None, section=None, ticker=None, form_type=None, fiscal_period=None) -> str` — primary dispatch on `document_id`. Implementation:
    1. Look up the `documents` row by `document_id` to get `source_url`, `source_url_deep`, `source_accession`, `cik`, `form_type`.
    2. **Resolve the HTML URL** (accession-keyed, unambiguous per D13):
       - If `source_url_deep` is populated, use it.
       - Else fall back to constructing the primary-document URL from `source_accession` + `cik`: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}&dateb=&owner=include&count=40` won't do (landing page, not primary doc). The correct accession-keyed primary-document URL format is `https://www.sec.gov/Archives/edgar/data/{cik_no_leading_zeros}/{accession_nodashes}/{accession_with_dashes}-index.htm` — this is the accession index page, which in turn links to the primary HTML. Practical fetch: (a) fetch the accession index, (b) parse the primary document link, (c) follow it to the primary HTML. This is well-documented SEC URL structure; implement in a small helper `core/corpus/edgar_urls.py`.
       - **Last resort** (both source_url_deep null AND URL construction fails): return an `ExcerptUnavailableError` with the `document_id` and the reason. Agent/UI surfaces this rather than silently substituting non-verbatim content.
    3. Fetch the HTML via `httpx.get(url, headers={'User-Agent': 'hank-corpus/0.1 hank@hank.investments'})` — SEC requires a compliant User-Agent with contact info.
    4. **Parse for the named section** using Edgar_updater's `parse_filing_sections(html_content, filing_type)` at `Edgar_updater/edgar_parser/section_parser.py:242`. Return shape: dict with a `sections` field keyed by **canonical section IDs** like `item_7`, `item_1a`, `item_7a` (not by corpus header strings like `"Item 7. Management's Discussion and Analysis"`). Our `SearchHit.section` stores the corpus header string. Map corpus header → canonical ID via a small table mirrored from Edgar_updater's `_CANONICAL_HEADERS` inverse. New helper `core/corpus/section_map.py::corpus_header_to_edgar_id(section: str, form_type: str) -> str` does this lookup. Select the mapped ID from the parsed `sections` dict and return its verbatim text.
    5. **Form-type support:** `parse_filing_sections()` rejects `DEF 14A` (and other non-10-K/Q/8-K forms) at its entry per `section_parser.py:198`. **Phase 0 scope decision:** DEF 14A is **dropped from the canary** (see G1 update). Proxy statement support is deferred to Phase 1 via one of: (a) extending `parse_filing_sections()` in Edgar_updater to accept DEF 14A with its own section taxonomy, or (b) adding a crude-header-match fallback path in `core/corpus/edgar_urls.py` that parses raw HTML by `<h1>`/`<h2>` markers (works but less robust than the structured parser). Phase 0 `filings_source_excerpt` returns `ExcerptUnavailableError` for any non-supported form_type with a clear message pointing at Phase 1 plans.
    5. **Do NOT translate back to `(ticker, year, quarter)` and call `edgar-mcp.get_filing_sections`** — that violates D13 (tuple is ambiguous for amendments/same-day multi-8-Ks). The accession-keyed HTML URL is unambiguous.
    - Convenience overload: `(ticker, form_type, fiscal_period)` resolves via SQL (`SELECT document_id FROM documents WHERE ticker=? AND form_type=? AND fiscal_period=? AND is_superseded_by IS NULL`). If >1 row matches → raise `AmbiguousDocumentError` with candidate document_ids; caller retries with explicit document_id.
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
    1. Parse `fmp_transcripts:{ticker}_{fiscal_period}` to extract `(ticker, year, quarter)` — reversible canonical encoding. FMP's data model is 1:1 per (ticker, quarter); `document_id` IS the tuple.
    2. **AVOID the preview-mode trap.** `get_earnings_transcript(..., section='all', format='full', max_words=None)` with no `filter_speaker`/`filter_role` hits the preview branch at `transcripts.py:874-881` (truncates to 3 segments per section × 500 words each + sets a `hint` field). Verbatim retrieval requires one of: non-`'all'` section, OR a speaker/role filter, OR both.
    3. **Retrieval strategy:**
       - **If `speaker` is set:** single call `get_earnings_transcript(symbol=ticker, year=year, quarter=quarter, filter_speaker=speaker, section='all', format='full', max_words=None, output='inline')`. With `filter_speaker` populated, `speaker_filter_active=True` per `transcripts.py:881`, so preview mode is skipped. Returns `prepared_remarks` + `qa` lists filtered to that speaker's turns with full text.
       - **If `speaker` is None:** two parallel calls:
         - `get_earnings_transcript(..., section='prepared_remarks', format='full', max_words=None, output='inline')`
         - `get_earnings_transcript(..., section='qa', format='full', max_words=None, output='inline')`
         - Per `transcripts.py:818-880`, explicit `section` (not `'all'`) also skips preview mode. Each call returns the corresponding list with full text.
    4. **Error-status handling (before flattening):** `get_earnings_transcript()` returns `{'status': 'error', 'error': <message>}` for missing/invalid transcripts (per `transcripts.py:947,966`). **Check this first** — map `status='error'` to `raise ExcerptUnavailableError(document_id, reason=f"FMP error: {result.get('error', 'unknown FMP error')}")` (use `.get()` with default — malformed error payloads shouldn't `KeyError`). This happens before any data-shape handling. **Two-call path error precedence:** check prepared_remarks result first, then qa; if either fails, raise with the **first** error encountered (deterministic). Don't try to surface both errors — the first-failure signal is sufficient for agent recovery.
    5. **Response dict shape** (per `transcripts.py:997+` when `status='success'`):
       - `result['prepared_remarks']` — list of segment dicts: `{speaker, role, text, word_count}`
       - `result['qa']` — same shape
       - `result['qa_exchanges']` — list of analyst-Q + management-A pairs (derivative; ignored by source_excerpt)
       - `result['metadata']` — counts + hints (ignored)
    6. **Flattening for source_excerpt** (matches A6's locked transcript convention and §4.4 of arch doc):
       - Emit `"## PREPARED REMARKS"` parent header, then each prepared-remarks segment as `f"### SPEAKER: {segment['speaker']}" + (f" ({segment['role']})" if segment.get('role') else "") + f"\n\n{segment['text']}"`.
       - Emit `"## Q&A SESSION"` parent header, then each qa segment in the same format.
       - Skip the parent header if its section list is empty (e.g., when `speaker` filter matches only prepared-remarks turns, no `## Q&A SESSION` appears).
       - Role appended only when non-empty (matches `fmp/tools/transcripts.py:713` + `AI-excel-addin/api/research/document_service.py:236`).
       - Join elements with `"\n\n"`.
       - Return the combined string — structurally identical to what A6's `_build_transcript_body` emits into the corpus markdown, so `filings_read(transcript_file_path)` output and `transcripts_source_excerpt(document_id)` output are parallel in shape (one from corpus, one verbatim from source).
    7. **Empty-match contract (after error handling):** if the two-call path returns `prepared_remarks=[]` and `qa=[]`, OR the speaker-filter call returns empty lists, **raise `ExcerptUnavailableError(document_id, reason="no content for speaker filter" | "transcript has no content")`**. Never silently return an empty string — the agent must know the source is unavailable, not that the speaker said nothing.
    - Convenience overload `(ticker, fiscal_period)` constructs the document_id and dispatches. No ambiguity in FMP's 1-per-quarter model; `AmbiguousDocumentError` kept in signature for consistency with filings.
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
- New `mcp_tools/corpus/` package (per P2 resolution):
  - `mcp_tools/corpus/__init__.py` — empty file (package marker). Required because Python doesn't treat directories as packages without it.
  - `mcp_tools/corpus/filings.py` — `@mcp.tool()` decorators for `filings_search`, `filings_read`, `filings_source_excerpt`, `filings_list`. Each delegates to the core function in `core/corpus/filings.py` and marshals results (typed dataclasses → JSON-safe dicts; exceptions → structured error responses).
  - `mcp_tools/corpus/transcripts.py` — same pattern for `transcripts_*` tools.
- New `core/corpus/__init__.py` — empty package marker. (`core/` already exists as a package; `core/corpus/` is new and needs its own `__init__.py`.)
- `mcp_server.py` — import the new `mcp_tools/corpus/` modules to trigger tool registration at server startup. No direct tool-definition code here.
- `tests/test_tool_surface_sync.py` — extend the existing top-level `mcp_tools/*.py` scan (line 69 per P2) to recurse into `mcp_tools/corpus/` sub-package so the new tools are picked up by the surface-sync check.

**Depends on:** C2, C3, C4.

**Tests:**
- `tests/test_mcp_corpus_tools.py::test_tool_registered` — introspect mcp_server, confirm all 8 tool names present.
- `tests/test_mcp_corpus_tools.py::test_tool_dispatch_round_trip` — invoke each tool via MCP protocol, verify JSON-serializable response.
- `tests/test_tool_surface_sync.py` (updated) — confirm scan recurses into `mcp_tools/corpus/` and finds the 8 new tools.

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
- `tests/test_migration_cutover.py::test_app_config_flip_and_revert` — verify the app-level writer config actually changes at cutover and reverts at rollback. Specifically: patch an Edgar_updater output-path setter (or inspect whatever config var Edgar_updater reads for its target directory), verify it points at `CORPUS_ROOT/edgar/` after cutover and back at the legacy path after rollback. Filesystem cutover alone is insufficient — if the app still writes to the old path after we've archived it, the next ingestion silently breaks.

**Effort:** S.

### Block G — Canary dataset + acceptance

#### G1. Canary ticker list + filings selection (BLOCKING for G2)

**Goal:** Lock exactly which tickers + filings + edge-case filings make up the canary. **This is a research task that must complete before G2 starts.** G2's "ingest the canary" cannot execute against a proposal — it needs a finalized list of real SEC accessions.

**Lockdown acceptance criteria (all must be specified before G2):**
- **8-12 canonical tickers** with exact list (e.g., `['AAPL', 'MSFT', 'GOOG', 'META', 'BRK.B', 'JPM', 'XOM', 'TGT']` + one microcap — P5 to resolve).
- **For each ticker**: exact filing scope — most-recent 10-K accession + last 4 10-Q accessions + (for Q4's MSFT) last 2 earnings-call transcript fiscal periods.
- **Amendment pair (P6)**: one real 10-K/A accession + its original 10-K accession, both publicly available on EDGAR. The pair must be from a ticker that's ALSO in the primary canary list (so it tests the amendment path on a ticker we're ingesting anyway) OR an additional small ticker added specifically for this case.
- **Same-day multi-8-K case**: one ticker × one date with ≥2 8-K accessions filed on that day. Must be real SEC filings (not synthetic).
- **Microcap (P5)**: one real small-cap ticker (<$2B market cap) with a recent 10-K featuring spartan structure (few sections populated). Identifies brittleness in section-canonicalization assumptions.
- **Low-confidence synthetic amendment** for canary query 9 (Q9 in §7) — a hand-authored file mimicking an amendment but with `supersedes_confidence: 'low'`, pointing at one of the above real originals. This is the ONLY synthetic data in the canary; everything else is real SEC/FMP sources.

**Canary set (proposed — finalize during task execution):**
- **AAPL** — one recent 10-K + 4 recent 10-Qs + 2 earnings transcripts (last 2 quarters). Clean tech baseline.
- **MSFT** — same breadth. Includes the existing MSFT_10Q_2025 sample from both legacy locations (migration test).
- **GOOG** — share-class edge case (confirms SymbolResolver integration).
- **META** — required by canary query Q1 (§7); tech baseline with AI-related language.
- **BRK.B** — diversified conglomerate, unusual filing structure. **Filings only** (Berkshire doesn't hold traditional quarterly earnings calls; FMP transcript coverage is absent/sparse). No transcript sample requirement.
- **JPM** — financials taxonomy (Basel III / credit provisions language).
- **XOM** — XBRL-heavy, segment reporting.
- **TGT** — consumer retail baseline.
- **One microcap** — TBD (see P5), stress-test spartan filings (probably a recent IPO or small-cap with minimal sections).
- **Amendment edge case** — one real 10-K/A + its original (per E1).
- **Multi-8-K day** — one ticker with multiple 8-Ks on same day (common around earnings + material events).
- ~~DEF 14A~~ — **dropped from Phase 0 canary.** `Edgar_updater.parse_filing_sections()` rejects DEF 14A at entry (`section_parser.py:198`). Supporting proxy statements requires either extending that helper (scope creep for Phase 0) or implementing a crude-header-match fallback for proxies specifically. Both deferred to Phase 1. Phase 0 filings scope = 10-K, 10-Q, 8-K only. Canary query coverage adjusted accordingly (no query currently depends on DEF 14A).

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
- **Scale** — 500+ tickers, 20k+ files. Phase 0 tops out at ~60-80 documents (8-12 tickers × 1 10-K + 4 10-Qs each + 2-4 transcripts for MSFT + edge-case amendments/multi-8-K).
- **Concurrency stress** — Phase 0 tests cover 2-worker races; heavier concurrency in Phase 1.
- **Amendment linker** — manual only.
- **Cross-host / multi-node** — single-host Phase 0.

---

## 6. Sequencing & Dependencies

### 6.1 Critical path

```
A0 (LLM swap) ──────────────────────────────────────────────────────────────┐
                                                                             │
A1 (spec) ─→ A2 (frontmatter lib) ─→ A3 (hash) ─→ A4 (paths)                │
                        │                                                     │
                        └─→ A5 (section parsers) ─→ A6 (transcript body) ─┐  │
                                                  ─→ A7 (transcript no-op)  │  │
                                                                            │  │
B1 (schema) ─→ B3 (types) ─→ B2 (supersession SQL) ────────────────────────│  │
                                                                            │  │
                                              A8 (ingest orchestrator) ←───┴──┘
                                                            │
                                                            ↓
                    B4a (walker) ─→ B4b (doc sync) + B4c (fts sync) + B4d (supersession recompute) ─→ B4e (orchestrator)
                                                            │
C1 (search) ─→ C2 (filings_*) + C3 (transcripts_*) + C4 (I13 validation) ─→ C5 (MCP registration)
                                                            │
D1 (merge + prompt)                                         │
                                                            ↓
F1 (inventory) ─→ F2 (transform) ─→ F3 (cutover + rollback + app-config flip test)
                                                            │
E1 (manual amendment + low-confidence synthetic) ───────────┘
                                                            ↓
                                              G1 (canary dataset lockdown)
                                                            │
                                                            ↓
                                              G2 (ingest canary) ─→ G3 (run 9 queries) ─→ G4 (ship)
```

### 6.2 Parallelizable tracks

- **Track X (spec + body producers):** A1 → A2 → A3 → A4 → A5 → A6 → A7
- **Track Y (schema + primitives):** B1 → B3 → B2 (parallel with X from B1)
- **Track Z (LLM swap):** A0 (standalone, depends only on existing providers/ + Edgar_updater knowledge)
- **Track W (ingestion + reconciler):** A8 (after X+Y converge) → B4a → B4b/c/d in parallel → B4e
- **Track V (tool surface):** C1 + C4 (after B1+B3) → C2 + C3 parallel (need A8+B4 for end-to-end validation) → C5
- **Track U (migration):** F1 parallel with X; F2 needs X+Y complete + A8 (for ingest_raw); F3 comes last
- **Track T (canary):** E1 research-only, anytime before G2. G1/G2/G3/G4 sequential at the end.

### 6.3 Estimated total effort (rough)

| Block | Tasks | Effort |
|---|---|---|
| A (canonicalization) | A0–A8 = 9 tasks | L + S + S + S + M + S + M + S + M ≈ ~8-10 days (A0 grew M→L after R11/R12 scope expansion — vendoring + typed-exception plumbing + test updates + validator script) |
| B (schema + primitives + reconciler split) | B1, B2, B3, B4a–e = 8 tasks | S + S + S + M + S + S + S + M ≈ ~4-6 days |
| C (tool surface) | C1–C5 = 5 tasks | M + M + M + S + M ≈ ~5-6 days |
| D (composition + prompt) | D1 = 1 task | S ≈ <1 day |
| E (supersession manual authoring) | E1 = 1 task | S ≈ <1 day |
| F (migration) | F1–F3 = 3 tasks | S + M + S ≈ ~2-3 days |
| G (canary) | G1–G4 = 4 tasks | S + M + M + S ≈ ~2-3 days |
| **Total** | **31 tasks** | **~4-5 weeks serial; ~2-3 weeks with parallel tracks** |

Significantly more tasks than initial R1 draft (23 → 31) due to the R2/R3 decomposition of A2/B4/etc. Each task is smaller and more independently testable.

---

## 7. Canary Acceptance — Per-Query Spec

Each of the 9 canary queries from §13.6 of the arch doc maps to a concrete acceptance criterion in Phase 0.

### Q1. "What AI investments are AAPL, MSFT, GOOG, META discussing?"

- `filings_search(query='"AI capital" OR "AI infrastructure" OR "AI investment"', universe=['AAPL','MSFT','GOOG','META'], form_type=['10-K'])`
- **Pass:** returns ≥3 hits across ≥3 different tickers; every hit has populated `file_path`, `source_url`, `section`, `snippet`, `rank`.

### Q2. "How have MSFT risk factors evolved across the last 4 quarters?"

- `filings_search(query='risk', universe=['MSFT'], form_type=['10-K','10-Q'], section='Item 1A. Risk Factors')` — or equivalent with post-filter on section.
- **Pass:** returns hits with all from `Item 1A` sections; agent can diff content between periods.
- **Ordering note:** `filings_search` returns BM25-ranked hits (smaller rank = more relevant). Chronological ordering for the diff-across-periods narrative is the agent's job: sort `response.hits` by `filing_date DESC` client-side after receiving the response. Q2 acceptance does NOT require the tool to return filing_date-ordered results; the tool always returns rank-ordered. The architecture keeps rank as primary ordering (C1); date-ordering is an agent-side concern.

### Q3. "AAPL FY2025 10-K on services revenue growth (Item 7) AND related risks (Item 1A)"

- Two queries: `filings_search(query='services revenue', universe=['AAPL'], form_type=['10-K'])` + `filings_search(query='services', universe=['AAPL'], form_type=['10-K'])` with section filter on Item 1A.
- **Pass:** both return hits from the same `document_id`; `filings_read(file_path, section='Item 7')` and `filings_read(file_path, section='Item 1A')` both succeed and return section-scoped content.

### Q4. "Where has MSFT discussed capital allocation — filings or transcripts?"

- **Ticker locked: MSFT.** Rationale: guaranteed FMP quarterly transcript coverage (confirmed present in our research samples — `AAPL_1Q25_transcript_0f8bb74b.md` + `AAPL_4Q25_transcript_d3b65636.md` exist; MSFT has the same coverage pattern). Capital-allocation language is present in both MSFT's recent 10-Ks/Qs (MD&A) and earnings calls (CFO prepared remarks + analyst Q&A).
- Parallel calls:
  - `filings_search(query='capital allocation', universe=['MSFT'], limit=20)`
  - `transcripts_search(query='capital allocation', universe=['MSFT'], limit=20)`
- Merge: `sorted(f.hits + t.hits, key=lambda h: h.rank)[:30]`
- **Pass (all required, not conditional):**
  - Merged list has ≥1 hit from **each** source (filings AND transcripts — the cross-source merge path IS exercised).
  - Every hit's `rank` is ascending (smaller-is-better).
  - Agent sees the `source` field distinguishing filings (`'edgar'`) from transcripts (`'fmp_transcripts'`).
  - `SearchResponse.total_matches` + `SearchResponse.applied_filters` populated on both parallel responses.

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
   **Follow-up task for C5**: the existing `tests/test_tool_surface_sync.py:69` scans only top-level `mcp_tools/*.py` files — must be extended to recurse into `mcp_tools/corpus/` (and future sub-packages). Add this to C5's test updates.

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
