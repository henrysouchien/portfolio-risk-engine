# Building Blocks Internal Delegate — Phase 3B Plan

**Parent plan**: `AGENT_SURFACE_AUDIT.md` (Phase 3 scoping, Option B)
**Predecessor**: `PORTFOLIO_MATH_EXTRACTION_PLAN.md` (Phase 2, SHIPPED) and PM1A
**Status**: **SHIPPED 2026-04-21** — Codex PASS after R1-R3, landed at `afe4fe93`

## Ship log

| Commit | Summary |
|---|---|
| `aae7e7d0` | Plan doc (approved v3) |
| `afe4fe93` | Implementation — `agent/building_blocks.py` delegates to `portfolio_math.compute_correlation_matrix` + `compute_performance_metrics`; `DATA_QUALITY_THRESHOLDS["min_observations_for_capm_regression"]` sourced explicitly (not inlined); new regression test in `tests/services/test_agent_building_blocks.py` distinguishes override from hardcoded default |

Return shapes preserved byte-identically via `.to_legacy_dict()`. 35 of 36 building_blocks tests pass + the 1 pre-existing registry-count drift (confirmed pre-existing via stash/unstash). 41 portfolio_math + legacy wrapper tests green. Registry / risk_client / tool surface tests untouched.

---
**Date**: 2026-04-20

---

## 1. Goal

Wire `agent/building_blocks.compute_metrics` and `get_correlation_matrix` to delegate directly to `portfolio_math` (not via the legacy `portfolio_risk_engine` wrapper chain). Zero agent-facing change: return shapes, registry surface, risk_client methods all preserved. Internal coupling cleanup only.

This is Phase 3 Option B — the smaller, non-breaking slice from the 3-phase agent surface roadmap. Phase 3 Option A (remove these functions entirely from the registry) is explicitly NOT this plan.

---

## 2. Current state (verified by source read)

**`building_blocks.compute_metrics` (line 382)**:
- Imports `compute_performance_metrics` from `portfolio_risk_engine.performance_metrics_engine` — the legacy wrapper that internally calls `portfolio_math.compute_performance_metrics` and returns the legacy dict via `.to_legacy_dict()`.
- Does its own HTTP work (fetches benchmark prices via `get_price_provider().fetch_monthly_close`).
- Returns `{"status": "success", "metrics": <dict>}` (the dict is the legacy-shape output).

**`building_blocks.get_correlation_matrix` (line 350)**:
- Calls `returns_df.corr()` (pandas) directly.
- Does its own HTTP work (fetches returns via `get_returns_dataframe`).
- Returns `{"status": "success", "correlation_matrix": ..., "tickers": ..., ...}`.

Neither currently depends on `portfolio_math` directly.

---

## 3. Target state

**`compute_metrics`**:
- Import `compute_performance_metrics` from `portfolio_math` (not `portfolio_risk_engine`).
- Call it, then `.to_legacy_dict()` on the returned `PerformanceMetrics` dataclass to produce the legacy dict shape.
- Result-embedding behavior (`{"status": "success", "metrics": ...}`) and `make_json_safe` wrapping preserved.

**`get_correlation_matrix`**:
- Import `compute_correlation_matrix` from `portfolio_math`.
- Replace `matrix = returns_df.corr()` with `matrix = compute_correlation_matrix(returns_df)`.
- Returns `pd.DataFrame` (same as `.corr()`), downstream `.to_dict()` + `make_json_safe` unchanged.

HTTP fetch paths unchanged; preamble, registry, risk_client wrappers all unchanged.

---

## 4. Design decisions

### D1: Call `to_legacy_dict()`, not `dataclasses.asdict()`

`portfolio_math.compute_performance_metrics` returns a `PerformanceMetrics` dataclass. Codex R1 on Phase 2 was explicit: blind `asdict()` breaks nested-shape callers. `to_legacy_dict()` is the field-by-field adapter that produces byte-identical legacy output — same path the `portfolio_risk_engine` legacy wrapper uses today.

### D2: Keep the existing dict envelope `{"status": "success", "metrics": ...}`

`building_blocks.compute_metrics` today returns `{"status": "success", "metrics": <legacy dict>}`. This envelope is what the agent registry + risk_client expect. Do NOT change it. The legacy dict produced by `to_legacy_dict()` goes inside the `metrics` key, matching today's structure exactly.

### D3: Keep `make_json_safe` wrapping

Both functions wrap their output in `make_json_safe(...)` today. Preserve that wrapping — numpy scalar / pandas Timestamp coercion for HTTP serialization is load-bearing (F36 pattern).

### D4: No registry change, no risk_client change

The registered function names + signatures + return shapes are unchanged. `rc.compute_metrics(...)` and `rc.get_correlation_matrix(...)` keep working with identical behavior. Drift test on `risk_client/__init__.py` should remain green (no regeneration needed since registered function signatures don't change).

### D5: Add one regression test for threshold propagation (Codex R1 requirement)

Existing building_blocks tests at `tests/services/test_agent_building_blocks.py:192` only check the happy path and one nested key — they would NOT catch a config-override regression. Add one new test that DISTINGUISHES the override from the default (Codex R2 correction: "CAPM=None below threshold" alone doesn't distinguish a hardcoded `12` from the real override).

Test design — use observation count that sits **between** the override and the default:

- Monkeypatch `DATA_QUALITY_THRESHOLDS["min_observations_for_capm_regression"] = 6` (BELOW the default of 12)
- Call `building_blocks.compute_metrics(...)` with a returns_dict of exactly **10 observations** (between 6 and 12)
- Assert CAPM fields (`beta`, `alpha_annual`, `r_squared`) are NON-None / present
- Rationale: a buggy impl hardcoding `12` would reject 10 observations → CAPM=None → test fails. Only a correct impl reading the overridden threshold of 6 would accept 10 observations → CAPM populated → test passes.

Alternative/complementary: assert the warnings list content reflects the overridden required count (if the warning message mentions the threshold value). Pick whichever is cleanest given the actual warning string format.

**Test fixture gotcha** (Codex R3 note): to get 10 benchmark return observations, stub the benchmark price series with **11** monthly closes — `calc_monthly_returns()` uses `pct_change().dropna()` at `portfolio_risk_engine/factor_utils.py:58`, which drops the first row. Use 11 closes for both portfolio returns and benchmark fixture.

All other existing tests (correlation, compute_metrics happy path) should pass unchanged — return shape is preserved byte-identically by `to_legacy_dict()`.

---

## 5. Scope

### In scope
- `agent/building_blocks.py` lines 350-378 (get_correlation_matrix) and 381-416 (compute_metrics)
- Import line changes at the top of the file
- Verify `tests/services/test_agent_building_blocks.py` still passes

### Out of scope
- Removing these functions from the registry (Option A — separate plan)
- Changing return shapes to dataclass (breaking change)
- Touching any other building_blocks function
- Any changes to portfolio_math, risk_client, registry, routes
- Risk_client regeneration (registered signatures don't change)

---

## 6. Implementation — single commit

**File changes in `agent/building_blocks.py`**:

1. Imports (top of file):
   - Remove or keep `from portfolio_risk_engine.performance_metrics_engine import compute_performance_metrics` (leave if still used elsewhere in the file — verify via grep; remove only if this was the only site)
   - Add `from portfolio_math import compute_correlation_matrix, compute_performance_metrics`

2. `get_correlation_matrix` body:
   - Replace `matrix = returns_df.corr()` with `matrix = compute_correlation_matrix(returns_df)`

3. `compute_metrics` body:
   - Import (alongside the existing imports): `from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS`
   - At the call site, replace:
     ```python
     metrics = compute_performance_metrics(
         portfolio_returns=aligned["portfolio"],
         benchmark_returns=aligned["benchmark"],
         risk_free_rate=float(risk_free_rate),
         benchmark_ticker=benchmark_ticker,
         start_date=aligned.index.min().date().isoformat(),
         end_date=aligned.index.max().date().isoformat(),
     )
     return {"status": "success", "metrics": make_json_safe(metrics)}
     ```
     with:
     ```python
     result = compute_performance_metrics(
         portfolio_returns=aligned["portfolio"],
         benchmark_returns=aligned["benchmark"],
         risk_free_rate=float(risk_free_rate),
         benchmark_ticker=benchmark_ticker,
         start_date=aligned.index.min().date().isoformat(),
         end_date=aligned.index.max().date().isoformat(),
         min_capm_observations=DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 12),
     )
     return {"status": "success", "metrics": make_json_safe(result.to_legacy_dict())}
     ```
   - **CRITICAL** (Codex R1 blocker fix): `min_observations_for_capm_regression` MUST be sourced from `DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 12)` — the same dict the legacy wrapper reads at `performance_metrics_engine.py:71`. Do NOT inline a literal (e.g., `12`). Doing so would break config-override behavior that `tests/core/test_performance_metrics_engine.py:67` asserts. Any literal inline = a real behavior change whenever settings override the threshold.
   - Rationale per Codex R1: do NOT add a default constant to `portfolio_math` itself. That package stays pure/policy-free; the threshold is config/policy, not math. Read the config in `building_blocks.py` directly.

**Verification**:
- `pytest tests/services/test_agent_building_blocks.py` green
- `pytest tests/test_risk_client.py tests/test_risk_client_contract.py tests/test_risk_client_generator_sync.py tests/test_tool_surface_sync.py` green (no registry/client changes)
- `pytest tests/test_portfolio_math_*.py` green (no portfolio_math changes)
- Full suite: no new failures beyond the 34-36 baseline

**Estimate**: ~half day (actual code change is minutes; verification is the bulk).

---

## 7. Risks

1. **Config-override regression for `min_observations_for_capm_regression`** (upgraded from "default drift" per Codex R1): today `building_blocks.compute_metrics` goes through the legacy wrapper which reads `DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 12)` — so settings overrides flow through automatically. After B, `building_blocks.py` must read that dict explicitly when invoking `portfolio_math.compute_performance_metrics`. **Inlining a literal (e.g. `12`) would silently break config-override behavior** that `tests/core/test_performance_metrics_engine.py:67` depends on. **Mitigation**: read `DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 12)` at the building_blocks call site (per §6). Add a regression test per D5 that monkeypatches the threshold and asserts it's honored end-to-end at the building_blocks layer.

2. **Return-shape drift**: `to_legacy_dict()` is supposed to produce byte-identical output. Phase 2 verified this for the legacy wrapper call path. The portfolio_math→dataclass→to_legacy_dict path IS the legacy wrapper's internal implementation — so using it directly should produce the same output. **Mitigation**: existing tests assert on return keys; if they pass unchanged, shape is preserved.

3. **Stale `compute_performance_metrics` import**: if the existing `from portfolio_risk_engine.performance_metrics_engine import compute_performance_metrics` is still needed elsewhere in `building_blocks.py`, a simple import removal breaks those sites. **Mitigation**: grep before editing. If still needed, alias the portfolio_math import (e.g., `from portfolio_math import compute_performance_metrics as _pm_compute_metrics`) to avoid the name collision.

4. **Test coverage gaps**: if no existing test exercises `building_blocks.compute_metrics` / `get_correlation_matrix` end-to-end with real output comparison, silent drift could slip through. **Mitigation**: `tests/services/test_agent_building_blocks.py` exercises both (confirmed via grep during Phase 3 scoping). Ensure those tests pass.

---

## 8. Open questions

Both resolved by Codex R1:

1. **Leave the legacy wrapper alone**: `services/performance_helpers.py:1116` + multiple `portfolio_risk_engine` / `mcp_tools` paths still call the wrapper. Verified live callers exist. This plan ONLY touches `building_blocks.py`.

2. **Commit subject**: Codex R1 recommends behavior-first: `refactor(building_blocks): call portfolio_math directly`. Put "Phase 3B" in the PR body / commit trailing reference, not the subject.

---

## 9. Success criteria

- [ ] `agent/building_blocks.py` imports `compute_correlation_matrix` and `compute_performance_metrics` from `portfolio_math`
- [ ] `get_correlation_matrix` uses `portfolio_math.compute_correlation_matrix(returns_df)` instead of `returns_df.corr()`
- [ ] `compute_metrics` calls `portfolio_math.compute_performance_metrics(...)` directly and converts via `.to_legacy_dict()`
- [ ] `min_observations_for_capm_regression` sourced from `DATA_QUALITY_THRESHOLDS.get("min_observations_for_capm_regression", 12)` — NOT a literal inline
- [ ] New regression test in `tests/services/test_agent_building_blocks.py` monkeypatches the threshold and asserts it's honored at the building_blocks layer
- [ ] All existing tests green (building_blocks, risk_client, portfolio_math, tool surface sync)
- [ ] Full suite within 34-36 pre-existing baseline, zero new failures
- [ ] Single commit in risk_module
- [ ] Zero changes to registry, risk_client, routes, or portfolio_math itself
