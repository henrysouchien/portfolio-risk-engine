# Fix Trading Flags Currency Mismatch

## Context

The Trading P&L card shows contradicting metrics:
- Card: "Expectancy: $4/trade" (USD) vs Insight: "Negative expectancy: losing 633 per trade" (local currency)
- Card: "Profit Factor: 1.03x" (USD) vs Insight: "Profit factor is 0.19" (local currency)

The card reads USD-converted metrics (`expectancy_usd`, `profit_factor_usd`). The flags read local currency metrics (`expectancy`, `profit_factor`). For multi-currency portfolios, FX conversion makes these diverge significantly.

## Fix

Change `core/trading_flags.py` to read USD metrics from the snapshot, matching the card display. The snapshot already includes both versions — see `trading_analysis/models.py` lines 786-792.

### File: `core/trading_flags.py`

**Line 34** — expectancy:
```python
# Before:
expectancy = performance.get("expectancy")

# After:
expectancy = performance.get("expectancy_usd") if performance.get("expectancy_usd") is not None else performance.get("expectancy")
```

**Line 45** — profit_factor:
```python
# Before:
profit_factor = performance.get("profit_factor")

# After:
profit_factor = performance.get("profit_factor_usd") if performance.get("profit_factor_usd") is not None else performance.get("profit_factor")
```

**Line 192** — strong profit factor positive signal (also uses `profit_factor`):
```python
# This line already references the local `profit_factor` variable, so the fix at line 45 propagates automatically.
# No change needed here.
```

Fallback to local currency when USD is null preserves behavior for single-currency portfolios where USD might not be computed.

Keep flag messages currency-neutral — since we fall back to local currency when USD is null, we can't hardcode "$". Leave existing message text as-is:
- Line 40: keep `f"Negative expectancy: losing {abs(expectancy):.0f} per trade on average"` (no "$")
- Line 51: change "in dollar terms" to "in absolute terms" to be currency-neutral

### File: `tests/core/test_trading_flags.py`

Update `_base_snapshot()` to include USD fields:
```python
"performance": {
    "expectancy": 12.0,
    "expectancy_usd": 12.0,
    "profit_factor": 1.4,
    "profit_factor_usd": 1.4,
},
```

Update test cases to set USD fields:
- `test_negative_expectancy_flag`: set `expectancy_usd` = -5.0
- `test_low_profit_factor_flag`: set `profit_factor_usd` = 0.8
- `test_strong_profit_factor` (line ~157): set `profit_factor_usd` = 2.5 (matching the local value)
- Add fallback tests (USD null, local currency triggers):
  - `expectancy_usd` = None, `expectancy` = -5.0 → should still trigger `negative_expectancy`
  - `profit_factor_usd` = None, `profit_factor` = 0.8 → should still trigger `low_profit_factor`

## Files Changed

| File | Change |
|------|--------|
| `core/trading_flags.py` | Read `expectancy_usd`/`profit_factor_usd` with local currency fallback |
| `tests/core/test_trading_flags.py` | Update snapshot + test cases with USD fields |

## Verification

1. Run `pytest tests/core/test_trading_flags.py -v`
2. Browser: Performance → Trading P&L card — confirm flag messages now agree with the card metrics (both USD)
