from __future__ import annotations

from pathlib import Path
import re

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


def normalize_fts5_query(raw: str) -> tuple[str, list[str]]:
    """Reduce a user-provided query to a best-effort safe FTS5 expression.

    Removes prose punctuation outside double-quoted phrases. Preserves
    Unicode word characters and whitespace. Quoted phrase contents are kept
    verbatim, including punctuation that would otherwise be stripped.

    Returns (normalized, warnings). The warnings vocabulary covers semantic
    transformations only (punctuation_stripped, unbalanced_quote_stripped,
    query_reduced_to_empty). Whitespace collapse is silent.

    The output is *not* guaranteed to be valid FTS5 -- orphan operators like
    `NOT cloud` or `cloud AND` survive and will be caught by the backstop
    in `_search`. Empty result is a normal outcome; the caller returns an
    empty SearchResponse.
    """
    warnings: set[str] = set()

    quote_idxs = [i for i, c in enumerate(raw) if c == '"']
    if len(quote_idxs) % 2 == 1:
        warnings.add('unbalanced_quote_stripped')
        quote_idxs = quote_idxs[:-1]

    segments: list[tuple[str, str]] = []
    cursor = 0
    for i in range(0, len(quote_idxs), 2):
        ps, pe = quote_idxs[i], quote_idxs[i + 1]
        if cursor < ps:
            segments.append(('bare', raw[cursor:ps]))
        segments.append(('phrase', raw[ps + 1:pe]))
        cursor = pe + 1
    if cursor < len(raw):
        segments.append(('bare', raw[cursor:]))

    out_parts: list[str] = []
    for kind, text in segments:
        if kind == 'phrase':
            out_parts.append(f'"{text}"')
            continue

        cleaned_chars = []
        for ch in text:
            if re.match(r'[\w\s]', ch):
                cleaned_chars.append(ch)
            else:
                cleaned_chars.append(' ')
                warnings.add('punctuation_stripped')
        collapsed = ' '.join(''.join(cleaned_chars).split())
        if collapsed:
            out_parts.append(collapsed)

    result = ' '.join(p for p in out_parts if p)
    if not result:
        warnings.add('query_reduced_to_empty')

    order = ['punctuation_stripped', 'unbalanced_quote_stripped', 'query_reduced_to_empty']
    return result, [w for w in order if w in warnings]


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
    'normalize_fts5_query',
    'validate_read_path',
    'validate_search_inputs',
]
