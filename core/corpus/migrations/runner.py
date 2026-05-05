from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3


_MIGRATIONS_DIR = Path(__file__).resolve().parent
_MIGRATION_PATTERN = re.compile(r'^(?P<version>\d{4})_(?P<description>[a-z0-9_]+)\.sql$')


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
        if not _has_version_table(db):
            _initialize_version_table(db)

        applied_versions = _applied_versions(db)
        newly_applied: list[int] = []

        for migration in migrations:
            if migration.version in applied_versions:
                continue
            _apply_migration(db, migration)
            applied_versions.add(migration.version)
            newly_applied.append(migration.version)

        return newly_applied
    finally:
        db.close()


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
            INSERT INTO corpus_schema_version (version, applied_at, description)
            VALUES (?, CURRENT_TIMESTAMP, ?)
            """,
            (migration.version, migration.description),
        )


def _split_sql_statements(sql: str) -> list[str]:
    statements = [statement.strip() for statement in sql.split(';')]
    return [statement for statement in statements if statement]


__all__ = ['apply_migrations']
