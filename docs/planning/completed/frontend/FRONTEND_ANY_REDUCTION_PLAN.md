# Frontend `no-explicit-any` Warning Reduction Plan

**Date**: 2026-02-25
**Status**: Complete — 590→194 (67% reduction), committed as 1f1cb7e6
**Risk**: Low — type-level only changes, no runtime behavior changes
**Prerequisite**: Frontend TypeScript cleanup (complete — 0 TS errors)
**Codex review**: 3 rounds — addressed dynamic-access exclusions, `as any` assertions, verification accuracy

## Context

The frontend has 590 `@typescript-eslint/no-explicit-any` warnings across the three packages. These are real tech debt — `any` bypasses TypeScript's type system, hiding bugs and making refactoring unsafe. This plan reduces them through safe, mechanical conversions.

Current lint baseline: **704 total warnings**, of which **590 are `no-explicit-any`**.

### Current breakdown by package

| Package | `no-explicit-any` count |
|---------|------------------------|
| `@risk/chassis` | 129 |
| `@risk/connectors` | 246 |
| `@risk/ui` | 215 |
| **Total** | **590** |

Additionally, there are **~180 `as any` assertion casts** across the codebase that also trigger `no-explicit-any`.

## Strategy

### Tier 1 — `any` → `unknown` (~150 fixes, safest)

Convert `any` to `unknown` where the value is genuinely untyped and the code doesn't access properties on it directly. This is the safest conversion because `unknown` forces callers to narrow the type before use.

**Patterns to convert:**
- Function params typed as `any` where the body only passes them through (no property access): `(data: any)` → `(data: unknown)`
- Catch clauses: `catch (e: any)` → `catch (e: unknown)` then add `e instanceof Error` guard before accessing `.message` (this is a minimal runtime-safe narrowing check, not a behavioral change)
- Generic containers where values aren't accessed with known keys: `Record<string, any>` → `Record<string, unknown>`
- Array types where elements are opaque: `any[]` → `unknown[]`
- Event handler data params: `(data: any)` → `(data: unknown)` in callbacks/event emitters
- Generic Promise/Map types: `Promise<any>` → `Promise<unknown>`, `Map<K, any>` → `Map<K, unknown>` where the resolved value isn't destructured
- State variables holding opaque data: `useState<any>()` → `useState<unknown>()` where value is only passed through

**Do NOT apply Tier 1 in these files** (deep property access on `any`-typed values — `unknown` would require downstream casts). These are Tier 2 candidates only (add real types) or leave as-is:
- `packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` — `(stockData as any).…` pattern
- `packages/ui/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx` — optimization payload access
- `packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` — deep payload traversal
- `packages/connectors/src/adapters/RiskAnalysisAdapter.ts` — dynamic response object access
- `packages/connectors/src/adapters/RiskSettingsAdapter.ts` — dynamic object access
- `packages/connectors/src/managers/PortfolioManager.ts` — dynamic object access
- `packages/ui/src/components/dashboard/shared/charts/adapters/chartDataAdapters.ts` — dynamic chart data access
- Any other file where converting `any` → `unknown` would require adding `as any` or `as unknown as T` elsewhere

### Tier 2 — Add real types (~50 fixes, moderate)

Where the actual type is obvious from usage context, replace `any` with the correct type. Only use **existing** types/interfaces — create new local interfaces only when the type is used in 3+ places in the same file.

**Patterns to convert:**
- React event handlers: `(e: any)` → `(e: React.ChangeEvent<HTMLInputElement>)`, `(e: React.MouseEvent)`, etc.
- API response data where existing schemas/interfaces exist (check `packages/connectors/src/schemas/api-schemas.ts` and adapter data types, but note coverage is partial — many fields are `z.any()`)
- Function params where the body accesses specific properties and a matching interface already exists
- React component props typed as `any` where the prop shape is clear from JSX usage

### Not fixing (leave as `any`)

- Third-party library interop where upstream types are `any` (e.g., Radix primitives, TanStack Query data)
- Deep adapter/transformer chains where fixing one `any` requires threading types through 5+ functions
- Complex generic utility types that would require significant refactoring
- Dynamic-access files listed in the Tier 1 exclusions above
- Existing `as any` assertion casts (~180) — these require case-by-case analysis and proper typing, not bulk conversion. Leave for a future pass.
- Index signatures (`[key: string]: any`) in flexible data structures
- Cases where converting to `unknown` would require adding `as any` casts downstream — the cure is worse than the disease

## Execution

Process by package, smallest first:

### 1. `packages/chassis/src/` (129 warnings)
- Services: API client response types, cache service data types, event bus payloads
- Types: shared type definitions that use `any` for flexibility
- Utils: cache config, adapter registry

### 2. `packages/connectors/src/` (246 warnings)
- Adapters: API response transformers — skip deep-access files listed above
- Hooks: TanStack Query data types, callback params
- Schemas: API schema definitions (leave `z.any()` as-is — these are intentionally flexible)
- Managers: portfolio/risk settings manager method params — skip PortfolioManager dynamic access

### 3. `packages/ui/src/` (215 warnings)
- Components: event handlers, prop types, render data — skip StockLookup/StrategyBuilder containers
- Charts: data adapter functions
- Pages: state management types

## Guardrails

1. **No new `as any` casts** — if converting `any` → `unknown` requires adding `as any` elsewhere, leave it as `any`
2. **No `as unknown as T` chains** — these are just disguised `any` casts
3. **No runtime behavior changes** — all fixes must be type-level only (type annotations, generics, type imports). Exception: adding `instanceof Error` guards in catch clauses is allowed — this is a safe narrowing check, not a behavioral change.
4. **Preserve API compatibility** — exported function signatures should remain compatible (widening params from `any` to `unknown` is safe; narrowing is not)
5. **New type definitions only when justified** — create a local interface only when the same shape appears 3+ times in the same file. Otherwise use inline types or `unknown`.
6. **Skip, don't force** — if a conversion isn't clean and obvious, skip it. Better to leave `any` than introduce fragile type workarounds.

## Verification

All commands run from the `frontend/` directory:

1. `pnpm build` — passes
2. `pnpm typecheck` — 0 errors (no regressions from type changes)
3. `pnpm lint` — 0 errors, warning count reduced (target: ~520, down from 704). Conservative estimate given expanded Tier 1 exclusion list.
4. `rg -o "as any" packages/*/src/ --no-filename | wc -l` — should not increase from current baseline (~180 occurrences). Use `rg -o` for accurate token-level counting (line-counting with `grep | wc -l` undercounts when multiple casts appear on one line).
5. No new files created — all changes are in existing files
