from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Sequence


_MIGRATIONS_DIR = Path(__file__).resolve().parent
_MIGRATION_PATTERN = re.compile(r'^(?P<version>\d{4})_(?P<description>[a-z0-9_]+)\.sql$')
_BASELINE_DESCRIPTION = 'baseline schema'
_PARSER_COLUMNS = (
    ('parser_version', 'TEXT'),
    ('parser_schema_version', 'INTEGER'),
    ('parser_path', 'TEXT'),
    ('parser_state', 'TEXT'),
    ('parser_result_status', 'TEXT'),
    ('cross_reference_target', 'TEXT'),
    ('producer_deployment_id', 'TEXT'),
    ('producer_instance_id', 'TEXT'),
    ('producer_build_id', 'TEXT'),
)
_REINGEST_LOG_COLUMNS = (
    'id',
    'document_id',
    'accession',
    'ticker',
    'old_file_path',
    'new_file_path',
    'old_content_hash',
    'new_content_hash',
    'content_changed',
    'parser_version_before',
    'parser_version_after',
    'reason',
    'invalidation_id',
    'status',
    'started_at',
    'completed_at',
    'error',
)
_REINGEST_INDEX_SQL = (
    'CREATE INDEX IF NOT EXISTS idx_reingest_invalidation ON corpus_reingest_log(invalidation_id)',
    'CREATE INDEX IF NOT EXISTS idx_reingest_document ON corpus_reingest_log(document_id, started_at)',
    """
    CREATE INDEX IF NOT EXISTS idx_reingest_active ON corpus_reingest_log(status)
        WHERE status NOT IN ('complete', 'no_change', 'abandoned')
    """,
)


@dataclass(frozen=True)
class _Migration:
    version: int
    description: str
    path: Path


def apply_migrations(db_path: Path) -> list[int]:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrations = _discover_migrations()

    db = sqlite3.connect(db_path)
    try:
        db.row_factory = sqlite3.Row
        return apply_migrations_to_connection(db, migrations=migrations)
    finally:
        db.close()


def apply_migrations_to_connection(
    db: sqlite3.Connection,
    *,
    migrations: Sequence[_Migration] | None = None,
) -> list[int]:
    if migrations is None:
        migrations = _discover_migrations()

    if not _has_version_table(db):
        _initialize_version_table(db)
    else:
        _record_baseline_if_needed(db)

    applied_versions = _applied_versions(db)
    newly_applied: list[int] = []

    for migration in migrations:
        if migration.path.name == '0002_parser_provenance.sql':
            applied = _ensure_parser_provenance(db, migration)
        elif migration.path.name == '0003_corpus_reingest_log.sql':
            applied = _ensure_reingest_log(db, migration)
        elif migration.version in applied_versions:
            continue
        else:
            _apply_migration(db, migration)
            applied = True
        applied_versions.add(migration.version)
        if applied:
            newly_applied.append(migration.version)

    return newly_applied


def _discover_migrations() -> list[_Migration]:
    migrations: list[_Migration] = []
    seen_versions: set[int] = set()

    for path in sorted(_MIGRATIONS_DIR.glob('*.sql')):
        match = _MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            raise ValueError(f'invalid corpus migration filename: {path.name}')

        version = int(match.group('version'))
        if version in seen_versions:
            raise ValueError(f'duplicate corpus migration version: {version:04d}')

        seen_versions.add(version)
        migrations.append(
            _Migration(
                version=version,
                description=match.group('description').replace('_', ' '),
                path=path,
            )
        )

    return sorted(migrations, key=lambda migration: migration.version)


def _has_version_table(db: sqlite3.Connection) -> bool:
    row = db.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'corpus_schema_version'
        """
    ).fetchone()
    return row is not None


def _initialize_version_table(db: sqlite3.Connection) -> None:
    with db:
        db.execute('BEGIN')
        db.execute(
            """
            CREATE TABLE corpus_schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL,
                description TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            INSERT INTO corpus_schema_version (version, applied_at, description)
            VALUES (1, CURRENT_TIMESTAMP, 'baseline schema')
            """
        )


def _record_baseline_if_needed(db: sqlite3.Connection) -> None:
    if not _table_exists(db, 'documents'):
        return
    _record_migration(db, 1, _BASELINE_DESCRIPTION)


def _applied_versions(db: sqlite3.Connection) -> set[int]:
    return {
        int(row['version'])
        for row in db.execute('SELECT version FROM corpus_schema_version')
    }


def _apply_migration(db: sqlite3.Connection, migration: _Migration) -> None:
    sql = migration.path.read_text(encoding='utf-8')
    statements = _split_sql_statements(sql)

    with db:
        db.execute('BEGIN')
        for statement in statements:
            db.execute(statement)
        db.execute(
            """
            INSERT OR IGNORE INTO corpus_schema_version (version, applied_at, description)
            VALUES (?, CURRENT_TIMESTAMP, ?)
            """,
            (migration.version, migration.description),
        )


def _split_sql_statements(sql: str) -> list[str]:
    statements = [statement.strip() for statement in sql.split(';')]
    return [statement for statement in statements if statement]


def _ensure_parser_provenance(
    db: sqlite3.Connection,
    migration: _Migration,
) -> bool:
    if not _table_exists(db, 'documents'):
        raise sqlite3.OperationalError('documents table missing; cannot apply parser provenance migration')

    existing_columns = _column_types(db, 'documents')
    missing_columns: list[tuple[str, str]] = []
    for column, column_type in _PARSER_COLUMNS:
        existing_type = existing_columns.get(column)
        if existing_type is None:
            missing_columns.append((column, column_type))
            continue
        if existing_type.upper() != column_type:
            raise RuntimeError(
                f'documents.{column} has type {existing_type!r}; expected {column_type!r}'
            )

    if not missing_columns:
        _record_migration(db, migration.version, migration.description)
        return False

    with db:
        db.execute('BEGIN')
        for column, column_type in missing_columns:
            db.execute(f'ALTER TABLE documents ADD COLUMN {column} {column_type}')
        db.execute(
            """
            INSERT OR IGNORE INTO corpus_schema_version (version, applied_at, description)
            VALUES (?, CURRENT_TIMESTAMP, ?)
            """,
            (migration.version, migration.description),
        )
    return True


def _ensure_reingest_log(
    db: sqlite3.Connection,
    migration: _Migration,
) -> bool:
    if not _table_exists(db, 'corpus_reingest_log'):
        _apply_migration(db, migration)
        return True

    columns = tuple(_column_types(db, 'corpus_reingest_log'))
    if columns != _REINGEST_LOG_COLUMNS:
        raise RuntimeError(
            'corpus_reingest_log schema is incompatible with migration 0003: '
            f'got {columns!r}; expected {_REINGEST_LOG_COLUMNS!r}'
        )

    with db:
        db.execute('BEGIN')
        for statement in _REINGEST_INDEX_SQL:
            db.execute(statement)
        db.execute(
            """
            INSERT OR IGNORE INTO corpus_schema_version (version, applied_at, description)
            VALUES (?, CURRENT_TIMESTAMP, ?)
            """,
            (migration.version, migration.description),
        )
    return False


def _record_migration(db: sqlite3.Connection, version: int, description: str) -> None:
    with db:
        db.execute(
            """
            INSERT OR IGNORE INTO corpus_schema_version (version, applied_at, description)
            VALUES (?, CURRENT_TIMESTAMP, ?)
            """,
            (version, description),
        )


def _table_exists(db: sqlite3.Connection, table_name: str) -> bool:
    row = db.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _column_types(db: sqlite3.Connection, table_name: str) -> dict[str, str]:
    return {
        str(row[1]): str(row[2])
        for row in db.execute(f'PRAGMA table_info({table_name})')
    }


__all__ = ['apply_migrations', 'apply_migrations_to_connection']
