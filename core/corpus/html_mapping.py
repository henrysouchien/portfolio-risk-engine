from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Sequence

from core.corpus.section_map import SectionRow, corpus_header_to_edgar_id


SIDECAR_SCHEMA_VERSION = "html_corpus_map.v1"
MAPPING_ALGORITHM_VERSION = "html-corpus-section-v1"
VISIBLE_TEXT_OFFSET_FRAME = "source_html_visible_text_v1"
CORPUS_OFFSET_FRAME = "corpus_doc"
MATERIALIZED_READER_VISIBLE_TEXT_ALGORITHM_VERSION = "sec-visible-text-v1"
MATERIALIZED_READER_SIDECAR_PREFIX = "materialized-source-html://"
_CONTEXT_CHARS = 160


class HtmlCorpusMappingError(ValueError):
    """Raised when a registry-backed HTML/corpus mapping is missing or invalid."""


@dataclass(frozen=True)
class MappingIngestResult:
    mapping_set_id: str
    record_count: int


def sidecar_path_for_canonical(canonical_path: Path) -> Path:
    return canonical_path.with_name(f"{canonical_path.stem}.html_corpus_map.v1.json")


def build_html_corpus_mapping_sidecar(
    *,
    finalized_text: str,
    metadata: Mapping[str, Any],
    sections: Sequence[SectionRow],
    sections_response: Mapping[str, Any] | None,
    canonical_path: Path,
    created_at: str | None = None,
) -> dict[str, Any] | None:
    if metadata.get("source") != "edgar" or not sections_response:
        return None

    source_html_hash = _first_string(
        sections_response,
        "source_html_hash",
        ("source_html", "hash"),
        ("reader_html", "source_html_hash"),
    )
    sanitizer_version = _first_string(
        sections_response,
        "sanitizer_version",
        ("source_html", "sanitizer_version"),
        ("reader_html", "sanitizer_version"),
    )
    visible_text_offset_frame = _first_string(
        sections_response,
        "visible_text_offset_frame",
        ("visible_text_stream", "offset_frame"),
        ("reader_html", "visible_text_offset_frame"),
    )
    visible_text_algorithm_version = _first_string(
        sections_response,
        "visible_text_algorithm_version",
        ("visible_text_stream", "algorithm_version"),
        ("reader_html", "visible_text_algorithm_version"),
    )
    parser_version = _optional_string(metadata.get("parser_version") or sections_response.get("parser_version"))
    parser_schema_version = _optional_int(
        metadata.get("parser_schema_version") or sections_response.get("parser_schema_version")
    )
    if (
        not source_html_hash
        or not sanitizer_version
        or visible_text_offset_frame != VISIBLE_TEXT_OFFSET_FRAME
        or not visible_text_algorithm_version
        or not parser_version
        or parser_schema_version is None
    ):
        return None

    document_id = _required_metadata(metadata, "document_id")
    accession = _required_metadata(metadata, "source_accession")
    primary_document_url = (
        _first_string(sections_response, "primary_document_url", ("filing", "primary_document_url"))
        or _required_metadata(metadata, "source_url_deep")
    )
    corpus_content_hash = _required_metadata(metadata, "content_hash")
    created = created_at or _now_iso()
    section_rows = {section.section: section for section in sections}
    records: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    response_sections = sections_response.get("sections") or {}

    if not isinstance(response_sections, Mapping):
        diagnostics.append("sections_response.sections is not an object")
        response_sections = {}

    for fallback_index, (section_id_raw, section_payload) in enumerate(response_sections.items()):
        if not isinstance(section_payload, Mapping):
            diagnostics.append(f"section {section_id_raw!r} is not an object")
            continue
        state = _optional_string(section_payload.get("state"))
        if state == "missing":
            continue
        quote = _clean_section_text(section_payload.get("text"))
        if not quote:
            continue
        header = _clean_header(section_payload.get("header"))
        section_row = section_rows.get(header)
        if section_row is None:
            diagnostics.append(f"section {section_id_raw!r} header {header!r} was not found in corpus sections")
            continue
        visible_range = _visible_text_range(section_payload)
        if visible_range is None:
            diagnostics.append(f"section {section_id_raw!r} has no producer visible-text range")
            continue
        if visible_range[1] - visible_range[0] != len(quote):
            diagnostics.append(f"section {section_id_raw!r} visible-text range does not match quote length")
            continue
        producer_trace = _producer_trace(section_payload)
        if producer_trace is None:
            diagnostics.append(f"section {section_id_raw!r} has no producer mapping trace")
            continue
        local_start = section_row.content.find(quote)
        if local_start < 0:
            diagnostics.append(f"section {section_id_raw!r} text was not found verbatim in corpus section")
            continue
        char_start = section_row.char_start + local_start
        char_end = char_start + len(quote)
        if finalized_text[char_start:char_end] != quote:
            diagnostics.append(f"section {section_id_raw!r} corpus offsets failed round-trip validation")
            continue

        section_id = str(section_id_raw or "").strip() or (
            corpus_header_to_edgar_id(header, str(metadata.get("form_type") or "")) or f"section_{fallback_index}"
        )
        text_before = finalized_text[max(0, char_start - _CONTEXT_CHARS):char_start] or None
        text_after = finalized_text[char_end:char_end + _CONTEXT_CHARS] or None
        producer_record_identity = {
            "document_id": document_id,
            "source_html_hash": source_html_hash,
            "corpus_content_hash": corpus_content_hash,
            "parser_version": parser_version,
            "parser_schema_version": parser_schema_version,
            "visible_text_algorithm_version": visible_text_algorithm_version,
            "mapping_algorithm_version": MAPPING_ALGORITHM_VERSION,
            "section_id": section_id,
            "normalized_visible_text": _normalize_text_for_hash(quote),
            "visible_text_span": list(visible_range),
            "corpus_span": [char_start, char_end],
        }
        records.append({
            "producer_record_id": f"producer_{_sha256_json(producer_record_identity)[:32]}",
            "section_id": section_id,
            "section_header": header,
            "content_type": "prose",
            "html_anchor": {
                "visible_text_anchor": {
                    "visible_text_offset_frame": VISIBLE_TEXT_OFFSET_FRAME,
                    "char_start": visible_range[0],
                    "char_end": visible_range[1],
                    "text_quote": quote,
                    "prefix_text": text_before,
                    "suffix_text": text_after,
                    "section_hint": header,
                },
                "dom_hint": None,
                "table_hint": None,
            },
            "corpus_span": {
                "offset_frame": CORPUS_OFFSET_FRAME,
                "char_start": char_start,
                "char_end": char_end,
            },
            "visible_text_span": {
                "offset_frame": VISIBLE_TEXT_OFFSET_FRAME,
                "char_start": visible_range[0],
                "char_end": visible_range[1],
            },
            "quote": quote,
            "text_before": text_before,
            "text_after": text_after,
            "confidence": "exact",
            "producer_trace": producer_trace,
            "diagnostics": [],
        })

    if not records:
        return None

    producer = {
        "pipeline": _optional_string(metadata.get("extraction_pipeline")),
        "deployment_id": _optional_string(metadata.get("producer_deployment_id")),
        "instance_id": _optional_string(metadata.get("producer_instance_id")),
        "build_id": _optional_string(metadata.get("producer_build_id")),
    }
    return {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "document_id": document_id,
        "accession": accession,
        "primary_document_url": primary_document_url,
        "source_html_hash": source_html_hash,
        "corpus_content_hash": corpus_content_hash,
        "sanitizer_version": sanitizer_version,
        "parser_version": parser_version,
        "parser_schema_version": parser_schema_version,
        "visible_text_offset_frame": VISIBLE_TEXT_OFFSET_FRAME,
        "visible_text_algorithm_version": visible_text_algorithm_version,
        "mapping_algorithm_version": MAPPING_ALGORITHM_VERSION,
        "created_at": created,
        "producer": producer,
        "sidecar_path": str(sidecar_path_for_canonical(canonical_path)),
        "records": records,
        "diagnostics": diagnostics,
    }


def write_mapping_sidecar(path: Path, sidecar: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(sidecar, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_text(body, encoding="utf-8")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def ingest_mapping_sidecar(
    db: sqlite3.Connection,
    *,
    sidecar: Mapping[str, Any],
    sidecar_path: Path,
    sidecar_hash: str,
) -> MappingIngestResult:
    _validate_sidecar_top_level(sidecar)
    mapping_set_id = mapping_set_id_for(sidecar)
    now = _optional_string(sidecar.get("created_at")) or _now_iso()

    db.execute(
        """
        UPDATE html_corpus_mapping_sets
        SET active = 0
        WHERE document_id = ?
          AND mapping_set_id <> ?
        """,
        (sidecar["document_id"], mapping_set_id),
    )
    db.execute(
        """
        INSERT INTO html_corpus_mapping_sets (
            mapping_set_id,
            document_id,
            accession,
            primary_document_url,
            source_html_hash,
            corpus_content_hash,
            sanitizer_version,
            parser_version,
            parser_schema_version,
            visible_text_algorithm_version,
            mapping_algorithm_version,
            sidecar_path,
            sidecar_hash,
            producer_json,
            provenance,
            active,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(mapping_set_id) DO UPDATE SET
            sidecar_path = excluded.sidecar_path,
            sidecar_hash = excluded.sidecar_hash,
            producer_json = excluded.producer_json,
            active = 1,
            created_at = excluded.created_at
        """,
        (
            mapping_set_id,
            sidecar["document_id"],
            sidecar["accession"],
            sidecar["primary_document_url"],
            sidecar["source_html_hash"],
            sidecar["corpus_content_hash"],
            sidecar["sanitizer_version"],
            sidecar.get("parser_version"),
            sidecar.get("parser_schema_version"),
            sidecar["visible_text_algorithm_version"],
            sidecar["mapping_algorithm_version"],
            str(sidecar_path),
            sidecar_hash,
            json.dumps(sidecar.get("producer") or {}, sort_keys=True, separators=(",", ":")),
            "producer",
            now,
        ),
    )
    db.execute("DELETE FROM html_corpus_mapping_records WHERE mapping_set_id = ?", (mapping_set_id,))

    record_count = 0
    for record in sidecar.get("records") or []:
        if not isinstance(record, Mapping):
            continue
        mapping_record_id = mapping_record_id_for(sidecar, record)
        corpus_span = _required_mapping(record.get("corpus_span"), "record.corpus_span")
        visible_text_span = _required_mapping(record.get("visible_text_span"), "record.visible_text_span")
        visible_span_offset_frame = _required_string(
            visible_text_span.get("offset_frame"),
            "record.visible_text_span.offset_frame",
        )
        if visible_span_offset_frame != VISIBLE_TEXT_OFFSET_FRAME:
            raise HtmlCorpusMappingError("record.visible_text_span.offset_frame is not supported")
        html_anchor = _required_mapping(record.get("html_anchor"), "record.html_anchor")
        visible_text_anchor = _required_mapping(
            html_anchor.get("visible_text_anchor"),
            "record.html_anchor.visible_text_anchor",
        )
        db.execute(
            """
            INSERT INTO html_corpus_mapping_records (
                mapping_record_id,
                mapping_set_id,
                producer_record_id,
                section_id,
                section_header,
                content_type,
                corpus_char_start,
                corpus_char_end,
                offset_frame,
                visible_text_offset_frame,
                visible_text_char_start,
                visible_text_char_end,
                quote,
                text_before,
                text_after,
                confidence,
                producer_trace_json,
                diagnostics_json,
                active,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                mapping_record_id,
                mapping_set_id,
                _required_string(record.get("producer_record_id"), "record.producer_record_id"),
                _required_string(record.get("section_id"), "record.section_id"),
                _required_string(record.get("section_header"), "record.section_header"),
                _required_string(record.get("content_type"), "record.content_type"),
                _required_int(corpus_span.get("char_start"), "record.corpus_span.char_start"),
                _required_int(corpus_span.get("char_end"), "record.corpus_span.char_end"),
                _required_string(corpus_span.get("offset_frame"), "record.corpus_span.offset_frame"),
                _required_string(
                    visible_text_anchor.get("visible_text_offset_frame"),
                    "record.visible_text_anchor.visible_text_offset_frame",
                ),
                _required_int(visible_text_span.get("char_start"), "record.visible_text_span.char_start"),
                _required_int(visible_text_span.get("char_end"), "record.visible_text_span.char_end"),
                _required_string(record.get("quote"), "record.quote"),
                _optional_string(record.get("text_before")),
                _optional_string(record.get("text_after")),
                _required_string(record.get("confidence"), "record.confidence"),
                json.dumps(
                    _required_mapping(record.get("producer_trace"), "record.producer_trace"),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(record.get("diagnostics") or [], sort_keys=True, separators=(",", ":")),
                now,
            ),
        )
        record_count += 1

    return MappingIngestResult(mapping_set_id=mapping_set_id, record_count=record_count)


def upsert_materialized_source_html_identity(
    db: sqlite3.Connection,
    *,
    identity: Mapping[str, Any],
    created_at: str | None = None,
) -> MappingIngestResult:
    """Persist a verified reader HTML identity even when no corpus spans exist yet.

    The source-html reader can prove the rendered filing identity before a producer
    has emitted an HTML/corpus sidecar. Table-cell evidence still needs this
    durable identity so exact table resolution can verify it is operating against
    the same SEC HTML the analyst selected from.
    """

    document_id = _required_string(_field(identity, "document_id", "documentId"), "identity.document_id")
    accession = _required_string(_field(identity, "accession", "accession"), "identity.accession")
    primary_document_url = _required_string(
        _field(identity, "primary_document_url", "primaryDocumentUrl"),
        "identity.primary_document_url",
    )
    source_html_hash = _required_string(
        _field(identity, "source_html_hash", "sourceHtmlHash"),
        "identity.source_html_hash",
    )
    corpus_content_hash = _required_string(
        _field(identity, "corpus_content_hash", "corpusContentHash"),
        "identity.corpus_content_hash",
    )
    sanitizer_version = _required_string(
        _field(identity, "sanitizer_version", "sanitizerVersion"),
        "identity.sanitizer_version",
    )
    row = db.execute(
        """
        SELECT parser_version, parser_schema_version
        FROM documents
        WHERE document_id = ?
          AND source_accession = ?
          AND source = 'edgar'
          AND is_superseded_by IS NULL
        LIMIT 1
        """,
        (document_id, accession),
    ).fetchone()
    if row is None:
        raise HtmlCorpusMappingError("materialized reader identity requires a local corpus document")

    parser_version = (
        _optional_string(_field(identity, "parser_version", "parserVersion"))
        or _optional_string(row["parser_version"])
    )
    parser_schema_version = _optional_int(
        _field(identity, "parser_schema_version", "parserSchemaVersion")
    )
    if parser_schema_version is None:
        parser_schema_version = _optional_int(row["parser_schema_version"])
    if parser_version is None:
        raise HtmlCorpusMappingError("materialized reader identity requires parser_version")
    if parser_schema_version is None:
        raise HtmlCorpusMappingError("materialized reader identity requires parser_schema_version")

    visible_text_algorithm_version = (
        _optional_string(_field(identity, "visible_text_algorithm_version", "visibleTextAlgorithmVersion"))
        or MATERIALIZED_READER_VISIBLE_TEXT_ALGORITHM_VERSION
    )
    mapping_algorithm_version = (
        _optional_string(_field(identity, "mapping_algorithm_version", "mappingAlgorithmVersion"))
        or MAPPING_ALGORITHM_VERSION
    )
    identity_sidecar = {
        "document_id": document_id,
        "accession": accession,
        "primary_document_url": primary_document_url,
        "source_html_hash": source_html_hash,
        "corpus_content_hash": corpus_content_hash,
        "sanitizer_version": sanitizer_version,
        "parser_version": parser_version,
        "parser_schema_version": parser_schema_version,
        "visible_text_algorithm_version": visible_text_algorithm_version,
        "mapping_algorithm_version": mapping_algorithm_version,
    }
    mapping_set_id = mapping_set_id_for(identity_sidecar)
    now = created_at or _now_iso()
    producer = {
        "pipeline": "risk_module.source_html_materializer",
        "identity_only": True,
        "visible_text_offset_frame": VISIBLE_TEXT_OFFSET_FRAME,
    }
    sidecar_path = f"{MATERIALIZED_READER_SIDECAR_PREFIX}{mapping_set_id}"
    sidecar_hash = _sha256_json({
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "identity": _mapping_set_identity(identity_sidecar),
        "producer": producer,
        "records": [],
    })
    producer_json = json.dumps(producer, sort_keys=True, separators=(",", ":"))

    with db:
        db.execute(
            """
            INSERT INTO html_corpus_mapping_sets (
                mapping_set_id,
                document_id,
                accession,
                primary_document_url,
                source_html_hash,
                corpus_content_hash,
                sanitizer_version,
                parser_version,
                parser_schema_version,
                visible_text_algorithm_version,
                mapping_algorithm_version,
                sidecar_path,
                sidecar_hash,
                producer_json,
                provenance,
                active,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'producer', 1, ?)
            ON CONFLICT(mapping_set_id) DO UPDATE SET
                sidecar_path = CASE
                    WHEN html_corpus_mapping_sets.sidecar_path LIKE ?
                    THEN excluded.sidecar_path
                    ELSE html_corpus_mapping_sets.sidecar_path
                END,
                sidecar_hash = CASE
                    WHEN html_corpus_mapping_sets.sidecar_path LIKE ?
                    THEN excluded.sidecar_hash
                    ELSE html_corpus_mapping_sets.sidecar_hash
                END,
                producer_json = CASE
                    WHEN html_corpus_mapping_sets.sidecar_path LIKE ?
                    THEN excluded.producer_json
                    ELSE html_corpus_mapping_sets.producer_json
                END,
                active = 1,
                created_at = CASE
                    WHEN html_corpus_mapping_sets.sidecar_path LIKE ?
                    THEN excluded.created_at
                    ELSE html_corpus_mapping_sets.created_at
                END
            """,
            (
                mapping_set_id,
                document_id,
                accession,
                primary_document_url,
                source_html_hash,
                corpus_content_hash,
                sanitizer_version,
                parser_version,
                parser_schema_version,
                visible_text_algorithm_version,
                mapping_algorithm_version,
                sidecar_path,
                sidecar_hash,
                producer_json,
                now,
                f"{MATERIALIZED_READER_SIDECAR_PREFIX}%",
                f"{MATERIALIZED_READER_SIDECAR_PREFIX}%",
                f"{MATERIALIZED_READER_SIDECAR_PREFIX}%",
                f"{MATERIALIZED_READER_SIDECAR_PREFIX}%",
            ),
        )

    return MappingIngestResult(mapping_set_id=mapping_set_id, record_count=0)


def mapping_set_id_for(sidecar: Mapping[str, Any]) -> str:
    return f"html_corpus_set_{_sha256_json(_mapping_set_identity(sidecar))[:24]}"


def mapping_record_id_for(sidecar: Mapping[str, Any], record: Mapping[str, Any]) -> str:
    return f"html_corpus_map_{_sha256_json({
        **_mapping_set_identity(sidecar),
        'producer_record_id': record.get('producer_record_id'),
    })[:32]}"


def validate_mapping_anchor(db: sqlite3.Connection, anchor: Mapping[str, Any]) -> dict[str, Any]:
    mapping_record_id = _required_string(_field(anchor, "mapping_record_id", "mappingRecordId"), "anchor.mapping_record_id")
    row = db.execute(
        """
        SELECT
            records.mapping_record_id,
            records.corpus_char_start,
            records.corpus_char_end,
            records.quote,
            records.confidence,
            records.content_type,
            sets.document_id,
            sets.accession,
            sets.primary_document_url,
            sets.source_html_hash,
            sets.corpus_content_hash,
            sets.sanitizer_version,
            sets.parser_version,
            sets.parser_schema_version,
            sets.visible_text_algorithm_version,
            sets.mapping_algorithm_version
        FROM html_corpus_mapping_records AS records
        JOIN html_corpus_mapping_sets AS sets
          ON sets.mapping_set_id = records.mapping_set_id
        WHERE records.mapping_record_id = ?
          AND records.active = 1
          AND sets.active = 1
        """,
        (mapping_record_id,),
    ).fetchone()
    if row is None:
        raise HtmlCorpusMappingError("mapped reader artifacts require an authoritative mapping registry")

    expected_identity = {
        "document_id": row["document_id"],
        "accession": row["accession"],
        "primary_document_url": row["primary_document_url"],
        "source_html_hash": row["source_html_hash"],
        "corpus_content_hash": row["corpus_content_hash"],
        "sanitizer_version": row["sanitizer_version"],
        "parser_version": row["parser_version"],
        "parser_schema_version": row["parser_schema_version"],
        "visible_text_algorithm_version": row["visible_text_algorithm_version"],
        "mapping_algorithm_version": row["mapping_algorithm_version"],
    }
    for field, expected in expected_identity.items():
        actual = _field(anchor, field, _camel_case(field))
        if str(actual or "").strip() != str(expected or "").strip():
            raise HtmlCorpusMappingError(f"anchor.{field} does not match mapping registry")

    char_start = _required_int(_field(anchor, "char_start", "charStart"), "anchor.char_start")
    char_end = _required_int(_field(anchor, "char_end", "charEnd"), "anchor.char_end")
    if char_start < int(row["corpus_char_start"]) or char_end > int(row["corpus_char_end"]) or char_end <= char_start:
        raise HtmlCorpusMappingError("anchor corpus offsets are outside the mapping record span")

    local_start = char_start - int(row["corpus_char_start"])
    local_end = char_end - int(row["corpus_char_start"])
    selected_text = _required_string(_field(anchor, "selected_text", "selectedText"), "anchor.selected_text")
    mapped_text = str(row["quote"])[local_start:local_end]
    if _normalize_text_for_hash(mapped_text) != _normalize_text_for_hash(selected_text):
        raise HtmlCorpusMappingError("anchor selected_text does not match mapping registry span")

    requested_confidence = _required_string(anchor.get("confidence"), "anchor.confidence")
    if _confidence_rank(str(row["confidence"])) < _confidence_rank(requested_confidence):
        raise HtmlCorpusMappingError("anchor confidence exceeds mapping registry confidence")
    if str(row["content_type"]) == "table":
        raise HtmlCorpusMappingError("table mappings require table-cell provenance before exact citation")
    return dict(row)


def resolve_visible_mapping_anchor(db: sqlite3.Connection, request: Mapping[str, Any]) -> dict[str, Any]:
    selected_text = _required_string(
        _field(request, "selected_text", "selectedText"),
        "selected_text",
    )
    source_id = _required_string(_field(request, "source_id", "sourceId"), "source_id")
    visible_text_anchor = _required_mapping(
        _field(request, "visible_text_anchor", "visibleTextAnchor"),
        "visible_text_anchor",
    )
    visible_anchor_text = _required_string(
        _field(visible_text_anchor, "text_quote", "textQuote"),
        "visible_text_anchor.text_quote",
    )
    if visible_anchor_text != selected_text:
        raise HtmlCorpusMappingError("visible_text_anchor.text_quote must match selected_text")
    visible_anchor_frame = _required_string(
        _field(visible_text_anchor, "visible_text_offset_frame", "visibleTextOffsetFrame"),
        "visible_text_anchor.visible_text_offset_frame",
    )
    if visible_anchor_frame != VISIBLE_TEXT_OFFSET_FRAME:
        raise HtmlCorpusMappingError("visible_text_anchor.visible_text_offset_frame is not supported")
    html_anchor = _optional_mapping(_field(request, "html_anchor", "htmlAnchor")) or {
        "anchor_version": "html-quote-v1",
        "text_quote": selected_text,
        "prefix_text": _field(visible_text_anchor, "prefix_text", "prefixText"),
        "suffix_text": _field(visible_text_anchor, "suffix_text", "suffixText"),
        "section_hint": _field(visible_text_anchor, "section_hint", "sectionHint"),
    }
    identity = _resolve_identity(request)
    candidates = db.execute(
        """
        SELECT
            records.mapping_record_id,
            records.corpus_char_start,
            records.corpus_char_end,
            records.visible_text_char_start,
            records.visible_text_char_end,
            records.quote,
            records.confidence,
            records.content_type,
            records.section_header,
            records.offset_frame,
            records.visible_text_offset_frame,
            sets.document_id,
            sets.accession,
            sets.primary_document_url,
            sets.source_html_hash,
            sets.corpus_content_hash,
            sets.sanitizer_version,
            sets.parser_version,
            sets.parser_schema_version,
            sets.visible_text_algorithm_version,
            sets.mapping_algorithm_version
        FROM html_corpus_mapping_records AS records
        JOIN html_corpus_mapping_sets AS sets
          ON sets.mapping_set_id = records.mapping_set_id
        WHERE sets.document_id = ?
          AND sets.accession = ?
          AND sets.primary_document_url = ?
          AND sets.source_html_hash = ?
          AND sets.corpus_content_hash = ?
          AND sets.sanitizer_version = ?
          AND sets.parser_version = ?
          AND sets.parser_schema_version = ?
          AND sets.visible_text_algorithm_version = ?
          AND sets.mapping_algorithm_version = ?
          AND sets.active = 1
          AND records.active = 1
          AND records.content_type <> 'table'
          AND records.confidence IN ('exact', 'high')
        """,
        (
            identity["document_id"],
            identity["accession"],
            identity["primary_document_url"],
            identity["source_html_hash"],
            identity["corpus_content_hash"],
            identity["sanitizer_version"],
            identity["parser_version"],
            identity["parser_schema_version"],
            identity["visible_text_algorithm_version"],
            identity["mapping_algorithm_version"],
        ),
    ).fetchall()
    matches: list[dict[str, Any]] = []
    for row in candidates:
        local_start = str(row["quote"]).find(selected_text)
        if local_start < 0:
            continue
        if str(row["quote"]).find(selected_text, local_start + 1) >= 0:
            continue
        char_start = int(row["corpus_char_start"]) + local_start
        char_end = char_start + len(selected_text)
        visible_text_char_start = int(row["visible_text_char_start"]) + local_start
        visible_text_char_end = visible_text_char_start + len(selected_text)
        if not _visible_anchor_matches_record(
            visible_text_anchor,
            row,
            selected_text=selected_text,
            local_start=local_start,
            visible_text_char_start=visible_text_char_start,
            visible_text_char_end=visible_text_char_end,
        ):
            continue
        resolved_visible_anchor = {
            **dict(visible_text_anchor),
            "visible_text_offset_frame": VISIBLE_TEXT_OFFSET_FRAME,
            "text_quote": selected_text,
            "section_hint": row["section_header"],
        }
        resolved_visible_anchor.pop("char_start", None)
        resolved_visible_anchor.pop("char_end", None)
        resolved_visible_anchor.pop("charStart", None)
        resolved_visible_anchor.pop("charEnd", None)
        matches.append({
            "anchor_schema_version": "v2",
            "anchor_kind": "filing_mapped",
            "surface": "filing_html",
            "source_type": "filing",
            "source_id": source_id,
            "selected_text": selected_text,
            "html_anchor": dict(html_anchor),
            "visible_text_anchor": resolved_visible_anchor,
            "confidence": row["confidence"],
            "mapping_record_id": row["mapping_record_id"],
            "char_start": char_start,
            "char_end": char_end,
            "offset_frame": row["offset_frame"],
            "visible_text_offset_frame": row["visible_text_offset_frame"],
            "section_header": row["section_header"],
            **identity,
        })

    if not matches:
        raise HtmlCorpusMappingError("no active mapping record matched the visible selection")
    if len(matches) > 1:
        raise HtmlCorpusMappingError("visible selection matched multiple mapping records")
    return matches[0]


def _validate_sidecar_top_level(sidecar: Mapping[str, Any]) -> None:
    if sidecar.get("schema_version") != SIDECAR_SCHEMA_VERSION:
        raise HtmlCorpusMappingError("mapping sidecar schema_version is not supported")
    for field in (
        "document_id",
        "accession",
        "primary_document_url",
        "source_html_hash",
        "corpus_content_hash",
        "sanitizer_version",
        "parser_version",
        "visible_text_algorithm_version",
        "mapping_algorithm_version",
    ):
        _required_string(sidecar.get(field), f"sidecar.{field}")
    _required_int(sidecar.get("parser_schema_version"), "sidecar.parser_schema_version")
    if sidecar.get("visible_text_offset_frame") != VISIBLE_TEXT_OFFSET_FRAME:
        raise HtmlCorpusMappingError("mapping sidecar visible_text_offset_frame is not supported")
    records = sidecar.get("records")
    if not isinstance(records, list) or not records:
        raise HtmlCorpusMappingError("mapping sidecar records must be a non-empty array")


def _mapping_set_identity(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "document_id": sidecar.get("document_id"),
        "accession": sidecar.get("accession"),
        "primary_document_url": sidecar.get("primary_document_url"),
        "source_html_hash": sidecar.get("source_html_hash"),
        "corpus_content_hash": sidecar.get("corpus_content_hash"),
        "sanitizer_version": sidecar.get("sanitizer_version"),
        "parser_version": sidecar.get("parser_version"),
        "parser_schema_version": sidecar.get("parser_schema_version"),
        "visible_text_algorithm_version": sidecar.get("visible_text_algorithm_version"),
        "mapping_algorithm_version": sidecar.get("mapping_algorithm_version"),
    }


def _resolve_identity(request: Mapping[str, Any]) -> dict[str, Any]:
    parser_schema_version = _required_int(
        _field(request, "parser_schema_version", "parserSchemaVersion"),
        "parser_schema_version",
    )
    return {
        "document_id": _required_string(_field(request, "document_id", "documentId"), "document_id"),
        "accession": _required_string(_field(request, "accession", "accession"), "accession"),
        "primary_document_url": _required_string(
            _field(request, "primary_document_url", "primaryDocumentUrl"),
            "primary_document_url",
        ),
        "source_html_hash": _required_string(
            _field(request, "source_html_hash", "sourceHtmlHash"),
            "source_html_hash",
        ),
        "corpus_content_hash": _required_string(
            _field(request, "corpus_content_hash", "corpusContentHash"),
            "corpus_content_hash",
        ),
        "sanitizer_version": _required_string(
            _field(request, "sanitizer_version", "sanitizerVersion"),
            "sanitizer_version",
        ),
        "parser_version": _required_string(
            _field(request, "parser_version", "parserVersion"),
            "parser_version",
        ),
        "parser_schema_version": parser_schema_version,
        "visible_text_algorithm_version": _required_string(
            _field(request, "visible_text_algorithm_version", "visibleTextAlgorithmVersion"),
            "visible_text_algorithm_version",
        ),
        "mapping_algorithm_version": _optional_string(
            _field(request, "mapping_algorithm_version", "mappingAlgorithmVersion")
        )
        or MAPPING_ALGORITHM_VERSION,
    }


def _visible_anchor_matches_record(
    visible_text_anchor: Mapping[str, Any],
    row: sqlite3.Row,
    *,
    selected_text: str,
    local_start: int,
    visible_text_char_start: int,
    visible_text_char_end: int,
) -> bool:
    anchor_start = _optional_int(_field(visible_text_anchor, "char_start", "charStart"))
    anchor_end = _optional_int(_field(visible_text_anchor, "char_end", "charEnd"))
    if anchor_start is not None or anchor_end is not None:
        if anchor_start != visible_text_char_start or anchor_end != visible_text_char_end:
            return False

    section_hint = _optional_string(_field(visible_text_anchor, "section_hint", "sectionHint"))
    if section_hint is not None and section_hint != str(row["section_header"]):
        return False

    quote = str(row["quote"])
    prefix_text = _optional_string(_field(visible_text_anchor, "prefix_text", "prefixText"))
    if prefix_text is not None and not quote[:local_start].endswith(prefix_text):
        return False

    suffix_text = _optional_string(_field(visible_text_anchor, "suffix_text", "suffixText"))
    local_end = local_start + len(selected_text)
    if suffix_text is not None and not quote[local_end:].startswith(suffix_text):
        return False

    if anchor_start is None and anchor_end is None and section_hint is None and prefix_text is None and suffix_text is None:
        return False
    return True


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _first_string(source: Mapping[str, Any], *paths: str | tuple[str, str]) -> str | None:
    for path in paths:
        if isinstance(path, str):
            value = source.get(path)
        else:
            parent = source.get(path[0])
            value = parent.get(path[1]) if isinstance(parent, Mapping) else None
        text = _optional_string(value)
        if text is not None:
            return text
    return None


def _required_metadata(metadata: Mapping[str, Any], field: str) -> str:
    return _required_string(metadata.get(field), f"metadata.{field}")


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HtmlCorpusMappingError(f"{field} must be an object")
    return value


def _required_string(value: Any, field: str) -> str:
    text = _optional_string(value)
    if text is None:
        raise HtmlCorpusMappingError(f"{field} is required")
    return text


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_int(value: Any, field: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise HtmlCorpusMappingError(f"{field} must be an integer") from exc
    return normalized


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip() or "Unknown Section"


def _clean_section_text(value: Any) -> str:
    return str(value or "").strip()


def _visible_text_range(section_payload: Mapping[str, Any]) -> tuple[int, int] | None:
    value = section_payload.get("visible_text_range") or section_payload.get("visible_text_span")
    if not isinstance(value, Mapping):
        return None
    offset_frame = _optional_string(value.get("offset_frame") or value.get("visible_text_offset_frame"))
    if offset_frame != VISIBLE_TEXT_OFFSET_FRAME:
        return None
    try:
        char_start = _required_int(value.get("char_start"), "section.visible_text_range.char_start")
        char_end = _required_int(value.get("char_end"), "section.visible_text_range.char_end")
    except HtmlCorpusMappingError:
        return None
    if char_start < 0 or char_end <= char_start:
        return None
    return (char_start, char_end)


def _producer_trace(section_payload: Mapping[str, Any]) -> dict[str, Any] | None:
    trace = section_payload.get("mapping_trace") or section_payload.get("parser_trace")
    if isinstance(trace, Mapping) and trace:
        return dict(trace)
    trace_id = _optional_string(section_payload.get("mapping_trace_id") or section_payload.get("parser_trace_id"))
    if trace_id is not None:
        return {"trace_id": trace_id}
    return None


def _normalize_text_for_hash(value: str) -> str:
    return value.replace("\u00a0", " ").strip().lower()


def _confidence_rank(value: str) -> int:
    return {
        "none": 0,
        "section_only": 1,
        "quote": 2,
        "high": 3,
        "exact": 4,
    }.get(value, -1)


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _field(record: Mapping[str, Any], snake_key: str, camel_key: str) -> Any:
    return record.get(snake_key) if snake_key in record else record.get(camel_key)


__all__ = [
    "CORPUS_OFFSET_FRAME",
    "HtmlCorpusMappingError",
    "MAPPING_ALGORITHM_VERSION",
    "MATERIALIZED_READER_VISIBLE_TEXT_ALGORITHM_VERSION",
    "MappingIngestResult",
    "SIDECAR_SCHEMA_VERSION",
    "VISIBLE_TEXT_OFFSET_FRAME",
    "build_html_corpus_mapping_sidecar",
    "ingest_mapping_sidecar",
    "mapping_record_id_for",
    "mapping_set_id_for",
    "resolve_visible_mapping_anchor",
    "sidecar_path_for_canonical",
    "upsert_materialized_source_html_identity",
    "validate_mapping_anchor",
    "write_mapping_sidecar",
]
