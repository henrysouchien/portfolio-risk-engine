# Scenario Tool Decomposition v1

## Context

The `run_whatif()`, `run_optimization()`, and `run_backtest()` MCP tools are the workhorses of the Scenario Workflows vision but are too monolithic for composable agent use. Specifically:

1. **Agent snapshots don't expose resolved weights** — an agent can't extract "what weights did this analysis use?" from any tool's output, blocking tool-to-tool chaining (e.g., optimize → backtest the result).
2. **Backtest lacks delta mode** — `run_whatif()` accepts `delta_changes` ("+5%", "-200bp") but `run_backtest()` only accepts absolute weights, forcing the agent to manually resolve deltas before backtesting.

This plan adds `resolved_weights` to all three agent snapshots and `delta_changes` support to `run_backtest()`. Additive only — no breaking changes.

---

## Step 1: Add `resolved_weights` to BacktestResult snapshot

**File:** `core/result_objects/backtest.py`

In `get_agent_snapshot()` (line 101-127), add `resolved_weights` to the dict inside `make_json_safe()`, after `"warnings"`:

```python
"resolved_weights": self.weights,
```

`self.weights` is already `Dict[str, float]` in decimal form (line 22). `make_json_safe()` handles serialization.

---

## Step 2: Add `resolved_weights` to OptimizationResult snapshot

**File:** `core/result_objects/optimization.py`

In `get_agent_snapshot()` (line 302-326), add after `"weight_changes"` (line 320):

```python
"resolved_weights": {k: round(v, 6) for k, v in self.optimized_weights.items()},
```

Uses `self.optimized_weights` directly (line 84) — the full optimized allocation including near-zero positions. This is intentional: for chaining purposes (e.g., optimize → backtest), the agent needs the exact allocation the optimizer produced, not the presentation-filtered `active_positions` (which drops `abs(weight) <= 0.001`). Dropping dust would silently change the portfolio an agent chains into backtest.

**Codex R1 fix:** Original plan used `active_positions` which filters dust — changed to `self.optimized_weights` for chaining fidelity.

---

## Step 3: Add `resolved_weights` to WhatIfResult snapshot

**File:** `core/result_objects/whatif.py`

In `get_agent_snapshot()` (line 308-347), add after `"top_factor_deltas"` (line 344):

```python
"resolved_weights": getattr(self.scenario_metrics, "portfolio_weights", None) or {},
```

Same access pattern already used at line 250 for position changes. Safe: `getattr` with fallback. Key does NOT start with `_` so it passes through `_build_agent_response`'s stripping (mcp_tools/whatif.py:36).

---

## Step 4: Add `delta_changes` to `run_backtest()` MCP tool

**File:** `mcp_tools/backtest.py`

1. **Add import** at top:
   ```python
   from utils.helpers_input import parse_delta
   ```

2. **Add parameter** to `run_backtest()` signature (after `weights`):
   ```python
   delta_changes: Optional[dict] = None,
   ```

3. **Add mutual exclusion validation** (after line 146, before weight resolution):
   ```python
   if weights and delta_changes:
       return {"status": "error", "error": "Provide only one of weights or delta_changes, not both."}
   ```

4. **Add delta resolution** (replace the simple `backtest_weights = weights or ...` at line 148):
   ```python
   if delta_changes and not weights:
       base_weights = portfolio_data.get_weights()
       if not base_weights:
           return {"status": "error", "error": "delta_changes requires a portfolio with existing weights as baseline."}
       # Normalize delta ticker keys to uppercase before parsing (base_weights keys
       # are already uppercase from portfolio_data). This prevents duplicate keys
       # when delta_changes uses "aapl" vs base_weights having "AAPL".
       normalized_deltas = {
           str(k or "").strip().upper(): v
           for k, v in delta_changes.items()
           if str(k or "").strip()
       }
       delta_dict, _ = parse_delta(literal_shift=normalized_deltas)
       resolved = dict(base_weights)
       for ticker, delta_value in delta_dict.items():
           resolved[ticker] = resolved.get(ticker, 0.0) + delta_value
       backtest_weights = resolved
   else:
       backtest_weights = weights or portfolio_data.get_weights()
   ```

   The resolved weights are NOT explicitly normalized here. This is intentional and matches the existing flow: the downstream normalization loop (lines 149-159) already uppercases and float-casts each weight, and the backtest engine applies `normalize_weights()` at `backtest_engine.py:124` (which respects the `PORTFOLIO_DEFAULT_NORMALIZE_WEIGHTS` config setting, default `false`).

5. **Update docstring** to document `delta_changes`.

**Reuses:**
- `parse_delta()` from `utils/helpers_input.py:41-118` — public API for delta string parsing (converts "+200bp"/"-5%"/"+0.05" to decimal). Same function used by the what-if pipeline.
- Same additive logic as `simulate_portfolio_change()` at `portfolio_risk_engine/portfolio_optimizer.py:122-124`

**Codex R1 fix:** Changed from private `_parse_shift()` to public `parse_delta()`. Removed explicit `normalize_weights()` call — config default is `false` (`config.py:35`). The backtest engine normalizes at `backtest_engine.py:124` when the config setting is enabled.

**Codex R2 fix:** Added ticker key normalization (uppercase + strip) before `parse_delta()` to prevent duplicate-key bugs when delta_changes uses lowercase tickers (e.g., `"aapl"` vs base_weights `"AAPL"`). `parse_delta()` preserves key casing from its input, so normalization must happen before the call.

**Note on `parse_delta` error handling:** `parse_delta()` raises `ValueError` if shift strings are unparseable. The `@handle_mcp_errors` decorator on `run_backtest()` catches this and returns a structured error response — no additional try/except needed.

---

## Step 5: Add `delta_changes` to MCP server registration

**File:** `mcp_server.py`

In the `run_backtest` wrapper (line 1649-1694):
1. Add `delta_changes: Optional[dict] = None` parameter after `weights` (line 1650)
2. Pass through: `delta_changes=delta_changes` in the `_run_backtest()` call (after line 1685)
3. Update docstring

---

## Step 6: Update existing tests

### 6a. Optimization snapshot key test
**File:** `tests/core/test_optimization_agent_snapshot.py`

Update key assertion at line 36-44 — add `"resolved_weights"` to expected set.

Add tests:
- `test_agent_snapshot_resolved_weights_includes_all()` — full `optimized_weights` dict appears (no dust filtering)
- `test_agent_snapshot_resolved_weights_decimal_format()` — values are decimal (0.25 not 25.0)

### 6b. WhatIf snapshot key test
**File:** `tests/core/test_whatif_agent_snapshot.py`

Update key assertion at line 84-95 — add `"resolved_weights"` to expected set.

Add tests:
- `test_agent_snapshot_resolved_weights_matches_scenario()` — scenario_weights appear in resolved_weights
- `test_agent_snapshot_resolved_weights_empty_when_no_scenario()` — graceful empty dict

### 6c. WhatIf MCP agent format test
**File:** `tests/mcp_tools/test_whatif_agent_format.py`

Add `"resolved_weights": {}` to `_DummyResult._snapshot` dict so the dummy snapshot is valid.

---

## Step 7: Create new test files

### 7a. Backtest snapshot tests
**File:** `tests/core/test_backtest_agent_snapshot.py` (NEW)

Pattern: follow `test_optimization_agent_snapshot.py` with `_make_result()` factory.

Tests:
- `test_agent_snapshot_keys()` — all expected keys including `resolved_weights`
- `test_agent_snapshot_resolved_weights_matches_input()` — weights passed appear in snapshot
- `test_agent_snapshot_resolved_weights_decimal_format()` — decimal not percentage

### 7b. Backtest MCP agent format tests
**File:** `tests/mcp_tools/test_backtest_agent_format.py` (NEW)

Tests:
- `test_agent_format_structure()` — response has status/format/snapshot/flags/file_path
- `test_agent_format_snapshot_has_resolved_weights()` — resolved_weights in snapshot
- `test_delta_changes_resolves_to_weights()` — "+5%" with base weights produces correct result
- `test_delta_changes_mutual_exclusion()` — both weights + delta_changes returns error
- `test_delta_changes_invalid_string()` — unparseable delta string returns error (e.g., "abc")
- `test_delta_changes_no_baseline()` — delta_changes with empty portfolio returns error
- `test_delta_changes_lowercase_ticker()` — lowercase/whitespace tickers in delta_changes merge correctly with uppercase base_weights (no duplicate keys)
- `test_mcp_server_delta_changes_param()` — AST introspection of mcp_server.py confirms `delta_changes` parameter on wrapper (follows pattern at `test_whatif_agent_format.py:352`, `test_optimization_agent_format.py:315`)
- `test_mcp_server_delta_changes_forwarded()` — verify `delta_changes` is passed through in the `_run_backtest()` call at `mcp_server.py:1683` (not just parameter presence but actual forwarding)

**Codex R1 fix:** Added error branch tests + AST wrapper schema test (missing from original plan).
**Codex R2 fix:** Added lowercase ticker regression test + wrapper forwarding verification test.

---

## Edge Cases

- **`delta_changes={}`** — `bool({})` is `False`, falls through to `weights or portfolio_data.get_weights()`. Correct behavior.
- **New tickers in delta_changes** — added with weight = 0.0 + delta. Engine excludes if no price history (existing behavior).
- **Negative weights after delta** — Deltas that drive a position negative create a short weight. The backtest engine's `build_portfolio_view()` handles this via `get_returns_dataframe()`, but `portfolio_risk.py:673-678` falls back to `{}` when net weight total is not positive after ticker exclusions. **Limitation:** net-short or market-neutral portfolios after exclusions may produce empty results. This matches what-if behavior (same code path) but is not "fully supported" — document in docstring.
- **Invalid delta strings** — `parse_delta()` raises `ValueError` for unparseable shifts. `@handle_mcp_errors` catches this and returns structured error. No special handling needed.
- **Missing baseline weights** — If `delta_changes` is provided but portfolio has no positions, returns explicit error before delta resolution.

**Codex R1 fix:** Original plan overstated negative weight support. Added limitation note.

---

## Files Changed

| File | Type | Change |
|------|------|--------|
| `core/result_objects/backtest.py` | Modify | +1 line: `resolved_weights` in snapshot |
| `core/result_objects/optimization.py` | Modify | +1 line: `resolved_weights` in snapshot |
| `core/result_objects/whatif.py` | Modify | +1 line: `resolved_weights` in snapshot |
| `mcp_tools/backtest.py` | Modify | +30 lines: `delta_changes` param + resolution |
| `mcp_server.py` | Modify | +5 lines: `delta_changes` passthrough |
| `tests/core/test_optimization_agent_snapshot.py` | Modify | Key set update + 2 new tests |
| `tests/core/test_whatif_agent_snapshot.py` | Modify | Key set update + 2 new tests |
| `tests/mcp_tools/test_whatif_agent_format.py` | Modify | Add resolved_weights to dummy |
| `tests/core/test_backtest_agent_snapshot.py` | Create | 3 tests |
| `tests/mcp_tools/test_backtest_agent_format.py` | Create | 9 tests |

~45 lines production code, ~280 lines tests. 10 files total.

---

## Verification

1. `pytest tests/core/test_backtest_agent_snapshot.py tests/core/test_optimization_agent_snapshot.py tests/core/test_whatif_agent_snapshot.py -v`
2. `pytest tests/mcp_tools/test_backtest_agent_format.py tests/mcp_tools/test_whatif_agent_format.py -v`
3. Full suite: `pytest tests/ -x --timeout=120`
4. Manual MCP test: call `run_backtest(delta_changes={"AAPL": "+5%"}, format="agent")` and verify `resolved_weights` in snapshot
5. TypeScript build: `cd frontend && npm run build` (no frontend changes, but sanity check)

---

## TODO.md Update

After implementation, update `docs/TODO.md:44` section:
- Check off the audit questions answered by this change
- Mark the section as `PARTIAL` (v1 done, v2/v3 remaining)
