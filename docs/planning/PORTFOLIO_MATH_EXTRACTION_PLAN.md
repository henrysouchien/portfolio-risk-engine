# Portfolio Math Package Extraction — Phase 2 Plan

**Parent plan**: `AGENT_SURFACE_AUDIT.md` (Phase 2 scope)
**Predecessor**: `RISK_CLIENT_TYPE_POLISH_PLAN.md` (Phase 1, SHIPPED)
**Status**: **APPROVED v4** — Codex PASS after R1, R2, R3, R4
**Date**: 2026-04-17

---

## 1. Goal

Extract a curated set of **pure-compute math kernels** from `risk_module` into a standalone, sandbox-installable Python package called `portfolio_math`. The AI agent running in the AI-excel-addin code-execution sandbox can then `from portfolio_math import ...` and compose pure functions **in-process** — no HTTP, no DB, no FMP — complementing the typed `risk_client` HTTP shim from Phase 1.

**Target agent pattern**:

```python
from risk_client import RiskClient
from portfolio_math import (
    compute_performance_metrics,
    compute_correlation_matrix,
    black_scholes_greeks,
    PerformanceMetrics,
    GreeksSnapshot,
)

rc = RiskClient()

# Data: HTTP (stays as-is from Phase 1)
returns = rc.get_returns_series(tickers=["AAPL","MSFT","SPY"], period="1Y")

# Compute: local, pure, typed
metrics: PerformanceMetrics = compute_performance_metrics(
    portfolio_returns, benchmark_returns, risk_free_rate=0.05
)
greeks: GreeksSnapshot = black_scholes_greeks(
    S=200, K=210, T=0.25, r=0.05, sigma=0.25, option_type="call"
)
# Nested access matches the faithful legacy shape (see D10):
print(f"Sharpe={metrics.risk_adjusted_returns.sharpe_ratio:.2f}, Delta={greeks.delta:.3f}")
```

This matches the finance_cli `SPEC_FINANCIAL_MATH_LIBRARY.md` spec principles (typed signatures, labeled dataclass returns for composite results, pure functions, composability).

---

## 2. Current state (verified by survey + Codex R1 audit)

**11 MVP extraction-ready pure-compute kernels** identified across these files (revised down from 14 after Codex R1 caught MC + payoff scope issues):

| Module | Kernel | Source | Notes |
|---|---|---|---|
| **stats** (1) | `compute_performance_metrics` | `portfolio_risk_engine/performance_metrics_engine.py:51` | Returns nested dict with drawdown meta, monthly maps, rolling series, warnings — extraction must preserve this shape (Codex R1 blocker #1) |
| **correlation** (5) | `compute_correlation_matrix` | `portfolio_risk_engine/portfolio_risk.py:353` | Returns `pd.DataFrame` — no dataclass wrapping needed |
| | `compute_covariance_matrix` | `portfolio_risk_engine/portfolio_risk.py:345` | Returns `pd.DataFrame` |
| | `compute_portfolio_volatility` | `portfolio_risk_engine/portfolio_risk.py:369` | Returns `float` — scalar, no dataclass |
| | `compute_risk_contributions` | `portfolio_risk_engine/portfolio_risk.py:383` | Returns `pd.Series` |
| | `compute_herfindahl` | `portfolio_risk_engine/portfolio_risk.py:400` | Returns `float` — depends on optional `DIVERSIFIED_SECURITY_TYPES` filter |
| **options** (5) | `black_scholes_price` | `options/greeks.py:40` | Returns `float` |
| | `black_scholes_greeks` | `options/greeks.py:116` | Returns `GreeksSnapshot` (from `options/result_objects.py:17`) with fields: delta, gamma, theta, vega, implied_vol, source |
| | `black76_price` | `options/greeks.py:81` | Returns `float` |
| | `black76_greeks` | `options/greeks.py:185` | Returns `GreeksSnapshot` |
| | `implied_volatility` | `options/greeks.py:271` | Returns `float`; hybrid Newton-Raphson + bisection |

**Deferred to follow-up (not Phase 2 MVP)** — Codex R1 flagged these as API redesigns, not straight moves:
- **Monte Carlo simulators**: there is no `simulate_normal`/`simulate_student_t` in the engine today — only unified `run_monte_carlo` at `portfolio_risk_engine/monte_carlo.py:539` with private helpers `_generate_shocks` at `:460` and `_build_correlation_transform` at `:351`. The engine returns percentile paths + terminal distribution + rich metadata, wrapped by `MonteCarloResult` at `core/result_objects/monte_carlo.py:12`. Extracting this as pure kernels requires splitting the shock generator from the orchestrator — deliberate API design, separate plan.
- **Payoff functions** (`leg_payoff`, `strategy_payoff`, `intrinsic_value` from `options/payoff.py`) — depend on `OptionLeg` + `OptionStrategy` domain types at `options/data_objects.py:31`. Extracting the payoff functions means extracting (or import-aliasing) these domain types, which widens the surface. Defer until MVP pattern is proven.
- **Optimizer kernels** (min-var, max-return, max-Sharpe, efficient frontier) — cvxpy dependency + deeply coupled to `build_portfolio_view`, risk config, and CVXPY orchestration in `portfolio_optimizer.py` / `efficient_frontier.py`. Separate plan.

### Architectural traps (7 — 2 added after Codex R1)

1. `portfolio_risk_engine/optimization.py` reads YAML at runtime — looks pure but isn't. (Out of scope; noted.)
2. `performance_metrics_engine.compute_recent_returns` calls `_fetch_daily_close_via_registry` — hidden FMP fetch. Extract `compute_performance_metrics` only; leave `compute_recent_returns` in risk_module.
3. `building_blocks.run_monte_carlo` does portfolio load before MC — tied into the deferred MC extraction.
4. `efficient_frontier.py` builds portfolio view before solving — optimizer-deferred territory.
5. `core/cash_helpers.py` has module-level YAML cache — not safe to extract.
6. **(NEW, Codex R1)** `compute_performance_metrics` at `performance_metrics_engine.py:82` pulls `min_capm_observations` from config when the argument is omitted. The extracted kernel must expose it as an explicit parameter (no hidden config lookup). Also imports `statsmodels` at `:19` — dep must be declared.
7. **(NEW, Codex R1)** `normalize_weights()` at `portfolio_risk.py:233` defaults off `PORTFOLIO_DEFAULTS` AND normalizes to **gross exposure** (Σ |w| = 1), not net sum (Codex R2 correction). This matters for long/short portfolios — net-sum-1 would be wrong. That hidden default flows into `compute_portfolio_volatility` (`:369`), `compute_risk_contributions` (`:383`), and `compute_herfindahl` (`:400`) — all five correlation/risk kernels in MVP. Decision captured in D3: extracted kernels expect gross-normalized weights as input.

8. **(NEW, Codex R2)** `compute_risk_contributions` divides by `sqrt(w' Σ w)` — zero-vol portfolio (all-zero weights, or degenerate cov) triggers divide-by-zero. Current implementation at `portfolio_risk.py:383` must be inspected for its zero-vol handling; extracted kernel must preserve that exact behavior (or document deviation).

---

## 3. Target state

### 3.1 Package structure (MVP) — flat, matching `risk_client`

**Codex R2 blocker #1 fix**: repo sys.path only has repo root; nested `portfolio_math/portfolio_math/` would not resolve. Follow the existing `risk_client/` layout — flat at repo root, tests live in repo's top-level `tests/`.

```
portfolio_math/                  # flat package, code lives here directly
  __init__.py                    # public API exports
  types.py                       # dataclass return types for composite results
  stats.py                       # compute_performance_metrics + period conversions
  correlation.py                 # correlation, covariance, portfolio_vol, risk_contributions, herfindahl
  options.py                     # black_scholes_price/greeks, black76_price/greeks, implied_volatility
  _utils.py                      # private: _norm_cdf, _norm_pdf, _validate_aligned_index
  pyproject.toml                 # name="portfolio-math", version="0.1.0", deps: numpy, pandas, scipy, statsmodels
  README.md

tests/                           # repo-level tests/ (matches risk_client's location)
  test_portfolio_math_stats.py
  test_portfolio_math_correlation.py
  test_portfolio_math_options.py
  test_portfolio_math_equivalence.py   # golden-fixture regression vs risk_module
  test_portfolio_math_invariants.py    # algebraic invariants (put-call parity, etc.)
  fixtures/portfolio_math/             # committed golden inputs/outputs as JSON
```

**Deliberately deferred** (not Phase 2 MVP):
- `monte_carlo.py` — see Codex R1 blocker #2; extraction is API redesign, separate plan
- Payoff functions + OptionLeg/OptionStrategy domain type extraction — separate plan
- `optimize.py` — cvxpy dep; tightly coupled to portfolio view; separate plan
- `stress.py` — orchestration-heavy

### 3.2 Return type contract — tiered (Codex R1 D3)

Codex R1 recommendation: "Use dataclasses for composite in-process results only. Use plain `float`, `pd.Series`, `pd.DataFrame`, or `np.ndarray` for scalar/matrix kernels. 'Everything returns a dataclass' is overbuilt."

Adopted contract per kernel:

| Kernel | Return type | Reason |
|---|---|---|
| `compute_performance_metrics` | `PerformanceMetrics` dataclass (nested — see 3.3) | Composite; many labeled fields |
| `compute_correlation_matrix` | `pd.DataFrame` | Matrix; Pandas is the idiom |
| `compute_covariance_matrix` | `pd.DataFrame` | Matrix |
| `compute_portfolio_volatility` | `float` | Scalar; dataclass is overkill |
| `compute_risk_contributions` | `pd.Series` | Vector indexed by ticker |
| `compute_herfindahl` | `float` | Scalar |
| `black_scholes_price` | `float` | Scalar |
| `black_scholes_greeks` | `GreeksSnapshot` dataclass | Composite; preserves existing `options/result_objects.py:17` contract |
| `black76_price` | `float` | Scalar |
| `black76_greeks` | `GreeksSnapshot` dataclass | Composite |
| `implied_volatility` | `float` | Scalar |

### 3.3 Faithful legacy-shape preservation (Codex R1 blocker #1 fix)

The existing `compute_performance_metrics` returns a nested dict with rounded fields, drawdown metadata, monthly return maps, rolling series, and warnings — broadly consumed by `portfolio_risk.py:2515`, `core/result_objects/realized_performance.py:403`, and more. **The extracted dataclass must mirror this shape exactly.**

`types.py` will declare `PerformanceMetrics` as a nested dataclass tree that matches the current nested dict (all keys, all nesting, all sub-structures). Legacy wrappers then use `to_legacy_dict()` adapters (NOT blind `asdict()`) to convert back to the dict shape existing callers expect. This pattern:
- Preserves zero behavioral drift for existing callers
- Gives agent sandbox users typed field access
- Allows incremental migration of downstream callers from dict-access to dot-access

Same principle for `GreeksSnapshot` — preserve all current fields (`delta`, `gamma`, `theta`, `vega`, `implied_vol`, `source`) via `types.py` import from or re-export of the existing `options/result_objects.py` definition. (Codex R2 correction: `rho` is NOT a current field; the existing type has only these 6 fields.)

### 3.4 Purity contract

Every public function in `portfolio_math/`:
- Takes all inputs as arguments (no hidden config, no env lookups, no YAML reads)
- Uses only stdlib + `numpy` + `pandas` + `scipy` + `statsmodels` (nothing in `risk_module`)
- Returns either a scalar/matrix (per 3.2) or a dataclass instance
- Is deterministic — same inputs produce same outputs (MC deferred; IV tolerance-bounded)
- Has a docstring declaring units on every numeric parameter

**No I/O, no DB, no network, no global state, no YAML reads.** Inputs like `min_capm_observations` that are config-defaulted in risk_module become explicit parameters with documented defaults in portfolio_math.

---

## 4. Design decisions

### D1: Extraction with explicit compatibility adapters (Codex R1 rec 1)

Bad option: keep two copies (silent drift).
Bad option: blind `asdict()` legacy wrapper — breaks nested-shape callers.

**Chosen**: extract the kernel to `portfolio_math/`. Replace the risk_module implementation with a thin wrapper that calls the extracted kernel and uses an **explicit `to_legacy_dict()` adapter** to convert the dataclass back to the dict shape existing callers expect. Example:

```python
# portfolio_risk_engine/performance_metrics_engine.py (after)
from portfolio_math import compute_performance_metrics as _pm_compute

def compute_performance_metrics(portfolio_returns, benchmark_returns, risk_free_rate, ...) -> dict:
    """Legacy wrapper. Existing callers keep dict access; new callers should import from portfolio_math directly."""
    result = _pm_compute(portfolio_returns, benchmark_returns, risk_free_rate, ...)
    return result.to_legacy_dict()   # explicit field-by-field conversion preserving nested shape + rounding
```

`to_legacy_dict()` is defined on each composite dataclass and documents the legacy contract explicitly.

### D2: MVP-of-MVP (Codex R1 rec 2 + scope challenge)

11 kernels land in Phase 2 (down from 14 after Codex R1):
- **stats** (1): `compute_performance_metrics`
- **correlation** (5): `compute_correlation_matrix`, `compute_covariance_matrix`, `compute_portfolio_volatility`, `compute_risk_contributions`, `compute_herfindahl`
- **options** (5): `black_scholes_price`, `black_scholes_greeks`, `black76_price`, `black76_greeks`, `implied_volatility`

Deferred to follow-ups (each gets its own plan):
- Monte Carlo extraction (API redesign, not a move)
- Payoff functions + OptionLeg/OptionStrategy domain type extraction
- Optimizer kernels (min-var, max-return, max-Sharpe, efficient frontier)

### D3: Weight-normalization handling — gross-normalized (Codex R2 correction)

The 5 correlation/risk kernels currently accept a raw weights dict and internally call `normalize_weights()` which defaults off `PORTFOLIO_DEFAULTS` AND normalizes to **gross exposure** (Σ |w_i| = 1, not Σ w_i = 1). This matters for long/short portfolios.

**Chosen**: portfolio_math kernels accept **already-gross-normalized** weights as input — convention is `sum(abs(weights.values())) == 1.0`. Document the expectation in docstrings explicitly (emphasize "gross", not "net"). Risk_module's legacy wrapper calls its existing `normalize_weights()` before delegating, preserving existing behavior.

Not extracting `normalize_weights` itself in MVP — it reads a global default, and parameterizing it is a separate change not required for the agent's in-process compute pattern. Agent sandbox users who want the normalization step will either pre-normalize themselves or we add `normalize_weights` as a separate pure utility in a follow-up.

### D4: Numerical tolerance — per kernel (Codex R1 rec 6)

Per Codex R1: tolerance must be kernel-specific.

| Kernel group | Tolerance | Rationale |
|---|---|---|
| `compute_correlation_matrix`, `compute_covariance_matrix` | `rtol=0, atol=0` (exact) | Pandas wrappers; no new numerics |
| `compute_portfolio_volatility`, `compute_risk_contributions`, `compute_herfindahl` | `rtol=1e-12, atol=1e-14` | Basic linalg; any drift is implementation noise |
| `compute_performance_metrics` via `to_legacy_dict()` | **exact (byte-identical)** | Legacy wrapper must reproduce current dict exactly for callers (Codex R2 correction) |
| `compute_performance_metrics` raw dataclass fields | `rtol=1e-10, atol=1e-12` | If raw-field invariant tests are added |
| `black_scholes_price/greeks`, `black76_price/greeks` | `rtol=1e-12, atol=1e-14` | `math.erf`-based; deterministic |
| `implied_volatility` | `atol=1e-6` | Hybrid Newton-Raphson; convergence-bounded |

Per-kernel tolerances live in the equivalence test module, one constant per kernel.

### D5: Distribution — path-mount (same as risk_client)

Like `risk_client`, `portfolio_math` is a standalone package inside the risk_module repo with its own `pyproject.toml`. AI-excel-addin sandbox adds it to `PYTHONPATH` via env var (e.g., `PORTFOLIO_MATH_PATH`) or bundles into the Docker image.

No pip publish in Phase 2. Distribution mechanism matches the existing risk_client pattern.

**AI-excel-addin coordination**: follow-up PR adds the path mount — tracked as a named TODO item in `docs/TODO.md` once this plan lands, not bundled into this Phase 2 ship.

### D6: Python version and deps

`pyproject.toml`:
- `requires-python = ">=3.11"` (matches risk_client)
- Runtime deps: `numpy`, `pandas`, `scipy`, **`statsmodels`** (Codex R1 blocker #3 — OLS regression in `compute_performance_metrics`)
- Dev deps: `mypy`, `pytest`

### D7: Package name

Distribution name: `portfolio-math` (PyPI-style dash; standard). Import package name: `portfolio_math` (PEP 8 underscore; standard). Codex R1 rec 5 confirms.

### D8: Do NOT touch `agent/building_blocks.py` (Phase 3)

Phase 3 retires the `building_blocks` tier once `portfolio_math` proves the in-process pattern. In Phase 2:
- Keep building_blocks as-is — they still dispatch via HTTP
- Don't update them to call portfolio_math internally

### D9: `GreeksSnapshot` — re-export existing type (6 fields exact)

The existing `GreeksSnapshot` at `options/result_objects.py:17` has **6 fields**: `delta`, `gamma`, `theta`, `vega`, `implied_vol`, `source`. Codex R1 blocker #4 + R2 correction: preserve EXACT contract — **do not add `rho`** (I fabricated it in v2; there is no such field today).

**Chosen**: `portfolio_math/types.py` defines `GreeksSnapshot` with those 6 fields exactly. Risk_module's `options/result_objects.py` is updated to `from portfolio_math.types import GreeksSnapshot` and re-exports. Single source of truth; existing imports unchanged. No field additions, no removals — mechanical move.

### D10: `PerformanceMetrics` section-dataclass structure (Codex R2 rec — lock now)

The legacy `compute_performance_metrics` output is a nested dict with known top-level sections. Per Codex R2: decide the dataclass structure in this plan; don't leave it open to implementation. Sections:

```python
@dataclass(frozen=True)
class PerformanceMetrics:
    # 7 section dataclasses
    analysis_period: AnalysisPeriod
    returns: ReturnsStats
    risk_metrics: RiskStats
    risk_adjusted_returns: RiskAdjustedReturns           # contains sharpe_ratio, sortino_ratio, etc.
    benchmark_analysis: BenchmarkAnalysis                # contains beta, alpha, r_squared
    benchmark_comparison: BenchmarkComparison
    monthly_stats: MonthlyStats

    # Standalone top-level fields (Codex R3 correction — these are top-level in the real output, NOT section-nested)
    risk_free_rate: float                                # engine line 341
    monthly_returns: dict[str, float]                    # plain dict (date-string → return)
    benchmark_monthly_returns: dict[str, float]          # plain dict
    rolling_sharpe: dict[str, float]                     # engine line 344 — separate top-level field
    rolling_volatility: dict[str, float]                 # engine line 345 — separate top-level field
    warnings: list[str]                                  # plain list (may be empty)

    def to_legacy_dict(self) -> dict: ...                # byte-identical reproduction of existing dict
```

Each section is its own `@dataclass(frozen=True)` with the exact fields produced by the current engine — confirmed via characterization snapshot in P2.1. Plain containers (`dict`, `list`) for opaque collections that are legitimately variable-keyed (date strings, window sizes, warning messages). This structure:
- Gives typed field access for agent sandbox users (e.g. `metrics.risk_adjusted_returns.sharpe_ratio`)
- Keeps `to_legacy_dict()` a mechanical field-by-field recursion
- Doesn't force sub-dataclasses on collections that are legitimately variable-keyed

Exact per-section field list is pinned at P2.1 via the characterization snapshot — this plan locks the top-level section structure.

### D11: `compute_herfindahl` signature — preserve per-ticker map (Codex R2 correction)

Current signature at `portfolio_risk.py:400` takes `security_types: Optional[Dict[str, str]]` (a per-ticker map) plus implicitly consults `DIVERSIFIED_SECURITY_TYPES`. A bare `set[str]` of diversified types loses the per-ticker mapping — you can't know which tickers to exclude without it.

**Chosen**:
```python
def compute_herfindahl(
    weights: dict[str, float],
    security_types: dict[str, str] | None = None,
    diversified_types: frozenset[str] | None = None,
) -> float:
```

Both params explicit, no hidden constants. Default `diversified_types=None` falls through to "don't filter anything". Legacy wrapper in `portfolio_risk.py` supplies both from its existing config sources. If `security_types` is provided but `diversified_types` is None, no filtering occurs (matches current behavior with no diversified-type set).

---

## 5. Scope

### In scope (Phase 2 MVP)
- New `portfolio_math/` package with pyproject.toml, `requires-python >=3.11`, deps: numpy, pandas, scipy, statsmodels
- 11 MVP kernels across stats, correlation, options modules
- `PerformanceMetrics` dataclass with faithful nested shape matching existing legacy output + `to_legacy_dict()` adapter
- `GreeksSnapshot` dataclass preserving existing options/result_objects.py contract (moved here, re-exported from original location)
- Per-kernel numerical equivalence tests (tolerance table from D4)
- Algebraic invariant tests (put-call parity, correlation symmetry, Σ risk_contributions = portfolio_vol²/vol, etc.)
- Integration smoke tests for risk_module flows that use these kernels
- `mypy --strict portfolio_math/` green
- Replace risk_module's internal implementations with re-exports + legacy dict adapters
- `portfolio_math/README.md` — usage, purity contract, spec alignment, migration note
- TODO entry for AI-excel-addin sandbox mount follow-up

### Out of scope (follow-ups, each with its own plan)
- **MC extraction** — requires API redesign per Codex R1
- **Payoff + OptionLeg/OptionStrategy domain types** — widens surface; validate MVP pattern first
- **Optimizer kernels + efficient frontier** — cvxpy dep; portfolio-view coupling
- **Stress shock application** — orchestration-heavy
- **Retiring `agent/building_blocks.py`** — Phase 3
- **Publishing to PyPI** — packaging-only follow-up
- **AI-excel-addin sandbox mount PR** — coordination work, tracked as TODO

---

## 6. Implementation phases

### P2.1 — Package scaffold + types.py + GreeksSnapshot migration (1 day)
- Create `portfolio_math/` directory with `pyproject.toml` (deps: numpy, pandas, scipy, statsmodels), `README.md` stub, `__init__.py`, `types.py`, `_utils.py`
- Define `PerformanceMetrics` dataclass in `types.py` — **first audit the real nested shape** via `grep` of downstream field access + characterization snapshot of one real call to `compute_performance_metrics`. Every top-level key + every nested sub-structure must be declared.
- Implement `PerformanceMetrics.to_legacy_dict()` field-by-field, preserving rounding and key ordering
- Move `GreeksSnapshot` from `options/result_objects.py` to `portfolio_math/types.py`. Update `options/result_objects.py` to re-export
- Run `options/` tests — must pass unchanged (re-export is transparent)
- Commit: `feat(portfolio_math): P2.1 scaffold + types + GreeksSnapshot migration`

### P2.2 — Options module (1.5 days)
- Extract `black_scholes_price`, `black_scholes_greeks`, `black76_price`, `black76_greeks`, `implied_volatility` from `options/greeks.py` into `portfolio_math/options.py`
- Move `_norm_cdf`, `_norm_pdf` into `portfolio_math/_utils.py`
- Update `options/greeks.py` to re-export
- Tests: `test_options.py` — put-call parity, intrinsic at expiry, IV round-trip, Greeks sanity (delta ∈ [-1, 1], gamma ≥ 0, etc.)
- Equivalence test: golden fixtures from real calls to risk_module's original functions, compare new output per-field with D4 tolerances
- Integration smoke: run `options/analyzer.py` test suite — must pass (GreeksSnapshot contract preserved + re-exports transparent)
- Commit: `feat(portfolio_math): P2.2 options math + Greeks + IV`

### P2.3 — Correlation module (1 day)
- Extract `compute_correlation_matrix`, `compute_covariance_matrix`, `compute_portfolio_volatility`, `compute_risk_contributions`, `compute_herfindahl` from `portfolio_risk_engine/portfolio_risk.py` into `portfolio_math/correlation.py`
- Input contract: **already-gross-normalized weights** (convention: `sum(abs(w.values())) == 1.0`) — per D3
- `compute_herfindahl(weights, security_types=None, diversified_types=None)` per D11 — both maps explicit, no hidden constants
- Update `portfolio_risk.py` legacy wrappers: they continue to accept raw weights, call `normalize_weights()`, then delegate
- Tests: symmetry, PSD, Σ contributions ≈ vol, Herfindahl edge cases (all-equal, one-dominant)
- Equivalence test: per D4 tolerances
- Integration smoke: run `build_portfolio_view` + risk-analysis-consuming tests
- Commit: `feat(portfolio_math): P2.3 correlation + risk decomposition`

### P2.4 — Stats module (1.5 days)
- Extract `compute_performance_metrics` from `portfolio_risk_engine/performance_metrics_engine.py` into `portfolio_math/stats.py`
- `min_capm_observations` is an explicit param (no config fallback) — per D3 + trap #6 fix
- Consolidate period conversions (`annualize_volatility`, `total_return_to_cagr`, `daily_to_monthly_compound`) from scattered sites
- Update `performance_metrics_engine.py` legacy wrapper: applies config-defaulted `min_capm_observations`, delegates to portfolio_math, returns `result.to_legacy_dict()`
- Tests: known-output fixtures (canonical SPY/AAPL series), CAGR identity, annualization identity
- Equivalence test: **CRITICAL** — this kernel has the most fields and broadest downstream consumption. Compare top-level and all nested keys, all rounded fields, warnings list. Per D4 tolerance.
- Integration smoke: run full `get_performance` call path under mocks, compare output dict to pre-extraction baseline
- Commit: `feat(portfolio_math): P2.4 stats module + compute_performance_metrics`

### P2.5 — Integration verification (1.5 days — Codex R1 expanded from 0.5)
- Run full risk_module test suite — must pass 100% minus pre-existing failures (34 failures baseline from Phase 1 smoke)
- Run `test_portfolio_math_equivalence.py` — all 11 kernels within D4 tolerance
- Run `test_portfolio_math_invariants.py` — all algebraic identities hold
- `mypy --strict portfolio_math/` green
- **Caller audit**: `grep -rn "compute_performance_metrics\|compute_correlation_matrix\|compute_covariance_matrix\|compute_portfolio_volatility\|compute_risk_contributions\|compute_herfindahl" --include="*.py"` — confirm no caller breaks. Specifically verify `portfolio_risk.py:2515`, `core/result_objects/realized_performance.py:403`, and `mcp_tools/monte_carlo.py:184`.
- Commit: `test(portfolio_math): P2.5 integration verification`

### P2.6 — README + version + CHANGELOG (0.5 day)
- Write `portfolio_math/README.md`: usage examples showing typed returns + composition with risk_client, purity contract, spec alignment, installation via PYTHONPATH, migration note for consumers wanting direct dataclass access
- Tag portfolio_math v0.1.0
- Update risk_module CHANGELOG
- Add TODO entry for AI-excel-addin sandbox mount follow-up
- Commit: `docs(portfolio_math): P2.6 README + v0.1.0`

**Total estimate**: 7 working days (up from 5 after Codex R1 corrections; still short of their 7-8 upper bound because MVP cut is tighter than I initially planned).

### Implementation pitfalls (consolidated from survey + Codex R1/R2 review)

1. **Legacy-dict key fidelity**: `PerformanceMetrics.to_legacy_dict()` must produce the exact nested shape, exact keys, exact rounding, and warnings list structure of the current engine output. Static audit of downstream field access BEFORE writing the dataclass fields. Affected sites include `portfolio_risk.py:2515`, `core/result_objects/realized_performance.py:403`.
2. **`min_capm_observations` param contract**: explicit parameter in portfolio_math; legacy wrapper supplies config-default. Document in the docstring.
3. **`normalize_weights` boundary**: portfolio_math expects pre-normalized weights. Legacy wrappers in `portfolio_risk.py` normalize first, then delegate. Document the convention in portfolio_math docstrings.
4. **statsmodels as a runtime dep**: add to `portfolio_math/pyproject.toml`. It's not a test dep.
5. **GreeksSnapshot re-export**: `options/result_objects.py` must preserve the current import path so `from options.result_objects import GreeksSnapshot` keeps working everywhere.
6. **numpy scalar leaks**: F36 caught `numpy.bool_` escaping a JSON path. Dataclass construction from engine results must `bool(...)`, `float(...)`, `int(...)`-coerce any numpy-scalar comparison or aggregate that flows into dataclass fields that will be serialized downstream.
7. **Per-kernel tolerance not uniform**: the equivalence-test module must declare tolerance per kernel via D4 table. A single global `allclose` won't work (IV solver will fail at `rtol=1e-12`).
8. **Invariant tests are necessary**: golden fixtures alone can silently drift if the fixture generation is itself broken. Algebraic invariants (put-call parity, correlation symmetry, Σ risk_contributions ≈ vol²) catch implementation bugs even when fixtures are wrong.
9. **Characterization snapshot BEFORE extraction**: for `compute_performance_metrics` specifically, capture a snapshot of one real call's output as a committed fixture BEFORE starting P2.4. That becomes the frozen reference for `to_legacy_dict()`.
10. **CVXPY exclusion**: don't accidentally pull optimizer imports into `portfolio_math/__init__.py` — must stay zero-cvxpy for MVP.

---

## 7. Files touched

### New files
- `portfolio_math/pyproject.toml`
- `portfolio_math/README.md`
- `portfolio_math/__init__.py`
- `portfolio_math/types.py`
- `portfolio_math/stats.py`
- `portfolio_math/correlation.py`
- `portfolio_math/options.py`
- `portfolio_math/_utils.py`
- `tests/test_portfolio_math_stats.py`
- `tests/test_portfolio_math_correlation.py`
- `tests/test_portfolio_math_options.py`
- `tests/test_portfolio_math_equivalence.py`
- `tests/test_portfolio_math_invariants.py`
- `tests/fixtures/portfolio_math/perf_metrics_spy_aapl.json` (committed golden fixture)
- `tests/fixtures/portfolio_math/risk_decomp_3asset.json`
- `tests/fixtures/portfolio_math/bs_greeks_canonical.json`

### Modified files (risk_module re-exports + legacy adapters)
- `portfolio_risk_engine/performance_metrics_engine.py` — delegate + `to_legacy_dict` conversion
- `portfolio_risk_engine/portfolio_risk.py` — delegate 5 correlation/risk kernels; normalize first
- `options/greeks.py` — delegate 5 pricing/Greeks/IV; remove inline `_norm_cdf`/`_norm_pdf`
- `options/result_objects.py` — re-export `GreeksSnapshot` from `portfolio_math.types`
- `CHANGELOG.md` — 0.2.x or separate entry
- `docs/TODO.md` — new entry for AI-excel-addin sandbox mount follow-up

### NOT touched
- `agent/registry.py`, `agent/building_blocks.py` (Phase 3)
- `risk_client/` (Phase 1, already shipped)
- `mcp_tools/`, `actions/`, `services/`, `routes/`
- `portfolio_risk_engine/monte_carlo.py` (MC deferred)
- `options/payoff.py`, `options/data_objects.py` (payoff/domain-types deferred)
- Optimizer files (deferred)
- `core/cash_helpers.py` (trap #5)

---

## 8. Tests

### New tests (in repo-level `tests/` per §3.1 flat-layout convention)

**Unit / property**:
- `test_portfolio_math_stats.py`: `compute_performance_metrics` on canonical SPY/AAPL series (fixtures); period conversion round-trips
- `test_portfolio_math_correlation.py`: symmetry, PSD, Σ contributions ≈ vol² / vol, Herfindahl bounds
- `test_portfolio_math_options.py`: put-call parity, intrinsic at expiry, IV round-trip (price → IV → price within atol=1e-6), Greeks sanity (delta in bounds, gamma ≥ 0)

**Numerical equivalence (the load-bearing drift test)**:
- `test_portfolio_math_equivalence.py`: for each kernel, feed committed golden fixture input through both risk_module's original and portfolio_math's extracted, assert per-kernel tolerance from D4 table holds.

**Algebraic invariants (Codex R1 rec: "golden fixtures not sufficient")**:
- `test_portfolio_math_invariants.py`: algebraic identities that should hold regardless of implementation drift. E.g., put-call parity: `call - put = S * e^(-qT) - K * e^(-rT)` within `atol=1e-10`. Correlation matrix symmetry: `corr == corr.T`. Risk contributions identity: `risk_contributions.sum() == σ_p` (NOT σ_p² — Codex R2 correction: individual `w_i * marginal_i` sums to σ_p²; the normalized contributions sum to σ_p). Zero-vol portfolio handling: risk_contributions on all-zero weights returns per-trap-#8 behavior (documented).

### Existing tests to keep green
- Full risk_module test suite (minus 34 pre-existing failures)
- `options/` test suite (GreeksSnapshot contract preserved)
- `get_performance` call-path integration smokes

### Type checking
- `mypy --strict portfolio_math/` exits 0
- All public functions have complete type annotations

---

## 9. Open questions — resolved by Codex R1

| # | Question | Resolution |
|---|---|---|
| 1 | Extraction vs. re-implementation | ✅ Extract with explicit `to_legacy_dict()` adapters (D1) |
| 2 | MVP kernel count | ✅ 11 (drop MC + payoffs + optimizer) |
| 3 | Dataclass vs. TypedDict | ✅ Tiered — scalars/matrices return `float`/`pd.DataFrame`; composites return dataclass (D2) |
| 4 | Legacy-wrapper key compat | ✅ Static grep + characterization snapshot BEFORE P2.4 (pitfall #9) |
| 5 | Package name | ✅ `portfolio_math` import / `portfolio-math` distribution (D7) |
| 6 | Numerical tolerance | ✅ Per-kernel table (D4) |
| 7 | Seed handling for MC | ⚪ Moot — MC deferred |
| 8 | AI-excel-addin coordination | ✅ Tracked as TODO, not bundled (D5) |

### New questions raised by v2 — resolved by Codex R2

- **PerformanceMetrics faithful shape**: ✅ Use dataclass tree with section-dataclasses at the top level, plain `dict`/`list` for opaque variable-keyed collections. Structure locked in D10. Not a TypedDict facade.
- **Herfindahl filter signature**: ✅ Keep `security_types: dict[str, str]` (per-ticker map) + `diversified_types: frozenset[str] | None`. Signature locked in D11.
- **Period conversion consolidation**: ✅ Keep period-conversion helpers private to `stats.py` module (not exported). Scope narrower — not a public consolidation effort in MVP.

---

## 10. Success criteria

- [ ] `portfolio_math/` package builds and installs cleanly
- [ ] All 11 MVP kernels implemented with typed signatures
- [ ] Composite returns use dataclasses with faithful nested-shape preservation; scalars return `float`; matrices return `pd.DataFrame`
- [ ] `PerformanceMetrics.to_legacy_dict()` produces byte-identical output to current `compute_performance_metrics` dict for the committed characterization fixture
- [ ] `GreeksSnapshot` moved to portfolio_math; re-exported from `options/result_objects.py`; all existing imports unchanged
- [ ] `mypy --strict portfolio_math/` exits 0
- [ ] Zero I/O, zero DB, zero network imports anywhere in `portfolio_math/`
- [ ] Per-kernel numerical equivalence tests pass with D4 tolerances
- [ ] Algebraic invariant tests green
- [ ] Full risk_module test suite green after re-export changes (minus 34 pre-existing failures)
- [ ] Sample agent sandbox code block (audit §6 pattern) type-checks and runs when `portfolio_math` is path-mounted
- [ ] `portfolio_math/README.md` documents purity contract, spec alignment, usage examples, PYTHONPATH install
- [ ] Version 0.1.0 tagged, CHANGELOG updated
- [ ] `docs/TODO.md` entry for AI-excel-addin sandbox mount follow-up
