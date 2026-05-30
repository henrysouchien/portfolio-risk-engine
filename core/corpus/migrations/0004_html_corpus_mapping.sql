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
