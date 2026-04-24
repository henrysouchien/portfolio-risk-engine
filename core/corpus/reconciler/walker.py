from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
from pathlib import Path
import re
from typing import Any

import yaml

from core.corpus.frontmatter import (
    FRONTMATTER_PATTERN,
    FrontmatterValidationError,
    _normalize_loaded_mapping,
    _validated_metadata,
    parse_frontmatter,
)


_LOGGER = logging.getLogger(__name__)
_SEMVER_PATTERN = re.compile(r'^(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?$')
_MIN_SORTABLE_TIMESTAMP = (0, 0, 0, 0, 0, 0, 0)
_MIN_SORTABLE_SEMVER = (0, 0, 0)


@dataclass(frozen=True)
class AuthoritativeFile:
    document_id: str
    file_path: Path
    content_hash: str
    frontmatter: dict
    other_files: list[Path]


@dataclass(frozen=True)
class _ScannedFile:
    document_id: str
    file_path: Path
    content_hash: str
    frontmatter: dict
    sort_key: tuple[tuple[int, int, int, int, int, int, int], tuple[int, int, int], str]


def scan_corpus(corpus_root: Path) -> dict[str, AuthoritativeFile]:
    """Walk corpus markdown files and pick one authoritative file per document_id."""
    root = Path(corpus_root)
    if not root.exists():
        return {}

    grouped: dict[str, list[_ScannedFile]] = {}
    for path in sorted(root.rglob('*.md')):
        if not path.is_file() or '.staging' in path.parts:
            continue

        frontmatter = _load_frontmatter(path)
        if frontmatter is None:
            continue

        document_id = frontmatter['document_id']
        scanned = _ScannedFile(
            document_id=document_id,
            file_path=path.resolve(),
            content_hash=frontmatter['content_hash'],
            frontmatter=frontmatter,
            sort_key=_authoritative_sort_key(frontmatter),
        )
        grouped.setdefault(document_id, []).append(scanned)

    result: dict[str, AuthoritativeFile] = {}
    for document_id, files in grouped.items():
        authoritative = max(files, key=lambda item: item.sort_key)
        other_files = [item.file_path for item in files if item.file_path != authoritative.file_path]
        result[document_id] = AuthoritativeFile(
            document_id=document_id,
            file_path=authoritative.file_path,
            content_hash=authoritative.content_hash,
            frontmatter=authoritative.frontmatter,
            other_files=other_files,
        )

    return result


def _load_frontmatter(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding='utf-8')

    try:
        metadata, _ = parse_frontmatter(text)
        return metadata
    except FrontmatterValidationError as exc:
        loaded = _load_yaml_mapping(text)
        if loaded is None:
            _LOGGER.warning(
                'skipping corpus file with malformed YAML frontmatter: path=%s errors=%s',
                path,
                exc.invalid_types or exc.missing_required,
            )
            return None

        if not _only_invalid_extraction_at(exc):
            _LOGGER.warning(
                'skipping corpus file with invalid frontmatter: path=%s errors=%s',
                path,
                exc.invalid_types or exc.missing_required,
            )
            return None

        extraction_at = loaded.get('extraction_at')
        relaxed = dict(loaded)
        relaxed.pop('extraction_at', None)
        try:
            metadata = _validated_metadata(
                relaxed,
                require_content_hash=True,
                allow_placeholder_hash=True,
                apply_defaults=True,
            )
        except FrontmatterValidationError:
            _LOGGER.warning(
                'skipping corpus file with invalid frontmatter: path=%s errors=%s',
                path,
                exc.invalid_types or exc.missing_required,
            )
            return None

        if 'extraction_at' in loaded:
            metadata['extraction_at'] = extraction_at
        return metadata


def _load_yaml_mapping(text: str) -> dict[str, Any] | None:
    match = FRONTMATTER_PATTERN.match(text)
    if match is None:
        return None

    try:
        loaded = yaml.safe_load(match.group('yaml')) or {}
    except yaml.YAMLError:
        return None

    if not isinstance(loaded, dict):
        return None

    return _normalize_loaded_mapping(loaded)


def _only_invalid_extraction_at(exc: FrontmatterValidationError) -> bool:
    if exc.missing_required or not exc.invalid_types:
        return False
    return all(field == 'extraction_at' for field, _ in exc.invalid_types)


def _authoritative_sort_key(
    frontmatter: dict[str, Any],
) -> tuple[tuple[int, int, int, int, int, int, int], tuple[int, int, int], str]:
    return (
        _sortable_extraction_at(frontmatter.get('extraction_at')),
        _sortable_pipeline_semver(frontmatter.get('extraction_pipeline')),
        str(frontmatter.get('content_hash') or ''),
    )


def _sortable_extraction_at(value: Any) -> tuple[int, int, int, int, int, int, int]:
    if not isinstance(value, str):
        return _MIN_SORTABLE_TIMESTAMP

    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return _MIN_SORTABLE_TIMESTAMP

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return (
        parsed.year,
        parsed.month,
        parsed.day,
        parsed.hour,
        parsed.minute,
        parsed.second,
        parsed.microsecond,
    )


def _sortable_pipeline_semver(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, str):
        return _MIN_SORTABLE_SEMVER

    _, separator, version = value.rpartition('@')
    if not separator:
        return _MIN_SORTABLE_SEMVER

    match = _SEMVER_PATTERN.fullmatch(version)
    if match is None:
        return _MIN_SORTABLE_SEMVER

    patch = match.group('patch') or '0'
    return (
        int(match.group('major')),
        int(match.group('minor')),
        int(patch),
    )


__all__ = ['AuthoritativeFile', 'scan_corpus']
