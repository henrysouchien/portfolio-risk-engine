# F156 Reader On-Top Layer Spec — Visual Overlay + See↔Agent Bridges

**Status:** Draft v1 — reconciled with `F156_READER_SYSTEM_ARCHITECTURE.md` and `F156_READER_IMPLEMENTATION_PLAN.md`
**Date:** 2026-05-28
**Owner:** Research Workspace / Filing Reader / Reader UX
**Companion specs:**
- `F156_READER_SYSTEM_ARCHITECTURE.md` — authoritative umbrella; wins on conflicts.
- `F156_SEC_HTML_READER_ARCHITECTURE_SPEC.md` — HTML serving, sanitizer, anchors, security (the spine).
- `F156_READER_ANALYST_NOTE_LAYER_SPEC.md` — artifact/evidence/promotion workflow after the UI action-surface supersession below.
- `docs/design/research-reader-on-top-preview.html` — canonical visual preview for this spec's reader framing, quiet annotation, selection overlay, and rail relationship.
- This spec — the **visual layer rendered on top of the faithful HTML**, and the **bridges** that connect what the human sees to what the agent sees.

## 0. One-line thesis

The faithful SEC HTML stays the visible spine. Everything that makes it a *research instrument* — agent highlights, quiet annotations, selection actions, "what you're looking at" awareness — is layered **on top of** the HTML and **behind** it (corpus-backed infra), never by restyling the filing itself.

## 1. What this spec owns

This spec does **not** re-open the reader architecture. F156 is binding: one human filing reader, SEC HTML as the visible baseline, corpus as hidden substrate. This spec covers only the two things layered around that spine:

- **The on-top visual layer** — what the analyst sees overlaid on / framed around the filing.
- **The see↔agent bridges** — how "what the human sees" and "what the agent sees" stay connected and honest.

Reference inspiration: **`clicky`** (farzaa) — an AI tutor that bridges screen content to a model and points back at it via an overlay. We borrow its *overlay discipline* and *inline-anchor protocol*, not its pixel-coordinate citation model (we have something better for prose; see §3).

## 2. Non-negotiables

1. **HTML spine, faithful, no inner restyle.** The sanitized SEC HTML renders as-is (F156 D2). We frame it and overlay on it; we do not recolor or re-typeset the document body. Risking table/statement fidelity to chase app-native prose is forbidden.
2. **Quiet overlay; conversation lives in the rail.** On the document we show only: highlights, a restrained one-line "Agent:" annotation, and a compact selection action. Anything conversational — questions, answers, comparisons — happens in the sidebar agent panel, not in the document margin. (Matches the preview: inline `⚑ Agent:` note in the doc, dialogue in the right rail.)
3. **Overlay never mutates the filing except inert highlight marks.** Inline highlights may inject inert `<mark>` into the same-origin iframe (already done). Everything richer — annotations, the selection chip, agent "look here" pointers — lives in a **parent overlay anchored to bounding rects**, so we never inject non-text chrome into untrusted SEC markup.
4. **Alignment, not drift.** Structured corpus / identity-bound table/XBRL data is the **single source of truth** for any number the agent cites or computes. The visual/vision bridge (§3) may *localize* within a table or chart, but it must never emit an authoritative number that can diverge from the parsed source of truth. Vision points; parsed data supplies values.
5. **Honest confidence.** The F156 anchor ladder (`exact / high / quote / section_only / none`) is preserved. The overlay must never render a quote-only or low-confidence anchor as if it were an exact corpus citation.
6. **Dual representation, bridge-only coupling.** Two clean independent representations — the **human spine** (faithful SEC HTML + capture/identity infra) and the **agent substrate** (corpus + tools, kept maximally capable for research) — coupled *only* by the bridge (mapping with confidence + provenance). Neither bends to serve the other; the overlay/journey **consume the bridge and never reach around it** to fuse the two. (Inherited from `F156_SEC_HTML_READER_ARCHITECTURE_SPEC`'s Primary-surface / Hidden-substrate / Bridge model.)

## 3. The three bridges ("what the agent sees")

`clicky` bridges via pixels + screen coordinates because it has **no structured access** to the app underneath. We have the opposite: **same-origin DOM access** to the filing (the reason the iframe sandbox was dropped). That lets us split "what the agent sees" into three bridges, each correct for a different job:

| Bridge | Mechanism | Right for | Source of truth | Status |
|---|---|---|---|---|
| **Semantic** | corpus char offsets ↔ inert DOM marks | durable, auditable **prose** citations + agent highlight projection | corpus text | Active bridge lane; extraction/registry work continues in the reconciled wave plan |
| **Perceptual** | same-origin DOM scroll-spy → which spans/section are in the viewport | **"what you're looking at right now"** → live agent context + an audit trail of what the analyst actually read | DOM viewport state | new (this spec) |
| **Visual** | snapshot a *rendered region* (table/chart/image) → vision model | **tables, charts, images** — where the semantic bridge is weakest | **identity-bound parsed tables / XBRL** (see law below) | new (this spec) |

### The alignment law (vision must not drift from parsed tables)

For tables and charts, the visual bridge is a **spatial anchor resolver**, not a data source:

- Vision answers *"which cell / region is the human pointing at"* → identifies row/column headers.
- That location resolves to the **identity-bound parsed table / XBRL value** for that cell — which is what gets cited or computed on.
- The resolver must prove the parsed table payload is for the same rendered filing (accession / primary document / CIK-form-period / source HTML identity). If it cannot, the selection degrades to quote/section-only.
- This fills F156's `VisibleTextAnchor.table_context` (`table_id`, `table_index`, `row_index`, `column_index`, `row_header`, `column_header`, parsed value provenance, resolver version, mismatch diagnostics) from a *visual* selection, with the parsed value as the authority.
- **By construction there is no drift:** vision never produces the number; it produces the *location*, and the number always comes from the structured data.
- If vision's read and the parsed value disagree, **trust the parsed value and surface the mismatch as a diagnostic** — never silently prefer vision. A persistent mismatch is a corpus/parser bug to file, not a thing to paper over.
- The overlay link is visual only: it stores the anchor/artifact id and asks `ReaderBridge` to recompute the current bounding rect. Pixels are never durable evidence.

This turns the weakest case (financial-statement tables, where corpus markdown is mush and exact text-mapping is hard) into a *capability*: the agent reads the same faithful pixels you do, but every cited figure is still the structured datum.

## 3b. The interaction is two-way (perception + action)

The on-top layer is not just *what the agent sees* — it is the **bidirectional interface** between human and agent over the filing. This is the reader's analog of **computer-use**, with one crucial difference: a generic computer-use agent operates by **pixels** (screenshot in, click-coordinate out), which is fragile and unauditable. Our agent operates by **anchors** — the v2 `DocumentAnchor` is the shared coordinate system for both directions.

- **Perception (human → agent) — "what the agent sees":** the three bridges in §3.
- **Action (agent → human) — "what the agent does":** a bounded reader-action vocabulary, each action parameterized by an anchor and rendered through the on-top layer (never by restyling the filing).

Because both directions speak `DocumentAnchor`, the loop closes cleanly: a human selection produces an anchor the agent reasons about; an agent action emits an anchor the reader resolves to a DOM range and renders. Same language, both ways — robust and loggable, not a brittle pixel-poke.

### Agent reader-action vocabulary

| Action | Param | Renders as | Confidence behavior |
|---|---|---|---|
| `highlight(anchor, author=agent)` | anchor | inline `--accent-dim` mark | exact/high → precise span; section → section band; quote → quote span; never renders a precise mark it can't anchor precisely |
| `annotate(anchor, note)` | anchor + ≤1-line text | quiet `⚑ Agent:` callout (no box) | same as highlight |
| `point_to(anchor)` | anchor | scroll-into-view + transient flash | needs ≥ section-level anchor |
| `flag(anchor, severity)` | anchor | urgency dot (watch/act/alert) | same as highlight |
| `open(section \| document)` | section / doc id | section nav or new document tab | n/a |

The preview's *"I've highlighted two passages that weren't in the prior filing"* is exactly `highlight()` + `annotate()` emitted by the agent and reflected in the document, while the rail message narrates them.

### Two binding rules

1. **Narration is bound to action, and the action is shown.** If the agent says "I highlighted X," the `highlight(X)` action must actually have been emitted and **rendered visibly in the reader** — the visible mark is primary; the agent's words merely describe what is already on the page. The agent's claims about document state must be *true* — the action log is the truth, the narration describes it. Agent reader-actions are logged alongside human ones in the audit trail.
2. **Highlighting/annotating is free; directing the viewport is consented.** The agent may highlight and annotate in place at will (passive — it does not move you). But *moving the human's viewport* (scroll / jump) is the reader analog of the agent grabbing your mouse. Default: the agent **proposes** ("→ go to the litigation disclosure") and the human **commits** by clicking — exactly the preview's "Open in reader →" / "Open in tab →" links. Auto-scrolling on every agent utterance is out. (See open decision #6.)

## 3c. Primary journey: agent-first (and why action dominates)

The dominant journey is **agent-first**: the human directs in natural language; the agent does the research and **acts on the document**; the human reads the marked-up filing and asks follow-ups. Manual human selection/capture (the workflow the note-layer spec leads with) is the **secondary, occasional path** — used when the human wants to point at something the agent did not surface.

**Role model — the agent is the human's reading capacity, scaled.** The human **directs** (asks the questions, sets the agenda) and **judges** (owns the thesis, decides what becomes a durable conclusion). The agent does the **reading legwork and surfaces the insight a diligent analyst would draw for themselves if they could read everything instantly** — observation plus measured implication, *not a verdict*. It is the analyst's faster self, not an autonomous decider. Consequences that bound the design:
- The agent volunteers insight **within the scope of the human's question** (more than a passive search box) but **stops short of concluding** (less than an autonomous agent). Proactive highlighting is scoped to the query, not the agent freelancing across the whole filing.
- Insight voice stays **grounded and restrained** (DESIGN.md analyst voice): observation + measured implication, sourced, never a recommendation the human didn't ask for.
- **Judgment, decision, and promotion stay human-owned** — the agent proposes (highlights, notes, draft claims); the analyst decides what becomes a thesis/report input (per `F156_READER_ANALYST_NOTE_LAYER_SPEC`).

This emphasis also derisks the build: the agent→document direction rides the **corpus→HTML projection bridge that is already live for stored annotations/extractions**, then expands through `reader_action` and findings projection. The human→agent *exact-citation* direction is the harder, currently quote-only path. Product emphasis and plumbing strength agree.

Worked example — *"What changed in VALE's risk factors vs. last year?"*:

| # | Human | Agent (capability → bridge → action) | Reader renders | Rail renders |
|---|---|---|---|---|
| 1 | asks in rail composer | diff current vs. prior filing (corpus + prior filing / EDGAR compare) → **located findings** | opens §3.D | "working…" |
| 2 | — | `highlight(anchor)` ×2 (corpus→HTML projection) | 2 agent highlights appear | — |
| 3 | — | `annotate(anchor, insight)` ×2 | 2 quiet `⚑` callouts | — |
| 4 | reads marked-up filing | conversational synthesis | marks persist | "I highlighted two passages…" + **→ go-to** links |
| 5 | "provision vs. estimate range?" | retrieve provision (**parsed XBRL**) + range (prose); answer; optional `point_to` cell | optional cell flash | answer w/ figures (provision = parsed, not vision) |
| 6 *(secondary)* | selects a passage agent missed → chip | quote anchor → Ask/Save/Flag | selection highlight | note artifact |

### The contract this exposes (verified 2026-05-28)

For the agent to highlight what it found, its research/analysis tools must **return located findings — corpus offsets / section anchors — not just prose.** Codex's bridge *renders* an anchor; the agent's tools must *supply* one.

**Verified status:**
- **Substrate is located.** `filings_read` returns text with `char_start`/`char_end` (`core/corpus/filings.py:98–142`); `filings_source_excerpt` returns section-scoped excerpts with offsets (`:147–262`); the evidence layer carries `char_start/char_end + source_ref + section_header` across `AI-excel-addin/api/research/*`. The agent **can** obtain located findings today.
- **Last-mile gap.** The reader projection feed `buildProjectedCorpusHighlights` (`DocumentTab.tsx:125–159`) consumes only stored **annotations** + langextract **extractions** — not live agent query-findings. The agent-first journey needs a connective piece that **routes agent answer-findings (with their offsets) into the projection feed.** Buildable on existing primitives; does not exist yet. In the reconciled plan this is Wave B, after `ReaderBridge` and the transient `reader_action` channel.

### Bridge state (verified 2026-05-28) — two seams to reach "tight + aligned"

The projection + quote→corpus mapping is **section-scoped text-normalization alignment** (`SourceHtmlPane.tsx:418–467` map; `:762–806` project — range-scoped, deduped, confidence-gated, prefix/suffix context). Tight for prose. Seams:

1. **Alignment boundary.** Corpus hoists tables to end-of-section `### TABLES`, so corpus offsets ↔ HTML positions align cleanly **only in pure-prose sections**. Interleaved sections (MD&A, Notes) drift. Enforce: project corpus offsets only on prose; degrade to section/quote on table regions.
2. **Producer-emitted mapping sidecar + authoritative registry (missing).** Durable `filing_mapped` persistence is explicitly blocked — `reader_artifacts.py:234–238` ("mapped reader artifacts require an authoritative mapping registry"). Visible selections persist quote-only; a client display-mapper exists but nothing durable agrees with it. Because corpus markdown is made from SEC HTML, "tight + aligned" should start in the corpus/Edgar producer: emit an HTML↔corpus mapping sidecar during corpus generation, ingest it into the registry, and have the client *consume* registry records. Post-hoc matching is legacy/backfill only.
3. **Security/identity gate.** On-top marks are parent-side DOM instrumentation against a same-origin, no-sandbox iframe. They are allowed only after the source route has sanitized/hash-bound the materialized HTML and the parent has verified materialized identity. Route-bound URL verification alone is not enough.

### Emphasis correction to the companion specs

The `F156_READER_ANALYST_NOTE_LAYER_SPEC` leads with the human-driven loop (read → select → ask → save). Under agent-first, that loop is the *secondary* path. The on-top layer's center of gravity is the **agent action vocabulary** (§3b), driven by rail queries; the selection chip is the lighter, occasional human affordance.

## 4. The on-top visual layer ("what the human sees")

Inventory by **anchoring discipline** — this is what determines difficulty and where the jank lives. Each component maps to an existing DESIGN.md pattern so we apply the system rather than invent.

| Component | Anchoring | DESIGN.md pattern | Notes |
|---|---|---|---|
| **Document framing** ("paper on a desk") | CSS around iframe, no bridge | Layout / surfaces | Intentional dark-desk frame so the white filing reads as *the document*, not a foreign rectangle. The preview uses a narrow static paper for illustration; the live reader must not add an arbitrary `max-width` that violates F156 width gates. Cheapest fix, biggest felt gap. Ships first. |
| **Inline highlights** | in-document inert `<mark>` (moves with content) | "Document Reading Mode": agent = `--accent-dim` bg; user = `--surface-2` bg + `--text-dim` rail | Semantic bridge. Codex has this. |
| **Quiet agent annotation** (the `⚑ Agent:` line) | parent overlay, rect-anchored | **"Callout Annotations"**: Geist Mono 10px `--ink`, 0.6px leader + 2px terminal dot, `--bg` background **no box**; `--bg` chip only if it crosses marks | One line, restrained. Detail/conversation → rail, not here. |
| **Selection action chip** (Ask / Save / Flag) | parent overlay, anchored to selection rect | compact, must not cover text | Produces a v2 anchor; exact only when mapping proven, else quote. |
| **Agent "look here" pointer** | parent overlay + scroll-into-view + transient flash | Urgency dots (`--accent` = act) | `clicky`-style: agent references a passage → resolve to scroll + brief point. |
| **Confidence / provenance badge** | inline with annotation/artifact | **"Annotation Tags"**: Geist Mono 10px, 1px border, 3px radius, collapsed | Internal clarity (`Quote` / `Mapped` / `Section`) without burdening reading. |
| **Scroll-position indicator dots** | rail / scrollbar gutter | Chat-margin "indicator dots at scroll positions" | Where annotations/highlights sit in the document; click to jump. |
| **Perceptual context** ("Reading · §1A") | input-only, no rendering | Dateline / agent-context line | Sharpened from section-level to viewport-aware by the perceptual bridge. |

**Author coloring (DESIGN.md "Two-Author Distinction"):** agent marks/annotations use gold (`--accent` / `--accent-dim`) — the analyst's direct address; user marks use `--surface-2` + `--text-dim` rail. Gold stays rare and meaningful.

## 4b. Action surface (decided 2026-05-28)

The human's direct action surface is the **minimal selection overlay only**: `Ask` / `Save` / `Flag`, in place near the selection. **No action buttons in the sidebar.**

Rich/typed actions — `Save quote`, `Save to thesis`, `Add to risk/catalyst/assumption`, `Compare`, `Promote` — are **agent-mediated for now**: the analyst directs the agent ("save that to the thesis") and the agent performs the action through its capabilities. The rail returns to conversation + context + a recent-artifacts list; it is **not** an action panel.

- **Capabilities preserved, entry point moved.** Codex's action capabilities (`reader_artifacts`, evidence registration, typed promotion) stay; only the invocation surface changes (sidebar buttons → overlay for the common three + agent for the rest). Nothing is removed.
- **Supersedes** the rich selected-passage action *card* in `F156_READER_ANALYST_NOTE_LAYER_SPEC` (Ask analyst / Save note / Save quote / Flag / Add to thesis / Compare as a rail card). Those collapse to the overlay's three + agent-directed actions.
- **Agent-mediated actions ride the bridge.** "Save *that*" resolves through the active selection/anchor + viewport context (§3/§3b), so the agent knows the referent.
- **Durable typed writes stay human-approved.** Per the role model (§3c), agent-mediated "save to thesis" = capture + evidence registration + promotion *proposal*; the typed thesis/report/model mutation remains the explicit approved step.

## 5. What we take from `clicky` (and what we don't)

- **Take:** the overlay discipline — the agent's visual layer is a *separate overlay that points at the surface and never mutates it*; and the *inline anchor protocol* — agent output carries structured anchor references (corpus span / quote / `table_context`) that the reader resolves to a mark + a scroll/point affordance (analogous to clicky's `[POINT:x,y]` tags).
- **Don't take:** pixel coordinates as the citation substrate. Coordinates are fragile to scroll/reflow and are not durable evidence anchors. For prose we cite by corpus offset (stable, auditable); vision is reserved for *localizing* within unstructured regions, resolving to structured values.

## 6. Interaction flows (brief)

- **Read** → perceptual scroll-spy keeps the agent's context current to the visible section/spans.
- **Agent finds something** → projects an inline highlight + a quiet one-line annotation; the substance lives in the rail.
- **Select prose** → action chip → semantic anchor (exact when mapping proven, else quote).
- **Select inside a table** → vision localizes the cell → resolves to the same-filing parsed table/XBRL value → `table_context` anchor, exact value when identity-bound, otherwise quote/section degradation.
- **Agent references a passage** → inline anchor resolves to scroll-to + a transient point.

## 7. DESIGN.md reconciliation note

DESIGN.md "Document Reading Mode" currently describes app-native dark prose (Instrument Sans / `--ink` / 640px). Under the F156 constraint the *substrate* is faithful SEC HTML, but the *highlight/annotation grammar* in that section (and "Callout Annotations") carries over unchanged — applied on top of the HTML. DESIGN.md's Document Reading Mode entry likely needs a later editorial update to reflect the SEC-HTML-spine decision; **that is the design owner's call and out of scope for this draft** (no edits to DESIGN.md here).

## 8. Coordination

Codex is actively iterating the semantic bridge and reader components — `SourceHtmlPane.tsx`, `AgentPanel.tsx`, `DocumentTab.tsx`, `ReaderArtifactPanel.tsx`, `frontend/packages/connectors/src/stores/researchStore.ts`, `services/reader_artifacts.py` have been shared edit surfaces. A1 framing is the only low-collision visual step; A2 overlay/action rebind, `reader_action`, and B projection work must be sequenced after S0/S1, the reader shell/layout wave, and then after or co-owned with the bridge extraction. The semantic bridge (mapping records, highlight projection) is Codex's track; this spec adds the perceptual + visual bridges and the visual overlay grammar around it.

## 9. Open decisions & proposed sequencing

**Reconciled sequencing** (matches `F156_READER_IMPLEMENTATION_PLAN.md`):

- **S0 — source HTML safety gate:** harden redirect sanitization + materialized identity before DOM instrumentation.
- **A1 — framing + quiet callout grammar:** dark-desk/paper framing around the iframe, no filing-body restyle, no selection/action logic changes.
- **S1 — contract lock:** lock render-surface, v2 anchor/offset-frame, and evidence-locator contracts.
- **Perception chain:** route live `document_context` through `context.document_context`, persist the same payload as message metadata, and inject it into agent prompts.
- **Reader shell/layout:** URL-addressable first-class reader shell, dominant filing canvas, collapsed/clamped sidecar, and width gates against the source route.
- **ReaderBridge extraction:** extract the typed bridge module before A2/B so overlay and agent actions cannot reach around it to iframe DOM or corpus offsets directly. This is a hard prerequisite.
- **A2 — action-surface rebind:** minimal selection overlay `Ask / Save / Flag`; rail returns to conversation, context, and recent artifacts; rich actions become agent-mediated.
- **`reader_action` channel:** typed transient stream events for `highlight / annotate / point_to / flag`, parsed and projected only through `ReaderBridge`.
- **B — findings projection + alignment-boundary enforcement:** agent located findings render as transient marks; table-region corpus offsets degrade instead of projecting misleading precise marks.
- **C-contract/C0/C/D/E — mapping contract, corpus producer mapping sidecar, mapping registry, perceptual bridge, visual bridge:** durable exact/high mapping authority starts with a locked sidecar/registry contract, then the parser/converter preserving the HTML→markdown trace; the registry stores/validates those records; perceptual and visual bridges add viewport awareness and table/chart localization.

**Open decisions to resolve before locking:**
1. **Annotation richness ceiling.** Confirmed direction: quiet one-line `⚑ Agent:` only; conversation in rail. (Lock it.)
2. **Vision trigger.** On-select of a table region, on-demand ("read this table"), or both? Affects latency/cost budget.
3. **Vision/parsed reconciliation surface.** When vision and parsed disagree, how visible is the mismatch — silent diagnostic log, or a quiet badge? (Default proposed: trust parsed, log mismatch, no user-facing noise unless persistent.)
4. **Perceptual granularity/privacy.** Section-level vs span-level "what you're looking at"; dwell/read-time is excluded until retention, consent, and user-visible disclosure are explicitly approved.
5. **Pointer affordance.** How much "look here" motion is appropriate before it feels gimmicky (clicky's animated cursor is louder than this product's restraint).
6. **Viewport-control consent.** Default: agent highlights/annotates freely in place; viewport navigation is human-committed (agent proposes a link, human clicks). Open: are there cases where the agent may gently auto-scroll (e.g., the human says "walk me through the risk factors"), and what's the motion budget when it does?
