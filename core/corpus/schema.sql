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
    CHECK (supersedes_confidence IS NULL OR supersedes_confidence IN ('high', 'medium', 'low')),
    CHECK (
        fiscal_period IS NULL
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-FY'
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-Q[1-4]'
        OR fiscal_period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    )
);

CREATE INDEX IF NOT EXISTS idx_documents_ticker ON documents(ticker);
CREATE INDEX IF NOT EXISTS idx_documents_form_type ON documents(form_type);
CREATE INDEX IF NOT EXISTS idx_documents_is_superseded ON documents(is_superseded_by);
CREATE INDEX IF NOT EXISTS idx_documents_supersedes ON documents(supersedes);
CREATE INDEX IF NOT EXISTS idx_documents_sector ON documents(sector);

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
