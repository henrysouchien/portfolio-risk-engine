# Provider Extensibility Decoupling — Implementation Plan

> **Date**: 2026-03-20
> **Status**: IMPLEMENTED
> **Audit**: `docs/planning/PROVIDER_EXTENSIBILITY_AUDIT.md` (Codex-reviewed PASS)
> **TODO ref**: `docs/TODO.md` lines 60-76

## Context

The audit found that the provider protocol layer is well-designed (6 Protocols, priority-ordered `ProviderRegistry`) but ~60% of live data calls bypass it via direct `FMPClient()` usage (18 files). Goal: make the codebase truly provider-agnostic so a new provider (Polygon, Yahoo, etc.) plugged into the registry works end-to-end.

This is pure refactoring — no new features, no behavior changes. All existing tests must continue to pass.

---

## Step 1: New Protocols + Registry Slots

**Files**: `providers/interfaces.py`, `providers/registry.py`

Add 3 `@runtime_checkable` Protocol classes to `interfaces.py` (following exact existing pattern — mandatory `provider_name: str`, methods use `...`):

**`ProfileMetadataProvider`**:
- `fetch_profile(symbol: str, *, use_cache: bool = True) -> dict[str, Any] | None` — returns `{symbol, exchange, country, industry, marketCap, isEtf, isFund, companyName, description, sector, currency, price, lastDiv}` or None
- `fetch_batch_profiles(symbols: list[str], *, use_cache: bool = True) -> dict[str, dict[str, Any]]`

**`QuoteProvider`**:
- `fetch_quote(symbol: str, *, use_cache: bool = False) -> tuple[float | None, str | None]` — returns `(price, currency)`
- `fetch_batch_quotes(symbols: list[str], *, use_cache: bool = False) -> dict[str, dict[str, Any]]` — returns `{symbol: {price, currency, change, changesPercentage, volume, marketCap, dayLow, dayHigh, ...}}`. Default `use_cache=False` matches existing live-fetch semantics at bypass sites.

**`SymbolSearchProvider`**:
- `search(query: str, *, limit: int = 10) -> list[dict[str, Any]]` — returns `[{symbol, name, exchange, currency, exchangeShortName}]`

Add to `registry.py`:
- 3 storage fields: `_profile_provider`, `_quote_provider`, `_search_provider` (all `Type | None = None`)
- 6 methods: `register_X_provider(provider)` + `get_X_provider()` (single-instance pattern, with fallback scan of price chain for protocol match — same as treasury/dividend)

**Tests**: `tests/providers/test_interfaces.py` — structural typing tests. `tests/providers/test_registry.py` — register/get tests for each new type.

---

## Step 2: FMP Implementation + Bootstrap Registration

**Files**: New `providers/fmp_metadata.py`, `providers/bootstrap.py`

Create `FMPProfileProvider` implementing all 3 new protocols (multi-protocol class, like `FMPProvider` implements Price+Treasury+Dividend):

```python
class FMPProfileProvider:
    provider_name = "fmp"

    def fetch_profile(self, symbol, *, use_cache=True):
        # Lazy import FMPClient, call fetch_raw("profile", symbol=symbol)
        # Return FULL profile dict: {symbol, exchange, country, industry, marketCap,
        #   isEtf, isFund, companyName, description, sector, currency, price, lastDiv}
        # CANNOT delegate to ticker_resolver.fetch_batch_fmp_profile_metadata() — that
        # only returns {price, currency, sector, company_name, last_div} (5 fields).
        # Must call FMPClient directly for the full profile shape.

    def fetch_batch_profiles(self, symbols, *, use_cache=True):
        # Same: call FMPClient.fetch_raw("profile", symbol=",".join(chunk))
        # Return {symbol: full_profile_dict} with chunking (chunk_size=25)

    def fetch_quote(self, symbol, *, use_cache=False):
        # Calls fetch_batch_quotes([symbol]) internally for consistency
        # Returns (price, currency) tuple

    def fetch_batch_quotes(self, symbols, *, use_cache=False):
        # Two-phase: (1) fetch prices via FMPClient.fetch("quote") for price/change/volume/etc,
        # (2) fetch currency via FMPClient.fetch_raw("profile") batch for currency field.
        # FMP's /quote endpoint does NOT return currency — it must come from /profile.
        # This mirrors how ticker_resolver.fetch_batch_fmp_quotes_with_currency() works
        # (it calls fetch_batch_fmp_profile_metadata for currency, not /quote).
        # Return {symbol: {price, currency, change, changesPercentage, volume,
        #   marketCap, dayLow, dayHigh}} with chunking

    def search(self, query, *, limit=10):
        # Lazy: from utils.ticker_resolver import fmp_search
        # Delegates to fmp_search(query), applies limit
```

Key design note: `fetch_profile`/`fetch_batch_profiles` CANNOT delegate to `ticker_resolver.fetch_batch_fmp_profile_metadata()` because that function only returns a 5-field snapshot (`{price, currency, sector, company_name, last_div}`). Steps 3, 7, 8 need the full profile shape (exchange, country, industry, marketCap, isEtf, isFund, etc.). The FMP implementation must call `FMPClient.fetch_raw("profile")` directly for full field coverage, using lazy imports to preserve startup performance.

`search` can delegate to existing `ticker_resolver.fmp_search()` (preserves caching). `fetch_quote` delegates to `fetch_batch_quotes` internally (two-phase: `/quote` for prices + `/profile` for currency, matching how `ticker_resolver.fetch_batch_fmp_quotes_with_currency()` works).

`ticker_resolver.py` remains for backward compat but callers migrate to the registry over Steps 3-20.

Register in `bootstrap.py`:
```python
fmp_profile = FMPProfileProvider()
registry.register_profile_provider(fmp_profile)
registry.register_quote_provider(fmp_profile)
registry.register_search_provider(fmp_profile)
```

**Tests**: `tests/providers/test_fmp_metadata.py` — structural typing, delegation verification via monkeypatch. `tests/providers/test_registry_parity.py` — assert `get_profile/quote/search_provider()` not None.

---

## Step 3: Route `proxy_builder.py` Through Registry (Eliminate Raw HTTP)

**Files**: `core/proxy_builder.py`

Replace the raw HTTP `fetch_profile()` function (lines 299-366) that calls `requests.get(financialmodelingprep.com/stable/profile)`:
- Remove `import requests`, `FMP_API_KEY = os.getenv(...)`, `BASE_URL` constants
- Rewrite to: `get_registry().get_profile_provider().fetch_profile(ticker)`
- Keep `@cache_company_profile` LFU decorator and return dict shape unchanged
- Provider returns superset; caller picks what it needs

**Verify**: `pytest tests/ -k proxy_builder -v`

---

## Step 4: Route `_ticker.py` Currency/Quote Through Registry

**Files**: `portfolio_risk_engine/_ticker.py`

Replace `_infer_fmp_currency_cached` (line 17: `FMPClient().fetch_raw("profile")`):
- Change to: `get_registry().get_profile_provider().fetch_profile(symbol)` → extract `["currency"]`
- Keep `@lru_cache(maxsize=256)` and raise-on-failure (so LRU doesn't cache failures)

Replace `fetch_fmp_quote_with_currency` (lines 86-103):
- Change to: `get_registry().get_quote_provider().fetch_quote(symbol)`
- Keep instrument_type guard (return None,None for futures/derivative)

**Verify**: `pytest tests/ -k ticker -v`

---

## Step 5: Route `get_spot_price()` + Rename `filter_fmp_eligible`

**Files**: `providers/price_service.py`

Line 86: Replace `fetch_fmp_quote_with_currency(fmp_symbol)` with `get_registry().get_quote_provider().fetch_quote(fmp_symbol)`.

Rename `filter_fmp_eligible` → `filter_price_eligible` (the function filters by instrument_type, nothing FMP-specific). Keep `filter_fmp_eligible = filter_price_eligible` alias for backward compat.

**Verify**: `pytest tests/ -k "price_service or spot_price" -v`

---

## Step 6: Route `performance_metrics_engine.py` Daily Close Through Registry

**Files**: `portfolio_risk_engine/performance_metrics_engine.py`

Line 21: Replace direct `from fmp.compat import fetch_daily_close` with a registry-backed helper:
```python
def _fetch_daily_close_via_registry(symbol, start_date=None, fmp_ticker_map=None, **kw):
    chain = get_registry().get_price_chain("equity")
    for provider in chain:
        try:
            result = provider.fetch_daily_close(symbol, start_date, None, fmp_ticker_map=fmp_ticker_map, **kw)
            if result is not None and not result.empty:
                return result
        except Exception:
            continue
    return pd.Series(dtype=float)
```

Replace call at line 326 (`compute_recent_returns`).

**Verify**: `pytest tests/ -k performance_metrics -v`

---

## Step 7: Route `portfolio_risk.py` Sector Mapping Through Registry

**Files**: `portfolio_risk_engine/portfolio_risk.py`

Lines 2272-2306: Replace `FMPClient()` sector mapping with:
```python
provider = get_registry().get_profile_provider()
if provider:
    profiles = provider.fetch_batch_profiles(unique_symbols)
    for sym, profile in profiles.items():
        sector = (profile or {}).get("sector")
        if sector:
            symbol_to_sector[sym] = sector
```

Remove `FMPClient` import, `FMP_API_KEY` gate, `ThreadPoolExecutor` (batch is handled by provider).

**Verify**: `pytest tests/ -k "portfolio_risk and sector" -v`

---

## Step 8: Route `trading_analysis/analyzer.py` Through Registry

**Files**: `trading_analysis/analyzer.py`

Two bypass sites in this file:

1. Lines 432-448 (`_fetch_fmp_company_name`): Replace `_get_fmp_client().fetch_raw("profile")` with:
```python
provider = get_registry().get_profile_provider()
if provider is None:
    return None
profile = provider.fetch_profile(ticker)
name = (profile or {}).get("companyName") or (profile or {}).get("name")
```
Keep `_fmp_name_cache` instance-level caching.

2. Line 414 (`_warm_symbol_name_lookup`): Uses `fetch_batch_fmp_profile_metadata()` for batch company-name warming. Replace with `get_registry().get_profile_provider().fetch_batch_profiles(symbols)` and extract `companyName` from each profile.

Remove `_get_fmp_client()`, `from fmp.client import FMPClient`, and `from utils.ticker_resolver import fetch_batch_fmp_profile_metadata` if no other callers remain.

**Verify**: `pytest tests/ -k analyzer -v`

---

## Step 9: Clean Dead Code

**Files**: `portfolio_risk_engine/factor_utils.py`

Delete lines 53-55 (dead `FMP_API_KEY`, `API_KEY`, `BASE_URL` constants — never referenced). Remove `import os` if unused after deletion.

**Verify**: `pytest tests/ -k factor_utils -v`

---

## Step 10: Config-Driven Price Provider Stack

**Files**: `providers/bootstrap.py`, `core/realized_performance/pricing.py`, `settings.py`

Add `PRICE_PROVIDERS` env var + factory pattern to `bootstrap.py`:
```python
_PRICE_PROVIDER_FACTORIES = {
    "fmp": _register_fmp,
    "ibkr": _register_ibkr,
    "bs": _register_bs,
}

def _parse_price_providers():
    env = os.getenv("PRICE_PROVIDERS", "").strip()
    if env:
        return [n.strip().lower() for n in env.split(",") if n.strip()]
    return ["fmp", "ibkr", "bs"]  # Default
```

Each factory function encapsulates registration of its provider + dependencies. `build_default_registry()` iterates the parsed list.

In `core/realized_performance/pricing.py`: Replace `_build_default_price_registry()` (lines 63-104) with delegation to `providers.bootstrap.build_default_registry()`, preserving monkeypatch-compatible test shim behavior for overridden fetchers.

**Tests**: `tests/providers/test_bootstrap_config.py` — default stack, custom `PRICE_PROVIDERS`, unknown names skipped, empty uses default.

**Verify**: `pytest tests/providers/ -v && pytest tests/ -k realized_performance -v`

---

## Step 11: Route `services/stock_service.py` Through Registry

**Files**: `services/stock_service.py`

Replace generic FMP calls (search/profile/quote) with registry providers:
- Line 223 (`search_stocks`): `self.fmp_client.fetch_raw("search")` → `get_registry().get_search_provider().search(query, limit=limit)` + `get_registry().get_quote_provider().fetch_batch_quotes(symbols)` for enrichment
- Line 335 (`_enrich_stock_data_from_fmp`): profile fetch → `get_registry().get_profile_provider().fetch_profile(ticker)`
- Line 352: quote fetch → `get_registry().get_quote_provider().fetch_batch_quotes([ticker])`

Keep `self.fmp_client` for FMP-native analytics (ratios_ttm, historical_price_adjusted, peers, technical — Category C).

**Verify**: `pytest tests/ -k stock_service -v`

---

## Step 12: Route `services/portfolio_service.py` Through Registry

**Files**: `services/portfolio_service.py`

- Line 1560: `fetch_batch_fmp_profile_metadata()` → `get_registry().get_profile_provider().fetch_batch_profiles(symbols)`. **Key**: caller at lines 1566-1568 expects snake_case keys (`sector`, `company_name`, `last_div`). The protocol returns camelCase (`companyName`, `lastDiv`). The FMP implementation must normalize to snake_case, OR add a thin adapter in this file. Preferred: normalize in `FMPProfileProvider.fetch_batch_profiles()` — return both forms or use snake_case consistently in the protocol dict.
- Line 1734: quote fetch → `get_registry().get_quote_provider().fetch_batch_quotes(symbols)`
- Lines 1757, 1917, 1930, 1943: FMP-native (historical_price_eod, price_target_consensus, analyst endpoints) — leave as-is

**Verify**: `pytest tests/ -k portfolio_service -v`

---

## Step 13: Route `services/position_service.py` Through Registry

**Files**: `services/position_service.py`

- Line 1532: `fetch_batch_fmp_latest_prices()` → `get_registry().get_quote_provider().fetch_batch_quotes()` + extract prices
- Line 1543: `fetch_batch_fmp_quotes_with_currency()` → same quote provider

**Verify**: `pytest tests/ -k position_service -v`

---

## Step 14: Route `services/agent_building_blocks.py` Dividends Through Registry

**Files**: `services/agent_building_blocks.py`

- Line 547 (`fetch_fmp_data`): FMP passthrough — leave as-is (Category C)
- Line 567 (`get_dividend_history`): `FMPClient().fetch("dividends")` → `get_registry().get_dividend_provider().fetch_dividend_history(ticker)`. DividendProvider protocol already exists.

**Verify**: `pytest tests/ -k agent_building -v`

---

## Step 15: Route `mcp_tools/quote.py` Through QuoteProvider

**Files**: `mcp_tools/quote.py`

Line 36: `FMPClient().fetch("quote")` → `get_registry().get_quote_provider().fetch_batch_quotes(normalized)`. Transform returned dict into existing response shape. Remove `FMPClient` import.

**Verify**: `pytest tests/ -k quote -v`

---

## Step 16: Route `mcp_tools/trading_helpers.py` Through Registry

**Files**: `mcp_tools/trading_helpers.py`

Change `fetch_current_prices` signature: `client: Optional[FMPClient] = None` → `profile_provider=None`.
- Default resolution: `profile_provider = profile_provider or get_registry().get_profile_provider()`
- Replace `client.fetch("profile", symbol=ticker)` → `profile_provider.fetch_profile(ticker)`
- Extract `profile.get("price")`
- Remove `FMPClient` import

Update all callers that pass `client=` to pass `profile_provider=` instead.

**Verify**: `pytest tests/ -k trading_helpers -v`

---

## Step 17: Route `mcp_tools/baskets.py` Through Registry (Ships with Steps 16, 18, 20)

**Files**: `mcp_tools/baskets.py`

Change `client: FMPClient` parameter threading to `profile_provider` at ALL sites:
- `_fetch_profile(profile_provider, ticker, use_cache)` → `profile_provider.fetch_profile(ticker, use_cache=use_cache)`
- `_validate_tickers`, `_resolve_market_cap_weights`, `_resolve_weights` — pass `profile_provider` through
- Lines 507, 604, 664, 893: all `client = FMPClient()` → `profile_provider = get_registry().get_profile_provider()`
- Line 1053: `FMPClient()` for `etf_holdings` — this is FMP-native (no generic protocol for ETF holdings). Keep as lazy `FMPClient` import for this call only. Do NOT remove `FMPClient` import entirely — move to lazy import inside the ETF holdings function.

**Verify**: `pytest tests/ -k basket -v`

---

## Step 18: Route `mcp_tools/basket_trading.py` Through Registry (Ships with Steps 16, 17)

**Files**: `mcp_tools/basket_trading.py`

Line 305: `client = FMPClient()` → `profile_provider = get_registry().get_profile_provider()`. Pass to `_resolve_weights` and `fetch_current_prices` (updated in Steps 16-17). Remove `FMPClient` import.

**Steps 16-18 + 20 MUST ship together** — Step 17 changes `_resolve_weights()` signature in `baskets.py`, which is called from `factor_intelligence.py` (Step 20) and `basket_trading.py` (Step 18). All callers must update simultaneously.

**Verify**: `pytest tests/ -k "basket_trading or baskets or trading_helpers" -v`

---

## Step 19: Route `mcp_tools/income.py` Through Registry

**Files**: `mcp_tools/income.py`

- `_get_minor_divisors(positions, client, use_cache)`: The `client` param IS used — line 182 calls `client.fetch("profile", symbol=",".join(chunk))` for bulk currency inference. Replace with `get_registry().get_profile_provider().fetch_batch_profiles(chunk)` and extract currency from returned dicts. Remove `client` parameter from the function signature.
- Calendar entries (`client.fetch("dividends_calendar")`): FMP-native — keep as lazy `FMPClient` import only for this call.
- Remove top-level `from fmp.client import get_client`. Update all callers of `_get_minor_divisors` to stop passing `client`.

**Verify**: `pytest tests/ -k income -v`

---

## Step 20: Route `mcp_tools/factor_intelligence.py` Through Registry

**Files**: `mcp_tools/factor_intelligence.py`

Line 106: `client = FMPClient()` passed to `_resolve_weights`. After Step 17, `_resolve_weights` accepts `profile_provider`. Change to `profile_provider = get_registry().get_profile_provider()`. Remove `FMPClient` import.

**Verify**: `pytest tests/ -k factor_intelligence -v`

---

## Step 21: `utils/ticker_resolver.py` Cleanup

**Files**: `utils/ticker_resolver.py`

This file is NOT routed through the registry — it IS the FMP implementation layer that `FMPProfileProvider` delegates to. Changes here are cleanup only:

1. **Do NOT remove** the top-level `from fmp.client import FMPClient` at line 19. Tests monkeypatch `utils.ticker_resolver.FMPClient` (e.g., `tests/services/test_portfolio_service_performance_modes.py:235`). Removing it would break those test patches. Leave it as-is.
2. Add `set_search_client(client)` function for test injection (optional improvement, not required).

After Steps 3-20, most external callers no longer import from `ticker_resolver` directly — they go through the registry. Remaining direct callers are `FMPProfileProvider` (by design) and any Category C FMP-native sites.

**Verify**: `pytest tests/ -k ticker_resolver -v`

---

## Step 22: Document FMP-Native Features (Intentional Coupling)

**Files**: `docs/planning/PROVIDER_EXTENSIBILITY_AUDIT.md`

Update Category C with final list of intentionally-coupled FMP sites remaining after all decoupling. Also reclassify `mcp_tools/news_events.py` from Category B to Category C in the audit doc (it was listed as B #18 but its FMP tool imports are for FMP-native features with no generic equivalent):
- `mcp_tools/news_events.py` — news, estimates, insider, calendar (reclassified from Category B)
- `mcp_tools/__init__.py` — screening, peers, technical, transcripts re-exports
- `services/stock_service.py` — ratios_ttm, historical_price_adjusted, peers, technical
- `services/agent_building_blocks.py:fetch_fmp_data` — generic FMP passthrough
- `services/portfolio_service.py:1757,1917,1930,1943` — historical_price_eod, price_target_consensus, analyst endpoints
- `mcp_tools/income.py` — dividends_calendar endpoint
- `portfolio_risk_engine/factor_utils.py` — fmp.cache.get_timeseries_store

---

## Commit Grouping

| Commit | Steps | Description |
|--------|-------|-------------|
| 1 | 1, 2 | New protocols + FMP implementation + bootstrap registration |
| 2 | 3 | Eliminate raw HTTP in proxy_builder (CRITICAL) |
| 3 | 4, 5 | _ticker.py + get_spot_price + rename filter_fmp_eligible |
| 4 | 6, 9 | performance_metrics_engine daily close + dead code cleanup |
| 5 | 7, 8 | portfolio_risk sector mapping + analyzer company name |
| 6 | 10 | Config-driven provider stack (PRICE_PROVIDERS env var) |
| 7 | 11 | stock_service routing |
| 8 | 12, 13, 14 | portfolio_service + position_service + agent_building_blocks |
| 9 | 15 | quote.py routing |
| 10 | 16, 17, 18, 20 | trading_helpers + baskets + basket_trading + factor_intelligence (shared `_resolve_weights` signature) |
| 11 | 19 | income routing |
| 12 | 21, 22 | ticker_resolver cleanup + documentation |

---

## Risk Mitigation

- **Caching preserved**: `FMPProfileProvider.search` delegates to existing `ticker_resolver.fmp_search()` (TTL cache). `fetch_profile`/`fetch_batch_profiles`/`fetch_quote`/`fetch_batch_quotes` call `FMPClient` directly (full field coverage needed) but callers retain their own caches (`@cache_company_profile` in proxy_builder, `@lru_cache` in _ticker.py, instance-level caches in analyzer/stock_service).
- **No circular deps**: `ticker_resolver.py` does NOT call registry. `FMPProfileProvider` delegates TO it. One-way dependency.
- **Lazy imports**: All new registry usage uses `from providers.bootstrap import get_registry` inside functions (matching existing lazy import pattern).
- **Test isolation**: `monkeypatch.setattr("providers.bootstrap.get_registry", lambda: custom_registry)` — standard pattern already used in test suite.
- **Backward compat**: `filter_fmp_eligible = filter_price_eligible` alias. No public API removals.

## Verification

After all steps: `pytest tests/ -x -q` (full suite, fail-fast). Expected: 0 regressions, ~30 new tests across `test_interfaces.py`, `test_fmp_metadata.py`, `test_bootstrap_config.py`, and updated `test_registry.py`.
