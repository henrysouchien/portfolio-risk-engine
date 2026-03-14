# Fix: `fetch_monthly_close` 500s — float in `fmp_ticker_map`

## Context

`/api/analyze` and `/api/performance` 500 with `TypeError: argument of type 'float' is not iterable` at `fmp/compat.py:96`. The function `_minor_currency_divisor_for_symbol(fmp_symbol)` receives a `float` (likely `NaN`) instead of `str`. 233 error instances in logs on March 7-8.

## Root Cause

Codex investigation found **5 sites** that can write non-string values (specifically `float('nan')`) into `fmp_ticker_map`. The core issue: `float('nan')` is **truthy** in Python, so `if fmp_ticker:` guards don't catch it.

### Primary: Stale variable bug in plaid_loader.py

```python
# First loop (line 846-853) — currency checking
for _, row in holdings_df.iterrows():
    fmp_ticker = row.get('fmp_ticker')  # ← reads fmp_ticker HERE
    ...

# Second loop (line 868+) — main processing
for _, row in holdings_df.iterrows():
    # fmp_ticker is NEVER reassigned in this loop!
    ...
    if fmp_ticker:  # ← uses STALE value from last row of first loop
        fmp_ticker_map[ticker] = fmp_ticker  # ← could be float('nan')
```

If the last row of the first loop had a NaN `fmp_ticker` (e.g., a synthetic cash row), that NaN leaks into EVERY entry in the second loop.

### Secondary: NaN truthiness at 4 other sites

All use `if fmp_ticker:` which passes for `float('nan')`:

- **`snaptrade_loader.py:1363-1371`** — reads `fmp_ticker = row.get('fmp_ticker')` from DataFrame `iterrows()` (NaN for missing cells), writes to map
- **`inputs/portfolio_assembler.py:151-156`** — reads from position dict, writes to map
- **`portfolio_risk_engine/data_objects.py:517,589-595`** — `to_portfolio_data()` reads from position dict, writes to map
- **`portfolio_risk_engine/providers.py:55-57`** — `_normalize_kwargs()` writes `kw.get("fmp_ticker")` into a fresh map behind `if fmp_ticker:`

### Why `PositionsData.from_dataframe()` doesn't help

Line 423 does `df.where(pd.notnull(df), None)` which converts NaN→None. But the legacy loaders (`plaid_loader.py`, `snaptrade_loader.py`) and the assembler bypass this — they iterate DataFrames or raw dicts directly.

## Changes

### Fix 1: plaid_loader.py — fix stale variable + add type guard
**File**: `plaid_loader.py:846-884`

- Remove stale `fmp_ticker = row.get('fmp_ticker')` from first loop (line 849) — not used there.
- Add `fmp_ticker = row.get('fmp_ticker')` inside the second loop body.
- Change guard from `if fmp_ticker:` to `if isinstance(fmp_ticker, str) and fmp_ticker.strip():`.

### Fix 2: snaptrade_loader.py — add type guard
**File**: `snaptrade_loader.py:1367-1371`

Change guard from `if fmp_ticker:` to `if isinstance(fmp_ticker, str) and fmp_ticker.strip():`.

### Fix 3: portfolio_assembler.py — add type guard
**File**: `inputs/portfolio_assembler.py:155-156`

Change guard from `if ticker and fmp_ticker and ticker != fmp_ticker:` to `if ticker and isinstance(fmp_ticker, str) and fmp_ticker.strip() and ticker != fmp_ticker:`.

### Fix 4: data_objects.py `to_portfolio_data()` — add type guard
**File**: `portfolio_risk_engine/data_objects.py:517,589`

After reading `fmp_ticker = position.get("fmp_ticker")`, add:
```python
if fmp_ticker is not None and not isinstance(fmp_ticker, str):
    fmp_ticker = None
```

### Fix 5: providers.py `_normalize_kwargs()` — add type guard
**File**: `portfolio_risk_engine/providers.py:55-57`

Change:
```python
fmp_ticker = kw.get("fmp_ticker")
if fmp_ticker:
    fmp_ticker_map[ticker] = fmp_ticker
```
To:
```python
fmp_ticker = kw.get("fmp_ticker")
if isinstance(fmp_ticker, str) and fmp_ticker.strip():
    fmp_ticker_map[ticker] = fmp_ticker
```

### Fix 6: select_fmp_symbol() — reject non-strings (BOTH copies)
**Files**: `utils/ticker_resolver.py:79-87` AND `portfolio_risk_engine/_ticker.py:25-32`

Do NOT `str()` coerce (that would turn NaN into `"nan"` garbage symbol). Instead, reject non-strings:
```python
if fmp_ticker:
    if not isinstance(fmp_ticker, str):
        return ticker  # reject non-string, fall back to ticker
    return fmp_ticker
if fmp_ticker_map:
    mapped = fmp_ticker_map.get(ticker)
    if mapped:
        if not isinstance(mapped, str):
            return ticker
        return mapped
return ticker
```

### Fix 7: Improve `@log_errors` to include exception details
**File**: `app_platform/logging/decorators.py:24-29,38-44`

Change message from `"Function {name} failed"` to `"{name} failed: {type}: {message}"` so app.log is actually useful for debugging. Apply to both async and sync wrappers.

## Files

| File | Change |
|------|--------|
| `plaid_loader.py` | Fix stale variable, add `isinstance` guard (~line 849, 868-884) |
| `snaptrade_loader.py` | Add `isinstance` guard (~line 1367-1371) |
| `inputs/portfolio_assembler.py` | Add `isinstance` guard (~line 155-156) |
| `portfolio_risk_engine/data_objects.py` | Add `isinstance` guard (~line 517-595) |
| `portfolio_risk_engine/providers.py` | Add `isinstance` guard (~line 55-57) |
| `utils/ticker_resolver.py` | Reject non-string backstop (~line 79-87) |
| `portfolio_risk_engine/_ticker.py` | Reject non-string backstop (~line 25-32) |
| `app_platform/logging/decorators.py` | Include exc details in log message (~line 24-29, 38-44) |

## Verification

1. `python -m pytest tests/ -x -q` — existing tests pass
2. Manual: start server (`make dev`), hit overview page — should load without 500
3. Check `logs/errors.jsonl` — no new float TypeErrors
4. Check `logs/app.log` — error messages now include exception details
