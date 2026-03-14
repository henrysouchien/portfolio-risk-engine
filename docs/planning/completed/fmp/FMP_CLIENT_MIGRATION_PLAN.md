# Migrate Legacy FMP API Calls to FMPClient

> **Status**: COMPLETE — All 5 phases implemented and verified
> **Created**: 2026-02-05
> **Completed**: 2026-02-06
> **Reviewed by**: Codex (GPT) — no P0/P1 issues, P2/P3 items addressed below

## Summary

Replace all direct `requests.get()` calls to the FMP API with calls through the existing `FMPClient` abstraction layer (`fmp/`). The compat wrappers in `fmp/compat.py` already exist for the 4 main `data_loader.py` functions but aren't wired in yet. The remaining 3 call sites in `ticker_resolver.py` and `analyzer.py` need new migrations.

## Current State

**7 direct FMP API call sites** across 3 files:

| File | Function | FMP Endpoint | Has Compat Wrapper? |
|------|----------|-------------|-------------------|
| `data_loader.py` | `fetch_monthly_close` | `/stable/historical-price-eod/full` | Yes |
| `data_loader.py` | `fetch_monthly_total_return_price` | `/stable/historical-price-eod/dividend-adjusted` + fallback | Yes |
| `data_loader.py` | `fetch_monthly_treasury_rates` | `/stable/treasury-rates` | Yes |
| `data_loader.py` | `fetch_dividend_history` | `/stable/dividends` | Yes |
| `utils/ticker_resolver.py` | `fmp_search` | `/api/v3/search` | No |
| `utils/ticker_resolver.py` | `fetch_fmp_quote_with_currency` | `/api/v3/profile/{symbol}` | No |
| `trading_analysis/analyzer.py` | `_fetch_fmp_company_name` | `/api/v3/profile/{ticker}` | No |

Additionally, `_fetch_current_dividend_yield_lru` in `data_loader.py` calls `fetch_dividend_history` and `fetch_monthly_close` internally — it migrates automatically when those two are migrated.

## Files to Modify

| File | Change |
|------|--------|
| `data_loader.py` | Replace 4 function bodies with delegation to `fmp/compat.py`; remove old caching layers |
| `utils/ticker_resolver.py` | Migrate `fmp_search` and `fetch_fmp_quote_with_currency` to use `FMPClient` |
| `trading_analysis/analyzer.py` | Migrate `_fetch_fmp_company_name` to use `FMPClient` |

## Reference Files (no changes)

| File | Role |
|------|------|
| `fmp/client.py` | `FMPClient` class — `fetch()`, `fetch_raw()`, `get_client()` |
| `fmp/compat.py` | Existing compat wrappers with LRU caching (already use FMPClient) |
| `fmp/registry.py` | All needed endpoints already registered (`search`, `profile`, etc.) |
| `utils/config.py` | Add `FMP_SEARCH_TIMEOUT` config constant |

---

## Review Items (from Codex)

### [P2] Timeout regression — RESOLVED

Current state: `ticker_resolver.py` and `analyzer.py` use `timeout=10` for search/profile lookups. `FMPClient` defaults to `timeout=30`.

**Decision**: Add a configurable `FMP_SEARCH_TIMEOUT` to `utils/config.py` (default 10s). Pass this timeout when constructing or calling `FMPClient` for search/profile lookups in ticker_resolver and analyzer. The `FMPClient` constructor already accepts a `timeout` param.

```python
# utils/config.py
FMP_SEARCH_TIMEOUT = int(os.getenv("FMP_SEARCH_TIMEOUT", "10"))
```

For ticker_resolver and analyzer, use a dedicated client instance or pass timeout:
```python
from fmp.client import FMPClient
from utils.config import FMP_SEARCH_TIMEOUT
_search_client = FMPClient(timeout=FMP_SEARCH_TIMEOUT)
```

### [P2] Loss of `log_critical_alert` calls — RESOLVED

Current state: `data_loader.py` has ~8 `log_critical_alert` calls for empty data, connection failures, invalid maturities. These would be lost when delegating to compat.

**Decision**: Add equivalent `log_critical_alert` calls to `fmp/compat.py`. The compat layer is the behavioral bridge and the right place for domain-specific monitoring. This ensures alerts fire regardless of caller (data_loader, services, CLI).

Alerts to add to compat:
- `fetch_monthly_close`: alert on empty data / connection failure
- `fetch_monthly_total_return_price`: alert on both adjusted and fallback failures
- `fetch_monthly_treasury_rates`: alert on connection failure / invalid maturity
- `fetch_dividend_history`: alert on connection failure

### [P2] Cache semantics change — ACKNOWLEDGED (desired)

The new FMPClient cache:
- Rooted at repo level via `FMPCache(Path(__file__).parent.parent)`
- Uses MONTHLY refresh for dividends (smarter than old hash-only)
- Adds staleness tokens for date-param endpoints without `end_date` (prevents stale "latest data" hits)

These are improvements over the old caching behavior. The cache directory change (`cache_prices/` → `cache/prices/`) means a one-time cold-cache miss after migration — acceptable.

### [P3] `fetch_raw` bypasses profile TTL cache — ACKNOWLEDGED (acceptable)

Using `fetch_raw` for search/profile in ticker_resolver and analyzer matches current behavior (no caching). The profile endpoint's 1-week TTL is available via `fetch()` if we want to reduce API calls in the future, but not needed now.

### Test gaps — WILL ADDRESS

1. Add unit tests for `fmp_search` and `fetch_fmp_quote_with_currency` with mocked `FMPClient.fetch_raw`
2. Add unit test for `_fetch_fmp_company_name` with mocked `FMPClient.fetch_raw`
3. Add regression test asserting `data_loader.fetch_monthly_*` returns same series names and resample behavior after delegation

---

## Phase 1: Wire data_loader.py to fmp/compat.py ✅

**What**: The 4 main functions in `data_loader.py` currently make raw `requests.get()` calls. The compat wrappers in `fmp/compat.py` already replicate their exact behavior using `FMPClient`. We replace the function bodies with simple delegation.

### Caching Strategy

Current `data_loader.py` has a two-tier cache:
- **Tier 1 (LRU)**: `@lru_cache` wrappers at lines 727-788 for `fetch_monthly_close` and `fetch_monthly_treasury_rates`
- **Tier 2 (Disk)**: `cache_read()` calls inside the original function bodies (Parquet in `cache_prices/`, `cache_dividends/`)

`fmp/compat.py` already has its own two-tier cache:
- **Tier 1 (LRU)**: `@lru_cache` on `_fetch_monthly_close_cached`, `_fetch_monthly_total_return_cached`, `fetch_monthly_treasury_rates`
- **Tier 2 (Disk)**: `FMPClient` disk cache (Parquet in `cache/prices/`, `cache/dividends/`)

**Approach**: Remove the data_loader.py caching entirely (both LRU re-wrappers at lines 720-788 and disk cache calls in original bodies). The compat layer handles all caching. This avoids double-caching.

**Cache directory change**: Old cache was in `cache_prices/`, new is in `cache/prices/`. First call after migration will be a cold-cache miss — acceptable.

### Changes to `data_loader.py`

#### 1a. Replace `fetch_monthly_close` body ✅

Replace the full function body (which contains `requests.get()`, `cache_read()`, JSON parsing, resampling) with a one-line delegation:

```python
@log_error_handling("high")
def fetch_monthly_close(
    ticker, start_date=None, end_date=None, *, fmp_ticker=None, fmp_ticker_map=None,
) -> pd.Series:
    """...(keep docstring)..."""
    from fmp.compat import fetch_monthly_close as _compat_fetch_monthly_close
    return _compat_fetch_monthly_close(
        ticker, start_date, end_date,
        fmp_ticker=fmp_ticker, fmp_ticker_map=fmp_ticker_map,
    )
```

#### 1b. Replace `fetch_monthly_total_return_price` body ✅

Same pattern — delegate to `fmp.compat.fetch_monthly_total_return_price`.

#### 1c. Replace `fetch_monthly_treasury_rates` body ✅

Same pattern — delegate to `fmp.compat.fetch_monthly_treasury_rates`.

#### 1d. Replace `fetch_dividend_history` body ✅

Same pattern — delegate to `fmp.compat.fetch_dividend_history`.

#### 1e. Remove LRU re-wrappers ✅

Delete the entire section that re-defines `fetch_monthly_close` and `fetch_monthly_treasury_rates` with LRU wrappers. The compat layer already handles LRU caching with the same `DATA_LOADER_LRU_SIZE` and `TREASURY_RATE_LRU_SIZE` settings.

#### 1f. `_fetch_current_dividend_yield_lru` — no changes needed ✅

This function calls `fetch_dividend_history()` and `fetch_monthly_close()` internally. After steps 1a/1d, those calls automatically route through compat → FMPClient. No code changes needed.

### Add `log_critical_alert` calls to `fmp/compat.py` ✅

The compat wrappers currently don't have the monitoring alerts that `data_loader.py` has. Add try/except with `log_critical_alert` to each compat function to preserve operational monitoring:

Exact alert keys and severities to preserve (from `data_loader.py`):

| Compat Function | Trigger | Alert Key | Severity |
|----------------|---------|-----------|----------|
| `_fetch_monthly_close_cached` | HTTP error / connection failure | `api_connection_failure` | `high` |
| `_fetch_monthly_close_cached` | Empty data or missing `date` column | `empty_api_data` | `high` |
| `_fetch_monthly_total_return_cached` | Adjusted endpoint HTTP error | `api_connection_failure` | `high` |
| `_fetch_monthly_total_return_cached` | Adjusted endpoint empty data / missing `date` | `empty_api_data` | `high` |
| `_fetch_monthly_total_return_cached` | Fallback endpoint HTTP error | `api_connection_failure` | `high` |
| `_fetch_monthly_total_return_cached` | Fallback endpoint empty data / missing `date` | `empty_api_data` | `high` |
| `fetch_monthly_treasury_rates` | HTTP error / connection failure | `api_connection_failure` | `high` |
| `fetch_monthly_treasury_rates` | Invalid maturity column | `invalid_treasury_maturity` | `medium` |
| `fetch_dividend_history` | HTTP error / connection failure | `api_connection_failure` | `high` |
| `fetch_dividend_history` | Empty data or missing `date` column | `empty_api_data` | `high` |

All alerts use `log_critical_alert(key, severity, message, recommendation, details={...})` from `utils.logging`.

### Critical Behaviors Preserved

- **Fallback chain**: `fetch_monthly_total_return_price` tries adjusted endpoint, falls back to close-only on any exception
- **Month-end resampling**: All price/rate functions resample to month-end (`.resample("ME")`)
- **Series naming**: `{ticker}_total_return` vs `{ticker}_price_only` distinction preserved
- **Frequency-based TTM**: `fetch_dividend_history` selects most recent N observations based on payment frequency
- **Data quality gate**: `_fetch_current_dividend_yield_lru` returns 0.0 if yield > threshold

### Testing Phase 1

- Run `pytest tests/test_fmp_client.py` — existing compat wrapper tests
- Run `pytest tests/` — full regression
- Manual smoke test: `python -c "from data_loader import fetch_monthly_close; print(fetch_monthly_close('AAPL', '2024-01-01'))"`

---

## Phase 2: Migrate ticker_resolver.py ✅

**What**: Replace 2 direct `requests.get()` calls with `FMPClient`. Both `search` and `profile` endpoints are already registered.

### Changes to `utils/ticker_resolver.py`

#### 2a. Add module-level client with configurable timeout ✅

```python
from fmp.client import FMPClient
from utils.config import FMP_SEARCH_TIMEOUT

# Lazy-initialized client with search-appropriate timeout
_fmp_client: FMPClient | None = None

def _get_search_client() -> FMPClient:
    global _fmp_client
    if _fmp_client is None:
        _fmp_client = FMPClient(timeout=FMP_SEARCH_TIMEOUT)
    return _fmp_client
```

#### 2b. Migrate `fmp_search` ✅

Replace `requests.get()` to `/api/v3/search` with `FMPClient.fetch_raw()`:

```python
def fmp_search(query: str) -> Optional[list[dict[str, Any]]]:
    if not query:
        return []
    try:
        data = _get_search_client().fetch_raw("search", query=query)
        return data if isinstance(data, list) else []
    except Exception as exc:
        portfolio_logger.warning(f"FMP search failed for {query!r}: {exc}")
        return None
```

Use `fetch_raw` (not `fetch`) because callers expect `list[dict]`, not a DataFrame.

#### 2c. Migrate `fetch_fmp_quote_with_currency` ✅

Replace `requests.get()` to `/api/v3/profile/{symbol}` with `FMPClient.fetch_raw()`:

```python
def fetch_fmp_quote_with_currency(symbol: str) -> tuple[Optional[float], Optional[str]]:
    if not symbol:
        return None, None
    try:
        data = _get_search_client().fetch_raw("profile", symbol=symbol)
        if data and isinstance(data, list):
            return data[0].get("price"), data[0].get("currency")
        return None, None
    except Exception as exc:
        portfolio_logger.warning(f"FMP profile fetch failed for {symbol}: {exc}")
        return None, None
```

#### 2d. `resolve_fmp_ticker` — no changes needed ✅

Calls `fmp_search()` internally; automatically uses FMPClient after step 2a.

#### 2e. Clean up imports ✅

Remove `import requests`, `FMP_API_KEY`, `BASE_URL` constants, and related `load_dotenv` if no longer needed by other functions in the file.

### Testing Phase 2

- Run `pytest tests/` — regression
- Manual: `python -c "from utils.ticker_resolver import fmp_search; print(fmp_search('apple'))"`
- Manual: `python -c "from utils.ticker_resolver import fetch_fmp_quote_with_currency; print(fetch_fmp_quote_with_currency('AAPL'))"`

---

## Phase 3: Migrate analyzer.py ✅

**What**: Replace 1 direct `requests.get()` call in `TradingAnalyzer._fetch_fmp_company_name`.

### Changes to `trading_analysis/analyzer.py`

#### 3a. Migrate `_fetch_fmp_company_name` ✅

Replace `requests.get()` to `/api/v3/profile/{ticker}` with `FMPClient.fetch_raw()`:

Add a module-level cached client (same pattern as ticker_resolver):

```python
# At module level in trading_analysis/analyzer.py
from fmp.client import FMPClient
from utils.config import FMP_SEARCH_TIMEOUT

_fmp_client: FMPClient | None = None

def _get_fmp_client() -> FMPClient:
    global _fmp_client
    if _fmp_client is None:
        _fmp_client = FMPClient(timeout=FMP_SEARCH_TIMEOUT)
    return _fmp_client
```

Then in the method:

```python
def _fetch_fmp_company_name(self, ticker: str) -> Optional[str]:
    if not ticker:
        return None
    if ticker in self._fmp_name_cache:
        cached = self._fmp_name_cache.get(ticker)
        return cached or None
    try:
        data = _get_fmp_client().fetch_raw("profile", symbol=ticker)
        if data and isinstance(data, list):
            name = data[0].get("companyName") or data[0].get("name")
        else:
            name = None
    except Exception:
        name = None
    self._fmp_name_cache[ticker] = name or ""
    return name or None
```

Keep the instance-level `self._fmp_name_cache` — it avoids repeated calls within a single analysis session.

#### 3b. Clean up imports ✅

Remove `import requests` and `import os` if no longer needed.

### Testing Phase 3

- Run existing trading analysis tests
- Manual: verify company name resolution works

---

## Phase 4: Final Cleanup ✅

After all phases are verified:

### `data_loader.py`
- Remove `import requests`
- Remove `FMP_API_KEY`, `API_KEY`, `BASE_URL` constants
- Remove `load_dotenv()` if nothing else needs it
- Remove old `cache_read`/`cache_write` disk-cache calls from the replaced function bodies
- Keep `cache_read`/`cache_write` utility functions if used elsewhere in the file

### `utils/ticker_resolver.py`
- Remove `import requests`, `FMP_API_KEY`, `BASE_URL`

### `trading_analysis/analyzer.py`
- Remove `import requests`, `import os` (if unused)

---

## Phase 5: Add Migration Tests ✅

Add tests to lock in post-migration behavior:

### `tests/test_fmp_migration.py`

**Important**: Patch at the call site (where the name is looked up), not at the class definition. This ensures module-level cached clients (`_fmp_client`) pick up the mock.

1. **ticker_resolver tests** — patch `utils.ticker_resolver._get_search_client` to return a mock client:
   ```python
   @patch("utils.ticker_resolver._get_search_client")
   def test_fmp_search_success(self, mock_get_client):
       mock_client = MagicMock()
       mock_client.fetch_raw.return_value = [{"symbol": "AAPL", ...}]
       mock_get_client.return_value = mock_client
   ```
   - `fmp_search("")` returns `[]`
   - `fmp_search("apple")` returns `list[dict]` with expected keys
   - `fmp_search` returns `None` on API failure (not exception)
   - `fetch_fmp_quote_with_currency("AAPL")` returns `(float, str)` tuple
   - `fetch_fmp_quote_with_currency` returns `(None, None)` on failure

2. **analyzer tests** — patch `trading_analysis.analyzer._get_fmp_client` to return a mock client:
   ```python
   @patch("trading_analysis.analyzer._get_fmp_client")
   def test_fetch_company_name(self, mock_get_client):
       mock_client = MagicMock()
       mock_client.fetch_raw.return_value = [{"companyName": "Apple Inc."}]
       mock_get_client.return_value = mock_client
   ```
   - `_fetch_fmp_company_name("AAPL")` returns company name string
   - `_fetch_fmp_company_name("INVALID")` returns `None`
   - Instance cache is populated after first call

3. **data_loader delegation tests** — patch `fmp.compat` functions at the import site:
   ```python
   @patch("fmp.compat.fetch_monthly_close")
   def test_data_loader_delegates(self, mock_compat):
       mock_compat.return_value = pd.Series([100.0], name="AAPL")
       result = data_loader.fetch_monthly_close("AAPL")
       mock_compat.assert_called_once()
   ```
   - `data_loader.fetch_monthly_close` returns `pd.Series` with correct `.name`
   - `data_loader.fetch_monthly_total_return_price` returns series with `_total_return` or `_price_only` suffix
   - `data_loader.fetch_monthly_treasury_rates` returns series named `treasury_{maturity}`

---

## Verification

1. **Unit tests**: `pytest tests/test_fmp_client.py tests/test_fmp_migration.py -v`
2. **Full test suite**: `pytest tests/ -v`
3. **API simulation**: `python tests/utils/show_api_output.py analyze`
4. **Smoke tests**: Call each migrated function directly and verify output matches expectations
5. **Grep verification**: `grep -r "requests.get.*financialmodelingprep" --include="*.py"` should return 0 hits outside of `fmp/client.py`

---

## Call Flow After Migration

```
Callers (risk module, services, CLI)
  └── data_loader.py (thin delegates, preserves signatures)
        └── fmp/compat.py (LRU cache + behavior replication)
              └── fmp/client.py (FMPClient — disk cache, rate limiting, error handling)
                    └── FMP API (HTTP)

utils/ticker_resolver.py ──→ fmp/client.py (FMPClient) ──→ FMP API
trading_analysis/analyzer.py ──→ fmp/client.py (FMPClient) ──→ FMP API
```
