# F63 — Claude Code stdio MCP cwd not honored when cwd is a Python package

**Filed:** 2026-05-04 (during V2.P10 R20 follow-up)
**Status:** RESOLVED LOCALLY 2026-05-04; upstream Claude Code cwd behavior remains an external bug to file.
**Affected servers:** `research-workbench-mcp`, `jobs-mcp`, `options-mcp`, `fred-mcp`, `macro-mcp` (all with `cwd=/Users/henrychien/Documents/Jupyter/investment_tools`)

## Symptom

Five stdio MCP servers configured with `cwd: /Users/henrychien/Documents/Jupyter/investment_tools` fail to load on Claude Code startup. Their tools never appear in the catalog. Per-server logs at `~/Library/Caches/claude-cli-nodejs/-Users-henrychien-Documents-Jupyter-risk-module/mcp-logs-<server>/*.jsonl` all show:

```
Server stderr: /Library/Frameworks/Python.framework/Versions/3.13/bin/python3: Error while finding module specification for 'research.server' (ModuleNotFoundError: No module named 'research')
Connection failed after ~40ms: MCP error -32000: Connection closed
```

(Module name varies per server: `jobs.server`, `options_mcp.server`, `fred_mcp.server`, `macro_mcp.server`.)

## Diagnosis

Reproducible asymmetry — same launch shape works for some cwds, fails for others:

| Server | cwd | cwd has root `__init__.py`? | Result |
|---|---|---|---|
| `finance-cli` | `/Users/henrychien/Documents/Jupyter/finance_cli` | NO | ✅ connects |
| `fmp-mcp` | `/Users/henrychien/Documents/Jupyter/risk_module` | NO | ✅ connects |
| `research-workbench-mcp` | `/Users/henrychien/Documents/Jupyter/investment_tools` | **YES** | ❌ ModuleNotFoundError |
| `jobs-mcp`, `options-mcp`, `fred-mcp`, `macro-mcp` | same as above | **YES** | ❌ ModuleNotFoundError |

Manual reproduction confirms Python is correct:

```bash
# From outside investment_tools:
python3 -m research.server                          # ModuleNotFoundError (expected)
PYTHONPATH=$INVESTMENT_TOOLS python3 -m research.server   # works

# subprocess.run with cwd= explicitly:
subprocess.run(['python3','-m','research.server'], cwd=INVESTMENT_TOOLS)  # works
```

So `python3 -m` does honor cwd → adds `''` to `sys.path[0]` → finds `research`. But Claude Code's spawn isn't reaching that state for cwds that are themselves Python packages (have `__init__.py`).

**Hypothesis (unconfirmed):** Claude Code's stdio MCP launcher conditionally suppresses the `cwd` argument, sets it to the session cwd, or runs Python with a working directory whose ancestor `__init__.py` shadows the intended package root via implicit-namespace-package detection. Diagnosing the spawn requires Claude Code source / debug instrumentation we don't have access to.

The symptom is consistent regardless of which session/profile launches Claude Code — it reproduces in fresh sessions launched from any cwd.

## Workaround applied (2026-05-04)

Added `"PYTHONPATH": "/Users/henrychien/Documents/Jupyter/investment_tools"` to the `env` block of all 5 affected entries in `~/.claude.json`. PYTHONPATH is honored regardless of cwd-handling, so this sidesteps the issue without changing package layout.

Backup of pre-fix config: `~/.claude.json.bak.20260504-135344`.

Verification: restart Claude Code, then `mcp-logs-<server>/*.jsonl` should show "Successfully connected" instead of ModuleNotFoundError. Tools surface normally in the catalog after that.

## Restart verification (2026-05-04)

After Claude Code restart, 3 of 5 servers fully resolved:
- ✅ `research-workbench-mcp` — connected, 20 tools (`mcp__research-workbench-mcp__*`) in catalog.
- ✅ `jobs-mcp` — connected.
- ✅ `fred-mcp` — connected.
- ❌ `options-mcp` — got past ModuleNotFoundError on `options_mcp` but failed on `from options.helpers import ...` at `options_mcp/server.py:21`.
- ❌ `macro-mcp` — same downstream failure at `macro_mcp/server.py:25`.

**Second-order bug surfaced by the workaround:** PYTHONPATH only **adds** to `sys.path`; it can't override `sys.path[0] == ''` (the cwd). When the spawn cwd is `risk_module` (Claude Code's session cwd, since cwd field is being ignored), `import options` resolves to `risk_module/options/__init__.py` — which exists but lacks `helpers.py` — instead of `investment_tools/options/helpers.py` from PYTHONPATH. PYTHONPATH workaround works only when there's no name collision between cwd and the intended package root. Verified by `import options; options.__file__` → `/Users/henrychien/Documents/Jupyter/risk_module/options/__init__.py` even with PYTHONPATH set.

**Second fix applied:** for `options-mcp` and `macro-mcp`, switched the catalog entry to a shell wrapper that explicitly `cd`s before exec'ing python:
```json
"command": "/bin/bash",
"args": ["-c", "cd /Users/henrychien/Documents/Jupyter/investment_tools && exec python3 -m options_mcp.server"]
```
The `cd` forces the child Python's actual cwd to investment_tools, so `sys.path[0]==''` resolves correctly without depending on Claude Code honoring the `cwd` field. Backup: `~/.claude.json.bak.<timestamp>` before the second edit.

## Final local resolution (2026-05-04)

Latest risk-module Claude logs show all five affected servers connected:
- `research-workbench-mcp`
- `jobs-mcp`
- `fred-mcp`
- `options-mcp`
- `macro-mcp`

For consistency, all five `~/.claude.json` entries now use the shell-wrapper pattern:
```json
"command": "/bin/bash",
"args": ["-c", "cd /Users/henrychien/Documents/Jupyter/investment_tools && exec python3 -m <module>.server"]
```

This makes the child process's actual cwd deterministic and avoids depending on Claude Code's `cwd` handling. Existing env blocks, including `PYTHONPATH`, remain in place. Backup before standardization: `~/.claude.json.bak.20260504-192236-f63`.

## Why not other fixes

- **Removing `investment_tools/__init__.py`** would break `from investment_tools.jobs.runner import now_iso` at `investment_tools/research/server.py:36` plus other intra-repo imports. Package layout is load-bearing.
- **Renaming the cwd to a non-package dir** is intrusive and breaks the same imports.
- **Wrapper files on disk** would also work, but the inline `/bin/bash -c "cd ... && exec python3 -m ..."` entries avoid adding local script files.

## Upstream bug to file (Anthropic / Claude Code)

**Title:** stdio MCP server cwd field appears not honored when cwd has root `__init__.py`

**Repro:**
1. Add a stdio MCP server entry to `~/.claude.json` with `cwd` pointing at a Python package root (a directory with `__init__.py`).
2. Use `args: ["-m", "<subpkg>.server"]` where `<subpkg>` is a sub-package of that root.
3. Restart Claude Code.
4. Observe `mcp-logs-<server>/*.jsonl` — connection fails with `ModuleNotFoundError: No module named '<subpkg>'`.
5. Compare against an identical config where the cwd does **not** have a root `__init__.py` — connects fine.

**Expected:** child Python process inherits cwd, finds the sub-package via `sys.path[0] == ''` resolution.

**Actual:** child can't find the sub-package, suggesting cwd was not applied (or applied in a way Python's `-m` resolution doesn't pick up).

**Workaround:** explicitly `cd` in the stdio command before `exec python3 -m ...`.

## Follow-up actions

- [x] Verify workaround works after Claude Code restart; latest risk-module MCP logs show all five affected servers connected.
- [ ] File upstream bug with Anthropic (or claude-code repo if open-source surface exists). External follow-up, not active risk-module queue.
- [ ] Remove workaround if/when upstream fix lands. External follow-up, not active risk-module queue.
