# Futures Phase 2: Pricing Dispatch — Implementation Plan

## Context

Phase 1 (done) built the `brokerage/futures/` domain model with `FuturesContractSpec`, notional math, and asset class taxonomy. The IBKR metadata in `exchange_mappings.yaml` includes multiplier, tick_size, currency, exchange, and FMP commodity symbol for all 27 contracts.

Phase 2 routes futures tickers through the pricing chain so they resolve to actual prices instead of failing through the FMP equity endpoint.

## Problem

Currently, all tickers flow through the same pricing path:

```
latest_price()  →  fetch_monthly_close()  →  FMP /historical-price-eod/full
get_returns_dataframe()  →  fetch_monthly_total_return_price()  →  FMP /historical-price-eod/dividend-adjusted
```

Futures tickers (ES, NQ, GC, etc.) don't exist as equities on FMP. They either:
1. Return no data → ValueError
2. Collide with an equity ticker (Z = Zillow vs Z = FTSE 100 futures)

The fix: detect futures tickers via `instrument_types` and route them to the right price source. This phase also decouples the futures infrastructure from IBKR-specific code, making it easy to add new data providers.

## Step 0: Decouple Contract Catalog + Pluggable Pricing Chain

### 0A. Move Contract Catalog Into `brokerage/futures/`

**Problem:** `load_contract_specs()` in `contract_spec.py` imports directly from `ibkr.compat`:
```python
from ibkr.compat import get_ibkr_futures_contract_meta, get_ibkr_futures_fmp_map
```
This means `brokerage/futures/` (supposed to be broker-agnostic) depends on the `ibkr/` package. A new futures data provider would need to modify `ibkr/` code, which is wrong.

**Fix:** Create `brokerage/futures/contracts.yaml` with the canonical contract catalog. Move the broker-agnostic data (symbol, multiplier, tick_size, currency, asset_class, fmp_symbol) out of `ibkr/exchange_mappings.yaml` into this new file. `load_contract_specs()` reads from its own YAML — no `ibkr` import.

**`brokerage/futures/contracts.yaml`:**
```yaml
# Canonical futures contract specifications (broker-agnostic)
contracts:
  ES:
    multiplier: 50
    tick_size: 0.25
    currency: USD
    exchange: CME
    asset_class: equity_index
    fmp_symbol: ESUSD
  MES:
    multiplier: 5
    tick_size: 0.25
    currency: USD
    exchange: CME
    asset_class: equity_index
    fmp_symbol: ESUSD
  # ... all 27 contracts
  DAX:
    multiplier: 25
    tick_size: 1.0
    currency: EUR
    exchange: EUREX
    asset_class: equity_index
    fmp_symbol: "^GDAXI"
  ZT:
    multiplier: 2000
    tick_size: 0.00390625
    currency: USD
    exchange: CBOT
    asset_class: fixed_income
    fmp_symbol: ZTUSD
```

**Updated `load_contract_specs()`:**
```python
def load_contract_specs() -> Dict[str, FuturesContractSpec]:
    """Load all contract specs from the canonical contracts catalog."""
    catalog = _load_contracts_yaml()
    specs: Dict[str, FuturesContractSpec] = {}
    for symbol, meta in catalog.items():
        asset_class = meta.get("asset_class")
        if asset_class is None:
            raise ValueError(f"Missing asset_class in contracts.yaml for symbol: {symbol}")
        specs[symbol] = FuturesContractSpec(
            symbol=symbol,
            multiplier=float(meta["multiplier"]),
            tick_size=float(meta["tick_size"]),
            currency=meta["currency"],
            exchange=meta["exchange"],
            asset_class=asset_class,
            fmp_symbol=meta.get("fmp_symbol"),
        )
    return specs
```

**`_ASSET_CLASS_MAP` is removed** — `asset_class` is now read directly from `contracts.yaml`. Single source of truth.

```python
def _load_contracts_yaml() -> Dict[str, Any]:
    """Load the contracts.yaml catalog file."""
    yaml_path = Path(__file__).parent / "contracts.yaml"
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return data.get("contracts", {})
```

**What stays in `ibkr/exchange_mappings.yaml`:**
- `ibkr_exchange_to_mic` — IBKR exchange code → ISO MIC mapping (IBKR-specific)
- `ibkr_futures_exchanges` — Slimmed to just `{exchange, currency}` (IBKR order-routing only). Multiplier/tick_size removed. Note: `exchange` and `currency` exist in both places — `contracts.yaml` is authoritative for contract properties, `ibkr_futures_exchanges` is authoritative for which exchange IBKR routes orders to. In practice these are the same values; the IBKR copy exists only so IBKR routing code doesn't need to import from `brokerage/futures/`.
- `ibkr_futures_to_fmp` — Removed entirely (FMP symbol mapping now in contracts.yaml).

**Backward compatibility for `ibkr/compat.py`:**
- `get_ibkr_futures_exchanges()` — unchanged. Still reads IBKR-specific routing info from `exchange_mappings.yaml` (exchange + currency only). This is the IBKR-routable symbol set.
- `get_ibkr_futures_contract_meta()` — delegates to `brokerage.futures.load_contract_specs()` but **intersects with `get_ibkr_futures_exchanges()`** to ensure only IBKR-routable symbols are returned. Overlays IBKR-specific `exchange` and `currency` from `ibkr_futures_exchanges` (IBKR routing authority) onto the contract identity from `contracts.yaml`. This preserves IBKR-specific semantics: if exchange/currency ever diverge between the two sources, the IBKR values win for IBKR routing contexts.
  ```python
  def get_ibkr_futures_contract_meta():
      from brokerage.futures import load_contract_specs
      ibkr_routing = get_ibkr_futures_exchanges()
      all_specs = load_contract_specs()
      result = {}
      for sym, spec in all_specs.items():
          if sym in ibkr_routing:
              identity = spec.to_contract_identity()
              # Overlay IBKR-specific routing values (authoritative for IBKR)
              identity["exchange"] = ibkr_routing[sym]["exchange"]
              identity["currency"] = ibkr_routing[sym]["currency"]
              result[sym] = identity
      return result
  ```
- `get_ibkr_futures_fmp_map()` — same intersection pattern. Only returns FMP mappings for IBKR-routable symbols.
- `get_futures_currency()` — delegates to `get_contract_spec(symbol).currency` (from `contracts.yaml`, the authoritative source for contract properties). This is correct because FX conversion uses the contract's intrinsic currency, not the IBKR routing currency (which is the same value in practice, but the authority distinction matters). Falls back to `"USD"` for unknown symbols:
  ```python
  def get_futures_currency(symbol: str) -> str:
      key = str(symbol or "").strip().upper()
      if not key:
          return "USD"
      from brokerage.futures import get_contract_spec
      spec = get_contract_spec(key)
      return spec.currency if spec else "USD"
  ```

### 0B. Pluggable Futures Pricing Chain

**Problem:** Phase 2 helpers (`_latest_futures_price`, `_fetch_futures_prices`) hardcode the FMP → IBKR fallback chain. Adding a new price source means modifying these helpers.

**Fix:** Define a simple protocol and ordered source list in `brokerage/futures/`:

**`brokerage/futures/pricing.py`:**
```python
from __future__ import annotations
from typing import Protocol, Optional, List
import pandas as pd


class FuturesPriceSource(Protocol):
    """Protocol for a futures price data source.

    The `alt_symbol` parameter passes a provider-specific alternate symbol
    (e.g., FMP commodity symbol). Each source decides whether to use it.
    This keeps the protocol broker-agnostic — no source-specific parameter names.
    """

    @property
    def name(self) -> str:
        """Human-readable source name for logging."""
        ...

    def fetch_latest_price(self, symbol: str, alt_symbol: Optional[str] = None) -> Optional[float]:
        """Fetch the latest available price. Returns None if unavailable."""
        ...

    def fetch_monthly_close(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        alt_symbol: Optional[str] = None,
    ) -> Optional[pd.Series]:
        """Fetch monthly close prices. Returns None if unavailable."""
        ...


class FuturesPricingChain:
    """Ordered chain of price sources. Tries each in order until one succeeds."""

    def __init__(self, sources: Optional[List[FuturesPriceSource]] = None):
        self._sources: List[FuturesPriceSource] = sources or []

    def add_source(self, source: FuturesPriceSource) -> None:
        self._sources.append(source)

    def fetch_latest_price(self, symbol: str, alt_symbol: Optional[str] = None) -> float:
        """Try each source in order. Raises ValueError if all fail."""
        for source in self._sources:
            try:
                price = source.fetch_latest_price(symbol, alt_symbol=alt_symbol)
                if price is not None:
                    return price
            except Exception:
                pass
        raise ValueError(f"No price available for futures ticker {symbol}")

    def fetch_monthly_close(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        alt_symbol: Optional[str] = None,
    ) -> pd.Series:
        """Try each source in order. Raises ValueError if all fail."""
        for source in self._sources:
            try:
                prices = source.fetch_monthly_close(
                    symbol, start_date, end_date, alt_symbol=alt_symbol,
                )
                if prices is not None and not prices.empty:
                    return prices
            except Exception:
                pass
        raise ValueError(f"No price data for futures ticker {symbol}")
```

**Default sources (registered at module level):**

**`brokerage/futures/sources/fmp.py`:**
```python
class FMPFuturesPriceSource:
    """FMP commodity endpoint as a futures price source.

    Uses alt_symbol (= FMP commodity symbol) — never falls back to raw symbol
    (raw symbol could collide with equity, e.g., Z = Zillow vs FTSE).
    Applies minor-currency normalization (e.g., GBp → GBP for FTSE).
    """

    @property
    def name(self) -> str:
        return "FMP"

    def fetch_latest_price(self, symbol, alt_symbol=None):
        if not alt_symbol:
            return None
        prices = fetch_monthly_close(alt_symbol)
        raw_price = float(prices.dropna().iloc[-1])
        # Normalize minor currency units (e.g., GBp → GBP)
        _, fmp_currency = fetch_fmp_quote_with_currency(alt_symbol)
        normalized_price, _ = normalize_fmp_price(raw_price, fmp_currency)
        return normalized_price

    def fetch_monthly_close(self, symbol, start_date, end_date, alt_symbol=None):
        if not alt_symbol:
            return None
        prices = fetch_monthly_close(alt_symbol, start_date=start_date, end_date=end_date)
        # Note: minor-currency normalization (GBp→GBP) is a price-level
        # adjustment, not a series-level one. For returns calculation,
        # the scaling cancels out (returns are ratios), so normalization
        # is not needed here. It only matters for latest_price (absolute value).
        return prices
```

**`brokerage/futures/sources/ibkr.py`:**
```python
class IBKRFuturesPriceSource:
    """IBKR historical data as a futures price source."""

    @property
    def name(self) -> str:
        return "IBKR"

    def fetch_latest_price(self, symbol, alt_symbol=None):
        from ibkr.compat import fetch_ibkr_monthly_close
        prices = fetch_ibkr_monthly_close(symbol, "2020-01-01", "2099-12-31")
        if prices.empty:
            return None
        return float(prices.dropna().iloc[-1])

    def fetch_monthly_close(self, symbol, start_date, end_date, alt_symbol=None):
        from ibkr.compat import fetch_ibkr_monthly_close
        prices = fetch_ibkr_monthly_close(symbol, start_date, end_date)
        return prices if not prices.empty else None
```

**Default chain factory:**
```python
def get_default_pricing_chain() -> FuturesPricingChain:
    """Build the default pricing chain: FMP first, IBKR fallback."""
    chain = FuturesPricingChain()
    chain.add_source(FMPFuturesPriceSource())
    chain.add_source(IBKRFuturesPriceSource())
    return chain
```

**Impact on Phase 2 helpers:** `_latest_futures_price()` and `_fetch_futures_prices()` become thin wrappers around the pricing chain instead of containing hardcoded source logic:

```python
def _latest_futures_price(ticker, *, currency=None, fmp_ticker=None, fmp_ticker_map=None):
    from brokerage.futures import get_contract_spec
    from brokerage.futures.pricing import get_default_pricing_chain

    spec = get_contract_spec(ticker)
    # Resolve FMP symbol (explicit override > contract spec, NO raw ticker)
    resolved_fmp = ...  # same logic as before

    chain = get_default_pricing_chain()
    raw_price = chain.fetch_latest_price(ticker, alt_symbol=resolved_fmp)

    # FX conversion (same logic as before)
    ...
    return raw_price
```

### 0C. Package Boundary After Decoupling

```
ibkr/
  exchange_mappings.yaml    — IBKR exchange routing only (exchange, currency)
  compat.py                 — delegates to brokerage.futures for contract data
  market_data.py            — IBKR historical bars (unchanged)

brokerage/futures/
  contracts.yaml            — canonical catalog (27 contracts, broker-agnostic)
  contract_spec.py          — FuturesContractSpec, load_contract_specs() reads own YAML
  pricing.py                — FuturesPricingChain protocol + chain
  sources/fmp.py            — FMP price source
  sources/ibkr.py           — IBKR price source (imports ibkr.compat)
  notional.py               — notional math (unchanged)

main system
  portfolio_config.py       — _latest_futures_price() uses pricing chain
  portfolio_risk.py         — _fetch_futures_prices() uses pricing chain
```

**Note:** `brokerage/futures/sources/ibkr.py` does import from `ibkr.compat` — this is intentional. The IBKR source adapter is the boundary between the broker-agnostic chain and the IBKR-specific implementation. A new provider would add `brokerage/futures/sources/newprovider.py` implementing the same protocol, and register it in the chain.

### 0D. What Changes from Phase 1

- `brokerage/futures/contract_spec.py` — `load_contract_specs()` reads from `contracts.yaml` instead of importing from `ibkr.compat`. `_ASSET_CLASS_MAP` removed (asset_class now in YAML).
- `brokerage/futures/__init__.py` — add exports for pricing chain.
- `ibkr/exchange_mappings.yaml` — `ibkr_futures_exchanges` slimmed to `{exchange, currency}` only. `ibkr_futures_to_fmp` section removed entirely.
- `ibkr/compat.py` — `get_ibkr_futures_contract_meta()` and `get_ibkr_futures_fmp_map()` delegate to `brokerage.futures` with IBKR-routable intersection. `get_futures_currency()` delegates with USD fallback.
- Tests updated to reflect new data source.

## Dispatch Points

Two categories of changes: (A) core pricing helpers that detect and route futures, and (B) `instrument_types` threading through all call chains that reach those helpers.

### 1. `latest_price()` — `portfolio_risk_engine/portfolio_config.py:254`

**Current signature:**
```python
def latest_price(ticker, *, fmp_ticker=None, fmp_ticker_map=None, currency=None) -> float
```

**Change:** Add `instrument_types` parameter. When `instrument_types.get(ticker) == "futures"`:
1. Look up `FuturesContractSpec` by IBKR root symbol to get the FMP commodity symbol
2. Fetch price via FMP commodity endpoint (using `fmp_symbol` as the ticker)
3. If FMP fails, fall back to `ibkr.compat.fetch_ibkr_monthly_close()`
4. Auto-detect currency from contract spec (skip manual currency_map lookup)
5. FX-convert if non-USD

**New signature:**
```python
def latest_price(
    ticker: str,
    *,
    fmp_ticker: str | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
    currency: str | None = None,
    instrument_types: dict[str, str] | None = None,
) -> float
```

**Futures branch (inserted before line 280, after docstring):**
```python
# Futures dispatch: use FMP commodity symbol with IBKR fallback
# Normalize ticker for lookup — instrument_types keys are uppercase (from to_portfolio_data)
_key = str(ticker or "").strip().upper()
if instrument_types and str(instrument_types.get(_key, "")).strip().lower() == "futures":
    return _latest_futures_price(
        ticker, currency=currency, fmp_ticker=fmp_ticker, fmp_ticker_map=fmp_ticker_map,
    )
```

**New helper `_latest_futures_price()`** in same file:
```python
def _latest_futures_price(
    ticker: str,
    *,
    currency: str | None = None,
    fmp_ticker: str | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
) -> float:
    """Fetch latest price for a futures ticker via the pluggable pricing chain.

    Symbol resolution priority:
    1. Explicit fmp_ticker / fmp_ticker_map override (caller knows best)
    2. Contract spec fmp_symbol (from contracts.yaml)
    Note: raw ticker is NOT used as FMP fallback (avoids Z collision risk).
    """
    from brokerage.futures import get_contract_spec
    from brokerage.futures.pricing import get_default_pricing_chain

    spec = get_contract_spec(ticker)

    # Resolve FMP symbol: explicit override > contract spec (NO raw ticker fallback)
    # Check for explicit override first (fmp_ticker or fmp_ticker_map entry)
    has_explicit_override = bool(fmp_ticker) or bool((fmp_ticker_map or {}).get(ticker))
    if has_explicit_override:
        resolved_fmp = select_fmp_symbol(ticker, fmp_ticker=fmp_ticker, fmp_ticker_map=fmp_ticker_map)
    else:
        resolved_fmp = spec.fmp_symbol if spec else None

    # Fetch price through the pricing chain (FMP → IBKR by default)
    chain = get_default_pricing_chain()
    raw_price = chain.fetch_latest_price(ticker, alt_symbol=resolved_fmp)

    # FX conversion: explicit currency > contract spec > assume USD
    effective_currency = currency or (spec.currency if spec else None)
    if effective_currency and effective_currency.upper() != "USD":
        try:
            fx = get_fx_provider()
            if fx is not None:
                raw_price = raw_price * float(fx.get_fx_rate(effective_currency))
        except Exception:
            pass

    return raw_price
```

### 2. `get_returns_dataframe()` — `portfolio_risk_engine/portfolio_risk.py:459`

**Already accepts `instrument_types`** (line 466). Already uses it for currency auto-detection (lines 563-573).

**Change:** Before the FMP price fetch (lines 541-555), add a futures dispatch branch:

```python
for t in weights:
    try:
        # Futures dispatch: use FMP commodity symbol with IBKR fallback
        _key = str(t or "").strip().upper()
        is_futures = instrument_types and str(instrument_types.get(_key, "")).strip().lower() == "futures"

        if is_futures:
            prices = _fetch_futures_prices(t, start_date, end_date, fmp_ticker_map=fmp_ticker_map)
        else:
            # Existing FMP path (unchanged)
            try:
                prices = fetch_monthly_total_return_price(...)
            except Exception:
                prices = fetch_monthly_close(...)
```

**New helper `_fetch_futures_prices()`** in same file:
```python
def _fetch_futures_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> pd.Series:
    """Fetch monthly close prices for a futures ticker via the pluggable pricing chain.

    Symbol resolution: fmp_ticker_map override > contract spec fmp_symbol.
    Raw ticker is NOT used as FMP fallback (avoids Z collision risk).
    """
    from brokerage.futures import get_contract_spec
    from brokerage.futures.pricing import get_default_pricing_chain

    spec = get_contract_spec(ticker)

    # Resolve FMP symbol: explicit map > contract spec (NO raw ticker fallback)
    fmp_symbol = (fmp_ticker_map or {}).get(ticker)
    if not fmp_symbol and spec and spec.fmp_symbol:
        fmp_symbol = spec.fmp_symbol

    # Fetch through the pricing chain (FMP → IBKR by default)
    chain = get_default_pricing_chain()
    return chain.fetch_monthly_close(ticker, start_date, end_date, alt_symbol=fmp_symbol)
```

### 3. `instrument_types` Threading — All Call Chains

`latest_price()` and `get_returns_dataframe()` are the two core dispatch points. But `instrument_types` must be threaded through all intermediate functions that call them. This is the bulk of the work.

#### 3A. `price_fetcher` Lambda Sites — Grep-and-Fix Pattern

Every site that constructs a `price_fetcher = lambda t: latest_price(...)` must add `instrument_types=instrument_types` to the `latest_price()` call.

**Implementation:** Run `grep -rn "latest_price(" portfolio_risk_engine/ core/ services/` to find ALL call sites. For each, add `instrument_types` threading. This includes both lambda sites and direct calls.

**Known sites** (at time of plan writing):

| File | Lines | Context |
|------|-------|---------|
| `portfolio_config.py` | ~345 | `load_portfolio_config()` |
| `config_adapters.py` | ~46 | `resolve_portfolio_config()` — most MCP tool path |
| `optimization.py` | ~84, ~170 | Min-var and max-return paths |
| `performance_analysis.py` | ~90 | `analyze_performance()` |
| `portfolio_risk_score.py` | ~1775 | Risk score path |
| `scenario_analysis.py` | ~122 | Scenario analysis path |
| `core/portfolio_analysis.py` | ~97, ~103 | `analyze_portfolio()` |
| `services/portfolio_service.py` | ~913 | Direct call in holdings loop — see note below |

**`portfolio_service.py` special case:** This site loops over holdings and calls `latest_price(ticker, fmp_ticker=fmp_ticker)` directly — no `config` dict in scope. The raw holding `type` field may be `"derivative"` (not `"futures"`), so we cannot just copy it. Replicate the same detection logic that `to_portfolio_data()` uses — derivative type + known futures symbol intersection:
```python
from ibkr.compat import get_ibkr_futures_exchanges
known_futures = get_ibkr_futures_exchanges()
instrument_types = {}
for h in holdings:
    ticker = str(h.get("ticker") or "").strip().upper()
    if str(h.get("type") or "").strip().lower() == "derivative" and ticker in known_futures:
        instrument_types[ticker] = "futures"
```
Then pass `instrument_types=instrument_types` to the `latest_price()` call. This mirrors `to_portfolio_data()` line ~620–629 exactly.

**All other sites follow the same pattern:**
```python
instrument_types = config.get("instrument_types")
price_fetcher = lambda t: latest_price(
    t,
    fmp_ticker_map=fmp_ticker_map,
    currency=currency_map.get(t) if currency_map else None,
    instrument_types=instrument_types,
)
```

**Note:** `config_adapters.py:resolve_portfolio_config()` is the most critical — it's the path used by all MCP tools via `_load_portfolio_for_analysis()`. The config dict already includes `instrument_types` from `PortfolioData` (line 39).

#### 3B. `_filter_tickers_by_data_availability()` — `portfolio_risk.py:397`

This prefilter function calls `fetch_monthly_close()` for each ticker to check data availability. Currently does NOT accept `instrument_types`, so futures tickers will fail the FMP equity lookup and be excluded before reaching `get_returns_dataframe()`.

**Change:** Add `instrument_types` parameter. When a ticker is futures, use `_fetch_futures_prices()` instead of `fetch_monthly_close()`.

#### 3C. `build_portfolio_view()` Call Sites — Grep-and-Fix Pattern

`build_portfolio_view()` already accepts `instrument_types` and threads it to `get_returns_dataframe()`. The gap is at the many call sites that don't pass it.

**Implementation:** Run `grep -rn "build_portfolio_view(" portfolio_risk_engine/ core/ services/` to find ALL call sites. For each, add `instrument_types=config.get("instrument_types")` (or equivalent from available context).

**Important:** Many `build_portfolio_view()` call sites are inside functions that do NOT currently accept `instrument_types`. The grep-and-fix must walk UP the call chain — not just fix the leaf call, but add `instrument_types` to every parent function signature along the way, following the existing `fmp_ticker_map` threading pattern.

**Known `build_portfolio_view()` call sites** (at time of plan writing — use grep to verify):

| File | Lines | Count |
|------|-------|-------|
| `portfolio_optimizer.py` | ~128, ~230, ~519, ~805, ~819, ~1137, ~1307 | 7 |
| `portfolio_risk_score.py` | ~1805 | 1 |
| `scenario_analysis.py` | ~151 | 1 |
| `services/factor_intelligence_service.py` | ~1014 | 1 |

**Full optimizer/scenario parent function chain (verified against code):**

These are all the functions that need `instrument_types: dict[str, str] | None = None` added alongside their existing `fmp_ticker_map` parameter:

*portfolio_optimizer.py — low-level functions (contain `build_portfolio_view()` calls):*

| Function | Line | Contains `build_portfolio_view()` calls |
|----------|------|----------------------------------------|
| `simulate_portfolio_change()` | ~101 | Yes |
| `solve_min_variance_with_risk_limits()` | ~155 | Yes |
| `evaluate_weights()` | ~504 | Yes |
| `solve_max_return_with_risk_limits()` | ~1058 | Yes |

*portfolio_optimizer.py — mid-level wrappers (call the above, need param threaded):*

| Function | Line | Calls |
|----------|------|-------|
| `run_what_if()` | ~419 | → `simulate_portfolio_change()` |
| `run_what_if_scenario()` | ~691 | → `run_what_if()` |
| `run_min_var_optimiser()` | ~876 | → `solve_min_variance_with_risk_limits()`, `evaluate_weights()` |
| `run_min_var()` | ~948 | → `run_min_var_optimiser()` |
| `run_max_return_portfolio()` | ~1272 | → `solve_max_return_with_risk_limits()`, `evaluate_weights()` |

*optimization.py — top-level entry points (MCP tools call these):*

| Function | Line | Calls |
|----------|------|-------|
| `optimize_min_variance()` | ~48 | → `run_min_var()` (via config) |
| `optimize_max_return()` | ~135 | → `run_max_return_portfolio()` (via config) |

*scenario_analysis.py — top-level entry point:*

| Function | Line | Calls |
|----------|------|-------|
| `analyze_scenario()` | ~43 | → `run_what_if_scenario()` (via config) |

**Threading approach by function tier:**

- **Top-level entry points** (`optimize_min_variance`, `optimize_max_return`, `analyze_scenario`): These accept `PortfolioData` and extract `fmp_ticker_map` from the resolved `config` dict internally (via `resolve_portfolio_config()`). `instrument_types` is already in the config dict (populated by `to_portfolio_data()`). No signature change needed — just extract `instrument_types = config.get("instrument_types")` alongside the existing `fmp_ticker_map = config.get("fmp_ticker_map")` and thread it down.

- **Mid-level wrappers with `config` dict** (`run_what_if_scenario`, `run_min_var`, `run_max_return_portfolio`): Already receive `config` as a parameter. Extract `instrument_types` from it.

- **Low-level functions with explicit params** (`simulate_portfolio_change`, `solve_min_variance_with_risk_limits`, `evaluate_weights`, `run_min_var_optimiser`, `solve_max_return_with_risk_limits`, `run_what_if`): These accept `fmp_ticker_map` as an explicit parameter. Add `instrument_types: dict[str, str] | None = None` alongside it.

#### 3D. `calculate_portfolio_performance_metrics()` — `portfolio_risk.py:1508`

Add `instrument_types` param, thread to both `_filter_tickers_by_data_availability()` and `get_returns_dataframe()`. Update ALL callers:

| Caller | File | Line |
|--------|------|------|
| `analyze_performance()` | `performance_analysis.py` | ~110 |
| Factor performance profiling | `core/factor_intelligence.py` | ~1331, ~1400, ~1412 |

### 4. `to_portfolio_data()` — `portfolio_risk_engine/data_objects.py`

**Change:** When building `fmp_ticker_map` for futures positions, populate from contract spec's `fmp_symbol`. Currently, futures positions from IBKR don't have an `fmp_ticker` field on the position dict — the mapping lives in `exchange_mappings.yaml`.

**Issue:** The `instrument_types` dict is built AFTER the position loop (line ~617), so it's not available during the loop where `fmp_ticker_map` is populated.

**Fix:** Second pass after `instrument_types` is built (option b — simpler and less invasive):
```python
# After instrument_types auto-detection (line ~617), before PortfolioData construction:
# Populate fmp_ticker_map for futures from contract specs
if instrument_types:
    from brokerage.futures import get_contract_spec
    for t, itype in instrument_types.items():
        if itype == "futures" and t not in fmp_ticker_map:
            spec = get_contract_spec(t)
            if spec and spec.fmp_symbol:
                fmp_ticker_map[t] = spec.fmp_symbol
```

## Z Ticker Collision

Z is both Zillow (equity) and FTSE 100 futures. The `instrument_types` guard handles this:
- If `instrument_types["Z"] == "futures"` → dispatched to futures pricing
- If `instrument_types` is None or `instrument_types["Z"] == "equity"` → existing FMP equity path

The auto-detection in `to_portfolio_data()` already handles this — positions from IBKR with derivative type guards produce `instrument_types["Z"] = "futures"` when it's actually a futures position. Manual YAML portfolios need explicit `instrument_types: {Z: futures}` in the config.

## Currency Auto-Detection

Already implemented in `get_returns_dataframe()` (lines 563-573). The existing logic:
```python
if not currency and instrument_types:
    instrument_type = str(instrument_types.get(t) or "").strip().lower()
    if instrument_type == "futures":
        from ibkr.compat import get_futures_currency
        inferred = str(get_futures_currency(t) or "").strip().upper()
        if inferred and inferred != "USD":
            currency = inferred
```

This already works for returns FX-adjustment. The same pattern extends to `latest_price()` via `_latest_futures_price()` which reads `spec.currency`.

## FMP Commodity Symbol Behavior

FMP commodity symbols (e.g., `GCUSD`, `ESUSD`, `CLUSD`) return prices via the same `/historical-price-eod/full` endpoint as equities. No special endpoint needed — just use the FMP symbol as the ticker in `fetch_monthly_close()`.

For international index futures (e.g., `^N225`, `^STOXX50E`, `^GDAXI`), FMP uses index symbols with `^` prefix. These also work via the standard endpoint.

**Verification needed:** Confirm that FMP returns data for these symbols. If not, IBKR fallback handles it.

## Backward Compatibility

- `latest_price()` — new `instrument_types` kwarg with `None` default. All existing callers unchanged.
- `get_returns_dataframe()` — already accepts `instrument_types`. No signature change.
- `_filter_tickers_by_data_availability()` — new `instrument_types` kwarg with `None` default. Internal function; update all callers in same file.
- `calculate_portfolio_performance_metrics()` — new `instrument_types` kwarg with `None` default. Internal function; update callers.
- `to_portfolio_data()` — internal change only, no signature change.
- All `price_fetcher` lambda sites (8 files, some with paired if/else branches — use grep to find all) — internal changes only, extract `instrument_types` from config dict that already contains it.
- `build_portfolio_view()` call sites — add `instrument_types` kwarg to existing calls (already accepted by the function).

## Tests

### Step 0 Tests (`tests/brokerage/futures/test_pricing_chain.py`)

1. **`test_pricing_chain_first_source_succeeds`** — First source returns price, second not called
2. **`test_pricing_chain_fallback_to_second`** — First source fails, second succeeds
3. **`test_pricing_chain_all_fail`** — All sources fail → ValueError
4. **`test_pricing_chain_add_source`** — Register new source, verify it's tried
5. **`test_fmp_source_uses_fmp_symbol`** — FMP source uses `fmp_symbol` param, not raw ticker
6. **`test_ibkr_source_uses_raw_symbol`** — IBKR source uses raw IBKR symbol
7. **`test_contract_specs_from_yaml`** — `load_contract_specs()` loads from `contracts.yaml`, not IBKR
8. **`test_contract_specs_count`** — Still 27 contracts after migration
9. **`test_ibkr_compat_delegates`** — `get_ibkr_futures_contract_meta()` delegates to `brokerage.futures`
10. **`test_fmp_source_no_raw_fallback`** — FMP source returns None when `fmp_symbol` is None (no raw ticker fallback)
11. **`test_ibkr_compat_fmp_map_parity`** — `get_ibkr_futures_fmp_map()` output matches contract spec `fmp_symbol` for all IBKR-routable symbols
12. **`test_ibkr_compat_intersection`** — `get_ibkr_futures_contract_meta()` only returns IBKR-routable symbols (intersection with `get_ibkr_futures_exchanges()`)
13. **`test_get_futures_currency_unknown_symbol`** — `get_futures_currency("UNKNOWN")` returns `"USD"` (preserves default-safe fallback)
14. **`test_fmp_source_normalizes_minor_currency`** — FMP source applies `normalize_fmp_price()` for GBp → GBP

### Step 1-3 Tests (`tests/portfolio_risk_engine/test_futures_pricing.py`)

1. **`test_latest_price_futures_dispatch`** — Mock `fetch_monthly_close` with FMP commodity symbol, verify `latest_price()` routes correctly when `instrument_types={"ES": "futures"}`
2. **`test_latest_price_futures_ibkr_fallback`** — Mock FMP failure, verify IBKR fallback via `fetch_ibkr_monthly_close()`
3. **`test_latest_price_futures_fx_conversion`** — Non-USD futures (e.g., NIY in JPY), verify FX conversion applied
4. **`test_latest_price_no_instrument_types`** — Verify existing behavior unchanged when `instrument_types=None`
5. **`test_latest_price_equity_with_instrument_types`** — Verify equities still use FMP path even when `instrument_types` present
6. **`test_latest_price_z_ticker_collision`** — `instrument_types={"Z": "futures"}` routes to futures; without it, routes to FMP equity
7. **`test_fetch_futures_prices_fmp_first`** — FMP commodity symbol used first
8. **`test_fetch_futures_prices_ibkr_fallback`** — FMP fails → IBKR fallback
9. **`test_fetch_futures_prices_both_fail`** — Both fail → ValueError
10. **`test_get_returns_dataframe_futures_dispatch`** — Mock prices, verify futures ticker dispatched correctly
11. **`test_to_portfolio_data_futures_fmp_map`** — Verify `fmp_ticker_map` populated from contract specs for futures positions
12. **`test_filter_tickers_futures_not_excluded`** — Futures ticker not excluded by `_filter_tickers_by_data_availability()` when `instrument_types` is passed
13. **`test_calc_perf_metrics_futures_threading`** — `calculate_portfolio_performance_metrics()` with `instrument_types` threads to `get_returns_dataframe()`

### Integration Smoke Test (manual)

1. Load a portfolio YAML with `instrument_types: {ES: futures, NQ: futures}`
2. Verify `latest_price("ES", instrument_types={"ES": "futures"})` returns a price
3. Verify `get_returns_dataframe({"ES": 0.5, "SPY": 0.5}, ..., instrument_types={"ES": "futures"})` returns aligned returns

## Files Changed

### Step 0: Decoupling

| File | Change |
|------|--------|
| `brokerage/futures/contracts.yaml` | **New.** Canonical contract catalog (27 contracts). |
| `brokerage/futures/contract_spec.py` | `load_contract_specs()` reads from `contracts.yaml` instead of `ibkr.compat`. |
| `brokerage/futures/pricing.py` | **New.** `FuturesPriceSource` protocol + `FuturesPricingChain` + `get_default_pricing_chain()`. |
| `brokerage/futures/sources/__init__.py` | **New.** Package init. |
| `brokerage/futures/sources/fmp.py` | **New.** `FMPFuturesPriceSource`. |
| `brokerage/futures/sources/ibkr.py` | **New.** `IBKRFuturesPriceSource`. |
| `brokerage/futures/__init__.py` | Add pricing chain exports. |
| `ibkr/exchange_mappings.yaml` | Remove `multiplier`, `tick_size` from `ibkr_futures_exchanges`. Remove `ibkr_futures_to_fmp` (now in contracts.yaml). |
| `ibkr/compat.py` | `get_ibkr_futures_contract_meta()`, `get_ibkr_futures_fmp_map()` delegate to `brokerage.futures`. |
| `tests/brokerage/futures/test_contract_spec.py` | Update to reflect new YAML source. |
| `tests/brokerage/futures/test_pricing_chain.py` | **New.** Tests for pricing chain, source registration, fallback behavior. |

### Step 1-3: Dispatch + Threading

| File | Change |
|------|--------|
| `portfolio_risk_engine/portfolio_config.py` | Add `instrument_types` to `latest_price()`. Add `_latest_futures_price()` helper (uses pricing chain). Thread in `load_portfolio_config()` lambda. |
| `portfolio_risk_engine/portfolio_risk.py` | Add `_fetch_futures_prices()` helper (uses pricing chain). Add futures dispatch in `get_returns_dataframe()`, `_filter_tickers_by_data_availability()`, `calculate_portfolio_performance_metrics()`. |
| `portfolio_risk_engine/config_adapters.py` | Thread `instrument_types` into lambda + `standardize_portfolio_input()`. |
| `portfolio_risk_engine/optimization.py` | Thread `instrument_types` into lambdas (~84, ~170). |
| `portfolio_risk_engine/performance_analysis.py` | Thread `instrument_types` into lambda, `calculate_portfolio_performance_metrics()` call. |
| `portfolio_risk_engine/portfolio_risk_score.py` | Thread `instrument_types` into lambda, `build_portfolio_view()` call. |
| `portfolio_risk_engine/scenario_analysis.py` | Thread `instrument_types` into lambda, `build_portfolio_view()` call. |
| `portfolio_risk_engine/portfolio_optimizer.py` | Thread `instrument_types` into all `build_portfolio_view()` calls. |
| `core/portfolio_analysis.py` | Thread `instrument_types` into lambda (~97, ~103). |
| `services/factor_intelligence_service.py` | Thread `instrument_types` into `build_portfolio_view()` call (~1014). |
| `services/portfolio_service.py` | Thread `instrument_types` into direct `latest_price()` call (~913). |
| `core/factor_intelligence.py` | Thread `instrument_types` into `calculate_portfolio_performance_metrics()` calls (~1331, ~1400, ~1412). |
| `portfolio_risk_engine/data_objects.py` | Populate `fmp_ticker_map` from contract specs for futures in `to_portfolio_data()`. |
| `tests/portfolio_risk_engine/test_futures_pricing.py` | **New.** ~11 tests for dispatch + threading. |

## Estimated Scope

- **Step 0:** ~200 lines new code (pricing chain, sources, YAML) + ~100 lines tests + ~50 lines refactored
- **Steps 1-3:** ~150 lines new code (helpers + dispatch) + ~200 lines tests + ~20 mechanical threading one-liners

## Dependencies

- Phase 1 complete (contract specs, `get_contract_spec()`, `fmp_symbol` field) ✅
- `ibkr.compat.fetch_ibkr_monthly_close()` available ✅
- `ibkr.compat.get_futures_currency()` available ✅
- FMP commodity symbols mapped in `exchange_mappings.yaml` ✅ (will move to `contracts.yaml`)

## Open Questions

1. **FMP commodity data quality** — Do all 27 FMP symbols return reliable monthly data? Need to verify, especially international indices (`^N225`, `^STOXX50E`, `^GDAXI`, `^HSI`, `^BVSP`). If not, IBKR fallback covers it.
2. **FMP commodity price units** — Are FMP commodity prices in the native currency (e.g., GBp for FTSE) or USD? Need to verify to avoid double-conversion. Plan includes `normalize_fmp_price()` + `fetch_fmp_quote_with_currency()` in the **FMP price source adapter** (`brokerage/futures/sources/fmp.py`) to handle this correctly regardless. Note: `normalize_fmp_price()` has a pre-existing bug where `normalize_currency()` aliases GBX→GBP before the minor-currency division check, so GBX prices would NOT be divided by 100. This doesn't affect any current futures contract (none return GBX from FMP), but should be fixed in `_ticker.py` if GBX-priced instruments are added later.
3. **`^` prefix handling** — **Verified OK.** FMP client sends symbols as query params via `requests`, which URL-encodes automatically. `^N225` will work.

## Codex Review Findings (R1)

1. **7 `price_fetcher` lambda sites + downstream threading** — Plan originally only covered `load_portfolio_config()`. Codex R1 identified 4 additional lambda sites. R2 found the second optimization lambda and `scenario_analysis.py`. R3 identified deeper threading gaps: `calculate_portfolio_performance_metrics()`, `build_portfolio_view()` call sites, and `portfolio_optimizer.py`. All now covered.
2. **`_filter_tickers_by_data_availability()` prefilter** — Function excludes tickers that fail FMP equity lookup before `get_returns_dataframe()` runs. Futures would be excluded before the dispatch branch runs. Now included as dispatch point #4.
3. **`fmp_ticker`/`fmp_ticker_map` override plumbing** — Futures helpers originally ignored existing symbol override infrastructure. `_latest_futures_price()` accepts both `fmp_ticker` and `fmp_ticker_map` (matching `latest_price()` signature). `_fetch_futures_prices()` accepts only `fmp_ticker_map` (matching `get_returns_dataframe()` context which operates on multiple tickers with a shared map, not a single `fmp_ticker`). Both fall back to contract spec `fmp_symbol` when no override is provided.
4. **Price unit normalization** — Plan originally assumed FMP commodity prices are in native currency. Codex flagged that equities go through `normalize_fmp_price()` for minor-currency handling (GBp → GBP). FMP price source adapter (`brokerage/futures/sources/fmp.py`) now runs the same normalization via `fetch_fmp_quote_with_currency()` + `normalize_fmp_price()` in its `fetch_latest_price()` method.
5. **`fetch_ibkr_monthly_close(currency=...)` is a no-op** — The `currency` parameter is accepted but ignored (`del currency` on line 118 of `ibkr/compat.py`). FX conversion is handled post-fetch only. Plan updated to not rely on the currency param for IBKR fetches.
