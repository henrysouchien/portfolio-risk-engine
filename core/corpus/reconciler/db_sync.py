from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from logging import Logger
from pathlib import Path
import sqlite3

from core.corpus.frontmatter import FRONTMATTER_PATTERN, FrontmatterValidationError, parse_frontmatter
from core.corpus.reconciler.walker import AuthoritativeFile
from core.corpus.section_map import parse_sections
from core.corpus.supersession import update_is_superseded_by


_DOCUMENT_COLUMNS = (
    'document_id',
    'ticker',
    'cik',
    'company_name',
    'source',
    'form_type',
    'fiscal_period',
    'filing_date',
    'period_end',
    'source_url',
    'source_url_deep',
    'source_accession',
    'file_path',
    'content_hash',
    'extraction_pipeline',
    'extraction_model',
    'extraction_at',
    'extraction_status',
    'sector',
    'industry',
    'sector_source',
    'exchange',
    'supersedes',
    'supersedes_source',
    'supersedes_confidence',
)
_UPSERT_COLUMNS = _DOCUMENT_COLUMNS + ('last_indexed',)
_UPDATE_COLUMNS = tuple(column for column in _DOCUMENT_COLUMNS if column != 'document_id')


@dataclass(frozen=True)
class DBSyncReport:
    rows_inserted: int
    rows_updated: int
    rows_marked_orphan: int
    divergences: int


@dataclass(frozen=True)
class SectionsFtsReport:
    document_ids_refreshed: int
    total_sections_inserted: int


def sync_documents(
    db: sqlite3.Connection,
    scan_result: dict[str, AuthoritativeFile],
    logger: Logger,
) -> DBSyncReport:
    """Apply authoritative scan results to the documents table."""
    existing_rows = {
        row['document_id']: row
        for row in db.execute(_select_documents_sql())
    }
    available_document_ids = set(existing_rows)

    rows_inserted = 0
    rows_updated = 0
    now_value = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')

    pending = sorted(scan_result.items(), key=lambda item: item[0])
    while pending:
        next_round = []
        progressed = False

        for document_id, authoritative in pending:
            desired_row = _document_row_for(authoritative)
            supersedes = desired_row.get('supersedes')
            if (
                isinstance(supersedes, str)
                and supersedes in scan_result
                and supersedes not in available_document_ids
            ):
                next_round.append((document_id, authoritative))
                continue

            existing = existing_rows.get(document_id)
            if existing is None:
                db.execute(
                    _insert_documents_sql(),
                    tuple(desired_row[column] for column in _DOCUMENT_COLUMNS) + (now_value,),
                )
                rows_inserted += 1
            elif _documents_differ(existing, desired_row):
                db.execute(
                    _update_documents_sql(),
                    tuple(desired_row[column] for column in _UPDATE_COLUMNS) + (now_value, document_id),
                )
                rows_updated += 1

            available_document_ids.add(document_id)
            progressed = True

        if not next_round:
            break

        if not progressed:
            for document_id, authoritative in next_round:
                desired_row = _document_row_for(authoritative)
                existing = existing_rows.get(document_id)
                if existing is None:
                    db.execute(
                        _insert_documents_sql(),
                        tuple(desired_row[column] for column in _DOCUMENT_COLUMNS) + (now_value,),
                    )
                    rows_inserted += 1
                elif _documents_differ(existing, desired_row):
                    db.execute(
                        _update_documents_sql(),
                        tuple(desired_row[column] for column in _UPDATE_COLUMNS) + (now_value, document_id),
                    )
                    rows_updated += 1
                available_document_ids.add(document_id)
            break

        pending = next_round

    authoritative_paths = {str(authoritative.file_path) for authoritative in scan_result.values()}
    rows_marked_orphan = 0
    for row in db.execute('SELECT document_id, file_path FROM documents ORDER BY document_id'):
        if row['document_id'] in scan_result:
            continue
        if row['file_path'] in authoritative_paths:
            continue

        rows_marked_orphan += 1
        logger.warning(
            'orphan_document_row: document_id=%s file_path=%s',
            row['document_id'],
            row['file_path'],
        )

    return DBSyncReport(
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        rows_marked_orphan=rows_marked_orphan,
        divergences=sum(1 for authoritative in scan_result.values() if authoritative.other_files),
    )


def sync_sections_fts(
    db: sqlite3.Connection,
    scan_result: dict[str, AuthoritativeFile],
) -> SectionsFtsReport:
    """Delete and rebuild sections_fts rows from authoritative disk files."""
    total_sections_inserted = 0

    for document_id, authoritative in scan_result.items():
        text = authoritative.file_path.read_text(encoding='utf-8')
        body = _extract_body(text)
        source = str(authoritative.frontmatter['source'])
        parse_input = text if source in {'edgar', 'fmp_transcripts'} else body
        sections = parse_sections(parse_input, source=source)

        db.execute('DELETE FROM sections_fts WHERE document_id = ?', (document_id,))
        for section in sections:
            db.execute(
                """
                INSERT INTO sections_fts (
                    document_id,
                    section,
                    content,
                    char_start,
                    char_end,
                    speaker_name,
                    speaker_role
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    section.section,
                    section.content,
                    section.char_start,
                    section.char_end,
                    section.speaker_name,
                    section.speaker_role,
                ),
            )
            total_sections_inserted += 1

    return SectionsFtsReport(
        document_ids_refreshed=len(scan_result),
        total_sections_inserted=total_sections_inserted,
    )


def recompute_supersession(db: sqlite3.Connection) -> int:
    """Recompute is_superseded_by globally from high-confidence supersedes pointers."""
    return update_is_superseded_by(db, document_id=None)


def _document_row_for(authoritative: AuthoritativeFile) -> dict[str, object]:
    row = {column: authoritative.frontmatter.get(column) for column in _DOCUMENT_COLUMNS}
    row['document_id'] = authoritative.document_id
    row['file_path'] = str(authoritative.file_path)
    row['content_hash'] = authoritative.content_hash
    row.setdefault('extraction_status', 'complete')
    return row


def _documents_differ(existing: sqlite3.Row, desired: dict[str, object]) -> bool:
    for column in _DOCUMENT_COLUMNS:
        if column == 'document_id':
            continue
        if _normalize_db_value(existing[column]) != desired[column]:
            return True
    return False


def _normalize_db_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _insert_documents_sql() -> str:
    columns = ', '.join(_UPSERT_COLUMNS)
    placeholders = ', '.join('?' for _ in _UPSERT_COLUMNS)
    return f'INSERT INTO documents ({columns}) VALUES ({placeholders})'


def _select_documents_sql() -> str:
    select_columns = []
    for column in _UPSERT_COLUMNS:
        if column in {'filing_date', 'period_end', 'extraction_at', 'last_indexed'}:
            select_columns.append(f'CAST({column} AS TEXT) AS {column}')
        else:
            select_columns.append(column)
    return f"SELECT {', '.join(select_columns)} FROM documents"


def _update_documents_sql() -> str:
    assignments = ', '.join(f'{column} = ?' for column in _UPDATE_COLUMNS)
    return f'UPDATE documents SET {assignments}, last_indexed = ? WHERE document_id = ?'


def _extract_body(text: str) -> str:
    try:
        _, body = parse_frontmatter(text)
        return body
    except FrontmatterValidationError:
        match = FRONTMATTER_PATTERN.match(text)
        if match is None:
            raise
        return match.group('body') or ''


__all__ = [
    'DBSyncReport',
    'SectionsFtsReport',
    'recompute_supersession',
    'sync_documents',
    'sync_sections_fts',
]
