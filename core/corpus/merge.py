from __future__ import annotations

from core.corpus.types import SearchHit, SearchResponse


def merge_responses(responses: list[SearchResponse]) -> list[SearchHit]:
    """Merge SearchHits from multiple SearchResponse envelopes by BM25 rank ascending.

    Use this to combine parallel filings_search + transcripts_search calls for
    cross-source queries. SQLite FTS5 BM25 scores are smaller = better match,
    so sort ascending.

    Returns a flat list of SearchHit objects ordered by rank. No dedup - each
    hit is a unique (document_id, section) pair. Callers who want a truncated
    cross-source top-N can slice the returned list.
    """
    hits = [hit for response in responses for hit in response.hits]
    return sorted(hits, key=lambda hit: hit.rank)


__all__ = ['merge_responses']
