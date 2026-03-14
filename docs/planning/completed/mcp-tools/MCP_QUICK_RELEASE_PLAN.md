# Quick Release: gsheets-mcp, drive-mcp, gmail-mcp

Phase 1 of the weekend sprint — push three already-built MCP servers to public GitHub repos.

**Status:** Completed
**Date:** 2026-02-23

---

## Prerequisites (do first)

- [x] **Re-authenticate `gh`** — current token is invalid. Run `gh auth login`.
- [x] **Pick a license** — MIT is standard for this kind of infra. Add `LICENSE` file to each repo.

---

## Release Order

Ship in order of readiness: gsheets-mcp → drive-mcp → gmail-mcp.

---

## 1. gsheets-mcp

**Location:** `~/Documents/Jupyter/gsheets-mcp/`
**Tools:** 8 — `gsheet_list_tabs`, `gsheet_read_range`, `gsheet_update_range`, `gsheet_append_rows`, `gsheet_create`, `gsheet_search`, `gsheet_clear_range`, `gsheet_touch_range`

**Current state:**
- Git repo with 2 clean commits, working tree clean
- Has: `pyproject.toml`, `.gitignore`, 11 unit tests
- No credentials in git history (verified)
- Missing: README, LICENSE

**Steps:**
- [x] Write `README.md` (see template below)
- [x] Add `LICENSE` (MIT)
- [x] Add `license`, `authors`, `classifiers` to `pyproject.toml`
- [x] `git add README.md LICENSE pyproject.toml && git commit`
- [x] Run safety checks (see below)
- [x] `gh repo create gsheets-mcp --public --description "MCP server for Google Sheets operations" --source . --remote origin --push`
- [x] `git tag -a v0.1.0 -m "v0.1.0"` + `git push origin v0.1.0`

---

## 2. drive-mcp

**Location:** `~/Documents/Jupyter/drive-mcp/`
**Tools:** 10 — `gdrive_list_folder`, `gdrive_list_folder_recursive`, `gdrive_search`, `gdrive_read_file`, `gdrive_rename`, `gdrive_move`, `onedrive_list_root`, `onedrive_list_folder`, `onedrive_search`, `onedrive_read_file`

**Current state:**
- Already a git repo (has `.git/`) with dirty working tree
- Has: `pyproject.toml`, `.gitignore` (credentials excluded), README (outdated — says 8 tools, actually 10)
- Credentials on disk but gitignored
- Needs cleanup: `error_logs/`, `RELEASE_PLAN.md`, `TODO.md`
- README has hardcoded local paths (`/Users/henrychien/...`) that need scrubbing

**Steps:**
- [x] Delete `error_logs/`, `RELEASE_PLAN.md`, `TODO.md`
- [x] Update `README.md`:
  - Add `gdrive_rename` + `gdrive_move` to tools table, fix count to 10
  - Replace all hardcoded `/Users/henrychien/...` paths with generic `/path/to/drive-mcp`
- [x] Add `LICENSE` (MIT)
- [x] Add `license`, `authors`, `classifiers` to `pyproject.toml`
- [x] Stage explicitly: `git add .gitignore pyproject.toml README.md LICENSE run_server.py src/`
- [x] Verify: `git status` shows no `.json`, `.pickle`, or token files
- [x] `git commit`
- [x] Run safety checks (see below)
- [x] `gh repo create drive-mcp --public --description "MCP server for Google Drive and OneDrive" --source . --remote origin --push`
- [x] `git tag -a v0.1.0 -m "v0.1.0"` + `git push origin v0.1.0`

**Note:** `src/onedrive.py` has hardcoded Azure Client ID and Tenant ID (lines 24-25). These are public app registration IDs for device-code flow — safe to publish, standard practice for MSAL public clients.

---

## 3. gmail-mcp

**Location:** `~/Documents/Jupyter/gmail-mcp/`
**Tools:** 8 — `gmail_list_labels`, `gmail_list_inbox`, `gmail_search_emails`, `gmail_read_email`, `gmail_send_email`, `gmail_reply_email`, `gmail_manage_labels`, `gmail_delete_email`

**Current state:**
- NOT a git repo yet
- Has: `pyproject.toml`
- **NO `.gitignore`** — `gmail_credentials.json` and `gmail_token.pickle` are unprotected
- Missing: README, LICENSE
- Needs cleanup: `src/__pycache__/`, `error_logs/` (copied from another project)

**Known bug:** `reply_all=True` in `gmail_reply_email` computes recipients but doesn't use the variable (`src/server.py:244-270`). Fix before release.

**Steps:**
- [x] **Create `.gitignore` FIRST** — must happen before `git init`
  - Exclude: `gmail_credentials.json`, `gmail_token.pickle`, `venv/`, `__pycache__/`, `error_logs/`, `*.pyc`, `.DS_Store`
- [x] Delete `src/__pycache__/`, `error_logs/`
- [x] Fix `reply_all` bug in `src/server.py`
- [x] Write `README.md` (see template below)
- [x] Add `LICENSE` (MIT)
- [x] Add `license`, `authors`, `classifiers` to `pyproject.toml`
- [x] `git init`
- [x] `git add .gitignore pyproject.toml README.md LICENSE run_server.py src/` (explicit add only)
- [x] Verify: `git status` shows no `gmail_credentials.json` or `gmail_token.pickle`
- [x] `git commit`
- [x] Run safety checks (see below)
- [x] `gh repo create gmail-mcp --public --description "MCP server for Gmail" --source . --remote origin --push`
- [x] `git tag -a v0.1.0 -m "v0.1.0"` + `git push origin v0.1.0`

---

## Safety Protocol (run before each `gh repo create`)

```bash
# 1. Confirm gh is authenticated
gh auth status

# 2. No credential files staged or committed
git status                          # no .json, .pickle, or token files
git show HEAD --stat                # only source files in commit
git log --all --name-only | grep -iE '\.json|\.pickle|token|credential|secret'  # must be empty

# 3. .gitignore covers credentials
git check-ignore drive_credentials.json gmail_credentials.json token.pickle gmail_token.pickle onedrive_token_cache.json

# 4. No hardcoded local paths in committed files
git show HEAD -p | grep -i '/Users/'   # must be empty
```

---

## README Template (consistent across all 3)

```markdown
# {repo-name}

One-line description.

## Tools

| Tool | Description |
|------|-------------|
| ... | ... |

## Setup

### Prerequisites
- Python 3.10+
- {service} account with API access

### Installation
\`\`\`bash
git clone https://github.com/{user}/{repo-name}.git
cd {repo-name}
python3 -m venv venv
source venv/bin/activate
pip install -e .
\`\`\`

### Authentication
{First-time OAuth flow instructions}

### Claude Code Configuration
Add to `~/.claude.json`:
\`\`\`json
{
  "mcpServers": {
    "{repo-name}": {
      "type": "stdio",
      "command": "/path/to/{repo-name}/venv/bin/python",
      "args": ["/path/to/{repo-name}/run_server.py"]
    }
  }
}
\`\`\`

## Development
{Running tests, adding new tools}

## License
MIT
```

---

## Post-Release Verification

- [x] `gh repo list --limit 10` — all 3 repos exist and are public
- [x] Visit each repo URL — README renders, no secrets visible
- [x] Each has a v0.1.0 tag
- [x] Update `RELEASE_PLAN.md` in risk_module to mark Phase 1 items complete
