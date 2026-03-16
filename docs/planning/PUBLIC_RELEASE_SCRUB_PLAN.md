# 3K. Public Release Scrub — Execution Plan

**Status:** READY TO EXECUTE
**Date:** 2026-03-15 (v11-final — 10 Codex review rounds)
**Prerequisite findings:** `docs/deployment/RELEASE_SCRUB_FINDINGS.md`, `docs/deployment/PUBLIC_RELEASE_EXCLUSION_CHECKLIST.md`
**Approach:** Option A (exclude `docs/planning/` from public repo) — simplest path

---

## Decision: Sync-Based Public Repo

The public repo will be a **filtered sync** of this repo (not a history rewrite). A sync script copies source code while excluding private directories/files. The private repo retains full history. The public repo starts with a clean initial commit.

This means:
- No `git filter-repo` needed on this repo
- No risk to working history
- Exclusions are declarative (in the sync script)
- Can re-sync any time after new features land

---

## Phase 1: Pre-Scrub Decisions + Workflow Disablement (~15 min)

| # | Decision | Options | Notes |
|---|----------|---------|-------|
| 1.1 | **License** | MIT / Apache 2.0 / source-available | Currently mismatched: `LICENSE` says proprietary, `package.json` says MIT |
| 1.2 | **Public repo name** | `portfolio-mcp` / `portfolio-risk` / other | GitHub org: `henrysouchien` or new org? |
| 1.3 | **Domain name** | Needed for deployment (1B prerequisite too) | Blocks Google OAuth production |

### 1.4 Disable Legacy Sync Workflow (BLOCKING — do this FIRST)

`.github/workflows/sync-to-public.yml` auto-syncs on every push to main. It copies `portfolio.yaml`, `docs/planning/*`, `architecture.md`, and `settings.py` to the `portfolio-risk-engine` public repo — **all of which contain personal data**.

**Action:** Before ANY other work in this plan, either:
- Delete the file: `git rm .github/workflows/sync-to-public.yml && git commit -m "remove legacy public sync workflow"`
- Or disable in GitHub Actions settings (repo → Settings → Actions → Workflows → disable)

If this workflow runs during Phase 3 edits, it will push partially-scrubbed code to a public repo. **This is the highest-priority item in the entire plan.**

**Deliverable:** License choice, repo name, domain name recorded. Legacy workflow disabled.

---

## Phase 2: Create Sync Script (~30 min)

Create `scripts/sync_public_repo.sh` following the pattern of existing sync scripts (`sync_fmp_mcp.sh`, etc.).

### 2.1 Exclusion list (from findings + Codex review rounds 1+2)

**Directories to exclude entirely:**
```
docs/planning/          # Personal financial data, account IDs, dollar amounts
docs/guides/            # Internal admin guides with personal email
docs/specs/             # Internal specs with hardcoded paths
docs/deployment/        # Internal deployment plans with IPs, credentials patterns
docs/prompts/           # Internal prompts with personal paths
docs/schemas/           # CLI output captures with personal paths
docs/_archive/          # Archived internal docs with personal paths
docs/architecture/legacy/  # Legacy codebase maps with personal paths
docs/*.csv              # IBKR statements + Schwab/Merrill exports at docs/ root (7 files)
.claude/                # Session memory, project memory
.github/workflows/sync-to-public.yml  # Legacy workflow that leaks private data
tests/snaptrade/        # Personal email, AWS secret names, real account test results
tests/reports/          # AI test reports with personal data (19 JSON files)
tests/diagnostics/      # Diagnostic scripts with personal email + account IDs
config/portfolio.yaml   # Real portfolio holdings (17 positions)
portfolio.yaml          # Root-level copy (byte-identical to config/portfolio.yaml)
backup/                 # Local backups
user_data/              # User-specific data
archive/                # Old code
cache_prices/           # Cached market data
logs/                   # Runtime logs
*.log                   # Build/lint log files (e.g., frontend/eslint-check.log)
*.tsbuildinfo           # TS build info with absolute paths (e.g., tsconfig.tsbuildinfo)
scripts/secrets_helper.sh  # References private secrets repo
scripts/update_secrets.sh  # References private secrets repo
scripts/plaid_reauth.py    # Internal tooling
scripts/extract_performance_actual_baseline.py  # References excluded statement data
scripts/materialize_ibkr_statement.py           # References excluded statement data
scripts/test_first_exit_backfill.py             # Hardcoded IBKR account ID
scripts/debug_fmp_ticker_map.py                 # Hardcoded personal email
tests/fixtures/performance_baseline_2025.json   # Real account data, holdings, dollar values
```

**NOTE:** `inputs/` is **NOT excluded** — it is application code imported by `app.py`. It contains normalizer definitions and transaction store logic, not user data.

**NOTE:** Excluding `docs/planning/` will break markdown links from included docs (e.g., `docs/interfaces/README.md`, `docs/interfaces/cli.md`) that reference planning files. This is acceptable — the public repo's docs are reference material, and broken links to internal plans are harmless. If desired, add a note to the public README explaining that internal planning docs are not included.

**Files to exclude:**
```
docs/CHANGELOG.md       # Contains personal paths
CHANGELOG.md            # Root-level copy, also personal paths
AI_CONTEXT.md           # Contains personal email in MCP server example
RELEASE_PLAN.md         # Contains deploy infra details (EC2 IP, SSH key paths)
tests/TESTING_COMMANDS.md  # 27+ personal email references
```

### 2.2 Post-Sync Pattern Scrub (safety net)

Enumerating every file with personal data is fragile — new files get added, patterns appear in test fixtures, comments, etc. Instead, the sync script includes a **post-rsync sed sweep** that replaces all remaining instances of banned patterns. This is the safety net that catches anything the exclusion list and Phase 3 edits miss.

```bash
# Post-sync: sweep remaining banned patterns in the target repo
echo "=== Running post-sync pattern scrub ==="
cd "$TARGET_DIR"

# Replace personal email
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/hc@henrychien\.com/user@example.com/g' {} +

# Replace support email
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/support@henrychien\.com/support@example.com/g' {} +

# Replace IBKR account ID (in non-binary files)
find . -type f -not -path './.git/*' \
  -not -name '*.png' -not -name '*.jpg' -not -name '*.woff2' -exec \
  sed -i '' 's/U2471778/<ACCOUNT_ID>/g' {} +

# Replace absolute home paths
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's|/Users/henrychien/Documents/Jupyter/risk_module|<PROJECT_ROOT>|g' {} +
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's|/Users/henrychien|<HOME>|g' {} +

# Replace SnapTrade UUID
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/cb7a1987-bce1-42bb-afd5-6fc2b54bbf12/<SNAPTRADE_USER_ID>/g' {} +

echo "=== Post-sync pattern scrub complete ==="
```

This runs automatically as part of the sync script (after rsync, before verification).

### 2.3 Files to scrub in-repo (Phase 3)

These need deliberate edits in the **private repo** because the sed sweep's generic replacements may break code or look messy. Better to fix them properly:

| File | What to change |
|------|---------------|
| `mcp_server.py` | Replace path in docstring with relative `./` or env var reference |
| `LICENSE` | Replace with chosen license text |
| `package.json` | Align `"license"` field to chosen license |
| `database/schema.sql` | Replace seed email → `user@example.com`, name → `Test User` |
| `tests/utils/create_test_session.py` | Replace email → `user@example.com`, name → `Test User` |
| `run_snaptrade.py` (root) | Replace docstring emails → `user@example.com` |
| `run_plaid.py` (root) | Replace docstring emails → `user@example.com` |
| `scripts/run_snaptrade.py` | Replace docstring emails → `user@example.com` |
| `scripts/run_plaid.py` | Replace docstring emails → `user@example.com` |
| `scripts/explore_transactions.py` | Replace default email → `user@example.com` |
| `architecture.md` | Replace path + email in MCP example → generic |
| `docs/reference/MCP_SERVERS.md` | Replace path + email in registration example → generic |
| `docs/reference/API_REFERENCE.md` | Replace personal paths/emails → generic |
| `docs/reference/EARNINGS_ESTIMATES.md` | Replace personal paths → generic |
| `mcp_tools/README.md` | Replace path AND email in examples → generic |
| `scripts/deploy.sh` | Replace SSH key path → `$SSH_KEY` env var, EC2 IP → `$EC2_HOST` env var |
| `core/realized_performance/aggregation.py` | Replace `U2471778` in comments → `<ACCOUNT_ID>` |
| `core/realized_performance_analysis.py` | Replace `U2471778` references → `<ACCOUNT_ID>` |
| `ibkr/flex.py` | Replace `U2471778` in comment → `<ACCOUNT_ID>` |
| `CLAUDE.md` | Remove/generalize memory file references |
| `README.md` | Remove private sync workflow instructions, PAT rotation references, and any internal infra details (check tail of file) |
| Create `config/portfolio.example.yaml` | Anonymized sample portfolio |

### 2.4 Tests referencing excluded data or containing personal data

These files reference `performance-actual-2025/` (excluded), `docs/*.csv` (excluded), `config/portfolio.yaml` (excluded), or contain hardcoded personal data:

| File | Issue | Action |
|------|-------|--------|
| `tests/importers/test_ibkr_statement.py` | References excluded statement data | Audit: if uses real files → exclude; if mocked → safe |
| `tests/mcp_tools/test_import_transactions_csv.py` | References `docs/*.csv` | Audit: if uses real CSVs → create sanitized fixture or exclude |
| `tests/mcp_tools/test_import_transactions.py` | Same | Same |
| `tests/fixtures/performance_baseline_2025.json` | Contains real account ID, holdings, dollar values, statement paths. Used by `tests/core/test_realized_performance_analysis.py`. | **Exclude** from sync (add to exclusion list) or create a sanitized version with fake data. Too much real financial data to sed-sweep cleanly. |
| `tests/providers/test_account_aliases.py` | Contains `U2471778` in test data | Sed sweep handles it |
| `tests/ibkr/test_flex.py` | Contains `U2471778` in test fixtures | Sed sweep handles it |
| `tests/services/test_trade_execution_service_preview.py` | Contains `U2471778` | Sed sweep handles it |
| `tests/inputs/test_normalizers.py` | May reference `docs/*.csv` fixture paths | Audit: if references excluded paths → update path or exclude |
| `tests/inputs/test_schwab_csv_normalizer.py` | Same | Same |
| `tests/inputs/test_schwab_position_normalizer.py` | Same | Same |
| `tests/inputs/test_transaction_normalizer_registry.py` | Same | Same |
| `tests/api/test_api_endpoints.py` | References `config/portfolio.yaml` | Replace with `config/portfolio.example.yaml` reference |
| `scripts/collect_all_schemas.py` | References `config/portfolio.yaml` | Same |
| `tests/conftest.py` | Hardcodes `config/portfolio.yaml` path, feeds `tests/utils/test_cli.py` | Redirect to `config/portfolio.example.yaml` |
| `tests/core/test_temp_file_refactor.py` | Hardcodes `config/portfolio.yaml` | Same — redirect to example |

**Action for tests referencing excluded CSV fixtures:**
During Phase 3, run each test in isolation. If it fails because a fixture file was excluded, either:
1. Move the fixture to `tests/fixtures/` with sanitized content
2. Make the test skip if the fixture is missing (`@pytest.mark.skipif`)
3. Exclude the test file from the sync

### 2.5 Script structure

```bash
#!/usr/bin/env bash
# scripts/sync_public_repo.sh
# Syncs risk_module to the public repo, excluding private data.
#
# Usage: ./scripts/sync_public_repo.sh <path-to-public-repo>
# Dry run: ./scripts/sync_public_repo.sh <path-to-public-repo> --dry-run

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:?Usage: $0 <path-to-public-repo> [--dry-run]}"
DRY_RUN="${2:-}"

RSYNC_FLAGS="-av --delete --delete-excluded"
if [[ "$DRY_RUN" == "--dry-run" ]]; then
  RSYNC_FLAGS="-avn --delete --delete-excluded"
  echo "=== DRY RUN MODE (rsync only, no scrub) ==="
fi

echo "=== Step 1: Rsync with exclusions ==="
# --delete-excluded ensures excluded files already in target are removed on re-sync
rsync $RSYNC_FLAGS \
  --exclude='.git' \
  --exclude='.claude' \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='node_modules' \
  --exclude='venv' \
  --exclude='.github/workflows/sync-to-public.yml' \
  --exclude='docs/planning/' \
  --exclude='docs/guides/' \
  --exclude='docs/specs/' \
  --exclude='docs/deployment/' \
  --exclude='docs/prompts/' \
  --exclude='docs/schemas/' \
  --exclude='docs/_archive/' \
  --exclude='docs/architecture/legacy/' \
  --exclude='docs/CHANGELOG.md' \
  --exclude='docs/*.csv' \
  --exclude='CHANGELOG.md' \
  --exclude='AI_CONTEXT.md' \
  --exclude='RELEASE_PLAN.md' \
  --exclude='tests/snaptrade/' \
  --exclude='tests/TESTING_COMMANDS.md' \
  --exclude='tests/reports/' \
  --exclude='tests/diagnostics/' \
  --exclude='config/portfolio.yaml' \
  --exclude='portfolio.yaml' \
  --exclude='backup/' \
  --exclude='user_data/' \
  --exclude='archive/' \
  --exclude='cache_prices/' \
  --exclude='logs/' \
  --exclude='*.log' \
  --exclude='*.tsbuildinfo' \
  --exclude='scripts/secrets_helper.sh' \
  --exclude='scripts/update_secrets.sh' \
  --exclude='scripts/plaid_reauth.py' \
  --exclude='scripts/extract_performance_actual_baseline.py' \
  --exclude='scripts/materialize_ibkr_statement.py' \
  --exclude='scripts/test_first_exit_backfill.py' \
  --exclude='scripts/debug_fmp_ticker_map.py' \
  --exclude='tests/fixtures/performance_baseline_2025.json' \
  "$SOURCE_DIR/" "$TARGET_DIR/"

if [[ "$DRY_RUN" == "--dry-run" ]]; then
  echo "=== Dry run complete. No files modified. ==="
  exit 0
fi

echo ""
echo "=== Step 2: Post-sync pattern scrub (safety net) ==="
cd "$TARGET_DIR"

# Replace personal emails
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/hc@henrychien\.com/user@example.com/g' {} + 2>/dev/null || true
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/support@henrychien\.com/support@example.com/g' {} + 2>/dev/null || true

# Replace IBKR account ID
find . -type f -not -path './.git/*' \
  -not -name '*.png' -not -name '*.jpg' -not -name '*.ico' -not -name '*.woff2' -exec \
  sed -i '' 's/U2471778/<ACCOUNT_ID>/g' {} + 2>/dev/null || true

# Replace absolute home paths (longer pattern first, then shorter)
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's|/Users/henrychien/Documents/Jupyter/risk_module|<PROJECT_ROOT>|g' {} + 2>/dev/null || true
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's|/Users/henrychien|<HOME>|g' {} + 2>/dev/null || true
# Also catch $HOME-relative and tilde paths (broader: any Documents/Jupyter reference)
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's|\$HOME/Documents/Jupyter[^ "]*|<PROJECT_PATH>|g' {} + 2>/dev/null || true
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's|~/Documents/Jupyter[^ "]*|<PROJECT_PATH>|g' {} + 2>/dev/null || true

# Replace EC2 IP address
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/3\.136\.23\.202/<EC2_IP>/g' {} + 2>/dev/null || true

# Replace SnapTrade UUID
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/cb7a1987-bce1-42bb-afd5-6fc2b54bbf12/<SNAPTRADE_USER_ID>/g' {} + 2>/dev/null || true

# Replace personal names (multiple case variants found in codebase)
for name_pattern in 'Henry Chien' 'Henry Souchien' 'HENRY CHIEN' 'HENRY S CHIEN' 'HENRY SOUCHIEN'; do
  find . -type f -not -path './.git/*' -exec \
    sed -i '' "s/$name_pattern/<USER>/g" {} + 2>/dev/null || true
done
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/henry\.souchien@gmail\.com/<USER_EMAIL>/g' {} + 2>/dev/null || true

# Replace any personal bank account numbers found in transaction samples
# BAC account number pattern
find . -type f -not -path './.git/*' -exec \
  sed -i '' 's/BAC#[0-9]\{9,\}/BAC#<REDACTED>/g' {} + 2>/dev/null || true

echo "Pattern scrub complete."

echo ""
echo "=== Sync + scrub complete ==="
echo "Now run the Phase 5 verification checks from the plan doc."
echo ""
echo "*** DO NOT commit until all verification checks pass ***"
```

**Deliverable:** Working sync script with integrated scrub, tested with dry-run.

---

## Phase 3: In-Repo Scrub Edits (~45 min)

Make these edits in the **private repo** (so they flow through sync). These are for files where the generic sed replacement would look bad or break something.

| # | File | Edit | Verify |
|---|------|------|--------|
| 3.1 | `mcp_server.py` | Generalize docstring path | `grep '/Users/henrychien' mcp_server.py` → 0 |
| 3.2 | `database/schema.sql` | Replace seed email + name | `grep -i 'henrychien\|henry.souchien' database/schema.sql` → 0 |
| 3.3 | `tests/utils/create_test_session.py` | Replace email + name → `user@example.com` / `Test User` | grep → 0 |
| 3.4 | `run_snaptrade.py` (root) | Replace docstring emails | grep → 0 |
| 3.5 | `run_plaid.py` (root) | Replace docstring emails | grep → 0 |
| 3.6 | `scripts/run_snaptrade.py` | Replace docstring emails | grep → 0 |
| 3.7 | `scripts/run_plaid.py` | Replace docstring emails | grep → 0 |
| 3.8 | `scripts/explore_transactions.py` | Replace default email | grep → 0 |
| 3.9 | `architecture.md` | Replace path + email → generic | grep → 0 |
| 3.10 | `docs/reference/MCP_SERVERS.md` | Replace path + email → generic | grep → 0 |
| 3.11 | `docs/reference/API_REFERENCE.md` | Replace personal paths/emails → generic | grep → 0 |
| 3.12 | `docs/reference/EARNINGS_ESTIMATES.md` | Replace personal paths → generic | grep → 0 |
| 3.13 | `mcp_tools/README.md` | Replace path + email → generic | grep → 0 |
| 3.14 | `core/realized_performance/aggregation.py` | Replace `U2471778` → `<ACCOUNT_ID>` | grep → 0 |
| 3.15 | `core/realized_performance_analysis.py` | Replace `U2471778` → `<ACCOUNT_ID>` | grep → 0 |
| 3.16 | `ibkr/flex.py` | Replace `U2471778` → `<ACCOUNT_ID>` | grep → 0 |
| 3.17 | `LICENSE` | Write chosen license | Visual check |
| 3.18 | `package.json` | Align license field | `jq .license package.json` matches |
| 3.19 | Create `config/portfolio.example.yaml` | Anonymized sample portfolio | No real tickers/quantities |
| 3.20 | `CLAUDE.md` | Remove/generalize memory file references | No personal paths |
| 3.21 | `README.md` | Remove private sync workflow refs, PAT rotation, internal infra details | `grep PUBLIC_REPO_TOKEN README.md` → 0 |
| 3.22 | `docs/interfaces/test-matrix.md` | Remove `PUBLIC_REPO_TOKEN` / sync workflow references | `grep PUBLIC_REPO_TOKEN docs/interfaces/test-matrix.md` → 0 |
| 3.23 | `.env.example` | Verify no real values (currently clean) | Visual check |
| 3.24 | Audit test fixtures (2.4 table) | Fix or exclude broken tests | `pytest` passes in public repo |

**Deliverable:** All edits committed. Private repo still works. Tests pass.

---

## Phase 4: Verify + Create Public Repo + Push (~20 min)

**CRITICAL:** Verification runs BEFORE any commit/push to public repo.

```bash
# 1. Create empty repo on GitHub
gh repo create henrysouchien/<repo-name> --public --description "Portfolio risk analysis + MCP tools"

# 2. Clone it
git clone git@github.com:henrysouchien/<repo-name>.git /path/to/public-repo

# 3. Run sync (dry-run first to check exclusions)
./scripts/sync_public_repo.sh /path/to/public-repo --dry-run
# Review output — spot-check exclusions are working

# 4. Run actual sync (rsync + pattern scrub)
./scripts/sync_public_repo.sh /path/to/public-repo

# 5. *** RUN VERIFICATION BEFORE COMMITTING ***
# (See Phase 5 below — run ALL checks)
# If ANY check fails, DO NOT commit. Fix source, re-sync.

# 6. Only after all checks pass:
cd /path/to/public-repo
git add -A
git commit -m "Initial public release"
git push origin main
```

**Deliverable:** Public repo live on GitHub with verified clean content.

---

## Phase 5: Verification (~15 min)

Run **before committing** to public repo (integrated into Phase 4 step 5).

Use `git ls-files` (not raw `grep -r .`) for deterministic results on tracked files only:

```bash
cd /path/to/public-repo
# Stage all files first so git ls-files works on the initial commit
git add -A

FAIL=0

echo "=== Pattern checks (must all return 0 results) ==="

for pattern in \
  'hc@henrychien.com' \
  'support@henrychien.com' \
  'henry.souchien@gmail.com' \
  'Henry Chien' \
  'HENRY CHIEN' \
  'HENRY S CHIEN' \
  'Henry Souchien' \
  'HENRY SOUCHIEN' \
  'U2471778' \
  '/Users/henrychien' \
  'Documents/Jupyter' \
  '3.136.23.202' \
  'cb7a1987-bce1-42bb-afd5-6fc2b54bbf12'; do
  HITS=$(git ls-files -z | xargs -0 grep -l "$pattern" 2>/dev/null || true)
  if [[ -n "$HITS" ]]; then
    echo "FAIL: '$pattern' found in:"
    echo "$HITS"
    FAIL=1
  else
    echo "PASS: no '$pattern'"
  fi
done

# API key patterns
HITS=$(git ls-files -z | xargs -0 grep -lE 'sk-ant|sk-proj|AKIA[A-Z0-9]{16}' 2>/dev/null || true)
if [[ -n "$HITS" ]]; then
  echo "FAIL: API key pattern in: $HITS"
  FAIL=1
else
  echo "PASS: no API key patterns"
fi

# Legacy workflow file must not be present (highest-priority leak vector)
[[ -f .github/workflows/sync-to-public.yml ]] && echo "FAIL: sync-to-public.yml present" && FAIL=1 || echo "PASS: no legacy sync workflow"

# Bank account numbers (from transaction samples)
HITS=$(git ls-files -z | xargs -0 grep -lE 'BAC#[0-9]{9,}' 2>/dev/null || true)
if [[ -n "$HITS" ]]; then
  echo "FAIL: Bank account number pattern in: $HITS"
  FAIL=1
else
  echo "PASS: no bank account numbers"
fi

# Internal infrastructure references
for pattern in 'PUBLIC_REPO_TOKEN' 'sync-to-public.yml'; do
  HITS=$(git ls-files -z | xargs -0 grep -l "$pattern" 2>/dev/null || true)
  if [[ -n "$HITS" ]]; then
    echo "FAIL: '$pattern' found in: $HITS (internal infra reference leaked)"
    FAIL=1
  fi
done

echo ""
echo "=== Binary/data file checks ==="

HITS=$(git ls-files '*.sqlite' '*.pdf' '*.mhtml' | grep -v node_modules || true)
[[ -n "$HITS" ]] && echo "FAIL: binary data: $HITS" && FAIL=1 || echo "PASS: no binary data"

# No CSVs under docs/ at all (all are personal financial data)
HITS=$(git ls-files 'docs/*.csv' 'docs/**/*.csv' || true)
[[ -n "$HITS" ]] && echo "FAIL: CSV files in docs/: $HITS" && FAIL=1 || echo "PASS: no CSVs in docs/"

echo ""
echo "=== Directory exclusion checks ==="

for dir in docs/planning docs/guides docs/specs docs/deployment docs/prompts docs/schemas docs/_archive docs/architecture/legacy tests/snaptrade tests/reports tests/diagnostics .claude archive backup; do
  [[ -d "$dir" ]] && echo "FAIL: $dir exists" && FAIL=1 || echo "PASS: $dir excluded"
done

echo ""
echo "=== Sensitive file exclusion checks ==="

# These specific files/dirs must not be present (full exclusion contract)
for f in \
  config/portfolio.yaml portfolio.yaml \
  tests/fixtures/performance_baseline_2025.json \
  .github/workflows/sync-to-public.yml \
  scripts/secrets_helper.sh scripts/update_secrets.sh scripts/plaid_reauth.py \
  scripts/extract_performance_actual_baseline.py scripts/materialize_ibkr_statement.py \
  scripts/test_first_exit_backfill.py scripts/debug_fmp_ticker_map.py \
  CHANGELOG.md AI_CONTEXT.md RELEASE_PLAN.md docs/CHANGELOG.md \
  tests/TESTING_COMMANDS.md; do
  [[ -e "$f" ]] && echo "FAIL: $f exists (should be excluded)" && FAIL=1 || echo "PASS: $f excluded"
done

# Excluded directories must also not exist (redundant with dir check above, but covers any additions)
for d in user_data cache_prices logs; do
  [[ -d "$d" ]] && echo "FAIL: $d/ exists" && FAIL=1 || echo "PASS: $d/ excluded"
done

echo ""
echo "=== Structural checks ==="

[[ -f .env.example ]] && echo "PASS: .env.example exists" || echo "WARN: .env.example missing"
HITS=$(grep -E '=.{10,}' .env.example 2>/dev/null | grep -vE '=<|=your|=example|=\$|=true|=false|=production|=development' || true)
[[ -n "$HITS" ]] && echo "FAIL: .env.example may have real values: $HITS" && FAIL=1 || echo "PASS: .env.example clean"

[[ -f README.md ]] && echo "PASS: README.md exists" || { echo "FAIL: README.md missing"; FAIL=1; }
[[ -d inputs ]] && echo "PASS: inputs/ present (app code)" || { echo "FAIL: inputs/ missing"; FAIL=1; }

echo ""
if [[ $FAIL -eq 1 ]]; then
  echo "*** VERIFICATION FAILED — DO NOT COMMIT ***"
  echo "Fix issues in source repo and re-run sync."
  git reset HEAD . > /dev/null 2>&1  # unstage
  exit 1
else
  echo "*** ALL CHECKS PASSED — safe to commit ***"
fi
```

**Deliverable:** All checks pass. Script exits 0. Safe to commit.

---

## Phase 6: Post-Publish Actions

| # | Action | Notes |
|---|--------|-------|
| 6.1 | **Rotate ALL API keys** | Keys have been in `.env` in private git history. Rotate: FMP, OpenAI, Anthropic, AWS, Plaid, Schwab, SnapTrade, Google OAuth, IBKR Flex tokens, admin token, Edgar key |
| 6.2 | **Update DEPLOY_CHECKLIST.md** | Add public repo to sync table |
| 6.3 | **Verify README** (public repo) | Phase 3.21 should have cleaned it. Double-check setup instructions are self-contained. |
| 6.4 | **Add GitHub topics/description** | `portfolio-management`, `risk-analysis`, `mcp`, `python` |
| 6.5 | **Clean up legacy public repo** | If `portfolio-risk-engine` has stale/leaked data from the old workflow, either delete it or scrub it |

---

## Total Effort

| Phase | Effort |
|-------|--------|
| 1. Decisions + workflow disable | 15 min |
| 2. Sync script | 30 min |
| 3. In-repo edits | 45 min |
| 4. Verify + create + push | 20 min |
| 5. (integrated into 4) | — |
| 6. Post-publish | 30 min (key rotation) |
| **Total** | **~2.5 hours** |

---

## Ordering vs. Other Phases

- **Phase 1.4 (disable legacy workflow) is the FIRST action** — if left active, any push to main leaks private data
- **Can run independently of 1B and 3J** — no dependency on deployment infra
- **Should complete before 3J** if the public repo is what gets deployed
- **Key rotation (6.1) should happen after deployment** — don't rotate keys you're actively using until the new deployment is using fresh ones
- **Phase 6.5 (clean legacy repo)** — check if `portfolio-risk-engine` has leaked data from the old workflow
