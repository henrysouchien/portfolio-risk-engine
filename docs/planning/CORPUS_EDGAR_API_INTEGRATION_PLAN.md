# Corpus → Edgar API Integration

## Status: v8 — addresses Codex R7 FAIL (1 P1 + 1 P2) on 2026-04-28

Replaces `CORPUS_LAYERED_PARSER_PLUMBING_PLAN.md` (abandoned). Switches corpus's edgar integration from direct Python imports of `edgar_parser` to HTTP calls against `/api/sections` and `/api/filings` at edgarparser.com.

This is the corrected Track 3 of `CORPUS_PRE_PHASE1_HARDENING_PLAN.md` v2.

## Why this plan exists

Public Python `edgar_parser` package frozen at v0.3.0 (2026-04-13); Phase 3+4 work shipped only at edgarparser.com. Direct Python import from corpus picks up the frozen v0.3.0 (28KB `section_parser.py`), NOT the dev version (84KB) with Phase 3+4. Original Track 3 plumbing (commit `858b4e9b`, reverted at `a0b31678`) extended the wrong integration model. This plan switches to HTTP API.

## Investigation summary (2026-04-28)

Verified live against `https://www.financialmodelupdater.com` with paid-tier key:

- **`/api/sections`** is the working endpoint for parsed sections. Takes `(ticker, year, quarter, sections, format, source, max_words)`. **Top-level response shape includes `status: "success"` (or `"error"` with `message`)** plus `filing_type`, `sections_found/absent/missing/unavailable`, `declared_sections`, `parser_path`, `sections: {<id>: {header, state, text, tables, word_count, source, confidence}}`, `metadata`, `cache_version`. `tables` is a list of pre-formatted markdown-table strings. State `missing` means parser couldn't find it (still HTTP 200 with `status: success` at top level — bridge needs the in-body status check separately from the HTTP-status check).
- **`/api/filings`** returns filing list with `accession`, `filing_date`, `url`, `form` per entry — exact match for old `edgar_parser.tools.get_filings()` shape.
- **`/api/filing/document`** works with paid key BUT has a known cache-poisoning bug (filed in `Edgar_updater/docs/TODO.md`): returns `filing.accession=null` when `_markdown.json` cache built before `_filings.json`. **Don't use it.**
- **No accession-keyed endpoint exists** anywhere. All routes take `(ticker, year, quarter)`. API caches/returns "latest matching filing in quarter."
- **API `header` field exactly matches `_EDGAR_CORPUS_HEADER_TO_ID` keys** (e.g., `"Part I, Item 1. Financial Statements"` for canonical id `part1_item1`). So body assembly uses API's `header` directly — no inverse-mapping table needed.
- **Today's bridge body format** (from `Edgar_updater/edgar-parser/edgar_parser/section_parser.py::_write_sections_markdown`): `## SECTION: <header>\n**Word count:** N\n<text>\n### TABLES\n<table>\n---\n` repeated per section. New body assembly must match for round-trip parity with the markdown convention `core/corpus/section_map.py::_parse_filing_sections_raw` consumes.
- **JPM 10-Q 2025Q3 `part1_item1` is silently absent** from `declared_sections`/`sections_found`/`sections_missing` (Phase 4 money-center bank TOC bug, separate Edgar_updater follow-up). Asking explicitly via `?sections=part1_item1` returns `state=missing` with empty text — easy to detect.
- **Bridge fiscal_period for 8-K is `YYYY-Qn`** (per `corpus_ingest_accession.py::compute_fiscal_period`), NOT `YYYY-MM-DD`. Schema CHECK constraint allows date format too but bridge doesn't write it.

## Goal

Corpus retrieves filing section text via HTTP `/api/sections` (with `/api/filings` pre-flight for accession alignment). No `edgar_parser` Python imports anywhere in `core/corpus/` or `scripts/corpus_ingest_accession.py`. Local `_fetch_filing_html`, `parse_filing_sections`, `_load_edgar_section_parser` paths removed.

## Scope

### In scope

- New `core/corpus/edgar_api_client.py` — HTTP client wrapping `/api/sections` and `/api/filings`.
- Add inverse mapping helper in `core/corpus/section_map.py` (`edgar_id_to_corpus_header(canonical_id, form_type) -> str | None`) for body assembly.
- Update `core/corpus/filings.py::filings_source_excerpt` to call new client + add `/api/filings` pre-flight for accession alignment.
- Extend `_FILING_SOURCE_LOOKUP_COLUMNS` AND the inline SELECT at `_resolve_filing_document_row` line 269 to include `ticker` and `fiscal_period`.
- Update `scripts/corpus_ingest_accession.py` to call new client; add body-assembly helper that produces canonical markdown matching today's format.
- Delete `_fetch_filing_html`, `parse_filing_sections` wrapper, `_load_edgar_section_parser` from `core/corpus/filings.py`.
- Delete `import sys`, `import httpx`, and `SEC_USER_AGENT`/`fetch_primary_document_html` import from `core/corpus/filings.py`.
- Tests: new `tests/test_edgar_api_client.py`; update existing mocks in `tests/test_filings_tools.py` and `tests/test_corpus_ingest_accession.py`.

### Out of scope — parked

- `core/corpus/edgar_urls.py` — keep as-is. `SEC_USER_AGENT` and `fetch_primary_document_html` still pass their own tests; orphaned only at the corpus-callsite level. Delete in a separate cleanup pass if/when confirmed truly unused.
- Phase 4 fields surfaced in `SearchHit` (`source`, `confidence`, `state`, `declaration_type`) — Bucket C work.
- Source-excerpt for amendments (10-K/A, 10-Q/A) and same-day multi-8K — F43 territory; the pre-flight check will fail loudly for these cases (acceptable per F43 deferral).
- 8-K bridge ingest with `--source 8k` — supported in plumbing (passes `source="8k"` to API) but not Phase-1-validation-blocking.
- `tables_structured` top-level field surfacing — not used today; keep simple body assembly.
- Markdown↔HTML offset map (F44).

### Deliberately rejected

- `/api/filing/document` for source-excerpt accession alignment — rejected because of the known cache-poisoning bug (returns `accession=null` in the documented failure mode). Pre-flight via `/api/filings` is more robust.
- Caching at corpus layer — API has its own cache.
- Retry/backoff in client — fail-fast; revisit if rate limits become operational pain.

## Touch points

| File | Change |
|---|---|
| `core/corpus/edgar_api_client.py` (new) | `get_filing_sections`, `get_filings`, `EdgarAPIError`, `_config()`. ~120 LOC. |
| `core/corpus/section_map.py` | Add `edgar_id_to_corpus_header(canonical_id, form_type) -> str \| None` (inverse of `corpus_header_to_edgar_id`). ~10 LOC. |
| `core/corpus/filings.py` | Delete `_fetch_filing_html`, `parse_filing_sections`, `_load_edgar_section_parser`. Delete `import sys`, `import httpx`, `from core.corpus.edgar_urls import SEC_USER_AGENT, fetch_primary_document_html`. Extend `_FILING_SOURCE_LOOKUP_COLUMNS` + inline SELECT (line 269) to include `ticker, fiscal_period`. Update `filings_source_excerpt` body. Add `_resolve_api_params_from_row` helper. Add accession pre-flight via `/api/filings`. |
| `scripts/corpus_ingest_accession.py` | Delete `from edgar_parser.tools import ...`. Add `from core.corpus import edgar_api_client` AND `from core.corpus.edgar_api_client import EdgarAPIError`. **Module-attribute call style required** (`edgar_api_client.get_filings(...)`, `edgar_api_client.get_filing_sections(...)`) — bare-name imports break test mock targets. Replace `get_filings` call (line 151) and `get_filing_sections` call (line 189). Remove `file_path` extraction; keep `status == 'success'` body check (catches HTTP-200-with-in-body-error responses). Add `_assemble_body_from_api_response` helper. |
| `tests/test_filings_tools.py` | Replace `monkeypatch.setattr('core.corpus.filings.parse_filing_sections', ...)` with mock of `core.corpus.edgar_api_client.get_filing_sections`. Replace `monkeypatch.setattr('core.corpus.filings.httpx.get', ...)` with mock of `core.corpus.edgar_api_client.get_filings` (for the pre-flight). Existing test fixture pattern preserved. |
| `tests/test_corpus_ingest_accession.py` | Replace mocks of `edgar_parser.tools.get_filings`/`get_filing_sections` with mocks of new client. |
| `tests/test_edgar_api_client.py` (new) | 11 unit tests (see Tests section). |

## Code shape — `core/corpus/edgar_api_client.py`

```python
"""HTTP client for edgar_api at edgarparser.com.

Replaces direct Python imports of edgar_parser. Phase 3+4 parser is
deployed at edgarparser.com; the public PyPI edgar_parser package is
frozen at v0.3.0 (pre-Phase-3+4) and must not be used.
"""
from __future__ import annotations

import os
from typing import Any

import httpx


_DEFAULT_TIMEOUT = 30.0


class EdgarAPIError(Exception):
    """API call to edgar_api failed (network, auth, rate limit, server error)."""


def _config() -> tuple[str, str]:
    base_url = os.getenv("EDGAR_API_URL", "").rstrip("/")
    api_key = os.getenv("EDGAR_API_KEY", "")
    if not base_url or not api_key:
        raise EdgarAPIError(
            "EDGAR_API_URL and EDGAR_API_KEY must be set in environment"
        )
    return base_url, api_key


def _request_json(path: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    base_url, api_key = _config()
    try:
        resp = httpx.get(
            f"{base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise EdgarAPIError(f"network error calling {path}: {exc}") from exc
    if resp.status_code != 200:
        raise EdgarAPIError(
            f"HTTP {resp.status_code} from {path}: {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise EdgarAPIError(f"invalid JSON from {path}: {exc}") from exc


def get_filing_sections(
    ticker: str,
    year: int,
    quarter: int,
    *,
    sections: list[str] | None = None,
    format: str = "full",
    source: str | None = None,
    max_words: int | str | None = None,
    include_tables: bool = False,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "ticker": ticker,
        "year": year,
        "quarter": quarter,
        "format": format,
    }
    if sections:
        params["sections"] = ",".join(sections)
    if source:
        params["source"] = source
    if max_words is not None:
        params["max_words"] = str(max_words)
    if include_tables:
        params["include_tables"] = "true"
    return _request_json("/api/sections", params, timeout=timeout)


def get_filings(
    ticker: str,
    year: int,
    quarter: int,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    return _request_json(
        "/api/filings",
        {"ticker": ticker, "year": year, "quarter": quarter},
        timeout=timeout,
    )


__all__ = ["EdgarAPIError", "get_filing_sections", "get_filings"]
```

## Code shape — `core/corpus/section_map.py` inverse mapping addition

Add at end of file, after `corpus_header_to_edgar_id`:

```python
def edgar_id_to_corpus_header(canonical_id: str, form_type: str) -> str | None:
    """Map Edgar_updater's canonical section id back to the corpus header string.

    Inverse of corpus_header_to_edgar_id. Used by API-response → canonical
    markdown body assembly.
    """
    base_form_type = form_type[:-2] if form_type.endswith('/A') else form_type
    forward = _EDGAR_CORPUS_HEADER_TO_ID.get(base_form_type) or {}
    for header, cid in forward.items():
        if cid == canonical_id:
            return header
    return None
```

(One-line invert. Unit test: every canonical_id in `_EDGAR_CORPUS_HEADER_TO_ID` round-trips back to its original header.)

## Code shape — `filings.py` changes

### Extend lookup columns (line 39-45):

```python
_FILING_SOURCE_LOOKUP_COLUMNS = (
    'document_id',
    'ticker',          # added — needed for API call
    'cik',
    'form_type',
    'fiscal_period',   # added — needed for year/quarter mapping
    'source_url_deep',
    'source_accession',
)
```

### Update inline SELECT in `_resolve_filing_document_row` (line 267-279):

Already produces all needed columns explicitly — just add `ticker, fiscal_period` to the column list. The existing `WHERE ticker = ? AND form_type = ? AND fiscal_period = ?` clause already filters on these; just ensure they're in the SELECT.

### Add `_resolve_api_params_from_row` helper:

```python
def _resolve_api_params_from_row(row: sqlite3.Row) -> tuple[int, int, str | None]:
    """Map a documents row to (year, quarter, source) for edgar_api.

    Handles the 3 fiscal_period formats allowed by schema:
    - 'YYYY-FY' → year, quarter=4, source=None (10-K)
    - 'YYYY-Qn' → year, quarter=n, source=None for 10-Q; "8k" for 8-K
    - 'YYYY-MM-DD' → year, quarter=((month-1)//3)+1, source per form
    """
    form_type = str(row['form_type'])
    fiscal_period = str(row['fiscal_period'] or '').strip()
    base_form = form_type[:-2] if form_type.endswith('/A') else form_type
    source: str | None = '8k' if base_form == '8-K' else None

    if not fiscal_period:
        raise InvalidInputError(f"row missing fiscal_period for form_type {form_type}")

    # Format detection. Schema CHECK constraint allows 3 GLOB patterns but glob
    # cannot validate semantic ranges (e.g., month 00 or 99 would pass the GLOB).
    # Validate aggressively at this boundary.
    try:
        if fiscal_period.endswith('-FY'):
            year = int(fiscal_period[:4])
            return year, 4, source
        if len(fiscal_period) == 7 and fiscal_period[4] == '-' and fiscal_period[5] == 'Q':
            year = int(fiscal_period[:4])
            quarter = int(fiscal_period[6])
            if not 1 <= quarter <= 4:
                raise InvalidInputError(f'invalid quarter {quarter} in {fiscal_period!r}')
            return year, quarter, source
        if len(fiscal_period) == 10 and fiscal_period[4] == '-' and fiscal_period[7] == '-':
            year = int(fiscal_period[:4])
            month = int(fiscal_period[5:7])
            if not 1 <= month <= 12:
                raise InvalidInputError(f'invalid month {month} in {fiscal_period!r}')
            return year, ((month - 1) // 3) + 1, source
    except ValueError as exc:
        raise InvalidInputError(
            f'malformed fiscal_period {fiscal_period!r} for form_type {form_type}: {exc}'
        ) from exc

    raise InvalidInputError(
        f'unsupported fiscal_period format {fiscal_period!r} for form_type {form_type}'
    )
```

### Update `filings_source_excerpt` body (replace lines 140-148):

```python
# Reject amendment forms outright — the API caches "latest in quarter" and
# cannot reliably target the specific accession that an amendment row
# represents. F43 explicitly defers amendment handling.
form_type = str(row['form_type'])
if form_type.endswith('/A'):
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason=(
            f'amendment form {form_type} cannot be source-excerpted via API '
            '(F43: amendment routing deferred; API cannot target accession)'
        ),
    )

ticker = str(row['ticker'])
year, quarter, source_param = _resolve_api_params_from_row(row)

# Pre-flight: verify our accession is the latest for this form-type+quarter.
# API caches "latest in quarter" semantics; if our row is older/amended/superseded,
# /api/sections would return a different accession's text — fail loudly instead.
expected_accession = (str(row['source_accession']).strip() or None) if row['source_accession'] else None
if expected_accession is None:
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason='row missing source_accession; cannot verify API alignment',
    )

try:
    filings_payload = edgar_api_client.get_filings(ticker, year, quarter)
except edgar_api_client.EdgarAPIError as exc:
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason=f'edgar_api /api/filings failed: {exc}',
    ) from exc

base_form = normalized_form_type
# Match ONLY the base form, NOT base_form/A (amendments rejected above).
matching = [
    f for f in (filings_payload.get('filings') or [])
    if str(f.get('form', '')) == base_form
]
if not matching:
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason=f'no {base_form} filings in API response for {ticker} {year}Q{quarter}',
    )
# Sort by filing_date desc; resolve ties by accession lex desc.
matching.sort(key=lambda f: (str(f.get('filing_date', '')), str(f.get('accession', ''))), reverse=True)
latest_filing_date = str(matching[0].get('filing_date', '')).strip()
# Defensive: empty filing_date means we can't verify "latestness" by date.
# Codex R3 [P2]: don't pretend a single empty-date entry is "the latest".
if not latest_filing_date:
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason=(
            f'/api/filings returned {len(matching)} {base_form} filing(s) for '
            f'{ticker} {year}Q{quarter} with no filing_date — cannot verify '
            'accession alignment'
        ),
    )
# Detect same-date multi-match (F43 territory: same-day multi-8K, same-day amendments).
# If more than one filing has the latest date, accession alignment is ambiguous —
# accession lex order is NOT a semantic signal. Reject explicitly.
same_date_matches = [f for f in matching if str(f.get('filing_date', '')) == latest_filing_date]
if len(same_date_matches) > 1:
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason=(
            f'{len(same_date_matches)} {base_form} filings on {latest_filing_date} for '
            f'{ticker} {year}Q{quarter}; API cannot disambiguate (F43 territory)'
        ),
    )
latest_accession = str(matching[0].get('accession', ''))
if latest_accession != expected_accession:
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason=(
            f'corpus row accession {expected_accession} is not the latest for '
            f'{ticker} {year}Q{quarter} {base_form} (API has {latest_accession}); '
            'API cannot target older/amended/superseded filings'
        ),
    )

# Safe to call /api/sections — accession alignment verified
try:
    api_payload = edgar_api_client.get_filing_sections(
        ticker=ticker,
        year=year,
        quarter=quarter,
        sections=[canonical_section_id],
        format='full',
        source=source_param,
        max_words='none',  # Codex R7 [P1]: API defaults to max_words=3000; need 'none' for verbatim source excerpt
    )
except edgar_api_client.EdgarAPIError as exc:
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason=f'edgar_api /api/sections failed: {exc}',
    ) from exc

section_payload = (api_payload.get('sections') or {}).get(canonical_section_id) or {}
state = str(section_payload.get('state', ''))
text = str(section_payload.get('text') or '').strip()
if state == 'missing' or not text:
    raise ExcerptUnavailableError(
        resolved_document_id,
        reason=f"section {section!r} not available from API (state={state!r})",
    )
return text
```

### Delete from `filings.py`:

- `import sys` (line 7) — no longer needed
- `import httpx` (line 8) — no longer needed
- `from core.corpus.edgar_urls import SEC_USER_AGENT, fetch_primary_document_html` (line 11)
- `parse_filing_sections` wrapper (line 203-210)
- `_load_edgar_section_parser` (line 213-217)
- `_fetch_filing_html` (line 295-end)
- Add: `from core.corpus import edgar_api_client`

## Code shape — bridge `corpus_ingest_accession.py` rewrite

### Replace the `edgar_parser.tools` import (line 16):

```python
from core.corpus import edgar_api_client
from core.corpus.edgar_api_client import EdgarAPIError
```

**Note (Codex R3 [P1]):** import the module + reference functions as
`edgar_api_client.get_filings(...)` / `edgar_api_client.get_filing_sections(...)` at the call site, NOT bare-name `get_filings(...)`. Bare-name imports bind the function reference at script import time; tests cannot then monkeypatch `core.corpus.edgar_api_client.get_*` and intercept the call. Module-attribute reference makes monkeypatching work — single source of truth.

### Replace `get_filings` call (line 151-156):

```python
try:
    filings_response = edgar_api_client.get_filings(
        ticker=ticker, year=args.year, quarter=args.quarter,
    )
except EdgarAPIError as exc:
    _print_error(f'edgar_api /api/filings error for {ticker} {args.year} Q{args.quarter}: {exc}')
    return 2
# /api/filings returns {status: success, filings: [...]} matching old shape
```

### Replace `get_filing_sections` call (line 188-202):

```python
try:
    sections_response = edgar_api_client.get_filing_sections(
        ticker=ticker,
        year=args.year,
        quarter=args.quarter,
        format='full',
        max_words='none',  # MUST be 'none' string — Codex R6 [P2]: integer caps would silently truncate large 10-K Item 8s
        source=args.source,
        include_tables=False,  # tables are inside per-section.tables already
    )
except EdgarAPIError as exc:
    _print_error(f'edgar_api /api/sections error for {ticker} {args.year} Q{args.quarter}: {exc}')
    return 5

if sections_response.get('status') != 'success':
    _print_error(f'/api/sections returned non-success: {sections_response.get("message", "unknown")}')
    return 5

# OLD path read body from file via load_body(file_path); new path assembles in-memory
try:
    body = _assemble_body_from_api_response(sections_response, expected_form=expected_form)
except ValueError as exc:
    _print_error(str(exc))
    return 4
```

### Add `_assemble_body_from_api_response` helper:

```python
def _assemble_body_from_api_response(payload: Mapping[str, Any], *, expected_form: str) -> str:
    """Convert /api/sections response to canonical corpus markdown body.

    Matches the format Edgar_updater's _write_sections_markdown produces
    (which today's bridge reads via load_body) so that
    core/corpus/section_map.py::_parse_filing_sections_raw consumes it
    identically. See investigation notes 2026-04-28.
    """
    sections = payload.get('sections') or {}
    if not sections:
        raise ValueError(f'/api/sections returned no sections for {expected_form}')
    lines: list[str] = []
    for canonical_id, section in sections.items():
        if not isinstance(section, Mapping):
            continue
        # NOTE: do NOT skip state=='missing' entries (Codex R6 [P2]).
        # Upstream _write_sections_markdown emits header + state line + word count
        # = 0 line for missing records too — strict round-trip parity requires the
        # same. parse_sections handles them correctly; corpus search just sees
        # extra `**State:** missing\n**Word count:** 0` lines (no text body) which
        # don't materially affect FTS5 ranking.
        # Match Edgar_updater/edgar_parser/section_parser.py::_write_sections_markdown
        # parity (Codex R3+R4+R5): full State marker including cross_reference_target +
        # declaration_type combinator. _safe_heading collapses whitespace + falls
        # back to "Unknown Section" if header missing — DON'T skip empty-header
        # entries, emit them as "Unknown Section" to match upstream behavior.
        header_safe = re.sub(r'\s+', ' ', str(section.get('header') or '')).strip() or 'Unknown Section'
        word_count = section.get('word_count', 0)
        state = str(section.get('state', '')).strip()
        text = str(section.get('text') or '').strip()
        tables = section.get('tables') or []
        lines.append(f'## SECTION: {header_safe}')
        if state:
            marker = f'**State:** {state}'
            if state == 'cross_reference' and section.get('cross_reference_target'):
                marker += f' ({section.get("cross_reference_target")})'
            if section.get('declaration_type'):
                marker += f' | **Declaration:** {section.get("declaration_type")}'
            lines.append(marker)
        lines.append(f'**Word count:** {word_count:,}')
        if text:
            lines.append(text)
        if tables:
            lines.append('### TABLES')
            for table in tables:
                table_text = (str(table) or '').strip()
                if table_text:
                    lines.append(table_text)
        lines.append('---')
    if not lines:
        raise ValueError(f'/api/sections returned empty sections payload for {expected_form}')
    # All-missing check (Codex R6 [P2] follow-on): emitting strict-parity bodies
    # for all-missing payloads would store useless headers in corpus. Detect +
    # reject explicitly even though the helper now emits missing entries.
    non_missing = [
        canonical_id for canonical_id, section in sections.items()
        if isinstance(section, Mapping) and str(section.get('state', '')) != 'missing'
    ]
    if not non_missing:
        raise ValueError(f'all sections were state=missing for {expected_form}')
    if lines[-1] == '---':
        lines.pop()
    return '\n'.join(lines).strip() + '\n'
```

### Delete from bridge:

- `load_body` function (no longer reading from file)
- `file_path_value` extraction (line 199-202)

## Tests

### New `tests/test_edgar_api_client.py` (11 tests)

1. `test_get_filing_sections_success` — mock `httpx.get` returns 200 JSON; assert URL = `f"{base}/api/sections"`, params include ticker/year/quarter/format, header `Authorization: Bearer <key>`.
2. `test_get_filing_sections_with_sections_filter` — assert `sections=["item_7"]` becomes `?sections=item_7`.
3. `test_get_filing_sections_with_source_8k` — assert `source="8k"` reaches URL.
4. `test_get_filing_sections_400` — mock returns 400; assert raises `EdgarAPIError` with "HTTP 400".
5. `test_get_filing_sections_401` — mock 401; same shape.
6. `test_get_filing_sections_429` — mock 429; same shape.
7. `test_get_filing_sections_5xx` — mock 500; same shape.
8. `test_get_filing_sections_network_error` — mock raises `httpx.RequestError`; assert raises `EdgarAPIError` with "network error".
9. `test_get_filing_sections_invalid_json` — mock returns 200 with non-JSON body; assert raises `EdgarAPIError` with "invalid JSON".
10. `test_get_filings_success` — same shape as #1, against `/api/filings` URL.
11. `test_config_missing_env` — clear `EDGAR_API_URL` (or KEY); assert raises `EdgarAPIError` with config message.

### Updated `tests/test_filings_tools.py`

`test_filings_source_excerpt_document_id` (line 78) currently has 2 monkeypatches:
- `core.corpus.filings.httpx.get` (for `_fetch_filing_html`) — DELETE (no longer relevant)
- `core.corpus.filings.parse_filing_sections` (lambda html, filing_type) — REPLACE with mock of `core.corpus.edgar_api_client.get_filings` AND `core.corpus.edgar_api_client.get_filing_sections`

The new mock setup needs to:
- Return a `/api/filings` payload where the seeded fixture's accession IS the latest (so pre-flight passes)
- Return a `/api/sections` payload with the requested section's text

Pattern:
```python
def _mock_get_filings(ticker, year, quarter, **kwargs):
    return {'status': 'success', 'filings': [
        {'form': '10-K', 'accession': '<seeded accession>', 'filing_date': '2024-11-01'},
    ]}

def _mock_get_filing_sections(ticker, year, quarter, **kwargs):
    return {'status': 'success', 'sections': {
        'item_7': {'state': 'body', 'text': 'Verbatim MD&A from API.', 'header': '...'},
    }}

monkeypatch.setattr('core.corpus.edgar_api_client.get_filings', _mock_get_filings)
monkeypatch.setattr('core.corpus.edgar_api_client.get_filing_sections', _mock_get_filing_sections)
```

Existing test assertion (`assert content == 'Verbatim MD&A from SEC HTML.'`) updates to `'Verbatim MD&A from API.'`.

Add 3 new tests in `tests/test_filings_tools.py`:
- `test_filings_source_excerpt_accession_mismatch_fails` — mock `/api/filings` returns a DIFFERENT accession as latest; assert raises `ExcerptUnavailableError` with "not the latest" reason.
- `test_filings_source_excerpt_section_state_missing` — mock `/api/sections` returns `state=missing`; assert raises `ExcerptUnavailableError` with "not available from API".
- `test_filings_source_excerpt_api_filings_error_propagates` — mock `/api/filings` raises `EdgarAPIError`; assert wraps as `ExcerptUnavailableError`.

Update existing `_resolve_filing_document_row`-tuple-based tests if they exist, since lookup columns changed.

### Updated `tests/test_corpus_ingest_accession.py`

Replace mocks. **Codex R3 [P1]:** because the bridge imports the module and references functions as `edgar_api_client.get_*(...)`, monkeypatching `core.corpus.edgar_api_client.get_*` works at the module level. Tests should target:
- `core.corpus.edgar_api_client.get_filings` (NOT `scripts.corpus_ingest_accession.get_filings` — the script doesn't bind those names directly)
- `core.corpus.edgar_api_client.get_filing_sections` (same reasoning)

If the implementer accidentally writes `from core.corpus.edgar_api_client import get_filings` instead of `from core.corpus import edgar_api_client`, the monkeypatch would not intercept calls — tests would hit the real API. **Codex R4 [P2] correction**: don't write a "verify happy path doesn't fire" guard test (inverted logic, noisy). Instead, the standard mock-asserting test pattern catches this:
- Patch `core.corpus.edgar_api_client.get_filings` to return a sentinel payload (e.g., `{'status': 'success', 'filings': [{...marker accession...}]}`).
- Run the bridge happy path.
- Assert the bridge wrote markdown derived from the marker accession (proving the mock was actually consumed).
- If the bare-name import bug is present, the bridge would call the REAL API (or fail because env not set), and the assertion would fail loudly. No need for a separate AssertionError-on-mock guard.

Optional belt-and-suspenders: also patch `core.corpus.edgar_api_client.httpx.get` to raise; if the bridge somehow bypasses the mock, the httpx patch catches it.

Mock returns must include the new shape:
- `get_filings` returns `{status: success, filings: [...]}`
- `get_filing_sections` returns `{status: success, sections: {<id>: {header, text, tables, state, word_count, source, confidence}}}` — the bridge will assemble body from this

Add `test_assemble_body_from_api_response_round_trip` (location: `tests/test_corpus_ingest_accession.py`):
- Synthetic API payload with ≥3 sections: 2 with `state='body'` + populated text/tables/word_count, plus 1 with `state='missing'` and empty text/word_count=0.
- Assert assembled body:
  (a) contains `## SECTION: <header>` for ALL sections including the missing one (Codex R6+R7 [P2]: emits state='missing' for upstream parity)
  (b) emits `**State:** body` / `**State:** missing` / etc. line after the header when state present
  (c) emits `**State:** cross_reference (Note 30)` when state=cross_reference + cross_reference_target set
  (d) appends ` | **Declaration:** {declaration_type}` when declaration_type present (test the combinator separately)
  (e) emits `**Word count:** N` line per section (including N=0 for missing)
  (f) emits `### TABLES` block followed by table strings, separated by `\n`
  (g) emits `---` separator between sections (last `---` removed per upstream)
- Round-trip: feed assembled body to `core.corpus.section_map.parse_sections(body, source='edgar')`. Assert:
  (a) Returned `SectionRow` count equals total entries in input (including missing-state entries)
  (b) `SectionRow.section` (the header) matches each input section's `header` exactly (or "Unknown Section" for empty-header inputs)
  (c) For non-missing entries: `SectionRow.content` includes the section's text + tables (verbatim)
  (d) For missing entries: `SectionRow.content` contains the State + Word count lines but no text body
- Edge: section with empty text but state='body' (non-missing) → emits header + state + word_count line + no text + separator. parse_sections still finds it.
- Edge: section with empty header → emits `## SECTION: Unknown Section` (upstream parity).

Add `test_assemble_body_empty_payload` — `{sections: {}}` → raises ValueError("returned empty sections payload").

Add `test_assemble_body_all_missing` — only `state='missing'` entries → raises ValueError("all sections were state=missing"). Still rejects despite emitting parity entries (separate post-loop check on `non_missing` list).

### Regression check

`pytest tests/test_filings_*.py tests/test_corpus_*.py tests/test_edgar_api_client.py tests/test_section_map.py -v` — all green.

## Edge cases

| Case | Behavior |
|---|---|
| `EDGAR_API_URL` or `EDGAR_API_KEY` unset | `EdgarAPIError("EDGAR_API_URL and EDGAR_API_KEY must be set in environment")`. Source-excerpt path wraps as `ExcerptUnavailableError`. |
| Network timeout | `EdgarAPIError("network error ...")` → `ExcerptUnavailableError`. |
| 401 (key rotation) | `EdgarAPIError("HTTP 401 ...")` → `ExcerptUnavailableError`. Operator updates `.env`. |
| 429 (rate limit) | `EdgarAPIError("HTTP 429 ...")` → `ExcerptUnavailableError`. No retry; fail-fast. |
| 5xx (API outage) | `EdgarAPIError("HTTP 5xx ...")` → `ExcerptUnavailableError`. |
| Invalid JSON body | `EdgarAPIError("invalid JSON ...")` → `ExcerptUnavailableError`. |
| `/api/sections` returns `state=missing` for requested section (e.g., JPM `part1_item1`) | `ExcerptUnavailableError("section X not available from API (state='missing')")`. |
| Pre-flight: corpus row accession is older than latest in quarter | `ExcerptUnavailableError("corpus row accession X is not the latest for ticker year quarter form (API has Y); API cannot target older/amended/superseded filings")`. |
| Pre-flight: no matching form in /api/filings response | `ExcerptUnavailableError("no FORM filings in API response for ticker year quarter")`. |
| Row has NULL `source_accession` | `ExcerptUnavailableError("row missing source_accession; cannot verify API alignment")`. |
| 10-K with `fiscal_period="2024-FY"` | `_resolve_api_params_from_row` → `(2024, 4, None)`. |
| 10-Q with `fiscal_period="2025-Q3"` | → `(2025, 3, None)`. |
| 8-K with `fiscal_period="2025-Q2"` (bridge format) | → `(2025, 2, "8k")`. |
| 8-K with `fiscal_period="2025-04-15"` (legacy date format) | → `(2025, 2, "8k")` via month/3 calc. |
| Bridge: API returns no sections (parser failure on every section) | `_assemble_body_from_api_response` raises `ValueError("/api/sections returned no sections")`; bridge prints + exits non-zero. |
| Bridge: all sections have `state=missing` (only synthesized) | `_assemble_body_from_api_response` raises `ValueError("all sections were state=missing")`. |
| Bridge: API returns extra section keys not in `_EDGAR_CORPUS_HEADER_TO_ID` (future Phase 4 expansions) | Body assembly emits them anyway via API's header field. `parse_sections` consumes them; corpus index reflects them. Forward-compatible. |

## Validation

- Plan-first per CLAUDE.md: this draft → Codex review → PASS → implement via Codex.
- Implementation gate: all new + updated tests pass.
- Round-trip gate: `_assemble_body_from_api_response(API payload) → parse_sections('edgar') → enumerated sections match input`.
- Smoke gate (manual, post-merge): live `filings_source_excerpt(document_id="edgar:0000950170-25-061046", section="Part I, Item 2. ...", db=...)` returns text matching curl `/api/sections?ticker=MSFT&year=2025&quarter=3&sections=part1_item2&format=full`.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| API key rotates | high (just happened) | `.env` update + restart; clear `HTTP 401` error makes diagnosis fast. |
| Rate limit on validation re-ingest (25 tickers × 2 = 50 calls + pre-flights) | low | Paid tier has higher limits; if hit, batch + sleep. |
| `/api/filings` shape changes between dev and verify | low | Curl-verified 2026-04-28 matches old `edgar_parser.tools` shape exactly. New tests assert on the shape. |
| `/api/sections` `header` field drifts from `_EDGAR_CORPUS_HEADER_TO_ID` keys | med | Round-trip test catches drift; CI gate. If drift happens, body assembly silently emits unknown headers (forward-compat behavior). |
| Pre-flight false-positive (legitimate latest filing not in /api/filings cache) | low | `/api/filings` cache is server-side; same age-class as `/api/sections` cache; in-sync by construction. If desynced, manual cache refresh upstream. |
| Body assembly format diverges from canonical convention | med | Round-trip test through `parse_sections('edgar')` is the gate. Mirrors today's `_write_sections_markdown` format from edgar-parser. |
| Direct python import of edgar_parser sneaks back in | med | Add a CI lint that fails if `import edgar_parser` appears anywhere in `core/corpus/` or `scripts/corpus_*` — file as F-followup if not done in this plan. |
| 8-K fiscal_period format drift | low | `_resolve_api_params_from_row` handles all 3 schema-allowed formats defensively. Unit test per format. |
| Phase 4 cache-poisoning bug for `/api/filing/document` bites us if we ever switch to it | low | Plan explicitly REJECTS `/api/filing/document` for accession-aligned use. Stick with `/api/sections` + `/api/filings`. |
| `EdgarAPIError` standalone (not subclass of `ExcerptUnavailableError`) breaks existing catch sites | low | Existing catch sites in `mcp_tools/corpus/filings.py` catch `ExcerptUnavailableError`. Source-excerpt callsite explicitly catches `EdgarAPIError` and rewraps — boundary pattern. |

## Open questions for Codex

1. **Ambiguity-tuple lookup path** (`_resolve_filing_document_row` line 261-292): if the caller provides `(ticker, form_type, fiscal_period)` instead of `document_id`, the helper queries with multiple potential matches and may raise `AmbiguousDocumentError`. After the lookup-columns extension, the SELECT still includes `ticker, fiscal_period` but those are also in WHERE — redundant but harmless. Confirm the SELECT change is purely additive.

2. **Pre-flight on the document-id path only?** The pre-flight check makes sense when caller asks for a specific document_id (which encodes a specific accession). For tuple-based lookups (caller asks "give me the MSFT 10-K for 2024-FY"), pre-flight is redundant — the SELECT already constrained to "the latest non-superseded matching tuple", which IS the latest. Could skip pre-flight in that branch. Or always run it for consistency. Lean: always run for consistency, skip optimization.

3. **`_assemble_body_from_api_response` location**: bridge-only (in `scripts/corpus_ingest_accession.py`) or shared (in `core/corpus/section_map.py` next to inverse mapping helper)? Lean: keep in bridge for now — it's bridge-specific concern; promote to shared if a second consumer appears.

4. **Header text trust**: API returns `section['header']` as the canonical-corpus-header string today. Plan trusts this (uses directly in `## SECTION: <header>`). If upstream Phase 4 changes the header text format (e.g., adds prefixes, normalizes case), corpus body assembly silently drifts. Should the body assembler validate header against `_EDGAR_CORPUS_HEADER_TO_ID` and fall back to inverse-lookup-from-canonical-id if mismatch? Adds defense; costs one dict lookup per section.

5. **Rate-limit handling in pre-flight**: the pre-flight adds 1 extra `/api/filings` call per source-excerpt request. For typical use (low-volume citation verification), fine. If a caller does 100+ source-excerpts in a burst, the pre-flights double the call count. Should the client cache `/api/filings` results by `(ticker, year, quarter)` for short TTL (e.g., 60s in-process)? Lean: skip for v1; revisit if real usage shows pressure.

## References

- `CORPUS_PRE_PHASE1_HARDENING_PLAN.md` v2 Track 3 — parent milestone
- `CORPUS_LAYERED_PARSER_PLUMBING_PLAN.md` — abandoned predecessor
- `CORPUS_ARCHITECTURE.md` §5.1 — SearchResponse envelope (no change)
- `Edgar_updater/edgar_api/routes/sections.py:32-111` — `/api/sections` endpoint contract
- `Edgar_updater/edgar_api/routes/filings.py` — `/api/filings` endpoint
- `Edgar_updater/edgar_api/auth.py` — Bearer auth
- `Edgar_updater/docs/TODO.md` — public-package-freeze decision; Phase 3+4 ship; `/api/filing/document` cache-poisoning bug
- `Edgar_updater/edgar-parser/edgar_parser/section_parser.py:584-634` — today's `_write_sections_markdown` format (target for body-assembly parity)
- `core/corpus/section_map.py:53-68` — `_parse_filing_sections_raw` body shape consumer
- `core/corpus/section_map.py:16-40` — `_EDGAR_CORPUS_HEADER_TO_ID` mapping table
- F44 (corpus source-passage highlighting) — separate Bucket C work
- `.env` — `EDGAR_API_URL`, `EDGAR_API_KEY` (rotated 2026-04-28)

---

## Appendix — implementation checklist (for Codex implementer)

1. Create `core/corpus/edgar_api_client.py` per "Code shape" §1.
2. Create `tests/test_edgar_api_client.py` with 11 tests per Tests §1.
3. Add `edgar_id_to_corpus_header` to `core/corpus/section_map.py` per "Code shape" §2.
4. Add unit test in `tests/test_section_map.py` (create if missing): every entry in `_EDGAR_CORPUS_HEADER_TO_ID` round-trips.
5. Edit `core/corpus/filings.py`:
   - Delete `import sys`, `import httpx`, `from core.corpus.edgar_urls import SEC_USER_AGENT, fetch_primary_document_html`.
   - Add `from core.corpus import edgar_api_client`.
   - Extend `_FILING_SOURCE_LOOKUP_COLUMNS` (line 39-45) with `ticker`, `fiscal_period`.
   - Update inline SELECT in `_resolve_filing_document_row` (line 269) to include `ticker, fiscal_period`.
   - Add `_resolve_api_params_from_row` helper.
   - Replace `filings_source_excerpt` body (lines 140-148) per "Code shape" §3.
   - Delete `parse_filing_sections` wrapper (line 203-210).
   - Delete `_load_edgar_section_parser` (line 213-217).
   - Delete `_fetch_filing_html` (line 295-end).
6. Update `tests/test_filings_tools.py`:
   - Find existing monkeypatches: `rg -n -U "monkeypatch\.setattr\([\s\S]*?(parse_filing_sections|httpx\.get)" tests/test_filings_tools.py`.
   - Replace `parse_filing_sections` mocks with mocks of `core.corpus.edgar_api_client.get_filings` AND `get_filing_sections`.
   - Delete `httpx.get` mocks (no longer relevant — no local fetch).
   - Add 3 new tests per Tests §2: accession mismatch, state=missing, /api/filings error propagation.
7. Edit `scripts/corpus_ingest_accession.py`:
   - Delete `from edgar_parser.tools import get_filing_sections, get_filings`.
   - Add `from core.corpus import edgar_api_client` AND `from core.corpus.edgar_api_client import EdgarAPIError`. **Codex R4 [P1]:** module-attribute reference at call sites is required for monkeypatching to work — do NOT bare-import `get_filings`/`get_filing_sections`. Use `edgar_api_client.get_filings(...)` / `edgar_api_client.get_filing_sections(...)` per "Code shape" §4.
   - Replace `get_filings` call (line 151) and `get_filing_sections` call (line 188) per "Code shape" §4.
   - Delete `load_body` function (line 90-98), `file_path_value` extraction (line 199-202).
   - Add `_assemble_body_from_api_response` helper.
8. Update `tests/test_corpus_ingest_accession.py`:
   - Replace mocks of `edgar_parser.tools.*` with mocks of `core.corpus.edgar_api_client.*`.
   - Add round-trip test: assemble → parse → enumerate matches input.
9. Run `pytest tests/test_edgar_api_client.py tests/test_section_map.py tests/test_filings_tools.py tests/test_corpus_ingest_accession.py -v` — all green.
10. Run `pytest tests/test_corpus_*.py tests/test_filings_*.py -v` — broader regression.
11. Manual smoke: `python3 -c "from core.corpus.filings import filings_source_excerpt; ..."` for MSFT 10-Q 2025Q3 part1_item2 — text matches curl response.
12. Commit message: `feat(corpus): switch edgar integration to /api/sections HTTP — corrected Track 3 of pre-Phase-1 hardening`.

---

## v7 → v8 changelog (Codex R7 fixes)

- **[P1] Source-excerpt path also needed `max_words='none'`** — v7 only fixed the bridge call; missed the `filings_source_excerpt` callsite. `/api/sections` defaults to `max_words=3000`, would silently truncate any section excerpt > 3K words. Fixed.
- **[P2] Test spec stale after v7 missing-section change** — `test_assemble_body_from_api_response_round_trip` still claimed missing entries were skipped + SectionRow count equals non-missing count. v8 helper emits all entries. Test spec rewritten to match: assert all entries (including missing) appear with State + Word count lines, separators preserved, all-missing still rejected via separate post-loop check.

## v6 → v7 changelog (Codex R6 fixes)

- **[P2] `max_words=100000` could silently truncate** large 10-K Item 8 sections (some run > 100K words). Changed to `max_words='none'` per API string-or-int parameter contract — no truncation.
- **[P2] `state='missing'` skip diverged from upstream parity** — `_write_sections_markdown` emits header + state line + word count even for missing records. v7 helper now matches: emits all entries, falls back to "Unknown Section" + `**State:** missing` + `**Word count:** 0` for missing records. Added explicit "all-missing" detection (separate from emitting individual missing entries) so bridge still rejects all-missing payloads cleanly.

## v5 → v6 changelog (Codex R5 fixes)

- **[P1] Touch points table import inconsistency** — table at the start of the file was still listing bare-name imports (`from core.corpus.edgar_api_client import EdgarAPIError, get_filing_sections, get_filings`). Updated to match: `from core.corpus import edgar_api_client` + `from core.corpus.edgar_api_client import EdgarAPIError`. Also clarified inline that bare-name imports break test mocking.
- **[P2] `_safe_heading` fallback semantics** — removed the early `if not header: continue` skip in `_assemble_body_from_api_response`. Upstream `_write_sections_markdown` emits `## SECTION: Unknown Section` for empty-header entries; v5 was skipping them entirely, breaking parity. v6 always emits the section, falling back to `"Unknown Section"` per upstream.

## v4 → v5 changelog (Codex R4 fixes)

- **[P1] Appendix import inconsistency** — appendix step 7 was reintroducing bare imports; updated to match main section's `from core.corpus import edgar_api_client` + module-attribute reference at call sites.
- **[P2] Body assembly partial parity** — `_assemble_body_from_api_response` now FULLY matches `_write_sections_markdown` per Codex's inspection of `Edgar_updater/edgar_parser/section_parser.py:1636-1694`:
  - `_safe_heading` semantics: collapse whitespace via `re.sub(r'\s+', ' ', ...)`, strip, fall back to `"Unknown Section"` if empty.
  - State marker: `**State:** {state}` plus optional ` ({cross_reference_target})` when `state == 'cross_reference'` plus optional ` | **Declaration:** {declaration_type}` when `declaration_type` set.
- **[P2] Mock-target guard test** — replaced inverted "verify happy path doesn't fire" pattern with standard mock-payload + assertion-on-output pattern. If bare-name import bug is present, the assertion fails loudly (mock was bypassed → real env hit → test fails). Optional httpx-patch as belt-and-suspenders.

## v3 → v4 changelog (Codex R3 fixes)

- **[P1] Bridge import style** — changed from `from core.corpus.edgar_api_client import get_*` to `from core.corpus import edgar_api_client` + `edgar_api_client.get_*(...)` at call sites. Bare-name imports bind at script-import time and break monkeypatching of the source module. Module-attribute reference enables `core.corpus.edgar_api_client.get_*` mock target.
- **[P2] Body assembly parity drift** — `_assemble_body_from_api_response` now emits `**State:** {state}` line BEFORE `**Word count:**` when `state` is present, matching `Edgar_updater/edgar_parser/section_parser.py::_write_sections_markdown` (the dev version with Phase 4, NOT the frozen public package's version).
- **[P2] Empty `filing_date` defensive guard** — explicit reject when `latest_filing_date` is empty after normalization. Prevents a single empty-date entry from passing as "the latest" when latestness can't be verified by date.

## v2 → v3 changelog (Codex R2 fixes)

- **[P1] Bridge `status` check inconsistency** — clarified Investigation Summary that `/api/sections` DOES return top-level `status: success` (verified live; bridge check is correct). Removed the misleading "explicit removal" claim from v1→v2 changelog. The check stays — it catches HTTP 200 responses with in-body errors that wouldn't trigger the HTTP-status-based exception.
- **[P1] Amendment handling not fail-loud** — added explicit reject for `/A` form types at the TOP of `filings_source_excerpt` body, BEFORE the pre-flight. Pre-flight matching now matches ONLY the base form (no `/A` fallback). Same-day multi-match detection added.
- **[P2] Date parsing trust** — added month range validation (`1-12`), quarter range validation (`1-4`), and `try/except ValueError` wrapping with clear `InvalidInputError` messages. Schema GLOB cannot enforce semantic ranges; this layer does.
- **[P2] Pre-flight tie behavior** — explicit `same_date_matches` detection. If >1 filing has the latest filing_date AND form matches, reject with F43-territory reason instead of relying on accession lex order.
- **[P2] Body assembly tests too thin** — expanded test spec: round-trip enumeration with `SectionRow.content` parity, separator handling, state='missing' skip behavior, empty-text-but-present case, empty payload error, all-missing payload error.

## v1 → v2 changelog (Codex R1 fixes + investigation)

- **[P1] Lookup columns missing `ticker`/`fiscal_period`** — extended `_FILING_SOURCE_LOOKUP_COLUMNS` AND inline SELECT.
- **[P1] 8-K fiscal_period format wrong** — bridge writes `YYYY-Qn`, not date. Resolver now handles all 3 schema-allowed formats with explicit format detection.
- **[P1] Accession alignment** — added `/api/filings` pre-flight; rejects request with clear error if corpus row's accession isn't the latest. Bounded by F43 deferral; no silent precision loss.
- **[P1] Bridge body assembly** — added `_assemble_body_from_api_response` helper; uses API's `header` field directly (verified to match `_EDGAR_CORPUS_HEADER_TO_ID` keys); matches today's `_write_sections_markdown` format for round-trip parity.
- **[P1] `/api/filings` shape** — verified live, matches old `edgar_parser.tools.get_filings` exactly.
- **[P1] Stale bridge guards** — explicit removal of `status=='success'` check (replaced with exception-based flow) and `file_path` extraction.
- **[P2] JSON decode errors** — `_request_json` catches `ValueError` from `.json()`, raises `EdgarAPIError("invalid JSON")`.
- **[P2] `EdgarAPIError` subclass awkwardness** — now standalone `Exception`; source-excerpt rewraps as `ExcerptUnavailableError` at boundary.
- **[P2] Missing env raises wrong type** — now raises `EdgarAPIError`, consistent.
- **[P2] Test mock target inconsistent** — explicit: tests mock `core.corpus.edgar_api_client.get_*`, NOT `httpx.get`.
- **[P2] `edgar_urls.py` orphaning** — confirmed safe; keep as-is.
- **Investigation additions:** rejected `/api/filing/document` (cache bug), confirmed `state=missing` semantics for absent sections, verified API `header` matches corpus headers.
