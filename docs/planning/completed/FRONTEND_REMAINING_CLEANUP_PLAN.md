# Frontend Remaining Cleanup Plan

**Date**: 2026-02-24
**Status**: Complete (Codex review — 3 rounds, 2 high / 3 medium findings, all addressed)
**Risk**: Low — config changes, dead code deletion, mechanical lint fixes
**Prerequisite**: Frontend three-package split + wrapper cleanup (complete)

## Context

The frontend three-package split is complete (`@risk/chassis`, `@risk/connectors`, `@risk/ui`). Four cleanup items were identified in TODO.md. After investigation:

- **ESLint boundary enforcement** — Already done. `.eslintrc.js` lines 84-99 already have `no-restricted-imports` rules preventing chassis→connectors/ui and connectors→ui imports. No work needed.
- **Three remaining items** need work: legacy archive deletion, typecheck fix, and lint warning reduction.

## Changes

### 1. Delete `frontend/archive/legacy/` (~10.8K LOC)

No code imports from this directory (verified with `rg "from.*archive/legacy" frontend/`). The README inside confirms these are deprecated components preserved for reference only. The modern UI is fully operational via `App.tsx → AppOrchestratorModern → ModernDashboardApp`.

- Delete entire `frontend/archive/` directory (only contains `legacy/`)
- Clean up stale references in comments/docs:
  - `frontend/packages/ui/src/router/AppOrchestratorModern.tsx` — remove legacy path comments
  - `frontend/README.md` — update architecture section
  - `frontend/packages/ui/src/ARCHITECTURE.md` — update references
- **Scope:** ~55 files deleted, 3 files updated (comments only)

### 2. Fix `pnpm typecheck` (TS6310 + TS5055 errors)

**Problem:** The current script `tsc -b --noEmit` fails with 3 TS6310 errors because `--noEmit` conflicts with `composite: true` in project references. A naive fix of just `tsc -b` causes TS5055 overwrite errors on 3 `.js` files and emits `.js` into `src/` (because `allowJs: true` + `composite: true` + no `outDir`).

**Fix — 3 parts:**

#### 2a. Delete stale `.js` files

`.ts` versions already exist for all 3 files. Just delete the `.js` duplicates:

- Delete `packages/ui/src/reportWebVitals.js` (`.ts` already exists)
- Delete `packages/ui/src/setupTests.js` (`.ts` already exists)
- Delete `packages/ui/src/components/dashboard/shared/ui/index.js` (`.ts` already exists)

#### 2b. Add `emitDeclarationOnly` + `declarationDir` to each package tsconfig

`emitDeclarationOnly: true` prevents `.js` emit (Vite handles bundling). `declarationDir: "dist"` keeps `.d.ts` out of source directories. This avoids both TS5055 and `.d.ts` pollution in `src/`, and avoids needing to gitignore `.d.ts` in `src/` (which would hide the hand-written `snaptrade-react.d.ts`).

```jsonc
// packages/chassis/tsconfig.json, connectors/tsconfig.json, ui/tsconfig.json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "rootDir": "src",
    "composite": true,
    "emitDeclarationOnly": true,
    "declarationDir": "dist",
    "tsBuildInfoFile": "dist/tsconfig.tsbuildinfo"
  },
  // references and include unchanged
}
```

#### 2c. Update `package.json` + `.gitignore`

```diff
- "typecheck": "tsc -b --noEmit"
+ "typecheck": "tsc -b"
```

Add to `frontend/.gitignore`:
```
# TypeScript build artifacts (project references)
packages/*/dist/
```

**Files:**
- `frontend/packages/ui/src/reportWebVitals.js` — delete (`.ts` exists)
- `frontend/packages/ui/src/setupTests.js` — delete (`.ts` exists)
- `frontend/packages/ui/src/components/dashboard/shared/ui/index.js` — delete (`.ts` exists)
- `frontend/packages/chassis/tsconfig.json` — add `emitDeclarationOnly`, `declarationDir`, `tsBuildInfoFile`
- `frontend/packages/connectors/tsconfig.json` — add `emitDeclarationOnly`, `declarationDir`, `tsBuildInfoFile`
- `frontend/packages/ui/tsconfig.json` — add `emitDeclarationOnly`, `declarationDir`, `tsBuildInfoFile`
- `frontend/package.json` — change typecheck script
- `frontend/.gitignore` — add `packages/*/dist/`

**Note:** Pre-existing TS errors (TS2305, TS7006, etc.) may remain after this fix. The goal is to fix the config issues (TS6310/TS5055), not achieve 0 TS errors. Pre-existing type errors are a separate effort.

### 3. Reduce ESLint warnings (1,850 → target ~700)

Current warning breakdown (0 errors, ~1,850 warnings). Top categories:

| Count | Rule | Category |
|-------|------|----------|
| 587 | `@typescript-eslint/no-explicit-any` | TypeScript |
| 298 | `@typescript-eslint/no-unused-vars` | TypeScript |
| ~843 | Various `jsdoc/*` rules | JSDoc |
| 50 | `no-console` | Console |
| 29 | `react/no-array-index-key` | React |
| 22 | `react-hooks/exhaustive-deps` | React Hooks |

#### Step A — Auto-fix (~400 warnings)

Run `pnpm lint --fix`. Handles JSDoc whitespace/formatting (`tag-lines`, `no-types`, `check-tag-names` partial).

#### Step B — Turn off low-value JSDoc rules globally (~300+ warnings)

The JSDoc plugin was added during the ESLint migration as aspirational. For a codebase that never had JSDoc conventions, these rules create noise without value.

**Global rules (turn off in `.eslintrc.js`):**
- `jsdoc/require-jsdoc`: `'off'`
- `jsdoc/require-param`: `'off'`
- `jsdoc/require-returns`: `'off'`
- `jsdoc/require-description`: `'off'`
- `jsdoc/check-types`: `'off'`
- `jsdoc/check-tag-names`: `'off'`

**Keep strict for chassis/services** (via existing override at `packages/chassis/src/services/**`):
- `jsdoc/require-jsdoc`: `'error'`
- `jsdoc/require-description`: `'error'`
- `jsdoc/require-param`: `'error'`
- `jsdoc/require-returns`: `'error'`
- `jsdoc/check-tag-names`: `'error'` ← add explicitly so it's not lost when disabled globally

#### Step C — Remove unused vars (298 warnings)

Targeted pass through lint output, removing dead imports and variables left over from the package split.

#### Not changing (leave as warn):
- `@typescript-eslint/no-explicit-any` (587) — real tech debt, separate effort
- `react-hooks/exhaustive-deps` (22) — each needs manual judgment
- `no-console` (50) — good awareness signal for production code
- `react/no-array-index-key` (29) — legitimate warnings about fragile list rendering

**Files:**
- `frontend/.eslintrc.js` — rule adjustments + chassis/services override update
- Various source files — auto-fix changes + unused var cleanup

## Execution Order

1. Delete `frontend/archive/` directory
2. Clean up stale legacy references in comments/docs
3. Delete 3 stale `.js` files (`.ts` versions already exist)
4. Add `emitDeclarationOnly`/`declarationDir`/`tsBuildInfoFile` to each package tsconfig
5. Fix typecheck script in `package.json` + update `.gitignore`
6. Run `tsc -b --clean` then `pnpm typecheck` — verify TS6310/TS5055 are gone
7. Run `pnpm lint --fix` — auto-fix warnings
8. Adjust JSDoc rules in `.eslintrc.js`
9. Clean up unused vars (manual pass)
10. Run `pnpm lint` — verify final warning count
11. Run `pnpm build` — verify nothing broke

## Verification

1. `pnpm build` — passes (all three packages compile)
2. `pnpm typecheck` — TS6310 and TS5055 errors gone (pre-existing TS errors may remain)
3. `pnpm lint` — 0 errors, ~700 warnings (down from 1,850)
4. `pnpm dev` — dev server starts
5. No `.d.ts` or `.js` emit in `packages/*/src/` (only in `packages/*/dist/`)
6. `snaptrade-react.d.ts` still tracked by git (not ignored)

## Out of Scope

- **Fixing `no-explicit-any` warnings** (587) — requires manual type annotation, separate effort
- **Fixing `exhaustive-deps` warnings** (22) — each needs manual judgment
- **ESLint 9 flat config migration** — ESLint 8 works fine, migrate when needed
- **Fixing pre-existing TS type errors** (TS2305, TS7006, etc.) — separate effort
