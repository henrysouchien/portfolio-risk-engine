# F36 Fix — `run_whatif` HTTP serialization hardening

## Context

Smoke-testing `risk_client` v0.2.0 (2026-04-17) surfaced F36: `POST /api/agent/call` with `run_whatif` + `format="agent"` returns raw `text/plain` 500 (no JSON envelope). Every other tool's agent format works, and direct Python calls succeed — so the failure is HTTP-path-only.

**Root cause** (confirmed by tracing + Codex runtime verification in R1):

1. In production `self.volatility_delta`, `self.concentration_delta` are `np.float64` (pandas/numpy aggregations upstream).
2. `core/result_objects/whatif.py:355-356` captures `raw_vol_delta_pct = self.volatility_delta * 100` and `raw_conc_delta = self.concentration_delta` — still numpy.
3. Line 358: `is_marginal = abs(raw_vol_delta_pct) < 0.1 and abs(raw_conc_delta) < 0.001` → `np.bool_`.
4. Snapshot dict (lines 380-428) stores `is_marginal` (and `_raw_vol_delta_pct`, `_raw_conc_delta`).
5. `mcp_tools/whatif.py:37` strips `_`-prefixed keys but `is_marginal` survives.
6. `routes/agent_api.py:92-103` returns the dict; FastAPI's `jsonable_encoder` rejects `np.bool_` → unhandled `TypeError` → text/plain 500.

**Adjacent gaps** (surfaced across review rounds):

- `run_whatif(format="summary")` at `mcp_tools/whatif.py:182-190` returns `result.get_summary()` + `result.get_factor_exposures_comparison()`, both unwrapped. `get_summary()` leaks `np.float64` (`round(np.float64, 4)` stays `np.float64`). `get_factor_exposures_comparison()` can emit raw NaN from `portfolio_factor_betas.to_dict()`. Same HTTP-serialization bug class.
- The agent-snapshot top-3 factor sort at `core/result_objects/whatif.py:341-345` sorts by `abs(delta)`. Raw NaN deltas + set-union source order (line 438) produce non-deterministic top-3 selection. Separate computational correctness bug, orthogonal to JSON safety.

**Why it slipped through**: `tests/core/test_whatif_agent_snapshot.py` uses `SimpleNamespace` with native Python floats; `tests/mcp_tools/test_whatif_agent_format.py` stubs `get_agent_snapshot()`. Neither exercises numpy-scalar or NaN-bearing pandas Series paths.

**Precedent**: peer result objects wrap their producer-side output via `make_json_safe(...)` before returning — `risk.py:287`, `performance.py:294`, `backtest.py:70/115/151`, `monte_carlo.py:72/107/150`, `rebalance.py:28/77/91`, `basket.py:107/120/155`, `basket_trading.py:28/93/111/131/187/199`, `realized_performance.py:624`. Not universal (`optimization.py:335` returns raw; not currently leaking per Codex R1 runtime check — out of scope here). `whatif.py:11` imports `make_json_safe` but never calls it — the defect is a single missing convention call.

## Recommended approach (R5)

**All JSON-safety wraps at the result object.** The codebase convention is producer-side wrapping; `WhatIfResult` is the one outlier that drifted. The fix restores the convention across all three of its HTTP-facing methods. Zero wraps at the MCP tool layer — `mcp_tools/whatif.py` goes back to trusting the producer, matching every other tool.

The finite-first sort helper (introduced below) is what makes producer-side wrapping of `get_factor_exposures_comparison()` safe. Codex R2 originally flagged this path as regressive because the internal consumer's `sorted(..., key=lambda ...: abs(item["delta"]))` would hit `abs(None)` after wrapping. The new `_delta_rank` helper short-circuits `None`/non-numeric/non-finite inputs into a deterministic "last" bucket via `try: float(delta) except TypeError/ValueError`, so the internal consumer tolerates the wrapped output.

## Files to modify

### 1. `core/result_objects/whatif.py` (three producer wraps + finite-first sort)

All changes confined to this file. `make_json_safe` already imported at line 11. `math` already imported at line 5. No new imports.

- **`get_agent_snapshot()` line 430**: `return snapshot` → `return make_json_safe(snapshot)`.
- **`get_summary()` line 218-237**: wrap returned dict via `make_json_safe(...)`. Load-bearing, not defensive: `round(np.float64(...), 4)` keeps the value as `np.float64`.
- **`get_factor_exposures_comparison()` line 432-449**: wrap returned `comparison` dict via `make_json_safe(...)`. Maps NaN factor betas → `None`.
- **`get_agent_snapshot()` line 342-345 — finite-first sort key**: replace the existing lambda with a named helper:

  ```python
  def _delta_rank(item):
      delta = item[1].get("delta", 0)
      try:
          delta_f = float(delta)
      except (TypeError, ValueError):
          return (1, 0.0, item[0])  # non-numeric / None → last
      if not math.isfinite(delta_f):
          return (1, 0.0, item[0])  # NaN / ±Inf → last
      return (0, -abs(delta_f), item[0])  # finite → ranked by |delta| desc, alpha tiebreak
  sorted_factors = sorted(factor_comparison.items(), key=_delta_rank)
  ```

  This makes the top-3 selection deterministic regardless of NaN/None/Inf in `delta`. It also makes producer-side wrapping of `get_factor_exposures_comparison()` safe for the internal consumer.

### 2. `mcp_tools/whatif.py`

**No changes.** Previously considered: a callsite wrap at line 185. Dropped in R5 — the producer now guarantees JSON-safety, same as every other tool.

### 3. Regression tests (`tests/core/test_whatif_agent_snapshot.py`)

Two new tests using the existing `_make_metrics` + `WhatIfResult(...)` pattern in that file.

**Test A — numpy-scalar agent snapshot (the F36 repro)**:
- Build `WhatIfResult` with `volatility_annual=np.float64(0.20)`, `herfindahl=np.float64(0.10)`, `factor_pct=np.float64(0.70)`.
- Assert `json.dumps(result.get_agent_snapshot(), allow_nan=False)` succeeds.
- Assert `type(snapshot["is_marginal"]) is bool`.
- Assert `snapshot["risk_deltas"]["volatility_annual_pct"]["delta"]` is native `float`/`int`, not numpy scalar.

**Test B — NaN-bearing factor betas + deterministic finite-first ranking**:
- Build `WhatIfResult` with **five** factors so there's a real top-3 selection. Deltas = `{MKT: -0.3, VALUE: nan, SIZE: -0.1, MOMENTUM: -0.5, QUALITY: -0.05}` (via a NaN in `scenario_metrics.portfolio_factor_betas`).
- Assert `json.dumps(result.get_summary(), allow_nan=False)` succeeds.
- Assert `json.dumps(result.get_factor_exposures_comparison(), allow_nan=False)` succeeds.
- Assert `json.dumps(result.get_agent_snapshot(), allow_nan=False)` succeeds.
- Assert `result.get_factor_exposures_comparison()["VALUE"]["delta"] is None` (producer wrap normalized NaN).
- Assert `list(snapshot["top_factor_deltas"].keys()) == ["MOMENTUM", "MKT", "SIZE"]` (finite-first sort demoted VALUE despite its NaN delta).

All assertions use `allow_nan=False` for strict JSON validation.

### 4. `docs/TODO.md`

- Flip F36 row from `ROOT-CAUSED` to `CLOSED (commit <sha>)`. Note that summary-mode NaN hardening + deterministic factor sort were included in the same fix.

## Out of scope

- **`optimization.py:335`** (unwrapped `OptimizationResult.get_agent_snapshot`): different result object, not currently leaking per Codex R1 runtime check.
- **Agent API route error envelope**: FastAPI returning `text/plain` 500 on unhandled `TypeError` is default behavior; JSON-envelope-on-error is a cross-cutting concern.
- **`WhatIfResult.to_api_response()`**: already serializes cleanly via internal `_convert_to_json_serializable` / `_clean_nan_values` (verified by Codex R1). The producer wrap on `get_factor_exposures_comparison()` means `to_api_response` now receives pre-sanitized comparison data, which is a harmless no-op relative to its existing `_clean_nan_values` pass.
- **Lint/structural enforcement of the wrap convention**: worth a follow-up (a test that introspects every `get_agent_snapshot()` with real fixtures and asserts strict JSON), but larger-scope than F36.

## Verification

1. **Unit tests** (added): `pytest tests/core/test_whatif_agent_snapshot.py -v` — two new tests pass; existing tests unchanged.
2. **MCP tool test**: `pytest tests/mcp_tools/test_whatif_agent_format.py -v` — unchanged, still passes.
3. **Live HTTP — agent mode** (the F36 repro):
   ```bash
   curl -sS -X POST http://localhost:5001/api/agent/call \
     -H "Authorization: Bearer $AGENT_API_KEY" \
     -H 'Content-Type: application/json' \
     -d '{"function":"run_whatif","params":{"portfolio_name":"CURRENT_PORTFOLIO","delta_changes":{"AAPL":0.01},"format":"agent"}}' \
     | python3 -m json.tool
   ```
   Before: 500 text/plain. After: 200 with `{"ok":true,"result":{"status":"success","format":"agent","snapshot":{...},"flags":[...]}}`.
4. **Live HTTP — summary mode**:
   ```bash
   curl -sS -X POST http://localhost:5001/api/agent/call \
     -H "Authorization: Bearer $AGENT_API_KEY" \
     -H 'Content-Type: application/json' \
     -d '{"function":"run_whatif","params":{"portfolio_name":"CURRENT_PORTFOLIO","delta_changes":{"AAPL":0.01},"format":"summary"}}' \
     | python3 -c 'import sys,json; json.loads(sys.stdin.read(), parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"non-strict JSON token: {s}"))); print("strict JSON OK")'
   ```
   After: `strict JSON OK`.
5. **risk_client smoke**: re-run the P1.4 overload smoke test that discovered F36 (commit `8b507cdc`) and confirm it passes.

## Risk / blast radius

- **Scope**: three producer-side return wraps + one sort helper (all in `core/result_objects/whatif.py`) + two new regression tests. Zero changes outside the result object.
- **Semantic delta**: NaN/Inf → None in HTTP-serialized numeric outputs; strictly better than today (either crashes at `jsonable_encoder` or escapes as non-strict JSON).
- **Performance**: snapshot is ≤~30 fields; recursive copy is negligible.
- **Rollback**: revert the whatif.py edits and the test block.

## Commit plan

Single commit: `fix(whatif): json-safe producer outputs + deterministic factor sort (F36)` — three producer wraps, one sort helper, two regression tests, TODO update. All in `core/result_objects/whatif.py` + one test file + one TODO line.

## Codex review status

- **R1**: FAIL — peer-audit overstatement + summary-mode NaN not scoped. Addressed.
- **R2**: FAIL — producer-side wrap of `get_factor_exposures_comparison` would regress the agent-snapshot sort; tests used non-strict `json.dumps`. Both addressed.
- **R3**: FAIL — NaN deltas produced non-deterministic top-3. Addressed with finite-first sort.
- **R4**: PASS (with non-blocking notes on `pd.NA` at the raw-beta layer and `round(np.float64)` staying numpy). Plan shape: 2 producer wraps + 1 callsite wrap.
- **R5** (this revision): consolidated to 3 producer wraps + 0 callsite wraps; the finite-first sort from R4 makes producer-side wrapping of `get_factor_exposures_comparison` safe. All JSON-safety now lives at the result object, matching the codebase convention end-to-end. Pending Codex re-review.
