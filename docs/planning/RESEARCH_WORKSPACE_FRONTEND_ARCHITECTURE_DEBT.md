# Research Workspace Frontend Architecture Debt

**Status:** Implementation pass complete; low-priority route typing follow-up remains
**Date:** 2026-05-30
**Owner:** Research Workspace / Frontend Architecture
**TODO:** `docs/TODO.md` > Design Backlog > Research workspace frontend architecture debt
**Related:**
- `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md`
- `docs/planning/F156_RESEARCH_WORKSPACE_COMPLETION_PLAN.md`
- `docs/architecture/FRONTEND_ARCHITECTURE.md`

## Summary

The recent research workspace UI mostly follows the frontend package architecture:

- `@risk/app-platform` owns app bootstrap and provider composition.
- `@risk/chassis` owns app contracts and shared service wiring.
- `@risk/connectors` owns API hooks, React Query integration, gateway streaming helpers, stores, and route synchronization.
- `@risk/ui` owns visual components and user interaction surfaces.

The research workspace enters through `ModernDashboardApp`, delegates to `ResearchWorkspaceContainer`, and uses connector-owned hooks and Zustand stores for most data and state. That is the right general direction.

The remaining issues are architectural debt, not an emergency rewrite. The debt concentrates in reader/source entry points where UI components still own orchestration, parsing, or schema normalization that should live in connectors or typed adapters. Cleaning these boundaries up will make the workspace easier to test, less fragile under route changes, and more consistent with the rest of the frontend.

## Implementation Update

The implementation pass has addressed the primary boundary issues identified in this review:

- `@risk/connectors` now owns research document/source open orchestration, source inventory and source-ref normalization, source-html identity verification, and compare artifact view-model normalization.
- Research hash parsing now has a store-free parser consumed by hash sync and UI store initialization.
- `ResearchWorkspace` no longer uses module-scoped mutable artifact-source intent state.
- Focused Vitest coverage and `pnpm typecheck` pass for the changed research workspace paths.
- Adversarial subagent review passed after fixes for source HTML cover-page defaults, missing API handling in `useOpenResearchDocument`, and connector-level source HTML verification coverage.

The only remaining follow-up from review is non-blocking: consolidate research route id/type constants so `hashParser.ts` and UI store route typing cannot drift.

## Current Shape

- Route entry: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` lazy-loads and renders the research container.
- Container: `frontend/packages/ui/src/components/research/ResearchWorkspaceContainer.tsx` handles research route mode, tier gating, gateway preflight, file/bootstrap routing, and reader document open requests.
- Data and store layer: `@risk/connectors` owns `researchStore`, `useResearchFiles`, `useResearchBootstrap`, `useDiligenceState`, `useResearchChat`, and related research API hooks.
- Streaming: `ResearchStreamProvider` plus `useResearchChat` own gateway streaming, optimistic messages, server reconciliation, and active thread context.
- UI: `@risk/ui` renders the workspace, tabs, reader, source inventory, handoff/report surfaces, and compare view.
- Current debt: source inventory derivation, document/source open orchestration, some source-html verification, and some artifact normalization still live in UI files.

This split is close to the intended frontend architecture. The follow-up below should preserve the package boundaries and move a few remaining responsibilities to the right layer.

## Findings And Recommendations

### 1. Research document/source open orchestration is spread across UI entry points

**Severity:** Medium

**Evidence:**
- `frontend/packages/ui/src/components/research/ResearchWorkspace.tsx` imports connector service primitives directly: `useAPIService`, `getDocument`, and `ingestDocument` near lines 4-12. Its source inventory open path performs path ingest, document fetch, store mutation, and selection cleanup in one UI callback near lines 622-646.
- `frontend/packages/ui/src/components/research/ConversationFeed.tsx` imports the same primitives near lines 3-11, then opens reader tool-call sources directly in `handleOpenInReader()` near lines 112-134.
- `frontend/packages/ui/src/components/research/DiligenceTab.tsx` uses `useAPIService`, `getDocument`, and `ingestDocument` to open document sections from diligence jump links near lines 239 and 314-360.
- `frontend/packages/ui/src/components/research/ResearchWorkspaceContainer.tsx` bridges direct reader route query data into `researchStore.openDocumentTab()` near lines 282-287.

**Why it matters:**
- Several UI components own API orchestration instead of rendering and invoking connector operations.
- Error handling and retry state are hard to make consistent.
- React Query cache invalidation and optimistic updates are easy to miss.
- Future source types will add more data-path branching across multiple UI files.
- Direct reader routes, tool-call links, diligence links, and source inventory links can drift from each other.

**Recommendation:**
Create a connector-owned document/source open operation, likely `useOpenResearchDocument`, that owns the document lookup/ingest/open sequence for every UI entry point.

The hook must accept a connector-owned request type, not the UI-owned `ResearchSourceInventoryItem` currently declared in `ResearchSourceInventory.tsx`:

```ts
type ResearchDocumentOpenRequest =
  | {
      sourceType: 'transcript';
      sourceId: string;
      section?: string | null;
      key?: string | null;
    }
  | {
      sourceType: 'filing';
      sourceId?: string | null;
      sourcePath?: string | null;
      section?: string | null;
      key?: string | null;
    };

type OpenResearchDocumentResult = {
  openDocument: (request: ResearchDocumentOpenRequest) => Promise<void>;
  isOpeningSource: boolean;
  openingSourceKey: string | null;
  error: Error | null;
  resetError: () => void;
};
```

The connector should own:
- API service access.
- `getDocument` and `ingestDocument` sequencing.
- section selection for document-section opens.
- query cache update or invalidation for affected document/source data.
- `researchStore.openDocumentTab` or equivalent state mutation.
- typed error mapping for user-facing retry.

The UI should own:
- invoking `openDocument(request)`.
- showing loading, disabled, error, and retry states.
- maintaining visual selection behavior.

**Acceptance criteria:**
- `ResearchWorkspace.tsx`, `ConversationFeed.tsx`, and `DiligenceTab.tsx` no longer import `useAPIService`, `getDocument`, or `ingestDocument` for document/source open paths.
- The direct reader route hydration in `ResearchWorkspaceContainer.tsx` goes through a connector-owned route hydration helper/hook or has explicit tests proving it stays aligned with the shared open operation.
- The shared operation accepts a connector-owned descriptor/request type, not a UI-owned component type.
- Source-open failures render a retryable state instead of disappearing into an async callback.
- Tests cover existing-document open, path-ingest open, section open, direct reader route hydration, and ingest/fetch failure.

### 2. Source inventory schema normalization lives in UI

**Severity:** Medium/Low

**Evidence:**
- `frontend/packages/ui/src/components/research/ResearchSourceInventory.tsx` declares `ResearchSourceInventoryItem` near line 22.
- The same file recursively parses raw diligence `source_refs` in `collectSourceRefs()` near line 206.
- `buildResearchSourceInventory()` builds a derived source view model from open document tabs, messages, tool calls, citation context, diligence, and reader artifacts near line 343.
- `frontend/packages/ui/src/components/research/DiligenceTab.tsx` also recursively parses raw source refs near lines 96 and 369 to create jump links.

**Why it matters:**
- The inventory component is doing connector/adapter-shaped work instead of rendering already-normalized source data.
- The open operation proposed above needs a connector-owned source/document descriptor. Keeping the descriptor in UI would invert the package dependency.
- Diligence/source-ref parsing can drift between source inventory and diligence jump links.

**Recommendation:**
Move source inventory derivation and source-ref normalization into connectors, for example under a research-source adapter or hook. Export a connector-owned `ResearchSourceDescriptor` or `ResearchSourceInventoryItem` type from `@risk/connectors`; the UI component should render those items and emit descriptor-based open requests.

Keep visual labeling and grouping presentation in UI only if it is purely display-level. Keep raw schema traversal, source-type normalization, citation/tool-call merging, and artifact/diligence source extraction in connectors.

**Acceptance criteria:**
- `ResearchSourceInventory.tsx` receives normalized source items instead of traversing messages, diligence, and artifacts itself.
- `DiligenceTab.tsx` uses a shared connector source-ref utility or typed jump-link adapter instead of maintaining a separate recursive parser.
- The shared source descriptor can be passed to the connector document-open operation without importing from `@risk/ui`.
- Adapter tests cover open tabs, tool calls, citation context, diligence `source_refs`, reader artifacts, malformed source refs, and duplicate sources.

### 3. Research hash parsing has duplicated responsibility and needs a pure parser

**Severity:** Medium/Low

**Evidence:**
- `frontend/packages/connectors/src/navigation/hashSync.ts` imports `useUIStore` from `uiStore.ts` near lines 1-7, so `uiStore.ts` must not import `hashSync.ts` directly.
- `frontend/packages/connectors/src/navigation/hashSync.ts` builds and parses research reader routes with `readerSourceType` and `readerSourceId` near lines 136-143 and 196-203.
- `frontend/packages/connectors/src/stores/uiStore.ts` initializes navigation context with its own parser in `getStoredNavigationContext()` near line 170.
- `setInitialHash()` and runtime hash sync later correct state, but initial store hydration and hash parsing are not using one canonical parser.

**Why it matters:**
- Reader routes can drift from initial navigation context if only one parser is updated.
- Route bugs become timing-dependent because later hash sync can hide initial hydration differences.
- Adding more research route variants will require edits in more than one place.

**Recommendation:**
Extract a pure parser module, for example `frontend/packages/connectors/src/navigation/hashParser.ts`, with no Zustand/store imports. Both `hashSync.ts` and `uiStore.ts` should consume that pure helper.

Do not make `uiStore.ts` import `hashSync.ts`; that would create a `uiStore -> hashSync -> uiStore` cycle because `hashSync.ts` already imports `useUIStore`.

**Acceptance criteria:**
- There is one canonical parser for `#research/...` hash context.
- `uiStore` initialization recognizes reader routes through that parser.
- The pure parser has no import from `stores/uiStore.ts` or any React/Zustand runtime module.
- Hash sync tests cover initial hydration for list, workspace, compare, report, diligence, and reader routes.

### 4. SourceHtmlPane performs direct service calls for metadata verification

**Severity:** Medium/Low

**Evidence:**
- `frontend/packages/ui/src/components/research/SourceHtmlPane.tsx` imports `useAPIService` near lines 4-11.
- The component calls `api.request<SourceHtmlMaterializedIdentityWire>()` for materialized identity verification near lines 987-1007.

**Why it matters:**
- This is another direct service call from `@risk/ui`, which conflicts with the presentation-layer rule.
- Source-html rendering, iframe interaction, and selection projection are already complex; metadata verification should not add API orchestration to the same component.

**Recommendation:**
Move source-html materialized identity verification into a connector hook or adapter, for example `useSourceHtmlIdentityVerification`. The hook should own API access, wire response validation, and error normalization. `SourceHtmlPane` should keep iframe/rendering/selection responsibilities and render the verification state returned by the hook.

**Acceptance criteria:**
- `SourceHtmlPane.tsx` no longer imports `useAPIService` or calls `api.request` directly.
- Connector tests cover valid metadata, URL missing/invalid, validation mismatch, API failure, and cancellation/unmount behavior.
- Existing `SourceHtmlPane` tests continue to cover visual/rendering behavior without mocking a raw API service.

### 5. Artifact-source intent is stored in module-scoped mutable state

**Severity:** Low

**Evidence:**
- `frontend/packages/ui/src/components/research/ResearchWorkspace.tsx` declares `pendingArtifactSourceIntent` as a module-level mutable variable near line 192.
- The component reads and resets that variable across route and reader lifecycle paths near lines 324-345 and 616-645.

**Why it matters:**
- The variable is outside React lifecycle and outside the connector store.
- It can survive unmounts, hot reloads, or future multi-workspace rendering.
- The current file-id guards reduce risk, but the ownership model is still fragile.

**Recommendation:**
Move pending artifact-source intent into a scoped lifecycle:

- Preferred: add a small field and actions to `researchStore` so this state is reset with file/workspace state.
- Acceptable narrow fix: use a component-scoped `useRef` plus explicit reset on file change and unmount.

Use the store option if this intent needs to coordinate with route or reader state outside `ResearchWorkspace`.

**Acceptance criteria:**
- No module-scoped mutable pending intent remains in `ResearchWorkspace.tsx`.
- Intent resets are covered for file change, source mismatch, and completed open.
- Reader-source route tests still pass.

### 6. Compare view parses raw handoff artifact shape in UI

**Severity:** Low

**Evidence:**
- `frontend/packages/ui/src/components/research/ResearchCompareView.tsx` imports `ResearchHandoff` and manually normalizes `handoff.artifact` with `Record<string, unknown>` helpers near lines 30-87.

**Why it matters:**
- The UI component is coupled to raw artifact schema details.
- Changes to the handoff artifact shape require edits in visual components.
- Other surfaces may duplicate the same normalization logic later.

**Recommendation:**
Move artifact normalization into a typed connector adapter, for example:

```ts
type ResearchCompareViewModel = {
  status: string;
  generatedAt: string | null;
  recommendation: string | null;
  thesisSummary: string | null;
  keyRisks: string[];
};
```

The compare view should consume a typed view model rather than inspect raw artifact records.

**Acceptance criteria:**
- `ResearchCompareView.tsx` does not parse `Record<string, unknown>` artifact data directly.
- Adapter tests cover missing artifact, malformed sections, and expected populated sections.
- The adapter can be reused by report/compare surfaces if those surfaces converge later.

### 7. Large UI modules make boundaries harder to enforce

**Severity:** Low / maintainability

**Evidence:**
- `ResearchWorkspace.tsx` is about 1,437 lines.
- `DocumentTab.tsx` is about 1,025 lines.
- `SourceHtmlPane.tsx` is about 1,216 lines.

**Why it matters:**
- Large components make ownership drift harder to see.
- Data orchestration, layout, keyboard handling, and reader behavior become entangled.
- Small feature changes become risky because tests need to cover many behaviors in one file.

**Recommendation:**
Do not start with a broad rewrite. Instead, decompose opportunistically around the debt above:

- Extract source inventory normalization and source-open orchestration to connectors first.
- Extract reader intent state from `ResearchWorkspace`.
- Move compare artifact normalization to a connector adapter.
- When touching the reader again, split `DocumentTab` and `SourceHtmlPane` into focused hooks/components for viewport state, source text rendering, source-html verification, note/annotation actions, and toolbar controls.

**Acceptance criteria:**
- New code follows the connectors/hooks/store-first architecture.
- Component extraction happens only when it reduces live complexity or enables better tests.
- The public research workspace behavior remains unchanged.

## Suggested Implementation Order

1. Extract a pure hash parser module and add initial hydration coverage for reader routes.
2. Move source inventory/source-ref normalization into connectors and export a connector-owned source descriptor.
3. Add a connector-owned document/source open operation and migrate `ResearchWorkspace`, `ConversationFeed`, `DiligenceTab`, and direct reader route hydration to it.
4. Move source-html materialized identity verification into a connector hook.
5. Move pending artifact-source intent into `researchStore` or a scoped component ref.
6. Add a typed compare view-model adapter for research handoff artifacts.
7. Decompose the largest reader/workspace components only as nearby work creates a clear extraction point.

## Non-goals

- No visual redesign.
- No backend API rewrite.
- No change to the research artifact contract.
- No removal of current reader, source inventory, diligence, or compare functionality.
- No broad package reorganization beyond moving ownership to existing connector/store layers.

## Verification Plan

Run targeted frontend checks from `frontend/`:

```bash
pnpm test -- --run \
  packages/connectors/src/navigation/__tests__/hashSync.test.ts \
  packages/connectors/src/stores/researchStore.test.ts \
  packages/ui/src/components/research/ResearchWorkspaceContainer.test.tsx \
  packages/ui/src/components/research/ResearchSourceInventory.test.tsx \
  packages/ui/src/components/research/ConversationFeed.citations.test.tsx \
  packages/ui/src/components/research/DiligenceTab.test.tsx \
  packages/ui/src/components/research/SourceHtmlPane.test.tsx \
  packages/ui/src/components/research/ResearchWorkspacePhase2.test.tsx \
  packages/ui/src/components/research/ResearchWorkspacePhase3.test.tsx
```

Add or update focused tests for:
- pure hash parser coverage and reader route initial hydration.
- source inventory normalization from open tabs, messages, citations, diligence refs, and reader artifacts.
- source-open success and failure states across source inventory links, tool-call links, diligence jump links, and direct reader routes.
- source-html identity verification success and failure states.
- pending artifact-source intent reset behavior.
- compare artifact view-model normalization.

Run package-wide typecheck before merging:

```bash
pnpm typecheck
```

If the broad Vitest suite is run, note that the architectural review observed an unrelated generated-artifact rendering test failure where the expected accessible button name did not match the current aria-label.

## Open Questions

- Should source opening be a general document operation in connectors or a research-source-specific hook fed by a source inventory descriptor?
- Should direct reader route opening use the same document-open hook or a narrower route hydration helper with the same underlying implementation?
- Should source-html metadata verification live with document hooks or in a dedicated source-html connector hook?
- Should the compare view-model adapter become part of a broader typed handoff artifact presenter shared with report rendering?
