# IBKR Daily Bars Phase 2 — FX/Bond Daily + TimeSeriesStore Cache + Graceful Degradation

## Context

Phase 1 shipped (`a5037695`): futures get daily bars via `IBKRPriceProvider.fetch_daily_close()` → `_futures_daily_fetcher`. All other instrument types (FX, bonds, options) fall back to `fetch_monthly_close()` — monthly-only from IBKR.

The remaining TODO items:
1. FX daily bars
2. Bond daily bars
3. Options daily bars (investigate)
4. TimeSeriesStore caching for IBKR daily series
5. Graceful degradation for insufficient daily data

**Key insight**: FX, bond, and option profiles in `ibkr/profiles.py` already use `bar_size="1 day"`. The monthly wrappers fetch daily bars then resample via `_to_monthly_close()`. Adding daily wrappers = skip the resample. This is trivial.

**Equity daily bars are out of scope** — FMP (priority 10) already serves daily equity data via `TimeSeriesStore`. IBKR is only used for instruments FMP can't price.

**Options daily bars are deferred** — short lookback (3-6mo for OTM), complex contract spec required, B-S fallback already exists. Poor complexity-to-value ratio.

---

## Codex Review Rounds 1-2 — Findings Addressed

Rounds 1-8. All in-scope findings addressed. R8 found 2 pre-existing bugs (FMP cache adapter missing `close_me`/`total_return_me` series kinds; TimeSeriesStore stale-refresh coverage erasure) — both unrelated to this plan, filed as separate TODOs.

| Finding | Severity | Fix |
|---------|----------|-----|
| Coverage poisoning from transient IBKR failures | Critical | **Round 2 fix**: Add `raise_on_transient=True` param to `fetch_series()` so IBKRConnectionError/IBKREntitlementError propagate out of market_data.py instead of being swallowed. Cache-aware daily methods use this flag. Loader in `cached_daily_fetch()` catches these and re-raises as `IBKRTransientError`, which `TimeSeriesStore.read()` does NOT catch (it re-raises non-`_is_empty_loader_error` exceptions), so coverage is NOT expanded. |
| Bond cache key collision (symbol-only, no contract_identity) | High | Cache key = `_cache_ticker(symbol, instrument_type, contract_identity)` — appends contract_identity hash for bonds |
| FX symbol not canonicalized (slash creates nested paths) | High | `_cache_ticker()` uses `_normalize_fx_pair()` from `ibkr.contracts` for FX; all FX keys become `GBPHKD`-style |
| Singleton weaker than FMP per-base-dir pattern | High | Mirror FMP exactly: `_stores: dict[str, TimeSeriesStore]` keyed by resolved base_dir string |
| Feature flag only gates cache, not daily-vs-monthly cutover | High | Three separate flags: `IBKR_FX_DAILY_ENABLED` (default `"0"`), `IBKR_BOND_DAILY_ENABLED` (default `"0"`), `IBKR_TIMESERIES_CACHE_ENABLED` (default `"1"`). FX/bond daily are opt-in; cache is opt-out. |
| Cached compat path loses fail-open try/except | High | Wrap `cached_daily_fetch()` call in try/except → empty Series on any cache-layer error |
| `daily_quality_sufficient` flag on PriceResult is dead code | High | Defer Step 7 entirely. Existing `min_observations` gate + `min_weight_coverage=0.5` already protect downstream. Revisit when daily returns are consumed directly. |
| Quality thresholds too blunt for illiquid bonds | Medium | Deferred with Step 7 |
| Double caching (ibkr/cache.py + TimeSeriesStore) | Medium | Documented: inner cache (request-shape, 4h TTL) handles intra-day dedup; outer cache (TimeSeriesStore, 1d TTL) handles cross-session persistence. Complementary, not redundant. |
| `ibkr → fmp.cache` cross-package dependency | Medium | **Fixed**: Extract `TimeSeriesStore` to `utils/timeseries_store.py` as part of this plan. Both `fmp/cache.py` and `ibkr/timeseries_cache.py` import from there. Thin re-export shim in `fmp/cache.py` for backward compat. |
| `_cache_ticker()` edge cases (empty symbol, identifier-less bond) | Medium | Guard: raise `ValueError` on empty symbol. Identifier-less bonds use symbol-only key (matches upstream contract rejection — bonds without identifiers fail at `resolve_contract()` before reaching cache). Document limitation. |
| Feature flags default to "1" (opt-out, not gradual) | High | **Fixed**: FX/bond daily default to `"0"` (opt-in). Only cache defaults to `"1"`. |
| Missing tests for cache collisions, normalization, fail-open, futures regression | Missing | Added: bond monthly fallback test, futures cached fail-open regression, end-to-end compat→market_data poisoning test |
| `raise_on_transient` fires before whatToShow chain exhausted (R3) | High | **Fixed**: Track `_last_transient` through chain, only re-raise after ALL candidates tried. Also catches `IBKRDataError` (generic base class for `_request_bars()` failures). |
| New IBKR timeseries cache not wired into cache-control surface (R3) | Medium | **Fixed**: Base-dir resolver falls back to `IBKR_CACHE_DIR` env var (same as `ibkr/cache.py`). `IBKRDiskCacheAdapter` updated to clear/stat both caches. |
| `IBKR_CACHE_DIR` treated as base root, not final dir (R4) | Medium | **Fixed**: `_resolve_cache_dir()` now creates a sibling `ibkr_timeseries/` next to `IBKR_CACHE_DIR` (not nested inside it). Direct `cache_dir` resolution, no `CACHE_SUBDIR` indirection. |
| Missing tests for chain-exhaustion, IBKRDataError, env fallback (R4) | Medium | **Fixed**: 3 new chain-exhaustion tests, 1 IBKRDataError test, 3 cache-dir resolution tests, 1 cache-control wiring test. |
| Inner request cache bond key collision (R7) | High | **Fixed**: Add `contract_identity` to `ibkr/cache.py` `cache_key()` — hash `con_id`/`cusip`/`isin` into the key (same fingerprint approach as `_cache_ticker()`). Also update `get_cached()`/`put_cache()` signatures to accept `contract_identity`. `fetch_series()` already has it in scope. |
| `clear_by_age()` doesn't cover timeseries cache (R7) | Medium | **Fixed**: `IBKRDiskCacheAdapter.clear_by_age()` also age-clears timeseries Parquet files. `TimeSeriesStore` doesn't have native age-clear, so use direct glob + mtime filter on `ibkr_timeseries/` directory. |

---

## Step 0: Add `raise_on_transient` to `fetch_series()`

**File: `ibkr/market_data.py`** — Modify `fetch_series()` signature (~line 283):

```python
def fetch_series(
    self,
    symbol: str,
    instrument_type: str,
    start_date: Any,
    end_date: Any,
    profile: InstrumentProfile | None = None,
    what_to_show: str | None = None,
    contract_identity: dict[str, Any] | None = None,
    raise_on_transient: bool = False,  # NEW
) -> pd.Series:
```

The error handling must exhaust the full `whatToShow` chain before deciding to re-raise — FX/bond profiles have 3 candidates (MIDPOINT→BID→ASK), and entitlement errors on one candidate should not abort before trying the others.

**Implementation**: Track the last transient exception seen. After the chain loop, if no data was found and `raise_on_transient=True` and a transient error was recorded, re-raise it:

```python
# Before the candidate loop:
_last_transient: Exception | None = None

# In the per-candidate error handling (no changes to existing behavior):
except IBKREntitlementError as exc:
    logger.warning("IBKR entitlement issue for %s (%s): %s", sym, candidate, exc)
    _last_transient = exc  # NEW: record for post-chain re-raise
    continue
except IBKRConnectionError as exc:
    logger.info("IB Gateway not running; IBKR fallback unavailable for %s", sym)
    _last_transient = exc  # NEW: record for post-chain re-raise
    if not raise_on_transient:
        return pd.Series(dtype=float)  # existing behavior: bail immediately
    continue  # NEW: try remaining candidates before giving up
except IBKRDataError as exc:
    logger.warning("IBKR data error for %s (%s): %s", sym, candidate, exc)
    _last_transient = exc  # NEW: catch generic transient data errors too
    continue

# After the candidate loop (existing: return pd.Series(dtype=float)):
if raise_on_transient and _last_transient is not None:
    raise _last_transient
return pd.Series(dtype=float)
```

This is **backward-compatible** — default `raise_on_transient=False` preserves all existing behavior (including immediate bail on `IBKRConnectionError`). With `True`, the chain is fully exhausted before re-raising. Also catches `IBKRDataError` (the generic base class for transient request failures surfaced by `_request_bars()`).

---

## Step 1: FX + Bond Daily Methods on `IBKRMarketDataClient`

**File: `ibkr/market_data.py`** — Add after `fetch_daily_close_futures()` (~line 438):

```python
def fetch_daily_close_fx(self, symbol, start_date, end_date,
                         raise_on_transient=False) -> pd.Series:
    """Daily FX close series (no month-end resample)."""
    profile = get_profile("fx")  # Already bar_size="1 day"
    return self.fetch_series(
        symbol=symbol, instrument_type="fx",
        start_date=start_date, end_date=end_date, profile=profile,
        raise_on_transient=raise_on_transient,
    )

def fetch_daily_close_bond(self, symbol, start_date, end_date,
                           contract_identity=None,
                           raise_on_transient=False) -> pd.Series:
    """Daily bond close series (no month-end resample)."""
    profile = get_profile("bond")  # Already bar_size="1 day"
    return self.fetch_series(
        symbol=symbol, instrument_type="bond",
        start_date=start_date, end_date=end_date,
        profile=profile, contract_identity=contract_identity,
        raise_on_transient=raise_on_transient,
    )
```

Also update `fetch_daily_close_futures()` to accept `raise_on_transient`:
```python
def fetch_daily_close_futures(self, symbol, start_date, end_date,
                              raise_on_transient=False) -> pd.Series:
    profile = get_profile("futures_daily")
    return self.fetch_series(
        symbol=symbol, instrument_type="futures",
        start_date=start_date, end_date=end_date, profile=profile,
        raise_on_transient=raise_on_transient,
    )
```

Mirrors existing pattern — calls `fetch_series()` without `_to_monthly_close()`.

---

## Step 2: FX + Bond Daily Compat Wrappers

**File: `ibkr/compat.py`** — Add after `fetch_ibkr_daily_close_futures()`:

```python
def fetch_ibkr_daily_close_fx(symbol, start_date, end_date) -> pd.Series:
    """Fetch daily FX close series through the IBKR market data client."""
    try:
        client_cls = IBKRMarketDataClient
        if client_cls is None:
            from .market_data import IBKRMarketDataClient as _cls
            client_cls = _cls
        client = client_cls()
        return client.fetch_daily_close_fx(symbol, start_date, end_date)
    except Exception as exc:
        logger.warning("IBKR daily FX fetch failed for %s: %s", symbol, exc)
        return pd.Series(dtype=float)

def fetch_ibkr_daily_close_bond(symbol, start_date, end_date,
                                contract_identity=None) -> pd.Series:
    """Fetch daily bond close series through the IBKR market data client."""
    try:
        client_cls = IBKRMarketDataClient
        if client_cls is None:
            from .market_data import IBKRMarketDataClient as _cls
            client_cls = _cls
        client = client_cls()
        return client.fetch_daily_close_bond(symbol, start_date, end_date,
                                             contract_identity=contract_identity)
    except Exception as exc:
        logger.warning("IBKR daily bond fetch failed for %s: %s", symbol, exc)
        return pd.Series(dtype=float)
```

Add both to `__all__`.

**File: `ibkr/__init__.py`** — Add to `_LAZY_EXPORTS`:
```python
"fetch_ibkr_daily_close_fx": ("ibkr.compat", "fetch_ibkr_daily_close_fx"),
"fetch_ibkr_daily_close_bond": ("ibkr.compat", "fetch_ibkr_daily_close_bond"),
```

---

## Step 3: IBKR TimeSeriesStore Cache

**File: `ibkr/timeseries_cache.py`** (NEW)

Mirror the FMP per-base-dir registry pattern exactly.

**Prerequisite**: Extract `TimeSeriesStore` from `fmp/cache.py` to `utils/timeseries_store.py`. Add thin re-export in `fmp/cache.py`: `from utils.timeseries_store import TimeSeriesStore`. This removes the `ibkr → fmp.cache` cross-package dependency.

```python
"""Incremental daily time-series cache for IBKR market data.

Imports TimeSeriesStore from utils.timeseries_store (shared module).
Keyed by (symbol, instrument_type, contract_identity_hash) → one file per
instrument series.

Two cache layers (complementary, not redundant):
- Inner: ibkr/cache.py request-shape cache (4h TTL, intra-day dedup)
- Outer: this module (1d TTL, cross-session persistence + incremental extend)
"""
import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from utils.timeseries_store import TimeSeriesStore
from ibkr.contracts import _normalize_fx_pair
from ibkr.exceptions import IBKRConnectionError, IBKREntitlementError

_stores: dict[str, TimeSeriesStore] = {}
_store_guard = threading.Lock()


class IBKRTransientError(Exception):
    """Raised when IBKR fetch fails transiently (Gateway down, entitlement).

    Distinct from "no data" (empty series). TimeSeriesStore re-raises this,
    preventing coverage expansion on transient failures.
    """


def _resolve_cache_dir() -> Path:
    """Resolve timeseries cache directory, aligned with ibkr/cache.py conventions.

    ibkr/cache.py treats IBKR_CACHE_DIR as the FINAL cache directory (files go
    directly there). We store timeseries files as a sibling 'ibkr_timeseries/'
    subdirectory next to the request-cache directory.

    Resolution order:
    1. IBKR_TIMESERIES_CACHE_DIR → use directly (explicit override)
    2. IBKR_CACHE_DIR → sibling: IBKR_CACHE_DIR/../ibkr_timeseries
    3. Default project root → cache/ibkr_timeseries/
    """
    # Explicit timeseries override
    ts_env = os.getenv("IBKR_TIMESERIES_CACHE_DIR")
    if ts_env:
        d = Path(ts_env).expanduser().resolve()
        d.mkdir(parents=True, exist_ok=True)
        return d
    # Sibling of existing IBKR request cache
    ibkr_env = os.getenv("IBKR_CACHE_DIR")
    if ibkr_env:
        d = Path(ibkr_env).expanduser().resolve().parent / "ibkr_timeseries"
        d.mkdir(parents=True, exist_ok=True)
        return d
    # Default: project root / cache / ibkr_timeseries
    root = Path(__file__).parent.parent
    if (root / "settings.py").is_file():
        d = root / "cache" / "ibkr_timeseries"
    else:
        d = Path.home() / ".cache" / "ibkr-mcp" / "ibkr_timeseries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_ibkr_timeseries_store(cache_dir: str | Path | None = None) -> TimeSeriesStore:
    """Get or create per-dir TimeSeriesStore singleton (mirrors FMP pattern).

    Unlike FMP's store which takes a base_dir and appends CACHE_SUBDIR,
    this takes a resolved cache_dir directly (from _resolve_cache_dir()).
    """
    resolved = Path(cache_dir or _resolve_cache_dir()).expanduser().resolve()
    key = str(resolved)
    with _store_guard:
        store = _stores.get(key)
        if store is None:
            # Create store with a dummy base_dir, then override cache_dir
            store = TimeSeriesStore(resolved.parent)
            store.cache_dir = resolved
            store.cache_dir.mkdir(parents=True, exist_ok=True)
            _stores[key] = store
        return store


def _reset_stores_for_tests() -> None:
    """Drop all store singletons for test isolation."""
    with _store_guard:
        _stores.clear()


def _cache_ticker(
    symbol: str,
    instrument_type: str,
    contract_identity: dict[str, Any] | None = None,
) -> str:
    """Build collision-free, path-safe cache ticker.

    - FX: canonicalize via _normalize_fx_pair (GBP/HKD → GBPHKD)
    - Bonds: append contract_identity hash (con_id, cusip, isin)
    - Others: symbol as-is (uppercased, dots preserved)

    Raises ValueError on empty symbol to prevent cache writes with blank keys.
    Bonds without contract_identity use symbol-only keys (acceptable because
    resolve_contract() rejects identifier-less bonds before reaching cache).
    """
    raw = str(symbol or "").strip().upper()
    if not raw:
        raise ValueError("Cannot build cache ticker for empty symbol")
    itype = (instrument_type or "").strip().lower()

    if itype == "fx":
        try:
            raw = _normalize_fx_pair(raw)
        except Exception:
            # Fallback: strip non-alphanum
            raw = raw.replace("/", "").replace(".", "")

    if itype == "bond" and isinstance(contract_identity, dict):
        # Fingerprint bond identity to avoid same-symbol collisions
        id_parts = []
        for k in ("con_id", "cusip", "isin"):
            v = contract_identity.get(k)
            if v is not None and str(v).strip():
                id_parts.append(f"{k}={v}")
        if id_parts:
            h = hashlib.md5("|".join(sorted(id_parts)).encode()).hexdigest()[:8]
            raw = f"{raw}_{h}"

    # Ensure path-safe: replace any remaining path separators
    return raw.replace("/", "_").replace("\\", "_")


def cached_daily_fetch(
    symbol: str,
    start_date: Any,
    end_date: Any,
    *,
    instrument_type: str,
    raw_fetcher: Callable[..., pd.Series],
    contract_identity: dict[str, Any] | None = None,
) -> pd.Series:
    """Cache-backed daily series fetch. Wraps raw_fetcher with incremental cache.

    The loader raises IBKRTransientError on Gateway/entitlement failures so
    TimeSeriesStore does NOT expand coverage on transient failures. Empty series
    on genuine no-data is correct and coverage expansion is safe.
    """
    store = get_ibkr_timeseries_store()
    ticker = _cache_ticker(symbol, instrument_type, contract_identity)
    kind = f"{instrument_type}_daily"
    s = pd.Timestamp(start_date).date().isoformat() if start_date else None
    e = pd.Timestamp(end_date).date().isoformat() if end_date else None

    def _loader(ls: str | None, le: str | None) -> pd.Series:
        """Fetch from IBKR, raising on transient failures."""
        kw: dict[str, Any] = {"start_date": ls, "end_date": le}
        if contract_identity is not None:
            kw["contract_identity"] = contract_identity
        try:
            return raw_fetcher(symbol, **kw)
        except (IBKRConnectionError, IBKREntitlementError) as exc:
            raise IBKRTransientError(str(exc)) from exc

    return store.read(
        ticker=ticker, series_kind=kind,
        start=s, end=e, loader=_loader, max_age_days=1,
    )
```

**Key design decisions**:
- **Coverage poisoning fix**: `_loader` re-raises `IBKRConnectionError`/`IBKREntitlementError` as `IBKRTransientError`. `TimeSeriesStore.read()` does NOT catch arbitrary exceptions during coverage expansion (lines 394-399, 408-413 in `fmp/cache.py` only catch via `_is_empty_loader_error`). The `IBKRTransientError` propagates up, preventing coverage bounds from expanding on transient failures.
- **Cache key**: `_cache_ticker()` canonicalizes FX symbols, fingerprints bond contract_identity, and ensures path-safety.
- **Per-base-dir registry**: mirrors FMP's `_timeseries_stores` dict pattern exactly.
- **Double caching is fine**: inner `ibkr/cache.py` (request-shape, 4h TTL) deduplicates identical requests within a session. Outer `TimeSeriesStore` (1d TTL) persists across sessions and extends incrementally. The `_raw_daily_*` functions go through `IBKRMarketDataClient.fetch_series()` which hits the inner cache first — this is correct and complementary.

---

## Step 4: Wire Cache into Compat Wrappers

**File: `ibkr/compat.py`**

Three separate feature flags for gradual rollout. **FX/bond daily default OFF (opt-in), cache default ON (opt-out)**:

```python
import os

def _ibkr_fx_daily_enabled():
    return os.getenv("IBKR_FX_DAILY_ENABLED", "0").strip() == "1"

def _ibkr_bond_daily_enabled():
    return os.getenv("IBKR_BOND_DAILY_ENABLED", "0").strip() == "1"

def _ibkr_ts_cache_enabled():
    return os.getenv("IBKR_TIMESERIES_CACHE_ENABLED", "1").strip() == "1"
```

Refactor daily compat wrappers. Each has two variants — a fail-open public wrapper (existing contract) and a cache-aware raw fetcher that uses `raise_on_transient=True`:

```python
def _raw_daily_futures(symbol, start_date, end_date):
    """Raw IBKR daily futures fetch (fail-open, existing contract)."""
    try:
        client_cls = IBKRMarketDataClient
        if client_cls is None:
            from .market_data import IBKRMarketDataClient as _cls
            client_cls = _cls
        client = client_cls()
        return client.fetch_daily_close_futures(symbol, start_date, end_date)
    except Exception as exc:
        logger.warning("IBKR daily futures fetch failed for %s: %s", symbol, exc)
        return pd.Series(dtype=float)

def _raw_daily_futures_for_cache(symbol, start_date, end_date):
    """Raw fetch for cache loader — raise_on_transient=True so IBKRConnectionError
    and IBKREntitlementError propagate out of fetch_series() instead of being
    swallowed. This lets the cache loader distinguish transient failures from
    genuine no-data, preventing coverage poisoning."""
    client_cls = IBKRMarketDataClient
    if client_cls is None:
        from .market_data import IBKRMarketDataClient as _cls
        client_cls = _cls
    client = client_cls()
    return client.fetch_daily_close_futures(
        symbol, start_date, end_date, raise_on_transient=True)

def fetch_ibkr_daily_close_futures(symbol, start_date, end_date):
    """Public wrapper — uses cache if enabled, falls back to raw on any error."""
    if _ibkr_ts_cache_enabled():
        try:
            from .timeseries_cache import cached_daily_fetch
            return cached_daily_fetch(
                symbol, start_date, end_date,
                instrument_type="futures",
                raw_fetcher=_raw_daily_futures_for_cache,
            )
        except Exception as exc:
            logger.warning("IBKR cache-backed daily futures failed for %s, falling back: %s", symbol, exc)
            return _raw_daily_futures(symbol, start_date, end_date)
    return _raw_daily_futures(symbol, start_date, end_date)
```

**Coverage poisoning fix trace**:
1. `fetch_ibkr_daily_close_futures()` → `cached_daily_fetch()` → `TimeSeriesStore.read()`
2. On coverage extension, `TimeSeriesStore.read()` calls `_loader(start, end)`
3. `_loader()` calls `_raw_daily_futures_for_cache()` → `client.fetch_daily_close_futures(raise_on_transient=True)` → `fetch_series(raise_on_transient=True)`
4. If Gateway down: `fetch_series()` catches `IBKRConnectionError`, sees `raise_on_transient=True`, **re-raises**
5. `_loader()` catches `IBKRConnectionError` → raises `IBKRTransientError`
6. `TimeSeriesStore.read()` at line ~395: `_is_empty_loader_error(IBKRTransientError)` → `False` → **re-raises** → coverage NOT expanded
7. `cached_daily_fetch()` propagates `IBKRTransientError` to `fetch_ibkr_daily_close_futures()`
8. Outer try/except catches it → falls back to `_raw_daily_futures()` (fail-open, returns empty)

**FX/bond wrappers** — same pattern, plus feature flag check:

```python
def fetch_ibkr_daily_close_fx(symbol, start_date, end_date):
    if not _ibkr_fx_daily_enabled():
        return pd.Series(dtype=float)  # Caller falls back to monthly
    if _ibkr_ts_cache_enabled():
        try:
            from .timeseries_cache import cached_daily_fetch
            return cached_daily_fetch(
                symbol, start_date, end_date,
                instrument_type="fx",
                raw_fetcher=_raw_daily_fx_for_cache,
            )
        except Exception as exc:
            logger.warning("IBKR cache-backed daily FX failed for %s, falling back: %s", symbol, exc)
            return _raw_daily_fx(symbol, start_date, end_date)
    return _raw_daily_fx(symbol, start_date, end_date)
```

---

## Step 5: Wire Daily Fetchers into IBKRPriceProvider

**File: `providers/ibkr_price.py`**

Add `fx_daily_fetcher` and `bond_daily_fetcher` constructor params + update dispatch:

```python
def __init__(self, ..., fx_daily_fetcher=None, bond_daily_fetcher=None):
    ...
    self._fx_daily_fetcher = fx_daily_fetcher or fetch_ibkr_daily_close_fx
    self._bond_daily_fetcher = bond_daily_fetcher or fetch_ibkr_daily_close_bond

def fetch_daily_close(self, symbol, start_date, end_date, *,
                      instrument_type="equity", contract_identity=None,
                      fmp_ticker_map=None):
    itype = (instrument_type or "").strip().lower()
    if itype == "futures":
        return self._futures_daily_fetcher(symbol, start_date=start_date, end_date=end_date)
    if itype == "fx":
        series = self._fx_daily_fetcher(symbol, start_date=start_date, end_date=end_date)
        if not series.empty:
            return series
        # Feature flag off or no daily data → fall back to monthly
        return self.fetch_monthly_close(symbol, start_date=start_date, end_date=end_date,
                                        instrument_type=instrument_type)
    if itype == "bond":
        series = self._bond_daily_fetcher(
            symbol, start_date=start_date, end_date=end_date,
            contract_identity=contract_identity)
        if not series.empty:
            return series
        return self.fetch_monthly_close(symbol, start_date=start_date, end_date=end_date,
                                        instrument_type=instrument_type,
                                        contract_identity=contract_identity)
    # Options: fall back to monthly (no daily wrapper — deferred)
    return self.fetch_monthly_close(
        symbol, start_date=start_date, end_date=end_date,
        instrument_type=instrument_type, contract_identity=contract_identity,
        fmp_ticker_map=fmp_ticker_map)
```

**Key**: FX/bond daily try daily first, fall back to monthly if daily returns empty (feature flag off, Gateway down, no data). This is the correct gradual rollout — the worst case is equivalent to current behavior.

Add imports: `from ibkr.compat import fetch_ibkr_daily_close_fx, fetch_ibkr_daily_close_bond`

---

## Step 6: Wire Through Bootstrap + Realized-Performance Pricing

**File: `providers/bootstrap.py`** — Add `ibkr_fx_daily_fetcher` and `ibkr_bond_daily_fetcher` params to `_register_ibkr()` and `build_default_registry()`, pass through to `IBKRPriceProvider`.

**File: `core/realized_performance/pricing.py`** — Thread daily FX/bond shims:
```python
from ibkr.compat import fetch_ibkr_daily_close_fx, fetch_ibkr_daily_close_bond

# In _build_default_price_registry():
ibkr_fx_daily_fetcher=_helpers._shim_attr("fetch_ibkr_daily_close_fx", fetch_ibkr_daily_close_fx),
ibkr_bond_daily_fetcher=_helpers._shim_attr("fetch_ibkr_daily_close_bond", fetch_ibkr_daily_close_bond),
```

**File: `core/realized_performance/__init__.py`** — Add the 2 new imports for `_shim_attr()` compat.

---

## Step 7: Graceful Degradation — DEFERRED

The original plan proposed a `_daily_quality_ok()` check + `PriceResult.daily_quality_sufficient` flag. Codex correctly identified this as dead code — nothing in the engine reads the flag.

**Why defer**: The existing guards already protect downstream:
- `get_returns_dataframe()` `min_observations` gate excludes instruments with too few monthly return observations
- `compute_portfolio_returns_partial()` `min_weight_coverage=0.5` excludes months where >50% of weight has missing data
- Step 5's daily→monthly fallback in `IBKRPriceProvider` means empty daily data degrades to monthly, not to nothing

**When to revisit**: When daily returns are consumed directly for correlation/VaR (not resampled to monthly first). At that point, add quality gating on resampled month coverage, not raw daily density.

---

## What Does NOT Change

- `ibkr/cache.py` — **Modified**: `cache_key()` and `get_cached()`/`put_cache()` extended with `contract_identity` param for bond key collision fix. Otherwise untouched.
- `services/cache_adapters.py` — **Modified**: `IBKRDiskCacheAdapter.clear_cache()` and `get_cache_stats()` must also clear/stat the new `ibkr_timeseries` cache. Add `get_ibkr_timeseries_store().clear()` call in `clear_cache()` and merge stats.
- `ibkr/profiles.py` — no new profiles needed (fx/bond already use `bar_size="1 day"`)
- `fmp/cache.py` — `TimeSeriesStore` + helpers extracted to `utils/timeseries_store.py`; `fmp/cache.py` gets thin re-exports for backward compat (listed in Files to Modify)
- `fetch_monthly_close_*` wrappers — all preserved
- Option pricing path — B-S fallback unchanged
- `portfolio_risk_engine/portfolio_risk.py` — no changes
- `PriceResult` dataclass — no changes (deferred)

---

## Files to Modify

| File | Change |
|------|--------|
| `utils/timeseries_store.py` | **NEW** — Extract `TimeSeriesStore` + helpers from `fmp/cache.py` |
| `fmp/cache.py` | Replace class + helpers with re-exports from `utils/timeseries_store` |
| `ibkr/cache.py` | Add `contract_identity` to `cache_key()`, `get_cached()`, `put_cache()` for bond collision fix |
| `ibkr/market_data.py` | Add `raise_on_transient` to `fetch_series()`, pass `contract_identity` to inner cache, add `fetch_daily_close_fx()`, `fetch_daily_close_bond()`, update `fetch_daily_close_futures()` |
| `ibkr/compat.py` | Add FX/bond daily wrappers + `_raw_*_for_cache` variants, add 3 feature flags, refactor all 3 daily wrappers to use cache with fail-open |
| `ibkr/__init__.py` | Add 2 exports to `_LAZY_EXPORTS` + `__all__` |
| `ibkr/timeseries_cache.py` | **NEW** — per-base-dir store registry, `_cache_ticker()`, `cached_daily_fetch()`, `IBKRTransientError` |
| `providers/ibkr_price.py` | Add `fx_daily_fetcher`/`bond_daily_fetcher` params + daily dispatch with monthly fallback |
| `providers/bootstrap.py` | Thread 2 new daily fetcher params |
| `core/realized_performance/pricing.py` | Thread FX/bond daily shims |
| `core/realized_performance/__init__.py` | Add 2 daily imports for `_shim_attr()` |
| `services/cache_adapters.py` | Wire `IBKRDiskCacheAdapter` to clear/stat both old request cache and new timeseries cache |

## Tests

**`tests/ibkr/test_market_data.py`** (7 new):
- `test_fetch_daily_close_fx_no_resample` — mock `fetch_series`, verify no `_to_monthly_close`
- `test_fetch_daily_close_bond_forwards_contract_identity` — mock `fetch_series`, verify kwarg
- `test_fetch_series_raise_on_transient_connection` — `raise_on_transient=True` + all candidates fail with `IBKRConnectionError` → re-raised after chain exhaustion
- `test_fetch_series_raise_on_transient_entitlement` — `raise_on_transient=True` + `IBKREntitlementError` on all candidates → re-raised
- `test_fetch_series_raise_on_transient_first_fails_second_succeeds` — first candidate entitlement error, second candidate returns data → success (no raise)
- `test_fetch_series_raise_on_transient_data_error` — `IBKRDataError` (generic base) → recorded as transient, re-raised after chain
- `test_fetch_series_raise_on_transient_false_preserves_behavior` — default `False` + connection error → empty series returned (no raise), same as current behavior

**`tests/ibkr/test_timeseries_cache.py`** (NEW, 12 tests):
- `test_store_creates_ibkr_timeseries_dir`
- `test_per_base_dir_singleton_reuse` — same base_dir returns same store instance
- `test_per_base_dir_different_dirs` — different base_dirs get separate stores
- `test_cached_daily_fetch_calls_raw_on_miss`
- `test_cached_daily_fetch_serves_from_cache`
- `test_cached_daily_fetch_extends_range_incrementally`
- `test_transient_error_does_not_poison_coverage` — loader raises IBKRTransientError → propagates, no coverage expansion
- `test_cache_ticker_fx_normalization` — GBP.HKD, GBP/HKD, GBPHKD all → same key
- `test_cache_ticker_bond_fingerprint` — same symbol + different contract_identity → different keys
- `test_cache_ticker_bond_same_identity` — same symbol + same contract_identity → same key
- `test_cache_ticker_empty_symbol_raises` — empty string → ValueError
- `test_reset_clears_all_singletons`

**`tests/ibkr/test_compat.py`** (8 new):
- `test_daily_fx_compat_wrapper_delegates`
- `test_daily_bond_compat_wrapper_delegates`
- `test_daily_fx_cache_enabled_path_fail_open` — cache error falls back to raw
- `test_daily_bond_cache_enabled_path_fail_open` — cache error falls back to raw
- `test_daily_futures_cache_enabled_fail_open_regression` — existing futures path still works after cache refactor
- `test_daily_fx_flag_off_returns_empty` — `IBKR_FX_DAILY_ENABLED=0` → empty series
- `test_daily_bond_flag_off_returns_empty` — `IBKR_BOND_DAILY_ENABLED=0` → empty series
- `test_e2e_transient_failure_no_coverage_poisoning` — full compat→market_data chain: mock Gateway down → verify no coverage expansion in TimeSeriesStore

**`tests/providers/test_ibkr_price.py`** (5 new/modified):
- `test_daily_routes_fx_to_fx_daily_fetcher`
- `test_daily_routes_bond_to_bond_daily_fetcher`
- `test_daily_fx_empty_falls_back_to_monthly` — daily returns empty → monthly fallback
- `test_daily_bond_empty_falls_back_to_monthly` — daily returns empty → monthly fallback
- `test_daily_option_still_falls_back_to_monthly`

**`tests/ibkr/test_timeseries_cache_dirs.py`** (NEW, 3 tests):
- `test_resolve_cache_dir_default` — no env vars → `project_root/cache/ibkr_timeseries/`
- `test_resolve_cache_dir_ibkr_cache_dir_sibling` — `IBKR_CACHE_DIR=/x/ibkr` → `/x/ibkr_timeseries/`
- `test_resolve_cache_dir_explicit_override` — `IBKR_TIMESERIES_CACHE_DIR=/y` → `/y`

**`tests/services/test_cache_control.py`** (2 new):
- `test_ibkr_disk_cache_adapter_clears_timeseries` — verify `clear_cache()` clears both request cache and timeseries cache
- `test_ibkr_disk_cache_adapter_stats_includes_timeseries` — verify `get_cache_stats()` merges stats from both caches

**`tests/fmp/test_incremental_timeseries_cache.py`** (1 modified):
- Verify existing tests pass after `TimeSeriesStore` extraction to `utils/timeseries_store.py`

**Total**: ~38 new tests

## Verification

1. `pytest tests/ibkr/test_market_data.py -k "daily_close_fx or daily_close_bond" -q`
2. `pytest tests/ibkr/test_timeseries_cache.py -q`
3. `pytest tests/ibkr/test_compat.py -k "daily" -q`
4. `pytest tests/providers/test_ibkr_price.py -q`
5. `pytest tests/ -q` — full regression
6. With IBKR Gateway: verify `fetch_ibkr_daily_close_fx("GBP.HKD", ...)` returns daily series, cache file appears at `cache/ibkr_timeseries/GBPHKD_fx_daily.parquet`
7. Kill Gateway, re-run: verify IBKRTransientError propagates, no coverage poisoning, fallback to monthly in provider
