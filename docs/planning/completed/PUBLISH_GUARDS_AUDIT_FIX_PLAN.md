# Publish Guards: pip-audit Scope + ERR Trap Fix

## Status: v2 — addresses Codex R1 CHANGES_REQUESTED

Scoped fix for `publish_guards.sh` — addresses bugs surfaced during the `ai-agent-gateway 0.10.0` and `app-platform 0.8.0` publishes on 2026-04-23.

**R1 corrections:**
- **Blocker fixed**: `pip-audit -P <wheel>` is not a valid flag in 2.10.0. Replaced with the `pip-audit <project_path>` positional form, which parses `pyproject.toml [project].dependencies` from the dist repo. Verified against `/Users/henrychien/Documents/Jupyter/app-platform-dist` and `/Users/henrychien/Documents/Jupyter/agent-gateway-dist` — both return `No known vulnerabilities found` (exit 0).
- **Wheel detection removed**: not needed since we pass `$dest` directly.
- **risk_module pipeline bug recharacterized**: Codex verified on bash 3.2.57 that the current pipeline form does NOT trip the ERR banner — its actual bug is that `pipefail + grep-matches + ||-echo` can print matching CVEs AND `No CVEs found` on the same run, then return success. Both forms need replacing.
- **`set +E` confirmed**: Codex and I both independently verified on bash 3.2.57 that `set +E` around a `$()` capture suppresses the inherited ERR trap while preserving the inner exit code via `|| rc=$?`. Simple grouping and `set +e` do not suppress it.

## Context

`scripts/publish_guards.sh` is sourced by each `publish_<pkg>.sh` script and runs pre-upload integrity checks (artifact-name match + SHA256 + dependency CVE audit). The audit was meant to verify "the package's declared dependencies" (per inline comment) but is broken in two ways — and the two in-tree copies have drifted.

### Bug 1 — Wrong audit scope (substantive, both files)

The audit runs `pip-audit --desc on` with no args, which scans the **active Python environment**, not the package's declared deps. The `grep -iE "^($pypi_name|fastapi|PyJWT|mcp|httpx|pydantic|anthropic|fastmcp)"` filter is a blunt second-line defense — it only surfaces hits if the active env happens to pin a vulnerable version of those named libs.

Consequences:
- Publishing from a dev machine with a clean active env but a wheel that pins vulnerable upstream → audit reports clean, publish proceeds.
- Publishing from a dirty dev env surfaces CVEs that have nothing to do with the package being shipped.
- Results change between machines.

Correct scope: audit the dist repo's `[project].dependencies` (what `pip install <pkg>` would actually pull). `pip-audit` accepts a positional `project_path` and parses PEP 621 pyproject.toml deps.

### Bug 2 — ERR trap false positive (cosmetic, AI-excel-addin form only)

AI-excel-addin's `publish_guards.sh:66` captures pip-audit via `audit_output="$(python3 -m pip_audit ... 2>&1)" || audit_rc=$?`. The parent publish scripts use `set -Eeuo pipefail` with `trap '_on_error $LINENO' ERR`. `set -E` inherits the ERR trap into `$()` subshells. When `pip-audit` exits 1 (vulnerabilities found — a normal signal, not a failure), the trap fires **inside the subshell**, prints `ERROR at step "integrity_check"...` on stderr, and `exit 1` terminates the subshell only. The outer `|| audit_rc=$?` captures the exit and the parent script continues.

Net effect: scary stderr banner during a successful run. Confirmed by the `ai-agent-gateway 0.10.0` publish output today.

### Bug 3 — pipeline-form result bug (substantive, risk_module form only)

risk_module's `publish_guards.sh:66` has:

```bash
pip-audit --desc on 2>/dev/null | grep -iE "^(...)" || echo "  No CVEs found in core deps"
```

With `pipefail`, the pipeline's exit code is the rightmost non-zero. If pip-audit exits 1 (CVEs found) and grep exits 0 (matched a CVE line), `pipefail` yields 1 → `||` fires → prints "No CVEs found in core deps" **after** the matched CVE line already printed. The audit both reports and hides the problem on the same run.

Codex confirmed: bash 3.2.57 on this machine does NOT trip the ERR banner in this form (unlike the `$()` form); this bug is purely about wrong result logic.

### Bug 4 — The two files have drifted

- `risk_module/scripts/publish_guards.sh` — pipeline form, permissive (just prints hits, keeps going). Bug 3.
- `AI-excel-addin/scripts/publish_guards.sh` — captured form with exit-code discrimination, strict (exits 1 on filtered hits). Bug 2.

Neither has the scope fix. Both need replacing. Single-source consolidation is tracked separately.

## Proposed Fix

Align both files to one implementation that fixes all three issues. Two-commit delivery (one per repo).

### New `check_build_integrity` audit block

```bash
# Audit the package's declared dependencies for known CVEs.
# Scoped to the dist repo's pyproject.toml [project].dependencies (what
# `pip install <pkg>` actually pulls) — reproducible across dev machines.
if python3 -m pip_audit --version >/dev/null 2>&1; then
  echo "Auditing package dependencies..."

  # pip-audit exit codes: 0=clean, 1=vulns found (normal signal), >1=operational
  # error. Suppress ERR trap inheritance so the exit=1 case doesn't print the
  # _on_error banner from within the $() subshell (confirmed needed on bash
  # 3.2.57 per Codex R1 verification).
  local audit_output audit_rc=0
  set +E
  audit_output="$(python3 -m pip_audit "$dest" --desc on 2>&1)" || audit_rc=$?
  set -E

  if [[ $audit_rc -gt 1 ]]; then
    echo "ERROR: pip-audit failed (exit $audit_rc). Fix the audit environment before publishing." >&2
    echo "$audit_output" | tail -10 >&2
    exit 1
  fi

  # Fail closed: any CVE in the package's declared deps blocks publish.
  # No grep filter — every hit is in-scope once we audit the project.
  if [[ $audit_rc -eq 1 ]]; then
    echo "$audit_output"
    echo "ERROR: dependency CVEs found in package. Update affected packages in pyproject.toml before publishing." >&2
    exit 1
  fi

  echo "  No CVEs found in package dependencies"
fi
```

### Key changes vs current state

| Aspect | risk_module (current) | AI-excel-addin (current) | Both (after fix) |
|---|---|---|---|
| Audit scope | Active env | Active env | **Project (`$dest` positional)** |
| ERR trap banner | No (pipeline form) | Yes (via `$()` subshell) | **No (`set +E` guard)** |
| Result logic | **Bug**: can print hits + "no CVEs" + succeed | Hits exit 1 | Hits exit 1 |
| Invocation | `pip-audit` | `python3 -m pip_audit` | `python3 -m pip_audit` |
| grep filter | Kept | Kept | **Removed** (project scope makes all hits relevant) |

### Why `set +E` not `|| true`

`|| true` on `pip-audit` would clobber `audit_rc` and lose the signal that distinguishes "CVEs found" (rc=1) from "operational error" (rc>1). `set +E` only disables ERR trap inheritance for the subshell; the exit code still reaches `audit_rc=$?`. Verified on bash 3.2.57 by both reviewers.

### Scope: base deps only (no extras, no dev deps)

`pip-audit <project_path>` reads `[project].dependencies` from pyproject.toml. It does NOT read `[project.optional-dependencies]` or dev/test deps. That is the correct default for a publish gate — we want to block if `pip install <pkg>` (no extras) would pull a vulnerable lib. Opt-in extras and dev tooling are the consumer's problem, not the package's.

## Files

- `risk_module/scripts/publish_guards.sh` — replace `check_build_integrity` audit block (lines 63–67 currently)
- `AI-excel-addin/scripts/publish_guards.sh` — same replacement (currently different shape, same scope bug)

## Verification (manual — no unit test framework for shell scripts)

1. **Clean publish**: run `./scripts/publish_app_platform.sh --yes` against a clean wheel → prints `No CVEs found in package dependencies`, proceeds to upload. Already verified by running `pip-audit /Users/henrychien/Documents/Jupyter/app-platform-dist` directly → exit 0, "No known vulnerabilities found".
2. **CVE-found publish**: temporarily add a vulnerable pin (e.g., `requests==2.19.0`) to dist pyproject.toml, run publish → exit 1 with CVE printed, NO banner on stderr, NO upload.
3. **Operational failure**: simulate DNS failure → exit 1 with "pip-audit failed" message, last 10 lines of output shown.
4. **Visual**: no `ERROR at step "integrity_check"` banner should appear for either success or vuln-found cases.

## Risks / Edge Cases

- **pip-audit network dep**: `pip-audit <project>` fetches the PyPI advisory DB. Offline publish is now a hard fail (currently silently succeeds). Acceptable — publishing while offline is unusual and should be blocked for safety.
- **New transitive CVEs block publishes**: strict mode means any new upstream CVE in a declared dep blocks publishing until pinned/upgraded. This is the intended behavior; the current permissive/env-scoped mode was itself the bug.
- **pyproject.toml parse failure**: if the dist pyproject.toml is malformed, pip-audit exits >1 — handled by the operational-error branch.

## Non-goals

- Consolidating the two `publish_guards.sh` files into a single shared location (tracked separately; the drift is real but solvable after this fix).
- Switching to a different audit tool (e.g., `safety`, `osv-scanner`).
- Caching advisory DB between runs.
- Auditing lockfiles (`--locked`) — would require maintaining a lock in each dist repo, out of scope.
