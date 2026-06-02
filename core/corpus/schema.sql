CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    cik TEXT,
    company_name TEXT,
    source TEXT NOT NULL,
    form_type TEXT NOT NULL,
    fiscal_period TEXT,
    filing_date DATE,
    period_end DATE,
    source_url TEXT,
    source_url_deep TEXT,
    source_accession TEXT,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    extraction_pipeline TEXT,
    extraction_model TEXT,
    extraction_at TIMESTAMP,
    extraction_status TEXT DEFAULT 'complete',
    sector TEXT,
    industry TEXT,
    sector_source TEXT,
    exchange TEXT,
    supersedes TEXT REFERENCES documents(document_id),
    supersedes_source TEXT,
    supersedes_confidence TEXT,
    is_superseded_by TEXT REFERENCES documents(document_id),
    last_indexed TIMESTAMP,
    parser_version TEXT,
    parser_schema_version INTEGER,
    parser_path TEXT,
    parser_state TEXT,
    parser_result_status TEXT,
    cross_reference_target TEXT,
    producer_deployment_id TEXT,
    producer_instance_id TEXT,
    producer_build_id TEXT,
    CHECK (supersedes_confidence IS NULL OR supersedes_confidence IN ('high', 'medium', 'low')),
    CHECK (
        fiscal_period IS NULL
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-FY'
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-Q[1-4]'
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    )
);

CREATE TABLE IF NOT EXISTS corpus_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corpus_reingest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    accession TEXT NOT NULL,
    ticker TEXT NOT NULL,
    old_file_path TEXT,
    new_file_path TEXT NOT NULL,
    old_content_hash TEXT,
    new_content_hash TEXT NOT NULL,
    content_changed INTEGER NOT NULL DEFAULT 0,
    parser_version_before TEXT,
    parser_version_after TEXT,
    reason TEXT NOT NULL,
    invalidation_id TEXT,
    status TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    error TEXT,
    CHECK (status IN (
        'planned', 'new_written', 'db_upserted', 'old_deleted',
        'complete', 'no_change', 'abandoned',
        'planned_failed', 'new_written_failed', 'db_upserted_failed', 'old_deleted_failed'
    ))
);

CREATE INDEX IF NOT EXISTS idx_documents_ticker ON documents(ticker);
CREATE INDEX IF NOT EXISTS idx_documents_form_type ON documents(form_type);
CREATE INDEX IF NOT EXISTS idx_documents_is_superseded ON documents(is_superseded_by);
CREATE INDEX IF NOT EXISTS idx_documents_supersedes ON documents(supersedes);
CREATE INDEX IF NOT EXISTS idx_documents_sector ON documents(sector);
CREATE INDEX IF NOT EXISTS idx_reingest_invalidation ON corpus_reingest_log(invalidation_id);
CREATE INDEX IF NOT EXISTS idx_reingest_document ON corpus_reingest_log(document_id, started_at);
CREATE INDEX IF NOT EXISTS idx_reingest_active ON corpus_reingest_log(status)
    WHERE status NOT IN ('complete', 'no_change', 'abandoned');

CREATE TABLE IF NOT EXISTS html_corpus_mapping_sets (
    mapping_set_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    accession TEXT NOT NULL,
    primary_document_url TEXT NOT NULL,
    source_html_hash TEXT NOT NULL,
    corpus_content_hash TEXT NOT NULL,
    sanitizer_version TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    parser_schema_version INTEGER NOT NULL,
    visible_text_algorithm_version TEXT NOT NULL,
    mapping_algorithm_version TEXT NOT NULL,
    sidecar_path TEXT NOT NULL,
    sidecar_hash TEXT NOT NULL,
    producer_json TEXT,
    provenance TEXT NOT NULL DEFAULT 'producer',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL,
    CHECK (active IN (0, 1)),
    CHECK (provenance IN ('producer', 'legacy_backfill')),
    UNIQUE (
        document_id,
        source_html_hash,
        corpus_content_hash,
        sanitizer_version,
        parser_version,
        parser_schema_version,
        visible_text_algorithm_version,
        mapping_algorithm_version
    )
);

CREATE TABLE IF NOT EXISTS html_corpus_mapping_records (
    mapping_record_id TEXT PRIMARY KEY,
    mapping_set_id TEXT NOT NULL REFERENCES html_corpus_mapping_sets(mapping_set_id) ON DELETE CASCADE,
    producer_record_id TEXT NOT NULL,
    section_id TEXT NOT NULL,
    section_header TEXT NOT NULL,
    content_type TEXT NOT NULL,
    corpus_char_start INTEGER NOT NULL,
    corpus_char_end INTEGER NOT NULL,
    offset_frame TEXT NOT NULL,
    visible_text_offset_frame TEXT NOT NULL,
    visible_text_char_start INTEGER NOT NULL,
    visible_text_char_end INTEGER NOT NULL,
    quote TEXT NOT NULL,
    text_before TEXT,
    text_after TEXT,
    confidence TEXT NOT NULL,
    producer_trace_json TEXT NOT NULL,
    diagnostics_json TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL,
    CHECK (corpus_char_start >= 0),
    CHECK (corpus_char_end > corpus_char_start),
    CHECK (visible_text_char_start >= 0),
    CHECK (visible_text_char_end > visible_text_char_start),
    CHECK (offset_frame = 'corpus_doc'),
    CHECK (visible_text_offset_frame = 'source_html_visible_text_v1'),
    CHECK (content_type IN ('prose', 'table', 'heading', 'footnote', 'unknown')),
    CHECK (confidence IN ('exact', 'high', 'quote', 'section_only', 'none')),
    CHECK (active IN (0, 1)),
    UNIQUE (mapping_set_id, producer_record_id)
);

CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_sets_document
    ON html_corpus_mapping_sets(document_id, active);

CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_sets_identity
    ON html_corpus_mapping_sets(
        document_id,
        source_html_hash,
        corpus_content_hash,
        sanitizer_version,
        visible_text_algorithm_version,
        mapping_algorithm_version,
        active
    );

CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_records_set
    ON html_corpus_mapping_records(mapping_set_id, active);

CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_records_span
    ON html_corpus_mapping_records(mapping_set_id, corpus_char_start, corpus_char_end);

CREATE INDEX IF NOT EXISTS idx_html_corpus_mapping_records_visible_span
    ON html_corpus_mapping_records(mapping_set_id, visible_text_char_start, visible_text_char_end);

CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    document_id UNINDEXED,
    section UNINDEXED,
    content,
    char_start UNINDEXED,
    char_end UNINDEXED,
    speaker_name UNINDEXED,
    speaker_role UNINDEXED,
    tokenize = 'porter unicode61'
);
-- Note: SQLite does not support CREATE INDEX on FTS5 virtual tables. Document_id
-- lookups go through WHERE clauses on UNINDEXED columns; FTS5 handles this via
-- bitmap scans of the index's row metadata. If hot, Phase 1 may add a companion
-- regular table with (document_id -> rowid).

CREATE TABLE IF NOT EXISTS sections_fts_metadata (
    fts_rowid INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    form_type TEXT NOT NULL,
    fiscal_period TEXT,
    filing_date DATE,
    extraction_status TEXT,
    sector TEXT,
    is_superseded_by TEXT,
    section TEXT NOT NULL,
    speaker_name TEXT,
    speaker_role TEXT,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    CHECK (char_start >= 0),
    CHECK (char_end >= char_start)
);

CREATE INDEX IF NOT EXISTS idx_sections_fts_metadata_filters
    ON sections_fts_metadata(
        ticker,
        source,
        form_type,
        is_superseded_by,
        extraction_status
    );

CREATE INDEX IF NOT EXISTS idx_sections_fts_metadata_document
    ON sections_fts_metadata(document_id);

CREATE INDEX IF NOT EXISTS idx_sections_fts_metadata_section
    ON sections_fts_metadata(section);

CREATE INDEX IF NOT EXISTS idx_sections_fts_metadata_speaker_role
    ON sections_fts_metadata(speaker_role);

CREATE TABLE IF NOT EXISTS sections_fts_metadata_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    is_complete INTEGER NOT NULL DEFAULT 0,
    refreshed_at TIMESTAMP,
    CHECK (is_complete IN (0, 1))
);
