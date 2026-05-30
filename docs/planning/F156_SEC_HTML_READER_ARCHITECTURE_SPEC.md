# F156 Human Filing Reader Architecture Spec

**Status:** REVIEWED R6 - visual/product PASS, architecture PASS
**Date:** 2026-05-27
**Owner:** Research Workspace / Filing Reader / Corpus UX
**Primary repos:** `risk_module` frontend, AI-excel-addin research API/document service, corpus/Edgar ingestion pipeline
**Companion specs:** `F156_READER_ANALYST_NOTE_LAYER_SPEC.md`

## 2026-05-29 Reconciliation Note

This document remains the L1 spine/security/detail spec for the human filing reader, but the authoritative umbrella is now `F156_READER_SYSTEM_ARCHITECTURE.md` and active sequencing is in `F156_READER_IMPLEMENTATION_PLAN.md`.

The product direction has also narrowed:

- There is still one human reader: faithful sanitized SEC HTML.
- Corpus/extracted text remains diagnostic/substrate only.
- The live source route includes the `risk_module` same-origin proxy/materialization path as well as the upstream AI-excel-addin sanitizer/source service. Browser-followed redirects to SEC are not an acceptable reader path.
- The reader sidecar is not the direct note-action interface. Direct passage actions collapse to the on-document `Ask / Save / Flag` chip; rich actions are agent-mediated and still gated by the durable artifact/evidence/promotion rules.
- Exact/high HTML↔corpus mapping is now producer-first: because corpus markdown is derived from SEC/Edgarparser HTML, the corpus producer should emit an HTML↔corpus mapping sidecar during corpus generation. The mapping registry stores/validates that sidecar and issues `mapping_record_id`; post-hoc text matching is legacy/backfill only.
- The adversarial blocker review found two L1 implementation hazards that this spec now treats as fail gates: redirect materialization must not return raw SEC HTML from the app origin, and parent-side DOM instrumentation must wait for materialized identity with `source_html_hash`.
- The phase list later in this file is historical architecture scaffolding. Use the wave order in `F156_READER_IMPLEMENTATION_PLAN.md` for implementation.

## Executive Summary

F156 is not primarily a parser-format bug. It exposed a product architecture mistake: the Research Workspace made the corpus extraction artifact visible as if it were the filing. That is backwards.

The product surface we need is a **human filing reader**. The baseline is visual/readability parity with opening the SEC filing directly in a normal browser. Anything less readable than the SEC browser rendering fails the core requirement.

The corpus, source text, section map, offsets, retrieval chunks, citation anchors, and future mapping records are still essential, but they are infrastructure. They should make the filing reader more useful by enabling agent grounding, note-taking, citations, research artifacts, and report/model handoff. They should not degrade the human reading experience or leak implementation labels into the primary workflow.

The corrected architecture is:

```text
Primary product surface:
  One human-readable filing reader that preserves SEC visual semantics.

Hidden research substrate:
  Corpus text, char offsets, source ids, document ids, retrieval chunks,
  citations, notes, evidence atoms, and mapping records.

Bridge layer:
  Explicit mapping between visible SEC HTML anchors/selections and the
  machine corpus/citation substrate, with confidence and provenance.
```

The current implementation has moved in the right direction by serving sanitized SEC HTML and defaulting filings to that surface, but serving HTML is not enough. The remaining product gap is layout and framing: the filing is squeezed inside a dashboard pane beside multiple app sidebars. Direct same-origin source HTML already looks close to the SEC document. The embedded app reader does not yet meet the baseline because the app shell consumes too much horizontal space and treats the filing as a panel inside a workspace instead of the main reading canvas.

## Product North Star

The Research Workspace should let a human analyst read the filing and work with an agent alongside it.

The analyst should be able to:

- Open an SEC filing and immediately recognize it as the filing, not as a transformed corpus export.
- Read statements, tables, footnotes, and prose at least as comfortably as on the SEC page.
- Ask the agent about visible passages without manually switching mental models.
- Take notes and capture research artifacts while staying oriented in the source document.
- Trust citations because the system records what filing, visible location, corpus source, and evidence atom support each claim.
- Move from filing reading to thesis/report/model work without losing source provenance.

The agent should be able to:

- See the corpus text and section metadata needed for retrieval and citation.
- Receive visible-selection context from the reader when the user asks about something.
- Link notes, citations, and artifacts back to stable document identity and, when possible, visible filing anchors.
- Degrade honestly when exact HTML-to-corpus mapping is unavailable.

## Non-Negotiable Decisions

### D1 - There Is One Human Filing Reader

The product does not have two equal reader modes. It has one filing reader for humans.

The default and preferred filing reader is rendered SEC filing HTML, sanitized and served through our app. The UI should not ask the analyst to choose between "Original Filing" and "Corpus Text" as if both are equivalent ways to read.

Implications:

- The visible header should say `Filing` or show filing identity, not implementation taxonomy.
- Corpus text must not be a prominent peer tab in the primary toolbar.
- Extracted text remains available as fallback/diagnostic/source text, not as the normal reading mode.
- The analyst workflow stays centered on the filing, with the agent and notes alongside.

### D2 - SEC Browser Rendering Is The Visual Baseline

The acceptance baseline is the same filing opened directly in a browser from the SEC Archives primary document URL.

The reader must preserve:

- Filing order and visible text.
- Table layout, statement boundaries, footnote alignment, and numeric columns.
- SEC-provided inline styles needed for readability.
- Natural document width and scrolling behavior.
- Browser-default readability where the SEC filing relies on default HTML behavior.

The app may add chrome, notes, citations, and an agent sidecar, but those additions cannot make the filing materially less readable.

### D3 - The Corpus Is Hidden Infrastructure

Corpus markdown/plain text remains canonical for:

- FTS/search.
- Agent context.
- Current citation/source refs.
- Current annotation char offsets.
- Langextract/extraction workflows.
- Parser diagnostics.
- Auditability of what the agent saw.

But it is not the primary human reading surface. The corpus should enhance the reader by powering features behind the scenes.

### D4 - Mapping Is Explicit And Confidence-Scored

The system must not fake precision. A visible SEC HTML selection and a corpus char span are different anchors until the bridge proves otherwise.

Mapping levels:

- `exact`: safe to persist corpus offsets and cite at char-span precision.
- `high`: safe for annotation/citation with visible confidence metadata.
- `quote`: safe for agent context and quote capture, not exact corpus offset persistence.
- `section_only`: safe for document/section-level grounding only.
- `none`: visible selection can seed a question, but not a precise citation.

### D5 - Available Reader Surfaces Require Stable Identity

Every visible filing surface and every machine artifact must carry enough identity to prove what is being viewed and what the agent/citation layer used.

For `status: 'available'`, the source HTML descriptor must include:

- `source_id`
- `source_type`
- corpus `document_id`
- SEC accession
- SEC primary document URL
- `corpus_content_hash`
- `sanitizer_version`

Lazy source HTML descriptors may omit only materialization-time fields:

- `source_html_hash`
- section anchors
- mapping records

If the service cannot resolve document id, accession, primary document URL, corpus hash, and sanitizer version, the source HTML surface is not `available`. It must be `missing`, `unsupported`, or `error` with a reason such as `identity_unresolved`.

### D6 - App Layout Must Serve Reading First

The reader cannot be a narrow iframe in the middle of a dense dashboard if the goal is SEC readability.

The filing receives the dominant canvas. Agent, note, and research-artifact surfaces are docked, collapsible, or overlayable so they support reading without permanently shrinking the filing below the SEC baseline.

## Reviewer Finding Resolution

R2 explicitly resolves the first review round:

| Finding | Resolution in R2 |
| --- | --- |
| Lazy available descriptors can violate identity. | Available descriptors now require document id, accession, primary document URL, corpus hash, and sanitizer version. Only source HTML hash/anchors can be lazy. |
| Source HTML endpoint stale/mismatch protection was underspecified. | Endpoint contract now requires authoritative identity resolution and hard rejection of mismatches before serving HTML. |
| Phase 2 iframe bridge security was too vague. | The live model is now explicit: a same-origin source HTML iframe without `sandbox`, guarded by sanitizer, route-scoped CSP, identity verification, safe SEC Archives redirect materialization, and parent-only inert DOM instrumentation. A two-frame bridge is a future option, not the current implementation. |
| SEC parity was subjective. | Visual gates now include concrete viewport, width, screenshot, table, and artifact requirements. |
| Layout architecture was vague. | Phase 1 now chooses a first-class filing reader shell/route, not another dashboard panel. |
| Selection/citation migration was underplanned. | Added schema version, anchor union, adapters, type guards, storage/API migration, and compatibility sequencing. |
| HTML anchors were fragile. | Added canonical visible-text stream anchors and table context; DOM path is only an optimization. |
| Sanitizer/CSP was too generic. | Added explicit policy shape, URL/resource/link rules, and inline-style constraints. |
| Agent/corpus provenance was incomplete. | Added evidence provenance contract for every artifact/answer/citation. |
| Corpus demotion could break existing workflows. | Phase 1 demotes visual prominence but keeps extracted text discoverable until replacement workflows exist. |
| Future document types risk SEC-specific modeling. | Public contract uses generic `primary_reader.kind`; SEC HTML is one reader kind. |
| Visual review artifacts were not required. | Visual QA now requires screenshots, metrics, viewport sizes, and pass/fail notes per target section. |

R3 explicitly resolves the 2026-05-29 adversarial blocker review:

| Finding | Resolution in R3 |
| --- | --- |
| Redirect materialization may bypass sanitizer. | The app proxy may server-fetch SEC Archives redirects, but the fetched body must run through the same sanitizer, CSP/header, identity, and source-html-hash materialization path as non-redirect source HTML. Returning raw SEC bytes from the app route is a fail gate. |
| Iframe instrumentation can run before materialized identity. | Route-bound descriptor verification and hash-backed materialized identity are separate states. Selection capture, inert projection, restored marks, scroll-spy, visual snapshots, and durable anchors require materialized identity including `source_html_hash`. |
| Anchor and offset-frame contract drift. | Offset-bearing anchors now declare `offset_frame`; visible quote anchors declare `visible_text_offset_frame`; render/evidence adapters are locked under S1 before `ReaderBridge`. |
| C0/C mapping not implementation-ready. | `F156_READER_IMPLEMENTATION_PLAN.md` now inserts a C-contract gate that locks sidecar path/schema, DB tables, record-id minting, invalidation, table policy, and backfill before C0/C implementation. |

R4 explicitly resolves the follow-up adversarial review:

| Finding | Resolution in R4 |
| --- | --- |
| S0 named safety but code/tests still asserted raw redirect passthrough. | S0 now explicitly replaces the existing redirect tests and requires app-owned headers, stripped upstream cookies/CSP, source HTML hash, route CSP, and sanitized/materialized redirect bodies. |
| First-class reader shell scope was contradictory. | Active sequencing now includes a Reader shell/layout wave; Phase 1 states the shell is active F156 scope and A1 framing alone is insufficient. |
| ReaderBridge was too abstract. | The implementation plan now locks module path, public inputs, projection result schema, diagnostics, table degradation, DOM ownership, and lint-boundary acceptance. |
| Pre-C projection lacked confidence/frame schema. | S1/ReaderBridge now own `ReaderProjectionInput` / `ReaderProjectionResult`; badges render resolved projection confidence and downgrade diagnostics. |
| C0 producer API remained underspecified. | C-contract now includes upstream artifact-bundle requirements, source identity/hash provenance, visible-text algorithm version, stable section ids, deterministic producer ids, atomicity, and DB migrations. |
| Remote SEC images conflicted with no-cookie privacy. | Default CSP blocks direct remote resources; SEC resources require an app proxy or an explicit tested privacy exception. |

## Current State Snapshot

### What Now Works

- Filing documents can advertise a source HTML render surface.
- The frontend can default filings to the visual filing reader when source HTML is available.
- The research API can lazily serve sanitized SEC HTML through a same-origin route.
- If the upstream research API represents source HTML as an SEC Archives redirect, the app proxy may materialize that redirect server-side, but the final body must still pass through sanitizer/CSP/hash/materialized-identity handling before it is returned from the same-origin route. Browser-followed redirects to `sec.gov` are not acceptable for the reader iframe because they break same-origin selection capture.
- The sanitizer strips hidden/non-visible iXBRL metadata that previously polluted the visible page.
- Direct same-origin source HTML rendering preserves SEC-like default layout much better than corpus markdown.
- A small `SEC` provenance link can point to the direct primary document.

### What Still Fails The Product Vision

- The filing is embedded inside a research-dashboard canvas, not promoted to a true reading canvas.
- The reader width is materially smaller than direct SEC browser rendering because app navigation, tabs, agent panels, and sidebars consume horizontal space.
- The filing appears as a pane under workspace chrome, so the first visual impression is "app panel containing a filing" rather than "filing with research tools around it."
- The agent/right rail is useful, but it competes with the document instead of behaving like a research sidecar.
- The UI still contains implementation affordances such as `View Text`, which may be acceptable as a short-term fallback but should not be central to the analyst workflow.
- Source selection, notes, and citation capture are not yet unified around visible filing anchors.

## Target Experience

### Default Filing Workspace

When an analyst opens a filing:

1. The filing occupies the primary viewport.
2. The visible document looks like the SEC filing opened in a browser, subject only to safe embedding constraints.
3. App chrome is reduced to navigation and source identity, not dense dashboard controls.
4. The agent sidecar is available but does not permanently compromise document width.
5. Notes/citations/artifacts are tied to visible document context without requiring the analyst to inspect corpus text.

### First-Class Reader Shell

F156 should ship a first-class filing reader shell, not another panel state inside the existing dashboard card.

The shell is:

- URL-addressable from the Research Workspace.
- Opened by document tabs / "Open in reader" actions.
- Back-linked to the originating research file and thread.
- State-preserving for current source id, section, agent draft, and notes.
- Minimal chrome by default: filing identity, section navigation, SEC link, agent/notes affordances, and back navigation.
- Free of nested card framing around the filing.

The existing Research Workspace remains the organizing surface for files, tabs, threads, and diligence. The filing reader shell is the focused reading surface launched from it.

### Reading Layout Rules

Desktop:

- With the agent sidecar collapsed, the filing iframe should occupy at least 80% of the browser viewport width at desktop widths >= 1440px.
- With the agent sidecar open, the filing iframe should remain at least 960px wide at a 1440px viewport and at least 1200px wide at an 1880px viewport, unless the viewport is too narrow to satisfy this without overlap.
- The embedded filing content viewport should be within 10% of the same-origin source HTML route width when the sidecar is collapsed.
- Global nav, research thread list, dense metadata controls, and footer exit ramps should not consume the reading canvas by default.
- Tables should keep their intrinsic layout. If a table exceeds the filing viewport, horizontal scrolling inside the document is acceptable; forced table compression that changes meaning is not.

Mobile/narrow:

- Filing remains the primary surface.
- Agent and notes move to drawers/sheets.
- Extracted-text fallback remains hidden behind a secondary action.
- Horizontal table scrolling is acceptable when it matches browser behavior; text overlap is not.

### Agent Sidecar Rules

The agent sidecar should:

- Show current document/section context.
- Accept questions about the visible filing.
- Hold note-taking and captured artifacts.
- Be collapsible and resizable.
- Default collapsed on first filing-reader entry.
- Restore a prior open/narrow sidecar state only when the measurable filing-width gates still pass.
- Never be required for basic reading.
- Never obscure filing text by default.

### Notes And Artifacts

The filing reader should support a research loop:

```text
Read visible filing passage
  -> ask agent / take note / capture quote
  -> store note + citation/evidence metadata
  -> reuse artifacts in thesis, report, or model build
```

The user-facing model is "I captured this from the filing." The internal model decides whether the anchor is exact corpus offset, visible quote anchor, section anchor, or document-level fallback.

## Architecture

### Reader Surface Model

Expose a generic primary reader contract so F156 does not bake SEC-only naming into all future research documents.

```ts
interface DocumentRenderSurfacesWire {
  render_surfaces_version: string;
  primary_reader?: PrimaryReaderSurfaceWire;
  diagnostic_surfaces?: DiagnosticSurfacesWire;
}

type PrimaryReaderSurfaceWire =
  | SecFilingHtmlReaderWire
  | UnsupportedReaderWire;

interface SecFilingHtmlReaderWire {
  kind: 'sec_filing_html';
  status: 'available';
  render_mode: 'lazy' | 'eager';
  html_url: string;
  source_id: string;
  source_type: 'filing';
  document_id: string;
  accession: string;
  primary_document_url: string;
  source_url?: string | null;
  source_url_deep?: string | null;
  source_html_hash?: string | null;
  corpus_content_hash: string;
  sanitizer_version: string;
  section_anchors?: Record<string, SourceHtmlSectionAnchorWire>;
}

interface UnsupportedReaderWire {
  kind: 'unsupported';
  status: 'missing' | 'unsupported' | 'error';
  reason: string;
}

interface DiagnosticSurfacesWire {
  corpus_text: CorpusTextSurfaceWire;
}

interface CorpusTextSurfaceWire {
  status: 'available';
  document_id: string;
  parser_version?: string | null;
  corpus_content_hash: string;
}
```

Product rule:

- `primary_reader.kind === 'sec_filing_html'` is the human reader for SEC filings.
- `diagnostic_surfaces.corpus_text` is machine substrate and fallback/diagnostic surface.
- The UI may expose `View extracted text` behind a secondary diagnostics action, but the default workflow should not present a two-mode choice.

Backward compatibility:

- Existing `render_surfaces.source_html` can be adapted into `primary_reader.kind = 'sec_filing_html'` during migration.
- Existing `render_surfaces.corpus_text` remains readable.
- The frontend should accept both shapes during the transition but internally normalize to `primary_reader`.

### Source HTML Identity And Lazy Materialization

`status: 'available'` means the backend can prove the filing identity before the iframe loads. It does not necessarily mean the raw/sanitized HTML has already been fetched and hashed.

Required before `available`:

- `source_id`
- `source_type = filing`
- `document_id`
- `accession`
- `primary_document_url`
- `corpus_content_hash`
- `sanitizer_version`
- `html_url`

Allowed to be lazy:

- `source_html_hash`
- `section_anchors`
- `mapping_version`
- `source_html_byte_length`

If identity cannot be resolved:

- Return `primary_reader.kind = 'unsupported'` or omit `primary_reader`.
- Keep `diagnostic_surfaces.corpus_text` available when possible.
- Show a fallback message: `Original filing unavailable; showing extracted text used for retrieval.`

### Backend Ownership

AI-excel-addin / research document service owns:

- Accession and primary document URL resolution.
- Raw SEC HTML fetch/cache.
- Sanitizer execution.
- Same-origin source HTML endpoint.
- Source HTML hash and sanitizer version.
- Section-anchor and HTML/corpus mapping generation.

`risk_module` owns:

- Typed frontend consumption.
- Reader shell layout and product experience.
- UI state around document, agent sidecar, notes, and artifacts.
- The current deployment's same-origin source-html proxy/materializer. It may only be removed if an equivalent same-origin route preserves safe SEC Archives redirect materialization through the sanitizer/hash pipeline, hard identity binding, CSP, and parent-side selection/projection access.

The frontend must not fetch SEC directly for the embedded reader.

### Same-Origin Source HTML Endpoint

```text
GET /api/research/content/documents/source-html
  ?source_id=...
  &source_type=filing
  &document_id=...
  &corpus_content_hash=...
  &sanitizer_version=...
```

The endpoint must resolve the request through an authoritative backend record before serving HTML.

Validation requirements:

1. Resolve `source_id` and `source_type` to the current document descriptor.
2. Resolve or verify corpus `document_id`.
3. Resolve SEC accession and primary document URL.
4. Verify requested `document_id` matches the resolved document id.
5. Verify requested `corpus_content_hash` matches the resolved corpus hash.
6. Verify requested `sanitizer_version` is supported and matches the intended render version.
7. If optional request params such as accession or primary URL are later added, reject if they disagree with the resolved identity.
8. Reject ambiguous or mismatched identity with `404` or `409`; do not serve a best-effort document.

Response requirements:

- `text/html` sanitized SEC filing HTML.
- Strict CSP.
- No source scripts, event handlers, forms, active embeds, `<base>`, `meta refresh`, or `javascript:` URLs.
- Preserve safe inline styles and table structure needed for SEC readability.
- Prefer browser-default document behavior over app CSS overrides.
- Always emit resolved identity headers:
  - `X-Source-Id`
  - `X-Document-Id`
  - `X-Accession`
  - `X-Primary-Document-Url`
  - `X-Corpus-Content-Hash`
  - `X-Source-Html-Hash` after materialization
  - `X-Sanitizer-Version`
- Redirect-materialized responses have the same requirements as ordinary source HTML responses. The app proxy must not return the raw `sec.gov` response body, headers, or content type directly from the same-origin route. Existing route tests that assert raw passthrough must be replaced with sanitizer/hash/CSP/header-allowlist tests.

Cache keys:

- Raw source cache: accession + primary document URL hash + raw/source HTML hash.
- Sanitized render cache: accession + primary document URL hash + raw/source HTML hash + sanitizer version.
- Served reader binding: sanitized render cache key + corpus content hash + document id. This prevents the UI from silently binding a valid HTML file to the wrong corpus artifact.

Browser caching:

- The iframe URL should include `sanitizer_version` so visual QA and browser caches are bound to the render rules.
- Responses should also use ETag/Last-Modified based on the resolved source HTML hash and sanitizer version.
- If sanitizer version is absent during a transition window, respond with `Cache-Control: no-store, private` and migrate callers to the versioned URL.

Materialized identity channel:

- Frontend code cannot rely on reading iframe navigation response headers.
- Add a same-origin metadata endpoint, or equivalent manifest endpoint, that returns the materialized reader identity as JSON:

```text
GET /api/research/content/documents/source-html/metadata
  ?source_id=...
  &source_type=filing
  &document_id=...
  &corpus_content_hash=...
  &sanitizer_version=...
```

```ts
interface SourceHtmlMaterializedIdentityWire {
  source_id: string;
  source_type: 'filing';
  document_id: string;
  accession: string;
  primary_document_url: string;
  corpus_content_hash: string;
  sanitizer_version: string;
  source_html_hash: string;
  html_url: string;
  etag?: string | null;
  byte_length?: number | null;
}
```

- The metadata endpoint uses the same hard identity validation as the HTML route.
- It may synchronously materialize sanitized HTML if needed, or return `202` with retry metadata if materialization is intentionally asynchronous.
- Parent-side selection capture, inert projection, restored quote anchors, scroll-spy/perceptual capture, visual snapshots, and persisted visible anchors are gated until the parent has fetched and verified this materialized identity.
- The sanitized HTML response may also include inert `<meta name="hank-source-html-hash" ...>` / JSON identity for diagnostics, but that is not the only contract.

### Sanitizer And CSP Contract

SEC HTML is untrusted. The sanitizer must preserve document readability while removing active behavior.

Sanitizer rules:

- Remove all `<script>`, `<noscript>` content that changes visible meaning only when verified safe, active embeds, `<object>`, `<embed>`, `<applet>`, and remote executable resources.
- Remove all inline event-handler attributes.
- Remove or neutralize forms and submit controls.
- Remove `<base>` and `meta http-equiv` refresh/content-security controls.
- Rewrite outbound links to `target="_blank" rel="noopener noreferrer"` or route them through an app-controlled safe opener.
- Strip `javascript:`, `data:` executable, and non-http(s)/mailto URL schemes from links/resources.
- Preserve safe inline style attributes required by SEC tables.
- Strip CSS imports and unsafe remote `url(...)` references unless rewritten through an approved resource proxy.
- Strip hidden/non-visible iXBRL metadata that is not part of the human-readable filing.

Source HTML response CSP should be equivalent to:

```text
default-src 'none';
script-src 'none';
object-src 'none';
connect-src 'none';
frame-src 'none';
style-src 'unsafe-inline';
img-src 'self' data:;
font-src 'self' data:;
base-uri 'none';
form-action 'none';
frame-ancestors 'self';
```

Remote images/fonts are blocked by default. If visual QA proves SEC-hosted resources are required for readability, add an app-controlled resource proxy that fetches allowlisted SEC resources server-side and serves them from `self` without forwarding cookies, referrers, or upstream active headers. Direct `img-src https://www.sec.gov` is a deliberate privacy exception and must not be enabled without documenting and testing the leakage boundary. Inline styles are allowed only because SEC filings commonly encode table presentation inline; script execution remains blocked.

### Reader Isolation And Bridge Security

The live reader uses a CSP-constrained, same-origin filing iframe. This is an explicit product/security tradeoff: faithful browser rendering and direct selection/highlight projection require the parent reader to inspect and mutate the sanitized filing DOM. A sandboxed iframe made that bridge impossible without degrading the reader, so the security boundary is the source HTML route plus response policy, not the iframe `sandbox` attribute.

Current rendering model:

- Render sanitized source HTML at `/api/research/content/documents/source-html`.
- The app proxy must not forward an upstream `Location` response directly to the browser for this route. If the upstream returns a redirect to an SEC Archives primary document, the proxy fetches that document server-side, verifies the final URL is an allowed `sec.gov` Archives URL, sanitizes/materializes it with the same source-html pipeline, computes `source_html_hash`, and returns only the sanitized HTML from the same-origin source route.
- Redirect materialization uses app-owned response headers only: route CSP, route frame policy, sanitized content type, cache headers keyed to `source_html_hash`/sanitizer version, and identity headers. It must strip or ignore upstream `Set-Cookie`, CSP, `Location`, `Content-Encoding`, active content-type surprises, and other non-allowlisted headers.
- Redirects to non-SEC hosts, non-HTTPS URLs, or paths outside `/Archives/edgar/` fail closed.
- Embed that route in a same-origin iframe with no `sandbox` attribute.
- Set `referrerPolicy="no-referrer"` on the iframe.
- Parent code may read selection state and inject inert highlight marks into the iframe DOM.
- No source scripts are preserved by the sanitizer.
- The source HTML response sends `script-src 'none'`, `object-src 'none'`, `connect-src 'none'`, `frame-src 'none'`, and `form-action 'none'`.
- The source HTML route uses `X-Frame-Options: SAMEORIGIN` and `frame-ancestors 'self'` so only the app can embed it.
- The general app remains `X-Frame-Options: DENY`; this exception is route-scoped to source HTML.
- Durable reader actions are gated on verified materialized identity, including source id, document id, accession, primary document URL, corpus hash, sanitizer version, and source HTML hash.
- Parent-side DOM instrumentation is also gated on verified materialized identity. Route-bound URL verification alone is insufficient.

Threat-model requirements:

- Sanitized SEC markup is untrusted content.
- Sanitized source HTML must never be injected into the parent app DOM.
- Source HTML must not execute scripts, submit forms, open nested frames, call network APIs, run object/embed content, or override base URLs.
- Parent code must treat selected filing text as untrusted quoted data in prompt assembly.
- Parent code may create inert marks for highlight projection/restored quote anchors, but it must not inject executable script or event handlers into the source frame.
- Links inside source HTML must be neutralized or safe-opened according to the sanitizer rules.
- Perceptual/read-trail capture uses the accepted F156 D posture: visible-section viewport context only, attached to the research turn for replay/audit, self-labeled by an audit manifest, with no dwell/read time, no per-section temporal trail, and no durable read-trail table. User-facing disclosure is required before any UI surfaces that trail in the multi-user product.
- Tests must assert the route-scoped CSP includes the explicit no-script/no-connect/no-frame/no-object directives.

Future option:

If we later need a richer bridge that runs app-owned scripts outside the parent, use a two-frame app-owned bridge design. That design must still keep scripts out of the filing document itself, validate source identity on every message, and prove sanitized SEC content cannot emit trusted bridge events. It is not the current model.

## Selection, Notes, Citations, And Evidence

The current selection model is corpus-only. The future model must be a discriminated union with schema versioning.

```ts
type DocumentAnchor =
  | CorpusSpanAnchor
  | FilingQuoteAnchor
  | FilingMappedAnchor
  | FilingTableCellAnchor
  | SectionAnchor
  | DocumentLevelAnchor;

interface BaseAnchor {
  anchor_schema_version: 'v2';
  source_id: string;
  source_type: 'filing' | 'transcript';
  document_id: string;
  corpus_content_hash?: string | null;
  confidence: 'exact' | 'high' | 'quote' | 'section_only' | 'none';
}

type OffsetFrame = 'corpus_doc' | 'api_excerpt';
type VisibleTextOffsetFrame = 'source_html_visible_text_v1';

interface CorpusSpanAnchor extends BaseAnchor {
  anchor_kind: 'corpus_span';
  surface: 'corpus_text';
  corpus_content_hash: string;
  section_header?: string | null;
  selected_text: string;
  char_start: number;
  char_end: number;
  offset_frame: OffsetFrame;
  confidence: 'exact';
}

interface FilingQuoteAnchor extends BaseAnchor {
  anchor_kind: 'filing_quote';
  surface: 'filing_html';
  source_type: 'filing';
  accession: string;
  primary_document_url: string;
  corpus_content_hash: string;
  source_html_hash: string;
  selected_text: string;
  html_anchor: HtmlAnchor;
  confidence: 'quote' | 'section_only' | 'none';
}

interface FilingMappedAnchor extends BaseAnchor {
  anchor_kind: 'filing_mapped';
  surface: 'filing_html';
  source_type: 'filing';
  accession: string;
  primary_document_url: string;
  corpus_content_hash: string;
  selected_text: string;
  html_anchor: HtmlAnchor;
  char_start: number;
  char_end: number;
  offset_frame: 'corpus_doc';
  source_html_hash: string;
  mapping_algorithm_version: string;
  mapping_record_id: string;
  confidence: 'exact' | 'high';
}

interface FilingTableCellAnchor extends BaseAnchor {
  anchor_kind: 'filing_table_cell';
  surface: 'filing_html';
  source_type: 'filing';
  accession: string;
  primary_document_url: string;
  corpus_content_hash: string;
  source_html_hash: string;
  sanitizer_version: string;
  selected_text: string;
  html_anchor: HtmlAnchor;
  table_context: TableCellContext;
  table_citation_record_id: string;
  confidence: 'exact' | 'high';
}

type SectionAnchor = FilingSectionAnchor | CorpusSectionAnchor;

interface FilingSectionAnchor extends BaseAnchor {
  anchor_kind: 'filing_section';
  surface: 'filing_html';
  source_type: 'filing';
  document_id: string;
  accession: string;
  primary_document_url: string;
  corpus_content_hash: string;
  source_html_hash: string;
  sanitizer_version: string;
  section_header: string;
  section_anchor_status: 'available' | 'missing' | 'ambiguous' | 'error';
  confidence: 'section_only';
}

interface CorpusSectionAnchor extends BaseAnchor {
  anchor_kind: 'corpus_section';
  surface: 'corpus_text';
  source_type: 'filing' | 'transcript';
  document_id: string;
  corpus_content_hash: string;
  section_header: string;
  confidence: 'section_only';
}

type DocumentLevelAnchor = FilingDocumentAnchor | CorpusDocumentAnchor;

interface FilingDocumentAnchor extends BaseAnchor {
  anchor_kind: 'filing_document';
  surface: 'filing_html';
  source_type: 'filing';
  document_id: string;
  accession: string;
  primary_document_url: string;
  corpus_content_hash: string;
  source_html_hash: string;
  sanitizer_version: string;
  confidence: 'none' | 'section_only';
}

interface CorpusDocumentAnchor extends BaseAnchor {
  anchor_kind: 'corpus_document';
  surface: 'corpus_text';
  source_type: 'filing' | 'transcript';
  document_id: string;
  corpus_content_hash: string;
  confidence: 'none' | 'section_only';
}

interface HtmlAnchor {
  html_url: string;
  accession: string;
  primary_document_url: string;
  sanitizer_version: string;
  source_html_hash: string;
  visible_text_anchor: VisibleTextAnchor;
  dom_path?: string | null;
  element_id?: string | null;
  element_text_hash?: string | null;
}

type TableValueSource = 'edgar_financials_table' | 'edgar_statement' | 'xbrl_fact';

interface TableFilingIdentity {
  document_id?: string | null;
  accession: string;
  primary_document_url?: string | null;
  cik?: string | null;
  form_type?: string | null;
  source?: string | null;
  fiscal_year?: number | null;
  fiscal_quarter?: number | null;
}

interface TableCellContext {
  table_citation_record_id?: string | null;
  table_index?: number | null;
  row_index?: number | null;
  column_index?: number | null;
  row_header?: string | null;
  column_header?: string | null;
  table_value_source: TableValueSource;
  value_filing_identity: TableFilingIdentity;
  table_id?: string | null;
  table_section_key?: string | null;
  table_section_header?: string | null;
  raw_cell_text?: string | null;
  parsed_value_text?: string | null;
  parsed_numeric_value?: string | null;
  unit?: string | null;
  scale?: string | null;
  period?: string | null;
  concept?: string | null;
  fact_id?: string | null;
  reader_source_html_hash: string;
  resolver_version: string;
  resolved_at: string;
  mismatch_diagnostics?: string[] | null;
}

interface VisibleTextAnchor {
  quote: string;
  text_before?: string | null;
  text_after?: string | null;
  normalized_stream_start?: number | null;
  normalized_stream_end?: number | null;
  visible_text_offset_frame: VisibleTextOffsetFrame;
  section_hint?: string | null;
  table_context?: TableCellContext | null;
  anchor_algorithm_version: string;
}
```

Rules:

- Do not invent corpus `char_start` / `char_end` for visible HTML selections.
- Quote-only selections may seed the agent and notes, but cannot become exact citations.
- Exact/high mappings may persist corpus offsets and support citation/evidence atoms only when backed by a durable registry `mapping_record_id`.
- Every offset-bearing anchor must include `offset_frame`; mapped visible filing anchors use `offset_frame: 'corpus_doc'`; visible quote anchors use `visible_text_anchor.visible_text_offset_frame = 'source_html_visible_text_v1'` for normalized visible-text offsets.
- Citeable table selections require a server-issued `filing_table_cell` anchor (or explicitly equivalent registry-backed table authority) with `table_context` carrying same-filing table-value provenance. ReaderBridge may submit a table/cell localization candidate, but the table resolver must prove `value_filing_identity` matches the materialized reader filing identity before persisting parsed values or exact/high table-cell evidence.
- `table_context` may persist table/cell identity, parsed value provenance, resolver version, and diagnostics. It must not persist viewport pixels, screenshots, or bounding rects as citation coordinates. Overlay links store a `DocumentAnchor` / artifact id and ask `ReaderBridge` to recompute current rects from the verified iframe.
- Persisted anchors use `anchor_schema_version = 'v2'`.
- Existing legacy corpus annotations that can resolve a corpus hash from the document descriptor are adapted at read time into valid `CorpusSpanAnchor` values with `anchor_schema_version = 'v2'` and optional `legacy_source` metadata outside the anchor object.
- Existing legacy corpus annotations that cannot resolve `corpus_content_hash` are exposed as legacy/unversioned evidence and must not be treated as fully versioned exact citations until backfilled.
- Visible filing anchors created from the reader must include materialized `document_id`, accession, primary URL, corpus hash, sanitizer version, and source HTML hash before they are persisted or sent as durable agent evidence.
- Filing section/document fallback anchors created from the visible reader have the same materialized identity requirement as quote anchors.
- Exact/high mapped filing anchors must include `mapping_algorithm_version` and `mapping_record_id`; exact/high table-cell anchors must include `table_citation_record_id` and server-authorized table provenance.
- Lazy descriptors may omit `source_html_hash`; persisted visible anchors may not.
- DOM path is an optimization only; durable visible anchors use quote, prefix/suffix, normalized visible-text stream offsets, section hints, table context, source HTML hash, sanitizer version, and anchor algorithm version.

### Persistence And API Migration

Migration requirements:

- Add or reuse an anchor JSON field for notes, artifacts, and future annotations.
- Preserve existing `char_start` / `char_end` rows as corpus-span anchors.
- Add type guards at every boundary that currently assumes corpus offsets:
  - annotation creation
  - note creation
  - chat/thread context
  - source refs/citations
  - extraction highlights
  - artifact registry writes
- Corpus-only APIs continue to accept only `CorpusSpanAnchor`.
- Quote/mapped filing anchors use new paths or explicit union-aware inputs.
- Compile-time tests should fail if a `FilingQuoteAnchor` is passed to a corpus-offset-only path.

Compatibility rule:

- Phase 1 may visually demote extracted/corpus text, but it must remain discoverable for existing annotations, highlights, and debugging until quote selection and note capture are available in the visible filing reader.

### Evidence Provenance Contract

Every agent response artifact, note, citation, or captured evidence item should carry:

- `anchor_kind`
- `confidence`
- `surface`
- source id/type
- document id
- accession and primary URL for SEC filings
- corpus hash when corpus was used
- source HTML hash when visible HTML was used and materialized
- selected quote or section/document fallback
- mapping algorithm version when applicable
- offset frame when any offsets are present
- `mapping_record_id` for exact/high mapped filing evidence

User-facing UI should stay simple, but citation/evidence details must preserve whether the support came from:

- exact corpus span
- exact/high mapped visible filing span
- quote-only visible filing selection
- section-only/document-level fallback

## Implementation Plan

This section records the older architecture-phase decomposition. The active build order has been superseded by `F156_READER_IMPLEMENTATION_PLAN.md`:

1. S0 source HTML safety gate: redirect sanitization and materialized-identity instrumentation gate.
2. A1 framing/callout grammar.
3. S1 contract lock: render-surface adapter, v2 anchors/offset frames, quote-level evidence locator.
4. Perception chain via `context.document_context`.
5. First-class reader shell/layout.
6. `ReaderBridge` extraction.
7. A2 action-surface rebind to the minimal overlay plus agent-mediated rich actions.
8. `reader_action` transient stream channel.
9. Findings projection plus alignment-boundary enforcement.
10. C-contract sidecar/registry schema gate.
11. Corpus producer mapping sidecar.
12. Mapping registry, perceptual bridge, and visual bridge.

The phase descriptions below remain useful for acceptance scope, but implementation agents should not treat them as the current sequencing contract.

### Phase 0 - Product And Architecture Reset

Goal: update the plan and align reviewers before more implementation.

Tasks:

- Replace the two-surface product framing with one human filing reader plus hidden substrate.
- Record current implementation status and visual gap.
- Run visual/product reviewer against current app screenshot and source HTML baseline.
- Run adversarial architecture reviewer against this spec.
- Iterate until no blocking reviewer findings remain.

Exit criteria:

- Plan clearly states SEC browser rendering is the baseline.
- Plan clearly states corpus text is infrastructure/fallback, not a primary reader mode.
- Visual gaps are converted into actionable implementation items.
- Architecture conflicts are resolved before implementation resumes.

### Phase 1 - First-Class Reading Shell

Goal: make the embedded reader satisfy the SEC readability baseline.

Frontend tasks:

- Implement a first-class filing reader shell/route launched from Research Workspace document tabs.
- Make the filing shell URL-addressable and preserve back navigation to the originating research workspace.
- Treat the first-class shell as active F156 scope, not a later workspace-only task. A1 framing alone is insufficient for Phase 1.
- Give the filing HTML a dominant canvas with substantially more horizontal width.
- Default the agent sidecar collapsed on first filing reader entry.
- Restore a previous sidecar state only if the filing-width gates still pass.
- Make the agent sidecar collapsible and resizable.
- Reduce chrome to filing identity, section navigation, SEC link, agent/notes affordances, and back navigation.
- Remove nested card framing around the filing.
- Move `View Text` / extracted corpus text behind a secondary diagnostics/fallback menu.
- Preserve current corpus text selection/highlight behavior when fallback/diagnostic text is opened.

Backend tasks:

- Enforce available-descriptor identity requirements.
- Enforce source HTML route identity validation.
- Preserve SEC inline styles and browser-default behavior unless a sanitizer rule requires removal.
- Continue stripping hidden iXBRL metadata and active content.
- Return lazy descriptor metadata with stable identity fields.
- Ensure redirect-materialized SEC HTML is sanitized/hash-bound before the same-origin route returns it.
- Split route-bound descriptor verification from materialized identity; parent-side DOM instrumentation requires the materialized identity state.

Acceptance:

- Current app reader screenshot is visually compared to direct SEC URL and same-origin source HTML route.
- Filing iframe width meets the measurable layout gates.
- Sidecar collapsed view is within 10% of direct same-origin source route width.
- Sidecar open view still satisfies minimum filing width gates.
- No prominent corpus/debug product mode is shown in the primary reader.
- Existing tests for document loading and corpus fallback continue to pass.
- Security tests prove raw SEC bytes are never returned from the app origin on redirect materialization.
- Tests that previously asserted raw SEC redirect passthrough are updated to assert sanitized/hash-bound redirect materialization and allowlisted response headers.

### Phase 2 - Quote-Based Visible Selection

Goal: let the analyst ask about or note visible filing text without pretending exact corpus offsets exist.

Tasks:

- Introduce the v2 anchor union across frontend context, chat seeding, and note creation.
- Lock offset-frame fields before extracting `ReaderBridge`: corpus/API offset-bearing anchors declare `offset_frame`; visible quote anchors declare `visible_text_offset_frame`.
- Capture quote-only visible selections from the same-origin, CSP-constrained source HTML iframe.
- Store visible quote anchors with document identity.
- Allow "Ask about this" and note capture for quote anchors.
- Do not enable exact citation creation unless a backend mapping record proves `exact` or `high` confidence.
- Add route-scoped CSP/security tests proving the source HTML frame cannot execute scripts, submit forms, create nested frames, connect out, or run object/embed content.
- Add tests that projection/restored marks do not run before materialized identity includes `source_html_hash`.

Acceptance:

- User can select text in the filing reader and ask the agent about it.
- The agent receives visible quote, filing identity, and current section/document context.
- No quote-only path fabricates corpus offsets.
- Sanitized SEC content cannot execute active behavior, and parent-created quote anchors remain quote-level unless a real mapping record exists.

### Phase 3 - Research Artifacts And Notes

Goal: make note-taking and artifacts first-class around the filing reader.

Tasks:

- Add note/artifact capture UI tied to visible filing context.
- Persist note anchors as quote/section/document anchors when exact mapping is unavailable.
- Register quote-level evidence through the v2 `reader_anchor` `Excerpt.locator` shape; keep legacy `external_anchor` strings only as read adapters.
- Replace new-write `_filing_anchor_locator` behavior so new evidence registration writes object-form `reader_anchor` locators; update canonical evidence tests that currently assert legacy strings.
- Connect captured artifacts to thesis/report/model-building flows.
- Display citation confidence and anchor type internally where useful, without burdening normal reading.

Acceptance:

- An analyst can read, capture a note, ask the agent, and reuse that artifact in a report flow.
- Stored artifacts include document identity and anchor confidence.
- The user-facing workflow remains filing-first.

### Phase 4 - HTML/Corpus Mapping

Goal: project machine precision back onto the visible reader where safe by preserving the conversion trace from SEC HTML to corpus markdown.

Tasks:

- Extend the Edgarparser/corpus producer contract so the same pipeline that creates corpus markdown emits an HTML↔corpus mapping sidecar.
- Lock the C-contract first: sidecar path (`<canonical>.html_corpus_map.v1.json`), top-level schema, record schema, registry tables, deterministic `mapping_record_id`, invalidation rules, table policy, and legacy backfill policy.
- Lock the upstream producer artifact contract before C0: source identity/hash provenance, visible-text stream algorithm/version, stable section ids, deterministic producer record ids, sidecar atomicity with canonical markdown, and corpus DB migrations.
- Include section id/header, visible-text stream offsets, quote/prefix/suffix, corpus `char_start` / `char_end`, content type, table context where available, parser version, source HTML hash, corpus content hash, sanitizer version, mapping algorithm version, confidence, and diagnostics.
- Persist or ingest mapping sidecars into an authoritative mapping registry keyed by document id, accession, primary URL, source HTML hash, corpus content hash, sanitizer version, parser version, and mapping algorithm version.
- Use post-hoc section-scoped text normalization and quote matching only for legacy/backfill documents whose producer sidecar is missing.
- Require a real `mapping_record_id` before any visible HTML selection stores corpus offsets.
- Treat tables as a separate mapping class: do not infer precise prose offsets for table regions solely from hoisted markdown table text.
- Because current ingestion calls Edgarparser with `include_tables=False`, initial exact/high mappings are prose-only until the producer returns stable table/cell metadata.

Acceptance:

- Freshly ingested filings produce corpus markdown and a mapping sidecar from the same source parse.
- Narrative passages map to corpus char spans where exact/high confidence is proven by the registry.
- Financial table selections degrade to quote-only unless exact mapping is proven.
- Old mapping records become invalid when source HTML hash, corpus hash, sanitizer version, parser version, or mapping algorithm version changes.
- Existing citations remain trustworthy.

### Phase 5 - Highlight And Citation Projection

Goal: make agent marks and citations visible in the filing reader.

Tasks:

- Project corpus extraction highlights onto HTML DOM ranges only for exact/high mappings.
- Keep unmapped highlights available in diagnostic corpus view.
- Add diagnostics for unmapped spans.
- Avoid misleading highlights on low-confidence mappings.

Acceptance:

- High-confidence agent marks appear in the visible filing.
- Low-confidence marks do not appear as if they were exact.

## Visual QA Gates

Required captures for every visual review:

- Direct SEC primary document URL.
- Same-origin sanitized source HTML route.
- Embedded filing reader with sidecar collapsed.
- Embedded filing reader with sidecar open.

Artifact convention:

- During local iteration, write visual QA artifacts to `/tmp/f156-visual-review-<YYYYMMDD-HHMMSS>/`.
- Each run should include `metrics.json`, `sec-direct.png`, `source-route.png`, `embedded-collapsed.png`, and `embedded-sidecar-open.png`.
- If a review result needs to be preserved in-repo, copy the run into `docs/planning/artifacts/f156/<YYYY-MM-DD>/` with a short `REVIEW.md`.

Required metadata for every capture:

- viewport width/height
- app shell/global nav width
- filing iframe rect
- filing document body/client width
- filing document scroll width
- first major financial table scroll width
- sidecar width and state

Required target sections:

- MSFT 2Q25 cover page first viewport.
- MSFT 2Q25 `Part I, Item 1. Financial Statements`.
- MSFT income statement table.
- MSFT balance sheet table.
- One narrative-heavy 10-K Item 1A.
- One inline XBRL-heavy filing.

Pass/fail rules:

- Embedded sidecar-collapsed filing width is within 10% of same-origin source route width at the same viewport.
- Embedded sidecar-open filing width meets desktop minimum gates.
- Financial tables do not wrap numeric columns differently from the source route unless the source route also requires horizontal scrolling.
- App chrome does not occupy more vertical space than the compact reader toolbar before the filing starts.
- Corpus/extracted text fallback is not a primary toolbar peer.
- Screenshots and metrics are stored with the review result.

## Architecture Review Gates

An adversarial reviewer should fail the plan or implementation if:

- `status: available` source HTML descriptors omit document id, accession, primary URL, corpus hash, or sanitizer version.
- The source HTML endpoint serves without authoritative identity validation.
- The route can bind a valid SEC HTML file to the wrong corpus hash/document id.
- Redirect materialization returns raw SEC HTML from the app origin instead of sanitized/hash-bound source HTML.
- Redirect materialization preserves upstream `Set-Cookie`, upstream CSP, or non-allowlisted response headers.
- Scripts can run in the same document as SEC markup.
- The parent trusts messages/events from source markup instead of reading verified same-origin selection state itself.
- Parent-side selection capture, projection, restored marks, scroll-spy, or visual snapshots run before materialized identity includes `source_html_hash`.
- Quote-only selections can enter corpus-offset persistence paths.
- Offset-bearing anchors omit `offset_frame`, or visible quote anchors omit their visible-text offset frame.
- Exact/high mapping can be persisted before the authoritative mapping registry exists, or without source HTML hash, corpus hash, sanitizer version, parser version, mapping version, and a real mapping record id.
- The implementation treats client-side text matching as the primary exact-mapping authority instead of producer-emitted sidecars plus registry validation.
- New evidence registration code depends on legacy `external_anchor` string prefixes instead of the v2 `reader_anchor` locator contract.
- Table-cell evidence can cite a parsed value from edgar-financials without proving the returned table payload matches the exact materialized reader filing.
- A durable citation or artifact stores viewport pixels, screenshots, or bounding rects as its authoritative anchor instead of a `DocumentAnchor` plus table/prose provenance.
- Direct SEC subresources are enabled without an explicit proxy/privacy exception and test coverage for the leakage boundary.
- Existing corpus annotations/highlights become unreachable before replacement visible-reader workflows exist.

## Testing Strategy

Unit tests:

- Document response normalizer accepts lazy source HTML descriptors only when required identity fields exist.
- Filing documents default to the human filing reader when source HTML is available.
- Fallback extracted text remains available without being the primary reader mode.
- Quote-only selections cannot call corpus-only annotation paths.
- Exact/high mappings are required before corpus offsets are persisted from HTML selections.
- `FilingMappedAnchor` requires a non-null `mapping_record_id`.
- Offset-bearing anchor validators reject missing or invalid `offset_frame`.
- Table-cell anchor validators reject missing `table_value_source`, value filing identity, resolver version, or `reader_source_html_hash`.
- Producer-emitted mapping sidecars invalidate when source HTML hash, corpus content hash, sanitizer version, parser version, or mapping algorithm version changes.
- Source HTML route rejects mismatched document id/corpus hash.
- Source HTML metadata endpoint returns materialized identity and rejects the same mismatches as the HTML route.
- CSP/sanitizer removes active content while preserving safe inline table styles.
- Source HTML route CSP explicitly includes `script-src 'none'`, `object-src 'none'`, `connect-src 'none'`, and `frame-src 'none'`.

Integration tests:

- Open MSFT filing from Research Workspace and verify source HTML iframe loads.
- Enter the filing reader shell and verify reduced chrome.
- Collapse/expand agent sidecar and verify the filing canvas resizes without losing state.
- Open fallback extracted text and verify existing selection/highlight behavior.
- Verify source identity fields round-trip through document response and source HTML route.
- Verify the bridge/parent fetches materialized source HTML identity before creating durable visible-reader anchors.
- Verify parent-side projection/restoration/scroll-spy does not run when only route-bound identity exists.
- Verify fresh corpus ingestion can produce canonical markdown plus a mapping sidecar from the same source parse.
- Verify selected visible filing passages create quote-level anchors and the backend rejects `filing_mapped` artifacts until a mapping registry can validate exact/high producer-backed corpus mapping records.
- Verify table-cell selection either resolves through server-authorized same-filing `get_filing_tables` provenance or rejects/degrades when edgar-financials returns missing/mismatched accession or primary-document identity.
- Verify overlay go-to links recompute current rects through `ReaderBridge` after scroll/resize and never rely on persisted pixel coordinates.

Visual tests:

- Capture the four required visual surfaces at desktop wide, desktop 1440, tablet, and mobile/narrow.
- Store screenshots and metrics for reviewer inspection.
- Fail on width/table/chrome/corpus-affordance violations.

Security tests:

- Source scripts do not execute.
- Redirect-materialized source HTML is sanitized, hash-bound, and CSP-bound; raw SEC bodies are never served from the app origin.
- Redirect-materialized responses strip upstream cookies/headers and use app-owned CSP/identity/cache headers.
- Inline event handlers are stripped.
- Forms are inert.
- `javascript:` URLs, `<base>`, `meta refresh`, active embeds, and unsafe resource loads are stripped or neutralized.
- The source HTML route CSP blocks scripts, forms, popups/top navigation, object/embed content, nested frames, and network connects from the filing document.
- The iframe is intentionally same-origin and unsandboxed so the parent can read selection state and inject inert marks; tests should assert parent access works only for the verified same-origin source route.
- Any future bridge validates source/session/document identity before accepting messages.
- SEC source content cannot post or synthesize a trusted selection/reader-action event.
- Remote SEC resources obey the chosen policy: blocked/proxied by default; any direct SEC-host exception requires explicit leakage-boundary tests.

## Acceptance Criteria

F156 is successful when:

- Opening the MSFT filing in Research Workspace presents a human-readable filing view that is visually comparable to the SEC browser view.
- The filing, not the corpus, is the primary human surface.
- The agent can sit alongside the filing without making it unreadable.
- Notes, quotes, citations, and research artifacts attach to stable document identity.
- Corpus text remains available for machine retrieval, citation offsets, diagnostics, and fallback.
- The UI does not pretend quote-only anchors are exact corpus spans.
- Source HTML is sanitized, same-origin, cached/provenanced, and isolated from app auth state.
- Reviewer findings from visual/product and adversarial architecture review have no unresolved blockers.
