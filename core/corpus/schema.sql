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
