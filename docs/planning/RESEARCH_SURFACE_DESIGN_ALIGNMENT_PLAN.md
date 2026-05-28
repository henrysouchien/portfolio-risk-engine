# Research Surface Design Alignment Plan

**Status:** Draft for design review
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

- Research-specific preview: `~/.gstack/projects/henrysouchien-risk_module/designs/research-workspace-20260403/research-workspace-preview.html`
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
| Thread | Focused thread timeline, notes, pinned finding, related evidence | Thread summary, pressure-test prompt, related threads, message input | Compact recent context only; must not duplicate full main timeline | Active thread or panel thread by explicit policy | Thread notes/messages persist through research API |
| Document / filing | Human-readable source/document surface | Active document identity, selected-text prompt, ask/save/branch actions, agent sidecar | No full competing feed by default; sidecar may show compact assistant context | Panel thread with document context | Visible-source anchors follow F156; corpus offsets only when mapping allows |
| Diligence | Checklist/draft sections and source refs | Progress scan, missing sections, refresh/opening-take prompts, report action | No full feed by default | Panel thread with diligence context | Section state persists through diligence API |
| Handoff/report | Frozen report, evidence, source chips, version being reviewed | Version/status context, build-model action, new-version action, decision-log shortcuts | No full feed by default | Panel thread with report context | Report artifact remains immutable for finalized versions |
| Compare | Comparison table/narrative | Compare framing, differences to resolve, next-action prompts | No full feed by default | Panel thread with compare context | Compare selection stays client/session state unless saved elsewhere |

If an implementation keeps `AgentPanel`'s internal `ConversationFeed`, it must visually demote it when the main pane is also conversation-like and prove the two surfaces have distinct labels, density, and purpose. For Explore and Thread, Phase 1 acceptance is stricter: the rail is annotations/context-first, with file context, workspace scan, selected prompt, pinned or related findings, and compact recent context only. A full timestamped conversation feed at equal visual weight does not pass.

Implementation note: "compact recent context" means a short contextual excerpt or summary, not a shortened full chat transcript with the same timestamp/author rhythm as the main pane.

Default thread input policy for Phase 1: the rail input writes to the panel thread and includes the active thread id/context when the active artifact is a thread. It does not directly append to the active thread timeline unless the user is in an explicit "reply in this thread" affordance. This preserves the main thread as the focused artifact while keeping the analyst rail contextual.

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
