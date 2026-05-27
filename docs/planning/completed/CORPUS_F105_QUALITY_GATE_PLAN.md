# F105 — Corpus Read-Path Quality Gate

**Status:** APPROVED — Codex v2 review returned PASS (2026-05-19). Two non-blocking implementation notes folded into §11.

**Author:** Henry / Claude

**Date opened:** 2026-05-19

**TODO entry:** `docs/TODO.md` F105 (P2)

**Source audit:** `docs/corpus/CACHE_GAPS.md` C5

---

## 1. Problem

`documents.extraction_status` is a producer-emitted field with values
`{'complete', 'partial', 'failed', 'orphaned'}` (`ALLOWED_EXTRACTION_STATUSES`
in `core/corpus/frontmatter.py:30`). The column is declared `TEXT DEFAULT
'complete'` in `core/corpus/schema.sql:19`. Ingest stores the value
verbatim from the producer's frontmatter (`core/corpus/ingest.py:47-164`).

Today **no read path filters on it**:

- `core/corpus/search.py::_build_where_clause` has no `extraction_status` clause
- `core/corpus/filings.py::filings_list` SELECT has no `extraction_status` filter
- `core/corpus/filings.py::filings_source_excerpt` tuple-lookup query
  (`core/corpus/filings.py:472-484`) gates only on `is_superseded_by IS NULL`
- `core/corpus/transcripts.py::transcripts_list` has no `extraction_status` filter
- `mcp_tools/corpus/{filings,transcripts}.py` expose no flag for this

**Result:** When the producer marks a row `'failed'` or `'orphaned'`, agent-
facing search/list APIs return the bad row indistinguishably from a healthy
parse. If a producer regression slips past upstream validators, garbage
propagates into downstream features (research-mcp, Hank agent, MCP tools).

**Mirror pattern that already works:** `is_superseded` is default-filtered at
`core/corpus/search.py:391` and `core/corpus/filings.py:480`, with an
opt-in `include_superseded: bool = False` flag plumbed through MCP →
core. We replicate that pattern.

## 2. Goal

Default-hide low-quality documents from read APIs; provide an opt-in flag
for callers who explicitly want them (diagnostics, ingest investigations).
Surface the `extraction_status` value on every returned row so callers can
see when matches exist that were filtered out.

## 3. Scope decisions

### 3.1 What counts as "high quality" (allowlist, not blacklist)

The default filter is a **visible-status allowlist**, not a blacklist:

```sql
COALESCE(d.extraction_status, 'complete') IN ('complete', 'partial')
```

Rationale (Codex v1 review): the schema has no `CHECK` constraint on
`extraction_status` (`core/corpus/schema.sql:19`), and `frontmatter.py`
does not require the column to be set. If the producer ever emits a
new value (`'unverified'`, `'pending'`, anything), a blacklist would
silently show it; an allowlist fails closed and hides it until the
consumer explicitly opts in.

- `'complete'` — visible.
- `'partial'` — visible. Some sections recovered, others lost; still
  useful evidence. Callers see `extraction_status='partial'` on each
  hit so they can filter client-side if they want stricter quality.
- `'failed'` — hidden by default. Upstream parser failure.
- `'orphaned'` — hidden by default. Row exists without canonical file
  (per `tests/test_migration_transform.py:368`).
- Any unknown/new value — **hidden by default** (fail-closed).
- NULL — treated as `'complete'` via `COALESCE` for legacy rows
  pre-dating the column migration.

The allowlist is centralized as a module-level tuple
`_VISIBLE_EXTRACTION_STATUSES = ('complete', 'partial')` in
`core/corpus/search.py`.

### 3.2 `parser_result_status` is OUT OF SCOPE

`parser_result_status` is a free-text producer-internal field
(`core/corpus/schema.sql:33`, no CHECK constraint, observed values
`'success'` and `'complete'` in tests). It carries upstream pipeline
state, not a consumer-facing health verdict. We do **not** gate on it
in this change. Follow-up: file a prod audit task to enumerate observed
values, then decide separately. Out-of-scope here keeps blast radius
small.

### 3.3 NULL handling for legacy rows

Rows ingested before any extraction_status migration may have
`extraction_status IS NULL`. Schema default is `'complete'`, but
historical rows predating the column would be NULL. Treat NULL as
`'complete'` in filter SQL via `COALESCE` (see §3.1 SQL form).
Matches the existing `COALESCE(d.fiscal_period, '')` pattern in
`core/corpus/search.py` and `core/corpus/filings.py`.

### 3.4 Public flag name

`include_low_quality: bool = False` — mirrors `include_superseded` shape.

Rejected alternatives:
- `include_failed` — too narrow; reads as gating only `failed`.
- `quality_filter='strict'` enum — over-engineered for a 2-state knob.

### 3.5 `filings_source_excerpt` tuple-lookup path

`core/corpus/filings.py:472-497` resolves `(ticker, form_type,
fiscal_period)` to a single row, then dispatches to the EDGAR API. If
the row's `extraction_status` is `'failed'` or `'orphaned'`, the API
fetch is almost certainly meaningless — there's no canonical content to
verify against.

**Decision:** Add the same `COALESCE` filter to the tuple-lookup SQL.
`document_id`-lookup path (line 456-460) stays **unfiltered** — passing
an explicit ID is consent. No new flag exposed at the MCP layer for
`source_excerpt` (the tuple-lookup is itself a convenience shortcut;
explicit ID lookup remains the escape hatch).

### 3.6 What the response envelope surfaces

- **`SearchHit.extraction_status: str`** — new field, populated from
  `COALESCE(d.extraction_status, 'complete')`. Always present on every
  hit.
- **`DocumentMetadata.extraction_status: str`** — same, for list APIs.
- **`SearchResponse.has_low_quality_matches: bool`** — true when matches
  exist that would have been returned with `include_low_quality=True`
  but are hidden by the default filter. Mirrors
  `has_superseded_matches` (computed via a parallel variant-count
  query when the filter is on).

## 4. Files changed

### 4.1 `core/corpus/search.py`

- Add `_VISIBLE_EXTRACTION_STATUSES = ('complete', 'partial')` module
  constant.
- Add `_QUALITY_FILTER_SQL` helper string:
  `"COALESCE(d.extraction_status, 'complete') IN ('complete', 'partial')"`.
- `_build_where_clause()`:
  - Add `include_low_quality: bool` kwarg.
  - When `not include_low_quality`, append the allowlist clause.
- `_run_match_queries()`:
  - Add `include_low_quality: bool` + `low_quality_variant_clauses` /
    `low_quality_variant_params` kwargs (mirrors superseded variant).
  - Return tuple grows to include `low_quality_count`.
  - SELECT adds `COALESCE(d.extraction_status, 'complete') AS extraction_status`.
- `_search()`:
  - Add `include_low_quality: bool = False` kwarg.
  - Build the **low-quality variant** where-clause by re-calling
    `_build_where_clause` with `include_low_quality=True` while
    **preserving the current `include_superseded` value**. This is the
    only orthogonality-critical detail: the low-quality variant lifts
    only the quality filter; it must not also lift the superseded
    filter (and vice versa for the existing superseded variant, which
    must preserve the current quality filter). Tests in §5.1 cover the
    cross-contamination case.
  - Compute `has_low_quality_matches = low_quality_count > total_matches`.
  - Add `extraction_status` to `SearchHit` construction.
  - Add `'include_low_quality': include_low_quality` to `applied_filters`.

### 4.2 `core/corpus/types.py`

All new fields are **appended at the end** of each dataclass — even
though our audit confirmed every in-repo construction site is
keyword-only (Codex v1 review: `SearchHit(` at `search.py:311`,
`DocumentMetadata(` at `filings.py:303` + `transcripts.py:266`,
`SearchResponse(` at `search.py:224`), appending is defensive against
any external positional caller and matches Python dataclass best
practice for additive fields with defaults.

- `SearchHit`: append `extraction_status: str = 'complete'` (after
  `scale_hint`).
- `SearchResponse`: append `has_low_quality_matches: bool = False`
  (after `has_low_confidence_supersession`).
- `DocumentMetadata`: append `extraction_status: str = 'complete'`
  (after `source_url`).

### 4.3 `core/corpus/filings.py`

- `filings_search()`: add `include_low_quality: bool = False` param;
  pass through to `_search()`.
- `filings_list()`: add `include_low_quality: bool = False` param; add
  the quality-filter clause to its WHERE when `not include_low_quality`;
  add `COALESCE(d.extraction_status, 'complete') AS extraction_status`
  to the SELECT; populate `DocumentMetadata.extraction_status` on the
  return.
- `filings_source_excerpt()` tuple-lookup query
  (`core/corpus/filings.py:472-484`): add
  `AND COALESCE(extraction_status, 'complete') IN ('complete', 'partial')`
  alongside the existing `is_superseded_by IS NULL` clause. This means
  the tuple lookup will prefer a `'complete'`-status row over a
  `'failed'` sibling for the same `(ticker, form_type, fiscal_period)`
  rather than raising ambiguity — see test case in §5.2. No new
  argument exposed at the MCP layer; explicit `document_id` lookup
  remains the escape hatch.

### 4.4 `core/corpus/transcripts.py`

- `transcripts_search()`: add `include_low_quality: bool = False` param;
  pass through to `_search()`.
- `transcripts_list()`: add `include_low_quality: bool = False` param;
  add the quality-filter clause + SELECT update + `DocumentMetadata`
  population (same shape as `filings_list`).

### 4.5 `mcp_tools/corpus/filings.py`

- `filings_search`: add `include_low_quality: bool = False` arg; pass
  through. Update docstring `Args:` block to add:
  ```
  include_low_quality: Set `True` to include documents the producer
      marked with `extraction_status` outside the visible allowlist
      (`'complete'` / `'partial'`). The default hides `'failed'`,
      `'orphaned'`, and any unknown future status value.
  ```
- `filings_list`: add same arg + docstring. The `corpus_inventory`
  payload also surfaces `hidden_low_quality_document_count` — see §4.7.
- `_search_response_to_payload`: add `'has_low_quality_matches'` and
  `'extraction_status'` to the per-hit payload (the latter falls out
  naturally from `asdict(hit)`).

### 4.6 `mcp_tools/corpus/transcripts.py`

- `transcripts_search`: add `include_low_quality` arg + docstring.
- `transcripts_list`: add same arg + docstring.
- `_search_response_to_payload`: add `'has_low_quality_matches'`.

### 4.7 `mcp_tools/corpus/filings.py::corpus_inventory`

- Pass through `include_low_quality` (default `False`) to
  `filings_list`.
- Add `'hidden_low_quality_document_count'` to `coverage_summary`.
  **Compute correctly** (Codex v1 bug catch): the default `filings_list`
  result hides low-quality rows, so the count cannot be derived from
  it. Compute via a second `filings_list(include_low_quality=True)`
  call and subtract, only when the caller is using the default filter
  (`include_low_quality=False`). When the caller already opted in to
  see low-quality rows, set the count to `0` (nothing was hidden).
  The name `hidden_low_quality_document_count` is deliberate to make
  it self-documenting that this counts what was filtered out, not
  total low-quality docs in the corpus.

## 5. Tests

### 5.1 `tests/test_corpus_search.py`

New tests:
- `test_search_default_hides_failed_extraction_status`
- `test_search_default_hides_orphaned_extraction_status`
- `test_search_default_keeps_partial_extraction_status`
- `test_search_default_hides_unknown_extraction_status` (allowlist
  fail-closed — Codex gap)
- `test_search_include_low_quality_surfaces_failed_orphaned_and_unknown`
- `test_search_null_extraction_status_treated_as_complete`
- `test_has_low_quality_matches_flag_set_when_filter_hides_results`
- `test_has_low_quality_matches_set_on_or_fallback_path` (the
  OR-rewrite fallback in `_search()` lines 284-301 — Codex gap)
- `test_search_hit_carries_extraction_status_field`
- `test_supersession_and_quality_filters_are_orthogonal` (Codex gap):
  fixture has 4 rows covering the 2×2 of `{superseded, not-superseded}
  × {complete, failed}`; assert default returns only the
  not-superseded/complete row; assert `include_superseded=True` adds
  the superseded/complete row (NOT the failed one); assert
  `include_low_quality=True` adds the not-superseded/failed row (NOT
  the superseded one); assert both flags returns all four.

### 5.2 `tests/test_corpus_ingest.py` / new module

- `test_filings_list_default_hides_failed`
- `test_filings_list_include_low_quality`
- `test_transcripts_list_default_hides_failed`
- `test_filings_source_excerpt_tuple_lookup_excludes_failed_when_unique`
  (single `'failed'` row matching the tuple — assert
  `ExcerptUnavailableError`)
- `test_filings_source_excerpt_tuple_lookup_prefers_complete_over_failed`
  (Codex gap): two rows for the same `(ticker, form_type, fiscal_period)`
  — one `'complete'`, one `'failed'`. The allowlist filter must return
  the complete row rather than raising `AmbiguousDocumentError`.
- `test_filings_source_excerpt_document_id_lookup_returns_failed_row`
  (the id-lookup escape hatch — caller passed explicit ID, row is
  returned to the downstream verifier which then raises its own error
  based on accession verification)

### 5.3 `tests/test_mcp_corpus_tools.py` (or equivalent)

- MCP schema/signature smoke test (Codex gap): use `inspect.signature`
  to assert that `include_low_quality` appears as a kwarg on
  `mcp_tools.corpus.filings.filings_search`, `filings_list`,
  `corpus_inventory`, `mcp_tools.corpus.transcripts.transcripts_search`,
  and `transcripts_list`.
- Smoke test that `corpus_inventory` payload includes `extraction_status`
  per document and `hidden_low_quality_document_count` in
  `coverage_summary`.
- Smoke test that `corpus_inventory` `hidden_low_quality_document_count`
  is `0` when called with `include_low_quality=True` (Codex bug catch).

### 5.4 Fixture updates

`tests/_corpus_helpers.py` and any test fixtures that build `documents`
rows directly need to set `extraction_status='complete'` explicitly
(some tests already do — `test_corpus_ingest_accession.py:204,287`,
`test_corpus_reingest_sweeper.py:191`, `test_frontmatter.py:34`).
Audit for fixtures missing the field; rely on `COALESCE` default for
the rest.

## 6. Backward compatibility

- **Schema:** no change. Column already exists with
  `DEFAULT 'complete'`.
- **Public API:** new fields on `SearchHit` / `DocumentMetadata` /
  `SearchResponse` are additive with defaults; `asdict()` consumers
  (`mcp_tools/corpus/*.py:374-380`) get the field for free in the
  payload — additive at the JSON wire level too.
- **MCP tool surface:** new `include_low_quality=False` kwarg is a
  **deliberate behavior change** — today no filter exists; after this
  change, default callers will start hiding `'failed'`, `'orphaned'`,
  and any unknown `extraction_status` values. This is the desired fix.
  Document as a release-note item.
- **Existing tests:** Tests that rely on the absence of an
  `extraction_status` filter on `documents` (none observed in current
  read-path tests) need to either set the field on their fixtures or
  pass `include_low_quality=True`. Audit during implementation.

## 7. Risks

1. **Hiding rows that are actually fine.** If the producer misuses
   `'failed'` / `'orphaned'` / a new status, we hide good content. The
   allowlist makes this stricter (any unknown value hides). Mitigation:
   `'partial'` stays visible by default; `extraction_status` is
   surfaced on every hit so callers can see the labels; `include_low_quality`
   escape hatch always available.
2. **Variant-count cost on hot search path.** The superseded variant
   already does a parallel COUNT(*) per query. Adding the low-quality
   variant doubles that to two extra counts. Acceptable — both run
   against the same FTS index, sub-millisecond at corpus size.
   Mitigation: if the cost shows up in perf logs, fold both variants
   into a single conditional aggregation in v2.
3. **MCP wire schema change.** Adding fields is backward-compatible for
   JSON consumers that ignore unknown fields (which is the contract).
   No version bump needed.
4. **`SearchHit` default-arg position.** `SearchHit` is a `frozen=True
   dataclass`. Adding a non-default field would break positional
   construction; adding a default field is fine. Confirm test fixtures
   don't construct positionally — grep shows they use kwargs.

## 8. Out of scope (explicit)

- `parser_result_status` gating — see §3.2.
- Adding a `documents.quality_score` sidecar column.
- Health-snapshot trend tables for extraction_status — F108 territory.
- Surfacing `extraction_status` in `corpus_health_report.py` output.
  Follow-up if useful.

## 9. Rollout

Single PR, no flag wrapping (the default-filter IS the change).

1. Implement per §4.
2. Run `pytest tests/test_corpus_search.py tests/test_corpus_ingest.py
   tests/test_mcp_corpus_tools.py -x`.
3. Spot-check on a local dev corpus: `python -c "from
   mcp_tools.corpus.filings import filings_search; ..."` — confirm
   default behavior excludes non-allowlist statuses and surfaces
   `extraction_status` on every hit.
4. Commit on `main` (per `feedback_commit_to_main_default`).
5. Update `docs/corpus/CACHE_GAPS.md` C5 to `[RESOLVED]`.
6. Mark F105 SHIPPED in `docs/TODO.md`; move to TODO_COMPLETED.

## 10. Open questions — resolved in Codex v1 review

1. **Hide `partial` by default?** No. Keep visible; surface
   `extraction_status` on hits so callers can client-side filter.
2. **MCP flag for `filings_source_excerpt` tuple lookup?** No.
   Explicit `document_id` lookup is sufficient escape hatch.
3. **`corpus_inventory` low-quality count?** Yes, but named
   `hidden_low_quality_document_count` and computed from a second
   `include_low_quality=True` query, not from the default result. See
   §4.7.
4. **Two extra variant COUNT(*) queries per search call?** No
   performance concern at current corpus scale. Both run against the
   same FTS index, sub-millisecond. Re-evaluate only if perf logs
   surface it.

## 11. Implementation notes (Codex v2 review)

1. **Unknown-status fixtures must bypass frontmatter validation.**
   `core/corpus/frontmatter.py:374-379` raises `FrontmatterValidationError`
   for any `extraction_status` not in `ALLOWED_EXTRACTION_STATUSES =
   {'complete', 'partial', 'failed', 'orphaned'}`. So the
   `test_search_default_hides_unknown_extraction_status` and the
   `test_search_include_low_quality_surfaces_failed_orphaned_and_unknown`
   tests cannot ingest a row with status `'unverified'` through the
   normal ingest path — they must INSERT directly into the
   `documents` table after a normal ingest, or use a fixture helper
   that bypasses the validator. Recommended: extend
   `tests/_corpus_helpers.py` with an `insert_document_row(...)` that
   takes an explicit `extraction_status` kwarg and writes raw SQL.
2. **`_QUALITY_FILTER_SQL` helper must be alias-safe.** The same SQL
   fragment is consumed by `_build_where_clause()` (alias `d.extraction_status`)
   and by `filings_source_excerpt`'s tuple-lookup query (unaliased
   `extraction_status`, see `core/corpus/filings.py:472-484`). Either
   (a) parameterize the helper to take an alias, e.g.
   `_quality_filter_sql(alias: str = 'd') -> str`; or (b) duplicate
   the COALESCE clause inline in the two call sites. Option (a) keeps
   the allowlist value single-sourced and is the recommended path.
