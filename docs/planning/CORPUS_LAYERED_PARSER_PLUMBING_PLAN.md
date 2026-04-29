# Corpus — Layered Parser `(cik, accession, sec_headers)` Plumbing

## Status: ABANDONED 2026-04-28 — solved the wrong problem; replaced by `CORPUS_EDGAR_API_INTEGRATION_PLAN.md`

The R3-PASS plan was implemented (commit `858b4e9b`) and immediately reverted (commit `a0b31678`) when post-merge runtime testing surfaced a P0 architectural anomaly: corpus calls `edgar_parser` via direct Python import, but the importable `edgar_parser` is the frozen public PyPI v0.3.0 (28KB `section_parser.py`) — NOT the Phase 3+4 dev version in `Edgar_updater/edgar_parser/` (84KB). The Edgar_updater team explicitly froze the public Python package 2026-04-13 and went **API-only at edgarparser.com**. Direct Python import was the wrong integration model from the start; this plan extended that anomaly instead of fixing it.

The right architecture is: corpus calls `/api/sections` over HTTP, never imports `edgar_parser` Python. See replacement plan `CORPUS_EDGAR_API_INTEGRATION_PLAN.md`.

What this plan correctly produced (kept for historical record):
- 3 Codex review rounds (R1 FAIL → R2 FAIL → R3 PASS) — review process worked, but reviewers stayed in repo scope per filesystem boundary and didn't probe live runtime imports
- 6 useful test cases that survive into the new plan (mock HTTP instead of mock parser)
- Edge case enumeration, NULL/whitespace normalization patterns

Lesson: when a plan touches an integration boundary (Python import / HTTP API / MCP / CLI), explicitly verify live runtime behavior against the actual deployed dependency, not just the source code in the dev repo. The `core/corpus/filings.py::_load_edgar_section_parser` sys.path fallback hid the issue because `edgar_parser` was always importable from the public package, so the fallback never fired.

## Status (original plan content below): v3 — addresses Codex R2 FAIL (1 P1 + 1 P2) on 2026-04-28

Forward-compat plumbing for `core/corpus/filings.py::parse_filing_sections` wrapper to thread `(cik, accession, sec_headers)` to upstream `edgar_parser.section_parser.parse_filing_sections`. Track 3 of `CORPUS_PRE_PHASE1_HARDENING_PLAN.md` v2.

**Forward-compat only.** Upstream parser currently `del sec_headers` immediately at `Edgar_updater/edgar_parser/section_parser.py:319`; `cik`/`accession` are used only to compose a shadow-validation `filing_key` at line 404. So this change adds NO functional behavior today. It exists to:

1. Match the upstream parser's reserved kwarg interface (signature already accepts these per Phase 3 ship).
2. Be ready when Phase 5 unpauses (currently paused 2026-04-27 with re-trigger conditions; none corpus-driven today).
3. Lock the wrapper signature so any future caller that adds the kwargs gets them threaded for free.

**Not in this plan:** bridge `scripts/corpus_ingest_accession.py`. Bridge calls `get_filing_sections` → `get_filing_sections_cached` (a different upstream entry point that does NOT accept these kwargs and won't until Phase 5 §3 ships per the `c851b60` → DUPLICATE-OF-PHASE-5-§3 trace in Edgar_updater TODO). Bridge stays as-is.

## Goal

Corpus wrapper at `core/corpus/filings.py::parse_filing_sections` accepts `(cik, accession, sec_headers)` keyword arguments (default `None`) and threads them through to the upstream parser. The single internal caller (`filings_source_excerpt` at line 141) extracts `cik` + `source_accession` from the existing `documents` row and passes them along with a `sec_headers` dict built from the existing `SEC_USER_AGENT` constant.

## Context

**Pre-conditions (verified):**

- `core/corpus/filings.py:11` already imports `SEC_USER_AGENT` from `core.corpus.edgar_urls`.
- `_fetch_filing_html` at `core/corpus/filings.py:289` already receives the full `documents` row (which includes `cik` + `source_accession`).
- Upstream `edgar_parser.section_parser.parse_filing_sections` signature accepts the 3 kwargs since Phase 3 layered architecture ship (`Edgar_updater` 2026-04-25, commit `4eebf0a`):
  ```python
  def parse_filing_sections(
      html_content: bytes | str,
      filing_type: str,
      *,
      cik: str | None = None,
      accession: str | None = None,
      sec_headers: dict | None = None,
  ) -> dict
  ```
- Current corpus wrapper `core/corpus/filings.py:203-216`:
  ```python
  def parse_filing_sections(html_content: bytes | str, filing_type: str) -> dict:
      parser = _load_edgar_section_parser()
      return parser.parse_filing_sections(html_content, filing_type)
  ```
- The `documents` table schema at `core/corpus/schema.sql:3,13` carries `cik TEXT` and `source_accession TEXT` per row; both `NULL`-able. Phase 0 ingestion populates them for SEC filings. May be `NULL` for legacy migrated docs or non-SEC sources.

**No-op characterization upstream (verified at `Edgar_updater/edgar_parser/section_parser.py`):**
- Line 319 (`_parse_filing_sections_with_context`): `del sec_headers` — discarded immediately.
- Line 404: `filing_key = f"{cik or ''}_{accession or ''}".strip("_") or None` — only consumed by the opt-in `EDGAR_SHADOW_VALIDATION_*` env-flag gate; diagnostic, not a parser layer.
- No L2 emitter exists; `xbrl_role` source string is referenced in arbitrator weights/tie-breakers but no emitter creates `xbrl_role` candidates.

So threading these kwargs today produces **no normal-output behavior change with shadow validation disabled** (the default). This is intentional — we're forward-compatting. *Caveat:* when the `EDGAR_SHADOW_VALIDATION_*` env flag IS set, `cik`+`accession` feed `filing_key` at line 404 for the shadow validator's gating — diagnostic only, doesn't affect parser output, but does change which filings the shadow validator runs on.

## Scope

### In scope

- Wrapper signature change at `core/corpus/filings.py::parse_filing_sections` (line 203).
- Single callsite update at `core/corpus/filings.py::filings_source_excerpt` line 141 to pass `cik` + `accession` from the existing row + `sec_headers` from `SEC_USER_AGENT`.
- Unit tests asserting kwargs are threaded; default-None paths still work; missing-on-row paths gracefully no-op.
- Existing test regression check.

### Out of scope

- Bridge `scripts/corpus_ingest_accession.py` — uses `get_filing_sections` not `parse_filing_sections`; cached path doesn't accept these kwargs upstream.
- New corpus schema fields (`source`, `confidence` on sections — Bucket C work).
- Surfacing parser response's new fields (`state`, `declaration_type`, `source`, `confidence`) in `SearchHit` — Bucket C.
- Validating that the threaded kwargs change parser output (they won't — no L2 emitter exists today).

## Touch points

| File | Line | Change |
|---|---|---|
| `core/corpus/filings.py` | 203-216 | Extend `parse_filing_sections` wrapper signature with 3 kwargs; thread to upstream call. |
| `core/corpus/filings.py` | 141 (callsite in `filings_source_excerpt`) | Extract `cik` + `accession` from the resolved row; build `sec_headers={'User-Agent': SEC_USER_AGENT}`; pass to wrapper. |
| `tests/test_filings_tools.py` | new test class | Mock upstream, assert kwargs threaded; mock None-row, assert defaults. |

No other corpus file is affected. `SEC_USER_AGENT` is already imported. `_fetch_filing_html` does NOT need a signature change — it already has the row.

## Code changes

### 1. Wrapper signature (line 203-216)

**Before:**
```python
def parse_filing_sections(html_content: bytes | str, filing_type: str) -> dict:
    parser = _load_edgar_section_parser()
    return parser.parse_filing_sections(html_content, filing_type)
```

**After:**
```python
def parse_filing_sections(
    html_content: bytes | str,
    filing_type: str,
    *,
    cik: str | None = None,
    accession: str | None = None,
    sec_headers: dict | None = None,
) -> dict:
    parser = _load_edgar_section_parser()
    return parser.parse_filing_sections(
        html_content,
        filing_type,
        cik=cik,
        accession=accession,
        sec_headers=sec_headers,
    )
```

### 2. Callsite in `filings_source_excerpt` (around line 141)

**Before** (existing flow, lines 140-141):
```python
html_content = _fetch_filing_html(row)
parsed = parse_filing_sections(html_content, normalized_form_type)
```

**After:**
```python
html_content = _fetch_filing_html(row)
row_cik = row['cik']
row_accession = row['source_accession']
parsed = parse_filing_sections(
    html_content,
    normalized_form_type,
    cik=(str(row_cik).strip() or None) if row_cik else None,
    accession=(str(row_accession).strip() or None) if row_accession else None,
    sec_headers={'User-Agent': SEC_USER_AGENT},
)
```

`SEC_USER_AGENT` is already imported at line 11. `row` is a `sqlite3.Row` — column access by name works. **NULL/whitespace handling:** outer `if row_cik else None` guards NULL/empty-string at column level; inner `.strip() or None` drops surrounding whitespace while preserving leading zeroes (CIKs are zero-padded 10-digit; accession numbers contain hyphens). Net result: any non-content value (NULL, "", "  ") becomes `None`; valid content passes through trimmed. `sec_headers` is passed unconditionally because the User-Agent string is always available; even though upstream `del`s it, passing the dict matches the documented forward-compat shape.

### 3. No changes elsewhere

- `_fetch_filing_html` (line 289) — unchanged; already receives row.
- `_load_edgar_section_parser` (line 208) — unchanged; just imports the upstream module.
- All other `parse_filing_sections` callers — Codex R1 ripgrep confirmed only one external callsite of `core.corpus.filings.parse_filing_sections` (the `filings_source_excerpt` callsite at line 141, plus the wrapper itself). The unrelated `core/corpus/section_map._parse_filing_sections_raw` is a different function with a different signature; no conflict.

## Tests

### New test cases (in `tests/test_filings_tools.py`)

1. **`test_parse_filing_sections_threads_kwargs`** — mock `edgar_parser.section_parser.parse_filing_sections`; call corpus wrapper with all 3 kwargs; assert mock received them by keyword with the exact values passed.

2. **`test_parse_filing_sections_defaults_to_none`** — call corpus wrapper without kwargs; assert mock received `cik=None, accession=None, sec_headers=None`. Backward-compat assertion.

3. **`test_filings_source_excerpt_threads_row_context`** — mock the upstream parser; ingest a synthetic doc via `tests/_corpus_helpers.py` with `cik="0000789019"`, `source_accession="0001628280-25-..."`, AND `source_url_deep="https://www.sec.gov/..."` (or mock `_fetch_filing_html` to bypass the live HTTP fetch); call `filings_source_excerpt(document_id=...)`; assert the upstream parser received `cik="0000789019"`, `accession="0001628280-25-..."`, `sec_headers={'User-Agent': SEC_USER_AGENT}`.

4. **`test_filings_source_excerpt_handles_null_cik`** — synthetic doc with `cik=None`, `source_accession="0001628280-25-..."`, AND `source_url_deep` populated (NULL `cik` is a legacy-migrated case; `_fetch_filing_html` falls back to `source_url_deep` when cik is missing — the row MUST have `source_url_deep` populated or the test will fail in `_fetch_filing_html` BEFORE kwargs threading is exercised). Call `filings_source_excerpt`; assert upstream received `cik=None`. Confirms graceful no-op for cik specifically.

5. **`test_filings_source_excerpt_handles_null_accession`** — same fixture shape as #4 with `source_accession=None` instead. Requires `source_url_deep` populated for the same reason.

6. **`test_filings_source_excerpt_normalizes_whitespace`** — Phase 0 helpers will reject whitespace-padded CIK/accession at frontmatter validation (per Codex R2: `core/corpus/frontmatter.py` requires `cik` to match `\d{10}` exactly). Workaround: ingest a valid row first via Phase 0 helper, then bypass frontmatter and update the SQLite row directly:
   ```python
   ingest_filing(..., cik="0000789019", source_accession="0001628280-25-000001", ...)
   db.execute("UPDATE documents SET cik = ?, source_accession = ? WHERE document_id = ?",
              ("  0000789019  ", "  0001628280-25-000001  ", document_id))
   db.commit()
   ```
   Then call `filings_source_excerpt(document_id=...)`; assert upstream parser received trimmed values `cik="0000789019"`, `accession="0001628280-25-000001"`. Confirms `.strip() or None` normalization works at the wrapper layer (frontmatter validation is the upstream guard, but corpus shouldn't trust DB-level invariants — direct SQL writes, migration scripts, or future schema relaxations could allow whitespace).

### Existing test that MUST be updated (Codex R1 [P1])

`tests/test_filings_tools.py::test_filings_source_excerpt_document_id` (and any other test in the file that monkeypatches `parse_filing_sections`) currently uses a 2-arg lambda:
```python
monkeypatch.setattr(filings_module, "parse_filing_sections", lambda html, filing_type: ...)
```

The new callsite passes 3 additional keyword args, which the 2-arg lambda will reject with `TypeError: <lambda>() got an unexpected keyword argument 'cik'`. Update each such monkeypatch to one of:

- **(a) Permissive shape:** `lambda html, filing_type, **kwargs: ...` — accepts new kwargs without asserting on them. Lowest-touch fix; preserves test's existing scope.
- **(b) Deliberate assertion shape:** `def fake_parser(html, filing_type, *, cik=None, accession=None, sec_headers=None): ... ; monkeypatch.setattr(...)` — asserts on the new kwargs. Strictly better but more code per call.

Recommended: option (a) for tests that don't care about the kwargs; option (b) for any new test where the threading is the assertion.

**Implementation must find every monkeypatch BEFORE editing — no silent miss.** The `setattr(` call and the `parse_filing_sections` target are on SEPARATE lines (per Codex R2), so a single-line grep misses the match. Use a multiline ripgrep:

```bash
rg -n -U "monkeypatch\.setattr\([\s\S]*?parse_filing_sections" tests/test_filings_tools.py
```

Or, more permissively:

```bash
rg -n "parse_filing_sections" tests/test_filings_tools.py
```

The simpler version returns more noise (every reference) but guarantees no missed monkeypatches. Per Codex R2 there is at least one affected monkeypatch at `tests/test_filings_tools.py:78`.

### Regression check

After the existing-test updates above, `pytest tests/test_filings_tools.py -v` must pass clean. The only test changes should be to monkeypatch shapes; no logical assertions should change.

### Live smoke (post-merge, manual — NOT a test)

After merge, run live `filings_source_excerpt` against an existing canary ticker (e.g., MSFT 10-K Item 7) — should return text identically to pre-change behavior. No XBRL anchoring change expected (L2 not wired upstream). Confirms no regression in the live path.

## Edge cases

| Case | Behavior |
|---|---|
| Row has `NULL` cik | `cik=None` passed to upstream; current upstream behavior unchanged. |
| Row has `NULL` source_accession | Same as above. |
| Row has both `NULL` | Same — wrapper passes both as None. Equivalent to today's no-context call. |
| Row has whitespace in cik or accession (e.g., `"  789019  "`) | `.strip() or None` trims; passes clean string to upstream. |
| Row has only-whitespace cik (e.g., `"   "`) | Outer guard treats truthy string as content → enters `.strip() or None` → empty string → `or None` → `None` passed. |
| `sec_headers` always populated | Yes — `SEC_USER_AGENT` is a module-level constant, never None. Upstream `del`s it anyway. |
| Backward-compat for callers not passing kwargs | All keyword-only with default `None`; existing positional calls work unchanged. |
| Caller passes `sec_headers` as wider dict (future) | Wrapper passes through unchanged; upstream signature accepts `dict | None`. |
| `EDGAR_SHADOW_VALIDATION_*` env flag set | `cik`+`accession` now reach `filing_key` at upstream line 404. Doesn't change parser output, but does change which filings the shadow validator runs on. Acceptable — operators who set the flag opt into this. |

## Validation

- Plan-first per CLAUDE.md: this draft → Codex review → PASS → implement via Codex.
- Implementation gate: 5 new tests + existing tests pass.
- Smoke gate: live `filings_source_excerpt` returns existing canary content unchanged.
- No prod deploy concern — change is internal to `core/corpus/filings.py`, no schema migration, no MCP surface change.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| `sqlite3.Row` column access by name fails | low | Existing callsite in `_fetch_filing_html` uses identical pattern (`row['cik']`, `row['source_accession']`); confirms column accessor works with current Row factory. |
| Upstream parser raises on unexpected kwarg shape | low | Verified upstream signature accepts `dict \| None` for sec_headers; `str \| None` for cik/accession. Defaults to `None`. |
| `SEC_USER_AGENT` import becomes circular | low | Already imported in `filings.py:11`; no new module dependency. |
| Wrapper signature change breaks an external caller | low | Grep confirms only `filings_source_excerpt` calls this wrapper; no external import. Adding keyword-only kwargs with defaults is non-breaking even if external callers existed. |
| Mock-based tests drift from upstream signature | med | Test mocks the corpus wrapper's call to upstream — assert by-keyword to fail fast if upstream signature ever changes. |
| Forward-compat ships, then Phase 5 ships with different kwarg names/shape | low | Phase 5 plan v3 PASS already specifies the same kwargs. If Phase 5 v4 changes shape during unpause, this plumbing is one wrapper edit + signature change away from realignment. |

## Open questions — resolved by Codex R1

1. **`sec_headers` shape:** ✓ Codex confirmed `{'User-Agent': SEC_USER_AGENT}` matches existing `httpx.get(..., headers=...)` shape in `core/corpus/edgar_urls.py`. No `Accept` dependency. Minimal header is correct; widen only if Phase 5 unpauses with more requirements.

2. **Pass `sec_headers=None` vs populated dict:** keep populated. Matches forward-compat shape; allocation cost negligible.

3. **Surface Phase 4 fields (`state`, `declaration_type`, `source`, `confidence`) in corpus today:** ✓ Codex confirmed defer to Bucket C — out of scope here.

4. **Test fixture realism:** ✓ Codex confirmed use Phase 0 helpers (`tests/_corpus_helpers.py`) for callsite tests #3-6. Mocks sufficient for tests #1-2.

## References

- `docs/planning/CORPUS_PRE_PHASE1_HARDENING_PLAN.md` v2 Track 3 — parent milestone
- `docs/planning/CORPUS_ARCHITECTURE.md` §5.1 — SearchResponse envelope (no change)
- `Edgar_updater/edgar_parser/section_parser.py:449-466` — upstream `parse_filing_sections` signature (accepts kwargs since Phase 3)
- `Edgar_updater/edgar_parser/section_parser.py:310-321` — `_parse_filing_sections_with_context` `del sec_headers` (today's no-op)
- `Edgar_updater/docs/plans/PLAN-section-parser-phase5-xbrl-refinement.md` v3 — paused 2026-04-27, threading lands when this unpauses
- `Edgar_updater/docs/TODO.md` — closed-as-duplicate trace for cached-path threading (`c851b60` → Phase 5 §3)
- v1 of this plan: commit `086d806b` (Codex R1 FAIL: 1 P1 + 5 P2)
- v2 of this plan: commit `ae4319f2` (Codex R2 FAIL: 1 P1 + 1 P2)

## v2 → v3 changelog (Codex R2 fixes)

- **[P1] Mandated grep was wrong.** `setattr(` and `parse_filing_sections` are on separate lines, so `grep ... setattr.*parse_filing_sections` returns 0 matches. v3 replaces with multiline ripgrep `rg -n -U "monkeypatch\.setattr\([\s\S]*?parse_filing_sections"` OR a permissive `rg -n "parse_filing_sections"` fallback. Confirmed monkeypatch site exists at `tests/test_filings_tools.py:78`.
- **[P2] Test #6 (whitespace) infeasible as written.** Phase 0 helpers reject whitespace at frontmatter validation (`core/corpus/frontmatter.py` requires `cik` to match `\d{10}` exactly). v3 reworks test to ingest a valid row first via helpers, then UPDATE the SQLite row directly to inject whitespace. Test asserts wrapper-layer normalization is robust against future schema relaxations or direct DB writes that bypass frontmatter validation.

## v1 → v2 changelog (Codex R1 fixes)

- **[P1] Existing test breakage:** new "Existing test that MUST be updated" subsection in Tests; explicit grep step + 2 fix-shape options (`**kwargs` permissive vs deliberate-assertion); appendix step 3 added.
- **[P2] "No observable behavior change" softened** to "no normal-output change with shadow validation disabled"; shadow-validator caveat added in Context + Edge cases.
- **[P2] NULL test fixtures must preserve `source_url_deep`** — explicit note in tests #4 + #5.
- **[P2] Whitespace normalization** — code change §2 now uses `(str(value).strip() or None) if value else None`; new edge cases for whitespace + only-whitespace; new test #6 `test_filings_source_excerpt_normalizes_whitespace`.
- **[P2] Grep claim wording** — clarified `section_map._parse_filing_sections_raw` is unrelated; only one external callsite of corpus wrapper.
- **[P2] sec_headers shape** — confirmed correct; open question resolved.
- **Open questions section** — moved from "for Codex" to "resolved by Codex R1" with all 4 answers locked.

---

## Appendix — implementation checklist (for Codex implementer)

1. Edit `core/corpus/filings.py:203-216` — extend signature + thread kwargs (per "Code changes §1" above).
2. Edit `core/corpus/filings.py:140-141` — extract row context + pass kwargs to wrapper using `(str(value).strip() or None) if value else None` normalization (per "Code changes §2" above).
3. **Find + update existing monkeypatches of `parse_filing_sections`:** run multiline ripgrep `rg -n -U "monkeypatch\.setattr\([\s\S]*?parse_filing_sections" tests/test_filings_tools.py` first (per Codex R2 — single-line grep misses the multi-line setattr call); for each match, change the lambda/function to accept `**kwargs` (option (a) in Tests section) or to assert deliberately on the new kwargs (option (b)). At minimum: `test_filings_source_excerpt_document_id` (line 78 per Codex R2) requires this update per Codex R1 [P1].
4. Add 6 new test cases per "Tests" section above to `tests/test_filings_tools.py` (note: count went from 5 → 6 in v2; added `test_filings_source_excerpt_normalizes_whitespace`).
5. Run `pytest tests/test_filings_tools.py -v` — all new + updated existing tests green.
6. Run `pytest tests/test_filings_*.py tests/test_corpus_*.py -v` — broader regression check across all corpus tests.
7. (No deploy step — internal change only.)
8. Commit with message: `feat(corpus): forward-compat plumbing for parse_filing_sections (cik, accession, sec_headers) — Track 3 of pre-Phase-1 hardening`
