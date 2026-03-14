# Fix: FMP Pricing Cache Gaps
**Status:** DONE

## Context

Audit of FMP API pricing calls revealed uncached hot paths causing redundant API calls. The `fmp/compat.py` layer has `@lru_cache` on monthly close, daily close, total return, treasury rates, and minor currency divisor. Profile lookups (used for spot prices + currency inference) bypass all caching layers.

## Audit Summary

### Already Cached (No Action)
| Function | File | Cache | MaxSize |
|----------|------|-------|---------|
| `_fetch_monthly_close_cached()` | `fmp/compat.py:152` | `@lru_cache` | 1024 |
| `_fetch_daily_close_cached()` | `fmp/compat.py:215` | `@lru_cache` | 1024 |
| `_fetch_monthly_total_return_cached()` | `fmp/compat.py:357` | `@lru_cache` | 1024 |
| `_minor_currency_divisor_for_symbol()` | `fmp/compat.py:86` | `@lru_cache` | 1024 |
| `fetch_monthly_treasury_rates()` | `fmp/compat.py:513` | `@lru_cache` | 256 |
| `_get_spot_fx_cached()` | `fmp/fx.py:236` | `@lru_cache` | 32 |

### `fetch_dividend_history()` — Disk-Cached, No In-Memory LRU (LOW)

**File**: `fmp/compat.py:573`

Unlike its sibling functions, `fetch_dividend_history()` lacks an `@lru_cache` wrapper. However, the underlying `client.fetch("dividends")` path goes through `FMPCache.read()` with Parquet disk caching and `cache_refresh=CacheRefresh.MONTHLY` (registry entry at `fmp/registry.py:277`). So this is **not uncached** — it has disk caching with monthly refresh semantics.

Adding `@lru_cache` on top would create stale-data risk in long-lived processes (dividend data cached indefinitely past monthly refresh). The income projection tool (`mcp_tools/income.py:131`) also fetches dividends via `client.fetch("dividends", use_cache=use_cache)` directly, not through `fetch_dividend_history()`.

**Decision**: No change. Disk cache with monthly TTL is appropriate for dividend data.

### Provider Chain (`_RegistryBackedPriceProvider`) — Safe
The provider loop in `providers.py:72-85` iterates providers and catches exceptions, but downstream calls hit the LRU cache. No redundant FMP calls.

## Gaps Found

### Gap 1: `fetch_fmp_quote_with_currency()` — No Cache (HIGH)

**Files**: `utils/ticker_resolver.py:133` and `portfolio_risk_engine/_ticker.py:53`

Both implementations call `FMPClient().fetch_raw("profile", symbol=symbol)` with no caching at any layer. `fetch_raw()` bypasses both disk cache and LRU cache (`fmp/client.py:461` — "no caching" by design).

**Callers** (two categories):

*Currency-only callers* (don't use the price):
- `portfolio_risk_engine/_fmp_provider.py:115` — `FMPCurrencyResolver.infer_currency()` — extracts only `currency`
- `portfolio_risk_engine/portfolio_risk.py:732` — currency inference fallback — extracts only `currency`
- `brokerage/futures/sources/fmp.py:29` — futures currency — extracts only `currency`

*Price + currency callers* (need reasonably fresh prices):
- `providers/price_service.py:86` — `get_spot_price()` for position market values
- `services/position_service.py:839` — position value enrichment
- `mcp_tools/options.py:121` — underlying price for option analysis
- `mcp_tools/chain_analysis.py:127` — underlying price for chain analysis
- `mcp_tools/tax_harvest.py:236` — current price for harvest candidates
- `run_options.py:94` — option pricing

**Impact**: Per-symbol profile fetch during portfolio analysis, income projection, spot price resolution. Same symbol can be queried multiple times across different code paths in a single request.

### Gap 2: `_get_minor_divisors()` in `mcp_tools/income.py:62` — Uncached Loop (MEDIUM)

Loops over all non-USD positions calling `client.fetch_raw("profile", symbol=fmp_ticker)` — also uncached via `fetch_raw()`. For a portfolio with 10 international holdings, that's 10 uncached profile fetches per `get_income_projection()` call.

## Changes

### Fix 1: Split-cache `fetch_fmp_quote_with_currency()` — cache currency, always fetch price

**Problem**: This function serves two audiences with conflicting freshness requirements:
- **Currency inference** callers need only `currency` (stable, safe to cache forever)
- **Spot price** callers need fresh `price` (changes during market hours)

Caching the full `(price, currency)` indefinitely would serve stale prices to option analysis, tax harvest, and position market value callers. Not caching at all wastes API calls for currency inference (which is the majority of calls).

**Solution**: Cache only the `currency` from the profile response with `@lru_cache`. Always fetch price live via `fetch_raw`. Within the same request, use the cached currency to avoid redundant profile fetches for currency-only callers.

**Approach A**: Provide a separate `infer_fmp_currency()` function that only does currency lookups (cached), and keep `fetch_fmp_quote_with_currency()` uncached for price callers. Currency-only callers switch to the new function.

**Critical detail — don't cache empty/None responses**: `fetch_raw()` can return `[]` or `None` on transient failures. If `_infer_fmp_currency_cached()` returns `None`, `@lru_cache` caches it permanently — creating a stale negative cache. Fix: raise `ValueError` on empty/missing responses so `@lru_cache` does NOT cache failures (exceptions propagate, entry stays uncached).

**File**: `utils/ticker_resolver.py`

```python
@lru_cache(maxsize=256)
def _infer_fmp_currency_cached(symbol: str) -> str:
    """Cached FMP profile lookup for listing currency only.

    Currency is stable metadata — safe to cache for process lifetime.
    Raises on empty/missing response so @lru_cache does NOT cache failures.
    """
    data = _get_search_client().fetch_raw("profile", symbol=symbol)
    if data and isinstance(data, list) and data[0].get("currency"):
        return data[0]["currency"]
    raise ValueError(f"No currency in FMP profile for {symbol}")


def infer_fmp_currency(symbol: str) -> str | None:
    """Get a symbol's listing currency from FMP (cached).

    Returns None on failure (not cached — next call retries).
    """
    if not symbol:
        return None
    try:
        return _infer_fmp_currency_cached(symbol)
    except Exception as exc:
        portfolio_logger.warning(f"FMP currency inference failed for {symbol}: {exc}")
        return None
```

**File**: `portfolio_risk_engine/_ticker.py`

Same pattern but with `instrument_type` guard preserved. The existing `fetch_fmp_quote_with_currency()` in `_ticker.py` has `instrument_type` filtering (returns `(None, None)` for futures/derivatives). `FMPCurrencyResolver.infer_currency()` and `portfolio_risk.py:732` both pass `instrument_type` through this guard. The new `infer_fmp_currency()` must keep this guard to prevent futile FMP profile lookups for futures symbols.

```python
@lru_cache(maxsize=256)
def _infer_fmp_currency_cached(symbol: str) -> str:
    """Cached FMP profile lookup for listing currency only.

    Raises on empty/missing response so @lru_cache does NOT cache failures.
    """
    from fmp.client import FMPClient  # type: ignore

    data = FMPClient().fetch_raw("profile", symbol=symbol)
    if isinstance(data, list) and data and data[0].get("currency"):
        return data[0]["currency"]
    raise ValueError(f"No currency in FMP profile for {symbol}")


def infer_fmp_currency(
    symbol: str,
    instrument_type: str | None = None,
) -> str | None:
    """Get a symbol's listing currency from FMP (cached).

    Preserves instrument_type guard from fetch_fmp_quote_with_currency() —
    returns None immediately for futures/derivatives (FMP has no profile).
    """
    if not symbol:
        return None
    if str(instrument_type or "").strip().lower() in {"futures", "derivative"}:
        return None
    try:
        return _infer_fmp_currency_cached(symbol)
    except Exception:
        return None
```

Note: `_ticker.py`'s cached function uses `FMPClient()` directly (30s default timeout), while `ticker_resolver.py`'s uses `_get_search_client()` (10s `FMP_SEARCH_TIMEOUT`). This mirrors the existing split — `_ticker.py:fetch_fmp_quote_with_currency()` already uses `FMPClient()` while `ticker_resolver.py:fetch_fmp_quote_with_currency()` already uses `_get_search_client()`.

Currency-only callers migrate:
- `FMPCurrencyResolver.infer_currency()` at `_fmp_provider.py:115` — use `infer_fmp_currency(symbol, instrument_type=instrument_type)` instead of `fetch_fmp_quote_with_currency()` (only uses `currency` return)
- `portfolio_risk.py:732` — currency inference — use `infer_fmp_currency(fmp_ticker_map[ticker], instrument_type=instrument_type)`
- `brokerage/futures/sources/fmp.py:29` — import `infer_fmp_currency` from `portfolio_risk_engine._ticker` (same module as current import, preserving 30s `FMPClient()` timeout). Call `infer_fmp_currency(alt_symbol)` — no `instrument_type` param needed since this caller queries the FMP alternate equity symbol (e.g., "ESUSD"), not the raw futures ticker

Price callers stay on `fetch_fmp_quote_with_currency()` (uncached, always live).

### Fix 2: Refactor `_get_minor_divisors()` to use cached currency lookup
**File**: `mcp_tools/income.py`

Replace the per-position `client.fetch_raw("profile")` loop with calls to the new `infer_fmp_currency()` from Fix 1, extracting currency and looking up divisors from `exchange_mappings.yaml`.

**Timeout change**: The current code uses the injected `client` parameter (`FMPClient()`, 30s default timeout). The refactored code routes through `_get_search_client()` in `ticker_resolver.py` (10s `FMP_SEARCH_TIMEOUT`). The FMP `/profile` endpoint typically responds in 1-2s, so 10s is ample. If the lookup fails (timeout or error), `infer_fmp_currency()` returns `None` → divisor is skipped → income amounts for that ticker are NOT divided, matching the current behavior when `fetch_raw()` raises an exception (the existing `except` block at `income.py:90` also skips the divisor).

The `client` parameter becomes unused and can be removed from the signature in a follow-up.

```python
def _get_minor_divisors(positions, client, use_cache=True):
    """
    Build {ticker: divisor} for positions whose FMP prices are in minor
    currency units (e.g., GBp pence → 100, ZAc cents → 100).
    """
    from utils.ticker_resolver import infer_fmp_currency, load_exchange_mappings

    config = load_exchange_mappings()
    minor_currencies = config.get("minor_currencies", {})
    if not minor_currencies:
        return {}

    divisors = {}
    for p in positions:
        if p.get("currency", "USD") == "USD":
            continue
        ticker = p["ticker"]
        fmp_ticker = p.get("fmp_ticker") or ticker
        fmp_currency = infer_fmp_currency(fmp_ticker)
        if fmp_currency and fmp_currency in minor_currencies:
            divisors[ticker] = minor_currencies[fmp_currency]["divisor"]

    return divisors
```

## Files

| File | Change |
|------|--------|
| `utils/ticker_resolver.py` | Add `_infer_fmp_currency_cached()` + `infer_fmp_currency()` with `@lru_cache(256)` |
| `portfolio_risk_engine/_ticker.py` | Same cached currency lookup with `instrument_type` guard |
| `portfolio_risk_engine/_fmp_provider.py` | `FMPCurrencyResolver.infer_currency()` → use `infer_fmp_currency(symbol, instrument_type=instrument_type)` |
| `portfolio_risk_engine/portfolio_risk.py` | Currency inference call → use `infer_fmp_currency()` |
| `brokerage/futures/sources/fmp.py` | Import + use `infer_fmp_currency` from `_ticker` (replaces `fetch_fmp_quote_with_currency`) |
| `mcp_tools/income.py` | `_get_minor_divisors()` → use `infer_fmp_currency()` from `utils.ticker_resolver` |

### Test Updates

Existing tests monkeypatch `fetch_fmp_quote_with_currency` at migrated call sites. These must be updated to patch `infer_fmp_currency` instead:

| Test File | Current Patch | New Patch |
|-----------|--------------|-----------|
| `tests/test_price_service.py:111` | `portfolio_risk_engine._ticker.fetch_fmp_quote_with_currency` | `portfolio_risk_engine._ticker.infer_fmp_currency` (signature changes: returns `str\|None`, not `tuple`) |
| `tests/brokerage/futures/test_pricing_chain.py:98` | `fmp_module.fetch_fmp_quote_with_currency` | `fmp_module.infer_fmp_currency` (lambda returns `"USD"`, not `(None, "USD")`) |
| `tests/brokerage/futures/test_pricing_chain.py:129` | `fmp_module.fetch_fmp_quote_with_currency` | `fmp_module.infer_fmp_currency` (same) |

Note: `tests/test_price_service.py:105` (`test_portfolio_risk_quote_fetch_skips_futures`) tests `fetch_fmp_quote_with_currency` directly — this stays unchanged since `fetch_fmp_quote_with_currency` is not removed, only currency-only callers are migrated.

### New Tests

| Test | Location | What it verifies |
|------|----------|-----------------|
| `test_infer_fmp_currency_cached_hit` | `tests/fmp/test_fmp_migration.py` | Mock `fetch_raw` → call twice → assert 1 API call (cache hit) |
| `test_infer_fmp_currency_no_negative_cache` | `tests/fmp/test_fmp_migration.py` | Mock `fetch_raw` returning `[]` → call → returns `None`. Change mock to return `[{"currency": "GBP"}]` → call again → returns `"GBP"` (not cached `None`) |
| `test_infer_fmp_currency_futures_guard` | `tests/fmp/test_fmp_migration.py` | `infer_fmp_currency("ES", instrument_type="futures")` → `None`, no `fetch_raw` call |
| `test_get_minor_divisors_uses_cached_currency` | `tests/mcp_tools/test_income.py` | Mock `infer_fmp_currency` → call `_get_minor_divisors()` → assert correct divisors returned |

## Verification

1. `python3 -m pytest tests/ -x -q` — existing tests pass
2. MCP: `get_income_projection()` — verify no regression
3. MCP: `get_performance(format="summary", use_cache=false)` — still works
4. MCP: `analyze_option_chain(symbol="AAPL")` — verify live price still fetched (not stale)
5. Inspect `_infer_fmp_currency_cached.cache_info()` after portfolio analysis — confirm hits > 0
6. Verify transient failure recovery: mock `fetch_raw()` returning `[]` → `infer_fmp_currency()` returns `None` → call again after fixing mock → returns currency (not cached `None`)
7. Verify futures guard: `infer_fmp_currency("ES", instrument_type="futures")` → `None` (no FMP call made)

## Impact Estimate

For a 30-position portfolio with 10 international holdings:
- **Before**: ~10+ uncached profile fetches for currency inference + minor divisors per analysis
- **After**: 1 profile fetch per unique symbol for currency (cached). Price-fetch callers still make live calls (correct behavior). Net reduction: ~60-70% of profile API calls eliminated.

## Design Notes

- **Multi-worker uvicorn**: Each worker has its own LRU cache (per-process). Cold misses will duplicate across workers. This is acceptable — the cache prevents *intra-request* redundancy, not cross-worker redundancy. Redis would be needed for cross-worker caching but is out of scope.
- **Concurrent first misses**: Within one worker, concurrent first calls for the same symbol can race and issue multiple outbound requests. `@lru_cache` is thread-safe for reads but not for preventing duplicate computation on cold miss. This is acceptable — it's a performance optimization, not a correctness requirement.
- **`client` parameter in `_get_minor_divisors`**: Kept in signature for backward compatibility but effectively unused after refactor. Can be removed in a follow-up cleanup.
