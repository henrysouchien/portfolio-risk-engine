from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import uuid

from core.corpus.frontmatter import (
    FrontmatterValidationError,
    assemble_canonical_text,
    build_frontmatter,
    canonical_path,
    finalize_with_hash,
)
from core.corpus.section_map import parse_sections
from core.corpus.supersession import update_is_superseded_by


@dataclass(frozen=True)
class IngestResult:
    status: str
    document_id: str
    content_hash: str
    canonical_path: Path
    warnings: list[str]


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

_UPSERT_MUTABLE_COLUMNS = (
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


def ingest_raw(
    body: str,
    metadata: dict,
    corpus_root: Path,
    db: sqlite3.Connection,
) -> IngestResult:
    """Single authoritative write path for corpus markdown and index rows."""
    build_frontmatter(metadata, with_placeholder_hash=True)
    assembled_text = assemble_canonical_text(metadata, body)

    corpus_root = Path(corpus_root).resolve()
    staging_dir = corpus_root / '.staging'
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f'{uuid.uuid4()}.md'
    staging_path.write_text(assembled_text, encoding='utf-8')

    finalized_text, content_hash = finalize_with_hash(assembled_text)
    finalized_metadata = dict(metadata)
    finalized_metadata['content_hash'] = content_hash
    finalized_path = canonical_path(finalized_metadata, corpus_root).resolve()
    finalized_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_text(finalized_text, encoding='utf-8')
    os.rename(staging_path, finalized_path)

    sections = parse_sections(finalized_text, finalized_metadata['source'])
    document_row = _build_document_row(finalized_metadata, finalized_path)

    with db:
        db.execute(_documents_upsert_sql(), tuple(document_row[column] for column in _DOCUMENT_COLUMNS))
        db.execute('DELETE FROM sections_fts WHERE document_id = ?', (document_row['document_id'],))
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
                    document_row['document_id'],
                    section.section,
                    section.content,
                    section.char_start,
                    section.char_end,
                    section.speaker_name,
                    section.speaker_role,
                ),
            )
        if (
            document_row.get('supersedes')
            and document_row.get('supersedes_confidence') == 'high'
        ):
            update_is_superseded_by(db, document_id=document_row['supersedes'])

    return IngestResult(
        status='complete',
        document_id=document_row['document_id'],
        content_hash=content_hash,
        canonical_path=finalized_path,
        warnings=[],
    )


def _build_document_row(metadata: dict, canonical_file_path: Path) -> dict[str, object]:
    row = {column: metadata.get(column) for column in _DOCUMENT_COLUMNS}
    row['file_path'] = str(canonical_file_path)
    row['content_hash'] = metadata['content_hash']
    row.setdefault('extraction_status', 'complete')
    return row


def _documents_upsert_sql() -> str:
    columns = ', '.join(_DOCUMENT_COLUMNS)
    placeholders = ', '.join('?' for _ in _DOCUMENT_COLUMNS)
    updates = ', '.join(f'{column} = excluded.{column}' for column in _UPSERT_MUTABLE_COLUMNS)
    return (
        f'INSERT INTO documents ({columns}) VALUES ({placeholders}) '
        f'ON CONFLICT(document_id) DO UPDATE SET {updates}'
    )


__all__ = ['FrontmatterValidationError', 'IngestResult', 'ingest_raw']
