# Plan: Extract `portfolio-risk-engine` Package — COMPLETED 2026-02-23

**Status:** All phases implemented. 1143 tests passing. Live-verified.

## Context

The monorepo `risk_module/core/` contains portfolio analytics code that needs to be extracted into a standalone pip-installable package, following the same pattern as `brokerage-connect` (shims, re-export compatibility, zero consumer breakage). An outdated standalone repo exists at `~/Documents/Jupyter/portfolio-risk-engine/` — it will be replaced.

The key insight: the real math lives in **root-level modules** (`portfolio_risk.py`, `factor_utils.py`, `data_loader.py`, etc.), not just `core/`. Without those, the package is data objects with no computation. We pull them in.

---

## What Moves vs What Stays

### Moves into `portfolio_risk_engine/`

| Source | Why |
|--------|-----|
| `core/exceptions.py`, `constants.py`, `risk_profiles.py`, `risk_flags.py`, `income_projection.py`, `exit_signals.py` | Pure — zero external deps |
| `core/data_objects.py`, `performance_metrics_engine.py` | Core data layer — minor refactoring |
| `core/portfolio_config.py` | Portfolio input normalization (rewire FMP/DB deps) |
| `core/config_adapters.py` | Config resolution (depends on portfolio_config — must move together) |
| `portfolio_risk.py` (1780 lines) | Factor regression, covariance, variance decomposition |
| `factor_utils.py` (622 lines) | Factor beta computation, HAC regression |
| `data_loader.py` | Data fetching layer — rewired to PriceProvider protocol |
| `risk_helpers.py`, `risk_summary.py` | Internal math helpers |
| `portfolio_optimizer.py` (1376 lines) | Min-variance, max-return optimization |
| `portfolio_risk_score.py` (1930 lines) | Risk scoring engine |
| `core/performance_analysis.py`, `stock_analysis.py`, `scenario_analysis.py`, `optimization.py`, `asset_class_performance.py` | Analysis entrypoints |

### Stays in Monorepo

| File | Why |
|------|-----|
| `core/result_objects.py` | 7380 lines, heavy presentation/service coupling (see below) |
| `core/realized_performance_analysis.py` | ~15 provider/trading_analysis deps |
| `core/factor_intelligence.py` | Depends on proxy_builder → gpt_helpers + database |
| `core/portfolio_analysis.py` | Orchestration wrapper for run_portfolio_risk |
| `core/interpretation.py` | Depends on gpt_helpers (LLM calls) |
| `proxy_builder.py` | GPT + database coupling |
| `run_portfolio_risk.py` | Orchestration glue, stays as monorepo wiring |
| `helpers_display.py`, `helpers_input.py` | CLI/display helpers (not core analysis) |
| `utils/etf_mappings.py`, `utils/sector_config.py` | Presentation-layer utilities |
| `core/broker_adapter.py`, `core/trade_objects.py` | Already shims for brokerage/ |

### Why `result_objects.py` stays (changed from v1)

Codex review found `result_objects.py` (7380 lines) has coupling to:
- `helpers_display` (lazy, 3+ calls)
- `run_portfolio_risk` (lazy)
- `utils.etf_mappings` (lazy, 4 calls with try/except)
- `utils.sector_config` (lazy, 1 call)
- `core.portfolio_config.get_cash_positions` (lazy, try/except)

These are all lazy/conditional imports, but the file is a broad presentation surface — it formats results for API, CLI, and MCP consumers. Moving it drags in display/service concerns that don't belong in a math library.

**Instead:** The package defines lightweight result dataclasses in a new `portfolio_risk_engine/results.py`. The monorepo's `core/result_objects.py` imports from there and adds presentation logic. This keeps the package focused on computation while the monorepo handles formatting.

---

## Package Structure

```
portfolio_risk_engine/
├── __init__.py                    # Public API exports
├── _logging.py                    # Logging shim (monorepo fallback → stdlib)
├── _vendor.py                     # Vendored: make_json_safe, _to_float
├── config.py                      # Settings from env vars (replaces settings.py imports)
├── providers.py                   # PriceProvider / FXProvider protocols + registry
├── _fmp_provider.py               # Default FMP implementation (lazy-imports fmp.compat)
├── pyproject.toml
│
├── # Tier 1: Pure data (zero deps)
├── exceptions.py
├── constants.py
├── risk_profiles.py
├── risk_flags.py
├── income_projection.py
├── exit_signals.py
│
├── # Tier 2: Data objects + metrics
├── data_objects.py
├── performance_metrics_engine.py
├── results.py                     # Lightweight result dataclasses (new, extracted from result_objects.py)
│
├── # Tier 3: Math engine (the core value)
├── data_loader.py                 # Rewired to use PriceProvider protocol
├── factor_utils.py
├── portfolio_risk.py
├── risk_helpers.py
├── risk_summary.py
├── portfolio_optimizer.py
├── portfolio_risk_score.py
│
├── # Tier 4: Analysis entrypoints + config
├── portfolio_config.py
├── config_adapters.py             # Moved here (depends on portfolio_config)
├── performance_analysis.py
├── stock_analysis.py
├── scenario_analysis.py
├── optimization.py
└── asset_class_performance.py
```

---

## Key Abstraction: PriceProvider Protocol

All external data fetching funnels through `data_loader.py` → `fmp.compat`. We create a `PriceProvider` protocol covering the **full** `data_loader` API surface:

```python
# providers.py
@runtime_checkable
class PriceProvider(Protocol):
    def fetch_monthly_close(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_monthly_treasury_rates(self, maturity: str, start_date=None, end_date=None) -> pd.Series: ...
    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw) -> pd.DataFrame: ...
    def fetch_current_dividend_yield(self, ticker, **kw) -> float: ...

@runtime_checkable
class FXProvider(Protocol):
    def adjust_returns_for_fx(self, returns: pd.Series, currency: str, **kw) -> Union[pd.Series, dict]: ...  # Returns dict when decompose=True
    def get_fx_rate(self, currency: str) -> float: ...

_price_provider: PriceProvider | None = None
_fx_provider: FXProvider | None = None

def set_price_provider(provider: PriceProvider) -> None: ...
def get_price_provider() -> PriceProvider: ...
def set_fx_provider(provider: FXProvider) -> None: ...
def get_fx_provider() -> FXProvider | None: ...  # Returns None if not configured (FX is optional)
```

Default: `_fmp_provider.py` lazy-imports `fmp.compat` and `fmp.fx` when available. FX operations gracefully skip when no provider is set (already guarded by try/except in `portfolio_risk.py`).

---

## Re-export Shim Strategy: Module-alias, Not Star-imports

### Problem (from Codex P0 finding)

Star re-exports (`from portfolio_risk_engine.X import *`) create **copies** of names in the shim module. Tests that do `monkeypatch.setattr("core.exceptions.SomeError", mock)` would patch the copy, not the real object — breaking test isolation.

### Solution: Module-alias shims

Each shim replaces itself in `sys.modules` so the old import path resolves to the actual package module:

```python
# core/exceptions.py (shim)
import portfolio_risk_engine.exceptions as _mod
import sys
sys.modules[__name__] = _mod
```

This means `import core.exceptions` and `import portfolio_risk_engine.exceptions` return the **same module object**. Monkeypatch works because there's only one module.

For root-level shims (e.g., `portfolio_risk.py`, `data_loader.py`), the same pattern:

```python
# portfolio_risk.py (shim)
import portfolio_risk_engine.portfolio_risk as _mod
import sys
sys.modules[__name__] = _mod
```

**Tested pattern:** This is the standard approach for package renames (e.g., `sklearn` → `scikit-learn`). All existing `monkeypatch.setattr(mod, "func", ...)` calls continue to work because `mod` is the real module object regardless of which import path was used.

---

## Shim Files (internal to package)

- **`_logging.py`**: Try monorepo `utils.logging`, fall back to stdlib `logging.getLogger()`. Decorators (`log_timing`, `log_errors`, `log_operation`) become no-ops in standalone mode.
- **`_vendor.py`**: Vendor `make_json_safe` (from `utils.serialization`), `_to_float`. Note: `_drop_factors` from `helpers_display` is NOT vendored — it's only used by `portfolio_optimizer.py` via lazy import and `helpers_display` stays in monorepo.
- **`config.py`**: All `settings.py` constants → env-var-driven with sensible defaults. Includes `PORTFOLIO_DEFAULTS`, `DIVIDEND_DEFAULTS`, `DATA_QUALITY_THRESHOLDS`, `RATE_FACTOR_CONFIG`, `FMP_API_KEY`. A `configure()` function allows programmatic override.

---

## Handling Specific Coupling Points

### `portfolio_optimizer.py` dependencies

| Dependency | Source | Resolution |
|-----------|--------|-----------|
| `build_portfolio_view`, `normalize_weights` | `portfolio_risk.py` | Internal import (both move) |
| `evaluate_portfolio_risk_limits`, `evaluate_portfolio_beta_limits` | `run_portfolio_risk.py` | **Injectable parameters** with default=None (skip limit checks when not provided). Monorepo wires them in. |
| `_drop_factors` | `helpers_display.py` | Lazy import wrapped in **try/except** — skip factor dropping standalone |
| `compare_risk_tables`, `compare_beta_tables` | `helpers_display.py` | Lazy imports in `run_what_if_scenario` — wrap in **try/except**, return unformatted results standalone |
| `parse_delta` | `helpers_input.py` | Lazy import in `run_what_if_scenario` — wrap in **try/except**, require explicit delta dict standalone |
| `risk_helpers.*` | `risk_helpers.py` | Internal import (both move) |

### `core/stock_analysis.py` service dependencies

`security_type_service` is already guarded with try/except:
```python
# Already in the code:
try:
    from services.security_type_service import SecurityTypeService
    asset_class = SecurityTypeService.get_asset_classes([ticker]).get(ticker, 'equity')
except Exception:
    asset_class = 'equity'  # Works standalone
```

**`factor_proxy_service` is NOT guarded** (`stock_analysis.py:194,198`). Must wrap in try/except during extraction:
```python
# Needs to be added:
try:
    from services.factor_proxy_service import get_stock_factor_proxies
    factor_proxies = get_stock_factor_proxies(ticker)
except Exception:
    factor_proxies = {}  # Standalone: caller must pass factor_proxies explicitly
```

### `core/data_objects.py` DB dependency

`_load_cash_proxy_map()` has 3-tier fallback: DB → YAML → hardcoded defaults. Replace DB tier with optional injection:
```python
_db_loader: Callable | None = None
def set_db_loader(loader): ...  # Monorepo wires this
```
YAML and hardcoded fallbacks work standalone.

### `portfolio_risk.py` FX/IBKR lazy imports

Already defensive with try/except (lines 567-590). In standalone mode without `ibkr` or `fmp.fx`:
- Currency detection falls back to USD
- FX adjustment is skipped
- No errors raised

When `FXProvider` is set via `set_fx_provider()`, the package uses it instead of lazy `fmp.fx` imports.

---

## Phased Execution

### Phase 1: Scaffolding + Tier 1 (pure modules)
1. Create `portfolio_risk_engine/` with `__init__.py`, `_logging.py`, `_vendor.py`, `config.py`, `providers.py`, `_fmp_provider.py`, `pyproject.toml`
2. Copy 6 Tier 1 files verbatim (zero changes needed): `exceptions.py`, `constants.py`, `risk_profiles.py`, `risk_flags.py`, `income_projection.py`, `exit_signals.py`
3. Create **module-alias shims** at `core/` paths (e.g., `core/exceptions.py` → `sys.modules[__name__] = portfolio_risk_engine.exceptions`)
4. Run tests — zero breakage expected

### Phase 2: Tier 2 (data objects + metrics)
1. Move `data_objects.py` — replace `database.get_db_session` with optional `set_db_loader()` injection, keep YAML/hardcoded fallback
2. Move `performance_metrics_engine.py` — replace `settings.DATA_QUALITY_THRESHOLDS` with `config.DATA_QUALITY_THRESHOLDS`
3. Create `results.py` — extract lightweight result dataclasses from `result_objects.py` (the math-relevant fields, not presentation methods)
4. Module-alias shims at `core/` paths, run tests

**Important:** All moved modules that currently import from `core.result_objects` must be rewired to `portfolio_risk_engine.results` during their extraction phase. Affected files:
- `portfolio_risk_score.py` (Phase 4) — imports `RiskScoreResult`
- `core/performance_analysis.py` (Phase 4) — imports `PerformanceResult`
- `core/optimization.py` (Phase 4) — imports `OptimizationResult`
- `core/scenario_analysis.py` (Phase 4) — imports `WhatIfResult`
- `core/stock_analysis.py` (Phase 4) — imports `StockAnalysisResult`

The monorepo's `core/result_objects.py` continues to import from `portfolio_risk_engine.results` and extends with presentation methods. Both paths resolve correctly via module-alias shims.

### Phase 3: Tier 3 (math engine — the big move)
1. Rewire `data_loader.py` to use `PriceProvider` protocol instead of `fmp.compat` direct imports. Cache helpers (`cache_read`/`cache_write`) are self-contained and come along.
2. Move `factor_utils.py` — replace `settings`/`utils.logging` with package shims, keep direct `requests` calls for FMP API (uses `config.FMP_API_KEY`)
3. Move `portfolio_risk.py` — replace imports with internal package imports. FX lazy imports already try/except — add `get_fx_provider()` as preferred path.
4. Move `risk_helpers.py`, `risk_summary.py` — internal deps only after above
5. Move `portfolio_optimizer.py` — make `evaluate_portfolio_risk_limits` and `evaluate_portfolio_beta_limits` **optional callable parameters** (default=None → skip limit evaluation). Wrap `helpers_display`/`helpers_input` lazy imports in **try/except with graceful fallback** (return unformatted results when helpers unavailable in standalone mode).
6. Create module-alias shims at root paths
7. Run tests

### Phase 4: Tier 4 (analysis entrypoints + config)
1. Move `portfolio_config.py` — replace `fmp.compat.fetch_monthly_close` with `get_price_provider()` call, replace DB imports with optional injection (already has YAML fallback), replace `utils.ticker_resolver` with vendored `select_fmp_symbol` (~20 lines) or make optional
2. Move `config_adapters.py` — all deps (`portfolio_config`, `data_objects`) are now internal
3. Move `portfolio_risk_score.py` — move threshold/scenario config to `config.py`, make `SecurityTypeService` optional (lazy import with fallback). Depends on `config_adapters`/`portfolio_config` which are now internal. Rewire `core.result_objects.RiskScoreResult` → `portfolio_risk_engine.results`.
4. Move `performance_analysis.py`, `scenario_analysis.py`, `optimization.py`, `asset_class_performance.py` — all deps are internal. Rewire `core.result_objects` imports → `portfolio_risk_engine.results`.
5. Move `stock_analysis.py` — wrap `services.factor_proxy_service` import in **try/except** (currently unguarded at `stock_analysis.py:194,198`). `security_type_service` is already guarded. Standalone fallback: require `factor_proxies` parameter explicitly. Rewire `core.result_objects` → `portfolio_risk_engine.results`.
6. Module-alias shims at `core/` paths
7. Run full test suite

### Phase 5: Verification + cleanup
1. `pip install -e portfolio_risk_engine/` in clean venv
2. Verify import: `from portfolio_risk_engine import build_portfolio_view`
3. Verify all monorepo tests still pass via module-alias shims
4. Scrub for secrets and hardcoded paths
5. Update `RELEASE_PLAN.md` with completed steps

---

## Risk Areas

| Risk | Severity | Mitigation |
|------|----------|------------|
| Module-alias shims + circular imports | HIGH | Test each phase incrementally. Note: alias shims DO execute the target module at import time — ensure no circular import chains between shim and package. Import order matters. |
| `portfolio_optimizer.py` without risk-limit evaluators | MEDIUM | Default=None skips limits; monorepo passes real functions. Document in API. |
| `data_loader.py` cache paths changing | LOW | Cache dir comes from `config.py` with same defaults as current `settings.py` |
| `result_objects.py` stays but depends on moved modules | MEDIUM | It already lazy-imports core modules; module-alias shims mean the imports still resolve |
| Tests that import from both old and new paths | LOW | Module-alias ensures same object regardless of path |

---

## Verification

```bash
# 1. Monorepo tests still pass (zero breakage via module-alias shims)
cd ~/Documents/Jupyter/risk_module && python -m pytest tests/ -x

# 2. Standalone install works
python -m venv /tmp/pre-test && source /tmp/pre-test/bin/activate
pip install -e portfolio_risk_engine/
python -c "from portfolio_risk_engine import build_portfolio_view; print('OK')"

# 3. With FMP provider (live)
FMP_API_KEY=xxx python -c "
from portfolio_risk_engine import build_portfolio_view
result = build_portfolio_view(weights={'AAPL': 0.5, 'MSFT': 0.5})
print(result)
"

# 4. Module-alias shim verification
python -c "
import core.exceptions as a
import portfolio_risk_engine.exceptions as b
assert a is b, 'Module alias shim failed'
print('Shim OK: same module object')
"
```

---

## Not in Scope (later phases per RELEASE_PLAN.md)
- Math validation / benchmark comparison (Phase 5 task, after extraction)
- Methodology documentation
- Public GitHub repo + PyPI publish
- README positioning
