# F156 Filing Identity Cutover Plan

**Status:** Review PASS 2026-05-30 - ready for implementation planning
**Date:** 2026-05-30
**Owner:** Research Workspace / Filing Reader / Corpus
**Primary repos:** `/Users/henrychien/Documents/Jupyter/risk_module`, `/Users/henrychien/Documents/Jupyter/AI-excel-addin`, `/Users/henrychien/Documents/Jupyter/Edgar_updater`
**Related plans:** `F156_READER_IMPLEMENTATION_PLAN.md`, `F156_READER_SYSTEM_ARCHITECTURE.md`, `F156_RESEARCH_WORKSPACE_COMPLETION_PLAN.md`
**Triggering issue:** parser spacing repair exposed stale filing markdown caches and a remaining legacy filing `source_id` identity path.

## Executive Summary

The source HTML reader is now the visual canonical filing surface, and the corpus DB already keys filings by `document_id = edgar:<accession>`. But the UI, local reader artifacts, AI-excel research artifacts, and some API routes still carry the old content-hash filing identifier in `source_id`, for example:

```text
MSFT_10Q_2025_6f90a2a7
```

That identifier was useful when document reads were backed by immutable content-hash markdown files. It is no longer the correct user-facing or evidence-facing filing identity. The correct long-term contract is:

```text
filing identity = document_id = edgar:<accession>
```

The cutover should be a full value cutover away from legacy hash IDs while respecting package boundaries:

- `risk_module` should not import Edgar parser internals.
- `AI-excel-addin` should act as the research gateway/document facade.
- `Edgar_updater` should own parsing, filing document lookup, cache schema, and invalidation metadata.
- The corpus is a regenerated materialization keyed by stable `document_id`, not the source of filing identity.

This plan separates two concerns that are currently intertwined:

1. **Parser/corpus cache correctness:** fix stale markdown produced before the span-spacing parser fix.
2. **Filing identity cutover:** stop using legacy content-hash IDs in UI routes, reader artifacts, annotations, thesis source records, and agent document contexts.

## Naming Clarification

This plan uses the terms precisely:

- **Legacy filing source ID:** content-hash ID such as `MSFT_10Q_2025_6f90a2a7`. This should disappear from active filing identity paths.
- **Canonical filing document ID:** accession-backed ID such as `edgar:0000950170-25-010491`. This is the durable filing identity.
- **Generic source record ID:** thesis citation IDs such as `src_1`, `src_2`. These remain stable citation handles and are not being removed.
- **Generic `source_id` field:** some schemas use this name for all source types. For filings, the value should become the canonical `edgar:<accession>` ID during the value cutover. A later schema cleanup can rename filing-specific fields to `document_id`.
- **Transcript identity:** transcript source IDs already use stable document IDs like `fmp_transcripts:MSFT_2025-Q2`; transcript behavior is not part of the legacy filing-hash cutover except where shared code must keep working.

## Verified Baseline

### Parser and corpus state

- The Edgar parser span-spacing fix is committed in `Edgar_updater` at `8e28e83 Preserve filing heading span spacing`.
- Forced local reparse of MSFT 2Q25 now emits readable headings:
  - `BALANCE SHEETS`
  - `CASH FLOWS STATEMENTS`
- Stale corpus markdown still exists locally:
  - `risk_module/data/filings/edgar/MSFT/10-Q_2025-Q2_a411522d.md`
  - examples: `BALANCESHEETS`, `CASH FLOWSSTATEMENTS`
- Local invalidation predicate matched 42 stale filing corpus docs:
  - `form_type IN ('10-K', '10-Q') AND text LIKE '%BALANCESHEETS%'`
- `risk_module` corpus DB filing rows are already keyed correctly:
  - `documents.document_id` has `edgar:*` for all local EDGAR filings checked.

### UI and reader artifact state

- The frontend normalizes API `source_id` into `DocumentTabData.sourceId` in `frontend/packages/connectors/src/features/external/hooks/useResearchDocuments.ts`.
- The source HTML reader builds filing quote anchors with `sourceId: sourceHtml.sourceId` in `frontend/packages/ui/src/components/research/readerBridge/index.ts`.
- `services/reader_artifacts.py` requires filing anchors to include both `source_id` and `document_id`.
- Reader artifact source identity hashes include `source_id`, `endpoint_or_filing_id`, and key fields.
- Local `user_data/research_reader_artifacts.json` has 19 active artifacts:
  - 16 active filing artifacts still use `source_id = MSFT_10Q_2025_6f90a2a7`.
  - Those same 16 already include `document_id = edgar:0000950170-25-010491`.
  - 3 transcript artifacts use stable transcript IDs and should remain unchanged.

### AI-excel research artifact state

Local AI-excel research DB scan found legacy filing IDs in `data/users/1/research.db`:

- 1 annotation row with `source_type='filing'` and legacy `source_id`.
- 2 thesis source records with legacy `source_id` and `endpoint_or_filing_id = edgar:0000950170-25-010491`.
- 3 research message metadata document contexts with legacy `document_context.source_id`.

No matching local rows were found in `henry`, `hc@henrychien.com`, or `alice` research DBs, but production must be audited separately.

## Problem

The reader system now has two filing identities in circulation:

```text
legacy source_id         = MSFT_10Q_2025_6f90a2a7
canonical document_id    = edgar:0000950170-25-010491
```

This creates four classes of risk:

1. **Stale document reads:** old content-hash IDs can point at stale markdown materializations even after parser fixes.
2. **Evidence hash drift:** reader artifact and thesis source identity hashes include `source_id`, so changing identity after evidence is registered can orphan lookup paths unless migrated carefully.
3. **Route and query fragmentation:** the UI route and React Query keys use `sourceId`, so the same filing can be opened under multiple IDs.
4. **Cross-package ambiguity:** `risk_module`, `AI-excel-addin`, and `Edgar_updater` each see slightly different filing identity concepts.

## Root Cause

The original document reader used content-hash filing IDs as the primary read key. Later, the corpus and source HTML reader moved to stable accession-backed identities but preserved the old `source_id` field for compatibility.

The compatibility field became load-bearing in:

- reader routes: `#research/:ticker/reader/:source_type/:source_id`
- document API calls: `/api/research/content/documents?source_id=...`
- source HTML URLs: `/documents/source-html?source_id=...&document_id=...`
- reader artifact anchors
- annotation rows
- thesis source records and identity hashes
- agent document context metadata

The system now treats `document_id` as canonical in some places and `source_id` as canonical in others.

## Target Architecture

### Filing identity contract

For filings:

```text
canonical_id = document_id = edgar:<accession>
```

Rules:

- The UI opens filings by `documentId`, not legacy content-hash ID.
- If a generic schema requires `source_id`, filing values must equal the canonical `document_id`.
- `source_id` values matching content-hash filing IDs are migration input only, not a valid active runtime identity.
- `corpus_content_hash` remains a materialization/version field, not an identity field.
- `source_html_hash` remains a render-materialization field, not the filing identity.
- `src_N` source refs remain stable citation handles and are not replaced by document IDs.

### Package boundaries

`Edgar_updater` owns:

- parser fixes
- parser/cache schema versions
- invalidation feed
- canonical filing document lookup by accession/document ID
- document payload provenance

`AI-excel-addin` owns:

- research document facade
- thesis/handoff source registry
- research DB migrations for annotations, theses, handoffs, messages
- source HTML gateway routes

`risk_module` owns:

- frontend reader state and route shape
- local reader artifact store
- corpus DB/materialized markdown cache
- corpus rebuild/promote workflow
- proxying research content without importing parser internals

## Implementation Strategy

The safe order is:

1. Finish and deploy parser/cache invalidation.
2. Add canonical `edgar:<accession>` document read support through Edgar and the AI-excel gateway, including legacy-alias canonicalization.
3. Rebuild corpus materializations and mapping records against the fixed parser.
4. Deploy runtime canonicalization shims that stop new legacy writes and normalize old stored anchors on read/open.
5. Migrate AI-excel research DB source records once, after corpus hashes are stable.
6. Migrate risk_module reader artifacts after thesis/source-record excerpt IDs are stable.
7. Remove legacy compatibility after clean audits.

This avoids rewriting source/evidence identity hashes before the corpus rebuild changes `corpus_content_hash`.

## Phase 0 - Preflight and Snapshots

Goal: make the current state measurable before changing identities.

Tasks:

- Add or run a local audit that reports legacy filing IDs across the known active stores:
  - `risk_module/user_data/research_reader_artifacts.json`
  - AI-excel `annotations.source_id`
  - AI-excel `theses.artifact_json`
  - AI-excel `research_handoffs.artifact`
  - AI-excel `research_messages.metadata`
  - AI-excel `research_messages.content` if reader actions are embedded
- Add a production-safe SQLite text audit for AI-excel research DBs:
  - inspect every table and every `TEXT`/JSON-like column with a legacy filing-ID regex.
  - classify each hit as `rewrite`, `archive_only_allowed`, or `unresolved`.
  - require explicit handling for known additional surfaces: `research_files.source_ref`, `research_files.idea_provenance`, `research_file_history.changes`, `thesis_links.link_json`, `thesis_scorecards.scorecard_json`, `thesis_decisions_log.entry_json`, `model_build_contexts.mbc_json`, `model_insights.insights_json`, and `price_targets.payload_json`.
  - active runtime state should be `rewrite`; append-only historical/audit state may be `archive_only_allowed` only when it is not used to seed new state, build document context, or register evidence.
- Snapshot all mutable stores before migration:
  - `risk_module/user_data/research_reader_artifacts.json`
  - each AI-excel `research.db`
  - `risk_module/data/filings.db`
  - `risk_module/data/filings/`
- Save audit output as JSONL with:
  - store path
  - table/path
  - row/artifact ID
  - legacy source ID
  - canonical document ID when discoverable
  - rewrite status

Acceptance:

- We can list every active legacy filing ID before migration.
- Every legacy hit is classified as `rewrite`, `archive_only_allowed`, or `unresolved`.
- Every rewrite candidate has a canonical `edgar:<accession>` target.
- No unresolved hit is silently skipped in live mode.

## Phase 1 - Edgar and Gateway Canonical Document Reads

Goal: make `edgar:<accession>` a first-class filing read key before changing the UI.

### Canonical Filing API Contract

During this cutover, `source_id` remains a required schema field because current API schemas and frontend normalization expect it. The value changes; the field does not disappear yet.

For filing document responses:

```text
source_id = document_id = edgar:<accession>
```

Dropping or renaming `source_id` is a later schema-v3 cleanup task. It is explicitly out of scope for this value cutover.

Canonical filing document payloads must include enough metadata for the source HTML reader without parsing legacy hash IDs or local markdown filenames:

- identity:
  - `source_id = edgar:<accession>`
  - `document_id = edgar:<accession>`
  - `source_type = filing`
  - `source_accession` / `accession`
- filing metadata:
  - `ticker`
  - `cik`
  - `form_type`
  - `fiscal_period` and/or enough fiscal year/quarter metadata for existing UI display
  - `filing_date` and `period_end` when available
- source HTML metadata:
  - `primary_document_url`
  - `source_url`
  - `source_url_deep`
- corpus/parser metadata:
  - `content_hash` or `corpus_content_hash`
  - `parser_version`
  - `parser_schema_version`
  - `producer_deployment_id` when available
- content:
  - `full_text`
  - `sections`
  - `available_sections`
  - `segments` only for transcript responses
- render surface:
  - `render_surfaces.corpus_text.document_id = edgar:<accession>`
  - `render_surfaces.corpus_text.corpus_content_hash`
  - `render_surfaces.source_html.source_id = edgar:<accession>`
  - `render_surfaces.source_html.document_id = edgar:<accession>`
  - `render_surfaces.source_html.accession`
  - `render_surfaces.source_html.primary_document_url`
  - `render_surfaces.source_html.corpus_content_hash`
  - `render_surfaces.source_html.sanitizer_version`

If AI-excel source HTML resolution continues to compute identity locally, it must use these canonical fields from the Edgar document payload. If Edgar emits equivalent source HTML render metadata directly, AI-excel may trust and forward that metadata after validating `document_id`, `accession`, and `corpus_content_hash`.

Edgar-side requirements:

- `GET /api/documents/{id}` must accept `id = edgar:<accession>` for filings.
- Returned document payload must include:
  - `source_id = edgar:<accession>`
  - `document_id = edgar:<accession>`
  - `ticker`, `cik`, `form_type`, and fiscal-period metadata
  - `source_accession`
  - `primary_document_url`
  - `content_hash` / `corpus_content_hash`
  - parser provenance fields
  - render surfaces metadata needed by the source HTML reader
- Legacy content-hash ID reads may remain temporarily as a compatibility alias, but must not be emitted as canonical identity.

AI-excel gateway requirements:

- `DocumentClient.get_document(...)` and `RemoteDocumentService` must work with `edgar:<accession>`.
- `/api/research/documents` should accept canonical filing IDs.
- `/api/research/documents/source-html` and `/metadata` should work when `source_id = document_id = edgar:<accession>`.
- Source HTML identity resolution must continue to reject mismatched `document_id`.
- `RemoteDocumentService.get_document()` must call the source HTML attachment path with the canonical filing ID from the returned document, not the raw request ID, when the request used a legacy alias.
- `get_source_html(...)` and `get_source_html_metadata(...)` must also canonicalize before calling `prepare_source_html_render(...)`; otherwise `render_surfaces.source_html.source_id`, `html_url`, response headers, and metadata will leak the legacy request ID.

Compatibility stance:

- During rollout, legacy filing IDs can be accepted as aliases only if the response canonicalizes every active identity field back to `source_id = document_id = edgar:<accession>`.
- The legacy request ID may appear only in explicit diagnostic metadata such as `legacy_source_id` or `request_alias_source_id`; it must not appear in route URLs, source HTML URLs, headers, anchors, source records, or reader context.
- After migration, new code paths should stop constructing legacy IDs.

Acceptance:

- Loading MSFT by `edgar:0000950170-25-010491` returns the same filing as the old legacy ID, but canonical response identity is accession-backed.
- Source HTML loads and metadata materializes with `source_id=edgar:0000950170-25-010491`.
- Legacy and canonical reads have equivalent visible source HTML output for the same accession before legacy aliases are retired.
- A legacy-alias read never emits `MSFT_10Q_2025_6f90a2a7` except in explicit diagnostic alias metadata.
- Response headers from source HTML materialization use the canonical ID.

## Phase 2 - Corpus Cache and Mapping Rebuild

Goal: repair stale parser output and stabilize corpus hashes before evidence migration.

Edgar deploy tasks:

- Commit and deploy the Edgar cache contract follow-up:
  - bump `_MARKDOWN_SCHEMA_VERSION`
  - add invalidation entry for the span-spacing parser fix
  - annotate no-corpus-impact logging-only parser commit
- Verify invalidation completeness tests pass in `Edgar_updater`.

Risk_module corpus rebuild tasks:

- Run invalidation-based delta reingest or a version-floor rebuild for filing corpus rows after the Edgar deploy.
- For the local stale predicate, verify the known 42 rows are queued or repaired.
- Rebuild sections FTS rows through the normal reingest path.
- Regenerate or refresh HTML-to-corpus mapping sets for rebuilt filings, because `corpus_content_hash` changes invalidate old mapping identities.
- Promote the rebuilt corpus only after health checks pass.

Important ordering:

- Do this before migrating reader artifact/evidence identity hashes.
- Existing artifacts contain `corpus_content_hash`; if the corpus rebuild changes it, artifact source identity hashes and mapping-record IDs may change. Rewriting identities after the corpus rebuild avoids a second migration.

Acceptance:

- Local and deployed corpus rows for affected filings no longer contain known bad strings:
  - `BALANCESHEETS`
  - `CASH FLOWSSTATEMENTS`
  - `FINANCIAL STATEMENTSINCOME STATEMENTS`
- `documents.parser_version` or invalidation logs show affected rows were refreshed against the fixed parser.
- Active mapping sets exist for rebuilt source HTML/corpus hash pairs where source HTML is available.

## Phase 3 - Risk Module UI and API Runtime Cutover

Goal: stop creating new legacy filing IDs in the UI/runtime path while keeping old stored artifacts usable until migration completes.

Frontend tasks:

- Treat filing `documentId` as the reader key.
- Add a small canonical identity helper layer instead of scattering conditionals:
  - `canonicalDocumentKey(document)` returns `document.documentId` for filings when present, otherwise the existing source ID.
  - `canonicalAnchorSourceId(anchor)` returns `anchor.documentId` for filing anchors and `anchor.sourceId` for transcripts.
  - `isLegacyFilingSourceId(value)` recognizes content-hash IDs only for audit/migration/test fixtures.
- Use `canonicalAnchorSourceId(anchor)` anywhere existing reader artifacts are opened, filtered, converted into source-inventory drafts, or used to queue prompts. This is required because pre-migration artifacts may still store a legacy `anchor.sourceId` with a canonical `anchor.documentId`.
- Update reader route construction for filings:
  - preferred route identity: `#research/:ticker/reader/filing/:document_id`
  - transcript routes continue using transcript document IDs.
- Audit route parsing and URL encoding for `edgar:<accession>`:
  - colons must round-trip through `hashSync`, `ResearchWorkspaceContainer`, and direct reloads.
  - error-message display helpers must replace both raw and encoded canonical IDs.
- Update `DocumentTabData` usage so filing tabs, query keys, selections, and reader artifact filters use canonical accession-backed identity.
- Ensure `SourceHtmlAvailableSurface.sourceId` is canonical for filings.
- Build filing anchors where:
  - `documentId = edgar:<accession>`
  - `sourceId = documentId` only where v2 schema still requires `sourceId`
- Remove hash-strip display assumptions from filing reader labels:
  - `DocumentTab.tsx` currently formats reader source labels by stripping `_[0-9a-f]{8}`.
  - `researchStore.ts` currently formats document tab labels by stripping `_[0-9a-f]{8}`.
  - Post-cutover filing display should prefer title/period/company metadata, then a compact accession label, never legacy hash cleanup.
- Replace normal frontend test fixtures that use `VALE_10K_2025_deadbeef`, `MSFT_2Q25_10Q_deadbeef`, or `MSFT_10Q_2025_6f90a2a7` with `edgar:<accession>` values.
- Keep legacy hash fixtures only in tests whose name and assertion explicitly cover legacy migration/audit behavior.
- Add an allowlist-based fixture guard that scans frontend/backend tests for hash-style filing IDs and fails outside explicit legacy migration/alias tests.

Backend/proxy tasks in `risk_module`:

- Accept canonical filing document IDs on `/api/research/content/documents`.
- Forward canonical IDs to AI-excel.
- For reader artifacts list filtering, support `document_id` for filings; do not rely on legacy `source_id`.
- While migration is incomplete, listing artifacts for a canonical filing must include artifacts whose `anchor.document_id` matches even when `anchor.source_id` is legacy.
- Keep transcript filtering by transcript document/source ID.
- Validate source HTML metadata against canonical filing identity.

Acceptance:

- Opening a filing from the source inventory creates a route with `edgar:<accession>`, not a legacy hash ID.
- Saved filing reader artifacts from new UI sessions store canonical filing identity.
- React Query keys do not create separate cache entries for legacy and canonical IDs for the same filing.
- No non-migration frontend test fixture uses hash-style filing IDs as the expected active identity.

## Phase 4 - AI-excel Research DB Migration

Goal: rewrite persisted research artifacts that still contain legacy filing IDs, before risk_module reader artifacts reconcile registered evidence.

Tables/files/fields:

- `annotations.source_id`
- `theses.artifact_json`
- `theses.markdown_path` target files when serialized sources are present in markdown
- `research_handoffs.artifact`
- `research_messages.metadata`
- `research_messages.content` only when structured reader actions or document contexts are embedded
- every additional SQLite `TEXT`/JSON-like column classified as `rewrite` by Phase 0, including source refs embedded in model build context, price target, scorecard, decision-log, and history payloads when they can feed active runtime state

Migration script behavior:

- Dry-run by default.
- Discover mappings from either:
  - colocated `document_id` / `endpoint_or_filing_id` fields
  - source HTML identity metadata
  - explicit mapping file generated by Phase 0
- For filing source records:
  - rewrite `source_id` to `edgar:<accession>`
  - keep `endpoint_or_filing_id = edgar:<accession>`
  - recompute `identity_hash` with the same canonical JSON rules as `schema.source_registry.compute_identity_hash`
  - recompute excerpt `hash` with the same rules as `schema.source_registry.compute_excerpt_hash`
  - update `excerpt_id` if it is derived from the old hash prefix
  - preserve `id = src_N`
  - preserve `claim_ids`
  - preserve source refs by rewriting the source record in place, not by calling a path that mints a fresh `src_N`
- For annotations:
  - rewrite `source_id` to `edgar:<accession>`
  - preserve offsets and selected text
- For message metadata:
  - rewrite `document_context.source_id` to `document_context.document_id` for filing contexts
  - preserve content text unless it is structured JSON that explicitly carries the legacy ID
- For markdown snapshots:
  - update the `Sources` section metadata when the markdown is an active thesis serialization.
  - keep `theses.markdown_path` unchanged unless the existing repository already changes it for unrelated reasons; this cutover is source identity, not file identity.

Guardrails:

- Do not mutate transcript rows.
- Do not rewrite generic `src_N` citation refs.
- Do not infer accession from ticker/period if an unambiguous `document_id` is not present.
- Emit unresolved rows for manual review instead of guessing.
- Validate each rewritten thesis with the existing schema/parser path before live write.
- Validate source-excerpt preservation behavior, because `api/research/source_excerpt_preservation.py` treats visible `source_id` changes as identity contradictions.
- Emit an old-to-new source/excerpt mapping for reader artifact migration:
  - old source identity hash
  - new source identity hash
  - old excerpt hash / ID
  - new excerpt hash / ID
  - preserved `src_N`

Acceptance:

- No active local AI-excel research DB row contains legacy filing content-hash IDs in filing identity fields.
- Active thesis markdown snapshots no longer serialize legacy filing IDs in source metadata.
- Thesis source registry validates after rewrite.
- Existing `src_N` references still resolve.
- Existing registered reader artifacts can map their `source_ref` and excerpt to the migrated thesis source record.
- Migration output includes an old-to-new excerpt mapping for every rewritten source record with excerpts.

## Phase 5 - Reader Artifact Store Migration

Goal: rewrite local reader artifacts from legacy filing IDs to canonical filing IDs after corpus hashes are stable.

Migration script behavior:

- Dry-run by default.
- Input: `user_data/research_reader_artifacts.json`.
- For each artifact anchor where:
  - `source_type = filing`
  - `document_id` starts with `edgar:`
  - `source_id != document_id`
- Rewrite:
  - `anchor.source_id = anchor.document_id`
  - any nested filing source identity fields that duplicate `source_id`
  - `corpus_content_hash` to the current corpus DB hash for `document_id`, when the selected text can still be validated or the artifact is quote-only
  - mapping/table authority fields only if a current registry record can be resolved for the new corpus hash
- Preserve:
  - `artifact_id`
  - `created_at`
  - user notes/body/tags
  - transcript artifacts unchanged

Registered-evidence handling:

- For artifacts with `canonical_evidence`, reconcile against migrated AI-excel thesis source records from Phase 4.
- Preserve `source_ref` (`src_N`) where possible.
- If excerpt IDs change because the source identity hash changed, update `canonical_evidence.excerpt_id` to the migrated thesis excerpt ID.
- Consume the Phase 4 old-to-new excerpt mapping rather than recomputing thesis source records independently in `risk_module`.
- If a registered mapped/table artifact cannot be revalidated against the current mapping/table registry, downgrade only the exactness status, not the user note:
  - keep the artifact active
  - mark evidence status as quote/workbench pending re-registration
  - record a migration warning

Acceptance:

- No active filing reader artifact has a legacy content-hash `anchor.source_id`.
- Existing visible reader artifacts still appear in the workspace evidence strip.
- Registered evidence still links to a valid `src_N` and excerpt where the target thesis source exists.

## Phase 6 - Compatibility Removal

Goal: remove the legacy path once production data and clients are clean.

Tasks:

- Add tests that fail when new frontend fixtures or backend responses emit hash-style filing IDs as canonical identities.
- Remove or restrict legacy ID acceptance in gateway/document APIs.
- Remove legacy route-generation code.
- Keep only a diagnostic/audit script that can recognize legacy IDs in old backups.
- Keep historical `archive_only_allowed` audit records out of active runtime scans; they may remain only if they are not surfaced as reader identity.

Acceptance:

- A new reader session cannot produce `MSFT_10Q_2025_6f90a2a7`.
- A new reader artifact cannot persist a filing `source_id` different from `document_id`.
- A new thesis source record for filing evidence uses `source_id = endpoint_or_filing_id = edgar:<accession>`.

## Tests and Verification

### Unit and integration tests

Risk_module:

- `tests/routes/test_research_content.py`
  - canonical filing document load
  - source HTML metadata canonical identity
  - legacy filing alias response canonicalizes every active identity field
  - source HTML route/header/metadata responses do not leak legacy alias IDs
  - reader artifact create/list/register with filing `source_id == document_id`
  - pre-migration reader artifact filtering by canonical `document_id` still returns artifacts whose stored `anchor.source_id` is legacy
  - legacy artifact migration dry-run and live-mode fixture
- Frontend connector tests:
  - document normalization with canonical filing IDs
  - source HTML surface normalization
  - reader artifact serialization
  - query invalidation/filtering by canonical ID
- Research workspace tests:
  - route opens canonical filing ID
  - route reload round-trips `edgar:<accession>` through hash parsing/encoding
  - source inventory opens filing by `edgar:<accession>`
  - saved evidence remains visible after reload
- Guard tests:
  - no non-migration frontend fixture emits hash-style filing IDs as active filing identity
  - display labels do not rely on stripping legacy `_[0-9a-f]{8}` suffixes

AI-excel:

- document routes accept canonical filing IDs
- source HTML routes accept `source_id = document_id = edgar:<accession>`
- legacy alias document/source HTML routes emit canonical IDs in payload, URL, metadata, and headers
- research DB migration dry-run/live fixture
- thesis source registry recomputes identity/excerpt hashes and preserves `src_N` refs
- thesis markdown snapshot migration fixture
- source excerpt preservation fixture where only filing source identity changes

Edgar_updater:

- document API lookup by accession-backed ID
- document API payload includes the canonical filing contract fields required by AI-excel source HTML resolution
- legacy content-hash document lookup, while enabled, emits canonical `source_id = document_id`
- parser invalidation completeness
- section/parser spacing regression

### Live verification

Use MSFT 2Q25 as the smoke filing:

- Open filing by canonical route.
- Verify source HTML reader loads.
- Select a quote, save, reload, and confirm artifact persistence.
- Register as evidence and verify the thesis source record uses canonical filing identity.
- Ask the agent about the active document and verify document context uses `edgar:0000950170-25-010491`.
- Confirm no live response contains `MSFT_10Q_2025_6f90a2a7` except in explicit legacy-audit output.

### Corpus verification

- Query corpus DB for known bad strings after rebuild.
- Verify `documents.content_hash` changed for repaired rows where text changed.
- Verify old markdown files were deleted or marked non-authoritative by the reingest flow.
- Verify active HTML mapping sets match current `corpus_content_hash`.

## Rollback Plan

Before live-mode migrations:

- snapshot JSON stores and SQLite DBs
- record file hashes
- keep dry-run report

Rollback:

- restore the snapshot files
- restart local services
- clear frontend query cache/browser session storage if needed

For production:

- run the DB migration inside the existing deploy/snapshot process
- use a pre-migration DB snapshot
- keep legacy read alias enabled until post-migration health checks pass
- remove alias only after clean audit

## Open Decisions

1. **Schema rename timing:** Do we only canonicalize filing values in existing `source_id` fields now, or introduce a schema-v3 reader anchor that drops filing `source_id` entirely in favor of `document_id`? Recommendation: value cutover first, schema rename later.
2. **Legacy API alias removal date:** Should legacy filing ID reads return 410 immediately after migration, or stay as an internal compatibility alias for one deploy? Recommendation: one deploy of alias with canonical response, then remove.
3. **Mapped/table artifact downgrade semantics:** If a stale mapped/table artifact cannot be revalidated after corpus hash changes, should it become `workbench_only` or `registered_quote`? Recommendation: keep the user artifact active and downgrade exactness, but do not fabricate mapped/table authority.
4. **Production audit source:** Production may have more research DB locations than local. The migration should discover all configured user DBs from AI-excel settings rather than hardcoding local paths.

## Acceptance Criteria

The cutover is complete when:

- New filing routes and document tabs use `edgar:<accession>`.
- New filing reader artifacts use canonical accession-backed identity.
- Existing local/prod reader artifacts have no legacy filing hash IDs in active filing anchors.
- Existing annotations/theses/handoffs/messages have no legacy filing hash IDs in active filing identity fields.
- Corpus rows affected by the parser-spacing bug are rebuilt.
- Source HTML and corpus mapping identity use the rebuilt corpus hash.
- Tests cover canonical reads, migration, and no-new-legacy-output guards.
- Legacy content-hash IDs are no longer required for normal UI, agent, evidence, or corpus workflows.

## Initial Implementation Checklist

- [ ] Commit and deploy Edgar parser invalidation/cache follow-up.
- [ ] Add canonical `edgar:<accession>` document read support where missing.
- [ ] Rebuild affected corpus rows and mapping sets.
- [ ] Add legacy filing ID audit scripts.
- [ ] Cut over frontend reader keys/routes to canonical IDs.
- [ ] Cut over reader artifact creation/filtering to canonical IDs.
- [ ] Add AI-excel research DB migration.
- [ ] Add risk_module reader artifact JSON migration.
- [ ] Run dry-run migrations locally and review output.
- [ ] Run live local MSFT smoke test.
- [ ] Deploy in order with snapshots and post-deploy audits.
