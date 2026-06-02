# Agent Control Artifact Render Bridge Plan

**Date:** 2026-06-01  
**Status:** Draft bridge plan for review  
**Owner:** Henry  
**Primary surface:** `/analyst` chat route, via `AgentControlDeck` + `ArtifactPanelConnected`

## 1. Purpose

The agent-control product spec now treats the existing artifact panel as the **human artifact render lane** for run and skill outputs. This plan defines the missing architecture bridge between a control-plane artifact reference and the reviewable visual shown to the analyst.

The bridge exists because there are two different artifact concepts:

- **Machine artifact:** typed contract, sidecar, schema payload, file path, or binary output used by agents and workflow stages.
- **Human artifact render:** visual view-model derived from the machine artifact for analyst review, approval evidence, reuse, and later report inclusion.

The current `/analyst` artifact panel only accepts a block-oriented `ArtifactSpec` and renders it through `BriefingRenderer`. That is useful as a fallback, but it is not enough for contract-backed visuals, F122 HTML artifacts, F147 curated renderers, or future presentation packs.

## 2. Current State

Relevant shipped pieces:

- `frontend/packages/chassis/src/types/index.ts`
  - `ArtifactSpec = { id?, title, blocks }`
  - No `contract_name`, artifact path, binary path, source metadata, export handles, or renderer discriminator.
- `frontend/packages/ui/src/components/chat/ArtifactPanel.tsx`
  - Always renders `artifact.blocks` via `BriefingRenderer`.
- `frontend/packages/ui/src/components/chat/ArtifactPanelConnected.tsx`
  - Reads `currentArtifact` from shared chat state and passes it directly to `ArtifactPanel`.
- `frontend/packages/ui/src/components/agent-control/AgentControlDeck.tsx`
  - Converts `ControlArtifact` into a synthetic metadata-only `ArtifactSpec` via `buildArtifactSpec(...)`, then opens the panel.
- `frontend/packages/chassis/src/services/ControlGatewayTypes.ts`
  - `ControlArtifact` carries fields like `artifact_id`, `run_id`, `skill_run_id`, `contract_name`, `artifact_path`, `binary_artifact_path`, `data_source`, and `url`.

Related plans:

- `docs/planning/AGENT_CONTROL_SURFACE_DESIGN_PLAN.md`
  - Product direction: artifact panel is the human artifact render lane.
- `docs/planning/F122_HTML_ARTIFACT_RENDERER_SPEC.md`
  - Shared HTML artifact infra and analyst-view delta-spec path.
- `docs/planning/F122_HTML_ARTIFACT_RENDERER_IMPL_PLAN.md`
  - Research-workspace implementation plan; shared infra lands there first; analyst-view integration is parked.
- `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md`
  - Curated React registry direction for stable recurring artifact types.
- `docs/planning/VISUAL_STACK_EXECUTION_PLAN.md`
  - Sequencing authority for F122, F147, F148, and related visual work.

## 3. Goal

Introduce a small resolver layer so `/analyst` can open a control-plane artifact reference and render the right human-facing visual in `ArtifactPanelConnected`.

The bridge should:

1. Preserve control-plane artifact identity and provenance.
2. Route known artifact contracts to the right renderer family.
3. Keep the control deck as an index/control lane, not a full renderer.
4. Keep the main chat thread as the run/output lane.
5. Let F122, F147, and F148 integrate without redefining `/analyst` artifact behavior later.

## 4. Non-Goals

- Do not implement F122 HTML renderer internals here. Consume F122 shared primitives when they land.
- Do not implement F147 thesis renderer entries here. Consume F147 registry lookup/dispatch when available.
- Do not redesign `ArtifactPanel` visuals in this bridge plan beyond the minimum shell and routing requirements.
- Do not move artifact rendering into the control deck.
- Do not store screenshots as report artifacts. Future packs should consume stable artifact refs and render contracts.

## 5. Proposed Types

### 5.1 `ArtifactRenderRef`

This is the object opened by `AgentControlDeck`, selected-run thread artifact chips, and approval evidence actions.

```ts
export type ArtifactRenderSource = 'control-plane' | 'chat-artifact' | 'research-workspace';

export interface ArtifactRenderRef {
  source: ArtifactRenderSource;
  artifactId: string;
  title?: string | null;
  runId?: string | null;
  skillRunId?: string | null;
  contractName?: string | null;
  skill?: string | null;
  ticker?: string | null;
  dataSource?: string | null;
  artifactPath?: string | null;
  binaryArtifactPath?: string | null;
  url?: string | null;
  createdAt?: string | null;
  sourcePayload?: unknown;
}
```

Rules:

- `artifactId` is required and stable.
- `contractName` is the primary routing discriminator when present.
- `sourcePayload` is optional escape-hatch metadata for fallback display only; renderers should prefer typed fetches/contracts.
- Conversion from `ControlArtifact` to `ArtifactRenderRef` should live in one helper, not inside deck JSX.

### 5.2 `ArtifactRenderResult`

The resolver returns one of several renderable states.

```ts
export type ArtifactRenderResult =
  | { kind: 'legacy-blocks'; artifact: ArtifactSpec }
  | { kind: 'html-artifact'; artifactId: string }
  | { kind: 'curated-registry'; descriptorId: string; artifactId: string; ref: ArtifactRenderRef }
  | { kind: 'binary'; ref: ArtifactRenderRef }
  | { kind: 'metadata-fallback'; ref: ArtifactRenderRef; reason: string }
  | { kind: 'loading'; ref: ArtifactRenderRef }
  | { kind: 'error'; ref: ArtifactRenderRef; message: string };
```

Rules:

- `metadata-fallback` is allowed only as an explicit fallback state.
- Unknown contract names must render a clear fallback, not silently masquerade as a complete visual.
- Loading and error states belong in the panel, not the deck.

## 6. Resolver Routing

Add an `ArtifactRenderResolver` module used by `ArtifactPanelConnected`.

Routing priority:

1. **Legacy block artifacts**
   - Existing `:::artifact` chat output keeps working.
   - Existing `ArtifactSpec` values can still open directly.
   - Route to `legacy-blocks`.

2. **F122 `HtmlArtifact`**
   - `contractName === "HtmlArtifact"` routes to `html-artifact`.
   - `ArtifactPanelConnected` uses F122 shared primitives once available:
     - `useHtmlArtifact(artifactId)`
     - `HtmlArtifactRenderer`
     - `buildSandboxedDocument`
     - `StaticExportsBar`
   - Until F122 shared infra exists, render `metadata-fallback` with a clear "HTML renderer unavailable" state.

3. **F147 / curated registry contracts**
   - Stable recurring contracts route to `curated-registry`.
   - The bridge should call the central registry lookup once F147 exposes it.
   - Expected match inputs:
     - `contractName`
     - namespace/id when present
     - `skill`
     - `artifactPath` sidecar fields after fetch
   - Until registry entries exist, render `metadata-fallback`.

4. **Binary or file artifacts**
   - If `binaryArtifactPath`, `url`, or a download-capable contract exists, route to `binary`.
   - Panel shows a review card with provenance and open/download affordance.
   - Do not treat this as a complete visual if the skill is expected to have a paired human render.

5. **Unknown artifacts**
   - Route to `metadata-fallback`.
   - Display contract name, run id, skill run id, source, paths, created time, and a short explanation that no renderer is registered yet.

## 7. Component Integration

### 7.1 Shared chat state

Extend artifact state without breaking existing callers:

- Keep `currentArtifact: ArtifactSpec | null` for legacy chat block artifacts.
- Add `currentArtifactRef: ArtifactRenderRef | null`, or replace both with a discriminated union:

```ts
type CurrentArtifact =
  | { kind: 'legacy'; artifact: ArtifactSpec }
  | { kind: 'ref'; ref: ArtifactRenderRef };
```

The discriminated union is cleaner if the change can be contained; parallel fields are lower-risk if active in-flight sessions are modifying the chat context.

### 7.2 `ArtifactPanelConnected`

Responsibilities:

- Own resolver invocation.
- Render panel states from `ArtifactRenderResult`.
- Keep `onSendMessage` / `onNavigate` compatibility for legacy block artifacts.
- Avoid owning selected-run state; selected run remains in `ChatInterface` / agent-control state.

### 7.3 `ArtifactPanel`

Likely evolution:

- Either split into `ArtifactPanelShell` + render-specific body components.
- Or add `renderResult` as the body input and keep the shell unchanged.

Minimum body components:

- `LegacyArtifactBody`
- `HtmlArtifactBody`
- `CuratedArtifactBody`
- `BinaryArtifactBody`
- `ArtifactMetadataFallbackBody`

### 7.4 `AgentControlDeck`

Change:

- Stop building synthetic complete-looking `ArtifactSpec` objects for control-plane artifacts.
- Convert `ControlArtifact` to `ArtifactRenderRef`.
- Open the ref through shared chat/artifact context.

The deck can keep showing compact title/provenance rows. Full rendering belongs in the panel.

### 7.5 Selected-run thread and approvals

The same open-ref mechanism should be available to:

- artifact chips in the selected-run main thread
- `Review Evidence` actions in approval inspectors
- completed-run artifact rows

This avoids three separate artifact-opening behaviors.

## 8. Lane Arbitration

Keep the lane model from `AGENT_CONTROL_SURFACE_DESIGN_PLAN.md`:

- Main thread: selected run output / chat.
- Control deck: run selector, approvals, logs, compact metadata, artifact index.
- Artifact panel: human render and evidence review.

Layout rules:

- At ordinary desktop widths, opening the artifact panel compresses the control deck to an approval/status rail.
- At wide desktop widths, full deck + artifact panel may coexist if the main thread remains readable.
- On small screens, artifact review should be a modal/sheet state over the main surface; blocking approvals remain reachable.
- Width/padding constants should live in one small layout helper/module rather than duplicated in `ChatInterface`, `AgentControlDeck`, and `ArtifactPanel`.

## 9. Sequencing

This bridge should not interrupt the current agent-control UI/QA session. Recommended sequence:

1. Finish current agent-control surface stabilization and QA.
2. Implement bridge scaffolding with fallback render only:
   - `ArtifactRenderRef`
   - shared open-ref state
   - resolver shell
   - metadata fallback
   - deck opens refs instead of synthetic block specs
3. Add F122 HTML route once F122 shared infra PRs land or are mocked.
4. Add curated-registry route once F147 PR-0/PR-1 expose the relevant substrate and lookup shape.
5. Add report-pack hooks after F148 / Block D composition substrate exists.

This order prevents the `/analyst` panel from blocking F122 or F147, but keeps the integration point stable.

## 10. Test Plan

Unit tests:

- `ControlArtifact -> ArtifactRenderRef` preserves identity/provenance.
- Resolver routes `HtmlArtifact` to `html-artifact`.
- Resolver routes unknown contracts to `metadata-fallback`.
- Resolver routes binary-only artifacts to `binary`.
- Legacy `ArtifactSpec` still renders through `BriefingRenderer`.

Component tests:

- `AgentControlDeck` opens an artifact ref, not a synthetic complete visual.
- `ArtifactPanelConnected` renders metadata fallback for unknown control artifact.
- `ArtifactPanelConnected` preserves legacy block artifact behavior.
- `HtmlArtifact` branch renders loading/error/fallback states without `dangerouslySetInnerHTML`.
- Artifact panel open does not clear selected run.

Integration / visual QA:

- Open artifact from deck `Recent`.
- Open artifact from selected-run thread.
- Open artifact from approval `Review Evidence`.
- Verify deck compresses to approval/status rail when panel opens.
- Verify provenance is visible in every fallback and renderer state.
- Verify user can ask Hank about the open artifact.

## 11. Acceptance Criteria

The bridge is ready when:

- Control-plane artifact rows can open the artifact panel via `ArtifactRenderRef`.
- Unknown contracts render a clear fallback with provenance.
- Existing `:::artifact` behavior is not regressed.
- F122 HTML renderer can be mounted behind the resolver without changing `AgentControlDeck`.
- F147 registry renderers can be mounted behind the resolver without changing `AgentControlDeck`.
- Artifact panel open/close does not disrupt selected-run context or normal chat streaming.
- Lane arbitration remains coherent across desktop and small screens.

## 12. Open Questions

1. Should `CurrentArtifact` be a discriminated union immediately, or should we add `currentArtifactRef` alongside legacy state for a lower-risk transition?
2. What exact registry key should curated contracts use before F147 central lookup exists: `contractName`, `skill`, `artifact_id` prefix, or sidecar-declared descriptor id?
3. Should binary artifacts with known skill contracts show "visual pending" warnings when a canonical renderer is expected but absent?
4. Should `ArtifactPanelConnected` be renamed once it becomes resolver-backed, or should the stable name remain for lower churn?

