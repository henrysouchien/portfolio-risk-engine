# portfolio_math Monte Carlo Kernel Extraction (Phase 3C)

**Status**: ✅ v6 — Codex R6 PASS. Implementation-ready. v6 = v5 + Codex R5 fixes (correct test helper name `_build_three_asset_result`, snapshot equality consistency). 6 review rounds total (R1-R5 FAIL → R6 PASS).
**Date**: 2026-04-25
**Parent**: `AGENT_SURFACE_AUDIT.md` Phase 3C row.
**Prior plans referenced**: `PORTFOLIO_MATH_EXTRACTION_PLAN.md` (Phase 2 — base extraction), `PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md` + `PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md` (Phase 3D — pattern match).
**Effort estimate**: 4-6 days. (Codex R1 said "5-7 days, API redesign"; my v1 said "2-4 days, clean move." Truth is in the middle: it IS partial API redesign because the existing helpers weren't designed for sandbox composition, but the algorithm is preserved verbatim and the orchestrator already does the impure work.)

---

## 1. Goal

Extract the Monte Carlo simulation engine into `portfolio_math` via a **two-tier API**:

1. **Low-level primitive** `simulate_paths(...)` — takes a fully-resolved per-asset drift array + covariance + weights + distribution params. Pure numerics. The composition unlock — agents can compute their own drift any way they like and feed it in.
2. **High-level wrapper** `run_monte_carlo_from_components(...)` — takes materialized risk-analysis inputs (covariance, weights, asset_vol_summary, portfolio_returns, stock_betas) + drift-model selectors (`drift_model`, `expected_returns`, `risk_free_rate`, `drift_overrides`, `scenario_shocks`). Internally resolves drift, then calls `simulate_paths`. Mirrors today's `run_monte_carlo` behavior exactly.

After this ships, the agent sandbox can:
- Call the high-level wrapper with materialized risk-analysis arrays — equivalent to today's `rc.run_monte_carlo` but local
- **Or** compute its own drift (custom drift model, scenario-conditioning, time-varying drift) and call the low-level `simulate_paths` directly

The orchestrator on risk_module's side (`agent/building_blocks.run_monte_carlo` → `portfolio_risk_engine.monte_carlo.run_monte_carlo`) is refactored to delegate to `portfolio_math.run_monte_carlo_from_components`. Wire-format unchanged. Existing engine entry preserved as a thin wrapper that pulls components out of `RiskAnalysisResult` and delegates.

---

## 2. Non-goals

- **No HTTP path removal.** `rc.run_monte_carlo(...)` continues to work.
- **No `MonteCarloResult` dataclass move.** Lives at `core/result_objects/monte_carlo.py:12`. Stays as the wire format on the orchestrator side.
- **No `RiskAnalysisResult` → `portfolio_math` move.** That dataclass is the orchestrator's bundle; `portfolio_math` shouldn't depend on it.
- **No portfolio-loading or factor-fetch extraction.** Those stay in `agent/building_blocks` + `services/`.
- **No algorithm change.** v2 preserves vol_scale-on-covariance behavior, bootstrap-fallback-to-normal logic, scenario-shocks nonlinear monthly↔annual round-tripping, percentile levels (5/25/50/75/95), histogram bins (30), terminal-distribution shape — all byte-identical to today.
- **No statsmodels dependency.** MC kernel uses numpy + pandas (for `pd.Series`/`pd.DataFrame` inputs to `_prepare_bootstrap_history` and asset_vol_summary handling). No scipy.stats either — Student-t generation is rolled by hand via `chisquare` (verified at `portfolio_risk_engine/monte_carlo.py:533`).

---

## 3. Current state (verified 2026-04-25 via end-to-end read of `portfolio_risk_engine/monte_carlo.py:1-758`)

### 3.1 The actual call graph + impurity boundary

`portfolio_risk_engine/monte_carlo.py` is **already pure-on-materialized-inputs**. It depends only on `numpy`, `pandas`, and `core.result_objects.RiskAnalysisResult` for type-checking. The "impurity" Codex R1 was concerned about lives in callers, not in this file.

| Lines | Function | What it does | Where impurity lives |
|---|---|---|---|
| 81-96 | `_extract_weights(risk_result)` | Reads `risk_result.portfolio_weights` or `risk_result.allocations["Portfolio Weight"]` | Pure on materialized RiskAnalysisResult |
| 99-150 | `_validate_resolved_weights(risk_result, resolved_weights)` | Validates ticker keys against covariance index | Pure |
| 153-175 | `_resolve_tickers_and_covariance(risk_result, weights)` | Pulls `risk_result.covariance_matrix` rows/cols by weight tickers | Pure |
| 178-200 | `_resolve_weight_vector(tickers, raw_weights)` | Aligns weights to ticker order, normalizes (gross or net) | Pure |
| 203-243 | `_resolve_historical_monthly_drift(risk_result, tickers)` | Reads `risk_result.portfolio_returns.mean()` + `risk_result.asset_vol_summary["Annual Return"]` | Pure |
| 246-348 | `_resolve_monthly_drift(risk_result, tickers, drift_model, ...)` | Dispatches drift_model + applies drift_overrides + scenario_shocks (nonlinear monthly↔annual) | Pure |
| 351-383 | `_build_correlation_transform(covariance)` | **Misnamed**: takes covariance, returns Cholesky of it (not correlation). PSD repair fallback. | Pure |
| 386-442 | `_build_flat_result(...)` | Constructs zero-vol/empty-portfolio result dict | Pure |
| 445-457 | `_prepare_bootstrap_history(portfolio_returns)` | Coerces `pd.Series`/`pd.DataFrame` → `np.ndarray`, drops NaN | Pure |
| 460-536 | `_generate_shocks(rng, distribution, ...)` | Generates either `correlated_shocks (sims, months, n_assets)` OR `monthly_portfolio_returns (sims, months)` for bootstrap. Returns 3-tuple `(asset_shocks, portfolio_returns, metadata)` — exactly one of the first two is non-None. | Pure |
| 539-758 | `run_monte_carlo(risk_result, ...)` | Orchestrates: extract weights → resolve covariance + drift → scale covariance by vol_scale² → build transform → generate shocks → apply weights (asset shocks → portfolio returns) → compound paths → percentile + VaR/CVaR + histogram → assemble dict | Pure |

**The actual impurity** is in `agent/building_blocks.run_monte_carlo` (around line 488) which calls `get_risk_analysis(...)` to materialize a `RiskAnalysisResult` from DB + factor service. After that, it calls into `portfolio_risk_engine.monte_carlo.run_monte_carlo(risk_result, ...)`. The engine itself is pure.

### 3.2 The `_generate_shocks` tuple return — critical to API design

At line 470: `return tuple[Optional[np.ndarray], Optional[np.ndarray], Dict[str, Any]]`. Specifically:
- For `distribution="normal"` or `distribution="t"`: returns `(correlated_shocks, None, metadata)` — caller multiplies by `weight_vector` at line 689 to get portfolio returns
- For `distribution="bootstrap"` (sufficient history): returns `(None, monthly_portfolio_returns, metadata)` — caller skips weight application; portfolio returns are sampled directly from history
- Bootstrap fallback (insufficient history → falls through to normal): returns `(correlated_shocks, None, metadata_with_warning)`
- Empty `n_assets` or `transform=None`: returns `(None, None, metadata)`

This dual return shape is **part of the API contract** — bootstrap fundamentally returns portfolio-level returns (no per-asset structure), and that's why bootstrap can't compose with scenario_shocks (no per-asset shock to add per-asset stress to).

### 3.3 vol_scale semantics (line 583-590, 633)

- Validated at lines 583-590: `vol_scale > 0` required; **must be 1.0 for bootstrap** (or ValueError).
- Applied at line 633: `scaled_covariance = covariance * (vol_scale_value ** 2)` — scales covariance pre-transform.
- This means vol_scale flows through the transform → into shocks → into asset returns. It does NOT scale `weight_vector @ asset_returns` separately. The kernel's correctness depends on covariance scaling, not path-level scaling.

### 3.4 Scenario-shocks math (lines 326-346) — nonlinear

```python
base_monthly = monthly_drift[idx]                                     # current monthly
base_annual = (1.0 + base_monthly) ** 12 - 1.0                        # un-compound to annual
combined_annual = base_annual + stress_drift_annual                    # add stress in annual space
monthly_drift[idx] = _annual_to_monthly_compound(combined_annual)      # re-compound to monthly
```

`stress_drift_annual = sum(beta(factor) × shock(factor) for factor, shock in scenario_shocks)`.

**Why nonlinear**: monthly compounding is `(1+r)^(1/12) - 1`, not `r/12`. Adding stress in annual space + re-compounding ≠ adding stress directly to monthly drift. Test pinned at `tests/test_monte_carlo.py:1079-1096`: AAPL base annual 0.12 + market shock −0.10 × beta 1.0 = 0.02 combined annual → `_compound_monthly(0.02)`.

### 3.5 Result-dict shape (lines 736-758) — fuller than v1 plan claimed

Top-level keys (15+): `num_simulations`, `time_horizon_months`, `initial_value`, `percentile_paths` (5/25/50/75/95 — five percentiles, not three), `terminal_distribution` (mean/median/min/max/p5/p95/var_95/cvar_95/probability_of_loss/max_gain_pct/max_loss_pct — eleven fields), `histogram` (30 bins, edges + counts), `distribution`, `requested_distribution`, `distribution_fallback_reason`, `distribution_params` (dict for t-distribution df), `vol_scale`, `weights_overridden`, `resolved_weights`, `dropped_tickers`, `drift_model`, `drift_overrides_count`, `bootstrap_sample_size`, `warnings`. Conditionally adds `scenario_conditioning` (dict with shocks + overrides_applied + drift_model_base) when `scenario_shocks` provided.

The `MonteCarloResult` wrapper at `core/result_objects/monte_carlo.py:12` consumes this shape via `from_engine_output(dict_result)`.

### 3.6 Existing tests at `tests/test_monte_carlo.py` (NOT `tests/portfolio_risk_engine/`)

v1 plan referenced a non-existent test path. The actual file is `tests/test_monte_carlo.py`. Verified via `ls /Users/henrychien/Documents/Jupyter/risk_module/tests/test_monte_carlo.py`. Pinned tests include scenario-shocks, drift-overrides, vol_scale validation, bootstrap fallback, weights-overridden flow, dropped-tickers warning. These are the regression contract.

### 3.7 `portfolio_math/pyproject.toml` already has scipy + statsmodels

v1 plan said "no new deps; scipy already there." That's right; statsmodels is also already there (Phase 2 added it for `compute_performance_metrics`). MC kernel uses numpy + pandas only. No new deps.

### 3.8 Caller — `agent/building_blocks.py:488` (corrected per Codex R2)

`run_monte_carlo` (the agent-facing wrapper at ~line 488) does:
1. `_load_portfolio_for_analysis(user_email, portfolio_name, use_cache=True)` (line 523) — DB load
2. `enrich_portfolio_factor_proxies(...)` (lines 526-533) — factor proxy enrichment
3. `risk_result = PortfolioService(cache_results=True).analyze_portfolio(portfolio_data)` (line 534) — materializes `RiskAnalysisResult`
4. `expand_risk_result_for_tickers(...)` if `resolved_weights` provided (lines 535-547)
5. Calls into `portfolio_risk_engine.monte_carlo.run_monte_carlo(risk_result, ...)` and returns dict with `simulation` field (NOT direct `MonteCarloResult` wrap — that lives elsewhere in the call chain).

Verified by Codex R2 + by reading the file at lines 523-547. v2's claim about `get_risk_analysis` and `MonteCarloResult.from_engine_output` was wrong; v3 corrects it. The point that matters: this caller is the impurity (DB + enrichment + portfolio analysis); `portfolio_risk_engine.monte_carlo.run_monte_carlo(risk_result, ...)` itself is pure.

`MonteCarloResult` wrapping happens in a different call path (the MCP/HTTP wrapping path), tested at `tests/test_monte_carlo_result.py:67-213`. v3 adds those tests to Step 5's verification list.

### 3.9 Phase 3D pattern (for reference on un-curated root exports)

`portfolio_math/__init__.py` already root-exports `OptionLeg`, `OptionStrategy`, 10 payoff functions, 5 pricing primitives, and stats/correlation primitives. v2 follows the same pattern: all new MC primitives at root.

---

## 4. Design decisions

### 4.1 Two-tier API — composability + behavior preservation

| Tier | Function | Purpose |
|---|---|---|
| Low-level primitive | `simulate_paths(covariance, weights, drift, distribution, num_sims, horizon, vol_scale, df, portfolio_returns_for_bootstrap, initial_value, seed) → dict` | Takes pre-resolved per-asset drift. The composition unlock. |
| High-level wrapper | `run_monte_carlo_from_components(covariance, weights_dict, tickers, asset_vol_summary, portfolio_returns, stock_betas, drift_model, expected_returns, risk_free_rate, drift_overrides, scenario_shocks, num_sims, horizon, distribution, df, vol_scale, portfolio_value, seed) → dict` | Resolves drift via 4 drift_models + drift_overrides + scenario_shocks, then calls `simulate_paths`. Behavior-equivalent to today's `run_monte_carlo`. |
| Helpers (also exposed) | `nearest_psd`, `build_covariance_transform`, `compute_monthly_drift_from_components`, `terminal_stats` | Building blocks. Agent can call any subset. |

### 4.2 Naming — fix `_build_correlation_transform`

Today's `_build_correlation_transform(covariance)` is misnamed. Public name: `build_covariance_transform(covariance)`. Returns Cholesky factor. Internal alias preserved on the engine side as `_build_correlation_transform = build_covariance_transform` for shim compatibility (zero behavior change; same call sites).

### 4.3 vol_scale stays on covariance — no semantic redesign

Inside `simulate_paths`:
1. Validate `vol_scale > 0`. If `distribution=="bootstrap"` and `vol_scale != 1.0`, raise `ValueError` (preserving today's lines 589-590).
2. Apply scaling: `scaled_cov = covariance * vol_scale ** 2` (today's line 633).
3. Build transform on scaled covariance.

Rationale: v1 proposed moving vol_scale into accumulation. That would change behavior because the transform is built on UNscaled covariance under v1 — so the shocks have unscaled correlation but scaled magnitudes. Mathematically equivalent for the magnitude only, but the agent sandbox composability case is ambiguous about whether the agent wants to override vol-scaling per-step. Keeping it on covariance preserves byte-identical output and matches the test pins.

### 4.4 Bootstrap handling — fallback logic stays in the kernel

Today's `_generate_shocks` lines 481-515 own the bootstrap-fallback-to-normal logic (history < 12 months → fall back with warning). v2 keeps this in the kernel — it's a simulation-contract concern, not orchestration. `simulate_paths(distribution="bootstrap", portfolio_returns_for_bootstrap=array)`:

- If `array is None` or `array.size < 12` → log fallback in metadata, downgrade to normal (no exception)
- This preserves today's lines 484-506 behavior

### 4.5 Tuple return shape preserved internally

The shock generator inside `simulate_paths` keeps the `(asset_shocks, portfolio_returns, metadata)` tuple internally because bootstrap returns portfolio returns directly. The PUBLIC `simulate_paths` return is the unified result dict — internal tuple is hidden.

### 4.6 Drift resolution: high-level wrapper handles `drift_model` + `drift_overrides` + `scenario_shocks`

Low-level `simulate_paths` takes `drift: np.ndarray | None` (per-asset monthly drift). If `None`, defaults to zeros. The four drift_models, drift_overrides, and scenario_shocks-via-betas math live in `compute_monthly_drift_from_components(...)` — the high-level wrapper calls this then passes the resolved array to `simulate_paths`.

This means an agent can:
- Use the wrapper with named drift_model selectors (matches today's HTTP API)
- OR build their own drift array (any custom math) and call `simulate_paths` directly with it
- OR mix: call `compute_monthly_drift_from_components(...)` for the historical baseline, then add their own custom adjustments before calling `simulate_paths`

### 4.7 What the orchestrator (`portfolio_risk_engine/monte_carlo.py::run_monte_carlo`) becomes

A thin wrapper that:
1. Pulls components out of `risk_result` (covariance, weights, asset_vol_summary, portfolio_returns, stock_betas) via the existing `_extract_weights` / `_resolve_tickers_and_covariance` / `_resolve_weight_vector` helpers (which stay in this file because they're tied to `RiskAnalysisResult` shape).
2. Calls `portfolio_math.run_monte_carlo_from_components(...)` with materialized arrays.
3. Adds **four** orchestrator-only result-dict fields (corrected per Codex R2):
   - `weights_overridden: bool` — true when `resolved_weights` was provided
   - `resolved_weights: dict | None` — the per-ticker weight map after normalization
   - `dropped_tickers: list[str]` — tickers in `resolved_weights` not in covariance
   - **Appended to `warnings`**: `"Dropped N ticker(s) not in covariance matrix: ..."` when `dropped_tickers` is non-empty (matches `portfolio_risk_engine/monte_carlo.py:657-662`; asserted at `tests/test_monte_carlo.py:643-655`; deduped at `tests/test_monte_carlo_flags.py:271-285`). The orchestrator inserts this into the result dict's `warnings` array AFTER `portfolio_math` returns.
4. Returns the merged dict — wire-format unchanged.

The existing private helpers `_resolve_monthly_drift`, `_build_correlation_transform`, `_generate_shocks`, `_build_flat_result`, `_prepare_bootstrap_history`, `_nearest_psd` become thin shims that import-and-call `portfolio_math` versions, preserving any internal callers (matches Phase 3D's shim-flip approach in `options/data_objects.py` + `options/payoff.py`).

### 4.8 `MonteCarloInputs` dataclass — DEFER

Considered: a dataclass at `portfolio_math/types.py` to bundle the materialized inputs for `run_monte_carlo_from_components`. Rejected for v1 of this work — the parameter list is long but not unmanageable (~14 keyword args). Adding a dataclass is a separate API design choice; punting keeps scope tight.

---

## 5. Scope — files to change (LOCKED PAIR with §6 for §5.1 file rows; §5.2 is operational)

### 5.1 Files

| # | File | Change |
|---|------|--------|
| 1 | `portfolio_math/monte_carlo.py` (new) | Implements low-level `simulate_paths`, helpers (`nearest_psd`, `build_covariance_transform`, `compute_monthly_drift_from_components`, `terminal_stats`), and high-level `run_monte_carlo_from_components`. ~400 lines. Preserves today's algorithm verbatim including bootstrap fallback, vol_scale-on-covariance, scenario_shocks nonlinear math. |
| 2 | `portfolio_math/__init__.py` | Add 6 root exports: `simulate_paths`, `run_monte_carlo_from_components`, `compute_monthly_drift_from_components`, `build_covariance_transform`, `nearest_psd`, `terminal_stats`. |
| 3 | `portfolio_risk_engine/monte_carlo.py` (refactor) | `run_monte_carlo` becomes a thin wrapper that pulls components from `risk_result` and delegates to `portfolio_math.run_monte_carlo_from_components`. Adds orchestrator-only fields (`weights_overridden`, `resolved_weights`, `dropped_tickers`) to the returned dict + copies-and-appends the dropped-tickers warning to `result["warnings"]`. The **7** private helpers (`_nearest_psd`, `_build_correlation_transform`, `_generate_shocks`, `_resolve_monthly_drift`, `_resolve_historical_monthly_drift`, `_build_flat_result`, `_prepare_bootstrap_history`) become thin import-shims that delegate to `portfolio_math` (alias module-level names so internal callers + tests still find them). |
| 4 | `tests/portfolio_math/test_monte_carlo.py` (new) | Pure-kernel unit tests for the new primitives — see §7 list. |
| 5 | `tests/test_monte_carlo.py` (existing, extend) | Add a characterization snapshot test: `test_run_monte_carlo_byte_identical_pre_post_refactor` — fixed seed + small synthetic `RiskAnalysisResult`, capture baseline output dict before refactor, assert exact equality after (no float tolerance — for true characterization). Existing tests for `_resolve_monthly_drift`, vol_scale, bootstrap fallback, weights-overridden, dropped-tickers, scenario_shocks all continue to pass via the import shims (no rewrite needed). |
| 5b | `tests/fixtures/monte_carlo_snapshot.json` (new) | Pre-refactor snapshot of the engine output dict for the synthetic input used in test #5's `test_run_monte_carlo_byte_identical_pre_post_refactor`. Generated as a one-time pre-refactor capture (Step 4a in §6). Loaded as `json.load(open("tests/fixtures/monte_carlo_snapshot.json"))` in the test. Committed alongside Step 3's refactor. |
| 6 | `core/result_objects/monte_carlo.py` | No code change. Verify `from_engine_output(dict)` still works against the post-refactor dict shape. (Step 4 of §6 confirms via the snapshot test.) |
| 7 | `agent/building_blocks.py` | No code change. The wrapper at line ~488 already calls `portfolio_risk_engine.monte_carlo.run_monte_carlo(...)`; that entry signature is unchanged after refactor. Verify existing tests still pass. |
| 8 | `portfolio_math/pyproject.toml` | No change. numpy + pandas + scipy already declared; Phase 2 added statsmodels (unrelated). MC kernel uses numpy + pandas only (no scipy.stats — Student-t is rolled via `chisquare`). |

### 5.2 Operational steps (not file edits)

§6 also contains operational steps that don't correspond to file rows:
- Step 6 (AI-excel-addin sandbox smoke test) — runs in the addin worktree; produces a separate AI-excel-addin PR with no risk_module file change. Out of scope of §5.1.
- Step 7 (live-verify end-to-end MC via Hank UI) — runtime operation against live gateway.
- Step 8 (mark Phase 3C SHIPPED in TODO.md + AGENT_SURFACE_AUDIT.md) — handled in the same risk_module PR as Steps 1-5; covered by §5.1's #3-#7 commit.

The §5.1↔§6 lock applies to file rows #1-#8 only.

---

## 6. Implementation steps (LOCKED PAIR with §5.1)

### Step 1 — `portfolio_math/monte_carlo.py` (covers §5.1 #1)

Implement (full signatures in Appendix A):

- `nearest_psd(matrix) → np.ndarray` — verbatim from today's `monte_carlo.py:52-58`.
- `build_covariance_transform(covariance) → np.ndarray` — Cholesky with PSD-repair fallback + degenerate-matrix diagonal fallback (preserves today's lines 351-383)
- `_prepare_bootstrap_history(portfolio_returns) → np.ndarray` — coercion helper, may be public-aliased as `prepare_bootstrap_history`. Verbatim from today's lines 445-457.
- `_generate_shocks(rng, distribution, num_sims, horizon, n_assets, transform, df, portfolio_returns) → tuple` — internal; preserves today's tuple shape (lines 460-536) including bootstrap fallback to normal.
- `_build_flat_result(num_sims, horizon, initial_value, **kwargs) → dict` (v5 — added per Codex R4; lives in `portfolio_math` not the engine) — verbatim move from today's lines 386-442. Builds zero-vol/empty-portfolio result dict. Used by `run_monte_carlo_from_components` when `n_assets == 0` or `transform is None`. The 14-arg keyword surface is preserved as today's. Engine imports it as a shim per Step 3.
- `compute_monthly_drift_from_components(tickers, drift_model, asset_vol_summary, portfolio_returns, expected_returns, risk_free_rate, drift_overrides, scenario_shocks, scenario_stock_betas) → tuple[np.ndarray, int]` — extracts today's `_resolve_monthly_drift` + the historical/industry_etf/risk_free/zero dispatch + drift_overrides + scenario_shocks-via-betas nonlinear math. Takes materialized `pd.Series`/`pd.DataFrame` instead of `risk_result`. Helper `_resolve_historical_monthly_drift_from_components(asset_vol_summary, portfolio_returns, tickers)` extracted from today's lines 203-243.
- `terminal_stats(paths, initial_value, percentiles=(5, 25, 50, 75, 95)) → dict` — extracts today's lines 699-734. Returns dict with `percentile_paths`, `terminal_distribution`, `histogram` keys matching today's shape.
- `simulate_paths(covariance, weights, drift, distribution, num_sims, horizon, vol_scale, df, portfolio_returns_for_bootstrap, initial_value, seed) → dict` — composes the above. Preserves today's vol_scale-on-covariance, bootstrap fallback, weight application (asset shocks → portfolio returns at line 689), path compounding (lines 692-697), terminal stats. When `n_assets == 0` or `transform is None`, delegates to `_build_flat_result` (matches today's lines 666-685).
- `run_monte_carlo_from_components(...)` — calls `compute_monthly_drift_from_components`, then `simulate_paths`, then assembles the full result dict matching today's lines 736-758 EXCEPT for the three orchestrator-only fields (`weights_overridden`, `resolved_weights`, `dropped_tickers`) and the dropped-tickers warning, which the orchestrator adds itself.

### Step 2 — Update `portfolio_math/__init__.py` (covers §5.1 #2)

Add 6 root exports per §4.1.

### Step 3 — Refactor `portfolio_risk_engine/monte_carlo.py` (covers §5.1 #3)

Three concrete edits in this file:

1. **Wrapper rewrite** of `run_monte_carlo(risk_result, ...)`:
   ```python
   def run_monte_carlo(risk_result, ...):
       # Existing setup (validate args, extract weights, resolve tickers/covariance — keep these here, they're tied to RiskAnalysisResult)
       weights_dict = _extract_weights(risk_result) if resolved_weights is None else _validate_resolved_weights(risk_result, resolved_weights)[0]
       tickers, covariance = _resolve_tickers_and_covariance(risk_result, weights_dict)
       weights_vector = _resolve_weight_vector(tickers, weights_dict)
       # Delegate to portfolio_math
       result = portfolio_math.run_monte_carlo_from_components(
           covariance=covariance, weights=weights_vector, tickers=tickers,
           asset_vol_summary=getattr(risk_result, "asset_vol_summary", None),
           portfolio_returns=getattr(risk_result, "portfolio_returns", None),
           stock_betas=getattr(risk_result, "stock_betas", None),
           ...
       )
       # Add orchestrator-only fields
       result["weights_overridden"] = bool(resolved_weights is not None)
       result["resolved_weights"] = resolved_weight_map
       result["dropped_tickers"] = sorted(dropped_tickers)
       return result
   ```

2. **Shim aliases** for the **7** private helpers so existing tests + internal callers still find them (v3 — added `_resolve_historical_monthly_drift` per Codex R2; tests at `tests/test_monte_carlo.py:8-13` import it and exercise at lines 842-907):
   ```python
   from portfolio_math.monte_carlo import (
       nearest_psd as _nearest_psd,
       build_covariance_transform as _build_correlation_transform,
       _generate_shocks,
       compute_monthly_drift_from_components,
       _build_flat_result,
       _prepare_bootstrap_history,
   )
   def _resolve_monthly_drift(risk_result, tickers, **kwargs):
       return compute_monthly_drift_from_components(
           tickers=tickers,
           asset_vol_summary=getattr(risk_result, "asset_vol_summary", None),
           portfolio_returns=getattr(risk_result, "portfolio_returns", None),
           scenario_stock_betas=kwargs.pop("scenario_stock_betas", None),
           **kwargs,
       )
   def _resolve_historical_monthly_drift(risk_result, tickers):
       """Shim — extract historical drift baseline from risk_result attributes."""
       return compute_monthly_drift_from_components(
           tickers=tickers,
           drift_model="historical",
           asset_vol_summary=getattr(risk_result, "asset_vol_summary", None),
           portfolio_returns=getattr(risk_result, "portfolio_returns", None),
       )[0]  # discard applied_override_count
   ```

   Concrete warnings re-insertion in the wrapper (v4 — copy-before-append per Codex R3 to preserve list-ownership boundary; matches today's `portfolio_risk_engine/monte_carlo.py:655-662` pattern of `result_warnings = list(distribution_metadata["warnings"])` then append):
   ```python
   result = portfolio_math.run_monte_carlo_from_components(...)
   result["weights_overridden"] = bool(resolved_weights is not None)
   result["resolved_weights"] = resolved_weight_map
   result["dropped_tickers"] = sorted(dropped_tickers)
   # COPY warnings list before mutating — preserves ownership boundary;
   # portfolio_math may return a list reference shared with internal state.
   warnings = list(result.get("warnings", []))
   if dropped_tickers:
       # IMPORTANT: do NOT sort dropped_tickers in the warning text.
       # Today's engine at portfolio_risk_engine/monte_carlo.py:657 uses
       # `', '.join(dropped_tickers)` in original (unsorted) order, even
       # though the result["dropped_tickers"] field at line 750 is sorted.
       # The asymmetry is preserved for byte-identity.
       warnings.append(
           "Dropped "
           f"{len(dropped_tickers)} ticker(s) not in covariance matrix: "
           f"{', '.join(dropped_tickers)}"
       )
   result["warnings"] = warnings
   return result
   ```

3. **Keep** the four `RiskAnalysisResult`-tied helpers in this file: `_extract_weights`, `_validate_resolved_weights`, `_resolve_tickers_and_covariance`, `_resolve_weight_vector`. These are NOT extractable — they depend on `RiskAnalysisResult` shape.

`run_monte_carlo` keeps its public signature unchanged. The shim aliases preserve `from portfolio_risk_engine.monte_carlo import _generate_shocks` etc. for any test that still uses them.

**Commit message**: `refactor(risk_engine): delegate Monte Carlo kernel to portfolio_math (Phase 3C)`

### Step 4a — Capture pre-refactor snapshot (covers §5.1 #5b)

Before Step 3's refactor lands, capture the baseline output dict:

```python
# scripts/capture_mc_snapshot.py (one-time use, can be deleted after fixture is committed)
import json, os
os.environ.setdefault("USE_DATABASE", "false")
# Use the existing 3-asset deterministic builder at tests/test_monte_carlo.py:50
# (other available deterministic builders: _build_single_asset_result:91,
#  _build_zero_vol_result:107 — pick whichever covers the most behavior.)
from tests.test_monte_carlo import _build_three_asset_result
from portfolio_risk_engine.monte_carlo import run_monte_carlo

risk_result = _build_three_asset_result()
out = run_monte_carlo(risk_result, num_simulations=100, time_horizon_months=12, seed=42)
with open("tests/fixtures/monte_carlo_snapshot.json", "w") as f:
    json.dump(out, f, indent=2, sort_keys=True)
```

The fixture file is committed alongside the refactor (Step 3 PR).

### Step 4 — Tests (covers §5.1 #4 + #5)

§5.1 #4: New `tests/portfolio_math/test_monte_carlo.py`:
- `test_nearest_psd_repairs_negative_eigenvalues`
- `test_build_covariance_transform_identity_returns_diag_sqrt`
- `test_build_covariance_transform_degenerate_matrix_falls_back_to_diagonal`
- `test_simulate_paths_deterministic_seed_normal`
- `test_simulate_paths_t_distribution_uses_df_param`
- `test_simulate_paths_bootstrap_with_short_history_falls_back_to_normal`
- `test_simulate_paths_bootstrap_full_history_samples_portfolio_returns`
- `test_simulate_paths_vol_scale_scales_covariance_not_paths`
- `test_simulate_paths_bootstrap_with_vol_scale_not_one_raises`
- `test_simulate_paths_zero_n_assets_returns_flat_result`
- `test_compute_monthly_drift_historical_uses_asset_vol_summary`
- `test_compute_monthly_drift_industry_etf_requires_expected_returns`
- `test_compute_monthly_drift_risk_free_uses_rate`
- `test_compute_monthly_drift_zero_drift_model_zeros`
- `test_compute_monthly_drift_drift_overrides_apply`
- `test_compute_monthly_drift_scenario_shocks_nonlinear_match`  ← pin AAPL 0.12 + market −0.10 × beta 1.0 = `_compound_monthly(0.02)` (matches existing test at `tests/test_monte_carlo.py:1079-1096`)
- `test_compute_monthly_drift_scenario_and_overrides_mutually_exclusive`
- `test_terminal_stats_known_terminal_values_var_cvar_match`
- `test_run_monte_carlo_from_components_end_to_end_fixed_seed`

§5.1 #5: Extend existing `tests/test_monte_carlo.py`:
- `test_run_monte_carlo_byte_identical_pre_post_refactor` — characterization snapshot. Build a synthetic `RiskAnalysisResult` via `_build_three_asset_result()` with fixed seed=42, num_simulations=100, time_horizon_months=12. Capture baseline output dict via Step 4a (committed at `tests/fixtures/monte_carlo_snapshot.json`). Assert **exact equality** of post-refactor `run_monte_carlo(...)` against the snapshot (no float tolerance — for true characterization, any drift signals a real regression). Compare via `json.dumps(out, sort_keys=True) == json.dumps(snapshot, sort_keys=True)` or equivalent stable serialization.
- All existing tests in this file (drift_overrides_apply, vol_scale_validation, bootstrap_fallback, weights_overridden, dropped_tickers, scenario_shocks, etc.) continue to pass via the import shims. Zero rewrites — verified by reading the test file's imports.

### Step 5 — Run pytest (covers §5.1 #6 + #7 + #8) — broader scope per Codex R2

Codex R2 flagged that v2's pytest scope was too narrow. v3 expands to cover the dedicated test files for each `§5.1` "no change" row:

```bash
cd /Users/henrychien/Documents/Jupyter/risk_module
pytest \
    tests/portfolio_math/test_monte_carlo.py \
    tests/test_monte_carlo.py \
    tests/test_monte_carlo_flags.py \
    tests/test_monte_carlo_result.py \
    tests/services/test_agent_building_blocks.py \
    tests/mcp_tools/test_monte_carlo_mcp.py \
    -v
```

| Test file | Verifies |
|---|---|
| `tests/portfolio_math/test_monte_carlo.py` (new — §5.1 #4) | Pure-kernel primitives |
| `tests/test_monte_carlo.py` (extended — §5.1 #5) | Engine-level behavior incl. byte-identical snapshot, dropped-tickers warning, vol_scale, scenario_shocks, drift_overrides |
| `tests/test_monte_carlo_flags.py` (existing) | Warning dedup logic — confirms warnings re-insertion from §6 Step 3 doesn't break dedup at lines 271-285 |
| `tests/test_monte_carlo_result.py` (existing — verifies §5.1 #6) | `MonteCarloResult.from_engine_output` contract at lines 67-213 |
| `tests/services/test_agent_building_blocks.py` (existing — verifies §5.1 #7) | `agent/building_blocks.run_monte_carlo` wrapper behavior at lines 277-368 + 431-506 |
| `tests/mcp_tools/test_monte_carlo_mcp.py` (existing) | MCP wrapper behavior at lines 478-537 |

§5.1 #8 (no `pyproject.toml` change) is a no-op verified by `git status` showing it untouched.

### Step 6 — AI-excel-addin sandbox smoke test (operational; cross-repo)

After Steps 1-5 ship in risk_module, on a separate AI-excel-addin PR (mirroring `PORTFOLIO_MATH_OPTIONS_AI_EXCEL_ADDIN_PLAN.md` Steps 6-7):
- Add subprocess smoke test that imports `portfolio_math` and calls `pm.simulate_paths(...)` with synthetic 2x2 covariance, fixed seed, 100 sims, 12-month horizon, equal weights, zero drift. Pin terminal mean against expected value (~initial_value, since drift=0 and large-N). Pin a specific p5/p95 against fixed-seed reproduction.
- Update system prompt to enumerate the 6 new MC primitives at root, matching Phase 3D's enumeration pattern.

### Step 7 — Live-verify end-to-end (operational)

After Step 6 merges:
- Restart gateway via services-mcp.
- Through Hank UI: ask agent to "run Monte Carlo on a small portfolio." Verify `MonteCarloResult` returns shape matching pre-refactor (compare with snapshot).
- Sandbox composition test: ask agent in chat to "compose a custom drift override and call `pm.simulate_paths` directly with it, then report VaR." Verify it executes locally without an HTTP MC call.

### Step 8 — Mark Phase 3C SHIPPED (operational; included in Step 3's PR)

In the same PR as Step 3, update:
- `docs/TODO.md` PM3 row: change Phase 3C state from `ACTIONABLE` to `SHIPPED <date>` with PR + commit refs.
- `docs/planning/AGENT_SURFACE_AUDIT.md` Phase 3C row: same.
- This plan's §11 Change log: add v3 SHIPPED entry.

---

## 7. Tests

See §6 Step 4 for the full list. Coverage rationale:

- 4 unit tests on each new primitive (covariance transform, drift resolution, simulate_paths, terminal_stats)
- 1 byte-identical characterization snapshot for the orchestrator entry
- 6 explicit edge cases that today's tests already cover (bootstrap fallback, vol_scale validation, scenario_shocks nonlinear match, mutually-exclusive overrides, zero n_assets, t-distribution df param)

Codex R1 nit: "12 tests too thin." v2 has 19 unit tests + 1 snapshot = 20. Plus all existing tests in `tests/test_monte_carlo.py` continue to validate via the import shims.

---

## 8. Rollout

- **Reversibility**: full. The shim aliases mean `_generate_shocks` etc. continue to be importable from `portfolio_risk_engine.monte_carlo`. To rollback, revert the import-shim block + restore the original function bodies (one commit). No external surface changed.
- **Ordering**: Steps 1-5 ship in one risk_module PR. Step 6 ships in a second AI-excel-addin PR after the risk_module PR merges + the package is live in the addin's environment (via `PORTFOLIO_MATH_PATH` env var per PM1A).
- **Blast radius**: HTTP `/api/agent/call → run_monte_carlo` — unchanged wire format. MCP `run_monte_carlo` tool — unaffected. New surface is additive.

---

## 9. Risks

### R1 — Floating-point determinism on snapshot regression

Same as Phase 3D's risk: future numpy/scipy upgrade may shift the snapshot. Accept.

### R2 — Orchestrator-only fields drift

`weights_overridden`, `resolved_weights`, `dropped_tickers` are added by the orchestrator after `portfolio_math.run_monte_carlo_from_components` returns. If `MonteCarloResult.from_engine_output` ever reads these from `portfolio_math`'s return directly, refactor breaks. Verified at `core/result_objects/monte_carlo.py` (Step 5 snapshot test catches it implicitly).

### R3 — Bootstrap-history coercion

`_prepare_bootstrap_history` accepts `pd.Series`/`pd.DataFrame`/None. Sandbox callers passing a raw `np.ndarray` won't hit the coercion path — they'd need to wrap in a `pd.Series`. Mitigation: `simulate_paths` documents that `portfolio_returns_for_bootstrap` must be a 1D numpy array (already-coerced); the orchestrator does the coercion. Sandbox callers are responsible for their own coercion.

### R4 — Codex R1's "API redesign" framing was correct, but bounded

Codex R1 was right: this is partial API redesign (renaming `_build_correlation_transform` → `build_covariance_transform`, restructuring vol_scale ownership in design space, splitting `_resolve_monthly_drift`'s impurity from its math, exposing `simulate_paths` as a new public surface that today's API doesn't have). v2 accepts that framing — the kernel preserves byte-identical algorithm, but the public API surface IS new (and has to be designed, not just moved).

### R5 — `compute_monthly_drift_from_components` parameter list is long (~9 args)

Acceptable. Matches `_resolve_monthly_drift`'s today's parameter list (8 args). Could be tightened later via a `DriftSpec` dataclass; punted for v1.

### R6 — Scenario-shocks `stock_betas` is `pd.DataFrame` — pandas creeps into the kernel

The scenario-shocks logic at lines 326-346 reads `scenario_stock_betas.loc[ticker_upper]` and `row.get(factor)`. To preserve byte-identity, the kernel must accept `pd.DataFrame`. Acceptable — `portfolio_math` already accepts `pd.Series`/`pd.DataFrame` in `compute_performance_metrics`. No new dep.

### R7 — `_build_flat_result` has 14 keyword args

The flat-result builder (zero-vol / empty portfolio path) is invoked at line 666 with all the bookkeeping fields. Moving it to `portfolio_math` means agents calling `simulate_paths` with empty inputs get the same flat-result shape. Wide signature is annoying but matches today's behavior. v2 accepts.

---

## 10. Live verification — to run after Step 7

| # | Check | Pass criteria |
|---|-------|---------------|
| 1 | Pre-refactor: capture `run_monte_carlo` output for fixed-seed synthetic `RiskAnalysisResult` | Snapshot saved at `tests/fixtures/monte_carlo_snapshot.json` |
| 2 | Post-refactor: same call returns byte-identical output | `assert dict_equal(result, snapshot)` passes |
| 3 | Sandbox direct call: `import portfolio_math as pm; pm.simulate_paths(cov, weights, drift, "normal", 100, 12, seed=42)` | Returns dict with `percentile_paths` (5 keys) + `terminal_distribution` (11 keys) + `histogram` |
| 4 | Sandbox composition: `pm.compute_monthly_drift_from_components(...)` → modify drift → `pm.simulate_paths(..., drift=modified)` | Returns valid stats dict |
| 5 | Hank UI end-to-end: agent runs MC on a 5-ticker portfolio | `MonteCarloResult` returns shape matching `from_engine_output` contract |
| 6 | Hank UI sandbox composition: agent does "simulate paths under custom drift, report VaR" | Agent executes pure-numpy composition without HTTP MC call |

---

## 11. Change log

- **SHIPPED end-to-end 2026-04-26** — Cross-repo Step 6 completed via AI-excel-addin PR #49 (squash `61d8dbb9`): subprocess smoke test pinning `pm.simulate_paths(seed=42, ...)` to `mean ≈ 108.631818` + system prompt enumeration adding the 6 MC primitives as a 5th category. Plan: `docs/planning/PORTFOLIO_MATH_MONTE_CARLO_AI_EXCEL_ADDIN_PLAN.md` (v2, Codex R2 PASS). Agent sandbox can now `import portfolio_math as pm`, compose `pm.simulate_paths(...)` with custom drift, intercept paths, and chain into other `portfolio_math` primitives without HTTP round-trips. Sister status updates: `AGENT_SURFACE_AUDIT.md` Phase 3C row → SHIPPED; `docs/TODO.md` PM3 row → "3D + 3C DONE end-to-end".
- **v6 (2026-04-25)** — Codex R5 FAIL fixes (2 issues, both trivial):
  - **R5 #1 (test helper name)**: Step 4a's capture script used `_build_synthetic_risk_result` which doesn't exist. v6 uses `_build_three_asset_result` from `tests/test_monte_carlo.py:50`. Comment lists the other available deterministic builders for reference.
  - **R5 #2 (snapshot equality consistency)**: §5.1 row #5 said "exact equality, no float tolerance," but Step 4 still said "deep-compare with float tolerance." v6 aligns Step 4 to exact equality via `json.dumps(..., sort_keys=True)` comparison.
- **v5 (2026-04-25)** — Codex R4 FAIL fixes (3 issues):
  - **R4 issue #1 (sort behavior change in warning)**: §6 Step 3 wrapper code restored `', '.join(dropped_tickers)` (no sort) — matches today's `portfolio_risk_engine/monte_carlo.py:657`. The asymmetry vs. `result["dropped_tickers"] = sorted(...)` at line 750 is a quirk of today's code, preserved for byte-identity. Added a comment in the wrapper.
  - **R4 issue #2 (snapshot fixture missing from §5.1)**: added §5.1 row #5b for `tests/fixtures/monte_carlo_snapshot.json`. Added §6 Step 4a (capture script) that produces the fixture.
  - **R4 issue #3 (`_build_flat_result` placement)**: §6 Step 1 now explicitly says `_build_flat_result` lives in `portfolio_math/monte_carlo.py` (verbatim move from today's lines 386-442). §6 Step 3's shim block already imports from there.
  - **R4 nit (snapshot equality semantics)**: §5.1 row #5 specifies "exact equality" (no float tolerance) for true characterization. Float drift would indicate a real regression, not a numerical edge case.
- **v4 (2026-04-25)** — Codex R3 FAIL fixes (1 blocker + 2 nits, all tightening):
  - **R3 blocker (warnings list mutation)**: §6 Step 3 wrapper code now copies `result["warnings"]` to a local list before append, then re-assigns. Matches today's `portfolio_risk_engine/monte_carlo.py:655-662` pattern (`result_warnings = list(distribution_metadata["warnings"])`). Prevents accidental shared-state mutation if `portfolio_math` returns a list reference.
  - **R3 nit (helper count)**: §5.1 row 3 "6 private helpers" → "7" (matches §6 Step 3's actual 7-helper shim block after `_resolve_historical_monthly_drift` was added in v3).
  - R3 non-blocking confirmations carried forward: shim correctness OK, §5↔§6 lock OK, pytest scope OK.
- **v3 (2026-04-25)** — v2 + Codex R2 fixes (3 blockers all resolved):
  - **R2 blocker #1 (orchestrator-owned warning)**: §4.7 now adds the `dropped_tickers` warning insertion as a 4th orchestrator field. §6 Step 3 shows concrete code. Preserves test pin at `tests/test_monte_carlo.py:643-655` + dedup contract at `tests/test_monte_carlo_flags.py:271-285`.
  - **R2 blocker #2 (shim list completeness)**: §6 Step 3 adds `_resolve_historical_monthly_drift` to the shim block (tests at `tests/test_monte_carlo.py:8-13` import it directly).
  - **R2 blocker #3 (verification scope)**: §6 Step 5 expanded pytest invocation to include `tests/test_monte_carlo_result.py` (verifies §5.1 #6), `tests/services/test_agent_building_blocks.py` (verifies §5.1 #7), `tests/mcp_tools/test_monte_carlo_mcp.py` (additional consumer), and `tests/test_monte_carlo_flags.py` (warning dedup contract).
  - §3.8 corrected: `agent/building_blocks.run_monte_carlo` actually uses `_load_portfolio_for_analysis` + `enrich_portfolio_factor_proxies` + `PortfolioService.analyze_portfolio` + optional `expand_risk_result_for_tickers`, not the (incorrect) `get_risk_analysis` + `MonteCarloResult.from_engine_output` chain v2 described. Fact-check confirmed by reading `agent/building_blocks.py:523-547`.
  - Effort estimate revised 3-5 → 4-6 days. Codex R2 said 4-6 minimum, possibly 5-7 if first pass shakes out result-shape regressions. Adopted 4-6 with the understanding that R6 risk (PSD repair edge cases) could push higher.
- **v2 (2026-04-25)** — Full rewrite after Codex R1 FAIL. Key corrections:
  - Boundary characterization fixed: `monte_carlo.py` is **already pure-on-materialized-inputs**; the impurity is in callers (`agent/building_blocks.run_monte_carlo` materializes `RiskAnalysisResult`). v1's purity table at §3.1 was wrong.
  - API design ground in two-tier model: low-level `simulate_paths` (composition unlock) + high-level `run_monte_carlo_from_components` (mirrors today's behavior). v1 conflated these.
  - vol_scale stays on covariance — preserves today's behavior. v1 proposed moving to accumulation, which Codex correctly flagged as a behavior change.
  - Bootstrap fallback (history < 12 months → normal with warning) explicitly retained in the kernel — v1 said "raise ValueError," wrong.
  - Drift-override math is **nonlinear**: monthly→annual→add stress→re-compound. v1 sketched it as linear; test pin at `tests/test_monte_carlo.py:1079-1096` pins the nonlinear behavior.
  - Test path corrected from `tests/portfolio_risk_engine/test_monte_carlo.py` (doesn't exist) to `tests/test_monte_carlo.py`.
  - §5↔§6 lock fixed: §5.1 row 6 (`MonteCarloResult`) and row 7 (`agent/building_blocks.py`) are explicitly "no change" rows that Step 5 verifies via the snapshot test (no orphan rows).
  - Result-shape understatement fixed: today's dict has 5 percentile keys (5/25/50/75/95) + 11 terminal_distribution fields + histogram + scenario_conditioning + 8 metadata fields. §3.5 enumerates.
  - Effort estimate moved from 2-4 days (v1 optimistic) to 3-5 days. Codex R1 said 5-7; truth is in between because the algorithm is preserved but the public surface IS new.
- **v1 (2026-04-24)** — Initial draft. Codex R1 FAILED with 7 blockers (boundary characterization wrong, API not composable as written, vol_scale semantics wrong, bootstrap handling wrong, drift override oversimplified, §5↔§6 broken, effort estimate too optimistic). Lost research depth. v2 grounded in end-to-end engine read.

---

## Appendix A — Primitives signature sketch

```python
# portfolio_math/monte_carlo.py

import math
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

_MIN_BOOTSTRAP_MONTHS = 12  # matches portfolio_risk_engine/monte_carlo.py:17
_SUPPORTED_DISTRIBUTIONS = {"normal", "t", "bootstrap"}
_SUPPORTED_DRIFT_MODELS = {"historical", "industry_etf", "risk_free", "zero"}


def nearest_psd(matrix: np.ndarray, epsilon: float = 1e-10) -> np.ndarray:
    """Project a symmetric matrix onto the PSD cone via eigenvalue clamping."""
    # Verbatim from monte_carlo.py:52-58


def build_covariance_transform(covariance: np.ndarray) -> np.ndarray:
    """Cholesky factor of covariance with PSD-repair fallback + degenerate-matrix
    diagonal fallback. Verbatim from monte_carlo.py:351-383 (renamed from
    _build_correlation_transform; the input has always been covariance)."""


def compute_monthly_drift_from_components(
    tickers: List[str],
    drift_model: str = "historical",
    asset_vol_summary: Optional[pd.DataFrame] = None,    # for "historical"
    portfolio_returns: Optional[pd.Series] = None,        # for "historical" baseline
    expected_returns: Optional[Dict[str, float]] = None,  # for "industry_etf"
    risk_free_rate: Optional[float] = None,                # for "risk_free"
    drift_overrides: Optional[Dict[str, float]] = None,
    scenario_shocks: Optional[Dict[str, float]] = None,
    scenario_stock_betas: Optional[pd.DataFrame] = None,
) -> Tuple[np.ndarray, int]:
    """Resolve per-ticker monthly drift array.
    Returns (drift, applied_override_count). Preserves all 4 drift_models +
    drift_overrides + scenario_shocks nonlinear monthly↔annual round-tripping
    from monte_carlo.py:246-348."""


def terminal_stats(
    paths: np.ndarray,                          # shape (sims, months+1)
    initial_value: float,
    percentile_levels: List[int] = [5, 25, 50, 75, 95],
    histogram_bins: int = 30,
) -> Dict[str, Any]:
    """Compute percentile_paths + terminal_distribution + histogram dict.
    Verbatim from monte_carlo.py:699-734."""


def simulate_paths(
    covariance: np.ndarray,
    weights: np.ndarray,                        # shape (n_assets,)
    drift: np.ndarray,                          # shape (n_assets,) — per-asset monthly drift
    distribution: str = "normal",
    num_simulations: int = 1000,
    time_horizon_months: int = 12,
    vol_scale: float = 1.0,
    df: int = 5,
    portfolio_returns_for_bootstrap: Optional[np.ndarray] = None,
    initial_value: float = 1.0,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Pure simulation with pre-resolved inputs. The composition unlock.

    - Validates: vol_scale > 0; bootstrap requires vol_scale==1.0
    - Scales covariance: scaled = covariance * vol_scale**2
    - Builds Cholesky transform via build_covariance_transform
    - Generates shocks (normal/t/bootstrap with fallback to normal on insufficient history)
    - Applies weights: monthly_portfolio_returns = monthly_asset_returns @ weights
    - Compounds paths from initial_value
    - Returns dict with percentile_paths + terminal_distribution + histogram + metadata.
    """


def run_monte_carlo_from_components(
    covariance: np.ndarray,
    weights: np.ndarray,
    tickers: List[str],
    asset_vol_summary: Optional[pd.DataFrame] = None,
    portfolio_returns: Optional[pd.Series] = None,
    stock_betas: Optional[pd.DataFrame] = None,
    drift_model: str = "historical",
    expected_returns: Optional[Dict[str, float]] = None,
    risk_free_rate: Optional[float] = None,
    drift_overrides: Optional[Dict[str, float]] = None,
    scenario_shocks: Optional[Dict[str, float]] = None,
    num_simulations: int = 1000,
    time_horizon_months: int = 12,
    distribution: str = "normal",
    df: int = 5,
    vol_scale: float = 1.0,
    portfolio_value: Optional[float] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """High-level wrapper: resolves drift via compute_monthly_drift_from_components,
    then calls simulate_paths. Mirrors today's run_monte_carlo behavior modulo the
    three orchestrator-only fields (weights_overridden, resolved_weights,
    dropped_tickers) which the orchestrator adds after this returns."""
```
