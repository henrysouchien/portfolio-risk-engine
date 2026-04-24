from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    ticker: str
    company_name: str
    source: str
    form_type: str
    fiscal_period: str
    filing_date: str
    is_superseded: bool
    has_low_confidence_supersession: bool
    section: str
    snippet: str
    file_path: str
    char_start: int
    char_end: int
    source_url: str
    source_url_deep: str | None
    source_accession: str | None
    rank: float


@dataclass(frozen=True)
class SearchResponse:
    hits: list[SearchHit]
    applied_filters: dict[str, Any]
    total_matches: int
    has_superseded_matches: bool
    has_low_confidence_supersession: bool
    query_warnings: list[str]


@dataclass(frozen=True)
class DocumentMetadata:
    """Return type for *_list tools — document-grain, no sections/snippets."""

    document_id: str
    ticker: str
    form_type: str
    fiscal_period: str
    filing_date: str
    is_superseded: bool
    file_path: str
    source_url: str


class AmbiguousDocumentError(Exception):
    """Raised when a tuple lookup matches multiple non-superseded documents."""

    def __init__(self, candidates: list[str], *, ticker: str, form_type: str, fiscal_period: str):
        self.candidates = candidates
        self.ticker = ticker
        self.form_type = form_type
        self.fiscal_period = fiscal_period
        super().__init__(
            f"Ambiguous document: {len(candidates)} matches for "
            f"({ticker}, {form_type}, {fiscal_period}): {candidates}"
        )


class InvalidInputError(Exception):
    """Raised by I13 tool-boundary validation on limit/length/path violations."""


class ExcerptUnavailableError(Exception):
    """Raised when the authoritative source excerpt cannot be fetched."""

    def __init__(self, document_id: str, reason: str):
        self.document_id = document_id
        self.reason = reason
        super().__init__(f'Source excerpt unavailable for {document_id}: {reason}')


__all__ = [
    'AmbiguousDocumentError',
    'DocumentMetadata',
    'ExcerptUnavailableError',
    'InvalidInputError',
    'SearchHit',
    'SearchResponse',
]
