# F156 SEC HTML Reader Architecture Spec

**Status:** DRAFT R0 - discussion artifact for architecture review
**Date:** 2026-05-27
**Owner:** Research Workspace / Corpus UX
**Primary repos:** `risk_module` frontend/backend, AI-excel-addin research API/document service, Edgar parser/corpus pipeline

## Executive Summary

F156 exposed a product architecture mistake: the Research Workspace document reader currently asks a human to read the corpus markdown/plain-text artifact. That artifact is a good machine substrate for retrieval, extraction, offsets, and citation anchoring, but it is a bad primary human reading surface for SEC financial statements.

The MSFT 2Q25 filing example proves the failure mode:

- The exported corpus file already contains run-together statement headings such as `FINANCIAL STATEMENTSINCOME STATEMENTS`, `BALANCESHEETS`, and `CASH FLOWSSTATEMENTS`.
- The section body is serialized as one 3,500-character line before tables.
- The metadata says `Table count: 40`, but the markdown serializes those tables as one contiguous markdown table run. The current frontend therefore sees one giant paragraph plus one giant table.

The recommended architecture is a **hybrid document reader**:

```text
Human reading surface: original sanitized SEC HTML
Agent/citation substrate: corpus markdown/plain text + char offsets
Bridge layer: optional HTML DOM anchor <-> corpus char-span mapping
```

The default user-facing reader should render original SEC HTML when available. The corpus text remains available as a secondary "Corpus Text" / "Extraction Debug" mode and remains the canonical machine layer for retrieval, langextract highlights, annotations, source refs, and citation validation until the bridge layer is mature.

## Goals

1. Make SEC filings readable in the Research Workspace, especially financial statements and tables.
2. Preserve existing corpus-offset functionality: selections, "Ask about this", threads, annotations, extraction highlights, and citation/source refs.
3. Avoid making direct SEC pages the source of application state. The app should own a stable, cached, sanitized source-html surface.
4. Keep corpus markdown as a first-class machine artifact rather than deleting or replacing it.
5. Make failures explicit: if original HTML is unavailable or cannot be mapped to corpus offsets, the UI should degrade honestly.

## Non-Goals

- Do not edit SEC source HTML.
- Do not mutate existing corpus markdown in the browser as a readability hack.
- Do not make all corpus searches depend on HTML parsing.
- Do not require perfect HTML-to-corpus offset mapping in the first release.
- Do not render untrusted SEC HTML unsanitized in the app DOM.

## Current State

### Current frontend document contract

The frontend receives a text-first document:

```ts
interface DocumentTabData {
  sourceType: 'filing' | 'transcript';
  sourceId: string;
  sectionMap: Record<string, { text: string; start: number; end: number }>;
  availableSections: string[];
  activeSection: string | null;
  fullText: string;
  extractions: ExtractionHighlight[];
  annotations: Annotation[];
  segments: TranscriptSegment[];
}
```

This maps to the current research document endpoint:

```text
GET /api/research/content/documents?source_id=...&source_type=filing
```

The endpoint returns `full_text`, `sections`, and `available_sections`. It does not return original HTML, raw-source metadata, raw-source availability, DOM anchors, or HTML/corpus alignment data.

### Current reader behavior

The filing reader parses markdown-ish text into blocks:

- markdown headings (`### TABLES`)
- metadata lines (`**Word count:**`)
- markdown tables (`| ... |`)
- paragraphs split by blank lines

That parser is not wrong. It is operating on a damaged representation. When the source gives it one giant paragraph and one giant table run, it renders one giant paragraph and one giant table run.

### Existing functionality tied to corpus text

These features depend on corpus text and char offsets today:

- `TextSelectionHandler` maps a selected DOM range back to `charStart` / `charEnd`.
- `HighlightLayer` renders annotation and extraction highlights by char span.
- `createAnnotation` persists `char_start`, `char_end`, `selected_text`, `source_id`, and `section_header`.
- Thread seeding stores selected text and document context.
- Langextract requests run against `filing_id`, `section`, and schema names.
- Citation/source refs use document ids, sections, and optional char spans.

Therefore "just render SEC HTML" cannot be a simple replacement unless we intentionally drop or rework these features. The correct design is a two-surface reader with a bridge.

## Locked Architecture Direction

### Decision D1 - Original SEC HTML is the default human reader

For SEC filings, the primary visual surface should be the original filing HTML, sanitized and served by our backend. This should be the default tab when available.

Rationale:

- SEC HTML preserves statement headings, table boundaries, row/column alignment, inline notes, and original order.
- Financial statements are inherently layout-sensitive. Flattened markdown is not an adequate primary representation.
- The user came to the reader to inspect a source document, not a corpus export.

### Decision D2 - Corpus text remains the machine substrate

Corpus markdown/plain text remains canonical for:

- FTS/search
- agent context
- langextract
- citation validation
- existing annotations
- current source-ref char offsets
- debugging parser/corpus quality

Rationale:

- The agent stack already depends on stable text offsets.
- Corpus text is compact and model-friendly.
- HTML DOM offsets are unstable across source revisions, sanitizer changes, browser layout, and inline XBRL noise.

### Decision D3 - Add a bridge layer instead of collapsing the two surfaces

The system should introduce a mapping layer between:

- original HTML DOM anchors
- corpus `full_text` / section char spans

The first release should ship as read-only for Original Filing mode. Later releases can add quote-only selection and deterministic alignment once the selection union and bridge security model are implemented.

Rationale:

- This lets us ship readability first without breaking existing source-state features.
- Perfect alignment is difficult and should be built/tested as its own layer.
- A bridge can improve over time without changing the primary reader UX.

### Decision D4 - The UI must expose both modes

The document tab should have a mode control:

```text
Original Filing | Corpus Text
```

Optional later mode:

```text
Extracts / Agent Marks
```

Default mode:

- `Original Filing` when `source_html.status === "available"`
- `Corpus Text` when source HTML is unavailable

Rationale:

- Analysts need a clean source view.
- Developers and citation/debug workflows still need to inspect the corpus representation.
- The mode label makes the contract honest: "Corpus Text" is not the original filing.

### Decision D5 - Render surfaces must be bound to versioned document identity

Every source HTML surface, corpus text surface, annotation anchor, and mapping record must carry enough identity to prove that the user is looking at the same document version the machine offsets were derived from.

Required identity fields:

- corpus `document_id`
- UI/backend `source_id`
- SEC `accession`
- SEC `primary_document_url`
- `corpus_content_hash`
- `source_html_hash`
- `sanitizer_version`

Rationale:

- Existing corpus architecture treats `document_id` as load-bearing.
- Existing Research Workspace state uses `source_id` heavily.
- SEC filings can be amended, parser output can be regenerated, and sanitizer output can change independently.
- A mapping from HTML to corpus offsets is only valid for a specific pair of source HTML hash and corpus content hash.

### Decision D6 - Phase 1 Original Filing mode is read-only

Phase 1 should not expose selection actions in Original Filing mode. It should ship only the readable source HTML surface, section navigation, fallback handling, and Corpus Text mode parity.

Quote-only selection starts in Phase 2 after the selection wire contract supports HTML anchors without fake char offsets.

Rationale:

- Current `DocumentContextSelection`, `TextSelection`, chat metadata, and annotation create inputs assume `charStart` / `charEnd`.
- Fake corpus offsets would corrupt annotations and citations.
- Readability is the urgent F156 fix; selection and annotation semantics can be layered on safely.

## Proposed Data Model

### Extended document response

Extend `DocumentResponseWire` with render surfaces:

```ts
interface DocumentResponseWire {
  source_id: string;
  source_type: 'filing' | 'transcript';
  document_id?: string | null;
  full_text: string;
  sections: Record<string, { text: string; start: number; end: number }>;
  available_sections: string[];
  segments?: TranscriptSegmentWire[];
  render_surfaces?: DocumentRenderSurfacesWire;
}

interface DocumentRenderSurfacesWire {
  render_surfaces_version: string;
  corpus_text: {
    status: 'available';
    document_id: string;
    parser_version?: string | null;
    corpus_content_hash: string;
  };
  source_html?: SourceHtmlSurfaceWire;
}

type SourceHtmlSurfaceWire =
  | SourceHtmlAvailableSurfaceWire
  | SourceHtmlUnavailableSurfaceWire;

interface SourceHtmlAvailableSurfaceWire {
  status: 'available';
  html_url: string;
  source_url: string;
  source_url_deep?: string | null;
  document_id: string;
  accession: string;
  primary_document_url: string;
  source_html_hash: string;
  corpus_content_hash: string;
  sanitizer_version: string;
  section_anchors: Record<string, SourceHtmlSectionAnchorWire>;
}

interface SourceHtmlUnavailableSurfaceWire {
  status: 'missing' | 'unsupported' | 'error';
  reason: string;
  html_url?: null;
  source_url?: string | null;
  source_url_deep?: string | null;
  document_id?: string | null;
  accession?: string | null;
  primary_document_url?: string | null;
  source_html_hash?: null;
  corpus_content_hash?: string | null;
  sanitizer_version?: string | null;
  section_anchors?: Record<string, SourceHtmlSectionAnchorWire>;
}

type MappingConfidence = 'exact' | 'high' | 'quote' | 'section_only' | 'none';

interface SourceHtmlSectionAnchorWire {
  status: 'available' | 'missing' | 'ambiguous' | 'error';
  fragment?: string | null;
  text_quote?: string | null;
  search_hint?: string | null;
  confidence: MappingConfidence;
  reason?: string | null;
}
```

Notes:

- `html_url` should be a same-origin app URL, not a direct SEC URL.
- `source_url_deep` remains a provenance link, not necessarily the rendered iframe URL.
- `status` lets the UI decide fallback behavior without guessing.
- `document_id`, `corpus_content_hash`, and `source_html_hash` are required before any HTML/corpus mapping can be trusted.
- `section_anchors` lets the v1 reader open the right filing region instead of dumping the user at the start of the full filing.

### Selection and anchor model

The existing selection model is corpus-only. Before Phase 2, frontend and backend contracts need a discriminated selection union that supports HTML quote selections without char offsets:

```ts
type DocumentSelection = CorpusTextSelection | SourceHtmlQuoteSelection | MappedSourceHtmlSelection;

interface CorpusTextSelection {
  surface: 'corpus_text';
  sourceType: 'filing' | 'transcript';
  sourceId: string;
  documentId?: string | null;
  sectionHeader?: string | null;
  selectedText: string;
  charStart: number;
  charEnd: number;
  mappingConfidence: 'exact';
}

interface BaseSourceHtmlSelection {
  surface: 'source_html';
  sourceType: 'filing';
  sourceId: string;
  documentId: string;
  accession: string;
  primaryDocumentUrl: string;
  selectedText: string;
  htmlAnchor: HtmlAnchor;
}

interface SourceHtmlQuoteSelection extends BaseSourceHtmlSelection {
  corpusCharStart?: null;
  corpusCharEnd?: null;
  mappingConfidence: 'quote' | 'section_only' | 'none';
}

interface MappedSourceHtmlSelection extends BaseSourceHtmlSelection {
  corpusCharStart: number;
  corpusCharEnd: number;
  corpusContentHash: string;
  sourceHtmlHash: string;
  mappingConfidence: 'exact' | 'high';
}

interface DocumentAnchor {
  sourceType: 'filing' | 'transcript';
  sourceId: string;
  documentId?: string | null;
  sectionHeader?: string | null;
  selectedText: string;
  corpusCharStart?: number | null;
  corpusCharEnd?: number | null;
  htmlAnchor?: HtmlAnchor | null;
  mappingConfidence?: MappingConfidence;
}

interface HtmlAnchor {
  htmlUrl: string;
  accession: string;
  primaryDocumentUrl: string;
  sourceHtmlHash: string;
  sanitizerVersion: string;
  sourceUrlDeep?: string | null;
  textQuote: string;
  textBefore?: string | null;
  textAfter?: string | null;
  domPath?: string | null;
  elementId?: string | null;
  elementTextHash?: string | null;
}
```

Existing annotation rows can stay valid because `corpusCharStart` / `corpusCharEnd` remain supported. New HTML-backed annotations can add anchor metadata in a JSON column or metadata field after a backend migration.

Contract rule: do not coerce `SourceHtmlQuoteSelection` into the current corpus-only `DocumentContextSelection` by inventing `charStart` / `charEnd`. Until the union exists end to end, Original Filing mode remains read-only.

## Backend Architecture

### Source HTML acquisition

The research document service must provide a stable source HTML surface for a filing. Preferred source order:

1. Existing raw primary-document HTML cached by Edgar parser/corpus pipeline, if available.
2. SEC Archives primary document URL resolved from accession metadata.
3. Fallback unavailable status with reason.

Ownership:

- AI-excel-addin / research document service owns accession resolution, raw HTML fetch/cache, sanitizer execution, content hashes, section-anchor generation, and HTML/corpus mapping.
- risk_module owns the typed frontend contract and may expose a same-origin proxy route, but that proxy must not implement sanitizer or mapping business logic.
- If deployment already routes the research document service under `/api/research`, the same-origin route can be the research service endpoint directly.

The frontend should not fetch SEC directly.

Reasons:

- SEC pages may have frame or cross-origin restrictions.
- Direct SEC URLs do not carry our auth/session context.
- We need stable caching, sanitizer control, and provenance.
- We need to support local/offline dev from cached source artifacts where possible.

### Same-origin HTML endpoint

Add a document source endpoint:

```text
GET /api/research/content/documents/source-html?source_id=...&source_type=filing&document_id=...
```

Response:

- `text/html` sanitized HTML
- response headers include CSP and source identity headers
- response body is safe to render in the selected iframe mode

Recommended initial implementation:

- Serve sanitized HTML as `text/html` from same origin.
- Include a strict CSP.
- Remove scripts, event handlers, remote forms, active embeds, and navigation controls.
- Rewrite relative asset links only if needed for readability.
- Preserve tables and inline styles required for SEC filing layout where safe.
- Include headers such as `X-Document-Id`, `X-Corpus-Content-Hash`, `X-Source-Html-Hash`, and `X-Sanitizer-Version` for debugging and verification.
- Reject mismatched `document_id` / `source_id` pairs rather than serving an ambiguous document.

### Raw HTML cache

Store raw and sanitized HTML separately from corpus markdown:

```text
data/filings_raw/edgar/{accession}/{primary_document_hash}/primary.html
data/filings_rendered/edgar/{accession}/{primary_document_hash}/{sanitizer_version}_{source_html_hash}.html
```

or equivalent inside the existing corpus root.

Rules:

- Raw source is immutable per accession + primary-document URL.
- Sanitized render is derived and rebuildable.
- Corpus markdown remains separate.
- Store provenance: document id, source id, accession, primary URL, fetch time, parser version, corpus content hash, sanitizer version, source HTML hash.
- Mapping records are valid only for a specific `(document_id, corpus_content_hash, source_html_hash, sanitizer_version)` tuple.

### Security Requirements

SEC HTML is untrusted input. The renderer must defend against XSS and state-changing links.

Required controls:

- Strip all scripts.
- Strip inline event handlers.
- Disable forms or rewrite them inert.
- Prevent top-level navigation from inside rendered content.
- Open outbound links in a new tab or route through a confirmation-safe link component.
- Apply CSP with no script execution for source HTML.
- Keep the source HTML renderer isolated from app auth tokens.
- Strip or neutralize `<base>`, `<meta http-equiv>`, remote styles/scripts, active embeds, `javascript:` URLs, and CSS constructs that can trigger external loads or UI spoofing.

Iframe/CSP contract:

1. **Phase 1 read-only iframe**
   - Use `sandbox=""` or the smallest possible token set.
   - Do not use `allow-scripts`.
   - Do not use `allow-same-origin`.
   - Do not use `allow-forms`, `allow-popups`, or top-navigation tokens.
   - CSP should block all scripts.
   - No selection bridge is available in this phase.

2. **Phase 2 quote-selection iframe bridge**
   - Use an app-generated wrapper document that contains sanitized source markup and one app-owned bridge script.
   - The iframe may use `sandbox="allow-scripts"` but must not use `allow-same-origin`.
   - The bridge script posts quote-selection payloads with `postMessage`.
   - Parent code must validate `event.source`, expected opaque-frame session id, document identity, and payload shape.
   - CSP allows only the nonce/hash for the app-owned bridge script; source HTML scripts and event handlers remain stripped.
   - The bridge cannot access app cookies, local storage, or parent DOM.

3. **Sanitized HTML injected into app DOM**
   - Easier selection/highlight overlay.
   - Higher XSS risk; not recommended for F156 v1.
   - Requires a separate security review before use.

Recommendation: Phase 1 uses the read-only iframe. Phase 2 adds the bridge only after the selection union and security tests exist.

## Frontend Architecture

### DocumentTab surface selection

`DocumentTab` should render:

```text
Toolbar:
  Section selector
  Mode segmented control: Original Filing | Corpus Text
  Selection actions when supported

Body:
  Original Filing -> SourceHtmlPane
  Corpus Text     -> FilingSection
```

`FilingSection` remains the corpus text renderer. It should be visually labeled as such.

### SourceHtmlPane

Responsibilities:

- Load the same-origin `html_url`.
- Render original filing HTML.
- Support section navigation through `source_html.section_anchors`.
- Expose selected text to parent only after the Phase 2 bridge contract exists.
- Show clear capability state:
  - "Read-only original filing"
  - "Ask about this available" only in Phase 2+
  - "Annotations available after mapping" only in Phase 3+
  - "Corpus mapping unavailable"

Initial v1 can support:

- reading
- scrolling
- section navigation through exact anchors, fragments, or explicit search hints returned by the backend
- a clear fallback when a section anchor is missing or ambiguous

Initial v1 does not need:

- quote-only "Ask about this"
- exact extraction highlight overlays on HTML
- persistent HTML annotations
- exact corpus span mapping

### Section navigation

The section selector cannot assume that corpus section names map directly to SEC HTML fragments. The backend must return section anchor status for each available corpus section:

```ts
interface SourceHtmlSectionAnchorWire {
  status: 'available' | 'missing' | 'ambiguous' | 'error';
  fragment?: string | null;
  text_quote?: string | null;
  search_hint?: string | null;
  confidence: MappingConfidence;
  reason?: string | null;
}
```

Frontend rules:

- `available` + `fragment`: navigate iframe URL to `html_url#fragment`.
- `available` + `text_quote` / `search_hint`: scroll through a backend-provided anchor/search API or frame bridge only if supported.
- `missing` / `ambiguous` / `error`: keep the user in Original Filing mode but show that exact section positioning is unavailable; do not silently pretend navigation succeeded.

### Corpus Text mode

Corpus Text mode keeps all current behavior:

- text selection with char spans
- annotations
- extraction highlights
- corpus parser warning
- raw source diagnostics

The user-facing label should not imply this is the original document.

Recommended copy:

```text
Corpus Text
Extracted text used for agent retrieval and citation offsets.
```

### Selection behavior

Selection in Original Filing mode has four maturity levels:

0. **Read-only**
   - Phase 1 default.
   - No selection actions are offered in Original Filing mode.
   - User can switch to Corpus Text for current char-span selection, annotations, and highlights.

1. **Quote-only selection**
   - Capture selected visible text.
   - Seed agent prompt with quote + filing metadata + current section.
   - Do not persist exact char offsets.
   - Use `SourceHtmlQuoteSelection`.
   - Mapping confidence: `none`, `section_only`, or `quote`.

2. **Quote + context selection**
   - Store text quote, prefix, suffix, current HTML URL, accession, and section.
   - Good enough to re-find most selections later.
   - Mapping confidence: `quote`.

3. **Mapped selection**
   - Align HTML text node range to corpus char span.
   - Persist both HTML anchor and corpus offsets.
   - Mapping confidence: `exact` or `high`.

Do not block Original Filing v1 on selection. Do not ship levels 1-3 until the selection union is supported by chat context, annotation create inputs, persistence, and tests.

## Bridge Layer: HTML to Corpus Mapping

### Why mapping is hard

SEC HTML and corpus markdown differ because:

- inline XBRL tags wrap facts
- tables flatten differently
- headings can be merged/split by parser
- whitespace normalizes differently
- markdown table serialization inserts pipes and rows not present in visible text
- corpus may truncate or reorder table sections

### Recommended mapping strategy

Build mapping in phases:

1. Normalize HTML visible text and corpus section text with a shared normalizer:
   - collapse whitespace
   - normalize unicode quotes/dashes where safe
   - drop page numbers/header/footer tokens only if deterministic
   - preserve numeric text

2. Align by section first:
   - map `Part I, Item 1` HTML region to corpus `Part I, Item 1`
   - do not try whole-document global alignment as the first step

3. Use quote-based matching for selected text:
   - exact normalized substring
   - prefix/suffix disambiguation
   - confidence score

4. Later, build DOM text-node interval maps:
   - `htmlTextOffset -> corpusCharOffset`
   - only where alignment confidence is high
   - expose confidence to UI and persistence layer

### Mapping output

```ts
interface CorpusHtmlMapping {
  sourceId: string;
  documentId: string;
  accession: string;
  primaryDocumentUrl: string;
  sourceHtmlHash: string;
  corpusContentHash: string;
  sanitizerVersion: string;
  sectionMappings: Array<{
    sectionHeader: string;
    htmlStartHint?: string | null;
    htmlEndHint?: string | null;
    corpusStart: number;
    corpusEnd: number;
    confidence: MappingConfidence;
  }>;
  quoteMapVersion: string;
}
```

Persistence rule:

- `exact` / `high`: can persist corpus offsets with the HTML anchor.
- `quote` / `section_only` / `none`: can seed chat context but cannot create corpus-offset annotations or citations.

## User Experience

### Default filing reader

When source HTML is available:

- Show Original Filing by default.
- Use SEC-like document layout, not app-card layout.
- Keep the analyst panel beside it.
- Keep top Research Workspace chrome unchanged.
- Allow switching to Corpus Text when the user needs to inspect citations or extraction output.

### F156-specific behavior

For MSFT 2Q25 Item 1:

- Original Filing mode should show financial statements as tables/headed sections, not a run-on paragraph.
- Corpus Text mode may still show parser damage, but it should be labeled as corpus extraction and carry the warning.
- The warning belongs in Corpus Text mode by default, not as the primary answer to unreadable Original Filing.

### Empty/unavailable states

If source HTML is unavailable:

```text
Original filing unavailable
Showing corpus text extracted for agent retrieval.
```

If source HTML exists but mapping is unavailable:

```text
Original filing shown. Agent highlights use Corpus Text mode until mapping is available.
```

## Implementation Plan

### Phase 0 - Contract audit

No product change. Confirm and document:

- Where accession / primary document URL lives today.
- Whether AI-excel-addin or Edgar parser caches raw SEC HTML.
- Whether current source ids can resolve to stable document ids/accessions.
- How source_url/source_url_deep move through `ReaderToolCall`, `DocumentResponseWire`, and corpus metadata.
- Exact owner boundaries:
  - research document service owns source HTML fetch/cache/sanitize/map
  - risk_module owns typed UI consumption and optional same-origin proxy
- The required selection union shape for future HTML selections.

Exit criteria:

- One trace for MSFT 2Q25 from UI `sourceId` to source markdown to accession to primary SEC HTML URL.
- Confirmed endpoint shape for source HTML.
- Confirmed identity tuple: `(document_id, source_id, accession, primary_document_url, corpus_content_hash, source_html_hash, sanitizer_version)`.

### Phase 1 - Original Filing read-only mode

Backend:

- Add source HTML availability metadata to document response.
- Add sanitized source HTML endpoint owned by the research document service, optionally exposed through a risk_module same-origin proxy.
- Cache sanitized HTML by accession, primary document URL hash, sanitizer version, and source HTML hash.
- Add section anchor metadata for each corpus section.

Frontend:

- Add Original Filing / Corpus Text segmented control.
- Add `SourceHtmlPane`.
- Default to Original Filing when available.
- Use read-only iframe sandbox with no scripts and no same-origin access.
- Disable Original Filing selection actions.
- Keep Corpus Text mode unchanged for existing annotation/highlight behavior.
- Invalidate or refresh document metadata when render-surface availability changes; do not cache `render_surfaces` forever by only `sourceType/sourceId`.

Exit criteria:

- MSFT 2Q25 Item 1 is readable in Original Filing mode.
- Section selector lands on Item 1 when a section anchor is available, or reports unavailable/ambiguous when it cannot.
- Corpus Text mode still renders existing offsets/highlights.
- If source HTML unavailable, old behavior remains available.
- Existing JS tests pass.

### Phase 2 - Quote-only selection from Original Filing

Frontend/backend:

- Introduce `DocumentSelection = CorpusTextSelection | SourceHtmlQuoteSelection | MappedSourceHtmlSelection`.
- Capture selected visible quote from Original Filing mode.
- Seed "Ask about this" and "Start thread" with selected text, section, source id, and source URL metadata.
- Persist no exact char offsets unless mapping is available.
- Use iframe bridge with `sandbox="allow-scripts"` and no `allow-same-origin`; bridge messages require source/session/document validation.

Exit criteria:

- User can select a passage in Original Filing mode and ask the analyst about it.
- The prompt/context clearly identifies it as source HTML selection with lower mapping confidence.
- No code path invents corpus `charStart` / `charEnd` for quote-only selections.

### Phase 3 - HTML/corpus quote mapping

Backend:

- Implement section-scoped quote matcher.
- Return mapping confidence.
- Add optional anchor metadata to annotations or document context.

Frontend:

- When selection maps confidently, enable normal annotation persistence with corpus offsets.
- When not, show quote-only behavior.
- Persist corpus offsets only for `exact` / `high` mappings.

Exit criteria:

- Simple narrative passages map to corpus char spans.
- Financial table selections degrade to quote-only unless exact mapping is proven.

### Phase 4 - Highlight overlays in Original Filing mode

Only after Phase 3 is stable:

- Project extraction highlights from corpus spans onto HTML DOM ranges where mapping confidence is high.
- Keep unmapped highlights visible in Corpus Text mode.
- Add diagnostics for unmapped spans.

Exit criteria:

- Existing agent marks appear on Original Filing for high-confidence narrative spans.
- No misleading highlights are shown for low-confidence mappings.

## Testing Strategy

### Unit tests

- Document response normalizer handles `render_surfaces`.
- Mode selection defaults to Original Filing only when `source_html.status === "available"`.
- Corpus Text mode keeps current `FilingSection` behavior.
- SourceHtmlPane handles unavailable/error states.
- `DocumentSelection` union rejects quote-only selections in corpus-only annotation create paths.
- Confidence enum is shared across render surfaces, anchors, mapping output, and persistence gates.
- Document query cache invalidates or refreshes render-surface availability when hashes/version change.

### Integration tests

- Mock document response with source HTML available.
- Verify Original Filing mode is default.
- Switch to Corpus Text and verify section text/highlights still render.
- Verify Phase 1 Original Filing mode has no selection actions.
- Verify Phase 2 quote-only selection creates a `SourceHtmlQuoteSelection` payload and no fake char offsets.
- Verify section selector behavior for available, missing, and ambiguous `section_anchors`.

### Visual tests

Fixtures:

- MSFT 2Q25 Item 1 financial statements.
- A narrative-heavy 10-K Item 1A.
- A filing with inline XBRL-heavy tables.
- A filing with missing source HTML.

Acceptance:

- MSFT financial statements are readable on desktop and mobile.
- Tables do not collapse into one unreadable grid.
- Corpus Text label prevents confusing corpus extraction for original source.
- No text overlaps or horizontal page overflow outside intentional table scrolling.

### Security tests

- Source HTML with script tags does not execute.
- Inline event handlers are stripped.
- Forms are inert.
- Links cannot navigate the parent app unexpectedly.
- CSP blocks script execution inside the source HTML surface.
- Phase 1 iframe has no `allow-scripts`, no `allow-same-origin`, no forms, and no top-navigation permissions.
- Phase 2 bridge iframe, if enabled, validates `postMessage` source/session/document identity.
- `<base>`, `meta refresh`, remote active content, `javascript:` URLs, and unsafe CSS/resource loads are stripped or neutralized.

## Migration and Compatibility

Existing documents:

- Continue to load through current `sourceId`.
- Keep current corpus text and char offsets.
- Gain source HTML only when backend can resolve accession/primary URL.
- Add `document_id`, corpus hash, and render-surface metadata without changing existing corpus-section text semantics.
- Refresh document query cache when render-surface metadata appears for a previously loaded document.

Existing annotations:

- Continue to display in Corpus Text mode.
- Do not automatically project into Original Filing until mapping exists.
- Existing corpus annotations remain `CorpusTextSelection`-compatible.
- HTML quote selections are not persisted as corpus annotations until the backend supports anchor metadata.

Existing source refs/citations:

- Continue to point at corpus document/section/char spans.
- UI can add "Open original filing" affordance using `source_url_deep` when available.

Existing agent tools:

- No immediate change to corpus retrieval tools.
- Future tool outputs should include stable document identity and primary source HTML URL when known.
- Chat/thread context must accept the selection union before Original Filing selection actions are exposed.

## Risks

### R1 - Misleading mapping

Bad HTML-to-corpus mapping is worse than no mapping. It can attach annotations or citations to the wrong passage.

Mitigation:

- Confidence levels are required.
- Only `exact` / `high` confidence enables persistent corpus offsets.
- Low-confidence selection stays quote-only.

### R2 - XSS / untrusted HTML

SEC HTML must be treated as untrusted.

Mitigation:

- Sanitizer.
- CSP.
- sandboxed/isolation-first rendering.
- Phase 1 has no scripts/forms.
- Phase 2 bridge script requires no `allow-same-origin`, strict CSP, and message validation.

### R3 - Two truths problem

Original SEC HTML and corpus text may diverge after parser fixes or re-extractions.

Mitigation:

- Store document id plus both content hashes.
- Render provenance in debug mode.
- Mapping records include source HTML hash, corpus content hash, primary document URL, and sanitizer version.

### R4 - Scope creep into full browser/document engine

Rendering every SEC filing perfectly can become a large project.

Mitigation:

- Start with SEC HTML read-only mode.
- Defer exact overlays and table-cell mapping.
- Use fallback Corpus Text mode for agent/citation precision.

## Open Questions

1. Where is raw SEC primary-document HTML currently cached, if anywhere: Edgar parser, AI-excel-addin, both, or neither?
2. Does the existing `sourceId` always resolve back to an SEC accession and primary document URL?
3. Should source HTML read-only mode be scoped only to SEC filings, or later generalized to transcripts and decks?
4. Should Corpus Text mode become hidden behind a developer/debug affordance, or stay user-visible for citation inspection?

## Acceptance Criteria

The architecture is successful when:

- Opening MSFT 2Q25 Item 1 in Research Workspace defaults to a readable original filing view.
- The same tab can switch to Corpus Text and show existing corpus offsets/highlights.
- The user understands which surface they are reading.
- Phase 1 Original Filing mode is read-only; it does not expose broken/fake offset actions.
- Existing annotation/thread/citation workflows are not broken.
- Source HTML is sanitized and served through our app, not fetched ad hoc by the frontend from SEC.
- Source HTML identity is bound to `document_id`, accession, primary URL, source HTML hash, sanitizer version, and corpus content hash.
- Section navigation is explicit about available/missing/ambiguous anchors.
- The system can honestly report when HTML/corpus mapping is unavailable rather than faking precision.
