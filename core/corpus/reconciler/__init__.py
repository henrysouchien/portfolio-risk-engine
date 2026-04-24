from __future__ import annotations

from dataclasses import dataclass
from logging import Logger, getLogger
from pathlib import Path
import sqlite3

from core.corpus.reconciler.db_sync import (
    DBSyncReport,
    SectionsFtsReport,
    recompute_supersession,
    sync_documents,
    sync_sections_fts,
)
from core.corpus.reconciler.walker import AuthoritativeFile, scan_corpus


@dataclass(frozen=True)
class ReconcilerReport:
    doc_report: DBSyncReport
    sections_report: SectionsFtsReport
    supersession_updates: int
    divergences: list[AuthoritativeFile]


def reconcile(
    corpus_root: Path,
    db: sqlite3.Connection,
    logger: Logger | None = None,
) -> ReconcilerReport:
    """Reconcile corpus files back into documents, sections_fts, and supersession state."""
    logger = logger or getLogger(__name__)

    with db:
        scan = scan_corpus(corpus_root)
        doc_report = sync_documents(db, scan, logger)
        sections_report = sync_sections_fts(db, scan)
        supersession_updates = recompute_supersession(db)
        divergences = [authoritative for authoritative in scan.values() if authoritative.other_files]
        for authoritative in divergences:
            logger.warning(
                'content_divergence: document_id=%s authoritative=%s other_files=%s',
                authoritative.document_id,
                authoritative.file_path,
                authoritative.other_files,
            )

    return ReconcilerReport(
        doc_report=doc_report,
        sections_report=sections_report,
        supersession_updates=supersession_updates,
        divergences=divergences,
    )


__all__ = [
    'AuthoritativeFile',
    'DBSyncReport',
    'ReconcilerReport',
    'SectionsFtsReport',
    'reconcile',
    'recompute_supersession',
    'scan_corpus',
    'sync_documents',
    'sync_sections_fts',
]
