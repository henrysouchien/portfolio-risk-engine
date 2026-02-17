# Plan: USD-Normalize Trading P&L

**Status:** IMPLEMENTED

## Context
`to_summary()` and `to_cli_report()` rank top winners/losers by `pnl_dollars` which is in **original currency**. MHI futures trading in HKD shows -$30,664 HKD as the top loser, but that's only ~$3,930 USD. Rankings and totals need USD normalization for cross-currency comparability.

## Approach
Add `pnl_dollars_usd` field to `TradeResult`, computed at creation time using spot FX rates via `get_spot_fx_rate()` from `fmp/fx.py`. Applied in **both** `_analyze_trades_fifo()` and `_analyze_trades_averaged()` paths.

**Why spot rate:** Only 3 of 84 trades are non-USD (all HKD). Building exit-date FX series adds complexity for minimal accuracy gain. `get_spot_fx_rate()` is simple, `@lru_cache`'d, and good enough for ranking.

## Step 1: Add `pnl_dollars_usd` to `TradeResult`

**File:** `trading_analysis/models.py`

Add field in the **defaulted section** (after line 277, alongside `num_buys`, `num_sells`):
```python
pnl_dollars_usd: float = 0.0  # USD-normalized P&L
```
This avoids the dataclass "non-default follows default" error — `pnl_dollars_usd` goes after the existing defaulted fields.

Update `to_dict()` to include `'pnl_dollars_usd': round(self.pnl_dollars_usd, 2)`.

## Step 2: Compute USD P&L in both analyzer paths

**File:** `trading_analysis/analyzer.py`

Add a private helper (module-level or on `TradingAnalyzer`):
```python
def _build_fx_rates(closed_trades_or_results) -> Dict[str, float]:
    """Build {currency: fx_rate} for all unique non-USD currencies. Always uppercase."""
    from fmp.fx import get_spot_fx_rate
    currencies = {
        (t.currency or 'USD').upper()
        for t in closed_trades_or_results
        if (t.currency or 'USD').upper() != 'USD'
    }
    rates = {'USD': 1.0}
    for ccy in currencies:
        try:
            rates[ccy] = get_spot_fx_rate(ccy)
        except Exception:
            trading_logger.warning(f"FX lookup failed for {ccy}; treating as 1.0")
            rates[ccy] = 1.0
    return rates
```

Apply in **both** paths:
- `_analyze_trades_fifo()` (line 1089): after `result.closed_trades`, build `fx_rates`, then set `pnl_dollars_usd` on each `TradeResult`
- `_analyze_trades_averaged()` (line 1132): same pattern — build `fx_rates` from trade results, set `pnl_dollars_usd`. Note: averaged mode hardcodes `currency='USD'` so all rates will be 1.0 — this is correct behavior, and the code path is covered for completeness.

**Currency normalization:** Always `.upper()` the currency string before lookup to prevent case drift.

## Step 3: Update `to_summary()` — sort by USD

**File:** `trading_analysis/models.py` (line 655)

- Sort `top_winners`/`top_losers` by `pnl_dollars_usd` instead of `pnl_dollars`
- In `_trade_brief()`: always include `pnl_dollars_usd`; add `currency` field
- Add `total_trading_pnl_usd` to response (sum of `pnl_dollars_usd`)
- Keep `total_trading_pnl` unchanged (original mixed-currency sum) for backward compat

## Step 4: Update `to_api_response()`

**File:** `trading_analysis/models.py` (line 606)

- Add `total_trading_pnl_usd` field alongside existing `total_trading_pnl`
- `to_dict()` already updated in Step 1

## Step 5: Update `to_cli_report()` — show USD for non-USD trades

**File:** `trading_analysis/models.py` (line 696)

In TOP WINNERS / TOP LOSERS sections:
- Sort by `pnl_dollars_usd`
- Non-USD: `MHI: $9,136.00 HKD ($1,172.31 USD) (+4.0%)`
- USD: unchanged display

## Step 6: Fallback for `pnl_dollars_usd` default value

Since `pnl_dollars_usd` defaults to `0.0`, any `TradeResult` constructed outside the analyzer (e.g., test fixtures) would sort incorrectly. **Resolution:** In `to_summary()` and `to_cli_report()`, use a sort key that falls back to `pnl_dollars` when `pnl_dollars_usd == 0.0`:
```python
key=lambda t: t.pnl_dollars_usd if t.pnl_dollars_usd != 0.0 else t.pnl_dollars
```
Also update the test fixture helper `_make_trade()` in `test_result_serialization.py` to set `pnl_dollars_usd=pnl_dollars` (since all test fixtures are USD).

## Step 7: Do NOT change `total_trading_pnl` in `run_full_analysis()`

Keep `total_trading_pnl = sum(t.pnl_dollars for t in trade_results)` as-is (original mixed-currency). The CLI `_print_summary()` in `run_trading_analysis.py` uses this with per-currency labels (line 63-69) — changing it to USD would mislabel single-currency totals.

Instead, the USD-normalized total is computed on-demand in `to_summary()` and `to_api_response()` as `total_trading_pnl_usd`.

## Step 8: Update existing tests

**File:** `tests/trading_analysis/test_result_serialization.py`

- Update `_make_trade()` helper to set `pnl_dollars_usd=pnl_dollars` (all test fixtures are USD)
- Update key-set assertions to include `pnl_dollars_usd` in `TradeResult.to_dict()`, `to_summary()`, `to_api_response()`

## Step 9: New tests

**New file:** `tests/trading_analysis/test_usd_normalization.py`

- `test_usd_trades_pnl_usd_equals_pnl`: USD trades → `pnl_dollars_usd == pnl_dollars`
- `test_non_usd_trades_converted`: HKD trade → `pnl_dollars_usd = pnl * fx_rate`
- `test_top_winners_sorted_by_usd`: Mixed-currency sorting uses USD
- `test_summary_includes_usd_fields`: `to_summary()` has `total_trading_pnl_usd`
- `test_fx_failure_defaults_to_1`: Missing FX → fallback to 1.0

## Files to modify
| Action | File | Changes |
|--------|------|---------|
| Edit | `trading_analysis/models.py` | Add `pnl_dollars_usd` field (defaulted section), update `to_dict()`, `to_summary()`, `to_api_response()`, `to_cli_report()` |
| Edit | `trading_analysis/analyzer.py` | Add `_build_fx_rates()`, apply in both `_analyze_trades_fifo()` and `_analyze_trades_averaged()` |
| Edit | `tests/trading_analysis/test_result_serialization.py` | Update key-set assertions for new fields |
| New | `tests/trading_analysis/test_usd_normalization.py` | 5 tests |

## Verification
1. `python -m pytest tests/trading_analysis/test_usd_normalization.py -v`
2. `python -m pytest tests/trading_analysis/test_result_serialization.py -v` (existing tests still pass)
3. MCP test: `get_trading_analysis(source='all', format='summary')` — MHI should rank lower
4. CLI test: `python run_trading_analysis.py --source ibkr_flex` — non-USD trades show `HKD ($X USD)`
