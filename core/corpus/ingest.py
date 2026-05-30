from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import uuid

from core.corpus._paths import normalize_corpus_path
from core.corpus.frontmatter import (
    FrontmatterValidationError,
    assemble_canonical_text,
    build_frontmatter,
    canonical_path,
    finalize_with_hash,
)
from core.corpus.html_mapping import (
    build_html_corpus_mapping_sidecar,
    ingest_mapping_sidecar,
    sidecar_path_for_canonical,
    write_mapping_sidecar,
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
    mapping_sidecar_path: Path | None = None
    mapping_record_count: int = 0


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
    'parser_version',
    'parser_schema_version',
    'parser_path',
    'parser_state',
    'parser_result_status',
    'cross_reference_target',
    'producer_deployment_id',
    'producer_instance_id',
    'producer_build_id',
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
    'parser_version',
    'parser_schema_version',
    'parser_path',
    'parser_state',
    'parser_result_status',
    'cross_reference_target',
    'producer_deployment_id',
    'producer_instance_id',
    'producer_build_id',
)


def ingest_raw(
    body: str,
    metadata: dict,
    corpus_root: Path,
    db: sqlite3.Connection,
    *,
    html_mapping_source: dict | None = None,
) -> IngestResult:
    """Single authoritative write path for corpus markdown and index rows."""
    build_frontmatter(metadata, with_placeholder_hash=True)
    assembled_text = assemble_canonical_text(metadata, body)

    corpus_root = normalize_corpus_path(corpus_root)
    staging_dir = corpus_root / '.staging'
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f'{uuid.uuid4()}.md'
    staging_path.write_text(assembled_text, encoding='utf-8')

    finalized_text, content_hash = finalize_with_hash(assembled_text)
    finalized_metadata = dict(metadata)
    finalized_metadata['content_hash'] = content_hash
    finalized_path = canonical_path(finalized_metadata, corpus_root)
    finalized_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_text(finalized_text, encoding='utf-8')
    os.rename(staging_path, finalized_path)

    sections = parse_sections(finalized_text, finalized_metadata['source'])
    mapping_sidecar = build_html_corpus_mapping_sidecar(
        finalized_text=finalized_text,
        metadata=finalized_metadata,
        sections=sections,
        sections_response=html_mapping_source,
        canonical_path=finalized_path,
    )
    mapping_sidecar_path: Path | None = None
    mapping_sidecar_hash: str | None = None
    if mapping_sidecar is not None:
        mapping_sidecar_path = sidecar_path_for_canonical(finalized_path)
        staging_sidecar_path = staging_dir / f'{uuid.uuid4()}.html_corpus_map.v1.json'
        mapping_sidecar_hash = write_mapping_sidecar(staging_sidecar_path, mapping_sidecar)
        os.rename(staging_sidecar_path, mapping_sidecar_path)

    document_row = _build_document_row(finalized_metadata, finalized_path)
    mapping_record_count = 0

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
        if mapping_sidecar is not None and mapping_sidecar_path is not None and mapping_sidecar_hash is not None:
            mapping_result = ingest_mapping_sidecar(
                db,
                sidecar=mapping_sidecar,
                sidecar_path=mapping_sidecar_path,
                sidecar_hash=mapping_sidecar_hash,
            )
            mapping_record_count = mapping_result.record_count
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
        mapping_sidecar_path=mapping_sidecar_path,
        mapping_record_count=mapping_record_count,
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
