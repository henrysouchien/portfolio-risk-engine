from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable, Mapping
import uuid

from core.corpus import edgar_api_client
from core.corpus.filings import _resolve_api_params_from_row
from core.corpus.frontmatter import (
    assemble_canonical_text,
    canonical_path,
    finalize_with_hash,
    parse_frontmatter,
)
from core.corpus.ingest import _DOCUMENT_COLUMNS, _build_document_row, _documents_upsert_sql
from core.corpus.section_map import parse_sections
from core.corpus.supersession import update_is_superseded_by
from scripts.corpus_ingest_accession import _assemble_body_from_api_response, derive_provenance


_LOG = logging.getLogger(__name__)
_TERMINAL_STATUSES = {'complete', 'no_change', 'abandoned'}
_FAILED_STATUSES = {
    'planned_failed',
    'new_written_failed',
    'db_upserted_failed',
    'old_deleted_failed',
}
_PLANNED_RETRY_THRESHOLD = timedelta(hours=24)
_DOCUMENT_SELECT_COLUMNS = tuple(
    f'CAST({column} AS TEXT) AS {column}'
    if column in {'filing_date', 'period_end', 'extraction_at'}
    else column
    for column in _DOCUMENT_COLUMNS
)
_LOG_SELECT_COLUMNS = """
    id,
    document_id,
    accession,
    ticker,
    old_file_path,
    new_file_path,
    old_content_hash,
    new_content_hash,
    content_changed,
    parser_version_before,
    parser_version_after,
    reason,
    invalidation_id,
    status,
    CAST(started_at AS TEXT) AS started_at,
    CAST(completed_at AS TEXT) AS completed_at,
    error
"""


@dataclass(frozen=True)
class ReingestResult:
    log_id: int
    document_id: str
    accession: str
    status: str
    content_changed: bool
    old_file_path: Path | None
    new_file_path: Path
    old_content_hash: str | None
    new_content_hash: str


@dataclass(frozen=True)
class RecoveryReport:
    scanned: int
    completed: int
    failed: int
    abandoned: int
    skipped_failed: int
    results: tuple[ReingestResult, ...]


@dataclass(frozen=True)
class _PreparedDocument:
    metadata: dict[str, Any]
    finalized_text: str
    new_content_hash: str
    new_file_path: Path
    parser_version_after: str | None


def reingest_one(
    db: sqlite3.Connection,
    accession: str,
    ticker: str,
    document_id: str,
    *,
    reason: str,
    invalidation_id: str | None = None,
    fetch_response: Callable[[], dict],
    corpus_root: Path,
) -> ReingestResult:
    """Run one re-ingest through the state machine. Returns terminal state."""
    corpus_root = Path(corpus_root).resolve()
    old_row = _fetch_document_row(db, document_id)
    response_body = fetch_response()
    prepared = _prepare_from_response(old_row, response_body, corpus_root)

    old_file_path = Path(str(old_row['file_path'])).resolve() if old_row['file_path'] else None
    old_content_hash = _nullable_str(old_row['content_hash'])
    old_parser_version = _nullable_str(old_row['parser_version'])

    if prepared.new_content_hash == old_content_hash:
        log_id = _insert_log(
            db,
            document_id=document_id,
            accession=accession,
            ticker=ticker,
            old_file_path=old_file_path,
            new_file_path=old_file_path or prepared.new_file_path,
            old_content_hash=old_content_hash,
            new_content_hash=old_content_hash,
            content_changed=False,
            parser_version_before=old_parser_version,
            parser_version_after=old_parser_version,
            reason=reason,
            invalidation_id=invalidation_id,
            status='no_change',
            completed=True,
        )
        return _result_from_log(db, log_id)

    log_id = _insert_log(
        db,
        document_id=document_id,
        accession=accession,
        ticker=ticker,
        old_file_path=old_file_path,
        new_file_path=prepared.new_file_path,
        old_content_hash=old_content_hash,
        new_content_hash=prepared.new_content_hash,
        content_changed=True,
        parser_version_before=old_parser_version,
        parser_version_after=prepared.parser_version_after,
        reason=reason,
        invalidation_id=invalidation_id,
        status='planned',
        completed=False,
    )
    _fault('after_planned')
    return _run_planned_work(db, log_id, old_file_path, prepared)


def recover_pending(db: sqlite3.Connection, corpus_root: Path) -> RecoveryReport:
    """Read non-terminal rows from corpus_reingest_log; resume or mark each."""
    try:
        rows = db.execute(
            f"""
            SELECT {_LOG_SELECT_COLUMNS}
            FROM corpus_reingest_log
            WHERE status NOT IN ('complete', 'no_change', 'abandoned')
            ORDER BY started_at, id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return RecoveryReport(0, 0, 0, 0, 0, ())

    results: list[ReingestResult] = []
    completed = 0
    failed = 0
    abandoned = 0
    skipped_failed = 0
    for row in rows:
        status = str(row['status'])
        if status in _FAILED_STATUSES:
            skipped_failed += 1
            _LOG.warning(
                'reingest_recovery_skipping_failed: log_id=%s status=%s error=%s',
                row['id'],
                status,
                row['error'],
            )
            results.append(_result_from_log(db, int(row['id'])))
            continue
        try:
            result = _recover_row(db, row, Path(corpus_root).resolve())
        except Exception as exc:  # noqa: BLE001
            failed_status = _failed_status_for(status)
            _LOG.warning(
                'reingest_recovery_failed: log_id=%s status=%s error=%s',
                row['id'],
                status,
                exc,
                exc_info=True,
            )
            _mark_failed(db, int(row['id']), failed_status, exc)
            result = _result_from_log(db, int(row['id']))
        results.append(result)
        if result.status == 'complete':
            completed += 1
        elif result.status == 'abandoned':
            abandoned += 1
        elif result.status in _FAILED_STATUSES:
            failed += 1

    return RecoveryReport(
        scanned=len(rows),
        completed=completed,
        failed=failed,
        abandoned=abandoned,
        skipped_failed=skipped_failed,
        results=tuple(results),
    )


def _recover_row(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    corpus_root: Path,
) -> ReingestResult:
    status = str(row['status'])
    log_id = int(row['id'])
    old_file_path = _optional_path(row['old_file_path'])
    new_file_path = Path(str(row['new_file_path'])).resolve()

    if status == 'planned':
        if new_file_path.exists():
            actual_hash = _frontmatter_content_hash(new_file_path)
            if actual_hash != row['new_content_hash']:
                exc = RuntimeError(
                    f'planned file hash mismatch at {new_file_path}: '
                    f'expected {row["new_content_hash"]}, got {actual_hash}'
                )
                _LOG.warning('reingest_planned_file_collision: log_id=%s path=%s', log_id, new_file_path)
                _mark_failed(db, log_id, 'planned_failed', exc)
                return _result_from_log(db, log_id)
            _update_status(db, log_id, 'new_written')
            row = _fetch_log_row(db, log_id)
            return _recover_row(db, row, corpus_root)

        prepared = _prepare_recovery_fetch(db, row, corpus_root)
        if _is_stale(row['started_at']) or (
            prepared.new_content_hash != row['new_content_hash']
            or str(prepared.new_file_path) != str(new_file_path)
        ):
            replacement_id = _abandon_and_insert_replacement(db, row, prepared)
            return _run_planned_work(db, replacement_id, old_file_path, prepared)
        return _run_planned_work(db, log_id, old_file_path, prepared)

    if status == 'new_written':
        if not new_file_path.exists():
            exc = FileNotFoundError(new_file_path)
            _mark_failed(db, log_id, 'new_written_failed', exc)
            return _result_from_log(db, log_id)
        if _frontmatter_content_hash(new_file_path) != row['new_content_hash']:
            exc = RuntimeError(f'new_written file hash mismatch at {new_file_path}')
            _mark_failed(db, log_id, 'new_written_failed', exc)
            return _result_from_log(db, log_id)
        prepared = _prepare_from_file(new_file_path)
        return _advance_after_new_written(db, log_id, old_file_path, prepared)

    if status == 'db_upserted':
        return _delete_old_and_complete(db, log_id, old_file_path, new_file_path)

    if status == 'old_deleted':
        if old_file_path is not None and old_file_path.exists():
            _delete_old_file(old_file_path, new_file_path)
            _update_status(db, log_id, 'old_deleted')
        _complete(db, log_id)
        return _result_from_log(db, log_id)

    raise RuntimeError(f'unsupported recovery status {status!r}')


def _run_planned_work(
    db: sqlite3.Connection,
    log_id: int,
    old_file_path: Path | None,
    prepared: _PreparedDocument,
) -> ReingestResult:
    try:
        _write_prepared_file(prepared)
    except Exception as exc:  # noqa: BLE001
        _mark_failed(db, log_id, 'new_written_failed', exc)
        return _result_from_log(db, log_id)
    _update_status(db, log_id, 'new_written')
    _fault('after_new_written')
    return _advance_after_new_written(db, log_id, old_file_path, prepared)


def _advance_after_new_written(
    db: sqlite3.Connection,
    log_id: int,
    old_file_path: Path | None,
    prepared: _PreparedDocument,
) -> ReingestResult:
    try:
        _upsert_and_mark(db, log_id, prepared)
    except Exception as exc:  # noqa: BLE001
        _mark_failed(db, log_id, 'db_upserted_failed', exc)
        return _result_from_log(db, log_id)
    _fault('after_db_upserted')
    return _delete_old_and_complete(db, log_id, old_file_path, prepared.new_file_path)


def _delete_old_and_complete(
    db: sqlite3.Connection,
    log_id: int,
    old_file_path: Path | None,
    new_file_path: Path,
) -> ReingestResult:
    try:
        _delete_old_file(old_file_path, new_file_path)
    except Exception as exc:  # noqa: BLE001
        _mark_failed(db, log_id, 'old_deleted_failed', exc)
        return _result_from_log(db, log_id)
    _update_status(db, log_id, 'old_deleted')
    _fault('after_old_deleted')
    _complete(db, log_id)
    _fault('after_complete')
    return _result_from_log(db, log_id)


def _prepare_from_response(
    old_row: sqlite3.Row,
    response_body: Mapping[str, Any],
    corpus_root: Path,
) -> _PreparedDocument:
    metadata = _metadata_from_document_row(old_row)
    for key, value in derive_provenance(dict(response_body)).items():
        if value is not None or key in metadata:
            metadata[key] = value
    body = _assemble_body_from_api_response(response_body, expected_form=str(old_row['form_type']))
    assembled_text = assemble_canonical_text(metadata, body)
    finalized_text, content_hash = finalize_with_hash(assembled_text)
    finalized_metadata = dict(metadata)
    finalized_metadata['content_hash'] = content_hash
    finalized_path = canonical_path(finalized_metadata, corpus_root).resolve()
    return _PreparedDocument(
        metadata=finalized_metadata,
        finalized_text=finalized_text,
        new_content_hash=content_hash,
        new_file_path=finalized_path,
        parser_version_after=_nullable_str(finalized_metadata.get('parser_version')),
    )


def _prepare_from_file(path: Path) -> _PreparedDocument:
    text = path.read_text(encoding='utf-8')
    metadata, _body = parse_frontmatter(text)
    return _PreparedDocument(
        metadata=metadata,
        finalized_text=text,
        new_content_hash=str(metadata['content_hash']),
        new_file_path=path.resolve(),
        parser_version_after=_nullable_str(metadata.get('parser_version')),
    )


def _prepare_recovery_fetch(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    corpus_root: Path,
) -> _PreparedDocument:
    document_row = _fetch_document_row(db, str(row['document_id']))
    source_accession = _nullable_str(document_row['source_accession'])
    if source_accession:
        response_body = edgar_api_client.get_filing_sections(
            ticker=str(document_row['ticker']),
            accession=source_accession,
            cik=_nullable_str(document_row['cik']),
            form_type=_nullable_str(document_row['form_type']),
            format='full',
            max_words='none',
            include_tables=False,
        )
        return _prepare_from_response(document_row, response_body, corpus_root)
    year, quarter, source = _resolve_api_params_from_row(document_row)
    response_body = edgar_api_client.get_filing_sections(
        ticker=str(row['ticker']),
        year=year,
        quarter=quarter,
        format='full',
        max_words='none',
        source=source,
        include_tables=False,
    )
    return _prepare_from_response(document_row, response_body, corpus_root)


def _metadata_from_document_row(row: sqlite3.Row) -> dict[str, Any]:
    file_path = Path(str(row['file_path']))
    if file_path.exists():
        try:
            metadata, _body = parse_frontmatter(file_path.read_text(encoding='utf-8'))
            metadata.pop('content_hash', None)
            metadata['extraction_status'] = 'complete'
            return metadata
        except Exception:  # noqa: BLE001
            _LOG.warning('reingest_old_frontmatter_unreadable: path=%s', file_path, exc_info=True)

    metadata = {
        column: row[column]
        for column in _DOCUMENT_COLUMNS
        if column not in {'file_path', 'content_hash'} and row[column] is not None
    }
    metadata['extraction_status'] = 'complete'
    return metadata


def _write_prepared_file(prepared: _PreparedDocument) -> None:
    staging_dir = prepared.new_file_path.parents[2] / '.staging'
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f'{uuid.uuid4()}.md'
    prepared.new_file_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_text(prepared.finalized_text, encoding='utf-8')
    os.rename(staging_path, prepared.new_file_path)


def _upsert_and_mark(
    db: sqlite3.Connection,
    log_id: int,
    prepared: _PreparedDocument,
) -> None:
    sections = parse_sections(prepared.finalized_text, prepared.metadata['source'])
    document_row = _build_document_row(prepared.metadata, prepared.new_file_path)
    # Keep the authoritative DB pointer and re-ingest log phase inseparable.
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
        db.execute(
            "UPDATE corpus_reingest_log SET status = 'db_upserted', error = NULL WHERE id = ?",
            (log_id,),
        )


def _delete_old_file(old_file_path: Path | None, new_file_path: Path) -> None:
    if old_file_path is None:
        return
    old_file_path = old_file_path.resolve()
    if old_file_path == new_file_path.resolve():
        return
    if old_file_path.exists():
        old_file_path.unlink()


def _insert_log(
    db: sqlite3.Connection,
    *,
    document_id: str,
    accession: str,
    ticker: str,
    old_file_path: Path | None,
    new_file_path: Path,
    old_content_hash: str | None,
    new_content_hash: str,
    content_changed: bool,
    parser_version_before: str | None,
    parser_version_after: str | None,
    reason: str,
    invalidation_id: str | None,
    status: str,
    completed: bool,
) -> int:
    now = _now()
    with db:
        cursor = db.execute(
            """
            INSERT INTO corpus_reingest_log (
                document_id,
                accession,
                ticker,
                old_file_path,
                new_file_path,
                old_content_hash,
                new_content_hash,
                content_changed,
                parser_version_before,
                parser_version_after,
                reason,
                invalidation_id,
                status,
                started_at,
                completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                accession,
                ticker,
                str(old_file_path) if old_file_path is not None else None,
                str(new_file_path),
                old_content_hash,
                new_content_hash,
                int(content_changed),
                parser_version_before,
                parser_version_after,
                reason,
                invalidation_id,
                status,
                now,
                now if completed else None,
            ),
        )
        return int(cursor.lastrowid)


def _abandon_and_insert_replacement(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    prepared: _PreparedDocument,
) -> int:
    now = _now()
    with db:
        db.execute(
            """
            UPDATE corpus_reingest_log
            SET status = 'abandoned', completed_at = ?, error = NULL
            WHERE id = ?
            """,
            (now, row['id']),
        )
        cursor = db.execute(
            """
            INSERT INTO corpus_reingest_log (
                document_id,
                accession,
                ticker,
                old_file_path,
                new_file_path,
                old_content_hash,
                new_content_hash,
                content_changed,
                parser_version_before,
                parser_version_after,
                reason,
                invalidation_id,
                status,
                started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?)
            """,
            (
                row['document_id'],
                row['accession'],
                row['ticker'],
                row['old_file_path'],
                str(prepared.new_file_path),
                row['old_content_hash'],
                prepared.new_content_hash,
                int(prepared.new_content_hash != row['old_content_hash']),
                row['parser_version_before'],
                prepared.parser_version_after,
                row['reason'],
                row['invalidation_id'],
                now,
            ),
        )
        return int(cursor.lastrowid)


def _update_status(db: sqlite3.Connection, log_id: int, status: str) -> None:
    with db:
        db.execute(
            'UPDATE corpus_reingest_log SET status = ?, error = NULL WHERE id = ?',
            (status, log_id),
        )


def _complete(db: sqlite3.Connection, log_id: int) -> None:
    with db:
        db.execute(
            """
            UPDATE corpus_reingest_log
            SET status = 'complete', completed_at = ?, error = NULL
            WHERE id = ?
            """,
            (_now(), log_id),
        )


def _mark_failed(
    db: sqlite3.Connection,
    log_id: int,
    failed_status: str,
    exc: BaseException,
) -> None:
    with db:
        db.execute(
            'UPDATE corpus_reingest_log SET status = ?, error = ? WHERE id = ?',
            (failed_status, str(exc), log_id),
        )


def _fetch_document_row(db: sqlite3.Connection, document_id: str) -> sqlite3.Row:
    row = db.execute(
        f"SELECT {', '.join(_DOCUMENT_SELECT_COLUMNS)} FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f'document not found for re-ingest: {document_id}')
    return row


def _fetch_log_row(db: sqlite3.Connection, log_id: int) -> sqlite3.Row:
    row = db.execute(
        f'SELECT {_LOG_SELECT_COLUMNS} FROM corpus_reingest_log WHERE id = ?',
        (log_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f'reingest log row not found: {log_id}')
    return row


def _result_from_log(db: sqlite3.Connection, log_id: int) -> ReingestResult:
    row = _fetch_log_row(db, log_id)
    return ReingestResult(
        log_id=int(row['id']),
        document_id=str(row['document_id']),
        accession=str(row['accession']),
        status=str(row['status']),
        content_changed=bool(row['content_changed']),
        old_file_path=_optional_path(row['old_file_path']),
        new_file_path=Path(str(row['new_file_path'])),
        old_content_hash=_nullable_str(row['old_content_hash']),
        new_content_hash=str(row['new_content_hash']),
    )


def _frontmatter_content_hash(path: Path) -> str:
    metadata, _body = parse_frontmatter(path.read_text(encoding='utf-8'))
    return str(metadata['content_hash'])


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    return Path(str(value)).resolve()


def _nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _is_stale(value: Any) -> bool:
    started_at = _parse_timestamp(value)
    return _now_dt() - started_at > _PLANNED_RETRY_THRESHOLD


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _failed_status_for(status: str) -> str:
    if status == 'planned':
        return 'planned_failed'
    if status == 'new_written':
        return 'db_upserted_failed'
    return 'old_deleted_failed'


def _now_dt() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _now() -> str:
    return _now_dt().isoformat().replace('+00:00', 'Z')


def _fault(_label: str) -> None:
    return None


__all__ = ['RecoveryReport', 'ReingestResult', 'recover_pending', 'reingest_one']
