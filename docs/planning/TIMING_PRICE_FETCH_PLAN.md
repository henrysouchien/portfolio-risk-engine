# Timing Analysis — FMP Price Fetch Integration

## Context

Timing grade is always N/A because `analyze_timing()` only uses transaction prices. Without historical market high/low during holding periods, it can't measure exit quality. The FMP infrastructure for daily OHLCV fetching already exists in the codebase.

## Approach

Rewrite `analyze_timing()` to operate on **round-trips** (not raw trades), fetch **daily OHLCV from FMP** via the compat layer for each round-trip's holding period, and compute timing score as exit price vs the best available price.

### Key design decisions:
- Use **round-trips** as the unit of analysis (consistent with other v2 grades)
- Use **`FMPClient.fetch("historical_price_eod")` + `_index_fmp_history_frame()`** for date-indexed OHLCV DataFrame. Verified: FMP returns `open/high/low/close/volume` columns regardless of `serietype` default. Apply minor-unit normalization via `_minor_currency_divisor_for_symbol()` from `fmp/compat.py` for LSE pence etc.
- **Skip symbols** where FMP data is unavailable — no fallback to transaction prices (avoids mixing real and fake scores)
- **Only equity-like symbols** — exclude options, futures, bonds, fx (FMP doesn't have option/futures contract history)

## Implementation

### Rewrite `analyze_timing()` in `trading_analysis/analyzer.py`

**New signature:**
```python
def analyze_timing(self, round_trips: list[RoundTrip]) -> list[TimingResult]:
```

**Logic:**

1. Filter round-trips to equity-like longs only:
```python
equity_types = {"equity", "unknown"}  # mutual_fund excluded (existing behavior preserved)
eligible_rts = [
    rt for rt in round_trips
    if not rt.synthetic
    and rt.direction == "LONG"  # shorts excluded — timing formula inverts for shorts
    and rt.instrument_type in equity_types  # RoundTrip already carries instrument_type
]
```

2. Group by `(symbol, currency)` — multi-currency listings get separate price fetches:
```python
by_key: dict[tuple[str, str], list[RoundTrip]] = defaultdict(list)
for rt in eligible_rts:
    by_key[(rt.symbol, rt.currency)].append(rt)
```

3. For each symbol, fetch OHLCV:
```python
from fmp.compat import _index_fmp_history_frame, _minor_currency_divisor_for_symbol
from fmp.client import get_client

client = get_client()
symbol, currency = key

# FMP ticker resolution: use resolve_fmp_ticker() already imported in analyzer.
# It handles US tickers (returned as-is), international tickers (suffix added via
# exchange MIC or FMP search), and caches results.
company_name = self._get_company_name(symbol)  # existing cached FMP name lookup
# No exchange_mic available on RoundTrip — resolver falls back to name+currency
# search for international symbols. This is slower but still works. Adding MIC
# to the FIFO pipeline would improve resolution but is out of scope for this plan.
fmp_ticker = resolve_fmp_ticker(symbol, company_name=company_name, currency=currency)

# Date range covers all round-trips for this (symbol, currency) key
all_entries = [rt.entry_date for rt in rts]
all_exits = [rt.exit_date for rt in rts]
from_date = min(all_entries).strftime("%Y-%m-%d")
to_date = max(all_exits).strftime("%Y-%m-%d")

try:
    df = client.fetch("historical_price_eod", symbol=fmp_ticker, **{"from": from_date, "to": to_date})
    if df is None or df.empty or "date" not in df.columns:
        continue  # skip this symbol

    df = _index_fmp_history_frame(df)  # DatetimeIndex

    # Minor-unit normalization (e.g., LSE pence → pounds)
    divisor = _minor_currency_divisor_for_symbol(fmp_ticker)
    if divisor != 1.0:
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = df[col] / divisor
except Exception:
    continue  # skip on any fetch error
```

4. For each round-trip in this symbol, compute timing:
```python
for rt in rts:
    # Slice to holding period — use pd.Timestamp for DatetimeIndex comparison
    start_ts = pd.Timestamp(rt.entry_date.date())
    end_ts = pd.Timestamp(rt.exit_date.date())
    period_df = df.loc[start_ts:end_ts]  # DatetimeIndex slice (inclusive)

    if period_df.empty or "high" not in period_df.columns or "low" not in period_df.columns:
        continue  # skip this round-trip

    best_price = float(period_df["high"].max())
    worst_price = float(period_df["low"].min())

    # Use avg_exit_price for timing score. For multi-exit round-trips (scaled out),
    # this is the quantity-weighted average exit. This is an approximation — ideally
    # we'd score each exit against the high up to that exit date. But for v1, the
    # weighted average is a reasonable summary of overall exit quality.
    exit_price = rt.avg_exit_price

    timing_score = calculate_timing_score(exit_price, best_price, worst_price)
    regret_dollars = (best_price - exit_price) * rt.total_quantity if best_price > exit_price else 0

    # Compute P&L scenarios for TimingResult fields
    qty = rt.total_quantity
    entry_price = rt.avg_entry_price
    actual_pnl = (exit_price - entry_price) * qty
    best_case_pnl = (best_price - entry_price) * qty
    worst_case_pnl = (worst_price - entry_price) * qty
    best_price_date = str(period_df["high"].idxmax().date()) if not period_df.empty else ""

    timing_results.append(TimingResult(
        symbol=symbol,
        currency=currency,
        avg_buy_price=entry_price,
        actual_sell_price=exit_price,
        best_possible_price=best_price,
        worst_possible_price=worst_price,
        actual_pnl=actual_pnl,
        best_case_pnl=best_case_pnl,
        worst_case_pnl=worst_case_pnl,
        regret_dollars=regret_dollars,
        timing_score=timing_score,
        sell_date=str(rt.exit_date.date()),
        best_price_date=best_price_date,
    ))
```

**Note on multi-exit approximation:** Using avg_exit_price against full-window max can overstate regret when some exits were at good prices and later exits were at bad prices. This is a known v1 limitation. Per-exit timing would be more accurate but requires lot-level analysis within each round-trip, which we may add later.

**Exit price derivation:** RoundTrip has `proceeds` and `cost_basis` but not a direct `exit_price`. Options:
- A: Add `avg_exit_price` field to RoundTrip (computed in `from_lots()` as weighted avg of lot exit prices)
- B: Use `proceeds / quantity` where quantity = sum of lot quantities
- C: Pass the last ClosedTrade's exit_price

**Recommendation:** Option A — add `avg_exit_price` and `avg_entry_price` to RoundTrip. Clean and reusable.

### Add `avg_exit_price` and `avg_entry_price` to RoundTrip

**File:** `trading_analysis/fifo_matcher.py`

Add to RoundTrip dataclass (with defaults so existing test constructors don't break):
```python
total_quantity: float = 0.0   # sum of lot quantities
avg_entry_price: float = 0.0  # weighted avg entry price across lots
avg_exit_price: float = 0.0   # weighted avg exit price across lots
```

In `from_lots()`:
```python
total_qty = sum(lot.quantity for lot in lots)
avg_entry_price = sum(lot.entry_price * lot.quantity for lot in lots) / total_qty if total_qty > 0 else 0
avg_exit_price = sum(lot.exit_price * lot.quantity for lot in lots) / total_qty if total_qty > 0 else 0
```

`total_quantity` is needed by timing analysis to compute `regret_dollars = (best_price - exit_price) * total_quantity`.

### FMP ticker resolution

Uses `resolve_fmp_ticker(symbol, company_name, currency)` already imported in the analyzer. For US equities, returns symbol as-is. For international, searches by name+currency (no exchange_mic available on RoundTrip — documented limitation). Cached via `_RESOLUTION_CACHE` in ticker_resolver.py.

### Wire into `run_full_analysis()`

```python
# After round-trip aggregation:
timing_results = self.analyze_timing(round_trips)
avg_timing = (
    sum(r.timing_score for r in timing_results) / len(timing_results)
    if timing_results else None
)
# Count distinct (symbol, currency) keys, not round-trips
timing_symbol_count = len({(r.symbol, r.currency) for r in timing_results})
timing_grade = compute_timing_grade(avg_timing, timing_symbol_count=timing_symbol_count)
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| FMP ticker not found | Skip symbol, no timing result |
| FMP fetch error (rate limit, 402, network) | Skip symbol, log warning |
| Empty DataFrame | Skip symbol |
| No high/low columns | Skip symbol |
| best_price == worst_price (flat period) | timing_score = 50 (neutral, already in calculate_timing_score) |
| < 3 symbols with timing data | Timing grade = N/A (existing threshold) |

No fallback to transaction prices. If market data is unavailable, the symbol is excluded from timing scoring entirely.

**Short positions:** Excluded from timing for now. For shorts, "optimal exit" is the period LOW (buy to cover cheaply), which inverts the standard timing formula. Adding short timing support requires a separate formula path. Deferred — most retail portfolios are primarily long.

**`use_fifo=False` (averaged mode):** No round-trips available, so timing returns empty (grade N/A). This is consistent with Edge/Sizing/Discipline which are also N/A in averaged mode. Averaged mode is legacy, not used in production.

**Multi-currency regret:** `regret_dollars` is computed per round-trip in local currency. The aggregate `total_regret` in the snapshot sums these — for mixed-currency portfolios this is an approximation. Acceptable for v1 since FX conversion for regret would add complexity without much value (regret is directional, not precise).

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/analyzer.py` | Rewrite `analyze_timing()` to use round-trips + FMP OHLCV |
| `trading_analysis/fifo_matcher.py` | Add `total_quantity`, `avg_entry_price`, `avg_exit_price` (all defaulted) to RoundTrip, compute in `from_lots()` |
| `trading_analysis/models.py` | Add `currency: str = "USD"` field to `TimingResult` (defaulted). Add `currency` to `TimingResult.to_dict()`. Update `get_agent_snapshot()` timing_symbol_count to use `len({(r.symbol, r.currency) for r in self.timing_results})` |
| `trading_analysis/main.py` | Guard `avg_timing_score` formatting against None. Also update hand-built `timing_analysis` rows (~line 154) to include `currency` field (doesn't use TimingResult.to_dict()). |
| `tests/trading_analysis/test_analyzer_mutual_funds.py` | Update `analyze_timing()` monkeypatches for new signature |
| `tests/trading_analysis/test_scorecard_v2.py` | Add new fields to RoundTrip construction (total_quantity, avg_entry_price, avg_exit_price — use defaults), update `analyze_timing` monkeypatches for new signature, update `use_fifo=False` test to expect timing N/A |
| `tests/trading_analysis/test_analyzer_mutual_funds.py` | Rewrite timing-related tests — current tests assert self.trades swap/filter behavior which changes with round-trip-based analyze_timing(). Update monkeypatches and assertions. |

## Tests

**File:** `tests/trading_analysis/test_scorecard_v2.py` (add timing tests)

- Mock FMPClient.fetch to return OHLCV DataFrame → timing scores computed correctly
- Mock FMPClient.fetch to return None → symbol skipped, no crash
- Mock FMPClient.fetch to raise → symbol skipped gracefully
- Options/futures round-trips excluded from timing
- < 3 symbols with data → timing grade N/A
- best_price == worst_price → score 50
- Round-trip avg_exit_price used correctly (not transaction-level)
- Regret dollars uses total_quantity from RoundTrip
- Snapshot: 2 round-trips for same (symbol, currency) → timing_symbol_count == 1 (distinct keys)
- Snapshot: same symbol different currencies → timing_symbol_count == 2

## Verification

1. `pytest tests/trading_analysis/ -v` — all tests pass
2. MCP: `get_trading_analysis(format="agent")` — `timing_symbol_count > 0` for equity-heavy portfolio
3. Live: timing grade shows a letter grade instead of N/A
