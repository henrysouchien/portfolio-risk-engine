# A10 — Scenario Tool Component Registry

## Context

Adding or modifying a scenario tool today requires editing **5+ separate files** that each maintain their own copy of the tool list. The tool's identity, label, icon, route, lazy import, and component instance are scattered across:

1. `frontend/packages/connectors/src/stores/uiStore.ts` — `ScenarioToolId` union + `VALID_TOOL_IDS` array
2. `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx` — lazy imports + `fallbackByTool` switch map
3. `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosLanding.tsx` — `TOOL_CARDS` array (icon, title, description, badge)
4. `frontend/packages/ui/src/components/portfolio/scenarios/shared/ToolBreadcrumb.tsx` — `TOOL_LABELS` map
5. `frontend/packages/ui/src/components/portfolio/scenarios/workflows.ts` — workflow step `toolId` references
6. `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx` — `SIDEBAR_ITEMS` array (curated subset of 5 tools + `'landing'`, custom SVG icons by design — type-only fix needed, not registry-driven)

The codebase already has a clean precedent for this kind of consolidation: **`DataCatalog`** in `frontend/packages/chassis/src/catalog/DataCatalog.ts` — a type-safe registry of 30+ data sources with `register()`, `list()`, `describe()`, `search()`, `listByCategory()`, dependency validation, and cycle detection. The DataCatalog is exported as a singleton (`dataCatalog`) and consumed across packages.

A10 mirrors that pattern for **scenario tools (UI components)** rather than data sources. With Compare Scenarios shipped as agent-only on 2026-04-10, the 8-tool set is final, and the registry has no remaining unknowns.

**Goal**: One descriptor per tool, registered in one place. The router, landing page, and breadcrumb all read from the registry. Adding a future tool becomes a one-file change (plus an opt-in update to AppSidebar if it should appear there too).

**Out of scope**: New runtime capabilities (feature flags, dynamic availability, agent discovery surface, runtime registration of plugin tools). Pure refactor.

---

## Design

### Source of truth: static id list + lookup registry

The 8 tool ids and the `'landing'` sentinel must be available **at app boot** for hash routing (`hashSync.parseHash` runs before any React tree mounts), but the components themselves should stay lazy. Splitting the two concerns:

- **Static `SCENARIO_TOOL_IDS` const array** in chassis — the authoritative id list. `ScenarioToolId` is derived from this array. Hash validation and `VALID_TOOL_IDS` consume this directly, with **zero runtime dependency on the registry**.
- **`ScenarioToolRegistry`** in chassis — populated lazily from ui. Holds descriptor metadata (label, description, icon, component, dataSources). Consumers that only run *after* the React tree mounts (router, landing, breadcrumb) read from the registry.

This avoids the bootstrap-ordering footgun where `useHashSync()` would run at app boot, read `VALID_TOOL_IDS` from an empty registry, and reject valid `#scenarios/<tool>` deeplinks until the lazy `ScenariosRouter` mounted.

It also matches how `DataCatalog` works today: `DataSourceId` is a hand-maintained union in `chassis/src/catalog/types.ts`; the catalog only holds *descriptors* for known ids.

### `scenarioTools.ts` — types + registry

Lives in `frontend/packages/chassis/src/catalog/scenarioTools.ts` (new file, alongside `DataCatalog.ts`).

```ts
import type { ComponentType, LazyExoticComponent } from 'react';
import type { DataSourceId } from './types';

/**
 * Authoritative list of scenario tool ids. Hand-maintained.
 * `ScenarioToolId` is derived from this array, so adding a new id
 * here flows through to all consumers via the type system.
 */
export const SCENARIO_TOOL_IDS = [
  'what-if',
  'optimize',
  'backtest',
  'stress-test',
  'hedge',
  'monte-carlo',
  'rebalance',
  'tax-harvest',
] as const;
// ^ Order matches the current ScenariosLanding TOOL_CARDS order (line 37-86).
//   ScenariosLanding renders cards via scenarioToolRegistry.list(), which
//   returns descriptors in registration order. registry.ts MUST register
//   in this same order to preserve the existing landing UI layout.

export type ScenarioToolId = (typeof SCENARIO_TOOL_IDS)[number];

/**
 * Structural icon type — matches both Lucide icons and the custom SVG glyph
 * components used by AppSidebar. Avoids forcing chassis to depend on lucide-react.
 */
export type ScenarioToolIcon = ComponentType<{ className?: string }>;

export interface ScenarioToolComponentProps {
  context: Record<string, unknown>;
  /**
   * Navigate to another scenario tool. The optional `context` payload is
   * forwarded as the next tool's initial context (used for cross-tool chaining
   * — e.g. Optimize -> What-If passing resolved_weights).
   */
  onNavigate: (tool: ScenarioToolId, context?: Record<string, unknown>) => void;
}

export interface ScenarioToolDescriptor {
  /** Unique tool identifier (matches hash route segment) */
  id: ScenarioToolId;
  /** Display label used by breadcrumb, landing card, workflow progress */
  label: string;
  /** Short description shown on landing card */
  description: string;
  /** Icon component (Lucide or custom). Structurally typed — accepts `{ className?: string }` */
  icon: ScenarioToolIcon;
  /** Optional badge ("Most used", etc.) on landing card */
  badge?: string;
  /** Lazy component factory — registry never imports tool modules eagerly */
  component: LazyExoticComponent<ComponentType<ScenarioToolComponentProps>>;
  /**
   * Data sources this tool depends on. Used for documentation today;
   * future work can pre-fetch / validate from this list.
   * Each entry must be a registered DataCatalog source.
   */
  dataSources: readonly DataSourceId[];
}

const SCENARIO_TOOL_ID_SET = new Set<string>(SCENARIO_TOOL_IDS);

export function isScenarioToolId(value: string): value is ScenarioToolId {
  return SCENARIO_TOOL_ID_SET.has(value);
}

export class ScenarioToolRegistry {
  private readonly descriptors = new Map<ScenarioToolId, ScenarioToolDescriptor>();

  register(descriptor: ScenarioToolDescriptor): void {
    if (!isScenarioToolId(descriptor.id)) {
      throw new Error(`Cannot register unknown scenario tool '${descriptor.id}' (not in SCENARIO_TOOL_IDS)`);
    }
    if (this.descriptors.has(descriptor.id)) {
      throw new Error(`Scenario tool '${descriptor.id}' is already registered`);
    }
    this.descriptors.set(descriptor.id, descriptor);
  }

  describe(id: ScenarioToolId): ScenarioToolDescriptor {
    const descriptor = this.descriptors.get(id);
    if (!descriptor) throw new Error(`Unknown scenario tool '${id}' — registry not initialized?`);
    return descriptor;
  }

  has(id: string): id is ScenarioToolId {
    return this.descriptors.has(id as ScenarioToolId);
  }

  list(): ScenarioToolDescriptor[] {
    return Array.from(this.descriptors.values());
  }

  listIds(): ScenarioToolId[] {
    return Array.from(this.descriptors.keys());
  }

  /** Test-only helper: assert registry has a descriptor for every SCENARIO_TOOL_IDS entry. */
  assertComplete(): void {
    const missing = SCENARIO_TOOL_IDS.filter((id) => !this.descriptors.has(id));
    if (missing.length > 0) {
      throw new Error(`ScenarioToolRegistry missing descriptors for: ${missing.join(', ')}`);
    }
  }
}

export const scenarioToolRegistry = new ScenarioToolRegistry();
```

The class is intentionally smaller than `DataCatalog` — no category/search/cycle detection because there are 8 tools, no categories, and no dependency graph between tools. The two registry-shape additions over the original sketch are:
- `register()` validates `descriptor.id` is in `SCENARIO_TOOL_IDS` (catches typos at registration time, not first lookup)
- `assertComplete()` is a test-only invariant: every static id has a registered descriptor

### Where descriptors are registered

Tools live in `@risk/ui` and use icons from `lucide-react`, so the descriptors **cannot** live in `@risk/chassis` (chassis must not depend on ui or react components). The pattern:

- **chassis** exports the *types*, the *static id list*, and the *empty registry singleton*
- **ui** imports the singleton and registers all 8 descriptors at module-load time

New file: `frontend/packages/ui/src/components/portfolio/scenarios/registry.ts`

```ts
import { lazy } from 'react';
import { Activity, BarChart3, LineChart, Scale, Shield, Target, Zap } from 'lucide-react';
import { scenarioToolRegistry } from '@risk/chassis';

scenarioToolRegistry.register({
  id: 'what-if',
  label: 'What-If',
  description: 'Edit weights, simulate risk impact',
  icon: Zap,
  badge: 'Most used',
  component: lazy(() => import('./tools/WhatIfTool')),
  dataSources: ['what-if'],
});

scenarioToolRegistry.register({
  id: 'optimize',
  label: 'Optimize',
  description: 'Find optimal allocation for your risk tolerance',
  icon: Target,
  component: lazy(() => import('./tools/OptimizeTool')),
  dataSources: ['optimization'],
});

// ...6 more
```

### Registration entry point

Hash routing uses **`SCENARIO_TOOL_IDS`** (static, evaluated at chassis module-load), so it does *not* depend on the registry being populated. That removes the boot-ordering constraint entirely.

The remaining requirement is simpler: **the registry must be populated before any component calls `scenarioToolRegistry.describe()`**. The natural place for that side-effect import is **`ScenariosRouter.tsx` itself**:

```ts
// frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx
import './registry'; // populates scenarioToolRegistry — must run before describe() below
import { scenarioToolRegistry } from '@risk/chassis';
// ...
```

Why this works:
- `ScenariosRouter.tsx` is currently lazy-loaded inside `ModernDashboardApp.tsx` via `React.lazy(() => import('./ScenariosRouter'))`. When the dashboard chooses to render the scenarios view, the router module loads, which transitively loads `./registry`, which registers all 8 descriptors. By the time `ScenariosRouter`'s render function calls `scenarioToolRegistry.describe(activeTool)`, the registry is populated.
- The descriptor module does not eagerly evaluate the `lazy(() => import(...))` factories — it only stores the factory references. So the actual tool components stay code-split.
- **`ScenariosRouter.test.tsx`** (which imports `ScenariosRouter` directly) automatically gets a populated registry via the same transitive import. No test setup change needed.
- `ScenariosLanding.tsx` and `ToolBreadcrumb.tsx` are imported from inside `ScenariosRouter`, so they are guaranteed to see a populated registry.

This is the cleanest path: no `ModernDashboardApp.tsx` change, no per-test bootstrap, no risk of tree-shaking dropping a side-effect import in some other file.

### Consumer refactors

| Consumer | Reads from | Before | After |
|---|---|---|---|
| **`ScenariosRouter.tsx`** | registry | 8 `lazy()` imports + `fallbackByTool` map | `import './registry'` (side-effect populates registry); `const Tool = scenarioToolRegistry.describe(activeTool).component; <Tool ... />` |
| **`ScenariosLanding.tsx`** | registry | Hand-maintained `TOOL_CARDS` array | `const TOOL_CARDS = scenarioToolRegistry.list()` |
| **`ToolBreadcrumb.tsx`** | registry | `TOOL_LABELS` const map | `scenarioToolRegistry.describe(tool).label`; helper `getScenarioToolLabel()` stays as a thin wrapper |
| **`hashSync.ts`** | static `SCENARIO_TOOL_IDS` (boot-safe) | `VALID_TOOL_IDS.includes(...)` | Still uses `VALID_TOOL_IDS`; that array is now computed from `SCENARIO_TOOL_IDS` (no registry dependency, runs at app boot) |
| **`uiStore.ts`** | static `SCENARIO_TOOL_IDS` (boot-safe) | Local `ScenarioToolId` union + `VALID_TOOL_IDS` literal | Re-exports `ScenarioToolId` from `@risk/chassis`; `VALID_TOOL_IDS = [...SCENARIO_TOOL_IDS, 'landing'] as const` |
| **`AppSidebar.tsx`** | nothing new (type-only fix) | Uses `ScenarioToolId` for `id` field but stores `'landing'` in `SIDEBAR_ITEMS` | Type fix: change field type to `ScenarioRouteId` (or keep `ScenarioToolId` and use a discriminated `kind: 'tool-or-landing'`); curated icon set + tool subset stays hand-coded by design |
| **`workflows.ts`** | nothing new (literals already valid) | Strings like `'stress-test'` literal | Unchanged — workflow steps already use real `ScenarioToolId` strings |

### `ScenarioToolId` migration

`ScenarioToolId` currently lives in `connectors/uiStore.ts` and includes `'landing'` as a sentinel. After the refactor:

- **`@risk/chassis`** exports `ScenarioToolId` as the union of the 8 real tool ids (derived from `SCENARIO_TOOL_IDS`, no `'landing'`)
- **`@risk/connectors`** defines a wrapper type `ScenarioRouteId = ScenarioToolId | 'landing'` for store/hash use, and re-exports `ScenarioToolId` from chassis
- All existing call sites that used the old `ScenarioToolId` (which included `'landing'`) get updated:
  - Code that needs the route id (including landing) → `ScenarioRouteId`
  - Code that needs a real tool id (router fallback, breadcrumb, landing onSelect) → `ScenarioToolId`
- The existing `SelectableScenarioTool = Exclude<ScenarioToolId, 'landing'>` aliases in `ScenariosRouter.tsx`, `ScenariosLanding.tsx`, `ToolBreadcrumb.tsx` collapse into the new `ScenarioToolId` directly (no exclusion needed)

**Callsites that need the type split** (TypeScript will surface all of these):

1. `connectors/src/stores/uiStore.ts` — `ScenarioRouterState.activeTool`, `setActiveTool`, `getStoredActiveTool`, the persist slice — all use `ScenarioRouteId`
2. `connectors/src/navigation/hashSync.ts` — `ParsedHash.tool` becomes `ScenarioRouteId`
3. `connectors/src/stores/scenarioWorkflowStore.ts` — uses `ScenarioToolId` for workflow steps; **stays as the new (8-tool) `ScenarioToolId`** because workflow steps cannot target `'landing'`
4. `ui/src/components/dashboard/AppSidebar.tsx` — `AppSidebarProps.activeScenarioTool`, `onNavigateScenarioTool`, and the `SidebarItemDef.id` for tool entries: change to `ScenarioRouteId` (sidebar surfaces a "Workflows" entry mapped to `'landing'`)
5. `ui/src/components/portfolio/scenarios/ScenariosRouter.tsx` / `ScenariosLanding.tsx` / `shared/ToolBreadcrumb.tsx` / `shared/ToolCard.tsx` — drop `SelectableScenarioTool`, use `ScenarioToolId` directly
6. `ui/src/components/portfolio/scenarios/useScenarioChatLauncher.ts` and `useWorkflowStepCompletion.ts` — already pass real tool ids; `ScenarioToolId` works as-is
7. Tests in `connectors/src/stores/scenarioWorkflowStore.test.ts`, `connectors/src/navigation/__tests__/hashSync.test.ts`, `ui/.../shared/WorkflowProgressBar.test.tsx`, `ui/.../tools/__tests__/WhatIfTool.test.tsx` — string literals already valid; type imports updated if any reference `ScenarioToolId` directly

### Package boundary

Chassis must not depend on `@risk/ui` or `lucide-react`. The plan keeps the boundary clean by **structurally typing the icon field** rather than importing `LucideIcon`:

```ts
export type ScenarioToolIcon = ComponentType<{ className?: string }>;
```

Every Lucide icon satisfies this shape (they all accept a `className` prop), and so do the custom SVG glyph components in `AppSidebar.tsx` (which use the same `FC<{ className?: string }>` pattern). No `lucide-react` dependency added to chassis. No peer-dep update to `frontend/packages/chassis/package.json`.

This was confirmed by reading `frontend/packages/chassis/package.json` — it currently lists `react` only as a peer dep through `@tanstack/react-query`, and adding `lucide-react` would unnecessarily bloat the chassis surface for every consumer.

---

## Files

### New

| Path | Purpose |
|---|---|
| `frontend/packages/chassis/src/catalog/scenarioTools.ts` | `SCENARIO_TOOL_IDS` const, `ScenarioToolId`, `ScenarioToolIcon`, `ScenarioToolDescriptor`, `ScenarioToolComponentProps`, `ScenarioToolRegistry` class, `scenarioToolRegistry` singleton, `isScenarioToolId` |
| `frontend/packages/chassis/src/catalog/__tests__/scenarioTools.test.ts` | Registry unit tests (register/describe/has/list/duplicate detection/unknown-id rejection/`assertComplete`) |
| `frontend/packages/ui/src/components/portfolio/scenarios/registry.ts` | All 8 tool descriptor registrations (the only place that imports tool modules + lucide icons) |
| `frontend/packages/ui/src/components/portfolio/scenarios/__tests__/registry.test.ts` | Snapshot test asserting `assertComplete()` passes after import side-effect, plus per-tool field shape |

### Modified

| Path | Change |
|---|---|
| `frontend/packages/chassis/src/index.ts` | Export `scenarioToolRegistry`, `ScenarioToolRegistry`, `SCENARIO_TOOL_IDS`, `ScenarioToolId`, `ScenarioToolIcon`, `ScenarioToolDescriptor`, `ScenarioToolComponentProps`, `isScenarioToolId` |
| `frontend/packages/connectors/src/stores/uiStore.ts` | Drop local `ScenarioToolId` literal union; re-export `ScenarioToolId` from chassis; add `ScenarioRouteId = ScenarioToolId \| 'landing'`; rebuild `VALID_TOOL_IDS = [...SCENARIO_TOOL_IDS, 'landing'] as const`; update `ScenarioRouterState`, `setActiveTool`, `getStoredActiveTool` to use `ScenarioRouteId` |
| `frontend/packages/connectors/src/index.ts` | Re-export `ScenarioToolId`, `ScenarioRouteId`, `SCENARIO_TOOL_IDS` from new locations |
| `frontend/packages/connectors/src/navigation/hashSync.ts` | `ParsedHash.tool` → `ScenarioRouteId`; continues to use `VALID_TOOL_IDS` (now derived from `SCENARIO_TOOL_IDS` — no behavioural change, just type tightening) |
| `frontend/packages/connectors/src/stores/scenarioWorkflowStore.ts` | Type imports updated; workflow step `toolId` stays as new `ScenarioToolId` (workflows can't target `'landing'`) |
| `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx` | Add `import './registry';` side-effect; drop 8 lazy imports + `fallbackByTool`; render via `scenarioToolRegistry.describe(activeTool).component`; remove `SelectableScenarioTool` alias |
| `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosLanding.tsx` | Drop `TOOL_CARDS` const array; derive cards from `scenarioToolRegistry.list()`; remove `SelectableScenarioTool` alias |
| `frontend/packages/ui/src/components/portfolio/scenarios/shared/ToolBreadcrumb.tsx` | Drop `TOOL_LABELS` map; `getScenarioToolLabel()` calls `scenarioToolRegistry.describe(tool).label`; remove `SelectableScenarioTool` alias |
| `frontend/packages/ui/src/components/portfolio/scenarios/shared/ToolCard.tsx` | Update `toolId` prop type to `ScenarioToolId` (no `Exclude` needed) |
| `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx` | Type-only fix: `activeScenarioTool` and `onNavigateScenarioTool` props change to `ScenarioRouteId`; `SidebarItemDef.id` for tool entries widens to `ScenarioRouteId`. Curated tool subset and custom SVG icons stay as-is by design (sidebar is intentionally not registry-driven). |

### Tests touched

| Path | Change |
|---|---|
| `frontend/packages/connectors/src/stores/scenarioWorkflowStore.test.ts` | Type imports updated; existing string literals still valid |
| `frontend/packages/connectors/src/navigation/__tests__/hashSync.test.ts` | Existing `parseHash`/`buildHash`/`useUIStore` cases stay green (string literals); covers the `'landing'` ↔ `ScenarioRouteId` boundary |
| `frontend/packages/ui/src/components/portfolio/scenarios/shared/WorkflowProgressBar.test.tsx` | Type imports updated if needed |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/__tests__/*.test.tsx` | Imports if any reference `ScenarioToolId` directly |
| `frontend/packages/ui/src/components/dashboard/__tests__/AppSidebar*.test.tsx` (if exists) | Type updates for `activeScenarioTool` prop |

---

## Implementation phases

Each phase compiles and tests pass before moving to the next.

### Phase 1 — chassis: static id list + empty registry
1. Add `frontend/packages/chassis/src/catalog/scenarioTools.ts` with `SCENARIO_TOOL_IDS`, `ScenarioToolId`, `ScenarioToolIcon`, `ScenarioToolDescriptor`, `ScenarioToolComponentProps`, `isScenarioToolId`, `ScenarioToolRegistry` class, `scenarioToolRegistry` singleton
2. Export from `chassis/src/index.ts`
3. Add unit tests in `chassis/src/catalog/__tests__/scenarioTools.test.ts`:
   - `register` happy path
   - `register` rejects duplicate id
   - `register` rejects unknown id (not in `SCENARIO_TOOL_IDS`)
   - `describe` returns descriptor / throws on missing
   - `has` positive/negative
   - `list`/`listIds` returns all entries
   - `assertComplete` passes when all 8 registered, throws otherwise
   - `isScenarioToolId` type guard
4. **Verify**: `pnpm --filter @risk/chassis test scenarioTools` passes; chassis builds clean (no new deps added to package.json)

### Phase 2 — connectors: type migration (boot-safe, no registry dep)
This phase uses **`SCENARIO_TOOL_IDS` only** — no dependency on the populated registry. This is the critical ordering fix: hash routing must work at app boot before any UI module loads.

1. In `connectors/src/stores/uiStore.ts`:
   - Drop the local `ScenarioToolId` literal union
   - Import and re-export `ScenarioToolId` from `@risk/chassis`
   - Add `export type ScenarioRouteId = ScenarioToolId | 'landing'`
   - Replace `VALID_TOOL_IDS` literal with `export const VALID_TOOL_IDS: readonly ScenarioRouteId[] = [...SCENARIO_TOOL_IDS, 'landing'] as const`
   - Update `ScenarioRouterState`, `setActiveTool`, `getStoredActiveTool`, store init slice — all use `ScenarioRouteId`
2. In `connectors/src/navigation/hashSync.ts`:
   - `ParsedHash.tool?: ScenarioRouteId`
   - Existing `VALID_TOOL_IDS.includes(...)` calls work as-is (the const is now derived from `SCENARIO_TOOL_IDS`)
3. In `connectors/src/stores/scenarioWorkflowStore.ts`:
   - Type imports updated; `WorkflowStep.toolId` stays as `ScenarioToolId` (workflows can't target `'landing'`)
4. Update `connectors/src/index.ts` to re-export `ScenarioToolId`, `ScenarioRouteId`, `SCENARIO_TOOL_IDS`
5. **Verify**: `pnpm --filter @risk/connectors typecheck && test` passes (the existing `hashSync.test.ts` covers `#scenarios/backtest` parsing and works unchanged because it uses string literals)

### Phase 3 — ui: descriptor registration + AppSidebar type fix
1. Add `frontend/packages/ui/src/components/portfolio/scenarios/registry.ts` with all 8 descriptors **in the current landing UI order**:
   1. what-if (badge: "Most used")
   2. optimize
   3. backtest
   4. stress-test
   5. hedge
   6. monte-carlo
   7. rebalance
   8. tax-harvest
   This order MUST match `SCENARIO_TOOL_IDS` in chassis (which was already adjusted to match) and the existing `TOOL_CARDS` array in `ScenariosLanding.tsx:37-86`. `scenarioToolRegistry.list()` returns descriptors in registration order, so the landing card grid will be visually identical.
   Each descriptor: id + label + description + lucide icon + optional badge + `lazy(() => import('./tools/<Name>Tool'))` + dataSources.
2. Add `frontend/packages/ui/src/components/portfolio/scenarios/__tests__/registry.test.ts`:
   - Imports `./registry` to trigger registration
   - Calls `scenarioToolRegistry.assertComplete()`
   - Asserts each descriptor has non-empty label, description, icon, component, dataSources
   - Asserts `scenarioToolRegistry.listIds()` returns ids in the expected landing order (regression guard against accidental reordering)
3. Fix `AppSidebar.tsx` types (no behavioural change, no registry dep):
   - `AppSidebarProps.activeScenarioTool: ScenarioRouteId`
   - `AppSidebarProps.onNavigateScenarioTool: (tool: ScenarioRouteId) => void`
   - `SidebarItemDef.id: ViewId | ScenarioRouteId`
4. **Verify**: `pnpm --filter @risk/ui test registry` passes; AppSidebar typechecks; existing UI still works (no consumer of the registry yet)

### Phase 4 — ui: consumer refactor (router + landing + breadcrumb)
1. Refactor `ScenariosRouter.tsx`:
   - Add `import './registry';` at the top (side-effect import — populates the registry transitively when this module loads)
   - Drop 8 lazy imports + `fallbackByTool` map
   - Drop `SelectableScenarioTool` alias (use `ScenarioToolId`)
   - When `activeTool !== 'landing'`: `const ToolComponent = scenarioToolRegistry.describe(activeTool).component`; render `<ToolComponent context={toolContext} onNavigate={setActiveTool} />`
2. Refactor `ScenariosLanding.tsx`:
   - Drop the `TOOL_CARDS` literal
   - `const TOOL_CARDS = scenarioToolRegistry.list()` — returns descriptors with `{ id, label, description, icon, badge }` in `SCENARIO_TOOL_IDS` order (see Phase 3 — registration order = list output order)
   - Update the `ToolCard` JSX to read `tool.id`, `tool.icon`, `tool.label`, `tool.description`, `tool.badge`
   - Drop `SelectableScenarioTool` alias
3. Refactor `ToolBreadcrumb.tsx`:
   - Drop `TOOL_LABELS` map
   - `getScenarioToolLabel(tool)` returns `scenarioToolRegistry.describe(tool).label`
   - Drop `SelectableScenarioTool` alias
4. Update `ToolCard.tsx` prop types: `toolId: ScenarioToolId` (the no-Exclude version)
5. **Verify**: `pnpm --filter @risk/ui typecheck && test` passes — `ScenariosRouter.test.tsx` works without modification because importing `ScenariosRouter` transitively imports `./registry` and populates the registry

### Phase 5 — full test sweep + manual verification
1. `pnpm test` across all frontend packages
2. Start `risk_module` + `risk_module_frontend` services via `services-mcp`
3. Manual smoke checks (see Verification section below)

---

## Reusable existing code

| Path | Used as |
|---|---|
| `frontend/packages/chassis/src/catalog/DataCatalog.ts` | Architectural reference (registry pattern, register/describe/has/list, singleton export) |
| `frontend/packages/chassis/src/catalog/types.ts` | `DataSourceId` union — used in `dataSources: readonly DataSourceId[]` field |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/*.tsx` | The 8 existing tool components (no changes — they already conform to the props shape) |
| `frontend/packages/ui/src/components/portfolio/scenarios/shared/ToolCard.tsx` | Existing card UI; props become registry-aware |

---

## Verification

### Unit tests (added in this PR)
- `chassis/.../scenarioTools.test.ts` — 8 tests: register happy path, register rejects duplicate, register rejects unknown id, describe success, describe missing throws, has positive/negative, list/listIds returns all entries, `assertComplete` invariant, `isScenarioToolId` type guard
- `ui/.../registry.test.ts` — 1 integration test: imports `./registry` (triggers registration) then calls `scenarioToolRegistry.assertComplete()`; asserts each of the 8 descriptors has non-empty label/description/icon/component/dataSources

### Existing tests (must still pass)
- `pnpm --filter @risk/chassis test`
- `pnpm --filter @risk/connectors test` — especially `scenarioWorkflowStore.test.ts` and `navigation/__tests__/hashSync.test.ts` (the latter covers `'landing'`, `#scenarios/backtest`, `#scenarios/invalid` boundaries)
- `pnpm --filter @risk/ui test` — especially `WorkflowProgressBar.test.tsx`, individual tool tests

### Boot-order verification
This is the critical regression risk. After Phase 2 lands (before Phase 3/4), manually verify in dev:
1. Restart frontend dev server (clears module cache)
2. Open `localhost:3000/#scenarios/what-if` directly (deep link, no navigation through landing)
3. Confirm: page loads on the What-If tool, NOT on the landing page

If this works after Phase 2, it confirms `VALID_TOOL_IDS` is correctly derived from `SCENARIO_TOOL_IDS` at module-load time of chassis (no registry dep).

### Manual end-to-end (after Phase 5)
1. Start services: `services-mcp` → start `risk_module` + `risk_module_frontend`
2. Open `localhost:3000`, log in
3. **Landing**: Navigate to Scenarios view; verify all 8 tool cards render on landing with correct icon/label/description/badge
4. **Tool mount**: Click each tool card; verify the right component mounts and breadcrumb shows the correct label
5. **Deep links**: Test direct hash routes: `#scenarios/what-if`, `#scenarios/optimize`, ..., `#scenarios/hedge` — each loads the correct tool from a fresh page load
6. **AppSidebar**: Verify the sidebar still shows the curated 5 scenario tools + "Workflows" entry, and clicking each navigates correctly (this surface is *not* registry-driven; we're confirming the type fix didn't break it)
7. **Workflows**: Run a guided workflow (e.g. "Recession Prep") and verify the workflow progress bar uses the correct labels at each step
8. **State persistence**: Run a tool, navigate away, come back — verify state persistence still works (`useScenarioRouterState` is unchanged)

### Codex post-implementation diff review
Per the standard workflow (`docs/standards/SCENARIO_TOOL_AUDIT_PLAYBOOK.md` Step 5a), send the full diff to Codex for review before commit. Specifically watch for:
- Stale references to the old `SelectableScenarioTool` alias
- Any consumer that still hard-codes a tool list outside the registry
- Type narrowing issues at the `ScenarioRouteId` ↔ `ScenarioToolId` boundary
- AppSidebar `'landing'` flow still type-checks end-to-end
- `ScenariosRouter.tsx` `import './registry';` is present and not removed by an unused-import lint rule (the import is intentional side-effect — bundler will preserve it because there's no `import name from`)
- Landing card order in the rendered UI matches the order before the refactor
