# F147 PR-1 — Foundation Types + Thesis Scaffolding (Implementation Plan)

**Status:** CODEX PASS R5 — ready for implementation in parallel with PR-0.
**Created:** 2026-05-25. **Revised:** 2026-05-25 (R4 → R5).

**R4 → R5 changelog:**
- **B1 (`ArtifactRenderer<unknown>` rejects concrete renderers under strict mode):** Per TS `strictFunctionTypes`, `ArtifactRenderer<unknown>` is not a supertype of `ArtifactRenderer<FooProps>` (function parameter contravariance). Added `AnyArtifactRenderer = ArtifactRenderer<never>` for heterogeneous dispatch storage. `THESIS_RENDERER_DISPATCH: Partial<Record<string, AnyArtifactRenderer>>`. Documented contained cast inside `renderThesisArtifact`.
- **NB1:** Metadata stale R3 → R4 — updated to R5.
- **NB2:** §7 review brief stale `propsOrNull` description swept.

---

**R3 → R4 changelog:**
- B1 (residual any in §2 index.ts row): Fixed — row now describes re-export pattern from types.ts.
- B2 (unused import in index.ts snippet): Cleaned — only imports types actually used.
- NB1: Duplicate "R1 → R2 changelog" header removed.

---

**R2 → R3 changelog:**
- **B1 (`any` types fail project lint):** Replaced `any` with `unknown`/`never` per project's `@typescript-eslint/no-explicit-any: warn` + `--max-warnings=0` enforcement. `AnyArtifactDescriptor = ArtifactDescriptor<never, unknown, unknown>`.
- **NB1 (test count drift):** Swept — 21 tests throughout.
- **NB2 (§2 file table vs §3.5 inconsistency):** §2 file-diff row for `registry.ts` clarified.

---

**R1 → R2 changelog:**
- **B1 (backward-compat import break):** `registry.ts` keeps `ArtifactDescriptor` as a specialized alias (`= BaseArtifactDescriptor<OverviewArtifactBuilderContext, GeneratedArtifactProps, GeneratedArtifactProps | null>`) so existing unparameterized imports at `PortfolioOverviewContainer.tsx:66` keep working without code change.
- **B2 (skeleton references PR-0 types):** `ThesisArtifactBuilderContext` skeleton uses placeholder types (`unknown` / `unknown | null`) instead of PR-0 types. PR-2 replaces placeholders with real types when PR-0 has landed. Keeps PR-1 compile-independent of PR-0.
- **NB1 (`propsOrNull` overly permissive):** Guards specific BuilderResult statuses (`ready` / `partial` / `empty` / `loading` / `error`) — not just `'status' in result`. Test added for "legacy props object with unrelated status field passes through."
- **NB2 (`ThesisArtifactBuilderContext` ownership inconsistent):** Defined in `thesis/useThesisArtifactContext.ts` only; type-only import from `thesis-registry.ts`.
- **NB3 (`AnyArtifactDescriptor` duplicate):** Defined in `types.ts`; re-exported from `index.ts`.
**Owner:** Henry.
**Per CLAUDE.md plan-first workflow:** Codex review → PASS → impl via Codex.

**Parent docs (read first):**
- Spec: `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md` (R7 CODEX PASS)
- Umbrella: `docs/planning/F147_IMPL_PLAN.md`
- Companion PR plan: `docs/planning/F147_PR0_IMPL_PLAN.md` (ships parallel)

---

## 1. Goal

Ship the type system + thesis-side scaffolding that PR-2+ entries will populate. **No behavior change** for shipped overview entries. Ships **parallel to PR-0** since it's substrate-independent.

What this PR ships:
1. 3-generic `ArtifactDescriptor<Context, Props, R>` parameterized type
2. `BuilderResult<Props>` discriminated union
3. Supporting types: `RenderContext`, `ArtifactRenderer<P>`, `AnyArtifactDescriptor`, `propsOrNull` adapter
4. Central registry index (`getArtifactDescriptor`, `getAllArtifactIds`, `AnyArtifactDescriptor`)
5. Empty thesis-side scaffolding (`thesis-registry.ts`, `thesis-dispatch.tsx`, `useThesisArtifactContext.ts` skeleton)

**Out of scope:** Overview migration to `BuilderResult` — deferred to PR-1b (separate impl plan, follow-up).

---

## 2. File diffs

| File | Action | Description |
|---|---|---|
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/types.ts` | EXTEND | Add: `BuilderResult<Props>` discriminated union (`ready \| partial \| empty \| loading \| error` variants); `isRenderable<P>(result): bool` type guard; `RenderContext` interface; `ArtifactRenderer<P>` type. Widen `ArtifactDescriptor` to `<Context, Props, R = BuilderResult<Props>>` — `R` defaults to BuilderResult; overview specializes to `GeneratedArtifactProps \| null`. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` | EXTEND (type-only) | Add specialized alias `export type ArtifactDescriptor = BaseArtifactDescriptor<OverviewArtifactBuilderContext, GeneratedArtifactProps, GeneratedArtifactProps \| null>` (per R1 B1 — preserves backward-compat for unparameterized imports at `PortfolioOverviewContainer.tsx:66`). Then `OVERVIEW_ARTIFACT_REGISTRY: readonly ArtifactDescriptor[]` keeps its existing shape. See §3.5 for the exact alias pattern. Builder functions unchanged. Same byte output for all 7 builders. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis-registry.ts` | NEW | Export empty `THESIS_ARTIFACT_REGISTRY: readonly ArtifactDescriptor<ThesisArtifactBuilderContext, unknown, BuilderResult<unknown>>[] = []`. Filled in PR-2+. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis-dispatch.tsx` | NEW | Export empty `THESIS_RENDERER_DISPATCH: Partial<Record<string, AnyArtifactRenderer>> = {}` (uses `AnyArtifactRenderer = ArtifactRenderer<never>` per R4 B1 — `ArtifactRenderer<unknown>` fails under TS `strictFunctionTypes`) + `renderThesisArtifact(id, result, ctx)` function with contained cast. Filled in PR-2+. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/index.ts` | NEW | Re-export `AnyArtifactDescriptor` from `./types` (single source per R1 NB3 + R2 B1 — declared as `ArtifactDescriptor<never, unknown, unknown>` in types.ts). Export `REGISTRIES` map (`{ overview: OVERVIEW_ARTIFACT_REGISTRY, thesis: THESIS_ARTIFACT_REGISTRY }`). Export `getArtifactDescriptor(id): AnyArtifactDescriptor \| null`. Export `getAllArtifactIds(): readonly string[]`. Export `propsOrNull<P>(result: P \| null \| BuilderResult<P>): P \| null` adapter with runtime guard. See §3.7 for full snippet. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis/useThesisArtifactContext.ts` | NEW (skeleton) | Export `ThesisArtifactBuilderContext` interface (initial fields: `ticker`, `thesis`, `artifactReady`, `positions`, `loadingStates`). Export skeleton `useThesisArtifactContext(ticker: string)` returning the interface — fills out as entries land in PR-2+. |

---

## 3. Type definitions

### 3.1 `BuilderResult<Props>` (in `types.ts`)

```ts
export type BuilderResult<Props> =
  | { status: 'ready'; props: Props }
  | { status: 'partial'; props: Props; missingSources: string[]; reason?: string }
  | { status: 'empty'; reason?: string; affordance?: { skillName: string; label: string } }
  | { status: 'loading'; sources?: string[] }
  | { status: 'error'; reason: string; sources?: string[] };

export function isRenderable<P>(
  result: BuilderResult<P>
): result is Extract<BuilderResult<P>, { props: P }> {
  return result.status === 'ready' || result.status === 'partial';
}
```

### 3.2 `ArtifactDescriptor<C, P, R>` (extend in `types.ts`)

Per R1 NB3: `AnyArtifactDescriptor` defined here in `types.ts` only; re-exported from `index.ts`.

```ts
export interface ArtifactDescriptor<Context = unknown, Props = unknown, R = BuilderResult<Props>> {
  id: string;
  label: string;
  builderRef: string;
  requiresHooks: string[];
  builder: (context: Context) => R;
}

// AnyArtifactDescriptor — single source. Uses unknown/never (NOT any) per R2 B1
// to satisfy project's @typescript-eslint/no-explicit-any: warn + --max-warnings=0.
// Re-exported from index.ts.
export type AnyArtifactDescriptor = ArtifactDescriptor<never, unknown, unknown>;
```

### 3.3 `RenderContext` + `ArtifactRenderer<P>` (in `types.ts`)

```ts
export interface RenderContext {
  onSendMessage?: (message: string) => void;
  onNavigate?: (view: string) => void;
  adjacentArtifacts?: Record<string, BuilderResult<unknown>>;
  affordances?: { runSkill?: (skillName: string) => void };
}

export type ArtifactRenderer<Props = unknown> = (
  result: BuilderResult<Props>,
  ctx: RenderContext
) => React.ReactElement | null;

// AnyArtifactRenderer — erased renderer alias for heterogeneous dispatch storage.
// `ArtifactRenderer<unknown>` does NOT accept `ArtifactRenderer<FooProps>` under
// TS strictFunctionTypes (function-parameter contravariance). Using `never` props
// makes the assignment legal at the dispatch-map level; per-entry calls cast
// internally inside renderThesisArtifact.
export type AnyArtifactRenderer = ArtifactRenderer<never>;
```

Dispatch usage (in `thesis-dispatch.tsx`):

```ts
import type { AnyArtifactRenderer, ArtifactRenderer, BuilderResult, RenderContext } from './types';

export const THESIS_RENDERER_DISPATCH: Partial<Record<string, AnyArtifactRenderer>> = {};

export function renderThesisArtifact(
  id: string,
  result: BuilderResult<unknown>,
  ctx: RenderContext
): React.ReactElement | null {
  const renderer = THESIS_RENDERER_DISPATCH[id];
  if (!renderer) return null;
  // Contained cast — entries register their concrete renderer; the dispatch
  // map stores them as erased `<never>` for heterogeneous storage. At call
  // time we re-widen to the unknown-typed result the consumer passes in.
  return (renderer as ArtifactRenderer<unknown>)(result, ctx);
}
```

### 3.4 `propsOrNull` (in `index.ts`)

Per R1 NB1: guards specific BuilderResult statuses (not just `'status' in result`) so legacy props with unrelated `status` fields aren't mistakenly treated as BuilderResults.

```ts
const BUILDER_RESULT_STATUSES = new Set(['ready', 'partial', 'empty', 'loading', 'error'] as const);

export function propsOrNull<P>(result: P | null | BuilderResult<P>): P | null {
  if (result === null || result === undefined) return null;
  // Recognize BuilderResult shape only when status is one of the 5 known variants
  if (
    typeof result === 'object' &&
    result !== null &&
    'status' in result &&
    typeof (result as { status: unknown }).status === 'string' &&
    BUILDER_RESULT_STATUSES.has((result as { status: string }).status as 'ready' | 'partial' | 'empty' | 'loading' | 'error')
  ) {
    const r = result as BuilderResult<P>;
    if (r.status === 'ready' || r.status === 'partial') return r.props;
    return null;
  }
  // Legacy props (including props that happen to have an unrelated `status` field)
  return result as P;
}
```

### 3.5 `OVERVIEW_ARTIFACT_REGISTRY` (type alias in `registry.ts` — preserves backward-compat imports per R1 B1)

```ts
// registry.ts (PR-1)
import type { ArtifactDescriptor as BaseArtifactDescriptor } from './types';

// PR-1 B1 fix: keep the locally-exported ArtifactDescriptor name as a SPECIALIZED ALIAS.
// Existing consumers (e.g., PortfolioOverviewContainer.tsx:66) import unparameterized
// `ArtifactDescriptor` from this file and rely on the legacy `Props | null` return type.
// Aliasing preserves that behavior without forcing every consumer to update imports.
export type ArtifactDescriptor = BaseArtifactDescriptor<
  OverviewArtifactBuilderContext,
  GeneratedArtifactProps,
  GeneratedArtifactProps | null
>;

export const OVERVIEW_ARTIFACT_REGISTRY: readonly ArtifactDescriptor[] = [
  // SAME 7 entries, SAME builders, SAME byte output as shipped
];
```

### 3.6 `THESIS_ARTIFACT_REGISTRY` (NEW empty) + `ThesisArtifactBuilderContext`

Per R1 B2: PR-1 ships compile-independent of PR-0. Skeleton uses placeholder types — PR-2 replaces with real types once PR-0 has landed (or in parallel if both ship together).

`ThesisArtifactBuilderContext` lives in `thesis/useThesisArtifactContext.ts` (single source per R1 NB2); `thesis-registry.ts` type-only imports it.

```ts
// thesis/useThesisArtifactContext.ts (skeleton)
export interface ThesisArtifactBuilderContext {
  ticker: string;
  // PR-0 types replace these placeholders in PR-2:
  thesis: unknown | null;                              // ThesisSnapshot (PR-0)
  artifactReady: Record<string, unknown | null>;       // ArtifactSidecarPayload (PR-0)
  positions: unknown | null;                           // existing positions type from connectors
  loadingStates: Record<string, 'loading' | 'ready' | 'error'>;
}

// Skeleton hook — implemented in PR-2 after PR-0's hooks exist
export function useThesisArtifactContext(ticker: string): ThesisArtifactBuilderContext {
  return {
    ticker,
    thesis: null,
    artifactReady: {},
    positions: null,
    loadingStates: {},
  };
}
```

```ts
// thesis-registry.ts
import type { ArtifactDescriptor, BuilderResult } from './types';
import type { ThesisArtifactBuilderContext } from './thesis/useThesisArtifactContext';

export const THESIS_ARTIFACT_REGISTRY: readonly ArtifactDescriptor<
  ThesisArtifactBuilderContext,
  unknown,
  BuilderResult<unknown>
>[] = [];  // Empty in PR-1; PR-2 adds first entry
```

### 3.7 Central index (`index.ts`)

```ts
// Local imports — only types actually USED in this file's logic (avoids
// @typescript-eslint/no-unused-vars per R2 lint policy).
import { OVERVIEW_ARTIFACT_REGISTRY } from './registry';
import { THESIS_ARTIFACT_REGISTRY } from './thesis-registry';
import type { BuilderResult, AnyArtifactDescriptor } from './types';

export const REGISTRIES: Record<string, readonly AnyArtifactDescriptor[]> = {
  'overview': OVERVIEW_ARTIFACT_REGISTRY,
  'thesis': THESIS_ARTIFACT_REGISTRY,
  // 'advisor', 'plan', 'review' in v1.1
};

export function getArtifactDescriptor(id: string): AnyArtifactDescriptor | null {
  const namespace = id.split('.')[0];
  return REGISTRIES[namespace]?.find((d) => d.id === id) ?? null;
}

export function getAllArtifactIds(): readonly string[] {
  return Object.values(REGISTRIES).flatMap((r) => r.map((d) => d.id));
}

// propsOrNull adapter (see §3.4 for full implementation with runtime guard)
export function propsOrNull<P>(result: P | null | BuilderResult<P>): P | null { /* ... */ }

// Re-exports for cross-namespace consumers (direct re-exports — don't need
// local imports for these).
export { OVERVIEW_ARTIFACT_REGISTRY, THESIS_ARTIFACT_REGISTRY };
export type { ArtifactDescriptor, BuilderResult, RenderContext, ArtifactRenderer, AnyArtifactRenderer, AnyArtifactDescriptor } from './types';
```

---

## 4. Tests

| # | Test name | File |
|---|---|---|
| 1 | `test_BuilderResult_isRenderable_ready_returns_true` | `artifacts/types.test.ts` |
| 2 | `test_BuilderResult_isRenderable_partial_returns_true` | same |
| 3 | `test_BuilderResult_isRenderable_empty_returns_false` | same |
| 4 | `test_BuilderResult_isRenderable_loading_returns_false` | same |
| 5 | `test_BuilderResult_isRenderable_error_returns_false` | same |
| 6 | `test_OVERVIEW_REGISTRY_compiles_with_widened_descriptor_type` | `artifacts/registry.test.ts` (existing — verify no regression) |
| 7 | `test_OVERVIEW_REGISTRY_byte_equivalent_after_type_widening` | same — render any overview entry and confirm output unchanged |
| 8 | `test_getArtifactDescriptor_returns_overview_concentration` | `artifacts/index.test.ts` |
| 9 | `test_getArtifactDescriptor_unknown_id_returns_null` | same |
| 10 | `test_getArtifactDescriptor_unknown_namespace_returns_null` | same |
| 11 | `test_getAllArtifactIds_includes_overview_ids` | same |
| 12 | `test_getAllArtifactIds_returns_overview_only_in_PR1` (thesis registry empty in PR-1) | same |
| 13 | `test_propsOrNull_passes_through_legacy_props` | same |
| 14 | `test_propsOrNull_returns_props_for_ready_BuilderResult` | same |
| 15 | `test_propsOrNull_returns_props_for_partial_BuilderResult` | same |
| 16 | `test_propsOrNull_returns_null_for_empty_BuilderResult` | same |
| 17 | `test_propsOrNull_returns_null_for_loading_BuilderResult` | same |
| 18 | `test_propsOrNull_returns_null_for_error_BuilderResult` | same |
| 19 | `test_propsOrNull_returns_null_for_input_null` | same |
| 20 | `test_propsOrNull_passes_through_legacy_props_with_unrelated_status_field` (e.g. `{ status: 'active', count: 5 }`) | same |
| 21 | `test_renderThesisArtifact_unknown_id_returns_null` (empty dispatch map in PR-1) | `artifacts/thesis-dispatch.test.tsx` |
| 22 | `test_AnyArtifactRenderer_accepts_concrete_renderer_assignment` (compile-time type test: `const r: AnyArtifactRenderer = (result: BuilderResult<FooProps>, ctx) => ...; const map: Partial<Record<string, AnyArtifactRenderer>> = { 'foo': r };` — locks the R4 B1 variance fix against future regression) | `artifacts/thesis-dispatch.test.tsx` |

---

## 5. Acceptance criteria

1. ✓ `OVERVIEW_ARTIFACT_REGISTRY` type-checks against the new 3-generic signature with `R = GeneratedArtifactProps | null`
2. ✓ All existing overview tests pass — zero behavior change
3. ✓ `getArtifactDescriptor('overview.concentration')` returns the existing descriptor
4. ✓ `propsOrNull` handles all variants correctly (5 BuilderResult variants + legacy null + legacy props)
5. ✓ `THESIS_ARTIFACT_REGISTRY` is empty array; `THESIS_RENDERER_DISPATCH` is empty map
6. ✓ All 22 tests pass
7. ✓ Import compatibility — existing `ArtifactDescriptor` consumers (`registry.ts` + `registry.test.ts`) continue to import from `registry.ts` (re-export preserved)

---

## 6. Codex implementation prompt

When dispatching PR-1 to Codex via `mcp__codex__codex` (after this plan PASSes review):

```
Implement PR-1 for F147 THESIS_ARTIFACT_REGISTRY per the impl plan at:
docs/planning/F147_PR1_IMPL_PLAN.md

Foundation types + thesis-side scaffolding. ZERO behavior change for
shipped overview entries.

Scope (§2): 6 files — 2 EXTENDED (types.ts + registry.ts), 4 NEW
(thesis-registry.ts, thesis-dispatch.tsx, index.ts, useThesisArtifactContext.ts skeleton)

Type definitions: §3 (BuilderResult, ArtifactDescriptor<C,P,R>, RenderContext,
ArtifactRenderer, AnyArtifactDescriptor, propsOrNull)

Tests: §4 (22 tests)
Acceptance: §5

Critical invariants:
- OVERVIEW_ARTIFACT_REGISTRY builders MUST NOT change behavior — only type
  signature widens to include R = GeneratedArtifactProps | null.
- All 7 shipped overview entries: SAME builder code, SAME byte output.
- THESIS_ARTIFACT_REGISTRY ships empty; PR-2 adds first entry.
- BuilderResult discriminated union: 5 variants per §3.1.

Per CLAUDE.md Codex MCP conventions: approval-policy "never",
sandbox "workspace-write", cwd risk_module root.

PR-1 ships PARALLEL to PR-0 — they touch different files, no mutual
dependency. Either can land first.
```

---

## 7. Codex review brief (for this plan)

**Areas to challenge:**

1. **3-generic type ergonomics** — `ArtifactDescriptor<C, P, R = BuilderResult<P>>` — does the default `R` work cleanly for thesis consumers that just write `ArtifactDescriptor<ThesisCtx, FooProps>`? Verify TS inference.
2. **OVERVIEW migration risk** — type widening only; no runtime change. Verify against `PortfolioOverviewContainer.tsx:1685` `renderOverviewArtifactEntry` consumers that they don't break on the wider type.
3. **`propsOrNull` runtime guard** — implementation in §3.4 now checks `result.status` against the known set `{ 'ready', 'partial', 'empty', 'loading', 'error' }` (not just `'status' in result`). Edge: a legacy props object that happens to have `status: 'ready'` would collide. No current `GeneratedArtifactProps` consumers have a top-level `status` field — verify if/when overview migration happens in PR-1b.
4. **Empty `THESIS_ARTIFACT_REGISTRY`** — PR-2 will add the first entry. Is there a test/lint that fails if THESIS registry stays empty too long? (Probably not necessary for PR-1; defer to v1 acceptance.)
5. **Cross-import cycles** — `index.ts` imports from `registry.ts` AND `thesis-registry.ts`. Both are imported elsewhere. Verify no cycles.

**Inputs available for local execution:**
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` (73 lines, 7 entries)
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.test.ts`
- `frontend/packages/ui/src/components/design/GeneratedArtifact.tsx:61` (GeneratedArtifactProps)
- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx:1685` (renderOverviewArtifactEntry)

---

## 8. Open questions

1. **PR-1b scoping** — When overview migration to BuilderResult happens, what tests verify nullable-semantic dependencies at `PortfolioOverviewContainer.tsx:1578, 1685` don't regress? Filed for PR-1b plan, not blocking PR-1.

---

## 9. Definition of done

PR-1 ships when:

1. All 22 tests pass
2. No regression in any existing overview test (incl. `PortfolioOverviewContainer.tsx` compile)
3. `getArtifactDescriptor('overview.concentration')` returns descriptor
4. Codex review of THIS plan — PASS

---

## 10. References

- Spec: `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md` (CODEX PASS R7)
- Umbrella: `docs/planning/F147_IMPL_PLAN.md`
- Companion: `docs/planning/F147_PR0_IMPL_PLAN.md`
- Principles: `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md`
