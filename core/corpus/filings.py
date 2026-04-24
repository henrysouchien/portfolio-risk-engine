from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys

import httpx

from core.corpus.db import open_corpus_db
from core.corpus.edgar_urls import SEC_USER_AGENT, fetch_primary_document_html
from core.corpus.frontmatter import parse_frontmatter
from core.corpus.search import _resolved_source_url_sql, _search
from core.corpus.section_map import corpus_header_to_edgar_id, parse_sections
from core.corpus.types import (
    AmbiguousDocumentError,
    DocumentMetadata,
    ExcerptUnavailableError,
    InvalidInputError,
    SearchResponse,
)
from core.corpus.validation import (
    _validate_canonical_ticker,
    validate_read_path,
    validate_search_inputs,
)


FILINGS_FAMILY_FORM_TYPES = frozenset({'10-K', '10-Q', '8-K'})
_FILINGS_FAMILY_DEFAULT_FORM_TYPES = ['10-K', '10-Q', '8-K']
_EXCERPT_FORM_TYPES = {
    '10-K': '10-K',
    '10-K/A': '10-K',
    '10-Q': '10-Q',
    '10-Q/A': '10-Q',
    '8-K': '8-K',
    '8-K/A': '8-K',
}
_FILING_SOURCE_LOOKUP_COLUMNS = (
    'document_id',
    'cik',
    'form_type',
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
) -> str:
    path = validate_read_path(file_path, _corpus_root())
    text = path.read_text(encoding='utf-8')

    if section is None and char_start is None and char_end is None:
        return text

    scoped_text = text
    if section is not None:
        _metadata, body = parse_frontmatter(text)
        for row in parse_sections(body, source='edgar'):
            if row.section == section:
                scoped_text = row.content
                break
        else:
            raise InvalidInputError(f"section {section!r} not found in filing")

    return _slice_text(scoped_text, char_start, char_end)


def filings_source_excerpt(
    document_id: str | None = None,
    section: str | None = None,
    ticker: str | None = None,
    form_type: str | None = None,
    fiscal_period: str | None = None,
    *,
    db: sqlite3.Connection,
) -> str:
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

    canonical_section_id = corpus_header_to_edgar_id(section, normalized_form_type)
    if canonical_section_id is None:
        raise ExcerptUnavailableError(
            resolved_document_id,
            reason=f"section {section!r} unsupported for form_type {row['form_type']}",
        )

    html_content = _fetch_filing_html(row)
    parsed = parse_filing_sections(html_content, normalized_form_type)
    section_payload = (parsed.get('sections') or {}).get(canonical_section_id)
    text = str((section_payload or {}).get('text') or '').strip()
    if not text:
        raise ExcerptUnavailableError(
            resolved_document_id,
            reason=f"section {section!r} not found in source filing",
        )
    return text


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


def parse_filing_sections(html_content: bytes | str, filing_type: str) -> dict:
    parser = _load_edgar_section_parser()
    return parser.parse_filing_sections(html_content, filing_type)


def _load_edgar_section_parser():
    try:
        import edgar_parser.section_parser as section_parser
    except ModuleNotFoundError:
        edgar_root = Path(__file__).resolve().parents[3] / 'Edgar_updater'
        if str(edgar_root) not in sys.path:
            sys.path.insert(0, str(edgar_root))
        import edgar_parser.section_parser as section_parser
    return section_parser


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

    rows = db.execute(
        """
        SELECT document_id, cik, form_type, source_url_deep, source_accession
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


def _fetch_filing_html(row: sqlite3.Row) -> str:
    source_url_deep = row['source_url_deep']
    if source_url_deep:
        response = httpx.get(
            str(source_url_deep),
            headers={'User-Agent': SEC_USER_AGENT},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.text

    cik = row['cik']
    accession = row['source_accession']
    if cik and accession:
        try:
            return fetch_primary_document_html(str(cik), str(accession))
        except Exception as exc:
            raise ExcerptUnavailableError(
                str(row['document_id']),
                reason=f'accession-keyed SEC fetch failed: {exc}',
            ) from exc

    raise ExcerptUnavailableError(
        str(row['document_id']),
        reason='missing source_url_deep and accession/cik fallback',
    )


def _slice_text(text: str, char_start: int | None, char_end: int | None) -> str:
    if char_start is None and char_end is None:
        return text
    start = 0 if char_start is None else char_start
    end = len(text) if char_end is None else char_end
    if start < 0 or end < 0:
        raise InvalidInputError('char_start and char_end must be >= 0')
    if end < start:
        raise InvalidInputError('char_end must be >= char_start')
    return text[start:end]


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
