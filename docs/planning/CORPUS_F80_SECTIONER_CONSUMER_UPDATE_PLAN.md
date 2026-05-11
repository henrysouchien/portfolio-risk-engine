# F80 — Consumer-side updates for Edgarparser sectioner improvements (cover page + Items 4-6/9-15)

**Status**: DRAFT — pending Codex review
**Author**: 2026-05-08
**Trigger**: Edgarparser ships F79 (cover-page section + Items 4-6, 9-15 separate sectioning in `/api/sections`). See `Edgar_updater/docs/TODO.md` (filed 2026-05-08, commit `e7560f9`).
**Risk_module dependency tracked as**: F79 in `risk_module/docs/TODO.md`.

---

## 1. Goal

When Edgarparser starts emitting new section headers (`Cover Page`, `Item 4`, `Item 5`, `Item 6`, `Item 9`, `Item 10–14`, `Item 15`, `Signatures` for 10-K; equivalents for 10-Q + 20-F), risk_module's corpus consumer should:

1. Index those sections under correct canonical ids (so predicate queries like `section_key="<upstream cover key>"` work).
2. Re-ingest the existing corpus so search hits get the right `section` attribution.
3. Surface the new content (especially cover-page + Item 5 shareholders-of-record) in Hank's prompt routing hints.

**Non-goal**: No change to the corpus DB schema or `sections_fts` indexing logic — those are section-name-agnostic by design.

---

## 2. Scope

### 2.1 In scope (3 changes total)

**(a) Extend `_EDGAR_CORPUS_HEADER_TO_ID`** at `core/corpus/section_map.py:16`. Add canonical id mappings for new section headers across forms. Concrete additions:

**Canonical id naming — copy upstream exactly** (Codex R1 finding 1): `filings_source_excerpt` at `core/corpus/filings.py:182,210` converts our corpus header to a canonical id and sends it to Edgarparser as `sections=[canonical_section_id]`. If our consumer stores `cover_page` but upstream's actual section key is `cover`, source-excerpt round-trips break. **Decision**: defer the canonical-id naming choice until F79 ships and we can read the actual emitted keys. The example mappings below show provisional names — replace with upstream's exact keys at implementation time. Add an alias layer only if upstream itself uses inconsistent keys across sections.

For `10-K`:
```
'Cover Page': '<copy upstream key>'  # provisional: cover_page
'Item 4. Mine Safety Disclosures': 'item_4'
'Item 5. Market for Registrant\'s Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities': 'item_5'
'Item 6. [Reserved]': 'item_6'  (— or 'item_6_reserved' since "Reserved" varies)
'Item 9. Changes in and Disagreements with Accountants on Accounting and Financial Disclosure': 'item_9'
'Item 9A. Controls and Procedures': 'item_9a'
'Item 9B. Other Information': 'item_9b'
'Item 9C. Disclosure Regarding Foreign Jurisdictions that Prevent Inspections': 'item_9c'
'Item 10. Directors, Executive Officers and Corporate Governance': 'item_10'
'Item 11. Executive Compensation': 'item_11'
'Item 12. Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters': 'item_12'
'Item 13. Certain Relationships and Related Transactions, and Director Independence': 'item_13'
'Item 14. Principal Accountant Fees and Services': 'item_14'
'Item 15. Exhibits and Financial Statement Schedules': 'item_15'
'Signatures': 'signatures'
```

For `10-Q`:
```
'Cover Page': 'cover_page'
'Part II, Item 1. Legal Proceedings': 'part2_item1'
'Part II, Item 2. Unregistered Sales of Equity Securities and Use of Proceeds': 'part2_item2'
'Part II, Item 3. Defaults Upon Senior Securities': 'part2_item3'
'Part II, Item 4. Mine Safety Disclosures': 'part2_item4'
'Part II, Item 5. Other Information': 'part2_item5'
'Part II, Item 6. Exhibits': 'part2_item6'
'Signatures': 'signatures'
```

For `20-F`: the existing single `Annual Report` mapping stays. Add a structural breakdown ONLY if Edgarparser also ships per-Item 20-F sectioning. **Decision**: defer the 20-F extension to a separate sub-step until Edgarparser confirms what 20-F section keys it actually emits.

**Predicate parser side note** (Codex R1 finding 2): `_SECTION_FORM_TYPES = ('10-K', '10-Q', '8-K')` at `core/corpus/predicate.py:56`. 20-F predicate queries are currently rejected today (the `_section_headers_for_key` lookup never tries 20-F). When F79 ships per-Item 20-F keys, F80 must add `20-F` to that tuple too — otherwise predicate `section_key` queries against 20-F filings will still raise `unknown section_key`. Add as part of the same code change as the section_map extension.

For `6-K`: keep `Foreign Issuer Report` as-is unless F79 splits it.

**(b) Update Hank prompt routing hint** at `AI-excel-addin/api/agent/shared/system_prompt.py:1392`. Current line:
> *"For broad qualitative SEC questions, use source-pack retrieval: regulatory risk checks Item 1 plus Item 1A; concentration checks financial-statement notes/tables; revenue disaggregation checks revenue/segment notes; debt terms check debt notes/tables."*

Extend with cover-page + Items 4-6/9-15 routing (softened verbs per Codex R1: "look in" / "typically appear in" rather than "live in" — keeps it as routing guidance, not a brittle disclosure taxonomy):
> Append: *"Cover-page facts (CIK, share-class counts, registered securities, filer status, fiscal year designation) typically appear in the `Cover Page` section. Shareholders of record, share repurchases, and equity-issuance disclosures typically appear in Item 5. Controls-and-procedures and remediation language typically appear in Item 9A. Executive compensation and governance discussion are usually in Items 10–14 (but are often incorporated by reference to DEF 14A — verify with `filings_search` first)."*

Same single-line change pattern as F72 — surgical edit. No need to extend `EDGAR_METRIC_ROLE_GUIDANCE` or other constants; this is a different concern.

**(c) Re-ingest the merged universe** to refresh `sections_fts` rows with correct attribution.

**Re-ingest path choice — use `core.corpus.reingest`, NOT `corpus_phase1_bulk_ingest.py`** (Codex R3 finding 1). The bulk ingest path calls `ingest_raw` (`core/corpus/ingest.py:111`) which writes a NEW content-hash file (`new_file_path`) WITHOUT deleting the old markdown file. With F79 changing section output, the new content has a new hash → new file → thousands of orphaned old files on disk → reconciler walker divergences (`core/corpus/reconciler/walker.py:70`) → drift threshold trip (`workers/tasks/corpus.py:91`).

`core.corpus.reingest.reingest_one` (at `core/corpus/reingest.py:94`) already tracks `old_file_path` and handles file replacement correctly — that's its design. Need a small wrapper script that iterates the merged universe and calls `reingest_one` per `(ticker, accession)`. Since no `corpus_bulk_reingest.py` exists today (only `corpus_reingest_log_rotate.py`, unrelated), F80 includes a **new wrapper script** as part of §2.1(c).

```bash
sqlite3 data/filings.db ".backup data/filings.db.pre_f80_<date>"
# Wrapper iterates documents in merged universe, calls reingest_one per (ticker, accession),
# tracks plan IDs + reconciliation state.
EDGAR_API_TIMEOUT=120 python3 scripts/corpus_bulk_reingest.py \
  --universe data/corpus/universe.json \
  --log logs/corpus/f80_reingest_<date>.jsonl \
  --requests-per-second 2 \
  --retry-attempts 3 \
  --retry-base-delay 1 \
  --retry-max-delay 30
```

**Wrapper selection criteria — EDGAR filings only** (Codex R4 finding 1, BLOCKING). `reingest_one` is Edgarparser `/api/sections`-shaped via `_prepare_from_response` → `_assemble_body_from_api_response` (`scripts/corpus_ingest_accession.py:350`). If a `source='fmp_transcripts'` row passes through, the wrapper would fetch a filing response, parse it with transcript parsing, and corrupt or delete the transcript file. **Required SQL filter**:
```sql
SELECT document_id, ticker, source_accession, form_type, fiscal_period, source
FROM documents
WHERE source = 'edgar'
  AND form_type IN ('10-K', '10-Q', '20-F', '6-K')  -- or the F79-affected subset
```

Adding `source = 'edgar'` is mandatory; without it the wrapper can clobber transcripts. The form_type filter narrows further if F79 only affects specific forms.

**Accession round-trip validation** (Codex R4 finding 2). For 20-F/6-K (and any case where a future duplicate filing could share the same `(ticker, year, quarter)`), the wrapper must validate the returned `/api/sections` filing's accession against `documents.source_accession` before calling `reingest_one` — otherwise a refreshed body could land under the wrong `document_id`. The fetch resolution path is `_resolve_api_params_from_row` at `core/corpus/filings.py:412` (maps only to `(year, quarter, source)`); the wrapper layers an accession-equality check on top before accepting the response.

**Behavior guarantee** (after both filters in place): the wrapper's per-document call (a) selects only EDGAR filing rows, (b) verifies returned accession matches stored, (c) calls `reingest_one`, which deletes the old markdown file (`core/corpus/reingest.py:455` — verified by Codex R4 against existing test `test_reingest_one_happy_path_updates_db_and_deletes_old_file`), upserts the document row, and deletes-then-replaces all `sections_fts` rows by `document_id` (`core/corpus/reingest.py:420`). No orphaned files, no orphaned FTS rows, no transcript corruption.

**Note on `_SECTION_FORM_TYPES` and 6-K** (Codex R4 minor): if F79 also adds per-section structure to 6-K (currently the corpus stores 6-K as a single `Foreign Issuer Report` section), F80 should extend `_SECTION_FORM_TYPES = ('10-K', '10-Q', '8-K')` at `core/corpus/predicate.py:56` to include `'6-K'` alongside `'20-F'`. Read upstream's actual emitted keys at implementation time.

### 2.2 Explicitly NOT in scope

- **Schema migration on `sections_fts`** — the column is `TEXT` with no enum/CHECK; nothing to migrate.
- **Predicate parser changes** (mostly) — `_section_headers_for_key` derives via section_map; expanding the map auto-extends predicate support for forms already in `_SECTION_FORM_TYPES`. Verified at `core/corpus/predicate.py:377-391`. **Exception**: if F79 ships per-Item 20-F sectioning, `_SECTION_FORM_TYPES = ('10-K', '10-Q', '8-K')` at `core/corpus/predicate.py:56` must be extended to include `'20-F'` — bundled with the section_map change as part of §2.1(a).
- **MCP tool argument validators** — `mcp_tools/corpus/` doesn't enum-restrict the section argument; tools pass section through as opaque string.
- **Test fixture rewrites** — existing tests at `tests/test_corpus_ingest_accession.py`, `test_corpus_types.py`, `test_reconciler_walker.py` use specific sections as *sample inputs*, not *the universe of valid sections*. They continue to pass.
- **Cross-repo Hank prompt sweep beyond `system_prompt.py:1392`** — the 8-surface F72 sweep didn't find other section-name-specific prompt content. Skipping a re-sweep unless verification surfaces a gap.
- **`scripts/corpus_health_report.py` legacy 10-Q section heuristics** at lines 22, 35 — Phase 2-real coverage gate is form-presence-based (`10-K` / `10-Q` / `20-F` cohort thresholds) rather than per-section coverage. No required F80 change in the health report. If we ever want a "% of 10-Ks with cover-page section present" metric as informational health, that's a separate plan.

---

## 3. Open questions / decisions

### 3.1 Canonical id naming — defer to upstream
**Don't pre-pick names.** Read `/api/sections` after F79 ships and use upstream's exact emitted keys. Reasoning per Codex R1: `filings_source_excerpt` round-trips the canonical id back to Edgarparser at `core/corpus/filings.py:182,210`; if our consumer's stored key ≠ upstream's emitted key, source-excerpt API breaks. Add an alias layer ONLY if upstream itself uses inconsistent keys across sections.

Examples in §2.1(a) ("provisional: cover_page" etc.) are placeholders — replace with upstream's actual keys at implementation time.

### 3.2 Stale section rows after re-ingest — VERIFIED RESOLVED (Codex R1)
**Was an open question; Codex R1 ground-truthed it as already handled.** All three ingest paths delete `sections_fts` rows by `document_id` BEFORE inserting new ones:
- `core/corpus/ingest.py:119` (`ingest_raw` — primary path used by `scripts/corpus_ingest_accession.py:325`)
- `core/corpus/reingest.py:415`
- `core/corpus/reconciler/db_sync.py:179`

So when section names change between old and new ingest, the old rows are wiped and the new ones are inserted clean. **No stale-row risk; no DELETE statement needed.** Step 4 of the original implementation order ("audit insert behavior") is dropped.

Existing test coverage at `tests/test_reconciler_sections_fts.py:31` already exercises stale-row replacement. No new F80 test needed (Codex R2).

### 3.3 Verification smokes
After re-ingest, verify:
- Hank query "Apple FY2025 cover page CIK" → corpus search returns `[S]` cited from cover-page section, not from elsewhere.
- Hank query "Apple FY2025 shareholders of record" → cited from `Item 5`, not `Item 3`.
- Predicate query `section_key="<upstream cover key>"` returns only cover-page sections.
- Predicate query `section_key="item_5"` returns Item 5 content only.
- `corpus_health_report.py --gate-coverage --phase 2-real` still passes (cover-page is informational, not a gate column).

---

## 4. Implementation order

1. **Wait for F79 to ship upstream** — verify by hitting `/api/sections?ticker=AAPL&year=2025&quarter=4` against prod and confirming the response includes `Cover Page` + `Item 4` + `Signatures` etc. as separate sections.
2. **Codex plan review of this doc** — iterate to PASS.
3. **Codex implementation R1** — three deliverables:
   - Extend `_EDGAR_CORPUS_HEADER_TO_ID` per §2.1(a) using upstream's actual section keys (read live from `/api/sections` after F79 ships).
   - Add `20-F` to `_SECTION_FORM_TYPES` at `core/corpus/predicate.py:56` if F79 emits 20-F per-Item keys.
   - **NEW** `scripts/corpus_bulk_reingest.py` wrapper. SELECT filter: `WHERE source = 'edgar' AND form_type IN ('10-K', '10-Q', '20-F', '6-K')` (REQUIRED to avoid transcript corruption — Codex R4 BLOCKING finding 1). Per-row accession round-trip validation before `reingest_one` (Codex R4 finding 2 — guards 20-F/6-K period-collision case). Calls `core.corpus.reingest.reingest_one`, writes JSONL log of per-doc outcome, exit code reflects pass/fail. Distinct from `corpus_phase1_bulk_ingest.py` because that one creates orphan files on content-hash change (Codex R3 finding 1). F88 hardening adds `--requests-per-second`, retry/backoff for 429/502/503/504, transient-failure log metadata, and dry-run wall-clock estimates.
   - Tests: extend `tests/test_section_map.py:202` round-trip scaffold. New `tests/scripts/test_corpus_bulk_reingest.py` per Codex R4/F88: real tiny temp corpus DB (seed one 10-K, one 20-F or 6-K, one `fmp_transcripts`, one off-universe EDGAR row) + mocked `reingest_one`; assert (a) only in-universe EDGAR rows are selected and called, (b) transcript row excluded, (c) JSONL records written, (d) failed mock result drives nonzero exit, (e) transient 502 retries can recover, (f) exhausted 429 is logged with explicit HTTP metadata, and (g) dry-run reports minimum wall-clock at the configured request rate. The actual file deletion path is already covered by `tests/test_corpus_reingest.py` — full E2E here is redundant. Stale-row replacement coverage exists at `tests/test_reconciler_sections_fts.py:31` (Codex R2).
4. **WAL-safe DB snapshot** before re-ingest (`sqlite3 data/filings.db ".backup …"`).
5. **Re-ingest** the merged universe via the new `scripts/corpus_bulk_reingest.py` wrapper (NOT `corpus_phase1_bulk_ingest.py` — see §2.1(c) Codex R3 finding 1). Wrapper iterates every document by `(document_id, source)` and calls `core.corpus.reingest.reingest_one` per row, which handles old-file cleanup + FTS row replacement.
6. **Verification smokes** per §3.3.
7. **Cross-repo** prompt update at `AI-excel-addin/api/agent/shared/system_prompt.py:1392` per §2.1(b). Path-scoped commit. Restart gateway to pick up new prompt (per `feedback_long_running_processes_stale_module_state.md`).
8. **Hank live-smoke**: cover-page query + Item 5 shareholders query.
9. Update F79 / F80 status in TODO + close out.

---

## 5. Effort + cost rollup

- §2.1(a) section_map extension: S — ~25 LOC + ~30 LOC test
- §2.1(b) Hank prompt: S — 3 LOC, cross-repo
- §2.1(c) re-ingest: ~15-30 min wall clock at current 3,800 docs (or post-Phase-2-real ~7,800 docs), ~$50-200 cost
- §3.2: verified resolved by Codex R1 — no audit work, no DELETE statement needed
- Verification smokes: ~10 min
- **Total: ~1 hour wall clock + ~$50-200 spend**, fully consumer-side (no upstream dependencies once F79 lands)

---

## 6. Sequencing relative to Phase 2-real

If F79 ships **before** Phase 2-real bulk ingest:
- Run F80 implementation + re-ingest current 3,800 docs → THEN run Phase 2-real bulk ingest with full sectioning from the start. ~$50 saved on re-ingest cost.

If F79 ships **after** Phase 2-real:
- Run Phase 2-real now (covers ~7,800 docs total).
- After F79: run F80 implementation + re-ingest the full 7,800-doc merged universe. ~$80-200 cost.

Either order works; the only delta is re-ingest scale. Phase 2-real plan (`CORPUS_PHASE_2_REAL_PLAN.md`) currently waits on F79.
