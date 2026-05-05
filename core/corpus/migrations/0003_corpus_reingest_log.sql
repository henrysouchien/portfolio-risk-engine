CREATE TABLE corpus_reingest_log (
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
CREATE INDEX idx_reingest_invalidation ON corpus_reingest_log(invalidation_id);
CREATE INDEX idx_reingest_document ON corpus_reingest_log(document_id, started_at);
CREATE INDEX idx_reingest_active ON corpus_reingest_log(status)
    WHERE status NOT IN ('complete', 'no_change', 'abandoned');
