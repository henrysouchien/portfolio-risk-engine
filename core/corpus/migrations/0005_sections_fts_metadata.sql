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
