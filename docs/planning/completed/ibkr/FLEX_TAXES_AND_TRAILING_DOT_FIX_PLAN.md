# Realized Performance Data Quality: Flex Taxes + Trailing-Dot Pricing

**Date**: 2026-03-07
**Status**: Complete (commit `867b46fd`)

## Context

Two data quality gaps identified while comparing engine output vs IBKR broker statements:

1. **Missing transaction taxes ($11)**: IBKR Flex Trade XML has a `taxes` field (UK Stamp Tax, SEC fees) that we ignore. We only extract `ibCommission`. The IBKR statement shows $11 in transaction taxes unaccounted for.

2. **AT. unpriceable ($0 NAV impact)**: Ashtead Technology (LSE) shows as unpriceable because stale cached position data has `AT.` (trailing dot) as the ticker. The `fmp_ticker_map` gets built with key `"AT."` and value `"AT..L"` (double dot — invalid FMP symbol). Even with fresh data post trailing-dot fix (commit `14d88dd9`), there's no defensive strip in the holdings builder or pricing layer to prevent this class of issue.

Both fixes are independent and low-risk.

## Fix 1: Add `taxes` to Fee Extraction

**File**: `ibkr/flex.py:357-362`

Change fee calculation from:
```python
fee = abs(
    safe_float(
        _get_attr(trade, "ibCommission", "commission", "commissionAmount"),
        0.0,
    )
)
```

To:
```python
fee = abs(
    safe_float(
        _get_attr(trade, "ibCommission", "commission", "commissionAmount"),
        0.0,
    )
) + abs(
    safe_float(
        _get_attr(trade, "taxes"),
        0.0,
    )
)
```

**Why safe**: Missing `taxes` attribute → `_get_attr` returns `None` → `safe_float(None, 0.0)` → `0.0`. All existing tests pass unchanged because `_flex_trade()` helper doesn't include `taxes`, so `abs(0.0)` is added.

**Verified from Flex data**:
| Trade | ibCommission | taxes | Total Fee (current) | Total Fee (after) |
|-------|-------------|-------|--------------------|--------------------|
| AT. BUY 300 | -3.00 GBP | -6.00 GBP | 3.00 | 9.00 |
| AT. BUY 100 | -3.00 GBP | -2.08 GBP | 3.00 | 5.08 |

**Tests** (in `tests/ibkr/test_flex.py`, after `test_fee_sign_normalization` at line 145):

1. `test_fee_includes_taxes` — trade with `ibCommission=-3.21, taxes=-1.50` → `fee == 4.71`
2. `test_fee_with_zero_taxes` — trade with `taxes=0.0` → fee unchanged
3. `test_fee_with_missing_taxes` — trade without `taxes` attr → fee unchanged (documents contract)

### Existing tests that must NOT break
- `test_fee_sign_normalization` (line 143) — creates trade with `ibCommission=-3.21` and no `taxes`. After change: `fee = 3.21 + 0.0 = 3.21`. Passes unchanged.
- All other `test_normalize_flex_trades_*` tests — `_flex_trade()` helper doesn't include `taxes`, so `_get_attr(trade, "taxes")` returns `None`, `safe_float(None, 0.0)` returns `0.0`. No impact.

## Fix 2: Trailing-Dot Strip — Two Layers

### Fix 2a: Input layer — Holdings Builder

**File**: `core/realized_performance/holdings.py:83-86`

After existing validation, add strip:
```python
ticker = pos.get("ticker")
if not ticker or not isinstance(ticker, str):
    continue
ticker = ticker.rstrip(".")       # ADD — defensive strip
if not ticker:                     # ADD — guard all-dot tickers
    continue                       # ADD
```

This fixes the position dict key (`current_positions["AT"]` not `"AT."`) and the
`fmp_ticker_map` KEY (map lookup uses `"AT"` not `"AT."`). Note: the map VALUE
comes from `pos.get("fmp_ticker")` verbatim — if stale cached data has
`fmp_ticker="AT..L"`, this strip does NOT fix the value. The one-time fix for
stale values is `use_cache=False`; this strip prevents future key mismatches.

`rstrip(".")` is idempotent: `"BRK.B"` → `"BRK.B"`, `"AT.L"` → `"AT.L"` (only trailing dots removed). Pattern already used in 6 other locations:
- `ibkr/flex.py:339`
- `snaptrade_loader.py:928`
- `utils/ticker_resolver.py:196`

**Tests** (in `tests/core/test_realized_performance_analysis.py`, follow pattern from `test_build_current_positions_marks_cost_basis_provenance` at line 2274):

1. `test_build_current_positions_strips_trailing_dot` — position with `ticker="AT."`, `fmp_ticker="AT.L"` → key is `"AT"`, map has `"AT" → "AT.L"`, `"AT."` not in either
2. `test_build_current_positions_preserves_internal_dots` — positions with `ticker="BRK.B"` and `ticker="AT.L"` → keys preserved unchanged
3. `test_build_current_positions_skips_all_dot_ticker` — position with `ticker="..."` → skipped entirely (not in current_positions)

### Fix 2b: Provider layer — `select_fmp_symbol()` safety net (BOTH copies)

There are two `select_fmp_symbol()` functions. Both need the strip:

**File 1**: `utils/ticker_resolver.py:73-86` — used by the realized perf pricing
path via `fmp/compat.py:303`. This is the PRIMARY path.

**File 2**: `portfolio_risk_engine/_ticker.py:19-31` — used by `portfolio_risk_engine/data_loader.py`
and `portfolio_risk_engine/_fmp_provider.py`. Secondary path.

Add defensive strip at the top of both:
```python
def select_fmp_symbol(
    ticker: str,
    *,
    fmp_ticker: Optional[str] = None,
    fmp_ticker_map: Optional[dict[str, str]] = None,
) -> str:
    ticker = ticker.rstrip(".")    # ADD — defensive strip
    if fmp_ticker:
        return fmp_ticker
    if fmp_ticker_map and ticker in fmp_ticker_map:
        ...
```

This ensures that even if a trailing-dot ticker reaches the pricing layer, the
map lookup uses the clean key. Idempotent: `"BRK.B".rstrip(".")` = `"BRK.B"`.

**Note on stale `fmp_ticker` values**: If cached position data predates the
trailing-dot fix (commit `14d88dd9`), the `fmp_ticker` value may be `"AT..L"`
(double dot). Stripping the lookup KEY doesn't fix a bad VALUE. The one-time
fix is `use_cache=False` to force a fresh SnapTrade position load where
`resolve_fmp_ticker()` (which already strips at `ticker_resolver.py:196`)
produces the correct `"AT.L"`. The defensive strips here prevent future
occurrences, not stale cache artifacts.

**Tests** (in `tests/utils/test_ticker_resolver.py`, create if needed):

1. `test_select_fmp_symbol_strips_trailing_dot` — `select_fmp_symbol("AT.", fmp_ticker_map={"AT": "AT.L"})` → `"AT.L"`
2. `test_select_fmp_symbol_preserves_internal_dots` — `select_fmp_symbol("BRK.B")` → `"BRK.B"`

## Key Files
- `ibkr/flex.py:357-362` — taxes extraction (Fix 1)
- `tests/ibkr/test_flex.py:14-31, 143-145` — test helper + existing fee test (Fix 1)
- `core/realized_performance/holdings.py:83-86` — trailing-dot strip input layer (Fix 2a)
- `utils/ticker_resolver.py:73-86` — trailing-dot strip provider layer, PRIMARY (Fix 2b)
- `portfolio_risk_engine/_ticker.py:19-31` — trailing-dot strip provider layer, SECONDARY (Fix 2b)
- `tests/core/test_realized_performance_analysis.py:2274+` — test pattern (Fix 2a)

## Verification

### Unit tests
```bash
pytest tests/ibkr/test_flex.py -x -v
pytest tests/core/test_realized_performance_analysis.py -x -v -k "build_current_positions or fee"
pytest tests/utils/test_ticker_resolver.py -x -v -k "select_fmp_symbol"
```

### Live test
```
get_performance(mode="realized", institution="ibkr", format="summary", use_cache=False)
```
- AT. should no longer appear in `unpriceable_symbols`
- `unpriceable_symbol_count` should drop from 1 to 0
- Fees should be slightly higher (capturing $11 in taxes)

## Not in Scope
- PortfolioService cache invalidation (use_cache=False sufficient)
- Other Flex fee fields beyond `taxes` (none identified)
- Transaction store persistence of taxes (inherits from existing fee field)
- Broader symbol normalization refactor (these defensive strips are sufficient)
