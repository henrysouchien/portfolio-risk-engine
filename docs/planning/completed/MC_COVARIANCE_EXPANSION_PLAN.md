# Bug A8 Fix: MC Covariance Expansion for New Tickers

## Context

When chaining What-If → Monte Carlo, What-If adds new tickers (e.g. AGG via `delta_changes`) to `resolved_weights`. MC builds `risk_result` from the original portfolio only, so the covariance matrix doesn't cover AGG. The validator at `monte_carlo.py:136` raises `ValueError: resolved_weights contains tickers not in covariance matrix: AGG`.

The original plan (`MC_NEW_TICKER_GRACEFUL_DROP_PLAN.md`) proposed dropping unknown tickers and warning. But that defeats the purpose of the What-If → MC chain — the user wants to simulate the hypothetical portfolio *with* the new ticker.

**Revised approach:** Two-layer fix.
- **Layer 1 (Primary):** Expand the covariance matrix to include new tickers by fetching their returns. Same pattern What-If already uses (`portfolio_optimizer.py:914-921`).
- **Layer 2 (Fallback):** Gracefully drop tickers that still can't be included (e.g. insufficient price history < 12 months). Warn instead of crash.

## Critical Files

| File | Change |
|------|--------|
| `portfolio_risk_engine/portfolio_risk.py` | New `expand_risk_result_for_tickers()` helper (module-internal, after `build_portfolio_view`) |
| `portfolio_risk_engine/monte_carlo.py:99-142` | Validator: warn-and-drop (fallback), numeric validation reorder, return tuple |
| `portfolio_risk_engine/monte_carlo.py:593` | Unpack `(raw_weights, dropped_tickers)` from validator |
| `portfolio_risk_engine/monte_carlo.py:~718` | Add `dropped_tickers` to result dict + warning string |
| `portfolio_risk_engine/monte_carlo.py:378` | Add `dropped_tickers` param to `_build_flat_result()` |
| `services/scenario_service.py:536` | Call expansion helper before `run_monte_carlo()` |
| `mcp_tools/monte_carlo.py:112` | Call expansion helper before engine call |
| `services/agent_building_blocks.py:505` | Call expansion helper before engine call (third call site) |
| `core/result_objects/monte_carlo.py` | Add `dropped_tickers` field, wire into all 3 output methods |
| `core/monte_carlo_flags.py` | Add `tickers_dropped` warning flag |
| `models/response_models.py:215` | Add `dropped_tickers` to `MonteCarloResponse` Pydantic model |

## Implementation Steps

### Step 1: Expansion helper — `portfolio_risk_engine/portfolio_risk.py`

Add `expand_risk_result_for_tickers()` near `build_portfolio_view()`. Uses existing `get_returns_dataframe()` + `compute_covariance_matrix()` + `compute_correlation_matrix()` from the same file.

```python
def expand_risk_result_for_tickers(
    risk_result: RiskAnalysisResult,
    resolved_weights: Dict[str, float],
    start_date: str,
    end_date: str,
    *,
    ticker_alias_map=None, currency_map=None,
    instrument_types=None, contract_identities=None,
) -> Tuple[RiskAnalysisResult, List[str]]:
```

Logic:
1. `existing = set(str(t) for t in risk_result.covariance_matrix.columns)`
2. `new_tickers = {str(t or "").strip().upper() for t in resolved_weights if str(t or "").strip()} - existing` — uses the same `str(ticker or "").strip().upper()` defensive pattern as the engine validator (`monte_carlo.py:114`) to handle `None` or non-string keys without `AttributeError`.
3. **Early return** `(risk_result, [])` if no new tickers — zero overhead for common case.
4. Build combined weights dict (all existing + new tickers as keys). Weight values don't matter for covariance — just need tickers as keys.
5. **Wrap `get_returns_dataframe()` in try/except**: Call `get_returns_dataframe(combined, start_date, end_date, ...)`. If it raises (transient provider failure, all symbols fail at `portfolio_risk.py:1063`), log a warning and return `(risk_result, list(new_tickers))` — fall back to original covariance, let the validator's graceful-drop handle the new tickers. This ensures a fetch failure never aborts Monte Carlo.
6. **Monotonic expansion guard**: Check that ALL existing covariance tickers are still present in `returns_df.columns`. If any existing ticker was dropped (transient data issue, provider hiccup), abort expansion — log a warning and return `(risk_result, list(new_tickers))` treating all new tickers as still-missing. This prevents the expansion from shrinking the covariance universe and regressing MC behavior.
7. Compute `new_cov = compute_covariance_matrix(returns_df)` and `new_corr = compute_correlation_matrix(returns_df)`.
8. `still_missing = [t for t in new_tickers if t not in set(str(c) for c in returns_df.columns)]` — tickers excluded by `get_returns_dataframe` due to insufficient history.
9. Use `dataclasses.replace(risk_result, covariance_matrix=new_cov, correlation_matrix=new_corr)` — avoids mutating the cached original. The `_api_response_cache` field (`init=False`) resets to `None`, which is correct.
10. Log info: "Expanded covariance matrix: {existing_count} → {new_count} tickers"
11. Return `(expanded_result, still_missing)`.

### Step 2: No public export

Keep `expand_risk_result_for_tickers` as a module-internal function in `portfolio_risk.py`. Both call sites import it directly from `portfolio_risk_engine.portfolio_risk` — no need to export via `portfolio_risk_engine/__init__.py` unless another public caller actually needs it.

### Step 3: Validator fallback — `monte_carlo.py:99-142`

Change `_validate_resolved_weights()`:

**a) Reorder loop** — numeric validation BEFORE universe check:
```python
for ticker, raw_value in resolved_weights.items():
    normalized_ticker = str(ticker or "").strip().upper()
    if not normalized_ticker:
        invalid_tickers.append(str(ticker))
        continue
    # Numeric validation FIRST
    try:
        numeric_value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid resolved weight for ticker '{normalized_ticker}': {raw_value}") from exc
    if not math.isfinite(numeric_value):
        raise ValueError(f"Invalid resolved weight for ticker '{normalized_ticker}': {raw_value}")
    # Universe check AFTER
    if universe and normalized_ticker not in universe:
        missing_tickers.append(normalized_ticker)
        continue
    normalized_weights[normalized_ticker] = numeric_value
```

**b) Replace raise with warn-and-drop** (lines 136-138):
```python
if missing_tickers and not normalized_weights:
    raise ValueError(f"resolved_weights contains only tickers not in covariance matrix: {', '.join(sorted(set(missing_tickers)))}")
if missing_tickers:
    _LOGGER.warning("Dropping %d ticker(s) not in covariance matrix: %s", len(missing_tickers), ", ".join(sorted(set(missing_tickers))))
```

**c) Change return type** to `Tuple[Dict[str, float], List[str]]`:
```python
return normalized_weights, sorted(set(missing_tickers))
```

### Step 4: Wire expansion + validator changes into engine — `monte_carlo.py`

**Call site (line 593):** Unpack tuple:
```python
raw_weights, dropped_tickers = _validate_resolved_weights(risk_result, resolved_weights)
```

Initialize `dropped_tickers = []` at top of resolved-weights branch so it's available when `resolved_weights is None`.

**Main result dict (~line 718):** Add `"dropped_tickers": sorted(dropped_tickers)`. Add warning string if non-empty.

**`_build_flat_result()` (line 378):** Add `dropped_tickers: Optional[list[str]] = None` parameter, include `"dropped_tickers": list(dropped_tickers or [])` in returned dict. Update call site to pass it.

### Step 5: Wire expansion into call sites

**`services/scenario_service.py:536`** — after `risk_result = self.portfolio_service.analyze_portfolio(portfolio_data)`:
```python
if resolved_weights is not None:
    from portfolio_risk_engine.portfolio_risk import expand_risk_result_for_tickers
    risk_result, _expansion_misses = expand_risk_result_for_tickers(
        risk_result, resolved_weights,
        portfolio_data.start_date, portfolio_data.end_date,
        ticker_alias_map=portfolio_data.ticker_alias_map,
        currency_map=portfolio_data.currency_map,
        instrument_types=portfolio_data.instrument_types,
        contract_identities=portfolio_data.contract_identities,
    )
```

**`mcp_tools/monte_carlo.py:112`** — after `risk_result = PortfolioService(...).analyze_portfolio(portfolio_data)`:
Same pattern. `portfolio_data` has all needed attributes (`start_date`, `end_date`, `ticker_alias_map`, `currency_map`, `instrument_types`, `contract_identities` — confirmed in `data_objects.py:1069-1078`).

**`services/agent_building_blocks.py:505`** — after `risk_result = PortfolioService(cache_results=True).analyze_portfolio(portfolio_data)`:
Same pattern. This is the agent code execution registry's `run_monte_carlo()` function, which also builds `risk_result` from the original portfolio and passes `resolved_weights` to `_run_monte_carlo_engine()` at line 555.

### Step 6: Result object + flags + REST response model

**`core/result_objects/monte_carlo.py`:**
- Add field: `dropped_tickers: List[str] = field(default_factory=list)`
- `from_engine_output()`: `dropped_tickers=list(data.get("dropped_tickers", []) or [])`
- `get_agent_snapshot()` → in `conditioning` dict: `"dropped_tickers": self.dropped_tickers`
- `get_summary()`: `"dropped_tickers": self.dropped_tickers`
- `to_api_response()`: `"dropped_tickers": self.dropped_tickers`

**`core/monte_carlo_flags.py`:**
- Read `dropped_tickers` from `snapshot.get("conditioning", {}).get("dropped_tickers", [])`
- If non-empty, emit `{"type": "tickers_dropped", "severity": "warning", "message": "...", "dropped_tickers": [...]}`
- Dedup: skip `engine_warnings` entries starting with `"Dropped "` to avoid double-flagging

**`models/response_models.py:215` — `MonteCarloResponse`:**
- Add field: `dropped_tickers: Optional[List[str]] = None`
- Without this, the `/api/monte-carlo` endpoint (which uses `response_model=MonteCarloResponse`) would silently strip the new field from REST responses.

### Step 7: Tests

**`tests/test_monte_carlo.py` — engine/validator tests:**
1. Update `test_resolved_weights_missing_ticker_raises` → `test_resolved_weights_missing_ticker_drops_and_warns`: no longer raises; assert `dropped_tickers == ["NVDA"]` and warning in result
2. New: `test_resolved_weights_all_missing_raises` — all tickers outside covariance → still ValueError
3. New: `test_numeric_validation_before_universe_check` — `{"NVDA": "oops"}` raises ValueError even though NVDA not in universe
4. New: `test_industry_etf_drift_zero_for_new_ticker` — build 3-asset result, pass `resolved_weights` with a ticker present in covariance but missing from `expected_returns`, with `drift_model="industry_etf"`. Assert simulation succeeds (no crash). Use `caplog` to assert the engine log message `"Missing expected return for Monte Carlo industry_etf drift ticker"` fires. This confirms the zero-drift fallback is intentional and observable. (Note: the engine logs this warning at `monte_carlo.py:275-278` but does NOT add it to `result["warnings"]` — that is by design, as it's an engine-internal diagnostic, not a user-facing warning.)

**New file `tests/test_expand_risk_result.py` — expansion helper tests:**
5. `test_expand_noop_no_new_tickers` — same object returned (`is` identity check), `still_missing == []`
6. `test_expand_adds_new_ticker_to_covariance` — mock `get_returns_dataframe` returning expanded DataFrame, assert new ticker in covariance index+columns
7. `test_expand_reports_still_missing` — mock returns excluding one new ticker, assert in `still_missing`
8. `test_expand_does_not_mutate_original` — original `risk_result.covariance_matrix` unchanged after expansion
9. `test_expand_monotonic_guard_aborts_on_existing_ticker_loss` — mock `get_returns_dataframe` returning a DataFrame that drops one existing ticker (simulating transient data issue). Assert the function returns the **original** risk_result unchanged, with all new tickers reported as still_missing. Verifies the monotonic expansion guard.
10. `test_expand_fetch_failure_falls_back_gracefully` — mock `get_returns_dataframe` to raise `Exception`. Assert the function returns the **original** risk_result unchanged, with all new tickers reported as still_missing. Verifies the try/except fallback.

**`tests/test_monte_carlo_flags.py` — flag tests:**
11. `test_tickers_dropped_flag_fires` — snapshot with `dropped_tickers=["AGG"]`, assert flag present with severity `warning`
12. `test_tickers_dropped_flag_absent_when_empty` — assert no flag
13. `test_tickers_dropped_dedup_with_engine_warnings` — snapshot with both `dropped_tickers=["AGG"]` and a `"Dropped "` engine warning string. Assert only one flag for the event (dedup works).

**`tests/test_monte_carlo_result.py` — result object tests:**
14. Update `_engine_output()` fixture to include `"dropped_tickers": []`
15. Update `test_get_agent_snapshot_matches_documented_shape` (line 99) — add `"dropped_tickers": []` to the expected `conditioning` dict. This existing exact-shape assertion will fail without this update.
16. `test_dropped_tickers_in_agent_snapshot` — build with `dropped_tickers=["AGG"]`, assert `snapshot["conditioning"]["dropped_tickers"] == ["AGG"]`
17. `test_dropped_tickers_in_summary_and_api` — assert field present in both `get_summary()` and `to_api_response()`

**`tests/test_response_models.py` or inline — REST contract test:**
18. `test_monte_carlo_response_includes_dropped_tickers` — instantiate `MonteCarloResponse` with `dropped_tickers=["AGG"]`, assert the field survives Pydantic serialization. Ensures the REST endpoint doesn't silently strip the field.

**Wrapper call site tests (mock-based, 3 call sites):**
19. `test_scenario_service_passes_expanded_result_to_engine` — in `tests/services/test_scenario_service.py`. Mock `expand_risk_result_for_tickers` to return a sentinel expanded result, and mock the MC engine. Call `run_monte_carlo_simulation(resolved_weights={"AAPL": 0.5, "AGG": 0.5})`. Assert the **expanded** risk_result (not the original) is what gets passed as `risk_result=` to `run_monte_carlo()`. The existing test harness captures engine kwargs — use that to verify. This proves the bug is actually fixed, not just that the helper was called.
20. `test_mcp_mc_passes_expanded_result_to_engine` — in `tests/mcp_tools/test_monte_carlo_mcp.py`. **Requires updating `_setup_tool()` harness**: (a) Add `ticker_alias_map=None, currency_map=None, instrument_types=None, contract_identities=None` to the `portfolio_data` SimpleNamespace stub (line 73-78). (b) Add a `covariance_matrix` (pd.DataFrame with test tickers as index/columns) to the fake `analyze_portfolio()` return value (line 98). (c) The existing `test_resolved_weights_pass_through_and_surface_in_response` (line 399) will now hit the expansion helper before the engine — it must still pass since the resolved_weights tickers (AAPL, MSFT) are in the fake covariance universe and the helper's early-return path fires. Verify this test still passes after the harness update.
21. `test_agent_blocks_mc_passes_expanded_result_to_engine` — same pattern in `tests/services/test_agent_building_blocks.py` for the agent registry call site at `agent_building_blocks.py:505`. Check the existing test harness for similar SimpleNamespace gaps.

## Known Limitations — Explicit Design Decisions

- **Drift for new tickers (industry_etf model)**: New tickers will use **0.0 drift** in `industry_etf` mode because `ReturnsService.get_complete_returns()` (`mcp_tools/monte_carlo.py:134`) only generates expected returns for the stored portfolio universe, not for new tickers from `resolved_weights`. The engine already logs a per-ticker warning at `monte_carlo.py:275-278`: `"Missing expected return for Monte Carlo industry_etf drift ticker {ticker}; using 0 drift"`. This is **intentional for the initial fix** — the primary value of the expansion is correct covariance (correlations and volatility), not drift precision. A follow-up could call `ReturnsService.estimate_returns_for_tickers()` for new tickers, but the 0.0 fallback is conservative and safe. **This must be tested.**
- **Drift for new tickers (historical model)**: Falls back to `portfolio_monthly_mean` for tickers missing from `asset_vol_summary` (`monte_carlo.py:217-218`). Acceptable — won't crash, uses portfolio average as proxy.
- **Factor betas for new tickers**: If `scenario_shocks` is used alongside new tickers, the conditioning may not fully capture the new ticker's factor exposure. Edge case — scenario_shocks + new tickers is an unusual combination.
- **Performance**: Expansion re-fetches returns for ALL tickers (original should hit FMP cache). Expect ~1-3s additional latency when triggered, only on the new-ticker path.

## Verification

1. Run existing MC tests: `pytest tests/test_monte_carlo.py tests/test_monte_carlo_flags.py tests/test_monte_carlo_result.py -v`
2. Run new expansion tests: `pytest tests/test_expand_risk_result.py -v`
3. Integration: MCP `run_whatif(delta_changes={"AGG": "+10%"})` → take `resolved_weights` → `run_monte_carlo(resolved_weights=...)` → expect 200 with AGG in simulation (not dropped)
4. Fallback: MCP `run_monte_carlo(resolved_weights={"AAPL": 0.5, "XYZFAKE": 0.5})` → expect 200 with `dropped_tickers=["XYZFAKE"]` and warning flag
