# Fix: Non-USD Cash Proxy ETFs Get USD Treasury Rate

## Context

Non-USD cash proxy ETFs (ERNS.L for GBP, IBGE.L for EUR) incorrectly receive the USD Treasury rate (~5.1%) as their expected return. `CUR:GBP` and `CUR:EUR` correctly get 0.0%, but when positions use the proxy ETF ticker instead, the non-USD detection fails because it only checks `is_cur_ticker()` (which requires a `CUR:*` prefix). ERNS.L is not `CUR:*`, so it falls through to the USD Treasury rate.

This was a gap in the Cash Semantics Optimizer Fix (`b5ff9122`) — Step 4 (currency-aware expected returns) was only partially implemented for `CUR:*` tickers, not proxy ETFs.

## Bug Location

`services/returns_service.py:395-417` — the `get_complete_returns()` method:

```python
elif is_cash_proxy_ticker(ticker):          # Line 395: TRUE for ERNS.L
    if (
        is_cur_ticker(ticker)               # Line 397: FALSE for ERNS.L (not CUR:*)
        and ticker.split(":", 1)[1].upper() != "USD"
    ):
        complete_returns[ticker] = 0.0      # Never reached for ERNS.L
    else:
        treasury_rate = self._get_current_treasury_rate()
        complete_returns[ticker] = treasury_rate  # BUG: ERNS.L gets 5.1%
```

## Fix (2 source files, 2 test files)

### Step 1: Extend `currency_for_ticker()` to resolve proxy ETFs

**File**: `core/cash_helpers.py:185-194`

Add a reverse lookup against `proxy_by_currency` so proxy ETFs resolve to their currency:
- SGOV → USD, ERNS.L → GBP, IBGE.L → EUR

Currently only resolves `CUR:*` and aliases. Add a third check: reverse-lookup `_get_proxy_by_currency_cached()`.

**Cache the reverse map** with a module-level `_proxy_ticker_to_currency_cache` (same pattern as the other caches in this file, lines 43-46).

**Before**:
```python
def currency_for_ticker(ticker: str) -> str | None:
    if not isinstance(ticker, str):
        return None
    if is_cur_ticker(ticker):
        currency = ticker.split(":", 1)[1].strip().upper()
        return currency or None
    return _get_alias_to_currency_cached().get(ticker)
```

**After**:
```python
def currency_for_ticker(ticker: str) -> str | None:
    """Return the ISO currency code for a cash ticker, or None if not cash.

    Resolves CUR:* prefix (CUR:USD -> USD), proxy ETFs from
    proxy_by_currency (ERNS.L -> GBP, SGOV -> USD), and broker-format
    aliases from alias_to_currency (CASH -> USD). YAML-backed.
    """
    if not isinstance(ticker, str):
        return None
    if is_cur_ticker(ticker):
        currency = ticker.split(":", 1)[1].strip().upper()
        return currency or None
    # Reverse lookup: proxy ETF -> currency (ERNS.L -> GBP)
    proxy_currency = _get_proxy_ticker_to_currency_cached().get(ticker)
    if proxy_currency is not None:
        return proxy_currency
    return _get_alias_to_currency_cached().get(ticker)
```

Add the reverse-map cache builder (same pattern as `_get_proxy_tickers_cached` at line 87):

```python
_proxy_ticker_to_currency_cache: dict[str, str] | None = None

def _get_proxy_ticker_to_currency_cached() -> dict[str, str]:
    global _proxy_ticker_to_currency_cache
    if _proxy_ticker_to_currency_cache is None:
        _proxy_ticker_to_currency_cache = {
            proxy: currency
            for currency, proxy in _get_proxy_by_currency_cached().items()
        }
    return _proxy_ticker_to_currency_cache
```

### Step 2: Use `currency_for_ticker()` in the expected returns logic

**File**: `services/returns_service.py:395-417`

Replace the `is_cur_ticker()` gate with `currency_for_ticker()` — works for both `CUR:*` and proxy ETFs.

**Before**:
```python
elif is_cash_proxy_ticker(ticker):
    if (
        is_cur_ticker(ticker)
        and ticker.split(":", 1)[1].upper() != "USD"
    ):
        complete_returns[ticker] = 0.0
```

**After**:
```python
elif is_cash_proxy_ticker(ticker):
    resolved_currency = currency_for_ticker(ticker)
    if resolved_currency is not None and resolved_currency != "USD":
        complete_returns[ticker] = 0.0
```

Update the import at `returns_service.py:33` — replace `is_cur_ticker` with `currency_for_ticker` (is_cur_ticker is no longer used after the fix):

**Before**: `from core.cash_helpers import is_cash_proxy_ticker, is_cur_ticker`
**After**: `from core.cash_helpers import is_cash_proxy_ticker, currency_for_ticker`

Update the log message at the current line 402 to use the resolved currency:
```python
portfolio_logger.info(f"💰 Using 0.0% expected return for non-USD cash {ticker} ({resolved_currency})")
```

### Step 3: Tests

**File**: `tests/core/test_cash_helpers.py`

**3a. Reset new cache in fixture** — the `cash_helpers_module` fixture (line 6) clears all module-level caches. Add `cash_helpers._proxy_ticker_to_currency_cache = None` alongside the existing 4 resets.

**3b. Add proxy ETF cases to `currency_for_ticker` tests**:
- `"SGOV"` → `"USD"`
- `"ERNS.L"` → `"GBP"`
- `"IBGE.L"` → `"EUR"`

**File**: `tests/services/test_returns_service_dynamic.py` — add test for non-USD proxy ETF expected returns:
- `ERNS.L` should get `0.0` (not Treasury rate)
- `IBGE.L` should get `0.0` (not Treasury rate)
- `SHY` and `BIL` (cash_equivalent_tickers but NOT proxy_by_currency values) should NOT enter the cash proxy branch at all — they're not `is_cash_proxy_ticker()` matches, so they go through normal equity returns. Add a regression assertion confirming this.

## Files Modified

| File | Change |
|------|--------|
| `core/cash_helpers.py` | Add `_proxy_ticker_to_currency_cache` + builder, extend `currency_for_ticker()` |
| `services/returns_service.py` | Replace `is_cur_ticker()` gate with `currency_for_ticker()`, add import |
| `tests/core/test_cash_helpers.py` | Add proxy ETF cases to `currency_for_ticker` tests |
| `tests/services/test_returns_service_dynamic.py` | Add ERNS.L/IBGE.L expected return tests |

## Verification

1. Run `pytest tests/core/test_cash_helpers.py -v` — all pass including new proxy ETF cases
2. Run `pytest tests/services/test_returns_service_dynamic.py -v` — ERNS.L/IBGE.L get 0.0, SGOV still gets Treasury
3. Run full suite `pytest tests/ -x -q` — no regressions
