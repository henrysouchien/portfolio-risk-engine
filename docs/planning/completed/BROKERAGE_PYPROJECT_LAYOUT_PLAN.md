# Brokerage pyproject layout — converge source and dist

## Status: v6 — **SHIPPED 2026-04-30**. Layout converged, source/dist pyproject byte-identical (modulo dist's PolyForm LICENSE excluded from sync), `brokerage-connect 0.3.0` published to PyPI, drift class eliminated. Plan history v1-v5 below preserved for context. Concrete step sequence in §Implementation.

## Ship Summary

**PyPI:** https://pypi.org/project/brokerage-connect/0.3.0/ (was 0.2.2; 0.3.0 captures boto3 cleanup + layout convergence in one release).

**Source-repo commits on origin/main:**
- `94fb0432` `refactor(brokerage): mirror brokerage-connect layout` — the move + README convergence + pyproject rewrite.
- `703f97aa` `chore(brokerage): wire editable install and sync script` — `scripts/deploy.sh` editable install, sync script rewrite with explicit excludes.
- `b791805e` `chore(brokerage): update nested layout references` — `_lint.py`, `rule_b_baseline.json`, `seed_reference_data.py`, test path constructions, active markdown docs, CLAUDE.md table row.
- `c271dfc8` `chore(brokerage): set PYTHONPATH for local services-mcp runtime` — services.yaml `env: PYTHONPATH: brokerage-connect` on all 6 Python services + DEVELOPER_ONBOARDING.md note. Surfaced after end-to-end testing showed the dev runtime path the v5 plan didn't cover.
- `ae4b8259` `chore(brokerage): add publish_brokerage_connect.sh + register in deploy checklist` — new `scripts/publish_brokerage_connect.sh` mirroring `publish_fmp_mcp.sh`; PACKAGE_DEPLOY_CHECKLIST.md two new rows.

**Dist-repo commit:** `d01e2633` `sync: update from source repo` (in `~/Documents/Jupyter/brokerage-connect-dist/`).

**Verification:**
- `/api/positions/holdings` and `/api/snaptrade/connections` returned HTTP 200 after restart.
- Pytest baseline: 39 failed → 36 failed (3 fewer real failures; 6 "new" failures were all test-order pollution that pass in isolation, surfaced by parallel session's connection_status repairs).
- Step 9 clean-install smoke (build wheel + install in throwaway venv): `OK BrokerAdapter`.
- `python3 -m pip index versions brokerage-connect` lists 0.3.0.

**Known followups (NOT this PR):**
- **Compatibility shim (intentional, load-bearing):** `brokerage/__init__.py` (45 lines) at repo root is a namespace-package shim added in commit `cfe74259` "Fix test suite drift and import boundaries" by a parallel session the night of the ship, then verified necessary 2026-05-01. It uses `__path__.insert(0, "brokerage-connect/brokerage")` to redirect submodule resolution to the moved package and re-exports the public API (diff-clean against `brokerage-connect/brokerage/__init__.py`). Removing it breaks pytest collection on `tests/brokerage/` because pytest's collection-time imports don't reliably benefit from the editable-install pth — the shim restores CWD-relative resolution. Sits as the first layer of `import brokerage` resolution; the editable install + services.yaml `env: PYTHONPATH: brokerage-connect` + `.env` shim cover other invocation paths. Belt-and-suspenders by design.
- `brokerage-connect` published wheel still has hidden monorepo deps via `brokerage.config` (imports `ibkr.config`) and `brokerage.futures` (imports yaml, pandas) — pre-existing in 0.2.2, carry-forward decision per v3 review. Separate plan if/when we want clean-installable subpackages.

**Drift class eliminated:** future dependency / version / extras edits to `brokerage-connect/pyproject.toml` will sync byte-identically to dist via `./scripts/sync_brokerage_connect.sh`. The `--exclude='pyproject.toml'` carve-out is gone.

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

## Recommendation (locked)

**Option 1** — restructure source to mirror dist. This eliminates the drift class entirely and matches the standard monorepo sub-package pattern. v2 also introduces a real consistency cost worth naming up front (see §Tradeoffs).

## Resolved open questions (v2)

### Q1 — How is `brokerage` importable today?

**Dev (this repo, .venv):** the editable install of repo-root `pyproject.toml` (which is `fmp-mcp`'s, not `brokerage`'s) creates `.venv/lib/python3.13/site-packages/_editable_impl_fmp_mcp.pth` whose contents are literally the repo root path `/Users/.../risk_module`. That puts repo root on `sys.path` for the venv, so every top-level subdir (`brokerage/`, `ibkr/`, `app_platform/`, `fmp/`, `portfolio_math/`, `portfolio_risk_engine/`, `risk_client/`) resolves as a top-level import. There is **no** editable install of `brokerage` itself, no repo-root `conftest.py`, no `sys.path` manipulation in `app.py`/`mcp_server.py`/Makefile.

**Prod (EC2):** `services.yaml:risk_module` launches uvicorn with CWD = repo root (`/var/www/risk_module/`). Python's default behavior adds CWD to `sys.path`, achieving the same effect as the dev pth file. `requirements.txt` does not reference brokerage.

**Implication:** moving `risk_module/brokerage/` → `risk_module/brokerage-connect/brokerage/` removes `brokerage/` from the repo-root sys.path entry. `import brokerage` will break in both environments unless we add `risk_module/brokerage-connect/` to sys.path. The cleanest fix is to install brokerage-connect as editable in dev (`uv pip install --python .venv/bin/python -e brokerage-connect/` since this repo's `.venv` is uv-managed → creates a second pth file) and equivalently on prod (add `pip install -e brokerage-connect/` to `scripts/deploy.sh:90` right after the existing `pip install -r requirements.txt`; prod uses a conventional venv with pip).

### Q2 — CI / deploy / config refs to `brokerage/` path?

Comprehensive grep across `Makefile`, `.github/workflows/`, `services.yaml`, `requirements*.txt`, `scripts/*.sh`, `pyproject.toml`, `pytest.ini`, `.cfg`/`.ini` files, `.vscode/settings.json`:
- `scripts/sync_brokerage_connect.sh:32` — 1 ref (the rsync source path).
- `scripts/deploy.sh` — no direct `brokerage/` ref. Rsync includes the path implicitly; default behavior carries `brokerage-connect/` along.
- `tests/api_budget/_lint.py` — 52 hardcoded path strings of the form `"brokerage/<sub>/<file>.py"` used as relpaths against `REPO_ROOT` for vendor-boundary lint allowlists. After the move, every entry rewrites to `"brokerage-connect/brokerage/<sub>/<file>.py"`.
- No CI workflow refs. No Makefile refs. No services.yaml path refs.
- Note: 108 files contain `import brokerage` / `from brokerage` — these are package-name references and continue to work unchanged once sys.path is updated.

### Q3 — IDE / workspace / type-checker config?

- `.vscode/settings.json` — no Python path config; no impact.
- No `.idea/`, no `pyrightconfig.json`, no `mypy.ini`, no top-level `[tool.mypy]` referencing brokerage.
- Repo-root `pyproject.toml` is `fmp-mcp`'s and only configures hatch wheel for `fmp/`; no brokerage references.

## Tradeoffs (new in v2)

**Consistency cost.** Today every top-level Python package in this repo (`brokerage`, `ibkr`, `app_platform`, `fmp`, `portfolio_math`, `portfolio_risk_engine`, `risk_client`) lives directly at repo root with its own pyproject.toml. Option 1 makes `brokerage` the **first** package to adopt the nested `<published-name>/<package>/` layout. The ergonomic price: contributors who know the repo will be momentarily surprised to find brokerage one level deeper. The structural payoff: the dist pyproject and source pyproject become byte-identical (modulo what we deliberately exclude), eliminating the drift class entirely and removing the `--exclude='pyproject.toml'` carve-out from the sync script.

**Net call:** the consistency cost is small (one outlier directory, one CLAUDE.md table row that already names the pattern) and the drift cost is real and recurring (already burned us once on boto3, will keep happening on every dependency change). Option 1 stands.

## Implementation (v5 step sequence)

Single PR. Estimated ~couple hours including verification. Per CLAUDE.md plan-first workflow, send this to Codex for review before any execution.

1. **Move source tree.** `git mv brokerage/ brokerage-connect/`, then `cd brokerage-connect && mkdir brokerage && git mv plaid/ snaptrade/ schwab/ ibkr/ futures/ __init__.py _logging.py _vendor.py broker_adapter.py config.py trade_objects.py brokerage/`. Then **explicitly handle the README situation** (Codex caught this in v3 review): the existing source README at `brokerage-connect/README.md` (formerly `brokerage/README.md`) is monorepo-flavored ("risk-module-brokerage") and would clobber dist's public-facing README on sync. Mirror dist's two-README structure exactly:
   - **`brokerage-connect/README.md`** (root, public-facing) — replace contents with the current dist root README (`brokerage-connect-dist/README.md`, the "Unified Python interface for brokerage APIs" public doc). **Fix the License section while doing this**: dist's current root README claims "MIT" (line 52) but pyproject and the actual `LICENSE` file say `PolyForm-Noncommercial-1.0.0`. Correct the README's License section to match the real license. (Aligning docs with metadata, not a license change.) This is the README hatch will package and PyPI will display.
   - **`brokerage-connect/brokerage/README.md`** (inner, monorepo-flavored) — `git mv` the existing source README into the package dir. Keeps the "What it contains / Supported integrations" reference for monorepo contributors and matches the dist's existing inner README byte-for-byte.
   - Net layout: `brokerage-connect/{pyproject.toml, README.md (public), brokerage/{README.md (monorepo), plaid/, snaptrade/, schwab/, ibkr/, futures/, __init__.py, ...}}`. Mirrors `brokerage-connect-dist/` exactly. Sync becomes lossless.
2. **Rewrite `brokerage-connect/pyproject.toml`.** Adopt dist's structural fields (hatchling backend, `name = "brokerage-connect"`, PolyForm license, project URLs, `packages = ["brokerage"]`, `requires-python = ">=3.11"`) AND the source's already-cleaned dependency set (no boto3 in extras). Bump version to **0.3.0** in this same edit — captures both boto3 cleanup and layout convergence in one published bump. After this step, source pyproject IS the authoritative version source; future bumps happen here, then sync.
3. **Add editable install for dev.** This repo's `.venv` is uv-managed (no `pip` module inside the venv — only `uv pip` works against it). Run from repo root: `uv pip install --python .venv/bin/python -e brokerage-connect/`. Verifies the new `_editable_impl_brokerage_connect.pth` resolves `import brokerage` correctly. (Prod uses a conventional venv with pip — see step 4.)
3a. **Smoke test imports immediately.** Right after step 3 (before any further changes), run from repo root using the venv's Python explicitly:
   ```bash
   .venv/bin/python -c "
   import brokerage
   from brokerage import BrokerAdapter, OrderPreview, OrderResult, TradePreviewResult, BrokerAccount
   import brokerage.plaid, brokerage.snaptrade, brokerage.schwab, brokerage.ibkr, brokerage.futures
   print('OK')
   "
   ```
   In editable install context (this is the dev .venv with `app_platform/`, `ibkr/`, `pyyaml`, `pandas` already importable from the monorepo), this broader test SHOULD pass — fails fast if the editable install didn't wire up correctly OR if any subpackage relative-import got broken by the move. The narrower clean-install version is in step 9.
3b. **Document the install step.** Add the `uv pip install --python .venv/bin/python -e brokerage-connect/` line (with a brief note that prod's conventional venv uses `pip install -e brokerage-connect/` instead — see `scripts/deploy.sh`) to `docs/guides/DEVELOPER_ONBOARDING.md` so fresh checkouts know.
4. **Update `scripts/deploy.sh`.** Add `pip install -e brokerage-connect/` immediately after the existing `pip install -q -r requirements.txt` line (`scripts/deploy.sh:90`). This handles prod's editable install.
5. **Update `scripts/sync_brokerage_connect.sh`:**
   - Change source dir from `$MONOREPO/brokerage/` to `$MONOREPO/brokerage-connect/`.
   - Change target dir from `$TARGET/brokerage/` to `$TARGET/` (rsync flattens `brokerage-connect/` → repo root of `brokerage-connect-dist/`).
   - Drop `--exclude='pyproject.toml'` (the convergence point).
   - **Add explicit excludes to protect dist-only root files** that exist in `$TARGET/` but not in source `brokerage-connect/`. Without these, `--delete` will catastrophically wipe them:
     - `--exclude='LICENSE'` — preserve dist's PolyForm-Noncommercial license (source repo has its own monorepo LICENSE that doesn't apply to the published package).
     - `--exclude='.git/'` — `$TARGET/` IS the dist repo root, so this is its actual `.git` directory; deleting it would destroy the dist git history.
     - `--exclude='.gitignore'` — dist repo has its own.
     - `--exclude='dist/'` — build artifacts directory in dist (visible from `ls`).
     - `--exclude='*.egg-info/'` — any local build leftovers.
   - Verify each existing exclude (`__pycache__/`, `*.pyc`, `.DS_Store`) is preserved.
6. **Rewrite hardcoded `brokerage/` path references** across the repo. Two flavors of refs exist — literal strings (`"brokerage/x/y.py"`) AND path constructions (`Path(...) / "brokerage" / ...`). Both need updating. Concrete locations confirmed via grep:
   - **`tests/api_budget/_lint.py`** — 52 entries in `VENDOR_BOUNDARY_ALLOWLIST` (literal strings, lines ~32-156) → rewrite each `"brokerage/<sub>/<file>.py"` to `"brokerage-connect/brokerage/<sub>/<file>.py"`. Plus the `_BOUNDARY_EXPORT_SOURCES` dict at lines 203-206 — three `REPO_ROOT / "brokerage" / ...` constructions → rewrite each `"brokerage"` segment to `"brokerage-connect" / "brokerage"`.
   - **`tests/api_budget/rule_b_baseline.json:4`** — exactly one source path: `"brokerage/config.py:6"` → `"brokerage-connect/brokerage/config.py:6"`. (The other 5 baseline entries are `tests/brokerage/...` test paths — those test files don't move, so their entries stay unchanged.)
   - **`scripts/seed_reference_data.py:17`** — `Path(...) / "brokerage"` construction → update segment.
   - **`tests/brokerage/futures/test_contract_spec.py:26`** — `Path(...) / "brokerage" / "futures" / "contracts.yaml"` → update first segment.
   - **`tests/api_budget/test_costs_config.py:58`** — `Path(...) / "brokerage" / "snaptrade" / "client.py"` → update first segment.
   - **`docs/guides/DEVELOPER_ONBOARDING.md:166`** — markdown link `[`../../brokerage/`](../../brokerage/)` → update to `brokerage-connect/brokerage/`.
   - **Active markdown docs** (Codex v3 review found these via grep — all should be updated since they're navigation/reference docs, not historical):
     - `README.md:138` — package-README list, `` `brokerage/README.md` `` → `` `brokerage-connect/brokerage/README.md` ``.
     - `Readme.md` — duplicate at line ~138 (case-variant copy of root README, identical content). Update same line.
     - `docs/README.md:33` — broker/provider nav table, `` `../brokerage/README.md` `` → `` `../brokerage-connect/brokerage/README.md` ``.
     - `docs/PRODUCT_ARCHITECTURE.md`, `docs/reference/ARCHITECTURE.md`, `docs/reference/FUTURES_CONTRACT_VERIFICATION.md`, `docs/reference/PRICING_PROVIDER_REGISTRY.md`, `docs/architecture/README.md`, `mcp_tools/README.md`, `ibkr/README.md`, `frontend/packages/ui/src/ARCHITECTURE.md` — Codex should grep each, identify any active path refs (e.g., `` `brokerage/<sub>/<file>` `` or markdown links to `brokerage/...`), and update to `brokerage-connect/brokerage/...`. Skip historical changelog/release-note refs that describe past state.
   - Implementation note: do NOT use a global sed — these are mixed literal-string, path-construction, and markdown-link patterns. Codex should make targeted edits per file, then run `pytest tests/api_budget/ tests/brokerage/futures/` to verify lint baselines and contract_spec tests pass. After all edits, do a final `grep -rE "['\"\`(]brokerage/" --include='*.py' --include='*.md' --include='*.json' --include='*.sh'` from repo root to confirm no stragglers remain (excluding `tests/brokerage/` test paths and any historical/changelog content).
7. **Update `CLAUDE.md` package table.** Today the `Package Development — Local-First Rule` table has rows for `fmp/`, `ibkr/`, `app_platform/`, `frontend/packages/app-platform/`, `sheets_finance/` — but **no row for brokerage**. ADD a new row: `` | `brokerage-connect/` | `brokerage-connect` (PyPI) | `scripts/sync_brokerage_connect.sh` | ``. (Confirm at write-time whether the brokerage package vendors any whitelisted `utils/` modules; current source has no `_shared/` vendoring, so no parenthetical needed.)
8. **Run full test suite.** `pytest tests/` with focus on `tests/brokerage/`, `tests/api_budget/` (post-step-6 lint + baseline), and `tests/providers/` (which import via brokerage adapters). All must pass at parity with pre-move baseline. (Step 3a already smoke-tested basic imports earlier; this is the comprehensive run.)
9. **Clean-install verification (narrowed to actual standalone surface).** Build the wheel using system python (which has `build` available): `cd brokerage-connect/ && python3 -m build`. Create a throwaway conventional venv with a unique path (NOT uv, must have `pip`) so stale environments from prior runs don't mask issues: `VENV=/tmp/brokerage-clean-$(date +%s) && python3 -m venv "$VENV" && "$VENV/bin/pip" install dist/brokerage_connect-0.3.0-py3-none-any.whl`. Then from that venv run a **narrow** smoke test:
   ```bash
   "$VENV/bin/python" -c "
   import brokerage
   from brokerage import BrokerAdapter, OrderPreview, OrderResult, TradePreviewResult, BrokerAccount
   print('OK', brokerage.__name__, BrokerAdapter.__name__)
   "
   ```
   This validates: build backend works, wheel builds without errors, README path resolves correctly (hatch will fail at build if `readme = "README.md"` doesn't exist next to pyproject), pyproject metadata is valid, and the dependency-light public surface (`BrokerAdapter`, `trade_objects.*`) imports cleanly. **Prerequisite check**: confirm `python3 -m build --version` works before step 9 starts; if not, install with `python3 -m pip install --user build`.
   
   **Explicitly NOT tested in this smoke** (and why — pre-existing packaging state, out of scope for this PR): `brokerage.config` imports `ibkr.config` (sibling monorepo package, not declared as dep); `brokerage.futures` imports `yaml` and `pandas` (not declared as deps); `brokerage.plaid/.snaptrade/.schwab/.ibkr` need their respective extras (`pip install brokerage-connect[plaid]` etc.) to import. The published `brokerage-connect` 0.2.2 already had this same packaging shape; this PR converges layout, not dependency declarations. File a follow-up if we want clean-install for `futures`/`config` (would need `pyyaml`+`pandas` as base deps, or lazy-import refactor for `ibkr.config` use).
10. **Dist preflight + dry-run sync.** Before any sync, `cd ~/Documents/Jupyter/brokerage-connect-dist && git status` — must be clean (no uncommitted changes). If dirty, stop and resolve before proceeding (dirty dist would conflate "this PR's intentional changes" with "pre-existing uncommitted state"). Then run a dry-run of the new sync script (`rsync -avn` mode). Expected delta: pyproject.toml updated (0.2.2 → 0.3.0, cleaned extras, hatchling structure preserved), brokerage/ package files updated where source diverged, LICENSE/.git/.gitignore/dist/ untouched.
11. **Live sync + publish.** Execute `./scripts/sync_brokerage_connect.sh` for real. In `brokerage-connect-dist/`, `git status` to verify diff matches step 10's dry-run, commit, push, publish to PyPI per `docs/deployment/PACKAGE_DEPLOY_CHECKLIST.md`.

## Risks

- **Step 3 forgotten on a fresh clone.** If a developer clones the repo and runs tests without the new editable install step, every brokerage import fails. Mitigation: step 3b documents the install in `DEVELOPER_ONBOARDING.md`. (Optional follow-up: a one-line check in `tests/conftest.py` that errors with a clear "run `pip install -e brokerage-connect/`" message if `import brokerage` fails. Out of scope for this PR.)
- **Step 4 missed on next deploy.** If `deploy.sh` is updated but the next deploy doesn't run `pip install -e brokerage-connect/` (e.g., emergency `--skip-checks` path), prod startup fails on first import. Mitigation: the install line lives unconditionally after the `pip install -r requirements.txt` block, so it runs every deploy. Tested via steps 8 and 9.
- **`brokerage-connect-dist/` rsync delta on first sync.** First post-move sync will overwrite the dist pyproject with the source pyproject (intentional convergence). Step 10 preflight + dry-run is the gate: confirms only the pyproject + intended package changes appear, no surprise deletions, no LICENSE/.git/.gitignore/dist clobber.
- **Lint baseline drift in step 6.** Pre-confirmed: `rule_b_baseline.json` has 1 source path (`brokerage/config.py`) requiring rewrite; the other 5 entries are `tests/brokerage/...` test paths whose files don't move. `_lint.py` has 52 literal-string entries plus 3 path-construction entries in `_BOUNDARY_EXPORT_SOURCES`. Step 6 covers all of these explicitly.
- **Editable install hides packaging bugs.** `pip install -e` doesn't catch missing package_data (e.g., `contracts.yaml` not bundled), README path mis-resolution, or build-backend errors. Step 9 builds a wheel into a throwaway venv specifically to catch these (narrowed to dependency-light public surface — see step 9 for what's NOT tested and why).
- **Pre-existing packaging gaps in `brokerage-connect`.** `brokerage.config` imports `ibkr.config` (sibling monorepo package, not declared); `brokerage.futures` imports `yaml`+`pandas` (not declared). These exist in the published 0.2.2 wheel today — this PR converges layout, not deps. Acceptable carry-forward; file a follow-up plan if we want clean-installable `futures`/`config`.
- **Git history.** `git log --follow brokerage-connect/brokerage/<file>` continues to traverse history through the rename. `git blame` UX is slightly noisier post-move on the moved files (the rename commit appears in blame), but no history is lost. Acceptable cost.

Until scheduled, the **2026-04-30 release** carries:
- Source pyproject already cleaned (boto removed).
- Dist pyproject manually edited at release time (version 0.2.2 → 0.3.0; boto removed from extras).

## Out of scope

- Full publishing pipeline (PyPI release automation) — separate concern.
- Source `brokerage/` package name change (stays `brokerage`).
- Dist license / URL changes (stay as-is).

## Decisions log

- **2026-04-30 (v1)** — Option 1 recommended over 2/3. Surfaced during credentials KMS migration when boto3 cleanup didn't propagate to dist. Filed as follow-up rather than blocking the credentials release.
- **2026-04-30 (v2)** — Open questions resolved via codebase research. Decision locked: Option 1. Confirmed: (a) brokerage import resolves through repo-root-on-sys.path via the `fmp-mcp` editable install pth file — not a brokerage editable install, so the move requires adding `pip install -e brokerage-connect/`; (b) breakage surface in scripts/Makefile/CI is small; (c) no CI / IDE / Makefile / services.yaml refs. New consistency tradeoff named: brokerage becomes the first sub-package to use the nested `<published-name>/<package>/` layout. Net call: drift cost > consistency cost, Option 1 stands.
- **2026-04-30 (v3)** — Codex review of v2 returned FAIL with 5 required changes. All addressed: (1) rsync excludes added for `LICENSE`/`.git/`/`.gitignore`/`dist/`/`*.egg-info` to prevent dist root clobber from `--delete`; (2) README.md placement fixed — stays at `brokerage-connect/README.md` level (matching `readme = "README.md"` in pyproject), not nested into the package dir as v2 had it; (3) path-rewrite scope expanded to include `_BOUNDARY_EXPORT_SOURCES` in `_lint.py:203-206`, `scripts/seed_reference_data.py:17`, `tests/brokerage/futures/test_contract_spec.py:26`, `tests/api_budget/test_costs_config.py:58`, `docs/guides/DEVELOPER_ONBOARDING.md:166`; (4) factual corrections: CLAUDE.md table requires ADDING a row (no existing brokerage row), deploy checklist actual path is `docs/deployment/PACKAGE_DEPLOY_CHECKLIST.md`, `rule_b_baseline.json` has 1 source path to rewrite (not 6 — the others are test paths); (5) clean-install verification step added (build + install in throwaway venv) to catch packaging blind spots editable install hides. Plus 3 suggestions folded in: smoke test moved to step 3a, dist preflight check added to step 10, git history tradeoff named in §Risks.
- **2026-04-30 (v4)** — Codex review of v3 returned FAIL with 3 required changes. All addressed: (1) **README content overwrite** — v3 left source `brokerage-connect/README.md` as monorepo-flavored "risk-module-brokerage" content, which sync would have used to clobber dist's public-facing PyPI README. v4 step 1 now explicitly mirrors dist's two-README structure: replace `brokerage-connect/README.md` with public dist content + move monorepo README into `brokerage-connect/brokerage/README.md`. (2) **Active markdown docs path refs** — Codex grep found refs in root `README.md:138`, `Readme.md`, `docs/README.md:33`, plus 8 other architecture/reference docs. Step 6 now lists these explicitly + adds a final repo-wide grep verification step. (3) **Clean-install smoke test would fail** — `brokerage.futures` imports yaml/pandas (not declared deps), `brokerage.config` imports `ibkr.config` (sibling monorepo package). Step 9 narrowed to test only the truly clean public surface (`BrokerAdapter`, `trade_objects.*`); broader subpackage testing requires extras or pre-existing packaging refactor and is named explicitly out of scope.
- **2026-04-30 (v5)** — Codex review of v4 returned FAIL with 2 required changes. All addressed: (1) **README license fix** — dist's current root README claims "MIT" but pyproject + actual LICENSE file say `PolyForm-Noncommercial-1.0.0`. Step 1 now explicitly fixes the License section while copying. (2) **Tool-availability mismatch** — verified locally: this repo's `.venv` is uv-managed (no `pip` module). Steps 3, 3a, 3b, 9 updated to use the right invocations: `uv pip install --python .venv/bin/python -e brokerage-connect/` for dev editable, `.venv/bin/python -c ...` for smoke test, `python3 -m build` (system) for wheel build, and a throwaway conventional `python3 -m venv` (with pip) for the clean-install smoke. Prod's deploy.sh keeps `pip install -e` since prod uses a conventional venv.
- **2026-04-30 (v6)** — Step 11 is being executed through a new `scripts/publish_brokerage_connect.sh` automation path instead of the manual publish flow described in v5. The package deploy checklist is being updated to register the new brokerage-connect publish script and sync command.
