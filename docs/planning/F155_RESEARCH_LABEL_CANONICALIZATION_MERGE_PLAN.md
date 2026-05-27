# F155 Research Label Canonicalization And Merge Plan

**Status:** DRAFT R1 - needs Codex review
**Date:** 2026-05-26
**Owner:** Research workspace identity contract workstream
**Primary implementation repo:** `/Users/henrychien/Documents/Jupyter/AI-excel-addin`
**Tracking repo:** `/Users/henrychien/Documents/Jupyter/risk_module`

## Executive Summary

F155 is a backend identity-contract bug, not a frontend display bug.

The research workspace currently treats `ticker + label` as a durable identity. That identity is persisted in `research_files`, copied into `theses`, used for markdown paths, used for file lookup, and surfaced back to the UI. Several upstream boundaries trim labels, but none canonicalize percent-encoded labels. As a result, these two labels can become separate rows even though they are the same user intent:

- `F82-F87 live verification`
- `F82-F87%20live%20verification`

The local user `1` database already has this split for `PCTY`:

| id | ticker | label | notable state |
| --- | --- | --- | --- |
| 225 | PCTY | `F82-F87 live verification` | 3 threads, 1 thesis, 1 history row |
| 227 | PCTY | `F82-F87%20live%20verification` | 2 threads, 1 thesis, 1 finalized handoff, 5 model build contexts, 2 history rows |

A direct rename of row `227` to the decoded label is blocked by the existing unique constraint on `(ticker, label)`. Both rows have child state, and both rows have a thesis, so the repair must be a deliberate merge. Decoding only in the frontend title helper would hide one symptom while leaving the split identity in place.

The fix should be a full cutover to one research-label contract:

1. Add one shared canonicalizer for research identity labels in AI-excel-addin.
2. Apply it at all route and repository identity boundaries before labels are written, looked up, compared, copied into thesis snapshots, or converted to markdown paths.
3. Add focused tests proving encoded and decoded labels resolve to the same identity.
4. Add a dry-run-first repair script for pre-existing duplicate groups, with an explicit merge spec for groups that contain conflicting child state.

## Root Cause

The backend has multiple local normalizers that only trim whitespace.

At the route boundary:

- `AI-excel-addin/api/research/routes.py:180` has `_normalize_request_label(...)`, which currently returns `str(value or "").strip()`.
- `AI-excel-addin/api/research/routes.py:185` compares the request label to `body.idea.label` using the trimmed values.
- `AI-excel-addin/api/research/routes.py:828` passes `body.label` directly to `repo.upsert_file(...)` for ticker+label file creation.

At the repository boundary:

- `AI-excel-addin/api/research/repository.py:779` has `_normalize_thesis_label(...)`, which currently only trims.
- `AI-excel-addin/api/research/repository.py:1447` normalizes `upsert_file(..., label=...)` with trim only.
- `AI-excel-addin/api/research/repository.py:1474` normalizes `get_file_by_ticker_label(..., label=...)` with trim only.
- `AI-excel-addin/api/research/repository.py:1488` normalizes `seed_research_file_from_idea(...)` labels with trim only.
- `AI-excel-addin/api/research/repository.py:1988` normalizes `update_file(..., label=...)` with trim only.

At thesis and markdown boundaries:

- `AI-excel-addin/api/research/repository.py:792` builds thesis markdown paths from the label after trim-only normalization.
- `AI-excel-addin/schema/thesis_markdown.py:192` also computes markdown paths from `ticker + label`.
- `AI-excel-addin/api/research/thesis_service.py` resolves markdown filenames back to research files by comparing exact labels and slugified labels.

The frontend helper is not the correct fix point:

- `frontend/packages/ui/src/components/research/ResearchPresentation.tsx:242` renders `file.label` as returned by the backend.

That helper should keep rendering the canonical label it receives. It should not become an identity normalizer.

## Reproduction Evidence

The local DB contains two rows for the same logical `PCTY` label:

```sql
SELECT id, ticker, label, company_name, created_at, updated_at
FROM research_files
WHERE ticker='PCTY' AND id IN (225, 227);
```

Observed:

| id | ticker | label | company_name |
| --- | --- | --- | --- |
| 225 | PCTY | `F82-F87 live verification` | empty |
| 227 | PCTY | `F82-F87%20live%20verification` | `Paylocity Holding Corporation` |

Child-state counts:

| table | 225 | 227 |
| --- | ---: | ---: |
| `research_threads` | 3 | 2 |
| `theses` | 1 | 1 |
| `research_handoffs` | 0 | 1 |
| `research_file_history` | 1 | 2 |
| `model_build_contexts` | 0 | 5 |
| `model_insights` | 0 | 0 |
| `price_targets` | 0 | 0 |

The two thesis rows are also split:

| research_file_id | thesis label | markdown path | version |
| ---: | --- | --- | ---: |
| 225 | `F82-F87 live verification` | `theses/PCTY__f82_f87_live_verification.md` | 2 |
| 227 | `F82-F87%20live%20verification` | `theses/PCTY__f82_f87_20live_20verification.md` | 10 |

This proves the repair is not a single metadata edit.

## Canonical Label Contract

Add one shared helper in AI-excel-addin, for example:

```python
def canonicalize_research_label(value: object | None) -> str:
  ...
```

The contract:

- Accept `None`, strings, and primitive values; return a string.
- Convert to string.
- Strip leading and trailing whitespace.
- If the string contains one or more percent-encoded octets matching `%[0-9A-Fa-f]{2}`, apply `urllib.parse.unquote(...)` exactly once.
- Strip again after decoding.
- Do not use `unquote_plus`; `+` should remain a literal plus unless the user actually sent `%20`.
- Do not repeatedly decode. For example, `foo%2520bar` canonicalizes to `foo%20bar`, not `foo bar`.
- Preserve empty labels as `""`; unlabeled research remains a supported distinct identity from labeled research.

This is intentionally narrower than generic URL/query decoding. The observed bug came from path/hash encoding of spaces, and the durable identity should not silently reinterpret `+` or recursively decode potentially meaningful literal percent signs.

## Implementation Plan

### Phase 1 - Shared canonicalizer

Add a small module in AI-excel-addin, likely one of:

- `api/research/labels.py`
- `api/research/identity.py`

The module should export:

- `canonicalize_research_label(value: object | None) -> str`
- optionally `canonicalize_research_ticker(value: object | None) -> str` only if the implementation wants to remove repeated ticker normalization at the same time.

Keep the first change narrow. The minimum F155 fix only needs the label canonicalizer.

### Phase 2 - Route boundary cutover

Update `api/research/routes.py`:

- `_normalize_request_label(...)` should call the shared canonicalizer and return `None` only for the empty canonical label when the current route semantics expect an omitted label.
- `_idea_request_mismatch_payload(...)` should compare canonical request label to canonical idea label.
- `_resolve_idea_request(...)` should copy the canonical request label into the idea only when the idea omitted a label.
- `upsert_file(...)` should pass canonical labels through the repository path. The repository remains the final enforcement point, so the route layer is not the only defense.

Expected behavior:

- A request with top-level `label="Bull%20Case"` and idea label `"Bull Case"` is accepted.
- A request with top-level `label="Bear%20Case"` and idea label `"Bull Case"` is rejected.
- Error payloads report canonical labels, so the client sees the same identity the backend will persist.

### Phase 3 - Repository boundary cutover

Update `api/research/repository.py`:

- Replace trim-only label normalization in `upsert_file(...)` with the shared canonicalizer.
- Replace trim-only label normalization in `get_file_by_ticker_label(...)`.
- Replace trim-only label normalization in `seed_research_file_from_idea(...)`.
- Replace trim-only label normalization in `update_file(...)`.
- Replace `_normalize_thesis_label(...)` with the shared canonicalizer or delegate to it.
- Ensure `update_thesis_parent_snapshot(...)` and `rename_thesis_parent(...)` use canonical labels when they update thesis rows and markdown paths.
- Ensure `get_thesis(ticker, label)` canonicalizes the lookup label before querying.

Expected behavior:

- `repo.upsert_file("PCTY", "F82-F87%20live%20verification")` stores the decoded label.
- A later `repo.upsert_file("PCTY", "F82-F87 live verification")` returns the same row.
- `repo.get_file_by_ticker_label("PCTY", "F82-F87%20live%20verification")` returns the decoded row.
- Thesis snapshots and markdown paths use the canonical label.

### Phase 4 - Thesis markdown path cutover

The markdown path helpers should produce one path for encoded and decoded inputs.

Update or wrap:

- `api/research/repository.py:_thesis_markdown_relative_path(...)`
- `schema/thesis_markdown.py:thesis_markdown_path(...)`
- `api/research/thesis_service.py:_absolute_markdown_path(...)`
- `api/research/thesis_service.py:_find_research_file(...)`
- lock helpers that derive lock filenames from labels, such as `api/research/handoff.py` and `api/research/thesis_log_helpers.py`

Expected behavior:

- `thesis_markdown_path("PCTY", "F82-F87%20live%20verification")` equals `thesis_markdown_path("PCTY", "F82-F87 live verification")`.
- Lock paths for encoded and decoded labels are the same.
- A markdown load by slug continues to work for canonical paths.

### Phase 5 - Existing duplicate repair

Add a repair script in AI-excel-addin, for example:

```text
scripts/repair_research_label_duplicates.py
```

Required properties:

- Default mode is dry run.
- Accepts a specific user DB path or user id.
- Scans `research_files` and groups rows by `(ticker, canonical_label)`.
- Prints a machine-readable and human-readable report for each duplicate group.
- Refuses to mutate any group with conflicting child state unless an explicit merge spec is supplied.
- Runs each applied merge in a single SQLite transaction with foreign keys enabled.
- Creates a backup before mutation unless explicitly disabled.
- Writes a `research_file_history` audit event on the surviving row.

Suggested command shape:

```bash
python scripts/repair_research_label_duplicates.py --user-id 1 --dry-run
python scripts/repair_research_label_duplicates.py --user-id 1 --plan-file data/repairs/f155_pcty_merge.json --apply
```

The dry-run report should include:

- duplicate group key
- row ids
- original labels
- canonical label
- child counts by table
- thesis ids and versions
- finalized/draft handoffs
- model build context ids
- proposed keeper candidates
- conflicts requiring explicit selection

### Phase 6 - PCTY merge spec

For the current local duplicate, do not rely on a blind newest-row or oldest-row rule.

The conflict is real:

- Row `225` already owns the canonical decoded label.
- Row `227` owns the finalized handoff and model build contexts.
- Both rows own a thesis.
- Both rows own reserved `Panel` and `Explore` thread rows, and those tables have partial unique indexes per research file.

The repair script should support a hand-authored merge spec for this case. The likely operator choice is:

- Keep the canonical decoded row id `225` as the surviving research identity, because it already has the target `(ticker, label)` pair.
- Backfill row `225.company_name` from row `227` when row `225` is empty.
- Move non-conflicting durable artifacts from row `227` to row `225`, including finalized handoffs and model build contexts.
- Preserve the higher-version row `227` thesis as the surviving active thesis if review confirms it contains the latest F82-F87/F124 work.
- Preserve the superseded row `225` thesis as a historical artifact, not by silently deleting it. Options include exporting it to a repair artifact file and appending a history event that records the superseded thesis id.
- Merge or preserve thread transcripts without violating the `idx_threads_explore` and `idx_threads_panel` unique indexes. Reserved `Panel` and `Explore` rows need explicit handling: either merge messages into the surviving reserved threads or rename/archive duplicate reserved threads before reassignment.
- Delete or tombstone row `227` only after all referenced children are moved or archived and the post-merge invariants pass.

The exact active-thesis selection should be reviewed before applying the local data repair. The script should make the review visible instead of hiding it behind an automatic heuristic.

## Test Plan

### Canonicalizer unit tests

Add tests that prove:

- `None` becomes `""`.
- `" Bull Case "` becomes `"Bull Case"`.
- `"Bull%20Case"` becomes `"Bull Case"`.
- `"Bull%2FCase"` decodes once to `"Bull/Case"` if the contract accepts slash in labels.
- `"Bull+Case"` stays `"Bull+Case"`.
- `"Bull%2520Case"` becomes `"Bull%20Case"`, not `"Bull Case"`.
- Invalid percent text such as `"Bull%ZZCase"` is left unchanged.

### Repository tests

Add focused tests under `AI-excel-addin/tests/api/research/`:

- `upsert_file` stores canonical labels and reuses the same row for encoded and decoded labels.
- `get_file_by_ticker_label` accepts encoded and decoded label inputs.
- `seed_research_file_from_idea` stores the canonical label.
- `update_file` canonicalizes label updates and surfaces a conflict if the canonical target already exists.
- `create_thesis`, `get_thesis`, and parent snapshot updates all use the canonical label.
- Thesis markdown path generation is identical for encoded and decoded labels.

### Route tests

Extend `tests/api/research/test_start_research_from_idea.py`:

- Top-level encoded label plus decoded idea label is accepted and persists the decoded label.
- Top-level decoded label plus encoded idea label is accepted and persists the decoded label.
- Encoded-vs-decoded mismatch after canonicalization is still rejected when the actual labels differ.
- Ticker+label file creation with an encoded label returns the canonical label and reuses an existing decoded row.

### Repair script tests

Add tests with a temp user DB:

- Dry run reports duplicate groups without mutation.
- Non-conflicting duplicate rows can be merged automatically.
- Conflicting duplicate rows fail closed without a merge spec.
- A merge spec can move child rows and delete/tombstone the duplicate only when post-merge invariants pass.
- The script refuses to run without a backup path in apply mode unless a deliberate flag is supplied.

### Post-merge invariant checks

The repair script should validate:

- No duplicate `(ticker, canonical_label)` groups remain.
- No research file row stores a label that differs from its canonical form.
- Every thesis label matches the parent research file canonical label.
- Every thesis markdown path matches the canonical label.
- No child table references a deleted duplicate row.
- `PRAGMA foreign_key_check` returns no rows.

## Acceptance Criteria

F155 is complete when:

- AI-excel-addin has one shared research-label canonicalizer.
- New writes cannot create separate rows for encoded and decoded versions of the same label.
- Reads and lookups accept encoded or decoded input and resolve to the same row.
- Thesis snapshots, markdown paths, and lock paths use the canonical label.
- Tests cover route, repository, thesis, markdown path, and repair-script behavior.
- The local PCTY duplicate can be repaired by a scripted, auditable merge path.
- The frontend compare title renders the canonical backend label without needing display-only decoding.

## Non-Goals

- Do not add frontend-only decoding in `buildResearchDisplayTitle(...)` as the fix.
- Do not recursively decode labels.
- Do not use `unquote_plus`.
- Do not remove support for empty labels.
- Do not apply ad hoc SQL directly to the user DB.
- Do not silently discard either PCTY thesis before review.

## Suggested Implementation Order

1. Add canonicalizer and unit tests.
2. Wire route/repository/thesis identity boundaries.
3. Add repository and route regression tests.
4. Add repair script in dry-run mode.
5. Run dry run against local user `1` DB and review the PCTY merge report.
6. Add the explicit PCTY merge spec.
7. Apply the repair to a backup copy first.
8. Apply to the local DB only after invariants pass on the backup.
9. Live-test `#research/compare/88,225` or the equivalent repaired compare route.
10. Mark F155 done after code tests, repair dry run, repair apply, and live UI verification all pass.
