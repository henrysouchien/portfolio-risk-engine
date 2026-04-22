# Portfolio Math Sandbox Mount (PM1A — subprocess-only) — Phase 3 Plan

**Parent plan**: `AGENT_SURFACE_AUDIT.md` (post-Phase-2 follow-up)
**Predecessor**: `PORTFOLIO_MATH_EXTRACTION_PLAN.md` (Phase 2, SHIPPED)
**Status**: **SHIPPED 2026-04-19** — approved v4 Codex PASS (R1-R4), implemented cleanly

## Ship log

Plan approved after 4 Codex review rounds. Implementation:

| Commit | Repo | Summary |
|---|---|---|
| `cf1b726` | AI-excel-addin | Renamed `_prepare_env_with_risk` → `_prepare_env_with_host_paths` with realpath dedupe. Added availability + routing prompt bullets. New subprocess-pinned integration test (`register_docker=False`) verifies `import portfolio_math; black_scholes_price(...)` against canonical 8.051. 11 tests in `tests/test_code_execute.py` pass. |
| `7c9d417e` | risk_module | `docs/TODO.md` — PM1A → DONE with SHA; PM1B placeholder added for docker parity. |

**Live smoke** (post-ship verification against real subprocess sandbox + live risk_module on localhost:5001):
- Pure compute in sandbox: `black_scholes_price(S=200, K=210, ...) → $8.051`, IV round-trip exact
- HTTP + local compose: `_risk.get_returns_series(...)` → `portfolio_math.compute_correlation_matrix` / `compute_portfolio_volatility` / `compute_risk_contributions` — invariant `sum(contribs) = vol = 0.0349` holds
- Typed dataclass: `PerformanceMetrics.risk_adjusted_returns.sharpe_ratio` = 0.851, etc.
- All 3 sandbox invocations return_code=0, ~1.7-2s each

**Known gap documented as PM1B**: docker backend doesn't volume-mount host paths + lacks `statsmodels`. Separate plan.

---
**Date**: 2026-04-17

---

## 1. Goal

Make `portfolio_math` importable inside AI-excel-addin's **subprocess-backend** code-execution sandbox, matching how `risk_client` is mounted today. Once PM1A lands, agents running code in the subprocess backend can do `import portfolio_math as pm` alongside the existing `_RiskClient` import.

**Scope deliberately narrowed after Codex R1**: docker-backend parity is a separate follow-up (PM1B) because it requires a Docker image rebuild (add `statsmodels`) plus a real path-mount into the container (currently only the session workdir is mounted). Subprocess-only is the correct MVP — it matches exactly how `_risk` / `RiskClient` are used today per `api/agent/shared/system_prompt.py:696`.

## 2. Current state (verified)

**How risk_client reaches the sandbox (subprocess only)**:
```
.env: RISK_CLIENT_PATH=/Users/.../risk_module
  ↓
api/agent/interactive/runtime.py:125-130  _prepare_env_with_risk()  reads env var, prepends to PYTHONPATH
  ↓
packages/agent-gateway/agent_gateway/code_execution/_config.py  CodeExecutionConfig.prepare_env (single callback slot)
  ↓
subprocess backend  inherits PYTHONPATH env var; Python resolves `from risk_client import ...`
  ↓
preamble at runtime.py:93-99  does `from risk_client import RiskClient as _RiskClient`
```

**How docker backend currently behaves (IMPORTANT)**:
- `_docker.py:155, 321` — only the per-session workdir gets mounted into `/workspace`; host paths like `/Users/.../risk_module` are not volume-mounted into the container.
- Docker container has matplotlib/numpy/pandas/scipy/sympy pre-installed (per `api/Dockerfile.code-exec:6`), but NOT statsmodels.
- `import portfolio_math` eagerly loads `stats.py` which imports `statsmodels` (`portfolio_math/__init__.py:17` → `stats.py:9`) — fails in docker.
- `_handlers.py:41` prefers docker when available; `system_prompt.py:696` instructs the model to use `host="subprocess"` for `_risk` flows.

So subprocess-only is the **existing working pattern**. PM1A replicates it for portfolio_math without tackling docker.

## 3. Design decisions

### D1: No preamble injection for portfolio_math (Codex R1 correction)

Risk_client preamble injects `_RiskClient` because it's a pre-instantiated helper — the agent uses the same client instance across calls. Portfolio_math is a plain library; the agent imports what it needs when it needs it:

```python
# Agent-written code (not preamble):
import portfolio_math as pm
metrics = pm.compute_performance_metrics(...)
```

No preamble changes. Plan previously had D1 = "namespace import in preamble" — rejected after Codex R1. Benefits: avoids eager load of `statsmodels` path at every sandbox boot; matches "library" semantics.

### D2: Single generic env-prep helper (Codex R1 correction)

`CodeExecutionConfig.prepare_env` accepts ONE callback. Previous plan's "separate callback per package" was impossible as written.

**Chosen**: replace `_prepare_env_with_risk(env)` with a generic `_prepare_env_with_host_paths(env)` that reads BOTH `RISK_CLIENT_PATH` and `PORTFOLIO_MATH_PATH`, normalizes each via **`os.path.realpath`** (resolves symlinks + normalizes separators; Codex R2 correction — `normpath` alone doesn't resolve symlinks), and prepends to PYTHONPATH with explicit dedupe on the realpath-normalized form. Preserves existing risk_client behavior; adds portfolio_math side-by-side.

Dedupe algorithm (Codex R3 correction — reads from `env` dict, not `os.environ`; dedupes within `new_paths` too):
```python
current = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
seen = {os.path.realpath(p) for p in current}
prepended = []
for raw in new_paths:                                       # e.g. [RISK_CLIENT_PATH, PORTFOLIO_MATH_PATH]
    if not raw:
        continue
    resolved = os.path.realpath(raw)                        # symlink-resolved
    if resolved in seen:
        continue                                            # dedupe both vs current AND within new_paths
    seen.add(resolved)
    prepended.append(resolved)
env["PYTHONPATH"] = os.pathsep.join(prepended + current)
```

Note: reads from the `env` dict that `prepare_env(env)` receives (per `_helpers.py:65` contract), NOT from `os.environ` directly. Also dedupes within `new_paths` so passing the same repo root for both env vars doesn't produce a duplicate entry.

### D3: System prompt — two bullets: availability + routing (Codex R2 expansion)

`_handlers.py:59` prefers docker. The model won't know to pick subprocess unless told. Two bullets added to `api/agent/shared/system_prompt.py` around line 694-696 (where existing `_risk`-specific guidance lives):

1. **Availability**: "`portfolio_math` is available in the subprocess `code_execute` backend. Import explicitly, e.g. `import portfolio_math as pm`."
2. **Routing**: "When using `_risk` or `portfolio_math`, set `host=\"subprocess\"`. These require host-path imports that are not available in the docker backend."

Without the availability bullet, the model may not know portfolio_math exists. Without the routing bullet, it picks docker by default and the import fails.

### D4: `PORTFOLIO_MATH_PATH` source — root `.env` only; `api/.env` optional (Codex R2 clarification)

Codex R1 verified: `RISK_CLIENT_PATH` comes from root `.env` (loaded via `api/main.py:79`) plus an OPTIONAL `api/.env` override that some dev environments use. No checked-in CI/compose override exists.

**Plan scope**: PM1A touches root `.env` ONLY. If a local dev already has `RISK_CLIENT_PATH` set in `api/.env` as an override, they must also add `PORTFOLIO_MATH_PATH` there — but that's a user action, not something the PR edits (we can't commit per-dev overrides). The PR description calls this out for developers.

**Not in scope**: external deploy env wiring — if a deployed environment sets `RISK_CLIENT_PATH` through some out-of-repo secret mechanism, the operator has to add `PORTFOLIO_MATH_PATH` there too. Called out in the TODO follow-up, doesn't block PM1A.

### D5: No changes to portfolio_math, no changes to risk_module

Pure AI-excel-addin work + one TODO update in risk_module. Portfolio_math ships as-is from Phase 2.

## 4. Scope

### In scope (PM1A — subprocess-only)
- Add `PORTFOLIO_MATH_PATH` to AI-excel-addin `.env` (no `.env.example` touch — doesn't exist at root, per Codex R1)
- Rename/rewrite `_prepare_env_with_risk()` → `_prepare_env_with_host_paths()` handling both env vars with dedupe
- Update `CodeExecutionConfig` assembly to use the renamed helper
- Update `api/agent/shared/system_prompt.py` near line 696 to add portfolio_math alongside `_risk` in the `host="subprocess"` guidance
- Extend `tests/test_code_execute.py` with one real subprocess integration test that imports `portfolio_math` inside the sandbox and calls one kernel
- Update `tests/test_code_execute.py` fixtures (`_consumer_code_execution_config` or equivalent) to set both env vars
- Update `risk_module/docs/TODO.md`: mark PM1A as DONE post-merge; add PM1B placeholder for docker parity

### Out of scope (PM1B — separate plan, follow-up)
- Docker image rebuild to add `statsmodels`
- Real volume mount of `risk_module` repo into the docker container (not just PYTHONPATH env var)
- Prompt change to allow `host="docker"` for risk/portfolio_math flows
- Docker backend integration tests that actually exercise portfolio_math imports
- Publishing `portfolio_math` to PyPI (would make docker parity trivial but is separate scope)

## 5. Implementation — single AI-excel-addin commit + one risk_module commit

### AI-excel-addin commit (primary change)

1. `.env`: add `PORTFOLIO_MATH_PATH=/Users/henrychien/Documents/Jupyter/risk_module` (same value as `RISK_CLIENT_PATH`)
2. `api/agent/interactive/runtime.py`:
   - Rename `_prepare_env_with_risk` → `_prepare_env_with_host_paths`
   - Read both `RISK_CLIENT_PATH` and `PORTFOLIO_MATH_PATH`
   - Normalize each via `os.path.realpath` (resolves symlinks + normalizes separators — per D2; `normpath` alone is insufficient)
   - Split existing `PYTHONPATH` on `os.pathsep`, dedupe, prepend normalized paths (insert-at-front, skip duplicates)
3. `api/agent/shared/system_prompt.py` near lines 694-696 — add BOTH prompt bullets per D3 (Codex R3 correction — design had 2 bullets, implementation previously only mentioned one):
   - **Availability bullet**: `"portfolio_math is available in the subprocess code_execute backend. Import explicitly, e.g. import portfolio_math as pm."`
   - **Routing bullet**: `"When using _risk or portfolio_math, set host=\"subprocess\". These require host-path imports that are not available in the docker backend."`
4. Test changes — **must pin subprocess backend explicitly** (Codex R2 blocker fix):
   - Extend the existing subprocess fixture helper to set `PORTFOLIO_MATH_PATH` alongside `RISK_CLIENT_PATH`
   - Add a new test that:
     - **Pins subprocess backend via `register_docker=False`** (pattern at `packages/agent-gateway/tests/test_code_execution.py:107`) OR explicit `host="subprocess"` in the call — whichever matches the existing `test_code_execute.py` pattern
     - Runs a subprocess sandbox with both env vars set
     - Executed code: `import portfolio_math; result = portfolio_math.black_scholes_price(S=200, K=210, T=0.25, r=0.05, sigma=0.28, option_type="call")`
     - Asserts `abs(result - 8.051) < 0.01` (matches the post-Phase-2 smoke test canonical value)
   - The new test MUST fail if subprocess isn't actually exercised — do not rely on backend auto-selection
5. Run full AI-excel-addin test suite — all tests green, new test green

### risk_module commit (TODO update only, separate)
- Update `docs/TODO.md` PM1 entry:
  - PM1A: mark DONE with the AI-excel-addin commit SHA
  - PM1B: add docker-parity follow-up placeholder with rough scope (add statsmodels, mount risk_module, rebuild image, add container test)

### Time estimate

~0.5 day. Smaller scope than v1 because preamble injection + docker parity were dropped.

## 6. Tests

### New (in AI-excel-addin)
- ONE subprocess integration test: imports `portfolio_math` and calls `black_scholes_price` inside a real subprocess sandbox. Uses the canonical smoke-test inputs from the post-Phase-2 validation (expected price ≈ 8.051).
- **Subprocess is pinned explicitly** (Codex R2 blocker): test uses `register_docker=False` or `host="subprocess"` so backend auto-selection can't accidentally route to docker. See §5 step 4.

### Existing to keep green (in AI-excel-addin)
- Full test suite — unchanged imports, only the env-prep helper function name + behavior changes
- Existing risk_client subprocess tests — continue to pass (helper still reads `RISK_CLIENT_PATH`)

### Not exercised
- Docker backend behavior — deliberately out of scope (PM1B). Document this gap.

## 7. Risks (revised after Codex R1)

1. **Backend drift to docker without prompt update** (Codex R1): model defaults to docker when available, so without the system_prompt.py change it'll try docker and `import portfolio_math` fails. **Mitigation**: D3 prompt update is mandatory, not optional. Review the generated PR diff to confirm the prompt change landed.

2. **Missing Docker image support (PM1B scope)**: `statsmodels` not in `ai-excel-addin-code-exec:latest`. Acceptable for PM1A because subprocess is the live pattern, but documented as a PM1B gating item in `docs/TODO.md`.

3. **PYTHONPATH collisions / duplicate prepends** (Codex R1): duplicate `sys.path` entries are NOT a no-op — they cause subtle import-order issues and confuse debugging. **Mitigation**: D2 helper normalizes + dedupes. Test this directly.

4. **Cross-repo env drift**: root `.env` vs `api/.env` can diverge silently. **Mitigation**: document in the PR description that if a deploy environment overrides `RISK_CLIENT_PATH` in `api/.env`, it must also set `PORTFOLIO_MATH_PATH` in the same file.

5. **In-flight session drain** (Codex R1): env changes require process restart; old sessions keep old config. **Mitigation**: AI-excel-addin runs a development server locally; restart after the change. Production deploy path not covered by PM1A — operator handles.

6. **Existing tests pass even when prod is broken** (Codex R1): current sandbox tests are wiring tests, not real backend exercises. The new integration test in §6 addresses this for portfolio_math specifically — it exercises real subprocess execution, not just the config-construction path.

7. **Deploy-env wiring unknown**: repo has no checked-in CI/compose override for `RISK_CLIENT_PATH`. Wherever that's set externally (secrets manager, deploy config), `PORTFOLIO_MATH_PATH` needs to go alongside. Operator responsibility; documented in TODO.

## 8. Open questions — resolved by Codex R1

| # | Question | Resolution |
|---|---|---|
| 1 | `PORTFOLIO_MATH_PATH` source | ✅ Only root `.env` + optional `api/.env`. No checked-in CI override. External deploy envs are operator-handled; documented in TODO. |
| 2 | `statsmodels` in Docker image | ✅ No. Rebuild required if docker parity wanted. Deferred to PM1B. |
| 3 | Preamble import | ✅ Skip preamble injection. Agent imports explicitly. D1 updated. |

### New questions raised by v2 (still open for R2 review)
- Should the prompt-guidance wording in `system_prompt.py:696` also mention that docker is unsupported (and why), or keep it minimal? Verbose is safer for the model; minimal keeps the prompt short.
- Does the dedupe-and-normalize helper need to handle Windows paths (backslashes, drive letters)? AI-excel-addin is Mac/Linux-dev-first; Windows not supported today. Confirm that's still true.

## 9. Success criteria

- [ ] `PORTFOLIO_MATH_PATH` set in AI-excel-addin root `.env`
- [ ] Generic `_prepare_env_with_host_paths` helper handles both env vars with normalization + dedupe
- [ ] System prompt updated to require `host="subprocess"` for portfolio_math flows
- [ ] New subprocess integration test: agent code imports portfolio_math, calls `black_scholes_price`, gets expected value
- [ ] Full AI-excel-addin test suite green
- [ ] risk_module `docs/TODO.md` updated: PM1A marked DONE with commit SHA, PM1B placeholder for docker parity
- [ ] Single AI-excel-addin commit + single risk_module commit
- [ ] PR description explicitly calls out the docker-gap as known + PM1B-scoped
