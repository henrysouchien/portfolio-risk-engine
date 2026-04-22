# portfolio_math Options — AI-excel-addin Cross-Repo Completion (Phase 3D Steps 6-7)

**Status**: DRAFT v2 — Codex R1 PASS (2026-04-22); ready to implement
**Date**: 2026-04-22
**Repo affected**: `AI-excel-addin` (NOT risk_module). Implementation happens at `~/Documents/Jupyter/AI-excel-addin`.
**Predecessor risk_module plans**:
- `PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md` — Phase 3D shipped 2026-04-22, Steps 6-7 explicitly scoped out as cross-repo.
- `PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md` — un-curation shipped 2026-04-22; root surface now has all 10 payoff functions + 2 domain types.
**Predecessor AI-excel-addin commit (template)**: `cf1b726` — PM1A subprocess mount + system prompt update.

---

## 1. Goal

Complete Phase 3D end-to-end by:
1. **Adding a subprocess-pinned integration test** in AI-excel-addin that imports the new domain types + payoff functions from `portfolio_math` and asserts a canonical pinned value. Mirror of the existing `test_code_execute_subprocess_imports_portfolio_math` test at `tests/test_code_execute.py:234-259` that pins `portfolio_math.black_scholes_price`.
2. **Extending the agent system prompt** at `api/agent/shared/system_prompt.py:695-697` to enumerate the shipped `portfolio_math` surface — domain types + payoff primitives + pricing — so agents know these are available at root without having to discover via introspection.

After this, agents using `code_execute` with `host="subprocess"` will be able to zero-shot:
```python
import portfolio_math as pm
legs = [pm.OptionLeg(position="long", option_type="call", strike=100, premium=2, expiration="20270115")]
strategy = pm.OptionStrategy(legs=legs, underlying_price=100)
breakevens = pm.find_breakevens(strategy)
mp = pm.max_profit(strategy)
```

No more HTTP round-trips for strategy construction + payoff math.

---

## 2. Non-goals

- **No runtime changes.** `api/agent/interactive/runtime.py:125` `_prepare_env_with_host_paths` already mounts `PORTFOLIO_MATH_PATH` via PYTHONPATH. Nothing to add — mount is transparent to portfolio_math's internal surface.
- **No docker-backend changes.** Docker parity is PM1B, still deferred.
- **No `_risk` catalog integration.** The risk-function catalog (`_fetch_risk_function_catalog` at `system_prompt.py:610`) is a dynamic fetch from the risk_module backend. A parallel `portfolio_math` catalog mechanism is out of scope — static enumeration in the prompt is sufficient and matches how BS/Greeks were documented in PM1A.
- **No changes in risk_module** other than optionally appending cross-repo commit SHAs to the 3D extraction plan's ship log and the un-curation plan's ship log post-ship.
- **No new `portfolio_math` capability.** The functions already exist and ship; this phase is pure agent-surface exposure.

---

## 3. Current AI-excel-addin state (verified 2026-04-22)

### 3.1 Runtime (`api/agent/interactive/runtime.py`)
Line 125: `_prepare_env_with_host_paths` reads `RISK_CLIENT_PATH` and `PORTFOLIO_MATH_PATH`, realpath-resolves, dedupes, prepends to PYTHONPATH. Works for anything added to `portfolio_math/` in risk_module — the 3D additions (OptionLeg, OptionStrategy, payoff functions) import cleanly through the existing mount without code change.

**Smoke verification** (Codex R1 recommend #1 correction — `PORTFOLIO_MATH_PATH` is runtime-internal; only `_prepare_env_with_host_paths` copies it into `PYTHONPATH`. Use `PYTHONPATH` directly for a plain shell smoke):
```bash
PYTHONPATH=/Users/henrychien/Documents/Jupyter/risk_module python3 -c "import portfolio_math; print(portfolio_math.OptionLeg, portfolio_math.strategy_payoff)"
```
Returns both objects cleanly. The actual agent runtime path uses `PORTFOLIO_MATH_PATH` via `_prepare_env_with_host_paths` — the Step 1 subprocess integration test (§4.1) exercises that code path end-to-end.

### 3.2 System prompt (`api/agent/shared/system_prompt.py`)
Lines 695-697 (post-PM1A, unchanged since `cf1b726`):
```
- A pre-instantiated `_risk` client is available for accessing portfolio and market data.
- `portfolio_math` is available in the subprocess `code_execute` backend. Import explicitly, e.g. `import portfolio_math as pm`.
- When using `_risk` or `portfolio_math`, set `host="subprocess"` in your `code_execute` call. These require host-path imports that are not available in the docker backend.
```

Generic pointer only. No enumeration of the surface. Agent must discover via `dir(portfolio_math)` / `help()`. Works eventually for well-known primitives (Black-Scholes) but slow for non-obvious constructor signatures (`OptionLeg` validation is strict; getting `position`/`option_type`/`expiration` right is non-trivial zero-shot).

### 3.3 Tests (`tests/test_code_execute.py`)
PM1A smoke at lines 234-259 is the exact template. Sets `PORTFOLIO_MATH_PATH` via env override, runs `import portfolio_math; result = portfolio_math.black_scholes_price(S=200, K=210, T=0.25, r=0.05, sigma=0.28, option_type="call")` in a real subprocess. Pins the result to a canonical value (Codex R1 pin: 8.051 — per PM1A plan).

### 3.4 Working tree (2026-04-22; Codex R1 recommend #2 correction — 12 entries total, not 9)
Parallel workstream files present:
- ` M api/memory/workspace/notes/methodology/_playbook.md`
- ` M docs/design/business-model-artifact-design.md`
- ` M docs/design/business-model-artifact-phase1-validation.md`
- `?? docs/design/business-model-compiler-task.md`
- `?? docs/design/business-model-typed-contract-task.md`
- `?? docs/design/edgar-equivalence-expansion-audit-task.md`
- `?? docs/design/tutor-mode-task.md`
- `?? schema/business_model.py`
- `?? schema/business_model_compiler.py`
- `?? tests/schema/snapshots/business_model_v1_0.schema.json`
- `?? tests/schema/test_business_model_compiler.py`
- `?? tests/schema/test_business_model_types.py`

**Hard rule**: do not stage or modify any of these. If any unrelated file appears modified during implementation, STOP and report.

---

## 4. Scope — exact changes

### 4.1 `AI-excel-addin/tests/test_code_execute.py`

Add one new subprocess integration test — `test_code_execute_subprocess_imports_portfolio_math_options` — immediately after the existing `test_code_execute_subprocess_imports_portfolio_math` at line 234.

**Pattern**: identical harness to the PM1A test at `tests/test_code_execute.py:234-259` — Codex R1 recommend #4 explicitly pins the template details:

- Same `monkeypatch.delenv("PORTFOLIO_MATH_PATH", raising=False)` + `env_override={"PORTFOLIO_MATH_PATH": "/Users/henrychien/Documents/Jupyter/risk_module"}` pattern.
- Same `register_docker=False` argument so the test exercises the real subprocess path, not the docker path.
- Same subprocess-health assertions from the PM1A template: non-zero result, no stderr errors, exit code 0.

Code block:

```python
def test_code_execute_subprocess_imports_portfolio_math_options(monkeypatch) -> None:
    # Identical env + harness setup to test_code_execute_subprocess_imports_portfolio_math
    # (register_docker=False, PORTFOLIO_MATH_PATH env override).
    #
    # Test body:
    code = (
        "import portfolio_math as pm\n"
        "leg = pm.OptionLeg(position='long', option_type='call', strike=100, premium=2, expiration='20270115')\n"
        "strategy = pm.OptionStrategy(legs=[leg], underlying_price=100)\n"
        "pnl_at_breakeven = pm.strategy_payoff(strategy, 102.0)\n"
        "breakevens = pm.find_breakevens(strategy)\n"
        "max_profit = pm.max_profit(strategy)\n"
        "max_loss = pm.max_loss(strategy)\n"
        "print(f'pnl={pnl_at_breakeven} bes={breakevens} mp={max_profit} ml={max_loss}')\n"
    )
    # Expected pinned output: pnl=0.0, breakevens=[102.0], max_profit=None, max_loss=-200.0
    # (single long call → unlimited upside → max_profit=None; max_loss = -premium*size*multiplier = -200)
```

**Pinned assertions** (exact values to lock):
- `pnl_at_breakeven == 0.0` (within tolerance 1e-9)
- `breakevens == [102.0]`
- `max_profit is None` (unlimited upside for single long call)
- `max_loss == -200.0` (premium 2 × size 1 × multiplier 100, negated for long)

These choices give the broadest per-function coverage in one subprocess call — exercises `OptionLeg` validation, `OptionStrategy` construction, `strategy_payoff` + `find_breakevens` + `max_profit` + `max_loss`, and confirms the `None`-for-unlimited convention.

### 4.2 `AI-excel-addin/api/agent/shared/system_prompt.py`

Extend the "Portfolio & Risk Data in code_execute" section (line 695-697) with a new bullet enumerating the shipped `portfolio_math` surface. Insert immediately after the existing "portfolio_math is available…" bullet.

**Current state** (lines 696-697):
```
- `portfolio_math` is available in the subprocess `code_execute` backend. Import explicitly, e.g. `import portfolio_math as pm`.
- When using `_risk` or `portfolio_math`, set `host="subprocess"` in your `code_execute` call. These require host-path imports that are not available in the docker backend.
```

**After** (replace lines 696-697 block — Codex R1 nit: exact symbol names, no shorthands or `etc.`):
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

One new multi-line bullet; nothing else in the prompt changes.

**Rationale for enumeration**: agents can't guess `OptionLeg`'s constructor signature (position/option_type/strike/premium/size/multiplier/expiration) zero-shot. Black-Scholes primitives are discoverable; domain types and payoff function names benefit from an explicit list. Deliberately using nested bullets (not a code block) to match the existing prompt's conversational style.

### 4.3 No runtime changes

`api/agent/interactive/runtime.py` already mounts `PORTFOLIO_MATH_PATH`. Verified via smoke in §3.1. Do not touch.

---

## 5. Step-by-step implementation (in AI-excel-addin repo)

### Step 1 — Add subprocess integration test
- Add `test_code_execute_subprocess_imports_portfolio_math_options` per §4.1.
- Pin to the 4 assertion values listed.
- Run: `cd ~/Documents/Jupyter/AI-excel-addin && python3 -m pytest tests/test_code_execute.py -q` — expect new test passes + existing PM1A test still passes (set size should increase by 1).
- Scoped commit: `git add tests/test_code_execute.py && git commit -m "test(sandbox): subprocess smoke for portfolio_math options (Phase 3D)"`.

**Exit criterion**: new test green. Existing test suite unchanged. No other files staged.

### Step 2 — Extend system prompt enumeration
- Apply the §4.2 insertion.
- **Pin the prompt contract** (Codex R1 recommend #3 — existing `tests/test_system_prompt.py:98` `test_code_execution_guidance_includes_risk_section` asserts specific strings in the code execution guidance section; extend it). Add at minimum these substring assertions so the bullet can't silently regress:
  - `"OptionLeg"` present in section
  - `"OptionStrategy"` present in section
  - `"strategy_payoff"` present in section (at least one payoff helper)
  - `"find_breakevens"` present in section
- Run existing + extended prompt tests: `cd ~/Documents/Jupyter/AI-excel-addin && python3 -m pytest tests/test_system_prompt.py -q` — expect all pass (existing + 4 new assertions).
- Also run `python3 -m pytest tests/ -q -k "system_prompt or prompt"` as a broader sweep.
- Scoped commit: `git add api/agent/shared/system_prompt.py tests/test_system_prompt.py && git commit -m "docs(prompt): enumerate portfolio_math surface for agent discovery (Phase 3D)"`.

**Exit criterion**: prompt includes the new enumeration bullet. Prompt contract tests pin the 4 new substring assertions. No other files staged.

### Step 3 — Cross-repo ship log update (back in risk_module)
- In `~/Documents/Jupyter/risk_module`:
  - Append a cross-repo ship log entry to `docs/planning/PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md` §11 (after the existing Step 5 entry) noting Steps 6-7 shipped with the AI-excel-addin commit SHAs from Steps 1-2 above.
- Scoped commit in risk_module: `git add docs/planning/PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md && git commit -m "docs(planning): record AI-excel-addin Phase 3D Steps 6-7 ship (cross-repo)"`.

**Exit criterion**: ship log entry visible. Cross-repo trace complete.

**Commit counts**: 2 commits in AI-excel-addin, 1 commit in risk_module.

---

## 6. Test plan

- **New test** (`tests/test_code_execute.py`): `test_code_execute_subprocess_imports_portfolio_math_options` — pinned values per §4.1. Exercises real subprocess (no mocks), mirrors PM1A discipline.
- **Regression**: `python3 -m pytest tests/test_code_execute.py -q` baseline must hold (11 passed per PM1A — should become 12 passed).
- **Prompt test sweep** (if applicable): `python3 -m pytest tests/ -q -k "system_prompt or prompt"`.
- **Live manual verification** (optional, not required for ship): start a local agent session, ask it to price a debit spread via `code_execute` with `host="subprocess"`, confirm it finds and uses `portfolio_math.OptionStrategy` without hunting.

---

## 7. Risks

- **Low.** Both changes are additive (new test, new prompt bullet). No runtime code touched. Parallel workstream files untouched per §3.4 hard rule.
- **Prompt bloat concern**: the new bullet is ~400 chars. Negligible against the existing multi-thousand-char system prompt. If a future prompt diet is needed, the `portfolio_math.*` surface is a candidate for migration to a dynamic catalog (like `_fetch_risk_function_catalog`) — out of scope here.
- **Prompt drift**: if AI-excel-addin lands other portfolio_math-related prompt changes before implementation, merge carefully. Current state (2026-04-22) shows no drift since `cf1b726` on the two target files.
- **Pinned test values**: the four asserted values (`pnl=0.0`, `breakevens=[102.0]`, `max_profit=None`, `max_loss=-200.0`) are mathematical identities for a long 100 call at $2 premium evaluated at $102. They won't drift unless the payoff semantics themselves change — in which case the characterization oracle in risk_module `tests/options/test_serialization_contract.py` would catch it first.

---

## 8. Rollback

If either step fails:
- Revert only the files you just wrote (`git reset HEAD <file> && git checkout <file>` is destructive — prefer `git restore --source=HEAD~ <file>` or re-edit manually). Per the hard rules, do not use destructive git; rewrite the file instead.
- Working tree remains untouched for parallel workstream files in all cases.

Risk is low enough that rollback is unlikely to be needed.

---

## 9. Commit message templates

AI-excel-addin commits:
1. `test(sandbox): subprocess smoke for portfolio_math options (Phase 3D)`
2. `docs(prompt): enumerate portfolio_math surface for agent discovery (Phase 3D)`

risk_module commit:
3. `docs(planning): record AI-excel-addin Phase 3D Steps 6-7 ship (cross-repo)`

All commits include:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## 10. Change log

**v2 (2026-04-22)**: Codex R1 PASS with 4 recommends + 1 nit. All integrated:
- §3.1 smoke command: `PORTFOLIO_MATH_PATH=` changed to `PYTHONPATH=` (runtime env var vs shell-smoke correction).
- §3.4 working tree inventory: corrected to 12 entries (3 modified + 9 untracked).
- §4.1 PM1A mirror: `register_docker=False` + subprocess health assertions explicitly named.
- §4.2 prompt bullet: exact symbol names replacing shorthands and `etc.`; nested bullets for readability.
- §5 Step 2 exit criterion: extended to pin 4 substring assertions (`OptionLeg`, `OptionStrategy`, `strategy_payoff`, `find_breakevens`) in existing `tests/test_system_prompt.py:98` to prevent silent prompt regression.

**v1 (2026-04-22)**: Initial draft.
