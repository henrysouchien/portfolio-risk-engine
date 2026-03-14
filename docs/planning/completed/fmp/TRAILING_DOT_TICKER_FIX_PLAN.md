# Fix AT. Trailing-Dot Ticker Pricing Crash

**Added**: 2026-03-06

## Context
IBKR-sourced positions via SnapTrade arrive with trailing-dot tickers (e.g., `AT.` for Ashtead Group on LSE). The SnapTrade position loader passes raw `AT.` to `resolve_fmp_ticker()`, which appends `.L` → `AT..L` (double dot). FMP can't price `AT..L`, and the `ValueError` propagates uncaught through `latest_price()`, crashing the entire portfolio analysis.

Other normalizers (IBKR Flex, Plaid, SymbolResolver) already strip trailing dots — SnapTrade is the only gap.

### Error chain
```
snaptrade_loader.py:925  →  ticker = "AT." (raw from SnapTrade API)
snaptrade_loader.py:958  →  resolve_fmp_ticker("AT.", exchange_mic="XLON") → "AT..L"
data_objects.py:563      →  fmp_ticker_map["AT."] = "AT..L"
portfolio_config.py:335  →  fetch_monthly_close("AT.", fmp_ticker="AT..L") → FMP fails
providers.py:89          →  ValueError("No provider could price AT.") → crash
```

## Changes (3 files, defense-in-depth)

### 1. `snaptrade_loader.py` — Strip at source (root cause fix)
**Lines ~925, 971**

After extracting `ticker = inner_symbol.get('symbol', 'UNKNOWN')`, strip trailing dots:
```python
raw_ticker = inner_symbol.get('symbol', 'UNKNOWN')
# IBKR-sourced symbols via SnapTrade can have trailing dots (e.g., "AT." for LSE stocks).
# Strip before resolution to avoid double-dot FMP symbols like "AT..L".
ticker = raw_ticker.rstrip(".") if raw_ticker and raw_ticker != "UNKNOWN" else raw_ticker
```

Change line 971 from `"ticker": inner_symbol.get('symbol', 'UNKNOWN')` to `"ticker": ticker` (use already-cleaned variable instead of re-reading raw value).

Result: `ticker="AT"`, `resolve_fmp_ticker("AT", exchange_mic="XLON")` → `"AT.L"` correctly.

### 2. `utils/ticker_resolver.py` — Defensive strip in resolver
**Lines ~188-189 of `resolve_fmp_ticker()`**

Add `ticker = ticker.rstrip(".")` after early-exit checks (CUR: prefix, empty check):
```python
if isinstance(ticker, str) and ticker.startswith("CUR:"):
    return ticker

# Defensive: strip trailing dots from IBKR-style symbols (e.g., "AT." → "AT")
# to prevent double-dot FMP tickers (e.g., "AT." + ".L" → "AT..L").
ticker = ticker.rstrip(".")
if not ticker:
    return ""
```

Prevents any future caller from producing double-dot tickers. Idempotent: `"AT".rstrip(".")` = `"AT"`, `"BRK.B".rstrip(".")` = `"BRK.B"` (only trailing dots affected). Matches existing pattern in `providers/symbol_resolution.py:61`.

### 3. `portfolio_risk_engine/portfolio_config.py` — Safety net in `latest_price()`
**Lines ~335-340**

try/except around `fetch_monthly_close()` + `.dropna().iloc[-1]`, returning `0.0` with warning on failure. Matches existing `_latest_option_price()` pattern at lines 406-414. Prevents any single unpriceable ticker from crashing the entire analysis.

## Reference: Existing trailing-dot strip patterns
| File | Line | Pattern |
|------|------|---------|
| `ibkr/flex.py` | 339 | `base_symbol = symbol.rstrip(".")` |
| `providers/symbol_resolution.py` | 61 | `base = symbol.rstrip(".").upper()` |
| `providers/normalizers/plaid.py` | 305 | `ticker=symbol.rstrip(".")` |

## Verification
1. Run existing trailing-dot tests: `pytest tests/ibkr/test_flex.py tests/providers/test_symbol_resolution.py tests/trading_analysis/test_plaid_ticker_resolution.py -x`
2. Add test for `resolve_fmp_ticker("AT.", exchange_mic="XLON")` → `"AT.L"` (not `"AT..L"`)
3. Add test for `latest_price()` returning `0.0` on unpriceable ticker
4. Restart server and verify portfolio analysis completes without crash
