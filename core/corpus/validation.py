from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3

from core.corpus.types import InvalidInputError


MAX_QUERY_LEN = 1024
MAX_UNIVERSE_SIZE = 5000
MAX_LIMIT = 500
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_DATA_DIR = _REPO_ROOT / 'data' / 'corpus'
_CIK_CACHE_DIR = _CORPUS_DATA_DIR / 'cache' / 'phase2_ciks'
_UNIVERSE_FILES = (
    _CORPUS_DATA_DIR / 'universe.json',
    _CORPUS_DATA_DIR / 'universe_phase2.json',
)


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


def resolve_corpus_universe_aliases(
    db: sqlite3.Connection,
    universe: list[str] | None,
) -> tuple[list[str] | None, list[str]]:
    """Resolve ticker filters to indexed ticker(s) for the same SEC issuer CIK."""
    if universe is None:
        return None, []

    resolved: list[str] = []
    warnings: list[str] = []
    existing_by_cik: dict[str, list[str]] = {}

    for ticker in universe:
        selected = [ticker]
        if not _ticker_exists_in_corpus(db, ticker):
            cik = _lookup_reference_cik(ticker)
            if cik:
                existing = existing_by_cik.setdefault(
                    cik,
                    _indexed_tickers_for_cik(db, cik),
                )
                if existing:
                    selected = existing
                    warnings.append(
                        f'ticker_alias_resolved_by_cik: {ticker}->{",".join(selected)}'
                    )

        for candidate in selected:
            if candidate not in resolved:
                resolved.append(candidate)

    return resolved, warnings


def resolve_corpus_ticker_alias(db: sqlite3.Connection, ticker: str) -> str:
    """Resolve one ticker filter against indexed share-class aliases."""
    resolved, _warnings = resolve_corpus_universe_aliases(db, [ticker])
    if not resolved:
        return ticker
    return resolved[0]


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


def _ticker_exists_in_corpus(db: sqlite3.Connection, ticker: str) -> bool:
    row = db.execute(
        'SELECT 1 FROM documents WHERE ticker = ? LIMIT 1',
        (ticker,),
    ).fetchone()
    return row is not None


def _indexed_tickers_for_cik(db: sqlite3.Connection, cik: str) -> list[str]:
    rows = db.execute(
        """
        SELECT ticker, MAX(filing_date) AS last_filing_date
        FROM documents
        WHERE cik = ?
        GROUP BY ticker
        ORDER BY last_filing_date DESC, ticker ASC
        """,
        (cik,),
    ).fetchall()
    return [str(row['ticker']) for row in rows]


def _lookup_reference_cik(ticker: str) -> str | None:
    """Resolve ticker->CIK from local corpus reference artifacts, no network calls."""
    ticker = ticker.strip().upper()

    profile_path = _CIK_CACHE_DIR / f'{ticker}.json'
    profile = _read_json(profile_path)
    cik = _normalize_cik(profile.get('cik')) if isinstance(profile, dict) else None
    if cik:
        return cik

    for universe_path in _UNIVERSE_FILES:
        cik = _lookup_cik_in_universe_file(universe_path, ticker)
        if cik:
            return cik

    return None


def _lookup_cik_in_universe_file(path: Path, ticker: str) -> str | None:
    payload = _read_json(path)
    if payload is None:
        return None

    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            symbol = str(value.get('symbol') or value.get('ticker') or '').strip().upper()
            if symbol == ticker:
                cik = _normalize_cik(value.get('cik'))
                if cik:
                    return cik
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return None


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError, OSError):
        return None


def _normalize_cik(value: object) -> str | None:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if not digits:
        return None
    return digits.zfill(10)


__all__ = [
    'MAX_LIMIT',
    'MAX_QUERY_LEN',
    'MAX_UNIVERSE_SIZE',
    'normalize_fts5_query',
    'resolve_corpus_ticker_alias',
    'resolve_corpus_universe_aliases',
    'validate_read_path',
    'validate_search_inputs',
]
