# F156 Reader Implementation Plan (wave-by-wave)

**Status:** Active — waves 1-13 implemented/reviewed through Wave D; E-pre-1 upstream table identity and E-pre-2 local table provenance authority are implemented; Wave E MVP is implemented in this repo and pending final live/reviewer pass.
**Date:** 2026-05-28
**Derives from:** `F156_READER_SYSTEM_ARCHITECTURE.md` (L0–L8, Codex PASS) + `F156_READER_AGENT_INTERFACE_SPEC.md` (Codex PASS) + `F156_READER_ON_TOP_LAYER_SPEC.md`.
**Visual target:** `docs/design/research-reader-on-top-preview.html` is the repo-local reader preview for the on-top layer, paper-on-desk framing, quiet agent annotations, and rail relationship. `docs/design/research-workspace-preview.html` remains the broader workspace preview, not the primary F156 reader target.

## Working mode

- **Plan each wave → Codex review → PASS → hand to an implementation batch.** Do not implement waves one at a time inline.
- Reviews use the `/codex` CLI (auth via `~/.codex/auth.json` — working). The Codex **MCP write-path needs re-login** (token refresh failed 2026-05-28) before any batch implement.
- Every wave plan must respect the invariants: HTML spine unrestyled, bridge-only coupling (consume `ReaderBridge`, never reach around it), alignment-not-drift, honest confidence, F156 width gates.
- Coordination: a parallel session currently holds `AgentPanel.tsx`, `ResearchListView.tsx`, `ResearchWorkspacePhase2/3.test.tsx` dirty. Any wave touching those must coordinate.

## Wave status

Dependency order (revised after adversarial review — blocker gates inserted):

| # | Wave | What | Plan | Collision risk |
|---|---|---|---|---|
| 1 | **S0** | source HTML safety gate: redirect sanitization + materialized identity before DOM instrumentation | IMPLEMENTED | route + `SourceHtmlPane` |
| 2 | **A1** | "paper on a desk" framing | IMPLEMENTED | none (CSS on `SourceHtmlPane` container) |
| 3 | **S1** | contract lock: v2 anchor/offset-frame, render-surface adapter, quote-level `Excerpt.locator` | IMPLEMENTED | connectors + services + docs/tests |
| 4 | **Perception chain** | `document_context` via `context` → consume | IMPLEMENTED | cross-repo runtime transport |
| 5 | **Reader shell/layout** | URL-addressable first-class reader shell + sidecar width gates | IMPLEMENTED | route/layout live; keep width gates in visual QA |
| 6 | **ReaderBridge extraction** | extract the bridge module from `SourceHtmlPane` (§0.7 enforcement) — **prereq for A2 + B** | IMPLEMENTED | bridge extracted + lint boundary |
| 7 | **A2** | action-surface rebind (overlay Ask/Save/Flag + agent-mediated rich) | IMPLEMENTED | overlay/agent-first actions live |
| 8 | **`reader_action` channel** | typed transient stream events: emit (runtime) + parse (`chatStreamPayloads`) + project hook — **prereq for B** | IMPLEMENTED | cross-repo runtime + frontend replay live |
| 9 | **B** | findings→projection feed + alignment-boundary enforcement | IMPLEMENTED | quote/confidence-scoped projection live |
| 10 | **C-contract** | mapping sidecar + registry schema/API design gate | IMPLEMENTED-MVP | producer identity fields still required from upstream |
| 11 | **C0** | corpus producer mapping implementation (parser emits HTML↔corpus sidecar while building markdown) | IMPLEMENTED-MVP | prose-only, table exactness deferred |
| 12 | **C** | authoritative mapping registry (`mapping_record_id`) stores producer-emitted mappings + legacy backfill | IMPLEMENTED-MVP | durable `filing_mapped` accepted only when registry-backed |
| 13 | **D** | perceptual bridge (viewport awareness + audit trail) | IMPLEMENTED | accepted posture A: visible-section read trail, no dwell/read-time |
| 14a | **E-pre-1** | upstream edgar-financials identity-bound domestic table lookup | IMPLEMENTED-CROSS-REPO | Edgar_updater now returns and validates domestic table filing identity |
| 14b | **E-pre-2** | server-authorized table-cell provenance + artifact/registry guard | IMPLEMENTED | this repo; browser candidates are not citation authority |
| 14c | **E** | on-demand rendered-table bridge (tables, alignment-law) | IMPLEMENTED-MVP | DOM localization candidate + server resolver; vision remains optional helper |

Critical dependencies: **S0 precedes any new iframe DOM instrumentation or projection work** because the same-origin/no-sandbox model is only safe after redirect materialization is sanitized and materialized identity is verified. **S1 precedes both perception consumption and `ReaderBridge`** because the live `document_context` and bridge API must be typed against the locked v2 anchor/render/evidence contracts. **A2 and B both consume `ReaderBridge` (wave 6)** — extract it first or they re-embed bridge logic. **A2's ReaderBridge dependency is hard, not "ideal."** **B consumes the `reader_action` channel (wave 8)** — without it there's nothing to project. B does **not** need C0/C (mapping producer/registry) because transient projection is quote/confidence-scoped, not exact-mapped, but it does require the S1/ReaderBridge projection-result schema. Durable exact `filing_mapped` citations need **C-contract → C0 → C**: lock the sidecar/registry contract, have the parser/corpus producer emit the mapping sidecar, then have the registry validate and mint `mapping_record_id`.

Wave E has an additional fail-closed dependency chain from the accepted D/E supplement: **E-pre-1a (Edgar_updater accession-bound domestic table identity) + E-pre-2 (this repo's server-authorized table-cell provenance path) → E (rendered-table bridge)**. The MVP now consumes those authorities: the browser/ReaderBridge submits table localization candidates only, and the backend resolver mints exact/high table evidence only after same-filing parsed-table provenance is proven. Missing or mismatched identity still degrades to quote/section.

---

## S0 — source HTML safety gate  ·  IMPLEMENTED

**Why:** the same-origin/no-sandbox iframe is intentional, but that makes the source route the security boundary. The plan previously stated that redirect materialization was safe; the code reality is stricter: `routes/research_content.py:_materialize_source_html_redirect` server-fetches allowed SEC Archives redirects and currently returns `final_response` bytes. That path must not bypass the sanitizer/materialized-identity/hash pipeline. Separately, `SourceHtmlPane` can hold `verification.status === 'verified'` with `sourceHtmlHash: null`; selection capture checks the hash, but inert projection/restored-anchor instrumentation currently keys mostly on `verified`.

**Plan:**
1. **Redirect materialization must sanitize or fail closed.** If the upstream source-html endpoint returns an SEC Archives redirect, the app proxy may server-fetch it, but the fetched body must run through the same sanitizer, CSP/header builder, identity binding, and source-html-hash materialization path as non-redirect source HTML. Returning raw SEC bytes from the same-origin route is a fail condition.
2. **Replace the existing raw-redirect tests.** `tests/routes/test_research_content.py` currently asserts the unsafe passthrough behavior; S0 must replace that expectation. Redirect tests must assert the app route uses an allowlisted source-html response header builder, strips `Set-Cookie`/upstream CSP/content type surprises, emits app-owned CSP, emits `X-Source-Html-Hash`, and returns sanitized/materialized reader HTML.
3. **Split verification states.** Replace the ambiguous `verified` state with at least `route_bound` and `materialized_identity_verified`. `route_bound` proves descriptor URL params match; only `materialized_identity_verified` proves `source_html_hash`, sanitizer version, final primary URL, document id, accession, and corpus hash.
4. **Gate all DOM instrumentation.** Selection capture, restored quote marks, projected corpus/agent marks, scroll-spy, visual snapshots, and any future parent-side DOM mutation require `materialized_identity_verified`. Basic iframe display may load in route-bound state, but the parent must not inject marks or read durable anchors until the hash-backed identity is present.
5. **Tests.** Add route tests proving SEC redirect materialization goes through sanitizer/CSP/hash and rejects unsafe redirects; add `SourceHtmlPane` tests proving projection/restoration do not run when `sourceHtmlHash` is missing.

**Acceptance:** a redirected SEC filing still renders faithfully, but the response is sanitized, CSP-bound, identity-hashed, and metadata-verifiable; no parent-side instrumentation runs with `sourceHtmlHash: null`.

---

## Wave A1 — "paper on a desk" framing  ·  IMPLEMENTED

**Goal:** frame the faithful white SEC iframe as a deliberate document inset on a dark desk (per `docs/design/research-reader-on-top-preview.html` + DESIGN.md), without restyling the filing content, touching no logic, and respecting F156 width gates.

**File:** `frontend/packages/ui/src/components/research/SourceHtmlPane.tsx` — render block ~lines 1214–1227. **Two className changes only:**

1. Stage container: `relative min-h-0 flex-1 bg-white` → `relative min-h-0 flex-1 overflow-auto bg-background p-4 sm:p-6`
2. Iframe className: add `block rounded-[6px] border border-border` + shadow `shadow-[0_28px_64px_-24px_rgba(0,0,0,0.66),0_3px_10px_-2px_rgba(0,0,0,0.45)]`, remove `border-0`; keep `block h-full min-h-0 w-full bg-white transition-opacity duration-150 {opacity}`.

**Constraints / acceptance:**
- No `max-width` (would undercut the F156 ≥80%-viewport gate on wide screens — Codex verified px-4→6 keeps the iframe ~1392–1408px at 1440px collapsed, above both 80% (1152) and the visual spec's stricter ≥90%-of-source-route (1296)).
- No CSS injected into the iframe document; `src` stays the source-html route. No logic/hook/selection/projection/verification changes. No other file (esp. **not** `AgentPanel.tsx`).
- `block` on the iframe prevents inline-baseline whitespace → stray outer scrollbar (Codex catch).
- Loading/error states + the absolute `SourceHtmlFrameStatus` overlay still render correctly (overlay may sit over the desk inset during load — acceptable).

**Tests:** `SourceHtmlPane.test.tsx` + `e2e/tests/research-reader-visual-review.spec.ts` width/chrome gates must still pass (visual spec measures the `source-html-frame` bounding box; no hardcoded class/screenshot diff to break).

**Codex review:** PASS with the two fixes above folded in (`block`, exact shadow tokens). No `max-width`, no document CSS injection, no logic changes.

---

## S1 — contract lock: anchors, render surfaces, and evidence locators  ·  IMPLEMENTED

**Why:** the docs and code currently drift on three contracts: the public render surface (`primary_reader` target vs current `render_surfaces.source_html`), the v2 anchor union (target full union vs frontend `FilingQuoteAnchor | FilingMappedAnchor`), and canonical evidence locators (quote-level `Excerpt.locator` target vs current service-specific `external_anchor` string). If the bridge or perception chain is extracted before this is locked, every later wave bakes in a different coordinate system.

**Plan:**
1. **Render-surface adapter:** keep accepting current `render_surfaces.source_html` / `render_surfaces.corpus_text`, but normalize internally to the target `primary_reader` / `diagnostic_surfaces` shape. Do not require every backend caller to switch in one step.
2. **v2 anchor schema:** define the shared discriminated union in the connector package first. Offset-bearing anchors must declare their offset frame (`corpus_doc` or `api_excerpt`); visible filing quote anchors must declare their visible-text frame (`source_html_visible_text_v1`) on `VisibleTextAnchor`; non-offset section/document anchors do not pretend to have corpus offsets.
3. **Backend validator parity:** align `services/reader_artifacts.py`, frontend serializers, and replay normalizers with the same schema. `filing_mapped` is schema-valid but only persists when a registry-backed `mapping_record_id` validates with `offset_frame: 'corpus_doc'`.
4. **Quote-level evidence locator:** replace `_filing_anchor_locator` new-write output with the discriminated `reader_anchor` object for quote and mapped anchors. Existing `external_anchor` / `text_range` string locators remain read-only compatibility input. Update tests that currently assert legacy string locators (including `tests/routes/test_research_content.py`) to assert object-form locators for new registrations.
5. **Projection feed schema:** replace the current bare `ProjectedCorpusHighlight` feed with `ReaderProjectionInput` / `ReaderProjectionResult` types owned by `ReaderBridge` (schema below). Badges and confidence UI render from the result's `projection_confidence`, not from the original corpus/tool confidence.
6. **Tests:** type/normalizer tests for quote and mapped anchors; backend validator tests for missing offset frame, missing materialized identity, missing mapping record id; evidence registration tests for `registered_quote` locator shape; projection schema tests for table degradation and confidence downgrade.

**Acceptance:** a selected filing quote serializes, persists as a reader artifact, registers into canonical evidence, reloads, and rehydrates through one v2 schema; mapped anchors persist only when backed by an active mapping registry record; projection callers cannot submit raw char offsets without an anchor, frame, and diagnostics path.

## Perception chain — `document_context` gateway → consume  ·  IMPLEMENTED

**Grounding (verified 2026-05-28):** the frontend `GatewayService.ts:302` already sends `{messages, context, metadata}`, and `useResearchChat` puts `document_context` in **`metadata`**. The gateway `ChatRequest` (`agent-gateway/server.py:129`) is `{messages, user_id, request_id, context, model}` — **no `metadata` field**, so Pydantic drops it; but `context` IS preserved and already consumed by the runtime (`_resolve_chat_profile_name(context)`, `context["channel"]`). So the fix routes through the surviving `context`, **not** a new field.

**Reconciled transport rule:** `context.document_context` is the live request transport. `message.metadata.document_context` is the persistence/replay/audit location after the turn is stored. Do not add a second live gateway contract unless the gateway/runtime is deliberately versioned to support it.

**Plan (4 links):**
1. **Send via `context`:** put the serialized `document_context` into `context.document_context` (the surviving channel) in `useResearchChat`/`GatewayService` instead of (or alongside) `metadata`. Smallest frontend change; no new gateway field.
2. **Preserve through runtime:** thread `context.document_context` from the gateway turn inputs to the prompt-assembly point (context already flows for profile/channel).
3. **Persist on the user message:** store `document_context` on the persisted research message (live turns save only user text — `runtime.py:198`) so it's replayable/auditable.
4. **Inject into the prompt:** when `context.document_context` is present, add the reader-context block (doc identity, section, selected text, anchor kind + confidence, verified-vs-prompt-only) per agent-interface §3.

**Constraints:** selected filing text is untrusted quoted data (prompt-injection). Cross-repo (AI-excel-addin gateway + runtime — follow sync rules); the send is risk_module. No reader-UI collision. Consumes S1 schema; do not ship prompt consumption against the legacy metadata-only shape.
**Acceptance:** asking with a selection puts the selected text + v2 anchor + section + verified/materialized identity state into the assembled prompt via `context.document_context` (runtime/prompt test asserts it). Frontend tests update away from metadata-only transport and cover quote, mapped-shape, legacy, and verified-identity context.

## Reader shell/layout — first-class filing reader  ·  IMPLEMENTED

**Why:** the SEC reader spec requires a URL-addressable first-class reader shell, but A1 is only CSS framing around the iframe. This wave makes the product scope explicit instead of hiding shell/layout inside A1 or workspace work.

**Plan:**
1. **Route/shell:** use or complete the existing reader URL shape (`#research/:ticker/reader/:source_type/:source_id`) as the canonical human filing reader entry. Back navigation returns to the originating research workspace state.
2. **Dominant canvas:** the filing receives the primary width. Workspace navigation, tabs, debug controls, and dense dashboard chrome are reduced or removed in reader mode.
3. **Agent sidecar:** desktop opens the analyst rail by default when no preference exists, then persists open/closed state per session/source; compact layouts collapse or clamp the rail when the filing would fall below minimum width.
4. **Diagnostics:** corpus/extracted text is behind a secondary diagnostics/fallback menu, not a peer reader toggle.
5. **Visual QA:** compare the reader shell to the same-origin source-html route and direct SEC URL at desktop wide, 1440, tablet, and narrow/mobile.

**Acceptance:** collapsed shell iframe width is within 10% of the same-origin source route at the same viewport and at least 80% of desktop viewport width; sidecar-open shell still satisfies the SEC spec's minimum width gates; the route is addressable/reloadable; the filing appears as the primary reader, not a dashboard panel.

**Implementation status (2026-05-29):** implemented, not dropped. The canonical hash route is `#research/:ticker/reader/:source_type/:source_id`; `hashSync` builds/parses it, `ResearchWorkspaceContainer` loads the routed document, and `ResearchWorkspace` renders a fixed full-viewport document-reading shell with a width-gated analyst rail. Product deviation from the earlier default-collapsed note: desktop reader sessions open the analyst rail by default when no saved preference exists, then persist open/closed preference; compact/narrow layouts still collapse when needed for filing readability. A2/B overlays currently improve that first-class reader shell, not the older dashboard panel.

## ReaderBridge extraction — the §0.7 enforcement module  ·  IMPLEMENTED

**Why:** the dual-representation invariant is unenforced today — bridge logic (selection capture, `mapVisibleQuoteToCorpus`, `projectCorpusHighlightsInDocument`) lives embedded in `SourceHtmlPane.tsx`. A2 and B both must *consume* the bridge; without a module they'd re-embed logic and re-violate the invariant.
**Module path:** `frontend/packages/ui/src/components/research/readerBridge/` with shared anchor types imported from `@risk/connectors`.
**Public contract:**
- `MaterializedReaderIdentity` input requires `source_id, document_id, accession, primary_document_url, corpus_content_hash, sanitizer_version, source_html_hash, verified_at`.
- `resolveVisibleSelection({ ownerDocument, identity, sectionAnchors, activeSection }) -> FilingQuoteSelection | null`; fails closed unless identity is materialized.
- `projectReaderAnchors({ ownerDocument, identity, corpusSection, inputs }) -> ReaderProjectionResult[]`; owns all DOM mark creation/removal and table degradation.
- `restoreVisibleAnchor({ ownerDocument, identity, anchor }) -> ReaderProjectionResult`; same identity gate and diagnostics.
- `mapVisibleQuoteToCorpus(...) -> MappingPreviewResult`; diagnostic only until C registry exists, never authoritative for durable `filing_mapped`.
- `deriveCorpusContentRegions(corpusSectionText) -> ContentRegion[]`; derives prose/table regions from `### TABLES` / markdown table structure until producer metadata exists.

**Shipped API note (2026-05-29):** the implemented bridge keeps `SourceHtmlPane` as the legitimate iframe DOM host and exposes the bridge primitives consumed by that host: `buildVisibleQuoteAnchor`, `rangeContextText`, `mapVisibleQuoteToCorpus`, `projectCorpusHighlightsInDocument`, `projectReaderActionsInDocument`, `restoreQuoteAnchorInDocument`, and `deriveCorpusContentRegions`. Earlier placeholder names (`resolveVisibleSelection`, `projectReaderAnchors`, `restoreVisibleAnchor`) describe the same boundary but are not the shipped export names.

**Projection schema:**

```ts
interface FilingQuoteSelection {
  tab_id: string;
  selected_text: string;
  section_header?: string | null;
  anchor: FilingQuoteAnchor;
  rect?: { top: number; left: number; width: number; height: number } | null;
}

type ContentRegionType = 'prose' | 'table' | 'heading' | 'footnote' | 'unknown';

interface ContentRegion {
  type: ContentRegionType;
  char_start: number;
  char_end: number;
  reason?: string | null;
}

interface ReaderProjectionInput {
  id: string;
  source: 'annotation' | 'langextract' | 'agent_transient' | 'restored_selection';
  persistence: 'durable' | 'transient';
  anchor: DocumentAnchor;
  label?: string | null;
  requested_confidence: 'exact' | 'high' | 'quote' | 'section_only' | 'none';
}

interface ReaderProjectionResult {
  input_id: string;
  status: 'projected' | 'degraded' | 'skipped';
  projection_confidence: 'exact' | 'high' | 'quote' | 'section_only' | 'none';
  content_type: 'prose' | 'table' | 'heading' | 'footnote' | 'unknown';
  diagnostics: string[];
  downgrade_reason?: 'missing_identity' | 'offset_frame_mismatch' | 'table_region' | 'quote_not_found' | 'stale_source' | null;
  mark_ids?: string[];
}

interface MappingPreviewInput {
  identity: MaterializedReaderIdentity;
  filing_anchor: FilingQuoteAnchor;
  corpus_section_text: string;
  corpus_section_start: number;
  content_regions: ContentRegion[];
}

interface MappingPreviewResult {
  status: 'mapped' | 'unmapped' | 'degraded';
  confidence: 'high' | 'quote' | 'section_only' | 'none';
  char_start?: number;
  char_end?: number;
  offset_frame?: 'corpus_doc';
  diagnostics: string[];
}
```

**Plan:** extract the module above out of `SourceHtmlPane`. `SourceHtmlPane` becomes the DOM host that passes `contentDocument` and materialized identity into the bridge; L4/L5 import the bridge API and result types, **never** the iframe DOM or corpus offsets directly. Add a lint/import-boundary rule.
**Constraints:** pure refactor — no behavior change; runtime still builds `filing_quote` (mapper stays preview/`__testing` until C). Requires S0 and S1 so the extracted module cannot inherit the unsafe `verified-with-null-hash` state or the drifting anchor contract. **Coordinate** (`SourceHtmlPane`).
**Acceptance:** `SourceHtmlPane.test.tsx` passes with equivalent behavior; projection tests prove table-region degradation, offset-frame mismatch skipping, stale-source skipping, and confidence downgrade diagnostics; lint rule fails if an L4/L5 component imports iframe-DOM/corpus internals directly. Implemented enforcement lives in `frontend/.eslintrc.js`, with `ReaderBridgeBoundaryLint.test.ts` proving L4/L5 direct iframe/corpus imports fail, `readerBridge` imports pass, and `SourceHtmlPane` remains exempt as the DOM host.

## A2 — action-surface rebind  ·  IMPLEMENTED

**Grounding:** the selection action surface exists **twice** — DocumentTab toolbar (`DocumentTab.tsx:455-475`: `AskAboutThis` + "Start thread →" + more) and the ReaderArtifactPanel rail card (`ReaderArtifactPanel.tsx:249-265`: RailButtons "Ask analyst" / "Save note" / "Save quote" / …).

**Plan:**
1. Add the **minimal selection overlay** (Ask / Save / Flag) anchored near the selection (parent overlay), consuming existing selection state (`textSelection` / `filingQuoteSelection`).
2. **Remove** the rich rail action-card buttons (ReaderArtifactPanel) and the toolbar selection actions (DocumentTab), keeping the *handlers* (`saveArtifact`, note draft, etc.) reachable via the overlay's Save + the agent path.
3. **Rich/typed actions → agent-mediated** (save-to-thesis, compare via the agent's existing tool capabilities, not buttons).
4. Rail returns to conversation + context + recent-artifacts list.

**Constraints:** capabilities preserved (only entry points move; don't delete `reader_artifacts`/evidence/promotion handlers). Consume the `ReaderBridge`. **Coordinate** — touches `DocumentTab`/`ReaderArtifactPanel`/`SourceHtmlPane` (parallel-session + Codex files) and must reconcile with what Codex's batch wrote into `F156_READER_ANALYST_NOTE_LAYER_SPEC.md` (its rich rail card vs our supersession).
**Depends on:** A1 (visual), S0, S1, Reader shell/layout, and the `ReaderBridge` extraction. The ReaderBridge dependency is hard.
**Acceptance:** selection shows the minimal overlay; rail has no rich action-card; "save to thesis" works via the agent; capabilities intact.

## `reader_action` transient stream channel — emit + parse + project  ·  IMPLEMENTED

**Why:** B projects the agent's transient marks, but there's no channel — `chatStreamPayloads.ts` has no `reader_action` event type and the runtime emits none.
**Plan (agent-interface §4):** (1) **emit** a typed, schema-validated `reader_action` stream event (`{action, anchor, label?, confidence, source:'agent'}`) from the runtime — NOT embedded in assistant prose (injection-safe); (2) **parse** it in `chatStreamPayloads.ts` (today unknown chunks are ignored) — schema-validated, logged to message metadata for replay; (3) **project** validated events via the `ReaderBridge` (wave 6). Directive handlers **forbidden from durable writes**.
**Constraints:** cross-repo (emit = AI-excel-addin runtime) + coordinate (parse/project = risk_module). Transient, non-persistent, no state-write.
**Depends on:** `ReaderBridge` (wave 6).
**Acceptance:** an emitted `reader_action` parses + validates + projects a transient mark; a malformed/prose-embedded one is rejected; no durable write occurs.

## B — findings→projection feed + alignment-boundary enforcement  ·  IMPLEMENTED

**Grounding:** `buildProjectedCorpusHighlights` (`DocumentTab.tsx:125-159`) feeds projection from **stored annotations + langextract extractions only**. `projectCorpusHighlightsInDocument` (`SourceHtmlPane.tsx:759`) projects any offset in the active section — **no table guard**.

**Plan:**
1. **Findings→projection feed:** extend the projection feed to accept the agent's transient `reader_action` events (agent-interface §4) — agent-emitted marks (anchor + confidence) projected alongside annotations/extractions. The connective tissue that makes the agent-first journey render.
2. **Alignment-boundary guard:** in `projectCorpusHighlightsInDocument`, project corpus offsets only on prose; on table regions **degrade to section/quote**, don't project a precise mark. *Table-range source:* `DocumentSection` is only `{text,start,end}` — no table metadata exists, so table ranges must be **derived from markdown-table parsing of the corpus section** (`### TABLES`/pipe-row structure). State this in the build; don't assume table metadata is present.

**Constraints:** go through the `ReaderBridge` (projection + agent-action ingestion); honest confidence. **Coordinate** — shared reader files (`DocumentTab`/`SourceHtmlPane`) + stream/store surfaces.
**Depends on:** the `reader_action` channel (wave 8, emit+parse) and the `ReaderBridge` module (wave 6). Does **not** depend on C.
**Acceptance:** an agent transient highlight renders on prose; a table-region corpus offset degrades (no misaligned mark); regression test (prose projects, table degrades).

**Implementation status (2026-05-29):** implemented. The grounding above was the pre-wave gap; projection now flows through ReaderBridge and table-region corpus offsets degrade instead of projecting exact DOM marks.

## C-contract — mapping sidecar and registry design gate  ·  IMPLEMENTED-MVP

**Why:** C0-before-C is the right implementation dependency for exact mapped citations, but C0 cannot start until the sidecar and registry contract are concrete. Otherwise the producer emits an artifact the registry cannot validate or invalidate.

**Locked target unless explicitly revised:**
- **Sidecar file:** co-written next to the finalized canonical markdown using the same basename and suffix `.html_corpus_map.v1.json` (for example, `<canonical>.html_corpus_map.v1.json`). The DB stores the sidecar path for audit; the registry is the query authority.
- **Sidecar top-level schema:** `schema_version`, `document_id`, `accession`, `primary_document_url`, `source_html_hash`, `corpus_content_hash`, `sanitizer_version`, `parser_version`, `parser_schema_version`, `visible_text_offset_frame`, `visible_text_algorithm_version`, `mapping_algorithm_version`, `created_at`, `producer`, `records[]`, `diagnostics`.
- **Record schema:** deterministic `producer_record_id`, `section_id`, `section_header`, `content_type`, `html_anchor` (`visible_text_anchor`, optional DOM/table hints), `visible_text_span` (`offset_frame: 'source_html_visible_text_v1'`, `char_start`, `char_end`), `corpus_span` (`offset_frame: 'corpus_doc'`, `char_start`, `char_end`), `quote`, `text_before`, `text_after`, `confidence`, `producer_trace`, `diagnostics`.
- **Registry storage:** add corpus DB migrations for `html_corpus_mapping_sets` and `html_corpus_mapping_records`. Registry mints an opaque deterministic `mapping_record_id` from the identity tuple + producer record id + mapping version, marks old sets inactive when any hash/version changes, and exposes lookup by visible anchor or corpus span.
- **Upstream producer API:** current `/api/sections` with `include_tables=False` is insufficient. C0 must add or consume an artifact-bundle endpoint/response that returns the sanitized reader HTML identity (`source_html_hash`, `sanitizer_version`, final primary URL), the visible-text stream algorithm/version, stable parser section ids, source HTML byte/hash provenance, and enough parser trace to align each emitted corpus span to visible text.
- **Producer record ids:** `producer_record_id` is deterministic from `(document_id, source_html_hash, corpus_content_hash, parser_version, parser_schema_version, visible_text_algorithm_version, mapping_algorithm_version, section_id, normalized visible text range, corpus span)` so re-ingest is idempotent.
- **Atomicity:** canonical markdown and sidecar are written through the same staging/rename discipline; the DB must never point at a mapping set whose canonical markdown write failed.
- **Table policy:** current ingestion calls Edgarparser with `include_tables=False`; therefore the first C0 implementation is prose/heading/footnote only. Table records must be `content_type: 'table'` with `confidence: 'none'` or absent until the producer endpoint returns stable table/cell metadata. Do not infer precise table offsets from hoisted markdown tables.
- **Backfill:** legacy corpus files without sidecars can be queued for post-hoc matching, but those records are flagged `provenance: 'legacy_backfill'` and cannot outrank producer-emitted exact/high mappings.

**Acceptance:** reviewers can implement C0 and C independently from this contract without inventing storage, IDs, invalidation, table semantics, or lookup shape.

**Implementation status (2026-05-29):** implemented in `core/corpus/html_mapping.py`, `core/corpus/schema.sql`, and migration `0004_html_corpus_mapping.sql`. The locked sidecar suffix is `.html_corpus_map.v1.json`; registry records are keyed by materialized source identity plus corpus hash/parser schema/visible-text algorithm/mapping algorithm identity. The current MVP fail-closes unless the `/api/sections` payload provides `source_html_hash`, `sanitizer_version`, visible-text stream algorithm/frame, parser version/schema, per-section visible-text span, and per-section producer trace; exact citations cannot be minted from section text alone.

## C0 — corpus producer mapping implementation  ·  IMPLEMENTED-MVP (prereq for exact mapped citations)

**Grounding:** the corpus markdown is already derived from SEC/Edgarparser output. `scripts/corpus_ingest_accession.py` calls `/api/sections`, assembles canonical markdown in `_assemble_body_from_api_response`, and `core/corpus/ingest.py` writes the content-addressed file and indexes section offsets. That is the right point to preserve the conversion trace instead of forcing the reader to rediscover it later.

**Approach:** extend the Edgarparser/corpus producer contract so the same pipeline that creates corpus markdown also emits the C-contract HTML↔corpus mapping sidecar. The sidecar is keyed by `document_id, accession, primary_document_url, source_html_hash, corpus_content_hash, sanitizer_version, parser_version, parser_schema_version, visible_text_algorithm_version, mapping_algorithm_version` and contains section-level records:
- `section_id` / `section_header`
- visible HTML text-stream range and quote/prefix/suffix
- corpus `char_start` / `char_end` in the `corpus_doc` offset frame
- content type (`prose`, `table`, `heading`, `footnote`, `unknown`)
- table context when applicable
- confidence and producer diagnostics

**Contract:** producer emits candidate exact/high mappings for prose-like content; registry validates and mints durable `mapping_record_id`; `reader_artifacts` accepts `filing_mapped` only when that ID exists.

**Implementation notes:** current `scripts/corpus_ingest_accession.py` calls `/api/sections` with `include_tables=False`. Do not claim table/cell exact mapping until that producer call or endpoint changes to return stable table metadata. The initial C0 MVP should be prose-only and should explicitly degrade table regions.

**Acceptance:** a freshly ingested filing produces canonical markdown, section offsets, materialized source HTML identity, and a mapping sidecar from the same source parse; re-ingest changes any relevant hash/version and invalidates old mapping records.

**Implementation status (2026-05-29):** `ingest_raw(..., html_mapping_source=...)` now builds the prose-only sidecar from the same canonical markdown/section parse, writes it with the markdown staging/rename discipline, ingests it into the registry inside the DB transaction, and marks superseded mapping sets inactive on re-ingest. `scripts/corpus_ingest_accession.py` passes the exact `/api/sections` response into this path. Tables remain non-exact until the producer returns stable table/cell metadata.

## C — authoritative mapping registry  ·  IMPLEMENTED-MVP

**Why:** a backend subsystem, not a reader edit — unblocks durable exact citations without letting the browser/client mint corpus offsets.
**Approach:** a backend service + store that ingests producer-emitted mapping sidecars as the primary path and optionally computes post-hoc mappings only for legacy/backfill. Records are keyed by `document_id, accession, primary_document_url, source_html_hash, corpus_content_hash, sanitizer_version, parser_version, parser_schema_version, visible_text_algorithm_version, mapping_algorithm_version`. The client `__testing` mapper (`SourceHtmlPane.tsx:414`) becomes a *diagnostic preview* of the registry, not the authority.
**Contract:** `mapping_record_id` returned → `reader_artifacts` accepts `filing_mapped` (offsets, exact/high confidence, offset-frame recorded).
**Open decisions:** async legacy backfill scheduling, GC policy for inactive mapping sets, and whether legacy backfill can ever produce `high` or only `quote`/`section_only`.
**Implementation status (2026-05-29):** `services/reader_artifacts.py` now validates `filing_mapped` anchors against the authoritative registry before persisting or registering canonical evidence. Registry-backed mapped artifacts retain `mapping_record_id`, `corpus_doc` offsets, parser identity, visible-text algorithm, and mapping algorithm version in the evidence locator and register as `registered_mapped`. `POST /api/research/content/reader-mapping/resolve` is the public resolve surface that turns a verified visible selection plus identity tuple into the registry-backed mapped anchor. The frontend save/flag path now attempts that resolve first and falls back to quote-only when mapping metadata or a registry match is unavailable. Unregistered/stale identity/text mismatches fail closed. The client-side mapper remains diagnostic and is not an authority for durable mapped citations.

## D — perceptual bridge  ·  IMPLEMENTED

**Approach:** a viewport scroll-spy on the same-origin source-HTML iframe maps the visible region → current section/spans, fed into the agent's `document_context` (a `viewport` field) + an audit "read trail."
**Accepted posture:** bounded/disclosed posture A from `F156_READER_DE_DESIGN_SPEC.md`: visible sections + scroll snapshot are attached to the research turn for replay/audit; dwell/read time, per-section first/last timestamps, observation counts, and durable read-trail tables are excluded. A user-facing disclosure is required before any UI surfaces the trail in the multi-user product.
**Depends on:** the perception chain (extends the same `context.document_context` payload).

**Implementation status (2026-05-29):** implemented and review-passed. `SourceHtmlPane` remains the only iframe DOM host and emits a `reader-viewport-v1` context only after `materialized_identity_verified`. The context is deliberately limited to current visible section names/fragments plus scroll dimensions; it does **not** record dwell/read time, per-section first/last timestamps, observation counts, or a durable read-trail table. `ResearchStore` keeps only the latest viewport per document tab, clears it when the document identity changes, `AgentPanel` includes it in the active `document_context`, and `useResearchChat` sends it through both live `context.document_context` and persisted `metadata.document_context`. The audit block is explicit: `scope: visible_sections_only`, `persistence: attached_to_research_turn`, `dwell_time_ms_recorded: false`.

**Acceptance:** scrolling the SEC-faithful iframe updates the active viewport context without injecting styles or marks into the filing; asking the analyst from an unselected filing view includes the currently visible section context; asking with a selected quote includes both the quote anchor and the visible-section viewport context; persisted messages retain the same viewport audit object for replay without per-section temporal trail data.

## E-pre-1 — upstream edgar-financials identity-bound lookup  ·  IMPLEMENTED-CROSS-REPO

**Approach:** `get_filing_tables` remains the primary value source for table-cell citations, but domestic 10-K/10-Q exact table evidence requires accession-bound lookup and returned filing identity. Edgar_updater must return enough identity for the caller to prove same filing: accession, primary document URL or `filing_url`, CIK, form/source, and fiscal period. The reader-local `source_html_hash` is not an Edgar_updater field; it is required by the reader resolver before minting table authority.

**Required upstream work:** write filing identity into domestic table caches, return that identity for domestic reads, and accept/accession-bind domestic table lookup or fail on non-matching accession instead of falling back to ticker/year/quarter best effort. `get_statement`/`get_metric` identity remains secondary/deferrable; E MVP resolves citeable table cells through `get_filing_tables`.

**Acceptance:** a domestic 10-K/10-Q table response carries the resolved filing identity; with accession input, a non-matching accession returns an error; the risk_module resolver can compare returned identity to the materialized reader identity before producing table evidence.

**Implementation status (2026-05-29):** implemented in `Edgar_updater`. Domestic table caches now write/read the `filing` identity block for 10-K/10-Q tables, `/api/tables` accepts domestic `accession`, validates the requested accession against the resolved table cache filing identity, and returns a 400 `filing_identity_mismatch` / `filing_identity_unavailable` instead of falling back to period-keyed best effort. Legacy period-keyed table caches without filing identity are not retroactively blessed; accession-bound reads fail closed unless the cache already carries complete identity. Verified identity requires accession, filing/primary-document URL, CIK, form, and a period signal. `get_filing_tables` forwards domestic `accession` through the MCP proxy. Targeted upstream tests cover identity-bearing success, mismatch fail-closed behavior, incomplete/legacy identity fail-closed behavior, domestic accession forwarding, foreign accession forwarding, table cache identity writing, and ordinary non-accession cache-read immutability.

## E-pre-2 — server-authorized table-cell provenance  ·  IMPLEMENTED

**Approach:** add the local schema/validator/registry path that lets table evidence round-trip only when server-authorized. ReaderBridge can submit a candidate localization, but exact/high table evidence is minted by a backend resolver after same-filing parsed-value validation. Client-provided `table_context` alone is never sufficient.

**Table authority contract:**
- preferred anchor shape: `filing_table_cell`; acceptable interim: `filing_mapped` only if backed by a server-issued table citation authority id and no fabricated corpus offsets;
- provenance includes `table_value_source`, value-source filing identity, reader-local `source_html_hash`, `table_id`, section, row/column indexes and headers, raw cell text, parsed value text and exact numeric string, unit/scale/period/concept, resolver version, mismatch diagnostics, and authority id;
- `reader_artifacts.py` must validate/round-trip table provenance but reject exact/high table evidence without server authority;
- `html_mapping.py` / registry must keep rejecting table records without server-authorized table-cell provenance. If table citations remain inside the mapping registry, they are a distinct table authority path, not ordinary prose corpus-offset mappings.

**Acceptance:** server-authorized table-cell provenance persists and registers as exact/high table evidence; the same payload without authority degrades; ordinary table records without provenance still fail closed.

**Implementation status (2026-05-29):** `services/reader_table_citations.py` now mints server-issued `table_citation_record_id` records only from a trusted server resolver result shape, then performs same-filing checks across anchor accession, primary document URL, reader `source_html_hash`, and raw selected cell text. The resolver result carries parsed-source provenance (`source_record_hash`, value-source filing identity, table/cell identity, parsed value strings, resolver run/version) so arbitrary client-shaped `table_context` cannot mint authority. `services/reader_artifacts.py` accepts `filing_table_cell` only with exact/high confidence, full table context, and a matching server-issued record; client-only or mismatched table context fails closed. Registered table artifacts preserve table provenance in the canonical evidence source record and return `registered_table`. Frontend serializers, replay normalizers, and reader-action projection now understand server-authorized `filing_table_cell` / `registered_table`; unauthorized table evidence still degrades. The existing mapping registry still rejects ordinary table records lacking server-authorized provenance, so table exactness cannot be fabricated through corpus offsets.

## E — on-demand rendered-table bridge  ·  IMPLEMENTED-MVP

**Approach:** analyst explicitly invokes the table action on a visible filing table cell → `SourceHtmlPane` / ReaderBridge captures a rendered DOM table/cell localization candidate in the same-origin iframe without persisting pixels → backend resolver maps that localization to identity-bound `get_filing_tables` data → resolver verifies same filing and reader `source_html_hash` → server-authorized table provenance is registered. Vision/OCR remains an optional future helper for non-DOM charts, images, or ambiguous tables; it never supplies the cited value.

**Law:** alignment-not-drift. Parsed value is authoritative; on parsed-vs-vision mismatch, trust parsed and log diagnostics. If identity or authority is missing, degrade to quote/section.

**Overlay link contract:** the visual overlay link stores the `DocumentAnchor` / artifact id only. Rects, screenshots, and pixel coordinates are recomputed by ReaderBridge from the current same-origin iframe and materialized identity. If the overlay target cannot be restored, the link degrades to section/document navigation; it never becomes a durable citation coordinate.

**Acceptance:** a table-cell selection in the MSFT reader either resolves to a same-accession parsed value with server-issued provenance and a restorable overlay target, or visibly degrades to quote/section-only with diagnostics. Tests cover identity mismatch, missing accession/primary-document/source-html-hash metadata, rendered-candidate mismatch, server-authority guard, and overlay restore after resize/scroll.

**Implementation status (2026-05-29):** `POST /api/research/content/reader-table/resolve` accepts a visible quote anchor plus a rendered table-cell candidate, proves reader document identity from the corpus DB, calls accession-bound `get_filing_tables`, verifies returned filing identity against the materialized filing URL/accession/hash, selects a matching parsed table cell, and mints a `filing_table_cell` anchor through the server table-citation authority. The reader selection overlay exposes this as the on-demand Table action when a selection is inside a table cell. Resolver failure returns a degraded response; the UI saves a quote fallback tagged with a table-resolution gap instead of fabricating exact table evidence. Agent reader actions for server-authorized table cells now project through ReaderBridge by visible quote.
