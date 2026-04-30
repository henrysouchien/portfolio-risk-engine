# Brokerage pyproject layout — converge source and dist

## Status: v1 — DRAFT (filed 2026-04-30 as follow-up to CREDENTIALS_KMS_MIGRATION_PLAN)

## Problem

Source `brokerage/pyproject.toml` and dist `brokerage-connect-dist/pyproject.toml` are deliberately divergent files that share semantic content (deps, extras, python version) but differ in structural content (build backend, package name, license, URLs, location). The sync script `scripts/sync_brokerage_connect.sh:31` excludes `pyproject.toml` from sync to preserve dist-specific publishing metadata.

**Cost surfaced 2026-04-30**: during the credentials KMS migration, Codex updated source `brokerage/pyproject.toml` to drop `boto3>=1.42,<2`, `botocore>=1.42,<2` from the `snaptrade` and `plaid` extras. The change did not propagate to dist (because of the sync exclude). Codex R5 review caught it; otherwise the published `brokerage-connect` 0.3.0 wheel would have advertised boto3 dependencies it doesn't need. Manual edits to the dist pyproject at release time are the only correction path — easy to forget.

This will keep happening. Any extras change, dependency upgrade, or python-version bump has to be manually mirrored across both files. The default outcome is silent drift.

## Why divergent today

The layouts genuinely differ:

| | Path | Package layout |
|---|---|---|
| Source | `risk_module/brokerage/pyproject.toml` | pyproject lives **inside** the package directory; uses `setuptools` with `[tool.setuptools.packages.find] where = [".."], include = ["brokerage*"]` to package the directory it's in |
| Dist | `brokerage-connect-dist/pyproject.toml` | pyproject at **repo root**; package at `brokerage/` subdir; uses `hatchling` with `packages = ["brokerage"]` |

The build directives can't be the same file content because they describe different filesystem positions. Naming, license, and URLs also differ between monorepo-internal use and the published package.

## Options

### Option 1 — Restructure source layout to mirror dist (RECOMMENDED)

Move source from `risk_module/brokerage/{pyproject.toml, plaid/, snaptrade/, ...}` to `risk_module/brokerage-connect/{pyproject.toml, brokerage/{plaid/, snaptrade/, ...}}`. Source layout then matches dist 1:1 and `pyproject.toml` can sync cleanly.

**Pros:**
- Single source of truth. Deps/extras/version all sync automatically.
- `from brokerage import ...` continues to work (PYTHONPATH update only — package is still named `brokerage`).
- Sync script becomes trivial: `rsync brokerage-connect/ brokerage-connect-dist/`.
- Standard monorepo pattern (sub-package in its own dir with its own pyproject).

**Cons / scope:**
- Touches `PYTHONPATH` (or whatever wires brokerage into risk_module's Python path).
- Touches `scripts/sync_brokerage_connect.sh` (different source dir).
- Touches IDE configs, mypy/pyright configs, test runners, CI scripts.
- Potentially touches CLAUDE.md's "Package Development — Local-First Rule" table (path entry).
- Estimated: ~couple hours of careful refactor + verification.

### Option 2 — Sync-helper that merges only `[project.optional-dependencies]`

Keep source/dist locations as-is. Add a script that reads source pyproject, extracts `[project.optional-dependencies]`, and rewrites that section in dist pyproject. Run as part of `sync_brokerage_connect.sh`.

**Pros:**
- No layout change; risk is local to the sync script.
- ~30 min implementation.

**Cons:**
- Doesn't cover version (still manual at release).
- Doesn't cover `requires-python` or top-level `dependencies` (could extend, but each addition is more script).
- Two pyprojects continue to exist; the bug surface is just narrower.

### Option 3 — Post-sync drift check

Cheapest. After `sync_brokerage_connect.sh` runs, diff source vs dist `[project.optional-dependencies]` and emit a warning if they differ. Doesn't auto-correct; just makes silent drift loud.

**Pros:**
- ~10 min, no architecture change.
- Warns at the point of release prep, before publish.

**Cons:**
- Doesn't fix the drift; just surfaces it.
- Still requires manual edit to resolve.

## Recommendation

**Option 1** is the right architectural fix. It eliminates the class of bug entirely and matches the standard monorepo sub-package pattern.

Order of operations if scheduled:
1. Move `risk_module/brokerage/` → `risk_module/brokerage-connect/brokerage/`
2. Update `PYTHONPATH` / `sys.path` references (likely a few entry points + tests)
3. Update `scripts/sync_brokerage_connect.sh` source path
4. Drop the `--exclude='pyproject.toml'` from sync script
5. Make source pyproject equal to dist pyproject (adopt published name, license, URLs, hatchling backend)
6. Update `CLAUDE.md` package table entry
7. Re-run sync; verify standalone import still works in dist
8. Verify monorepo tests still pass
9. Bump dist version, publish

Until scheduled, the **2026-04-30 release** carries:
- Source pyproject already cleaned (boto removed).
- Dist pyproject manually edited at release time (version 0.2.2 → 0.3.0; boto removed from extras).

## Open questions

- Does `risk_module` import `brokerage` via repo-root `sys.path` (which would just need adjustment) or via an editable install (which would need the install command updated)?
- Are there CI / deploy scripts that reference `brokerage/` paths explicitly? (Grep before scheduling.)
- Does the move affect any IDE workspace or `.vscode/settings.json` Python paths?

## Out of scope

- Full publishing pipeline (PyPI release automation) — separate concern.
- Source `brokerage/` package name change (stays `brokerage`).
- Dist license / URL changes (stay as-is).

## Decisions log

- **2026-04-30** — Option 1 recommended over 2/3. Surfaced during credentials KMS migration when boto3 cleanup didn't propagate to dist. Filed as follow-up rather than blocking the credentials release.
