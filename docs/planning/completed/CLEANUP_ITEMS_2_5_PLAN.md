# Cleanup Items 2-5 Plan
**Status:** DONE

## Context

Finishing the cleanup roadmap from `docs/TODO.md`. Item 1 (core shim removal, `18479c3d`) and item 6 (dead cash anchor test, `be91cb91`) are done. Four items remain — all mechanical, no logic changes.

---

## Item 2: `models/` Directory Audit — Delete 24 Dead Files

**Problem:** 27 .py files, only 3 used. 24 are dead duplicates or unused stubs.

**Keep (3 files):**
- `__init__.py` — re-exports from response_models.py
- `response_models.py` (192 lines) — 25 Pydantic response models used by app.py (via `models.__init__`)
- `factor_intelligence_models.py` (394 lines) — 9 models used by routes/factor_intelligence.py, mcp_tools/baskets.py

**Delete (24 files):**
- 19 individual response files — exact duplicates of classes in response_models.py, zero direct imports:
  `analyzeresponse.py`, `currentportfolioresponse.py`, `directinterpretresponse.py`, `directoptimizemaxretresponse.py`, `directoptimizeminvarresponse.py`, `directperformanceresponse.py`, `directportfolioresponse.py`, `directstockresponse.py`, `directwhatifresponse.py`, `healthresponse.py`, `interpretresponse.py`, `maxreturnresponse.py`, `minvarianceresponse.py`, `performanceresponse.py`, `portfolioanalysisresponse.py`, `portfolioslistresponse.py`, `riskscoreresponse.py`, `risksettingsresponse.py`, `whatifresponse.py`
- 3 generated factor stubs (unused): `generated_factorcorrelationresponse.py`, `generated_factorperformanceresponse.py`, `generated_offsetrecommendationresponse.py`
- 1 unused: `factoranalysisresponse.py`
- 1 docs artifact: `usage_example.py`

**Note:** No out-of-repo consumers exist for `models.*` — this is a monorepo-internal package, not published.

**Note on stale doc references:** `tests/TESTING_COMMANDS.md` (line 1370) references `models/usage_example.py` — update or remove when deleting the file. `docs/guides/DEVELOPER_ONBOARDING.md` (line ~701) describes `models/` as "27 model files" — update the count to 3 after deletion. (`trading_analysis/README.md:92` shows `examples/usage_example.py`, a different file in the `trading_analysis/` subtree — unrelated to our deletion.)

**Note on `trading_analysis/main.py`:** Line 37 has `from models import FullAnalysisResult, Grade`. When run as `python3 trading_analysis/main.py`, Python prepends `trading_analysis/` to `sys.path[0]`, so this resolves to `trading_analysis/models.py` (which defines both names). The top-level `models/` package would only collide if run via `python3 -m trading_analysis.main` (which adds CWD to `sys.path`). This is a pre-existing quirk of the CLI script, unrelated to our cleanup — we are not modifying `models/__init__.py` or `trading_analysis/`.

### Verification for Item 2

```bash
# Confirm no imports reference deleted files (both from/import patterns)
rg "(from models\.(analyzeresponse|currentportfolioresponse|directinterpretresponse|directoptimizemaxretresponse|directoptimizeminvarresponse|directperformanceresponse|directportfolioresponse|directstockresponse|directwhatifresponse|healthresponse|interpretresponse|maxreturnresponse|minvarianceresponse|performanceresponse|portfolioanalysisresponse|portfolioslistresponse|riskscoreresponse|risksettingsresponse|whatifresponse|factoranalysisresponse|generated_|usage_example)|import models\.(analyzeresponse|currentportfolioresponse|directinterpretresponse|directoptimizemaxretresponse|directoptimizeminvarresponse|directperformanceresponse|directportfolioresponse|directstockresponse|directwhatifresponse|healthresponse|interpretresponse|maxreturnresponse|minvarianceresponse|performanceresponse|portfolioanalysisresponse|portfolioslistresponse|riskscoreresponse|risksettingsresponse|whatifresponse|factoranalysisresponse|generated_|usage_example))" --glob '*.py' -g '!archive/**' -g '!.claude/**' -g '!models/**' .

# Confirm retained models still importable
python3 -c "from models import AnalyzeResponse, HealthResponse, RiskScoreResponse; print('OK')"
python3 -c "from models.factor_intelligence_models import FactorCorrelationRequest; print('OK')"

# File count
ls models/*.py | wc -l  # Should be 3
```

---

## Item 3: Root `pyproject.toml` Clarification

**Problem:** Root pyproject.toml defines `fmp-mcp` package, confusing in a monorepo context.

**Action:** Add a comment block at the top of `pyproject.toml` explaining:
- This file defines the `fmp-mcp` package (synced to its own repo via `scripts/sync_fmp_mcp.sh`)
- Other packages have their own pyproject.toml: `ibkr/`, `brokerage/`, `portfolio_risk_engine/`, `app_platform/`
- No structural changes needed — current setup works for pip install and sync

TOML supports `#` comments at the top of the file — add comment lines before `[build-system]` explaining the monorepo context.

---

## Item 4: `archive/` Directory — Untrack Remaining Files from Git

**Problem:** `archive/` is already in `.gitignore` (line 61), but 22 files (~0.6MB) are still tracked in the git index from before the ignore rule was added. Zero production imports.

**Action:**
1. `git rm -r --cached archive/` — untrack the 22 remaining files without deleting from disk (files stay in working directory, just removed from git index)
2. No `.gitignore` change needed — `archive/` rule already present
3. Commit the index removal

### Verification for Item 4

```bash
# Confirm no production code imports from archive/
rg "from archive|import archive" --glob '*.py' -g '!archive/**' -g '!.claude/**' .

# Confirm archive/ is untracked after git rm --cached
git ls-files archive/ | wc -l  # Should be 0

# Confirm archive/ is ignored (use a synthetic path — git check-ignore needs
# an untracked path to test the rule; tracked files always return exit 1)
git check-ignore -v archive/test-file  # Should show .gitignore:61:archive/
```

---

## Item 5: Planning Docs Status Headers

**Problem:** 39 non-index docs in `docs/planning/` (44 total minus 5 index files: TODO.md, PROGRESS.md, BACKLOG.md, README.md, BUGS.md). Of these 39, ~35 lack `**Status:**` headers (4 already have them and will be left as-is or updated if the status has changed).

**Action:** For each file in `docs/planning/*.md` (not subdirectories):
1. Scan content for completion markers: all `[x]` checkboxes done, "DONE" text, "COMPLETE" text, commit references suggesting work is finished
2. Classify as one of:
   - **DONE** — all work complete, has commit refs or all checkboxes checked
   - **ACTIVE** — work in progress, has unchecked items
   - **DEFERRED** — explicitly deferred or paused
   - **PLANNING** — plan written but work not started
3. Add `**Status:** X` line after the title (line 1)
4. Move any DONE plans to `docs/planning/completed/`, and update any relative links in tracker docs (TODO.md, BACKLOG.md, PROGRESS.md, README.md) that reference moved files

### Classification Rules
- If ALL checkboxes are `[x]` and there's a commit hash → DONE → move to completed/
- If it has unchecked `[ ]` items and recent activity → ACTIVE
- If it says "deferred" or "paused" → DEFERRED
- If it's a plan with no implementation evidence → PLANNING
- TODO.md, PROGRESS.md, BACKLOG.md, README.md, BUGS.md are index/tracker files — skip (don't add status or move)
- **`completed/` uses nested subdirectories** (e.g., `completed/frontend/`, `completed/futures/`). Place moved files in the appropriate subdirectory based on topic, or at the `completed/` root if no existing subdirectory fits.
- When moving files, update both markdown links `[text](FILENAME.md)` and backtick references `` `FILENAME.md` `` in tracker/index docs (TODO.md, BACKLOG.md, PROGRESS.md, README.md) to point to the actual destination path (e.g., `completed/futures/FILENAME.md`). Backtick refs in PROGRESS.md are historical log entries — update the path but keep the backtick format. Links in non-index docs (other plans, architecture docs) are low-priority and can be left as-is.
- **DONE heuristic edge cases:** Some plans have commits referenced in tracker docs (TODO.md, BACKLOG.md, PROGRESS.md, completed/TODO_COMPLETED.md) but no checkboxes in the plan itself (e.g., `PG_POOL_EXHAUSTION_FIX_PLAN.md`, `FUTURES_LIVE_PRICING_PLAN.md`). Cross-reference all tracker docs (TODO.md, BACKLOG.md, PROGRESS.md, completed/TODO_COMPLETED.md) for completion evidence — if any of these marks them as done with a commit, classify as DONE even without checkboxes. Audit/design docs (e.g., `ONBOARDING_FRICTION_AUDIT.md`, `FUTURES_DESIGN.md`) may mention commits without being "done" — these describe ongoing architecture, not one-shot implementation plans. Classify as ACTIVE unless tracker docs explicitly mark them complete.

### Verification for Item 5

```bash
# All non-index planning docs should have a Status line in first 5 lines
# Uses rg instead of grep to avoid BSD grep's "repetition-operator operand invalid" on \*
for f in docs/planning/*.md; do
  base=$(basename "$f")
  if [[ "$base" == "TODO.md" || "$base" == "PROGRESS.md" || "$base" == "BACKLOG.md" || "$base" == "README.md" || "$base" == "BUGS.md" ]]; then continue; fi
  if ! head -5 "$f" | rg -q '^\*\*Status:'; then echo "MISSING STATUS: $f"; fi
done
# Should output nothing (all files have status headers)
```

**Note:** `BUGS.md` has `**Status:**` entries in bug items (body), not as a file-level header — hence excluded as an index file. The `head -5` check ensures we only match header-level status lines, not body content.

### Verification for Doc Link Integrity

```bash
# After moving files, check that tracker docs don't have broken references.
# Checks markdown link targets [text](*.md), bare backtick plan refs `FILENAME.md`,
# and path-qualified backtick refs like `docs/planning/FILENAME.md`.
# Resolves each ref relative to docs/planning/, then searches nested completed/*/.
for f in docs/planning/TODO.md docs/planning/BACKLOG.md docs/planning/PROGRESS.md docs/planning/README.md; do
  [ -f "$f" ] || continue
  {
    # 1. Markdown links: [text](./FILE.md) or [text](FILE.md)
    rg -o '\]\((\./)?([A-Za-z][A-Za-z0-9_/-]*\.md)\)' -r '$2' "$f"
    # 2. Bare backtick plan refs: `FUTURES_DESIGN.md`, `PHASE_A_NO_INFRA_PLAN.md`
    rg -o '`([A-Za-z][A-Za-z0-9_-]+_(?:PLAN|DESIGN|AUDIT|ARCHITECTURE)\.md)`' -r '$1' "$f"
    # 3. Path-qualified backtick refs: `docs/planning/FUTURES_DESIGN.md`, `completed/FOO.md`
    rg -o '`((?:docs/planning/|completed/)[A-Za-z][A-Za-z0-9_/-]*\.md)`' -r '$1' "$f"
  } | sort -u | while read ref; do
    # Normalize path-qualified refs to basename for lookup
    case "$ref" in
      docs/planning/completed/*) base=$(basename "$ref"); ref="completed/$base" ;;
      docs/planning/*) ref=$(basename "$ref") ;;
      completed/*) ;; # already relative to planning/
    esac
    # Check existence: direct path or basename search in completed/
    base=$(basename "$ref")
    if [ -f "docs/planning/$ref" ]; then continue; fi
    if find docs/planning/completed -name "$base" -print -quit 2>/dev/null | rg -q .; then continue; fi
    echo "BROKEN REF in $f: $ref"
  done
done
```

**Note:** The backtick extraction uses a suffix whitelist (`_PLAN.md`, `_DESIGN.md`, `_AUDIT.md`, `_ARCHITECTURE.md`) to avoid matching prose filenames like `MCP_SERVERS.md` or `TODO-options-tools.md` that were moved/merged in earlier cleanups. Path-qualified refs (e.g., `docs/planning/FUTURES_DESIGN.md`) are normalized to their planning-relative path before lookup.

---

## Execution Order

1. **Item 2** — Delete 24 dead model files
2. **Item 4** — Untrack archive/
3. **Item 3** — Add pyproject.toml comment
4. **Item 5** — Planning docs status scan + headers + moves

## Final Verification

```bash
# Full test suite
python3 -m pytest tests/ -x --no-header -q

# Entry points
python3 -c "import app; import mcp_server; import fmp_mcp_server; print('OK')"

# Models still work
python3 -c "from models import AnalyzeResponse, HealthResponse; print('OK')"

# models/ file count
ls models/*.py | wc -l  # Should be 3
```
