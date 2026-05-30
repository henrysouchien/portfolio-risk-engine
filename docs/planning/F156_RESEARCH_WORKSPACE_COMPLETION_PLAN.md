# F156 Research Workspace Completion Plan

**Status:** Implemented through final review-gated QA
**Date:** 2026-05-29
**Owner:** Research Workspace / Filing Reader / Agent Layer
**Related specs:** `F156_READER_IMPLEMENTATION_PLAN.md`, `F156_READER_AGENT_INTERFACE_SPEC.md`, `F156_READER_DE_DESIGN_SPEC.md`
**Visual targets:** `docs/design/research-workspace-preview.html` for the workspace shell; `docs/design/research-reader-on-top-preview.html` for the first-class reader.

## 1. Product Frame

The product is a research workspace where the analyst can move fluidly between a company research file, source documents, a faithful document reader, and an agent that can perceive and act on the same evidence. The reader infrastructure now exists, but the workspace still exposes it indirectly. The remaining work is to make the product feel coherent and discoverable:

- The human should see an explicit path from a research file to its source documents.
- A filing should open in the faithful SEC HTML reader, not feel hidden behind agent-only interactions.
- Transcripts should be first-class reader documents with the same analyst/agent loop as filings: selection overlay, ask/save/flag, artifact capture, agent-visible context, transient agent highlights, and promotion/review states.
- The side agent should be simpler than the old dense rail: context-aware conversation, recent evidence, and review states, not a command-heavy notes sidebar.
- Artifacts, citations, and promotions should feel like a research layer on top of reading, not a separate workflow.

## 2. Starting As-Built Baseline

At the start of this completion plan, the following reader infrastructure was already implemented:

- URL-addressable document routes: `#research/:ticker/reader/:source_type/:source_id`.
- Filing source HTML reader with same-origin CSP/materialized identity gates.
- Visible filing selection capture, quote anchors, table-cell resolver MVP, evidence registration, and promotion review.
- Agent perception/action infrastructure: document context, viewport trail, reader actions, bridge boundary, and reader artifacts.
- Transcript support existed in `DocumentTab`, `researchStore`, hash parsing, and agent/tool source-card opening, but had not yet been lifted to full parity with the filing reader interaction layer.

Initial product gaps addressed by the phases below:

- The main research workspace does not show a clear "Read filing/transcript" entry point.
- Reader access is mostly implicit through diligence source jump links, agent source cards, or direct URLs.
- The side agent rail is still heavier than the new preview direction and can read as a generic workspace panel rather than a focused reading companion.
- Transcript support is present but lacks the same explicit two-way analyst/agent/product affordances that filings now have.
- The reader and workspace specs describe adjacent surfaces, but the handoff between them needs an explicit implementation sequence.

## 3. Product Decisions

1. **One human reader route family.** Filings and transcripts both open through `#research/:ticker/reader/:source_type/:source_id`. Filing uses faithful SEC HTML when available; transcript uses a transcript segment reader.
2. **Source inventory is a first-class workspace surface.** The workspace should expose source documents directly instead of requiring the analyst to ask the agent or find a diligence citation first.
3. **Agent-first does not mean agent-only.** The agent can suggest/open/read documents, but the human must also have obvious source controls.
4. **The side agent is a companion rail, not a notes command center.** Save/flag/ask entry points stay lightweight; richer actions route through the agent or secondary review surfaces.
5. **Transcript parity is required, not merely protected.** The shared reader product is the analyst/agent/artifact loop. Filing and transcript surfaces differ only in renderer and citation semantics. Both must support visible selection, `Ask`, `Save`, `Flag`, artifact/evidence registration, agent perception, agent-emitted highlights/callouts, review/promotion flow, reloadable routes, and return-to-workspace continuity.
6. **Renderer adapters, shared reader layer.** SEC HTML and transcripts should use different document renderers under a shared reader interaction layer. Filing-specific logic belongs in the filing adapter; transcript-specific logic belongs in the transcript adapter; overlay, agent rail, document context, artifact actions, and transient projection should be source-type aware but shared.

### 3.1 Transcript Parity Contract

The transcript reader is not a separate or reduced product surface. It must be a first-class implementation of the same reader contract used by filings:

- **Human-to-agent:** selecting transcript text exposes the same visible overlay actions as filings: `Ask`, `Save`, and `Flag`.
- **Agent-to-human:** the agent can project transient highlights, callouts, and cited passage focus into transcript content through the same reader action channel used for filing highlights.
- **Artifact capture:** transcript selections create durable research artifacts with quote text, source identity, transcript locator metadata, and review/promotion state.
- **Citation semantics:** transcript artifacts cite speaker/segment/time-or-section context instead of SEC table/filing DOM coordinates. They must never masquerade as SEC filing citations.
- **Shared boundaries:** the side rail, overlay, artifact registration, reader actions, and workspace handoff should consume a shared reader adapter interface. They should not branch into a filing-only path plus a transcript-specific sidebar.
- **Renderer-specific internals:** the transcript renderer may own segment layout, speaker metadata, and passage anchoring; filing renderer may own SEC HTML iframe/DOM anchoring. Everything above the renderer adapter treats both as reader documents.

## 4. Implementation Phases

### Phase 1 — Source Inventory and Reader Entry Points

**Goal:** make the route to the reader obvious from the research workspace.

Scope:

- Add a compact source/document area for the active research file, aligned with `research-workspace-preview.html`.
- Surface known filings and transcripts with type, title/period, and status where available.
- Add an explicit `Read` / reader icon action for each source.
- Opening a filing sets `readerSourceType: 'filing'` and `readerSourceId`.
- Opening a transcript sets `readerSourceType: 'transcript'` and `readerSourceId`.
- Preserve the current direct URL path and back-to-workspace behavior.
- Keep the agent source-card and diligence jump-link paths working.

Acceptance:

- From `#research/MSFT`, the analyst can visibly open the MSFT filing reader without typing a URL or asking the agent.
- The resulting URL is reloadable and uses the canonical reader route.
- Existing agent source cards and diligence source links still open the same reader.
- Tests cover source inventory rendering, filing open, transcript open, and route persistence.

### Phase 2 — Transcript Reader Parity

**Goal:** make transcripts a first-class reader surface with the same two-way analyst/agent/artifact functionality as filings, adapted to transcript semantics.

Scope:

- Audit transcript route loading through `ResearchWorkspaceContainer`, `researchStore`, and `DocumentTab`.
- Add or refresh tests for `#research/:ticker/reader/transcript/:source_id`.
- Introduce or harden a transcript reader adapter that exposes transcript segments, speaker metadata, section/QA context, and quote anchors to the shared reader interaction layer.
- Verify transcript selection creates source-type-specific document context and can be used by the agent.
- Apply the same visible selection overlay to transcripts: `Ask`, `Save`, and `Flag`.
- Ensure transcript selections can create reader artifacts and evidence records with transcript-appropriate locator semantics.
- Ensure agent transient actions can highlight or call out transcript passages through the same reader action/projection channel, without using filing-only SEC HTML DOM assumptions.
- Ensure promotion/review states can attach to transcript-derived artifacts.
- Ensure filing-only SEC HTML controls do not appear on transcript documents.
- Ensure source inventory can list/open transcripts when the data exists.

Acceptance:

- A transcript route opens and reloads correctly.
- Transcript speaker labels and segment structure render.
- Transcript text selection shows the same lightweight overlay as filing selection.
- `Ask` sends transcript context to the agent, including source id, section/segment context, selected quote, and speaker context where available.
- `Save` and `Flag` create transcript reader artifacts and registration states that are visible in the reader/workspace artifact layer.
- Agent-emitted transient highlights/callouts can project onto transcript passages.
- Transcript-derived artifacts can enter promotion review without pretending to be SEC filing citations.
- Filing-only table/SEC HTML affordances are hidden or inert for transcripts.

### Phase 3 — Simplified Agent Companion Rail

**Goal:** align the side rail with the new preview direction: focused conversation and evidence state, not a dense command sidebar.

Scope:

- Simplify reader-mode `AgentPanel` chrome.
- Show only the active document/section context, concise latest analyst response, composer, and compact recent evidence/review state.
- Keep the visible selection overlay as the primary direct action surface for `Ask`, `Save`, and `Flag`.
- Move richer artifact actions to agent-mediated prompts or a secondary review/promotion surface.
- Make artifact/evidence status readable but quiet: saved, registered, data gap, promotion review, promoted.
- Preserve keyboard/focus behavior and width gates.

Acceptance:

- In reader mode, the filing remains dominant and the side rail feels like a companion, not a dashboard.
- Selection actions are not duplicated across toolbar, side rail, and overlay.
- Saved artifacts and promotion review are still discoverable.
- Visual QA compares against `research-reader-on-top-preview.html`.

### Phase 4 — Workspace-to-Reader Research Flow

**Goal:** make the workspace, reader, agent, and artifacts feel like one workflow.

Scope:

- When a source is opened from workspace context, carry the research file, thread, and source identity into the reader.
- In reader mode, `Back to files` returns to the prior workspace context.
- The agent composer should know whether it is in workspace mode, thread mode, filing reader mode, or transcript reader mode.
- Recent filing and transcript artifacts created in the reader should appear back in the workspace's evidence/research artifact layer.
- Promotion review should be reachable from the reader and visible at the workspace level.

Acceptance:

- Open source → read/select → ask/save/flag → register evidence → return to workspace is a continuous path.
- The URL and store state stay consistent across reloads and tab switches.
- The agent receives the right document context in each mode.

### Phase 5 — Review-Gated Product QA

**Goal:** finish with the same bar used for the reader: code review, visual review, and live walkthrough.

Scope:

- Code review pass for route/store/API boundaries, reader/transcript parity, and no direct iframe/corpus boundary violations.
- Visual/product review pass against both previews.
- Live in-app QA:
  - open `#research/MSFT`,
  - open filing from visible source controls,
  - select quote and save/ask/flag,
  - resolve/register a table value where available,
  - open a transcript from visible source controls or a seeded route,
  - select transcript text and save/ask/flag,
  - verify agent transient highlighting/callout on transcript content,
  - return to workspace and verify artifact continuity.
- Update specs when implementation intentionally diverges from preview.

Acceptance:

- All targeted unit/integration tests pass.
- Live QA records no blocking route, evidence, or visual-readability defects.
- Any non-blocking deviations are documented with rationale and follow-up.

## 5. Suggested Implementation Order

1. Build source inventory and explicit reader entry points first. This resolves the user's immediate discoverability gap and gives every later phase a visible entry surface.
2. Build transcript reader parity immediately after, before simplifying the reader rail, so the shared interaction layer is proven across both filings and transcripts.
3. Simplify the agent companion rail once the source/document model is explicit.
4. Tie artifacts/promotion states back into the broader workspace after the reader and rail surfaces stabilize.
5. Run visual and code review at the end of each batch, not only at the end.

## 6. Review Checklist

- Does the filing reader still visually preserve the SEC HTML baseline?
- Can a human open the reader without asking the agent?
- Can the agent still open/source documents when useful?
- Do transcripts have the same reader interaction loop as filings, with transcript-appropriate citation semantics?
- Is the agent rail quieter and more context-specific than the old sidebar?
- Are durable evidence writes still gated by verified identity and server authority?
- Are table citations exact only when same-filing parsed provenance is proven?
- Is every reader route reloadable and back-navigation friendly?

## 7. Implementation Checkpoints

### 2026-05-29 — Phase 1 Source Inventory Entry Point

Implemented the first source inventory batch:

- Added a compact workspace `Sources` band that derives known filing/transcript sources from open document tabs, agent tool-call metadata, persisted citation context, and diligence source refs.
- Added explicit `Read` actions for filing and transcript source entries.
- Routed source-id entries directly to `#research/:ticker/reader/:source_type/:source_id`.
- Routed path-only filing entries through document ingest, then opened the canonical content-addressed filing reader route.
- Added a container-to-workspace `isReaderRoute` boundary so `#research/:ticker` cannot remain stuck in stale document-reader mode.
- Changed reader `Back to files` to return to the current company workspace route instead of the generic research list.
- Kept the source inventory analyst-facing by stripping internal content hashes from visible source titles and hiding raw tool names from status copy.

Verified with targeted tests and live in-app QA. Transcript entries were first covered in unit/integration tests when source metadata existed; the later final QA pass below verified the live MSFT transcript route and workspace transcript entry path.

Deferred non-blocking visual follow-ups:

- Normal workspace still uses `Back to files` to leave the active research file. This is existing workspace navigation semantics; revisit during the broader workspace shell polish instead of changing reader-entry behavior in this batch.
- Filing reader can briefly show an empty white area while the faithful SEC iframe loads. This belongs with reader loading-state polish, not source inventory routing.

### 2026-05-29 — Phase 2 Transcript Reader Parity Batch

Implemented the first transcript parity batch:

- Added a transcript-specific `transcript_quote` reader artifact anchor with `transcript_text` surface, corpus-document offsets, section header, speaker metadata, segment bounds, and `transcript-corpus-v1` locator semantics.
- Extended reader artifact creation, normalization, local persistence, source-record registration, and canonical evidence registration to accept transcript anchors without SEC HTML fields. Canonical registry writes intentionally use `type="transcript"` plus a schema-compatible `text_range` locator while keeping the richer `transcript_quote` anchor on the local reader artifact for UI restoration.
- Added the same lightweight reader selection overlay for transcript selections: `Ask`, `Save`, and `Flag`.
- Updated transcript `Ask` prompts to include transcript passage context and speaker/role when available.
- Added transcript reader action projection so agent-emitted highlights/callouts can render on transcript passages through the shared `readerActions` channel.
- Updated the artifact rail to restore transcript artifacts as transcript selections and to label transcript evidence distinctly from filing evidence.
- Preserved transcript selections while the analyst moves from the reader into the agent rail, so structured `Ask` context is not dropped before the message is sent.
- Blocked multi-speaker transcript selections from being persisted as a single speaker quote, and show the analyst why Save/Flag are disabled until one speaker turn is selected.
- Restoring a saved transcript artifact now activates the artifact's transcript section before restoring the selection, so the visible passage highlight can render in the reader.

Verified with targeted frontend connector/UI tests, targeted eslint on touched frontend files, backend reader-artifact route tests, filing-reader live route QA, and a product/visual reviewer pass. The first Phase 2 pass relied on tests for transcript route behavior because the running workspace did not yet expose a loadable transcript; the later final QA pass below verified the live MSFT transcript route end to end.

### 2026-05-30 — Phase 3 Simplified Reader Rail and Phase 4 Workspace Continuity Batch

Implemented the simplified reader rail and first workspace artifact-continuity path:

- Simplified reader-mode `AgentPanel` into active document/section context, a concise reading prompt, composer, and compact recent evidence state.
- Removed visible reader-side command chrome that duplicated the on-document `Ask / Save / Flag` overlay direction.
- Shared reader-artifact presentation labels across the reader rail and workspace layer so filing/transcript source labels, transcript section names, evidence status, and promotion target copy stay consistent.
- Added a compact workspace `Evidence` strip that reads durable `reader_artifacts` across the research file and stays hidden when there are no artifacts.
- Made filing and transcript artifacts visible from the workspace code path with human source labels, section context, quiet evidence/promotion status, and no raw source ids in visible text.
- Added workspace-level `Open` actions that return to the canonical `#research/:ticker/reader/:source_type/:source_id` route.
- Added workspace-level `Review` actions that queue an analyst-mediated prompt with the artifact's selected passage and registered evidence context when available.

Verified with targeted UI tests for workspace filing/transcript source and evidence continuity, existing reader artifact rail tests, TypeScript, ESLint, and live in-app filing QA on `#research/MSFT`: the workspace showed reader evidence after load, `Open` returned to the faithful filing reader, `Back to files` returned to the workspace, and `Review` queued the analyst composer with anchored filing-passage context. The running MSFT transcript document later became loadable and was covered in the final QA pass below.

### 2026-05-30 — Phase 5 Final Review-Gated QA

Completed the final review gate for the F156 workspace/reader product alignment:

- Re-ran targeted UI suites for reader selection, transcript parity, workspace source inventory, workspace evidence continuity, agent rail behavior, and artifact restoration.
- Re-ran connector suites for reader document normalization, reader artifact serialization/normalization, query invalidation, transcript-shaped anchor strictness, and research store document/tab behavior.
- Re-ran backend reader-content tests covering local transcript documents, filing source HTML surfaces, reader artifacts, evidence registration, mapped/table evidence guards, and transcript corpus validation.
- Re-ran targeted TypeScript and ESLint checks for the touched UI and connector surfaces.
- Live in-app QA on `#research/MSFT` verified visible workspace `Sources` and `Evidence`, filing reader navigation from source controls, reader-to-workspace return, transcript reader navigation from source controls, transcript section rendering, workspace artifact continuity, and separated visible evidence/promotion status.
- Independent browser QA verified transcript text selection produces the same `Ask / Save / Flag` toolbar as filing selections; `Ask` queues an analyst prompt with transcript section and speaker context; `Save` creates transcript workbench evidence; and `Flag` creates a transcript risk/promotion candidate.
- Final code-review returned PASS. Product/visual review returned follow-ups for artifact-only source discoverability, stale transcript-live-QA docs, and raw evidence titles; those were addressed in the post-review closure pass below.

Final verification commands:

- `pnpm exec vitest run packages/ui/src/components/research/ResearchWorkspacePhase2.test.tsx packages/ui/src/components/research/ResearchWorkspacePhase3.test.tsx packages/ui/src/components/research/AgentPanel.test.tsx` — 117 passed.
- `pnpm exec vitest run packages/connectors/src/features/external/__tests__/useResearchDocuments.test.tsx packages/connectors/src/stores/researchStore.test.ts` — 48 passed.
- `python3 -m pytest tests/routes/test_research_content.py` — 82 passed.
- `pnpm exec tsc -p packages/ui/tsconfig.json --noEmit --pretty false` — passed.
- `pnpm exec tsc -b packages/connectors/tsconfig.json --pretty false` — passed.
- Targeted `pnpm exec eslint ... --max-warnings=0` for reader/workspace UI and connector files — passed.

Residual non-blocking follow-ups:

- Live table-cell registration still depends on `edgar_api` health; the implemented behavior degrades safely to quote evidence when authoritative table resolution is unavailable.

### 2026-05-30 — Phase 5 Review Findings (code + visual review pass)

Ran the Phase 5 review gate against the §6 checklist. Code review (architecture/boundary) and live visual review on `#research/MSFT` both passed:

- Filing reader preserves the faithful SEC HTML baseline — verified live on the cover page and the dense `Part I, Item 1` income-statement table (multi-column numeric table, right-alignment, `$`, parenthetical negatives, subtotal rules all intact).
- On-top `Ask/Save/Table/Flag` selection overlay and the selection→perception wiring work: selecting filing text attaches the passage to the rail (`LOOKING AT` / "Selected passage attached") and adapts the composer.
- Simplified reader rail (Phase 3) and the workspace `Evidence` strip (Phase 4) render; artifact `Open` navigates to the section and re-attaches the selection; `Back to files` round-trips; routes are content-addressed and reloadable.
- The table-cell path correctly degraded to "saved as quote" when upstream parsed-table identity was unavailable (alignment-not-drift / fail-closed working live).
- Transcript citation semantics verified in code: `services/reader_artifacts.py` bifurcates `transcript_quote` to a separate normalizer (`:298`), never reaching the filing path that requires `surface=filing_html`/`accession`/`primary_document_url`; the canonical registry write uses a `text_range` locator (`:749`), never a filing/table locator. Bridge boundary is clean (`DocumentTab`/`AgentPanel` carry no direct iframe/corpus access; §0.7 lint intact); the multi-speaker save guard is present (`DocumentTab.tsx:912`).

Non-blocking follow-ups filed during the first review pass:

- **Selection overlay mispositions on artifact restore** (`F156-reader-overlay-restore-position`): opening an artifact via workspace `Evidence` → `Open` re-attached the selection, but the floating `Ask/Save/Flag` overlay anchored top-right and overlapped the analyst rail header ("…Financial Statements" clipped) instead of sitting beside the restored passage. Observed once on the restore path. Check the restored-selection rect computation, overlay z-index, and viewport-edge clamping.
QA precondition (not a tracked code item — environmental/transient): `edgar_api` (edgar_updater, `:8500`) was `degraded`/timed out during this review, which is why live table-cell resolution degraded to quote. Restart/verify `edgar_api` before table-resolution QA so the fail-closed-to-quote path is not mistaken for a code regression.

### 2026-05-30 — Phase 5 Post-Review Closure

Closed the product/visual reviewer follow-ups that were not covered by the first Phase 5 patch:

- Workspace `Sources` now merges active reader artifacts as durable source references, so filing/transcript documents discovered only through saved evidence are still reachable from the research workspace. This preserves the product rule that saved research evidence is also a navigable reading trail.
- Transcript live QA is no longer blocked: the final QA pass loaded the MSFT transcript route, verified section rendering, and independently verified transcript selection with `Ask`, `Save`, `Flag`, evidence registration, and promotion candidate behavior.
- Workspace/rail evidence titles now prefer curated labels derived from source type, artifact kind, and section when the stored title is generated from raw selected text. The full quote remains in artifact body/prompt context; the visible list no longer needs to expose long raw filing or transcript text as the title.
- Restored-selection overlay positioning no longer falls back to the top-right viewport corner when restored quote geometry is unavailable. The restored selection remains available as reader context, and the floating `Ask / Save / Flag` toolbar renders only when it has a measured passage rectangle; live filing restore QA confirmed no Vite/runtime error and a measured overlay anchored near the passage after the SEC iframe verified.
