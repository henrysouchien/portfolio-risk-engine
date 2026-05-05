# portfolio_math Monte Carlo — AI-excel-addin Cross-Repo Completion (Phase 3C Step 6)

**Status**: SHIPPED 2026-04-26 — AI-excel-addin PR #49 squash `61d8dbb9`.
**Date**: 2026-04-26
**Repo affected**: `AI-excel-addin` (NOT risk_module). Implementation happens at `~/Documents/Jupyter/AI-excel-addin`.
**Predecessor risk_module plan**: `completed/PORTFOLIO_MATH_MONTE_CARLO_EXTRACTION_PLAN.md` — Phase 3C SHIPPED + MERGED 2026-04-25 (PR #21, squash commit `0ef688fd`). Steps 6-7 explicitly scoped out as cross-repo.
**Predecessor AI-excel-addin commit (template)**: PR #46 (Phase 3D options). Same pattern: subprocess smoke test + system prompt enumeration. Verified at `tests/test_code_execute.py:408-460` (options test) + `api/agent/shared/system_prompt.py:763-772` (current portfolio_math enumeration).

---

## 1. Goal

Complete Phase 3C end-to-end by:
1. **Adding a subprocess-pinned integration test** in AI-excel-addin that imports the new MC primitives from `portfolio_math` and asserts canonical pinned values from a fixed-seed run. Mirror of the existing options test at `tests/test_code_execute.py:408-460` and the original PM1A BS test at `tests/test_code_execute.py:365-405`.
2. **Extending the agent system prompt** at `api/agent/shared/system_prompt.py:763-772` to enumerate the Phase 3C Monte Carlo surface — `simulate_paths`, `run_monte_carlo_from_components`, `compute_monthly_drift_from_components`, `build_covariance_transform`, `nearest_psd`, `terminal_stats` — so agents know these are available at root without having to discover via introspection.

After this ships, agents using `code_execute` with `host="subprocess"` can zero-shot:
```python
import numpy as np
import portfolio_math as pm

# Compose MC with custom drift in the sandbox — no HTTP round-trip
covariance = np.array([[0.0036]])
result = pm.simulate_paths(
    covariance=covariance,
    weights=np.array([1.0]),
    drift=np.array([0.0083]),
    distribution="normal",
    num_simulations=100,
    time_horizon_months=12,
    initial_value=100.0,
    seed=42,
)
mean = result["terminal_distribution"]["mean"]
prob_of_loss = result["terminal_distribution"]["probability_of_loss"]
```

The capability unlock from Phase 3C: the agent can now intercept paths, apply custom drift, scenario-condition locally, and chain MC outputs into other portfolio_math primitives — all in one sandbox turn.

---

## 2. Non-goals

- **No runtime changes.** `api/agent/interactive/runtime.py:125` `_prepare_env_with_host_paths` already mounts `PORTFOLIO_MATH_PATH` via PYTHONPATH (PM1A pattern). Nothing to add — the new MC module imports cleanly through the existing mount.
- **No docker-backend changes.** Docker parity is PM1B, still deferred.
- **No `_risk` catalog integration.** The risk-function catalog (`_fetch_risk_function_catalog`) is dynamic. Static enumeration in the prompt is sufficient and matches the prior PM1A + Phase 3D pattern.
- **No new `portfolio_math` capability.** The MC primitives already exist and ship; this phase is pure agent-surface exposure.
- **No changes in risk_module** other than appending a cross-repo ship log entry to the Phase 3C extraction plan post-ship (Step 3 below).

---

## 3. Current AI-excel-addin state (verified 2026-04-26)

### 3.1 Runtime (`api/agent/interactive/runtime.py`)

PM1A's `_prepare_env_with_host_paths` reads `RISK_CLIENT_PATH` and `PORTFOLIO_MATH_PATH`, realpath-resolves, dedupes, prepends to PYTHONPATH. Verified by Phase 3D smoke that `OptionStrategy` imports cleanly through this mount; the Phase 3C MC additions inherit the same path.

**Pre-implementation smoke** (run from any cwd, confirms the new MC primitives are reachable on the live filesystem before adding the test):
```bash
PYTHONPATH=/Users/henrychien/Documents/Jupyter/risk_module python3 -c "
import portfolio_math as pm
print(pm.simulate_paths, pm.run_monte_carlo_from_components, pm.terminal_stats)
"
```

### 3.2 System prompt (`api/agent/shared/system_prompt.py:763-772`)

Current state (verified live):
```
- `portfolio_math` is available in the subprocess `code_execute` backend. Import explicitly, e.g. `import portfolio_math as pm`.
- `portfolio_math` root surface (pure-compute, all sandbox-local):
  - Pricing: `black_scholes_price`, `black_scholes_greeks`, `black76_price`, `black76_greeks`, `implied_volatility`
  - Options domain types: `OptionLeg`, `OptionStrategy`
  - Payoff math: `strategy_payoff`, `leg_payoff`, `find_breakevens`, `max_profit`, `max_loss`, `payoff_table`, `intrinsic_value`, `extrinsic_value`, `cost_of_leverage_annualized`, `pnl_per_dollar_move`
  - Correlation + stats: `compute_correlation_matrix`, `compute_covariance_matrix`, `compute_portfolio_volatility`, `compute_risk_contributions`, `compute_herfindahl`, `compute_performance_metrics`
  - Use `help(portfolio_math)` for signatures.
- When using `_risk` or `portfolio_math`, set `host="subprocess"` in your `code_execute` call. These require host-path imports that are not available in the docker backend.
```

The four-category enumeration (Pricing / Options domain types / Payoff math / Correlation + stats) is the Phase 3D structure. Phase 3C adds a fifth category: **Monte Carlo**.

### 3.3 Tests (`tests/test_code_execute.py`)

Two subprocess smoke tests already exist as templates:
- PM1A pattern: `test_code_execute_subprocess_imports_portfolio_math` at line 365-405 — pins `black_scholes_price` to 8.051.
- Phase 3D pattern: `test_code_execute_subprocess_imports_portfolio_math_options` at line 408-460 — pins `OptionStrategy` payoff math to multiple values via stdout parsing.

Both use the same harness:
- `monkeypatch.delenv("RISK_CLIENT_PATH", raising=False)` + `delenv("PORTFOLIO_MATH_PATH", raising=False)`
- `_consumer_code_execution_config(register_docker=False, extra_env={...})`
- `_dispatch_bundle_tool(session, bundle, "code_execute", {"host": "subprocess", "code": ...})`
- Assert `error is None`, `result["stderr"] == ""`, `result["return_code"] == 0`

The Phase 3C MC test follows this pattern verbatim.

### 3.4 Working tree (2026-04-26 — Codex pre-flight gate)

Parallel-session uncommitted files present in the AI-excel-addin worktree:
- `?? "docs/design/completed/build-diagnostics-task 2.md"` (iCloud duplicate)
- `?? "docs/design/completed/build-diagnostics-task 3.md"` (iCloud duplicate)
- `?? "docs/design/completed/tui-tutor-toggle-task 2.md"` (iCloud duplicate)
- `?? docs/design/git-hook-robustness-task.md`
- `?? "docs/design/legacy-compat-runner-removal-phase1-task 2.md"` (iCloud duplicate)
- `?? docs/design/tutor-mode-identity-override-task.md`
- `?? docs/design/tutor-mode-task.md`
- `?? mcp_servers/services_mcp/logs/`

**Hard rule**: do not stage or modify any of these. They are all in `docs/design/` or `mcp_servers/services_mcp/logs/` — orthogonal to this plan's `tests/test_code_execute.py` and `api/agent/shared/system_prompt.py` scope. If any unrelated file appears modified during implementation, STOP and report.

---

## 4. Scope — exact changes

### 4.1 `AI-excel-addin/tests/test_code_execute.py`

Add one new subprocess integration test — `test_code_execute_subprocess_imports_portfolio_math_monte_carlo` — immediately after the existing options test at line 460. Mirror the harness exactly.

**Test body** (deterministic small case — 1 asset, 100 sims, 12 months, fixed seed):

```python
def test_code_execute_subprocess_imports_portfolio_math_monte_carlo(monkeypatch) -> None:
  monkeypatch.delenv("RISK_CLIENT_PATH", raising=False)
  monkeypatch.delenv("PORTFOLIO_MATH_PATH", raising=False)

  async def _run_test() -> None:
    session = SessionStore(ttl=3600).create_session(api_key_hash="hash")
    bundle = build_code_execution(
      session,
      config=_consumer_code_execution_config(
        register_docker=False,
        extra_env={
          "RISK_CLIENT_PATH": "/Users/henrychien/Documents/Jupyter/risk_module",
          "PORTFOLIO_MATH_PATH": "/Users/henrychien/Documents/Jupyter/risk_module",
        },
      ),
    )

    result, error = await _dispatch_bundle_tool(
      session,
      bundle,
      "code_execute",
      {
        "host": "subprocess",
        "code": (
          "import numpy as np\n"
          "import portfolio_math as pm\n"
          "out = pm.simulate_paths(\n"
          "    covariance=np.array([[0.0036]]),\n"
          "    weights=np.array([1.0]),\n"
          "    drift=np.array([0.0083]),\n"
          "    distribution='normal',\n"
          "    num_simulations=100,\n"
          "    time_horizon_months=12,\n"
          "    vol_scale=1.0,\n"
          "    initial_value=100.0,\n"
          "    seed=42,\n"
          ")\n"
          "td = out['terminal_distribution']\n"
          "mean = td['mean']\n"
          "pol = td['probability_of_loss']\n"
          "sims = out['num_simulations']\n"
          "horizon = out['time_horizon_months']\n"
          "dist = out['distribution']\n"
          "print(f'mean={mean:.6f} pol={pol:.6f} sims={sims} horizon={horizon} dist={dist}')\n"
        ),
      },
    )

    assert error is None
    assert result is not None
    stdout = result["stdout"].strip()
    # Parse: "mean=108.631818 pol=0.430000 sims=100 horizon=12 dist=normal"
    parts = dict(token.split("=", 1) for token in stdout.split())
    assert abs(float(parts["mean"]) - 108.631818) < 1e-4
    assert abs(float(parts["pol"]) - 0.43) < 1e-9
    assert parts["sims"] == "100"
    assert parts["horizon"] == "12"
    assert parts["dist"] == "normal"
    assert result["stderr"] == ""
    assert result["return_code"] == 0
    assert result["images"] == []
    assert result["timed_out"] is False
    assert result["truncated"] is False

  _run(_run_test())
```

**Pinned values** (captured by running the exact same code locally against `portfolio_math` from main at squash commit `0ef688fd`):
- `mean ≈ 108.631818` (1e-4 tolerance — accommodates float-print roundoff; not a numerics test, this is a "did the code path execute end-to-end" smoke)
- `probability_of_loss == 0.43` (exact — 43/100 for fixed-seed normal)
- `num_simulations == 100`
- `time_horizon_months == 12`
- `distribution == "normal"`

The MC kernel itself has a byte-identical regression test in risk_module (`test_run_monte_carlo_byte_identical_pre_post_refactor` against `tests/fixtures/monte_carlo_snapshot.json`). This addin test is **not** a numerics regression — it's a "the subprocess can import + invoke the new surface" smoke. Loose tolerance on float prints is fine; the strict assertions come from the risk_module side.

### 4.2 `AI-excel-addin/api/agent/shared/system_prompt.py`

Insert one new bullet into the four-category `portfolio_math root surface` enumeration. Insert location: between "Correlation + stats" (current line 770) and "Use `help(portfolio_math)` for signatures." (current line 771).

**After**:
```
- `portfolio_math` root surface (pure-compute, all sandbox-local):
  - Pricing: `black_scholes_price`, `black_scholes_greeks`, `black76_price`, `black76_greeks`, `implied_volatility`
  - Options domain types: `OptionLeg`, `OptionStrategy`
  - Payoff math: `strategy_payoff`, `leg_payoff`, `find_breakevens`, `max_profit`, `max_loss`, `payoff_table`, `intrinsic_value`, `extrinsic_value`, `cost_of_leverage_annualized`, `pnl_per_dollar_move`
  - Correlation + stats: `compute_correlation_matrix`, `compute_covariance_matrix`, `compute_portfolio_volatility`, `compute_risk_contributions`, `compute_herfindahl`, `compute_performance_metrics`
  - Monte Carlo: `simulate_paths` (low-level — pre-resolved drift), `run_monte_carlo_from_components` (high-level wrapper), `compute_monthly_drift_from_components`, `build_covariance_transform`, `nearest_psd`, `terminal_stats`
  - Use `help(portfolio_math)` for signatures.
```

One new line, six symbols enumerated. Two parenthetical notes on the two main entry points (low-level `simulate_paths` for composition; high-level `run_monte_carlo_from_components` for behavior-equivalent runs) so the agent picks the right one.

### 4.3 `AI-excel-addin/tests/test_system_prompt.py` (extend prompt-contract assertions)

Mirror the Phase 3D pattern at `tests/test_system_prompt.py:106` (per the 3D plan §5 Step 2; line drifted from `:98` since 3D shipped). Add at minimum these substring assertions to `test_code_execution_guidance_includes_risk_section` so the bullet can't silently regress:
- `"simulate_paths"` present in section
- `"run_monte_carlo_from_components"` present in section
- `"terminal_stats"` present in section

Three minimal pins; no need to over-test the bullet content (the test harness is checking enumeration presence, not narrative correctness).

### 4.4 No runtime changes

`api/agent/interactive/runtime.py` already mounts `PORTFOLIO_MATH_PATH`. Verified live in §3.1. Do not touch.

---

## 5. Step-by-step implementation (in AI-excel-addin worktree)

Per the saved feedback rule on shared-worktree branch handling, work happens in a fresh `git worktree add` worktree off `origin/main`, not the primary AI-excel-addin worktree (which has parallel-session uncommitted state).

### Step 0 — Create temp worktree

```bash
cd /Users/henrychien/Documents/Jupyter/AI-excel-addin
git fetch origin main
git worktree add -b feat/portfolio-math-mc-addin-phase-3c /tmp/AI-excel-addin-wt-mc-3c origin/main
cd /tmp/AI-excel-addin-wt-mc-3c
```

### Step 1 — Add subprocess integration test (covers §4.1)

- Add `test_code_execute_subprocess_imports_portfolio_math_monte_carlo` per §4.1.
- Pin to the 5 assertion values listed.
- Run: `python3 -m pytest tests/test_code_execute.py -q` — expect new test passes + existing PM1A test + existing Phase 3D options test still pass.
- Scoped commit: `git add tests/test_code_execute.py && git commit -m "test(sandbox): subprocess smoke for portfolio_math Monte Carlo (Phase 3C)"`.

**Exit criterion**: new test green. Existing test suite unchanged. No other files staged.

### Step 2 — Extend system prompt enumeration + pin (covers §4.2 + §4.3)

- Apply the §4.2 single-line insertion.
- Apply the §4.3 substring-pin extension to `tests/test_system_prompt.py`.
- Run: `python3 -m pytest tests/test_system_prompt.py -q` — expect all pass (existing + 3 new substring assertions).
- Run broader: `python3 -m pytest tests/ -q -k "system_prompt or prompt"`.
- Scoped commit: `git add api/agent/shared/system_prompt.py tests/test_system_prompt.py && git commit -m "docs(prompt): enumerate portfolio_math Monte Carlo surface for agent discovery (Phase 3C)"`.

**Exit criterion**: prompt includes the new MC bullet. Prompt contract tests pin the 3 new substring assertions. No other files staged.

### Step 3 — Push + open PR (operational)

```bash
git push -u origin feat/portfolio-math-mc-addin-phase-3c
gh pr create --repo henrysouchien/AI-excel-addin --base main --head feat/portfolio-math-mc-addin-phase-3c \
  --title "feat: Phase 3C Monte Carlo — sandbox smoke + system prompt enumeration" \
  --body "<see §9>"
```

### Step 4 — Cross-repo ship log update (back in risk_module, after Step 3 PR merges)

In `~/Documents/Jupyter/risk_module`:
- Append a cross-repo ship log entry to `docs/planning/completed/PORTFOLIO_MATH_MONTE_CARLO_EXTRACTION_PLAN.md` §11 Change log noting Step 6 shipped with the AI-excel-addin commit SHAs from Steps 1-2.
- Update `docs/planning/AGENT_SURFACE_AUDIT.md` Phase 3C row to SHIPPED.
- Update `docs/TODO.md` PM3 row Phase 3C state to SHIPPED.
- Scoped commit in risk_module: `git add docs/planning/completed/PORTFOLIO_MATH_MONTE_CARLO_EXTRACTION_PLAN.md docs/planning/AGENT_SURFACE_AUDIT.md docs/TODO.md && git commit -m "docs(planning): record Phase 3C end-to-end SHIPPED (cross-repo)"`.

**Exit criterion**: ship-log entries visible. Cross-repo trace complete.

**Commit counts**: 2 commits in AI-excel-addin (in temp worktree, then pushed via PR), 1 commit in risk_module.

---

## 6. Test plan

- **New test** (`tests/test_code_execute.py`): `test_code_execute_subprocess_imports_portfolio_math_monte_carlo` — pinned values per §4.1. Exercises real subprocess (no mocks), mirrors PM1A + Phase 3D discipline.
- **Regression**: `python3 -m pytest tests/test_code_execute.py -q` baseline must hold. Today: 15 tests in the file (Codex R1 verified), 4 use `host="subprocess"`, 2 are `portfolio_math` smokes (PM1A at line 365, Phase 3D options at line 408). After this: 16 tests in the file, 5 subprocess, 3 `portfolio_math` smokes.
- **Prompt test sweep**: `python3 -m pytest tests/ -q -k "system_prompt or prompt"`.
- **Live manual verification** (optional, not required for ship): start a local agent session, ask it to run a custom-drift Monte Carlo via `code_execute` with `host="subprocess"`, confirm it finds and uses `pm.simulate_paths` without hunting.

---

## 7. Risks

- **Low.** Both changes are additive (new test, new prompt line). No runtime code touched. Parallel workstream files untouched per §3.4 hard rule.
- **Pinned test value drift** (`mean ≈ 108.631818`): seed=42 + numpy default RNG is deterministic across versions. If numpy ever changes its default RNG implementation (unlikely — `np.random.default_rng` has a stable contract since numpy 1.17), this assertion drifts. 1e-4 tolerance accommodates float-print roundoff; 1e-2 would also be safe. Strict numerics regression coverage is in risk_module's snapshot, not here.
- **Prompt drift**: if AI-excel-addin lands other portfolio_math-related prompt changes between draft and ship, merge carefully. Verified at 2026-04-26 — prompt section unchanged since Phase 3D ship.
- **iCloud `" 2.md"` duplicates**: present in working tree (parallel-session artifact). They don't overlap with this plan's scope. Step 0's temp-worktree pattern keeps them out of the implementation worktree entirely.

---

## 8. Rollback

If either step fails:
- Drop the temp worktree (`git worktree remove --force /tmp/AI-excel-addin-wt-mc-3c`) and the local branch (`git branch -D feat/portfolio-math-mc-addin-phase-3c`). Risk_module side is untouched.
- Per shared-worktree-safety rule, no destructive git in the AI-excel-addin primary worktree. The temp worktree is mine — `--force` is acceptable there.

Risk is low enough that rollback is unlikely to be needed.

---

## 9. Commit message templates + PR body

AI-excel-addin commits:
1. `test(sandbox): subprocess smoke for portfolio_math Monte Carlo (Phase 3C)`
2. `docs(prompt): enumerate portfolio_math Monte Carlo surface for agent discovery (Phase 3C)`

risk_module commit:
3. `docs(planning): record Phase 3C end-to-end SHIPPED (cross-repo)`

PR body sketch:

```markdown
## Summary

Cross-repo completion of Phase 3C (Monte Carlo kernel extraction). After
risk_module PR #21 (squash `0ef688fd`) shipped `pm.simulate_paths` and the
two-tier MC API, this PR exposes them to the agent sandbox:

- New subprocess smoke test in `tests/test_code_execute.py` that imports
  `portfolio_math` and runs `pm.simulate_paths(...)` against a deterministic
  fixed-seed input. Pins `mean ≈ 108.631818` and `probability_of_loss == 0.43`.
- `api/agent/shared/system_prompt.py` enumeration extended with a `Monte Carlo`
  category listing the 6 root primitives.
- `tests/test_system_prompt.py` extended with 3 substring assertions
  (`simulate_paths`, `run_monte_carlo_from_components`, `terminal_stats`) so
  the prompt enumeration can't silently regress.

Plan: risk_module `docs/planning/completed/PORTFOLIO_MATH_MONTE_CARLO_AI_EXCEL_ADDIN_PLAN.md`.

## Test plan

- [x] `python3 -m pytest tests/test_code_execute.py -q` — new test passes + existing options/PM1A tests unchanged.
- [x] `python3 -m pytest tests/test_system_prompt.py -q` — new substring assertions pin.
- [ ] Live manual: agent session with `code_execute(host="subprocess")` runs a custom-drift MC and reports VaR.
```

All commits include:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## 10. Change log

**v2 (2026-04-26)** — Codex R1 fixes:
- **R1 blocker (string escaping)**: §4.1 test code rewritten to extract dict values into local variables before the `print(f'...')` call, eliminating the broken `td[\\\"mean\\\"]` triple-escape pattern that didn't parse. Codex verified the new form compiles cleanly.
- **R1 nit #1 (test count baseline)**: §6 now pins exact baseline (15 tests today → 16 after; 4 subprocess → 5; 2 `portfolio_math` smokes → 3).
- **R1 nit #2 (system_prompt line range)**: §3.2 corrected from `:765-772` → `:763-772` (full section).
- **R1 nit #3 (test_system_prompt line)**: §4.3 corrected from `:98` → `:106` (line drifted since 3D shipped).
- R1 confirmations carried forward: pin values reproduced (`mean=108.63181760586698`, `probability_of_loss=0.43`); insert location accurate; §5 mapping complete; temp worktree path free; iCloud `" 2.md"` files don't follow into a fresh worktree.

**v1 (2026-04-26)** — Initial draft. Mirror of Phase 3D `completed/PORTFOLIO_MATH_OPTIONS_AI_EXCEL_ADDIN_PLAN.md` v2 structure with the Monte Carlo enumeration. Pin values captured live from `pm.simulate_paths(seed=42, ...)` against squash commit `0ef688fd`.
