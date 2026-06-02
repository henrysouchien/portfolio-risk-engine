from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
_DEV_STATE_DIR = REPO_ROOT / 'data'
_DEV_LOG_DIR = REPO_ROOT / 'logs' / 'corpus'
_PRODUCTION_ENVIRONMENTS = {'prod', 'production'}


@dataclass(frozen=True)
class CorpusPaths:
    state_dir: Path
    db_path: Path
    root: Path
    cache_dir: Path
    cik_cache_dir: Path
    thirteenf_cache_dir: Path
    archive_dir: Path
    backup_dir: Path
    health_dir: Path
    log_dir: Path
    lock_file: Path


def normalize_corpus_path(path: str | Path) -> Path:
    """Return an absolute Path with `~` expanded but symlinks not followed.

    Used for paths stored in documents.file_path or
    corpus_reingest_log.{old_file_path, new_file_path}. This intentionally
    uses os.path.abspath rather than Path.resolve so the unversioned corpus
    symlink prefix is preserved for cross-machine path rewriting.
    """
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def is_production_environment() -> bool:
    return os.getenv('ENVIRONMENT', 'development').strip().lower() in _PRODUCTION_ENVIRONMENTS


def corpus_state_dir() -> Path:
    raw = _env_path('CORPUS_STATE_DIR')
    if raw is not None:
        return raw
    _raise_if_production_missing('CORPUS_STATE_DIR')
    return _DEV_STATE_DIR


def dev_corpus_db_path() -> Path:
    return _DEV_STATE_DIR / 'filings.db'


def dev_corpus_root() -> Path:
    return _DEV_STATE_DIR / 'filings'


def dev_corpus_cache_dir() -> Path:
    return _DEV_STATE_DIR / 'corpus' / 'cache'


def dev_corpus_archive_dir() -> Path:
    return _DEV_STATE_DIR / 'corpus' / 'archives'


def dev_corpus_backup_dir() -> Path:
    return _DEV_STATE_DIR / 'backups'


def dev_corpus_health_dir() -> Path:
    return _DEV_STATE_DIR / 'corpus' / 'health'


def corpus_db_path() -> Path:
    return _resolve_state_path('CORPUS_DB_PATH', Path('filings.db'), dev_corpus_db_path())


def corpus_root() -> Path:
    return _resolve_state_path('CORPUS_ROOT', Path('filings'), dev_corpus_root())


def corpus_cache_dir() -> Path:
    return _resolve_state_path('CORPUS_CACHE_DIR', Path('corpus') / 'cache', dev_corpus_cache_dir())


def corpus_cik_cache_dir() -> Path:
    return corpus_cache_dir() / 'phase2_ciks'


def corpus_13f_cache_dir() -> Path:
    return corpus_cache_dir() / 'phase2_13f'


def corpus_archive_dir() -> Path:
    return _resolve_state_path(
        'CORPUS_ARCHIVE_DIR',
        Path('corpus') / 'archives',
        dev_corpus_archive_dir(),
    )


def corpus_backup_dir() -> Path:
    return _resolve_state_path('CORPUS_BACKUP_DIR', Path('backups'), dev_corpus_backup_dir())


def corpus_health_dir() -> Path:
    return _resolve_state_path(
        'CORPUS_HEALTH_DIR',
        Path('corpus') / 'health',
        dev_corpus_health_dir(),
    )


def corpus_log_dir() -> Path:
    raw = _env_path('CORPUS_LOG_DIR')
    if raw is not None:
        return raw
    return _DEV_LOG_DIR


def corpus_lock_file() -> Path:
    raw = _env_path('CORPUS_LOCK_FILE')
    if raw is not None:
        return raw
    return Path('/run/corpus_promote.lock')


def corpus_paths() -> CorpusPaths:
    return CorpusPaths(
        state_dir=corpus_state_dir(),
        db_path=corpus_db_path(),
        root=corpus_root(),
        cache_dir=corpus_cache_dir(),
        cik_cache_dir=corpus_cik_cache_dir(),
        thirteenf_cache_dir=corpus_13f_cache_dir(),
        archive_dir=corpus_archive_dir(),
        backup_dir=corpus_backup_dir(),
        health_dir=corpus_health_dir(),
        log_dir=corpus_log_dir(),
        lock_file=corpus_lock_file(),
    )


def _resolve_state_path(env_name: str, state_suffix: Path, dev_default: Path) -> Path:
    raw = _env_path(env_name)
    if raw is not None:
        return raw

    state_raw = _env_path('CORPUS_STATE_DIR')
    if state_raw is not None:
        return state_raw / state_suffix

    _raise_if_production_missing(f'CORPUS_STATE_DIR or {env_name}')
    return dev_default


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name, '').strip()
    if not raw:
        return None
    return normalize_corpus_path(raw)


def _raise_if_production_missing(required: str) -> None:
    if is_production_environment():
        raise RuntimeError(
            f'Production corpus paths require {required}; repo-local corpus fallback is disabled.'
        )


__all__ = [
    'CorpusPaths',
    'REPO_ROOT',
    'corpus_13f_cache_dir',
    'corpus_archive_dir',
    'corpus_backup_dir',
    'corpus_cache_dir',
    'corpus_cik_cache_dir',
    'corpus_db_path',
    'corpus_health_dir',
    'corpus_lock_file',
    'corpus_log_dir',
    'corpus_paths',
    'corpus_root',
    'corpus_state_dir',
    'dev_corpus_archive_dir',
    'dev_corpus_backup_dir',
    'dev_corpus_cache_dir',
    'dev_corpus_db_path',
    'dev_corpus_health_dir',
    'dev_corpus_root',
    'is_production_environment',
    'normalize_corpus_path',
]
