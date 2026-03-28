# Provider-Agnostic Ticker Resolution — TickerResolver Protocol + Rename

## Context

IBKR reports tickers in its own symbology (e.g. `AT`). FMP needs `AT.L`, Bloomberg would need `AT LN Equity`. Currently, the resolution is done via a `fmp_ticker_map: dict[str, str]` threaded through ~130 files. This plan:
1. **Phase 1**: Adds a `TickerResolver` protocol at the provider layer (~20 files)
2. **Phase 2**: Renames remaining FMP-specific naming above the adapter (~110 files) — already Codex-approved at `docs/planning/PROVIDER_AGNOSTIC_TICKER_ALIASING_PLAN.md`

## Architecture: The Adapter Boundary

```
ABOVE THE ADAPTER (services, core, engine — ~110 files)
  Pass fmp_ticker_map: dict[str, str] as portfolio data
  ↓
ADAPTER BOUNDARIES (4 sites)
  _RegistryBackedPriceProvider._normalize_kwargs()      [portfolio_risk_engine/providers.py:53]
  _fetch_price_from_chain()                             [core/realized_performance/pricing.py:125]
  _fetch_daily_close_via_registry()                     [portfolio_risk_engine/performance_metrics_engine.py:22]
  TradingAnalyzer._fetch_group_closes()                  [trading_analysis/analyzer.py:1364,1377]
  Convert: dict → AliasMapResolver(dict) → TickerResolver
  ↓
PROVIDER LAYER (protocol + implementations — ~20 files)
  PriceSeriesProvider protocol receives ticker_resolver: TickerResolver | None
  FMPProvider: resolver.resolve(symbol) → FMP API
  IBKRProvider: ignores resolver (uses contract_identity)
```

## Phase 1: TickerResolver Protocol (~20 files)

### New file: `providers/ticker_resolver.py`

```python
@runtime_checkable
class TickerResolver(Protocol):
    def resolve(self, symbol: str) -> str:
        """Return the data-provider symbol for the given portfolio symbol."""
        ...

class AliasMapResolver:
    """TickerResolver backed by a dict[str, str] alias map.

    MUST reproduce exact select_fmp_symbol() semantics:
    - Tries original symbol key first, then trailing-dot-stripped key
    - Falls back to stripped symbol (not raw) when no mapping exists
    - Ignores non-string mapped values (returns stripped symbol)
    - Ignores falsey mapped values (returns stripped symbol)
    """
    def __init__(self, alias_map: dict[str, str] | None = None):
        self._map: dict[str, str] = dict(alias_map or {})

    def resolve(self, symbol: str) -> str:
        original = symbol
        stripped = symbol.rstrip(".")
        mapped = self._map.get(original) or self._map.get(stripped)
        if mapped and isinstance(mapped, str):
            return mapped
        return stripped or original

class NullResolver:
    """Resolver that only applies trailing-dot normalization.
    Does NOT return raw symbol unchanged — preserves the rstrip('.') behavior
    to avoid regressions with trailing-dot tickers."""
    def resolve(self, symbol: str) -> str:
        return symbol.rstrip(".") or symbol
```

### Step-by-step

1. **Create `providers/ticker_resolver.py`** — protocol + implementations (AliasMapResolver, NullResolver)
2. **Update `providers/interfaces.py`** — add `ticker_resolver: TickerResolver | None = None` to `PriceSeriesProvider.fetch_monthly_close()` and `fetch_daily_close()` (including the default method). Keep `fmp_ticker_map` temporarily for backward compat.
3. **Update `portfolio_risk_engine/providers.py`** — `_normalize_kwargs()` creates `AliasMapResolver` from dict, includes `ticker_resolver` in returned kwargs. Pass BOTH `ticker_resolver` and `fmp_ticker_map` during transition.
4. **Update `providers/fmp_price.py`** — `FMPProvider` uses `ticker_resolver.resolve()` when present, falls back to `select_fmp_symbol()` for backward compat
5. **Update `providers/ibkr_price.py`** — accept `ticker_resolver`, immediately delete (like it does with `fmp_ticker_map`)
6. **Update `providers/bs_option_price.py`** — pass `ticker_resolver` through to underlying fetcher
7. **Update `providers/price_service.py`** — `_resolve_futures_fmp_symbol()` and `get_spot_price()` accept resolver. **NOTE**: `_resolve_futures_fmp_symbol()` has extra semantics beyond alias lookup (uppercase-key normalization, explicit-map precedence, contract-spec `fmp_symbol` fallback). The resolver is used for the alias-map portion only; contract-spec and uppercase-key logic stays as-is alongside the resolver.
8. **Update `fmp/compat.py`** — all 4 public functions gain `ticker_resolver` kwarg; use resolver-first, fallback to `select_fmp_symbol()` for old callers
9. **Update `portfolio_risk_engine/_fmp_provider.py`** — dividend yield resolution uses resolver when present
10. **Update `core/realized_performance/pricing.py`** — adapter boundary: `_fetch_price_from_chain()` creates resolver from dict at top of function, passes BOTH `ticker_resolver` and `fmp_ticker_map` during transition
11. **Update `portfolio_risk_engine/performance_metrics_engine.py`** — adapter boundary: `_fetch_daily_close_via_registry()` creates resolver from dict, passes to provider chain
12. **Update `trading_analysis/analyzer.py`** — adapter boundary: `_fetch_group_closes()` creates resolver from dict at top, passes to `fetch_daily_close()` (line 1364) and `fetch_monthly_close()` (line 1377)
13. **Update test stubs** — 5 test files with 9 hard-coded provider method signatures that would reject a `ticker_resolver` kwarg (files already using `**kwargs` are compatible and not listed):
    - `tests/providers/test_interfaces.py:77` (protocol mock + default method, 2 signatures)
    - `tests/providers/test_legacy_price_provider_adapter.py:20` (1 signature)
    - `tests/trading_analysis/test_analyzer_mutual_funds.py:119` (2 signatures)
    - `tests/trading_analysis/test_scorecard_v2.py:155,185` (2 signatures)
    - `tests/trading_analysis/test_post_exit_analysis.py:79,109` (2 signatures)
    Note: `tests/providers/test_fmp_price.py` already uses `**kwargs` and is compatible.

### What Phase 1 does NOT touch

Phase 1 scope is the **provider layer only** — making the PriceSeriesProvider protocol provider-agnostic. It intentionally does NOT cover:

- Everything above the adapter: `PortfolioData.fmp_ticker_map`, all service/core/engine pass-through
- Non-price resolution paths that call `select_fmp_symbol()` directly:
  - `portfolio_config.py:327` — price fetcher construction
  - `security_type_service.py:192` — classification ticker lookup
  - `proxy_builder.py:541` — proxy generation ticker lookup
  - `returns_calculator.py:131` — returns calculation
  - `factor_utils.py:123` — cache key generation
  These are above the adapter and use `select_fmp_symbol()` with the dict directly. They are handled in Phase 2 (rename `select_fmp_symbol` → `resolve_ticker_alias`).
- `select_fmp_symbol()` / `infer_fmp_currency()` function names
- DB columns, YAML keys, file names
- All ~110 files that just thread the dict

### Backward compatibility
- Provider signatures accept BOTH `fmp_ticker_map` and `ticker_resolver` during transition
- Adapter boundaries pass BOTH kwargs so providers/compat work with either
- `fmp/compat.py` checks `ticker_resolver` first, falls back to `fmp_ticker_map`
- All callers above the adapter continue passing `fmp_ticker_map: dict` — no change for them
- `NullResolver` preserves trailing-dot normalization (no regression)

## Phase 2: Rename (~110 files above the adapter)

Already Codex-approved (6 rounds, 24 findings). See `docs/planning/PROVIDER_AGNOSTIC_TICKER_ALIASING_PLAN.md`.

After Phase 1, Phase 2 scope is reduced:
- Provider-layer files already use `ticker_resolver` — NOT touched again
- Rename `fmp_ticker_map` → `ticker_alias_map` in ~110 files above the adapter
- Rename functions: `select_fmp_symbol` → `resolve_ticker_alias`, etc.
- DB columns, YAML keys, file names
- Remove backward-compat `fmp_ticker_map` kwargs from provider signatures (cleanup)

## Phase 3: Remove Legacy Kwargs

Small cleanup commit after Phase 2:
- Remove `fmp_ticker_map` parameter from provider method signatures
- Remove `fmp_ticker` / `fmp_ticker_map` kwargs from `fmp/compat.py` functions
- Remove `select_fmp_symbol()` entirely (replaced by `AliasMapResolver`)
- The protocol becomes clean: only `ticker_resolver`

## Verification

1. **Unit tests**: `tests/providers/test_ticker_resolver.py` — AliasMapResolver (alias hit, miss, trailing-dot, non-string, falsey), NullResolver (trailing-dot normalization), protocol compliance (`isinstance` check)
2. **Integration**: existing provider chain tests pass with new kwargs
3. **Backward compat**: old callers still work (fmp_ticker_map accepted during transition)
4. **Full suite**: `pytest tests/ -x --timeout=120`

## Critical files

| File | Change | Risk |
|------|--------|------|
| `providers/ticker_resolver.py` | NEW — protocol + implementations | Low |
| `providers/interfaces.py` | Add ticker_resolver param to protocol + default method | Medium |
| `portfolio_risk_engine/providers.py` | _normalize_kwargs creates resolver | Medium — primary adapter |
| `providers/fmp_price.py` | Use resolver for all price fetches | Medium — terminal consumer |
| `fmp/compat.py` | Resolver-first resolution in 4 functions | Medium — many callers |
| `core/realized_performance/pricing.py` | Adapter boundary | Higher — tight price-fetch loop |
| `portfolio_risk_engine/performance_metrics_engine.py` | Adapter boundary | Medium |
| `trading_analysis/analyzer.py` | Adapter boundary | Medium |
| `providers/ibkr_price.py` | Trivially ignore resolver | Low |
| `providers/bs_option_price.py` | Pass through | Low |
| `providers/price_service.py` | Resolver for futures + spot; preserve contract-spec fallback | Medium |
| 5 test files (9 signatures) | Update stubs to accept ticker_resolver | Low |

## Codex Review History

### Round 1 (4 findings → FAIL)
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | 2 more adapter boundaries: performance_metrics_engine.py, trading_analysis/analyzer.py | R2: added as steps 11-12, listed in architecture diagram |
| 2 | HIGH | AliasMapResolver semantics underspecified (trailing-dot, non-string, falsey) | R2: full implementation shown with exact edge case handling. NullResolver preserves rstrip('.') |
| 3 | MEDIUM | price_service.py has extra semantics (uppercase-key, contract-spec fallback) | R2: step 7 note — resolver handles alias-map portion only, extra semantics preserved alongside |
| 4 | MEDIUM | 9 test stubs need updating, not just 2 | R2: step 13 lists all 6 affected test files explicitly |

### Round 2 (2 findings → FAIL)
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | MEDIUM | Says "9 test files" but it's 6 files with 9 signatures | R3: corrected to "6 test files with 9 signatures", each file shows signature count |
| 2 | MEDIUM | `_build_price_fetchers()` doesn't exist — actual method is `_fetch_group_closes()` | R3: corrected to `_fetch_group_closes()` with exact line refs (1364, 1377) |

### Round 3 (2 findings → FAIL)
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | MEDIUM | Analyzer line refs swapped: fetch_daily is 1364, fetch_monthly is 1377 | R4: corrected order |
| 2 | MEDIUM | test_fmp_price.py already uses **kwargs (compatible); real surface is 5 files/9 sigs, not 6 | R4: removed test_fmp_price.py, corrected to 5 files, added missing second signatures for scorecard_v2 and post_exit_analysis |
