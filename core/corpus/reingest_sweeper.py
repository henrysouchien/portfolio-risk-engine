from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Sequence

from core.corpus._paths import (
    corpus_db_path,
    corpus_log_dir,
    corpus_root,
    dev_corpus_db_path,
    dev_corpus_root,
)
from core.corpus.db import open_corpus_db
from core.corpus.frontmatter import parse_frontmatter


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = dev_corpus_db_path()
DEFAULT_CORPUS_ROOT = dev_corpus_root()
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweeperReport:
    scanned: int
    deleted: int
    completed: int
    skipped: int
    alerts: int
    errors: int


def sweep(db: sqlite3.Connection, corpus_root: Path) -> SweeperReport:
    del corpus_root
    try:
        rows = db.execute(
            """
            SELECT log.id, log.document_id, log.old_file_path, log.old_content_hash
            FROM corpus_reingest_log log
            JOIN documents doc ON doc.document_id = log.document_id
            WHERE log.status IN ('db_upserted', 'old_deleted', 'old_deleted_failed')
              AND log.old_file_path IS NOT NULL
              AND doc.file_path != log.old_file_path
              AND NOT EXISTS (
                SELECT 1 FROM corpus_reingest_log active
                WHERE active.document_id = log.document_id
                  AND active.status NOT IN ('complete', 'no_change', 'abandoned')
                  AND active.id != log.id
              )
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return SweeperReport(0, 0, 0, 0, 0, 0)

    deleted = 0
    completed = 0
    skipped = 0
    alerts = 0
    errors = 0
    for row in rows:
        log_id = int(row['id'])
        old_path = Path(str(row['old_file_path']))
        if not old_path.exists():
            _complete(db, log_id)
            completed += 1
            continue

        try:
            content_hash = _content_hash(old_path)
        except Exception as exc:  # noqa: BLE001
            alerts += 1
            skipped += 1
            _LOG.warning(
                'reingest_sweeper_frontmatter_unreadable: log_id=%s path=%s error=%s',
                log_id,
                old_path,
                exc,
                exc_info=True,
            )
            continue

        if content_hash != row['old_content_hash']:
            alerts += 1
            skipped += 1
            _LOG.warning(
                'reingest_sweeper_content_hash_mismatch: log_id=%s path=%s expected=%s actual=%s',
                log_id,
                old_path,
                row['old_content_hash'],
                content_hash,
            )
            continue

        try:
            old_path.unlink()
        except Exception as exc:  # noqa: BLE001
            errors += 1
            _mark_old_deleted_failed(db, log_id, exc)
            _LOG.warning(
                'reingest_sweeper_unlink_failed: log_id=%s path=%s error=%s',
                log_id,
                old_path,
                exc,
                exc_info=True,
            )
            continue

        deleted += 1
        _mark_old_deleted(db, log_id)
        _complete(db, log_id)
        completed += 1

    return SweeperReport(
        scanned=len(rows),
        deleted=deleted,
        completed=completed,
        skipped=skipped,
        alerts=alerts,
        errors=errors,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Sweep old corpus re-ingest markdown files.')
    parser.add_argument('--db', type=Path)
    parser.add_argument('--corpus-root', type=Path)
    parser.add_argument('--log', type=Path)
    args = parser.parse_args(argv)
    args.db = args.db or corpus_db_path()
    args.corpus_root = args.corpus_root or corpus_root()
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    with open_corpus_db(args.db) as db:
        report = sweep(db, args.corpus_root)

    payload = {'ts': _now(), **asdict(report)}
    print(json.dumps(payload, sort_keys=True))

    log_path = args.log or (
        corpus_log_dir()
        / f'reingest_sweeper_{datetime.now(timezone.utc).date().isoformat()}.jsonl'
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, sort_keys=True) + '\n')

    return 1 if report.errors else 0


def _content_hash(path: Path) -> str:
    metadata, _body = parse_frontmatter(path.read_text(encoding='utf-8'))
    return str(metadata['content_hash'])


def _mark_old_deleted(db: sqlite3.Connection, log_id: int) -> None:
    with db:
        db.execute(
            "UPDATE corpus_reingest_log SET status = 'old_deleted', error = NULL WHERE id = ?",
            (log_id,),
        )


def _mark_old_deleted_failed(
    db: sqlite3.Connection,
    log_id: int,
    exc: BaseException,
) -> None:
    with db:
        db.execute(
            "UPDATE corpus_reingest_log SET status = 'old_deleted_failed', error = ? WHERE id = ?",
            (str(exc), log_id),
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


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


__all__ = ['SweeperReport', 'main', 'parse_args', 'sweep']


if __name__ == '__main__':
    raise SystemExit(main())
