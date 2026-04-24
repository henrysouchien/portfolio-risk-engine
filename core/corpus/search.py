from __future__ import annotations

import sqlite3

from core.corpus.types import SearchHit, SearchResponse


_LOW_CONFIDENCE_SUPERSEDER_EXISTS_SQL = (
    "EXISTS ("
    "SELECT 1 FROM documents d3 "
    "WHERE d3.supersedes = d.document_id "
    "AND d3.supersedes_confidence IN ('low', 'medium')"
    ")"
)

_TRANSCRIPT_SECTION_FILTERS = {
    'prepared_remarks': 'Prepared Remarks',
    'qa': 'Q&A Session',
    'both': None,
}


def _resolved_source_url_sql(document_alias: str = 'd') -> str:
    return (
        "COALESCE("
        f"{document_alias}.source_url, "
        "CASE "
        f"WHEN {document_alias}.source = 'fmp_transcripts' "
        f"AND {document_alias}.fiscal_period GLOB '[0-9][0-9][0-9][0-9]-Q[1-4]' "
        "THEN "
        "'https://financialmodelingprep.com/financial-summary/' || "
        f"{document_alias}.ticker || "
        "'?transcript=' || "
        f"substr({document_alias}.fiscal_period, 1, 4) || "
        "'Q' || "
        f"substr({document_alias}.fiscal_period, 7, 1) "
        "END"
        ")"
    )


def _search(
    db: sqlite3.Connection,
    query: str,
    form_types: list[str],
    sources: list[str],
    universe: list[str] | None = None,
    sector: str | None = None,
    section: str | None = None,
    speaker_role: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_superseded: bool = False,
    include_low_confidence_supersession: bool = False,
    limit: int = 20,
) -> SearchResponse:
    """Run a metadata-filtered FTS query across the unified corpus index."""
    applied_filters = {
        'form_types': list(form_types),
        'sources': list(sources),
        'universe': list(universe) if universe is not None else None,
        'sector': sector,
        'section': section,
        'speaker_role': speaker_role,
        'date_from': date_from,
        'date_to': date_to,
        'include_superseded': include_superseded,
        'include_low_confidence_supersession': include_low_confidence_supersession,
        'limit': limit,
    }

    if not form_types or not sources or (universe is not None and len(universe) == 0):
        return SearchResponse(
            hits=[],
            applied_filters=applied_filters,
            total_matches=0,
            has_superseded_matches=False,
            has_low_confidence_supersession=False,
            query_warnings=[],
        )

    where_clauses, where_params = _build_where_clause(
        form_types=form_types,
        sources=sources,
        universe=universe,
        sector=sector,
        section=section,
        speaker_role=speaker_role,
        date_from=date_from,
        date_to=date_to,
        include_superseded=include_superseded,
        include_low_confidence_supersession=include_low_confidence_supersession,
    )
    where_sql = ' AND '.join(where_clauses + ['s.content MATCH ?'])
    base_params = [*where_params, query]

    rows = db.execute(
        f"""
        SELECT
            d.document_id,
            d.ticker,
            COALESCE(d.company_name, '') AS company_name,
            d.source,
            d.form_type,
            COALESCE(d.fiscal_period, '') AS fiscal_period,
            COALESCE(CAST(d.filing_date AS TEXT), '') AS filing_date,
            d.is_superseded_by IS NOT NULL AS is_superseded,
            {_LOW_CONFIDENCE_SUPERSEDER_EXISTS_SQL} AS has_low_confidence_supersession,
            s.section,
            snippet(sections_fts, 2, '<b>', '</b>', '...', 20) AS snippet,
            d.file_path,
            s.char_start,
            s.char_end,
            {_resolved_source_url_sql('d')} AS source_url,
            d.source_url_deep,
            d.source_accession,
            bm25(sections_fts) AS rank
        FROM documents d
        JOIN sections_fts s USING (document_id)
        WHERE {where_sql}
        ORDER BY rank ASC, d.document_id ASC, s.char_start ASC
        LIMIT ?
        """,
        [*base_params, limit],
    ).fetchall()

    total_matches = int(
        db.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM documents d
            JOIN sections_fts s USING (document_id)
            WHERE {where_sql}
            """,
            base_params,
        ).fetchone()['count']
    )

    has_superseded_matches = False
    if not include_superseded:
        superseded_variant_where, superseded_variant_params = _build_where_clause(
            form_types=form_types,
            sources=sources,
            universe=universe,
            sector=sector,
            section=section,
            speaker_role=speaker_role,
            date_from=date_from,
            date_to=date_to,
            include_superseded=True,
            include_low_confidence_supersession=include_low_confidence_supersession,
        )
        superseded_count = int(
            db.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM documents d
                JOIN sections_fts s USING (document_id)
                WHERE {' AND '.join(superseded_variant_where + ['s.content MATCH ?'])}
                """,
                [*superseded_variant_params, query],
            ).fetchone()['count']
        )
        has_superseded_matches = superseded_count > total_matches

    hits = [
        SearchHit(
            document_id=str(row['document_id']),
            ticker=str(row['ticker']),
            company_name=str(row['company_name'] or ''),
            source=str(row['source']),
            form_type=str(row['form_type']),
            fiscal_period=str(row['fiscal_period'] or ''),
            filing_date=str(row['filing_date'] or ''),
            is_superseded=bool(row['is_superseded']),
            has_low_confidence_supersession=bool(row['has_low_confidence_supersession']),
            section=str(row['section']),
            snippet=str(row['snippet'] or ''),
            file_path=str(row['file_path']),
            char_start=int(row['char_start']),
            char_end=int(row['char_end']),
            source_url=str(row['source_url'] or ''),
            source_url_deep=str(row['source_url_deep']) if row['source_url_deep'] is not None else None,
            source_accession=str(row['source_accession']) if row['source_accession'] is not None else None,
            rank=float(row['rank']),
        )
        for row in rows
    ]

    return SearchResponse(
        hits=hits,
        applied_filters=applied_filters,
        total_matches=total_matches,
        has_superseded_matches=has_superseded_matches,
        has_low_confidence_supersession=any(hit.has_low_confidence_supersession for hit in hits),
        query_warnings=[],
    )


def _build_where_clause(
    *,
    form_types: list[str],
    sources: list[str],
    universe: list[str] | None,
    sector: str | None,
    section: str | None,
    speaker_role: str | None,
    date_from: str | None,
    date_to: str | None,
    include_superseded: bool,
    include_low_confidence_supersession: bool,
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    clauses.append(f"d.form_type IN ({_placeholders(form_types)})")
    params.extend(form_types)

    clauses.append(f"d.source IN ({_placeholders(sources)})")
    params.extend(sources)

    if universe:
        clauses.append(f"d.ticker IN ({_placeholders(universe)})")
        params.extend(universe)

    if sector is not None:
        clauses.append('d.sector = ?')
        params.append(sector)

    transcript_section = _TRANSCRIPT_SECTION_FILTERS.get(section) if section is not None else None
    if transcript_section is not None:
        clauses.append('s.section = ?')
        params.append(transcript_section)

    if speaker_role is not None:
        clauses.append('s.speaker_role = ?')
        params.append(speaker_role)

    if date_from is not None:
        clauses.append('d.filing_date >= ?')
        params.append(date_from)

    if date_to is not None:
        clauses.append('d.filing_date <= ?')
        params.append(date_to)

    if not include_superseded:
        clauses.append('d.is_superseded_by IS NULL')

    if include_low_confidence_supersession:
        clauses.append(f'NOT {_LOW_CONFIDENCE_SUPERSEDER_EXISTS_SQL}')

    return clauses, params


def _placeholders(values: list[object]) -> str:
    return ', '.join('?' for _ in values)


__all__ = ['_search']
