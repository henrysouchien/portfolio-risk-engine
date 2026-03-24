# Monte Carlo Enhancement Plan — Distribution Models + MCP Tool + Agent Format

> **v6** — revised after Codex review rounds 1-5 (9 + 4 + 3 + 4 + 3 findings addressed).

## Context

Monte Carlo is the **only** scenario tool without an MCP tool, agent format, or interpretive flags. The engine (`portfolio_risk_engine/monte_carlo.py`) is solid but Gaussian-only, which understates tail risk. This plan adds:

1. **Configurable distribution models** — Student-t (fat tails) and historical bootstrap alongside the existing normal
2. **Scenario conditioning** — weight/value/volatility overrides for cross-tool chaining (optimize → MC, stress test → MC)
3. **MCP tool + agent format** — result class, interpretive flags, and MCP tool following the established three-layer pattern

No behavior change for existing callers — all new params default to current behavior.

**Scope**: New distribution models and conditioning are **MCP-only** for v1. The existing REST endpoint (`/api/monte-carlo`) and frontend continue using the current Gaussian-only path unchanged. REST/frontend extension is a separate future step — this avoids touching response models, API types, and frontend components in this plan.

---

## Step 1: Engine Extension — Distribution Models + Conditioning

**File**: `portfolio_risk_engine/monte_carlo.py`

**New signature**:
```python
def run_monte_carlo(
    risk_result: RiskAnalysisResult,
    num_simulations: int = 1000,
    time_horizon_months: int = 12,
    portfolio_value: Optional[float] = None,
    distribution: str = "normal",                       # NEW
    df: int = 5,                                        # NEW (Student-t only)
    vol_scale: float = 1.0,                             # NEW (covariance multiplier)
    resolved_weights: Optional[Dict[str, float]] = None, # NEW (upstream weight override)
    seed: Optional[int] = None,                          # NEW (deterministic RNG for testing)
) -> Dict[str, Any]:
```

### Distribution dispatch — new `_generate_shocks()` helper

- **Normal** (default): `rng.standard_normal()` — current behavior, no change.

- **Student-t** (proper multivariate construction with covariance preservation):
  ```python
  # Draw correlated normals
  z = rng.standard_normal(size=(num_simulations, time_horizon_months, n_assets))
  # Draw shared chi-square scale per (simulation, month) — preserves tail dependence
  s = rng.chisquare(df, size=(num_simulations, time_horizon_months)) / df
  # Scale: t = z / sqrt(s), broadcast s across assets
  t_shocks = z / np.sqrt(s[:, :, np.newaxis])
  # Rescale to preserve target covariance: multivariate-t has cov = df/(df-2) * Sigma,
  # so we shrink by sqrt((df-2)/df) to recover cov = Sigma
  t_shocks *= np.sqrt((df - 2) / df)
  ```
  This produces a true multivariate Student-t with elliptical tail dependence across assets (not independent per-asset t draws). The shared `s` ensures that when one asset has a fat-tail event, all correlated assets do too. The `sqrt((df-2)/df)` rescaling ensures the resulting distribution has the same covariance matrix as the normal case — without it, the multivariate-t inflates volatility by `df/(df-2)`.
  Require `df >= 3` (df ≤ 2 gives infinite variance; df must be numeric > 2, but we enforce integer >= 3 at the MCP layer).
  Cholesky transform applies the same way: `correlated_shocks = t_shocks @ transform.T`.

- **Bootstrap** (portfolio-return resampling):
  Resample rows from `risk_result.portfolio_returns` with replacement. Produces portfolio-level monthly returns directly — **skips Cholesky and per-asset decomposition**.
  - Minimum 12 months required; below that, fall back to normal with a **surfaced warning** (see fallback metadata below).
  - Empty or all-NaN `portfolio_returns` → fall back to normal with warning.
  - **Incompatible with `resolved_weights`** — historical returns embed current weights. Return error if both specified.
  - **Incompatible with `vol_scale != 1.0`** — historical returns embed historical volatility. Return error if both specified.
  - **Limitation note**: This is a portfolio-return bootstrap, not per-asset. It preserves the actual distribution (fat tails, skew, correlation structure) but only for the current weighting. This is explicitly documented in the MCP tool docstring.

### Conditioning params

- **`resolved_weights`**: Override `_extract_weights(risk_result)`. **Validated**:
  1. Non-empty dict
  2. All tickers must exist in `risk_result.covariance_matrix.columns` — missing tickers → error listing them
  3. All values must be numeric and finite (`float(v)` succeeds and `math.isfinite(v)`) — non-numeric/NaN/inf → error
  This constrains overrides to reweighting within the analyzed asset universe.

- **`portfolio_value`**: Override initial portfolio value. **Validation is at the MCP tool layer only** (not the engine): the MCP tool rejects `portfolio_value <= 0` before calling the engine. The engine's existing silent coercion (`<= 0 → 1.0`) is preserved for internal callers (REST endpoint, service layer) that pass `risk_result.total_value` directly — changing that would break the "no behavior change for existing callers" guarantee.

- **`vol_scale`**: Scale covariance matrix before Cholesky: `covariance *= vol_scale ** 2`. **Validated**: must be > 0. Negative or zero → error. Not applicable to bootstrap (error if `vol_scale != 1.0` with bootstrap).

- **`distribution`**: **Validated at engine level**: must be one of `"normal"`, `"t"`, `"bootstrap"`. Unknown values → `ValueError(f"Unknown distribution: {distribution}. Must be one of: normal, t, bootstrap")`. This ensures both the MCP tool path (which uses `Literal` type hints) and the building-block/agent path (which doesn't enforce enum membership at runtime) reject invalid values.

### Fallback metadata

When bootstrap falls back to normal (short history, empty returns), the engine must surface this:

```python
{
    ...existing fields...,
    "distribution": "normal",                    # actual distribution used
    "requested_distribution": "bootstrap",       # what was requested
    "distribution_fallback_reason": "Insufficient history (8 months < 12 minimum)",
    "distribution_params": {},
    "vol_scale": float,
    "weights_overridden": bool,
    "resolved_weights": dict | None,             # actual weights used (for chaining)
    "bootstrap_sample_size": None,               # set to None on fallback (not the short sample size)
    "warnings": ["Bootstrap requested but fell back to normal: only 8 months of history available (minimum 12)"],
}
```

When no fallback occurs, `requested_distribution == distribution` and `distribution_fallback_reason` is `None`.

**Important**: On fallback, `bootstrap_sample_size` is set to `None` (not the actual short sample count). This prevents the `small_bootstrap_sample` flag from firing when bootstrap wasn't actually used — avoiding contradictory "small bootstrap sample" + "fell back to normal" warnings.

---

## Step 2: MonteCarloResult Class

**File to create**: `core/result_objects/monte_carlo.py`

Pattern: follows `BacktestResult` (dataclass + `from_engine_output()` factory + 3 output methods). No `to_formatted_report()` — the MCP tool only exposes `summary`/`full`/`agent` formats.

```python
@dataclass
class MonteCarloResult:
    num_simulations: int
    time_horizon_months: int
    initial_value: float
    percentile_paths: Dict[str, List[float]]
    terminal_distribution: Dict[str, float]
    distribution: str = "normal"
    requested_distribution: str = "normal"
    distribution_fallback_reason: Optional[str] = None
    distribution_params: Dict[str, Any] = field(default_factory=dict)
    vol_scale: float = 1.0
    weights_overridden: bool = False
    resolved_weights: Optional[Dict[str, float]] = None
    bootstrap_sample_size: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    portfolio_name: Optional[str] = None
    analysis_date: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_engine_output(cls, data: dict, *, portfolio_name: str = None) -> "MonteCarloResult": ...

    def get_summary(self) -> dict: ...      # includes distribution, requested_distribution,
                                              # distribution_fallback_reason, warnings
    def get_agent_snapshot(self) -> dict: ...
    def to_api_response(self) -> dict: ...
```

All three output methods include `distribution`, `requested_distribution`, `distribution_fallback_reason`, and `warnings` — ensuring fallback visibility regardless of which `format` the caller uses.

**Agent snapshot shape** (consumed by flags):
```python
{
    "mode": "monte_carlo",
    "simulation": {
        "num_simulations": int,
        "time_horizon_months": int,
        "distribution": str,                  # actual distribution used
        "requested_distribution": str,         # what was requested
        "distribution_fallback_reason": str | None,
        "distribution_params": dict,
        "vol_scale": float,
        "bootstrap_sample_size": int | None,
    },
    "terminal": {
        "mean": float, "median": float, "p5": float, "p95": float,
        "var_95": float, "cvar_95": float, "probability_of_loss": float,
        "max_gain_pct": float, "max_loss_pct": float,
    },
    "initial_value": float,
    "conditioning": {
        "weights_overridden": bool,
        "resolved_weights": dict | None,      # actual weights for downstream chaining
        "vol_scale": float,
    },
    "warnings": list[str],
}
```

**Modify**: `core/result_objects/__init__.py` — add `MonteCarloResult` to imports + `__all__`.

---

## Step 3: Interpretive Flags

**File to create**: `core/monte_carlo_flags.py`

Pattern: follows `core/backtest_flags.py`.

```python
def generate_monte_carlo_flags(snapshot: dict) -> list[dict]:
```

| Condition | Type | Severity | Message |
|-----------|------|----------|---------|
| `distribution != requested_distribution` | `distribution_fallback` | warning | "Requested {req} but fell back to {actual}: {reason}" |
| prob_of_loss > 0.50 | `high_loss_probability` | warning | "Over 50% probability of loss over {months} months" |
| var_95 / initial_value > horizon-scaled threshold¹ | `extreme_var` | warning | "95% VaR exceeds {pct}% of portfolio value" |
| bootstrap_sample_size < 24 | `small_bootstrap_sample` | warning | "Bootstrap uses only {n} months — results may be unstable" |
| num_simulations < 500 | `low_simulation_count` | info | "Low simulation count; consider 1000+ for stable estimates" |
| df < 4 (Student-t) | `extreme_fat_tails` | info | "Student-t df={df} produces very heavy tails" |
| vol_scale != 1.0 | `vol_regime_adjustment` | info | "Volatility scaled by {x}x (regime-conditional)" |
| warnings non-empty | `engine_warnings` | info | "{warning text}" (one flag per warning) |
| prob_of_loss < 0.05 | `low_loss_probability` | success | "Less than 5% probability of loss" |

¹ **Horizon-scaled VaR threshold**: Flag fires when `var_95 / initial_value > threshold`. `var_95` is an absolute dollar amount from the engine; the flag converts to a ratio for comparison. `threshold = base_pct * sqrt(months / 12)` where `base_pct = 0.20`. This scales ~20% at 12 months to ~28% at 24 months, ~40% at 48 months, reflecting that longer horizons naturally produce wider distributions.

Sorted by severity order (error → warning → info → success).

---

## Step 4: MCP Tool

**File to create**: `mcp_tools/monte_carlo.py`

Pattern: follows `mcp_tools/backtest.py`.

```python
@handle_mcp_errors
def run_monte_carlo(
    user_email: Optional[str] = None,
    num_simulations: int = 1000,
    time_horizon_months: int = 12,
    distribution: Literal["normal", "t", "bootstrap"] = "normal",
    df: int = 5,
    vol_scale: float = 1.0,
    resolved_weights: Optional[dict] = None,
    portfolio_value: Optional[float] = None,
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "agent"] = "agent",
    output: Literal["inline", "file"] = "inline",
    use_cache: bool = True,
) -> dict:
```

**Flow**:
1. `_load_portfolio_for_analysis(user_email, portfolio_name, use_cache=use_cache)` → portfolio_data
2. `PortfolioService(cache_results=use_cache).analyze_portfolio(portfolio_data)` → risk_result
3. Validate params:
   - `num_simulations` in [100, 50000]
   - `time_horizon_months` in [1, 120]
   - `df >= 3` when `distribution == "t"`
   - `vol_scale > 0`
   - `portfolio_value > 0` when provided (MCP layer only — engine still coerces for internal callers)
   - `resolved_weights + bootstrap` → error
   - `vol_scale != 1.0 + bootstrap` → error
4. Call engine `run_monte_carlo(risk_result, ...)` with all params
5. Wrap in `MonteCarloResult.from_engine_output()`
6. Branch on `format`:
   - `"agent"` → `_build_agent_response(result)` (snapshot + flags)
   - `"summary"` → `result.get_summary()`
   - `"full"` → `result.to_api_response()`
7. If `output == "file"` → save JSON, return file_path

Private helpers: `_build_agent_response()`, `_save_full_monte_carlo()`.

---

## Step 5: MCP Server Registration + Agent Surface Update

**File**: `mcp_server.py`
- Import `from mcp_tools.monte_carlo import run_monte_carlo as _run_monte_carlo`
- Register `@mcp.tool()` wrapper near other scenario tools (stress_test/backtest area)
- Docstring with examples for agent discoverability

**File**: `services/agent_building_blocks.py`
- Update existing `run_monte_carlo()` wrapper (lines 462-491) to accept and pass through all new params: `distribution`, `df`, `vol_scale`, `resolved_weights`, `portfolio_value`. The `distribution` param **must** use `Literal["normal", "t", "bootstrap"]` type annotation (not bare `str`) — the agent schema builder in `routes/agent_api.py` only emits enum choices from `Literal` annotations. Update the docstring. Add the same validation rules as the MCP tool (`df >= 3`, `vol_scale > 0`, `portfolio_value > 0`, bootstrap incompatibilities).

**File**: `services/agent_registry.py`
- No schema/description changes needed — the registry derives these from the callable signature and docstring at runtime. The building block signature update above is sufficient.

**NOT in scope** (explicitly MCP-only for v1):
- REST endpoint (`/api/monte-carlo` in `app.py`) — unchanged, continues Gaussian-only
- Response models (`models/response_models.py`) — unchanged
- Frontend types/services/UI — unchanged
- These are a separate future step when we want distribution selection in the browser UI.

---

## Step 6: Tests (~60 new)

### Deterministic RNG strategy

The engine currently instantiates an unseeded `np.random.default_rng()` internally. To make statistical assertions reliable:
- Add an optional `seed: Optional[int] = None` param to `run_monte_carlo()`. When provided, `rng = np.random.default_rng(seed)`. When `None` (default), behavior is unchanged (random seed).
- Tests that make statistical assertions (fatter tails, covariance preservation, spread comparisons) use a fixed seed + high sim count (5000) for stability.
- Tests that only check output shape/structure can use any seed with low sim count (100) for speed.

### Engine tests (extend `tests/test_monte_carlo.py`, ~24 tests):
- Student-t output shape matches normal output shape
- Student-t produces fatter tails than normal (5000 sims, statistical assertion on p5/p95 spread)
- Student-t covariance preservation: verify terminal distribution variance matches normal case within tolerance (regression test for `sqrt((df-2)/df)` rescaling)
- Student-t shared chi-square construction: tail events are correlated across assets (verify joint extreme returns)
- Student-t df=3 works, df=2 raises ValueError
- Student-t with single asset works
- Bootstrap output shape matches normal output shape
- Bootstrap short-history (<12 months) falls back to normal with warning
- Bootstrap exact boundary: 11 months → fallback, 12 months → bootstrap
- Bootstrap empty/NaN portfolio_returns falls back to normal with warning
- Bootstrap fallback surfaces `requested_distribution`, `distribution_fallback_reason`, `warnings`
- Bootstrap rejects `resolved_weights` combo → error
- Bootstrap rejects `vol_scale != 1.0` combo → error
- Bootstrap preserves return range (terminal values within plausible historical range)
- `vol_scale > 1.0` increases p95-p5 spread
- `vol_scale <= 0` raises ValueError
- `resolved_weights` override: custom weights used, output contains `resolved_weights` dict
- `resolved_weights` with tickers not in covariance matrix → error listing missing tickers
- `resolved_weights` with non-numeric/NaN/inf values → error
- `portfolio_value <= 0` at MCP layer → error (engine still coerces for internal callers)
- Invalid `distribution` string → ValueError at engine level
- Distribution metadata in output: `distribution`, `requested_distribution`, `distribution_params`
- Bootstrap fallback sets `bootstrap_sample_size=None` (not the short count)
- Default behavior unchanged: `distribution="normal"` matches old output structure

### Result class tests (`tests/test_monte_carlo_result.py`, ~8 tests):
- `from_engine_output` round-trip
- `get_summary` has expected keys including `distribution`, `requested_distribution`, `distribution_fallback_reason`, `warnings`
- `get_summary` with fallback scenario: summary surfaces fallback fields correctly
- `get_agent_snapshot` structure matches documented shape
- `get_agent_snapshot` includes `resolved_weights` dict and `warnings`
- `to_api_response` contains all fields including fallback fields, JSON-safe
- Fallback fields populated correctly when `requested_distribution != distribution`
- Warnings list flows through to all three output methods

### Flag tests (`tests/test_monte_carlo_flags.py`, ~13 tests):
- `distribution_fallback` flag fires when `requested != actual`
- `small_bootstrap_sample` flag does NOT fire on fallback (bootstrap_sample_size=None)
- `high_loss_probability` flag: prob_of_loss > 0.50 → warning
- `extreme_var` flag: horizon-scaled threshold (test 12mo and 36mo thresholds differ)
- `small_bootstrap_sample` flag: sample < 24 → warning
- `low_simulation_count` flag: sims < 500 → info
- `extreme_fat_tails` flag: df < 4 → info
- `vol_regime_adjustment` flag: vol_scale != 1.0 → info
- `engine_warnings` flag: warnings list surfaced
- `low_loss_probability` flag: prob_of_loss < 0.05 → success
- No spurious flags on clean normal run
- Severity sort order: warnings before info before success
- Empty snapshot returns empty flags list

### MCP tool tests (`tests/mcp_tools/test_monte_carlo_mcp.py`, ~14 tests):
- Default call returns success
- `format="agent"` returns snapshot + flags
- `format="summary"` returns summary dict with fallback fields
- `format="full"` returns full API response
- `output="file"` returns file_path
- `distribution="t"` succeeds with df param
- `distribution="bootstrap"` succeeds
- `vol_scale` param passes through
- `resolved_weights` param passes through with weights in response
- Invalid distribution returns error
- `num_simulations` out of range returns error
- `vol_scale <= 0` returns error
- `portfolio_value <= 0` returns error
- `resolved_weights + bootstrap` returns error

### Building block tests (extend `tests/services/test_agent_building_blocks.py`, ~3 tests):
- New params (`distribution`, `df`, `vol_scale`, `resolved_weights`, `portfolio_value`) pass through to engine
- Validation rules match MCP tool (df >= 3, vol_scale > 0, portfolio_value > 0, bootstrap incompatibilities)
- Agent registry schema test: assert `distribution` param in the registry-exposed schema contains enum choices `["normal", "t", "bootstrap"]` (regression guard for `Literal` annotation)

---

## File Summary

**Create (4)**:
1. `core/result_objects/monte_carlo.py`
2. `core/monte_carlo_flags.py`
3. `mcp_tools/monte_carlo.py`
4. `tests/mcp_tools/test_monte_carlo_mcp.py`

**Modify (6)**:
1. `portfolio_risk_engine/monte_carlo.py` — distribution, df, vol_scale, resolved_weights params + proper multivariate-t
2. `core/result_objects/__init__.py` — re-export MonteCarloResult
3. `mcp_server.py` — register run_monte_carlo tool
4. `services/agent_building_blocks.py` — pass through new params
5. `tests/test_monte_carlo.py` — extend with distribution + conditioning tests
6. `tests/services/test_agent_building_blocks.py` — extend with new param pass-through tests

**New test files (2)**:
1. `tests/test_monte_carlo_result.py`
2. `tests/test_monte_carlo_flags.py`

---

## Step Dependencies

```
Step 1 (Engine) ──→ Step 2 (Result Class) ──→ Step 3 (Flags)
                                            ──→ Step 4 (MCP Tool) ──→ Step 5 (Registration + Agent Surface)
Step 6 (Tests) — in parallel with each step
```

## Verification

1. **Unit tests**: `pytest tests/test_monte_carlo.py tests/test_monte_carlo_result.py tests/test_monte_carlo_flags.py tests/mcp_tools/test_monte_carlo_mcp.py tests/services/test_agent_building_blocks.py -v`
2. **MCP tool smoke test**: Call `run_monte_carlo()` via portfolio-mcp with default params → verify agent format response
3. **Distribution comparison**: Run normal vs t(df=5) vs bootstrap on same portfolio → verify t has wider tails (joint tail events correlated), bootstrap matches historical range
4. **Conditioning**: Run `run_monte_carlo(resolved_weights={...})` → verify weights in response match override, not current portfolio
5. **Fallback**: Run `run_monte_carlo(distribution="bootstrap")` with short-history portfolio → verify fallback to normal with `requested_distribution="bootstrap"`, `distribution="normal"`, warnings populated
6. **Backward compat**: Existing frontend/REST calls produce identical results (all new params default to current behavior)
7. **Agent surface**: Call `run_monte_carlo` via agent code execution registry → verify new params work
