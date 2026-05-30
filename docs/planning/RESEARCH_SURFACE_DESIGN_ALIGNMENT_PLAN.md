# Research Surface Design Alignment Plan

**Status:** Non-reader component and reduced-shell alignment pass verified 2026-05-29; F156 reader and F122 Workbench convergence remain separate tracks.
**Date:** 2026-05-27
**Owner:** Research workspace / Hank UI
**Scope:** Research list, research workspace shell, conversation/thread views, document reader integration, report/handoff presentation, and research-to-action exits.

## 0. Why This Plan Exists

The current research surface has become functionally powerful, but its visual and interaction model has drifted from the original research workspace preview and the broader Hank workspace design language.

The goal is not to remove working functionality. The goal is to rehouse the existing functionality inside the intended product model:

```text
An IDE for equity research:
  files organize the work,
  tabs hold active artifacts,
  the main pane is the current research artifact,
  the analyst rail stays contextual,
  every useful result leads to a next action.
```

The original preview should guide the interaction model and visual hierarchy. The shipped architecture should remain the source of truth for persistence, research file identity, per-user state, diligence, handoff artifacts, and source/corpus provenance.

## 1. Design And Architecture Authorities

The references below are not equal authorities. Use this precedence when implementation details conflict.

| Reference | Authority Level | Binding Use |
| --- | --- | --- |
| Research-specific preview | Product/visual target | Interaction model, density, tab/rail/exits visual language. Not binding for superseded architecture details. |
| `EQUITY_RESEARCH_WORKSPACE_SPEC.md` | Product intent | "IDE for equity research", two-pane mental model, reading surface principles, thread emergence. Architecture sections marked superseded in that doc are not binding. |
| `RESEARCH_WORKSPACE_ARCHITECTURE.md` + decisions log | Architecture authority | Persistence, per-user isolation, research file identity, diligence/report pipeline, tool access, handoff contract. |
| `F156_SEC_HTML_READER_ARCHITECTURE_SPEC.md` | Binding filing-reader authority | First-class human filing reader shell, source HTML as primary reader, diagnostics/fallback behavior, SEC parity gates, anchor/provenance direction. |
| `F122_HTML_ARTIFACT_RENDERER_*` | Binding HTML artifact authority | Workbench, artifact tabs, proxy/SSE/store/renderer/sandbox implementation. This plan may only consume and visually place those surfaces after F122 lands. |
| `RESEARCH_WORKSPACE_AUDIT.md` + `UI_POLISH_FOLLOWUPS_PLAN.md` | Issue inventories | Useful gap lists, but must be reconciled against current code before assigning work because several items are stale or partially closed. |

### Primary product/design references

- Research-specific preview: `docs/design/research-workspace-preview.html`
- Product spec: `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md`
- Research audit: `docs/planning/RESEARCH_WORKSPACE_AUDIT.md`
- Workspace architecture: `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md`
- Architecture decisions: `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md`
- UI polish follow-ups: `docs/planning/UI_POLISH_FOLLOWUPS_PLAN.md`

### Parallel-track boundaries

- Human filing reader / SEC HTML reader: `docs/planning/F156_SEC_HTML_READER_ARCHITECTURE_SPEC.md`
- HTML artifact renderer / Workbench: `docs/planning/F122_HTML_ARTIFACT_RENDERER_SPEC.md` and `docs/planning/F122_HTML_ARTIFACT_RENDERER_IMPL_PLAN.md`

This plan should not duplicate those implementation tracks. It should define how those surfaces fit into the research workspace once they land.

## 2. Current State Snapshot

The April audit is directionally useful but stale. Several items it listed as missing are now partially or fully present.

### Current strengths to preserve

- Research files are first-class and keyed by `research_file_id`, with ticker plus optional label.
- Research list is now table-based, with stage, strategy, direction, conviction, thread count, update time, compare, and open actions.
- Workspace supports Explore, Thread, Document, Diligence, and Handoff/Report tabs.
- Conversation feed supports compact tool rows, open-in-reader actions, source/citation rendering, and branch/start-thread actions.
- Document reader supports section navigation, corpus text selection, annotations, ask-about-this, and thread creation from selected passages.
- Research workspace has exit ramps to scenarios, trading, compare-to-holdings prompts, document summaries, and thread pressure tests.
- Handoff/report rendering now uses more of the Hank design system, including `InsightSection`, `NamedSectionBreak`, source chips, typed metric strips, and structured sections.
- Source HTML filing rendering is entering the surface through `SourceHtmlPane` and `DocumentTab`.

### Current weaknesses to address

- The research shell reads partly like a file/workflow cockpit rather than an IDE for active research.
- The main reader pane and right analyst rail can both look like conversation feeds, which blurs purpose.
- The research list still starts from operational controls instead of a briefing-style readout of what needs attention.
- Some preview patterns are present in code but not yet visually resolved: dateline, exit ramps, tab bar, author distinction, findings, notes, and inline data.
- Document mode is in transition. The source HTML filing reader needs to become a focused reading surface without losing notes, citations, selections, and corpus grounding.
- Some controls expose implementation concepts too directly, such as diagnostics/fallback text controls and dense metadata controls competing with the reading surface.

## 3. Target Model

### Research visual contract

The research surface should inherit the preview's visual grammar instead of drifting back to generic dashboard/card composition.

| Surface Element | Binding Visual Direction |
| --- | --- |
| Typography | Instrument Sans for prose and analyst/user content. Geist Mono for datelines, tabs, labels, table headers, metrics, and compact metadata. |
| Color system | Dark workspace tokens from the preview/design system. Gold/accent is reserved for analyst-directed action, active tab underlines, findings, highlights, and exit arrows. Do not turn the surface into a one-hue accent layout. |
| Layout framing | No card quilts and no cards-inside-cards for page/workspace sections. Use the workspace shell, flat bands, tables, rails, and source/document canvases. Repeated items may use rows; modals and individual artifacts may still use cards. |
| Radius | Keep workspace and small controls at 6px radius or less unless an existing shared primitive forces otherwise. Avoid large rounded dashboard cards in the core research workspace. |
| Tabs | Flat IDE-style tabs, mono 11px, active state as text plus 2px accent underline. Avoid pill tabs with filled backgrounds as the primary research tab language. |
| Dateline/context | Mono 11px uppercase context line: date, company/file, stage. It should orient the workspace without becoming an editable control bar. |
| Analyst rail | Target 280-320px on desktop unless F156 filing width gates require collapse. Rail is contextual and visually secondary when the main pane is conversation-like. |
| Exit ramps | Text links with gold arrows, not bordered command buttons. They should read as "where this result leads" rather than a toolbar. |
| Stage badges | Exploring uses chart blue, Diligence uses accent/gold, Decision uses up/green. Other stages should be quiet and consistent. |
| Inline metrics | Horizontal metric strips with mono labels/values, hairline separators, tabular numbers, and restrained up/down color. |
| Inline tables | Mono headers, numeric alignment, tabular numbers, ticker emphasis, hairline borders, no heavy card wrapper. |
| Branch/open actions | "Start thread: X ->" and "Open in tab: Y ->" style text links with accent arrows. Avoid bordered button rows for the default state. |

### Research list

The list should answer:

```text
What research needs attention, what is ready for decision, and where should I go next?
```

The dense table remains valuable, but it should sit under a short analyst briefing. The top of the page should feel like Hank is triaging active research, not merely showing a file manager.

Default first-viewport order for `#research`:

1. Dateline: date + `Research`.
2. Analyst briefing on a subtle `--surface-raised` treatment, written as a diagnosis of active files.
3. A quiet text-link action: `Start new research ->`.
4. Dense table header and first visible rows.
5. Create form, filters, sort, compare controls, and bulk actions are secondary. They should be compact, collapsible, or placed below/alongside the briefing rather than leading the page.

### Research workspace

The workspace should preserve the preview's mental model:

- Top context line establishes date, file, ticker/company, stage, direction, strategy, and conviction.
- Main pane owns the active artifact: explore feed, focused thread, filing, transcript, diligence checklist, report, or HTML artifact.
- Right rail is the persistent analyst/context rail: active context, workspace scan, selected-text prompt, pinned finding, related threads, quick prompts, and message input.
- Exit ramps remain visible and low-friction, but should look like a natural bottom action row rather than a separate tool block.
- Tabs should feel like IDE tabs: compact, flat, readable, and stable.

### Document reader

The filing reader should follow F156:

- SEC/source HTML is the primary human reading surface when available.
- Corpus text remains infrastructure and fallback, not a peer "mode" in the normal workflow.
- Notes, citations, selections, evidence atoms, and agent context must remain supported.
- The filing gets a dominant canvas; agent/notes/artifacts are sidecars or drawers that do not permanently degrade readability.
- F156's first-class, URL-addressable filing reader shell is binding. This plan owns workspace launch/return semantics and surrounding fit, not an alternate reader implementation.
- F156 acceptance gates are inherited here for any filing-reader-facing work: sidecar collapsed by default, diagnostics hidden from the primary path, desktop filing width gates, and source-route vs embedded-reader screenshot comparison.

### Handoff/report

The report should feel like a frozen analyst artifact, not a raw data inspector:

- Lead with thesis and decision framing.
- Render typed sections with evidence and source chips.
- Preserve versioning and decision-log history without letting those mechanics dominate first impression.
- Keep build-model and downstream actions clear, but secondary to reading the finalized thesis.

## 4. Guiding Decisions

### D1. Preserve capability while changing hierarchy

Do not remove functioning features as the first move. Rehouse them into the intended hierarchy. Removal should come only after a design review shows an affordance is redundant, confusing, or purely diagnostic.

### D2. Main pane and rail must have distinct jobs

Proposed target:

- Main pane: the active research artifact.
- Right rail: contextual analyst companion, workspace scan, selected-text handling, quick prompts, and input.

The rail can show analyst messages, but it should not compete visually with the active thread/feed. If the main pane is a conversation artifact, the rail should become lighter and more contextual.

Default rail contract:

| Active Artifact | Main Pane Owns | Rail Owns | Rail Message Feed? | Input Target | Selection / Persistence |
| --- | --- | --- | --- | --- | --- |
| Explore | Primary exploration conversation and branchable analyst turns | File context, workspace scan, suggested prompts, active metadata, message input | Compact recent context only; no full timestamped feed at equal weight | Panel thread unless an explicit thread is selected | Draft prompt persists in research store; no durable note unless sent/saved |
| Thread | Focused thread timeline, notes, pinned finding, related evidence | Thread summary, pressure-test prompt, related threads, message input | Compact recent context only; must not duplicate full main timeline | Active thread while the focused thread tab is active | Thread notes/messages persist through research API |
| Document / filing | Human-readable source/document surface | Active document identity, selected-text prompt, ask/save/branch actions, agent sidecar | No full competing feed by default; sidecar may show compact assistant context | Panel thread with document context | Visible-source anchors follow F156; corpus offsets only when mapping allows |
| Diligence | Checklist/draft sections and source refs | Progress scan, missing sections, refresh/opening-take prompts, report action | No full feed by default | Panel thread with diligence context | Section state persists through diligence API |
| Handoff/report | Frozen report, evidence, source chips, version being reviewed | Version/status context, build-model action, new-version action, decision-log shortcuts | No full feed by default | Panel thread with report context | Report artifact remains immutable for finalized versions |
| Compare | Comparison table/narrative | Compare framing, differences to resolve, next-action prompts | No full feed by default | Panel thread with compare context | Compare selection stays client/session state unless saved elsewhere |

If an implementation keeps `AgentPanel`'s internal `ConversationFeed`, it must visually demote it when the main pane is also conversation-like and prove the two surfaces have distinct labels, density, and purpose. For Explore and Thread, Phase 1 acceptance is stricter: the rail is annotations/context-first, with file context, workspace scan, selected prompt, pinned or related findings, and compact recent context only. A full timestamped conversation feed at equal visual weight does not pass.

Implementation note: "compact recent context" means a short contextual excerpt or summary, not a shortened full chat transcript with the same timestamp/author rhythm as the main pane.

Default thread input policy for Phase 1: when the active artifact is a focused thread, the rail input writes to that same active thread and the compact recent-context block reads from that same thread. This keeps the rail's visible context and optimistic/streamed messages coherent. Any future panel-thread review mode should be a separate explicit affordance, not an implicit background write path while the rail is presenting active-thread context.

### D3. Research list needs briefing voice

The list should retain table density but add a diagnosis-first top readout. V1 must be deterministic and client-side from existing file metadata: stage, updated age, conviction, direction, strategy, thread count, flagged thread count, diligence/report availability, and compare selection. An editorial/LLM-generated briefing is a later separate plan, not part of the initial UI-alignment slice.

### D4. Source HTML is a reader integration, not a UI fallback pile

The research design plan should not create a second filing architecture. F156 owns reader architecture. This plan only defines where the focused reader launches from, how it returns to the workspace, and how agent/notes/citations stay reachable.

No silent reader fallback: if the primary filing reader is missing, unsupported, identity-unresolved, or errored, the UI must say that explicitly and then offer extracted/corpus text as a diagnostic fallback. The user must not be led to believe extracted text is the filing. During migration, any legacy wire shape such as `render_surfaces.source_html` and frontend shape such as `renderSurfaces.sourceHtml` should be normalized behind the F156 `primary_reader` / `diagnostic_surfaces` model rather than expanded as a new public contract.

### D5. Structured output should be typed where possible

Metric strips, peer tables, source chips, mini charts, and action links should not rely only on brittle markdown heuristics over time. The long-term direction is typed research-output blocks rendered by shared Hank design components.

### D6. Every result leads somewhere

Exit ramps are a design principle, not decoration. Each should either navigate with context, seed the analyst rail with a useful prompt, or open the relevant artifact.

## 5. Workstream Process

This should proceed as a staged design-alignment program, not one large rewrite.

### Phase 0 - Refresh the baseline

Purpose: create a reliable current-state comparison before implementation.

Deliverables:

- Capture screenshots for:
  - Research list
  - MSFT/AAPL workspace Explore tab
  - A named Thread tab
  - Document reader with source HTML available
  - Document reader with corpus fallback
  - Diligence tab
  - Handoff/report tab
  - Compare view
- Reconcile `RESEARCH_WORKSPACE_AUDIT.md` against current code and mark:
  - closed
  - partially closed
  - still open
  - superseded by F156/F122
- Produce a small "current vs target" visual matrix.

Exit criteria:

- We know which divergences are still real.
- We have a shared order of operations.
- We avoid assigning work that the F156/F122 sessions already own.

### Phase 1 - Workspace shell and hierarchy

Purpose: make the existing research workspace read as the preview's IDE surface.

Candidate scope:

- Simplify header stacking and reduce competing context rows.
- Normalize top dateline/context treatment.
- Align tab bar with the flat IDE-style preview.
- Clarify main-pane vs right-rail purpose.
- Adjust right rail density and hierarchy so it is contextual, not a second equally weighted feed.
- Align exit ramp row styling and placement.
- Keep direction, strategy, and conviction controls, but move or quiet them so they do not dominate first impression.

Implementation guardrails:

- Limit this phase to the normal workspace shell, tab bar, right rail hierarchy, metadata/context treatment, and exit ramp presentation.
- Do not modify `DocumentTab`, `SourceHtmlPane`, source HTML fetching, anchor mapping, or the filing-reader branch in `ResearchWorkspace.tsx`.
- The only filing-reader-adjacent changes allowed in this phase are labels, launch/back-link wording, or navigation placement explicitly approved against F156.

Non-goals:

- Do not redesign the filing reader architecture.
- Do not change research persistence.
- Do not remove diligence/report functionality.

Acceptance:

- A user can tell immediately what the active artifact is.
- A user can tell what the analyst rail is for.
- The shell visually aligns with the preview without losing current actions.

### Phase 2 - Research list as briefing surface

Purpose: make `#research` feel like Hank triaging active research.

Candidate scope:

- Add a compact deterministic analyst briefing above the controls/table using existing `ResearchFile` fields only.
- Preserve the dense table.
- Keep create-file and compare flows but reduce their first-impression weight.
- Make stale files, decision-ready files, flagged threads, and incomplete diligence easier to scan.
- Keep stage/sort/filter controls, but make them secondary to the briefing.

First-viewport requirements:

- The dateline and analyst briefing appear before create/filter/compare controls.
- `Start new research ->` is a text action attached to the briefing, not a dominant filled/outlined button.
- The dense table header and at least the first rows are visible on a desktop first viewport.
- Create, filter, sort, and compare controls do not lead the page. They may sit in a compact secondary row, disclosure, or lower section.

Acceptance:

- The first viewport answers what needs attention.
- The list still supports repeated operational use.
- Compare and open flows remain quick.

### Phase 3 - Conversation, threads, notes, and findings

Purpose: align active research artifacts with the preview's "threads emerge from exploration" model.

Candidate scope:

- Standardize author distinction:
  - user message: dim bullet / no heavy rail
  - agent message: accent rail
  - user note: dim rail and explicit note label
  - system/tool rows: compact and secondary
- Review branch/start-thread action copy and placement.
- Make pinned findings visually distinct from thread labels.
- Consider collapsed history for older thread content.
- Improve thread naming and default names.
- Clarify when the rail is showing workspace context vs active thread conversation.

Minimum visual requirements:

- Metric strips use mono labels/values, hairline separators, and tabular numbers.
- Financial tables use mono uppercase headers, numeric right alignment, ticker emphasis, and restrained borders.
- Branch/open actions render as text links with accent arrows, not bordered buttons in the default state.
- User notes have their own visual treatment distinct from normal user chat.
- Pinned findings use an explicit `Finding` label and should read like a conclusion, not a thread title.

Acceptance:

- Exploration, thread, and note content feel related but distinct.
- Threads feel like focused workstreams, not renamed chats.
- Tool and system mechanics stay out of the analyst voice.

### Phase 4 - Document reader integration

Purpose: integrate the F156 filing reader into the research workspace model.

Candidate scope:

- Define launch/return behavior from workspace tabs to focused filing reader.
- Ensure the active filing identity, section, source link, and research file context are visible.
- Keep notes, selected-text ask flow, thread creation, and annotation capture.
- Reposition corpus text as fallback/diagnostic according to F156.
- Define how document-context prompts appear in the right rail or reader sidecar.

Document interaction contract:

- Selecting text creates an obvious ask/save/branch affordance in the rail or reader sidecar without covering the filing text.
- Agent highlights render as subtle inline annotations or notes tied to the visible passage when F156 anchor/mapping support exists.
- User notes and citations remain reachable from the reading flow without permanently shrinking the filing below F156 width gates.
- Corpus diagnostics and extracted-text fallback never appear as primary toolbar items in the normal reader path.

Coordination:

- F156 owns the reader architecture, anchor mapping, and SEC visual parity.
- This plan owns the surrounding workspace fit and navigation semantics.
- Do not implement a second embedded filing mode here. The intended steady state is the F156 first-class reader shell; any interim embedded state must be explicitly temporary and visually subordinate to that target.

Acceptance:

- Opening a filing feels like reading a filing, not inspecting a corpus export.
- The user can return to the research workspace without losing context.
- Agent/citation/notes flows continue to work.
- Missing or invalid source HTML degrades honestly with a clear reason before exposing extracted text.

### Phase 5 - Report, artifact, and structured output alignment

Purpose: align downstream outputs with the research IDE model.

Candidate scope:

- Polish handoff/report as a frozen analyst artifact.
- Keep version history and decision log available but secondary.
- Coordinate with F122 so HTML artifacts appear as Workbench/artifact tabs without competing with document tabs.
- Move toward typed research-output blocks for metrics, peer tables, charts, and action links.

F122 dependency boundary:

- Do not implement Workbench, artifact tab/store state, `/api/html-artifacts` proxying, SSE `artifact_ready`, iframe sandboxing, or artifact renderer components in this plan.
- This plan may reserve layout semantics for where Workbench/artifact tabs sit and may consume F122 outputs after the F122 PR sequence lands.

Acceptance:

- Reports read like research conclusions, not JSON viewers.
- HTML artifacts feel like research outputs inside the workspace.
- Structured data is rendered consistently across chat, report, and artifacts.

## 6. Proposed Implementation Sequencing

The safest order is:

1. Phase 0 audit refresh.
2. Decide the right-rail/main-pane contract.
3. Phase 1 shell alignment.
4. Phase 2 list briefing.
5. Phase 3 conversation/thread visual model.
6. Phase 4 filing reader fit, coordinated with F156.
7. Phase 5 report/artifact/typed-output alignment, coordinated with F122.

Reasoning:

- Shell hierarchy affects every research view, so it should come before detailed polish.
- The list is independent enough to ship after shell decisions.
- Conversation/thread polish depends on the rail contract.
- Filing reader work should not be rushed while F156 is active.
- Typed output is valuable, but it is a broader renderer contract and should not block shell clarity.

## 7. Verification Process

Each implementation phase should include:

- Focused unit/component tests for changed behavior.
- Playwright visual checks at fixed viewports:
  - desktop: 1440 x 900
  - wide desktop: 1880 x 1000
  - narrow/mobile: 390 x 844 or nearest supported viewport
- For preview-backed states, capture three-way comparison screenshots:
  - original preview state
  - current pre-change app state
  - post-change app state
- Live local walk-through on representative routes:
  - `#research`
  - `#research/MSFT`
  - `#research/AAPL`
  - `#research/compare/...`
  - one document reader route/state
  - one diligence/report state when available
- Screenshot capture before and after.
- Store screenshots under `/tmp/research-surface-alignment-<YYYYMMDD-HHMMSS>/` or an equivalent review artifact directory, with phase, route, and viewport in each filename.
- Explicit check that no F156/F122-owned architecture was duplicated or bypassed.
- Existing focused research tests must pass for touched areas.

Visual review should look for:

- active artifact is obvious
- rail purpose is obvious
- main pane and rail have distinct labels and visual weight
- no nested cards inside cards
- no card quilt in the research first viewport or workspace shell
- controls do not lead the page where the preview leads with context/briefing
- no control text overflow
- no overlapping text or incoherent wrapping at target viewports
- no dense diagnostics in the primary path
- exit ramps are styled as text links with accent arrows
- notes/citations/source links remain reachable
- preview comparison notes exist for the equivalent preview view when one exists

Preview states that must receive named pass/fail notes when touched:

- Exploration Mode
- Document Reading
- Thread View
- Research List

Filing-reader-specific verification, when a phase touches reader launch or surrounding fit, inherits F156 gates:

- sidecar collapsed by default on first filing entry
- diagnostics/fallback controls are secondary
- source HTML unavailable states are explicit
- desktop filing width gates are measured
- same-origin source route and embedded/focused reader screenshots are compared

## 8. Coordination Rules

- Do not edit F156 reader architecture while another session owns that track unless explicitly coordinated.
- Do not implement F122 Workbench/artifact renderer pieces from this plan unless that workstream is assigned here; no proxy, SSE, store, Workbench, sandbox, or renderer work belongs to this plan.
- Avoid broad fallbacks. If a UI flow fails, identify the actual state/contract mismatch.
- Do not add silent UI fallbacks. Degraded states need user-visible reason text and should distinguish product surface from diagnostics.
- Keep changes small enough for visual review after each phase.
- Preserve current working functionality unless the design review explicitly decides an affordance should be removed or hidden.

## 9. Open Design Decisions

1. Right rail contract:
   - The default contract is defined in D2. Review should either confirm it or explicitly revise the table before Phase 1 implementation.
2. Metadata controls:
   - Default for Phase 1: metadata appears as a quiet secondary context row or details affordance. Editable segmented controls should not lead the workspace first viewport. Review may revise exact placement before implementation.
3. Research list briefing:
   - V1 is deterministic from existing metadata. The open decision is copy/ordering, not whether to create a new editorial endpoint.
4. Filing reader transition:
   - F156 locks the first-class filing reader shell. The open decision is only the interim behavior for non-filing documents and partially migrated filing states.
5. Typed output:
   - Should chat structured blocks reuse handoff/report renderers, or should there be a shared `ResearchOutputBlock` contract?
6. Diagnostics:
   - Where should corpus text, source HTML diagnostics, and fallback controls live once the reader path stabilizes?

## 10. First Review Agenda

Use the opened preview and current live surface side by side.

Review in this order:

1. Confirm the right-rail/main-pane contract.
2. Confirm the desired first viewport for `#research`.
3. Confirm which current features must remain visible vs tucked away.
4. Mark F156/F122 boundaries as blocked/owned-by-other-session.
5. Pick the first implementation slice after design agreement.

Recommended first implementation slice after agreement:

```text
Research workspace shell hierarchy:
  header/context simplification,
  tab bar alignment,
  right rail role clarity,
  exit ramp styling,
  no filing-reader architecture changes.
```

This slice is large enough to make the workspace feel aligned, but small enough to avoid stepping on the active HTML reader architecture work.

## 11. Locked Path Forward

After architecture and visual review, the plan resolves into the following concrete action set.

### A. Architecture / coordination actions

1. Treat the authority table in Section 1 as binding for implementation review.
2. Keep F156 as the sole owner of the first-class filing reader shell, anchor mapping, SEC parity gates, and primary-reader contract.
3. Keep F122 as the sole owner of Workbench/artifact tab/store/proxy/SSE/sandbox/renderer implementation.
4. In this plan, consume F156/F122 surfaces only through launch/return semantics, layout placement, and visual fit.
5. Preserve per-user research architecture and `research_file_id` identity. Do not add new persistence paths for design-only alignment work.
6. Normalize legacy reader surface naming toward F156 (`primary_reader` / `diagnostic_surfaces`) when reader-adjacent work is assigned, and never add silent fallback behavior.

### B. First implementation slice

Scope: Research workspace shell hierarchy only.

Allowed work:

- Simplify normal workspace header/context stacking.
- Make dateline/context treatment match the research visual contract.
- Convert research tabs toward the flat IDE tab style.
- Apply the right-rail contract for Explore/Thread states.
- Rework exit ramp presentation to text links with accent arrows.
- Quiet direction/strategy/conviction controls into a secondary context row or details affordance.

Explicitly out of scope:

- `DocumentTab`
- `SourceHtmlPane`
- source HTML fetching
- filing-reader shell/route architecture
- F122 Workbench/artifact implementation
- research persistence or API changes

### C. Second implementation slice

Scope: Research list first viewport.

Allowed work:

- Add deterministic client-side analyst briefing from existing `ResearchFile` metadata.
- Place dateline, briefing, `Start new research ->`, and dense table first.
- Move create/filter/sort/compare controls into secondary treatment.
- Preserve existing create, open, compare, filter, and sort functionality.

### D. Third implementation slice

Scope: Conversation/thread visual fidelity.

Allowed work:

- Apply author distinction rules.
- Convert branch/open actions to text links with accent arrows.
- Tighten metric strips and financial tables to preview grammar.
- Improve pinned finding and note treatments.
- Keep tool/system output visually secondary.

### E. Deferred / coordinated slices

- Filing reader fit: coordinate with F156 after or alongside the reader-shell owner.
- Report/artifact/typed-output alignment: coordinate with F122 and any typed-output contract work.
- Editorial/LLM research-list briefing: separate future plan after deterministic v1 proves useful.

### F. Review gate before implementation starts

Before any code work starts, review and confirm:

1. Right-rail contract in D2.
2. Research list first-viewport order.
3. Metadata control placement default.
4. F156/F122 ownership boundaries.
5. Screenshot/verification directory convention.

## 12. Implementation Checkpoints

### 2026-05-27 Phase 1 shell alignment

First committed pass: `7f061058 Align research workspace surface`.

Follow-up batch status:

- Route-level research padding removed so the workspace starts flush with the Hank content column.
- Workspace frame flattened to border bands rather than an inset rounded card.
- Metadata controls moved behind a quiet `Framing` disclosure for the normal workspace path.
- Tab bar tightened toward flat IDE-style tabs with single-line labels.
- Right rail shifted from operational logs toward analyst read, evidence excerpts, and lower-priority workspace state.
- Main composer and exit-ramp footer reduced so the thread/feed keeps the visual weight.
- Non-document collapsed `Ask analyst` affordance keeps focus while typing and does not jump into the full composer after the first character.

Verification:

- Focused research component tests: `49 passed`.
- Scoped ESLint: pass with `--max-warnings=0`.
- Frontend typecheck: pass.
- Live local smoke on `http://localhost:3000/#research/MSFT`: no horizontal overflow; workspace flush at the content column; right rail about 264px; compact footer about 20px high; collapsed analyst composer remained visible while typing.

Open follow-ups:

- `docs/TODO.md` tracks the dedicated research workspace shell-mode decision for suppressing/minimizing global Hank chrome. This is an architectural shell choice, not a component-level Phase 1 blocker.
- Document-reader-specific wording, tab filtering, and filing-reader header placement remain under the F156 boundary. Treat any current reader changes as coordinated reader-track work, not part of this normal-workspace shell batch.

### 2026-05-27 Phase 1 preview-detail alignment

Second follow-up batch status:

- Research preview HTML is now stored in-repo at `docs/design/research-workspace-preview.html`.
- Conversation chrome uses the workspace visual mode for quieter empty states, preview-style user-note treatment, and raw tool-call suppression where explicitly requested.
- Thread chrome is separated from workspace suppression: focused thread timelines can use flatter visual treatment while preserving author/timestamp metadata and tool-call history.
- Thread pinned findings use a flat border band treatment after review, rather than a raised card block.
- Analyst rail state is demoted from dashboard-style workspace status blocks toward contextual evidence excerpts and lightweight cross-reference actions.
- Research list desktop table now follows the preview's `Ticker` / `Company` structure, keeps direction/stage/strategy/conviction/thread/update data, and preserves compare/open functionality with visible text row actions.
- Compare view, metric strips, and markdown tables were flattened further toward hairline preview styling.

Verification:

- Focused research component tests: `81 passed`.
- Scoped ESLint: pass.
- Frontend typecheck: pass.
- `git diff --check`: pass for the scoped research UI/design files.
- Live local smoke: `#research/MSFT` Explore and Thread loaded; `#research` rendered preview-style list columns after data load. Screenshots captured under `/tmp/research-msft-explore-ui-batch3.png`, `/tmp/research-msft-thread-ui-batch3.png`, and `/tmp/research-list-ui-batch4.png`. Later thread/feed review tightened the thread history preservation contract.

Open follow-ups:

- Document-reader files and filing/source HTML reader behavior remain out of this batch and under F156 ownership.
- The dedicated shell-mode decision remains tracked in `docs/TODO.md`; global Hank side chrome still frames the research surface.

### 2026-05-28 Phase 1 exit-ramp visibility alignment

Follow-up batch status:

- Normal non-document research workspace paths now render primary exit ramps as a visible bottom text-link row, matching the preview's low-friction `Size a position ->` / `Stress test ->` / downstream action treatment.
- The top `Actions` disclosure now contains only secondary workflow actions such as `Form thesis`, `Generate report`, or `Open report`, so core scenario/trading/compare exits no longer require opening a menu.
- Document-reader footer behavior remains separately gated and unchanged for the F156-owned reader path.
- Phase 3 coverage now asserts primary exit ramps are directly clickable from the visible row and remain visible on the active handoff/report tab even when no secondary `Actions` disclosure is present.

Verification:

- Focused research workspace Phase 3 tests: `20 passed`.
- Broad research component pack: `18 files / 157 tests passed`.
- Targeted ESLint for changed workspace files: pass with `--max-warnings=0`.
- `git diff --check` for changed workspace files: pass.
- Live local smoke on `http://localhost:3000/#research/MSFT`: primary exit ramps visible and text-link styled, no console errors, no horizontal overflow at 1440x900, 1880x1000, or 390x844. Screenshots captured under `/tmp/research-surface-alignment-20260528-exit-ramps/`.
- Code review subagent: PASS after the handoff-tab assertion was added.
- Visual review subagent: PASS against `docs/design/research-workspace-preview.html`.

Known unrelated verification limit:

- Package UI typecheck still fails on the existing reader-track `ResearchWorkspacePhase2.test.tsx` fixture where `activeSection: undefined` is not assignable to `string | null`. This batch did not touch that F156/document-reader lane.

### 2026-05-28 Phase 2 compare-context alignment

Follow-up batch status:

- The compare route header now uses the same preview-style context line as the list/workspace surfaces: dateline plus `Research Comparison`.
- Compare file-open actions now use text-link action language with muted text and an accent arrow (`Open MSFT ->` visually as `Open MSFT →`), instead of all-accent mono labels without arrows.
- Existing compare functionality was preserved: back-to-files, open-file actions, side-by-side overview, report snapshots, thesis/catalyst/risk sections, and decision logs.

Verification:

- Focused compare component tests: `4 passed`.
- Non-reader research component pack excluding the reader-track Phase 2 file: `17 files / 122 tests passed`.
- Targeted ESLint for changed compare files: pass with `--max-warnings=0`.
- `git diff --check` for changed compare files: pass.
- Live local smoke on `http://localhost:3000/#research/compare/88,87`: dateline/context rendered, `Back to files`, `Open MSFT`, and `Open AAPL` remained visible, no console errors, no horizontal overflow. Screenshots captured under `/tmp/research-surface-alignment-20260528-compare-dateline/`.
- Code review subagent: PASS.
- Visual review subagent: PASS after the action-arrow and context-size findings were addressed.

Known unrelated verification limit:

- The full research component pack currently fails only in the reader-track `ResearchWorkspacePhase2.test.tsx` assertions that expect `title="Filing"` while the current reader fixture renders `title="Filing: Cover Page"`. This remains under the document-reader/F156 lane.

Boundary:

- This batch did not touch document-reader, source HTML, F156, or F122-owned files.

### 2026-05-28 Phase 5 report-action polish

Follow-up batch status:

- The report header `New Version` action now uses the same flat text-link language as the rest of the aligned research surface: muted label, accent arrow, transparent background, no outline frame.
- The create-new-version behavior and pending disabled state are preserved.

Verification:

- Focused report review tests: `4 passed`.
- Targeted ESLint for changed report files: pass with `--max-warnings=0`.
- `git diff --check` for changed report files: pass.
- Live local smoke on `http://localhost:3000/#research/MSFT`: opened the report tab, confirmed `New Version→` visible with flat/muted styling, no console errors. Screenshot captured under `/tmp/research-surface-alignment-20260528-report-action/`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Boundary:

- This batch did not touch document-reader, source HTML, F156, or F122-owned files.

### 2026-05-28 Phase 5 locked-diligence action polish

Follow-up batch status:

- The locked diligence `Create New Version` action now uses the same flat text-link language as the report/workspace actions: muted label, accent arrow, transparent background, and no outline frame.
- The primary diligence action class remains unchanged for confirm/finalize actions; the locked-state action uses a separate `diligenceLinkActionClass` helper.
- The create-new-version behavior, disabled pending state, and accessible name are preserved.

Verification:

- Focused Diligence + finalize action tests: `11 passed`.
- Targeted ESLint for changed Diligence files and shared helper: pass with `--max-warnings=0`.
- `git diff --check` for changed Diligence files: pass.
- Code review subagent: PASS after `diligenceStyles.ts` was explicitly included in scope.
- Visual review subagent: PASS after the label color was changed from primary/accent to muted with accent-only arrow.

Boundary:

- This batch did not touch document-reader, source HTML, F156, or F122-owned files.

### 2026-05-28 Phase 2 list action-link grammar

Follow-up batch status:

- Research-list primary actions now consistently use the preview action-link grammar: muted label, accent-only arrow, transparent background, and no border frame.
- Covered actions: `Start new research`, `New File`, `Retry`, `Open comparison`, and desktop/mobile row `Open`.
- Create, retry, compare, row open, mobile open, sorting, filtering, direction metadata, thread metadata, and briefing behavior are preserved.

Verification:

- Focused research-list tests: `8 passed`.
- Non-reader research component pack excluding the reader-track Phase 2 file: `17 files / 124 tests passed`.
- Targeted ESLint for changed list files: pass with `--max-warnings=0`.
- `git diff --check` for changed list files: pass.
- Live local smoke on `http://localhost:3000/#research`: desktop list rendered live data with `Start new research→` and `Open comparison→`, no console errors, no horizontal overflow.
- Live mobile smoke at 390x844: create form rendered `New File→`; row `Open→` actions remained visible, no console errors, no horizontal overflow. Screenshots captured under `/tmp/research-surface-alignment-20260528-list-actions/`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Boundary:

- This batch did not touch document-reader, source HTML, F156, or F122-owned files.

### 2026-05-27 Phase 5 handoff/report alignment

Report follow-up batch status:

- Handoff/report review now presents the thesis as a frozen report lead instead of a raised dashboard card.
- Version history remains available, but is flattened into a secondary side rail with active-version accent treatment.
- Report snapshot, decision lens, decision log, and sources now use hairline report bands instead of repeated rounded cards.
- Build-model, export, download, retry, and status actions remain available, but render as secondary report actions rather than primary filled controls.
- Narrow/mobile report layout no longer traps the viewport on version history; the report body remains reachable in the normal document flow.

Verification:

- Focused handoff tests: `46 passed`.
- Broader research component pack: `128 passed`.
- Scoped ESLint: pass.
- Frontend typecheck: pass.
- `git diff --check`: pass for the scoped report files.
- Live local smoke on `#research/MSFT`: opened `Report v6` from the overflow tab menu; DOM verified `Research Report v6`, `Report Snapshot`, decision lens, downstream actions, sources, and report sections are present. Browser screenshot capture timed out on this page, so visual evidence is DOM + live in-app observation rather than a saved screenshot.

Open follow-ups:

- Report content still depends on the existing handoff artifact shape; typed output block convergence remains a later cross-surface task.
- F122 Workbench/artifact tabs remain out of scope until that implementation lands.

### 2026-05-27 Phase 5 report action ergonomics

Report action follow-up batch status:

- Build model, export JSON, download model, retry build, and retry annotations keep the flat report-action visual style but now have practical `min-h-7` hit targets.
- Build/export/download behavior and persisted model-ref download visibility are unchanged.

Verification:

- Focused build/report tests: `10 passed`.
- Scoped ESLint: pass.
- `git diff --check`: pass for scoped report-action files.

Open follow-ups:

- Full frontend typecheck remains blocked by the unrelated reader-track fixture noted in the container-state checkpoint.

### 2026-05-27 Phase 5 diligence alignment

Diligence follow-up batch status:

- Diligence header, pre-population notice, finalized state, and version creation action now use flat report/workspace bands rather than raised cards.
- Editable diligence sections now render as accordion rows with hairline preview grids, left-accent authorship, flat research-link bands, and text actions for save/confirm.
- Opening take and qualitative factor surfaces were flattened to the same report grammar while preserving generate/refresh/add/update/remove behavior.
- Diligence status badges were squared off to match the preview's compact metadata treatment.
- Review follow-up tightened flat action hit targets, disabled duplicate draft refresh while pre-population is active, associated qualitative-factor form labels, and softened research links into inline related actions.

Verification:

- Focused Diligence tests: `10 passed`.
- Broader research component pack: `140 passed`.
- Scoped ESLint: pass.
- Frontend typecheck: pass.
- `git diff --check`: pass for scoped Diligence/report-plan files.
- Live local smoke on `#research/MSFT`: opened Diligence from overflow, verified the finalized/locked state, then created local draft handoff v7 and verified editable Diligence signals (`Draft handoff`, `Opening Take`, `Business Overview`, `Working Notes`, `Qualitative Factors`, related links, save/confirm, refresh/finalize) with no console errors. Screenshots captured under `/tmp/risk-module-diligence-smoke.png`, `/tmp/risk-module-diligence-editable-smoke.png`, and `/tmp/risk-module-diligence-editable-smoke-after-review.png`.

Open follow-ups:

- The smoke created a local MSFT handoff draft v7 from the finalized report state; this is app data, not a code migration.
- Document-reader files and source/filing HTML reader behavior remain out of this batch and under F156 ownership.

### 2026-05-27 Phase 5 editorial brief alignment

Editorial brief follow-up batch status:

- `ResearchBriefSection` now renders ready, loading, and error states as flat report bands rather than raised rounded cards.
- Editorial slot candidates keep the same fixed order and source/why affordances, but use stacked hairline rows and bracketed source tokens to avoid cramped prose columns in the report pane.
- The brief remains optional: 204/known-404 responses still hide the section entirely.

Verification:

- Focused brief/report tests: `13 passed`.
- Broader research component pack: `149 passed`.
- Scoped ESLint: pass.
- Frontend typecheck: pass.
- Live local report smoke on `#research/MSFT`: opened the report path after local v7 finalization; the real local handoff currently has no brief data, so the optional section stayed hidden with no console errors. A second smoke intercepted only `/api/research/content/handoffs/*/brief` with ready sample data and verified `Editorial Brief`, headline, three stacked slot rows, bracketed source tokens, no `rounded-[8px]` brief shells, and no console errors. Screenshots captured under `/tmp/risk-module-report-brief-intercept-smoke.png` and `/tmp/risk-module-report-brief-intercept-smoke-after-review.png`.

Open follow-ups:

- Real brief availability depends on the backend/editorial pipeline producing a brief for the handoff; the UI continues to hide absent briefs intentionally.

### 2026-05-27 Phase 1 container-state alignment

Container-state follow-up batch status:

- `ResearchWorkspaceContainer` loading and error states now use flat workspace bands instead of `Card`/`CardContent` wrappers.
- Compare-route and bootstrap error actions remain available, but render as text-style workspace actions.
- Loading route states now announce as `status`, error route states announce as `alert`, and long bootstrap error text wraps inside the flat band.
- Compare/list/detail routing behavior and addressable reader-route opening were left unchanged.

Verification:

- Focused container tests: `11 passed`.
- Broader research component pack: `152 passed`.
- Scoped ESLint: pass.
- Frontend typecheck: blocked by an unrelated dirty reader-track fixture in `ResearchWorkspacePhase2.test.tsx` (`activeSection: undefined` no longer satisfies `DocumentTabData`); this file is under the F156/document-reader boundary and was not modified in this batch.
- `git diff --check`: pass for scoped container files.
- Live local smoke on `#research/compare/999999,999998` with intercepted 404 file lookups verified the flattened compare error state and `Back to research files` action. The expected injected 404 network logs appeared; no runtime page errors were observed. Screenshot captured under `/tmp/risk-module-container-error-smoke.png`.

Open follow-ups:

- This batch only covers transient route states. It does not alter document-reader route handling or reader UI.

### 2026-05-27 Phase 1 thread/feed action ergonomics

Thread/feed follow-up batch status:

- `ThreadTab` flat actions now have practical `min-h-7` hit targets without adding filled button chrome.
- `ConversationFeed` inline actions (`Start thread`, `Open in tab`) keep their flat text-action treatment while also using `min-h-7` hit targets.
- Thread feed chrome is now explicitly separate from workspace suppression chrome, so focused thread timelines preserve author/timestamp metadata and tool-call history.
- The pinned finding header remains a flat border band, not a rounded or raised card.

Verification:

- Focused thread/feed tests: `6 passed`.
- Broader research component pack: `155 passed`.
- Frontend typecheck: still blocked by the unrelated reader-track fixture in `ResearchWorkspacePhase2.test.tsx` (`activeSection: undefined` no longer satisfies `DocumentTabData`); this file remains under the F156/document-reader boundary and was not modified.
- `git diff --check`: pass for scoped thread/feed files.
- Live local smoke on `#research/MSFT`: opened the `Valuation Deep Dive` thread and verified `Pin Finding` renders as a flat 28px action and the finding section class is `mx-4 mt-4 border-b border-border-subtle pb-4`. The current local MSFT thread had no visible tool-call row, so tool-history preservation is covered by the new `ConversationFeed` test.

Open follow-ups:

- This batch only covers thread/feed action ergonomics and thread chrome separation. It does not alter document-reader route handling, document tabs, filing rendering, or source HTML reader behavior.

### 2026-05-27 Phase 1 list action ergonomics

Research list follow-up batch status:

- Remaining research-list text actions (`Start new research`, `Retry`, `Clear`, `Open comparison`) now use flat `min-h-7` action treatment.
- `New File` keeps its outline affordance but now uses a squared `min-h-8` control.
- Inline create failures render as border-y error notices instead of rounded alert cards, while preserving the draft ticker and error copy.
- Mobile research-file rows now use flat hairline row treatment instead of rounded file cards, while preserving visible `Compare` / `Open` actions.
- Desktop research rows preserve visible `Direction` metadata and text row actions after review flagged those as preserve-functionality requirements.
- The obsolete unreferenced `ResearchFileCard` component was removed so the old rounded-card list model is no longer kept as a parallel implementation path.

Verification:

- Focused list tests: `8 passed`.
- Broader research component pack: `157 passed`.
- Frontend typecheck: still blocked by the unrelated reader-track fixture in `ResearchWorkspacePhase2.test.tsx` (`activeSection: undefined` no longer satisfies `DocumentTabData`).
- `git diff --check`: pass for scoped list files.
- Live local smoke on `#research`: verified the table renders and `Start new research` / `Open comparison` are transparent 28px actions. The create-error notice is covered by unit tests rather than a live create failure.
- Mobile live smoke: unmocked `#research` still hit the known local credential resolver 503; an intercepted preflight/files smoke verified two mobile rows, `border-y` wrapper, `border-b` rows, and flat `min-h-7` compare/open actions. Screenshot captured at `/tmp/research-list-mobile-row-intercept-smoke-after-review.png`.
- Desktop intercepted smoke verified `DIRECTION`, `Long`, `Watch`, and visible `COMPARE` / `OPEN` text actions.
- Review loop: code and visual reviewers initially flagged desktop `Direction`/text-action loss; both findings were fixed and follow-up reviews passed.
- Dead-code cleanup: repository search confirmed no `ResearchFileCard` imports/usages before deletion; focused list tests still pass after removal.

Open follow-ups:

- This batch only covers list action ergonomics and create-error presentation. It does not alter research-file persistence, compare routing, or reader/document behavior.
- Any commit containing this plan reference must include `docs/design/research-workspace-preview.html`; it is the repo-local replacement for the original gstack preview path.

### 2026-05-27 Report renderer follow-up triage (superseded 2026-05-29)

Original finding:

- At the time, `HandoffSectionRenderer` had several specialized rounded card/chip treatments inside nested typed-output sections. That was real visual drift, but it was not a safe opportunistic component polish because it cut across report-body semantics, handoff artifact shapes, tests for specialized sections, and the F122 artifact-renderer boundary.

Current disposition:

- The component-level flat pass has now shipped and is recorded in the later 2026-05-29 checkpoints: nested report rows, tables, metric strips, source triggers, badges, and model/status bands have preview-aligned flat chrome while preserving report artifact semantics.
- `docs/TODO.md` now marks `Research report typed-output renderer convergence` as `COMPONENT FLAT PASS SHIPPED 2026-05-29 - F122 CONVERGENCE STILL SEPARATE`.
- The remaining work is not a normal research-surface polish batch: it is the broader F122 Workbench/artifact renderer convergence decision covering shared renderer ownership, source-chip grammar, provenance interactions, and typed-output fallback behavior.

### 2026-05-27 Phase 1 upgrade-state alignment

Upgrade-state follow-up batch status:

- `UpgradeSurface` keeps the shared Pro upsell prompt intact, but the research-specific access note now renders as a flat dashed border band instead of a rounded raised panel.

Verification:

- Focused upgrade-surface test: `1 passed`.
- Broader research component pack: `156 passed`.
- `git diff --check`: pass for scoped upgrade files.

Open follow-ups:

- The shared `UpgradePrompt` component still uses the app-wide card primitive and was intentionally left alone because it is used outside the research surface.

### 2026-05-27 Phase 1 compare action ergonomics

Compare follow-up batch status:

- `ResearchCompareView` file-open actions now use the same flat `min-h-7` text-action treatment as the rest of the research workspace.
- `Back to files` now renders as a flat secondary action instead of a boxed outline control.
- Compare routing and report/history loading behavior are unchanged.

Verification:

- Focused compare tests: `4 passed`.
- Broader research component pack: `156 passed`.
- `git diff --check`: pass for scoped compare files.
- Live local smoke on `#research/compare/88,87`: verified `Back to files`, `Open MSFT`, and `Open AAPL` render as transparent 28px actions while real comparison/report/history content remains visible.

Open follow-ups:

- This batch only covers compare-view action ergonomics. It does not alter compare data loading, report rendering semantics, or document-reader behavior.

### 2026-05-27 Phase 1 analyst rail related-thread ergonomics

Analyst rail follow-up batch status:

- Related-thread cross-reference buttons in the analyst rail now use flat `min-h-7` hit targets while preserving their text-link treatment and active-tab behavior.
- Added a focused `AgentPanel` test for the related-thread rail action instead of editing the reader-heavy `ResearchWorkspacePhase2.test.tsx` fixture.

Verification:

- Focused `AgentPanel` test: `1 passed`.
- Broader research component pack: `157 passed`.
- `git diff --check`: pass for scoped rail files.
- Live local smoke on `#research/MSFT`: the workspace loaded without bootstrapping/error state; after opening `Thread 1`, the analyst rail showed `Related Threads` and the cross-reference action rendered as a flat wrapping `min-h-7` text control. Screenshot captured at `/tmp/research-agentpanel-thread-smoke.png`.
- Review loop: initial code review flagged an out-of-scope `Current Work` rail block. The block and its matching uncommitted assertions were removed; follow-up code and visual reviews both passed.

Open follow-ups:

- This batch only covers analyst-rail related-thread action ergonomics. It does not alter document-reader behavior, panel-thread message routing, or research chat execution.

### 2026-05-28 Phase 1 research list entry-point hierarchy

Research list entry-point follow-up batch status:

- The list now follows the preview order more closely: standalone dateline/context row, briefing readout, then `Start new research ->` as a flat text action under the briefing.
- Filters, sort, compare status, open-comparison action, table density, mobile row actions, create flow, retry flow, and compare routing remain intact.
- Tablet widths now keep the row layout through the `lg` breakpoint so the visible `Compare` / `Open` controls are not clipped by the dense 9-column table.
- Desktop company fallback now uses `Research file` instead of duplicating ticker/title in the split `Ticker` / `Company` table columns.

Verification:

- Focused `ResearchListView` tests: `9 passed`.
- Targeted ESLint for `ResearchListView` and its test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `17 files / 123 tests passed`.
- `git diff --check`: pass for scoped list files.
- Live local smoke on `#research`: desktop 1440 renders the dense table; tablet 768 and mobile 390 render row layout; all three have no console/page errors and no horizontal overflow. Screenshots captured under `/tmp/research-surface-alignment-20260528-list-entry/`.
- Review loop: code reviewer flagged the company fallback and visual reviewer flagged tablet table clipping. Both findings were fixed; follow-up code and visual reviews passed.
- Retry cleanup addendum: load-error `Retry->` now uses the same ghost/text-link action grammar as the rest of the list. Focused list tests still pass, and an intercepted 503 smoke verified transparent background, no border, muted text, accent arrow, 28px min-height, and no overflow. Screenshot captured at `/tmp/research-surface-alignment-20260528-list-retry/research-list-retry-1440x900.png`; the only console errors were the intentionally injected 503. Code and visual review subagents passed.

Open follow-ups:

- This batch only covers research-list visual hierarchy and responsive fit. It does not alter research-file persistence, compare routing, or reader/document behavior.

### 2026-05-28 Phase 5 report downstream action-link grammar

Report downstream-action follow-up batch status:

- `Build Model`, `Export JSON`, `Download Model`, `Retry Build`, and `Retry Annotations` now follow the report/list action-link grammar: muted label, accent-only arrow, transparent background, and no border frame.
- Build, export, download, retry-build, retry-annotation, pending, and disabled behavior remain unchanged.

Verification:

- Focused `BuildModelButton` tests: `6 passed`.
- Targeted ESLint for `BuildModelButton` and its test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `17 files / 124 tests passed`.
- `git diff --check`: pass for scoped report-action files.
- Live local smoke on `#research/MSFT`: opened the report through the workspace `Actions` disclosure and verified `Build Model->`, `Export JSON->`, and `Download Model->` render as transparent 28px actions with muted text, no console/page errors, and no horizontal overflow. Screenshot context captured under `/tmp/research-surface-alignment-20260528-report-actions/`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers report downstream actions. It does not alter `HandoffSectionRenderer`, report artifact semantics, F122, or document-reader/F156 behavior.

### 2026-05-28 Phase 1 feed action-link grammar

Feed action-link follow-up batch status:

- Inline feed actions (`Start thread: ...` and `Open in tab: ...`) now follow the preview's inline message-action grammar: normal-case 12px sans text, muted label, accent-only arrow, transparent background, and no button/card chrome.
- Start-thread branching and open-in-reader handler behavior remain unchanged.
- The action class explicitly uses normal letter spacing so it does not inherit negative tracking from surrounding UI.

Verification:

- Focused `ConversationFeed` citation/action tests: `4 passed`.
- Targeted ESLint for `ConversationFeed` and its test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `17 files / 124 tests passed`.
- `git diff --check`: pass for scoped feed-action files.
- Live local smoke on `#research/MSFT`: verified `Start thread: Sector & Industry->` renders with Instrument Sans, normal case, 12px font size, normal letter spacing, muted text, accent arrow, transparent background, 28px min-height, no console/page errors, and no horizontal overflow. Screenshot captured at `/tmp/research-surface-alignment-20260528-feed-actions/research-feed-actions-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS after the mono/uppercase/tracking finding was fixed.

Open follow-ups:

- This batch only covers inline feed action presentation. It does not alter document opening, thread creation logic, `DocumentTab`, `SourceHtmlPane`, or reader/F156 behavior.

### 2026-05-28 Phase 1 thread action tone alignment

Thread action-tone follow-up batch status:

- Focused thread `Pin Finding` now keeps the flat action hit target while shifting from all-accent text to muted label text with an accent pin icon.
- Collapsed thread history now reads as a quieter separator row: `▸ N earlier exchanges · See full thread`, 10px mono text, normal tracking, dim color, and no button chrome.
- Focused thread timelines explicitly pass `chrome="thread"` to `ConversationFeed` so author/timestamp metadata and tool-call history stay visible in thread tabs.
- Pin finding, expand/collapse history, and thread-history loading behavior remain unchanged.

Verification:

- Focused `ThreadTab` tests: `3 passed`, including metadata/tool-history preservation for focused thread chrome.
- Targeted ESLint for `ThreadTab` and its test: pass.
- Intercepted live smoke on `#research/MSFT` with deterministic research-content fixtures verified the pinned finding, muted flat `Pin Finding` action, accent pin icon, collapsed-history separator row, no console/page errors, and no horizontal overflow. Screenshot captured at `/tmp/research-surface-alignment-20260528-thread-tone/research-thread-tone-intercept-1440x900.png`.
- Real in-app browser visual check on local data opened the `Valuation Deep Dive` thread and verified the live pinned-finding state renders in the visible workspace. Screenshot captured at `/tmp/research-surface-alignment-20260528-thread-tone/in-app-real-thread-valuation-1440x900.png`.

Open follow-ups:

- This batch only covers focused thread action tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 workspace secondary action tone

Workspace secondary-action follow-up batch status:

- Normal workspace header `Actions` trigger and menu entries now use the same flat action-link grammar as the research list, feed, and report actions: muted label text, accent arrow, 12px normal tracking, transparent background, and a 28px hit target.
- Covered normal-workspace actions: `Form thesis`, `Generate report`, and `Open report`. The selection-driven `Start thread` action uses the same class but remains gated behind document selection and is not part of this reader-lane batch.
- Form-thesis, report-finalize, and report-open behavior remain unchanged.
- The disclosure panel was reduced from a bordered/shadowed dropdown to a content-width hairline menu so the single-action state no longer reads as heavy button chrome.

Verification:

- Focused `ResearchWorkspacePhase3` tests: `21 passed`.
- Targeted ESLint for `ResearchWorkspace` and the Phase 3 test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `18 files / 144 tests passed`.
- Real in-app browser visual check on local data opened `#research/MSFT`, expanded the workspace `Actions` disclosure, and verified `Actions 1->` and `Open report->` render as transparent, borderless, muted 12px text with normal tracking, 28px min-height, no overflow, and no browser warning/error logs. Final screenshot captured at `/tmp/research-surface-alignment-20260528-workspace-actions/in-app-workspace-actions-refined-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS after the trigger outline/typography/arrow and heavy-popover findings were addressed.

Open follow-ups:

- This batch only covers normal workspace secondary action tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal workspace back-action tone

Normal workspace header follow-up batch status:

- `Back to files` in the normal research workspace header now uses the same flat text-action grammar as the aligned `Actions` disclosure: muted 12px label, accent directional icon, transparent background, no border frame, no radius, and a 28px hit target.
- Document-reader header behavior was left on the existing reader-owned path and was not changed in this batch.
- Back-navigation behavior remains unchanged.

Verification:

- Focused `ResearchWorkspacePhase3` tests: `22 passed`.
- Targeted ESLint for `ResearchWorkspace` and the Phase 3 test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `18 files / 145 tests passed`.
- `git diff --check`: pass for scoped files.
- Real in-app browser visual check on local data opened `#research/MSFT` and verified `Back to files` renders transparent, borderless, 12px, normal tracking, 28px high, no overflow, and no console warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-header-back/in-app-header-back-loaded-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers the normal workspace header back action. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal workspace framing disclosure tone

Normal workspace framing follow-up batch status:

- `Framing` in the normal research workspace header now uses the same flat disclosure grammar as the aligned `Actions` control: muted 12px label, normal tracking, accent arrow, transparent background, no outline/box/shadow chrome, and a 28px trigger hit target.
- The opened metadata panel was reduced to a compact hairline details menu instead of a wide bordered/shadowed dropdown.
- Direction, strategy, and conviction controls remain the same segmented/dot controls and keep their existing update handlers.
- Document-reader header behavior was left on the existing reader-owned path and was not changed in this batch.

Verification:

- Focused `ResearchWorkspacePhase3` tests: `23 passed`.
- Targeted ESLint for `ResearchWorkspace` and the Phase 3 test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `18 files / 146 tests passed`.
- `git diff --check`: pass for scoped files.
- Real in-app browser visual check on local data opened `#research/MSFT`, expanded `Framing`, and verified a transparent 12px/28px trigger, compact 368px panel, no border/shadow box, no overflow, and no console warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-framing-disclosure/in-app-framing-disclosure-compact-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers the normal workspace framing disclosure tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal workspace tab-overflow tone

Normal workspace tab-overflow follow-up batch status:

- The normal workspace `More` tab overflow menu now keeps overflow functionality while rendering as a compact flat hairline panel instead of a bordered/shadowed popover.
- Hidden tab selection and close behavior remain unchanged.
- Reader-variant tab sizing and overflow-panel styling are explicitly preserved on the existing reader path.

Verification:

- Focused `ResearchTabBar` tests: `5 passed`, including default flat-panel coverage and reader-variant regression coverage.
- Targeted ESLint for `ResearchTabBar` and its test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `18 files / 148 tests passed`.
- `git diff --check`: pass for scoped files.
- Real in-app browser visual check on local data opened `#research/MSFT`, expanded `More`, and verified a compact 192px hairline panel with no full border/shadow box, hidden tab actions still visible, no overflow, and no console warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-tab-overflow/in-app-tab-overflow-flat-1440x900.png`.
- Code review subagent: initial findings on reader-variant width/test coverage; both fixed; follow-up PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers the normal workspace tab-overflow menu tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal analyst rail latest-exchange tone

Normal workspace analyst-rail follow-up batch status:

- The normal research analyst rail now renders the latest user/analyst exchange as compact rail conversation text instead of the old boxed `Latest Exchange` block with uppercase per-message labels.
- User and analyst message selection still comes from the existing `latestUserMessage`, `latestAnalystMessage`, and `summarizePanelMessage` paths; this batch changes presentation only.
- Document-reader presentation and document-context behavior were explicitly restored to the prior path after code review flagged an out-of-scope leak.

Verification:

- Focused `AgentPanel` + reader-track Phase 2 tests: `2 files / 41 tests passed`.
- Targeted ESLint for `AgentPanel` and its test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `18 files / 149 tests passed`.
- `git diff --check`: pass for scoped files.
- Real Chrome visual check on local authenticated data opened `#research/MSFT` and verified the right analyst rail renders the compact latest-exchange rail without the old boxed heading/uppercase `YOU` or `ANALYST` labels, no overflow, and no console warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-agent-rail/chrome-agent-rail-1440x900.png`.
- Code review subagent: initial finding on document-reader context leakage; fixed by restoring the document-context path; follow-up PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers the normal workspace analyst rail latest-exchange tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 active-thread related rail tone

Normal workspace active-thread rail follow-up batch status:

- Related thread cross-references now render inside the normal analyst rail body as a compact rail-message block instead of a separate uppercase `Related Threads` header section.
- Existing related-thread behavior is preserved: each related thread remains a flat hit target and still switches the active tab through the existing `setActiveTab` path.
- A screen-reader-only `Related Threads` label is retained for compatibility with existing accessibility/test expectations while the visible copy follows the preview-style conversational wording.
- Document-reader presentation remains on the existing reader path and was not changed.

Verification:

- Focused `AgentPanel` + reader-track Phase 2 tests: `2 files / 41 tests passed`.
- Targeted ESLint for `AgentPanel` and its test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `18 files / 149 tests passed`.
- `git diff --check`: pass for scoped files.
- Real Chrome visual check on local authenticated data opened the `Valuation Deep Dive` thread in `#research/MSFT` and verified the related-thread links render inside the analyst rail body with compact body text, flat arrow links, no visible uppercase header block, no overflow, and no console warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-related-threads-rail/chrome-related-threads-rail-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers the normal workspace active-thread related thread rail tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal analyst rail signal markers

Normal workspace analyst-rail signal-marker follow-up batch status:

- The normal analyst rail opening summary now uses preview-style signal markers instead of generic triangle bullets.
- Primary summary rows render with accent `⚑` markers; secondary rail context rows render with muted `○` markers, so both preview marker states are reachable.
- The underlying rail message selection and summary text still come from the existing `briefItems` and `analystContext` data paths; this is a presentation-only change.
- The current reader-track `documentContextFromReaderSelection` path is preserved and remains guarded by reader Phase 2 coverage; this batch did not add document-reader behavior.

Verification:

- Focused `AgentPanel` + reader-track Phase 2 tests: `2 files / 42 tests passed`.
- Targeted ESLint for `AgentPanel` and its test: pass.
- Non-reader research component pack excluding the reader-track Phase 2 file: `18 files / 149 tests passed`.
- `git diff --check`: pass for scoped files.
- Real Chrome visual check on local authenticated data opened the `Valuation Deep Dive` thread in `#research/MSFT` and verified accent `⚑` primary rows, muted `○` secondary rows, no old `▸` bullets in the opening summary, compact related-thread rail links, no overflow, and no console warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-rail-signal-markers/chrome-rail-signal-markers-secondary-final-1440x900.png`.
- Code review subagent: initial findings on unreachable secondary markers and reader-track scope interpretation; secondary markers fixed and reader-track state clarified; follow-up PASS.
- Visual review subagent: PASS on the final screenshot.

Open follow-ups:

- This batch only covers the normal workspace analyst rail signal-marker tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal analyst rail signal markers

Normal workspace analyst-rail follow-up batch status:

- The normal research analyst rail opening summary now uses preview-style signal markers instead of generic triangle bullets.
- Primary opening-summary rows render with accent flag markers.
- Secondary workspace context rows render inline below the primary rows with muted open-circle markers.
- Existing row content and rail behavior are preserved: analyst summaries still come from the current rail evidence messages, fallback guidance still appears when no analyst messages are available, and thread/link behavior remains unchanged.
- Document-reader presentation remains on the existing reader path and was not changed by this marker batch.

Verification:

- Focused `AgentPanel` tests: `1 file / 2 tests passed`.
- Non-reader research component pack excluding the reader-track Phase 2 file: `18 files / 149 tests passed`.
- Targeted ESLint for `AgentPanel` and its test: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke on `#research/MSFT` verified accent flags for primary rail rows, muted open circles for secondary context rows, no triangle marker in the opening summary, no overflow, and no browser warning/error logs. Final screenshot captured at `/tmp/research-surface-alignment-20260528-rail-signal-markers/chrome-rail-signal-markers-secondary-final-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Known unrelated verification limit:

- The reader-track Phase 2 suite currently has an out-of-scope filing-anchor context expectation mismatch. That remains under the document-reader/source HTML/corpus reader lane and was not changed for this normal rail-marker batch.

Open follow-ups:

- This batch only covers the normal workspace analyst rail marker presentation. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 focused-thread pin action tone

Focused-thread follow-up batch status:

- The focused thread `Pin Finding` action now uses the same flat action grammar as the aligned workspace controls: normal-case 12px label, normal tracking, muted text, transparent background, no border frame, no rounded button chrome, and a 28px hit target.
- The pin icon remains accent-colored because this action is specifically tied to finding capture rather than route/navigation.
- Existing behavior is preserved: opening the finding dialog, drafting the finding summary, and calling the existing `updateThread.mutateAsync` update path are unchanged.
- The pinned finding block remains a flat border band, not a raised card.

Verification:

- Focused `ThreadTab` + reader-track Phase 2 tests: `2 files / 44 tests passed`.
- Targeted ESLint for `ThreadTab` and its test: pass.
- Full research component pack: `20 files / 197 tests passed`.
- `git diff --check`: pass for scoped files.
- Live Chrome visual check on local authenticated data opened `#research/MSFT`, activated `Thread 1`, and verified the `Pin Finding` action renders with `text-transform: none`, normal letter spacing, 12px font, 400 weight, transparent background, zero border, 28px min-height, no fresh browser warning/error logs, and no layout overflow. Screenshot captured at `/tmp/research-surface-alignment-20260528-thread-pin-action/chrome-thread-pin-action-live-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers the focused-thread pin finding action tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 3 seeded-thread history loading

Thread-history follow-up batch status:

- Newly created research threads no longer write an empty `messagesByThread[thread.id]` entry immediately after creation.
- This preserves the store's unloaded state for newly opened threads, so `ThreadTab` can fetch server-created history for seeded threads instead of rendering a permanent empty workstream.
- The fix addresses the root cause of blank focused threads after `seed_message_ids` / `initial_message` creation paths: the client had been incorrectly marking the thread as loaded-empty before the message query could run.
- Existing behavior is preserved: the created thread summary is still upserted, the tab still opens, and the active tab still moves to the new thread.

Verification:

- Focused connector/thread tests: `2 files / 14 tests passed`.
- Targeted ESLint for `useResearchContent` and its test: pass.
- Non-reader connector/research pack: `19 files / 153 tests passed`.
- `git diff --check`: pass for scoped files.
- Live Chrome visual check on local authenticated data opened the existing server-seeded `Sector & Industry` thread in `#research/MSFT` and verified its seeded analyst message renders in the focused thread workstream instead of the blank loaded-empty state. Screenshot captured at `/tmp/research-surface-alignment-20260528-seeded-thread-history/chrome-seeded-thread-history-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Known unrelated verification limit:

- A broader all-research test run failed only in `SourceHtmlPane.test.tsx` (`reopens saved quote anchors by scrolling and marking the source HTML text`). That is in the active document-reader/source-HTML lane and was not touched for this connector/thread-history batch.

Open follow-ups:

- This batch only covers seeded thread history loading for focused thread workstreams. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 analyst rail flagged count source

Analyst rail aggregate-count follow-up batch status:

- The normal research analyst rail now reads `flaggedThreadCount` from the active `ResearchFile` instead of inferring flagged threads from `threadsById[*].finding_summary`.
- The root cause was twofold: pinned findings and backend flagged-thread aggregates are different contracts, and detail-page bootstrap was hydrating from the create-or-load file response before the backend aggregate counts were available.
- `bootstrapResearchWorkspace` now refreshes the canonical file detail record after thread listing and hydrates the store from that file detail payload, so `threadCount` and `flaggedThreadCount` come from the backend aggregate source.
- `useUpdateResearchThread` now starts a non-blocking canonical file-detail refresh after a successful thread finding update, invalidates file queries, and updates the active file when the refresh succeeds. A refresh failure no longer makes the already-saved thread update look failed to the user.
- Existing thread behavior is preserved: thread summaries still upsert through the existing store path, thread tabs still open normally, and seeded thread history loading remains unloaded until `ThreadTab` fetches it.

Verification:

- Focused connector/rail/list/compare tests: `4 files / 28 tests passed`.
- Targeted ESLint for `useResearchContent`, its test, `AgentPanel`, and its test: pass.
- Non-reader connector/research pack: `19 files / 155 tests passed`.
- `git diff --check`: pass for scoped files.
- Live Chrome smoke on local authenticated `#research/MSFT` verified bootstrap displays `7 active threads · 1 flagged` from backend aggregate data. Pinning a temporary finding on `Thread 1` updated the rail to `7 active threads · 2 flagged`; clearing that temporary finding restored `No pinned finding yet` and `7 active threads · 1 flagged`. No fresh browser warning/error logs. Final restored screenshot captured at `/tmp/research-surface-alignment-20260528-rail-flagged-count/chrome-pin-clear-flagged-count-final-restored-1440x900.png`.
- Initial code review subagent found a stale-count mutation path after pin/clear; the mutation-path canonical file refresh fixed it and added regression coverage. A follow-up review finding on refresh-failure isolation was also fixed; final code review PASS.
- Visual review subagent: PASS on the initial bootstrap screenshot, with a minor note that the tiny rail metadata can look visually tight.

Known unrelated verification limit:

- The document-reader/source-HTML lane remains intentionally out of scope for this batch. Existing reader/source pane work and the unrelated `active_anchor` dirty hunk in the connector file are not part of this flagged-count change.

Open follow-ups:

- This batch only covers normal workspace analyst rail aggregate-count sourcing and update propagation. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 3 explicit manual thread naming

Thread-naming follow-up batch status:

- The normal workspace tab-bar `+` no longer creates an immediate generic `Thread ${n}` workstream.
- The root cause was the manual tab-bar path generating a name locally and calling `createThread.mutateAsync` immediately, while seeded/document-driven thread flows already had explicit naming or context.
- Manual thread creation now opens a `Name Thread` dialog first. The input starts empty, `Create Thread` is disabled until a non-empty name exists, and cancel closes the dialog without creating a thread.
- Successful submission still uses the existing `createThread.mutateAsync` path with `{ research_file_id: file.id, name }`, preserving active-tab/store behavior owned by the connector mutation.
- Disabled dialog confirm actions now render as a muted neutral disabled surface so the unavailable action does not read as an active primary action.
- Seeded/document-driven thread creation paths remain untouched.

Verification:

- Focused research UI tests: `4 files / 34 tests passed`.
- Non-reader connector/research pack with constrained workers: `19 files / 156 tests passed`.
- Targeted ESLint for `ResearchWorkspace`, `ResearchWorkspacePhase3.test`, and `TextInputDialog`: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research/MSFT`: tab-bar `+` opened `Name Thread`, the field was empty, `Create Thread` was disabled, cancel closed without creating a new tab/thread, and there were no fresh browser warning/error logs. Final screenshot captured at `/tmp/research-surface-alignment-20260528-new-thread-naming/playwright-new-thread-name-dialog-disabled-polish-1440x900.png`.
- Code review subagent: PASS. Residual cancel/no-create coverage note was addressed with unit coverage after the review.
- Visual review subagent: initial finding that the disabled `Create Thread` looked too active; disabled confirm styling was fixed; follow-up PASS.

Known unrelated verification limit:

- A parallel broad Vitest run hit worker-queue/test timeouts under load; the same pack passed with `--maxWorkers=1 --minWorkers=1`, and the timed-out Phase 3 tests passed in focused reruns.

Open follow-ups:

- This batch only covers normal workspace manual thread naming from the tab bar. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal tab add affordance tone

Tab-bar follow-up batch status:

- The normal workspace tab-bar `+` add affordance now renders as a muted utility control instead of a primary accent action.
- The root cause was a shared `text-primary` class on the add button, which made thread creation compete with the active tab underline and other accent signals despite the preview treating `+` as quiet tab chrome.
- The reader variant keeps its existing `text-primary` styling so this normal-workspace polish does not alter the F156/reader path.
- Existing behavior is preserved: the button keeps `aria-label="New research thread"`, the same click handler, and disabled behavior.

Verification:

- Focused tab/workspace tests: `2 files / 29 tests passed`.
- Targeted ESLint for `ResearchTabBar` and its test: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research/MSFT`: tab add button class included `text-[hsl(var(--text-dim))]`, computed color was `rgb(138, 143, 153)`, and there were no fresh browser warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-tab-add-tone/playwright-tab-add-muted-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal workspace tab add affordance tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal tab overflow-count tone

Tab-bar follow-up batch status:

- The normal workspace `More N` hidden-tab count now renders as muted tab utility text instead of primary accent text.
- The root cause was the same tab-chrome tone issue as the add affordance: the overflow count used `text-primary`, making overflow mechanics compete with the active tab underline.
- The reader variant keeps its existing primary count styling so this normal-workspace polish does not alter the F156/reader path.
- Existing overflow behavior is preserved: the summary label, menu open state, hidden-tab selection, and close actions all remain on the same paths.

Verification:

- Focused tab/workspace tests: `2 files / 29 tests passed`.
- Targeted ESLint for `ResearchTabBar` and its test: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research/MSFT`: overflow count class included `text-[hsl(var(--text-dim))]`, computed color was `rgb(138, 143, 153)`, the overflow menu opened successfully, and there were no fresh browser warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-tab-overflow-count-tone/playwright-tab-overflow-count-muted-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Known unrelated local-data note:

- The live smoke surfaced a local `DELETE-TEST` thread in the MSFT overflow menu. That appears to be local research data cleanup, not a tab-bar code issue.

Open follow-ups:

- This batch only covers normal workspace tab overflow-count tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal framing summary tone

Header-framing follow-up batch status:

- The normal workspace framing summary (`Long · General · Unrated`) now renders as muted secondary metadata instead of primary accent text.
- The root cause was that the flattened `Framing` disclosure still used `text-primary` for the value summary, making secondary metadata compete with the stage label and active accent cues.
- The arrow remains primary accent as the action cue; the disclosure label, aria label, metadata controls, and update paths are unchanged.

Verification:

- Focused workspace/tab tests: `2 files / 29 tests passed`.
- Targeted ESLint for `ResearchWorkspace` and the Phase 3 test: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research/MSFT`: framing value class included `text-muted-foreground`, computed value color was `rgb(158, 162, 169)`, the arrow remained `rgb(200, 163, 78)`, and there were no fresh browser warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-framing-summary-tone/playwright-framing-summary-muted-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal workspace framing-summary tone. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 1 normal Explore composer framing

Explore-composer follow-up batch status:

- The normal Explore pane composer now reads as the primary active-artifact input, matching the preview language pattern: `Ask about {TICKER}, or type / for commands...`.
- The root cause was placeholder hierarchy drift: the main Explore input still said `Explore this company with the research analyst...`, which made the primary pane sound like a generic helper surface while the right rail also had an analyst input.
- `ResearchWorkspace` now passes the active file ticker into `ExploreTab`, and `ExploreTab` falls back to `this company` if no ticker is available.
- A subagent code review caught a reader-boundary regression from the earlier manual thread-naming batch: the shared tab bar meant document-reader `+` would also open the naming dialog. That was fixed by restoring an immediate reader-only `Thread N` creation path while keeping the naming dialog limited to the normal workspace.

Verification:

- Focused research UI tests: `2 files / 27 tests passed`.
- Targeted ESLint for `ExploreTab`, `ExploreTab.test`, `ResearchWorkspace`, and `ResearchWorkspacePhase3.test`: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research/MSFT`: the main composer placeholder rendered as `Ask about MSFT, or type / for commands...`, the rail composer remained `Ask the analyst...`, and there were no fresh browser warning/error logs after load. Screenshot captured at `/tmp/research-surface-alignment-20260528-explore-composer-placeholder-1440x900.png`.
- Code review subagent: initial P1 on reader `+` boundary fixed with regression coverage; follow-up PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal Explore composer hierarchy and the reader-boundary regression in the shared tab-bar handler. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 content behavior.

### 2026-05-28 Phase 1 normal rail context identity

Rail-context follow-up batch status:

- The normal workspace analyst rail context now uses the company identity when available, so the rail scopes itself as `Diligence · Microsoft Corporation` instead of `Diligence · MSFT`.
- The root cause was that `AgentPanel` reused `buildResearchDisplayTitle`, which is appropriate for list/file labels but intentionally returns ticker plus optional label and does not use `companyName`.
- The new rail-only context title uses `file.companyName || buildResearchDisplayTitle(file)`, preserving list semantics and preserving document/thread rail context branches.

Verification:

- Focused rail test: `1 file / 2 tests passed`.
- Targeted ESLint for `AgentPanel` and `AgentPanel.test`: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research/MSFT`: right rail rendered `Diligence · Microsoft Corporation`, the old `Diligence · MSFT` context was absent, and there were no fresh browser warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-rail-context-company-1440x900.png`.
- Code review subagent: PASS, including an additional `pnpm --dir frontend exec tsc -p packages/ui/tsconfig.json --noEmit --pretty false` check.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal workspace analyst rail identity text. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 content behavior.

### 2026-05-28 Phase 1 normal tab overflow casing

Tab-overflow follow-up batch status:

- The normal workspace overflow tab trigger now reads like ordinary tab chrome (`More N`) instead of an uppercase utility control (`MORE N`).
- The root cause was a shared overflow summary class that forced `uppercase`, `text-[10px]`, and `tracking-[0.08em]` across both normal workspace and reader variants.
- The normal/default variant now uses `h-9 text-[11px] tracking-[0.04em]` with no uppercase transform, matching the visible tab label grammar.
- The reader variant keeps its compact `h-7 text-[10px] uppercase tracking-[0.08em]` path unchanged.

Verification:

- Focused tab-bar test: `1 file / 5 tests passed`.
- Targeted ESLint for `ResearchTabBar` and `ResearchTabBar.test`: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research/MSFT`: normal overflow trigger computed `text-transform: none`, font size `11px`, class included `tracking-[0.04em]`, and there were no fresh browser warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-tab-overflow-casing-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal workspace tab overflow casing. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 content behavior.

### 2026-05-28 Phase 1 research list briefing action tone

List-briefing follow-up batch status:

- The top research-list briefing action now reads like the preview's quiet prose-adjacent link: `Start new research ->` in normal 12px text with an accent arrow.
- The root cause was that the briefing action reused the list toolbar command class, making it render as uppercase mono command text (`START NEW RESEARCH`) rather than part of the briefing block.
- A dedicated `listBriefingActionClass` now applies only to the top briefing `Start new research` action. Filter, compare, retry, new-file, and table row actions remain on the existing list command styling.

Verification:

- Focused list test: `1 file / 9 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research`: briefing action computed `text-transform: none`, font size `12px`, normal letter spacing, Instrument Sans font family, and there were no fresh browser warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-list-briefing-action-tone-1440x900.png`.
- Visual review subagent: PASS.
- Code review subagent: initial findings pointed at pre-existing dirty list-alignment hunks in the shared worktree; follow-up review of the isolated current hunk PASS.

Open follow-ups:

- This batch only covers the research-list briefing action tone. It does not alter list table structure, breakpoints, compare controls, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 content behavior.

### 2026-05-28 Phase 1 report version-history accessibility

Report-version follow-up batch status:

- Report/handoff version-history rows now have deliberate accessible names instead of relying on concatenated visible text such as `v7finalizedCreated...`.
- The new label includes the visible version token first (`v7`), then report version, status, created timestamp, finalized timestamp, and `current version` for the active row. This preserves label-in-name behavior for voice control users.
- Visible report UI, version selection behavior, and `aria-current` behavior are unchanged.

Verification:

- Focused report test: `1 file / 4 tests passed`.
- Targeted ESLint for `HandoffReviewView` and `HandoffReviewView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via Playwright/dev auth on `http://localhost:3000/#research/MSFT`: report version buttons exposed labels beginning with visible tokens (`v7`, `v6`, `v5`), active `v7` retained `aria-current="true"`, and there were no fresh browser warning/error logs. Screenshot captured at `/tmp/research-surface-alignment-20260528-report-version-labels-1440x900.png`.
- Visual review subagent: PASS.
- Code review subagent: initial findings included pre-existing dirty report visual-alignment hunks in the shared worktree and a valid label-in-name issue. The label-in-name issue was fixed; follow-up review of the isolated accessibility hunk PASS.

Open follow-ups:

- This batch only covers report version-history accessible names. It does not alter report visual structure, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 content behavior.

### 2026-05-28 Phase 1 review-fix batch: list briefing scope and rail tab identity

Review-fix batch status:

- The research-list briefing now stays scoped to the full file set while the visible table rows remain scoped to the active filters and sorting.
- Duplicate-ticker attention copy now uses deduped ticker grammar, so repeated flagged files for the same ticker render as `VALE has...` instead of `VALE have...`.
- Research-list row keys now use stable file ids rather than symbols, avoiding duplicate-key risk when multiple files share a ticker.
- Exploring stage badges now use the chart-blue stage tone from the preview while Diligence remains on the primary/gold tone.
- The analyst rail now uses tab-specific context and lead copy for locked/draft Diligence and frozen Report views, instead of carrying the generic stage rail language into those tabs.

Verification:

- Focused research UI tests: `2 files / 14 tests passed`.
- Targeted ESLint for `ResearchPresentation`, `ResearchListView`, `ResearchListView.test`, `AgentPanel`, and `AgentPanel.test`: pass.
- `git diff --check`: pass for scoped files.
- Live local smoke via in-app browser on `http://localhost:3000/#research` and `http://localhost:3000/#research/MSFT`: Exploring badges computed chart-blue tone, Diligence-filtered list kept the full-file top briefing while rows filtered correctly, locked Diligence rail rendered locked-context copy, Report rail rendered report-context copy, and there were no fresh browser warning/error logs. Screenshots captured at `/tmp/research-surface-alignment-20260528-stage-badge-tone/in-app-exploring-badge-blue-1440x900.png`, `/tmp/research-surface-alignment-20260528-review-fixes/in-app-list-filter-briefing-diligence-1440x900.png`, `/tmp/research-surface-alignment-20260528-review-fixes/in-app-diligence-rail-context-1440x900.png`, and `/tmp/research-surface-alignment-20260528-review-fixes/in-app-report-rail-context-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal research-list briefing scope, stage badge tone, and analyst rail identity for Diligence/Report tabs. It does not alter document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 content behavior.

### 2026-05-28 Phase 5 report secondary action tone

Report-action follow-up batch status:

- Report secondary actions now use the same flat action-link grammar as the rest of the aligned research surface: 12px normal-case sans text, normal tracking, muted label, accent-only arrow, transparent background, no border frame, and a 28px hit target.
- Covered actions: `New Version`, `Build Model`, `Export JSON`, `Download Model`, `Retry Build`, and `Retry Annotations`.
- Build/export/download/retry behavior, disabled states, persisted model-ref visibility, and handoff version selection behavior are unchanged.

Verification:

- Focused report action tests: `2 files / 10 tests passed`.
- Targeted ESLint for `BuildModelButton`, `BuildModelButton.test`, `HandoffReviewView`, and `HandoffReviewView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research/MSFT`: report actions computed `text-transform: none`, `font-size: 12px`, normal letter spacing, transparent background, zero border, 28px min-height, no horizontal overflow, and no fresh browser warning/error logs.
- Playwright visual captures saved at `/tmp/research-surface-alignment-20260528-report-action-tone/playwright-report-actions-normal-1440x900.png` and `/tmp/research-surface-alignment-20260528-report-action-tone/playwright-report-downstream-actions-normal-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers report secondary action tone. It does not alter report typed-output renderer semantics, F122 Workbench/artifact implementation, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 2 compare action tone

Compare-action follow-up batch status:

- Compare-route actions now use the same flat action-link grammar as the aligned research surface: 12px normal-case sans text, normal tracking, muted label, accent-only directional mark, transparent background, no border frame, and a 28px hit target.
- Covered actions: `Back to files`, `Open MSFT`, and `Open AAPL` / `Open {file title}`.
- The existing compare behavior is unchanged: back navigation and opening either compared file still call the same callbacks.

Verification:

- Focused compare test: `1 file / 4 tests passed`.
- Targeted ESLint for `ResearchCompareView` and `ResearchCompareView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research/compare/88,87`: compare actions computed `text-transform: none`, `font-size: 12px`, normal letter spacing, transparent background, zero border, 28px min-height, primary-colored back arrow / open arrows, no horizontal overflow, and no fresh browser warning/error logs.
- Playwright visual capture saved at `/tmp/research-surface-alignment-20260528-compare-action-tone/playwright-compare-actions-arrow-normal-1440x900.png`.
- Code review subagent: initial P2 on missing compare back arrow fixed; follow-up PASS.
- Visual review subagent: PASS, including follow-up after the back-arrow fix.

Open follow-ups:

- This batch only covers compare-route action tone. It does not alter compare data loading, report rendering semantics, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 2 list primary action tone

List-action follow-up batch status:

- Research-list primary actions now consistently use the flat action-link grammar: 12px normal-case sans text, normal weight, normal tracking, muted label, accent-only arrow, transparent background, no border frame, and a 28px hit target.
- Covered actions: `Start new research`, `New File`, `Retry`, `Open comparison`, and desktop/mobile row `Open`.
- Idle `New File` and `Retry` no longer show leading utility icons; their spinner icons remain only while pending/retrying.
- Secondary utility compare controls (`Compare`, `Selected`, `Clear`) remain visually secondary and unchanged in behavior.

Verification:

- Focused list test: `1 file / 10 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research`: primary list actions computed `font-weight: 400`, `font-size: 12px`, `text-transform: none`, normal letter spacing, sans font family, transparent background, zero border, 28px min-height, primary-colored action arrows, no idle leading icons, no horizontal overflow, and no fresh browser warning/error logs.
- In-app browser screenshot saved at `/tmp/research-surface-alignment-20260528-list-row-actions-final-1440x900.png`.
- Code review subagent: initial P3 findings on inherited `font-medium` and idle leading icons fixed; follow-up PASS.
- Visual review subagent: PASS, including follow-up after the font/icon fix.

Open follow-ups:

- This batch only covers research-list primary action tone. It does not alter filtering/sorting behavior, compare selection behavior, research-file persistence, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 3 inline feed action weight

Feed-action follow-up batch status:

- Inline feed actions now explicitly override the shared button base so `Start thread: ...` and `Open in tab: ...` render as normal-weight, normal-case flat action links.
- The action label stays muted on hover; the arrow remains the accent-only visual cue.
- Existing behavior is unchanged: branch/start-thread callbacks and open-in-reader handlers continue to use the same paths.

Verification:

- Focused feed action/citation test: `1 file / 4 tests passed`.
- Targeted ESLint for `ConversationFeed` and `ConversationFeed.citations.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research/MSFT`: `Start thread: Sector & Industry ->` computed `font-weight: 400`, `font-size: 12px`, `text-transform: none`, normal letter spacing, sans font family, muted label color, transparent background, zero border, 28px min-height, no horizontal overflow, and no fresh browser warning/error logs.
- In-app browser screenshot saved at `/tmp/research-surface-alignment-20260528-feed-action-weight/in-app-feed-actions-normal-weight-1440x900.png`.
- Code review subagent: initial P3 findings on hover label color and missing explicit `normal-case` fixed; follow-up PASS.
- Visual review subagent: PASS, including follow-up after the class-level fixes.

Open follow-ups:

- This batch only covers inline feed action typography and hover tone. It does not alter document opening, thread creation logic, `DocumentTab`, `SourceHtmlPane`, source HTML reader behavior, or reader/F156 behavior.

### 2026-05-28 Phase 3 workspace exit-ramp tone

Workspace exit-ramp follow-up batch status:

- Normal non-document research workspace footer exit ramps now explicitly render with the preview-aligned flat text-link grammar: 12px sans text, normal weight, normal letter spacing, muted label, accent-only arrow, transparent background, no border frame, and a 28px hit target.
- The root cause was the normal workspace `ExitRamps` call overriding the shared design primitive down to `min-h-6` without explicitly resetting inherited compact tracking. The shared primitive and document-reader branch remain unchanged.
- Covered actions: `Size a position`, `Stress test`, `Compare to holdings`, and `Generate trades` / `Open trading desk`.

Verification:

- Focused workspace integration test: `1 file / 26 tests passed`.
- Targeted ESLint for `ResearchWorkspace` and `ResearchWorkspacePhase3.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research/MSFT`: footer actions computed `font-weight: 400`, `font-size: 12px`, `text-transform: none`, normal letter spacing, sans font family, transparent background, zero border, 28px min-height, no horizontal overflow, and no fresh browser warning/error logs.
- Playwright visual capture saved at `/tmp/research-surface-alignment-20260528-workspace-exit-ramp-tone/playwright-workspace-exit-ramps-normal-loaded-1440x900.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal workspace footer exit-ramp tone. It does not alter document-reader exit ramps, document opening, `DocumentTab`, `SourceHtmlPane`, source HTML reader behavior, or reader/F156 behavior.

### 2026-05-28 Phase 3 diligence action tone

Diligence-action follow-up batch status:

- Normal Diligence actions now use the same flat action-link grammar as the aligned research surface: 12px sans text, normal weight, normal case, normal letter spacing, transparent background, no border frame, and a 28px hit target.
- The root cause was the shared `diligenceStyles` action class forcing 10px uppercase mono controls with wide tracking across Diligence commands.
- Covered actions include `Create New Version`, `Refresh Draft`, `Finalize Report`, `Generate Take` / `Refresh Take`, `Save Draft`, `Confirm`, `Add Factor`, `Save`, and `Remove`.
- The new shared `diligenceStyles.ts` file is staged so imports from the Diligence components are not left dependent on an untracked local file.

Verification:

- Focused Diligence component test: `1 file / 10 tests passed`.
- Focused regression pack with report/workspace action tests: `4 files / 46 tests passed`.
- Targeted ESLint for `diligenceStyles` and `DiligenceTab.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research/MSFT`: `Create New Version ->` computed `font-weight: 400`, `font-size: 12px`, `text-transform: none`, normal letter spacing, sans font family, transparent background, zero border, 28px min-height, no horizontal overflow, and no fresh browser warning/error logs.
- In-app browser screenshot saved at `/tmp/research-surface-alignment-20260528-diligence-action-tone/in-app-diligence-action-normal-loaded-1440x900.png`.
- Code review subagent: initial P1 on untracked `diligenceStyles.ts` fixed by staging the new file; follow-up PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers Diligence action typography/tone. It does not alter Diligence data mutation behavior, document-reader exit ramps, document opening, `DocumentTab`, `SourceHtmlPane`, source HTML reader behavior, or reader/F156 behavior.

### 2026-05-28 Phase 3 container state-action tone

Container state-action follow-up batch status:

- Research container state-band actions now use the same flat action-link grammar as the aligned research surface: 12px sans text, normal weight, normal case, normal letter spacing, primary text, transparent background, no border frame, and a 28px hit target.
- The root cause was `ResearchWorkspaceContainer`'s shared `stateActionClass` forcing 10px uppercase mono controls with wide tracking across gateway, compare, and bootstrap error actions.
- Covered actions: `Retry gateway check` and `Back to research files` across gateway failure, compare-file resolution failure, and bootstrap failure states.
- State-band actions now include the same accent arrow treatment as the rest of the normalized action links.

Verification:

- Focused container test: `1 file / 14 tests passed`.
- Targeted ESLint for `ResearchWorkspaceContainer` and its test: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research/compare/99999991,99999992`: `Back to research files ->` computed `font-weight: 400`, `font-size: 12px`, `text-transform: none`, normal letter spacing, sans font family, transparent background, zero border, 28px min-height, no horizontal overflow, and no fresh browser warning/error logs.
- In-app browser screenshot saved at `/tmp/research-surface-alignment-20260528-container-state-action-tone/in-app-container-state-action-normal-1440x900.png`.
- Code review subagent: initial P3 on missing bootstrap-failure assertion fixed with shared `expectFlatStateAction`; follow-up PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers research container loading/error state action typography/tone. It does not alter gateway checks, compare resolution, bootstrap behavior, document-reader exit ramps, document opening, `DocumentTab`, `SourceHtmlPane`, source HTML reader behavior, or reader/F156 behavior.

### 2026-05-28 Phase 3 list compare action tone

Research-list compare action follow-up batch status:

- Research-list comparison controls now use the same flat action grammar as the aligned list/workspace actions: 12px sans text, normal weight, normal case, normal letter spacing, muted text, transparent background, no border frame, and a 28px hit target.
- The root cause was that row-level `Compare` / `Selected` controls and the comparison-toolbar `Clear` action kept hardcoded mono uppercase utility classes after the surrounding list actions had been normalized.
- Covered actions: desktop and mobile row `Compare` / `Selected`, plus comparison-toolbar `Clear`.
- Compare selection behavior, compare-route opening, mobile/desktop row visibility, and table row navigation behavior are unchanged.

Verification:

- Focused research list test: `1 file / 10 tests passed`.
- Focused list/compare regression pack: `2 files / 14 tests passed`.
- Targeted ESLint for `ResearchListView` and its test: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research`: visible `Compare`, `Selected`, and `Clear` actions computed `font-weight: 400`, `font-size: 12px`, `text-transform: none`, normal letter spacing, sans font family, transparent background, zero border, 28px min-height, no horizontal overflow.

Open follow-ups:

- This batch only covers list compare action typography/tone. It does not alter filtering/sorting behavior, compare selection behavior, compare route resolution, research-file persistence, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 3 normal tab overflow item tracking

Normal tab-overflow follow-up batch status:

- Normal workspace overflow menu tab items now explicitly use the same `tracking-[0.04em]` tab-label grammar as visible tabs and the `More N` overflow trigger.
- The root cause was that hidden-tab menu buttons had no explicit tracking class, allowing global/browser computed tracking to diverge from visible tab chrome and produce negative letter spacing in the live menu item.
- The reader variant is left on its prior class path, preserving the reader-owned compact path and avoiding a normal-workspace style leak.
- Covered controls: hidden normal-workspace overflow tab items such as `Report v7`; the `More N` trigger remains unchanged because it already matched the preview tab chrome.

Verification:

- Focused tab-bar test: `1 file / 5 tests passed`.
- Targeted ESLint for `ResearchTabBar` and its test: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser DOM/computed-style smoke on `http://localhost:3000/#research/MSFT`: `Report v7` overflow menu item computed `font-size: 11px`, `font-weight: 400`, `text-transform: none`, `letter-spacing: 0.44px`, transparent background, zero border, no horizontal overflow.
- Visual review subagent: initial P2 on reader-variant style leakage fixed by limiting the explicit tracking class to the normal/default workspace variant; follow-up PASS for the scoped batch. A pre-existing reader-visible-tab tracking concern remains classified as F156/reader-owned and was not changed here.

Open follow-ups:

- This batch only covers normal workspace tab-overflow menu item tracking. It does not alter tab routing, thread creation, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 3 Explore quick-fact metric strips

Explore-message data presentation follow-up batch status:

- Research agent quick-fact lines now promote into the existing inline `MetricStrip` when a contiguous run uses compact finance metric labels such as `P/E (TTM)`, `Price`, and `Mkt cap`.
- The root cause was that `ResearchMessageContent` only recognized one pipe-delimited `Label: Value | ...` line, while live research answers commonly emit compact line-based facts and bullet-separated market data. That left preview-style inline data as plain prose.
- The parser uses the same compact-metric allowlist for quick-fact and legacy pipe-delimited promotion, requires at least two recognized metrics in a contiguous run, and only removes a line when every segment on that line is a recognized metric. Ordinary narrative colon text and mixed prose/citation segments stay in markdown.
- Categorical metadata such as `Sector` stays in prose so the strip remains compact like the preview KPI treatment.
- Existing markdown table rendering and citation paths remain unchanged, including citations that appear inside promoted metric values.

Verification:

- Focused message-content test: `1 file / 6 tests passed`.
- Focused message-content/conversation regression pack: `2 files / 10 tests passed`.
- Broad research component suite: `21 files / 220 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Targeted ESLint for `ResearchMessageContent`, `ResearchMessageContent.test`, and `MetricStrip`: pass.
- Live in-app browser smoke on `http://localhost:3000/#research/MSFT`: Sector remained prose/list text, P/E/Price/Mkt cap rendered in the metric strip, and console error count was `0`.
- Code review subagent: PASS after tightening quick-fact and legacy pipe parsing to all-or-nothing compact metric allowlists with citation preservation.
- Visual review subagent: PASS after source-order rendering and categorical metadata handling were corrected.
- `git diff --check`: pass for scoped files.

Open follow-ups:

- This batch only covers Explore/conversation quick-fact presentation. It does not alter report typed-output rendering, `HandoffSectionRenderer`, F122 Workbench/artifact behavior, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 3 analyst rail table-summary cleanup

Analyst-rail summary follow-up batch status:

- Normal analyst rail compact summaries no longer expose raw markdown table rows from underlying research messages.
- The root cause was that `summarizePanelMessage` flattened markdown before removing table blocks, so rows like `| Section | Words | Tables |` could leak into the contextual rail even though the main thread remained the right place for the table.
- Rail summaries now replace a detected markdown table block with one in-place note: `Table details remain in the thread.`
- Table detection is block-based and requires a markdown separator row, so edge-pipe and no-edge tables are removed while non-table pipe metric lines remain intact.

Verification:

- Focused `AgentPanel` test: `1 file / 6 tests passed`.
- Focused rail/reader-boundary regression pack: `2 files / 50 tests passed`.
- Broad research component suite: `21 files / 222 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Targeted ESLint for `AgentPanel` and `AgentPanel.test`: pass.
- Live in-app browser smoke on `http://localhost:3000/#research/MSFT`: no raw markdown table pipe rows were visible in the rail and console error count was `0`.
- Code review subagent: PASS after block-level table detection was tightened for no-edge two-column tables and duplicate-note occurrence coverage.
- Visual review subagent: PASS after confirming the rail-summary scope and table note behavior.
- `git diff --check`: pass for scoped files.

Open follow-ups:

- This batch only covers normal analyst rail compact summary presentation. It does not alter the main conversation feed, report typed-output rendering, `HandoffSectionRenderer`, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 3 research-list briefing ticker cap

Research-list briefing follow-up batch status:

- Research-list top briefings now cap long ticker runs at five visible tickers with a `plus N more` suffix, while preserving the full file table and all compare/filter/sort behavior.
- The root cause was that `buildResearchListLead` and the attention-summary branches rendered every unique ticker inline for active stages, flagged threads, diligence files, and unrated files. Busy local workspaces made the preview-style briefing read like an inventory dump before the user reached the table.
- The cap is shared by stage and attention summaries and keeps grammar based on the full unique ticker count.
- Dedupe order, table rows, compare selection, compare-route opening, filters, sorting, and research persistence are unchanged.

Verification:

- Focused research-list test: `1 file / 12 tests passed`.
- Focused list/container/compare regression pack: `3 files / 30 tests passed`.
- Broad research component suite: `21 files / 224 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/#research`: briefing showed `PCTY, GE, AAPL, MSFT, and VALE, plus 2 more are in exploration`, the full table and controls remained present, and console error count was `0`.
- Code review subagent: initial finding that attention summaries still dumped long ticker lists was fixed; follow-up PASS.
- Visual review subagent: PASS after confirming the capped briefing, retained table/detail surface, and no reader-surface changes.

Open follow-ups:

- This batch only covers normal research-list briefing copy length. It does not alter table rows, filtering/sorting behavior, compare selection behavior, compare route resolution, research-file persistence, document-reader route handling, filing/source HTML rendering, document tabs, report typed-output rendering, `HandoffSectionRenderer`, or reader/F156 behavior.

### 2026-05-28 Phase 3 research-list selector chrome

Research-list control-chrome follow-up batch status:

- Research-list Stage and Sort select triggers now use the same flat secondary-control grammar as the briefing/list actions: transparent background, no border frame, sans 12px text, normal weight, normal case, and normal letter spacing.
- The root cause was that the stage/sort controls retained the older bordered uppercase mono trigger treatment after the surrounding research-list actions had been aligned to the preview-style flat action language.
- The controls remain Radix select triggers, keep fixed widths for stable layout, preserve the dropdown arrow, and retain an explicit visible focus ring for keyboard users.
- Filtering, sorting, table rows, compare selection, and compare-route behavior are unchanged.

Verification:

- Focused research-list test: `1 file / 12 tests passed`.
- Focused list/container/compare regression pack: `3 files / 30 tests passed`.
- Broad research component suite: `21 files / 224 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/#research`: Stage and Sort triggers computed transparent background, `0px` border, sans 12px, `font-weight: 400`, `text-transform: none`, normal letter spacing, the briefing/table remained present, and console error count was `0`.
- Code review subagent: initial P1 on removed keyboard focus indicator was fixed with `focus:ring-1 focus:ring-primary/50 focus:ring-offset-0`; follow-up PASS.
- Visual review subagent: PASS after confirming the controls read as flat secondary controls without dominating the briefing/table viewport.

Open follow-ups:

- This batch only covers normal research-list select-trigger visual chrome. It does not alter filtering/sorting semantics, table rows, compare selection behavior, compare route resolution, research-file persistence, document-reader route handling, filing/source HTML rendering, document tabs, report typed-output rendering, `HandoffSectionRenderer`, or reader/F156 behavior.

### 2026-05-28 Phase 3 compare subtitle fallback

Research-compare summary follow-up batch status:

- Compare overview cards now render a quiet `Research file` subtitle when a compared file has no usable `companyName`, while preserving real company-name subtitles and still avoiding duplicated ticker/title subtitles.
- The root cause was that `ComparisonColumn` suppressed the subtitle whenever `companyName` was missing or title-equivalent, leaving an empty metadata slot in compare cards. The research list already used `Research file` as the explicit fallback, so compare diverged from the list surface.
- Compare routing, report snapshot loading, history loading, title rendering, and open/back actions are unchanged.

Verification:

- Focused compare/list/container regression pack: `3 files / 30 tests passed`.
- Broad research component suite: `21 files / 224 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Targeted ESLint for `ResearchCompareView` and `ResearchCompareView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/#research/compare/88,87`: MSFT still showed `Microsoft Corporation`, AAPL showed `Research file`, comparison content remained present, and console error count was `0`.
- Code review subagent: PASS.
- Visual review subagent: PASS after confirming the fallback is secondary subtitle text and does not compete with title/action/status metrics.

Open follow-ups:

- This batch only covers normal research-compare subtitle fallback text. It does not alter compare routing, report artifact rendering, `HandoffSectionRenderer`, document-reader route handling, filing/source HTML rendering, document tabs, or reader/F156 behavior.

### 2026-05-28 Phase 3 direct thread route activation

Research workspace route lifecycle follow-up batch status:

- Direct normal workspace thread routes now parse, build, hydrate, and activate matching thread tabs with `#research/TICKER/thread/ID`.
- The root cause was that the hash parser and UI-store initial hash hydration ignored the `thread/ID` suffix, so direct thread URLs collapsed to ticker-level Research and the workspace defaulted back to Explore.
- Selecting an existing thread tab now writes a shareable thread URL; creating a thread from the tab bar or a document selection writes the newly created thread id into navigation context.
- Routed thread activation is consumed once per file/thread route key so later tab lifecycle events, such as creating another thread, are not forced back to the original routed tab.
- Closing an active routed thread clears back to the base file route, and stale thread ids canonicalize to the base file route with Explore active.
- Reader-owned routing remains out of scope: this batch did not add reader initial-hydration parsing, change SourceHtmlPane behavior, alter filing/source HTML rendering, or touch F122/F156/report-artifact architecture.

Verification:

- Focused routing/workspace tests: `3 files / 70 tests passed`.
- Broad research component suite: `21 files / 231 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Targeted ESLint for hash sync, UI store, ResearchWorkspace, ResearchWorkspaceContainer, and touched tests: pass.
- Live in-app browser smoke on `http://localhost:3000/#research/MSFT/thread/12`: valid thread deep link activated Thread 1, closing Thread 1 rewrote to `#research/MSFT` with Explore active, stale `#research/MSFT/thread/999999` canonicalized to `#research/MSFT` with Explore active, and console warning/error count was `0`.
- Local research gateway note: live smoke required starting the configured risk-module research gateway on `https://localhost:8010`, matching `.env` `RESEARCH_GATEWAY_URL`.
- Code review subagent: initial lifecycle findings for route reassertion, active-thread close cleanup, and out-of-scope reader hydration were fixed; follow-up found the create-from-selection path and it was fixed; final PASS.
- Visual review subagent: PASS after confirming valid direct thread routes, shareable URL writing, invalid-route canonicalization, and no reader/report surface changes.

Open follow-ups:

- This batch only covers normal research workspace thread routes and route/tab lifecycle consistency. It does not alter reader route architecture, SourceHtmlPane, filing/source HTML rendering, document-reader ownership, report typed-output rendering, `HandoffSectionRenderer`, F122, or F156 behavior.

### 2026-05-28 Phase 3 local/dev research data hygiene

Local visual-QA cleanup batch status:

- Added `scripts/cleanup_research_dev_artifacts.py`, a dry-run-first local/dev helper for cleaning empty placeholder research threads and empty debug research files from AI-excel-addin SQLite research stores.
- The root cause was persisted local research data from earlier test runs, not tab-bar/list rendering: the workspace was correctly showing empty non-system threads named `DELETE-TEST`, generic `Thread N`, and later a persisted empty `TEST` research file.
- The thread cleanup guard is intentionally narrow: it only matches non-explore, non-panel threads with zero messages, no pinned `finding_summary`, and placeholder names (`DELETE-TEST` or `Thread N`), supports ticker/label scoping, and rechecks the name plus empty finding state at delete time before removing a row.
- The file cleanup guard is similarly narrow: it only matches exact debug tickers (`TEST` by default), respects ticker/label scoping, requires zero related rows across research threads, history, annotations, handoffs, theses, model build context, model insights, and price targets, and rechecks those guards at delete time.
- `--apply` requires `--ticker` or explicit `--all-files`, and uses SQLite's backup API before deletion unless `--no-backup` is explicitly passed.
- Applied the helper to local user `1` / unlabeled MSFT after dry-run review, deleting empty thread ids `12`, `16`, `19`, `22`, and `45`; backup written to `/Users/henrychien/Documents/Jupyter/AI-excel-addin/data/users/1/research.db.backup-20260528-141839`.
- Applied the helper to local user `1` / unlabeled `TEST` after dry-run review, deleting empty research file id `30`; backup written to `/Users/henrychien/Documents/Jupyter/AI-excel-addin/data/users/1/research.db.backup-20260528-165024`.
- This is not a UI fallback or hidden filter: real seeded/message-bearing threads remain visible, and the tool is explicit local/dev cleanup.

Verification:

- Focused cleanup tests: `1 file / 13 tests passed`.
- Targeted Ruff for the cleanup script and tests: pass.
- Dry run against local MSFT showed only empty placeholder rows.
- Post-apply SQLite query showed only `Explore`, `Panel`, `Valuation Deep Dive`, pair-review system threads, and seeded `Sector & Industry` remain for MSFT.
- Live in-app browser reload on `http://localhost:3000/#research/MSFT`: `DELETE-TEST` and generic `Thread 1/3/5/6` were gone; `Valuation Deep Dive` and `Sector & Industry` remained; no `More` overflow was needed for those deleted placeholders.
- Live in-app browser reload on `http://localhost:3000/?testCleanup=1779999024#research`: the research list loaded with no `TEST`, no `Compare TEST`, no `Open TEST`, no `DELETE-TEST`, no generic `Thread N`, no console warnings/errors, and no horizontal overflow. Screenshot captured at `/tmp/research-list-test-cleanup-20260528-after-wait.png`.

Open follow-ups:

- This batch only covers local/dev data hygiene for visual QA. It does not alter research persistence contracts, frontend tab filtering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 1 normal workspace tab visibility

Tab-bar follow-up batch status:

- The normal research workspace tab bar now keeps up to five compact tabs visible on desktop before using the overflow menu.
- The root cause was a shared hard cap of three visible tabs for both normal workspace and reader variants. After local data cleanup, the normal desktop MSFT workspace still pushed real Diligence/Report tabs into `More 2` despite having enough horizontal room.
- Compact normal workspace widths keep the three-tab overflow limit so mobile does not bury tabs off-screen in the horizontal scroller.
- The reader variant keeps the three-tab cap so the F156/document-reader constrained layout is unchanged.
- Existing tab selection, close actions, overflow menu behavior, and new-thread affordance are unchanged.

Verification:

- Focused tab/workspace tests: `2 files / 41 tests passed`.
- Broad research component suite: `21 files / 235 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Targeted ESLint for `ResearchTabBar`, `ResearchWorkspace`, and their focused tests: pass.
- Live Playwright smoke on `http://localhost:3000/#research/MSFT`: `Explore`, `Diligence locked`, `Report v7`, `Valuation Deep Dive`, and `Sector & Industry` all rendered as visible tabs; no `More` trigger rendered; no horizontal overflow. Screenshot captured at `/tmp/research-msft-five-tabs-visible-playwright-1440x900.png`.
- Mobile-width smoke at 390px verified the compact limit keeps a `More 2` trigger visible instead of pushing all five tabs off-screen. Screenshot captured at `/tmp/research-msft-tabs-responsive-mobile-390x844.png`.

Open follow-ups:

- This batch only covers normal workspace tab visibility. It does not alter reader tab limits, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 1 research gateway preflight deduplication

Research loading-friction follow-up batch status:

- The research container remains the single owner of the web-channel gateway preflight before list, compare, or workspace data loads.
- Removed duplicate `/api/research/content/preflight` calls from `useResearchFiles` and `bootstrapResearchWorkspace`; those hooks are only invoked by `ResearchWorkspaceContainer` after `useResearchGatewayStatus` succeeds.
- The root cause was duplicated frontend orchestration: after the container's preflight gate succeeded, list and ticker bootstrap paths immediately made a second preflight request, which forces another gateway session refresh instead of moving directly to the data request.
- Upstream research content requests still obtain and refresh gateway session tokens through the backend proxy, including 401 retry handling; this batch only removes the redundant frontend preflight calls.

Verification:

- Focused connector/container tests: `2 files / 28 tests passed`.
- Targeted ESLint for `useResearchFiles`, `useResearchContent`, the connector hook test, and `ResearchWorkspaceContainer.test`: pass.
- Broad research component suite plus connector hook test: `22 files / 248 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Live in-app browser reload on `http://localhost:3000/#research/MSFT`: warm route reached the MSFT workspace in `830ms`, with no gateway/bootstrap state left on screen and no browser warning/error logs.

Open follow-ups:

- This batch only covers duplicate normal research preflight calls. It does not change backend gateway token/session handling, chat gateway transport, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 1 existing-thread feed actions

Explore feed follow-up batch status:

- Explore feed branch actions now resolve the suggested thread name against already-open normal thread tabs.
- If a matching thread exists, the inline action reads `Open thread: <name>` and routes to the existing thread tab instead of opening the create-thread dialog.
- If no matching thread exists, the action still reads `Start thread: <name>` and preserves the seeded thread creation flow with `seed_message_ids`.
- The root cause was that `ExploreTab` treated every agent answer as a new seeded workstream. The message-level thread-name suggestion was already deterministic, but the component never checked whether that workstream was already present in the workspace.

Verification:

- Focused research tests: `3 files / 51 tests passed`.
- Targeted ESLint for `ConversationFeed`, `ExploreTab`, `ResearchWorkspace`, and touched tests: pass.
- Broad research component suite: `21 files / 236 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Live in-app browser smoke on `http://localhost:3000/#research/MSFT`: the existing `Sector & Industry` branch rendered as `Open thread: Sector & Industry`; `Start thread: Sector & Industry` was absent; clicking routed to `#research/MSFT/thread/48`; no `Name Thread` dialog opened; no browser warning/error logs or horizontal overflow.

Open follow-ups:

- This batch only covers normal Explore feed actions for existing thread tabs. It does not change document-selection thread creation, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 1 compare route back-state cleanup

Compare route lifecycle follow-up batch status:

- The research list now clears local compare selection state when the user leaves a direct comparison route through `Back to files`.
- The root cause was route-seeded local state: `#research/compare/<left>,<right>` correctly seeded `compareSelectionIds`, but the shared back-to-list handler only reset the research workspace store and navigation context. Returning to `#research` therefore left the previous pair selected, kept `Open comparison` enabled, and disabled every other row-level `Compare` action.
- The fix keeps the compare-route transition atomic by clearing `compareSelectionIds` in `handleBackToList` only when the current route is an active compare route.
- Ordinary workspace exits preserve manually selected comparison candidates, so a user can select files on the list, inspect one file, and return without losing the pending comparison setup.
- Added a container test that preserves component state across a compare-route render, clicks `Back to files`, rerenders the list route, and verifies the list receives an empty compare selection.
- Added a second container regression test for the non-compare path to verify manually selected comparison candidates survive a list -> workspace -> list round trip.

Verification:

- Focused container test: `1 file / 17 tests passed`.
- Targeted ESLint for `ResearchWorkspaceContainer` and its test: pass.
- Live in-app browser smoke on `http://localhost:3000/#research/compare/88,87`: after `Back to files`, the list returned to `#research` with no selected comparison rows, `Open comparison` disabled, row-level `Compare` actions enabled, no browser warning/error logs, and no horizontal overflow. Screenshot captured at `/tmp/research-compare-back-clean-20260528.png`.

Open follow-ups:

- This batch only covers normal research compare/list state cleanup. It does not change compare content rendering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 1 normal artifact route lifecycle

Normal workspace route follow-up batch status:

- Diligence and finalized Report tabs now have explicit normal-workspace hash routes: `#research/<ticker>/diligence` and `#research/<ticker>/report`.
- The root cause was that `ResearchWorkspace` selected the Diligence/Report tabs in local research-store state but routed them through the base file context. The hash builder only had addressable branches for compare, thread, and reader tabs, so clicking Diligence or Report left the URL at `#research/MSFT` even though the visible artifact changed.
- The fix adds a narrow `workspaceTab` navigation context for normal workspace artifacts only. Thread and reader routes keep precedence, compare routing is unchanged, and the F156/source-HTML reader path is untouched.
- `ResearchWorkspaceContainer` now preserves and passes the requested normal artifact tab through bootstrap so direct report/diligence hashes can activate the matching tab after the file hydrates.
- Secondary `Open report` now writes the report artifact route when it switches to the handoff tab.
- Browser Back from a normal artifact route to the base workspace route now reselects Explore instead of leaving a Diligence/Report artifact under the base `#research/<ticker>` URL.
- Mutation-driven artifact activation now writes the same route context as tab clicks: `Form thesis` writes the Diligence route, and `Generate report` writes the Report route without relying on a stale tab list immediately after mutation.

Verification:

- Focused hash/container/workspace route tests: `3 files / 78 tests passed`.
- Reader-adjacent Phase2 regression file: `1 file / 45 tests passed`.
- Targeted ESLint for touched hash sync, UI store, workspace, container, and tests: pass.

Open follow-ups:

- The already-open dev browser tab kept the pre-edit hash-sync subscription during HMR, so live-click verification needs a full page refresh or dev-server restart before this route-specific browser check is meaningful.
- This batch only covers normal Diligence/Report workspace artifact routing. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 1 Explore rail active-artifact identity

Normal workspace rail-context follow-up batch status:

- The analyst rail now labels the active Explore artifact as `Explore · <company>` instead of reusing the file lifecycle stage label.
- The root cause was `AgentPanel`'s fallback context branch: any non-document, non-thread, non-diligence, non-report tab used `formatResearchStageLabel(file.stage)`, so a diligence-stage file on the Explore tab rendered as `Diligence · Microsoft Corporation`.
- Explore's empty-state rail brief now uses Explore-specific guidance instead of saying the Diligence artifact is active. Diligence and Report tabs keep their explicit artifact labels and prompts.

Verification:

- Focused rail test: `1 file / 7 tests passed`.
- Broad research component suite: `21 files / 243 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Targeted ESLint for `AgentPanel` and its test: pass.
- Live in-app browser reload on `http://localhost:3000/#research/MSFT`: rail title showed `Explore · Microsoft Corporation`, stale `Diligence · Microsoft Corporation` was absent, no browser warning/error logs, and no horizontal overflow.

Open follow-ups:

- This batch only covers normal Explore rail context text. It does not alter Diligence/Report artifact behavior, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 2 research-list ticker aggregation

Research-list triage follow-up batch status:

- The research list now collapses repeated ticker rows into an aggregate ticker header so generated live-run files no longer dominate the first viewport.
- The root cause was that the list remained strictly file-row centric: repeated durable files for the same ticker, especially F131/live-verification runs, sorted individually by recency and crowded out the triage surface.
- Aggregate rows group by normalized ticker, compute the `latest` label from max `updatedAt`, show mixed metadata honestly when grouped files differ, aggregate thread counts, and expose `Show N files` / `Hide` disclosure controls.
- Aggregate headers do not navigate, open, or compare a hidden file. Exact `Open` and `Compare` actions remain on individual child rows after expansion, preserving `research_file_id` identity and file-specific labels.
- Long aggregate summaries truncate inside the company cell, and zero/unrated conviction rows preserve the prior dash behavior instead of rendering empty conviction dots.

Verification:

- Focused list/container/compare regression pack: `3 files / 39 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/#research`: PCTY rendered as an aggregate `18 files · latest F131 live...` row with `Show 18 files`; expanding revealed exact F131 rows; no browser warning/error logs and no horizontal overflow.
- Code review subagent: PASS after fixing aggregate identity, sort-independent latest metadata, disclosure state, and zero-conviction rendering.
- Visual review subagent: PASS after confirming the aggregate row reads as ticker-level triage rather than a merged research-file identity.

Open follow-ups:

- This batch only covers normal research-list ticker aggregation. It does not alter research persistence, compare route resolution, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 3 analyst rail secondary marker clarity

Analyst-rail visual follow-up batch status:

- Secondary analyst-rail context markers no longer render as literal `○` glyphs.
- The root cause was that `RailSignalMarker` reused a hollow-circle text character for secondary context lines, which made rail context read like progress or conviction dots instead of simple list punctuation.
- Primary analyst findings keep the `⚑` marker; secondary context now uses a decorative CSS-only bordered dot with `aria-hidden`, preserving the context lines without exposing ambiguous text.

Verification:

- Focused rail/list tests: `2 files / 24 tests passed`.
- Targeted ESLint for `AgentPanel`, `AgentPanel.test`, `ResearchListView`, and `ResearchListView.test`: pass.
- Live in-app browser smoke on `http://localhost:3000/#research/MSFT`: the rail no longer contained `○`, still showed `2 active threads · 1 flagged` and posture/lens context, no browser warning/error logs, and no horizontal overflow.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal analyst-rail marker presentation. It does not alter rail data selection, conversation feeds, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 3 workspace disclosure affordance clarity

Workspace-shell visual follow-up batch status:

- `Framing` and `Actions` are now rendered as expandable disclosure controls, not forward-navigation/action links.
- The root cause was shared action styling: the disclosure summaries used the same gold `→` glyph as true exit/action links, so the shell header blurred the difference between opening local controls and navigating to a next artifact.
- The disclosure summaries now use neutral compact chevrons that rotate with the `details` open state.
- Real action links still keep their gold arrows, including `Open report`, exit ramps, and thread/action rows inside expanded menus.

Verification:

- Focused workspace test: `1 file / 36 tests passed`.
- Targeted ESLint for `ResearchWorkspace` and `ResearchWorkspacePhase3.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/#research/MSFT`: `Framing` and `Actions` summaries each had one SVG chevron and zero `→` text; expanded `Actions` still showed `Open report→`; no gateway error remained after retry, no browser warning/error logs, and no horizontal overflow. Screenshot captured at `/tmp/research-disclosure-smoke-20260528.png`.

Open follow-ups:

- This batch only covers normal research workspace shell disclosure affordances. It does not alter action semantics, research persistence, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 2 research-list briefing prose spacing

Research-list visual follow-up batch status:

- The research-list briefing paragraphs now opt out of inherited compressed prose spacing with explicit `tracking-normal`.
- The root cause was global body prose spacing (`letter-spacing: -0.01em`) applying to the briefing. With short count phrases, the live screenshot made normal text read as jammed tokens such as `2flagged`.
- The fix is scoped to the list briefing lead and attention paragraphs. It does not change table typography, row actions, global CSS, aggregation behavior, or any reader/report surface.

Verification:

- Focused list test: `1 file / 17 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser reload on `http://localhost:3000/?briefingSpacing=17799999#research`: both briefing paragraphs reported `letterSpacing: normal`; the list had no `TEST`, no `DELETE-TEST`, no generic `Thread N`, no browser warning/error logs, and no horizontal overflow. Screenshot captured at `/tmp/research-list-briefing-spacing-20260528.png`.

Open follow-ups:

- This batch only covers normal research-list briefing prose spacing. It does not alter research persistence, compare route resolution, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 2 research-list group disclosure affordance clarity

Research-list visual follow-up batch status:

- Grouped ticker rows now render `Show N files` / `Hide` as disclosure controls with neutral chevrons instead of forward action arrows.
- The root cause was shared action-arrow styling: aggregate-row disclosure buttons reused the same gold `->` grammar as true navigation/actions (`Open`, `Open comparison`, `Start new research`), so expanding a group looked like leaving the list.
- Collapsed disclosures use a down chevron; expanded disclosures rotate the chevron upward. True row actions still keep the gold forward arrow.

Verification:

- Focused list test: `1 file / 17 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/?groupDisclosureShot=17799999#research`: grouped `Show N files` controls each had one chevron SVG and zero `->`; expanded `Hide` controls had rotated chevrons and zero `->`; real `Open->` row actions still kept their arrows; no browser warning/error logs and no horizontal overflow. Screenshot captured at `/tmp/research-list-group-disclosure-chevron-20260528.png`.

Open follow-ups:

- This batch only covers normal research-list group disclosure affordances. It does not alter grouping semantics, compare/open actions, research persistence, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 2 research-route timestamp mutation fix

Research-route persistence follow-up batch status:

- Opening an existing research route now resolves the file through read-only file-list data before hydrating the workspace.
- The root cause was that `bootstrapResearchWorkspace` used `POST /api/research/content/files` for direct route opens. The upstream research API treats that endpoint as an upsert, and `repo.upsert_file(...)` previously updated `research_files.updated_at` on every ticker/label conflict.
- The frontend route-open path no longer calls the file upsert endpoint, and a missing direct route now surfaces a not-found bootstrap error instead of silently creating a new research file.
- The upstream AI-excel-addin repository also now preserves `updated_at` for no-op file upsert conflicts, while still updating `company_name` and `updated_at` when the supplied company name materially changes.

Verification:

- Frontend focused hook test: `1 file / 14 tests passed`.
- Targeted ESLint for `useResearchContent.ts` and `useResearchContent.test.tsx`: pass.
- AI-excel-addin focused repository test: `28 passed`.
- AI-excel-addin repository lint: `ruff check api/research/repository.py` passed. The repository-schema test file still has pre-existing E402 path-bootstrap warnings when linted directly.
- Live in-app browser smoke on `#research/GE`, `#research/MSFT`, `#research/MSFT:pair%20review`, and `#research/compare/88,87`: no gateway errors, no browser warning/error logs, and routed opens left `research_files.updated_at` unchanged.
- Explicit `Start new research` smoke for existing `GE` opened the existing workspace and left `GE.updated_at` unchanged.
- Code review subagents: PASS for both frontend and backend batches.
- Visual review subagents: PASS for both frontend and backend batches.

Commits:

- risk_module: `cfd93da8 Avoid file upsert when opening research routes`
- AI-excel-addin: `5766b927 Preserve research file timestamps on no-op upsert`

Open follow-ups:

- The workspace bootstrap still uses reserved-thread creation endpoints for Explore/Panel thread IDs. That is idempotent when reserved threads exist, but route-open can still create missing reserved infrastructure for older or partial files. Treat any broader read-only workspace bootstrap redesign as a separate architecture task.
- This batch does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Phase 3 related-thread route sync

Normal workspace route lifecycle follow-up batch status:

- Analyst-rail related-thread links now route through the workspace tab selector instead of calling `researchStore.setActiveTab` directly.
- The root cause was that `AgentPanel` changed the active thread locally while bypassing `ResearchWorkspace.handleSelectTab`, which is the code path that updates both active tab state and navigation context. A related-thread click could therefore change the visible thread while leaving the URL at the previous `#research/<ticker>/thread/<id>` route.
- `AgentPanel` now accepts an optional `onSelectThread` callback and falls back to the store setter for standalone tests/usages. `ResearchWorkspace` passes `handleSelectTab`, so normal workspace related-thread clicks keep tab state and hash routes aligned.

Verification:

- Focused tests: `2 files / 44 tests passed`.
- Broad research component suite: `21 files / 250 tests passed`; existing happy-dom iframe abort stderr from `SourceHtmlPane` remained non-fatal and reader-owned.
- Targeted ESLint for `AgentPanel`, `ResearchWorkspace`, and `ResearchWorkspacePhase3.test`: pass.
- Live in-app browser smoke: direct `#research/MSFT/thread/48` loaded Sector & Industry; clicking the analyst rail related-thread link switched the visible pane to Valuation Deep Dive and updated the hash to `#research/MSFT/thread/15`; browser Back returned both hash and visible pane to Sector & Industry; no browser warning/error logs.
- Additional live smoke covered normal Diligence/Report routes, list stage/sort controls, grouped-row expand/collapse, labelled `MSFT:pair review` open, same-ticker comparison `#research/compare/88,437`, and research exit ramps to stress-test/trading; all passed without browser warning/error logs.
- Route-open timestamp check left `research_files.updated_at` unchanged for AAPL, MSFT, MSFT pair review, and GE.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Commits:

- risk_module: `943464a6 Sync research related-thread routes`

Open follow-ups:

- This batch only covers normal research workspace related-thread route sync and follow-on route/list smoke verification. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, report artifact architecture, or the F131 harness artifact isolation follow-up.

### 2026-05-28 Phase 3 research-list pinned briefing surface

Research-list visual hierarchy follow-up batch status:

- The research-list lead, attention line, and `Start new research ->` action now render inside a single `bg-surface-raised` `rounded-[4px]` briefing block, matching the preview's pinned-finding treatment.
- The root cause was that the briefing copy and start action were loose children of the list header surface, so the first viewport still read as operational page chrome instead of a distinct analyst briefing before the table.
- The create form remains outside the raised briefing block, so opening it does not turn the pinned insight into a form container.
- Filters, sort, compare status/action, grouped rows, mobile rows, retry state, create submission, and table density are unchanged.

Verification:

- Focused research-list test: `1 file / 17 tests passed`.
- Focused list/workspace regression pack: `2 files / 54 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- Live in-app browser smoke on `http://localhost:3000/#research`: briefing rendered with class `max-w-3xl rounded-[4px] bg-surface-raised px-4 py-3`, computed background `rgb(33, 37, 45)`, `4px` radius, table and Stage/Sort/Open comparison controls remained present below, start action opened and closed the create form outside the briefing block, and browser warning/error logs were empty.
- In-app screenshot capture timed out at the browser runtime after the interaction smoke had passed; visual verification used DOM/computed-style evidence and subagent review.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal research-list briefing container hierarchy. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, table data semantics, compare routing, or research-file persistence.

### 2026-05-28 Phase 3 research-list table-first hierarchy

Research-list visual hierarchy follow-up batch status:

- The research-list dense rows now appear immediately after the raised briefing, and the Stage/Sort/Compare control strip renders after the rows.
- The root cause was that the secondary control strip still led the list body, so the first viewport order remained briefing -> controls -> table instead of the preview and plan order of briefing -> rows -> secondary controls.
- Stage filtering, sort selection, compare status/action, grouped rows, mobile rows, create flow, retry flow, and table behavior are unchanged.

Verification:

- Focused research-list test: `1 file / 17 tests passed`.
- Focused list/workspace regression pack: `2 files / 54 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/#research`: briefing bottom `237`, table top `271`, table bottom `681`, Stage control top `711`; DOM order placed the table before Stage, Sort, and Open comparison; Stage filtered to Diligence and restored All stages; browser warning/error logs were empty.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal research-list hierarchy. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, compare routing, table data semantics, or research-file persistence.

### 2026-05-28 Phase 3 normal workspace durable tab visibility

Tab-bar follow-up batch status:

- Normal desktop research workspaces now keep durable non-closeable workspace tabs such as Diligence and Report visible before filling remaining tab-strip slots with closeable thread/document tabs.
- The root cause was that `ResearchTabBar` filled normal desktop tab slots with closeable tabs before it considered other non-closeable workspace artifacts. With several closeable tabs open, Diligence and Report could be pushed into `More` despite being durable workspace destinations.
- Compact normal workspaces (`visibleTabLimit <= 3`) and reader variant tab bars keep the previous stricter overflow behavior.
- Tab selection, close actions, overflow menu closing, reader tab overflow styling, new-thread action, and active-tab visibility are unchanged.

Verification:

- Focused tab-bar test: `1 file / 9 tests passed`.
- Focused tab/workspace regression pack: `2 files / 46 tests passed`.
- Targeted ESLint for `ResearchTabBar` and `ResearchTabBar.test`: pass.
- `git diff --check`: pass for scoped files.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Known verification limit:

- The in-app browser and Chrome browser automation backends were unavailable during this batch, so browser-level visual smoke could not be completed. This batch is covered by component/integration tests and subagent review, and should receive a live browser spot-check when browser automation is available again.

Open follow-ups:

- This batch only covers normal workspace tab visibility priority. It does not alter document-reader tab limits, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, report artifact architecture, or research persistence.

### 2026-05-28 Phase 3 focused-thread pinned finding surface

Focused-thread visual hierarchy follow-up batch status:

- Focused thread pinned findings now use the preview's raised `finding-pinned` treatment: `bg-surface-raised`, `rounded-[4px]`, compact padding, and 14px body copy.
- The root cause was that `ThreadTab` still rendered the pinned finding as a loose bordered section, so the focused-thread first pane did not match the preview's conclusion-first artifact treatment.
- The `Pin Finding` action, thread metadata, collapsed-history toggle, message feed, and update-thread mutation behavior remain intact.

Verification:

- Focused thread-tab test: `1 file / 3 tests passed`.
- Focused thread/workspace regression pack: `2 files / 40 tests passed`.
- Targeted ESLint for `ThreadTab` and `ThreadTab.test`: pass.
- `git diff --check`: pass for scoped files.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Known verification limit:

- In-app browser and Chrome extension automation were unavailable during this batch, so browser-level visual smoke could not be completed. This batch is covered by class-level tests, code inspection, and subagent review; browser smoke should be re-run when browser automation is available again.

Open follow-ups:

- This batch only covers the focused-thread pinned finding surface. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, message persistence, or thread update semantics.

### 2026-05-28 Phase 3 workspace disclosure metadata clarity

Normal-workspace header follow-up batch status:

- The `Framing` disclosure trigger now separates the label from its current metadata summary with a muted slash (`Framing / Long · General · Unrated`), so the header reads as a quiet secondary control rather than a compressed metadata run.
- The secondary `Actions` disclosure uses the same treatment (`Actions / 1`) so the count reads as metadata, not as an undelimited label suffix.
- The root cause was that the disclosure triggers rendered labels and compact metadata as adjacent inline text. At header scale, this looked like jammed label/value tokens even though the accessible labels were clear.
- The separators are visual-only (`aria-hidden`) and the existing accessible disclosure labels remain `Framing: <summary>` and `Actions: <count> available`.
- No document-reader header, F156 reader route, source HTML rendering, or reader rail behavior was changed.

Verification:

- Focused workspace Phase 3 test: `1 file / 37 tests passed`.
- Focused non-reader research regression pack: `4 files / 70 tests passed`.
- Targeted ESLint for `ResearchWorkspace` and `ResearchWorkspacePhase3.test`: pass.
- Live Playwright smoke on `http://localhost:3000/#research/MSFT`: triggers rendered as `Framing/Long · General · Unrated` and `Actions/1`; accessible labels remained `Framing: Long · General · Unrated` and `Actions: 1 available`; no gold action arrows appeared inside either disclosure; no horizontal overflow; and browser warning/error logs were empty. Screenshots captured at `/tmp/research-framing-slash-1440.png` and `/tmp/research-header-disclosures-1440.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal workspace header disclosure readability. It does not alter metadata/action behavior, persistence, tab routing, document-reader behavior, F122, or F156-owned reader architecture.

### 2026-05-28 Phase 2 research-list briefing state alignment

Research-list transient-state follow-up batch status:

- The research-list briefing now renders state-aware copy while the file list is loading or failed, instead of showing the empty-list onboarding sentence before the actual loading/error band.
- The root cause was that the raised briefing selected its empty copy only from `files.length`, so transient `files=[]` states during loading or request failure looked like a true empty workspace.
- True empty lists still show the existing start-first-file copy, while loading states say `Loading active research files.` and failed loads say `Research files could not be loaded.`
- The raised briefing surface, `Start new research ->` action, create flow, retry flow, table rows, compare controls, and list grouping behavior remain unchanged.

Verification:

- Focused research-list test: `1 file / 18 tests passed`.
- Focused list/container/compare regression pack: `3 files / 40 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- `git diff --check`: pass for scoped files.
- Playwright smoke on `http://localhost:3000/#research` with an injected `/api/research/content/files` 503: briefing rendered `Research files could not be loaded.`, `Start the first research file` and `No research files yet.` were absent, there was no horizontal overflow, and the only console errors were the intentionally injected 503 request.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal research-list transient briefing copy. It does not alter research-file persistence, compare routing, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, or harness artifact isolation.

### 2026-05-28 Phase 5 report timeframe label formatting

Report framing follow-up batch status:

- Report thesis framing now formats known timeframe tokens such as `long_term`, `long-term`, `medium`, and `near_term` as human labels instead of leaking raw schema vocabulary into the frozen report.
- The root cause was that `HandoffReviewView` passed direction and strategy through `formatResearchStageLabel`, but rendered `thesis.timeframe` with `String(...)` directly.
- Already-human timeframe copy such as `12-18 months` remains unchanged, so producer-authored prose/ranges are preserved.

Verification:

- Focused handoff review test: `1 file / 9 tests passed`.
- Focused report/workspace regression pack: `2 files / 46 tests passed`.
- Targeted ESLint for `HandoffReviewView` and `HandoffReviewView.test`: pass.
- Live Playwright smoke on `http://localhost:3000/#research/MSFT/report`: report framing rendered `Long Term`, `long_term` was absent from the page, no horizontal overflow, and browser warning/error logs were empty. Screenshot captured at `/tmp/research-report-timeframe-label-1440.png`.
- Code review subagent: PASS after replacing the initial heuristic with an explicit timeframe label map.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers report framing label formatting. It does not alter handoff artifact data, report persistence, typed-output rendering, F122, document-reader behavior, or F156-owned reader architecture.

### 2026-05-28 Phase 3 active-thread rail finding alignment

Focused-thread rail-context follow-up batch status:

- The normal workspace analyst rail now uses the active thread's pinned finding as its primary rail signal while a focused thread tab is active.
- The recent-exchange block also reads from the active thread's own messages instead of the panel thread, so stale panel summaries such as "No pinned thread findings yet" cannot appear under a thread that already has a pinned finding.
- The rail composer targets the same active thread while a focused thread tab is active, keeping the visible recent-exchange block and optimistic/streamed messages in the same thread.
- The empty recent-exchange copy is now thread-specific: `No recent exchanges in this thread yet.`
- The root cause was that `AgentPanel` mixed active-tab identity with panel-thread message summaries and send state. The focused pane could show a pinned finding while the rail still summarized or wrote to the background panel thread, creating contradictory analyst context.
- Explore, diligence, report, document presentation, related-thread navigation, and composer behavior remain unchanged.

Verification:

- Focused analyst rail test: `1 file / 8 tests passed`.
- Focused thread/workspace regression pack: `3 files / 48 tests passed`.
- Targeted ESLint for `AgentPanel` and `AgentPanel.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/#research/MSFT/thread/15`: the rail showed `Thread · Valuation Deep Dive`, the pressure-test lead, the same `MSFT trades at 34x P/E` pinned finding as the main thread pane, `No recent exchanges in this thread yet.`, no old workspace/panel fallback text, and no horizontal overflow. Screenshot captured at `/tmp/research-thread-rail-finding-20260528-iab-send-target-loaded.png`.
- Code review subagent: PASS after aligning the visible rail message source and composer send target to the same active thread id.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal workspace active-thread rail context. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, report artifact architecture, or research persistence.

### 2026-05-28 Phase 3 focused-thread feed chrome

Focused-thread workstream follow-up batch status:

- Focused thread feeds now suppress generic `You` / `Analyst` timestamp metadata while preserving the existing visual author distinction: user bullets, agent accent rails, user-note labels, and compact tool rows.
- The root cause was that `ConversationFeed` treated `chrome="thread"` like default transcript chrome for metadata. That made focused threads read like raw chat logs, while the preview and Phase 3 plan define threads as workstreams where the visual rail/bullet treatment carries authorship.
- Workspace chrome already suppressed this metadata, so the change narrows the same preview-aligned treatment to focused thread feeds without changing default conversation feeds.
- The Phase 1 rail input policy in this plan now matches the shipped active-thread rail contract: when the rail presents active-thread context, it reads from and writes to that active thread.

Verification:

- Focused thread/feed tests: `2 files / 7 tests passed`.
- Focused shared research workspace regression pack: `4 files / 90 tests passed`.
- Targeted ESLint for `ConversationFeed`, `ThreadTab.test`, and `ConversationFeed.citations.test`: pass.
- `git diff --check`: pass for scoped files.
- Live in-app browser smoke on `http://localhost:3000/#research/MSFT/thread/48`: the thread body showed the saved MSFT sector/industry analyst message with visual workstream chrome, no visible author/timestamp metadata in the main pane, no horizontal overflow, and no browser warning/error logs. Screenshot captured at `/tmp/research-thread-feed-chrome-20260528-iab.png`.

Open follow-ups:

- This batch only covers normal focused-thread feed chrome and the rail input-policy plan correction. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, report artifact architecture, or research persistence.

### 2026-05-28 Phase 3 Explore single-prompt hierarchy

Normal Explore workspace hierarchy follow-up batch status:

- The normal Explore tab no longer renders its own bottom composer; the analyst rail is now the single prompt surface for the Explore workspace.
- The root cause was duplicated input ownership: `ExploreTab` kept a main-pane `MessageInput` while `AgentPanel` also rendered the active analyst prompt. That made the main artifact and contextual rail compete for the same user action.
- Explore still owns the conversation timeline and branch/open-thread actions. The rail remains responsible for analyst prompting, context, and compact workspace scan.
- Thread creation from an Explore exchange, existing-thread routing, tab routing, and exit ramps are unchanged.

Verification:

- Focused Explore/workspace tests: `2 files / 39 tests passed`.
- Focused non-reader research regression pack: `4 files / 88 tests passed`.
- Targeted ESLint for `ExploreTab`, `ResearchWorkspace`, and touched tests: pass.
- TypeScript check: `pnpm --dir frontend exec tsc --noEmit --pretty false` passed.
- `git diff --check`: pass for scoped files.
- Live Playwright smoke on `http://localhost:3000/#research/MSFT`: only one visible input remained, with placeholder `Ask the analyst...`; `Ask about MSFT` and `Ask about this company` were absent; the URL stayed at `#research/MSFT`; no horizontal overflow; and browser warning/error logs were empty. Screenshot captured at `/tmp/research-explore-single-prompt-1780011002624.png`.
- Code review subagent: PASS.
- Visual review subagent: PASS.

Open follow-ups:

- This batch only covers normal Explore prompt-surface ownership. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, report artifact architecture, or research persistence.

### 2026-05-28 Phase 2 research-list capped ticker grammar

Research-list briefing copy follow-up batch status:

- Capped ticker lists in the deterministic briefing now render as `AAA, BBB, CCC, DDD, EEE, plus 2 more` instead of `AAA, BBB, CCC, DDD, and EEE, plus 2 more`.
- The root cause was that capped lists reused the full-list joiner, which adds a final `and` before the visible last ticker even though the list continues with `plus N more`.
- Uncapped one-, two-, and three-plus ticker lists keep the existing readable `and` grammar.

Verification:

- Focused research-list test: `1 file / 18 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- Live Playwright smoke on `http://localhost:3000/#research`: the briefing rendered `AAPL, PCTY, GE, MSFT, VALE, plus 1 more are in exploration`, no horizontal overflow, and browser warning/error logs were empty.

Open follow-ups:

- This batch only covers normal research-list briefing copy. It does not alter table rows, grouping semantics, compare routing, research persistence, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, or F156 behavior.

### 2026-05-28 Follow-up issue: F131 harness artifacts in research list

Finding:

- The live research list is inflated by multiple `PCTY / F131 live ...` research files created by `AI-excel-addin/tests/integration/f131_agent_loop.py`.
- These rows are not empty local placeholders. Most have reserved threads plus thesis, handoff, model-build-context, model-insight, or price-target rows, so deleting them with the local dev cleanup helper would risk removing real harness output.
- The root cause is that the live harness writes test-run research files into the same user research database that powers the product research list. The UI is therefore accurately rendering harness artifacts as active research files.

Recommended fix path:

- Do not hard-code `F131 live` label exclusions in the product UI.
- Move the F131 live harness to an isolated user/workspace namespace or add a first-class source/sandbox marker in the research-file schema.
- Add an archival or visibility contract for harness-created research files, then migrate existing F131 rows into that contract.
- Only after that contract exists should the research list default to hiding sandbox/archived harness files while still allowing explicit inspection when needed.

Status:

- Filed as a separate architecture follow-up. No code change was made for this issue in the current batch.

### 2026-05-29 Phase 1 analyst rail width calibration

Normal workspace shell follow-up batch status:

- The non-reader workspace split now defaults to `78/22` instead of `76/24`, bringing the desktop analyst rail back into the plan's 280-320px target band on the current shell while preserving the existing resizable rail behavior.
- The rail minimum and maximum percentages are now named separately from the F156/document-reader constants, so future workspace tuning does not accidentally change the filing reader width gates.
- Prompt ownership is unchanged: Explore still has one visible rail prompt, and the current shipped placeholder contract remains contextual (`Ask about MSFT...`, `Ask about Valuation Deep Dive...`) rather than a second main-pane composer. The older 2026-05-28 smoke note that recorded `Ask the analyst...` is superseded by the current tests and live behavior.

Verification:

- Focused workspace/reader guardrail tests: `2 files / 83 tests passed`.
- Targeted ESLint for `ResearchWorkspace`: pass.
- Live in-app browser smoke on `http://localhost:3000/?qa=rail-width-20260529#research/MSFT`: the analyst rail measured `313px` wide at a `1605px` viewport, the only visible input remained `Ask about MSFT...`, there was no horizontal overflow, and no gateway unavailable state remained after preflight completed. Screenshot captured at `/tmp/research-rail-width-20260529-loaded.png`.
- Live in-app browser smoke on `http://localhost:3000/?qa=rail-width-20260529#research/MSFT/thread/15`: the analyst rail measured `313px`, retained `Thread · Valuation Deep Dive`, preserved the `MSFT trades at 34x P/E` pinned finding and empty-state copy, showed `Ask about Valuation Deep Dive...`, had no horizontal overflow, and browser logs contained no warnings or errors. Screenshot captured at `/tmp/research-rail-width-thread15-20260529.png`.

Open follow-ups:

- This batch only covers normal non-reader workspace shell sizing. It does not alter document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, report artifact architecture, research persistence, or the compact mobile stack.

### 2026-05-29 Phase 2 compare decision-log row treatment

Research-compare visual hierarchy follow-up batch status:

- Compare decision logs now render as a single hairline row list instead of separated raised blocks, matching the plan's dense comparison-table/narrative direction and reducing card-like chrome in the non-reader compare surface.
- Each history row keeps the existing date, patch summary, fresh-version marker, and idempotent replay copy. Compare data loading, report summaries, back navigation, and open-file actions are unchanged.

Verification:

- Focused compare/list/workspace regression pack: `3 files / 60 tests passed`.
- Targeted ESLint for `ResearchCompareView` and `ResearchCompareView.test`: pass.
- Live in-app browser smoke on `http://localhost:3000/?qa=compare-history-rows-20260529#research/compare/88,87`: the comparison loaded MSFT vs AAPL, preserved `Open MSFT`, `Open AAPL`, and `Back to files`, rendered decision history in a `divide-y` / `border-y` row container with transparent background, had no horizontal overflow, and browser logs contained no warnings or errors. Screenshot captured at `/tmp/research-compare-history-rows-20260529.png`.

Open follow-ups:

- This batch only covers normal research-compare decision-log chrome. It does not alter compare route resolution, report artifact rendering semantics, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or mobile stack behavior.

### 2026-05-29 Phase 3 locked diligence artifact alignment

Normal diligence artifact follow-up batch status:

- The finalized/locked Diligence tab now presents its locked-state copy as a top-aligned flat notice band instead of centering the message in the artifact canvas.
- The existing `Create New Version ->` action, locked copy, and report-finalized semantics are unchanged. The change only removes empty-state centering so the pane still reads like an active workspace artifact.

Verification:

- Focused diligence/compare/workspace regression pack: `3 files / 52 tests passed`.
- Targeted ESLint for `DiligenceTab` and `DiligenceTab.test`: pass.
- Live in-app browser smoke on `http://localhost:3000/?qa=diligence-locked-band-20260529#research/MSFT/diligence`: the locked surface measured `1071px` wide at the top of the pane (`y=136`), used `border-y`, transparent background, `align-items: flex-start`, and `justify-content: space-between`; `Create New Version` remained visible; the route had no horizontal overflow and browser logs contained no warnings or errors. Screenshot captured at `/tmp/research-diligence-locked-band-20260529.png`.

Open follow-ups:

- This batch only covers the normal locked Diligence pane. It does not alter Diligence section data, draft/finalize behavior, report artifact rendering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 diligence loading-state alignment

Normal diligence transient-state follow-up batch status:

- The transient `Diligence state is still loading.` pane now uses the same top-aligned flat status-band treatment as the locked Diligence artifact instead of centering placeholder copy in the workspace canvas.
- The loading semantics are unchanged: this only affects the visual frame while Diligence data is not yet present.

Verification:

- Focused diligence/workspace regression pack: `2 files / 49 tests passed`.
- Targeted ESLint for `DiligenceTab` and `DiligenceTab.test`: pass.
- Component coverage now asserts that the loading surface is a `role="status"` band with `border-y` / `border-border-subtle` and no centered placeholder classes.
- Live in-app browser probe on `http://localhost:3000/?qa=diligence-loading-band-20260529#research/AAPL/diligence`: current live data did not exercise the loading-state path; the route stayed on Explore with no gateway unavailable state and no horizontal overflow.
- Live in-app browser regression smoke on `http://localhost:3000/?qa=diligence-loading-band-20260529#research/MSFT/diligence`: the locked Diligence band still rendered at the top of the pane, `Create New Version` remained visible, there was no horizontal overflow, and browser logs contained no warnings or errors. Screenshot capture timed out on this pass, so DOM geometry/log evidence is the authoritative live evidence for this sub-batch.

Open follow-ups:

- This batch only covers the normal Diligence loading-state shell. It does not alter Diligence data fetching, draft/finalize behavior, report artifact rendering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report loading-state alignment

Normal report artifact follow-up batch status:

- The transient `Handoff review is loading.` pane now uses a top-aligned flat status band instead of centering placeholder copy in the report canvas.
- The report loading semantics are unchanged. This only aligns the transient report shell with the non-reader workspace treatment used by the Diligence loading/locked states.

Verification:

- Focused report/workspace regression pack: `2 files / 48 tests passed`.
- Targeted ESLint for `HandoffReviewView` and `HandoffReviewView.test`: pass.
- Component coverage now asserts that the loading surface is a `role="status"` band with `border-y` / `border-border-subtle` and no centered placeholder classes.
- Live in-app browser smoke on `http://localhost:3000/?qa=handoff-loading-band-20260529#research/MSFT/report`: the loaded report did not retain the loading surface, rendered `Research Report v7`, `REPORT SNAPSHOT`, `DECISION LOG THROUGH FINALIZATION`, `DOWNSTREAM ACTIONS`, and formatted `Long Term` without exposing raw `long_term`; there was no horizontal overflow and browser logs contained no warnings or errors. Screenshot capture timed out on this pass, so DOM/log evidence is the authoritative live evidence for this sub-batch.

Open follow-ups:

- This batch only covers the normal report loading-state shell. It does not alter report artifact rendering semantics, version history behavior, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report empty-state row treatment

Report artifact visual hierarchy follow-up batch status:

- Typed report-section empty states now render as flat dashed hairline rows instead of rounded dashed cards.
- The empty-state copy and section rendering semantics are unchanged. This reduces card chrome in report artifacts while keeping missing-section diagnostics visible.

Verification:

- Focused report-renderer/report/workspace regression pack: `3 files / 84 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts that an empty report section uses `border-y`, `border-dashed`, and `border-border-subtle`, and no longer uses `rounded-[8px]` or full `border` card framing.
- Live in-app browser smoke on `http://localhost:3000/?qa=report-empty-rows-20260529#research/MSFT/report`: the loaded report rendered `RESEARCH REPORT V7`, found a live `No entries in this section.` empty state with class `border-y border-dashed border-border-subtle`, computed `border-radius: 0px`, transparent background, no raw `long_term`, no horizontal overflow, and browser logs contained no warnings or errors. Screenshot capture timed out on this long report page, so DOM/log evidence is the authoritative live evidence for this sub-batch.

Open follow-ups:

- This batch only covers report-section empty-state chrome in `HandoffSectionRenderer`. It does not alter report artifact data semantics, source chips, narrative/table rendering, version history behavior, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report editorial peer row treatment

Report artifact visual hierarchy follow-up batch status:

- Editorial peer-set entries in typed report sections now render as a single hairline row list instead of separate rounded `bg-card` blocks.
- Peer ticker chips, peer names, source labels, provenance metadata, and rationale tooltips are unchanged.

Verification:

- Focused report-renderer/report/workspace regression pack: `3 files / 84 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts that editorial peer rows keep the existing metadata but no longer use `rounded-[8px]` or `bg-card`.
- Live in-app browser smoke on `http://localhost:3000/?qa=editorial-peer-rows-20260529#research/MSFT/report`: the loaded report rendered `RESEARCH REPORT V7`; the live editorial peer list used `divide-y divide-border-subtle border-y border-border-subtle`; the Amazon row used `space-y-2 px-4 py-3`, transparent background, `border-radius: 0px`, preserved `AMZN`, `Amazon.com Inc`, `editorial`, and `added by competitive-position · added at 2026-05-25`; no rounded peer-card wrappers remained; there was no horizontal overflow and browser logs contained no warnings or errors.

Open follow-ups:

- This batch only covers editorial peer-set row chrome in `HandoffSectionRenderer`. It does not alter report artifact data semantics, source chips, rationale tooltip behavior, narrative/table rendering, version history behavior, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report peer-comps empty row treatment

Report artifact visual hierarchy follow-up batch status:

- The report `Peer Comps` empty state now renders as the same flat dashed hairline row used by typed report-section empty states instead of falling through the shared `DataTable` empty card.
- Populated peer-comps tables still use the existing table renderer and API contract, so ticker/name rows and report data semantics are unchanged.

Verification:

- Focused report-renderer/report/workspace regression pack: `3 files / 85 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts that empty peer comps render with `border-y`, `border-dashed`, and `border-border-subtle`, with no `rounded-lg` or `bg-card`, and that no empty table shell is emitted.
- Live in-app browser smoke on `http://localhost:3000/?qa=peer-empty-row-20260529#research/MSFT/report`: the loaded report rendered `RESEARCH REPORT V7`; `No peer comps recorded.` used `border-y border-dashed border-border-subtle px-4 py-3 text-sm text-muted-foreground`, computed transparent background, dashed top/bottom 1px borders, and `border-radius: 0px`; no rounded/background card wrapper contained that peer-empty text; there was no horizontal overflow and browser warning/error logs contained no entries for this QA pass.

Open follow-ups:

- This batch only covers the empty `Peer Comps` row chrome in `HandoffSectionRenderer`. It does not alter populated peer-comps table rendering, report artifact data semantics, source chips, narrative/table rendering, version history behavior, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report differentiated-claim row treatment

Report artifact visual hierarchy follow-up batch status:

- Differentiated-view claims now render as a single hairline row list instead of separate rounded `bg-card` blocks.
- Claim labels, claim headlines, rationale text, evidence source chips, and upside/downside metric strips are unchanged.

Verification:

- Focused report-renderer/report/workspace regression pack: `3 files / 85 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts that differentiated-view claims render inside a `divide-y` / `border-y` row list, preserve evidence chips and metric strips, and no longer use `rounded-[8px]` or `bg-card` row chrome.
- Live in-app browser smoke on `http://localhost:3000/?qa=differentiated-claim-rows-20260529#research/MSFT/report`: the loaded report rendered `RESEARCH REPORT V7`, preserved the previously aligned peer-empty row, had no exact legacy `rounded-[8px] border border-border/70 bg-card` claim wrappers in the DOM, no raw `long_term`, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass. The current live MSFT report did not expose a standalone differentiated-claim row, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers differentiated-view claim row chrome in `HandoffSectionRenderer`. It does not alter report artifact data semantics, source chips, rationale content, metric strip rendering, narrative/table rendering, version history behavior, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report operating-comparison group row treatment

Report artifact visual hierarchy follow-up batch status:

- Operating-comparison metric groups now render as hairline accordion rows instead of separate rounded `bg-card` wrappers.
- Collapsed/expanded details behavior, group labels, metric counts, tooltip-only citations, peer/median rows, and table rendering are unchanged.

Verification:

- Focused report-renderer/report/workspace regression pack: `3 files / 85 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts that operating-comparison `details` rows use `px-4 py-3`, sit inside a `divide-y` / `border-y` list, remain collapsed by default, and no longer use `rounded-[8px]` or `bg-card`.
- Live in-app browser smoke on `http://localhost:3000/?qa=operating-comparison-rows-20260529#research/MSFT/report`: the loaded report rendered `RESEARCH REPORT V7`, preserved the previously aligned peer-empty row, had zero legacy `rounded-[8px] border border-border/70 bg-card` report wrappers in the DOM, no raw `long_term`, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass. The current live MSFT report did not expose an operating-comparison accordion, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers operating-comparison group wrapper chrome in `HandoffSectionRenderer`. It does not alter report artifact data semantics, tooltip/source behavior, populated table rendering, narrative rendering, version history behavior, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report table frame treatment

Report artifact visual hierarchy follow-up batch status:

- The shared `DataTable` now supports an opt-in `frame="flat"` mode. Existing callers keep the default rounded card frame.
- `HandoffSectionRenderer` uses the flat frame for report-owned peer-comparison, operating-comparison, and peer-comps tables so populated report tables follow the preview's hairline inline-table grammar instead of the default dashboard-card table shell.
- Table columns, sorting affordances, compact headers, row hover behavior, source chips, tooltip citations, and empty-state behavior are unchanged.

Verification:

- Focused report-renderer/report/workspace regression pack: `3 files / 85 tests passed`.
- Targeted ESLint for `DataTable`, `HandoffSectionRenderer`, and `HandoffSectionRenderer.test`: pass.
- TypeScript check: `pnpm --dir frontend exec tsc --noEmit --pretty false` passed.
- Component coverage now asserts report-owned sectioned peer-comparison, fallback peer-comparison, operating-comparison, and peer-comps tables render inside `border-y` / `bg-transparent` frames and no longer use `rounded-lg` or `bg-card`.
- Live in-app browser smoke on `http://localhost:3000/?qa=report-flat-tables-20260529#research/MSFT/report`: the loaded report rendered `RESEARCH REPORT V7`, had zero legacy rounded `bg-card` `DataTable` frames in the report DOM, no raw `long_term`, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass. The current live MSFT report did not expose populated report tables, so component coverage is the direct table-branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers report-owned `DataTable` frame chrome via an opt-in prop. It does not alter default `DataTable` behavior outside the report renderer, report artifact data semantics, source chips, tooltip/source behavior, row content, version history behavior, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report version-history row treatment

Report artifact visual hierarchy follow-up batch status:

- Report version-history actions now render as a hairline `border-y` row list rather than a loose stack of control blocks.
- The active version keeps the existing button behavior and `aria-current` state, but its visual state is now a transparent row with a 2px left accent instead of a background-filled control.
- Version labels, status badges, created/finalized timestamps, superseded-version loading, and read-only behavior are unchanged.

Verification:

- Focused report/workspace regression pack: `2 files / 48 tests passed`.
- Targeted ESLint for `HandoffReviewView` and `HandoffReviewView.test`: pass.
- Component coverage now asserts the active version button keeps `aria-current`, uses `border-b`, `border-l-2`, `border-l-primary`, and `bg-transparent`, and sits inside a `border-y border-border-subtle` row list.
- Live in-app browser smoke on `http://localhost:3000/?qa=version-history-rows-20260529#research/MSFT/report`: the loaded report rendered `RESEARCH REPORT V7`; the active v7 row retained `aria-current="true"`, used `border-l-2` with transparent background and `0px` radius, the version list used `border-y border-border-subtle`, there was no raw `long_term`, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass.

Open follow-ups:

- This batch only covers report version-history chrome in `HandoffReviewView`. It does not alter handoff selection behavior, active/superseded report loading, report artifact data semantics, report body rendering, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 diligence section hairline-token alignment

Normal Diligence artifact follow-up batch status:

- Editable Diligence section dividers, draft preview bands, preview grid cells, and empty-section bands now use `border-border-subtle` instead of the heavier generic `border-border` token.
- Server/user authorship left accents, accordion behavior, working-note editing, related jump links, save/confirm actions, source counts, and section data semantics are unchanged.

Verification:

- Focused diligence/workspace regression pack: `2 files / 49 tests passed`.
- Targeted ESLint for `DiligenceSection` and `DiligenceTab.test`: pass.
- Component coverage now asserts the empty Diligence section band, server-draft preview band, and preview grid cell use `border-border-subtle`.
- Live in-app browser smoke on `http://localhost:3000/?qa=diligence-section-borders-20260529#research/VALE/diligence`: the local VALE route rendered the locked Diligence artifact, had no gateway unavailable state, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass. The current live VALE state is locked and did not expose editable section preview bands, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers editable Diligence section separator/band tokens in `DiligenceSection`. It does not alter Diligence data fetching, section persistence, draft/confirm behavior, qualitative factor behavior, report finalization, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 diligence opening/factor band alignment

Normal Diligence artifact follow-up batch status:

- The editable Diligence draft header, opening-take band, qualitative-factor empty state, qualitative-factor list wrapper, and qualitative-factor rows now use the same subtle hairline treatment as the rest of the aligned Diligence surface.
- The filled opening take and qualitative-factor rows now stay transparent rather than using heavier surface backgrounds.
- Generate/refresh opening take, add/update/remove qualitative factors, rating selection, metric strips, authorship left accents, and factor data semantics are unchanged.

Verification:

- Focused diligence/workspace regression pack: `2 files / 49 tests passed`.
- Targeted ESLint for `DiligenceTab`, `DiligenceOpeningTake`, `QualitativeFactorsSection`, `QualitativeFactorCard`, and `DiligenceTab.test`: pass.
- Component coverage now asserts the editable draft header, opening-take band, qualitative-factor empty state, and qualitative-factor row use `border-border-subtle` / transparent row treatment.
- Live in-app browser smoke on `http://localhost:3000/?qa=diligence-adjacent-bands-20260529#research/VALE/diligence`: the local VALE Diligence route rendered the locked artifact, had no gateway unavailable state, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass. The locked surface remained transparent with `border-y border-border-subtle` and `0px` radius. The current live VALE state is locked and did not expose editable draft/factor rows, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers editable Diligence opening/factor band chrome in `DiligenceTab`, `DiligenceOpeningTake`, `QualitativeFactorsSection`, and `QualitativeFactorCard`. It does not alter Diligence data fetching, opening-take generation, qualitative-factor persistence, rating controls, modal behavior, report finalization, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 compare content-band transparency

Compare surface visual hierarchy follow-up batch status:

- Compare thesis, catalyst, risk, and report-section loading bands now use transparent hairline rows instead of filled `bg-surface` / `bg-background` blocks.
- Decision-log rows, overview file summaries, report loading/fallback copy, and compare navigation actions are unchanged.

Verification:

- Focused compare/list/workspace regression pack: `3 files / 60 tests passed`.
- Targeted ESLint for `ResearchCompareView` and `ResearchCompareView.test`: pass.
- Component coverage now asserts populated thesis/list bands and loading report-section bands use `border-border-subtle` with `bg-transparent`.
- Live in-app browser smoke on `http://localhost:3000/?qa=compare-content-bands-20260529#research/compare/88,87`: the comparison route rendered, had no gateway unavailable state, found transparent `border-y border-border-subtle` report-section content bands with `0px` radius, found zero legacy filled `bg-surface` compare content bands for thesis/catalyst/risk/fallback content, had no horizontal overflow, and browser warning/error logs contained no entries for this QA pass.

Open follow-ups:

- This batch only covers compare thesis/list/loading content-band chrome in `ResearchCompareView`. It does not alter compare route resolution, report/history fetch behavior, overview file summaries, decision-log rendering, open/back actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 compare overview band transparency

Compare surface visual hierarchy follow-up batch status:

- Compare overview file-summary bands now use transparent hairline treatment instead of filled `bg-surface` blocks.
- The `Latest report` row inside each overview now uses the same transparent `border-y` treatment instead of a filled left-callout block.
- File title/subtitle, stage/direction/strategy badges, conviction display, thread/flag/update metrics, latest-report status, and open-file actions are unchanged.

Verification:

- Focused compare/list/workspace regression pack: `3 files / 60 tests passed`.
- Targeted ESLint for `ResearchCompareView` and `ResearchCompareView.test`: pass.
- Component coverage now asserts the overview summary section and latest-report row use `border-border-subtle` with `bg-transparent`.
- Live in-app browser smoke on `http://localhost:3000/?qa=compare-overview-transparent-20260529#research/compare/88,87`: after the comparison hydrated, both MSFT and AAPL overview sections used `space-y-4 border-y border-border-subtle bg-transparent px-5 py-5`, their latest-report rows used `border-y border-border-subtle bg-transparent`, no legacy filled `section.border-y.border-border-subtle.bg-surface` overview sections remained, there was no gateway unavailable state, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass.

Open follow-ups:

- This batch only covers compare overview/latest-report band chrome in `ResearchCompareView`. It does not alter compare route resolution, report/history fetch behavior, overview data semantics, badges, metrics, decision-log rendering, open/back actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 compare header transparency

Compare surface visual hierarchy follow-up batch status:

- The compare route header now uses the same transparent hairline context-band treatment as the rest of the aligned Compare surface instead of a filled `bg-surface` band.
- Dateline, `Research Comparison` context label, pair title, and `Back to files` action are unchanged.

Verification:

- Focused compare/list/workspace regression pack: `3 files / 60 tests passed`.
- Targeted ESLint for `ResearchCompareView` and `ResearchCompareView.test`: pass.
- Component coverage now asserts the compare header uses `border-border-subtle` and `bg-transparent`.
- Live in-app browser smoke on `http://localhost:3000/?qa=compare-header-transparent-20260529#research/compare/88,87`: after hydration, the header rendered `MAY 29, 2026 · Research Comparison`, `MSFT vs AAPL`, and `Back to files`; its class was `flex flex-wrap items-start justify-between gap-3 border-y border-border-subtle bg-transparent px-5 py-5`, computed background was transparent, radius was `0px`, no legacy filled `bg-surface` compare header remained, there was no gateway unavailable state, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass.

Open follow-ups:

- This batch only covers compare route header chrome in `ResearchCompareView`. It does not alter compare route resolution, report/history fetch behavior, overview/content bands, decision-log rendering, open/back behavior, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 report lead-band transparency

Report review visual hierarchy follow-up batch status:

- The report review header, Report Snapshot metric grid, and Decision Lens metric grid now use transparent hairline treatment instead of filled `bg-surface` bands.
- Report version history rows, thesis/source rendering, downstream actions, decision-log filtering, section rendering, and new-version behavior are unchanged.

Verification:

- Focused report/workspace regression pack: `2 files / 48 tests passed`.
- Targeted ESLint for `HandoffReviewView` and `HandoffReviewView.test`: pass.
- Component coverage now asserts the report header, Report Snapshot grid, and Decision Lens grid use `border-border-subtle` with `bg-transparent`.
- Live in-app browser smoke on `http://localhost:3000/?qa=report-lead-transparent-20260529b#research/MSFT/report`: after gateway hydration, the MSFT report rendered `Research Report v7`, `Report Snapshot`, and `Decision Lens`; all three lead bands computed transparent backgrounds with `0px` radius, no legacy filled `bg-surface` lead bands remained, there was no gateway unavailable state, no raw `long_term` display, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass.
- QA note: the first browser pass hit `Research gateway unavailable. resolver timeout`. Port `8000` itself was healthy, but the gateway had been launched with `RISK_MODULE_RESOLVER_URL=http://localhost:5001/api/internal/resolve-credential`; restarting only the gateway with `http://127.0.0.1:5001/api/internal/resolve-credential` and `PRODUCT_ID=hank-dev` restored the research route. That service-launch hygiene should be tracked separately from the UI alignment work.

Open follow-ups:

- This batch only covers report lead-band chrome in `HandoffReviewView`. It does not alter report route resolution, handoff/history fetch behavior, report section rendering, new-version mutations, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 research-list lead-shell transparency

Research-list visual hierarchy follow-up batch status:

- The research-list dateline/briefing shell now uses transparent hairline treatment instead of a filled outer `bg-background`/inner `bg-surface` band.
- The preview-style raised briefing block remains intact, including its `rounded-[4px] bg-surface-raised` treatment and flat `Start new research ->` action.
- Create-file fields, table/mobile rows, filters, comparison actions, grouping behavior, loading/error/empty states, and row open/compare actions are unchanged.

Verification:

- Focused list/workspace regression pack: `2 files / 56 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- Component coverage now asserts the lead section and briefing wrapper use `border-border-subtle` / `bg-transparent`, while the briefing card stays `bg-surface-raised`.
- Live in-app browser smoke on `http://localhost:3000/?qa=list-lead-transparent-20260529#research`: the research list hydrated with 33 active files, the lead section computed transparent background with `0px` radius, the wrapper computed transparent background with `0px` radius, the briefing retained `rgb(33, 37, 45)` raised background and `4px` radius, no legacy filled lead shell remained, table rows and mobile rows rendered, there was no gateway unavailable state, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass.

Open follow-ups:

- This batch only covers research-list lead-shell chrome in `ResearchListView`. It does not alter research file fetching, create-file mutation behavior, sort/filter behavior, comparison navigation, grouping/expansion logic, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 research-list state-band transparency

Research-list state follow-up batch status:

- Research-list loading, empty, and load-error bands now use transparent hairline treatment instead of filled `bg-surface` blocks.
- Loading copy, empty copy, destructive error border/color, retry action, and state branching are unchanged.
- The populated file table/mobile rows and controls remain unchanged.

Verification:

- Focused list/workspace regression pack: `2 files / 56 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- Component coverage now asserts the loading, empty, and load-error bands use `bg-transparent` and no longer use `bg-surface`.
- Live in-app browser smoke on `http://localhost:3000/?qa=list-state-bands-retry-20260529#research`: after one retry for a transient gateway `web_timeout`, the populated research list hydrated, the lead section and wrapper remained transparent, the briefing retained its raised `4px` treatment, the table rendered 7 visible desktop rows, there was no gateway unavailable state, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass. The live route is populated, so component coverage is the direct branch evidence for loading/empty/error state bands.

Open follow-ups:

- This batch only covers research-list loading/empty/error band chrome in `ResearchListView`. It does not alter research file fetching, create-file mutation behavior, retry behavior, sort/filter behavior, comparison navigation, grouping/expansion logic, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 research-list table/control frame transparency

Research-list visual hierarchy follow-up batch status:

- The populated research-list desktop table frame, mobile row-list frame, and secondary filter/compare control band now use transparent hairline treatment instead of filled `bg-surface` / `bg-background` wrappers.
- The dense table, mobile rows, grouping/expansion, stage/sort controls, compare status, and open-comparison action are unchanged.

Verification:

- Focused list/workspace regression pack: `2 files / 56 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- Component coverage now asserts the desktop table frame, mobile row frame, and filter/control band use `border-border-subtle` with `bg-transparent`.
- Live in-app browser smoke on `http://localhost:3000/?qa=list-table-frames-20260529#research`: the populated research list hydrated, rendered table headers and 7 visible desktop rows, kept `All stages`, `Recently updated`, and `Open comparison ->` controls, table/mobile/control frames all computed transparent backgrounds with `0px` radius, no legacy filled list table/control frames remained, there was no gateway unavailable state, no horizontal overflow, and browser warning/error logs contained no entries for this QA pass.

Open follow-ups:

- This batch only covers populated research-list table/mobile/control frame chrome in `ResearchListView`. It does not alter research file fetching, create-file mutation behavior, retry behavior, sort/filter behavior, comparison navigation, grouping/expansion logic, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 research-list child-row transparency

Research-list grouped-row follow-up batch status:

- Expanded grouped child rows now keep the same transparent row treatment as the parent list instead of adding `bg-background/30` fill on desktop or mobile.
- Desktop list rows now use `hover:bg-transparent` so expanded grouped rows do not reintroduce filled hover bands.
- Group expand/collapse behavior, grouped file counts, row open actions, compare actions, mobile rows, filters, and create-file behavior are unchanged.

Verification:

- Focused list/workspace regression pack: `2 files / 56 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- Component coverage now asserts that expanded desktop child rows use `hover:bg-transparent` without `bg-background/30`, and expanded mobile child rows no longer use `bg-background/30`.
- Live in-app browser smoke on `http://localhost:3000/?qa=list-child-rows-timed-20260529#research`: the populated research list hydrated with 7 desktop rows, expanding `Show 3 files for MSFT` produced 10 desktop rows and 10 mobile list items, preserved `Hide MSFT related files`, `Open MSFT...`, and `Compare MSFT...` actions, kept table and mobile frames transparent, found zero legacy `bg-background/30` row fills, had no gateway unavailable state, no horizontal overflow, and browser warning/error logs contained no new entries for the timed QA pass.

Open follow-ups:

- This batch only covers expanded research-list child-row chrome in `ResearchListView`. It does not alter research file fetching, create-file mutation behavior, retry behavior, sort/filter behavior, comparison navigation, grouping/expansion logic, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report editorial-brief band transparency

Report artifact visual hierarchy follow-up batch status:

- The report Editorial Brief ready and loading containers now use transparent hairline treatment instead of filled `bg-surface` bands.
- Editorial brief slot separators now use `border-border-subtle`, matching the rest of the aligned report artifact row grammar.
- Brief polling, optional 204/404 hiding behavior, failed-state prompt, headline, slot ordering, incomplete/limited-data badges, evidence bullets, source refs, and `Why` details are unchanged.

Verification:

- Focused brief/report/workspace regression pack: `3 files / 57 tests passed`.
- Targeted ESLint for `ResearchBriefSection` and `ResearchBriefSection.test`: pass.
- Component coverage now asserts ready and loading Editorial Brief bands use `border-border-subtle` / `bg-transparent`, do not use `bg-surface`, and no longer emit `border-border/70` slot separators.
- Live fallback browser smoke on `http://localhost:3000/?qa=report-brief-band-headless-20260529#research/MSFT/report`: the MSFT report loaded, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The current live MSFT report did not expose an Editorial Brief section, so component coverage is the direct branch evidence for ready/loading brief band styling.

Open follow-ups:

- This batch only covers report Editorial Brief chrome in `ResearchBriefSection`. It does not alter brief fetching/polling semantics, report artifact data semantics, report section rendering, version history behavior, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 workspace state-band transparency

Normal workspace shell state follow-up batch status:

- Gateway preflight, compare-route loading/failure, and file bootstrap loading/failure bands now use transparent hairline treatment instead of filled `bg-surface` bands.
- Retry gateway, back-to-files, compare route loading, bootstrap route sync, long error wrapping, and active workspace/list navigation behavior are unchanged.

Verification:

- Focused workspace container/workspace regression pack: `2 files / 56 tests passed`.
- Targeted ESLint for `ResearchWorkspaceContainer` and `ResearchWorkspaceContainer.test`: pass.
- Component coverage now asserts gateway checking/failure, compare loading/failure, and bootstrap loading/failure state bands use `border-y border-border-subtle bg-transparent`, and no longer use `bg-surface` or generic `border-border`.
- Forced fallback browser smoke on `http://localhost:3000/?qa=workspace-state-band-forced-20260529#research/MSFT`: intercepting only `/api/research/content/preflight` produced the expected gateway alert with class `border-y border-border-subtle bg-transparent px-4 py-4`, computed transparent background, `0px` radius, visible `Retry gateway check ->` and `Back to research files ->` actions, and no horizontal overflow. The browser logs contained the expected intercepted 502 entries for this forced failure path.
- Normal fallback browser smoke on `http://localhost:3000/?qa=workspace-state-band-normal-20260529#research/MSFT`: the MSFT workspace loaded with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers normal non-reader workspace shell state-band chrome in `ResearchWorkspaceContainer`. It does not alter gateway preflight semantics, research file/bootstrap fetching, compare route resolution, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 normal workspace header/footer transparency

Normal workspace shell visual hierarchy follow-up batch status:

- The normal non-document workspace context header now uses transparent hairline treatment instead of a filled `bg-surface` band.
- The normal workspace exit-ramp footer now uses the same transparent hairline treatment, so the downstream action row reads as part of the workspace shell rather than a separate filled toolbar.
- Dateline/context labels, Framing disclosure, Actions disclosure, Back to files, exit-ramp labels, and exit-ramp navigation behavior are unchanged.

Verification:

- Focused workspace/container regression pack: `2 files / 56 tests passed`.
- Targeted ESLint for `ResearchWorkspace` and `ResearchWorkspacePhase3.test`: pass.
- Component coverage now asserts the normal Back-to-files header band and `Size a position` exit-ramp footer band use `border-border-subtle` / `bg-transparent`, and no longer use `bg-surface`.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=workspace-shell-bands-headless-20260529#research/MSFT`: the normal MSFT workspace loaded, preserved `Back to files` and `Size a position`, the header class was `border-b border-border-subtle bg-transparent px-4 py-2`, the footer class was `border-t border-border-subtle bg-transparent px-4 py-2`, both computed transparent backgrounds with `0px` radius, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers normal non-reader workspace header/footer chrome in `ResearchWorkspace`. It does not alter tab routing, Framing/Actions disclosure behavior, exit-ramp navigation semantics, document-reader header/footer behavior, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 normal workspace tab-strip transparency

Normal workspace tab visual hierarchy follow-up batch status:

- The normal workspace research tab strip now uses transparent hairline treatment instead of a filled `bg-surface` band.
- The compact reader variant remains on its existing `bg-surface` treatment so this batch does not change the F156-adjacent reader tab shell.
- Tab selection, close buttons, overflow behavior, durable-tab prioritization, compact normal overflow limits, new-thread action, and reader overflow behavior are unchanged.

Verification:

- Focused tab/workspace regression pack: `2 files / 47 tests passed`.
- Targeted ESLint for `ResearchTabBar` and `ResearchTabBar.test`: pass.
- Component coverage now asserts the default tab strip uses `border-border-subtle` / `bg-transparent` and no longer uses `bg-surface`, while the reader variant remains `bg-surface`.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=tab-strip-band-headless-20260529#research/MSFT`: the normal MSFT workspace loaded, preserved the `Explore` tab and `New research thread` action, the tab band class was `flex items-center border-b border-border-subtle bg-transparent min-h-10 px-4`, computed transparent background with `0px` radius, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers normal non-reader `ResearchTabBar` shell chrome. It does not alter tab identity/order, close/select semantics, overflow semantics, document-reader tab-bar behavior, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 analyst rail shell transparency

Normal workspace analyst rail follow-up batch status:

- Normal context/conversation analyst rails now use a transparent root shell instead of a filled `bg-surface` wrapper.
- The document presentation rail remains on `bg-surface`, preserving the F156/reader-adjacent surface treatment.
- Rail context labels, related-thread links, compact exchange summaries, markdown table summarization, placeholders, and composer behavior are unchanged.

Verification:

- Focused rail/workspace regression pack: `2 files / 47 tests passed`.
- Targeted ESLint for `AgentPanel` and `AgentPanel.test`: pass.
- Component coverage now asserts the normal rail root uses `bg-transparent`, the document presentation rail remains `bg-surface`, and the reader artifact panel still renders on the document presentation path.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=agent-panel-shell-headless-20260529#research/MSFT:Core`: the normal MSFT workspace loaded, preserved `Research Analyst` and `Ask about MSFT` rail copy, the rail root class was `flex h-full min-h-0 flex-col bg-transparent`, computed transparent background with `0px` radius, had no gateway unavailable state, no raw `long_term`, no horizontal overflow on desktop or mobile, and no browser warning/error logs on the final pass.
- QA caveat: an earlier unauthenticated headless pass captured one `/api/research/content/messages` fetch warning; a direct frontend-proxy request returned `401 Unauthorized` for that message-history request. The visible workspace still rendered from hydrated fixture state, so this was treated as an environment/auth caveat rather than a shell transparency regression.

Open follow-ups:

- This batch only covers normal non-reader `AgentPanel` shell chrome. It does not alter rail chat routing, document presentation behavior, `ReaderArtifactPanel` internals, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report version-rail transparency

Report artifact visual hierarchy follow-up batch status:

- The report version-history rail now uses transparent hairline treatment instead of a filled `bg-surface` sidebar.
- Version list framing, active-version indicator, superseded-version navigation, New Version action, report header, report body, and decision-log behavior are unchanged.

Verification:

- Focused report/workspace regression pack: `2 files / 48 tests passed`.
- Targeted ESLint for `HandoffReviewView` and `HandoffReviewView.test`: pass.
- Component coverage now asserts the version-history rail uses `border-r border-border-subtle bg-transparent`, does not use `bg-surface`, and keeps the existing version-list row treatment.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=report-version-rail-headless-20260529#research/MSFT/report`: the MSFT report loaded, the version-history rail class was `border-r border-border-subtle bg-transparent`, computed transparent background with `0px` radius, no legacy `aside.bg-surface` rail remained, `Research Report`, `Version History`, and `New Version` controls were present, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow on desktop or mobile, and no browser warning/error logs on the final pass.
- QA caveat: an earlier unauthenticated headless pass captured one `/api/research/content/files` fetch warning; a direct frontend-proxy request returned `401 Unauthorized` for that request. The report route still rendered from hydrated fixture state, so this was treated as an environment/auth caveat rather than a version-rail regression.

Open follow-ups:

- This batch only covers normal report review version-rail chrome in `HandoffReviewView`. It does not alter handoff/history fetching, active handoff mutation, superseded-version review semantics, report artifact rendering, build/export/download actions, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 normal workspace canvas transparency

Normal workspace shell visual hierarchy follow-up batch status:

- The normal research workspace outer shell and active content pane now use transparent canvas treatment instead of `bg-background`.
- Document-reader mode explicitly keeps its existing `bg-background` shell and content pane treatment, preserving the F156/reader-owned surface.
- Tab routing, active pane selection, Explore/Diligence/Report rendering, resizable analyst rail behavior, normal header/footer chrome, and document-reader controls are unchanged.

Verification:

- Focused workspace/rail regression pack: `2 files / 47 tests passed`.
- Targeted ESLint for `ResearchWorkspace` and `ResearchWorkspacePhase3.test`: pass.
- Component coverage now asserts normal workspace shell/content pane use `bg-transparent`, while document-reader shell/content pane remain `bg-background`.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=workspace-content-shell-headless-20260529#research/MSFT`: the normal MSFT workspace loaded, the shell class was `flex flex-col bg-transparent border-y border-border-subtle overflow-hidden h-full min-h-[40rem]`, the active content pane class was `min-h-0 flex-1 bg-transparent`, both computed transparent backgrounds with `0px` radius, no document-reader shell rendered on the normal route, `Research workspace`, `Back to files`, and `Size a position` remained present, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow on desktop or mobile, and no browser warning/error logs.

Open follow-ups:

- This batch only covers normal non-reader workspace shell/content canvas chrome in `ResearchWorkspace`. It does not alter active tab selection, tab identity/order, resizable layout sizing, document-reader shell/content treatment, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 diligence empty-badge transparency

Normal diligence artifact visual hierarchy follow-up batch status:

- Empty Diligence section completion badges now use transparent hairline treatment instead of a filled `bg-background` badge.
- Draft and confirmed badges keep their existing semantic colored treatments.
- Empty-section copy, accordion behavior, save/confirm actions, draft summaries, source refs, jump links, and locked/loading Diligence states are unchanged.

Verification:

- Focused diligence/workspace regression pack: `2 files / 49 tests passed`.
- Targeted ESLint for `DiligenceSectionHeader` and `DiligenceTab.test`: pass.
- Component coverage now asserts the empty completion badge uses `border-border-subtle bg-transparent` and no longer uses `bg-background`.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=diligence-empty-badge-headless-20260529#research/MSFT/diligence`: the current live MSFT Diligence route rendered the locked Diligence surface, so it did not expose empty completion badges; the route still had no gateway unavailable state, no raw `long_term`, no horizontal overflow on desktop or mobile, and no browser warning/error logs. Component coverage is the direct branch evidence for the empty-badge styling.

Open follow-ups:

- This batch only covers normal Diligence section empty completion-badge chrome in `DiligenceSectionHeader`. It does not alter Diligence data, draft/confirmed semantic badge treatments, save/confirm behavior, locked/new-version behavior, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 analyst rail collapsed-composer transparency

Normal workspace analyst rail follow-up batch status:

- The normal collapsed analyst composer band now uses transparent hairline treatment instead of a translucent `bg-background/45` wrapper.
- The embedded input field, contextual placeholder, send behavior, streaming/error behavior, and document-presentation composer path are unchanged.

Verification:

- Focused rail/workspace regression pack: `2 files / 47 tests passed`.
- Targeted ESLint for `AgentPanel` and `AgentPanel.test`: pass.
- Component coverage now asserts the collapsed composer wrapper uses `border-border-subtle bg-transparent` and no longer uses `bg-background/45`.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=agent-collapsed-composer-headless-20260529#research/MSFT`: the normal MSFT workspace loaded, the collapsed composer wrapper class was `border-t border-border-subtle bg-transparent p-2`, computed transparent background with `0px` radius, the prompt placeholder remained `Ask about MSFT...`, the analyst rail shell remained `bg-transparent`, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow on desktop or mobile, and no browser warning/error logs on the final pass.

Open follow-ups:

- This batch only covers normal non-reader `AgentPanel` collapsed-composer wrapper chrome. It does not alter rail chat routing, input behavior, document presentation behavior, `ReaderArtifactPanel` internals, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report editorial-peer chip transparency

Report artifact visual hierarchy follow-up batch status:

- Editorial peer ticker/source chips now use transparent hairline treatment instead of older `border-border/70` and `bg-surface-2` chip chrome.
- Editorial peer rows remain a flat hairline row list; peer names, rationale tooltip behavior, provenance metadata, and row ordering are unchanged.

Verification:

- Focused report-renderer/report regression pack: `2 files / 47 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts editorial peer ticker chips use `border-border-subtle bg-transparent` instead of `border-border/70`, and source chips use `border-border-subtle bg-transparent` instead of `bg-surface-2`.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=editorial-peer-chip-headless-20260529#research/MSFT/report`: the MSFT report loaded with a live Editorial Peer Set, the `AMZN` ticker chip and `editorial` source chip both used `border border-border-subtle bg-transparent`, computed transparent backgrounds with `6px` radius, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow on desktop or mobile, and no browser warning/error logs on the final pass.

Open follow-ups:

- This batch only covers editorial peer chip chrome in `HandoffSectionRenderer`. It does not alter report artifact data semantics, peer-set row structure, rationale tooltip behavior, source/provenance metadata, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report watch-item badge transparency

Report artifact visual hierarchy follow-up batch status:

- Monitoring watch-item metadata badges now use transparent hairline treatment instead of older `border-border/70` / `bg-muted/30` chip chrome.
- Watch-item description, metric/threshold/last-checked metadata, source refs, source popovers, and list ordering are unchanged.

Verification:

- Focused report-renderer/report regression pack: `2 files / 47 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts watch-item Metric/Threshold/Last checked badges use `border-border-subtle bg-transparent`, and no longer use `border-border/70` or `bg-muted/30`; the source-ref popover branch remains covered.
- Live in-app Browser was attempted but the current Codex browser pane was unavailable, so a fallback headless browser smoke was used for this sub-batch.
- Fallback browser smoke on `http://localhost:3000/?qa=watch-item-badge-headless-20260529#research/MSFT/report`: the MSFT report loaded on desktop and mobile; the live watch-item `Metric` and `Threshold` badges used `border border-border-subtle bg-transparent`, computed transparent backgrounds with `6px` radius, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs after filtering known unauthenticated `/api/research/content/*` warnings.

Open follow-ups:

- This batch only covers report monitoring watch-item badge chrome in `HandoffSectionRenderer`. It does not alter report artifact data semantics, watch-list row structure, metric threshold semantics, source/provenance metadata, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2/5 flat table separator token alignment

Research list and report table visual hierarchy follow-up batch status:

- Shared flat `DataTable` instances now use `border-border-subtle` header separators and `divide-border-subtle` body separators instead of the heavier generic `border-border/60` / `divide-border/40` tokens.
- The research-list desktop table now uses `border-border-subtle` on its header and data rows so the custom list table matches the already-aligned flat frame and mobile row list.
- Default `DataTable` card framing remains unchanged for non-flat consumers.
- Research-list table rows, mobile rows, open/compare actions, grouping, sorting/filtering, and report table data rendering are unchanged.

Verification:

- Focused report/list regression pack: `2 files / 55 tests passed`.
- Targeted ESLint for `DataTable`, `ResearchListView`, `ResearchListView.test`, and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts report flat `DataTable` frames keep `bg-transparent`, use `border-border-subtle` on `thead`, and use `divide-border-subtle` on `tbody`; research-list coverage asserts the custom desktop table frame/header/data rows use subtle separators.
- In-app Browser smoke loaded `http://localhost:3000/?qa=flat-table-separators-iab-20260529#research` and `http://localhost:3000/?qa=flat-table-separators-iab-20260529#research/MSFT/report` with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; the live in-app data state did not expose inspectable table branches on those routes.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=flat-table-separators-headless-rerun-20260529#research`: the desktop research-list table frame was `border-y border-border-subtle bg-transparent`, the header/data rows used `border-border-subtle`, the mobile row list used `border-y border-border-subtle bg-transparent`, and there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs after filtering known unauthenticated `/api/research/content/*` warnings.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=flat-table-separators-headless-rerun-20260529#research/MSFT/report`: the report route loaded on desktop and mobile with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs; the live MSFT report did not expose a table branch, so component coverage is the direct report-table evidence for this sub-batch.

Open follow-ups:

- This batch only covers flat table separator tokens in `DataTable` and the custom `ResearchListView` table. It does not alter table data semantics, sorting/filtering, row grouping, compare/open actions, report section rendering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 business-segment divider token alignment

Report artifact visual hierarchy follow-up batch status:

- Large business-overview segment sets now use `border-border-subtle` divider rows instead of the heavier generic `border-border/60` separator.
- Inline short segment summaries, segment names, revenue-percent values, source refs, and business-overview narrative rendering are unchanged.

Verification:

- Focused report-renderer/report regression pack: `2 files / 48 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now exercises the larger segment-grid branch and asserts the segment row uses `border-border-subtle` and no longer uses `border-border/60`, while preserving segment values.
- In-app Browser smoke attempted `http://localhost:3000/?qa=segment-divider-iab-20260529#research/MSFT/report`; the page loaded with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs, but that in-app pass did not expose the report artifact/segment branch.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=segment-divider-headless-20260529#research/MSFT/report`: the report route loaded on desktop and mobile with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs after filtering known unauthenticated `/api/research/content/*` warnings. The live MSFT report did not expose the larger segment-grid branch, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers large business-overview segment divider tokens in `HandoffSectionRenderer`. It does not alter report artifact data semantics, business-overview narrative content, source chips/popovers, table rendering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 operating-comparison median row transparency

Report artifact visual hierarchy follow-up batch status:

- Operating-comparison median rows in flat report tables now use transparent treatment instead of the filled `bg-surface-2/50` row state.
- Median labeling, italic/medium emphasis, values, tooltip-only citations, collapsed details behavior, and peer rows are unchanged.

Verification:

- Focused report-renderer/report regression pack: `2 files / 48 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now opens the operating-comparison details branch and asserts the `Median` row uses `bg-transparent` and no longer uses `bg-surface-2/50`, while preserving values and citation tooltip behavior.
- In-app Browser smoke on `http://localhost:3000/?qa=median-row-iab-20260529#research/MSFT/report`: the report route loaded with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; the live MSFT report did not expose a median operating-comparison row.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=median-row-headless-20260529#research/MSFT/report`: the report route loaded on desktop and mobile with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs after filtering known unauthenticated `/api/research/content/*` warnings. The live MSFT report did not expose the median operating-comparison row, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers operating-comparison median row chrome in `HandoffSectionRenderer`. It does not alter report artifact data semantics, operating-comparison row construction, metric formatting, tooltip/source behavior, table rendering outside the median row, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 flat table row-hover transparency

Report artifact visual hierarchy follow-up batch status:

- Shared flat `DataTable` rows now use transparent hover/active row treatment instead of the filled `hover:bg-surface-2/60` / `bg-surface-2/70` defaults used by card tables.
- Default card-framed `DataTable` behavior remains unchanged.
- Report table row data, metric formatting, source/citation behavior, sorting headers, and empty states are unchanged.

Verification:

- Focused report-renderer/report regression pack: `2 files / 48 tests passed`.
- Targeted ESLint for `DataTable` and `HandoffSectionRenderer.test`: pass.
- Component coverage now opens a flat report `DataTable` branch and asserts the row uses `hover:bg-transparent` and no longer uses `hover:bg-surface-2/60`; the existing median-row coverage also preserves `bg-transparent` and removes `bg-surface-2/50`.
- In-app Browser smoke on `http://localhost:3000/?qa=flat-table-row-hover-iab-20260529#research/MSFT/report`: the route stayed healthy with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs, but that in-app pass did not hydrate the report artifact/table branch.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=flat-table-row-hover-headless-20260529#research/MSFT/report`: the report route loaded on desktop and mobile with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs after filtering known unauthenticated `/api/research/content/*` warnings. The live MSFT report did not expose a flat report table, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers flat `DataTable` row hover/active chrome. It does not alter default card-table behavior, report artifact data semantics, sorting, source/citation rendering, table frame/header/body tokens, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 embedded composer input transparency

Normal workspace analyst rail follow-up batch status:

- The embedded collapsed analyst composer textarea now uses `bg-transparent` instead of `bg-background/55`, matching the already-aligned transparent collapsed composer wrapper.
- Default non-embedded `MessageInput` styling and document-presentation composer usage are unchanged.
- Placeholder text, Enter-to-send behavior, Shift+Enter newline behavior, retry/error state, controlled draft state, and send dispatch behavior are unchanged.

Verification:

- Focused input/rail regression pack: `2 files / 12 tests passed`.
- Targeted ESLint for `MessageInput`, `MessageInput.test`, and `AgentPanel.test`: pass.
- Component coverage now asserts the embedded composer input uses `bg-transparent`, no longer uses `bg-background/55`, and still sends the entered text on Enter.
- In-app Browser smoke on `http://localhost:3000/?qa=embedded-composer-iab-20260529#research/MSFT`: the normal MSFT workspace loaded, the collapsed composer wrapper stayed `border-t border-border-subtle bg-transparent p-2`, the embedded textarea used `bg-transparent` with computed transparent background, the placeholder remained `Ask about MSFT...`, and there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=embedded-composer-headless-20260529#research/MSFT`: desktop and mobile both found the embedded composer textarea with `bg-transparent`, computed transparent background, preserved `Ask about MSFT...`, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs after filtering known unauthenticated `/api/research/content/*` warnings.

Open follow-ups:

- This batch only covers the embedded collapsed `MessageInput` textarea chrome used by the normal analyst rail. It does not alter default composer styling, document-presentation rail behavior, chat routing, input semantics, streaming/error behavior, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 default conversation empty-state transparency

Conversation feed visual hierarchy follow-up batch status:

- The default `ConversationFeed` empty state now uses a transparent dashed hairline band instead of the older `bg-surface/40` fill.
- Workspace and thread feed variants were already flat and are unchanged.
- Empty copy, message rendering, citation rendering, inline start-thread actions, tool-call rows, user-note rows, open-in-reader behavior, and streaming/error state handling are unchanged.

Verification:

- Focused conversation-feed regression pack: `1 file / 5 tests passed`.
- Targeted ESLint for `ConversationFeed` and `ConversationFeed.citations.test`: pass.
- Component coverage now asserts the default empty state uses `border-y border-dashed border-border-subtle bg-transparent` and no longer uses `bg-surface/40`.
- In-app Browser smoke on `http://localhost:3000/?qa=conversation-empty-default-iab-20260529#research/MSFT`: the normal MSFT research route loaded with research content, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; the live route did not expose the default empty-state branch.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=conversation-empty-default-headless-20260529#research/MSFT`: desktop and mobile routes loaded with research content, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs; the live route did not expose the default empty-state branch, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers default `ConversationFeed` empty-state chrome. It does not alter workspace/thread feed variants, message/citation semantics, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 default composer transparency with reader route-around

Normal workspace analyst rail follow-up batch status:

- The default non-reader `MessageInput` composer wrapper, textarea, and send-button hover state now use transparent chrome instead of the older `bg-background/45`, `bg-surface/70`, and `hover:bg-surface` fills.
- The embedded collapsed composer remains transparent and unchanged.
- Document-presentation composer usage now opts into an explicit `reader` chrome variant so the reader-owned surface keeps its prior `bg-background/45` wrapper, `bg-surface/70` textarea, and filled send-button hover treatment.
- Placeholder text, controlled draft state, Enter-to-send behavior, Shift+Enter newline behavior, retry/stop actions, streaming/error state, and send dispatch behavior are unchanged.

Verification:

- Focused input/rail regression pack: `2 files / 14 tests passed`.
- Targeted ESLint for `MessageInput`, `MessageInput.test`, `AgentPanel`, and `AgentPanel.test`: pass.
- Component coverage now asserts default non-reader composer chrome is transparent, embedded composer behavior still sends, and reader chrome preserves the old filled treatment.
- In-app Browser smoke on `http://localhost:3000/?qa=default-composer-iab-20260529#research/MSFT`: the normal MSFT route loaded with research content, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; that in-app state did not expose the exit-ramp action needed to open the expanded default composer.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=default-composer-headless-20260529#research/MSFT`: desktop and mobile routes loaded with research content, the `Compare to holdings` exit-ramp opened the queued default composer, the wrapper class was `border-t border-border-subtle p-1.5 bg-transparent`, the textarea used `min-h-9 bg-transparent` with computed transparent background, the send button used `hover:bg-transparent`, the queued prompt remained `Compare MSFT to our current holdings and flag the closest analogs or overlaps.`, and there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs.

Open follow-ups:

- This batch only covers `MessageInput` composer chrome and the explicit reader route-around in `AgentPanel`. It does not alter chat routing, message sending semantics, document presentation content, `ReaderArtifactPanel` internals, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 normal tab-overflow panel transparency

Normal workspace tab-overflow follow-up batch status:

- The default non-reader `ResearchTabBar` overflow panel now uses transparent hairline treatment instead of an opaque `bg-background` panel fill.
- The compact reader overflow path remains on its existing bordered `bg-background` / `shadow-lg` popover treatment.
- Hidden-tab count, overflow selection, close behavior, visible-tab prioritization, compact normal tab limits, new-thread action, and Diligence progress labels are unchanged.

Verification:

- Focused tab-bar regression pack: `1 file / 9 tests passed`.
- Targeted ESLint for `ResearchTabBar` and `ResearchTabBar.test`: pass.
- Component coverage now asserts the default overflow panel uses `border-t border-border-subtle bg-transparent` and no longer uses `bg-background`, while the reader overflow panel still uses `bg-background` and `shadow-lg`.
- In-app Browser smoke on `http://localhost:3000/?qa=tab-overflow-transparent-iab-20260529#research/MSFT`: the normal MSFT route loaded with research content, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; that in-app viewport did not expose tab overflow.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=tab-overflow-transparent-headless-20260529#research/MSFT`: desktop loaded without tab overflow; compact and mobile viewports exposed the normal `More` overflow panel with class `absolute right-0 z-20 mt-1 w-max min-w-48 max-w-[min(18rem,calc(100vw-2rem))] border-t border-border-subtle bg-transparent px-2 py-2`, computed transparent background, `0px` radius, hidden `Diligence locked` and `Report v7` actions preserved, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs.

Open follow-ups:

- This batch only covers normal non-reader `ResearchTabBar` overflow-panel chrome. It does not alter tab identity/order, close/select semantics, overflow semantics, document-reader tab-bar behavior, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 normal workspace disclosure-panel transparency

Normal workspace header disclosure follow-up batch status:

- The normal `Framing` and `Actions` disclosure panels now use transparent desktop panel treatment instead of `md:bg-background`.
- Disclosure triggers were already flat and are unchanged.
- Framing metadata controls, secondary workflow actions, accessible summary labels, visible slash/count treatment, chevron behavior, metadata update dispatch, report/diligence actions, and exit-ramp behavior are unchanged.

Verification:

- Focused workspace disclosure regression pack: `1 file / 38 tests passed`.
- Targeted ESLint for `ResearchWorkspace` and `ResearchWorkspacePhase3.test`: pass.
- Component coverage now asserts both the `Framing` panel and `Actions` panel keep `border-border-subtle`, use `md:bg-transparent`, and no longer use `md:bg-background`.
- In-app Browser smoke on `http://localhost:3000/?qa=workspace-disclosure-panels-core-iab-20260529#research/MSFT:Core`: the route loaded with research content, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; that in-app state did not expose the normal workspace header disclosure controls.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=workspace-disclosure-panels-core-headless-20260529#research/MSFT:Core`: desktop exposed both header disclosures; opening `Framing` preserved `Framing: Long · Compounder · 4/5`, `Direction: Long`, and a panel class of `mt-2 border-t border-border-subtle pt-2 md:absolute md:right-0 md:z-20 md:w-max md:bg-transparent md:px-2 md:py-2 md:max-w-[min(34rem,calc(100vw-2rem))]` with computed transparent background and `0px` radius; opening `Actions` preserved `Actions: 1 available`, `Form thesis ->`, and a matching `md:bg-transparent` panel with computed transparent background and `0px` radius. Desktop and mobile had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs; mobile did not expose these header disclosure controls in the current compact layout.

Open follow-ups:

- This batch only covers normal non-reader `ResearchWorkspace` header disclosure-panel chrome. It does not alter disclosure trigger semantics, metadata updates, secondary action routing, exit-ramp navigation semantics, document-reader header/footer behavior, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 Diligence editor textarea transparency

Editable Diligence follow-up batch status:

- `DiligenceSection` working-note textareas now use `bg-transparent` instead of a local `bg-background` override.
- `QualitativeFactorCard` assessment textareas now use `bg-transparent` instead of a local `bg-background` override.
- Section preview bands, empty states, qualitative factor rows, rating select styling, save/confirm actions, factor create modal behavior, and locked Diligence presentation are unchanged.
- Working-note draft submission and qualitative-factor update payloads are unchanged.

Verification:

- Focused Diligence regression pack: `1 file / 11 tests passed`.
- Targeted ESLint for `DiligenceSection`, `QualitativeFactorCard`, and `DiligenceTab.test`: pass.
- Component coverage now asserts both editable textarea branches use `bg-transparent`, no longer use `bg-background`, and still submit/update the same payloads.
- In-app Browser smoke on `http://localhost:3000/?qa=diligence-textareas-iab-20260529#research/MSFT/diligence`: the route stayed healthy with research content, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; that in-app state did not expose the Diligence branch.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=diligence-textareas-desktop-retry-20260529#research/MSFT/diligence`: the live MSFT Diligence route loaded its locked finalized surface with `Diligence LOCKED`, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs. The live locked route did not expose editable Diligence textareas, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers editable Diligence textarea chrome in `DiligenceSection` and `QualitativeFactorCard`. It does not alter Diligence data fetching, section persistence semantics, qualitative-factor persistence semantics, AddFactorModal behavior, report finalization, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 research-message markdown table row separators

Conversation rendering follow-up batch status:

- `ResearchMessageContent` markdown table body rows now use `border-border-subtle` separators instead of the older generic `border-border/50` separator.
- The table frame remains `border-y border-border-subtle`, and the table header remains transparent.
- Markdown parsing, quick-fact metric-strip promotion, citation rendering, table headers, numeric-cell alignment, prose fallback, and message content are unchanged.

Verification:

- Focused message-content/feed regression pack: `2 files / 11 tests passed`.
- Targeted ESLint for `ResearchMessageContent`, `ResearchMessageContent.test`, and `ConversationFeed.citations.test`: pass.
- Component coverage now asserts markdown table data rows use `border-border-subtle`, no longer use `border-border/50`, and still preserve no-wrap headers/numeric cells.
- In-app Browser smoke on `http://localhost:3000/?qa=message-table-separators-iab-20260529#research/MSFT:Core`: the normal MSFT workspace route loaded with research content, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; the live route did not expose a research-message markdown table.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=message-table-separators-headless-20260529#research/MSFT:Core`: desktop and mobile loaded with research content, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs; the live route did not expose a research-message markdown table, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers normal research-message markdown table row separators in `ResearchMessageContent`. It does not alter conversation feed routing, citation semantics, metric-strip extraction, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 research-list create-input transparency

Research-list create flow follow-up batch status:

- The `Start new research` create-form ticker and label inputs now use `border-border-subtle bg-transparent` instead of the older `border-border bg-background` overrides.
- The preview-style raised briefing block remains intact, and the create form remains outside that block.
- `Start new research`, `New File`, create validation, create mutation payloads, create-error rendering, filters, sorting, compare actions, table rows, grouping, and mobile rows are unchanged.

Verification:

- Focused research-list regression pack: `1 file / 18 tests passed`.
- Targeted ESLint for `ResearchListView` and `ResearchListView.test`: pass.
- Component coverage now asserts both create-form inputs use `border-border-subtle bg-transparent`, no longer use `border-border` or `bg-background`, while the existing create-failure coverage preserves the draft ticker and mutation payload.
- In-app Browser smoke on `http://localhost:3000/?qa=list-create-inputs-iab-20260529#research`: the route stayed healthy with no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs; that in-app state did not expose the research-list entry branch.
- Fixed-viewport fallback browser smoke on `http://localhost:3000/?qa=list-create-inputs-headless-20260529#research`: desktop and mobile exposed the research-list entry branch, opened `Start new research`, preserved `New File`, and both `Research ticker` / `Research label` inputs rendered with `border-border-subtle bg-transparent` and computed transparent backgrounds; there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no unexpected browser warning/error logs.

Open follow-ups:

- This batch only covers research-list create-form input chrome in `ResearchListView`. It does not alter research file fetching, create-file mutation behavior, retry behavior, sort/filter behavior, comparison navigation, grouping/expansion logic, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 neutral stage-badge border token alignment

Research stage badge follow-up batch status:

- Neutral `ResearchStageBadge` paths now use `border-border-subtle` instead of the older generic `border-border` token.
- The changed paths are `monitoring`, `closed`, and unknown/fallback stage values.
- Accent stage tones remain unchanged for `exploring`, `diligence` / `has thesis`, and `decision`.
- Stage label formatting, research list grouping, compare rendering, file metadata, filters, sorting, and navigation behavior are unchanged.

Verification:

- Focused presentation/list/compare regression pack: `3 files / 24 tests passed`.
- Targeted ESLint for `ResearchPresentation` and `ResearchPresentation.test`: pass.
- Component coverage now asserts neutral badge paths use `border-border-subtle`, no longer use `border-border`, and preserve muted/dim text treatment.
- Component coverage also asserts the preview-directed accent badge tones still render for `Exploring`, `Diligence`, and `Decision`.
- In-app Browser smoke on `http://localhost:3000/?qa=stage-badge-20260529#research`: the research list route rendered, exposed existing `Exploring` and `Diligence` badge samples with unchanged accent border classes, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live seed data did not expose `Monitoring` or `Closed`, so component coverage is the direct branch evidence for neutral badges.

Open follow-ups:

- This batch only covers stage badge chrome in `ResearchPresentation`. It does not alter research file fetching, grouped ticker aggregation, create-file mutation behavior, compare selection, compare rendering semantics, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 add-factor modal border token alignment

Diligence add-factor modal follow-up batch status:

- The `Add Qualitative Factor` dialog frame now uses `border-border-subtle` instead of the older generic `border-border` token.
- The modal remains a filled dialog surface with `bg-background`, preserving the expected modal affordance rather than flattening it into the workspace canvas.
- Strategy suggestions, seeded category suggestions, category/label inputs, cancel behavior, create validation, create payload shape, and modal close behavior are unchanged.

Verification:

- Focused Diligence regression pack: `1 file / 11 tests passed`.
- Targeted ESLint for `AddFactorModal` and `DiligenceTab.test`: pass.
- Component coverage now asserts the open dialog uses `border-border-subtle`, no longer uses `border-border`, and still renders the strategy suggestion set.
- In-app Browser smoke on `http://localhost:3000/?qa=add-factor-modal-border-20260529#research/VALE/diligence`: the route rendered the locked VALE Diligence workspace, preserved `Create New Version`, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live state was locked and did not expose the add-factor modal branch, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers the Diligence add-factor modal border token. It does not alter Diligence lock/versioning behavior, factor creation semantics, strategy/category suggestion content, research persistence, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, or the mobile stack.

### 2026-05-29 Phase 5 report row-list divider token alignment

Report row-list follow-up batch status:

- Handoff/report row-list groups now use `divide-border-subtle` instead of the older `divide-border/60` token.
- Covered branches include invalidation triggers, industry macro drivers, industry structural trends, catalyst/risk narrative lists, assumptions, qualitative factors, monitoring watch lists, and generic object-array fallback rows.
- Report data extraction, source chips, metadata lines, row identity keys, disclosure behavior, watch-item badges, and empty-state behavior are unchanged.

Verification:

- Focused report renderer/review regression pack: `2 files / 49 tests passed`.
- Targeted ESLint for `HandoffSectionRenderer` and `HandoffSectionRenderer.test`: pass.
- Component coverage now asserts all updated row-list branches use `divide-border-subtle` and no longer use `divide-border/60`.
- In-app Browser smoke on `http://localhost:3000/?qa=handoff-row-dividers-20260529#research/MSFT/report`: after hydration, the MSFT report rendered with updated `divide-y divide-border-subtle` row groups for live report sections including watch/invalidation, macro driver, structural trend, editorial peer, assumptions, and trigger content. The route had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.
- One remaining live `divide-border/60` sample came from the shared design `MetricStrip` grid divider, not the report row-list branches covered by this batch.

Open follow-ups:

- This batch only covers handoff/report row-list divider tokens in `HandoffSectionRenderer`. It does not alter report artifact parsing, report versioning, source/citation popovers, shared `MetricStrip`, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1/3/5 research metric-strip flat chrome

Research metric-strip follow-up batch status:

- `MetricStrip` now supports an opt-in `chrome="flat"` path that uses `border-border-subtle bg-transparent` and `divide-border-subtle`.
- The default `MetricStrip` chrome remains unchanged for non-research consumers.
- Research message metric strips, report/handoff metric strips, and Diligence qualitative-factor metric strips now opt into the flat chrome.
- Metric extraction, metric values, citations promoted into metric values, Diligence factor editing, report source chips, and report artifact parsing are unchanged.

Verification:

- Focused design/research regression pack: `5 files / 67 tests passed`.
- Targeted ESLint for `MetricStrip`, `MetricStrip.test`, `HandoffSectionRenderer`, `HandoffSectionRenderer.test`, `ResearchMessageContent`, `ResearchMessageContent.test`, `QualitativeFactorCard`, and `DiligenceTab.test`: pass.
- Shared component coverage now asserts default `MetricStrip` remains `border-border/80 bg-background divide-border/60`, while `chrome="flat"` uses `border-border-subtle bg-transparent divide-border-subtle`.
- Research component coverage now asserts report, research-message, and Diligence metric strips use the flat chrome and no longer use the older filled frame/divider classes.
- In-app Browser smoke on `http://localhost:3000/?qa=flat-metric-strip-20260529#research/MSFT/report`: after hydration, the live report metric strip rendered as `border-border-subtle bg-transparent` with `divide-border-subtle`, computed transparent background, zero live `divide-border/60` metric-strip dividers, zero old metric-strip frames, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers research-owned opt-in uses of `MetricStrip`. It does not change default `MetricStrip` chrome for portfolio/scenario/dashboard consumers, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 focused text-dialog border token alignment

Normal research text-dialog follow-up batch status:

- `TextInputDialog` now supports an opt-in `chrome="research"` path that uses `border-border-subtle` while preserving the filled `bg-background` modal affordance.
- The default dialog chrome remains `border-border bg-background`, so reader-owned `DocumentTab` usage keeps its prior treatment.
- Normal Explore thread naming, focused-thread `Pin Finding`, and normal workspace thread naming opt into the subtle-border research chrome.
- `ResearchWorkspace` routes the dialog chrome through `isDocumentReading`, so document-reader mode remains on the default path.
- Dialog open/close behavior, submit trimming, disabled-submit behavior, create-thread mutations, pin-finding mutations, document selection semantics, and reader-owned dialog usage are unchanged.

Verification:

- Focused dialog/workspace regression pack: `3 files / 43 tests passed`.
- Targeted ESLint for `TextInputDialog`, `TextInputDialog.test`, `ExploreTab`, `ThreadTab`, `ThreadTab.test`, and `ResearchWorkspace`: pass.
- Component coverage now asserts default `TextInputDialog` preserves `border-border bg-background` and submit trimming, while `chrome="research"` uses `border-border-subtle bg-background`.
- Thread coverage now opens `Pin Finding` and asserts the focused-thread dialog uses `border-border-subtle` instead of `border-border`.
- In-app Browser smoke on `http://localhost:3000/?qa=text-dialog-chrome-20260529#research/MSFT/thread/15`: the normal focused-thread route rendered, opening `Pin Finding` produced a dialog with `border-border-subtle bg-background`, no old `border-border`, no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers normal research text-dialog border chrome and the explicit document-reader route-around. It does not alter `DocumentTab` dialog styling, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, create-thread semantics, pin-finding persistence, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 add-factor modal action chrome alignment

Diligence add-factor modal follow-up batch status:

- `AddFactorModal` suggestion/category option buttons now use transparent subtle-outline chrome instead of the older filled outline-button treatment.
- The modal footer now uses the same flat Diligence action grammar as editable section actions: muted secondary `Cancel` and primary-text `Add Factor`.
- The shared Diligence action base now explicitly carries `border-0 bg-transparent shadow-none`, making the existing flat-action contract concrete across Diligence actions.
- Category suggestion application, label seeding, disabled create state, create payload shape, modal close behavior, and Diligence persistence semantics are unchanged.

Verification:

- Focused Diligence/workspace regression pack: `2 files / 49 tests passed`.
- Targeted ESLint for `diligenceStyles`, `AddFactorModal`, and `DiligenceTab.test`: pass.
- Component coverage now asserts the strategy suggestion button uses `border-border-subtle bg-transparent`, the footer actions use transparent flat action chrome, the create action remains disabled until a category is selected, selecting `Competitive Moat` seeds the same category/label values, and the create payload/close callback remain unchanged.
- In-app Browser smoke on `http://localhost:3000/?qa=add-factor-actions-20260529#research/VALE/diligence`: the route hydrated to the locked VALE Diligence workspace, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live state did not expose the editable add-factor modal branch, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers Diligence add-factor modal action chrome and the shared flat-action base. It does not alter factor creation semantics, suggestion content, Diligence lock/versioning behavior, report finalization, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 add-factor modal input chrome alignment

Diligence add-factor modal follow-up batch status:

- The `Add Qualitative Factor` category and label inputs now use `border-border-subtle bg-transparent shadow-none`, matching the already-aligned research-list create inputs.
- Suggestion/category buttons, flat modal footer actions, category/label state, create validation, create payload shape, and close behavior remain unchanged from the prior modal action batch.

Verification:

- Focused Diligence regression pack: `1 file / 11 tests passed`.
- Targeted ESLint for `AddFactorModal` and `DiligenceTab.test`: pass.
- Component coverage now asserts both modal inputs use `border-border-subtle bg-transparent shadow-none`, do not use `bg-background`, still receive seeded category/label values from `Competitive Moat`, and still submit the unchanged factor payload.
- In-app Browser smoke on `http://localhost:3000/?qa=add-factor-inputs-20260529#research/VALE/diligence`: the route hydrated to the locked VALE Diligence workspace, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live state did not expose the editable add-factor modal branch, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers Diligence add-factor modal input chrome. It does not alter factor creation semantics, suggestion content, Diligence lock/versioning behavior, report finalization, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 focused text-dialog input chrome alignment

Normal research text-dialog follow-up batch status:

- The `TextInputDialog` research variant now applies `border-border-subtle shadow-none` to its textbox while preserving the shared input sizing, focus treatment, value binding, and transparent fill.
- The default `TextInputDialog` path keeps the shared `border-input` textbox treatment, so reader-owned/default dialog usage remains unchanged.
- Focused-thread `Pin Finding`, Explore thread naming, and normal workspace thread naming continue to use the existing `chrome="research"` opt-in introduced by the prior dialog-border batch.
- Dialog open/close behavior, submit trimming, disabled-submit behavior, create-thread mutations, pin-finding mutations, document selection semantics, and reader-owned dialog usage are unchanged.

Verification:

- Focused dialog/thread regression pack: `2 files / 5 tests passed`.
- Targeted ESLint for `TextInputDialog`, `TextInputDialog.test`, and `ThreadTab.test`: pass.
- Component coverage now asserts default `TextInputDialog` keeps the shared `border-input` input and does not receive `border-border-subtle` or `shadow-none`, while `chrome="research"` applies the subtle/shadowless input treatment.
- Thread coverage now opens `Pin Finding` and asserts both the focused-thread dialog frame and textbox use the subtle research chrome while preserving the existing action path.
- In-app Browser smoke on `http://localhost:3000/?qa=text-dialog-input-20260529#research/MSFT/thread/15`: after the gateway preflight resolved, the focused-thread route rendered, opening `Pin Finding` produced a single dialog and single `Finding` textbox, the dialog had `border-border-subtle bg-background` without old `border-border`, the textbox had `border-border-subtle shadow-none`, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers normal research text-dialog input chrome. It does not alter `DocumentTab` dialog styling, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, create-thread semantics, pin-finding persistence, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 focused text-dialog action chrome alignment

Normal research text-dialog follow-up batch status:

- The `TextInputDialog` research variant now uses flat footer actions: muted transparent `Cancel` and primary-text transparent confirm.
- The default `TextInputDialog` path keeps the shared outline cancel and filled primary submit treatment, so reader-owned/default dialog usage remains unchanged.
- The action change is gated by the existing `chrome="research"` opt-in used by normal Explore thread naming, focused-thread `Pin Finding`, and normal workspace thread naming.
- Dialog open/close behavior, submit trimming, disabled-submit behavior, create-thread mutations, pin-finding mutations, document selection semantics, and reader-owned dialog usage are unchanged.

Verification:

- Focused dialog/thread regression pack: `2 files / 5 tests passed`.
- Targeted ESLint for `TextInputDialog`, `TextInputDialog.test`, and `ThreadTab.test`: pass.
- Component coverage now asserts default `TextInputDialog` keeps the outline cancel and filled primary submit treatment, while `chrome="research"` applies transparent borderless shadowless footer actions.
- Thread coverage opens `Pin Finding`, distinguishes the original trigger from the submit action, and asserts the modal submit action uses the flat research chrome.
- In-app Browser smoke on `http://localhost:3000/?qa=text-dialog-actions-20260529#research/MSFT/thread/15`: after the route resolved, opening `Pin Finding` preserved one trigger and one submit button, `Cancel` and submit computed transparent backgrounds, `0px` borders, and no box shadow, the dialog/input retained the prior subtle research chrome, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. Screenshot capture timed out on this pass, so DOM/computed-style/log evidence is the authoritative live evidence for this sub-batch.

Open follow-ups:

- This batch only covers normal research text-dialog footer action chrome. It does not alter `DocumentTab` dialog styling, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, create-thread semantics, pin-finding persistence, research persistence, or the mobile stack.

### 2026-05-29 Phase 1/rail composer state-action chrome alignment

Normal research composer follow-up batch status:

- Non-reader `MessageInput` Retry and Stop state actions now use flat transparent action chrome instead of the older outline-button treatment.
- `chrome="reader"` keeps the outline Retry/Stop buttons, preserving the document-reader analyst rail treatment.
- The existing default/embedded transparent composer shell, textarea treatment, send-button behavior, keyboard send behavior, retry callback, stop callback, disabled states, and error copy remain unchanged.

Verification:

- Focused composer regression pack: `1 file / 6 tests passed`.
- Targeted ESLint for `MessageInput` and `MessageInput.test`: pass.
- Component coverage now asserts non-reader Retry and Stop actions use `border-0 bg-transparent shadow-none`, and still call `onRetry` / `onStop`.
- Component coverage also asserts `chrome="reader"` keeps the existing outline `border-input bg-background` retry action while preserving the reader composer fill and send-button hover treatment.
- In-app Browser smoke on `http://localhost:3000/?qa=message-state-actions-20260529#research/MSFT`: the normal MSFT route rendered the research workspace, the embedded rail composer remained `border-t border-border-subtle bg-transparent p-2`, the textarea used `bg-transparent`, the send button kept `hover:bg-transparent`, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live route did not expose error/streaming state actions, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers non-reader `MessageInput` Retry/Stop state-action chrome. It does not alter message send semantics, retry/stop behavior, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 research-brief status badge token alignment

Research brief follow-up batch status:

- `ResearchBriefSection` incomplete and limited-data metadata badges now explicitly use `border-border-subtle bg-transparent text-[hsl(var(--text-dim))]` instead of relying on the generic outline badge treatment.
- The ready/pending/failed brief states, metadata conditions, badge labels, polling cadence, slot order, evidence rendering, and optional-endpoint hiding behavior are unchanged.

Verification:

- Focused research-brief regression pack: `1 file / 9 tests passed`.
- Targeted ESLint for `ResearchBriefSection` and `ResearchBriefSection.test`: pass.
- Component coverage now asserts both `incomplete` and `limited data` badges use subtle transparent badge chrome while preserving the same metadata-driven visibility.
- In-app Browser smoke on `http://localhost:3000/?qa=brief-status-badges-20260529#research/MSFT/report`: the report route hydrated to `Research Report v7`, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The current live MSFT report did not expose the `Editorial Brief` metadata badge branch, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers research-brief metadata badge chrome. It does not alter brief fetching/polling semantics, report artifact rendering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 2 compare metadata badge token alignment

Research-compare follow-up batch status:

- Compare-view direction and strategy metadata badges now explicitly use `border-border-subtle bg-transparent text-[hsl(var(--text-dim))]` instead of the generic outline badge treatment.
- Stage badges, conviction dots, latest-report summaries, decision-history rows, loading states, open/back actions, and compare data loading behavior are unchanged.

Verification:

- Focused compare regression pack: `1 file / 4 tests passed`.
- Targeted ESLint for `ResearchCompareView` and `ResearchCompareView.test`: pass.
- Component coverage now asserts the left compare card's `Long` and `Value` metadata badges use subtle transparent badge chrome while preserving the existing labels.
- In-app Browser smoke on `http://localhost:3000/?qa=compare-meta-badges-20260529#research/compare/88,87`: the comparison route rendered `Research Comparison`, preserved file open actions, exposed a live `Long` metadata badge with `border-border-subtle bg-transparent` and computed transparent background, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers compare-view direction/strategy metadata badge chrome. It does not alter compare route resolution, report artifact summaries, decision-history semantics, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report status badge token alignment

Report review follow-up batch status:

- Handoff/report status badges in the version rail and report header now explicitly use `border-border-subtle bg-transparent text-[hsl(var(--text-dim))]` instead of the generic outline badge treatment.
- Version selection, active-version marking, superseded report loading, new-version creation, report artifact rendering, decision-log filtering, and report status labels are unchanged.

Verification:

- Focused report review regression pack: `1 file / 10 tests passed`.
- Targeted ESLint for `HandoffReviewView` and `HandoffReviewView.test`: pass.
- Component coverage now asserts the report-header `finalized` badge and active version-rail `finalized` badge use subtle transparent badge chrome while preserving the same status text.
- In-app Browser smoke on `http://localhost:3000/?qa=report-status-badges-20260529#research/MSFT/report`: the report route rendered `Research Report`, visible `finalized` and `superseded` status badges used `border-border-subtle bg-transparent` with computed transparent background, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers report review status badge chrome. It does not alter handoff/version semantics, report artifact rendering, decision-history semantics, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 diligence completion badge fill alignment

Diligence section follow-up batch status:

- Diligence section `DRAFT` and `CONFIRMED` completion badges now use transparent fills while preserving their existing status colors through border/text color.
- The already-aligned `EMPTY` completion badge remains `border-border-subtle bg-transparent`.
- Section open/close behavior, section draft editing, save/confirm submit payloads, source refs, preview rendering, locked Diligence behavior, add-factor behavior, and qualitative-factor editing are unchanged.

Verification:

- Focused Diligence regression pack: `1 file / 11 tests passed`.
- Targeted ESLint for `DiligenceSectionHeader` and `DiligenceTab.test`: pass.
- Component coverage now asserts `DRAFT` uses `border-primary/30 bg-transparent text-primary` and no longer uses `bg-primary/10`; `CONFIRMED` uses `border-[hsl(var(--up))]/30 bg-transparent text-up` and no longer uses `bg-[hsl(var(--up))]/10`.
- In-app Browser smoke on `http://localhost:3000/?qa=diligence-completion-badges-20260529#research/MSFT/diligence`: after hydration, the route rendered the locked Diligence workspace, preserved `Create New Version`, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live route was locked and did not expose section completion badges, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers Diligence section completion badge fill chrome. It does not alter Diligence persistence semantics, lock/versioning behavior, report finalization, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 focused-thread pinned finding flat band

Focused thread follow-up batch status:

- The focused-thread pinned finding block now renders as a flat `border-y border-border-subtle bg-transparent` band instead of a rounded raised surface.
- The pinned finding copy, thread label, `Pin Finding` action, dialog open path, dialog chrome, input chrome, and submit/cancel controls are unchanged.

Verification:

- Focused thread regression pack: `1 file / 3 tests passed`.
- Targeted ESLint for `ThreadTab` and `ThreadTab.test`: pass.
- Component coverage now asserts the pinned finding uses `border-y border-border-subtle bg-transparent`, no longer uses `rounded-[4px]` or `bg-surface-raised`, and still opens the `Pin Finding` dialog with the aligned research dialog/input/action chrome.
- In-app Browser smoke on `http://localhost:3000/?qa=pinned-finding-flat-20260529#research/MSFT/thread/15`: the focused thread rendered `Valuation Deep Dive`, the pinned finding class was `mx-4 mt-4 border-y border-border-subtle bg-transparent px-4 py-3`, computed transparent background, `1px` top/bottom borders, and `0px` radius, the `Pin Finding` action remained visible, there was no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers focused-thread pinned-finding container chrome. It does not alter thread history loading, pinned finding persistence, dialog behavior, conversation rendering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 diligence pre-population notice fill alignment

Diligence transient-state follow-up batch status:

- The `Pre-populating sections in parallel and merging the draft once.` notice now uses a transparent fill while preserving its `border-primary/30` and `text-primary` status signal.
- Refresh disabled behavior, trigger-prepopulation mutation behavior, draft/header layout, section rendering, locked Diligence behavior, and report finalization behavior are unchanged.

Verification:

- Focused Diligence regression pack: `1 file / 11 tests passed`.
- Targeted ESLint for `DiligenceTab`, `DiligenceTab.test`, and `DiligenceSectionHeader`: pass.
- Component coverage now asserts the pre-population notice uses `border-y border-primary/30 bg-transparent text-primary`, no longer uses `bg-primary/10`, and the disabled Refreshing action still does not call the mutation.
- In-app Browser smoke on `http://localhost:3000/?qa=diligence-notice-flat-20260529#research/MSFT/diligence`: after gateway preflight resolved, the route rendered the locked Diligence workspace, preserved `Create New Version`, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live route was locked and did not expose the pre-population notice branch, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers Diligence pre-population notice fill chrome. It does not alter Diligence pre-population semantics, persistence, lock/versioning behavior, report finalization, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 5 report model status-band fill alignment

Report model-action follow-up batch status:

- `BuildModelButton` model build failure, annotation failure, and model/annotation success status bands now use transparent fills while preserving their down/primary/up border and text signals.
- Build-model, retry-build, retry-annotations, export JSON, model download, persisted model-ref download, and superseded-readonly behavior are unchanged.

Verification:

- Focused model-action regression pack: `1 file / 6 tests passed`.
- Targeted ESLint for `BuildModelButton` and `BuildModelButton.test`: pass.
- Component coverage now asserts the build-failure band uses `border-[hsl(var(--down))]/25 bg-transparent text-down`, the annotation-failure band uses `border-primary/25 bg-transparent text-primary`, and the success band uses `border-[hsl(var(--up))]/25 bg-transparent text-up`, while preserving retry/export/download callbacks and links.
- In-app Browser smoke on `http://localhost:3000/?qa=model-status-bands-20260529#research/MSFT/report`: the report route rendered `Research Report`, preserved `Build Model` and `Export JSON`, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live route had no active model error/success banner, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers report model-action status-band fill chrome. It does not alter model build/export/download semantics, handoff/version semantics, report artifact rendering, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 conversation user-note flat rail

Conversation feed follow-up batch status:

- Default `ConversationFeed` user notes now render as a flat annotation rail instead of a rounded raised note chip.
- The `Your Note` label, note body rendering, citations, inline feed actions, open-in-reader/start-thread actions, pending/error styling, workspace/thread feed chrome, and message ordering are unchanged.

Verification:

- Focused conversation feed regression pack: `1 file / 6 tests passed`.
- Targeted ESLint for `ConversationFeed` and `ConversationFeed.citations.test`: pass.
- Component coverage now asserts user notes use `border-l-2 border-[hsl(var(--text-dim))] text-foreground`, no longer use `rounded-[4px]` or `bg-surface-raised/35`, and still render the existing `Your Note` label and note body.
- In-app Browser smoke on `http://localhost:3000/?qa=conversation-note-flat-20260529#research/MSFT/thread/15`: after hydration, the focused-thread route rendered `Valuation Deep Dive`, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. The live seeded route did not expose a saved default user-note message, so component coverage is the direct branch evidence for this sub-batch.

Open follow-ups:

- This batch only covers default `ConversationFeed` user-note container chrome. It does not alter note persistence, message/citation semantics, thread history loading, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 focused text-dialog disabled action fill alignment

Normal research text-dialog follow-up batch status:

- The `TextInputDialog` research submit action now keeps the flat transparent disabled fill instead of also carrying the default dialog's `disabled:bg-muted` class.
- Default `TextInputDialog` submits keep the existing disabled muted-fill treatment, so reader-owned/default dialog usage remains unchanged.
- Disabled-submit gating, `aria-disabled`, submit trimming, dialog open/close behavior, focused-thread `Pin Finding`, normal workspace thread naming, and reader-owned dialog usage are unchanged.

Verification:

- Focused text-dialog regression pack: `1 file / 3 tests passed`.
- Targeted ESLint for `TextInputDialog` and `TextInputDialog.test`: pass.
- Component coverage now asserts an empty research dialog submit remains disabled, keeps `aria-disabled="true"`, uses `bg-transparent` / `disabled:bg-transparent`, no longer carries `disabled:bg-muted`, and still does not call `onConfirm` when clicked.
- In-app Browser automation was unavailable for this pass after the browser pipe went stale, so the live UI smoke used local Playwright fallback. Fallback smoke on `http://localhost:3000/?qa=text-dialog-disabled-flat-20260529#research/MSFT/thread/15` hydrated the focused MSFT thread, had no gateway unavailable state, no raw `long_term`, no horizontal overflow, and no browser warning/error logs. Opening `Pin Finding` non-mutatively showed the live research dialog with `border-border-subtle`, textbox `border-border-subtle shadow-none`, submit `bg-transparent disabled:bg-transparent`, and no `disabled:bg-muted`.

Open follow-ups:

- This batch only covers non-reader research text-dialog disabled submit fill chrome. It does not alter `DocumentTab` dialog styling, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, create-thread semantics, pin-finding persistence, research persistence, or the mobile stack.

### 2026-05-29 Phase 3 diligence disabled action fill alignment

Diligence action follow-up batch status:

- The shared Diligence flat action base now explicitly keeps disabled actions transparent, shadowless, and at normal opacity while retaining the dim disabled text signal.
- Add-factor create, modal cancel, section save/confirm, opening-take refresh, factor edit/remove, report-finalize, and create-new-version callbacks are unchanged because the update is class-only.

Verification:

- Focused Diligence regression pack: `1 file / 11 tests passed`.
- Targeted ESLint for `diligenceStyles` and `DiligenceTab.test`: pass.
- Component coverage now asserts the disabled `Add Factor` action remains disabled and uses `disabled:bg-transparent`, `disabled:text-[hsl(var(--text-dim))]`, `disabled:opacity-100`, and `disabled:shadow-none` while preserving the existing suggestion selection and create payload path.
- Rendered route QA was blocked by the current research gateway preflight: local Playwright saw `/api/research/content/preflight` return `504 Gateway Timeout` with `resolver timeout`, leaving the route on `Research gateway unavailable.` Direct gateway health on HTTPS port 8000 was up, so this needs rerun when the resolver/preflight path is healthy. No browser warning/error logs were emitted before the preflight failure.

Open follow-ups:

- This batch only covers shared non-reader Diligence flat-action disabled chrome. It does not alter Diligence persistence, add-factor creation semantics, section save/confirm behavior, report finalization behavior, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 workspace manual-thread disabled action coverage

Normal workspace dialog follow-up batch status:

- The normal workspace manual-thread flow now has integration coverage for the research dialog's transparent disabled submit state.
- The manual thread flow still requires an explicit name, still avoids calling `createResearchThread` while empty, still resets when canceled/reopened, and still submits the same payload once a name is entered.

Verification:

- Focused workspace regression: `ResearchWorkspacePhase3.test.tsx -t "requires an explicit name"` passed.
- Targeted ESLint for `ResearchWorkspacePhase3.test`, `TextInputDialog`, `TextInputDialog.test`, `diligenceStyles`, and `DiligenceTab.test`: pass.
- Focused disabled-action packs: `TextInputDialog.test.tsx` and `DiligenceTab.test.tsx` passed (`2 files / 14 tests passed`).
- Rendered local Playwright smoke on `http://localhost:3000/?qa=manual-thread-disabled-live-20260529#research/MSFT`: the route passed gateway preflight, opened the manual `Name Thread` dialog, the empty `Create Thread` action was disabled with `disabled:bg-transparent` and no `disabled:bg-muted`, the textbox stayed empty, cancel closed the dialog without submitting, there was no raw `long_term`, no horizontal overflow, and no browser warning/error logs.

Open follow-ups:

- This batch only covers normal workspace manual-thread disabled action coverage for the already-aligned research dialog. It does not alter thread creation semantics, reader-owned `TextInputDialog` usage, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1/3/5 metric change-badge flat chrome

Research metric-strip follow-up batch status:

- `MetricStrip` now routes optional `item.change` badge chrome through the existing `chrome` variant.
- Default metric strips keep the filled `border-primary/25 bg-primary/10 text-primary` change badge.
- Flat research metric strips now render change badges as transparent hairline metadata with `border-border-subtle bg-transparent text-[hsl(var(--text-dim))]`.
- Metric values, metric labels, citations promoted into metric values, report artifact parsing, Diligence factor editing, and default non-research metric-strip consumers are unchanged.

Verification:

- Focused design/research regression pack: `MetricStrip.test.tsx`, `ResearchMessageContent.test.tsx`, and `HandoffSectionRenderer.test.tsx` passed (`3 files / 46 tests passed`).
- Targeted ESLint for `MetricStrip`, `MetricStrip.test`, `ResearchMessageContent`, and `HandoffSectionRenderer`: pass.
- Component coverage now asserts default change badges keep the filled primary treatment and flat change badges use transparent hairline metadata treatment with no `bg-primary/10`.
- Local Playwright smoke on `http://localhost:3000/?qa=metric-strip-flat-badge-20260529#research/MSFT/report`: dev login succeeded, the report route rendered a flat metric strip (`border-border-subtle bg-transparent`), had no sign-out or portfolio failure state, and emitted no browser console/page errors. The live seeded report did not include an `item.change` badge, so the optional badge branch is covered directly by component regression.

Open follow-ups:

- This batch only covers optional change-badge chrome in `MetricStrip` flat mode. It does not alter metric extraction, report artifact semantics, shared default metric-strip chrome, document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, research persistence, or the mobile stack.

### 2026-05-29 Phase 1 reduced research shell chrome

Normal research shell follow-up batch status:

- Desktop research routes now use a reduced-global-chrome shell that suppresses the portfolio ticker row and keeps the workspace at the top of the viewport.
- `AppSidebar` now has a compact chrome mode used by research routes: the wide Hank wordmark, group labels, and text labels collapse to a 64px icon rail while preserving every navigation button, settings, sign-out, aria label, title, and shortcut affordance.
- Non-research routes keep the existing dashboard shell, including the market ticker and 180px desktop sidebar.
- Mobile research routes keep the existing mobile header/nav path rather than introducing a new mobile shell.
- Research workspace content, tab routing, report rendering, exit ramps, persistence, and reader-owned document mode are unchanged.

Verification:

- Focused sidebar regression pack: `AppSidebar.test.tsx` passed (`1 file / 4 tests passed`).
- Targeted ESLint for `ModernDashboardApp`, `AppSidebar`, and `AppSidebar.test`: pass.
- Component coverage now asserts compact research chrome keeps icon-button navigation and sign-out callable while removing wide text labels.
- Local Playwright smoke on `http://localhost:3000/?qa=research-compact-shell-20260529#research/MSFT/report`: dev login succeeded, the report route rendered with no market ticker, a 64px sidebar, main content starting at x=64, no sign-out or portfolio failure state, and no browser console/page errors. Control route `#score` still rendered the market ticker and a 180px sidebar.

Open follow-ups:

- This batch implements reduced global chrome for the existing dashboard-hosted research route. It does not create a fully standalone research app shell, remove global navigation, alter ticker behavior on non-research routes, change research persistence, or touch document-reader route handling, filing/source HTML rendering, SourceHtmlPane, F122, F156, or the mobile stack.

### 2026-05-29 Current non-reader component audit

Post reduced-shell audit status:

- A visual-token scan after the reduced-shell batch found no new safe non-reader research component polish target.
- Remaining old-card/fill token hits fall into expected buckets:
  - shared default component variants that intentionally preserve non-research behavior (`DataTable` default frame and `MetricStrip` default chrome)
  - global shell affordances in the compact icon rail and app loading/error/mobile header paths
  - reader/document-owned files under the F156 boundary (`DocumentTab`, `SourceHtmlPane`, `FilingSection`, `TranscriptSection`, `AnnotationPopover`, reader variants in `ResearchWorkspace`, `ResearchTabBar`, `AgentPanel`, and `MessageInput`)
  - intentional modal or preview-matching surfaces (`AddFactorModal`, `TextInputDialog` default, and the raised research-list briefing band)
  - tests that assert previous flat research variants do not regress to old filled/card treatments
- `docs/TODO.md` now routes the two remaining broad design items away from normal component polish: dedicated research shell mode is `REDUCED CHROME SHIPPED 2026-05-29 - FULL STANDALONE SHELL DEFERRED`, and report typed-output convergence is `COMPONENT FLAT PASS SHIPPED 2026-05-29 - F122 CONVERGENCE STILL SEPARATE`.

Verification:

- Current worktree scan used `rg` across `frontend/packages/ui/src/components/research`, `MetricStrip`, `DataTable`, `ModernDashboardApp`, and `AppSidebar` for old rounded/card/fill tokens.
- `git status --short` showed no tracked changes before this audit note; the only untracked file remained `docs/TODO 2.md`, intentionally left untouched.

Open follow-ups:

- Further visual alignment work should start from a specific new preview mismatch, F156 reader coordination item, F122 shared-renderer convergence task, or product decision for a fully standalone research app shell. Do not reopen already-classified default/shared/reader-token hits as opportunistic component polish.

### 2026-05-29 Non-reader alignment completion audit

Objective requirements audited:

- Resume the crashed research-surface design alignment work.
- Align the non-reader research surfaces toward the preview: research list, normal workspace shell, Explore/thread, Diligence, report/handoff, compare, exit ramps, tab/context treatment, inline metrics, and tables.
- Preserve existing functionality while changing visual hierarchy.
- Keep F156 reader-owned implementation separate and avoid duplicating the filing-reader architecture.
- Coordinate F122/report renderer convergence as a separate shared-renderer track instead of replacing report semantics ad hoc.
- Produce small verified batches with committed tracking evidence.

Current evidence:

- Commit history contains the small verified batches for list, shell, tabs, rail/composer, conversation/thread notes, Diligence, report/handoff, compare, typed report renderers, metric strips, reduced global shell chrome, TODO status, and residual audit checkpoints.
- `docs/TODO.md` routes the two broad leftovers away from normal component polish: `Research workspace dedicated shell mode` is `REDUCED CHROME SHIPPED 2026-05-29 - FULL STANDALONE SHELL DEFERRED`; `Research report typed-output renderer convergence` is `COMPONENT FLAT PASS SHIPPED 2026-05-29 - F122 CONVERGENCE STILL SEPARATE`.
- Broad component regression: `pnpm --dir frontend exec vitest run packages/ui/src/components/research packages/ui/src/components/dashboard/__tests__/AppSidebar.test.tsx packages/ui/src/components/design/MetricStrip.test.tsx` passed (`25 files / 287 tests passed`). The run includes reader tests, which still emit existing happy-dom iframe/fetch stderr from `SourceHtmlPane`, but all tests passed.
- Non-reader targeted ESLint passed for `ModernDashboardApp`, `AppSidebar`, non-reader research components/tests, `MetricStrip`, and `DataTable`.
- Frontend typecheck passed with `pnpm --dir frontend exec tsc --noEmit --pretty false`.
- Live local Playwright matrix on `http://localhost:3000/?qa=research-final-matrix-20260529` passed for `#research`, `#research/MSFT`, `#research/MSFT/thread/15`, `#research/MSFT/diligence`, `#research/MSFT/report`, and `#research/compare/1,88`: dev login succeeded, no sign-out or portfolio failure state, no research gateway unavailable state, no market ticker on research routes, 64px sidebar, main content at x=64, no horizontal overflow, no raw `long_term`, and no browser console/page errors.
- A full-directory ESLint attempt over `packages/ui/src/components/research` still reports one existing reader-owned warning in `SourceHtmlPane.test.tsx` (`@typescript-eslint/no-empty-function`). That is outside this non-reader pass and remains in the F156 reader-owned lane.

Conclusion:

- The non-reader research surface alignment pass is complete to the evidence standard for this objective: current code preserves shipped functionality through regression coverage and live smoke checks, while remaining visual-token hits are classified as shared defaults, intentional surfaces, tests, or F156/F122/deferred ownership.
- Remaining work is outside this objective's non-reader alignment scope unless a new concrete preview mismatch is found: F156 filing-reader polish/mapping, F122 Workbench/shared-renderer convergence, and any future fully standalone research app shell decision.
