# Research Workspace — Phase 2 Implementation Plan: Document Reading + Annotation

**Status:** DRAFT — Codex reviewed (5 rounds R1-R5 + cross-doc sync). Hook naming fix applied.
**Date:** 2026-04-13 (R1 fixes: 2026-04-11, R2 fixes: 2026-04-11, R3 fixes: 2026-04-11, R4 fixes: 2026-04-11, R5 fixes: 2026-04-11)
**Anchor:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md` (the locked system frame)
**Decisions:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` (the 7 locked decisions)
**Phase 1:** `docs/planning/RESEARCH_WORKSPACE_PHASE1_PLAN_V5.md` (in progress; Phase 2 builds on it)
**Product spec:** `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md` (design/interaction model sections authoritative)

**Primary architecture reference:** Architecture doc Section 5 Flow 4 (open document tab), Section 3 (annotations table stub), Section 7 Invariants 6-7 (filing immutability, char offsets).
**Primary decisions reference:** Decision 6 (citation precision: char offsets, no para_id), Decision 7 (3 new langextract schemas).

---

## Review History

### R1 — Codex Review (2026-04-11)

**4 findings, 4 fixes applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | Transcript support not end-to-end — API surface uses `filing_id` + `parse_filing_sections()` but transcript rendering expects speaker-segmented data. No parser contract for transcript markdown to prepared-remarks/Q&A with stable char spans. | Added `parse_transcript_sections()` contract to DocumentService (Step 1). Extended `GET /documents` with `source_type` parameter to handle both filings and transcripts. Defined transcript markdown format (`## PREPARED REMARKS` / `## Q&A SESSION` section markers, `### SPEAKER: {name} ({role})` sub-sections). Returns `{speaker, role, text, char_start, char_end, section}` segments. Added 2 tests. |
| 2 | High | Document-context contract contradictory — plan said both `tab_context` (integer) and `metadata.document_context` (JSON). Phase 1 runtime only persists `tab_context` pre-turn as an integer thread_id, not arbitrary metadata. | Committed to `metadata.document_context` as sole mechanism for document tab context. `tab_context` stays as panel thread_id (integer, unchanged from Phase 1). Added concrete Step 8 backend change: `save_message` call extended to include `metadata` from request payload; `build_research_context()` reads `document_context` from last user message metadata. Cleaned up all contradictory references. |
| 3 | Medium | Decision 6 paragraph split not fully implemented — helper only did CRLF + blank-line split, missing bullet/list/caption handling. Paragraph numbering was document-absolute, not section-relative. | Rewrote `computeParagraphNumber` to take `sectionText` + `charStartWithinSection` (section-relative). Full split rule: CRLF normalization, `\n\n+` split, bullet/numbered list run coalescence (`^\s*[-*\u2022]\s` or `^\s*\d+[.)]\s` consecutive lines as one paragraph), figure/table caption line coalescence. Added 3 targeted tests. |
| 4 | Medium | "Open in reader" missing ingest endpoint — no API path from agent message `source_path` to content-hashed `filing_id`. | Added `POST /api/research/content/documents/ingest` endpoint wrapping `DocumentService.ingest_filing()`. Updated Step 9 to show two-step flow (ingest to get filing_id, then GET /documents to load content). Added 1 test. |

---

## What Phase 2 Delivers

- **Document tabs in the reader** — filing sections rendered as prose with section selector (via `parse_filing_sections()`), earnings transcripts rendered with speaker labels and prepared remarks / Q&A structure (via `parse_transcript_sections()` on the immutable transcript markdown).
- **Agent document highlights** — langextract extractions rendered as colored overlays on raw section text. `--accent-dim` background with annotation note.
- **User text selection + annotation** — char offset-based, stored in the `annotations` table (already stubbed in Phase 1 schema). `--surface-2` background with `--text-dim` left rail.
- **"Ask about this"** — text selection in a document tab prefills the agent panel input with a source citation and question context; sends via Flow 3 with annotation reference in metadata.
- **3 new langextract schemas** — `management_commentary`, `competitive_positioning`, `segment_discussion` (Decision 7, locked). Added to `AI-excel-addin/mcp_servers/langextract_mcp/schemas.py`.
- **Filing content-hash versioning** — filing output naming convention changes to `VALE_10K_2024_a3f8b2c1` (8-char content hash suffix from file content). Same content bytes produce the same SHA hash and therefore the same filing_id (idempotent). Different normalization of the same SEC filing produces different content bytes, a different hash, and a different filing_id. Both old and new versions coexist. The filing_id includes a content hash, so identical content always produces the identical filing_id. Old annotations continue pointing at their original filing version. Filings stored in shared `data/filings/` directory (immutable, safe to share across users).
- **Deterministic paragraph split rule** for citation display (Decision 6) — paragraph numbers computed lazily at render time from immutable filing text, never persisted.
- **5 new REST endpoints** — `GET /documents`, `POST /documents/ingest`, `GET /extractions`, `GET /annotations`, `POST /annotations` (architecture doc Section 4).
- **DocumentService** — stateless read service at `api/research/document_service.py` (architecture doc Section 2).

## What is NOT in Phase 2

- Diligence checklist (9 core sections + qualitative factors) — Phase 3
- Research handoff artifact assembly — Phase 4
- `annotate_model_with_research()` MCP tool — Phase 4
- Report generation / export — Phase 4/5
- Web search integration — Phase 5
- Multi-ticker theme research — Phase 5
- Financial statement tabs (tabular data rendering) — deferred within Phase 2; start with prose filings + transcripts
- Semantic search across filings (chunks + embeddings ingestion) — Phase 3+ if needed
- Investor deck document type — deferred; `source_type='investor_deck'` in annotation schema is future-proofing
- Per-thread gateway sessions for conversation isolation — deferred unless Phase 1 reveals bleed
- Run-to-completion persistence for disconnect resilience — deferred

---

## Investigation Findings (Compressed)

### 1. Langextract Pipeline

**Path:** `AI-excel-addin/mcp_servers/langextract_mcp/`

**Flow:** Raw filing markdown (from edgar-mcp `get_filing_sections()` with `output="file"`) lands on disk at `~/.cache/edgar-mcp/file_output/` (or `EDGAR_MCP_OUTPUT_DIR`). The markdown contains `## SECTION: {header}` markers. `text_utils.py:parse_filing_sections()` returns `SectionMap: dict[str, tuple[str, int, int]]` — section header to (text, start_offset, end_offset). Offsets are exact character positions in the original file.

`strip_table_blocks()` whitespace-fills pipe tables and markdown separators **without** changing text length, preserving char offsets. This is validated by a length assertion.

`extract_filing_file()` calls langextract's `lx_extract()` with schema-specific prompt descriptions, then `_normalize_extractions()` validates every extraction by checking `original_text[char_start:char_end] == extraction_text`. Only grounded (text-verified) extractions are returned.

**Output:** Each extraction is `{class, text, attributes, char_start, char_end, grounded: true}`. These char offsets are relative to the full original file text, making them directly usable as annotation overlays.

**4 existing schemas:** `risk_factors`, `forward_guidance`, `capital_allocation`, `liquidity_leverage`. Each is an `ExtractionSchema` dataclass with `name`, `prompt_description`, `valid_classes`, `recommended_sections`, and `examples`.

### 2. Filing Retrieval (edgar-mcp)

`get_filing_sections()` calls the remote EDGAR API at `/api/sections`, writes full markdown to disk at `FILE_OUTPUT_DIR / filename`. Current naming convention: `{TICKER}_{QUARTER}Q{YY}_sections.md`. No content hash today.

**What needs to change for content-hash versioning:**
- After writing the file, compute an 8-char SHA hash of the file content.
- Copy to `data/filings/{TICKER}_{FILING_TYPE}_{YEAR}_{hash}.md`.
- The `DocumentService` resolves `filing_id` to this path.
- Re-ingesting the same filing with different normalization produces a new hash and a new file.

### 3. Transcript Retrieval (fmp-mcp)

`get_earnings_transcript()` returns structured parsed data: `prepared_remarks` (list of `{speaker, role, text, word_count}`), `qa` (same shape), `qa_exchanges` (grouped), and `metadata`.

**FLAG: Transcripts do NOT have `char_start`/`char_end` per speaker segment.** The Inv-B finding in the decisions doc is incorrect. The parser produces `line_index` on raw segments but the final output only has `speaker`, `role`, `text`, `word_count`.

**Resolution:** Write transcripts as content-hashed markdown files (same convention as filings) using `## PREPARED REMARKS` / `## Q&A SESSION` section markers and `### SPEAKER: {name} ({role})` sub-sections. `parse_transcript_sections()` on DocumentService round-trips this format back to structured `{speaker, role, text, char_start, char_end, section}` segments. `GET /documents?source_id=...&source_type=transcript` returns both section map and speaker segments. Keeps the annotation schema unified.

### 4. Existing Document Rendering Patterns

No existing document/prose rendering components in the frontend. DESIGN.md Document Reading Mode spec:
- Filing prose: 14-15px Instrument Sans, `--ink`, max-width 640px
- Transcript: speaker labels in Geist Mono 10px uppercase, dialogue in 14px Instrument Sans
- Agent highlights: `--accent-dim` background + annotation note in `--accent`
- User highlights: `--surface-2` background + annotation with `--text-dim` left rail

### 5. Annotation Storage

The `annotations` table is already stubbed in Phase 1's schema. Phase 2 REST endpoints (from architecture doc Section 4, extended in R1):
- `GET /api/research/content/documents?source_id=...&source_type=filing|transcript`
- `POST /api/research/content/documents/ingest` — accepts `{source_path}`, returns `{filing_id}`
- `GET /api/research/content/extractions?filing_id=...&section=...&schemas=...`
- `GET /api/research/content/annotations?research_file_id=...`
- `POST /api/research/content/annotations`

### 6. Text Selection in React

Use the browser `Selection` API (`window.getSelection()`). Render filing text as paragraphs with known char offsets via `data-char-start` attributes. On `mouseup`, compute `char_start` and `char_end` by walking from the selection anchor/focus nodes to the container root and summing character lengths. For overlaying highlights, split text runs at highlight boundaries and stack background colors. No external library needed.

---

## Invariants Phase 2 Must Uphold

| Invariant | Enforcement in Phase 2 |
|---|---|
| 1 — Per-user isolation is physical | Filing cache is shared (public SEC docs, immutable); annotations are per-user in `research.db` scoped by `research_file_id` |
| 6 — Filing text is immutable once ingested | Content-hash naming in `data/filings/`. Same content bytes → same SHA hash → same filing_id (idempotent). Different normalization → different hash → different filing_id. |
| 7 — Char offsets are the stable annotation reference | Annotation schema uses `char_start`/`char_end`. No `para_id` column. Paragraph numbers computed at render time |
| 12 — Connection-per-request for SQLite | `ResearchRepository` pattern unchanged |
| 15 — Content scoped by research_file_id | `annotations.research_file_id` FK. Same filing passage annotated under two theses creates two distinct rows |
| 3, 4 — User_id proxy-injected + tier gating | New endpoints go through same `research_content.py` proxy |

---

## Step 1 — Filing Content-Hash Versioning + DocumentService

**Owner:** ai-excel-addin
**New file:** `api/research/document_service.py`

The `DocumentService` handles filing ingest (hash + copy to `data/filings/`), section parsing, and extraction orchestration.

```python
class DocumentService:
    """Stateless filing + extraction read service."""

    def __init__(self, filings_dir: Path):
        self._filings_dir = filings_dir

    def ingest_filing(self, source_path: str) -> str:
        """Read a filing markdown, compute content hash, copy to filings dir.
        Returns the filing_id (content-hashed filename without extension).
        Idempotent: if file with same hash exists, returns existing filing_id."""
        content = Path(source_path).read_text(encoding="utf-8")
        hash8 = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
        ticker, filing_type, year = _parse_filing_header(content)
        filing_id = f"{ticker}_{filing_type}_{year}_{hash8}"
        dest = self._filings_dir / f"{filing_id}.md"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        return filing_id

    def get_document(self, source_id: str,
                     source_type: str = "filing") -> dict:
        """Load a filing or transcript, parse sections, return section map.

        Args:
            source_id: content-hashed identifier (filing_id or transcript source_id)
            source_type: "filing" or "transcript"
        """
        path = self._filings_dir / f"{source_id}.md"
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {source_id}")
        text = path.read_text(encoding="utf-8")

        if source_type == "transcript":
            segments = self.parse_transcript_sections(text)
            # Build section map from transcript structure
            sections = {}
            for section_key in ("prepared_remarks", "qa"):
                section_segs = [s for s in segments if s["section"] == section_key]
                if section_segs:
                    start = section_segs[0]["char_start"]
                    end = section_segs[-1]["char_end"]
                    sections[section_key] = {
                        "text": text[start:end],
                        "start": start,
                        "end": end,
                    }
            return {
                "source_id": source_id,
                "source_type": "transcript",
                "full_text": text,
                "sections": sections,
                "available_sections": list(sections.keys()),
                "segments": segments,
            }
        else:
            sections = parse_filing_sections(text)
            return {
                "source_id": source_id,
                "source_type": "filing",
                "full_text": text,
                "sections": {
                    header: {"text": sec_text, "start": start, "end": end}
                    for header, (sec_text, start, end) in sections.items()
                },
                "available_sections": list(sections.keys()),
            }

    @staticmethod
    def parse_transcript_sections(text: str) -> list[dict]:
        """Parse immutable transcript markdown into speaker-segmented data.

        Transcript markdown format:
          ## PREPARED REMARKS
          ### SPEAKER: John Smith (CEO)
          <speaker text>
          ## Q&A SESSION
          ### SPEAKER: Jane Doe (Analyst, Goldman Sachs)
          <speaker text>

        Returns a list of segments, each:
          {speaker, role, text, char_start, char_end, section: "prepared_remarks"|"qa"}
        where char_start/char_end are offsets into the full transcript text.
        """
        import re

        segments = []
        current_section = None
        section_map = {
            "PREPARED REMARKS": "prepared_remarks",
            "Q&A SESSION": "qa",
        }

        # Find all ## and ### headers with their positions
        header_pattern = re.compile(
            r'^(#{2,3})\s+(.+)$', re.MULTILINE
        )
        headers = list(header_pattern.finditer(text))

        for i, match in enumerate(headers):
            level = len(match.group(1))
            title = match.group(2).strip()

            if level == 2:
                current_section = section_map.get(title)
                continue

            if level == 3 and current_section:
                speaker_match = re.match(
                    r'SPEAKER:\s*(.+?)\s*\((.+?)\)', title
                )
                if not speaker_match:
                    continue

                speaker = speaker_match.group(1).strip()
                role = speaker_match.group(2).strip()

                # Text starts after the header line
                text_start = match.end() + 1  # skip newline after header
                # Text ends at next header or end of file
                if i + 1 < len(headers):
                    text_end = headers[i + 1].start() - 1
                else:
                    text_end = len(text)

                segment_text = text[text_start:text_end].strip()
                segments.append({
                    "speaker": speaker,
                    "role": role,
                    "text": segment_text,
                    "char_start": text_start,
                    "char_end": text_end,
                    "section": current_section,
                })

        return segments

    def get_extractions(self, filing_id: str, section: str,
                        schemas: list[str]) -> dict:
        """Run langextract on a specific section with given schemas."""
        path = self._filings_dir / f"{filing_id}.md"
        results = {}
        for schema_name in schemas:
            result = extract_filing_file(
                file_path=str(path), schema_name=schema_name,
                sections_filter=[section],
            )
            results[schema_name] = result.get("extractions", [])
        return {"filing_id": filing_id, "section": section,
                "extractions_by_schema": results}

    def ingest_transcript(self, symbol: str, year: int, quarter: int,
                          parsed_transcript: dict) -> str:
        """Write parsed transcript as immutable markdown, return source_id.

        Renders transcript into the canonical markdown format that
        parse_transcript_sections() can round-trip:

          ## PREPARED REMARKS
          ### SPEAKER: {name} ({role})
          {text}
          ## Q&A SESSION
          ### SPEAKER: {name} ({role})
          {text}

        This format is the contract between ingest and rendering.
        """
        md_content = _render_transcript_markdown(symbol, year, quarter, parsed_transcript)
        hash8 = hashlib.sha256(md_content.encode("utf-8")).hexdigest()[:8]
        source_id = f"{symbol}_{quarter}Q{year % 100:02d}_transcript_{hash8}"
        dest = self._filings_dir / f"{source_id}.md"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(md_content, encoding="utf-8")
        return source_id
```

**Tests (8):**
- `test_ingest_filing_content_hash` — same content → same filing_id; different content → different
- `test_ingest_filing_idempotent` — calling ingest twice does not overwrite
- `test_get_document_sections` — ingested filing returns correct section_map with offsets
- `test_get_document_not_found` — non-existent filing_id raises FileNotFoundError
- `test_ingest_transcript_content_hash` — transcript produces stable source_id
- `test_get_extractions_delegates` — calls langextract and returns grounded extractions per schema
- `test_parse_transcript_sections_prepared_remarks_and_qa` — round-trip: ingest transcript markdown, call `parse_transcript_sections()`, verify segments have correct `speaker`, `role`, `section` ("prepared_remarks" or "qa"), and that `text[char_start:char_end]` matches the segment text
- `test_get_document_transcript_type` — `get_document(source_id, source_type="transcript")` returns `segments` list with speaker data and `sections` keyed by "prepared_remarks"/"qa" with correct char offsets

---

## Step 2 — 3 New Langextract Schemas

**Owner:** ai-excel-addin
**Extended file:** `AI-excel-addin/mcp_servers/langextract_mcp/schemas.py`

Add 3 new `ExtractionSchema` entries following the existing pattern (~100-200 lines each).

**`management_commentary`:**
- Feeds qualitative factors: `management_team`, `management_quality`
- `valid_classes`: `tone_signal`, `capital_discipline`, `track_record`, `bench_depth`, `succession`
- `recommended_sections`: `("Item 7", "Part I, Item 2")`

**`competitive_positioning`:**
- Feeds qualitative factor: `competitive_moat`
- `valid_classes`: `barrier_to_entry`, `pricing_power`, `switching_cost`, `market_share`, `moat_claim`
- `recommended_sections`: `("Item 1", "Item 7", "Part I, Item 2")`

**`segment_discussion`:**
- Feeds Business Overview diligence section
- `valid_classes`: `segment_revenue`, `segment_margin`, `segment_commentary`, `product_mix`, `geographic_breakdown`
- `recommended_sections`: `("Item 1", "Item 7", "Part I, Item 2")`

**Tests (3):**
- `test_schema_management_commentary_valid` — schema has correct valid_classes, examples parse cleanly
- `test_schema_competitive_positioning_valid`
- `test_schema_segment_discussion_valid`

---

## Step 3 — Annotation Repository Methods + REST Endpoints

**Owner:** ai-excel-addin
**Extended files:** `api/research/repository.py`, `api/research/routes.py`

**New `ResearchRepository` methods:**

```python
def save_annotation(self, research_file_id: int, source_type: str,
                    source_id: str, char_start: int, char_end: int,
                    selected_text: str, author: str,
                    section_header: str = None, note: str = None,
                    diligence_ref: str = None) -> dict: ...

def list_annotations(self, research_file_id: int,
                     source_type: str = None,
                     source_id: str = None) -> list[dict]: ...

def delete_annotation(self, annotation_id: int,
                      research_file_id: int) -> bool: ...
```

**New REST endpoints (5):**

```python
@router.get("/documents")
def get_document(source_id: str,
                 source_type: str = "filing",
                 user_id = Depends(get_trusted_user_id)):
    """Load a filing or transcript document.

    Query params:
        source_id: content-hashed identifier (filing_id or transcript source_id)
        source_type: "filing" (default) or "transcript"
    """
    return document_service.get_document(source_id, source_type=source_type)

@router.post("/documents/ingest")
def ingest_document(body: IngestDocumentBody,
                    user_id = Depends(get_trusted_user_id)):
    """Ingest a filing from source_path, return content-hashed filing_id.

    Body: {source_path: str}
    Returns: {filing_id: str}
    """
    filing_id = document_service.ingest_filing(body.source_path)
    return {"filing_id": filing_id}

@router.get("/extractions")
def get_extractions(filing_id: str, section: str, schemas: str,
                    user_id = Depends(get_trusted_user_id)): ...

@router.get("/annotations")
def list_annotations(research_file_id: int, source_id: str = None,
                     user_id = Depends(get_trusted_user_id)): ...

@router.post("/annotations")
def create_annotation(body: CreateAnnotationBody,
                      user_id = Depends(get_trusted_user_id)): ...
```

**Tests (10):**
- `test_save_annotation_basic` — creates with correct char offsets
- `test_list_annotations_file_scoped` — annotations from file A not visible in file B
- `test_list_annotations_filtered_by_source`
- `test_delete_annotation_file_scope` — cannot delete annotation from different file
- `test_annotation_same_passage_two_files` — same filing passage under two theses creates independent rows
- `test_routes_documents_returns_sections` — `GET /documents?source_id=...` returns filing sections
- `test_routes_documents_transcript` — `GET /documents?source_id=...&source_type=transcript` returns transcript segments with speaker data
- `test_routes_documents_ingest` — `POST /documents/ingest` with `{source_path}` returns `{filing_id}` matching content hash; calling twice with same file returns same filing_id
- `test_routes_extractions_returns_grounded`
- `test_routes_annotations_crud`

---

## Step 4 — Agent Highlight Creation via Chat Runtime

**Owner:** ai-excel-addin
**Extended files:** `api/agent/interactive/runtime.py`, `api/research/context.py`

Agent creates annotations with `author='agent'` when it finds notable extractions during research turns. Context extension includes document source_id when `metadata.document_context` is present on the user message.

**Document-context contract (R1 fix):** When a document tab is active and the user sends from the agent panel:
- `tab_context` (INTEGER) stays as the panel's thread_id — unchanged from Phase 1. This is the thread the message belongs to.
- `metadata.document_context` (JSON) carries `{source_id, source_type, section, selection?}` — the document the user is reading.
- `build_research_context()` reads `document_context` from the LAST user message's metadata (via `repo.list_messages(thread_id, limit=1)`) when building the prompt block. If `document_context` is present, it adds a `[DOCUMENT CONTEXT]` section with the source reference and optionally the selected text.
- `tab_context` is NEVER used for document tab identification. It remains an integer thread_id for thread-to-thread cross-reference only.

**Tests (3):**
- `test_agent_annotation_persists` — agent-authored annotation saved with `author='agent'`
- `test_context_includes_document_context` — when last user message has `metadata.document_context`, context block includes source_id, source_type, and section
- `test_agent_annotation_scoped_to_file`

---

## Step 5 — `researchStore` Extension for Document Tabs

**Owner:** frontend (risk_module)
**Extended file:** `researchStore.ts`

```typescript
// Frontend TypeScript interfaces use camelCase per JS convention.
// The WIRE FORMAT (metadata JSON sent to backend) uses snake_case:
//   { source_id, source_type, section, selection }
// The backend reads doc_ctx['source_id'], doc_ctx['source_type'].
// Serialization layer (e.g., in useResearchChat) converts camelCase → snake_case.

interface DocumentTabData {
  sourceType: 'filing' | 'transcript';
  sourceId: string;
  sectionMap: Record<string, { text: string; start: number; end: number }>;
  availableSections: string[];
  activeSection: string | null;
  fullText: string;
  extractions: ExtractionHighlight[];
  annotations: Annotation[];
}

interface TextSelection {
  tabId: string;
  sourceId: string;
  sectionHeader: string | null;
  charStart: number;
  charEnd: number;
  selectedText: string;
}
```

**Tab behavior:** `openDocumentTab` deduplicates by `sourceId`. Document tabs are closeable. When active, reader has NO MessageInput (read-only). Agent panel has MessageInput — sends to panel thread with `tab_context` = panel thread_id (unchanged from Phase 1), and attaches `metadata.document_context = {source_id, source_type, section, selection?}` to the message payload (snake_case wire format — see P2-F1). The `document_context` metadata is the sole mechanism for document tab awareness; `tab_context` remains an integer thread_id only.

**Tests (5):**
- `test_openDocumentTab_dedup`
- `test_openDocumentTab_new`
- `test_setDocumentSection`
- `test_setTextSelection`
- `test_addAnnotation`

---

## Step 6 — React Query Hooks for Documents + Annotations

**Owner:** frontend (risk_module)
**New file:** `useResearchDocuments.ts`

```typescript
export function useDocumentSections(sourceId: string | null, sourceType: 'filing' | 'transcript') { ... }
  // staleTime: Infinity (immutable content-hashed source)
export function useExtractions(sourceId: string | null, section: string | null, schemas: string[]) { ... }
export function useAnnotations(researchFileId: number | null, sourceId?: string) { ... }
export function useCreateAnnotation() { ... }
```

**Tests (4):**
- `test_useDocumentSections_caches_immutable`
- `test_useExtractions_enabled_guard`
- `test_useAnnotations_invalidates_on_create`
- `test_useCreateAnnotation`

---

## Step 7 — Document Tab Components (Filing + Transcript)

**Owner:** frontend (risk_module)
**New files (8 components):**
- `DocumentTab.tsx` — container with section selector
- `FilingSection.tsx` — prose rendering with highlight overlays
- `TranscriptSection.tsx` — speaker-segmented rendering
- `HighlightLayer.tsx` — overlay rendering for agent + user highlights
- `SectionSelector.tsx` — dropdown of available sections
- `TextSelectionHandler.tsx` — captures text selection with char offsets
- `AnnotationPopover.tsx` — note display; "Add note" form for selections
- `AskAboutThis.tsx` — prompt prefill for agent panel

**Filing rendering:** 14-15px Instrument Sans, `--ink`, max-width 640px. Each paragraph gets `data-char-start` and `data-char-end` attributes. Deterministic paragraph split rule per Decision 6: normalize CRLF → LF, split on `\n\n+`, coalesce bullet/list runs and caption lines into single paragraphs.

**Highlight rendering:** Agent highlights: `background: var(--accent-dim)`. User highlights: `background: var(--surface-2)`. Overlapping highlights: outer gets priority.

**Paragraph numbering** (lazy, render-time only, section-relative per R1 fix):

Paragraph numbers are section-relative: "Item 7, para 3" means the 3rd paragraph within the Item 7 section text, NOT the 3rd paragraph in the full document. The helper takes section text and an offset within that section, not full document text and absolute offset.

```typescript
/**
 * Deterministic paragraph split implementing Decision 6's locked rule.
 * Returns paragraph blocks from section text. Each "paragraph" is one of:
 * - A run of non-blank lines (prose paragraph)
 * - A run of bullet/numbered list lines (coalesced into one paragraph)
 * - A figure/table caption line (coalesced into one paragraph)
 *
 * Split rule:
 * 1. Normalize CRLF → LF
 * 2. Split on \n\n+ (2+ consecutive newlines) into raw blocks
 * 3. Within each raw block, consecutive bullet lines (^\s*[-*•]\s)
 *    or numbered list lines (^\s*\d+[.)]\s) count as one paragraph
 * 4. Figure/table caption lines (starting with "Figure", "Table",
 *    "Exhibit", "Chart" followed by a number) count as one paragraph
 */
function splitIntoParagraphs(sectionText: string): string[] {
  const normalized = sectionText.replace(/\r\n/g, '\n');
  const rawBlocks = normalized.split(/\n\n+/).filter(b => b.trim());

  const paragraphs: string[] = [];
  const bulletPattern = /^\s*[-*\u2022]\s/;
  const numberedPattern = /^\s*\d+[.)]\s/;
  const captionPattern = /^(Figure|Table|Exhibit|Chart)\s+\d/i;

  for (const block of rawBlocks) {
    const lines = block.split('\n');
    // Check if entire block is a bullet/numbered list run
    const allBullets = lines.every(l => bulletPattern.test(l) || !l.trim());
    const allNumbered = lines.every(l => numberedPattern.test(l) || !l.trim());
    const allCaptions = lines.every(l => captionPattern.test(l) || !l.trim());

    if (allBullets || allNumbered || allCaptions) {
      // Entire block is one paragraph
      paragraphs.push(block);
    } else {
      // Prose block — one paragraph
      paragraphs.push(block);
    }
  }
  return paragraphs;
}

/**
 * Compute section-relative paragraph number for a char offset.
 *
 * Uses cumulative offset iteration to avoid the off-by-one bug where
 * slice-then-split returns N-1 when charStart falls exactly on a
 * paragraph boundary (P2-F3 fix).
 *
 * @param sectionText - the immutable text of a single filing section
 * @param charStartWithinSection - char offset relative to section start
 * @returns 1-based paragraph number within this section
 *
 * Usage: "Item 7, para 3" means charStartWithinSection falls in the
 * 3rd paragraph of the Item 7 section text.
 */
function computeParagraphNumber(
  sectionText: string,
  charStartWithinSection: number,
): number {
  const paragraphs = splitIntoParagraphs(sectionText);
  let cumOffset = 0;
  for (let i = 0; i < paragraphs.length; i++) {
    cumOffset += paragraphs[i].length;
    if (charStartWithinSection < cumOffset) return i + 1;
    // Skip the delimiter between paragraphs
    const remaining = sectionText.slice(cumOffset);
    const delimMatch = remaining.match(/^(\n\n+)/);
    if (delimMatch) cumOffset += delimMatch[1].length;
  }
  return paragraphs.length; // charStart is at or past the last paragraph
}
```

**Tests (12):**
- `test_DocumentTab_renders_section_selector`
- `test_FilingSection_renders_prose`
- `test_HighlightLayer_agent_highlight`
- `test_HighlightLayer_user_highlight`
- `test_HighlightLayer_overlapping`
- `test_TextSelectionHandler_captures_offsets`
- `test_TranscriptSection_speaker_labels`
- `test_SelectionActionBar_appears_on_selection`
- `test_computeParagraphNumber_bullet_list_coalesced` — a section with "Prose para 1\n\n- bullet A\n- bullet B\n- bullet C\n\nProse para 3" → offset in "Prose para 3" returns paragraph 3 (bullet run counts as one paragraph, not three)
- `test_computeParagraphNumber_numbered_list_coalesced` — "1. First\n2. Second\n3. Third" block counts as one paragraph
- `test_computeParagraphNumber_section_relative` — paragraph 2 within Item 7 section text returns 2, regardless of how many paragraphs precede Item 7 in the full document
- `test_computeParagraphNumber_boundary_exact` — charStart at exact first char of paragraph 3 returns 3 (not 2), verifying the off-by-one fix at paragraph boundaries

---

## Step 8 — "Ask About This" + Agent Panel Integration

**Owner:** frontend (risk_module) + ai-excel-addin backend
**Extended files:** `AgentPanel.tsx`, `useResearchChat.ts`, `api/research/context.py`, `api/agent/interactive/runtime.py`

**Frontend:** When sending from panel while a document tab is active, the message payload includes:
- `tab_context`: panel thread_id (INTEGER, unchanged from Phase 1 — this is the thread the message belongs to)
- `metadata`: `{"document_context": {"source_id": "...", "source_type": "filing"|"transcript", "section": "Item 7", "selection": {"char_start": N, "char_end": M, "text": "..."} | null}}`

"Ask about this" flow: user selects text in document tab → `TextSelectionHandler` captures selection → user clicks "Ask about this" → agent panel MessageInput is prefilled with the selected text as a quote block → on send, `metadata.document_context` is attached with the selection offsets.

**Backend change (R1 fix):** The Phase 1 runtime's `save_message` call already accepts a `metadata` parameter. Extend the runtime pre-turn persistence to pass `metadata` from the request payload through to `save_message`:

```python
# In runtime.py pre-turn persistence (existing code, extended):
research_context["repo"].save_message(
    thread_id=context["thread_id"],
    author="user",
    content=_extract_last_user_message(request.messages),
    content_type="message",
    tab_context=context.get("tab_context"),
    metadata=json.dumps(request_metadata) if request_metadata else None,
)
```

`build_research_context()` extension: after loading the active thread messages, check the LAST user message for `metadata.document_context`. If present, append a `[DOCUMENT CONTEXT]` block to the prompt:

```python
# In build_research_context(), after loading active_messages:
last_user_msg = next(
    (m for m in reversed(active_messages) if m["author"] == "user"),
    None,
)
if last_user_msg and last_user_msg.get("metadata"):
    meta = json.loads(last_user_msg["metadata"])
    doc_ctx = meta.get("document_context")
    if doc_ctx:
        # Add document reference to prompt block
        doc_block = f"[DOCUMENT CONTEXT] Reading {doc_ctx['source_type']} "
        doc_block += f"{doc_ctx['source_id']}, section: {doc_ctx.get('section', 'N/A')}"
        if doc_ctx.get("selection"):
            sel = doc_ctx["selection"]
            doc_block += f"\nSelected text (chars {sel['char_start']}-{sel['char_end']}): "
            doc_block += f'"{sel["text"]}"'
```

**Tests (5):**
- `test_ask_about_this_prefills_panel` — selecting text and clicking "Ask about this" prefills MessageInput with quote block
- `test_ask_about_this_sends_document_context` — sent message includes `metadata.document_context` with correct source_id, section, and selection offsets
- `test_build_research_context_with_document` — when last user message has `metadata.document_context`, prompt block includes `[DOCUMENT CONTEXT]` section with source reference
- `test_build_research_context_without_document` — when last user message has no `document_context`, prompt block is unchanged from Phase 1 behavior
- `test_metadata_persisted_through_save_message` — `save_message` call includes metadata from request payload; `list_messages` returns it back

---

## Step 9 — "Open in Tab" Action from Agent Messages

**Owner:** frontend (risk_module)
**Extended files:** `ConversationFeed.tsx`, `AgentPanel.tsx`

Agent messages with filing/langextract tool calls render "Open in reader →" links. The flow is a two-step process (R1 fix):

1. **Ingest:** Frontend calls `POST /api/research/content/documents/ingest` with `{source_path}` from the agent message's tool call result. This returns `{filing_id}` (content-hashed).
2. **Load:** Frontend calls `GET /api/research/content/documents?source_id={filing_id}` to load the document content and sections.
3. **Open:** `researchStore.openDocumentTab(filing_id, sectionMap, ...)` opens the tab.

```typescript
async function handleOpenInReader(sourcePath: string) {
  // Step 1: Ingest — get content-hashed filing_id
  const { filing_id } = await researchApi.ingestDocument({ source_path: sourcePath });

  // Step 2: Load — fetch document content + sections
  const doc = await researchApi.getDocument(filing_id);

  // Step 3: Open tab
  researchStore.getState().openDocumentTab({
    sourceType: 'filing',
    sourceId: filing_id,
    sectionMap: doc.sections,
    availableSections: doc.available_sections,
    fullText: doc.full_text,
  });
}
```

For transcripts, the agent's `get_earnings_transcript` tool call result includes the transcript data. The flow uses `ingest_transcript()` (server-side, called during the agent turn) so the `source_id` is already available in the tool call result. Frontend calls `GET /documents?source_id=...&source_type=transcript` directly.

**Tests (4):**
- `test_open_in_tab_from_agent_message` — agent message with filing tool call renders "Open in reader →" link
- `test_open_in_tab_triggers_ingest` — clicking link calls `POST /documents/ingest` then `GET /documents`, then opens tab
- `test_open_in_tab_existing_filing` — if filing_id already has an open tab, deduplicates (switches to existing tab)
- `test_open_in_tab_ingest_endpoint` — `POST /documents/ingest` returns `{filing_id}` matching the content hash of the source file

---

## Step 10 — Integration Wiring

**Owner:** risk_module frontend + backend

No proxy code changes needed (Phase 1 catchall handles new paths). Frontend updates: `ResearchTabBar` renders document tab labels, `ResearchWorkspace` renders `DocumentTab` when active, `AgentPanelHeader` shows "Reading" context.

**Tests (3):**
- `test_tab_bar_document_tab`
- `test_tab_content_switches_to_document`
- `test_panel_header_reading_context`

---

## Dependency Batches

```
Batch 1 (parallel, no deps beyond Phase 1):
  Step 1: DocumentService + filing content-hash versioning (ai-excel-addin)
  Step 2: 3 new langextract schemas (ai-excel-addin)
  Step 5: researchStore extension for document tabs (frontend, types-only)

Batch 2 (depends on Batch 1):
  Step 3: Annotation repo methods + REST endpoints (needs Step 1)
  Step 6: React Query hooks (needs Step 5)

Batch 3 (depends on Batch 2):
  Step 4: Agent highlight creation (needs Step 3)
  Step 7: Document tab components (needs Steps 5, 6)

Batch 4 (depends on Batch 3):
  Step 8: "Ask about this" + panel integration (needs Step 7)
  Step 9: "Open in tab" from agent messages (needs Step 7)

Batch 5 (depends on Batch 4):
  Step 10: Integration wiring
```

**Estimated duration:** ~8-12 days single developer, plus review rounds.

---

## Test Summary

| Step | Tests | Delta |
|------|-------|-------------|
| Step 1 — DocumentService | 8 | +2 R1 (transcript parsing) |
| Step 2 — Langextract Schemas | 3 | — |
| Step 3 — Annotation Repo + Routes | 10 | +2 R1 (transcript route, ingest endpoint) |
| Step 4 — Agent Highlights | 3 | — |
| Step 5 — researchStore Extension | 5 | — |
| Step 6 — React Query Hooks | 4 | — |
| Step 7 — Document Tab Components | 12 | +3 R1 (bullet list, numbered list, section-relative paragraph) +1 R2 (boundary exact) |
| Step 8 — Ask About This | 5 | +1 R1 (metadata persistence) |
| Step 9 — Open in Tab | 4 | +1 R1 (ingest endpoint) |
| Step 10 — Integration | 3 | — |
| **Total** | **57** | **+9 R1, +1 R2** |

---

## Cross-Repo Change Summary

| Repo | Changes |
|---|---|
| **ai-excel-addin** | New `api/research/document_service.py` (~300 lines, includes `parse_transcript_sections()`). Extended `api/research/repository.py` (annotation methods, ~100 lines). Extended `api/research/routes.py` (5 new endpoints, ~100 lines). Extended `api/research/context.py` (document_context from metadata, ~40 lines). Extended `api/agent/interactive/runtime.py` (metadata pass-through on save_message, ~5 lines). Extended `mcp_servers/langextract_mcp/schemas.py` (3 new schemas, ~400-600 lines). New shared directory `data/filings/` (content-addressed filing cache). Total: ~1050-1250 lines new code. |
| **risk_module (backend)** | No changes — Phase 1 proxy catchall already forwards `/documents`, `/extractions`, `/annotations`. |
| **risk_module (frontend)** | 8 new React components in `components/research/`. Extended `researchStore.ts` (~150 lines). New `useResearchDocuments.ts` hooks (~80 lines). Extended `ConversationFeed.tsx`, `AgentPanel.tsx`, `ResearchTabBar.tsx`, `ResearchWorkspace.tsx`, `useResearchChat.ts`. Total: ~1500-2000 lines new code + ~200 lines extensions. |

---

## Flagged Issues

1. **Transcript char offsets — decisions doc factual error.** Inv-B finding says transcripts return `char_start`/`char_end` per segment. They do not. Plan resolves by writing transcripts as immutable markdown and using char offsets within that. `parse_transcript_sections()` added in R1 to provide the end-to-end parser contract. Not an architectural conflict — annotation approach unchanged.

2. **`tab_context` vs `document_context` — resolved in R1.** Phase 1 defines `research_messages.tab_context` as INTEGER (thread_id). Document tabs are not threads. R1 fix: `tab_context` stays as panel thread_id (integer, Phase 1 semantics unchanged). `metadata.document_context` (JSON) is the sole mechanism for document tab awareness. No schema migration needed. `build_research_context()` reads `document_context` from the last user message's metadata. Phase 3+ should be aware that document context flows through metadata, not `tab_context`.

---

## Review History (continued)

### R2 — Codex Review (2026-04-11)

**4 findings, 4 fixes applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | `document_context` payload shape inconsistent — some places use camelCase (`sourceId`, `sourceType`), others snake_case (`source_id`, `source_type`). Backend reads `doc_ctx['source_id']`. | Standardized wire format (metadata JSON) on snake_case (`source_id`, `source_type`, `section`, `selection`) throughout the plan. Frontend TypeScript interfaces retain camelCase internally (JS convention); serialization layer converts. Added clarification comment to Step 5 interfaces and fixed Step 5 tab behavior description. |
| 2 | High | Architecture doc not updated for Phase 2 changes — still shows filing-only `GET /documents?filing_id=...`, filing-only annotations, `build_research_context()` without metadata passthrough. | Updated architecture doc: Section 4 API surface Phase 2 endpoints now show `GET /documents?source_id=...&source_type=filing|transcript` + `POST /documents/ingest`. Section 5 Flow 4 updated for source_type dispatch. Section 6 agent context flow notes metadata.document_context extension. |
| 3 | Medium | Paragraph numbering off-by-one at boundaries — `slice(0, charStart)` then `splitIntoParagraphs` returns N-1 when charStart falls on first char of a paragraph. | Replaced `computeParagraphNumber` with cumulative-offset iteration. Iterates paragraphs + delimiters with running offset; returns the paragraph the charStart falls within. Added `test_computeParagraphNumber_boundary_exact` test. |
| 4 | Medium | Ingest idempotency contradicts architecture — plan says "same content → same filing_id" but arch doc says "re-ingesting creates a new filing_id". | Clarified in both docs: same content bytes → same SHA hash → same filing_id (idempotent). Different normalization of the same SEC filing → different content bytes → different hash → different filing_id. Both versions coexist. The filing_id includes a content hash, so identical content always produces the identical filing_id. |

**Test delta:** 56 → 57 (+1 test: paragraph boundary exact)

### R3 — Codex Review (2026-04-11)

**2 findings, both in anchor docs (not plan body):**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | Architecture doc Invariant 6 still says "Re-ingesting the same filing produces a NEW filing_id" — contradicts idempotent model fixed in R2. | Updated architecture doc Invariant 6 to: "Same content bytes → same SHA hash → same filing_id (idempotent). Different normalization of the same SEC filing → different content bytes → different hash → different filing_id. Both versions coexist; old annotations keep pointing at their original filing version." |
| 2 | Medium | Decisions doc Inv-B still claims FMP transcripts return per-speaker `char_start`/`char_end`. Phase 2 plan says this is incorrect. | Added correction note to decisions doc Inv-B: FMP transcripts do NOT return `char_start`/`char_end` per speaker segment. Parser returns `speaker`, `role`, `text`, `word_count` only. Phase 2 resolves via content-hashed markdown files with char offsets within that markdown. |

**Test delta:** No change (57 tests). Fixes were propagation/consistency corrections in anchor docs only.

### R4 — Codex Review (2026-04-11)

**2 findings, both applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | Phase 2 invariant table still says "Re-ingest produces new file_id" — contradicts idempotent model fixed in R2-F4. | Updated Invariant 6 enforcement text to: "Same content bytes → same SHA hash → same filing_id (idempotent). Different normalization → different hash → different filing_id." |
| 2 | Medium | Decisions doc `annotations.source_id` column comment says "transcript period" — stale, should use content-hashed identifiers. | Changed to "content-hashed source identifier (e.g., `VALE_10K_2024_a3f8b2c1` for filings, `VALE_4Q24_transcript_b7c3e1f2` for transcripts)". |

**Test delta:** No change (57 tests). Fixes were stale wording corrections.
