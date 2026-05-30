# F156 Reader System Architecture (Authoritative)

**Status:** Reconciled v3 — authoritative umbrella architecture, updated for accepted D/E supplement
**Date:** 2026-05-28
**Owner:** Research Workspace / Filing Reader
**Authority:** This is the **single source of truth** for the filing reader system. The documents below hold component detail; where any of them conflict with this doc, **this doc wins.**

| Document | Role under this spec |
|---|---|
| `F156_SEC_HTML_READER_ARCHITECTURE_SPEC.md` | L1 spine detail (sanitizer, CSP, identity, source-html endpoint, anchor union). Authoritative for the spine; subsumed here. |
| `F156_READER_ON_TOP_LAYER_SPEC.md` | L3 bridges + L4 overlay + L5 journey detail. Subsumed here. |
| `F156_READER_ANALYST_NOTE_LAYER_SPEC.md` | L6 artifact/evidence/promotion workflow. Subsumed here — **its rich rail action-card is superseded** (see L4). |
| `F156_READER_AGENT_INTERFACE_SPEC.md` | The L2↔L3↔L5 **operational contract** — how the agent perceives the reader (`document_context`) and acts on it (durable tool calls vs transient typed stream events). Codex-reviewed PASS. |
| `F156_READER_DE_DESIGN_SPEC.md` | Accepted D/E supplement: bounded viewport/read-trail posture A and the split table-vision sequence (`E-pre-1` upstream identity, `E-pre-2` table provenance authority, gated visual bridge). |
| `RESEARCH_SURFACE_DESIGN_ALIGNMENT_PLAN.md` | Workspace fit / navigation around the reader. Consumes this. |
| `docs/design/research-reader-on-top-preview.html` | Canonical F156 reader visual preview for the on-top layer, document framing, quiet annotations, and rail relationship. |
| `DESIGN.md` | Visual grammar. Its "Document Reading Mode" carries the 2026-05-28 SEC-HTML-spine exception. |

---

## 0. Purpose & non-negotiables (L0)

**Purpose.** A human filing reader that doubles as an agent-driven research instrument: the analyst reads the *real* SEC filing, and the agent — the analyst's reading capacity scaled — does the legwork on it under the analyst's direction, with everything it does visible, grounded, and auditable.

**Non-negotiables (bind every layer):**

1. **One reader, HTML spine, on-top overlay.** The sanitized SEC HTML is the visible document; the app never restyles the filing body. Corpus/extracted text is **diagnostic-only, demoted behind a secondary action** (per F156 D1) — never a *peer* reading mode. (As-built still exposes a `ReaderMode = 'source_html' | 'corpus_text'` toggle in `DocumentTab.tsx`; L7 tracks whether its presentation meets the diagnostic-only bar or is still too peer-like.)
2. **Readability never regresses** below opening the filing on SEC.gov. Tables/statements stay faithful. The overlay only *adds*.
3. **Quiet overlay; conversation in the rail.** On the document: highlights + a one-line `⚑ Agent:` annotation + a minimal Ask/Save/Flag chip. Everything conversational lives in the agent rail.
4. **Anchors, not pixels.** The v2 `DocumentAnchor` is the shared coordinate system for both directions — robust and auditable, unlike screen coordinates.
5. **Alignment, not drift.** Any cited number comes from parsed corpus/XBRL; table values additionally require same-filing identity proof. Vision may *localize* but never supplies authoritative figures.
6. **Honest confidence.** The `exact / high / quote / section_only / none` ladder is preserved; never render a quote-only anchor as an exact citation.
7. **Dual representation, bridge-only coupling.** Two clean independent representations (human spine / agent substrate), coupled *only* by the bridge. **Enforcement mechanism (not just an assertion):** the bridge is a dedicated module exposing a typed API (anchor in → mapping/projection out); L4/L5 consume *that module only* and **must not import the iframe DOM (L1) or corpus offsets (L2) directly**. A lint/boundary rule makes it checkable. As of Wave 6, `ReaderBridge` is extracted and `SourceHtmlPane` remains the legitimate DOM host.
8. **Human directs and judges; agent proposes and never decides.** The agent is scaled reading capacity, not an authority. Durable typed conclusions are human-owned.

---

## 1. Architecture at a glance

```
                    ┌──────────────────────────────────────────────┐
   HUMAN  ◀────────▶│  L4 On-top overlay        L5 Agent journey     │
                    │  framing · marks · ⚑callouts ·  agent-first    │
                    │  Ask/Save/Flag · point-to       direct→act→read │
                    └──────────────────────▲────────────────────────┘
                                           │  consume ONLY the bridge
                    ┌──────────────────────┴────────────────────────┐
                    │  L3 BRIDGE                                      │
                    │  semantic · perceptual · visual                │
                    │  + mapping registry · confidence · provenance  │
                    └──────▲──────────────────────────────▲──────────┘
                           │      sole coupling            │
        ┌──────────────────┴─────────┐      ┌──────────────┴──────────────┐
        │ L1 HUMAN SPINE             │      │ L2 AGENT SUBSTRATE           │
        │ faithful sanitized SEC     │      │ corpus + tools · offsets ·   │
        │ HTML + capture/identity    │      │ section map · evidence       │
        └────────────────────────────┘      └──────────────────────────────┘

   L6 Artifact / evidence / promotion — durable, human-approved (reads L2/L3, never L1 directly)
```

**The invariant, drawn:** L1 and L2 are clean and independent; **L3 is the only thing that touches both**; L4/L5 consume L3 and never reach around it to fuse the spine and the substrate.

---

## L1 — Human spine: faithful SEC HTML

**Job.** Render the untouched filing as the visible document, and expose stable identity + captured text so the agent can be grounded.

**Invariants & contracts.**
- Sanitized SEC source HTML served same-origin (`GET /api/research/content/documents/source-html`), embedded in a CSP-constrained, **same-origin (no-sandbox)** iframe so the parent can read selection state and inject inert marks.
- Untrusted-content discipline: sanitizer strips scripts/handlers/forms/active embeds/`<base>`/meta-refresh; route-scoped CSP (`script-src 'none'` … `frame-ancestors 'self'`); SEC inline table styles preserved.
- **Identity is mandatory before "available":** `source_id, source_type, document_id, accession, primary_document_url, corpus_content_hash, sanitizer_version`; materialized identity adds `source_html_hash`. (Detail: `F156_SEC_HTML_READER_ARCHITECTURE_SPEC`.)
- **Redirect materialization is not a sanitizer bypass:** if the app proxy server-fetches an SEC Archives redirect, the fetched body must run through the same sanitizer/CSP/hash/materialized-identity pipeline as ordinary source HTML or fail closed.
- **DOM instrumentation is hash-gated:** basic iframe display can be route-bound, but selection capture, restored marks, projected marks, scroll-spy, visual snapshots, and durable anchors require materialized identity including `source_html_hash`.
- The app **never restyles** the filing body. Framing (L4) sits around it, not in it.

**As-built (verified 2026-05-28; blocker-reviewed 2026-05-29).** Built and in the working tree: faithful reader, same-origin iframe (sandbox dropped), capture of rendered filing text + identity, source-html serving/sanitizer in `AI-excel-addin/api/research/source_html.py`, and the `risk_module` same-origin proxy/materialization path. **Blocker:** `routes/research_content.py:_materialize_source_html_redirect` server-fetches allowed SEC Archives redirects but currently returns the final response body directly from the app route. That must be changed under **S0** so redirect materialization cannot bypass sanitizer/hash/CSP. Browser-followed redirects to `sec.gov` remain explicitly outside the reader contract because they break same-origin selection capture and parent-side inert projection.

---

## L2 — Agent substrate: corpus + tools

**Job.** The agent's full-power research layer: corpus text, char offsets, section map, retrieval/search, and the evidence layer the rest of the system reads.

**Invariants.**
- **Kept maximally capable, never degraded to serve the UI.** The reader does not constrain the corpus/tool surface.
- Hidden infrastructure: not a human reading surface, not a peer "mode."
- **Located-findings contract:** research/analysis/compare tools must return *located* findings (corpus offsets / section anchors), not just prose — the action layer can only act on what carries an anchor.

**As-built (verified 2026-05-28).** `filings_read` returns text + `char_start/char_end` (`core/corpus/filings.py:98–142`); `filings_source_excerpt` returns section-scoped located excerpts (`:147–262`); evidence layer carries offsets + `source_ref` + `section_header` across `AI-excel-addin/api/research/*`. Substrate is located. ✅ Gap: nothing yet routes *live agent answer-findings* into the reader (see L5 findings→projection feed).

> **Offset-frame caution (load-bearing for the bridge).** `filings_source_excerpt` offsets are relative to the **combined API excerpt**, not the local corpus document — they are **not interchangeable** with `filings_read` corpus-document offsets. Every offset-bearing anchor must carry *which offset frame* it is in (`corpus_doc` vs `api_excerpt`), and L3 must never mix frames when mapping/projecting. Visible quote anchors use the visible-text frame (`source_html_visible_text_v1`) instead of pretending to have corpus offsets. Conflating frames silently produces misaligned highlights.

---

## L3 — The bridge (the load-bearing layer)

**Job.** Reconcile "what the human sees" with "what the agent sees," honestly. The *only* coupling between L1 and L2.

**Three bridges.**

| Bridge | Mechanism | For | Source of truth |
|---|---|---|---|
| Semantic | corpus offsets ↔ inert DOM marks | durable **prose** citations + highlight projection | corpus text |
| Perceptual | same-origin DOM scroll-spy → visible spans | "what you're looking at now" + read/audit trail | DOM viewport |
| Visual | rendered-region snapshot → vision | **tables/charts/images** localization | **identity-bound parsed tables/XBRL** |

**Mapping registry (authoritative, producer-first).** Durable exact/high mappings require a backend `mapping_record_id` keyed by `document_id, accession, primary_document_url, source_html_hash, corpus_content_hash, sanitizer_version, parser_version, mapping_algorithm_version`. The client may *display* a mapping, but durability and citation come from the registry. **Single source of mapping truth.** The preferred producer of records is the corpus/Edgar parser pipeline that already converts SEC HTML into corpus markdown; post-hoc matching is a legacy/backfill fallback, not the primary architecture. The sidecar/registry schema is now a named **C-contract** gate before C0 producer implementation starts.

**Corpus producer mapping contract.** Because the corpus markdown is made from the SEC HTML, the parser/converter should emit three artifacts from the same source parse: canonical corpus markdown, sanitized/source HTML identity, and an HTML↔corpus mapping sidecar. That sidecar preserves the conversion trace while it exists: section id/header, visible-text offsets, DOM/table context when available, corpus `char_start`/`char_end`, quote/prefix/suffix, parser version, source/corpus hashes, and confidence. The registry stores and validates this sidecar and mints `mapping_record_id` values. The reader consumes those records through `ReaderBridge`; it does not rediscover exact mappings as its source of truth. Initial C0 is prose-first because current ingestion calls Edgarparser with `include_tables=False`; table/cell exactness requires producer table metadata.

**Alignment boundary (the table-hoisting seam).** The corpus hoists tables to an end-of-section `### TABLES` block, so corpus offsets ↔ HTML positions align cleanly **only in pure-prose sections**. Rule: **project corpus offsets only on prose; degrade to section/quote on table regions; use the visual bridge for tables.** Wave B enforces this through ReaderBridge projection diagnostics: table-region corpus offsets degrade instead of projecting a precise DOM mark.

**Alignment law (rendered-table bridge).** Rendered table localization is a *spatial anchor resolver* that can identify a visible cell's row/column/header context; for SEC HTML tables the MVP uses same-origin DOM cell localization, while vision/OCR remains an optional future helper for charts, images, or ambiguous non-DOM regions. The cited value comes from the identity-bound parsed table/XBRL layer, not the browser or vision. On mismatch: trust parsed, log a diagnostic. ReaderBridge may submit only a candidate localization. Exact/high table evidence is minted only by a backend resolver/registry path after the parsed-value source proves same SEC filing identity (`accession`, primary document URL or filing URL, CIK/form/source/fiscal period when available) and the reader resolver proves the current materialized reader identity, including local `source_html_hash`. If either proof is missing or mismatched, the bridge degrades to quote/section-only and cannot emit a citeable table cell. E-pre-1, E-pre-2, and the Wave E MVP resolver now connect rendered table localization to those authorities.

**Visual overlay link contract.** Pixels are never durable evidence. Reader artifacts persist the `DocumentAnchor` plus table-cell provenance; the parent overlay stores/recomputes bounding rects transiently through `ReaderBridge` after materialized identity verification. A "go to cell" or visual overlay link may scroll/flash the current iframe region, but if rect restoration fails after resize/reflow/sanitizer change it degrades to section/document navigation instead of treating old coordinates as authoritative.

**As-built (status reconciled 2026-05-29).** The implementation plan is the current status ledger. The source HTML reader, reader shell, ReaderBridge boundary, action overlay, transient reader-action projection, prose-first mapping sidecar/registry, exact live-selection resolve path, D perceptual bridge, upstream E-pre-1 table identity, local E-pre-2 table-cell authority guard, and Wave E MVP rendered-table resolver are implemented. D emits a bounded `reader-viewport-v1` context only after materialized identity and excludes dwell/read-time and per-section temporal trails. E-pre-1 verifies only complete domestic table identity (accession, filing/primary-document URL, CIK, form, and period signal) and fails closed for legacy/no-identity caches. Wave E now lets a visible table-cell selection submit a DOM localization candidate to the backend resolver; exact/high `filing_table_cell` evidence is emitted only when the resolver proves same-filing parsed table provenance and mints server-issued table authority, otherwise it degrades to quote/section.

---

## L4 — On-top layer (what the human sees)

**Job.** Make the faithful filing a research instrument without touching it.

**Components, by anchoring discipline** (detail: `F156_READER_ON_TOP_LAYER_SPEC` §4):
- **Framing** (CSS, no bridge): "paper on a desk" — readable measure, deliberate document surface. *Biggest felt fix, cheapest.*
- **Inline marks** (in-document inert): agent = `--accent-dim`; user = `--surface-2` + `--text-dim` rail.
- **Quiet `⚑ Agent:` callout** (parent overlay, rect-anchored): DESIGN.md "Callout Annotations" grammar — Geist Mono 10px, 0.6px leader + terminal dot, no box. One line; detail goes to the rail.
- **Selection chip** (parent overlay): the action surface — see below.
- **Point-to** (overlay + scroll-into-view + transient flash).
- **Confidence badge / scroll-position dots** (internal clarity / navigation).

**Action surface (decided 2026-05-28).** Human's direct surface = the **minimal overlay only: Ask / Save / Flag.** No sidebar action buttons. Rich/typed actions are **agent-mediated** (analyst directs; agent executes via L6 capabilities). This **supersedes** the rich rail action-card in the note-layer spec; the rail returns to conversation + context + recent-artifacts list. Codex's capabilities are preserved — only the entry point moves.

**Anchor = shared coordinate system.** Every overlay element references a `DocumentAnchor`; the overlay consumes the bridge and never fuses L1↔L2.

**As-built.** Marks project from stored annotations + langextract extractions (`DocumentTab.tsx:125–159`). The action surface currently exists in **two places at once** — a toolbar action set in `DocumentTab.tsx:461` *and* a rich rail card in `ReaderArtifactPanel.tsx:~250` — a **current contradiction**, not just "a rail card to be rebound." Collapsing both into the minimal overlay (+ agent-mediated rich actions), plus framing/callout grammar: **to-build.**

---

## L5 — Agent journey & role model

**Role model.** Human **directs** (asks) and **judges** (owns conclusions). Agent = reading capacity scaled: it surfaces the insight a diligent analyst would draw for themselves — observation + measured implication, scoped to the question, **not a verdict**, never freelancing the whole filing.

**Two-way (anchors both ways).**
- **Action (agent→human, the workhorse):** `highlight / annotate / point_to / flag / open`, each anchor-parameterized, **rendered visibly** — narration is bound to a visible action.
- **Perception (human→agent):** the three bridges. Selection (human→agent capture) is the secondary path.

**Agent-first journey** (worked example, "what changed in VALE's risk factors?"): direct → agent diffs (located findings) → `highlight`×2 → `annotate`×2 → rail synthesis + `→ go-to` links → follow-up answered from parsed/​prose → (secondary) human selects what agent missed. Detail + table: `F156_READER_ON_TOP_LAYER_SPEC` §3c.

**The connective contract (findings→projection feed).** Agent answer-findings and typed reader actions route into the L4 projection feed through ReaderBridge. Quote/confidence-scoped transient projection is implemented, and server-authorized table-cell actions now project by visible quote. Client-only or authority-missing table actions remain invalid upstream of projection.

**Viewport consent.** Agent highlights/annotates freely in place; *moving the viewport* is human-committed (agent proposes a link, human clicks).

---

## L6 — Artifact / evidence / promotion

**Job.** Turn captures into durable, auditable research that feeds the rest of the system.

- Notes/quotes/flags/findings → durable **reader artifacts** scoped by `research_file_id`, with v2 anchor + confidence.
- **Evidence registration** → canonical `Thesis.sources[]` + `Excerpt` atoms (quote-level or exact/high mapped). Quote-level `Excerpt.locator` is first-class via a v2 `reader_anchor` locator; legacy string locators are compatibility adapters, not the contract.
- **Promotion** to thesis/risk/catalyst/assumption/valuation/model/report — **human-approved**; the agent captures + registers + *proposes*, the typed mutation is the approved step.
- Capabilities preserved from Codex's build; only invocation moves (L4 action surface).

**As-built (verified 2026-05-29).** Reader artifacts, evidence registration, quote anchors, mapped anchors, table-cell anchors, and promotion candidates are built (`services/reader_artifacts.py`, `services/reader_table_citations.py`). `filing_mapped` exactness is gated on the L3 registry. `filing_table_cell` exactness is gated on a server-issued table citation record minted from a trusted resolver result with parsed-source provenance, then revalidated for same filing, same reader `source_html_hash`, and exact raw-cell text before persistence or evidence registration.

---

## L7 — As-built vs to-build & cohesive sequencing

**Built through Wave E MVP:** L1 faithful reader + capture/identity; source HTML safety gate; first-class reader shell; ReaderBridge boundary + lint enforcement; minimal Ask/Save/Flag/Table overlay; L2 located corpus tools + evidence layer; reader-action transient projection including server-authorized table-cell actions; prose/table alignment-boundary degradation; C-contract/C0/C registry MVP for prose exact mappings; D bounded viewport context; upstream accession-bound domestic table identity; local server-authorized table-cell provenance schema and guards; and backend table resolver over accession-bound `get_filing_tables`.

**Remaining contradictions/gaps:** (a) the current table-citation store is a local server authority primitive and should be replaced or backed by the final durable registry/storage path; (b) non-DOM visual cases such as charts/images still need an explicit on-demand vision/OCR helper that feeds localization candidates only; (c) old Edgar table caches without complete filing identity fail closed until regenerated upstream.

**To-build:**
- **E follow-up.** Durable table authority storage, non-DOM chart/image localization, and richer user-visible diagnostics for table-resolution fallback.

**Sequencing rationale.** Completed waves built the safe HTML spine, bridge boundary, action layer, projection path, prose-first mapping registry, bounded perceptual context, upstream same-filing parsed table identity, and local table-cell provenance guard. Wave E now consumes those authorities: rendered table localization is candidate input only, and tables degrade to quote/section unless the risk_module resolver proves same filing and mints server-issued provenance.

---

## L8 — Inter-layer contracts (the interfaces to lock)

- **Render-surface descriptor** (`primary_reader` / `diagnostic_surfaces`) — L1→L4. Target shape; current `render_surfaces.source_html` / `corpus_text` remains accepted through an adapter until all callers migrate.
- **Source-HTML endpoint + materialized-identity endpoint** — L1. Metadata and HTML route share the same identity resolver, sanitizer, hash, CSP, and redirect materialization path.
- **Current deployment source route** — L1 also includes the `risk_module` source-html proxy/materializer. Any future consolidation into AI-excel-addin must preserve the same same-origin URL, hard identity binding, CSP, and safe SEC Archives redirect materialization guarantees before the proxy can be removed. Redirect materialization must never return raw SEC bytes from the app origin.
- **Corpus producer mapping sidecar** — L2→L3. The Edgar/corpus producer emits mapping records from the same HTML parse that creates canonical markdown. Required fields include document/source identity, source/corpus hashes, parser/sanitizer/mapping versions, section identity, visible-text anchor, corpus offsets with `offset_frame`, content type, confidence, and table context where applicable. Sidecar and registry schema are locked by C-contract before C0 starts.
- **Reader shell route/layout contract** — L4. The first-class route is `#research/:ticker/reader/:source_type/:source_id` or its router-equivalent, with back navigation to workspace state, sidecar default collapsed, sidecar width clamping, diagnostic corpus surface demotion, and width gates against the same-origin source route.
- **`ReaderBridge` module API** (the §0.7 enforcement seam) — the *only* surface L4/L5 may call to map/project/resolve anchors. Implemented at `frontend/packages/ui/src/components/research/readerBridge/`, with `SourceHtmlPane` as DOM host and L4/L5 as API consumers only.
- **v2 `DocumentAnchor` union** — the shared coordinate system. Every offset-bearing anchor must carry its **offset frame** (`corpus_doc` vs `api_excerpt`); visible quote anchors carry a visible-text frame (`source_html_visible_text_v1`). Current frontend/runtime code implements quote, mapped prose, and `filing_table_cell` anchors; table cells require table-context normalization plus server-issued authority before they can become exact/high evidence.
- **`Excerpt.locator` reader-anchor shape** — L6. Quote-level visible filing evidence uses a discriminated `reader_anchor` locator; exact/high mapped evidence adds `mapping_record_id` and `offset_frame: 'corpus_doc'`. Legacy `external_anchor` strings remain readable but are not the contract for new code.
- **Mapping-registry API** (`mapping_record_id`, confidence, provenance) — L3. Stores producer-emitted mappings as the primary path; supports post-hoc matching only for legacy/backfill.
- **Projection feed** (corpus highlights → marks) + **findings→projection** (agent findings → marks) — L3↔L4/L5. The feed speaks `ReaderProjectionInput` / `ReaderProjectionResult`: source, persistence, `DocumentAnchor`, requested confidence, projection confidence, content type, diagnostics, and downgrade reason.
- **Table-cell provenance + overlay target** — L3/L6. Table anchors carry server-authorized same-filing edgar-financials provenance (`table_id`, value-source filing identity, reader-local `source_html_hash`, row/column, headers, parsed value/unit/period/concept, resolver version, diagnostics, and a server-issued authority id). Browser/ReaderBridge table localization is candidate input only. Overlay targets are transient `ReaderBridge` restore results, not stored pixel coordinates.
- **Agent action vocabulary** (`highlight/annotate/point_to/flag/open`) — L5→L4. Operational contract (perception payload, durable-vs-transient emission, transport): `F156_READER_AGENT_INTERFACE_SPEC.md`.
- **Reader artifact + evidence registration** schema — L6.

These are the seams adversarial review should pressure-test first.

---

## Cross-cutting

- **Security.** SEC markup is untrusted; no scripts in the filing doc; redirect materialization sanitizes or fails; parent reads selection state itself and injects only inert marks after materialized identity verification; durable actions gated on verified materialized identity.
- **Privacy.** Remote SEC subresources are blocked by default or loaded through an app-controlled resource proxy; direct SEC image loads are not the default because no-referrer does not prevent SEC-cookie/read-activity leakage. The accepted D posture stores only visible-section viewport context attached to the research turn for replay/audit, self-labels the audit scope, and excludes dwell/read time, per-section first/last timestamps, observation counts, and durable read-trail tables. User-facing disclosure is required before any UI surfaces that trail in the multi-user product.
- **Auditability.** Every artifact carries `anchor_kind / confidence / surface / source+doc identity / corpus+source-html hashes / mapping version`. Agent reader-actions and human captures are logged; the perceptual bridge may add an approved read trail. You can always prove what supported a claim and what was actually read.
- **Confidence ladder.** `exact / high / quote / section_only / none` flows from L3 through L4 (badges) and L6 (evidence state) without ever overclaiming.

---

## Resolved And Deferred Decisions

1. **Vision trigger:** resolved by `F156_READER_DE_DESIGN_SPEC.md` — table vision is on-demand only, never automatic on selection.
2. **Vision↔parsed mismatch:** resolved by `F156_READER_DE_DESIGN_SPEC.md` — parsed value is authoritative; mismatch is logged silently in v1.
3. **Perceptual granularity/privacy:** resolved by `F156_READER_DE_DESIGN_SPEC.md` — visible-section viewport context only, attached to the research turn, no dwell/read time, no per-section temporal trail, no durable read-trail table; disclosure required before surfacing the trail in multi-user UI.
4. **Pointer restraint:** deferred — motion budget for "look here" remains a product interaction tuning item, but cannot weaken materialized-identity gating or the no-pixel-citation rule.
5. **Viewport-control consent:** resolved baseline — agent may propose links/point-to actions, but viewport movement remains human-committed unless a later product policy explicitly approves bounded auto-scroll.
