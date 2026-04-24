from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

import yaml

CANONICAL_HASH_PLACEHOLDER = '0' * 16

ALLOWED_SOURCES = {'edgar', 'fmp_transcripts', 'quartr'}
ALLOWED_FORM_TYPES = {
    '10-K',
    '10-Q',
    '8-K',
    '10-K/A',
    '10-Q/A',
    '8-K/A',
    'TRANSCRIPT',
    'DECK',
}
ALLOWED_EXTRACTION_STATUSES = {'complete', 'partial', 'failed', 'orphaned'}
ALLOWED_SUPERSEDES_SOURCES = {'sec_header', 'heuristic', 'llm_extraction', 'manual'}
ALLOWED_SUPERSEDES_CONFIDENCES = {'high', 'medium', 'low'}

FIELD_ORDER = (
    'document_id',
    'ticker',
    'cik',
    'company_name',
    'source',
    'form_type',
    'fiscal_period',
    'filing_date',
    'period_end',
    'source_url',
    'source_url_deep',
    'source_accession',
    'extraction_pipeline',
    'extraction_model',
    'extraction_at',
    'extraction_status',
    'content_hash',
    'sector',
    'industry',
    'sector_source',
    'exchange',
    'supersedes',
    'supersedes_source',
    'supersedes_confidence',
)

REQUIRED_FIELDS = ('document_id', 'ticker', 'source', 'form_type', 'content_hash')
NULLABLE_STRING_FIELDS = {
    'cik',
    'company_name',
    'fiscal_period',
    'filing_date',
    'period_end',
    'source_url',
    'source_url_deep',
    'source_accession',
    'extraction_pipeline',
    'extraction_model',
    'extraction_at',
    'extraction_status',
    'sector',
    'industry',
    'sector_source',
    'exchange',
    'supersedes',
    'supersedes_source',
    'supersedes_confidence',
}
FRONTMATTER_PATTERN = re.compile(r'\A---\n(?P<yaml>.*?)\n---(?:\n(?P<body>.*))?\Z', re.DOTALL)
DOCUMENT_ID_PATTERN = re.compile(r'^(?P<source>[a-z][a-z0-9_]*):(?P<source_id>\S+)$')
FISCAL_PERIOD_PATTERN = re.compile(r'^\d{4}-(?:FY|Q[1-4]|\d{2}-\d{2})$')
CONTENT_HASH_PATTERN = re.compile(r'^[0-9a-f]{8}$')
FRONTMATTER_CONTENT_HASH_PATTERN = re.compile(
    r'^content_hash:\s*(?P<quote>[\'"]?)(?P<hash>[0-9a-f]{8})(?P=quote)\s*$',
    re.MULTILINE,
)


@dataclass(frozen=True)
class FrontmatterValidationError(Exception):
    missing_required: list[str]
    invalid_types: list[tuple[str, str]]


def build_frontmatter(metadata: dict, *, with_placeholder_hash: bool = True) -> str:
    """Validate metadata against the spec and serialize it to YAML frontmatter."""
    normalized = _validated_metadata(
        metadata,
        require_content_hash=not with_placeholder_hash,
        allow_placeholder_hash=with_placeholder_hash,
        apply_defaults=True,
    )
    content_hash = (
        CANONICAL_HASH_PLACEHOLDER
        if with_placeholder_hash
        else normalized['content_hash']
    )
    ordered = _ordered_frontmatter(normalized, content_hash=content_hash)
    yaml_text = yaml.safe_dump(ordered, sort_keys=False)
    return f'---\n{yaml_text}---'


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split frontmatter from body text and validate the parsed metadata."""
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        raise FrontmatterValidationError(
            missing_required=[],
            invalid_types=[('frontmatter', "expected '---\\n{yaml}\\n---\\n{body}'")],
        )

    try:
        loaded = yaml.safe_load(match.group('yaml')) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterValidationError(
            missing_required=[],
            invalid_types=[('frontmatter', f'malformed YAML: {exc}')],
        ) from exc

    if not isinstance(loaded, dict):
        raise FrontmatterValidationError(
            missing_required=[],
            invalid_types=[('frontmatter', 'frontmatter root must be a mapping')],
        )

    normalized = _normalize_loaded_mapping(loaded)
    validated = _validated_metadata(
        normalized,
        require_content_hash=True,
        allow_placeholder_hash=True,
        apply_defaults=True,
    )
    body = match.group('body') or ''
    return validated, body


def assemble_canonical_text(metadata: dict, body: str) -> str:
    """Assemble frontmatter with the placeholder hash followed by the body."""
    if not isinstance(body, str):
        raise FrontmatterValidationError(
            missing_required=[],
            invalid_types=[('body', f'expected str, got {type(body).__name__}')],
        )
    return build_frontmatter(metadata, with_placeholder_hash=True) + '\n' + body


def finalize_with_hash(assembled_text_with_placeholder: str) -> tuple[str, str]:
    """Replace the placeholder hash with the real 8-char SHA-1 hash."""
    assert CANONICAL_HASH_PLACEHOLDER in assembled_text_with_placeholder, (
        'assembled_text must contain CANONICAL_HASH_PLACEHOLDER'
    )
    sha1 = hashlib.sha1(assembled_text_with_placeholder.encode('utf-8')).hexdigest()
    content_hash = sha1[:8]
    finalized = assembled_text_with_placeholder.replace(
        CANONICAL_HASH_PLACEHOLDER,
        content_hash,
        1,
    )
    return finalized, content_hash


def verify_content_hash(text: str) -> bool:
    """Verify that the stored frontmatter content_hash matches the canonical form."""
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return False

    yaml_block = match.group('yaml')
    hash_match = FRONTMATTER_CONTENT_HASH_PATTERN.search(yaml_block)
    if not hash_match:
        return False

    stored_hash = hash_match.group('hash')
    canonical_yaml = FRONTMATTER_CONTENT_HASH_PATTERN.sub(
        lambda match: (
            f"content_hash: {match.group('quote')}"
            f'{CANONICAL_HASH_PLACEHOLDER}'
            f"{match.group('quote')}"
        ),
        yaml_block,
        count=1,
    )

    canonical_text = f'---\n{canonical_yaml}\n---'
    body = match.group('body')
    if body is not None:
        canonical_text += f'\n{body}'

    sha1 = hashlib.sha1(canonical_text.encode('utf-8')).hexdigest()
    return sha1[:8] == stored_hash


def canonical_path(metadata: dict, corpus_root: Path) -> Path:
    """Compute the canonical on-disk path for a finalized corpus document."""
    if not isinstance(metadata, dict):
        raise FrontmatterValidationError(
            missing_required=[],
            invalid_types=[('metadata', f'expected dict, got {type(metadata).__name__}')],
        )

    required = ('source', 'ticker', 'form_type', 'fiscal_period', 'content_hash')
    missing = [field for field in required if field not in metadata]
    invalid: list[tuple[str, str]] = []

    for field in required:
        if field in metadata and not isinstance(metadata[field], str):
            invalid.append((field, f'expected str, got {type(metadata[field]).__name__}'))

    source = metadata.get('source')
    if isinstance(source, str) and source not in ALLOWED_SOURCES:
        invalid.append(('source', f'unsupported source {source!r}'))

    form_type = metadata.get('form_type')
    if isinstance(form_type, str) and form_type not in ALLOWED_FORM_TYPES:
        invalid.append(('form_type', f'unsupported form_type {form_type!r}'))

    fiscal_period = metadata.get('fiscal_period')
    if isinstance(fiscal_period, str) and not _is_valid_fiscal_period(fiscal_period):
        invalid.append(('fiscal_period', f'invalid fiscal period {fiscal_period!r}'))

    content_hash = metadata.get('content_hash')
    if isinstance(content_hash, str) and not CONTENT_HASH_PATTERN.fullmatch(content_hash):
        invalid.append(('content_hash', 'expected 8 lowercase hex chars'))

    ticker = metadata.get('ticker')
    if isinstance(ticker, str):
        if (
            not ticker
            or ticker != ticker.strip()
            or ticker != ticker.upper()
            or any(char in ticker for char in ':/ ')
        ):
            invalid.append(
                (
                    'ticker',
                    f'non-canonical ticker {ticker!r} — caller must canonicalize via SymbolResolver',
                )
            )

    _raise_if_invalid(missing, invalid)

    filename = f"{metadata['form_type']}_{metadata['fiscal_period']}_{metadata['content_hash']}.md"
    return Path(corpus_root) / metadata['source'] / metadata['ticker'] / filename


def _validated_metadata(
    metadata: dict[str, Any],
    *,
    require_content_hash: bool,
    allow_placeholder_hash: bool,
    apply_defaults: bool,
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise FrontmatterValidationError(
            missing_required=[],
            invalid_types=[('metadata', f'expected dict, got {type(metadata).__name__}')],
        )

    normalized = dict(metadata)
    if apply_defaults:
        normalized.setdefault('extraction_status', 'complete')

    missing_required = [
        field
        for field in REQUIRED_FIELDS
        if field != 'content_hash'
        and field not in normalized
    ]
    if require_content_hash and 'content_hash' not in normalized:
        missing_required.append('content_hash')

    invalid_types: list[tuple[str, str]] = []

    for field in normalized:
        if field not in FIELD_ORDER:
            invalid_types.append((field, 'unexpected field'))

    for field in REQUIRED_FIELDS:
        if field == 'content_hash' and not require_content_hash and field not in normalized:
            continue
        if field in normalized and not isinstance(normalized[field], str):
            invalid_types.append((field, f'expected str, got {type(normalized[field]).__name__}'))

    for field in NULLABLE_STRING_FIELDS:
        if field in normalized and normalized[field] is not None and not isinstance(normalized[field], str):
            invalid_types.append((field, f'expected str or null, got {type(normalized[field]).__name__}'))

    document_id = normalized.get('document_id')
    source = normalized.get('source')
    if isinstance(document_id, str):
        match = DOCUMENT_ID_PATTERN.fullmatch(document_id)
        if not match:
            invalid_types.append(('document_id', 'expected {source}:{canonical_source_id}'))
        elif isinstance(source, str) and match.group('source') != source:
            invalid_types.append(
                ('document_id', f"source prefix {match.group('source')!r} does not match source {source!r}")
            )

    ticker = normalized.get('ticker')
    if isinstance(ticker, str) and not ticker.strip():
        invalid_types.append(('ticker', 'must not be blank'))

    if isinstance(source, str) and source not in ALLOWED_SOURCES:
        invalid_types.append(('source', f'unsupported source {source!r}'))

    form_type = normalized.get('form_type')
    if isinstance(form_type, str) and form_type not in ALLOWED_FORM_TYPES:
        invalid_types.append(('form_type', f'unsupported form_type {form_type!r}'))

    cik = normalized.get('cik')
    if isinstance(cik, str) and not re.fullmatch(r'\d{10}', cik):
        invalid_types.append(('cik', 'expected zero-padded 10-digit SEC CIK'))

    fiscal_period = normalized.get('fiscal_period')
    if isinstance(fiscal_period, str) and not _is_valid_fiscal_period(fiscal_period):
        invalid_types.append(
            ('fiscal_period', 'expected YYYY-FY, YYYY-QN, or YYYY-MM-DD'),
        )

    for field in ('filing_date', 'period_end'):
        value = normalized.get(field)
        if isinstance(value, str) and not _is_valid_iso_date(value):
            invalid_types.append((field, 'expected ISO-8601 date'))

    for field in ('source_url', 'source_url_deep'):
        value = normalized.get(field)
        if isinstance(value, str) and not _is_valid_url(value):
            invalid_types.append((field, 'expected absolute http(s) URL'))

    extraction_at = normalized.get('extraction_at')
    if isinstance(extraction_at, str) and not _is_valid_iso_timestamp(extraction_at):
        invalid_types.append(('extraction_at', 'expected ISO-8601 timestamp'))

    extraction_status = normalized.get('extraction_status')
    if isinstance(extraction_status, str) and extraction_status not in ALLOWED_EXTRACTION_STATUSES:
        invalid_types.append(
            (
                'extraction_status',
                f'expected one of {sorted(ALLOWED_EXTRACTION_STATUSES)}',
            )
        )

    supersedes_source = normalized.get('supersedes_source')
    if isinstance(supersedes_source, str) and supersedes_source not in ALLOWED_SUPERSEDES_SOURCES:
        invalid_types.append(
            (
                'supersedes_source',
                f'expected one of {sorted(ALLOWED_SUPERSEDES_SOURCES)}',
            )
        )

    supersedes_confidence = normalized.get('supersedes_confidence')
    if isinstance(supersedes_confidence, str) and supersedes_confidence not in ALLOWED_SUPERSEDES_CONFIDENCES:
        invalid_types.append(
            (
                'supersedes_confidence',
                f'expected one of {sorted(ALLOWED_SUPERSEDES_CONFIDENCES)}',
            )
        )

    if 'content_hash' in normalized and isinstance(normalized['content_hash'], str):
        content_hash = normalized['content_hash']
        if content_hash == CANONICAL_HASH_PLACEHOLDER:
            if not allow_placeholder_hash:
                invalid_types.append(('content_hash', 'placeholder hash is only valid before finalization'))
        elif not CONTENT_HASH_PATTERN.fullmatch(content_hash):
            invalid_types.append(('content_hash', 'expected 8 lowercase hex chars'))

    _raise_if_invalid(missing_required, invalid_types)
    return normalized


def _ordered_frontmatter(metadata: dict[str, Any], *, content_hash: str) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for field in FIELD_ORDER:
        if field == 'content_hash':
            ordered[field] = content_hash
        elif field in metadata:
            ordered[field] = metadata[field]
    return ordered


def _normalize_loaded_mapping(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, datetime):
            normalized[key] = value.isoformat()
        elif isinstance(value, date):
            normalized[key] = value.isoformat()
        else:
            normalized[key] = value
    return normalized


def _is_valid_fiscal_period(value: str) -> bool:
    if not FISCAL_PERIOD_PATTERN.fullmatch(value):
        return False
    if re.fullmatch(r'^\d{4}-\d{2}-\d{2}$', value):
        return _is_valid_iso_date(value)
    return True


def _is_valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_valid_iso_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return True


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def _raise_if_invalid(
    missing_required: list[str],
    invalid_types: list[tuple[str, str]],
) -> None:
    if missing_required or invalid_types:
        raise FrontmatterValidationError(
            missing_required=missing_required,
            invalid_types=invalid_types,
        )


__all__ = [
    'CANONICAL_HASH_PLACEHOLDER',
    'FrontmatterValidationError',
    'assemble_canonical_text',
    'build_frontmatter',
    'canonical_path',
    'finalize_with_hash',
    'parse_frontmatter',
    'verify_content_hash',
]
