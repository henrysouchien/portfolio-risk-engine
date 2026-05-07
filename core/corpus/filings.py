from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from core.corpus import edgar_api_client
from core.corpus.db import open_corpus_db
from core.corpus.frontmatter import parse_frontmatter
from core.corpus.search import _resolved_source_url_sql, _search
from core.corpus.section_map import corpus_header_to_edgar_id, parse_sections
from core.corpus.types import (
    AmbiguousDocumentError,
    DocumentMetadata,
    ExcerptUnavailableError,
    InvalidInputError,
    ReadResult,
    SearchResponse,
)
from core.corpus.validation import (
    _validate_canonical_ticker,
    resolve_corpus_ticker_alias,
    validate_read_path,
    validate_search_inputs,
)


FILINGS_FAMILY_FORM_TYPES = frozenset({'10-K', '10-Q', '8-K', '20-F', '6-K'})
_FILINGS_FAMILY_DEFAULT_FORM_TYPES = ['10-K', '10-Q', '8-K', '20-F', '6-K']
_EXCERPT_FORM_TYPES = {
    '10-K': '10-K',
    '10-K/A': '10-K',
    '10-Q': '10-Q',
    '10-Q/A': '10-Q',
    '8-K': '8-K',
    '8-K/A': '8-K',
    '20-F': '20-F',
    '20-F/A': '20-F',
    '6-K': '6-K',
    '6-K/A': '6-K',
}
_API_SOURCE_BY_BASE_FORM = {
    '8-K': '8k',
    '20-F': '20f',
    '6-K': '6k',
}
_FILING_SOURCE_LOOKUP_COLUMNS = (
    'document_id',
    'ticker',
    'cik',
    'form_type',
    'fiscal_period',
    'source_url',
    'source_url_deep',
    'source_accession',
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS_ROOT = _REPO_ROOT / 'data' / 'filings'
_DEFAULT_CORPUS_DB_PATH = _REPO_ROOT / 'data' / 'filings.db'


def filings_search(
    query: str,
    universe: list[str] | None = None,
    sector: str | None = None,
    form_type: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_superseded: bool = False,
    include_low_confidence_supersession: bool = False,
    limit: int = 20,
) -> SearchResponse:
    validate_search_inputs(query, universe, limit)
    resolved_form_types = _resolve_filings_form_types(form_type)

    db = _open_runtime_db()
    try:
        return _search(
            db=db,
            query=query,
            form_types=resolved_form_types,
            sources=['edgar'],
            universe=universe,
            sector=sector,
            date_from=date_from,
            date_to=date_to,
            include_superseded=include_superseded,
            include_low_confidence_supersession=include_low_confidence_supersession,
            limit=limit,
        )
    finally:
        db.close()


def filings_read(
    file_path: str,
    section: str | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
) -> ReadResult:
    path = validate_read_path(file_path, _corpus_root())
    text = path.read_text(encoding='utf-8')
    metadata, _body = parse_frontmatter(text)

    if section is None and char_start is None and char_end is None:
        return ReadResult(
            content=text,
            document_id=str(metadata['document_id']),
            section=None,
            char_start=0,
            char_end=len(text),
            url=_source_url_from_metadata(metadata),
        )

    scoped_text = text
    scoped_start = 0
    resolved_section: str | None = None
    if section is not None:
        for row in parse_sections(text, source='edgar'):
            if row.section == section:
                scoped_text = row.content
                scoped_start = row.char_start
                resolved_section = row.section
                break
        else:
            raise InvalidInputError(f"section {section!r} not found in filing")

    content, resolved_start, resolved_end = _slice_text_with_offsets(
        scoped_text,
        char_start,
        char_end,
        base_start=scoped_start,
    )
    return ReadResult(
        content=content,
        document_id=str(metadata['document_id']),
        section=resolved_section,
        char_start=resolved_start,
        char_end=resolved_end,
        url=_source_url_from_metadata(metadata),
    )


def filings_source_excerpt(
    document_id: str | None = None,
    section: str | None = None,
    ticker: str | None = None,
    form_type: str | None = None,
    fiscal_period: str | None = None,
    *,
    db: sqlite3.Connection,
) -> ReadResult:
    if section is None:
        raise InvalidInputError('section is required for filings_source_excerpt')

    row = _resolve_filing_document_row(
        db=db,
        document_id=document_id,
        ticker=ticker,
        form_type=form_type,
        fiscal_period=fiscal_period,
    )
    resolved_document_id = str(row['document_id'])

    normalized_form_type = _EXCERPT_FORM_TYPES.get(str(row['form_type']))
    if normalized_form_type is None:
        raise ExcerptUnavailableError(
            resolved_document_id,
            reason=f"form_type {row['form_type']} unsupported in Phase 0; proxy support is Phase 1",
        )

    form_type = str(row['form_type'])
    if form_type.endswith('/A'):
        raise ExcerptUnavailableError(
            resolved_document_id,
            reason=(
                f'amendment form {form_type} cannot be source-excerpted via API '
                '(F43: amendment routing deferred; API cannot target accession)'
            ),
        )

    canonical_section_id = corpus_header_to_edgar_id(section, normalized_form_type)
    if canonical_section_id is None:
        raise ExcerptUnavailableError(
            resolved_document_id,
            reason=f"section {section!r} unsupported for form_type {row['form_type']}",
        )

    ticker_value = str(row['ticker'])
    year, quarter, source_param = _resolve_api_params_from_row(row)

    expected_accession = (str(row['source_accession']).strip() or None) if row['source_accession'] else None
    if expected_accession is None:
        raise ExcerptUnavailableError(
            resolved_document_id,
            reason='row missing source_accession; cannot verify API alignment',
        )

    if source_param not in {'20f', '6k'}:
        _verify_latest_filing_alignment(
            document_id=resolved_document_id,
            ticker=ticker_value,
            year=year,
            quarter=quarter,
            base_form=normalized_form_type,
            expected_accession=expected_accession,
        )

    try:
        api_payload = edgar_api_client.get_filing_sections(
            ticker=ticker_value,
            year=year,
            quarter=quarter,
            sections=[canonical_section_id],
            format='full',
            source=source_param,
            max_words='none',
        )
    except edgar_api_client.EdgarAPIError as exc:
        raise ExcerptUnavailableError(
            resolved_document_id,
            reason=f'edgar_api /api/sections failed: {exc}',
        ) from exc

    if source_param in {'20f', '6k'}:
        api_accession = _section_response_accession(api_payload)
        if api_accession != expected_accession:
            raise ExcerptUnavailableError(
                resolved_document_id,
                reason=(
                    f'corpus row accession {expected_accession} does not match '
                    f'/api/sections {normalized_form_type} response accession {api_accession or "<missing>"}'
                ),
            )

    section_payload = (api_payload.get('sections') or {}).get(canonical_section_id) or {}
    state = str(section_payload.get('state', ''))
    text = str(section_payload.get('text') or '').strip()
    # Phase 4 v10 critical-key rescue (Edgar_updater abbf412, deployed 2026-04-29)
    # splits rescued sections as text=heading + tables[*]=content. Concatenate to
    # preserve verbatim excerpt parity with bridge ingest body assembly.
    tables = section_payload.get('tables') or []
    parts: list[str] = [text] if text else []
    for table in tables:
        table_str = str(table or '').strip()
        if table_str:
            parts.append(table_str)
    combined = '\n\n'.join(parts).strip()
    if state == 'missing' or not combined:
        raise ExcerptUnavailableError(
            resolved_document_id,
            reason=f"section {section!r} not available from API (state={state!r})",
        )
    return ReadResult(
        content=combined,
        document_id=resolved_document_id,
        section=section,
        char_start=0,
        char_end=len(combined),
        url=_source_url_from_row(row),
    )


def filings_list(
    ticker: str | None = None,
    form_type: list[str] | None = None,
    fiscal_period: str | None = None,
    *,
    db: sqlite3.Connection,
) -> list[DocumentMetadata]:
    resolved_form_types = _resolve_filings_form_types(form_type)

    clauses = ["d.source = 'edgar'", f"d.form_type IN ({', '.join('?' for _ in resolved_form_types)})"]
    params: list[object] = [*resolved_form_types]
    if ticker is not None:
        _validate_canonical_ticker(ticker, field='ticker')
        ticker = resolve_corpus_ticker_alias(db, ticker)
        clauses.append('d.ticker = ?')
        params.append(ticker)
    if fiscal_period is not None:
        clauses.append('d.fiscal_period = ?')
        params.append(fiscal_period)

    rows = db.execute(
        f"""
        SELECT
            d.document_id,
            d.ticker,
            d.form_type,
            COALESCE(d.fiscal_period, '') AS fiscal_period,
            COALESCE(CAST(d.filing_date AS TEXT), '') AS filing_date,
            d.is_superseded_by IS NOT NULL AS is_superseded,
            d.file_path,
            {_resolved_source_url_sql('d')} AS source_url
        FROM documents d
        WHERE {' AND '.join(clauses)}
        ORDER BY d.filing_date DESC, d.document_id ASC
        """,
        params,
    ).fetchall()

    return [
        DocumentMetadata(
            document_id=str(row['document_id']),
            ticker=str(row['ticker']),
            form_type=str(row['form_type']),
            fiscal_period=str(row['fiscal_period'] or ''),
            filing_date=str(row['filing_date'] or ''),
            is_superseded=bool(row['is_superseded']),
            file_path=str(row['file_path']),
            source_url=str(row['source_url'] or ''),
        )
        for row in rows
    ]


def _resolve_filings_form_types(form_type: list[str] | None) -> list[str]:
    if form_type is None:
        return list(_FILINGS_FAMILY_DEFAULT_FORM_TYPES)
    if not form_type:
        raise InvalidInputError('form_type must not be empty')

    invalid = [value for value in form_type if value not in FILINGS_FAMILY_FORM_TYPES]
    if invalid:
        offending = invalid[0]
        if offending == 'TRANSCRIPT':
            raise InvalidInputError(
                f"form_type {offending!r} not in filings family; use transcripts_search instead"
            )
        valid_family = ', '.join(_FILINGS_FAMILY_DEFAULT_FORM_TYPES)
        raise InvalidInputError(
            f"form_type {offending!r} not in filings family; valid form types: {valid_family}"
        )
    return list(form_type)


def _verify_latest_filing_alignment(
    *,
    document_id: str,
    ticker: str,
    year: int,
    quarter: int,
    base_form: str,
    expected_accession: str,
) -> None:
    try:
        filings_payload = edgar_api_client.get_filings(ticker, year, quarter)
    except edgar_api_client.EdgarAPIError as exc:
        raise ExcerptUnavailableError(
            document_id,
            reason=f'edgar_api /api/filings failed: {exc}',
        ) from exc

    matching = [
        filing for filing in (filings_payload.get('filings') or [])
        if str(filing.get('form', '')) == base_form
    ]
    if not matching:
        raise ExcerptUnavailableError(
            document_id,
            reason=f'no {base_form} filings in API response for {ticker} {year}Q{quarter}',
        )

    matching.sort(
        key=lambda filing: (str(filing.get('filing_date', '')), str(filing.get('accession', ''))),
        reverse=True,
    )
    latest_filing_date = str(matching[0].get('filing_date', '')).strip()
    if not latest_filing_date:
        raise ExcerptUnavailableError(
            document_id,
            reason=(
                f'/api/filings returned {len(matching)} {base_form} filing(s) for '
                f'{ticker} {year}Q{quarter} with no filing_date - cannot verify '
                'accession alignment'
            ),
        )

    same_date_matches = [
        filing for filing in matching
        if str(filing.get('filing_date', '')) == latest_filing_date
    ]
    if len(same_date_matches) > 1:
        raise ExcerptUnavailableError(
            document_id,
            reason=(
                f'{len(same_date_matches)} {base_form} filings on {latest_filing_date} for '
                f'{ticker} {year}Q{quarter}; API cannot disambiguate (F43 territory)'
            ),
        )

    latest_accession = str(matching[0].get('accession', ''))
    if latest_accession != expected_accession:
        raise ExcerptUnavailableError(
            document_id,
            reason=(
                f'corpus row accession {expected_accession} is not the latest for '
                f'{ticker} {year}Q{quarter} {base_form} (API has {latest_accession}); '
                'API cannot target older/amended/superseded filings'
            ),
        )


def _section_response_accession(api_payload: dict) -> str | None:
    filing = api_payload.get('filing')
    if not isinstance(filing, dict):
        return None
    accession = str(filing.get('accession') or '').strip()
    return accession or None


def _resolve_api_params_from_row(row: sqlite3.Row) -> tuple[int, int, str | None]:
    """Map a documents row to (year, quarter, source) for edgar_api."""
    form_type = str(row['form_type'])
    fiscal_period = str(row['fiscal_period'] or '').strip()
    base_form = form_type[:-2] if form_type.endswith('/A') else form_type
    source: str | None = _API_SOURCE_BY_BASE_FORM.get(base_form)

    if not fiscal_period:
        raise InvalidInputError(f"row missing fiscal_period for form_type {form_type}")

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


def _resolve_filing_document_row(
    *,
    db: sqlite3.Connection,
    document_id: str | None,
    ticker: str | None,
    form_type: str | None,
    fiscal_period: str | None,
) -> sqlite3.Row:
    if document_id is not None:
        row = db.execute(
            f"SELECT {', '.join(_FILING_SOURCE_LOOKUP_COLUMNS)} FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            raise ExcerptUnavailableError(document_id, reason='document not found')
        return row

    if ticker is None or form_type is None or fiscal_period is None:
        raise InvalidInputError(
            'provide document_id or the full (ticker, form_type, fiscal_period) tuple'
        )
    _validate_canonical_ticker(ticker, field='ticker')
    ticker = resolve_corpus_ticker_alias(db, ticker)

    rows = db.execute(
        """
        SELECT document_id, ticker, cik, form_type, fiscal_period, source_url, source_url_deep, source_accession
        FROM documents
        WHERE ticker = ?
          AND form_type = ?
          AND fiscal_period = ?
          AND source = 'edgar'
          AND is_superseded_by IS NULL
        ORDER BY document_id ASC
        """,
        (ticker, form_type, fiscal_period),
    ).fetchall()
    if not rows:
        raise ExcerptUnavailableError(
            f'edgar:{ticker}_{form_type}_{fiscal_period}',
            reason='document not found',
        )
    if len(rows) > 1:
        raise AmbiguousDocumentError(
            [str(row['document_id']) for row in rows],
            ticker=ticker,
            form_type=form_type,
            fiscal_period=fiscal_period,
        )
    return rows[0]


def _slice_text_with_offsets(
    text: str,
    char_start: int | None,
    char_end: int | None,
    *,
    base_start: int,
) -> tuple[str, int, int]:
    if char_start is None and char_end is None:
        return text, base_start, base_start + len(text)
    start = 0 if char_start is None else char_start
    end = len(text) if char_end is None else char_end
    if start < 0 or end < 0:
        raise InvalidInputError('char_start and char_end must be >= 0')
    if end < start:
        raise InvalidInputError('char_end must be >= char_start')
    return text[start:end], base_start + start, base_start + end


def _source_url_from_metadata(metadata: dict) -> str:
    return str(metadata.get('source_url_deep') or metadata.get('source_url') or '')


def _source_url_from_row(row: sqlite3.Row) -> str:
    return str(row['source_url_deep'] or row['source_url'] or '')


def _corpus_root() -> Path:
    raw = os.getenv('CORPUS_ROOT')
    return Path(raw).expanduser().resolve() if raw else _DEFAULT_CORPUS_ROOT.resolve()


def _corpus_db_path() -> Path:
    raw = os.getenv('CORPUS_DB_PATH')
    return Path(raw).expanduser().resolve() if raw else _DEFAULT_CORPUS_DB_PATH.resolve()


def _open_runtime_db() -> sqlite3.Connection:
    return open_corpus_db(_corpus_db_path())


__all__ = [
    'FILINGS_FAMILY_FORM_TYPES',
    'filings_list',
    'filings_read',
    'filings_search',
    'filings_source_excerpt',
]
