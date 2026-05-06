# Frontend Type Boundary Design

> Status: active design, resolver, registry, chat/research payload, UI block registry, and shared-state/tool-cache slices implemented 2026-05-06.
> Scope: residual frontend type debt that cannot be safely removed by mechanical `any` to `unknown` edits.

## Goal

Move remaining frontend type debt out of feature callsites and into explicit boundary contracts. The frontend already passes `pnpm typecheck`; the remaining debt is mostly broad assertions at dynamic boundaries: resolver outputs, generic registries, streamed chat payloads, UI block sanitizers, and shared-state primitives.

The design target is not "zero casts everywhere." The target is one audited boundary per dynamic system, with typed callers on both sides.

## Non-Goals

- Do not narrow intentionally flexible backend payloads until runtime schemas exist.
- Do not hand-edit generated OpenAPI types.
- Do not replace adapters with ad hoc component-local parsing.
- Do not add `as unknown as T` chains to satisfy TypeScript.

## Boundary Rules

1. Unknown data is allowed only at an ingress boundary.
2. Each ingress boundary must normalize into a catalog or schema-owned type before feature hooks consume it.
3. Generic registries should keep any unavoidable cast inside the registry implementation, not in every caller.
4. Adapter `transform()` methods that feed the SDK resolver must return catalog source types or structural equivalents checked by a helper.
5. Dynamic UI block rendering must map block ids to prop types before components are invoked.

## Workstreams

### 1. Resolver / Catalog Boundary

Current source: `frontend/packages/connectors/src/resolver/`.

Implemented slice:

- Added `resolver/contracts.ts` with `ResolverContext`, `SourceParams`, `SourceOutput`, `SourceResolver`, `ResolverMap`, `defineResolverMap()`, and `sourceOutput()`.
- Added `getSourceQuerySnapshot()` in `resolver/core.ts` so nested resolver cache reads use `queryClient.getQueryData<SDKSourceOutputMap[Id]>()` instead of direct `query.state.data as ...`.
- Typed `useDataSource()` query data directly with `useQuery<SDKSourceOutputMap[Id], DataSourceError>()`.
- Tightened `RiskScoreAdapter.transform()` to return `RiskScoreSourceData` and expanded `RiskScoreSourceData` to match the adapter's enhanced fields.
- Normalized Monte Carlo scenario flags before returning `MonteCarloSourceData`.
- Replaced income-projection metadata, monthly-calendar, and quarterly-summary casts with resolver-local field normalizers.
- Removed remaining resolver-side adapter input assertions by exporting the risk-analysis adapter input type, normalizing raw risk-analysis records, typing `StockManager` stock-analysis results, and passing typed what-if responses directly.
- Added type-level resolver contract tests so adapter outputs must remain assignable to catalog source outputs.
- Narrowed `PortfolioManager.analyzePortfolioRisk()` and downstream complete/comprehensive risk-analysis returns to the generated analyze-response payload shape.

Remaining resolver actions:

- No known broad resolver source-output casts remain outside tests. Future resolver work should preserve the contract helpers and add specific normalizers for new flexible backend fields.

Acceptance:

- `registry.ts`, `core.ts`, and `useDataSource.ts` contain no broad source-output casts except localized field normalizers.
- `pnpm typecheck` and `pnpm lint` remain green.

### 2. Cache / Service Generic Registries

Current sources: `frontend/packages/app-platform/src/`, `frontend/packages/chassis/src/services/`.

Design:

- Introduce typed key maps:
  - `ServiceKeyMap` for service containers.
  - `AdapterKeyMap` for adapter registries.
  - `EventPayloadMap` for event buses.
  - `CacheEntryMap` for unified cache entries where keys are known.
- Keep a single internal cast in each registry read path after key validation.
- Expose typed convenience methods for known keys and preserve generic fallbacks for plugin-like or unknown keys.

Implemented slice:

- Made `ServiceContainer` generic over a known service map.
- Added explicit dynamic fallback methods (`registerDynamic()`, `safeRegisterDynamic()`, `getDynamic()`, `hasDynamicService()`, and `unregisterDynamic()`) so unknown service keys are opt-in.
- Typed the session-scoped service container with a `SessionServiceRegistry`.
- Removed caller-supplied generics from known session service lookups in `SessionServicesProvider`.
- Added `ServiceContainer` contract tests covering typed known-key reads and dynamic fallback access.
- Made `EventBus` generic over an event-payload map.
- Added explicit dynamic event methods (`onDynamic()`, `emitDynamic()`, and `offDynamic()`) for configurable or plugin-like event names.
- Typed chassis cache-coordination event names through a shared `EventPayloadMap` and removed caller-supplied event payload generics from known emits/subscriptions.
- Added `EventBus` contract tests covering known event payload inference and dynamic fallback access.
- Made `UnifiedCache` generic over a cache-entry map, with typed `get()`, `set()`, and `inspect()` methods for known keys.
- Added explicit dynamic cache methods (`getDynamic()`, `setDynamic()`, `inspectDynamic()`, and `listEntriesDynamic()`) for generated cache keys.
- Updated adapter and cache-warmer generated-key reads to use `getDynamic()`.
- Added `UnifiedCache` contract tests covering known cache-entry inference and dynamic generated-key access.
- Made `AdapterRegistry` use an augmentable `AdapterKeyMap`.
- Added `getDynamicAdapter()` for plugin-like adapter keys while keeping `getAdapter()` typed for known adapter keys.
- Declared the connector adapter key map in `adapters/adapterRegistryTypes.ts`.
- Added `AdapterRegistry` contract tests covering known adapter inference and dynamic fallback access.

Remaining actions:

- No known cache/service generic-registry actions remain. New registries should follow the typed-key plus named-dynamic-fallback pattern.

Acceptance:

- Callers no longer write generic `as T` when resolving known service, adapter, event, or cache keys.
- The generic fallback API is named as unsafe or dynamic.

### 3. Chat / Research Payload Schema Boundary

Current sources: `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts`, `useResearchChat.ts`, and related chat services.

Design:

- Define runtime parsers for streamed chat events, UI blocks, source registry snapshots, file-reader payloads, and portfolio display metadata.
- Convert raw stream chunks to discriminated unions before state updates.
- Keep source-registry and citation objects schema-owned so UI components do not cast streamed payloads.

Implemented slice:

- Added `chatStreamPayloads.ts` with runtime parsers for gateway stream chunks, citation validation events, source registry snapshots, code execution output files, tool approval payloads, and portfolio display names.
- Updated `usePortfolioChat()` and `useResearchChat()` to switch on parsed discriminated stream events before state updates.
- Replaced the portfolio chat source-registry snapshot cast with source normalization shared by research chat.
- Made malformed citation-validation chunks recoverable parse errors with hook-level logging.
- Narrowed FileReader data URL handling so non-string reader results reject instead of being asserted.
- Added parser tests covering source registry snapshots, citation validation normalization, recoverable parse errors, code execution files, and display-name metadata.
- Moved markdown UI block/artifact fence payloads through `parseUIRenderableSpecs()` so only block/layout discriminated specs cross the chassis parser boundary, while malformed layouts remain explicit renderer fallbacks.

Remaining actions:

- No known chat/research payload schema actions remain. New stream events, persisted payloads, or renderable spec shapes should add parser fixtures before feature hooks or UI components consume them.

Acceptance:

- Chat and research hooks operate on discriminated payload types after parse.
- Stream parsing errors become typed recoverable events with logging.

### 4. UI Block Registry / Sanitizer Contracts

Current sources: `frontend/packages/ui/src/sdk/rendering/`, `frontend/packages/ui/src/components/chat/blocks/`.

Design:

- Define a `BlockPropsMap` keyed by block id.
- Register blocks through `defineBlockRegistry()` so each component receives `BlockPropsMap[Id]`.
- Make sanitizers return typed `BlockPropsMap[Id]` values or a typed rejection result.
- Keep unknown JSON only at the sanitizer ingress.

Shipped in slice `Type UI block registry contracts`:

- `BlockPropsMap` now keys known blocks to component props, with `BlockSanitizedPropsMap` for blocks whose JSON props differ from rendered props.
- `registerBlock`/`resolveBlock` are restricted to known block ids; ad hoc JSON paths use explicit `registerDynamicBlock`/`resolveDynamicBlock`.
- Chat defaults, SDK manifest blocks, and design briefing blocks all register through the typed map.
- Registry type tests prove unknown ids are rejected by the typed API and that sanitizer output must match mapped sanitized props.
- Direct sanitizer fixture tests cover default chat blocks and design blocks with valid payloads, malformed required fields, and optional-field normalization.

Remaining:

- No known UI block registry or sanitizer actions remain. New registered blocks should extend the typed maps and add direct sanitizer fixtures for accepted and rejected JSON payloads.

Acceptance:

- Block rendering does not cast component props through a generic registry type.
- Sanitizer tests cover invalid payloads and prove typed output for each registered block.

### 5. Shared State / Flow Primitives

Current source: `frontend/packages/connectors/src/primitives/`.

Design:

- Keep generic primitives for truly ad hoc flows.
- Add key-scoped stores for known shared states where callers currently initialize or update through casts.
- Use factory defaults for empty initial state rather than `{} as TContext`.

Shipped in slice `Type shared-state primitive contracts`:

- `useSharedState` now accepts only keys registered through `SharedStateMap`.
- Ad hoc state moved behind the explicit `useDynamicSharedState` API.
- `useFlow` now uses empty context only for context-free flows; typed flow contexts require an `initialContext` or `createInitialContext` factory.
- Primitive contract tests prove unknown shared-state keys are rejected by the typed API and dynamic state remains available by name.

Shipped in slice `Type scenario tool cache params`:

- `uiStore.toolRunParams` now has an augmentable `ToolRunParamsMap` for known scenario run caches.
- `setToolRunParams` and `clearToolRunParams` are restricted to registered cache keys and mapped payload values.
- Ad hoc/UI-only scenario caches moved behind explicit `setDynamicToolRunParams` and `clearDynamicToolRunParams` APIs.
- Backtest, Monte Carlo, stress test, tax harvest, optimize, and what-if connector hooks register their cache entries and narrow `cacheKey` options to those known keys.
- Scenario UI tools use the dynamic API for local UI state such as form hydration, auto-run context flags, and rebalance UI caches.

Remaining:

- No known shared-state, flow, or scenario tool-cache actions remain. New scenario caches should either augment `ToolRunParamsMap` or use the dynamic API with a documented UI-only rationale.

Acceptance:

- Known shared flows use key-scoped typed stores.
- Generic primitives retain explicit `unknown` or dynamic naming so consumers opt into flexibility.

## Sequence

1. Finish resolver/catalog boundary.
2. Apply the same typed-key pattern to service, adapter, event, and cache registries.
3. Add runtime schemas for chat and research streams plus markdown renderable payloads.
4. Type UI block registry and sanitizers. Registry map shipped; sanitizer fixture expansion remains.
5. Split shared-state primitives and scenario tool caches into known typed stores plus explicit dynamic fallbacks.

## Verification

Run from `frontend/` after each slice:

```bash
pnpm typecheck
pnpm lint
```

For UI block and chat schema slices, also run the relevant Vitest suites before closure.
