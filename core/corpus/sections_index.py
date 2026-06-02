from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from core.corpus.section_map import SectionRow


def delete_sections_for_document(db: sqlite3.Connection, document_id: str) -> None:
    """Delete FTS rows and sidecar metadata for one document."""
    db.execute('DELETE FROM sections_fts_metadata WHERE document_id = ?', (document_id,))
    db.execute('DELETE FROM sections_fts WHERE document_id = ?', (document_id,))


def replace_sections_for_document(
    db: sqlite3.Connection,
    document_id: str,
    sections: Iterable[SectionRow],
) -> int:
    """Replace one document's FTS rows and sidecar rows in the same transaction."""
    document = _document_metadata(db, document_id)
    delete_sections_for_document(db, document_id)

    inserted = 0
    for section in sections:
        cursor = db.execute(
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
        _insert_section_metadata(
            db,
            fts_rowid=int(cursor.lastrowid),
            document=document,
            section=section,
        )
        inserted += 1
    return inserted


def rebuild_sections_fts_metadata(db: sqlite3.Connection) -> int:
    """Rebuild sidecar metadata from existing documents and sections_fts rows."""
    with db:
        db.execute('DELETE FROM sections_fts_metadata')
        cursor = db.execute(
            """
            INSERT INTO sections_fts_metadata (
                fts_rowid,
                document_id,
                ticker,
                source,
                form_type,
                fiscal_period,
                filing_date,
                extraction_status,
                sector,
                is_superseded_by,
                section,
                speaker_name,
                speaker_role,
                char_start,
                char_end
            )
            SELECT
                s.rowid,
                s.document_id,
                d.ticker,
                d.source,
                d.form_type,
                d.fiscal_period,
                CAST(d.filing_date AS TEXT),
                COALESCE(d.extraction_status, 'complete'),
                d.sector,
                d.is_superseded_by,
                s.section,
                s.speaker_name,
                s.speaker_role,
                s.char_start,
                s.char_end
            FROM sections_fts s
            JOIN documents d ON d.document_id = s.document_id
            """
        )
        mark_sections_fts_metadata_complete(db)
    return int(cursor.rowcount or 0)


def mark_sections_fts_metadata_complete(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT INTO sections_fts_metadata_state (id, is_complete, refreshed_at)
        VALUES (1, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            is_complete = excluded.is_complete,
            refreshed_at = excluded.refreshed_at
        """
    )


def mark_sections_fts_metadata_incomplete(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT INTO sections_fts_metadata_state (id, is_complete, refreshed_at)
        VALUES (1, 0, NULL)
        ON CONFLICT(id) DO UPDATE SET
            is_complete = excluded.is_complete,
            refreshed_at = excluded.refreshed_at
        """
    )


def sections_fts_metadata_is_complete(db: sqlite3.Connection) -> bool:
    try:
        row = db.execute(
            'SELECT is_complete FROM sections_fts_metadata_state WHERE id = 1'
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return bool(row and int(row['is_complete']) == 1)


def refresh_sections_metadata_for_document(
    db: sqlite3.Connection,
    document_id: str,
) -> None:
    """Refresh mutable document metadata copied into sidecar rows."""
    document = _document_metadata(db, document_id)
    db.execute(
        """
        UPDATE sections_fts_metadata
        SET
            ticker = ?,
            source = ?,
            form_type = ?,
            fiscal_period = ?,
            filing_date = ?,
            extraction_status = ?,
            sector = ?,
            is_superseded_by = ?
        WHERE document_id = ?
        """,
        (
            document['ticker'],
            document['source'],
            document['form_type'],
            document['fiscal_period'],
            document['filing_date'],
            document['extraction_status'],
            document['sector'],
            document['is_superseded_by'],
            document_id,
        ),
    )


def refresh_all_sections_metadata_from_documents(db: sqlite3.Connection) -> None:
    db.execute(
        """
        UPDATE sections_fts_metadata
        SET
            ticker = (
                SELECT d.ticker FROM documents d
                WHERE d.document_id = sections_fts_metadata.document_id
            ),
            source = (
                SELECT d.source FROM documents d
                WHERE d.document_id = sections_fts_metadata.document_id
            ),
            form_type = (
                SELECT d.form_type FROM documents d
                WHERE d.document_id = sections_fts_metadata.document_id
            ),
            fiscal_period = (
                SELECT d.fiscal_period FROM documents d
                WHERE d.document_id = sections_fts_metadata.document_id
            ),
            filing_date = (
                SELECT CAST(d.filing_date AS TEXT) FROM documents d
                WHERE d.document_id = sections_fts_metadata.document_id
            ),
            extraction_status = COALESCE((
                SELECT d.extraction_status FROM documents d
                WHERE d.document_id = sections_fts_metadata.document_id
            ), 'complete'),
            sector = (
                SELECT d.sector FROM documents d
                WHERE d.document_id = sections_fts_metadata.document_id
            ),
            is_superseded_by = (
                SELECT d.is_superseded_by FROM documents d
                WHERE d.document_id = sections_fts_metadata.document_id
            )
        """
    )


def _document_metadata(db: sqlite3.Connection, document_id: str) -> Mapping[str, Any]:
    row = db.execute(
        """
        SELECT
            document_id,
            ticker,
            source,
            form_type,
            fiscal_period,
            CAST(filing_date AS TEXT) AS filing_date,
            COALESCE(extraction_status, 'complete') AS extraction_status,
            sector,
            is_superseded_by
        FROM documents
        WHERE document_id = ?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f'document row missing for sections_fts metadata: {document_id}')
    return row


def _insert_section_metadata(
    db: sqlite3.Connection,
    *,
    fts_rowid: int,
    document: Mapping[str, Any],
    section: SectionRow,
) -> None:
    db.execute(
        """
        INSERT INTO sections_fts_metadata (
            fts_rowid,
            document_id,
            ticker,
            source,
            form_type,
            fiscal_period,
            filing_date,
            extraction_status,
            sector,
            is_superseded_by,
            section,
            speaker_name,
            speaker_role,
            char_start,
            char_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fts_rowid,
            document['document_id'],
            document['ticker'],
            document['source'],
            document['form_type'],
            document['fiscal_period'],
            document['filing_date'],
            document['extraction_status'],
            document['sector'],
            document['is_superseded_by'],
            section.section,
            section.speaker_name,
            section.speaker_role,
            section.char_start,
            section.char_end,
        ),
    )


__all__ = [
    'delete_sections_for_document',
    'mark_sections_fts_metadata_complete',
    'mark_sections_fts_metadata_incomplete',
    'rebuild_sections_fts_metadata',
    'refresh_all_sections_metadata_from_documents',
    'refresh_sections_metadata_for_document',
    'replace_sections_for_document',
    'sections_fts_metadata_is_complete',
]
