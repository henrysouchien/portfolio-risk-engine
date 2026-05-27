from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3

from core.corpus._paths import normalize_corpus_path
from core.corpus.db import open_corpus_db
from core.corpus.frontmatter import parse_frontmatter
from core.corpus.search import _quality_filter_sql, _resolved_source_url_sql, _search
from core.corpus.types import DocumentMetadata, ExcerptUnavailableError, InvalidInputError, ReadResult, SearchResponse
from core.corpus.validation import (
    _validate_canonical_ticker,
    resolve_corpus_ticker_alias,
    validate_read_path,
    validate_search_inputs,
)
from fmp.tools.transcripts import get_earnings_transcript


_TRANSCRIPT_DOCUMENT_ID_RE = re.compile(
    r'^fmp_transcripts:(?P<ticker>[^_]+)_(?P<fiscal_period>\d{4}-Q(?P<quarter>[1-4]))$'
)
_TRANSCRIPT_SECTION_LABELS = {
    'prepared_remarks': 'Prepared Remarks',
    'qa': 'Q&A Session',
}
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CORPUS_ROOT = _REPO_ROOT / 'data' / 'filings'
_DEFAULT_CORPUS_DB_PATH = _REPO_ROOT / 'data' / 'filings.db'


@dataclass(frozen=True)
class _TextSpan:
    content: str
    char_start: int
    char_end: int


def transcripts_search(
    query: str,
    universe: list[str] | None = None,
    speaker_role: str | None = None,
    section: str = 'both',
    date_from: str | None = None,
    date_to: str | None = None,
    include_superseded: bool = False,
    include_low_quality: bool = False,
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
            include_low_quality=include_low_quality,
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
) -> ReadResult:
    path = validate_read_path(file_path, _corpus_root())
    text = path.read_text(encoding='utf-8')
    metadata, body = parse_frontmatter(text)
    body_start = len(text) - len(body)

    if section is None and speaker is None and char_start is None and char_end is None:
        return ReadResult(
            content=text,
            document_id=str(metadata['document_id']),
            section=None,
            char_start=0,
            char_end=len(text),
            url=_source_url_from_metadata(metadata),
        )

    scoped_text = body
    scoped_start = body_start
    scoped_source_end = body_start + len(body)
    resolved_section: str | None = None

    if section is not None:
        section_key = _validate_transcript_section(section, allow_both=False)
        section_blocks = _extract_transcript_section_spans(body)
        section_block = section_blocks.get(section_key)
        if section_block is None:
            raise InvalidInputError(f"section {section!r} not found in transcript")
        scoped_text = section_block.content
        scoped_start = body_start + section_block.char_start
        scoped_source_end = body_start + section_block.char_end
        resolved_section = _TRANSCRIPT_SECTION_LABELS[section_key]

    if speaker is not None:
        speaker_blocks = _extract_speaker_block_spans(scoped_text, speaker)
        if not speaker_blocks:
            raise InvalidInputError(f"speaker {speaker!r} not found in transcript")
        scoped_text = '\n\n'.join(block.content for block in speaker_blocks)
        speaker_start = min(block.char_start for block in speaker_blocks)
        speaker_end = max(block.char_end for block in speaker_blocks)
        scoped_source_end = scoped_start + speaker_end
        scoped_start += speaker_start

    if char_start is None and char_end is None:
        content = scoped_text
        resolved_start = scoped_start
        resolved_end = scoped_source_end
    else:
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


def transcripts_source_excerpt(
    document_id: str | None = None,
    speaker: str | None = None,
    ticker: str | None = None,
    fiscal_period: str | None = None,
) -> ReadResult:
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

    content = '\n\n'.join(lines)
    return ReadResult(
        content=content,
        document_id=resolved_document_id,
        section=_source_excerpt_section(prepared_remarks=prepared_remarks, qa=qa),
        char_start=0,
        char_end=len(content),
        url=_transcript_source_url(symbol, fiscal_period_value),
    )


def transcripts_list(
    ticker: str | None = None,
    fiscal_period: str | None = None,
    *,
    include_low_quality: bool = False,
    db: sqlite3.Connection,
) -> list[DocumentMetadata]:
    clauses = ["d.source = 'fmp_transcripts'", "d.form_type = 'TRANSCRIPT'"]
    params: list[object] = []
    if ticker is not None:
        _validate_canonical_ticker(ticker, field='ticker')
        ticker = resolve_corpus_ticker_alias(db, ticker)
        clauses.append('d.ticker = ?')
        params.append(ticker)
    if fiscal_period is not None:
        clauses.append('d.fiscal_period = ?')
        params.append(fiscal_period)
    if not include_low_quality:
        clauses.append(_quality_filter_sql('d'))

    rows = db.execute(
        f"""
        SELECT
            d.document_id,
            d.ticker,
            d.form_type,
            COALESCE(d.fiscal_period, '') AS fiscal_period,
            COALESCE(CAST(d.filing_date AS TEXT), '') AS filing_date,
            COALESCE(d.extraction_status, 'complete') AS extraction_status,
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
            extraction_status=str(row['extraction_status'] or 'complete'),
            is_superseded=bool(row['is_superseded']),
            file_path=str(row['file_path']),
            source_url=str(row['source_url'] or ''),
        )
        for row in rows
    ]


def _extract_transcript_section_spans(body: str) -> dict[str, _TextSpan]:
    matches = list(re.finditer(r'^## (?P<title>PREPARED REMARKS|Q&A SESSION)$', body, flags=re.MULTILINE))
    blocks: dict[str, _TextSpan] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        title = match.group('title')
        key = 'prepared_remarks' if title == 'PREPARED REMARKS' else 'qa'
        content = body[start:end].rstrip()
        blocks[key] = _TextSpan(content=content, char_start=start, char_end=start + len(content))
    return blocks


def _extract_speaker_block_spans(text: str, speaker: str) -> list[_TextSpan]:
    matches = list(re.finditer(r'^### SPEAKER: (?P<header>.+)$', text, flags=re.MULTILINE))
    normalized_target = speaker.strip().casefold()
    blocks: list[_TextSpan] = []

    for index, match in enumerate(matches):
        next_section = re.search(r'^## ', text[match.end():], flags=re.MULTILINE)
        next_speaker_start = matches[index + 1].start() if index + 1 < len(matches) else None
        next_section_start = match.end() + next_section.start() if next_section else None
        candidates = [value for value in (next_speaker_start, next_section_start, len(text)) if value is not None]
        end = min(candidates)

        speaker_name = match.group('header').split(' (', 1)[0].strip().casefold()
        if speaker_name == normalized_target:
            content = text[match.start():end].rstrip()
            blocks.append(_TextSpan(content=content, char_start=match.start(), char_end=match.start() + len(content)))

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


def _source_excerpt_section(*, prepared_remarks: list[dict], qa: list[dict]) -> str:
    if prepared_remarks and qa:
        return 'Prepared Remarks + Q&A Session'
    if prepared_remarks:
        return 'Prepared Remarks'
    return 'Q&A Session'


def _source_url_from_metadata(metadata: dict) -> str:
    source_url = metadata.get('source_url_deep') or metadata.get('source_url')
    if source_url:
        return str(source_url)
    ticker = str(metadata.get('ticker') or '').strip().upper()
    fiscal_period = str(metadata.get('fiscal_period') or '').strip()
    if ticker and fiscal_period:
        return _transcript_source_url(ticker, fiscal_period)
    return ''


def _transcript_source_url(symbol: str, fiscal_period: str) -> str:
    match = re.fullmatch(r'(?P<year>\d{4})-Q(?P<quarter>[1-4])', fiscal_period)
    if match is None:
        return ''
    return (
        'https://financialmodelingprep.com/financial-summary/'
        f'{symbol.upper()}?transcript={match.group("year")}Q{match.group("quarter")}'
    )


def _corpus_root() -> Path:
    raw = os.getenv('CORPUS_ROOT')
    return normalize_corpus_path(raw) if raw else _DEFAULT_CORPUS_ROOT


def _corpus_db_path() -> Path:
    raw = os.getenv('CORPUS_DB_PATH')
    return normalize_corpus_path(raw) if raw else _DEFAULT_CORPUS_DB_PATH


def _open_runtime_db() -> sqlite3.Connection:
    return open_corpus_db(_corpus_db_path())


__all__ = [
    'transcripts_list',
    'transcripts_read',
    'transcripts_search',
    'transcripts_source_excerpt',
]
