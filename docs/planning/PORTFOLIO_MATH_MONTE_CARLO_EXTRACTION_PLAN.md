# portfolio_math Monte Carlo Kernel Extraction (Phase 3C)

**Status**: DRAFT v1 — pending Codex review
**Date**: 2026-04-24
**Parent**: `AGENT_SURFACE_AUDIT.md` Phase 3C row.
**Prior plans referenced**: `PORTFOLIO_MATH_EXTRACTION_PLAN.md` (Phase 2 — base extraction), `PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md` + `PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md` (Phase 3D — pattern match).
**Effort estimate**: 2-4 days (revised down from Codex R1's original 5-7 day estimate after research pass; pure-compute boundary is sharper than R1 assumed).

---

## 1. Goal

Extract the Monte Carlo simulation kernel into `portfolio_math` so the agent sandbox can compose MC with other local math (custom drift models, alternative shock distributions, scenario-conditioning, path-level analytics) without one-shot HTTP round-trips. Match Phase 3D's un-curated root export pattern: `import portfolio_math as pm; pm.simulate_paths(...)`.

After this ships, the agent can:
- Generate correlated shocks from a covariance matrix (`pm.generate_shocks`)
- Apply scenario-conditioning via factor-beta × shock-vector math (`pm.compute_drift_overrides`)
- Accumulate paths with arbitrary drift + vol_scale (`pm.accumulate_paths`)
- Compute terminal-distribution stats including VaR/CVaR (`pm.terminal_stats`)
- Or call `pm.simulate_paths(...)` end-to-end with pre-computed correlation + drift inputs

The orchestrator (`agent/building_blocks.run_monte_carlo`) stays in risk_module, doing portfolio loading + factor enrichment + covariance fetch, then delegating to `portfolio_math` for the pure numerics.

---

## 2. Non-goals

- **No HTTP path removal.** `rc.run_monte_carlo(...)` continues to work for "I just want one MC run, give me percentile paths" — that's the right shape for one-shot calls.
- **No `MonteCarloResult` dataclass move.** That lives at `core/result_objects/monte_carlo.py:12` and stays on the orchestrator side (it's the wire format, not pure compute). `portfolio_math` returns raw numpy arrays + dicts.
- **No portfolio-loading or factor-fetch extraction.** Those are impure (DB/service calls) and stay in `agent/building_blocks` + `portfolio_risk_engine`.
- **No `vol_scale` semantic redesign.** The existing vol_scale parameter (applied during path accumulation at `monte_carlo.py:718`) is preserved as-is. Sandbox callers must coordinate with shock scaling per §9 R2.
- **No statsmodels dependency.** The extracted kernel uses numpy + scipy + pandas only. statsmodels is not imported anywhere in the MC engine today (verified via research pass — only stats.py uses it).
- **No "configurable random distribution" feature creep.** The extracted kernel mirrors today's normal/Student-t/bootstrap fallback chain. Adding new distributions is post-MVP.

---

## 3. Current state (verified 2026-04-24)

### 3.1 Engine boundary — verified clean split point

`portfolio_risk_engine/monte_carlo.py` has a sharp pure/impure boundary:

| Lines | Function | Purity | Action |
|---|---|---|---|
| 81-152 | `_resolve_weights` | impure (DB/cache via `portfolio_service`) | stays in risk_module |
| 153-202 | `_resolve_tickers_and_covariance` | impure (FactorService HTTP) | stays in risk_module |
| 203-245 | `_resolve_historical_monthly_drift` | impure (covariance cache) | stays in risk_module |
| 246-348 | `_resolve_monthly_drift` (incl. drift-override path 326-346) | mostly pure | **extract pure portion** to kernel |
| 351-383 | `_build_correlation_transform` (Cholesky + PSD fallback via `_nearest_psd`) | pure | **extract** to kernel |
| 460-536 | `_generate_shocks` (normal/Student-t/bootstrap fallback chain) | pure | **extract** to kernel |
| 539-758 | `run_monte_carlo` (entry — orchestrates above + path accumulation 595-722 + percentile stats 723-750) | mixed | **split**: orchestration stays, path accum + stats extract |

**Kernel target size**: ~200 lines of deterministic numpy compute.

### 3.2 Caller surface — clean integration point

`agent/building_blocks.py:488` `run_monte_carlo` is the agent-facing wrapper. It calls `_run_monte_carlo_engine` at `:597` (which is `portfolio_risk_engine.monte_carlo.run_monte_carlo`). Single HTTP entry, no recursive calls. After extraction:
- `building_blocks.run_monte_carlo` continues to call the orchestrator
- The orchestrator delegates pure numerics to `portfolio_math.simulate_paths` (or finer-grained primitives)
- HTTP shape unchanged — `MonteCarloResult.from_engine_output(...)` wraps the dict and returns

### 3.3 Scenario-conditioning flow

User passes `scenario_shocks: dict[str, float]` (factor name → shock magnitude). At `monte_carlo.py:607` this is forwarded to `_resolve_monthly_drift`. The factor-beta × shock-vector math at lines 326-346 is **pure linear algebra** (beta matrix × shock vector → per-ticker drift adjustment) — extractable.

### 3.4 Return shape

`run_monte_carlo` returns `dict` with two top-level keys:
- `percentile_paths: Dict[str, List[float]]` — keyed by percentile (e.g. "p5", "p50", "p95"), values are time-series
- `terminal_distribution: Dict[str, float]` — `mean`, `median`, `p5`, `p95`, `var_95`, `cvar_95`, `probability_of_loss`, `max_gain_pct`, `max_loss_pct`

Both are JSON-serializable. `MonteCarloResult` (at `core/result_objects/monte_carlo.py:12`) wraps with `vol_scale` field added.

### 3.5 Dependencies (verified)

`portfolio_risk_engine/monte_carlo.py` imports: `numpy`, `pandas`, `scipy.stats`, plus risk_module-internal modules (`portfolio_service`, `FactorService`, etc. — all in the orchestrator portion).

The pure kernel needs: `numpy`, `scipy.stats` (for Student-t and norm percentile), optionally `pandas` for index-aware inputs. **No statsmodels, no YAML, no I/O.**

### 3.6 Existing `portfolio_math` package shape (for reference)

After Phase 3D, `portfolio_math/` exposes (root):
- Stats: `compute_performance_metrics`, period conversions (`stats.py`)
- Correlation: `correlation`, `covariance`, `portfolio_volatility`, `risk_contributions`, `herfindahl` (`correlation.py`)
- Options pricing: `black_scholes_price`, `black_scholes_greeks`, `black76_price`, `black76_greeks`, `implied_volatility` (`options.py`)
- Options strategy: `OptionLeg`, `OptionStrategy`, 10 payoff functions at root (un-curated)
- Types: `types.py` (composite return dataclasses)

Phase 3C adds: `monte_carlo.py` module + composable primitives at root.

---

## 4. Design decisions

### 4.1 Module name and surface — match Phase 3D's un-curated pattern

Add `portfolio_math/monte_carlo.py` with all primitives exported at root (per `feedback_codex_scope_reduction_scope.md` — un-curated surface lets the agent compose freely):

```python
# portfolio_math/__init__.py adds:
from .monte_carlo import (
    generate_shocks,           # _generate_shocks → public
    build_correlation_transform,  # _build_correlation_transform → public
    nearest_psd,               # _nearest_psd → public (used by build_correlation_transform fallback)
    compute_drift_overrides,   # extracted from _resolve_monthly_drift:326-346 (factor-beta × shock)
    accumulate_paths,          # extracted from run_monte_carlo:595-722
    terminal_stats,            # extracted from run_monte_carlo:723-750
    simulate_paths,            # convenience wrapper that composes the above (the "easy mode")
)
```

**Why expose all six instead of just `simulate_paths`**: the un-curation lesson from Phase 3D's `PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md` — gating composition behind a single entry point traps the agent in the orchestration shape we picked. Exposing primitives lets the agent skip steps it doesn't need (e.g., reuse a correlation transform across multiple distribution choices).

### 4.2 Return shapes — raw structures, no dataclasses in `portfolio_math`

`portfolio_math` continues its convention: return numpy arrays, plain dicts, or stdlib structures. No domain dataclasses (those live in `core/result_objects` on the orchestrator side and are wire-format concerns).

- `generate_shocks(...) → np.ndarray` shape `(num_simulations, time_horizon_months, n_assets)`
- `build_correlation_transform(corr) → np.ndarray` shape `(n_assets, n_assets)` (Cholesky factor)
- `nearest_psd(matrix) → np.ndarray`
- `compute_drift_overrides(beta_matrix, shock_vector) → np.ndarray` shape `(n_assets,)` of monthly drift adjustments
- `accumulate_paths(shocks, drift, vol_scale, initial_value) → np.ndarray` shape `(num_simulations, time_horizon_months)` of portfolio values
- `terminal_stats(paths, percentiles=(5, 50, 95)) → dict[str, float]` matching today's `terminal_distribution` keys
- `simulate_paths(corr, drift, distribution, num_simulations, time_horizon_months, ...) → dict` matching today's `run_monte_carlo` return contract (minus orchestrator-only fields)

### 4.3 Where the orchestrator delegates

`portfolio_risk_engine/monte_carlo.py::run_monte_carlo` is refactored to:
1. Resolve weights, tickers, covariance, drift via existing impure helpers (unchanged).
2. Call `portfolio_math.compute_drift_overrides(beta_matrix, shock_vector)` instead of inlining.
3. Call `portfolio_math.build_correlation_transform(corr)` instead of inlining.
4. Call `portfolio_math.generate_shocks(...)` instead of `_generate_shocks`.
5. Call `portfolio_math.accumulate_paths(...)` for the path accumulation loop.
6. Call `portfolio_math.terminal_stats(...)` for percentile/VaR/CVaR computation.
7. Wrap result in `MonteCarloResult.from_engine_output(dict_result)` (unchanged).

The private helpers `_generate_shocks`, `_build_correlation_transform`, `_nearest_psd` become thin shims that import-and-call the `portfolio_math` versions, preserving any internal callers (matches Phase 3D's shim-flip approach in `options/data_objects.py` + `options/payoff.py`).

### 4.4 Bootstrap mode — pre-pass portfolio_returns

Today `_generate_shocks` at `:533` falls back to bootstrapping historical portfolio returns when normal/Student-t fail. The historical returns are fetched live in the orchestrator (via `_resolve_historical_monthly_drift`). The extracted `generate_shocks` accepts `portfolio_returns: np.ndarray | None` as an explicit parameter — when bootstrap is requested and the array is None, raise `ValueError`. Orchestrator passes the array; sandbox callers can pass `None` to opt out of bootstrap fallback.

### 4.5 vol_scale coordination

Today `vol_scale` is applied during path accumulation (`monte_carlo.py:718`). After extraction, `accumulate_paths(...)` takes `vol_scale: float = 1.0` as an explicit parameter. The orchestrator passes through the value from `MonteCarloResult.vol_scale`. Sandbox callers must understand: scaling shocks AND scaling vol both compound — pick one or the other unless intentionally double-scaling. Documented in docstring.

### 4.6 Sorted-paths invariant for VaR/CVaR

`terminal_stats` computes VaR/CVaR by sorting terminal values and indexing into percentiles. The kernel sorts internally; callers don't need to pre-sort. Test pins exact VaR/CVaR values against fixed-seed paths.

### 4.7 Why no `pandas` dependency in the kernel core

The pure kernel works on numpy arrays. Pandas is the orchestrator's responsibility (taking `pd.Series`/`pd.DataFrame` inputs, extracting `.values` before delegating). Keeps the kernel dep surface minimal and the function signatures less ambiguous.

---

## 5. Scope — files to change (LOCKED PAIR with §6 — file rows in §5.1, operational steps in §5.2)

### 5.1 Files (code + tests)

| # | File | Change |
|---|------|--------|
| 1 | `portfolio_math/monte_carlo.py` (new) | New module. Implements `generate_shocks`, `build_correlation_transform`, `nearest_psd`, `compute_drift_overrides`, `accumulate_paths`, `terminal_stats`, `simulate_paths`. Pure numpy/scipy. |
| 2 | `portfolio_math/__init__.py` | Add 7 root-level exports for the new primitives. Match the Phase 3D un-curated pattern. |
| 3 | `portfolio_math/types.py` (extend) | Add no new dataclasses (kernel returns plain dicts). Confirm no dataclass mismatch with options-side types. |
| 4 | `portfolio_risk_engine/monte_carlo.py` (refactor) | Refactor `run_monte_carlo` to delegate to `portfolio_math`. `_generate_shocks`, `_build_correlation_transform`, `_nearest_psd` become thin import-shims. Drift-override math at 326-346 delegates to `portfolio_math.compute_drift_overrides`. |
| 5 | `tests/portfolio_math/test_monte_carlo.py` (new) | Pure-kernel unit tests: shock generation determinism (fixed seed), correlation transform vs. Cholesky, PSD repair, drift overrides math, path accumulation, terminal stats with known fixed-seed VaR/CVaR pins. |
| 6 | `tests/portfolio_risk_engine/test_monte_carlo.py` (existing — extend) | Regression test: byte-identical output of `run_monte_carlo` end-to-end pre/post-refactor with same seed. Snapshot characterization oracle pattern (matches `tests/options/test_serialization_contract.py` from Phase 3D). |
| 7 | `core/result_objects/monte_carlo.py` | No change. Confirm `from_engine_output` still works against the orchestrator's dict shape. |
| 8 | `agent/building_blocks.py` | No code change. Verify `run_monte_carlo` wrapper still returns `MonteCarloResult`. Add a docstring note that the underlying kernel is now in `portfolio_math` so the agent can compose primitives in the sandbox. |

### 5.2 Operational steps (not file edits)

§6 also contains operational steps that don't correspond to file rows:
- Step 5 (AI-excel-addin sandbox smoke test) — runs in the addin worktree; produces no risk_module file change.
- Step 6 (live-verify end-to-end MC via Hank UI) — runtime operation against live gateway.
- Step 7 (system prompt update in AI-excel-addin) — separate cross-repo PR scoped to the addin.

The §5.1↔§6 lock applies to file rows #1-#8 only.

---

## 6. Implementation steps (LOCKED PAIR with §5.1)

### Step 1 — Add `portfolio_math/monte_carlo.py` (covers §5 #1 + #3)

Implement the 7 primitives as pure numpy/scipy functions:
- `generate_shocks(rng, distribution, num_simulations, time_horizon_months, n_assets, transform, df=None, portfolio_returns=None)`
- `build_correlation_transform(corr) → cholesky_factor`
- `nearest_psd(matrix) → repaired_matrix`
- `compute_drift_overrides(beta_matrix, shock_vector) → drift_adjustments`
- `accumulate_paths(shocks, drift, vol_scale=1.0, initial_value=1.0) → paths`
- `terminal_stats(paths, percentiles=(5, 50, 95)) → dict`
- `simulate_paths(corr, drift, distribution, num_simulations, time_horizon_months, vol_scale=1.0, df=None, portfolio_returns=None, percentiles=(5, 50, 95), seed=None) → dict`

Each function gets a docstring with units, deterministic-seed contract, and parameter shape requirements.

§5 #3: confirm no new dataclasses needed (types.py untouched).

### Step 2 — Update `portfolio_math/__init__.py` (covers §5 #2)

Add 7 root exports per §4.1.

### Step 3 — Refactor `portfolio_risk_engine/monte_carlo.py` (covers §5 #4)

- `_generate_shocks` → thin shim that calls `portfolio_math.generate_shocks` with same signature
- `_build_correlation_transform` → thin shim → `portfolio_math.build_correlation_transform`
- `_nearest_psd` → thin shim → `portfolio_math.nearest_psd`
- Drift-override math at lines 326-346 → call `portfolio_math.compute_drift_overrides`
- Path accumulation at 595-722 → call `portfolio_math.accumulate_paths`
- Percentile stats at 723-750 → call `portfolio_math.terminal_stats`

`run_monte_carlo` keeps its public signature unchanged.

**Commit message**: `refactor(risk_engine): delegate Monte Carlo kernel to portfolio_math`

### Step 4 — Tests (covers §5 #5 + #6)

§5 #5: New `tests/portfolio_math/test_monte_carlo.py` with:
- `test_generate_shocks_deterministic_seed` — fixed seed → identical array
- `test_generate_shocks_distribution_normal_mean_zero_std_one` — large-N statistical check
- `test_generate_shocks_studentt_fallback` — verifies df parameter routing
- `test_generate_shocks_bootstrap_requires_portfolio_returns` — None raises ValueError
- `test_build_correlation_transform_identity_returns_identity_cholesky`
- `test_build_correlation_transform_nonpsd_falls_back_to_nearest_psd`
- `test_nearest_psd_repairs_negative_eigenvalues`
- `test_compute_drift_overrides_known_betas_known_shocks`
- `test_accumulate_paths_zero_drift_zero_shocks_constant_value`
- `test_accumulate_paths_vol_scale_applied`
- `test_terminal_stats_known_percentiles_var_cvar`
- `test_simulate_paths_end_to_end_fixed_seed_matches_pinned_output`

§5 #6: Extend existing `tests/portfolio_risk_engine/test_monte_carlo.py` with characterization snapshot:
- `test_run_monte_carlo_byte_identical_pre_post_refactor` — capture baseline output dict before refactor (committed snapshot file), assert equality after refactor.

### Step 5 — AI-excel-addin sandbox smoke test (operational; cross-repo)

After Steps 1-4 ship in risk_module, on a separate AI-excel-addin PR:
- Add subprocess smoke test that imports `portfolio_math` and calls `pm.simulate_paths(...)` with a 2x2 correlation, fixed seed, 100 sims, 12-month horizon. Pin terminal mean against expected value.
- Update system prompt to enumerate the 7 new MC primitives at root, matching Phase 3D's enumeration pattern.

(Mirrors `PORTFOLIO_MATH_OPTIONS_AI_EXCEL_ADDIN_PLAN.md` Steps 6-7.)

### Step 6 — Live-verify end-to-end (operational)

After Step 5 merges:
- Restart gateway under services-mcp.
- Through Hank UI: ask agent to run MC on a small portfolio. Verify `MonteCarloResult` returns identical shape pre/post refactor.
- Sandbox composition test: ask agent in chat to compose `pm.simulate_paths` with a custom drift override (not via the standard `run_monte_carlo` API) and report a custom statistic. Verify it executes without HTTP.

### Step 7 — System prompt + docs update (covers §5 #8)

Same PR as Step 5. Add note to `agent/building_blocks.run_monte_carlo` docstring that the kernel is in `portfolio_math` for sandbox composition. Update `AGENT_SURFACE_AUDIT.md` Phase 3C row to SHIPPED.

---

## 7. Tests

Run after Step 4:

```bash
cd /Users/henrychien/Documents/Jupyter/risk_module
pytest tests/portfolio_math/test_monte_carlo.py tests/portfolio_risk_engine/test_monte_carlo.py -v
```

Expected: all new tests pass + existing engine tests pass + the byte-identical-output regression test confirms the refactor preserves wire-format.

---

## 8. Rollout

- **Reversibility**: Step 3 refactor is internal. The shim pattern means `_generate_shocks`/`_build_correlation_transform`/`_nearest_psd` continue to exist with the same signatures — internal callers are unaffected. Rollback = revert the orchestrator's import-and-delegate calls.
- **Ordering**: Steps 1-4 ship in one risk_module PR. Step 5 (addin smoke + prompt) ships in a second AI-excel-addin PR after the risk_module PR merges + the package is reinstalled in the addin's environment (per the 6D-ARCH publish-gap reality — addin reads `PORTFOLIO_MATH_PATH` env var per PM1A, so editable-install / repo-symlink suffices in dev).
- **Blast radius**: HTTP `/api/agent/call → run_monte_carlo` callers see no change (wire format unchanged). MCP `run_monte_carlo` tool unaffected. New surface is additive.

---

## 9. Risks

### R1 — Snapshot drift on the byte-identical regression test

Floating-point determinism is sensitive to numpy/scipy version changes. The Phase 3D characterization-oracle test pinned its values via `tests/options/test_serialization_contract.py` and survived intact through the shim flip. We mirror that approach but accept that a future numpy/scipy upgrade may need a one-time snapshot regeneration.

### R2 — `vol_scale` × shock-scaling double application

Sandbox callers can both (a) scale `corr` before passing to `build_correlation_transform` AND (b) pass `vol_scale=2.0` to `accumulate_paths` — that double-scales. Mitigation: explicit docstring note. No code-level guard (intentional — the kernel is a primitive layer, callers own composition).

### R3 — Bootstrap mode unreachable from sandbox without portfolio_returns

If a sandbox caller wants bootstrap, they must pre-compute their own historical portfolio returns array. The orchestrator does this via `_resolve_historical_monthly_drift`. Sandbox callers without DB access would need to compute returns from a price series first (which `portfolio_math.compute_performance_metrics` already supports — composable). Documented in `generate_shocks` docstring.

### R4 — Codex R1 on Phase 2 said "API redesign, not a move"

That was the Phase 2 R1 estimate before the boundary was traced precisely. Today's research pass shows the orchestrator already does all the impure work — the kernel is ~200 lines of clean numpy. The "redesign" framing was about *which inputs* the kernel accepts (covariance matrix instead of ticker list; pre-computed drift instead of factor service). This plan accepts that input shape change as table stakes. Plan-time grep over `_generate_shocks` callers confirms it's only called from `run_monte_carlo` itself — no external surface to break.

### R5 — Drift-override extraction (lines 326-346) reads `_resolve_factor_betas` upstream

The drift-override math (`beta_matrix × shock_vector → drift_adjustment`) is pure — but the `beta_matrix` itself is computed via `_resolve_factor_betas` (impure, calls `FactorService`). The orchestrator computes the beta matrix first, then passes the array to `compute_drift_overrides`. Same pattern as `compute_drift_overrides` accepting pre-computed factors instead of fetching them.

### R6 — `portfolio_math` package gets a dep update (scipy)

`portfolio_math/pyproject.toml` already lists `scipy` (Phase 2 added it for `_norm_cdf`/`_norm_pdf`). MC kernel reuses the same `scipy.stats.norm` / `scipy.stats.t`. No new dep. Verified via grep over current `portfolio_math/`.

---

## 10. Live verification — to run after Step 6

| # | Check | Pass criteria |
|---|-------|---------------|
| 1 | Pre-refactor: capture `run_monte_carlo` output for fixed seed + small portfolio | Snapshot saved in test fixture |
| 2 | Post-refactor: same call returns byte-identical output | `assert result == snapshot` passes |
| 3 | Sandbox direct call: `import portfolio_math as pm; pm.simulate_paths(corr, drift, "normal", 100, 12, seed=42)` | Returns dict with `percentile_paths` + `terminal_distribution` keys |
| 4 | Sandbox composition: `pm.generate_shocks(...) → custom transform → pm.accumulate_paths(...) → pm.terminal_stats(...)` | Returns valid stats dict |
| 5 | Hank UI end-to-end: ask agent to run MC on a 5-ticker portfolio | `MonteCarloResult` returns matching shape, no error |
| 6 | Hank UI sandbox composition: ask agent to "simulate paths under a custom drift override and report VaR" | Agent executes pure-numpy composition without HTTP MC call |

---

## 11. Change log

- **v1 (2026-04-24)** — Initial draft. Scope: extract pure MC kernel (~200 lines) into `portfolio_math/monte_carlo.py` with 7 root exports matching Phase 3D's un-curated pattern. Refactor risk_module orchestrator to delegate. Effort revised down from Codex R1's 5-7 day estimate to 2-4 days based on research pass showing the boundary is sharper than R1 assumed.

---

## Appendix A — Primitives signature sketch

```python
# portfolio_math/monte_carlo.py

import numpy as np
import scipy.stats

def generate_shocks(
    rng: np.random.Generator,
    distribution: str,                  # "normal" | "student_t" | "bootstrap"
    num_simulations: int,
    time_horizon_months: int,
    n_assets: int,
    transform: np.ndarray,              # cholesky factor of correlation matrix
    df: float | None = None,            # required for student_t
    portfolio_returns: np.ndarray | None = None,  # required for bootstrap
) -> np.ndarray:
    """Generate correlated shocks for MC paths.
    Returns shape (num_simulations, time_horizon_months, n_assets).
    Deterministic for fixed rng seed."""

def build_correlation_transform(corr: np.ndarray) -> np.ndarray:
    """Cholesky factor of correlation matrix; falls back to PSD repair if rank-deficient.
    Returns shape (n, n) lower triangular."""

def nearest_psd(matrix: np.ndarray) -> np.ndarray:
    """Project matrix to nearest PSD via eigendecomposition.
    Used as Cholesky fallback."""

def compute_drift_overrides(
    beta_matrix: np.ndarray,            # shape (n_assets, n_factors)
    shock_vector: np.ndarray,           # shape (n_factors,)
) -> np.ndarray:
    """Per-asset monthly drift adjustment from factor scenario shocks.
    Returns shape (n_assets,)."""

def accumulate_paths(
    shocks: np.ndarray,                 # shape (sims, months, assets)
    drift: np.ndarray,                  # shape (assets,) monthly
    vol_scale: float = 1.0,
    initial_value: float = 1.0,
) -> np.ndarray:
    """Compound paths from shocks + drift.
    Returns shape (sims, months) of portfolio values."""

def terminal_stats(
    paths: np.ndarray,                  # shape (sims, months)
    percentiles: tuple[int, ...] = (5, 50, 95),
) -> dict[str, float]:
    """Terminal-distribution statistics: mean, median, percentiles, VaR/CVaR, etc.
    Sorts internally; returns dict matching today's terminal_distribution shape."""

def simulate_paths(
    corr: np.ndarray,
    drift: np.ndarray,
    distribution: str,
    num_simulations: int,
    time_horizon_months: int,
    vol_scale: float = 1.0,
    df: float | None = None,
    portfolio_returns: np.ndarray | None = None,
    percentiles: tuple[int, ...] = (5, 50, 95),
    seed: int | None = None,
) -> dict:
    """End-to-end convenience wrapper.
    Returns dict with 'percentile_paths' + 'terminal_distribution' keys."""
```
