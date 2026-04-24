from __future__ import annotations

from pathlib import Path
import sqlite3


_SCHEMA_PATH = Path(__file__).with_name('schema.sql')


def open_corpus_db(path: Path) -> sqlite3.Connection:
    """Open the corpus SQLite DB and apply the idempotent schema on every open."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA foreign_keys=ON')

    _ensure_fts5_available(db)

    with db:
        db.executescript(_SCHEMA_PATH.read_text(encoding='utf-8'))

    return db


def _ensure_fts5_available(db: sqlite3.Connection) -> None:
    try:
        db.execute('CREATE VIRTUAL TABLE temp.__fts5_smoke USING fts5(content)')
        db.execute('DROP TABLE temp.__fts5_smoke')
    except sqlite3.OperationalError as exc:
        raise RuntimeError('SQLite FTS5 is required for corpus indexing') from exc

    try:
        db.execute('SELECT fts5_version()').fetchone()
    except sqlite3.OperationalError:
        # Some SQLite builds expose FTS5 but not the convenience version function.
        db.create_function('fts5_version', 0, lambda: sqlite3.sqlite_version)


__all__ = ['open_corpus_db']
