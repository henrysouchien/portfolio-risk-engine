# F156 Reader — D (Perceptual) + E (Visual/Vision) Design Spec — v3

**Status:** Accepted implementation supplement — **Codex review PASS (2026-05-29)**, confirmed on the committed text (the three non-blocking corrections were folded in and re-confirmed; no blockers, no parked decisions). History: v1 FAILED (idealized as-built); v2 PASSED but predated the D-posture decision; v3 finalizes D (posture A) and deepens E to implementable depth (E-pre-1 grounded in the actual Edgar_updater code).
**Date:** 2026-05-29
**Owner:** Research Workspace / Filing Reader
**Parent:** `F156_READER_SYSTEM_ARCHITECTURE.md` + `F156_READER_IMPLEMENTATION_PLAN.md` (waves D, E).
**Authority:** This supplement is the accepted D/E detail. Parent docs must fold these decisions in; after reconciliation the system architecture remains the umbrella source of truth.

## 0. What v1 got wrong (so v2 doesn't repeat it)

Codex's review found three things v1 ignored, all verified in code:
1. **D is already partially built — with a richer payload than v1 claimed.** The viewport context already carries a per-message **read-trail** (`observed_at`, `scroll{scrollTop,viewportHeight,documentHeight}`, `viewport_coverage`, `audit.scope`) and `useResearchChat` persists the whole `documentContext` on the user message (`researchStore.ts:125–141,688–709`; `useResearchChat.ts:68`). v1 claimed "no durable trail." False. v2 **pares it back.**
2. **The registry rejects tables; it does not consume provenance.** `html_mapping.py:452` *unconditionally rejects* `content_type == "table"`; `reader_artifacts.py:235` normalizes only quote/prefix/suffix/section and **drops `table_context`**. v1 said E "populates `table_context` and the registry mints" — impossible without extending both.
3. **edgar-financials needed accession-bound domestic lookup.** The original review found `get_filing_tables` rejected domestic `accession` and domestic table responses omitted filing metadata. E-pre-1 now addresses that primary table path in `Edgar_updater`; `get_statement`/`get_metric` identity remains secondary and deferrable.

## 1. Decisions resolved

| # | Decision | Resolution (accepted v3) | Grounding |
|---|---|---|---|
| D1 | Read-trail granularity | **Bounded, disclosed — DECIDED (A) 2026-05-29.** `scope: 'visible_sections_only'`, **`dwellTimeMsRecorded: false`** (the worst surveillance signal excluded). Keeps `current_section`/`visible_sections` + scroll + `observed_at`. Accepted as-built; serves F156 auditability. (Strict strip rejected as over-rotated.) | `SourceHtmlPane.tsx:316`; `researchStore.ts:142` |
| D2 | Retention | **Attached to the research turn** (`persistence: 'attached_to_research_turn'`) — persisted with the message for read-audit/replay; the payload self-declares it (audit manifest). | `researchStore.ts:142`; `useResearchChat.ts:68` |
| D3 | Consent/disclosure | **Required before any UI surfaces the trail** in the multi-user product. The data self-labels; add user-facing disclosure when surfaced. The one remaining D item. | — |
| D4 | Replay | Replayable from the turn — by design, for research provenance. | — |
| E1 | Vision trigger | **On-demand** ("read this table"), not on-select. | cost/latency |
| E2 | Registry/artifact path | **E must extend** the server-side artifact/registry path for table-cell provenance. ReaderBridge may produce only a candidate table/cell localization; exact table evidence is minted only by the backend resolver after identity-bound parsed-value validation. Do not let L4/L5 or the browser construct citeable table evidence directly. | `html_mapping.py:452`, `reader_artifacts.py:235` |
| E3 | Value source identity | **Primary table path implemented upstream**: Edgar_updater supports accession-bound domestic table lookup + filing metadata in responses. Edgar_updater proves SEC filing identity (`accession`, `primary_document_url`/`filing_url`, CIK, form, period); the reader resolver separately requires and persists the local `source_html_hash`. Until the local resolver consumes this identity, domestic tables **degrade to quote/section**. | `tables.py`, `section_parser.py`, `concept.py:1552` |
| E4 | Fail-closed | **Hard precondition**: no exact table citation object is constructed unless the reader identity has `source_html_hash` and the parsed-value source proves the same `accession` + `primary_document_url`/filing URL + compatible CIK/form/period. Missing or mismatched identity → degrade, tested at the resolver boundary. | the wrong-filing path |
| E5 | Mismatch surface | Parsed authoritative; mismatch logged silently (v1 diagnostic). | — |

> **The genuinely-yours call — DECIDED 2026-05-29 → (A) bounded + disclosed.** Accept Codex's already-built posture (visible-sections-only, **no dwell-time**, attached-to-turn, self-labeling audit manifest) over the strict strip — it serves F156's auditability goal, and the worst surveillance signal (dwell) is excluded. v2's original "strip everything" was over-rotated; corrected. **Only remaining D work: user-facing disclosure if/when the read-trail is surfaced in the multi-user product.** D is otherwise implemented.

---

## Wave D — Perceptual bridge (v2) · IMPLEMENTED (posture A) — remaining: disclosure-if-surfaced

**Job.** Tell the agent which section is in view, via a **bounded, self-disclosing** read-trail (no dwell-time).

**Mechanism (as-built).** Section-presence + scroll computed in `SourceHtmlPane.tsx:~860` via scroll/resize listeners; `DocumentViewportContext` carries `current_section`, `visible_sections`, `scroll`, `observed_at`, and a self-declaring `audit` manifest (`scope: 'visible_sections_only'`, `persistence: 'attached_to_research_turn'`, `dwellTimeMsRecorded: false`). Threaded into `document_context`, persisted with the research turn. Lives in the DOM host (`SourceHtmlPane`), consistent with the lint boundary.

**Decided posture (A):** bounded + disclosed, not stripped — dwell excluded, scope visible-sections-only, persistence honestly labeled. Serves the auditability goal over a maximal-privacy strip.

**Remaining work (the only open D item):**
1. **User-facing disclosure** before any UI surfaces the read-trail in the multi-user product (the payload self-labels; this is the human-visible surface).
2. Confirm the observer gates on `materialized_identity_verified` (should already).

**Acceptance:**
- Scrolling updates `current_section`; asking with no selection resolves to that section in the prompt.
- `dwellTimeMsRecorded` stays `false`; `scope` stays `visible_sections_only` (assert the audit manifest).
- A disclosure is present if/when the trail is surfaced in UI.
**Tests:** audit-manifest test (scope + no-dwell held); boundary test (L4/L5 cannot read viewport from the iframe).

---

## Wave E — Visual/vision bridge (tables), re-scoped

E is **not one wave**. It is two prerequisites + the bridge. Until the prerequisites land, table selections **degrade to quote/section** (already enforced by `html_mapping.py:452`).

### E-pre-1 — Upstream edgar-financials identity-bound lookup (Edgar_updater, cross-repo) · IMPLEMENTED-CROSS-REPO

**Grounded in the real code (read 2026-05-29):** the foreign path already resolved accession→CIK→primary_document→tables (`edgar_api/routes/tables.py:_fetch_foreign_accession_tables_cache`); the identity helpers existed (`edgar_parser/section_parser.py:_primary_document_url` ~134, accession parsing ~129, `_metadata_from_fetch_result` ~181); but `_read_tables_cache` gated the `filing` identity block to `{proxy,20f,6k}`, and `get_tables_route` + `_build_tables_payload` rejected `accession` for domestic. E-pre-1 removes those gates for the domestic table path.

**E-pre-1a — table identity (primary path, tractable):**
1. **Write filing identity into the domestic tables cache:** include a `filing` block (`accession`, `primary_document_url`, `cik`, `form`/`filing_type`, fiscal `period`). The identity is **already available** — source it from `cached_result["filing"]` / `_get_last_fetched_filing_metadata()` (`section_parser.py:~1167,~5824`), *not* from `_compute_tables_by_section`; it's currently **discarded for domestic** at `~5932` and the `filing`-write is gated to DEF 14A/20-F/6-K at `~5413` — remove both gates. **Field mapping:** Edgar_updater uses `filing_url`; alias/map it to the reader's `primary_document_url`.
2. **Ungate the read:** in `_read_tables_cache`, return the `filing` block for domestic too (drop the `{proxy,20f,6k}` gate).
3. **Accept `accession` for domestic:** relax the `accession requires 20f/6k` checks in `get_tables_route` + `_build_tables_payload`, resolving via the foreign pattern generalized (`lookup_cik_from_ticker` + `section_parser.fetch_recent_form_accessions` → match accession → primary_document → tables). *Minimum without (3):* identity in the response (1+2) lets the caller do **strict returned-filing validation**; (3) is the cleaner direct bind.
- `get_filing_tables` is E's **primary** value source (cell-addressable `table_id`→row, now identity-carrying).

**E-pre-1b — statement/metric identity (secondary, deferrable):** `get_statement` is period-keyed (year+quarter / period range), aggregates XBRL concepts, and has **no accession param + no per-filing identity** (`edgar_api/routes/concept.py`). Per-filing identity for aggregated statements is a later refinement; **E's MVP does not depend on it** — table-cell citation goes through `get_filing_tables` (E-pre-1a). Where E would use a statement/metric value and cannot prove the source filing, it **degrades**.

**Acceptance:** a domestic 10-K/10-Q `get_filing_tables` response carries the resolved filing's `accession`/`primary_document_url`/`cik`/`form`/`period`; with accession input, a non-matching accession returns an error (not a best-effort table); the caller can verify returned identity against the rendered filing.

**As-built (2026-05-29):** domestic 10-K/10-Q table caches write/read the `filing` identity block, `/api/tables` accepts domestic `accession`, validates it against the resolved cache filing identity, and fails closed with `filing_identity_mismatch` or `filing_identity_unavailable` when identity cannot be proven. Legacy table caches without filing identity are not retroactively verified. Verified table identity requires accession, filing/primary-document URL, CIK, form, and a period signal. The MCP `get_filing_tables` proxy forwards domestic `accession`. E-pre-1b statement/metric identity remains deferred; E's MVP table citation path uses `get_filing_tables`.

### E-pre-2 — Registry + artifact table-cell provenance (this repo) · IMPLEMENTED

**Authority model:** table exactness is not a browser-minted corpus mapping. The browser/ReaderBridge can submit a table/cell localization candidate, but the backend table resolver is the authority that combines verified reader identity, identity-bound Edgar_updater table data, parsed-value provenance, and the artifact/registry guard. Exact table evidence must carry a server-issued authority id (`table_citation_record_id` or the eventual registry-equivalent), not just a client-provided `table_context`.

- **Anchor/artifact schema:** the citeable table-cell anchor/provenance shape is `filing_table_cell`. The provenance block includes `table_id`, section, `row_index`/`column_index` + `row_header`/`column_header`, `table_value_source` (`edgar_financials_table|edgar_statement|xbrl_fact`), value-source filing identity (`accession`/`primary_document_url` or `filing_url`/`cik`/`form`/`period`), the reader-local `source_html_hash`, **exact numeric value string** + unit/scale/period/concept, resolver version, mismatch diagnostics, and a server-issued `table_citation_record_id`.
- **`reader_artifacts.py` + `reader_table_citations.py`:** table provenance now round-trips through persistence and evidence registration only after a trusted server resolver result supplies parsed-source provenance and server authority validates same filing, same reader `source_html_hash`, same raw cell text, and exact matching table context. Client-only, authority-shaped, or mismatched table provenance fails closed for exact/high evidence.
- **`html_mapping.py:452` / registry path** currently rejects `content_type=='table'`. Keep rejecting table records lacking server-authorized table-cell provenance. If table citations remain inside the mapping registry, table records must be a distinct authority path inside that registry, not ordinary prose corpus-offset mappings.

**Acceptance:** a server-authorized table-cell anchor with full provenance round-trips through artifact persistence and evidence registration as exact/high table evidence; the same shape without server-issued authority degrades; ordinary `content_type=='table'` mapping records without provenance still fail closed; the provenance shape matches what `get_filing_tables` returns (E-pre-1a) and what E (the bridge) submits as a candidate.

### E — the bridge (gated on E-pre-1a + E-pre-2) · IMPLEMENTED-MVP
**Mechanism (on-demand):** analyst invokes the Table action on a visible filing table-cell selection → `ReaderBridge` / `SourceHtmlPane` captures the rendered table region + selected cell position from the same-origin DOM (no persisted pixels) → submit that localization as a candidate to the backend resolver → **resolve via `get_filing_tables`** (E-pre-1a) for the reader's filing, then **verify** returned filing identity matches the reader's `accession`/`primary_document_url` or equivalent `filing_url`; require the reader-local `source_html_hash` before authority is minted → build server-authorized **table provenance** (`table_value_source`, value-source filing identity, reader source HTML hash, `table_id`/section/row/col + headers + raw cell text, **parsed value as exact numeric string** (never JS float, never browser/vision's number), unit/scale/period/concept, resolver version, mismatch diagnostics, authority id) → register via E-pre-2.
**Fail-closed (E4):** if any reader identity field (`accession`, `primary_document_url`, `source_html_hash`) or value-source identity field needed for same-filing proof is missing/mismatched, **no exact table citation object is constructed** — degrade to quote/section. Enforced at the resolver boundary, with a test.
**Vision/browser is localization only:** the cited number is always the parsed value; neither browser DOM nor vision supplies it (alignment-not-drift). On disagreement: trust parsed, log mismatch. For HTML tables the MVP uses DOM localization; vision/OCR remains a future explicit helper for charts/images/ambiguous non-DOM regions.
**Cost (E1):** on-demand only; cache localization per `(table_id, source_html_hash)` once durable table authority storage replaces the local authority primitive.

**Acceptance:**
- A domestic table-cell read either returns a **same-accession** parsed value with server-issued provenance + restorable overlay, or **degrades** with a diagnostic — never a wrong-filing or vision-sourced number.
- Server-issued provenance round-trips through E-pre-2 to an exact citation; absent server authority, the table guard still blocks.
- Browser/vision localization fires only on explicit invocation; no automatic table scanning.
**Tests:** identity mismatch → degrade; missing identity fields → no citation constructed (resolver-boundary test); rendered-candidate mismatch → no exact table citation; provenance → exact citation via server authority; overlay restore after resize/scroll.

---

## 2. Sequencing & cleanup

- **D** ships as the bounded/disclosed read-trail already in the tree (posture A) — **not** a pare-back. The only remaining D item is **user-facing disclosure if/when the trail is surfaced** in the multi-user product.
- **E** now has an MVP local bridge/resolver: **E-pre-1a (Edgar_updater table identity) + E-pre-2 (registry/artifact provenance) → E (bridge)**. E-pre-1b (statement/metric identity) is deferred because E's MVP resolves through `get_filing_tables`. Exact table citation remains a multi-step flow; until the resolver proves same-filing table identity and mints server authority, tables degrade.
- **Parent docs reconciled:** `F156_READER_IMPLEMENTATION_PLAN.md`, `F156_READER_SYSTEM_ARCHITECTURE.md`, and the anchor detail in `F156_SEC_HTML_READER_ARCHITECTURE_SPEC.md` should reflect this accepted split before Wave E implementation resumes.
