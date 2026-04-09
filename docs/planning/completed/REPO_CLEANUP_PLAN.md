# Repo Cleanup Plan

**Created:** 2026-03-24
**Status:** Phases 1-2 complete, Phase 5 deferred post-deploy

---

## Phase 1 — Untracked Disk Bloat (safe, no git impact)

All items are **untracked by git** (or ephemeral artifacts), so deletion has zero impact on the repo's committed state. The `logs/` directory is a special case — it contains both disposable log files AND active MCP tool output subdirectories that code writes to at runtime.

### Step 1: Delete `backup/` (~746MB)
```bash
rm -rf backup/
```
- One-time manual snapshot from Feb 18 2026
- `scripts/backup_system.sh` uses `backup/` as its target dir (`mkdir -p` — creates if missing). Safe to delete current snapshot; script will recreate the directory next time it runs.
- Not tracked in git, no symlinks
- **Note:** snapshot includes `.env` and `user_data/` which are not in git. Confirm these are no longer needed (or already captured elsewhere) before deleting. Code-level content is preserved in git history at that date.

### Step 2: Purge `__pycache__/` (~80MB)
```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
```
- 144 directories, 2,062 .pyc files
- Regenerated automatically on next Python import

### Step 3: Delete `cache/` (~247MB)
```bash
rm -rf cache/
```
- FMP/IBKR runtime price/data caches (23 subdirs, incl. `cache/file_output` for FMP tool CSV output)
- Code recreates dirs on demand via `fmp/cache.py` and `utils/timeseries_store.py`
- Trade-off: next run will be slower (cold cache), and fresh upstream FMP API fetches will be needed (rate-limit/cost exposure). No structural breakage — all cache paths are auto-created.

### Step 4: Prune `logs/` — rotated log files only (~340MB)
```bash
# Delete rotated/old log files only (top-level, excludes active sinks)
find logs/ -maxdepth 1 -type f -name "*.log.*" -delete     # rotated: debug.log.1, app.log.2, etc.
find logs/ -maxdepth 1 -type f -name "*.jsonl.*" -delete   # rotated: errors.jsonl.1, frontend.jsonl.1, etc.
find logs/ -maxdepth 1 -type f -name "*.json" -delete      # old one-off JSON exports

# Keep subdirectories intact — 19 MCP tools write snapshots there:
#   logs/positions/, logs/risk_analysis/, logs/performance/, etc.
```
- 340MB+ in rotated debug.log.N, app.log.N files
- MCP tool output subdirs (~17MB) are kept — actively written to at runtime
- **Preserved active sinks** (not deleted):
  - `logs/usage.jsonl` — read by `routes/admin.py` for admin analytics
  - `logs/timing.jsonl` — read by `routes/debug.py` for timing summaries
  - `logs/frontend.jsonl`, `logs/errors.jsonl` — structured logging sinks
  - `logs/app.log`, `logs/debug.log` — current (non-rotated) log files

### ~~Step 5: Delete root `node_modules/`~~ — SKIPPED
- Root `node_modules/` (~230MB) is needed by `e2e/` tests (`@playwright/test` declared only in root `package.json`)
- Conflicting lockfiles (`package-lock.json` vs `pnpm-lock.yaml`) make reinstall risky — could mutate tracked lockfiles
- Moved to "NOT deleting" list. Can revisit when lockfiles are consolidated (Phase 4+ candidate).

### Step 6: Delete test artifacts (~524KB)
```bash
rm -rf playwright-report/ test-results/
```
- Generated Playwright HTML report + last-run metadata
- Regenerated on next test run

### Step 7: Delete `.context/` (tiny)
```bash
rm -rf .context/
```
- Codex session ID file, untracked, ephemeral

### Step 8: Harden `.gitignore`
Most of these are already ignored (`backup/`, `cache/`, `logs/`, `playwright-report/`, `test-results/`). Add the missing entry:
```gitignore
# Codex session state
.context/
```

### NOT deleting (intentionally kept)
- **`node_modules/`** (root, ~230MB) — needed by `e2e/` tests; conflicting lockfiles make reinstall risky
- **`frontend/node_modules/`** (~1.5GB) — active dev environment, needed for frontend builds/tests
- **`frontend/build/`** (~3.9MB) — last production build artifact
- **`frontend/packages/*/dist/`** (~5.2MB) — built package outputs, needed for local imports
- **`.pytest_cache/`** (~136KB across 3 dirs) — tiny, harmless
- **`exports/`** — empty dir, keep as output target
- **`.claude/worktrees/`** (57MB) — may be from an active parallel session, skip for now
- **`data/`** (184KB) — small, likely has reference data
- **`user_data/`** (16KB) — small, user-specific config

### Verification
1. `du -sh .` to confirm disk savings (~1.5GB recovered)
2. `git status --short` to confirm no tracked files were affected (worktree may already be dirty from other work — check that no *new* changes appear)
3. `git status --short --ignored` to confirm ignored paths are correct
4. `find logs -maxdepth 1 -type d | sort` to verify MCP tool output subdirs preserved
5. `python3 -c "import settings"` to confirm Python imports still work

### Estimated savings

| Item | Size |
|------|------|
| backup/ | 746MB |
| __pycache__/ | ~80MB |
| cache/ | 247MB |
| logs/ (rotated only) | ~340MB |
| test artifacts | ~1MB |
| **Total** | **~1.4GB** |

---

## Phase 2 — Dead Tracked Code (needs git commit)

### Step 1: Delete `risk_client/` + its test (3 files)
```bash
git rm -r risk_client/
git rm tests/test_risk_client.py
```
- Dead HTTP client package — no production importers (only its own test file)
- Contains `__init__.py` (RiskClient class) + `pyproject.toml`
- `tests/test_risk_client.py` exercises the client — must be deleted with the package
- `.gitignore` already ignores `risk_client/risk_client.egg-info/`

### Step 2: Delete `options/models 2.py` (1 file)
```bash
git rm "options/models 2.py"
```
- Duplicate of the old pre-refactor `models.py` (has space in filename)
- Zero importers — the live `options/models.py` is a shim that re-exports from `data_objects` + `result_objects`

### Step 3: Delete 24 dead files from `models/` (keep 3 live)
```bash
git rm models/analyzeresponse.py models/currentportfolioresponse.py \
  models/directinterpretresponse.py models/directoptimizemaxretresponse.py \
  models/directoptimizeminvarresponse.py models/directperformanceresponse.py \
  models/directportfolioresponse.py models/directstockresponse.py \
  models/directwhatifresponse.py models/factoranalysisresponse.py \
  models/generated_factorcorrelationresponse.py \
  models/generated_factorperformanceresponse.py \
  models/generated_offsetrecommendationresponse.py \
  models/healthresponse.py models/interpretresponse.py \
  models/maxreturnresponse.py models/minvarianceresponse.py \
  models/performanceresponse.py models/portfolioanalysisresponse.py \
  models/portfolioslistresponse.py models/riskscoreresponse.py \
  models/risksettingsresponse.py models/whatifresponse.py \
  models/usage_example.py
```
- Original one-class-per-file pattern, superseded by consolidated `response_models.py`
- Zero importers on all 24 files
- **Keep** (3 live files):
  - `models/__init__.py` — re-exports used by `app.py`
  - `models/response_models.py` — all API Pydantic models
  - `models/factor_intelligence_models.py` — used by `mcp_tools/baskets.py` + `routes/factor_intelligence.py`

### Verification
1. `git status` to confirm only intended files staged for deletion
2. `python3 -c "from models import HealthResponse; print('OK')"` — confirm live models still import
3. `python3 -c "from models.factor_intelligence_models import FactorCorrelationRequest; print('OK')"` — confirm factor models still import
4. `python3 -c "import app; print('OK')"` — confirm app.py model import surface intact
5. `python3 -m pytest tests/routes/test_baskets_api.py tests/mcp_tools/test_factor_intelligence.py -x -q` — run tests adjacent to kept model files

---

## Phase 3 — Archive / Stale Tracked Content

| Item | Tracked files | What it is | Action |
|------|--------------|-----------|--------|
| `archive/` | 22 | Old e2e tests + stale mock test. Already explicitly archived. | Keep as-is or gitignore |
| `e2e/` | 17 | Playwright e2e tests (TypeScript). | Audit — are these still run? Keep if active, archive if not |
| `docs/_archive/` | ~20 | Old schemas, specs, guides | Already archived — low priority, leave alone |
| `docs/planning/completed/` | **1,154 files, 44MB** | Completed plan docs | See Phase 5 |

---

## Phase 4 — Audit Directories for Consolidation

These directories are functional but may have stale or consolidation-worthy content.

| Item | Importers | Notes |
|------|-----------|-------|
| `admin/` | 1 (`scripts/seed_reference_data.py`) | Migration/backfill scripts — one-time-use? Could move to `scripts/admin/` |
| `brokerage/` | 10+ files | Active — broker adapter layer. Has sub-packages (futures, ibkr, plaid). Leave alone. |
| `models/` (non-dead parts) | See Phase 2 | Only `factor_intelligence_models.py` is live. Rest is dead weight. |

---

## Phase 5 — Plan Doc Pruning (biggest git-history impact)

`docs/planning/completed/` has **1,154 .md files (44MB tracked)**. Every completed plan is preserved here even though the implementation is in git history.

**Options:**
- [ ] A: Delete all completed plans (they're in git history if ever needed)
- [ ] B: Keep a curated subset (landmark features only), delete the rest
- [ ] C: Move to a separate branch or tag, remove from main
- [ ] D: Leave as-is (no action)

**Active plans** (`docs/planning/*.md`, not in `completed/`): ~170 files — audit which are still relevant vs. abandoned.

---

## Phase 6 — .gitignore Hardening

Already ignored: `__pycache__/`, `node_modules/`, `*.pyc`, `backup/`, `cache/`, `logs/`, `playwright-report/`, `test-results/`.

Only addition needed:
```
.context/
```

---

## Execution Order

1. **Phase 1** first — zero risk, big disk savings
2. **Phase 6** — harden .gitignore before Phase 2 changes
3. **Phase 2** — small, surgical git commits
4. **Phase 3** — audit e2e, decide on archive
5. **Phase 4** — consolidation (lower priority)
6. **Phase 5** — plan doc pruning (discuss strategy first)
