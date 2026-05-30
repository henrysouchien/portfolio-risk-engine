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
_HTML_CORPUS_MAPPING_SET_COLUMNS = (
    'mapping_set_id',
    'document_id',
    'accession',
    'primary_document_url',
    'source_html_hash',
    'corpus_content_hash',
    'sanitizer_version',
    'parser_version',
    'parser_schema_version',
    'visible_text_algorithm_version',
    'mapping_algorithm_version',
    'sidecar_path',
    'sidecar_hash',
    'producer_json',
    'provenance',
    'active',
    'created_at',
)
_HTML_CORPUS_MAPPING_RECORD_COLUMNS = (
    'mapping_record_id',
    'mapping_set_id',
    'producer_record_id',
    'section_id',
    'section_header',
    'content_type',
    'corpus_char_start',
    'corpus_char_end',
    'offset_frame',
    'visible_text_offset_frame',
    'visible_text_char_start',
    'visible_text_char_end',
    'quote',
    'text_before',
    'text_after',
    'confidence',
    'producer_trace_json',
    'diagnostics_json',
    'active',
    'created_at',
)
_HTML_CORPUS_MAPPING_SET_SIGNATURE = (
    ('mapping_set_id', 'TEXT', 0, 1),
    ('document_id', 'TEXT', 1, 0),
    ('accession', 'TEXT', 1, 0),
    ('primary_document_url', 'TEXT', 1, 0),
    ('source_html_hash', 'TEXT', 1, 0),
    ('corpus_content_hash', 'TEXT', 1, 0),
    ('sanitizer_version', 'TEXT', 1, 0),
    ('parser_version', 'TEXT', 1, 0),
    ('parser_schema_version', 'INTEGER', 1, 0),
    ('visible_text_algorithm_version', 'TEXT', 1, 0),
    ('mapping_algorithm_version', 'TEXT', 1, 0),
    ('sidecar_path', 'TEXT', 1, 0),
    ('sidecar_hash', 'TEXT', 1, 0),
    ('producer_json', 'TEXT', 0, 0),
    ('provenance', 'TEXT', 1, 0),
    ('active', 'INTEGER', 1, 0),
    ('created_at', 'TIMESTAMP', 1, 0),
)
_HTML_CORPUS_MAPPING_RECORD_SIGNATURE = (
    ('mapping_record_id', 'TEXT', 0, 1),
    ('mapping_set_id', 'TEXT', 1, 0),
    ('producer_record_id', 'TEXT', 1, 0),
    ('section_id', 'TEXT', 1, 0),
    ('section_header', 'TEXT', 1, 0),
    ('content_type', 'TEXT', 1, 0),
    ('corpus_char_start', 'INTEGER', 1, 0),
    ('corpus_char_end', 'INTEGER', 1, 0),
    ('offset_frame', 'TEXT', 1, 0),
    ('visible_text_offset_frame', 'TEXT', 1, 0),
    ('visible_text_char_start', 'INTEGER', 1, 0),
    ('visible_text_char_end', 'INTEGER', 1, 0),
    ('quote', 'TEXT', 1, 0),
    ('text_before', 'TEXT', 0, 0),
    ('text_after', 'TEXT', 0, 0),
    ('confidence', 'TEXT', 1, 0),
    ('producer_trace_json', 'TEXT', 1, 0),
    ('diagnostics_json', 'TEXT', 0, 0),
    ('active', 'INTEGER', 1, 0),
    ('created_at', 'TIMESTAMP', 1, 0),
)
_HTML_CORPUS_MAPPING_INDEX_SQL = (
    """
    CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_sets_document
        ON html_corpus_mapping_sets(document_id, active)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_sets_identity
        ON html_corpus_mapping_sets(
            document_id,
            source_html_hash,
            corpus_content_hash,
            sanitizer_version,
            visible_text_algorithm_version,
            mapping_algorithm_version,
            active
        )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_records_set
        ON html_corpus_mapping_records(mapping_set_id, active)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_records_span
        ON html_corpus_mapping_records(mapping_set_id, corpus_char_start, corpus_char_end)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_records_visible_span
        ON html_corpus_mapping_records(mapping_set_id, visible_text_char_start, visible_text_char_end)
    """,
)
_HTML_CORPUS_MAPPING_REQUIRED_SQL = {
    'html_corpus_mapping_sets': (
        'references documents(document_id)',
        'check (active in (0, 1))',
        "check (provenance in ('producer', 'legacy_backfill'))",
        (
            'unique ( document_id, source_html_hash, corpus_content_hash, '
            'sanitizer_version, parser_version, parser_schema_version, '
            'visible_text_algorithm_version, mapping_algorithm_version )'
        ),
    ),
    'html_corpus_mapping_records': (
        'references html_corpus_mapping_sets(mapping_set_id) on delete cascade',
        'check (corpus_char_start >= 0)',
        'check (corpus_char_end > corpus_char_start)',
        'check (visible_text_char_start >= 0)',
        'check (visible_text_char_end > visible_text_char_start)',
        "check (offset_frame = 'corpus_doc')",
        "check (visible_text_offset_frame = 'source_html_visible_text_v1')",
        "check (content_type in ('prose', 'table', 'heading', 'footnote', 'unknown'))",
        "check (confidence in ('exact', 'high', 'quote', 'section_only', 'none'))",
        'check (active in (0, 1))',
        'unique (mapping_set_id, producer_record_id)',
    ),
}


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
        elif migration.path.name == '0004_html_corpus_mapping.sql':
            applied = _ensure_html_corpus_mapping(db, migration)
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


def _ensure_html_corpus_mapping(
    db: sqlite3.Connection,
    migration: _Migration,
) -> bool:
    set_exists = _table_exists(db, 'html_corpus_mapping_sets')
    record_exists = _table_exists(db, 'html_corpus_mapping_records')
    if not set_exists or not record_exists:
        _validate_html_mapping_table_if_present(
            db,
            'html_corpus_mapping_sets',
            _HTML_CORPUS_MAPPING_SET_COLUMNS,
        )
        _validate_html_mapping_table_if_present(
            db,
            'html_corpus_mapping_records',
            _HTML_CORPUS_MAPPING_RECORD_COLUMNS,
        )
        _apply_migration(db, migration)
        return True

    _validate_html_mapping_table_if_present(
        db,
        'html_corpus_mapping_sets',
        _HTML_CORPUS_MAPPING_SET_COLUMNS,
    )
    _validate_html_mapping_table_if_present(
        db,
        'html_corpus_mapping_records',
        _HTML_CORPUS_MAPPING_RECORD_COLUMNS,
    )

    with db:
        db.execute('BEGIN')
        for statement in _HTML_CORPUS_MAPPING_INDEX_SQL:
            db.execute(statement)
        db.execute(
            """
            INSERT OR IGNORE INTO corpus_schema_version (version, applied_at, description)
            VALUES (?, CURRENT_TIMESTAMP, ?)
            """,
            (migration.version, migration.description),
        )
    return False


def _validate_html_mapping_table_if_present(
    db: sqlite3.Connection,
    table_name: str,
    expected_columns: tuple[str, ...],
) -> None:
    if not _table_exists(db, table_name):
        return

    columns = tuple(_column_types(db, table_name))
    if columns != expected_columns:
        raise RuntimeError(
            f'{table_name} schema is incompatible with migration 0004: '
            f'got {columns!r}; expected {expected_columns!r}'
        )
    expected_signature = {
        'html_corpus_mapping_sets': _HTML_CORPUS_MAPPING_SET_SIGNATURE,
        'html_corpus_mapping_records': _HTML_CORPUS_MAPPING_RECORD_SIGNATURE,
    }[table_name]
    signature = _column_signature(db, table_name)
    if signature != expected_signature:
        raise RuntimeError(
            f'{table_name} column signature is incompatible with migration 0004: '
            f'got {signature!r}; expected {expected_signature!r}'
        )
    _validate_required_table_sql(db, table_name)


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


def _column_signature(
    db: sqlite3.Connection,
    table_name: str,
) -> tuple[tuple[str, str, int, int], ...]:
    return tuple(
        (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in db.execute(f'PRAGMA table_info({table_name})')
    )


def _validate_required_table_sql(db: sqlite3.Connection, table_name: str) -> None:
    row = db.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    sql = _normalize_sql(str(row[0] if row else ''))
    missing = [
        snippet
        for snippet in _HTML_CORPUS_MAPPING_REQUIRED_SQL[table_name]
        if _normalize_sql(snippet) not in sql
    ]
    if missing:
        raise RuntimeError(
            f'{table_name} constraints are incompatible with migration 0004: '
            f'missing {missing!r}'
        )


def _normalize_sql(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip().lower()


__all__ = ['apply_migrations', 'apply_migrations_to_connection']
