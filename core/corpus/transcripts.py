from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3

from core.corpus.db import open_corpus_db
from core.corpus.frontmatter import parse_frontmatter
from core.corpus.search import _resolved_source_url_sql, _search
from core.corpus.types import DocumentMetadata, ExcerptUnavailableError, InvalidInputError, SearchResponse
from core.corpus.validation import (
    _validate_canonical_ticker,
    validate_read_path,
    validate_search_inputs,
)
from fmp.tools.transcripts import get_earnings_transcript


_TRANSCRIPT_DOCUMENT_ID_RE = re.compile(
    r'^fmp_transcripts:(?P<ticker>[^_]+)_(?P<fiscal_period>\d{4}-Q(?P<quarter>[1-4]))$'
)
_TRANSCRIPT_SECTION_HEADERS = {
    'prepared_remarks': 'PREPARED REMARKS',
    'qa': 'Q&A SESSION',
}
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS_ROOT = _REPO_ROOT / 'data' / 'filings'
_DEFAULT_CORPUS_DB_PATH = _REPO_ROOT / 'data' / 'filings.db'


def transcripts_search(
    query: str,
    universe: list[str] | None = None,
    speaker_role: str | None = None,
    section: str = 'both',
    date_from: str | None = None,
    date_to: str | None = None,
    include_superseded: bool = False,
    include_low_confidence_supersession: bool = False,
    limit: int = 20,
) -> SearchResponse:
    validate_search_inputs(query, universe, limit)
    _validate_transcript_section(section, allow_both=True)

    db = _open_runtime_db()
    try:
        return _search(
            db=db,
            query=query,
            form_types=['TRANSCRIPT'],
            sources=['fmp_transcripts'],
            universe=universe,
            section=section,
            speaker_role=speaker_role,
            date_from=date_from,
            date_to=date_to,
            include_superseded=include_superseded,
            include_low_confidence_supersession=include_low_confidence_supersession,
            limit=limit,
        )
    finally:
        db.close()


def transcripts_read(
    file_path: str,
    section: str | None = None,
    speaker: str | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
) -> str:
    path = validate_read_path(file_path, _corpus_root())
    text = path.read_text(encoding='utf-8')

    if section is None and speaker is None and char_start is None and char_end is None:
        return text

    _metadata, body = parse_frontmatter(text)
    scoped_text = body

    if section is not None:
        section_key = _validate_transcript_section(section, allow_both=False)
        section_blocks = _extract_transcript_sections(body)
        scoped_text = section_blocks.get(section_key, '')
        if not scoped_text:
            raise InvalidInputError(f"section {section!r} not found in transcript")

    if speaker is not None:
        speaker_blocks = _extract_speaker_blocks(scoped_text, speaker)
        if not speaker_blocks:
            raise InvalidInputError(f"speaker {speaker!r} not found in transcript")
        scoped_text = '\n\n'.join(speaker_blocks)

    return _slice_text(scoped_text, char_start, char_end)


def transcripts_source_excerpt(
    document_id: str | None = None,
    speaker: str | None = None,
    ticker: str | None = None,
    fiscal_period: str | None = None,
) -> str:
    resolved_document_id = document_id
    if resolved_document_id is None:
        if ticker is None or fiscal_period is None:
            raise InvalidInputError('provide document_id or the full (ticker, fiscal_period) tuple')
        resolved_document_id = f'fmp_transcripts:{ticker.upper()}_{fiscal_period}'

    match = _TRANSCRIPT_DOCUMENT_ID_RE.fullmatch(resolved_document_id)
    if match is None:
        raise InvalidInputError(f'invalid transcript document_id {resolved_document_id!r}')

    symbol = match.group('ticker').upper()
    fiscal_period_value = match.group('fiscal_period')
    year = int(fiscal_period_value[:4])
    quarter = int(match.group('quarter'))

    if speaker is not None:
        result = get_earnings_transcript(
            symbol=symbol,
            year=year,
            quarter=quarter,
            filter_speaker=speaker,
            section='all',
            format='full',
            max_words=None,
            output='inline',
        )
        _raise_on_fmp_error(resolved_document_id, result)
        prepared_remarks = list(result.get('prepared_remarks') or [])
        qa = list(result.get('qa') or [])
    else:
        prepared_result = get_earnings_transcript(
            symbol=symbol,
            year=year,
            quarter=quarter,
            section='prepared_remarks',
            format='full',
            max_words=None,
            output='inline',
        )
        _raise_on_fmp_error(resolved_document_id, prepared_result)

        qa_result = get_earnings_transcript(
            symbol=symbol,
            year=year,
            quarter=quarter,
            section='qa',
            format='full',
            max_words=None,
            output='inline',
        )
        _raise_on_fmp_error(resolved_document_id, qa_result)

        prepared_remarks = list(prepared_result.get('prepared_remarks') or [])
        qa = list(qa_result.get('qa') or [])

    if not prepared_remarks and not qa:
        reason = 'no content for speaker filter' if speaker is not None else 'transcript has no content'
        raise ExcerptUnavailableError(resolved_document_id, reason=reason)

    lines: list[str] = []
    if prepared_remarks:
        lines.append('## PREPARED REMARKS')
        for segment in prepared_remarks:
            lines.append(_format_speaker_segment(segment))
    if qa:
        lines.append('## Q&A SESSION')
        for segment in qa:
            lines.append(_format_speaker_segment(segment))

    return '\n\n'.join(lines)


def transcripts_list(
    ticker: str | None = None,
    fiscal_period: str | None = None,
    *,
    db: sqlite3.Connection,
) -> list[DocumentMetadata]:
    clauses = ["d.source = 'fmp_transcripts'", "d.form_type = 'TRANSCRIPT'"]
    params: list[object] = []
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


def _extract_transcript_sections(body: str) -> dict[str, str]:
    matches = list(re.finditer(r'^## (?P<title>PREPARED REMARKS|Q&A SESSION)$', body, flags=re.MULTILINE))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        title = match.group('title')
        key = 'prepared_remarks' if title == 'PREPARED REMARKS' else 'qa'
        blocks[key] = body[start:end].rstrip()
    return blocks


def _extract_speaker_blocks(text: str, speaker: str) -> list[str]:
    matches = list(re.finditer(r'^### SPEAKER: (?P<header>.+)$', text, flags=re.MULTILINE))
    normalized_target = speaker.strip().casefold()
    blocks: list[str] = []

    for index, match in enumerate(matches):
        next_section = re.search(r'^## ', text[match.end():], flags=re.MULTILINE)
        next_speaker_start = matches[index + 1].start() if index + 1 < len(matches) else None
        next_section_start = match.end() + next_section.start() if next_section else None
        candidates = [value for value in (next_speaker_start, next_section_start, len(text)) if value is not None]
        end = min(candidates)

        speaker_name = match.group('header').split(' (', 1)[0].strip().casefold()
        if speaker_name == normalized_target:
            blocks.append(text[match.start():end].rstrip())

    return blocks


def _validate_transcript_section(section: str, *, allow_both: bool) -> str:
    allowed = {'prepared_remarks', 'qa'}
    if allow_both:
        allowed.add('both')
    if section not in allowed:
        allowed_display = ', '.join(sorted(allowed))
        raise InvalidInputError(f'section must be one of: {allowed_display}')
    return section


def _raise_on_fmp_error(document_id: str, result: dict) -> None:
    if result.get('status') == 'error':
        raise ExcerptUnavailableError(
            document_id,
            reason=f"FMP error: {result.get('error', 'unknown FMP error')}",
        )


def _format_speaker_segment(segment: dict) -> str:
    speaker_name = str(segment.get('speaker') or 'Unknown').strip() or 'Unknown'
    speaker_role = str(segment.get('role') or '').strip()
    heading = (
        f'### SPEAKER: {speaker_name} ({speaker_role})'
        if speaker_role
        else f'### SPEAKER: {speaker_name}'
    )
    return f"{heading}\n\n{str(segment.get('text') or '').strip()}".rstrip()


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
    'transcripts_list',
    'transcripts_read',
    'transcripts_search',
    'transcripts_source_excerpt',
]
