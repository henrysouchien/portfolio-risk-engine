from __future__ import annotations

import sqlite3


def update_is_superseded_by(
    db: sqlite3.Connection,
    document_id: str | None = None,
) -> int:
    """Apply the confidence-gated D14 derived-column rule."""
    if document_id is None:
        cur1 = db.execute('UPDATE documents SET is_superseded_by = NULL')
        cur2 = db.execute(
            """
            UPDATE documents SET is_superseded_by = (
                SELECT d2.document_id FROM documents d2
                WHERE d2.supersedes = documents.document_id
                  AND d2.supersedes_confidence = 'high'
                ORDER BY d2.filing_date DESC, d2.document_id DESC
                LIMIT 1
            )
            """
        )
        return (cur1.rowcount or 0) + (cur2.rowcount or 0)

    cur = db.execute(
        """
        UPDATE documents SET is_superseded_by = (
            SELECT d2.document_id FROM documents d2
            WHERE d2.supersedes = documents.document_id
              AND d2.supersedes_confidence = 'high'
            ORDER BY d2.filing_date DESC, d2.document_id DESC
            LIMIT 1
        )
        WHERE document_id = ?
        """,
        (document_id,),
    )
    return cur.rowcount or 0


__all__ = ['update_is_superseded_by']
