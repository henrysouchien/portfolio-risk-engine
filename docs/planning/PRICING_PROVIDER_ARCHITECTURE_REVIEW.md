# Pricing Provider Architecture Review

**Date**: 2026-02-27
**Status**: Review complete (Codex-verified), refactor plan TBD
**Goal**: Assess how easy it is to swap or add a new price data provider. Identify coupling points and recommend fixes.

## Overall Assessment: 6/10 (Decent, but two abstractions need unification)

The codebase has good provider abstractions, but there are **two separate pricing systems** that don't talk to each other. The modern `ProviderRegistry` + `PriceSeriesProvider` chain (used in realized performance) is well-designed. The legacy `PriceProvider` global (used in hypothetical analysis) is simpler but broader. Unifying them is the main architectural task. FX conversion is hardcoded to FMP throughout — `set_fx_provider()` exists but is never called anywhere.

**Estimated effort to integrate a new provider**: 4-8 hours (must satisfy both abstractions or unify them first).

---

## Critical Finding: Two Pricing Abstractions (Partially Coupled)

### Abstraction 1: Legacy Global — `portfolio_risk_engine/providers.py`

Used by: `latest_price()`, `get_returns_dataframe()`, hypothetical portfolio analysis.

```python
class PriceProvider(Protocol):
    def fetch_monthly_close(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_monthly_treasury_rates(self, maturity, start_date=None, end_date=None) -> pd.Series: ...
    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw) -> pd.DataFrame: ...
    def fetch_current_dividend_yield(self, ticker, **kw) -> float: ...

class FXProvider(Protocol):
    def adjust_returns_for_fx(self, returns, currency, **kw) -> Union[pd.Series, dict]: ...
    def get_fx_rate(self, currency) -> float: ...
```

**Broader interface** — 5 methods on PriceProvider (close, total return, treasury, dividends, yield). Single global singleton via `get_price_provider()` / `set_price_provider()`. Default: `FMPPriceProvider` (lazy-loaded). No instrument-type dispatch.

### Abstraction 2: Modern Chain — `providers/interfaces.py` + `providers/registry.py`

Used by: realized performance analysis (`core/realized_performance_analysis.py`).

```python
class PriceSeriesProvider(Protocol):
    provider_name: str
    def can_price(self, instrument_type: str) -> bool: ...
    def fetch_monthly_close(self, symbol, start_date, end_date, *,
        instrument_type="equity", contract_identity=None, fmp_ticker_map=None) -> pd.Series: ...
```

**Narrower interface** — just `can_price()` + `fetch_monthly_close()`. But supports instrument-type routing and multi-provider fallback chains via `ProviderRegistry`.

### The Two Systems Are Partially Coupled

The modern chain is **not fully independent** of the legacy global. Key coupling:

1. **FMP leg delegates to legacy global**: `_build_default_price_registry()` creates `FMPPriceProvider(fetcher=fetch_monthly_close)`, and `fetch_monthly_close` in `data_loader.py:170` calls `get_price_provider().fetch_monthly_close()` — the legacy global singleton.
2. **Treasury rates via legacy**: Realized performance calls `fetch_monthly_treasury_rates()` (`data_loader.py:232`) which delegates to `get_price_provider().fetch_monthly_treasury_rates()`.
3. **FX is direct FMP import**: Realized performance imports `from fmp.fx import get_monthly_fx_series` directly — bypasses both abstractions.

This means **swapping the legacy global provider also affects the modern chain's FMP leg**. The IBKR leg is independent (uses its own fetchers).

### How They're Used

| Path | Abstraction | Providers | Notes |
|------|-------------|-----------|-------|
| `latest_price()` → hypothetical analysis | Legacy global (`PriceProvider`) | FMP only (default) | FX via `get_fx_provider()` (silent no-op if unset) |
| `get_returns_dataframe()` → hypothetical analysis | Legacy global (`PriceProvider`) | FMP only (default) | FX fallback imports `fmp.fx` directly |
| Realized performance — equity/futures pricing | Modern chain, but FMP leg delegates to legacy global | FMP (via legacy) + IBKR (independent) | |
| Realized performance — treasury rates | Legacy global (via `data_loader.fetch_monthly_treasury_rates`) | FMP only | |
| Realized performance — FX | Neither — direct `fmp.fx` import | FMP only | Bypasses both abstractions |
| MCP tools (direct IBKR calls) | Neither — direct `IBKRMarketDataClient` calls | IBKR only | |

**Key problem**: The two abstractions are tangled. A new provider must either implement both interfaces, or we unify them first. Additionally, swapping the legacy global has a side-effect on the modern chain's FMP leg.

---

## Architecture Flow

### Hypothetical Analysis Path (Legacy Global)

```
build_portfolio_view() / analyze_portfolio()
  ↓
get_returns_dataframe(weights, start_date, end_date)
  ↓
  for each ticker:
    get_price_provider().fetch_monthly_total_return_price(ticker)
      ↓  (fallback)
    get_price_provider().fetch_monthly_close(ticker)
      ↓
    FX-adjust if needed
      fallback: from fmp.fx import adjust_returns_for_fx  ← HARDCODED
      ↓
    calc_monthly_returns(prices)
  ↓
pd.DataFrame → pure math (covariance, volatility, factors)
```

### Realized Performance Path (Modern Chain)

```
analyze_realized_performance()
  ↓
_build_default_price_registry()
  ↓
  ProviderRegistry with:
    FMPPriceProvider (priority 10) — equity, futures
    IBKRPriceProvider (priority 20) — futures, fx, bond, option
  ↓
  for each ticker:
    registry.get_price_chain(instrument_type)
      → try each provider in priority order
      → first success wins
```

---

## Layer-by-Layer Assessment

### 1. Modern Provider Interface — `providers/interfaces.py` (9/10)

Clean Protocol with instrument-type routing. `contract_identity` dict allows provider-specific metadata without polluting the interface. Adding a new provider to the modern chain is straightforward.

### 2. Provider Registry — `providers/registry.py` (8/10)

Priority-ordered chain with `can_price()` gating. Exceptions caught. Clean design.

### 3. Legacy Global — `portfolio_risk_engine/providers.py` (6/10)

Simple but broader — requires 5 methods (treasury rates, dividends, yield) beyond basic pricing. No instrument-type dispatch. Single provider, no fallback chain. `set_fx_provider()` exists but **is never called anywhere in the codebase** — FMP FX is always used via direct import fallback.

### 4. IBKR Integration (7/10)

IBKR **is** registered in `ProviderRegistry` for realized performance:
- `IBKRPriceProvider` in `providers/ibkr_price.py` implements `PriceSeriesProvider`
- Registered at priority 20 (after FMP at 10)
- Handles: futures, fx, bond, option
- Built in `_build_default_price_registry()` at `core/realized_performance_analysis.py:291`

**Not integrated** into the legacy global path (`latest_price()`, `get_returns_dataframe()`). Those paths only use FMP.

### 5. Symbol Resolution — `providers/symbol_resolution.py` (8/10)

Provider-aware. Routes IBKR futures to FMP equivalents. No hardcoded vendor assumptions.

---

## Coupling Points

### CP-1: Realized Performance FX (Medium)

**File**: `core/realized_performance_analysis.py`
**Import**: `from fmp.fx import get_monthly_fx_series`
**Impact**: Called during realized performance analysis for FX conversion.
**Fix**: Route through FX provider. Note: current `FXProvider` protocol lacks a monthly-series method — needs extension.
**Effort**: Medium (protocol extension + implementation).

### CP-2: FX Adjustment in Hypothetical Analysis — Default FMP Path (Medium)

**File**: `portfolio_risk_engine/portfolio_risk.py` (~line 588)
**Import**: `from fmp.fx import adjust_returns_for_fx`
**Impact**: `set_fx_provider()` is never called anywhere in the codebase. In `get_returns_dataframe()`, this means the FMP FX import is the *actual default* for all non-USD tickers. Note: `latest_price()` uses `get_fx_provider()` correctly but silently no-ops when unset (no FX conversion happens), which is a different bug.
**Fix**: Either call `set_fx_provider()` at startup with FMP as explicit default, or make the default initialization lazy (like `get_price_provider()`).
**Effort**: Small (but requires deciding on default FX provider initialization strategy).

### CP-3: Currency Inference (Low)

**File**: `portfolio_risk_engine/_ticker.py`
**Import**: `fetch_fmp_quote_with_currency()` for inferring currency when unknown.
**Impact**: Only fires when `currency_map` is not provided. Bypassed with explicit data.
**Fix**: Abstract into a `CurrencyResolver` protocol, default implementation uses FMP.
**Effort**: Small.

### CP-4: Position Service FMP Imports (Low)

**File**: `services/position_service.py` (lines ~674, ~765)
**Import**: Direct FMP calls for position enrichment.
**Impact**: Position-level data enrichment, not core pricing.
**Fix**: Route through provider abstraction if needed for provider swap.
**Effort**: Small.

### CP-5: Cache Adapters FMP Imports (Low)

**File**: `services/cache_adapters.py` (lines ~165, ~171)
**Import**: Direct FMP calls for cache warming.
**Impact**: Cache layer, not core pricing.
**Fix**: Route through provider abstraction.
**Effort**: Small.

### CP-6: Modern Chain FMP Leg Delegates to Legacy Global (Architectural)

**File**: `core/realized_performance_analysis.py:294` → `portfolio_risk_engine/data_loader.py:170`
**Mechanism**: `_build_default_price_registry()` injects `fetch_monthly_close` (from `data_loader`) as the FMP leg. That function delegates to `get_price_provider().fetch_monthly_close()` — the legacy global singleton.
**Impact**: The modern chain's FMP pricing is NOT independent of the legacy global. Swapping the legacy global via `set_price_provider()` also affects the modern chain's FMP leg. This is a hidden coupling — the two systems look separate but are linked.
**Fix**: Either make this coupling explicit (document it as intentional) or give the modern chain its own FMP fetcher that doesn't delegate to the global.
**Effort**: Small to document, medium to decouple.

### CP-7: Realized Performance Treasury Rates via Legacy Global (Low)

**File**: `core/realized_performance_analysis.py:1884` → `data_loader.py:232`
**Mechanism**: `_safe_treasury_rate()` calls `fetch_monthly_treasury_rates()` which delegates to `get_price_provider().fetch_monthly_treasury_rates()`.
**Impact**: Treasury rate sourcing in realized performance goes through the legacy global, not the modern chain. A provider registered only in `ProviderRegistry` won't affect treasury rates. Conversely, `set_price_provider()` DOES affect treasury rates.
**Fix**: Add treasury rate sourcing to the modern chain or accept this as intentional delegation.
**Effort**: Small.

### CP-8: Realized Performance Benchmark Pricing via Legacy Global (Low)

**File**: `core/realized_performance_analysis.py:4191`
**Mechanism**: Benchmark pricing calls `fetch_monthly_close()` directly (from `data_loader`), which delegates to `get_price_provider().fetch_monthly_close()` — bypassing the `ProviderRegistry` chain.
**Impact**: Benchmark returns in realized performance use the legacy global, not the modern chain. Same pattern as CP-6/CP-7 — `set_price_provider()` affects this, `ProviderRegistry` does not.
**Fix**: Route through the modern chain's `_fetch_price_from_chain()`, or accept as intentional delegation.
**Effort**: Small.

---

## What Adding a New Provider Looks Like Today

### For Realized Performance (Modern Chain) — Easy

```python
# 1. Implement PriceSeriesProvider
class BloombergPriceProvider:
    provider_name = "bloomberg"

    def can_price(self, instrument_type: str) -> bool:
        return instrument_type in ["equity", "futures", "fx"]

    def fetch_monthly_close(self, symbol, start_date, end_date, **kwargs) -> pd.Series:
        ...

# 2. Register in chain
registry.register_price_provider(BloombergPriceProvider(), priority=5)  # highest priority
```

### For Hypothetical Analysis (Legacy Global) — Requires Broader Interface

```python
# Must implement ALL 5 methods of PriceProvider
class BloombergPriceProvider:
    def fetch_monthly_close(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_monthly_treasury_rates(self, maturity, start_date=None, end_date=None) -> pd.Series: ...
    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw) -> pd.DataFrame: ...
    def fetch_current_dividend_yield(self, ticker, **kw) -> float: ...

# Then swap global
set_price_provider(BloombergPriceProvider())
```

### For Both — Complex Due to Coupling

The two systems are partially coupled (CP-6): the modern chain's FMP leg delegates to the legacy global. This means:

- **`set_price_provider(new_provider)`** has wide reach: affects hypothetical analysis, the modern chain's FMP leg, treasury rates (CP-7), and benchmark pricing in realized performance. Does NOT affect the IBKR leg or FX (which is direct `fmp.fx` import).
- **Registering only in `ProviderRegistry`** covers realized performance instrument-type routing (fx, bond, option chain semantics) — but misses hypothetical analysis, treasury rates, benchmark pricing, dividends, and yield.
- **Full coverage** requires both: `set_price_provider()` for the legacy paths (which cascade into multiple realized-performance paths), and `ProviderRegistry` registration for instrument-type routing and multi-provider fallback semantics.

A new provider must implement both interfaces or we unify them first.

---

## Recommended Cleanup (for full pluggability)

### Phase 1 — FX Provider Initialization (Small, High Impact)
- [ ] CP-2: Initialize `set_fx_provider()` at startup with FMP as explicit default (not silent fallback)
- [ ] CP-1: Extend `FXProvider` protocol with `get_monthly_fx_series()` method, route realized perf through it
- [ ] CP-3: Abstract currency inference into `CurrencyResolver` protocol

### Phase 2 — Clarify/Decouple the Legacy↔Modern Coupling (Medium, Prerequisite for Unification)
- [ ] CP-6: Decide whether the modern chain's FMP leg *should* delegate to the legacy global (intentional shared default) or have its own independent fetcher
- [ ] CP-7: Decide whether treasury rates should flow through the modern chain or remain in legacy global
- [ ] Document the coupling explicitly if keeping it, or decouple if not
- [ ] This must be resolved before attempting full unification — otherwise the migration scope is unclear

### Phase 3 — Unify Pricing Abstractions (Medium-Large, Core Fix)
- [ ] Bridge or merge the two abstractions so a single provider registration covers both paths
- [ ] Options: (a) Make `ProviderRegistry` the single source, adapt legacy global to delegate to it; (b) Extend `PriceSeriesProvider` with treasury/dividend methods; (c) Create adapter that wraps `PriceSeriesProvider` as `PriceProvider`
- [ ] Wire IBKR into hypothetical analysis path (currently FMP-only)

### Phase 4 — Reduce Scattered FMP Imports (Small)
- [ ] CP-4: Route `position_service.py` FMP calls through provider abstraction
- [ ] CP-5: Route `cache_adapters.py` FMP calls through provider abstraction

### Phase 5 — Documentation & Testing (Small)
- [ ] Document provider registration patterns in `docs/reference/`
- [ ] Add integration test: swap provider, verify both analysis paths work
- [ ] Document the `currency_map` override pattern

---

## Key Files Reference

| File | Role |
|------|------|
| `providers/interfaces.py` | `PriceSeriesProvider` protocol (modern chain) |
| `providers/registry.py` | `ProviderRegistry` — priority-ordered provider chain |
| `providers/fmp_price.py` | `FMPPriceProvider` for modern chain |
| `providers/ibkr_price.py` | `IBKRPriceProvider` for modern chain |
| `portfolio_risk_engine/providers.py` | `PriceProvider` / `FXProvider` protocols (legacy global) + `set_price_provider()` / `set_fx_provider()` |
| `portfolio_risk_engine/_fmp_provider.py` | Default `FMPPriceProvider` for legacy global |
| `portfolio_risk_engine/portfolio_config.py` | `latest_price()` — single-price entry point (legacy) |
| `portfolio_risk_engine/portfolio_risk.py` | `get_returns_dataframe()` — historical returns (legacy) |
| `portfolio_risk_engine/_ticker.py` | Currency inference (FMP-coupled) |
| `core/realized_performance_analysis.py` | Realized perf — builds registry with FMP+IBKR chain |
| `ibkr/market_data.py` | `IBKRMarketDataClient` — raw IBKR market data |
| `providers/symbol_resolution.py` | Provider-aware ticker resolution |
| `fmp/fx.py` | FX conversion utilities (should be behind FX provider) |
| `services/position_service.py` | Direct FMP imports for position enrichment |
| `services/cache_adapters.py` | Direct FMP imports for cache warming |
