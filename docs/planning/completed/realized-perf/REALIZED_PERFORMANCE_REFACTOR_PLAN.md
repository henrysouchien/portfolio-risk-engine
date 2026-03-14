# Refactor: Split `realized_performance_analysis.py` into Package

## Context

`core/realized_performance_analysis.py` is 6,729 lines with 80 functions. We're actively debugging IBKR realized performance accuracy (3 pending fixes touching synthetic events, cash/NAV, and the core engine). The file is too large to navigate efficiently. Goal: split into a `core/realized_performance/` package with cohesive submodules, following the `core/result_objects/` pattern.

**Zero behavior change. Pure structural refactoring.**

## Package Structure

```
core/realized_performance/
├── __init__.py          # Re-exports everything (backward compat)
├── _helpers.py          # ~275 lines — constants, type coercions, pure utilities
├── pricing.py           # ~215 lines — PriceResult, registry, chain fetch, diagnostics
├── holdings.py          # ~330 lines — current positions, source scoping, account matching
├── fx.py                # ~100 lines — FX series fetchers, cache, event rates
├── timeline.py          # ~640 lines — synthetic events, position timeline, seed lots
├── nav.py               # ~720 lines — cash/NAV, monthly returns, TWR, PnL helpers
├── provider_flows.py    # ~615 lines — flow dedup, authority, slice functions
├── backfill.py          # ~325 lines — backfill CSV, diagnostics, realized PnL/income
├── engine.py            # ~2,210 lines — core single-scope analyzer
└── aggregation.py       # ~1,370 lines — account discovery, series helpers, public API
```

Plus: `core/realized_performance_analysis.py` becomes a thin backward-compat shim.

## Monkey-Patching Strategy (Critical)

Tests import as `from core import realized_performance_analysis as rpa` and patch via `monkeypatch.setattr(rpa, "function_name", mock)`.

**Problem:** A shim doing `from core.realized_performance import *` creates *copies* of bindings. Patching the shim's namespace doesn't affect the submodule's namespace. If `engine.py` does `from .nav import compute_monthly_nav`, patching `rpa.compute_monthly_nav` won't reach engine.

**Solution:** Submodules call sibling functions via module reference: `from . import nav` then `nav.compute_monthly_nav()`. Tests patch the **submodule** target: `monkeypatch.setattr(rpa.nav, "compute_monthly_nav", mock)`. This is a mandatory test update per wave — each wave updates the monkey-patches for functions it extracts.

The backward-compat shim (`core/realized_performance_analysis.py`) does `from core.realized_performance import *` for callers that only *import* names (not patch them). For patching, tests use `rpa.submodule.function`.

**The `_ORIGINAL_*` pattern** (3 sentinel variables for detecting test patches) moves to `_helpers.py` with the originals captured at import time. Engine checks `_helpers._ORIGINAL_FETCH_MONTHLY_CLOSE`.

## Phased Approach

### Wave 1: Scaffold + Peripherals (low risk)
Create package directory, `__init__.py`. Extract:
- `_helpers.py` — constants + utility functions (lines 76-275, 493-536)
- `pricing.py` — PriceResult + pricing chain (lines 279-493)
- `holdings.py` — position/holdings building (lines 536-862)
- `fx.py` — FX handling (lines 863-966)

These have minimal cross-dependencies. `__init__.py` re-exports all public names. Original file becomes shim importing from package.

**Test:** `pytest tests/core/test_realized_performance_analysis.py -x` (no test changes needed — `rpa.X` still resolves via `__init__.py`).

### Wave 2: High-Value Modules (where IBKR fixes touch)
Extract:
- `timeline.py` — synthetic events + position timeline (lines 871-1606)
- `nav.py` — cash derivation + NAV + monthly returns (lines 1606-2330)

These are where the 3 pending IBKR fixes operate:
- Synthetic TWR price alignment → `timeline.py`
- Cash anchor NAV → `nav.py`
- MTM double-counting → `timeline.py` + `nav.py`

**Test:** same test suite, verify passing.

### Wave 3: Provider Flows + Backfill
Extract:
- `provider_flows.py` — dedup, authority, slicing (lines 2326-2822)
- `backfill.py` — backfill CSV, diagnostics, PnL/income summaries (lines 2825-3150)

**Test:** same test suite.

### Wave 4: Engine + Aggregation
Extract:
- `engine.py` — `_analyze_realized_performance_single_scope` (lines 3150-5360)
- `aggregation.py` — account discovery, series helpers, aggregated result, public entry point (lines 5360-6729)

Engine imports siblings via `from . import _helpers, timeline, nav, fx, holdings, pricing, provider_flows, backfill` and calls through the module reference (e.g., `nav.compute_monthly_nav()`, `_helpers._flows_to_dict()`). This is the biggest wave — engine.py carries the most import dependencies.

Update `__init__.py` to import `analyze_realized_performance` from `aggregation`. Original shim file now just does `from core.realized_performance import *`.

**Test:** full test suite + `python3 -c "from core.realized_performance_analysis import analyze_realized_performance; print('OK')"` (backward compat).

### Wave 5: Test Patch Updates (required)
Update test monkey-patches to target specific submodules (e.g., `monkeypatch.setattr(rpa.nav, "compute_monthly_nav", mock)`). This is required because patching the shim namespace doesn't propagate to submodule bindings used by engine.py. Done incrementally: each wave updates patches for the functions it extracts.

## What We Defer

**Breaking `_analyze_realized_performance_single_scope` into sub-functions.** The 2,210-line function has heavy local state threading and a 520-line nested closure (`_compose_cash_and_external_flows`). Breaking it up during active IBKR debugging is high risk. The package split alone gives us file-level navigation. Phase functions can come later when the 3 IBKR fixes are landed and accuracy is stable.

## Function-to-Submodule Mapping

### `_helpers.py`
- `TYPE_ORDER`, `_FX_PAIR_SYMBOL_RE`, `_IBKR_ACCOUNT_ID_RE`, `REALIZED_PROVIDER_ALIAS_MAP` (constants)
- `_is_fx_artifact_symbol()`, `_infer_instrument_type_from_transaction()`, `_infer_position_instrument_type()`
- `_to_datetime()`, `_as_float()`, `_value_at_or_before()`, `_series_from_cache()`
- `_option_fifo_terminal_series()`, `_option_expiry_datetime()`
- `_month_end_range()`, `_business_day_range()`, `_normalize_monthly_index()`
- `_dict_to_series()`, `_series_to_dict()`, `_flows_to_dict()`, `_dict_to_flow_list()` (series conversion helpers — shared by engine + aggregation)
- `_ORIGINAL_FETCH_MONTHLY_CLOSE`, `_ORIGINAL_GET_MONTHLY_FX_SERIES`, `_ORIGINAL_COMPUTE_MONTHLY_RETURNS` (test sentinels)

### `pricing.py`
- `PriceResult` (dataclass)
- `_build_default_price_registry()`, `_fetch_price_from_chain()`, `_emit_pricing_diagnostics()`

### `holdings.py`
- `_build_current_positions()`, `SourceScopedHoldings` (dataclass)
- `_normalize_source_token()`, `_match_account()`, `_is_ibkr_identity_field()`
- `_provider_matches_from_position_row()`, `_build_source_scoped_holdings()`

### `fx.py`
- `get_monthly_fx_series()`, `get_daily_fx_series()`, `_build_fx_cache()`, `_event_fx_rate()`

### `timeline.py`
- `_synthetic_events_to_flows()`, `_synthetic_price_hint_from_position()`
- `_detect_first_exit_without_opening()`, `_build_seed_open_lots()`
- `build_position_timeline()`, `_create_synthetic_cash_events()`

### `nav.py`
- `derive_cash_and_external_flows()`, `compute_monthly_nav()`
- `compute_monthly_external_flows()`, `compute_monthly_returns()`, `compute_twr_monthly_returns()`
- `_safe_treasury_rate()`, `_compute_unrealized_pnl_usd()`, `_compute_net_contributions_usd()`
- `_income_with_currency()`

### `provider_flows.py`
- `_normalize_optional_identifier()`, `_normalize_replay_identifier()`, `_normalize_realized_replay_provider()`, `_replay_account_identity()`
- `_dedupe_income_provider_internal_flow_overlap()`, `_flow_slice_key()`, `_provider_flow_event_sort_key()`
- `_deduplicate_provider_flow_events()`, `_build_provider_flow_authority()`
- `_is_snaptrade_sync_gap_metadata_row()`, `_build_fetch_metadata_warnings()`
- `_is_authoritative_slice()`, `_authoritative_slice_status()`, `_combine_cash_snapshots()`
- `_normalize_source_name()`

### `backfill.py`
- `_sanitize_backfill_id_component()`, `_build_backfill_transaction_id()`
- `_build_backfill_entry_transactions()`, `_emit_backfill_diagnostics()`
- `_compute_realized_pnl_usd()`, `_summarize_income_usd()`

### `engine.py`
- `_analyze_realized_performance_single_scope()` (the 2,210-line core function)

### `aggregation.py`
- `_prefetch_fifo_transactions()`, `_looks_like_display_name()`
- `_discover_account_ids()`, `_discover_schwab_account_ids()`
- `_snap_flow_date_to_nav()`, `_merge_window()`, `_merge_numeric_dict()`
- `_sum_account_daily_series()`, `_sum_account_monthly_series()`
- `_build_aggregated_result()`, `_analyze_realized_performance_account_aggregated()`
- `analyze_realized_performance()` (public entry point)

## Files Modified

| File | Change |
|------|--------|
| `core/realized_performance/` (new) | Package with 10 submodules + `__init__.py` |
| `core/realized_performance_analysis.py` | Becomes backward-compat shim (~5 lines) |
| `tests/core/test_realized_performance_analysis.py` | Update monkey-patch targets to submodules (`rpa.nav`, `rpa.fx`, etc.) |
| `tests/core/test_realized_cash_anchor.py` | Update monkey-patch targets |
| `tests/core/test_realized_perf_futures_mtm.py` | Update monkey-patch targets (if any) |

## Verification

After each wave:
1. `pytest tests/core/test_realized_performance_analysis.py -x -q`
2. `pytest tests/core/test_realized_performance_bond_pricing.py -x -q`
3. `pytest tests/core/test_realized_cash_anchor.py -x -q`
4. `pytest tests/core/test_realized_perf_futures_mtm.py -x -q`
5. `pytest tests/mcp_tools/test_performance.py -x -q`
6. `python3 -c "from core.realized_performance_analysis import analyze_realized_performance; print('OK')"`
