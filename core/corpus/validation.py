from __future__ import annotations

from pathlib import Path

from core.corpus.types import InvalidInputError


MAX_QUERY_LEN = 1024
MAX_UNIVERSE_SIZE = 5000
MAX_LIMIT = 500


def _validate_canonical_ticker(ticker, *, field: str) -> None:
    if not isinstance(ticker, str):
        raise InvalidInputError(
            f'{field} contains non-string value {ticker!r}'
        )
    if (
        not ticker
        or ticker != ticker.strip()
        or ticker != ticker.upper()
        or any(ch in ticker for ch in ':/ ')
    ):
        raise InvalidInputError(
            f'{field} contains non-canonical ticker {ticker!r}: '
            "expected uppercase with no leading/trailing whitespace "
            "and no ' ', ':', or '/' characters"
        )


def validate_search_inputs(
    query: str,
    universe: list[str] | None,
    limit: int,
) -> None:
    if len(query) > MAX_QUERY_LEN:
        raise InvalidInputError(f'query exceeds max length {MAX_QUERY_LEN}')
    if universe and len(universe) > MAX_UNIVERSE_SIZE:
        raise InvalidInputError(f'universe exceeds max size {MAX_UNIVERSE_SIZE}')
    if universe:
        for i, ticker in enumerate(universe):
            _validate_canonical_ticker(ticker, field=f'universe[{i}]')
    if limit > MAX_LIMIT:
        raise InvalidInputError(f'limit exceeds cap {MAX_LIMIT}')
    if limit < 1:
        raise InvalidInputError('limit must be >= 1')


def validate_read_path(file_path: str, corpus_root: Path) -> Path:
    """Resolve + canonicalize; ensure result is under corpus_root."""
    p = Path(file_path).resolve()
    root = Path(corpus_root).resolve()
    if not p.is_relative_to(root):
        raise InvalidInputError(f'Path {p} outside corpus root')
    return p


__all__ = [
    'MAX_LIMIT',
    'MAX_QUERY_LEN',
    'MAX_UNIVERSE_SIZE',
    'validate_read_path',
    'validate_search_inputs',
]
