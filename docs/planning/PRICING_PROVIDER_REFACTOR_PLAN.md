# Pricing Provider Refactor Plan

**Date**: 2026-02-27
**Updated**: 2026-02-27 (post-Futures P2 landing)
**Status**: Complete
**Prerequisite**: `PRICING_PROVIDER_ARCHITECTURE_REVIEW.md` (Codex-verified)
**Goal**: Unify the two equity/general pricing abstractions so adding a new provider = implement one interface + register once. Futures pricing stays in its own dedicated chain by design.

## Current State

Three pricing paths exist:

| System | Interface | Used By | Providers |
|--------|-----------|---------|-----------|
| Legacy global | `PriceProvider` (5 methods) | `latest_price()` (equity path), `get_returns_dataframe()` (equity path), hypothetical analysis | FMP only |
| Modern chain | `PriceSeriesProvider` (2 methods) + `ProviderRegistry` | Realized performance | FMP + IBKR |
| Futures chain | `FuturesPriceSource` + `FuturesPricingChain` | `latest_price()` (futures path), `get_returns_dataframe()` (futures path) | FMP commodity + IBKR historical |

They are **partially coupled**: the modern chain's FMP leg injects `data_loader.fetch_monthly_close`, which delegates to the legacy global `get_price_provider()`. Treasury rates and benchmark pricing in realized perf also route through the legacy global.

FX is hardcoded to FMP: `set_fx_provider()` exists but is never called.

**Futures chain scope**: The `FuturesPricingChain` (`brokerage/futures/pricing.py`) is intentionally separate — different instrument types often require different data providers and resolution logic. This refactor does NOT attempt to absorb futures into `ProviderRegistry`. The goal is to unify the **equity/general** legacy global with the modern chain.

## Target State

One pricing **interface** for new equity/general providers. `ProviderRegistry` is the canonical authority for equity/bond/option pricing. Legacy global delegates to it. Realized performance keeps a parallel factory for test isolation (guarded by a parity test) — this is an accepted tradeoff until test infrastructure is migrated to fixture-based isolation.

Futures keep their own `FuturesPricingChain` — different instrument types may use entirely different data vendors and resolution logic.

```
Equity/bond/option callers (hypothetical, realized, MCP tools)
  ↓
data_loader.fetch_monthly_close(ticker, ...)
  ↓
ProviderRegistry.get_price_chain(instrument_type)
  → try each provider in priority order
  → first success wins

Futures callers (latest_price, get_returns_dataframe when instrument_type=="futures")
  ↓
FuturesPricingChain (brokerage/futures/pricing.py)
  → FMP commodity endpoint → IBKR historical fallback
  → Separate from ProviderRegistry by design
```

Adding a new equity provider:
```python
class BloombergProvider:
    provider_name = "bloomberg"
    def can_price(self, instrument_type): ...
    def fetch_monthly_close(self, symbol, start, end, **kw): ...

registry.register_price_provider(BloombergProvider(), priority=5)
# Done. All equity analysis paths use it.
```

Adding a new futures provider:
```python
class BloombergFuturesSource:
    name = "bloomberg_futures"
    def fetch_latest_price(self, symbol, alt_symbol=None): ...
    def fetch_monthly_close(self, symbol, start, end, alt_symbol=None): ...

chain.add_source(BloombergFuturesSource())
# Futures pricing chain is separate — add sources there.
```

---

## Phase 1 — FX Provider Initialization

**Goal**: Eliminate direct `fmp.fx` imports. Make FX routing go through the provider abstraction.

### 1a. Initialize FX provider at startup

`get_fx_provider()` currently returns `None` when unset. Change to lazy-default (same pattern as `get_price_provider()`).

**File**: `portfolio_risk_engine/providers.py`

```python
# Before
def get_fx_provider() -> Optional[FXProvider]:
    return _fx_provider

# After
def get_fx_provider() -> FXProvider:
    global _fx_provider
    if _fx_provider is None:
        from portfolio_risk_engine._fmp_provider import FMPFXProvider
        _fx_provider = FMPFXProvider()
    return _fx_provider
```

### 1b. Extend FXProvider with monthly series method

Realized performance needs `get_monthly_fx_series()` (CP-1). Add to protocol.

**File**: `portfolio_risk_engine/providers.py`

```python
class FXProvider(Protocol):
    def adjust_returns_for_fx(self, returns: pd.Series, currency: str, **kw) -> Union[pd.Series, dict]: ...
    def get_fx_rate(self, currency: str) -> float: ...
    def get_spot_fx_rate(self, currency: str) -> float: ...
    def get_monthly_fx_series(self, currency: str, start_date=None, end_date=None) -> pd.Series: ...
```

Note: `get_spot_fx_rate` is used by `trading_analysis/analyzer.py` and `mcp_tools/tax_harvest.py` for real-time spot rates. `get_fx_rate` returns month-end rates. Both are needed.

**File**: `portfolio_risk_engine/_fmp_provider.py` — add implementation:

```python
class FMPFXProvider:
    ...
    def get_spot_fx_rate(self, currency):
        from fmp.fx import get_spot_fx_rate as _fn
        return float(_fn(currency))

    def get_monthly_fx_series(self, currency, start_date=None, end_date=None):
        from fmp.fx import get_monthly_fx_series as _fn
        return _fn(currency, start_date, end_date)
```

### 1c. Replace direct fmp.fx imports

| File | Current | After |
|------|---------|-------|
| `core/realized_performance_analysis.py` | `from fmp.fx import get_monthly_fx_series` | `from portfolio_risk_engine.providers import get_fx_provider` → `get_fx_provider().get_monthly_fx_series(...)` |
| `portfolio_risk_engine/portfolio_risk.py` ~L652 | `from fmp.fx import adjust_returns_for_fx` (fallback when `get_fx_provider()` returns None) | `get_fx_provider().adjust_returns_for_fx(...)` (always — no fallback needed after 1a) |
| `trading_analysis/analyzer.py` ~L60 | `from fmp.fx import get_spot_fx_rate` | Route through `get_fx_provider()` |
| `mcp_tools/tax_harvest.py` ~L29 | `from fmp.fx import get_monthly_fx_series, get_spot_fx_rate` | Route through `get_fx_provider()` |

### 1d. Abstract currency inference (CP-3)

**File**: `portfolio_risk_engine/providers.py` — add protocol:

```python
class CurrencyResolver(Protocol):
    def infer_currency(self, ticker: str) -> Optional[str]: ...
```

**File**: `portfolio_risk_engine/_fmp_provider.py` — default implementation:

```python
class FMPCurrencyResolver:
    def infer_currency(self, ticker):
        from portfolio_risk_engine._ticker import fetch_fmp_quote_with_currency
        _, currency = fetch_fmp_quote_with_currency(ticker)
        return currency
```

Wire into `latest_price()` via `get_currency_resolver()` (same lazy-default pattern).

**Tests**: Existing tests pass (behavior unchanged, just routed through provider). Add test for lazy FX init.

---

## Phase 2 — Unify Equity/General Pricing Abstractions

**Goal**: Make `ProviderRegistry` the single pricing authority for equity/bond/option instruments. Legacy `PriceProvider` becomes a facade that delegates to it. Futures pricing stays in `FuturesPricingChain` — this phase does NOT touch `brokerage/futures/pricing.py` or the futures paths in `latest_price()` / `get_returns_dataframe()`.

**Scope boundary**: `_RegistryBackedPriceProvider.fetch_monthly_close()` is called by `data_loader.fetch_monthly_close()`, which is only reached for non-futures tickers. When `instrument_type == "futures"`, callers (`latest_price`, `get_returns_dataframe`) route directly to `FuturesPricingChain` and never hit the legacy global.

### 2a. Extend PriceSeriesProvider with additional methods

The legacy `PriceProvider` has 3 methods beyond basic pricing: treasury rates, dividend history, dividend yield. These need to be accessible through the modern chain.

**Option chosen**: Separate protocols for separate concerns. Don't bloat `PriceSeriesProvider`.

```python
# In providers/interfaces.py

class TreasuryRateProvider(Protocol):
    provider_name: str
    def fetch_monthly_treasury_rates(self, maturity: str, start_date=None, end_date=None) -> pd.Series: ...

class DividendProvider(Protocol):
    provider_name: str
    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw) -> pd.DataFrame: ...
    def fetch_current_dividend_yield(self, ticker, **kw) -> float: ...
```

Note: `fetch_monthly_total_return_price` is on `DividendProvider` (not `PriceSeriesProvider`) because total-return pricing = close prices + dividend adjustment. Only providers with dividend data can compute it. The `PriceSeriesProvider` chain handles close-only pricing.

### 2b. Register FMP for treasury/dividends in ProviderRegistry

**File**: `providers/registry.py` — add treasury/dividend registration:

```python
class ProviderRegistry:
    def __init__(self):
        ...
        self._treasury_provider: TreasuryRateProvider | None = None
        self._dividend_provider: DividendProvider | None = None

    def register_treasury_provider(self, provider: TreasuryRateProvider) -> None:
        self._treasury_provider = provider

    def get_treasury_provider(self) -> TreasuryRateProvider | None:
        return self._treasury_provider

    def register_dividend_provider(self, provider: DividendProvider) -> None:
        self._dividend_provider = provider

    def get_dividend_provider(self) -> DividendProvider | None:
        return self._dividend_provider
```

### 2c. Create unified FMP provider

One class that implements all three protocols.

**File**: `providers/fmp_price.py` — extend or replace:

```python
class FMPProvider:
    """FMP provider implementing PriceSeriesProvider, TreasuryRateProvider, DividendProvider."""

    provider_name = "fmp"

    # PriceSeriesProvider
    def can_price(self, instrument_type): return instrument_type in {"equity", "futures"}
    def fetch_monthly_close(self, symbol, start_date, end_date, **kw): ...

    # TreasuryRateProvider
    def fetch_monthly_treasury_rates(self, maturity, start_date=None, end_date=None): ...

    # DividendProvider
    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw): ...
    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw): ...
    def fetch_current_dividend_yield(self, ticker, **kw): ...
```

Implementation delegates to `fmp.compat` (same as today's `_fmp_provider.py`).

### 2d. Build centralized registry at startup

**File**: New `providers/bootstrap.py`

```python
def build_default_registry() -> ProviderRegistry:
    """Build the default provider registry with FMP + IBKR."""
    from providers.fmp_price import FMPProvider
    from providers.ibkr_price import IBKRPriceProvider
    from ibkr.compat import (
        fetch_ibkr_monthly_close,
        fetch_ibkr_fx_monthly_close,
        fetch_ibkr_bond_monthly_close,
        fetch_ibkr_option_monthly_mark,
    )

    registry = ProviderRegistry()

    fmp = FMPProvider()
    registry.register_price_provider(fmp, priority=10)
    registry.register_treasury_provider(fmp)
    registry.register_dividend_provider(fmp)

    registry.register_price_provider(
        IBKRPriceProvider(
            futures_fetcher=fetch_ibkr_monthly_close,
            fx_fetcher=fetch_ibkr_fx_monthly_close,
            bond_fetcher=fetch_ibkr_bond_monthly_close,
            option_fetcher=fetch_ibkr_option_monthly_mark,
        ),
        priority=20,
    )

    return registry


# Global singleton
_registry: ProviderRegistry | None = None

def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry
```

### 2e. Make legacy global delegate to registry

**File**: `portfolio_risk_engine/providers.py`

```python
def get_price_provider() -> PriceProvider:
    global _price_provider
    if _price_provider is None:
        _price_provider = _RegistryBackedPriceProvider()
    return _price_provider


class _RegistryBackedPriceProvider:
    """Adapter: legacy PriceProvider interface backed by ProviderRegistry.

    Key design: data_loader.py passes legacy kwargs (fmp_ticker, fmp_ticker_map)
    that PriceSeriesProvider.fetch_monthly_close accepts as keyword args. The
    adapter normalizes these before forwarding to chain providers.
    """

    @staticmethod
    def _normalize_kwargs(ticker: str, kw: dict) -> dict:
        """Extract PriceSeriesProvider-compatible kwargs from legacy kwargs.

        Legacy callers pass fmp_ticker, fmp_ticker_map, etc. PriceSeriesProvider
        accepts fmp_ticker_map, instrument_type, contract_identity. This method
        maps between the two interfaces.

        fmp_ticker handling: Legacy callers pass fmp_ticker for explicit symbol
        override (e.g., international tickers mapped to FMP symbols). We merge
        it into fmp_ticker_map keyed by the actual ticker so downstream resolution
        (fmp.compat → fmp_ticker_map.get(ticker)) finds the override.
        """
        fmp_ticker_map = dict(kw.get("fmp_ticker_map") or {})
        fmp_ticker = kw.get("fmp_ticker")
        # Bridge fmp_ticker → fmp_ticker_map entry keyed by ticker
        if fmp_ticker:
            fmp_ticker_map[ticker] = fmp_ticker  # explicit override wins

        return {
            "instrument_type": kw.get("instrument_type", "equity"),
            "contract_identity": kw.get("contract_identity"),
            "fmp_ticker_map": fmp_ticker_map or None,
        }

    def fetch_monthly_close(self, ticker, start_date=None, end_date=None, **kw):
        from providers.bootstrap import get_registry
        normalized = self._normalize_kwargs(ticker, kw)
        chain = get_registry().get_price_chain(normalized["instrument_type"])
        last_exc = None
        last_result = None
        for provider in chain:
            try:
                result = provider.fetch_monthly_close(
                    ticker, start_date, end_date, **normalized
                )
                # Treat empty series as non-success (match realized perf behavior)
                if result is not None and not result.empty:
                    return result
                last_result = result
            except Exception as e:
                last_exc = e
                continue
        # If all providers returned empty, return last empty result
        # rather than raising, for backward compat with callers that handle empty
        if last_result is not None:
            return last_result
        raise ValueError(f"No provider could price {ticker}") from last_exc

    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw):
        # Total return = close + dividend adjustment. Only DividendProvider can supply this.
        from providers.bootstrap import get_registry
        dp = get_registry().get_dividend_provider()
        if dp:
            return dp.fetch_monthly_total_return_price(ticker, start_date, end_date, **kw)
        # Hard fallback: close-only (will lose dividend adjustment — logged)
        from utils.logging import portfolio_logger
        portfolio_logger.warning(
            f"No DividendProvider registered — falling back to close-only for {ticker}"
        )
        return self.fetch_monthly_close(ticker, start_date, end_date, **kw)

    def fetch_monthly_treasury_rates(self, maturity, start_date=None, end_date=None):
        from providers.bootstrap import get_registry
        tp = get_registry().get_treasury_provider()
        if tp:
            return tp.fetch_monthly_treasury_rates(maturity, start_date, end_date)
        raise ValueError("No treasury rate provider registered")

    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw):
        from providers.bootstrap import get_registry
        dp = get_registry().get_dividend_provider()
        if dp:
            return dp.fetch_dividend_history(ticker, start_date, end_date, **kw)
        raise ValueError("No dividend provider registered")

    def fetch_current_dividend_yield(self, ticker, **kw):
        from providers.bootstrap import get_registry
        dp = get_registry().get_dividend_provider()
        if dp:
            return dp.fetch_current_dividend_yield(ticker, **kw)
        return 0.0
```

### 2f. Update realized performance to use shared registry construction

**File**: `core/realized_performance_analysis.py`

Currently `_build_default_price_registry()` builds a local registry per-call, injecting module-local fetcher references (`fetch_monthly_close` imported at module top, IBKR fetchers from `ibkr.compat`). Tests monkeypatch these module-level names (e.g., `rpa.fetch_monthly_close = mock_fn`) to control pricing in isolation.

**Key constraint**: Tests patch the module-local names, not the factory. If the factory delegates to shared bootstrap that binds its own fetcher references, those patches stop working.

**Approach**: Keep `_build_default_price_registry()` with its current injection pattern (module-local fetcher references), but extract the shared bootstrap as a reference implementation. The realized-perf factory mirrors the bootstrap structure but uses its own monkeypatchable import bindings:

```python
# core/realized_performance_analysis.py — NO CHANGE to existing pattern
# Tests continue to monkeypatch: rpa.fetch_monthly_close, rpa.fetch_ibkr_monthly_close, etc.

def _build_default_price_registry() -> ProviderRegistry:
    """Build price registry using module-local fetcher bindings.

    Tests monkeypatch the module-level fetcher names to control pricing.
    Do NOT delegate to providers.bootstrap — that would break test isolation.
    """
    registry = ProviderRegistry()
    registry.register_price_provider(
        FMPPriceProvider(fetcher=fetch_monthly_close),  # module-local binding
        priority=10,
    )
    registry.register_price_provider(
        IBKRPriceProvider(
            futures_fetcher=fetch_ibkr_monthly_close,   # module-local binding
            fx_fetcher=fetch_ibkr_fx_monthly_close,
            bond_fetcher=fetch_ibkr_bond_monthly_close,
            option_fetcher=fetch_ibkr_option_monthly_mark,
        ),
        priority=20,
    )
    return registry
```

The shared `providers/bootstrap.py` uses the same pattern but with its own imports. Both produce equivalent registries — the duplication is intentional for test isolation.

**Anti-drift guard**: Add a test that asserts both registries produce equivalent provider chains:

```python
def test_registry_parity():
    """Ensure bootstrap and realized-perf registries have same providers.

    Covers: price chain membership/order, treasury provider, dividend provider.
    Does NOT cover behavioral equivalence (same fetcher implementations) —
    that's inherently untestable without integration tests.
    """
    from providers.bootstrap import build_default_registry
    from core.realized_performance_analysis import _build_default_price_registry

    bootstrap = build_default_registry()
    realized = _build_default_price_registry()

    # Price chain parity across all instrument types
    for itype in ("equity", "futures", "fx", "bond", "option"):
        b_names = [p.provider_name for p in bootstrap.get_price_chain(itype)]
        r_names = [p.provider_name for p in realized.get_price_chain(itype)]
        assert b_names == r_names, f"Price chain drift for {itype}: bootstrap={b_names}, realized={r_names}"

    # Treasury provider parity
    b_tp = bootstrap.get_treasury_provider()
    r_tp = realized.get_treasury_provider()
    assert (b_tp is None) == (r_tp is None), "Treasury provider presence mismatch"
    if b_tp and r_tp:
        assert b_tp.provider_name == r_tp.provider_name, "Treasury provider name drift"

    # Dividend provider parity
    b_dp = bootstrap.get_dividend_provider()
    r_dp = realized.get_dividend_provider()
    assert (b_dp is None) == (r_dp is None), "Dividend provider presence mismatch"
    if b_dp and r_dp:
        assert b_dp.provider_name == r_dp.provider_name, "Dividend provider name drift"
```

Note: The realized-perf factory currently does NOT register treasury/dividend providers (it only needs price chains). The parity test will surface this gap and force alignment when those protocols are added in Phase 2b.

**Future cleanup**: Once tests are migrated to fixture-based isolation (e.g., `set_registry()` / `reset_registry()`), the realized-perf factory can delegate to bootstrap. But that's a test infrastructure change, not a pricing refactor.

### 2g. Backward compatibility

- `data_loader.py` functions unchanged — they call `get_price_provider()` which now delegates to registry
- `set_price_provider()` still works for tests/overrides — it replaces the global, bypassing registry
- Realized performance tests still monkeypatch the factory function — no isolation change
- Legacy `fmp_ticker` kwarg normalized by `_RegistryBackedPriceProvider._normalize_kwargs()` so existing callers don't break

**Tests**: Run full test suite. Key assertions:
- `get_price_provider()` returns `_RegistryBackedPriceProvider` by default
- Price chain includes FMP + IBKR
- `set_price_provider(custom)` overrides for test isolation
- `data_loader.fetch_monthly_close()` works with `fmp_ticker` / `fmp_ticker_map` kwargs
- `fetch_monthly_total_return_price()` returns dividend-adjusted data (not close-only)
- Treasury/dividend/yield still return data
- Realized performance tests still pass with monkeypatched fetchers

---

## Phase 3 — Reduce Scattered FMP Imports

**Goal**: Route remaining direct FMP calls through provider abstractions.

### 3a. Position service FX (CP-4)

**File**: `services/position_service.py` (~lines 695, 786)
Direct `from fmp.fx import get_spot_fx_rate` — should route through `get_fx_provider().get_spot_fx_rate()` after Phase 1.
Other FMP calls in position_service (company profile data) are FMP-specific enrichment — keep as-is with a comment.

### 3b. Cache adapters (CP-5)

**File**: `services/cache_adapters.py` (~line 171)
`from fmp.fx import _get_spot_fx_cached` — internal cache helper. Keep as-is (cache layer, not pricing path) or route through `get_fx_provider()` for consistency.

---

## Phase 4 — Documentation & Testing

- [ ] Document `providers/bootstrap.py` and `get_registry()` pattern in `docs/reference/`
- [ ] Add integration test: register custom provider, verify it handles pricing for all analysis paths
- [ ] Document how to add a new provider (single page, step-by-step)
- [ ] Add test: `set_price_provider()` override still works for test isolation

---

## Sequencing & Dependencies

```
Phase 1 (FX cleanup)
  ↓ no dependency
Phase 2 (Unify abstractions)
  ↓ requires Phase 1 (FX routing settled)
Phase 3 (Scattered imports)
  ↓ independent, can run in parallel with Phase 2
Phase 4 (Docs & tests)
  ↓ after Phase 2
```

Phase 1 and Phase 3 can run in parallel. Phase 2 is the core work. Phase 4 is cleanup.

## Files Modified

### Phase 1 (FX)
| File | Change |
|------|--------|
| `portfolio_risk_engine/providers.py` | Lazy FX default, `CurrencyResolver` protocol, `get_spot_fx_rate()` + `get_monthly_fx_series()` on `FXProvider` |
| `portfolio_risk_engine/_fmp_provider.py` | `FMPFXProvider.get_spot_fx_rate()`, `FMPFXProvider.get_monthly_fx_series()`, `FMPCurrencyResolver` |
| `core/realized_performance_analysis.py` | Replace `from fmp.fx import get_monthly_fx_series` with `get_fx_provider().get_monthly_fx_series(...)` |
| `portfolio_risk_engine/portfolio_risk.py` ~L652 | Remove FX fallback `from fmp.fx import adjust_returns_for_fx`, use `get_fx_provider()` directly (always available after 1a) |
| `portfolio_risk_engine/portfolio_config.py` | Use `get_currency_resolver()` instead of `fetch_fmp_quote_with_currency()` |
| `trading_analysis/analyzer.py` ~L60 | Replace `from fmp.fx import get_spot_fx_rate` with `get_fx_provider().get_spot_fx_rate(...)` |
| `mcp_tools/tax_harvest.py` ~L29 | Replace `from fmp.fx import get_monthly_fx_series, get_spot_fx_rate` with `get_fx_provider()` calls |

### Phase 2 (Unify)
| File | Change |
|------|--------|
| `providers/interfaces.py` | Add `TreasuryRateProvider`, `DividendProvider` protocols |
| `providers/registry.py` | Add treasury/dividend registration methods |
| `providers/fmp_price.py` | Extend to `FMPProvider` implementing all 3 protocols |
| `providers/bootstrap.py` | **New** — centralized registry builder + global singleton |
| `portfolio_risk_engine/providers.py` | `_RegistryBackedPriceProvider` adapter, legacy global delegates to registry |
| `core/realized_performance_analysis.py` | Keep local `_build_default_price_registry()` for test isolation; ensure it mirrors `providers/bootstrap.py` structure |

### Phase 3 (Scattered imports)
| File | Change |
|------|--------|
| `services/position_service.py` | Assess and route or annotate |
| `services/cache_adapters.py` | Assess and route or annotate |

## Verification

```bash
# Phase 1
pytest tests/ -x -q --timeout=30 -k "not slow"
# Spot-check: FX provider lazy-loads correctly
python3 -c "from portfolio_risk_engine.providers import get_fx_provider; print(get_fx_provider())"

# Phase 2
pytest tests/ -x -q --timeout=30 -k "not slow"
# Spot-check: registry has both providers
python3 -c "
from providers.bootstrap import get_registry
r = get_registry()
print('Price chain (equity):', [p.provider_name for p in r.get_price_chain('equity')])
print('Price chain (futures):', [p.provider_name for p in r.get_price_chain('futures')])
print('Price chain (bond):', [p.provider_name for p in r.get_price_chain('bond')])
print('Treasury:', r.get_treasury_provider().provider_name if r.get_treasury_provider() else 'None')
print('Dividend:', r.get_dividend_provider().provider_name if r.get_dividend_provider() else 'None')
"
```
