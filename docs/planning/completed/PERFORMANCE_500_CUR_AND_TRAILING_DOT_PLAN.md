# Fix: Performance 500s — Unmapped CUR: Cash + AT. Trailing-Dot Mismatch

## Context

After fixing the float NaN bug (`bd0d57fa`), the overview page's risk analysis loads but `/api/performance` and `/api/positions/market-intelligence` still 500. Two remaining issues discovered via the improved `@log_errors` output:

1. `fetch_monthly_close failed: ValueError: No provider could price CUR:CAD` (also CUR:HKD, CUR:JPY, CUR:MXN)
2. `fetch_monthly_close failed: ValueError: No provider could price AT.` (should be AT.L)

These failures cascade: enough tickers fail → "Insufficient data for performance calculation after filtering" → 500 on the whole endpoint.

## Root Cause 1: Unmapped CUR:XXX Cash Tickers

**`inputs/portfolio_assembler.py:130`** — `apply_cash_mapping()`:
```python
proxy_ticker = proxy_by_currency.get(currency, ticker)  # fallback = ticker itself
```

When a currency has no proxy in `cash_map.yaml` (CAD, HKD, JPY, MXN), the cash ticker maps to itself (e.g., `CUR:CAD → CUR:CAD`). This goes into `portfolio_input` → YAML → `get_returns_dataframe()` → `fetch_monthly_close("CUR:CAD")` → crash.

**Why the other path is fine**: `to_portfolio_data()` (data_objects.py:628-637) has explicit unmapped cash removal. But the DB performance path goes through `PortfolioManager._load_portfolio_from_database()` → `apply_cash_mapping()` which lacks this guard.

**Currencies with proxies** (OK): USD→SGOV, EUR→IBGE.L, GBP→ERNS.L
**Currencies without proxies** (failing): CAD, HKD, JPY, MXN

## Root Cause 2: AT. Trailing-Dot Map Key Mismatch

**`utils/ticker_resolver.py:80`** and **`portfolio_risk_engine/_ticker.py:25`** — `select_fmp_symbol()`:
```python
ticker = ticker.rstrip(".")        # AT. → AT
...
mapped = fmp_ticker_map.get(ticker) # looks up "AT" but key is "AT."  → miss!
```

The fmp_ticker_map is built with the original IBKR ticker as key: `{"AT.": "AT.L"}`. But `select_fmp_symbol()` strips the trailing dot before lookup, creating a mismatch. Falls back to `"AT"` → FMP can't price it.

**Why realized performance works**: `core/realized_performance/holdings.py:86` pre-strips tickers before building the map, so keys are `{"AT": "AT.L"}`.

## Changes

### Fix 1: `apply_cash_mapping()` — skip unmapped cash
**File**: `inputs/portfolio_assembler.py:125-137`

After resolving alias→currency→proxy, check if the resolved currency actually has a proxy. If not, skip with warning. This is precise: it checks the final resolved currency against `proxy_by_currency` rather than string-matching the result.

```python
for position in positions:
    ticker = position["ticker"]

    if position.get("type") == "cash":
        currency = position.get("currency", "USD")

        # Resolve alias → currency if applicable
        if ticker in alias_to_currency:
            currency = alias_to_currency[ticker]

        proxy_ticker = proxy_by_currency.get(currency)
        if not proxy_ticker:
            portfolio_logger.warning(
                "Unmapped cash %s (%s) excluded — no proxy in cash_map",
                ticker, currency,
            )
            continue

        portfolio_input[proxy_ticker] = {"dollars": float(position["quantity"])}
        portfolio_logger.info("📊 Cash mapping: %s (%s) -> %s", ticker, currency, proxy_ticker)
```

### Fix 2: `select_fmp_symbol()` — try original key first, then stripped
**Files**: `utils/ticker_resolver.py:79-87` AND `portfolio_risk_engine/_ticker.py:24-32`

Preserve original ticker, strip for return value but try exact original key first in map lookup (maps from DB path are keyed on `"AT."`, maps from realized path on `"AT"`):

```python
def select_fmp_symbol(ticker, *, fmp_ticker=None, fmp_ticker_map=None):
    original_ticker = ticker
    ticker = ticker.rstrip(".")
    if fmp_ticker:
        if not isinstance(fmp_ticker, str):
            return ticker
        return fmp_ticker
    if fmp_ticker_map:
        # Try exact original key first, then stripped (handles both keying conventions)
        mapped = fmp_ticker_map.get(original_ticker) or fmp_ticker_map.get(ticker)
        if mapped:
            if not isinstance(mapped, str):
                return ticker
            return mapped
    return ticker
```

### Fix 3: Defense-in-depth — skip CUR: in `_fetch_ticker_returns()`
**File**: `portfolio_risk_engine/portfolio_risk.py:661-672`

Early return for CUR: tickers that somehow reach the pricing pipeline (belt-and-suspenders):

```python
def _fetch_ticker_returns(ticker, start_date, end_date, ...):
    # CUR: tickers are cash positions — they have no price series
    if isinstance(ticker, str) and ticker.startswith("CUR:"):
        return {"ticker": ticker, "returns": None, "fx_attribution": None}

    instrument_type = _resolve_instrument_type(ticker, instrument_types)
    ...
```

## Files

| File | Change |
|------|--------|
| `inputs/portfolio_assembler.py` | Skip unmapped cash in `apply_cash_mapping()` (~line 128-136) |
| `utils/ticker_resolver.py` | Try original key first in fmp_ticker_map lookup (~line 80-87) |
| `portfolio_risk_engine/_ticker.py` | Same fix for duplicate `select_fmp_symbol()` (~line 25-32) |
| `portfolio_risk_engine/portfolio_risk.py` | CUR: early-return guard in `_fetch_ticker_returns()` (~line 672) |

## Verification

1. `python3 -m pytest tests/ -x -q` — existing tests pass
2. Restart risk_module, load overview page in Chrome — no 500s
3. Check `logs/app.log` — no "No provider could price CUR:" or "No provider could price AT" errors
4. MCP: `get_performance(format="summary", use_cache=false)` returns success
5. MCP: `get_risk_analysis(format="summary", use_cache=false)` still returns success
